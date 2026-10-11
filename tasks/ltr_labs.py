#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import traceback

from core.appliance_client import ApplianceClient
from core.appliance_config_loader import ApplianceConfigLoader
from core.appliance_operations import (
    _get_appliance_connection_params,
    setup_appnode as _setup_appnode,
)
from core.guardium_rest_api import import_definitions_files
from core.logger import get_logger
import secrets
from core.utils import execute_local_command, write_file

logger = get_logger(__name__)

def _header(logger, title: str) -> None:
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)

def _require(logger, **kwargs) -> bool:
    for name, value in kwargs.items():
        if not value:
            logger.error(f"{name} is required")
            return False
    return True

def setup_seaweedfs_on_raptor(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, "SETUP SEAWEEDFS ON RAPTOR")

    raptor_ip = config.get_machine_ip("raptor", use_private=True)
    if not raptor_ip:
        logger.error("Could not determine raptor IP address")
        return False

    pwd = config.get_custom_variable("pwd")
    if not _require(logger, pwd=pwd):
        return False

    cert_cmds = [
        "mkdir -p /opt/seaweedfs/{data,certs,nginx}",
        "mkdir -p /opt/seaweedfs/certs/ca",
        "openssl genrsa -out /opt/seaweedfs/certs/ca/ca.key 4096",
        'openssl req -x509 -new -nodes -key /opt/seaweedfs/certs/ca/ca.key -sha256 -days 3650 -subj "/CN=seaweedFS-Root-CA" -out /opt/seaweedfs/certs/ca/ca.crt',
        "cp /opt/seaweedfs/certs/ca/ca.crt /etc/pki/ca-trust/source/anchors/",
        "update-ca-trust",
        "openssl genrsa -out /opt/seaweedfs/certs/tls.key 4096 && chmod 600 /opt/seaweedfs/certs/tls.key",
        f'openssl req -new -key /opt/seaweedfs/certs/tls.key -out /opt/seaweedfs/seaweedfs.csr -subj "/CN=seaweedfs.demo.guardium" -addext "subjectAltName=DNS:raptor.demo.guardium,IP:{raptor_ip}"',
        "openssl x509 -req -in /opt/seaweedfs/seaweedfs.csr -CA /opt/seaweedfs/certs/ca/ca.crt -CAkey /opt/seaweedfs/certs/ca/ca.key -CAcreateserial -out /opt/seaweedfs/certs/tls.crt -days 3600 -sha256 -copy_extensions copy",
        "cat /opt/seaweedfs/certs/tls.crt /opt/seaweedfs/certs/ca/ca.crt > /opt/seaweedfs/certs/fullchain.crt",
        "chmod 644 /opt/seaweedfs/certs/*",
        "chmod 600 /opt/seaweedfs/certs/tls.key /opt/seaweedfs/certs/ca/ca.key",
        "chcon -Rt container_file_t /opt/seaweedfs",
    ]
    for cmd in cert_cmds:
        result = execute_local_command(cmd, logger=logger, verbose=verbose)
        if result["rc"] != 0:
            logger.error(f"✗ Failed: {cmd}\n{result['stderr']}")
            return False
    logger.info("✓ SeaweedFS certificates prepared")

    jwt_key = secrets.token_hex(32)
    files = {
        "/opt/seaweedfs/nginx/nginx.conf": NGINX_CONF,
        "/opt/seaweedfs/s3.json": S3_JSON_TEMPLATE.format(pwd=pwd),
        "/opt/seaweedfs/security.toml": (
            f'[jwt.filer_signing]\nkey = "{jwt_key}"\n\n'
            f'[jwt.filer_signing.read]\nkey = "{jwt_key}"\n'
        ),
        "/etc/systemd/system/seaweedfs-stack.service": SEAWEEDFS_SERVICE,
    }
    for path, content in files.items():
        try:
            write_file(path, content)
            logger.info(f"✓ {path} created")
        except Exception as e:
            logger.error(f"✗ Failed to create {path}: {e}")
            return False

    perms_cmds = [
        "chmod 644 /opt/seaweedfs/nginx/nginx.conf",
        "chmod 644 /opt/seaweedfs/s3.json",
        "chmod 644 /opt/seaweedfs/security.toml",
        "chcon -t container_file_t /opt/seaweedfs/nginx/nginx.conf",
        "chcon -t container_file_t /opt/seaweedfs/s3.json",
        "chcon -t container_file_t /opt/seaweedfs/security.toml",
        "firewall-cmd --permanent --add-port=8333/tcp",
        "firewall-cmd --reload",
        "systemctl daemon-reload",
        "systemctl enable --now seaweedfs-stack",
        "systemctl start seaweedfs-stack",
    ]
    for cmd in perms_cmds:
        result = execute_local_command(cmd, logger=logger, verbose=verbose)
        if result["rc"] != 0:
            logger.error(f"✗ Failed: {cmd}\n{result['stderr']}")
            return False
    logger.info("✓ Permissions set, firewall opened, service started")

    logger.info("⌛ Waiting 30s for service to stabilize...")
    time.sleep(30)

    verify_cmd = (
        "openssl s_client -connect raptor.demo.guardium:8333 -servername raptor.demo.guardium"
        " </dev/null 2>/dev/null"
        ' | openssl x509 -noout -text | grep -E "(Issuer:|Subject:|Not After|DNS:|IP Address:)"'
    )
    result = execute_local_command(verify_cmd, logger=logger, verbose=verbose)
    if result["rc"] != 0:
        logger.error(f"✗ TLS verification failed\n{result['stderr']}")
        return False
    logger.info(f"✓ TLS certificate verified:\n{result['stdout']}")

    return True

SEAWEEDFS_SERVICE = """\
[Unit]
Description=SeaweedFS S3 + Nginx TLS Proxy Stack
After=network-online.target
Wants=network-online.target

[Service]
Restart=always
TimeoutStartSec=120

ExecStartPre=-/usr/bin/podman pod rm -f seaweedfs-pod
ExecStartPre=/usr/bin/podman pod create --name seaweedfs-pod -p 8333:8333 -p 9333:9333

ExecStartPre=/usr/bin/podman run -d --pod seaweedfs-pod --name seaweedfs-server \\
  -v /opt/seaweedfs/data:/data:z \\
  -v /opt/seaweedfs/s3.json:/etc/seaweedfs/s3.json:ro,z \\
  -v /opt/seaweedfs/security.toml:/etc/seaweedfs/security.toml:ro,z \\
  docker.io/chrislusf/seaweedfs:latest server -dir=/data -filer -s3 -s3.port=8332 -s3.iam.config=/etc/seaweedfs/s3.json

ExecStartPre=/usr/bin/sleep 2

ExecStart=/usr/bin/podman run --rm --pod seaweedfs-pod --name seaweedfs-proxy \\
  -v /opt/seaweedfs/nginx/nginx.conf:/etc/nginx/nginx.conf:ro,z \\
  -v /opt/seaweedfs/certs:/etc/nginx/certs:ro,z \\
  docker.io/library/nginx:alpine nginx -g "daemon off;"

ExecStop=/usr/bin/podman pod stop seaweedfs-pod
ExecStopPost=/usr/bin/podman pod rm -f seaweedfs-pod

[Install]
WantedBy=multi-user.target
"""

S3_JSON_TEMPLATE = """\
{{
  "identities": [
    {{
      "name": "s3admin",
      "credentials": [
        {{
          "accessKey": "s3admin",
          "secretKey": "{pwd}"
        }}
      ],
      "actions": [
        "Admin",
        "Read",
        "Write",
        "List"
      ]
    }}
  ]
}}
"""

NGINX_CONF = """\
events {
    worker_connections 1024;
}

http {
    upstream seaweedfs_s3 {
        server 127.0.0.1:8332;
    }

    server {
        listen 8333 ssl;
        server_name raptor.demo.guardium _;

        ssl_certificate /etc/nginx/certs/fullchain.crt;
        ssl_certificate_key /etc/nginx/certs/tls.key;

        # Zwiększenie limitu uploadu dla S3
        client_max_body_size 0;

        location / {
            proxy_pass http://seaweedfs_s3;
            proxy_set_header Host $http_host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Wymagane dla streamingu dużych plików S3
            proxy_http_version 1.1;
            proxy_request_buffering off;
        }
    }
}
"""

def setup_appnode(
    config,
    logger,
    verbose: bool = False,
    appliance_name: str = None,
    retry_interval: int = 60,
    max_retries: int = 10,
    debug: bool = False,
    **kwargs) -> bool:

    if not _require(logger, appliance_name=appliance_name):
        return False
    return _setup_appnode(
        config=config, logger=logger,
        appliance_name=appliance_name,
        retry_interval=retry_interval, max_retries=max_retries,
        debug=debug,
    )

def enable_ltr_on_appnode(
    config,
    logger,
    verbose: bool = False,
    appliance_name: str = None,
    debug: bool = False,
    **kwargs) -> bool:

    if not _require(logger, appliance_name=appliance_name):
        return False

    _header(logger, f"ENABLE LTR ON APPNODE: {appliance_name}")

    params = _get_appliance_connection_params(config, logger, appliance_name)
    if not params:
        return False

    try:
        client = ApplianceClient(
            host=params['host'], user=params['user'], password=params['password'],
            prompt_regex=params['prompt_regex'],
            initial_pattern=None, timeout=300, strip_ansi=True, debug=debug,
        )
        if not client.connect():
            logger.error(f"Failed to connect to {appliance_name}")
            return False

        steps = [
            ("store datalake install",       "Datalake installation was successful",       "install datalake"),
            ("store datalake all_in_one xxsmall", "Datalake all_in_one was brought up correctly", "configure all_in_one"),
        ]
        try:
            for cmd, expected, desc in steps:
                logger.info(f"➜ {cmd}")
                result = client.execute_command(cmd, timeout=300)
                if expected not in result:
                    logger.error(f"✗ Failed to {desc}: {result}")
                    return False
                logger.info(f"✓ {desc}")

            logger.info("➜ store datalake service start")
            client.execute_command("store datalake service start", timeout=300)

            for attempt in range(1, 11):
                logger.info(f"➜ show datalake status (attempt {attempt}/10)")
                status = client.execute_command("show datalake status", timeout=60)
                logger.info(f"  {status.strip()}")
                if "Datalake is running" in status:
                    logger.info("✓ Datalake is running")
                    return True
                if attempt < 10:
                    logger.info("⌛ Datalake still starting, waiting 30s...")
                    time.sleep(30)

            logger.error(f"✗ Datalake is not running after 10 attempts: {status}")
            return False

        finally:
            client.disconnect()

    except Exception as e:
        logger.error(f"✗ Error enabling LTR on appnode: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False

def import_minio_CA_certificate(
    config,
    logger,
    verbose: bool = False,
    appliance_name: str = None,
    certificate_file_path: str = "/home/minio/ca/certs/ca.crt",
    debug: bool = False,
    **kwargs) -> bool:

    if not _require(logger, appliance_name=appliance_name):
        return False

    _header(logger, f"IMPORT DATALAKE S3 CERTIFICATE: {appliance_name}")

    try:
        with open(certificate_file_path, 'r') as f:
            cert_content = f.read()
        if not cert_content or 'BEGIN CERTIFICATE' not in cert_content:
            logger.error("Invalid certificate content")
            return False
        logger.info(f"✓ Certificate read from {certificate_file_path}")
    except FileNotFoundError:
        logger.error(f"Certificate file not found: {certificate_file_path}")
        return False
    except Exception as e:
        logger.error(f"Error reading certificate file: {e}")
        return False

    params = _get_appliance_connection_params(config, logger, appliance_name)
    if not params:
        return False

    try:
        client = ApplianceClient(
            host=params['host'], user=params['user'], password=params['password'],
            prompt_regex=params['prompt_regex'],
            initial_pattern=None, timeout=120, strip_ansi=True, debug=debug,
        )
        if not client.connect():
            logger.error(f"Failed to connect to {appliance_name}")
            return False

        try:
            logger.info("➜ store certificate application datalake s3 console")
            client.channel.send(b"store certificate application datalake s3 console\r")

            # Phase 1: wait for paste prompt or replace confirmation
            buf = ""
            deadline = time.time() + 30
            paste_prompt_found = False
            while time.time() < deadline:
                if client.channel.recv_ready():
                    buf += client.channel.recv(65535).decode(errors="replace")
                if "Please paste your Trusted certificate below in PEM encoded format" in buf:
                    logger.info("✓ Certificate prompt detected")
                    paste_prompt_found = True
                    break
                if "will not be replaced" in buf or "already exists" in buf.lower():
                    # Guardium asks to confirm replacement — send 'y'
                    logger.info("⚠ Certificate already exists — sending 'y' to replace")
                    client.channel.send(b"y\r")
                    buf = ""
                    # wait again for paste prompt
                    deadline2 = time.time() + 30
                    while time.time() < deadline2:
                        if client.channel.recv_ready():
                            buf += client.channel.recv(65535).decode(errors="replace")
                        if "Please paste your Trusted certificate below in PEM encoded format" in buf:
                            logger.info("✓ Certificate prompt detected after confirmation")
                            paste_prompt_found = True
                            break
                        time.sleep(0.1)
                    break
                time.sleep(0.1)

            if not paste_prompt_found:
                logger.error(f"✗ Certificate paste prompt not found, buf: {buf[:300]}")
                return False

            # Phase 2: send certificate content
            for line in cert_content.splitlines():
                client.channel.send((line + "\n").encode())
                time.sleep(0.01)
            time.sleep(0.5)
            client.channel.send(b"\x04")

            # Phase 3: wait for success or GUI restart
            time.sleep(2)
            buf = ""
            deadline = time.time() + 60
            while time.time() < deadline:
                if client.channel.recv_ready():
                    buf += client.channel.recv(65535).decode(errors="replace")
                if "SUCCESS: Certificate imported successfully" in buf:
                    logger.info("✓ Certificate imported successfully")
                    return True
                if "Restarting GUI service" in buf:
                    logger.info("✓ Certificate imported (GUI restarting)")
                    return True
                if client.prompt_re.search(buf):
                    break
                time.sleep(0.1)

            if "SUCCESS: Certificate imported successfully" in buf:
                logger.info("✓ Certificate imported successfully")
                return True
            if "Restarting GUI service" in buf:
                logger.info("✓ Certificate imported (GUI restarting)")
                return True
            logger.error(f"✗ Certificate import failed: {buf}")
            return False

        finally:
            client.disconnect()

    except Exception as e:
        logger.error(f"✗ Error importing certificate: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False

def distribute_minio_certificate(
    config,
    logger,
    verbose: bool = False,
    appliance_name: str = "cm",
    ltr_appnode: str = "appnode1",
    phase2_delay: int = 120,
    timeout: int = 600,
    check_interval: int = 10,
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, f"DISTRIBUTE DATALAKE CERTIFICATE FROM {appliance_name}")

    from core.appliance_config_loader import ApplianceConfigLoader
    loader = ApplianceConfigLoader(config_loader=config)
    all_appliances = loader.get_all_appliances()

    # collectors = wszyscy oprócz CM i ltr_appnode
    collectors = [n for n in all_appliances if n != appliance_name and n != ltr_appnode]

    # faza 1: CM(3xINFO) + ltr_appnode(3xSuccess) + collectors(1xSuccess datalake-s3-gui)
    # faza 2: dodatkowo wszyscy others (kafka, appnode2...) mają 1xSuccess datalake-s3-gui
    CM_ALIASES      = {"datalake-catalog", "datalake-gui", "datalake-s3-gui"}
    APPNODE_ALIASES = {"datalake-catalog", "datalake-gui", "datalake-s3-gui"}
    S3_ALIAS        = "datalake-s3-gui"

    logger.info(f"  ltr_appnode={ltr_appnode}  collectors={collectors}")

    params = _get_appliance_connection_params(config, logger, appliance_name)
    if not params:
        return False

    # domain suffix z ltr_appnode hostname
    appnode_cfg = loader.get_appliance(ltr_appnode)
    domain = ""
    if appnode_cfg:
        fqdn = appnode_cfg.get('hostname', '')
        parts = fqdn.split('.', 1)
        domain = '.' + parts[1] if len(parts) > 1 else ""

    def _parse(output, expected_shorts):
        cm_ok      = set()
        appnode_ok = set()
        others_ok  = {n: False for n in expected_shorts}
        for line in output.splitlines():
            cols = line.split()
            if len(cols) < 4:
                continue
            hostname = cols[1]
            alias    = cols[2]
            status   = cols[3]
            short    = hostname.split('.')[0]
            if status == "INFO" and "finished" in line and short == appliance_name:
                cm_ok.add(alias)
            elif status == "Success" and short == ltr_appnode:
                appnode_ok.add(alias)
            elif status == "Success" and alias == S3_ALIAS and short in others_ok:
                others_ok[short] = True
        missing = []
        if not CM_ALIASES.issubset(cm_ok):
            missing.append(f"CM missing INFO: {CM_ALIASES - cm_ok}")
        if not APPNODE_ALIASES.issubset(appnode_ok):
            missing.append(f"{ltr_appnode} missing Success: {APPNODE_ALIASES - appnode_ok}")
        for n, ok in others_ok.items():
            if not ok:
                missing.append(f"{n} missing Success {S3_ALIAS}")
        return missing

    def _monitor(client, expected_shorts, label):
        start = time.time()
        missing = ["initial"]
        while time.time() - start < timeout:
            time.sleep(check_interval)
            output = client.execute_command("distribute certificate showlog all", timeout=300)
            missing = _parse(output, expected_shorts)
            elapsed = int(time.time() - start)
            if missing:
                logger.info(f"  [{label} {elapsed}s] waiting: {missing}")
            else:
                logger.info(f"✓ [{label}] distribution complete ({elapsed}s)")
                return True
        logger.error(f"✗ [{label}] timeout after {timeout}s, missing: {missing}")
        return False

    try:
        client = ApplianceClient(
            host=params['host'], user=params['user'], password=params['password'],
            prompt_regex=params['prompt_regex'],
            initial_pattern=None, timeout=120, strip_ansi=True, debug=debug,
        )
        if not client.connect():
            logger.error(f"Failed to connect to {appliance_name}")
            return False

        try:
            # ── Faza 1: distribute do ltr_appnode + collectors ────────────────
            targets = ",".join(
                [f"{ltr_appnode}{domain}"] + [f"{n}{domain}" for n in collectors]
            )
            cmd1 = f"distribute application certificate datalake {targets}"
            logger.info(f"➜ {cmd1}")
            client.execute_command(cmd1, timeout=300)
            logger.info("✓ Phase 1 distribute executed")

            if not _monitor(client, collectors, "phase1"):
                return False

            # ── Faza 2: distribute all_managed ───────────────────────────────
            logger.info(f"⌛ waiting {phase2_delay}s before phase 2...")
            time.sleep(phase2_delay)

            cmd2 = "distribute application certificate datalake all_managed true"
            logger.info(f"➜ {cmd2}")
            client.execute_command(cmd2, timeout=300)
            logger.info("✓ Phase 2 distribute executed")

            # others = wszyscy oprócz CM i ltr_appnode (collectors + kafka + appnode2...)
            others = [n for n in all_appliances if n != appliance_name and n != ltr_appnode]
            if not _monitor(client, others, "phase2"):
                return False

            return True

        finally:
            client.disconnect()

    except Exception as e:
        logger.error(f"✗ Error during certificate distribution: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False

def activate_ltr(
    config,
    logger,
    verbose: bool = False,
    appliance_name: str = "cm",
    retry_wait_seconds: int = 600,
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, f"ACTIVATE LTR ON {appliance_name}")

    admin_pwd = config.get_custom_variable('pwd')
    if not _require(logger, pwd=admin_pwd):
        return False

    params = _get_appliance_connection_params(config, logger, appliance_name)
    if not params:
        return False

    cmd = (
        f'grdapi configure_complete_cold_storage '
        f'protocol="CUSTOM" '
        f'objectStorageEndpoint="https://raptor.demo.guardium:9000" '
        f'accessKey=minioadmin '
        f'secretKey="{admin_pwd}" '
        f'dataBucket=guardium-ltr '
        f'resultSchema="datalake_reports" '
        f'region="US_EAST_1" '
        f'coldCatalogEndpoint="https://appnode1.demo.guardium:8443" '
        f'coldCatalogSchema="datalake" '
        f'coldStorageName="datalake" '
        f'queryEngineHost="appnode1.demo.guardium" '
        f'debug=3'
    )
    logger.info(f"➜ {cmd.replace(admin_pwd, '***')}")

    indicators = [
        "Cold Storage Maintenance Setup Completed",
        "Cold Storage ID:",
        "Cold Storage Name: datalake",
        '"status":"success"',
        "Complete cold storage configuration successful",
    ]
    streaming_error = "Step 3/4 FAILED: Data streaming configuration failed"

    for attempt in range(1, 3):
        try:
            client = ApplianceClient(
                host=params['host'], user=params['user'], password=params['password'],
                prompt_regex=params['prompt_regex'],
                initial_pattern=None, timeout=300, strip_ansi=True, debug=debug,
            )
            if not client.connect():
                logger.error(f"Failed to connect to {appliance_name}")
                return False

            try:
                output = client.execute_command(cmd, timeout=300)
            finally:
                client.disconnect()

        except Exception as e:
            logger.error(f"✗ Error activating LTR (attempt {attempt}/2): {e}")
            if debug:
                logger.error(traceback.format_exc())
            return False

        found = [ind for ind in indicators if ind.lower() in output.lower()]
        if len(found) >= 3:
            logger.info(f"✓ LTR activated ({len(found)}/{len(indicators)} indicators)")
            return True

        if streaming_error in output and attempt == 1:
            logger.warning(f"⚠ Streaming error detected — waiting {retry_wait_seconds}s ({retry_wait_seconds // 60} min) before retry...")
            time.sleep(retry_wait_seconds)
            logger.info("➜ Retrying activate_ltr (attempt 2/2)...")
            continue

        logger.error(f"✗ LTR activation failed ({len(found)}/{len(indicators)} indicators)\n{output}")
        return False

    logger.error("✗ LTR activation failed after 2 attempts")
    return False

def import_ltr_dashboard(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
    debug: bool = False,
    **kwargs) -> bool:
    
    _header(logger, "IMPORT LTR DASHBOARD ON CM")

    success = import_definitions_files(
        config=config, logger=logger,
        appliance_name=cm_appliance,
        definition_files=["exp_dashboard_ltr.sql"],
        definitions_dir=definitions_dir,
        debug=debug,
    )
    if success:
        logger.info("✓ LTR dashboard imported successfully")
    return success

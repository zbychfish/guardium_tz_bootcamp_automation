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
from core.utils import execute_local_command

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

# ---------------------------------------------------------------------------

def setup_minio_on_raptor(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, "SETUP MINIO ON RAPTOR")

    raptor_ip = config.get_machine_ip("raptor", use_private=True)
    if not raptor_ip:
        logger.error("Could not determine raptor IP address")
        return False

    pwd = config.get_custom_variable("pwd")
    if not _require(logger, pwd=pwd):
        return False

    pre_cmds = [
        "mkdir -p /home/minio/ca/{certs,private,newcerts}",
        "chmod 700 /home/minio/ca/private",
        "touch /home/minio/ca/index.txt",
        "echo 1000 > /home/minio/ca/serial",
        "mkdir -p /home/minio/certs/CAs",
        "openssl genrsa -out /home/minio/ca/private/ca.key 4096",
        'openssl req -x509 -new -nodes -key /home/minio/ca/private/ca.key -sha256 -days 3650 -subj "/CN=MinIO-Root-CA" -out /home/minio/ca/certs/ca.crt',
        "cp /home/minio/ca/certs/ca.crt /home/minio/certs/CAs/",
        "cp /home/minio/ca/certs/ca.crt /etc/pki/ca-trust/source/anchors/",
        "update-ca-trust",
        "openssl genrsa -out /home/minio/certs/private.key 4096 && chmod 600 /home/minio/certs/private.key",
        f'openssl req -new -key /home/minio/certs/private.key -out /home/minio/minio.csr -subj "/CN=minio.demo.guardium" -addext "subjectAltName=DNS:raptor.demo.guardium,IP:{raptor_ip}"',
        "openssl x509 -req -in /home/minio/minio.csr -CA /home/minio/ca/certs/ca.crt -CAkey /home/minio/ca/private/ca.key -CAcreateserial -out /home/minio/certs/public.crt -days 3600 -sha256 -copy_extensions copy",
        "mkdir -p /home/data/minio",
        "chmod 700 /home/data/minio",
        "curl -L -o /usr/local/bin/mc https://dl.min.io/client/mc/release/linux-amd64/mc",
        "chmod +x /usr/local/bin/mc",
    ]
    podman_cmd = (
        f"podman run -d --name minio --restart=always "
        f"-p 0.0.0.0:9000:9000 -p 0.0.0.0:9001:9001 "
        f"-v /home/data/minio:/data:Z "
        f"-v /home/minio/certs:/root/.minio/certs:Z "
        f"-e MINIO_ROOT_USER=minioadmin "
        f"-e MINIO_ROOT_PASSWORD='{pwd}' "
        f"quay.io/minio/minio server /data --console-address ':9001'"
    )
    post_cmds = [
        f"/usr/local/bin/mc alias set myminio https://raptor.demo.guardium:9000 minioadmin '{pwd}'",
        "/usr/local/bin/mc mb myminio/guardium-ltr",
        "podman update --restart=always minio",
    ]

    for cmd in pre_cmds:
        result = execute_local_command(cmd, logger=logger, verbose=verbose)
        if result["rc"] != 0:
            logger.error(f"✗ Failed: {cmd}\n{result['stderr']}")
            return False

    logger.info("➜ Starting MinIO container...")
    result = execute_local_command(podman_cmd, logger=logger, verbose=verbose)
    if result["rc"] != 0:
        logger.error(f"✗ Failed to start MinIO container\n{result['stderr']}")
        return False

    logger.info("⌛ Waiting 10s for MinIO to start...")
    time.sleep(10)

    for cmd in post_cmds:
        result = execute_local_command(cmd, logger=logger, verbose=verbose)
        if result["rc"] != 0:
            logger.error(f"✗ Failed: {cmd}\n{result['stderr']}")
            return False

    logger.info("✓ MinIO certificates prepared and MinIO started on raptor")
    return True

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
    timeout: int = 300,
    check_interval: int = 10,
    debug: bool = False,
    **kwargs) -> bool:

    import re

    _header(logger, f"DISTRIBUTE DATALAKE CERTIFICATE FROM {appliance_name}")

    from core.appliance_config_loader import ApplianceConfigLoader
    loader = ApplianceConfigLoader(config_loader=config)
    all_appliances = loader.get_all_appliances()
    appnodes   = [n for n, c in all_appliances.items() if c.get('type') == 'appnode']
    collectors = [n for n, c in all_appliances.items() if c.get('type') == 'collector']
    managed = len(appnodes) + len(collectors)
    expected_success = managed + 1
    expected_info    = 2

    logger.info(f"  appnodes={appnodes}  collectors={collectors}")
    logger.info(f"  expected Success={expected_success}  INFO={expected_info}")

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
            logger.info("➜ distribute application certificate datalake all_managed true --restart_cm_gui=true")
            client.execute_command("distribute application certificate datalake all_managed true --restart_cm_gui=true", timeout=300)
            logger.info("✓ Distribution command executed")

            start = time.time()
            success_count = info_count = 0
            while time.time() - start < timeout:
                time.sleep(check_interval)
                output = client.execute_command("distribute certificate showlog all", timeout=300)
                success_count = len(re.findall(r'\bSuccess\b', output, re.IGNORECASE))
                info_count    = len(re.findall(r'\bINFO\b', output))
                elapsed = int(time.time() - start)
                logger.info(f"  [{elapsed}s] Success={success_count}/{expected_success}  INFO={info_count}/{expected_info}")
                if success_count >= expected_success and info_count >= expected_info:
                    logger.info(f"✓ Certificate distribution completed ({elapsed}s)")
                    return True

            logger.error(f"✗ Distribution timeout after {timeout}s (Success={success_count}/{expected_success}, INFO={info_count}/{expected_info})")
            return False

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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import re
import traceback
from packaging.version import Version
from core.logger import get_logger
from core.appliance_config_loader import ApplianceConfigLoader
from core.appliance_client import ApplianceClient
from core.ssh_client import SSHClient
from core.utils import execute_local_command, run_local_command

logger = get_logger(__name__)


def _header(logger, title: str) -> None:
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)

def _connect_appliance(collector_ip, cli_password, step, debug, logger):
    appliance = ApplianceClient(host=collector_ip, user="cli", password=cli_password,
                                prompt_regex=r">", strip_ansi=True, debug=debug)
    if not appliance.connect():
        logger.error(f"✗ connect to collector failed ({step})")
        return None
    logger.info(f"✓ connected to collector ({step})")
    return appliance

def _load_etap_secret(config, token_var: str, token_file: str, logger) -> str:
    token = config.get_custom_variable(token_var)
    if not token and os.path.exists(token_file):
        with open(token_file, "r", encoding="utf-8") as f:
            token = f.read().strip()
    if not token:
        logger.error(f"{token_var} not found in custom_variables or {token_file}")
    return token

def _open_firewall_port(port: str, logger, ssh=None) -> bool:
    if ssh:
        check = ssh.execute_command("firewall-cmd --list-ports", print_output=False)
        if f"{port}/tcp" in (check.get('stdout') or ""):
            logger.info(f"  port {port}/tcp already open")
            return True
        logger.info(f"➜ firewall-cmd --add-port={port}/tcp")
        result = ssh.execute_command(f"firewall-cmd --permanent --add-port={port}/tcp && firewall-cmd --reload", print_output=False)
        if result.get('rc') != 0:
            logger.error(f"✗ firewall-cmd failed: {result.get('stderr')}")
            return False
    else:
        try:
            listed = run_local_command(command="firewall-cmd --list-ports", shell=True, timeout=10, check=False)
            if f"{port}/tcp" in (listed.stdout or ""):
                logger.info(f"  port {port}/tcp already open")
                return True
        except Exception:
            pass
        logger.info(f"➜ firewall-cmd --add-port={port}/tcp")
        result = run_local_command(command=f"firewall-cmd --permanent --add-port={port}/tcp && firewall-cmd --reload", shell=True, timeout=30, check=False)
        if result.returncode != 0:
            logger.error(f"✗ firewall-cmd failed (rc={result.returncode}): {result.stderr}")
            return False
    logger.info(f"✓ port {port}/tcp opened")
    return True

def _setup_etap_certs(
    config, logger, debug,
    collector_ip, cli_password,
    ca_dir, ca_key_path, ca_cert_path,
    csr_filename, cert_filename, token_filename, token_var,
    etap_alias, etap_common_name, etap_san1,
    etap_organizational_unit, etap_organization,
    etap_country, etap_encryption_algorithm, etap_keysize,
    etap_locality, etap_state, etap_email, etap_san2,
    import_ca: bool, ca_alias: str) -> bool:

    csr_path       = os.path.join(ca_dir, csr_filename)
    etap_cert_path = os.path.join(ca_dir, cert_filename)
    token_file     = os.path.join(ca_dir, token_filename)

    logger.info(f"➜ generate_external_stap_csr alias={etap_alias}")
    appliance = _connect_appliance(collector_ip, cli_password, "generate CSR", debug, logger)
    if not appliance:
        return False
    try:
        csr, token, line_above = appliance.generate_external_stap_csr(
            alias=etap_alias, common_name=etap_common_name, san1=etap_san1,
            organizational_unit=etap_organizational_unit, organization=etap_organization,
            country=etap_country, encryption_algorithm=etap_encryption_algorithm,
            keysize=etap_keysize, locality=etap_locality, state=etap_state,
            email=etap_email, san2=etap_san2
        )
    except Exception as e:
        logger.error(f"✗ generate CSR failed: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        appliance.disconnect()

    with open(csr_path, "w", encoding="utf-8") as f:
        f.write(csr)
    etap_csr_id = line_above
    etap_token  = token
    config.set_custom_variable(token_var, etap_token)
    with open(token_file, "w", encoding="utf-8") as f:
        f.write(etap_token)
    logger.info(f"✓ CSR generated (id={etap_csr_id}, token={etap_token})")

    logger.info(f"➜ openssl x509 sign CSR → {etap_cert_path}")
    try:
        run_local_command(
            command=f"openssl x509 -sha256 -req -days 3650 -CA {ca_cert_path} -CAkey {ca_key_path} -CAcreateserial -CAserial {ca_dir}/serial -in {csr_path} -out {etap_cert_path}",
            shell=True, timeout=60, check=True
        )
    except Exception as e:
        logger.error(f"✗ sign CSR failed: {e}")
        return False
    logger.info(f"✓ CSR signed → {etap_cert_path}")

    if import_ca:
        logger.info(f"➜ import_external_stap_ca_certificate alias={ca_alias}")
        appliance = _connect_appliance(collector_ip, cli_password, "import CA cert", debug, logger)
        if not appliance:
            return False
        try:
            with open(ca_cert_path, "r", encoding="utf-8") as f:
                ca_cert_pem = f.read()
            appliance.import_external_stap_ca_certificate(alias=ca_alias, ca_cert=ca_cert_pem)
        except Exception as e:
            logger.error(f"✗ import CA cert failed: {e}")
            if debug:
                logger.error(traceback.format_exc())
            return False
        finally:
            appliance.disconnect()
        logger.info("✓ CA certificate imported")

    logger.info(f"➜ import_external_stap_certificate id={etap_csr_id}")
    appliance = _connect_appliance(collector_ip, cli_password, "import ETAP cert", debug, logger)
    if not appliance:
        return False
    try:
        with open(etap_cert_path, "r", encoding="utf-8") as f:
            etap_cert_pem = f.read()
        appliance.import_external_stap_certificate(alias_line=etap_csr_id, stap_cert=etap_cert_pem)
    except Exception as e:
        logger.error(f"✗ import ETAP cert failed: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        appliance.disconnect()
    logger.info("✓ ETAP certificate imported")
    return True

def _deploy_etap_container(
    config, logger, verbose,
    container_name, db_type, db_port, publish_port,
    tenant_id, proxy_group_uuid,
    collector_ip, db_host_ip,
    etap_version, etap_token) -> bool:
    container_file_content = f"""[Unit]
Description={container_name}
Documentation=man:podman-generate-systemd(1)

[Container]
Image=icr.io/guardium/guardium_external_s-tap:v{etap_version}
ContainerName={container_name}
HostName=localhost-{container_name}

PodmanArgs=--memory=4g --shm-size=800M

PublishPort={publish_port}:8888/tcp

Environment=STAP_CONFIG_TAP_TAP_IP=NULL
Environment=STAP_CONFIG_TAP_PRIVATE_TAP_IP=NULL
Environment=STAP_CONFIG_TAP_FORCE_SERVER_IP=0
Environment=STAP_CONFIG_PROXY_GROUP_UUID={proxy_group_uuid}
Environment=STAP_CONFIG_PROXY_GROUP_MEMBER_COUNT=1
Environment=STAP_CONFIG_PROXY_NUM_WORKERS=1
Environment=STAP_CONFIG_PROXY_PROXY_PROTOCOL=0
Environment=STAP_CONFIG_PROXY_DISCONNECT_ON_INVALID_CERTIFICATE=0
Environment=STAP_CONFIG_PROXY_NOTIFY_ON_INVALID_CERTIFICATE=0
Environment=STAP_CONFIG_PROXY_DETECT_SSL_WITHIN_X_PACKETS=-1
Environment=STAP_CONFIG_DB_0_REAL_DB_PORT={db_port}
Environment=STAP_CONFIG_PROXY_LISTEN_PORT=8888
Environment=STAP_CONFIG_PROXY_DEBUG=0
Environment=STAP_CONFIG_PROXY_SECRET={etap_token}
Environment=STAP_CONFIG_PROXY_CSR_NAME=
Environment=STAP_CONFIG_PROXY_CSR_COUNTRY=
Environment=STAP_CONFIG_PROXY_CSR_PROVINCE=
Environment=STAP_CONFIG_PROXY_CSR_CITY=
Environment=STAP_CONFIG_PROXY_CSR_ORGANIZATION=
Environment=STAP_CONFIG_PROXY_CSR_KEYLENGTH=2048
Environment=STAP_CONFIG_DB_0_DB_TYPE={db_type}
Environment=STAP_CONFIG_PARTICIPATE_IN_LOAD_BALANCING=0
Environment=STAP_CONFIG_TAP_TENANT_ID={tenant_id}
Environment=STAP_CONFIG_SQLGUARD_0_SQLGUARD_IP={collector_ip}
Environment=STAP_CONFIG_PROXY_DB_HOST={db_host_ip}

[Service]
Restart=always
TimeoutStopSec=70

[Install]
WantedBy=multi-user.target
"""
    container_file_path = f"/etc/containers/systemd/{container_name}.container"
    for cmd, desc in [
        ("mkdir -p /etc/containers/systemd", "mkdir /etc/containers/systemd"),
        (f"cat > {container_file_path} << 'EOF'\n{container_file_content}\nEOF", f"write {container_file_path}"),
        ("systemctl daemon-reload", "systemctl daemon-reload"),
        (f"systemctl start {container_name}", f"systemctl start {container_name}"),
    ]:
        logger.info(f"➜ {desc}")
        result = execute_local_command(cmd, logger=logger, verbose=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ {desc} (rc={result['rc']})")
            if result['stdout']:
                logger.error(f"  stdout: {result['stdout']}")
            if result['stderr']:
                logger.error(f"  stderr: {result['stderr']}")
            return False
        logger.info(f"✓ {desc}")
    return True


# ── public functions ──────────────────────────────────────────────────────────

def setup_raptor_to_deploy_etap(
    config,
    logger,
    verbose: bool = False,
    local_tar: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/images/guardium_external_s-tap_v12.2.4.tar",
    debug: bool = False) -> bool:

    _header(logger, "SETUP RAPTOR TO DEPLOY ETAP")

    logger.info("➜ dnf install podman-docker skopeo")
    try:
        result = run_local_command(command="dnf -y install podman-docker skopeo", shell=True, timeout=300, check=True)
        logger.info("✓ packages installed")
        if debug and result.stdout:
            logger.debug(result.stdout)
    except Exception as e:
        logger.error(f"✗ dnf install failed: {e}")
        return False

    for action, svc in [("start", "podman-restart"), ("enable", "podman-restart")]:
        logger.info(f"➜ systemctl {action} {svc}")
        try:
            run_local_command(command=f"systemctl {action} {svc}", shell=True, timeout=30, check=True)
            logger.info(f"✓ systemctl {action} {svc}")
        except Exception as e:
            logger.error(f"✗ systemctl {action} {svc}: {e}")
            return False

    etap_version = None

    logger.info("➜ skopeo list-tags icr.io/guardium/guardium_external_s-tap")
    try:
        result = run_local_command(command="skopeo list-tags docker://icr.io/guardium/guardium_external_s-tap", shell=True, timeout=120, check=True)
        if result.stdout:
            etap_versions = json.loads(result.stdout)
            if debug:
                logger.debug(f"tags: {etap_versions.get('Tags', [])}")
            latest = {}
            for tag in etap_versions.get("Tags", []):
                match = re.match(r"^v(\d+\.\d+\.\d+)", tag)
                if not match:
                    continue
                version_str = match.group(1)
                major, minor, _ = version_str.split(".")
                key = f"{major}.{minor}"
                try:
                    v = Version(version_str)
                    if key not in latest or v > latest[key]:
                        latest[key] = v
                except Exception:
                    continue
            if latest:
                guardium_minor_version = config.get_custom_variable('guardium_minor_version') or max(latest.keys())
                if guardium_minor_version in latest:
                    etap_version = str(latest[guardium_minor_version])
                    logger.info(f"✓ latest ETAP for Guardium {guardium_minor_version}: {etap_version}")
    except Exception as e:
        logger.warning(f"⚠ skopeo failed ({e}) — falling back to local image")

    # ── TEMPORARY WORKAROUND: ICR registry unavailable ───────────────────────
    # When skopeo cannot reach icr.io, load the ETAP image from a local tar
    # and extract the version from the archive filename.
    # Remove this block once ICR access is restored.
    if etap_version is None:
        logger.warning("⚠ ICR unreachable — loading local ETAP image (TEMPORARY WORKAROUND)")
        tar_match = re.search(r"guardium_external_s-tap_v(\d+\.\d+\.\d+)\.tar", local_tar)
        if not tar_match:
            logger.error(f"✗ cannot extract version from: {local_tar}")
            return False
        etap_version = tar_match.group(1)
        logger.info(f"➜ podman load -i {local_tar}")
        try:
            load_result = run_local_command(command=f"podman load -i {local_tar}", shell=True, timeout=300, check=True)
            logger.info(f"✓ local image loaded (version: {etap_version})")
            if debug and load_result.stdout:
                logger.debug(load_result.stdout)
        except Exception as e:
            logger.error(f"✗ podman load failed: {e}")
            return False
    # ── END TEMPORARY WORKAROUND ─────────────────────────────────────────────

    os.makedirs("/opt/ETAP/ca", exist_ok=True)
    with open("/opt/ETAP/ca/guardium_etap_version.txt", "w", encoding="utf-8") as f:
        f.write(etap_version)
    config.set_custom_variable('guardium_etap_version', etap_version)
    logger.info(f"✓ ETAP version saved: {etap_version}")
    return True

def setup_etap_certificates_mysql(
    config,
    logger,
    verbose: bool = False,
    collector_appliance: str = "coll1",
    ca_dir: str = "/opt/ETAP/ca",
    etap_alias: str = "mysql-etap",
    etap_common_name: str = "mysql-etap",
    etap_san1: str = "coll1.demo.com",
    etap_organizational_unit: str = "Demo",
    etap_organization: str = "Guardium",
    etap_locality: str = "",
    etap_state: str = "",
    etap_country: str = "PL",
    etap_email: str = "",
    etap_encryption_algorithm: str = "2",
    etap_keysize: str = "2",
    etap_san2: str = "",
    ca_common_name: str = "ETAP CA",
    ca_alias: str = "etapca",
    debug: bool = False) -> bool:

    _header(logger, "SETUP ETAP CERTIFICATES (MYSQL)")

    collector_config = ApplianceConfigLoader(config_loader=config).get_appliance(collector_appliance)
    if not collector_config:
        logger.error(f"collector '{collector_appliance}' not found in machines_info.json")
        return False
    collector_ip = collector_config.get('ip')
    if not collector_ip:
        logger.error(f"collector '{collector_appliance}' has no IP configured")
        return False

    cli_password = config.get_custom_variable('cli_pwd')
    if not cli_password:
        logger.error("cli_pwd not found in custom_variables")
        return False

    logger.info(f"  collector={collector_appliance} ({collector_ip})  ca_dir={ca_dir}  alias={etap_alias}")

    ca_key_path  = os.path.join(ca_dir, "ca.key")
    ca_cert_path = os.path.join(ca_dir, "ca.pem")

    ca_subj_parts = [f"C={etap_country}"]
    if etap_state:
        ca_subj_parts.append(f"ST={etap_state}")
    if etap_locality:
        ca_subj_parts.append(f"L={etap_locality}")
    ca_subj_parts += [f"O={etap_organization}", f"OU={etap_organizational_unit}", f"CN={ca_common_name}"]
    if etap_email:
        ca_subj_parts.append(f"emailAddress={etap_email}")
    ca_subj = "/" + "/".join(ca_subj_parts)

    try:
        logger.info(f"➜ mkdir -p {ca_dir}")
        run_local_command(command=f"mkdir -p {ca_dir}", shell=True, timeout=30, check=True)
        logger.info(f"➜ openssl genrsa → {ca_key_path}")
        run_local_command(command=f"openssl genrsa -out {ca_key_path} 2048", shell=True, timeout=60, check=True)
        logger.info(f"➜ openssl req -x509 → {ca_cert_path}")
        run_local_command(command=f'openssl req -x509 -sha256 -new -key {ca_key_path} -days 3650 -out {ca_cert_path} -subj "{ca_subj}"', shell=True, timeout=60, check=True)
        logger.info("✓ CA key + certificate generated")
    except Exception as e:
        logger.error(f"✗ CA setup failed: {e}")
        return False

    return _setup_etap_certs(
        config=config, logger=logger, debug=debug,
        collector_ip=collector_ip, cli_password=cli_password,
        ca_dir=ca_dir, ca_key_path=ca_key_path, ca_cert_path=ca_cert_path,
        csr_filename="etap.csr", cert_filename="etap.pem",
        token_filename="mysql_etap_token.txt", token_var="mysql_etap_token",
        etap_alias=etap_alias, etap_common_name=etap_common_name, etap_san1=etap_san1,
        etap_organizational_unit=etap_organizational_unit, etap_organization=etap_organization,
        etap_country=etap_country, etap_encryption_algorithm=etap_encryption_algorithm,
        etap_keysize=etap_keysize, etap_locality=etap_locality, etap_state=etap_state,
        etap_email=etap_email, etap_san2=etap_san2,
        import_ca=True, ca_alias=ca_alias
    )

def deploy_etap_mysql(
    config,
    logger,
    verbose: bool = False,
    collector_appliance: str = "coll1",
    debug: bool = False) -> bool:

    _header(logger, "DEPLOY ETAP MYSQL")

    raptor_info = config.get_machine("raptor")
    if not raptor_info:
        logger.error("machine 'raptor' not found in configuration")
        return False
    raptor_ip = raptor_info.get("private_ip") or raptor_info.get("host")
    if not raptor_ip:
        logger.error("raptor IP not found in configuration")
        return False

    collector_config = ApplianceConfigLoader(config_loader=config).get_appliance(collector_appliance)
    if not collector_config:
        logger.error(f"collector '{collector_appliance}' not found in configuration")
        return False
    collector_ip = collector_config.get("ip")
    if not collector_ip:
        logger.error(f"collector '{collector_appliance}' IP not found in configuration")
        return False

    version_file = "/opt/ETAP/ca/guardium_etap_version.txt"
    etap_version = config.get_custom_variable("guardium_etap_version")
    if not etap_version and os.path.exists(version_file):
        with open(version_file, "r", encoding="utf-8") as f:
            etap_version = f.read().strip()
    if not etap_version:
        logger.error("guardium_etap_version not found in custom_variables or version file")
        return False

    etap_token = _load_etap_secret(config, "mysql_etap_token", "/opt/ETAP/ca/mysql_etap_token.txt", logger)
    if not etap_token:
        return False

    sshd_config = "/etc/ssh/sshd_config"
    check_cmd = f"python3 -c \"import pathlib, re; text = pathlib.Path('{sshd_config}').read_text(); raise SystemExit(0 if re.search(r'^\\s*Port\\s+22\\s*$', text, re.MULTILINE) else 1)\""
    try:
        port22_present = run_local_command(command=check_cmd, shell=True, timeout=10, check=False).returncode == 0
    except Exception:
        port22_present = False
    if not port22_present:
        logger.info("➜ add Port 22 to sshd_config")
        result = execute_local_command(f"printf '\\n# Temporary port for ETAP\\nPort 22\\n' >> {sshd_config}", logger=logger, verbose=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ failed to add port 22: {result['stderr']}")
            return False
        logger.info("✓ Port 22 added")
    else:
        logger.info("  Port 22 already in sshd_config")

    for cmd, desc in [
        ("systemctl restart sshd", "systemctl restart sshd"),
        ("mkdir -p /opt/ETAP && cd /opt/ETAP && if [ ! -d Guardium_External_S-TAP ]; then git clone https://github.com/IBM/Guardium_External_S-TAP.git; fi; exit 0", "git clone Guardium_External_S-TAP"),
    ]:
        logger.info(f"➜ {desc}")
        result = execute_local_command(cmd, logger=logger, verbose=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ {desc} (rc={result['rc']})")
            if result['stdout']:
                logger.error(f"  stdout: {result['stdout']}")
            if result['stderr']:
                logger.error(f"  stderr: {result['stderr']}")
            return False
        logger.info(f"✓ {desc}")

    if not _open_firewall_port("63333", logger):
        return False

    return _deploy_etap_container(
        config=config, logger=logger, verbose=verbose,
        container_name="mysql-etap", db_type="mysql", db_port="3306", publish_port="63333",
        tenant_id="MYSQLETAP", proxy_group_uuid="305575f5-c47b-48b2-b3f8-67138fd36d61",
        collector_ip=collector_ip, db_host_ip=raptor_ip,
        etap_version=etap_version, etap_token=etap_token
    )

def deploy_etap_for_oracle_container_on_sauropod(
    config,
    logger,
    verbose: bool = False,
    collector_appliance: str = "coll1",
    ca_dir: str = "/opt/ETAP/ca",
    etap_alias: str = "oracle-etap",
    etap_common_name: str = "oracle-etap",
    etap_san1: str = "coll1.demo.com",
    etap_organizational_unit: str = "Demo",
    etap_organization: str = "Guardium",
    etap_locality: str = "",
    etap_state: str = "",
    etap_country: str = "PL",
    etap_email: str = "",
    etap_encryption_algorithm: str = "2",
    etap_keysize: str = "2",
    etap_san2: str = "",
    ca_alias: str = "etapca",
    debug: bool = False) -> bool:

    _header(logger, "DEPLOY ETAP FOR ORACLE CONTAINER (SAUROPOD)")

    collector_config = ApplianceConfigLoader(config_loader=config).get_appliance(collector_appliance)
    if not collector_config:
        logger.error(f"collector '{collector_appliance}' not found in machines_info.json")
        return False
    collector_ip = collector_config.get('ip')
    if not collector_ip:
        logger.error(f"collector '{collector_appliance}' has no IP configured")
        return False

    cli_password = config.get_custom_variable('cli_pwd')
    if not cli_password:
        logger.error("cli_pwd not found in custom_variables")
        return False

    sauropod_info = config.get_machine("sauropod")
    if not sauropod_info:
        logger.error("machine 'sauropod' not found in configuration")
        return False
    sauropod_ip = sauropod_info.get("private_ip") or sauropod_info.get("host")
    if not sauropod_ip:
        logger.error("sauropod IP not found in configuration")
        return False

    version_file = "/opt/ETAP/ca/guardium_etap_version.txt"
    etap_version = config.get_custom_variable("guardium_etap_version")
    if not etap_version and os.path.exists(version_file):
        with open(version_file, "r", encoding="utf-8") as f:
            etap_version = f.read().strip()
    if not etap_version:
        logger.error("guardium_etap_version not found in custom_variables or version file")
        return False

    logger.info(f"  collector={collector_appliance} ({collector_ip})  sauropod={sauropod_ip}  alias={etap_alias}")

    ca_key_path  = os.path.join(ca_dir, "ca.key")
    ca_cert_path = os.path.join(ca_dir, "ca.pem")

    if not _setup_etap_certs(
        config=config, logger=logger, debug=debug,
        collector_ip=collector_ip, cli_password=cli_password,
        ca_dir=ca_dir, ca_key_path=ca_key_path, ca_cert_path=ca_cert_path,
        csr_filename="etap2.csr", cert_filename="etap2.pem",
        token_filename="oracle_etap_token.txt", token_var="oracle_etap_token",
        etap_alias=etap_alias, etap_common_name=etap_common_name, etap_san1=etap_san1,
        etap_organizational_unit=etap_organizational_unit, etap_organization=etap_organization,
        etap_country=etap_country, etap_encryption_algorithm=etap_encryption_algorithm,
        etap_keysize=etap_keysize, etap_locality=etap_locality, etap_state=etap_state,
        etap_email=etap_email, etap_san2=etap_san2,
        import_ca=False, ca_alias=ca_alias
    ):
        return False

    etap_token = _load_etap_secret(config, "oracle_etap_token", os.path.join(ca_dir, "oracle_etap_token.txt"), logger)
    if not etap_token:
        return False

    sauropod_password = config.get_custom_variable('pwd')
    ssh_cfg = config.get('ssh', {})
    ssh = SSHClient(
        host=sauropod_ip,
        username=ssh_cfg.get('username', 'root'),
        password=sauropod_password,
        port=ssh_cfg.get('port', 2223),
        timeout=60
    )
    logger.info(f"➜ connect to sauropod ({sauropod_ip}) for firewall")
    if not ssh.connect():
        logger.error("✗ failed to connect to sauropod")
        return False
    try:
        for port in ("1521", "1522", "63334"):
            if not _open_firewall_port(port, logger, ssh=ssh):
                return False
    finally:
        ssh.disconnect()

    return _deploy_etap_container(
        config=config, logger=logger, verbose=verbose,
        container_name="oracle-etap", db_type="oracle", db_port="1522", publish_port="63334",
        tenant_id="ORACLEETAP", proxy_group_uuid="7a2f91bc-d83e-41c5-a6f9-12047ae58b32",
        collector_ip=collector_ip, db_host_ip=sauropod_ip,
        etap_version=etap_version, etap_token=etap_token
    )

def stop_oracle_lab_services(config, logger, verbose: bool = False, **kwargs) -> bool:
    _header(logger, "STOP ORACLE LAB SERVICES")

    for svc, actions in [
        ("mysqld",      ("stop", "disable")),
        ("mysql-etap",  ("stop", "mask")),
        ("oracle-etap", ("stop", "mask")),
    ]:
        for action in actions:
            logger.info(f"➜ systemctl {action} {svc}")
            result = execute_local_command(f"systemctl {action} {svc}", logger=logger, verbose=verbose)
            if result['rc'] != 0:
                logger.warning(f"⚠ systemctl {action} {svc}: {result['stderr']}")
            else:
                logger.info(f"✓ systemctl {action} {svc}")

    logger.info("✓ mysqld stopped/disabled, mysql-etap and oracle-etap stopped/masked")
    return True


# Made with Bob

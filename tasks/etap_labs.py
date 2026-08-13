#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import re
from packaging.version import Version
from typing import Optional
from core.logger import get_logger
from core.appliance_config_loader import ApplianceConfigLoader
from core.appliance_client import ApplianceClient
from core.utils import execute_local_command, run_local_command

logger = get_logger(__name__)


def setup_raptor_to_deploy_etap(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False
) -> bool:
    logger.info("=" * 80)
    logger.info("SETUP RAPTOR TO DEPLOY ETAP")
    logger.info("=" * 80)

    # Step 1: Install required packages
    logger.info("\n➜ Installing package requirements (podman-docker, skopeo)...")

    try:
        dnf_command = "dnf -y install podman-docker skopeo"
        logger.info(f"Executing: {dnf_command}")
        result = run_local_command(command=dnf_command, shell=True, timeout=300, check=True)
        logger.info("✓ Packages installed successfully")
        if debug and result.stdout:
            logger.debug(f"dnf output: {result.stdout}")
    except Exception as e:
        logger.error(f"✗ Failed to install packages: {e}")
        logger.error("ETAP setup requires podman-docker and skopeo packages")
        return False

    # Step 2: Determine the latest ETAP version from ICR
    logger.info("\n➜ Determining the latest ETAP version from ICR...")

    etap_version = None

    try:
        skopeo_command = "skopeo list-tags docker://icr.io/guardium/guardium_external_s-tap"
        logger.info(f"Executing: {skopeo_command}")
        result = run_local_command(command=skopeo_command, shell=True, timeout=120, check=True)

        if result.stdout:
            etap_versions = json.loads(result.stdout)
            if debug:
                logger.debug(f"Available tags: {etap_versions.get('Tags', [])}")

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
                    logger.info(f"✓ Latest ETAP version for Guardium {guardium_minor_version}: {etap_version}")

    except Exception as e:
        logger.warning(f"⚠ skopeo failed ({e}) — falling back to local image")

    # ── TEMPORARY WORKAROUND: ICR registry unavailable ───────────────────────
    # When skopeo cannot reach icr.io, load the ETAP image from a local tar
    # and extract the version from the archive filename.
    # Remove this block once ICR access is restored.
    if etap_version is None:
        local_tar = "/opt/guardium_tz_bootcamp_automation/upload/source_files/images/guardium_external_s-tap_v12.2.4.tar"
        logger.warning("⚠ ICR registry unreachable — loading local ETAP image (TEMPORARY WORKAROUND)")
        logger.info(f"➜ Loading image from {local_tar}...")

        tar_match = re.search(r"guardium_external_s-tap_v(\d+\.\d+\.\d+)\.tar", local_tar)
        if not tar_match:
            logger.error(f"✗ Cannot extract version from tar filename: {local_tar}")
            return False
        etap_version = tar_match.group(1)

        try:
            load_result = run_local_command(command=f"podman load -i {local_tar}", shell=True, timeout=300, check=True)
            logger.info(f"✓ Local image loaded (version: {etap_version})")
            if debug and load_result.stdout:
                logger.debug(f"podman load output: {load_result.stdout}")
        except Exception as e:
            logger.error(f"✗ Failed to load local ETAP image: {e}")
            return False
    # ── END TEMPORARY WORKAROUND ─────────────────────────────────────────────

    os.makedirs("/opt/ETAP/ca", exist_ok=True)
    with open("/opt/ETAP/ca/guardium_etap_version.txt", "w", encoding="utf-8") as f:
        f.write(etap_version)
    config.set_custom_variable('guardium_etap_version', etap_version)

    logger.info(f"✓ ETAP version saved: {etap_version}")
    logger.info("\n" + "=" * 80)
    logger.info("✓ Raptor setup for ETAP deployment completed successfully")
    logger.info(f"ETAP Version: {etap_version}")
    logger.info("=" * 80)
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
    debug: bool = False
) -> bool:
    from core.utils import run_local_command as _run

    logger.info("=" * 80)
    logger.info("SETUP ETAP CERTIFICATES")
    logger.info("=" * 80)

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    collector_config = appliance_loader.get_appliance(collector_appliance)
    if not collector_config:
        logger.error(f"Collector '{collector_appliance}' not found in machines_info.json")
        return False
    collector_ip = collector_config.get('ip')
    if not collector_ip:
        logger.error(f"Collector '{collector_appliance}' has no IP address configured")
        return False

    cli_password = config.get_custom_variable('cli_pwd')
    if not cli_password:
        logger.error("CLI password not found in custom_variables (cli_pwd)")
        return False

    logger.info(f"Collector: {collector_appliance} at {collector_ip}")
    logger.info(f"CA Directory: {ca_dir}")
    logger.info(f"ETAP Alias: {etap_alias}")

    ca_key_path = os.path.join(ca_dir, "ca.key")
    ca_cert_path = os.path.join(ca_dir, "ca.pem")
    csr_path = os.path.join(ca_dir, "etap.csr")
    etap_cert_path = os.path.join(ca_dir, "etap.pem")
    token_file = os.path.join(ca_dir, "mysql_etap_token.txt")

    try:
        _run(command=f"mkdir -p {ca_dir}", shell=True, timeout=30, check=True)
        logger.info("✓ CA directory created")
        _run(command=f"openssl genrsa -out {ca_key_path} 2048", shell=True, timeout=60, check=True)
        logger.info("✓ CA private key generated")

        ca_subj_parts = [f"C={etap_country}"]
        if etap_state:
            ca_subj_parts.append(f"ST={etap_state}")
        if etap_locality:
            ca_subj_parts.append(f"L={etap_locality}")
        ca_subj_parts += [f"O={etap_organization}", f"OU={etap_organizational_unit}", f"CN={ca_common_name}"]
        if etap_email:
            ca_subj_parts.append(f"emailAddress={etap_email}")
        ca_subj = "/" + "/".join(ca_subj_parts)

        _run(command=f'openssl req -x509 -sha256 -new -key {ca_key_path} -days 3650 -out {ca_cert_path} -subj "{ca_subj}"', shell=True, timeout=60, check=True)
        logger.info("✓ CA certificate generated")
    except Exception as e:
        logger.error(f"✗ CA setup failed: {e}")
        return False

    etap_csr_id = None
    etap_token = None

    for step, action in [("generate CSR", True), ("import CA cert", False), ("import ETAP cert", False)]:
        try:
            appliance = ApplianceClient(host=collector_ip, user="cli", password=cli_password, prompt_regex=r">", strip_ansi=True, debug=debug)
            if not appliance.connect():
                logger.error(f"✗ Failed to connect to collector for: {step}")
                return False
            logger.info(f"✓ Connected to collector ({step})")

            if action:  # generate CSR
                csr, token, line_above = appliance.generate_external_stap_csr(
                    alias=etap_alias, common_name=etap_common_name, san1=etap_san1,
                    organizational_unit=etap_organizational_unit, organization=etap_organization,
                    country=etap_country, encryption_algorithm=etap_encryption_algorithm,
                    keysize=etap_keysize, locality=etap_locality, state=etap_state,
                    email=etap_email, san2=etap_san2
                )
                with open(csr_path, "w", encoding="utf-8") as f:
                    f.write(csr)
                etap_csr_id = line_above
                etap_token = token
                config.set_custom_variable('mysql_etap_token', etap_token)
                with open(token_file, "w", encoding="utf-8") as f:
                    f.write(etap_token)
                logger.info(f"✓ CSR generated (id={etap_csr_id}, token={etap_token})")

                _run(command=f"openssl x509 -sha256 -req -days 3650 -CA {ca_cert_path} -CAkey {ca_key_path} -CAcreateserial -CAserial serial -in {csr_path} -out {etap_cert_path}", shell=True, timeout=60, check=True)
                logger.info(f"✓ CSR signed → {etap_cert_path}")

            elif etap_csr_id is None:  # import CA cert (second iteration)
                with open(ca_cert_path, "r", encoding="utf-8") as f:
                    ca_cert_pem = f.read()
                appliance.import_external_stap_ca_certificate(alias=ca_alias, ca_cert=ca_cert_pem)
                logger.info("✓ CA certificate imported")
            else:  # import ETAP cert (third iteration)
                with open(etap_cert_path, "r", encoding="utf-8") as f:
                    etap_cert_pem = f.read()
                appliance.import_external_stap_certificate(alias_line=etap_csr_id, stap_cert=etap_cert_pem)
                logger.info("✓ ETAP certificate imported")

            appliance.disconnect()
        except Exception as e:
            logger.error(f"✗ {step} failed: {e}")
            if debug:
                import traceback
                logger.error(traceback.format_exc())
            return False

    logger.info("✓ ETAP CERTIFICATES SETUP COMPLETED SUCCESSFULLY")
    return True


def deploy_etap_mysql(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False,
    **kwargs
) -> bool:
    logger.info("=" * 80)
    logger.info("DEPLOY ETAP MYSQL")
    logger.info("=" * 80)

    collector_appliance = kwargs.get('collector_appliance', 'coll1')

    raptor_info = config.get_machine("raptor")
    if not raptor_info:
        logger.error("Machine 'raptor' not found in configuration")
        return False
    raptor_ip = raptor_info.get("private_ip") or raptor_info.get("host")
    if not raptor_ip:
        logger.error("Raptor IP not found in configuration")
        return False

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    collector_config = appliance_loader.get_appliance(collector_appliance)
    if not collector_config:
        logger.error(f"Collector '{collector_appliance}' not found in configuration")
        return False
    collector_ip = collector_config.get("ip")
    if not collector_ip:
        logger.error(f"Collector '{collector_appliance}' IP not found in configuration")
        return False

    version_file = "/opt/ETAP/ca/guardium_etap_version.txt"
    etap_version = config.get_custom_variable("guardium_etap_version")
    if not etap_version and os.path.exists(version_file):
        with open(version_file, "r", encoding="utf-8") as f:
            etap_version = f.read().strip()
        if etap_version:
            logger.info(f"Loaded guardium_etap_version from {version_file}")
    if not etap_version:
        logger.error("guardium_etap_version not found in custom_variables or version file")
        return False

    token_file = "/opt/ETAP/ca/mysql_etap_token.txt"
    etap_token = config.get_custom_variable("mysql_etap_token")
    if not etap_token and os.path.exists(token_file):
        with open(token_file, "r", encoding="utf-8") as f:
            etap_token = f.read().strip()
        if etap_token:
            logger.info(f"Loaded mysql_etap_token from {token_file}")
    if not etap_token:
        logger.error("mysql_etap_token not found in custom_variables or token file")
        return False

    sshd_config = "/etc/ssh/sshd_config"
    check_command = f"python3 -c \"import pathlib, re; text = pathlib.Path('{sshd_config}').read_text(); raise SystemExit(0 if re.search(r'^\\s*Port\\s+22\\s*$', text, re.MULTILINE) else 1)\""
    if execute_local_command(check_command, logger=logger, verbose=False)['rc'] != 0:
        logger.info("Port 22 not found - adding temporary SSH port 22 to sshd_config")
        result = execute_local_command(f"printf '\\n# Temporary port for ETAP\\nPort 22\\n' >> {sshd_config}", logger=logger, verbose=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ Failed to add port 22: {result['stderr']}")
            return False
    else:
        logger.info("Port 22 already present in sshd_config")

    for cmd, desc in [
        ("systemctl restart sshd", "restart SSHD"),
        ("mkdir -p /opt/ETAP && cd /opt/ETAP && if [ ! -d Guardium_External_S-TAP ]; then git clone https://github.com/IBM/Guardium_External_S-TAP.git; else echo Repository already exists; fi", "clone Guardium External S-TAP"),
    ]:
        result = execute_local_command(cmd, logger=logger, verbose=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ Failed to {desc}: {result['stderr']}")
            return False

    container_file_content = f"""[Unit]
Description=mysql-etap
Documentation=man:podman-generate-systemd(1)

[Container]
Image=icr.io/guardium/guardium_external_s-tap:v{etap_version}
ContainerName=mysql-etap
HostName=localhost-mysql-etap

PodmanArgs=--memory=4g --shm-size=800M

PublishPort=63333:8888/tcp

Environment=STAP_CONFIG_TAP_TAP_IP=NULL
Environment=STAP_CONFIG_TAP_PRIVATE_TAP_IP=NULL
Environment=STAP_CONFIG_TAP_FORCE_SERVER_IP=0
Environment=STAP_CONFIG_PROXY_GROUP_UUID=305575f5-c47b-48b2-b3f8-67138fd36d61
Environment=STAP_CONFIG_PROXY_GROUP_MEMBER_COUNT=1
Environment=STAP_CONFIG_PROXY_NUM_WORKERS=1
Environment=STAP_CONFIG_PROXY_PROXY_PROTOCOL=0
Environment=STAP_CONFIG_PROXY_DISCONNECT_ON_INVALID_CERTIFICATE=0
Environment=STAP_CONFIG_PROXY_NOTIFY_ON_INVALID_CERTIFICATE=0
Environment=STAP_CONFIG_PROXY_DETECT_SSL_WITHIN_X_PACKETS=-1
Environment=STAP_CONFIG_DB_0_REAL_DB_PORT=3306
Environment=STAP_CONFIG_PROXY_LISTEN_PORT=8888
Environment=STAP_CONFIG_PROXY_DEBUG=0
Environment=STAP_CONFIG_PROXY_SECRET={etap_token}
Environment=STAP_CONFIG_PROXY_CSR_NAME=
Environment=STAP_CONFIG_PROXY_CSR_COUNTRY=
Environment=STAP_CONFIG_PROXY_CSR_PROVINCE=
Environment=STAP_CONFIG_PROXY_CSR_CITY=
Environment=STAP_CONFIG_PROXY_CSR_ORGANIZATION=
Environment=STAP_CONFIG_PROXY_CSR_KEYLENGTH=2048
Environment=STAP_CONFIG_DB_0_DB_TYPE=mysql
Environment=STAP_CONFIG_PARTICIPATE_IN_LOAD_BALANCING=0
Environment=STAP_CONFIG_TAP_TENANT_ID=MYSQLETAP
Environment=STAP_CONFIG_SQLGUARD_0_SQLGUARD_IP={collector_ip}
Environment=STAP_CONFIG_PROXY_DB_HOST={raptor_ip}

[Service]
Restart=always
TimeoutStopSec=70

[Install]
WantedBy=multi-user.target
"""

    container_file_path = "/etc/containers/systemd/mysql-etap.container"
    for cmd, desc in [
        ("mkdir -p /etc/containers/systemd", "create systemd container directory"),
        (f"cat > {container_file_path} << 'EOF'\n{container_file_content}\nEOF", "create systemd container file"),
        ("systemctl daemon-reload", "reload systemd daemon"),
        ("systemctl start mysql-etap", "start mysql-etap service"),
    ]:
        result = execute_local_command(cmd, logger=logger, verbose=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ Failed to {desc}: {result['stderr']}")
            return False

    logger.info("✓ ETAP MySQL deployed and started on raptor")
    return True


# Made with Bob

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import subprocess
import sys
import traceback
from pathlib import Path
from time import sleep
from typing import Optional

from core.appliance_client import ApplianceClient
from core.appliance_config_loader import ApplianceConfigLoader
from core.guardium_rest_api import import_definitions_files
from core.logger import get_logger
from core.ssh_client import SSHClient
from core.utils import execute_local_command
from core.web_ui import guardium_customer_upload_import

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

def _connect_appliance(config, logger, appliance_name: str, debug: bool = False):
    """Return connected ApplianceClient or None."""
    loader = ApplianceConfigLoader(config_loader=config)
    cfg = loader.get_appliance(appliance_name)
    if not cfg:
        logger.error(f"Appliance '{appliance_name}' not found")
        return None
    host = cfg.get('ip')
    if not host:
        logger.error(f"No IP for appliance '{appliance_name}'")
        return None
    appliance_type = cfg.get('type')
    prompt = loader.get_default_prompt(appliance_type, configured=True) if appliance_type else r">"
    cli_pwd = config.get_custom_variable('cli_pwd')
    if not cli_pwd:
        logger.error("cli_pwd not found in custom_variables")
        return None
    client = ApplianceClient(
        host=host, user="cli", password=cli_pwd,
        prompt_regex=prompt, initial_pattern=None,
        timeout=60, strip_ansi=True, debug=debug,
    )
    if not client.connect():
        logger.error(f"Failed to connect to {appliance_name}")
        return None
    return client

def _ssh_sauropod(config, logger, timeout: int = 60):
    """Return connected SSHClient to sauropod or None."""
    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return None
    ssh_cfg = config.get('ssh', {})
    password = config.get_custom_variable('pwd')
    if not password:
        logger.error("pwd not found in custom_variables")
        return None
    ssh = SSHClient(
        host=sauropod_ip,
        username=ssh_cfg.get('username', 'root'),
        password=password,
        port=ssh_cfg.get('port', 2223),
        timeout=timeout,
    )
    logger.info(f"➜ Connecting to sauropod ({sauropod_ip})...")
    if not ssh.connect():
        logger.error("Failed to connect to sauropod")
        return None
    logger.info("✓ Connected to sauropod")
    return ssh

# ---------------------------------------------------------------------------

def enable_vulnerability_management(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    flag_name: str = "VULNERABILITY_MANAGEMENT",
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, "ENABLE VULNERABILITY MANAGEMENT FEATURE FLAG")

    client = _connect_appliance(config, logger, cm_appliance, debug=debug)
    if client is None:
        return False

    try:
        cmd = f"grdapi enable_disable_feature_flag flagName={flag_name} action=enable"
        logger.info(f"➜ {cmd}")
        result = client.execute_command(cmd, timeout=30)
        if verbose:
            logger.info(f"Response: {result}")

        logger.info("➜ Verifying flag state via grdapi list_feature_flags...")
        flags_output = client.execute_command("grdapi list_feature_flags", timeout=30)
        if verbose or debug:
            logger.info(f"Feature flags:\n{flags_output}")

        for line in flags_output.splitlines():
            if flag_name in line:
                if "State: ENABLED" in line:
                    logger.info(f"✓ {flag_name} is ENABLED")
                    return True
                else:
                    logger.error(f"✗ {flag_name} found but state is not ENABLED: {line.strip()}")
                    return False

        logger.error(f"✗ {flag_name} not found in list_feature_flags output")
        return False

    finally:
        client.disconnect()

def create_va_postgres_account(
    config,
    logger,
    verbose: bool = True,
    db_user: str = "sqlguard",
    db_group: str = "gdmmonitor",
    **kwargs) -> bool:

    _header(logger, "CREATE VA POSTGRES ACCOUNT")

    password = config.get_custom_variable('pwd')
    if not _require(logger, pwd=password):
        return False

    def psql(sql, desc):
        if '$$' in sql:
            cmd = f"sudo -u postgres psql -d postgres -U postgres << 'EOSQL'\n{sql}\nEOSQL"
        else:
            escaped = sql.replace('"', '\\"')
            cmd = f'sudo -u postgres psql -d postgres -U postgres -c "{escaped}"'
        result = execute_local_command(cmd, logger, verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to {desc}: {result['stderr']}")
            return False
        logger.info(f"✓ {desc}")
        return True

    steps = [
        (f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_user WHERE usename='{db_user}') THEN CREATE USER {db_user} WITH ENCRYPTED PASSWORD '{password}'; END IF; END $$",
         f"create user {db_user}"),
        (f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_group WHERE groname='{db_group}') THEN CREATE GROUP {db_group}; END IF; END $$",
         f"create group {db_group}"),
        (f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_group g JOIN pg_user u ON u.usesysid=ANY(g.grolist) WHERE g.groname='{db_group}' AND u.usename='{db_user}') THEN ALTER GROUP {db_group} ADD USER {db_user}; END IF; END $$",
         f"add {db_user} to {db_group}"),
        (f"GRANT pg_read_all_settings TO {db_group}",   f"grant pg_read_all_settings to {db_group}"),
        (f"GRANT SELECT ON pg_authid TO {db_group}",    f"grant SELECT on pg_authid to {db_group}"),
        ("CREATE EXTENSION IF NOT EXISTS pgcrypto",      "create extension pgcrypto"),
    ]

    for sql, desc in steps:
        if not psql(sql, desc):
            return False

    logger.info("✓ VA PostgreSQL account ready")
    return True

def import_va_postgres_definitions(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, "IMPORT VA POSTGRES DEFINITIONS")

    success = import_definitions_files(
        config=config,
        logger=logger,
        appliance_name=cm_appliance,
        definition_files=["exp_security_assessment_postgres_on_raptor.sql"],
        definitions_dir=definitions_dir,
        debug=debug,
    )
    if success:
        logger.info("✓ VA PostgreSQL definitions imported successfully")
    return success

def fetch_cm_certificate_on_sauropod(
    config,
    logger,
    verbose: bool = True,
    cm_host: str = "cm.demo.guardium",
    cm_port: int = 8443,
    cert_path: str = "/root/gn-trainings/vascanner/certs/vascanner.pem",
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, "FETCH CM CERTIFICATE ON SAUROPOD")

    ssh = _ssh_sauropod(config, logger)
    if ssh is None:
        return False

    cert_dir = cert_path.rsplit('/', 1)[0]
    cmds = [
        (f"mkdir -p {cert_dir}",                                                                    "create cert dir"),
        (f"openssl s_client -connect {cm_host}:{cm_port} -showcerts </dev/null 2>/dev/null "
         f"| openssl x509 -outform PEM > {cert_path}",                                             f"fetch certificate from {cm_host}:{cm_port}"),
        (f"test -s {cert_path}",                                                                    "verify cert file non-empty"),
    ]

    try:
        for cmd, desc in cmds:
            logger.info(f"➜ {desc}...")
            result = ssh.execute_command(cmd, timeout=30, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"✗ Failed to {desc}: {result['stderr']}")
                return False
            logger.info(f"✓ {desc}")

        logger.info(f"✓ Certificate saved to sauropod:{cert_path}")
        return True

    except Exception as e:
        logger.error(f"✗ SSH operation failed: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

def create_va_api_key(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    key_name: str = "vascanner",
    key_file: str = ".va_api_key",
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, "CREATE VA API KEY")

    client = _connect_appliance(config, logger, cm_appliance, debug=debug)
    if client is None:
        return False

    try:
        cmd = f"grdapi create_api_key name={key_name}"
        logger.info(f"➜ {cmd}")
        output = client.execute_command(cmd, timeout=30)
        if verbose:
            logger.info(f"Response:\n{output}")

        api_key = None
        for line in output.splitlines():
            if "Encoded API key:" in line:
                api_key = line.split("Encoded API key:", 1)[1].strip()
                break

        if not api_key:
            logger.error(f"Could not parse 'Encoded API key' from output: {output}")
            return False

        logger.info(f"✓ API key generated: {api_key[:10]}...")
        key_path = config.config_file.parent.parent / key_file
        key_path.write_text(api_key, encoding='utf-8')
        logger.info(f"✓ API key saved to: {key_path}")
        return True

    finally:
        client.disconnect()

def deploy_vascanner_on_sauropod(
    config,
    logger,
    verbose: bool = True,
    image: str = None,
    container_name: str = "va-scanner-sauropod",
    config_file: str = "/opt/vascanner/config",
    certs_dir: str = "/root/gn-trainings/vascanner/certs",
    va_agent_name: str = "VA_SCANNER_ON_SAUROPOD",
    cm_host: str = "cm.demo.guardium",
    cm_port: int = 8443,
    key_file: str = ".va_api_key",
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, "DEPLOY VA SCANNER ON SAUROPOD")

    ibm_key = config.get_custom_variable('ibm_container_api_key')
    if not _require(logger, image=image, ibm_container_api_key=ibm_key):
        return False

    key_path = config.config_file.parent.parent / key_file
    if not key_path.exists():
        logger.error(f"{key_path} not found — run create_va_api_key stage first")
        return False
    api_key = key_path.read_text(encoding='utf-8').strip()
    if not api_key:
        logger.error(f"{key_path} is empty")
        return False

    config_content = (
        f"GDP_HOST={cm_host}\n"
        f"GDP_HOST_PORT={cm_port}\n"
        f"CLIENT_API_KEY={api_key}\n"
        f"VA_AGENT_NAME={va_agent_name}\n"
    )

    ssh = _ssh_sauropod(config, logger, timeout=120)
    if ssh is None:
        return False

    try:
        logger.info("➜ Logging in to cp.icr.io...")
        result = ssh.execute_command(f"podman login cp.icr.io -u cp -p '{ibm_key}'", timeout=60, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ podman login failed: {result['stderr']}")
            return False
        logger.info("✓ Logged in to cp.icr.io")

        logger.info(f"➜ Pulling image {image}...")
        result = ssh.execute_command(f"podman pull {image}", timeout=600, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ podman pull failed: {result['stderr']}")
            return False
        logger.info("✓ Image pulled")

        logger.info("➜ Resolving image ID...")
        result = ssh.execute_command(f"podman images --format '{{{{.ID}}}}' {image}", timeout=30, print_output=verbose)
        if result['rc'] != 0 or not result['stdout'].strip():
            logger.error(f"✗ Failed to get image ID: {result['stderr']}")
            return False
        image_id = result['stdout'].strip().splitlines()[0].strip()
        logger.info(f"✓ Image ID: {image_id}")

        config_dir = config_file.rsplit('/', 1)[0]
        logger.info(f"➜ Writing config to {config_file}...")
        result = ssh.execute_command(
            f"mkdir -p {config_dir} && cat > {config_file} << 'EOF'\n{config_content}EOF",
            timeout=30, print_output=verbose,
        )
        if result['rc'] != 0:
            logger.error(f"✗ Failed to write config file: {result['stderr']}")
            return False
        logger.info("✓ Config file written")

        logger.info(f"➜ Starting container {container_name}...")
        run_cmd = (
            f"podman run --network host -d --replace "
            f"--env-file {config_file} "
            f"--name {container_name} "
            f"-v {certs_dir}:/var/vascanner/certs "
            f"{image_id}"
        )
        result = ssh.execute_command(run_cmd, timeout=60, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ podman run failed: {result['stderr']}")
            return False
        logger.info(f"✓ Container {container_name} started")
        return True

    except Exception as e:
        logger.error(f"✗ SSH operation failed: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

def import_dps(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    dps_file: str = None,
    demo_user: str = "demo",
    headless: bool = True,
    **kwargs) -> bool:
    _header(logger, "IMPORT DPS")

    if not _require(logger, dps_file=dps_file):
        return False
    if not os.path.exists(dps_file):
        logger.error(f"DPS file not found: {dps_file}")
        return False

    password = config.get_custom_variable('pwd')
    if not _require(logger, pwd=password):
        return False

    loader = ApplianceConfigLoader(config_loader=config)
    appliance_config = loader.get_appliance(cm_appliance)
    if not appliance_config:
        logger.error(f"Appliance '{cm_appliance}' not found")
        return False
    cm_ip = appliance_config.get('ip')
    if not cm_ip:
        logger.error(f"No IP for appliance '{cm_appliance}'")
        return False

    login_url = f"https://{cm_ip}:8443"

    logger.info("➜ Installing playwright browsers...")
    result = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(f"⚠ playwright install returned {result.returncode}: {result.stderr.strip()}")

    logger.info(f"➜ Starting DPS import from {dps_file}...")
    logger.info(f"  login_url: {login_url}, user: {demo_user}")
    sleep(30)

    try:
        guardium_customer_upload_import(
            login_url=login_url,
            username=demo_user,
            password=password,
            file_to_upload=dps_file,
            headless=headless,
        )
        logger.info("✓ DPS imported successfully")
        return True
    except FileNotFoundError as e:
        logger.error(f"✗ {e}")
        return False
    except Exception as e:
        logger.error(f"✗ DPS import failed: {e}")
        return False

def import_va_api_definitions(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, "IMPORT VA API DEFINITIONS ON CM")

    success = import_definitions_files(
        config=config,
        logger=logger,
        appliance_name=cm_appliance,
        definition_files=[
            "exp_dashboard_va.sql",
            "exp_security_assessment_oracle_on_sauropod.sql",
        ],
        definitions_dir=definitions_dir,
        debug=debug,
    )
    if success:
        logger.info("✓ VA API definitions imported successfully")
    return success

def create_va_oauth_client(
    config,
    logger,
    verbose: bool = True,
    appliance_name: str = "cm",
    client_id: str = "va-api",
    debug: bool = False,
    **kwargs) -> bool:
    
    import json

    _header(logger, f"CREATE OAUTH CLIENT: {client_id}")

    loader = ApplianceConfigLoader(config_loader=config)
    appliance_config = loader.get_appliance(appliance_name)
    if not appliance_config:
        logger.error(f"Appliance '{appliance_name}' not found")
        return False

    appliance_ip = appliance_config.get('ip')
    if not appliance_ip:
        logger.error(f"No IP for appliance '{appliance_name}'")
        return False

    cli_pwd = config.get_custom_variable('cli_pwd')
    if not _require(logger, cli_pwd=cli_pwd):
        return False

    user = loader.get_default_user(appliance_config.get('type', 'cm'))
    prompt = loader.get_default_prompt(appliance_config.get('type', 'cm'), configured=True)

    client = ApplianceClient(
        host=appliance_ip,
        user=user,
        password=cli_pwd,
        prompt_regex=prompt,
        timeout=120,
        debug=debug,
    )

    try:
        if not client.connect():
            logger.error(f"Failed to connect to {appliance_name}")
            return False
        logger.info("✓ Connected successfully")

        result = client.execute_command("grdapi list_oauth_clients")
        if f"Client Id: {client_id}" in result:
            logger.info(f"➜ Deleting existing OAuth client '{client_id}'...")
            client.execute_command(f"grdapi delete_oauth_clients client_id={client_id}")
            logger.info("✓ Existing client deleted")

        logger.info(f"➜ Creating OAuth client '{client_id}'...")
        result = client.execute_command(f'grdapi register_oauth_client client_id={client_id} grant_types="password"')

        client_secret = None
        for line in result.splitlines():
            line = line.strip()
            if line.startswith('{') and line.endswith('}'):
                try:
                    data = json.loads(line)
                    client_secret = data.get('client_secret')
                    if client_secret:
                        logger.info(f"✓ OAuth client created: {client_id}")
                        logger.info(f"  Client Secret: {client_secret[:10]}...")
                        break
                except json.JSONDecodeError:
                    pass

        if not client_secret:
            logger.error(f"Failed to extract client_secret from response: {result}")
            return False

        secret_file = config.config_file.parent.parent / ".client_secret_va"
        secret_file.write_text(client_secret, encoding='utf-8')
        logger.info(f"✓ Client secret saved to: {secret_file}")
        return True

    except Exception as e:
        logger.error(f"✗ Error creating OAuth client: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        client.disconnect()

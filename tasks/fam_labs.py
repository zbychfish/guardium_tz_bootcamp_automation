#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re
import tempfile
import time
import traceback
from typing import Optional

from core.appliance_config_loader import ApplianceConfigLoader
from core.guardium_rest_api import create_guardium_api, import_definitions_files
from core.logger import get_logger
from core.ssh_client import SSHClient

logger = get_logger(__name__)


def _header(logger, title: str) -> None:
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)


def configure_fam_on_raptor(config, logger, verbose=True,
                             cm_appliance: str = "cm",
                             installation_delay: int = 10,
                             debug: bool = False, **kwargs) -> bool:
    _header(logger, "CONFIGURE FAM ON RAPTOR")

    stap_host = config.get_machine_ip('raptor', use_private=True)
    if not stap_host:
        logger.error("Raptor IP not found in machines config")
        return False

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("Password 'pwd' not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    for param, value in [
        ("STAP_FAM_ENABLED",       "1"),
        ("STAP_FAM_INSTALLED",     "1"),
        ("STAP_UID_CHAIN_SSHD_IP", "1"),
        ("STAP_UID_CHAIN_TRACE",   "1"),
    ]:
        if verbose:
            logger.info(f"Setting {param}={value} on raptor ({stap_host})")
        api.gim_client_params(client_ip=stap_host, param_name=param, param_value=value)

    logger.info("➜ Scheduling GIM install on raptor...")
    api.gim_schedule_install(client_ip=stap_host, date="now")
    logger.info(f"✓ Scheduled. Waiting {installation_delay}s before monitoring...")
    time.sleep(installation_delay)

    logger.info("➜ Monitoring installation progress...")
    pending = ["initial"]
    check_count = 0
    while pending:
        check_count += 1
        logger.info(f"  Check #{check_count}: Querying module status...")
        modules = api.gim_list_client_modules(client_ip=stap_host)

        if "ErrorCode" in modules or "ErrorMessage" in modules:
            logger.error(f"  ✗ API Error: {modules.get('ErrorCode')} {modules.get('ErrorMessage')}")
            return False

        entries = [e.strip() for e in re.split(r"#+\s*ENTRY\s+\d+\s*#+", modules.get("Message", "")) if e.strip()]
        result_mods = []
        for entry in entries:
            m_name  = re.search(r"NAME:\s+([A-Z0-9\-]+)", entry)
            m_state = re.search(r"STATE:\s+([A-Z\-]+)", entry)
            result_mods.append({"name": m_name.group(1) if m_name else "?", "state": m_state.group(1) if m_state else "?"})

        pending = [m for m in result_mods if m["state"] != "INSTALLED"]
        if pending:
            logger.info(f"  ⌛ {len(pending)} module(s) still installing: {[m['name'] for m in pending]}")
            logger.info("  Waiting 30s before next check...")
            time.sleep(30)
        else:
            logger.info("  ✓ All modules installed successfully!")

    logger.info("✓ FAM configured on raptor")
    return True


def import_fam_policy(config, logger, verbose: bool = True,
                      cm_appliance: str = "cm",
                      definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
                      debug: bool = False, **kwargs) -> bool:
    _header(logger, "IMPORT FAM POLICY ON CM")

    success = import_definitions_files(
        config=config,
        logger=logger,
        appliance_name=cm_appliance,
        definition_files=["exp_fam_policy.sql"],
        definitions_dir=definitions_dir,
        debug=debug
    )

    if success:
        logger.info("✓ FAM policy imported successfully")
    return success


def install_fammonitor_on_ceratops(config, logger, verbose=False,
                                   appliance_name: str = "cm",
                                   collector_name: str = "coll1",
                                   client_ip: Optional[str] = None,
                                   module: str = "FAMMONITOR",
                                   module_version: str = "12.2_r120202259_1",
                                   debug: bool = False, **kwargs) -> bool:
    from core.appliance_operations import install_gim_module

    _header(logger, "INSTALL FAMMONITOR ON CERATOPS")

    if not client_ip:
        client_ip = config.get_machine_ip('ceratops', use_private=True)
        if not client_ip:
            logger.error("client_ip not provided and ceratops not found in machines config")
            return False
        logger.info(f"Auto-detected ceratops IP: {client_ip}")

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    collector_config = appliance_loader.get_appliance(collector_name)
    if not collector_config:
        logger.error(f"Collector '{collector_name}' not found in machines_info.json")
        return False

    sqlguard_ip = collector_config.get('ip')
    if not sqlguard_ip:
        logger.error(f"Collector '{collector_name}' has no IP address configured")
        return False

    logger.info(f"  - Client IP (ceratops): {client_ip}")
    logger.info(f"  - SQL Guard IP (collector '{collector_name}'): {sqlguard_ip}")
    logger.info(f"  - Module version: {module_version}")

    return install_gim_module(
        config=config,
        logger=logger,
        appliance_name=appliance_name,
        client_ip=client_ip,
        module=module,
        module_version=module_version,
        params={"FAMMONITOR_SQLGUARD_IP": sqlguard_ip},
        monitor_installation=True,
        installation_delay=10,
        debug=debug
    )


def enable_fam_protect_privileged_on_raptor(config, logger, verbose=True, **kwargs) -> bool:
    from core.utils import execute_commands

    _header(logger, "ENABLE FAM PROTECT PRIVILEGED ON RAPTOR")

    commands = [
        r"sed -i 's/^fam_protect_privileged[[:space:]]*=.*/fam_protect_privileged=1/' /opt/guardium/modules/STAP/current/guard_tap.ini",
        "/opt/guardium/modules/STAP/current/guard-config-update --restart stap",
    ]

    if not execute_commands(commands, logger, verbose):
        logger.error("Failed to enable fam_protect_privileged on raptor")
        return False

    logger.info("✓ fam_protect_privileged=1 set and STAP restarted on raptor")
    return True


def enable_fam_protect_privileged_on_ceratops(config, logger, verbose=True,
                                               ceratops_machine: str = "ceratops",
                                               ssh_username: str = "itzuser",
                                               debug: bool = False, **kwargs) -> bool:
    _header(logger, "ENABLE FAM PROTECT PRIVILEGED ON CERATOPS")

    ceratops_ip = config.get_machine_ip(ceratops_machine, use_private=True)
    if not ceratops_ip:
        logger.error(f"✗ IP not found for machine: {ceratops_machine}")
        return False

    ssh_private_key = config.get_custom_variable('ssh_private_key')
    tmp_key_path = None
    key_file = None

    if ssh_private_key:
        tmp_fd, tmp_key_path = tempfile.mkstemp(prefix="itz_key_", suffix=".pem")
        try:
            os.write(tmp_fd, ssh_private_key.encode())
        finally:
            os.close(tmp_fd)
        os.chmod(tmp_key_path, 0o600)
        key_file = tmp_key_path
        logger.info("  Using SSH key from custom_variables")
    else:
        logger.info("  No SSH key in custom_variables — using agent/default keys")

    ini_file = r'C:\Program Files\IBM\Windows Fam Monitor\Bin\Guard_Tap.ini'

    try:
        ssh = SSHClient(
            host=ceratops_ip,
            username=ssh_username,
            key_file=key_file,
            port=2223,
            timeout=30
        )
        if not ssh.connect():
            logger.error(f"✗ Failed to connect to {ceratops_machine} ({ceratops_ip}) as {ssh_username}")
            return False

        try:
            steps = [
                (
                    f'powershell -Command "(Get-Content \'{ini_file}\') -replace \'FAM_PROTECT_PRIVILEGED=0\', \'FAM_PROTECT_PRIVILEGED=1\' | Set-Content \'{ini_file}\'"',
                    'set FAM_PROTECT_PRIVILEGED=1 in Guard_Tap.ini'
                ),
                (
                    'net stop "IBM Guardium FAM for Windows" && net start "IBM Guardium FAM for Windows"',
                    'restart IBM Guardium FAM for Windows'
                ),
            ]

            for cmd, desc in steps:
                logger.info(f"  ➜ {desc}...")
                result = ssh.execute_command(cmd, timeout=60, print_output=verbose)
                if result['rc'] != 0:
                    logger.error(f"✗ Failed to {desc} (rc={result['rc']}): {result['stderr'].strip() or result['stdout'].strip()}")
                    return False
                logger.info(f"  ✓ {desc}")

            logger.info(f"✓ FAM_PROTECT_PRIVILEGED=1 set and service restarted on {ceratops_machine}")
            return True

        finally:
            ssh.disconnect()

    except Exception as e:
        logger.error(f"✗ Unexpected error: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        if tmp_key_path and os.path.exists(tmp_key_path):
            os.remove(tmp_key_path)

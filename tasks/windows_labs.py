#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import tempfile
import time
import traceback
from typing import Optional

from core.appliance_config_loader import ApplianceConfigLoader
from core.appliance_operations import install_gim_module
from core.logger import get_logger
from core.ssh_client import SSHClient

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


def _ssh_ceratops(config, logger, ceratops_machine: str, ssh_username: str):
    """Return connected SSHClient to ceratops (key-auth) or None."""
    ceratops_ip = config.get_machine_ip(ceratops_machine, use_private=True)
    if not ceratops_ip:
        logger.error(f"✗ IP not found for machine: {ceratops_machine}")
        return None, None

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
        logger.info("  ⚠ No SSH key in custom_variables — using agent/default keys")

    ssh = SSHClient(host=ceratops_ip, username=ssh_username, key_file=key_file, port=2223, timeout=30)
    if not ssh.connect():
        logger.error(f"✗ Failed to connect to {ceratops_machine} ({ceratops_ip}) as {ssh_username}")
        if tmp_key_path and os.path.exists(tmp_key_path):
            os.remove(tmp_key_path)
        return None, None

    return ssh, tmp_key_path

# ---------------------------------------------------------------------------

def extract_zip_on_ceratops(
    config,
    logger,
    verbose: bool = True,
    ceratops_machine: str = "ceratops",
    ssh_username: str = "itzuser",
    zip_path: str = r'C:\bootcamp\zip\GIM-Installer-12.2_r120202259_1.zip',
    dest_dir: str = r'C:\bootcamp',
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, "EXTRACT ZIP ON CERATOPS")

    ssh, tmp_key_path = _ssh_ceratops(config, logger, ceratops_machine, ssh_username)
    if ssh is None:
        return False

    try:
        cmd = f'powershell -Command "Expand-Archive -Path \'{zip_path}\' -DestinationPath \'{dest_dir}\' -Force"'
        logger.info(f"➜ Extracting {zip_path} → {dest_dir}")
        result = ssh.execute_command(cmd, timeout=120, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ Extraction failed (rc={result['rc']}): {result['stderr'].strip() or result['stdout'].strip()}")
            return False
        logger.info(f"✓ Extracted {zip_path} to {dest_dir} on {ceratops_machine}")
        return True

    except Exception as e:
        logger.error(f"✗ Unexpected error: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()
        if tmp_key_path and os.path.exists(tmp_key_path):
            os.remove(tmp_key_path)

def install_gim_on_ceratops(
    config,
    logger,
    verbose: bool = True,
    ceratops_machine: str = "ceratops",
    ssh_username: str = "itzuser",
    setup_exe: str = r'C:\bootcamp\gim_unpacked\GIM_Client\Setup.exe',
    appliance: str = "coll1.demo.guardium",
    local_ip: Optional[str] = None,
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, "INSTALL GIM ON CERATOPS")

    ceratops_ip = config.get_machine_ip(ceratops_machine, use_private=True)
    if not ceratops_ip:
        logger.error(f"✗ IP not found for machine: {ceratops_machine}")
        return False

    if not local_ip:
        local_ip = ceratops_ip

    ssh, tmp_key_path = _ssh_ceratops(config, logger, ceratops_machine, ssh_username)
    if ssh is None:
        return False

    try:
        cmd = f'"{setup_exe}" -UNATTENDED -APPLIANCE {appliance} -LOCALIP {local_ip}'
        logger.info(f"➜ {cmd}")
        result = ssh.execute_command(cmd, timeout=300, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ GIM installation failed (rc={result['rc']}): {result['stderr'].strip() or result['stdout'].strip()}")
            return False
        logger.info(f"✓ GIM installed on {ceratops_machine}")
        return True

    except Exception as e:
        logger.error(f"✗ Unexpected error: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()
        if tmp_key_path and os.path.exists(tmp_key_path):
            os.remove(tmp_key_path)

def install_winstap_on_ceratops(
    config,
    logger,
    verbose: bool = False,
    appliance_name: str = "cm",
    collector_name: str = "coll1",
    client_ip: Optional[str] = None,
    module: str = "WINSTAP",
    module_version: str = "",
    gim_registration_delay: int = 60,
    debug: bool = False,
    **kwargs) -> bool:
    
    _header(logger, "INSTALL WINSTAP ON CERATOPS")

    if not client_ip:
        client_ip = config.get_machine_ip('ceratops', use_private=True)
        if not client_ip:
            logger.error("client_ip not provided and ceratops not found in machines config")
            return False
        logger.info(f"  Auto-detected ceratops IP: {client_ip}")

    loader = ApplianceConfigLoader(config_loader=config)
    collector_config = loader.get_appliance(collector_name)
    if not collector_config:
        logger.error(f"Collector '{collector_name}' not found")
        return False

    sqlguard_ip = collector_config.get('ip')
    if not sqlguard_ip:
        logger.error(f"Collector '{collector_name}' has no IP address configured")
        return False

    logger.info(f"  client IP (ceratops): {client_ip}")
    logger.info(f"  SQL Guard IP (collector '{collector_name}'): {sqlguard_ip}")
    logger.info(f"  module version: {module_version}")

    logger.info(f"⌛ Waiting {gim_registration_delay}s for GIM client registration...")
    time.sleep(gim_registration_delay)

    return install_gim_module(
        config=config,
        logger=logger,
        appliance_name=appliance_name,
        client_ip=client_ip,
        module=module,
        module_version=module_version,
        params={"WINSTAP_SQLGUARD_IP": sqlguard_ip},
        monitor_installation=True,
        installation_delay=10,
        debug=debug,
    )

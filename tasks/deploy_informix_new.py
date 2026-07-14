#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import ConfigLoader
from core.ssh_client import SSHClient

SYSCTL_CONTENT = (
    "# Informix shared memory settings\n"
    "kernel.shmmax = 536870912\n"
    "kernel.shmall = 131072\n"
    "kernel.shmmni = 4096\n"
    "\n"
    "# Semaphores: semmsl semmns semopm semmni\n"
    "kernel.sem = 250 32000 100 128\n"
    "\n"
    "# Maximum number of open file descriptors per process\n"
    "fs.file-max = 65536\n"
    "\n"
    "# Local port range\n"
    "net.ipv4.ip_local_port_range = 1024 65000\n"
)

SYSCTL_FILE = "/etc/sysctl.d/99-informix.conf"

LIMITS_CONTENT = (
    "\n# Resource limits for the informix OS user\n"
    "informix  soft  nofile   65536\n"
    "informix  hard  nofile   65536\n"
    "informix  soft  nproc    16384\n"
    "informix  hard  nproc    16384\n"
    "informix  soft  stack    32768\n"
    "informix  hard  stack    32768\n"
    "informix  soft  memlock  unlimited\n"
    "informix  hard  memlock  unlimited\n"
)

LIMITS_FILE = "/etc/security/limits.conf"


def _get_ssh(config) -> tuple:
    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    ssh_config = config.get('ssh', {})
    return (
        sauropod_ip,
        SSHClient(
            host=sauropod_ip,
            username=ssh_config.get('username', 'root'),
            password=config.get_custom_variable('pwd'),
            port=ssh_config.get('port', 2223),
            timeout=60
        )
    )


def configure_kernel_parameters(config, logger, verbose: bool = True, **kwargs) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("CONFIGURE KERNEL PARAMETERS FOR INFORMIX ON SAUROPOD")
        logger.info("=" * 80)

    sauropod_ip, ssh = _get_ssh(config)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    if not ssh.connect():
        logger.error(f"Failed to connect to sauropod ({sauropod_ip})")
        return False

    try:
        logger.info(f"➜ Writing {SYSCTL_FILE}...")
        result = ssh.execute_command(
            f"cat > {SYSCTL_FILE} << 'EOF'\n{SYSCTL_CONTENT}EOF",
            timeout=30, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"Failed to write {SYSCTL_FILE}: {result['stderr']}")
            return False
        logger.info(f"✓ {SYSCTL_FILE} written")

        logger.info("➜ Applying kernel parameters...")
        result = ssh.execute_command(
            f"sysctl -p {SYSCTL_FILE} > /dev/null",
            timeout=30, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"Failed to apply sysctl config: {result['stderr']}")
            return False
        logger.info("✓ Kernel parameters applied")

        logger.info(f"➜ Checking informix limits in {LIMITS_FILE}...")
        check = ssh.execute_command(
            "grep -c '^informix' /etc/security/limits.conf || true",
            timeout=10, print_output=False
        )
        if check['stdout'].strip() not in ('', '0'):
            logger.info("⊘ Resource limits for 'informix' already present — skipping")
        else:
            result = ssh.execute_command(
                f"cat >> {LIMITS_FILE} << 'EOF'\n{LIMITS_CONTENT}EOF",
                timeout=30, print_output=verbose
            )
            if result['rc'] != 0:
                logger.error(f"Failed to append informix limits: {result['stderr']}")
                return False
            logger.info("✓ Resource limits for 'informix' added")

    except Exception as e:
        logger.error(f"✗ SSH operation failed: {e}")
        return False
    finally:
        ssh.disconnect()

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ KERNEL PARAMETERS CONFIGURED")
        logger.info("=" * 80)
    return True


def create_informix_user(config, logger, verbose: bool = True, **kwargs) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("CREATE INFORMIX GROUP AND USER ON SAUROPOD")
        logger.info("=" * 80)

    sauropod_ip, ssh = _get_ssh(config)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    password = config.get_custom_variable('pwd')
    if not password:
        logger.error("Root password (pwd) not found in custom_variables")
        return False

    if not ssh.connect():
        logger.error(f"Failed to connect to sauropod ({sauropod_ip})")
        return False

    try:
        for cmd, desc in [
            ("getent group informix > /dev/null 2>&1 || groupadd -g 200 informix",                                              "group informix"),
            ("id informix > /dev/null 2>&1 || useradd -u 200 -g informix -m -d /home/informix -s /bin/bash informix",           "user informix"),
            (f"echo 'informix:{password}' | chpasswd",                                                                          "informix password"),
        ]:
            result = ssh.execute_command(cmd, timeout=30, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"Failed to configure {desc}: {result['stderr']}")
                return False
        logger.info("✓ Group and user 'informix' configured")

    except Exception as e:
        logger.error(f"✗ SSH operation failed: {e}")
        return False
    finally:
        ssh.disconnect()

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX USER CREATED")
        logger.info("=" * 80)
    return True


def install_informix_binaries(
    config, logger, verbose: bool = True,
    installer_filename: str = "ibm.server.15.0.1.0.Linux.64.x86_64.tar",
    installer_source_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/informix",
    install_tmp_dir: str = "/opt/informix_tmp",
    install_dir: str = "/opt/ibm/informix",
    **kwargs
) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("INSTALL INFORMIX BINARIES ON SAUROPOD")
        logger.info("=" * 80)

    sauropod_ip, ssh = _get_ssh(config)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    import os
    local_path = f"{installer_source_dir}/{installer_filename}"
    if not os.path.exists(local_path):
        logger.error(f"Installer not found: {local_path}")
        return False

    remote_tar = f"{install_tmp_dir}/{installer_filename}"
    response_file = f"{install_tmp_dir}/response.properties"
    response_content = (
        "# Silent (unattended) installation mode\n"
        "INSTALLER_UI=SILENT\n"
        "\n"
        "# Installation directory\n"
        f"USER_INSTALL_DIR={install_dir}\n"
        "\n"
        "# Installation type: TYPICAL | FULL | CUSTOM\n"
        "CHOSEN_INSTALL_FEATURE_LIST=TYPICAL\n"
        "\n"
        "# License acceptance — must be TRUE to proceed\n"
        "LICENSE_ACCEPTED=TRUE\n"
        "\n"
        "# Edition: DEVELOPER | INNOVATORC | WORKGROUP | ENTERPRISE\n"
        "IDS_LICENSE_TYPE=DEVELOPER\n"
        "\n"
        "# Do not create the informix OS user automatically (already created above)\n"
        "CREATE_INFORMIX_USER=NO\n"
        "INFORMIX_USER=informix\n"
        "INFORMIX_GROUP=informix\n"
    )

    if not ssh.connect():
        logger.error(f"Failed to connect to sauropod ({sauropod_ip})")
        return False

    try:
        logger.info(f"➜ Creating {install_tmp_dir}...")
        result = ssh.execute_command(f"mkdir -p {install_tmp_dir}", timeout=15, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to create directory: {result['stderr']}")
            return False

        logger.info(f"➜ Uploading {installer_filename}...")
        if not ssh.upload_file(local_path, remote_tar):
            logger.error(f"Failed to upload {installer_filename}")
            return False
        logger.info("✓ Installer uploaded")

        logger.info(f"➜ Extracting outer tar in {install_tmp_dir}...")
        result = ssh.execute_command(f"tar -xf {remote_tar} -C {install_tmp_dir}", timeout=300, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to extract outer tar: {result['stderr']}")
            return False
        logger.info("✓ Outer tar extracted")

        logger.info(f"➜ Extracting inner tar {installer_filename}...")
        result = ssh.execute_command(f"cd {install_tmp_dir} && tar -xf {installer_filename}", timeout=300, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to extract inner tar: {result['stderr']}")
            return False
        logger.info("✓ Inner tar extracted")

        logger.info(f"➜ Writing {response_file}...")
        result = ssh.execute_command(
            f"cat > {response_file} << 'EOF'\n{response_content}EOF",
            timeout=30, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"Failed to write response file: {result['stderr']}")
            return False
        logger.info("✓ response.properties written")

        logger.info(f"➜ Running Informix silent installer (target: {install_dir})...")
        result = ssh.execute_command(
            f"cd {install_tmp_dir} && ./ids_install -i silent -f {response_file}",
            timeout=600, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"Informix installer failed: {result['stderr']}")
            return False
        logger.info("✓ Informix binaries installed")

    except Exception as e:
        logger.error(f"✗ SSH operation failed: {e}")
        return False
    finally:
        ssh.disconnect()

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX BINARIES INSTALLED")
        logger.info("=" * 80)
    return True


def open_informix_firewall_ports(
    config, logger, verbose: bool = True,
    informix_port: int = 9088,
    informix_admin_port: int = 9089,
    **kwargs
) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("OPEN INFORMIX FIREWALL PORTS ON SAUROPOD")
        logger.info("=" * 80)

    sauropod_ip, ssh = _get_ssh(config)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    if not ssh.connect():
        logger.error(f"Failed to connect to sauropod ({sauropod_ip})")
        return False

    try:
        for cmd, desc in [
            (f"firewall-cmd --permanent --add-port={informix_port}/tcp",       f"port {informix_port}/tcp"),
            (f"firewall-cmd --permanent --add-port={informix_admin_port}/tcp",  f"port {informix_admin_port}/tcp"),
            ("firewall-cmd --reload",                                            "firewall reload"),
        ]:
            result = ssh.execute_command(cmd, timeout=30, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"Failed to open {desc}: {result['stderr']}")
                return False
        logger.info(f"✓ Ports {informix_port}/tcp and {informix_admin_port}/tcp opened")

    except Exception as e:
        logger.error(f"✗ SSH operation failed: {e}")
        return False
    finally:
        ssh.disconnect()

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX FIREWALL PORTS OPENED")
        logger.info("=" * 80)
    return True

# Made with Bob

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
            "grep -q '^informix' /etc/security/limits.conf",
            timeout=10, print_output=False
        )
        if check['rc'] == 0:
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

# Made with Bob

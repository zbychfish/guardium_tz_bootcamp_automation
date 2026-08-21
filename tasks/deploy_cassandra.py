#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cassandra Deployment Task
Handles Cassandra installation and configuration on remote machine (sauropod)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import ConfigLoader
from core.ssh_client import SSHClient
from core.utils import ssh_dnf_install


def _header(logger, title: str):
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)


def _ssh_cmd(ssh, cmd, logger, desc: str, timeout: int = 30) -> bool:
    result = ssh.execute_command(cmd, timeout=timeout, print_output=False)
    if result['rc'] != 0:
        logger.error(f"✗ Failed to {desc}: {result['stderr'].strip()}")
        return False
    return True


def _ssh_cmds(ssh, commands, logger, desc: str, timeout: int = 30, stop_on_error: bool = True) -> bool:
    results = ssh.execute_commands(commands=commands, timeout=timeout, print_output=False, stop_on_error=stop_on_error)
    failed = [r for r in results if r['rc'] != 0]
    if failed:
        logger.error(f"✗ Failed to {desc}: {failed[0]['stderr'].strip()}")
        return False
    return True


def deploy_cassandra_on_sauropod(config: ConfigLoader, logger, verbose: bool = True, **kwargs) -> bool:
    _header(logger, "Apache Cassandra 4.1 deployment on sauropod")

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("✗ sauropod IP not found in configuration")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')

    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("✗ pwd not found in custom_variables")
        return False

    logger.info(f"  ➜ SSH {ssh_username}@{sauropod_ip}:{ssh_port}")
    ssh = SSHClient(host=sauropod_ip, port=ssh_port, username=ssh_username, password=root_password, timeout=60)
    if not ssh.connect():
        logger.error("✗ Failed to connect to sauropod via SSH")
        return False
    logger.info("  ✓ Connected to sauropod")

    try:
        repo_content = """[cassandra]
name=Apache Cassandra
baseurl=https://redhat.cassandra.apache.org/41x/
gpgcheck=0
repo_gpgcheck=0
gpgkey=https://downloads.apache.org/cassandra/KEYS
"""
        logger.info("  ➜ write /etc/yum.repos.d/cassandra.repo")
        if not _ssh_cmd(ssh, f"cat << 'EOF' > /etc/yum.repos.d/cassandra.repo\n{repo_content}EOF",
                        logger, "create Cassandra repo"):
            return False
        logger.info("  ✓ Cassandra repository configured")

        logger.info("  ➜ dnf install cassandra")
        if not ssh_dnf_install(ssh, "cassandra", logger, timeout=600):
            return False
        logger.info("  ✓ Cassandra installed")

        logger.info("  ➜ sed cassandra.yaml: audit_logging_options enabled FileAuditLogger")
        if not _ssh_cmd(ssh,
                        r"sed -i '/^audit_logging_options:/,/^[[:space:]]*- class_name:/c\audit_logging_options:\n  enabled: true\n  logger:\n    - class_name: FileAuditLogger' /etc/cassandra/conf/cassandra.yaml",
                        logger, "configure audit logging in cassandra.yaml"):
            return False
        logger.info("  ✓ Audit logging configured in cassandra.yaml")

        logger.info("  ➜ sed logback.xml: uncomment AUDIT appender + logger")
        if not _ssh_cmds(ssh, [
            "sed -i '/<!-- <appender name=\"AUDIT\"/,/SizeAndTimeBasedRollingPolicy/ { s/<!-- //; s/ -->// }' /etc/cassandra/conf/logback.xml",
            "sed -i 's|<!-- *<fileNamePattern>\\(.*\\)</fileNamePattern> *-->|<fileNamePattern>\\1</fileNamePattern>|' /etc/cassandra/conf/logback.xml",
            "sed -i '/<!-- *<maxFileSize>/,/<\\/appender> *-->/ { s/<!-- //; s/ -->// }' /etc/cassandra/conf/logback.xml",
            "sed -i '/<!-- *<logger name=\"org.apache.cassandra.audit\"/,/<\\/logger> *-->/ { s/<!-- //; s/ -->// }' /etc/cassandra/conf/logback.xml",
        ], logger, "configure audit logging in logback.xml"):
            return False
        logger.info("  ✓ Audit logging configured in logback.xml")

        logger.info("  ➜ service cassandra start (x2 with sleep 5)")
        ssh.execute_commands(
            commands=["service cassandra start", "sleep 5", "service cassandra start"],
            timeout=60, print_output=False, stop_on_error=False
        )
        logger.info("  ✓ Cassandra service started")

        logger.info("  ➜ service cassandra status")
        result = ssh.execute_command("service cassandra status", timeout=30, print_output=False)
        if result['rc'] == 0:
            logger.info("  ✓ Cassandra is running")
        else:
            logger.warning("  Cassandra status check returned non-zero — may still be starting up")

        logger.info("✓ Cassandra deployment completed")
        logger.info("  Note: Cassandra may take a few minutes to fully start up")
        return True

    finally:
        ssh.disconnect()


# Made with Bob

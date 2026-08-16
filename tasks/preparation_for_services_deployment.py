#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Preparation for Services Deployment Task
Handles system updates and downloading supporting files before service deployments
"""

import os
import sys
from pathlib import Path

# Add core modules to path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import execute_commands, download_and_extract, ConfigLoader
from core.ssh_client import SSHClient


def update_system_packages(config: ConfigLoader, logger, verbose: bool = True, **kwargs) -> bool:
    logger.info("Updating system packages on raptor (excluding kernel)")
    if not execute_commands(["dnf update --exclude=kernel* -y"], logger):
        logger.error("✗ System update failed")
        return False
    logger.info("✓ System packages updated")

    logger.info("Installing required packages on raptor")
    if not execute_commands(
        ["dnf install -y unzip lsof nmap-ncat python3.12 python3.12-pip python3.12-devel git bc java-11-openjdk compat-openssl11 gcc python3.9 python3.9-devel socat"],
        logger
    ):
        logger.error("✗ Package installation failed")
        return False
    logger.info("✓ Required packages installed")
    return True


def prepare_upload_content(config: ConfigLoader, logger, verbose: bool = True, **kwargs) -> bool:
    logger.info("Creating upload directory")
    if not execute_commands(["mkdir -p /opt/guardium_tz_bootcamp_automation/upload"], logger):
        logger.error("✗ Failed to create upload directory")
        return False

    logger.info("Downloading source_files from IBM COS")
    api_id   = config.get_custom_variable('s3_source_api_id')
    api_key  = config.get_custom_variable('s3_source_api_key')
    endpoint = config.get_custom_variable('s3_source_endpoint')
    bucket   = config.get_custom_variable('s3_source_bucket')

    if not all([api_id, api_key, endpoint, bucket]):
        logger.error("✗ Missing COS credentials in custom_variables (s3_source_api_id/key/endpoint/bucket)")
        return False

    try:
        import warnings
        warnings.filterwarnings("ignore", message=".*Boto3 will no longer support.*")
        import boto3
        from botocore.client import Config

        cos = boto3.client(
            "s3",
            aws_access_key_id=api_id,
            aws_secret_access_key=api_key,
            endpoint_url=endpoint,
            config=Config(signature_version="s3v4")
        )

        local_base = "/opt/guardium_tz_bootcamp_automation/upload/source_files/"
        paginator = cos.get_paginator("list_objects_v2")
        downloaded = 0
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                local_path = os.path.join(local_base, key)
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                logger.info(f"  ↓ {key}")
                cos.download_file(bucket, key, local_path)
                downloaded += 1

        logger.info(f"✓ Downloaded {downloaded} file(s) from COS")
    except Exception as e:
        logger.error(f"✗ Failed to download from IBM COS: {e}")
        return False

    logger.info("Cloning guardium_notes_dbtraffic repository")
    if not execute_commands(
        ["cd /opt/guardium_tz_bootcamp_automation/upload && rm -rf guardium_notes_dbtraffic && git clone https://github.com/zbychfish/guardium_notes_dbtraffic.git"],
        logger
    ):
        logger.error("✗ Failed to clone guardium_notes_dbtraffic")
        return False
    logger.info("✓ guardium_notes_dbtraffic cloned")
    return True


def configure_dbtraffic(config: ConfigLoader, logger, verbose: bool = True, **kwargs) -> bool:
    logger.info("Configuring guardium_notes_dbtraffic (venv, yaml configs, deps)")

    root_password = config.get_custom_variable("pwd")
    if not root_password:
        logger.error("✗ Custom variable 'pwd' not found")
        return False

    dbtraffic_dir = "/opt/guardium_tz_bootcamp_automation/upload/guardium_notes_dbtraffic"
    venv_python = f"{dbtraffic_dir}/venv/bin/python3.12"

    common_scenario = f"""\
workload:
  duration_seconds: 3600  # 60 minutes (used if --duration not specified)
  think_time_ms: 250      # normal speed (used if --speed not specified)

scenario:
  name: micro_payments
  options:
    locale: pl_PL
    seed_customers: 100
    app_users:
      - appuser1
      - appuser2
    admin_users:
      - adminuser1
    default_password: {root_password}"""

    commands = [
        f"""cat > {dbtraffic_dir}/config/pgsql.yaml <<'EOF'
# Admin config - for deploy-schema, seed-data, cleanup-schema, rebuild
# Use super user (postgres, tom, etc.) with full privileges
database:
  type: postgres
  host: raptor.demo.guardium
  port: 5432
  database: postgres
  user: tom
  password: {root_password}

{common_scenario}
EOF""",
        f"""cat > {dbtraffic_dir}/config/oracle_container_sauropod.yaml <<'EOF'
# Admin config - for deploy-schema, seed-data, cleanup-schema, rebuild
# Use super user (postgres, tom, etc.) with full privileges
database:
  type: oracle
  host: sauropod.demo.guardium
  port: 1522
  database: ORCLPDB1
  user: system
  password: {root_password}

{common_scenario}
EOF""",
        f"""cat > {dbtraffic_dir}/config/mssql_ceratops.yaml <<'EOF'
# Admin config - for deploy-schema, seed-data, cleanup-schema, rebuild
# Use super user (postgres, tom, etc.) with full privileges
database:
  type: mssql
  host: ceratops.demo.guardium
  port: 1433
  database: master
  user: sa
  password: {root_password}

{common_scenario}
EOF""",
        f"cd {dbtraffic_dir} && python3.12 -m venv venv",
        f"cd {dbtraffic_dir} && {venv_python} -m pip install --upgrade pip",
        f"cd {dbtraffic_dir} && {venv_python} -m pip install -e .",
        f"cd {dbtraffic_dir} && {venv_python} -m pip install -r requirements.txt",
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("✗ Failed to configure guardium_notes_dbtraffic")
        return False

    logger.info("✓ guardium_notes_dbtraffic configured")
    return True


def configure_swap(config: ConfigLoader, logger, verbose: bool = True, **kwargs) -> bool:
    logger.info("Configuring 8G swap file on raptor")
    commands = [
        "fallocate -l 8G /home/swapfile",
        "chmod 600 /home/swapfile",
        "mkswap /home/swapfile",
        "swapon /home/swapfile",
        r"grep -q '^/home/swapfile[[:space:]]\+swap[[:space:]]\+swap[[:space:]]\+defaults[[:space:]]\+0[[:space:]]\+0$' /etc/fstab || echo '/home/swapfile swap swap defaults 0 0' >> /etc/fstab",
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("✗ Swap file configuration failed")
        return False
    logger.info("✓ Swap file configured (8G, /home/swapfile)")
    return True


def install_packages_on_sauropod(config: ConfigLoader, logger, verbose: bool = True, **kwargs) -> bool:
    logger.info("Installing kernel-devel, Java 11 and podman on sauropod")

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.warning("sauropod not found in configuration — skipping")
        return True

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')

    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("✗ pwd not found in custom_variables")
        return False

    logger.info(f"  Connecting to sauropod ({sauropod_ip}:{ssh_port})")
    ssh = SSHClient(host=sauropod_ip, port=ssh_port, username=ssh_username, password=root_password, timeout=60)

    if not ssh.connect():
        logger.error("✗ Failed to connect to sauropod via SSH")
        return False

    try:
        install_cmd = "dnf install -y kernel-devel-$(uname -r) java-11-openjdk podman"
        result = ssh.execute_command(install_cmd, timeout=300, print_output=verbose)

        if result['rc'] != 0:
            if 'rhel-8-for-x86_64-appstream-eus-rpms' in result['stderr'] or '404' in result['stderr']:
                logger.warning("  EUS repository error — applying workaround")
                result = ssh.execute_command('subscription-manager repos --disable="*eus*"', timeout=60, print_output=verbose)
                if result['rc'] != 0:
                    logger.warning(f"  Failed to disable EUS repos (rc={result['rc']}), continuing")
                result = ssh.execute_command('subscription-manager repos --enable=rhel-8-for-x86_64-baseos-rpms --enable=rhel-8-for-x86_64-appstream-rpms', timeout=60, print_output=verbose)
                if result['rc'] != 0:
                    logger.error("✗ Failed to enable standard repositories")
                    return False
                logger.info("  ✓ Repositories updated, retrying installation")
                result = ssh.execute_command(install_cmd, timeout=300, print_output=verbose)
                if result['rc'] != 0:
                    logger.error("✗ Package installation failed after workaround")
                    return False
            else:
                logger.error("✗ Package installation failed on sauropod")
                return False

        logger.info("✓ kernel-devel, Java 11 and podman installed on sauropod")

        for action in ("start", "enable"):
            logger.info(f"➜ systemctl {action} podman-restart")
            result = ssh.execute_command(f"systemctl {action} podman-restart", timeout=30, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"✗ systemctl {action} podman-restart: {result['stderr']}")
                return False
            logger.info(f"✓ systemctl {action} podman-restart")

    finally:
        ssh.disconnect()

    return True

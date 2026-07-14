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


def preparation_for_services_deployment(config: ConfigLoader, logger, verbose: bool = True) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("Preparing system for services deployment")
        logger.info("=" * 80)
    
    # Step 1: Update system packages (excluding kernel)
    if verbose:
        logger.info("Step 1: Updating system packages (excluding kernel)")
    
    commands = [
        "dnf update --exclude=kernel* -y"
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("System update failed")
        return False
    
    if verbose:
        logger.info("✓ System packages updated successfully")
    
    # Step 2: Create necessary directories
    if verbose:
        logger.info("Step 2: Creating necessary directories")
    
    commands = [
        "mkdir -p /opt/guardium_tz_bootcamp_automation/upload"
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("Failed to create upload directory")
        return False
    
    if verbose:
        logger.info("✓ Directories created successfully")
    
    # Step 3: Download source_files from IBM COS
    if verbose:
        logger.info("Step 3: Downloading source_files from IBM COS")

    api_id  = config.get_custom_variable('s3_source_api_id')
    api_key = config.get_custom_variable('s3_source_api_key')
    endpoint = config.get_custom_variable('s3_source_endpoint')
    bucket  = config.get_custom_variable('s3_source_bucket')

    if not all([api_id, api_key, endpoint, bucket]):
        logger.error("Missing COS credentials in custom_variables (s3_source_api_id/key/endpoint/bucket)")
        return False

    try:
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
                if verbose:
                    logger.info(f"  ↓ {key}")
                cos.download_file(bucket, key, local_path)
                downloaded += 1

        if verbose:
            logger.info(f"✓ Downloaded {downloaded} file(s) from COS to {local_base}")

    except Exception as e:
        logger.error(f"Failed to download from IBM COS: {e}")
        return False
    
    # Step 4: Clone guardium_notes_dbtraffic repository
    if verbose:
        logger.info("Step 4: Cloning guardium_notes_dbtraffic repository")
    
    commands = [
        "cd /opt/guardium_tz_bootcamp_automation/upload && rm -rf guardium_notes_dbtraffic && git clone https://github.com/zbychfish/guardium_notes_dbtraffic.git"
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("Failed to clone guardium_notes_dbtraffic repository")
        return False
    
    if verbose:
        logger.info("✓ guardium_notes_dbtraffic repository cloned successfully")

    # Step 5: Install required packages on raptor
    if verbose:
        logger.info("Step 5: Installing required packages on raptor")

    commands = [
        "dnf install -y unzip lsof nmap-ncat python3.12 python3.12-pip python3.12-devel git bc java-11-openjdk compat-openssl11 gcc python3.9 python3.9-devel"
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("Package installation failed")
        return False

    if verbose:
        logger.info("✓ Required packages installed on raptor")

    # Step 6: Configure guardium_notes_dbtraffic (pgsql.yaml, venv, dependencies)
    if verbose:
        logger.info("Step 6: Configuring guardium_notes_dbtraffic")

    root_password = config.get_custom_variable("pwd")
    if not root_password:
        logger.error("Custom variable 'pwd' not found")
        return False

    dbtraffic_dir = "/opt/guardium_tz_bootcamp_automation/upload/guardium_notes_dbtraffic"
    venv_python = f"{dbtraffic_dir}/venv/bin/python"

    common_scenario = """\
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
    default_password: password"""

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
        f"cd {dbtraffic_dir} && python3.9 -m venv venv",
        f"cd {dbtraffic_dir} && {venv_python} -m pip install --upgrade pip",
        f"cd {dbtraffic_dir} && {venv_python} -m pip install wheel",
        f"cd {dbtraffic_dir} && {venv_python} -m pip install -e .",
        f"cd {dbtraffic_dir} && {venv_python} -m pip install --no-build-isolation -r requirements.txt",
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("Failed to configure guardium_notes_dbtraffic")
        return False

    driver_lib = f"{dbtraffic_dir}/venv/lib/python3.9/site-packages/onedb-odbc-driver/lib"
    ldconf_content = (
        f"{driver_lib}\n"
        f"{driver_lib}/cli\n"
        f"{driver_lib}/esql\n"
        f"{driver_lib}/client/csm\n"
    )
    ldconf_commands = [
        f"cat > /etc/ld.so.conf.d/onedb-ifx.conf << 'EOF'\n{ldconf_content}EOF",
        "ldconfig",
    ]
    if not execute_commands(ldconf_commands, logger, verbose):
        logger.error("Failed to configure onedb ODBC driver library paths")
        return False

    if verbose:
        logger.info("✓ onedb ODBC driver library paths configured")

    if verbose:
        logger.info("✓ Required packages installed on raptor")

    # Step 6: Configure swap file on raptor
    if verbose:
        logger.info("Step 6: Configuring swap file on raptor")

    commands = [
        "fallocate -l 8G /home/swapfile",
        "chmod 600 /home/swapfile",
        "mkswap /home/swapfile",
        "swapon /home/swapfile",
        r"grep -q '^/home/swapfile[[:space:]]\+swap[[:space:]]\+swap[[:space:]]\+defaults[[:space:]]\+0[[:space:]]\+0$' /etc/fstab || echo '/home/swapfile swap swap defaults 0 0' >> /etc/fstab"
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("Swap file configuration failed")
        return False

    if verbose:
        logger.info("✓ Swap file configured on raptor")

    # Step 7: Install Java on sauropod (required for Oracle SQLcl)
    if verbose:
        logger.info("Step 7: Installing Java 11 on sauropod")
    
    # Get sauropod machine IP (use private IP for internal communication)
    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.warning("Could not find sauropod machine in configuration, skipping Java installation")
    else:
        # Get SSH configuration
        ssh_config = config.get('ssh', {})
        ssh_port = ssh_config.get('port', 2223)
        ssh_username = ssh_config.get('username', 'root')
        
        # Get root password from custom_variables
        root_password = config.get_custom_variable('pwd')
        if not root_password:
            logger.warning("Root password (pwd) not found in custom_variables, skipping Java installation on sauropod")
            return True
        
        if verbose:
            logger.info(f"Connecting to sauropod at {sauropod_ip}:{ssh_port}")
        
        # Connect to sauropod via SSH
        ssh = SSHClient(
            host=sauropod_ip,
            port=ssh_port,
            username=ssh_username,
            password=root_password,
            timeout=60
        )
        
        if not ssh.connect():
            logger.error("Failed to connect to sauropod via SSH")
            return False
        
        try:
            install_cmd = "dnf install -y kernel-devel-$(uname -r) java-11-openjdk podman"
            if verbose:
                logger.info("Installing kernel-devel, Java 11 and podman")
            result = ssh.execute_command(install_cmd, timeout=300, print_output=verbose)

            if result['rc'] != 0:
                if 'rhel-8-for-x86_64-appstream-eus-rpms' in result['stderr'] or '404' in result['stderr']:
                    logger.warning("EUS repository error detected, applying workaround...")
                    result = ssh.execute_command('subscription-manager repos --disable="*eus*"', timeout=60, print_output=verbose)
                    if result['rc'] != 0:
                        logger.warning(f"Failed to disable EUS repos (rc={result['rc']}), continuing anyway")
                    result = ssh.execute_command('subscription-manager repos --enable=rhel-8-for-x86_64-baseos-rpms --enable=rhel-8-for-x86_64-appstream-rpms', timeout=60, print_output=verbose)
                    if result['rc'] != 0:
                        logger.error("Failed to enable standard repositories")
                        return False
                    logger.info("✓ Repository configuration updated, retrying installation")
                    result = ssh.execute_command(install_cmd, timeout=300, print_output=verbose)
                    if result['rc'] != 0:
                        logger.error("Failed to install packages on sauropod after workaround")
                        return False
                else:
                    logger.error("Failed to install packages on sauropod")
                    return False

            if verbose:
                logger.info("✓ kernel-devel, Java 11 and podman installed successfully on sauropod")

        finally:
            ssh.disconnect()
    
    if verbose:
        logger.info("=" * 80)
        logger.info("System preparation completed successfully")
        logger.info("=" * 80)
    
    return True


# Made with Bob

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Preparation for Services Deployment Task
Handles system updates and downloading supporting files before service deployments
"""

import sys
from pathlib import Path

# Add core modules to path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import execute_commands, download_and_extract, ConfigLoader
from core.ssh_client import SSHClient


def preparation_for_services_deployment(config: ConfigLoader, logger, verbose: bool = True) -> bool:
    """
    Prepare system for service deployments by:
    1. Updating system packages (excluding kernel)
    2. Downloading and extracting supporting files from Box
    
    Supporting files include:
    - MySQL database dumps (salesDB.sql)
    - MongoDB sample data (sampledata.archive.gz)
    - Other environment initialization files
    
    Args:
        logger: Logger instance
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
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
    
    # Step 3: Download and extract supporting files from Box
    if verbose:
        logger.info("Step 3: Downloading supporting files from Box")
    
    box_url = "https://ibm.box.com/shared/static/v7p17jj7oa95f42otbr49a9v0vs98ea0.zip"
    target_dir = "/opt/guardium_tz_bootcamp_automation/upload/"
    
    if verbose:
        logger.info(f"Downloading from: {box_url}")
        logger.info(f"Extracting to: {target_dir}")
    
    if not download_and_extract(box_url, target_dir, logger, verbose):
        logger.error("Failed to download and extract supporting files")
        return False
    
    if verbose:
        logger.info("✓ Supporting files downloaded and extracted successfully")
    
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
        "dnf install -y unzip lsof nmap-ncat python3.12 python3.12-pip python3.12-devel git"
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
    venv_pip = f"{dbtraffic_dir}/venv/bin/pip"

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
  host: raptor.guardium.demo
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
        f"cd {dbtraffic_dir} && rm -rf venv && python3.12 -m venv venv",
        f"cd {dbtraffic_dir} && {venv_python} -m pip install --upgrade pip",
        f"cd {dbtraffic_dir} && {venv_pip} install -e .",
        f"cd {dbtraffic_dir} && {venv_pip} install -r requirements.txt",
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("Failed to configure guardium_notes_dbtraffic")
        return False

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

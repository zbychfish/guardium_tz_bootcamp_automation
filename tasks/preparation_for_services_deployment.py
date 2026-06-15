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
        logger.info("=" * 80)
        logger.info("System preparation completed successfully")
        logger.info("=" * 80)
    
    # Step 4: RH packages installation for different tasks
    if verbose:
        logger.info("Step 4: Installing required packages on raptor")
    commands = [
        "dnf install unzip lsof nmap-ncat -y"
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("Package installation failed")
        return False
    
    if verbose:
        logger.info("✓ Required packages installed on raptor")
    
    # Step 5: Install Java on sauropod (required for Oracle SQLcl)
    if verbose:
        logger.info("Step 5: Installing Java 11 on sauropod")
    
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
            # Install Java 11 on sauropod
            java_install_cmd = "dnf install -y java-11-openjdk"
            result = ssh.execute_command(
                java_install_cmd,
                timeout=300,
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error("Failed to install Java 11 on sauropod")
                return False
            
            if verbose:
                logger.info("✓ Java 11 installed successfully on sauropod")
        
        finally:
            ssh.disconnect()
    
    if verbose:
        logger.info("=" * 80)
        logger.info("System preparation completed successfully")
        logger.info("=" * 80)
    
    return True


# Made with Bob

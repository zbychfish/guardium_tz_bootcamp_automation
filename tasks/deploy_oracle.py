#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Oracle Deployment Task
Handles Oracle installation and configuration on remote machine (sauropod)
"""

import sys
from pathlib import Path

# Add core modules to path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import ConfigLoader
from core.ssh_client import SSHClient


def deploy_oracle_on_sauropod(config: ConfigLoader, logger, verbose: bool = True) -> bool:
    """
    Deploy Oracle Database 21c on remote machine (sauropod).
    
    This function:
    1. Connects to sauropod machine via SSH
    2. Downloads Oracle preinstall package
    3. Installs compat-openssl10 dependency
    4. Installs Oracle preinstall package
    
    Args:
        config: ConfigLoader instance with machine information
        logger: Logger instance
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    if verbose:
        logger.info("=" * 80)
        logger.info("Oracle Database 21c deployment on sauropod")
        logger.info("=" * 80)
    
    # Get sauropod machine IP (use private IP for internal communication)
    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Could not find sauropod machine in configuration")
        return False
    
    # Get SSH configuration
    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')
    
    # Get root password from custom_variables
    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("Root password (pwd) not found in custom_variables")
        return False
    
    if verbose:
        logger.info(f"Connecting to sauropod at {sauropod_ip}:{ssh_port}")
    
    try:
        # Connect to sauropod
        with SSHClient(
            host=sauropod_ip,
            username=ssh_username,
            password=root_password,
            port=ssh_port,
            timeout=60
        ) as ssh:
            
            if verbose:
                logger.info("✓ Connected to sauropod")
            
            # Define commands to execute
            commands = [
                # Step 1: Download Oracle preinstall package
                "curl -o /tmp/oracle-database-preinstall-21c.rpm https://yum.oracle.com/repo/OracleLinux/OL8/appstream/x86_64/getPackage/oracle-database-preinstall-21c-1.0-1.el8.x86_64.rpm",
                
                # Step 2: Install compat-openssl10 dependency
                "dnf install -y --nogpgcheck https://yum.oracle.com/repo/OracleLinux/OL8/appstream/x86_64/getPackage/compat-openssl10-1.0.2o-4.el8_6.x86_64.rpm",
                
                # Step 3: Install Oracle preinstall package
                "dnf install -y --nogpgcheck /tmp/oracle-database-preinstall-21c.rpm"
            ]
            
            # Execute commands
            if verbose:
                logger.info(f"Executing {len(commands)} installation commands")
            
            results = ssh.execute_commands(
                commands=commands,
                timeout=600,  # 10 minutes timeout for each command
                print_output=verbose,
                stop_on_error=True
            )
            
            # Check if all commands succeeded
            failed = [r for r in results if r['rc'] != 0]
            if failed:
                logger.error(f"Failed to execute {len(failed)} command(s)")
                for result in failed:
                    logger.error(f"Failed command: {result['cmd']}")
                    if result['stderr']:
                        logger.error(f"Error: {result['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ All Oracle installation commands completed successfully")
                logger.info("=" * 80)
            
            return True
            
    except Exception as e:
        logger.error(f"Error during Oracle deployment: {e}")
        return False


# Made with Bob
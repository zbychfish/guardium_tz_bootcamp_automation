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
            
            # # Step 1: Install Oracle prerequisites
            # if verbose:
            #     logger.info("Step 1: Installing Oracle prerequisites")
            
            # prereq_commands = [
            #     "curl -o /tmp/oracle-database-preinstall-21c.rpm https://yum.oracle.com/repo/OracleLinux/OL8/appstream/x86_64/getPackage/oracle-database-preinstall-21c-1.0-1.el8.x86_64.rpm",
            #     "dnf install -y --nogpgcheck https://yum.oracle.com/repo/OracleLinux/OL8/appstream/x86_64/getPackage/compat-openssl10-1.0.2o-4.el8_6.x86_64.rpm",
            #     "dnf install -y --nogpgcheck /tmp/oracle-database-preinstall-21c.rpm"
            # ]
            
            # results = ssh.execute_commands(
            #     commands=prereq_commands,
            #     timeout=600,
            #     print_output=verbose,
            #     stop_on_error=True
            # )
            
            # failed = [r for r in results if r['rc'] != 0]
            # if failed:
            #     logger.error("Failed to install Oracle prerequisites")
            #     return False
            
            # if verbose:
            #     logger.info("✓ Oracle prerequisites installed")
            
            # Step 2: Create Oracle directories
            if verbose:
                logger.info("Step 2: Creating Oracle directories")
            
            dir_commands = [
                "mkdir -p /u01/app/oracle/product/21c/dbhome_1",
                "chown -R oracle:oinstall /u01",
                "chmod -R 775 /u01"
            ]
            
            results = ssh.execute_commands(
                commands=dir_commands,
                timeout=60,
                print_output=verbose,
                stop_on_error=True
            )
            
            failed = [r for r in results if r['rc'] != 0]
            if failed:
                logger.error("Failed to create Oracle directories")
                return False
            
            if verbose:
                logger.info("✓ Oracle directories created")
            
            # Step 3: Configure oracle user environment
            if verbose:
                logger.info("Step 3: Configuring oracle user environment")
            
            bashrc_content = """
# Oracle environment variables
export ORACLE_BASE=/u01/app/oracle
export ORACLE_HOME=$ORACLE_BASE/product/21c/dbhome_1
export PATH=$ORACLE_HOME/bin:$PATH
"""
            
            # Append to oracle's .bashrc
            result = ssh.execute_command(
                f"echo '{bashrc_content}' >> /home/oracle/.bashrc",
                timeout=30,
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error("Failed to configure oracle user environment")
                return False
            
            if verbose:
                logger.info("✓ Oracle user environment configured")
            
            # Step 4: Copy Oracle installation archive from raptor
            if verbose:
                logger.info("Step 4: Copying Oracle installation archive from raptor")
            
            # Get raptor IP
            raptor_ip = config.get_machine_ip('raptor', use_private=True)
            if not raptor_ip:
                logger.error("Could not find raptor machine IP")
                return False
            
            source_file = "/opt/guardium_tz_bootcamp_automation/upload/source_files/env_init/LINUX.X64_213000_db_home.zip"
            
            # Use scp to copy file from raptor to sauropod
            scp_cmd = f"scp -P {ssh_port} -o StrictHostKeyChecking=no root@{raptor_ip}:{source_file} /home/oracle/"
            
            result = ssh.execute_command(
                scp_cmd,
                timeout=1800,  # 30 minutes for large file transfer
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error(f"Failed to copy Oracle installation archive: {result['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ Oracle installation archive copied")
            
            # Step 5: Unzip Oracle installation archive as oracle user
            if verbose:
                logger.info("Step 5: Extracting Oracle installation archive")
            
            unzip_cmd = "su - oracle -c 'unzip -q /home/oracle/LINUX.X64_213000_db_home.zip -d $ORACLE_HOME'"
            
            result = ssh.execute_command(
                unzip_cmd,
                timeout=1800,  # 30 minutes for extraction
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error(f"Failed to extract Oracle installation archive: {result['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ Oracle installation archive extracted")
                logger.info("=" * 80)
            
            return True
            
    except Exception as e:
        logger.error(f"Error during Oracle deployment: {e}")
        return False


# Made with Bob
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MySQL Deployment Task
Handles MySQL installation and configuration on local machine (raptor)
"""

import sys
from pathlib import Path

# Add core modules to path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import execute_local_command, execute_mysql_sql, ConfigLoader, download_and_extract
import re


def set_mysql_root_password(new_password: str, logger, verbose: bool = True) -> bool:
    """
    Set MySQL root password by extracting temporary password and changing it.
    Also creates root@'%' user with the same password for remote access.
    
    Args:
        new_password: New password to set for root user
        logger: Logger instance
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    if verbose:
        logger.info("=" * 80)
        logger.info("Setting MySQL root password")
        logger.info("=" * 80)
    
    # Step 1: Extract temporary password from mysqld.log
    if verbose:
        logger.info("Step 1: Extracting temporary password from /var/log/mysqld.log")
    result = execute_local_command(
        "sudo grep 'temporary password' /var/log/mysqld.log",
        logger,
        verbose
    )
    
    if result['rc'] != 0:
        logger.error("Failed to extract temporary password from mysqld.log")
        return False
    
    # Parse temporary password from output
    # Expected format: "A temporary password is generated for root@localhost: <password>"
    temp_password_match = re.search(r'temporary password.*:\s*(\S+)', result['stdout'])
    if not temp_password_match:
        logger.error("Could not parse temporary password from log")
        logger.error(f"Log output: {result['stdout']}")
        return False
    
    temp_password = temp_password_match.group(1)
    if verbose:
        logger.info("Temporary password extracted successfully")
    
    # Step 2: Change root@localhost password and create root@'%'
    if verbose:
        logger.info("Step 2: Changing root@localhost password and creating root@'%' user")
    
    sql_commands = f"""ALTER USER 'root'@'localhost' IDENTIFIED BY '{new_password}';
CREATE USER IF NOT EXISTS 'root'@'%' IDENTIFIED BY '{new_password}';
GRANT ALL PRIVILEGES ON *.* TO 'root'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;
"""
    
    result = execute_mysql_sql(
        sql_commands=sql_commands,
        username="root",
        password=temp_password,
        additional_options="--connect-expired-password",
        logger=logger,
        verbose=verbose
    )
    
    if result['rc'] != 0:
        logger.error("Failed to change MySQL root password")
        if result['stderr']:
            logger.error(f"MySQL error: {result['stderr']}")
        return False
    
    if verbose:
        logger.info("✓ MySQL root password changed successfully")
        logger.info("✓ Created root@'%' user for remote access")
        logger.info("=" * 80)
    
    return True


def create_mysql_superadmins(password: str, logger, verbose: bool = True) -> bool:
    """
    Create MySQL superadmin users 'tom' and 'jerry' with full privileges.
    
    Args:
        password: Password to set for both users
        logger: Logger instance
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    if verbose:
        logger.info("=" * 80)
        logger.info("Creating MySQL superadmin users (tom, jerry)")
        logger.info("=" * 80)
    
    sql_commands = f"""CREATE USER IF NOT EXISTS 'tom'@'%' IDENTIFIED BY '{password}';
CREATE USER IF NOT EXISTS 'jerry'@'%' IDENTIFIED BY '{password}';
GRANT ALL PRIVILEGES ON *.* TO 'tom'@'%' WITH GRANT OPTION;
GRANT ALL PRIVILEGES ON *.* TO 'jerry'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;
"""
    
    result = execute_mysql_sql(
        sql_commands=sql_commands,
        username="root",
        password=password,
        logger=logger,
        verbose=verbose
    )
    
    if result['rc'] != 0:
        logger.error("Failed to create MySQL superadmin users")
        if result['stderr']:
            logger.error(f"MySQL error: {result['stderr']}")
        return False
    
    if verbose:
        logger.info("✓ Created superadmin user 'tom'@'%'")
        logger.info("✓ Created superadmin user 'jerry'@'%'")
        logger.info("=" * 80)
    
    return True


def create_mysql_config_file(password: str, logger, verbose: bool = True) -> bool:
    """
    Create ~/.my.cnf file for root user with MySQL credentials.
    This allows passwordless MySQL access for root user.
    
    Args:
        password: MySQL root password
        logger: Logger instance
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    if verbose:
        logger.info("=" * 80)
        logger.info("Creating ~/.my.cnf configuration file")
        logger.info("=" * 80)
    
    import os
    
    # Get root home directory
    home_dir = os.path.expanduser("~")
    my_cnf_path = os.path.join(home_dir, ".my.cnf")
    
    # Create .my.cnf content
    my_cnf_content = f"""[client]
user=root
password={password}
"""
    
    try:
        # Write .my.cnf file
        if verbose:
            logger.info(f"Writing configuration to: {my_cnf_path}")
        
        with open(my_cnf_path, 'w') as f:
            f.write(my_cnf_content)
        
        # Set permissions to 600 (read/write for owner only)
        os.chmod(my_cnf_path, 0o600)
        
        if verbose:
            logger.info(f"✓ Created {my_cnf_path}")
            logger.info("✓ Set permissions to 600")
            logger.info("=" * 80)
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to create .my.cnf file: {e}")
        return False


def deploy_mysql_on_raptor(logger, verbose: bool = True) -> bool:
    """
    Deploy MySQL on local machine (raptor).
    
    This function executes a series of commands to install and configure MySQL.
    Commands should be added/modified as needed.
    
    Args:
        logger: Logger instance
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    if verbose:
        logger.info("=" * 80)
        logger.info("Starting MySQL deployment on raptor")
        logger.info("=" * 80)
    
    config = ConfigLoader("config/config.yaml", "/root/machines_info.json")
    password = config.get_custom_variable('pwd')

    # Update system and create necessary directories
    commands = [
        "dnf update --exclude=kernel* -y",
        "mkdir -p /opt/guardium_tz_bootcamp_automation/upload"
    ]

    for i, command in enumerate(commands, 1):
        logger.info(f"Step {i}/{len(commands)}: {command}")
        
        result = execute_local_command(command, logger)
        
        if result['rc'] != 0:
            logger.error(f"Command failed: {command}")
            logger.error("MySQL deployment failed")
            return False

    # Create mysql defaults file with password to avoid prompting for password
    create_mysql_config_file(password, logger, verbose)

    # Download supporting files
    if not download_and_extract("https://ibm.box.com/shared/static/v7p17jj7oa95f42otbr49a9v0vs98ea0.zip", "/opt/guardium_tz_bootcamp_automation/upload/", logger, verbose):
        logger.error("Failed to create MySQL superadmin users")
        return False

    # List of commands to execute
    # Add your MySQL installation commands here
    # commands = [
    #     "rpm --import https://repo.mysql.com/RPM-GPG-KEY-mysql-2023",
    #     "dnf install -y https://dev.mysql.com/get/mysql84-community-release-el9-4.noarch.rpm",
    #     "dnf install -y mysql-community-server"
    #     "systemctl start mysqld",
    #     "systemctl enable mysqld"
    # ]
    
    # # Execute each command
    # for i, command in enumerate(commands, 1):
    #     logger.info(f"Step {i}/{len(commands)}: {command}")
        
    #     result = execute_local_command(command, logger)
        
    #     if result['rc'] != 0:
    #         logger.error(f"Command failed: {command}")
    #         logger.error("MySQL deployment failed")
    #         return False
    
    # Set root password
    # if not set_mysql_root_password(password, logger, verbose):
    #     logger.error("Failed to set MySQL root password")
    #     return False
    
    # Create ~/.my.cnf configuration file
    if not create_mysql_config_file(password, logger, verbose):
        logger.error("Failed to create MySQL configuration file")
        return False
    
    # Create superadmin users
    # if not create_mysql_superadmins(password, logger, verbose):
    #     logger.error("Failed to create MySQL superadmin users")
    #     return False

    if verbose:
        logger.info("=" * 80)
        logger.info("MySQL deployment completed successfully")
        logger.info("=" * 80)
    return True


# Made with Bob
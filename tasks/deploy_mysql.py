#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MySQL Deployment Task
Handles MySQL installation and configuration on local machine (raptor)
"""

from calendar import c
import sys
from pathlib import Path

# Add core modules to path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import execute_local_command, execute_mysql_sql, ConfigLoader
import re


def set_mysql_root_password(new_password: str, logger) -> bool:
    """
    Set MySQL root password by extracting temporary password and changing it.
    Also creates root@'%' user with the same password for remote access.
    
    Args:
        new_password: New password to set for root user
        logger: Logger instance
        
    Returns:
        True if successful, False otherwise
    """
    logger.info("=" * 80)
    logger.info("Setting MySQL root password")
    logger.info("=" * 80)
    
    # Step 1: Extract temporary password from mysqld.log
    logger.info("Step 1: Extracting temporary password from /var/log/mysqld.log")
    result = execute_local_command(
        "sudo grep 'temporary password' /var/log/mysqld.log",
        logger
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
    logger.info("Temporary password extracted successfully")
    
    # Step 2: Change root@localhost password and create root@'%'
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
        logger=logger
    )
    
    if result['rc'] != 0:
        logger.error("Failed to change MySQL root password")
        if result['stderr']:
            logger.error(f"MySQL error: {result['stderr']}")
        return False
    
    logger.info("✓ MySQL root password changed successfully")
    logger.info("✓ Created root@'%' user for remote access")
    logger.info("=" * 80)
    
    return True


def deploy_mysql_on_raptor(logger) -> bool:
    """
    Deploy MySQL on local machine (raptor).
    
    This function executes a series of commands to install and configure MySQL.
    Commands should be added/modified as needed.
    
    Args:
        logger: Logger instance
        
    Returns:
        True if successful, False otherwise
    """
    logger.info("=" * 80)
    logger.info("Starting MySQL deployment on raptor")
    logger.info("=" * 80)
    
    # List of commands to execute
    # Add your MySQL installation commands here
    # commands = [
    #     "dnf update --exclude=kernel* -y",
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
    
    config = ConfigLoader("config/config.yaml", "/root/machines_info.json")
    password = config.get_custom_variable('pwd')
    set_mysql_root_password(password, logger)





    logger.info("=" * 80)
    logger.info("MySQL deployment completed successfully")
    logger.info("=" * 80)
    return True


# Made with Bob
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

from core import execute_local_command


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
    commands = [
        "dnf update --exclude=kernel* -y",
        "dnf install -y https://dev.mysql.com/get/mysql80-community-release-el9-1.noarch.rpm",
        "dnf install -y mysql-community-server"

    ]
    
    # If no commands defined yet, just log and return success
    if not commands:
        logger.warning("No MySQL deployment commands defined yet")
        logger.info("Add commands to tasks/deploy_mysql.py in the 'commands' list")
        logger.info("MySQL deployment task placeholder completed")
        return True
    
    # Execute each command
    for i, command in enumerate(commands, 1):
        logger.info(f"Step {i}/{len(commands)}: {command}")
        
        result = execute_local_command(command, logger)
        
        if result['rc'] != 0:
            logger.error(f"Command failed: {command}")
            logger.error("MySQL deployment failed")
            return False
    
    logger.info("=" * 80)
    logger.info("MySQL deployment completed successfully")
    logger.info("=" * 80)
    return True


# Made with Bob
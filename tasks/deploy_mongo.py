#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MongoDB Deployment Task
Handles MongoDB installation and configuration on local machine (raptor)
"""

import sys
from pathlib import Path

# Add core modules to path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import execute_local_command, execute_commands, execute_mongo_js, modify_config_file, write_file, ConfigLoader


def create_mongodb_repo_file(logger, verbose: bool = True) -> bool:
    """
    Create MongoDB Enterprise repository file at /etc/yum.repos.d/mongodb-enterprise-8.3.repo
    
    Args:
        logger: Logger instance
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    if verbose:
        logger.info("=" * 80)
        logger.info("Creating MongoDB Enterprise repository file")
        logger.info("=" * 80)
    
    repo_file_path = "/etc/yum.repos.d/mongodb-enterprise-8.3.repo"
    repo_content = """[mongodb-enterprise-8.3]
name=MongoDB Enterprise Repository
baseurl=https://repo.mongodb.com/yum/redhat/9/mongodb-enterprise/8.3/$basearch/
gpgcheck=1
enabled=1
gpgkey=https://pgp.mongodb.com/server-8.0.asc
"""
    
    try:
        if verbose:
            logger.info(f"Writing repository configuration to: {repo_file_path}")
        
        # Write the repository file using core function
        write_file(repo_file_path, repo_content)
        
        if verbose:
            logger.info(f"✓ Created {repo_file_path}")
            logger.info("=" * 80)
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to create MongoDB repository file: {e}")
        return False


def create_mongodb_admin_user(password: str, logger, verbose: bool = True) -> bool:
    """
    Create MongoDB admin user with root role.
    
    Args:
        password: Password for admin user
        logger: Logger instance
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    if verbose:
        logger.info("=" * 80)
        logger.info("Creating MongoDB admin user")
        logger.info("=" * 80)
    
    # JavaScript commands to create admin user
    # Note: We connect directly to admin database, so no need for 'use admin'
    js_commands = f"""db.createUser({{
  user: "admin",
  pwd: "{password}",
  roles: [ {{ role: "root", db: "admin" }} ]
}})
"""
    
    result = execute_mongo_js(
        js_commands=js_commands,
        database="admin",
        logger=logger,
        verbose=verbose
    )
    
    if result['rc'] != 0:
        logger.error("Failed to create MongoDB admin user")
        if result['stderr']:
            logger.error(f"MongoDB error: {result['stderr']}")
        if result['stdout']:
            logger.error(f"MongoDB output: {result['stdout']}")
        return False
    
    if verbose:
        logger.info("✓ MongoDB admin user created successfully")
        logger.info("=" * 80)
    
    return True


def enable_mongodb_authorization(logger, verbose: bool = True) -> bool:
    """
    Enable authorization in MongoDB configuration file.
    Adds security.authorization setting to /etc/mongod.conf
    
    Args:
        logger: Logger instance
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    if verbose:
        logger.info("=" * 80)
        logger.info("Enabling MongoDB authorization")
        logger.info("=" * 80)
    
    mongod_conf_path = "/etc/mongod.conf"
    security_config = """security:
  authorization: enabled
"""
    
    if verbose:
        logger.info(f"Adding authorization config to: {mongod_conf_path}")
    
    # Append security configuration to the end of file
    success = modify_config_file(
        path=mongod_conf_path,
        content=security_config,
        mode='append',
        backup=True,
        logger=logger
    )
    
    if not success:
        logger.error("Failed to enable MongoDB authorization")
        return False
    
    if verbose:
        logger.info(f"✓ Added authorization configuration")
        logger.info("=" * 80)
    
    return True


def deploy_mongo_on_raptor(logger, verbose: bool = True) -> bool:
    """
    Deploy MongoDB on local machine (raptor).
    
    This function executes a series of commands to install and configure MongoDB.
    Commands should be added/modified as needed.
    
    Args:
        logger: Logger instance
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    if verbose:
        logger.info("=" * 80)
        logger.info("Starting MongoDB deployment on raptor")
        logger.info("=" * 80)
    
    config = ConfigLoader("config/config.yaml", "/root/machines_info.json")
    password = config.get_custom_variable('pwd')
    
    # Create MongoDB repository file
    if not create_mongodb_repo_file(logger, verbose):
        logger.error("Failed to create MongoDB repository file")
        return False
    
    # Install MongoDB
    commands = [
        # "dnf install -y mongodb-enterprise-database",
        # "dnf install -y mongodb-enterprise-tools",
        # "dnf install -y mongodb-mongosh-shared-openssl3",
        "dnf install -y mongodb-enterprise",
        "systemctl enable mongod",
        "systemctl start mongod",
        "sleep 5",  # Wait for MongoDB to be ready
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("MongoDB installation failed")
        return False
    
    # Verify MongoDB is running
    if verbose:
        logger.info("Verifying MongoDB is running...")
    verify_result = execute_local_command("systemctl is-active mongod", logger, verbose=False)
    if verify_result['rc'] != 0:
        logger.error("MongoDB service is not running")
        return False
    
    # Create admin user (before enabling authorization)
    if not create_mongodb_admin_user(password, logger, verbose):
        logger.error("Failed to create MongoDB admin user")
        return False
    
    # Enable authorization
    if not enable_mongodb_authorization(logger, verbose):
        logger.error("Failed to enable MongoDB authorization")
        return False
    
    # Restart MongoDB to apply authorization settings
    commands = [
        "systemctl restart mongod"
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("Failed to restart MongoDB")
        return False

    if verbose:
        logger.info("=" * 80)
        logger.info("MongoDB deployment completed successfully")
        logger.info("=" * 80)
    
    return True


# Made with Bob
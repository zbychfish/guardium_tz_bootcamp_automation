#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MongoDB Deployment Task
Handles MongoDB installation and configuration on local machine (raptor)
"""

import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

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
    
    # Escape single quotes in password for JavaScript
    escaped_password = password.replace("'", "\\'").replace('"', '\\"')
    
    # JavaScript commands to create admin user
    # Note: We connect directly to admin database, so no need for 'use admin'
    js_commands = f"""db.createUser({{
  user: "admin",
  pwd: "{escaped_password}",
  roles: [ {{ role: "root", db: "admin" }} ]
}})
"""
    
    if verbose:
        logger.info("Executing user creation command...")
    
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
    
    # Verify user was created
    if verbose:
        logger.info("Verifying user creation...")
    
    verify_js = """db.getUsers()"""
    verify_result = execute_mongo_js(
        js_commands=verify_js,
        database="admin",
        logger=logger,
        verbose=verbose
    )
    
    if verify_result['rc'] == 0:
        if verbose:
            logger.info(f"Users in admin database: {verify_result['stdout']}")
    
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


def create_mongo_env_file(password: str, logger, verbose: bool = True) -> bool:
    """
    Create .mongo_env file in /root with MongoDB connection URI.
    Also updates .bashrc to source this file.
    
    Args:
        password: MongoDB admin password
        logger: Logger instance
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    if verbose:
        logger.info("=" * 80)
        logger.info("Creating MongoDB environment file")
        logger.info("=" * 80)
    
    # URL-encode password to handle special characters
    encoded_password = quote_plus(password)
    
    # Create .mongo_env content
    mongo_env_path = "/root/.mongo_env"
    mongo_env_content = f"export MONGO_URI='mongodb://admin:{encoded_password}@localhost:27017/admin'\n"
    
    try:
        if verbose:
            logger.info(f"Writing MongoDB environment file to: {mongo_env_path}")
        
        # Write the .mongo_env file
        write_file(mongo_env_path, mongo_env_content)
        
        # Set secure permissions (readable only by owner)
        result = execute_local_command(f"chmod 600 {mongo_env_path}", logger, verbose=False)
        if result['rc'] != 0:
            logger.error(f"Failed to set permissions on {mongo_env_path}")
            return False
        
        if verbose:
            logger.info(f"✓ Created {mongo_env_path}")
        
        # Update .bashrc to source .mongo_env (without checking if exists)
        bashrc_path = "/root/.bashrc"
        
        if verbose:
            logger.info(f"Adding .mongo_env sourcing to {bashrc_path}")
        
        # Use heredoc to append multi-line content to .bashrc
        append_cmd = f"""cat >> {bashrc_path} << 'EOF'

# Load MongoDB environment variables
if [ -f /root/.mongo_env ]; then
    . /root/.mongo_env
fi
EOF"""
        
        append_result = execute_local_command(
            append_cmd,
            logger,
            verbose=False
        )
        
        if append_result['rc'] == 0:
            if verbose:
                logger.info(f"✓ Updated {bashrc_path} to source .mongo_env")
        else:
            # Non-critical - MongoDB is already configured and working
            if verbose:
                logger.debug(f"Note: Could not update {bashrc_path} (non-critical)")
        
        if verbose:
            logger.info("=" * 80)
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to create MongoDB environment file: {e}")
        return False


def import_mongodb_sample_data(logger, verbose: bool = True) -> bool:
    """
    Import sample data into MongoDB from compressed archive.
    Uses the MONGO_URI environment variable for connection.
    
    Args:
        logger: Logger instance
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    if verbose:
        logger.info("=" * 80)
        logger.info("Importing MongoDB sample data")
        logger.info("=" * 80)
    
    archive_path = "/opt/guardium_tz_bootcamp_automation/upload/source_files/env_init/sampledata.archive.gz"
    
    # Check if archive exists
    check_result = execute_local_command(
        f"test -f {archive_path}",
        logger,
        verbose=False
    )
    
    if check_result['rc'] != 0:
        logger.warning(f"Sample data archive not found: {archive_path}")
        logger.warning("Skipping data import")
        return True  # Not a critical error
    
    if verbose:
        logger.info(f"Found sample data archive: {archive_path}")
        logger.info("Importing data using mongorestore...")
    
    # Build mongorestore command with --quiet flag if not verbose
    quiet_flag = "--quiet" if not verbose else ""
    
    # Source .mongo_env in the same shell session and execute import
    # This ensures MONGO_URI is available for the mongorestore command
    # Use single quotes around the bash -c command to avoid escaping issues
    full_command = f"bash -c '. /root/.mongo_env && gunzip -c {archive_path} | mongorestore --archive --uri=\"$MONGO_URI\" --nsInclude=\"*\" {quiet_flag}'"
    
    result = execute_local_command(full_command, logger, verbose=verbose)
    
    if result['rc'] != 0:
        logger.error("Failed to import MongoDB sample data")
        if result['stderr']:
            logger.error(f"Error: {result['stderr']}")
        return False
    
    if verbose:
        logger.info("✓ Sample data imported successfully")
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
        "dnf install -y mongodb-enterprise-database mongodb-enterprise-tools mongodb-mongosh-shared-openssl3 mongodb-enterprise",
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
    if verbose:
        logger.info("Restarting MongoDB to apply authorization settings...")
    
    commands = [
        "systemctl restart mongod",
        "sleep 5",  # Wait for MongoDB to be ready
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("MongoDB restart failed")
        return False
    
    # Create .mongo_env file with connection URI
    if not create_mongo_env_file(password, logger, verbose):
        logger.error("Failed to create MongoDB environment file")
        return False
    
    # Import sample data
    if not import_mongodb_sample_data(logger, verbose):
        logger.error("Failed to import MongoDB sample data")
        return False

    if verbose:
        logger.info("=" * 80)
        logger.info("MongoDB deployment completed successfully")
        logger.info("=" * 80)
    
    return True


# Made with Bob
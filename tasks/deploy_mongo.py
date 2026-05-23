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

from core import execute_local_command, execute_commands, ConfigLoader


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
        
        # Write the repository file
        with open(repo_file_path, 'w') as f:
            f.write(repo_content)
        
        if verbose:
            logger.info(f"✓ Created {repo_file_path}")
            logger.info("=" * 80)
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to create MongoDB repository file: {e}")
        return False


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
    
    # Create MongoDB repository file
    if not create_mongodb_repo_file(logger, verbose):
        logger.error("Failed to create MongoDB repository file")
        return False
    
    # Install MongoDB
    commands = [
        "dnf install -y mongodb-enterprise-database",
        "dnf install -y mongodb-enterprise-tools",
        "dnf install -y mongodb-mongosh-shared-openssl3"
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("Initial setup commands failed")
        return False
        
    if verbose:
        logger.info("=" * 80)
        logger.info("MongoDB deployment completed successfully")
        logger.info("=" * 80)
    
    return True


# Made with Bob
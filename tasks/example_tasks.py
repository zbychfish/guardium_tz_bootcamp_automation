#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Example Tasks Module
Template for creating automation tasks
"""

import sys
from pathlib import Path

# Add parent directory to path to import core modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import SSHClient, get_logger, ConfigLoader

logger = get_logger("ExampleTasks")


def example_task_check_connectivity(config: ConfigLoader) -> bool:
    """
    Example task: Check SSH connectivity to a machine.
    
    Args:
        config: Configuration loader instance
        
    Returns:
        True if successful, False otherwise
    """
    logger.info("Checking SSH connectivity...")
    
    # Get machine configuration
    host = config.get('machines.example_machine.host')
    username = config.get('ssh.username', 'root')
    
    if not host:
        logger.error("Machine host not configured")
        return False
    
    # Create SSH client and test connection
    ssh = SSHClient(host=host, username=username)
    
    if ssh.connect():
        logger.info(f"✓ Successfully connected to {host}")
        
        # Execute a simple command
        result = ssh.execute_command("hostname", print_output=False)
        logger.info(f"Remote hostname: {result['stdout'].strip()}")
        
        ssh.disconnect()
        return True
    else:
        logger.error(f"✗ Failed to connect to {host}")
        return False


def example_task_install_package(config: ConfigLoader, package_name: str = "vim") -> bool:
    """
    Example task: Install a package on remote machine.
    
    Args:
        config: Configuration loader instance
        package_name: Name of package to install
        
    Returns:
        True if successful, False otherwise
    """
    logger.info(f"Installing package: {package_name}")
    
    host = config.get('machines.example_machine.host')
    username = config.get('ssh.username', 'root')
    
    with SSHClient(host=host, username=username) as ssh:
        # Detect package manager and install
        commands = [
            f"which dnf && dnf install -y {package_name} || yum install -y {package_name}"
        ]
        
        results = ssh.execute_commands(commands)
        
        if results[0]['rc'] == 0:
            logger.info(f"✓ Package {package_name} installed successfully")
            return True
        else:
            logger.error(f"✗ Failed to install package {package_name}")
            return False


def example_task_create_directory(config: ConfigLoader, directory: str = "/opt/myapp") -> bool:
    """
    Example task: Create a directory on remote machine.
    
    Args:
        config: Configuration loader instance
        directory: Directory path to create
        
    Returns:
        True if successful, False otherwise
    """
    logger.info(f"Creating directory: {directory}")
    
    host = config.get('machines.example_machine.host')
    username = config.get('ssh.username', 'root')
    
    with SSHClient(host=host, username=username) as ssh:
        result = ssh.execute_command(f"mkdir -p {directory}")
        
        if result['rc'] == 0:
            logger.info(f"✓ Directory {directory} created")
            return True
        else:
            logger.error(f"✗ Failed to create directory {directory}")
            return False


def example_task_upload_file(
    config: ConfigLoader,
    local_file: str,
    remote_file: str
) -> bool:
    """
    Example task: Upload a file to remote machine.
    
    Args:
        config: Configuration loader instance
        local_file: Local file path
        remote_file: Remote destination path
        
    Returns:
        True if successful, False otherwise
    """
    logger.info(f"Uploading file: {local_file} -> {remote_file}")
    
    host = config.get('machines.example_machine.host')
    username = config.get('ssh.username', 'root')
    
    with SSHClient(host=host, username=username) as ssh:
        if ssh.upload_file(local_file, remote_file):
            logger.info(f"✓ File uploaded successfully")
            return True
        else:
            logger.error(f"✗ Failed to upload file")
            return False


# ============================================================================
# Task Registration Helper
# ============================================================================

def register_example_tasks(orchestrator):
    """
    Register all example tasks with the orchestrator.
    
    Args:
        orchestrator: AutomationOrchestrator instance
    """
    config = orchestrator.config
    
    # Register tasks
    orchestrator.register_task(
        task_id="001_check_connectivity",
        task_fn=lambda: example_task_check_connectivity(config),
        description="Check SSH connectivity to target machine"
    )
    
    orchestrator.register_task(
        task_id="002_install_vim",
        task_fn=lambda: example_task_install_package(config, "vim"),
        description="Install vim text editor"
    )
    
    orchestrator.register_task(
        task_id="003_create_app_directory",
        task_fn=lambda: example_task_create_directory(config, "/opt/myapp"),
        description="Create application directory"
    )
    
    # Add more task registrations here as you develop them

# Made with Bob

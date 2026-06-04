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

from core import execute_commands, download_and_extract


def preparation_for_services_deployment(logger, verbose: bool = True) -> bool:
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
        logger.info("Step 4: Installing required packages")
    commands = [
        "dnf install unzip lsof -y"
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("Package installation failed")
        return False
    
    return True


# Made with Bob

def preparation_for_services_deployment_task(config, logger, verbose: bool = True) -> bool:
    """
    Wrapper function for group-based execution.
    
    Args:
        config: ConfigLoader instance (not used, for compatibility)
        logger: Logger instance
        verbose: Enable verbose logging
        
    Returns:
        True if successful, False otherwise
    """
    return preparation_for_services_deployment(logger, verbose)

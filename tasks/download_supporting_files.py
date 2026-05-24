#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download Supporting Files Task
Handles downloading and extracting supporting files from external sources
"""

import sys
from pathlib import Path

# Add core modules to path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import execute_commands, download_and_extract


def download_supporting_files(logger, verbose: bool = True) -> bool:
    """
    Download and extract supporting files from Box.
    This should be executed as a separate stage before other deployments.
    
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
        logger.info("Downloading supporting files")
        logger.info("=" * 80)
    
    # Create necessary directories
    commands = [
        "mkdir -p /opt/guardium_tz_bootcamp_automation/upload"
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("Failed to create upload directory")
        return False
    
    # Download and extract supporting files from Box
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
    
    return True


# Made with Bob
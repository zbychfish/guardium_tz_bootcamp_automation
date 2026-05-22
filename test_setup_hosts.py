#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for setup_hosts functionality
Tests /etc/hosts generation without actually deploying
"""

import sys
from pathlib import Path

# Add core modules to path
sys.path.insert(0, str(Path(__file__).parent / "core"))
sys.path.insert(0, str(Path(__file__).parent / "tasks"))

from core.config_loader import ConfigLoader
from core.logger import setup_logger
from tasks.setup_hosts import generate_hosts_content


def main():
    """Test /etc/hosts generation."""
    
    logger = setup_logger("TestSetupHosts")
    
    # Load configuration
    config = ConfigLoader(
        config_file="config/config.yaml",
        machines_info_file="/root/machines_info.json"
    )
    
    # Get machines
    machines = config.get_machines()
    
    if not machines:
        logger.error("No machines found in configuration")
        return 1
    
    logger.info(f"Found {len(machines)} machine(s)")
    for machine_name, machine_info in machines.items():
        logger.info(f"  - {machine_name}: {machine_info.get('private_ip')} ({machine_info.get('host')})")
    
    # Generate /etc/hosts content
    logger.info("\nGenerating /etc/hosts content:")
    logger.info("=" * 80)
    
    hosts_content = generate_hosts_content(machines)
    print(hosts_content)
    
    logger.info("=" * 80)
    logger.info("\nTest completed successfully")
    logger.info("To deploy this to raptor, run: python automation.py")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Made with Bob
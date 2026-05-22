#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Example: How to use machines loaded from machines_info.json

This example demonstrates how to access machine information
that is automatically loaded from /root/machines_info.json
"""

import sys
from pathlib import Path

# Add core modules to path
sys.path.insert(0, str(Path(__file__).parent / "core"))

from core.config_loader import ConfigLoader
from core.logger import setup_logger


def main():
    """Example usage of machine information from JSON file."""
    
    logger = setup_logger("MachinesExample")
    
    # Load configuration (will automatically load machines from /root/machines_info.json)
    config = ConfigLoader(
        config_file="config/config.yaml",
        machines_info_file="/root/machines_info.json"
    )
    
    # Get all machines
    machines = config.get_machines()
    logger.info(f"Found {len(machines)} machine(s)")
    
    # Iterate through all machines
    for machine_name, machine_info in machines.items():
        logger.info(f"\nMachine: {machine_name}")
        logger.info(f"  Full name: {machine_info.get('full_name')}")
        logger.info(f"  Public IP: {machine_info.get('host')}")
        logger.info(f"  Private IP: {machine_info.get('private_ip')}")
        logger.info(f"  FQDN: {machine_info.get('fqdn')}")
    
    # Get specific machine by base name (without suffix)
    # For example, if full name is "hana-dsbni7pj", use "hana"
    hana_machine = config.get_machine('hana')
    if hana_machine:
        logger.info(f"\nHANA machine details:")
        logger.info(f"  Public IP: {hana_machine.get('host')}")
        logger.info(f"  Full name: {hana_machine.get('full_name')}")
    
    # Get machine IP directly
    raptor_ip = config.get_machine_ip('raptor')
    if raptor_ip:
        logger.info(f"\nRaptor public IP: {raptor_ip}")
    
    # Get private IP
    raptor_private_ip = config.get_machine_ip('raptor', use_private=True)
    if raptor_private_ip:
        logger.info(f"Raptor private IP: {raptor_private_ip}")
    
    # Get credentials
    credentials = config.get_credentials()
    if credentials:
        logger.info(f"\nCredentials:")
        logger.info(f"  Username: {credentials.get('username')}")
        logger.info(f"  SSH Key Fingerprint: {credentials.get('ssh_public_key_fingerprint')}")
    
    # Get deployment information
    deployment = config.get_deployment_info()
    if deployment:
        logger.info(f"\nDeployment Info:")
        logger.info(f"  Environment ID: {deployment.get('environment_id')}")
        logger.info(f"  Environment Key: {deployment.get('environment_key')}")
        logger.info(f"  Requester: {deployment.get('requester_email')}")
        logger.info(f"  Usage Category: {deployment.get('usage_category')}")


if __name__ == "__main__":
    main()

# Made with Bob
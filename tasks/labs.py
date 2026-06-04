#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lab Setup Tasks
Tasks for preparing lab environments
"""

import os
import glob
from typing import Dict, Any, Optional
from core.logger import get_logger
from core.appliance_config_loader import ApplianceConfigLoader
from core.guardium_rest_api import GuardiumRestAPI

logger = get_logger(__name__)


def import_gim_modules(
    config,
    logger,
    appliance_name: Optional[str] = None,
    demo_user: str = "demo",
    demo_password: Optional[str] = None,
    gim_directory: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/agents/gim",
    debug: bool = False
) -> bool:
    """
    Import GIM (Guardium Installation Manager) modules to Guardium appliance.
    
    This function:
    1. Loads appliance configuration
    2. Creates GuardiumRestAPI client
    3. Authenticates using demo user credentials
    4. Imports all *.gim files from the specified directory
    
    Args:
        config: Configuration object
        logger: Logger instance
        appliance_name: Name of the appliance (required)
        demo_user: Demo user username (default: "demo")
        demo_password: Demo user password (optional, uses custom_variables if not provided)
        gim_directory: Directory containing GIM files (default: /opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/agents/gim)
        debug: Enable debug output
    
    Returns:
        True if import successful, False otherwise
    """
    logger.info("=" * 80)
    logger.info("IMPORT GIM MODULES")
    logger.info("=" * 80)
    
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    # Load appliance configuration
    appliance_loader = ApplianceConfigLoader()
    appliance_config = appliance_loader.get_appliance(appliance_name)
    
    if not appliance_config:
        logger.error(f"Appliance '{appliance_name}' not found in appliances.yaml")
        return False
    
    appliance_type = appliance_config.get('type')
    host = appliance_config.get('ip')
    
    if not host:
        logger.error(f"No IP address configured for appliance '{appliance_name}'")
        return False
    
    logger.info(f"Appliance: {appliance_name} ({appliance_type}) at {host}")
    
    # Get demo user password
    if not demo_password:
        try:
            demo_password = config.get_custom_variable('demo_pwd')
            if demo_password:
                logger.info("Using demo password from custom_variables (demo_pwd)")
        except:
            pass
    
    if not demo_password:
        logger.error("Demo user password is required")
        logger.error("Provide demo_password in args or set 'demo_pwd' in custom_variables")
        return False
    
    # Get OAuth client secret
    try:
        client_secret = config.get_custom_variable('client_secret')
        if not client_secret:
            logger.error("client_secret not found in custom_variables")
            return False
    except Exception as e:
        logger.error(f"Failed to get client_secret from custom_variables: {e}")
        return False
    
    # Check if GIM directory exists
    if not os.path.exists(gim_directory):
        logger.error(f"GIM directory not found: {gim_directory}")
        return False
    
    # Check for GIM files
    gim_files = glob.glob(os.path.join(gim_directory, "*.gim"))
    if not gim_files:
        logger.error(f"No *.gim files found in {gim_directory}")
        return False
    
    logger.info(f"Found {len(gim_files)} GIM file(s) in {gim_directory}:")
    for gim_file in gim_files:
        logger.info(f"  - {os.path.basename(gim_file)}")
    
    # Create REST API client
    base_url = f"https://{host}"
    logger.info(f"\nConnecting to Guardium REST API at {base_url}")
    
    try:
        api = GuardiumRestAPI(
            base_url=base_url,
            client_id="BOOTCAMP",
            client_secret=client_secret,
            verify_ssl=False
        )
        
        # Get OAuth token
        logger.info(f"Authenticating as user '{demo_user}'...")
        token = api.get_token(username=demo_user, password=demo_password)
        logger.info("✓ Authentication successful")
        
        if debug:
            logger.info(f"Access token: {token[:20]}...")
        
        # Import GIM packages
        logger.info("\nImporting GIM packages...")
        logger.info("Using wildcard pattern: *.gim")
        
        response = api.get_gim_package(filename="*.gim")
        
        if debug:
            logger.info(f"API Response: {response}")
        
        logger.info("✓ GIM packages import initiated successfully")
        logger.info("=" * 80)
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to import GIM packages: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        logger.error("=" * 80)
        return False

# Made with Bob

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
from core.appliance_operations import copy_files_to_appliance

logger = get_logger(__name__)


def import_gim_modules(
    config,
    logger,
    verbose: bool = False,
    appliance_name: Optional[str] = None,
    demo_user: str = "demo",
    demo_password: Optional[str] = None,
    gim_directory: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/agents/gim",
    gim_target_dir: str = "/var/IBM/Guardium/gim/packages",
    debug: bool = False
) -> bool:
    """
    Import GIM (Guardium Installation Manager) modules to Guardium appliance.
    
    This function:
    1. Copies GIM files from raptor to appliance
    2. Loads appliance configuration
    3. Creates GuardiumRestAPI client
    4. Authenticates using demo user credentials
    5. Imports all *.gim files using REST API
    
    Args:
        config: Configuration object
        logger: Logger instance
        appliance_name: Name of the appliance (required)
        demo_user: Demo user username (default: "demo")
        demo_password: Demo user password (optional, uses custom_variables if not provided)
        gim_directory: Directory containing GIM files on raptor (default: /opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/agents/gim)
        gim_target_dir: Target directory on appliance (default: /var/IBM/Guardium/gim/packages)
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
    
    # Step 1: Copy GIM files to appliance
    logger.info(f"\n{'=' * 80}")
    logger.info("STEP 1: Copy GIM files to appliance")
    logger.info(f"{'=' * 80}")
    
    copy_success = copy_files_to_appliance(
        config=config,
        logger=logger,
        appliance_name=appliance_name,
        source_dir=gim_directory,
        file_pattern="*.gim",
        target_dir=gim_target_dir,
        owner="tomcat:tomcat",
        debug=debug
    )
    
    if not copy_success:
        logger.error("✗ Failed to copy GIM files to appliance")
        return False
    
    # Step 2: Import GIM modules using REST API
    logger.info(f"\n{'=' * 80}")
    logger.info("STEP 2: Import GIM modules using REST API")
    logger.info(f"{'=' * 80}")
    
    # Get demo user password
    if not demo_password:
        try:
            demo_password = config.get_custom_variable('pwd')
            if demo_password:
                logger.info("Using demo password from custom_variables (pwd)")
        except:
            pass
    
    if not demo_password:
        logger.error("Demo user password is required")
        logger.error("Provide demo_password in args or set 'pwd' in custom_variables")
        return False
    
    # Get OAuth client secret from .client_secret file
    try:
        from pathlib import Path
        project_root = config.config_file.parent.parent
        secret_file = project_root / ".client_secret"
        
        if not secret_file.exists():
            logger.error(f"client_secret file not found: {secret_file}")
            logger.error("Run 'create_oauth_client' stage first to generate the client secret")
            return False
        
        with open(secret_file, 'r') as f:
            client_secret = f.read().strip()
        
        if not client_secret:
            logger.error("client_secret file is empty")
            return False
        
        logger.info(f"Using client_secret from file: {secret_file}")
        
    except Exception as e:
        logger.error(f"Failed to read client_secret from file: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    
    # Create REST API client
    base_url = f"https://{host}"
    logger.info(f"Connecting to Guardium REST API at {base_url}")
    
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

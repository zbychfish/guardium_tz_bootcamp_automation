#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Guardium REST API wrapper for guardium_tz_bootcamp_automation
Imports and uses the original GuardiumRestAPI from guardium_bootcamp_automation
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import from guardium_bootcamp_automation
parent_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(parent_dir / "guardium_bootcamp_automation"))

try:
    from guardium_rest_api import GuardiumRestAPI  # type: ignore
except ImportError as e:
    raise ImportError(
        f"Cannot import GuardiumRestAPI from guardium_bootcamp_automation: {e}\n"
        "Make sure guardium_bootcamp_automation directory exists in the parent directory."
    )


def create_guardium_api(config, logger, appliance_name: str = "cm01") -> GuardiumRestAPI:
    """
    Create GuardiumRestAPI instance using appliance configuration
    
    Args:
        config: ConfigLoader instance
        logger: Logger instance
        appliance_name: Name of appliance from config/appliances.yaml (default: cm01)
    
    Returns:
        GuardiumRestAPI instance
    
    Example:
        api = create_guardium_api(config, logger, "cm01")
        token = api.get_token(username='accessmgr', password='password')
        users = api.get_users()
    """
    from .appliance_config_loader import ApplianceConfigLoader
    
    # Load appliance configuration
    appliance_loader = ApplianceConfigLoader(config.config_dir)
    appliance_config = appliance_loader.get_appliance(appliance_name)
    
    if not appliance_config:
        raise ValueError(f"Appliance '{appliance_name}' not found in config/appliances.yaml")
    
    appliance_ip = appliance_config.get('ip')
    if not appliance_ip:
        raise ValueError(f"IP address not found for appliance '{appliance_name}'")
    
    # Get CLIENT_SECRET from .client_secret file, custom_variables, or environment
    client_secret = None
    
    # Try to read from .client_secret file first
    secret_file = Path(config.project_root) / ".client_secret"
    if secret_file.exists():
        try:
            with open(secret_file, 'r') as f:
                client_secret = f.read().strip()
            logger.info(f"Using CLIENT_SECRET from .client_secret file")
        except Exception as e:
            logger.warning(f"Failed to read .client_secret file: {e}")
    
    # Try to get from custom_variables if not found in file
    if not client_secret:
        custom_vars = config.get_custom_variables()
        if custom_vars and 'client_secret' in custom_vars:
            client_secret = custom_vars['client_secret']
            logger.info(f"Using CLIENT_SECRET from custom_variables")
    
    # Try environment variable as last resort
    if not client_secret:
        client_secret = os.getenv('CLIENT_SECRET')
        if client_secret:
            logger.info(f"Using CLIENT_SECRET from environment variable")
    
    if not client_secret:
        raise ValueError(
            "CLIENT_SECRET not found. Run 'create_oauth_client' stage first, or add it to:\n"
            "  1. .client_secret file (created by create_oauth_client stage)\n"
            "  2. machines_info.json custom_variables, or\n"
            "  3. Environment variable CLIENT_SECRET"
        )
    
    # Create base URL
    base_url = f"https://{appliance_ip}"
    
    logger.info(f"Creating Guardium REST API client for {appliance_name} ({appliance_ip})")
    
    # Create and return API instance
    api = GuardiumRestAPI(
        base_url=base_url,
        client_id="BOOTCAMP",
        client_secret=client_secret,
        verify_ssl=False
    )
    
    return api


# Re-export GuardiumRestAPI for direct import
__all__ = ['GuardiumRestAPI', 'create_guardium_api']

# Made with Bob

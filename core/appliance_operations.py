#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Appliance Operations - Reusable functions for Guardium appliance operations
"""

import time
from typing import Optional
from .appliance_client import ApplianceClient
from .appliance_config_loader import ApplianceConfigLoader


def restart_appliance(
    config,
    logger,
    appliance_name: str,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True,
    wait_for_availability: bool = True,
    wait_timeout: int = 600
) -> bool:
    """
    Restart Guardium appliance with MySQL busy check
    
    This is a reusable core function that can be called from any task.
    
    Args:
        config: ConfigLoader instance
        logger: Logger instance
        appliance_name: Name of appliance from appliances.yaml (required)
        user: SSH username (optional, uses default from type if not provided)
        password: SSH password (optional, uses cli_pwd from custom_variables if not provided)
        prompt_regex: Prompt regex (optional, uses default from type if not provided)
        debug: Enable debug mode (default True)
        wait_for_availability: Wait for appliance to come back online (default True)
        wait_timeout: Timeout for waiting in seconds (default 600 = 10 minutes)
    
    Returns:
        True if successful, False otherwise
    
    Example:
        from core.appliance_operations import restart_appliance
        
        success = restart_appliance(
            config=config,
            logger=logger,
            appliance_name="cm01",
            wait_for_availability=True,
            wait_timeout=600
        )
    """
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    logger.info("=" * 80)
    logger.info(f"RESTART APPLIANCE: {appliance_name}")
    logger.info("=" * 80)
    
    # Load appliance configuration
    appliance_loader = ApplianceConfigLoader()
    appliance_config = appliance_loader.get_appliance(appliance_name)
    
    if not appliance_config:
        logger.error(f"Appliance '{appliance_name}' not found in appliances.yaml")
        available = list(appliance_loader.get_all_appliances().keys())
        logger.error(f"Available appliances: {', '.join(available)}")
        return False
    
    appliance_type = appliance_config.get('type')
    host = appliance_config.get('ip')
    
    if not host:
        logger.error(f"No IP address configured for appliance '{appliance_name}'")
        return False
    
    # Get user from config if not provided
    if not user:
        if appliance_type:
            user = appliance_loader.get_default_user(appliance_type)
        else:
            user = "cli"
    
    # Get password from custom_variables if not provided
    if not password:
        password = config.get_custom_variable('cli_pwd')
        if password:
            logger.info("Using password from custom_variables (cli_pwd)")
    
    if not password:
        logger.error("Password not provided and cli_pwd not found in custom_variables")
        return False
    
    # Get prompt regex from config if not provided
    if not prompt_regex:
        if appliance_type:
            prompt_regex = appliance_loader.get_default_prompt(appliance_type, configured=False)
        if not prompt_regex:
            logger.error(f"No prompt_regex provided and no default found for type '{appliance_type}'")
            return False
    
    logger.info(f"Appliance: {appliance_name} ({appliance_type}) at {host}")
    logger.info(f"User: {user}")
    
    try:
        # Connect to appliance
        client = ApplianceClient(
            host=host,
            user=user,
            password=password,
            prompt_regex=prompt_regex,
            initial_pattern=None,
            timeout=60,
            strip_ansi=True,
            debug=debug
        )
        
        if not client.connect():
            logger.error("Failed to connect to appliance")
            return False
        
        # Execute restart with MySQL busy check
        logger.info("\n➜ Executing: restart system")
        logger.info("Checking if MySQL is busy...")
        result = client.execute_restart_with_check()
        
        client.disconnect()
        
        # Check result
        if "System is restarting" in result:
            logger.info("✓ System restart initiated")
            
            if wait_for_availability:
                logger.info(f"\n⌛ Waiting for appliance to come back online (timeout: {wait_timeout}s)...")
                
                start_time = time.time()
                while time.time() - start_time < wait_timeout:
                    try:
                        # Try to connect
                        test_client = ApplianceClient(
                            host=host,
                            user=user,
                            password=password,
                            prompt_regex=prompt_regex,
                            initial_pattern=None,
                            timeout=30,
                            strip_ansi=True,
                            debug=False
                        )
                        
                        if test_client.connect():
                            test_client.disconnect()
                            elapsed = int(time.time() - start_time)
                            logger.info(f"✓ Appliance is back online (after {elapsed}s)")
                            logger.info("=" * 80)
                            logger.info("Appliance restarted successfully")
                            logger.info("=" * 80)
                            return True
                    except Exception:
                        pass
                    
                    time.sleep(10)
                
                logger.error(f"✗ Timeout waiting for appliance (waited {wait_timeout}s)")
                return False
            else:
                logger.info("=" * 80)
                logger.info("Restart initiated (not waiting for availability)")
                logger.info("=" * 80)
                return True
                
        elif "MySQL is busy" in result:
            logger.warning("✗ Restart rejected - MySQL is busy updating the database")
            logger.warning("Please wait a few minutes and try again")
            return False
        else:
            logger.error(f"✗ Unexpected result: {result}")
            return False
        
    except Exception as e:
        logger.error(f"Error restarting appliance: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

# Made with Bob

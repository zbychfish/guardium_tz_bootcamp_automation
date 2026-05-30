#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Setup Appliances Tasks
Tasks for configuring Guardium appliances
"""

from typing import Dict, Any, Optional
from core.logger import get_logger
from core.appliance_client import ApplianceClient
from core.appliance_config_loader import ApplianceConfigLoader

logger = get_logger(__name__)


def connect_and_show_clock(
    config,
    logger,
    verbose: bool = True,
    appliance_name: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = False
) -> bool:
    """
    Connect to appliance and execute 'show system clock all' command
    
    Args:
        config: ConfigLoader instance (not used, kept for compatibility)
        logger: Logger instance
        verbose: Enable verbose logging
        appliance_name: Name of appliance from appliances.yaml (required)
        user: SSH username (optional, uses default from type if not provided)
        password: SSH password (required)
        prompt_regex: Prompt regex (optional, uses default from type if not provided)
    
    Returns:
        True if successful, False otherwise
    
    Example in config/groups.yaml:
        stages:
          - name: test_collector
            function: connect_and_show_clock
            module: tasks.setup_appliances
            args:
              appliance_name: "collector1"
              password: "your_password"
              prompt_regex: "guard\\.yourcompany\\.com>"  # Optional
    """
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    logger.info(f"Connecting to appliance: {appliance_name}")
    
    # Load appliance configuration
    appliance_loader = ApplianceConfigLoader()
    appliance_config = appliance_loader.get_appliance(appliance_name)
    
    if not appliance_config:
        logger.error(f"Appliance '{appliance_name}' not found in appliances.yaml")
        available = list(appliance_loader.get_all_appliances().keys())
        logger.error(f"Available appliances: {', '.join(available)}")
        return False
    
    # Get appliance details
    appliance_type = appliance_config.get('type')
    host = appliance_config.get('ip')
    
    if not host:
        logger.error(f"No IP address configured for appliance '{appliance_name}'")
        return False
    
    # Use provided credentials or defaults
    if not user:
        if appliance_type:
            user = appliance_loader.get_default_user(appliance_type)
        else:
            user = "cli"  # Fallback default
    
    # Try to get password from custom_variables if not provided
    if not password:
        try:
            password = config.get_custom_variable('cli_pwd')
            if password:
                logger.info("Using password from custom_variables (cli_pwd)")
        except:
            pass
    
    if not password:
        logger.error(f"Password is required for appliance '{appliance_name}'")
        logger.error("Provide password in args or set 'cli_pwd' in custom_variables")
        return False
    
    if not prompt_regex:
        # Try to get default prompt for type
        if appliance_type:
            prompt_regex = appliance_loader.get_default_prompt(appliance_type, configured=False)
        if not prompt_regex:
            logger.error(f"No prompt_regex provided and no default found for type '{appliance_type}'")
            return False
    
    logger.info(f"Appliance: {appliance_name} ({appliance_type}) at {host}")
    logger.info(f"User: {user}")
    
    # Create appliance client
    # Use None for initial_pattern - will nudge prompt and wait directly for prompt
    if debug:
        logger.info(f"Creating appliance client with:")
        logger.info(f"  host: {host}")
        logger.info(f"  user: {user}")
        logger.info(f"  prompt_regex: {prompt_regex}")
    
    appliance = ApplianceClient(
        host=host,
        user=user,
        password=password,
        prompt_regex=prompt_regex,
        initial_pattern=None,
        timeout=60,
        strip_ansi=True,
        debug=debug  # Use debug parameter from args
    )
    
    # Connect
    logger.info(f"Establishing SSH connection to {host}...")
    if not appliance.connect():
        logger.error(f"Failed to connect to appliance at {host}")
        return False
    
    logger.info("✓ Connected successfully")
    
    try:
        # Execute command
        logger.info("Executing command: show system clock all")
        output = appliance.execute_command("show system clock all")
        
        logger.info("Command output:")
        logger.info("-" * 60)
        for line in output.splitlines():
            logger.info(line)
        logger.info("-" * 60)
        
        # Parse timezone
        lines = output.strip().splitlines()
        if lines:
            timezone = lines[-1].strip()
            logger.info(f"Current timezone: {timezone}")
        
        logger.info("✓ Command executed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error executing command: {e}")
        return False
        
    finally:
        logger.info("Disconnecting from appliance...")
        appliance.disconnect()
        logger.info("✓ Disconnected")


def initial_collector_settings(
    config,
    logger,
    verbose: bool = True,
    collector_name: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = False
) -> bool:
    """
    Configure initial collector settings
    
    Performs initial configuration on a Guardium collector:
    - Disables purge
    - Sets timezone to Europe/Warsaw
    - Configures NTP servers
    - Enables time synchronization
    
    Args:
        config: ConfigLoader instance (not used, kept for compatibility)
        logger: Logger instance
        verbose: Enable verbose logging
        collector_name: Name of collector from appliances.yaml (required)
        user: SSH username (optional, uses default if not provided)
        password: SSH password (required)
        prompt_regex: Prompt regex (optional, uses default for unconfigured collector)
    
    Returns:
        True if successful, False otherwise
    
    Example in config/groups.yaml:
        stages:
          - name: configure_collector
            function: initial_collector_settings
            module: tasks.setup_appliances
            args:
              collector_name: "collector1"
              password: "your_password"
              prompt_regex: "guard\\.yourcompany\\.com>"  # Optional
    """
    if not collector_name:
        logger.error("collector_name is required")
        return False
    
    logger.info(f"Configuring initial settings for collector: {collector_name}")
    
    # Load appliance configuration
    appliance_loader = ApplianceConfigLoader()
    collector_config = appliance_loader.get_appliance(collector_name)
    
    if not collector_config:
        logger.error(f"Collector '{collector_name}' not found in appliances.yaml")
        available = list(appliance_loader.get_appliances_by_type('collector').keys())
        logger.error(f"Available collectors: {', '.join(available)}")
        return False
    
    # Verify it's a collector
    if collector_config.get('type') != 'collector':
        logger.error(f"Appliance '{collector_name}' is not a collector (type: {collector_config.get('type')})")
        return False
    
    # Get collector details
    host = collector_config.get('ip')
    
    if not host:
        logger.error(f"No IP address configured for collector '{collector_name}'")
        return False
    
    # Use provided credentials or defaults
    if not user:
        user = appliance_loader.get_default_user('collector')
    
    # Try to get password from custom_variables if not provided
    if not password:
        try:
            password = config.get_custom_variable('cli_pwd')
            if password:
                logger.info("Using password from custom_variables (cli_pwd)")
        except:
            pass
    
    if not password:
        logger.error(f"Password is required for collector '{collector_name}'")
        logger.error("Provide password in args or set 'cli_pwd' in custom_variables")
        return False
    
    if not prompt_regex:
        # Use unconfigured collector prompt
        prompt_regex = appliance_loader.get_default_prompt('collector', configured=False)
        if not prompt_regex:
            logger.error("No prompt_regex provided and no default found for unconfigured collector")
            return False
    
    logger.info(f"Collector: {collector_name} at {host}")
    logger.info(f"User: {user}")
    
    # Create appliance client
    # Use None for initial_pattern - will nudge prompt and wait directly for prompt
    if debug:
        logger.info(f"Creating appliance client with:")
        logger.info(f"  host: {host}")
        logger.info(f"  user: {user}")
        logger.info(f"  prompt_regex: {prompt_regex}")
    
    appliance = ApplianceClient(
        host=host,
        user=user,
        password=password,
        prompt_regex=prompt_regex,
        initial_pattern=None,
        timeout=120,
        strip_ansi=True,
        debug=debug  # Use debug parameter from args
    )
    
    # Connect
    logger.info("Connecting to collector...")
    if not appliance.connect():
        logger.error("Failed to connect to collector")
        return False
    
    logger.info("✓ Connected successfully")
    
    try:
        # Disable purge
        logger.info("Disabling purge...")
        output = appliance.execute_command("grdapi disable_purge")
        logger.info("✓ Purge disabled")
        
        # Check current timezone
        logger.info("Checking current timezone...")
        output = appliance.execute_command("show system clock all")
        timezone = output.strip().splitlines()[-1] if output.strip() else ""
        logger.info(f"Current timezone: {timezone}")
        
        # Set timezone if needed
        if timezone != "Europe/Warsaw":
            logger.info("Setting timezone to Europe/Warsaw...")
            output = appliance.execute_command_with_confirmation(
                command="store system clock timezone Europe/Warsaw",
                response="y",
                confirmation_pattern=r"Do you want to proceed\?\s*\(y/n\)\s*"
            )
            logger.info("✓ Timezone set")
            
            # Verify new timezone
            output = appliance.execute_command("show system clock all")
            new_timezone = output.strip().splitlines()[-1] if output.strip() else ""
            logger.info(f"New timezone: {new_timezone}")
        else:
            logger.info("✓ Timezone already set correctly")
        
        # Configure NTP servers
        logger.info("Configuring NTP servers...")
        appliance.execute_command(
            "store system time_server hostname 0.pool.ntp.org 1.pool.ntp.org 2.pool.ntp.org"
        )
        logger.info("✓ NTP servers configured")
        
        # Enable time synchronization
        logger.info("Enabling time synchronization...")
        appliance.execute_command("store system time_server state on")
        logger.info("✓ Time synchronization enabled")
        
        logger.info("✓ Initial collector settings configured successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error configuring collector: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
        
    finally:
        logger.info("Disconnecting from collector...")
        appliance.disconnect()
        logger.info("✓ Disconnected")

# Made with Bob



def read_license_keys(
    config,
    logger,
    verbose: bool = True,
    keys_directory: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/keys"
) -> bool:
    """
    Read and display license keys from raptor
    
    Reads .lkey files from specified directory:
    - base.lkey (base license)
    - append*.lkey (append licenses)
    
    Displays content in single-line format: base keys first, then append keys
    
    Args:
        config: ConfigLoader instance
        logger: Logger instance
        verbose: Enable verbose logging
        keys_directory: Path to directory with .lkey files
    
    Returns:
        True if successful, False otherwise
    
    Example in config/groups.yaml:
        stages:
          - name: read_license_keys
            function: read_license_keys
            module: tasks.setup_appliances
            args:
              keys_directory: "/opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/keys"
    """
    import os
    import glob
    
    logger.info(f"Reading license keys from: {keys_directory}")
    
    # Check if directory exists
    if not os.path.exists(keys_directory):
        logger.error(f"Directory not found: {keys_directory}")
        return False
    
    # Find all .lkey files
    lkey_files = glob.glob(os.path.join(keys_directory, "*.lkey"))
    
    if not lkey_files:
        logger.error(f"No .lkey files found in {keys_directory}")
        return False
    
    logger.info(f"Found {len(lkey_files)} license key file(s)")
    
    # Separate base and append keys
    base_keys = []
    append_keys = []
    
    for filepath in lkey_files:
        filename = os.path.basename(filepath)
        
        try:
            with open(filepath, 'r') as f:
                content = f.read().strip()
            
            # Convert to single line (remove newlines)
            single_line = content.replace('\n', '').replace('\r', '')
            
            if filename.startswith('base'):
                base_keys.append((filename, single_line))
            elif filename.startswith('append'):
                append_keys.append((filename, single_line))
            else:
                logger.warning(f"Unknown key type: {filename}")
                
        except Exception as e:
            logger.error(f"Error reading {filename}: {e}")
            return False
    
    # Display keys in order: base first, then append
    logger.info("=" * 80)
    logger.info("LICENSE KEYS")
    logger.info("=" * 80)
    
    # Display base keys
    if base_keys:
        logger.info("\nBASE LICENSE KEYS:")
        for filename, content in sorted(base_keys):
            logger.info(f"  {filename}:")
            logger.info(f"    {content}")
    else:
        logger.warning("No base license keys found")
    
    # Display append keys
    if append_keys:
        logger.info("\nAPPEND LICENSE KEYS:")
        for filename, content in sorted(append_keys):
            logger.info(f"  {filename}:")
            logger.info(f"    {content}")
    else:
        logger.info("No append license keys found")
    
    logger.info("=" * 80)
    logger.info(f"Total: {len(base_keys)} base key(s), {len(append_keys)} append key(s)")
    
    return True

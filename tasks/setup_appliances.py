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


def create_oauth_client(
    config,
    logger,
    verbose: bool = True,
    appliance_name: str = "cm01",
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    client_id: str = "BOOTCAMP",
    debug: bool = False
) -> bool:
    """
    Create OAuth client in Guardium and save client_secret to file
    
    Creates OAuth client with specified client_id and saves the generated
    client_secret to .client_secret file in project root.
    
    Based on t_initial_cm_settings from guardium_bootcamp_automation.
    
    Args:
        config: ConfigLoader instance
        logger: Logger instance
        verbose: Enable verbose logging
        appliance_name: Name of appliance from appliances.yaml (default: cm01)
        user: SSH username (optional, uses default from type if not provided)
        password: SSH password (optional, uses cli_pwd from custom_variables if not provided)
        prompt_regex: Prompt regex (optional, uses default from type if not provided)
        client_id: OAuth client ID (default: BOOTCAMP)
        debug: Enable debug mode for SSH connection
    
    Returns:
        True if successful, False otherwise
    
    Example in config/groups.yaml:
        stages:
          - name: create_oauth_client
            function: create_oauth_client
            module: tasks.setup_appliances
            args:
              appliance_name: "cm01"
              client_id: "BOOTCAMP"
    """
    import json
    from pathlib import Path
    
    logger.info("=" * 80)
    logger.info(f"CREATE OAUTH CLIENT: {client_id}")
    logger.info("=" * 80)
    
    appliances_file = config.config_file.parent / "appliances.yaml"
    appliance_loader = ApplianceConfigLoader(appliances_file)
    appliance_config = appliance_loader.get_appliance(appliance_name)
    
    if not appliance_config:
        logger.error(f"Appliance '{appliance_name}' not found in config/appliances.yaml")
        return False
    
    # Get password from custom_variables if not provided
    if not password:
        custom_vars = config.get_custom_variables()
        if custom_vars and 'cli_pwd' in custom_vars:
            password = custom_vars['cli_pwd']
            logger.info("Using password from custom_variables (cli_pwd)")
        else:
            logger.error("Password not provided and cli_pwd not found in custom_variables")
            return False
    
    # Get default user if not provided
    if not user:
        user = appliance_loader.get_default_user(appliance_config.get('type', 'collector'))
    
    # Get default prompt if not provided
    if not prompt_regex:
        appliance_type = appliance_config.get('type', 'collector')
        prompt_regex = appliance_loader.get_default_prompt(appliance_type, configured=True)
    
    appliance_ip = appliance_config.get('ip')
    if not appliance_ip:
        logger.error(f"IP address not found for appliance '{appliance_name}'")
        return False
    
    if not password:
        logger.error("Password is required")
        return False
    
    if not prompt_regex:
        logger.error("Prompt regex could not be determined")
        return False
    
    logger.info(f"Connecting to {appliance_name} ({appliance_ip})...")
    
    # Create appliance client
    client = ApplianceClient(
        host=appliance_ip,
        user=user,
        password=password,
        prompt_regex=prompt_regex,
        timeout=120,
        debug=debug
    )
    
    try:
        # Connect to appliance
        if not client.connect():
            logger.error("Failed to connect to appliance")
            return False
        
        logger.info("✓ Connected successfully")
        
        # List existing OAuth clients
        logger.info(f"\nListing existing OAuth clients...")
        result = client.execute_command("grdapi list_oauth_clients")
        logger.info(result)
        
        # Delete existing client if exists
        if f"Client Id: {client_id}" in result:
            logger.info(f"\n➜ Deleting existing OAuth client '{client_id}'...")
            result = client.execute_command(f"grdapi delete_oauth_clients client_id={client_id}")
            logger.info("✓ Existing client deleted")
        
        # Create new OAuth client
        logger.info(f"\n➜ Creating OAuth client '{client_id}'...")
        result = client.execute_command(f'grdapi register_oauth_client client_id={client_id} grant_types="password"')
        
        # Parse client_secret from response
        client_secret = None
        for line in result.splitlines():
            line = line.strip()
            if line.startswith('{') and line.endswith('}'):
                try:
                    data = json.loads(line)
                    client_secret = data.get('client_secret')
                    if client_secret:
                        logger.info(f"✓ OAuth client created successfully")
                        logger.info(f"  Client ID: {client_id}")
                        logger.info(f"  Client Secret: {client_secret[:10]}...")
                        break
                except json.JSONDecodeError:
                    pass
        
        if not client_secret:
            logger.error("Failed to extract client_secret from response")
            logger.error(f"Response: {result}")
            return False
        
        project_root = config.config_file.parent.parent
        secret_file = project_root / ".client_secret"
        try:
            with open(secret_file, 'w') as f:
                f.write(client_secret)
            logger.info(f"\n✓ Client secret saved to: {secret_file}")
            logger.info("  (This file is in .gitignore and will not be committed)")
        except Exception as e:
            logger.error(f"Failed to save client_secret to file: {e}")
            return False
        
        logger.info("=" * 80)
        logger.info("OAuth client setup completed successfully")
        logger.info("=" * 80)
        
        return True
        
    except Exception as e:
        logger.error(f"Error creating OAuth client: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
        
    finally:
        client.disconnect()


def create_demo_user(
    config,
    logger,
    verbose: bool = True,
    appliance_name: str = "cm01",
    accessmgr_password: Optional[str] = None,
    demo_password: Optional[str] = None
) -> bool:
    
    from core.guardium_rest_api import create_guardium_api
    
    logger.info("=" * 80)
    logger.info("CREATE DEMO USER")
    logger.info("=" * 80)
    
    custom_vars = config.get_custom_variables()
    
    if not accessmgr_password:
        if custom_vars and 'cli_pwd' in custom_vars:
            accessmgr_password = custom_vars['cli_pwd']
            logger.info("Using accessmgr password from custom_variables (cli_pwd)")
        else:
            logger.error("accessmgr_password not provided and cli_pwd not found in custom_variables")
            return False
    
    if not demo_password:
        if custom_vars and 'pwd' in custom_vars:
            demo_password = custom_vars['pwd']
            logger.info("Using demo password from custom_variables (pwd)")
        else:
            logger.error("demo_password not provided and pwd not found in custom_variables")
            return False
    
    assert accessmgr_password is not None
    assert demo_password is not None
    
    try:
        api = create_guardium_api(config, logger, appliance_name)
        
        logger.info("Getting token as accessmgr...")
        token = api.get_token(username='accessmgr', password=accessmgr_password)
        logger.info("✓ Token obtained successfully")
        
        logger.info("\nListing existing users:")
        users = api.get_users()
        
        for u in users:
            status = "DISABLED" if u.get("disabled") == "true" else "ACTIVE"
            logger.info(f"  {u['user_name']:12} | {status}")
        
        demo_exists = any(u.get('user_name') == 'demo' for u in users)
        
        if not demo_exists:
            logger.info("\n➜ Creating demo user...")
            result = api.create_user(
                username='demo',
                password=demo_password,
                confirm_password=demo_password,
                first_name='User',
                last_name='Demo',
                email='demo@demo.training',
                country='PL',
                disabled=False,
                disable_pwd_expiry=True
            )
            logger.info("✓ Demo user created successfully")
            
            logger.info("\n➜ Assigning roles to demo user...")
            result = api.set_user_roles(
                username='demo',
                roles='admin,cli,user,vulnerability-assess'
            )
            logger.info("✓ Roles assigned: admin, cli, user, vulnerability-assess")
            
        else:
            logger.info("\nℹ Demo user already exists")
        
        # Verify demo user can login
        logger.info("\nVerifying demo user credentials...")
        token = api.get_token(username='demo', password=demo_password)
        logger.info("✓ Demo user login successful")
        
        # Disable guardium account
        logger.info("\n➜ Disabling guardium account...")
        api.update_user(username='guardium', disabled=True)
        logger.info("✓ guardium account disabled")
        
        # Disable guardcli2 to guardcli9 accounts
        logger.info("\n➜ Disabling guardcli accounts...")
        for cli_num in range(2, 10):  # guardcli2 to guardcli9
            username = f"guardcli{cli_num}"
            api.update_user(username=username, disabled=True)
            logger.info(f"✓ {username} account disabled")
        
        logger.info("=" * 80)
        logger.info("Demo user setup completed successfully")
        logger.info("Disabled accounts: guardium, guardcli2-guardcli9")
        logger.info("=" * 80)
        
        return True
        
    except Exception as e:
        logger.error(f"Error creating demo user: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
    return True

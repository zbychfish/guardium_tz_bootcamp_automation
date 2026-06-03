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
from core.appliance_operations import (
    restart_appliance as core_restart_appliance,
    configure_hosts_resolving as core_configure_hosts
)

logger = get_logger(__name__)

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
        
        logger.info("\n➜ Disabling guardium account...")
        api.update_user(username='guardium', disabled=True)
        logger.info("✓ guardium account disabled")
        
        logger.info("\n➜ Disabling guardcli accounts...")
        for cli_num in range(2, 10):
            username = f"guardcli{cli_num}"
            api.update_user(username=username, disabled=True)
            logger.info(f"✓ {username} account disabled")
        
        logger.info("\nVerifying demo user credentials...")
        token = api.get_token(username='demo', password=demo_password)
        logger.info("✓ Demo user login successful")
        
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

def set_unit_type_manager(
    config,
    logger,
    verbose: bool = True,
    appliance_name: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:

    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    logger.info("=" * 80)
    logger.info(f"SET UNIT TYPE MANAGER: {appliance_name}")
    logger.info("=" * 80)
    
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
    
    if not user:
        if appliance_type:
            user = appliance_loader.get_default_user(appliance_type)
        else:
            user = "cli"
    
    if not password:
        password = config.get_custom_variable('cli_pwd')
        if password:
            logger.info("Using password from custom_variables (cli_pwd)")
    
    if not password:
        logger.error("Password not provided and cli_pwd not found in custom_variables")
        return False
    
    if not prompt_regex:
        if appliance_type:
            prompt_regex = appliance_loader.get_default_prompt(appliance_type, configured=False)
        if not prompt_regex:
            logger.error(f"No prompt_regex provided and no default found for type '{appliance_type}'")
            return False
    
    logger.info(f"Appliance: {appliance_name} ({appliance_type}) at {host}")
    logger.info(f"User: {user}")
    logger.info(f"Prompt regex: {prompt_regex}")
    
    try:
        client = ApplianceClient(
            host=host,
            user=user,
            password=password,
            prompt_regex=prompt_regex,
            initial_pattern=None,
            timeout=300,
            strip_ansi=True,
            debug=debug
        )
        
        if not client.connect():
            logger.error("Failed to connect to appliance")
            return False
        
        logger.info("\n➜ Executing: store unit type manager")
        logger.info("This command may take up to 5 minutes to complete...")
        output = client.execute_command("store unit type manager", timeout=300)
        logger.info(f"Command output:\n{output}")
        
        client.disconnect()
        
        # Verify success
        if "success: true" not in output:
            logger.error("Command did not return 'success: true'")
            logger.error("This indicates the command failed")
            return False
        
        if "GUI restart succeeded" not in output:
            logger.error("Command did not return 'GUI restart succeeded'")
            logger.error("This indicates the GUI restart failed")
            return False
        
        logger.info("=" * 80)
        logger.info("✓ Unit type set to manager successfully")
        logger.info("✓ Verified: success: true")
        logger.info("✓ Verified: GUI restart succeeded")
        logger.info("=" * 80)
        
        return True
        
    except Exception as e:
        logger.error(f"Error setting unit type: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def restart_appliance_all(
    config,
    logger,
    verbose: bool = True,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True,
    wait_for_availability: bool = True,
    retry_interval: int = 10,
    max_retries: int = 60
) -> bool:
    """
    Restart all appliances asynchronously in order: CM → Collectors → AppNodes
    Uses parallel execution to restart multiple appliances simultaneously (max 20 parallel).
    
    Args:
        config: Configuration object
        logger: Logger instance
        verbose: Enable verbose output
        user: SSH username (optional, uses default from appliance type)
        password: SSH password (optional, uses cli_pwd from custom_variables)
        prompt_regex: CLI prompt regex (optional, uses default from appliance type)
        debug: Enable debug output
        wait_for_availability: Wait for appliances to come back online
        retry_interval: Seconds between retry attempts (default: 10)
        max_retries: Maximum number of retry attempts (default: 60, total timeout = max_retries * retry_interval)
    
    Returns:
        True if all appliances restarted successfully, False otherwise
    """
    from core.appliance_config_loader import ApplianceConfigLoader
    from core.appliance_operations import execute_on_appliances_async
    
    logger.info("=" * 80)
    logger.info("RESTART ALL APPLIANCES (ASYNC)")
    logger.info("=" * 80)
    
    # Load all appliances
    appliance_loader = ApplianceConfigLoader()
    all_appliances = appliance_loader.get_all_appliances()
    
    if not all_appliances:
        logger.error("No appliances found in appliances.yaml")
        return False
    
    # Group appliances by type
    cms = []
    collectors = []
    appnodes = []
    others = []
    
    for name, appliance_config in all_appliances.items():
        appliance_type = appliance_config.get('type', '').lower()
        if appliance_type == 'cm':
            cms.append(name)
        elif appliance_type == 'collector':
            collectors.append(name)
        elif appliance_type == 'appnode':
            appnodes.append(name)
        else:
            others.append(name)
    
    # Order: CM → Collectors → AppNodes → Others
    ordered_appliances = cms + collectors + appnodes + others
    
    logger.info(f"Found {len(ordered_appliances)} appliances to restart:")
    logger.info(f"  - CMs: {len(cms)} ({', '.join(cms) if cms else 'none'})")
    logger.info(f"  - Collectors: {len(collectors)} ({', '.join(collectors) if collectors else 'none'})")
    logger.info(f"  - AppNodes: {len(appnodes)} ({', '.join(appnodes) if appnodes else 'none'})")
    if others:
        logger.info(f"  - Others: {len(others)} ({', '.join(others)})")
    logger.info("")
    
    # Execute restart asynchronously on all appliances (max 20 parallel)
    results, errors = execute_on_appliances_async(
        appliances=ordered_appliances,
        operation_func=core_restart_appliance,
        operation_name="restart",
        logger=logger,
        config=config,
        user=user,
        password=password,
        prompt_regex=prompt_regex,
        debug=debug,
        wait_for_availability=wait_for_availability,
        retry_interval=retry_interval,
        max_retries=max_retries
    )
    
    # Count results
    success_count = sum(1 for success in results.values() if success)
    failed_count = len(results) - success_count
    failed_appliances = [name for name, success in results.items() if not success]
    
    # Summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("RESTART SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total appliances: {len(ordered_appliances)}")
    logger.info(f"✓ Successful: {success_count}")
    logger.info(f"✗ Failed: {failed_count}")
    
    if failed_appliances:
        logger.error(f"Failed appliances: {', '.join(failed_appliances)}")
        for appliance in failed_appliances:
            if appliance in errors:
                logger.error(f"  - {appliance}: {errors[appliance]}")
    
    logger.info("=" * 80)
    
    # Return True only if all succeeded
    return failed_count == 0

def configure_network_ip_all(
    config,
    logger,
    verbose: bool = True,
    prefix: str = "/24",
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    """
    Configure network IP addresses on all appliances in order: CM → Collectors → AppNodes
    Uses IP addresses from appliances.yaml configuration.
    
    Args:
        config: Configuration object
        logger: Logger instance
        verbose: Enable verbose output
        prefix: Network prefix (default: /24)
        user: SSH username (optional)
        password: SSH password (optional)
        prompt_regex: CLI prompt regex (optional)
        debug: Enable debug output
    
    Returns:
        True if all appliances configured successfully, False otherwise
    """
    from core.appliance_operations import configure_network_ip as core_configure_network_ip
    from core.appliance_config_loader import ApplianceConfigLoader
    
    logger.info("=" * 80)
    logger.info("CONFIGURE NETWORK IP ON ALL APPLIANCES")
    logger.info("=" * 80)
    
    # Load all appliances
    appliance_loader = ApplianceConfigLoader()
    all_appliances = appliance_loader.get_all_appliances()
    
    if not all_appliances:
        logger.error("No appliances found in appliances.yaml")
        return False
    
    # Group appliances by type
    cms = []
    collectors = []
    appnodes = []
    others = []
    
    for name, appliance_config in all_appliances.items():
        appliance_type = appliance_config.get('type', '').lower()
        if appliance_type == 'cm':
            cms.append(name)
        elif appliance_type == 'collector':
            collectors.append(name)
        elif appliance_type == 'appnode':
            appnodes.append(name)
        else:
            others.append(name)
    
    # Order: CM → Collectors → AppNodes → Others
    ordered_appliances = cms + collectors + appnodes + others
    
    logger.info(f"Found {len(ordered_appliances)} appliances:")
    logger.info(f"  - CMs: {len(cms)} ({', '.join(cms) if cms else 'none'})")
    logger.info(f"  - Collectors: {len(collectors)} ({', '.join(collectors) if collectors else 'none'})")
    logger.info(f"  - AppNodes: {len(appnodes)} ({', '.join(appnodes) if appnodes else 'none'})")
    if others:
        logger.info(f"  - Others: {len(others)} ({', '.join(others)})")
    logger.info("")
    
    # Configure network IP on each appliance
    success_count = 0
    failed_count = 0
    failed_appliances = []
    
    for appliance_name in ordered_appliances:
        logger.info(f"➜ Configuring network IP on appliance: {appliance_name}")
        
        try:
            result = core_configure_network_ip(
                config=config,
                logger=logger,
                appliance_name=appliance_name,
                ip_address=None,  # Use IP from appliances.yaml
                prefix=prefix,
                user=user,
                password=password,
                prompt_regex=prompt_regex,
                debug=debug
            )
            
            if result:
                success_count += 1
                logger.info(f"✓ {appliance_name} network IP configured successfully\n")
            else:
                failed_count += 1
                failed_appliances.append(appliance_name)
                logger.error(f"✗ {appliance_name} network IP configuration failed\n")
        
        except Exception as e:
            failed_count += 1
            failed_appliances.append(appliance_name)
            logger.error(f"✗ {appliance_name} network IP configuration failed with exception: {str(e)}\n")
            if debug:
                import traceback
                logger.error(traceback.format_exc())
    
    # Summary
    logger.info("=" * 80)
    logger.info("NETWORK IP CONFIGURATION SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total appliances: {len(ordered_appliances)}")
    logger.info(f"✓ Successful: {success_count}")
    logger.info(f"✗ Failed: {failed_count}")
    
    if failed_appliances:
        logger.error(f"Failed appliances: {', '.join(failed_appliances)}")
    
    logger.info("=" * 80)
    logger.info("Note: Changes will take effect after network restart on each appliance")
    logger.info("=" * 80)
    
    # Return True only if all succeeded
    return failed_count == 0
    
    # Return True only if all succeeded
    return failed_count == 0

def configure_hosts_resolving_all(
    config,
    logger,
    verbose: bool = True,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    """
    Configure /etc/hosts resolving on all appliances in order: CM → Collectors → AppNodes
    Adds entries for:
    - Unix machines (raptor, ceraptos, sauropod) from machines_info.json
    - Other Guardium appliances from appliances.yaml
    
    Args:
        config: Configuration object
        logger: Logger instance
        verbose: Enable verbose output
        user: SSH username (optional, uses default from appliance type)
        password: SSH password (optional, uses cli_pwd from custom_variables)
        prompt_regex: CLI prompt regex (optional, uses default from appliance type)
        debug: Enable debug output
    
    Returns:
        True if all appliances configured successfully, False otherwise
    """
    from core.appliance_config_loader import ApplianceConfigLoader
    
    logger.info("=" * 80)
    logger.info("CONFIGURE HOSTS RESOLVING ON ALL APPLIANCES")
    logger.info("=" * 80)
    
    # Load all appliances
    appliance_loader = ApplianceConfigLoader()
    all_appliances = appliance_loader.get_all_appliances()
    
    if not all_appliances:
        logger.error("No appliances found in appliances.yaml")
        return False
    
    # Group appliances by type
    cms = []
    collectors = []
    appnodes = []
    others = []
    
    for name, appliance_config in all_appliances.items():
        appliance_type = appliance_config.get('type', '').lower()
        if appliance_type == 'cm':
            cms.append(name)
        elif appliance_type == 'collector':
            collectors.append(name)
        elif appliance_type == 'appnode':
            appnodes.append(name)
        else:
            others.append(name)
    
    # Order: CM → Collectors → AppNodes → Others
    ordered_appliances = cms + collectors + appnodes + others
    
    logger.info(f"Found {len(ordered_appliances)} appliances:")
    logger.info(f"  - CMs: {len(cms)} ({', '.join(cms) if cms else 'none'})")
    logger.info(f"  - Collectors: {len(collectors)} ({', '.join(collectors) if collectors else 'none'})")
    logger.info(f"  - AppNodes: {len(appnodes)} ({', '.join(appnodes) if appnodes else 'none'})")
    if others:
        logger.info(f"  - Others: {len(others)} ({', '.join(others)})")
    logger.info("")
    
    # Define operation function
    def configure_hosts_operation(appliance_name: str, **kwargs) -> bool:
        return core_configure_hosts(
            appliance_name=appliance_name,
            **kwargs
        )
    
    # Execute operation on all appliances asynchronously
    from core.appliance_operations import execute_on_appliances_async
    
    results, errors = execute_on_appliances_async(
        appliances=ordered_appliances,
        operation_func=configure_hosts_operation,
        operation_name="configure hosts resolving",
        logger=logger,
        config=config,
        user=user,
        password=password,
        prompt_regex=prompt_regex,
        debug=debug
    )
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("HOSTS CONFIGURATION SUMMARY")
    logger.info("=" * 80)
    
    success_count = sum(1 for success in results.values() if success)
    total_count = len(results)
    
    logger.info(f"Total appliances: {total_count}")
    logger.info(f"✓ Successful: {success_count}")
    logger.info(f"✗ Failed: {total_count - success_count}")
    
    if errors:
        logger.error("\nErrors encountered:")
        for appliance_name, error_msg in errors.items():
            logger.error(f"  - {appliance_name}: {error_msg}")
    
    all_success = all(results.values())
    
    if all_success:
        logger.info("\n✓ All appliances configured successfully")
    else:
        logger.error("\n✗ Some appliances failed configuration")
    
    logger.info("=" * 80)
    
    return all_success

def configure_ntp_all(
    config,
    logger,
    verbose: bool = True,
    ntp_servers: Optional[list] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    """
    Configure NTP on all appliances in order: CM → Collectors → AppNodes
    
    Args:
        config: Configuration object
        logger: Logger instance
        verbose: Enable verbose output
        ntp_servers: List of NTP servers (optional, defaults to pool.ntp.org)
        user: SSH username (optional, uses default from appliance type)
        password: SSH password (optional, uses cli_pwd from custom_variables)
        prompt_regex: CLI prompt regex (optional, uses default from appliance type)
        debug: Enable debug output
    
    Returns:
        True if all appliances configured successfully, False otherwise
    """
    from core.appliance_operations import configure_ntp as core_configure_ntp
    from core.appliance_config_loader import ApplianceConfigLoader
    
    logger.info("=" * 80)
    logger.info("CONFIGURE NTP ON ALL APPLIANCES")
    logger.info("=" * 80)
    
    # Load all appliances
    appliance_loader = ApplianceConfigLoader()
    all_appliances = appliance_loader.get_all_appliances()
    
    if not all_appliances:
        logger.error("No appliances found in appliances.yaml")
        return False
    
    # Group appliances by type
    cms = []
    collectors = []
    appnodes = []
    others = []
    
    for name, appliance_config in all_appliances.items():
        appliance_type = appliance_config.get('type', '').lower()
        if appliance_type == 'cm':
            cms.append(name)
        elif appliance_type == 'collector':
            collectors.append(name)
        elif appliance_type == 'appnode':
            appnodes.append(name)
        else:
            others.append(name)
    
    # Order: CM → Collectors → AppNodes → Others
    ordered_appliances = cms + collectors + appnodes + others
    
    logger.info(f"Found {len(ordered_appliances)} appliances:")
    logger.info(f"  - CMs: {len(cms)} ({', '.join(cms) if cms else 'none'})")
    logger.info(f"  - Collectors: {len(collectors)} ({', '.join(collectors) if collectors else 'none'})")
    logger.info(f"  - AppNodes: {len(appnodes)} ({', '.join(appnodes) if appnodes else 'none'})")
    if others:
        logger.info(f"  - Others: {len(others)} ({', '.join(others)})")
    logger.info("")
    
    # Define operation function
    def configure_ntp_operation(appliance_name: str, **kwargs) -> bool:
        return core_configure_ntp(
            appliance_name=appliance_name,
            **kwargs
        )
    
    # Execute operation on all appliances asynchronously
    from core.appliance_operations import execute_on_appliances_async
    
    results, errors = execute_on_appliances_async(
        appliances=ordered_appliances,
        operation_func=configure_ntp_operation,
        operation_name="configure NTP",
        logger=logger,
        config=config,
        ntp_servers=ntp_servers,
        user=user,
        password=password,
        prompt_regex=prompt_regex,
        debug=debug
    )
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("NTP CONFIGURATION SUMMARY")
    logger.info("=" * 80)
    
    success_count = sum(1 for success in results.values() if success)
    total_count = len(results)
    
    logger.info(f"Total appliances: {total_count}")
    logger.info(f"✓ Successful: {success_count}")
    logger.info(f"✗ Failed: {total_count - success_count}")
    
    if errors:
        logger.error("\nErrors encountered:")
        for appliance_name, error_msg in errors.items():
            logger.error(f"  - {appliance_name}: {error_msg}")
    
    all_success = all(results.values())
    
    if all_success:
        logger.info("\n✓ All appliances configured successfully")
    else:
        logger.error("\n✗ Some appliances failed configuration")
    
    logger.info("=" * 80)
    
    return all_success

def configure_system_settings_all(
    config,
    logger,
    verbose: bool = True,
    hostname: Optional[str] = None,
    domain: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:

    from core.appliance_operations import configure_system_settings as core_configure_system_settings
    from core.appliance_config_loader import ApplianceConfigLoader
    
    logger.info("=" * 80)
    logger.info("CONFIGURE SYSTEM SETTINGS ON ALL APPLIANCES")
    logger.info("=" * 80)
    
    # Load all appliances
    appliance_loader = ApplianceConfigLoader()
    all_appliances = appliance_loader.get_all_appliances()
    
    if not all_appliances:
        logger.error("No appliances found in appliances.yaml")
        return False
    
    # Group appliances by type
    cms = []
    collectors = []
    appnodes = []
    others = []
    
    for name, appliance_config in all_appliances.items():
        appliance_type = appliance_config.get('type', '').lower()
        if appliance_type == 'cm':
            cms.append(name)
        elif appliance_type == 'collector':
            collectors.append(name)
        elif appliance_type == 'appnode':
            appnodes.append(name)
        else:
            others.append(name)
    
    # Order: CM → Collectors → AppNodes → Others
    ordered_appliances = cms + collectors + appnodes + others
    
    logger.info(f"Found {len(ordered_appliances)} appliances:")
    logger.info(f"  - CMs: {len(cms)} ({', '.join(cms) if cms else 'none'})")
    logger.info(f"  - Collectors: {len(collectors)} ({', '.join(collectors) if collectors else 'none'})")
    logger.info(f"  - AppNodes: {len(appnodes)} ({', '.join(appnodes) if appnodes else 'none'})")
    if others:
        logger.info(f"  - Others: {len(others)} ({', '.join(others)})")
    logger.info("")
    
    # Define operation function
    def configure_settings_operation(appliance_name: str, **kwargs) -> bool:
        return core_configure_system_settings(
            appliance_name=appliance_name,
            **kwargs
        )
    
    # Execute operation on all appliances asynchronously
    from core.appliance_operations import execute_on_appliances_async
    
    results, errors = execute_on_appliances_async(
        appliances=ordered_appliances,
        operation_func=configure_settings_operation,
        operation_name="configure system settings",
        logger=logger,
        config=config,
        hostname=hostname,
        domain=domain,
        user=user,
        password=password,
        prompt_regex=prompt_regex,
        debug=debug
    )
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("CONFIGURATION SUMMARY")
    logger.info("=" * 80)
    
    success_count = sum(1 for success in results.values() if success)
    total_count = len(results)
    
    logger.info(f"Total appliances: {total_count}")
    logger.info(f"✓ Successful: {success_count}")
    logger.info(f"✗ Failed: {total_count - success_count}")
    
    if errors:
        logger.error("\nErrors encountered:")
        for appliance_name, error_msg in errors.items():
            logger.error(f"  - {appliance_name}: {error_msg}")
    
    all_success = all(results.values())
    
    if all_success:
        logger.info("\n✓ All appliances configured successfully")
    else:
        logger.error("\n✗ Some appliances failed configuration")
    
    logger.info("=" * 80)
    
    return all_success

def set_shared_secret_all(
    config,
    logger,
    verbose: bool = True,
    shared_secret: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    """
    Set shared secret on all appliances in order: CM → Collectors → AppNodes
    This must be done before registering appliances on Central Manager.
    
    Args:
        config: Configuration object
        logger: Logger instance
        verbose: Enable verbose output
        shared_secret: Shared secret value (optional, uses value from machines_info.json custom_variables)
        user: SSH username (optional, uses default from appliance type)
        password: SSH password (optional, uses cli_pwd from custom_variables)
        prompt_regex: CLI prompt regex (optional, uses default from appliance type)
        debug: Enable debug output
    
    Returns:
        True if all appliances configured successfully, False otherwise
    """
    from core.appliance_operations import set_shared_secret
    from core.appliance_config_loader import ApplianceConfigLoader
    
    logger.info("=" * 80)
    logger.info("SET SHARED SECRET ON ALL APPLIANCES")
    logger.info("=" * 80)
    
    # Load all appliances
    appliance_loader = ApplianceConfigLoader()
    all_appliances = appliance_loader.get_all_appliances()
    
    if not all_appliances:
        logger.error("No appliances found in appliances.yaml")
        return False
    
    # Sort appliances by type: CM → Collectors → AppNodes
    type_order = {'cm': 1, 'collector': 2, 'appnode': 3}
    sorted_appliances = sorted(
        all_appliances.items(),
        key=lambda x: type_order.get(x[1].get('type', '').lower(), 999)
    )
    
    logger.info(f"Found {len(sorted_appliances)} appliances to configure")
    
    # Define operation function
    def set_secret_operation(appliance_name: str, **kwargs) -> bool:
        return set_shared_secret(
            appliance_name=appliance_name,
            **kwargs
        )
    
    # Prepare appliance list
    appliance_names = [name for name, _ in sorted_appliances]
    
    # Execute operation on all appliances asynchronously
    from core.appliance_operations import execute_on_appliances_async
    
    results, errors = execute_on_appliances_async(
        appliances=appliance_names,
        operation_func=set_secret_operation,
        operation_name="set shared secret",
        logger=logger,
        config=config,
        shared_secret=shared_secret,
        user=user,
        password=password,
        prompt_regex=prompt_regex,
        debug=debug
    )
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("SHARED SECRET CONFIGURATION SUMMARY")
    logger.info("=" * 80)
    
    success_count = sum(1 for success in results.values() if success)
    total_count = len(results)
    
    logger.info(f"Total appliances: {total_count}")
    logger.info(f"Successful: {success_count}")
    logger.info(f"Failed: {total_count - success_count}")
    
    if errors:
        logger.error("\nErrors encountered:")
        for appliance_name, error_msg in errors.items():
            logger.error(f"  - {appliance_name}: {error_msg}")
    
    all_success = all(results.values())
    
    if all_success:
        logger.info("\n✓ Shared secret set successfully on all appliances")
    else:
        logger.error("\n✗ Some appliances failed shared secret configuration")
    
    logger.info("=" * 80)
    
    return all_success

def register_appliances_all(
    config,
    logger,
    verbose: bool = True,
    cm_ip: Optional[str] = None,
    cm_port: int = 8443,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True,
    timeout: int = 600
) -> bool:
    """
    Register all Collectors and AppNodes on Central Manager sequentially.
    Note: CM itself is not registered. Shared secret must be set on all appliances first.
    Registers appliances one by one to avoid potential conflicts.
    
    Args:
        config: Configuration object
        logger: Logger instance
        verbose: Enable verbose output
        cm_ip: Central Manager IP (optional, auto-detected from appliances.yaml)
        cm_port: Central Manager port (default: 8443)
        user: SSH username (optional, uses default from appliance type)
        password: SSH password (optional, uses cli_pwd from custom_variables)
        prompt_regex: CLI prompt regex (optional, uses default from appliance type)
        debug: Enable debug output
        timeout: Registration timeout in seconds (default: 600)
    
    Returns:
        True if all appliances registered successfully, False otherwise
    """
    from core.appliance_operations import register_appliance
    from core.appliance_config_loader import ApplianceConfigLoader
    
    logger.info("=" * 80)
    logger.info("REGISTER APPLIANCES ON CENTRAL MANAGER")
    logger.info("=" * 80)
    
    # Load all appliances
    appliance_loader = ApplianceConfigLoader()
    all_appliances = appliance_loader.get_all_appliances()
    
    if not all_appliances:
        logger.error("No appliances found in appliances.yaml")
        return False
    
    # Filter out CM - only register Collectors and AppNodes
    appliances_to_register = {
        name: cfg for name, cfg in all_appliances.items()
        if cfg.get('type', '').lower() in ['collector', 'appnode']
    }
    
    if not appliances_to_register:
        logger.warning("No Collectors or AppNodes found to register")
        return True
    
    # Sort by type: Collectors → AppNodes
    type_order = {'collector': 1, 'appnode': 2}
    sorted_appliances = sorted(
        appliances_to_register.items(),
        key=lambda x: type_order.get(x[1].get('type', '').lower(), 999)
    )
    
    logger.info(f"Found {len(sorted_appliances)} appliances to register")
    for name, cfg in sorted_appliances:
        logger.info(f"  - {name} ({cfg.get('type')})")
    
    # Register appliances sequentially (one by one)
    all_success = True
    for appliance_name, appliance_config in sorted_appliances:
        appliance_type = appliance_config.get('type', 'unknown')
        logger.info(f"\n{'='*80}")
        logger.info(f"Registering {appliance_type.upper()}: {appliance_name}")
        logger.info(f"{'='*80}")
        
        success = register_appliance(
            config=config,
            logger=logger,
            appliance_name=appliance_name,
            cm_ip=cm_ip,
            cm_port=cm_port,
            user=user,
            password=password,
            prompt_regex=prompt_regex,
            debug=debug,
            timeout=timeout
        )
        
        if not success:
            logger.error(f"Failed to register {appliance_name}")
            all_success = False
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("APPLIANCE REGISTRATION SUMMARY")
    logger.info("=" * 80)
    
    if all_success:
        logger.info("✓ All appliances registered successfully")
    else:
        logger.error("✗ Some appliances failed registration")
    
    logger.info("=" * 80)
    
    return all_success

def set_timezone_all(
    config,
    logger,
    verbose: bool = True,
    timezone: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    """
    Set timezone on all appliances in order: CM → Collectors → AppNodes
    
    Args:
        config: Configuration object
        logger: Logger instance
        verbose: Enable verbose output
        timezone: Timezone string (optional, defaults to Europe/Warsaw or from machines_info.json)
        user: SSH username (optional, uses default from appliance type)
        password: SSH password (optional, uses cli_pwd from custom_variables)
        prompt_regex: CLI prompt regex (optional, uses default from appliance type)
        debug: Enable debug output
    
    Returns:
        True if all appliances configured successfully, False otherwise
    """
    from core.appliance_operations import set_timezone
    from core.appliance_config_loader import ApplianceConfigLoader
    
    logger.info("=" * 80)
    logger.info("SET TIMEZONE ON ALL APPLIANCES")
    logger.info("=" * 80)
    
    # Load all appliances
    appliance_loader = ApplianceConfigLoader()
    all_appliances = appliance_loader.get_all_appliances()
    
    if not all_appliances:
        logger.error("No appliances found in appliances.yaml")
        return False
    
    # Sort appliances by type: CM → Collectors → AppNodes
    type_order = {'cm': 1, 'collector': 2, 'appnode': 3}
    sorted_appliances = sorted(
        all_appliances.items(),
        key=lambda x: type_order.get(x[1].get('type', '').lower(), 999)
    )
    
    logger.info(f"Found {len(sorted_appliances)} appliances to configure")
    
    # Define operation function
    def set_timezone_operation(appliance_name: str, **kwargs) -> bool:
        return set_timezone(
            appliance_name=appliance_name,
            **kwargs
        )
    
    # Prepare appliance list
    appliance_names = [name for name, _ in sorted_appliances]
    
    # Execute operation on all appliances asynchronously
    from core.appliance_operations import execute_on_appliances_async
    
    results, errors = execute_on_appliances_async(
        appliances=appliance_names,
        operation_func=set_timezone_operation,
        operation_name="set timezone",
        logger=logger,
        config=config,
        timezone=timezone,
        user=user,
        password=password,
        prompt_regex=prompt_regex,
        debug=debug
    )
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("TIMEZONE CONFIGURATION SUMMARY")
    logger.info("=" * 80)
    
    success_count = sum(1 for success in results.values() if success)
    total_count = len(results)
    
    logger.info(f"Total appliances: {total_count}")
    logger.info(f"Successful: {success_count}")
    logger.info(f"Failed: {total_count - success_count}")
    
    if errors:
        logger.error("\nErrors encountered:")
        for appliance_name, error_msg in errors.items():
            logger.error(f"  - {appliance_name}: {error_msg}")
    
    all_success = all(results.values())
    
    if all_success:
        logger.info("\n✓ Timezone set successfully on all appliances")
    else:
        logger.error("\n✗ Some appliances failed timezone configuration")
    
    logger.info("=" * 80)
    
    return all_success

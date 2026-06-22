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
    configure_hosts_resolving as core_configure_hosts,
    configure_aggr_settings,
    execute_on_appliances_async,
    reset_cli_password,
    set_shared_secret,
    configure_system_settings_consolidated,
    register_appliance,
    prepare_appliance_for_patching,
    get_patch_installation_order,
    install_and_monitor_patches
)

logger = get_logger(__name__)
def reset_cli_password_all(
    config,
    logger,
    verbose: bool = True,
    cloudsupport_password: Optional[str] = None,
    cli_password: Optional[str] = None,
    debug: bool = True
) -> bool:
    
    from core.appliance_operations import reset_cli_password, execute_on_appliances_async
    from core.appliance_config_loader import ApplianceConfigLoader
    
    logger.info("=" * 80)
    logger.info("RESET CLI PASSWORD ON ALL APPLIANCES")
    logger.info("=" * 80)
    
    # Load appliances from machines_info.json via ConfigLoader
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    all_appliances = appliance_loader.get_all_appliances()
    
    if not all_appliances:
        logger.error("No appliances found in machines_info.json")
        return False
    
    type_order = {'cm': 1, 'collector': 2, 'appnode': 3}
    sorted_appliances = sorted(
        all_appliances.items(),
        key=lambda x: type_order.get(x[1].get('type', '').lower(), 999)
    )
    
    appliance_names = [name for name, _ in sorted_appliances]
    
    logger.info(f"Found {len(appliance_names)} appliances")
    for name, cfg in sorted_appliances:
        logger.info(f"  - {name} ({cfg.get('type')})")
    
    results, errors = execute_on_appliances_async(
        appliances=appliance_names,
        operation_func=reset_cli_password,
        operation_name="reset_cli_password",
        logger=logger,
        config=config,
        cloudsupport_password=cloudsupport_password,
        cli_password=cli_password,
        debug=debug
    )
    
    logger.info("\n" + "=" * 80)
    logger.info("RESET CLI PASSWORD SUMMARY")
    logger.info("=" * 80)
    
    success_count = sum(1 for success in results.values() if success)
    failed_count = len(results) - success_count
    
    logger.info(f"✓ Successful: {success_count}/{len(results)}")
    if failed_count > 0:
        logger.error(f"✗ Failed: {failed_count}/{len(results)}")
        for appliance_name, success in results.items():
            if not success:
                error_msg = errors.get(appliance_name, "Unknown error")
                logger.error(f"  - {appliance_name}: {error_msg}")
    
    logger.info("=" * 80)
    
    return failed_count == 0

def set_shared_secret_all(
    config,
    logger,
    verbose: bool = True,
    shared_secret: Optional[str] = None,
    debug: bool = True
) -> bool:
    
    from core.appliance_operations import set_shared_secret, execute_on_appliances_async
    from core.appliance_config_loader import ApplianceConfigLoader
    
    logger.info("=" * 80)
    logger.info("SET SHARED SECRET ON ALL APPLIANCES")
    logger.info("=" * 80)
    
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    all_appliances = appliance_loader.get_all_appliances()
    
    if not all_appliances:
        logger.error("No appliances found in machines_info.json")
        return False
    
    type_order = {'cm': 1, 'collector': 2, 'appnode': 3}
    sorted_appliances = sorted(
        all_appliances.items(),
        key=lambda x: type_order.get(x[1].get('type', '').lower(), 999)
    )
    
    appliance_names = [name for name, _ in sorted_appliances]
    
    logger.info(f"Found {len(appliance_names)} appliances")
    for name, cfg in sorted_appliances:
        logger.info(f"  - {name} ({cfg.get('type')})")
    
    results, errors = execute_on_appliances_async(
        appliances=appliance_names,
        operation_func=set_shared_secret,
        operation_name="set_shared_secret",
        logger=logger,
        config=config,
        shared_secret=shared_secret,
        debug=debug
    )
    
    logger.info("\n" + "=" * 80)
    logger.info("SET SHARED SECRET SUMMARY")
    logger.info("=" * 80)
    
    success_count = sum(1 for success in results.values() if success)
    failed_count = len(results) - success_count
    
    logger.info(f"✓ Successful: {success_count}/{len(results)}")
    if failed_count > 0:
        logger.error(f"✗ Failed: {failed_count}/{len(results)}")
        for appliance_name, success in results.items():
            if not success:
                error_msg = errors.get(appliance_name, "Unknown error")
                logger.error(f"  - {appliance_name}: {error_msg}")
    
    logger.info("=" * 80)
    
    return failed_count == 0

def configure_aggr_settings_all(
    config,
    logger,
    verbose: bool = True,
    debug: bool = True
) -> bool:
    """
    Configure aggregation settings on all appliances:
    - store run_cleanup_orphans_daily off
    - store purge_age_period 0 (with confirmation, only on CM)
    """
    
    from core.appliance_operations import configure_aggr_settings, execute_on_appliances_async
    from core.appliance_config_loader import ApplianceConfigLoader
    
    logger.info("=" * 80)
    logger.info("CONFIGURE AGGREGATION SETTINGS ON ALL APPLIANCES")
    logger.info("=" * 80)
    
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    all_appliances = appliance_loader.get_all_appliances()
    
    if not all_appliances:
        logger.error("No appliances found in machines_info.json")
        return False
    
    type_order = {'cm': 1, 'collector': 2, 'appnode': 3}
    sorted_appliances = sorted(
        all_appliances.items(),
        key=lambda x: type_order.get(x[1].get('type', '').lower(), 999)
    )
    
    appliance_names = [name for name, _ in sorted_appliances]
    
    logger.info(f"Found {len(appliance_names)} appliances")
    for name, cfg in sorted_appliances:
        logger.info(f"  - {name} ({cfg.get('type')})")
    
    results, errors = execute_on_appliances_async(
        appliances=appliance_names,
        operation_func=configure_aggr_settings,
        operation_name="configure_aggr_settings",
        logger=logger,
        config=config,
        debug=debug
    )
    
    logger.info("\n" + "=" * 80)
    logger.info("CONFIGURE STORE SETTINGS SUMMARY")
    logger.info("=" * 80)
    
    success_count = sum(1 for success in results.values() if success)
    failed_count = len(results) - success_count
    
    logger.info(f"✓ Successful: {success_count}/{len(results)}")
    if failed_count > 0:
        logger.error(f"✗ Failed: {failed_count}/{len(results)}")
        for appliance_name, success in results.items():
            if not success:
                error_msg = errors.get(appliance_name, "Unknown error")
                logger.error(f"  - {appliance_name}: {error_msg}")
    
    logger.info("=" * 80)
    
    return failed_count == 0


def import_definitions_on_cm(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm02",
    definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
    debug: bool = True
) -> bool:
    from core.guardium_rest_api import import_definitions_files
    
    logger.info("=" * 80)
    logger.info("IMPORT DEFINITIONS ON CM")
    logger.info("=" * 80)
    
    definition_files = [
        "exp_default_policy.sql",
        "exp_dashboard_training.sql"
    ]
    
    logger.info(f"CM Appliance: {cm_appliance}")
    logger.info(f"Definitions directory: {definitions_dir}")
    logger.info(f"Files to import: {', '.join(definition_files)}")
    
    success = import_definitions_files(
        config=config,
        logger=logger,
        appliance_name=cm_appliance,
        definition_files=definition_files,
        definitions_dir=definitions_dir,
        debug=debug
    )
    
    if success:
        logger.info("\n" + "=" * 80)
        logger.info("✓ All definitions imported successfully")
        logger.info("=" * 80)
    
    return success

def install_policy_on_collector(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm02",
    collector_appliance: str = "coll2",
    policy_name: str = "Log Everything",
    max_outer_retries: int = 5,
    outer_retry_delay: int = 120,
    debug: bool = True
) -> bool:
    
    from core.guardium_rest_api import create_guardium_api
    from core.appliance_config_loader import ApplianceConfigLoader
    import time
    
    logger.info("=" * 80)
    logger.info("INSTALL POLICY ON COLLECTOR")
    logger.info("=" * 80)
    
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    collector_config = appliance_loader.get_appliance(collector_appliance)
    
    if not collector_config:
        logger.error(f"Collector '{collector_appliance}' not found in machines_info.json")
        return False
    
    collector_ip = collector_config.get('ip')
    if not collector_ip:
        logger.error(f"No IP configured for collector '{collector_appliance}'")
        return False
    
    logger.info(f"CM Appliance: {cm_appliance}")
    logger.info(f"Collector: {collector_appliance} ({collector_ip})")
    logger.info(f"Policy: {policy_name}")
    
    try:
        api = create_guardium_api(config, logger, appliance_name=cm_appliance)
        
        demo_password = config.get_custom_variable('pwd')
        if not demo_password:
            logger.error("pwd not found in custom_variables")
            return False
        
        username = 'demo'
        logger.info(f"Authenticating as '{username}' user...")
        api.get_token(username=username, password=demo_password)
        logger.info("✓ Authentication successful")
        
        if debug:
            logger.info(f"API User: {username}")
            logger.info(f"CM Appliance: {cm_appliance}")
            logger.info(f"Target Collector: {collector_appliance} ({collector_ip})")
        
        error_code = '999'
        error_message = 'Unknown error'
        
        for outer_attempt in range(1, max_outer_retries + 1):
            logger.info(f"\nAttempt {outer_attempt}/{max_outer_retries}: Installing policy '{policy_name}' on collector {collector_ip}...")
            
            result = api.install_policy(
                policy=policy_name,
                api_target_host=collector_ip,
                max_retries=3,
                retry_delay=60,
                debug=debug
            )
            
            if debug:
                logger.info(f"API Response: {result}")
            
            error_code = result.get('ErrorCode') or result.get('ID', '0')
            error_message = result.get('ErrorMessage') or result.get('Message', '')
            
            if debug:
                logger.info(f"Parsed error_code: {error_code}")
                logger.info(f"Parsed error_message: {error_message}")
            
            if error_code == '0':
                logger.info(f"✓ Policy '{policy_name}' installed successfully on {collector_appliance}")
                logger.info("=" * 80)
                return True
            
            if error_code == '15' and outer_attempt < max_outer_retries:
                logger.warning(f"⚠ Target host still offline after inner retries. Outer retry {outer_attempt}/{max_outer_retries}")
                logger.info(f"Waiting {outer_retry_delay}s before next attempt...")
                time.sleep(outer_retry_delay)
                continue
            
            if outer_attempt == max_outer_retries:
                logger.error(f"✗ Failed to install policy after {max_outer_retries} attempts: Code={error_code}, Message={error_message}")
                logger.info("=" * 80)
                return False
        
        logger.error(f"✗ Failed to install policy: Code={error_code}, Message={error_message}")
        logger.info("=" * 80)
        return False
        
    except Exception as e:
        logger.error(f"✗ Failed to install policy: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False

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
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    collector_config = appliance_loader.get_appliance(collector_name)
    
    if not collector_config:
        logger.error(f"Collector '{collector_name}' not found in machines_info.json")
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
    
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    appliance_config = appliance_loader.get_appliance(appliance_name)
    
    if not appliance_config:
        logger.error(f"Appliance '{appliance_name}' not found in machines_info.json")
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
                roles='admin,cli,user,vulnerability-assess,fam'
            )
            logger.info("✓ Roles assigned: admin, cli, user, vulnerability-assess, fam")
            
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
    
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    appliance_config = appliance_loader.get_appliance(appliance_name)
    
    if not appliance_config:
        logger.error(f"Appliance '{appliance_name}' not found in machines_info.json")
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
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    all_appliances = appliance_loader.get_all_appliances()
    
    if not all_appliances:
        logger.error("No appliances found in machines_info.json")
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

def configure_system_settings_all(
    config,
    logger,
    verbose: bool = True,
    hostname: Optional[str] = None,
    domain: Optional[str] = None,
    ip_address: Optional[str] = None,
    prefix: str = "/24",
    timezone: Optional[str] = None,
    ntp_servers: Optional[list] = None,
    configure_hosts: bool = True,
    gid: Optional[int] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    from core.appliance_operations import configure_system_settings_consolidated
    from core.appliance_config_loader import ApplianceConfigLoader
    
    logger.info("=" * 80)
    logger.info("CONFIGURE ALL SYSTEM SETTINGS (CONSOLIDATED)")
    logger.info("=" * 80)
    
    # Load all appliances
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    all_appliances = appliance_loader.get_all_appliances()
    
    if not all_appliances:
        logger.error("No appliances found in machines_info.json")
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
    def configure_consolidated_operation(appliance_name: str, **kwargs) -> bool:
        return configure_system_settings_consolidated(
            appliance_name=appliance_name,
            **kwargs
        )
    
    # Execute operation on all appliances asynchronously
    from core.appliance_operations import execute_on_appliances_async
    
    results, errors = execute_on_appliances_async(
        appliances=ordered_appliances,
        operation_func=configure_consolidated_operation,
        operation_name="configure all system settings (consolidated)",
        logger=logger,
        config=config,
        hostname=hostname,
        domain=domain,
        ip_address=ip_address,
        prefix=prefix,
        timezone=timezone,
        ntp_servers=ntp_servers,
        configure_hosts=configure_hosts,
        gid=gid,
        user=user,
        password=password,
        prompt_regex=prompt_regex,
        debug=debug
    )
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("CONSOLIDATED CONFIGURATION SUMMARY")
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
        logger.info("Note: All operations completed in single CLI session per appliance")
    else:
        logger.error("\n✗ Some appliances failed configuration")
    
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
    timeout: int = 600,
    registration_check_delay: int = 120
) -> bool:
    """
    Register all Collectors and AppNodes on Central Manager in parallel.
    Note: CM itself is not registered. Shared secret must be set on all appliances first.
    Registers appliances in parallel (max 20 workers) for faster execution.
    
    Args:
        config: Configuration object
        logger: Logger instance
        verbose: Enable verbose output
        cm_ip: Central Manager IP (optional, auto-detected from machines_info.json)
        cm_port: Central Manager port (default: 8443)
        user: SSH username (optional, uses default from appliance type)
        password: SSH password (optional, uses cli_pwd from custom_variables)
        prompt_regex: CLI prompt regex (optional, uses default from appliance type)
        debug: Enable debug output
        timeout: Registration timeout in seconds (default: 600)
        registration_check_delay: Delay in seconds before checking registration status after timeout or "Fail:" (default: 120)
    
    Returns:
        True if all appliances registered successfully, False otherwise
    """
    from core.appliance_operations import register_appliance, execute_on_appliances_async
    from core.appliance_config_loader import ApplianceConfigLoader
    
    logger.info("=" * 80)
    logger.info("REGISTER APPLIANCES ON CENTRAL MANAGER (PARALLEL)")
    logger.info("=" * 80)
    
    # Load all appliances
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    all_appliances = appliance_loader.get_all_appliances()
    
    if not all_appliances:
        logger.error("No appliances found in machines_info.json")
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
    logger.info("")
    
    # Prepare appliance list
    appliance_names = [name for name, _ in sorted_appliances]
    
    # Define operation function
    def register_operation(appliance_name: str, **kwargs) -> bool:
        return register_appliance(
            appliance_name=appliance_name,
            **kwargs
        )
    
    # Execute registration on all appliances asynchronously
    results, errors = execute_on_appliances_async(
        appliances=appliance_names,
        operation_func=register_operation,
        operation_name="register appliance",
        logger=logger,
        config=config,
        cm_ip=cm_ip,
        cm_port=cm_port,
        user=user,
        password=password,
        prompt_regex=prompt_regex,
        debug=debug,
        timeout=timeout,
        registration_check_delay=registration_check_delay
    )
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("APPLIANCE REGISTRATION SUMMARY")
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
        logger.info("\n✓ All appliances registered successfully")
    else:
        logger.error("\n✗ Some appliances failed registration")
    
    logger.info("=" * 80)
    
    return all_success

def prepare_appliances_for_patching_all(
    config,
    logger,
    verbose: bool = True,
    patches_source_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/patches/",
    cloudsupport_password: Optional[str] = None,
    debug: bool = True
) -> bool:
    """
    Prepare all appliances for patching by copying patch files to each appliance.
    Executes in parallel (max 20 workers) for all appliances.
    
    Args:
        config: Configuration object
        logger: Logger instance
        verbose: Enable verbose output
        patches_source_dir: Local directory containing patch files
        cloudsupport_password: Password for cloudsupport user (optional, uses custom_variables)
        debug: Enable debug output
    
    Returns:
        True if all appliances prepared successfully, False otherwise
    """
    from core.appliance_operations import prepare_appliance_for_patching, execute_on_appliances_async
    from core.appliance_config_loader import ApplianceConfigLoader
    
    logger.info("=" * 80)
    logger.info("PREPARE ALL APPLIANCES FOR PATCHING")
    logger.info("=" * 80)
    
    # Load all appliances
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    all_appliances = appliance_loader.get_all_appliances()
    
    if not all_appliances:
        logger.error("No appliances found in machines_info.json")
        return False
    
    # Sort by type: CM → Collectors → AppNodes
    type_order = {'cm': 1, 'collector': 2, 'appnode': 3}
    sorted_appliances = sorted(
        all_appliances.items(),
        key=lambda x: type_order.get(x[1].get('type', '').lower(), 999)
    )
    
    appliance_names = [name for name, _ in sorted_appliances]
    
    logger.info(f"Found {len(appliance_names)} appliances to prepare")
    for name, cfg in sorted_appliances:
        logger.info(f"  - {name} ({cfg.get('type')})")
    
    # Execute in parallel (max 20 workers)
    results, errors = execute_on_appliances_async(
        appliances=appliance_names,
        operation_func=prepare_appliance_for_patching,
        operation_name="prepare_for_patching",
        logger=logger,
        config=config,
        patches_source_dir=patches_source_dir,
        cloudsupport_password=cloudsupport_password,
        debug=debug
    )
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("PREPARE FOR PATCHING SUMMARY")
    logger.info("=" * 80)
    
    success_count = sum(1 for success in results.values() if success)
    failed_count = len(results) - success_count
    
    logger.info(f"✓ Successful: {success_count}/{len(results)}")
    if failed_count > 0:
        logger.error(f"✗ Failed: {failed_count}/{len(results)}")
        for appliance_name, success in results.items():
            if not success:
                error_msg = errors.get(appliance_name, "Unknown error")
                logger.error(f"  - {appliance_name}: {error_msg}")
    
    logger.info("=" * 80)
    
    return failed_count == 0

def install_and_monitor_patches_all(
    config,
    logger,
    verbose: bool = True,
    patch_selection: Optional[str] = None,
    reinstall_answer: str = "y",
    check_interval: int = 60,
    max_checks: int = 60,
    user: Optional[str] = None,
    password: Optional[str] = None,
    debug: bool = True
) -> bool:
    """
    Install and monitor patches on all appliances in parallel.
    
    This function:
    1. Gets patch installation order from CM (if patch_selection not provided)
    2. Installs patches on all appliances in parallel
    3. Monitors installation progress on all appliances in parallel
    
    Args:
        config: Configuration object
        logger: Logger instance
        verbose: Enable verbose output
        patch_selection: Comma-separated patch positions (e.g., "2,1,3"). If None, will be determined from CM.
        reinstall_answer: Answer to reinstall question ("y" or "n", default: "y")
        check_interval: Seconds between status checks (default: 60)
        max_checks: Maximum number of checks (default: 60)
        user: SSH username (optional, uses 'cli' by default)
        password: SSH password (optional, uses cli_pwd from custom_variables)
        debug: Enable debug output
    
    Returns:
        True if all appliances patched successfully, False otherwise
    """
    from core.appliance_operations import (
        get_patch_installation_order,
        install_and_monitor_patches,
        execute_on_appliances_async
    )
    from core.appliance_config_loader import ApplianceConfigLoader
    
    logger.info("=" * 80)
    logger.info("INSTALL AND MONITOR PATCHES ON ALL APPLIANCES")
    logger.info("=" * 80)
    
    # Load all appliances
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    all_appliances = appliance_loader.get_all_appliances()
    
    if not all_appliances:
        logger.error("No appliances found in machines_info.json")
        return False
    
    # Get patch selection if not provided
    if not patch_selection:
        logger.info("\n➜ Patch selection not provided, determining from CM...")
        
        # Find CM
        cm_appliances = {name: cfg for name, cfg in all_appliances.items() 
                        if cfg.get('type', '').lower() == 'cm'}
        
        if not cm_appliances:
            logger.error("No Central Manager found in machines_info.json")
            return False
        
        cm_name = list(cm_appliances.keys())[0]
        logger.info(f"Using CM: {cm_name}")
        
        # Get patch installation order from CM
        patch_selection = get_patch_installation_order(
            config=config,
            logger=logger,
            appliance_name=cm_name,
            user=user,
            password=password,
            debug=debug
        )
        
        if not patch_selection:
            logger.error("Failed to determine patch installation order from CM")
            return False
        
        logger.info(f"✓ Patch selection determined: {patch_selection}")
    else:
        logger.info(f"Using provided patch selection: {patch_selection}")
    
    # Get list of all appliance names
    appliance_names = list(all_appliances.keys())
    
    logger.info(f"\nFound {len(appliance_names)} appliances to patch:")
    for name in appliance_names:
        appliance_type = all_appliances[name].get('type', 'unknown')
        logger.info(f"  - {name} ({appliance_type})")
    
    # Define operation function
    def install_and_monitor_operation(appliance_name: str, **kwargs) -> bool:
        return install_and_monitor_patches(
            appliance_name=appliance_name,
            **kwargs
        )
    
    # Execute operation on all appliances asynchronously
    logger.info("\n" + "=" * 80)
    logger.info("Starting parallel patch installation and monitoring...")
    logger.info("=" * 80)
    
    results, errors = execute_on_appliances_async(
        appliances=appliance_names,
        operation_func=install_and_monitor_operation,
        operation_name="install and monitor patches",
        logger=logger,
        config=config,
        patch_selection=patch_selection,
        reinstall_answer=reinstall_answer,
        check_interval=check_interval,
        max_checks=max_checks,
        user=user,
        password=password,
        debug=debug
    )
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("PATCH INSTALLATION SUMMARY")
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
    
    all_success = success_count == total_count
    
    if all_success:
        logger.info("\n✓ All appliances patched successfully")
    else:
        logger.error("\n✗ Some appliances failed patching")
    
    logger.info("=" * 80)
    
    return all_success



def prepare_appliance_for_patching_single(
    config,
    logger,
    verbose: bool = True,
    appliance_name: Optional[str] = None,
    patches_source_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/patches/",
    cloudsupport_password: Optional[str] = None,
    debug: bool = True
) -> bool:
    from core.appliance_operations import prepare_appliance_for_patching as core_prepare
    
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    return core_prepare(
        config=config,
        logger=logger,
        appliance_name=appliance_name,
        patches_source_dir=patches_source_dir,
        cloudsupport_password=cloudsupport_password,
        debug=debug
    )


def install_patch_on_appliance_single(
    config,
    logger,
    verbose: bool = True,
    appliance_name: Optional[str] = None,
    patch_selection: Optional[str] = None,
    reinstall_answer: str = "y",
    user: Optional[str] = None,
    password: Optional[str] = None,
    debug: bool = True
) -> bool:
    from core.appliance_operations import install_patch_on_appliance as core_install
    
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    if not patch_selection:
        logger.error("patch_selection is required")
        return False
    
    return core_install(
        config=config,
        logger=logger,
        appliance_name=appliance_name,
        patch_selection=patch_selection,
        reinstall_answer=reinstall_answer,
        user=user,
        password=password,
        debug=debug
    )



def copy_single_file_to_appliance_task(
    config,
    logger,
    verbose: bool = True,
    appliance_name: Optional[str] = None,
    source_file_path: Optional[str] = None,
    target_dir: str = "/var/IBM/Guardium/log/patches/",
    owner: str = "tomcat:tomcat",
    cloudsupport_password: Optional[str] = None,
    debug: bool = True
) -> bool:
    from core.appliance_operations import copy_single_file_to_appliance
    
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    if not source_file_path:
        logger.error("source_file_path is required")
        return False
    
    return copy_single_file_to_appliance(
        config=config,
        logger=logger,
        appliance_name=appliance_name,
        source_file_path=source_file_path,
        target_dir=target_dir,
        owner=owner,
        cloudsupport_password=cloudsupport_password,
        debug=debug
    )

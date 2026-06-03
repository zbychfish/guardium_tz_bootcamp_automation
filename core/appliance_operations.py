#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Appliance Operations - Reusable functions for Guardium appliance operations
"""

import time
import random
from typing import Optional, List
from .appliance_client import ApplianceClient
from .appliance_config_loader import ApplianceConfigLoader
import concurrent.futures
from typing import Callable, Dict, Any, Tuple


def execute_on_appliances_async(
    appliances: List[str],
    operation_func: Callable,
    operation_name: str,
    logger,
    **operation_kwargs
) -> Tuple[Dict[str, bool], Dict[str, str]]:
    """
    Execute an operation on multiple appliances asynchronously.
    This is a reusable function for parallel execution of appliance operations.
    
    Args:
        appliances: List of appliance names to operate on
        operation_func: Function to execute on each appliance (must accept appliance_name as first arg)
        operation_name: Name of the operation (for logging)
        logger: Logger instance
        **operation_kwargs: Additional keyword arguments to pass to operation_func
    
    Returns:
        Tuple of (results_dict, errors_dict) where:
        - results_dict: {appliance_name: success_bool}
        - errors_dict: {appliance_name: error_message}
    
    Example:
        results, errors = execute_on_appliances_async(
            appliances=['cm02', 'coll1', 'appnode1'],
            operation_func=restart_appliance,
            operation_name="restart",
            logger=logger,
            config=config,
            debug=True,
            wait_for_availability=True
        )
    """
    if not appliances:
        logger.warning("No appliances provided for async execution")
        return {}, {}
    
    # Determine number of workers (max 20 parallel operations)
    max_workers = min(len(appliances), 20)
    
    logger.info(f"Starting async {operation_name} on {len(appliances)} appliances (max {max_workers} parallel)")
    logger.info(f"Appliances: {', '.join(appliances)}")
    logger.info("")
    
    results = {}
    errors = {}
    
    def execute_single(appliance_name: str) -> Tuple[str, bool, Optional[str]]:
        """Execute operation on single appliance and return result"""
        try:
            logger.info(f"[{appliance_name}] Starting {operation_name}...")
            success = operation_func(
                appliance_name=appliance_name,
                logger=logger,
                **operation_kwargs
            )
            if success:
                logger.info(f"[{appliance_name}] ✓ {operation_name} completed successfully")
            else:
                logger.error(f"[{appliance_name}] ✗ {operation_name} failed")
            return appliance_name, success, None
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[{appliance_name}] ✗ {operation_name} failed with exception: {error_msg}")
            return appliance_name, False, error_msg
    
    # Execute operations in parallel using ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_appliance = {
            executor.submit(execute_single, appliance): appliance 
            for appliance in appliances
        }
        
        # Wait for all tasks to complete
        for future in concurrent.futures.as_completed(future_to_appliance):
            appliance_name, success, error = future.result()
            results[appliance_name] = success
            if error:
                errors[appliance_name] = error
    
    return results, errors

def restart_appliance(
    config,
    logger,
    appliance_name: str,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True,
    wait_for_availability: bool = True,
    retry_interval: int = 10,
    max_retries: int = 60
) -> bool:
    
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
                total_timeout = max_retries * retry_interval
                
                logger.info(f"\n⌛ Waiting for appliance to come back online...")
                logger.info(f"   Retry interval: {retry_interval}s")
                logger.info(f"   Max retries: {max_retries}")
                logger.info(f"   Total timeout: ~{total_timeout}s (~{total_timeout//60}m)")
                
                start_time = time.time()
                retry_count = 0
                
                while retry_count < max_retries:
                    retry_count += 1
                    
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
                            logger.info(f"✓ Appliance is back online (after {elapsed}s, {retry_count} attempts)")
                            logger.info("=" * 80)
                            logger.info("Appliance restarted successfully")
                            logger.info("=" * 80)
                            return True
                    except Exception:
                        pass
                    
                    if retry_count < max_retries:
                        logger.debug(f"   Attempt {retry_count}/{max_retries} failed, waiting {retry_interval}s...")
                        time.sleep(retry_interval)
                
                elapsed = int(time.time() - start_time)
                logger.error(f"✗ Timeout waiting for appliance (waited {elapsed}s, {retry_count} attempts)")
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

def configure_network_ip(
    config,
    logger,
    appliance_name: str,
    ip_address: Optional[str] = None,
    prefix: str = "/24",
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    """
    Configure network IP address on Guardium appliance.
    
    Args:
        config: Configuration object
        logger: Logger instance
        appliance_name: Name of the appliance
        ip_address: IP address to set (optional, uses IP from appliances.yaml if not provided)
        prefix: Network prefix (default: /24)
        user: SSH username (optional, uses default from appliance type)
        password: SSH password (optional, uses cli_pwd from custom_variables)
        prompt_regex: CLI prompt regex (optional, uses default from appliance type)
        debug: Enable debug output
    
    Returns:
        bool: True if successful, False otherwise
    
    Example:
        configure_network_ip(config, logger, 'cm02', ip_address='10.240.64.9')
    """
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    logger.info("=" * 80)
    logger.info(f"CONFIGURE NETWORK IP: {appliance_name}")
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
    
    # Use IP from appliances.yaml if not provided
    if not ip_address:
        ip_address = host
        logger.info(f"Using IP address from appliances.yaml: {ip_address}")
    
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
    logger.info(f"Setting IP: {ip_address}{prefix}")
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
        
        # Check current network configuration
        logger.info("\n➜ Checking current network configuration...")
        current_config = client.execute_command("show network interface all")
        logger.info(f"Current configuration:\n{current_config}")
        
        # Set network IP
        command = f"store network interface ip {ip_address}{prefix}"
        logger.info(f"\n➜ Executing: {command}")
        output = client.execute_command(command)
        logger.info(f"Command output:\n{output}")
        
        # Verify the change
        if "This change will take effect after the next network restart" in output or "ok" in output:
            logger.info("✓ Network IP configuration command executed successfully")
            
            # Show updated configuration
            logger.info("\n➜ Verifying new configuration...")
            new_config = client.execute_command("show network interface all")
            logger.info(f"New configuration:\n{new_config}")
            
            # Check if IP is in the output
            if ip_address and ip_address in new_config:
                logger.info(f"✓ IP address {ip_address} confirmed in configuration")
            else:
                logger.warning(f"⚠ IP address {ip_address} not found in configuration output")
            
            client.disconnect()
            
            logger.info("=" * 80)
            logger.info("Network IP configured successfully")
            logger.info("Note: Changes will take effect after network restart")
            logger.info("=" * 80)
            return True
        else:
            logger.error(f"✗ Unexpected output: {output}")
            client.disconnect()
            return False
        
    except Exception as e:
        logger.error(f"Error configuring network IP: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def set_shared_secret(
    config,
    logger,
    appliance_name: str,
    shared_secret: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    """
    Set shared secret on Guardium appliance.
    
    Args:
        config: Configuration object
        logger: Logger instance
        appliance_name: Name of the appliance
        shared_secret: Shared secret value (optional, uses value from machines_info.json custom_variables if not provided)
        user: SSH username (optional, uses default from appliance type)
        password: SSH password (optional, uses cli_pwd from custom_variables)
        prompt_regex: CLI prompt regex (optional, uses default from appliance type)
        debug: Enable debug output
    
    Returns:
        bool: True if successful, False otherwise
    
    Example:
        set_shared_secret(config, logger, 'cm02', shared_secret='guardium')
    """
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    logger.info("=" * 80)
    logger.info(f"SET SHARED SECRET: {appliance_name}")
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
    
    # Use shared_secret from custom_variables (machines_info.json) if not provided
    if not shared_secret:
        shared_secret = config.get_custom_variable('shared_secret')
        if shared_secret:
            logger.info("Using shared_secret from custom_variables (machines_info.json)")
        else:
            logger.error("shared_secret not provided and not found in custom_variables")
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
        
        # Set shared secret
        command = f"store system shared secret {shared_secret}"
        logger.info(f"\n➜ Executing: store system shared secret ***")
        output = client.execute_command(command)
        logger.info(f"Command output:\n{output}")
        
        client.disconnect()
        
        # Verify success
        # Note: execute_command filters out "ok" line, so we check for "Command ran on:" or absence of error
        if "error" in output.lower() or "failed" in output.lower():
            logger.error(f"✗ Command failed: {output}")
            return False
        elif "Command ran on:" in output or not output.strip():
            # Success: either has timestamp or empty output (ok was filtered)
            logger.info("=" * 80)
            logger.info("✓ Shared secret set successfully")
            logger.info("=" * 80)
            return True
        else:
            logger.warning(f"⚠ Unexpected output (assuming success): {output}")
            logger.info("=" * 80)
            logger.info("✓ Shared secret set successfully")
            logger.info("=" * 80)
            return True
        
    except Exception as e:
        logger.error(f"Error setting shared secret: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def register_appliance(
    config,
    logger,
    appliance_name: str,
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
    Register appliance (Collector or AppNode) on Central Manager.
    
    Args:
        config: Configuration object
        logger: Logger instance
        appliance_name: Name of the appliance to register
        cm_ip: Central Manager IP address (optional, auto-detected from appliances.yaml)
        cm_port: Central Manager port (default: 8443)
        user: SSH username (optional, uses default from appliance type)
        password: SSH password (optional, uses cli_pwd from custom_variables)
        prompt_regex: CLI prompt regex (optional, uses default from appliance type)
        debug: Enable debug output
        timeout: Command timeout in seconds (default: 600 - 10 minutes)
        registration_check_delay: Delay in seconds before checking registration status after timeout or "Fail:" (default: 120)
    
    Returns:
        bool: True if successful, False otherwise
    
    Example:
        register_appliance(config, logger, 'coll1', cm_ip='10.240.64.9')
    """
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    logger.info("=" * 80)
    logger.info(f"REGISTER APPLIANCE: {appliance_name}")
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
    
    # Auto-detect CM IP if not provided
    if not cm_ip:
        all_appliances = appliance_loader.get_all_appliances()
        cm_appliances = {name: cfg for name, cfg in all_appliances.items() 
                        if cfg.get('type', '').lower() == 'cm'}
        
        if not cm_appliances:
            logger.error("No Central Manager found in appliances.yaml")
            return False
        
        if len(cm_appliances) > 1:
            logger.warning(f"Multiple CMs found: {list(cm_appliances.keys())}")
            logger.warning("Using the first one. Specify cm_ip to use a different CM.")
        
        cm_name = list(cm_appliances.keys())[0]
        cm_ip = cm_appliances[cm_name].get('ip')
        logger.info(f"Auto-detected Central Manager: {cm_name} at {cm_ip}")
    
    if not cm_ip:
        logger.error("Central Manager IP not found")
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
    logger.info(f"Central Manager: {cm_ip}:{cm_port}")
    logger.info(f"User: {user}")
    logger.info(f"Timeout: {timeout} seconds")
    
    try:
        # Connect to appliance
        client = ApplianceClient(
            host=host,
            user=user,
            password=password,
            prompt_regex=prompt_regex,
            initial_pattern=None,
            timeout=timeout,
            strip_ansi=True,
            debug=debug
        )
        
        if not client.connect():
            logger.error("Failed to connect to appliance")
            return False
        
        # Check unit type before registration
        logger.info("\n➜ Checking unit type before registration...")
        unit_type_output = client.execute_command("show unit type")
        logger.info(f"Unit type:\n{unit_type_output}")
        
        # Register appliance using early fail detection
        command = f"register management {cm_ip} {cm_port}"
        logger.info(f"\n➜ Executing: {command}")
        logger.info("⌛ This can take several minutes (up to 10 minutes)...")
        
        try:
            # Use special method that detects "Fail:" early
            output, fail_detected = client.execute_command_with_early_fail_detection(
                command,
                fail_pattern="Fail:",
                timeout=timeout
            )
            logger.info(f"Command output:\n{output}")
            
            # If "Fail:" was detected, disconnect and check unit type after delay
            if fail_detected:
                logger.warning(f"⚠ Registration returned 'Fail:' - disconnecting and waiting {registration_check_delay} seconds before checking status...")
                client.disconnect()
                
                # Wait before checking status
                logger.info(f"⏳ Waiting {registration_check_delay} seconds...")
                time.sleep(registration_check_delay)
                
                # Reconnect and check status
                logger.info("➜ Reconnecting to check registration status...")
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
                    logger.error("Failed to reconnect to appliance")
                    return False
                
                logger.info("\n➜ Checking unit type after 'Fail:' response...")
                unit_type_output = client.execute_command("show unit type")
                logger.info(f"Unit type:\n{unit_type_output}")
                
                client.disconnect()
                
                # Check if appliance is Managed
                if "Managed" in unit_type_output or "managed" in unit_type_output.lower():
                    logger.info("=" * 80)
                    logger.info("✓ Appliance is Managed - registration successful despite 'Fail:' message")
                    logger.info("=" * 80)
                    return True
                else:
                    logger.error("✗ Appliance is not Managed - registration failed")
                    return False
            
            # Normal success path
            # Check unit type after registration
            logger.info("\n➜ Checking unit type after registration...")
            unit_type_output = client.execute_command("show unit type")
            logger.info(f"Unit type:\n{unit_type_output}")
            
            client.disconnect()
            
            # Verify success by checking if appliance is Managed
            if "Managed" in unit_type_output or "managed" in unit_type_output.lower():
                logger.info("=" * 80)
                logger.info("✓ Appliance registered successfully (Managed)")
                logger.info("=" * 80)
                return True
            elif "unit_type" in output.lower() or "registered" in output.lower():
                logger.info("=" * 80)
                logger.info("✓ Appliance registered successfully")
                logger.info("=" * 80)
                return True
            else:
                logger.warning("Registration command completed but verification unclear")
                logger.warning("Check the output above to verify registration status")
                return True
                
        except TimeoutError:
            logger.warning("⚠ Registration command timeout")
            logger.warning(f"This sometimes happens. Waiting {registration_check_delay} seconds and checking status...")
            time.sleep(registration_check_delay)
            
            # Reconnect and check status
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
                logger.error("Failed to reconnect to appliance")
                return False
            
            logger.info("\n➜ Checking unit type after timeout...")
            unit_type_output = client.execute_command("show unit type")
            logger.info(f"Unit type:\n{unit_type_output}")
            
            client.disconnect()
            
            # Check if appliance is Managed
            if "Managed" in unit_type_output or "managed" in unit_type_output.lower():
                logger.info("=" * 80)
                logger.info("✓ Registration completed (after timeout) - appliance is Managed")
                logger.info("=" * 80)
                return True
            else:
                logger.warning("⚠ Registration timeout but appliance is not Managed")
                logger.warning("Check the output above to verify registration status")
                return False
        
    except Exception as e:
        logger.error(f"Error registering appliance: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def configure_hosts_resolving(
    config,
    logger,
    appliance_name: str,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    logger.info("=" * 80)
    logger.info(f"CONFIGURE HOSTS RESOLVING: {appliance_name}")
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
    
    # Get machines from config (loaded from machines_info.json)
    machines = config.get('machines', {})
    
    # Get all appliances from appliances.yaml
    all_appliances = appliance_loader.get_all_appliances()
    
    # Combine both sources
    total_entries = len(machines) + len(all_appliances) - 1  # -1 to exclude current appliance
    
    if not machines and not all_appliances:
        logger.warning("No machines or appliances found to configure")
        logger.info("=" * 80)
        logger.info("No hosts to configure")
        logger.info("=" * 80)
        return True
    
    logger.info(f"Found {len(machines)} Unix machines and {len(all_appliances)} appliances to configure")
    
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
        
        # Get existing hosts to avoid duplicates
        logger.info("\n➜ Checking existing hosts configuration...")
        existing_output = client.execute_command("support show hosts")
        logger.info(f"Current hosts:\n{existing_output}")
        
        # Parse existing hosts (format: "ip hostname")
        existing_hosts = set()
        for line in existing_output.split('\n'):
            line = line.strip()
            if line and not line.startswith('#') and ' ' in line:
                parts = line.split()
                if len(parts) >= 2:
                    existing_hosts.add((parts[0], parts[1]))
        
        logger.info(f"Found {len(existing_hosts)} existing host entries")
        
        # Configure hosts for each machine and appliance
        configured_count = 0
        skipped_count = 0
        
        # First, add Unix machines (raptor, ceraptos, sauropod)
        logger.info("\n➜ Configuring Unix machines:")
        for machine_name, machine_config in machines.items():
            # Use private_ip (local network IP)
            private_ip = machine_config.get('private_ip', '')
            
            if not private_ip:
                logger.warning(f"  ⊘ Skipping {machine_name}: no private_ip")
                continue
            
            # Use short name (without suffix) and add .demo.guardium domain
            short_name = machine_name  # Already shortened by config_loader
            fqdn = f"{short_name}.demo.guardium"
            
            # Check if already exists (check both FQDN and short name)
            if (private_ip, fqdn) in existing_hosts or (private_ip, short_name) in existing_hosts:
                logger.info(f"  ⊘ Skipping {short_name} ({private_ip}) - already configured")
                skipped_count += 1
                continue
            
            # Add host entry with FQDN
            command = f"support store hosts {private_ip} {fqdn}"
            logger.info(f"  ➜ Adding: {fqdn} ({private_ip})")
            output = client.execute_command(command)
            
            if debug and output:
                logger.info(f"     Output: {output}")
            
            configured_count += 1
        
        # Second, add other Guardium appliances (excluding current one)
        logger.info("\n➜ Configuring Guardium appliances:")
        for other_appliance_name, other_appliance_config in all_appliances.items():
            # Skip the current appliance
            if other_appliance_name == appliance_name:
                logger.info(f"  ⊘ Skipping {other_appliance_name} (current appliance)")
                continue
            
            # Get IP address
            appliance_ip = other_appliance_config.get('ip', '')
            if not appliance_ip:
                logger.warning(f"  ⊘ Skipping {other_appliance_name}: no IP address")
                continue
            
            # Remove suffix from appliance name (everything after last dash)
            # e.g., "cm02-suffix" -> "cm02", "coll2-suffix2" -> "coll2", "cm-02-suffix" -> "cm-02"
            short_name = other_appliance_name.rsplit('-', 1)[0] if '-' in other_appliance_name else other_appliance_name
            fqdn = f"{short_name}.demo.guardium"
            
            # Check if already exists
            if (appliance_ip, fqdn) in existing_hosts or (appliance_ip, short_name) in existing_hosts:
                logger.info(f"  ⊘ Skipping {short_name} ({appliance_ip}) - already configured")
                skipped_count += 1
                continue
            
            # Add host entry with FQDN
            command = f"support store hosts {appliance_ip} {fqdn}"
            logger.info(f"  ➜ Adding: {fqdn} ({appliance_ip})")
            output = client.execute_command(command)
            
            if debug and output:
                logger.info(f"     Output: {output}")
            
            configured_count += 1
        
        # Show final configuration
        logger.info("\n➜ Final hosts configuration:")
        final_output = client.execute_command("support show hosts")
        logger.info(f"\n{final_output}")
        
        client.disconnect()
        
        logger.info("=" * 80)
        logger.info(f"✓ Hosts resolving configured successfully")
        logger.info(f"  - Configured: {configured_count} new entries")
        logger.info(f"  - Skipped: {skipped_count} existing entries")
        logger.info("=" * 80)
        return True
        
    except Exception as e:
        logger.error(f"Error configuring hosts resolving: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def set_timezone(
    config,
    logger,
    appliance_name: str,
    timezone: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    """
    Set timezone on Guardium appliance.
    
    Args:
        config: Configuration object with machines_info
        logger: Logger instance
        appliance_name: Name of the appliance (e.g., 'cm', 'collector1')
        timezone: Timezone to set (default: Europe/Warsaw or from machines_info.json)
        user: SSH user (optional, uses config if not provided)
        password: SSH password (optional, uses config if not provided)
        prompt_regex: CLI prompt regex (optional, uses config if not provided)
        debug: Enable debug output
    
    Returns:
        bool: True if successful, False otherwise
    
    Example:
        set_timezone(config, logger, 'cm')
        set_timezone(config, logger, 'cm', timezone='America/New_York')
    """
    try:
        if not appliance_name:
            logger.error("appliance_name is required")
            return False
        
        logger.info("=" * 80)
        logger.info(f"SET TIMEZONE: {appliance_name}")
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
        
        # Determine timezone to use
        target_timezone = timezone
        if not target_timezone:
            # Try to get from machines_info.json
            machines_info = config.get('machines_info', {})
            target_timezone = machines_info.get('timezone', 'Europe/Warsaw')
        
        logger.info(f"Target timezone: {target_timezone}")
        logger.info(f"Connecting to {appliance_name} ({host})...")
        
        # Create appliance client with longer timeout for timezone change
        client = ApplianceClient(
            host=host,
            user=user,
            password=password,
            prompt_regex=prompt_regex,
            timeout=120,  # Longer timeout as timezone change restarts services
            debug=debug
        )
        
        if not client.connect():
            logger.error(f"Failed to connect to {appliance_name}")
            return False
        
        logger.info(f"✓ Connected to {appliance_name}")
        
        # Check current timezone
        logger.info("➜ Checking current timezone...")
        output = client.execute_command("show system clock all")
        
        if not output:
            logger.error("Failed to get current timezone")
            client.disconnect()
            return False
        
        # Parse current timezone (last line of output)
        current_timezone = output.strip().splitlines()[-1]
        logger.info(f"  Current timezone: {current_timezone}")
        
        # Check if timezone needs to be changed
        if current_timezone == target_timezone:
            logger.info(f"✓ Timezone already set to {target_timezone}")
            client.disconnect()
            return True
        
        # Change timezone
        logger.info(f"➜ Changing timezone from {current_timezone} to {target_timezone}...")
        command = f"store system clock timezone {target_timezone}"
        
        output = client.execute_command_with_confirmation(
            command=command,
            response="y"
        )
        
        if debug and output:
            logger.info(f"  Command output:\n{output}")
        
        # Verify new timezone (wait a moment for services to restart)
        logger.info("➜ Verifying new timezone...")
        time.sleep(1)  # Give services time to restart
        output = client.execute_command("show system clock all")
        
        if output:
            new_timezone = output.strip().splitlines()[-1]
            logger.info(f"  New timezone: {new_timezone}")
            
            if new_timezone == target_timezone:
                logger.info(f"✓ Timezone successfully changed to {target_timezone}")
            else:
                logger.warning(f"⚠ Timezone verification failed. Expected: {target_timezone}, Got: {new_timezone}")
        
        client.disconnect()
        
        logger.info("=" * 80)
        logger.info(f"✓ Timezone configuration completed")
        logger.info("=" * 80)
        return True
        
    except Exception as e:
        logger.error(f"Error setting timezone: {str(e)}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False

def configure_ntp(
    config,
    logger,
    appliance_name: str,
    ntp_servers: Optional[List[str]] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    """
    Configure NTP servers and enable time synchronization on Guardium appliance.
    
    Args:
        config: Configuration object with machines_info
        logger: Logger instance
        appliance_name: Name of the appliance (e.g., 'cm', 'collector1')
        ntp_servers: List of NTP servers (default: ['0.pool.ntp.org', '1.pool.ntp.org', '2.pool.ntp.org'])
        user: SSH user (optional, uses config if not provided)
        password: SSH password (optional, uses config if not provided)
        prompt_regex: CLI prompt regex (optional, uses config if not provided)
        debug: Enable debug output
    
    Returns:
        bool: True if successful, False otherwise
    
    Example:
        configure_ntp(config, logger, 'cm')
        configure_ntp(config, logger, 'cm', ntp_servers=['time.google.com', 'time.cloudflare.com'])
    """
    try:
        if not appliance_name:
            logger.error("appliance_name is required")
            return False
        
        logger.info("=" * 80)
        logger.info(f"CONFIGURE NTP: {appliance_name}")
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
        
        # Determine NTP servers to use
        if not ntp_servers:
            # Try to get from machines_info.json
            machines_info = config.get('machines_info', {})
            ntp_servers = machines_info.get('ntp_servers', ['0.pool.ntp.org', '1.pool.ntp.org', '2.pool.ntp.org'])
        
        # Ensure ntp_servers is a list
        if not isinstance(ntp_servers, list):
            ntp_servers = ['0.pool.ntp.org', '1.pool.ntp.org', '2.pool.ntp.org']
        
        logger.info(f"NTP servers: {' '.join(ntp_servers)}")
        logger.info(f"Connecting to {appliance_name} ({host})...")
        
        # Create appliance client with 5 minute timeout for hostname change
        client = ApplianceClient(
            host=host,
            user=user,
            password=password,
            prompt_regex=prompt_regex,
            timeout=300,  # 5 minutes for hostname change operations
            debug=debug
        )
        
        if not client.connect():
            logger.error(f"Failed to connect to {appliance_name}")
            return False
        
        logger.info(f"✓ Connected to {appliance_name}")
        
        # Configure NTP servers
        logger.info("➜ Configuring NTP servers...")
        ntp_command = f"store system time_server hostname {' '.join(ntp_servers)}"
        output = client.execute_command(ntp_command)
        
        if debug and output:
            logger.info(f"  Command output: {output}")
        
        logger.info(f"✓ NTP servers configured: {' '.join(ntp_servers)}")
        
        # Enable time synchronization
        logger.info("➜ Enabling time synchronization...")
        output = client.execute_command("store system time_server state on")
        
        if debug and output:
            logger.info(f"  Command output: {output}")
        
        logger.info("✓ Time synchronization enabled")
        
        # Verify configuration
        logger.info("➜ Verifying NTP configuration...")
        output = client.execute_command("show system time_server")
        
        if output:
            logger.info(f"  NTP configuration:\n{output}")
        
        client.disconnect()
        
        logger.info("=" * 80)
        logger.info(f"✓ NTP configuration completed")
        logger.info("=" * 80)
        return True
        
    except Exception as e:
        logger.error(f"Error configuring NTP: {str(e)}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False

def configure_system_settings(
    config,
    logger,
    appliance_name: str,
    hostname: Optional[str] = None,
    domain: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    
    try:
        if not appliance_name:
            logger.error("appliance_name is required")
            return False
        
        logger.info("=" * 80)
        logger.info(f"CONFIGURE SYSTEM SETTINGS: {appliance_name}")
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
        
        # Determine hostname - remove suffix after last dash
        if not hostname:
            # Remove everything after last dash (e.g., coll1-suffix -> coll1, coll2-suffix2 -> coll2, cm-02-suffix -> cm-02)
            hostname = appliance_name.rsplit('-', 1)[0] if '-' in appliance_name else appliance_name
            logger.info(f"Using hostname from appliance_name: {appliance_name} -> {hostname}")
        
        # Determine domain
        if not domain:
            domain = "demo.guardium"
        
        logger.info(f"Hostname: {hostname}")
        logger.info(f"Domain: {domain}")
        
        # ===== CONNECTION 1: Set hostname and domain =====
        logger.info(f"➜ Setting hostname and domain...")
        logger.info(f"Connecting to {appliance_name} ({host})...")
        
        client1 = ApplianceClient(
            host=host,
            user=user,
            password=password,
            prompt_regex=prompt_regex,
            timeout=180,  # 3 minutes
            debug=debug
        )
        
        if not client1.connect():
            logger.error(f"Failed to connect to {appliance_name}")
            return False
        
        logger.info(f"✓ Connected to {appliance_name}")
        
        # Set hostname
        logger.info(f"➜ Setting hostname to: {hostname}")
        try:
            output = client1.execute_command_with_confirmation(
                command=f"store system hostname {hostname}",
                confirmation_pattern=r"Is it a newly cloned appliance\s*\(y/n\)\?",
                response="y"
            )
            if debug and output:
                logger.info(f"  Command output: {output}")
            logger.info(f"✓ Hostname set to: {hostname}")
        except TimeoutError as e:
            logger.warning(f"Timeout during hostname change, verifying...")
            client1.disconnect()
            logger.info("Reconnecting to verify hostname...")
            
            # Reconnect to verify
            verify_client = ApplianceClient(
                host=host,
                user=user,
                password=password,
                prompt_regex=prompt_regex,
                timeout=60,
                debug=debug
            )
            
            if not verify_client.connect():
                logger.error(f"✗ Cannot reconnect to verify hostname change")
                return False
            
            try:
                verify_output = verify_client.execute_command("show system hostname")
                
                if hostname in verify_output:
                    logger.info(f"✓ Hostname successfully set to: {hostname} (verified after timeout)")
                    # Keep this connection for domain
                    client1 = verify_client
                else:
                    logger.error(f"✗ Hostname change failed: {e}")
                    verify_client.disconnect()
                    return False
            except Exception as verify_error:
                logger.error(f"✗ Cannot verify hostname change: {verify_error}")
                verify_client.disconnect()
                return False
        
        # Set domain (using same connection)
        logger.info(f"➜ Setting domain to: {domain}")
        try:
            output = client1.execute_command(f"store system domain {domain}")
            if debug and output:
                logger.info(f"  Command output: {output}")
            logger.info(f"✓ Domain set to: {domain}")
        except TimeoutError as e:
            logger.warning(f"Timeout during domain change, verifying...")
            client1.disconnect()
            logger.info("Reconnecting to verify domain...")
            
            # Reconnect to verify
            # Use configured prompt_regex (it should match the new hostname.domain format)
            if appliance_type:
                configured_prompt = appliance_loader.get_default_prompt(appliance_type, configured=True)
            else:
                configured_prompt = None
            
            if not configured_prompt:
                logger.error("Cannot determine configured prompt regex")
                return False
            
            verify_client = ApplianceClient(
                host=host,
                user=user,
                password=password,
                prompt_regex=configured_prompt,
                timeout=60,
                debug=debug
            )
            
            if not verify_client.connect():
                logger.error(f"✗ Cannot reconnect to verify domain change")
                return False
            
            try:
                verify_output = verify_client.execute_command("show system domain")
                
                if domain in verify_output:
                    logger.info(f"✓ Domain successfully set to: {domain} (verified after timeout)")
                    # Keep this connection for remaining operations
                    client1 = verify_client
                else:
                    logger.error(f"✗ Domain change failed: {e}")
                    verify_client.disconnect()
                    return False
            except Exception as verify_error:
                logger.error(f"✗ Cannot verify domain change: {verify_error}")
                verify_client.disconnect()
                return False
        
        # Continue using same connection (client1) for remaining operations
        logger.info("➜ Configuring small disk and timeouts...")
        
        # Enable small disk mode (requires "I agree" confirmation)
        logger.info("➜ Enabling small disk mode...")
        output = client1.execute_command_simple_confirmation(
            command="store system small_disk",
            confirmation_text="I agree",
            response="I agree",
            timeout=60
        )
        if debug and output:
            logger.info(f"  Command output: {output}")
        logger.info("✓ Small disk mode enabled")
        
        # Configure GUI session timeout
        logger.info("➜ Configuring GUI session timeout (9999 minutes)...")
        output = client1.execute_command("store gui session_timeout 9999")
        if debug and output:
            logger.info(f"  Command output: {output}")
        logger.info("✓ GUI session timeout set to 9999 minutes")
        
        # Configure CLI session timeout
        logger.info("➜ Configuring CLI session timeout (600 seconds)...")
        output = client1.execute_command("store timeout cli_session 600")
        if debug and output:
            logger.info(f"  Command output: {output}")
        logger.info("✓ CLI session timeout set to 600 seconds")
        
        # Restart GUI to apply changes
        logger.info("➜ Restarting GUI...")
        output = client1.execute_command_with_confirmation(
            command="restart gui",
            confirmation_pattern=r"Are you sure you want to restart GUI\s*\(y/n\)\?",
            response="y"
        )
        if debug and output:
            logger.info(f"  Command output: {output}")
        logger.info("✓ GUI restarted")
        
        client1.disconnect()
        
        logger.info("=" * 80)
        logger.info(f"✓ System settings configured successfully")
        logger.info(f"  - Hostname: {hostname}")
        logger.info(f"  - Domain: {domain}")
        logger.info(f"  - Small disk: enabled")
        logger.info(f"  - GUI timeout: 9999 min")
        logger.info(f"  - CLI timeout: 600 sec")
        logger.info("=" * 80)
        return True
        
    except Exception as e:
        logger.error(f"Error configuring system settings: {str(e)}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False

def set_product_gid(
    config,
    logger,
    appliance_name: str,
    gid: Optional[int] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    """
    Set product GID on Guardium appliance.
    
    Args:
        config: Configuration object
        logger: Logger instance
        appliance_name: Name of the appliance
        gid: GID value (optional, generates random 1000-100000 if not provided)
        user: SSH username (optional, uses default from appliance type)
        password: SSH password (optional, uses cli_pwd from custom_variables)
        prompt_regex: CLI prompt regex (optional, uses default from appliance type)
        debug: Enable debug output
    
    Returns:
        bool: True if successful, False otherwise
    
    Example:
        set_product_gid(config, logger, 'cm02', gid=234674365)
    """
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    # Generate random GID if not provided
    if gid is None:
        gid = random.randint(1000, 100000)
        logger.info(f"Generated random GID: {gid}")
    
    logger.info("=" * 80)
    logger.info(f"SET PRODUCT GID: {appliance_name}")
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
    logger.info(f"GID: {gid}")
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
        
        # Set product GID
        command = f"store product gid {gid}"
        logger.info(f"\n➜ Executing: {command}")
        output = client.execute_command(command)
        logger.info(f"Command output:\n{output}")
        
        client.disconnect()
        
        # Verify success
        # Note: execute_command filters out "ok" line, so we check for "Command ran on:" or absence of error
        if "error" in output.lower() or "failed" in output.lower():
            logger.error(f"✗ Command failed: {output}")
            return False
        elif "Command ran on:" in output or not output.strip():
            # Success: either has timestamp or empty output (ok was filtered)
            logger.info("=" * 80)
            logger.info(f"✓ Product GID set successfully to {gid}")
            logger.info("=" * 80)
            return True
        else:
            logger.warning(f"⚠ Unexpected output (assuming success): {output}")
            logger.info("=" * 80)
            logger.info(f"✓ Product GID set successfully to {gid}")
            logger.info("=" * 80)
            return True
        
    except Exception as e:
        logger.error(f"Error setting product GID: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def prepare_appliance_for_patching(
    config,
    logger,
    appliance_name: str,
    patches_source_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/patches/",
    cloudsupport_password: Optional[str] = None,
    debug: bool = True
) -> bool:
    """
    Prepare appliance for patching by copying patch files (*.sig) to /var/log/guard/patches/
    
    This function:
    1. Copies *.sig files from local patches directory to appliance's /tmp/ as cloudsupport user
    2. Uses sudo to move files from /tmp/ to /var/log/guard/patches/
    3. Sets ownership to tomcat:tomcat
    
    Args:
        config: Configuration object
        logger: Logger instance
        appliance_name: Name of the appliance
        patches_source_dir: Local directory containing patch files (default: /opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/patches/)
        cloudsupport_password: Password for cloudsupport user (optional, uses custom_variables)
        debug: Enable debug output
    
    Returns:
        True if successful, False otherwise
    """
    import os
    import glob
    import subprocess
    
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    logger.info("=" * 80)
    logger.info(f"PREPARE APPLIANCE FOR PATCHING: {appliance_name}")
    logger.info("=" * 80)
    
    # Load appliance configuration
    appliance_loader = ApplianceConfigLoader()
    appliance_config = appliance_loader.get_appliance(appliance_name)
    
    if not appliance_config:
        logger.error(f"Appliance '{appliance_name}' not found in appliances.yaml")
        available = list(appliance_loader.get_all_appliances().keys())
        logger.error(f"Available appliances: {', '.join(available)}")
        return False
    
    host = appliance_config.get('ip')
    if not host:
        logger.error(f"No IP address configured for appliance '{appliance_name}'")
        return False
    
    # Get cloudsupport password from custom_variables if not provided
    if not cloudsupport_password:
        cloudsupport_password = config.get_custom_variable('cloudsupport_pwd')
        if not cloudsupport_password:
            logger.error("cloudsupport_pwd not found in machines_info.json custom_variables")
            return False
        logger.info("Using cloudsupport password from custom_variables")
    
    # Check if patches directory exists
    if not os.path.exists(patches_source_dir):
        logger.error(f"Patches directory not found: {patches_source_dir}")
        return False
    
    # Find all *.sig files
    patch_files = glob.glob(os.path.join(patches_source_dir, "*.sig"))
    if not patch_files:
        logger.error(f"No *.sig files found in {patches_source_dir}")
        return False
    
    logger.info(f"Found {len(patch_files)} patch files to copy")
    for patch_file in patch_files:
        logger.info(f"  - {os.path.basename(patch_file)}")
    
    try:
        # Step 1: Connect as cloudsupport and copy files using SFTP
        logger.info(f"\n➜ Connecting to {host} as cloudsupport user...")
        
        import paramiko
        
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            ssh_client.connect(
                hostname=host,
                username='cloudsupport',
                password=cloudsupport_password,
                look_for_keys=False,
                allow_agent=False,
                timeout=30
            )
            
            logger.info(f"✓ Connected successfully")
            
            # Copy files using SFTP
            logger.info(f"\n➜ Copying patch files to {host}:/tmp/ using SFTP...")
            sftp = ssh_client.open_sftp()
            
            for patch_file in patch_files:
                filename = os.path.basename(patch_file)
                logger.info(f"  Copying {filename}...")
                
                try:
                    sftp.put(patch_file, f"/tmp/{filename}")
                except Exception as e:
                    logger.error(f"Failed to copy {filename}: {e}")
                    sftp.close()
                    ssh_client.close()
                    return False
            
            sftp.close()
            logger.info(f"✓ All {len(patch_files)} files copied to /tmp/")
            
            # Step 2: Use sudo to move files and set permissions
            logger.info(f"\n➜ Moving files to /var/log/guard/patches/ and setting permissions...")
            
            # Create target directory if it doesn't exist
            logger.info("  Creating /var/log/guard/patches/ directory if needed...")
            stdin, stdout, stderr = ssh_client.exec_command('sudo mkdir -p /var/log/guard/patches/')
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                error = stderr.read().decode()
                logger.error(f"Failed to create directory: {error}")
                ssh_client.close()
                return False
            
            # Move files from /tmp/ to /var/log/guard/patches/
            logger.info("  Moving files from /tmp/ to /var/log/guard/patches/...")
            stdin, stdout, stderr = ssh_client.exec_command('sudo mv /tmp/*.sig /var/log/guard/patches/')
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                error = stderr.read().decode()
                logger.error(f"Failed to move files: {error}")
                ssh_client.close()
                return False
            
            # Set ownership to tomcat:tomcat
            logger.info("  Setting ownership to tomcat:tomcat...")
            stdin, stdout, stderr = ssh_client.exec_command('sudo chown tomcat:tomcat /var/log/guard/patches/*.sig')
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                error = stderr.read().decode()
                logger.error(f"Failed to set ownership: {error}")
                ssh_client.close()
                return False
            
            # Verify files exist
            logger.info("  Verifying files...")
            stdin, stdout, stderr = ssh_client.exec_command('sudo ls -la /var/log/guard/patches/*.sig')
            output = stdout.read().decode()
            logger.info(f"Files in /var/log/guard/patches/:\n{output}")
            
            ssh_client.close()
            
            logger.info("=" * 80)
            logger.info(f"✓ Appliance {appliance_name} prepared for patching successfully")
            logger.info("=" * 80)
            return True
            
        except Exception as e:
            logger.error(f"SSH/SFTP error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            ssh_client.close()
            return False
    except Exception as e:
        logger.error(f"Error preparing appliance for patching: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

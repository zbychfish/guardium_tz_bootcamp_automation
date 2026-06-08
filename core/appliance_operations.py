#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Appliance Operations - Reusable functions for Guardium appliance operations
"""

import time
import random
import re
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

def _get_appliance_connection_params(
    config,
    logger,
    appliance_name: str,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Helper function to get appliance connection parameters.
    Reduces code duplication across appliance operation functions.
    
    Returns:
        Dict with keys: appliance_config, host, user, password, prompt_regex, appliance_type
        or None if validation fails
    """
    if not appliance_name:
        logger.error("appliance_name is required")
        return None
    
    appliance_loader = ApplianceConfigLoader()
    appliance_config = appliance_loader.get_appliance(appliance_name)
    
    if not appliance_config:
        logger.error(f"Appliance '{appliance_name}' not found in appliances.yaml")
        available = list(appliance_loader.get_all_appliances().keys())
        logger.error(f"Available appliances: {', '.join(available)}")
        return None
    
    appliance_type = appliance_config.get('type')
    host = appliance_config.get('ip')
    
    if not host:
        logger.error(f"No IP address configured for appliance '{appliance_name}'")
        return None
    
    # Get user from config if not provided
    if not user:
        user = appliance_loader.get_default_user(appliance_type) if appliance_type else "cli"
    
    # Validate user is not None
    if not user:
        logger.error(f"No user configured for appliance '{appliance_name}' (type: {appliance_type})")
        return None
    
    # Get password from custom_variables if not provided
    if not password:
        password = config.get_custom_variable('cli_pwd')
        if password:
            logger.info("Using password from custom_variables (cli_pwd)")
    
    if not password:
        logger.error("Password not provided and cli_pwd not found in custom_variables")
        return None
    
    # Get prompt regex from config if not provided
    if not prompt_regex and appliance_type:
        prompt_regex = appliance_loader.get_default_prompt(appliance_type, configured=False)
    
    if not prompt_regex:
        logger.error(f"No prompt_regex provided and no default found for type '{appliance_type}'")
        return None
    
    return {
        'appliance_config': appliance_config,
        'host': host,
        'user': user,
        'password': password,
        'prompt_regex': prompt_regex,
        'appliance_type': appliance_type
    }

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
    max_retries: int = 60,
    mysql_busy_retries: int = 5,
    mysql_busy_wait: int = 60
) -> bool:
    """
    Restart a Guardium appliance with MySQL busy check and retry logic.
    
    Args:
        mysql_busy_retries: Number of times to retry if MySQL is busy (default: 5)
        mysql_busy_wait: Seconds to wait between MySQL busy retries (default: 60)
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
    
    # Retry loop for MySQL busy condition
    for mysql_attempt in range(1, mysql_busy_retries + 1):
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
            if mysql_attempt > 1:
                logger.info(f"\n➜ Retry {mysql_attempt}/{mysql_busy_retries}: restart system")
            else:
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
                if mysql_attempt < mysql_busy_retries:
                    logger.warning(f"✗ Restart rejected - MySQL is busy updating the database (attempt {mysql_attempt}/{mysql_busy_retries})")
                    logger.warning(f"Waiting {mysql_busy_wait}s before retry...")
                    time.sleep(mysql_busy_wait)
                    continue  # Retry
                else:
                    logger.error(f"✗ Restart rejected - MySQL is busy after {mysql_busy_retries} attempts")
                    logger.error("Please wait for MySQL to finish updating and try again later")
                    return False
            else:
                logger.error(f"✗ Unexpected result: {result}")
                return False
            
        except Exception as e:
            logger.error(f"Error restarting appliance: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    # Should not reach here, but just in case
    logger.error("✗ Restart failed after all retry attempts")
    return False

def configure_aggr_settings(
    config,
    logger,
    appliance_name: str,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    """
    Configure aggregation settings on Guardium appliance:
    - store run_cleanup_orphans_daily off (all appliances)
    - store purge_age_period 0 (only on CM appliances, with confirmation)
    
    Args:
        config: Configuration object
        logger: Logger instance
        appliance_name: Name of the appliance
        user: SSH username (optional, uses default from appliance type)
        password: SSH password (optional, uses cli_pwd from custom_variables)
        prompt_regex: CLI prompt regex (optional, uses default from appliance type)
        debug: Enable debug output
    
    Returns:
        bool: True if successful, False otherwise
    """
    logger.info("=" * 80)
    logger.info(f"CONFIGURE AGGREGATION SETTINGS: {appliance_name}")
    logger.info("=" * 80)
    
    # Get connection parameters using helper function
    params = _get_appliance_connection_params(config, logger, appliance_name, user, password, prompt_regex)
    if not params:
        return False
    
    host = params['host']
    user = params['user']
    password = params['password']
    prompt_regex = params['prompt_regex']
    appliance_type = params['appliance_type']
    
    # Validate required parameters (should not be None after _get_appliance_connection_params)
    if not user or not password or not prompt_regex:
        logger.error(f"Missing required connection parameters for appliance '{appliance_name}'")
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
        
        # Execute first command: store run_cleanup_orphans_daily off
        logger.info("\n➜ Executing: store run_cleanup_orphans_daily off")
        result1 = client.execute_command("store run_cleanup_orphans_daily off")
        
        if "The parameter has been changed" in result1:
            logger.info("✓ run_cleanup_orphans_daily set to off")
        else:
            logger.warning(f"Unexpected response: {result1}")
        
        # Execute second command: store purge_age_period 0 (only on CM appliances)
        if appliance_type != 'cm':
            logger.info(f"\n⊘ Skipping 'store purge_age_period 0' - only applicable to CM appliances (current type: {appliance_type})")
            client.disconnect()
            logger.info("=" * 80)
            logger.info("Store settings configured successfully")
            logger.info("=" * 80)
            return True
        
        logger.info("\n➜ Executing: store purge_age_period 0")
        logger.info("This command requires ONLY on Central Manager (CM) appliances")
        logger.info("This command requires confirmation (y/n)")
        
        # Send command
        if not client.channel:
            logger.error("Channel not available")
            return False
            
        client.channel.send(b"store purge_age_period 0\n")
        time.sleep(1)
        
        # Wait for confirmation prompt
        output = ""
        start_time = time.time()
        while time.time() - start_time < 10:
            if client.channel.recv_ready():
                chunk = client.channel.recv(4096).decode('utf-8', errors='ignore')
                output += chunk
                
                # Check if we got the confirmation prompt
                if "Are you sure you want to continue? (y/n)" in output:
                    logger.info("Received confirmation prompt, sending 'y'")
                    client.channel.send(b"y\n")
                    time.sleep(2)
                    
                    # Read remaining output
                    final_output = ""
                    final_start = time.time()
                    while time.time() - final_start < 5:
                        if client.channel.recv_ready():
                            final_chunk = client.channel.recv(4096).decode('utf-8', errors='ignore')
                            final_output += final_chunk
                        else:
                            time.sleep(0.1)
                    
                    output += final_output
                    break
            else:
                time.sleep(0.1)
        
        if client.strip_ansi_flag:
            from .appliance_client import strip_ansi
            output = strip_ansi(output)
        
        if "The purge_age period has been changed" in output:
            logger.info("✓ purge_age_period set to 0")
        else:
            logger.warning(f"Unexpected response: {output}")
        
        client.disconnect()
        
        logger.info("=" * 80)
        logger.info("Store settings configured successfully")
        logger.info("=" * 80)
        return True
        
    except Exception as e:
        logger.error(f"Error configuring store settings: {e}")
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
    logger.info("=" * 80)
    logger.info(f"SET SHARED SECRET: {appliance_name}")
    logger.info("=" * 80)
    
    # Get connection parameters using helper function
    params = _get_appliance_connection_params(config, logger, appliance_name, user, password, prompt_regex)
    if not params:
        return False
    
    host = params['host']
    user = params['user']
    password = params['password']
    prompt_regex = params['prompt_regex']
    appliance_type = params['appliance_type']
    
    # Validate required parameters (should not be None after _get_appliance_connection_params)
    if not user or not password or not prompt_regex:
        logger.error(f"Missing required connection parameters for appliance '{appliance_name}'")
        return False
    
    # Get shared secret value
    target_shared_secret = shared_secret or config.get_custom_variable('shared_secret') or "guardium"
    if shared_secret:
        logger.info("Using provided shared_secret")
    elif config.get_custom_variable('shared_secret'):
        logger.info("Using shared_secret from custom_variables")
    else:
        logger.info("Using default shared_secret: guardium")
    
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
        command = f"store system shared secret {target_shared_secret}"
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

def configure_system_settings_consolidated(
    config,
    logger,
    appliance_name: str,
    hostname: Optional[str] = None,
    domain: Optional[str] = None,
    ip_address: Optional[str] = None,
    prefix: str = "/24",
    timezone: Optional[str] = None,
    ntp_servers: Optional[List[str]] = None,
    configure_hosts: bool = True,
    gid: Optional[int] = None,
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
        logger.info(f"CONFIGURE SYSTEM SETTINGS (CONSOLIDATED): {appliance_name}")
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
            hostname = appliance_name.rsplit('-', 1)[0] if '-' in appliance_name else appliance_name
            logger.info(f"Using hostname from appliance_name: {appliance_name} -> {hostname}")
        
        # Determine domain
        if not domain:
            domain = "demo.guardium"
        
        # Use IP from appliances.yaml if not provided
        if not ip_address:
            ip_address = host
            logger.info(f"Using IP address from appliances.yaml: {ip_address}")
        
        # Determine timezone to use
        target_timezone = timezone
        if not target_timezone:
            machines_info = config.get('machines_info', {})
            target_timezone = machines_info.get('timezone', 'Europe/Warsaw')
        
        # Determine NTP servers to use
        if not ntp_servers:
            machines_info = config.get('machines_info', {})
            ntp_servers = machines_info.get('ntp_servers', ['0.pool.ntp.org', '1.pool.ntp.org', '2.pool.ntp.org'])
        
        if not isinstance(ntp_servers, list):
            ntp_servers = ['0.pool.ntp.org', '1.pool.ntp.org', '2.pool.ntp.org']
        
        logger.info(f"Configuration parameters:")
        logger.info(f"  - Hostname: {hostname}")
        logger.info(f"  - Domain: {domain}")
        logger.info(f"  - IP: {ip_address}{prefix}")
        logger.info(f"  - Timezone: {target_timezone}")
        logger.info(f"  - NTP servers: {' '.join(ntp_servers)}")
        logger.info(f"  - Configure hosts: {configure_hosts}")
        
        # ===== SINGLE CONNECTION FOR ALL OPERATIONS =====
        logger.info(f"\n➜ Connecting to {appliance_name} ({host})...")
        
        client = ApplianceClient(
            host=host,
            user=user,
            password=password,
            prompt_regex=prompt_regex,
            timeout=300,  # 5 minutes for all operations
            debug=debug
        )
        
        if not client.connect():
            logger.error(f"Failed to connect to {appliance_name}")
            return False
        
        logger.info(f"✓ Connected to {appliance_name}")
        
        # ===== OPERATION 1: Set hostname and domain =====
        logger.info(f"\n{'='*60}")
        logger.info("OPERATION 1: Configure hostname and domain")
        logger.info(f"{'='*60}")
        
        logger.info(f"➜ Setting hostname to: {hostname}")
        try:
            output = client.execute_command_with_confirmation(
                command=f"store system hostname {hostname}",
                confirmation_pattern=r"Is it a newly cloned appliance\s*\(y/n\)\?",
                response="y"
            )
            if debug and output:
                logger.info(f"  Command output: {output}")
            logger.info(f"✓ Hostname set to: {hostname}")
        except TimeoutError as e:
            logger.warning(f"Timeout during hostname change, continuing...")
        
        logger.info(f"➜ Setting domain to: {domain}")
        try:
            output = client.execute_command(f"store system domain {domain}")
            if debug and output:
                logger.info(f"  Command output: {output}")
            logger.info(f"✓ Domain set to: {domain}")
        except TimeoutError as e:
            logger.warning(f"Timeout during domain change, continuing...")
        
        logger.info("➜ Configuring small disk and timeouts...")
        output = client.execute_command_simple_confirmation(
            command="store system small_disk",
            confirmation_text="I agree",
            response="I agree",
            timeout=60
        )
        if debug and output:
            logger.info(f"  Command output: {output}")
        logger.info("✓ Small disk mode enabled")
        
        logger.info("➜ Configuring GUI session timeout (9999 minutes)...")
        output = client.execute_command("store gui session_timeout 9999")
        if debug and output:
            logger.info(f"  Command output: {output}")
        logger.info("✓ GUI session timeout set to 9999 minutes")
        
        logger.info("➜ Configuring CLI session timeout (600 seconds)...")
        output = client.execute_command("store timeout cli_session 600")
        if debug and output:
            logger.info(f"  Command output: {output}")
        logger.info("✓ CLI session timeout set to 600 seconds")
        
        logger.info("➜ Restarting GUI...")
        output = client.execute_command_with_confirmation(
            command="restart gui",
            confirmation_pattern=r"Are you sure you want to restart GUI\s*\(y/n\)\?",
            response="y"
        )
        if debug and output:
            logger.info(f"  Command output: {output}")
        logger.info("✓ GUI restarted")
        
        # ===== OPERATION 2: Configure network IP =====
        logger.info(f"\n{'='*60}")
        logger.info("OPERATION 2: Configure network IP")
        logger.info(f"{'='*60}")
        
        logger.info(f"➜ Setting IP: {ip_address}{prefix}")
        command = f"store network interface ip {ip_address}{prefix}"
        output = client.execute_command(command)
        if debug and output:
            logger.info(f"  Command output: {output}")
        
        if "This change will take effect after the next network restart" in output or "ok" in output:
            logger.info(f"✓ Network IP set to: {ip_address}{prefix}")
        else:
            logger.warning(f"⚠ Network IP configuration may have failed")
        
        # ===== OPERATION 3: Set timezone =====
        logger.info(f"\n{'='*60}")
        logger.info("OPERATION 3: Configure timezone")
        logger.info(f"{'='*60}")
        
        logger.info(f"➜ Setting timezone to: {target_timezone}")
        command = f"store system clock timezone {target_timezone}"
        output = client.execute_command_with_confirmation(
            command=command,
            response="y"
        )
        if debug and output:
            logger.info(f"  Command output: {output}")
        logger.info(f"✓ Timezone set to: {target_timezone}")
        
        # ===== OPERATION 4: Configure NTP =====
        logger.info(f"\n{'='*60}")
        logger.info("OPERATION 4: Configure NTP")
        logger.info(f"{'='*60}")
        
        logger.info(f"➜ Configuring NTP servers: {' '.join(ntp_servers)}")
        ntp_command = f"store system time_server hostname {' '.join(ntp_servers)}"
        output = client.execute_command(ntp_command)
        if debug and output:
            logger.info(f"  Command output: {output}")
        logger.info(f"✓ NTP servers configured")
        
        logger.info("➜ Enabling time synchronization...")
        output = client.execute_command("store system time_server state on")
        if debug and output:
            logger.info(f"  Command output: {output}")
        logger.info("✓ Time synchronization enabled")
        
        # Track operation number
        operation_num = 5
        
        # ===== OPERATION 5: Configure hosts resolving =====
        if configure_hosts:
            logger.info(f"\n{'='*60}")
            logger.info(f"OPERATION {operation_num}: Configure hosts resolving")
            logger.info(f"{'='*60}")
            
            # Get machines from config
            machines = config.get('machines', {})
            all_appliances = appliance_loader.get_all_appliances()
            
            if machines or all_appliances:
                logger.info(f"Found {len(machines)} Unix machines and {len(all_appliances)} appliances")
                
                # Get existing hosts
                logger.info("➜ Checking existing hosts...")
                existing_output = client.execute_command("support show hosts")
                existing_hosts = set()
                for line in existing_output.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('#') and ' ' in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            existing_hosts.add((parts[0], parts[1]))
                
                logger.info(f"Found {len(existing_hosts)} existing host entries")
                
                configured_count = 0
                skipped_count = 0
                
                # Add Unix machines
                logger.info("➜ Configuring Unix machines:")
                for machine_name, machine_config in machines.items():
                    private_ip = machine_config.get('private_ip', '')
                    if not private_ip:
                        continue
                    
                    short_name = machine_name
                    fqdn = f"{short_name}.demo.guardium"
                    
                    if (private_ip, fqdn) in existing_hosts or (private_ip, short_name) in existing_hosts:
                        skipped_count += 1
                        continue
                    
                    command = f"support store hosts {private_ip} {fqdn}"
                    output = client.execute_command(command)
                    configured_count += 1
                    logger.info(f"  ✓ Added: {fqdn} ({private_ip})")
                
                # Add other appliances
                logger.info("➜ Configuring Guardium appliances:")
                for other_name, other_config in all_appliances.items():
                    if other_name == appliance_name:
                        continue
                    
                    other_ip = other_config.get('ip', '')
                    if not other_ip:
                        continue
                    
                    other_hostname = other_name.rsplit('-', 1)[0] if '-' in other_name else other_name
                    other_fqdn = f"{other_hostname}.demo.guardium"
                    
                    if (other_ip, other_fqdn) in existing_hosts or (other_ip, other_hostname) in existing_hosts:
                        skipped_count += 1
                        continue
                    
                    command = f"support store hosts {other_ip} {other_fqdn}"
                    output = client.execute_command(command)
                    configured_count += 1
                    logger.info(f"  ✓ Added: {other_fqdn} ({other_ip})")
                
                logger.info(f"✓ Hosts configuration complete: {configured_count} added, {skipped_count} skipped")
            else:
                logger.info("⊘ No machines or appliances to configure")
            operation_num += 1
        else:
            logger.info(f"\n⊘ Skipping OPERATION {operation_num}: hosts configuration (configure_hosts=False)")
            operation_num += 1
        
        # ===== OPERATION 6: Set product GID (ALWAYS) =====
        logger.info(f"\n{'='*60}")
        logger.info(f"OPERATION {operation_num}: Set product GID")
        logger.info(f"{'='*60}")
        
        target_gid = gid
        if target_gid is None:
            # Generate random GID
            target_gid = random.randint(1000, 100000)
            logger.info(f"Generated random GID: {target_gid}")
        
        command = f"store product gid {target_gid}"
        logger.info(f"➜ Setting product GID to: {target_gid}")
        output = client.execute_command(command)
        if debug and output:
            logger.info(f"  Command output: {output}")
        logger.info(f"✓ Product GID set to: {target_gid}")
        operation_num += 1
        
        # Disconnect
        client.disconnect()
        
        logger.info("\n" + "=" * 80)
        logger.info(f"✓ ALL OPERATIONS COMPLETED SUCCESSFULLY")
        logger.info(f"  1. System settings: hostname={hostname}, domain={domain}")
        logger.info(f"  2. Network IP: {ip_address}{prefix}")
        logger.info(f"  3. Timezone: {target_timezone}")
        logger.info(f"  4. NTP: {' '.join(ntp_servers)}")
        logger.info(f"  5. Hosts: {'configured' if configure_hosts else 'skipped'}")
        logger.info(f"  6. Product GID: {target_gid}")
        logger.info("=" * 80)
        return True
        
    except Exception as e:
        logger.error(f"Error in consolidated configuration: {str(e)}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False

def reset_cli_password(
    config,
    logger,
    appliance_name: str,
    cloudsupport_password: Optional[str] = None,
    cli_password: Optional[str] = None,
    debug: bool = True
) -> bool:
    
    logger.info("=" * 80)
    logger.info(f"RESET CLI PASSWORD: {appliance_name}")
    logger.info("=" * 80)
    
    # Validate appliance exists and get host
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
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
    
    # Get passwords from custom_variables if not provided
    if not cloudsupport_password:
        cloudsupport_password = config.get_custom_variable('cloudsupport_pwd')
        if not cloudsupport_password:
            logger.error("cloudsupport_pwd not found in custom_variables")
            return False
        logger.info("Using cloudsupport password from custom_variables")
    
    if not cli_password:
        cli_password = config.get_custom_variable('cli_pwd')
        if not cli_password:
            logger.error("cli_pwd not found in custom_variables")
            return False
        logger.info("Using CLI password from custom_variables")
    
    try:
        import paramiko
        
        logger.info(f"Connecting to {host} as cloudsupport user...")
        
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        ssh_client.connect(
            hostname=host,
            username='cloudsupport',
            password=cloudsupport_password,
            look_for_keys=False,
            allow_agent=False,
            timeout=30
        )
        
        logger.info(f"Connected to {host}")
        
        command = f"echo 'cli:{cli_password}' | sudo chpasswd"
        logger.info(f"Executing: echo 'cli:***' | sudo chpasswd")
        
        stdin, stdout, stderr = ssh_client.exec_command(command, timeout=30)
        exit_code = stdout.channel.recv_exit_status()
        
        stdout_text = stdout.read().decode('utf-8').strip()
        stderr_text = stderr.read().decode('utf-8').strip()
        
        if debug and stdout_text:
            logger.info(f"STDOUT: {stdout_text}")
        if stderr_text:
            logger.warning(f"STDERR: {stderr_text}")
        
        ssh_client.close()
        
        if exit_code == 0:
            logger.info(f"✓ CLI password reset successfully on {appliance_name}")
            return True
        else:
            logger.error(f"✗ Failed to reset CLI password on {appliance_name} (exit code: {exit_code})")
            return False
            
    except Exception as e:
        logger.error(f"✗ Exception while resetting CLI password on {appliance_name}: {e}")
        if debug:
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
    Prepare appliance for patching by copying patch files (*.sig) to /var/IBM/Guardium/log/patches/
    
    This function:
    1. Copies *.sig files from local patches directory to appliance's /tmp/ as cloudsupport user
    2. Uses sudo to move files from /tmp/ to /var/IBM/Guardium/log/patches/
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
    
    appliance_type = appliance_config.get('type')
    host = appliance_config.get('ip')
    if not host:
        logger.error(f"No IP address configured for appliance '{appliance_name}'")
        return False
    
    # Get prompt regex for CLI user
    cli_prompt_regex = appliance_loader.get_default_prompt(appliance_type, configured=True) if appliance_type else None
    if not cli_prompt_regex:
        cli_prompt_regex = r'[\w-]+(\.demo\.guardium)?> '
    
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
        # Get raptor IP from machines_info.json
        raptor_ip = config.get_machine_ip('raptor', use_private=True)
        if not raptor_ip:
            logger.error("Could not find raptor IP in machines_info.json")
            return False
        
        # Get root password for raptor from custom_variables
        raptor_root_password = config.get_custom_variable('pwd')
        if not raptor_root_password:
            logger.error("pwd not found in machines_info.json custom_variables")
            return False
        
        # Get SSH port from config.yaml
        ssh_port = config.config.get('ssh', {}).get('port', 22)
        
        logger.info(f"Raptor IP: {raptor_ip}, SSH port: {ssh_port}")
        
        # Step 1: Connect as cloudsupport and pull files from raptor using SCP
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
            
            # Copy files from raptor to appliance /tmp/ using SCP (pull from appliance side)
            logger.info(f"\n➜ Copying patch files from raptor:{patches_source_dir} to {host}:/tmp/...")
            
            # Try to use sshpass first, if not available use expect-like approach
            logger.info("  Checking if sshpass is available...")
            stdin, stdout, stderr = ssh_client.exec_command('which sshpass')
            sshpass_available = stdout.channel.recv_exit_status() == 0
            
            for patch_file in patch_files:
                filename = os.path.basename(patch_file)
                logger.info(f"  Copying {filename}...")
                
                if sshpass_available:
                    # Use sshpass if available
                    scp_command = f"sshpass -p '{raptor_root_password}' scp -P {ssh_port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@{raptor_ip}:{patch_file} /tmp/{filename}"
                    stdin, stdout, stderr = ssh_client.exec_command(scp_command)
                    exit_status = stdout.channel.recv_exit_status()
                    
                    if exit_status != 0:
                        error = stderr.read().decode()
                        logger.error(f"Failed to copy {filename}: {error}")
                        ssh_client.close()
                        return False
                else:
                    # Use expect-like approach with invoke_shell
                    logger.info("  Using interactive SCP (sshpass not available)...")
                    channel = ssh_client.invoke_shell()
                    time.sleep(0.5)
                    
                    # Clear initial output
                    if channel.recv_ready():
                        channel.recv(65535)
                    
                    # Send SCP command
                    scp_cmd = f"scp -P {ssh_port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@{raptor_ip}:{patch_file} /tmp/{filename}\n"
                    channel.send(scp_cmd.encode())
                    
                    # Wait for password prompt
                    output = ""
                    timeout = time.time() + 30
                    while time.time() < timeout:
                        if channel.recv_ready():
                            chunk = channel.recv(4096).decode(errors='ignore')
                            output += chunk
                            if "password:" in output.lower():
                                # Send password
                                channel.send(f"{raptor_root_password}\n".encode())
                                break
                        time.sleep(0.1)
                    
                    # Wait for completion
                    time.sleep(2)
                    final_output = ""
                    while channel.recv_ready():
                        final_output += channel.recv(4096).decode(errors='ignore')
                    
                    channel.close()
                    
                    # Check if file was copied
                    stdin, stdout, stderr = ssh_client.exec_command(f"test -f /tmp/{filename} && echo 'OK'")
                    result = stdout.read().decode().strip()
                    
                    if result != "OK":
                        logger.error(f"Failed to copy {filename}")
                        logger.error(f"SCP output: {output + final_output}")
                        ssh_client.close()
                        return False
            
            logger.info(f"✓ All {len(patch_files)} files copied to /tmp/")
            
            # Step 2: Use sudo to move files and set permissions
            logger.info(f"\n➜ Moving files to /var/IBM/Guardium/log/patches/ and setting permissions...")
            
            # Create target directory if it doesn't exist
            logger.info("  Creating /var/IBM/Guardium/log/patches/ directory if needed...")
            stdin, stdout, stderr = ssh_client.exec_command('sudo mkdir -p /var/IBM/Guardium/log/patches/')
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                error = stderr.read().decode()
                logger.error(f"Failed to create directory: {error}")
                ssh_client.close()
                return False
            
            # Move files from /tmp/ to /var/IBM/Guardium/log/patches/
            logger.info("  Moving files from /tmp/ to /var/IBM/Guardium/log/patches/...")
            stdin, stdout, stderr = ssh_client.exec_command('sudo mv /tmp/*.sig /var/IBM/Guardium/log/patches/')
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                error = stderr.read().decode()
                logger.error(f"Failed to move files: {error}")
                ssh_client.close()
                return False
            
            # Set ownership to tomcat:tomcat
            logger.info("  Setting ownership to tomcat:tomcat...")
            stdin, stdout, stderr = ssh_client.exec_command('sudo chown tomcat:tomcat /var/IBM/Guardium/log/patches/*.sig')
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                error = stderr.read().decode()
                logger.error(f"Failed to set ownership: {error}")
                ssh_client.close()
                return False
            
            # Verify files exist
            logger.info("  Verifying files...")
            stdin, stdout, stderr = ssh_client.exec_command('sudo ls -la /var/IBM/Guardium/log/patches/*.sig')
            output = stdout.read().decode()
            logger.info(f"Files in /var/IBM/Guardium/log/patches/:\n{output}")
            
            ssh_client.close()
            
            # Step 3: Register patches using CLI user
            logger.info(f"\n➜ Registering patches on appliance as CLI user...")
            
            # Get CLI password from custom_variables
            cli_password = config.get_custom_variable('cli_pwd')
            if not cli_password:
                logger.error("cli_pwd not found in machines_info.json custom_variables")
                return False
            
            # Connect as CLI user to register patches
            cli_client = ApplianceClient(
                host=host,
                user='cli',
                password=cli_password,
                prompt_regex=cli_prompt_regex,
                initial_pattern=None,
                timeout=60,
                strip_ansi=True,
                debug=debug
            )
            
            if not cli_client.connect():
                logger.error("Failed to connect to appliance as CLI user")
                return False
            
            # Execute show system patch available to register patches
            logger.info("  Executing: show system patch available")
            patch_output = cli_client.execute_command("show system patch available")
            logger.info(f"Available patches:\n{patch_output}")
            
            cli_client.disconnect()
            
            logger.info("=" * 80)
            logger.info(f"✓ Appliance {appliance_name} prepared for patching successfully")
            logger.info(f"✓ Patches registered and available for installation")
            logger.info("=" * 80)
            return True
            
        except Exception as e:
            logger.error(f"SSH/SFTP error: {e}")
            if debug:
                import traceback
                logger.error(traceback.format_exc())
            logger.error("=" * 80)
            return False
    
    except Exception as e:
        logger.error(f"✗ Failed to prepare appliance for patching: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        logger.error("=" * 80)
        return False

def copy_files_to_appliance(
    config,
    logger,
    appliance_name: str,
    source_dir: str,
    file_pattern: str,
    target_dir: str,
    owner: str = "tomcat:tomcat",
    cloudsupport_password: Optional[str] = None,
    debug: bool = False
) -> bool:
    """
    Copy files from raptor to appliance using SCP.
    
    This is a generic function that:
    1. Connects to appliance as cloudsupport user
    2. Uses SCP to pull files from raptor to /tmp/ on appliance
    3. Uses sudo to move files to target directory
    4. Sets ownership
    
    Args:
        config: Configuration object
        logger: Logger instance
        appliance_name: Name of the appliance
        source_dir: Source directory on raptor (e.g., /opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/patches/)
        file_pattern: File pattern to copy (e.g., "*.sig", "*.gim")
        target_dir: Target directory on appliance (e.g., /var/IBM/Guardium/log/patches/)
        owner: Owner:group for files (default: tomcat:tomcat)
        cloudsupport_password: Password for cloudsupport user (optional, uses custom_variables)
        debug: Enable debug output
    
    Returns:
        True if successful, False otherwise
    """
    import os
    import glob
    import time
    import paramiko
    
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    logger.info("=" * 80)
    logger.info(f"COPY FILES TO APPLIANCE: {appliance_name}")
    logger.info("=" * 80)
    
    # Load appliance configuration
    from core.appliance_config_loader import ApplianceConfigLoader
    appliance_loader = ApplianceConfigLoader()
    appliance_config = appliance_loader.get_appliance(appliance_name)
    
    if not appliance_config:
        logger.error(f"Appliance '{appliance_name}' not found in appliances.yaml")
        return False
    
    host = appliance_config.get('ip')
    if not host:
        logger.error(f"No IP address configured for appliance '{appliance_name}'")
        return False
    
    # Get cloudsupport password
    if not cloudsupport_password:
        cloudsupport_password = config.get_custom_variable('cloudsupport_pwd')
        if not cloudsupport_password:
            logger.error("cloudsupport_pwd not found in custom_variables")
            return False
    
    # Check if source directory exists
    if not os.path.exists(source_dir):
        logger.error(f"Source directory not found: {source_dir}")
        return False
    
    # Find files matching pattern
    files_to_copy = glob.glob(os.path.join(source_dir, file_pattern))
    if not files_to_copy:
        logger.error(f"No files matching '{file_pattern}' found in {source_dir}")
        return False
    
    logger.info(f"Found {len(files_to_copy)} file(s) to copy:")
    for file_path in files_to_copy:
        logger.info(f"  - {os.path.basename(file_path)}")
    
    try:
        # Get raptor IP
        raptor_ip = config.get_machine_ip('raptor', use_private=True)
        if not raptor_ip:
            logger.error("Could not find raptor IP in machines_info.json")
            return False
        
        # Get root password for raptor
        raptor_root_password = config.get_custom_variable('pwd')
        if not raptor_root_password:
            logger.error("pwd not found in custom_variables")
            return False
        
        # Get SSH port
        ssh_port = config.config.get('ssh', {}).get('port', 22)
        
        logger.info(f"Raptor IP: {raptor_ip}, SSH port: {ssh_port}")
        logger.info(f"Target appliance: {host}")
        
        # Connect as cloudsupport
        logger.info(f"\n➜ Connecting to {host} as cloudsupport user...")
        
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        ssh_client.connect(
            hostname=host,
            username='cloudsupport',
            password=cloudsupport_password,
            look_for_keys=False,
            allow_agent=False,
            timeout=30
        )
        
        logger.info(f"✓ Connected successfully")
        
        # Copy files from raptor to appliance /tmp/
        logger.info(f"\n➜ Copying files from raptor:{source_dir} to {host}:/tmp/...")
        
        # Check if sshpass is available
        stdin, stdout, stderr = ssh_client.exec_command('which sshpass')
        sshpass_available = stdout.channel.recv_exit_status() == 0
        
        for file_path in files_to_copy:
            filename = os.path.basename(file_path)
            logger.info(f"  Copying {filename}...")
            
            if sshpass_available:
                # Use sshpass
                scp_command = f"sshpass -p '{raptor_root_password}' scp -P {ssh_port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@{raptor_ip}:{file_path} /tmp/{filename}"
                stdin, stdout, stderr = ssh_client.exec_command(scp_command)
                exit_status = stdout.channel.recv_exit_status()
                
                if exit_status != 0:
                    error = stderr.read().decode()
                    logger.error(f"Failed to copy {filename}: {error}")
                    ssh_client.close()
                    return False
            else:
                # Use interactive SCP
                logger.info("  Using interactive SCP (sshpass not available)...")
                channel = ssh_client.invoke_shell()
                time.sleep(0.5)
                
                if channel.recv_ready():
                    channel.recv(65535)
                
                scp_cmd = f"scp -P {ssh_port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@{raptor_ip}:{file_path} /tmp/{filename}\n"
                channel.send(scp_cmd.encode())
                
                # Wait for password prompt
                output = ""
                timeout_time = time.time() + 30
                while time.time() < timeout_time:
                    if channel.recv_ready():
                        chunk = channel.recv(4096).decode(errors='ignore')
                        output += chunk
                        if "password:" in output.lower():
                            channel.send(f"{raptor_root_password}\n".encode())
                            break
                    time.sleep(0.1)
                
                time.sleep(2)
                while channel.recv_ready():
                    channel.recv(4096)
                
                channel.close()
                
                # Verify file was copied
                stdin, stdout, stderr = ssh_client.exec_command(f"test -f /tmp/{filename} && echo 'OK'")
                result = stdout.read().decode().strip()
                
                if result != "OK":
                    logger.error(f"Failed to copy {filename}")
                    ssh_client.close()
                    return False
        
        logger.info(f"✓ All {len(files_to_copy)} file(s) copied to /tmp/")
        
        # Move files to target directory
        logger.info(f"\n➜ Moving files to {target_dir} and setting permissions...")
        
        # Create target directory
        logger.info(f"  Creating {target_dir} directory if needed...")
        stdin, stdout, stderr = ssh_client.exec_command(f'sudo mkdir -p {target_dir}')
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            error = stderr.read().decode()
            logger.error(f"Failed to create directory: {error}")
            ssh_client.close()
            return False
        
        # Move files
        logger.info(f"  Moving files from /tmp/ to {target_dir}...")
        stdin, stdout, stderr = ssh_client.exec_command(f'sudo mv /tmp/{file_pattern} {target_dir}')
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            error = stderr.read().decode()
            logger.error(f"Failed to move files: {error}")
            ssh_client.close()
            return False
        
        # Set ownership
        logger.info(f"  Setting ownership to {owner}...")
        stdin, stdout, stderr = ssh_client.exec_command(f'sudo chown {owner} {target_dir}/{file_pattern}')
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            error = stderr.read().decode()
            logger.error(f"Failed to set ownership: {error}")
            ssh_client.close()
            return False
        
        # Verify files
        logger.info("  Verifying files...")
        stdin, stdout, stderr = ssh_client.exec_command(f'sudo ls -la {target_dir}/{file_pattern}')
        output = stdout.read().decode()
        logger.info(f"Files in {target_dir}:\n{output}")
        
        ssh_client.close()
        
        logger.info(f"\n✓ Files copied successfully to {appliance_name}")
        logger.info("=" * 80)
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to copy files: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        logger.error("=" * 80)
        return False

def get_patch_installation_order(
    config,
    logger,
    appliance_name: str,
    patch_order_file: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/patches/patch_order.txt",
    user: Optional[str] = None,
    password: Optional[str] = None,
    debug: bool = True
) -> Optional[str]:
    
    import os
    
    logger.info("=" * 80)
    logger.info(f"GET PATCH INSTALLATION ORDER")
    logger.info("=" * 80)
    
    if not os.path.exists(patch_order_file):
        logger.error(f"Patch order file not found: {patch_order_file}")
        return None
    
    logger.info(f"➜ Reading patch order from: {patch_order_file}")
    try:
        with open(patch_order_file, 'r') as f:
            patch_order = [line.strip() for line in f if line.strip()]
        
        logger.info(f"Desired installation order ({len(patch_order)} patches):")
        for i, patch_name in enumerate(patch_order, 1):
            logger.info(f"  {i}. {patch_name}")
    except Exception as e:
        logger.error(f"Failed to read patch order file: {e}")
        return None
    
    if not patch_order:
        logger.error("No patches found in patch_order.txt")
        return None
    
    sorted_patches = sorted(patch_order)
    
    logger.info(f"\nAlphabetically sorted (CM order) ({len(sorted_patches)} patches):")
    for i, patch_name in enumerate(sorted_patches, 1):
        logger.info(f"  Position {i}: {patch_name}")
    
    logger.info("\n➜ Mapping desired order to CM positions...")
    patch_positions = []
    
    for patch_spec in patch_order:
        try:
            position = sorted_patches.index(patch_spec) + 1
            patch_positions.append(str(position))
            logger.info(f"  {patch_spec} → position {position}")
        except ValueError:
            logger.warning(f"  {patch_spec} → NOT FOUND in sorted list!")
    
    if not patch_positions:
        logger.error("No patches mapped from patch_order.txt")
        return None
    
    patch_selection = ','.join(patch_positions)
    
    logger.info("=" * 80)
    logger.info(f"✓ Patch installation order: {patch_selection}")
    logger.info("=" * 80)
    
    return patch_selection

def install_patch_on_appliance(
    config,
    logger,
    appliance_name: str,
    patch_selection: str,
    reinstall_answer: str = "y",
    user: Optional[str] = None,
    password: Optional[str] = None,
    debug: bool = True
) -> bool:
    """
    Install patches on a Guardium appliance using interactive CLI.
    
    This function:
    1. Connects to appliance as CLI user
    2. Executes 'store system patch install sys'
    3. Responds to patch selection prompt with patch_selection
    4. Responds to reinstall prompt with reinstall_answer
    5. Waits for command completion
    
    Args:
        config: Configuration object
        logger: Logger instance
        appliance_name: Name of the appliance
        patch_selection: Comma-separated patch positions (e.g., "2,1,3" or "1-3")
        reinstall_answer: Answer to reinstall question ("y" or "n", default: "y")
        user: SSH username (optional, uses 'cli' by default)
        password: SSH password (optional, uses cli_pwd from custom_variables)
        debug: Enable debug output
    
    Returns:
        True if installation started successfully, False otherwise
    """
    import socket
    
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    if not patch_selection:
        logger.error("patch_selection is required")
        return False
    
    logger.info("=" * 80)
    logger.info(f"INSTALL PATCHES: {appliance_name}")
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
    
    # Get prompt regex for CLI user
    cli_prompt_regex = appliance_loader.get_default_prompt(appliance_type, configured=True) if appliance_type else None
    if not cli_prompt_regex:
        cli_prompt_regex = r'[\w-]+(\.demo\.guardium)?> '
    
    # Get user (default to 'cli')
    if not user:
        user = 'cli'
    
    # Get password from custom_variables if not provided
    if not password:
        password = config.get_custom_variable('cli_pwd')
        if not password:
            logger.error("cli_pwd not found in machines_info.json custom_variables")
            return False
        logger.info("Using password from custom_variables (cli_pwd)")
    
    logger.info(f"Appliance: {appliance_name} ({appliance_type}) at {host}")
    logger.info(f"Patch selection: {patch_selection}")
    logger.info(f"Reinstall answer: {reinstall_answer}")
    
    try:
        # Connect to appliance
        client = ApplianceClient(
            host=host,
            user=user,
            password=password,
            prompt_regex=cli_prompt_regex,
            initial_pattern=None,
            timeout=60,
            strip_ansi=True,
            debug=debug
        )
        
        if not client.connect():
            logger.error("Failed to connect to appliance")
            return False
        
        logger.info("✓ Connected successfully")
        
        # Get the SSH channel for interactive communication
        channel = client.channel
        if not channel:
            logger.error("No SSH channel available")
            client.disconnect()
            return False
        
        channel.settimeout(0.1)
        
        # Send patch install command
        command = "store system patch install sys"
        logger.info(f"\n➜ Executing: {command}")
        logger.info("⌛ Waiting for patch selection prompt...")
        
        channel.send((command + "\r").encode())
        
        # Read output and respond to prompts
        buf = ""
        patch_selected = False
        reinstall_answered = False
        last_activity = time.time()
        
        while True:
            try:
                chunk = channel.recv(4096).decode('utf-8', errors='replace')
                if chunk:
                    buf += chunk
                    last_activity = time.time()
                    
                    if debug:
                        # Print chunk without ANSI codes for cleaner output
                        import re
                        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                        clean_chunk = ansi_escape.sub('', chunk)
                        print(clean_chunk, end='', flush=True)
                    
                    # Remove ANSI codes for pattern matching
                    import re
                    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                    buf_clean = ansi_escape.sub('', buf)
                    
                    # Check for patch selection prompt
                    if not patch_selected and ("Please choose patches" in buf_clean or "or q to quit" in buf_clean):
                        last_line = buf_clean.strip().split('\n')[-1]
                        if last_line.endswith(':'):
                            # Wait a moment to ensure prompt is complete
                            time.sleep(1.0)
                            try:
                                extra = channel.recv(4096).decode('utf-8', errors='replace')
                                if extra:
                                    buf += extra
                                    if debug:
                                        clean_extra = ansi_escape.sub('', extra)
                                        print(clean_extra, end='', flush=True)
                            except:
                                pass
                            
                            logger.info(f"\n>>> Sending patch selection: {patch_selection} <<<")
                            channel.send((patch_selection + "\r").encode())
                            patch_selected = True
                            last_activity = time.time()
                            time.sleep(0.5)
                    
                    # Check for reinstall prompt
                    if patch_selected and not reinstall_answered and "Do you really want to install again" in buf_clean:
                        if "(yes or no)?" in buf_clean:
                            # Wait a moment to ensure prompt is complete
                            time.sleep(1.0)
                            try:
                                extra = channel.recv(4096).decode('utf-8', errors='replace')
                                if extra:
                                    buf += extra
                                    if debug:
                                        clean_extra = ansi_escape.sub('', extra)
                                        print(clean_extra, end='', flush=True)
                            except:
                                pass
                            
                            logger.info(f"\n>>> Sending reinstall answer: {reinstall_answer} <<<")
                            channel.send((reinstall_answer + "\r").encode())
                            reinstall_answered = True
                            last_activity = time.time()
                            time.sleep(0.5)
                    
                    # Check if we're back at prompt (command completed)
                    if patch_selected and (cli_prompt_regex and re.search(cli_prompt_regex, buf_clean)):
                        # Wait a moment for any final output
                        time.sleep(1)
                        try:
                            while True:
                                chunk = channel.recv(4096).decode('utf-8', errors='replace')
                                if chunk:
                                    if debug:
                                        clean_chunk = ansi_escape.sub('', chunk)
                                        print(clean_chunk, end='', flush=True)
                                else:
                                    break
                        except:
                            pass
                        
                        logger.info("\n\n=== Patch installation command completed ===")
                        client.disconnect()
                        
                        logger.info("=" * 80)
                        logger.info(f"✓ Patch installation initiated on {appliance_name}")
                        logger.info("=" * 80)
                        return True
                
            except socket.timeout:
                # Timeout is normal - no data available
                # Check if too much time passed without activity
                if time.time() - last_activity > 300:  # 5 minutes without activity
                    logger.warning("\n\n⚠ No activity for 5 minutes")
                    break
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"\nUnexpected error during patch installation: {e}")
                break
            
            # Check if channel is still open
            if channel.closed:
                logger.warning("\nChannel closed unexpectedly")
                break
        
        client.disconnect()
        logger.warning("Patch installation may not have completed successfully")
        return False
        
    except Exception as e:
        logger.error(f"Error installing patches: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def monitor_patch_installation(
    config,
    logger,
    appliance_name: str,
    patch_numbers: Optional[List[str]] = None,
    check_interval: int = 60,
    max_checks: int = 60,
    user: Optional[str] = None,
    password: Optional[str] = None,
    debug: bool = False
) -> bool:
    """
    Monitor patch installation progress on an appliance.
    
    This function periodically checks 'show system patch install sys' to monitor installation progress.
    It checks each patch by number and verifies status is "DONE: Patch installation Succeeded."
    For patch 9997, WARNING is also accepted as success.
    
    Args:
        config: Configuration object
        logger: Logger instance
        appliance_name: Name of the appliance
        patch_numbers: List of patch numbers to monitor (e.g., ['9997', '1033', '223']). If None, monitors all patches.
        check_interval: Seconds between status checks (default: 60)
        max_checks: Maximum number of checks before giving up (default: 60 = 1 hour with 60s interval)
        user: SSH username (optional, uses 'cli' by default)
        password: SSH password (optional, uses cli_pwd from custom_variables)
        debug: Enable debug output
    
    Returns:
        True if all patches installed successfully, False otherwise
    """
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    logger.info("=" * 80)
    logger.info(f"MONITOR PATCH INSTALLATION: {appliance_name}")
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
    
    # Get prompt regex for CLI user
    cli_prompt_regex = appliance_loader.get_default_prompt(appliance_type, configured=True) if appliance_type else None
    if not cli_prompt_regex:
        cli_prompt_regex = r'[\w-]+(\.demo\.guardium)?> '
    
    # Get user (default to 'cli')
    if not user:
        user = 'cli'
    
    # Get password from custom_variables if not provided
    if not password:
        password = config.get_custom_variable('cli_pwd')
        if not password:
            logger.error("cli_pwd not found in machines_info.json custom_variables")
            return False
    
    logger.info(f"Appliance: {appliance_name} ({appliance_type}) at {host}")
    logger.info(f"Check interval: {check_interval} seconds")
    logger.info(f"Max checks: {max_checks} (timeout: {check_interval * max_checks} seconds)")
    
    check_count = 0
    
    while check_count < max_checks:
        check_count += 1
        logger.info(f"\n{'=' * 80}")
        logger.info(f"Check #{check_count}/{max_checks} for {appliance_name}")
        logger.info(f"{'=' * 80}")
        
        try:
            # Connect to appliance
            client = ApplianceClient(
                host=host,
                user=user,
                password=password,
                prompt_regex=cli_prompt_regex,
                initial_pattern=None,
                timeout=60,
                strip_ansi=True,
                debug=debug
            )
            
            if not client.connect():
                logger.warning(f"⚠ Failed to connect to {appliance_name} (attempt {check_count}/{max_checks})")
                logger.info(f"  Appliance may be restarting or unavailable")
                logger.info(f"  Waiting {check_interval} seconds before next check...")
                time.sleep(check_interval)
                continue
            
            # Execute show system patch install
            logger.info(f"➜ Executing: show system patch install")
            output = client.execute_command("show system patch install")
            
            client.disconnect()
            
            if not output:
                logger.warning(f"⚠ No output from 'show system patch install'")
                logger.info(f"  Waiting {check_interval} seconds before next check...")
                time.sleep(check_interval)
                continue
            
            if debug:
                logger.info(f"Patch installation status:\n{output}")
            
            # Parse output to check each patch status
            # Format: P#      Who       Description                     Request Time         Status
            #         9997    CLI       Health Check for GPU and Bundle 2026-06-03 19:13:50  DONE: Patch installation Succeeded.
            
            lines = output.split('\n')
            patch_status = {}  # {patch_number: status_line}
            
            for line in lines:
                line_stripped = line.strip()
                # Skip header and empty lines
                if not line_stripped or line_stripped.startswith('P#') or 'Request Time' in line_stripped:
                    continue
                
                # Look for lines starting with patch number
                match = re.match(r'^(\d+)\s+', line_stripped)
                if match:
                    patch_number = match.group(1)
                    patch_status[patch_number] = line_stripped
            
            # If patch_numbers not specified, monitor all patches found
            if not patch_numbers:
                patch_numbers_to_check = list(patch_status.keys())
            else:
                patch_numbers_to_check = patch_numbers
            
            if not patch_numbers_to_check:
                logger.warning("⚠ No patches found to monitor")
                logger.info(f"  Waiting {check_interval} seconds before next check...")
                time.sleep(check_interval)
                continue
            
            # Check status of each patch
            patches_in_progress = 0
            patches_completed = 0
            patches_failed = 0
            patches_with_warning = 0
            
            logger.info(f"\n📊 Checking status of {len(patch_numbers_to_check)} patch(es):")
            
            for patch_num in patch_numbers_to_check:
                if patch_num not in patch_status:
                    logger.warning(f"  ⚠ Patch {patch_num}: NOT FOUND in output")
                    patches_failed += 1
                    continue
                
                status_line = patch_status[patch_num]
                
                # Check for success: "DONE: Patch installation Succeeded."
                if "DONE: Patch installation Succeeded" in status_line:
                    logger.info(f"  ✓ Patch {patch_num}: Succeeded")
                    patches_completed += 1
                # Special case for patch 9997: WARNING is acceptable
                elif patch_num == "9997" and "WARNING:" in status_line:
                    logger.warning(f"  ⚠ Patch {patch_num}: Completed with WARNING (acceptable for 9997)")
                    # Extract warning message
                    warning_match = re.search(r'WARNING:\s*(.+)', status_line)
                    if warning_match:
                        warning_msg = warning_match.group(1)
                        logger.warning(f"    Warning message: {warning_msg}")
                    patches_completed += 1
                    patches_with_warning += 1
                # Check for in-progress states
                elif any(keyword in status_line for keyword in ["Preparing", "STEP:", "Executing", "Applying", "POST:"]):
                    # Extract the status message
                    status_match = re.search(r'(Preparing|STEP:|Executing|Applying|POST:)\s*(.+)', status_line)
                    if status_match:
                        status_msg = status_match.group(0)
                        logger.info(f"  ⏳ Patch {patch_num}: {status_msg}")
                    else:
                        logger.info(f"  ⏳ Patch {patch_num}: In progress")
                    patches_in_progress += 1
                # Check for failure
                elif "FAIL" in status_line.upper() or "ERROR" in status_line.upper():
                    logger.error(f"  ✗ Patch {patch_num}: FAILED")
                    logger.error(f"    Status: {status_line}")
                    patches_failed += 1
                else:
                    # Unknown status - treat as in progress
                    logger.info(f"  ? Patch {patch_num}: Unknown status")
                    logger.info(f"    Status: {status_line}")
                    patches_in_progress += 1
            
            logger.info(f"\n📊 Summary:")
            logger.info(f"  ⏳ In progress: {patches_in_progress}")
            logger.info(f"  ✓ Completed: {patches_completed}")
            if patches_with_warning > 0:
                logger.info(f"  ⚠ With warnings: {patches_with_warning}")
            logger.info(f"  ✗ Failed: {patches_failed}")
            
            # Check if installation is complete
            if patches_in_progress == 0:
                if patches_failed > 0:
                    logger.error(f"\n✗ Patch installation completed with {patches_failed} failure(s)")
                    logger.error("=" * 80)
                    return False
                else:
                    if patches_with_warning > 0:
                        logger.info(f"\n✓ All patches installed successfully ({patches_with_warning} with acceptable warnings)")
                    else:
                        logger.info(f"\n✓ All patches installed successfully!")
                    logger.info("=" * 80)
                    return True
            
            # Still patches in progress
            logger.info(f"\n⏳ {patches_in_progress} patch(es) still installing...")
            logger.info(f"  Waiting {check_interval} seconds before next check...")
            time.sleep(check_interval)
            
        except Exception as e:
            logger.warning(f"⚠ Error checking patch status (attempt {check_count}/{max_checks}): {e}")
            if debug:
                import traceback
                logger.error(traceback.format_exc())
            logger.info(f"  Waiting {check_interval} seconds before next check...")
            time.sleep(check_interval)
    
    # Max checks reached
    logger.error(f"\n✗ Maximum checks ({max_checks}) reached without completion")
    logger.error("=" * 80)
    return False

def install_and_monitor_patches(
    config,
    logger,
    appliance_name: str,
    patch_selection: str,
    reinstall_answer: str = "y",
    check_interval: int = 60,
    max_checks: int = 60,
    user: Optional[str] = None,
    password: Optional[str] = None,
    debug: bool = True
) -> bool:
    """
    Install patches on an appliance and monitor the installation progress.
    
    This is a convenience function that combines install_patch_on_appliance and monitor_patch_installation.
    
    Args:
        config: Configuration object
        logger: Logger instance
        appliance_name: Name of the appliance
        patch_selection: Comma-separated patch positions (e.g., "2,1,3")
        reinstall_answer: Answer to reinstall question ("y" or "n", default: "y")
        check_interval: Seconds between status checks (default: 60)
        max_checks: Maximum number of checks (default: 60)
        user: SSH username (optional, uses 'cli' by default)
        password: SSH password (optional, uses cli_pwd from custom_variables)
        debug: Enable debug output
    
    Returns:
        True if installation and monitoring completed successfully, False otherwise
    """
    logger.info("=" * 80)
    logger.info(f"INSTALL AND MONITOR PATCHES: {appliance_name}")
    logger.info("=" * 80)
    
    # Step 1: Get patch numbers from patch_selection
    # Map positions to patch numbers based on alphabetically sorted *.sig files
    logger.info("\n📋 Step 1: Determining patch numbers from selection...")
    
    # Define patches directory path
    patches_dir = "/opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/patches/"
    
    try:
        import os
        import glob
        
        # Get all *.sig files and sort them alphabetically
        sig_files = glob.glob(os.path.join(patches_dir, "*.sig"))
        sig_files.sort()
        
        if not sig_files:
            logger.error(f"No *.sig files found in {patches_dir}")
            return False
        
        logger.info(f"Found {len(sig_files)} patch files:")
        
        # Map positions to patch numbers
        available_patches = {}  # {position: patch_number}
        position = 0
        
        for sig_file in sig_files:
            position += 1
            filename = os.path.basename(sig_file)
            
            # Extract patch number from filename using regex p(\d+)
            match = re.search(r'p(\d+)', filename)
            if match:
                patch_number = match.group(1)
                available_patches[position] = patch_number
                logger.info(f"  Position {position}: {filename} → Patch {patch_number}")
            else:
                logger.warning(f"  Position {position}: {filename} → Could not extract patch number")
        
        if not available_patches:
            logger.error("Could not extract patch numbers from any *.sig files")
            return False
        
        # Map patch_selection positions to patch numbers
        patch_numbers = []
        positions = [p.strip() for p in patch_selection.split(',')]
        
        logger.info(f"\nMapping selected positions to patch numbers:")
        for pos_str in positions:
            try:
                pos = int(pos_str)
                if pos in available_patches:
                    patch_numbers.append(available_patches[pos])
                    logger.info(f"  Position {pos} → Patch {available_patches[pos]}")
                else:
                    logger.warning(f"  Position {pos} → NOT FOUND (valid range: 1-{len(available_patches)})")
            except ValueError:
                logger.warning(f"  Invalid position: {pos_str}")
        
        if not patch_numbers:
            logger.error("Could not determine patch numbers from selection")
            return False
        
        logger.info(f"✓ Will monitor patches: {', '.join(patch_numbers)}")
        
    except Exception as e:
        logger.error(f"Error reading patch files from {patches_dir}: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        logger.info("Will monitor all patches")
        patch_numbers = None
    
    # Step 2: Install patches
    logger.info("\n📦 Step 2: Installing patches...")
    install_success = install_patch_on_appliance(
        config=config,
        logger=logger,
        appliance_name=appliance_name,
        patch_selection=patch_selection,
        reinstall_answer=reinstall_answer,
        user=user,
        password=password,
        debug=debug
    )
    
    if not install_success:
        logger.error(f"✗ Failed to initiate patch installation on {appliance_name}")
        return False
    
    logger.info(f"\n✓ Patch installation initiated successfully")
    logger.info(f"⏳ Waiting {check_interval} seconds before starting monitoring...")
    time.sleep(check_interval)
    
    # Step 3: Monitor installation
    logger.info("\n📊 Step 3: Monitoring patch installation...")
    monitor_success = monitor_patch_installation(
        config=config,
        logger=logger,
        appliance_name=appliance_name,
        patch_numbers=patch_numbers,
        check_interval=check_interval,
        max_checks=max_checks,
        user=user,
        password=password,
        debug=False  # Less verbose during monitoring
    )
    
    if not monitor_success:
        logger.error(f"✗ Patch installation monitoring failed for {appliance_name}")
        return False
    
    logger.info("=" * 80)
    logger.info(f"✓ Patches installed and verified successfully on {appliance_name}")
    logger.info("=" * 80)
    return True

def install_gim_module(
    config,
    logger,
    appliance_name: str,
    client_ip: str,
    module: str,
    module_version: str,
    params: Optional[dict] = None,
    demo_user: str = "demo",
    demo_password: Optional[str] = None,
    monitor_installation: bool = True,
    installation_delay: int = 10,
    debug: bool = False
) -> bool:
    """
    Universal function to install GIM module on a client using Guardium REST API.
    
    This function:
    1. Authenticates to Guardium appliance
    2. Assigns GIM module to client
    3. Sets module parameters (if provided)
    4. Schedules installation
    5. Optionally monitors installation progress
    
    Args:
        config: Configuration object
        logger: Logger instance
        appliance_name: Name of Guardium appliance (CM) to connect to
        client_ip: IP address of the client where module will be installed
        module: GIM module name (e.g., "BUNDLE-STAP", "BUNDLE-ATAP")
        module_version: Module version (e.g., "12.2.2.0_r123489_")
        params: Dictionary of module parameters {param_name: param_value}
        demo_user: Demo user username (default: "demo")
        demo_password: Demo user password (optional, uses custom_variables if not provided)
        monitor_installation: Whether to monitor installation progress (default: True)
        installation_delay: Delay in seconds before monitoring (default: 10)
        debug: Enable debug output
    
    Returns:
        True if installation successful, False otherwise
    
    Example:
        # Install STAP module
        install_gim_module(
            config=config,
            logger=logger,
            appliance_name="cm01",
            client_ip="10.10.9.70",
            module="BUNDLE-STAP",
            module_version="12.2.2.0_r123489_",
            params={
                "STAP_SQLGUARD_IP": "10.10.9.219",
                "STAP_USE_TLS": "1",
                "STAP_STATISTICS": "-3",
                "STAP_CONNECTION_POOL_SIZE": "2"
            }
        )
    """
    from core.guardium_rest_api import create_guardium_api
    import time
    
    logger.info("=" * 80)
    logger.info(f"INSTALL GIM MODULE: {module}")
    logger.info("=" * 80)
    logger.info(f"Appliance: {appliance_name}")
    logger.info(f"Client IP: {client_ip}")
    logger.info(f"Module: {module}")
    logger.info(f"Version: {module_version}")
    
    # Get demo user password
    if not demo_password:
        demo_password = config.get_custom_variable('pwd')
        if demo_password:
            logger.info("Using demo password from custom_variables (pwd)")
    
    if not demo_password:
        logger.error("Demo user password is required")
        logger.error("Provide demo_password in args or set 'pwd' in custom_variables")
        return False
    
    try:
        # Create REST API client
        api = create_guardium_api(config, logger, appliance_name)
        logger.info("✓ GuardiumRestAPI client created successfully")
        
        if debug:
            logger.info(f"DEBUG: API Base URL: {api.base_url}")
        
        # Get OAuth token
        logger.info(f"\n{'=' * 80}")
        logger.info("STEP 1: OAuth Authentication")
        logger.info(f"{'=' * 80}")
        logger.info(f"➜ Authenticating as user '{demo_user}'...")
        
        if debug:
            logger.info(f"DEBUG: API Call: get_token(username='{demo_user}', password='***')")
        
        token = api.get_token(username=demo_user, password=demo_password)
        logger.info("✓ Authentication successful")
        
        if debug:
            logger.info(f"DEBUG: Access token (first 30 chars): {token[:30]}...")
        
        # Assign module to client
        logger.info(f"\n{'=' * 80}")
        logger.info("STEP 2: Assign GIM Module to Client")
        logger.info(f"{'=' * 80}")
        logger.info(f"➜ Assigning module '{module}' (version: {module_version}) to client {client_ip}...")
        
        if debug:
            logger.info(f"DEBUG: API Call: gim_client_assign(")
            logger.info(f"DEBUG:   client_ip='{client_ip}',")
            logger.info(f"DEBUG:   module='{module}',")
            logger.info(f"DEBUG:   module_version='{module_version}'")
            logger.info(f"DEBUG: )")
        
        assign_response = api.gim_client_assign(
            client_ip=client_ip,
            module=module,
            module_version=module_version
        )
        
        logger.info(f"✓ Module assigned successfully")
        if debug:
            logger.info(f"DEBUG: API Response: {assign_response}")
        
        # Set module parameters
        if params:
            logger.info(f"\n{'=' * 80}")
            logger.info(f"STEP 3: Set Module Parameters ({len(params)} parameter(s))")
            logger.info(f"{'=' * 80}")
            
            for param_name, param_value in params.items():
                logger.info(f"➜ Setting parameter: {param_name} = {param_value}")
                
                if debug:
                    logger.info(f"DEBUG: API Call: gim_client_params(")
                    logger.info(f"DEBUG:   client_ip='{client_ip}',")
                    logger.info(f"DEBUG:   param_name='{param_name}',")
                    logger.info(f"DEBUG:   param_value='{param_value}'")
                    logger.info(f"DEBUG: )")
                
                param_response = api.gim_client_params(
                    client_ip=client_ip,
                    param_name=param_name,
                    param_value=str(param_value)
                )
                
                logger.info(f"  ✓ Parameter set successfully")
                if debug:
                    logger.info(f"DEBUG:   API Response: {param_response}")
            
            logger.info(f"\n✓ All {len(params)} parameter(s) set successfully")
        else:
            logger.info(f"\n{'=' * 80}")
            logger.info("STEP 3: Set Module Parameters")
            logger.info(f"{'=' * 80}")
            logger.info("⊘ No parameters to set")
        
        # Schedule installation
        logger.info(f"\n{'=' * 80}")
        logger.info("STEP 4: Schedule Installation")
        logger.info(f"{'=' * 80}")
        logger.info(f"➜ Scheduling installation for client {client_ip}...")
        logger.info(f"  Installation time: now")
        
        if debug:
            logger.info(f"DEBUG: API Call: gim_schedule_install(")
            logger.info(f"DEBUG:   client_ip='{client_ip}',")
            logger.info(f"DEBUG:   date='now'")
            logger.info(f"DEBUG: )")
        
        schedule_response = api.gim_schedule_install(
            client_ip=client_ip,
            date="now"
        )
        
        logger.info(f"✓ Installation scheduled successfully")
        if debug:
            logger.info(f"DEBUG: API Response: {schedule_response}")
        
        # Monitor installation
        if monitor_installation:
            logger.info(f"\n➜ Waiting {installation_delay} seconds before monitoring...")
            time.sleep(installation_delay)
            
            logger.info(f"➜ Monitoring installation progress for client {client_ip}...")
            
            # Monitor until all modules are installed
            import re
            pending = ["initial"]  # Initialize to enter loop
            check_count = 0
            while pending:
                check_count += 1
                logger.info(f"\n  Check #{check_count}: Querying module status...")
                
                modules = api.gim_list_client_modules(client_ip=client_ip)
                
                if debug:
                    logger.debug(f"  Full API response: {modules}")
                
                # Check for API errors
                if "ErrorCode" in modules or "ErrorMessage" in modules:
                    error_code = modules.get("ErrorCode", "N/A")
                    error_msg = modules.get("ErrorMessage", "N/A")
                    logger.error(f"  ✗ API Error: Code={error_code}, Message={error_msg}")
                    logger.error(f"  This usually means the client IP is not registered or modules not assigned")
                    return False
                
                msg = modules.get("Message", "")
                
                if debug:
                    logger.debug(f"  Raw API response Message:\n{msg}")
                
                if not msg:
                    logger.warning(f"  ⚠ API returned empty Message field")
                    logger.warning(f"  Full response keys: {list(modules.keys())}")
                
                # Parse module entries
                entries = [
                    e.strip()
                    for e in re.split(r"#+\s*ENTRY\s+\d+\s*#+", msg)
                    if e.strip()
                ]
                
                logger.info(f"  Found {len(entries)} module entry/entries")
                
                result = []
                for entry in entries:
                    entry_str: str = str(entry)
                    def g(p: str) -> Optional[str]:
                        m = re.search(p, entry_str)
                        return m.group(1) if m else None
                    
                    module_info = {
                        "module_id": g(r"MODULE_ID:\s+(-?\d+)"),
                        "name": g(r"NAME:\s+([A-Z0-9\-]+)"),
                        "installed_version": g(r"INSTALLED_VERSION\s+([0-9][^\s]+)"),
                        "scheduled_version": g(r"SCHEDULED_VERSION\s+([0-9][^\s]+)"),
                        "state": g(r"STATE:\s+([A-Z\-]+)"),
                        "is_scheduled": g(r"IS_SCHEDULED:\s+([NY])"),
                        "schedule_time": g(r"IS_SCHEDULED:\s+[NY]\s+\(([^)]+)\)")
                    }
                    result.append(module_info)
                    
                    if debug:
                        logger.debug(f"  Module: {module_info['name']} | State: {module_info['state']} | Scheduled: {module_info['scheduled_version']}")
                
                # Check for pending installations
                pending = [m for m in result if m["state"] != "INSTALLED"]
                
                if pending:
                    logger.info(f"  ⌛ {len(pending)} module(s) still installing:")
                    for m in pending:
                        logger.info(f"    - {m['name']}: {m['state']}")
                    logger.info(f"  Waiting 30 seconds before next check...")
                    time.sleep(30)
                else:
                    logger.info("  ✓ All modules installed successfully!")
                    for m in result:
                        logger.info(f"    - {m['name']}: {m['state']} (version: {m['installed_version']})")
        
        logger.info("\n" + "=" * 80)
        logger.info(f"✓ GIM MODULE INSTALLATION COMPLETED")
        logger.info("=" * 80)
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to install GIM module: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        logger.error("=" * 80)
        return False

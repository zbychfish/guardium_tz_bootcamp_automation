#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Appliance Operations - Reusable functions for Guardium appliance operations
"""

import time
from typing import Optional, List
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
    if not machines:
        logger.warning("No machines found in config (machines_info.json may not be loaded)")
        logger.info("=" * 80)
        logger.info("No hosts to configure")
        logger.info("=" * 80)
        return True
    
    logger.info(f"Found {len(machines)} machines to configure")
    
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
        
        # Configure hosts for each machine
        configured_count = 0
        skipped_count = 0
        
        for machine_name, machine_config in machines.items():
            # Use private_ip (local network IP)
            private_ip = machine_config.get('private_ip', '')
            
            if not private_ip:
                logger.warning(f"Skipping {machine_name}: no private_ip")
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

# Made with Bob


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
        
        # Determine hostname - remove suffix after dash
        if not hostname:
            # Remove suffix after dash (e.g., coll1-suffix -> coll1, cm02-suffix -> cm02)
            import re
            hostname = re.sub(r'-suffix$', '', appliance_name)
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
                response="n"
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

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
    gim_target_dir: str = "/var/dump",
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
    
    # Create REST API client using helper function
    try:
        from core.guardium_rest_api import create_guardium_api
        
        api = create_guardium_api(config, logger, appliance_name)
        logger.info("✓ GuardiumRestAPI client created successfully")
        
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


def install_gim_on_raptor(
    config,
    logger,
    verbose: bool = False,
    gim_installer_path: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/agents/shell/guard-bundle-GIM-12.2.2.0_r123489_v12_x_1-rhel-9-linux-x86_64.gim.sh",
    install_dir: str = "/opt/guardium",
    tapip: Optional[str] = None,
    sqlguardip: Optional[str] = None,
    debug: bool = False
) -> bool:
    """
    Install GIM (Guardium Installation Manager) on raptor machine.
    
    This function executes the GIM shell installer with required parameters:
    - --dir: Installation directory (default: /opt/guardium)
    - --tapip: TAP IP address (raptor's own IP, auto-detected from machines_info if not provided)
    - --sqlguardip: SQL Guard IP address (Central Manager IP, auto-detected from appliances.yaml if not provided)
    
    Args:
        config: Configuration object
        logger: Logger instance
        verbose: Enable verbose output
        gim_installer_path: Path to GIM installer shell script
        install_dir: Installation directory (default: /opt/guardium)
        tapip: TAP IP address (optional, auto-detected from raptor machine in machines_info)
        sqlguardip: SQL Guard IP address (optional, auto-detected from Central Manager in appliances.yaml)
        debug: Enable debug output
    
    Returns:
        True if installation successful, False otherwise
    
    Example:
        install_gim_on_raptor(
            config=config,
            logger=logger,
            gim_installer_path="/opt/guardium_tz_bootcamp_automation/upload/source_files/agents/shell/guard-bundle-GIM-12.2.2.0_r123489_v12_x_1-rhel-9-linux-x86_64.gim.sh"
        )
    """
    import os
    from core.utils import run_local_command
    
    logger.info("=" * 80)
    logger.info("INSTALL GIM ON RAPTOR")
    logger.info("=" * 80)
    
    # Check if installer exists
    if not os.path.exists(gim_installer_path):
        logger.error(f"GIM installer not found: {gim_installer_path}")
        return False
    
    logger.info(f"GIM installer: {gim_installer_path}")
    
    # Install required Perl packages
    logger.info(f"\n➜ Installing required Perl packages...")
    
    try:
        dnf_command = "dnf install -y perl-File-Copy perl-Sys-Hostname"
        logger.info(f"Executing: {dnf_command}")
        dnf_result = run_local_command(
            command=dnf_command,
            shell=True,
            timeout=180,  # 3 minutes timeout for package installation
            check=True
        )
        logger.info(f"✓ Perl packages installed successfully")
        
        if debug and dnf_result.stdout:
            logger.debug(f"dnf output: {dnf_result.stdout}")
            
    except Exception as e:
        logger.error(f"✗ Failed to install Perl packages: {e}")
        logger.error("GIM installation requires perl-File-Copy and perl-Sys-Hostname")
        return False
    
    # Add execute permission to all *.sh files in shell directory
    shell_dir = os.path.dirname(gim_installer_path)
    logger.info(f"\n➜ Adding execute permission to *.sh files in {shell_dir}")
    
    try:
        chmod_command = f"chmod +x {shell_dir}/*.sh"
        chmod_result = run_local_command(
            command=chmod_command,
            shell=True,
            timeout=30,
            check=True
        )
        logger.info(f"✓ Execute permission added to shell scripts")
        
        if debug and chmod_result.stdout:
            logger.debug(f"chmod output: {chmod_result.stdout}")
            
    except Exception as e:
        logger.warning(f"⚠ Failed to add execute permission: {e}")
        logger.warning("Continuing anyway - installer might still work")
    
    # Auto-detect tapip from machines if not provided
    if not tapip:
        machines = config.get('machines', {})
        raptor_info = machines.get('raptor', {})
        tapip = raptor_info.get('private_ip')
        
        if tapip:
            logger.info(f"Auto-detected TAP IP from machines config: {tapip}")
        else:
            logger.error("TAP IP not provided and not found in machines config for raptor")
            return False
    
    # Auto-detect sqlguardip from appliances.yaml if not provided (use CM, not collector)
    if not sqlguardip:
        appliance_loader = ApplianceConfigLoader()
        cms = appliance_loader.get_appliances_by_type('cm')
        
        if cms:
            # Get first CM
            first_cm_name = list(cms.keys())[0]
            first_cm = cms[first_cm_name]
            sqlguardip = first_cm.get('ip')
            
            if sqlguardip:
                logger.info(f"Auto-detected SQL Guard IP from Central Manager ({first_cm_name}): {sqlguardip}")
            else:
                logger.error(f"Central Manager '{first_cm_name}' has no IP address configured")
                return False
        else:
            logger.error("SQL Guard IP not provided and no Central Manager found in appliances.yaml")
            return False
    
    logger.info(f"Installation parameters:")
    logger.info(f"  - Install directory: {install_dir}")
    logger.info(f"  - TAP IP: {tapip}")
    logger.info(f"  - SQL Guard IP: {sqlguardip}")
    
    # Build command string
    command = f"{gim_installer_path} -- --dir {install_dir} --tapip {tapip} --sqlguardip {sqlguardip}"
    
    logger.info(f"\n➜ Executing GIM installer...")
    logger.info(f"Command: {command}")
    
    try:
        # Run installer using core utility function
        result = run_local_command(
            command=command,
            shell=True,
            timeout=300,  # 5 minutes timeout
            check=True
        )
        
        if debug and result.stdout:
            logger.info(f"Installer output:\n{result.stdout}")
        
        if result.stderr and debug:
            logger.warning(f"Installer stderr:\n{result.stderr}")
        
        logger.info("✓ GIM installation completed successfully")
        logger.info("=" * 80)
        return True
        
    except TimeoutError:
        logger.error("✗ GIM installation timeout (exceeded 5 minutes)")
        logger.error("=" * 80)
        return False
    except Exception as e:
        logger.error(f"✗ GIM installation failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        logger.error("=" * 80)
        return False

# Made with Bob



def install_stap_on_raptor(
    config,
    logger,
    appliance_name: str,
    collector_name: str,
    verbose: bool = False,
    client_ip: Optional[str] = None,
    module_version: str = "STAP-12.2.2.0_r123489_",
    use_tls: str = "1",
    statistics: str = "-3",
    connection_pool_size: str = "2",
    demo_user: str = "demo",
    demo_password: Optional[str] = None,
    debug: bool = False
) -> bool:
    """
    Install STAP (S-TAP) module on raptor machine using GIM.
    
    This function uses the universal install_gim_module function to:
    1. Assign BUNDLE-STAP module to client
    2. Set STAP parameters (SQLGUARD_IP, USE_TLS, STATISTICS, CONNECTION_POOL_SIZE)
    3. Schedule installation
    4. Monitor installation progress
    
    Args:
        config: Configuration object
        logger: Logger instance
        appliance_name: Name of Guardium appliance (GIM server, e.g., "cm02") - REQUIRED
        collector_name: Name of collector appliance for SQLGUARD_IP (e.g., "coll2") - REQUIRED
        verbose: Enable verbose output
        client_ip: IP address of raptor (optional, auto-detected from machines config)
        module_version: STAP module version (default: "STAP-12.2.2.0_r123489_")
        use_tls: Use TLS for STAP connection (default: "1")
        statistics: STAP statistics level (default: "-3")
        connection_pool_size: STAP connection pool size (default: "2")
        demo_user: Demo user username (default: "demo")
        demo_password: Demo user password (optional, uses custom_variables if not provided)
        debug: Enable debug output
    
    Returns:
        True if installation successful, False otherwise
    
    Example:
        install_stap_on_raptor(
            config=config,
            logger=logger,
            appliance_name="cm02",
            collector_name="coll2"
        )
    """
    from core.appliance_operations import install_gim_module
    from core.appliance_config_loader import ApplianceConfigLoader
    
    logger.info("=" * 80)
    logger.info("INSTALL STAP ON RAPTOR")
    logger.info("=" * 80)
    
    # Auto-detect client_ip (raptor IP) if not provided
    if not client_ip:
        machines = config.get('machines', {})
        raptor_info = machines.get('raptor', {})
        client_ip = raptor_info.get('private_ip')
        
        if client_ip:
            logger.info(f"Auto-detected raptor IP from machines config: {client_ip}")
        else:
            logger.error("Client IP not provided and not found in machines config for raptor")
            return False
    
    # Get sqlguard_ip from collector_name
    appliance_loader = ApplianceConfigLoader()
    collector_config = appliance_loader.get_appliance(collector_name)
    
    if not collector_config:
        logger.error(f"Collector '{collector_name}' not found in appliances.yaml")
        return False
    
    sqlguard_ip = collector_config.get('ip')
    if not sqlguard_ip:
        logger.error(f"Collector '{collector_name}' has no IP address configured")
        return False
    
    logger.info(f"Using SQL Guard IP from collector '{collector_name}': {sqlguard_ip}")
    
    # Prepare STAP parameters
    stap_params = {
        "STAP_SQLGUARD_IP": sqlguard_ip,
        "STAP_USE_TLS": use_tls,
        "STAP_STATISTICS": statistics,
        "STAP_CONNECTION_POOL_SIZE": connection_pool_size
    }
    
    logger.info(f"STAP Configuration:")
    logger.info(f"  - Client IP (raptor): {client_ip}")
    logger.info(f"  - SQL Guard IP (collector): {sqlguard_ip}")
    logger.info(f"  - Use TLS: {use_tls}")
    logger.info(f"  - Statistics: {statistics}")
    logger.info(f"  - Connection Pool Size: {connection_pool_size}")
    
    # Install STAP module using universal function
    return install_gim_module(
        config=config,
        logger=logger,
        appliance_name=appliance_name,
        client_ip=client_ip,
        module="BUNDLE-STAP",
        module_version=module_version,
        params=stap_params,
        demo_user=demo_user,
        demo_password=demo_password,
        monitor_installation=True,
        installation_delay=10,
        debug=debug
    )


def debug_stap_installation(
    config,
    logger,
    appliance_name: str,
    collector_name: str,
    client_ip: Optional[str] = None,
    module_version: str = "STAP-12.2.2.0_r123489_",
    demo_user: str = "demo",
    demo_password: Optional[str] = None
) -> bool:
    """
    DEBUG function to test STAP installation step by step.
    Tests each API call individually with detailed output.
    
    Args:
        config: Configuration object
        logger: Logger instance
        appliance_name: Name of Guardium appliance (GIM server, e.g., "cm02") - REQUIRED
        collector_name: Name of collector appliance for SQLGUARD_IP (e.g., "coll2") - REQUIRED
        client_ip: IP address of raptor (optional, auto-detected from machines config)
        module_version: STAP module version
        demo_user: Demo user username
        demo_password: Demo user password (optional, uses custom_variables if not provided)
    """
    from core.guardium_rest_api import create_guardium_api
    from core.appliance_config_loader import ApplianceConfigLoader
    
    logger.info("=" * 80)
    logger.info("DEBUG: STAP INSTALLATION STEP BY STEP")
    logger.info("=" * 80)
    
    # Auto-detect client_ip
    if not client_ip:
        machines = config.get('machines', {})
        raptor_info = machines.get('raptor', {})
        client_ip = raptor_info.get('private_ip')
        logger.info(f"✓ Auto-detected client IP: {client_ip}")
    
    if not client_ip:
        logger.error("✗ Client IP is required")
        return False
    
    # Get sqlguard_ip from collector_name
    appliance_loader = ApplianceConfigLoader()
    collector_config = appliance_loader.get_appliance(collector_name)
    
    if not collector_config:
        logger.error(f"✗ Collector '{collector_name}' not found in appliances.yaml")
        return False
    
    sqlguard_ip = collector_config.get('ip')
    if not sqlguard_ip:
        logger.error(f"✗ Collector '{collector_name}' has no IP address configured")
        return False
    
    logger.info(f"✓ Using SQL Guard IP from collector '{collector_name}': {sqlguard_ip}")
    
    # Get demo password
    if not demo_password:
        demo_password = config.get_custom_variable('pwd')
        logger.info("✓ Got demo password from custom_variables")
    
    if not demo_password:
        logger.error("✗ Demo password is required")
        return False
    
    try:
        # STEP 1: Create API client
        logger.info("\n" + "=" * 80)
        logger.info("STEP 1: Create API client")
        logger.info("=" * 80)
        api = create_guardium_api(config, logger, appliance_name)
        logger.info(f"✓ API client created for appliance: {appliance_name}")
        logger.info(f"  Base URL: {api.base_url}")
        
        # STEP 2: Get token
        logger.info("\n" + "=" * 80)
        logger.info("STEP 2: Get OAuth token")
        logger.info("=" * 80)
        logger.info(f"  Username: {demo_user}")
        token = api.get_token(username=demo_user, password=demo_password)
        logger.info(f"✓ Token received: {token[:30]}...")
        
        # STEP 3: Assign module
        logger.info("\n" + "=" * 80)
        logger.info("STEP 3: Assign BUNDLE-STAP module")
        logger.info("=" * 80)
        logger.info(f"  Client IP: {client_ip}")
        logger.info(f"  Module: BUNDLE-STAP")
        logger.info(f"  Version: {module_version}")
        
        assign_response = api.gim_client_assign(
            client_ip=client_ip,
            module="BUNDLE-STAP",
            module_version=module_version
        )
        logger.info(f"✓ Module assigned")
        logger.info(f"  Response: {assign_response}")
        
        # STEP 4: Set parameters
        logger.info("\n" + "=" * 80)
        logger.info("STEP 4: Set STAP parameters")
        logger.info("=" * 80)
        
        params = {
            "STAP_SQLGUARD_IP": sqlguard_ip,
            "STAP_USE_TLS": "1",
            "STAP_STATISTICS": "-3",
            "STAP_CONNECTION_POOL_SIZE": "2"
        }
        
        for param_name, param_value in params.items():
            logger.info(f"\n  Setting: {param_name} = {param_value}")
            param_response = api.gim_client_params(
                client_ip=client_ip,
                param_name=param_name,
                param_value=str(param_value)
            )
            logger.info(f"  ✓ Response: {param_response}")
        
        # STEP 5: Schedule installation
        logger.info("\n" + "=" * 80)
        logger.info("STEP 5: Schedule installation")
        logger.info("=" * 80)
        logger.info(f"  Client IP: {client_ip}")
        logger.info(f"  Date: now")
        
        schedule_response = api.gim_schedule_install(
            client_ip=client_ip,
            date="now"
        )
        logger.info(f"✓ Installation scheduled")
        logger.info(f"  Response: {schedule_response}")
        
        # STEP 6: Check modules
        logger.info("\n" + "=" * 80)
        logger.info("STEP 6: List client modules")
        logger.info("=" * 80)
        logger.info(f"  Client IP: {client_ip}")
        
        import time
        time.sleep(5)
        
        modules_response = api.gim_list_client_modules(client_ip=client_ip)
        logger.info(f"✓ Modules list received")
        logger.info(f"  Full response: {modules_response}")
        
        if "Message" in modules_response:
            logger.info(f"\n  Message field:\n{modules_response['Message']}")
        
        logger.info("\n" + "=" * 80)
        logger.info("✓ DEBUG COMPLETED SUCCESSFULLY")
        logger.info("=" * 80)
        return True
        
    except Exception as e:
        logger.error(f"\n✗ DEBUG FAILED: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

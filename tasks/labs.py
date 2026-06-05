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


def install_stap_on_raptor(
    config,
    logger,
    verbose: bool = False,
    appliance_name: Optional[str] = None,
    collector_name: Optional[str] = None,
    client_ip: Optional[str] = None,
    module: str = "BUNDLE-STAP",
    module_version: str = "STAP-12.2.2.0_r123489_",
    use_tls: str = "1",
    statistics: str = "-3",
    connection_pool_size: str = "2",
    demo_user: str = "demo",
    demo_password: Optional[str] = None,
    debug: bool = False
) -> bool:
    
    from core.appliance_operations import install_gim_module
    from core.appliance_config_loader import ApplianceConfigLoader
    
    logger.info("=" * 80)
    logger.info("INSTALL STAP ON RAPTOR")
    logger.info("=" * 80)
    
    # Validate required parameters
    if not appliance_name:
        logger.error("appliance_name is required (GIM server, e.g., 'cm02')")
        return False
    
    if not collector_name:
        logger.error("collector_name is required (collector for SQLGUARD_IP, e.g., 'coll2')")
        return False
    
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
    
    # Install kernel-devel and kernel-headers locally before STAP installation
    logger.info("\n" + "=" * 80)
    logger.info("Installing kernel-devel and kernel-headers")
    logger.info("=" * 80)
    
    from core.utils import execute_commands
    
    commands = [
        "dnf install -y kernel-devel-$(uname -r) kernel-headers-$(uname -r)"
    ]
    
    if not execute_commands(commands, logger, verbose=True):
        logger.error("Failed to install kernel packages")
        return False
    
    logger.info("✓ Kernel packages installed successfully")
    
    # Prepare STAP parameters
    stap_params = {
        "STAP_SQLGUARD_IP": sqlguard_ip,
        "STAP_USE_TLS": use_tls,
        "STAP_STATISTIC": statistics,
        "STAP_CONNECTION_POOL_SIZE": connection_pool_size
    }
    
    logger.info(f"\n{'=' * 80}")
    logger.info("STAP Configuration:")
    logger.info(f"{'=' * 80}")
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
        module=module,
        module_version=module_version,
        params=stap_params,
        demo_user=demo_user,
        demo_password=demo_password,
        monitor_installation=True,
        installation_delay=10,
        debug=debug
    )




def enable_atap_for_postgres_on_raptor(config, logger, verbose=True, db_user="postgres",
                                       db_home="/usr", db_user_dir="/var/lib/pgsql",
                                       db_type="postgres", db_instance="postgres",
                                       db_version="16", **kwargs):
    from core.utils import execute_commands
    
    guardctl = "/opt/guardium/modules/ATAP/current/files/bin/guardctl"
    steps = [
        (f"{guardctl} --db-user={db_user} --db-home={db_home} --db-user-dir={db_user_dir} --db-type={db_type} --db-instance={db_instance} --db-version={db_version} store-conf", "store configuration"),
        (f"{guardctl} authorize-user {db_user}", "authorize user"),
        ("systemctl stop postgresql", "stop service"),
        (f"{guardctl} --db-instance={db_instance} activate", "activate ATAP"),
        ("systemctl start postgresql", "start service")
    ]
    
    for cmd, desc in steps:
        if not execute_commands([cmd], logger, verbose):
            logger.error(f"Failed to {desc}")
            return False
    
    logger.info("✓ ATAP enabled for PostgreSQL")
    return True


def correct_mysql_ie(config, logger, verbose=True, cm_appliance="cm01", collector_appliance="coll2",
                     stap_host=None, **kwargs):
    from core.guardium_rest_api import create_guardium_api
    from core.appliance_config_loader import ApplianceConfigLoader
    
    if not stap_host:
        machines = config.get('machines', {})
        raptor_info = machines.get('raptor', {})
        stap_host = raptor_info.get('private_ip')
        if not stap_host:
            logger.error("stap_host not provided and not found in machines config")
            return False
    
    appliance_loader = ApplianceConfigLoader()
    collector_config = appliance_loader.get_appliance(collector_appliance)
    if not collector_config:
        logger.error(f"Collector '{collector_appliance}' not found")
        return False
    
    api_target_host = collector_config.get('ip')
    if not api_target_host:
        logger.error(f"Collector '{collector_appliance}' has no IP")
        return False
    
    api = create_guardium_api(config, logger, cm_appliance)
    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("Password 'pwd' not found in custom_variables")
        return False
    api.get_token(username='demo', password=pwd)
    
    if verbose:
        logger.info(f"Deleting MySQL IE for {stap_host} on collector {api_target_host}")
    api.delete_inspection_engine(stap_host=stap_host, type="mysql", wait_for_response="1", api_target_host=api_target_host)
    
    ie_configs = [
        {"port_min": "3306", "port_max": "3306", "ktap_db_port": "3306", "unix_socket_marker": "mysql.sock"},
        {"port_min": "33060", "port_max": "33060", "ktap_db_port": "33060", "unix_socket_marker": "mysql.sock"},
        {"port_min": "3306", "port_max": "3306", "ktap_db_port": "3306", "unix_socket_marker": "mysqlx.sock"},
        {"port_min": "33060", "port_max": "33060", "ktap_db_port": "33060", "unix_socket_marker": "mysqlx.sock"}
    ]
    
    for i, ie_config in enumerate(ie_configs, 1):
        if verbose:
            logger.info(f"Creating MySQL IE {i}/4: port {ie_config['port_min']}, socket {ie_config['unix_socket_marker']}")
        api.create_inspection_engine(
            stap_host=stap_host,
            protocol="mysql",
            db_user="mysqld",
            db_version="8",
            client="0.0.0.0/0.0.0.0",
            proc_name="/usr/sbin/mysqld",
            db_install_dir="/var/lib/mysql",
            api_target_host=api_target_host,
            **ie_config
        )
    
    logger.info("✓ MySQL IE corrected")
    return True


def configure_ssl_for_mongo(config, logger, verbose=True, **kwargs):
    import re
    from pathlib import Path
    from core.utils import execute_commands
    
    commands = [
        "mkdir -p /var/lib/mongo/cert",
        'openssl req -x509 -newkey rsa:4096 -keyout /var/lib/mongo/cert/key.pem -out /var/lib/mongo/cert/cert.pem -sha256 -days 3650 -nodes -subj "/C=PL/ST=Lubuskie/L=Nowa Sol/O=Training/OU=Demo/CN=mongod"',
        "cat /var/lib/mongo/cert/key.pem /var/lib/mongo/cert/cert.pem > /var/lib/mongo/cert/both.pem",
        "chown -R mongod:mongod /var/lib/mongo/cert"
    ]
    
    if not execute_commands(commands, logger, verbose):
        logger.error("Failed to configure SSL certificates")
        return False
    
    conf = Path("/etc/mongod.conf")
    lines = []
    with conf.open() as f:
        for line in f:
            if re.match(r"^\s*bindIp\s*:", line):
                line = "  bindIp: 0.0.0.0  # Enter 0.0.0.0,:: to bind to all IPv4 and IPv6 addresses or, alternatively, use the net.bindIpAll setting.\n"
                lines.append("  tls:\n")
                lines.append("    mode: requireTLS\n")
                lines.append("    certificateKeyFile: /var/lib/mongo/cert/both.pem\n")
            else:
                lines.append(line)
    conf.write_text("".join(lines))
    
    if not execute_commands(["systemctl restart mongod"], logger, verbose):
        logger.error("Failed to restart mongod")
        return False
    
    logger.info("✓ SSL configured for MongoDB")
    return True

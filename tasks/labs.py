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
from core.utils import execute_local_command

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
 
    logger.info("=" * 80)
    logger.info("IMPORT GIM MODULES")
    logger.info("=" * 80)
    
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    # Load appliance configuration
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    appliance_config = appliance_loader.get_appliance(appliance_name)
    
    if not appliance_config:
        logger.error(f"Appliance '{appliance_name}' not found in machines_info.json")
        return False
    
    appliance_type = appliance_config.get('type')
    host = appliance_config.get('ip')
    
    if not host:
        logger.error(f"No IP address configured for appliance '{appliance_name}'")
        return False
    
    logger.info(f"Appliance: {appliance_name} ({appliance_type}) at {host}")
    
    # Step 1: Set executable permissions on shell files
    logger.info(f"\n{'=' * 80}")
    logger.info("STEP 1: Set executable permissions on shell files")
    logger.info(f"{'=' * 80}")
    
    shell_dir = "/opt/guardium_tz_bootcamp_automation/upload/source_files/agents/shell/"
    logger.info(f"Setting +x on files in: {shell_dir}")
    
    result = execute_local_command(f"chmod +x {shell_dir}*", logger=logger, verbose=verbose)
    
    if result['rc'] == 0:
        logger.info(f"✓ Executable permissions set on shell files")
    else:
        logger.warning(f"⚠ Failed to set executable permissions (rc={result['rc']})")
        if result['stderr']:
            logger.warning(f"Error: {result['stderr']}")
    
    # Step 2: Copy GIM files to appliance
    logger.info(f"\n{'=' * 80}")
    logger.info("STEP 2: Copy GIM files to appliance")
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
    
    # Step 3: Import GIM modules using REST API
    logger.info(f"\n{'=' * 80}")
    logger.info("STEP 3: Import GIM modules using REST API")
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
    
    # Auto-detect sqlguardip from machines_info.json if not provided (use CM, not collector)
    if not sqlguardip:
        appliance_loader = ApplianceConfigLoader(config_loader=config)
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
            logger.error("SQL Guard IP not provided and no Central Manager found in machines_info.json")
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
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    collector_config = appliance_loader.get_appliance(collector_name)
    
    if not collector_config:
        logger.error(f"Collector '{collector_name}' not found in machines_info.json")
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
    
    appliance_loader = ApplianceConfigLoader(config_loader=config)
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


def enable_atap_for_mongo(config, logger, verbose=True, **kwargs):
    from core.utils import execute_commands
    
    guardctl = "/opt/guardium/modules/ATAP/current/files/bin/guardctl"
    steps = [
        ("mv /opt/guardium/etc/guard/root/postgres.conf /opt/guardium/etc/guard", "backup postgres.conf"),
        (f"{guardctl} --db-user=mongod --db-home=/usr --db-base=/var/lib/mongo --db-type=mongodb --db-instance=mongo4 store-conf", "store configuration"),
        (f"{guardctl} authorize-user mongod", "authorize user"),
        ("systemctl stop mongod", "stop service"),
        (f"{guardctl} --db-instance=mongo4 activate", "activate ATAP"),
        ("systemctl start mongod", "start service"),
        ("mv /opt/guardium/etc/guard/postgres.conf /opt/guardium/etc/guard/root", "restore postgres.conf")
    ]
    
    for cmd, desc in steps:
        if not execute_commands([cmd], logger, verbose):
            logger.error(f"Failed to {desc}")
            return False
    
    logger.info("✓ ATAP enabled for MongoDB")
    return True


def configure_db2_exit_ie(config, logger, verbose=True, cm_appliance="cm02", collector_appliance="coll2",
                          stap_host=None, **kwargs):
    """
    Configure DB2 Exit Inspection Engine.
    Deletes existing DB2 IEs and creates new DB2 Exit IE.
    
    Args:
        config: Configuration object
        logger: Logger instance
        verbose: Enable verbose logging
        cm_appliance: Central Manager appliance name (default: cm02)
        collector_appliance: Collector appliance name (default: coll2)
        stap_host: STAP host IP (optional, auto-detected from raptor)
        
    Returns:
        True if successful, False otherwise
    """
    from core.guardium_rest_api import create_guardium_api
    from core.appliance_config_loader import ApplianceConfigLoader
    
    if not stap_host:
        machines = config.get('machines', {})
        raptor_info = machines.get('raptor', {})
        stap_host = raptor_info.get('private_ip')
        if not stap_host:
            logger.error("stap_host not provided and not found in machines config")
            return False
    
    appliance_loader = ApplianceConfigLoader(config_loader=config)
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
        logger.info(f"Deleting DB2 IE for {stap_host} on collector {api_target_host}")
    api.delete_inspection_engine(stap_host=stap_host, type="Db2", wait_for_response="1", api_target_host=api_target_host)
    
    if verbose:
        logger.info(f"Creating DB2 Exit IE for {stap_host} on collector {api_target_host}")
    api.create_inspection_engine(
        stap_host=stap_host,
        protocol="Db2 Exit",
        db_user="db2inst1",
        db_version="11",
        client="0.0.0.0/0.0.0.0",
        proc_name="/home/db2inst1/sqllib/adm/db2sysc",
        db_install_dir="/home/db2inst1",
        api_target_host=api_target_host
    )
    
    logger.info("✓ DB2 Exit IE configured")
    return True


def db2_exit_configuration(config, logger, verbose: bool = True) -> bool:
    """
    Configure DB2 exit for Guardium monitoring on raptor.
    
    Args:
        config: ConfigLoader instance
        logger: Logger instance
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    from core.utils import execute_commands
    
    if verbose:
        logger.info("=" * 80)
        logger.info("Configuring DB2 exit for Guardium monitoring")
        logger.info("=" * 80)
    
    commands = [
        "/opt/guardium/modules/ATAP/current/files/bin/guardctl authorize-user db2inst1",
        "su - db2inst1 -c 'db2stop'",
        "su - db2inst1 -c 'mkdir -p /home/db2inst1/sqllib/security64/plugin/commexit'",
        "su - db2inst1 -c 'ln -fs /usr/lib64/libguard_db2_exit_64.so /home/db2inst1/sqllib/security64/plugin/commexit/libguard_db2_exit_64.so'",
        "su - db2inst1 -c 'db2 update dbm cfg using comm_exit_list libguard_db2_exit_64'",
        "su - db2inst1 -c 'db2start'"
    ]
    
    if not execute_commands(commands, logger, verbose):
        logger.error("DB2 exit configuration failed")
        return False
    
    if verbose:
        logger.info("✓ DB2 exit configured successfully")
        logger.info("=" * 80)
    
    return True


def import_atap_definitions(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm02",
    definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
    debug: bool = True
) -> bool:
    from core.guardium_rest_api import create_guardium_api
    import os
    
    logger.info("=" * 80)
    logger.info("IMPORT ATAP LAB DEFINITIONS")
    logger.info("=" * 80)
    
    definition_files = [
        "exp_datasource_verification_atap_lab.sql"
    ]
    
    logger.info(f"CM Appliance: {cm_appliance}")
    logger.info(f"Definitions directory: {definitions_dir}")
    logger.info(f"Files to import: {', '.join(definition_files)}")
    
    try:
        api = create_guardium_api(config, logger, appliance_name=cm_appliance)
        
        demo_password = config.get_custom_variable('pwd')
        if not demo_password:
            logger.error("pwd not found in custom_variables")
            return False
        
        logger.info("Authenticating as demo user...")
        api.get_token(username='demo', password=demo_password)
        logger.info("✓ Authentication successful")
        
        for filename in definition_files:
            file_path = os.path.join(definitions_dir, filename)
            
            if not os.path.exists(file_path):
                logger.error(f"✗ File not found: {file_path}")
                return False
            
            logger.info(f"\n➜ Importing: {filename}")
            result = api.import_definitions(file_path=file_path)
            
            if debug:
                logger.info(f"  API Response: {result}")
            
            logger.info(f"✓ {filename} imported successfully")
        
        logger.info("\n" + "=" * 80)
        logger.info("✓ ATAP definitions imported successfully")
        logger.info("=" * 80)
        return True
        
    except FileNotFoundError as e:
        logger.error(f"✗ File not found: {e}")
        return False
    except Exception as e:
        logger.error(f"✗ Failed to import definitions: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False


def install_filebeat_on_sauropod(
    config,
    logger,
    verbose: bool = False,
    rpms_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/rpms",
    filebeat_pattern: str = "filebeat-*.rpm",
    debug: bool = False
) -> bool:
    from core.ssh_client import SSHClient
    import glob
    import os
    
    logger.info("=" * 80)
    logger.info("INSTALL FILEBEAT ON SAUROPOD")
    logger.info("=" * 80)
    
    machines = config.get('machines', {})
    sauropod_info = machines.get('sauropod', {})
    sauropod_ip = sauropod_info.get('private_ip')
    sauropod_password = sauropod_info.get('password')
    
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False
    
    if not sauropod_password:
        logger.error("Sauropod password not found in machines config")
        return False
    
    logger.info(f"Sauropod IP: {sauropod_ip}")
    
    filebeat_rpm_pattern = os.path.join(rpms_dir, filebeat_pattern)
    filebeat_rpms = glob.glob(filebeat_rpm_pattern)
    
    if not filebeat_rpms:
        logger.error(f"No filebeat RPM found matching pattern: {filebeat_rpm_pattern}")
        return False
    
    filebeat_rpm = filebeat_rpms[0]
    filebeat_filename = os.path.basename(filebeat_rpm)
    
    logger.info(f"Found filebeat RPM: {filebeat_filename}")
    
    ssh = SSHClient(
        host=sauropod_ip,
        username="root",
        password=sauropod_password,
        timeout=60
    )
    
    try:
        logger.info("\n➜ Connecting to sauropod...")
        if not ssh.connect():
            logger.error("Failed to connect to sauropod")
            return False
        
        logger.info("✓ Connected to sauropod")
        
        logger.info("\n➜ Creating directory /root/gn-trainings...")
        result = ssh.execute_command("mkdir -p /root/gn-trainings", print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to create directory: {result['stderr']}")
            return False
        logger.info("✓ Directory created")
        
        logger.info(f"\n➜ Uploading {filebeat_filename} to sauropod...")
        remote_rpm_path = f"/root/gn-trainings/{filebeat_filename}"
        if not ssh.upload_file(filebeat_rpm, remote_rpm_path):
            logger.error("Failed to upload filebeat RPM")
            return False
        logger.info("✓ RPM uploaded")
        
        logger.info("\n➜ Installing filebeat RPM...")
        install_cmd = f"dnf -y install {remote_rpm_path}"
        result = ssh.execute_command(install_cmd, timeout=300, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to install filebeat: {result['stderr']}")
            return False
        logger.info("✓ Filebeat installed")
        
        logger.info("\n➜ Configuring filebeat for Cassandra audit logs...")
        
        config_commands = [
            r"sed -i '/^- type: filestream/,/^[^[:space:]]/c\- type: filestream\n  id: \"cassandra\"\n  enabled: true\n  paths:\n    - /var/log/cassandra/audit/audit.log\n  exclude_lines: [\"AuditLogManager\"]\n  tags: [\"cassandra\"]\n  multiline.type: pattern\n  multiline.pattern: \"^INFO\"\n  multiline.negate: true\n  multiline.match: after' /etc/filebeat/filebeat.yml",
            r"sed -i '/^output.elasticsearch:/,/^[^[:space:]]/ { s/^/# / }' /etc/filebeat/filebeat.yml",
            r"sed -i '/^#output.logstash:/,/^[^[:space:]]/ { s/^#output\.logstash:/output.logstash:/; s|^  #hosts:.*|  hosts: [\"coll1.demo.com:5047\"]| }' /etc/filebeat/filebeat.yml"
        ]
        
        for cmd in config_commands:
            result = ssh.execute_command(cmd, print_output=verbose)
            if result['rc'] != 0:
                logger.warning(f"Configuration command failed (rc={result['rc']}): {cmd[:50]}...")
                if debug:
                    logger.debug(f"stderr: {result['stderr']}")
        
        logger.info("✓ Filebeat configured")
        
        logger.info("\n➜ Starting and enabling filebeat service...")
        result = ssh.execute_command("systemctl start filebeat", print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to start filebeat: {result['stderr']}")
            return False
        
        result = ssh.execute_command("systemctl enable filebeat", print_output=verbose)
        if result['rc'] != 0:
            logger.warning(f"Failed to enable filebeat: {result['stderr']}")
        
        logger.info("✓ Filebeat started and enabled")
        
        logger.info("\n" + "=" * 80)
        logger.info("✓ Filebeat installation completed successfully")
        logger.info("=" * 80)
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to install filebeat: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()


def deploy_etap_mysql(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False,
    **kwargs
) -> bool:
    logger.info("=" * 80)
    logger.info("DEPLOY ETAP MYSQL")
    logger.info("=" * 80)

    collector_appliance = kwargs.get('collector_appliance', 'coll1')

    raptor_info = config.get_machine("raptor")
    if not raptor_info:
        logger.error("Machine 'raptor' not found in configuration")
        return False

    raptor_ip = raptor_info.get("private_ip") or raptor_info.get("host")
    if not raptor_ip:
        logger.error("Raptor IP not found in configuration")
        return False

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    collector_config = appliance_loader.get_appliance(collector_appliance)
    if not collector_config:
        logger.error(f"Collector '{collector_appliance}' not found in configuration")
        return False

    collector_ip = collector_config.get("ip")
    if not collector_ip:
        logger.error(f"Collector '{collector_appliance}' IP not found in configuration")
        return False

    version_file = "/opt/ETAP/ca/guardium_etap_version.txt"
    etap_version = config.get_custom_variable("guardium_etap_version")
    if not etap_version and os.path.exists(version_file):
        with open(version_file, "r", encoding="utf-8") as f:
            etap_version = f.read().strip()
        if etap_version:
            logger.info(f"Loaded guardium_etap_version from {version_file}")

    if not etap_version:
        logger.error("guardium_etap_version not found in custom_variables or version file")
        return False

    token_file = "/opt/ETAP/ca/mysql_etap_token.txt"
    etap_token = config.get_custom_variable("mysql_etap_token")
    if not etap_token and os.path.exists(token_file):
        with open(token_file, "r", encoding="utf-8") as f:
            etap_token = f.read().strip()
        if etap_token:
            logger.info(f"Loaded mysql_etap_token from {token_file}")

    if not etap_token:
        logger.error("mysql_etap_token not found in custom_variables or token file")
        return False

    sshd_config = "/etc/ssh/sshd_config"
    check_command = f"python3 -c \"import pathlib, re; text = pathlib.Path('{sshd_config}').read_text(); raise SystemExit(0 if re.search(r'^\\s*Port\\s+22\\s*$', text, re.MULTILINE) else 1)\""
    add_command = f"printf '\\n# Temporary port for ETAP\\nPort 22\\n' >> {sshd_config}"
    restart_command = "systemctl restart sshd"
    clone_command = "mkdir -p /opt/ETAP && cd /opt/ETAP && if [ ! -d Guardium_External_S-TAP ]; then git clone https://github.com/IBM/Guardium_External_S-TAP.git; else echo Repository already exists; fi"

    logger.info("Checking if SSH port 22 is configured in sshd_config")
    check_result = execute_local_command(check_command, logger=logger, verbose=False)
    if check_result['rc'] != 0:
        logger.info("Port 22 not found - adding temporary SSH port 22 to sshd_config")
        add_result = execute_local_command(add_command, logger=logger, verbose=verbose)
        if add_result['rc'] != 0:
            logger.error(f"✗ Failed to add port 22 to sshd_config: {add_result['stderr']}")
            return False
    else:
        logger.info("Port 22 already present in sshd_config")

    logger.info("Restarting SSHD service")
    restart_result = execute_local_command(restart_command, logger=logger, verbose=verbose)
    if restart_result['rc'] != 0:
        logger.error(f"✗ Failed to restart SSHD: {restart_result['stderr']}")
        return False

    logger.info("Cloning Guardium External S-TAP repository")
    clone_result = execute_local_command(clone_command, logger=logger, verbose=verbose)
    if clone_result['rc'] != 0:
        logger.error(f"✗ Failed to clone Guardium External S-TAP repository: {clone_result['stderr']}")
        return False

    container_file_content = f"""[Unit]
Description=mysql-etap
Documentation=man:podman-generate-systemd(1)

[Container]
# Obraz i nazwa kontenera wyciągnięte dokładnie z ExecStart
Image=icr.io/guardium/guardium_external_s-tap:v{etap_version}
ContainerName=mysql-etap
HostName=localhost-mysql-etap

# Przekazanie limitu pamięci oraz shm-size, które było w oryginalnej komendzie
PodmanArgs=--memory=4g --shm-size=800M

# Mapowanie portu
PublishPort=63333:8888/tcp

# Zmienne środowiskowe przeniesione 1:1
Environment=STAP_CONFIG_TAP_TAP_IP=NULL
Environment=STAP_CONFIG_TAP_PRIVATE_TAP_IP=NULL
Environment=STAP_CONFIG_TAP_FORCE_SERVER_IP=0
Environment=STAP_CONFIG_PROXY_GROUP_UUID=305575f5-c47b-48b2-b3f8-67138fd36d61
Environment=STAP_CONFIG_PROXY_GROUP_MEMBER_COUNT=1
Environment=STAP_CONFIG_PROXY_NUM_WORKERS=1
Environment=STAP_CONFIG_PROXY_PROXY_PROTOCOL=0
Environment=STAP_CONFIG_PROXY_DISCONNECT_ON_INVALID_CERTIFICATE=0
Environment=STAP_CONFIG_PROXY_NOTIFY_ON_INVALID_CERTIFICATE=0
Environment=STAP_CONFIG_PROXY_DETECT_SSL_WITHIN_X_PACKETS=-1
Environment=STAP_CONFIG_DB_0_REAL_DB_PORT=3306
Environment=STAP_CONFIG_PROXY_LISTEN_PORT=8888
Environment=STAP_CONFIG_PROXY_DEBUG=0
Environment=STAP_CONFIG_PROXY_SECRET={etap_token}
Environment=STAP_CONFIG_PROXY_CSR_NAME=
Environment=STAP_CONFIG_PROXY_CSR_COUNTRY=
Environment=STAP_CONFIG_PROXY_CSR_PROVINCE=
Environment=STAP_CONFIG_PROXY_CSR_CITY=
Environment=STAP_CONFIG_PROXY_CSR_ORGANIZATION=
Environment=STAP_CONFIG_PROXY_CSR_KEYLENGTH=2048
Environment=STAP_CONFIG_DB_0_DB_TYPE=mysql
Environment=STAP_CONFIG_PARTICIPATE_IN_LOAD_BALANCING=0
Environment=STAP_CONFIG_TAP_TENANT_ID=MYSQLETAP
Environment=STAP_CONFIG_SQLGUARD_0_SQLGUARD_IP={collector_ip}
Environment=STAP_CONFIG_PROXY_DB_HOST={raptor_ip}

[Service]
Restart=always
TimeoutStopSec=70

[Install]
# Zmieniono na multi-user.target (standard dla usług systemowych root)
WantedBy=multi-user.target
"""

    container_file_path = "/etc/containers/systemd/mysql-etap.container"
    create_dir_command = "mkdir -p /etc/containers/systemd"
    write_file_command = f"cat > {container_file_path} << 'EOF'\n{container_file_content}\nEOF"

    logger.info("Creating systemd container directory")
    create_dir_result = execute_local_command(create_dir_command, logger=logger, verbose=verbose)
    if create_dir_result['rc'] != 0:
        logger.error(f"✗ Failed to create systemd container directory: {create_dir_result['stderr']}")
        return False

    logger.info(f"Creating systemd container file: {container_file_path}")
    write_file_result = execute_local_command(write_file_command, logger=logger, verbose=verbose)
    if write_file_result['rc'] != 0:
        logger.error(f"✗ Failed to create systemd container file: {write_file_result['stderr']}")
        return False

    daemon_reload_command = "systemctl daemon-reload"
    logger.info("Reloading systemd daemon")
    daemon_reload_result = execute_local_command(daemon_reload_command, logger=logger, verbose=verbose)
    if daemon_reload_result['rc'] != 0:
        logger.error(f"✗ Failed to reload systemd daemon: {daemon_reload_result['stderr']}")
        return False

    start_service_command = "systemctl start mysql-etap"
    logger.info("Starting mysql-etap service")
    start_service_result = execute_local_command(start_service_command, logger=logger, verbose=verbose)
    if start_service_result['rc'] != 0:
        logger.error(f"✗ Failed to start mysql-etap service: {start_service_result['stderr']}")
        return False

    logger.info("✓ ETAP MySQL deployed and started on raptor")
    return True


def setup_minio_on_raptor(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False
) -> bool:
    logger.info("=" * 80)
    logger.info("SETUP MINIO ON RAPTOR")
    logger.info("=" * 80)

    raptor_ip = config.get_machine_ip("raptor", use_private=True)
    if not raptor_ip:
        logger.error("Could not determine raptor IP address")
        return False

    minio_password = config.get_custom_variable("pwd")
    if not minio_password:
        logger.error("Custom variable 'pwd' not found")
        return False

    commands_before_podman = [
        "mkdir -p /home/minio/ca/{certs,private,newcerts}",
        "chmod 700 /home/minio/ca/private",
        "touch /home/minio/ca/index.txt",
        "echo 1000 > /home/minio/ca/serial",
        "mkdir -p /home/minio/certs/CAs",
        "openssl genrsa -out /home/minio/ca/private/ca.key 4096",
        'openssl req -x509 -new -nodes -key /home/minio/ca/private/ca.key -sha256 -days 3650 -subj "/CN=MinIO-Root-CA" -out /home/minio/ca/certs/ca.crt',
        "cp /home/minio/ca/certs/ca.crt /home/minio/certs/CAs/",
        "cp /home/minio/ca/certs/ca.crt /etc/pki/ca-trust/source/anchors/",
        "update-ca-trust",
        "openssl genrsa -out /home/minio/certs/private.key 4096 && chmod 600 /home/minio/certs/private.key",
        f'openssl req -new -key /home/minio/certs/private.key -out /home/minio/minio.csr -subj "/CN=minio.demo.guardium" -addext "subjectAltName=DNS:raptor.demo.guardium,IP:{raptor_ip}"',
        "openssl x509 -req -in /home/minio/minio.csr -CA /home/minio/ca/certs/ca.crt -CAkey /home/minio/ca/private/ca.key -CAcreateserial -out /home/minio/certs/public.crt -days 3600 -sha256 -copy_extensions copy",
        "dnf -y install podman",
        "mkdir -p /home/data/minio",
        "chmod 700 /home/data/minio",
        "curl -L -o /usr/local/bin/mc https://dl.min.io/client/mc/release/linux-amd64/mc",
        "chmod +x /usr/local/bin/mc",
    ]
    
    podman_run_command = f"podman run -d --name minio --restart=always -p 0.0.0.0:9000:9000 -p 0.0.0.0:9001:9001 -v /home/data/minio:/data:Z -v /home/minio/certs:/root/.minio/certs:Z -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD='{minio_password}' quay.io/minio/minio server /data --console-address ':9001'"
    
    commands_after_podman = [
        f"mc alias set myminio https://raptor.demo.guardium:9000 minioadmin '{minio_password}'",
        "mc mb myminio/guardium-ltr",
    ]

    for command in commands_before_podman:
        result = execute_local_command(command, logger=logger, verbose=verbose)
        if result["rc"] != 0:
            logger.error(f"✗ Failed command: {command}")
            logger.error(result["stderr"])
            return False
    
    logger.info("➜ Starting MinIO container...")
    result = execute_local_command(podman_run_command, logger=logger, verbose=verbose)
    if result["rc"] != 0:
        logger.error(f"✗ Failed to start MinIO container")
        logger.error(result["stderr"])
        return False
    
    import time
    logger.info("⌛ Waiting 10 seconds for MinIO to start...")
    time.sleep(10)
    
    for command in commands_after_podman:
        result = execute_local_command(command, logger=logger, verbose=verbose)
        if result["rc"] != 0:
            logger.error(f"✗ Failed command: {command}")
            logger.error(result["stderr"])
            return False

    logger.info("✓ MinIO certificates prepared and MinIO started on raptor")
    return True


def setup_raptor_to_deploy_etap(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False
) -> bool:
    """
    Setup raptor machine to deploy ETAP (External TAP).
    Installs required packages and determines the latest ETAP version.
    
    Args:
        config: ConfigLoader instance
        logger: Logger instance
        verbose: Enable verbose logging (default: False)
        debug: Enable debug mode (default: False)
        
    Returns:
        True if successful, False otherwise
    """
    import json
    import re
    from packaging.version import Version
    from core.utils import run_local_command
    
    logger.info("=" * 80)
    logger.info("SETUP RAPTOR TO DEPLOY ETAP")
    logger.info("=" * 80)
    
    # Step 1: Install required packages
    logger.info("\n➜ Installing package requirements (podman-docker, skopeo)...")
    
    try:
        dnf_command = "dnf -y install podman-docker skopeo"
        logger.info(f"Executing: {dnf_command}")
        
        result = run_local_command(
            command=dnf_command,
            shell=True,
            timeout=300,  # 5 minutes timeout for package installation
            check=True
        )
        
        logger.info("✓ Packages installed successfully")
        
        if debug and result.stdout:
            logger.debug(f"dnf output: {result.stdout}")
            
    except Exception as e:
        logger.error(f"✗ Failed to install packages: {e}")
        logger.error("ETAP setup requires podman-docker and skopeo packages")
        return False
    
    # Step 3: Determine the latest ETAP version
    logger.info("\n➜ Determining the latest ETAP version from ICR...")
    
    try:
        skopeo_command = "skopeo list-tags docker://icr.io/guardium/guardium_external_s-tap"
        logger.info(f"Executing: {skopeo_command}")
        
        result = run_local_command(
            command=skopeo_command,
            shell=True,
            timeout=120,  # 2 minutes timeout
            check=True
        )
        
        if not result.stdout:
            logger.error("✗ No output from skopeo command")
            return False
        
        # Parse JSON output
        etap_versions = json.loads(result.stdout)
        
        if debug:
            logger.debug(f"Available tags: {etap_versions.get('Tags', [])}")
        
        # Extract version numbers and find latest per minor version
        latest = {}
        tags = etap_versions.get("Tags", [])
        
        logger.info(f"Found {len(tags)} tags, analyzing versions...")
        
        for tag in tags:
            # Match version pattern: v12.2.2.0 or similar
            match = re.match(r"^v(\d+\.\d+\.\d+)", tag)
            if not match:
                continue
            
            version_str = match.group(1)
            major, minor, patch = version_str.split(".")
            key = f"{major}.{minor}"
            
            try:
                v = Version(version_str)
                if key not in latest or v > latest[key]:
                    latest[key] = v
                    if debug:
                        logger.debug(f"Updated latest for {key}: {v}")
            except Exception as e:
                if debug:
                    logger.debug(f"Failed to parse version {version_str}: {e}")
                continue
        
        if not latest:
            logger.error("✗ No valid ETAP versions found")
            return False
        
        # Get Guardium minor version from config
        guardium_minor_version = config.get_custom_variable('guardium_minor_version')
        
        if not guardium_minor_version:
            # Try to auto-detect from available versions (use latest)
            guardium_minor_version = max(latest.keys())
            logger.info(f"No guardium_minor_version in config, using latest: {guardium_minor_version}")
        
        if guardium_minor_version not in latest:
            logger.error(f"✗ No ETAP version found for Guardium {guardium_minor_version}")
            logger.error(f"Available minor versions: {', '.join(latest.keys())}")
            return False
        
        etap_version = str(latest[guardium_minor_version])
        
        logger.info(f"✓ Latest ETAP version for Guardium {guardium_minor_version}: {etap_version}")
        
        # Save to custom_variables in config
        # Note: This updates the in-memory config, not the JSON file
        config.set_custom_variable('guardium_etap_version', etap_version)
        os.makedirs("/opt/ETAP/ca", exist_ok=True)
        with open("/opt/ETAP/ca/guardium_etap_version.txt", "w", encoding="utf-8") as f:
            f.write(etap_version)
        
        logger.info(f"✓ ETAP version saved to config: {etap_version}")
        
        logger.info("\n" + "=" * 80)
        logger.info("✓ Raptor setup for ETAP deployment completed successfully")
        logger.info(f"ETAP Version: {etap_version}")
        logger.info("=" * 80)
        
        return True
        
    except json.JSONDecodeError as e:
        logger.error(f"✗ Failed to parse skopeo output: {e}")
        if debug:
            logger.debug(f"Output was: {result.stdout}")
        return False
    except Exception as e:
        logger.error(f"✗ Failed to determine ETAP version: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False


def setup_etap_certificates_mysql(
    config,
    logger,
    verbose: bool = False,
    collector_appliance: str = "coll1",
    ca_dir: str = "/opt/ETAP/ca",
    etap_alias: str = "mysql-etap",
    etap_common_name: str = "mysql-etap",
    etap_san1: str = "coll1.demo.com",
    etap_organizational_unit: str = "Demo",
    etap_organization: str = "Guardium",
    etap_locality: str = "",
    etap_state: str = "",
    etap_country: str = "PL",
    etap_email: str = "",
    etap_encryption_algorithm: str = "2",
    etap_keysize: str = "2",
    etap_san2: str = "",
    ca_common_name: str = "ETAP CA",
    ca_alias: str = "etapca",
    debug: bool = False
) -> bool:
    import os
    from core.utils import run_local_command
    from core.appliance_config_loader import ApplianceConfigLoader
    from core.appliance_client import ApplianceClient
    
    logger.info("=" * 80)
    logger.info("SETUP ETAP CERTIFICATES")
    logger.info("=" * 80)
    
    # Get collector configuration
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    collector_config = appliance_loader.get_appliance(collector_appliance)
    
    if not collector_config:
        logger.error(f"Collector '{collector_appliance}' not found in machines_info.json")
        return False
    
    collector_ip = collector_config.get('ip')
    if not collector_ip:
        logger.error(f"Collector '{collector_appliance}' has no IP address configured")
        return False
    
    logger.info(f"Collector: {collector_appliance} at {collector_ip}")
    logger.info(f"CA Directory: {ca_dir}")
    logger.info(f"ETAP Alias: {etap_alias}")
    
    # Get CLI password
    cli_password = config.get_custom_variable('cli_pwd')
    if not cli_password:
        logger.error("CLI password not found in custom_variables (cli_pwd)")
        return False
    
    # Step 1: Create CA directory
    logger.info(f"\n{'=' * 80}")
    logger.info("STEP 1: Create CA directory")
    logger.info(f"{'=' * 80}")
    
    try:
        logger.info(f"Creating directory: {ca_dir}")
        result = run_local_command(
            command=f"mkdir -p {ca_dir}",
            shell=True,
            timeout=30,
            check=True
        )
        logger.info(f"✓ CA directory created")
    except Exception as e:
        logger.error(f"✗ Failed to create CA directory: {e}")
        return False
    
    # Step 2: Create CA private key
    logger.info(f"\n{'=' * 80}")
    logger.info("STEP 2: Create CA private key")
    logger.info(f"{'=' * 80}")
    
    ca_key_path = os.path.join(ca_dir, "ca.key")
    try:
        logger.info(f"Generating CA private key: {ca_key_path}")
        result = run_local_command(
            command=f"openssl genrsa -out {ca_key_path} 2048",
            shell=True,
            timeout=60,
            check=True
        )
        logger.info(f"✓ CA private key generated")
        
        if debug and result.stdout:
            logger.debug(f"openssl output: {result.stdout}")
    except Exception as e:
        logger.error(f"✗ Failed to generate CA private key: {e}")
        return False
    
    # Step 3: Generate CA certificate
    logger.info(f"\n{'=' * 80}")
    logger.info("STEP 3: Generate CA certificate")
    logger.info(f"{'=' * 80}")
    
    ca_cert_path = os.path.join(ca_dir, "ca.pem")
    try:
        logger.info(f"Generating CA certificate: {ca_cert_path}")
        
        ca_subj_parts = [f"C={etap_country}"]
        if etap_state:
            ca_subj_parts.append(f"ST={etap_state}")
        if etap_locality:
            ca_subj_parts.append(f"L={etap_locality}")
        ca_subj_parts.append(f"O={etap_organization}")
        ca_subj_parts.append(f"OU={etap_organizational_unit}")
        ca_subj_parts.append(f"CN={ca_common_name}")
        if etap_email:
            ca_subj_parts.append(f"emailAddress={etap_email}")
        
        ca_subj = "/" + "/".join(ca_subj_parts)
        
        result = run_local_command(
            command=f'openssl req -x509 -sha256 -new -key {ca_key_path} -days 3650 -out {ca_cert_path} -subj "{ca_subj}"',
            shell=True,
            timeout=60,
            check=True
        )
        logger.info(f"✓ CA certificate generated")
        
        if debug and result.stdout:
            logger.debug(f"openssl output: {result.stdout}")
    except Exception as e:
        logger.error(f"✗ Failed to generate CA certificate: {e}")
        return False
    
    token_file = os.path.join(ca_dir, "mysql_etap_token.txt")

    # Step 4: Connect to collector and generate CSR
    logger.info(f"\n{'=' * 80}")
    logger.info("STEP 4: Generate CSR for ETAP on collector")
    logger.info(f"{'=' * 80}")
    
    csr_path = os.path.join(ca_dir, "etap.csr")
    etap_csr_id = None
    etap_token = None
    
    try:
        logger.info(f"Connecting to collector {collector_ip}...")
        
        appliance = ApplianceClient(
            host=collector_ip,
            user="cli",
            password=cli_password,
            prompt_regex=r">",
            strip_ansi=True,
            debug=debug
        )
        
        if not appliance.connect():
            logger.error("Failed to connect to collector")
            return False
        
        logger.info("✓ Connected to collector")
        
        logger.info(f"Generating CSR for alias '{etap_alias}'...")
        logger.info(f"CSR parameters: locality='{etap_locality}', state='{etap_state}', email='{etap_email}'")
        csr, token, line_above = appliance.generate_external_stap_csr(
            alias=etap_alias,
            common_name=etap_common_name,
            san1=etap_san1,
            organizational_unit=etap_organizational_unit,
            organization=etap_organization,
            country=etap_country,
            encryption_algorithm=etap_encryption_algorithm,
            keysize=etap_keysize,
            locality=etap_locality,
            state=etap_state,
            email=etap_email,
            san2=etap_san2
        )
        
        # Save CSR to file
        with open(csr_path, "w", encoding="utf-8") as f:
            f.write(csr)
        
        etap_csr_id = line_above
        etap_token = token
        config.set_custom_variable('mysql_etap_token', etap_token)
        with open(token_file, "w", encoding="utf-8") as f:
            f.write(etap_token)

        logger.info(f"✓ CSR generated and saved to {csr_path}")
        logger.info(f"  CSR ID: {etap_csr_id}")
        logger.info(f"  Deployment token: {etap_token}")
        
        appliance.disconnect()
        
    except Exception as e:
        logger.error(f"✗ Failed to generate CSR: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    
    # Step 5: Sign CSR with CA
    logger.info(f"\n{'=' * 80}")
    logger.info("STEP 5: Sign CSR with CA")
    logger.info(f"{'=' * 80}")
    
    etap_cert_path = os.path.join(ca_dir, "etap.pem")
    try:
        logger.info(f"Signing CSR...")
        result = run_local_command(
            command=f"openssl x509 -sha256 -req -days 3650 -CA {ca_cert_path} -CAkey {ca_key_path} -CAcreateserial -CAserial serial -in {csr_path} -out {etap_cert_path}",
            shell=True,
            timeout=60,
            check=True
        )
        logger.info(f"✓ CSR signed, certificate saved to {etap_cert_path}")
        
        if debug and result.stdout:
            logger.debug(f"openssl output: {result.stdout}")
    except Exception as e:
        logger.error(f"✗ Failed to sign CSR: {e}")
        return False
    
    # Step 6: Import CA certificate to collector
    logger.info(f"\n{'=' * 80}")
    logger.info("STEP 6: Import CA certificate to collector")
    logger.info(f"{'=' * 80}")
    
    try:
        logger.info(f"Connecting to collector {collector_ip}...")
        
        appliance = ApplianceClient(
            host=collector_ip,
            user="cli",
            password=cli_password,
            prompt_regex=r">",
            strip_ansi=True,
            debug=debug
        )
        
        if not appliance.connect():
            logger.error("Failed to connect to collector")
            return False
        
        logger.info("✓ Connected to collector")
        
        # Read CA certificate
        with open(ca_cert_path, "r", encoding="utf-8") as f:
            ca_cert_pem = f.read()
        
        logger.info(f"Importing CA certificate with alias '{ca_alias}'...")
        appliance.import_external_stap_ca_certificate(
            alias=ca_alias,
            ca_cert=ca_cert_pem
        )
        
        logger.info(f"✓ CA certificate imported successfully")
        
        appliance.disconnect()
        
    except Exception as e:
        logger.error(f"✗ Failed to import CA certificate: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    
    # Step 7: Import ETAP certificate to collector
    logger.info(f"\n{'=' * 80}")
    logger.info("STEP 7: Import ETAP certificate to collector")
    logger.info(f"{'=' * 80}")
    
    try:
        logger.info(f"Connecting to collector {collector_ip}...")
        
        appliance = ApplianceClient(
            host=collector_ip,
            user="cli",
            password=cli_password,
            prompt_regex=r">",
            strip_ansi=True,
            debug=debug
        )
        
        if not appliance.connect():
            logger.error("Failed to connect to collector")
            return False
        
        logger.info("✓ Connected to collector")
        
        # Read ETAP certificate
        with open(etap_cert_path, "r", encoding="utf-8") as f:
            etap_cert_pem = f.read()
        
        logger.info(f"Importing ETAP certificate...")
        appliance.import_external_stap_certificate(
            alias_line=etap_csr_id,
            stap_cert=etap_cert_pem
        )
        
        logger.info(f"✓ ETAP certificate imported successfully")
        
        appliance.disconnect()
        
    except Exception as e:
        logger.error(f"✗ Failed to import ETAP certificate: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("✓ ETAP CERTIFICATES SETUP COMPLETED SUCCESSFULLY")
    logger.info("=" * 80)
    logger.info(f"CA Directory: {ca_dir}")
    logger.info(f"CA Certificate: {ca_cert_path}")
    logger.info(f"ETAP Certificate: {etap_cert_path}")
    logger.info(f"ETAP Deployment Token: {etap_token}")
    logger.info("=" * 80)
    
    return True


def deploy_etap_for_oracle_container_on_sauropod(
    config,
    logger,
    verbose: bool = False,
    collector_appliance: str = "coll1",
    ca_dir: str = "/opt/ETAP/ca",
    etap_alias: str = "oracle-etap",
    etap_common_name: str = "oracle-etap",
    etap_san1: str = "coll1.demo.com",
    etap_organizational_unit: str = "Demo",
    etap_organization: str = "Guardium",
    etap_locality: str = "",
    etap_state: str = "",
    etap_country: str = "PL",
    etap_email: str = "",
    etap_encryption_algorithm: str = "2",
    etap_keysize: str = "2",
    etap_san2: str = "",
    ca_alias: str = "etapca",
    debug: bool = False
) -> bool:
    import os
    from core.utils import run_local_command
    from core.appliance_config_loader import ApplianceConfigLoader
    from core.appliance_client import ApplianceClient
    from core import execute_local_command

    logger.info("=" * 80)
    logger.info("CREATE ORACLE CONTAINER ETAP CERTIFICATE")
    logger.info("=" * 80)

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    collector_config = appliance_loader.get_appliance(collector_appliance)
    if not collector_config:
        logger.error(f"Collector '{collector_appliance}' not found in machines_info.json")
        return False

    collector_ip = collector_config.get('ip')
    if not collector_ip:
        logger.error(f"Collector '{collector_appliance}' has no IP address configured")
        return False

    cli_password = config.get_custom_variable('cli_pwd')
    if not cli_password:
        logger.error("CLI password not found in custom_variables (cli_pwd)")
        return False

    ca_key_path = os.path.join(ca_dir, "ca.key")
    ca_cert_path = os.path.join(ca_dir, "ca.pem")
    csr_path = os.path.join(ca_dir, "etap2.csr")
    etap_cert_path = os.path.join(ca_dir, "etap2.pem")
    token_file = os.path.join(ca_dir, "oracle_etap_token.txt")

    logger.info(f"Collector: {collector_appliance} at {collector_ip}")
    logger.info(f"CA Directory: {ca_dir}")
    logger.info(f"ETAP Alias: {etap_alias}")

    # Step 1: Generate CSR on collector
    logger.info(f"\n{'=' * 80}")
    logger.info("STEP 1: Generate CSR for Oracle ETAP on collector")
    logger.info(f"{'=' * 80}")

    etap_csr_id = None
    etap_token = None

    try:
        appliance = ApplianceClient(
            host=collector_ip,
            user="cli",
            password=cli_password,
            prompt_regex=r">",
            strip_ansi=True,
            debug=debug
        )
        if not appliance.connect():
            logger.error("Failed to connect to collector")
            return False

        logger.info("✓ Connected to collector")
        logger.info(f"Generating CSR for alias '{etap_alias}' (alias already exists → will select option 2)...")

        csr, token, line_above = appliance.generate_external_stap_csr(
            alias=etap_alias,
            common_name=etap_common_name,
            san1=etap_san1,
            organizational_unit=etap_organizational_unit,
            organization=etap_organization,
            country=etap_country,
            encryption_algorithm=etap_encryption_algorithm,
            keysize=etap_keysize,
            locality=etap_locality,
            state=etap_state,
            email=etap_email,
            san2=etap_san2
        )

        with open(csr_path, "w", encoding="utf-8") as f:
            f.write(csr)

        etap_csr_id = line_above
        etap_token = token
        config.set_custom_variable('oracle_etap_token', etap_token)
        with open(token_file, "w", encoding="utf-8") as f:
            f.write(etap_token)

        logger.info(f"✓ CSR generated and saved to {csr_path}")
        logger.info(f"  CSR ID: {etap_csr_id}")
        logger.info(f"  Deployment token: {etap_token}")

        appliance.disconnect()

    except Exception as e:
        logger.error(f"✗ Failed to generate CSR: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False

    # Step 2: Sign CSR with existing CA
    logger.info(f"\n{'=' * 80}")
    logger.info("STEP 2: Sign CSR with CA")
    logger.info(f"{'=' * 80}")

    try:
        result = run_local_command(
            command=f"openssl x509 -sha256 -req -days 3650 -CA {ca_cert_path} -CAkey {ca_key_path} -CAcreateserial -CAserial {ca_dir}/serial -in {csr_path} -out {etap_cert_path}",
            shell=True,
            timeout=60,
            check=True
        )
        logger.info(f"✓ CSR signed, certificate saved to {etap_cert_path}")
    except Exception as e:
        logger.error(f"✗ Failed to sign CSR: {e}")
        return False

    # Step 3: Import ETAP certificate to collector
    logger.info(f"\n{'=' * 80}")
    logger.info("STEP 3: Import ETAP certificate to collector")
    logger.info(f"{'=' * 80}")

    try:
        appliance = ApplianceClient(
            host=collector_ip,
            user="cli",
            password=cli_password,
            prompt_regex=r">",
            strip_ansi=True,
            debug=debug
        )
        if not appliance.connect():
            logger.error("Failed to connect to collector")
            return False

        logger.info("✓ Connected to collector")

        with open(etap_cert_path, "r", encoding="utf-8") as f:
            etap_cert_pem = f.read()

        appliance.import_external_stap_certificate(
            alias_line=etap_csr_id,
            stap_cert=etap_cert_pem
        )

        logger.info("✓ ETAP certificate imported successfully")
        appliance.disconnect()

    except Exception as e:
        logger.error(f"✗ Failed to import ETAP certificate: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False

    # Step 4: Deploy Oracle ETAP quadlet
    logger.info(f"\n{'=' * 80}")
    logger.info("STEP 4: Deploy Oracle ETAP quadlet")
    logger.info(f"{'=' * 80}")

    sauropod_info = config.get_machine("sauropod")
    if not sauropod_info:
        logger.error("Machine 'sauropod' not found in configuration")
        return False
    sauropod_ip = sauropod_info.get("private_ip") or sauropod_info.get("host")
    if not sauropod_ip:
        logger.error("Sauropod IP not found in configuration")
        return False

    version_file = "/opt/ETAP/ca/guardium_etap_version.txt"
    etap_version = config.get_custom_variable("guardium_etap_version")
    if not etap_version and os.path.exists(version_file):
        with open(version_file, "r", encoding="utf-8") as f:
            etap_version = f.read().strip()
        if etap_version:
            logger.info(f"Loaded guardium_etap_version from {version_file}")
    if not etap_version:
        logger.error("guardium_etap_version not found in custom_variables or version file")
        return False

    container_file_content = f"""[Unit]
Description=oracle-etap
Documentation=man:podman-generate-systemd(1)

[Container]
Image=icr.io/guardium/guardium_external_s-tap:v{etap_version}
ContainerName=oracle-etap
HostName=localhost-oracle-etap

PodmanArgs=--memory=4g --shm-size=800M

PublishPort=63334:8888/tcp

Environment=STAP_CONFIG_TAP_TAP_IP=NULL
Environment=STAP_CONFIG_TAP_PRIVATE_TAP_IP=NULL
Environment=STAP_CONFIG_TAP_FORCE_SERVER_IP=0
Environment=STAP_CONFIG_PROXY_GROUP_UUID=7a2f91bc-d83e-41c5-a6f9-12047ae58b32
Environment=STAP_CONFIG_PROXY_GROUP_MEMBER_COUNT=1
Environment=STAP_CONFIG_PROXY_NUM_WORKERS=1
Environment=STAP_CONFIG_PROXY_PROXY_PROTOCOL=0
Environment=STAP_CONFIG_PROXY_DISCONNECT_ON_INVALID_CERTIFICATE=0
Environment=STAP_CONFIG_PROXY_NOTIFY_ON_INVALID_CERTIFICATE=0
Environment=STAP_CONFIG_PROXY_DETECT_SSL_WITHIN_X_PACKETS=-1
Environment=STAP_CONFIG_DB_0_REAL_DB_PORT=1522
Environment=STAP_CONFIG_PROXY_LISTEN_PORT=8888
Environment=STAP_CONFIG_PROXY_DEBUG=0
Environment=STAP_CONFIG_PROXY_SECRET={etap_token}
Environment=STAP_CONFIG_PROXY_CSR_NAME=
Environment=STAP_CONFIG_PROXY_CSR_COUNTRY=
Environment=STAP_CONFIG_PROXY_CSR_PROVINCE=
Environment=STAP_CONFIG_PROXY_CSR_CITY=
Environment=STAP_CONFIG_PROXY_CSR_ORGANIZATION=
Environment=STAP_CONFIG_PROXY_CSR_KEYLENGTH=2048
Environment=STAP_CONFIG_DB_0_DB_TYPE=oracle
Environment=STAP_CONFIG_PARTICIPATE_IN_LOAD_BALANCING=0
Environment=STAP_CONFIG_TAP_TENANT_ID=ORACLEETAP
Environment=STAP_CONFIG_SQLGUARD_0_SQLGUARD_IP={collector_ip}
Environment=STAP_CONFIG_PROXY_DB_HOST={sauropod_ip}

[Service]
Restart=always
TimeoutStopSec=70

[Install]
WantedBy=multi-user.target
"""

    container_file_path = "/etc/containers/systemd/oracle-etap.container"

    result = execute_local_command("mkdir -p /etc/containers/systemd", logger=logger, verbose=verbose)
    if result['rc'] != 0:
        logger.error(f"✗ Failed to create systemd container directory: {result['stderr']}")
        return False

    result = execute_local_command(f"cat > {container_file_path} << 'EOF'\n{container_file_content}\nEOF", logger=logger, verbose=verbose)
    if result['rc'] != 0:
        logger.error(f"✗ Failed to create systemd container file: {result['stderr']}")
        return False
    logger.info(f"✓ Quadlet file created: {container_file_path}")

    result = execute_local_command("systemctl daemon-reload", logger=logger, verbose=verbose)
    if result['rc'] != 0:
        logger.error(f"✗ Failed to reload systemd daemon: {result['stderr']}")
        return False

    result = execute_local_command("systemctl start oracle-etap", logger=logger, verbose=verbose)
    if result['rc'] != 0:
        logger.error(f"✗ Failed to start oracle-etap service: {result['stderr']}")
        return False

    logger.info("\n" + "=" * 80)
    logger.info("✓ ORACLE CONTAINER ETAP CERTIFICATE COMPLETED")
    logger.info("=" * 80)
    logger.info(f"CSR: {csr_path}")
    logger.info(f"Certificate: {etap_cert_path}")
    logger.info(f"Deployment Token: {etap_token}")
    logger.info(f"Quadlet: {container_file_path}")
    logger.info(f"ETAP DB Host: {sauropod_ip}:1522")
    logger.info("=" * 80)

    return True


def setup_appnode(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False,
    **kwargs
) -> bool:
    from core.appliance_operations import setup_appnode as core_setup_appnode
    
    if not kwargs.get('appliance_name'):
        logger.error("appliance_name required")
        return False
    
    return core_setup_appnode(
        config=config,
        logger=logger,
        appliance_name=kwargs['appliance_name'],
        user=kwargs.get('user'),
        password=kwargs.get('password'),
        prompt_regex=kwargs.get('prompt_regex'),
        debug=debug,
        retry_interval=kwargs.get('retry_interval', 60),
        max_retries=kwargs.get('max_retries', 10)
    )


def enable_ltr_on_appnode(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False,
    **kwargs
) -> bool:
    from core.appliance_operations import enable_ltr_on_appnode as core_enable_ltr
    
    if not kwargs.get('appliance_name'):
        logger.error("appliance_name required")
        return False
    
    return core_enable_ltr(
        config=config,
        logger=logger,
        appliance_name=kwargs['appliance_name'],
        user=kwargs.get('user'),
        password=kwargs.get('password'),
        prompt_regex=kwargs.get('prompt_regex'),
        debug=debug
    )


def import_minio_CA_certificate(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False,
    **kwargs
) -> bool:
    from core.appliance_operations import import_datalake_s3_certificate
    
    if not kwargs.get('appliance_name'):
        logger.error("appliance_name required")
        return False
    
    return import_datalake_s3_certificate(
        config=config,
        logger=logger,
        appliance_name=kwargs['appliance_name'],
        certificate_file_path=kwargs.get('certificate_file_path', '/home/minio/ca/certs/ca.crt'),
        user=kwargs.get('user'),
        password=kwargs.get('password'),
        prompt_regex=kwargs.get('prompt_regex'),
        debug=debug
    )


def distribute_minio_certificate(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False,
    **kwargs
) -> bool:
    """
    Distribute MinIO S3 certificate to all managed appliances.
    
    Wrapper for distribute_datalake_certificate from appliance_operations.
    """
    from core.appliance_operations import distribute_datalake_certificate
    
    return distribute_datalake_certificate(
        config=config,
        logger=logger,
        appliance_name=kwargs.get('appliance_name', 'cm'),
        user=kwargs.get('user'),
        password=kwargs.get('password'),
        prompt_regex=kwargs.get('prompt_regex'),
        timeout=kwargs.get('timeout', 300),
        check_interval=kwargs.get('check_interval', 10),
        debug=debug
    )


def activate_ltr(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False,
    **kwargs
) -> bool:
    """
    Activate LTR (Long Term Retention) by configuring complete cold storage.
    
    Wrapper for activate_ltr from appliance_operations.
    """
    from core.appliance_operations import activate_ltr as activate_ltr_op
    
    return activate_ltr_op(
        config=config,
        logger=logger,
        appliance_name=kwargs.get('appliance_name', 'cm'),
        user=kwargs.get('user'),
        password=kwargs.get('password'),
        prompt_regex=kwargs.get('prompt_regex'),
        debug=debug
    )


def import_ltr_dashboard(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
    debug: bool = False
) -> bool:
    from core.guardium_rest_api import import_definitions_files
    
    logger.info("=" * 80)
    logger.info("IMPORT LTR DASHBOARD ON CM")
    logger.info("=" * 80)
    
    definition_files = ["exp_dashboard_ltr.sql"]
    
    logger.info(f"CM Appliance: {cm_appliance}")
    logger.info(f"Definitions directory: {definitions_dir}")
    logger.info(f"File to import: {definition_files[0]}")
    
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
        logger.info("✓ LTR dashboard imported successfully")
        logger.info("=" * 80)
    
    return success


def enable_atap_for_oracle(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False
) -> bool:
    from core.ssh_client import SSHClient

    logger.info("=" * 80)
    logger.info("ENABLE ATAP FOR ORACLE ON SAUROPOD")
    logger.info("=" * 80)

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')

    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("Root password (pwd) not found in custom_variables")
        return False

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password, port=ssh_port, timeout=60)

    try:
        logger.info(f"\n➜ Connecting to sauropod ({sauropod_ip}:{ssh_port})...")
        if not ssh.connect():
            logger.error("Failed to connect to sauropod")
            return False
        logger.info("✓ Connected to sauropod")

        logger.info("\n➜ Stopping Oracle listener...")
        result = ssh.execute_command("su - oracle -c 'lsnrctl stop'", timeout=60, print_output=verbose)
        if result['rc'] != 0:
            logger.warning(f"lsnrctl stop returned non-zero: {result['stderr']}")

        logger.info("\n➜ Shutting down Oracle database...")
        result = ssh.execute_command(
            'su - oracle -c "echo -e \'shutdown immediate;\\nexit\' | sqlplus / as sysdba"',
            timeout=120,
            print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"Oracle shutdown failed: {result['stderr']}")
            return False

        logger.info("✓ Oracle stopped")

        guardctl = "/opt/guardium/modules/ATAP/current/files/bin/guardctl"

        logger.info("\n➜ Authorizing oracle user...")
        result = ssh.execute_command(f"{guardctl} authorize-user oracle", timeout=60, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"authorize-user failed: {result['stderr']}")
            return False

        logger.info("\n➜ Storing ATAP configuration for Oracle...")
        result = ssh.execute_command(
            f"{guardctl} --db-type=oracle --db-instance=ORCLCDB --db_user=oracle"
            f" --db_home=/u01/app/oracle/product/21c/dbhome_1/ --db_base=/home/oracle --db_version=21 store-conf",
            timeout=60, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"store-conf failed: {result['stderr']}")
            return False

        logger.info("\n➜ Activating ATAP for Oracle...")
        result = ssh.execute_command(
            f"{guardctl} --db-type=oracle --db-instance=ORCLCDB activate",
            timeout=60, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"activate failed: {result['stderr']}")
            return False

        logger.info("\n➜ Starting Oracle database...")
        result = ssh.execute_command(
            'su - oracle -c "echo -e \'startup\\nexit\' | sqlplus / as sysdba"',
            timeout=120, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"Oracle startup failed: {result['stderr']}")
            return False

        logger.info("\n➜ Starting Oracle listener...")
        result = ssh.execute_command("su - oracle -c 'lsnrctl start'", timeout=60, print_output=verbose)
        if result['rc'] != 0:
            logger.warning(f"lsnrctl start returned non-zero: {result['stderr']}")

        logger.info("✓ Oracle started")

    except Exception as e:
        logger.error(f"✗ SSH operation failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

    logger.info("=" * 80)
    logger.info("✓ Oracle stopped successfully")
    logger.info("=" * 80)
    return True


def install_stap_on_sauropod(
    config,
    logger,
    verbose: bool = False,
    appliance_name: Optional[str] = None,
    collector_name: Optional[str] = None,
    client_ip: Optional[str] = None,
    gim_installer_filename: str = "guard-bundle-GIM-12.2.2.0_r123489_v12_x_1-rhel-8-linux-x86_64.gim.sh",
    gim_source_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/agents/shell",
    module: str = "BUNDLE-STAP",
    module_version: str = "12.2.2.0_r123489_3",
    use_tls: str = "1",
    statistics: str = "-3",
    debug: bool = False
) -> bool:
    from core.ssh_client import SSHClient
    from core.appliance_operations import install_gim_module
    from core.appliance_config_loader import ApplianceConfigLoader
    import time

    logger.info("=" * 80)
    logger.info("INSTALL STAP ON SAUROPOD")
    logger.info("=" * 80)

    if not appliance_name:
        logger.error("appliance_name is required (GIM server, e.g., 'cm')")
        return False

    if not collector_name:
        logger.error("collector_name is required (collector for SQLGUARD_IP, e.g., 'coll1')")
        return False

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')

    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("Root password (pwd) not found in custom_variables")
        return False

    if not client_ip:
        client_ip = sauropod_ip
        logger.info(f"Auto-detected sauropod client IP: {client_ip}")

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    collector_config = appliance_loader.get_appliance(collector_name)
    if not collector_config:
        logger.error(f"Collector '{collector_name}' not found in machines_info.json")
        return False

    sqlguard_ip = collector_config.get('ip')
    if not sqlguard_ip:
        logger.error(f"Collector '{collector_name}' has no IP address configured")
        return False

    logger.info(f"Sauropod IP: {sauropod_ip}:{ssh_port}")
    logger.info(f"SQL Guard IP (collector '{collector_name}'): {sqlguard_ip}")

    gim_local_path = f"{gim_source_dir}/{gim_installer_filename}"
    remote_lab_dir = "/opt/lab_files"
    remote_installer_path = f"{remote_lab_dir}/{gim_installer_filename}"

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password, port=ssh_port, timeout=60)

    try:
        logger.info("\n➜ Connecting to sauropod...")
        if not ssh.connect():
            logger.error("Failed to connect to sauropod")
            return False
        logger.info("✓ Connected to sauropod")

        logger.info(f"\n➜ Creating directory {remote_lab_dir}...")
        result = ssh.execute_command(f"mkdir -p {remote_lab_dir}", print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to create directory: {result['stderr']}")
            return False
        logger.info(f"✓ {remote_lab_dir} created")

        logger.info(f"\n➜ Copying {gim_installer_filename} to sauropod...")
        if not ssh.upload_file(gim_local_path, remote_installer_path):
            logger.error(f"Failed to upload {gim_installer_filename}")
            return False
        logger.info("✓ GIM installer uploaded")

        logger.info("\n➜ Setting execute permissions on *.sh files...")
        result = ssh.execute_command(f"chmod +x {remote_lab_dir}/*.sh", print_output=verbose)
        if result['rc'] != 0:
            logger.warning(f"chmod returned non-zero: {result['stderr']}")

        install_cmd = (
            f"cd {remote_lab_dir} && "
            f"./{gim_installer_filename} -- --dir /opt/guardium --tapip {sauropod_ip} --sqlguardip cm -q"
        )
        logger.info(f"\n➜ Installing GIM on sauropod...")
        logger.info(f"Command: {install_cmd}")
        result = ssh.execute_command(install_cmd, timeout=300, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"GIM installation failed: {result['stderr']}")
            return False
        logger.info("✓ GIM installed on sauropod")

    except Exception as e:
        logger.error(f"✗ SSH operation failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

    logger.info("\n⌛ Waiting for GIM client to register on CM...")
    from core.guardium_rest_api import create_guardium_api
    api = create_guardium_api(config, logger, appliance_name)
    demo_password = config.get_custom_variable('pwd')
    api.get_token(username='demo', password=demo_password)

    max_wait = 300
    interval = 15
    elapsed = 0
    while elapsed < max_wait:
        try:
            api.gim_list_client_modules(client_ip=client_ip)
            logger.info(f"✓ GIM client {client_ip} registered on CM (after {elapsed}s)")
            break
        except Exception:
            logger.info(f"  Client not yet registered, waiting {interval}s... ({elapsed}/{max_wait}s)")
            time.sleep(interval)
            elapsed += interval
    else:
        logger.error(f"✗ GIM client {client_ip} did not register within {max_wait}s")
        return False

    stap_params = {
        "STAP_SQLGUARD_IP": sqlguard_ip,
        "STAP_USE_TLS": use_tls,
        "STAP_STATISTIC": statistics,
        "KTAP_ENABLED": "1",
        "STAP_ENABLED": "1",
        "KTAP_ALLOW_MODULE_COMBOS": "Y"
    }

    logger.info(f"\n{'=' * 80}")
    logger.info("STAP Configuration:")
    logger.info(f"  - Client IP (sauropod): {client_ip}")
    logger.info(f"  - SQL Guard IP (collector): {sqlguard_ip}")
    logger.info(f"  - Use TLS: {use_tls}")
    logger.info(f"  - Statistics: {statistics}")
    logger.info(f"  - KTAP_ENABLED: 1")
    logger.info(f"  - STAP_ENABLED: 1")
    logger.info(f"  - KTAP_ALLOW_MODULE_COMBOS: Y")

    return install_gim_module(
        config=config,
        logger=logger,
        appliance_name=appliance_name,
        client_ip=client_ip,
        module=module,
        module_version=module_version,
        params=stap_params,
        monitor_installation=True,
        installation_delay=10,
        debug=debug
    )


def setup_stap_with_oua_on_sauropod(
    config,
    logger,
    verbose: bool = False,
    appliance_name: str = "cm",
    collector_name: str = "coll1",
    guardium_password: Optional[str] = None,
    instantclient_rpm: str = "oracle-instantclient-basic-21.1.0.0.0-1.x86_64.rpm",
    instantclient_source_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/oracle",
    debug: bool = False
) -> bool:
    from core.ssh_client import SSHClient
    from core.guardium_rest_api import create_guardium_api
    from core.appliance_config_loader import ApplianceConfigLoader
    import time

    if not guardium_password:
        guardium_password = config.get_custom_variable('simple_pwd')
    if not guardium_password:
        logger.error("guardium_password not provided and 'simple_pwd' not found in custom_variables")
        return False

    logger.info("=" * 80)
    logger.info("SETUP STAP WITH OUA ON SAUROPOD")
    logger.info("=" * 80)

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("Root password (pwd) not found in custom_variables")
        return False

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    collector_config = appliance_loader.get_appliance(collector_name)
    if not collector_config:
        logger.error(f"Collector '{collector_name}' not found in machines_info.json")
        return False

    collector_ip = collector_config.get('ip')
    if not collector_ip:
        logger.error(f"Collector '{collector_name}' has no IP address configured")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')

    remote_lab_dir = "/opt/lab_files"
    local_rpm = f"{instantclient_source_dir}/{instantclient_rpm}"
    remote_rpm = f"{remote_lab_dir}/{instantclient_rpm}"

    tnsnames_content = """\
ORCLPDB1 =
  (DESCRIPTION =
    (ADDRESS = (PROTOCOL = TCP)(HOST = sauropod.gdemo.com)(PORT = 1522))
    (CONNECT_DATA =
      (SERVER = DEDICATED)
      (SERVICE_NAME = ORCLPDB1)
    )
  )"""

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password, port=ssh_port, timeout=60)

    # Step 1: Install Oracle Instant Client and configure tnsnames.ora
    logger.info("\n➜ Step 1: Install Oracle Instant Client on sauropod")
    try:
        if not ssh.connect():
            logger.error("Failed to connect to sauropod")
            return False
        logger.info("✓ Connected to sauropod")

        result = ssh.execute_command(f"mkdir -p {remote_lab_dir}", print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to create {remote_lab_dir}: {result['stderr']}")
            return False

        logger.info(f"  Uploading {instantclient_rpm}...")
        if not ssh.upload_file(local_rpm, remote_rpm):
            logger.error(f"Failed to upload {instantclient_rpm}")
            return False
        logger.info("✓ RPM uploaded")

        result = ssh.execute_command(f"dnf -y install {remote_rpm}", timeout=120, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to install Oracle Instant Client: {result['stderr']}")
            return False
        logger.info("✓ Oracle Instant Client installed")

        tnsnames_dir = "/usr/lib/oracle/21/client64/lib/network/admin"
        result = ssh.execute_command(f"mkdir -p {tnsnames_dir}", print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to create tnsnames dir: {result['stderr']}")
            return False

        result = ssh.execute_command(
            f"cat > {tnsnames_dir}/tnsnames.ora << 'EOF'\n{tnsnames_content}\nEOF",
            print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"Failed to write tnsnames.ora: {result['stderr']}")
            return False
        logger.info(f"✓ tnsnames.ora configured at {tnsnames_dir}/tnsnames.ora")

    except Exception as e:
        logger.error(f"✗ SSH operation failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

    # Step 2: Create game schema in Oracle container via guardium-notes-dbtraffic
    logger.info("\n➜ Step 2: Create game schema in Oracle container (rebuild)")
    dbtraffic_dir = "/opt/guardium_tz_bootcamp_automation/upload/guardium_notes_dbtraffic"
    rebuild_cmd = (
        f"cd {dbtraffic_dir} && "
        f"source venv/bin/activate && "
        f"guardium-notes-dbtraffic --config config/oracle_container_sauropod.yaml rebuild"
    )
    result = execute_local_command(rebuild_cmd, logger=logger, verbose=verbose)
    if result['rc'] != 0:
        logger.error(f"✗ Failed to create game schema: {result['stderr']}")
        return False
    logger.info("✓ Game schema created in Oracle container")

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password, port=ssh_port, timeout=60)

    # Step 3: Create secadmin and guardium users, grant privileges
    logger.info("\n➜ Step 3: Create secadmin and guardium users")
    try:
        import oracledb
        dsn = f"{sauropod_ip}:1522/ORCLPDB1"

        conn = oracledb.connect(user="system", password=root_password, dsn=dsn)
        for sql in [
            f'CREATE USER secadmin IDENTIFIED BY "{root_password}"',
            f'CREATE USER guardium IDENTIFIED BY "{guardium_password}"',
            "GRANT CONNECT, SELECT ANY DICTIONARY, SELECT_CATALOG_ROLE, AUDIT_ADMIN, CREATE PROCEDURE, DROP ANY PROCEDURE, AUDIT SYSTEM, AUDIT ANY, CREATE JOB TO SECADMIN",
            "GRANT CONNECT, RESOURCE TO guardium",
            "GRANT SELECT ANY DICTIONARY TO guardium",
            r"BEGIN DBMS_NETWORK_ACL_ADMIN.APPEND_HOST_ACE(host => 'localhost', ace => xs$ace_type(privilege_list => xs$name_list('connect', 'resolve'), principal_name => 'guardium', principal_type => xs_acl.ptype_db)); END;",
        ]:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
        conn.close()
        logger.info("✓ secadmin and guardium users created")

        # Step 4: Create audit policy GAME_APP and scheduler job as secadmin
        logger.info("\n➜ Step 4: Setup OUA audit policy GAME_APP as secadmin")
        conn = oracledb.connect(user="secadmin", password=root_password, dsn=dsn)
        for sql in [
            r"BEGIN DECLARE v_cnt NUMBER; BEGIN SELECT COUNT(*) INTO v_cnt FROM audit_unified_policies WHERE policy_name='GAME_APP'; IF v_cnt=0 THEN EXECUTE IMMEDIATE 'CREATE AUDIT POLICY GAME_APP ACTIONS ALL ON game.customers, ALL ON game.credit_cards, ALL ON game.transactions, ALL ON game.extras, ALL ON game.features'; END IF; EXECUTE IMMEDIATE 'AUDIT POLICY GAME_APP'; END; END;",
            r"BEGIN DBMS_SCHEDULER.create_job(job_name=>'ENSURE_GAME_APP_AUDIT', job_type=>'STORED_PROCEDURE', job_action=>'ENSURE_GAME_APP_AUDIT', repeat_interval=>'FREQ=MINUTELY;INTERVAL=45', enabled=>TRUE); END;",
        ]:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
        conn.close()
        logger.info("✓ Audit policy GAME_APP created and enabled")

    except Exception as e:
        logger.error(f"✗ Oracle connection failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False

    # Step 5: Configure guard_tap.ini for OUA monitoring
    logger.info("\n➜ Step 5: Configure guard_tap.ini for OUA")
    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password, port=ssh_port, timeout=60)
    try:
        if not ssh.connect():
            logger.error("Failed to connect to sauropod")
            return False
        logger.info("✓ Connected to sauropod")

        ini_cmds = [
            "sed -i 's|^sqlc_properties_dir=.*|sqlc_properties_dir=/usr/lib/oracle/21/client64/lib/network/admin|' /opt/guardium/modules/STAP/current/guard_tap.ini",
            "sed -i 's|^ld_library_paths=.*|ld_library_paths=/usr/lib/oracle/21/client64/lib|' /opt/guardium/modules/STAP/current/guard_tap.ini",
            "/opt/guardium/modules/STAP/current/guard-config-update --restart STAP"
        ]
        for cmd in ini_cmds:
            result = ssh.execute_command(cmd, timeout=60, print_output=verbose)
            if result['rc'] != 0:
                logger.warning(f"Command returned non-zero: {cmd}\n{result['stderr']}")
        logger.info("✓ guard_tap.ini configured and STAP restarted")

    except Exception as e:
        logger.error(f"✗ SSH operation failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

    # Step 5: Store SQL credentials and create SQL configuration via REST API
    logger.info("\n➜ Step 5: Store Oracle credentials and create SQL configuration")
    try:
        api = create_guardium_api(config, logger, appliance_name)
        api.get_token(username='demo', password=root_password)

        logger.info("  Storing guardium user credentials on collector...")
        api.store_sql_credentials(
            password=guardium_password,
            username="guardium",
            stap_host=sauropod_ip,
            api_target_host=collector_ip
        )
        logger.info("✓ SQL credentials stored")

        time.sleep(60)

        logger.info("  Creating SQL configuration for Oracle OUA...")
        api.create_sql_configuration(
            db_type="Oracle",
            instance="ORCLPDB1",
            stap_host=sauropod_ip,
            username="guardium",
            api_target_host=collector_ip
        )
        logger.info("✓ SQL configuration created")

        time.sleep(60)

        # Step 6: Disable STAP (STAP_ENABLED=0) and reinstall
        logger.info("\n➜ Step 6: Set STAP_ENABLED=0 and apply")
        api.gim_client_params(client_ip=sauropod_ip, param_name="STAP_ENABLED", param_value="0")
        api.gim_schedule_install(client_ip=sauropod_ip, date="now")
        logger.info("✓ STAP_ENABLED=0 scheduled")

    except Exception as e:
        logger.error(f"✗ REST API operation failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False

    logger.info("\n" + "=" * 80)
    logger.info("✓ SETUP STAP WITH OUA ON SAUROPOD COMPLETED")
    logger.info("=" * 80)
    return True


def deploy_uc_for_oracle_container(
    config,
    logger,
    verbose: bool = False,
    collector_appliance: str = "coll1",
    kafka_appliance: str = "kafka1",
    cm_appliance: str = "cm",
    cluster_name: str = "kafka_cluster_1",
    member_list: str = "kafka1.demo.guardium",
    apply_cruise_control: bool = False,
    credential_name: str = "oracle_container_sauropod",
    credential_type: str = "JDBC Credentials",
    cred_username: str = "guardium",
    cred_password: Optional[str] = None,
    csv_path: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/oracle/oracle_21_container_sauropod.csv",
    jar_file: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/oracle/ojdbc8.jar",
    test_connections: bool = True,
    profile_names: str = "test1",
    bulk_install_hosts: str = "coll1.demo.guardium",
    debug: bool = False,
    **kwargs
) -> bool:
    from core.appliance_client import ApplianceClient
    from core.appliance_config_loader import ApplianceConfigLoader
    from core.appliance_operations import setup_kafka_node as core_setup_kafka_node
    from core.guardium_rest_api import create_guardium_api

    if not cred_password:
        cred_password = config.get_custom_variable('simple_pwd')
    if not cred_password:
        logger.error("cred_password not provided and 'simple_pwd' not found in custom_variables")
        return False

    logger.info("=" * 80)
    logger.info("DEPLOY UC FOR ORACLE CONTAINER")
    logger.info("=" * 80)

    # Step 1: Run UC on collector
    logger.info("\n" + "=" * 80)
    logger.info("STEP 1: Run Universal Connector on collector")
    logger.info("=" * 80)

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    coll_config = appliance_loader.get_appliance(collector_appliance)
    if not coll_config:
        logger.error(f"Appliance '{collector_appliance}' not found")
        return False

    coll_host = coll_config.get('ip')
    coll_type = coll_config.get('type')
    cli_pwd = config.get_custom_variable('cli_pwd')
    if not cli_pwd:
        logger.error("cli_pwd not found in custom_variables")
        return False

    coll_prompt = appliance_loader.get_default_prompt(coll_type, configured=True) if coll_type else r">"

    client = ApplianceClient(host=coll_host, user="cli", password=cli_pwd, prompt_regex=coll_prompt,
                             initial_pattern=None, timeout=300, strip_ansi=True, debug=debug)
    if not client.connect():
        logger.error("Failed to connect to collector")
        return False

    result = client.execute_command("grdapi run_universal_connector", timeout=120)
    if verbose:
        logger.info(f"Output: {result}")
    logger.info("✓ run_universal_connector executed")

    status = client.execute_command("grdapi get_universal_connector_status", timeout=60)
    if "Guardium Universal Connector is running" not in status:
        logger.error(f"✗ Unexpected UC status: {status}")
        client.disconnect()
        return False
    logger.info("✓ Guardium Universal Connector is running")
    client.disconnect()

    # Step 2: Setup kafka-node
    logger.info("\n" + "=" * 80)
    logger.info("STEP 2: Setup kafka-node")
    logger.info("=" * 80)

    if not core_setup_kafka_node(config=config, logger=logger, appliance_name=kafka_appliance, debug=debug):
        return False

    # Step 3: Create Kafka cluster
    logger.info("\n" + "=" * 80)
    logger.info("STEP 3: Create Kafka cluster")
    logger.info("=" * 80)

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("Password 'pwd' not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    logger.info(f"Cluster: {cluster_name}, members: {member_list}")
    api.create_kafka_cluster(cluster_name=cluster_name, member_list=member_list, apply_cruise_control=apply_cruise_control)
    logger.info("✓ Kafka cluster created")

    # Step 4: Create UC credential
    logger.info("\n" + "=" * 80)
    logger.info("STEP 4: Create UC credential")
    logger.info("=" * 80)

    logger.info(f"Credential: {credential_name} ({credential_type})")
    api.create_uc_credential(name=credential_name, credential_type=credential_type,
                             parameters={"username": cred_username, "password": cred_password})
    logger.info("✓ UC credential created")

    # Step 5: Import UC profile
    logger.info("\n" + "=" * 80)
    logger.info("STEP 5: Import UC profile")
    logger.info("=" * 80)

    logger.info(f"CSV: {csv_path}")
    logger.info(f"JAR: {jar_file}")
    api.import_profiles_from_file(csv_path=csv_path, jar_file=jar_file, update_mode=False, test_connections=test_connections)
    logger.info("✓ UC profile imported")

    # Step 6: UC bulk install
    logger.info("\n" + "=" * 80)
    logger.info("STEP 6: UC bulk install")
    logger.info("=" * 80)

    cm_config = appliance_loader.get_appliance(cm_appliance)
    cm_host = cm_config.get('ip')
    cm_type = cm_config.get('type')
    cm_prompt = appliance_loader.get_default_prompt(cm_type, configured=True) if cm_type else r">"

    client = ApplianceClient(host=cm_host, user="cli", password=cli_pwd, prompt_regex=cm_prompt,
                             initial_pattern=None, timeout=300, strip_ansi=True, debug=debug)
    if not client.connect():
        logger.error("Failed to connect to CM")
        return False

    cmd = f"grdapi universal_connector_bulk_install profileNames={profile_names} hosts={bulk_install_hosts}"
    logger.info(f"➜ {cmd}")
    result = client.execute_command(cmd, timeout=120)
    logger.info(f"Output: {result}")
    client.disconnect()
    logger.info("✓ UC bulk install completed")

    logger.info("\n" + "=" * 80)
    logger.info("✓ DEPLOY UC FOR ORACLE CONTAINER - ALL STEPS COMPLETED")
    logger.info("=" * 80)
    return True


# TODO: TEMP - uc2_tests group - remove after UC2 testing is complete
def uc2_test_register_kafka_cluster(
    config,
    logger,
    verbose: bool = False,
    cm_appliance: str = "cm",
    cluster_name: str = "kafka_cluster_1",
    member_list: str = "kafka1.demo.guardium",
    apply_cruise_control: bool = False,
    debug: bool = True,
    **kwargs
) -> bool:
    from core.guardium_rest_api import create_guardium_api

    logger.info("=" * 80)
    logger.info("UC2 TEST: REGISTER KAFKA CLUSTER")
    logger.info("=" * 80)

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("Password 'pwd' not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    logger.info(f"Cluster: {cluster_name}, members: {member_list}, cruise_control: {apply_cruise_control}")
    result = api.create_kafka_cluster(
        cluster_name=cluster_name,
        member_list=member_list,
        apply_cruise_control=apply_cruise_control
    )
    if debug:
        logger.info(f"API response: {result}")
    logger.info("✓ Kafka cluster registered")
    return True


def uc2_test_import_uc_profile(
    config,
    logger,
    verbose: bool = False,
    cm_appliance: str = "cm",
    csv_path: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/oracle/oracle_21_container_sauropod.csv",
    jar_file: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/oracle/ojdbc8.jar",
    update_mode: bool = False,
    test_connections: bool = True,
    debug: bool = True,
    **kwargs
) -> bool:
    from core.guardium_rest_api import create_guardium_api

    logger.info("=" * 80)
    logger.info("UC2 TEST: IMPORT UC PROFILE")
    logger.info("=" * 80)
    logger.info(f"CSV: {csv_path}")
    logger.info(f"JAR: {jar_file}")
    logger.info(f"update_mode: {update_mode}, test_connections: {test_connections}")

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("Password 'pwd' not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    result = api.import_profiles_from_file(
        csv_path=csv_path,
        jar_file=jar_file,
        update_mode=update_mode,
        test_connections=test_connections
    )
    if debug:
        logger.info(f"API response: {result}")
    logger.info("✓ UC profile imported")
    return True


def uc2_test_bulk_install_uc_profile(
    config,
    logger,
    verbose: bool = False,
    cm_appliance: str = "cm",
    profile_names: str = "oracle_21_container_sauropod",
    bulk_install_hosts: str = "coll1.demo.guardium",
    debug: bool = True,
    **kwargs
) -> bool:
    from core.appliance_client import ApplianceClient
    from core.appliance_config_loader import ApplianceConfigLoader

    logger.info("=" * 80)
    logger.info("UC2 TEST: BULK INSTALL UC PROFILE")
    logger.info("=" * 80)
    logger.info(f"profileNames: {profile_names}, hosts: {bulk_install_hosts}")

    cli_pwd = config.get_custom_variable('cli_pwd')
    if not cli_pwd:
        logger.error("cli_pwd not found in custom_variables")
        return False

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    cm_config = appliance_loader.get_appliance(cm_appliance)
    if not cm_config:
        logger.error(f"Appliance '{cm_appliance}' not found")
        return False

    cm_host = cm_config.get('ip')
    cm_type = cm_config.get('type')
    cm_prompt = appliance_loader.get_default_prompt(cm_type, configured=True) if cm_type else r">"

    client = ApplianceClient(host=cm_host, user="cli", password=cli_pwd, prompt_regex=cm_prompt,
                             initial_pattern=None, timeout=300, strip_ansi=True, debug=debug)
    if not client.connect():
        logger.error("Failed to connect to CM")
        return False

    cmd = f"grdapi universal_connector_bulk_install profileNames={profile_names} hosts={bulk_install_hosts}"
    logger.info(f"➜ {cmd}")
    result = client.execute_command(cmd, timeout=120)
    logger.info(f"Output: {result}")
    client.disconnect()
    logger.info("✓ UC bulk install completed")
    return True
# END TODO: TEMP


def import_oracle_dashboard(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
    debug: bool = False
) -> bool:
    from core.guardium_rest_api import import_definitions_files

    logger.info("=" * 80)
    logger.info("IMPORT ORACLE DASHBOARD ON CM")
    logger.info("=" * 80)

    definition_files = ["exp_dashboard_oracle.sql"]

    logger.info(f"CM Appliance: {cm_appliance}")
    logger.info(f"File to import: {definition_files[0]}")

    success = import_definitions_files(
        config=config,
        logger=logger,
        appliance_name=cm_appliance,
        definition_files=definition_files,
        definitions_dir=definitions_dir,
        debug=debug
    )

    if success:
        logger.info("✓ Oracle dashboard imported successfully")

    return success

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

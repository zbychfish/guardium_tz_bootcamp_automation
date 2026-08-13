#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import traceback
from typing import Optional
from core.logger import get_logger
from core.appliance_config_loader import ApplianceConfigLoader
from core.appliance_operations import copy_files_to_appliance, install_gim_module
from core.guardium_rest_api import create_guardium_api
from core.utils import execute_local_command, execute_commands, run_local_command

logger = get_logger(__name__)

def _header(logger, title: str) -> None:
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)

def _require(logger, **kwargs) -> bool:
    for name, value in kwargs.items():
        if not value:
            logger.error(f"{name} is required")
            return False
    return True

def _get_pwd(config, logger) -> Optional[str]:
    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("pwd not found in custom_variables")
    return pwd

def import_gim_modules(
    config,
    logger,
    verbose: bool = False,
    appliance_name: Optional[str] = None,
    demo_user: str = "demo",
    gim_directory: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/agents/gim",
    gim_target_dir: str = "/var/dump",
    debug: bool = False) -> bool:

    if not _require(logger, appliance_name=appliance_name):
        return False

    _header(logger, "IMPORT GIM MODULES")

    shell_dir = "/opt/guardium_tz_bootcamp_automation/upload/source_files/agents/shell/"
    logger.info(f"➜ chmod +x {shell_dir}*")
    result = execute_local_command(f"chmod +x {shell_dir}*", logger=logger, verbose=verbose)
    if result['rc'] != 0:
        logger.warning(f"⚠ chmod +x failed (rc={result['rc']}): {result['stderr']}")

    logger.info(f"➜ copy *.gim → {appliance_name}:{gim_target_dir}")
    if not copy_files_to_appliance(
        config=config, logger=logger, appliance_name=appliance_name,
        source_dir=gim_directory, file_pattern="*.gim",
        target_dir=gim_target_dir, owner="tomcat:tomcat", debug=debug
    ):
        return False

    demo_password = _get_pwd(config, logger)
    if not demo_password:
        return False

    try:
        api = create_guardium_api(config, logger, appliance_name)
        logger.info(f"➜ get_token {demo_user}")
        api.get_token(username=demo_user, password=demo_password)
        logger.info("✓ authenticated")

        logger.info("➜ get_gim_package *.gim")
        response = api.get_gim_package(filename="*.gim")
        if debug:
            logger.info(f"  response: {response}")
        logger.info("✓ GIM packages imported")
        return True

    except Exception as e:
        logger.error(f"✗ {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False

def install_gim_on_raptor(
    config,
    logger,
    verbose: bool = False,
    gim_installer_path: Optional[str] = None,
    debug: bool = False) -> bool:

    _header(logger, "INSTALL GIM ON RAPTOR")

    if not _require(logger, gim_installer_path=gim_installer_path):
        return False

    if not os.path.exists(gim_installer_path):
        logger.error(f"GIM installer not found: {gim_installer_path}")
        return False

    try:
        logger.info("➜ dnf install perl-File-Copy perl-Sys-Hostname")
        run_local_command(command="dnf install -y perl-File-Copy perl-Sys-Hostname", shell=True, timeout=180, check=True)
        logger.info("✓ Perl packages installed")
    except Exception as e:
        logger.error(f"✗ dnf install failed: {e}")
        return False

    shell_dir = os.path.dirname(gim_installer_path)
    try:
        logger.info(f"➜ chmod +x {shell_dir}/*.sh")
        run_local_command(command=f"chmod +x {shell_dir}/*.sh", shell=True, timeout=30, check=True)
        logger.info("✓ chmod +x done")
    except Exception as e:
        logger.warning(f"⚠ chmod +x failed: {e}")

    tapip = config.get('machines', {}).get('raptor', {}).get('private_ip')
    if not tapip:
        logger.error("TAP IP not found in machines config for raptor")
        return False

    cms = ApplianceConfigLoader(config_loader=config).get_appliances_by_type('cm')
    if not cms:
        logger.error("no Central Manager found in machines_info.json")
        return False
    cm_name, cm = next(iter(cms.items()))
    sqlguardip = cm.get('ip')
    if not sqlguardip:
        logger.error(f"CM '{cm_name}' has no IP configured")
        return False

    command = f"{gim_installer_path} -- --dir /opt/guardium --tapip {tapip} --sqlguardip {sqlguardip}"
    logger.info(f"➜ {command}")

    try:
        result = run_local_command(command=command, shell=True, timeout=300, check=True)
        if debug and result.stdout:
            logger.info(f"  output:\n{result.stdout}")
        logger.info("✓ GIM installed")
        return True
    except TimeoutError:
        logger.error("✗ GIM installation timeout (5 min)")
        return False
    except Exception as e:
        logger.error(f"✗ {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False

def install_stap_on_raptor(
    config,
    logger,
    verbose: bool = False,
    appliance_name: Optional[str] = None,
    collector_name: Optional[str] = None,
    module: Optional[str] = None,
    module_version: Optional[str] = None,
    use_tls: Optional[str] = None,
    statistics: Optional[str] = None,
    connection_pool_size: Optional[str] = None,
    debug: bool = False) -> bool:

    if not _require(logger, appliance_name=appliance_name, collector_name=collector_name):
        return False

    _header(logger, "INSTALL STAP ON RAPTOR")

    client_ip = config.get('machines', {}).get('raptor', {}).get('private_ip')
    if not client_ip:
        logger.error("raptor private_ip not found in machines config")
        return False

    collector_config = ApplianceConfigLoader(config_loader=config).get_appliance(collector_name)
    if not collector_config:
        logger.error(f"collector '{collector_name}' not found in machines_info.json")
        return False
    sqlguard_ip = collector_config.get('ip')
    if not sqlguard_ip:
        logger.error(f"collector '{collector_name}' has no IP configured")
        return False

    logger.info("➜ dnf install kernel-devel kernel-headers")
    if not execute_commands(["dnf install -y kernel-devel-$(uname -r) kernel-headers-$(uname -r)"], logger, verbose=verbose):
        logger.error("failed to install kernel packages")
        return False
    logger.info("✓ kernel packages installed")

    stap_params = {
        "STAP_SQLGUARD_IP": sqlguard_ip,
        "STAP_USE_TLS": use_tls,
        "STAP_STATISTIC": statistics,
        "STAP_CONNECTION_POOL_SIZE": connection_pool_size
    }
    logger.info(f"client_ip={client_ip} sqlguard_ip={sqlguard_ip} tls={use_tls} stats={statistics} pool={connection_pool_size}")

    return install_gim_module(
        config=config, logger=logger,
        appliance_name=appliance_name, client_ip=client_ip,
        module=module, module_version=module_version,
        params=stap_params, monitor_installation=True, installation_delay=10,
        debug=debug
    )

def enable_atap_for_postgres_on_raptor(
    config,
    logger,
    verbose: bool = False,
    db_user: Optional[str] = None,
    db_home: Optional[str] = None,
    db_user_dir: Optional[str] = None,
    db_type: Optional[str] = None,
    db_instance: Optional[str] = None,
    db_version: Optional[str] = None,
    **kwargs) -> bool:

    _header(logger, "ENABLE ATAP FOR POSTGRESQL ON RAPTOR")
    guardctl = "/opt/guardium/modules/ATAP/current/files/bin/guardctl"
    steps = [
        (f"{guardctl} --db-user={db_user} --db-home={db_home} --db-user-dir={db_user_dir} --db-type={db_type} --db-instance={db_instance} --db-version={db_version} store-conf", "store configuration"),
        (f"{guardctl} authorize-user {db_user}", "authorize user"),
        ("systemctl stop postgresql", "stop service"),
        (f"{guardctl} --db-instance={db_instance} activate", "activate ATAP"),
        ("systemctl start postgresql", "start service"),
    ]
    for cmd, desc in steps:
        if not execute_commands([cmd], logger, verbose):
            logger.error(f"Failed to {desc}")
            return False
    logger.info("✓ ATAP enabled for PostgreSQL")
    return True


def correct_mysql_ie(
    config,
    logger,
    verbose: bool = False,
    cm_appliance: Optional[str] = None,
    collector_appliance: Optional[str] = None,
    stap_host: Optional[str] = None,
    **kwargs) -> bool:

    if not stap_host:
        stap_host = config.get('machines', {}).get('raptor', {}).get('private_ip')
        if not stap_host:
            logger.error("stap_host not found in machines config")
            return False

    collector_config = ApplianceConfigLoader(config_loader=config).get_appliance(collector_appliance)
    if not collector_config:
        logger.error(f"Collector '{collector_appliance}' not found")
        return False
    api_target_host = collector_config.get('ip')
    if not api_target_host:
        logger.error(f"Collector '{collector_appliance}' has no IP")
        return False

    pwd = _get_pwd(config, logger)
    if not pwd:
        return False
    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    logger.info(f"➜ delete MySQL IE {stap_host} on {api_target_host}")
    api.delete_inspection_engine(stap_host=stap_host, type="mysql", wait_for_response="1", api_target_host=api_target_host)

    ie_configs = [
        {"port_min": "3306",  "port_max": "3306",  "ktap_db_port": "3306",  "unix_socket_marker": "mysql.sock"},
        {"port_min": "33060", "port_max": "33060", "ktap_db_port": "33060", "unix_socket_marker": "mysql.sock"},
        {"port_min": "3306",  "port_max": "3306",  "ktap_db_port": "3306",  "unix_socket_marker": "mysqlx.sock"},
        {"port_min": "33060", "port_max": "33060", "ktap_db_port": "33060", "unix_socket_marker": "mysqlx.sock"},
    ]
    for i, ie_config in enumerate(ie_configs, 1):
        logger.info(f"➜ create MySQL IE {i}/4: port {ie_config['port_min']}, socket {ie_config['unix_socket_marker']}")
        api.create_inspection_engine(
            stap_host=stap_host, protocol="mysql", db_user="mysqld", db_version="8",
            client="0.0.0.0/0.0.0.0", proc_name="/usr/sbin/mysqld",
            db_install_dir="/var/lib/mysql", api_target_host=api_target_host, **ie_config
        )

    logger.info(f"➜ STAP_DISCOVERY_ENABLED=0 on {stap_host}")
    api.gim_client_params(client_ip=stap_host, param_name="STAP_DISCOVERY_ENABLED", param_value="0")
    api.gim_schedule_install(client_ip=stap_host, date="now")
    logger.info("✓ MySQL IE corrected")
    return True


def enable_atap_for_mongo(config, logger, verbose: bool = False, **kwargs) -> bool:
    _header(logger, "ENABLE ATAP FOR MONGODB ON RAPTOR")
    guardctl = "/opt/guardium/modules/ATAP/current/files/bin/guardctl"
    steps = [
        ("mv /opt/guardium/etc/guard/root/postgres.conf /opt/guardium/etc/guard", "backup postgres.conf"),
        (f"{guardctl} --db-user=mongod --db-home=/usr --db-base=/var/lib/mongo --db-type=mongodb --db-instance=mongo4 store-conf", "store configuration"),
        (f"{guardctl} authorize-user mongod", "authorize user"),
        ("systemctl stop mongod", "stop service"),
        (f"{guardctl} --db-instance=mongo4 activate", "activate ATAP"),
        ("systemctl start mongod", "start service"),
        ("mv /opt/guardium/etc/guard/postgres.conf /opt/guardium/etc/guard/root", "restore postgres.conf"),
    ]
    for cmd, desc in steps:
        if not execute_commands([cmd], logger, verbose):
            logger.error(f"Failed to {desc}")
            return False
    logger.info("✓ ATAP enabled for MongoDB")
    return True


def db2_exit_configuration(config, logger, verbose: bool = False) -> bool:
    _header(logger, "DB2 EXIT CONFIGURATION")
    commands = [
        "/opt/guardium/modules/ATAP/current/files/bin/guardctl authorize-user db2inst1",
        "su - db2inst1 -c 'db2stop'",
        "su - db2inst1 -c 'mkdir -p /home/db2inst1/sqllib/security64/plugin/commexit'",
        "su - db2inst1 -c 'ln -fs /usr/lib64/libguard_db2_exit_64.so /home/db2inst1/sqllib/security64/plugin/commexit/libguard_db2_exit_64.so'",
        "su - db2inst1 -c 'db2 update dbm cfg using comm_exit_list libguard_db2_exit_64'",
        "su - db2inst1 -c 'db2start'",
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("DB2 exit configuration failed")
        return False
    logger.info("✓ DB2 exit configured")
    return True


def configure_db2_exit_ie(
    config,
    logger,
    verbose: bool = False,
    cm_appliance: Optional[str] = None,
    collector_appliance: Optional[str] = None,
    stap_host: Optional[str] = None,
    **kwargs) -> bool:

    if not stap_host:
        stap_host = config.get('machines', {}).get('raptor', {}).get('private_ip')
        if not stap_host:
            logger.error("stap_host not found in machines config")
            return False

    collector_config = ApplianceConfigLoader(config_loader=config).get_appliance(collector_appliance)
    if not collector_config:
        logger.error(f"Collector '{collector_appliance}' not found")
        return False
    api_target_host = collector_config.get('ip')
    if not api_target_host:
        logger.error(f"Collector '{collector_appliance}' has no IP")
        return False

    pwd = _get_pwd(config, logger)
    if not pwd:
        return False
    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    logger.info(f"➜ delete Db2 IE {stap_host} on {api_target_host}")
    api.delete_inspection_engine(stap_host=stap_host, type="Db2", wait_for_response="1", api_target_host=api_target_host)

    logger.info(f"➜ create Db2 Exit IE {stap_host} on {api_target_host}")
    api.create_inspection_engine(
        stap_host=stap_host, protocol="Db2 Exit", db_user="db2inst1", db_version="11",
        client="0.0.0.0/0.0.0.0", proc_name="/home/db2inst1/sqllib/adm/db2sysc",
        db_install_dir="/home/db2inst1", api_target_host=api_target_host
    )
    logger.info("✓ DB2 Exit IE configured")
    return True

# Made with Bob

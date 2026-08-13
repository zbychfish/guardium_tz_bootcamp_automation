#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import glob
import os
import re
import time
import traceback
from typing import Optional
from core.logger import get_logger
from core.appliance_config_loader import ApplianceConfigLoader
from core.appliance_operations import copy_files_to_appliance, install_gim_module, _get_appliance_connection_params
from core.appliance_client import ApplianceClient
from core.guardium_rest_api import create_guardium_api
from core.ssh_client import SSHClient
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

def _get_api(config, logger, appliance_name: str):
    pwd = _get_pwd(config, logger)
    if not pwd:
        return None
    api = create_guardium_api(config, logger, appliance_name)
    api.get_token(username='demo', password=pwd)
    return api

def _monitor_gim(api, client_ip: str, logger) -> bool:
    """Poll gim_list_client_modules until all modules reach INSTALLED state."""
    logger.info("⌛ waiting 10s before monitoring")
    time.sleep(10)
    pending = ["initial"]
    check_count = 0
    while pending:
        check_count += 1
        modules = api.gim_list_client_modules(client_ip=client_ip)
        if "ErrorCode" in modules or "ErrorMessage" in modules:
            logger.error(f"✗ API error: {modules.get('ErrorCode')} — {modules.get('ErrorMessage')}")
            return False
        entries = [e.strip() for e in re.split(r"#+\s*ENTRY\s+\d+\s*#+", modules.get("Message", "")) if e.strip()]
        result_mods = []
        for entry in entries:
            m_name  = re.search(r"NAME:\s+([A-Z0-9\-]+)", entry)
            m_state = re.search(r"STATE:\s+([A-Z\-]+)", entry)
            result_mods.append({
                "name":  m_name.group(1)  if m_name  else "?",
                "state": m_state.group(1) if m_state else "?",
            })
        pending = [m for m in result_mods if m["state"] != "INSTALLED"]
        if pending:
            logger.info(f"  ⌛ [{check_count}] {len(pending)} module(s) pending: {[m['name'] for m in pending]}")
            time.sleep(30)
        else:
            logger.info(f"  ✓ [{check_count}] all modules INSTALLED")
    return True

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
    api = _get_api(config, logger, cm_appliance)
    if not api:
        return False

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

    if not _monitor_gim(api, stap_host, logger):
        return False

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

    api = _get_api(config, logger, cm_appliance)
    if not api:
        return False

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

def import_verification_definitions(
    config,
    logger,
    verbose: bool = False,
    cm_appliance: Optional[str] = None,
    definitions_dir: Optional[str] = None,
    debug: bool = False) -> bool:

    if not _require(logger, cm_appliance=cm_appliance, definitions_dir=definitions_dir):
        return False

    _header(logger, "IMPORT ATAP LAB DEFINITIONS")

    definition_files = ["exp_datasource_verification_atap_lab.sql"]

    api = _get_api(config, logger, cm_appliance)
    if not api:
        return False

    for filename in definition_files:
        file_path = os.path.join(definitions_dir, filename)
        if not os.path.exists(file_path):
            logger.error(f"✗ file not found: {file_path}")
            return False
        logger.info(f"➜ import {filename}")
        result = api.import_definitions(file_path=file_path)
        if debug:
            logger.info(f"  response: {result}")
        logger.info(f"✓ {filename} imported")

    logger.info("✓ ATAP definitions imported")
    return True

def stop_databases_atap(config, logger, verbose: bool = False, **kwargs) -> bool:
    _header(logger, "STOP DATABASES ATAP (RAPTOR)")
    services = ["mongod", "informix-ifxserver"]
    for svc in services:
        logger.info(f"➜ stop {svc}")
        if not execute_commands([f"systemctl stop {svc}"], logger, verbose):
            logger.error(f"✗ failed to stop {svc}")
            return False
        logger.info(f"➜ disable {svc}")
        if not execute_commands([f"systemctl disable {svc}"], logger, verbose):
            logger.error(f"✗ failed to disable {svc}")
            return False
        logger.info(f"✓ {svc} stopped and disabled")
    logger.info("✓ all ATAP databases stopped and disabled")
    return True

def set_stap_network_latency(
    config,
    logger,
    verbose: bool = False,
    collector_appliance: str = "coll1",
    latency: int = 10,
    **kwargs) -> bool:
    _header(logger, "SET STAP NETWORK LATENCY ON COLLECTOR")

    params = _get_appliance_connection_params(config, logger, collector_appliance)
    if not params:
        return False

    client = ApplianceClient(
        host=params['host'], user=params['user'], password=params['password'],
        prompt_regex=params['prompt_regex'], initial_pattern=None,
        timeout=60, strip_ansi=True
    )

    logger.info(f"[{collector_appliance}] ➜ connect {params['host']}")
    if not client.connect():
        logger.error(f"[{collector_appliance}] ✗ failed to connect")
        return False

    try:
        cmd = f"store stap network_latency {latency}"
        logger.info(f"[{collector_appliance}] ➜ {cmd}")
        result = client.execute_command(cmd)
        if verbose:
            logger.info(f"[{collector_appliance}]   {result.strip()}")
        logger.info(f"[{collector_appliance}] ✓ network_latency set to {latency}")
        return True
    finally:
        client.disconnect()

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
    debug: bool = False) -> bool:

    if not _require(logger, appliance_name=appliance_name, collector_name=collector_name):
        return False

    _header(logger, "INSTALL STAP ON SAUROPOD")

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')

    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("pwd not found in custom_variables")
        return False

    if not client_ip:
        client_ip = sauropod_ip

    collector_config = ApplianceConfigLoader(config_loader=config).get_appliance(collector_name)
    if not collector_config:
        logger.error(f"collector '{collector_name}' not found in machines_info.json")
        return False
    sqlguard_ip = collector_config.get('ip')
    if not sqlguard_ip:
        logger.error(f"collector '{collector_name}' has no IP configured")
        return False

    logger.info(f"  sauropod={sauropod_ip}:{ssh_port}  sqlguard={sqlguard_ip}")

    gim_local_path = f"{gim_source_dir}/{gim_installer_filename}"
    remote_lab_dir = "/opt/lab_files"
    remote_installer_path = f"{remote_lab_dir}/{gim_installer_filename}"

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password, port=ssh_port, timeout=60)
    try:
        logger.info("➜ connect to sauropod")
        if not ssh.connect():
            logger.error("✗ failed to connect to sauropod")
            return False
        logger.info("✓ connected")

        result = ssh.execute_command(f"mkdir -p {remote_lab_dir}", print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ mkdir failed: {result['stderr']}")
            return False

        logger.info(f"➜ upload {gim_installer_filename}")
        if not ssh.upload_file(gim_local_path, remote_installer_path):
            logger.error(f"✗ failed to upload {gim_installer_filename}")
            return False
        logger.info("✓ GIM installer uploaded")

        result = ssh.execute_command(f"chmod +x {remote_lab_dir}/*.sh", print_output=verbose)
        if result['rc'] != 0:
            logger.warning(f"⚠ chmod +x failed: {result['stderr']}")

        install_cmd = f"cd {remote_lab_dir} && ./{gim_installer_filename} -- --dir /opt/guardium --tapip {sauropod_ip} --sqlguardip cm -q"
        logger.info(f"➜ {install_cmd}")
        result = ssh.execute_command(install_cmd, timeout=300, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ GIM install failed: {result['stderr']}")
            return False
        logger.info("✓ GIM installed on sauropod")

    except Exception as e:
        logger.error(f"✗ {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

    logger.info("⌛ waiting for GIM client to register on CM")
    api = create_guardium_api(config, logger, appliance_name)
    api.get_token(username='demo', password=root_password)

    max_wait, interval, elapsed = 300, 15, 0
    while elapsed < max_wait:
        try:
            api.gim_list_client_modules(client_ip=client_ip)
            logger.info(f"✓ GIM client {client_ip} registered (after {elapsed}s)")
            break
        except Exception:
            logger.info(f"  not registered yet ({elapsed}/{max_wait}s)")
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
    logger.info(f"  sqlguard={sqlguard_ip}  tls={use_tls}  stats={statistics}")

    return install_gim_module(
        config=config, logger=logger,
        appliance_name=appliance_name, client_ip=client_ip,
        module=module, module_version=module_version,
        params=stap_params, monitor_installation=True, installation_delay=10,
        debug=debug
    )

def enable_atap_for_oracle(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False) -> bool:
    
    _header(logger, "ENABLE ATAP FOR ORACLE ON SAUROPOD")

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')

    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("pwd not found in custom_variables")
        return False

    guardctl = "/opt/guardium/modules/ATAP/current/files/bin/guardctl"
    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password, port=ssh_port, timeout=60)
    try:
        logger.info(f"➜ connect to sauropod ({sauropod_ip}:{ssh_port})")
        if not ssh.connect():
            logger.error("✗ failed to connect to sauropod")
            return False
        logger.info("✓ connected")

        for cmd, desc, warn_only in [
            ("su - oracle -c 'lsnrctl stop'", "lsnrctl stop", True),
            ('su - oracle -c "echo -e \'shutdown immediate;\\nexit\' | sqlplus / as sysdba"', "sqlplus shutdown immediate", False),
            (f"{guardctl} authorize-user oracle", "guardctl authorize-user oracle", False),
            (f"{guardctl} --db-type=oracle --db-instance=ORCLCDB --db_user=oracle --db_home=/u01/app/oracle/product/21c/dbhome_1/ --db_base=/home/oracle --db_version=21 store-conf", "guardctl store-conf", False),
            (f"{guardctl} --db-type=oracle --db-instance=ORCLCDB activate", "guardctl activate", False),
            ('su - oracle -c "echo -e \'startup\\nexit\' | sqlplus / as sysdba"', "sqlplus startup", False),
            ("su - oracle -c 'lsnrctl start'", "lsnrctl start", True),
        ]:
            logger.info(f"➜ {desc}")
            result = ssh.execute_command(cmd, timeout=120, print_output=verbose)
            if result['rc'] != 0:
                if warn_only:
                    logger.warning(f"⚠ {desc}: {result['stderr']}")
                else:
                    logger.error(f"✗ {desc}: {result['stderr']}")
                    return False
        logger.info("✓ ATAP enabled for Oracle")

    except Exception as e:
        logger.error(f"✗ {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

    return True


# Made with Bob

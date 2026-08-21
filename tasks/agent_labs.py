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
from core.utils import execute_local_command, execute_commands, run_local_command, dnf_install, ssh_dnf_install

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
    debug: bool = False,
    **kwargs) -> bool:

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
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, "INSTALL GIM ON RAPTOR")

    if not _require(logger, gim_installer_path=gim_installer_path):
        return False

    if not os.path.exists(gim_installer_path):
        logger.error(f"GIM installer not found: {gim_installer_path}")
        return False

    logger.info("➜ dnf install perl-File-Copy perl-Sys-Hostname")
    if not dnf_install("perl-File-Copy perl-Sys-Hostname", logger):
        return False
    logger.info("✓ Perl packages installed")

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
    debug: bool = False,
    **kwargs) -> bool:

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
    if not dnf_install("kernel-devel-$(uname -r) kernel-headers-$(uname -r)", logger):
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
    logger.info(f"➜ STAP_DISCOVERY_DBS on {stap_host}")
    api.gim_client_params(client_ip=stap_host, param_name="STAP_DISCOVERY_DBS", param_value="oracle:db2:informix:postgres:sybase:teradata:netezza:memsql:mariadb:verticadb:mongodb")
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

def db2_exit_configuration(config, logger, verbose: bool = False, **kwargs) -> bool:
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
    debug: bool = False,
    **kwargs) -> bool:

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
    debug: bool = False,
    **kwargs) -> bool:

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
    debug: bool = False,
    **kwargs) -> bool:
    
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

def setup_stap_with_oua_on_sauropod(
    config,
    logger,
    verbose: bool = False,
    appliance_name: str = "cm",
    collector_name: str = "coll1",
    guardium_password: Optional[str] = None,
    instantclient_rpm: Optional[str] = None,
    instantclient_source_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/oracle",
    debug: bool = False,
    **kwargs) -> bool:

    if not _require(logger, instantclient_rpm=instantclient_rpm):
        return False

    if not guardium_password:
        guardium_password = config.get_custom_variable('simple_pwd')
    if not guardium_password:
        logger.error("guardium_password not provided and 'simple_pwd' not found in custom_variables")
        return False

    _header(logger, "SETUP STAP WITH OUA ON SAUROPOD")

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("sauropod IP not found in machines config")
        return False

    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("pwd not found in custom_variables")
        return False

    collector_config = ApplianceConfigLoader(config_loader=config).get_appliance(collector_name)
    if not collector_config:
        logger.error(f"collector '{collector_name}' not found in machines_info.json")
        return False
    collector_ip = collector_config.get('ip')
    if not collector_ip:
        logger.error(f"collector '{collector_name}' has no IP configured")
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

    # Step 1: Install Oracle Instant Client and configure tnsnames.ora
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

        logger.info(f"➜ upload {instantclient_rpm}")
        if not ssh.upload_file(local_rpm, remote_rpm):
            logger.error(f"✗ failed to upload {instantclient_rpm}")
            return False
        logger.info("✓ RPM uploaded")

        if not ssh_dnf_install(ssh, remote_rpm, logger, timeout=120):
            return False
        logger.info("✓ Oracle Instant Client installed")

        tnsnames_dir = "/usr/lib/oracle/21/client64/lib/network/admin"
        result = ssh.execute_command(f"mkdir -p {tnsnames_dir}", print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ mkdir tnsnames dir failed: {result['stderr']}")
            return False

        result = ssh.execute_command(f"cat > {tnsnames_dir}/tnsnames.ora << 'EOF'\n{tnsnames_content}\nEOF", print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ write tnsnames.ora failed: {result['stderr']}")
            return False
        logger.info(f"✓ tnsnames.ora configured")

    except Exception as e:
        logger.error(f"✗ {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

    # Step 2: Create game schema via guardium-notes-dbtraffic
    dbtraffic_dir = "/opt/guardium_tz_bootcamp_automation/upload/guardium_notes_dbtraffic"
    logger.info("➜ guardium-notes-dbtraffic rebuild oracle_container_sauropod")
    result = execute_local_command(
        f"cd {dbtraffic_dir} && source venv/bin/activate && guardium-notes-dbtraffic --config config/oracle_container_sauropod.yaml rebuild",
        logger=logger, verbose=verbose
    )
    if result['rc'] != 0:
        logger.error(f"✗ rebuild failed: {result['stderr']}")
        return False
    logger.info("✓ game schema created")

    # Step 3: Create secadmin and guardium users
    logger.info("➜ create secadmin and guardium Oracle users")
    try:
        import oracledb
        conn = oracledb.connect(user="system", password=root_password, dsn=f"{sauropod_ip}:1522/ORCLPDB1")
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
    except Exception as e:
        logger.error(f"✗ Oracle connection failed: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False

    # Step 4: Configure guard_tap.ini
    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password, port=ssh_port, timeout=60)
    try:
        logger.info("➜ connect to sauropod (guard_tap.ini)")
        if not ssh.connect():
            logger.error("✗ failed to connect to sauropod")
            return False
        logger.info("✓ connected")

        for cmd in [
            "sed -i 's|^sqlc_properties_dir=.*|sqlc_properties_dir=/usr/lib/oracle/21/client64/lib/network/admin|' /opt/guardium/modules/STAP/current/guard_tap.ini",
            "sed -i 's|^ld_library_paths=.*|ld_library_paths=/usr/lib/oracle/21/client64/lib|' /opt/guardium/modules/STAP/current/guard_tap.ini",
            "/opt/guardium/modules/STAP/current/guard-config-update --restart STAP",
        ]:
            result = ssh.execute_command(cmd, timeout=60, print_output=verbose)
            if result['rc'] != 0:
                logger.warning(f"⚠ guard_tap.ini cmd failed: {result['stderr']}")
        logger.info("✓ guard_tap.ini configured and STAP restarted")

    except Exception as e:
        logger.error(f"✗ {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

    # Step 5: Store SQL credentials and create SQL configuration
    logger.info("➜ store Oracle credentials and create SQL config")
    try:
        api = create_guardium_api(config, logger, appliance_name)
        api.get_token(username='demo', password=root_password)

        api.store_sql_credentials(password=guardium_password, username="guardium", stap_host=sauropod_ip, api_target_host=collector_ip)
        logger.info("✓ SQL credentials stored")

        time.sleep(60)

        api.create_sql_configuration(db_type="Oracle", instance="ORCLPDB1", stap_host=sauropod_ip, username="guardium", api_target_host=collector_ip)
        logger.info("✓ SQL configuration created")

        time.sleep(60)

        api.gim_client_params(client_ip=sauropod_ip, param_name="STAP_ENABLED", param_value="0")
        api.gim_schedule_install(client_ip=sauropod_ip, date="now")
        logger.info("✓ STAP_ENABLED=0 scheduled")

    except Exception as e:
        logger.error(f"✗ REST API failed: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False

    logger.info("✓ SETUP STAP WITH OUA ON SAUROPOD COMPLETED")
    return True

def setup_oua_audit_policy_on_sauropod(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, "SETUP OUA AUDIT POLICY GAME_APP ON SAUROPOD")

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("sauropod IP not found in machines config")
        return False

    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("pwd not found in custom_variables")
        return False

    try:
        import oracledb
        conn = oracledb.connect(user="secadmin", password=root_password, dsn=f"{sauropod_ip}:1522/ORCLPDB1")
        cur = conn.cursor()

        for ddl in ["NOAUDIT POLICY GAME_APP", "DROP AUDIT POLICY GAME_APP"]:
            try:
                cur.execute(ddl); conn.commit()
            except Exception:
                conn.rollback()
        try:
            cur.execute("BEGIN DBMS_SCHEDULER.drop_job(job_name=>'ENSURE_GAME_APP_AUDIT', force=>TRUE); END;"); conn.commit()
        except Exception:
            conn.rollback()

        logger.info("➜ CREATE AUDIT POLICY GAME_APP / AUDIT POLICY / DBMS_SCHEDULER")
        for sql in [
            r"CREATE AUDIT POLICY GAME_APP ACTIONS ALL ON game.customers, ALL ON game.credit_cards, ALL ON game.transactions, ALL ON game.extras, ALL ON game.features",
            r"AUDIT POLICY GAME_APP",
            r"BEGIN DBMS_SCHEDULER.create_job(job_name=>'ENSURE_GAME_APP_AUDIT', job_type=>'STORED_PROCEDURE', job_action=>'ENSURE_GAME_APP_AUDIT', repeat_interval=>'FREQ=MINUTELY;INTERVAL=45', enabled=>TRUE); END;",
        ]:
            cur.execute(sql); conn.commit()

        cur.close(); conn.close()
        logger.info("✓ audit policy GAME_APP created and enabled")

    except Exception as e:
        logger.error(f"✗ Oracle connection failed: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False

    return True

def import_oracle_dashboard(
    config,
    logger,
    verbose: bool = False,
    cm_appliance: str = "cm",
    definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
    debug: bool = False,
    **kwargs) -> bool:
    from core.guardium_rest_api import import_definitions_files

    _header(logger, "IMPORT ORACLE DASHBOARD ON CM")
    logger.info(f"  cm={cm_appliance}  dir={definitions_dir}")

    return import_definitions_files(
        config=config, logger=logger, appliance_name=cm_appliance,
        definition_files=["exp_dashboard_oracle.sql"],
        definitions_dir=definitions_dir, debug=debug
    )

# Made with Bob

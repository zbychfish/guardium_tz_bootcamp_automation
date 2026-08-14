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


def install_filebeat_on_sauropod(
    config,
    logger,
    verbose: bool = False,
    rpms_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/rpms",
    filebeat_pattern: str = "filebeat-*.rpm",
    debug: bool = False
) -> bool:
    machines = config.get('machines', {})
    sauropod_info = machines.get('sauropod', {})
    sauropod_ip = sauropod_info.get('private_ip')
    sauropod_password = sauropod_info.get('password')

    if not sauropod_ip:
        logger.error("sauropod private_ip not found in machines config")
        return False
    if not sauropod_password:
        logger.error("sauropod password not found in machines config")
        return False

    filebeat_rpms = glob.glob(os.path.join(rpms_dir, filebeat_pattern))
    if not filebeat_rpms:
        logger.error(f"✗ no filebeat RPM found: {os.path.join(rpms_dir, filebeat_pattern)}")
        return False

    filebeat_rpm = filebeat_rpms[0]
    filebeat_filename = os.path.basename(filebeat_rpm)
    logger.info(f"  found: {filebeat_filename}")

    ssh = SSHClient(host=sauropod_ip, username="root", password=sauropod_password, timeout=60)
    try:
        logger.info("➜ connect to sauropod")
        if not ssh.connect():
            logger.error("✗ failed to connect to sauropod")
            return False
        logger.info("✓ connected")

        result = ssh.execute_command("mkdir -p /root/gn-trainings", print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ mkdir failed: {result['stderr']}")
            return False

        remote_rpm_path = f"/root/gn-trainings/{filebeat_filename}"
        logger.info(f"➜ upload {filebeat_filename}")
        if not ssh.upload_file(filebeat_rpm, remote_rpm_path):
            logger.error("✗ failed to upload filebeat RPM")
            return False
        logger.info("✓ RPM uploaded")

        logger.info(f"➜ dnf install {filebeat_filename}")
        result = ssh.execute_command(f"dnf -y install {remote_rpm_path}", timeout=300, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ dnf install failed: {result['stderr']}")
            return False
        logger.info("✓ filebeat installed")

        config_commands = [
            r"sed -i '/^- type: filestream/,/^[^[:space:]]/c\- type: filestream\n  id: \"cassandra\"\n  enabled: true\n  paths:\n    - /var/log/cassandra/audit/audit.log\n  exclude_lines: [\"AuditLogManager\"]\n  tags: [\"cassandra\"]\n  multiline.type: pattern\n  multiline.pattern: \"^INFO\"\n  multiline.negate: true\n  multiline.match: after' /etc/filebeat/filebeat.yml",
            r"sed -i '/^output.elasticsearch:/,/^[^[:space:]]/ { s/^/# / }' /etc/filebeat/filebeat.yml",
            r"sed -i '/^#output.logstash:/,/^[^[:space:]]/ { s/^#output\.logstash:/output.logstash:/; s|^  #hosts:.*|  hosts: [\"coll1.demo.com:5047\"]| }' /etc/filebeat/filebeat.yml",
        ]
        for cmd in config_commands:
            result = ssh.execute_command(cmd, print_output=verbose)
            if result['rc'] != 0:
                logger.warning(f"⚠ config command failed (rc={result['rc']}): {cmd[:60]}…")
                if debug:
                    logger.debug(f"  stderr: {result['stderr']}")
        logger.info("✓ filebeat configured")

        result = ssh.execute_command("systemctl start filebeat", print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ start failed: {result['stderr']}")
            return False

        result = ssh.execute_command("systemctl enable filebeat", print_output=verbose)
        if result['rc'] != 0:
            logger.warning(f"⚠ enable failed: {result['stderr']}")

        logger.info("✓ filebeat started and enabled")
        return True

    except Exception as e:
        logger.error(f"✗ {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

def run_uc_and_setup_kafka_node(
    config,
    logger,
    verbose: bool = False,
    collector_appliance: str = "coll1",
    kafka_appliance: str = "kafka1",
    debug: bool = False,
    **kwargs
) -> bool:
    from core.appliance_client import ApplianceClient
    from core.appliance_config_loader import ApplianceConfigLoader
    from core.appliance_operations import setup_kafka_node as core_setup_kafka_node

    logger.info("=" * 80)
    logger.info("RUN UC AND SETUP KAFKA NODE")
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
    logger.info("âś“ run_universal_connector executed")

    status = client.execute_command("grdapi get_universal_connector_status", timeout=60)
    if "Guardium Universal Connector is running" not in status:
        logger.error(f"âś— Unexpected UC status: {status}")
        client.disconnect()
        return False
    logger.info("âś“ Guardium Universal Connector is running")
    client.disconnect()

    # Step 2: Setup kafka-node
    logger.info("\n" + "=" * 80)
    logger.info("STEP 2: Setup kafka-node")
    logger.info("=" * 80)

    if not core_setup_kafka_node(config=config, logger=logger, appliance_name=kafka_appliance, debug=debug):
        return False

    logger.info("\n" + "=" * 80)
    logger.info("âś“ RUN UC AND SETUP KAFKA NODE - COMPLETED")
    logger.info("=" * 80)

    import time
    logger.info("âŚ› Waiting 1 minute...")
    time.sleep(60)
    return True


def create_uc_credential_for_oracle_container(
    config,
    logger,
    verbose: bool = False,
    cm_appliance: str = "cm",
    credential_name: str = "oracle_container_sauropod",
    credential_type: str = "JDBC Credentials",
    cred_username: str = "guardium",
    cred_password: Optional[str] = None,
    debug: bool = False,
    **kwargs
) -> bool:
    from core.guardium_rest_api import create_guardium_api

    if not cred_password:
        cred_password = config.get_custom_variable('simple_pwd')
    if not cred_password:
        logger.error("cred_password not provided and 'simple_pwd' not found in custom_variables")
        return False

    logger.info("=" * 80)
    logger.info("CREATE UC CREDENTIAL FOR ORACLE CONTAINER")
    logger.info("=" * 80)

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("Password 'pwd' not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    logger.info(f"Credential: {credential_name} ({credential_type}), username: {cred_username}")
    result = api.create_uc_credential(
        name=credential_name,
        credential_type=credential_type,
        parameters={"username": cred_username, "password": cred_password}
    )
    if debug:
        logger.info(f"API response: {result}")
    logger.info("âś“ UC credential created")
    return True


def register_kafka_cluster(
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
    logger.info("REGISTER KAFKA CLUSTER")
    logger.info("=" * 80)

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("Password 'pwd' not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    import time

    logger.info(f"Cluster: {cluster_name}, members: {member_list}, cruise_control: {apply_cruise_control}")

    # Register cluster â€” retry up to 10 times with 30s interval if API returns an error
    registered = False
    for attempt in range(1, 11):
        result = api.create_kafka_cluster(
            cluster_name=cluster_name,
            member_list=member_list,
            apply_cruise_control=apply_cruise_control
        )
        if debug:
            logger.info(f"API response: {result}")

        if isinstance(result, dict) and result.get('ErrorCode'):
            logger.warning(f"âš  Registration attempt {attempt}/10 failed (ErrorCode {result['ErrorCode']}): {result.get('ErrorMessage', '')} â€” retrying in 30s...")
            time.sleep(30)
        else:
            logger.info(f"âś“ Cluster registration accepted (attempt {attempt}/10)")
            registered = True
            break

    if not registered:
        logger.error(f"âś— Kafka cluster registration failed after 10 attempts")
        return False

    logger.info("âžś Verifying cluster exists via GET /restAPI/kafka_cluster (max 6 attempts, 60s interval)...")
    for attempt in range(1, 7):
        clusters = api.get_kafka_clusters()
        logger.info(f"GET kafka_cluster response: {clusters}")

        if isinstance(clusters, list):
            items = clusters
        elif isinstance(clusters, dict):
            items = next((v for k, v in clusters.items() if isinstance(v, list)), [])
        else:
            items = []

        found = any(
            c.get('name') == cluster_name or c.get('clusterName') == cluster_name
            for c in items
            if isinstance(c, dict)
        )
        if found:
            logger.info(f"âś“ Kafka cluster '{cluster_name}' confirmed (attempt {attempt}/6)")
            break

        if attempt < 6:
            logger.warning(f"âš  Cluster not found yet (attempt {attempt}/6), waiting 60s...")
            time.sleep(60)
    else:
        logger.error(f"âś— Kafka cluster '{cluster_name}' not found after 6 attempts")
        return False

    logger.info("âŚ› Waiting 5 minutes for Kafka cluster to stabilize...")
    time.sleep(300)
    logger.info("âś“ Kafka cluster registration completed")
    return True


def start_kafka_nodes(
    config,
    logger,
    verbose: bool = False,
    cm_appliance: str = "cm",
    cluster_name: str = "kafka_cluster_1",
    member_list: str = "kafka1.demo.guardium",
    debug: bool = True,
    **kwargs
) -> bool:
    import time
    from core.appliance_client import ApplianceClient
    from core.appliance_config_loader import ApplianceConfigLoader

    logger.info("=" * 80)
    logger.info("START KAFKA NODES")
    logger.info("=" * 80)

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

    logger.info("âŚ› Waiting 10s before starting kafka nodes...")
    time.sleep(10)

    client = ApplianceClient(host=cm_host, user="cli", password=cli_pwd, prompt_regex=cm_prompt,
                             initial_pattern=None, timeout=60, strip_ansi=True, debug=debug)
    if not client.connect():
        logger.error("Failed to connect to CM")
        return False

    cmd = f"grdapi start_kafka_nodes clusterName={cluster_name} memberList={member_list}"
    logger.info(f"âžś {cmd}")
    result = client.execute_command(cmd, timeout=30)
    logger.info(f"Output: {result}")
    client.disconnect()
    logger.info("âś“ start_kafka_nodes executed")

    logger.info("âŚ› Waiting 5 minutes for kafka node to start (async)...")
    time.sleep(300)
    logger.info("âś“ Wait completed")
    return True


def import_uc_profile_oracle_container(
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
    logger.info("IMPORT UC PROFILE")
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
    logger.info("âś“ UC profile imported")

    logger.info("âŚ› Waiting 1 minute for UC profile to be processed...")
    import time
    time.sleep(60)
    logger.info("âś“ Wait completed")
    return True


def bulk_install_uc_profile(
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
    logger.info("BULK INSTALL UC PROFILE")
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
    logger.info(f"âžś {cmd}")
    result = client.execute_command(cmd, timeout=120)
    logger.info(f"Output: {result}")
    client.disconnect()
    logger.info("âś“ UC bulk install completed")
    return True


def stop_raptor_databases(config, logger, verbose=True, **kwargs):
    from core.utils import execute_commands

    services = [
        "informix-ifxserver",
        "mongod",
        "mysqld",
        "mysql-etap",
        "oracle-etap",
    ]

    commands = [f"systemctl stop {svc}" for svc in services]

    if not execute_commands(commands, logger, verbose, stop_on_error=False):
        logger.warning("Some services could not be stopped (may not be running)")

    logger.info("âś“ Raptor databases stopped")
    return True


def import_policies_reports_dashboard(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
    debug: bool = False
) -> bool:
    from core.guardium_rest_api import import_definitions_files

    logger.info("=" * 80)
    logger.info("IMPORT POLICIES AND REPORTS DASHBOARD ON CM")
    logger.info("=" * 80)

    definition_files = [
        "exp_dashboard_policies_and_reports.sql",
        "exp_policy_policies_part1.sql",
    ]

    logger.info(f"CM Appliance: {cm_appliance}")
    logger.info(f"Files to import: {', '.join(definition_files)}")

    success = import_definitions_files(
        config=config,
        logger=logger,
        appliance_name=cm_appliance,
        definition_files=definition_files,
        definitions_dir=definitions_dir,
        debug=debug
    )

    if success:
        logger.info("âś“ Policies and Reports dashboard imported successfully")

    return success


def set_stap_firewall_flags_on_raptor(config, logger, verbose=True,
                                      cm_appliance="cm", stap_host=None,
                                      installation_delay=10, **kwargs):
    import re
    import time
    from core.guardium_rest_api import create_guardium_api
    from core.utils import execute_local_command

    if not stap_host:
        machines = config.get('machines', {})
        stap_host = machines.get('raptor', {}).get('private_ip')
        if not stap_host:
            logger.error("stap_host not provided and not found in machines config")
            return False

    api = create_guardium_api(config, logger, cm_appliance)
    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("Password 'pwd' not found in custom_variables")
        return False
    api.get_token(username='demo', password=pwd)

    for param, value in [("STAP_FIREWALL_INSTALLED", "1"), ("STAP_FIREWALL_DEFAULT_STATE", "1")]:
        if verbose:
            logger.info(f"Setting {param}={value} on raptor ({stap_host})")
        api.gim_client_params(client_ip=stap_host, param_name=param, param_value=value)

    logger.info("Scheduling GIM install on raptor...")
    api.gim_schedule_install(client_ip=stap_host, date="now")
    logger.info(f"âś“ Scheduled. Waiting {installation_delay}s before monitoring...")
    time.sleep(installation_delay)

    logger.info("Monitoring installation progress...")
    pending = ["initial"]
    check_count = 0
    while pending:
        check_count += 1
        logger.info(f"  Check #{check_count}: Querying module status...")
        modules = api.gim_list_client_modules(client_ip=stap_host)

        if "ErrorCode" in modules or "ErrorMessage" in modules:
            logger.error(f"  âś— API Error: {modules.get('ErrorCode')} {modules.get('ErrorMessage')}")
            return False

        entries = [e.strip() for e in re.split(r"#+\s*ENTRY\s+\d+\s*#+", modules.get("Message", "")) if e.strip()]
        result_mods = []
        for entry in entries:
            m_state = re.search(r"STATE:\s+([A-Z\-]+)", entry)
            m_name = re.search(r"NAME:\s+([A-Z0-9\-]+)", entry)
            result_mods.append({"name": m_name.group(1) if m_name else "?", "state": m_state.group(1) if m_state else "?"})

        pending = [m for m in result_mods if m["state"] != "INSTALLED"]
        if pending:
            logger.info(f"  âŚ› {len(pending)} module(s) still installing: {[m['name'] for m in pending]}")
            logger.info("  Waiting 30s before next check...")
            time.sleep(30)
        else:
            logger.info("  âś“ All modules installed successfully!")

    logger.info("Restarting STAP agent on raptor...")
    result = execute_local_command(
        "/opt/guardium/modules/STAP/current/guard-config-update --restart STAP",
        logger=logger, verbose=verbose
    )
    if result['rc'] != 0:
        logger.error(f"âś— Failed to restart STAP: {result['stderr']}")
        return False

    logger.info("âś“ STAP firewall flags set, modules installed, agent restarted on raptor")
    return True


def configure_engine_on_raptor(config, logger, verbose=True,
                               cm_appliance="cm", collector_appliance="coll1",
                               compute_average=True, inspect_data=True,
                               log_records=True, record_empty=True, **kwargs):
    from core.guardium_rest_api import create_guardium_api
    from core.appliance_config_loader import ApplianceConfigLoader

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    collector_config = appliance_loader.get_appliance(collector_appliance)
    if not collector_config:
        logger.error(f"Collector '{collector_appliance}' not found")
        return False
    collector_ip = collector_config.get('ip')
    if not collector_ip:
        logger.error(f"Collector '{collector_appliance}' has no IP")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("Password 'pwd' not found in custom_variables")
        return False
    api.get_token(username='demo', password=pwd)

    if verbose:
        logger.info(f"Configuring Inspection Engine (api_target_host={collector_ip})")
        logger.info(f"  compute_average={compute_average}, inspect_data={inspect_data}, "
                    f"log_records={log_records}, record_empty={record_empty}")

    api.engine_config(
        compute_average=compute_average,
        inspect_data=inspect_data,
        log_records=log_records,
        record_empty=record_empty,
        api_target_host=collector_ip
    )

    logger.info("âś“ Inspection Engine configured on raptor")
    return True


def run_dbtraffic_pgsql_on_raptor(config, logger, verbose=True, **kwargs):
    from core.utils import execute_local_command

    base = "/opt/guardium_tz_bootcamp_automation/upload/guardium_notes_dbtraffic"

    commands = [
        f"bash -c 'cd {base} && source venv/bin/activate && guardium-notes-dbtraffic --config config/pgsql.yaml rebuild'",
        f"bash -c 'cd {base} && source venv/bin/activate && guardium-notes-dbtraffic --config config/pgsql.yaml run --duration 1 --speed fast'",
    ]

    for cmd in commands:
        result = execute_local_command(cmd, logger=logger, verbose=verbose)
        if result['rc'] != 0:
            logger.error(f"âś— Command failed: {result['stderr']}")
            return False

    logger.info("âś“ dbtraffic pgsql completed on raptor")
    return True


def add_postgres_app_profile_member(config, logger, verbose=True,
                                    cm_appliance="cm", **kwargs):
    from core.guardium_rest_api import create_guardium_api

    raptor_ip = config.get_machine_ip('raptor', use_private=True)
    if not raptor_ip:
        logger.error("Raptor IP not found in machines config")
        return False

    member = f"{raptor_ip}+POSTGRESQL CLIENT PROGRAM+APPUSER%+{raptor_ip}+%"
    group_desc = "Postgres application profiles"

    api = create_guardium_api(config, logger, cm_appliance)
    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("Password 'pwd' not found in custom_variables")
        return False
    api.get_token(username='demo', password=pwd)

    if verbose:
        logger.info(f"Adding member to group '{group_desc}'")
        logger.info(f"  member: {member}")

    api.create_group_member(desc=group_desc, member=member)

    logger.info(f"âś“ Member added to group '{group_desc}'")
    return True


def install_app_data_access_policy(config, logger, verbose=True,
                                   cm_appliance="cm", collector_appliance="coll1",
                                   policy_name="Application data access control",
                                   debug=False, **kwargs):
    from tasks.setup_appliances import install_policy_on_collector

    return install_policy_on_collector(
        config=config,
        logger=logger,
        verbose=verbose,
        cm_appliance=cm_appliance,
        collector_appliance=collector_appliance,
        policy_name=policy_name,
        debug=debug
    )


def configure_fam_on_raptor(config, logger, verbose=True,
                             cm_appliance: str = "cm",
                             installation_delay: int = 10,
                             debug: bool = False, **kwargs) -> bool:
    import re
    import time
    from core.guardium_rest_api import create_guardium_api

    logger.info("=" * 80)
    logger.info("CONFIGURE FAM ON RAPTOR")
    logger.info("=" * 80)

    stap_host = config.get_machine_ip('raptor', use_private=True)
    if not stap_host:
        logger.error("Raptor IP not found in machines config")
        return False

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("Password 'pwd' not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    for param, value in [
        ("STAP_FAM_ENABLED",        "1"),
        ("STAP_FAM_INSTALLED",       "1"),
        ("STAP_UID_CHAIN_SSHD_IP",  "1"),
        ("STAP_UID_CHAIN_TRACE",     "1"),
    ]:
        if verbose:
            logger.info(f"Setting {param}={value} on raptor ({stap_host})")
        api.gim_client_params(client_ip=stap_host, param_name=param, param_value=value)

    logger.info("Scheduling GIM install on raptor...")
    api.gim_schedule_install(client_ip=stap_host, date="now")
    logger.info(f"âś“ Scheduled. Waiting {installation_delay}s before monitoring...")
    time.sleep(installation_delay)

    logger.info("Monitoring installation progress...")
    pending = ["initial"]
    check_count = 0
    while pending:
        check_count += 1
        logger.info(f"  Check #{check_count}: Querying module status...")
        modules = api.gim_list_client_modules(client_ip=stap_host)

        if "ErrorCode" in modules or "ErrorMessage" in modules:
            logger.error(f"  âś— API Error: {modules.get('ErrorCode')} {modules.get('ErrorMessage')}")
            return False

        entries = [e.strip() for e in re.split(r"#+\s*ENTRY\s+\d+\s*#+", modules.get("Message", "")) if e.strip()]
        result_mods = []
        for entry in entries:
            m_name  = re.search(r"NAME:\s+([A-Z0-9\-]+)", entry)
            m_state = re.search(r"STATE:\s+([A-Z\-]+)", entry)
            result_mods.append({"name": m_name.group(1) if m_name else "?", "state": m_state.group(1) if m_state else "?"})

        pending = [m for m in result_mods if m["state"] != "INSTALLED"]
        if pending:
            logger.info(f"  âŚ› {len(pending)} module(s) still installing: {[m['name'] for m in pending]}")
            logger.info("  Waiting 30s before next check...")
            time.sleep(30)
        else:
            logger.info("  âś“ All modules installed successfully!")

    logger.info("âś“ FAM configured on raptor")
    return True


def import_fam_policy(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
    debug: bool = False,
    **kwargs
) -> bool:
    from core.guardium_rest_api import import_definitions_files

    logger.info("=" * 80)
    logger.info("IMPORT FAM POLICY ON CM")
    logger.info("=" * 80)

    definition_files = ["exp_fam_policy.sql"]

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
        logger.info("âś“ FAM policy imported successfully")

    return success


def install_fammonitor_on_ceratops(config, logger, verbose=False,
                                    appliance_name: str = "cm",
                                    collector_name: str = "coll1",
                                    client_ip: Optional[str] = None,
                                    module: str = "FAMMONITOR",
                                    module_version: str = "12.2_r120202259_1",
                                    debug: bool = False, **kwargs) -> bool:
    from core.appliance_operations import install_gim_module
    from core.appliance_config_loader import ApplianceConfigLoader

    logger.info("=" * 80)
    logger.info("INSTALL FAMMONITOR ON CERATOPS")
    logger.info("=" * 80)

    if not client_ip:
        client_ip = config.get_machine_ip('ceratops', use_private=True)
        if not client_ip:
            logger.error("client_ip not provided and ceratops not found in machines config")
            return False
        logger.info(f"Auto-detected ceratops IP: {client_ip}")

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    collector_config = appliance_loader.get_appliance(collector_name)
    if not collector_config:
        logger.error(f"Collector '{collector_name}' not found in machines_info.json")
        return False

    sqlguard_ip = collector_config.get('ip')
    if not sqlguard_ip:
        logger.error(f"Collector '{collector_name}' has no IP address configured")
        return False

    logger.info(f"  - Client IP (ceratops): {client_ip}")
    logger.info(f"  - SQL Guard IP (collector '{collector_name}'): {sqlguard_ip}")
    logger.info(f"  - Module version: {module_version}")

    return install_gim_module(
        config=config,
        logger=logger,
        appliance_name=appliance_name,
        client_ip=client_ip,
        module=module,
        module_version=module_version,
        params={"FAMMONITOR_SQLGUARD_IP": sqlguard_ip},
        monitor_installation=True,
        installation_delay=10,
        debug=debug
    )


def enable_fam_protect_privileged_on_raptor(config, logger, verbose=True, **kwargs) -> bool:
    from core.utils import execute_commands

    logger.info("=" * 80)
    logger.info("ENABLE FAM PROTECT PRIVILEGED ON RAPTOR")
    logger.info("=" * 80)

    commands = [
        r"sed -i 's/^fam_protect_privileged[[:space:]]*=.*/fam_protect_privileged=1/' /opt/guardium/modules/STAP/current/guard_tap.ini",
        "/opt/guardium/modules/STAP/current/guard-config-update --restart stap",
    ]

    if not execute_commands(commands, logger, verbose):
        logger.error("Failed to enable fam_protect_privileged on raptor")
        return False

    logger.info("âś“ fam_protect_privileged=1 set and STAP restarted on raptor")
    return True


def enable_fam_protect_privileged_on_ceratops(config, logger, verbose=True,
                                               ceratops_machine: str = "ceratops",
                                               ssh_username: str = "itzuser",
                                               debug: bool = False, **kwargs) -> bool:
    import tempfile
    import os
    from core.ssh_client import SSHClient

    logger.info("=" * 80)
    logger.info("ENABLE FAM PROTECT PRIVILEGED ON CERATOPS")
    logger.info("=" * 80)

    ceratops_ip = config.get_machine_ip(ceratops_machine, use_private=True)
    if not ceratops_ip:
        logger.error(f"âś— IP not found for machine: {ceratops_machine}")
        return False

    ssh_private_key = config.get_custom_variable('ssh_private_key')
    key_file = None
    tmp_key_path = None

    if ssh_private_key:
        tmp_fd, tmp_key_path = tempfile.mkstemp(prefix="itz_key_", suffix=".pem")
        try:
            os.write(tmp_fd, ssh_private_key.encode())
        finally:
            os.close(tmp_fd)
        os.chmod(tmp_key_path, 0o600)
        key_file = tmp_key_path
        logger.info("  Using SSH key from custom_variables")
    else:
        logger.info("  No SSH key in custom_variables â€” using agent/default keys")

    ini_file = r'C:\Program Files\IBM\Windows Fam Monitor\Bin\Guard_Tap.ini'

    try:
        ssh = SSHClient(
            host=ceratops_ip,
            username=ssh_username,
            key_file=key_file,
            port=2223,
            timeout=30
        )
        if not ssh.connect():
            logger.error(f"âś— Failed to connect to {ceratops_machine} ({ceratops_ip}) as {ssh_username}")
            return False

        try:
            steps = [
                (
                    f'powershell -Command "(Get-Content \'{ini_file}\') -replace \'FAM_PROTECT_PRIVILEGED=0\', \'FAM_PROTECT_PRIVILEGED=1\' | Set-Content \'{ini_file}\'"',
                    'set FAM_PROTECT_PRIVILEGED=1 in Guard_Tap.ini'
                ),
                (
                    'net stop "IBM Guardium FAM for Windows" && net start "IBM Guardium FAM for Windows"',
                    'restart IBM Guardium FAM for Windows'
                ),
            ]

            for cmd, desc in steps:
                logger.info(f"  âžś {desc}...")
                result = ssh.execute_command(cmd, timeout=60, print_output=verbose)
                if result['rc'] != 0:
                    logger.error(f"âś— Failed to {desc} (rc={result['rc']}): {result['stderr'].strip() or result['stdout'].strip()}")
                    return False
                logger.info(f"  âś“ {desc}")

            logger.info(f"âś“ FAM_PROTECT_PRIVILEGED=1 set and service restarted on {ceratops_machine}")
            return True

        finally:
            ssh.disconnect()

    except Exception as e:
        logger.error(f"âś— Unexpected error: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        if tmp_key_path and os.path.exists(tmp_key_path):
            os.remove(tmp_key_path)

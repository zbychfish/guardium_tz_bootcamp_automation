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



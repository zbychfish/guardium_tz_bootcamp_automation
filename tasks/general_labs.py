#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re
import time

from core.appliance_config_loader import ApplianceConfigLoader
from core.guardium_rest_api import create_guardium_api, import_definitions_files
from core.logger import get_logger
from core.utils import execute_local_command
from tasks.setup_appliances import install_policy_on_collector

logger = get_logger(__name__)


def _header(logger, title: str) -> None:
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)

def import_policies_reports_dashboard(config, logger, verbose: bool = True,
                                       cm_appliance: str = "cm",
                                       definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
                                       debug: bool = False, **kwargs) -> bool:

    _header(logger, "IMPORT POLICIES AND REPORTS DASHBOARD ON CM")

    success = import_definitions_files(
        config=config,
        logger=logger,
        appliance_name=cm_appliance,
        definition_files=[
            "exp_dashboard_policies_and_reports.sql",
            "exp_policy_policies_part1.sql",
        ],
        definitions_dir=definitions_dir,
        debug=debug
    )
    if success:
        logger.info("✓ Policies and Reports dashboard imported successfully")
    return success

def set_stap_firewall_flags_on_raptor(config, logger, verbose=True,
                                      cm_appliance="cm",
                                      installation_delay=10, **kwargs):

    _header(logger, "SET STAP FIREWALL FLAGS ON RAPTOR")

    stap_host = config.get_machine_ip('raptor', use_private=True)
    if not stap_host:
        logger.error("✗ Raptor IP not found in machines config")
        return False

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("✗ pwd not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    for param, value in [("STAP_FIREWALL_INSTALLED", "1"), ("STAP_FIREWALL_DEFAULT_STATE", "1")]:
        logger.info(f"➜ gim_client_params {param}={value} on {stap_host}")
        api.gim_client_params(client_ip=stap_host, param_name=param, param_value=value)

    logger.info("➜ gim_schedule_install on raptor")
    api.gim_schedule_install(client_ip=stap_host, date="now")
    logger.info(f"✓ Scheduled. Waiting {installation_delay}s before monitoring...")
    time.sleep(installation_delay)

    pending = ["initial"]
    check_count = 0
    while pending:
        check_count += 1
        logger.info(f"  Check #{check_count}: querying module status...")
        modules = api.gim_list_client_modules(client_ip=stap_host)
        if "ErrorCode" in modules or "ErrorMessage" in modules:
            logger.error(f"  ✗ API Error: {modules.get('ErrorCode')} {modules.get('ErrorMessage')}")
            return False
        entries = [e.strip() for e in re.split(r"#+\s*ENTRY\s+\d+\s*#+", modules.get("Message", "")) if e.strip()]
        result_mods = []
        for entry in entries:
            m_name  = re.search(r"NAME:\s+([A-Z0-9\-]+)", entry)
            m_state = re.search(r"STATE:\s+([A-Z\-]+)", entry)
            result_mods.append({"name": m_name.group(1) if m_name else "?", "state": m_state.group(1) if m_state else "?"})
        pending = [m for m in result_mods if m["state"] != "INSTALLED"]
        if pending:
            logger.info(f"  ⌛ {len(pending)} module(s) still installing: {[m['name'] for m in pending]}")
            time.sleep(30)
        else:
            logger.info("  ✓ All modules installed successfully!")

    logger.info("➜ guard-config-update --restart STAP")
    result = execute_local_command(
        "/opt/guardium/modules/STAP/current/guard-config-update --restart STAP",
        logger=logger, verbose=verbose
    )
    if result['rc'] != 0:
        logger.error(f"✗ Failed to restart STAP: {result['stderr']}")
        return False

    logger.info("✓ STAP firewall flags set, modules installed, agent restarted on raptor")
    return True

def configure_engine_on_raptor(config, logger, verbose=True,
                               cm_appliance="cm", collector_appliance="coll1",
                               compute_average=True, inspect_data=True,
                               log_records=True, record_empty=True, **kwargs):

    _header(logger, "CONFIGURE INSPECTION ENGINE ON RAPTOR")

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    collector_config = appliance_loader.get_appliance(collector_appliance)
    if not collector_config:
        logger.error(f"✗ Collector '{collector_appliance}' not found")
        return False
    collector_ip = collector_config.get('ip')
    if not collector_ip:
        logger.error(f"✗ Collector '{collector_appliance}' has no IP")
        return False

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("✗ pwd not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    logger.info(f"➜ engine_config api_target_host={collector_ip} compute_average={compute_average} inspect_data={inspect_data} log_records={log_records} record_empty={record_empty}")
    api.engine_config(
        compute_average=compute_average,
        inspect_data=inspect_data,
        log_records=log_records,
        record_empty=record_empty,
        api_target_host=collector_ip
    )
    logger.info("✓ Inspection Engine configured on raptor")
    return True

def run_dbtraffic_pgsql_on_raptor(config, logger, verbose=True, **kwargs):

    _header(logger, "RUN DBTRAFFIC PGSQL ON RAPTOR")

    base = "/opt/guardium_tz_bootcamp_automation/upload/guardium_notes_dbtraffic"
    for cmd in [
        f"bash -c 'cd {base} && source venv/bin/activate && guardium-notes-dbtraffic --config config/pgsql.yaml rebuild'",
        f"bash -c 'cd {base} && source venv/bin/activate && guardium-notes-dbtraffic --config config/pgsql.yaml run --duration 1 --speed fast'",
    ]:
        logger.info(f"➜ {cmd}")
        result = execute_local_command(cmd, logger=logger, verbose=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ Command failed: {result['stderr']}")
            return False
        logger.info("✓ done")

    logger.info("✓ dbtraffic pgsql completed on raptor")
    return True

def add_postgres_app_profile_member(config, logger, verbose=True,
                                    cm_appliance="cm", **kwargs):

    _header(logger, "ADD POSTGRES APP PROFILE MEMBER")

    raptor_ip = config.get_machine_ip('raptor', use_private=True)
    if not raptor_ip:
        logger.error("✗ Raptor IP not found in machines config")
        return False

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("✗ pwd not found in custom_variables")
        return False

    member = f"{raptor_ip}+POSTGRESQL CLIENT PROGRAM+APPUSER%+{raptor_ip}+%"
    group_desc = "Postgres application profiles"

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    logger.info(f"➜ create_group_member desc='{group_desc}' member={member}")
    api.create_group_member(desc=group_desc, member=member)
    logger.info(f"✓ Member added to group '{group_desc}'")
    return True

def install_app_data_access_policy(config, logger, verbose=True,
                                   cm_appliance="cm", collector_appliance="coll1",
                                   policy_name="Application data access control",
                                   debug=False, **kwargs):
    return install_policy_on_collector(
        config=config,
        logger=logger,
        verbose=verbose,
        cm_appliance=cm_appliance,
        collector_appliance=collector_appliance,
        policy_name=policy_name,
        debug=debug
    )

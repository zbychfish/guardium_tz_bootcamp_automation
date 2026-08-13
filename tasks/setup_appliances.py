#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import Dict, Any, Optional
from core.logger import get_logger
from core.appliance_client import ApplianceClient
from core.appliance_config_loader import ApplianceConfigLoader
from core.appliance_operations import (
    restart_appliance as core_restart_appliance,
    configure_aggr_settings,
    execute_on_appliances_async,
    reset_cli_password,
    set_shared_secret,
    configure_system_settings_consolidated,
    register_appliance,
    prepare_appliance_for_patching,
    prepare_appliance_for_patching as core_prepare,
    get_patch_installation_order,
    install_and_monitor_patches,
    install_patch_on_appliance as core_install,
    copy_single_file_to_appliance,
    prepare_log_guard_dir,
    _get_appliance_connection_params
)

logger = get_logger(__name__)


def _get_all_appliances(config, logger):
    all_appliances = ApplianceConfigLoader(config_loader=config).get_all_appliances()
    if not all_appliances:
        logger.error("No appliances found in machines_info.json")
    return all_appliances

def _header(logger, title: str) -> None:
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)

def _log_summary(logger, title: str, results: dict, errors: dict) -> None:
    _header(logger, title)
    success_count = sum(1 for s in results.values() if s)
    failed_count = len(results) - success_count
    logger.info(f"✓ Successful: {success_count}/{len(results)}")
    if failed_count > 0:
        logger.error(f"✗ Failed: {failed_count}/{len(results)}")
        for name, success in results.items():
            if not success:
                logger.error(f"  - {name}: {errors.get(name, 'Unknown error')}")

def reset_cli_password_all(
    config,
    logger,
    verbose: bool = True,
    cloudsupport_password: Optional[str] = None,
    cli_password: Optional[str] = None,
    debug: bool = True) -> bool:
    _header(logger, "RESET CLI PASSWORD ON ALL APPLIANCES")

    all_appliances = _get_all_appliances(config, logger)
    if not all_appliances:
        return False

    type_order = {'cm': 1, 'collector': 2, 'appnode': 3}
    sorted_appliances = sorted(
        all_appliances.items(),
        key=lambda x: type_order.get(x[1].get('type', '').lower(), 999)
    )
    appliance_names = [name for name, _ in sorted_appliances]

    logger.info(f"Found {len(appliance_names)} appliances")
    for name, cfg in sorted_appliances:
        logger.info(f"  - {name} ({cfg.get('type')})")

    results, errors = execute_on_appliances_async(
        appliances=appliance_names,
        operation_func=reset_cli_password,
        operation_name="reset_cli_password",
        logger=logger,
        config=config,
        cloudsupport_password=cloudsupport_password,
        cli_password=cli_password,
        debug=debug
    )

    _log_summary(logger, "RESET CLI PASSWORD SUMMARY", results, errors)
    return all(results.values())

def set_shared_secret_all(
    config,
    logger,
    verbose: bool = True,
    shared_secret: Optional[str] = None,
    debug: bool = True) -> bool:
    _header(logger, "SET SHARED SECRET ON ALL APPLIANCES")

    all_appliances = _get_all_appliances(config, logger)
    if not all_appliances:
        return False

    type_order = {'cm': 1, 'collector': 2, 'appnode': 3}
    sorted_appliances = sorted(
        all_appliances.items(),
        key=lambda x: type_order.get(x[1].get('type', '').lower(), 999)
    )
    appliance_names = [name for name, _ in sorted_appliances]

    logger.info(f"Found {len(appliance_names)} appliances")
    for name, cfg in sorted_appliances:
        logger.info(f"  - {name} ({cfg.get('type')})")

    results, errors = execute_on_appliances_async(
        appliances=appliance_names,
        operation_func=set_shared_secret,
        operation_name="set_shared_secret",
        logger=logger,
        config=config,
        debug=debug
    )

    _log_summary(logger, "SET SHARED SECRET SUMMARY", results, errors)
    return all(results.values())

def configure_aggr_settings_all(
    config,
    logger,
    verbose: bool = True,
    debug: bool = True) -> bool:
    _header(logger, "CONFIGURE AGGREGATION SETTINGS ON ALL APPLIANCES")

    all_appliances = _get_all_appliances(config, logger)
    if not all_appliances:
        return False

    type_order = {'cm': 1, 'collector': 2, 'appnode': 3}
    sorted_appliances = sorted(
        all_appliances.items(),
        key=lambda x: type_order.get(x[1].get('type', '').lower(), 999)
    )
    appliance_names = [name for name, _ in sorted_appliances]

    logger.info(f"Found {len(appliance_names)} appliances")
    for name, cfg in sorted_appliances:
        logger.info(f"  - {name} ({cfg.get('type')})")

    results, errors = execute_on_appliances_async(
        appliances=appliance_names,
        operation_func=configure_aggr_settings,
        operation_name="configure_aggr_settings",
        logger=logger,
        config=config,
        debug=debug
    )

    _log_summary(logger, "CONFIGURE AGGREGATION SETTINGS SUMMARY", results, errors)
    return all(results.values())

def import_definitions_on_cm(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm02",
    definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
    debug: bool = True) -> bool:
    from core.guardium_rest_api import import_definitions_files

    _header(logger, "IMPORT DEFINITIONS ON CM")

    definition_files = [
        "exp_default_policy.sql",
        "exp_dashboard_training.sql"
    ]

    logger.info(f"CM: {cm_appliance}, dir: {definitions_dir}")
    logger.info(f"Files: {', '.join(definition_files)}")

    success = import_definitions_files(
        config=config,
        logger=logger,
        appliance_name=cm_appliance,
        definition_files=definition_files,
        definitions_dir=definitions_dir,
        debug=debug
    )

    if success:
        logger.info("✓ All definitions imported successfully")

    return success

def install_policy_on_collector(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm02",
    collector_appliance: str = "coll2",
    policy_name: str = "Log Everything",
    max_outer_retries: int = 5,
    outer_retry_delay: int = 120,
    debug: bool = True) -> bool:
    import time
    import traceback
    from core.guardium_rest_api import create_guardium_api

    _header(logger, "INSTALL POLICY ON COLLECTOR")

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    collector_config = appliance_loader.get_appliance(collector_appliance)

    if not collector_config:
        logger.error(f"Collector '{collector_appliance}' not found in machines_info.json")
        return False

    collector_ip = collector_config.get('ip')
    if not collector_ip:
        logger.error(f"No IP configured for collector '{collector_appliance}'")
        return False

    logger.info(f"CM: {cm_appliance}, collector: {collector_appliance} ({collector_ip}), policy: {policy_name}")

    try:
        api = create_guardium_api(config, logger, appliance_name=cm_appliance)

        demo_password = config.get_custom_variable('pwd')
        if not demo_password:
            logger.error("pwd not found in custom_variables")
            return False

        logger.info("➜ get_token demo")
        api.get_token(username='demo', password=demo_password)
        logger.info("✓ Authenticated")

        error_code = '999'
        error_message = 'Unknown error'

        for outer_attempt in range(1, max_outer_retries + 1):
            logger.info(f"➜ install_policy attempt {outer_attempt}/{max_outer_retries}")

            result = api.install_policy(
                policy=policy_name,
                api_target_host=collector_ip,
                max_retries=3,
                retry_delay=60,
                debug=debug
            )

            error_code = result.get('ErrorCode') or result.get('ID', '0')
            error_message = result.get('ErrorMessage') or result.get('Message', '')

            if error_code == '0':
                logger.info(f"✓ Policy '{policy_name}' installed on {collector_appliance}")
                return True

            if error_code == '15' and outer_attempt < max_outer_retries:
                logger.warning(f"⚠ target offline, waiting {outer_retry_delay}s (attempt {outer_attempt}/{max_outer_retries})")
                time.sleep(outer_retry_delay)
                continue

            logger.error(f"✗ install_policy failed after {outer_attempt} attempts: Code={error_code}, Message={error_message}")
            return False

        logger.error(f"✗ install_policy: Code={error_code}, Message={error_message}")
        return False

    except Exception as e:
        logger.error(f"✗ {e}")
        logger.error(traceback.format_exc())
        return False

def initial_collector_settings(
    config,
    logger,
    verbose: bool = True,
    collector_name: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = False) -> bool:
    import traceback

    if not collector_name:
        logger.error("collector_name is required")
        return False

    _header(logger, f"INITIAL COLLECTOR SETTINGS: {collector_name}")

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    collector_config = appliance_loader.get_appliance(collector_name)

    if not collector_config:
        logger.error(f"[{collector_name}] not found in machines_info.json")
        return False

    if collector_config.get('type') != 'collector':
        logger.error(f"[{collector_name}] not a collector (type: {collector_config.get('type')})")
        return False

    params = _get_appliance_connection_params(config, logger, collector_name, user, password, prompt_regex)
    if not params:
        return False

    appliance = ApplianceClient(
        host=params['host'], user=params['user'], password=params['password'],
        prompt_regex=params['prompt_regex'], initial_pattern=None,
        timeout=120, strip_ansi=True, debug=debug
    )

    logger.info(f"[{collector_name}] ➜ connect {params['host']}")
    if not appliance.connect():
        logger.error(f"[{collector_name}] failed to connect")
        return False
    logger.info(f"[{collector_name}] ✓ connected")

    try:
        logger.info(f"[{collector_name}] ➜ grdapi disable_purge")
        appliance.execute_command("grdapi disable_purge")
        logger.info(f"[{collector_name}] ✓ purge disabled")

        logger.info(f"[{collector_name}] ➜ show system clock all")
        output = appliance.execute_command("show system clock all")
        timezone = output.strip().splitlines()[-1] if output.strip() else ""
        logger.info(f"[{collector_name}] current timezone: {timezone}")

        if timezone != "Europe/Warsaw":
            logger.info(f"[{collector_name}] ➜ store system clock timezone Europe/Warsaw")
            appliance.execute_command_with_confirmation(
                command="store system clock timezone Europe/Warsaw",
                response="y",
                confirmation_pattern=r"Do you want to proceed\?\s*\(y/n\)\s*"
            )
            output = appliance.execute_command("show system clock all")
            new_timezone = output.strip().splitlines()[-1] if output.strip() else ""
            logger.info(f"[{collector_name}] ✓ timezone={new_timezone}")
        else:
            logger.info(f"[{collector_name}] ✓ timezone already Europe/Warsaw")

        logger.info(f"[{collector_name}] ➜ store system time_server hostname ...")
        appliance.execute_command(
            "store system time_server hostname 0.pool.ntp.org 1.pool.ntp.org 2.pool.ntp.org"
        )
        logger.info(f"[{collector_name}] ✓ ntp configured")

        logger.info(f"[{collector_name}] ➜ store system time_server state on")
        appliance.execute_command("store system time_server state on")
        logger.info(f"[{collector_name}] ✓ time sync enabled")

        return True

    except Exception as e:
        logger.error(f"[{collector_name}] ✗ {e}")
        logger.error(traceback.format_exc())
        return False

    finally:
        appliance.disconnect()

def create_oauth_client(
    config,
    logger,
    verbose: bool = True,
    appliance_name: str = "cm01",
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    client_id: str = "BOOTCAMP",
    debug: bool = False) -> bool:
    import json
    import traceback

    _header(logger, f"CREATE OAUTH CLIENT: {client_id}")

    params = _get_appliance_connection_params(config, logger, appliance_name, user, password, prompt_regex)
    if not params:
        return False

    client = ApplianceClient(
        host=params['host'], user=params['user'], password=params['password'],
        prompt_regex=params['prompt_regex'], timeout=120, debug=debug
    )

    try:
        logger.info(f"➜ connect {appliance_name} ({params['host']})")
        if not client.connect():
            logger.error(f"[{appliance_name}] failed to connect")
            return False
        logger.info(f"[{appliance_name}] ✓ connected")

        logger.info("➜ grdapi list_oauth_clients")
        result = client.execute_command("grdapi list_oauth_clients")
        logger.info(result)

        if f"Client Id: {client_id}" in result:
            logger.info(f"➜ grdapi delete_oauth_clients client_id={client_id}")
            client.execute_command(f"grdapi delete_oauth_clients client_id={client_id}")
            logger.info(f"✓ Deleted existing client {client_id}")

        logger.info(f'➜ grdapi register_oauth_client client_id={client_id} grant_types="password"')
        result = client.execute_command(f'grdapi register_oauth_client client_id={client_id} grant_types="password"')

        client_secret = None
        for line in result.splitlines():
            line = line.strip()
            if line.startswith('{') and line.endswith('}'):
                try:
                    data = json.loads(line)
                    client_secret = data.get('client_secret')
                    if client_secret:
                        break
                except json.JSONDecodeError:
                    pass

        if not client_secret:
            logger.error(f"Failed to extract client_secret from response: {result}")
            return False

        logger.info(f"✓ OAuth client created: {client_id} / secret={client_secret[:10]}...")

        secret_file = config.config_file.parent.parent / ".client_secret"
        try:
            with open(secret_file, 'w') as f:
                f.write(client_secret)
            logger.info(f"✓ Secret saved to {secret_file}")
        except Exception as e:
            logger.error(f"Failed to save client_secret: {e}")
            return False

        return True

    except Exception as e:
        logger.error(f"✗ {e}")
        logger.error(traceback.format_exc())
        return False

    finally:
        client.disconnect()

def create_demo_user(
    config,
    logger,
    verbose: bool = True,
    appliance_name: str = "cm01",
    accessmgr_password: Optional[str] = None,
    demo_password: Optional[str] = None) -> bool:
    import traceback
    from core.guardium_rest_api import create_guardium_api

    _header(logger, "CREATE DEMO USER")

    if not accessmgr_password:
        accessmgr_password = config.get_custom_variable('cli_pwd')
        if not accessmgr_password:
            logger.error("cli_pwd not found in custom_variables")
            return False

    if not demo_password:
        demo_password = config.get_custom_variable('pwd')
        if not demo_password:
            logger.error("pwd not found in custom_variables")
            return False

    try:
        api = create_guardium_api(config, logger, appliance_name)

        logger.info("➜ get_token accessmgr")
        api.get_token(username='accessmgr', password=accessmgr_password)
        logger.info("✓ Token obtained")

        logger.info("➜ get_users")
        users = api.get_users()
        demo_exists = any(u.get('user_name') == 'demo' for u in users)

        if not demo_exists:
            logger.info("➜ create_user demo")
            api.create_user(
                username='demo',
                password=demo_password,
                confirm_password=demo_password,
                first_name='User',
                last_name='Demo',
                email='demo@demo.training',
                country='PL',
                disabled=False,
                disable_pwd_expiry=True
            )
            logger.info("✓ demo user created")

            logger.info("➜ set_user_roles demo admin,cli,user,vulnerability-assess,fam")
            api.set_user_roles(username='demo', roles='admin,cli,user,vulnerability-assess,fam')
            logger.info("✓ Roles assigned")
        else:
            logger.info("ℹ demo user already exists")

        logger.info("➜ update_user guardium disabled=True")
        api.update_user(username='guardium', disabled=True)
        logger.info("✓ guardium disabled")

        for cli_num in range(2, 10):
            username = f"guardcli{cli_num}"
            logger.info(f"➜ update_user {username} disabled=True")
            api.update_user(username=username, disabled=True)
            logger.info(f"✓ {username} disabled")

        logger.info("➜ get_token demo (verify)")
        api.get_token(username='demo', password=demo_password)
        logger.info("✓ demo login verified")

        return True

    except Exception as e:
        logger.error(f"✗ {e}")
        logger.error(traceback.format_exc())
        return False

def set_unit_type_manager(
    config,
    logger,
    verbose: bool = True,
    appliance_name: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    import traceback

    if not appliance_name:
        logger.error("appliance_name is required")
        return False

    _header(logger, f"SET UNIT TYPE MANAGER: {appliance_name}")

    params = _get_appliance_connection_params(config, logger, appliance_name, user, password, prompt_regex)
    if not params:
        return False

    try:
        client = ApplianceClient(
            host=params['host'], user=params['user'], password=params['password'],
            prompt_regex=params['prompt_regex'], initial_pattern=None,
            timeout=300, strip_ansi=True, debug=debug
        )

        if not client.connect():
            logger.error(f"[{appliance_name}] failed to connect")
            return False

        logger.info(f"[{appliance_name}] ➜ store unit type manager")
        output = client.execute_command("store unit type manager", timeout=300)
        if debug and output:
            logger.info(f"[{appliance_name}] {output}")
        client.disconnect()

        if "success: true" not in output:
            logger.error(f"[{appliance_name}] ✗ missing 'success: true' in output")
            return False
        if "GUI restart succeeded" not in output:
            logger.error(f"[{appliance_name}] ✗ missing 'GUI restart succeeded' in output")
            return False

        logger.info(f"[{appliance_name}] ✓ unit type=manager, GUI restart succeeded")
        return True

    except Exception as e:
        logger.error(f"[{appliance_name}] ✗ {e}")
        logger.error(traceback.format_exc())
        return False

def restart_appliance_all(
    config,
    logger,
    verbose: bool = True,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True,
    wait_for_availability: bool = True,
    retry_interval: int = 10,
    max_retries: int = 60
) -> bool:
    _header(logger, "RESTART ALL APPLIANCES")

    all_appliances = _get_all_appliances(config, logger)
    if not all_appliances:
        return False

    cms        = [n for n, c in all_appliances.items() if c.get('type', '').lower() == 'cm']
    collectors = [n for n, c in all_appliances.items() if c.get('type', '').lower() == 'collector']
    appnodes   = [n for n, c in all_appliances.items() if c.get('type', '').lower() == 'appnode']
    others     = [n for n, c in all_appliances.items() if c.get('type', '').lower() not in ('cm', 'collector', 'appnode')]
    ordered_appliances = cms + collectors + appnodes + others

    logger.info(f"Found {len(ordered_appliances)} appliances:")
    logger.info(f"  - CMs: {len(cms)} ({', '.join(cms) if cms else 'none'})")
    logger.info(f"  - Collectors: {len(collectors)} ({', '.join(collectors) if collectors else 'none'})")
    logger.info(f"  - AppNodes: {len(appnodes)} ({', '.join(appnodes) if appnodes else 'none'})")
    if others:
        logger.info(f"  - Others: {len(others)} ({', '.join(others)})")

    results, errors = execute_on_appliances_async(
        appliances=ordered_appliances,
        operation_func=core_restart_appliance,
        operation_name="restart",
        logger=logger,
        config=config,
        debug=debug,
        wait_for_availability=wait_for_availability,
        retry_interval=retry_interval,
        max_retries=max_retries
    )

    _log_summary(logger, "RESTART SUMMARY", results, errors)
    return all(results.values())

def configure_system_settings_all(
    config,
    logger,
    verbose: bool = True,
    hostname: Optional[str] = None,
    domain: Optional[str] = None,
    ip_address: Optional[str] = None,
    prefix: str = "/24",
    timezone: Optional[str] = None,
    ntp_servers: Optional[list] = None,
    configure_hosts: bool = True,
    gid: Optional[int] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True) -> bool:
    _header(logger, "CONFIGURE ALL SYSTEM SETTINGS (CONSOLIDATED)")

    all_appliances = _get_all_appliances(config, logger)
    if not all_appliances:
        return False

    cms        = [n for n, c in all_appliances.items() if c.get('type', '').lower() == 'cm']
    collectors = [n for n, c in all_appliances.items() if c.get('type', '').lower() == 'collector']
    appnodes   = [n for n, c in all_appliances.items() if c.get('type', '').lower() == 'appnode']
    others     = [n for n, c in all_appliances.items() if c.get('type', '').lower() not in ('cm', 'collector', 'appnode')]
    ordered_appliances = cms + collectors + appnodes + others

    logger.info(f"Found {len(ordered_appliances)} appliances:")
    logger.info(f"  - CMs: {len(cms)} ({', '.join(cms) if cms else 'none'})")
    logger.info(f"  - Collectors: {len(collectors)} ({', '.join(collectors) if collectors else 'none'})")
    logger.info(f"  - AppNodes: {len(appnodes)} ({', '.join(appnodes) if appnodes else 'none'})")
    if others:
        logger.info(f"  - Others: {len(others)} ({', '.join(others)})")

    results, errors = execute_on_appliances_async(
        appliances=ordered_appliances,
        operation_func=configure_system_settings_consolidated,
        operation_name="configure_system_settings_consolidated",
        logger=logger,
        config=config,
        hostname=hostname,
        domain=domain,
        ip_address=ip_address,
        prefix=prefix,
        timezone=timezone,
        ntp_servers=ntp_servers,
        configure_hosts=configure_hosts,
        gid=gid,
        user=user,
        password=password,
        prompt_regex=prompt_regex,
        debug=debug
    )

    _log_summary(logger, "CONSOLIDATED CONFIGURATION SUMMARY", results, errors)
    return all(results.values())

def register_appliances_all(
    config,
    logger,
    verbose: bool = True,
    cm_ip: Optional[str] = None,
    cm_port: int = 8443,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True,
    timeout: int = 600,
    registration_check_delay: int = 120
) -> bool:
    _header(logger, "REGISTER APPLIANCES ON CENTRAL MANAGER")

    all_appliances = _get_all_appliances(config, logger)
    if not all_appliances:
        return False

    appliances_to_register = {
        name: cfg for name, cfg in all_appliances.items()
        if cfg.get('type', '').lower() in ('collector', 'appnode')
    }

    if not appliances_to_register:
        logger.warning("No Collectors or AppNodes found to register")
        return True

    type_order = {'collector': 1, 'appnode': 2}
    sorted_appliances = sorted(
        appliances_to_register.items(),
        key=lambda x: type_order.get(x[1].get('type', '').lower(), 999)
    )

    logger.info(f"Found {len(sorted_appliances)} appliances to register")
    for name, cfg in sorted_appliances:
        logger.info(f"  - {name} ({cfg.get('type')})")

    appliance_names = [name for name, _ in sorted_appliances]

    results, errors = execute_on_appliances_async(
        appliances=appliance_names,
        operation_func=register_appliance,
        operation_name="register_appliance",
        logger=logger,
        config=config,
        cm_ip=cm_ip,
        cm_port=cm_port,
        user=user,
        password=password,
        prompt_regex=prompt_regex,
        debug=debug,
        timeout=timeout,
        registration_check_delay=registration_check_delay
    )

    _log_summary(logger, "APPLIANCE REGISTRATION SUMMARY", results, errors)
    return all(results.values())

def prepare_appliances_for_patching_all(
    config,
    logger,
    verbose: bool = True,
    patches_source_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/patches/",
    cloudsupport_password: Optional[str] = None,
    debug: bool = True
) -> bool:
    _header(logger, "PREPARE ALL APPLIANCES FOR PATCHING")

    all_appliances = _get_all_appliances(config, logger)
    if not all_appliances:
        return False

    type_order = {'cm': 1, 'collector': 2, 'appnode': 3}
    sorted_appliances = sorted(
        all_appliances.items(),
        key=lambda x: type_order.get(x[1].get('type', '').lower(), 999)
    )
    appliance_names = [name for name, _ in sorted_appliances]

    logger.info(f"Found {len(appliance_names)} appliances")
    for name, cfg in sorted_appliances:
        logger.info(f"  - {name} ({cfg.get('type')})")

    results, errors = execute_on_appliances_async(
        appliances=appliance_names,
        operation_func=prepare_appliance_for_patching,
        operation_name="prepare_appliance_for_patching",
        logger=logger,
        config=config,
        patches_source_dir=patches_source_dir,
        cloudsupport_password=cloudsupport_password,
        debug=debug
    )

    _log_summary(logger, "PREPARE FOR PATCHING SUMMARY", results, errors)
    return all(results.values())

def install_and_monitor_patches_all(
    config,
    logger,
    verbose: bool = True,
    patch_selection: Optional[str] = None,
    reinstall_answer: str = "y",
    check_interval: int = 60,
    max_checks: int = 60,
    user: Optional[str] = None,
    password: Optional[str] = None,
    debug: bool = True
) -> bool:
    _header(logger, "INSTALL AND MONITOR PATCHES ON ALL APPLIANCES")

    all_appliances = _get_all_appliances(config, logger)
    if not all_appliances:
        return False

    if not patch_selection:
        cm_appliances = {n: c for n, c in all_appliances.items() if c.get('type', '').lower() == 'cm'}
        if not cm_appliances:
            logger.error("No Central Manager found in machines_info.json")
            return False
        cm_name = next(iter(cm_appliances))
        logger.info(f"➜ get_patch_installation_order from {cm_name}")
        patch_selection = get_patch_installation_order(
            config=config, logger=logger, appliance_name=cm_name,
            user=user, password=password, debug=debug
        )
        if not patch_selection:
            logger.error("Failed to determine patch installation order from CM")
            return False
        logger.info(f"✓ patch_selection={patch_selection}")
    else:
        logger.info(f"patch_selection={patch_selection}")

    appliance_names = list(all_appliances.keys())
    logger.info(f"Found {len(appliance_names)} appliances")
    for name in appliance_names:
        logger.info(f"  - {name} ({all_appliances[name].get('type', 'unknown')})")

    results, errors = execute_on_appliances_async(
        appliances=appliance_names,
        operation_func=install_and_monitor_patches,
        operation_name="install_and_monitor_patches",
        logger=logger,
        config=config,
        patch_selection=patch_selection,
        reinstall_answer=reinstall_answer,
        check_interval=check_interval,
        max_checks=max_checks,
        user=user,
        password=password,
        debug=debug
    )

    _log_summary(logger, "PATCH INSTALLATION SUMMARY", results, errors)
    return all(results.values())



def prepare_appliance_for_patching_single(
    config,
    logger,
    verbose: bool = True,
    appliance_name: Optional[str] = None,
    patches_source_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/patches/",
    cloudsupport_password: Optional[str] = None,
    debug: bool = True
) -> bool:
    if not appliance_name:
        logger.error("appliance_name is required")
        return False

    return core_prepare(
        config=config,
        logger=logger,
        appliance_name=appliance_name,
        patches_source_dir=patches_source_dir,
        cloudsupport_password=cloudsupport_password,
        debug=debug
    )


def install_patch_on_appliance_single(
    config,
    logger,
    verbose: bool = True,
    appliance_name: Optional[str] = None,
    patch_selection: Optional[str] = None,
    patch_filename: Optional[str] = None,
    reinstall_answer: str = "y",
    user: Optional[str] = None,
    password: Optional[str] = None,
    debug: bool = True
) -> bool:
    import os

    if not appliance_name:
        logger.error("appliance_name is required")
        return False

    if not patch_selection and not patch_filename:
        logger.error("patch_selection or patch_filename is required")
        return False

    if not patch_selection and patch_filename:
        import paramiko

        params = _get_appliance_connection_params(config, logger, appliance_name)
        if not params:
            return False

        host = params['host']
        cloudsupport_pwd = config.get_custom_variable('cloudsupport_pwd')
        if not cloudsupport_pwd:
            logger.error("cloudsupport_pwd not found in custom_variables")
            return False

        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(host, username='cloudsupport', password=cloudsupport_pwd, timeout=30)
            _, stdout, _ = ssh.exec_command("sudo ls /var/IBM/Guardium/log/patches/*.sig 2>/dev/null")
            raw = stdout.read().decode()
            ssh.close()
        except Exception as e:
            logger.error(f"Failed to list patches via SSH: {e}")
            return False

        sig_name = os.path.basename(patch_filename)
        entries = sorted([os.path.basename(p.strip()) for p in raw.splitlines() if p.strip()])
        logger.info(f"Patches on appliance (sorted): {entries}")

        try:
            patch_selection = str(entries.index(sig_name) + 1)
            logger.info(f"Auto-detected patch_selection={patch_selection} for '{sig_name}'")
        except ValueError:
            logger.error(f"Patch '{sig_name}' not found in list: {entries}")
            return False

    return core_install(
        config=config,
        logger=logger,
        appliance_name=appliance_name,
        patch_selection=patch_selection,
        reinstall_answer=reinstall_answer,
        user=user,
        password=password,
        debug=debug
    )



def copy_single_file_to_appliance_task(
    config,
    logger,
    verbose: bool = True,
    appliance_name: Optional[str] = None,
    source_file_path: Optional[str] = None,
    target_dir: str = "/var/IBM/Guardium/log/patches/",
    owner: str = "tomcat:tomcat",
    cloudsupport_password: Optional[str] = None,
    debug: bool = True
) -> bool:
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    if not source_file_path:
        logger.error("source_file_path is required")
        return False
    
    return copy_single_file_to_appliance(
        config=config,
        logger=logger,
        appliance_name=appliance_name,
        source_file_path=source_file_path,
        target_dir=target_dir,
        owner=owner,
        cloudsupport_password=cloudsupport_password,
        debug=debug
    )


def prepare_log_guard_dir_all(
    config,
    logger,
    verbose: bool = True,
    cloudsupport_password: Optional[str] = None,
    debug: bool = False) -> bool:
    all_appliances = _get_all_appliances(config, logger)
    if not all_appliances:
        return False
    results, errors = execute_on_appliances_async(
        appliances=list(all_appliances.keys()), operation_func=prepare_log_guard_dir,
        operation_name="prepare_log_guard_dir", logger=logger,
        config=config, cloudsupport_password=cloudsupport_password, debug=debug
    )
    return all(results.values())

# Made with Bob

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Appliance Operations - Reusable functions for Guardium appliance operations
"""

import time
import random
import re
from typing import Optional, List
from .appliance_client import ApplianceClient
from .appliance_config_loader import ApplianceConfigLoader
import concurrent.futures
from typing import Callable, Dict, Any, Tuple


def execute_on_appliances_async(
    appliances: List[str],
    operation_func: Callable,
    operation_name: str,
    logger,
    **operation_kwargs) -> Tuple[Dict[str, bool], Dict[str, str]]:
    
    if not appliances:
        logger.warning("No appliances provided for async execution")
        return {}, {}

    max_workers = min(len(appliances), 20)
    total = len(appliances)

    logger.info(f"➜ {operation_name} — {total} appliances, {max_workers} parallel")
    for a in appliances:
        logger.info(f"  ○ {a}")

    results = {}
    errors = {}
    completed_count = 0

    def execute_single(appliance_name: str) -> Tuple[str, bool, Optional[str], float]:
        t0 = time.time()
        try:
            success = operation_func(
                appliance_name=appliance_name,
                logger=logger,
                **operation_kwargs
            )
            return appliance_name, success, None, time.time() - t0
        except Exception as e:
            return appliance_name, False, str(e), time.time() - t0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_appliance = {
            executor.submit(execute_single, appliance): appliance
            for appliance in appliances
        }
        for future in concurrent.futures.as_completed(future_to_appliance):
            appliance_name, success, error, elapsed = future.result()
            results[appliance_name] = success
            if error:
                errors[appliance_name] = error
            completed_count += 1
            elapsed_str = f"{elapsed:.0f}s" if elapsed < 60 else f"{int(elapsed)//60}m{int(elapsed)%60:02d}s"
            if success:
                logger.info(f"  ✓ [{completed_count}/{total}] {appliance_name} ({elapsed_str})")
            else:
                msg = f" — {error}" if error else ""
                logger.error(f"  ✗ [{completed_count}/{total}] {appliance_name} ({elapsed_str}){msg}")

    return results, errors

def _get_appliance_connection_params(
    config,
    logger,
    appliance_name: str,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None) -> Optional[Dict[str, Any]]:
    
    if not appliance_name:
        logger.error("appliance_name is required")
        return None
    
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    appliance_config = appliance_loader.get_appliance(appliance_name)
    
    if not appliance_config:
        logger.error(f"Appliance '{appliance_name}' not found in machines_info.json")
        available = list(appliance_loader.get_all_appliances().keys())
        logger.error(f"Available appliances: {', '.join(available)}")
        return None
    
    appliance_type = appliance_config.get('type')
    host = appliance_config.get('ip')
    
    if not host:
        logger.error(f"No IP address configured for appliance '{appliance_name}'")
        return None
    
    # Get user from config if not provided
    if not user:
        user = appliance_loader.get_default_user(appliance_type) if appliance_type else "cli"
    
    # Validate user is not None
    if not user:
        logger.error(f"No user configured for appliance '{appliance_name}' (type: {appliance_type})")
        return None
    
    # Get password from custom_variables if not provided
    if not password:
        password = config.get_custom_variable('cli_pwd')
    if not password:
        logger.error("Password not provided and cli_pwd not found in custom_variables")
        return None
    
    # Get prompt regex from config if not provided
    if not prompt_regex and appliance_type:
        prompt_regex = appliance_loader.get_default_prompt(appliance_type, configured=False)
    
    if not prompt_regex:
        logger.error(f"No prompt_regex provided and no default found for type '{appliance_type}'")
        return None
    
    return {
        'appliance_config': appliance_config,
        'host': host,
        'user': user,
        'password': password,
        'prompt_regex': prompt_regex,
        'appliance_type': appliance_type
    }

def restart_appliance(
    config,
    logger,
    appliance_name: str,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True,
    wait_for_availability: bool = True,
    retry_interval: int = 10,
    max_retries: int = 60,
    mysql_busy_retries: int = 5,
    mysql_busy_wait: int = 60) -> bool:
    import traceback

    params = _get_appliance_connection_params(config, logger, appliance_name, user, password, prompt_regex)
    if not params:
        return False

    host = params['host']

    for mysql_attempt in range(1, mysql_busy_retries + 1):
        try:
            client = ApplianceClient(
                host=host, user=params['user'], password=params['password'],
                prompt_regex=params['prompt_regex'], initial_pattern=None,
                timeout=60, strip_ansi=True, debug=debug
            )

            if not client.connect():
                logger.error(f"[{appliance_name}] failed to connect")
                return False

            if mysql_attempt > 1:
                logger.info(f"[{appliance_name}] ➜ restart system (attempt {mysql_attempt}/{mysql_busy_retries})")
            else:
                logger.info(f"[{appliance_name}] ➜ restart system")
            result = client.execute_restart_with_check()
            client.disconnect()

            if "System is restarting" in result:
                logger.info(f"[{appliance_name}] ✓ restart initiated")

                if not wait_for_availability:
                    return True

                total_timeout = max_retries * retry_interval
                logger.info(f"[{appliance_name}] ⌛ waiting for online (timeout ~{total_timeout}s)")
                start_time = time.time()

                for retry_count in range(1, max_retries + 1):
                    try:
                        test_client = ApplianceClient(
                            host=host, user=params['user'], password=params['password'],
                            prompt_regex=params['prompt_regex'], initial_pattern=None,
                            timeout=30, strip_ansi=True, debug=False
                        )
                        if test_client.connect():
                            test_client.disconnect()
                            elapsed = int(time.time() - start_time)
                            logger.info(f"[{appliance_name}] ✓ back online ({elapsed}s, {retry_count} attempts)")
                            return True
                    except Exception:
                        pass
                    logger.debug(f"[{appliance_name}] attempt {retry_count}/{max_retries}, waiting {retry_interval}s...")
                    time.sleep(retry_interval)

                elapsed = int(time.time() - start_time)
                logger.error(f"[{appliance_name}] ✗ timeout ({elapsed}s, {max_retries} attempts)")
                return False

            elif "MySQL is busy" in result:
                if mysql_attempt < mysql_busy_retries:
                    logger.warning(f"[{appliance_name}] ⚠ MySQL busy (attempt {mysql_attempt}/{mysql_busy_retries}), waiting {mysql_busy_wait}s...")
                    time.sleep(mysql_busy_wait)
                    continue
                else:
                    logger.error(f"[{appliance_name}] ✗ MySQL busy after {mysql_busy_retries} attempts")
                    return False
            else:
                logger.error(f"[{appliance_name}] ✗ unexpected result: {result}")
                return False

        except Exception as e:
            logger.error(f"[{appliance_name}] ✗ {e}")
            logger.error(traceback.format_exc())
            return False

    logger.error(f"[{appliance_name}] ✗ restart failed after all retries")
    return False

def setup_appnode(
    config,
    logger,
    appliance_name: str,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True,
    retry_interval: int = 60,
    max_retries: int = 10) -> bool:
    import traceback

    params = _get_appliance_connection_params(config, logger, appliance_name, user, password, prompt_regex)
    if not params:
        return False

    host = params['host']

    try:
        client = ApplianceClient(
            host=host, user=params['user'], password=params['password'],
            prompt_regex=params['prompt_regex'], initial_pattern=None,
            timeout=60, strip_ansi=True, debug=debug
        )

        if not client.connect():
            logger.error(f"[{appliance_name}] failed to connect")
            return False

        logger.info(f"[{appliance_name}] ➜ store unit type app-node")
        try:
            client.execute_command_with_confirmation(
                command="store unit type app-node",
                confirmation_pattern=r"Are you sure you want to proceed\s*\(y/n\)\?",
                response="y",
                confirm_idle=0.2
            )
            logger.info(f"[{appliance_name}] ✓ command sent, system restarting")
        except RuntimeError as e:
            if "Channel closed" in str(e):
                logger.info(f"[{appliance_name}] ✓ system restarting (connection closed)")
            else:
                raise

        try:
            client.disconnect()
        except Exception:
            pass

        logger.info(f"[{appliance_name}] ⌛ waiting online (max {max_retries * retry_interval}s)")
        start_time = time.time()

        for retry_count in range(1, max_retries + 1):
            time.sleep(retry_interval)
            try:
                test_client = ApplianceClient(
                    host=host, user=params['user'], password=params['password'],
                    prompt_regex=params['prompt_regex'], initial_pattern=None,
                    timeout=30, strip_ansi=True, debug=False
                )
                if test_client.connect():
                    elapsed = int(time.time() - start_time)
                    logger.info(f"[{appliance_name}] ✓ back online ({elapsed}s, {retry_count} attempts)")
                    logger.info(f"[{appliance_name}] ➜ show unit type")
                    verify_result = test_client.execute_command("show unit type")
                    test_client.disconnect()
                    if "App-Node" in verify_result or "App_Node" in verify_result:
                        logger.info(f"[{appliance_name}] ✓ unit type=App-Node")
                        return True
                    else:
                        logger.error(f"[{appliance_name}] ✗ unexpected unit type: {verify_result.strip()}")
                        return False
            except Exception:
                pass

        elapsed = int(time.time() - start_time)
        logger.error(f"[{appliance_name}] ✗ timeout ({elapsed}s, {max_retries} attempts)")
        return False

    except Exception as e:
        logger.error(f"[{appliance_name}] ✗ {e}")
        logger.error(traceback.format_exc())
        return False

def setup_kafka_node(
    config,
    logger,
    appliance_name: str,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True,
    retry_interval: int = 60,
    max_retries: int = 10) -> bool:
    import traceback

    params = _get_appliance_connection_params(config, logger, appliance_name, user, password, prompt_regex)
    if not params:
        return False

    host = params['host']

    try:
        client = ApplianceClient(
            host=host, user=params['user'], password=params['password'],
            prompt_regex=params['prompt_regex'], initial_pattern=None,
            timeout=60, strip_ansi=True, debug=debug
        )

        if not client.connect():
            logger.error(f"[{appliance_name}] failed to connect")
            return False

        logger.info(f"[{appliance_name}] ➜ store unit type kafka-node")
        try:
            client.execute_command_with_confirmation(
                command="store unit type kafka-node",
                confirmation_pattern=r"Are you sure you want to proceed\s*\(y/n\)\?",
                response="y",
                confirm_idle=0.2
            )
            logger.info(f"[{appliance_name}] ✓ command sent, system restarting")
        except RuntimeError as e:
            if "Channel closed" in str(e):
                logger.info(f"[{appliance_name}] ✓ system restarting (connection closed)")
            else:
                raise

        try:
            client.disconnect()
        except Exception:
            pass

        logger.info(f"[{appliance_name}] ⌛ waiting online (max {max_retries * retry_interval}s)")
        start_time = time.time()

        for retry_count in range(1, max_retries + 1):
            time.sleep(retry_interval)
            try:
                test_client = ApplianceClient(
                    host=host, user=params['user'], password=params['password'],
                    prompt_regex=params['prompt_regex'], initial_pattern=None,
                    timeout=30, strip_ansi=True, debug=False
                )
                if test_client.connect():
                    elapsed = int(time.time() - start_time)
                    logger.info(f"[{appliance_name}] ✓ back online ({elapsed}s, {retry_count} attempts)")
                    logger.info(f"[{appliance_name}] ➜ show unit type")
                    verify_result = test_client.execute_command("show unit type")
                    test_client.disconnect()
                    if "Kafka" in verify_result:
                        logger.info(f"[{appliance_name}] ✓ unit type=Kafka-Node")
                        return True
                    else:
                        logger.error(f"[{appliance_name}] ✗ unexpected unit type: {verify_result.strip()}")
                        return False
            except Exception:
                pass

        elapsed = int(time.time() - start_time)
        logger.error(f"[{appliance_name}] ✗ timeout ({elapsed}s, {max_retries} attempts)")
        return False

    except Exception as e:
        logger.error(f"[{appliance_name}] ✗ {e}")
        logger.error(traceback.format_exc())
        return False

def configure_aggr_settings(
    config,
    logger,
    appliance_name: str,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True) -> bool:
    import traceback
    from .appliance_client import strip_ansi

    params = _get_appliance_connection_params(config, logger, appliance_name, user, password, prompt_regex)
    if not params:
        return False

    appliance_type = params['appliance_type']

    try:
        client = ApplianceClient(
            host=params['host'],
            user=params['user'],
            password=params['password'],
            prompt_regex=params['prompt_regex'],
            initial_pattern=None,
            timeout=60,
            strip_ansi=True,
            debug=debug
        )

        if not client.connect():
            logger.error(f"[{appliance_name}] failed to connect")
            return False

        logger.info(f"[{appliance_name}] ➜ store run_cleanup_orphans_daily off")
        result1 = client.execute_command("store run_cleanup_orphans_daily off")
        if "The parameter has been changed" in result1:
            logger.info(f"[{appliance_name}] ✓ run_cleanup_orphans_daily=off")
        else:
            logger.warning(f"[{appliance_name}] ⚠ unexpected response: {result1}")

        if appliance_type != 'cm':
            logger.info(f"[{appliance_name}] ⊘ purge_age_period skipped (type={appliance_type})")
            client.disconnect()
            return True

        if not client.channel:
            logger.error(f"[{appliance_name}] channel not available")
            return False

        logger.info(f"[{appliance_name}] ➜ store purge_age_period 0")
        client.channel.send(b"store purge_age_period 0\n")
        time.sleep(1)

        output = ""
        start_time = time.time()
        while time.time() - start_time < 10:
            if client.channel.recv_ready():
                chunk = client.channel.recv(4096).decode('utf-8', errors='ignore')
                output += chunk
                if "Are you sure you want to continue? (y/n)" in output:
                    client.channel.send(b"y\n")
                    time.sleep(2)
                    final_start = time.time()
                    while time.time() - final_start < 5:
                        if client.channel.recv_ready():
                            output += client.channel.recv(4096).decode('utf-8', errors='ignore')
                        else:
                            time.sleep(0.1)
                    break
            else:
                time.sleep(0.1)

        if client.strip_ansi_flag:
            output = strip_ansi(output)

        if "The purge_age period has been changed" in output:
            logger.info(f"[{appliance_name}] ✓ purge_age_period=0")
        else:
            logger.warning(f"[{appliance_name}] ⚠ unexpected response: {output}")

        client.disconnect()
        return True

    except Exception as e:
        logger.error(f"[{appliance_name}] ✗ {e}")
        logger.error(traceback.format_exc())
        return False

def set_shared_secret(
    config,
    logger,
    appliance_name: str,
    shared_secret: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True) -> bool:
    import traceback

    params = _get_appliance_connection_params(config, logger, appliance_name, user, password, prompt_regex)
    if not params:
        return False

    target_shared_secret = config.get_custom_variable('shared_secret') or "guardium"

    try:
        client = ApplianceClient(
            host=params['host'],
            user=params['user'],
            password=params['password'],
            prompt_regex=params['prompt_regex'],
            initial_pattern=None,
            timeout=60,
            strip_ansi=True,
            debug=debug
        )

        if not client.connect():
            logger.error(f"[{appliance_name}] failed to connect")
            return False

        logger.info(f"[{appliance_name}] ➜ store system shared secret ***")
        output = client.execute_command(f"store system shared secret {target_shared_secret}")
        client.disconnect()

        if "error" in output.lower() or "failed" in output.lower():
            logger.error(f"[{appliance_name}] ✗ {output}")
            return False

        logger.info(f"[{appliance_name}] ✓ shared secret set")
        return True

    except Exception as e:
        logger.error(f"[{appliance_name}] ✗ {e}")
        logger.error(traceback.format_exc())
        return False

def register_appliance(
    config,
    logger,
    appliance_name: str,
    cm_ip: Optional[str] = None,
    cm_port: int = 8443,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True,
    timeout: int = 240) -> bool:
    import traceback

    params = _get_appliance_connection_params(config, logger, appliance_name, user, password, prompt_regex)
    if not params:
        return False

    host = params['host']

    if not cm_ip:
        appliance_loader = ApplianceConfigLoader(config_loader=config)
        all_appliances = appliance_loader.get_all_appliances()
        cm_appliances = {n: c for n, c in all_appliances.items() if c.get('type', '').lower() == 'cm'}
        if not cm_appliances:
            logger.error(f"[{appliance_name}] no Central Manager found in machines_info.json")
            return False
        if len(cm_appliances) > 1:
            logger.warning(f"[{appliance_name}] multiple CMs: {list(cm_appliances.keys())} — using first")
        cm_name = next(iter(cm_appliances))
        cm_ip = cm_appliances[cm_name].get('ip')
        logger.info(f"[{appliance_name}] auto-detected CM: {cm_name} at {cm_ip}")

    if not cm_ip:
        logger.error(f"[{appliance_name}] CM IP not found")
        return False

    logger.info(f"[{appliance_name}] CM={cm_ip}:{cm_port} timeout={timeout}s")

    def _reconnect():
        c = ApplianceClient(
            host=host, user=params['user'], password=params['password'],
            prompt_regex=params['prompt_regex'], initial_pattern=None,
            timeout=60, strip_ansi=True, debug=debug
        )
        return c if c.connect() else None

    def _check_managed(c):
        logger.info(f"[{appliance_name}] ➜ show unit type")
        out = c.execute_command("show unit type")
        logger.info(f"[{appliance_name}] {out.strip()}")
        c.disconnect()
        return "Managed" in out or "managed" in out.lower()

    try:
        client = ApplianceClient(
            host=host, user=params['user'], password=params['password'],
            prompt_regex=params['prompt_regex'], initial_pattern=None,
            timeout=timeout, strip_ansi=True, debug=debug
        )

        if not client.connect():
            logger.error(f"[{appliance_name}] failed to connect")
            return False

        logger.info(f"[{appliance_name}] ➜ show unit type")
        logger.info(f"[{appliance_name}] {client.execute_command('show unit type').strip()}")

        command = f"register management {cm_ip} {cm_port}"
        logger.info(f"[{appliance_name}] ➜ {command}")
        logger.info(f"[{appliance_name}] ⌛ up to {timeout}s...")

        try:
            output, fail_detected = client.execute_command_with_early_fail_detection(
                command, fail_pattern="Fail:", timeout=timeout
            )
            if output:
                logger.info(f"[{appliance_name}] {output.strip()}")

            if fail_detected:
                logger.warning(f"[{appliance_name}] ⚠ Fail: detected")
                client.disconnect()
                reconnected = _reconnect()
                if not reconnected:
                    logger.error(f"[{appliance_name}] failed to reconnect")
                    return False
                managed = _check_managed(reconnected)
                if managed:
                    logger.info(f"[{appliance_name}] ✓ Managed (despite Fail: message)")
                else:
                    logger.error(f"[{appliance_name}] ✗ not Managed after Fail:")
                return managed

            managed = _check_managed(client)
            if managed:
                logger.info(f"[{appliance_name}] ✓ registered (Managed)")
            elif "unit_type" in output.lower() or "registered" in output.lower():
                logger.info(f"[{appliance_name}] ✓ registered")
                managed = True
            else:
                logger.warning(f"[{appliance_name}] ⚠ registration unclear — treating as success")
                managed = True
            return managed

        except TimeoutError:
            logger.debug(f"[{appliance_name}] ⚠ timeout, reconnecting")
            reconnected = _reconnect()
            if not reconnected:
                logger.error(f"[{appliance_name}] failed to reconnect after timeout")
                return False
            managed = _check_managed(reconnected)
            if managed:
                logger.info(f"[{appliance_name}] ✓ registered (after timeout)")
            else:
                logger.debug(f"[{appliance_name}] ⚠ timeout, not Managed")
            return managed

    except Exception as e:
        logger.error(f"[{appliance_name}] ✗ {e}")
        logger.error(traceback.format_exc())
        return False

def set_timezone(
    config,
    logger,
    appliance_name: str,
    timezone: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True) -> bool:
    import traceback

    params = _get_appliance_connection_params(config, logger, appliance_name, user, password, prompt_regex)
    if not params:
        return False

    machines_info = config.get('machines_info', {})
    target_timezone = timezone or machines_info.get('timezone', 'Europe/Warsaw')

    try:
        client = ApplianceClient(
            host=params['host'], user=params['user'], password=params['password'],
            prompt_regex=params['prompt_regex'], timeout=120, debug=debug
        )

        if not client.connect():
            logger.error(f"[{appliance_name}] failed to connect")
            return False

        logger.info(f"[{appliance_name}] ➜ show system clock all")
        output = client.execute_command("show system clock all")
        if not output:
            client.disconnect()
            logger.error(f"[{appliance_name}] failed to get current timezone")
            return False

        current_timezone = output.strip().splitlines()[-1]
        logger.info(f"[{appliance_name}] current timezone: {current_timezone}")

        if current_timezone == target_timezone:
            logger.info(f"[{appliance_name}] ✓ timezone already {target_timezone}")
            client.disconnect()
            return True

        logger.info(f"[{appliance_name}] ➜ store system clock timezone {target_timezone}")
        output = client.execute_command_with_confirmation(
            command=f"store system clock timezone {target_timezone}",
            response="y"
        )
        if debug and output:
            logger.info(f"[{appliance_name}] {output.strip()}")

        time.sleep(1)
        logger.info(f"[{appliance_name}] ➜ show system clock all (verify)")
        output = client.execute_command("show system clock all")
        if output:
            new_timezone = output.strip().splitlines()[-1]
            if new_timezone == target_timezone:
                logger.info(f"[{appliance_name}] ✓ timezone={new_timezone}")
            else:
                logger.warning(f"[{appliance_name}] ⚠ expected {target_timezone}, got {new_timezone}")

        client.disconnect()
        return True

    except Exception as e:
        logger.error(f"[{appliance_name}] ✗ {e}")
        logger.error(traceback.format_exc())
        return False

def configure_system_settings_consolidated(
    config,
    logger,
    appliance_name: str,
    hostname: Optional[str] = None,
    domain: Optional[str] = None,
    ip_address: Optional[str] = None,
    prefix: str = "/24",
    timezone: Optional[str] = None,
    ntp_servers: Optional[List[str]] = None,
    configure_hosts: bool = True,
    gid: Optional[int] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True) -> bool:
    import traceback

    def _log(msg, level='info'):
        getattr(logger, level)(f"[{appliance_name}] {msg}")

    try:
        params = _get_appliance_connection_params(config, logger, appliance_name, user, password, prompt_regex)
        if not params:
            return False

        appliance_loader = ApplianceConfigLoader(config_loader=config)
        host = params['host']

        if not hostname:
            hostname = appliance_name.rsplit('-', 1)[0] if '-' in appliance_name else appliance_name
        if not domain:
            domain = "demo.guardium"
        if not ip_address:
            ip_address = host

        machines_info = config.get('machines_info', {})
        target_timezone = timezone or machines_info.get('timezone', 'Europe/Warsaw')
        if not ntp_servers:
            ntp_servers = machines_info.get('ntp_servers', ['0.pool.ntp.org', '1.pool.ntp.org', '2.pool.ntp.org'])
        if not isinstance(ntp_servers, list):
            ntp_servers = ['0.pool.ntp.org', '1.pool.ntp.org', '2.pool.ntp.org']

        client = ApplianceClient(
            host=host, user=params['user'], password=params['password'],
            prompt_regex=params['prompt_regex'], timeout=300, debug=debug
        )

        if not client.connect():
            _log("failed to connect", 'error')
            return False

        try:
            output = client.execute_command_with_confirmation(
                command=f"store system hostname {hostname}",
                confirmation_pattern=r"Is it a newly cloned appliance\s*\(y/n\)\?",
                response="y"
            )
            if debug and output:
                _log(output)
            _log(f"✓ hostname={hostname}")
        except TimeoutError:
            _log("⚠ timeout during hostname change, continuing...", 'warning')

        try:
            output = client.execute_command(f"store system domain {domain}")
            if debug and output:
                _log(output)
            _log(f"✓ domain={domain}")
        except TimeoutError:
            _log("⚠ timeout during domain change, continuing...", 'warning')

        _prev_timeout = client.timeout
        client.timeout = 600
        try:
            output = client.execute_command_with_confirmation(
                command="restart network",
                confirmation_pattern=r"Do you really want to restart network\?\s*\(Yes/No\)",
                response="y"
            )
            if debug and output:
                _log(output)
            _log("✓ network restarted")
        except (TimeoutError, RuntimeError):
            _log("✓ network restart in progress (connection dropped - normal)")
        finally:
            client.timeout = _prev_timeout

        output = client.execute_command_simple_confirmation(
            command="store system small_disk",
            confirmation_text="I agree", response="I agree", timeout=60
        )
        if debug and output:
            _log(output)
        _log("✓ small_disk enabled")

        output = client.execute_command("store gui session_timeout 9999")
        if debug and output:
            _log(output)
        _log("✓ gui session_timeout=9999")

        output = client.execute_command("store timeout cli_session 600")
        if debug and output:
            _log(output)
        _log("✓ cli_session timeout=600")

        output = client.execute_command_with_confirmation(
            command="restart gui",
            confirmation_pattern=r"Are you sure you want to restart GUI\s*\(y/n\)\?",
            response="y"
        )
        if debug and output:
            _log(output)
        _log("✓ gui restarted")

        output = client.execute_command(f"store network interface ip {ip_address}{prefix}")
        if debug and output:
            _log(output)
        if "This change will take effect after the next network restart" in output or "ok" in output:
            _log(f"✓ ip={ip_address}{prefix}")
        else:
            _log(f"⚠ ip={ip_address}{prefix} — unexpected response", 'warning')

        output = client.execute_command_with_confirmation(
            command=f"store system clock timezone {target_timezone}",
            response="y"
        )
        if debug and output:
            _log(output)
        _log(f"✓ timezone={target_timezone}")

        output = client.execute_command(f"store system time_server hostname {' '.join(ntp_servers)}")
        if debug and output:
            _log(output)
        _log(f"✓ ntp={' '.join(ntp_servers)}")

        output = client.execute_command("store system time_server state on")
        if debug and output:
            _log(output)
        _log("✓ time sync enabled")

        hosts = {}
        for name, cfg in config.get_regular_machines().items():
            ip = cfg.get('private_ip', '')
            if ip:
                hosts[f"{name}.demo.guardium"] = ip
        for name, cfg in appliance_loader.get_all_appliances().items():
            if name == appliance_name:
                continue
            ip = cfg.get('ip', '')
            if ip:
                short = name.rsplit('-', 1)[0] if '-' in name else name
                hosts[f"{short}.demo.guardium"] = ip

        for fqdn, ip in hosts.items():
            client.execute_command(f"support store hosts {ip} {fqdn}")
        _log(f"✓ hosts={len(hosts)} entries")

        target_gid = gid if gid is not None else random.randint(1000, 100000)
        output = client.execute_command(f"store product gid {target_gid}")
        if debug and output:
            _log(output)
        _log(f"✓ gid={target_gid}")

        client.disconnect()
        _log(f"✓ done: hostname={hostname} ip={ip_address}{prefix} tz={target_timezone} gid={target_gid}")
        return True

    except Exception as e:
        logger.error(f"[{appliance_name}] ✗ {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False

def reset_cli_password(
    config,
    logger,
    appliance_name: str,
    cloudsupport_password: Optional[str] = None,
    cli_password: Optional[str] = None,
    debug: bool = True) -> bool:
    import paramiko
    import traceback

    if not appliance_name:
        logger.error("appliance_name is required")
        return False

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    appliance_config = appliance_loader.get_appliance(appliance_name)
    if not appliance_config:
        logger.error(f"[{appliance_name}] not found in machines_info.json")
        return False

    host = appliance_config.get('ip')
    if not host:
        logger.error(f"[{appliance_name}] no IP address configured")
        return False

    if not cloudsupport_password:
        cloudsupport_password = config.get_custom_variable('cloudsupport_pwd')
        if not cloudsupport_password:
            logger.error("cloudsupport_pwd not found in custom_variables")
            return False

    if not cli_password:
        cli_password = config.get_custom_variable('cli_pwd')
        if not cli_password:
            logger.error("cli_pwd not found in custom_variables")
            return False

    try:
        logger.info(f"➜ SSH {host} as cloudsupport")
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(
            hostname=host,
            username='cloudsupport',
            password=cloudsupport_password,
            look_for_keys=False,
            allow_agent=False,
            timeout=30
        )

        logger.info("➜ echo 'cli:***' | sudo chpasswd")
        stdin, stdout, stderr = ssh_client.exec_command(
            f"echo 'cli:{cli_password}' | sudo chpasswd", timeout=30
        )
        exit_code = stdout.channel.recv_exit_status()

        stdout_text = stdout.read().decode('utf-8').strip()
        stderr_text = stderr.read().decode('utf-8').strip()

        if debug and stdout_text:
            logger.info(f"STDOUT: {stdout_text}")
        if stderr_text:
            logger.warning(f"STDERR: {stderr_text}")

        ssh_client.close()

        if exit_code == 0:
            logger.info(f"✓ CLI password reset on {appliance_name}")
            return True
        else:
            logger.error(f"✗ chpasswd failed on {appliance_name} (exit code: {exit_code})")
            return False

    except Exception as e:
        logger.error(f"✗ {appliance_name}: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False

def prepare_appliance_for_patching(
    config,
    logger,
    appliance_name: str,
    patches_source_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/patches/",
    cloudsupport_password: Optional[str] = None,
    debug: bool = True) -> bool:
    
    import os
    import glob
    import paramiko
    import traceback

    params = _get_appliance_connection_params(config, logger, appliance_name)
    if not params:
        return False

    host, prompt_regex = params['host'], params['prompt_regex']

    if not cloudsupport_password:
        cloudsupport_password = config.get_custom_variable('cloudsupport_pwd')
        if not cloudsupport_password:
            logger.error(f"[{appliance_name}] cloudsupport_pwd not found in custom_variables")
            return False

    if not os.path.exists(patches_source_dir):
        logger.error(f"[{appliance_name}] patches directory not found: {patches_source_dir}")
        return False

    patch_files = glob.glob(os.path.join(patches_source_dir, "*.sig"))
    if not patch_files:
        logger.error(f"[{appliance_name}] no *.sig files found in {patches_source_dir}")
        return False

    logger.info(f"[{appliance_name}] found {len(patch_files)} patch files")
    for pf in patch_files:
        logger.info(f"[{appliance_name}]   - {os.path.basename(pf)}")

    try:
        raptor_ip = config.get_machine_ip('raptor', use_private=True)
        if not raptor_ip:
            logger.error(f"[{appliance_name}] raptor IP not found")
            return False

        raptor_root_password = config.get_custom_variable('pwd')
        if not raptor_root_password:
            logger.error(f"[{appliance_name}] pwd not found in custom_variables")
            return False

        ssh_port = config.config.get('ssh', {}).get('port', 22)
        logger.info(f"[{appliance_name}] ➜ SSH {host} as cloudsupport")

        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(
            hostname=host, username='cloudsupport', password=cloudsupport_password,
            look_for_keys=False, allow_agent=False, timeout=30
        )
        logger.info(f"[{appliance_name}] ✓ connected as cloudsupport")

        try:
            stdin, stdout, _ = ssh_client.exec_command('which sshpass')
            sshpass_available = stdout.channel.recv_exit_status() == 0

            logger.info(f"[{appliance_name}] ➜ scp {len(patch_files)} files from raptor")
            for patch_file in patch_files:
                filename = os.path.basename(patch_file)
                if sshpass_available:
                    scp_command = (
                        f"sshpass -p '{raptor_root_password}' scp -P {ssh_port} "
                        f"-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
                        f"root@{raptor_ip}:{patch_file} /tmp/{filename}"
                    )
                    stdin, stdout, stderr = ssh_client.exec_command(scp_command)
                    if stdout.channel.recv_exit_status() != 0:
                        logger.error(f"[{appliance_name}] failed to copy {filename}: {stderr.read().decode()}")
                        ssh_client.close()
                        return False
                else:
                    channel = ssh_client.invoke_shell()
                    time.sleep(0.5)
                    if channel.recv_ready():
                        channel.recv(65535)
                    channel.send(
                        f"scp -P {ssh_port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
                        f"root@{raptor_ip}:{patch_file} /tmp/{filename}\n".encode()
                    )
                    out = ""
                    deadline = time.time() + 30
                    while time.time() < deadline:
                        if channel.recv_ready():
                            chunk = channel.recv(4096).decode(errors='ignore')
                            out += chunk
                            if "password:" in out.lower():
                                channel.send(f"{raptor_root_password}\n".encode())
                                break
                        time.sleep(0.1)
                    time.sleep(2)
                    while channel.recv_ready():
                        channel.recv(4096)
                    channel.close()
                    stdin, stdout, _ = ssh_client.exec_command(f"test -f /tmp/{filename} && echo 'OK'")
                    if stdout.read().decode().strip() != "OK":
                        logger.error(f"[{appliance_name}] failed to copy {filename}")
                        ssh_client.close()
                        return False

            logger.info(f"[{appliance_name}] ✓ {len(patch_files)} files in /tmp/")

            logger.info(f"[{appliance_name}] ➜ sudo mkdir -p /var/IBM/Guardium/log/patches/")
            stdin, stdout, stderr = ssh_client.exec_command('sudo mkdir -p /var/IBM/Guardium/log/patches/')
            if stdout.channel.recv_exit_status() != 0:
                logger.error(f"[{appliance_name}] mkdir failed: {stderr.read().decode()}")
                ssh_client.close()
                return False

            logger.info(f"[{appliance_name}] ➜ sudo mv /tmp/*.sig /var/IBM/Guardium/log/patches/")
            stdin, stdout, stderr = ssh_client.exec_command('sudo mv /tmp/*.sig /var/IBM/Guardium/log/patches/')
            if stdout.channel.recv_exit_status() != 0:
                logger.error(f"[{appliance_name}] mv failed: {stderr.read().decode()}")
                ssh_client.close()
                return False

            logger.info(f"[{appliance_name}] ➜ sudo chown tomcat:tomcat /var/IBM/Guardium/log/patches/*.sig")
            stdin, stdout, stderr = ssh_client.exec_command('sudo chown tomcat:tomcat /var/IBM/Guardium/log/patches/*.sig')
            if stdout.channel.recv_exit_status() != 0:
                logger.error(f"[{appliance_name}] chown failed: {stderr.read().decode()}")
                ssh_client.close()
                return False

            stdin, stdout, _ = ssh_client.exec_command('sudo ls -la /var/IBM/Guardium/log/patches/*.sig')
            logger.info(f"[{appliance_name}] {stdout.read().decode().strip()}")
            ssh_client.close()

        except Exception as e:
            logger.error(f"[{appliance_name}] ✗ SSH error: {e}")
            logger.error(traceback.format_exc())
            return False

        cli_password = config.get_custom_variable('cli_pwd')
        if not cli_password:
            logger.error(f"[{appliance_name}] cli_pwd not found in custom_variables")
            return False

        cli_client = ApplianceClient(
            host=host, user='cli', password=cli_password,
            prompt_regex=prompt_regex, initial_pattern=None,
            timeout=300, strip_ansi=True, debug=debug
        )

        if not cli_client.connect():
            logger.error(f"[{appliance_name}] failed to connect as CLI user")
            return False

        logger.info(f"[{appliance_name}] ➜ show system patch available")
        patch_output = cli_client.execute_command("show system patch available", timeout=300)
        logger.info(f"[{appliance_name}] {patch_output.strip()}")
        cli_client.disconnect()

        logger.info(f"[{appliance_name}] ✓ prepared for patching")
        return True

    except Exception as e:
        logger.error(f"[{appliance_name}] ✗ {e}")
        logger.error(traceback.format_exc())
        return False

def copy_files_to_appliance(
    config,
    logger,
    appliance_name: str,
    source_dir: str,
    file_pattern: str,
    target_dir: str,
    owner: str = "tomcat:tomcat",
    cloudsupport_password: Optional[str] = None,
    debug: bool = False) -> bool:
    
    import os
    import glob
    import time
    import paramiko
    
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    logger.info("=" * 80)
    logger.info(f"COPY FILES TO APPLIANCE: {appliance_name}")
    logger.info("=" * 80)
    
    # Load appliance configuration
    from core.appliance_config_loader import ApplianceConfigLoader
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    appliance_config = appliance_loader.get_appliance(appliance_name)
    
    if not appliance_config:
        logger.error(f"Appliance '{appliance_name}' not found in machines_info.json")
        return False
    
    host = appliance_config.get('ip')
    if not host:
        logger.error(f"No IP address configured for appliance '{appliance_name}'")
        return False
    
    # Get cloudsupport password
    if not cloudsupport_password:
        cloudsupport_password = config.get_custom_variable('cloudsupport_pwd')
        if not cloudsupport_password:
            logger.error("cloudsupport_pwd not found in custom_variables")
            return False
    
    # Check if source directory exists
    if not os.path.exists(source_dir):
        logger.error(f"Source directory not found: {source_dir}")
        return False
    
    # Find files matching pattern
    files_to_copy = glob.glob(os.path.join(source_dir, file_pattern))
    if not files_to_copy:
        logger.error(f"No files matching '{file_pattern}' found in {source_dir}")
        return False
    
    logger.info(f"Found {len(files_to_copy)} file(s) to copy:")
    for file_path in files_to_copy:
        logger.info(f"  - {os.path.basename(file_path)}")
    
    try:
        # Get raptor IP
        raptor_ip = config.get_machine_ip('raptor', use_private=True)
        if not raptor_ip:
            logger.error("Could not find raptor IP in machines_info.json")
            return False
        
        # Get root password for raptor
        raptor_root_password = config.get_custom_variable('pwd')
        if not raptor_root_password:
            logger.error("pwd not found in custom_variables")
            return False
        
        # Get SSH port
        ssh_port = config.config.get('ssh', {}).get('port', 22)
        
        logger.info(f"Raptor IP: {raptor_ip}, SSH port: {ssh_port}")
        logger.info(f"Target appliance: {host}")
        
        # Connect as cloudsupport
        logger.info(f"\n➜ Connecting to {host} as cloudsupport user...")
        
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        ssh_client.connect(
            hostname=host,
            username='cloudsupport',
            password=cloudsupport_password,
            look_for_keys=False,
            allow_agent=False,
            timeout=30
        )
        
        logger.info(f"✓ Connected successfully")
        
        # Copy files from raptor to appliance /tmp/
        logger.info(f"\n➜ Copying files from raptor:{source_dir} to {host}:/tmp/...")
        
        # Check if sshpass is available
        stdin, stdout, stderr = ssh_client.exec_command('which sshpass')
        sshpass_available = stdout.channel.recv_exit_status() == 0
        
        for file_path in files_to_copy:
            filename = os.path.basename(file_path)
            logger.info(f"  Copying {filename}...")
            
            if sshpass_available:
                # Use sshpass
                scp_command = f"sshpass -p '{raptor_root_password}' scp -P {ssh_port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@{raptor_ip}:{file_path} /tmp/{filename}"
                stdin, stdout, stderr = ssh_client.exec_command(scp_command)
                exit_status = stdout.channel.recv_exit_status()
                
                if exit_status != 0:
                    error = stderr.read().decode()
                    logger.error(f"Failed to copy {filename}: {error}")
                    ssh_client.close()
                    return False
            else:
                # Use interactive SCP
                logger.info("  Using interactive SCP (sshpass not available)...")
                channel = ssh_client.invoke_shell()
                time.sleep(0.5)
                
                if channel.recv_ready():
                    channel.recv(65535)
                
                scp_cmd = f"scp -P {ssh_port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@{raptor_ip}:{file_path} /tmp/{filename}\n"
                channel.send(scp_cmd.encode())
                
                # Wait for password prompt
                output = ""
                timeout_time = time.time() + 30
                while time.time() < timeout_time:
                    if channel.recv_ready():
                        chunk = channel.recv(4096).decode(errors='ignore')
                        output += chunk
                        if "password:" in output.lower():
                            channel.send(f"{raptor_root_password}\n".encode())
                            break
                    time.sleep(0.1)
                
                time.sleep(2)
                while channel.recv_ready():
                    channel.recv(4096)
                
                channel.close()
                
                # Verify file was copied
                stdin, stdout, stderr = ssh_client.exec_command(f"test -f /tmp/{filename} && echo 'OK'")
                result = stdout.read().decode().strip()
                
                if result != "OK":
                    logger.error(f"Failed to copy {filename}")
                    ssh_client.close()
                    return False
        
        logger.info(f"✓ All {len(files_to_copy)} file(s) copied to /tmp/")
        
        # Move files to target directory
        logger.info(f"\n➜ Moving files to {target_dir} and setting permissions...")
        
        # Create target directory
        logger.info(f"  Creating {target_dir} directory if needed...")
        stdin, stdout, stderr = ssh_client.exec_command(f'sudo mkdir -p {target_dir}')
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            error = stderr.read().decode()
            logger.error(f"Failed to create directory: {error}")
            ssh_client.close()
            return False
        
        # Move files
        logger.info(f"  Moving files from /tmp/ to {target_dir}...")
        stdin, stdout, stderr = ssh_client.exec_command(f'sudo mv /tmp/{file_pattern} {target_dir}')
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            error = stderr.read().decode()
            logger.error(f"Failed to move files: {error}")
            ssh_client.close()
            return False
        
        # Set ownership
        logger.info(f"  Setting ownership to {owner}...")
        stdin, stdout, stderr = ssh_client.exec_command(f'sudo chown {owner} {target_dir}/{file_pattern}')
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            error = stderr.read().decode()
            logger.error(f"Failed to set ownership: {error}")
            ssh_client.close()
            return False
        
        # Verify files
        logger.info("  Verifying files...")
        stdin, stdout, stderr = ssh_client.exec_command(f'sudo ls -la {target_dir}/{file_pattern}')
        output = stdout.read().decode()
        logger.info(f"Files in {target_dir}:\n{output}")
        
        ssh_client.close()
        
        logger.info(f"\n✓ Files copied successfully to {appliance_name}")
        logger.info("=" * 80)
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to copy files: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        logger.error("=" * 80)
        return False

def copy_single_file_to_appliance(
    config,
    logger,
    appliance_name: str,
    source_file_path: str,
    target_dir: str = "/var/IBM/Guardium/log/patches/",
    owner: str = "tomcat:tomcat",
    cloudsupport_password: Optional[str] = None,
    debug: bool = True) -> bool:
    
    import os

    if not source_file_path:
        logger.error("source_file_path is required")
        return False

    params = _get_appliance_connection_params(config, logger, appliance_name)
    if not params:
        return False

    host = params['host']

    logger.info("=" * 80)
    logger.info(f"COPY FILE TO APPLIANCE: {appliance_name}")
    logger.info("=" * 80)

    if not cloudsupport_password:
        cloudsupport_password = config.get_custom_variable('cloudsupport_pwd')
        if not cloudsupport_password:
            logger.error("cloudsupport_pwd not found in machines_info.json custom_variables")
            return False
        logger.info("Using cloudsupport password from custom_variables")
    
    if not os.path.exists(source_file_path):
        logger.error(f"Source file not found: {source_file_path}")
        return False
    
    filename = os.path.basename(source_file_path)
    logger.info(f"File to copy: {filename}")
    logger.info(f"Source: {source_file_path}")
    logger.info(f"Target: {target_dir}")
    
    try:
        raptor_ip = config.get_machine_ip('raptor', use_private=True)
        if not raptor_ip:
            logger.error("Could not find raptor IP in machines_info.json")
            return False
        
        raptor_root_password = config.get_custom_variable('pwd')
        if not raptor_root_password:
            logger.error("pwd not found in machines_info.json custom_variables")
            return False
        
        ssh_port = config.config.get('ssh', {}).get('port', 22)
        
        logger.info(f"Raptor IP: {raptor_ip}, SSH port: {ssh_port}")
        
        import paramiko
        
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        ssh_client.connect(
            hostname=host,
            username='cloudsupport',
            password=cloudsupport_password,
            look_for_keys=False,
            allow_agent=False,
            timeout=30
        )
        
        logger.info(f"✓ Connected to {host}")
        logger.info(f"\n➜ Copying {filename} from raptor to appliance /tmp/...")
        
        stdin, stdout, stderr = ssh_client.exec_command('which sshpass')
        sshpass_available = stdout.channel.recv_exit_status() == 0
        
        if sshpass_available:
            logger.info("  Using sshpass for file transfer...")
            scp_cmd = f"sshpass -p '{raptor_root_password}' scp -P {ssh_port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@{raptor_ip}:{source_file_path} /tmp/{filename}"
            stdin, stdout, stderr = ssh_client.exec_command(scp_cmd, timeout=300)
            exit_status = stdout.channel.recv_exit_status()
            
            if exit_status != 0:
                error = stderr.read().decode()
                logger.error(f"SCP failed: {error}")
                ssh_client.close()
                return False
        else:
            logger.info("  Using interactive SCP (sshpass not available)...")
            channel = ssh_client.invoke_shell()
            
            import time
            time.sleep(0.5)
            while channel.recv_ready():
                channel.recv(65535)
            
            scp_cmd = f"scp -P {ssh_port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@{raptor_ip}:{source_file_path} /tmp/{filename}\n"
            channel.send(scp_cmd.encode())
            
            output = ""
            timeout_time = time.time() + 30
            while time.time() < timeout_time:
                if channel.recv_ready():
                    chunk = channel.recv(4096).decode(errors='ignore')
                    output += chunk
                    if "password:" in output.lower():
                        channel.send(f"{raptor_root_password}\n".encode())
                        break
                time.sleep(0.1)
            
            time.sleep(2)
            while channel.recv_ready():
                channel.recv(4096)
            
            channel.close()
        
        stdin, stdout, stderr = ssh_client.exec_command(f"test -f /tmp/{filename} && echo 'OK'")
        result = stdout.read().decode().strip()
        
        if result != "OK":
            logger.error(f"Failed to copy {filename}")
            ssh_client.close()
            return False
        
        logger.info(f"✓ File copied to /tmp/")
        logger.info(f"\n➜ Moving file to {target_dir} and setting permissions...")
        
        stdin, stdout, stderr = ssh_client.exec_command(f'sudo mkdir -p {target_dir}')
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            error = stderr.read().decode()
            logger.error(f"Failed to create directory: {error}")
            ssh_client.close()
            return False
        
        stdin, stdout, stderr = ssh_client.exec_command(f'sudo mv /tmp/{filename} {target_dir}')
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            error = stderr.read().decode()
            logger.error(f"Failed to move file: {error}")
            ssh_client.close()
            return False
        
        stdin, stdout, stderr = ssh_client.exec_command(f'sudo chown {owner} {target_dir}/{filename}')
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            error = stderr.read().decode()
            logger.error(f"Failed to set ownership: {error}")
            ssh_client.close()
            return False
        
        stdin, stdout, stderr = ssh_client.exec_command(f'sudo ls -la {target_dir}/{filename}')
        output = stdout.read().decode()
        logger.info(f"File in {target_dir}:\n{output}")
        
        ssh_client.close()
        
        logger.info(f"\n✓ File copied successfully to {appliance_name}")
        logger.info("=" * 80)
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to copy file: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        logger.error("=" * 80)
        return False

def get_patch_installation_order(
    config,
    logger,
    appliance_name: str,
    patch_order_file: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/patches/patch_order.txt",
    user: Optional[str] = None,
    password: Optional[str] = None,
    debug: bool = True
) -> Optional[str]:
    
    import os
    
    logger.info("=" * 80)
    logger.info(f"GET PATCH INSTALLATION ORDER")
    logger.info("=" * 80)
    
    if not os.path.exists(patch_order_file):
        logger.error(f"Patch order file not found: {patch_order_file}")
        return None
    
    logger.info(f"➜ Reading patch order from: {patch_order_file}")
    try:
        with open(patch_order_file, 'r') as f:
            patch_order = [line.strip() for line in f if line.strip()]
        
        logger.info(f"Desired installation order ({len(patch_order)} patches):")
        for i, patch_name in enumerate(patch_order, 1):
            logger.info(f"  {i}. {patch_name}")
    except Exception as e:
        logger.error(f"Failed to read patch order file: {e}")
        return None
    
    if not patch_order:
        logger.error("No patches found in patch_order.txt")
        return None
    
    sorted_patches = sorted(patch_order)
    
    logger.info(f"\nAlphabetically sorted (CM order) ({len(sorted_patches)} patches):")
    for i, patch_name in enumerate(sorted_patches, 1):
        logger.info(f"  Position {i}: {patch_name}")
    
    logger.info("\n➜ Mapping desired order to CM positions...")
    patch_positions = []
    
    for patch_spec in patch_order:
        try:
            position = sorted_patches.index(patch_spec) + 1
            patch_positions.append(str(position))
            logger.info(f"  {patch_spec} → position {position}")
        except ValueError:
            logger.warning(f"  {patch_spec} → NOT FOUND in sorted list!")
    
    if not patch_positions:
        logger.error("No patches mapped from patch_order.txt")
        return None
    
    patch_selection = ','.join(patch_positions)
    
    logger.info("=" * 80)
    logger.info(f"✓ Patch installation order: {patch_selection}")
    logger.info("=" * 80)
    
    return patch_selection

def install_patch_on_appliance(
    config,
    logger,
    appliance_name: str,
    patch_selection: str,
    reinstall_answer: str = "y",
    user: Optional[str] = None,
    password: Optional[str] = None,
    debug: bool = True
) -> bool:
    
    import socket

    if not patch_selection:
        logger.error("patch_selection is required")
        return False

    params = _get_appliance_connection_params(config, logger, appliance_name, user, password)
    if not params:
        return False

    host, user, password, prompt_regex = params['host'], params['user'], params['password'], params['prompt_regex']
    appliance_type = params['appliance_type']

    logger.info("=" * 80)
    logger.info(f"INSTALL PATCHES: {appliance_name}")
    logger.info("=" * 80)
    logger.info(f"Appliance: {appliance_name} ({appliance_type}) at {host}")
    logger.info(f"Patch selection: {patch_selection}")
    logger.info(f"Reinstall answer: {reinstall_answer}")

    try:
        client = ApplianceClient(
            host=host,
            user=user,
            password=password,
            prompt_regex=prompt_regex,
            initial_pattern=None,
            timeout=60,
            strip_ansi=True,
            debug=debug
        )
        
        if not client.connect():
            logger.error("Failed to connect to appliance")
            return False
        
        logger.info("✓ Connected successfully")
        
        # Get the SSH channel for interactive communication
        channel = client.channel
        if not channel:
            logger.error("No SSH channel available")
            client.disconnect()
            return False
        
        channel.settimeout(0.1)
        
        # Send patch install command
        command = "store system patch install sys"
        logger.info(f"\n➜ Executing: {command}")
        logger.info("⌛ Waiting for patch selection prompt...")
        
        channel.send((command + "\r").encode())
        
        # Read output and respond to prompts
        buf = ""
        patch_selected = False
        reinstall_answered = False
        last_activity = time.time()
        
        while True:
            try:
                chunk = channel.recv(4096).decode('utf-8', errors='replace')
                if chunk:
                    buf += chunk
                    last_activity = time.time()
                    
                    if debug:
                        # Print chunk without ANSI codes for cleaner output
                        import re
                        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                        clean_chunk = ansi_escape.sub('', chunk)
                        print(clean_chunk, end='', flush=True)
                    
                    # Remove ANSI codes for pattern matching
                    import re
                    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                    buf_clean = ansi_escape.sub('', buf)
                    
                    # Check for patch selection prompt
                    if not patch_selected and ("Please choose patches" in buf_clean or "or q to quit" in buf_clean):
                        last_line = buf_clean.strip().split('\n')[-1]
                        if last_line.endswith(':'):
                            # Wait a moment to ensure prompt is complete
                            time.sleep(1.0)
                            try:
                                extra = channel.recv(4096).decode('utf-8', errors='replace')
                                if extra:
                                    buf += extra
                                    if debug:
                                        clean_extra = ansi_escape.sub('', extra)
                                        print(clean_extra, end='', flush=True)
                            except:
                                pass
                            
                            logger.info(f"\n>>> Sending patch selection: {patch_selection} <<<")
                            channel.send((patch_selection + "\r").encode())
                            patch_selected = True
                            last_activity = time.time()
                            time.sleep(0.5)
                    
                    # Check for reinstall prompt
                    if patch_selected and not reinstall_answered and "Do you really want to install again" in buf_clean:
                        if "(yes or no)?" in buf_clean:
                            # Wait a moment to ensure prompt is complete
                            time.sleep(1.0)
                            try:
                                extra = channel.recv(4096).decode('utf-8', errors='replace')
                                if extra:
                                    buf += extra
                                    if debug:
                                        clean_extra = ansi_escape.sub('', extra)
                                        print(clean_extra, end='', flush=True)
                            except:
                                pass
                            
                            logger.info(f"\n>>> Sending reinstall answer: {reinstall_answer} <<<")
                            channel.send((reinstall_answer + "\r").encode())
                            reinstall_answered = True
                            last_activity = time.time()
                            time.sleep(0.5)
                    
                    # Check if we're back at prompt (command completed)
                    if patch_selected and (prompt_regex and re.search(prompt_regex, buf_clean)):
                        # Wait a moment for any final output
                        time.sleep(1)
                        try:
                            while True:
                                chunk = channel.recv(4096).decode('utf-8', errors='replace')
                                if chunk:
                                    if debug:
                                        clean_chunk = ansi_escape.sub('', chunk)
                                        print(clean_chunk, end='', flush=True)
                                else:
                                    break
                        except:
                            pass
                        
                        logger.info("\n\n=== Patch installation command completed ===")
                        client.disconnect()
                        
                        logger.info("=" * 80)
                        logger.info(f"✓ Patch installation initiated on {appliance_name}")
                        logger.info("=" * 80)
                        
                        # Now monitor the installation to ensure all patches complete successfully
                        logger.info("\n⏳ Monitoring patch installation progress...")
                        logger.info("=" * 80)
                        
                        # Wait a moment before starting to monitor
                        time.sleep(10)
                        
                        # Monitor the installation (check every 60 seconds, max 60 checks = 1 hour)
                        monitor_result = monitor_patch_installation(
                            config=config,
                            logger=logger,
                            appliance_name=appliance_name,
                            patch_numbers=None,  # Monitor all patches
                            check_interval=60,
                            max_checks=60,
                            user=user,
                            password=password,
                            debug=debug
                        )
                        
                        return monitor_result
                
            except socket.timeout:
                # Timeout is normal - no data available
                # Check if too much time passed without activity
                if time.time() - last_activity > 300:  # 5 minutes without activity
                    logger.warning("\n\n⚠ No activity for 5 minutes")
                    break
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"\nUnexpected error during patch installation: {e}")
                break
            
            # Check if channel is still open
            if channel.closed:
                logger.warning("\nChannel closed unexpectedly")
                break
        
        client.disconnect()
        logger.warning("Patch installation may not have completed successfully")
        return False
        
    except Exception as e:
        logger.error(f"Error installing patches: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def monitor_patch_installation(
    config,
    logger,
    appliance_name: str,
    patch_numbers: Optional[List[str]] = None,
    check_interval: int = 60,
    max_checks: int = 60,
    user: Optional[str] = None,
    password: Optional[str] = None,
    debug: bool = False
) -> bool:
    
    params = _get_appliance_connection_params(config, logger, appliance_name, user, password)
    if not params:
        return False

    host, user, password, prompt_regex = params['host'], params['user'], params['password'], params['prompt_regex']
    appliance_type = params['appliance_type']

    logger.info("=" * 80)
    logger.info(f"MONITOR PATCH INSTALLATION: {appliance_name}")
    logger.info("=" * 80)
    logger.info(f"Appliance: {appliance_name} ({appliance_type}) at {host}")
    logger.info(f"Check interval: {check_interval} seconds")
    logger.info(f"Max checks: {max_checks} (timeout: {check_interval * max_checks} seconds)")
    
    check_count = 0
    
    while check_count < max_checks:
        check_count += 1
        logger.info(f"\n{'=' * 80}")
        logger.info(f"Check #{check_count}/{max_checks} for {appliance_name}")
        logger.info(f"{'=' * 80}")
        
        try:
            # Connect to appliance
            client = ApplianceClient(
                host=host,
                user=user,
                password=password,
                prompt_regex=prompt_regex,
                initial_pattern=None,
                timeout=60,
                strip_ansi=True,
                debug=debug
            )
            
            if not client.connect():
                logger.warning(f"⚠ Failed to connect to {appliance_name} (attempt {check_count}/{max_checks})")
                logger.info(f"  Appliance may be restarting or unavailable")
                logger.info(f"  Waiting {check_interval} seconds before next check...")
                time.sleep(check_interval)
                continue
            
            # Execute show system patch install
            logger.info(f"➜ Executing: show system patch install")
            output = client.execute_command("show system patch install")
            
            client.disconnect()
            
            if not output:
                logger.warning(f"⚠ No output from 'show system patch install'")
                logger.info(f"  Waiting {check_interval} seconds before next check...")
                time.sleep(check_interval)
                continue
            
            if debug:
                logger.info(f"Patch installation status:\n{output}")
            
            # Parse output to check each patch status
            # Format: P#      Who       Description                     Request Time         Status
            #         9997    CLI       Health Check for GPU and Bundle 2026-06-03 19:13:50  DONE: Patch installation Succeeded.
            
            lines = output.split('\n')
            patch_status = {}  # {patch_number: status_line}
            
            for line in lines:
                line_stripped = line.strip()
                # Skip header and empty lines
                if not line_stripped or line_stripped.startswith('P#') or 'Request Time' in line_stripped:
                    continue
                
                # Look for lines starting with patch number
                match = re.match(r'^(\d+)\s+', line_stripped)
                if match:
                    patch_number = match.group(1)
                    patch_status[patch_number] = line_stripped
            
            # If patch_numbers not specified, monitor all patches found
            if not patch_numbers:
                patch_numbers_to_check = list(patch_status.keys())
            else:
                patch_numbers_to_check = patch_numbers
            
            if not patch_numbers_to_check:
                logger.warning("⚠ No patches found to monitor")
                logger.info(f"  Waiting {check_interval} seconds before next check...")
                time.sleep(check_interval)
                continue
            
            # Check status of each patch
            patches_in_progress = 0
            patches_completed = 0
            patches_failed = 0
            patches_with_warning = 0
            
            logger.info(f"\n📊 Checking status of {len(patch_numbers_to_check)} patch(es):")
            
            for patch_num in patch_numbers_to_check:
                if patch_num not in patch_status:
                    logger.warning(f"  ⚠ Patch {patch_num}: NOT FOUND in output")
                    patches_failed += 1
                    continue
                
                status_line = patch_status[patch_num]
                
                # Check for success: "DONE: Patch installation Succeeded."
                if "DONE: Patch installation Succeeded" in status_line:
                    logger.info(f"  ✓ Patch {patch_num}: Succeeded")
                    patches_completed += 1
                # Special case for patch 9997: WARNING is acceptable
                elif patch_num == "9997" and "WARNING:" in status_line:
                    logger.warning(f"  ⚠ Patch {patch_num}: Completed with WARNING (acceptable for 9997)")
                    # Extract warning message
                    warning_match = re.search(r'WARNING:\s*(.+)', status_line)
                    if warning_match:
                        warning_msg = warning_match.group(1)
                        logger.warning(f"    Warning message: {warning_msg}")
                    patches_completed += 1
                    patches_with_warning += 1
                # Check for in-progress states
                elif any(keyword in status_line for keyword in ["Preparing", "STEP:", "Executing", "Applying", "POST:"]):
                    # Extract the status message
                    status_match = re.search(r'(Preparing|STEP:|Executing|Applying|POST:)\s*(.+)', status_line)
                    if status_match:
                        status_msg = status_match.group(0)
                        logger.info(f"  ⏳ Patch {patch_num}: {status_msg}")
                    else:
                        logger.info(f"  ⏳ Patch {patch_num}: In progress")
                    patches_in_progress += 1
                # Check for failure
                elif "FAIL" in status_line.upper() or "ERROR" in status_line.upper():
                    logger.error(f"  ✗ Patch {patch_num}: FAILED")
                    logger.error(f"    Status: {status_line}")
                    patches_failed += 1
                else:
                    # Unknown status - treat as in progress
                    logger.info(f"  ? Patch {patch_num}: Unknown status")
                    logger.info(f"    Status: {status_line}")
                    patches_in_progress += 1
            
            logger.info(f"\n📊 Summary:")
            logger.info(f"  ⏳ In progress: {patches_in_progress}")
            logger.info(f"  ✓ Completed: {patches_completed}")
            if patches_with_warning > 0:
                logger.info(f"  ⚠ With warnings: {patches_with_warning}")
            logger.info(f"  ✗ Failed: {patches_failed}")
            
            # Check if installation is complete
            if patches_in_progress == 0:
                if patches_failed > 0:
                    logger.error(f"\n✗ Patch installation completed with {patches_failed} failure(s)")
                    logger.error("=" * 80)
                    return False
                else:
                    if patches_with_warning > 0:
                        logger.info(f"\n✓ All patches installed successfully ({patches_with_warning} with acceptable warnings)")
                    else:
                        logger.info(f"\n✓ All patches installed successfully!")
                    logger.info("=" * 80)
                    return True
            
            # Still patches in progress
            logger.info(f"\n⏳ {patches_in_progress} patch(es) still installing...")
            logger.info(f"  Waiting {check_interval} seconds before next check...")
            time.sleep(check_interval)
            
        except Exception as e:
            logger.warning(f"⚠ Error checking patch status (attempt {check_count}/{max_checks}): {e}")
            if debug:
                import traceback
                logger.error(traceback.format_exc())
            logger.info(f"  Waiting {check_interval} seconds before next check...")
            time.sleep(check_interval)
    
    # Max checks reached
    logger.error(f"\n✗ Maximum checks ({max_checks}) reached without completion")
    logger.error("=" * 80)
    return False

def install_and_monitor_patches(
    config,
    logger,
    appliance_name: str,
    patch_selection: str,
    reinstall_answer: str = "y",
    check_interval: int = 60,
    max_checks: int = 60,
    user: Optional[str] = None,
    password: Optional[str] = None,
    debug: bool = True
) -> bool:
    
    logger.info("=" * 80)
    logger.info(f"INSTALL AND MONITOR PATCHES: {appliance_name}")
    logger.info("=" * 80)
    
    # Step 1: Get patch numbers from patch_selection
    # Map positions to patch numbers based on alphabetically sorted *.sig files
    logger.info("\n📋 Step 1: Determining patch numbers from selection...")
    
    # Define patches directory path
    patches_dir = "/opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/patches/"
    
    try:
        import os
        import glob
        
        # Get all *.sig files and sort them alphabetically
        sig_files = glob.glob(os.path.join(patches_dir, "*.sig"))
        sig_files.sort()
        
        if not sig_files:
            logger.error(f"No *.sig files found in {patches_dir}")
            return False
        
        logger.info(f"Found {len(sig_files)} patch files:")
        
        # Map positions to patch numbers
        available_patches = {}  # {position: patch_number}
        position = 0
        
        for sig_file in sig_files:
            position += 1
            filename = os.path.basename(sig_file)
            
            # Extract patch number from filename using regex p(\d+)
            match = re.search(r'p(\d+)', filename)
            if match:
                patch_number = match.group(1)
                available_patches[position] = patch_number
                logger.info(f"  Position {position}: {filename} → Patch {patch_number}")
            else:
                logger.warning(f"  Position {position}: {filename} → Could not extract patch number")
        
        if not available_patches:
            logger.error("Could not extract patch numbers from any *.sig files")
            return False
        
        # Map patch_selection positions to patch numbers
        patch_numbers = []
        positions = [p.strip() for p in patch_selection.split(',')]
        
        logger.info(f"\nMapping selected positions to patch numbers:")
        for pos_str in positions:
            try:
                pos = int(pos_str)
                if pos in available_patches:
                    patch_numbers.append(available_patches[pos])
                    logger.info(f"  Position {pos} → Patch {available_patches[pos]}")
                else:
                    logger.warning(f"  Position {pos} → NOT FOUND (valid range: 1-{len(available_patches)})")
            except ValueError:
                logger.warning(f"  Invalid position: {pos_str}")
        
        if not patch_numbers:
            logger.error("Could not determine patch numbers from selection")
            return False
        
        logger.info(f"✓ Will monitor patches: {', '.join(patch_numbers)}")
        
    except Exception as e:
        logger.error(f"Error reading patch files from {patches_dir}: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        logger.info("Will monitor all patches")
        patch_numbers = None
    
    # Step 2: Install patches
    logger.info("\n📦 Step 2: Installing patches...")
    install_success = install_patch_on_appliance(
        config=config,
        logger=logger,
        appliance_name=appliance_name,
        patch_selection=patch_selection,
        reinstall_answer=reinstall_answer,
        user=user,
        password=password,
        debug=debug
    )
    
    if not install_success:
        logger.error(f"✗ Failed to initiate patch installation on {appliance_name}")
        return False
    
    logger.info(f"\n✓ Patch installation initiated successfully")
    logger.info(f"⏳ Waiting {check_interval} seconds before starting monitoring...")
    time.sleep(check_interval)
    
    # Step 3: Monitor installation
    logger.info("\n📊 Step 3: Monitoring patch installation...")
    monitor_success = monitor_patch_installation(
        config=config,
        logger=logger,
        appliance_name=appliance_name,
        patch_numbers=patch_numbers,
        check_interval=check_interval,
        max_checks=max_checks,
        user=user,
        password=password,
        debug=False  # Less verbose during monitoring
    )
    
    if not monitor_success:
        logger.error(f"✗ Patch installation monitoring failed for {appliance_name}")
        return False
    
    logger.info("=" * 80)
    logger.info(f"✓ Patches installed and verified successfully on {appliance_name}")
    logger.info("=" * 80)
    return True

def install_gim_module(
    config,
    logger,
    appliance_name: str,
    client_ip: str,
    module: str,
    module_version: str,
    params: Optional[dict] = None,
    demo_user: str = "demo",
    demo_password: Optional[str] = None,
    monitor_installation: bool = True,
    installation_delay: int = 10,
    debug: bool = False
) -> bool:
    
    from core.guardium_rest_api import create_guardium_api
    import time
    
    logger.info("=" * 80)
    logger.info(f"INSTALL GIM MODULE: {module}")
    logger.info("=" * 80)
    logger.info(f"Appliance: {appliance_name}")
    logger.info(f"Client IP: {client_ip}")
    logger.info(f"Module: {module}")
    logger.info(f"Version: {module_version}")
    
    # Get demo user password
    if not demo_password:
        demo_password = config.get_custom_variable('pwd')
        if demo_password:
            logger.info("Using demo password from custom_variables (pwd)")
    
    if not demo_password:
        logger.error("Demo user password is required")
        logger.error("Provide demo_password in args or set 'pwd' in custom_variables")
        return False
    
    try:
        # Create REST API client
        api = create_guardium_api(config, logger, appliance_name)
        logger.info("✓ GuardiumRestAPI client created successfully")
        
        if debug:
            logger.info(f"DEBUG: API Base URL: {api.base_url}")
        
        # Get OAuth token
        logger.info(f"\n{'=' * 80}")
        logger.info("STEP 1: OAuth Authentication")
        logger.info(f"{'=' * 80}")
        logger.info(f"➜ Authenticating as user '{demo_user}'...")
        
        if debug:
            logger.info(f"DEBUG: API Call: get_token(username='{demo_user}', password='***')")
        
        token = api.get_token(username=demo_user, password=demo_password)
        logger.info("✓ Authentication successful")
        
        if debug:
            logger.info(f"DEBUG: Access token (first 30 chars): {token[:30]}...")
        
        # Assign module to client
        logger.info(f"\n{'=' * 80}")
        logger.info("STEP 2: Assign GIM Module to Client")
        logger.info(f"{'=' * 80}")
        logger.info(f"➜ Assigning module '{module}' (version: {module_version}) to client {client_ip}...")
        
        if debug:
            logger.info(f"DEBUG: API Call: gim_client_assign(")
            logger.info(f"DEBUG:   client_ip='{client_ip}',")
            logger.info(f"DEBUG:   module='{module}',")
            logger.info(f"DEBUG:   module_version='{module_version}'")
            logger.info(f"DEBUG: )")
        
        assign_response = api.gim_client_assign(
            client_ip=client_ip,
            module=module,
            module_version=module_version
        )
        
        logger.info(f"✓ Module assigned successfully")
        if debug:
            logger.info(f"DEBUG: API Response: {assign_response}")
        
        # Set module parameters
        if params:
            logger.info(f"\n{'=' * 80}")
            logger.info(f"STEP 3: Set Module Parameters ({len(params)} parameter(s))")
            logger.info(f"{'=' * 80}")
            
            for param_name, param_value in params.items():
                logger.info(f"➜ Setting parameter: {param_name} = {param_value}")
                
                if debug:
                    logger.info(f"DEBUG: API Call: gim_client_params(")
                    logger.info(f"DEBUG:   client_ip='{client_ip}',")
                    logger.info(f"DEBUG:   param_name='{param_name}',")
                    logger.info(f"DEBUG:   param_value='{param_value}'")
                    logger.info(f"DEBUG: )")
                
                param_response = api.gim_client_params(
                    client_ip=client_ip,
                    param_name=param_name,
                    param_value=str(param_value)
                )
                
                logger.info(f"  ✓ Parameter set successfully")
                if debug:
                    logger.info(f"DEBUG:   API Response: {param_response}")
            
            logger.info(f"\n✓ All {len(params)} parameter(s) set successfully")
        else:
            logger.info(f"\n{'=' * 80}")
            logger.info("STEP 3: Set Module Parameters")
            logger.info(f"{'=' * 80}")
            logger.info("⊘ No parameters to set")
        
        # Schedule installation
        logger.info(f"\n{'=' * 80}")
        logger.info("STEP 4: Schedule Installation")
        logger.info(f"{'=' * 80}")
        logger.info(f"➜ Scheduling installation for client {client_ip}...")
        logger.info(f"  Installation time: now")
        
        if debug:
            logger.info(f"DEBUG: API Call: gim_schedule_install(")
            logger.info(f"DEBUG:   client_ip='{client_ip}',")
            logger.info(f"DEBUG:   date='now'")
            logger.info(f"DEBUG: )")
        
        schedule_response = api.gim_schedule_install(
            client_ip=client_ip,
            date="now"
        )
        
        logger.info(f"✓ Installation scheduled successfully")
        if debug:
            logger.info(f"DEBUG: API Response: {schedule_response}")
        
        # Monitor installation
        if monitor_installation:
            logger.info(f"\n➜ Waiting {installation_delay} seconds before monitoring...")
            time.sleep(installation_delay)
            
            logger.info(f"➜ Monitoring installation progress for client {client_ip}...")
            
            # Monitor until all modules are installed
            import re
            pending = ["initial"]  # Initialize to enter loop
            check_count = 0
            while pending:
                check_count += 1
                logger.info(f"\n  Check #{check_count}: Querying module status...")
                
                modules = api.gim_list_client_modules(client_ip=client_ip)
                
                if debug:
                    logger.debug(f"  Full API response: {modules}")
                
                # Check for API errors
                if "ErrorCode" in modules or "ErrorMessage" in modules:
                    error_code = modules.get("ErrorCode", "N/A")
                    error_msg = modules.get("ErrorMessage", "N/A")
                    logger.error(f"  ✗ API Error: Code={error_code}, Message={error_msg}")
                    logger.error(f"  This usually means the client IP is not registered or modules not assigned")
                    return False
                
                msg = modules.get("Message", "")
                
                if debug:
                    logger.debug(f"  Raw API response Message:\n{msg}")
                
                if not msg:
                    logger.warning(f"  ⚠ API returned empty Message field")
                    logger.warning(f"  Full response keys: {list(modules.keys())}")
                
                # Parse module entries
                entries = [
                    e.strip()
                    for e in re.split(r"#+\s*ENTRY\s+\d+\s*#+", msg)
                    if e.strip()
                ]
                
                logger.info(f"  Found {len(entries)} module entry/entries")
                
                result = []
                for entry in entries:
                    entry_str: str = str(entry)
                    def g(p: str) -> Optional[str]:
                        m = re.search(p, entry_str)
                        return m.group(1) if m else None
                    
                    module_info = {
                        "module_id": g(r"MODULE_ID:\s+(-?\d+)"),
                        "name": g(r"NAME:\s+([A-Z0-9\-]+)"),
                        "installed_version": g(r"INSTALLED_VERSION\s+([0-9][^\s]+)"),
                        "scheduled_version": g(r"SCHEDULED_VERSION\s+([0-9][^\s]+)"),
                        "state": g(r"STATE:\s+([A-Z\-]+)"),
                        "is_scheduled": g(r"IS_SCHEDULED:\s+([NY])"),
                        "schedule_time": g(r"IS_SCHEDULED:\s+[NY]\s+\(([^)]+)\)")
                    }
                    result.append(module_info)
                    
                    if debug:
                        logger.debug(f"  Module: {module_info['name']} | State: {module_info['state']} | Scheduled: {module_info['scheduled_version']}")
                
                # Check for pending installations
                pending = [m for m in result if m["state"] != "INSTALLED"]
                
                if pending:
                    logger.info(f"  ⌛ {len(pending)} module(s) still installing:")
                    for m in pending:
                        logger.info(f"    - {m['name']}: {m['state']}")
                    logger.info(f"  Waiting 30 seconds before next check...")
                    time.sleep(30)
                else:
                    logger.info("  ✓ All modules installed successfully!")
                    for m in result:
                        logger.info(f"    - {m['name']}: {m['state']} (version: {m['installed_version']})")
        
        logger.info("\n" + "=" * 80)
        logger.info(f"✓ GIM MODULE INSTALLATION COMPLETED")
        logger.info("=" * 80)
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to install GIM module: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        logger.error("=" * 80)
        return False



def enable_ltr_on_appnode(
    config,
    logger,
    appliance_name: str,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    
    
    params = _get_appliance_connection_params(config, logger, appliance_name, user, password, prompt_regex)
    if not params:
        return False

    host, user, password, prompt_regex = params['host'], params['user'], params['password'], params['prompt_regex']
    appliance_type = params['appliance_type']

    logger.info("=" * 80)
    logger.info(f"ENABLE LTR ON APPNODE: {appliance_name}")
    logger.info("=" * 80)
    logger.info(f"Appliance: {appliance_name} ({appliance_type}) at {host}")
    logger.info(f"User: {user}")
    
    try:
        client = ApplianceClient(
            host=host,
            user=user,
            password=password,
            prompt_regex=prompt_regex,
            initial_pattern=None,
            timeout=300,
            strip_ansi=True,
            debug=debug
        )
        
        if not client.connect():
            logger.error("Failed to connect to appliance")
            return False
        
        # Step 1: store datalake install
        logger.info("\n➜ Step 1: Installing datalake...")
        logger.info("Executing: store datalake install")
        result1 = client.execute_command("store datalake install", timeout=300)
        
        if "Datalake installation was successful" in result1:
            logger.info("✓ Datalake installation was successful")
        else:
            logger.error("✗ Datalake installation failed")
            logger.error(f"Output: {result1}")
            client.disconnect()
            return False
        
        # Step 2: store datalake all_in_one xxsmall
        logger.info("\n➜ Step 2: Configuring datalake all_in_one xxsmall...")
        logger.info("Executing: store datalake all_in_one xxsmall")
        result2 = client.execute_command("store datalake all_in_one xxsmall", timeout=300)
        
        if "Datalake all_in_one was brought up correctly" in result2:
            logger.info("✓ Datalake all_in_one was brought up correctly")
        else:
            logger.error("✗ Datalake all_in_one configuration failed")
            logger.error(f"Output: {result2}")
            client.disconnect()
            return False
        
        # Step 3: store datalake service start
        logger.info("\n➜ Step 3: Starting datalake service...")
        logger.info("Executing: store datalake service start")
        result3 = client.execute_command("store datalake service start", timeout=300)
        logger.info(f"Command output: {result3}")
        
        # Step 4: show datalake status - verify it's running
        logger.info("\n➜ Step 4: Verifying datalake status...")
        logger.info("Executing: show datalake status")
        result4 = client.execute_command("show datalake status", timeout=60)
        
        if "Datalake is running!" in result4:
            logger.info("✓ Datalake is running!")
        else:
            logger.error("✗ Datalake is not running")
            logger.error(f"Output: {result4}")
            client.disconnect()
            return False
        
        client.disconnect()
        
        logger.info("\n" + "=" * 80)
        logger.info("LTR enabled successfully on appnode")
        logger.info("=" * 80)
        return True
        
    except Exception as e:
        logger.error(f"Error enabling LTR on appnode: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False



def import_datalake_s3_certificate(
    config,
    logger,
    appliance_name: str,
    certificate_file_path: str = "/home/minio/ca/certs/ca.crt",
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    
    
    logger.info("=" * 80)
    logger.info(f"IMPORT DATALAKE S3 CERTIFICATE: {appliance_name}")
    logger.info("=" * 80)

    logger.info(f"Reading certificate from local file: {certificate_file_path}")
    
    try:
        with open(certificate_file_path, 'r') as f:
            certificate_content = f.read()
        
        if not certificate_content or 'BEGIN CERTIFICATE' not in certificate_content:
            logger.error("Invalid certificate content")
            return False
        
        logger.info("✓ Certificate read successfully from local file")
        
    except FileNotFoundError:
        logger.error(f"Certificate file not found: {certificate_file_path}")
        return False
    except Exception as e:
        logger.error(f"Error reading certificate file: {e}")
        return False
    
    params = _get_appliance_connection_params(config, logger, appliance_name, user, password, prompt_regex)
    if not params:
        return False

    host, user, password, prompt_regex = params['host'], params['user'], params['password'], params['prompt_regex']
    appliance_type = params['appliance_type']

    logger.info(f"Appliance: {appliance_name} ({appliance_type}) at {host}")
    logger.info(f"User: {user}")
    
    try:
        client = ApplianceClient(
            host=host,
            user=user,
            password=password,
            prompt_regex=prompt_regex,
            initial_pattern=None,
            timeout=120,
            strip_ansi=True,
            debug=debug
        )
        
        if not client.connect():
            logger.error("Failed to connect to appliance")
            return False
        
        # Verify channel is available
        if client.channel is None:
            logger.error("SSH channel not available after connection")
            return False
        
        logger.info("\n➜ Importing S3 certificate for datalake...")
        logger.info("Executing: store certificate application datalake s3 console")
        
        import time
        import sys
        
        # Send command
        client.channel.send(b"store certificate application datalake s3 console\r")
        
        # Wait for prompt asking for certificate
        time.sleep(1)
        buf = ""
        deadline = time.time() + 30
        
        while time.time() < deadline:
            if client.channel.recv_ready():
                chunk = client.channel.recv(65535).decode(errors="replace")
                buf += chunk
                if debug:
                    print(f"[DEBUG] Received: {repr(chunk)}", file=sys.stderr)
                
                # Check if we see the certificate prompt
                if "Please paste your Trusted certificate below in PEM encoded format" in buf:
                    logger.info("✓ Certificate prompt detected")
                    break
            time.sleep(0.1)
        
        # Send certificate content line by line
        logger.info("Sending certificate content...")
        for line in certificate_content.splitlines():
            client.channel.send((line + "\n").encode())
            time.sleep(0.01)
        
        # Send CTRL+D to finish input
        logger.info("Sending CTRL+D...")
        time.sleep(0.5)
        client.channel.send(b"\x04")  # CTRL+D
        
        # Wait for completion message
        time.sleep(2)
        buf = ""
        deadline = time.time() + 60
        
        while time.time() < deadline:
            if client.channel.recv_ready():
                chunk = client.channel.recv(65535).decode(errors="replace")
                buf += chunk
                if debug:
                    print(f"[DEBUG] Received: {repr(chunk)}", file=sys.stderr)
            
            # Check for success message
            if "SUCCESS: Certificate imported successfully" in buf:
                logger.info("✓ SUCCESS: Certificate imported successfully")
                client.disconnect()
                logger.info("=" * 80)
                logger.info("Datalake S3 certificate imported successfully")
                logger.info("=" * 80)
                return True
            
            # Check if prompt returned (command completed)
            if client.prompt_re.search(buf):
                break
            
            time.sleep(0.1)
        
        client.disconnect()
        
        if "SUCCESS: Certificate imported successfully" in buf:
            logger.info("✓ SUCCESS: Certificate imported successfully")
            logger.info("=" * 80)
            logger.info("Datalake S3 certificate imported successfully")
            logger.info("=" * 80)
            return True
        else:
            logger.error("✗ Certificate import failed or success message not detected")
            logger.error(f"Output: {buf}")
            return False
        
    except Exception as e:
        logger.error(f"Error importing certificate: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def distribute_datalake_certificate(
    config,
    logger,
    appliance_name: str = "cm",
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    timeout: int = 300,
    check_interval: int = 10,
    debug: bool = False
) -> bool:
    
    from .appliance_config_loader import ApplianceConfigLoader
    from .appliance_client import ApplianceClient
    import time
    import re
    
    logger.info("=" * 80)
    logger.info(f"DISTRIBUTE DATALAKE CERTIFICATE FROM {appliance_name}")
    logger.info("=" * 80)
    
    # Get all appliances to determine expected entries
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    all_appliances = appliance_loader.get_all_appliances()
    
    # Count appnodes and collectors
    appnodes = [name for name, cfg in all_appliances.items() if cfg.get('type') == 'appnode']
    collectors = [name for name, cfg in all_appliances.items() if cfg.get('type') == 'collector']
    cms = [name for name, cfg in all_appliances.items() if cfg.get('type') == 'cm']

    # Every managed appliance (appnode + collector) gets 1 Success entry for datalake-s3-gui.
    # Exactly one appnode (the LTR node) gets an additional Success entry for datalake-gui.
    managed = len(appnodes) + len(collectors)
    expected_success_entries = managed + 1  # +1 for datalake-gui on LTR appnode
    expected_info_entries = 2  # CM entries (datalake-gui + datalake-s3-gui)

    logger.info(f"Expected distribution targets:")
    logger.info(f"  - Appnodes: {len(appnodes)} ({', '.join(appnodes)})")
    logger.info(f"  - Collectors: {len(collectors)} ({', '.join(collectors)})")
    logger.info(f"  - CM: {len(cms)} ({', '.join(cms)})")
    logger.info(f"Expected results:")
    logger.info(f"  - Success entries: {expected_success_entries} ({managed} x datalake-s3-gui + 1 x datalake-gui)")
    logger.info(f"  - INFO entries: {expected_info_entries}")
    
    # Get CM appliance config
    appliance_config = appliance_loader.get_appliance(appliance_name)
    if not appliance_config:
        logger.error(f"Appliance '{appliance_name}' not found in machines_info.json")
        return False
    
    appliance_type = appliance_config.get('type')
    host = appliance_config.get('ip')
    
    if not host:
        logger.error(f"No IP address configured for appliance '{appliance_name}'")
        return False
    
    if not user:
        if appliance_type:
            user = appliance_loader.get_default_user(appliance_type)
        else:
            user = "cli"
    
    if not password:
        password = config.get_custom_variable('cli_pwd')
    if not password:
        logger.error("Password not provided and cli_pwd not found in custom_variables")
        return False
    
    if not prompt_regex:
        if appliance_type:
            prompt_regex = appliance_loader.get_default_prompt(appliance_type, configured=True)
        if not prompt_regex:
            logger.error(f"No prompt_regex provided and no default found for type '{appliance_type}'")
            return False
    
    logger.info(f"Connecting to {appliance_name} ({appliance_type}) at {host}")
    
    try:
        client = ApplianceClient(
            host=host,
            user=user,
            password=password,
            prompt_regex=prompt_regex,
            initial_pattern=None,
            timeout=120,
            strip_ansi=True,
            debug=debug
        )
        
        if not client.connect():
            logger.error("Failed to connect to appliance")
            return False
        
        # Verify channel is available
        if client.channel is None:
            logger.error("SSH channel not available after connection")
            return False
        
        # Execute distribution command
        logger.info("\n➜ Executing certificate distribution...")
        logger.info("Command: distribute application certificate datalake all_managed true")
        
        try:
            output = client.execute_command("distribute application certificate datalake all_managed true", timeout=300)
            logger.info("✓ Distribution command executed")
            if debug:
                logger.debug(f"Output: {output}")
        except Exception as e:
            logger.error(f"Failed to execute distribution command: {e}")
            client.disconnect()
            return False
        
        # Monitor distribution status
        logger.info(f"\n➜ Monitoring distribution status (timeout: {timeout}s, check interval: {check_interval}s)...")
        
        start_time = time.time()
        success_count = 0
        info_count = 0
        
        while time.time() - start_time < timeout:
            time.sleep(check_interval)
            
            # Check status
            try:
                output = client.execute_command("distribute certificate showlog all", timeout=300)
            except Exception as e:
                logger.warning(f"Failed to check status: {e}")
                continue
            
            # Count Success and INFO entries
            success_count = len(re.findall(r'\bSuccess\b', output, re.IGNORECASE))
            info_count = len(re.findall(r'\bINFO\b', output))
            
            elapsed = int(time.time() - start_time)
            logger.info(f"[{elapsed}s] Status: Success={success_count}/{expected_success_entries}, INFO={info_count}/{expected_info_entries}")
            
            if debug:
                logger.debug(f"Current output:\n{output}")
            
            # Check if distribution is complete
            if success_count >= expected_success_entries and info_count >= expected_info_entries:
                logger.info("\n" + "=" * 80)
                logger.info("✓ CERTIFICATE DISTRIBUTION COMPLETED SUCCESSFULLY")
                logger.info("=" * 80)
                logger.info(f"Final status:")
                logger.info(f"  - Success entries: {success_count}/{expected_success_entries}")
                logger.info(f"  - INFO entries: {info_count}/{expected_info_entries}")
                logger.info(f"  - Time elapsed: {elapsed}s")
                
                if debug:
                    logger.debug(f"\nFinal output:\n{output}")
                
                client.disconnect()
                return True
        
        # Timeout reached
        logger.error("\n" + "=" * 80)
        logger.error("✗ CERTIFICATE DISTRIBUTION TIMEOUT")
        logger.error("=" * 80)
        logger.error(f"Distribution did not complete within {timeout}s")
        logger.error(f"Final status:")
        logger.error(f"  - Success entries: {success_count}/{expected_success_entries}")
        logger.error(f"  - INFO entries: {info_count}/{expected_info_entries}")
        
        # Show final output for debugging
        try:
            final_output = client.execute_command("distribute certificate showlog all", timeout=300)
            logger.error(f"\nFinal output:\n{final_output}")
        except Exception as e:
            logger.error(f"Failed to get final output: {e}")
        
        client.disconnect()
        return False
        
    except Exception as e:
        logger.error(f"Error during certificate distribution: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def activate_ltr(
    config,
    logger,
    appliance_name: str = "cm",
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = True
) -> bool:
    
    from .appliance_config_loader import ApplianceConfigLoader
    from .appliance_client import ApplianceClient
    
    logger.info("=" * 80)
    logger.info(f"ACTIVATE LTR (LONG TERM RETENTION) ON {appliance_name}")
    logger.info("=" * 80)
    
    # Get admin password from custom_variables
    admin_password = config.get_custom_variable('pwd')
    if not admin_password:
        logger.error("Admin password not found in custom_variables (pwd)")
        return False
    
    logger.info("✓ Admin password retrieved from custom_variables (pwd)")
    
    # Get CM appliance config
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
    
    if not user:
        if appliance_type:
            user = appliance_loader.get_default_user(appliance_type)
        else:
            user = "cli"
    
    if not password:
        password = config.get_custom_variable('cli_pwd')
    if not password:
        logger.error("Password not provided and cli_pwd not found in custom_variables")
        return False
    
    if not prompt_regex:
        if appliance_type:
            prompt_regex = appliance_loader.get_default_prompt(appliance_type, configured=True)
        if not prompt_regex:
            logger.error(f"No prompt_regex provided and no default found for type '{appliance_type}'")
            return False
    
    logger.info(f"Appliance: {appliance_name} ({appliance_type}) at {host}")
    logger.info(f"User: {user}")
    
    # Build the grdapi command
    command = (
        f'grdapi configure_complete_cold_storage '
        f'protocol="CUSTOM" '
        f'objectStorageEndpoint="https://raptor.demo.guardium:9000" '
        f'accessKey=minioadmin '
        f'secretKey="{admin_password}" '
        f'dataBucket=guardium-ltr '
        f'resultSchema="datalake_reports" '
        f'region="US_EAST_1" '
        f'coldCatalogEndpoint="thrift://appnode1.demo.guardium:9083" '
        f'coldCatalogSchema="datalake" '
        f'coldStorageName="datalake" '
        f'queryEngineHost="appnode1.demo.guardium" '
        f'debug=3'
    )
    
    logger.info("\n➜ Executing LTR activation command...")
    logger.info(f"Command: {command.replace(admin_password, '***')}")
    
    try:
        client = ApplianceClient(
            host=host,
            user=user,
            password=password,
            prompt_regex=prompt_regex,
            initial_pattern=None,
            timeout=300,
            strip_ansi=True,
            debug=debug
        )
        
        if not client.connect():
            logger.error("Failed to connect to appliance")
            return False
        
        # Execute the command with extended timeout (5 minutes)
        output = client.execute_command(command, timeout=300)
        
        client.disconnect()
        
        # Check for success indicators
        success_indicators = [
            "Cold Storage Maintenance Setup Completed",
            "Cold Storage ID:",
            "Cold Storage Name: datalake",
            '"status":"success"',
            "Complete cold storage configuration successful"
        ]
        
        found_indicators = []
        for indicator in success_indicators:
            if indicator.lower() in output.lower():
                found_indicators.append(indicator)
        
        logger.info("\n" + "=" * 80)
        if len(found_indicators) >= 3:
            logger.info("✓ LTR ACTIVATION SUCCESSFUL")
            logger.info("=" * 80)
            logger.info(f"Found {len(found_indicators)}/{len(success_indicators)} success indicators:")
            for indicator in found_indicators:
                logger.info(f"  ✓ {indicator}")
            
            if debug:
                logger.debug(f"\nFull output:\n{output}")
            
            return True
        else:
            logger.error("✗ LTR ACTIVATION FAILED")
            logger.error("=" * 80)
            logger.error(f"Found only {len(found_indicators)}/{len(success_indicators)} success indicators:")
            for indicator in found_indicators:
                logger.error(f"  ✓ {indicator}")
            logger.error(f"\nOutput:\n{output}")
            return False
        
    except Exception as e:
        logger.error(f"Error activating LTR: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def prepare_log_guard_dir(
    config,
    logger,
    appliance_name: str,
    cloudsupport_password: Optional[str] = None,
    debug: bool = False) -> bool:
    import paramiko

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    appliance_config = appliance_loader.get_appliance(appliance_name)
    if not appliance_config:
        logger.error(f"Appliance '{appliance_name}' not found")
        return False

    host = appliance_config.get('ip')
    if not host:
        logger.error(f"No IP for appliance '{appliance_name}'")
        return False

    if not cloudsupport_password:
        cloudsupport_password = config.get_custom_variable('cloudsupport_pwd')
    if not cloudsupport_password:
        logger.error("cloudsupport_pwd not found in custom_variables")
        return False

    cmds = [
        "sudo mkdir -p /var/log/guard",
        "sudo chmod 2775 /var/log/guard",
        "sudo chown root:guardium /var/log/guard",
        "sudo touch /var/log/guard/jobqueue.log",
        "sudo chmod 644 /var/log/guard/jobqueue.log",
        "sudo chown tomcat:guardium /var/log/guard/jobqueue.log",
    ]

    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh_client.connect(
            hostname=host,
            username='cloudsupport',
            password=cloudsupport_password,
            look_for_keys=False,
            allow_agent=False,
            timeout=30
        )
        logger.info(f"✓ Connected to {appliance_name} ({host})")
        for cmd in cmds:
            stdin, stdout, stderr = ssh_client.exec_command(cmd)
            rc = stdout.channel.recv_exit_status()
            if rc != 0:
                err = stderr.read().decode().strip()
                logger.error(f"✗ [{appliance_name}] '{cmd}' failed (rc={rc}): {err}")
                return False
            if debug:
                logger.info(f"  [{appliance_name}] {cmd} → ok")
        logger.info(f"✓ /var/log/guard prepared on {appliance_name}")
        return True
    except Exception as e:
        logger.error(f"✗ SSH failed on {appliance_name}: {e}")
        return False
    finally:
        ssh_client.close()

# Made with Bob

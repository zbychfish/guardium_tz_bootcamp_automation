#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Appliance Operations - Reusable functions for Guardium appliance operations
"""

import os
import time
import random
import re
import traceback
import paramiko
from typing import Optional, List, Callable, Dict, Any, Tuple
import concurrent.futures
from .appliance_client import ApplianceClient
from .appliance_config_loader import ApplianceConfigLoader

def _header(logger, title: str) -> None:
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)

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

    logger.info(f"➜ {operation_name} → {total} appliances, {max_workers} parallel")
    for a in appliances:
        logger.info(f"  ↳ {a}")

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
                msg = f" → {error}" if error else ""
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
    max_retries: int = 10,) -> bool:
    
    import traceback

    _header(logger, f"SETUP APPNODE: {appliance_name}")

    params = _get_appliance_connection_params(config, logger, appliance_name, user, password, prompt_regex)
    if not params:
        return False

    host = params['host']

    try:
        client = ApplianceClient(
            host=host, user=params['user'], password=params['password'],
            prompt_regex=params['prompt_regex'], initial_pattern=None,
            timeout=60, strip_ansi=True, debug=debug,
        )
        if not client.connect():
            logger.error(f"[{appliance_name}] ✗ failed to connect")
            return False

        logger.info(f"[{appliance_name}] ➜ store unit type app-node")
        try:
            client.execute_command_with_confirmation(
                command="store unit type app-node",
                confirmation_pattern=r"Are you sure you want to proceed\s*\(y/n\)\?",
                response="y",
                confirm_idle=0.2,
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
                    timeout=30, strip_ansi=True, debug=False,
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
                    logger.error(f"[{appliance_name}] ✗ unexpected unit type: {verify_result.strip()}")
                    return False
            except Exception:
                pass

        elapsed = int(time.time() - start_time)
        logger.error(f"[{appliance_name}] ✗ timeout ({elapsed}s, {max_retries} attempts)")
        return False

    except Exception as e:
        logger.error(f"[{appliance_name}] ✗ {e}")
        if debug:
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
            logger.info(f"[{appliance_name}] ⚠ purge_age_period skipped (type={appliance_type})")
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
            logger.warning(f"[{appliance_name}] multiple CMs: {list(cm_appliances.keys())} → using first")
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
                logger.warning(f"[{appliance_name}] ⚠ registration unclear → treating as success")
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
            _log(f"⚠ ip={ip_address}{prefix} → unexpected response", 'warning')

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

        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(
            hostname=host, username='cloudsupport', password=cloudsupport_password,
            look_for_keys=False, allow_agent=False, timeout=30
        )

        try:
            stdin, stdout, _ = ssh_client.exec_command('which sshpass')
            sshpass_available = stdout.channel.recv_exit_status() == 0

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

            logger.info(f"[{appliance_name}] ✓ {len(patch_files)} patch files copied to /tmp/")

            stdin, stdout, stderr = ssh_client.exec_command('sudo mkdir -p /var/IBM/Guardium/log/patches/')
            if stdout.channel.recv_exit_status() != 0:
                logger.error(f"[{appliance_name}] mkdir failed: {stderr.read().decode()}")
                ssh_client.close()
                return False

            stdin, stdout, stderr = ssh_client.exec_command('sudo mv /tmp/*.sig /var/IBM/Guardium/log/patches/ && sudo chown tomcat:tomcat /var/IBM/Guardium/log/patches/*.sig')
            if stdout.channel.recv_exit_status() != 0:
                logger.error(f"[{appliance_name}] mv/chown failed: {stderr.read().decode()}")
                ssh_client.close()
                return False

            logger.info(f"[{appliance_name}] ✓ patch files moved to /var/IBM/Guardium/log/patches/")
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

        patch_output = cli_client.execute_command("show system patch available", timeout=300)
        logger.info(f"[{appliance_name}] available patches:\n{patch_output.strip()}")
        cli_client.disconnect()

        logger.info(f"[{appliance_name}] ✓ ready for patching")
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

    params = _get_appliance_connection_params(config, logger, appliance_name)
    if not params:
        return False

    host = params['host']

    if not cloudsupport_password:
        cloudsupport_password = config.get_custom_variable('cloudsupport_pwd')
        if not cloudsupport_password:
            logger.error(f"[{appliance_name}] cloudsupport_pwd not found in custom_variables")
            return False

    if not os.path.exists(source_dir):
        logger.error(f"[{appliance_name}] source dir not found: {source_dir}")
        return False

    files_to_copy = glob.glob(os.path.join(source_dir, file_pattern))
    if not files_to_copy:
        logger.error(f"[{appliance_name}] no files matching '{file_pattern}' in {source_dir}")
        return False

    _header(logger, f"COPY FILES TO APPLIANCE: {appliance_name}")
    logger.info(f"[{appliance_name}] {len(files_to_copy)} file(s) ➜ {target_dir}")

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

        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(hostname=host, username='cloudsupport', password=cloudsupport_password,
                           look_for_keys=False, allow_agent=False, timeout=30)

        stdin, stdout, _ = ssh_client.exec_command('which sshpass')
        sshpass_available = stdout.channel.recv_exit_status() == 0

        for file_path in files_to_copy:
            filename = os.path.basename(file_path)
            logger.info(f"[{appliance_name}] ➜ scp {filename}")
            if sshpass_available:
                scp_command = (f"sshpass -p '{raptor_root_password}' scp -P {ssh_port} "
                               f"-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
                               f"root@{raptor_ip}:{file_path} /tmp/{filename}")
                stdin, stdout, stderr = ssh_client.exec_command(scp_command)
                if stdout.channel.recv_exit_status() != 0:
                    logger.error(f"[{appliance_name}] ✗ scp {filename}: {stderr.read().decode()}")
                    ssh_client.close()
                    return False
            else:
                channel = ssh_client.invoke_shell()
                time.sleep(0.5)
                if channel.recv_ready():
                    channel.recv(65535)
                channel.send((f"scp -P {ssh_port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
                               f"root@{raptor_ip}:{file_path} /tmp/{filename}\n").encode())
                output = ""
                deadline = time.time() + 30
                while time.time() < deadline:
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
                stdin, stdout, _ = ssh_client.exec_command(f"test -f /tmp/{filename} && echo 'OK'")
                if stdout.read().decode().strip() != "OK":
                    logger.error(f"[{appliance_name}] ✗ scp {filename} failed")
                    ssh_client.close()
                    return False

        logger.info(f"[{appliance_name}] ✓ {len(files_to_copy)} file(s) in /tmp/")

        stdin, stdout, stderr = ssh_client.exec_command(f'sudo mkdir -p {target_dir}')
        if stdout.channel.recv_exit_status() != 0:
            logger.error(f"[{appliance_name}] ✗ mkdir {target_dir}: {stderr.read().decode()}")
            ssh_client.close()
            return False

        logger.info(f"[{appliance_name}] ➜ mv /tmp/{file_pattern} {target_dir} && chown {owner}")
        stdin, stdout, stderr = ssh_client.exec_command(
            f'sudo mv /tmp/{file_pattern} {target_dir} && sudo chown {owner} {target_dir}/{file_pattern}')
        if stdout.channel.recv_exit_status() != 0:
            logger.error(f"[{appliance_name}] ✗ mv/chown: {stderr.read().decode()}")
            ssh_client.close()
            return False

        ssh_client.close()
        logger.info(f"[{appliance_name}] ✓ files in {target_dir}")
        return True

    except Exception as e:
        import traceback
        logger.error(f"[{appliance_name}] ✗ {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False

def copy_single_file_to_appliance(
    config,
    logger,
    appliance_name: str,
    source_file_path: str,
    target_dir: str = "/var/IBM/Guardium/log/patches/",
    owner: str = "tomcat:tomcat",
    cloudsupport_password: Optional[str] = None,
    debug: bool = True,) -> bool:
    
    if not source_file_path:
        logger.error("source_file_path is required")
        return False

    params = _get_appliance_connection_params(config, logger, appliance_name)
    if not params:
        return False

    host = params['host']

    if not cloudsupport_password:
        cloudsupport_password = config.get_custom_variable('cloudsupport_pwd')
        if not cloudsupport_password:
            logger.error(f"[{appliance_name}] cloudsupport_pwd not found in custom_variables")
            return False

    if not os.path.exists(source_file_path):
        logger.error(f"[{appliance_name}] source file not found: {source_file_path}")
        return False

    raptor_ip = config.get_machine_ip('raptor', use_private=True)
    if not raptor_ip:
        logger.error(f"[{appliance_name}] raptor IP not found")
        return False

    raptor_root_password = config.get_custom_variable('pwd')
    if not raptor_root_password:
        logger.error(f"[{appliance_name}] pwd not found in custom_variables")
        return False

    filename = os.path.basename(source_file_path)
    ssh_port = config.config.get('ssh', {}).get('port', 22)

    _header(logger, f"COPY FILE TO APPLIANCE: {appliance_name}")
    logger.info(f"[{appliance_name}] {filename} -> {target_dir}")

    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh_client.connect(hostname=host, username='cloudsupport', password=cloudsupport_password,
                           look_for_keys=False, allow_agent=False, timeout=30)

        _, stdout, _ = ssh_client.exec_command('which sshpass')
        sshpass_available = stdout.channel.recv_exit_status() == 0

        logger.info(f"[{appliance_name}] -> scp {filename}")
        if sshpass_available:
            scp_cmd = (f"sshpass -p '{raptor_root_password}' scp -P {ssh_port} "
                       f"-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
                       f"root@{raptor_ip}:{source_file_path} /tmp/{filename}")
            _, stdout, stderr = ssh_client.exec_command(scp_cmd, timeout=300)
            if stdout.channel.recv_exit_status() != 0:
                logger.error(f"[{appliance_name}] x scp failed: {stderr.read().decode()}")
                return False
        else:
            channel = ssh_client.invoke_shell()
            time.sleep(0.5)
            while channel.recv_ready():
                channel.recv(65535)
            channel.send((f"scp -P {ssh_port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
                          f"root@{raptor_ip}:{source_file_path} /tmp/{filename}\n").encode())
            output = ""
            deadline = time.time() + 30
            while time.time() < deadline:
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

        _, stdout, _ = ssh_client.exec_command(f"test -f /tmp/{filename} && echo 'OK'")
        if stdout.read().decode().strip() != "OK":
            logger.error(f"[{appliance_name}] x scp {filename} failed")
            return False
        logger.info(f"[{appliance_name}] + {filename} in /tmp/")

        logger.info(f"[{appliance_name}] -> mkdir -p {target_dir}")
        _, stdout, stderr = ssh_client.exec_command(f'sudo mkdir -p {target_dir}')
        if stdout.channel.recv_exit_status() != 0:
            logger.error(f"[{appliance_name}] x mkdir {target_dir}: {stderr.read().decode()}")
            return False

        logger.info(f"[{appliance_name}] -> mv /tmp/{filename} {target_dir} && chown {owner}")
        _, stdout, stderr = ssh_client.exec_command(
            f'sudo mv /tmp/{filename} {target_dir} && sudo chown {owner} {target_dir}/{filename}')
        if stdout.channel.recv_exit_status() != 0:
            logger.error(f"[{appliance_name}] x mv/chown: {stderr.read().decode()}")
            return False

        logger.info(f"[{appliance_name}] ✓ {filename} → {target_dir}")
        return True

    except Exception as e:
        logger.error(f"[{appliance_name}] x {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh_client.close()

def get_patch_installation_order(
    config,
    logger,
    appliance_name: str,
    patch_order_file: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/patches/patch_order.txt",
    debug: bool = True) -> Optional[str]:

    import os

    _header(logger, "GET PATCH INSTALLATION ORDER")

    if not os.path.exists(patch_order_file):
        logger.error(f"patch order file not found: {patch_order_file}")
        return None

    try:
        with open(patch_order_file, 'r') as f:
            patch_order = [line.strip() for line in f if line.strip()]
    except Exception as e:
        logger.error(f"failed to read patch order file: {e}")
        return None

    if not patch_order:
        logger.error("no patches found in patch_order.txt")
        return None

    sorted_patches = sorted(patch_order)

    patch_positions = []
    for patch_spec in patch_order:
        try:
            position = sorted_patches.index(patch_spec) + 1
            patch_positions.append(str(position))
            logger.info(f"  {patch_spec} ➜ position {position}")
        except ValueError:
            logger.warning(f"  {patch_spec} ➜ NOT FOUND in sorted list")

    if not patch_positions:
        logger.error("no patches mapped from patch_order.txt")
        return None

    patch_selection = ','.join(patch_positions)
    logger.info(f"✓ patch order: {patch_selection}")
    return patch_selection

def install_patch_on_appliance(
    config,
    logger,
    appliance_name: str,
    patch_selection: str,
    reinstall_answer: str = "y",
    user: Optional[str] = None,
    password: Optional[str] = None,
    debug: bool = False,) -> bool:
    
    import socket

    if not patch_selection:
        logger.error("patch_selection is required")
        return False

    params = _get_appliance_connection_params(config, logger, appliance_name, user, password)
    if not params:
        return False

    host, user, password, prompt_regex = params['host'], params['user'], params['password'], params['prompt_regex']
    appliance_type = params['appliance_type']

    _header(logger, f"INSTALL PATCHES: {appliance_name}")
    logger.info(f"[{appliance_name}] ({appliance_type}) at {host} | selection={patch_selection}")

    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    try:
        import socket
        client = ApplianceClient(
            host=host, user=user, password=password,
            prompt_regex=prompt_regex, initial_pattern=None,
            timeout=60, strip_ansi=True, debug=debug
        )

        if not client.connect():
            logger.error(f"[{appliance_name}] failed to connect")
            return False

        channel = client.channel
        if not channel:
            logger.error(f"[{appliance_name}] no SSH channel available")
            client.disconnect()
            return False

        channel.settimeout(0.1)

        command = "store system patch install sys"
        logger.info(f"[{appliance_name}] ➜ {command}")
        channel.send((command + "\r").encode())

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
                        logger.debug(f"[{appliance_name}] recv: {ansi_escape.sub('', chunk)}")
                    buf_clean = ansi_escape.sub('', buf)

                    if not patch_selected and ("Please choose patches" in buf_clean or "or q to quit" in buf_clean):
                        last_line = buf_clean.strip().split('\n')[-1]
                        if last_line.endswith(':'):
                            time.sleep(1.0)
                            try:
                                extra = channel.recv(4096).decode('utf-8', errors='replace')
                                if extra:
                                    buf += extra
                                    if debug:
                                        logger.debug(f"[{appliance_name}] recv: {ansi_escape.sub('', extra)}")
                            except:
                                pass
                            logger.info(f"[{appliance_name}] ➜ patch selection: {patch_selection}")
                            channel.send((patch_selection + "\r").encode())
                            patch_selected = True
                            last_activity = time.time()
                            time.sleep(0.5)

                    if patch_selected and not reinstall_answered and "Do you really want to install again" in buf_clean:
                        if "(yes or no)?" in buf_clean:
                            time.sleep(1.0)
                            try:
                                extra = channel.recv(4096).decode('utf-8', errors='replace')
                                if extra:
                                    buf += extra
                                    if debug:
                                        logger.debug(f"[{appliance_name}] recv: {ansi_escape.sub('', extra)}")
                            except:
                                pass
                            logger.info(f"[{appliance_name}] ➜ reinstall answer: {reinstall_answer}")
                            channel.send((reinstall_answer + "\r").encode())
                            reinstall_answered = True
                            last_activity = time.time()
                            time.sleep(0.5)

                    if patch_selected and prompt_regex and re.search(prompt_regex, buf_clean):
                        time.sleep(1)
                        try:
                            while True:
                                chunk = channel.recv(4096).decode('utf-8', errors='replace')
                                if chunk:
                                    if debug:
                                        logger.debug(f"[{appliance_name}] recv: {ansi_escape.sub('', chunk)}")
                                else:
                                    break
                        except:
                            pass
                        client.disconnect()
                        logger.info(f"[{appliance_name}] ✓ patch install command completed")
                        time.sleep(10)
                        return monitor_patch_installation(
                            config=config, logger=logger, appliance_name=appliance_name,
                            patch_numbers=None, check_interval=60, max_checks=60,
                            user=user, password=password, debug=debug
                        )

            except socket.timeout:
                if time.time() - last_activity > 300:
                    logger.warning(f"[{appliance_name}] ⚠ no activity for 5 minutes")
                    break
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"[{appliance_name}] ✗ {e}")
                break

            if channel.closed:
                logger.warning(f"[{appliance_name}] ⚠ channel closed unexpectedly")
                break

        client.disconnect()
        logger.warning(f"[{appliance_name}] ⚠ patch installation may not have completed")
        return False

    except Exception as e:
        import traceback
        logger.error(f"[{appliance_name}] ✗ {e}")
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
    debug: bool = False) -> bool:
    
    params = _get_appliance_connection_params(config, logger, appliance_name, user, password)
    if not params:
        return False

    host, user, password, prompt_regex = params['host'], params['user'], params['password'], params['prompt_regex']
    appliance_type = params['appliance_type']

    _header(logger, f"MONITOR PATCH INSTALLATION: {appliance_name}")
    logger.info(f"[{appliance_name}] interval={check_interval}s max={max_checks} (timeout={check_interval * max_checks}s)")

    check_count = 0

    while check_count < max_checks:
        check_count += 1
        logger.info(f"[{appliance_name}] check {check_count}/{max_checks}")

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
                logger.warning(f"[{appliance_name}] ⚠ connect failed, retrying in {check_interval}s")
                time.sleep(check_interval)
                continue

            logger.info(f"[{appliance_name}] ➜ show system patch install")
            output = client.execute_command("show system patch install")
            client.disconnect()

            if not output:
                logger.warning(f"[{appliance_name}] ⚠ no output, retrying in {check_interval}s")
                time.sleep(check_interval)
                continue

            if debug:
                logger.info(f"[{appliance_name}] patch status:\n{output}")

            patch_status = {}
            for line in output.split('\n'):
                ls = line.strip()
                if not ls or ls.startswith('P#') or 'Request Time' in ls:
                    continue
                m = re.match(r'^(\d+)\s+', ls)
                if m:
                    patch_status[m.group(1)] = ls

            patch_numbers_to_check = patch_numbers or list(patch_status.keys())

            if not patch_numbers_to_check:
                logger.warning(f"[{appliance_name}] ⚠ no patches found, retrying in {check_interval}s")
                time.sleep(check_interval)
                continue

            done_patches = []
            fail_patches = []
            in_progress = 0

            for patch_num in patch_numbers_to_check:
                if patch_num not in patch_status:
                    fail_patches.append(patch_num)
                    continue
                sl = patch_status[patch_num]
                if "DONE: Patch installation Succeeded" in sl:
                    done_patches.append(patch_num)
                elif patch_num == "9997" and "WARNING:" in sl:
                    done_patches.append(patch_num)
                elif "FAIL" in sl.upper() or "ERROR" in sl.upper():
                    fail_patches.append(patch_num)
                else:
                    in_progress += 1

            done_str = ", ".join(done_patches) if done_patches else "→"
            logger.info(f"[{appliance_name}]: installed={done_str} | ✓ {in_progress} | ✗ {len(fail_patches)}")

            if in_progress == 0:
                if fail_patches:
                    logger.error(f"[{appliance_name}] ✗ failed patches: {', '.join(fail_patches)}")
                    return False
                logger.info(f"[{appliance_name}] ✓ all patches installed successfully")
                return True

            time.sleep(check_interval)

        except Exception as e:
            import traceback
            logger.warning(f"[{appliance_name}] ⚠ check error: {e}")
            if debug:
                logger.error(traceback.format_exc())
            time.sleep(check_interval)

    logger.error(f"[{appliance_name}] ✗ timeout after {max_checks} checks")
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
    debug: bool = True) -> bool:
    
    import os
    import glob

    _header(logger, f"INSTALL AND MONITOR PATCHES: {appliance_name}")

    patches_dir = "/opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/patches/"
    patch_numbers = None

    try:
        sig_files = sorted(glob.glob(os.path.join(patches_dir, "*.sig")))
        if not sig_files:
            logger.error(f"no *.sig files found in {patches_dir}")
            return False

        available_patches = {}
        for i, sig_file in enumerate(sig_files, 1):
            filename = os.path.basename(sig_file)
            m = re.search(r'p(\d+)', filename)
            if m:
                available_patches[i] = m.group(1)
                logger.info(f"  {i}: {filename} ➜ patch {m.group(1)}")
            else:
                logger.warning(f"  {i}: {filename} ➜ patch number not found")

        if not available_patches:
            logger.error("could not extract patch numbers from *.sig files")
            return False

        patch_numbers = []
        for pos_str in [p.strip() for p in patch_selection.split(',')]:
            try:
                pos = int(pos_str)
                if pos in available_patches:
                    patch_numbers.append(available_patches[pos])
                    logger.info(f"  position {pos} ➜ patch {available_patches[pos]}")
                else:
                    logger.warning(f"  position {pos} ➜ not found (range: 1-{len(available_patches)})")
            except ValueError:
                logger.warning(f"  invalid position: {pos_str}")

        if not patch_numbers:
            logger.error("could not determine patch numbers from selection")
            return False

        logger.info(f"➜ monitoring patches: {', '.join(patch_numbers)}")

    except Exception as e:
        import traceback
        logger.warning(f"[{appliance_name}] ⚠ could not resolve patch numbers: {e} → monitoring all")
        if debug:
            logger.error(traceback.format_exc())
        patch_numbers = None

    if not install_patch_on_appliance(
        config=config, logger=logger, appliance_name=appliance_name,
        patch_selection=patch_selection, reinstall_answer=reinstall_answer,
        user=user, password=password, debug=debug
    ):
        return False

    logger.info(f"[{appliance_name}] ✓ waiting {check_interval}s before monitoring")
    time.sleep(check_interval)

    if not monitor_patch_installation(
        config=config, logger=logger, appliance_name=appliance_name,
        patch_numbers=patch_numbers, check_interval=check_interval,
        max_checks=max_checks, user=user, password=password, debug=False
    ):
        return False

    logger.info(f"[{appliance_name}] ✓ patches installed and verified")
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
    debug: bool = False) -> bool:
    
    from core.guardium_rest_api import create_guardium_api

    _header(logger, f"INSTALL GIM MODULE: {module}")
    logger.info(f"appliance={appliance_name} client={client_ip} module={module} version={module_version}")

    if not demo_password:
        demo_password = config.get_custom_variable('pwd')
    if not demo_password:
        logger.error("demo password required → set 'pwd' in custom_variables")
        return False

    try:
        api = create_guardium_api(config, logger, appliance_name)

        logger.info(f"➜ authenticate as {demo_user}")
        token = api.get_token(username=demo_user, password=demo_password)
        logger.info("✓ authenticated")
        if debug:
            logger.info(f"  token: {token[:30]}...")

        logger.info(f"➜ gim_client_assign client={client_ip} module={module} version={module_version}")
        assign_response = api.gim_client_assign(client_ip=client_ip, module=module, module_version=module_version)
        logger.info("✓ module assigned")
        if debug:
            logger.info(f"  response: {assign_response}")

        if params:
            for param_name, param_value in params.items():
                logger.info(f"➜ gim_client_params {param_name}={param_value}")
                param_response = api.gim_client_params(client_ip=client_ip, param_name=param_name, param_value=str(param_value))
                if debug:
                    logger.info(f"  response: {param_response}")
            logger.info(f"✓ {len(params)} parameter(s) set")

        logger.info(f"➜ gim_schedule_install client={client_ip} date=now")
        schedule_response = api.gim_schedule_install(client_ip=client_ip, date="now")
        logger.info("✓ installation scheduled")
        if debug:
            logger.info(f"  response: {schedule_response}")

        if monitor_installation:
            logger.info(f"⌛ waiting {installation_delay}s before monitoring")
            time.sleep(installation_delay)

            pending = ["initial"]
            check_count = 0
            while pending:
                check_count += 1
                logger.info(f"➜ gim_list_client_modules check #{check_count}")
                modules = api.gim_list_client_modules(client_ip=client_ip)

                if "ErrorCode" in modules or "ErrorMessage" in modules:
                    logger.error(f"✗ API error: {modules.get('ErrorCode')} → {modules.get('ErrorMessage')}")
                    return False

                msg = modules.get("Message", "")
                if not msg:
                    logger.warning("⚠ API returned empty Message")

                entries = [e.strip() for e in re.split(r"#+\s*ENTRY\s+\d+\s*#+", msg) if e.strip()]

                result = []
                for entry in entries:
                    entry_str = str(entry)
                    def g(p):
                        m = re.search(p, entry_str)
                        return m.group(1) if m else None
                    result.append({
                        "module_id": g(r"MODULE_ID:\s+(-?\d+)"),
                        "name": g(r"NAME:\s+([A-Z0-9\-]+)"),
                        "installed_version": g(r"INSTALLED_VERSION\s+([0-9][^\s]+)"),
                        "scheduled_version": g(r"SCHEDULED_VERSION\s+([0-9][^\s]+)"),
                        "state": g(r"STATE:\s+([A-Z\-]+)"),
                        "is_scheduled": g(r"IS_SCHEDULED:\s+([NY])"),
                        "schedule_time": g(r"IS_SCHEDULED:\s+[NY]\s+\(([^)]+)\)")
                    })

                pending = [m for m in result if m["state"] != "INSTALLED"]
                if pending:
                    for m in pending:
                        logger.info(f"  ⌛ {m['name']}: {m['state']}")
                    time.sleep(30)
                else:
                    for m in result:
                        logger.info(f"  ✓ {m['name']}: {m['state']} v{m['installed_version']}")

        logger.info(f"✓ GIM module {module} installed on {client_ip}")
        return True

    except Exception as e:
        import traceback
        logger.error(f"✗ {e}")
        if debug:
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
                logger.info(f"  [{appliance_name}] {cmd} ➜ ok")
        logger.info(f"✓ /var/log/guard prepared on {appliance_name}")
        return True
    except Exception as e:
        logger.error(f"✗ SSH failed on {appliance_name}: {e}")
        return False
    finally:
        ssh_client.close()

# Made with Bob

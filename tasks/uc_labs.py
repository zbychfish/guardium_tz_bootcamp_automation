#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import glob
import os
import time
import traceback
from typing import Optional

from core.appliance_client import ApplianceClient
from core.appliance_config_loader import ApplianceConfigLoader
from core.appliance_operations import _get_appliance_connection_params
from core.guardium_rest_api import create_guardium_api
from core.logger import get_logger
from core.ssh_client import SSHClient

logger = get_logger(__name__)

def _header(logger, title: str) -> None:
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)

def install_filebeat_on_sauropod(
    config,
    logger,
    verbose: bool = False,
    rpms_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/rpms",
    filebeat_pattern: str = "filebeat-*.rpm",
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, "INSTALL FILEBEAT ON SAUROPOD")

    machines = config.get('machines', {})
    sauropod_info = machines.get('sauropod', {})
    sauropod_ip = sauropod_info.get('private_ip')
    sauropod_password = sauropod_info.get('password')

    if not sauropod_ip:
        logger.error("✗ sauropod private_ip not found in machines config")
        return False
    if not sauropod_password:
        logger.error("✗ sauropod password not found in machines config")
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

        logger.info(f"➜ dnf -y install {remote_rpm_path}")
        result = ssh.execute_command(f"dnf -y install {remote_rpm_path}", timeout=300, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ dnf install failed: {result['stderr']}")
            return False
        logger.info("✓ filebeat installed")

        for cmd in [
            r"sed -i '/^- type: filestream/,/^[^[:space:]]/c\- type: filestream\n  id: \"cassandra\"\n  enabled: true\n  paths:\n    - /var/log/cassandra/audit/audit.log\n  exclude_lines: [\"AuditLogManager\"]\n  tags: [\"cassandra\"]\n  multiline.type: pattern\n  multiline.pattern: \"^INFO\"\n  multiline.negate: true\n  multiline.match: after' /etc/filebeat/filebeat.yml",
            r"sed -i '/^output.elasticsearch:/,/^[^[:space:]]/ { s/^/# / }' /etc/filebeat/filebeat.yml",
            r"sed -i '/^#output.logstash:/,/^[^[:space:]]/ { s/^#output\.logstash:/output.logstash:/; s|^  #hosts:.*|  hosts: [\"coll1.demo.com:5047\"]| }' /etc/filebeat/filebeat.yml",
        ]:
            result = ssh.execute_command(cmd, print_output=verbose)
            if result['rc'] != 0:
                logger.warning(f"⚠ config command failed (rc={result['rc']}): {cmd[:60]}…")
                if debug:
                    logger.debug(f"  stderr: {result['stderr']}")
        logger.info("✓ filebeat configured")

        logger.info("➜ systemctl start filebeat")
        result = ssh.execute_command("systemctl start filebeat", print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ start failed: {result['stderr']}")
            return False

        logger.info("➜ systemctl enable filebeat")
        result = ssh.execute_command("systemctl enable filebeat", print_output=verbose)
        if result['rc'] != 0:
            logger.warning(f"⚠ enable failed: {result['stderr']}")

        logger.info("✓ filebeat started and enabled")
        return True

    except Exception as e:
        logger.error(f"✗ {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

def setup_kafka_node(
    config,
    logger,
    appliance_name: str,
    user: Optional[str] = None,
    password: Optional[str] = None,
    prompt_regex: Optional[str] = None,
    debug: bool = False,
    retry_interval: int = 60,
    max_retries: int = 10) -> bool:

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
            logger.error(f"[{appliance_name}] ✗ failed to connect")
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

def run_uc_and_setup_kafka_node(
    config,
    logger,
    verbose: bool = False,
    collector_appliance: str = "coll1",
    kafka_appliance: str = "kafka1",
    debug: bool = False,
    **kwargs) -> bool:
    
    _header(logger, "RUN UC AND SETUP KAFKA NODE")

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    coll_config = appliance_loader.get_appliance(collector_appliance)
    if not coll_config:
        logger.error(f"✗ Appliance '{collector_appliance}' not found")
        return False

    coll_host = coll_config.get('ip')
    coll_type = coll_config.get('type')
    cli_pwd = config.get_custom_variable('cli_pwd')
    if not cli_pwd:
        logger.error("✗ cli_pwd not found in custom_variables")
        return False

    coll_prompt = appliance_loader.get_default_prompt(coll_type, configured=True) if coll_type else r">"

    logger.info(f"➜ grdapi run_universal_connector on {collector_appliance}")
    client = ApplianceClient(host=coll_host, user="cli", password=cli_pwd, prompt_regex=coll_prompt,
                             initial_pattern=None, timeout=300, strip_ansi=True, debug=debug)
    if not client.connect():
        logger.error(f"✗ Failed to connect to {collector_appliance}")
        return False

    result = client.execute_command("grdapi run_universal_connector", timeout=120)
    if verbose:
        logger.info(f"Output: {result}")
    logger.info("✓ run_universal_connector executed")

    logger.info("➜ grdapi get_universal_connector_status")
    status = client.execute_command("grdapi get_universal_connector_status", timeout=60)
    client.disconnect()
    if "Guardium Universal Connector is running" not in status:
        logger.error(f"✗ Unexpected UC status: {status}")
        return False
    logger.info("✓ Guardium Universal Connector is running")

    logger.info(f"➜ setup_kafka_node on {kafka_appliance}")
    if not setup_kafka_node(config=config, logger=logger, appliance_name=kafka_appliance, debug=debug):
        return False

    logger.info("⌛ Waiting 1 minute...")
    time.sleep(60)
    logger.info("✓ RUN UC AND SETUP KAFKA NODE — completed")
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
    **kwargs) -> bool:

    _header(logger, "REGISTER KAFKA CLUSTER")

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("✗ pwd not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    logger.info(f"  cluster={cluster_name} members={member_list} cruise_control={apply_cruise_control}")

    registered = False
    for attempt in range(1, 11):
        logger.info(f"➜ create_kafka_cluster (attempt {attempt}/10)")
        result = api.create_kafka_cluster(
            cluster_name=cluster_name,
            member_list=member_list,
            apply_cruise_control=apply_cruise_control
        )
        if debug:
            logger.info(f"  API response: {result}")
        if isinstance(result, dict) and result.get('ErrorCode'):
            logger.warning(f"⚠ attempt {attempt}/10 failed (ErrorCode {result['ErrorCode']}): {result.get('ErrorMessage', '')} — retrying in 60s...")
            time.sleep(60)
        else:
            logger.info(f"✓ cluster registration accepted (attempt {attempt}/10)")
            registered = True
            break

    if not registered:
        logger.error("✗ Kafka cluster registration failed after 10 attempts")
        return False

    for attempt in range(1, 7):
        logger.info(f"➜ get_kafka_clusters (attempt {attempt}/6)")
        clusters = api.get_kafka_clusters()
        if debug:
            logger.info(f"  response: {clusters}")

        if isinstance(clusters, list):
            items = clusters
        elif isinstance(clusters, dict):
            items = next((v for k, v in clusters.items() if isinstance(v, list)), [])
        else:
            items = []

        if any(c.get('name') == cluster_name or c.get('clusterName') == cluster_name
               for c in items if isinstance(c, dict)):
            logger.info(f"✓ Kafka cluster '{cluster_name}' confirmed")
            break

        if attempt < 6:
            logger.warning(f"⚠ cluster not found yet (attempt {attempt}/6), waiting 60s...")
            time.sleep(60)
    else:
        logger.error(f"✗ Kafka cluster '{cluster_name}' not found after 6 attempts")
        return False

    logger.info("⌛ Waiting 5 minutes for Kafka cluster to stabilize...")
    time.sleep(300)
    logger.info("✓ Kafka cluster registration completed")
    return True

def cycle_kafka_nodes(
    config,
    logger,
    verbose: bool = False,
    cm_appliance: str = "cm",
    cluster_name: str = "kafka_cluster_1",
    member_list: str = "kafka1.demo.guardium",
    stop_wait_seconds: int = 300,
    start_wait_seconds: int = 900,
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, "CYCLE KAFKA NODES (stop → start)")

    params = _get_appliance_connection_params(config, logger, cm_appliance)
    if not params:
        return False

    steps = [
        ("stop",  f"grdapi stop_kafka_nodes  clusterName={cluster_name} memberList={member_list}", stop_wait_seconds),
        ("start", f"grdapi start_kafka_nodes clusterName={cluster_name} memberList={member_list}", start_wait_seconds),
    ]

    for action, cmd, wait_after in steps:
        client = ApplianceClient(
            host=params['host'], user=params['user'], password=params['password'],
            prompt_regex=params['prompt_regex'], initial_pattern=None,
            timeout=120, strip_ansi=True, debug=debug, logger=logger
        )
        try:
            if not client.connect():
                logger.error(f"✗ failed to connect to {cm_appliance} for '{action}'")
                return False
            logger.info(f"➜ {action}: {cmd}")
            result = client.execute_command(cmd, timeout=120)
            if debug:
                logger.info(f"  output: {result}")
            logger.info(f"✓ {action} executed")
        except Exception as e:
            logger.error(f"✗ {action} failed: {e}")
            logger.error(traceback.format_exc())
            return False
        finally:
            client.disconnect()

        logger.info(f"⌛ waiting {wait_after}s ({wait_after // 60} min)...")
        time.sleep(wait_after)

    logger.info("✓ CYCLE KAFKA NODES — completed")
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
    **kwargs) -> bool:

    _header(logger, "CREATE UC CREDENTIAL FOR ORACLE CONTAINER")

    if not cred_password:
        cred_password = config.get_custom_variable('simple_pwd')
    if not cred_password:
        logger.error("✗ cred_password not provided and 'simple_pwd' not found in custom_variables")
        return False

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("✗ pwd not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    logger.info(f"➜ create_uc_credential name={credential_name} type={credential_type} username={cred_username}")
    result = api.create_uc_credential(
        name=credential_name,
        credential_type=credential_type,
        parameters={"username": cred_username, "password": cred_password}
    )
    if debug:
        logger.info(f"  API response: {result}")
    logger.info("✓ UC credential created")
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
    **kwargs) -> bool:

    _header(logger, "IMPORT UC PROFILE")

    logger.info(f"  csv={csv_path}")
    logger.info(f"  jar={jar_file}")
    logger.info(f"  update_mode={update_mode} test_connections={test_connections}")

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("✗ pwd not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    logger.info("➜ import_profiles_from_file")
    result = api.import_profiles_from_file(
        csv_path=csv_path,
        jar_file=jar_file,
        update_mode=update_mode,
        test_connections=test_connections
    )
    if debug:
        logger.info(f"  API response: {result}")
    logger.info("✓ UC profile imported")

    logger.info("⌛ Waiting 1 minute for UC profile to be processed...")
    time.sleep(60)
    logger.info("✓ Wait completed")
    return True

def bulk_install_uc_profile(
    config,
    logger,
    verbose: bool = False,
    cm_appliance: str = "cm",
    profile_names: str = "oracle_21_container_sauropod",
    bulk_install_hosts: str = "coll1.demo.guardium",
    debug: bool = True,
    **kwargs) -> bool:

    _header(logger, "BULK INSTALL UC PROFILE")
    
    logger.info(f"  profileNames={profile_names} hosts={bulk_install_hosts}")

    cli_pwd = config.get_custom_variable('cli_pwd')
    if not cli_pwd:
        logger.error("✗ cli_pwd not found in custom_variables")
        return False

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    cm_config = appliance_loader.get_appliance(cm_appliance)
    if not cm_config:
        logger.error(f"✗ Appliance '{cm_appliance}' not found")
        return False

    cm_host = cm_config.get('ip')
    cm_type = cm_config.get('type')
    cm_prompt = appliance_loader.get_default_prompt(cm_type, configured=True) if cm_type else r">"

    client = ApplianceClient(host=cm_host, user="cli", password=cli_pwd, prompt_regex=cm_prompt,
                             initial_pattern=None, timeout=300, strip_ansi=True, debug=debug)
    if not client.connect():
        logger.error(f"✗ Failed to connect to {cm_appliance}")
        return False

    cmd = f"grdapi universal_connector_bulk_install profileNames={profile_names} hosts={bulk_install_hosts}"
    logger.info(f"➜ {cmd}")
    result = client.execute_command(cmd, timeout=120)
    if verbose:
        logger.info(f"  Output: {result}")
    client.disconnect()
    logger.info("✓ UC bulk install completed")
    return True

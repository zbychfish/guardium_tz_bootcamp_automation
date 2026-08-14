#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import glob
import os
import time
import traceback
from typing import Optional

from core.appliance_client import ApplianceClient
from core.appliance_config_loader import ApplianceConfigLoader
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
    **kwargs
) -> bool:
    _header(logger, "INSTALL FILEBEAT ON SAUROPOD")

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
    from core.appliance_operations import setup_kafka_node as core_setup_kafka_node

    _header(logger, "RUN UC AND SETUP KAFKA NODE")

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

    logger.info("➜ Run Universal Connector on collector")
    client = ApplianceClient(host=coll_host, user="cli", password=cli_pwd, prompt_regex=coll_prompt,
                             initial_pattern=None, timeout=300, strip_ansi=True, debug=debug)
    if not client.connect():
        logger.error("Failed to connect to collector")
        return False

    result = client.execute_command("grdapi run_universal_connector", timeout=120)
    if verbose:
        logger.info(f"Output: {result}")
    logger.info("✓ run_universal_connector executed")

    status = client.execute_command("grdapi get_universal_connector_status", timeout=60)
    if "Guardium Universal Connector is running" not in status:
        logger.error(f"✗ Unexpected UC status: {status}")
        client.disconnect()
        return False
    logger.info("✓ Guardium Universal Connector is running")
    client.disconnect()

    logger.info("➜ Setup kafka-node")
    if not core_setup_kafka_node(config=config, logger=logger, appliance_name=kafka_appliance, debug=debug):
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
    **kwargs
) -> bool:
    _header(logger, "REGISTER KAFKA CLUSTER")

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("Password 'pwd' not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    logger.info(f"Cluster: {cluster_name}, members: {member_list}, cruise_control: {apply_cruise_control}")

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
            logger.warning(f"⚠ Registration attempt {attempt}/10 failed (ErrorCode {result['ErrorCode']}): {result.get('ErrorMessage', '')} — retrying in 30s...")
            time.sleep(30)
        else:
            logger.info(f"✓ Cluster registration accepted (attempt {attempt}/10)")
            registered = True
            break

    if not registered:
        logger.error("✗ Kafka cluster registration failed after 10 attempts")
        return False

    logger.info("➜ Verifying cluster exists via GET /restAPI/kafka_cluster (max 6 attempts, 60s interval)...")
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
            logger.info(f"✓ Kafka cluster '{cluster_name}' confirmed (attempt {attempt}/6)")
            break

        if attempt < 6:
            logger.warning(f"⚠ Cluster not found yet (attempt {attempt}/6), waiting 60s...")
            time.sleep(60)
    else:
        logger.error(f"✗ Kafka cluster '{cluster_name}' not found after 6 attempts")
        return False

    logger.info("⌛ Waiting 5 minutes for Kafka cluster to stabilize...")
    time.sleep(300)
    logger.info("✓ Kafka cluster registration completed")
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
    _header(logger, "CREATE UC CREDENTIAL FOR ORACLE CONTAINER")

    if not cred_password:
        cred_password = config.get_custom_variable('simple_pwd')
    if not cred_password:
        logger.error("cred_password not provided and 'simple_pwd' not found in custom_variables")
        return False

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
    **kwargs
) -> bool:
    _header(logger, "IMPORT UC PROFILE")
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
    **kwargs
) -> bool:
    _header(logger, "BULK INSTALL UC PROFILE")
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
    logger.info(f"➜ {cmd}")
    result = client.execute_command(cmd, timeout=120)
    logger.info(f"Output: {result}")
    client.disconnect()
    logger.info("✓ UC bulk install completed")
    return True

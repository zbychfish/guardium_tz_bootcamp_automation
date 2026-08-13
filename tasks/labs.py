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


def setup_minio_on_raptor(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False
) -> bool:
    logger.info("=" * 80)
    logger.info("SETUP MINIO ON RAPTOR")
    logger.info("=" * 80)

    raptor_ip = config.get_machine_ip("raptor", use_private=True)
    if not raptor_ip:
        logger.error("Could not determine raptor IP address")
        return False

    minio_password = config.get_custom_variable("pwd")
    if not minio_password:
        logger.error("Custom variable 'pwd' not found")
        return False

    commands_before_podman = [
        "mkdir -p /home/minio/ca/{certs,private,newcerts}",
        "chmod 700 /home/minio/ca/private",
        "touch /home/minio/ca/index.txt",
        "echo 1000 > /home/minio/ca/serial",
        "mkdir -p /home/minio/certs/CAs",
        "openssl genrsa -out /home/minio/ca/private/ca.key 4096",
        'openssl req -x509 -new -nodes -key /home/minio/ca/private/ca.key -sha256 -days 3650 -subj "/CN=MinIO-Root-CA" -out /home/minio/ca/certs/ca.crt',
        "cp /home/minio/ca/certs/ca.crt /home/minio/certs/CAs/",
        "cp /home/minio/ca/certs/ca.crt /etc/pki/ca-trust/source/anchors/",
        "update-ca-trust",
        "openssl genrsa -out /home/minio/certs/private.key 4096 && chmod 600 /home/minio/certs/private.key",
        f'openssl req -new -key /home/minio/certs/private.key -out /home/minio/minio.csr -subj "/CN=minio.demo.guardium" -addext "subjectAltName=DNS:raptor.demo.guardium,IP:{raptor_ip}"',
        "openssl x509 -req -in /home/minio/minio.csr -CA /home/minio/ca/certs/ca.crt -CAkey /home/minio/ca/private/ca.key -CAcreateserial -out /home/minio/certs/public.crt -days 3600 -sha256 -copy_extensions copy",
        "dnf -y install podman",
        "mkdir -p /home/data/minio",
        "chmod 700 /home/data/minio",
        "curl -L -o /usr/local/bin/mc https://dl.min.io/client/mc/release/linux-amd64/mc",
        "chmod +x /usr/local/bin/mc",
    ]
    
    podman_run_command = f"podman run -d --name minio --restart=always -p 0.0.0.0:9000:9000 -p 0.0.0.0:9001:9001 -v /home/data/minio:/data:Z -v /home/minio/certs:/root/.minio/certs:Z -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD='{minio_password}' quay.io/minio/minio server /data --console-address ':9001'"
    
    commands_after_podman = [
        f"/usr/local/bin/mc alias set myminio https://raptor.demo.guardium:9000 minioadmin '{minio_password}'",
        "/usr/local/bin/mc mb myminio/guardium-ltr",
    ]

    for command in commands_before_podman:
        result = execute_local_command(command, logger=logger, verbose=verbose)
        if result["rc"] != 0:
            logger.error(f"âś— Failed command: {command}")
            logger.error(result["stderr"])
            return False
    
    logger.info("âžś Starting MinIO container...")
    result = execute_local_command(podman_run_command, logger=logger, verbose=verbose)
    if result["rc"] != 0:
        logger.error(f"âś— Failed to start MinIO container")
        logger.error(result["stderr"])
        return False
    
    import time
    logger.info("âŚ› Waiting 10 seconds for MinIO to start...")
    time.sleep(10)
    
    for command in commands_after_podman:
        result = execute_local_command(command, logger=logger, verbose=verbose)
        if result["rc"] != 0:
            logger.error(f"âś— Failed command: {command}")
            logger.error(result["stderr"])
            return False

    logger.info("âś“ MinIO certificates prepared and MinIO started on raptor")
    return True

def setup_appnode(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False,
    **kwargs
) -> bool:
    from core.appliance_operations import setup_appnode as core_setup_appnode
    
    if not kwargs.get('appliance_name'):
        logger.error("appliance_name required")
        return False
    
    return core_setup_appnode(
        config=config,
        logger=logger,
        appliance_name=kwargs['appliance_name'],
        user=kwargs.get('user'),
        password=kwargs.get('password'),
        prompt_regex=kwargs.get('prompt_regex'),
        debug=debug,
        retry_interval=kwargs.get('retry_interval', 60),
        max_retries=kwargs.get('max_retries', 10)
    )


def enable_ltr_on_appnode(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False,
    **kwargs
) -> bool:
    from core.appliance_operations import enable_ltr_on_appnode as core_enable_ltr
    
    if not kwargs.get('appliance_name'):
        logger.error("appliance_name required")
        return False
    
    return core_enable_ltr(
        config=config,
        logger=logger,
        appliance_name=kwargs['appliance_name'],
        user=kwargs.get('user'),
        password=kwargs.get('password'),
        prompt_regex=kwargs.get('prompt_regex'),
        debug=debug
    )


def import_minio_CA_certificate(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False,
    **kwargs
) -> bool:
    from core.appliance_operations import import_datalake_s3_certificate
    
    if not kwargs.get('appliance_name'):
        logger.error("appliance_name required")
        return False
    
    return import_datalake_s3_certificate(
        config=config,
        logger=logger,
        appliance_name=kwargs['appliance_name'],
        certificate_file_path=kwargs.get('certificate_file_path', '/home/minio/ca/certs/ca.crt'),
        user=kwargs.get('user'),
        password=kwargs.get('password'),
        prompt_regex=kwargs.get('prompt_regex'),
        debug=debug
    )


def distribute_minio_certificate(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False,
    **kwargs
) -> bool:
    """
    Distribute MinIO S3 certificate to all managed appliances.
    
    Wrapper for distribute_datalake_certificate from appliance_operations.
    """
    from core.appliance_operations import distribute_datalake_certificate
    
    return distribute_datalake_certificate(
        config=config,
        logger=logger,
        appliance_name=kwargs.get('appliance_name', 'cm'),
        user=kwargs.get('user'),
        password=kwargs.get('password'),
        prompt_regex=kwargs.get('prompt_regex'),
        timeout=kwargs.get('timeout', 300),
        check_interval=kwargs.get('check_interval', 10),
        debug=debug
    )


def activate_ltr(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False,
    **kwargs
) -> bool:
    """
    Activate LTR (Long Term Retention) by configuring complete cold storage.
    
    Wrapper for activate_ltr from appliance_operations.
    """
    from core.appliance_operations import activate_ltr as activate_ltr_op
    
    return activate_ltr_op(
        config=config,
        logger=logger,
        appliance_name=kwargs.get('appliance_name', 'cm'),
        user=kwargs.get('user'),
        password=kwargs.get('password'),
        prompt_regex=kwargs.get('prompt_regex'),
        debug=debug
    )


def import_ltr_dashboard(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
    debug: bool = False
) -> bool:
    from core.guardium_rest_api import import_definitions_files
    
    logger.info("=" * 80)
    logger.info("IMPORT LTR DASHBOARD ON CM")
    logger.info("=" * 80)
    
    definition_files = ["exp_dashboard_ltr.sql"]
    
    logger.info(f"CM Appliance: {cm_appliance}")
    logger.info(f"Definitions directory: {definitions_dir}")
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
        logger.info("\n" + "=" * 80)
        logger.info("âś“ LTR dashboard imported successfully")
        logger.info("=" * 80)
    
    return success


def enable_atap_for_oracle(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False
) -> bool:
    from core.ssh_client import SSHClient

    logger.info("=" * 80)
    logger.info("ENABLE ATAP FOR ORACLE ON SAUROPOD")
    logger.info("=" * 80)

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')

    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("Root password (pwd) not found in custom_variables")
        return False

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password, port=ssh_port, timeout=60)

    try:
        logger.info(f"\nâžś Connecting to sauropod ({sauropod_ip}:{ssh_port})...")
        if not ssh.connect():
            logger.error("Failed to connect to sauropod")
            return False
        logger.info("âś“ Connected to sauropod")

        logger.info("\nâžś Stopping Oracle listener...")
        result = ssh.execute_command("su - oracle -c 'lsnrctl stop'", timeout=60, print_output=verbose)
        if result['rc'] != 0:
            logger.warning(f"lsnrctl stop returned non-zero: {result['stderr']}")

        logger.info("\nâžś Shutting down Oracle database...")
        result = ssh.execute_command(
            'su - oracle -c "echo -e \'shutdown immediate;\\nexit\' | sqlplus / as sysdba"',
            timeout=120,
            print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"Oracle shutdown failed: {result['stderr']}")
            return False

        logger.info("âś“ Oracle stopped")

        guardctl = "/opt/guardium/modules/ATAP/current/files/bin/guardctl"

        logger.info("\nâžś Authorizing oracle user...")
        result = ssh.execute_command(f"{guardctl} authorize-user oracle", timeout=60, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"authorize-user failed: {result['stderr']}")
            return False

        logger.info("\nâžś Storing ATAP configuration for Oracle...")
        result = ssh.execute_command(
            f"{guardctl} --db-type=oracle --db-instance=ORCLCDB --db_user=oracle"
            f" --db_home=/u01/app/oracle/product/21c/dbhome_1/ --db_base=/home/oracle --db_version=21 store-conf",
            timeout=60, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"store-conf failed: {result['stderr']}")
            return False

        logger.info("\nâžś Activating ATAP for Oracle...")
        result = ssh.execute_command(
            f"{guardctl} --db-type=oracle --db-instance=ORCLCDB activate",
            timeout=60, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"activate failed: {result['stderr']}")
            return False

        logger.info("\nâžś Starting Oracle database...")
        result = ssh.execute_command(
            'su - oracle -c "echo -e \'startup\\nexit\' | sqlplus / as sysdba"',
            timeout=120, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"Oracle startup failed: {result['stderr']}")
            return False

        logger.info("\nâžś Starting Oracle listener...")
        result = ssh.execute_command("su - oracle -c 'lsnrctl start'", timeout=60, print_output=verbose)
        if result['rc'] != 0:
            logger.warning(f"lsnrctl start returned non-zero: {result['stderr']}")

        logger.info("âś“ Oracle started")

    except Exception as e:
        logger.error(f"âś— SSH operation failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

    logger.info("=" * 80)
    logger.info("âś“ Oracle stopped successfully")
    logger.info("=" * 80)
    return True

def setup_stap_with_oua_on_sauropod(
    config,
    logger,
    verbose: bool = False,
    appliance_name: str = "cm",
    collector_name: str = "coll1",
    guardium_password: Optional[str] = None,
    instantclient_rpm: str = "oracle-instantclient-basic-21.1.0.0.0-1.x86_64.rpm",
    instantclient_source_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/oracle",
    debug: bool = False
) -> bool:
    from core.ssh_client import SSHClient
    from core.guardium_rest_api import create_guardium_api
    from core.appliance_config_loader import ApplianceConfigLoader
    import time

    if not guardium_password:
        guardium_password = config.get_custom_variable('simple_pwd')
    if not guardium_password:
        logger.error("guardium_password not provided and 'simple_pwd' not found in custom_variables")
        return False

    logger.info("=" * 80)
    logger.info("SETUP STAP WITH OUA ON SAUROPOD")
    logger.info("=" * 80)

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("Root password (pwd) not found in custom_variables")
        return False

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    collector_config = appliance_loader.get_appliance(collector_name)
    if not collector_config:
        logger.error(f"Collector '{collector_name}' not found in machines_info.json")
        return False

    collector_ip = collector_config.get('ip')
    if not collector_ip:
        logger.error(f"Collector '{collector_name}' has no IP address configured")
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

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password, port=ssh_port, timeout=60)

    # Step 1: Install Oracle Instant Client and configure tnsnames.ora
    logger.info("\nâžś Step 1: Install Oracle Instant Client on sauropod")
    try:
        if not ssh.connect():
            logger.error("Failed to connect to sauropod")
            return False
        logger.info("âś“ Connected to sauropod")

        result = ssh.execute_command(f"mkdir -p {remote_lab_dir}", print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to create {remote_lab_dir}: {result['stderr']}")
            return False

        logger.info(f"  Uploading {instantclient_rpm}...")
        if not ssh.upload_file(local_rpm, remote_rpm):
            logger.error(f"Failed to upload {instantclient_rpm}")
            return False
        logger.info("âś“ RPM uploaded")

        result = ssh.execute_command(f"dnf -y install {remote_rpm}", timeout=120, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to install Oracle Instant Client: {result['stderr']}")
            return False
        logger.info("âś“ Oracle Instant Client installed")

        tnsnames_dir = "/usr/lib/oracle/21/client64/lib/network/admin"
        result = ssh.execute_command(f"mkdir -p {tnsnames_dir}", print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to create tnsnames dir: {result['stderr']}")
            return False

        result = ssh.execute_command(
            f"cat > {tnsnames_dir}/tnsnames.ora << 'EOF'\n{tnsnames_content}\nEOF",
            print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"Failed to write tnsnames.ora: {result['stderr']}")
            return False
        logger.info(f"âś“ tnsnames.ora configured at {tnsnames_dir}/tnsnames.ora")

    except Exception as e:
        logger.error(f"âś— SSH operation failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

    # Step 2: Create game schema in Oracle container via guardium-notes-dbtraffic
    logger.info("\nâžś Step 2: Create game schema in Oracle container (rebuild)")
    dbtraffic_dir = "/opt/guardium_tz_bootcamp_automation/upload/guardium_notes_dbtraffic"
    rebuild_cmd = (
        f"cd {dbtraffic_dir} && "
        f"source venv/bin/activate && "
        f"guardium-notes-dbtraffic --config config/oracle_container_sauropod.yaml rebuild"
    )
    result = execute_local_command(rebuild_cmd, logger=logger, verbose=verbose)
    if result['rc'] != 0:
        logger.error(f"âś— Failed to create game schema: {result['stderr']}")
        return False
    logger.info("âś“ Game schema created in Oracle container")

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password, port=ssh_port, timeout=60)

    # Step 3: Create secadmin and guardium users, grant privileges
    logger.info("\nâžś Step 3: Create secadmin and guardium users")
    try:
        import oracledb
        dsn = f"{sauropod_ip}:1522/ORCLPDB1"

        conn = oracledb.connect(user="system", password=root_password, dsn=dsn)
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
        logger.info("âś“ secadmin and guardium users created")

    except Exception as e:
        logger.error(f"âś— Oracle connection failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False

    # Step 5: Configure guard_tap.ini for OUA monitoring
    logger.info("\nâžś Step 5: Configure guard_tap.ini for OUA")
    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password, port=ssh_port, timeout=60)
    try:
        if not ssh.connect():
            logger.error("Failed to connect to sauropod")
            return False
        logger.info("âś“ Connected to sauropod")

        ini_cmds = [
            "sed -i 's|^sqlc_properties_dir=.*|sqlc_properties_dir=/usr/lib/oracle/21/client64/lib/network/admin|' /opt/guardium/modules/STAP/current/guard_tap.ini",
            "sed -i 's|^ld_library_paths=.*|ld_library_paths=/usr/lib/oracle/21/client64/lib|' /opt/guardium/modules/STAP/current/guard_tap.ini",
            "/opt/guardium/modules/STAP/current/guard-config-update --restart STAP"
        ]
        for cmd in ini_cmds:
            result = ssh.execute_command(cmd, timeout=60, print_output=verbose)
            if result['rc'] != 0:
                logger.warning(f"Command returned non-zero: {cmd}\n{result['stderr']}")
        logger.info("âś“ guard_tap.ini configured and STAP restarted")

    except Exception as e:
        logger.error(f"âś— SSH operation failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

    # Step 5: Store SQL credentials and create SQL configuration via REST API
    logger.info("\nâžś Step 5: Store Oracle credentials and create SQL configuration")
    try:
        api = create_guardium_api(config, logger, appliance_name)
        api.get_token(username='demo', password=root_password)

        logger.info("  Storing guardium user credentials on collector...")
        api.store_sql_credentials(
            password=guardium_password,
            username="guardium",
            stap_host=sauropod_ip,
            api_target_host=collector_ip
        )
        logger.info("âś“ SQL credentials stored")

        time.sleep(60)

        logger.info("  Creating SQL configuration for Oracle OUA...")
        api.create_sql_configuration(
            db_type="Oracle",
            instance="ORCLPDB1",
            stap_host=sauropod_ip,
            username="guardium",
            api_target_host=collector_ip
        )
        logger.info("âś“ SQL configuration created")

        time.sleep(60)

        # Step 6: Disable STAP (STAP_ENABLED=0) and reinstall
        logger.info("\nâžś Step 6: Set STAP_ENABLED=0 and apply")
        api.gim_client_params(client_ip=sauropod_ip, param_name="STAP_ENABLED", param_value="0")
        api.gim_schedule_install(client_ip=sauropod_ip, date="now")
        logger.info("âś“ STAP_ENABLED=0 scheduled")

    except Exception as e:
        logger.error(f"âś— REST API operation failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False

    logger.info("\n" + "=" * 80)
    logger.info("âś“ SETUP STAP WITH OUA ON SAUROPOD COMPLETED")
    logger.info("=" * 80)
    return True


def setup_oua_audit_policy_on_sauropod(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False,
    **kwargs
) -> bool:
    logger.info("=" * 80)
    logger.info("SETUP OUA AUDIT POLICY GAME_APP ON SAUROPOD")
    logger.info("=" * 80)

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("Root password (pwd) not found in custom_variables")
        return False

    try:
        import oracledb
        dsn = f"{sauropod_ip}:1522/ORCLPDB1"

        logger.info("âžś Creating audit policy GAME_APP and scheduler job as secadmin...")
        conn = oracledb.connect(user="secadmin", password=root_password, dsn=dsn)
        cur = conn.cursor()

        # cleanup â€” ignore errors if objects don't exist
        for ddl in [
            "NOAUDIT POLICY GAME_APP",
            "DROP AUDIT POLICY GAME_APP",
        ]:
            try:
                cur.execute(ddl)
                conn.commit()
            except Exception:
                conn.rollback()

        # drop scheduler job if exists
        try:
            cur.execute("BEGIN DBMS_SCHEDULER.drop_job(job_name=>'ENSURE_GAME_APP_AUDIT', force=>TRUE); END;")
            conn.commit()
        except Exception:
            conn.rollback()

        # create fresh
        for sql in [
            r"CREATE AUDIT POLICY GAME_APP ACTIONS ALL ON game.customers, ALL ON game.credit_cards, ALL ON game.transactions, ALL ON game.extras, ALL ON game.features",
            r"AUDIT POLICY GAME_APP",
            r"BEGIN DBMS_SCHEDULER.create_job(job_name=>'ENSURE_GAME_APP_AUDIT', job_type=>'STORED_PROCEDURE', job_action=>'ENSURE_GAME_APP_AUDIT', repeat_interval=>'FREQ=MINUTELY;INTERVAL=45', enabled=>TRUE); END;",
        ]:
            cur.execute(sql)
            conn.commit()

        cur.close()
        conn.close()
        logger.info("âś“ Audit policy GAME_APP created and enabled")

    except Exception as e:
        logger.error(f"âś— Oracle connection failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False

    logger.info("=" * 80)
    logger.info("âś“ SETUP OUA AUDIT POLICY COMPLETED")
    logger.info("=" * 80)
    return True


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


def import_oracle_dashboard(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
    debug: bool = False
) -> bool:
    from core.guardium_rest_api import import_definitions_files

    logger.info("=" * 80)
    logger.info("IMPORT ORACLE DASHBOARD ON CM")
    logger.info("=" * 80)

    definition_files = ["exp_dashboard_oracle.sql"]

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
        logger.info("âś“ Oracle dashboard imported successfully")

    return success


def enable_vulnerability_management(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    flag_name: str = "VULNERABILITY_MANAGEMENT",
    debug: bool = False,
    **kwargs
) -> bool:
    from core.appliance_client import ApplianceClient
    from core.appliance_config_loader import ApplianceConfigLoader

    logger.info("=" * 80)
    logger.info("ENABLE VULNERABILITY MANAGEMENT FEATURE FLAG")
    logger.info("=" * 80)

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    appliance_config = appliance_loader.get_appliance(cm_appliance)
    if not appliance_config:
        logger.error(f"Appliance '{cm_appliance}' not found")
        return False

    host = appliance_config.get('ip')
    if not host:
        logger.error(f"No IP for appliance '{cm_appliance}'")
        return False

    appliance_type = appliance_config.get('type')
    prompt_regex = appliance_loader.get_default_prompt(appliance_type, configured=True) if appliance_type else r">"

    cli_pwd = config.get_custom_variable('cli_pwd')
    if not cli_pwd:
        logger.error("cli_pwd not found in custom_variables")
        return False

    client = ApplianceClient(
        host=host,
        user="cli",
        password=cli_pwd,
        prompt_regex=prompt_regex,
        initial_pattern=None,
        timeout=60,
        strip_ansi=True,
        debug=debug
    )
    if not client.connect():
        logger.error(f"Failed to connect to {cm_appliance}")
        return False

    try:
        # â”€â”€ 1. Enable feature flag â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        cmd = f"grdapi enable_disable_feature_flag flagName={flag_name} action=enable"
        logger.info(f"âžś {cmd}")
        result = client.execute_command(cmd, timeout=30)
        if verbose:
            logger.info(f"Response: {result}")

        # â”€â”€ 2. Verify flag is ENABLED â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        logger.info("âžś Verifying flag state via grdapi list_feature_flags...")
        flags_output = client.execute_command("grdapi list_feature_flags", timeout=30)
        if verbose or debug:
            logger.info(f"Feature flags:\n{flags_output}")

        for line in flags_output.splitlines():
            if flag_name in line:
                if "State: ENABLED" in line:
                    logger.info(f"âś“ {flag_name} is ENABLED")
                    return True
                else:
                    logger.error(f"âś— {flag_name} found but state is not ENABLED: {line.strip()}")
                    return False

        logger.error(f"âś— {flag_name} not found in list_feature_flags output")
        return False

    finally:
        client.disconnect()


def create_va_postgres_account(
    config,
    logger,
    verbose: bool = True,
    db_user: str = "sqlguard",
    db_group: str = "gdmmonitor",
    **kwargs
) -> bool:
    from core.utils import execute_local_command

    logger.info("=" * 80)
    logger.info("CREATE VA POSTGRES ACCOUNT")
    logger.info("=" * 80)

    password = config.get_custom_variable('pwd')
    if not password:
        logger.error("pwd not found in custom_variables")
        return False

    def psql(sql, desc):
        if '$$' in sql:
            cmd = f"sudo -u postgres psql -d postgres -U postgres << 'EOSQL'\n{sql}\nEOSQL"
        else:
            escaped = sql.replace('"', '\\"')
            cmd = f'sudo -u postgres psql -d postgres -U postgres -c "{escaped}"'
        result = execute_local_command(cmd, logger, verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to {desc}: {result['stderr']}")
            return False
        logger.info(f"âś“ {desc}")
        return True

    steps = [
        (f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_user WHERE usename='{db_user}') THEN CREATE USER {db_user} WITH ENCRYPTED PASSWORD '{password}'; END IF; END $$", f"create user {db_user}"),
        (f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_group WHERE groname='{db_group}') THEN CREATE GROUP {db_group}; END IF; END $$",                      f"create group {db_group}"),
        (f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_group g JOIN pg_user u ON u.usesysid=ANY(g.grolist) WHERE g.groname='{db_group}' AND u.usename='{db_user}') THEN ALTER GROUP {db_group} ADD USER {db_user}; END IF; END $$", f"add {db_user} to {db_group}"),
        (f"GRANT pg_read_all_settings TO {db_group}",                                                                                                        f"grant pg_read_all_settings to {db_group}"),
        (f"GRANT SELECT ON pg_authid TO {db_group}",                                                                                                         f"grant SELECT on pg_authid to {db_group}"),
        (f"CREATE EXTENSION IF NOT EXISTS pgcrypto",                                                                                                         f"create extension pgcrypto"),
    ]

    for sql, desc in steps:
        if not psql(sql, desc):
            return False

    logger.info("âś“ VA PostgreSQL account ready")
    return True


def import_va_postgres_definitions(
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
    logger.info("IMPORT VA POSTGRES DEFINITIONS")
    logger.info("=" * 80)

    definition_files = ["exp_security_assessment_postgres_on_raptor.sql"]

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
        logger.info("âś“ VA PostgreSQL definitions imported successfully")

    return success


def fetch_cm_certificate_on_sauropod(
    config,
    logger,
    verbose: bool = True,
    cm_host: str = "cm.demo.guardium",
    cm_port: int = 8443,
    cert_path: str = "/root/gn-trainings/vascanner/certs/vascanner.pem",
    debug: bool = False,
    **kwargs
) -> bool:
    from core.ssh_client import SSHClient

    logger.info("=" * 80)
    logger.info("FETCH CM CERTIFICATE ON SAUROPOD")
    logger.info("=" * 80)

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port   = ssh_config.get('port', 2223)
    ssh_user   = ssh_config.get('username', 'root')
    password   = config.get_custom_variable('pwd')
    if not password:
        logger.error("pwd not found in custom_variables")
        return False

    cert_dir = cert_path.rsplit('/', 1)[0]

    cmds = [
        (f"mkdir -p {cert_dir}",                                                                              "create cert dir"),
        (f"openssl s_client -connect {cm_host}:{cm_port} -showcerts </dev/null 2>/dev/null "
         f"| openssl x509 -outform PEM > {cert_path}",                                                       f"fetch certificate from {cm_host}:{cm_port}"),
        (f"test -s {cert_path}",                                                                              "verify cert file non-empty"),
    ]

    ssh = SSHClient(host=sauropod_ip, username=ssh_user, password=password, port=ssh_port, timeout=60)
    try:
        logger.info(f"âžś Connecting to sauropod ({sauropod_ip}:{ssh_port})...")
        if not ssh.connect():
            logger.error("Failed to connect to sauropod")
            return False
        logger.info("âś“ Connected to sauropod")

        for cmd, desc in cmds:
            logger.info(f"âžś {desc}...")
            result = ssh.execute_command(cmd, timeout=30, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"âś— Failed to {desc}: {result['stderr']}")
                return False
            logger.info(f"âś“ {desc}")

        logger.info(f"âś“ Certificate saved to sauropod:{cert_path}")
        return True

    except Exception as e:
        logger.error(f"âś— SSH operation failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()


def create_va_api_key(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    key_name: str = "vascanner",
    key_file: str = ".va_api_key",
    debug: bool = False,
    **kwargs
) -> bool:
    from core.appliance_client import ApplianceClient
    from core.appliance_config_loader import ApplianceConfigLoader
    from pathlib import Path

    logger.info("=" * 80)
    logger.info("CREATE VA API KEY")
    logger.info("=" * 80)

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    appliance_config = appliance_loader.get_appliance(cm_appliance)
    if not appliance_config:
        logger.error(f"Appliance '{cm_appliance}' not found")
        return False

    host = appliance_config.get('ip')
    if not host:
        logger.error(f"No IP for appliance '{cm_appliance}'")
        return False

    appliance_type = appliance_config.get('type')
    prompt_regex = appliance_loader.get_default_prompt(appliance_type, configured=True) if appliance_type else r">"

    cli_pwd = config.get_custom_variable('cli_pwd')
    if not cli_pwd:
        logger.error("cli_pwd not found in custom_variables")
        return False

    client = ApplianceClient(
        host=host,
        user="cli",
        password=cli_pwd,
        prompt_regex=prompt_regex,
        initial_pattern=None,
        timeout=60,
        strip_ansi=True,
        debug=debug
    )
    if not client.connect():
        logger.error(f"Failed to connect to {cm_appliance}")
        return False

    try:
        cmd = f"grdapi create_api_key name={key_name}"
        logger.info(f"âžś {cmd}")
        output = client.execute_command(cmd, timeout=30)
        if verbose:
            logger.info(f"Response:\n{output}")

        # parse "Encoded API key: <value>"
        api_key = None
        for line in output.splitlines():
            if "Encoded API key:" in line:
                api_key = line.split("Encoded API key:", 1)[1].strip()
                break

        if not api_key:
            logger.error("Could not parse 'Encoded API key' from output")
            logger.error(f"Full output: {output}")
            return False

        logger.info(f"âś“ API key generated: {api_key[:10]}...")

        key_path = config.config_file.parent.parent / key_file
        key_path.write_text(api_key, encoding='utf-8')
        logger.info(f"âś“ API key saved to: {key_path}")

        return True

    finally:
        client.disconnect()


def deploy_vascanner_on_sauropod(
    config,
    logger,
    verbose: bool = True,
    image: str = "cp.icr.io/cp/ibm-guardium-data-security-center/guardium/vascanner-12.2.0/va-scanner:vascanner-v12.2.0",
    container_name: str = "va-scanner-sauropod",
    config_file: str = "/opt/vascanner/config",
    certs_dir: str = "/root/gn-trainings/vascanner/certs",
    va_agent_name: str = "VA_SCANNER_ON_SAUROPOD",
    cm_host: str = "cm.demo.guardium",
    cm_port: int = 8443,
    key_file: str = ".va_api_key",
    debug: bool = False,
    **kwargs
) -> bool:
    from core.ssh_client import SSHClient
    from pathlib import Path

    logger.info("=" * 80)
    logger.info("DEPLOY VA SCANNER ON SAUROPOD")
    logger.info("=" * 80)

    # â”€â”€ resolve sauropod connection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port   = ssh_config.get('port', 2223)
    ssh_user   = ssh_config.get('username', 'root')
    password   = config.get_custom_variable('pwd')
    if not password:
        logger.error("pwd not found in custom_variables")
        return False

    # â”€â”€ resolve IBM registry key â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    ibm_key = config.get_custom_variable('ibm_container_api_key')
    if not ibm_key:
        logger.error("ibm_container_api_key not found in custom_variables")
        return False

    # â”€â”€ resolve encoded API key from .va_api_key â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    key_path = config.config_file.parent.parent / key_file
    if not key_path.exists():
        logger.error(f"{key_path} not found â€” run create_va_api_key stage first")
        return False
    api_key = key_path.read_text(encoding='utf-8').strip()
    if not api_key:
        logger.error(f"{key_path} is empty")
        return False

    config_content = (
        f"GDP_HOST={cm_host}\n"
        f"GDP_HOST_PORT={cm_port}\n"
        f"CLIENT_API_KEY={api_key}\n"
        f"VA_AGENT_NAME={va_agent_name}\n"
    )

    ssh = SSHClient(host=sauropod_ip, username=ssh_user, password=password, port=ssh_port, timeout=120)
    try:
        logger.info(f"âžś Connecting to sauropod ({sauropod_ip}:{ssh_port})...")
        if not ssh.connect():
            logger.error("Failed to connect to sauropod")
            return False
        logger.info("âś“ Connected to sauropod")

        # â”€â”€ 1. podman login â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        logger.info("âžś Logging in to cp.icr.io...")
        result = ssh.execute_command(
            f"podman login cp.icr.io -u cp -p '{ibm_key}'",
            timeout=60, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"âś— podman login failed: {result['stderr']}")
            return False
        logger.info("âś“ Logged in to cp.icr.io")

        # â”€â”€ 2. podman pull â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        logger.info(f"âžś Pulling image {image}...")
        result = ssh.execute_command(
            f"podman pull {image}",
            timeout=600, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"âś— podman pull failed: {result['stderr']}")
            return False
        logger.info("âś“ Image pulled")

        # â”€â”€ 3. get image ID â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        logger.info("âžś Resolving image ID...")
        result = ssh.execute_command(
            f"podman images --format '{{{{.ID}}}}' {image}",
            timeout=30, print_output=verbose
        )
        if result['rc'] != 0 or not result['stdout'].strip():
            logger.error(f"âś— Failed to get image ID: {result['stderr']}")
            return False
        image_id = result['stdout'].strip().splitlines()[0].strip()
        logger.info(f"âś“ Image ID: {image_id}")

        # â”€â”€ 4. write config file â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        config_dir = config_file.rsplit('/', 1)[0]
        logger.info(f"âžś Writing config to {config_file}...")
        result = ssh.execute_command(
            f"mkdir -p {config_dir} && cat > {config_file} << 'EOF'\n{config_content}EOF",
            timeout=30, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"âś— Failed to write config file: {result['stderr']}")
            return False
        logger.info("âś“ Config file written")

        # â”€â”€ 5. podman run â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        logger.info(f"âžś Starting container {container_name}...")
        run_cmd = (
            f"podman run --network host -d --replace "
            f"--env-file {config_file} "
            f"--name {container_name} "
            f"-v {certs_dir}:/var/vascanner/certs "
            f"{image_id}"
        )
        result = ssh.execute_command(run_cmd, timeout=60, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"âś— podman run failed: {result['stderr']}")
            return False
        logger.info(f"âś“ Container {container_name} started")

        return True

    except Exception as e:
        logger.error(f"âś— SSH operation failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()


def import_dps(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    dps_file: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/appliances/dps/Guardium_V12_Quarterly_DPS_2026_Q2_20260515.enc",
    demo_user: str = "demo",
    headless: bool = True,
    **kwargs
) -> bool:
    import sys
    import subprocess
    from core.web_ui import guardium_customer_upload_import
    from core.appliance_config_loader import ApplianceConfigLoader

    logger.info("=" * 80)
    logger.info("IMPORT DPS")
    logger.info("=" * 80)

    import os
    if not os.path.exists(dps_file):
        logger.error(f"DPS file not found: {dps_file}")
        return False

    password = config.get_custom_variable('pwd')
    if not password:
        logger.error("pwd not found in custom_variables")
        return False

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    appliance_config = appliance_loader.get_appliance(cm_appliance)
    if not appliance_config:
        logger.error(f"Appliance '{cm_appliance}' not found")
        return False

    cm_ip = appliance_config.get('ip')
    if not cm_ip:
        logger.error(f"No IP for appliance '{cm_appliance}'")
        return False

    login_url = f"https://{cm_ip}:8443"

    logger.info("âžś Installing playwright browsers...")
    result = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(f"playwright install returned {result.returncode}: {result.stderr.strip()}")

    logger.info(f"âžś Starting DPS import from {dps_file}...")
    logger.info(f"  login_url: {login_url}, user: {demo_user}")

    from time import sleep
    sleep(30)

    try:
        guardium_customer_upload_import(
            login_url=login_url,
            username=demo_user,
            password=password,
            file_to_upload=dps_file,
            headless=headless,
        )
        logger.info("âś“ DPS imported successfully")
        return True
    except FileNotFoundError as e:
        logger.error(f"âś— {e}")
        return False
    except Exception as e:
        logger.error(f"âś— DPS import failed: {e}")
        return False


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


def import_va_api_definitions(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
    debug: bool = False
) -> bool:
    from core.guardium_rest_api import import_definitions_files

    logger.info("=" * 80)
    logger.info("IMPORT VA API DEFINITIONS ON CM")
    logger.info("=" * 80)

    definition_files = [
        "exp_dashboard_va.sql",
        "exp_security_assessment_oracle_on_sauropod.sql",
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
        logger.info("âś“ VA API definitions imported successfully")

    return success


def create_va_oauth_client(config, logger, verbose=True,
                           appliance_name="cm", client_id="va-api",
                           debug=False, **kwargs):
    import json
    from core.appliance_client import ApplianceClient
    from core.appliance_config_loader import ApplianceConfigLoader

    logger.info("=" * 80)
    logger.info(f"CREATE OAUTH CLIENT: {client_id}")
    logger.info("=" * 80)

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    appliance_config = appliance_loader.get_appliance(appliance_name)
    if not appliance_config:
        logger.error(f"Appliance '{appliance_name}' not found in machines_info.json")
        return False

    password = config.get_custom_variables().get('cli_pwd')
    if not password:
        logger.error("cli_pwd not found in custom_variables")
        return False

    appliance_ip = appliance_config.get('ip')
    if not appliance_ip:
        logger.error(f"IP address not found for appliance '{appliance_name}'")
        return False

    user = appliance_loader.get_default_user(appliance_config.get('type', 'cm'))
    prompt_regex = appliance_loader.get_default_prompt(appliance_config.get('type', 'cm'), configured=True)

    client = ApplianceClient(
        host=appliance_ip,
        user=user,
        password=password,
        prompt_regex=prompt_regex,
        timeout=120,
        debug=debug
    )

    try:
        if not client.connect():
            logger.error("Failed to connect to appliance")
            return False
        logger.info("âś“ Connected successfully")

        result = client.execute_command("grdapi list_oauth_clients")
        if f"Client Id: {client_id}" in result:
            logger.info(f"âžś Deleting existing OAuth client '{client_id}'...")
            client.execute_command(f"grdapi delete_oauth_clients client_id={client_id}")
            logger.info("âś“ Existing client deleted")

        logger.info(f"âžś Creating OAuth client '{client_id}'...")
        result = client.execute_command(f'grdapi register_oauth_client client_id={client_id} grant_types="password"')

        client_secret = None
        for line in result.splitlines():
            line = line.strip()
            if line.startswith('{') and line.endswith('}'):
                try:
                    data = json.loads(line)
                    client_secret = data.get('client_secret')
                    if client_secret:
                        logger.info(f"âś“ OAuth client created: {client_id}")
                        logger.info(f"  Client Secret: {client_secret[:10]}...")
                        break
                except json.JSONDecodeError:
                    pass

        if not client_secret:
            logger.error(f"Failed to extract client_secret from response: {result}")
            return False

        project_root = config.config_file.parent.parent
        secret_file = project_root / ".client_secret_va"
        with open(secret_file, 'w') as f:
            f.write(client_secret)
        logger.info(f"âś“ Client secret saved to: {secret_file}")

        logger.info("=" * 80)
        logger.info("âś“ VA OAuth client setup completed successfully")
        logger.info("=" * 80)
        return True

    except Exception as e:
        logger.error(f"Error creating OAuth client: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        client.disconnect()


def install_edge_patch_via_api(config, logger, verbose=True,
                               cm_appliance="cm",
                               patch_filename="SqlGuard-12.0p15002_Edge_Apr_14_2026.tgz.enc.sig",
                               mode="local_only",
                               debug=False, **kwargs):
    import re
    import os
    from core.guardium_rest_api import create_guardium_api
    from core.appliance_config_loader import ApplianceConfigLoader
    from core.appliance_client import ApplianceClient

    logger.info("=" * 80)
    logger.info("INSTALL EDGE PATCH ON CM VIA REST API")
    logger.info("=" * 80)

    m = re.search(r'12\.0p(\d+)', os.path.basename(patch_filename))
    if not m:
        logger.error(f"Cannot extract patch_number from filename: {patch_filename}")
        return False
    patch_number = int(m.group(1))
    logger.info(f"Patch number: {patch_number}")

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    appliance_config = appliance_loader.get_appliance(cm_appliance)
    if not appliance_config:
        logger.error(f"Appliance '{cm_appliance}' not found in machines_info.json")
        return False
    cm_ip = appliance_config.get('ip')
    if not cm_ip:
        logger.error(f"Appliance '{cm_appliance}' has no IP")
        return False

    appliance_type = appliance_config.get('type', 'cm')
    cli_prompt = appliance_loader.get_default_prompt(appliance_type, configured=True) or r'[\w-]+(\.demo\.guardium)?> '
    cli_pwd = config.get_custom_variable('cli_pwd')
    if not cli_pwd:
        logger.error("cli_pwd not found in custom_variables")
        return False

    logger.info("âžś Registering patches on CM: show system patch available...")
    cli = ApplianceClient(
        host=cm_ip,
        user='cli',
        password=cli_pwd,
        prompt_regex=cli_prompt,
        initial_pattern=None,
        timeout=600,
        strip_ansi=True,
        debug=debug
    )
    if not cli.connect():
        logger.error("âś— Failed to connect to CM CLI")
        return False
    try:
        patch_output = cli.execute_command("show system patch available", timeout=600)
        logger.info(f"Available patches:\n{patch_output}")
        logger.info("âś“ Patches registered on CM")
    except Exception as e:
        logger.error(f"âś— CLI command failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        cli.disconnect()

    api = create_guardium_api(config, logger, cm_appliance)
    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("Password 'pwd' not found in custom_variables")
        return False
    api.get_token(username='demo', password=pwd)

    logger.info(f"âžś Calling patch_install API (patch_number={patch_number}, unit={cm_ip}, mode={mode})...")
    try:
        result = api.patch_install(patch_number=patch_number, unit_ip_list=cm_ip, mode=mode)
    except Exception as e:
        logger.error(f"âś— patch_install API call failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False

    logger.info(f"  API response: {result}")
    if result.get('ErrorCode') or result.get('errorCode'):
        logger.error(f"âś— patch_install returned error: {result}")
        return False

    logger.info("âś“ Edge patch installation initiated via REST API on CM")
    return True


def monitor_edge_patch_installation(config, logger, verbose=True,
                                    cm_appliance="cm",
                                    patch_filename="SqlGuard-12.0p15002_Edge_Apr_14_2026.tgz.enc.sig",
                                    appear_interval=15, appear_max=40,
                                    install_interval=60, install_max=60,
                                    debug=False, **kwargs):
    import re
    import os
    import time
    from core.appliance_config_loader import ApplianceConfigLoader
    from core.appliance_client import ApplianceClient

    logger.info("=" * 80)
    logger.info("MONITOR EDGE PATCH INSTALLATION ON CM")
    logger.info("=" * 80)

    m = re.search(r'12\.0p(\d+)', os.path.basename(patch_filename))
    if not m:
        logger.error(f"Cannot extract patch_number from filename: {patch_filename}")
        return False
    patch_number_str = m.group(1)

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    appliance_config = appliance_loader.get_appliance(cm_appliance)
    if not appliance_config:
        logger.error(f"Appliance '{cm_appliance}' not found in machines_info.json")
        return False
    cm_ip = appliance_config.get('ip')
    if not cm_ip:
        logger.error(f"Appliance '{cm_appliance}' has no IP")
        return False

    appliance_type = appliance_config.get('type', 'cm')
    cli_prompt = appliance_loader.get_default_prompt(appliance_type, configured=True) or r'[\w-]+(\.demo\.guardium)?> '
    cli_pwd = config.get_custom_variable('cli_pwd')
    if not cli_pwd:
        logger.error("cli_pwd not found in custom_variables")
        return False

    def _cli_show_patch_install():
        client = ApplianceClient(
            host=cm_ip, user='cli', password=cli_pwd,
            prompt_regex=cli_prompt, timeout=60,
            strip_ansi=True, debug=debug
        )
        try:
            if not client.connect():
                return None
            output = client.execute_command("show system patch install")
            return output
        except Exception:
            return None
        finally:
            client.disconnect()

    def _parse_patch_status(output, patch_num_str):
        for line in output.splitlines():
            line = line.strip()
            if re.match(rf'^{re.escape(patch_num_str)}\s+', line):
                return line
        return None

    # â”€â”€ Phase 1: wait for patch to appear in install list (every 15s) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    logger.info(f"âŹł Phase 1: Waiting for patch {patch_number_str} to appear in 'show system patch install'")
    logger.info(f"   Checking every {appear_interval}s (max {appear_max} checks = {appear_interval * appear_max}s)...")
    appeared = False
    for check in range(1, appear_max + 1):
        time.sleep(appear_interval)
        output = _cli_show_patch_install()
        if output is None:
            logger.warning(f"  #{check}/{appear_max}: CLI unavailable, retrying...")
            continue
        status_line = _parse_patch_status(output, patch_number_str)
        if status_line:
            logger.info(f"  âś“ #{check}/{appear_max}: Patch {patch_number_str} appeared â†’ {status_line}")
            appeared = True
            break
        logger.info(f"  #{check}/{appear_max}: Patch {patch_number_str} not yet visible, waiting {appear_interval}s...")

    if not appeared:
        logger.error(f"âś— Patch {patch_number_str} did not appear in install list after {appear_interval * appear_max}s")
        return False

    # â”€â”€ Phase 2: wait for DONE status (every 60s) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    logger.info(f"âŹł Phase 2: Monitoring installation (every {install_interval}s, max {install_max} checks)...")
    for check in range(1, install_max + 1):
        time.sleep(install_interval)
        logger.info(f"  Check #{check}/{install_max}: querying 'show system patch install'...")
        output = _cli_show_patch_install()
        if output is None:
            logger.warning(f"  #{check}/{install_max}: CLI unavailable (appliance may be restarting), retrying...")
            continue
        status_line = _parse_patch_status(output, patch_number_str)
        if not status_line:
            logger.warning(f"  #{check}/{install_max}: Patch {patch_number_str} disappeared from list, retrying...")
            continue
        logger.info(f"  #{check}/{install_max}: {status_line}")
        if "DONE: Patch installation Succeeded" in status_line:
            logger.info("=" * 80)
            logger.info(f"âś“ Edge patch {patch_number_str} installed successfully on CM")
            logger.info("=" * 80)
            return True
        if "FAIL" in status_line.upper() or "ERROR" in status_line.upper():
            logger.error(f"âś— Patch installation failed: {status_line}")
            return False

    logger.error(f"âś— Timeout: patch {patch_number_str} not installed after {install_interval * install_max}s")
    return False


def register_edge_gateway(config, logger, verbose=True,
                          cm_appliance="cm",
                          exports_to="cm.demo.guardium",
                          name="sauropod.demo.guardium",
                          namespace="edge",
                          storageclass_rw_once="local-path",
                          version="v2.1.1",
                          deploy_proxy=True,
                          debug=False, **kwargs):
    from core.guardium_rest_api import create_guardium_api

    logger.info("=" * 80)
    logger.info("REGISTER EDGE GATEWAY ON CM")
    logger.info("=" * 80)
    logger.info(f"  name={name}, namespace={namespace}, exportsTo={exports_to}")
    logger.info(f"  storageclass_rw_once={storageclass_rw_once}, version={version}, deployProxy={deploy_proxy}")

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("pwd not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    try:
        result = api.register_edge(
            name=name,
            namespace=namespace,
            exports_to=exports_to,
            storageclass_rw_once=storageclass_rw_once,
            version=version,
            deploy_proxy=deploy_proxy,
        )
    except Exception as e:
        logger.error(f"âś— register_edge API call failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False

    if verbose:
        logger.info(f"  API response: {result}")
    if result.get('ErrorCode') or result.get('errorCode'):
        logger.error(f"âś— register_edge returned error: {result}")
        return False

    logger.info("âś“ Edge gateway registered successfully on CM")
    return True


def install_k3s_on_sauropod(config, logger, verbose=True,
                            k3s_version="v1.32.13+k3s1",
                            cm_appliance="cm",
                            expected_pods=3, max_wait=300, check_interval=15,
                            debug=False, **kwargs):
    import time
    from core.ssh_client import SSHClient
    from core.appliance_config_loader import ApplianceConfigLoader

    logger.info("=" * 80)
    logger.info("INSTALL K3S ON SAUROPOD")
    logger.info("=" * 80)

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    cm_config = appliance_loader.get_appliance(cm_appliance)
    if not cm_config:
        logger.error(f"Appliance '{cm_appliance}' not found in machines_info.json")
        return False
    cm_ip = cm_config.get('ip')
    if not cm_ip:
        logger.error(f"Appliance '{cm_appliance}' has no IP")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')

    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("Root password (pwd) not found in custom_variables")
        return False

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password,
                    port=ssh_port, timeout=60)

    try:
        logger.info(f"Connecting to sauropod ({sauropod_ip}:{ssh_port})...")
        if not ssh.connect():
            logger.error("Failed to connect to sauropod")
            return False
        logger.info("âś“ Connected to sauropod")

        install_cmd = (
            f"curl -sfL https://get.k3s.io | "
            f"INSTALL_K3S_VERSION={k3s_version} sh -s - --disable traefik"
        )
        logger.info(f"âžś Installing k3s {k3s_version}...")
        result = ssh.execute_command(install_cmd, timeout=300, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"âś— k3s installation failed: {result['stderr']}")
            return False
        logger.info("âś“ k3s installed")

        logger.info(f"âžś Waiting for {expected_pods} pods Running (max {max_wait}s, check every {check_interval}s)...")
        elapsed = 0
        while elapsed < max_wait:
            result = ssh.execute_command("kubectl get pods -A --no-headers 2>/dev/null", print_output=False)
            if result['rc'] == 0:
                lines = [l for l in result['stdout'].splitlines() if l.strip()]
                running = [l for l in lines if 'Running' in l]
                logger.info(f"  Pods Running: {len(running)}/{len(lines)} (elapsed {elapsed}s)")
                if debug:
                    for l in lines:
                        logger.info(f"    {l}")
                if len(running) >= expected_pods:
                    logger.info(f"âś“ {len(running)} pods Running â€” k3s ready")
                    break
            time.sleep(check_interval)
            elapsed += check_interval
        else:
            logger.error(f"âś— Timeout: expected {expected_pods} pods Running after {max_wait}s")
            return False

        # Patch CoreDNS NodeHosts and Corefile with correct IPs, then restart
        logger.info(f"âžś Patching CoreDNS (sauropod_ip={sauropod_ip}, cm_ip={cm_ip})...")

        node_hosts_value = (
            f"{sauropod_ip} sauropod.demo.guardium\\n"
            f"{cm_ip} cm.demo.guardium\\n"
            f"{cm_ip} cm.demo.guardium.demo.guardium\\n"
        )
        corefile_value = (
            ".:53 {\\n"
            "    errors\\n"
            "    health\\n"
            "    ready\\n"
            "    kubernetes cluster.local in-addr.arpa ip6.arpa {\\n"
            "        pods insecure\\n"
            "        fallthrough in-addr.arpa ip6.arpa\\n"
            "    }\\n"
            "    hosts {\\n"
            f"        {cm_ip} cm.demo.guardium\\n"
            f"        {cm_ip} cm.demo.guardium.demo.guardium\\n"
            "        fallthrough\\n"
            "    }\\n"
            "    prometheus :9153\\n"
            "    forward . /etc/resolv.conf\\n"
            "    cache 30\\n"
            "    loop\\n"
            "    reload\\n"
            "    loadbalance\\n"
            "}\\n"
        )

        coredns_cmds = [
            (
                f"kubectl -n kube-system patch configmap coredns --type='json' "
                f"-p='[{{\"op\":\"replace\",\"path\":\"/data/NodeHosts\",\"value\":\"{node_hosts_value}\"}}]'",
                "patch CoreDNS NodeHosts"
            ),
            (
                f"kubectl -n kube-system patch configmap coredns --type=json "
                f"-p='[{{\"op\":\"replace\",\"path\":\"/data/Corefile\",\"value\":\"{corefile_value}\"}}]'",
                "patch CoreDNS Corefile"
            ),
            (
                "kubectl -n kube-system rollout restart deployment coredns",
                "restart CoreDNS"
            ),
        ]

        for cmd, desc in coredns_cmds:
            logger.info(f"  âžś {desc}...")
            result = ssh.execute_command(cmd, timeout=60, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"  âś— Failed to {desc}: {result['stderr']}")
                return False
            logger.info(f"  âś“ {desc}")

        logger.info("âś“ k3s installed and CoreDNS configured on sauropod")
        return True

    except Exception as e:
        logger.error(f"âś— SSH operation failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()


def download_edge_bundle_via_api(config, logger, verbose=True,
                                 cm_appliance="cm",
                                 edge_name="sauropod.demo.guardium",
                                 sauropod_dest="/tmp/edge.tar.gz",
                                 debug=False, **kwargs):
    import os
    import tempfile
    from core.guardium_rest_api import create_guardium_api
    from core.ssh_client import SSHClient

    logger.info("=" * 80)
    logger.info("DOWNLOAD EDGE BUNDLE VIA REST API TO SAUROPOD")
    logger.info("=" * 80)

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("pwd not found in custom_variables")
        return False

    # â”€â”€ call REST API from raptor â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)
    logger.info(f"âžś Calling get_bundle(name={edge_name}) on CM...")
    try:
        bundle_bytes = api.get_bundle(name=edge_name)
    except Exception as e:
        logger.error(f"âś— get_bundle API call failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False

    if not bundle_bytes:
        logger.error("âś— get_bundle returned empty response")
        return False
    logger.info(f"âś“ Bundle received ({len(bundle_bytes)} bytes)")

    # â”€â”€ upload to sauropod via SFTP â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')

    tmp_path = os.path.join(tempfile.gettempdir(), 'edge.tar.gz')
    with open(tmp_path, 'wb') as f:
        f.write(bundle_bytes)
    logger.info(f"âžś Uploading to sauropod ({sauropod_ip}:{ssh_port}) â†’ {sauropod_dest}...")

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=pwd,
                    port=ssh_port, timeout=120)
    try:
        if not ssh.connect():
            logger.error("âś— Failed to connect to sauropod")
            return False
        if not ssh.upload_file(tmp_path, sauropod_dest):
            logger.error(f"âś— Failed to upload bundle to sauropod")
            return False
        logger.info(f"âś“ Edge bundle uploaded to sauropod: {sauropod_dest}")
        extract_dir = os.path.dirname(sauropod_dest.rstrip('/'))
        for cmd, desc in [
            (f"tar -xzf {sauropod_dest} -C {extract_dir}", f"extract {sauropod_dest}"),
            (f"rm -f {sauropod_dest}", f"remove archive {sauropod_dest}"),
        ]:
            result = ssh.execute_command(cmd, print_output=False)
            if result['rc'] != 0:
                logger.error(f"âś— Failed to {desc}: {result['stderr']}")
                return False
            logger.info(f"  âś“ {desc}")
        logger.info(f"âś“ Edge bundle extracted to {extract_dir}")
        return True
    except Exception as e:
        logger.error(f"âś— Upload/extract failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()
        try:
            os.remove(tmp_path)
        except OSError:
            pass



def prepare_sauropod_for_edge(config, logger, verbose=True,
                              debug=False, **kwargs):
    from core.ssh_client import SSHClient

    logger.info("=" * 80)
    logger.info("PREPARE SAUROPOD FOR EDGE DEPLOYMENT")
    logger.info("=" * 80)

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')
    root_pwd = config.get_custom_variable('pwd')
    if not root_pwd:
        logger.error("pwd not found in custom_variables")
        return False

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_pwd,
                    port=ssh_port, timeout=60)
    try:
        if not ssh.connect():
            logger.error("âś— Failed to connect to sauropod")
            return False

        # â”€â”€ configure firewall rules on sauropod â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        for cmd, desc in [
            ("firewall-cmd --permanent --add-port=6443/tcp",  "allow 6443/tcp"),
            ("firewall-cmd --permanent --add-port=8472/udp",  "allow 8472/udp"),
            ("firewall-cmd --permanent --add-port=10250/tcp", "allow 10250/tcp"),
            ("firewall-cmd --permanent --add-masquerade",     "enable masquerade"),
            ("firewall-cmd --reload",                         "reload firewall"),
        ]:
            logger.info(f"âžś {desc}...")
            result = ssh.execute_command(cmd, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"âś— Failed to {desc}: {result['stderr']}")
                return False
            logger.info(f"  âś“ {desc}")

        # â”€â”€ install expect on sauropod â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        logger.info("âžś Installing expect on sauropod...")
        result = ssh.execute_command("dnf -y install expect", print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"âś— Failed to install expect: {result['stderr']}")
            return False
        logger.info("âś“ expect installed on sauropod")
        return True
    except Exception as e:
        logger.error(f"âś— Operation failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()


def deploy_edge_gateway(config, logger, verbose=True,
                        edge_dir="/tmp/sauropod.demo.guardium",
                        install_script="edge-install.sh",
                        script_timeout=600,
                        debug=False, **kwargs):
    import time
    import socket
    import paramiko

    logger.info("=" * 80)
    logger.info("DEPLOY EDGE GATEWAY ON SAUROPOD")
    logger.info("=" * 80)

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')
    root_pwd = config.get_custom_variable('pwd')
    if not root_pwd:
        logger.error("pwd not found in custom_variables")
        return False

    # â”€â”€ run edge-install.sh with PTY via exec_command â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    logger.info(f"âžś Running {edge_dir}/{install_script} with PTY (timeout={script_timeout}s)...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(sauropod_ip, port=ssh_port, username=ssh_username, password=root_pwd,
                       look_for_keys=False, allow_agent=False, timeout=30)

        transport = client.get_transport()
        channel = transport.open_session()
        channel.get_pty(term="xterm", width=200, height=50)
        channel.settimeout(1.0)
        channel.exec_command(f"cd {edge_dir} && bash {install_script}")

        buf = ""
        deadline = time.time() + script_timeout
        last_activity = time.time()
        answers_sent = 0

        while time.time() < deadline:
            try:
                chunk = channel.recv(4096).decode('utf-8', errors='replace')
                if chunk:
                    buf += chunk
                    last_activity = time.time()
                    if verbose:
                        for line in chunk.splitlines():
                            if line.strip():
                                logger.info(f"  {line}")
                    # respond to each [y/N]? prompt with 'y'
                    while buf.count('[y/N]?') > answers_sent:
                        time.sleep(0.3)
                        logger.info("  >>> Sending: y")
                        channel.sendall(b"y\n")
                        answers_sent += 1
            except socket.timeout:
                if time.time() - last_activity > 60:
                    logger.warning("  âš  No output for 60s, still waiting...")
                    last_activity = time.time()
            if channel.exit_status_ready():
                # drain remaining output
                try:
                    while True:
                        tail = channel.recv(4096).decode('utf-8', errors='replace')
                        if not tail:
                            break
                        buf += tail
                        if verbose:
                            for line in tail.splitlines():
                                if line.strip():
                                    logger.info(f"  {line}")
                except socket.timeout:
                    pass
                break

        if not channel.exit_status_ready():
            logger.error(f"âś— edge-install.sh timed out after {script_timeout}s")
            return False

        exit_code = channel.recv_exit_status()
        if exit_code != 0:
            logger.error(f"âś— edge-install.sh failed (rc={exit_code})")
            return False

        logger.info("âś“ edge-install.sh completed successfully")
        return True

    except Exception as e:
        logger.error(f"âś— Operation failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        client.close()


def monitor_edge_gateway_deployment(config, logger, verbose=True,
                                    namespace="edge",
                                    pod_prefix="edge-manager",
                                    appear_interval=15, appear_max=40,
                                    log_interval=30, log_max=60,
                                    completion_marker="EDGE_SERVICES_INSTALLATION_STATUS is Completed",
                                    debug=False, **kwargs):
    import time
    from core.ssh_client import SSHClient

    logger.info("=" * 80)
    logger.info("MONITOR EDGE GATEWAY DEPLOYMENT ON SAUROPOD")
    logger.info("=" * 80)

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')
    root_pwd = config.get_custom_variable('pwd')
    if not root_pwd:
        logger.error("pwd not found in custom_variables")
        return False

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_pwd,
                    port=ssh_port, timeout=60)
    try:
        if not ssh.connect():
            logger.error("âś— Failed to connect to sauropod")
            return False
        logger.info("âś“ Connected to sauropod")

        # â”€â”€ Phase 1: wait for edge-manager pod to appear â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        logger.info(f"âŹł Phase 1: Waiting for pod '{pod_prefix}*' in namespace '{namespace}'")
        logger.info(f"   Checking every {appear_interval}s (max {appear_max} checks)...")
        pod_name = None
        for check in range(1, appear_max + 1):
            time.sleep(appear_interval)
            result = ssh.execute_command(
                f"kubectl get pods -n {namespace} --no-headers 2>/dev/null",
                print_output=False
            )
            for line in result['stdout'].splitlines():
                if line.strip().startswith(pod_prefix):
                    pod_name = line.split()[0]
                    break
            if pod_name:
                logger.info(f"  âś“ #{check}/{appear_max}: Pod found â†’ {pod_name}")
                break
            logger.info(f"  #{check}/{appear_max}: Pod '{pod_prefix}*' not yet visible, waiting {appear_interval}s...")

        if not pod_name:
            logger.error(f"âś— Pod '{pod_prefix}*' did not appear after {appear_interval * appear_max}s")
            return False

        # â”€â”€ Phase 2: wait for completion log line â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        logger.info(f"âŹł Phase 2: Monitoring logs of {pod_name} (every {log_interval}s, max {log_max} checks)...")
        for check in range(1, log_max + 1):
            time.sleep(log_interval)
            logger.info(f"  Check #{check}/{log_max}: kubectl logs {pod_name} -n {namespace}...")
            result = ssh.execute_command(
                f"kubectl logs {pod_name} -n {namespace} 2>/dev/null | grep '{completion_marker}' | tail -n 1",
                print_output=False
            )
            line = result['stdout'].strip()
            if line:
                logger.info(f"  âś“ Completed: {line}")
                logger.info("=" * 80)
                logger.info("âś“ Edge gateway deployment completed successfully")
                logger.info("=" * 80)
                return True
            logger.info(f"  Not yet completed, waiting {log_interval}s...")

        logger.error(f"âś— Timeout: completion marker not found after {log_interval * log_max}s")
        return False

    except Exception as e:
        logger.error(f"âś— Operation failed: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()


def install_policy_on_sauropod(config, logger, verbose=True,
                               cm_appliance="cm",
                               policy_name="Default bootcamp policy",
                               units="sauropod.demo.guardium",
                               install_action="install_override",
                               debug=False, **kwargs):
    from core.guardium_rest_api import create_guardium_api

    logger.info("=" * 80)
    logger.info("INSTALL POLICY ON SAUROPOD")
    logger.info("=" * 80)
    logger.info(f"  policy={policy_name}, units={units}, install_action={install_action}")

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("pwd not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    logger.info(f"âžś Installing policy '{policy_name}' on units={units}...")
    result = api.install_policy(
        policy=policy_name,
        units=units,
        install_action=install_action,
        max_retries=3,
        retry_delay=60,
        debug=debug
    )

    error_code = result.get('ErrorCode') or result.get('ID', '0')
    if str(error_code) not in ('0', ''):
        logger.error(f"âś— Policy installation failed: {result}")
        return False

    logger.info(f"âś“ Policy '{policy_name}' installed on sauropod")
    return True


def import_edge_dashboard(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
    debug: bool = False
) -> bool:
    from core.guardium_rest_api import import_definitions_files

    logger.info("=" * 80)
    logger.info("IMPORT EDGE DASHBOARD ON CM")
    logger.info("=" * 80)

    definition_files = ["exp_dashboard_edge.sql"]

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
        logger.info("âś“ Edge dashboard imported successfully")

    return success


def configure_stap_for_edge_on_sauropod(config, logger, verbose=True,
                                        cm_appliance="cm",
                                        installation_delay=10,
                                        debug=False, **kwargs):
    import re
    import time
    from core.ssh_client import SSHClient
    from core.guardium_rest_api import create_guardium_api

    logger.info("=" * 80)
    logger.info("CONFIGURE STAP FOR EDGE ON SAUROPOD")
    logger.info("=" * 80)

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')
    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("pwd not found in custom_variables")
        return False

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=pwd,
                    port=ssh_port, timeout=30)

    # â”€â”€ Step 1: open NodePort range on sauropod firewall â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    logger.info("âžś Opening NodePort range 30000-32767/tcp on sauropod firewall...")
    try:
        if not ssh.connect():
            logger.error("âś— Failed to connect to sauropod")
            return False
        for cmd, desc in [
            ("firewall-cmd --permanent --add-port=30000-32767/tcp", "allow 30000-32767/tcp"),
            ("firewall-cmd --reload",                               "reload firewall"),
        ]:
            result = ssh.execute_command(cmd, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"âś— Failed to {desc}: {result['stderr']}")
                return False
            logger.info(f"  âś“ {desc}")
    finally:
        ssh.disconnect()

    # â”€â”€ Step 2: get NodePorts from sauropod â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    logger.info("âžś Getting haproxy NodePorts from sauropod...")
    try:
        if not ssh.connect():
            logger.error("âś— Failed to connect to sauropod")
            return False
        result = ssh.execute_command(
            "kubectl -n edge describe svc haproxy-kubernetes-ingress",
            print_output=False
        )
        if result['rc'] != 0:
            logger.error(f"âś— kubectl failed: {result['stderr']}")
            return False
        svc_output = result['stdout']
    finally:
        ssh.disconnect()

    # parse NodePort for port-16016 (STAP_SQLGUARD_PORT)
    m16016 = re.search(r'NodePort:\s+port-16016\s+(\d+)/TCP', svc_output)
    m16018 = re.search(r'NodePort:\s+port-16018\s+(\d+)/TCP', svc_output)
    if not m16016:
        logger.error("âś— NodePort for port-16016 not found in kubectl output")
        return False
    if not m16018:
        logger.error("âś— NodePort for port-16018 not found in kubectl output")
        return False
    node_port_16016 = m16016.group(1)
    node_port_16018 = m16018.group(1)
    logger.info(f"  NodePort 16016 â†’ {node_port_16016}")
    logger.info(f"  NodePort 16018 â†’ {node_port_16018}")

    # â”€â”€ Step 3: set GIM params â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    params = [
        ("STAP_USING_EDGE",       "1"),
        ("STAP_ENABLED",          "1"),
        ("STAP_SQLGUARD_IP",      sauropod_ip),
        ("STAP_SQLGUARD_PORT",    node_port_16016),
        ("STAP_SQLGUARD_TLS_PORT", node_port_16018),
    ]
    for param, value in params:
        logger.info(f"  Setting {param}={value} on sauropod ({sauropod_ip})")
        api.gim_client_params(client_ip=sauropod_ip, param_name=param, param_value=value)

    # â”€â”€ Step 4: schedule install + monitor â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    logger.info("âžś Scheduling GIM install on sauropod...")
    api.gim_schedule_install(client_ip=sauropod_ip, date="now")
    logger.info(f"âś“ Scheduled. Waiting {installation_delay}s before monitoring...")
    time.sleep(installation_delay)

    logger.info("âžś Monitoring installation progress...")
    check_count = 0
    while True:
        check_count += 1
        logger.info(f"  Check #{check_count}: Querying module status...")
        modules = api.gim_list_client_modules(client_ip=sauropod_ip)

        if "ErrorCode" in modules or "ErrorMessage" in modules:
            logger.error(f"  âś— API Error: {modules.get('ErrorCode')} {modules.get('ErrorMessage')}")
            return False

        entries = [e.strip() for e in re.split(r"#+\s*ENTRY\s+\d+\s*#+", modules.get("Message", "")) if e.strip()]
        result_mods = []
        for e in entries:
            m_name = re.search(r"NAME:\s+([A-Z0-9\-]+)", e)
            m_state = re.search(r"STATE:\s+([A-Z\-]+)", e)
            result_mods.append({"name": m_name.group(1) if m_name else "?", "state": m_state.group(1) if m_state else "?"})
        pending = [m for m in result_mods if m["state"] != "INSTALLED"]
        if pending:
            logger.info(f"  âŚ› {len(pending)} module(s) still installing: {[m['name'] for m in pending]}")
            logger.info("  Waiting 30s before next check...")
            time.sleep(30)
        else:
            logger.info("  âś“ All modules installed successfully!")
            break

    logger.info("âś“ STAP configured for Edge on sauropod")
    return True





def extract_zip_on_ceratops(config, logger, verbose=True,
                             ceratops_machine: str = "ceratops",
                             ssh_username: str = "itzuser",
                             zip_path: str = r'C:\bootcamp\zip\GIM-Installer-12.2_r120202259_1.zip',
                             dest_dir: str = r'C:\bootcamp',
                             debug: bool = False, **kwargs) -> bool:
    import tempfile
    import os
    from core.ssh_client import SSHClient

    logger.info("=" * 80)
    logger.info("EXTRACT ZIP ON CERATOPS")
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
            cmd = f'powershell -Command "Expand-Archive -Path \'{zip_path}\' -DestinationPath \'{dest_dir}\' -Force"'
            logger.info(f"  âžś Extracting {zip_path} â†’ {dest_dir}")
            result = ssh.execute_command(cmd, timeout=120, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"âś— Extraction failed (rc={result['rc']}): {result['stderr'].strip() or result['stdout'].strip()}")
                return False
            logger.info(f"âś“ Extracted {zip_path} to {dest_dir} on {ceratops_machine}")
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


def install_gim_on_ceratops(config, logger, verbose=True,
                             ceratops_machine: str = "ceratops",
                             ssh_username: str = "itzuser",
                             setup_exe: str = r'C:\bootcamp\gim_unpacked\GIM_Client\Setup.exe',
                             appliance: str = "coll1.demo.guardium",
                             local_ip: Optional[str] = None,
                             debug: bool = False, **kwargs) -> bool:
    import tempfile
    import os
    from core.ssh_client import SSHClient

    logger.info("=" * 80)
    logger.info("INSTALL GIM ON CERATOPS")
    logger.info("=" * 80)

    ceratops_ip = config.get_machine_ip(ceratops_machine, use_private=True)
    if not ceratops_ip:
        logger.error(f"âś— IP not found for machine: {ceratops_machine}")
        return False

    if not local_ip:
        local_ip = ceratops_ip

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
            cmd = f'"{setup_exe}" -UNATTENDED -APPLIANCE {appliance} -LOCALIP {local_ip}'
            logger.info(f"  âžś {cmd}")
            result = ssh.execute_command(cmd, timeout=300, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"âś— GIM installation failed (rc={result['rc']}): {result['stderr'].strip() or result['stdout'].strip()}")
                return False
            logger.info(f"âś“ GIM installed on {ceratops_machine}")
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


def install_winstap_on_ceratops(config, logger, verbose=False,
                                 appliance_name: str = "cm",
                                 collector_name: str = "coll1",
                                 client_ip: Optional[str] = None,
                                 module: str = "WINSTAP",
                                 module_version: str = "",
                                 gim_registration_delay: int = 60,
                                 debug: bool = False, **kwargs) -> bool:
    import time
    from core.appliance_operations import install_gim_module
    from core.appliance_config_loader import ApplianceConfigLoader

    logger.info("=" * 80)
    logger.info("INSTALL WINSTAP ON CERATOPS")
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

    logger.info(f"âŚ› Waiting {gim_registration_delay}s for GIM client registration...")
    time.sleep(gim_registration_delay)

    return install_gim_module(
        config=config,
        logger=logger,
        appliance_name=appliance_name,
        client_ip=client_ip,
        module=module,
        module_version=module_version,
        params={"WINSTAP_SQLGUARD_IP": sqlguard_ip},
        monitor_installation=True,
        installation_delay=10,
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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Oracle Deployment Task
Handles Oracle installation and configuration on remote machine (sauropod)
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import ConfigLoader
from core.ssh_client import SSHClient


def _header(logger, title: str):
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)


def _ssh_cmd(ssh, cmd, logger, desc: str, timeout: int = 60, warning: bool = False) -> bool:
    result = ssh.execute_command(cmd, timeout=timeout, print_output=False)
    if result['rc'] != 0:
        msg = f"{'⚠' if warning else '✗'} Failed to {desc}: {result['stderr'].strip()}"
        if warning:
            logger.warning(msg)
        else:
            logger.error(msg)
        return False
    return True


def _ssh_upload(ssh, src, dest, logger, desc: str) -> bool:
    logger.info(f"  ➜ upload {src} → {dest}")
    if not ssh.upload_file(str(src), str(dest)):
        logger.error(f"✗ Failed to upload {desc}")
        return False
    logger.info(f"  ✓ {desc} uploaded")
    return True


def _ssh_cmds(ssh, commands, logger, desc: str, timeout: int = 60, stop_on_error: bool = True) -> bool:
    results = ssh.execute_commands(commands=commands, timeout=timeout, print_output=False, stop_on_error=stop_on_error)
    failed = [r for r in results if r['rc'] != 0]
    if failed:
        logger.error(f"✗ Failed to {desc}: {failed[0]['stderr'].strip()}")
        return False
    return True


def deploy_oracle_on_sauropod(config: ConfigLoader, logger, verbose: bool = True, **kwargs) -> bool:
    _header(logger, "Oracle Database 21c deployment on sauropod")

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("✗ sauropod IP not found in configuration")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')

    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("✗ pwd not found in custom_variables")
        return False

    logger.info(f"  ➜ SSH {ssh_username}@{sauropod_ip}:{ssh_port}")

    try:
        with SSHClient(host=sauropod_ip, username=ssh_username, password=root_password,
                       port=ssh_port, timeout=60) as ssh:
            logger.info("  ✓ Connected to sauropod")

            # ── upload Oracle files ───────────────────────────────────────────
            preinstall_src  = "/opt/guardium_tz_bootcamp_automation/upload/source_files/oracle/oracle-database-preinstall-21c-1.0-1.el8.x86_64.rpm"
            preinstall_dest = "/tmp/oracle-database-preinstall-21c-1.0-1.el8.x86_64.rpm"
            db_archive_src  = "/opt/guardium_tz_bootcamp_automation/upload/source_files/oracle/LINUX.X64_213000_db_home.zip"
            db_archive_dest = "/tmp/LINUX.X64_213000_db_home.zip"

            if not _ssh_upload(ssh, preinstall_src, preinstall_dest, logger, "oracle-database-preinstall RPM"):
                return False
            if not _ssh_upload(ssh, db_archive_src, db_archive_dest, logger, "Oracle db_home.zip"):
                return False

            ssh.execute_command(f"chown oracle:oinstall {db_archive_dest} 2>/dev/null || true", timeout=30, print_output=False)

            # ── prerequisites ─────────────────────────────────────────────────
            logger.info(f"  ➜ dnf install --nogpgcheck {preinstall_dest}")
            for _attempt in range(1, 6):
                if _ssh_cmds(ssh, [f"dnf install -y --nogpgcheck {preinstall_dest}"], logger, "install Oracle prerequisites", timeout=600):
                    break
                if _attempt < 5:
                    logger.warning(f"⚠ rpm.lock busy, waiting 60s (attempt {_attempt}/5)...")
                    time.sleep(60)
            else:
                logger.error("✗ Failed to install Oracle prerequisites after 5 attempts")
                return False
            logger.info("  ✓ Oracle prerequisites installed")

            # ── directories ───────────────────────────────────────────────────
            logger.info("  ➜ mkdir /u01/app/oracle/product/21c/dbhome_1 + chown/chmod")
            if not _ssh_cmds(ssh, [
                "mkdir -p /u01/app/oracle/product/21c/dbhome_1",
                "chown -R oracle:oinstall /u01",
                "chmod -R 775 /u01",
            ], logger, "create Oracle directories"):
                return False
            logger.info("  ✓ Oracle directories created")

            # ── oracle user environment ───────────────────────────────────────
            logger.info("  ➜ append ORACLE_BASE/HOME/SID/PATH to oracle ~/.bashrc")
            bashrc_cmd = """su - oracle -c "cat >> ~/.bashrc << 'EOF'

# Oracle environment variables
export ORACLE_BASE=/u01/app/oracle
export ORACLE_HOME=\\$ORACLE_BASE/product/21c/dbhome_1
export ORACLE_SID=ORCLCDB
export TNS_ADMIN=\\$ORACLE_HOME/network/admin
export PATH=\\$ORACLE_HOME/bin:\\$PATH

# SQLcl PATH
export PATH=\\$PATH:/opt/sqlcl/sqlcl/bin

# SQLcl aliases (removed /nolog to prompt for connection)
alias sqlnolog='sql /nolog'

# SQLcl history settings
export SQLPATH=\\$HOME/.sqlcl
EOF
" """
            if not _ssh_cmd(ssh, bashrc_cmd, logger, "configure oracle user environment"):
                return False
            logger.info("  ✓ Oracle user environment configured")

            # ── unzip db_home ─────────────────────────────────────────────────
            logger.info("  ➜ su - oracle -c 'unzip -q LINUX.X64_213000_db_home.zip -d $ORACLE_HOME'")
            if not _ssh_cmd(ssh,
                            "su - oracle -c 'unzip -q /tmp/LINUX.X64_213000_db_home.zip -d $ORACLE_HOME'",
                            logger, "extract Oracle installation archive", timeout=1800):
                return False
            logger.info("  ✓ Oracle installation archive extracted")

            # ── SSH config for oracle user ────────────────────────────────────
            logger.info("  ➜ hostname")
            hostname_result = ssh.execute_command("hostname", timeout=30, print_output=False)
            if hostname_result['rc'] != 0:
                logger.error("✗ Failed to get hostname")
                return False
            hostname = hostname_result['stdout'].strip()

            logger.info(f"  ➜ write oracle ~/.ssh/config (localhost + {hostname} → port 2223)")
            ssh_config_content = (
                f"Host localhost\n    Port 2223\n    StrictHostKeyChecking no\n"
                f"Host {hostname}\n    Port 2223\n    StrictHostKeyChecking no\n"
            )
            ssh.execute_command("su - oracle -c 'mkdir -p ~/.ssh'", timeout=30, print_output=False)
            config_cmd = f"su - oracle -c 'cat >> ~/.ssh/config <<EOF\n{ssh_config_content}EOF'"
            if not _ssh_cmd(ssh, config_cmd, logger, "configure SSH for oracle user"):
                return False
            ssh.execute_command("su - oracle -c 'chmod 600 ~/.ssh/config'", timeout=30, print_output=False)
            logger.info("  ✓ SSH configured for oracle user")

            # ── Oracle installer ──────────────────────────────────────────────
            logger.info("  ➜ runInstaller -silent INSTALL_DB_SWONLY EE (up to 60 min)")
            installer_cmd = """su - oracle -c 'cd $ORACLE_HOME && ./runInstaller -silent \
  oracle.install.option=INSTALL_DB_SWONLY \
  ORACLE_BASE=$ORACLE_BASE \
  ORACLE_HOME=$ORACLE_HOME \
  oracle.install.db.InstallEdition=EE \
  oracle.install.db.OSDBA_GROUP=dba \
  oracle.install.db.OSOPER_GROUP=dba \
  oracle.install.db.OSBACKUPDBA_GROUP=dba \
  oracle.install.db.OSDGDBA_GROUP=dba \
  oracle.install.db.OSKMDBA_GROUP=dba \
  oracle.install.db.OSRACDBA_GROUP=dba \
  -ignorePrereqFailure'"""
            result = ssh.execute_command(installer_cmd, timeout=3600, print_output=False, ok_rc=[6])
            if result['rc'] not in [0, 6]:
                logger.error(f"✗ Oracle installer failed (rc={result['rc']}): {result['stderr'].strip()}")
                return False
            if result['rc'] == 6:
                logger.info("  ⚠ Oracle installer completed with warnings")
            else:
                logger.info("  ✓ Oracle installer completed")

            # ── post-install root scripts ─────────────────────────────────────
            for script in ["/u01/app/oraInventory/orainstRoot.sh",
                           "/u01/app/oracle/product/21c/dbhome_1/root.sh"]:
                logger.info(f"  ➜ {script}")
                if not _ssh_cmd(ssh, script, logger, f"execute {script}", timeout=300):
                    return False
            logger.info("  ✓ Post-installation root scripts completed")

            # ── listener ──────────────────────────────────────────────────────
            logger.info("  ➜ netca -silent -responseFile netca.rsp")
            if not _ssh_cmd(ssh,
                            "su - oracle -c '$ORACLE_HOME/bin/netca -silent -responseFile $ORACLE_HOME/assistants/netca/netca.rsp'",
                            logger, "configure Oracle listener", timeout=600):
                return False
            logger.info("  ✓ Oracle listener configured")

            # ── create database ───────────────────────────────────────────────
            logger.info("  ➜ dbca -silent -createDatabase ORCLCDB/ORCLPDB1 (up to 60 min)")
            dbca_cmd = f"""su - oracle -c 'dbca -silent -createDatabase \
  -templateName General_Purpose.dbc \
  -gdbname ORCLCDB \
  -sid ORCLCDB \
  -createAsContainerDatabase true \
  -numberOfPDBs 1 \
  -pdbName ORCLPDB1 \
  -sysPassword "{root_password}" \
  -systemPassword "{root_password}" \
  -pdbAdminPassword "{root_password}" \
  -characterSet AL32UTF8 \
  -memoryMgmtType auto_sga \
  -totalMemory 1500 \
  -storageType FS \
  -datafileDestination "/u01/app/oracle/oradata"'"""
            if not _ssh_cmd(ssh, dbca_cmd, logger, "create Oracle database", timeout=3600):
                return False
            logger.info("  ✓ Oracle database created")

            # ── PDB auto-start ────────────────────────────────────────────────
            logger.info("  ➜ ALTER PLUGGABLE DATABASE ALL SAVE STATE")
            if not _ssh_cmd(ssh,
                            """su - oracle -c 'export ORACLE_SID=ORCLCDB && echo "ALTER PLUGGABLE DATABASE ALL SAVE STATE;" | sqlplus -s / as sysdba'""",
                            logger, "configure PDB auto-start", timeout=300):
                return False
            logger.info("  ✓ Pluggable databases configured to auto-start")

            # ── listener.ora / tnsnames.ora / sqlnet.ora ─────────────────────
            net_admin_dir = "$ORACLE_HOME/network/admin"
            for local_name, remote_tmp, desc in [
                ("listener.ora", "/tmp/listener.ora", "listener.ora"),
                ("tnsnames.ora", "/tmp/tnsnames.ora", "tnsnames.ora"),
                ("sqlnet.ora",   "/tmp/sqlnet.ora",   "sqlnet.ora"),
            ]:
                local_path = Path(__file__).parent.parent / "automation_config_files" / local_name
                if not local_path.exists():
                    logger.error(f"✗ {local_name} not found at {local_path}")
                    return False
                if not _ssh_upload(ssh, local_path, remote_tmp, logger, local_name):
                    return False
                copy_cmd = f"su - oracle -c 'cp {remote_tmp} {net_admin_dir}/{local_name} && chmod 644 {net_admin_dir}/{local_name}'"
                if not _ssh_cmd(ssh, copy_cmd, logger, f"copy {local_name} to network/admin"):
                    return False
            logger.info("  ✓ listener.ora / tnsnames.ora / sqlnet.ora configured")

            # ── listener restart ──────────────────────────────────────────────
            logger.info("  ➜ lsnrctl stop + start")
            ssh.execute_command("su - oracle -c 'lsnrctl stop'", timeout=120, print_output=False)
            results = ssh.execute_commands(
                commands=["su - oracle -c 'lsnrctl start'"],
                timeout=120, print_output=False, stop_on_error=False
            )
            if results and results[0]['rc'] != 0:
                logger.error(f"✗ Failed to start Oracle listener: {results[0]['stderr'].strip()}")
                return False
            logger.info("  ✓ Oracle listener restarted")

            # ── oratab auto-start ─────────────────────────────────────────────
            logger.info("  ➜ sed /etc/oratab ORCLCDB:...:N → :Y")
            if not _ssh_cmd(ssh, "sed -i 's/^ORCLCDB:\\(.*\\):N$/ORCLCDB:\\1:Y/' /etc/oratab",
                            logger, "configure /etc/oratab"):
                return False
            verify = ssh.execute_command("grep ORCLCDB /etc/oratab", timeout=30, print_output=False)
            if verify['rc'] == 0 and ':Y' in verify['stdout']:
                logger.info("  ✓ /etc/oratab auto-start enabled")
            else:
                logger.warning("  Could not verify /etc/oratab")

            # ── HR schema ─────────────────────────────────────────────────────
            hr_archive_path  = "/opt/guardium_tz_bootcamp_automation/upload/source_files/oracle/human_resources.tar.gz"
            hr_remote_path   = "/home/oracle/human_resources.tar.gz"

            if not _ssh_upload(ssh, hr_archive_path, hr_remote_path, logger, "HR schema archive"):
                return False
            if not _ssh_cmd(ssh, f"chown oracle:oinstall {hr_remote_path}",
                            logger, "chown HR archive"):
                return False

            logger.info(f"  ➜ tar -xzf {hr_remote_path}")
            if not _ssh_cmd(ssh, f"su - oracle -c 'cd /home/oracle && tar -xzf {hr_remote_path}'",
                            logger, "extract HR schema archive", timeout=120):
                return False
            logger.info("  ✓ HR schema archive extracted")

            escaped_password = root_password.replace('\\', '\\\\').replace('/', '\\/').replace('&', '\\&').replace('!', '\\!')
            logger.info("  ➜ sed hr_install.sql: update DEFINE pass")
            if not _ssh_cmd(ssh,
                            f"su - oracle -c 'sed -i \"s/DEFINE pass = .\\+/DEFINE pass = \\x27{escaped_password}\\x27/\" /home/oracle/human_resources/hr_install.sql'",
                            logger, "update password in hr_install.sql"):
                return False

            logger.info("  ➜ CREATE TABLESPACE hr_data in ORCLPDB1")
            if not _ssh_cmd(ssh, """su - oracle -c "export ORACLE_SID=ORCLCDB && sqlplus -s / as sysdba << 'EOF'
ALTER SESSION SET CONTAINER = ORCLPDB1;
CREATE TABLESPACE hr_data DATAFILE '/u01/app/oracle/oradata/ORCLCDB/ORCLPDB1/hr_data01.dbf' SIZE 100M AUTOEXTEND ON NEXT 10M MAXSIZE 1G;
EXIT;
EOF
" """, logger, "create HR tablespace", timeout=300):
                return False
            logger.info("  ✓ HR tablespace created")

            logger.info("  ➜ @hr_install.sql in ORCLPDB1 (up to 10 min)")
            if not _ssh_cmd(ssh, """su - oracle -c "export ORACLE_SID=ORCLCDB && cd /home/oracle/human_resources && sqlplus -s / as sysdba << 'EOF'
ALTER SESSION SET CONTAINER = ORCLPDB1;
@hr_install.sql
EXIT;
EOF
" """, logger, "install HR schema", timeout=600):
                return False
            logger.info("  ✓ HR schema installed")

            # ── cleanup ───────────────────────────────────────────────────────
            logger.info("  ➜ rm db_home.zip, human_resources.tar.gz, human_resources/")
            _ssh_cmds(ssh, [
                "rm -f /tmp/LINUX.X64_213000_db_home.zip",
                "su - oracle -c 'rm -f /home/oracle/human_resources.tar.gz'",
                "su - oracle -c 'rm -rf /home/oracle/human_resources'",
            ], logger, "cleanup installation files", stop_on_error=False)

            # ── SQLcl ─────────────────────────────────────────────────────────
            logger.info("  ➜ curl sqlcl-latest.zip + unzip /opt/sqlcl")
            failed_sqlcl = not _ssh_cmds(ssh, [
                "cd /tmp",
                "curl -L -o sqlcl-latest.zip https://download.oracle.com/otn_software/java/sqldeveloper/sqlcl-latest.zip",
                "mkdir -p /opt/sqlcl",
                "unzip -q -o sqlcl-latest.zip -d /opt/sqlcl",
                "rm -f /tmp/sqlcl-latest.zip",
            ], logger, "install SQLcl", timeout=600)
            if failed_sqlcl:
                logger.warning("  SQLcl installation failed — continuing")
            else:
                logger.info("  ✓ SQLcl installed")

            ssh.execute_command("su - oracle -c 'mkdir -p ~/.sqlcl'", timeout=60, print_output=False)
            login_sql_path = Path(__file__).parent.parent / "automation_config_files" / "sqlcl_login.sql"
            if login_sql_path.exists():
                if ssh.upload_file(str(login_sql_path), "/tmp/sqlcl_login.sql"):
                    if _ssh_cmd(ssh, "su - oracle -c 'cp /tmp/sqlcl_login.sql ~/.sqlcl/login.sql && chmod 644 ~/.sqlcl/login.sql'",
                                logger, "configure SQLcl login.sql"):
                        logger.info("  ✓ SQLcl login.sql configured")
                else:
                    logger.warning("  Failed to upload SQLcl login.sql")
            else:
                logger.warning(f"  SQLcl login.sql not found at {login_sql_path}")

            logger.info("  ➜ write oracle ~/.inputrc (readline meta-flag)")
            result = ssh.execute_command("""su - oracle -c "cat > ~/.inputrc << 'EOF'
# Basic readline settings
set meta-flag on
set input-meta on
set convert-meta off
EOF
" """, timeout=60, print_output=False)
            if result['rc'] == 0:
                logger.info("  ✓ ~/.inputrc created")
            else:
                logger.warning("  Failed to create ~/.inputrc")

            # ── SSL/TLS wallets ───────────────────────────────────────────────
            _header(logger, "Configuring SSL/TLS for Oracle")

            oracle_home      = "/u01/app/oracle/product/21c/dbhome_1"
            wallet_dir       = f"{oracle_home}/wallet"
            client_wallet_dir= f"{oracle_home}/client_wallet"
            orapki           = f"{oracle_home}/bin/orapki"

            for step_desc, cmd, timeout in [
                ("mkdir server wallet dir",
                 f"su - oracle -c 'mkdir -p {wallet_dir}'", 30),
                ("orapki wallet create (server)",
                 f"su - oracle -c \"{orapki} wallet create -wallet {wallet_dir} -auto_login_local -pwd '{root_password}'\"", 60),
                ("orapki wallet add CN=sauropod (server cert)",
                 f"su - oracle -c \"{orapki} wallet add -wallet {wallet_dir} -dn 'CN=sauropod.demo.guardium' -keysize 2048 -self_signed -validity 3650 -pwd '{root_password}'\"", 60),
                ("mkdir client wallet dir",
                 f"su - oracle -c 'mkdir -p {client_wallet_dir}'", 30),
                ("orapki wallet create (client)",
                 f"su - oracle -c \"{orapki} wallet create -wallet {client_wallet_dir} -auto_login_local -pwd '{root_password}'\"", 60),
                ("orapki wallet add CN=client (client cert)",
                 f"su - oracle -c \"{orapki} wallet add -wallet {client_wallet_dir} -dn 'CN=client' -keysize 2048 -self_signed -validity 3650 -pwd '{root_password}'\"", 60),
                ("orapki export server cert → /tmp/server-cert.crt",
                 f"su - oracle -c \"{orapki} wallet export -wallet {wallet_dir} -dn 'CN=sauropod.demo.guardium' -cert /tmp/server-cert.crt -pwd '{root_password}'\"", 60),
                ("orapki export client cert → /tmp/client-cert.crt",
                 f"su - oracle -c \"{orapki} wallet export -wallet {client_wallet_dir} -dn 'CN=client' -cert /tmp/client-cert.crt -pwd '{root_password}'\"", 60),
                ("orapki add server-cert to client wallet (cross-trust)",
                 f"su - oracle -c \"{orapki} wallet add -wallet {client_wallet_dir} -trusted_cert -cert /tmp/server-cert.crt -pwd '{root_password}'\"", 60),
                ("orapki add client-cert to server wallet (cross-trust)",
                 f"su - oracle -c \"{orapki} wallet add -wallet {wallet_dir} -trusted_cert -cert /tmp/client-cert.crt -pwd '{root_password}'\"", 60),
            ]:
                logger.info(f"  ➜ {step_desc}")
                if not _ssh_cmd(ssh, cmd, logger, step_desc, timeout=timeout):
                    return False

            ssh.execute_command("su - oracle -c 'rm -f /tmp/server-cert.crt /tmp/client-cert.crt'",
                                timeout=30, print_output=False)
            logger.info("  ✓ SSL/TLS wallets created and cross-trusted")

            # ── upload network/admin files for SSL ────────────────────────────
            net_admin = f"{oracle_home}/network/admin"
            for src, dest_name in [
                ("/opt/guardium_tz_bootcamp_automation/automation_config_files/listener.ora", "listener.ora"),
                ("/opt/guardium_tz_bootcamp_automation/automation_config_files/tnsnames.ora", "tnsnames.ora"),
                ("/opt/guardium_tz_bootcamp_automation/automation_config_files/sqlnet.ora",   "sqlnet.ora"),
            ]:
                if not _ssh_upload(ssh, src, f"{net_admin}/{dest_name}", logger, dest_name):
                    return False
            if not _ssh_cmd(ssh, f"chown -R oracle:oinstall {net_admin}/",
                            logger, "chown network/admin"):
                return False

            logger.info("  ➜ lsnrctl stop + start (SSL config)")
            ssh.execute_command(f"su - oracle -c '{oracle_home}/bin/lsnrctl stop'", timeout=60, print_output=False)
            result = ssh.execute_command(f"su - oracle -c '{oracle_home}/bin/lsnrctl start'", timeout=60, print_output=False)
            if result['rc'] != 0:
                logger.warning(f"  lsnrctl start returned non-zero: {result['stderr'].strip()}")

            logger.info("  ➜ ALTER SYSTEM SET local_listener + REGISTER")
            result = ssh.execute_command(
                f"su - oracle -c \"echo -e 'ALTER SYSTEM SET local_listener=\\\"(ADDRESS=(PROTOCOL=TCP)(HOST=sauropod.demo.guardium)(PORT=1521))\\\" SCOPE=BOTH;\\nALTER SYSTEM REGISTER;\\nexit' | {oracle_home}/bin/sqlplus / as sysdba\"",
                timeout=60, print_output=False
            )
            if result['rc'] != 0:
                logger.warning(f"  ALTER SYSTEM REGISTER returned non-zero: {result['stderr'].strip()}")

            logger.info(
                f"✓ Oracle 21c deployment completed — DB: ORCLCDB, PDB: ORCLPDB1, "
                f"SSL: on (wallet: {wallet_dir}), HR schema: installed, SQLcl: installed"
            )
            return True

    except Exception as e:
        logger.error(f"✗ Oracle deployment error: {e}")
        return False


def setup_oracle_container_on_sauropod(
    config: ConfigLoader,
    logger,
    verbose: bool = False,
    image_source_path: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/oracle/oracle_db_21c_image_with_oua.tar.gz",
    debug: bool = False,
    **kwargs
) -> bool:
    _header(logger, "Setup Oracle container on sauropod")

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("✗ sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')

    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("✗ pwd not found in custom_variables")
        return False

    image_filename = os.path.basename(image_source_path)
    remote_image_path = f"/opt/lab_files/{image_filename}"

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password, port=ssh_port, timeout=60)

    try:
        logger.info(f"  ➜ SSH {ssh_username}@{sauropod_ip}:{ssh_port}")
        if not ssh.connect():
            logger.error("✗ Failed to connect to sauropod")
            return False
        logger.info("  ✓ Connected to sauropod")

        logger.info("  ➜ mkdir -p /opt/lab_files")
        if not _ssh_cmd(ssh, "mkdir -p /opt/lab_files", logger, "create /opt/lab_files"):
            return False

        if not _ssh_upload(ssh, image_source_path, remote_image_path, logger, image_filename):
            return False

        logger.info(f"  ➜ gunzip -c {image_filename} | podman load")
        if not _ssh_cmd(ssh, f"cd /opt/lab_files && gunzip -c {image_filename} | podman load",
                        logger, "podman load Oracle image", timeout=600):
            return False
        logger.info("  ✓ Oracle container image loaded")

        logger.info("  ➜ mkdir /opt/oradata + chown 54321 + chmod 775 + restorecon")
        for cmd in [
            "mkdir -p /opt/oradata",
            "chown -R 54321:54321 /opt/oradata",
            "chmod -R 775 /opt/oradata",
            "restorecon -Rv /opt/oradata",
        ]:
            if not _ssh_cmd(ssh, cmd, logger, cmd, timeout=60):
                return False

        semanage_cmd = "semanage fcontext -a -t container_file_t '/opt/oradata(/.*)?' "
        logger.info(f"  ➜ {semanage_cmd.strip()}")
        for attempt in range(1, 11):
            result = ssh.execute_command(semanage_cmd, timeout=60, print_output=False)
            if result['rc'] == 0:
                break
            if 'Resource temporarily unavailable' in result['stderr'] or 'Could not get' in result['stderr']:
                logger.warning(f"  semanage lock busy (attempt {attempt}/10), retrying in 30s...")
                time.sleep(30)
            else:
                logger.error(f"✗ semanage failed: {result['stderr'].strip()}")
                return False
        else:
            logger.error("✗ semanage failed after 10 attempts (lock busy)")
            return False
        logger.info("  ✓ oradata directory configured")

        logger.info("  ➜ podman run oracle/database:21.3.0-ee-oua")
        run_cmd = (
            f"podman run -d --restart unless-stopped --name oracle_db_21c"
            f" -p 1522:1521 -p 5501:5500"
            f" -e ORACLE_EDITION=EE -e ORACLE_SID=ORCL -e ORACLE_PDB=ORCLPDB1"
            f" -e ORACLE_CHARACTERSET=AL32UTF8 -e ORACLE_SERVICE_NAME=ORCLPDB1.localdomain"
            f" -v /opt/oradata:/opt/oracle/oradata"
            f" -e ORACLE_PWD='{root_password}'"
            f" oracle/database:21.3.0-ee-oua"
        )
        if not _ssh_cmd(ssh, run_cmd, logger, "podman run Oracle container"):
            return False
        logger.info("  ✓ Oracle container started")

        # switch to restart=always when podman 5.x will be available
        # podman update --restart=always oracle_db_21c
        for cmd, desc in [
            ("podman generate systemd --name oracle_db_21c --files",                                        "podman generate systemd"),
            ("mv container-oracle_db_21c.service /etc/systemd/system/",                                    "mv service file"),
            ("sed -i 's/Restart=no/Restart=always/' /etc/systemd/system/container-oracle_db_21c.service", "sed Restart=always"),
            ("systemctl daemon-reload",                                                                      "daemon-reload"),
            ("systemctl enable container-oracle_db_21c.service",                                            "enable service"),
        ]:
            logger.info(f"  ➜ {cmd}")
            if not _ssh_cmd(ssh, cmd, logger, desc):
                return False
        logger.info("  ✓ oracle_db_21c configured for auto-restart via systemd")

        logger.info(f"  ➜ rm -f {remote_image_path}")
        result = ssh.execute_command(f"rm -f {remote_image_path}", print_output=False)
        if result['rc'] != 0:
            logger.warning(f"  Failed to remove image archive: {result['stderr'].strip()}")
        else:
            logger.info("  ✓ Image archive removed")

    except Exception as e:
        logger.error(f"✗ Oracle container setup error: {e}")
        return False
    finally:
        ssh.disconnect()

    logger.info("✓ Oracle container setup completed on sauropod")
    return True


# Made with Bob

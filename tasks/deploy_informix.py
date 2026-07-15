#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import execute_local_command, execute_commands, ConfigLoader

SYSCTL_CONTENT = (
    "# Informix shared memory settings\n"
    "kernel.shmmax = 8589934592\n"
    "kernel.shmall = 2097152\n"
    "kernel.shmmni = 4096\n"
    "\n"
    "# Semaphores: semmsl semmns semopm semmni\n"
    "kernel.sem = 250 32000 100 128\n"
    "\n"
    "# Maximum number of open file descriptors per process\n"
    "fs.file-max = 65536\n"
    "\n"
    "# Local port range\n"
    "net.ipv4.ip_local_port_range = 1024 65000\n"
)

SYSCTL_FILE = "/etc/sysctl.d/99-informix.conf"

LIMITS_CONTENT = (
    "\n# Resource limits for the informix OS user\n"
    "informix  soft  nofile   65536\n"
    "informix  hard  nofile   65536\n"
    "informix  soft  nproc    16384\n"
    "informix  hard  nproc    16384\n"
    "informix  soft  stack    32768\n"
    "informix  hard  stack    32768\n"
    "informix  soft  memlock  unlimited\n"
    "informix  hard  memlock  unlimited\n"
)

LIMITS_FILE = "/etc/security/limits.conf"

INSTALL_DIR     = "/opt/ibm/informix"
INFORMIX_SERVER = "ifxserver"
INFORMIX_HOST   = "raptor.demo.guardium"
INFORMIX_PORT   = 9088
ROOTDBS_SIZE_KB = 200000


def _run(cmd, logger, verbose, desc):
    result = execute_local_command(cmd, logger, verbose)
    if result['rc'] != 0:
        logger.error(f"Failed to {desc}: {result['stderr']}")
        return False
    return result


def _env(install_dir, informix_server):
    return (
        f"INFORMIXDIR={install_dir} "
        f"INFORMIXSERVER={informix_server} "
        f"ONCONFIG=onconfig.{informix_server} "
        f"INFORMIXSQLHOSTS={install_dir}/etc/sqlhosts "
        f"PATH={install_dir}/bin:$PATH "
        f"LD_LIBRARY_PATH={install_dir}/lib:{install_dir}/lib/esql"
    )


def deploy_informix(
    config, logger, verbose: bool = True,
    installer_filename: str = "ibm.server.15.0.1.0.Linux.64.x86_64.tar",
    installer_source_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/informix",
    install_tmp_dir: str = "/opt/informix_tmp",
    install_dir: str = INSTALL_DIR,
    informix_server: str = INFORMIX_SERVER,
    informix_host: str = INFORMIX_HOST,
    informix_port: int = INFORMIX_PORT,
    informix_admin_port: int = 9089,
    rootdbs_size_kb: int = ROOTDBS_SIZE_KB,
    jdbc_jars: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/informix/jdbc-15.0.1.3.jar:/opt/guardium_tz_bootcamp_automation/upload/source_files/informix/bson-4.11.1.jar",
    **kwargs
) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("DEPLOY INFORMIX")
        logger.info("=" * 80)

    password = config.get_custom_variable('pwd')
    if not password:
        logger.error("pwd not found in custom_variables")
        return False

    import os
    local_installer = f"{installer_source_dir}/{installer_filename}"
    if not os.path.exists(local_installer):
        logger.error(f"Installer not found: {local_installer}")
        return False

    onconfig_file   = f"{install_dir}/etc/onconfig.{informix_server}"
    bash_profile    = "/home/informix/.bash_profile"
    sqlhosts        = f"{install_dir}/etc/sqlhosts"
    service_name    = f"informix-{informix_server}"
    service_file    = f"/etc/systemd/system/{service_name}.service"
    env             = _env(install_dir, informix_server)

    # ── 1. Kernel parameters ────────────────────────────────────────────────
    logger.info("➜ Writing kernel parameters...")
    if not _run(f"cat > {SYSCTL_FILE} << 'EOF'\n{SYSCTL_CONTENT}EOF", logger, verbose, "write sysctl"):
        return False
    if not _run(f"sysctl -p {SYSCTL_FILE} > /dev/null", logger, verbose, "apply sysctl"):
        return False
    logger.info("✓ Kernel parameters applied")

    # ── 2. Resource limits ───────────────────────────────────────────────────
    check = execute_local_command("grep -c '^informix' /etc/security/limits.conf || true", logger, False)
    if check['stdout'].strip() in ('', '0'):
        if not _run(f"cat >> {LIMITS_FILE} << 'EOF'\n{LIMITS_CONTENT}EOF", logger, verbose, "append limits"):
            return False
        logger.info("✓ Resource limits added")
    else:
        logger.info("⊘ Resource limits already present — skipping")

    # ── 3. Group and user ────────────────────────────────────────────────────
    for cmd, desc in [
        ("getent group informix > /dev/null 2>&1 && echo EXISTS || groupadd -g 200 informix", "create group"),
        ("id informix > /dev/null 2>&1 && echo EXISTS || useradd -u 200 -g informix -m -d /home/informix -s /bin/bash informix", "create user"),
    ]:
        result = _run(cmd, logger, verbose, desc)
        if result is False:
            return False
        if 'EXISTS' in result['stdout']:
            logger.info(f"⊘ {desc} — already exists, skipping")
        else:
            logger.info(f"✓ {desc}")

    result = execute_local_command("id informix", logger, verbose)
    if result['rc'] != 0:
        logger.error("User 'informix' not found after creation")
        return False
    logger.info(f"✓ User verified: {result['stdout'].strip()}")

    if not _run(f"echo 'informix:{password}' | chpasswd", logger, verbose, "set password"):
        return False
    logger.info("✓ Password set")

    # ── 4. Install binaries ──────────────────────────────────────────────────
    tar_path      = f"{install_tmp_dir}/{installer_filename}"
    response_file = f"{install_tmp_dir}/response.properties"
    response_content = (
        "INSTALLER_UI=SILENT\n"
        f"USER_INSTALL_DIR={install_dir}\n"
        "CHOSEN_INSTALL_FEATURE_LIST=TYPICAL\n"
        "LICENSE_ACCEPTED=TRUE\n"
        "IDS_LICENSE_TYPE=DEVELOPER\n"
        "CREATE_INFORMIX_USER=NO\n"
        "INFORMIX_USER=informix\n"
        "INFORMIX_GROUP=informix\n"
    )
    for cmd, desc in [
        (f"mkdir -p {install_tmp_dir}",                                       "mkdir install_tmp"),
        (f"cp {local_installer} {tar_path}",                                  "copy installer"),
        (f"tar -xf {tar_path} -C {install_tmp_dir}",                         "extract outer tar"),
        (f"cd {install_tmp_dir} && tar -xf {installer_filename}",            "extract inner tar"),
        (f"cat > {response_file} << 'EOF'\n{response_content}EOF",           "write response.properties"),
        (f"cd {install_tmp_dir} && ./ids_install -i silent -f {response_file}", "run silent installer"),
    ]:
        logger.info(f"➜ {desc}...")
        if not _run(cmd, logger, verbose, desc):
            return False
        logger.info(f"✓ {desc}")

    # ── 5. .bash_profile ─────────────────────────────────────────────────────
    bash_block = (
        "\n# Informix environment variables\n"
        f"export INFORMIXDIR={install_dir}\n"
        f"export INFORMIXSERVER={informix_server}\n"
        f"export ONCONFIG=onconfig.{informix_server}\n"
        f"export INFORMIXSQLHOSTS=${{INFORMIXDIR}}/etc/sqlhosts\n"
        f"export PATH=${{INFORMIXDIR}}/bin:${{PATH}}\n"
        f"export LD_LIBRARY_PATH=${{INFORMIXDIR}}/lib:${{INFORMIXDIR}}/lib/esql:${{LD_LIBRARY_PATH:-}}\n"
        "export DB_LOCALE=en_US.utf8\n"
        "export CLIENT_LOCALE=en_US.utf8\n"
    )
    check = execute_local_command(f"grep -c 'INFORMIXDIR' {bash_profile} 2>/dev/null || true", logger, False)
    if check['stdout'].strip() in ('', '0'):
        if not _run(f"cat >> {bash_profile} << 'EOF'\n{bash_block}EOF", logger, verbose, "write .bash_profile"):
            return False
        execute_local_command(f"chown informix:informix {bash_profile}", logger, verbose)
        logger.info("✓ .bash_profile configured")
    else:
        logger.info("⊘ .bash_profile already configured — skipping")

    # ── 6. onconfig ──────────────────────────────────────────────────────────
    onconfig_std = f"{install_dir}/etc/onconfig.std"
    if not _run(f"cp {onconfig_std} {onconfig_file}", logger, verbose, "copy onconfig.std"):
        return False
    sed_cmd = (
        f"sed -i"
        f" -e 's/^DBSERVERNAME.*/DBSERVERNAME  {informix_server}/'"
        f" -e 's/^SERVERNUM.*/SERVERNUM      1/'"
        f" -e 's|^ROOTPATH.*|ROOTPATH       {install_dir}/rootdbs|'"
        f" -e 's/^ROOTSIZE.*/ROOTSIZE       {rootdbs_size_kb}/'"
        f" -e 's/^ROOTNAME.*/ROOTNAME       rootdbs/'"
        f" -e 's|^MSGPATH.*|MSGPATH        {install_dir}/tmp/online.log|'"
        f" -e 's|^LTAPEDEV.*|LTAPEDEV       /dev/null|'"
        f" -e 's|^TAPEDEV.*|TAPEDEV        /dev/null|'"
        f" -e 's/^LOGFILES.*/LOGFILES       6/'"
        f" -e 's/^LOGSIZE.*/LOGSIZE        5000/'"
        f" -e 's/^BUFFERS.*/BUFFERS        5000/'"
        f" -e 's/^PAGESIZE.*/PAGESIZE       2/'"
        f" -e 's/^GL_USEGLU.*/GL_USEGLU      1/'"
        f" -e 's/^NUMCPUVPS.*/NUMCPUVPS      1/'"
        f" {onconfig_file}"
    )
    if not _run(sed_cmd, logger, verbose, "configure onconfig"):
        return False
    if not _run(
        f"sed -i '/^NETTYPE[[:space:]]\\+ipcshm/a NETTYPE                    soctcp,1,50,NET' {onconfig_file}",
        logger, verbose, "add NETTYPE soctcp"
    ):
        return False
    execute_local_command(f"chown informix:informix {onconfig_file}", logger, verbose)
    logger.info(f"✓ onconfig.{informix_server} configured")

    # ── 7. Storage ───────────────────────────────────────────────────────────
    rootdbs = f"{install_dir}/rootdbs"
    tmp_dir = f"{install_dir}/tmp"
    for cmd, desc in [
        (f"touch {rootdbs}",                                                          "touch rootdbs"),
        (f"chmod 660 {rootdbs}",                                                      "chmod rootdbs"),
        (f"chown informix:informix {rootdbs}",                                        "chown rootdbs"),
        (f"dd if=/dev/zero of={rootdbs} bs=1024 count={rootdbs_size_kb} status=none","pre-allocate rootdbs"),
        (f"mkdir -p {tmp_dir}",                                                       "mkdir tmp"),
        (f"chown informix:informix {tmp_dir}",                                        "chown tmp"),
        (f"chmod 770 {tmp_dir}",                                                      "chmod tmp"),
    ]:
        logger.info(f"➜ {desc}...")
        if not _run(cmd, logger, verbose, desc):
            return False
    logger.info(f"✓ Storage prepared")

    # ── 8. Network (sqlhosts + /etc/services) ────────────────────────────────
    sqlhosts_entry = f"{informix_server}  onsoctcp  {informix_host}  {informix_port}"
    if not _run(f"echo '{sqlhosts_entry}' > {sqlhosts}", logger, verbose, "write sqlhosts"):
        return False
    execute_local_command(f"chown informix:informix {sqlhosts}", logger, verbose)
    logger.info(f"✓ sqlhosts written")

    check = execute_local_command(f"grep -c '^{informix_server}' /etc/services || true", logger, False)
    if check['stdout'].strip() in ('', '0'):
        if not _run(f"echo '{informix_server}  {informix_port}/tcp' >> /etc/services", logger, verbose, "add /etc/services entry"):
            return False
        logger.info("✓ /etc/services entry added")
    else:
        logger.info("⊘ /etc/services entry already present — skipping")

    # ── 9. Initialize instance ───────────────────────────────────────────────
    logger.info("➜ Running oninit -i as informix user...")
    if not _run(f"su - informix -c 'export {env}; echo y | oninit -i'", logger, verbose, "oninit -i"):
        return False
    logger.info("✓ oninit -i completed")

    result = execute_local_command(f"su - informix -c 'export {env}; onstat'", logger, verbose)
    if result['rc'] != 0 or 'On-Line' not in result['stdout']:
        logger.error("Informix is not On-Line after oninit -i")
        if result['stdout']:
            logger.error(f"onstat output: {result['stdout'].strip()}")
        return False
    logger.info("✓ Informix is On-Line")

    if not _run(f"su - informix -c 'export {env}; onmode -ky'", logger, verbose, "onmode -ky"):
        return False
    logger.info("✓ Informix instance stopped")

    # ── 10. Firewall ─────────────────────────────────────────────────────────
    for cmd, desc in [
        (f"firewall-cmd --permanent --add-port={informix_port}/tcp",       f"open port {informix_port}/tcp"),
        (f"firewall-cmd --permanent --add-port={informix_admin_port}/tcp",  f"open port {informix_admin_port}/tcp"),
        ("firewall-cmd --reload",                                            "reload firewall"),
    ]:
        logger.info(f"➜ {desc}...")
        if not _run(cmd, logger, verbose, desc):
            return False
    logger.info(f"✓ Ports {informix_port}/tcp and {informix_admin_port}/tcp opened")

    # ── 11. Systemd service ──────────────────────────────────────────────────
    service_content = (
        "[Unit]\n"
        f"Description=IBM Informix Database Server ({informix_server})\n"
        "After=network.target remote-fs.target\n"
        "Wants=network.target\n"
        "\n"
        "[Service]\n"
        "Type=forking\n"
        "User=informix\n"
        "Group=informix\n"
        f"Environment=\"INFORMIXDIR={install_dir}\"\n"
        f"Environment=\"INFORMIXSERVER={informix_server}\"\n"
        f"Environment=\"ONCONFIG=onconfig.{informix_server}\"\n"
        f"Environment=\"INFORMIXSQLHOSTS={install_dir}/etc/sqlhosts\"\n"
        f"Environment=\"PATH={install_dir}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin\"\n"
        f"Environment=\"LD_LIBRARY_PATH={install_dir}/lib:{install_dir}/lib/esql\"\n"
        "\n"
        f"ExecStart={install_dir}/bin/oninit\n"
        f"ExecStop={install_dir}/bin/onmode -ky\n"
        "\n"
        "TimeoutStartSec=120\n"
        "TimeoutStopSec=120\n"
        "Restart=on-failure\n"
        "RestartSec=10\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )
    if not _run(f"cat > {service_file} << 'EOF'\n{service_content}EOF", logger, verbose, "write service file"):
        return False
    for cmd, desc in [
        ("systemctl daemon-reload",             "daemon-reload"),
        (f"systemctl enable {service_name}",    f"enable {service_name}"),
        (f"systemctl start {service_name}",     f"start {service_name}"),
    ]:
        logger.info(f"➜ {desc}...")
        if not _run(cmd, logger, verbose, desc):
            return False
        logger.info(f"✓ {desc}")

    # ── 12. System users ─────────────────────────────────────────────────────
    for user in ['appuser1', 'appuser2', 'adminuser1']:
        for cmd, desc in [
            (f"id {user} > /dev/null 2>&1 && echo EXISTS || useradd -M -s /sbin/nologin {user}", f"create user {user}"),
            (f"echo '{user}:{password}' | chpasswd", f"set password for {user}"),
        ]:
            result = _run(cmd, logger, verbose, desc)
            if result is False:
                return False
            if desc.startswith('create') and 'EXISTS' in result['stdout']:
                logger.info(f"⊘ User '{user}' already exists — skipping")
            else:
                logger.info(f"✓ {desc}")

    # ── 13. dbtraffic config ─────────────────────────────────────────────────
    dbtraffic_dir = "/opt/guardium_tz_bootcamp_automation/upload/guardium_notes_dbtraffic"
    dbtraffic_config = f"{dbtraffic_dir}/config/informix_raptor.yaml"
    dbtraffic_content = f"""database:
  type: informix
  host: {informix_host}
  port: {informix_port}
  server: {informix_server}
  database: sysmaster
  user: informix
  password: {password}

workload:
  duration_seconds: 3600
  think_time_ms: 250

scenario:
  name: micro_payments
  options:
    locale: en_US
    seed_customers: 100
    app_users:
      - appuser1
      - appuser2
    admin_users:
      - adminuser1
    default_password: {password}
    jdbc_jar: {jdbc_jars}
"""
    if not _run(f"cat > {dbtraffic_config} << 'EOF'\n{dbtraffic_content}EOF", logger, verbose, "write dbtraffic informix config"):
        return False
    logger.info(f"✓ dbtraffic config written: {dbtraffic_config}")

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX DEPLOYED")
        logger.info("=" * 80)
    return True

# Made with Bob

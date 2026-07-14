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


def configure_kernel_parameters(config, logger, verbose: bool = True, **kwargs) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("CONFIGURE KERNEL PARAMETERS FOR INFORMIX")
        logger.info("=" * 80)

    logger.info(f"➜ Writing {SYSCTL_FILE}...")
    result = execute_local_command(f"cat > {SYSCTL_FILE} << 'EOF'\n{SYSCTL_CONTENT}EOF", logger, verbose)
    if result['rc'] != 0:
        logger.error(f"Failed to write {SYSCTL_FILE}: {result['stderr']}")
        return False
    logger.info(f"✓ {SYSCTL_FILE} written")

    logger.info("➜ Applying kernel parameters...")
    result = execute_local_command(f"sysctl -p {SYSCTL_FILE} > /dev/null", logger, verbose)
    if result['rc'] != 0:
        logger.error(f"Failed to apply sysctl config: {result['stderr']}")
        return False
    logger.info("✓ Kernel parameters applied")

    logger.info(f"➜ Checking informix limits in {LIMITS_FILE}...")
    check = execute_local_command("grep -c '^informix' /etc/security/limits.conf || true", logger, False)
    if check['stdout'].strip() not in ('', '0'):
        logger.info("⊘ Resource limits for 'informix' already present — skipping")
    else:
        result = execute_local_command(f"cat >> {LIMITS_FILE} << 'EOF'\n{LIMITS_CONTENT}EOF", logger, verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to append informix limits: {result['stderr']}")
            return False
        logger.info("✓ Resource limits for 'informix' added")

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ KERNEL PARAMETERS CONFIGURED")
        logger.info("=" * 80)
    return True


def create_informix_user(config, logger, verbose: bool = True, **kwargs) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("CREATE INFORMIX GROUP AND USER")
        logger.info("=" * 80)

    password = config.get_custom_variable('pwd')
    if not password:
        logger.error("Root password (pwd) not found in custom_variables")
        return False

    logger.info("➜ Creating informix group...")
    result = execute_local_command(
        "getent group informix > /dev/null 2>&1 && echo EXISTS || groupadd -g 200 informix",
        logger, verbose
    )
    if result['rc'] != 0:
        logger.error(f"Failed to create group informix: {result['stderr']}")
        return False
    if 'EXISTS' in result['stdout']:
        logger.info("⊘ Group 'informix' already exists — skipping")
    else:
        logger.info("✓ Group 'informix' created (gid 200)")

    logger.info("➜ Creating informix user...")
    result = execute_local_command(
        "id informix > /dev/null 2>&1 && echo EXISTS || useradd -u 200 -g informix -m -d /home/informix -s /bin/bash informix",
        logger, verbose
    )
    if result['rc'] != 0:
        logger.error(f"Failed to create user informix: {result['stderr']}")
        return False
    if 'EXISTS' in result['stdout']:
        logger.info("⊘ User 'informix' already exists — skipping")
    else:
        logger.info("✓ User 'informix' created (uid 200)")

    logger.info("➜ Verifying user informix exists...")
    result = execute_local_command("id informix", logger, verbose)
    if result['rc'] != 0:
        logger.error(f"User 'informix' not found after creation: {result['stderr']}")
        return False
    logger.info(f"✓ User verified: {result['stdout'].strip()}")

    logger.info("➜ Setting password for informix...")
    result = execute_local_command(f"echo 'informix:{password}' | chpasswd", logger, verbose)
    if result['rc'] != 0:
        logger.error(f"Failed to set informix password: {result['stderr']}")
        return False
    logger.info("✓ Password set")

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX USER CREATED")
        logger.info("=" * 80)
    return True


def configure_informix_bash_profile(
    config, logger, verbose: bool = True,
    install_dir: str = "/opt/ibm/informix",
    informix_server: str = "ifxserver",
    **kwargs
) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("CONFIGURE INFORMIX BASH_PROFILE")
        logger.info("=" * 80)

    bash_profile = "/home/informix/.bash_profile"
    bash_profile_block = (
        "\n# Informix environment variables\n"
        f"export INFORMIXDIR={install_dir}\n"
        f"export INFORMIXSERVER={informix_server}\n"
        f"export ONCONFIG=onconfig.{informix_server}\n"
        f"export INFORMIXSQLHOSTS=${{INFORMIXDIR}}/etc/sqlhosts\n"
        f"export PATH=${{INFORMIXDIR}}/bin:${{PATH}}\n"
        f"export LD_LIBRARY_PATH=${{INFORMIXDIR}}/lib:${{INFORMIXDIR}}/lib/esql:${{LD_LIBRARY_PATH:-}}\n"
        "export DB_LOCALE=en_US.819\n"
        "export CLIENT_LOCALE=en_US.819\n"
    )

    logger.info(f"➜ Checking {bash_profile}...")
    check = execute_local_command(
        f"grep -c 'INFORMIXDIR' {bash_profile} 2>/dev/null || true",
        logger, False
    )
    if check['stdout'].strip() not in ('', '0'):
        logger.info("⊘ INFORMIXDIR already present in .bash_profile — skipping")
    else:
        result = execute_local_command(
            f"cat >> {bash_profile} << 'EOF'\n{bash_profile_block}EOF",
            logger, verbose
        )
        if result['rc'] != 0:
            logger.error(f"Failed to write .bash_profile: {result['stderr']}")
            return False
        result = execute_local_command(f"chown informix:informix {bash_profile}", logger, verbose)
        if result['rc'] != 0:
            logger.warning(f"Failed to chown .bash_profile: {result['stderr']}")
        logger.info("✓ .bash_profile configured")

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX BASH_PROFILE CONFIGURED")
        logger.info("=" * 80)
    return True


def configure_informix_onconfig(
    config, logger, verbose: bool = True,
    install_dir: str = "/opt/ibm/informix",
    informix_server: str = "ifxserver",
    rootdbs_size_kb: int = 200000,
    **kwargs
) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("CONFIGURE INFORMIX ONCONFIG")
        logger.info("=" * 80)

    onconfig_std = f"{install_dir}/etc/onconfig.std"
    onconfig_file = f"{install_dir}/etc/onconfig.{informix_server}"

    logger.info(f"➜ Copying {onconfig_std} → {onconfig_file}...")
    result = execute_local_command(f"cp {onconfig_std} {onconfig_file}", logger, verbose)
    if result['rc'] != 0:
        logger.error(f"Failed to copy onconfig.std: {result['stderr']}")
        return False
    logger.info("✓ onconfig.std copied")

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

    logger.info(f"➜ Applying sed substitutions to {onconfig_file}...")
    result = execute_local_command(sed_cmd, logger, verbose)
    if result['rc'] != 0:
        logger.error(f"Failed to configure onconfig: {result['stderr']}")
        return False

    logger.info(f"➜ Adding NETTYPE soctcp entry after ipcshm line...")
    result = execute_local_command(
        f"sed -i '/^NETTYPE[[:space:]]\\+ipcshm/a NETTYPE                    soctcp,1,50,NET' {onconfig_file}",
        logger, verbose
    )
    if result['rc'] != 0:
        logger.error(f"Failed to add NETTYPE soctcp: {result['stderr']}")
        return False
    logger.info("✓ NETTYPE soctcp,1,50,NET added")

    result = execute_local_command(f"chown informix:informix {onconfig_file}", logger, verbose)
    if result['rc'] != 0:
        logger.warning(f"Failed to chown onconfig: {result['stderr']}")

    logger.info(f"✓ {onconfig_file} configured")

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX ONCONFIG CONFIGURED")
        logger.info("=" * 80)
    return True


def prepare_informix_storage(
    config, logger, verbose: bool = True,
    install_dir: str = "/opt/ibm/informix",
    rootdbs_size_kb: int = 200000,
    **kwargs
) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("PREPARE INFORMIX STORAGE")
        logger.info("=" * 80)

    rootdbs = f"{install_dir}/rootdbs"
    tmp_dir = f"{install_dir}/tmp"

    for cmd, desc in [
        (f"touch {rootdbs}",                                                        "touch rootdbs"),
        (f"chmod 660 {rootdbs}",                                                    "chmod rootdbs"),
        (f"chown informix:informix {rootdbs}",                                      "chown rootdbs"),
        (f"dd if=/dev/zero of={rootdbs} bs=1024 count={rootdbs_size_kb} status=none", "pre-allocate rootdbs"),
        (f"mkdir -p {tmp_dir}",                                                     "mkdir tmp"),
        (f"chown informix:informix {tmp_dir}",                                      "chown tmp"),
        (f"chmod 770 {tmp_dir}",                                                    "chmod tmp"),
    ]:
        logger.info(f"➜ {desc}...")
        result = execute_local_command(cmd, logger, verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to {desc}: {result['stderr']}")
            return False
    logger.info(f"✓ rootdbs ({rootdbs_size_kb} KB) and tmp directory prepared")

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX STORAGE PREPARED")
        logger.info("=" * 80)
    return True


def configure_informix_network(
    config, logger, verbose: bool = True,
    install_dir: str = "/opt/ibm/informix",
    informix_server: str = "ifxserver",
    informix_host: str = "raptor.demo.guardium",
    informix_port: int = 9088,
    **kwargs
) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("CONFIGURE INFORMIX NETWORK (sqlhosts + /etc/services)")
        logger.info("=" * 80)

    sqlhosts = f"{install_dir}/etc/sqlhosts"
    sqlhosts_entry = f"{informix_server}  onsoctcp  {informix_host}  {informix_port}"
    services_entry = f"{informix_server}  {informix_port}/tcp"

    logger.info(f"➜ Writing {sqlhosts}...")
    result = execute_local_command(
        f"echo '{sqlhosts_entry}' > {sqlhosts}",
        logger, verbose
    )
    if result['rc'] != 0:
        logger.error(f"Failed to write sqlhosts: {result['stderr']}")
        return False
    logger.info(f"✓ sqlhosts written: {sqlhosts_entry}")

    logger.info("➜ Checking /etc/services for existing entry...")
    check = execute_local_command(
        f"grep -c '^{informix_server}' /etc/services || true",
        logger, False
    )
    if check['stdout'].strip() not in ('', '0'):
        logger.info(f"⊘ /etc/services entry for '{informix_server}' already present — skipping")
    else:
        result = execute_local_command(
            f"echo '{services_entry}' >> /etc/services",
            logger, verbose
        )
        if result['rc'] != 0:
            logger.error(f"Failed to add /etc/services entry: {result['stderr']}")
            return False
        logger.info(f"✓ /etc/services entry added: {services_entry}")

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX NETWORK CONFIGURED")
        logger.info("=" * 80)
    return True


def install_informix_binaries(
    config, logger, verbose: bool = True,
    installer_filename: str = "ibm.server.15.0.1.0.Linux.64.x86_64.tar",
    installer_source_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/informix",
    install_tmp_dir: str = "/opt/informix_tmp",
    install_dir: str = "/opt/ibm/informix",
    **kwargs
) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("INSTALL INFORMIX BINARIES")
        logger.info("=" * 80)

    import os
    local_path = f"{installer_source_dir}/{installer_filename}"
    if not os.path.exists(local_path):
        logger.error(f"Installer not found: {local_path}")
        return False

    tar_path = f"{install_tmp_dir}/{installer_filename}"
    response_file = f"{install_tmp_dir}/response.properties"
    response_content = (
        "# Silent (unattended) installation mode\n"
        "INSTALLER_UI=SILENT\n"
        "\n"
        "# Installation directory\n"
        f"USER_INSTALL_DIR={install_dir}\n"
        "\n"
        "# Installation type: TYPICAL | FULL | CUSTOM\n"
        "CHOSEN_INSTALL_FEATURE_LIST=TYPICAL\n"
        "\n"
        "# License acceptance — must be TRUE to proceed\n"
        "LICENSE_ACCEPTED=TRUE\n"
        "\n"
        "# Edition: DEVELOPER | INNOVATORC | WORKGROUP | ENTERPRISE\n"
        "IDS_LICENSE_TYPE=DEVELOPER\n"
        "\n"
        "# Do not create the informix OS user automatically (already created above)\n"
        "CREATE_INFORMIX_USER=NO\n"
        "INFORMIX_USER=informix\n"
        "INFORMIX_GROUP=informix\n"
    )

    for cmd, desc in [
        (f"mkdir -p {install_tmp_dir}",                                                          f"create {install_tmp_dir}"),
        (f"cp {local_path} {tar_path}",                                                          f"copy installer to {install_tmp_dir}"),
        (f"tar -xf {tar_path} -C {install_tmp_dir}",                                            "extract outer tar"),
        (f"cd {install_tmp_dir} && tar -xf {installer_filename}",                               "extract inner tar"),
        (f"cat > {response_file} << 'EOF'\n{response_content}EOF",                              "write response.properties"),
        (f"cd {install_tmp_dir} && ./ids_install -i silent -f {response_file}",                 "run silent installer"),
    ]:
        logger.info(f"➜ {desc}...")
        result = execute_local_command(cmd, logger, verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to {desc}: {result['stderr']}")
            return False
        logger.info(f"✓ {desc}")

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX BINARIES INSTALLED")
        logger.info("=" * 80)
    return True


def open_informix_firewall_ports(
    config, logger, verbose: bool = True,
    informix_port: int = 9088,
    informix_admin_port: int = 9089,
    **kwargs
) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("OPEN INFORMIX FIREWALL PORTS")
        logger.info("=" * 80)

    for cmd, desc in [
        (f"firewall-cmd --permanent --add-port={informix_port}/tcp",      f"port {informix_port}/tcp"),
        (f"firewall-cmd --permanent --add-port={informix_admin_port}/tcp", f"port {informix_admin_port}/tcp"),
        ("firewall-cmd --reload",                                           "firewall reload"),
    ]:
        logger.info(f"➜ Opening {desc}...")
        result = execute_local_command(cmd, logger, verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to open {desc}: {result['stderr']}")
            return False
    logger.info(f"✓ Ports {informix_port}/tcp and {informix_admin_port}/tcp opened")

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX FIREWALL PORTS OPENED")
        logger.info("=" * 80)
    return True


def create_informix_service(
    config, logger, verbose: bool = True,
    install_dir: str = "/opt/ibm/informix",
    informix_server: str = "ifxserver",
    **kwargs
) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("CREATE INFORMIX SYSTEMD SERVICE")
        logger.info("=" * 80)

    service_file = f"/etc/systemd/system/informix-{informix_server}.service"
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
        "\n"
        "Restart=on-failure\n"
        "RestartSec=10\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )

    logger.info(f"➜ Writing {service_file}...")
    result = execute_local_command(
        f"cat > {service_file} << 'EOF'\n{service_content}EOF",
        logger, verbose
    )
    if result['rc'] != 0:
        logger.error(f"Failed to write service file: {result['stderr']}")
        return False
    logger.info(f"✓ {service_file} written")

    logger.info("➜ Reloading systemd daemon...")
    result = execute_local_command("systemctl daemon-reload", logger, verbose)
    if result['rc'] != 0:
        logger.error(f"Failed to reload systemd: {result['stderr']}")
        return False
    logger.info("✓ systemd daemon reloaded")

    service_name = f"informix-{informix_server}.service"
    for cmd, desc in [
        (f"systemctl enable {service_name}", f"enable {service_name}"),
        (f"systemctl start {service_name}",  f"start {service_name}"),
    ]:
        logger.info(f"➜ {desc}...")
        result = execute_local_command(cmd, logger, verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to {desc}: {result['stderr']}")
            return False
        logger.info(f"✓ {desc}")

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX SYSTEMD SERVICE CREATED")
        logger.info("=" * 80)
    return True


def initialize_informix(
    config, logger, verbose: bool = True,
    install_dir: str = "/opt/ibm/informix",
    informix_server: str = "ifxserver",
    **kwargs
) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("INITIALIZE INFORMIX INSTANCE")
        logger.info("=" * 80)

    env = (
        f"INFORMIXDIR={install_dir} "
        f"INFORMIXSERVER={informix_server} "
        f"ONCONFIG=onconfig.{informix_server} "
        f"INFORMIXSQLHOSTS={install_dir}/etc/sqlhosts "
        f"PATH={install_dir}/bin:$PATH "
        f"LD_LIBRARY_PATH={install_dir}/lib:{install_dir}/lib/esql"
    )

    logger.info("➜ Running oninit -i as informix user...")
    result = execute_local_command(
        f"su - informix -c 'export {env}; oninit -i'",
        logger, verbose
    )
    if result['rc'] != 0:
        logger.error(f"oninit -i failed: {result['stderr']}")
        return False
    logger.info("✓ oninit -i completed")

    logger.info("➜ Verifying Informix is On-Line...")
    result = execute_local_command(
        f"su - informix -c 'export {env}; onstat'",
        logger, verbose
    )
    if result['rc'] != 0 or 'On-Line' not in result['stdout']:
        logger.error("Informix is not On-Line after oninit -i")
        if result['stdout']:
            logger.error(f"onstat output: {result['stdout'].strip()}")
        return False
    logger.info("✓ Informix is On-Line")

    logger.info("➜ Stopping Informix instance (onmode -ky)...")
    result = execute_local_command(
        f"su - informix -c 'export {env}; onmode -ky'",
        logger, verbose
    )
    if result['rc'] != 0:
        logger.error(f"onmode -ky failed: {result['stderr']}")
        return False
    logger.info("✓ Informix instance stopped")

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX INSTANCE INITIALIZED AND STOPPED")
        logger.info("=" * 80)
    return True

# Made with Bob

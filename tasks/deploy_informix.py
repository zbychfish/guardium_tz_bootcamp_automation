#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import ConfigLoader
from core.ssh_client import SSHClient


def informix_installation_preparation(config, logger, verbose: bool = True) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("INFORMIX INSTALLATION PREPARATION ON SAUROPOD")
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

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password,
                    port=ssh_port, timeout=60)

    if not ssh.connect():
        logger.error(f"Failed to connect to sauropod ({sauropod_ip}:{ssh_port})")
        return False

    try:
        # Step 1: Write /etc/sysctl.d/99-informix.conf and apply
        logger.info("➜ Writing /etc/sysctl.d/99-informix.conf...")
        sysctl_content = (
            "# Informix shared memory settings\n"
            "kernel.shmmax = 536870912\n"
            "kernel.shmall = 131072\n"
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
        write_cmd = f"cat > /etc/sysctl.d/99-informix.conf << 'EOF'\n{sysctl_content}EOF"
        result = ssh.execute_command(write_cmd, timeout=30, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to write sysctl config: {result['stderr']}")
            return False
        logger.info("✓ /etc/sysctl.d/99-informix.conf written")

        result = ssh.execute_command(
            "sysctl -p /etc/sysctl.d/99-informix.conf > /dev/null",
            timeout=30, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"Failed to apply sysctl config: {result['stderr']}")
            return False
        logger.info("✓ Kernel parameters applied")

        # Step 2: Add informix resource limits (idempotent)
        logger.info("➜ Checking informix limits in /etc/security/limits.conf...")
        check = ssh.execute_command(
            "grep -q '^informix' /etc/security/limits.conf",
            timeout=10, print_output=False
        )
        if check['rc'] == 0:
            logger.info("⊘ Resource limits for 'informix' already present — skipping")
        else:
            limits_block = (
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
            append_cmd = f"cat >> /etc/security/limits.conf << 'EOF'\n{limits_block}EOF"
            result = ssh.execute_command(append_cmd, timeout=30, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"Failed to append informix limits: {result['stderr']}")
                return False
            logger.info("✓ Resource limits for 'informix' added to /etc/security/limits.conf")

        # Step 3: Create group and user 'informix' (idempotent)
        logger.info("➜ Creating informix group and user...")
        for cmd, desc in [
            ("getent group informix > /dev/null 2>&1 || groupadd -g 200 informix", "group informix"),
            ("id informix > /dev/null 2>&1 || useradd -u 200 -g informix -m -d /home/informix -s /bin/bash informix", "user informix"),
            (f"echo 'informix:{root_password}' | chpasswd", "informix password"),
        ]:
            result = ssh.execute_command(cmd, timeout=30, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"Failed to configure {desc}: {result['stderr']}")
                return False
        logger.info("✓ Group and user 'informix' configured")

    except Exception as e:
        logger.error(f"✗ SSH operation failed: {e}")
        return False
    finally:
        ssh.disconnect()

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX INSTALLATION PREPARATION COMPLETED")
        logger.info("=" * 80)
    return True


def copy_and_extract_informix_on_sauropod(
    config,
    logger,
    verbose: bool = True,
    installer_filename: str = "ibm.server.15.0.1.0.Linux.64.x86_64.tar",
    installer_source_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/informix",
    remote_target_dir: str = "/opt/informix_install",
    **kwargs
) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("COPY AND EXTRACT INFORMIX INSTALLER ON SAUROPOD")
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

    import os
    local_path = os.path.join(installer_source_dir, installer_filename)
    remote_path = f"{remote_target_dir}/{installer_filename}"

    if not os.path.exists(local_path):
        logger.error(f"Installer not found: {local_path}")
        return False

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password,
                    port=ssh_port, timeout=60)

    if not ssh.connect():
        logger.error(f"Failed to connect to sauropod ({sauropod_ip}:{ssh_port})")
        return False

    try:
        logger.info(f"➜ Creating target directory {remote_target_dir}...")
        result = ssh.execute_command(f"mkdir -p {remote_target_dir}", timeout=15, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to create directory: {result['stderr']}")
            return False

        logger.info(f"➜ Uploading {installer_filename} to sauropod...")
        if not ssh.upload_file(local_path, remote_path):
            logger.error(f"Failed to upload {installer_filename}")
            return False
        logger.info("✓ Installer uploaded")

        logger.info(f"➜ Extracting {installer_filename} in {remote_target_dir}...")
        result = ssh.execute_command(
            f"tar -xf {remote_path} -C {remote_target_dir}",
            timeout=300, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"Failed to extract outer tar: {result['stderr']}")
            return False
        logger.info("✓ Outer tar extracted")

        # The outer tar contains an inner tar with the same name — extract it in-place
        inner_tar = f"{remote_target_dir}/{installer_filename}"
        logger.info(f"➜ Extracting inner tar {installer_filename} in {remote_target_dir}...")
        result = ssh.execute_command(
            f"cd {remote_target_dir} && tar -xf {inner_tar}",
            timeout=300, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"Failed to extract inner tar: {result['stderr']}")
            return False
        logger.info("✓ Inner tar extracted")

    except Exception as e:
        logger.error(f"✗ SSH operation failed: {e}")
        return False
    finally:
        ssh.disconnect()

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX INSTALLER COPIED AND EXTRACTED ON SAUROPOD")
        logger.info("=" * 80)
    return True


def install_informix_on_sauropod(
    config,
    logger,
    verbose: bool = True,
    install_dir: str = "/opt/informix",
    install_tmp_dir: str = "/opt/informix_install",
    **kwargs
) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("INSTALL INFORMIX ON SAUROPOD")
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

    response_file = f"{install_tmp_dir}/response.properties"
    response_content = (
        "# Silent (unattended) installation mode\n"
        "INSTALLER_UI=SILENT\n"
        "\n"
        "# Installation directory\n"
        f"USER_INSTALL_DIR={install_dir}\n"
        "\n"
        "# Installation type: TYPICAL includes server, client tools and JDBC\n"
        "CHOSEN_INSTALL_FEATURE_LIST=TYPICAL\n"
        "\n"
        "# License acceptance — must be TRUE to proceed\n"
        "LICENSE_ACCEPTED=TRUE\n"
        "\n"
        "# Edition: DEVELOPER (no data limits, for development/test use)\n"
        "IDS_LICENSE_TYPE=DEVELOPER\n"
        "\n"
        "# Do not create the informix OS user automatically (already created above)\n"
        "CREATE_INFORMIX_USER=NO\n"
        "INFORMIX_USER=informix\n"
        "INFORMIX_GROUP=informix\n"
    )

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password,
                    port=ssh_port, timeout=60)

    if not ssh.connect():
        logger.error(f"Failed to connect to sauropod ({sauropod_ip}:{ssh_port})")
        return False

    try:
        logger.info(f"➜ Writing response file {response_file}...")
        write_cmd = f"cat > {response_file} << 'EOF'\n{response_content}EOF"
        result = ssh.execute_command(write_cmd, timeout=30, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to write response file: {result['stderr']}")
            return False
        logger.info("✓ Response file written")

        logger.info(f"➜ Running Informix silent installer (target: {install_dir})...")
        install_cmd = f"{install_tmp_dir}/ids_install -i silent -f {response_file}"
        result = ssh.execute_command(install_cmd, timeout=600, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to install Informix: {result['stderr']}")
            return False
        logger.info("✓ Informix installed")

    except Exception as e:
        logger.error(f"✗ SSH operation failed: {e}")
        return False
    finally:
        ssh.disconnect()

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX INSTALLATION COMPLETED")
        logger.info("=" * 80)
    return True


def configure_informix_on_sauropod(
    config,
    logger,
    verbose: bool = True,
    install_dir: str = "/opt/informix",
    informix_server: str = "ifxserver",
    rootdbs_size_kb: int = 200000,
    **kwargs
) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("CONFIGURE INFORMIX ON SAUROPOD")
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

    bash_profile = "/home/informix/.bash_profile"
    onconfig_file = f"{install_dir}/etc/onconfig.{informix_server}"

    bash_profile_block = (
        "\n# Informix environment variables (added by install_informix.sh)\n"
        f"export INFORMIXDIR={install_dir}\n"
        f"export INFORMIXSERVER={informix_server}\n"
        f"export ONCONFIG=onconfig.{informix_server}\n"
        f"export INFORMIXSQLHOSTS=${{INFORMIXDIR}}/etc/sqlhosts\n"
        f"export PATH=${{INFORMIXDIR}}/bin:${{PATH}}\n"
        f"export LD_LIBRARY_PATH=${{INFORMIXDIR}}/lib:${{INFORMIXDIR}}/lib/esql:${{LD_LIBRARY_PATH:-}}\n"
        "export DB_LOCALE=en_US.819\n"
        "export CLIENT_LOCALE=en_US.819\n"
    )

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password,
                    port=ssh_port, timeout=60)

    if not ssh.connect():
        logger.error(f"Failed to connect to sauropod ({sauropod_ip}:{ssh_port})")
        return False

    try:
        # Step 1: Create .bash_profile (idempotent)
        logger.info(f"➜ Configuring {bash_profile}...")
        check = ssh.execute_command(
            f"grep -q 'INFORMIXDIR' {bash_profile} 2>/dev/null",
            timeout=10, print_output=False
        )
        if check['rc'] == 0:
            logger.info("⊘ INFORMIXDIR already present in .bash_profile — skipping")
        else:
            append_cmd = f"cat >> {bash_profile} << 'EOF'\n{bash_profile_block}EOF"
            result = ssh.execute_command(append_cmd, timeout=30, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"Failed to write .bash_profile: {result['stderr']}")
                return False
            result = ssh.execute_command(
                f"chown informix:informix {bash_profile}", timeout=15, print_output=verbose
            )
            if result['rc'] != 0:
                logger.warning(f"Failed to chown .bash_profile: {result['stderr']}")
            logger.info("✓ .bash_profile configured")

        # Step 2: Create onconfig from template
        logger.info(f"➜ Creating {onconfig_file} from onconfig.std...")
        result = ssh.execute_command(
            f"cp {install_dir}/etc/onconfig.std {onconfig_file}",
            timeout=15, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"Failed to copy onconfig.std: {result['stderr']}")
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
        result = ssh.execute_command(sed_cmd, timeout=30, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"Failed to configure onconfig: {result['stderr']}")
            return False

        result = ssh.execute_command(
            f"chown informix:informix {onconfig_file}", timeout=15, print_output=verbose
        )
        if result['rc'] != 0:
            logger.warning(f"Failed to chown onconfig: {result['stderr']}")

        logger.info(f"✓ ONCONFIG written: {onconfig_file}")

    except Exception as e:
        logger.error(f"✗ SSH operation failed: {e}")
        return False
    finally:
        ssh.disconnect()

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX CONFIGURATION COMPLETED")
        logger.info("=" * 80)
    return True


def prepare_informix_storage_on_sauropod(
    config,
    logger,
    verbose: bool = True,
    install_dir: str = "/opt/informix",
    informix_server: str = "ifxserver",
    informix_port: int = 9088,
    rootdbs_size_kb: int = 200000,
    **kwargs
) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("PREPARE INFORMIX STORAGE ON SAUROPOD")
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

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password,
                    port=ssh_port, timeout=60)
    if not ssh.connect():
        logger.error(f"Failed to connect to sauropod ({sauropod_ip}:{ssh_port})")
        return False

    try:
        # Step 1: Pre-allocate root chunk file
        logger.info(f"➜ Pre-allocating root chunk ({rootdbs_size_kb} KB)...")
        for cmd, desc in [
            (f"touch {install_dir}/rootdbs",                                                         "touch rootdbs"),
            (f"chown informix:informix {install_dir}/rootdbs",                                       "chown rootdbs"),
            (f"chmod 660 {install_dir}/rootdbs",                                                     "chmod rootdbs"),
            (f"dd if=/dev/zero of={install_dir}/rootdbs bs=1024 count={rootdbs_size_kb} status=none","dd rootdbs"),
        ]:
            result = ssh.execute_command(cmd, timeout=120, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"Failed to {desc}: {result['stderr']}")
                return False
        logger.info(f"✓ Root chunk created: {install_dir}/rootdbs")

        # Step 2: Create message log directory
        logger.info(f"➜ Creating message log directory {install_dir}/tmp...")
        for cmd, desc in [
            (f"mkdir -p {install_dir}/tmp",                  "mkdir tmp"),
            (f"chown informix:informix {install_dir}/tmp",   "chown tmp"),
            (f"chmod 770 {install_dir}/tmp",                 "chmod tmp"),
        ]:
            result = ssh.execute_command(cmd, timeout=15, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"Failed to {desc}: {result['stderr']}")
                return False
        logger.info(f"✓ Message log directory created: {install_dir}/tmp")

        # Step 3: Configure sqlhosts (idempotent)
        sqlhosts = f"{install_dir}/etc/sqlhosts"
        logger.info(f"➜ Configuring {sqlhosts}...")
        check = ssh.execute_command(
            f"grep -q '^{informix_server}' {sqlhosts} 2>/dev/null",
            timeout=10, print_output=False
        )
        if check['rc'] == 0:
            logger.info(f"⊘ sqlhosts entry for '{informix_server}' already present — skipping")
        else:
            result = ssh.execute_command(
                f"echo '{informix_server}  onsoctcp  localhost  {informix_port}' >> {sqlhosts}",
                timeout=15, print_output=verbose
            )
            if result['rc'] != 0:
                logger.error(f"Failed to add sqlhosts entry: {result['stderr']}")
                return False
            logger.info(f"✓ sqlhosts entry added: {informix_server} -> localhost:{informix_port}")

        # Step 4: Register port in /etc/services (idempotent)
        logger.info(f"➜ Registering port in /etc/services...")
        check = ssh.execute_command(
            f"grep -q '^{informix_server}' /etc/services",
            timeout=10, print_output=False
        )
        if check['rc'] == 0:
            logger.info(f"⊘ /etc/services entry for '{informix_server}' already present — skipping")
        else:
            result = ssh.execute_command(
                f"echo '{informix_server}  {informix_port}/tcp' >> /etc/services",
                timeout=15, print_output=verbose
            )
            if result['rc'] != 0:
                logger.error(f"Failed to add /etc/services entry: {result['stderr']}")
                return False
            logger.info(f"✓ /etc/services entry added for {informix_server}")

    except Exception as e:
        logger.error(f"✗ SSH operation failed: {e}")
        return False
    finally:
        ssh.disconnect()

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX STORAGE PREPARATION COMPLETED")
        logger.info("=" * 80)
    return True


def initialize_informix_on_sauropod(
    config,
    logger,
    verbose: bool = True,
    install_dir: str = "/opt/informix",
    informix_server: str = "ifxserver",
    timeout: int = 120,
    **kwargs
) -> bool:
    import time

    if verbose:
        logger.info("=" * 80)
        logger.info("INITIALIZE INFORMIX DATABASE ON SAUROPOD")
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

    env_exports = (
        f"export INFORMIXDIR={install_dir}; "
        f"export INFORMIXSERVER={informix_server}; "
        f"export ONCONFIG=onconfig.{informix_server}; "
        f"export INFORMIXSQLHOSTS={install_dir}/etc/sqlhosts; "
        f"export PATH={install_dir}/bin:$PATH; "
        f"export LD_LIBRARY_PATH={install_dir}/lib:{install_dir}/lib/esql"
    )

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password,
                    port=ssh_port, timeout=60)
    if not ssh.connect():
        logger.error(f"Failed to connect to sauropod ({sauropod_ip}:{ssh_port})")
        return False

    try:
        # Step 1: oninit -i (destructive — initialises root chunk)
        logger.info("➜ Running oninit -i to initialise Informix database...")
        result = ssh.execute_command(
            f'su - informix -c "{env_exports}; oninit -i"',
            timeout=120, print_output=verbose
        )
        if result['rc'] != 0:
            logger.error(f"oninit -i failed: {result['stderr']}")
            return False
        logger.info("✓ oninit -i completed")

        # Step 2: Poll until On-Line (timeout seconds, 5s interval)
        logger.info(f"➜ Waiting for Informix to come On-Line (timeout: {timeout}s)...")
        elapsed = 0
        online_check = f'su - informix -c "{env_exports}; onstat - 2>/dev/null | grep -q \'On-Line\'"'
        while elapsed < timeout:
            result = ssh.execute_command(online_check, timeout=15, print_output=False)
            if result['rc'] == 0:
                logger.info(f"✓ Informix is On-Line (after {elapsed}s)")
                break
            logger.info(f"  Still waiting... ({elapsed}s)")
            time.sleep(5)
            elapsed += 5
        else:
            logger.error(f"Timeout ({timeout}s) waiting for Informix to come On-Line")
            logger.error(f"Check {install_dir}/tmp/online.log on sauropod")
            return False

    except Exception as e:
        logger.error(f"✗ SSH operation failed: {e}")
        return False
    finally:
        ssh.disconnect()

    if verbose:
        logger.info("=" * 80)
        logger.info("✓ INFORMIX DATABASE INITIALIZED AND ON-LINE")
        logger.info("=" * 80)
    return True

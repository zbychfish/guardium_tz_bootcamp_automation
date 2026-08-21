#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import execute_commands, execute_local_command, ConfigLoader, write_file, dnf_install


def _header(logger, title: str):
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)


def _cmds(commands, logger, verbose, desc: str) -> bool:
    if not execute_commands(commands, logger, verbose):
        logger.error(f"✗ {desc} failed")
        return False
    return True


def deploy_db2_on_raptor(config, logger, verbose: bool = True, **kwargs) -> bool:
    _header(logger, "Installing Db2 prerequisites on raptor")

    password = config.get_custom_variable('pwd')
    if not password:
        logger.error("✗ pwd not found in custom_variables")
        return False

    db2_lic_b64 = config.get_custom_variable('db2_lic')
    if db2_lic_b64:
        lic_file_path = "/opt/guardium_tz_bootcamp_automation/upload/source_files/db2/db2.lic"
        logger.info(f"  ➜ base64 decode db2_lic → {lic_file_path}")
        try:
            db2_lic_content = base64.b64decode(db2_lic_b64)
            with open(lic_file_path, 'wb') as f:
                f.write(db2_lic_content)
            logger.info(f"  ✓ DB2 license saved to {lic_file_path}")
        except Exception as e:
            logger.error(f"✗ Failed to decode and save DB2 license: {e}")
            return False
    else:
        logger.warning("  DB2 license (db2_lic) not found in custom_variables")

    logger.info("  ➜ groupadd db2iadm1/db2fadm1 + useradd db2inst1/db2fenc1 + dnf prereqs + sysctl + tar")
    if not dnf_install("libaio numactl ksh libgcc libstdc++ perl pam libibverbs patch NetworkManager-config-server pam.i686 libstdc++.i686", logger):
        return False
    commands = [
        "groupadd db2iadm1",
        "groupadd db2fadm1",
        f"useradd -g db2iadm1 -m -p $(openssl passwd -1 '{password}') db2inst1",
        f"useradd -g db2fadm1 -m -p $(openssl passwd -1 '{password}') db2fenc1",
        'sysctl -w kernel.sem="250 64000 100 4096"',
        "sysctl -w kernel.shmmni=8192",
        "sysctl -w kernel.shmmax=1073741824",
        "sysctl -w kernel.shmall=262144",
        "echo 'db2inst1 soft nofile 65536' >> /etc/security/limits.conf",
        "echo 'db2inst1 hard nofile 65536' >> /etc/security/limits.conf",
        "echo 'db2inst1 soft nproc 65536' >> /etc/security/limits.conf",
        "echo 'db2inst1 hard nproc 65536' >> /etc/security/limits.conf",
        "tar -xzf /opt/guardium_tz_bootcamp_automation/upload/source_files/db2/v11.5.9_linuxx64_universal_fixpack.tar.gz -C /opt/guardium_tz_bootcamp_automation/upload/source_files/db2",
    ]
    if not _cmds(commands, logger, verbose, "Db2 prerequisites installation"):
        return False
    logger.info("  ✓ Db2 groups, users and prerequisites installed")

    rsp_file_path = "/opt/guardium_tz_bootcamp_automation/upload/source_files/db2/db2inst1.rsp"
    logger.info(f"  ➜ write response file → {rsp_file_path}")
    rsp_content = f"""PROD                      = DB2_SERVER_EDITION
FILE                      = /opt/ibm/db2/V11.5
LIC_AGREEMENT             = ACCEPT         ** ACCEPT or DECLINE
*INTERACTIVE              = NONE            ** NONE, YES, MACHINE
INSTALL_TYPE              = TYPICAL         ** TYPICAL, COMPACT, CUSTOM
COMP                     = DB2_SAMPLE_DATABASE                 ** Sample database source
INSTANCE                  = DB2_INST        ** char(8)  no spaces
DB2_INST.NAME             = db2inst1        ** char(8)  no spaces, no upper case letters
DB2_INST.GROUP_NAME       = db2iadm1        ** char(30) no spaces
DB2_INST.HOME_DIRECTORY   =                 ** char(64) no spaces. Valid for root installation only
DB2_INST.PASSWORD         = {password} ** Valid for root installation only
*DB2_INST.TYPE            = ESE             ** DSF ESE WSE STANDALONE CLIENT
DB2_INST.AUTOSTART        = YES             ** YES or NO
DB2_INST.START_DURING_INSTALL = YES         ** YES or NO. Default is YES.
*DB2_INST.SVCENAME        = db2c_db2inst1   ** BLANK or char(14). Reserved for root installation only
*DB2_INST.PORT_NUMBER     = 25000           ** 1024 - 65535, Reserved for root installation only
*DB2_INST.DB2CF_PORT_NUMBER = 56001         ** 1024 - 65535.
*DB2_INST.DB2CF_MGMT_PORT_NUMBER = 56000    ** 1024 - 65535.
DB2_INST.FENCED_USERNAME  = db2sdfe1        ** char(8)  no spaces, no upper case letters
DB2_INST.FENCED_GROUP_NAME = db2fsdm1       ** char(30)  no spaces
DB2_INST.FENCED_PASSWORD = {password}                ** char(8)

** Database Settings
** -----------------
*DATABASE                 =                 ** databas1: char(8) no spaces - this is the prefix for this DB set
*databas1.DATABASE_NAME   =                 ** favorateDB: char(8) no spaces - this is the real database
*databas1.INSTANCE        =                 ** db2inst1: char(8)  no spaces - one value of INSTANCE keyword
*databas1.ALIAS           =                 ** alias of databas1: char(8) no spaces and can not start with SYS, DBM or IBM
*databas1.LOCATION        =                 ** local, remote, LOCAL or REMOTE; For client only product use remote or REMOTE
*databas1.SYSTEM_NAME     =                 ** some remote host char(64) no spaces: for LOCATION=remote only
*databas1.AUTHENTICATION  =                 ** CLIENT, SERVER, SERVER_ENCRYPT: optional
*databas1.PATH            =                 ** the directory for the database: optional
*databas1.SVCENAME        =                 ** service1: for remote LOCATION only
*databas1.USERNAME        =                 ** db2user: char(8)  no spaces
*databas1.PASSWORD        =                 ** db2pwd: char(8)  no spaces

*INSTALL_ENCRYPTION       = YES             ** YES or NO.Valid for root installation only.
"""
    try:
        write_file(rsp_file_path, rsp_content)
        logger.info(f"  ✓ Response file created: {rsp_file_path}")
    except Exception as e:
        logger.error(f"✗ Failed to create Db2 response file: {e}")
        return False

    _header(logger, "DB2 silent installation (15-30 min)")

    install_cmd = f"cd /opt/guardium_tz_bootcamp_automation/upload/source_files/db2/universal && ./db2setup -r {rsp_file_path} -f sysreq"
    logger.info(f"  ➜ db2setup -r {rsp_file_path} -f sysreq")
    result = execute_local_command(install_cmd, logger, verbose)

    if result['rc'] not in [0, 4]:
        logger.error(f"✗ DB2 silent installation failed (rc={result['rc']})")
        if result['stderr']:
            logger.error(f"  {result['stderr']}")
        return False

    if result['rc'] == 4:
        logger.info("  ⚠ DB2 installation completed with warnings")
    else:
        logger.info("  ✓ DB2 installation completed")

    _header(logger, "Creating sample database")
    logger.info("  ➜ su - db2inst1 -c 'db2sampl'")
    if not _cmds(["su - db2inst1 -c 'db2sampl'"], logger, verbose, "create sample database"):
        return False
    logger.info("  ✓ Sample database created")

    if db2_lic_b64:
        _header(logger, "Installing DB2 license")
        logger.info("  ➜ db2licm -a db2.lic + db2licm -r db2aese")
        if not _cmds([
            "su - db2inst1 -c 'db2licm -a /opt/guardium_tz_bootcamp_automation/upload/source_files/db2/db2.lic'",
            "su - db2inst1 -c 'db2licm -r db2aese'",
        ], logger, verbose, "install DB2 license"):
            return False
        logger.info("  ✓ DB2 license installed")

    _header(logger, "Configuring DB2 instance memory")
    logger.info("  ➜ db2 update dbm cfg INSTANCE_MEMORY 50")
    if not _cmds(["su - db2inst1 -c 'db2 update dbm cfg using INSTANCE_MEMORY 50'"],
                 logger, verbose, "configure DB2 instance memory"):
        return False
    logger.info("  ✓ DB2 instance memory configured")

    _header(logger, "Configuring remote access to DB2")
    logger.info("  ➜ catalog tcpip node mynode 127.0.0.1:25010 + catalog database sample")
    if not _cmds([
        'su - db2inst1 -c \'db2 "catalog tcpip node mynode remote 127.0.0.1 server 25010"\'',
        'su - db2inst1 -c \'db2 "catalog database sample as mysample at node mynode"\'',
    ], logger, verbose, "configure remote access to DB2"):
        return False
    logger.info("  ✓ Remote access configured")

    _header(logger, "Cleaning up installation files")
    logger.info("  ➜ rm db2.lic + rm -rf universal/")
    execute_commands([
        "rm -f /opt/guardium_tz_bootcamp_automation/upload/source_files/db2/db2.lic",
        "rm -rf /opt/guardium_tz_bootcamp_automation/upload/source_files/db2/universal",
    ], logger, verbose)
    logger.info("  ✓ Installation files cleaned up")

    logger.info("✓ Db2 deployment completed")
    return True


# Made with Bob

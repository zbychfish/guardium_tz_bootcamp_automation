#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import execute_commands, execute_local_command, ConfigLoader, write_file


def deploy_db2_on_raptor(config, logger, verbose: bool = True) -> bool:
    logger.info("=" * 80)
    logger.info("Installing Db2 prerequisites on raptor")
    logger.info("=" * 80)

    password = config.get_custom_variable('pwd')

    if not password:
        logger.error("Password (pwd) not found in custom_variables")
        return False

    db2_lic_b64 = config.get_custom_variable('db2_lic')

    if db2_lic_b64:
        logger.info("Decoding and saving DB2 license from custom_variables")
        try:
            db2_lic_content = base64.b64decode(db2_lic_b64)
            logger.info("✓ DB2 license decoded successfully")
            lic_file_path = "/opt/guardium_tz_bootcamp_automation/upload/source_files/db2/db2.lic"
            with open(lic_file_path, 'wb') as f:
                f.write(db2_lic_content)
            logger.info(f"✓ DB2 license file saved to: {lic_file_path}")
        except Exception as e:
            logger.error(f"Failed to decode and save DB2 license: {e}")
            return False
    else:
        logger.warning("DB2 license (db2_lic) not found in custom_variables")

    commands = [
        "groupadd db2iadm1",
        "groupadd db2fadm1",
        f"useradd -g db2iadm1 -m -p $(openssl passwd -1 '{password}') db2inst1",
        f"useradd -g db2fadm1 -m -p $(openssl passwd -1 '{password}') db2fenc1",
        "dnf install -y libaio numactl ksh libgcc libstdc++ perl pam libibverbs patch NetworkManager-config-server pam.i686 libstdc++.i686",
        'sysctl -w kernel.sem="250 64000 100 4096"',
        "sysctl -w kernel.shmmni=8192",
        "sysctl -w kernel.shmmax=1073741824",
        "sysctl -w kernel.shmall=262144",
        "echo 'db2inst1 soft nofile 65536' >> /etc/security/limits.conf",
        "echo 'db2inst1 hard nofile 65536' >> /etc/security/limits.conf",
        "echo 'db2inst1 soft nproc 65536' >> /etc/security/limits.conf",
        "echo 'db2inst1 hard nproc 65536' >> /etc/security/limits.conf",
        "tar -xzf /opt/guardium_tz_bootcamp_automation/upload/source_files/db2/v11.5.9_linuxx64_universal_fixpack.tar.gz -C /opt/guardium_tz_bootcamp_automation/upload/source_files/db2"
    ]

    if not execute_commands(commands, logger):
        logger.error("Db2 prerequisites installation failed")
        return False

    logger.info("✓ Db2 prerequisites installed successfully")

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
"""

    rsp_file_path = "/opt/guardium_tz_bootcamp_automation/upload/source_files/db2/db2inst1.rsp"

    try:
        write_file(rsp_file_path, rsp_content)
        logger.info(f"✓ Db2 response file created: {rsp_file_path}")
    except Exception as e:
        logger.error(f"Failed to create Db2 response file: {e}")
        return False

    logger.info("Running DB2 silent installation (this may take 15-30 minutes)")
    install_cmd = f"cd /opt/guardium_tz_bootcamp_automation/upload/source_files/db2/universal && ./db2setup -r {rsp_file_path} -f sysreq"
    result = execute_local_command(install_cmd, logger)
    logger.info(f"DB2 installation exit code: {result['rc']}")

    if result['rc'] not in [0, 4]:
        logger.error(f"DB2 silent installation failed with exit code {result['rc']}")
        if result['stderr']:
            logger.error(f"Error output: {result['stderr']}")
        return False

    if result['rc'] == 4:
        logger.info("⚠ DB2 installation completed with warnings (exit code 4)")
    else:
        logger.info("✓ DB2 installation completed successfully")

    if not execute_commands(["su - db2inst1 -c 'db2sampl'"], logger):
        logger.error("Failed to create sample database")
        return False
    logger.info("✓ Sample database created successfully")

    if db2_lic_b64:
        license_commands = [
            "su - db2inst1 -c 'db2licm -a /opt/guardium_tz_bootcamp_automation/upload/source_files/db2/db2.lic'",
            "su - db2inst1 -c 'db2licm -r db2aese'"
        ]
        if not execute_commands(license_commands, logger):
            logger.error("Failed to install DB2 license")
            return False
        logger.info("✓ DB2 license installed successfully")

    if not execute_commands(["su - db2inst1 -c 'db2 update dbm cfg using INSTANCE_MEMORY 50'"], logger):
        logger.error("Failed to configure DB2 instance memory")
        return False
    logger.info("✓ DB2 instance memory configured successfully")

    remote_access_commands = [
        'su - db2inst1 -c \'db2 "catalog tcpip node mynode remote 127.0.0.1 server 25010"\'',
        'su - db2inst1 -c \'db2 "catalog database sample as mysample at node mynode"\''
    ]
    if not execute_commands(remote_access_commands, logger):
        logger.error("Failed to configure remote access to DB2 database")
        return False
    logger.info("✓ Remote access to DB2 database configured successfully")

    cleanup_commands = [
        "rm -f /opt/guardium_tz_bootcamp_automation/upload/source_files/db2/db2.lic",
        "rm -rf /opt/guardium_tz_bootcamp_automation/upload/source_files/db2/universal"
    ]
    if not execute_commands(cleanup_commands, logger):
        logger.warning("Failed to cleanup some installation files")
    else:
        logger.info("✓ Installation files cleaned up")

    return True


# Made with Bob

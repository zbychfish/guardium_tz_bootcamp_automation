#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import execute_commands, execute_local_command, ConfigLoader, write_file


def deploy_db2_on_raptor(logger, verbose: bool = True) -> bool:
    if verbose:
        logger.info("=" * 80)
        logger.info("Installing Db2 prerequisites on raptor")
        logger.info("=" * 80)
    
    config = ConfigLoader("config/config.yaml", "/root/machines_info.json")
    password = config.get_custom_variable('pwd')
    
    if not password:
        logger.error("Password (pwd) not found in custom_variables")
        return False
    
    # Decode and save DB2 license file
    db2_lic_b64 = config.get_custom_variable('db2_lic')
    
    if db2_lic_b64:
        if verbose:
            logger.info("Decoding and saving DB2 license from custom_variables")
        
        try:
            # Decode base64 license
            db2_lic_content = base64.b64decode(db2_lic_b64)
            if verbose:
                logger.info("✓ DB2 license decoded successfully")
            
            # Save to file immediately
            lic_file_path = "/opt/guardium_tz_bootcamp_automation/upload/source_files/db2/db2.lic"
            
            with open(lic_file_path, 'wb') as f:
                f.write(db2_lic_content)
            
            if verbose:
                logger.info(f"✓ DB2 license file saved to: {lic_file_path}")
        except Exception as e:
            logger.error(f"Failed to decode and save DB2 license: {e}")
            return False
    else:
        if verbose:
            logger.warning("DB2 license (db2_lic) not found in custom_variables")
    
    if verbose:
        logger.info("Creating Db2 groups and users")
  
    commands = [
        "groupadd db2iadm1",
        "groupadd db2fadm1",
        f"useradd -g db2iadm1 -m -p $(openssl passwd -1 '{password}') db2inst1",
        f"useradd -g db2fadm1 -m -p $(openssl passwd -1 '{password}') db2fenc1",
        "dnf install -y libaio numactl ksh libgcc libstdc++ perl pam libibverbs patch NetworkManager-config-server pam.i686 libstdc++.i686",
        'sysctl -w kernel.sem="250 64000 100 4096"',
        "sysctl -w kernel.shmmni=8192",
        "sysctl -w kernel.shmmax=68719476736",
        "sysctl -w kernel.shmall=16777216",
        "echo 'db2inst1 soft nofile 65536' >> /etc/security/limits.conf",
        "echo 'db2inst1 hard nofile 65536' >> /etc/security/limits.conf",
        "echo 'db2inst1 soft nproc 65536' >> /etc/security/limits.conf",
        "echo 'db2inst1 hard nproc 65536' >> /etc/security/limits.conf",
        "tar -xzf /opt/guardium_tz_bootcamp_automation/upload/source_files/db2/v11.5.9_linuxx64_universal_fixpack.tar.gz -C /opt/guardium_tz_bootcamp_automation/upload/source_files/db2"
    ]
    
    if not execute_commands(commands, logger, verbose):
        logger.error("Db2 prerequisites installation failed")
        return False
    
    if verbose:
        logger.info("✓ Db2 groups and users created")
        logger.info("✓ Db2 prerequisites installed successfully")
    
    if verbose:
        logger.info("Creating Db2 response file")
    
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
    
    rsp_file_path = "/opt/guardium_tz_bootcamp_automation/upload/source_files/db2/db2inst1.rsp"
    
    try:
        write_file(rsp_file_path, rsp_content)
        if verbose:
            logger.info(f"✓ Db2 response file created: {rsp_file_path}")
    except Exception as e:
        logger.error(f"Failed to create Db2 response file: {e}")
        return False
    
    if verbose:
        logger.info("=" * 80)
        logger.info("Running DB2 silent installation (this may take 15-30 minutes)")
        logger.info("=" * 80)
    
    install_cmd = f"cd /opt/guardium_tz_bootcamp_automation/upload/source_files/db2/universal && ./db2setup -r {rsp_file_path} -f sysreq"
    
    result = execute_local_command(install_cmd, logger, verbose)
    
    if verbose:
        logger.info(f"DB2 installation exit code: {result['rc']}")
    
    if result['rc'] not in [0, 4]:
        logger.error(f"DB2 silent installation failed with exit code {result['rc']}")
        if result['stderr']:
            logger.error(f"Error output: {result['stderr']}")
        return False
    
    if result['rc'] == 4 and verbose:
        logger.info("⚠ DB2 installation completed with warnings (exit code 4)")
    elif verbose:
        logger.info("✓ DB2 installation completed successfully")
    
    if verbose:
        logger.info("=" * 80)
        logger.info("Creating sample database with db2sampl")
        logger.info("=" * 80)
    
    sample_db_cmd = "su - db2inst1 -c 'db2sampl'"
    
    if not execute_commands([sample_db_cmd], logger, verbose):
        logger.error("Failed to create sample database")
        return False
    
    if verbose:
        logger.info("✓ Sample database created successfully")
    
    # Install DB2 license if it was saved
    if db2_lic_b64:
        if verbose:
            logger.info("=" * 80)
            logger.info("Installing DB2 license")
            logger.info("=" * 80)
        
        license_commands = [
            "su - db2inst1 -c 'db2licm -a /opt/guardium_tz_bootcamp_automation/upload/source_files/db2/db2.lic'",
            "su - db2inst1 -c 'db2licm -r db2aese'"
        ]
        
        if not execute_commands(license_commands, logger, verbose):
            logger.error("Failed to install DB2 license")
            return False
        
        if verbose:
            logger.info("✓ DB2 license installed successfully")
    
    # Cleanup installation files
    if verbose:
        logger.info("=" * 80)
        logger.info("Cleaning up installation files")
        logger.info("=" * 80)
    
    cleanup_commands = [
        "rm -f /opt/guardium_tz_bootcamp_automation/upload/source_files/db2/db2.lic",
        "rm -rf /opt/guardium_tz_bootcamp_automation/upload/source_files/db2/universal"
    ]
    
    if not execute_commands(cleanup_commands, logger, verbose):
        logger.warning("Failed to cleanup some installation files")
    elif verbose:
        logger.info("✓ Installation files cleaned up")
    
    if verbose:
        logger.info("=" * 80)
    
    return True


# Made with Bob

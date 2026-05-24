#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Oracle Deployment Task
Handles Oracle installation and configuration on remote machine (sauropod)
"""

import sys
from pathlib import Path

# Add core modules to path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import ConfigLoader
from core.ssh_client import SSHClient


def deploy_oracle_on_sauropod(config: ConfigLoader, logger, verbose: bool = True) -> bool:
    """
    Deploy Oracle Database 21c on remote machine (sauropod).
    
    This function:
    1. Connects to sauropod machine via SSH
    2. Downloads Oracle preinstall package
    3. Installs compat-openssl10 dependency
    4. Installs Oracle preinstall package
    
    Args:
        config: ConfigLoader instance with machine information
        logger: Logger instance
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    if verbose:
        logger.info("=" * 80)
        logger.info("Oracle Database 21c deployment on sauropod")
        logger.info("=" * 80)
    
    # Get sauropod machine IP (use private IP for internal communication)
    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Could not find sauropod machine in configuration")
        return False
    
    # Get SSH configuration
    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')
    
    # Get root password from custom_variables
    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("Root password (pwd) not found in custom_variables")
        return False
    
    if verbose:
        logger.info(f"Connecting to sauropod at {sauropod_ip}:{ssh_port}")
    
    try:
        # Connect to sauropod
        with SSHClient(
            host=sauropod_ip,
            username=ssh_username,
            password=root_password,
            port=ssh_port,
            timeout=60
        ) as ssh:
            
            if verbose:
                logger.info("✓ Connected to sauropod")
            
            # # Step 1: Install Oracle prerequisites
            # if verbose:
            #     logger.info("Step 1: Installing Oracle prerequisites")
            
            # prereq_commands = [
            #     "curl -o /tmp/oracle-database-preinstall-21c.rpm https://yum.oracle.com/repo/OracleLinux/OL8/appstream/x86_64/getPackage/oracle-database-preinstall-21c-1.0-1.el8.x86_64.rpm",
            #     "dnf install -y --nogpgcheck https://yum.oracle.com/repo/OracleLinux/OL8/appstream/x86_64/getPackage/compat-openssl10-1.0.2o-4.el8_6.x86_64.rpm",
            #     "dnf install -y --nogpgcheck /tmp/oracle-database-preinstall-21c.rpm"
            # ]
            
            # results = ssh.execute_commands(
            #     commands=prereq_commands,
            #     timeout=600,
            #     print_output=verbose,
            #     stop_on_error=True
            # )
            
            # failed = [r for r in results if r['rc'] != 0]
            # if failed:
            #     logger.error("Failed to install Oracle prerequisites")
            #     return False
            
            # if verbose:
            #     logger.info("✓ Oracle prerequisites installed")
            
            # Step 2: Create Oracle directories
#             if verbose:
#                 logger.info("Step 2: Creating Oracle directories")
            
#             dir_commands = [
#                 "mkdir -p /u01/app/oracle/product/21c/dbhome_1",
#                 "chown -R oracle:oinstall /u01",
#                 "chmod -R 775 /u01"
#             ]
            
#             results = ssh.execute_commands(
#                 commands=dir_commands,
#                 timeout=60,
#                 print_output=verbose,
#                 stop_on_error=True
#             )
            
#             failed = [r for r in results if r['rc'] != 0]
#             if failed:
#                 logger.error("Failed to create Oracle directories")
#                 return False
            
#             if verbose:
#                 logger.info("✓ Oracle directories created")
            
#             # Step 3: Configure oracle user environment
#             if verbose:
#                 logger.info("Step 3: Configuring oracle user environment")
            
#             bashrc_content = """
# # Oracle environment variables
# export ORACLE_BASE=/u01/app/oracle
# export ORACLE_HOME=$ORACLE_BASE/product/21c/dbhome_1
# export PATH=$ORACLE_HOME/bin:$PATH
# """
            
#             # Append to oracle's .bashrc
#             result = ssh.execute_command(
#                 f"echo '{bashrc_content}' >> /home/oracle/.bashrc",
#                 timeout=30,
#                 print_output=verbose
#             )
            
#             if result['rc'] != 0:
#                 logger.error("Failed to configure oracle user environment")
#                 return False
            
#             if verbose:
#                 logger.info("✓ Oracle user environment configured")
            
#             # Step 4: Copy Oracle installation archive from raptor to sauropod
#             if verbose:
#                 logger.info("Step 4: Copying Oracle installation archive from raptor to sauropod")
            
#             source_file = "/opt/guardium_tz_bootcamp_automation/upload/source_files/env_init/LINUX.X64_213000_db_home.zip"
#             dest_file = "/home/oracle/LINUX.X64_213000_db_home.zip"
            
#             # Use SFTP to upload file from local (raptor) to remote (sauropod)
#             if verbose:
#                 logger.info(f"Uploading {source_file} to sauropod:{dest_file}")
            
#             upload_success = ssh.upload_file(source_file, dest_file)
            
#             if not upload_success:
#                 logger.error("Failed to upload Oracle installation archive")
#                 return False
            
#             # Set ownership to oracle user
#             result = ssh.execute_command(
#                 f"chown oracle:oinstall {dest_file}",
#                 timeout=30,
#                 print_output=verbose
#             )
            
#             if result['rc'] != 0:
#                 logger.error(f"Failed to set ownership on Oracle archive: {result['stderr']}")
#                 return False
            
#             if verbose:
#                 logger.info("✓ Oracle installation archive uploaded and ownership set")
            
#             # Step 5: Unzip Oracle installation archive as oracle user
#             if verbose:
#                 logger.info("Step 5: Extracting Oracle installation archive")
            
#             unzip_cmd = "su - oracle -c 'unzip -q /home/oracle/LINUX.X64_213000_db_home.zip -d $ORACLE_HOME'"
            
#             result = ssh.execute_command(
#                 unzip_cmd,
#                 timeout=1800,  # 30 minutes for extraction
#                 print_output=verbose
#             )
            
#             if result['rc'] != 0:
#                 logger.error(f"Failed to extract Oracle installation archive: {result['stderr']}")
#                 return False
            
#             if verbose:
#                 logger.info("✓ Oracle installation archive extracted")
            
            # Step 6: Configure SSH for oracle user
#             if verbose:
#                 logger.info("Step 6: Configuring SSH for oracle user")
            
#             # Get hostname for SSH config
#             hostname_result = ssh.execute_command("hostname", timeout=30, print_output=False)
#             if hostname_result['rc'] != 0:
#                 logger.error("Failed to get hostname")
#                 return False
            
#             hostname = hostname_result['stdout'].strip()
            
#             # Create SSH config for oracle user
#             ssh_config_content = f"""Host localhost
#     Port 2223
#     StrictHostKeyChecking no
# Host {hostname}
#     Port 2223
#     StrictHostKeyChecking no
# """
            
#             # Create .ssh directory if it doesn't exist
#             ssh.execute_command("su - oracle -c 'mkdir -p ~/.ssh'", timeout=30, print_output=verbose)
            
#             # Write SSH config
#             config_cmd = f"su - oracle -c 'cat >> ~/.ssh/config <<EOF\n{ssh_config_content}EOF'"
            
#             result = ssh.execute_command(config_cmd, timeout=30, print_output=verbose)
            
#             if result['rc'] != 0:
#                 logger.error(f"Failed to configure SSH for oracle user: {result['stderr']}")
#                 return False
            
#             # Set proper permissions on SSH config
#             ssh.execute_command("su - oracle -c 'chmod 600 ~/.ssh/config'", timeout=30, print_output=verbose)
            
#             if verbose:
#                 logger.info("✓ SSH configured for oracle user")
            
            # Step 7: Run Oracle installer
            if verbose:
                logger.info("Step 7: Running Oracle installer (this may take 15-30 minutes)")
            
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
            
            result = ssh.execute_command(
                installer_cmd,
                timeout=3600,  # 60 minutes for installation
                print_output=verbose
            )
            
            # Oracle installer returns rc=6 for "Successfully Setup Software with warning(s)"
            # This is acceptable - rc=0 is success, rc=6 is success with warnings
            if result['rc'] not in [0, 6]:
                logger.error(f"Oracle installer failed with return code {result['rc']}: {result['stderr']}")
                return False
            
            if result['rc'] == 6:
                if verbose:
                    logger.info("⚠ Oracle installer completed with warnings (rc=6)")
            else:
                if verbose:
                    logger.info("✓ Oracle installer completed successfully")
            
            # Step 8: Run post-installation root scripts
            if verbose:
                logger.info("Step 8: Running post-installation root scripts")
            
            root_scripts = [
                "/u01/app/oraInventory/orainstRoot.sh",
                "/u01/app/oracle/product/21c/dbhome_1/root.sh"
            ]
            
            for script in root_scripts:
                if verbose:
                    logger.info(f"Executing {script}")
                
                result = ssh.execute_command(
                    script,
                    timeout=300,  # 5 minutes per script
                    print_output=verbose
                )
                
                if result['rc'] != 0:
                    logger.error(f"Failed to execute {script}: {result['stderr']}")
                    return False
            
            if verbose:
                logger.info("✓ Post-installation root scripts completed")
            
            # Step 9: Configure Oracle listener
            if verbose:
                logger.info("Step 9: Configuring Oracle listener")
            
            netca_cmd = "su - oracle -c '$ORACLE_HOME/bin/netca -silent -responseFile $ORACLE_HOME/assistants/netca/netca.rsp'"
            
            result = ssh.execute_command(
                netca_cmd,
                timeout=600,  # 10 minutes
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error(f"Failed to configure Oracle listener: {result['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ Oracle listener configured")
            
            # Step 10: Create Oracle database
            if verbose:
                logger.info("Step 10: Creating Oracle database (this may take 20-40 minutes)")
            
            dbca_cmd = """su - oracle -c 'dbca -silent -createDatabase \
  -templateName General_Purpose.dbc \
  -gdbname ORCLCDB \
  -sid ORCLCDB \
  -createAsContainerDatabase true \
  -numberOfPDBs 1 \
  -pdbName ORCLPDB1 \
  -sysPassword "Guardium123!" \
  -systemPassword "Guardium123!" \
  -pdbAdminPassword "Guardium123!" \
  -characterSet AL32UTF8 \
  -memoryMgmtType auto_sga \
  -totalMemory 1500 \
  -storageType FS \
  -datafileDestination "/u01/app/oracle/oradata"'"""
            
            result = ssh.execute_command(
                dbca_cmd,
                timeout=3600,  # 60 minutes for database creation
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error(f"Failed to create Oracle database: {result['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ Oracle database created")
            
            # Step 11: Add ORACLE_SID to oracle user's .bashrc
            if verbose:
                logger.info("Step 11: Adding ORACLE_SID to oracle user environment")
            
            oracle_sid_export = "\nexport ORACLE_SID=ORCLCDB\n"
            
            result = ssh.execute_command(
                f"su - oracle -c 'echo \"{oracle_sid_export}\" >> ~/.bashrc'",
                timeout=30,
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error(f"Failed to add ORACLE_SID to .bashrc: {result['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ ORACLE_SID added to oracle user environment")
            
            # Step 12: Configure pluggable databases to auto-start
            if verbose:
                logger.info("Step 12: Configuring pluggable databases to auto-start")
            
            sqlplus_cmd = """su - oracle -c 'export ORACLE_SID=ORCLCDB && echo "ALTER PLUGGABLE DATABASE ALL SAVE STATE;" | sqlplus -s / as sysdba'"""
            
            result = ssh.execute_command(
                sqlplus_cmd,
                timeout=300,  # 5 minutes
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error(f"Failed to configure PDB auto-start: {result['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ Pluggable databases configured to auto-start")
                logger.info("=" * 80)
                logger.info("Oracle Database 21c installation completed successfully!")
                logger.info("Database: ORCLCDB")
                logger.info("PDB: ORCLPDB1")
                logger.info("Passwords: Guardium123!")
                logger.info("=" * 80)
            
            return True
            
    except Exception as e:
        logger.error(f"Error during Oracle deployment: {e}")
        return False


# Made with Bob
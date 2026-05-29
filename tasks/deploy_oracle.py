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
            
            # Step 1: Install Oracle prerequisites
            if verbose:
                logger.info("Step 1: Installing Oracle prerequisites")
            
            prereq_commands = [
                "dnf install -y --nogpgcheck /opt/guardium_tz_bootcamp_automation/upload/source_files/oracle/oracle-database-preinstall-21c-1.0-1.el8.x86_64.rpm"
            ]
            
            results = ssh.execute_commands(
                commands=prereq_commands,
                timeout=600,
                print_output=verbose,
                stop_on_error=True
            )
            
            failed = [r for r in results if r['rc'] != 0]
            if failed:
                logger.error("Failed to install Oracle prerequisites")
                return False
            
            if verbose:
                logger.info("✓ Oracle prerequisites installed")
            
            # Step 2: Create Oracle directories
            if verbose:
                logger.info("Step 2: Creating Oracle directories")
            
            dir_commands = [
                "mkdir -p /u01/app/oracle/product/21c/dbhome_1",
                "chown -R oracle:oinstall /u01",
                "chmod -R 775 /u01"
            ]
            
            results = ssh.execute_commands(
                commands=dir_commands,
                timeout=60,
                print_output=verbose,
                stop_on_error=True
            )
            
            failed = [r for r in results if r['rc'] != 0]
            if failed:
                logger.error("Failed to create Oracle directories")
                return False
            
            if verbose:
                logger.info("✓ Oracle directories created")
            
            # Step 3: Configure oracle user environment
            if verbose:
                logger.info("Step 3: Configuring oracle user environment")
            
            bashrc_content = """
# Oracle environment variables
export ORACLE_BASE=/u01/app/oracle
export ORACLE_HOME=$ORACLE_BASE/product/21c/dbhome_1
export PATH=$ORACLE_HOME/bin:$PATH
"""
            
            # Append to oracle's .bashrc
            result = ssh.execute_command(
                f"echo '{bashrc_content}' >> /home/oracle/.bashrc",
                timeout=30,
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error("Failed to configure oracle user environment")
                return False
            
            if verbose:
                logger.info("✓ Oracle user environment configured")
            
            # Step 4: Copy Oracle installation archive from raptor to sauropod
            if verbose:
                logger.info("Step 4: Copying Oracle installation archive from raptor to sauropod")
            
            source_file = "/opt/guardium_tz_bootcamp_automation/upload/source_files/oracle/LINUX.X64_213000_db_home.zip"
            dest_file = "/home/oracle/LINUX.X64_213000_db_home.zip"
            
            # Use SFTP to upload file from local (raptor) to remote (sauropod)
            if verbose:
                logger.info(f"Uploading {source_file} to sauropod:{dest_file}")
            
            upload_success = ssh.upload_file(source_file, dest_file)
            
            if not upload_success:
                logger.error("Failed to upload Oracle installation archive")
                return False
            
            # Set ownership to oracle user
            result = ssh.execute_command(
                f"chown oracle:oinstall {dest_file}",
                timeout=30,
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error(f"Failed to set ownership on Oracle archive: {result['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ Oracle installation archive uploaded and ownership set")
            
            # Step 5: Unzip Oracle installation archive as oracle user
            if verbose:
                logger.info("Step 5: Extracting Oracle installation archive")
            
            unzip_cmd = "su - oracle -c 'unzip -q /home/oracle/LINUX.X64_213000_db_home.zip -d $ORACLE_HOME'"
            
            result = ssh.execute_command(
                unzip_cmd,
                timeout=1800,  # 30 minutes for extraction
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error(f"Failed to extract Oracle installation archive: {result['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ Oracle installation archive extracted")
            
            # Step 6: Configure SSH for oracle user
            if verbose:
                logger.info("Step 6: Configuring SSH for oracle user")
            
            # Get hostname for SSH config
            hostname_result = ssh.execute_command("hostname", timeout=30, print_output=False)
            if hostname_result['rc'] != 0:
                logger.error("Failed to get hostname")
                return False
            
            hostname = hostname_result['stdout'].strip()
            
            # Create SSH config for oracle user
            ssh_config_content = f"""Host localhost
    Port 2223
    StrictHostKeyChecking no
Host {hostname}
    Port 2223
    StrictHostKeyChecking no
"""
            
            # Create .ssh directory if it doesn't exist
            ssh.execute_command("su - oracle -c 'mkdir -p ~/.ssh'", timeout=30, print_output=verbose)
            
            # Write SSH config
            config_cmd = f"su - oracle -c 'cat >> ~/.ssh/config <<EOF\n{ssh_config_content}EOF'"
            
            result = ssh.execute_command(config_cmd, timeout=30, print_output=verbose)
            
            if result['rc'] != 0:
                logger.error(f"Failed to configure SSH for oracle user: {result['stderr']}")
                return False
            
            # Set proper permissions on SSH config
            ssh.execute_command("su - oracle -c 'chmod 600 ~/.ssh/config'", timeout=30, print_output=verbose)
            
            if verbose:
                logger.info("✓ SSH configured for oracle user")
            
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
            
            # Only log warnings in verbose mode
            if result['rc'] == 6 and verbose:
                logger.info("⚠ Oracle installer completed with warnings (rc=6)")
            elif result['rc'] == 0 and verbose:
                logger.info("✓ Oracle installer completed successfully")
            elif not verbose:
                # In non-verbose mode, just log success without mentioning rc=6
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
            
            # Use password from custom_variables (pwd)
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
            
            # Step 13: Upload and configure listener.ora
            if verbose:
                logger.info("Step 13: Configuring listener.ora")
            
            # Path to local config file
            listener_config_path = Path(__file__).parent.parent / "automation_config_files" / "listener.ora"
            
            if not listener_config_path.exists():
                logger.error(f"listener.ora config file not found at {listener_config_path}")
                return False
            
            # Upload listener.ora to sauropod
            remote_listener_path = "/tmp/listener.ora"
            upload_success = ssh.upload_file(str(listener_config_path), remote_listener_path)
            
            if not upload_success:
                logger.error("Failed to upload listener.ora")
                return False
            
            # Copy to Oracle network admin directory
            copy_listener_cmd = f"su - oracle -c 'cp {remote_listener_path} $ORACLE_HOME/network/admin/listener.ora && chmod 644 $ORACLE_HOME/network/admin/listener.ora'"
            
            result = ssh.execute_command(
                copy_listener_cmd,
                timeout=60,
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error(f"Failed to copy listener.ora: {result['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ listener.ora configured")
            
            # Step 14: Upload and configure tnsnames.ora
            if verbose:
                logger.info("Step 14: Configuring tnsnames.ora")
            
            # Path to local config file
            tnsnames_config_path = Path(__file__).parent.parent / "automation_config_files" / "tnsnames.ora"
            
            if not tnsnames_config_path.exists():
                logger.error(f"tnsnames.ora config file not found at {tnsnames_config_path}")
                return False
            
            # Upload tnsnames.ora to sauropod
            remote_tnsnames_path = "/tmp/tnsnames.ora"
            upload_success = ssh.upload_file(str(tnsnames_config_path), remote_tnsnames_path)
            
            if not upload_success:
                logger.error("Failed to upload tnsnames.ora")
                return False
            
            # Copy to Oracle network admin directory
            copy_tnsnames_cmd = f"su - oracle -c 'cp {remote_tnsnames_path} $ORACLE_HOME/network/admin/tnsnames.ora && chmod 644 $ORACLE_HOME/network/admin/tnsnames.ora'"
            
            result = ssh.execute_command(
                copy_tnsnames_cmd,
                timeout=60,
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error(f"Failed to copy tnsnames.ora: {result['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ tnsnames.ora configured")
            
            # Step 15: Upload and configure sqlnet.ora
            if verbose:
                logger.info("Step 15: Configuring sqlnet.ora")
            
            # Path to local config file
            sqlnet_config_path = Path(__file__).parent.parent / "automation_config_files" / "sqlnet.ora"
            
            if not sqlnet_config_path.exists():
                logger.error(f"sqlnet.ora config file not found at {sqlnet_config_path}")
                return False
            
            # Upload sqlnet.ora to sauropod
            remote_sqlnet_path = "/tmp/sqlnet.ora"
            upload_success = ssh.upload_file(str(sqlnet_config_path), remote_sqlnet_path)
            
            if not upload_success:
                logger.error("Failed to upload sqlnet.ora")
                return False
            
            # Copy to Oracle network admin directory
            copy_sqlnet_cmd = f"su - oracle -c 'cp {remote_sqlnet_path} $ORACLE_HOME/network/admin/sqlnet.ora && chmod 644 $ORACLE_HOME/network/admin/sqlnet.ora'"
            
            result = ssh.execute_command(
                copy_sqlnet_cmd,
                timeout=60,
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error(f"Failed to copy sqlnet.ora: {result['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ sqlnet.ora configured")
            
            # Step 16: Restart Oracle listener to apply new configuration
            if verbose:
                logger.info("Step 16: Restarting Oracle listener")
            
            restart_listener_cmds = [
                "su - oracle -c 'lsnrctl stop'",
                "su - oracle -c 'lsnrctl start'"
            ]
            
            results = ssh.execute_commands(
                commands=restart_listener_cmds,
                timeout=120,
                print_output=verbose,
                stop_on_error=False  # Continue even if stop fails (listener might not be running)
            )
            
            # Check if start command succeeded (it's the second command)
            if len(results) > 1 and results[1]['rc'] != 0:
                logger.error(f"Failed to start Oracle listener: {results[1]['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ Oracle listener restarted with new configuration")
            
            # Step 17: Configure /etc/oratab for auto-start
            if verbose:
                logger.info("Step 17: Configuring /etc/oratab for database auto-start")
            
            # Change the last field from N to Y to enable auto-start
            oratab_cmd = "sed -i 's/^ORCLCDB:\\(.*\\):N$/ORCLCDB:\\1:Y/' /etc/oratab"
            
            result = ssh.execute_command(
                oratab_cmd,
                timeout=60,
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error(f"Failed to configure /etc/oratab: {result['stderr']}")
                return False
            
            # Verify the change
            verify_cmd = "grep ORCLCDB /etc/oratab"
            result = ssh.execute_command(
                verify_cmd,
                timeout=30,
                print_output=verbose
            )
            
            if result['rc'] == 0 and ':Y' in result['stdout']:
                if verbose:
                    logger.info("✓ /etc/oratab configured for auto-start")
            else:
                logger.warning("Could not verify /etc/oratab configuration")
            
            # Step 18: Install HR schema with sample data
            if verbose:
                logger.info("Step 18: Installing HR schema with sample data")
            
            # Path to HR schema archive on raptor
            hr_archive_path = "/opt/guardium_tz_bootcamp_automation/upload/source_files/oracle/human_resources.tar.gz"
            hr_remote_path = "/home/oracle/human_resources.tar.gz"
            
            # Upload HR schema archive to sauropod
            if verbose:
                logger.info(f"Uploading HR schema archive to sauropod")
            
            upload_success = ssh.upload_file(hr_archive_path, hr_remote_path)
            
            if not upload_success:
                logger.error("Failed to upload HR schema archive")
                return False
            
            # Set ownership to oracle user
            result = ssh.execute_command(
                f"chown oracle:oinstall {hr_remote_path}",
                timeout=30,
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error(f"Failed to set ownership on HR archive: {result['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ HR schema archive uploaded")
            
            # Extract HR schema archive
            if verbose:
                logger.info("Extracting HR schema archive")
            
            extract_cmd = f"su - oracle -c 'cd /home/oracle && tar -xzf {hr_remote_path}'"
            
            result = ssh.execute_command(
                extract_cmd,
                timeout=120,
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error(f"Failed to extract HR schema archive: {result['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ HR schema archive extracted")
            
            # Update password in hr_install.sql
            if verbose:
                logger.info("Updating password in hr_install.sql")
            
            # Escape special characters in password for sed and shell
            # Replace / with \/ for sed, and escape other special characters
            escaped_password = root_password.replace('\\', '\\\\').replace('/', '\\/').replace('&', '\\&').replace('!', '\\!')
            
            # Use single quotes around sed command to prevent shell interpretation
            update_password_cmd = f"su - oracle -c 'sed -i \"s/DEFINE pass = .\\+/DEFINE pass = \\x27{escaped_password}\\x27/\" /home/oracle/human_resources/hr_install.sql'"
            
            result = ssh.execute_command(
                update_password_cmd,
                timeout=60,
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error(f"Failed to update password in hr_install.sql: {result['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ Password updated in hr_install.sql")
            
            # Create HR tablespace
            if verbose:
                logger.info("Creating HR tablespace")
            
            # First switch to PDB, then create tablespace in separate commands
            create_tablespace_cmd = """su - oracle -c "export ORACLE_SID=ORCLCDB && sqlplus -s / as sysdba << 'EOF'
ALTER SESSION SET CONTAINER = ORCLPDB1;
CREATE TABLESPACE hr_data DATAFILE '/u01/app/oracle/oradata/ORCLCDB/ORCLPDB1/hr_data01.dbf' SIZE 100M AUTOEXTEND ON NEXT 10M MAXSIZE 1G;
EXIT;
EOF
" """
            
            result = ssh.execute_command(
                create_tablespace_cmd,
                timeout=300,
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error(f"Failed to create HR tablespace: {result['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ HR tablespace created")
            
            # Install HR schema
            if verbose:
                logger.info("Installing HR schema (this may take a few minutes)")
            
            # Use heredoc for proper SQL execution
            install_hr_cmd = """su - oracle -c "export ORACLE_SID=ORCLCDB && cd /home/oracle/human_resources && sqlplus -s / as sysdba << 'EOF'
ALTER SESSION SET CONTAINER = ORCLPDB1;
@hr_install.sql
EXIT;
EOF
" """
            
            result = ssh.execute_command(
                install_hr_cmd,
                timeout=600,  # 10 minutes
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.error(f"Failed to install HR schema: {result['stderr']}")
                return False
            
            if verbose:
                logger.info("✓ HR schema installed")
            
            # Step 19: Clean up installation files
            if verbose:
                logger.info("Step 19: Cleaning up installation files")
            
            cleanup_commands = [
                "su - oracle -c 'rm -f /home/oracle/LINUX.X64_213000_db_home.zip'",
                "su - oracle -c 'rm -f /home/oracle/human_resources.tar.gz'",
                "su - oracle -c 'rm -rf /home/oracle/human_resources'"
            ]
            
            results = ssh.execute_commands(
                commands=cleanup_commands,
                timeout=60,
                print_output=verbose,
                stop_on_error=False  # Continue even if some files don't exist
            )
            
            if verbose:
                logger.info("✓ Installation files cleaned up")
            
            # Step 20: Install SQLcl
            if verbose:
                logger.info("Step 20: Installing SQLcl")
            
            # Install Java 11 if not present
            java_install_cmd = "dnf install -y java-11-openjdk"
            result = ssh.execute_command(
                java_install_cmd,
                timeout=300,
                print_output=verbose
            )
            
            if result['rc'] != 0:
                logger.warning("Failed to install Java 11, SQLcl installation may fail")
            
            # Download and install SQLcl
            sqlcl_install_commands = [
                "cd /tmp",
                "curl -L -o sqlcl-latest.zip https://download.oracle.com/otn_software/java/sqldeveloper/sqlcl-latest.zip",
                "mkdir -p /opt/sqlcl",
                "unzip -q -o sqlcl-latest.zip -d /opt/sqlcl",
                "rm -f /tmp/sqlcl-latest.zip"
            ]
            
            results = ssh.execute_commands(
                commands=sqlcl_install_commands,
                timeout=600,
                print_output=verbose,
                stop_on_error=True
            )
            
            failed = [r for r in results if r['rc'] != 0]
            if failed:
                logger.warning("Failed to install SQLcl, but continuing...")
            else:
                if verbose:
                    logger.info("✓ SQLcl installed")
            
            # Step 21: Configure SQLcl for oracle user
            if verbose:
                logger.info("Step 21: Configuring SQLcl for oracle user")
            
            # Add SQLcl to PATH in oracle's .bashrc
            sqlcl_bashrc_addition = """
# SQLcl PATH
export PATH=$PATH:/opt/sqlcl/sqlcl/bin

# SQLcl aliases
alias sql='sql /nolog'

# SQLcl history settings
export SQLPATH=$HOME/.sqlcl
"""
            
            # Check if SQLcl PATH is already in .bashrc
            check_sqlcl_cmd = "su - oracle -c 'grep -q \"/opt/sqlcl/sqlcl/bin\" ~/.bashrc'"
            check_result = ssh.execute_command(
                check_sqlcl_cmd,
                timeout=30,
                print_output=False
            )
            
            if check_result['rc'] != 0:  # Not found, add it
                # Use heredoc to append to .bashrc
                append_sqlcl_cmd = """su - oracle -c "cat >> ~/.bashrc << 'EOF'

# SQLcl PATH
export PATH=\\$PATH:/opt/sqlcl/sqlcl/bin

# SQLcl aliases
alias sql='sql /nolog'

# SQLcl history settings
export SQLPATH=\\$HOME/.sqlcl
EOF
" """
                
                result = ssh.execute_command(
                    append_sqlcl_cmd,
                    timeout=60,
                    print_output=verbose
                )
                
                if result['rc'] != 0:
                    logger.warning("Failed to update oracle's .bashrc with SQLcl configuration")
                else:
                    if verbose:
                        logger.info("✓ Added SQLcl to oracle's PATH")
            
            # Create .sqlcl directory and upload login.sql
            sqlcl_setup_commands = [
                "su - oracle -c 'mkdir -p ~/.sqlcl'"
            ]
            
            results = ssh.execute_commands(
                commands=sqlcl_setup_commands,
                timeout=60,
                print_output=verbose,
                stop_on_error=False
            )
            
            # Upload login.sql configuration
            login_sql_path = Path(__file__).parent.parent / "automation_config_files" / "sqlcl_login.sql"
            
            if login_sql_path.exists():
                remote_login_sql = "/tmp/sqlcl_login.sql"
                upload_success = ssh.upload_file(str(login_sql_path), remote_login_sql)
                
                if upload_success:
                    # Copy to oracle's .sqlcl directory
                    copy_cmd = "su - oracle -c 'cp /tmp/sqlcl_login.sql ~/.sqlcl/login.sql && chmod 644 ~/.sqlcl/login.sql'"
                    result = ssh.execute_command(
                        copy_cmd,
                        timeout=60,
                        print_output=verbose
                    )
                    
                    if result['rc'] == 0:
                        if verbose:
                            logger.info("✓ SQLcl login.sql configured")
                    else:
                        logger.warning("Failed to configure SQLcl login.sql")
                else:
                    logger.warning("Failed to upload SQLcl login.sql")
            else:
                logger.warning(f"SQLcl login.sql not found at {login_sql_path}")
            
            if verbose:
                logger.info("=" * 80)
                logger.info("Oracle Database 21c installation completed successfully!")
                logger.info("Database: ORCLCDB")
                logger.info("PDB: ORCLPDB1")
                logger.info(f"Passwords: {root_password}")
                logger.info("Network Configuration:")
                logger.info("  - listener.ora: Configured on localhost:1521")
                logger.info("  - tnsnames.ora: ORCLPDB1 service configured")
                logger.info("  - sqlnet.ora: TNSNAMES, EZCONNECT enabled")
                logger.info("Auto-start: Enabled in /etc/oratab")
                logger.info("Sample Data: HR schema installed in hr_data tablespace")
                logger.info("Tools: SQLcl installed and configured")
                logger.info("=" * 80)
            
            return True
            
    except Exception as e:
        logger.error(f"Error during Oracle deployment: {e}")
        return False


# Made with Bob

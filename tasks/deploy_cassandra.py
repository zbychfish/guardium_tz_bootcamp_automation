#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cassandra Deployment Task
Handles Cassandra installation and configuration on remote machine (sauropod)
"""

import sys
from pathlib import Path

# Add core modules to path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import ConfigLoader
from core.ssh_client import SSHClient


def deploy_cassandra_on_sauropod(config: ConfigLoader, logger, verbose: bool = True) -> bool:
    """
    Deploy Apache Cassandra 4.1 on remote machine (sauropod).
    
    This function:
    1. Connects to sauropod machine via SSH
    2. Creates Cassandra repository configuration
    3. Installs Cassandra
    4. Configures audit logging in cassandra.yaml
    5. Configures audit logging in logback.xml
    6. Starts Cassandra service
    
    Args:
        config: ConfigLoader instance with machine information
        logger: Logger instance
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    if verbose:
        logger.info("=" * 80)
        logger.info("Apache Cassandra 4.1 deployment on sauropod")
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
    
    # Connect to sauropod via SSH
    ssh = SSHClient(
        host=sauropod_ip,
        port=ssh_port,
        username=ssh_username,
        password=root_password,
        timeout=60
    )
    
    if not ssh.connect():
        logger.error("Failed to connect to sauropod via SSH")
        return False
    
    try:
        # Step 1: Create Cassandra repository configuration
        if verbose:
            logger.info("Step 1: Creating Cassandra repository configuration")
        
        repo_content = """[cassandra]
name=Apache Cassandra
baseurl=https://redhat.cassandra.apache.org/41x/
gpgcheck=0
repo_gpgcheck=0
gpgkey=https://downloads.apache.org/cassandra/KEYS
"""
        
        create_repo_cmd = f"cat << 'EOF' > /etc/yum.repos.d/cassandra.repo\n{repo_content}EOF"
        result = ssh.execute_command(
            create_repo_cmd,
            timeout=30,
            print_output=verbose
        )
        
        if result['rc'] != 0:
            logger.error("Failed to create Cassandra repository configuration")
            return False
        
        if verbose:
            logger.info("✓ Cassandra repository configured")
        
        # Step 2: Install Cassandra
        if verbose:
            logger.info("Step 2: Installing Cassandra (this may take a few minutes)")
        
        install_cmd = "dnf -y install cassandra"
        result = ssh.execute_command(
            install_cmd,
            timeout=600,
            print_output=verbose
        )
        
        if result['rc'] != 0:
            logger.error("Failed to install Cassandra")
            return False
        
        if verbose:
            logger.info("✓ Cassandra installed successfully")
        
        # Step 3: Configure audit logging in cassandra.yaml
        if verbose:
            logger.info("Step 3: Configuring audit logging in cassandra.yaml")
        
        configure_yaml_cmd = r"sed -i '/^audit_logging_options:/,/^[[:space:]]*- class_name:/c\audit_logging_options:\n  enabled: true\n  logger:\n    - class_name: FileAuditLogger' /etc/cassandra/conf/cassandra.yaml"
        result = ssh.execute_command(
            configure_yaml_cmd,
            timeout=30,
            print_output=verbose
        )
        
        if result['rc'] != 0:
            logger.error("Failed to configure audit logging in cassandra.yaml")
            return False
        
        if verbose:
            logger.info("✓ Audit logging configured in cassandra.yaml")
        
        # Step 4: Configure audit logging in logback.xml
        if verbose:
            logger.info("Step 4: Configuring audit logging in logback.xml")
        
        logback_commands = [
            "sed -i '/<!-- <appender name=\"AUDIT\"/,/SizeAndTimeBasedRollingPolicy/ { s/<!-- //; s/ -->// }' /etc/cassandra/conf/logback.xml",
            "sed -i 's|<!-- *<fileNamePattern>\\(.*\\)</fileNamePattern> *-->|<fileNamePattern>\\1</fileNamePattern>|' /etc/cassandra/conf/logback.xml",
            "sed -i '/<!-- *<maxFileSize>/,/<\\/appender> *-->/ { s/<!-- //; s/ -->// }' /etc/cassandra/conf/logback.xml",
            "sed -i '/<!-- *<logger name=\"org.apache.cassandra.audit\"/,/<\\/logger> *-->/ { s/<!-- //; s/ -->// }' /etc/cassandra/conf/logback.xml"
        ]
        
        results = ssh.execute_commands(
            commands=logback_commands,
            timeout=30,
            print_output=verbose,
            stop_on_error=True
        )
        
        failed = [r for r in results if r['rc'] != 0]
        if failed:
            logger.error("Failed to configure audit logging in logback.xml")
            return False
        
        if verbose:
            logger.info("✓ Audit logging configured in logback.xml")
        
        # Step 5: Start Cassandra service (twice to ensure it's running)
        if verbose:
            logger.info("Step 5: Starting Cassandra service")
        
        start_commands = [
            "service cassandra start",
            "sleep 5",
            "service cassandra start"
        ]
        
        results = ssh.execute_commands(
            commands=start_commands,
            timeout=60,
            print_output=verbose,
            stop_on_error=False
        )
        
        if verbose:
            logger.info("✓ Cassandra service started")
        
        # Step 6: Verify Cassandra is running
        if verbose:
            logger.info("Step 6: Verifying Cassandra service status")
        
        verify_cmd = "service cassandra status"
        result = ssh.execute_command(
            verify_cmd,
            timeout=30,
            print_output=verbose
        )
        
        if verbose:
            if result['rc'] == 0:
                logger.info("✓ Cassandra is running")
            else:
                logger.warning("Cassandra service status check returned non-zero, but this may be normal during startup")
        
        if verbose:
            logger.info("=" * 80)
            logger.info("Cassandra deployment completed successfully")
            logger.info("=" * 80)
            logger.info("Note: Cassandra may take a few minutes to fully start up")
        
        return True
    
    finally:
        ssh.disconnect()


# Made with Bob
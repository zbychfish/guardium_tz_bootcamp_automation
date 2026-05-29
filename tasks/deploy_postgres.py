#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PostgreSQL Deployment Task
Handles PostgreSQL 16 installation and configuration on local machine (raptor)
"""

import sys
import subprocess
from pathlib import Path

# Add core modules to path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import ConfigLoader


def deploy_postgres_on_raptor(config: ConfigLoader, logger, verbose: bool = True) -> bool:
    """
    Deploy PostgreSQL 16 on local machine (raptor).
    
    This function:
    1. Installs and initializes PostgreSQL 16
    2. Configures SSL, authentication, and network access
    3. Creates admin users
    
    Args:
        config: ConfigLoader instance with machine information
        logger: Logger instance
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    if verbose:
        logger.info("=" * 80)
        logger.info("PostgreSQL 16 deployment on raptor (local)")
        logger.info("=" * 80)
    
    # Get password from custom_variables
    password = config.get_custom_variable('pwd')
    if not password:
        logger.error("Password (pwd) not found in custom_variables")
        return False
    
    # Get network configuration
    raptor_ip = config.get_machine_ip('raptor', use_private=True)
    if raptor_ip:
        ip_parts = raptor_ip.split('.')
        network = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0/24"
    else:
        network = "10.10.9.0/24"
        logger.warning(f"Could not get raptor IP, using default network: {network}")
    
    try:
        # Step 1: Install and initialize PostgreSQL
        if verbose:
            logger.info("Step 1: Installing and initializing PostgreSQL 16")
        
        commands = [
            (["dnf", "-qy", "install", "@postgresql:16"], 600, "install"),
            (["postgresql-setup", "--initdb", "--unit", "postgresql"], 300, "initialize"),
            (["chpasswd"], 60, "set password", f"postgres:{password}")
        ]
        
        for cmd, timeout, desc, *input_data in commands:
            result = subprocess.run(
                cmd,
                input=input_data[0] if input_data else None,
                text=True,
                capture_output=True,
                timeout=timeout
            )
            if result.returncode != 0:
                logger.error(f"Failed to {desc}: {result.stderr}")
                return False
        
        if verbose:
            logger.info("✓ PostgreSQL 16 installed and initialized")
        
        # Step 2: Create and configure SSL certificate
        if verbose:
            logger.info("Step 2: Configuring SSL certificate")
        
        ssl_commands = [
            ["openssl", "req", "-new", "-x509", "-days", "365", "-nodes", "-text",
             "-out", "/var/lib/pgsql/data/pgsql.crt",
             "-keyout", "/var/lib/pgsql/data/pgsql.key",
             "-subj", "/CN=raptor.demo.com"],
            ["chown", "postgres:postgres", "/var/lib/pgsql/data/pgsql.crt", "/var/lib/pgsql/data/pgsql.key"]
        ]
        
        for cmd in ssl_commands:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                logger.error(f"SSL configuration failed: {result.stderr}")
                return False
        
        if verbose:
            logger.info("✓ SSL certificate configured")
        
        # Step 3: Configure postgresql.conf
        if verbose:
            logger.info("Step 3: Configuring postgresql.conf")
        
        conf_path = Path("/var/lib/pgsql/data/postgresql.conf")
        if not conf_path.exists():
            logger.error(f"postgresql.conf not found")
            return False
        
        lines = []
        with conf_path.open() as f:
            for line in f:
                if line.strip().startswith("#ssl = off") or line.strip() == "#ssl = off":
                    line = "ssl = on\n"
                elif "ssl_cert_file" in line:
                    line = "ssl_cert_file = '/var/lib/pgsql/data/pgsql.crt'\n"
                elif "ssl_key_file" in line:
                    line = "ssl_key_file = '/var/lib/pgsql/data/pgsql.key'\n"
                elif "listen_addresses" in line and ("#" in line or "localhost" in line):
                    line = "listen_addresses = '*'\n"
                lines.append(line)
        
        conf_path.write_text("".join(lines))
        
        if verbose:
            logger.info("✓ postgresql.conf configured")
        
        # Step 4: Configure pg_hba.conf
        if verbose:
            logger.info("Step 4: Configuring pg_hba.conf")
        
        hba_path = Path("/var/lib/pgsql/data/pg_hba.conf")
        if not hba_path.exists():
            logger.error(f"pg_hba.conf not found")
            return False
        
        lines = []
        network_added = False
        
        with hba_path.open() as f:
            for line in f:
                stripped = line.strip()
                
                # Change local peer to ident
                if stripped.startswith("local") and "peer" in line:
                    lines.append("local   all             all                                     ident\n")
                
                # Replace host 127.0.0.1 ident with scram-sha-256 and add network line
                elif stripped.startswith("host") and "127.0.0.1/32" in line and "ident" in line:
                    lines.append("host    all             all             127.0.0.1/32            scram-sha-256\n")
                    if not network_added:
                        lines.append(f"host    all             all             {network}            scram-sha-256\n")
                        network_added = True
                
                # Keep other lines as-is (skip duplicates of what we already added)
                elif not (stripped.startswith("host") and "127.0.0.1/32" in line and "scram-sha-256" in line):
                    if not (stripped.startswith("host") and network in line):
                        lines.append(line)
        
        hba_path.write_text("".join(lines))
        
        if verbose:
            logger.info("✓ pg_hba.conf configured")
        
        # Step 5: Start PostgreSQL service
        if verbose:
            logger.info("Step 5: Starting PostgreSQL service")
        
        for cmd in [["systemctl", "start", "postgresql.service"],
                    ["systemctl", "enable", "postgresql.service"]]:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                logger.error(f"Service command failed: {result.stderr}")
                return False
        
        if verbose:
            logger.info("✓ PostgreSQL service started and enabled")
        
        # Step 6: Configure database users
        if verbose:
            logger.info("Step 6: Configuring database users")
        
        users = ["postgres", "tom", "jerry"]
        
        for user in users:
            if user == "postgres":
                sql = f"ALTER USER {user} WITH PASSWORD '{password}';"
            else:
                sql = f"CREATE ROLE {user} PASSWORD '{password}' SUPERUSER CREATEDB CREATEROLE INHERIT LOGIN;"
            
            result = subprocess.run(
                ["sudo", "-u", "postgres", "psql", "-d", "postgres", "-U", "postgres", "-c", sql],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                logger.error(f"Failed to configure user {user}: {result.stderr}")
                return False
        
        if verbose:
            logger.info(f"✓ Database users configured: {', '.join(users)}")
        
        if verbose:
            logger.info("=" * 80)
            logger.info("PostgreSQL 16 installation completed successfully!")
            logger.info(f"Users: {', '.join(users)} (password: {password})")
            logger.info(f"Network: {network}")
            logger.info("SSL: Enabled | Authentication: scram-sha-256")
            logger.info("=" * 80)
        
        return True
        
    except subprocess.TimeoutExpired as e:
        logger.error(f"Command timeout: {e}")
        return False
    except Exception as e:
        logger.error(f"Error during PostgreSQL deployment: {e}")
        return False


# Made with Bob
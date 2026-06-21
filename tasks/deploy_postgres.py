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
            (["dnf", "-qy", "install", "postgresql-contrib"], 600, "install postgresql-contrib"),
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
        
        # Create SSL certificate with SAN for localhost and IP addresses
        ssl_config = """[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_req
prompt = no

[req_distinguished_name]
CN = raptor.demo.guardium

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = raptor.demo.guardium
DNS.2 = localhost
IP.1 = 127.0.0.1
"""
        
        # Write SSL config to temp file
        ssl_config_path = Path("/tmp/pgsql_ssl.conf")
        ssl_config_path.write_text(ssl_config)
        
        ssl_commands = [
            ["openssl", "req", "-new", "-x509", "-days", "365", "-nodes", "-text",
             "-out", "/var/lib/pgsql/data/pgsql.crt",
             "-keyout", "/var/lib/pgsql/data/pgsql.key",
             "-config", "/tmp/pgsql_ssl.conf"],
            ["chown", "postgres:postgres", "/var/lib/pgsql/data/pgsql.crt", "/var/lib/pgsql/data/pgsql.key"],
            ["rm", "-f", "/tmp/pgsql_ssl.conf"]
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
        in_replication_section = False
        
        with hba_path.open() as f:
            for line in f:
                stripped = line.strip()
                
                # Skip empty lines and comments
                if not stripped or stripped.startswith("#"):
                    lines.append(line)
                    continue
                
                # Detect replication section start
                if "replication" in stripped.lower():
                    in_replication_section = True
                    lines.append(line)
                    continue
                
                # In replication section - keep lines as-is
                if in_replication_section:
                    lines.append(line)
                    continue
                
                # Before replication section - modify lines
                parts = stripped.split()
                
                # Change local peer to ident (only for "all" database)
                if len(parts) >= 4 and parts[0] == "local" and parts[1] == "all" and parts[2] == "all" and parts[3] == "peer":
                    line = line.replace("peer", "ident")
                    lines.append(line)
                
                # Replace host 127.0.0.1 ident with scram-sha-256 and add network line
                elif len(parts) >= 5 and parts[0] == "host" and parts[1] == "all" and parts[2] == "all" and "127.0.0.1/32" in parts[3]:
                    line = line.replace("ident", "scram-sha-256")
                    lines.append(line)
                    lines.append(f"host    all             all             {network}            scram-sha-256\n")
                
                # Keep other lines as-is
                else:
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
        
        # Step 7: Create required PostgreSQL extensions
        if verbose:
            logger.info('Step 7: Creating PostgreSQL extension "uuid-ossp"')
        
        result = subprocess.run(
            ["sudo", "-u", "postgres", "psql", "-d", "postgres", "-U", "postgres", "-c", 'CREATE EXTENSION "uuid-ossp";'],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            logger.error(f'Failed to create extension "uuid-ossp": {result.stderr}')
            return False
        
        if verbose:
            logger.info('✓ PostgreSQL extension "uuid-ossp" created')
        
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
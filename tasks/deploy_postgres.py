#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PostgreSQL Deployment Task
Handles PostgreSQL 16 installation and configuration on local machine (raptor)
"""

import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import ConfigLoader


def _header(logger, title: str):
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)


def _run(cmd, logger, desc: str, timeout: int = 120, input_data: str = None) -> bool:
    result = subprocess.run(
        cmd,
        input=input_data,
        text=True,
        capture_output=True,
        timeout=timeout
    )
    if result.returncode != 0:
        logger.error(f"✗ Failed to {desc}: {result.stderr.strip()}")
        return False
    return True


def deploy_postgres_on_raptor(config: ConfigLoader, logger, verbose: bool = True) -> bool:
    _header(logger, "PostgreSQL 16 deployment on raptor (local)")

    password = config.get_custom_variable('pwd')
    if not password:
        logger.error("✗ pwd not found in custom_variables")
        return False

    raptor_ip = config.get_machine_ip('raptor', use_private=True)
    if raptor_ip:
        ip_parts = raptor_ip.split('.')
        network = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0/24"
    else:
        network = "10.10.9.0/24"
        logger.warning(f"  Could not get raptor IP, using default network: {network}")

    try:
        # ── Step 1: install + init ────────────────────────────────────────────
        logger.info("  ➜ dnf install @postgresql:16 + postgresql-contrib")
        for cmd, timeout, desc, *inp in [
            (["dnf", "-qy", "install", "@postgresql:16"],             600, "install @postgresql:16"),
            (["dnf", "-qy", "install", "postgresql-contrib"],         600, "install postgresql-contrib"),
            (["postgresql-setup", "--initdb", "--unit", "postgresql"], 300, "initdb"),
            (["chpasswd"],                                              60, "set postgres OS password", f"postgres:{password}"),
        ]:
            if not _run(cmd, logger, desc, timeout, inp[0] if inp else None):
                return False
        logger.info("  ✓ PostgreSQL 16 installed and initialized")

        # ── Step 2: SSL certificate ───────────────────────────────────────────
        logger.info("  ➜ openssl: generate self-signed cert → /var/lib/pgsql/data/")
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
        Path("/tmp/pgsql_ssl.conf").write_text(ssl_config)

        for cmd, desc in [
            (["openssl", "req", "-new", "-x509", "-days", "365", "-nodes", "-text",
              "-out", "/var/lib/pgsql/data/pgsql.crt",
              "-keyout", "/var/lib/pgsql/data/pgsql.key",
              "-config", "/tmp/pgsql_ssl.conf"],
             "generate SSL cert"),
            (["chown", "postgres:postgres",
              "/var/lib/pgsql/data/pgsql.crt", "/var/lib/pgsql/data/pgsql.key"],
             "chown pgsql cert"),
            (["rm", "-f", "/tmp/pgsql_ssl.conf"], "remove temp ssl config"),
        ]:
            if not _run(cmd, logger, desc):
                return False
        logger.info("  ✓ SSL certificate configured")

        # ── Step 3: postgresql.conf ───────────────────────────────────────────
        logger.info("  ➜ patch /var/lib/pgsql/data/postgresql.conf (ssl=on, listen_addresses='*')")
        conf_path = Path("/var/lib/pgsql/data/postgresql.conf")
        if not conf_path.exists():
            logger.error("✗ postgresql.conf not found")
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
        logger.info("  ✓ postgresql.conf configured")

        # ── Step 4: pg_hba.conf ───────────────────────────────────────────────
        logger.info(f"  ➜ patch /var/lib/pgsql/data/pg_hba.conf (scram-sha-256, network {network})")
        hba_path = Path("/var/lib/pgsql/data/pg_hba.conf")
        if not hba_path.exists():
            logger.error("✗ pg_hba.conf not found")
            return False

        lines = []
        in_replication_section = False
        with hba_path.open() as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    lines.append(line)
                    continue
                if "replication" in stripped.lower():
                    in_replication_section = True
                    lines.append(line)
                    continue
                if in_replication_section:
                    lines.append(line)
                    continue
                parts = stripped.split()
                if len(parts) >= 4 and parts[0] == "local" and parts[1] == "all" and parts[2] == "all" and parts[3] == "peer":
                    line = line.replace("peer", "ident")
                    lines.append(line)
                elif len(parts) >= 5 and parts[0] == "host" and parts[1] == "all" and parts[2] == "all" and "127.0.0.1/32" in parts[3]:
                    line = line.replace("ident", "scram-sha-256")
                    lines.append(line)
                    lines.append(f"host    all             all             {network}            scram-sha-256\n")
                else:
                    lines.append(line)
        hba_path.write_text("".join(lines))
        logger.info("  ✓ pg_hba.conf configured")

        # ── Step 5: start service ─────────────────────────────────────────────
        logger.info("  ➜ systemctl start + enable postgresql.service")
        for cmd, desc in [
            (["systemctl", "start",  "postgresql.service"], "start postgresql"),
            (["systemctl", "enable", "postgresql.service"], "enable postgresql"),
        ]:
            if not _run(cmd, logger, desc):
                return False
        logger.info("  ✓ PostgreSQL service started and enabled")

        # ── Step 6: database users ────────────────────────────────────────────
        users = ["postgres", "tom", "jerry"]
        logger.info(f"  ➜ configure users: {', '.join(users)}")
        for user in users:
            if user == "postgres":
                sql = f"ALTER USER {user} WITH PASSWORD '{password}';"
            else:
                sql = f"CREATE ROLE {user} PASSWORD '{password}' SUPERUSER CREATEDB CREATEROLE INHERIT LOGIN;"
            if not _run(
                ["sudo", "-u", "postgres", "psql", "-d", "postgres", "-U", "postgres", "-c", sql],
                logger, f"configure user {user}", timeout=60
            ):
                return False
        logger.info(f"  ✓ Users configured: {', '.join(users)}")

        # ── Step 7: extensions ────────────────────────────────────────────────
        logger.info('  ➜ CREATE EXTENSION "uuid-ossp"')
        if not _run(
            ["sudo", "-u", "postgres", "psql", "-d", "postgres", "-U", "postgres",
             "-c", 'CREATE EXTENSION "uuid-ossp";'],
            logger, 'create extension "uuid-ossp"', timeout=60
        ):
            return False
        logger.info('  ✓ Extension "uuid-ossp" created')

        logger.info(f"✓ PostgreSQL 16 deployment completed — users: {', '.join(users)}, network: {network}, SSL: on, auth: scram-sha-256")
        return True

    except subprocess.TimeoutExpired as e:
        logger.error(f"✗ Command timeout: {e}")
        return False
    except Exception as e:
        logger.error(f"✗ PostgreSQL deployment error: {e}")
        return False


# Made with Bob

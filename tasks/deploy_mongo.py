#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MongoDB Deployment Task
Handles MongoDB installation and configuration on local machine (raptor)
"""

import re
import sys
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import execute_local_command, execute_commands, execute_mongo_js, modify_config_file, write_file, ConfigLoader


def _header(logger, title: str):
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)


def _mongo_error(result, msg, logger) -> bool:
    logger.error(f"✗ {msg}")
    if result.get('stderr'):
        logger.error(f"  MongoDB error: {result['stderr']}")
    if result.get('stdout'):
        logger.error(f"  MongoDB output: {result['stdout']}")
    return False


def create_mongodb_repo_file(logger, verbose: bool = True) -> bool:
    _header(logger, "Creating MongoDB Enterprise repository file")

    repo_file_path = "/etc/yum.repos.d/mongodb-enterprise-8.3.repo"
    repo_content = """[mongodb-enterprise-8.3]
name=MongoDB Enterprise Repository
baseurl=https://repo.mongodb.com/yum/redhat/9/mongodb-enterprise/8.3/$basearch/
gpgcheck=1
enabled=1
gpgkey=https://pgp.mongodb.com/server-8.0.asc
"""
    try:
        logger.info(f"  ➜ write {repo_file_path}")
        write_file(repo_file_path, repo_content)
        logger.info(f"  ✓ Created {repo_file_path}")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to create MongoDB repository file: {e}")
        return False


def create_mongodb_admin_user(password: str, logger, verbose: bool = True) -> bool:
    _header(logger, "Creating MongoDB admin user")

    escaped_password = password.replace("'", "\\'").replace('"', '\\"')
    js_commands = f"""db.createUser({{
  user: "admin",
  pwd: "{escaped_password}",
  roles: [ {{ role: "root", db: "admin" }} ]
}})
"""
    logger.info("  ➜ db.createUser(admin, root@admin)")
    result = execute_mongo_js(
        js_commands=js_commands,
        database="admin",
        logger=logger,
        verbose=verbose
    )
    if result['rc'] != 0:
        return _mongo_error(result, "Failed to create MongoDB admin user", logger)

    logger.info("  ➜ db.getUsers()")
    verify_result = execute_mongo_js(js_commands="db.getUsers()", database="admin", logger=logger, verbose=verbose)
    if verify_result['rc'] == 0:
        logger.info(f"  Users in admin db: {verify_result['stdout'].strip()}")

    logger.info("✓ MongoDB admin user created")
    return True


def enable_mongodb_authorization(logger, verbose: bool = True) -> bool:
    _header(logger, "Enabling MongoDB authorization")

    mongod_conf_path = "/etc/mongod.conf"
    security_config = "security:\n  authorization: enabled\n"

    logger.info(f"  ➜ append security.authorization: enabled → {mongod_conf_path}")
    success = modify_config_file(
        path=mongod_conf_path,
        content=security_config,
        mode='append',
        backup=True,
        logger=logger
    )
    if not success:
        logger.error(f"✗ Failed to enable MongoDB authorization in {mongod_conf_path}")
        return False

    logger.info("✓ MongoDB authorization enabled")
    return True


def create_mongo_env_file(password: str, logger, verbose: bool = True) -> bool:
    _header(logger, "Creating MongoDB environment file")

    encoded_password = quote_plus(password)
    mongo_env_path = "/root/.mongo_env"
    mongo_env_content = f"export MONGO_URI='mongodb://admin:{encoded_password}@localhost:27017/admin'\n"

    try:
        logger.info(f"  ➜ write {mongo_env_path}")
        write_file(mongo_env_path, mongo_env_content)

        logger.info(f"  ➜ chmod 600 {mongo_env_path}")
        result = execute_local_command(f"chmod 600 {mongo_env_path}", logger, verbose=False)
        if result['rc'] != 0:
            logger.error(f"✗ Failed to set permissions on {mongo_env_path}")
            return False
        logger.info(f"  ✓ Created {mongo_env_path} (mode 600)")

        bashrc_path = "/root/.bashrc"
        logger.info(f"  ➜ append .mongo_env sourcing → {bashrc_path}")
        append_cmd = f"""cat >> {bashrc_path} << 'EOF'

# Load MongoDB environment variables
if [ -f /root/.mongo_env ]; then
    . /root/.mongo_env
fi
EOF"""
        append_result = execute_local_command(append_cmd, logger, verbose=False)
        if append_result['rc'] == 0:
            logger.info(f"  ✓ Updated {bashrc_path}")
        else:
            logger.debug(f"  Could not update {bashrc_path} (non-critical)")

        return True
    except Exception as e:
        logger.error(f"✗ Failed to create MongoDB environment file: {e}")
        return False


def import_mongodb_sample_data(logger, verbose: bool = True) -> bool:
    _header(logger, "Importing MongoDB sample data")

    archive_path = "/opt/guardium_tz_bootcamp_automation/upload/source_files/mongo/sampledata.archive.gz"

    logger.info(f"  ➜ test -f {archive_path}")
    check_result = execute_local_command(f"test -f {archive_path}", logger, verbose)
    if check_result['rc'] != 0:
        logger.warning(f"  Sample data archive not found: {archive_path} — skipping")
        return True

    quiet_flag = "--quiet" if not verbose else ""
    full_command = (
        f"bash -c '. /root/.mongo_env && gunzip -c {archive_path} "
        f'| mongorestore --archive --uri="$MONGO_URI" --nsInclude="*" {quiet_flag}\''
    )
    logger.info(f"  ➜ mongorestore --archive {archive_path}")
    result = execute_local_command(full_command, logger, verbose=verbose)
    if result['rc'] != 0:
        return _mongo_error(result, "Failed to import MongoDB sample data", logger)

    logger.info("✓ Sample data imported")
    return True


def configure_ssl_for_mongo(logger, verbose: bool = True) -> bool:
    _header(logger, "Configuring SSL/TLS for MongoDB")

    commands = [
        "mkdir -p /var/lib/mongo/cert",
        'openssl req -x509 -newkey rsa:4096 -keyout /var/lib/mongo/cert/ca.key -out /var/lib/mongo/cert/ca.pem -sha256 -days 3650 -nodes -subj "/C=PL/ST=Lubuskie/L=Nowa Sol/O=Training/OU=Demo/CN=MongoCA" -addext "basicConstraints=critical,CA:TRUE"',
        'openssl req -newkey rsa:4096 -keyout /var/lib/mongo/cert/server.key -out /var/lib/mongo/cert/server.csr -nodes -subj "/C=PL/ST=Lubuskie/L=Nowa Sol/O=Training/OU=Demo/CN=localhost"',
        'bash -c \'openssl x509 -req -in /var/lib/mongo/cert/server.csr -CA /var/lib/mongo/cert/ca.pem -CAkey /var/lib/mongo/cert/ca.key -CAcreateserial -out /var/lib/mongo/cert/server.crt -days 3650 -sha256 -extfile <(printf "subjectAltName=DNS:localhost,IP:127.0.0.1\\nbasicConstraints=CA:FALSE\\nkeyUsage=digitalSignature,keyEncipherment\\nextendedKeyUsage=serverAuth")\'',
        "cat /var/lib/mongo/cert/server.key /var/lib/mongo/cert/server.crt > /var/lib/mongo/cert/both.pem",
        "chown -R mongod:mongod /var/lib/mongo/cert",
        "chmod 600 /var/lib/mongo/cert/*",
    ]
    logger.info("  ➜ openssl: generate CA + server cert → /var/lib/mongo/cert/")
    if not execute_commands(commands, logger, verbose):
        logger.error("✗ Failed to create SSL certificates")
        return False
    logger.info("  ✓ SSL certificates created")

    conf = Path("/etc/mongod.conf")
    logger.info(f"  ➜ patch {conf}: bindIp 0.0.0.0 + TLS block after port")
    lines = []
    tls_added = False
    with conf.open() as f:
        for line in f:
            if re.match(r"^\s*bindIp\s*:", line):
                line = re.sub(r"127\.0\.0\.1", "0.0.0.0", line)
            lines.append(line)
            if re.match(r"^\s*port\s*:", line) and not tls_added:
                lines += [
                    "  tls:\n",
                    "    mode: allowTLS\n",
                    "    certificateKeyFile: /var/lib/mongo/cert/both.pem\n",
                    "    CAFile: /var/lib/mongo/cert/ca.pem\n",
                    "    allowConnectionsWithoutCertificates: true\n",
                ]
                tls_added = True
    conf.write_text("".join(lines))
    logger.info(f"  ✓ {conf} updated")

    logger.info("  ➜ systemctl restart mongod")
    if not execute_commands(["systemctl restart mongod"], logger, verbose):
        logger.error("✗ Failed to restart MongoDB after TLS config")
        return False

    logger.info("✓ SSL/TLS configured for MongoDB")
    return True


def deploy_mongo_on_raptor(config, logger, verbose: bool = True, **kwargs) -> bool:
    _header(logger, "MongoDB deployment on raptor")

    password = config.get_custom_variable('pwd')

    if not create_mongodb_repo_file(logger, verbose):
        return False

    commands = [
        "dnf install -y mongodb-enterprise-database mongodb-enterprise-tools mongodb-mongosh-shared-openssl3 mongodb-enterprise",
        "systemctl enable mongod",
        "systemctl start mongod",
        "sleep 5",
    ]
    logger.info("  ➜ dnf install mongodb-enterprise + enable/start mongod")
    if not execute_commands(commands, logger, verbose):
        logger.error("✗ MongoDB installation failed")
        return False

    logger.info("  ➜ systemctl is-active mongod")
    verify_result = execute_local_command("systemctl is-active mongod", logger, verbose=False)
    if verify_result['rc'] != 0:
        logger.error("✗ MongoDB service is not running after install")
        return False
    logger.info("  ✓ mongod is active")

    if not create_mongodb_admin_user(password, logger, verbose):
        return False

    if not enable_mongodb_authorization(logger, verbose):
        return False

    commands = ["systemctl restart mongod", "sleep 5"]
    logger.info("  ➜ systemctl restart mongod (apply authorization)")
    if not execute_commands(commands, logger, verbose):
        logger.error("✗ MongoDB restart failed")
        return False
    logger.info("  ✓ mongod restarted")

    if not create_mongo_env_file(password, logger, verbose):
        return False

    if not import_mongodb_sample_data(logger, verbose):
        return False

    if not configure_ssl_for_mongo(logger, verbose):
        return False

    logger.info("✓ MongoDB deployment completed")
    return True


# Made with Bob

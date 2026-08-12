#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MySQL Deployment Task
Handles MySQL installation and configuration on local machine (raptor)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from core import execute_local_command, execute_commands, execute_mysql_sql, write_file, ConfigLoader


def _header(logger, title: str):
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)


def _mysql_error(result, msg, logger) -> bool:
    logger.error(f"✗ {msg}")
    if result.get('stderr'):
        logger.error(f"  MySQL error: {result['stderr']}")
    return False


def set_mysql_root_password(new_password: str, logger, verbose: bool = True) -> bool:
    _header(logger, "Setting MySQL root password")

    logger.info("  ➜ grep temporary password /var/log/mysqld.log")
    result = execute_local_command(
        "grep 'temporary password' /var/log/mysqld.log | sed 's/.*: //'",
        logger, verbose
    )
    if result['rc'] != 0:
        return _mysql_error(result, "Failed to extract temporary password from mysqld.log", logger)

    temp_password = result['stdout'].strip()
    if not temp_password:
        logger.error("✗ Could not parse temporary password from log")
        return False
    logger.info("  ✓ Temporary password extracted")

    logger.info("  ➜ ALTER USER root@localhost / CREATE USER root@'%' / GRANT ALL / FLUSH PRIVILEGES")
    sql = f"""ALTER USER 'root'@'localhost' IDENTIFIED BY '{new_password}';
CREATE USER IF NOT EXISTS 'root'@'%' IDENTIFIED BY '{new_password}';
GRANT ALL PRIVILEGES ON *.* TO 'root'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;
"""
    result = execute_mysql_sql(
        sql_commands=sql,
        username="root",
        password=temp_password,
        additional_options="--connect-expired-password",
        logger=logger,
        verbose=verbose
    )
    if result['rc'] != 0:
        return _mysql_error(result, "Failed to change MySQL root password", logger)

    logger.info("✓ MySQL root password set, root@'%' created")
    return True


def create_mysql_superadmins(password: str, logger, verbose: bool = True) -> bool:
    _header(logger, "Creating MySQL superadmin users (tom, jerry)")

    logger.info("  ➜ CREATE USER tom@'%', jerry@'%' / GRANT ALL / FLUSH PRIVILEGES")
    sql = f"""CREATE USER IF NOT EXISTS 'tom'@'%' IDENTIFIED BY '{password}';
CREATE USER IF NOT EXISTS 'jerry'@'%' IDENTIFIED BY '{password}';
GRANT ALL PRIVILEGES ON *.* TO 'tom'@'%' WITH GRANT OPTION;
GRANT ALL PRIVILEGES ON *.* TO 'jerry'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;
"""
    result = execute_mysql_sql(
        sql_commands=sql,
        username="root",
        password=password,
        logger=logger,
        verbose=verbose
    )
    if result['rc'] != 0:
        return _mysql_error(result, "Failed to create MySQL superadmin users", logger)

    logger.info("✓ Superadmin users tom, jerry created")
    return True


def create_mysql_config_file(password: str, logger, verbose: bool = True) -> bool:
    _header(logger, "Creating ~/.my.cnf configuration file")

    my_cnf_path = os.path.join(os.path.expanduser("~"), ".my.cnf")
    my_cnf_content = f"[client]\nuser=root\npassword={password}\n"

    try:
        write_file(my_cnf_path, my_cnf_content)
        os.chmod(my_cnf_path, 0o600)
        logger.info(f"✓ Created {my_cnf_path} (mode 600)")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to create .my.cnf: {e}")
        return False


def deploy_mysql_on_raptor(config, logger, verbose: bool = True) -> bool:
    _header(logger, "MySQL deployment on raptor")

    password = config.get_custom_variable('pwd')

    logger.info("  ➜ Installing mysql-community-server via dnf")
    commands = [
        "rpm --import https://repo.mysql.com/RPM-GPG-KEY-mysql-2023",
        "dnf install -y https://dev.mysql.com/get/mysql84-community-release-el9-4.noarch.rpm",
        "dnf config-manager --disable mysql-9.7-lts-community",
        "dnf config-manager --disable mysql-tools-9.7-lts-community",
        "dnf config-manager --enable mysql-8.4-lts-community",
        "dnf config-manager --enable mysql-tools-8.4-lts-community",
        "dnf install -y mysql-community-server",
        "systemctl start mysqld",
        "systemctl enable mysqld",
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("✗ MySQL installation failed")
        return False
    logger.info("  ✓ mysqld installed and started")

    if not set_mysql_root_password(password, logger, verbose):
        return False

    if not create_mysql_config_file(password, logger, verbose):
        return False

    if not create_mysql_superadmins(password, logger, verbose):
        return False

    _header(logger, "Importing salesDB database")
    logger.info("  ➜ CREATE DATABASE salesDB + import salesDB.sql")
    commands = [
        'mysql -u root -e "CREATE DATABASE IF NOT EXISTS salesDB"',
        "mysql -u root salesDB < /opt/guardium_tz_bootcamp_automation/upload/source_files/mysql/salesDB.sql",
    ]
    if not execute_commands(commands, logger, verbose):
        logger.error("✗ Failed to import salesDB")
        return False

    logger.info("✓ MySQL deployment completed")
    return True


# Made with Bob

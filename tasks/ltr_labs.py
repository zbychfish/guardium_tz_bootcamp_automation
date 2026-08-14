#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import traceback

from core.appliance_client import ApplianceClient
from core.appliance_operations import (
    _get_appliance_connection_params,
    setup_appnode as _setup_appnode,
)
from core.guardium_rest_api import import_definitions_files
from core.logger import get_logger
from core.utils import execute_local_command

logger = get_logger(__name__)

def _header(logger, title: str) -> None:
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)

def _require(logger, **kwargs) -> bool:
    for name, value in kwargs.items():
        if not value:
            logger.error(f"{name} is required")
            return False
    return True

# ---------------------------------------------------------------------------

def setup_minio_on_raptor(
    config,
    logger,
    verbose: bool = False,
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, "SETUP MINIO ON RAPTOR")

    raptor_ip = config.get_machine_ip("raptor", use_private=True)
    if not raptor_ip:
        logger.error("Could not determine raptor IP address")
        return False

    pwd = config.get_custom_variable("pwd")
    if not _require(logger, pwd=pwd):
        return False

    pre_cmds = [
        "mkdir -p /home/minio/ca/{certs,private,newcerts}",
        "chmod 700 /home/minio/ca/private",
        "touch /home/minio/ca/index.txt",
        "echo 1000 > /home/minio/ca/serial",
        "mkdir -p /home/minio/certs/CAs",
        "openssl genrsa -out /home/minio/ca/private/ca.key 4096",
        'openssl req -x509 -new -nodes -key /home/minio/ca/private/ca.key -sha256 -days 3650 -subj "/CN=MinIO-Root-CA" -out /home/minio/ca/certs/ca.crt',
        "cp /home/minio/ca/certs/ca.crt /home/minio/certs/CAs/",
        "cp /home/minio/ca/certs/ca.crt /etc/pki/ca-trust/source/anchors/",
        "update-ca-trust",
        "openssl genrsa -out /home/minio/certs/private.key 4096 && chmod 600 /home/minio/certs/private.key",
        f'openssl req -new -key /home/minio/certs/private.key -out /home/minio/minio.csr -subj "/CN=minio.demo.guardium" -addext "subjectAltName=DNS:raptor.demo.guardium,IP:{raptor_ip}"',
        "openssl x509 -req -in /home/minio/minio.csr -CA /home/minio/ca/certs/ca.crt -CAkey /home/minio/ca/private/ca.key -CAcreateserial -out /home/minio/certs/public.crt -days 3600 -sha256 -copy_extensions copy",
        "dnf -y install podman",
        "mkdir -p /home/data/minio",
        "chmod 700 /home/data/minio",
        "curl -L -o /usr/local/bin/mc https://dl.min.io/client/mc/release/linux-amd64/mc",
        "chmod +x /usr/local/bin/mc",
    ]
    podman_cmd = (
        f"podman run -d --name minio --restart=always "
        f"-p 0.0.0.0:9000:9000 -p 0.0.0.0:9001:9001 "
        f"-v /home/data/minio:/data:Z "
        f"-v /home/minio/certs:/root/.minio/certs:Z "
        f"-e MINIO_ROOT_USER=minioadmin "
        f"-e MINIO_ROOT_PASSWORD='{pwd}' "
        f"quay.io/minio/minio server /data --console-address ':9001'"
    )
    post_cmds = [
        f"/usr/local/bin/mc alias set myminio https://raptor.demo.guardium:9000 minioadmin '{pwd}'",
        "/usr/local/bin/mc mb myminio/guardium-ltr",
    ]

    for cmd in pre_cmds:
        result = execute_local_command(cmd, logger=logger, verbose=verbose)
        if result["rc"] != 0:
            logger.error(f"✗ Failed: {cmd}\n{result['stderr']}")
            return False

    logger.info("➜ Starting MinIO container...")
    result = execute_local_command(podman_cmd, logger=logger, verbose=verbose)
    if result["rc"] != 0:
        logger.error(f"✗ Failed to start MinIO container\n{result['stderr']}")
        return False

    logger.info("⌛ Waiting 10s for MinIO to start...")
    time.sleep(10)

    for cmd in post_cmds:
        result = execute_local_command(cmd, logger=logger, verbose=verbose)
        if result["rc"] != 0:
            logger.error(f"✗ Failed: {cmd}\n{result['stderr']}")
            return False

    logger.info("✓ MinIO certificates prepared and MinIO started on raptor")
    return True

def setup_appnode(
    config,
    logger,
    verbose: bool = False,
    appliance_name: str = None,
    retry_interval: int = 60,
    max_retries: int = 10,
    debug: bool = False,
    **kwargs
) -> bool:
    if not _require(logger, appliance_name=appliance_name):
        return False
    return _setup_appnode(
        config=config, logger=logger,
        appliance_name=appliance_name,
        retry_interval=retry_interval, max_retries=max_retries,
        debug=debug,
    )

def enable_ltr_on_appnode(
    config,
    logger,
    verbose: bool = False,
    appliance_name: str = None,
    debug: bool = False,
    **kwargs) -> bool:

    if not _require(logger, appliance_name=appliance_name):
        return False

    _header(logger, f"ENABLE LTR ON APPNODE: {appliance_name}")

    params = _get_appliance_connection_params(config, logger, appliance_name)
    if not params:
        return False

    try:
        client = ApplianceClient(
            host=params['host'], user=params['user'], password=params['password'],
            prompt_regex=params['prompt_regex'],
            initial_pattern=None, timeout=300, strip_ansi=True, debug=debug,
        )
        if not client.connect():
            logger.error(f"Failed to connect to {appliance_name}")
            return False

        steps = [
            ("store datalake install",       "Datalake installation was successful",       "install datalake"),
            ("store datalake all_in_one xxsmall", "Datalake all_in_one was brought up correctly", "configure all_in_one"),
        ]
        try:
            for cmd, expected, desc in steps:
                logger.info(f"➜ {cmd}")
                result = client.execute_command(cmd, timeout=300)
                if expected not in result:
                    logger.error(f"✗ Failed to {desc}: {result}")
                    return False
                logger.info(f"✓ {desc}")

            logger.info("➜ store datalake service start")
            client.execute_command("store datalake service start", timeout=300)

            logger.info("➜ show datalake status")
            status = client.execute_command("show datalake status", timeout=60)
            if "Datalake is running!" not in status:
                logger.error(f"✗ Datalake is not running: {status}")
                return False
            logger.info("✓ Datalake is running")
            return True

        finally:
            client.disconnect()

    except Exception as e:
        logger.error(f"✗ Error enabling LTR on appnode: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False

def import_minio_CA_certificate(
    config,
    logger,
    verbose: bool = False,
    appliance_name: str = None,
    certificate_file_path: str = "/home/minio/ca/certs/ca.crt",
    debug: bool = False,
    **kwargs) -> bool:

    if not _require(logger, appliance_name=appliance_name):
        return False
    return import_datalake_s3_certificate(
        config=config, logger=logger,
        appliance_name=appliance_name,
        certificate_file_path=certificate_file_path,
        user=kwargs.get('user'), password=kwargs.get('password'),
        prompt_regex=kwargs.get('prompt_regex'),
        debug=debug,
    )

def distribute_minio_certificate(
    config,
    logger,
    verbose: bool = False,
    appliance_name: str = "cm",
    timeout: int = 300,
    check_interval: int = 10,
    debug: bool = False,
    **kwargs) -> bool:

    return distribute_datalake_certificate(
        config=config, logger=logger,
        appliance_name=appliance_name,
        user=kwargs.get('user'), password=kwargs.get('password'),
        prompt_regex=kwargs.get('prompt_regex'),
        timeout=timeout, check_interval=check_interval,
        debug=debug,
    )

def activate_ltr(
    config,
    logger,
    verbose: bool = False,
    appliance_name: str = "cm",
    debug: bool = False,
    **kwargs) -> bool:

    return _activate_ltr(
        config=config, logger=logger,
        appliance_name=appliance_name,
        user=kwargs.get('user'), password=kwargs.get('password'),
        prompt_regex=kwargs.get('prompt_regex'),
        debug=debug,
    )

def import_ltr_dashboard(
    config,
    logger,
    verbose: bool = True,
    cm_appliance: str = "cm",
    definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
    debug: bool = False,
    **kwargs) -> bool:
    
    _header(logger, "IMPORT LTR DASHBOARD ON CM")

    success = import_definitions_files(
        config=config, logger=logger,
        appliance_name=cm_appliance,
        definition_files=["exp_dashboard_ltr.sql"],
        definitions_dir=definitions_dir,
        debug=debug,
    )
    if success:
        logger.info("✓ LTR dashboard imported successfully")
    return success

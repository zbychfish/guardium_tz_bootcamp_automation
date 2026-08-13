#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import traceback
from typing import Optional
from core.logger import get_logger
from core.appliance_config_loader import ApplianceConfigLoader
from core.appliance_operations import copy_files_to_appliance
from core.guardium_rest_api import create_guardium_api
from core.utils import execute_local_command

logger = get_logger(__name__)


def _header(logger, title: str) -> None:
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)


def import_gim_modules(
    config,
    logger,
    verbose: bool = False,
    appliance_name: Optional[str] = None,
    demo_user: str = "demo",
    demo_password: Optional[str] = None,
    gim_directory: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/agents/gim",
    gim_target_dir: str = "/var/dump",
    debug: bool = False) -> bool:

    if not appliance_name:
        logger.error("appliance_name is required")
        return False

    _header(logger, "IMPORT GIM MODULES")

    shell_dir = "/opt/guardium_tz_bootcamp_automation/upload/source_files/agents/shell/"
    logger.info(f"➜ chmod +x {shell_dir}*")
    result = execute_local_command(f"chmod +x {shell_dir}*", logger=logger, verbose=verbose)
    if result['rc'] != 0:
        logger.warning(f"⚠ chmod +x failed (rc={result['rc']}): {result['stderr']}")

    logger.info(f"➜ copy *.gim → {appliance_name}:{gim_target_dir}")
    if not copy_files_to_appliance(
        config=config, logger=logger, appliance_name=appliance_name,
        source_dir=gim_directory, file_pattern="*.gim",
        target_dir=gim_target_dir, owner="tomcat:tomcat", debug=debug
    ):
        return False

    if not demo_password:
        demo_password = config.get_custom_variable('pwd')
    if not demo_password:
        logger.error("demo password required — set 'pwd' in custom_variables")
        return False

    try:
        api = create_guardium_api(config, logger, appliance_name)
        logger.info(f"➜ get_token {demo_user}")
        api.get_token(username=demo_user, password=demo_password)
        logger.info("✓ authenticated")

        logger.info("➜ get_gim_package *.gim")
        response = api.get_gim_package(filename="*.gim")
        if debug:
            logger.info(f"  response: {response}")
        logger.info("✓ GIM packages imported")
        return True

    except Exception as e:
        logger.error(f"✗ {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False

# Made with Bob

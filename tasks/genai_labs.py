#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import traceback

from core.appliance_client import ApplianceClient
from core.appliance_config_loader import ApplianceConfigLoader


def _header(logger, title: str) -> None:
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)


def create_gdp_mcp_api_key(
    config,
    logger,
    verbose: bool = False,
    appliance_name: str = "appnode2",
    key_name: str = "gdp_mcp",
    debug: bool = False,
    **kwargs) -> bool:

    _header(logger, f"CREATE API KEY: {key_name}")

    loader = ApplianceConfigLoader(config_loader=config)
    appliance_config = loader.get_appliance(appliance_name)
    if not appliance_config:
        logger.error(f"✗ Appliance '{appliance_name}' not found")
        return False

    cli_pwd = config.get_custom_variable('cli_pwd')
    if not cli_pwd:
        logger.error("✗ cli_pwd not found in custom_variables")
        return False

    appliance_type = appliance_config.get('type', 'appnode')
    client = ApplianceClient(
        host=appliance_config.get('ip'),
        user=loader.get_default_user(appliance_type),
        password=cli_pwd,
        prompt_regex=loader.get_default_prompt(appliance_type, configured=True),
        timeout=120,
        strip_ansi=True,
        debug=debug,
    )

    try:
        if not client.connect():
            logger.error(f"✗ Failed to connect to {appliance_name}")
            return False

        logger.info(f"➜ grdapi create_api_key name={key_name}")
        result = client.execute_command(f"grdapi create_api_key name={key_name}", timeout=60)
        if debug:
            logger.info(f"  output: {result}")

        api_key = None
        for line in result.splitlines():
            ls = line.strip()
            if ls.startswith('Encoded API key:'):
                api_key = ls.split('Encoded API key:', 1)[1].strip()
                break

        if not api_key:
            logger.error(f"✗ Failed to extract API key from response: {result}")
            return False

        logger.info(f"✓ API key created: {api_key[:10]}...")
        key_file = config.config_file.parent.parent / ".genai_api_key"
        key_file.write_text(api_key, encoding='utf-8')
        logger.info(f"✓ API key saved to: {key_file}")
        return True

    except Exception as e:
        logger.error(f"✗ {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        client.disconnect()

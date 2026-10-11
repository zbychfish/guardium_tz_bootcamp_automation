#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from core.appliance_operations import (
    _get_appliance_connection_params,
    setup_appnode as _setup_appnode,
)
from core.logger import get_logger

logger = get_logger(__name__)

def _require(logger, **kwargs) -> bool:
    for name, value in kwargs.items():
        if not value:
            logger.error(f"{name} is required")
            return False
    return True

def setup_appnode(
    config,
    logger,
    verbose: bool = False,
    appliance_name: str = None,
    retry_interval: int = 60,
    max_retries: int = 10,
    debug: bool = False,
    **kwargs) -> bool:

    if not _require(logger, appliance_name=appliance_name):
        return False
    return _setup_appnode(
        config=config, logger=logger,
        appliance_name=appliance_name,
        retry_interval=retry_interval, max_retries=max_retries,
        debug=debug,
    )

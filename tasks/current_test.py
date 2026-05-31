#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Current Test - Diagnostic Functions
Temporary file for testing and debugging specific functionality
"""

from typing import Optional


def current_test(
    config,
    logger,
    verbose: bool = True,
    appliance_name: Optional[str] = None,
    **kwargs
) -> bool:
    """
    Test stage for disabling default accounts only
    Temporary diagnostic function to isolate account disabling logic
    """
    if not appliance_name:
        logger.error("appliance_name is required")
        return False
    
    logger.info("=" * 80)
    logger.info(f"TEST: Disabling default accounts on {appliance_name}")
    logger.info("=" * 80)
    
    try:
        from core.guardium_rest_api import create_guardium_api
        
        api = create_guardium_api(config, logger, appliance_name)
        
        logger.info("\n➜ Getting current user list...")
        users = api.get_users()
        logger.info(f"Found {len(users)} users")
        
        for u in users:
            status = "DISABLED" if u.get("disabled") == "true" else "ACTIVE"
            logger.info(f"  {u['user_name']:12} | {status}")
        
        logger.info("\n➜ Disabling guardium account...")
        result = api.update_user(username='guardium', disabled=True)
        logger.info(f"API response: {result}")
        logger.info("✓ guardium account disabled")
        
        logger.info("\n➜ Disabling guardcli accounts...")
        for cli_num in range(2, 10):
            username = f"guardcli{cli_num}"
            result = api.update_user(username=username, disabled=True)
            logger.info(f"API response for {username}: {result}")
            logger.info(f"✓ {username} account disabled")
        
        logger.info("\n➜ Verifying final state...")
        users = api.get_users()
        logger.info("Final user status:")
        for u in users:
            status = "DISABLED" if u.get("disabled") == "true" else "ACTIVE"
            logger.info(f"  {u['user_name']:12} | {status}")
        
        logger.info("=" * 80)
        logger.info("TEST COMPLETED")
        logger.info("=" * 80)
        
        return True
        
    except Exception as e:
        logger.error(f"Error in test: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

# Made with Bob

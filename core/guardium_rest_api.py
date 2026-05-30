#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Guardium REST API - class for communication with Guardium via REST API
Adapted for guardium_tz_bootcamp_automation project
"""

import os
import requests
from typing import Optional
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class GuardiumRestAPI:
    """Class for communication with Guardium via REST API"""
    
    def __init__(
        self,
        base_url: str,
        client_id: str = "BOOTCAMP",
        client_secret: Optional[str] = None,
        verify_ssl: bool = False
    ):
        """
        Initializes the REST API client.
        
        Args:
            base_url: Base API URL (e.g., 'https://10.10.9.219')
            client_id: OAuth client ID (default 'BOOTCAMP')
            client_secret: OAuth client secret (required)
            verify_ssl: Whether to verify SSL certificate (default False)
        """
        self.base_url = base_url.rstrip('/')
        self.client_id = client_id
        self.verify_ssl = verify_ssl
        
        if not client_secret:
            raise ValueError("client_secret is required")
        
        self.client_secret = client_secret
        self.access_token: Optional[str] = None
    
    def get_token(self, username: str, password: str) -> str:
        """
        Retrieves access token from Guardium OAuth.
        
        Args:
            username: Guardium username
            password: Guardium user password
        
        Returns:
            Access token
        
        Raises:
            requests.exceptions.RequestException: In case of HTTP error
            KeyError: If response does not contain access_token
        """
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': 'password',
            'username': username,
            'password': password
        }
        
        url = f'{self.base_url}/oauth/token'
        response = requests.post(url, data=data, verify=self.verify_ssl)
        response.raise_for_status()
        
        token_data = response.json()
        access_token = token_data['access_token']
        self.access_token = access_token
        
        return access_token
    
    def get_headers(self) -> dict:
        """
        Returns HTTP headers with authorization token.
        
        Returns:
            Dictionary with headers
        
        Raises:
            RuntimeError: If token has not been retrieved yet
        """
        if not self.access_token:
            raise RuntimeError("Access token not available. Call get_token() first.")
        
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
    
    def get_users(self) -> dict:
        """
        Retrieves list of users from Guardium.
        
        Returns:
            Dictionary with user data
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        """
        url = f'{self.base_url}/restAPI/user'
        headers = self.get_headers()
        
        response = requests.get(url, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def create_user(
        self,
        username: str,
        password: str,
        confirm_password: str,
        first_name: str,
        last_name: str,
        email: Optional[str] = None,
        country: Optional[str] = None,
        disabled: bool = False,
        disable_pwd_expiry: bool = False
    ) -> dict:
        """
        Creates a new user in Guardium.
        
        Args:
            username: Username (required)
            password: Password (required, min. 8 characters, uppercase/lowercase letter, digit, special character)
            confirm_password: Password confirmation (required, must match password)
            first_name: First name (required)
            last_name: Last name (required)
            email: Email address (optional)
            country: ISO 3166 2-letter country code, e.g., 'US', 'PL' (optional)
            disabled: Whether user is disabled (default False)
            disable_pwd_expiry: Whether to disable password change requirement on first login (default False)
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
            ValueError: If password != confirm_password
        """
        if password != confirm_password:
            raise ValueError("Password and confirmPassword must match")
        
        url = f'{self.base_url}/restAPI/user'
        headers = self.get_headers()
        
        data = {
            'userName': username,
            'password': password,
            'confirmPassword': confirm_password,
            'firstName': first_name,
            'lastName': last_name,
            'disabled': 1 if disabled else 0,
            'disablePwdExpiry': 1 if disable_pwd_expiry else 0
        }
        
        # Add optional parameters
        if email:
            data['email'] = email
        if country:
            data['country'] = country
        
        response = requests.post(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def set_user_roles(self, username: str, roles: str) -> dict:
        """
        Assigns or updates user roles in Guardium.
        
        Args:
            username: Username (required)
            roles: Role or roles to assign (required)
                   For multiple roles use comma without spaces, e.g., "role1,role2,role3"
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        """
        url = f'{self.base_url}/restAPI/user_roles'
        headers = self.get_headers()
        
        data = {
            'userName': username,
            'roles': roles
        }
        
        response = requests.put(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()


def create_guardium_api(config, logger, appliance_name: str = "cm01") -> 'GuardiumRestAPI':
    """
    Create GuardiumRestAPI instance using appliance configuration
    
    Args:
        config: ConfigLoader instance
        logger: Logger instance
        appliance_name: Name of appliance from config/appliances.yaml (default: cm01)
    
    Returns:
        GuardiumRestAPI instance
    
    Example:
        from core.guardium_rest_api import create_guardium_api
        
        api = create_guardium_api(config, logger, "cm01")
        token = api.get_token(username='accessmgr', password='password')
        users = api.get_users()
    """
    import os
    from pathlib import Path
    from .appliance_config_loader import ApplianceConfigLoader
    
    # Get path to appliances.yaml file
    appliances_file = config.config_file.parent / "appliances.yaml"
    
    # Load appliance configuration
    appliance_loader = ApplianceConfigLoader(appliances_file)
    appliance_config = appliance_loader.get_appliance(appliance_name)
    
    if not appliance_config:
        raise ValueError(f"Appliance '{appliance_name}' not found in config/appliances.yaml")
    
    appliance_ip = appliance_config.get('ip')
    if not appliance_ip:
        raise ValueError(f"IP address not found for appliance '{appliance_name}'")
    
    # Get CLIENT_SECRET from .client_secret file, custom_variables, or environment
    client_secret = None
    
    # Try to read from .client_secret file first (in project root - parent of config dir)
    project_root = config.config_file.parent.parent
    secret_file = project_root / ".client_secret"
    if secret_file.exists():
        try:
            with open(secret_file, 'r') as f:
                client_secret = f.read().strip()
            logger.info("Using CLIENT_SECRET from .client_secret file")
        except Exception as e:
            logger.warning(f"Failed to read .client_secret file: {e}")
    
    # Try to get from custom_variables if not found in file
    if not client_secret:
        custom_vars = config.get_custom_variables()
        if custom_vars and 'client_secret' in custom_vars:
            client_secret = custom_vars['client_secret']
            logger.info("Using CLIENT_SECRET from custom_variables")
    
    # Try environment variable as last resort
    if not client_secret:
        client_secret = os.getenv('CLIENT_SECRET')
        if client_secret:
            logger.info("Using CLIENT_SECRET from environment variable")
    
    if not client_secret:
        raise ValueError(
            "CLIENT_SECRET not found. Run 'create_oauth_client' stage first, or add it to:\n"
            "  1. .client_secret file (created by create_oauth_client stage)\n"
            "  2. machines_info.json custom_variables, or\n"
            "  3. Environment variable CLIENT_SECRET"
        )
    
    # Create base URL
    base_url = f"https://{appliance_ip}"
    
    logger.info(f"Creating Guardium REST API client for {appliance_name} ({appliance_ip})")
    
    # Create and return API instance
    api = GuardiumRestAPI(
        base_url=base_url,
        client_id="BOOTCAMP",
        client_secret=client_secret,
        verify_ssl=False
    )
    
    return api


# Made with Bob
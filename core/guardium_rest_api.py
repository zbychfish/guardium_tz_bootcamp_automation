#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Guardium REST API - class for communication with Guardium via REST API
Adapted for guardium_tz_bootcamp_automation project
"""

import os
import json
import requests
import time
from typing import Optional, Dict, Any, Callable
from functools import wraps
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def api_retry(max_retries: int = 3, retry_delay: int = 60):
    """
    Decorator for retrying API calls with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        retry_delay: Base delay in seconds between retries (default: 60)
    
    Returns:
        Decorated function with retry logic
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            logger = getattr(self, 'logger', None)
            
            for attempt in range(1, max_retries + 1):
                try:
                    return func(self, *args, **kwargs)
                except (requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout,
                        requests.exceptions.RequestException) as e:
                    
                    if attempt >= max_retries:
                        if logger:
                            logger.error(f"✗ API call failed after {max_retries} attempts: {func.__name__}")
                        raise
                    
                    if logger:
                        logger.warning(f"⚠ API call failed (attempt {attempt}/{max_retries}): {func.__name__}")
                        logger.warning(f"  Error: {str(e)}")
                        logger.info(f"⏳ Waiting {retry_delay} seconds before retry...")
                    
                    time.sleep(retry_delay)
            
            # Should not reach here due to raise in last attempt
            raise RuntimeError(f"Unexpected: retry loop completed without return or raise in {func.__name__}")
        
        return wrapper
    return decorator


class GuardiumRestAPI:
    """Class for communication with Guardium via REST API"""
    
    def __init__(
        self,
        base_url: str,
        client_id: str = "BOOTCAMP",
        client_secret: Optional[str] = None,
        verify_ssl: bool = False,
        logger=None
    ):
        """
        Initializes the REST API client.
        
        Args:
            base_url: Base API URL (e.g., 'https://10.10.9.219')
            client_id: OAuth client ID (default 'BOOTCAMP')
            client_secret: OAuth client secret (required)
            verify_ssl: Whether to verify SSL certificate (default False)
            logger: Optional logger instance for retry logging
        """
        self.base_url = base_url.rstrip('/')
        self.client_id = client_id
        self.verify_ssl = verify_ssl
        self.logger = logger
        
        if not client_secret:
            raise ValueError("client_secret is required")
        
        self.client_secret = client_secret
        self.access_token: Optional[str] = None
    
    @api_retry(max_retries=3, retry_delay=60)
    def get_token(self, username: str, password: str) -> str:
        """
        Retrieves access token from Guardium OAuth.
        Automatically retries on connection errors (3 attempts, 60s delay).
        
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
    def update_user(
        self,
        username: str,
        password: Optional[str] = None,
        confirm_password: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        email: Optional[str] = None,
        country: Optional[str] = None,
        disabled: Optional[bool] = None,
        disable_pwd_expiry: Optional[bool] = None
    ) -> dict:
        """
        Updates an existing user in Guardium.
        
        Args:
            username: Username (required)
            password: New password (optional)
            confirm_password: Password confirmation (optional, must match password if provided)
            first_name: First name (optional)
            last_name: Last name (optional)
            email: Email address (optional)
            country: ISO 3166 2-letter country code (optional)
            disabled: Whether user is disabled (optional)
            disable_pwd_expiry: Whether to disable password expiry (optional)
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
            ValueError: If password != confirm_password
        """
        if password and confirm_password and password != confirm_password:
            raise ValueError("Password and confirmPassword must match")
        
        url = f'{self.base_url}/restAPI/user'
        headers = self.get_headers()
        
        data: Dict[str, Any] = {'userName': username}
        
        if password:
            data['password'] = password
        if confirm_password:
            data['confirmPassword'] = confirm_password
        if first_name:
            data['firstName'] = first_name
        if last_name:
            data['lastName'] = last_name
        if email:
            data['email'] = email
        if country:
            data['country'] = country
        if disabled is not None:
            data['disabled'] = 1 if disabled else 0
        if disable_pwd_expiry is not None:
            data['disablePwdExpiry'] = 1 if disable_pwd_expiry else 0
        
        response = requests.put(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def get_gim_package(self, filename: str) -> dict:
        """
        Retrieves GIM (Guardium Installation Manager) package from Guardium.
        
        Args:
            filename: GIM package filename (required). Use wildcards like "*.gim" to get all packages.
        
        Returns:
            Dictionary with API response containing GIM package information
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        
        Example:
            api.get_gim_package("*.gim")  # Get all GIM packages
            api.get_gim_package("specific_package.gim")  # Get specific package
        """
        url = f'{self.base_url}/restAPI/gim_package'
        headers = self.get_headers()
        
        params = {
            'filename': filename
        }
        
        response = requests.get(url, headers=headers, params=params, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def gim_client_assign(
        self,
        client_ip: str,
        module: str,
        module_version: str
    ) -> dict:
        """
        Assigns GIM module to client.
        
        Args:
            client_ip: Client IP address (required)
            module: GIM module name (required)
            module_version: Module version (required)
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        
        Example:
            api.gim_client_assign(
                client_ip="10.10.9.100",
                module="BUNDLE-STAP",
                module_version="12.2.2.0_r123489_"
            )
        """
        url = f'{self.base_url}/restAPI/gim_client_assign'
        headers = self.get_headers()
        
        data = {
            'clientIP': client_ip,
            'module': module,
            'moduleVersion': module_version
        }
        
        response = requests.put(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def gim_client_params(
        self,
        client_ip: str,
        param_name: str,
        param_value: Optional[str] = None
    ) -> dict:
        """
        Sets GIM client parameters.
        
        Args:
            client_ip: Target client IP address (required)
            param_name: Parameter name (required)
            param_value: Parameter value (optional)
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        
        Example:
            # Set STAP parameters
            api.gim_client_params(
                client_ip="10.10.9.100",
                param_name="STAP_SQLGUARD_IP",
                param_value="10.10.9.219"
            )
            
            api.gim_client_params(
                client_ip="10.10.9.100",
                param_name="STAP_USE_TLS",
                param_value="1"
            )
        """
        url = f'{self.base_url}/restAPI/gim_client_params'
        headers = self.get_headers()
        
        data = {
            'clientIP': client_ip,
            'paramName': param_name
        }
        
        # Add optional parameter value
        if param_value is not None:
            data['paramValue'] = param_value
        
        response = requests.put(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def gim_schedule_install(
        self,
        client_ip: str,
        date: str,
        module: Optional[str] = None
    ) -> dict:
        """
        Schedules GIM module(s) installation on client.
        
        Args:
            client_ip: Client IP address (required)
            date: Installation date in format "now" or "yyyy-MM-dd HH:mm" (required)
            module: GIM module name (optional). If not provided, all modules
                   for the given client will be scheduled for installation.
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        
        Example:
            # Schedule installation immediately
            api.gim_schedule_install(
                client_ip="10.10.9.100",
                date="now"
            )
            
            # Schedule installation for specific date
            api.gim_schedule_install(
                client_ip="10.10.9.100",
                date="2026-03-27 14:30",
                module="BUNDLE-STAP"
            )
        """
        url = f'{self.base_url}/restAPI/gim_schedule_install'
        headers = self.get_headers()
        
        data = {
            'clientIP': client_ip,
            'date': date
        }
        
        # Add optional module parameter
        if module:
            data['module'] = module
        
        response = requests.put(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    def gim_list_client_modules(self, client_ip: str) -> dict:
        """
        Retrieves list of GIM modules assigned to client.
        
        Args:
            client_ip: Client IP address (required)
        
        Returns:
            Dictionary with list of GIM modules for the given client
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        
        Example:
            modules = api.gim_list_client_modules(client_ip="10.10.9.100")
        """
        url = f'{self.base_url}/restAPI/gim_list_client_modules'
        headers = self.get_headers()
        
        params = {
            'clientIP': client_ip
        }
        
        response = requests.get(url, headers=headers, params=params, verify=self.verify_ssl)
        response.raise_for_status()
        return response.json()
    
    def delete_inspection_engine(self, stap_host: str, type: str, sequence: Optional[str] = None,
                                 wait_for_response: Optional[str] = None, api_target_host: Optional[str] = None) -> dict:
        url = f'{self.base_url}/restAPI/inspection_engine'
        headers = self.get_headers()
        data: Dict[str, Any] = {'stapHost': stap_host, 'type': type}
        if sequence: data['sequence'] = sequence
        if wait_for_response: data['waitForResponse'] = wait_for_response
        if api_target_host: data['api_target_host'] = api_target_host
        response = requests.delete(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        return response.json()
    
    def create_inspection_engine(self, stap_host: str, protocol: str, client: Optional[str] = None,
                                db_install_dir: Optional[str] = None, db_user: Optional[str] = None,
                                db_version: Optional[str] = None, ktap_db_port: Optional[str] = None,
                                port_max: Optional[str] = None, port_min: Optional[str] = None,
                                proc_name: Optional[str] = None, unix_socket_marker: Optional[str] = None,
                                api_target_host: Optional[str] = None, **kwargs) -> dict:
        url = f'{self.base_url}/restAPI/inspection_engine'
        headers = self.get_headers()
        data: Dict[str, Any] = {'stapHost': stap_host, 'protocol': protocol}
        if client: data['client'] = client
        if db_install_dir: data['dbInstallDir'] = db_install_dir
        if db_user: data['dbUser'] = db_user
        if db_version: data['dbVersion'] = db_version
        if ktap_db_port: data['ktapDbPort'] = ktap_db_port
        if port_max: data['portMax'] = port_max
        if port_min: data['portMin'] = port_min
        if proc_name: data['procName'] = proc_name
        if unix_socket_marker: data['unixSocketMarker'] = unix_socket_marker
        if api_target_host: data['api_target_host'] = api_target_host
        for k, v in kwargs.items():
            if v is not None: data[k] = v
        response = requests.post(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        return response.json()
    
    def import_definitions(self, file_path: str) -> dict:
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        url = f'{self.base_url}/restAPI/import_definitions'
        headers = self.get_headers()
        
        headers_without_content_type = {k: v for k, v in headers.items() if k != 'Content-Type'}
        
        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f)}
            response = requests.post(
                url,
                files=files,
                headers=headers_without_content_type,
                verify=self.verify_ssl
            )
        
        response.raise_for_status()
        
        return response.json()
    
    def install_policy(
        self,
        policy: str,
        install_action: Optional[str] = None,
        api_target_host: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: int = 60,
        debug: bool = False
    ) -> dict:
        """
        Install policy on target host with retry logic for offline hosts.
        
        Args:
            policy: Policy name
            install_action: Install action (optional)
            api_target_host: Target host IP (optional)
            max_retries: Maximum number of retries for ErrorCode/ID 15 (default: 3)
            retry_delay: Delay in seconds between retries (default: 60)
            debug: Enable debug logging (default: False)
        
        Returns:
            dict: API response with ErrorCode/ID and ErrorMessage/Message
        
        Raises:
            Exception: If policy installation fails after all retries
        """
        import time
        
        url = f'{self.base_url}/restAPI/policy_install'
        headers = self.get_headers()
        
        data = {
            'policy': policy
        }
        
        if install_action:
            data['install_action'] = install_action
        if api_target_host:
            data['api_target_host'] = api_target_host
        
        if debug:
            print(f"DEBUG - API Call: POST {url}")
            print(f"DEBUG - Request data: {data}")
            print(f"DEBUG - Headers: {{'Authorization': '***', 'Content-Type': '{headers.get('Content-Type', 'application/json')}'}}")
        
        result = None
        for attempt in range(1, max_retries + 1):
            if debug and attempt > 1:
                print(f"DEBUG - Retry attempt {attempt}/{max_retries}")
            
            response = requests.post(url, json=data, headers=headers, verify=self.verify_ssl)
            response.raise_for_status()
            result = response.json()
            
            if debug:
                print(f"DEBUG - Response status: {response.status_code}")
                print(f"DEBUG - Response body: {result}")
            
            # Check both ErrorCode and ID (API uses different field names)
            error_code = result.get('ErrorCode') or result.get('ID', '0')
            error_message = result.get('ErrorMessage') or result.get('Message', '')
            
            if debug:
                print(f"DEBUG - Parsed error_code: {error_code}")
                print(f"DEBUG - Parsed error_message: {error_message}")
            
            # Success (ErrorCode/ID = '0')
            if error_code == '0':
                return result
            
            # ErrorCode/ID 15: Target host is not online - retry
            if error_code == '15' and attempt < max_retries:
                print(f"⚠ Attempt {attempt}/{max_retries}: Target host offline. Waiting {retry_delay}s before retry...")
                time.sleep(retry_delay)
                continue
            
            # Other errors or max retries reached - return error
            return result
        
        # Return last result (should always have a result after loop)
        return result if result else {'ErrorCode': '999', 'ErrorMessage': 'Unknown error'}

    def store_sql_credentials(
        self,
        password: str,
        stap_host: str,
        username: str,
        api_target_host: Optional[str] = None
    ) -> dict:
        url = f'{self.base_url}/restAPI/stap'
        data: Dict[str, Any] = {
            'password': password,
            'stapHost': stap_host,
            'username': username
        }
        if api_target_host:
            data['api_target_host'] = api_target_host
        response = requests.post(url, json=data, headers=self.get_headers(), verify=self.verify_ssl)
        response.raise_for_status()
        return response.json()

    def create_sql_configuration(
        self,
        db_type: str,
        instance: str,
        stap_host: str,
        username: str,
        data_pull_interval: Optional[str] = None,
        data_pull_rows: Optional[str] = None,
        timeout: Optional[str] = None,
        user_role: Optional[str] = None,
        api_target_host: Optional[str] = None
    ) -> dict:
        url = f'{self.base_url}/restAPI/create_sql_configuration'
        data: Dict[str, Any] = {
            'dbType': db_type,
            'instance': instance,
            'stapHost': stap_host,
            'username': username
        }
        if data_pull_interval:
            data['dataPullInterval'] = data_pull_interval
        if data_pull_rows:
            data['dataPullRows'] = data_pull_rows
        if timeout:
            data['timeout'] = timeout
        if user_role:
            data['userRole'] = user_role
        if api_target_host:
            data['api_target_host'] = api_target_host
        response = requests.post(url, json=data, headers=self.get_headers(), verify=self.verify_ssl)
        response.raise_for_status()
        return response.json()

    def create_kafka_cluster(
        self,
        cluster_name: str,
        member_list: str,
        apply_cruise_control: bool = False,
        api_target_host: Optional[str] = None
    ) -> dict:
        url = f'{self.base_url}/restAPI/kafka_cluster'
        data: Dict[str, Any] = {
            'clusterName': cluster_name,
            'memberList': member_list,
            'applyCruiseControl': str(apply_cruise_control).lower()
        }
        if api_target_host:
            data['api_target_host'] = api_target_host
        response = requests.post(url, json=data, headers=self.get_headers(), verify=self.verify_ssl)
        response.raise_for_status()
        return response.json()

    def create_uc_credential(
        self,
        name: str,
        credential_type: str,
        parameters: Optional[Dict[str, str]] = None,
        description: str = "",
        files_params: Optional[list] = None,
        files_paths: Optional[list] = None,
        api_target_host: Optional[str] = None
    ) -> dict:
        url = f'{self.base_url}/restAPI/ucCredential'
        credential: Dict[str, Any] = {
            'name': name,
            'credentialType': credential_type,
            'description': description
        }
        if parameters:
            credential['parameters'] = parameters
        if files_params:
            credential['files'] = files_params

        if files_paths:
            form_data = [('credential', (None, json.dumps(credential), 'application/json'))]
            for fp in files_paths:
                form_data.append(('files', (os.path.basename(fp), open(fp, 'rb'), 'application/octet-stream')))
            headers = {'Authorization': f'Bearer {self.access_token}'}
            if api_target_host:
                form_data.append(('api_target_host', (None, api_target_host)))
            response = requests.post(url, files=form_data, headers=headers, verify=self.verify_ssl)
        else:
            data: Dict[str, Any] = {'credential': json.dumps(credential)}
            if api_target_host:
                data['api_target_host'] = api_target_host
            response = requests.post(url, json=data, headers=self.get_headers(), verify=self.verify_ssl)

        response.raise_for_status()
        return response.json()

    def universal_connector_import_profiles(
        self,
        csv_path: str,
        update: bool = False,
        test_connections: bool = False,
        api_target_host: Optional[str] = None
    ) -> dict:
        url = f'{self.base_url}/restAPI/universal_connector_import_profiles'
        headers = {'Authorization': f'Bearer {self.access_token}'}
        files = {
            'uploadedfile': (os.path.basename(csv_path), open(csv_path, 'rb'), 'text/csv'),
        }
        data = {
            'update_mode': str(update).lower(),
        }
        if test_connections:
            data['TestConnections'] = str(test_connections).lower()
        if api_target_host:
            data['api_target_host'] = api_target_host
        response = requests.post(url, files=files, data=data, headers=headers, verify=self.verify_ssl)
        if response.status_code >= 400:
            if self.logger:
                self.logger.error(f"API error {response.status_code}: {response.text}")
        response.raise_for_status()
        return response.json()




def create_guardium_api(config, logger, appliance_name: str = "cm01") -> 'GuardiumRestAPI':
    """
    Create GuardiumRestAPI instance using appliance configuration
    
    Args:
        config: ConfigLoader instance
        logger: Logger instance
        appliance_name: Name of appliance from machines_info.json (default: cm)
    
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
    
    # Load appliance configuration from machines_info.json
    appliance_loader = ApplianceConfigLoader(config_loader=config)
    appliance_config = appliance_loader.get_appliance(appliance_name)
    
    if not appliance_config:
        raise ValueError(f"Appliance '{appliance_name}' not found in machines_info.json")
    
    appliance_ip = appliance_config.get('ip')
    if not appliance_ip:
        raise ValueError(f"IP address not found for appliance '{appliance_name}'")
    
    client_secret = None
    project_root = config.config_file.parent.parent
    secret_file = project_root / ".client_secret"
    
    if secret_file.exists():
        try:
            with open(secret_file, 'r') as f:
                client_secret = f.read().strip()
            logger.info("Using CLIENT_SECRET from .client_secret file")
        except Exception as e:
            logger.warning(f"Failed to read .client_secret file: {e}")
    
    if not client_secret:
        custom_vars = config.get_custom_variables()
        if custom_vars and 'client_secret' in custom_vars:
            client_secret = custom_vars['client_secret']
            logger.info("Using CLIENT_SECRET from custom_variables")
    
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
    
    base_url = f"https://{appliance_ip}:8443"
    logger.info(f"Creating Guardium REST API client for {appliance_name} ({appliance_ip}:8443)")
    
    api = GuardiumRestAPI(
        base_url=base_url,
        client_id="BOOTCAMP",
        client_secret=client_secret,
        verify_ssl=False,
        logger=logger
    )
    
    return api


# Made with Bob


def import_definitions_files(
    config,
    logger,
    appliance_name: str,
    definition_files: list,
    definitions_dir: str = "/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
    debug: bool = False
) -> bool:
    """
    Import definition files to Guardium appliance via REST API.
    
    Args:
        config: Configuration object
        logger: Logger instance
        appliance_name: Appliance name
        definition_files: List of definition file names to import
        definitions_dir: Directory containing definition files
        debug: Enable debug output
    
    Returns:
        True if successful, False otherwise
    """
    import os
    
    try:
        api = create_guardium_api(config, logger, appliance_name=appliance_name)
        
        demo_password = config.get_custom_variable('pwd')
        if not demo_password:
            logger.error("pwd not found in custom_variables")
            return False
        
        logger.info("Authenticating as demo user...")
        api.get_token(username='demo', password=demo_password)
        logger.info("✓ Authentication successful")
        
        for filename in definition_files:
            file_path = os.path.join(definitions_dir, filename)
            
            if not os.path.exists(file_path):
                logger.error(f"✗ File not found: {file_path}")
                return False
            
            logger.info(f"\n➜ Importing: {filename}")
            result = api.import_definitions(file_path=file_path)
            
            if debug:
                logger.info(f"  API Response: {result}")
            
            logger.info(f"✓ {filename} imported successfully")
        
        return True
        
    except FileNotFoundError as e:
        logger.error(f"✗ File not found: {e}")
        return False
    except Exception as e:
        logger.error(f"✗ Failed to import definitions: {e}")
        if debug:
            import traceback
            logger.error(traceback.format_exc())
        return False
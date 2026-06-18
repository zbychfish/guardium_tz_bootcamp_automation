#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration Loader Module
Handles loading and accessing configuration from YAML files and JSON machine info
"""

import os
import json
import yaml
from typing import Any, Dict, Optional, List
from pathlib import Path


class ConfigLoader:
    """
    Loads and provides access to configuration data.
    Supports YAML configuration files and environment variable overrides.
    """
    
    def __init__(self, config_file: str = "config/config.yaml", machines_info_file: str = "/root/machines_info.json"):
        """
        Initialize configuration loader.
        
        Args:
            config_file: Path to YAML configuration file
            machines_info_file: Path to JSON file containing machine information
        """
        self.config_file = Path(config_file)
        self.machines_info_file = Path(machines_info_file)
        self.config: Dict[str, Any] = self._load_config()
        self.machines_info: Dict[str, Any] = self._load_machines_info()
        
        # Merge machines from JSON into config
        self._merge_machines_into_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """
        Load configuration from YAML file.
        
        Returns:
            Dictionary containing configuration data
        """
        if not self.config_file.exists():
            print(f"Warning: Config file not found: {self.config_file}")
            return {}
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
                return config
        except yaml.YAMLError as e:
            print(f"Error: Could not parse config file: {e}")
            return {}
        except IOError as e:
            print(f"Error: Could not read config file: {e}")
            return {}
    
    def _load_machines_info(self) -> Dict[str, Any]:
        """
        Load machine information from JSON file.
        
        Returns:
            Dictionary containing machine information
        """
        if not self.machines_info_file.exists():
            print(f"Warning: Machines info file not found: {self.machines_info_file}")
            return {}
        
        try:
            with open(self.machines_info_file, 'r', encoding='utf-8') as f:
                machines_info = json.load(f)
                return machines_info
        except json.JSONDecodeError as e:
            print(f"Error: Could not parse machines info file: {e}")
            return {}
        except IOError as e:
            print(f"Error: Could not read machines info file: {e}")
            return {}
    
    def _merge_machines_into_config(self):
        """
        Merge machine information from JSON into config structure.
        Extracts machine names without suffixes and creates machine entries.
        """
        if not self.machines_info or 'machines' not in self.machines_info:
            return
        
        # Initialize machines section if it doesn't exist
        if 'machines' not in self.config:
            self.config['machines'] = {}
        
        # Process each machine from the JSON file
        for machine in self.machines_info.get('machines', []):
            # Extract machine name without suffix (e.g., "hana-dsbni7pj" -> "hana")
            full_name = machine.get('name', '')
            if not full_name:
                continue
            
            # Split by '-' and take the first part as the base name
            base_name = full_name.split('-')[0]
            
            # Create machine entry in config
            self.config['machines'][base_name] = {
                'host': machine.get('public_ip', ''),
                'private_ip': machine.get('private_ip', ''),
                'fqdn': machine.get('fqdn', ''),
                'full_name': full_name,
                'alias': machine.get('alias', ''),
                'description': f"Auto-loaded from machines_info.json"
            }
        
        # Also store credentials and deployment info if available
        if 'credentials' in self.machines_info:
            self.config['credentials'] = self.machines_info['credentials']
        
        if 'deployment' in self.machines_info:
            self.config['deployment'] = self.machines_info['deployment']
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by key.
        Supports dot notation for nested keys (e.g., "ssh.port").
        Checks environment variables first, then config file.
        
        Args:
            key: Configuration key (supports dot notation)
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        # Check environment variable first (convert dots to underscores and uppercase)
        env_key = key.replace('.', '_').upper()
        env_value = os.getenv(env_key)
        if env_value is not None:
            return env_value
        
        # Navigate nested dictionary using dot notation
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        
        return value if value is not None else default
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """
        Get entire configuration section.
        
        Args:
            section: Section name
            
        Returns:
            Dictionary containing section data
        """
        return self.config.get(section, {})
    
    def get_all(self) -> Dict[str, Any]:
        """
        Get entire configuration.
        
        Returns:
            Complete configuration dictionary
        """
        return self.config.copy()
    
    def reload(self):
        """Reload configuration from file."""
        self.config = self._load_config()
    
    def validate_required(self, required_keys: list) -> bool:
        """
        Validate that required configuration keys exist.
        
        Args:
            required_keys: List of required key paths (supports dot notation)
            
        Returns:
            True if all required keys exist, False otherwise
        """
        missing = []
        for key in required_keys:
            if self.get(key) is None:
                missing.append(key)
        
        if missing:
            print(f"Error: Missing required configuration keys: {', '.join(missing)}")
            return False
        
        return True
    
    def get_machines(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all machines configuration.
        
        Returns:
            Dictionary of machine configurations keyed by base name
        """
        return self.config.get('machines', {})
    
    def is_appliance(self, machine_name: str) -> bool:
        """
        Check if machine is a Guardium appliance (cm, appnodeX, collX).
        
        Args:
            machine_name: Base machine name (e.g., 'cm', 'appnode1', 'coll1')
            
        Returns:
            True if machine is an appliance, False otherwise
        """
        # Check if name matches appliance patterns
        appliance_patterns = [
            'cm',           # Central Manager
            'appnode',      # Application Nodes (appnode1, appnode2, etc.)
            'coll',         # Collectors (coll1, coll2, etc.)
        ]
        
        for pattern in appliance_patterns:
            if machine_name.startswith(pattern):
                return True
        
        return False
    
    def get_regular_machines(self) -> Dict[str, Dict[str, Any]]:
        """
        Get only regular machines (exclude appliances).
        
        Returns:
            Dictionary of regular machines (raptor, sauropod, ceratops, etc.)
        """
        machines = self.get_machines()
        return {
            name: info
            for name, info in machines.items()
            if not self.is_appliance(name)
        }
    
    def get_appliances(self) -> Dict[str, Dict[str, Any]]:
        """
        Get only appliances (cm, appnodeX, collX).
        
        Returns:
            Dictionary of appliances (cm, appnode1, coll1, etc.)
        """
        machines = self.get_machines()
        return {
            name: info
            for name, info in machines.items()
            if self.is_appliance(name)
        }
    
    def get_machine(self, machine_name: str) -> Optional[Dict[str, Any]]:
        """
        Get configuration for a specific machine by base name.
        
        Args:
            machine_name: Base machine name (without suffix)
            
        Returns:
            Machine configuration dictionary or None if not found
        """
        machines = self.get_machines()
        return machines.get(machine_name)
    
    def get_machine_ip(self, machine_name: str, use_private: bool = False) -> Optional[str]:
        """
        Get IP address for a specific machine.
        
        Args:
            machine_name: Base machine name (without suffix)
            use_private: If True, return private IP; otherwise return public IP
            
        Returns:
            IP address or None if not found
        """
        machine = self.get_machine(machine_name)
        if not machine:
            return None
        
        if use_private:
            return machine.get('private_ip')
        return machine.get('host')
    
    def get_credentials(self) -> Dict[str, Any]:
        """
        Get credentials information from machines_info.json.
        
        Returns:
            Dictionary containing credentials
        """
        return self.config.get('credentials', {})
    
    def get_deployment_info(self) -> Dict[str, Any]:
        """
        Get deployment information from machines_info.json.
        
        Returns:
            Dictionary containing deployment information
        """
        return self.config.get('deployment', {})
    
    def get_custom_variables(self) -> Dict[str, Any]:
        """
        Get custom variables from machines_info.json.
        These are variables passed from the TechZone manifest.
        
        Returns:
            Dictionary containing custom variables (e.g., pwd, stage, etc.)
        """
        return self.machines_info.get('custom_variables', {})
    
    def get_custom_variable(self, key: str, default: Any = None) -> Any:
        """
        Get a specific custom variable value.
        
        Args:
            key: Variable name
            default: Default value if not found
            
        Returns:
            Variable value or default
        """
        custom_vars = self.get_custom_variables()
        return custom_vars.get(key, default)
    
    def set_custom_variable(self, key: str, value: Any) -> None:
        """
        Set a custom variable value in memory.
        Note: This only updates the in-memory configuration, not the JSON file.
        
        Args:
            key: Variable name
            value: Variable value
        """
        # Initialize custom_variables in machines_info if it doesn't exist
        if 'custom_variables' not in self.machines_info:
            self.machines_info['custom_variables'] = {}
        
        # Set the variable
        self.machines_info['custom_variables'][key] = value

# Made with Bob

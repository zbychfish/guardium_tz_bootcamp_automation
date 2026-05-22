#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration Loader Module
Handles loading and accessing configuration from YAML files
"""

import os
import yaml
from typing import Any, Dict, Optional
from pathlib import Path


class ConfigLoader:
    """
    Loads and provides access to configuration data.
    Supports YAML configuration files and environment variable overrides.
    """
    
    def __init__(self, config_file: str = "config/config.yaml"):
        """
        Initialize configuration loader.
        
        Args:
            config_file: Path to YAML configuration file
        """
        self.config_file = Path(config_file)
        self.config: Dict[str, Any] = self._load_config()
    
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

# Made with Bob

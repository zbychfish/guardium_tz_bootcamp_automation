#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Appliance Configuration Loader
Loads and manages Guardium appliance configurations
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from core.logger import get_logger

logger = get_logger(__name__)


class ApplianceConfigLoader:
    """Loads and manages appliance configurations from YAML file"""
    
    def __init__(self, config_file: str = "config/appliances.yaml"):
        """
        Initialize appliance config loader
        
        Args:
            config_file: Path to appliances YAML configuration file
        """
        self.config_file = Path(config_file)
        self.appliances: Dict[str, Dict[str, Any]] = {}
        self.appliance_types: Dict[str, Dict[str, Any]] = {}
        self._load_config()
    
    def _load_config(self):
        """Load appliances configuration from YAML file"""
        if not self.config_file.exists():
            logger.warning(f"Appliances config file not found: {self.config_file}")
            return
        
        try:
            with open(self.config_file, 'r') as f:
                config = yaml.safe_load(f)
            
            self.appliances = config.get('appliances', {})
            self.appliance_types = config.get('appliance_types', {})
            
            logger.info(f"Loaded {len(self.appliances)} appliance(s) from {self.config_file}")
            
        except Exception as e:
            logger.error(f"Failed to load appliances config: {e}")
            raise
    
    def get_appliance(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get appliance configuration by name
        
        Args:
            name: Appliance name
        
        Returns:
            Appliance configuration dict or None if not found
        """
        return self.appliances.get(name)
    
    def get_all_appliances(self) -> Dict[str, Dict[str, Any]]:
        """Get all appliances"""
        return self.appliances.copy()
    
    def get_appliances_by_type(self, appliance_type: str) -> Dict[str, Dict[str, Any]]:
        """
        Get all appliances of specific type
        
        Args:
            appliance_type: Type of appliance (collector, cm, aggregator, appnode)
        
        Returns:
            Dictionary of appliances of specified type
        """
        return {
            name: config 
            for name, config in self.appliances.items() 
            if config.get('type') == appliance_type
        }
    
    def get_type_config(self, appliance_type: str) -> Optional[Dict[str, Any]]:
        """
        Get type configuration (default prompts, user, etc.)
        
        Args:
            appliance_type: Type of appliance
        
        Returns:
            Type configuration dict or None if not found
        """
        return self.appliance_types.get(appliance_type)
    
    def get_default_prompt(self, appliance_type: str, configured: bool = True) -> Optional[str]:
        """
        Get default prompt regex for appliance type
        
        Args:
            appliance_type: Type of appliance
            configured: True for configured prompt, False for unconfigured (collectors only)
        
        Returns:
            Prompt regex string or None
        """
        type_config = self.get_type_config(appliance_type)
        if not type_config:
            return None
        
        if appliance_type == 'collector' and not configured:
            return type_config.get('default_prompt_unconfigured')
        
        if appliance_type == 'collector' and configured:
            return type_config.get('default_prompt_configured')
        
        return type_config.get('default_prompt')
    
    def get_default_user(self, appliance_type: str) -> str:
        """
        Get default user for appliance type
        
        Args:
            appliance_type: Type of appliance
        
        Returns:
            Default username (defaults to 'cli')
        """
        type_config = self.get_type_config(appliance_type)
        if type_config:
            return type_config.get('default_user', 'cli')
        return 'cli'
    
    def list_appliances(self) -> None:
        """Print list of all configured appliances"""
        if not self.appliances:
            logger.info("No appliances configured")
            return
        
        logger.info("Configured appliances:")
        for name, config in self.appliances.items():
            logger.info(f"  - {name}: {config.get('type')} at {config.get('ip')} - {config.get('description', '')}")

# Made with Bob

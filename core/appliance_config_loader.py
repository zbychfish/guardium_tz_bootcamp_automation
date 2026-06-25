#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Appliance Configuration Loader
Loads and manages Guardium appliance configurations from machines_info.json
"""

from typing import Dict, Any, Optional
from core.logger import get_logger

logger = get_logger(__name__)


class ApplianceConfigLoader:
    """Loads and manages appliance configurations from machines_info.json via ConfigLoader"""
    
    def __init__(self, config_loader=None):
        """
        Initialize appliance config loader
        
        Args:
            config_loader: ConfigLoader instance (for getting appliances from machines_info.json)
        """
        self.config_loader = config_loader
        self.appliances: Dict[str, Dict[str, Any]] = {}
        self._load_config()
    
    def _load_config(self):
        """Load appliances configuration from machines_info.json"""
        # Load appliances from machines_info.json via ConfigLoader
        if self.config_loader:
            machines_appliances = self.config_loader.get_appliances()
            
            # Convert to appliance format with type detection
            for name, info in machines_appliances.items():
                appliance_type = self._detect_appliance_type(name)
                self.appliances[name] = {
                    'ip': info.get('private_ip', info.get('host', '')),
                    'type': appliance_type,
                    'description': f"Auto-loaded from machines_info.json",
                    'public_ip': info.get('host', ''),
                    'private_ip': info.get('private_ip', ''),
                    'fqdn': info.get('fqdn', ''),
                    'full_name': info.get('full_name', name)
                }
            
            logger.info(f"Loaded {len(self.appliances)} appliance(s) from machines_info.json")
        else:
            logger.warning("No ConfigLoader provided, appliances list will be empty")
    
    def _detect_appliance_type(self, name: str) -> str:
        """
        Detect appliance type from name
        
        Args:
            name: Appliance base name (e.g., 'cm', 'coll1', 'appnode1')
        
        Returns:
            Appliance type string
        """
        if name.startswith('cm'):
            return 'cm'
        elif name.startswith('coll'):
            return 'collector'
        elif name.startswith('appnode') or name.startswith('kafka'):
            return 'appnode'
        elif name.startswith('aggr'):
            return 'aggregator'
        else:
            return 'unknown'
    
    def get_appliance(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get appliance configuration by name.
        Supports both exact match and prefix match (name without suffix).
        
        Args:
            name: Appliance name (e.g., "cm02" or "cm02-suffix")
        
        Returns:
            Appliance configuration dict or None if not found
        """
        # Try exact match first
        if name in self.appliances:
            return self.appliances.get(name)
        
        # Try prefix match (find appliance starting with name)
        for appliance_name, config in self.appliances.items():
            if appliance_name.startswith(name + "-"):
                logger.debug(f"Found appliance '{appliance_name}' by prefix '{name}'")
                return config
        
        return None
    
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
    
    def get_default_prompt(self, appliance_type: str, configured: bool = True) -> Optional[str]:
        """
        Get default prompt regex for appliance type
        
        Args:
            appliance_type: Type of appliance
            configured: True for configured prompt, False for unconfigured (collectors only)
        
        Returns:
            Prompt regex string (hardcoded default)
        """
        return r"[\w-]+(\\.demo\\.guardium)?>"
    
    def get_default_user(self, appliance_type: str) -> str:
        """
        Get default user for appliance type
        
        Args:
            appliance_type: Type of appliance
        
        Returns:
            Default username (always 'cli')
        """
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

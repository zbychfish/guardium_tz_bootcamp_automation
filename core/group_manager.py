#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Group Manager
Manages logical groups of stages for training labs
"""

import yaml
import importlib
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any


class GroupManager:
    """Manages groups of stages defined in groups.yaml"""
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize GroupManager.
        
        Args:
            config_path: Path to groups.yaml file. If None, uses default location.
        """
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "groups.yaml"
        
        self.config_path = config_path
        self.groups = self._load_groups()
        self._stage_cache: Dict[str, Callable] = {}
    
    def _load_groups(self) -> Dict[str, Any]:
        """Load groups configuration from YAML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Groups configuration not found: {self.config_path}")
        
        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        if not config or 'groups' not in config:
            raise ValueError("Invalid groups.yaml: missing 'groups' key")
        
        return config['groups']
    
    def list_groups(self) -> List[str]:
        """Get list of all group names in order."""
        return list(self.groups.keys())
    
    def get_group_info(self, group_name: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a specific group.
        
        Args:
            group_name: Name of the group
            
        Returns:
            Dictionary with group information or None if not found
        """
        return self.groups.get(group_name)
    
    def get_auto_execute_groups(self) -> List[str]:
        """Get list of groups that should be auto-executed (before marker)."""
        return [
            name for name, info in self.groups.items()
            if info.get('auto_execute', False)
        ]
    
    def get_manual_groups(self) -> List[str]:
        """Get list of groups that are executed manually (after marker)."""
        return [
            name for name, info in self.groups.items()
            if not info.get('auto_execute', False)
        ]
    
    def get_group_stages(self, group_name: str) -> List[Dict[str, str]]:
        """
        Get list of stages in a group.
        
        Args:
            group_name: Name of the group
            
        Returns:
            List of stage dictionaries with name, function, module, description
        """
        group = self.groups.get(group_name)
        if not group:
            return []
        
        return group.get('stages', [])
    
    def load_stage_function(self, stage_info: Dict[str, str]) -> Optional[Callable]:
        """
        Dynamically load a stage function from its module.
        
        Args:
            stage_info: Dictionary with 'module' and 'function' keys
            
        Returns:
            Callable function or None if loading fails
        """
        module_name = stage_info.get('module')
        function_name = stage_info.get('function')
        
        if not module_name or not function_name:
            return None
        
        # Check cache first
        cache_key = f"{module_name}.{function_name}"
        if cache_key in self._stage_cache:
            return self._stage_cache[cache_key]
        
        try:
            # Import module
            module = importlib.import_module(module_name)
            
            # Get function
            if not hasattr(module, function_name):
                return None
            
            func = getattr(module, function_name)
            
            # Cache it
            self._stage_cache[cache_key] = func
            
            return func
            
        except (ImportError, AttributeError) as e:
            print(f"Error loading {module_name}.{function_name}: {e}")
            return None
    
    def validate_groups(self) -> Dict[str, List[str]]:
        """
        Validate that all stages in all groups can be loaded.
        
        Returns:
            Dictionary with group names as keys and list of errors as values
        """
        errors = {}
        
        for group_name, group_info in self.groups.items():
            group_errors = []
            
            stages = group_info.get('stages', [])
            if not stages:
                group_errors.append("No stages defined")
            
            for stage in stages:
                stage_name = stage.get('name', 'unknown')
                func = self.load_stage_function(stage)
                
                if func is None:
                    group_errors.append(
                        f"Stage '{stage_name}': Cannot load {stage.get('module')}.{stage.get('function')}"
                    )
            
            if group_errors:
                errors[group_name] = group_errors
        
        return errors
    
    def get_all_stages_ordered(self) -> List[tuple]:
        """
        Get all stages from all groups in execution order.
        
        Returns:
            List of tuples: (group_name, stage_info)
        """
        all_stages = []
        
        for group_name in self.list_groups():
            stages = self.get_group_stages(group_name)
            for stage in stages:
                all_stages.append((group_name, stage))
        
        return all_stages
    
    def find_stage_by_name(self, stage_name: str) -> Optional[tuple]:
        """
        Find a stage by its name across all groups.
        
        Args:
            stage_name: Name of the stage to find
            
        Returns:
            Tuple of (group_name, stage_info) or None if not found
        """
        for group_name in self.list_groups():
            stages = self.get_group_stages(group_name)
            for stage in stages:
                if stage.get('name') == stage_name:
                    return (group_name, stage)
        
        return None
    
    def print_groups_summary(self):
        """Print a summary of all groups and their stages."""
        print("\n" + "=" * 80)
        print("GROUPS CONFIGURATION")
        print("=" * 80)
        
        for group_name in self.list_groups():
            group_info = self.get_group_info(group_name)
            if not group_info:
                continue
            
            auto = "AUTO" if group_info.get('auto_execute') else "MANUAL"
            
            print(f"\n[{auto}] {group_name}: {group_info.get('name')}")
            print(f"  Description: {group_info.get('description')}")
            print(f"  Stages:")
            
            for stage in self.get_group_stages(group_name):
                print(f"    - {stage.get('name')}: {stage.get('description')}")
        
        print("\n" + "=" * 80)


# Made with Bob
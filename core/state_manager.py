#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
State Manager Module
Handles task execution state tracking and persistence
"""

import json
import os
from typing import List, Dict, Any
from pathlib import Path


class StateManager:
    """
    Manages execution state for automation tasks.
    Tracks completed tasks to enable resumable execution.
    """
    
    def __init__(self, state_file: str = "state.json"):
        """
        Initialize state manager.
        
        Args:
            state_file: Path to state persistence file
        """
        self.state_file = Path(state_file)
        self.state: Dict[str, Any] = self._load_state()
    
    def _load_state(self) -> Dict[str, Any]:
        """
        Load state from file.
        
        Returns:
            Dictionary containing state data
        """
        if not self.state_file.exists():
            return {
                "completed_tasks": [],
                "metadata": {}
            }
        
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load state file: {e}")
            return {
                "completed_tasks": [],
                "metadata": {}
            }
    
    def _save_state(self):
        """Save current state to file."""
        try:
            # Create parent directory if it doesn't exist
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2)
        except IOError as e:
            print(f"Error: Could not save state file: {e}")
    
    def is_completed(self, task_id: str) -> bool:
        """
        Check if task has been completed.
        
        Args:
            task_id: Task identifier
            
        Returns:
            True if task is completed, False otherwise
        """
        return task_id in self.state.get("completed_tasks", [])
    
    def mark_completed(self, task_id: str):
        """
        Mark task as completed.
        
        Args:
            task_id: Task identifier
        """
        if not self.is_completed(task_id):
            self.state.setdefault("completed_tasks", []).append(task_id)
            self._save_state()
    
    def get_completed_tasks(self) -> List[str]:
        """
        Get list of completed tasks.
        
        Returns:
            List of completed task IDs
        """
        return self.state.get("completed_tasks", [])
    
    def reset(self):
        """Reset state - clear all completed tasks."""
        self.state = {
            "completed_tasks": [],
            "metadata": {}
        }
        self._save_state()
    
    def set_metadata(self, key: str, value: Any):
        """
        Store metadata value.
        
        Args:
            key: Metadata key
            value: Metadata value (must be JSON serializable)
        """
        self.state.setdefault("metadata", {})[key] = value
        self._save_state()
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """
        Retrieve metadata value.
        
        Args:
            key: Metadata key
            default: Default value if key not found
            
        Returns:
            Metadata value or default
        """
        return self.state.get("metadata", {}).get(key, default)
    
    def remove_task(self, task_id: str):
        """
        Remove task from completed list.
        
        Args:
            task_id: Task identifier
        """
        completed = self.state.get("completed_tasks", [])
        if task_id in completed:
            completed.remove(task_id)
            self._save_state()
    
    def is_group_completed(self, group_name: str) -> bool:
        """
        Check if all stages in a group have been completed.
        
        Args:
            group_name: Name of the group
            
        Returns:
            True if group is marked as completed, False otherwise
        """
        completed_groups = self.state.get("completed_groups", [])
        return group_name in completed_groups
    
    def mark_group_completed(self, group_name: str):
        """
        Mark a group as completed.
        
        Args:
            group_name: Name of the group
        """
        if not self.is_group_completed(group_name):
            self.state.setdefault("completed_groups", []).append(group_name)
            self._save_state()
    
    def get_completed_groups(self) -> List[str]:
        """
        Get list of completed groups.
        
        Returns:
            List of completed group names
        """
        return self.state.get("completed_groups", [])
    
    def remove_group(self, group_name: str):
        """
        Remove group from completed list.
        
        Args:
            group_name: Name of the group
        """
        completed_groups = self.state.get("completed_groups", [])
        if group_name in completed_groups:
            completed_groups.remove(group_name)
            self._save_state()

# Made with Bob

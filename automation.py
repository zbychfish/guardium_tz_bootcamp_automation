#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Machine Automation Framework
Main orchestration script for managing machine configuration tasks
"""

import sys
import argparse
from pathlib import Path
from typing import List, Callable, Optional

# Add core modules to path
sys.path.insert(0, str(Path(__file__).parent / "core"))

from state_manager import StateManager
from config_loader import ConfigLoader
from logger import setup_logger


class AutomationOrchestrator:
    """
    Main orchestrator for machine automation tasks.
    Manages task execution, state tracking, and error handling.
    """
    
    def __init__(self, config_file: str = "config/config.yaml", state_file: str = "state.json"):
        """
        Initialize the orchestrator.
        
        Args:
            config_file: Path to configuration file
            state_file: Path to state tracking file
        """
        self.logger = setup_logger("AutomationOrchestrator")
        self.config = ConfigLoader(config_file)
        self.state = StateManager(state_file)
        self.tasks: List[tuple] = []
        
        self.logger.info("Automation Orchestrator initialized")
        self.logger.info(f"Config: {config_file}")
        self.logger.info(f"State: {state_file}")
    
    def register_task(self, task_id: str, task_fn: Callable, description: str = ""):
        """
        Register a task for execution.
        
        Args:
            task_id: Unique task identifier
            task_fn: Function to execute for this task
            description: Human-readable task description
        """
        self.tasks.append((task_id, task_fn, description))
        self.logger.debug(f"Registered task: {task_id} - {description}")
    
    def run_task(self, task_id: str, task_fn: Callable, description: str = "") -> bool:
        """
        Execute a single task if not already completed.
        
        Args:
            task_id: Unique task identifier
            task_fn: Function to execute
            description: Task description for logging
            
        Returns:
            True if task executed successfully, False otherwise
        """
        if self.state.is_completed(task_id):
            self.logger.info(f"⏭  Skipping (already completed): {task_id}")
            return True
        
        self.logger.info(f"➤  Running: {task_id}")
        if description:
            self.logger.info(f"   Description: {description}")
        
        try:
            result = task_fn()
            self.state.mark_completed(task_id)
            self.logger.info(f"✓  Completed: {task_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"✗  Failed: {task_id}")
            self.logger.error(f"   Error: {str(e)}", exc_info=True)
            return False
    
    def run_all_tasks(self, stop_at: Optional[str] = None) -> bool:
        """
        Execute all registered tasks in sequence.
        
        Args:
            stop_at: Optional task_id to stop execution at
            
        Returns:
            True if all tasks completed successfully, False otherwise
        """
        self.logger.info("=" * 80)
        self.logger.info("Starting automation execution")
        self.logger.info(f"Total tasks registered: {len(self.tasks)}")
        self.logger.info("=" * 80)
        
        for task_id, task_fn, description in self.tasks:
            success = self.run_task(task_id, task_fn, description)
            
            if not success:
                self.logger.error("Task execution failed. Stopping.")
                return False
            
            if stop_at and task_id == stop_at:
                self.logger.info(f"Stopping at requested task: {stop_at}")
                break
        
        self.logger.info("=" * 80)
        self.logger.info("Automation execution completed successfully")
        self.logger.info("=" * 80)
        return True
    
    def reset_state(self):
        """Reset state to start fresh."""
        self.state.reset()
        self.logger.info("State reset - all tasks will be re-executed")
    
    def show_status(self):
        """Display current execution status."""
        completed = self.state.get_completed_tasks()
        total = len(self.tasks)
        
        print("\n" + "=" * 80)
        print("AUTOMATION STATUS")
        print("=" * 80)
        print(f"Total tasks: {total}")
        print(f"Completed: {len(completed)}")
        print(f"Remaining: {total - len(completed)}")
        print("\nCompleted tasks:")
        for task_id in completed:
            print(f"  ✓ {task_id}")
        print("=" * 80 + "\n")


def main():
    """Main entry point for the automation framework."""
    parser = argparse.ArgumentParser(
        description="Machine Automation Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Path to configuration file (default: config/config.yaml)"
    )
    
    parser.add_argument(
        "--state",
        default="state.json",
        help="Path to state file (default: state.json)"
    )
    
    parser.add_argument(
        "--stop-at",
        help="Stop execution at specified task ID"
    )
    
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset state and start from beginning"
    )
    
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current execution status"
    )
    
    args = parser.parse_args()
    
    # Initialize orchestrator
    orchestrator = AutomationOrchestrator(
        config_file=args.config,
        state_file=args.state
    )
    
    # Handle special commands
    if args.reset:
        orchestrator.reset_state()
        return 0
    
    if args.status:
        orchestrator.show_status()
        return 0
    
    # Register your tasks here
    # Example:
    # orchestrator.register_task(
    #     task_id="task_001_example",
    #     task_fn=lambda: example_task_function(),
    #     description="Example task description"
    # )
    
    # Run all tasks
    success = orchestrator.run_all_tasks(stop_at=args.stop_at)
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

# Made with Bob

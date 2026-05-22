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
sys.path.insert(0, str(Path(__file__).parent / "tasks"))

from core.state_manager import StateManager
from core.config_loader import ConfigLoader
from core.logger import setup_logger
from tasks.setup_hosts import setup_hosts_locally, setup_hosts_on_remote_machine


class AutomationOrchestrator:
    """
    Main orchestrator for machine automation tasks.
    Manages task execution, state tracking, and error handling.
    """
    
    def __init__(self, config_file: str = "config/config.yaml", state_file: str = "state.json",
                 machines_info_file: str = "/root/machines_info.json"):
        """
        Initialize the orchestrator.
        
        Args:
            config_file: Path to configuration file
            state_file: Path to state tracking file
            machines_info_file: Path to JSON file containing machine information
        """
        self.logger = setup_logger("AutomationOrchestrator")
        self.config = ConfigLoader(config_file, machines_info_file)
        self.state = StateManager(state_file)
        self.tasks: List[tuple] = []
        
        self.logger.info("Automation Orchestrator initialized")
        self.logger.info(f"Config: {config_file}")
        self.logger.info(f"Machines Info: {machines_info_file}")
        self.logger.info(f"State: {state_file}")
        
        # Log loaded machines
        machines = self.config.get_machines()
        if machines:
            self.logger.info(f"Loaded {len(machines)} machine(s): {', '.join(machines.keys())}")
        else:
            self.logger.warning("No machines loaded from machines_info.json")
    
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
        "--machines-info",
        default="/root/machines_info.json",
        help="Path to machines info JSON file (default: /root/machines_info.json)"
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
        state_file=args.state,
        machines_info_file=args.machines_info
    )
    
    # Handle special commands
    if args.reset:
        orchestrator.reset_state()
        return 0
    
    if args.status:
        orchestrator.show_status()
        return 0
    
    # Register your tasks here
    
    machines = orchestrator.config.get_machines()
    credentials = orchestrator.config.get_credentials()
    logger = setup_logger("TaskRegistration")
    
    # Get root password from custom_variables (passed from manifest)
    root_password = orchestrator.config.get_custom_variable('pwd')
    if root_password:
        logger.info("Root password found in custom_variables - will be set on all machines")
    else:
        logger.warning("No root password (pwd) found in custom_variables - password will not be changed")
    
    # Setup /etc/hosts, SSHD, and root password on local machine (raptor)
    orchestrator.register_task(
        task_id="setup_local_raptor",
        task_fn=lambda: setup_hosts_locally(
            all_machines=machines,
            logger=logger,
            configure_sshd=True,
            root_password=root_password
        ),
        description="Setup /etc/hosts, SSHD, and root password on local machine (raptor)"
    )
    
    # Setup /etc/hosts, SSHD, and root password on remote machines
    # Get list of remote machines from config
    remote_machines = orchestrator.config.get('tasks', {}).get('remote_machines', [])
    logger.info(f"Remote machines to configure: {remote_machines}")
    
    for machine_name in remote_machines:
        machine_info = orchestrator.config.get_machine(machine_name)
        if machine_info:
            orchestrator.register_task(
                task_id=f"setup_remote_{machine_name}",
                task_fn=lambda m=machine_name, mi=machine_info: setup_hosts_on_remote_machine(
                    machine_name=m,
                    machine_info=mi,
                    all_machines=machines,
                    credentials=credentials,
                    logger=logger,
                    use_private_ip=True,
                    configure_sshd=True,
                    root_password=root_password
                ),
                description=f"Setup /etc/hosts, SSHD, and root password on {machine_name}"
            )
        else:
            logger.warning(f"Machine {machine_name} not found in configuration")
    
    # Run all tasks
    success = orchestrator.run_all_tasks(stop_at=args.stop_at)
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

# Made with Bob

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
from tasks.deploy_mysql import deploy_mysql_on_raptor
from tasks.deploy_mongo import deploy_mongo_on_raptor

class AutomationOrchestrator:
    """
    Main orchestrator for machine automation tasks.
    Manages task execution, state tracking, and error handling.
    """
    
    def __init__(self, config_file: str = "config/config.yaml", state_file: str = "state.json",
                 machines_info_file: str = "/root/machines_info.json", verbose: bool = False):
        """
        Initialize the orchestrator.
        
        Args:
            config_file: Path to configuration file
            state_file: Path to state tracking file
            machines_info_file: Path to JSON file containing machine information
            verbose: Enable verbose logging
        """
        self.logger = setup_logger("AutomationOrchestrator")
        self.config = ConfigLoader(config_file, machines_info_file)
        self.state = StateManager(state_file)
        self.tasks: List[tuple] = []
        self.verbose = verbose
        
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
            if self.verbose:
                self.logger.info(f"⏭  Skipping (already completed): {task_id}")
            else:
                self.logger.info(f"⏭  {task_id}")
            return True
        
        if self.verbose:
            self.logger.info(f"➤  Running: {task_id}")
            if description:
                self.logger.info(f"   Description: {description}")
        else:
            self.logger.info(f"➤  {task_id}")
        
        try:
            result = task_fn()
            self.state.mark_completed(task_id)
            if self.verbose:
                self.logger.info(f"✓  Completed: {task_id}")
            else:
                self.logger.info(f"✓  {task_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"✗  Failed: {task_id}")
            self.logger.error(f"   Error: {str(e)}", exc_info=self.verbose)
            return False
    
    def run_all_tasks(self, stop_at: Optional[str] = None, continue_mode: bool = False) -> bool:
        """
        Execute all registered tasks in sequence.
        
        Args:
            stop_at: Optional task_id to stop execution at (from stage parameter)
            continue_mode: If True, ignore stop_at and run all remaining tasks
            
        Returns:
            True if all tasks completed successfully, False otherwise
        """
        self.logger.info("=" * 80)
        self.logger.info("Starting automation execution")
        self.logger.info(f"Total tasks registered: {len(self.tasks)}")
        if continue_mode:
            self.logger.info("Mode: CONTINUE - executing all remaining tasks")
        elif stop_at:
            self.logger.info(f"Mode: INITIAL - stopping at stage: {stop_at}")
        else:
            self.logger.info("Mode: FULL - executing all tasks")
        self.logger.info("=" * 80)
        
        for task_id, task_fn, description in self.tasks:
            success = self.run_task(task_id, task_fn, description)
            
            if not success:
                self.logger.error("Task execution failed. Stopping.")
                return False
            
            # Stop at stage only if not in continue mode
            if not continue_mode and stop_at and task_id == stop_at:
                self.logger.info("=" * 80)
                self.logger.info(f"✓ Reached stage checkpoint: {stop_at}")
                self.logger.info("Initial setup phase completed successfully")
                self.logger.info("To continue with remaining tasks, run: python automation.py --continue")
                self.logger.info("=" * 80)
                return True
        
        self.logger.info("=" * 80)
        self.logger.info("Automation execution completed successfully")
        self.logger.info("=" * 80)
        return True
    
    def reset_state(self):
        """Reset state to start fresh."""
        self.state.reset()
        self.logger.info("State reset - all tasks will be re-executed")
    
    def show_status(self):
        """Display current execution status with task descriptions."""
        completed = self.state.get_completed_tasks()
        total = len(self.tasks)
        stage = self.config.get_custom_variable('stage')
        
        # Create task map for descriptions
        task_map = {task_id: (desc, idx) for idx, (task_id, _, desc) in enumerate(self.tasks, 1)}
        
        print("\n" + "=" * 80)
        print("AUTOMATION STATUS")
        print("=" * 80)
        print(f"Total tasks: {total}")
        print(f"Completed: {len(completed)}")
        print(f"Remaining: {total - len(completed)}")
        
        if stage:
            print(f"\nStage checkpoint: {stage}")
            # Check if stage task is completed
            if stage in completed:
                print(f"  ✓ Stage reached - run with --continue to proceed")
            else:
                print(f"  ⧗ Stage not yet reached")
        
        print("\nCompleted tasks:")
        for task_id in completed:
            marker = "  ✓ "
            if stage and task_id == stage:
                marker = "  ✓ [STAGE] "
            desc, idx = task_map.get(task_id, ("", 0))
            if desc:
                print(f"{marker}[{idx}] {task_id}")
                print(f"      {desc}")
            else:
                print(f"{marker}{task_id}")
        
        if total > len(completed):
            print("\nRemaining tasks:")
            for task_id, task_fn, desc in self.tasks:
                if task_id not in completed:
                    marker = "  ○ "
                    if stage and task_id == stage:
                        marker = "  ○ [STAGE] "
                    idx = task_map[task_id][1]
                    print(f"{marker}[{idx}] {task_id}")
                    if desc:
                        print(f"      {desc}")
        
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
        help="Stop execution at specified task ID (overrides stage from machines_info.json)"
    )
    
    parser.add_argument(
        "--continue",
        dest="continue_mode",
        action="store_true",
        help="Continue execution of remaining tasks (ignores stage parameter)"
    )
    
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset state and start from beginning"
    )
    
    parser.add_argument(
        "--remove-task",
        metavar="TASK_ID",
        help="Remove specific task from completed state (allows re-execution)"
    )
    
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current execution status"
    )
    
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output (show full task details and descriptions)"
    )
    
    args = parser.parse_args()
    
    # Initialize orchestrator
    orchestrator = AutomationOrchestrator(
        config_file=args.config,
        state_file=args.state,
        machines_info_file=args.machines_info,
        verbose=args.verbose
    )
    
    # Handle special commands
    if args.reset:
        orchestrator.reset_state()
        return 0
    
    if args.remove_task:
        task_id = args.remove_task
        if orchestrator.state.is_completed(task_id):
            orchestrator.state.remove_task(task_id)
            print(f"✓ Task '{task_id}' removed from completed state")
            print(f"  Task will be re-executed on next run")
        else:
            print(f"✗ Task '{task_id}' is not in completed state")
            print(f"\nCompleted tasks:")
            for completed_task in orchestrator.state.get_completed_tasks():
                print(f"  - {completed_task}")
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
    
    # Get stage from custom_variables (defines where to stop in initial run)
    stage = orchestrator.config.get_custom_variable('stage')
    if stage:
        logger.info(f"Stage parameter found: '{stage}' - initial run will stop at this task")
    else:
        logger.info("No stage parameter found - will execute all tasks")
    
    # Setup /etc/hosts, SSHD, and root password on local machine (raptor)
    orchestrator.register_task(
        task_id="setup_local_raptor",
        task_fn=lambda: setup_hosts_locally(
            all_machines=machines,
            logger=logger,
            configure_sshd=True,
            root_password=root_password,
            verbose=args.verbose
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
                    root_password=root_password,
                    verbose=args.verbose
                ),
                description=f"Setup /etc/hosts, SSHD, and root password on {machine_name}"
            )
        else:
            logger.warning(f"Machine {machine_name} not found in configuration")
    
    # Deploy MySQL on raptor
    orchestrator.register_task(
        task_id="deploy_mysql_on_raptor",
        task_fn=lambda: deploy_mysql_on_raptor(logger, verbose=args.verbose),
        description="Deploy and configure MySQL on raptor machine"
    )
    
    # Deploy MongoDB on raptor
    orchestrator.register_task(
        task_id="deploy_mongo_on_raptor",
        task_fn=lambda: deploy_mongo_on_raptor(logger, verbose=args.verbose),
        description="Deploy and configure MongoDB on raptor machine"
    )

    # Marker task: End of initial configuration phase
    # This task does nothing but serves as a checkpoint for stage mechanism
    # Use stage="initial_config" in machines_info.json to stop here
    orchestrator.register_task(
        task_id="initial_config",
        task_fn=lambda: True,  # Empty task - always succeeds
        description="Initial configuration completed - checkpoint for stage mechanism"
    )
    
    # Add more tasks here - they will be executed only when running with --continue flag

    # Determine stop_at parameter
    # Priority: --stop-at argument > stage from machines_info.json
    stop_at_task = args.stop_at if args.stop_at else stage
    
    # Validate stop_at task exists if specified (after all tasks are registered)
    if stop_at_task and not args.continue_mode:
        task_ids = [task_id for task_id, _, _ in orchestrator.tasks]
        if stop_at_task not in task_ids:
            logger.error(f"Stage task '{stop_at_task}' not found in registered tasks")
            logger.error(f"Available task IDs: {', '.join(task_ids)}")
            return 1
    
    # Run all tasks
    success = orchestrator.run_all_tasks(
        stop_at=stop_at_task,
        continue_mode=args.continue_mode
    )
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

# Made with Bob

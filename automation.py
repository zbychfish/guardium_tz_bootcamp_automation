#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Machine Automation Framework
Main orchestration script for managing machine configuration tasks using groups
"""

import sys
import argparse
import time
from pathlib import Path
from typing import List, Callable, Optional, Dict, Any

# Add core modules to path
sys.path.insert(0, str(Path(__file__).parent / "core"))
sys.path.insert(0, str(Path(__file__).parent / "tasks"))

from core.state_manager import StateManager
from core.config_loader import ConfigLoader
from core.group_manager import GroupManager
from core.logger import setup_logger


class AutomationOrchestrator:
    """
    Main orchestrator for machine automation tasks.
    Manages group and stage execution, state tracking, and error handling.
    """
    
    def __init__(self, config_file: str = "config/config.yaml", 
                 groups_file: str = "config/groups.yaml",
                 state_file: str = "state.json",
                 machines_info_file: str = "/root/machines_info.json", 
                 verbose: bool = False):
        """
        Initialize the orchestrator.
        
        Args:
            config_file: Path to configuration file
            groups_file: Path to groups configuration file
            state_file: Path to state tracking file
            machines_info_file: Path to JSON file containing machine information
            verbose: Enable verbose logging
        """
        self.logger = setup_logger("AutomationOrchestrator")
        self.config = ConfigLoader(config_file, machines_info_file)
        self.group_manager = GroupManager(Path(groups_file))
        self.state = StateManager(state_file)
        self.verbose = verbose
        
        self.logger.info("Automation Orchestrator initialized")
        self.logger.info(f"Config: {config_file}")
        self.logger.info(f"Groups: {groups_file}")
        self.logger.info(f"Machines Info: {machines_info_file}")
        self.logger.info(f"State: {state_file}")
        
        # Log loaded machines
        machines = self.config.get_machines()
        if machines:
            self.logger.info(f"Loaded {len(machines)} machine(s): {', '.join(machines.keys())}")
        else:
            self.logger.warning("No machines loaded from machines_info.json")
        
        # Validate groups configuration
        errors = self.group_manager.validate_groups()
        if errors:
            self.logger.error("Groups configuration validation failed:")
            for group_name, group_errors in errors.items():
                self.logger.error(f"  Group '{group_name}':")
                for error in group_errors:
                    self.logger.error(f"    - {error}")
            raise ValueError("Invalid groups configuration")
    
    def run_stage(self, group_name: str, stage_info: Dict[str, str]) -> bool:
        """
        Execute a single stage within a group.
        
        Args:
            group_name: Name of the group this stage belongs to
            stage_info: Stage information dictionary
            
        Returns:
            True if stage executed successfully, False otherwise
        """
        stage_name = stage_info.get('name', 'unknown')
        stage_key = f"{group_name}.{stage_name}"
        
        # Check if stage is already completed
        if self.state.is_completed(stage_key):
            if self.verbose:
                self.logger.info(f"⏭  Skipping (already completed): {stage_name}")
            else:
                self.logger.info(f"⏭  {stage_name}")
            return True
        
        # Load and execute stage function
        stage_fn = self.group_manager.load_stage_function(stage_info)
        if not stage_fn:
            self.logger.error(f"Failed to load stage function: {stage_name}")
            return False
        
        description = stage_info.get('description', '')
        
        if self.verbose:
            self.logger.info(f"➤  Running: {stage_name}")
            if description:
                self.logger.info(f"   Description: {description}")
        else:
            self.logger.info(f"➤  {stage_name}")
        
        start_time = time.time()
        
        try:
            # Get stage args if provided
            stage_args = stage_info.get('args', {})
            if not isinstance(stage_args, dict):
                stage_args = {}
            
            # Call stage function with config, logger, verbose, and any additional args
            result = stage_fn(self.config, self.logger, self.verbose, **stage_args)
            elapsed_time = time.time() - start_time
            
            if result:
                self.state.mark_completed(stage_key)
                time_str = self._format_time(elapsed_time)
                
                if self.verbose:
                    self.logger.info(f"✓  Completed: {stage_name} (took {time_str})")
                else:
                    self.logger.info(f"✓  {stage_name} ({time_str})")
                return True
            else:
                self.logger.error(f"✗  Failed: {stage_name} (returned False)")
                return False
            
        except Exception as e:
            elapsed_time = time.time() - start_time
            self.logger.error(f"✗  Failed: {stage_name} (after {elapsed_time:.1f}s)")
            self.logger.error(f"   Error: {str(e)}", exc_info=self.verbose)
            return False
    
    def run_group(self, group_name: str) -> bool:
        """
        Execute all stages in a group.
        
        Args:
            group_name: Name of the group to execute
            
        Returns:
            True if all stages completed successfully, False otherwise
        """
        group_info = self.group_manager.get_group_info(group_name)
        if not group_info:
            self.logger.error(f"Group not found: {group_name}")
            return False
        
        self.logger.info("=" * 80)
        self.logger.info(f"GROUP: {group_info.get('name', group_name)}")
        if self.verbose and group_info.get('description'):
            self.logger.info(f"Description: {group_info.get('description')}")
        self.logger.info("=" * 80)
        
        stages = self.group_manager.get_group_stages(group_name)
        
        for stage_info in stages:
            success = self.run_stage(group_name, stage_info)
            if not success:
                self.logger.error(f"Group '{group_name}' execution failed")
                return False
        
        self.logger.info(f"✓ Group '{group_name}' completed successfully")
        return True
    
    def run_single_stage(self, stage_name: str) -> bool:
        """
        Execute a single stage by name, including all preceding stages in the same group.
        This ensures dependencies are met.
        
        Args:
            stage_name: Name of the stage to execute
            
        Returns:
            True if stage executed successfully, False otherwise
        """
        # Find the stage in groups
        result = self.group_manager.find_stage_by_name(stage_name)
        
        if not result:
            self.logger.error(f"Stage '{stage_name}' not found in any group")
            self.logger.info("\nAvailable stages:")
            for group_name in self.group_manager.list_groups():
                stages = self.group_manager.get_group_stages(group_name)
                for stage in stages:
                    self.logger.info(f"  - {stage.get('name')} (in group '{group_name}')")
            return False
        
        group_name, target_stage_info = result
        
        self.logger.info("=" * 80)
        self.logger.info(f"Executing stage: {stage_name}")
        self.logger.info(f"From group: {group_name}")
        self.logger.info(f"Note: All preceding stages in this group will be executed first")
        self.logger.info("=" * 80)
        
        # Get all stages in the group
        all_stages = self.group_manager.get_group_stages(group_name)
        
        # Find the index of target stage
        target_index = -1
        for i, stage in enumerate(all_stages):
            if stage.get('name') == stage_name:
                target_index = i
                break
        
        if target_index == -1:
            self.logger.error(f"Stage '{stage_name}' not found in group stages")
            return False
        
        # Execute all stages up to and including the target stage
        for i in range(target_index + 1):
            stage = all_stages[i]
            success = self.run_stage(group_name, stage)
            if not success:
                self.logger.error(f"Failed at stage '{stage.get('name')}', stopping execution")
                return False
        
        self.logger.info("=" * 80)
        self.logger.info(f"Stage '{stage_name}' and all dependencies completed successfully")
        self.logger.info("=" * 80)
        
        return True
    
    def run_continue(self) -> bool:
        """
        Continue execution from current state - execute all remaining stages in all groups.
        Executes stages in order across all groups, skipping already completed ones.
        
        Returns:
            True if all stages completed successfully, False otherwise
        """
        start_time = time.time()
        
        self.logger.info("=" * 80)
        self.logger.info("CONTINUE MODE: Executing all remaining stages")
        self.logger.info("=" * 80)
        
        all_groups = self.group_manager.list_groups()
        total_executed = 0
        total_skipped = 0
        
        for group_name in all_groups:
            group_info = self.group_manager.get_group_info(group_name)
            if not group_info:
                continue
            
            stages = self.group_manager.get_group_stages(group_name)
            
            # Check if any stage in this group needs execution
            has_pending = False
            for stage in stages:
                stage_key = f"{group_name}.{stage.get('name')}"
                if not self.state.is_completed(stage_key):
                    has_pending = True
                    break
            
            if not has_pending:
                continue  # Skip this group entirely
            
            # Execute this group
            self.logger.info("=" * 80)
            self.logger.info(f"GROUP: {group_info.get('name', group_name)}")
            self.logger.info("=" * 80)
            
            for stage_info in stages:
                stage_name = stage_info.get('name')
                stage_key = f"{group_name}.{stage_name}"
                
                if self.state.is_completed(stage_key):
                    if self.verbose:
                        self.logger.info(f"⏭  Skipping (already completed): {stage_name}")
                    else:
                        self.logger.info(f"⏭  {stage_name}")
                    total_skipped += 1
                    continue
                
                success = self.run_stage(group_name, stage_info)
                if not success:
                    total_time = time.time() - start_time
                    self.logger.error(f"Stage '{stage_name}' failed. Stopping.")
                    self.logger.error(f"Total execution time: {self._format_time(total_time)}")
                    return False
                
                total_executed += 1
            
            self.logger.info(f"✓ Group '{group_name}' completed")
        
        total_time = time.time() - start_time
        self.logger.info("=" * 80)
        self.logger.info("CONTINUE MODE: All remaining stages completed successfully")
        self.logger.info(f"Executed: {total_executed} stages")
        self.logger.info(f"Skipped: {total_skipped} stages (already completed)")
        self.logger.info(f"Total execution time: {self._format_time(total_time)}")
        self.logger.info("=" * 80)
        
        return True
    
    def run_all_groups(self, specific_groups: Optional[List[str]] = None) -> bool:
        """
        Execute groups in sequence.
        
        Args:
            specific_groups: Optional list of specific groups to run. If None, runs auto_execute groups.
            
        Returns:
            True if all groups completed successfully, False otherwise
        """
        start_time = time.time()
        
        # Determine which groups to run
        if specific_groups:
            groups_to_run = specific_groups
            mode = f"SPECIFIC GROUPS: {', '.join(specific_groups)}"
        else:
            groups_to_run = self.group_manager.get_auto_execute_groups()
            mode = "AUTO-EXECUTE GROUPS (before marker)"
        
        self.logger.info("=" * 80)
        self.logger.info("Starting automation execution")
        self.logger.info(f"Mode: {mode}")
        self.logger.info(f"Groups to execute: {len(groups_to_run)}")
        self.logger.info("=" * 80)
        
        for group_name in groups_to_run:
            success = self.run_group(group_name)
            if not success:
                total_time = time.time() - start_time
                self.logger.error("Group execution failed. Stopping.")
                self.logger.error(f"Total execution time: {self._format_time(total_time)}")
                return False
        
        total_time = time.time() - start_time
        self.logger.info("=" * 80)
        self.logger.info("Automation execution completed successfully")
        self.logger.info(f"Total execution time: {self._format_time(total_time)}")
        self.logger.info("=" * 80)
        return True
    
    def _format_time(self, seconds: float) -> str:
        """Format time in seconds to human-readable string."""
        if seconds < 60:
            return f"{seconds:.1f}s"
        else:
            minutes = int(seconds // 60)
            remaining_seconds = seconds % 60
            return f"{minutes}m {remaining_seconds:.1f}s"
    
    def reset_state(self):
        """Reset state to start fresh."""
        self.state.reset()
        self.logger.info("State reset - all stages will be re-executed")
    
    def show_status(self):
        """Display current execution status."""
        completed = self.state.get_completed_tasks()
        
        print("\n" + "=" * 80)
        print("AUTOMATION STATUS")
        print("=" * 80)
        
        all_groups = self.group_manager.list_groups()
        
        for group_name in all_groups:
            group_info = self.group_manager.get_group_info(group_name)
            if not group_info:
                continue
            
            auto = "AUTO" if group_info.get('auto_execute') else "MANUAL"
            print(f"\n[{auto}] {group_name}: {group_info.get('name')}")
            print(f"  {group_info.get('description')}")
            
            stages = self.group_manager.get_group_stages(group_name)
            completed_count = 0
            
            for stage_info in stages:
                stage_name = stage_info.get('name')
                stage_key = f"{group_name}.{stage_name}"
                
                if stage_key in completed:
                    print(f"    ✓ {stage_name}")
                    completed_count += 1
                else:
                    print(f"    ○ {stage_name}")
            
            print(f"  Progress: {completed_count}/{len(stages)} stages completed")
        
        print("\n" + "=" * 80)
        print(f"Total completed stages: {len(completed)}")
        print("=" * 80 + "\n")
    
    def list_groups(self):
        """Display all available groups."""
        self.group_manager.print_groups_summary()


def main():
    """Main entry point for the automation framework."""
    parser = argparse.ArgumentParser(
        description="Machine Automation Framework with Groups",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Path to configuration file (default: config/config.yaml)"
    )
    
    parser.add_argument(
        "--groups-config",
        default="config/groups.yaml",
        help="Path to groups configuration file (default: config/groups.yaml)"
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
        "--group",
        dest="groups",
        action="append",
        help="Execute specific group(s). Can be used multiple times."
    )
    
    parser.add_argument(
        "--stage",
        help="Execute a single stage by name (includes all preceding stages in the same group)"
    )
    
    parser.add_argument(
        "--continue",
        dest="continue_mode",
        action="store_true",
        help="Continue execution from current state - execute all remaining stages in all groups"
    )
    
    parser.add_argument(
        "--list-groups",
        action="store_true",
        help="List all available groups and their stages"
    )
    
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset state and start from beginning"
    )
    
    parser.add_argument(
        "--remove-stage",
        metavar="GROUP.STAGE",
        help="Remove specific stage from completed state (format: group_name.stage_name)"
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
        help="Enable verbose output"
    )
    
    args = parser.parse_args()
    
    # Initialize orchestrator
    try:
        orchestrator = AutomationOrchestrator(
            config_file=args.config,
            groups_file=args.groups_config,
            state_file=args.state,
            machines_info_file=args.machines_info,
            verbose=args.verbose
        )
    except Exception as e:
        print(f"Failed to initialize orchestrator: {e}")
        return 1
    
    # Handle special commands
    if args.reset:
        orchestrator.reset_state()
        return 0
    
    if args.list_groups:
        orchestrator.list_groups()
        return 0
    
    if args.remove_stage:
        stage_key = args.remove_stage
        completed_tasks = orchestrator.state.get_completed_tasks()
        
        # Try exact match first
        if stage_key in completed_tasks:
            orchestrator.state.remove_task(stage_key)
            print(f"✓ Stage '{stage_key}' removed from completed state")
            print(f"  Stage will be re-executed on next run")
        else:
            # Try partial match (stage name without group prefix)
            matching_tasks = [task for task in completed_tasks if task.endswith(f".{stage_key}")]
            
            if len(matching_tasks) == 1:
                full_key = matching_tasks[0]
                orchestrator.state.remove_task(full_key)
                print(f"✓ Stage '{full_key}' removed from completed state")
                print(f"  Stage will be re-executed on next run")
            elif len(matching_tasks) > 1:
                print(f"✗ Multiple stages match '{stage_key}':")
                for task in matching_tasks:
                    print(f"  - {task}")
                print(f"\nPlease specify the full stage key (GROUP.STAGE)")
            else:
                print(f"✗ Stage '{stage_key}' is not in completed state")
                print(f"\nCompleted stages:")
                for completed_stage in completed_tasks:
                    print(f"  - {completed_stage}")
        return 0
    
    if args.status:
        orchestrator.show_status()
        return 0
    
    # Continue mode - execute all remaining stages
    if args.continue_mode:
        success = orchestrator.run_continue()
        return 0 if success else 1
    
    # Execute single stage if specified
    if args.stage:
        success = orchestrator.run_single_stage(args.stage)
        return 0 if success else 1
    
    # Run groups (specific or auto-execute)
    success = orchestrator.run_all_groups(specific_groups=args.groups)
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

# Made with Bob

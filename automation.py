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
                 skip_deps: bool = False):
        self.logger = setup_logger("AutomationOrchestrator")
        self.config = ConfigLoader(config_file, machines_info_file)
        self.group_manager = GroupManager(Path(groups_file))
        self.state = StateManager(state_file)
        self.skip_deps = skip_deps
        
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

        if self.state.is_completed(stage_key):
            print(f"  ⏭  {stage_name}")
            self.logger.info(f"Skipping (already completed): {stage_key}")
            return True

        stage_fn = self.group_manager.load_stage_function(stage_info)
        if not stage_fn:
            self.logger.error(f"Failed to load stage function: {stage_name}")
            return False

        print(f"  ➤  {stage_name}")
        self.logger.info(f"Running stage: {stage_key}")

        pre_delay = stage_info.get('pre_delay_seconds', 0)
        if pre_delay:
            print(f"  ⌛ Waiting {pre_delay}s...")
            self.logger.info(f"Pre-delay {pre_delay}s before {stage_name}")
            time.sleep(pre_delay)

        start_time = time.time()

        try:
            stage_args = stage_info.get('args', {})
            if not isinstance(stage_args, dict):
                stage_args = {}

            result = stage_fn(self.config, self.logger, **stage_args)
            elapsed_time = time.time() - start_time
            time_str = self._format_time(elapsed_time)

            if result:
                self.state.mark_completed(stage_key)
                print(f"  ✓  {stage_name} ({time_str})")
                self.logger.info(f"Stage completed: {stage_key} ({time_str})")
                return True
            else:
                print(f"  ✗  {stage_name} — FAILED")
                self.logger.error(f"Stage failed: {stage_key} (returned False)")
                return False

        except Exception as e:
            elapsed_time = time.time() - start_time
            print(f"  ✗  {stage_name} — ERROR ({elapsed_time:.1f}s)")
            self.logger.error(f"Stage error: {stage_key} after {elapsed_time:.1f}s — {str(e)}", exc_info=True)
            return False
    
    def run_group(self, group_name: str, skip_dependency_check: Optional[bool] = None) -> bool:
        """
        Execute all stages in a group.
        
        Args:
            group_name: Name of the group to execute
            skip_dependency_check: If True, skip dependency validation. If None, uses self.skip_deps (default: None)
            
        Returns:
            True if all stages completed successfully, False otherwise
        """
        group_info = self.group_manager.get_group_info(group_name)
        if not group_info:
            self.logger.error(f"Group not found: {group_name}")
            return False
        
        # Check if all stages in this group are already completed
        # If so, mark the group as completed automatically
        stages = self.group_manager.get_group_stages(group_name)
        all_stages_completed = True
        for stage_info in stages:
            stage_name = stage_info.get('name')
            stage_key = f"{group_name}.{stage_name}"
            if not self.state.is_completed(stage_key):
                all_stages_completed = False
                break
        
        if all_stages_completed and not self.state.is_group_completed(group_name):
            self.logger.info(f"All stages already completed for group '{group_name}', marking done.")
            self.state.mark_group_completed(group_name)

        should_skip = skip_dependency_check if skip_dependency_check is not None else self.skip_deps

        if not should_skip:
            completed_groups = self.state.get_completed_groups()
            deps_satisfied, missing_deps = self.group_manager.check_dependencies(group_name, completed_groups)

            if not deps_satisfied:
                self.logger.info(f"Resolving dependencies for '{group_name}': {', '.join(missing_deps)}")
                for dep_group in missing_deps:
                    self.logger.info(f"Executing dependency group: {dep_group}")
                    if not self.run_group(dep_group, skip_dependency_check=False):
                        self.logger.error(f"Dependency group '{dep_group}' failed")
                        return False

        group_display = group_info.get('name', group_name)
        print(f"\n▶ GROUP: {group_display}")
        self.logger.info(f"Starting group: {group_name} ({group_display})")
        
        stages = self.group_manager.get_group_stages(group_name)

        for stage_info in stages:
            if not self.run_stage(group_name, stage_info):
                self.logger.error(f"Group '{group_name}' execution failed")
                return False

        self.state.mark_group_completed(group_name)
        self.logger.info(f"Group completed: {group_name}")
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
            
            print(f"\n▶ GROUP: {group_info.get('name', group_name)}")

            for stage_info in stages:
                stage_name = stage_info.get('name')
                stage_key = f"{group_name}.{stage_name}"

                if self.state.is_completed(stage_key):
                    print(f"  ⏭  {stage_name}")
                    total_skipped += 1
                    continue

                if not self.run_stage(group_name, stage_info):
                    total_time = time.time() - start_time
                    self.logger.error(f"Stage '{stage_name}' failed after {self._format_time(total_time)}")
                    return False

                total_executed += 1

        total_time = time.time() - start_time
        print(f"\n✓ Done — {total_executed} executed, {total_skipped} skipped ({self._format_time(total_time)})")
        self.logger.info(f"Continue mode done: {total_executed} executed, {total_skipped} skipped, {self._format_time(total_time)}")
        
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
            deployment_type = self.config.get_custom_variable('deployment_type') or self.config.get('deployment.deployment_type', '')
            if not deployment_type:
                self.logger.error("deployment_type not found in custom_variables or deployment config")
                return False
            groups_to_run = self.group_manager.get_groups_for_deployment(deployment_type)
            mode = f"DEPLOYMENT TYPE: {deployment_type} ({len(groups_to_run)} groups)"
        
        print(f"▶ {mode}")
        self.logger.info(f"Starting execution: {mode}")

        for group_name in groups_to_run:
            if not self.run_group(group_name):
                total_time = time.time() - start_time
                self.logger.error(f"Execution failed at group '{group_name}' after {self._format_time(total_time)}")
                return False

        total_time = time.time() - start_time
        print(f"\n✓ Completed ({self._format_time(total_time)})")
        self.logger.info(f"Execution completed: {self._format_time(total_time)}")
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
            
            deployed_with = group_info.get('deployed_with', [])
            print(f"\n[{', '.join(deployed_with) or 'manual'}] {group_name}: {group_info.get('name')}")
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
        "--skip-deps",
        action="store_true",
        help="Skip dependency checks when executing groups (use with caution)"
    )
    
    args = parser.parse_args()
    
    # Initialize orchestrator
    try:
        orchestrator = AutomationOrchestrator(
            config_file=args.config,
            groups_file=args.groups_config,
            state_file=args.state,
            machines_info_file=args.machines_info,
            skip_deps=args.skip_deps
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

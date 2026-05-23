#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Core Module
Core functionality for the machine automation framework
"""

# Classes
from .state_manager import StateManager      # Track and persist task execution state
from .config_loader import ConfigLoader      # Load and manage configuration from YAML and JSON
from .ssh_client import SSHClient            # Execute commands on remote machines via SSH

# Logging
from .logger import setup_logger             # Configure logging for a module
from .logger import get_logger               # Get logger instance for a module

# Utilities
from .utils import get_env                   # Get environment variable value
from .utils import require_env               # Get required environment variable or raise error
from .utils import strip_ansi                # Remove ANSI escape sequences from text
from .utils import parse_key_value           # Extract value from text using regex
from .utils import ensure_directory          # Create directory if it doesn't exist
from .utils import read_file                 # Read file contents
from .utils import write_file                # Write content to file
from .utils import modify_config_file        # Advanced file modification (insert/replace/append)
from .utils import retry                     # Retry function execution on failure
from .utils import wait_for_condition        # Wait for a condition to become true
from .utils import run_local_command         # Execute command locally (returns CompletedProcess)
from .utils import execute_local_command     # Execute command locally (returns dict with rc/stdout/stderr)
from .utils import execute_commands          # Execute list of commands sequentially
from .utils import execute_mysql_sql         # Execute SQL commands in MySQL
from .utils import execute_mongo_js          # Execute JavaScript commands in MongoDB
from .utils import validate_ip               # Validate IP address format
from .utils import validate_hostname         # Validate hostname format
from .utils import download_file             # Download file from URL
from .utils import extract_zip               # Extract ZIP archive
from .utils import download_and_extract      # Download and extract ZIP in one step

__all__ = [
    'StateManager',
    'ConfigLoader',
    'setup_logger',
    'get_logger',
    'SSHClient',
    'get_env',
    'require_env',
    'strip_ansi',
    'parse_key_value',
    'ensure_directory',
    'read_file',
    'write_file',
    'modify_config_file',
    'retry',
    'wait_for_condition',
    'run_local_command',
    'execute_local_command',
    'execute_commands',
    'execute_mysql_sql',
    'execute_mongo_js',
    'validate_ip',
    'validate_hostname',
    'download_file',
    'extract_zip',
    'download_and_extract'
]

# Made with Bob

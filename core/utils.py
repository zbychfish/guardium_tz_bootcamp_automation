#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utilities Module
Common utility functions for the automation framework
"""

import os
import re
import time
import subprocess
from typing import Optional, Any, Callable
from pathlib import Path
from .logger import get_logger

logger = get_logger("Utils")


# ============================================================================
# Environment Variables
# ============================================================================

def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    Get environment variable value.
    
    Args:
        key: Environment variable name
        default: Default value if not found
        
    Returns:
        Environment variable value or default
    """
    return os.getenv(key, default)


def require_env(key: str) -> str:
    """
    Get required environment variable or raise error.
    
    Args:
        key: Environment variable name
        
    Returns:
        Environment variable value
        
    Raises:
        ValueError: If environment variable not found
    """
    value = os.getenv(key)
    if value is None:
        raise ValueError(f"Required environment variable not found: {key}")
    return value


# ============================================================================
# Text Processing
# ============================================================================

def strip_ansi(text: str) -> str:
    """
    Remove ANSI escape sequences from text.
    
    Args:
        text: Text containing ANSI codes
        
    Returns:
        Text with ANSI codes removed
    """
    ansi_pattern = re.compile(r'\x1B\[[0-9;?]*[ -/]*[@-~]')
    return ansi_pattern.sub('', text)


def parse_key_value(
    text: str,
    pattern: str,
    group: int = 1
) -> Optional[str]:
    """
    Extract value from text using regex pattern.
    
    Args:
        text: Text to search
        pattern: Regex pattern
        group: Capture group number (default: 1)
        
    Returns:
        Matched value or None
    """
    match = re.search(pattern, text)
    return match.group(group) if match else None


# ============================================================================
# File Operations
# ============================================================================

def ensure_directory(path: str) -> Path:
    """
    Ensure directory exists, create if necessary.
    
    Args:
        path: Directory path
        
    Returns:
        Path object
    """
    dir_path = Path(path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def read_file(path: str, encoding: str = 'utf-8') -> str:
    """
    Read file contents.
    
    Args:
        path: File path
        encoding: File encoding (default: utf-8)
        
    Returns:
        File contents as string
    """
    with open(path, 'r', encoding=encoding) as f:
        return f.read()


def write_file(path: str, content: str, encoding: str = 'utf-8'):
    """
    Write content to file.
    
    Args:
        path: File path
        content: Content to write
        encoding: File encoding (default: utf-8)
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(file_path, 'w', encoding=encoding) as f:
        f.write(content)


# ============================================================================
# Retry Logic
# ============================================================================

def retry(
    func: Callable,
    max_attempts: int = 3,
    delay: int = 5,
    exceptions: tuple = (Exception,)
) -> Any:
    """
    Retry function execution on failure.
    
    Args:
        func: Function to execute
        max_attempts: Maximum number of attempts
        delay: Delay between attempts in seconds
        exceptions: Tuple of exceptions to catch
        
    Returns:
        Function return value
        
    Raises:
        Last exception if all attempts fail
    """
    last_exception = None
    
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except exceptions as e:
            last_exception = e
            logger.warning(f"Attempt {attempt}/{max_attempts} failed: {e}")
            
            if attempt < max_attempts:
                logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
    
    logger.error(f"All {max_attempts} attempts failed")
    raise last_exception


def wait_for_condition(
    condition_func: Callable[[], bool],
    timeout: int = 300,
    interval: int = 10,
    description: str = "condition"
) -> bool:
    """
    Wait for a condition to become true.
    
    Args:
        condition_func: Function that returns True when condition is met
        timeout: Maximum time to wait in seconds
        interval: Check interval in seconds
        description: Description for logging
        
    Returns:
        True if condition met, False if timeout
    """
    logger.info(f"Waiting for {description}...")
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        if condition_func():
            logger.info(f"✓ {description} met")
            return True
        
        time.sleep(interval)
    
    logger.error(f"✗ Timeout waiting for {description}")
    return False


# ============================================================================
# Command Execution
# ============================================================================

def run_local_command(
    command: str,
    shell: bool = True,
    timeout: Optional[int] = None,
    check: bool = True
) -> subprocess.CompletedProcess:
    """
    Execute command locally.
    
    Args:
        command: Command to execute
        shell: Execute in shell (default: True)
        timeout: Command timeout in seconds
        check: Raise exception on non-zero exit code
        
    Returns:
        CompletedProcess object
    """
    logger.debug(f"Executing local command: {command}")
    
    result = subprocess.run(
        command,
        shell=shell,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check
    )
    
    return result


# ============================================================================
# Validation
# ============================================================================

def validate_ip(ip: str) -> bool:
    """
    Validate IP address format.
    
    Args:
        ip: IP address string
        
    Returns:
        True if valid IP, False otherwise
    """
    pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(pattern, ip):
        return False
    
    octets = ip.split('.')
    return all(0 <= int(octet) <= 255 for octet in octets)


def validate_hostname(hostname: str) -> bool:
    """
    Validate hostname format.
    
    Args:
        hostname: Hostname string
        
    Returns:
        True if valid hostname, False otherwise
    """
    pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$'
    return bool(re.match(pattern, hostname))

# Made with Bob

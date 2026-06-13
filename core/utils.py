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
import zipfile
import requests
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


def append_to_file(path: str, content: str, encoding: str = 'utf-8', ensure_newline: bool = True):
    """
    Append content to file. Creates file if it doesn't exist.
    
    Args:
        path: File path
        content: Content to append
        encoding: File encoding (default: utf-8)
        ensure_newline: Add newline before content if file doesn't end with one (default: True)
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Check if file exists and doesn't end with newline
    needs_newline = False
    if ensure_newline and file_path.exists():
        with open(file_path, 'r', encoding=encoding) as f:
            existing = f.read()
            if existing and not existing.endswith('\n'):
                needs_newline = True
    
    with open(file_path, 'a', encoding=encoding) as f:
        if needs_newline:
            f.write('\n')
        f.write(content)


def modify_config_file(
    path: str,
    content: str,
    mode: str = 'append',
    pattern: Optional[str] = None,
    line_number: Optional[int] = None,
    encoding: str = 'utf-8',
    backup: bool = True,
    logger=None
) -> bool:
    """
    Advanced file modification function for config files.
    
    Modes:
    - 'append': Add content at the end of file
    - 'prepend': Add content at the beginning of file
    - 'after': Add content after line matching pattern
    - 'before': Add content before line matching pattern
    - 'replace': Replace line matching pattern with content
    - 'insert': Insert content at specific line number (1-based)
    
    Args:
        path: File path
        content: Content to add/replace
        mode: Operation mode (default: 'append')
        pattern: Regex pattern to match line (for after/before/replace modes)
        line_number: Line number for insert mode (1-based)
        encoding: File encoding (default: utf-8)
        backup: Create backup file before modification (default: True)
        logger: Logger instance for logging operations
        
    Returns:
        True if successful, False otherwise
        
    Examples:
        # Append to end
        modify_config_file('/etc/config', 'new_setting=value', mode='append')
        
        # Insert at line 10
        modify_config_file('/etc/config', 'new_line', mode='insert', line_number=10)
        
        # Add after pattern
        modify_config_file('/etc/config', 'security:\n  enabled: true',
                          mode='after', pattern=r'^# Security')
        
        # Replace line
        modify_config_file('/etc/config', 'port=8080',
                          mode='replace', pattern=r'^port=')
    """
    log = logger if logger else globals()['logger']
    file_path = Path(path)
    
    try:
        # Create file if doesn't exist
        if not file_path.exists():
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.touch()
            log.info(f"Created new file: {path}")
        
        # Read existing content
        with open(file_path, 'r', encoding=encoding) as f:
            lines = f.readlines()
        
        # Create backup if requested
        if backup and lines:
            backup_path = f"{path}.backup"
            with open(backup_path, 'w', encoding=encoding) as f:
                f.writelines(lines)
            log.debug(f"Created backup: {backup_path}")
        
        # Ensure content ends with newline if it doesn't
        if content and not content.endswith('\n'):
            content = content + '\n'
        
        # Process based on mode
        new_lines = []
        modified = False
        
        if mode == 'append':
            new_lines = lines + [content]
            modified = True
            
        elif mode == 'prepend':
            new_lines = [content] + lines
            modified = True
            
        elif mode == 'insert':
            if line_number is None:
                log.error("line_number required for insert mode")
                return False
            # Convert to 0-based index
            idx = line_number - 1
            if idx < 0:
                idx = 0
            elif idx > len(lines):
                idx = len(lines)
            new_lines = lines[:idx] + [content] + lines[idx:]
            modified = True
            
        elif mode in ['after', 'before', 'replace']:
            if pattern is None:
                log.error(f"pattern required for {mode} mode")
                return False
            
            import re
            pattern_re = re.compile(pattern)
            
            for i, line in enumerate(lines):
                if pattern_re.search(line):
                    if mode == 'after':
                        new_lines.append(line)
                        new_lines.append(content)
                    elif mode == 'before':
                        new_lines.append(content)
                        new_lines.append(line)
                    elif mode == 'replace':
                        new_lines.append(content)
                    modified = True
                else:
                    new_lines.append(line)
            
            if not modified:
                log.warning(f"Pattern not found: {pattern}")
                return False
        else:
            log.error(f"Unknown mode: {mode}")
            return False
        
        # Write modified content
        if modified:
            with open(file_path, 'w', encoding=encoding) as f:
                f.writelines(new_lines)
            log.info(f"Modified file: {path} (mode: {mode})")
            return True
        
        return False
        
    except Exception as e:
        log.error(f"Error modifying file {path}: {e}")
        return False


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
    last_exception: Optional[Exception] = None
    
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
    if last_exception:
        raise last_exception
    else:
        raise RuntimeError("All retry attempts failed but no exception was captured")


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


def execute_local_command(command: str, logger=None, verbose: bool = True) -> dict:
    """
    Execute a command locally as root and return detailed result.
    
    This is a higher-level wrapper around run_local_command() that:
    - Logs command execution
    - Returns dict with rc, stdout, stderr
    - Logs output and errors
    
    Args:
        command: Command to execute
        logger: Logger instance (uses module logger if None)
        verbose: If True, log command and output; if False, only log errors
        
    Returns:
        Dictionary with 'rc' (return code), 'stdout', and 'stderr'
    """
    log = logger if logger else globals()['logger']
    
    if verbose:
        log.info(f"Executing: {command}")
    
    try:
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate()
        
        result = {
            'rc': process.returncode,
            'stdout': stdout.strip(),
            'stderr': stderr.strip()
        }
        
        if result['rc'] == 0:
            if verbose and result['stdout']:
                log.info(f"Output: {result['stdout']}")
        else:
            log.error(f"Command failed with return code {result['rc']}")
            if result['stderr']:
                log.error(f"Error: {result['stderr']}")
        
        return result
        
    except Exception as e:
        log.error(f"Exception executing command: {e}")
        return {
            'rc': 1,
            'stdout': '',
            'stderr': str(e)
        }


def execute_commands(commands: list, logger=None, verbose: bool = True, stop_on_error: bool = True) -> bool:
    """
    Execute a list of shell commands sequentially.
    
    Args:
        commands: List of command strings to execute
        logger: Logger instance (uses module logger if None)
        verbose: Enable verbose logging (default: True)
        stop_on_error: Stop execution if a command fails (default: True)
        
    Returns:
        True if all commands succeeded, False if any failed
        
    Example:
        >>> commands = [
        ...     "dnf update -y",
        ...     "dnf install -y mysql-server",
        ...     "systemctl start mysqld"
        ... ]
        >>> execute_commands(commands, logger)
    """
    log = logger if logger else globals()['logger']
    
    total = len(commands)
    failed_commands = []
    
    for i, command in enumerate(commands, 1):
        if verbose:
            log.info(f"Step {i}/{total}: {command}")
        
        result = execute_local_command(command, log, verbose)
        
        if result['rc'] != 0:
            log.error(f"Command failed: {command}")
            failed_commands.append(command)
            
            if stop_on_error:
                log.error(f"Stopping execution due to error")
                return False
    
    if failed_commands:
        log.error(f"Failed commands: {len(failed_commands)}/{total}")
        for cmd in failed_commands:
            log.error(f"  - {cmd}")
        return False
    
    if verbose:
        log.info(f"✓ All {total} commands executed successfully")
    
    return True


# ============================================================================
# Database Operations
# ============================================================================

def execute_mysql_sql(
    sql_commands: str,
    username: str = "root",
    password: str = "",
    host: str = "localhost",
    database: str = "",
    additional_options: str = "",
    logger=None,
    verbose: bool = True
) -> dict:
    """
    Execute SQL commands in MySQL.
    
    This is a general-purpose function for executing SQL in MySQL.
    Creates a temporary SQL file, executes it, and cleans up.
    
    Args:
        sql_commands: SQL commands to execute (can be multi-line)
        username: MySQL username (default: root)
        password: MySQL password (default: empty)
        host: MySQL host (default: localhost)
        database: Database name (default: empty - no database selected)
        additional_options: Additional mysql CLI options (e.g., "--connect-expired-password")
        logger: Logger instance (uses module logger if None)
        verbose: If True, log command and output; if False, only log errors
        
    Returns:
        Dictionary with 'rc' (return code), 'stdout', and 'stderr'
    """
    import tempfile
    import os
    
    log = logger if logger else globals()['logger']
    
    if verbose:
        log.info(f"Executing SQL commands as {username}@{host}")
    
    # Create temporary SQL file
    fd, sql_file = tempfile.mkstemp(suffix='.sql', text=True)
    try:
        # Write SQL commands to file
        with os.fdopen(fd, 'w') as f:
            f.write(sql_commands)
        
        # Build mysql command using config file for password (safer than command line)
        config_fd, config_file = tempfile.mkstemp(suffix='.cnf', text=True)
        try:
            # Write MySQL config file with password
            with os.fdopen(config_fd, 'w') as f:
                f.write("[client]\n")
                f.write(f"user={username}\n")
                if password:
                    # Escape special characters for MySQL config file
                    escaped_password = password.replace('\\', '\\\\').replace('"', '\\"')
                    f.write(f'password="{escaped_password}"\n')
                if host != "localhost":
                    f.write(f"host={host}\n")
            
            # Set restrictive permissions on config file
            os.chmod(config_file, 0o600)
            
            # Build mysql command using config file
            mysql_cmd = f"mysql --defaults-extra-file={config_file}"
            
            if database:
                mysql_cmd += f" {database}"
            
            if additional_options:
                mysql_cmd += f" {additional_options}"
            
            mysql_cmd += f" < {sql_file}"
            
            # Execute SQL
            result = execute_local_command(mysql_cmd, log, verbose)
            
            return result
            
        finally:
            # Clean up config file
            if os.path.exists(config_file):
                os.remove(config_file)
        
    finally:
        # Clean up temporary file
        if os.path.exists(sql_file):
            os.remove(sql_file)


def execute_mongo_js(
    js_commands: str,
    username: str = "",
    password: str = "",
    host: str = "localhost",
    port: int = 27017,
    database: str = "admin",
    auth_database: str = "admin",
    additional_options: str = "",
    logger=None,
    verbose: bool = True
) -> dict:
    """
    Execute JavaScript commands in MongoDB using mongosh.
    
    This is a general-purpose function for executing JavaScript in MongoDB.
    Creates a temporary JS file, executes it, and cleans up.
    
    Args:
        js_commands: JavaScript commands to execute (can be multi-line)
        username: MongoDB username (default: empty - no auth)
        password: MongoDB password (default: empty)
        host: MongoDB host (default: localhost)
        port: MongoDB port (default: 27017)
        database: Database to connect to (default: admin)
        auth_database: Authentication database (default: admin)
        additional_options: Additional mongosh CLI options
        logger: Logger instance (uses module logger if None)
        verbose: If True, log command and output; if False, only log errors
        
    Returns:
        Dictionary with 'rc' (return code), 'stdout', and 'stderr'
    """
    import tempfile
    import os
    
    log = logger if logger else globals()['logger']
    
    if verbose:
        log.info(f"Executing MongoDB JavaScript commands on {host}:{port}/{database}")
    
    # Create temporary JS file
    fd, js_file = tempfile.mkstemp(suffix='.js', text=True)
    try:
        # Write JS commands to file
        with os.fdopen(fd, 'w') as f:
            f.write(js_commands)
        
        # Build mongosh command
        mongosh_cmd = f"mongosh"
        
        if username and password:
            mongosh_cmd += f" --username {username} --password '{password}'"
            if auth_database:
                mongosh_cmd += f" --authenticationDatabase {auth_database}"
        
        mongosh_cmd += f" --host {host} --port {port}"
        
        if database:
            mongosh_cmd += f" {database}"
        
        if additional_options:
            mongosh_cmd += f" {additional_options}"
        
        mongosh_cmd += f" --file {js_file}"
        
        # Execute JavaScript
        result = execute_local_command(mongosh_cmd, log, verbose)
        
        return result
        
    finally:
        # Clean up temporary file
        if os.path.exists(js_file):
            os.remove(js_file)


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



# ============================================================================
# File Download and Extraction
# ============================================================================

def download_file(url: str, destination: str, logger=None, verbose: bool = True) -> bool:
    """
    Download file from URL to destination path.
    
    Args:
        url: URL to download from (e.g., IBM Box shared link)
        destination: Local file path to save to
        logger: Logger instance (uses module logger if None)
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    log = logger if logger else globals()['logger']
    
    try:
        if verbose:
            log.info(f"Downloading file from: {url}")
            log.info(f"Destination: {destination}")
        
        # Ensure destination directory exists
        dest_path = Path(destination)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Download file with streaming to handle large files
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()
        
        # Get file size if available
        total_size = int(response.headers.get('content-length', 0))
        
        # Write file in chunks
        downloaded = 0
        chunk_size = 8192
        
        with open(destination, 'wb') as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # Log progress for large files
                    if verbose and total_size > 0:
                        progress = (downloaded / total_size) * 100
                        if downloaded % (chunk_size * 100) == 0:  # Log every ~800KB
                            log.info(f"Progress: {progress:.1f}% ({downloaded}/{total_size} bytes)")
        
        if verbose:
            log.info(f"✓ File downloaded successfully: {destination}")
            log.info(f"  Size: {downloaded} bytes")
        
        return True
        
    except requests.exceptions.RequestException as e:
        log.error(f"Failed to download file: {e}")
        return False
    except Exception as e:
        log.error(f"Error downloading file: {e}")
        return False


def extract_zip(zip_path: str, extract_to: str, logger=None, verbose: bool = True) -> bool:
    """
    Extract ZIP archive to specified directory.
    
    Args:
        zip_path: Path to ZIP file
        extract_to: Directory to extract files to
        logger: Logger instance (uses module logger if None)
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    log = logger if logger else globals()['logger']
    
    try:
        if verbose:
            log.info(f"Extracting ZIP archive: {zip_path}")
            log.info(f"Extract to: {extract_to}")
        
        # Ensure extract directory exists
        extract_path = Path(extract_to)
        extract_path.mkdir(parents=True, exist_ok=True)
        
        # Extract ZIP file
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Get list of files
            file_list = zip_ref.namelist()
            
            if verbose:
                log.info(f"Archive contains {len(file_list)} file(s)")
            
            # Extract all files
            zip_ref.extractall(extract_to)
            
            if verbose:
                log.info("✓ ZIP archive extracted successfully")
                log.info(f"  Extracted {len(file_list)} file(s) to: {extract_to}")
        
        return True
        
    except zipfile.BadZipFile:
        log.error(f"Invalid ZIP file: {zip_path}")
        return False
    except Exception as e:
        log.error(f"Error extracting ZIP file: {e}")
        return False


def download_and_extract(url: str, extract_to: str, logger=None, verbose: bool = True) -> bool:
    """
    Download ZIP file from URL and extract it to specified directory.
    
    This is a convenience function that combines download_file() and extract_zip().
    The ZIP file is downloaded to a temporary location and deleted after extraction.
    
    Args:
        url: URL to download ZIP from (e.g., IBM Box shared link)
        extract_to: Directory to extract files to
        logger: Logger instance (uses module logger if None)
        verbose: Enable verbose logging (default: True)
        
    Returns:
        True if successful, False otherwise
        
    Example:
        >>> download_and_extract(
        ...     "https://ibm.box.com/shared/static/abc123.zip",
        ...     "upload/",
        ...     logger
        ... )
    """
    log = logger if logger else globals()['logger']
    
    try:
        # Create temporary file for download
        import tempfile
        fd, temp_zip = tempfile.mkstemp(suffix='.zip')
        os.close(fd)
        
        try:
            # Download file
            if not download_file(url, temp_zip, log, verbose):
                return False
            
            # Extract file
            if not extract_zip(temp_zip, extract_to, log, verbose):
                return False
            
            return True
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_zip):
                os.remove(temp_zip)
                if verbose:
                    log.info("Cleaned up temporary ZIP file")
        
    except Exception as e:
        log.error(f"Error in download_and_extract: {e}")
        return False

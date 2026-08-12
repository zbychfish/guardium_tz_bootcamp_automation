#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SSH Client Module
Provides SSH connection and command execution capabilities
"""

import paramiko
import socket
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from .logger import get_logger


class SSHClient:
    """
    SSH client for remote command execution and file operations.
    """
    
    def __init__(
        self,
        host: str,
        username: str = "root",
        password: Optional[str] = None,
        key_file: Optional[str] = None,
        port: int = 22,
        timeout: int = 30
    ):
        """
        Initialize SSH client.
        
        Args:
            host: Hostname or IP address
            username: SSH username (default: root)
            password: SSH password
            key_file: Path to SSH private key file
            port: SSH port (default: 22)
            timeout: Connection timeout in seconds
        """
        self.host = host
        self.username = username
        self.password = password
        self.key_file = key_file
        self.port = port
        self.timeout = timeout
        self.client: Optional[paramiko.SSHClient] = None
        self.logger = get_logger(f"SSHClient[{host}]")
    
    def connect(self) -> bool:
        """
        Establish SSH connection.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            connect_kwargs = {
                'hostname': self.host,
                'port': self.port,
                'username': self.username,
                'timeout': self.timeout,
                'look_for_keys': True,
                'allow_agent': True
            }
            
            if self.password:
                connect_kwargs['password'] = self.password
            
            if self.key_file:
                connect_kwargs['key_filename'] = self.key_file
            
            self.client.connect(**connect_kwargs)
            self.logger.info(f"Connected to {self.host}")
            return True
            
        except (paramiko.SSHException, socket.error) as e:
            self.logger.error(f"Connection failed: {e}")
            return False
    
    def disconnect(self):
        """Close SSH connection."""
        if self.client:
            self.client.close()
            self.logger.info(f"Disconnected from {self.host}")
            self.client = None
    
    def execute_command(
        self,
        command: str,
        timeout: Optional[int] = None,
        print_output: bool = True
    ) -> Dict[str, Any]:
        """
        Execute a single command on remote host.
        
        Args:
            command: Command to execute
            timeout: Command timeout in seconds (None = no timeout)
            print_output: Whether to print output to console
            
        Returns:
            Dictionary with keys: cmd, rc (return code), stdout, stderr
        """
        if not self.client:
            raise RuntimeError("Not connected. Call connect() first.")
        
        self.logger.debug(f"Executing: {command}")
        
        try:
            stdin, stdout, stderr = self.client.exec_command(
                command,
                timeout=timeout
            )
            
            rc = stdout.channel.recv_exit_status()
            out = stdout.read().decode('utf-8', errors='replace')
            err = stderr.read().decode('utf-8', errors='replace')
            
            if print_output:
                if out:
                    print(out)
                if err:
                    print(err)
            
            result = {
                'cmd': command,
                'rc': rc,
                'stdout': out,
                'stderr': err
            }
            
            if rc == 0:
                self.logger.debug(f"Command succeeded (rc={rc})")
            else:
                self.logger.warning(f"Command failed (rc={rc})")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Command execution failed: {e}")
            return {
                'cmd': command,
                'rc': -1,
                'stdout': '',
                'stderr': str(e)
            }
    
    def execute_commands(
        self,
        commands: List[str],
        timeout: Optional[int] = None,
        print_output: bool = True,
        stop_on_error: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Execute multiple commands sequentially.
        
        Args:
            commands: List of commands to execute
            timeout: Command timeout in seconds
            print_output: Whether to print output to console
            stop_on_error: Stop execution if a command fails
            
        Returns:
            List of result dictionaries
        """
        results = []
        
        for cmd in commands:
            result = self.execute_command(cmd, timeout, print_output)
            results.append(result)
            
            if stop_on_error and result['rc'] != 0:
                self.logger.error(f"Stopping due to error in: {cmd}")
                break
        
        return results
    
    def upload_file(
        self,
        local_path: str,
        remote_path: str
    ) -> bool:
        """
        Upload file to remote host via SFTP.
        
        Args:
            local_path: Local file path
            remote_path: Remote destination path
            
        Returns:
            True if successful, False otherwise
        """
        if not self.client:
            raise RuntimeError("Not connected. Call connect() first.")
        
        try:
            sftp = self.client.open_sftp()
            sftp.put(local_path, remote_path)
            sftp.close()
            
            self.logger.info(f"Uploaded: {local_path} -> {remote_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Upload failed: {e}")
            return False
    
    def download_file(
        self,
        remote_path: str,
        local_path: str
    ) -> bool:
        """
        Download file from remote host via SFTP.
        
        Args:
            remote_path: Remote file path
            local_path: Local destination path
            
        Returns:
            True if successful, False otherwise
        """
        if not self.client:
            raise RuntimeError("Not connected. Call connect() first.")
        
        try:
            sftp = self.client.open_sftp()
            sftp.get(remote_path, local_path)
            sftp.close()
            
            self.logger.info(f"Downloaded: {remote_path} -> {local_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Download failed: {e}")
            return False
    
    def file_exists(self, remote_path: str) -> bool:
        """
        Check if file exists on remote host.
        
        Args:
            remote_path: Remote file path
            
        Returns:
            True if file exists, False otherwise
        """
        result = self.execute_command(
            f"test -f {remote_path} && echo 'exists' || echo 'not_exists'",
            print_output=False
        )
        return 'exists' in result['stdout']
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()

# Made with Bob

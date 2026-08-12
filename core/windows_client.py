#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows Client Module
Handles WinRM connections and command execution on Windows machines
"""

import re
import winrm
from typing import Optional, Sequence, Dict, Any
from core.logger import get_logger

logger = get_logger(__name__)


class WindowsClient:
    """
    Windows remote management client using WinRM.
    Provides methods for executing PowerShell and CMD commands on remote Windows machines.
    """
    
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: Optional[int] = None,
        use_ssl: bool = False,
        path: str = "wsman",
        transport: str = "ntlm",
        ca_trust_path: Optional[str] = None,
        server_cert_validation: str = "validate",
        read_timeout_sec: int = 60,
        operation_timeout_sec: int = 40
    ):
        """
        Initialize Windows client.
        
        Args:
            host: Windows machine hostname or IP
            username: Windows username
            password: Windows password
            port: WinRM port (default: 5985 for HTTP, 5986 for HTTPS)
            use_ssl: Use HTTPS instead of HTTP
            path: WinRM path (default: "wsman")
            transport: Authentication transport (ntlm, kerberos, basic, certificate, credssp)
            ca_trust_path: Path to CA bundle for SSL verification
            server_cert_validation: "validate" or "ignore" (for self-signed certs)
            read_timeout_sec: Read timeout in seconds
            operation_timeout_sec: Operation timeout in seconds
        """
        self.host = host
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.transport = transport
        
        scheme = "https" if use_ssl else "http"
        
        # Handle host with port already included
        if re.search(r":\d+$", host):
            endpoint = f"{scheme}://{host}/{path}"
        else:
            if port is None:
                port = 5986 if use_ssl else 5985
            endpoint = f"{scheme}://{host}:{port}/{path}"
        
        self.endpoint = endpoint
        self.session = winrm.Session(
            endpoint,
            auth=(username, password),
            transport=transport,
            server_cert_validation=server_cert_validation,
            ca_trust_path=ca_trust_path,
            read_timeout_sec=read_timeout_sec,
            operation_timeout_sec=operation_timeout_sec,
        )
    
    def execute_powershell(self, command: str, verbose: bool = True) -> Dict[str, Any]:
        """
        Execute PowerShell command on remote Windows machine.
        
        Args:
            command: PowerShell command to execute
            verbose: Enable verbose logging
            
        Returns:
            Dictionary with 'rc' (return code), 'stdout', and 'stderr'
        """
        if verbose:
            logger.info(f"Executing PowerShell on {self.host}: {command[:100]}...")
        
        # Suppress progress and verbose output
        prolog = (
            "$ProgressPreference = 'SilentlyContinue'\n"
            "$VerbosePreference  = 'SilentlyContinue'\n"
            "$DebugPreference    = 'SilentlyContinue'\n"
            "$InformationPreference = 'SilentlyContinue'\n"
        )
        ps_script = prolog + command
        
        try:
            result = self.session.run_ps(ps_script)
            stdout = (result.std_out or b"").decode("utf-8", errors="replace")
            stderr = (result.std_err or b"").decode("utf-8", errors="replace")
            
            if verbose and stdout:
                logger.info(f"Output: {stdout[:500]}")
            if stderr:
                logger.warning(f"Stderr: {stderr[:500]}")
            
            return {
                'rc': result.status_code,
                'stdout': stdout,
                'stderr': stderr
            }
        except Exception as e:
            logger.error(f"PowerShell execution failed: {str(e)}")
            return {
                'rc': -1,
                'stdout': '',
                'stderr': str(e)
            }
    
    def execute_cmd(self, command: str, args: Optional[Sequence[str]] = None, verbose: bool = True) -> Dict[str, Any]:
        """
        Execute CMD command on remote Windows machine.
        
        Args:
            command: CMD command to execute
            args: Command arguments (optional)
            verbose: Enable verbose logging
            
        Returns:
            Dictionary with 'rc' (return code), 'stdout', and 'stderr'
        """
        full_cmd = " ".join([command] + list(args or []))
        if verbose:
            logger.info(f"Executing CMD on {self.host}: {full_cmd}")
        
        try:
            result = self.session.run_cmd(command, args or [])
            stdout = (result.std_out or b"").decode("utf-8", errors="replace")
            stderr = (result.std_err or b"").decode("utf-8", errors="replace")
            
            if verbose and stdout:
                logger.info(f"Output: {stdout[:500]}")
            if stderr:
                logger.warning(f"Stderr: {stderr[:500]}")
            
            return {
                'rc': result.status_code,
                'stdout': stdout,
                'stderr': stderr
            }
        except Exception as e:
            logger.error(f"CMD execution failed: {str(e)}")
            return {
                'rc': -1,
                'stdout': '',
                'stderr': str(e)
            }
    
    def test_connection(self) -> bool:
        """
        Test WinRM connection to Windows machine.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            result = self.execute_powershell("Write-Output 'Connection test'", verbose=False)
            return result['rc'] == 0
        except Exception as e:
            logger.error(f"Connection test failed: {str(e)}")
            return False
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        pass


# Made with Bob
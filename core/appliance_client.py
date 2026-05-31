#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Appliance Client - Class for executing commands on Guardium appliances via SSH
Adapted from guardium_bootcamp_automation/appliance_command.py
"""

import re
import sys
import time
from typing import Optional, Tuple
import paramiko


# ANSI escape sequence pattern
ANSI_RE = re.compile(r"\x1B\[[0-9;?]*[ -/]*[@-~]")


def strip_ansi(s: str) -> str:
    """Remove ANSI escape sequences from text"""
    return ANSI_RE.sub("", s)


def _find_last_prompt_span(text: str, prompt_re: re.Pattern) -> Optional[Tuple[int, int]]:
    """Return (start, end) of the last prompt match"""
    last = None
    for m in prompt_re.finditer(text):
        last = (m.start(), m.end())
    return last


class ApplianceClient:
    """Class for executing commands on Guardium appliances via SSH"""
    
    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        prompt_regex: str,
        port: int = 22,
        timeout: int = 60,
        initial_pattern: Optional[str] = None,
        logout_command: str = "quit",
        strip_ansi: bool = True,
        debug: bool = False
    ):
        """
        Initialize ApplianceClient
        
        Args:
            host: Appliance IP or hostname
            user: SSH username (typically 'cli')
            password: SSH password
            prompt_regex: Regular expression to match command prompt
            port: SSH port (default: 22)
            timeout: Command timeout in seconds (default: 60)
            initial_pattern: Optional pattern to wait for after login (e.g., 'Last login')
            logout_command: Command to logout (default: 'quit')
            strip_ansi: Strip ANSI escape sequences from output (default: True)
            debug: Enable debug output (default: False)
        """
        self.host = host
        self.user = user
        self.password = password
        self.port = port
        self.timeout = timeout
        self.logout_command = logout_command
        self.strip_ansi_flag = strip_ansi
        self.debug = debug
        
        self.prompt_re = re.compile(prompt_regex)
        self.initial_re = re.compile(initial_pattern) if initial_pattern else None
        self.error_re = re.compile(r"^(ERROR:|Error:)", re.MULTILINE)
        
        self.client: Optional[paramiko.SSHClient] = None
        self.channel: Optional[paramiko.Channel] = None
    
    def connect(self) -> bool:
        """
        Establish SSH connection and open shell
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            self.client.connect(
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                look_for_keys=False,
                allow_agent=False,
                timeout=15,
                banner_timeout=15,
                auth_timeout=15,
                compress=True,
            )
            
            self.channel = self.client.invoke_shell(term="xterm", width=200, height=40)
            time.sleep(0.2)
            
            # Nudge prompt
            for _ in range(2):
                self.channel.send(b"\r")
                time.sleep(0.1)
                self.channel.send(b"\n")
                time.sleep(0.1)
            
            # Wait for initial pattern if specified
            if self.initial_re:
                self._read_until_regex(self.initial_re, echo=False)
            
            # Wait for prompt
            self._read_until_regex(self.prompt_re, echo=False)
            
            if self.debug:
                print(f"[DEBUG] Connected to {self.host}", file=sys.stderr)
            
            return True
            
        except Exception as e:
            if self.debug:
                print(f"[ERROR] Connection failed: {e}", file=sys.stderr)
            return False
    
    def _read_until_regex(
        self,
        regex: re.Pattern,
        echo: bool = False,
        timeout: Optional[int] = None
    ) -> str:
        """
        Read output until regex match
        
        Args:
            regex: Regular expression pattern to match
            echo: Print output to stdout (default: False)
            timeout: Optional timeout in seconds (if None, uses self.timeout)
        
        Returns:
            Buffer content up to and including the match
        
        Raises:
            TimeoutError: If timeout reached before match
            RuntimeError: If no channel available
        """
        if not self.channel:
            raise RuntimeError("No channel available")
        
        cmd_timeout = timeout if timeout is not None else self.timeout
        buf = ""
        deadline = time.time() + cmd_timeout
        
        if self.debug:
            print(f"[DEBUG] Waiting for regex: {regex.pattern} (timeout: {cmd_timeout}s)", file=sys.stderr)
        
        while time.time() < deadline:
            if self.channel.recv_ready():
                chunk = self.channel.recv(65535).decode(errors="replace")
                buf += chunk
                
                if self.debug:
                    print(f"[DEBUG] Received chunk ({len(chunk)} bytes): {repr(chunk[:100])}", file=sys.stderr)
                
                if echo:
                    out = strip_ansi(chunk) if self.strip_ansi_flag else chunk
                    sys.stdout.write(out)
                    sys.stdout.flush()
            
            buf_for_match = strip_ansi(buf) if self.strip_ansi_flag else buf
            if regex.search(buf_for_match):
                if self.debug:
                    print(f"[DEBUG] Regex matched! Buffer length: {len(buf)}", file=sys.stderr)
                return buf
            
            if self.channel.closed:
                if self.debug:
                    print(f"[DEBUG] Channel closed", file=sys.stderr)
                break
            
            time.sleep(0.05)
        
        if self.debug:
            print(f"[DEBUG] Timeout! Buffer content: {repr(buf[:500])}", file=sys.stderr)
        
        raise TimeoutError(f"Timeout waiting for: {regex.pattern} (timeout: {cmd_timeout}s)")
    
    def execute_command(self, command: str, timeout: Optional[int] = None) -> str:
        """
        Execute single command and return output
        
        Args:
            command: Command to execute
            timeout: Optional timeout in seconds (if None, uses self.timeout)
        
        Returns:
            Command output (cleaned, without prompt and echo)
        
        Raises:
            RuntimeError: If not connected
        """
        if not self.channel:
            raise RuntimeError("Not connected")
        
        # Flush buffer
        time.sleep(0.05)
        while self.channel.recv_ready():
            self.channel.recv(65535)
        
        # Send command
        self.channel.send((command + "\r\n").encode())
        
        # Read until prompt with optional timeout
        raw = self._read_until_regex(self.prompt_re, echo=False, timeout=timeout)
        
        # Clean output
        working = strip_ansi(raw) if self.strip_ansi_flag else raw
        last_span = _find_last_prompt_span(working, self.prompt_re)
        output_region = working[: last_span[0]] if last_span else working
        
        lines = output_region.splitlines()
        
        # Remove empty lines and command echo
        while lines and not lines[0].strip():
            lines.pop(0)
        
        if lines:
            first = lines[0].rstrip("\r\n")
            if first.strip() == command.strip():
                lines = lines[1:]
        
        # Filter out unwanted lines
        filtered_lines = []
        for line in lines:
            stripped = line.strip()
            # Skip empty lines, "ok", and prompt lines
            if not stripped:
                continue
            if stripped == "ok":
                continue
            if self.prompt_re.search(stripped):
                continue
            filtered_lines.append(line)
        
        return "\n".join(filtered_lines)
    
    def execute_command_with_confirmation(
        self,
        command: str,
        confirmation_pattern: str = r"Do you want to proceed\?\s*\(y/n\)\s*",
        response: str = "y",
        confirm_idle: float = 0.2
    ) -> str:
        """
        Execute command that requires interactive confirmation.
        
        Args:
            command: Command to execute
            confirmation_pattern: Regex pattern for confirmation prompt
            response: Response to send (e.g. 'y', 'n')
            confirm_idle: Wait time for idle before sending response (seconds)
        
        Returns:
            Full command output
        
        Raises:
            RuntimeError: If not connected
            TimeoutError: If timeout reached
        """
        if not self.channel:
            raise RuntimeError("Not connected")
        
        # Flush buffer
        time.sleep(0.03)
        while self.channel.recv_ready():
            self.channel.recv(65535)
        
        # Send command with CR only (no LF)
        if self.debug:
            print(f"[DEBUG] Sending command: {command}", file=sys.stderr)
        self.channel.send((command + "\r").encode())
        
        confirmation_re = re.compile(confirmation_pattern)
        buf = ""
        deadline = time.time() + self.timeout
        confirmed = False
        
        while time.time() < deadline:
            if self.channel.recv_ready():
                chunk = self.channel.recv(65535).decode(errors="replace")
                buf += chunk
            
            buf_for_match = strip_ansi(buf) if self.strip_ansi_flag else buf
            
            # Handle confirmation once when detected
            if (not confirmed) and confirmation_re.search(buf_for_match):
                if self.debug:
                    print(f"[DEBUG] Confirmation pattern matched in buffer")
                    print(f"[DEBUG] Buffer content: {repr(buf_for_match[-200:])}")
                    print(f"[DEBUG] Waiting idle {confirm_idle}s then sending '{response}'")
                
                # Wait until channel is idle
                idle_deadline = time.time() + confirm_idle
                while time.time() < deadline:
                    if self.channel.recv_ready():
                        chunk = self.channel.recv(65535).decode(errors="replace")
                        buf += chunk
                        idle_deadline = time.time() + confirm_idle
                    if time.time() >= idle_deadline:
                        break
                    time.sleep(0.01)
                
                # Send response with CR only
                self.channel.send((response + "\r").encode())
                confirmed = True
                time.sleep(0.02)
            
            # Check if prompt returned
            if self.prompt_re.search(buf_for_match):
                if self.debug:
                    print(f"[DEBUG] Prompt detected after command")
                break
            
            if self.channel.closed:
                raise RuntimeError("Channel closed")
            
            time.sleep(0.005)
        else:
            raise TimeoutError(f"Timeout waiting for prompt: {self.prompt_re.pattern}")
        
        # Clean output
        working = strip_ansi(buf) if self.strip_ansi_flag else buf
        last_span = _find_last_prompt_span(working, self.prompt_re)
        output_region = working[: last_span[0]] if last_span else working
        
        lines = output_region.splitlines()
        return "\n".join(lines)
    
    def disconnect(self):
        """Close SSH connection"""
        try:
            if self.channel:
                # Try to logout gracefully
                try:
                    self.channel.send((self.logout_command + "\r\n").encode())
                    time.sleep(0.5)
                except:
                    pass
                
                self.channel.close()
                self.channel = None
            
            if self.client:
                self.client.close()
                self.client = None
            
            if self.debug:
                print(f"[DEBUG] Disconnected from {self.host}", file=sys.stderr)
        
        except Exception as e:
            if self.debug:
                print(f"[ERROR] Disconnect error: {e}", file=sys.stderr)

# Made with Bob


    def execute_restart_with_check(
        self,
        command: str = "restart system",
        confirmation_pattern: str = r"Are you sure you want to restart the system\s*\(y/n\)\?",
        busy_pattern: str = r"MYSQL is busy updating the database",
        confirm_idle: float = 0.2
    ) -> str:
        """
        Execute system restart with condition - checks if MySQL is busy.
        
        Args:
            command: Restart command
            confirmation_pattern: Regex pattern for confirmation prompt
            busy_pattern: Regex pattern for MySQL busy message
            confirm_idle: Wait time for idle before sending response
        
        Returns:
            Message about operation result
        """
        if not self.channel:
            raise RuntimeError("Not connected")
        
        time.sleep(0.03)
        while self.channel.recv_ready():
            self.channel.recv(65535)
        
        self.channel.send((command + "\r").encode())
        
        confirmation_re = re.compile(confirmation_pattern)
        busy_re = re.compile(busy_pattern)
        buf = ""
        deadline = time.time() + self.timeout
        confirmed = False
        
        while time.time() < deadline:
            if self.channel.recv_ready():
                chunk = self.channel.recv(65535).decode(errors="replace")
                buf += chunk
            
            buf_for_match = strip_ansi(buf) if self.strip_ansi_flag else buf
            
            if (not confirmed) and confirmation_re.search(buf_for_match):
                idle_deadline = time.time() + confirm_idle
                while time.time() < deadline:
                    if self.channel.recv_ready():
                        chunk = self.channel.recv(65535).decode(errors="replace")
                        buf += chunk
                        idle_deadline = time.time() + confirm_idle
                    if time.time() >= idle_deadline:
                        break
                    time.sleep(0.01)
                
                buf_for_match = strip_ansi(buf) if self.strip_ansi_flag else buf
                
                if busy_re.search(buf_for_match):
                    if self.debug:
                        print("[DEBUG] MySQL busy detected, sending 'n'", file=sys.stderr)
                    self.channel.send(b"n\r")
                    confirmed = True
                    time.sleep(0.02)
                    
                    try:
                        self._read_until_regex(self.prompt_re, echo=False)
                    except TimeoutError:
                        pass
                    
                    return "Restart rejected - MySQL is busy updating the database"
                else:
                    if self.debug:
                        print("[DEBUG] No busy detected, sending 'y' - system will restart", file=sys.stderr)
                    self.channel.send(b"y\r")
                    confirmed = True
                    time.sleep(0.5)
                    
                    try:
                        remaining = ""
                        end_time = time.time() + 5
                        while time.time() < end_time:
                            if self.channel.recv_ready():
                                chunk = self.channel.recv(65535).decode(errors="replace")
                                remaining += chunk
                            if self.channel.closed:
                                break
                            time.sleep(0.1)
                    except Exception:
                        pass
                    
                    return "System is restarting - connection broken"
            
            if self.channel.closed:
                return "System is restarting - connection broken"
            
            time.sleep(0.01)
        
        return "Timeout waiting for confirmation prompt"

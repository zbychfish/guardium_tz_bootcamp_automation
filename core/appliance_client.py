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
    
    def execute_command_with_early_fail_detection(
        self,
        command: str,
        fail_pattern: str = "Fail:",
        timeout: Optional[int] = None
    ) -> tuple[str, bool]:
        """
        Execute command with early detection of failure patterns.
        If fail_pattern is detected, immediately return without waiting for prompt.
        
        Args:
            command: Command to execute
            fail_pattern: Pattern that indicates early failure (default: "Fail:")
            timeout: Optional timeout in seconds
        
        Returns:
            Tuple of (output, fail_detected)
            - output: Command output received so far
            - fail_detected: True if fail_pattern was detected
        
        Raises:
            RuntimeError: If not connected
            TimeoutError: If timeout reached
        """
        if not self.channel:
            raise RuntimeError("Not connected")
        
        # Flush buffer
        time.sleep(0.05)
        while self.channel.recv_ready():
            self.channel.recv(65535)
        
        # Send command
        self.channel.send((command + "\r\n").encode())
        
        # Read until prompt or fail pattern
        cmd_timeout = timeout if timeout is not None else self.timeout
        buf = ""
        deadline = time.time() + cmd_timeout
        fail_detected = False
        
        if self.debug:
            print(f"[DEBUG] Executing with fail detection: {command} (timeout: {cmd_timeout}s)", file=sys.stderr)
        
        while time.time() < deadline:
            if self.channel.recv_ready():
                chunk = self.channel.recv(65535).decode(errors="replace")
                buf += chunk
                
                if self.debug:
                    print(f"[DEBUG] Received chunk ({len(chunk)} bytes): {repr(chunk[:100])}", file=sys.stderr)
            
            # Check for fail pattern first
            buf_for_match = strip_ansi(buf) if self.strip_ansi_flag else buf
            if fail_pattern in buf_for_match:
                if self.debug:
                    print(f"[DEBUG] Fail pattern '{fail_pattern}' detected!", file=sys.stderr)
                fail_detected = True
                break
            
            # Check for prompt
            if self.prompt_re.search(buf_for_match):
                if self.debug:
                    print(f"[DEBUG] Prompt matched! Buffer length: {len(buf)}", file=sys.stderr)
                break
            
            if self.channel.closed:
                raise RuntimeError("Channel closed unexpectedly")
            
            time.sleep(0.05)
        
        if time.time() >= deadline and not fail_detected:
            if self.debug:
                print(f"[DEBUG] Timeout! Buffer content: {repr(buf[:200])}", file=sys.stderr)
            raise TimeoutError(f"Timeout waiting for prompt or fail pattern after {cmd_timeout}s")
        
        # Clean output
        working = strip_ansi(buf) if self.strip_ansi_flag else buf
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
            if not stripped:
                continue
            if stripped == "ok":
                continue
            if self.prompt_re.search(stripped):
                continue
            filtered_lines.append(line)
        
        return "\n".join(filtered_lines), fail_detected
    
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
            print(f"[DEBUG] Confirmation pattern: {confirmation_pattern}", file=sys.stderr)
        self.channel.send((command + "\r").encode())
        
        confirmation_re = re.compile(confirmation_pattern)
        buf = ""
        deadline = time.time() + self.timeout
        confirmed = False
        
        iteration = 0
        while time.time() < deadline:
            iteration += 1
            if self.channel.recv_ready():
                chunk = self.channel.recv(65535).decode(errors="replace")
                if self.debug:
                    print(f"[DEBUG] Iteration {iteration}: Received chunk ({len(chunk)} bytes): {repr(chunk)}", file=sys.stderr)
                buf += chunk
            
            buf_for_match = strip_ansi(buf) if self.strip_ansi_flag else buf
            
            # Debug: show what we're matching against (only every 1000 iterations to avoid spam)
            if self.debug and (not confirmed) and len(buf_for_match) > 0 and (iteration % 1000 == 1):
                print(f"[DEBUG] Iteration {iteration}: Checking buffer for confirmation pattern...", file=sys.stderr)
                print(f"[DEBUG] Buffer (last 200 chars): {repr(buf_for_match[-200:])}", file=sys.stderr)
                print(f"[DEBUG] Pattern: {confirmation_re.pattern}", file=sys.stderr)
                print(f"[DEBUG] 'I agree' in buffer: {'I agree' in buf_for_match}", file=sys.stderr)
            
            # Handle confirmation once when detected
            if (not confirmed) and confirmation_re.search(buf_for_match):
                if self.debug:
                    print(f"[DEBUG] Confirmation pattern matched in buffer", file=sys.stderr)
                if self.debug:
                    print(f"[DEBUG] Buffer content: {repr(buf_for_match[-200:])}", file=sys.stderr)
                    print(f"[DEBUG] Waiting idle {confirm_idle}s then sending '{response}'", file=sys.stderr)
                
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
    
    def execute_command_simple_confirmation(
        self,
        command: str,
        confirmation_text: str,
        response: str,
        timeout: int = 60
    ) -> str:
        """
        Execute command with simple text-based confirmation.
        
        This method:
        1. Sends the command
        2. Waits for confirmation_text to appear in output
        3. Sends the response
        4. Waits for prompt to return
        
        Args:
            command: Command to execute
            confirmation_text: Text to wait for (e.g. "I agree")
            response: Response to send when confirmation_text appears
            timeout: Timeout in seconds (default: 60)
        
        Returns:
            Full command output
        
        Raises:
            RuntimeError: If not connected
            TimeoutError: If timeout reached
        """
        if not self.channel:
            raise RuntimeError("Not connected")
        
        # Step 1: Send command
        self.channel.send((command + "\r").encode())
        
        # Step 2: Wait for confirmation text to appear
        buf = ""
        deadline = time.time() + timeout
        confirmation_found = False
        
        while time.time() < deadline:
            if self.channel.recv_ready():
                chunk = self.channel.recv(65535).decode(errors="replace")
                buf += chunk
                
                if self.debug:
                    print(f"[DEBUG] Received chunk ({len(chunk)} bytes): {repr(chunk)}", file=sys.stderr)
            
            # Check if confirmation text appeared
            if confirmation_text in buf and not confirmation_found:
                if self.debug:
                    print(f"[DEBUG] Found '{confirmation_text}' in output, sending response '{response}'", file=sys.stderr)
                
                # Step 3: Wait a bit to ensure prompt is complete, then send response
                time.sleep(0.2)
                self.channel.send((response + "\r").encode())
                confirmation_found = True
            
            # Step 4: Check if prompt returned
            if confirmation_found and self.prompt_re.search(buf):
                if self.debug:
                    print(f"[DEBUG] Prompt detected, command completed", file=sys.stderr)
                break
            
            if self.channel.closed:
                raise RuntimeError("Channel closed")
            
            time.sleep(0.01)
        else:
            raise TimeoutError(f"Timeout waiting for command completion (timeout: {timeout}s)")
        
        # Return full output
        return buf
    
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

    def generate_external_stap_csr(
        self,
        alias: str,
        common_name: str,
        san1: str,
        organizational_unit: str,
        organization: str,
        country: str,
        encryption_algorithm: str,
        keysize: str,
        locality: str = "",
        state: str = "",
        email: str = "",
        san2: str = "",
        timeout_sec: int = 180,
        prompt_timeout_sec: int = 20
    ) -> Tuple[str, str, str]:
        """
        Generate CSR for Guardium External S-TAP using existing connection.
        
        Args:
            alias: CSR alias (e.g. mysql-etap)
            common_name: Certificate CN
            san1: First SAN value
            organizational_unit: Organizational unit (default "Training")
            organization: Organization (default "Demo")
            locality: City/location (default empty - skip)
            state: State/province (default empty - skip)
            country: Two-letter country code (default "PL")
            email: Email address (default empty - skip)
            encryption_algorithm: Encryption algorithm (default "2")
            keysize: Key size (default "2")
            san2: Second SAN value (default empty)
            timeout_sec: Global timeout in seconds (default 180)
            prompt_timeout_sec: Timeout for single prompt (default 20)
        
        Returns:
            Tuple[str, str, str]: (csr_pem, deployment_token, line_above_token)
        
        Raises:
            RuntimeError: If not connected or error occurred
            TimeoutError: If timeout exceeded
        """
        if not self.channel:
            raise RuntimeError("Not connected")
        
        # Wizard steps definition
        steps = [
            ("alias", "Please enter the hostname as the alias", alias),
            ("CN", "What is the Common Name", common_name),
            ("OU", "organizational unit", organizational_unit),
            ("OU-confirm", "another organizational unit", "n"),
            ("O", "organization (O=", organization),
        ]
        
        if locality:
            steps.append(("L", "city or locality", locality))
        else:
            steps.append(("L", "city or locality", ""))
            steps.append(("L-skip", "skip 'L'", "y"))
        
        if state:
            steps.append(("ST", "state or province", state))
        else:
            steps.append(("ST", "state or province", ""))
            steps.append(("ST-skip", "skip 'ST'", "y"))
        
        steps.append(("C", "two-letter country code", country))
        
        if email:
            steps.append(("email", "email address", email))
        else:
            steps.append(("email", "email address", ""))
            steps.append(("email-skip", "skip 'emailAddress'", "y"))
        
        steps.extend([
            ("crypto", "encryption algorithm", encryption_algorithm),
            ("keysize", "keysize", keysize),
            ("SAN1", "What is the name of SAN #1", san1),
            ("SAN2", "What is the name of SAN #2", san2),
        ])
        
        if self.debug:
            print(f"[DEBUG] Starting External S-TAP CSR generation", file=sys.stderr)
            print(f"[DEBUG] Alias={alias}, CN={common_name}, SAN1={san1}", file=sys.stderr)
        
        # Helper functions
        def read_output() -> str:
            if not self.channel:
                raise RuntimeError("Channel not available")
            buf = ""
            while self.channel.recv_ready():
                chunk = self.channel.recv(65535).decode("utf-8", errors="ignore")
                if self.debug:
                    print(f"[DEBUG] RECV <<< {chunk}", file=sys.stderr)
                buf += chunk
            return buf
        
        def send(text: str) -> None:
            if not self.channel:
                raise RuntimeError("Channel not available")
            if self.debug:
                print(f"[DEBUG] SEND >>> {text!r}", file=sys.stderr)
            self.channel.send((text + "\n").encode("utf-8"))
        
        # Send command
        send("create csr external_stap")
        if self.debug:
            print("[DEBUG] Command sent: create csr external_stap", file=sys.stderr)
        
        full_output = ""
        step_idx = 0
        start_time = time.time()
        last_activity = time.time()
        
        # Main loop
        while True:
            if time.time() - start_time > timeout_sec:
                raise TimeoutError("GLOBAL TIMEOUT: CSR generation took too long")
            
            out = read_output()
            if out:
                full_output += out
                last_activity = time.time()
            
            # CSR already exists → select option [2]
            if (
                "CSR for this alias already exists" in full_output
                or "How would you like to proceed?" in full_output
            ):
                if self.debug:
                    print("[DEBUG] Existing CSR detected – selecting option [2]", file=sys.stderr)
                send("2")
                full_output = ""
                continue
            
            # End – token
            if "To deploy the external_stap, use the following token:" in full_output:
                if self.debug:
                    print("[DEBUG] Wizard completed – token detected", file=sys.stderr)
                break
            
            # Standard flow
            if step_idx < len(steps):
                step_name, expected_prompt, answer = steps[step_idx]
                
                if expected_prompt in full_output:
                    if self.debug:
                        print(
                            f"[DEBUG] Step [{step_idx + 1}/{len(steps)}] "
                            f"{step_name} → sending "
                            f"{'ENTER' if answer == '' else answer}",
                            file=sys.stderr
                        )
                    send(answer)
                    step_idx += 1
                    full_output = ""
                    continue
                
                if time.time() - last_activity > prompt_timeout_sec:
                    raise TimeoutError(
                        f"PROMPT TIMEOUT at step '{step_name}', "
                        f"waiting for: '{expected_prompt}'"
                    )
            
            time.sleep(0.3)
        
        if self.debug:
            print("[DEBUG] CSR generation completed", file=sys.stderr)
        
        # Extract CSR
        csr_match = re.search(
            r"-----BEGIN NEW CERTIFICATE REQUEST-----(.*?)-----END NEW CERTIFICATE REQUEST-----",
            full_output,
            re.S,
        )
        if not csr_match:
            raise RuntimeError("CSR not found in output")
        
        csr = (
            "-----BEGIN NEW CERTIFICATE REQUEST-----"
            + csr_match.group(1)
            + "-----END NEW CERTIFICATE REQUEST-----"
        )
        
        # Extract token and line above
        lines = full_output.splitlines()
        token: Optional[str] = None
        line_above: Optional[str] = None
        
        for i, line in enumerate(lines):
            if "To deploy the external_stap, use the following token:" in line:
                token = line.split(":")[-1].strip()
                if i > 0:
                    line_above = lines[i - 1].strip()
                break
        
        if token is None:
            raise RuntimeError("Deployment token not found")
        if line_above is None:
            raise RuntimeError("Line above token not found")
        
        if self.debug:
            print(f"[DEBUG] Deployment token extracted: {token}", file=sys.stderr)
        
        return csr, token, line_above
    
    def import_external_stap_ca_certificate(
        self,
        alias: str,
        ca_cert: str,
        timeout_sec: int = 120,
        prompt_timeout_sec: int = 20,
        ignore_time_parse_error: bool = True
    ) -> None:
        """
        Import CA certificate to Guardium External S-TAP keystore using existing connection.
        
        Args:
            alias: Alias for CA certificate
            ca_cert: CA certificate in PEM format (string)
            timeout_sec: Global timeout in seconds (default 120)
            prompt_timeout_sec: Timeout for single prompt (default 20)
            ignore_time_parse_error: Whether to ignore "Error parsing time" error (default True)
        
        Raises:
            RuntimeError: If not connected or error occurred
            TimeoutError: If timeout exceeded
        """
        if not self.channel:
            raise RuntimeError("Not connected")
        
        if self.debug:
            print(f"[DEBUG] Starting External S-TAP CA certificate import", file=sys.stderr)
            print(f"[DEBUG] Alias: {alias}", file=sys.stderr)
        
        # Helper functions
        def send(text: str) -> None:
            if not self.channel:
                raise RuntimeError("Channel not available")
            if self.debug:
                print(f"[DEBUG] SEND >>> {text!r}", file=sys.stderr)
            self.channel.send((text + "\n").encode("utf-8"))
        
        def send_raw(data: str) -> None:
            if not self.channel:
                raise RuntimeError("Channel not available")
            if self.debug:
                print("[DEBUG] SEND >>> (raw certificate data)", file=sys.stderr)
            self.channel.send(data.encode("utf-8"))
        
        def send_ctrl_d() -> None:
            if not self.channel:
                raise RuntimeError("Channel not available")
            if self.debug:
                print("[DEBUG] SEND >>> CTRL+D", file=sys.stderr)
            self.channel.send(b"\x04")
        
        def read_output() -> str:
            if not self.channel:
                raise RuntimeError("Channel not available")
            buf = ""
            while self.channel.recv_ready():
                chunk = self.channel.recv(65535).decode("utf-8", errors="ignore")
                if self.debug:
                    print(f"[DEBUG] RECV <<< {chunk}", file=sys.stderr)
                buf += chunk
            return buf
        
        # Send command
        send("store certificate keystore_external_stap")
        if self.debug:
            print("[DEBUG] Command sent: store certificate keystore_external_stap", file=sys.stderr)
        
        full_output = ""
        start_time = time.time()
        last_activity = time.time()
        
        # Main loop
        while True:
            if time.time() - start_time > timeout_sec:
                raise TimeoutError("GLOBAL TIMEOUT during CA certificate import")
            
            out = read_output()
            if out:
                full_output += out
                last_activity = time.time()
            
            # Alias prompt
            if "Please enter the alias associated with the certificate" in full_output:
                if self.debug:
                    print(f"[DEBUG] Sending alias: {alias}", file=sys.stderr)
                send(alias)
                full_output = ""
                continue
            
            # Certificate paste prompt
            if "Please paste your Trusted certificate below" in full_output:
                if self.debug:
                    print("[DEBUG] Pasting CA certificate", file=sys.stderr)
                send_raw(ca_cert.strip() + "\n")
                send("")       # ENTER
                time.sleep(0.5)
                send_ctrl_d()  # CTRL+D
                full_output = ""
                continue
            
            # Success
            if "SUCCESS: Certificate imported successfully" in full_output:
                if self.debug:
                    print("[DEBUG] Certificate imported successfully", file=sys.stderr)
                break
            
            # Optional known error → normal termination
            if (
                ignore_time_parse_error
                and "Error parsing time" in full_output
            ):
                if self.debug:
                    print("[DEBUG] Known 'Error parsing time' detected – treating as success", file=sys.stderr)
                break
            
            if time.time() - last_activity > prompt_timeout_sec:
                raise TimeoutError("PROMPT TIMEOUT during CA certificate import")
            
            time.sleep(0.05)
    
    def import_external_stap_certificate(
        self,
        alias_line: str,
        stap_cert: str,
        timeout_sec: int = 180,
        prompt_timeout_sec: int = 30,
        ignore_time_parse_error: bool = True
    ) -> None:
        """
        Import External S-TAP certificate (end-entity) to Guardium using existing connection.
        
        Args:
            alias_line: Full alias line (e.g. "mysql-etap proxy_keycert 02717b9d-2a87-11f1-af30-c4df3d41f195")
            stap_cert: External S-TAP certificate in PEM format (string)
            timeout_sec: Global timeout in seconds (default 180)
            prompt_timeout_sec: Timeout for single prompt (default 30)
            ignore_time_parse_error: Whether to ignore "Error parsing time" error (default True)
        
        Raises:
            RuntimeError: If not connected or error occurred
            TimeoutError: If timeout exceeded
        """
        if not self.channel:
            raise RuntimeError("Not connected")
        
        if self.debug:
            print(f"[DEBUG] Starting External S-TAP certificate import", file=sys.stderr)
            print(f"[DEBUG] Alias line: {alias_line}", file=sys.stderr)
        
        # Helper functions
        def send(text: str) -> None:
            if not self.channel:
                raise RuntimeError("Channel not available")
            if self.debug:
                print(f"[DEBUG] SEND >>> {text!r}", file=sys.stderr)
            self.channel.send((text + "\n").encode("utf-8"))
        
        def send_raw(data: str) -> None:
            if not self.channel:
                raise RuntimeError("Channel not available")
            if self.debug:
                print("[DEBUG] SEND >>> (raw certificate data)", file=sys.stderr)
            self.channel.send(data.encode("utf-8"))
        
        def send_ctrl_d() -> None:
            if not self.channel:
                raise RuntimeError("Channel not available")
            if self.debug:
                print("[DEBUG] SEND >>> CTRL+D", file=sys.stderr)
            self.channel.send(b"\x04")
        
        def read_output() -> str:
            if not self.channel:
                raise RuntimeError("Channel not available")
            buf = ""
            while self.channel.recv_ready():
                chunk = self.channel.recv(65535).decode("utf-8", errors="ignore")
                if self.debug:
                    print(f"[DEBUG] RECV <<< {chunk}", file=sys.stderr)
                buf += chunk
            return buf
        
        # Send command
        send("store certificate external_stap")
        if self.debug:
            print("[DEBUG] Command sent: store certificate external_stap", file=sys.stderr)
        
        full_output = ""
        start_time = time.time()
        last_activity = time.time()
        csr_confirmed = False
        cert_sent = False
        
        # Main loop - exactly as in original appliance_command.py
        while True:
            if time.time() - start_time > timeout_sec:
                raise TimeoutError("GLOBAL TIMEOUT during External S-TAP cert import")
            
            out = read_output()
            if out:
                full_output += out
                last_activity = time.time()
            
            # Alias prompt
            if "Please enter the alias associated with the certificate" in full_output:
                if self.debug:
                    print("[DEBUG] Sending External S-TAP alias line", file=sys.stderr)
                send(alias_line)
                full_output = ""
                continue
            
            # CSR confirmation
            if (
                not csr_confirmed
                and "Are you importing an External S-TAP certificate" in full_output
            ):
                if self.debug:
                    print("[DEBUG] Confirming certificate corresponds to CSR (y)", file=sys.stderr)
                send("y")
                csr_confirmed = True
                full_output = ""
                continue
            
            # Paste certificate
            if (
                "Please paste your End-Entity certificate below" in full_output
                and not cert_sent
            ):
                if self.debug:
                    print("[DEBUG] Pasting External S-TAP certificate", file=sys.stderr)
                send_raw(stap_cert.strip() + "\n")
                send("")        # ENTER
                time.sleep(0.5)
                send_ctrl_d()   # CTRL+D
                cert_sent = True
                full_output = ""
                continue
            
            # Success
            if "SUCCESS: Certificate imported successfully" in full_output:
                if self.debug:
                    print("[DEBUG] External S-TAP certificate imported successfully", file=sys.stderr)
                break
            
            # Optional known error
            if (
                ignore_time_parse_error
                and "Error parsing time" in full_output
            ):
                if self.debug:
                    print("[DEBUG] Known 'Error parsing time' detected – treating as success", file=sys.stderr)
                break
            
            if time.time() - last_activity > prompt_timeout_sec:
                raise TimeoutError("PROMPT TIMEOUT during External S-TAP cert import")
            
            time.sleep(0.05)

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

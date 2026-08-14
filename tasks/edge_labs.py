#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re
import socket
import tempfile
import time
import traceback

import paramiko

from core.appliance_client import ApplianceClient
from core.appliance_config_loader import ApplianceConfigLoader
from core.appliance_operations import _get_appliance_connection_params
from core.guardium_rest_api import create_guardium_api, import_definitions_files
from core.logger import get_logger
from core.ssh_client import SSHClient

logger = get_logger(__name__)


def _header(logger, title: str) -> None:
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)

def install_edge_patch_via_api(config, logger, verbose=True,
                               cm_appliance="cm",
                               patch_filename="SqlGuard-12.0p15002_Edge_Apr_14_2026.tgz.enc.sig",
                               mode="local_only",
                               debug=False, **kwargs):
                               
    _header(logger, "INSTALL EDGE PATCH ON CM VIA REST API")

    m = re.search(r'12\.0p(\d+)', os.path.basename(patch_filename))
    if not m:
        logger.error(f"Cannot extract patch_number from filename: {patch_filename}")
        return False
    patch_number = int(m.group(1))
    logger.info(f"Patch number: {patch_number}")

    params = _get_appliance_connection_params(config, logger, cm_appliance)
    if not params:
        return False
    cm_ip = params['host']
    cli_pwd = params['password']
    cli_prompt = params['prompt_regex']

    logger.info("➜ Registering patches on CM: show system patch available...")
    cli = ApplianceClient(
        host=cm_ip,
        user='cli',
        password=cli_pwd,
        prompt_regex=cli_prompt,
        initial_pattern=None,
        timeout=600,
        strip_ansi=True,
        debug=debug
    )
    if not cli.connect():
        logger.error("✗ Failed to connect to CM CLI")
        return False
    try:
        patch_output = cli.execute_command("show system patch available", timeout=600)
        logger.info(f"Available patches:\n{patch_output}")
        logger.info("✓ Patches registered on CM")
    except Exception as e:
        logger.error(f"✗ CLI command failed: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        cli.disconnect()

    api = create_guardium_api(config, logger, cm_appliance)
    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("Password 'pwd' not found in custom_variables")
        return False
    api.get_token(username='demo', password=pwd)

    logger.info(f"➜ Calling patch_install API (patch_number={patch_number}, unit={cm_ip}, mode={mode})...")
    try:
        result = api.patch_install(patch_number=patch_number, unit_ip_list=cm_ip, mode=mode)
    except Exception as e:
        logger.error(f"✗ patch_install API call failed: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False

    logger.info(f"  API response: {result}")
    if result.get('ErrorCode') or result.get('errorCode'):
        logger.error(f"✗ patch_install returned error: {result}")
        return False

    logger.info("✓ Edge patch installation initiated via REST API on CM")
    return True

def register_edge_gateway(config, logger, verbose=True,
                          cm_appliance="cm",
                          exports_to="cm.demo.guardium",
                          name="sauropod.demo.guardium",
                          namespace="edge",
                          storageclass_rw_once="local-path",
                          version="v2.1.1",
                          deploy_proxy=True,
                          debug=False, **kwargs):

    _header(logger, "REGISTER EDGE GATEWAY ON CM")

    logger.info(f"  name={name}, namespace={namespace}, exportsTo={exports_to}")
    logger.info(f"  storageclass_rw_once={storageclass_rw_once}, version={version}, deployProxy={deploy_proxy}")

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("pwd not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    try:
        result = api.register_edge(
            name=name,
            namespace=namespace,
            exports_to=exports_to,
            storageclass_rw_once=storageclass_rw_once,
            version=version,
            deploy_proxy=deploy_proxy,
        )
    except Exception as e:
        logger.error(f"✗ register_edge API call failed: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False

    if verbose:
        logger.info(f"  API response: {result}")
    if result.get('ErrorCode') or result.get('errorCode'):
        logger.error(f"✗ register_edge returned error: {result}")
        return False

    logger.info("✓ Edge gateway registered successfully on CM")
    return True

def install_k3s_on_sauropod(config, logger, verbose=True,
                            k3s_version="v1.32.13+k3s1",
                            cm_appliance="cm",
                            expected_pods=3, max_wait=300, check_interval=15,
                            debug=False, **kwargs):
    _header(logger, "INSTALL K3S ON SAUROPOD")

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    appliance_loader = ApplianceConfigLoader(config_loader=config)
    cm_config = appliance_loader.get_appliance(cm_appliance)
    if not cm_config:
        logger.error(f"Appliance '{cm_appliance}' not found in machines_info.json")
        return False
    cm_ip = cm_config.get('ip')
    if not cm_ip:
        logger.error(f"Appliance '{cm_appliance}' has no IP")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')

    root_password = config.get_custom_variable('pwd')
    if not root_password:
        logger.error("Root password (pwd) not found in custom_variables")
        return False

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_password,
                    port=ssh_port, timeout=60)
    try:
        logger.info(f"Connecting to sauropod ({sauropod_ip}:{ssh_port})...")
        if not ssh.connect():
            logger.error("Failed to connect to sauropod")
            return False
        logger.info("✓ Connected to sauropod")

        install_cmd = (
            f"curl -sfL https://get.k3s.io | "
            f"INSTALL_K3S_VERSION={k3s_version} sh -s - --disable traefik"
        )
        logger.info(f"➜ Installing k3s {k3s_version}...")
        result = ssh.execute_command(install_cmd, timeout=300, print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ k3s installation failed: {result['stderr']}")
            return False
        logger.info("✓ k3s installed")

        logger.info(f"➜ Waiting for {expected_pods} pods Running (max {max_wait}s, check every {check_interval}s)...")
        elapsed = 0
        while elapsed < max_wait:
            result = ssh.execute_command("kubectl get pods -A --no-headers 2>/dev/null", print_output=False)
            if result['rc'] == 0:
                lines = [l for l in result['stdout'].splitlines() if l.strip()]
                running = [l for l in lines if 'Running' in l]
                logger.info(f"  Pods Running: {len(running)}/{len(lines)} (elapsed {elapsed}s)")
                if debug:
                    for l in lines:
                        logger.info(f"    {l}")
                if len(running) >= expected_pods:
                    logger.info(f"✓ {len(running)} pods Running — k3s ready")
                    break
            time.sleep(check_interval)
            elapsed += check_interval
        else:
            logger.error(f"✗ Timeout: expected {expected_pods} pods Running after {max_wait}s")
            return False

        logger.info(f"➜ Patching CoreDNS (sauropod_ip={sauropod_ip}, cm_ip={cm_ip})...")

        node_hosts_value = (
            f"{sauropod_ip} sauropod.demo.guardium\\n"
            f"{cm_ip} cm.demo.guardium\\n"
            f"{cm_ip} cm.demo.guardium.demo.guardium\\n"
        )
        corefile_value = (
            ".:53 {\\n"
            "    errors\\n"
            "    health\\n"
            "    ready\\n"
            "    kubernetes cluster.local in-addr.arpa ip6.arpa {\\n"
            "        pods insecure\\n"
            "        fallthrough in-addr.arpa ip6.arpa\\n"
            "    }\\n"
            "    hosts {\\n"
            f"        {cm_ip} cm.demo.guardium\\n"
            f"        {cm_ip} cm.demo.guardium.demo.guardium\\n"
            "        fallthrough\\n"
            "    }\\n"
            "    prometheus :9153\\n"
            "    forward . /etc/resolv.conf\\n"
            "    cache 30\\n"
            "    loop\\n"
            "    reload\\n"
            "    loadbalance\\n"
            "}\\n"
        )

        coredns_cmds = [
            (
                f"kubectl -n kube-system patch configmap coredns --type='json' "
                f"-p='[{{\"op\":\"replace\",\"path\":\"/data/NodeHosts\",\"value\":\"{node_hosts_value}\"}}]'",
                "patch CoreDNS NodeHosts"
            ),
            (
                f"kubectl -n kube-system patch configmap coredns --type=json "
                f"-p='[{{\"op\":\"replace\",\"path\":\"/data/Corefile\",\"value\":\"{corefile_value}\"}}]'",
                "patch CoreDNS Corefile"
            ),
            (
                "kubectl -n kube-system rollout restart deployment coredns",
                "restart CoreDNS"
            ),
        ]

        for cmd, desc in coredns_cmds:
            logger.info(f"  ➜ {desc}...")
            result = ssh.execute_command(cmd, timeout=60, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"  ✗ Failed to {desc}: {result['stderr']}")
                return False
            logger.info(f"  ✓ {desc}")

        logger.info("✓ k3s installed and CoreDNS configured on sauropod")
        return True

    except Exception as e:
        logger.error(f"✗ SSH operation failed: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

def download_edge_bundle_via_api(config, logger, verbose=True,
                                 cm_appliance="cm",
                                 edge_name="sauropod.demo.guardium",
                                 sauropod_dest="/tmp/edge.tar.gz",
                                 debug=False, **kwargs):

    _header(logger, "DOWNLOAD EDGE BUNDLE VIA REST API TO SAUROPOD")

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("pwd not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)
    logger.info(f"➜ Calling get_bundle(name={edge_name}) on CM...")
    try:
        bundle_bytes = api.get_bundle(name=edge_name)
    except Exception as e:
        logger.error(f"✗ get_bundle API call failed: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False

    if not bundle_bytes:
        logger.error("✗ get_bundle returned empty response")
        return False
    logger.info(f"✓ Bundle received ({len(bundle_bytes)} bytes)")

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')

    tmp_path = os.path.join(tempfile.gettempdir(), 'edge.tar.gz')
    with open(tmp_path, 'wb') as f:
        f.write(bundle_bytes)
    logger.info(f"➜ Uploading to sauropod ({sauropod_ip}:{ssh_port}) → {sauropod_dest}...")

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=pwd,
                    port=ssh_port, timeout=120)
    try:
        if not ssh.connect():
            logger.error("✗ Failed to connect to sauropod")
            return False
        if not ssh.upload_file(tmp_path, sauropod_dest):
            logger.error("✗ Failed to upload bundle to sauropod")
            return False
        logger.info(f"✓ Edge bundle uploaded to sauropod: {sauropod_dest}")
        extract_dir = os.path.dirname(sauropod_dest.rstrip('/'))
        for cmd, desc in [
            (f"tar -xzf {sauropod_dest} -C {extract_dir}", f"extract {sauropod_dest}"),
            (f"rm -f {sauropod_dest}", f"remove archive {sauropod_dest}"),
        ]:
            result = ssh.execute_command(cmd, print_output=False)
            if result['rc'] != 0:
                logger.error(f"✗ Failed to {desc}: {result['stderr']}")
                return False
            logger.info(f"  ✓ {desc}")
        logger.info(f"✓ Edge bundle extracted to {extract_dir}")
        return True
    except Exception as e:
        logger.error(f"✗ Upload/extract failed: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()
        try:
            os.remove(tmp_path)
        except OSError:
            pass

def prepare_sauropod_for_edge(config, logger, verbose=True,
                              debug=False, **kwargs):
    _header(logger, "PREPARE SAUROPOD FOR EDGE DEPLOYMENT")

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')
    root_pwd = config.get_custom_variable('pwd')
    if not root_pwd:
        logger.error("pwd not found in custom_variables")
        return False

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_pwd,
                    port=ssh_port, timeout=60)
    try:
        if not ssh.connect():
            logger.error("✗ Failed to connect to sauropod")
            return False

        for cmd, desc in [
            ("firewall-cmd --permanent --add-port=6443/tcp",  "allow 6443/tcp"),
            ("firewall-cmd --permanent --add-port=8472/udp",  "allow 8472/udp"),
            ("firewall-cmd --permanent --add-port=10250/tcp", "allow 10250/tcp"),
            ("firewall-cmd --permanent --add-masquerade",     "enable masquerade"),
            ("firewall-cmd --reload",                         "reload firewall"),
        ]:
            logger.info(f"➜ {desc}...")
            result = ssh.execute_command(cmd, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"✗ Failed to {desc}: {result['stderr']}")
                return False
            logger.info(f"  ✓ {desc}")

        logger.info("➜ Installing expect on sauropod...")
        result = ssh.execute_command("dnf -y install expect", print_output=verbose)
        if result['rc'] != 0:
            logger.error(f"✗ Failed to install expect: {result['stderr']}")
            return False
        logger.info("✓ expect installed on sauropod")
        return True
    except Exception as e:
        logger.error(f"✗ Operation failed: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

def deploy_edge_gateway(config, logger, verbose=True,
                        edge_dir="/tmp/sauropod.demo.guardium",
                        install_script="edge-install.sh",
                        script_timeout=600,
                        debug=False, **kwargs):

    _header(logger, "DEPLOY EDGE GATEWAY ON SAUROPOD")

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')
    root_pwd = config.get_custom_variable('pwd')
    if not root_pwd:
        logger.error("pwd not found in custom_variables")
        return False

    logger.info(f"➜ Running {edge_dir}/{install_script} with PTY (timeout={script_timeout}s)...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(sauropod_ip, port=ssh_port, username=ssh_username, password=root_pwd,
                       look_for_keys=False, allow_agent=False, timeout=30)

        transport = client.get_transport()
        channel = transport.open_session()
        channel.get_pty(term="xterm", width=200, height=50)
        channel.settimeout(1.0)
        channel.exec_command(f"cd {edge_dir} && bash {install_script}")

        buf = ""
        deadline = time.time() + script_timeout
        last_activity = time.time()
        answers_sent = 0

        while time.time() < deadline:
            try:
                chunk = channel.recv(4096).decode('utf-8', errors='replace')
                if chunk:
                    buf += chunk
                    last_activity = time.time()
                    if verbose:
                        for line in chunk.splitlines():
                            if line.strip():
                                logger.info(f"  {line}")
                    while buf.count('[y/N]?') > answers_sent:
                        time.sleep(0.3)
                        logger.info("  >>> Sending: y")
                        channel.sendall(b"y\n")
                        answers_sent += 1
            except socket.timeout:
                if time.time() - last_activity > 60:
                    logger.warning("  ⚠ No output for 60s, still waiting...")
                    last_activity = time.time()
            if channel.exit_status_ready():
                try:
                    while True:
                        tail = channel.recv(4096).decode('utf-8', errors='replace')
                        if not tail:
                            break
                        buf += tail
                        if verbose:
                            for line in tail.splitlines():
                                if line.strip():
                                    logger.info(f"  {line}")
                except socket.timeout:
                    pass
                break

        if not channel.exit_status_ready():
            logger.error(f"✗ edge-install.sh timed out after {script_timeout}s")
            return False

        exit_code = channel.recv_exit_status()
        if exit_code != 0:
            logger.error(f"✗ edge-install.sh failed (rc={exit_code})")
            return False

        logger.info("✓ edge-install.sh completed successfully")
        return True

    except Exception as e:
        logger.error(f"✗ Operation failed: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        client.close()

def monitor_edge_gateway_deployment(config, logger, verbose=True,
                                    namespace="edge",
                                    pod_prefix="edge-manager",
                                    appear_interval=15, appear_max=40,
                                    log_interval=30, log_max=60,
                                    completion_marker="EDGE_SERVICES_INSTALLATION_STATUS is Completed",
                                    debug=False, **kwargs):

    _header(logger, "MONITOR EDGE GATEWAY DEPLOYMENT ON SAUROPOD")

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')
    root_pwd = config.get_custom_variable('pwd')
    if not root_pwd:
        logger.error("pwd not found in custom_variables")
        return False

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=root_pwd,
                    port=ssh_port, timeout=60)
    try:
        if not ssh.connect():
            logger.error("✗ Failed to connect to sauropod")
            return False
        logger.info("✓ Connected to sauropod")

        logger.info(f"⬳ Phase 1: Waiting for pod '{pod_prefix}*' in namespace '{namespace}'")
        logger.info(f"   Checking every {appear_interval}s (max {appear_max} checks)...")
        pod_name = None
        for check in range(1, appear_max + 1):
            time.sleep(appear_interval)
            result = ssh.execute_command(
                f"kubectl get pods -n {namespace} --no-headers 2>/dev/null",
                print_output=False
            )
            for line in result['stdout'].splitlines():
                if line.strip().startswith(pod_prefix):
                    pod_name = line.split()[0]
                    break
            if pod_name:
                logger.info(f"  ✓ #{check}/{appear_max}: Pod found → {pod_name}")
                break
            logger.info(f"  #{check}/{appear_max}: Pod '{pod_prefix}*' not yet visible, waiting {appear_interval}s...")

        if not pod_name:
            logger.error(f"✗ Pod '{pod_prefix}*' did not appear after {appear_interval * appear_max}s")
            return False

        logger.info(f"⬳ Phase 2: Monitoring logs of {pod_name} (every {log_interval}s, max {log_max} checks)...")
        for check in range(1, log_max + 1):
            time.sleep(log_interval)
            logger.info(f"  Check #{check}/{log_max}: kubectl logs {pod_name} -n {namespace}...")
            result = ssh.execute_command(
                f"kubectl logs {pod_name} -n {namespace} 2>/dev/null | grep '{completion_marker}' | tail -n 1",
                print_output=False
            )
            line = result['stdout'].strip()
            if line:
                logger.info(f"  ✓ Completed: {line}")
                logger.info("✓ Edge gateway deployment completed successfully")
                return True
            logger.info(f"  Not yet completed, waiting {log_interval}s...")

        logger.error(f"✗ Timeout: completion marker not found after {log_interval * log_max}s")
        return False

    except Exception as e:
        logger.error(f"✗ Operation failed: {e}")
        if debug:
            logger.error(traceback.format_exc())
        return False
    finally:
        ssh.disconnect()

def install_policy_on_sauropod(config, logger, verbose=True,
                               cm_appliance="cm",
                               policy_name="Default bootcamp policy",
                               units="sauropod.demo.guardium",
                               install_action="install_override",
                               debug=False, **kwargs):

    _header(logger, "INSTALL POLICY ON SAUROPOD")
    
    logger.info(f"  policy={policy_name}, units={units}, install_action={install_action}")

    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("pwd not found in custom_variables")
        return False

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    logger.info(f"➜ Installing policy '{policy_name}' on units={units}...")
    result = api.install_policy(
        policy=policy_name,
        units=units,
        install_action=install_action,
        max_retries=3,
        retry_delay=60,
        debug=debug
    )

    error_code = result.get('ErrorCode') or result.get('ID', '0')
    if str(error_code) not in ('0', ''):
        logger.error(f"✗ Policy installation failed: {result}")
        return False

    logger.info(f"✓ Policy '{policy_name}' installed on sauropod")
    return True

def import_edge_dashboard(config, logger, verbose=True,
                          cm_appliance="cm",
                          definitions_dir="/opt/guardium_tz_bootcamp_automation/upload/source_files/exports/",
                          debug=False, **kwargs):
    _header(logger, "IMPORT EDGE DASHBOARD ON CM")

    success = import_definitions_files(
        config=config,
        logger=logger,
        appliance_name=cm_appliance,
        definition_files=["exp_dashboard_edge.sql"],
        definitions_dir=definitions_dir,
        debug=debug
    )

    if success:
        logger.info("✓ Edge dashboard imported successfully")
    return success

def configure_stap_for_edge_on_sauropod(config, logger, verbose=True,
                                        cm_appliance="cm",
                                        installation_delay=10,
                                        debug=False, **kwargs):
    _header(logger, "CONFIGURE STAP FOR EDGE ON SAUROPOD")

    sauropod_ip = config.get_machine_ip('sauropod', use_private=True)
    if not sauropod_ip:
        logger.error("Sauropod IP not found in machines config")
        return False

    ssh_config = config.get('ssh', {})
    ssh_port = ssh_config.get('port', 2223)
    ssh_username = ssh_config.get('username', 'root')
    pwd = config.get_custom_variable('pwd')
    if not pwd:
        logger.error("pwd not found in custom_variables")
        return False

    ssh = SSHClient(host=sauropod_ip, username=ssh_username, password=pwd,
                    port=ssh_port, timeout=30)

    logger.info("➜ Opening NodePort range 30000-32767/tcp on sauropod firewall...")
    try:
        if not ssh.connect():
            logger.error("✗ Failed to connect to sauropod")
            return False
        for cmd, desc in [
            ("firewall-cmd --permanent --add-port=30000-32767/tcp", "allow 30000-32767/tcp"),
            ("firewall-cmd --reload",                               "reload firewall"),
        ]:
            result = ssh.execute_command(cmd, print_output=verbose)
            if result['rc'] != 0:
                logger.error(f"✗ Failed to {desc}: {result['stderr']}")
                return False
            logger.info(f"  ✓ {desc}")
    finally:
        ssh.disconnect()

    logger.info("➜ Getting haproxy NodePorts from sauropod...")
    try:
        if not ssh.connect():
            logger.error("✗ Failed to connect to sauropod")
            return False
        result = ssh.execute_command(
            "kubectl -n edge describe svc haproxy-kubernetes-ingress",
            print_output=False
        )
        if result['rc'] != 0:
            logger.error(f"✗ kubectl failed: {result['stderr']}")
            return False
        svc_output = result['stdout']
    finally:
        ssh.disconnect()

    m16016 = re.search(r'NodePort:\s+port-16016\s+(\d+)/TCP', svc_output)
    m16018 = re.search(r'NodePort:\s+port-16018\s+(\d+)/TCP', svc_output)
    if not m16016:
        logger.error("✗ NodePort for port-16016 not found in kubectl output")
        return False
    if not m16018:
        logger.error("✗ NodePort for port-16018 not found in kubectl output")
        return False
    node_port_16016 = m16016.group(1)
    node_port_16018 = m16018.group(1)
    logger.info(f"  NodePort 16016 → {node_port_16016}")
    logger.info(f"  NodePort 16018 → {node_port_16018}")

    api = create_guardium_api(config, logger, cm_appliance)
    api.get_token(username='demo', password=pwd)

    for param, value in [
        ("STAP_USING_EDGE",        "1"),
        ("STAP_ENABLED",           "1"),
        ("STAP_SQLGUARD_IP",       sauropod_ip),
        ("STAP_SQLGUARD_PORT",     node_port_16016),
        ("STAP_SQLGUARD_TLS_PORT", node_port_16018),
    ]:
        logger.info(f"  Setting {param}={value} on sauropod ({sauropod_ip})")
        api.gim_client_params(client_ip=sauropod_ip, param_name=param, param_value=value)

    logger.info("➜ Scheduling GIM install on sauropod...")
    api.gim_schedule_install(client_ip=sauropod_ip, date="now")
    logger.info(f"✓ Scheduled. Waiting {installation_delay}s before monitoring...")
    time.sleep(installation_delay)

    logger.info("➜ Monitoring installation progress...")
    check_count = 0
    while True:
        check_count += 1
        logger.info(f"  Check #{check_count}: Querying module status...")
        modules = api.gim_list_client_modules(client_ip=sauropod_ip)

        if "ErrorCode" in modules or "ErrorMessage" in modules:
            logger.error(f"  ✗ API Error: {modules.get('ErrorCode')} {modules.get('ErrorMessage')}")
            return False

        entries = [e.strip() for e in re.split(r"#+\s*ENTRY\s+\d+\s*#+", modules.get("Message", "")) if e.strip()]
        result_mods = []
        for e in entries:
            m_name = re.search(r"NAME:\s+([A-Z0-9\-]+)", e)
            m_state = re.search(r"STATE:\s+([A-Z\-]+)", e)
            result_mods.append({"name": m_name.group(1) if m_name else "?", "state": m_state.group(1) if m_state else "?"})
        pending = [m for m in result_mods if m["state"] != "INSTALLED"]
        if pending:
            logger.info(f"  ⌛ {len(pending)} module(s) still installing: {[m['name'] for m in pending]}")
            logger.info("  Waiting 30s before next check...")
            time.sleep(30)
        else:
            logger.info("  ✓ All modules installed successfully!")
            break

    logger.info("✓ STAP configured for Edge on sauropod")
    return True

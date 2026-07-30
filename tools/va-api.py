#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# VA REST API demo — Guardium Bootcamp
#
# Jeśli uruchamiany z katalogu projektu (guardium_tz_bootcamp_automation/),
# brakujące argumenty są uzupełniane automatycznie z:
#   - /root/machines_info.json  → --appliance (IP CM)
#   - .client_secret            → --client-secret
#   - custom_variables.pwd      → --password
#   - custom_variables.demo_user (lub "demo") → --user
#
# Przykład ręczny (wszystkie argumenty wprost):
#   python tools/va-api.py --appliance 10.0.0.1 --client-secret abc123 \
#       --user demo --password Secret1! --score-type 0
#
# Przykład automatyczny (z katalogu projektu):
#   python tools/va-api.py --score-type 0

import sys
import os
import json
from pathlib import Path

def _inject_defaults():
    TOOLS_DIR  = Path(__file__).resolve().parent
    PROJECT_DIR = TOOLS_DIR.parent

    # Determine which args are already present
    argv_str = ' '.join(sys.argv[1:])
    missing = {
        'appliance':      '--appliance'      not in argv_str,
        'client-secret':  '--client-secret'  not in argv_str,
        'user':           '--user'            not in argv_str,
        'password':       '--password'        not in argv_str,
    }

    if not any(missing.values()):
        return  # all provided manually — nothing to do

    # ── Load machines_info.json ──────────────────────────────────────────────
    machines_info_path = Path('/root/machines_info.json')
    if not machines_info_path.exists():
        machines_info_path = PROJECT_DIR / 'config' / 'machines_info.json'

    cm_ip = None
    pwd   = None
    user  = 'demo'

    if machines_info_path.exists():
        try:
            data = json.loads(machines_info_path.read_text(encoding='utf-8'))
            # find CM machine
            for machine in data.get('machines', []):
                name = machine.get('name', '')
                if name.split('-')[0] in ('cm', 'collector'):
                    cm_ip = machine.get('private_ip') or machine.get('public_ip')
                    if cm_ip:
                        break
            # custom_variables
            custom_vars = data.get('custom_variables', {})
            pwd  = custom_vars.get('pwd')
            user = custom_vars.get('demo_user', 'demo')
        except Exception as e:
            print(f"[va-api] Warning: could not read machines_info.json: {e}", file=sys.stderr)

    # ── Load .client_secret ──────────────────────────────────────────────────
    secret = None
    secret_file = PROJECT_DIR / '.client_secret'
    if secret_file.exists():
        secret = secret_file.read_text(encoding='utf-8').strip()

    # ── Inject missing args into sys.argv ────────────────────────────────────
    extras = []
    if missing['appliance'] and cm_ip:
        extras += ['--appliance', cm_ip]
    if missing['client-secret'] and secret:
        extras += ['--client-secret', secret]
    if missing['user'] and user:
        extras += ['--user', user]
    if missing['password'] and pwd:
        extras += ['--password', pwd]

    if extras:
        sys.argv.extend(extras)

_inject_defaults()

# =============================================================================
# Original source — do not modify below this line
# =============================================================================

import requests
import urllib3
import argparse
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

parser = argparse.ArgumentParser(description='VA REST API client')
parser.add_argument('--appliance', required=True, help='Appliance hostname')
parser.add_argument('--port', default='8443', help='Appliance port')
parser.add_argument('--client-id', default='va-api', help='REST client ID')
parser.add_argument('--client-secret', required=True, help='REST client secret')
parser.add_argument('--user', required=True, help='Username')
parser.add_argument('--password', required=True, help='Password')
parser.add_argument('--score-type', type=int, required=True, help='Score type')
args = parser.parse_args()

appliance = args.appliance
port = args.port
client_id = args.client_id
client_secret = args.client_secret
username = args.user
password = args.password
score_type = args.score_type
base_url = f'https://{appliance}:{port}'

def get_token():
    data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'password',
        'username': username,
        'password': password
    }
    response = requests.post(f'{base_url}/oauth/token', data=data, verify=False)
    return response.json()['access_token']

def post_report(report_name, query_params):
    data = {'reportName': report_name, 'fetchSize': 30000, 'reportParameter': query_params}
    return requests.post(f'{base_url}/restAPI/online_report', headers=headers, json=data, verify=False)

def get_executions(collector):
    params = {'REMOTE_SOURCE': collector, 'SHOW_ALIASES': 'No', 'QUERY_FROM_DATE': 'NOW -60 DAY', 'QUERY_TO_DATE': 'NOW'}
    return post_report('VA - Assessment Result Sets (Training)', params)

def get_datasource(appliance, datasource_id):
    params = {'DataSourceID': datasource_id, 'REMOTE_SOURCE': appliance, 'SHOW_ALIASES': 'No', 'QUERY_FROM_DATE': 'NOW -60 DAY', 'QUERY_TO_DATE': 'NOW'}
    return post_report('VA - Assessment Datasources (Training)', params)

def get_test_info(appliance, test_id):
    params = {'TestId': test_id, 'REMOTE_SOURCE': appliance, 'SHOW_ALIASES': 'No', 'QUERY_FROM_DATE': 'NOW -60 DAY', 'QUERY_TO_DATE': 'NOW'}
    return post_report('VA - Tests (Training)', params)

def get_results(appliance, result_set, datasource):
    params = {'TestScore': score_type, 'ResultSetId': result_set, 'DataSourceId': datasource, 'REMOTE_SOURCE': appliance, 'SHOW_ALIASES': 'No', 'QUERY_FROM_DATE': 'NOW -60 DAY', 'QUERY_TO_DATE': 'NOW'}
    return post_report('VA - Assessment Result Set Values (Training)', params)

def get_all_exceptions(appliance='%', approver='%', test_description='%', datasource_group_name='%', datasource_name='%', assessment='%'):
    params = {'Approver': approver, 'TestDescription': test_description, 'DatasourceGroupName': datasource_group_name, 'DatasourceName': datasource_name, 'Assessment': assessment, 'REMOTE_SOURCE': appliance, 'SHOW_ALIASES': 'No', 'QUERY_FROM_DATE': 'NOW -60 DAY', 'QUERY_TO_DATE': 'NOW'}
    return post_report('Test Exceptions', params)

def get_all_detailed_exceptions(appliance='%', approver='%', except_type='%', except_detail_value='%', test_description='%', datasource_group_name='%', datasource_name='%', assessment='%'):
    params = {'Approver': approver, 'ExceptionType': except_type, 'ExceptionDetailValue': except_detail_value, 'TestDescription': test_description, 'DatasourceGroupName': datasource_group_name, 'DatasourceName': datasource_name, 'Assessment': assessment, 'REMOTE_SOURCE': appliance, 'SHOW_ALIASES': 'No', 'QUERY_FROM_DATE': 'NOW -60 DAY', 'QUERY_TO_DATE': 'NOW'}
    return post_report('Test Detail Exceptions', params)

def process_appliances(appliances):
    for appliance in appliances:
        source = 'Central Manager' if appliance == '%' else appliance
        print(f"Result set from: {source}")
        for execution in get_executions(appliance).json():
            ds_id = execution['Assessment Result Datasource Id']
            data_source = get_datasource(appliance, ds_id).json()[0]
            exec_date = execution['Execution Date']
            host = data_source['Host']
            ds_name = data_source['Datasource Name']
            ds_type = data_source['Datasource Type']
            print(f"Assessment executed {exec_date} on service on machine {host}. Database - {ds_name}/{ds_type}")
            result_id = execution['Assessment Result Id']
            for test_score in get_results(appliance, result_id, ds_id).json():
                print(test_score)
                if len(test_score) == 6:
                    test_id = test_score['Test Id']
                    test_info = get_test_info(appliance, test_id).json()[0]
                    test_num = test_score['Test Id']
                    desc = test_info['Test Description']
                    severity = test_info['Severity']
                    test_exception = get_all_exceptions(appliance, test_description=desc, datasource_name=ds_name).json()
                    if score_type == 0:
                        details = test_score['Result Details']
                        print(f"Test {test_num}: {desc}, Severity: {severity}, Details:")
                        if len(details) > 0:
                            print(f"{details}")
                    else:
                        print(f"Test {test_num}: {desc}, Severity: {severity}")
    # for exception in get_all_exceptions(appliance).json():
    #     valid_to = datetime.strptime(exception['Valid To Date'], '%Y-%m-%d %H:%M:%S').date()
    #     if valid_to > datetime.today().date():
    #         print(f"Exception for test {exception['Test Description']} on datasource {exception['Datasource Name']}, Approver - {exception['Approver']}, Valid from: {exception['Valid From Date']} to {exception['Valid To Date']} with explanation: {exception['Explanation']}")
    # for exception in get_all_detailed_exceptions(appliance).json():
    #     valid_to = datetime.strptime(exception['Valid To Date'], '%Y-%m-%d %H:%M:%S').date()
    #     if valid_to > datetime.today().date():
    #         print(f"Detailed exception for test {exception['Test Description']} on datasource {exception['Datasource Name']}, excepted value - {exception['Exception Detail Value']}, Approver - {exception['Approver']}, Valid from: {exception['Valid From Date']} to {exception['Valid To Date']} with explanation: {exception['Explanation']}")

if __name__ == '__main__':
    token = get_token()
    headers = {'Authorization': f'Bearer {token}'}
    appliances = ['%']
    process_appliances(appliances)

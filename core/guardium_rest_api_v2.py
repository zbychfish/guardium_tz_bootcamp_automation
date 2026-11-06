#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
from typing import Optional, Dict, Any, List
from .guardium_rest_api import GuardiumRestAPI, create_guardium_api


class GuardiumRestAPIv2:

    def __init__(self, auth_api: GuardiumRestAPI, logger=None):
        self.auth_api = auth_api
        self.base_url = f'{auth_api.base_url}/restAPI/v2'
        self.verify_ssl = auth_api.verify_ssl
        self.logger = logger

    def get_token(self, username: str, password: str) -> str:
        return self.auth_api.get_token(username=username, password=password)

    def get_headers(self) -> dict:
        return self.auth_api.get_headers()

    def register_edge(
        self,
        edge_name: Optional[str] = None,
        exports_to: Optional[List[str]] = None,
        namespace: Optional[str] = None,
        version: Optional[str] = None,
        sw_rw_once: Optional[str] = None,
        cpu_limit: Optional[int] = None,
        mem_limit: Optional[int] = None,
        storage_limit: Optional[Dict[str, Any]] = None,
        ingress_option: Optional[str] = None,
        backup_exports: Optional[List[str]] = None,
        external_registry_name: Optional[str] = None,
        worker_nodes: Optional[List[str]] = None,
        export_group_name: Optional[str] = None,
        default_export: Optional[str] = None,
    ) -> dict:
        if not edge_name:
            raise ValueError("edge_name is required")
        fields = {
            'edge_name': edge_name,
            'exports_to': exports_to,
            'namespace': namespace,
            'version': version,
            'sw_rw_once': sw_rw_once,
            'cpu_limit': cpu_limit,
            'mem_limit': mem_limit,
            'storage_limit': storage_limit,
            'ingress_option': ingress_option,
            'backup_exports': backup_exports,
            'external_registry_name': external_registry_name,
            'worker_nodes': worker_nodes,
            'export_group_name': export_group_name,
            'default_export': default_export,
        }
        data = {k: v for k, v in fields.items() if v is not None}
        url = f'{self.base_url}/edge'
        response = requests.post(url, json=data, headers=self.get_headers(), verify=self.verify_ssl)
        response.raise_for_status()
        return response.json() if response.content else {}


def create_guardium_api_v2(config, logger, appliance_name: str) -> GuardiumRestAPIv2:
    return GuardiumRestAPIv2(create_guardium_api(config, logger, appliance_name), logger=logger)

"""
OpenStack Security Groups SDK - Funciones de bajo nivel para Neutron Security Groups API
"""

import requests
import json
from typing import Dict, List, Optional, Any


def create_security_group(token: str, project_id: str, name: str, description: str = "") -> Optional[str]:
    """
    Crear security group en OpenStack
    
    Args:
        token: Token de autenticación
        project_id: ID del proyecto
        name: Nombre del security group
        description: Descripción
    
    Returns:
        ID del security group creado o None si falla
    """
    url = 'http://192.168.202.1:9696/v2.0/security-groups'
    headers = {
        'Content-Type': 'application/json',
        'X-Auth-Token': token
    }
    
    body = {
        "security_group": {
            "name": name,
            "description": description,
            "project_id": project_id
        }
    }
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(body))
        if response.status_code == 201:
            return response.json()['security_group']['id']
        else:
            print(f"Error creating SG: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Exception creating SG: {str(e)}")
        return None


def delete_security_group(token: str, sg_id: str) -> bool:
    """
    Eliminar security group
    
    Args:
        token: Token de autenticación
        sg_id: ID del security group
    
    Returns:
        True si se eliminó exitosamente
    """
    url = f'http://192.168.202.1:9696/v2.0/security-groups/{sg_id}'
    headers = {'X-Auth-Token': token}
    
    try:
        response = requests.delete(url, headers=headers)
        return response.status_code == 204
    except Exception as e:
        print(f"Exception deleting SG: {str(e)}")
        return False


def list_security_groups(token: str, project_id: str) -> List[Dict]:
    """
    Listar security groups de un proyecto
    
    Args:
        token: Token de autenticación
        project_id: ID del proyecto
    
    Returns:
        Lista de security groups
    """
    url = f'http://192.168.202.1:9696/v2.0/security-groups?project_id={project_id}'
    headers = {'X-Auth-Token': token}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('security_groups', [])
        return []
    except Exception as e:
        print(f"Exception listing SGs: {str(e)}")
        return []


def get_security_group_by_name(token: str, project_id: str, name: str) -> Optional[Dict]:
    """
    Obtener security group por nombre
    
    Args:
        token: Token de autenticación
        project_id: ID del proyecto
        name: Nombre del security group
    
    Returns:
        Security group o None
    """
    sgs = list_security_groups(token, project_id)
    for sg in sgs:
        if sg['name'] == name:
            return sg
    return None


def create_security_group_rule(
    token: str,
    sg_id: str,
    direction: str,
    ether_type: str = "IPv4",
    protocol: Optional[str] = None,
    port_range_min: Optional[int] = None,
    port_range_max: Optional[int] = None,
    remote_ip_prefix: Optional[str] = None,
    remote_group_id: Optional[str] = None,
    description: str = ""
) -> Optional[str]:
    """
    Crear regla en security group
    
    Args:
        token: Token de autenticación
        sg_id: ID del security group
        direction: 'ingress' o 'egress'
        ether_type: 'IPv4' o 'IPv6'
        protocol: 'tcp', 'udp', 'icmp', None (any)
        port_range_min: Puerto mínimo
        port_range_max: Puerto máximo
        remote_ip_prefix: CIDR (ej: '0.0.0.0/0')
        remote_group_id: ID de otro security group
        description: Descripción
    
    Returns:
        ID de la regla creada o None
    """
    url = 'http://192.168.202.1:9696/v2.0/security-group-rules'
    headers = {
        'Content-Type': 'application/json',
        'X-Auth-Token': token
    }
    
    body = {
        "security_group_rule": {
            "security_group_id": sg_id,
            "direction": direction,
            "ethertype": ether_type,
            "description": description
        }
    }
    
    # Agregar campos opcionales solo si se proporcionan
    if protocol:
        body["security_group_rule"]["protocol"] = protocol
    if port_range_min is not None:
        body["security_group_rule"]["port_range_min"] = port_range_min
    if port_range_max is not None:
        body["security_group_rule"]["port_range_max"] = port_range_max
    if remote_ip_prefix:
        body["security_group_rule"]["remote_ip_prefix"] = remote_ip_prefix
    if remote_group_id:
        body["security_group_rule"]["remote_group_id"] = remote_group_id
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(body))
        if response.status_code == 201:
            return response.json()['security_group_rule']['id']
        else:
            print(f"Error creating rule: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Exception creating rule: {str(e)}")
        return None


def delete_security_group_rule(token: str, rule_id: str) -> bool:
    """
    Eliminar regla de security group
    
    Args:
        token: Token de autenticación
        rule_id: ID de la regla
    
    Returns:
        True si se eliminó exitosamente
    """
    url = f'http://192.168.202.1:9696/v2.0/security-group-rules/{rule_id}'
    headers = {'X-Auth-Token': token}
    
    try:
        response = requests.delete(url, headers=headers)
        return response.status_code == 204
    except Exception as e:
        print(f"Exception deleting rule: {str(e)}")
        return False


def get_security_group_details(token: str, sg_id: str) -> Optional[Dict]:
    """
    Obtener detalles completos de un security group incluyendo sus reglas
    
    Args:
        token: Token de autenticación
        sg_id: ID del security group
    
    Returns:
        Detalles del security group o None
    """
    url = f'http://192.168.202.1:9696/v2.0/security-groups/{sg_id}'
    headers = {'X-Auth-Token': token}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()['security_group']
        return None
    except Exception as e:
        print(f"Exception getting SG details: {str(e)}")
        return None

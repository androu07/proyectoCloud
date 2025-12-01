import json, requests

# ================================== KEYSTONE ==================================

def password_authentication_with_scoped_authorization(auth_endpoint, user_id, password, domain_id, project_id):
    url = auth_endpoint + '/auth/tokens'
    data = \
        {
            "auth": {
                "identity": {
                    "methods": [
                        "password"
                    ],
                    "password": {
                        "user": {
                            "id": user_id,
                            "domain": {
                                "id": domain_id
                            },
                            "password": password
                        }
                    }
                },
                "scope": {
                    "project": {
                        "domain": {
                            "id": domain_id
                        },
                        "id": project_id
                    }
                }
            }
        }
        
    r = requests.post(url=url, data=json.dumps(data))
    # status_code success = 201
    return r

def token_authentication_with_scoped_authorization(auth_endpoint, token, domain_id, project_id):
    url = auth_endpoint + '/auth/tokens'

    data = \
        {
            "auth": {
                "identity": {
                    "methods": [
                        "token"
                    ],
                    "token": {
                        "id": token
                    }
                },
                "scope": {
                    "project": {
                        "domain": {
                            "id": domain_id
                        },
                        "id": project_id
                    }
                }
            }
        }

    r = requests.post(url=url, data=json.dumps(data))
    # status_code success = 201
    return r

def create_project(auth_endpoint, token, domain_id, project_name, description=''):
    url = auth_endpoint + '/projects'
    headers = {
        'Content-type': 'application/json',
        'X-Auth-Token': token,
    }
    
    data = {
        "project": {
            "name": project_name,
            "domain_id": domain_id,
            "description": description,
            "enabled": True
        }
    }
    
    r = requests.post(url=url, headers=headers, data=json.dumps(data))
    # status_code success = 201
    return r

def assign_role_to_user(auth_endpoint, token, project_id, user_id, role_id):
    """
    Asigna un rol a un usuario en un proyecto específico
    """
    url = auth_endpoint + f'/projects/{project_id}/users/{user_id}/roles/{role_id}'
    headers = {
        'X-Auth-Token': token,
    }
    
    r = requests.put(url=url, headers=headers)
    # status_code success = 204
    return r

def get_role_by_name(auth_endpoint, token, role_name):
    """
    Obtiene el ID de un rol por nombre (ej: 'admin')
    """
    url = auth_endpoint + '/roles'
    headers = {
        'X-Auth-Token': token,
    }
    
    r = requests.get(url=url, headers=headers)
    # status_code success = 200
    return r

# ================================== NOVA ==================================

def create_server(nova_endpoint, token, name, flavor_id, image_id, networks=None, availability_zone=None, project_id=None):
    url = nova_endpoint + '/servers'
    headers = {
        'Content-type': 'application/json',
        'X-Auth-Token': token,
    }
    
    data = \
        {
            'server': {
                'name': name,
                'flavorRef': flavor_id,
                'imageRef': image_id,
                'networks': networks,
            }
        }
    
    if availability_zone:
        data['server']['availability_zone'] = availability_zone
    
    r = requests.post(url=url, headers=headers, data=json.dumps(data))
    # status_code success = 202
    return r

def get_server_console(nova_endpoint, token, server_id, compute_api_version):
    url = nova_endpoint + '/servers/' + server_id + '/remote-consoles'
    headers = {
        'Content-type': 'application/json',
        'X-Auth-Token': token,
        "OpenStack-API-Version": "compute " + compute_api_version
    }
    
    data = \
        {
            "remote_console": {
                "protocol": "vnc",
                "type": "novnc"
                }
        }
    
    r = requests.post(url=url, headers=headers, data=json.dumps(data))
    # status_code success = 200
    return r

# ================================== GLANCE ==================================

def create_image(glance_endpoint, token, name, disk_format, container_format='bare', visibility='private'):
    url = glance_endpoint + '/v2/images'
    headers = {
        'Content-type': 'application/json',
        'X-Auth-Token': token,
    }
    
    data = {
        "name": name,
        "disk_format": disk_format,
        "container_format": container_format,
        "visibility": visibility
    }
    
    r = requests.post(url=url, headers=headers, data=json.dumps(data))
    # status_code success = 201
    return r

def upload_image_data(glance_endpoint, token, image_id, image_data):
    url = glance_endpoint + '/v2/images/' + image_id + '/file'
    headers = {
        'Content-Type': 'application/octet-stream',
        'X-Auth-Token': token,
    }
    
    r = requests.put(url=url, headers=headers, data=image_data)
    # status_code success = 204
    return r

def delete_image(glance_endpoint, token, image_id):
    url = glance_endpoint + '/v2/images/' + image_id
    headers = {
        'X-Auth-Token': token,
    }
    
    r = requests.delete(url=url, headers=headers)
    # status_code success = 204
    return r

# ================================== NEUTRON ==================================

def create_network(neutron_endpoint, token, name, project_id, vlan_id=None):
    url = neutron_endpoint + '/v2.0/networks'
    headers = {
        'Content-type': 'application/json',
        'X-Auth-Token': token,
    }
    
    data = {
        "network": {
            "name": name,
            "project_id": project_id,
            "port_security_enabled": True
        }
    }
    
    # Si se especifica VLAN, configurar como red VLAN provider
    if vlan_id is not None:
        data["network"]["provider:network_type"] = "vlan"
        data["network"]["provider:physical_network"] = "physnet1"
        data["network"]["provider:segmentation_id"] = int(vlan_id)
    
    r = requests.post(url=url, headers=headers, data=json.dumps(data))
    # status_code success = 201
    return r

def create_subnet(neutron_endpoint, token, name, network_id, project_id, cidr='10.0.39.96/28'):
    url = neutron_endpoint + '/v2.0/subnets'
    headers = {
        'Content-type': 'application/json',
        'X-Auth-Token': token,
    }
    
    data = {
        "subnet": {
            "name": name,
            "network_id": network_id,
            "project_id": project_id,
            "ip_version": 4,
            "cidr": cidr,
            "enable_dhcp": False,
            "gateway_ip": None
        }
    }
    
    r = requests.post(url=url, headers=headers, data=json.dumps(data))
    # status_code success = 201
    return r

def create_port(neutron_endpoint, token, name, network_id, project_id):
    url = neutron_endpoint + '/v2.0/ports'
    headers = {
        'Content-type': 'application/json',
        'X-Auth-Token': token,
    }
    
    data = {
        "port": {
            "name": name,
            "network_id": network_id,
            "project_id": project_id,
            "port_security_enabled": True,
            "allowed_address_pairs": [
                {"ip_address": "0.0.0.0/0"}
            ]
        }
    }
    
    r = requests.post(url=url, headers=headers, data=json.dumps(data))
    # status_code success = 201
    return r
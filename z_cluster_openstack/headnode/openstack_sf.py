from openstack_sdk import password_authentication_with_scoped_authorization, token_authentication_with_scoped_authorization, create_server, get_server_console, create_image, upload_image_data, delete_image, create_project, create_network, create_subnet, create_port, assign_role_to_user, get_role_by_name
from dotenv import load_dotenv
import os

load_dotenv()
ACCESS_NODE_IP = os.getenv("ACCESS_NODE_IP")
KEYSTONE_PORT = os.getenv("KEYSTONE_PORT")
NOVA_PORT = os.getenv("NOVA_PORT")
GLANCE_PORT = os.getenv("GLANCE_PORT", "9292")
NEUTRON_PORT = os.getenv("NEUTRON_PORT", "9696")
DOMAIN_ID = os.getenv("DOMAIN_ID")
ADMIN_PROJECT_ID = os.getenv("ADMIN_PROJECT_ID")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
ADMIN_USER_PASSWORD = os.getenv("ADMIN_USER_PASSWORD")
COMPUTE_API_VERSION = os.getenv("COMPUTE_API_VERSION")

KEYSTONE_ENDPOINT = 'http://' + ACCESS_NODE_IP + ':' + KEYSTONE_PORT + '/v3'
NOVA_ENDPOINT = 'http://' + ACCESS_NODE_IP + ':' + NOVA_PORT + '/v2.1'
GLANCE_ENDPOINT = 'http://' + ACCESS_NODE_IP + ':' + GLANCE_PORT
NEUTRON_ENDPOINT = 'http://' + ACCESS_NODE_IP + ':' + NEUTRON_PORT

def get_admin_token():
    """

    INPUT:

    OUTPUT:
        admin_project_token = token with scope authorization over the admin project (cloud_admin) | '' if something wrong
    
    """
    resp1 = password_authentication_with_scoped_authorization(KEYSTONE_ENDPOINT, ADMIN_USER_ID, ADMIN_USER_PASSWORD, DOMAIN_ID, ADMIN_PROJECT_ID)
    admin_project_token = ''
    if resp1.status_code == 201:
        admin_project_token = resp1.headers['X-Subject-Token']
    
    return admin_project_token

def get_token_for_project(project_id, admin_project_token):
    """

    INPUT:
        project_id = project identifier you need scoped authorization over
        admin_project_token = token with scope authorization over the admin project (cloud_admin)
    
    OUTPUT:
        token_for_project = token with scope authorization over the project identified by project_id | '' if something wrong
    
    """
    r = token_authentication_with_scoped_authorization(KEYSTONE_ENDPOINT, admin_project_token, DOMAIN_ID, project_id)
    token_for_project = ''
    if r.status_code == 201:
        token_for_project = r.headers['X-Subject-Token']
    
    return token_for_project

def create_vm(image_id, flavor_id, name, port_list, project_id, availability_zone=None):
    """

    INPUT:
        image_id = (string) identifier of image that instance will use
        flavor_id = (string) identifier of flavor that instance will use
        name = (string) name of the instance you will create
        port_list = (string list) list of port id that will be attached to instance
        project_id = (string) identifier of the project where the VM will be created
        availability_zone = (string, optional) availability zone where VM will be deployed
    
    OUTPUT:
        instance_info = dictionary with information about vm just created | {} if something wrong
    
    """
    try:
        # Obtener token scoped al proyecto específico
        project_token = get_admin_token_for_project(project_id)
        
        if not project_token:
            print(f"ERROR in create_vm: Failed to get project token for project {project_id}")
            return {}
        
        ports = [ { "port" : port } for port in port_list ]
        
        # Usar el token scoped al proyecto (ya no necesita X-Project-Id header)
        r = create_server(NOVA_ENDPOINT, project_token, name, flavor_id, image_id, ports, availability_zone, None)
        instance_info = {}
        if r.status_code == 202:
            instance_info = r.json()
        else:
            print(f"ERROR in create_vm: Nova API returned {r.status_code}")
            print(f"  Response: {r.text}")
            print(f"  VM: {name}, Image: {image_id}, Flavor: {flavor_id}")
            print(f"  Ports: {port_list}, AZ: {availability_zone}")
        
        return instance_info
    except Exception as e:
        print(f"EXCEPTION in create_vm: {str(e)}")
        import traceback
        traceback.print_exc()
        return {}

def get_console_url(instance_id, admin_project_token):
    """

    INPUT :
        instance_id = identifier of instance whose console url you need
        admin_project_token = toker with scoped authorization over admin project (cloud_admin)
    
    OUTPUT:
        console_url =  console url of the intance identified by instance_id | '' if something wrong
    
    """
    r = get_server_console(NOVA_ENDPOINT, admin_project_token, instance_id, COMPUTE_API_VERSION)
    console_url = ''
    if r.status_code == 200:
        console_url = r.json()['remote_console']['url']
    
    return console_url

def upload_image(name, image_data, disk_format, container_format='bare', visibility='private'):
    """

    INPUT:
        name = (string) name of the image
        image_data = (bytes) binary data of the image file
        disk_format = (string) format of the disk (qcow2, raw, vmdk, etc.)
        container_format = (string) container format, default 'bare'
        visibility = (string) visibility of the image (private, public, shared), default 'private'
    
    OUTPUT:
        image_info = dictionary with information about the uploaded image | {} if something wrong
    
    """
    # Obtener token admin
    admin_token = get_admin_token()
    
    # Crear imagen en Glance
    r = create_image(GLANCE_ENDPOINT, admin_token, name, disk_format, container_format, visibility)
    image_info = {}
    
    if r.status_code == 201:
        image_info = r.json()
        image_id = image_info['id']
        
        # Subir los datos de la imagen
        r_upload = upload_image_data(GLANCE_ENDPOINT, admin_token, image_id, image_data)
        
        if r_upload.status_code != 204:
            return {}
    
    return image_info

def remove_image(image_id):
    """

    INPUT:
        image_id = (string) identifier of the image to delete
    
    OUTPUT:
        success = True if deleted successfully | False if something wrong
    
    """
    # Obtener token admin
    admin_token = get_admin_token()
    
    # Eliminar imagen de Glance
    r = delete_image(GLANCE_ENDPOINT, admin_token, image_id)
    
    if r.status_code == 204:
        return True
    
    return False

def create_slice(slice_name, description=''):
    """

    INPUT:
        slice_name = (string) name for the new project/slice
        description = (string) optional description of the project
    
    OUTPUT:
        project_id = ID of the created project | '' if something wrong
    
    """
    admin_token = get_admin_token()
    
    r = create_project(KEYSTONE_ENDPOINT, admin_token, DOMAIN_ID, slice_name, description)
    project_id = ''
    if r.status_code == 201:
        project_id = r.json()['project']['id']
    
    return project_id

def assign_admin_role_to_project(project_id):
    """
    Asigna el rol 'admin' al usuario admin en el proyecto especificado
    
    INPUT:
        project_id = (string) ID del proyecto
    
    OUTPUT:
        success = (bool) True si se asignó correctamente, False si falló
    """
    admin_token = get_admin_token()
    
    # Obtener el ID del rol 'admin'
    r = get_role_by_name(KEYSTONE_ENDPOINT, admin_token, 'admin')
    if r.status_code != 200:
        return False
    
    roles = r.json().get('roles', [])
    admin_role_id = None
    for role in roles:
        if role['name'] == 'admin':
            admin_role_id = role['id']
            break
    
    if not admin_role_id:
        return False
    
    # Asignar el rol admin al usuario admin en el proyecto
    r = assign_role_to_user(KEYSTONE_ENDPOINT, admin_token, project_id, ADMIN_USER_ID, admin_role_id)
    
    return r.status_code == 204

def get_admin_token_for_project(project_id):
    """
    Obtiene un token de admin scoped a un proyecto específico
    
    INPUT:
        project_id = (string) ID del proyecto
    
    OUTPUT:
        token = token scoped al proyecto | '' si falla
    """
    admin_token = get_admin_token()
    
    r = token_authentication_with_scoped_authorization(
        KEYSTONE_ENDPOINT, 
        admin_token, 
        DOMAIN_ID, 
        project_id
    )
    
    token = ''
    if r.status_code == 201:
        token = r.headers['X-Subject-Token']
    
    return token

def create_network_slice(network_name, project_id, vlan_id=None):
    """

    INPUT:
        network_name = (string) name of the network
        project_id = (string) project ID where network will be created
        vlan_id = (int, optional) VLAN ID to assign to the network
    
    OUTPUT:
        network_id = ID of the created network | '' if something wrong
    
    """
    admin_token = get_admin_token()
    
    r = create_network(NEUTRON_ENDPOINT, admin_token, network_name, project_id, vlan_id)
    network_id = ''
    if r.status_code == 201:
        network_id = r.json()['network']['id']
    
    return network_id

def create_subnet_slice(subnet_name, network_id, project_id, cidr='10.0.39.96/28'):
    """

    INPUT:
        subnet_name = (string) name of the subnet
        network_id = (string) ID of the network to attach subnet
        project_id = (string) project ID where subnet will be created
        cidr = (string) CIDR of the subnet
    
    OUTPUT:
        subnet_id = ID of the created subnet | '' if something wrong
    
    """
    admin_token = get_admin_token()
    
    r = create_subnet(NEUTRON_ENDPOINT, admin_token, subnet_name, network_id, project_id, cidr)
    subnet_id = ''
    if r.status_code == 201:
        subnet_id = r.json()['subnet']['id']
    
    return subnet_id

def create_port_slice(port_name, network_id, project_id):
    """

    INPUT:
        port_name = (string) name of the port
        network_id = (string) ID of the network
        project_id = (string) project ID where port will be created
    
    OUTPUT:
        port_id = ID of the created port | '' if something wrong
    
    """
    admin_token = get_admin_token()
    
    r = create_port(NEUTRON_ENDPOINT, admin_token, port_name, network_id, project_id)
    port_id = ''
    if r.status_code == 201:
        port_id = r.json()['port']['id']
    
    return port_id
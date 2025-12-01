# from openstack_sf import create_vm
# from json import dumps as jdumps

# project_id = 'cd45b366563c40259ba5e5920c4c1be6'
# image_id = 'bdac805b-3ca4-4bd3-926e-a7322a923248' 
# flavor_id = '89de93a1-5f7c-4f4e-831d-c99a2ae6168d' 
# name = 'instance_1'
# port_list = ['2aaae40b-e0af-4ed1-b38c-63e3e0499c2d'] 

# instance_info = create_vm(image_id, flavor_id, name, port_list, project_id)
# print(jdumps(instance_info))

from fastapi import FastAPI, UploadFile, File, Form, Body
from openstack_sf import upload_image, remove_image, create_slice, create_network_slice, create_subnet_slice, create_port_slice, create_vm
import uvicorn
from typing import Dict

app = FastAPI(title="OpenStack API", version="1.0")

@app.post("/image-importer")
async def import_image(request: Dict = Body(...)):
    """
    Endpoint para importar una imagen a Glance desde una URL
    
    Body:
    {
        "name": "ubuntu-22.04",
        "url": "https://cloud-images.ubuntu.com/...",
        "disk_format": "qcow2"
    }
    """
    import requests
    import tempfile
    import os
    
    try:
        name = request.get("name")
        url = request.get("url")
        disk_format = request.get("disk_format")
        
        if not name or not url or not disk_format:
            return {
                "status": "error",
                "message": "name, url and disk_format are required"
            }
        
        # Crear archivo temporal
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f'.{disk_format}')
        temp_path = temp_file.name
        
        try:
            # Descargar imagen
            print(f"Downloading image from {url}...")
            response = requests.get(url, stream=True)
            
            if response.status_code != 200:
                return {
                    "status": "error",
                    "message": f"Failed to download image: HTTP {response.status_code}"
                }
            
            # Escribir en archivo temporal
            total_size = 0
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    temp_file.write(chunk)
                    total_size += len(chunk)
            
            temp_file.close()
            print(f"Downloaded {total_size} bytes to {temp_path}")
            
            # Leer el archivo descargado
            with open(temp_path, 'rb') as f:
                image_data = f.read()
            
            # Subir imagen a Glance
            print(f"Uploading to Glance...")
            image_info = upload_image(name, image_data, disk_format)
            
            if image_info:
                return {
                    "status": "success",
                    "message": "Image uploaded successfully",
                    "image_id": image_info.get('id'),
                    "image_name": image_info.get('name'),
                    "disk_format": image_info.get('disk_format'),
                    "size": image_info.get('size'),
                    "image_status": image_info.get('status'),
                    "downloaded_size": total_size
                }
            else:
                return {
                    "status": "error",
                    "message": "Failed to upload image to Glance"
                }
        
        finally:
            # Eliminar archivo temporal
            if os.path.exists(temp_path):
                os.remove(temp_path)
                print(f"Deleted temporary file {temp_path}")
    
    except Exception as e:
        return {
            "status": "error",
            "message": f"Exception: {str(e)}"
        }

@app.delete("/image-delete/{image_id}")
async def delete_image(image_id: str):
    """
    Endpoint para eliminar una imagen de Glance
    
    - image_id: UUID de la imagen a eliminar (en la URL)
    """
    success = remove_image(image_id)
    
    if success:
        return {
            "status": "success",
            "message": "Image deleted successfully",
            "image_id": image_id
        }
    else:
        return {
            "status": "error",
            "message": "Failed to delete image",
            "image_id": image_id
        }

@app.post("/deploy-topology")
async def deploy_topology(config: Dict = Body(...)):
    """
    Endpoint para desplegar una topología completa en OpenStack
    
    - config: JSON con la configuración del despliegue
    """
    slice_id = None  # Para rollback
    project_id = None
    
    try:
        # Debug: Log del JSON recibido
        print(f"[DEBUG] Received config: {config}")
        
        json_config = config.get("json_config", {})
        
        slice_id = str(json_config.get("id_slice"))
        vms = json_config.get("vms", [])
        
        if not slice_id:
            return {"status": "error", "message": "id_slice is required"}
        
        if not vms:
            return {"status": "error", "message": "vms list is required"}
        
        # Verificar que el slice no exista previamente
        import requests
        from openstack_sf import get_admin_token
        
        admin_token = get_admin_token()
        headers = {'X-Auth-Token': admin_token}
        project_name = f"id{slice_id}_project"
        
        url = 'http://192.168.202.1:5000/v3/projects'
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            projects = r.json()['projects']
            for p in projects:
                if p['name'] == project_name:
                    return {"status": "error", "message": f"Slice {slice_id} already exists"}
        
        # Extraer VLANs únicas de todas las VMs
        vlans_usadas = set()
        for vm in vms:
            conexiones = vm.get("conexiones_vlans", "")
            for vlan in conexiones.split(","):
                vlan = vlan.strip()
                if vlan:
                    vlans_usadas.add(vlan)
        
        # Mapeo de servers a availability zones
        server_to_host = {
            "worker4": "worker1",
            "worker5": "worker2",
            "worker6": "worker3"
        }
        
        # 1. Crear proyecto/slice
        project_id = create_slice(project_name, f"Slice {slice_id}")
        
        if not project_id:
            return {"status": "error", "message": "Failed to create project"}
        
        # 1.1. Asignar rol admin al usuario admin en el nuevo proyecto
        from openstack_sf import assign_admin_role_to_project
        if not assign_admin_role_to_project(project_id):
            print(f"ERROR: Failed to assign admin role, rolling back slice {slice_id}")
            await rollback_slice(slice_id)
            return {"status": "error", "message": "Failed to assign admin role, rollback executed"}
        
        print(f"✓ Project created and admin role assigned: {project_name} ({project_id})")
        
        # 2 y 3. Crear networks y subnets para cada VLAN
        # Network compartida "internet" para VLAN 11
        INTERNET_NETWORK_ID = "ac30b257-858f-4796-941c-233435c9b9a7"
        
        network_ids = {}
        for vlan in vlans_usadas:
            vlan = vlan.strip()
            if not vlan:
                continue
            
            # Si es VLAN 11, usar la network compartida "internet"
            if vlan == "11":
                network_ids["11"] = INTERNET_NETWORK_ID
                print(f"✓ Using shared network 'internet' for VLAN 11")
                continue
            
            network_name = f"id{slice_id}_network_vlan{vlan}"
            network_id = create_network_slice(network_name, project_id, int(vlan))
            
            if not network_id:
                print(f"ERROR: Failed to create network for VLAN {vlan}, rolling back slice {slice_id}")
                await rollback_slice(slice_id)
                return {"status": "error", "message": f"Failed to create network for VLAN {vlan}, rollback executed"}
            
            network_ids[vlan] = network_id
            
            # Crear subnet para esta network
            subnet_name = f"id{slice_id}_subnet_vlan{vlan}"
            subnet_id = create_subnet_slice(subnet_name, network_id, project_id)
            
            if not subnet_id:
                print(f"ERROR: Failed to create subnet for VLAN {vlan}, rolling back slice {slice_id}")
                await rollback_slice(slice_id)
                return {"status": "error", "message": f"Failed to create subnet for VLAN {vlan}, rollback executed"}
        
        # 4 y 5. Procesar cada VM
        for vm in vms:
            vm_name_short = vm.get("nombre")  # vmX
            vm_name = f"id{slice_id}_{vm_name_short}"
            image_id = vm.get("image")
            flavor_id = vm.get("id_flavor_openstack")
            conexiones_vlans = vm.get("conexiones_vlans", "").split(",")
            server = vm.get("server")
            
            # Determinar availability zone con host
            host = server_to_host.get(server)
            availability_zone = f"nova:{host}" if host else None
            
            # Crear ports para esta VM en cada VLAN conectada
            port_ids = []
            for vlan in conexiones_vlans:
                vlan = vlan.strip()
                if not vlan or vlan not in network_ids:
                    continue
                
                port_name = f"id{slice_id}_port_{vm_name_short}_vlan{vlan}"
                port_id = create_port_slice(port_name, network_ids[vlan], project_id)
                
                if not port_id:
                    print(f"ERROR: Failed to create port for VM {vm_name_short} on VLAN {vlan}, rolling back slice {slice_id}")
                    await rollback_slice(slice_id)
                    return {"status": "error", "message": f"Failed to create port for VM {vm_name_short} on VLAN {vlan}, rollback executed"}
                
                port_ids.append(port_id)
            
            # Crear la VM
            print(f"Creating VM {vm_name} with {len(port_ids)} ports on {availability_zone}")
            instance_info = create_vm(
                image_id=image_id,
                flavor_id=flavor_id,
                name=vm_name,
                port_list=port_ids,
                project_id=project_id,
                availability_zone=availability_zone
            )
            
            if not instance_info:
                print(f"ERROR: Failed to create VM {vm_name}, rolling back slice {slice_id}")
                await rollback_slice(slice_id)
                return {"status": "error", "message": f"Failed to create VM {vm_name}, rollback executed"}
            
            print(f"✓ VM {vm_name} created: {instance_info.get('server', {}).get('id', '')}")
        
        # Obtener reglas del security group default
        default_sg_rules = []
        try:
            from openstack_sf import get_admin_token_for_project
            import requests
            token = get_admin_token_for_project(project_id)
            headers = {'X-Auth-Token': token}
            
            # Listar security groups del proyecto
            url_sgs = f'http://192.168.202.1:9696/v2.0/security-groups?project_id={project_id}'
            r_sgs = requests.get(url_sgs, headers=headers)
            if r_sgs.status_code == 200:
                sgs = r_sgs.json().get('security_groups', [])
                for sg in sgs:
                    if sg['name'] == 'default':
                        rules = sg.get('security_group_rules', [])
                        
                        # Mapear reglas según el orden estándar
                        rule_mapping = {}
                        for rule in rules:
                            direction = rule['direction']
                            ethertype = rule['ethertype']
                            remote_group = rule.get('remote_group_id')
                            
                            # Regla 1: egress IPv4
                            if direction == 'egress' and ethertype == 'IPv4' and not remote_group:
                                rule_mapping[1] = rule['id']
                            # Regla 2: egress IPv6
                            elif direction == 'egress' and ethertype == 'IPv6' and not remote_group:
                                rule_mapping[2] = rule['id']
                            # Regla 3: ingress IPv4 desde mismo SG
                            elif direction == 'ingress' and ethertype == 'IPv4' and remote_group:
                                rule_mapping[3] = rule['id']
                            # Regla 4: ingress IPv6 desde mismo SG
                            elif direction == 'ingress' and ethertype == 'IPv6' and remote_group:
                                rule_mapping[4] = rule['id']
                        
                        # Generar lista ordenada en formato "id:N;uuid:..."
                        for rule_id in sorted(rule_mapping.keys()):
                            default_sg_rules.append(f"id:{rule_id};uuid:{rule_mapping[rule_id]}")
                        
                        break
        except Exception as e:
            print(f"Warning: Could not get default SG rules: {e}")
        
        return {
            "status": "success",
            "message": "Topology deployed successfully",
            "project_id": project_id,
            "default_sg_rules": default_sg_rules
        }
        
    except Exception as e:
        import traceback
        print(f"EXCEPTION during deployment: {str(e)}")
        traceback.print_exc()
        
        # Rollback en caso de excepción
        if slice_id:
            print(f"Rolling back slice {slice_id} due to exception")
            await rollback_slice(slice_id)
        
        return {
            "status": "error",
            "message": f"Deployment failed: {str(e)}, rollback executed"
        }

async def rollback_slice(slice_id: str):
    """
    Función auxiliar para hacer rollback de un slice fallido
    """
    try:
        print(f"[ROLLBACK] Starting rollback for slice {slice_id}")
        result = await delete_slice(slice_id)
        print(f"[ROLLBACK] Result: {result}")
    except Exception as e:
        print(f"[ROLLBACK] Error during rollback: {str(e)}")

@app.delete("/delete-slice/{slice_id}")
async def delete_slice(slice_id: str):
    """
    Endpoint para eliminar un slice completo con todos sus recursos
    
    - slice_id: ID del slice a eliminar (ej: "3" para id3_project)
    """
    try:
        import requests
        from openstack_sf import get_admin_token
        
        admin_token = get_admin_token()
        headers = {'X-Auth-Token': admin_token}
        
        # Buscar el proyecto
        project_name = f"id{slice_id}_project"
        url = 'http://192.168.202.1:5000/v3/projects'
        r = requests.get(url, headers=headers)
        
        if r.status_code != 200:
            return {"status": "error", "message": "Failed to list projects"}
        
        projects = r.json()['projects']
        project_id = None
        for p in projects:
            if p['name'] == project_name:
                project_id = p['id']
                break
        
        if not project_id:
            return {"status": "error", "message": f"Project {project_name} not found"}
        
        print(f"Deleting slice: {project_name} ({project_id})")
        
        # 1. Eliminar todas las VMs del proyecto
        url_servers = f'http://192.168.202.1:8774/v2.1/servers?project_id={project_id}&all_tenants=1'
        r_servers = requests.get(url_servers, headers=headers)
        vms_deleted = 0
        if r_servers.status_code == 200:
            servers = r_servers.json().get('servers', [])
            for server in servers:
                del_url = f'http://192.168.202.1:8774/v2.1/servers/{server["id"]}'
                r_del = requests.delete(del_url, headers=headers)
                if r_del.status_code == 204:
                    vms_deleted += 1
                    print(f"  Deleted VM: {server['name']}")
        
        # 2. Eliminar todos los ports del proyecto
        url_ports = f'http://192.168.202.1:9696/v2.0/ports?project_id={project_id}'
        r_ports = requests.get(url_ports, headers=headers)
        ports_deleted = 0
        if r_ports.status_code == 200:
            ports = r_ports.json().get('ports', [])
            for port in ports:
                del_url = f'http://192.168.202.1:9696/v2.0/ports/{port["id"]}'
                r_del = requests.delete(del_url, headers=headers)
                if r_del.status_code == 204:
                    ports_deleted += 1
                    print(f"  Deleted port: {port['name']}")
        
        # 3. Eliminar subnets y networks del proyecto
        url_nets = f'http://192.168.202.1:9696/v2.0/networks?project_id={project_id}'
        r_nets = requests.get(url_nets, headers=headers)
        networks_deleted = 0
        subnets_deleted = 0
        if r_nets.status_code == 200:
            networks = r_nets.json().get('networks', [])
            for net in networks:
                # Eliminar subnets primero
                for subnet_id in net.get('subnets', []):
                    del_url = f'http://192.168.202.1:9696/v2.0/subnets/{subnet_id}'
                    r_del = requests.delete(del_url, headers=headers)
                    if r_del.status_code == 204:
                        subnets_deleted += 1
                
                # Eliminar network
                del_url = f'http://192.168.202.1:9696/v2.0/networks/{net["id"]}'
                r_del = requests.delete(del_url, headers=headers)
                if r_del.status_code == 204:
                    networks_deleted += 1
                    print(f"  Deleted network: {net['name']}")
        
        # 4. Eliminar security groups del proyecto
        url_sgs = f'http://192.168.202.1:9696/v2.0/security-groups?project_id={project_id}'
        r_sgs = requests.get(url_sgs, headers=headers)
        sgs_deleted = 0
        if r_sgs.status_code == 200:
            sgs = r_sgs.json().get('security_groups', [])
            for sg in sgs:
                # No intentar eliminar el SG 'default' si causa problemas
                del_url = f'http://192.168.202.1:9696/v2.0/security-groups/{sg["id"]}'
                r_del = requests.delete(del_url, headers=headers)
                if r_del.status_code == 204:
                    sgs_deleted += 1
                    print(f"  Deleted security group: {sg['name']}")
        
        # 5. Eliminar el proyecto
        del_url = f'http://192.168.202.1:5000/v3/projects/{project_id}'
        r_del = requests.delete(del_url, headers=headers)
        
        if r_del.status_code != 204:
            return {
                "status": "error",
                "message": f"Failed to delete project: {r_del.text}"
            }
        
        print(f"✓ Slice {project_name} deleted successfully")
        
        return {
            "status": "success",
            "message": f"Slice {project_name} deleted successfully",
            "project_id": project_id,
            "resources_deleted": {
                "vms": vms_deleted,
                "ports": ports_deleted,
                "subnets": subnets_deleted,
                "networks": networks_deleted,
                "security_groups": sgs_deleted
            }
        }
        
    except Exception as e:
        import traceback
        print(f"EXCEPTION: {str(e)}")
        traceback.print_exc()
        return {
            "status": "error",
            "message": f"Deletion failed: {str(e)}"
        }

@app.get("/slice-status/{slice_id}")
async def get_slice_status(slice_id: str):
    """
    Obtiene el estado de todas las VMs de un slice
    
    - slice_id: ID del slice (ej: "4" para id4_project)
    """
    try:
        import requests
        from openstack_sf import get_admin_token
        
        admin_token = get_admin_token()
        headers = {'X-Auth-Token': admin_token}
        
        # Buscar el proyecto
        project_name = f"id{slice_id}_project"
        url = 'http://192.168.202.1:5000/v3/projects'
        r = requests.get(url, headers=headers)
        
        if r.status_code != 200:
            return {"status": "error", "message": "Failed to list projects"}
        
        projects = r.json()['projects']
        project_id = None
        for p in projects:
            if p['name'] == project_name:
                project_id = p['id']
                break
        
        if not project_id:
            return {"status": "error", "message": f"Project {project_name} not found"}
        
        # Listar VMs del proyecto
        url_servers = f'http://192.168.202.1:8774/v2.1/servers?project_id={project_id}&all_tenants=1'
        r_servers = requests.get(url_servers, headers=headers)
        
        if r_servers.status_code != 200:
            return {"status": "error", "message": "Failed to list servers"}
        
        servers = r_servers.json().get('servers', [])
        vms_status = []
        
        for server in servers:
            # Obtener detalles de cada VM
            detail_url = f'http://192.168.202.1:8774/v2.1/servers/{server["id"]}'
            r_detail = requests.get(detail_url, headers=headers)
            
            if r_detail.status_code == 200:
                details = r_detail.json()['server']
                vms_status.append({
                    "name": server['name'],
                    "id": server['id'],
                    "status": details.get('status'),
                    "power_state": details.get('OS-EXT-STS:power_state'),
                    "vm_state": details.get('OS-EXT-STS:vm_state'),
                    "task_state": details.get('OS-EXT-STS:task_state')
                })
        
        return {
            "status": "success",
            "slice_id": slice_id,
            "project_id": project_id,
            "total_vms": len(vms_status),
            "vms": vms_status
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": f"Failed: {str(e)}"}

@app.post("/slice-pause/{slice_id}")
async def pause_slice(slice_id: str):
    """
    Pausa todas las VMs de un slice
    
    - slice_id: ID del slice
    """
    return await _slice_action(slice_id, "pause", {"pause": None})

@app.post("/slice-unpause/{slice_id}")
async def unpause_slice(slice_id: str):
    """
    Reanuda todas las VMs de un slice
    
    - slice_id: ID del slice
    """
    return await _slice_action(slice_id, "unpause", {"unpause": None})

@app.post("/slice-stop/{slice_id}")
async def stop_slice(slice_id: str):
    """
    Apaga todas las VMs de un slice
    
    - slice_id: ID del slice
    """
    return await _slice_action(slice_id, "stop", {"os-stop": None})

@app.post("/slice-start/{slice_id}")
async def start_slice(slice_id: str):
    """
    Enciende todas las VMs de un slice
    
    - slice_id: ID del slice
    """
    return await _slice_action(slice_id, "start", {"os-start": None})

@app.post("/slice-reboot/{slice_id}")
async def reboot_slice(slice_id: str):
    """
    Reinicia todas las VMs de un slice
    
    - slice_id: ID del slice
    """
    return await _slice_action(slice_id, "reboot", {"reboot": {"type": "SOFT"}})

async def _slice_action(slice_id: str, action_name: str, action_body: dict):
    """
    Función auxiliar para ejecutar acciones en todas las VMs de un slice
    """
    try:
        import requests
        import json
        from openstack_sf import get_admin_token
        
        admin_token = get_admin_token()
        headers = {
            'Content-type': 'application/json',
            'X-Auth-Token': admin_token
        }
        
        # Buscar el proyecto
        project_name = f"id{slice_id}_project"
        url = 'http://192.168.202.1:5000/v3/projects'
        r = requests.get(url, headers={'X-Auth-Token': admin_token})
        
        if r.status_code != 200:
            return {"status": "error", "message": "Failed to list projects"}
        
        projects = r.json()['projects']
        project_id = None
        for p in projects:
            if p['name'] == project_name:
                project_id = p['id']
                break
        
        if not project_id:
            return {"status": "error", "message": f"Project {project_name} not found"}
        
        # Listar VMs del proyecto
        url_servers = f'http://192.168.202.1:8774/v2.1/servers?project_id={project_id}&all_tenants=1'
        r_servers = requests.get(url_servers, headers={'X-Auth-Token': admin_token})
        
        if r_servers.status_code != 200:
            return {"status": "error", "message": "Failed to list servers"}
        
        servers = r_servers.json().get('servers', [])
        results = []
        
        for server in servers:
            # Ejecutar acción en cada VM
            action_url = f'http://192.168.202.1:8774/v2.1/servers/{server["id"]}/action'
            r_action = requests.post(action_url, headers=headers, data=json.dumps(action_body))
            
            results.append({
                "vm_name": server['name'],
                "vm_id": server['id'],
                "success": r_action.status_code == 202,
                "status_code": r_action.status_code
            })
            
            if r_action.status_code == 202:
                print(f"  {action_name.upper()}: {server['name']}")
        
        success_count = sum(1 for r in results if r['success'])
        
        return {
            "status": "success",
            "action": action_name,
            "slice_id": slice_id,
            "total_vms": len(results),
            "successful": success_count,
            "failed": len(results) - success_count,
            "details": results
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": f"Failed: {str(e)}"}

@app.get("/vm-status/{slice_id}/{vm_name}")
async def get_vm_status(slice_id: str, vm_name: str):
    """
    Obtiene el estado de una VM específica
    
    - slice_id: ID del slice (ej: "4")
    - vm_name: Nombre corto de la VM (ej: "vm1")
    """
    try:
        import requests
        from openstack_sf import get_admin_token
        
        admin_token = get_admin_token()
        headers = {'X-Auth-Token': admin_token}
        
        # Buscar el proyecto
        project_name = f"id{slice_id}_project"
        url = 'http://192.168.202.1:5000/v3/projects'
        r = requests.get(url, headers=headers)
        
        if r.status_code != 200:
            return {"status": "error", "message": "Failed to list projects"}
        
        projects = r.json()['projects']
        project_id = None
        for p in projects:
            if p['name'] == project_name:
                project_id = p['id']
                break
        
        if not project_id:
            return {"status": "error", "message": f"Project {project_name} not found"}
        
        # Buscar la VM específica
        full_vm_name = f"id{slice_id}_{vm_name}"
        url_servers = f'http://192.168.202.1:8774/v2.1/servers?project_id={project_id}&all_tenants=1'
        r_servers = requests.get(url_servers, headers=headers)
        
        if r_servers.status_code != 200:
            return {"status": "error", "message": "Failed to list servers"}
        
        servers = r_servers.json().get('servers', [])
        vm_id = None
        for server in servers:
            if server['name'] == full_vm_name:
                vm_id = server['id']
                break
        
        if not vm_id:
            return {"status": "error", "message": f"VM {full_vm_name} not found"}
        
        # Obtener detalles de la VM
        detail_url = f'http://192.168.202.1:8774/v2.1/servers/{vm_id}'
        r_detail = requests.get(detail_url, headers=headers)
        
        if r_detail.status_code != 200:
            return {"status": "error", "message": "Failed to get VM details"}
        
        details = r_detail.json()['server']
        
        return {
            "status": "success",
            "vm_name": vm_name,
            "full_name": full_vm_name,
            "vm_id": vm_id,
            "vm_status": details.get('status'),
            "power_state": details.get('OS-EXT-STS:power_state'),
            "vm_state": details.get('OS-EXT-STS:vm_state'),
            "task_state": details.get('OS-EXT-STS:task_state'),
            "host": details.get('OS-EXT-SRV-ATTR:host'),
            "availability_zone": details.get('OS-EXT-AZ:availability_zone')
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": f"Failed: {str(e)}"}

@app.post("/vm-pause/{slice_id}/{vm_name}")
async def pause_vm(slice_id: str, vm_name: str):
    """
    Pausa una VM específica
    """
    return await _vm_action(slice_id, vm_name, "pause", {"pause": None})

@app.post("/vm-unpause/{slice_id}/{vm_name}")
async def unpause_vm(slice_id: str, vm_name: str):
    """
    Reanuda una VM específica
    """
    return await _vm_action(slice_id, vm_name, "unpause", {"unpause": None})

@app.post("/vm-stop/{slice_id}/{vm_name}")
async def stop_vm(slice_id: str, vm_name: str):
    """
    Apaga una VM específica
    """
    return await _vm_action(slice_id, vm_name, "stop", {"os-stop": None})

@app.post("/vm-start/{slice_id}/{vm_name}")
async def start_vm(slice_id: str, vm_name: str):
    """
    Enciende una VM específica
    """
    return await _vm_action(slice_id, vm_name, "start", {"os-start": None})

@app.post("/vm-reboot/{slice_id}/{vm_name}")
async def reboot_vm(slice_id: str, vm_name: str):
    """
    Reinicia una VM específica
    """
    return await _vm_action(slice_id, vm_name, "reboot", {"reboot": {"type": "SOFT"}})

async def _vm_action(slice_id: str, vm_name: str, action_name: str, action_body: dict):
    """
    Función auxiliar para ejecutar acciones en una VM específica
    """
    try:
        import requests
        import json
        from openstack_sf import get_admin_token
        
        admin_token = get_admin_token()
        headers = {
            'Content-type': 'application/json',
            'X-Auth-Token': admin_token
        }
        
        # Buscar el proyecto
        project_name = f"id{slice_id}_project"
        url = 'http://192.168.202.1:5000/v3/projects'
        r = requests.get(url, headers={'X-Auth-Token': admin_token})
        
        if r.status_code != 200:
            return {"status": "error", "message": "Failed to list projects"}
        
        projects = r.json()['projects']
        project_id = None
        for p in projects:
            if p['name'] == project_name:
                project_id = p['id']
                break
        
        if not project_id:
            return {"status": "error", "message": f"Project {project_name} not found"}
        
        # Buscar la VM específica
        full_vm_name = f"id{slice_id}_{vm_name}"
        url_servers = f'http://192.168.202.1:8774/v2.1/servers?project_id={project_id}&all_tenants=1'
        r_servers = requests.get(url_servers, headers={'X-Auth-Token': admin_token})
        
        if r_servers.status_code != 200:
            return {"status": "error", "message": "Failed to list servers"}
        
        servers = r_servers.json().get('servers', [])
        vm_id = None
        for server in servers:
            if server['name'] == full_vm_name:
                vm_id = server['id']
                break
        
        if not vm_id:
            return {"status": "error", "message": f"VM {full_vm_name} not found"}
        
        # Ejecutar acción en la VM
        action_url = f'http://192.168.202.1:8774/v2.1/servers/{vm_id}/action'
        r_action = requests.post(action_url, headers=headers, data=json.dumps(action_body))
        
        if r_action.status_code == 202:
            print(f"  {action_name.upper()}: {full_vm_name}")
            return {
                "status": "success",
                "action": action_name,
                "vm_name": vm_name,
                "full_name": full_vm_name,
                "vm_id": vm_id,
                "message": f"Action {action_name} executed successfully"
            }
        else:
            return {
                "status": "error",
                "action": action_name,
                "vm_name": vm_name,
                "message": f"Action failed with status {r_action.status_code}",
                "details": r_action.text
            }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": f"Failed: {str(e)}"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5805)
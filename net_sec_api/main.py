from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
from typing import List, Dict, Tuple
import mysql.connector
from mysql.connector import Error
import os
import logging
from topology_calculator import TopologyLinksGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Networking & Security API",
    version="1.0.0",
    description="API para mapeo de VLANs y configuración de red"
)

# Configuración de BD
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'slices_db'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'database': os.getenv('DB_NAME', 'slices_db'),
    'user': os.getenv('DB_USER', 'slices_user'),
    'password': os.getenv('DB_PASSWORD', 'slices_pass123')
}

# Rango de VLANs disponibles
VLAN_MIN = 2
VLAN_MAX = 4094

# Rango de Networks disponibles (192.168.0.0/24 - 192.168.128.0/24)
NETWORK_MIN = 0
NETWORK_MAX = 128

# ==================== MODELOS ====================

class VlanMappingRequest(BaseModel):
    slice_id: int

# ==================== FUNCIONES AUXILIARES ====================

def get_used_vlans_from_db() -> List[int]:
    """
    Obtiene todas las VLANs actualmente en uso de la BD
    Lee el campo 'vlans' de todos los slices con tipo='desplegado' o tipo='validado'
    Formato en BD: "2,3,4,5" -> [2, 3, 4, 5]
    """
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener todos los slices que tienen VLANs asignadas
        query = """
            SELECT vlans FROM slices 
            WHERE vlans IS NOT NULL 
            AND vlans != ''
            AND tipo IN ('validado', 'desplegado')
        """
        cursor.execute(query)
        results = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        used_vlans = []
        for row in results:
            vlans_str = row['vlans']
            if vlans_str:
                # Parsear "2,3,4,5" -> [2, 3, 4, 5]
                vlans = [int(v.strip()) for v in vlans_str.split(',') if v.strip()]
                used_vlans.extend(vlans)
        
        return sorted(set(used_vlans))  # Eliminar duplicados y ordenar
        
    except Error as e:
        logger.error(f"Error al obtener VLANs usadas: {str(e)}")
        return []

def allocate_vlans(num_vlans_needed: int, used_vlans: List[int]) -> List[int]:
    """
    Asigna VLANs disponibles, reutilizando espacios libres
    
    Ejemplo:
    - used_vlans = [2,3,4,5,22,23,24,40]
    - num_vlans_needed = 7
    - Resultado: [6,7,8,9,22,23,24] (reutiliza 22-24 que quedaron libres)
    """
    used_set = set(used_vlans)
    allocated = []
    
    # Buscar VLANs disponibles en el rango
    for vlan_id in range(VLAN_MIN, VLAN_MAX + 1):
        if vlan_id not in used_set:
            allocated.append(vlan_id)
            if len(allocated) == num_vlans_needed:
                break
    
    if len(allocated) < num_vlans_needed:
        raise Exception(f"No hay suficientes VLANs disponibles. Necesarias: {num_vlans_needed}, Disponibles: {len(allocated)}")
    
    return allocated

def get_used_networks_from_db() -> List[str]:
    """
    Obtiene todas las networks actualmente en uso de la BD
    Lee el campo 'network' de todos los slices con tipo='desplegado' o tipo='validado'
    Formato en BD: "192.168.5.0/24"
    """
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener todos los slices que tienen network asignada
        query = """
            SELECT network FROM slices 
            WHERE network IS NOT NULL 
            AND network != ''
            AND tipo IN ('validado', 'desplegado')
        """
        cursor.execute(query)
        results = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        used_networks = [row['network'] for row in results if row['network']]
        return used_networks
        
    except Error as e:
        logger.error(f"Error al obtener networks usadas: {str(e)}")
        return []

def allocate_network(used_networks: List[str]) -> str:
    """
    Asigna una network disponible del rango 192.168.0.0/24 - 192.168.128.0/24
    Reutiliza espacios libres si hay slices eliminados
    
    Ejemplo:
    - used_networks = ["192.168.0.0/24", "192.168.1.0/24", "192.168.5.0/24"]
    - Resultado: "192.168.2.0/24" (reutiliza el espacio libre)
    """
    used_set = set(used_networks)
    
    # Buscar network disponible en el rango
    for network_id in range(NETWORK_MIN, NETWORK_MAX + 1):
        network = f"192.168.{network_id}.0/24"
        if network not in used_set:
            return network
    
    raise Exception(f"No hay networks disponibles en el rango 192.168.0.0/24 - 192.168.128.0/24")

def calculate_topology_links(topology: Dict) -> List[Tuple[str, str]]:
    """
    Calcula los enlaces internos de una topología
    Retorna lista de tuplas (vm_nombre1, vm_nombre2)
    """
    topology_name = topology['nombre'].lower()
    vms = topology['vms']
    num_vms = len(vms)
    
    generator = TopologyLinksGenerator()
    
    # Obtener enlaces como índices (1-indexed)
    links_indices = generator.get_topology_links(topology_name, num_vms)
    
    # Convertir índices a nombres de VMs
    links_names = []
    for vm1_idx, vm2_idx in links_indices:
        vm1_name = vms[vm1_idx - 1]['nombre']  # Convertir de 1-indexed a 0-indexed
        vm2_name = vms[vm2_idx - 1]['nombre']
        links_names.append((vm1_name, vm2_name))
    
    return links_names

def parse_conexiones_vms(conexiones_str: str) -> List[Tuple[str, str]]:
    """
    Parsea el string conexiones_vms
    Ejemplo: "vm1-vm6;vm2-vm6" -> [("vm1", "vm6"), ("vm2", "vm6")]
    """
    if not conexiones_str or conexiones_str.strip() == "":
        return []
    
    connections = []
    for connection in conexiones_str.split(';'):
        if '-' in connection:
            vm1, vm2 = connection.strip().split('-')
            connections.append((vm1.strip(), vm2.strip()))
    
    return connections

def map_vlans_to_links(all_links: List[Tuple[str, str]], allocated_vlans: List[int]) -> Dict[str, int]:
    """
    Mapea VLANs a enlaces
    Retorna diccionario con formato: {"vm1-vm2": vlan_id, "vm2-vm6": vlan_id, ...}
    """
    if len(all_links) != len(allocated_vlans):
        raise Exception(f"Mismatch: {len(all_links)} enlaces vs {len(allocated_vlans)} VLANs")
    
    vlan_mapping = {}
    for i, (vm1, vm2) in enumerate(all_links):
        # Crear clave normalizada (siempre en orden alfabético para consistencia)
        link_key = f"{vm1}-{vm2}"
        vlan_mapping[link_key] = allocated_vlans[i]
    
    return vlan_mapping

def update_vm_vlan_connections(peticion_json: Dict, vlan_mapping: Dict[str, int]) -> None:
    """
    Actualiza el campo conexiones_vlans de cada VM con los VLANs correspondientes
    
    Para cada VM, busca en vlan_mapping todos los enlaces que la involucran
    y construye el string en formato: "vlan1,vlan2,vlan3"
    
    Si internet="si", se agrega VLAN 1 al principio
    
    Ejemplo:
    - vlan_mapping = {"vm1-vm2": 8, "vm3-vm4": 9, "vm2-vm5": 12, "vm4-vm1": 13}
    - vm1 participa en: "vm1-vm2" (8) y "vm4-vm1" (13)
    - vm1.internet = "no" -> vm1.conexiones_vlans = "8,13"
    - vm1.internet = "si" -> vm1.conexiones_vlans = "1,8,13"
    """
    # Crear un diccionario para cada VM con sus VLANs
    vm_vlans = {}
    
    for link_key, vlan_id in vlan_mapping.items():
        # Parsear el link_key "vm1-vm2" -> vm1, vm2
        vms = link_key.split('-')
        if len(vms) == 2:
            vm1, vm2 = vms[0].strip(), vms[1].strip()
            
            # Agregar VLAN a ambas VMs
            if vm1 not in vm_vlans:
                vm_vlans[vm1] = []
            if vm2 not in vm_vlans:
                vm_vlans[vm2] = []
            
            vm_vlans[vm1].append(vlan_id)
            vm_vlans[vm2].append(vlan_id)
    
    # Actualizar cada VM en el JSON con sus conexiones_vlans
    for topology in peticion_json['topologias']:
        for vm in topology['vms']:
            vm_name = vm['nombre']
            internet = vm.get('internet', 'no')
            
            # Lista de VLANs para esta VM
            vlans_list = []
            
            # Si internet="si", agregar VLAN 1 al principio
            if internet == 'si':
                vlans_list.append(1)
                logger.info(f"VM {vm_name}: internet=si, agregando VLAN 1")
            
            # Agregar VLANs de conexiones (si existen)
            if vm_name in vm_vlans:
                # Eliminar duplicados y ordenar (excluyendo VLAN 1 que ya se agregó)
                connection_vlans = sorted(set(vm_vlans[vm_name]))
                vlans_list.extend(connection_vlans)
            
            # Crear string de VLANs
            if vlans_list:
                vm['conexiones_vlans'] = ','.join(map(str, vlans_list))
                logger.info(f"VM {vm_name}: conexiones_vlans = {vm['conexiones_vlans']}")
            else:
                # VM sin conexiones ni internet (posible en topología "1vm")
                vm['conexiones_vlans'] = ""
                logger.info(f"VM {vm_name}: Sin conexiones VLAN")

# ==================== ENDPOINTS ====================

@app.get("/")
async def root():
    return {
        "message": "Networking & Security API",
        "status": "activo",
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check():
    return {"status": "OK"}

@app.post("/map-vlans")
async def map_vlans(request: VlanMappingRequest):
    """
    Mapea VLANs y Network para un slice validado
    
    Proceso:
    1. Obtener slice de la BD
    2. Actualizar id_slice en el JSON (no se guarda en BD aún)
    3. Calcular enlaces de topologías
    4. Calcular enlaces de conexiones_vms
    5. Obtener VLANs usadas y asignar VLANs disponibles
    6. Mapear VLANs a enlaces y actualizar JSON
    7. Obtener networks usadas y asignar network disponible
    8. Actualizar BD solo con vlans y network (NO peticion_json)
    9. Retornar JSON mapeado y resumen
    """
    try:
        # 1. Obtener slice de la BD
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM slices WHERE id = %s", (request.slice_id,))
        slice_data = cursor.fetchone()
        
        if not slice_data:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Slice {request.slice_id} no encontrado"
            )
        
        if slice_data['tipo'] != 'validado':
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Slice debe tener tipo='validado' (actual: {slice_data['tipo']})"
            )
        
        # Parsear peticion_json
        import json
        peticion_json = json.loads(slice_data['peticion_json']) if isinstance(slice_data['peticion_json'], str) else slice_data['peticion_json']
        
        # 2. Actualizar id_slice en el JSON
        peticion_json['id_slice'] = str(request.slice_id)
        
        # 3. Calcular enlaces de topologías (orden: primero topologías)
        all_links = []
        topology_links_count = 0
        
        for topology in peticion_json['topologias']:
            topo_links = calculate_topology_links(topology)
            all_links.extend(topo_links)
            topology_links_count += len(topo_links)
        
        logger.info(f"Slice {request.slice_id}: {topology_links_count} enlaces de topologías")
        
        # 4. Calcular enlaces de conexiones_vms (orden: después de topologías)
        conexiones_vms = peticion_json.get('conexiones_vms', '')
        inter_topo_links = parse_conexiones_vms(conexiones_vms)
        all_links.extend(inter_topo_links)
        
        logger.info(f"Slice {request.slice_id}: {len(inter_topo_links)} enlaces inter-topología")
        logger.info(f"Slice {request.slice_id}: {len(all_links)} enlaces totales")
        
        # 5. Obtener VLANs usadas y asignar VLANs disponibles
        used_vlans = get_used_vlans_from_db()
        logger.info(f"VLANs actualmente en uso: {len(used_vlans)}")
        
        allocated_vlans = allocate_vlans(len(all_links), used_vlans)
        logger.info(f"Slice {request.slice_id}: VLANs asignadas: {allocated_vlans}")
        
        # 6. Mapear VLANs a enlaces y actualizar JSON
        vlan_mapping = map_vlans_to_links(all_links, allocated_vlans)
        vlans_str = ','.join(map(str, allocated_vlans))
        peticion_json['vlans_usadas'] = vlans_str
        
        # Actualizar conexiones_vlans de cada VM
        update_vm_vlan_connections(peticion_json, vlan_mapping)
        
        # 7. Obtener networks usadas y asignar network disponible
        used_networks = get_used_networks_from_db()
        logger.info(f"Networks actualmente en uso: {len(used_networks)}")
        
        allocated_network = allocate_network(used_networks)
        logger.info(f"Slice {request.slice_id}: Network asignada: {allocated_network}")
        
        # Actualizar JSON con network
        peticion_json['network'] = allocated_network
        
        # 8. Actualizar BD solo con vlans y network (NO peticion_json aún)
        update_query = """
            UPDATE slices 
            SET vlans = %s,
                network = %s
            WHERE id = %s
        """
        cursor.execute(update_query, (
            vlans_str,
            allocated_network,
            request.slice_id
        ))
        connection.commit()
        
        cursor.close()
        connection.close()
        
        logger.info(f"Slice {request.slice_id}: VLANs y Network guardados en BD")
        
        # 9. Retornar JSON mapeado y resumen
        return {
            "success": True,
            "slice_id": request.slice_id,
            "total_links": len(all_links),
            "topology_links": topology_links_count,
            "inter_topology_links": len(inter_topo_links),
            "vlans_allocated": allocated_vlans,
            "vlans_string": vlans_str,
            "network_allocated": allocated_network,
            "vlan_mapping": vlan_mapping,
            "all_links": [f"{vm1}-{vm2}" for vm1, vm2 in all_links],
            "mapped_json": peticion_json
        }
        
    except HTTPException:
        raise
    except Error as e:
        logger.error(f"Error en base de datos: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en base de datos: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error interno: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=6300, workers=2)

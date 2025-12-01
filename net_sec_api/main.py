from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
from typing import List, Dict, Tuple
import mysql.connector
from mysql.connector import Error
import os
import logging
import pika
import json
import threading
import time
from topology_calculator import TopologyLinksGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Networking & Security API",
    version="1.0.0",
    description="API para mapeo de VLANs y configuración de red"
)

# Configuración de BD - Slices
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'slices_db'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'database': os.getenv('DB_NAME', 'slices_db'),
    'user': os.getenv('DB_USER', 'slices_user'),
    'password': os.getenv('DB_PASSWORD', 'slices_pass123')
}

# Configuración de BD - Security Groups
SG_DB_CONFIG = {
    'host': os.getenv('SG_DB_HOST', 'security_groups_db'),
    'port': int(os.getenv('SG_DB_PORT', 3306)),
    'database': os.getenv('SG_DB_NAME', 'security_groups_db'),
    'user': os.getenv('SG_DB_USER', 'secgroups_user'),
    'password': os.getenv('SG_DB_PASSWORD', 'secgroups_pass123')
}

# Rangos de VLANs disponibles por zona
VLAN_POOLS = {
    'linux': {'min': 5, 'max': 900},
    'openstack': {'min': 15, 'max': 900}
}

# Configuración RabbitMQ
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', 'rabbitmq')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', 5672))
RABBITMQ_USER = os.getenv('RABBITMQ_USER', 'guest')
RABBITMQ_PASS = os.getenv('RABBITMQ_PASS', 'guest')

# Nombres de colas
VLAN_QUEUE_LINUX = 'vlan_mapping_linux'
VLAN_QUEUE_OPENSTACK = 'vlan_mapping_openstack'
VM_PLACEMENT_QUEUE_LINUX = 'vm_placement_linux'
VM_PLACEMENT_QUEUE_OPENSTACK = 'vm_placement_openstack'

# ==================== MODELOS ====================

class VlanMappingRequest(BaseModel):
    slice_id: int

class SecurityGroupCreate(BaseModel):
    slice_id: int
    name: str
    description: str = ""

class SecurityGroupRule(BaseModel):
    direction: str  # ingress o egress
    ether_type: str  # IPv4 o IPv6
    protocol: str  # tcp, udp, icmp, any
    port_range: str = "any"  # "22", "80-443", "any"
    remote_ip_prefix: str = None  # "0.0.0.0/0", "192.168.1.0/24"
    remote_security_group: str = None  # "default", nombre de otro SG
    description: str = ""

class SecurityGroupAddRule(BaseModel):
    rule: SecurityGroupRule

class ApplySecurityGroupToWorker(BaseModel):
    slice_id: int
    security_group_id: int
    workers: List[str]  # Lista de IPs de workers donde aplicar

# ==================== FUNCIONES AUXILIARES ====================

def get_used_vlans_from_db(zona_disponibilidad: str) -> List[int]:
    """
    Obtiene todas las VLANs actualmente en uso de la BD para una zona específica
    Lee el campo 'vlans' de todos los slices con tipo='desplegado' o tipo='validado'
    filtrando por zona_disponibilidad
    Formato en BD: "3,4,5,6" -> [3, 4, 5, 6]
    
    Args:
        zona_disponibilidad: 'linux' o 'openstack'
    """
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener todos los slices que tienen VLANs asignadas en la misma zona
        query = """
            SELECT vlans FROM slices 
            WHERE vlans IS NOT NULL 
            AND vlans != ''
            AND tipo IN ('validado', 'desplegado')
            AND zona_disponibilidad = %s
        """
        cursor.execute(query, (zona_disponibilidad,))
        results = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        used_vlans = []
        for row in results:
            vlans_str = row['vlans']
            if vlans_str:
                # Parsear "3,4,5,6" -> [3, 4, 5, 6]
                vlans = [int(v.strip()) for v in vlans_str.split(',') if v.strip()]
                used_vlans.extend(vlans)
        
        return sorted(set(used_vlans))  # Eliminar duplicados y ordenar
        
    except Error as e:
        logger.error(f"Error al obtener VLANs usadas para zona {zona_disponibilidad}: {str(e)}")
        return []

def allocate_vlans(num_vlans_needed: int, used_vlans: List[int], zona_disponibilidad: str) -> List[int]:
    """
    Asigna VLANs disponibles del pool de la zona, reutilizando espacios libres
    
    Args:
        num_vlans_needed: Cantidad de VLANs a asignar
        used_vlans: VLANs ya en uso en esta zona
        zona_disponibilidad: 'linux' (pool 3-900) o 'openstack' (pool 11-900)
    
    Ejemplo zona linux:
    - used_vlans = [3,4,5,6,22,23,24,40]
    - num_vlans_needed = 7
    - Resultado: [7,8,9,10,11,12,13]
    
    Ejemplo zona openstack:
    - used_vlans = [11,12,13,14,30,31]
    - num_vlans_needed = 5
    - Resultado: [15,16,17,18,19]
    """
    if zona_disponibilidad not in VLAN_POOLS:
        raise Exception(f"Zona desconocida: {zona_disponibilidad}. Zonas válidas: {list(VLAN_POOLS.keys())}")
    
    pool = VLAN_POOLS[zona_disponibilidad]
    vlan_min = pool['min']
    vlan_max = pool['max']
    
    used_set = set(used_vlans)
    allocated = []
    
    # Buscar VLANs disponibles en el rango de la zona
    for vlan_id in range(vlan_min, vlan_max + 1):
        if vlan_id not in used_set:
            allocated.append(vlan_id)
            if len(allocated) == num_vlans_needed:
                break
    
    if len(allocated) < num_vlans_needed:
        raise Exception(f"No hay suficientes VLANs disponibles en zona '{zona_disponibilidad}'. Necesarias: {num_vlans_needed}, Disponibles: {len(allocated)}, Pool: {vlan_min}-{vlan_max}")
    
    return allocated

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

def update_vm_vlan_connections(peticion_json: Dict, vlan_mapping: Dict[str, int], zona_disponibilidad: str) -> None:
    """
    Actualiza el campo conexiones_vlans de cada VM con los VLANs correspondientes
    
    Para cada VM, busca en vlan_mapping todos los enlaces que la involucran
    y construye el string en formato: "vlan1,vlan2,vlan3"
    
    Si internet="si", se agrega la VLAN de internet al principio según zona:
    - Linux: VLAN 1
    - OpenStack: VLAN 11
    
    Ejemplo:
    - vlan_mapping = {"vm1-vm2": 8, "vm3-vm4": 9, "vm2-vm5": 12, "vm4-vm1": 13}
    - vm1 participa en: "vm1-vm2" (8) y "vm4-vm1" (13)
    - vm1.internet = "no" -> vm1.conexiones_vlans = "8,13"
    - vm1.internet = "si" (linux) -> vm1.conexiones_vlans = "1,8,13"
    - vm1.internet = "si" (openstack) -> vm1.conexiones_vlans = "11,8,13"
    """
    # Determinar VLAN de internet según zona
    internet_vlan = 1 if zona_disponibilidad == 'linux' else 11
    
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
            
            # Si internet="si", agregar VLAN de internet al principio
            if internet == 'si':
                vlans_list.append(internet_vlan)
                logger.info(f"VM {vm_name}: internet=si, agregando VLAN {internet_vlan} (zona {zona_disponibilidad})")
            
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

# ==================== FUNCIONES RABBITMQ ====================

def get_rabbitmq_connection():
    """Crear conexión a RabbitMQ con reintentos"""
    max_retries = 5
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
            parameters = pika.ConnectionParameters(
                host=RABBITMQ_HOST,
                port=RABBITMQ_PORT,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300
            )
            connection = pika.BlockingConnection(parameters)
            logger.info(f"[NET_SEC] Conexión a RabbitMQ establecida en intento {attempt + 1}")
            return connection
        except Exception as e:
            logger.warning(f"[NET_SEC] Intento {attempt + 1}/{max_retries} falló: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                raise Exception(f"No se pudo conectar a RabbitMQ después de {max_retries} intentos")

def publish_to_queue(queue_name: str, message: dict):
    """Publicar mensaje en una cola específica"""
    try:
        connection = get_rabbitmq_connection()
        channel = connection.channel()
        channel.queue_declare(queue=queue_name, durable=True)
        
        message_json = json.dumps(message)
        channel.basic_publish(
            exchange='',
            routing_key=queue_name,
            body=message_json,
            properties=pika.BasicProperties(
                delivery_mode=2,  # Mensaje persistente
            )
        )
        
        connection.close()
        logger.info(f"[NET_SEC] Mensaje publicado en cola '{queue_name}'")
        return True
    except Exception as e:
        logger.error(f"[NET_SEC] Error al publicar en cola '{queue_name}': {str(e)}")
        raise Exception(f"Error al publicar en RabbitMQ: {str(e)}")

def process_vlan_mapping(slice_id: int, zona_despliegue: str):
    """
    Procesar mapeo de VLANs para un slice
    Retorna True si es exitoso, False si falla
    """
    try:
        # Obtener slice de la BD
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM slices WHERE id = %s", (slice_id,))
        slice_data = cursor.fetchone()
        
        if not slice_data:
            logger.error(f"[NET_SEC] Slice {slice_id} no encontrado")
            cursor.close()
            connection.close()
            return False
        
        # Parsear peticion_json
        peticion_json = json.loads(slice_data['peticion_json']) if isinstance(slice_data['peticion_json'], str) else slice_data['peticion_json']
        
        # Actualizar id_slice en el JSON
        peticion_json['id_slice'] = str(slice_id)
        
        # Calcular enlaces de topologías
        all_links = []
        topology_links_count = 0
        
        for topology in peticion_json['topologias']:
            topo_links = calculate_topology_links(topology)
            all_links.extend(topo_links)
            topology_links_count += len(topo_links)
        
        logger.info(f"[NET_SEC] Slice {slice_id}: {topology_links_count} enlaces de topologías")
        
        # Calcular enlaces de conexiones_vms
        conexiones_vms = peticion_json.get('conexiones_vms', '')
        inter_topo_links = parse_conexiones_vms(conexiones_vms)
        all_links.extend(inter_topo_links)
        
        logger.info(f"[NET_SEC] Slice {slice_id}: {len(inter_topo_links)} enlaces inter-topología")
        logger.info(f"[NET_SEC] Slice {slice_id}: {len(all_links)} enlaces totales")
        
        # Obtener VLANs usadas en esta zona y asignar VLANs disponibles
        used_vlans = get_used_vlans_from_db(zona_despliegue)
        pool = VLAN_POOLS[zona_despliegue]
        logger.info(f"[NET_SEC] Zona '{zona_despliegue}': Pool VLANs {pool['min']}-{pool['max']}, VLANs en uso: {len(used_vlans)}")
        
        allocated_vlans = allocate_vlans(len(all_links), used_vlans, zona_despliegue)
        logger.info(f"[NET_SEC] Slice {slice_id}: VLANs asignadas: {allocated_vlans}")
        
        # Mapear VLANs a enlaces y actualizar JSON
        vlan_mapping = map_vlans_to_links(all_links, allocated_vlans)
        vlans_str = ','.join(map(str, allocated_vlans))
        peticion_json['vlans_usadas'] = vlans_str
        
        # Actualizar conexiones_vlans de cada VM
        update_vm_vlan_connections(peticion_json, vlan_mapping, zona_despliegue)
        
        # Actualizar BD solo con vlans
        update_query = """
            UPDATE slices 
            SET vlans = %s,
                estado = %s
            WHERE id = %s
        """
        cursor.execute(update_query, (
            vlans_str,
            'vlans_mapeadas',
            slice_id
        ))
        connection.commit()
        
        cursor.close()
        connection.close()
        
        logger.info(f"[NET_SEC] Slice {slice_id}: VLANs guardadas en BD")
        
        # ========== CREAR Security Group default en BD ==========
        try:
            logger.info(f"[NET_SEC] Slice {slice_id}: Inicializando Security Groups...")
            result = create_default_security_group(slice_id)
            
            if result:
                logger.info(f"[NET_SEC] Slice {slice_id}: Security Group creado - ID {result.get('id')}")
            else:
                logger.warning(f"[NET_SEC] Slice {slice_id}: Error creando Security Group (no crítico)")
        except Exception as sg_error:
            logger.warning(f"[NET_SEC] Slice {slice_id}: Error creando Security Group (no crítico): {str(sg_error)}")
        
        # ========== LOG: JSON DESPUÉS DE MAPEO DE VLANs ==========
        logger.info(f"\n{'='*100}")
        logger.info(f"[NET_SEC] Slice {slice_id} ('{slice_data['nombre_slice']}'): JSON DESPUÉS DE MAPEO DE VLANs")
        logger.info(f"{'='*100}")
        logger.info(f"[NET_SEC] Zona de despliegue: {zona_despliegue}")
        logger.info(f"[NET_SEC] JSON completo:")
        logger.info(json.dumps(peticion_json, indent=2, ensure_ascii=False))
        logger.info(f"{'='*100}\n")
        
        # Publicar en cola de vm_placement según zona
        vm_queue = VM_PLACEMENT_QUEUE_LINUX if zona_despliegue == 'linux' else VM_PLACEMENT_QUEUE_OPENSTACK
        
        vm_message = {
            "nombre_slice": slice_data['nombre_slice'],
            "zona_despliegue": zona_despliegue,
            "solicitud_json": peticion_json
        }
        
        publish_to_queue(vm_queue, vm_message)
        logger.info(f"[NET_SEC] Slice {slice_id}: Publicado en cola '{vm_queue}' para mapeo de servidores")
        
        return True
        
    except Exception as e:
        logger.error(f"[NET_SEC] Error procesando slice {slice_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def consume_vlan_queue(queue_name: str, zona: str):
    """
    Consumer worker para procesar mensajes de una cola de VLANs
    Se ejecuta en un thread separado
    """
    logger.info(f"[NET_SEC] Iniciando consumer para cola '{queue_name}' (zona: {zona})")
    
    while True:
        try:
            connection = get_rabbitmq_connection()
            channel = connection.channel()
            channel.queue_declare(queue=queue_name, durable=True)
            channel.basic_qos(prefetch_count=1)
            
            def callback(ch, method, properties, body):
                try:
                    message = json.loads(body)
                    slice_id = message.get('slice_id')
                    zona_despliegue = message.get('zona_despliegue')
                    
                    logger.info(f"[NET_SEC] Procesando slice {slice_id} de zona '{zona_despliegue}'")
                    
                    # Procesar mapeo de VLANs
                    success = process_vlan_mapping(slice_id, zona_despliegue)
                    
                    if success:
                        # ACK: mensaje procesado exitosamente
                        ch.basic_ack(delivery_tag=method.delivery_tag)
                        logger.info(f"[NET_SEC] Slice {slice_id} procesado exitosamente")
                    else:
                        # NACK: reencolar mensaje
                        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                        logger.error(f"[NET_SEC] Slice {slice_id} falló, reencolando...")
                        
                except Exception as e:
                    logger.error(f"[NET_SEC] Error en callback: {str(e)}")
                    # NACK sin reencolar para evitar loops infinitos
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            
            channel.basic_consume(queue=queue_name, on_message_callback=callback)
            logger.info(f"[NET_SEC] Consumer '{queue_name}' esperando mensajes...")
            channel.start_consuming()
            
        except Exception as e:
            logger.error(f"[NET_SEC] Error en consumer '{queue_name}': {str(e)}")
            time.sleep(5)  # Esperar antes de reintentar

def start_consumers():
    """Iniciar consumers en threads separados"""
    # Consumer para Linux
    thread_linux = threading.Thread(
        target=consume_vlan_queue,
        args=(VLAN_QUEUE_LINUX, 'linux'),
        daemon=True
    )
    thread_linux.start()
    logger.info("[NET_SEC] Thread consumer Linux iniciado")
    
    # Consumer para OpenStack
    thread_openstack = threading.Thread(
        target=consume_vlan_queue,
        args=(VLAN_QUEUE_OPENSTACK, 'openstack'),
        daemon=True
    )
    thread_openstack.start()
    logger.info("[NET_SEC] Thread consumer OpenStack iniciado")

@app.on_event("startup")
async def startup_event():
    """Inicializar consumers al arrancar"""
    import asyncio
    await asyncio.sleep(3)  # Esperar a que RabbitMQ esté listo
    start_consumers()
    logger.info("[NET_SEC] Consumers RabbitMQ iniciados")

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

# ==================== ENDPOINTS DE SECURITY GROUPS ====================

@app.post("/security-groups/create")
async def create_security_group(request: SecurityGroupCreate):
    """Crear un nuevo Security Group para un slice"""
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Verificar que el slice existe (en la BD de slices)
        slices_conn = mysql.connector.connect(**DB_CONFIG)
        slices_cursor = slices_conn.cursor(dictionary=True)
        slices_cursor.execute("SELECT id FROM slices WHERE id = %s", (request.slice_id,))
        slice_exists = slices_cursor.fetchone()
        slices_cursor.close()
        slices_conn.close()
        
        if not slice_exists:
            cursor.close()
            connection.close()
            raise HTTPException(status_code=404, detail=f"Slice {request.slice_id} no encontrado")
        
        # Crear Security Group vacío
        insert_query = """
            INSERT INTO security_groups (slice_id, name, description, rules)
            VALUES (%s, %s, %s, %s)
        """
        
        cursor.execute(insert_query, (
            request.slice_id,
            request.name,
            request.description,
            '[]'  # Sin reglas inicialmente
        ))
        
        connection.commit()
        sg_id = cursor.lastrowid
        
        cursor.close()
        connection.close()
        
        logger.info(f"✓ Security Group '{request.name}' creado para slice {request.slice_id} (id={sg_id})")
        
        return {
            "success": True,
            "message": f"Security Group '{request.name}' creado exitosamente",
            "security_group_id": sg_id,
            "slice_id": request.slice_id,
            "name": request.name
        }
        
    except mysql.connector.IntegrityError as e:
        if "unique_sg_per_slice" in str(e):
            raise HTTPException(
                status_code=400,
                detail=f"Ya existe un Security Group con nombre '{request.name}' en el slice {request.slice_id}"
            )
        raise HTTPException(status_code=500, detail=str(e))
    except Error as e:
        logger.error(f"Error creando Security Group: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/security-groups/slice/{slice_id}")
async def list_security_groups(slice_id: int):
    """Listar todos los Security Groups de un slice"""
    try:
        sgs = get_security_groups_by_slice(slice_id)
        
        return {
            "success": True,
            "slice_id": slice_id,
            "count": len(sgs),
            "security_groups": sgs
        }
        
    except Exception as e:
        logger.error(f"Error listando Security Groups: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/security-groups/{sg_id}")
async def get_security_group(sg_id: int):
    """Obtener detalles de un Security Group específico"""
    try:
        sg = get_security_group_by_id(sg_id)
        
        if not sg:
            raise HTTPException(status_code=404, detail=f"Security Group {sg_id} no encontrado")
        
        return {
            "success": True,
            "security_group": sg
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo Security Group: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/security-groups/{sg_id}/add-rule")
async def add_security_group_rule(sg_id: int, request: SecurityGroupAddRule):
    """Agregar una regla a un Security Group"""
    try:
        # Verificar que el SG existe
        sg = get_security_group_by_id(sg_id)
        if not sg:
            raise HTTPException(status_code=404, detail=f"Security Group {sg_id} no encontrado")
        
        # Agregar regla
        if not add_rule_to_security_group(sg_id, request.rule):
            raise HTTPException(status_code=500, detail="Error agregando regla")
        
        # Obtener SG actualizado
        updated_sg = get_security_group_by_id(sg_id)
        
        return {
            "success": True,
            "message": "Regla agregada exitosamente",
            "security_group": updated_sg
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error agregando regla: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/security-groups/{sg_id}/rule/{rule_id}")
async def delete_security_group_rule(sg_id: int, rule_id: int):
    """Eliminar una regla de un Security Group"""
    try:
        # Verificar que el SG existe
        sg = get_security_group_by_id(sg_id)
        if not sg:
            raise HTTPException(status_code=404, detail=f"Security Group {sg_id} no encontrado")
        
        # Eliminar regla
        if not delete_rule_from_security_group(sg_id, rule_id):
            raise HTTPException(status_code=500, detail="Error eliminando regla")
        
        # Obtener SG actualizado
        updated_sg = get_security_group_by_id(sg_id)
        
        return {
            "success": True,
            "message": f"Regla {rule_id} eliminada exitosamente",
            "security_group": updated_sg
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error eliminando regla: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/security-groups/{sg_id}")
async def delete_security_group(sg_id: int):
    """Eliminar un Security Group completo"""
    try:
        # Verificar que el SG existe
        sg = get_security_group_by_id(sg_id)
        if not sg:
            raise HTTPException(status_code=404, detail=f"Security Group {sg_id} no encontrado")
        
        # No permitir eliminar el SG "default"
        if sg['name'] == 'default':
            raise HTTPException(
                status_code=400,
                detail="No se puede eliminar el Security Group 'default'"
            )
        
        # Eliminar de BD
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor()
        
        cursor.execute("DELETE FROM security_groups WHERE id = %s", (sg_id,))
        connection.commit()
        
        cursor.close()
        connection.close()
        
        logger.info(f"✓ Security Group {sg_id} eliminado")
        
        return {
            "success": True,
            "message": f"Security Group '{sg['name']}' eliminado exitosamente"
        }
        
    except HTTPException:
        raise
    except Error as e:
        logger.error(f"Error eliminando Security Group: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/security-groups/{sg_id}/apply")
async def apply_security_group_to_workers(sg_id: int, request: ApplySecurityGroupToWorker):
    """
    Aplicar un Security Group en los workers especificados
    Llama al vm_node_manager de cada worker para configurar iptables
    """
    try:
        import requests
        
        # Obtener Security Group de BD
        sg = get_security_group_by_id(sg_id)
        if not sg:
            raise HTTPException(status_code=404, detail=f"Security Group {sg_id} no encontrado")
        
        # Verificar que pertenece al slice correcto
        if sg['slice_id'] != request.slice_id:
            raise HTTPException(
                status_code=400,
                detail=f"Security Group {sg_id} no pertenece al slice {request.slice_id}"
            )
        
        # Convertir reglas de BD al formato que espera vm_node_manager
        rules_for_worker = []
        for rule in sg['rules']:
            worker_rule = {
                "template": "CUSTOM_TCP" if rule['protocol'] == 'tcp' else 
                           "CUSTOM_UDP" if rule['protocol'] == 'udp' else
                           "CUSTOM_ICMP" if rule['protocol'] == 'icmp' else "SSH",
                "direction": rule['direction'],
                "remote_cidr": rule.get('remote_ip_prefix', '0.0.0.0/0'),
                "description": rule.get('description', '')
            }
            
            # Agregar puerto si es TCP/UDP
            if rule['protocol'] in ['tcp', 'udp']:
                port_range = rule.get('port_range', 'any')
                if port_range != 'any':
                    if '-' in port_range:
                        worker_rule['port_range'] = port_range
                    else:
                        worker_rule['port'] = int(port_range)
            
            # Agregar tipo ICMP si es ICMP
            if rule['protocol'] == 'icmp':
                worker_rule['icmp_type'] = rule.get('icmp_type')
                worker_rule['icmp_code'] = rule.get('icmp_code')
            
            rules_for_worker.append(worker_rule)
        
        # Aplicar en cada worker
        results = []
        for worker_ip in request.workers:
            try:
                url = f"http://{worker_ip}:5805/security-group/apply"
                payload = {
                    "id": request.slice_id,
                    "rules": rules_for_worker
                }
                headers = {"Authorization": "Bearer clavesihna"}
                
                response = requests.post(url, json=payload, headers=headers, timeout=10)
                
                if response.status_code == 200:
                    results.append({
                        "worker": worker_ip,
                        "success": True,
                        "message": response.json().get('message', 'Aplicado')
                    })
                    logger.info(f"✓ Security Group aplicado en worker {worker_ip}")
                else:
                    results.append({
                        "worker": worker_ip,
                        "success": False,
                        "message": f"HTTP {response.status_code}: {response.text}"
                    })
                    logger.error(f"✗ Error aplicando SG en worker {worker_ip}: {response.text}")
                    
            except Exception as e:
                results.append({
                    "worker": worker_ip,
                    "success": False,
                    "message": str(e)
                })
                logger.error(f"✗ Error conectando a worker {worker_ip}: {str(e)}")
        
        success_count = sum(1 for r in results if r['success'])
        
        return {
            "success": success_count > 0,
            "message": f"Security Group aplicado en {success_count}/{len(request.workers)} workers",
            "security_group_id": sg_id,
            "security_group_name": sg['name'],
            "slice_id": request.slice_id,
            "results": results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error aplicando Security Group: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/security-groups/initialize/{slice_id}")
async def initialize_default_security_group(slice_id: int):
    """
    Crear Security Group 'default' para un slice nuevo
    Llamado automáticamente cuando se crea un slice
    """
    try:
        result = create_default_security_group(slice_id)
        
        if not result:
            raise HTTPException(status_code=500, detail="Error creando Security Group default")
        
        return {
            "success": True,
            "message": f"Security Group 'default' inicializado para slice {slice_id}",
            "security_group": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error inicializando Security Group: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== ENDPOINTS DE VLANS ====================

@app.post("/map-vlans")
async def map_vlans(request: VlanMappingRequest):
    """
    Mapea VLANs para un slice validado
    
    Proceso:
    1. Obtener slice de la BD
    2. Actualizar id_slice en el JSON (no se guarda en BD aún)
    3. Calcular enlaces de topologías
    4. Calcular enlaces de conexiones_vms
    5. Obtener VLANs usadas y asignar VLANs disponibles
    6. Mapear VLANs a enlaces y actualizar JSON
    7. Actualizar BD solo con vlans (NO peticion_json)
    8. Retornar JSON mapeado y resumen
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
        
        # Obtener zona_disponibilidad
        zona_disponibilidad = slice_data.get('zona_disponibilidad')
        if not zona_disponibilidad:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Slice no tiene zona_disponibilidad definida"
            )
        
        if zona_disponibilidad not in ['linux', 'openstack']:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"zona_disponibilidad inválida: {zona_disponibilidad}. Debe ser 'linux' o 'openstack'"
            )
        
        logger.info(f"Slice {request.slice_id}: Zona de disponibilidad = {zona_disponibilidad}")
        
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
        
        # 5. Obtener VLANs usadas en esta zona y asignar VLANs disponibles del pool correspondiente
        used_vlans = get_used_vlans_from_db(zona_disponibilidad)
        pool = VLAN_POOLS[zona_disponibilidad]
        logger.info(f"Zona '{zona_disponibilidad}': Pool VLANs {pool['min']}-{pool['max']}, VLANs en uso: {len(used_vlans)}")
        
        allocated_vlans = allocate_vlans(len(all_links), used_vlans, zona_disponibilidad)
        logger.info(f"Slice {request.slice_id}: VLANs asignadas: {allocated_vlans}")
        
        # 6. Mapear VLANs a enlaces y actualizar JSON
        vlan_mapping = map_vlans_to_links(all_links, allocated_vlans)
        vlans_str = ','.join(map(str, allocated_vlans))
        peticion_json['vlans_usadas'] = vlans_str
        
        # Actualizar conexiones_vlans de cada VM
        update_vm_vlan_connections(peticion_json, vlan_mapping, zona_disponibilidad)
        
        # Actualizar BD solo con vlans (NO peticion_json aún)
        update_query = """
            UPDATE slices 
            SET vlans = %s
            WHERE id = %s
        """
        cursor.execute(update_query, (
            vlans_str,
            request.slice_id
        ))
        connection.commit()
        
        cursor.close()
        connection.close()
        
        logger.info(f"Slice {request.slice_id}: VLANs guardadas en BD")
        
        # Retornar JSON mapeado y resumen
        return {
            "success": True,
            "slice_id": request.slice_id,
            "zona_disponibilidad": zona_disponibilidad,
            "vlan_pool": f"{VLAN_POOLS[zona_disponibilidad]['min']}-{VLAN_POOLS[zona_disponibilidad]['max']}",
            "total_links": len(all_links),
            "topology_links": topology_links_count,
            "inter_topology_links": len(inter_topo_links),
            "vlans_allocated": allocated_vlans,
            "vlans_string": vlans_str,
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

# ==================== FUNCIONES DE SECURITY GROUPS ====================

def create_default_security_group(slice_id: int) -> Dict:
    """
    Crea el Security Group 'default' para un slice nuevo
    Copia las reglas del template (slice_id = 0)
    """
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener template default
        cursor.execute("SELECT rules FROM security_groups WHERE slice_id = 0 AND name = 'default'")
        template = cursor.fetchone()
        
        if not template:
            logger.error("No existe template de Security Group default")
            cursor.close()
            connection.close()
            return None
        
        # Crear SG default para el slice con is_default=TRUE
        insert_query = """
            INSERT INTO security_groups (slice_id, name, description, rules, is_default)
            VALUES (%s, %s, %s, %s, TRUE)
            ON DUPLICATE KEY UPDATE
                rules = VALUES(rules),
                is_default = TRUE,
                updated_at = CURRENT_TIMESTAMP
        """
        
        cursor.execute(insert_query, (
            slice_id,
            'default',
            f'Security group por defecto del slice {slice_id}',
            template['rules']
        ))
        
        connection.commit()
        sg_id = cursor.lastrowid
        
        cursor.close()
        connection.close()
        
        logger.info(f"✓ Security Group 'default' creado para slice {slice_id} (id={sg_id})")
        return {'id': sg_id, 'name': 'default', 'slice_id': slice_id}
        
    except Error as e:
        logger.error(f"Error creando Security Group default: {str(e)}")
        return None

def get_security_groups_by_slice(slice_id: int) -> List[Dict]:
    """Obtiene todos los Security Groups de un slice"""
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute(
            "SELECT id, slice_id, name, description, rules, created_at, updated_at FROM security_groups WHERE slice_id = %s",
            (slice_id,)
        )
        results = cursor.fetchall()
        
        # Parsear JSON de rules
        for row in results:
            if row['rules']:
                row['rules'] = json.loads(row['rules'])
        
        cursor.close()
        connection.close()
        
        return results
        
    except Error as e:
        logger.error(f"Error obteniendo Security Groups: {str(e)}")
        return []

def get_security_group_by_id(sg_id: int) -> Dict:
    """Obtiene un Security Group por ID"""
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        cursor.execute(
            "SELECT id, slice_id, name, description, rules, created_at, updated_at FROM security_groups WHERE id = %s",
            (sg_id,)
        )
        result = cursor.fetchone()
        
        if result and result['rules']:
            result['rules'] = json.loads(result['rules'])
        
        cursor.close()
        connection.close()
        
        return result
        
    except Error as e:
        logger.error(f"Error obteniendo Security Group: {str(e)}")
        return None

def add_rule_to_security_group(sg_id: int, rule: SecurityGroupRule) -> bool:
    """Agrega una regla a un Security Group"""
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener reglas actuales
        cursor.execute("SELECT rules FROM security_groups WHERE id = %s", (sg_id,))
        result = cursor.fetchone()
        
        if not result:
            cursor.close()
            connection.close()
            return False
        
        rules = json.loads(result['rules']) if result['rules'] else []
        
        # Generar nuevo ID para la regla
        max_id = max([r.get('id', 0) for r in rules], default=0)
        new_rule = rule.dict()
        new_rule['id'] = max_id + 1
        
        rules.append(new_rule)
        
        # Actualizar en BD
        cursor.execute(
            "UPDATE security_groups SET rules = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (json.dumps(rules), sg_id)
        )
        
        connection.commit()
        cursor.close()
        connection.close()
        
        logger.info(f"✓ Regla agregada al Security Group {sg_id}")
        return True
        
    except Error as e:
        logger.error(f"Error agregando regla: {str(e)}")
        return False

def delete_rule_from_security_group(sg_id: int, rule_id: int) -> bool:
    """Elimina una regla de un Security Group"""
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener reglas actuales
        cursor.execute("SELECT rules FROM security_groups WHERE id = %s", (sg_id,))
        result = cursor.fetchone()
        
        if not result:
            cursor.close()
            connection.close()
            return False
        
        rules = json.loads(result['rules']) if result['rules'] else []
        
        # Filtrar la regla a eliminar
        rules = [r for r in rules if r.get('id') != rule_id]
        
        # Actualizar en BD
        cursor.execute(
            "UPDATE security_groups SET rules = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (json.dumps(rules), sg_id)
        )
        
        connection.commit()
        cursor.close()
        connection.close()
        
        logger.info(f"✓ Regla {rule_id} eliminada del Security Group {sg_id}")
        return True
        
    except Error as e:
        logger.error(f"Error eliminando regla: {str(e)}")
        return False

def delete_security_group_by_id(sg_id: int) -> bool:
    """Elimina un Security Group por completo"""
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Verificar que no sea el SG default del slice (is_default=TRUE)
        cursor.execute("SELECT is_default, name, slice_id FROM security_groups WHERE id = %s", (sg_id,))
        sg = cursor.fetchone()
        
        if not sg:
            cursor.close()
            connection.close()
            logger.warning(f"Security Group {sg_id} no encontrado")
            return False
        
        if sg['is_default']:
            cursor.close()
            connection.close()
            logger.error(f"No se puede eliminar el Security Group default (id={sg_id})")
            return False
        
        # Eliminar el Security Group
        cursor.execute("DELETE FROM security_groups WHERE id = %s", (sg_id,))
        connection.commit()
        
        cursor.close()
        connection.close()
        
        logger.info(f"✓ Security Group '{sg['name']}' (id={sg_id}) eliminado del slice {sg['slice_id']}")
        return True
        
    except Error as e:
        logger.error(f"Error eliminando Security Group: {str(e)}")
        return False

def create_custom_security_group(slice_id: int, name: str, description: str = "") -> Dict:
    """Crea un Security Group personalizado (no default)"""
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Crear SG personalizado con is_default=FALSE
        insert_query = """
            INSERT INTO security_groups (slice_id, name, description, rules, is_default)
            VALUES (%s, %s, %s, %s, FALSE)
        """
        
        # Iniciar con reglas básicas de EGRESS (permitir todo saliente)
        initial_rules = [
            {
                "id": 1,
                "direction": "egress",
                "ether_type": "IPv4",
                "protocol": "any",
                "port_range": "any",
                "remote_ip_prefix": "0.0.0.0/0",
                "remote_security_group": None,
                "description": "Permitir todo tráfico saliente IPv4"
            },
            {
                "id": 2,
                "direction": "egress",
                "ether_type": "IPv6",
                "protocol": "any",
                "port_range": "any",
                "remote_ip_prefix": "::/0",
                "remote_security_group": None,
                "description": "Permitir todo tráfico saliente IPv6"
            }
        ]
        
        cursor.execute(insert_query, (
            slice_id,
            name,
            description or f'Security group personalizado {name} del slice {slice_id}',
            json.dumps(initial_rules)
        ))
        
        connection.commit()
        sg_id = cursor.lastrowid
        
        cursor.close()
        connection.close()
        
        logger.info(f"✓ Security Group personalizado '{name}' creado para slice {slice_id} (id={sg_id})")
        return {'id': sg_id, 'name': name, 'slice_id': slice_id, 'is_default': False}
        
    except mysql.connector.IntegrityError as e:
        if "unique_sg_per_slice" in str(e):
            logger.error(f"Ya existe un Security Group con nombre '{name}' en el slice {slice_id}")
            return None
        logger.error(f"Error de integridad: {str(e)}")
        return None
    except Error as e:
        logger.error(f"Error creando Security Group personalizado: {str(e)}")
        return None

# ==================== ENDPOINTS ====================
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=6300, workers=2)

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Dict, Any, Optional
import httpx
import os
import logging
import json
from datetime import datetime
import mysql.connector
from mysql.connector import Error

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Drivers API",
    version="1.0.0",
    description="Bypass para redirigir despliegues a orquestadores Linux/OpenStack"
)

# Configuración
SERVICE_TOKEN = os.getenv('SERVICE_TOKEN', 'clavesihna')

# Orquestadores configurados
ORCHESTRATORS = {
    'linux': {
        'host': '192.168.203.1',
        'port': 5805,
        'base_url': 'http://192.168.203.1:5805'
    },
    'openstack': {
        'host': '192.168.204.1',
        'port': 5805,
        'base_url': 'http://192.168.204.1:5805'
    }
}

# Security Groups API (headnode Linux)
SECURITY_API_LINUX = {
    'host': '192.168.203.1',
    'port': 5811,
    'base_url': 'http://192.168.203.1:5811'
}

# Security Groups API (headnode OpenStack)
SECURITY_API_OPENSTACK = {
    'host': '192.168.204.1',
    'port': 5811,
    'base_url': 'http://192.168.204.1:5811'
}

# Configuración de BD de slices
SLICES_DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'slices_db'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'database': os.getenv('DB_NAME', 'slices_db'),
    'user': os.getenv('DB_USER', 'slices_user'),
    'password': os.getenv('DB_PASSWORD', 'slices_pass123')
}

# Configuración de BD de Security Groups
SG_DB_CONFIG = {
    'host': os.getenv('SG_DB_HOST', 'security_groups_db'),
    'port': int(os.getenv('SG_DB_PORT', 3306)),
    'database': os.getenv('SG_DB_NAME', 'security_groups_db'),
    'user': os.getenv('SG_DB_USER', 'secgroups_user'),
    'password': os.getenv('SG_DB_PASSWORD', 'secgroups_pass123')
}

security = HTTPBearer()

# Modelos
class DeploySliceRequest(BaseModel):
    """Modelo para solicitud de despliegue de slice"""
    json_config: Dict[Any, Any]

class DeploySliceResponse(BaseModel):
    """Respuesta de despliegue de slice"""
    success: bool
    message: str
    zone: str
    slice_id: Optional[int] = None
    vnc_mapping: Optional[Dict[str, int]] = None  # {vm_name: vnc_port} - Linux
    project_id: Optional[str] = None  # OpenStack project ID
    default_sg_rules: Optional[list] = None  # OpenStack default SG rules
    deployment_details: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class DeleteSliceRequest(BaseModel):
    """Modelo para solicitud de eliminación de slice"""
    slice_id: int
    zona_despliegue: str

class DeleteSliceResponse(BaseModel):
    """Respuesta de eliminación de slice"""
    success: bool
    message: str
    zone: str
    slice_id: int
    deletion_details: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class SliceOperationRequest(BaseModel):
    """Modelo para operaciones sobre slice completo"""
    slice_id: int
    zona_despliegue: str

class VMOperationRequest(BaseModel):
    """Modelo para operaciones sobre VM individual"""
    slice_id: int
    vm_name: str
    zona_despliegue: str

class OperationResponse(BaseModel):
    """Respuesta genérica de operaciones"""
    success: bool
    message: str
    zone: str
    slice_id: int
    vm_name: Optional[str] = None
    workers_results: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class CreateCustomSGRequest(BaseModel):
    """Crear security group personalizado"""
    slice_id: int
    nombre: str  # Nombre del SG para la UI (ej: "Web Server")
    descripcion: str  # Descripción del SG para la UI
    zona_despliegue: str

class AddRuleRequest(BaseModel):
    """Agregar regla a security group"""
    slice_id: int
    zona_despliegue: str
    id_sg: Optional[int] = None  # None = default SG
    sg_name: Optional[str] = None
    rule_id: Optional[int] = None  # Si no se provee, se calcula automáticamente desde BD
    plantilla: Optional[str] = None  # SSH, HTTP, HTTPS, DNS, etc.
    direction: str  # INPUT/OUTPUT
    protocol: str = "any"
    port_range: str = "any"
    remote_ip_prefix: Optional[str] = None
    ether_type: Optional[str] = "IPv4"  # IPv4 o IPv6
    icmp_type: Optional[str] = None
    icmp_code: Optional[str] = None
    description: str = ""
    workers: Optional[str] = None  # Si no se provee, se obtiene automáticamente de BD

class RemoveRuleRequest(BaseModel):
    """Eliminar regla de security group"""
    slice_id: int
    zona_despliegue: str
    id_sg: Optional[int] = None
    sg_name: Optional[str] = None
    rule_id: int
    direction: Optional[str] = None  # Se obtiene automáticamente de BD si no se provee
    workers: Optional[str] = None  # Si no se provee, se obtiene automáticamente de BD

class RemoveCustomSGRequest(BaseModel):
    """Eliminar security group personalizado"""
    slice_id: int
    zona_despliegue: str
    id_sg: int
    workers: Optional[str] = None  # Si no se provee, se obtiene automáticamente de BD

class RemoveDefaultSGRequest(BaseModel):
    """Eliminar security group default"""
    slice_id: int
    zona_despliegue: str
    workers: Optional[str] = None  # Si no se provee, se obtiene automáticamente de BD

class SecurityGroupResponse(BaseModel):
    """Respuesta de operaciones de security groups"""
    success: bool
    message: str
    zone: str
    slice_id: int
    id_sg: Optional[int] = None
    sg_id: Optional[str] = None  # ID de OpenStack (UUID)
    error: Optional[str] = None

class SecurityGroupStatusRequest(BaseModel):
    """Petición para consultar estado de security groups"""
    slice_id: int
    zona_despliegue: str
    workers: Optional[str] = None  # Si no se provee, se obtiene automáticamente de BD

class SecurityGroupStatusResponse(BaseModel):
    """Respuesta de consulta de estado de security groups"""
    success: bool
    message: str
    zone: str
    slice_id: int
    security_groups: Optional[list] = None
    project_id: Optional[str] = None
    workers_status: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

# Autenticación
def get_service_auth(credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
    """Verificar token de servicio"""
    if credentials.credentials != SERVICE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de servicio inválido"
        )
    return True

# Funciones de BD
def get_workers_from_slice(slice_id: int) -> str:
    """
    Obtener workers de un slice desde la BD
    
    Args:
        slice_id: ID del slice
    
    Returns:
        String con workers separados por ';' (ej: 'worker2;worker3')
    
    Raises:
        HTTPException: Si no se encuentra el slice o no tiene VMs desplegadas
    """
    connection = None
    cursor = None
    
    try:
        connection = mysql.connector.connect(**SLICES_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        query = "SELECT vms FROM slices WHERE id = %s"
        cursor.execute(query, (slice_id,))
        result = cursor.fetchone()
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Slice {slice_id} no encontrado en BD"
            )
        
        vms_json = result.get('vms')
        if not vms_json:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Slice {slice_id} no tiene VMs desplegadas aún"
            )
        
        # Parsear JSON de VMs
        vms = json.loads(vms_json)
        
        if not isinstance(vms, list) or len(vms) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Slice {slice_id} no tiene VMs válidas"
            )
        
        # Extraer servers únicos
        servers = set()
        for vm in vms:
            server = vm.get('server')
            if server:
                servers.add(server)
        
        if not servers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se encontraron workers asignados al slice {slice_id}"
            )
        
        # Convertir a formato 'worker1;worker2;worker3'
        workers_str = ';'.join(sorted(servers))
        logger.info(f"Workers obtenidos del slice {slice_id}: {workers_str}")
        
        return workers_str
        
    except HTTPException:
        raise
    except Error as e:
        logger.error(f"Error de BD al obtener workers del slice {slice_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error consultando BD: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error al obtener workers del slice {slice_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

# Funciones de BD - Security Groups
def create_sg_in_db(slice_id: int, description: str = "") -> int:
    """
    Crear Security Group en BD y obtener su ID auto-generado
    
    Args:
        slice_id: ID del slice
        description: Descripción del SG
    
    Returns:
        ID del SG generado por AUTO_INCREMENT
    """
    connection = None
    cursor = None
    
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor()
        
        # Reglas por defecto (sync con cluster Linux)
        default_rules = [
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
                "direction": "ingress",
                "ether_type": "IPv4",
                "protocol": "any",
                "port_range": "any",
                "remote_ip_prefix": None,
                "remote_security_group": "default",
                "description": "Permitir desde mismo grupo IPv4"
            }
        ]
        
        rules_json = json.dumps(default_rules)
        
        # Insertar sin especificar 'name' aún (lo actualizaremos después con el ID)
        query = """
        INSERT INTO security_groups (slice_id, name, description, rules, is_default)
        VALUES (%s, %s, %s, %s, %s)
        """
        
        # Nombre temporal, lo actualizaremos con el ID real
        cursor.execute(query, (slice_id, 'temp', description, rules_json, False))
        connection.commit()
        
        # Obtener ID generado
        sg_id = cursor.lastrowid
        
        # Actualizar nombre con el ID real: SG_5, SG_10, etc.
        sg_name = f"SG_{sg_id}"
        update_query = "UPDATE security_groups SET name = %s WHERE id = %s"
        cursor.execute(update_query, (sg_name, sg_id))
        connection.commit()
        
        logger.info(f"SG '{sg_name}' (ID {sg_id}) creado en BD para slice {slice_id}")
        
        return sg_id
        
    except Error as e:
        logger.error(f"Error creando SG en BD: {str(e)}")
        if connection:
            connection.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en BD Security Groups: {str(e)}"
        )
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def get_next_rule_id(slice_id: int, sg_name: str) -> int:
    """
    Calcular el siguiente rule_id disponible para un SG
    
    Args:
        slice_id: ID del slice
        sg_name: Nombre del SG (ej: 'SG_5', 'default')
    
    Returns:
        Siguiente ID disponible (max + 1)
    """
    connection = None
    cursor = None
    
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        query = "SELECT rules FROM security_groups WHERE slice_id = %s AND name = %s"
        cursor.execute(query, (slice_id, sg_name))
        result = cursor.fetchone()
        
        if not result:
            # SG no existe, retornar 1
            return 1
        
        rules = json.loads(result['rules']) if result['rules'] else []
        
        if not rules:
            return 1
        
        # Obtener el ID más alto
        max_id = max([rule['id'] for rule in rules])
        return max_id + 1
        
    except Exception as e:
        logger.error(f"Error obteniendo next_rule_id: {str(e)}")
        return 1  # Fallback
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def add_rule_to_db(slice_id: int, sg_name: str, rule: Dict[str, Any]):
    """
    Agregar regla a un SG en BD
    
    Args:
        slice_id: ID del slice
        sg_name: Nombre del SG
        rule: Dict con datos de la regla
    """
    connection = None
    cursor = None
    
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        query = "SELECT rules FROM security_groups WHERE slice_id = %s AND name = %s"
        cursor.execute(query, (slice_id, sg_name))
        result = cursor.fetchone()
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Security Group '{sg_name}' no encontrado para slice {slice_id}"
            )
        
        rules = json.loads(result['rules']) if result['rules'] else []
        rules.append(rule)
        rules_json = json.dumps(rules)
        
        update_query = "UPDATE security_groups SET rules = %s WHERE slice_id = %s AND name = %s"
        cursor.execute(update_query, (rules_json, slice_id, sg_name))
        connection.commit()
        
        logger.info(f"Regla {rule['id']} agregada a SG '{sg_name}' en BD")
        
    except HTTPException:
        raise
    except Error as e:
        logger.error(f"Error agregando regla en BD: {str(e)}")
        if connection:
            connection.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en BD: {str(e)}"
        )
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def delete_sg_from_db(slice_id: int, sg_id: int):
    """
    Eliminar Security Group de BD
    
    Args:
        slice_id: ID del slice
        sg_id: ID del SG (de la tabla)
    """
    connection = None
    cursor = None
    
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor()
        
        # Obtener nombre del SG antes de eliminar
        query_name = "SELECT name FROM security_groups WHERE slice_id = %s AND id = %s"
        cursor.execute(query_name, (slice_id, sg_id))
        result = cursor.fetchone()
        sg_name = result[0] if result else f"SG_{sg_id}"
        
        query = "DELETE FROM security_groups WHERE slice_id = %s AND id = %s"
        cursor.execute(query, (slice_id, sg_id))
        connection.commit()
        
        logger.info(f"SG '{sg_name}' (ID {sg_id}) eliminado de BD para slice {slice_id}")
        
        return sg_name
        
    except Error as e:
        logger.error(f"Error eliminando SG de BD: {str(e)}")
        if connection:
            connection.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en BD: {str(e)}"
        )
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def get_rule_direction_from_db(slice_id: int, sg_name: str, rule_id: int) -> Optional[str]:
    """
    Obtener el campo direction de una regla específica desde la BD
    
    Args:
        slice_id: ID del slice
        sg_name: Nombre del SG (ej: 'default', 'SG_5')
        rule_id: ID de la regla
        
    Returns:
        direction de la regla ('INPUT' o 'OUTPUT') o None si no se encuentra
    """
    connection = None
    cursor = None
    
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        query = "SELECT rules FROM security_groups WHERE slice_id = %s AND name = %s"
        cursor.execute(query, (slice_id, sg_name))
        result = cursor.fetchone()
        
        if not result:
            logger.warning(f"SG '{sg_name}' no encontrado en BD (slice {slice_id})")
            return None
        
        rules = json.loads(result['rules']) if result['rules'] else []
        
        # Buscar la regla específica
        for rule in rules:
            if rule['id'] == rule_id:
                return rule.get('direction', 'INPUT')
        
        logger.warning(f"Regla {rule_id} no encontrada en SG '{sg_name}'")
        return None
        
    except Exception as e:
        logger.error(f"Error obteniendo direction de BD: {str(e)}")
        return None
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def remove_rule_from_db(slice_id: int, sg_name: str, rule_id: int):
    """
    Eliminar una regla del JSON de reglas de un SG en BD
    
    Args:
        slice_id: ID del slice
        sg_name: Nombre del SG (ej: 'default', 'SG_5')
        rule_id: ID de la regla a eliminar
    """
    connection = None
    cursor = None
    
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener reglas actuales
        query = "SELECT rules FROM security_groups WHERE slice_id = %s AND name = %s"
        cursor.execute(query, (slice_id, sg_name))
        result = cursor.fetchone()
        
        if not result:
            logger.warning(f"SG '{sg_name}' no encontrado en BD (slice {slice_id})")
            return None
        
        rules = json.loads(result['rules']) if result['rules'] else []
        
        # Buscar la regla a eliminar para obtener su direction
        rule_to_remove = None
        for r in rules:
            if r['id'] == rule_id:
                rule_to_remove = r
                break
        
        if not rule_to_remove:
            logger.warning(f"Regla {rule_id} no encontrada en SG '{sg_name}'")
            return None
        
        # Obtener direction de la regla
        direction = rule_to_remove.get('direction', 'INPUT')
        
        # Filtrar la regla a eliminar
        rules_filtered = [r for r in rules if r['id'] != rule_id]
        
        # Actualizar JSON de reglas
        rules_json = json.dumps(rules_filtered)
        update_query = "UPDATE security_groups SET rules = %s WHERE slice_id = %s AND name = %s"
        cursor.execute(update_query, (rules_json, slice_id, sg_name))
        connection.commit()
        
        logger.info(f"Regla {rule_id} (direction={direction}) eliminada de SG '{sg_name}' en BD")
        return direction
        
    except Exception as e:
        logger.error(f"Error eliminando regla de BD: {str(e)}")
        if connection:
            connection.rollback()
        return None
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def delete_default_sg_from_db(slice_id: int):
    """
    Eliminar el SG default de un slice de la BD
    
    Args:
        slice_id: ID del slice
    """
    connection = None
    cursor = None
    
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor()
        
        query = "DELETE FROM security_groups WHERE slice_id = %s AND is_default = TRUE"
        cursor.execute(query, (slice_id,))
        connection.commit()
        
        logger.info(f"SG default eliminado de BD (slice {slice_id})")
        
    except Exception as e:
        logger.error(f"Error eliminando SG default de BD: {str(e)}")
        if connection:
            connection.rollback()
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def update_custom_sg_default_rules(id_sg: int, default_rules: list):
    """
    Actualizar las reglas por defecto de un SG custom con los UUIDs de OpenStack
    
    Args:
        id_sg: ID del security group en BD
        default_rules: Lista de strings "id:N;uuid:..." del orquestador OpenStack
    """
    connection = None
    cursor = None
    
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener el SG
        query = "SELECT id, rules FROM security_groups WHERE id = %s"
        cursor.execute(query, (id_sg,))
        result = cursor.fetchone()
        
        if not result:
            logger.warning(f"SG con ID {id_sg} no encontrado")
            return
        
        # Parsear default_rules y crear mapeo id -> uuid
        uuid_mapping = {}
        for rule_str in default_rules:
            parts = rule_str.split(';')
            rule_id = None
            uuid = None
            for part in parts:
                if part.startswith('id:'):
                    rule_id = int(part.split(':')[1])
                elif part.startswith('uuid:'):
                    uuid = part.split(':', 1)[1]
            if rule_id and uuid:
                uuid_mapping[rule_id] = uuid
        
        # Crear las 2 reglas egress por defecto
        default_egress_rules = [
            {
                "id": 1,
                "direction": "egress",
                "ether_type": "IPv4",
                "protocol": "any",
                "port_range": "any",
                "remote_ip_prefix": "0.0.0.0/0",
                "remote_security_group": None,
                "description": "Permitir todo tráfico saliente IPv4",
                "id_openstack": uuid_mapping.get(1)
            },
            {
                "id": 2,
                "direction": "egress",
                "ether_type": "IPv6",
                "protocol": "any",
                "port_range": "any",
                "remote_ip_prefix": "::/0",
                "remote_security_group": None,
                "description": "Permitir todo tráfico saliente IPv6",
                "id_openstack": uuid_mapping.get(2)
            }
        ]
        
        # Guardar reglas
        rules_json = json.dumps(default_egress_rules)
        update_query = "UPDATE security_groups SET rules = %s WHERE id = %s"
        cursor.execute(update_query, (rules_json, result['id']))
        connection.commit()
        
        logger.info(f"Reglas por defecto actualizadas en SG con ID {id_sg}")
        
    except Exception as e:
        logger.error(f"Error actualizando reglas por defecto: {str(e)}")
        if connection:
            connection.rollback()
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def update_default_sg_rules_with_uuids(slice_id: int, default_sg_rules: list):
    """
    Actualizar las reglas del SG default con los UUIDs de OpenStack
    
    Args:
        slice_id: ID del slice
        default_sg_rules: Lista de strings "id:N;uuid:..." del orquestador OpenStack
    """
    connection = None
    cursor = None
    
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener el SG default del slice
        query = "SELECT id, rules FROM security_groups WHERE slice_id = %s AND is_default = TRUE"
        cursor.execute(query, (slice_id,))
        result = cursor.fetchone()
        
        if not result:
            logger.warning(f"SG default no encontrado para slice {slice_id}")
            return
        
        rules = json.loads(result['rules']) if result['rules'] else []
        
        # Parsear default_sg_rules y crear mapeo id -> uuid
        uuid_mapping = {}
        for rule_str in default_sg_rules:
            # Formato: "id:1;uuid:abc-123-..."
            parts = rule_str.split(';')
            rule_id = None
            uuid = None
            for part in parts:
                if part.startswith('id:'):
                    rule_id = int(part.split(':')[1])
                elif part.startswith('uuid:'):
                    uuid = part.split(':', 1)[1]
            if rule_id and uuid:
                uuid_mapping[rule_id] = uuid
        
        # Actualizar cada regla con su UUID
        for rule in rules:
            rule_id = rule.get('id')
            if rule_id in uuid_mapping:
                rule['id_openstack'] = uuid_mapping[rule_id]
        
        # Guardar reglas actualizadas
        rules_json = json.dumps(rules)
        update_query = "UPDATE security_groups SET rules = %s WHERE id = %s"
        cursor.execute(update_query, (rules_json, result['id']))
        connection.commit()
        
        logger.info(f"UUIDs de OpenStack actualizados en SG default del slice {slice_id} ({len(uuid_mapping)} reglas)")
        
    except Exception as e:
        logger.error(f"Error actualizando UUIDs de OpenStack: {str(e)}")
        if connection:
            connection.rollback()
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def get_openstack_rule_uuid(slice_id: int, sg_name: str, rule_id: int) -> Optional[str]:
    """
    Obtener el UUID de OpenStack de una regla a partir del ID secuencial
    
    Args:
        slice_id: ID del slice
        sg_name: Nombre del SG (None = default)
        rule_id: ID secuencial de la regla
        
    Returns:
        UUID de OpenStack o None si no se encuentra
    """
    connection = None
    cursor = None
    
    try:
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Determinar nombre del SG
        if sg_name is None:
            query = "SELECT rules FROM security_groups WHERE slice_id = %s AND is_default = TRUE"
            cursor.execute(query, (slice_id,))
        else:
            query = "SELECT rules FROM security_groups WHERE slice_id = %s AND name = %s"
            cursor.execute(query, (slice_id, sg_name))
        
        result = cursor.fetchone()
        
        if not result:
            logger.warning(f"SG no encontrado en BD (slice {slice_id}, name={sg_name})")
            return None
        
        rules = json.loads(result['rules']) if result['rules'] else []
        
        # Buscar la regla con el ID secuencial
        for rule in rules:
            if rule.get('id') == rule_id:
                return rule.get('id_openstack')  # Campo actualizado
        
        logger.warning(f"Regla {rule_id} no encontrada en SG")
        return None
        
    except Exception as e:
        logger.error(f"Error obteniendo UUID de OpenStack: {str(e)}")
        return None
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

# Funciones auxiliares
async def call_linux_orchestrator(endpoint: str, method: str = "POST", 
                                  payload: Optional[Dict] = None, 
                                  timeout: int = 300) -> Dict[str, Any]:
    """
    Llamada al orquestador Linux (orquestador_api.py)
    
    Args:
        endpoint: Endpoint de la API (ej: /desplegar-slice, /eliminar-slice)
        method: Método HTTP (POST)
        payload: Datos a enviar
        timeout: Timeout en segundos (5 min por defecto para despliegues)
    
    Returns:
        Dict con resultado de la llamada
    """
    try:
        orchestrator = ORCHESTRATORS['linux']
        url = f"{orchestrator['base_url']}{endpoint}"
        
        logger.info(f"Llamando a orquestador Linux: {url}")
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "POST":
                response = await client.post(url, json=payload)
            else:
                response = await client.get(url)
        
        if response.status_code == 200:
            return {
                'success': True,
                'status_code': 200,
                'data': response.json()
            }
        else:
            logger.error(f"Error del orquestador Linux: {response.status_code} - {response.text}")
            return {
                'success': False,
                'status_code': response.status_code,
                'error': response.text
            }
            
    except httpx.TimeoutException:
        logger.error(f"Timeout conectando al orquestador Linux")
        return {
            'success': False,
            'error': 'timeout',
            'message': 'Timeout conectando con el orquestador Linux'
        }
    except httpx.ConnectError:
        logger.error(f"Error de conexión al orquestador Linux")
        return {
            'success': False,
            'error': 'connection_error',
            'message': f'No se pudo conectar con el orquestador Linux en {orchestrator["base_url"]}'
        }
    except Exception as e:
        logger.error(f"Error interno llamando al orquestador: {str(e)}")
        return {
            'success': False,
            'error': 'internal_error',
            'message': f'Error interno: {str(e)}'
        }

async def call_security_api_linux(endpoint: str, method: str = "POST",
                                   payload: Optional[Dict] = None,
                                   timeout: int = 30) -> Dict[str, Any]:
    """
    Llamada a la Security Groups API Linux (security_api.py)
    
    Args:
        endpoint: Endpoint de la API (ej: /create-custom, /add-rule)
        method: Método HTTP (POST, GET)
        payload: Datos a enviar
        timeout: Timeout en segundos
    
    Returns:
        Dict con resultado de la llamada
    """
    try:
        api = SECURITY_API_LINUX
        url = f"{api['base_url']}{endpoint}"
        
        logger.info(f"Llamando a Security Groups API: {url}")
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "POST":
                response = await client.post(url, json=payload)
            elif method == "GET":
                response = await client.get(url)
            else:
                return {'success': False, 'error': f'Método {method} no soportado'}
        
        if response.status_code == 200:
            return {
                'success': True,
                'status_code': 200,
                'data': response.json()
            }
        else:
            logger.error(f"Error de Security API: {response.status_code} - {response.text}")
            return {
                'success': False,
                'status_code': response.status_code,
                'error': response.text
            }
    
    except httpx.TimeoutException:
        logger.error("Timeout conectando a Security Groups API")
        return {
            'success': False,
            'error': 'timeout',
            'message': 'Timeout conectando con Security Groups API'
        }
    except httpx.ConnectError:
        logger.error("Error de conexión a Security Groups API")
        return {
            'success': False,
            'error': 'connection_error',
            'message': f'No se pudo conectar con Security Groups API en {api["base_url"]}'
        }
    except Exception as e:
        logger.error(f"Error interno llamando a Security API: {str(e)}")
        return {
            'success': False,
            'error': 'internal_error',
            'message': f'Error interno: {str(e)}'
        }

async def deploy_to_linux(json_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Despliega un slice en el cluster Linux
    
    Llama al endpoint /desplegar-slice del orquestador_api.py
    Ahora el orquestador devuelve solo: {success, message, slice_id, vnc_mapping, error}
    """
    logger.info(f"Iniciando despliegue en cluster Linux")
    
    payload = {
        "json_config": json_config
    }
    
    result = await call_linux_orchestrator("/desplegar-slice", "POST", payload, timeout=300)
    
    if not result['success']:
        return {
            'success': False,
            'message': 'Error comunicándose con el orquestador Linux',
            'error': result.get('message', result.get('error', 'Unknown error')),
            'connection_failed': result.get('error') in ['timeout', 'connection_error']
        }
    
    response_data = result['data']
    
    # Verificar si el despliegue fue exitoso
    if response_data.get('success'):
        logger.info(f"Despliegue exitoso en cluster Linux")
        
        # LOG: Imprimir respuesta del orquestador
        logger.info(f"RESPUESTA DEL ORQUESTADOR:")
        logger.info(json.dumps(response_data, indent=2, ensure_ascii=False))
        
        # El orquestador ahora solo devuelve vnc_mapping
        vnc_mapping = response_data.get('vnc_mapping', {})
        
        return {
            'success': True,
            'message': response_data.get('message', 'Despliegue exitoso'),
            'vnc_mapping': vnc_mapping
        }
    else:
        logger.error(f"Error en despliegue Linux: {response_data.get('message')}")
        return {
            'success': False,
            'message': 'Error durante el despliegue en cluster Linux',
            'error': response_data.get('message', 'Unknown deployment error'),
            'connection_failed': False
        }

async def delete_from_linux(slice_id: int) -> Dict[str, Any]:
    """
    Elimina un slice del cluster Linux
    
    Llama al endpoint /eliminar-slice del orquestador_api.py
    """
    logger.info(f"Iniciando eliminación del slice {slice_id} en cluster Linux")
    
    payload = {
        "slice_id": slice_id
    }
    
    result = await call_linux_orchestrator("/eliminar-slice", "POST", payload, timeout=120)
    
    if not result['success']:
        return {
            'success': False,
            'message': 'Error comunicándose con el orquestador Linux',
            'error': result.get('message', result.get('error', 'Unknown error')),
            'connection_failed': result.get('error') in ['timeout', 'connection_error']
        }
    
    response_data = result['data']
    
    if response_data.get('success'):
        logger.info(f"Eliminación exitosa del slice {slice_id}")
        return {
            'success': True,
            'message': response_data.get('message', 'Slice eliminado exitosamente'),
            'workers_results': response_data.get('workers_results')
        }
    else:
        logger.error(f"Error eliminando slice {slice_id}: {response_data.get('message')}")
        return {
            'success': False,
            'message': 'Error durante la eliminación en cluster Linux',
            'error': response_data.get('message', 'Unknown deletion error'),
            'connection_failed': False
        }

# =============================================================================
# FUNCIONES AUXILIARES PARA OPERACIONES DE VM INDIVIDUAL
# =============================================================================

async def pause_vm_linux(slice_id: int, vm_name: str) -> Dict[str, Any]:
    """Pausar una VM específica en cluster Linux"""
    logger.info(f"Pausando VM {vm_name} del slice {slice_id} en cluster Linux")
    
    payload = {"slice_id": slice_id, "vm_name": vm_name}
    result = await call_linux_orchestrator("/pausar-vm", "POST", payload, timeout=60)
    
    if not result['success']:
        return {
            'success': False,
            'message': 'Error comunicándose con el orquestador Linux',
            'error': result.get('message', result.get('error', 'Unknown error')),
            'connection_failed': result.get('error') in ['timeout', 'connection_error']
        }
    
    response_data = result['data']
    
    if response_data.get('success'):
        logger.info(f"VM {vm_name} pausada exitosamente")
        return {
            'success': True,
            'message': response_data.get('message', f'VM {vm_name} pausada exitosamente'),
            'workers_results': response_data.get('workers_results')
        }
    else:
        logger.error(f"Error pausando VM {vm_name}: {response_data.get('message')}")
        return {
            'success': False,
            'message': f'Error al pausar VM {vm_name}',
            'error': response_data.get('error', 'Unknown error'),
            'connection_failed': False
        }

async def resume_vm_linux(slice_id: int, vm_name: str) -> Dict[str, Any]:
    """Reanudar una VM específica en cluster Linux"""
    logger.info(f"Reanudando VM {vm_name} del slice {slice_id} en cluster Linux")
    
    payload = {"slice_id": slice_id, "vm_name": vm_name}
    result = await call_linux_orchestrator("/reanudar-vm", "POST", payload, timeout=60)
    
    if not result['success']:
        return {
            'success': False,
            'message': 'Error comunicándose con el orquestador Linux',
            'error': result.get('message', result.get('error', 'Unknown error')),
            'connection_failed': result.get('error') in ['timeout', 'connection_error']
        }
    
    response_data = result['data']
    
    if response_data.get('success'):
        logger.info(f"VM {vm_name} reanudada exitosamente")
        return {
            'success': True,
            'message': response_data.get('message', f'VM {vm_name} reanudada exitosamente'),
            'workers_results': response_data.get('workers_results')
        }
    else:
        logger.error(f"Error reanudando VM {vm_name}: {response_data.get('message')}")
        return {
            'success': False,
            'message': f'Error al reanudar VM {vm_name}',
            'error': response_data.get('error', 'Unknown error'),
            'connection_failed': False
        }

async def shutdown_vm_linux(slice_id: int, vm_name: str) -> Dict[str, Any]:
    """Apagar una VM específica en cluster Linux"""
    logger.info(f"Apagando VM {vm_name} del slice {slice_id} en cluster Linux")
    
    payload = {"slice_id": slice_id, "vm_name": vm_name}
    result = await call_linux_orchestrator("/apagar-vm", "POST", payload, timeout=60)
    
    if not result['success']:
        return {
            'success': False,
            'message': 'Error comunicándose con el orquestador Linux',
            'error': result.get('message', result.get('error', 'Unknown error')),
            'connection_failed': result.get('error') in ['timeout', 'connection_error']
        }
    
    response_data = result['data']
    
    if response_data.get('success'):
        logger.info(f"VM {vm_name} apagada exitosamente")
        return {
            'success': True,
            'message': response_data.get('message', f'VM {vm_name} apagada exitosamente'),
            'workers_results': response_data.get('workers_results')
        }
    else:
        logger.error(f"Error apagando VM {vm_name}: {response_data.get('message')}")
        return {
            'success': False,
            'message': f'Error al apagar VM {vm_name}',
            'error': response_data.get('error', 'Unknown error'),
            'connection_failed': False
        }

async def start_vm_linux(slice_id: int, vm_name: str) -> Dict[str, Any]:
    """Encender una VM específica en cluster Linux"""
    logger.info(f"Encendiendo VM {vm_name} del slice {slice_id} en cluster Linux")
    
    payload = {"slice_id": slice_id, "vm_name": vm_name}
    result = await call_linux_orchestrator("/encender-vm", "POST", payload, timeout=60)
    
    if not result['success']:
        return {
            'success': False,
            'message': 'Error comunicándose con el orquestador Linux',
            'error': result.get('message', result.get('error', 'Unknown error')),
            'connection_failed': result.get('error') in ['timeout', 'connection_error']
        }
    
    response_data = result['data']
    
    if response_data.get('success'):
        logger.info(f"VM {vm_name} encendida exitosamente")
        return {
            'success': True,
            'message': response_data.get('message', f'VM {vm_name} encendida exitosamente'),
            'workers_results': response_data.get('workers_results')
        }
    else:
        logger.error(f"Error encendiendo VM {vm_name}: {response_data.get('message')}")
        return {
            'success': False,
            'message': f'Error al encender VM {vm_name}',
            'error': response_data.get('error', 'Unknown error'),
            'connection_failed': False
        }

# =============================================================================
# FUNCIONES AUXILIARES PARA OPERACIONES DE SLICE COMPLETO
# =============================================================================

async def shutdown_slice_linux(slice_id: int) -> Dict[str, Any]:
    """Apagar todas las VMs de un slice en cluster Linux"""
    logger.info(f"Apagando slice {slice_id} en cluster Linux")
    
    payload = {"slice_id": slice_id}
    result = await call_linux_orchestrator("/apagar-slice", "POST", payload, timeout=120)
    
    if not result['success']:
        return {
            'success': False,
            'message': 'Error comunicándose con el orquestador Linux',
            'error': result.get('message', result.get('error', 'Unknown error')),
            'connection_failed': result.get('error') in ['timeout', 'connection_error']
        }
    
    response_data = result['data']
    
    if response_data.get('success'):
        logger.info(f"Slice {slice_id} apagado exitosamente")
        return {
            'success': True,
            'message': response_data.get('message', f'Slice {slice_id} apagado exitosamente'),
            'workers_results': response_data.get('workers_results')
        }
    else:
        logger.error(f"Error apagando slice {slice_id}: {response_data.get('message')}")
        return {
            'success': False,
            'message': f'Error al apagar slice {slice_id}',
            'error': response_data.get('error', 'Unknown error'),
            'connection_failed': False
        }

async def start_slice_linux(slice_id: int) -> Dict[str, Any]:
    """Encender todas las VMs de un slice en cluster Linux"""
    logger.info(f"Encendiendo slice {slice_id} en cluster Linux")
    
    payload = {"slice_id": slice_id}
    result = await call_linux_orchestrator("/encender-slice", "POST", payload, timeout=120)
    
    if not result['success']:
        return {
            'success': False,
            'message': 'Error comunicándose con el orquestador Linux',
            'error': result.get('message', result.get('error', 'Unknown error')),
            'connection_failed': result.get('error') in ['timeout', 'connection_error']
        }
    
    response_data = result['data']
    
    if response_data.get('success'):
        logger.info(f"Slice {slice_id} encendido exitosamente")
        return {
            'success': True,
            'message': response_data.get('message', f'Slice {slice_id} encendido exitosamente'),
            'workers_results': response_data.get('workers_results')
        }
    else:
        logger.error(f"Error encendiendo slice {slice_id}: {response_data.get('message')}")
        return {
            'success': False,
            'message': f'Error al encender slice {slice_id}',
            'error': response_data.get('error', 'Unknown error'),
            'connection_failed': False
        }

# =============================================================================
# FUNCIONES AUXILIARES PARA OPENSTACK
# =============================================================================

async def call_openstack_orchestrator(endpoint: str, method: str = "POST", 
                                      payload: Optional[Dict] = None, 
                                      timeout: int = 300) -> Dict[str, Any]:
    """
    Llamada al orquestador OpenStack (main.py)
    
    Args:
        endpoint: Endpoint de la API (ej: /deploy-topology, /delete-slice/{id})
        method: Método HTTP (POST, DELETE)
        payload: Datos a enviar
        timeout: Timeout en segundos (5 min por defecto para despliegues)
    
    Returns:
        Dict con resultado de la llamada
    """
    try:
        orchestrator = ORCHESTRATORS['openstack']
        url = f"{orchestrator['base_url']}{endpoint}"
        
        logger.info(f"Llamando a orquestador OpenStack: {url}")
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "POST":
                response = await client.post(url, json=payload)
            elif method == "DELETE":
                response = await client.delete(url)
            else:
                response = await client.get(url)
        
        if response.status_code == 200:
            return {
                'success': True,
                'status_code': 200,
                'data': response.json()
            }
        else:
            logger.error(f"Error del orquestador OpenStack: {response.status_code} - {response.text}")
            return {
                'success': False,
                'status_code': response.status_code,
                'error': response.text
            }
            
    except httpx.TimeoutException:
        logger.error(f"Timeout conectando al orquestador OpenStack")
        return {
            'success': False,
            'error': 'timeout',
            'message': 'Timeout conectando con el orquestador OpenStack'
        }
    except httpx.ConnectError:
        logger.error(f"Error de conexión al orquestador OpenStack")
        return {
            'success': False,
            'error': 'connection_error',
            'message': f'No se pudo conectar con el orquestador OpenStack en {orchestrator["base_url"]}'
        }
    except Exception as e:
        logger.error(f"Error interno llamando al orquestador OpenStack: {str(e)}")
        return {
            'success': False,
            'error': 'internal_error',
            'message': f'Error interno: {str(e)}'
        }

async def call_security_api_openstack(endpoint: str, method: str = "POST",
                                       payload: Optional[Dict] = None,
                                       timeout: int = 30) -> Dict[str, Any]:
    """
    Llamada a la Security Groups API OpenStack (security_api.py)
    
    Args:
        endpoint: Endpoint de la API (ej: /create-custom, /add-rule)
        method: Método HTTP (POST, GET)
        payload: Datos a enviar
        timeout: Timeout en segundos
    
    Returns:
        Dict con resultado de la llamada
    """
    try:
        api = SECURITY_API_OPENSTACK
        url = f"{api['base_url']}{endpoint}"
        
        logger.info(f"Llamando a Security Groups API OpenStack: {url}")
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "POST":
                response = await client.post(url, json=payload)
            elif method == "GET":
                response = await client.get(url)
            else:
                return {'success': False, 'error': f'Método {method} no soportado'}
        
        if response.status_code == 200:
            return {
                'success': True,
                'status_code': 200,
                'data': response.json()
            }
        else:
            logger.error(f"Error de Security API OpenStack: {response.status_code} - {response.text}")
            return {
                'success': False,
                'status_code': response.status_code,
                'error': response.text
            }
    
    except httpx.TimeoutException:
        logger.error("Timeout conectando a Security Groups API OpenStack")
        return {
            'success': False,
            'error': 'timeout',
            'message': 'Timeout conectando con Security Groups API OpenStack'
        }
    except httpx.ConnectError:
        logger.error("Error de conexión a Security Groups API OpenStack")
        return {
            'success': False,
            'error': 'connection_error',
            'message': f'No se pudo conectar con Security Groups API OpenStack en {api["base_url"]}'
        }
    except Exception as e:
        logger.error(f"Error interno llamando a Security API OpenStack: {str(e)}")
        return {
            'success': False,
            'error': 'internal_error',
            'message': f'Error interno: {str(e)}'
        }

async def deploy_to_openstack(json_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Despliega un slice en el cluster OpenStack
    
    Llama al endpoint /deploy-topology del main.py de OpenStack
    """
    logger.info(f"Iniciando despliegue en cluster OpenStack")
    
    payload = {
        "json_config": json_config
    }
    
    result = await call_openstack_orchestrator("/deploy-topology", "POST", payload, timeout=300)
    
    if not result['success']:
        return {
            'success': False,
            'message': 'Error comunicándose con el orquestador OpenStack',
            'error': result.get('message', result.get('error', 'Unknown error')),
            'connection_failed': result.get('error') in ['timeout', 'connection_error']
        }
    
    response_data = result['data']
    
    # Verificar si el despliegue fue exitoso
    if response_data.get('status') == 'success':
        logger.info(f"Despliegue exitoso en cluster OpenStack")
        
        # LOG: Imprimir respuesta del orquestador
        logger.info(f"RESPUESTA DEL ORQUESTADOR OPENSTACK:")
        logger.info(json.dumps(response_data, indent=2, ensure_ascii=False))
        
        # OpenStack devuelve: project_id, default_sg_rules
        project_id = response_data.get('project_id')
        default_sg_rules = response_data.get('default_sg_rules', [])
        
        # Actualizar BD con los UUIDs de las reglas default
        slice_id = json_config.get('id_slice')
        if slice_id and default_sg_rules:
            update_default_sg_rules_with_uuids(int(slice_id), default_sg_rules)
        
        return {
            'success': True,
            'message': response_data.get('message', 'Despliegue exitoso'),
            'project_id': project_id,
            'default_sg_rules': default_sg_rules
        }
    else:
        logger.error(f"Error en despliegue OpenStack: {response_data.get('message')}")
        return {
            'success': False,
            'message': 'Error durante el despliegue en cluster OpenStack',
            'error': response_data.get('message', 'Unknown deployment error'),
            'connection_failed': False
        }

async def delete_from_openstack(slice_id: int) -> Dict[str, Any]:
    """
    Elimina un slice del cluster OpenStack
    
    Llama al endpoint /delete-slice/{slice_id} del main.py de OpenStack
    """
    logger.info(f"Iniciando eliminación del slice {slice_id} en cluster OpenStack")
    
    result = await call_openstack_orchestrator(f"/delete-slice/{slice_id}", "DELETE", timeout=120)
    
    if not result['success']:
        return {
            'success': False,
            'message': 'Error comunicándose con el orquestador OpenStack',
            'error': result.get('message', result.get('error', 'Unknown error')),
            'connection_failed': result.get('error') in ['timeout', 'connection_error']
        }
    
    response_data = result['data']
    
    if response_data.get('status') == 'success':
        logger.info(f"Eliminación exitosa del slice {slice_id}")
        return {
            'success': True,
            'message': response_data.get('message', 'Slice eliminado exitosamente'),
            'deletion_details': response_data.get('deletion_details')
        }
    else:
        logger.error(f"Error eliminando slice {slice_id}: {response_data.get('message')}")
        return {
            'success': False,
            'message': 'Error durante la eliminación en cluster OpenStack',
            'error': response_data.get('message', 'Unknown deletion error'),
            'connection_failed': False
        }

# Endpoints
@app.get("/")
async def root():
    return {
        "message": "Drivers API - Bypass de despliegue",
        "status": "activo",
        "version": "1.0.0",
        "supported_zones": list(ORCHESTRATORS.keys())
    }

@app.post("/deploy-slice", response_model=DeploySliceResponse)
async def deploy_slice(
    request: DeploySliceRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Despliega un slice en el orquestador correspondiente según zona_despliegue
    
    Flujo:
    1. Identifica zona_despliegue (linux/openstack)
    2. Llama al orquestador correspondiente
    3. Si hay error de despliegue → llama a eliminar-slice
    4. Si hay error de conexión → retorna error de conexión
    5. Si es exitoso → retorna JSON procesado completo
    
    Returns:
        - success: True si despliegue exitoso
        - processed_json: JSON completo procesado (para actualizar BD)
        - error: Mensaje de error si falla
    """
    try:
        json_config = request.json_config
        
        # Extraer zona_despliegue
        zona_despliegue = json_config.get('zona_despliegue', '').lower()
        
        if not zona_despliegue:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El campo 'zona_despliegue' es requerido"
            )
        
        # Extraer slice_id (formato simplificado: id_slice directo en json_config)
        slice_id_str = json_config.get('id_slice')
        
        try:
            slice_id = int(slice_id_str) if slice_id_str else None
        except (ValueError, TypeError):
            slice_id = None
        
        if not slice_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El campo 'id_slice' es requerido"
            )
        
        logger.info(f"Procesando despliegue de slice {slice_id} en zona '{zona_despliegue}'")
        
        # Validar zona soportada
        if zona_despliegue not in ORCHESTRATORS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona de despliegue '{zona_despliegue}' no soportada. Zonas válidas: {list(ORCHESTRATORS.keys())}"
            )
        
        # Desplegar según zona
        if zona_despliegue == 'linux':
            result = await deploy_to_linux(json_config)
        elif zona_despliegue == 'openstack':
            result = await deploy_to_openstack(json_config)
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=f"Despliegue en {zona_despliegue} no implementado"
            )
        
        # Analizar resultado
        if result.get('connection_failed'):
            # Error de conexión con el orquestador
            logger.error(f"Conexión fallida con orquestador {zona_despliegue}")
            return DeploySliceResponse(
                success=False,
                message=f"Conexión fallida con orquestador {zona_despliegue}",
                zone=zona_despliegue,
                slice_id=slice_id,
                error=result.get('error', 'Connection failed')
            )
        
        elif not result['success']:
            # Error durante el despliegue (orquestador ya hizo rollback)
            logger.error(f"Error en despliegue de slice {slice_id}: {result.get('error')}")
            
            return DeploySliceResponse(
                success=False,
                message=f"Error al desplegar slice {slice_id}",
                zone=zona_despliegue,
                slice_id=slice_id,
                deployment_details=result.get('deployment_details'),
                error=result.get('error', 'Deployment failed')
            )
        
        else:
            # Despliegue exitoso
            logger.info(f"Despliegue exitoso para slice {slice_id}")
            
            # Preparar respuesta según zona
            response_data = {
                "success": True,
                "message": f"Slice {slice_id} desplegado exitosamente en {zona_despliegue}",
                "zone": zona_despliegue,
                "slice_id": slice_id
            }
            
            # Agregar campos específicos según zona
            if zona_despliegue == 'linux':
                response_data["vnc_mapping"] = result.get('vnc_mapping', {})
            elif zona_despliegue == 'openstack':
                response_data["project_id"] = result.get('project_id')
                response_data["default_sg_rules"] = result.get('default_sg_rules', [])
            
            return DeploySliceResponse(**response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error interno en deploy-slice: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )

@app.post("/delete-slice", response_model=DeleteSliceResponse)
async def delete_slice(
    request: DeleteSliceRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Elimina un slice del orquestador correspondiente
    
    Args:
        slice_id: ID del slice a eliminar
        zona_despliegue: Zona donde está desplegado (linux/openstack)
    
    Returns:
        Resultado de la eliminación
    """
    try:
        slice_id = request.slice_id
        zona_despliegue = request.zona_despliegue.lower()
        
        logger.info(f"Procesando eliminación de slice {slice_id} en zona '{zona_despliegue}'")
        
        # Validar zona
        if zona_despliegue not in ORCHESTRATORS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona de despliegue '{zona_despliegue}' no soportada"
            )
        
        # Eliminar según zona
        if zona_despliegue == 'linux':
            result = await delete_from_linux(slice_id)
        elif zona_despliegue == 'openstack':
            result = await delete_from_openstack(slice_id)
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=f"Eliminación en {zona_despliegue} no implementada"
            )
        
        # Analizar resultado
        if result.get('connection_failed'):
            logger.error(f"Conexión fallida con orquestador {zona_despliegue}")
            return DeleteSliceResponse(
                success=False,
                message=f"Conexión fallida con orquestador {zona_despliegue}",
                zone=zona_despliegue,
                slice_id=slice_id,
                error=result.get('error', 'Connection failed')
            )
        
        elif not result['success']:
            logger.error(f"Error eliminando slice {slice_id}")
            return DeleteSliceResponse(
                success=False,
                message=f"Error eliminando slice {slice_id}",
                zone=zona_despliegue,
                slice_id=slice_id,
                deletion_details=result,
                error=result.get('error', 'Deletion failed')
            )
        
        else:
            logger.info(f"Slice {slice_id} eliminado exitosamente")
            return DeleteSliceResponse(
                success=True,
                message=result.get('message', f'Slice {slice_id} eliminado exitosamente'),
                zone=zona_despliegue,
                slice_id=slice_id,
                deletion_details=result
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error interno en delete-slice: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )

@app.post("/pause-slice")
async def pause_slice(
    request: DeleteSliceRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Pausar un slice en el orquestador correspondiente
    
    Args:
        slice_id: ID del slice a pausar
        zona_despliegue: Zona donde está desplegado (linux/openstack)
    
    Returns:
        Resultado de la operación de pausa
    """
    try:
        slice_id = request.slice_id
        zona_despliegue = request.zona_despliegue.lower()
        
        logger.info(f"Procesando pausa de slice {slice_id} en zona '{zona_despliegue}'")
        
        # Validar zona
        if zona_despliegue not in ORCHESTRATORS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona de despliegue '{zona_despliegue}' no soportada"
            )
        
        # Pausar según zona
        if zona_despliegue == 'linux':
            # Llamar al endpoint /pausar-slice del orquestador Linux
            payload = {"slice_id": slice_id}
            result = await call_linux_orchestrator("/pausar-slice", "POST", payload, timeout=120)
            
            if not result['success']:
                error_msg = result.get('message', result.get('error', 'Unknown error'))
                logger.error(f"Error al pausar slice {slice_id}: {error_msg}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Error al pausar slice: {error_msg}"
                )
            
            response_data = result['data']
            
            if not response_data.get('success'):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Error al pausar slice: {response_data.get('message', 'Unknown error')}"
                )
            
            logger.info(f"Slice {slice_id} pausado exitosamente")
            
            return {
                "success": True,
                "message": response_data.get('message', f'Slice {slice_id} pausado exitosamente'),
                "zone": zona_despliegue,
                "slice_id": slice_id,
                "workers_results": response_data.get('workers_results')
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Pausa en OpenStack no implementada aún"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error interno en pause-slice: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )

@app.post("/resume-slice")
async def resume_slice(
    request: DeleteSliceRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Reanudar un slice pausado en el orquestador correspondiente
    
    Args:
        slice_id: ID del slice a reanudar
        zona_despliegue: Zona donde está desplegado (linux/openstack)
    
    Returns:
        Resultado de la operación de reanudación
    """
    try:
        slice_id = request.slice_id
        zona_despliegue = request.zona_despliegue.lower()
        
        logger.info(f"Procesando reanudación de slice {slice_id} en zona '{zona_despliegue}'")
        
        # Validar zona
        if zona_despliegue not in ORCHESTRATORS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona de despliegue '{zona_despliegue}' no soportada"
            )
        
        # Reanudar según zona
        if zona_despliegue == 'linux':
            # Llamar al endpoint /reanudar-slice del orquestador Linux
            payload = {"slice_id": slice_id}
            result = await call_linux_orchestrator("/reanudar-slice", "POST", payload, timeout=120)
            
            if not result['success']:
                error_msg = result.get('message', result.get('error', 'Unknown error'))
                logger.error(f"Error al reanudar slice {slice_id}: {error_msg}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Error al reanudar slice: {error_msg}"
                )
            
            response_data = result['data']
            
            if not response_data.get('success'):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Error al reanudar slice: {response_data.get('message', 'Unknown error')}"
                )
            
            logger.info(f"Slice {slice_id} reanudado exitosamente")
            
            return {
                "success": True,
                "message": response_data.get('message', f'Slice {slice_id} reanudado exitosamente'),
                "zone": zona_despliegue,
                "slice_id": slice_id,
                "workers_results": response_data.get('workers_results')
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Reanudación en OpenStack no implementada aún"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error interno en resume-slice: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )

# =============================================================================
# ENDPOINTS DE OPERACIONES DE VM INDIVIDUAL
# =============================================================================

@app.post("/pause-vm", response_model=OperationResponse)
async def pause_vm(
    request: VMOperationRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Pausa una VM específica de un slice
    
    Args:
        slice_id: ID del slice
        vm_name: Nombre de la VM (ej: vm1, vm2)
        zona_despliegue: Zona donde está desplegado
    
    Returns:
        Resultado de la operación
    """
    try:
        slice_id = request.slice_id
        vm_name = request.vm_name
        zona_despliegue = request.zona_despliegue.lower()
        
        logger.info(f"Pausando VM {vm_name} del slice {slice_id} en zona '{zona_despliegue}'")
        
        # Validar zona
        if zona_despliegue not in ORCHESTRATORS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona de despliegue '{zona_despliegue}' no soportada"
            )
        
        # Pausar según zona
        if zona_despliegue == 'linux':
            result = await pause_vm_linux(slice_id, vm_name)
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Pausa de VM en OpenStack no implementada aún"
            )
        
        # Analizar resultado
        if result.get('connection_failed'):
            return OperationResponse(
                success=False,
                message=f"Conexión fallida con orquestador {zona_despliegue}",
                zone=zona_despliegue,
                slice_id=slice_id,
                vm_name=vm_name,
                error=result.get('error', 'Connection failed')
            )
        
        return OperationResponse(
            success=result['success'],
            message=result.get('message', f'VM {vm_name} pausada'),
            zone=zona_despliegue,
            slice_id=slice_id,
            vm_name=vm_name,
            workers_results=result.get('workers_results'),
            error=result.get('error')
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error interno en pause-vm: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )

@app.post("/resume-vm", response_model=OperationResponse)
async def resume_vm(
    request: VMOperationRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Reanuda una VM específica pausada de un slice
    
    Args:
        slice_id: ID del slice
        vm_name: Nombre de la VM (ej: vm1, vm2)
        zona_despliegue: Zona donde está desplegado
    
    Returns:
        Resultado de la operación
    """
    try:
        slice_id = request.slice_id
        vm_name = request.vm_name
        zona_despliegue = request.zona_despliegue.lower()
        
        logger.info(f"Reanudando VM {vm_name} del slice {slice_id} en zona '{zona_despliegue}'")
        
        # Validar zona
        if zona_despliegue not in ORCHESTRATORS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona de despliegue '{zona_despliegue}' no soportada"
            )
        
        # Reanudar según zona
        if zona_despliegue == 'linux':
            result = await resume_vm_linux(slice_id, vm_name)
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Reanudación de VM en OpenStack no implementada aún"
            )
        
        # Analizar resultado
        if result.get('connection_failed'):
            return OperationResponse(
                success=False,
                message=f"Conexión fallida con orquestador {zona_despliegue}",
                zone=zona_despliegue,
                slice_id=slice_id,
                vm_name=vm_name,
                error=result.get('error', 'Connection failed')
            )
        
        return OperationResponse(
            success=result['success'],
            message=result.get('message', f'VM {vm_name} reanudada'),
            zone=zona_despliegue,
            slice_id=slice_id,
            vm_name=vm_name,
            workers_results=result.get('workers_results'),
            error=result.get('error')
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error interno en resume-vm: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )

@app.post("/shutdown-vm", response_model=OperationResponse)
async def shutdown_vm(
    request: VMOperationRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Apaga (shutdown) una VM específica de un slice
    
    Args:
        slice_id: ID del slice
        vm_name: Nombre de la VM (ej: vm1, vm2)
        zona_despliegue: Zona donde está desplegado
    
    Returns:
        Resultado de la operación
    """
    try:
        slice_id = request.slice_id
        vm_name = request.vm_name
        zona_despliegue = request.zona_despliegue.lower()
        
        logger.info(f"Apagando VM {vm_name} del slice {slice_id} en zona '{zona_despliegue}'")
        
        # Validar zona
        if zona_despliegue not in ORCHESTRATORS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona de despliegue '{zona_despliegue}' no soportada"
            )
        
        # Apagar según zona
        if zona_despliegue == 'linux':
            result = await shutdown_vm_linux(slice_id, vm_name)
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Apagado de VM en OpenStack no implementado aún"
            )
        
        # Analizar resultado
        if result.get('connection_failed'):
            return OperationResponse(
                success=False,
                message=f"Conexión fallida con orquestador {zona_despliegue}",
                zone=zona_despliegue,
                slice_id=slice_id,
                vm_name=vm_name,
                error=result.get('error', 'Connection failed')
            )
        
        return OperationResponse(
            success=result['success'],
            message=result.get('message', f'VM {vm_name} apagada'),
            zone=zona_despliegue,
            slice_id=slice_id,
            vm_name=vm_name,
            workers_results=result.get('workers_results'),
            error=result.get('error')
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error interno en shutdown-vm: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )

@app.post("/start-vm", response_model=OperationResponse)
async def start_vm(
    request: VMOperationRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Enciende (start) una VM específica de un slice
    
    Args:
        slice_id: ID del slice
        vm_name: Nombre de la VM (ej: vm1, vm2)
        zona_despliegue: Zona donde está desplegado
    
    Returns:
        Resultado de la operación
    """
    try:
        slice_id = request.slice_id
        vm_name = request.vm_name
        zona_despliegue = request.zona_despliegue.lower()
        
        logger.info(f"Encendiendo VM {vm_name} del slice {slice_id} en zona '{zona_despliegue}'")
        
        # Validar zona
        if zona_despliegue not in ORCHESTRATORS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona de despliegue '{zona_despliegue}' no soportada"
            )
        
        # Encender según zona
        if zona_despliegue == 'linux':
            result = await start_vm_linux(slice_id, vm_name)
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Encendido de VM en OpenStack no implementado aún"
            )
        
        # Analizar resultado
        if result.get('connection_failed'):
            return OperationResponse(
                success=False,
                message=f"Conexión fallida con orquestador {zona_despliegue}",
                zone=zona_despliegue,
                slice_id=slice_id,
                vm_name=vm_name,
                error=result.get('error', 'Connection failed')
            )
        
        return OperationResponse(
            success=result['success'],
            message=result.get('message', f'VM {vm_name} encendida'),
            zone=zona_despliegue,
            slice_id=slice_id,
            vm_name=vm_name,
            workers_results=result.get('workers_results'),
            error=result.get('error')
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error interno en start-vm: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )

# =============================================================================
# ENDPOINTS DE OPERACIONES DE SLICE COMPLETO
# =============================================================================

@app.post("/shutdown-slice", response_model=OperationResponse)
async def shutdown_slice(
    request: SliceOperationRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Apaga todas las VMs de un slice
    
    Args:
        slice_id: ID del slice
        zona_despliegue: Zona donde está desplegado
    
    Returns:
        Resultado de la operación en todos los workers
    """
    try:
        slice_id = request.slice_id
        zona_despliegue = request.zona_despliegue.lower()
        
        logger.info(f"Apagando slice {slice_id} en zona '{zona_despliegue}'")
        
        # Validar zona
        if zona_despliegue not in ORCHESTRATORS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona de despliegue '{zona_despliegue}' no soportada"
            )
        
        # Apagar según zona
        if zona_despliegue == 'linux':
            result = await shutdown_slice_linux(slice_id)
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Apagado de slice en OpenStack no implementado aún"
            )
        
        # Analizar resultado
        if result.get('connection_failed'):
            return OperationResponse(
                success=False,
                message=f"Conexión fallida con orquestador {zona_despliegue}",
                zone=zona_despliegue,
                slice_id=slice_id,
                error=result.get('error', 'Connection failed')
            )
        
        return OperationResponse(
            success=result['success'],
            message=result.get('message', f'Slice {slice_id} apagado'),
            zone=zona_despliegue,
            slice_id=slice_id,
            workers_results=result.get('workers_results'),
            error=result.get('error')
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error interno en shutdown-slice: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )

@app.post("/start-slice", response_model=OperationResponse)
async def start_slice(
    request: SliceOperationRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Enciende todas las VMs de un slice
    
    Args:
        slice_id: ID del slice
        zona_despliegue: Zona donde está desplegado
    
    Returns:
        Resultado de la operación en todos los workers
    """
    try:
        slice_id = request.slice_id
        zona_despliegue = request.zona_despliegue.lower()
        
        logger.info(f"Encendiendo slice {slice_id} en zona '{zona_despliegue}'")
        
        # Validar zona
        if zona_despliegue not in ORCHESTRATORS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona de despliegue '{zona_despliegue}' no soportada"
            )
        
        # Encender según zona
        if zona_despliegue == 'linux':
            result = await start_slice_linux(slice_id)
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Encendido de slice en OpenStack no implementado aún"
            )
        
        # Analizar resultado
        if result.get('connection_failed'):
            return OperationResponse(
                success=False,
                message=f"Conexión fallida con orquestador {zona_despliegue}",
                zone=zona_despliegue,
                slice_id=slice_id,
                error=result.get('error', 'Connection failed')
            )
        
        return OperationResponse(
            success=result['success'],
            message=result.get('message', f'Slice {slice_id} encendido'),
            zone=zona_despliegue,
            slice_id=slice_id,
            workers_results=result.get('workers_results'),
            error=result.get('error')
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error interno en start-slice: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )

# =============================================================================
# ENDPOINTS DE SECURITY GROUPS
# =============================================================================

@app.get("/security-groups-linux/templates")
async def list_security_group_templates(
    zona_despliegue: str = "linux",
    authorized: bool = Depends(get_service_auth)
):
    """
    Listar plantillas de reglas disponibles para cluster Linux
    
    Args:
        zona_despliegue: Zona ('linux' o 'openstack')
    
    Returns:
        Diccionario con todas las plantillas disponibles
    """
    try:
        zona = zona_despliegue.lower()
        
        logger.info(f"Listando plantillas de security groups para zona '{zona}'")
        
        if zona not in ['linux', 'openstack']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona '{zona}' no soportada. Debe ser 'linux' u 'openstack'"
            )
        
        if zona == 'linux':
            result = await call_security_api_linux(
                "/templates",
                method="GET",
                payload=None
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Security Groups en OpenStack no implementado aún"
            )
        
        if not result['success']:
            raise HTTPException(
                status_code=result.get('status_code', 500),
                detail=result.get('error', 'Error obteniendo plantillas')
            )
        
        return result.get('data', {})
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en list-security-group-templates: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/security-groups-linux/status", response_model=SecurityGroupStatusResponse)
async def get_security_group_status(
    request: SecurityGroupStatusRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Consultar estado de security groups en workers específicos del cluster Linux
    
    Args:
        slice_id: ID del slice
        zona_despliegue: Zona del slice
        workers: Workers separados por ';' (opcional, se obtiene automáticamente de BD)
    
    Returns:
        Estado de security groups en cada worker
    """
    try:
        zona = request.zona_despliegue.lower()
        
        logger.info(f"Consultando estado de security groups del slice {request.slice_id} en zona '{zona}'")
        
        if zona not in ['linux', 'openstack']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona '{zona}' no soportada"
            )
        
        # Obtener workers automáticamente si no se proporcionaron
        workers = request.workers
        if not workers:
            workers = get_workers_from_slice(request.slice_id)
            logger.info(f"Workers obtenidos automáticamente: {workers}")
        
        if zona == 'linux':
            result = await call_security_api_linux(
                "/status",
                method="POST",
                payload={
                    "slice_id": request.slice_id,
                    "workers": workers
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Security Groups en OpenStack no implementado aún"
            )
        
        if not result['success']:
            return SecurityGroupStatusResponse(
                success=False,
                slice_id=request.slice_id,
                error=result.get('error', 'Error consultando estado')
            )
        
        data = result.get('data', {})
        return SecurityGroupStatusResponse(
            success=data.get('success', False),
            slice_id=request.slice_id,
            workers_status=data.get('workers_status')
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en get-security-group-status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/security-groups-linux/create-custom", response_model=SecurityGroupResponse)
async def create_custom_security_group(
    request: CreateCustomSGRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Crear security group personalizado en workers específicos del cluster Linux
    
    FLUJO NUEVO:
    1. Crear entrada en BD → obtener ID auto-generado
    2. Usar ese ID para crear SG en workers (security_api)
    3. Si falla, eliminar de BD (rollback)
    
    Args:
        slice_id: ID del slice
        id_sg: (Opcional) ID del SG, si no se provee se genera automáticamente
        zona_despliegue: Zona donde está el slice
        workers: (Opcional) Workers, se auto-detectan si no se proveen
    """
    try:
        zona = request.zona_despliegue.lower()
        
        if zona not in ['linux', 'openstack']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona '{zona}' no soportada. Debe ser 'linux' u 'openstack'"
            )
        
        # PASO 1: Crear en BD y obtener ID auto-generado
        if request.id_sg:
            # Usuario especificó ID manualmente (legacy)
            id_sg = request.id_sg
            logger.warning(f"ID manual {id_sg} especificado (legacy mode)")
        else:
            # Generar ID desde BD (modo recomendado)
            id_sg = create_sg_in_db(
                slice_id=request.slice_id,
                description=f"Security Group personalizado para slice {request.slice_id}"
            )
            logger.info(f"ID {id_sg} generado automáticamente desde BD")
        
        # Obtener workers automáticamente si no se proporcionaron
        workers = request.workers
        if not workers:
            workers = get_workers_from_slice(request.slice_id)
            logger.info(f"Workers obtenidos automáticamente: {workers}")
        
        # PASO 2: Crear SG en workers del cluster usando security_api
        if zona == 'linux':
            result = await call_security_api_linux(
                "/create-custom",
                method="POST",
                payload={
                    "slice_id": request.slice_id,
                    "id_sg": id_sg,  # Usar ID generado por BD
                    "workers": workers
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Security Groups en OpenStack no implementado aún"
            )
        
        # PASO 3: Si falló en workers, hacer rollback en BD
        if not result['success']:
            if not request.id_sg:  # Solo rollback si fue auto-generado
                delete_sg_from_db(request.slice_id, id_sg)
                logger.warning(f"Rollback: SG {id_sg} eliminado de BD tras fallo en workers")
            
            return SecurityGroupResponse(
                success=False,
                message=result.get('message', 'Error creando security group'),
                zone=zona,
                slice_id=request.slice_id,
                error=result.get('error')
            )
        
        data = result.get('data', {})
        return SecurityGroupResponse(
            success=data.get('success', False),
            message=data.get('message', f'Security Group {id_sg} creado (ID BD: {id_sg})'),
            zone=zona,
            slice_id=request.slice_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en create-custom-security-group: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/security-groups-linux/add-rule", response_model=SecurityGroupResponse)
async def add_security_group_rule(
    request: AddRuleRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Agregar regla a un security group del cluster Linux
    
    FLUJO NUEVO:
    1. Determinar nombre del SG (default o SG_{id})
    2. Consultar BD para obtener next_rule_id automáticamente
    3. Agregar regla en workers (security_api)
    4. Si exitoso, actualizar BD con la nueva regla
    
    Args:
        slice_id: ID del slice
        zona_despliegue: Zona del slice
        id_sg: ID del SG personalizado (None = default)
        sg_name: Nombre del SG (alternativa a id_sg)
        rule_id: (Opcional) ID de la regla, se calcula automáticamente si no se provee
        plantilla: Plantilla predefinida (SSH, HTTP, HTTPS, DNS, etc.)
        direction: Dirección (INPUT/OUTPUT)
        protocol, port_range, etc.
        workers: (Opcional) Workers, se auto-detectan
    """
    try:
        zona = request.zona_despliegue.lower()
        
        if zona not in ['linux', 'openstack']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona '{zona}' no soportada"
            )
        
        # PASO 1: Determinar nombre del SG
        if request.sg_name:
            sg_name = request.sg_name
        elif request.id_sg is not None:
            sg_name = f"SG_{request.id_sg}"
        else:
            sg_name = "default"  # SG default del slice
        
        # PASO 2: Obtener rule_id automáticamente si no se proporcionó
        if request.rule_id:
            rule_id = request.rule_id
            logger.warning(f"rule_id manual {rule_id} especificado (legacy mode)")
        else:
            rule_id = get_next_rule_id(request.slice_id, sg_name)
            logger.info(f"rule_id {rule_id} generado automáticamente para SG '{sg_name}'")
        
        # Obtener workers automáticamente si no se proporcionaron
        workers = request.workers
        if not workers:
            workers = get_workers_from_slice(request.slice_id)
            logger.info(f"Workers obtenidos automáticamente: {workers}")
        
        # PASO 3: Agregar regla en workers
        if zona == 'linux':
            payload = {
                "slice_id": request.slice_id,
                "rule_id": rule_id,  # Usar rule_id generado/calculado
                "direction": request.direction,
                "protocol": request.protocol,
                "port_range": request.port_range,
                "description": request.description,
                "workers": workers
            }
            
            # Campos opcionales
            if request.id_sg is not None:
                payload["id_sg"] = request.id_sg
            if request.sg_name:
                payload["sg_name"] = request.sg_name
            if request.plantilla:
                payload["plantilla"] = request.plantilla
            if request.remote_ip_prefix:
                payload["remote_ip_prefix"] = request.remote_ip_prefix
            if request.icmp_type:
                payload["icmp_type"] = request.icmp_type
            if request.icmp_code:
                payload["icmp_code"] = request.icmp_code
            
            result = await call_security_api_linux(
                "/add-rule",
                method="POST",
                payload=payload
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Security Groups en OpenStack no implementado aún"
            )
        
        if not result['success']:
            return SecurityGroupResponse(
                success=False,
                message=result.get('message', 'Error agregando regla'),
                zone=zona,
                slice_id=request.slice_id,
                error=result.get('error')
            )
        
        # PASO 4: Si exitoso en workers, actualizar BD
        rule_data = {
            "id": rule_id,
            "direction": request.direction.lower(),
            "ether_type": "IPv4",  # Default
            "protocol": request.protocol,
            "port_range": request.port_range,
            "remote_ip_prefix": request.remote_ip_prefix,
            "remote_security_group": None,
            "description": request.description
        }
        
        add_rule_to_db(request.slice_id, sg_name, rule_data)
        
        data = result.get('data', {})
        return SecurityGroupResponse(
            success=data.get('success', False),
            message=data.get('message', f'Regla {rule_id} agregada (BD actualizada)'),
            zone=zona,
            slice_id=request.slice_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en add-security-group-rule: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/security-groups-linux/remove-rule", response_model=SecurityGroupResponse)
async def remove_security_group_rule(
    request: RemoveRuleRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Eliminar regla de un security group del cluster Linux
    
    El sistema busca automáticamente la regla en ambas cadenas (INPUT y OUTPUT).
    
    Args:
        slice_id: ID del slice
        zona_despliegue: Zona del slice
        id_sg: ID del SG personalizado (None = default)
        sg_name: Nombre del SG
        rule_id: ID de la regla a eliminar
        workers: Workers donde eliminar (opcional, se obtiene automáticamente de BD)
    """
    try:
        zona = request.zona_despliegue.lower()
        
        logger.info(f"Eliminando regla {request.rule_id} del slice {request.slice_id} en zona '{zona}'")
        
        if zona not in ['linux', 'openstack']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona '{zona}' no soportada"
            )
        
        # Obtener workers automáticamente si no se proporcionaron
        workers = request.workers
        if not workers:
            workers = get_workers_from_slice(request.slice_id)
            logger.info(f"Workers obtenidos automáticamente: {workers}")
        
        # Obtener direction de la BD si no se proporcionó
        direction = request.direction
        if not direction:
            # Determinar nombre del SG para consultar BD
            if request.sg_name:
                sg_name = request.sg_name
            elif request.id_sg is not None:
                sg_name = f"SG_{request.id_sg}"
            else:
                sg_name = "default"
            
            # Consultar BD para obtener direction
            direction = get_rule_direction_from_db(request.slice_id, sg_name, request.rule_id)
            if direction:
                logger.info(f"Direction '{direction}' obtenida automáticamente de BD")
            else:
                direction = "INPUT"  # Fallback por si no se encuentra
                logger.warning(f"Direction no encontrada en BD, usando fallback: {direction}")
        
        if zona == 'linux':
            payload = {
                "slice_id": request.slice_id,
                "rule_id": request.rule_id,
                "direction": direction,  # Enviar direction desde BD
                "workers": workers
            }
            
            if request.id_sg is not None:
                payload["id_sg"] = request.id_sg
            if request.sg_name:
                payload["sg_name"] = request.sg_name
            
            result = await call_security_api_linux(
                "/remove-rule",
                method="POST",
                payload=payload
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Security Groups en OpenStack no implementado aún"
            )
        
        if not result['success']:
            return SecurityGroupResponse(
                success=False,
                message=result.get('message', 'Error eliminando regla'),
                zone=zona,
                slice_id=request.slice_id,
                error=result.get('error')
            )
        
        # Si exitoso en workers, sincronizar BD
        # Determinar nombre del SG
        if request.sg_name:
            sg_name = request.sg_name
        elif request.id_sg is not None:
            sg_name = f"SG_{request.id_sg}"
        else:
            sg_name = "default"
        
        remove_rule_from_db(request.slice_id, sg_name, request.rule_id)
        
        data = result.get('data', {})
        return SecurityGroupResponse(
            success=data.get('success', False),
            message=data.get('message', f'Regla {request.rule_id} eliminada (BD actualizada)'),
            zone=zona,
            slice_id=request.slice_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en remove-security-group-rule: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/security-groups-linux/remove-custom", response_model=SecurityGroupResponse)
async def remove_custom_security_group(
    request: RemoveCustomSGRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Eliminar security group personalizado del cluster Linux
    
    Args:
        slice_id: ID del slice
        zona_despliegue: Zona del slice
        id_sg: ID del security group a eliminar
        workers: Workers donde eliminar (opcional, se obtiene automáticamente de BD)
    """
    try:
        zona = request.zona_despliegue.lower()
        
        logger.info(f"Eliminando Security Group {request.id_sg} del slice {request.slice_id} en zona '{zona}'")
        
        if zona not in ['linux', 'openstack']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona '{zona}' no soportada"
            )
        
        # Obtener workers automáticamente si no se proporcionaron
        workers = request.workers
        if not workers:
            workers = get_workers_from_slice(request.slice_id)
            logger.info(f"Workers obtenidos automáticamente: {workers}")
        
        if zona == 'linux':
            result = await call_security_api_linux(
                "/remove-custom",
                method="POST",
                payload={
                    "slice_id": request.slice_id,
                    "id_sg": request.id_sg,
                    "workers": workers
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Security Groups en OpenStack no implementado aún"
            )
        
        if not result['success']:
            return SecurityGroupResponse(
                success=False,
                message=result.get('message', 'Error eliminando security group'),
                zone=zona,
                slice_id=request.slice_id,
                error=result.get('error')
            )
        
        # Si exitoso en workers, sincronizar BD
        delete_sg_from_db(request.slice_id, request.id_sg)
        
        data = result.get('data', {})
        return SecurityGroupResponse(
            success=data.get('success', False),
            message=data.get('message', f'Security Group {request.id_sg} eliminado (BD actualizada)'),
            zone=zona,
            slice_id=request.slice_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en remove-custom-security-group: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/security-groups-linux/remove-default", response_model=SecurityGroupResponse)
async def remove_default_security_group(
    request: RemoveDefaultSGRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Eliminar security group default del cluster Linux de un slice
    
    ⚠️ ADVERTENCIA: Esto deja las VMs sin protección de firewall.
    Solo recomendado antes de eliminar el slice completo.
    
    Args:
        slice_id: ID del slice
        zona_despliegue: Zona del slice
        workers: Workers donde eliminar (opcional, se obtiene automáticamente de BD)
    """
    try:
        zona = request.zona_despliegue.lower()
        
        logger.warning(f"Eliminando Security Group DEFAULT del slice {request.slice_id} en zona '{zona}'")
        
        if zona not in ['linux', 'openstack']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona '{zona}' no soportada"
            )
        
        # Obtener workers automáticamente si no se proporcionaron
        workers = request.workers
        if not workers:
            workers = get_workers_from_slice(request.slice_id)
            logger.info(f"Workers obtenidos automáticamente: {workers}")
        
        if zona == 'linux':
            result = await call_security_api_linux(
                "/remove-default",
                method="POST",
                payload={
                    "slice_id": request.slice_id,
                    "workers": workers
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Security Groups en OpenStack no implementado aún"
            )
        
        if not result['success']:
            return SecurityGroupResponse(
                success=False,
                message=result.get('message', 'Error eliminando security group default'),
                zone=zona,
                slice_id=request.slice_id,
                error=result.get('error')
            )
        
        # Si exitoso en workers, sincronizar BD
        delete_default_sg_from_db(request.slice_id)
        
        data = result.get('data', {})
        return SecurityGroupResponse(
            success=data.get('success', False),
            message=data.get('message', 'Security Group default eliminado (BD actualizada)'),
            zone=zona,
            slice_id=request.slice_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en remove-default-security-group: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

# =============================================================================
# ENDPOINTS SECURITY GROUPS - OPENSTACK
# =============================================================================

@app.post("/security-groups-openstack/status", response_model=SecurityGroupStatusResponse)
async def get_sg_status_openstack(
    request: SecurityGroupStatusRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Obtener estado de los security groups de un slice en OpenStack
    """
    try:
        zona = request.zona_despliegue.lower()
        
        logger.info(f"Consultando estado de Security Groups del slice {request.slice_id} en OpenStack")
        
        if zona != 'openstack':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona '{zona}' no válida para endpoint OpenStack"
            )
        
        result = await call_security_api_openstack(
            "/status",
            method="POST",
            payload={"slice_id": request.slice_id}
        )
        
        if not result['success']:
            return SecurityGroupStatusResponse(
                success=False,
                message=result.get('message', 'Error consultando estado'),
                zone=zona,
                slice_id=request.slice_id,
                error=result.get('error')
            )
        
        data = result.get('data', {})
        return SecurityGroupStatusResponse(
            success=data.get('status') == 'success',
            message=data.get('message', 'Estado obtenido exitosamente'),
            zone=zona,
            slice_id=request.slice_id,
            security_groups=data.get('security_groups', []),
            project_id=data.get('project_id')
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en get-sg-status-openstack: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/security-groups-openstack/create-custom", response_model=SecurityGroupResponse)
async def create_custom_sg_openstack(
    request: CreateCustomSGRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Crear security group personalizado en OpenStack
    """
    try:
        zona = request.zona_despliegue.lower()
        
        logger.info(f"Creando Security Group custom '{request.nombre}' para slice {request.slice_id} en OpenStack")
        
        if zona != 'openstack':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona '{zona}' no válida para endpoint OpenStack"
            )
        
        # SIEMPRE crear primero en BD para obtener id_sg autogenerado
        # create_sg_in_db crea con nombre temporal, luego lo actualiza a SG_{id_sg}
        id_sg = create_sg_in_db(request.slice_id, request.descripcion)
        logger.info(f"SG creado en BD con ID autogenerado: {id_sg}, nombre: SG_{id_sg}")
        
        # Crear en OpenStack
        result = await call_security_api_openstack(
            "/create-custom",
            method="POST",
            payload={
                "slice_id": request.slice_id,
                "id_sg": id_sg
            }
        )
        
        if not result['success']:
            # Rollback: eliminar de BD
            delete_sg_from_db(id_sg)
            return SecurityGroupResponse(
                success=False,
                message=result.get('message', 'Error creando security group'),
                zone=zona,
                slice_id=request.slice_id,
                error=result.get('error')
            )
        
        data = result.get('data', {})
        
        if data.get('status') != 'success':
            # Rollback: eliminar de BD
            delete_sg_from_db(id_sg)
            return SecurityGroupResponse(
                success=False,
                message=data.get('message', 'Error en OpenStack'),
                zone=zona,
                slice_id=request.slice_id,
                error=data.get('message')
            )
        
        # Actualizar BD con las 2 reglas por defecto (egress IPv4 e IPv6)
        default_rules = data.get('default_rules', [])
        if default_rules:
            update_custom_sg_default_rules(id_sg, default_rules)
            logger.info(f"Reglas por defecto sincronizadas: {len(default_rules)} reglas (id:1 egress IPv4, id:2 egress IPv6)")
        
        return SecurityGroupResponse(
            success=True,
            message=data.get('message', f'Security Group {id_sg} creado (BD sincronizada con {len(default_rules)} reglas)'),
            zone=zona,
            slice_id=request.slice_id,
            id_sg=id_sg,
            sg_id=data.get('sg_id')
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en create-custom-sg-openstack: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/security-groups-openstack/add-rule", response_model=SecurityGroupResponse)
async def add_rule_to_sg_openstack(
    request: AddRuleRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Agregar regla a security group en OpenStack
    """
    try:
        zona = request.zona_despliegue.lower()
        
        logger.info(f"Agregando regla al SG del slice {request.slice_id} en OpenStack")
        
        if zona != 'openstack':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona '{zona}' no válida para endpoint OpenStack"
            )
        
        # Determinar nombre del SG
        if request.id_sg is not None:
            sg_name = f"SG_{request.id_sg}"
        else:
            sg_name = "default"
        
        # Obtener siguiente rule_id si no se proporciona
        if request.rule_id is None:
            rule_id = get_next_rule_id(request.slice_id, sg_name)
            logger.info(f"Próximo rule_id generado: {rule_id} para SG '{sg_name}'")
        else:
            rule_id = request.rule_id
        
        # Construir payload para OpenStack
        payload = {
            "slice_id": request.slice_id,
            "direction": request.direction,
            "ether_type": request.ether_type or "IPv4",
            "remote_ip_prefix": request.remote_ip_prefix or "0.0.0.0/0"
        }
        
        # Para SG personalizado: enviar id_sg (headnode construye el nombre SG_id{slice}_{id_sg})
        # Para SG default: enviar sg_name = "default"
        if request.id_sg is not None:
            payload["id_sg"] = request.id_sg
        else:
            payload["sg_name"] = "default"
        
        # Usar plantilla o valores directos
        if request.plantilla:
            payload["rule_template"] = request.plantilla
            if request.port_range:
                payload["port_range"] = request.port_range
        else:
            payload["protocol"] = request.protocol
            if request.port_range:
                payload["port_range"] = request.port_range
        
        if request.description:
            payload["description"] = request.description
        
        # Agregar en OpenStack
        result = await call_security_api_openstack(
            "/add-rule",
            method="POST",
            payload=payload
        )
        
        if not result['success']:
            return SecurityGroupResponse(
                success=False,
                message=result.get('message', 'Error agregando regla'),
                zone=zona,
                slice_id=request.slice_id,
                error=result.get('error')
            )
        
        data = result.get('data', {})
        
        if data.get('status') != 'success':
            return SecurityGroupResponse(
                success=False,
                message=data.get('message', 'Error en OpenStack'),
                zone=zona,
                slice_id=request.slice_id,
                error=data.get('message')
            )
        
        # Sincronizar en BD
        openstack_rule_uuid = data.get('rule_id')
        
        # Construir objeto de regla para BD
        rule_data = {
            "id": rule_id,  # add_rule_to_db espera campo 'id', no 'rule_id'
            "direction": request.direction,
            "protocol": request.protocol or "tcp",
            "port_range": request.port_range or "any",
            "remote_ip_prefix": request.remote_ip_prefix or "0.0.0.0/0",
            "ether_type": request.ether_type or "IPv4",
            "description": request.description or "",
            "id_openstack": openstack_rule_uuid  # Campo para OpenStack UUID
        }
        
        add_rule_to_db(request.slice_id, sg_name, rule_data)
        
        return SecurityGroupResponse(
            success=True,
            message=data.get('message', f'Regla {rule_id} agregada a {sg_name} (BD sincronizada)'),
            zone=zona,
            slice_id=request.slice_id,
            id_sg=request.id_sg,
            sg_id=data.get('sg_id')
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en add-rule-openstack: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/security-groups-openstack/remove-rule", response_model=SecurityGroupResponse)
async def remove_rule_from_sg_openstack(
    request: RemoveRuleRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Eliminar regla de security group en OpenStack
    
    Para OpenStack, el rule_id es el UUID de OpenStack, no el ID secuencial.
    La BD almacena el mapeo entre ID secuencial y UUID.
    """
    try:
        zona = request.zona_despliegue.lower()
        
        logger.info(f"Eliminando regla {request.rule_id} del slice {request.slice_id} en OpenStack")
        
        if zona != 'openstack':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona '{zona}' no válida para endpoint OpenStack"
            )
        
        # Determinar nombre del SG
        if request.id_sg is not None:
            sg_name = f"SG_{request.id_sg}"
        else:
            sg_name = None  # None = default SG
        
        # Obtener el UUID de OpenStack desde la BD
        openstack_uuid = get_openstack_rule_uuid(request.slice_id, sg_name, request.rule_id)
        
        if not openstack_uuid:
            return SecurityGroupResponse(
                success=False,
                message=f'Regla {request.rule_id} no encontrada en BD',
                zone=zona,
                slice_id=request.slice_id,
                error='Rule not found in database'
            )
        
        # Eliminar en OpenStack usando el UUID
        result = await call_security_api_openstack(
            "/remove-rule",
            method="POST",
            payload={
                "slice_id": request.slice_id,
                "rule_id": openstack_uuid
            }
        )
        
        if not result['success']:
            return SecurityGroupResponse(
                success=False,
                message=result.get('message', 'Error eliminando regla'),
                zone=zona,
                slice_id=request.slice_id,
                error=result.get('error')
            )
        
        data = result.get('data', {})
        
        if data.get('status') != 'success':
            return SecurityGroupResponse(
                success=False,
                message=data.get('message', 'Error en OpenStack'),
                zone=zona,
                slice_id=request.slice_id,
                error=data.get('message')
            )
        
        # Sincronizar en BD
        remove_rule_from_db(request.slice_id, sg_name, request.rule_id)
        
        return SecurityGroupResponse(
            success=True,
            message=data.get('message', f'Regla {request.rule_id} eliminada de {sg_name or "default"} (BD actualizada)'),
            zone=zona,
            slice_id=request.slice_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en remove-rule-openstack: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/security-groups-openstack/remove-custom", response_model=SecurityGroupResponse)
async def remove_custom_sg_openstack(
    request: RemoveCustomSGRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Eliminar security group personalizado de OpenStack
    """
    try:
        zona = request.zona_despliegue.lower()
        
        logger.info(f"Eliminando Security Group custom {request.id_sg} del slice {request.slice_id} en OpenStack")
        
        if zona != 'openstack':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona '{zona}' no válida para endpoint OpenStack"
            )
        
        result = await call_security_api_openstack(
            "/remove-custom",
            method="POST",
            payload={
                "slice_id": request.slice_id,
                "id_sg": request.id_sg
            }
        )
        
        if not result['success']:
            return SecurityGroupResponse(
                success=False,
                message=result.get('message', 'Error eliminando security group'),
                zone=zona,
                slice_id=request.slice_id,
                error=result.get('error')
            )
        
        data = result.get('data', {})
        
        if data.get('status') != 'success':
            return SecurityGroupResponse(
                success=False,
                message=data.get('message', 'Error en OpenStack'),
                zone=zona,
                slice_id=request.slice_id,
                error=data.get('message')
            )
        
        # Sincronizar en BD
        delete_sg_from_db(request.slice_id, request.id_sg)
        
        return SecurityGroupResponse(
            success=True,
            message=data.get('message', f'Security Group {request.id_sg} eliminado (BD actualizada)'),
            zone=zona,
            slice_id=request.slice_id,
            id_sg=request.id_sg
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en remove-custom-sg-openstack: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/security-groups-openstack/remove-default", response_model=SecurityGroupResponse)
async def remove_default_sg_openstack(
    request: RemoveDefaultSGRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Eliminar security group default de OpenStack de un slice
    
    ⚠️ ADVERTENCIA: Esto deja las VMs sin protección de firewall.
    Solo recomendado antes de eliminar el slice completo.
    """
    try:
        zona = request.zona_despliegue.lower()
        
        logger.warning(f"Eliminando Security Group DEFAULT del slice {request.slice_id} en OpenStack")
        
        if zona != 'openstack':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona '{zona}' no válida para endpoint OpenStack"
            )
        
        result = await call_security_api_openstack(
            "/remove-default",
            method="POST",
            payload={
                "slice_id": request.slice_id,
                "sg_name": "default"
            }
        )
        
        if not result['success']:
            return SecurityGroupResponse(
                success=False,
                message=result.get('message', 'Error eliminando security group default'),
                zone=zona,
                slice_id=request.slice_id,
                error=result.get('error')
            )
        
        data = result.get('data', {})
        
        if data.get('status') != 'success':
            return SecurityGroupResponse(
                success=False,
                message=data.get('message', 'Error en OpenStack'),
                zone=zona,
                slice_id=request.slice_id,
                error=data.get('message')
            )
        
        # Sincronizar en BD
        delete_default_sg_from_db(request.slice_id)
        
        return SecurityGroupResponse(
            success=True,
            message=data.get('message', 'Security Group default eliminado (BD actualizada)'),
            zone=zona,
            slice_id=request.slice_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en remove-default-sg-openstack: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

# ==================== ENDPOINT DE LIMPIEZA ====================

@app.delete("/security-groups-{zona}/slice/{slice_id}")
async def delete_all_security_groups_of_slice(
    zona: str,
    slice_id: int,
    authorized: bool = Depends(get_service_auth)
):
    """
    Eliminar TODOS los security groups de un slice (default + custom)
    Usado para limpieza completa al eliminar un slice
    """
    try:
        if zona not in ['linux', 'openstack']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona inválida: {zona}"
            )
        
        logger.info(f"Eliminando todos los security groups del slice {slice_id} en zona {zona}")
        
        # Conectar a BD
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener todos los security groups del slice
        cursor.execute(
            "SELECT id, name, is_default FROM security_groups WHERE slice_id = %s",
            (slice_id,)
        )
        security_groups = cursor.fetchall()
        
        if not security_groups:
            cursor.close()
            connection.close()
            return {
                "success": True,
                "message": f"No hay security groups para el slice {slice_id}",
                "deleted_count": 0
            }
        
        deleted_count = 0
        errors = []
        
        # Eliminar cada security group
        for sg in security_groups:
            sg_name = sg['name']
            is_default = sg['is_default']
            
            try:
                # Llamar al orquestador para eliminar
                if zona == 'linux':
                    # Para Linux: llamar a remove-custom o remove-default
                    endpoint = "/remove-default" if is_default else "/remove-custom"
                    response = call_security_api(endpoint, {"slice_id": slice_id, "nombre": sg_name})
                else:
                    # Para OpenStack: llamar a remove-custom o remove-default
                    endpoint = "/remove-default" if is_default else "/remove-custom"
                    response = call_security_api_openstack(endpoint, {"slice_id": slice_id, "nombre": sg_name})
                
                if response.get('status_code') != 200:
                    errors.append(f"Error eliminando {sg_name}: {response.get('error')}")
                    continue
                
                deleted_count += 1
                
            except Exception as e:
                errors.append(f"Error eliminando {sg_name}: {str(e)}")
        
        # Eliminar de BD
        cursor.execute("DELETE FROM security_groups WHERE slice_id = %s AND zona = %s", (slice_id, zona))
        connection.commit()
        cursor.close()
        connection.close()
        
        logger.info(f"Security groups eliminados: {deleted_count}/{len(security_groups)}")
        
        return {
            "success": True,
            "message": f"Security groups eliminados: {deleted_count}/{len(security_groups)}",
            "deleted_count": deleted_count,
            "total": len(security_groups),
            "errors": errors if errors else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error eliminando security groups del slice: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=6200, workers=2)

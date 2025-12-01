#!/usr/bin/env python3
"""
OpenStack Security Groups API
Puerto: 5811
Versión: 1.0

API para gestión de Security Groups en OpenStack.
Nomenclatura basada en chains para compatibilidad con implementación Linux.
"""

from fastapi import FastAPI, Body, HTTPException
from typing import Dict, Optional, List, Any
from security_openstack_sdk import (
    create_security_group,
    delete_security_group,
    list_security_groups,
    get_security_group_by_name,
    create_security_group_rule,
    delete_security_group_rule,
    get_security_group_details
)
from openstack_sf import get_admin_token, get_admin_token_for_project
import uvicorn
import requests

app = FastAPI(title="OpenStack Security Groups API", version="1.0")

# =============================================================================
# PLANTILLAS DE REGLAS (igual que en Linux)
# =============================================================================

RULE_TEMPLATES = {
    "CUSTOM_TCP": {"protocol": "tcp", "ether_type": "IPv4"},
    "CUSTOM_UDP": {"protocol": "udp", "ether_type": "IPv4"},
    "CUSTOM_ICMP": {"protocol": "icmp", "ether_type": "IPv4"},
    "ALL_TCP": {"protocol": "tcp", "port_min": 1, "port_max": 65535, "ether_type": "IPv4"},
    "ALL_UDP": {"protocol": "udp", "port_min": 1, "port_max": 65535, "ether_type": "IPv4"},
    "ALL_ICMP": {"protocol": "icmp", "ether_type": "IPv4"},
    "SSH": {"protocol": "tcp", "port_min": 22, "port_max": 22, "ether_type": "IPv4"},
    "HTTP": {"protocol": "tcp", "port_min": 80, "port_max": 80, "ether_type": "IPv4"},
    "HTTPS": {"protocol": "tcp", "port_min": 443, "port_max": 443, "ether_type": "IPv4"},
    "DNS": {"protocol": "udp", "port_min": 53, "port_max": 53, "ether_type": "IPv4"}
}

# =============================================================================
# FUNCIONES AUXILIARES
# =============================================================================

def get_project_id_from_slice(slice_id: str) -> Optional[str]:
    """Obtener project_id a partir del slice_id"""
    try:
        token = get_admin_token()
        headers = {'X-Auth-Token': token}
        url = 'http://192.168.202.1:5000/v3/projects'
        r = requests.get(url, headers=headers)
        
        if r.status_code == 200:
            projects = r.json()['projects']
            project_name = f"id{slice_id}_project"
            for p in projects:
                if p['name'] == project_name:
                    return p['id']
        return None
    except:
        return None


def get_default_sg_name(slice_id: str) -> str:
    """Nomenclatura para security group default (basada en chains)"""
    return f"SG_df_id{slice_id}"


def get_custom_sg_name(slice_id: str, id_sg: int) -> str:
    """Nomenclatura para security group personalizado"""
    return f"SG_id{slice_id}_{id_sg}"


def apply_template(rule_data: Dict) -> Dict:
    """Aplicar plantilla de regla"""
    template_name = rule_data.get("rule_template") or rule_data.get("plantilla")
    
    if not template_name:
        # Sin plantilla, usar valores directos
        result = {
            "protocol": rule_data.get("protocol"),
            "ether_type": rule_data.get("ether_type", "IPv4"),
            "port_min": None,
            "port_max": None
        }
        
        # Parsear port_range si existe
        port_range = rule_data.get("port_range", "any")
        if port_range != "any":
            if "-" in port_range or ":" in port_range:
                parts = port_range.replace("-", ":").split(":")
                result["port_min"] = int(parts[0])
                result["port_max"] = int(parts[1])
            else:
                result["port_min"] = int(port_range)
                result["port_max"] = int(port_range)
        
        return result
    
    # Aplicar plantilla
    template_name = template_name.upper()
    if template_name not in RULE_TEMPLATES:
        raise ValueError(f"Template '{template_name}' not found")
    
    template = RULE_TEMPLATES[template_name]
    result = {
        "protocol": template.get("protocol"),
        "ether_type": template.get("ether_type", "IPv4"),
        "port_min": template.get("port_min"),
        "port_max": template.get("port_max")
    }
    
    # Para CUSTOM_*, usar port_range del usuario
    if "CUSTOM_" in template_name:
        port_range = rule_data.get("port_range", "any")
        if port_range != "any":
            if "-" in port_range or ":" in port_range:
                parts = port_range.replace("-", ":").split(":")
                result["port_min"] = int(parts[0])
                result["port_max"] = int(parts[1])
            else:
                result["port_min"] = int(port_range)
                result["port_max"] = int(port_range)
    
    return result


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/")
async def root():
    return {"service": "OpenStack Security Groups API", "version": "1.0"}


@app.get("/templates")
async def list_templates():
    """Listar plantillas de reglas disponibles"""
    return {
        "templates": {
            "SSH": "TCP puerto 22",
            "HTTP": "TCP puerto 80",
            "HTTPS": "TCP puerto 443",
            "DNS": "UDP puerto 53",
            "ALL_TCP": "Todos los puertos TCP (1-65535)",
            "ALL_UDP": "Todos los puertos UDP (1-65535)",
            "ALL_ICMP": "Todo el tráfico ICMP",
            "CUSTOM_TCP": "TCP personalizado (especificar port_range)",
            "CUSTOM_UDP": "UDP personalizado (especificar port_range)",
            "CUSTOM_ICMP": "ICMP personalizado"
        }
    }


@app.post("/create-custom")
async def create_custom_sg(request: Dict = Body(...)):
    """
    Crear security group personalizado
    
    Body:
    {
        "slice_id": 5,
        "id_sg": 1
    }
    """
    try:
        slice_id = str(request.get("slice_id"))
        id_sg = int(request.get("id_sg"))
        
        project_id = get_project_id_from_slice(slice_id)
        if not project_id:
            return {"status": "error", "message": f"Slice {slice_id} not found"}
        
        # Crear security group
        token = get_admin_token_for_project(project_id)
        sg_name = get_custom_sg_name(slice_id, id_sg)
        sg_id = create_security_group(token, project_id, sg_name, f"Custom SG {id_sg} for slice {slice_id}")
        
        if sg_id:
            # Obtener las reglas por defecto creadas automáticamente
            sg_details = get_security_group_details(token, sg_id)
            default_rules = []
            
            if sg_details and 'security_group_rules' in sg_details:
                for rule in sg_details['security_group_rules']:
                    # Reglas egress creadas por defecto (sin remote_group_id específico para ingress)
                    if rule.get('direction') == 'egress':
                        rule_id = rule.get('id')
                        ethertype = rule.get('ethertype', 'IPv4')
                        # Formato: id:N;uuid:xxx donde N es 1 para IPv4, 2 para IPv6
                        rule_num = 1 if ethertype == 'IPv4' else 2
                        default_rules.append(f"id:{rule_num};uuid:{rule_id}")
            
            # Ordenar para consistencia (id:1 antes de id:2)
            default_rules.sort()
            
            return {
                "status": "success", 
                "message": f"Created {sg_name}", 
                "sg_id": sg_id,
                "default_rules": default_rules
            }
        else:
            return {"status": "error", "message": "Failed to create SG"}
            
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/remove-default")
async def remove_default_sg(request: Dict = Body(...)):
    """
    Eliminar security group default
    
    Body:
    {
        "slice_id": 5,
        "sg_name": "default"  // Opcional, por defecto usa "default"
    }
    
    Nota: OpenStack crea un SG "default" automáticamente por proyecto.
    """
    try:
        slice_id = str(request.get("slice_id"))
        sg_name = request.get("sg_name", "default")
        
        project_id = get_project_id_from_slice(slice_id)
        if not project_id:
            return {"status": "error", "message": f"Slice {slice_id} not found"}
        
        token = get_admin_token_for_project(project_id)
        
        # Buscar el SG por nombre
        sg = get_security_group_by_name(token, project_id, sg_name)
        if not sg:
            return {"status": "error", "message": f"SG {sg_name} not found"}
        
        # Eliminar
        if delete_security_group(token, sg['id']):
            return {"status": "success", "message": f"Deleted {sg_name}"}
        else:
            return {"status": "error", "message": "Failed to delete SG"}
            
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/remove-custom")
async def remove_custom_sg(request: Dict = Body(...)):
    """
    Eliminar security group personalizado
    
    Body:
    {
        "slice_id": 5,
        "id_sg": 1
    }
    """
    try:
        slice_id = str(request.get("slice_id"))
        id_sg = int(request.get("id_sg"))
        
        project_id = get_project_id_from_slice(slice_id)
        if not project_id:
            return {"status": "error", "message": f"Slice {slice_id} not found"}
        
        token = get_admin_token_for_project(project_id)
        sg_name = get_custom_sg_name(slice_id, id_sg)
        
        # Buscar el SG por nombre
        sg = get_security_group_by_name(token, project_id, sg_name)
        if not sg:
            return {"status": "error", "message": f"SG {sg_name} not found"}
        
        # Eliminar
        if delete_security_group(token, sg['id']):
            return {"status": "success", "message": f"Deleted {sg_name}"}
        else:
            return {"status": "error", "message": "Failed to delete SG"}
            
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/add-rule")
async def add_rule_to_sg(request: Dict = Body(...)):
    """
    Agregar regla a security group
    
    Body:
    {
        "slice_id": 5,
        "id_sg": 1,              // None o ausente = default SG
        "rule_template": "SSH",  // O "plantilla": "SSH"
        "direction": "ingress",  // o "egress"
        "ether_type": "IPv4",
        "protocol": "tcp",       // Ignorado si se usa plantilla
        "port_range": "22",      // Para CUSTOM_*, especificar puerto
        "remote_ip_prefix": "0.0.0.0/0",
        "description": "Allow SSH"
    }
    
    Plantillas disponibles: SSH, HTTP, HTTPS, DNS, ALL_TCP, ALL_UDP, ALL_ICMP, 
                           CUSTOM_TCP, CUSTOM_UDP, CUSTOM_ICMP
    """
    try:
        slice_id = str(request.get("slice_id"))
        id_sg = request.get("id_sg")
        sg_name_param = request.get("sg_name")
        direction = request.get("direction", "ingress").lower()
        
        # Convertir INPUT/OUTPUT a ingress/egress
        if direction == "input":
            direction = "ingress"
        elif direction == "output":
            direction = "egress"
        
        project_id = get_project_id_from_slice(slice_id)
        if not project_id:
            return {"status": "error", "message": f"Slice {slice_id} not found"}
        
        token = get_admin_token_for_project(project_id)
        
        # Determinar nombre del SG
        if sg_name_param:
            # Si se proporciona sg_name directamente, usarlo
            sg_name = sg_name_param
        elif id_sg is None:
            sg_name = get_default_sg_name(slice_id)
        else:
            sg_name = get_custom_sg_name(slice_id, int(id_sg))
        
        # Buscar el SG
        sg = get_security_group_by_name(token, project_id, sg_name)
        if not sg:
            return {"status": "error", "message": f"SG {sg_name} not found"}
        
        # Aplicar plantilla
        rule_config = apply_template(request)
        
        # Crear regla
        rule_id = create_security_group_rule(
            token=token,
            sg_id=sg['id'],
            direction=direction,
            ether_type=rule_config["ether_type"],
            protocol=rule_config["protocol"],
            port_range_min=rule_config["port_min"],
            port_range_max=rule_config["port_max"],
            remote_ip_prefix=request.get("remote_ip_prefix"),
            remote_group_id=request.get("remote_security_group"),
            description=request.get("description", "")
        )
        
        if rule_id:
            return {"status": "success", "message": f"Rule added to {sg_name}", "rule_id": rule_id}
        else:
            return {"status": "error", "message": "Failed to add rule"}
            
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/remove-rule")
async def remove_rule_from_sg(request: Dict = Body(...)):
    """
    Eliminar regla de security group
    
    Body:
    {
        "slice_id": 5,
        "id_sg": 1,        // None o ausente = default SG
        "rule_id": "uuid-de-la-regla",
        "direction": "ingress"
    }
    
    Nota: rule_id es el UUID de OpenStack, no un número secuencial.
    Usa /status para ver los UUIDs de las reglas.
    """
    try:
        slice_id = str(request.get("slice_id"))
        rule_id = request.get("rule_id")
        
        if not rule_id:
            return {"status": "error", "message": "rule_id is required"}
        
        project_id = get_project_id_from_slice(slice_id)
        if not project_id:
            return {"status": "error", "message": f"Slice {slice_id} not found"}
        
        token = get_admin_token_for_project(project_id)
        
        # Eliminar regla
        if delete_security_group_rule(token, rule_id):
            return {"status": "success", "message": "Rule deleted"}
        else:
            return {"status": "error", "message": "Failed to delete rule"}
            
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/status")
async def get_sg_status(request: Dict = Body(...)):
    """
    Obtener estado de security groups de un slice
    
    Body:
    {
        "slice_id": 5
    }
    """
    try:
        slice_id = str(request.get("slice_id"))
        
        project_id = get_project_id_from_slice(slice_id)
        if not project_id:
            return {"status": "error", "message": f"Slice {slice_id} not found"}
        
        token = get_admin_token_for_project(project_id)
        sgs = list_security_groups(token, project_id)
        
        result = []
        for sg in sgs:
            result.append({
                "name": sg['name'],
                "id": sg['id'],
                "description": sg.get('description', ''),
                "rules_count": len(sg.get('security_group_rules', []))
            })
        
        return {
            "status": "success",
            "slice_id": slice_id,
            "project_id": project_id,
            "security_groups": result
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/sg-details/{slice_id}/{sg_name}")
async def get_sg_details(slice_id: str, sg_name: str):
    """
    Obtener detalles completos de un security group con todas sus reglas
    
    Params:
        slice_id: ID del slice
        sg_name: Nombre del SG (ej: "SG_df_id5" o "SG_id5_1")
    """
    try:
        project_id = get_project_id_from_slice(slice_id)
        if not project_id:
            return {"status": "error", "message": f"Slice {slice_id} not found"}
        
        token = get_admin_token_for_project(project_id)
        sg = get_security_group_by_name(token, project_id, sg_name)
        
        if not sg:
            return {"status": "error", "message": f"SG {sg_name} not found"}
        
        # Formatear reglas
        rules = []
        for rule in sg.get('security_group_rules', []):
            rules.append({
                "id": rule['id'],
                "direction": rule['direction'],
                "ethertype": rule['ethertype'],
                "protocol": rule.get('protocol', 'any'),
                "port_range_min": rule.get('port_range_min'),
                "port_range_max": rule.get('port_range_max'),
                "remote_ip_prefix": rule.get('remote_ip_prefix', 'any'),
                "description": rule.get('description', '')
            })
        
        return {
            "status": "success",
            "sg_name": sg['name'],
            "sg_id": sg['id'],
            "description": sg.get('description', ''),
            "rules": rules
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5811)

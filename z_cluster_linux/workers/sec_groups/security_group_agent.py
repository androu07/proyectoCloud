#!/usr/bin/env python3
"""
Security Group Agent - Servicio independiente para aplicación de reglas de firewall
Puerto: 5810
Versión: 1.0

Este agente corre en cada worker y aplica security groups de forma asíncrona,
sin bloquear el flujo de despliegue de VMs del orquestador.
"""

from fastapi import FastAPI, HTTPException, status, Request
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import asyncio
import subprocess
import logging
import os
import json
from datetime import datetime
import traceback

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [SG-Agent] - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/security_group_agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Security Group Agent",
    version="1.0.0",
    description="Agente independiente para aplicación de reglas de firewall en workers"
)

# =============================================================================
# MODELOS
# =============================================================================

class SecurityRule(BaseModel):
    """Modelo para reglas de security group personalizadas"""
    direction: str  # ingress o egress
    ether_type: str = "IPv4"  # IPv4 o IPv6
    protocol: str = "any"  # tcp, udp, icmp, any
    port_range: str = "any"  # "22", "80-443", "any"
    remote_ip_prefix: Optional[str] = None  # "0.0.0.0/0", "192.168.1.0/24"
    description: str = ""

class ApplyDefaultSGRequest(BaseModel):
    """Petición para aplicar security group por defecto"""
    slice_id: int
    tap_interfaces: List[str]  # Ejemplo: ["tap00", "tap01"]

class ApplyCustomSGRequest(BaseModel):
    """Petición para aplicar security group personalizado"""
    slice_id: int
    tap_interfaces: List[str]
    rules: List[SecurityRule]

class RemoveSGRequest(BaseModel):
    """Petición para remover security group"""
    slice_id: int

class VMOperationRequest(BaseModel):
    """Petición para operaciones sobre VMs de un slice"""
    slice_id: int

class CustomSGRequest(BaseModel):
    """Petición para security group personalizado"""
    slice_id: int
    id_sg: int

class AddRuleRequest(BaseModel):
    """Petición para agregar regla a security group"""
    slice_id: int
    id_sg: Optional[int] = None  # None = default SG
    rule_id: int
    rule_template: Optional[str] = None  # Plantilla: SSH, HTTP, HTTPS, DNS, etc.
    direction: str  # ingress o egress
    ether_type: str = "IPv4"
    protocol: str = "any"
    port_range: str = "any"
    remote_ip_prefix: Optional[str] = None
    remote_security_group: Optional[str] = None
    icmp_type: Optional[str] = None  # Para ICMP
    icmp_code: Optional[str] = None  # Para ICMP
    description: str = ""

class RemoveRuleRequest(BaseModel):
    """Petición para remover regla específica"""
    slice_id: int
    id_sg: Optional[int] = None  # None = default SG
    rule_id: int

# =============================================================================
# PLANTILLAS DE REGLAS
# =============================================================================

RULE_TEMPLATES = {
    # Plantillas personalizadas (usuario provee puertos)
    "CUSTOM_TCP": {
        "protocol": "tcp",
        "ether_type": "IPv4"
    },
    "CUSTOM_UDP": {
        "protocol": "udp",
        "ether_type": "IPv4"
    },
    "CUSTOM_ICMP": {
        "protocol": "icmp",
        "ether_type": "IPv4"
    },
    
    # Plantillas "ALL" (todos los puertos)
    "ALL_TCP": {
        "protocol": "tcp",
        "port_range": "1:65535",
        "ether_type": "IPv4"
    },
    "ALL_UDP": {
        "protocol": "udp",
        "port_range": "1:65535",
        "ether_type": "IPv4"
    },
    "ALL_ICMP": {
        "protocol": "icmp",
        "ether_type": "IPv4"
    },
    
    # Plantillas predefinidas con puertos específicos
    "SSH": {
        "protocol": "tcp",
        "port_range": "22",
        "ether_type": "IPv4"
    },
    "HTTP": {
        "protocol": "tcp",
        "port_range": "80",
        "ether_type": "IPv4"
    },
    "HTTPS": {
        "protocol": "tcp",
        "port_range": "443",
        "ether_type": "IPv4"
    },
    "DNS": {
        "protocol": "udp",
        "port_range": "53",
        "ether_type": "IPv4"
    }
}

def apply_rule_template(request: AddRuleRequest) -> Dict[str, Any]:
    """
    Aplicar plantilla de regla y auto-completar campos
    
    Args:
        request: Petición de agregar regla
    
    Returns:
        Dict con campos completados según plantilla
    """
    # Si no hay plantilla, usar valores del request tal cual
    if not request.rule_template:
        return {
            "protocol": request.protocol,
            "port_range": request.port_range,
            "ether_type": request.ether_type,
            "icmp_type": request.icmp_type,
            "icmp_code": request.icmp_code
        }
    
    # Validar que la plantilla existe
    template_name = request.rule_template.upper()
    if template_name not in RULE_TEMPLATES:
        raise ValueError(f"Plantilla '{request.rule_template}' no existe. Plantillas disponibles: {list(RULE_TEMPLATES.keys())}")
    
    template = RULE_TEMPLATES[template_name]
    
    # Aplicar valores de la plantilla
    result = {
        "protocol": template.get("protocol", request.protocol),
        "ether_type": template.get("ether_type", request.ether_type),
        "icmp_type": request.icmp_type,
        "icmp_code": request.icmp_code
    }
    
    # Para port_range:
    # - Si la plantilla define port_range (ej: SSH=22), usar ese
    # - Si es CUSTOM_*, usar el port_range que provee el usuario
    if "port_range" in template:
        result["port_range"] = template["port_range"]
    else:
        result["port_range"] = request.port_range
    
    return result

# =============================================================================
# FUNCIONES AUXILIARES - IPTABLES
# =============================================================================

async def run_iptables_command(command: str) -> Dict[str, Any]:
    """
    Ejecutar comando iptables de forma asíncrona
    
    Args:
        command: Comando iptables a ejecutar (sin 'sudo')
    
    Returns:
        Dict con success, output y error
    """
    try:
        full_command = f"sudo {command}"
        logger.debug(f"Ejecutando: {full_command}")
        
        process = await asyncio.create_subprocess_shell(
            full_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        return {
            'success': process.returncode == 0,
            'returncode': process.returncode,
            'stdout': stdout.decode().strip(),
            'stderr': stderr.decode().strip()
        }
        
    except Exception as e:
        logger.error(f"Error ejecutando iptables: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

async def chain_exists(chain_name: str) -> bool:
    """Verificar si una cadena iptables existe"""
    result = await run_iptables_command(f"iptables -L {chain_name} -n 2>/dev/null")
    return result['success']

async def create_chains(chain_input: str, chain_output: str) -> Dict[str, Any]:
    """Crear cadenas personalizadas"""
    # Crear cadenas si no existen
    await run_iptables_command(f"iptables -N {chain_input} 2>/dev/null || true")
    await run_iptables_command(f"iptables -N {chain_output} 2>/dev/null || true")
    
    # Limpiar reglas anteriores
    await run_iptables_command(f"iptables -F {chain_input}")
    await run_iptables_command(f"iptables -F {chain_output}")
    
    return {
        'chain_input': chain_input,
        'chain_output': chain_output
    }

async def link_tap_to_chains(tap_name: str, chain_input: str, chain_output: str) -> bool:
    """Vincular interfaz TAP a cadenas de security group (IPv4 e IPv6)"""
    try:
        # IPv4 - Eliminar vínculos anteriores si existen
        await run_iptables_command(f"iptables -D FORWARD -i {tap_name} -j {chain_input} 2>/dev/null || true")
        await run_iptables_command(f"iptables -D FORWARD -o {tap_name} -j {chain_output} 2>/dev/null || true")
        
        # IPv4 - Agregar nuevos vínculos
        result_in = await run_iptables_command(f"iptables -I FORWARD -i {tap_name} -j {chain_input}")
        result_out = await run_iptables_command(f"iptables -I FORWARD -o {tap_name} -j {chain_output}")
        
        # IPv6 - Eliminar vínculos anteriores si existen
        await run_iptables_command(f"ip6tables -D FORWARD -i {tap_name} -j {chain_input} 2>/dev/null || true")
        await run_iptables_command(f"ip6tables -D FORWARD -o {tap_name} -j {chain_output} 2>/dev/null || true")
        
        # IPv6 - Agregar nuevos vínculos
        result_in_v6 = await run_iptables_command(f"ip6tables -I FORWARD -i {tap_name} -j {chain_input}")
        result_out_v6 = await run_iptables_command(f"ip6tables -I FORWARD -o {tap_name} -j {chain_output}")
        
        return result_in['success'] and result_out['success'] and result_in_v6['success'] and result_out_v6['success']
        
    except Exception as e:
        logger.error(f"Error vinculando {tap_name}: {str(e)}")
        return False

async def verify_tap_exists(tap_name: str) -> bool:
    """Verificar que la interfaz TAP existe en el sistema"""
    try:
        result = await run_iptables_command(f"ip link show {tap_name}")
        return result['success']
    except:
        return False

async def get_tap_interfaces_for_slice(slice_id: int) -> List[str]:
    """Obtener todas las interfaces TAP de un slice"""
    try:
        result = await run_iptables_command("ip link show")
        if not result['success']:
            return []
        
        tap_interfaces = []
        pattern = f"id{slice_id}-"
        
        for line in result['stdout'].split('\n'):
            if pattern in line and '-t' in line:
                # Extraer nombre de interfaz
                parts = line.split(':')
                if len(parts) >= 2:
                    iface_name = parts[1].strip().split('@')[0]
                    if iface_name.startswith(pattern):
                        tap_interfaces.append(iface_name)
        
        return tap_interfaces
    except Exception as e:
        logger.error(f"Error obteniendo interfaces TAP del slice {slice_id}: {str(e)}")
        return []

def build_iptables_rule(chain: str, rule_id: int, direction: str, ether_type: str, 
                       protocol: str, port_range: str, remote_ip_prefix: Optional[str],
                       remote_security_group: Optional[str], tap_interfaces: List[str],
                       icmp_type: Optional[str] = None, icmp_code: Optional[str] = None) -> str:
    """Construir regla de iptables con comentario de rule_id"""
    
    # Base de la regla con comentario
    rule = f"iptables -A {chain} -m comment --comment \"rule_id:{rule_id}\""
    
    # Protocolo
    if protocol != "any":
        if protocol in ["tcp", "udp", "icmp"]:
            rule += f" -p {protocol}"
    
    # Puerto (solo para tcp/udp)
    if protocol in ["tcp", "udp"] and port_range != "any":
        if ":" in port_range:  # Rango de puertos
            rule += f" --dport {port_range}"
        else:  # Puerto único
            rule += f" --dport {port_range}"
    
    # ICMP type y code (solo para icmp)
    if protocol == "icmp":
        if icmp_type:
            rule += f" --icmp-type {icmp_type}"
            if icmp_code:
                rule += f"/{icmp_code}"
    
    # Dirección IP origen/destino
    if direction == "ingress":
        # Para ingress, source es el origen del tráfico
        if remote_ip_prefix:
            rule += f" -s {remote_ip_prefix}"
        elif remote_security_group:
            # Si viene del mismo security group, permitir desde las interfaces TAP
            # Esto se maneja de forma especial
            pass
    else:  # egress
        # Para egress, destination es el destino del tráfico
        if remote_ip_prefix:
            rule += f" -d {remote_ip_prefix}"
    
    # Acción
    rule += " -j ACCEPT"
    
    return rule

async def find_rule_by_id(chain: str, rule_id: int) -> Optional[int]:
    """Encontrar número de línea de una regla por su rule_id en comentario"""
    try:
        result = await run_iptables_command(f"iptables -L {chain} --line-numbers -n")
        if not result['success']:
            return None
        
        # Buscar línea con el comentario
        for line in result['stdout'].split('\n'):
            if f"rule_id:{rule_id}" in line:
                parts = line.split()
                if parts and parts[0].isdigit():
                    return int(parts[0])
        
        return None
    except Exception as e:
        logger.error(f"Error buscando regla {rule_id} en {chain}: {str(e)}")
        return None

# =============================================================================
# LÓGICA DE SECURITY GROUPS
# =============================================================================

async def create_default_security_group(slice_id: int, tap_interfaces: List[str]) -> Dict[str, Any]:
    """
    Aplicar security group por defecto a interfaces TAP específicas
    
    Reglas por defecto (como OpenStack):
    - EGRESS: Permitir TODO el tráfico saliente (IPv4/IPv6)
    - INGRESS: Solo desde otras VMs del mismo Security Group + ESTABLISHED/RELATED
    
    Args:
        slice_id: ID del slice
        tap_interfaces: Lista de interfaces TAP (ej: ["tap00", "tap01"])
    
    Returns:
        Dict con resultado de la aplicación
    """
    steps = []
    start_time = datetime.now()
    
    try:
        logger.info(f"Creando Security Group Default para slice {slice_id}, interfaces: {tap_interfaces}")
        
        # 1. Crear/limpiar cadenas con formato DEFAULT (IPv4 e IPv6)
        chain_input = f"SG_df_id{slice_id}_INPUT"
        chain_output = f"SG_df_id{slice_id}_OUTPUT"
        chains = await create_chains(chain_input, chain_output)
        chain_input = chains['chain_input']
        chain_output = chains['chain_output']
        steps.append(f"Cadenas {chain_input} y {chain_output} preparadas (IPv4)")
        
        # Crear cadenas IPv6 también
        await run_iptables_command(f"ip6tables -N {chain_input} 2>/dev/null || true")
        await run_iptables_command(f"ip6tables -F {chain_input} 2>/dev/null || true")
        await run_iptables_command(f"ip6tables -N {chain_output} 2>/dev/null || true")
        await run_iptables_command(f"ip6tables -F {chain_output} 2>/dev/null || true")
        steps.append(f"Cadenas {chain_input} y {chain_output} preparadas (IPv6)")
        
        # 2. Vincular interfaces TAP a las cadenas (IPv4 e IPv6)
        linked_interfaces = []
        failed_interfaces = []
        
        for tap in tap_interfaces:
            # Verificar que la interfaz existe
            if not await verify_tap_exists(tap):
                logger.warning(f"Interfaz {tap} no existe todavía, reintentando en 2s...")
                await asyncio.sleep(2)  # Esperar a que la VM termine de arrancar
                
                if not await verify_tap_exists(tap):
                    failed_interfaces.append({'tap': tap, 'reason': 'interface_not_found'})
                    continue
            
            # Vincular interfaz
            if await link_tap_to_chains(tap, chain_input, chain_output):
                linked_interfaces.append(tap)
            else:
                failed_interfaces.append({'tap': tap, 'reason': 'link_failed'})
        
        if not linked_interfaces:
            return {
                'success': False,
                'message': 'No se pudo vincular ninguna interfaz TAP',
                'details': {
                    'failed_interfaces': failed_interfaces,
                    'steps': steps
                }
            }
        
        steps.append(f"Vinculadas {len(linked_interfaces)}/{len(tap_interfaces)} interfaces TAP")
        
        # 3. REGLAS DE EGRESS (Salida) - PERMITIR TODO
        # Regla ID 1: Egress IPv4 (según BD)
        await run_iptables_command(f"iptables -A {chain_output} -m comment --comment \"rule_id:1\" -d 0.0.0.0/0 -j ACCEPT")
        steps.append("EGRESS: Permitido TODO tráfico saliente IPv4 (rule_id:1)")
        
        # Regla ID 2: Egress IPv6 (según BD)
        await run_iptables_command(f"ip6tables -A {chain_output} -m comment --comment \"rule_id:2\" -d ::/0 -j ACCEPT")
        steps.append("EGRESS: Permitido TODO tráfico saliente IPv6 (rule_id:2)")
        
        # 4. REGLAS DE INGRESS (Entrada) - SOLO del mismo Security Group
        # Regla ID 3: Ingress mismo grupo IPv4 (según BD)
        # Permitir tráfico entre interfaces del mismo slice
        for tap in linked_interfaces:
            # Permitir tráfico desde cualquier interfaz del mismo slice
            await run_iptables_command(f"iptables -A {chain_input} -m comment --comment \"rule_id:3\" -i {tap} -j ACCEPT")
        
        steps.append(f"INGRESS: Permitido tráfico entre VMs del slice ({len(linked_interfaces)} interfaces) (rule_id:3)")
        
        # Regla ID 4: Ingress mismo grupo IPv6 (según BD)
        for tap in linked_interfaces:
            await run_iptables_command(f"ip6tables -A {chain_input} -m comment --comment \"rule_id:4\" -i {tap} -j ACCEPT")
        
        steps.append(f"INGRESS: Permitido tráfico entre VMs del slice IPv6 ({len(linked_interfaces)} interfaces) (rule_id:4)")
        
        # 5. Permitir tráfico ESTABLISHED y RELATED (respuestas de conexiones salientes)
        # Esta es una regla implícita del sistema, no tiene rule_id en BD
        await run_iptables_command(f"iptables -A {chain_input} -m comment --comment \"rule_id:system_established\" -m state --state ESTABLISHED,RELATED -j ACCEPT")
        steps.append("INGRESS: Permitido tráfico ESTABLISHED,RELATED (system)")
        
        # 6. DENEGAR todo lo demás en INGRESS
        # Esta es una regla implícita del sistema, no tiene rule_id en BD
        await run_iptables_command(f"iptables -A {chain_input} -m comment --comment \"rule_id:system_drop\" -j DROP")
        steps.append("INGRESS: Denegado tráfico externo al Security Group (system)")
        
        elapsed_time = (datetime.now() - start_time).total_seconds()
        
        logger.info(f"Security Group Default aplicado a slice {slice_id} en {elapsed_time:.2f}s")
        
        return {
            'success': True,
            'message': f'Security Group Default aplicado a slice {slice_id}',
            'details': {
                'slice_id': slice_id,
                'security_group': 'default',
                'policy': {
                    'egress': 'ALLOW ALL (IPv4/IPv6)',
                    'ingress': 'ALLOW from same Security Group + ESTABLISHED/RELATED'
                },
                'linked_interfaces': linked_interfaces,
                'failed_interfaces': failed_interfaces,
                'total_interfaces': len(tap_interfaces),
                'execution_time_seconds': round(elapsed_time, 2),
                'steps': steps
            }
        }
        
    except Exception as e:
        logger.error(f"Error aplicando Security Group Default a slice {slice_id}: {str(e)}\n{traceback.format_exc()}")
        return {
            'success': False,
            'message': f'Error interno: {str(e)}',
            'details': {'error': 'internal_error', 'steps': steps}
        }

async def remove_default_security_group(slice_id: int) -> Dict[str, Any]:
    """
    Remover security group de un slice (limpiar cadenas y reglas)
    
    Args:
        slice_id: ID del slice
    
    Returns:
        Dict con resultado de la operación
    """
    try:
        logger.info(f"Removiendo Security Group Default del slice {slice_id}")
        
        chain_input = f"SG_df_id{slice_id}_INPUT"
        chain_output = f"SG_df_id{slice_id}_OUTPUT"
        steps = []
        
        # 1. Verificar si las cadenas existen
        if not await chain_exists(chain_input) and not await chain_exists(chain_output):
            return {
                'success': True,
                'message': f'Security Group del slice {slice_id} no existía',
                'details': {'already_removed': True}
            }
        
        # 2. Obtener lista de reglas en FORWARD que referencian nuestras cadenas (IPv4)
        result = await run_iptables_command("iptables -L FORWARD --line-numbers -n")
        if result['success']:
            lines = result['stdout'].split('\n')
            # Recopilar números de línea a eliminar (de mayor a menor para no cambiar índices)
            lines_to_delete = []
            for line in lines:
                if chain_input in line or chain_output in line:
                    parts = line.split()
                    if parts and parts[0].isdigit():
                        lines_to_delete.append(int(parts[0]))
            
            # Eliminar de mayor a menor
            for line_num in sorted(lines_to_delete, reverse=True):
                await run_iptables_command(f"iptables -D FORWARD {line_num}")
        
        # 2b. Obtener lista de reglas en FORWARD que referencian nuestras cadenas (IPv6)
        result_v6 = await run_iptables_command("ip6tables -L FORWARD --line-numbers -n")
        if result_v6['success']:
            lines = result_v6['stdout'].split('\n')
            lines_to_delete = []
            for line in lines:
                if chain_input in line or chain_output in line:
                    parts = line.split()
                    if parts and parts[0].isdigit():
                        lines_to_delete.append(int(parts[0]))
            
            for line_num in sorted(lines_to_delete, reverse=True):
                await run_iptables_command(f"ip6tables -D FORWARD {line_num}")
        
        steps.append("Referencias en FORWARD eliminadas (IPv4 e IPv6)")
        
        # 3. Limpiar cadenas IPv4
        await run_iptables_command(f"iptables -F {chain_input} 2>/dev/null || true")
        await run_iptables_command(f"iptables -F {chain_output} 2>/dev/null || true")
        
        # 3b. Limpiar cadenas IPv6
        await run_iptables_command(f"ip6tables -F {chain_input} 2>/dev/null || true")
        await run_iptables_command(f"ip6tables -F {chain_output} 2>/dev/null || true")
        steps.append("Cadenas limpiadas (IPv4 e IPv6)")
        
        # 4. Eliminar cadenas IPv4
        await run_iptables_command(f"iptables -X {chain_input} 2>/dev/null || true")
        await run_iptables_command(f"iptables -X {chain_output} 2>/dev/null || true")
        
        # 4b. Eliminar cadenas IPv6
        await run_iptables_command(f"ip6tables -X {chain_input} 2>/dev/null || true")
        await run_iptables_command(f"ip6tables -X {chain_output} 2>/dev/null || true")
        steps.append("Cadenas eliminadas (IPv4 e IPv6)")
        
        logger.info(f"Security Group Default del slice {slice_id} removido exitosamente")
        
        return {
            'success': True,
            'message': f'Security Group Default del slice {slice_id} removido',
            'details': {
                'slice_id': slice_id,
                'steps': steps
            }
        }
        
    except Exception as e:
        logger.error(f"Error removiendo Security Group Default del slice {slice_id}: {str(e)}")
        return {
            'success': False,
            'message': f'Error interno: {str(e)}',
            'details': {'error': 'internal_error'}
        }

async def create_custom_security_group(slice_id: int, id_sg: int, tap_interfaces: List[str]) -> Dict[str, Any]:
    """
    Crear security group personalizado para un slice
    Formato: SG{id_sg}_id{slice_id}_INPUT/OUTPUT
    """
    steps = []
    start_time = datetime.now()
    
    try:
        logger.info(f"Creando Security Group {id_sg} para slice {slice_id}, interfaces: {tap_interfaces}")
        
        # 1. Crear/limpiar cadenas con formato CUSTOM (IPv4 e IPv6)
        chain_input = f"SG{id_sg}_id{slice_id}_INPUT"
        chain_output = f"SG{id_sg}_id{slice_id}_OUTPUT"
        chains = await create_chains(chain_input, chain_output)
        chain_input = chains['chain_input']
        chain_output = chains['chain_output']
        steps.append(f"Cadenas {chain_input} y {chain_output} preparadas (IPv4)")
        
        # Crear cadenas IPv6 también
        await run_iptables_command(f"ip6tables -N {chain_input} 2>/dev/null || true")
        await run_iptables_command(f"ip6tables -F {chain_input} 2>/dev/null || true")
        await run_iptables_command(f"ip6tables -N {chain_output} 2>/dev/null || true")
        await run_iptables_command(f"ip6tables -F {chain_output} 2>/dev/null || true")
        steps.append(f"Cadenas {chain_input} y {chain_output} preparadas (IPv6)")
        
        # 2. Vincular interfaces TAP a las cadenas (IPv4 e IPv6)
        linked_interfaces = []
        failed_interfaces = []
        
        for tap in tap_interfaces:
            # Verificar que la interfaz existe
            if not await verify_tap_exists(tap):
                logger.warning(f"Interfaz {tap} no existe todavía, reintentando en 2s...")
                await asyncio.sleep(2)
                
                if not await verify_tap_exists(tap):
                    failed_interfaces.append({'tap': tap, 'reason': 'interface_not_found'})
                    continue
            
            # Vincular interfaz
            if await link_tap_to_chains(tap, chain_input, chain_output):
                linked_interfaces.append(tap)
            else:
                failed_interfaces.append({'tap': tap, 'reason': 'link_failed'})
        
        if not linked_interfaces:
            return {
                'success': False,
                'message': 'No se pudo vincular ninguna interfaz TAP',
                'details': {
                    'failed_interfaces': failed_interfaces,
                    'steps': steps
                }
            }
        
        steps.append(f"Vinculadas {len(linked_interfaces)}/{len(tap_interfaces)} interfaces TAP")
        
        # 3. Security Groups personalizados vienen con SOLO 2 reglas por defecto (egress IPv4/IPv6)
        # El usuario agregará las reglas de ingress que necesite mediante /add-rule
        
        # REGLAS DE EGRESS (Salida) - PERMITIR TODO
        # Regla ID 1: Egress IPv4
        await run_iptables_command(f"iptables -A {chain_output} -m comment --comment \"rule_id:1\" -d 0.0.0.0/0 -j ACCEPT")
        steps.append("EGRESS: Permitido TODO tráfico saliente IPv4 (rule_id:1)")
        
        # Regla ID 2: Egress IPv6
        await run_iptables_command(f"ip6tables -A {chain_output} -m comment --comment \"rule_id:2\" -d ::/0 -j ACCEPT")
        steps.append("EGRESS: Permitido TODO tráfico saliente IPv6 (rule_id:2)")
        
        # 4. REGLAS DE INGRESS (Entrada) - Vacías por defecto
        # El usuario debe agregar reglas personalizadas con /add-rule
        # Solo agregamos las reglas del sistema
        
        # Crear cadena INPUT para IPv6 (vacía)
        await run_iptables_command(f"ip6tables -N {chain_input} 2>/dev/null || true")
        await run_iptables_command(f"ip6tables -F {chain_input} 2>/dev/null || true")
        
        # Permitir ESTABLISHED y RELATED (regla del sistema)
        await run_iptables_command(f"iptables -A {chain_input} -m comment --comment \"rule_id:system_established\" -m state --state ESTABLISHED,RELATED -j ACCEPT")
        steps.append("INGRESS: Permitido tráfico ESTABLISHED,RELATED (system)")
        
        # DENEGAR todo lo demás (regla del sistema)
        await run_iptables_command(f"iptables -A {chain_input} -m comment --comment \"rule_id:system_drop\" -j DROP")
        steps.append("INGRESS: Denegado todo el tráfico entrante por defecto (system). Usuario debe agregar reglas personalizadas.")
        
        elapsed_time = (datetime.now() - start_time).total_seconds()
        
        logger.info(f"Security Group {id_sg} aplicado a slice {slice_id} en {elapsed_time:.2f}s")
        
        return {
            'success': True,
            'message': f'Security Group {id_sg} creado para slice {slice_id}',
            'details': {
                'slice_id': slice_id,
                'id_sg': id_sg,
                'security_group': f'SG{id_sg}',
                'policy': {
                    'egress': 'ALLOW ALL (IPv4/IPv6) - rule_id:1,2',
                    'ingress': 'DENY ALL by default (user must add custom rules)'
                },
                'linked_interfaces': linked_interfaces,
                'failed_interfaces': failed_interfaces,
                'total_interfaces': len(tap_interfaces),
                'execution_time_seconds': round(elapsed_time, 2),
                'steps': steps
            }
        }
        
    except Exception as e:
        logger.error(f"Error creando Security Group {id_sg} para slice {slice_id}: {str(e)}\n{traceback.format_exc()}")
        return {
            'success': False,
            'message': f'Error interno: {str(e)}',
            'details': {'error': 'internal_error', 'steps': steps}
        }

async def remove_custom_security_group(slice_id: int, id_sg: int) -> Dict[str, Any]:
    """
    Remover security group personalizado de un slice
    Formato: SG{id_sg}_id{slice_id}_INPUT/OUTPUT
    """
    try:
        logger.info(f"Removiendo Security Group {id_sg} del slice {slice_id}")
        
        chain_input = f"SG{id_sg}_id{slice_id}_INPUT"
        chain_output = f"SG{id_sg}_id{slice_id}_OUTPUT"
        steps = []
        
        # 1. Verificar si las cadenas existen
        if not await chain_exists(chain_input) and not await chain_exists(chain_output):
            return {
                'success': True,
                'message': f'Security Group {id_sg} del slice {slice_id} no existía',
                'details': {'already_removed': True}
            }
        
        # 2. Obtener lista de reglas en FORWARD que referencian nuestras cadenas (IPv4)
        result = await run_iptables_command("iptables -L FORWARD --line-numbers -n")
        if result['success']:
            lines = result['stdout'].split('\n')
            lines_to_delete = []
            for line in lines:
                if chain_input in line or chain_output in line:
                    parts = line.split()
                    if parts and parts[0].isdigit():
                        lines_to_delete.append(int(parts[0]))
            
            # Eliminar de mayor a menor
            for line_num in sorted(lines_to_delete, reverse=True):
                await run_iptables_command(f"iptables -D FORWARD {line_num}")
        
        # 2b. Obtener lista de reglas en FORWARD que referencian nuestras cadenas (IPv6)
        result_v6 = await run_iptables_command("ip6tables -L FORWARD --line-numbers -n")
        if result_v6['success']:
            lines = result_v6['stdout'].split('\n')
            lines_to_delete = []
            for line in lines:
                if chain_input in line or chain_output in line:
                    parts = line.split()
                    if parts and parts[0].isdigit():
                        lines_to_delete.append(int(parts[0]))
            
            for line_num in sorted(lines_to_delete, reverse=True):
                await run_iptables_command(f"ip6tables -D FORWARD {line_num}")
        
        steps.append("Referencias en FORWARD eliminadas (IPv4 e IPv6)")
        
        # 3. Limpiar cadenas IPv4 e IPv6
        await run_iptables_command(f"iptables -F {chain_input} 2>/dev/null || true")
        await run_iptables_command(f"iptables -F {chain_output} 2>/dev/null || true")
        await run_iptables_command(f"ip6tables -F {chain_input} 2>/dev/null || true")
        await run_iptables_command(f"ip6tables -F {chain_output} 2>/dev/null || true")
        steps.append("Cadenas limpiadas (IPv4 e IPv6)")
        
        # 4. Eliminar cadenas IPv4 e IPv6
        await run_iptables_command(f"iptables -X {chain_input} 2>/dev/null || true")
        await run_iptables_command(f"iptables -X {chain_output} 2>/dev/null || true")
        await run_iptables_command(f"ip6tables -X {chain_input} 2>/dev/null || true")
        await run_iptables_command(f"ip6tables -X {chain_output} 2>/dev/null || true")
        steps.append("Cadenas eliminadas (IPv4 e IPv6)")
        
        logger.info(f"Security Group {id_sg} del slice {slice_id} removido exitosamente")
        
        return {
            'success': True,
            'message': f'Security Group {id_sg} del slice {slice_id} removido',
            'details': {
                'slice_id': slice_id,
                'id_sg': id_sg,
                'steps': steps
            }
        }
        
    except Exception as e:
        logger.error(f"Error removiendo Security Group {id_sg} del slice {slice_id}: {str(e)}")
        return {
            'success': False,
            'message': f'Error interno: {str(e)}',
            'details': {'error': 'internal_error'}
        }

async def add_rule_to_security_group(slice_id: int, id_sg: Optional[int], rule_id: int,
                                    rule_template: Optional[str], direction: str, ether_type: str, 
                                    protocol: str, port_range: str, remote_ip_prefix: Optional[str],
                                    remote_security_group: Optional[str], icmp_type: Optional[str],
                                    icmp_code: Optional[str], description: str) -> Dict[str, Any]:
    """
    Agregar una regla específica a un security group
    """
    try:
        # Determinar nombres de cadenas
        if id_sg is None:
            chain_input = f"SG_df_id{slice_id}_INPUT"
            chain_output = f"SG_df_id{slice_id}_OUTPUT"
            sg_name = "default"
        else:
            chain_input = f"SG{id_sg}_id{slice_id}_INPUT"
            chain_output = f"SG{id_sg}_id{slice_id}_OUTPUT"
            sg_name = f"SG{id_sg}"
        
        # Seleccionar cadena según dirección
        chain = chain_input if direction == "ingress" else chain_output
        
        # Verificar que la cadena existe
        if not await chain_exists(chain):
            return {
                'success': False,
                'message': f'Security Group {sg_name} no existe para slice {slice_id}',
                'details': {'error': 'sg_not_found'}
            }
        
        # Verificar si la regla ya existe
        existing_line = await find_rule_by_id(chain, rule_id)
        if existing_line:
            return {
                'success': False,
                'message': f'Regla {rule_id} ya existe en {sg_name}',
                'details': {'error': 'rule_already_exists', 'line_number': existing_line}
            }
        
        # Aplicar plantilla si existe
        if rule_template:
            try:
                # Crear request temporal para aplicar plantilla
                temp_request = AddRuleRequest(
                    slice_id=slice_id,
                    id_sg=id_sg,
                    rule_id=rule_id,
                    rule_template=rule_template,
                    direction=direction,
                    ether_type=ether_type,
                    protocol=protocol,
                    port_range=port_range,
                    remote_ip_prefix=remote_ip_prefix,
                    icmp_type=icmp_type,
                    icmp_code=icmp_code
                )
                applied = apply_rule_template(temp_request)
                protocol = applied["protocol"]
                port_range = applied["port_range"]
                ether_type = applied["ether_type"]
                icmp_type = applied["icmp_type"]
                icmp_code = applied["icmp_code"]
            except ValueError as e:
                return {
                    'success': False,
                    'message': str(e),
                    'details': {'error': 'invalid_template'}
                }
        
        # Obtener interfaces TAP
        tap_interfaces = await get_tap_interfaces_for_slice(slice_id)
        
        # Construir y ejecutar regla
        if direction == "ingress" and remote_security_group:
            # Caso especial: permitir desde interfaces del mismo SG
            for tap in tap_interfaces:
                rule_cmd = f"iptables -A {chain} -m comment --comment \"rule_id:{rule_id}\" -i {tap} -j ACCEPT"
                await run_iptables_command(rule_cmd)
        else:
            # Regla normal
            rule_cmd = f"iptables -A {chain} -m comment --comment \"rule_id:{rule_id}\""
            
            # Protocolo
            if protocol != "any" and protocol in ["tcp", "udp", "icmp"]:
                rule_cmd += f" -p {protocol}"
            
            # Puerto
            if protocol in ["tcp", "udp"] and port_range != "any":
                rule_cmd += f" --dport {port_range}"
            
            # ICMP type y code
            if protocol == "icmp":
                if icmp_type:
                    rule_cmd += f" --icmp-type {icmp_type}"
                    if icmp_code:
                        rule_cmd += f"/{icmp_code}"
            
            # IP
            if direction == "ingress" and remote_ip_prefix:
                rule_cmd += f" -s {remote_ip_prefix}"
            elif direction == "egress" and remote_ip_prefix:
                rule_cmd += f" -d {remote_ip_prefix}"
            
            rule_cmd += " -j ACCEPT"
            
            result = await run_iptables_command(rule_cmd)
            if not result['success']:
                return {
                    'success': False,
                    'message': f'Error ejecutando regla: {result.get("stderr", "")}',
                    'details': {'error': 'iptables_error'}
                }
        
        logger.info(f"Regla {rule_id} agregada a {sg_name} del slice {slice_id}")
        
        return {
            'success': True,
            'message': f'Regla {rule_id} agregada a {sg_name}',
            'details': {
                'slice_id': slice_id,
                'id_sg': id_sg,
                'rule_id': rule_id,
                'rule_template': rule_template,
                'direction': direction,
                'protocol': protocol,
                'port_range': port_range,
                'chain': chain,
                'description': description
            }
        }
        
    except Exception as e:
        logger.error(f"Error agregando regla {rule_id}: {str(e)}")
        return {
            'success': False,
            'message': f'Error interno: {str(e)}',
            'details': {'error': 'internal_error'}
        }

async def remove_rule_from_security_group(slice_id: int, id_sg: Optional[int], rule_id: int) -> Dict[str, Any]:
    """
    Remover una regla específica de un security group usando su rule_id
    """
    try:
        # Determinar nombres de cadenas
        if id_sg is None:
            chain_input = f"SG_df_id{slice_id}_INPUT"
            chain_output = f"SG_df_id{slice_id}_OUTPUT"
            sg_name = "default"
        else:
            chain_input = f"SG{id_sg}_id{slice_id}_INPUT"
            chain_output = f"SG{id_sg}_id{slice_id}_OUTPUT"
            sg_name = f"SG{id_sg}"
        
        # Buscar y eliminar TODAS las ocurrencias en ambas cadenas (INPUT y OUTPUT) y en IPv4 e IPv6
        removed_count = 0
        removed_from = []
        
        for chain in [chain_input, chain_output]:
            if not await chain_exists(chain):
                continue
            
            # Eliminar TODAS las reglas con este rule_id en IPv4
            while True:
                line_number = await find_rule_by_id(chain, rule_id)
                if not line_number:
                    break
                
                result = await run_iptables_command(f"iptables -D {chain} {line_number}")
                if result['success']:
                    removed_count += 1
                    if f"{chain} (IPv4)" not in removed_from:
                        removed_from.append(f"{chain} (IPv4)")
                else:
                    break
            
            # Eliminar TODAS las reglas con este rule_id en IPv6
            while True:
                result_ipv6 = await run_iptables_command(f"ip6tables -L {chain} --line-numbers -n")
                if not result_ipv6['success']:
                    break
                
                found = False
                for line in result_ipv6['stdout'].split('\n'):
                    if f"rule_id:{rule_id}" in line:
                        parts = line.split()
                        if parts and parts[0].isdigit():
                            line_num_ipv6 = int(parts[0])
                            result = await run_iptables_command(f"ip6tables -D {chain} {line_num_ipv6}")
                            if result['success']:
                                removed_count += 1
                                if f"{chain} (IPv6)" not in removed_from:
                                    removed_from.append(f"{chain} (IPv6)")
                                found = True
                                break
                
                if not found:
                    break
        
        if removed_count > 0:
            logger.info(f"Regla {rule_id} eliminada de {sg_name} del slice {slice_id} ({removed_count} ocurrencias)")
            return {
                'success': True,
                'message': f'Regla {rule_id} eliminada de {sg_name} ({removed_count} ocurrencias)',
                'details': {
                    'slice_id': slice_id,
                    'id_sg': id_sg,
                    'rule_id': rule_id,
                    'removed_count': removed_count,
                    'chains': removed_from
                }
            }
        else:
            return {
                'success': False,
                'message': f'Regla {rule_id} no encontrada en {sg_name}',
                'details': {'error': 'rule_not_found'}
            }
        
    except Exception as e:
        logger.error(f"Error eliminando regla {rule_id}: {str(e)}")
        return {
            'success': False,
            'message': f'Error interno: {str(e)}',
            'details': {'error': 'internal_error'}
        }

# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check del agente"""
    return {
        'status': 'healthy',
        'service': 'security-group-agent',
        'version': '1.0.0',
        'timestamp': datetime.now().isoformat()
    }

@app.get("/templates")
async def list_templates():
    """Listar plantillas de reglas disponibles"""
    templates_info = {}
    for template_name, template_config in RULE_TEMPLATES.items():
        templates_info[template_name] = {
            "protocol": template_config.get("protocol", "any"),
            "port_range": template_config.get("port_range", "user-defined"),
            "ether_type": template_config.get("ether_type", "IPv4"),
            "description": get_template_description(template_name)
        }
    
    return {
        'success': True,
        'templates': templates_info,
        'total': len(RULE_TEMPLATES)
    }

def get_template_description(template_name: str) -> str:
    """Obtener descripción de plantilla"""
    descriptions = {
        "CUSTOM_TCP": "Regla TCP personalizada (usuario define puertos)",
        "CUSTOM_UDP": "Regla UDP personalizada (usuario define puertos)",
        "CUSTOM_ICMP": "Regla ICMP personalizada (usuario define tipo/código)",
        "ALL_TCP": "Permitir todo el tráfico TCP (puertos 1-65535)",
        "ALL_UDP": "Permitir todo el tráfico UDP (puertos 1-65535)",
        "ALL_ICMP": "Permitir todo el tráfico ICMP",
        "SSH": "Acceso SSH (TCP puerto 22)",
        "HTTP": "Acceso HTTP (TCP puerto 80)",
        "HTTPS": "Acceso HTTPS (TCP puerto 443)",
        "DNS": "Acceso DNS (UDP puerto 53)"
    }
    return descriptions.get(template_name, "Sin descripción")

@app.post("/apply-default")
async def apply_default_sg_endpoint(request: ApplyDefaultSGRequest):
    """
    Aplicar security group por defecto a interfaces TAP
    
    Este endpoint retorna inmediatamente y procesa en background
    para no bloquear el flujo de despliegue
    """
    try:
        logger.info(f"Petición de SG Default recibida: slice {request.slice_id}, TAPs: {request.tap_interfaces}")
        
        # Validar datos
        if not request.tap_interfaces:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Se requiere al menos una interfaz TAP"
            )
        
        # Procesar en background (fire-and-forget)
        asyncio.create_task(
            create_default_security_group(request.slice_id, request.tap_interfaces)
        )
        
        # Retornar inmediatamente
        return {
            'success': True,
            'message': f'Security Group Default en proceso para slice {request.slice_id}',
            'details': {
                'slice_id': request.slice_id,
                'tap_interfaces': request.tap_interfaces,
                'processing': 'background'
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en apply_default_sg_endpoint: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/create-default")
async def create_default_sg_endpoint(request: VMOperationRequest):
    """
    Crear security group DEFAULT para un slice
    Formato de cadenas: SG_df_id{slice_id}_INPUT/OUTPUT
    """
    try:
        logger.info(f"Creando Security Group Default para slice {request.slice_id}")
        
        # Obtener interfaces TAP del slice
        tap_interfaces = await get_tap_interfaces_for_slice(request.slice_id)
        
        if not tap_interfaces:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se encontraron interfaces TAP para slice {request.slice_id}"
            )
        
        result = await create_default_security_group(request.slice_id, tap_interfaces)
        
        if not result['success']:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result['message']
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en create_default_sg_endpoint: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/remove-default")
async def remove_default_sg_endpoint(request: VMOperationRequest):
    """
    Remover security group DEFAULT de un slice
    Formato de cadenas: SG_df_id{slice_id}_INPUT/OUTPUT
    """
    try:
        result = await remove_default_security_group(request.slice_id)
        
        if not result['success']:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result['message']
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en remove_default_sg_endpoint: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/create-custom")
async def create_custom_sg_endpoint(request: CustomSGRequest):
    """
    Crear security group PERSONALIZADO para un slice
    Formato de cadenas: SG{id_sg}_id{slice_id}_INPUT/OUTPUT
    """
    try:
        logger.info(f"Creando Security Group {request.id_sg} para slice {request.slice_id}")
        
        # Obtener interfaces TAP del slice
        tap_interfaces = await get_tap_interfaces_for_slice(request.slice_id)
        
        if not tap_interfaces:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se encontraron interfaces TAP para slice {request.slice_id}"
            )
        
        result = await create_custom_security_group(request.slice_id, request.id_sg, tap_interfaces)
        
        if not result['success']:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result['message']
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en create_custom_sg_endpoint: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/remove-custom")
async def remove_custom_sg_endpoint(request: CustomSGRequest):
    """
    Remover security group PERSONALIZADO de un slice
    Formato de cadenas: SG{id_sg}_id{slice_id}_INPUT/OUTPUT
    """
    try:
        result = await remove_custom_security_group(request.slice_id, request.id_sg)
        
        if not result['success']:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result['message']
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en remove_custom_sg_endpoint: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/remove")
async def remove_sg_endpoint(request: RemoveSGRequest):
    """Remover security group de un slice (legacy endpoint)"""
    try:
        result = await remove_default_security_group(request.slice_id)
        
        if not result['success']:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result['message']
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en remove_sg_endpoint: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/add-rule")
async def add_rule_endpoint(request: AddRuleRequest):
    """Agregar regla específica a un security group"""
    try:
        result = await add_rule_to_security_group(
            slice_id=request.slice_id,
            id_sg=request.id_sg,
            rule_id=request.rule_id,
            rule_template=request.rule_template,
            direction=request.direction,
            ether_type=request.ether_type,
            protocol=request.protocol,
            port_range=request.port_range,
            remote_ip_prefix=request.remote_ip_prefix,
            remote_security_group=request.remote_security_group,
            icmp_type=request.icmp_type,
            icmp_code=request.icmp_code,
            description=request.description
        )
        
        if not result['success']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result['message']
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en add_rule_endpoint: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/remove-rule")
async def remove_rule_endpoint(request: RemoveRuleRequest):
    """Remover regla específica de un security group"""
    try:
        result = await remove_rule_from_security_group(
            slice_id=request.slice_id,
            id_sg=request.id_sg,
            rule_id=request.rule_id
        )
        
        if not result['success']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result['message']
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en remove_rule_endpoint: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/remove-all")
async def remove_all_sg_endpoint(request: VMOperationRequest):
    """
    Eliminar TODOS los security groups de un slice (default y personalizados)
    """
    try:
        logger.info(f"Eliminando TODOS los security groups del slice {request.slice_id}")
        
        removed_sgs = []
        errors = []
        
        # 1. Buscar todas las cadenas relacionadas con el slice
        result = await run_iptables_command("iptables -L -n")
        if not result['success']:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error listando cadenas de iptables"
            )
        
        # 2. Identificar cadenas del slice (SG_df_id{X}, SG{Y}_id{X})
        chains_to_remove = []
        for line in result['stdout'].split('\n'):
            if f"_id{request.slice_id}_" in line and line.startswith("Chain"):
                # Extraer nombre de cadena: "Chain SG_df_id10_INPUT ..."
                parts = line.split()
                if len(parts) >= 2:
                    chain_name = parts[1]
                    if chain_name not in chains_to_remove:
                        chains_to_remove.append(chain_name)
        
        if not chains_to_remove:
            return {
                'success': True,
                'message': f'No se encontraron security groups para el slice {request.slice_id}',
                'details': {
                    'slice_id': request.slice_id,
                    'removed_sgs': [],
                    'total_removed': 0
                }
            }
        
        logger.info(f"Cadenas encontradas para slice {request.slice_id}: {chains_to_remove}")
        
        # 3. Identificar qué SGs son (default o custom)
        sg_types = {}
        for chain in chains_to_remove:
            if f"SG_df_id{request.slice_id}_" in chain:
                sg_types['default'] = True
            else:
                # Extraer id_sg de SG{id_sg}_id{slice_id}_
                import re
                match = re.match(rf"SG(\d+)_id{request.slice_id}_", chain)
                if match:
                    id_sg = int(match.group(1))
                    if 'custom' not in sg_types:
                        sg_types['custom'] = []
                    if id_sg not in sg_types['custom']:
                        sg_types['custom'].append(id_sg)
        
        # 4. Eliminar default SG si existe
        if sg_types.get('default'):
            try:
                result_default = await remove_default_security_group(request.slice_id)
                if result_default['success']:
                    removed_sgs.append({
                        'type': 'default',
                        'name': f'SG_df_id{request.slice_id}',
                        'status': 'removed'
                    })
                else:
                    errors.append({
                        'type': 'default',
                        'error': result_default.get('message', 'Unknown error')
                    })
            except Exception as e:
                errors.append({
                    'type': 'default',
                    'error': str(e)
                })
        
        # 5. Eliminar custom SGs si existen
        if sg_types.get('custom'):
            for id_sg in sg_types['custom']:
                try:
                    result_custom = await remove_custom_security_group(request.slice_id, id_sg)
                    if result_custom['success']:
                        removed_sgs.append({
                            'type': 'custom',
                            'id_sg': id_sg,
                            'name': f'SG{id_sg}_id{request.slice_id}',
                            'status': 'removed'
                        })
                    else:
                        errors.append({
                            'type': 'custom',
                            'id_sg': id_sg,
                            'error': result_custom.get('message', 'Unknown error')
                        })
                except Exception as e:
                    errors.append({
                        'type': 'custom',
                        'id_sg': id_sg,
                        'error': str(e)
                    })
        
        logger.info(f"Eliminados {len(removed_sgs)} security groups del slice {request.slice_id}")
        
        return {
            'success': len(errors) == 0,
            'message': f'Eliminados {len(removed_sgs)} security groups del slice {request.slice_id}',
            'details': {
                'slice_id': request.slice_id,
                'removed_sgs': removed_sgs,
                'errors': errors if errors else None,
                'total_removed': len(removed_sgs),
                'total_errors': len(errors)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error eliminando security groups del slice {request.slice_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.get("/status/{slice_id}")
async def get_sg_status(slice_id: int):
    """
    Obtener estado del security group de un slice
    """
    try:
        chain_input = f"SG_id{slice_id}_INPUT"
        chain_output = f"SG_id{slice_id}_OUTPUT"
        
        # Verificar si existen las cadenas
        input_exists = await chain_exists(chain_input)
        output_exists = await chain_exists(chain_output)
        
        if not input_exists and not output_exists:
            return {
                'slice_id': slice_id,
                'security_group_applied': False,
                'message': 'No hay Security Group aplicado'
            }
        
        # Listar reglas
        result_input = await run_iptables_command(f"iptables -L {chain_input} -n -v")
        result_output = await run_iptables_command(f"iptables -L {chain_output} -n -v")
        
        return {
            'slice_id': slice_id,
            'security_group_applied': True,
            'chains': {
                'input': {
                    'name': chain_input,
                    'exists': input_exists,
                    'rules': result_input['stdout'] if input_exists else None
                },
                'output': {
                    'name': chain_output,
                    'exists': output_exists,
                    'rules': result_output['stdout'] if output_exists else None
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo estado SG slice {slice_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    logger.info("Iniciando Security Group Agent en puerto 5810...")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5810,
        log_level="info",
        access_log=True
    )

#!/usr/bin/env python3
"""
Security Groups API - Coordinador para gestión de security groups multi-worker
Puerto: 5811
Versión: 1.0

Este servicio coordina la aplicación de security groups en múltiples workers,
actuando como intermediario entre el usuario y los security_group_agents (puerto 5810).
"""

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import requests
import logging
from datetime import datetime

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [Security-API] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Security Groups API",
    version="1.0.0",
    description="Coordinador para gestión de security groups en cluster Linux"
)

# =============================================================================
# CONFIGURACIÓN
# =============================================================================

# Workers del cluster
WORKERS_CONFIG = {
    'worker1': '192.168.201.2',
    'worker2': '192.168.201.3',
    'worker3': '192.168.201.4'
}

# Puerto del Security Group Agent en cada worker
SG_AGENT_PORT = 5810

# =============================================================================
# MODELOS PYDANTIC
# =============================================================================

class CreateCustomSGRequest(BaseModel):
    """Crear security group personalizado"""
    slice_id: int = Field(..., ge=1, le=9999)
    id_sg: int = Field(..., ge=1, le=9999)
    workers: str = Field(..., description="Workers separados por ';' (ej: 'worker1;worker2')")

class RemoveDefaultSGRequest(BaseModel):
    """Eliminar security group default"""
    slice_id: int = Field(..., ge=1, le=9999)
    workers: str = Field(..., description="Workers separados por ';' (ej: 'worker1;worker2')")

class RemoveCustomSGRequest(BaseModel):
    """Eliminar security group personalizado"""
    slice_id: int = Field(..., ge=1, le=9999)
    id_sg: int = Field(..., ge=1, le=9999)
    workers: str = Field(..., description="Workers separados por ';' (ej: 'worker1;worker2')")

class AddRuleRequest(BaseModel):
    """Agregar regla a security group"""
    slice_id: int = Field(..., ge=1, le=9999)
    id_sg: Optional[int] = Field(None, ge=1, le=9999, description="None = default SG")
    sg_name: Optional[str] = Field(None, description="Nombre alternativo: 'SG_df_id{slice}' para default")
    rule_id: int = Field(..., ge=1)
    rule_template: Optional[str] = Field(None, description="Plantilla: SSH, HTTP, HTTPS, etc.")
    plantilla: Optional[str] = Field(None, description="Alias de rule_template")
    direction: str = Field(..., description="ingress/egress o INPUT/OUTPUT")
    ether_type: str = Field("IPv4", description="IPv4 o IPv6")
    protocol: str = Field("any", description="tcp, udp, icmp, any")
    port_range: str = Field("any", description="Puerto o rango (ej: '22', '80-443', 'any')")
    remote_ip_prefix: Optional[str] = Field(None, description="CIDR (ej: '0.0.0.0/0')")
    remote_security_group: Optional[str] = Field(None, description="Permitir desde mismo SG")
    icmp_type: Optional[str] = Field(None, description="Tipo ICMP")
    icmp_code: Optional[str] = Field(None, description="Código ICMP")
    description: str = Field("", description="Descripción de la regla")
    workers: str = Field(..., description="Workers separados por ';'")

class RemoveRuleRequest(BaseModel):
    """Eliminar regla de security group"""
    slice_id: int = Field(..., ge=1, le=9999)
    id_sg: Optional[int] = Field(None, ge=1, le=9999, description="None = default SG")
    sg_name: Optional[str] = Field(None, description="Nombre alternativo: 'SG_df_id{slice}' para default")
    rule_id: int = Field(..., ge=1)
    direction: str = Field(..., description="ingress/egress o INPUT/OUTPUT")
    workers: str = Field(..., description="Workers separados por ';'")

class SGStatusRequest(BaseModel):
    """Consultar estado de security group"""
    slice_id: int = Field(..., ge=1, le=9999)
    workers: str = Field(..., description="Workers separados por ';'")

class OperationResponse(BaseModel):
    """Respuesta de operaciones de security groups"""
    success: bool
    message: str
    slice_id: int
    error: Optional[str] = None

# =============================================================================
# FUNCIONES AUXILIARES
# =============================================================================

def parse_workers(workers_str: str) -> List[str]:
    """
    Parsear string de workers separados por ';'
    
    Args:
        workers_str: "worker1;worker2;worker3"
    
    Returns:
        ["worker1", "worker2", "worker3"]
    """
    workers = [w.strip() for w in workers_str.split(';') if w.strip()]
    
    # Validar que todos los workers existen en la configuración
    invalid_workers = [w for w in workers if w not in WORKERS_CONFIG]
    if invalid_workers:
        raise ValueError(f"Workers inválidos: {', '.join(invalid_workers)}")
    
    return workers

async def call_sg_agent(worker_ip: str, endpoint: str, payload: Dict) -> Dict[str, Any]:
    """
    Llamar al security_group_agent de un worker
    
    Args:
        worker_ip: IP del worker
        endpoint: Endpoint del agente (ej: /create-custom)
        payload: Datos a enviar
    
    Returns:
        Dict con resultado de la llamada
    """
    try:
        url = f"http://{worker_ip}:{SG_AGENT_PORT}{endpoint}"
        headers = {"Content-Type": "application/json"}
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        if response.status_code == 200:
            return {
                'success': True,
                'data': response.json()
            }
        else:
            return {
                'success': False,
                'error': f"HTTP {response.status_code}",
                'details': response.text
            }
            
    except requests.exceptions.Timeout:
        return {
            'success': False,
            'error': 'timeout',
            'message': f'Timeout conectando al SG agent en {worker_ip}'
        }
    except requests.exceptions.ConnectionError:
        return {
            'success': False,
            'error': 'connection_error',
            'message': f'Error de conexión al SG agent en {worker_ip}'
        }
    except Exception as e:
        return {
            'success': False,
            'error': 'internal_error',
            'message': str(e)
        }

# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/")
async def root():
    """Endpoint raíz - información del servicio"""
    return {
        "service": "Security Groups API",
        "version": "1.0.0",
        "status": "running",
        "port": 5811,
        "workers": list(WORKERS_CONFIG.keys()),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health_check():
    """Health check del servicio"""
    return {
        "status": "healthy",
        "service": "security_groups_api",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/templates")
async def list_templates():
    """
    Listar plantillas de reglas disponibles
    
    Consulta el primer worker disponible para obtener la lista.
    """
    try:
        # Consultar primer worker
        first_worker_ip = list(WORKERS_CONFIG.values())[0]
        url = f"http://{first_worker_ip}:{SG_AGENT_PORT}/templates"
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error obteniendo plantillas"
            )
            
    except Exception as e:
        logger.error(f"Error obteniendo plantillas: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/create-custom", response_model=OperationResponse)
async def create_custom_sg(request: CreateCustomSGRequest):
    """
    Crear security group personalizado en workers especificados
    
    Formato de cadenas: SG{id_sg}_id{slice_id}_INPUT/OUTPUT
    """
    try:
        workers = parse_workers(request.workers)
        
        logger.info(f"Creando SG personalizado {request.id_sg} para slice {request.slice_id} en workers: {workers}")
        
        results = {
            'successful_workers': [],
            'failed_workers': []
        }
        
        for worker_name in workers:
            worker_ip = WORKERS_CONFIG[worker_name]
            
            payload = {
                "slice_id": request.slice_id,
                "id_sg": request.id_sg
            }
            
            result = await call_sg_agent(worker_ip, "/create-custom", payload)
            
            if result['success']:
                results['successful_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'response': result['data']
                })
                logger.info(f"SG {request.id_sg} creado en {worker_name}")
            else:
                results['failed_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'error': result.get('error', 'Unknown error')
                })
                logger.warning(f"Error creando SG {request.id_sg} en {worker_name}: {result.get('error')}")
        
        success = len(results['failed_workers']) == 0
        
        if success:
            message = f"SG custom {request.id_sg} creado en {len(results['successful_workers'])} workers"
        else:
            message = f"SG custom {request.id_sg}: {len(results['successful_workers'])} OK, {len(results['failed_workers'])} fallos"
        
        return OperationResponse(
            success=success,
            message=message,
            slice_id=request.slice_id
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error en create_custom_sg: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/remove-default", response_model=OperationResponse)
async def remove_default_sg(request: RemoveDefaultSGRequest):
    """
    Eliminar security group default de workers especificados
    
    Formato de cadenas: SG_df_id{slice_id}_INPUT/OUTPUT
    """
    try:
        workers = parse_workers(request.workers)
        
        logger.info(f"Eliminando SG default del slice {request.slice_id} en workers: {workers}")
        
        results = {
            'successful_workers': [],
            'failed_workers': []
        }
        
        for worker_name in workers:
            worker_ip = WORKERS_CONFIG[worker_name]
            
            payload = {"slice_id": request.slice_id}
            
            result = await call_sg_agent(worker_ip, "/remove-default", payload)
            
            if result['success']:
                results['successful_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'response': result['data']
                })
                logger.info(f"SG default eliminado en {worker_name}")
            else:
                results['failed_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'error': result.get('error', 'Unknown error')
                })
                logger.warning(f"Error eliminando SG default en {worker_name}: {result.get('error')}")
        
        success = len(results['failed_workers']) == 0
        
        if success:
            message = f"SG default slice {request.slice_id} eliminado en {len(results['successful_workers'])} workers"
        else:
            message = f"SG default slice {request.slice_id}: {len(results['successful_workers'])} OK, {len(results['failed_workers'])} fallos"
        
        return OperationResponse(
            success=success,
            message=message,
            slice_id=request.slice_id,
            
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error en remove_default_sg: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/remove-custom", response_model=OperationResponse)
async def remove_custom_sg(request: RemoveCustomSGRequest):
    """
    Eliminar security group personalizado de workers especificados
    
    Formato de cadenas: SG{id_sg}_id{slice_id}_INPUT/OUTPUT
    """
    try:
        workers = parse_workers(request.workers)
        
        logger.info(f"Eliminando SG {request.id_sg} del slice {request.slice_id} en workers: {workers}")
        
        results = {
            'successful_workers': [],
            'failed_workers': []
        }
        
        for worker_name in workers:
            worker_ip = WORKERS_CONFIG[worker_name]
            
            payload = {
                "slice_id": request.slice_id,
                "id_sg": request.id_sg
            }
            
            result = await call_sg_agent(worker_ip, "/remove-custom", payload)
            
            if result['success']:
                results['successful_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'response': result['data']
                })
                logger.info(f"SG {request.id_sg} eliminado en {worker_name}")
            else:
                results['failed_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'error': result.get('error', 'Unknown error')
                })
                logger.warning(f"Error eliminando SG {request.id_sg} en {worker_name}: {result.get('error')}")
        
        success = len(results['failed_workers']) == 0
        
        if success:
            message = f"SG custom {request.id_sg} eliminado en {len(results['successful_workers'])} workers"
        else:
            message = f"SG custom {request.id_sg}: {len(results['successful_workers'])} OK, {len(results['failed_workers'])} fallos"
        
        return OperationResponse(
            success=success,
            message=message,
            slice_id=request.slice_id,
            
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error en remove_custom_sg: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/add-rule", response_model=OperationResponse)
async def add_rule(request: AddRuleRequest):
    """
    Agregar regla a security group en workers especificados
    
    La regla se agrega al SG default si id_sg=None, o al SG personalizado especificado.
    """
    try:
        workers = parse_workers(request.workers)
        
        # Manejar sg_name alternativo (ej: "SG_df_id1" para default)
        if request.sg_name and request.sg_name.startswith("SG_df_id"):
            # Es un security group default
            request.id_sg = None
        
        # Usar plantilla si se proporciona en lugar de rule_template
        template = request.plantilla if request.plantilla else request.rule_template
        
        # Convertir direction de INPUT/OUTPUT a ingress/egress si es necesario
        direction = request.direction.lower()
        if direction == "input":
            direction = "ingress"
        elif direction == "output":
            direction = "egress"
        
        sg_name = "default" if request.id_sg is None else f"SG{request.id_sg}"
        logger.info(f"Agregando regla {request.rule_id} a {sg_name} del slice {request.slice_id} en workers: {workers}")
        
        results = {
            'successful_workers': [],
            'failed_workers': []
        }
        
        # Preparar payload
        payload = {
            "slice_id": request.slice_id,
            "id_sg": request.id_sg,
            "rule_id": request.rule_id,
            "rule_template": template,
            "direction": direction,
            "ether_type": request.ether_type,
            "protocol": request.protocol,
            "port_range": request.port_range,
            "remote_ip_prefix": request.remote_ip_prefix,
            "remote_security_group": request.remote_security_group,
            "icmp_type": request.icmp_type,
            "icmp_code": request.icmp_code,
            "description": request.description
        }
        
        for worker_name in workers:
            worker_ip = WORKERS_CONFIG[worker_name]
            
            result = await call_sg_agent(worker_ip, "/add-rule", payload)
            
            if result['success']:
                results['successful_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'response': result['data']
                })
                logger.info(f"Regla {request.rule_id} agregada en {worker_name}")
            else:
                results['failed_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'error': result.get('error', 'Unknown error'),
                    'details': result.get('details', '')
                })
                logger.warning(f"Error agregando regla {request.rule_id} en {worker_name}: {result.get('error')}")
        
        success = len(results['failed_workers']) == 0
        
        if success:
            message = f"Regla {request.rule_id} agregada en {len(results['successful_workers'])} workers"
        else:
            message = f"Regla {request.rule_id}: {len(results['successful_workers'])} OK, {len(results['failed_workers'])} fallos"
        
        return OperationResponse(
            success=success,
            message=message,
            slice_id=request.slice_id,
            
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error en add_rule: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/remove-rule", response_model=OperationResponse)
async def remove_rule(request: RemoveRuleRequest):
    """
    Eliminar regla de security group en workers especificados
    
    Elimina la regla del SG default si id_sg=None, o del SG personalizado especificado.
    """
    try:
        workers = parse_workers(request.workers)
        
        # Manejar sg_name alternativo (ej: "SG_df_id1" para default)
        if request.sg_name and request.sg_name.startswith("SG_df_id"):
            request.id_sg = None
        
        # Convertir direction de INPUT/OUTPUT a ingress/egress si es necesario
        direction = request.direction.lower()
        if direction == "input":
            direction = "ingress"
        elif direction == "output":
            direction = "egress"
        
        sg_name = "default" if request.id_sg is None else f"SG{request.id_sg}"
        logger.info(f"Eliminando regla {request.rule_id} de {sg_name} del slice {request.slice_id} en workers: {workers}")
        
        results = {
            'successful_workers': [],
            'failed_workers': []
        }
        
        payload = {
            "slice_id": request.slice_id,
            "id_sg": request.id_sg,
            "rule_id": request.rule_id,
            "direction": direction
        }
        
        for worker_name in workers:
            worker_ip = WORKERS_CONFIG[worker_name]
            
            result = await call_sg_agent(worker_ip, "/remove-rule", payload)
            
            if result['success']:
                results['successful_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'response': result['data']
                })
                logger.info(f"Regla {request.rule_id} eliminada en {worker_name}")
            else:
                results['failed_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'error': result.get('error', 'Unknown error'),
                    'details': result.get('details', '')
                })
                logger.warning(f"Error eliminando regla {request.rule_id} en {worker_name}: {result.get('error')}")
        
        success = len(results['failed_workers']) == 0
        
        if success:
            message = f"Regla {request.rule_id} eliminada en {len(results['successful_workers'])} workers"
        else:
            message = f"Regla {request.rule_id}: {len(results['successful_workers'])} OK, {len(results['failed_workers'])} fallos"
        
        return OperationResponse(
            success=success,
            message=message,
            slice_id=request.slice_id,
            
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error en remove_rule: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/status")
async def get_sg_status(request: SGStatusRequest):
    """
    Consultar estado de security groups en workers especificados
    """
    try:
        workers = parse_workers(request.workers)
        
        logger.info(f"Consultando estado SG del slice {request.slice_id} en workers: {workers}")
        
        workers_status = {}
        
        for worker_name in workers:
            worker_ip = WORKERS_CONFIG[worker_name]
            
            try:
                url = f"http://{worker_ip}:{SG_AGENT_PORT}/status/{request.slice_id}"
                response = requests.get(url, timeout=10)
                
                if response.status_code == 200:
                    workers_status[worker_name] = {
                        'success': True,
                        'ip': worker_ip,
                        'data': response.json()
                    }
                else:
                    workers_status[worker_name] = {
                        'success': False,
                        'ip': worker_ip,
                        'error': f"HTTP {response.status_code}"
                    }
                    
            except Exception as e:
                workers_status[worker_name] = {
                    'success': False,
                    'ip': worker_ip,
                    'error': str(e)
                }
        
        return {
            'success': True,
            'slice_id': request.slice_id,
            'workers_status': workers_status
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error en get_sg_status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    logger.info("=" * 60)
    logger.info("Iniciando Security Groups API")
    logger.info("=" * 60)
    logger.info(f"Puerto: 5811")
    logger.info(f"Workers configurados: {', '.join(WORKERS_CONFIG.keys())}")
    logger.info("=" * 60)
    
    uvicorn.run(
        "security_api:app",
        host="0.0.0.0",
        port=5811,
        reload=True,
        log_level="info"
    )

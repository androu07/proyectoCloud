#!/usr/bin/env python3

import asyncio
import aiohttp
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import uvicorn
import logging

# Configuración
SECRET_TOKEN = "clavesihna"
security = HTTPBearer()

# Configuración de workers
WORKERS = {
    "Worker-1": "10.0.10.2",
    "Worker-2": "10.0.10.3", 
    "Worker-3": "10.0.10.4"
}
WORKER_PORT = 5805
HEADNODE_PORT = 5803  # Puerto donde corre cleanup_vlan_api del headnode
HEADNODE_HOST = "localhost"

# Control de concurrencia
operation_lock = asyncio.Lock()

app = FastAPI(
    title="Cleanup VLAN Completo API",
    description="API Central para limpieza completa de rangos de VLANs en toda la infraestructura",
    version="1.0.0",
    docs_url=None,
    redoc_url=None
)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Modelos
class CleanupRangeRequest(BaseModel):
    vlan_range: str = Field(..., description="Rango de VLANs en formato 'inicio;fin' (ej: '100;103')")
    ovs_bridge: str = Field(default="br-cloud", description="Bridge OVS (siempre br-cloud)")

class StatusRangeRequest(BaseModel):
    vlan_range: str = Field(..., description="Rango de VLANs en formato 'inicio;fin' (ej: '100;103')")

class PauseRangeRequest(BaseModel):
    vlan_range: str = Field(..., description="Rango de VLANs en formato 'inicio;fin' (ej: '100;103')")

class ResumeRangeRequest(BaseModel):
    vlan_range: str = Field(..., description="Rango de VLANs en formato 'inicio;fin' (ej: '100;103')")

class VLANResult(BaseModel):
    vlan_id: int
    success: bool
    message: str
    details: Dict[str, Any] = {}

class NodeResult(BaseModel):
    node_name: str
    success: bool
    message: str
    vlans: List[VLANResult] = []

class CleanupRangeResponse(BaseModel):
    success: bool
    message: str
    total_vlans: int
    successful_vlans: int
    failed_vlans: int
    results: Dict[str, NodeResult]

class StatusRangeResponse(BaseModel):
    success: bool
    message: str
    total_vlans: int
    active_vlans: int
    inactive_vlans: int
    results: Dict[str, NodeResult]

class PauseRangeResponse(BaseModel):
    success: bool
    message: str
    total_vlans: int
    successful_vlans: int
    failed_vlans: int
    results: Dict[str, NodeResult]

class ResumeRangeResponse(BaseModel):
    success: bool
    message: str
    total_vlans: int
    successful_vlans: int
    failed_vlans: int
    results: Dict[str, NodeResult]

# Autenticación
async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    if credentials.credentials != SECRET_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

# Funciones auxiliares
def parse_vlan_range(vlan_range: str) -> List[int]:
    """Parsear rango de VLANs desde formato 'inicio;fin' a lista de enteros"""
    try:
        start_str, end_str = vlan_range.split(';')
        start = int(start_str.strip())
        end = int(end_str.strip())
        
        if start < 1 or end < 1 or start > 4094 or end > 4094:
            raise ValueError("VLANs deben estar entre 1 y 4094")
        
        if start > end:
            raise ValueError("VLAN de inicio debe ser menor o igual que VLAN final")
        
        return list(range(start, end + 1))
    except ValueError as e:
        raise ValueError(f"Formato de rango inválido: {str(e)}")

async def cleanup_vlan_headnode(session: aiohttp.ClientSession, vlan_id: int, ovs_bridge: str) -> Dict[str, Any]:
    """Limpiar VLAN en headnode usando cleanup_vlan_api"""
    try:
        url = f"http://{HEADNODE_HOST}:{HEADNODE_PORT}/cleanup"
        headers = {"Authorization": f"Bearer {SECRET_TOKEN}"}
        data = {
            "vlan_id": vlan_id,
            "ovs_bridge": ovs_bridge
        }
        
        async with session.post(url, json=data, headers=headers, timeout=60) as response:
            if response.status == 200:
                result = await response.json()
                return {
                    "success": result.get("success", False),
                    "message": result.get("message", ""),
                    "details": result
                }
            else:
                error_text = await response.text()
                return {
                    "success": False,
                    "message": f"HTTP {response.status}: {error_text}",
                    "details": {}
                }
    except asyncio.TimeoutError:
        return {
            "success": False,
            "message": "Timeout conectando con headnode API",
            "details": {}
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error conectando con headnode: {str(e)}",
            "details": {}
        }

async def cleanup_vlan_worker(session: aiohttp.ClientSession, worker_name: str, worker_ip: str, vlan_id: int) -> Dict[str, Any]:
    """Limpiar VLAN en worker usando pre_vlan_api"""
    try:
        url = f"http://{worker_ip}:{WORKER_PORT}/cleanup"
        headers = {"Authorization": f"Bearer {SECRET_TOKEN}"}
        data = {"vlan_id": vlan_id}
        
        async with session.post(url, json=data, headers=headers, timeout=60) as response:
            if response.status == 200:
                result = await response.json()
                return {
                    "success": result.get("success", False),
                    "message": result.get("message", ""),
                    "details": result
                }
            else:
                error_text = await response.text()
                return {
                    "success": False,
                    "message": f"HTTP {response.status}: {error_text}",
                    "details": {}
                }
    except asyncio.TimeoutError:
        return {
            "success": False,
            "message": f"Timeout conectando con {worker_name}",
            "details": {}
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error conectando con {worker_name}: {str(e)}",
            "details": {}
        }

async def status_vlan_headnode(session: aiohttp.ClientSession, vlan_id: int) -> Dict[str, Any]:
    """Obtener status de VLAN en headnode usando cleanup_vlan_api"""
    try:
        url = f"http://{HEADNODE_HOST}:{HEADNODE_PORT}/status/{vlan_id}"
        headers = {"Authorization": f"Bearer {SECRET_TOKEN}"}
        
        async with session.get(url, headers=headers, timeout=30) as response:
            if response.status == 200:
                result = await response.json()
                return {
                    "success": True,
                    "message": f"VLAN {vlan_id} - {result.get('total_count', 0)} recursos encontrados",
                    "details": result
                }
            else:
                error_text = await response.text()
                return {
                    "success": False,
                    "message": f"HTTP {response.status}: {error_text}",
                    "details": {}
                }
    except asyncio.TimeoutError:
        return {
            "success": False,
            "message": "Timeout conectando con headnode API",
            "details": {}
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error conectando con headnode: {str(e)}",
            "details": {}
        }

async def status_vlan_worker(session: aiohttp.ClientSession, worker_name: str, worker_ip: str, vlan_id: int) -> Dict[str, Any]:
    """Obtener status de VLAN en worker usando pre_vlan_api"""
    try:
        url = f"http://{worker_ip}:{WORKER_PORT}/status/{vlan_id}"
        headers = {"Authorization": f"Bearer {SECRET_TOKEN}"}
        
        async with session.get(url, headers=headers, timeout=30) as response:
            if response.status == 200:
                result = await response.json()
                vms_count = result.get('total_count', 0)
                running_count = result.get('running_count', 0)
                return {
                    "success": True,
                    "message": f"VLAN {vlan_id} - {vms_count} VMs ({running_count} corriendo)",
                    "details": result
                }
            else:
                error_text = await response.text()
                return {
                    "success": False,
                    "message": f"HTTP {response.status}: {error_text}",
                    "details": {}
                }
    except asyncio.TimeoutError:
        return {
            "success": False,
            "message": f"Timeout conectando con {worker_name}",
            "details": {}
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error conectando con {worker_name}: {str(e)}",
            "details": {}
        }

async def pause_vlan_worker(session: aiohttp.ClientSession, worker_name: str, worker_ip: str, vlan_id: int) -> Dict[str, Any]:
    """Pausar VLAN en worker usando pre_vlan_api"""
    try:
        url = f"http://{worker_ip}:{WORKER_PORT}/pause"
        headers = {"Authorization": f"Bearer {SECRET_TOKEN}"}
        data = {"vlan_id": vlan_id}
        
        async with session.post(url, json=data, headers=headers, timeout=60) as response:
            if response.status == 200:
                result = await response.json()
                return {
                    "success": result.get("success", False),
                    "message": result.get("message", ""),
                    "details": result
                }
            else:
                error_text = await response.text()
                return {
                    "success": False,
                    "message": f"HTTP {response.status}: {error_text}",
                    "details": {}
                }
    except asyncio.TimeoutError:
        return {
            "success": False,
            "message": f"Timeout conectando con {worker_name}",
            "details": {}
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error conectando con {worker_name}: {str(e)}",
            "details": {}
        }

async def resume_vlan_worker(session: aiohttp.ClientSession, worker_name: str, worker_ip: str, vlan_id: int) -> Dict[str, Any]:
    """Reanudar VLAN en worker usando pre_vlan_api"""
    try:
        url = f"http://{worker_ip}:{WORKER_PORT}/resume"
        headers = {"Authorization": f"Bearer {SECRET_TOKEN}"}
        data = {"vlan_id": vlan_id}
        
        async with session.post(url, json=data, headers=headers, timeout=60) as response:
            if response.status == 200:
                result = await response.json()
                return {
                    "success": result.get("success", False),
                    "message": result.get("message", ""),
                    "details": result
                }
            else:
                error_text = await response.text()
                return {
                    "success": False,
                    "message": f"HTTP {response.status}: {error_text}",
                    "details": {}
                }
    except asyncio.TimeoutError:
        return {
            "success": False,
            "message": f"Timeout conectando con {worker_name}",
            "details": {}
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error conectando con {worker_name}: {str(e)}",
            "details": {}
        }

# Endpoints
@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "cleanup_vlan_completo_api"}

@app.post("/cleanup-range", response_model=CleanupRangeResponse)
async def cleanup_vlan_range_endpoint(request: CleanupRangeRequest, token: str = Depends(verify_token)):
    """Limpiar rango completo de VLANs en toda la infraestructura"""
    
    async with operation_lock:
        try:
            logger.info(f"Iniciando limpieza de rango: {request.vlan_range}")
            
            # Parsear rango
            try:
                vlan_list = parse_vlan_range(request.vlan_range)
            except ValueError as e:
                return CleanupRangeResponse(
                    success=False,
                    message=str(e),
                    total_vlans=0,
                    successful_vlans=0,
                    failed_vlans=0,
                    results={}
                )
            
            logger.info(f"Limpiando VLANs: {vlan_list}")
            
            # Inicializar resultados por nodo
            all_results = {
                "headnode": NodeResult(node_name="headnode", success=True, message="", vlans=[]),
                **{worker.lower(): NodeResult(node_name=worker, success=True, message="", vlans=[]) 
                   for worker in WORKERS.keys()}
            }
            
            successful_vlans = 0
            failed_vlans = 0
            
            # Crear sesión HTTP
            timeout = aiohttp.ClientTimeout(total=300)  # 5 minutos timeout total
            async with aiohttp.ClientSession(timeout=timeout) as session:
                
                # Procesar cada VLAN
                for vlan_id in vlan_list:
                    logger.info(f"Procesando VLAN {vlan_id}...")
                    
                    # Limpiar en headnode
                    headnode_result = await cleanup_vlan_headnode(session, vlan_id, request.ovs_bridge)
                    all_results["headnode"].vlans.append(VLANResult(
                        vlan_id=vlan_id,
                        success=headnode_result["success"],
                        message=headnode_result["message"],
                        details=headnode_result["details"]
                    ))
                    
                    # Limpiar en workers en paralelo
                    worker_tasks = []
                    for worker_name, worker_ip in WORKERS.items():
                        task = cleanup_vlan_worker(session, worker_name, worker_ip, vlan_id)
                        worker_tasks.append((worker_name, task))
                    
                    # Esperar resultados de workers
                    vlan_success = headnode_result["success"]
                    for worker_name, task in worker_tasks:
                        worker_result = await task
                        worker_key = worker_name.lower()
                        if worker_key in all_results:
                            all_results[worker_key].vlans.append(VLANResult(
                                vlan_id=vlan_id,
                                success=worker_result["success"],
                                message=worker_result["message"],
                                details=worker_result["details"]
                            ))
                            if not worker_result["success"]:
                                vlan_success = False
                    
                    if vlan_success:
                        successful_vlans += 1
                    else:
                        failed_vlans += 1
            
            # Determinar éxito general y generar mensajes finales
            overall_success = failed_vlans == 0
            
            for node_result in all_results.values():
                successful_count = sum(1 for vlan in node_result.vlans if vlan.success)
                failed_count = len(node_result.vlans) - successful_count
                
                if failed_count == 0:
                    node_result.message = f"Todas las VLANs limpiadas exitosamente ({successful_count}/{len(node_result.vlans)})"
                else:
                    node_result.message = f"Limpieza parcial: {successful_count} exitosas, {failed_count} fallidas"
            
            return CleanupRangeResponse(
                success=overall_success,
                message=f"Limpieza completa: {successful_vlans} VLANs exitosas, {failed_vlans} fallidas de {len(vlan_list)} totales",
                total_vlans=len(vlan_list),
                successful_vlans=successful_vlans,
                failed_vlans=failed_vlans,
                results={key: value.dict() for key, value in all_results.items()}
            )
            
        except Exception as e:
            logger.error(f"Error en limpieza de rango: {str(e)}")
            return CleanupRangeResponse(
                success=False,
                message=f"Error interno: {str(e)}",
                total_vlans=0,
                successful_vlans=0,
                failed_vlans=0,
                results={}
            )

@app.post("/pause-range", response_model=PauseRangeResponse)
async def pause_vlan_range_endpoint(request: PauseRangeRequest, token: str = Depends(verify_token)):
    """Pausar rango completo de VLANs en todos los workers"""
    
    async with operation_lock:
        try:
            logger.info(f"Pausando rango: {request.vlan_range}")
            
            # Parsear rango
            try:
                vlan_list = parse_vlan_range(request.vlan_range)
            except ValueError as e:
                return PauseRangeResponse(
                    success=False,
                    message=str(e),
                    total_vlans=0,
                    successful_vlans=0,
                    failed_vlans=0,
                    results={}
                )
            
            logger.info(f"Pausando VLANs: {vlan_list}")
            
            # Inicializar resultados por worker (solo workers, no headnode)
            all_results = {
                worker.lower(): NodeResult(node_name=worker, success=True, message="", vlans=[]) 
                for worker in WORKERS.keys()
            }
            
            successful_vlans = 0
            failed_vlans = 0
            
            # Crear sesión HTTP
            timeout = aiohttp.ClientTimeout(total=300)  # 5 minutos timeout total
            async with aiohttp.ClientSession(timeout=timeout) as session:
                
                # Procesar cada VLAN
                for vlan_id in vlan_list:
                    logger.info(f"Pausando VLAN {vlan_id}...")
                    
                    # Pausar en workers en paralelo
                    worker_tasks = []
                    for worker_name, worker_ip in WORKERS.items():
                        task = pause_vlan_worker(session, worker_name, worker_ip, vlan_id)
                        worker_tasks.append((worker_name, task))
                    
                    # Esperar resultados de workers
                    vlan_success = True
                    for worker_name, task in worker_tasks:
                        worker_result = await task
                        worker_key = worker_name.lower()
                        if worker_key in all_results:
                            all_results[worker_key].vlans.append(VLANResult(
                                vlan_id=vlan_id,
                                success=worker_result["success"],
                                message=worker_result["message"],
                                details=worker_result["details"]
                            ))
                            if not worker_result["success"]:
                                vlan_success = False
                    
                    if vlan_success:
                        successful_vlans += 1
                    else:
                        failed_vlans += 1
            
            # Determinar éxito general y generar mensajes finales
            overall_success = failed_vlans == 0
            
            for worker_result in all_results.values():
                successful_count = sum(1 for vlan in worker_result.vlans if vlan.success)
                failed_count = len(worker_result.vlans) - successful_count
                
                if failed_count == 0:
                    worker_result.message = f"Todas las VLANs pausadas exitosamente ({successful_count}/{len(worker_result.vlans)})"
                else:
                    worker_result.message = f"Pausado parcial: {successful_count} exitosas, {failed_count} fallidas"
            
            return PauseRangeResponse(
                success=overall_success,
                message=f"Pausado completo: {successful_vlans} VLANs exitosas, {failed_vlans} fallidas de {len(vlan_list)} totales",
                total_vlans=len(vlan_list),
                successful_vlans=successful_vlans,
                failed_vlans=failed_vlans,
                results={key: value.dict() for key, value in all_results.items()}
            )
            
        except Exception as e:
            logger.error(f"Error pausando rango: {str(e)}")
            return PauseRangeResponse(
                success=False,
                message=f"Error interno: {str(e)}",
                total_vlans=0,
                successful_vlans=0,
                failed_vlans=0,
                results={}
            )

@app.post("/resume-range", response_model=ResumeRangeResponse)
async def resume_vlan_range_endpoint(request: ResumeRangeRequest, token: str = Depends(verify_token)):
    """Reanudar rango completo de VLANs en todos los workers"""
    
    async with operation_lock:
        try:
            logger.info(f"Reanudando rango: {request.vlan_range}")
            
            # Parsear rango
            try:
                vlan_list = parse_vlan_range(request.vlan_range)
            except ValueError as e:
                return ResumeRangeResponse(
                    success=False,
                    message=str(e),
                    total_vlans=0,
                    successful_vlans=0,
                    failed_vlans=0,
                    results={}
                )
            
            logger.info(f"Reanudando VLANs: {vlan_list}")
            
            # Inicializar resultados por worker (solo workers, no headnode)
            all_results = {
                worker.lower(): NodeResult(node_name=worker, success=True, message="", vlans=[]) 
                for worker in WORKERS.keys()
            }
            
            successful_vlans = 0
            failed_vlans = 0
            
            # Crear sesión HTTP
            timeout = aiohttp.ClientTimeout(total=300)  # 5 minutos timeout total
            async with aiohttp.ClientSession(timeout=timeout) as session:
                
                # Procesar cada VLAN
                for vlan_id in vlan_list:
                    logger.info(f"Reanudando VLAN {vlan_id}...")
                    
                    # Reanudar en workers en paralelo
                    worker_tasks = []
                    for worker_name, worker_ip in WORKERS.items():
                        task = resume_vlan_worker(session, worker_name, worker_ip, vlan_id)
                        worker_tasks.append((worker_name, task))
                    
                    # Esperar resultados de workers
                    vlan_success = True
                    for worker_name, task in worker_tasks:
                        worker_result = await task
                        worker_key = worker_name.lower()
                        if worker_key in all_results:
                            all_results[worker_key].vlans.append(VLANResult(
                                vlan_id=vlan_id,
                                success=worker_result["success"],
                                message=worker_result["message"],
                                details=worker_result["details"]
                            ))
                            if not worker_result["success"]:
                                vlan_success = False
                    
                    if vlan_success:
                        successful_vlans += 1
                    else:
                        failed_vlans += 1
            
            # Determinar éxito general y generar mensajes finales
            overall_success = failed_vlans == 0
            
            for worker_result in all_results.values():
                successful_count = sum(1 for vlan in worker_result.vlans if vlan.success)
                failed_count = len(worker_result.vlans) - successful_count
                
                if failed_count == 0:
                    worker_result.message = f"Todas las VLANs reanudadas exitosamente ({successful_count}/{len(worker_result.vlans)})"
                else:
                    worker_result.message = f"Reanudado parcial: {successful_count} exitosas, {failed_count} fallidas"
            
            return ResumeRangeResponse(
                success=overall_success,
                message=f"Reanudado completo: {successful_vlans} VLANs exitosas, {failed_vlans} fallidas de {len(vlan_list)} totales",
                total_vlans=len(vlan_list),
                successful_vlans=successful_vlans,
                failed_vlans=failed_vlans,
                results={key: value.dict() for key, value in all_results.items()}
            )
            
        except Exception as e:
            logger.error(f"Error reanudando rango: {str(e)}")
            return ResumeRangeResponse(
                success=False,
                message=f"Error interno: {str(e)}",
                total_vlans=0,
                successful_vlans=0,
                failed_vlans=0,
                results={}
            )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5804)
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import jwt
import httpx
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
import os
from concurrent.futures import ThreadPoolExecutor

app = FastAPI(
    title="Slice Manager API", 
    version="1.0.0",
    description="API para gestionar slices (VLANs) en múltiples workers - Pausar, Reanudar y Eliminar"
)

# Configuración JWT (debe coincidir con auth_api)
JWT_SECRET = os.getenv('JWT_SECRET_KEY', 'mi_clave_secreta_super_segura_12345')
JWT_ALGORITHM = 'HS256'

# Configuración de workers
WORKERS = {
    'worker1': '10.0.10.2',
    'worker2': '10.0.10.3', 
    'worker3': '10.0.10.4'
}
WORKER_PORT = 5805
WORKER_TOKEN = "clavesihna"  # Token para autenticarse con pre_vlan_api

security = HTTPBearer()
thread_pool = ThreadPoolExecutor(max_workers=20)

# Modelos Pydantic
class SliceOperationRequest(BaseModel):
    slice_id: int = Field(..., ge=1, le=4094, description="ID del slice (VLAN) a gestionar")

class CleanupRequest(BaseModel):
    slice_id: int = Field(..., ge=1, le=4094, description="ID del slice (VLAN) a eliminar")
    bridge_name: str = Field(default="br-cloud", description="Nombre del bridge (siempre br-cloud)")

class WorkerResponse(BaseModel):
    worker: str
    success: bool
    message: str
    details: Optional[Dict[str, Any]] = None

class SliceOperationResponse(BaseModel):
    operation: str
    slice_id: int
    overall_success: bool
    workers_contacted: int
    successful_workers: int
    failed_workers: int
    results: List[WorkerResponse]
    summary: str

class SliceStatusResponse(BaseModel):
    slice_id: int
    workers_status: List[Dict[str, Any]]
    total_vms: int
    running_vms: int
    paused_vms: int

# Función para verificar y decodificar JWT
def verify_jwt_token(token: str) -> dict:
    """Verificar y decodificar el token JWT"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        
        # Verificar expiración explícitamente
        exp_timestamp = payload.get('exp')
        if exp_timestamp:
            exp_datetime = datetime.utcfromtimestamp(exp_timestamp)
            if datetime.utcnow() > exp_datetime:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token expirado"
                )
        
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expirado"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido"
        )

# Función para obtener usuario actual desde JWT
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Obtener información del usuario actual desde el JWT"""
    token = credentials.credentials
    payload = verify_jwt_token(token)
    return payload

# Función para hacer petición a un worker específico
async def call_worker_api(worker_ip: str, worker_name: str, endpoint: str, payload: dict) -> WorkerResponse:
    """Hacer petición HTTP a un worker específico"""
    try:
        url = f"http://{worker_ip}:{WORKER_PORT}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {WORKER_TOKEN}",
            "Content-Type": "application/json"
        }
        
        timeout = httpx.Timeout(30.0)  # 30 segundos timeout
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                return WorkerResponse(
                    worker=worker_name,
                    success=data.get('success', False),
                    message=data.get('message', 'Operación completada'),
                    details=data
                )
            else:
                return WorkerResponse(
                    worker=worker_name,
                    success=False,
                    message=f"Error HTTP {response.status_code}: {response.text}",
                    details={"status_code": response.status_code, "response": response.text}
                )
                
    except httpx.TimeoutException:
        return WorkerResponse(
            worker=worker_name,
            success=False,
            message="Timeout conectando con el worker",
            details={"error": "timeout"}
        )
    except Exception as e:
        return WorkerResponse(
            worker=worker_name,
            success=False,
            message=f"Error conectando con el worker: {str(e)}",
            details={"error": str(e)}
        )

# Función para obtener status de un worker específico
async def get_worker_status(worker_ip: str, worker_name: str, slice_id: int) -> dict:
    """Obtener status de un slice en un worker específico"""
    try:
        url = f"http://{worker_ip}:{WORKER_PORT}/status/{slice_id}"
        headers = {"Authorization": f"Bearer {WORKER_TOKEN}"}
        
        timeout = httpx.Timeout(15.0)
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "worker": worker_name,
                    "success": True,
                    "exists": data.get('exists', False),
                    "total_vms": data.get('total_count', 0),
                    "running_vms": data.get('running_count', 0),
                    "paused_vms": data.get('total_count', 0) - data.get('running_count', 0),
                    "vms": data.get('vms', [])
                }
            else:
                return {
                    "worker": worker_name,
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                    "exists": False,
                    "total_vms": 0,
                    "running_vms": 0,
                    "paused_vms": 0,
                    "vms": []
                }
                
    except Exception as e:
        return {
            "worker": worker_name,
            "success": False,
            "error": str(e),
            "exists": False,
            "total_vms": 0,
            "running_vms": 0,
            "paused_vms": 0,
            "vms": []
        }

# Función para ejecutar operación en todos los workers
async def execute_on_all_workers(operation: str, slice_id: int, extra_params: dict = None) -> SliceOperationResponse:
    """Ejecutar una operación en todos los workers concurrentemente"""
    
    # Preparar payload base
    if operation == "cleanup":
        payload = {
            "vlan_id": slice_id,
            **(extra_params or {})
        }
    else:
        payload = {"vlan_id": slice_id}
    
    # Crear tareas para todos los workers
    tasks = []
    for worker_name, worker_ip in WORKERS.items():
        task = call_worker_api(worker_ip, worker_name, operation, payload)
        tasks.append(task)
    
    # Ejecutar todas las tareas concurrentemente
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Procesar resultados
    worker_responses = []
    successful_count = 0
    
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            worker_name = list(WORKERS.keys())[i]
            worker_responses.append(WorkerResponse(
                worker=worker_name,
                success=False,
                message=f"Error ejecutando operación: {str(result)}",
                details={"exception": str(result)}
            ))
        else:
            worker_responses.append(result)
            if result.success:
                successful_count += 1
    
    # Determinar éxito general
    overall_success = successful_count > 0  # Al menos un worker exitoso
    failed_count = len(WORKERS) - successful_count
    
    # Generar resumen
    if successful_count == len(WORKERS):
        summary = f"Operación '{operation}' exitosa en todos los workers"
    elif successful_count > 0:
        summary = f"Operación '{operation}' exitosa en {successful_count}/{len(WORKERS)} workers"
    else:
        summary = f"Operación '{operation}' falló en todos los workers"
    
    return SliceOperationResponse(
        operation=operation,
        slice_id=slice_id,
        overall_success=overall_success,
        workers_contacted=len(WORKERS),
        successful_workers=successful_count,
        failed_workers=failed_count,
        results=worker_responses,
        summary=summary
    )

# Endpoints
@app.get("/")
async def root():
    return {
        "message": "Slice Manager API",
        "status": "activo",
        "description": "API para gestionar slices (VLANs) en múltiples workers",
        "version": "1.0.0",
        "workers": list(WORKERS.keys()),
        "operations": ["pause", "resume", "cleanup", "status"]
    }

@app.get("/health")
async def health_check():
    """Endpoint de verificación de salud"""
    return {
        "status": "OK",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "slice_manager_api",
        "workers_configured": len(WORKERS)
    }

@app.get("/status/{slice_id}", response_model=SliceStatusResponse)
async def get_slice_status(
    slice_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Obtener el status de un slice en todos los workers
    """
    try:
        if not 1 <= slice_id <= 4094:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Slice ID debe estar entre 1 y 4094"
            )
        
        # Obtener status de todos los workers concurrentemente
        tasks = []
        for worker_name, worker_ip in WORKERS.items():
            task = get_worker_status(worker_ip, worker_name, slice_id)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Procesar resultados
        workers_status = []
        total_vms = 0
        running_vms = 0
        paused_vms = 0
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                worker_name = list(WORKERS.keys())[i]
                workers_status.append({
                    "worker": worker_name,
                    "success": False,
                    "error": str(result),
                    "exists": False,
                    "total_vms": 0,
                    "running_vms": 0,
                    "paused_vms": 0
                })
            else:
                workers_status.append(result)
                if result["success"]:
                    total_vms += result["total_vms"]
                    running_vms += result["running_vms"]
                    paused_vms += result["paused_vms"]
        
        return SliceStatusResponse(
            slice_id=slice_id,
            workers_status=workers_status,
            total_vms=total_vms,
            running_vms=running_vms,
            paused_vms=paused_vms
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error obteniendo status del slice: {str(e)}"
        )

@app.post("/pause", response_model=SliceOperationResponse)
async def pause_slice(
    request: SliceOperationRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Pausar un slice en todos los workers
    """
    try:
        if not 1 <= request.slice_id <= 4094:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Slice ID debe estar entre 1 y 4094"
            )
        
        result = await execute_on_all_workers("pause", request.slice_id)
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error pausando slice: {str(e)}"
        )

@app.post("/resume", response_model=SliceOperationResponse)
async def resume_slice(
    request: SliceOperationRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Reanudar un slice en todos los workers
    """
    try:
        if not 1 <= request.slice_id <= 4094:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Slice ID debe estar entre 1 y 4094"
            )
        
        result = await execute_on_all_workers("resume", request.slice_id)
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reanudando slice: {str(e)}"
        )

@app.post("/cleanup", response_model=SliceOperationResponse)
async def cleanup_slice(
    request: CleanupRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Eliminar/limpiar un slice en todos los workers
    """
    try:
        if not 1 <= request.slice_id <= 4094:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Slice ID debe estar entre 1 y 4094"
            )
        
        # Para cleanup, necesitamos pasar parámetros adicionales
        # Aunque en el código original no veo que usen bridge_name, 
        # lo mantengo por si acaso
        extra_params = {}
        if hasattr(request, 'bridge_name'):
            extra_params['bridge_name'] = request.bridge_name
        
        result = await execute_on_all_workers("cleanup", request.slice_id, extra_params)
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error eliminando slice: {str(e)}"
        )



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5900)

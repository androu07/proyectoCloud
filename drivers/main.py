from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Dict, Any, Optional
import httpx
import os
import logging
from datetime import datetime

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
        'host': '192.168.203.2',
        'port': 5805,
        'base_url': 'http://192.168.203.2:5805'
    },
    'openstack': {
        'host': 'TBD',
        'port': 0,
        'base_url': None  # Por implementar
    }
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
    deployment_details: Optional[Dict[str, Any]] = None
    processed_json: Optional[Dict[str, Any]] = None
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

# Autenticación
def get_service_auth(credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
    """Verificar token de servicio"""
    if credentials.credentials != SERVICE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de servicio inválido"
        )
    return True

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

async def deploy_to_linux(json_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Despliega un slice en el cluster Linux
    
    Llama al endpoint /desplegar-slice del orquestador_api.py
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
        
        # Extraer el JSON procesado del deployment_details
        deployment_details = response_data.get('deployment_details', {})
        processed_json = deployment_details.get('processed_config', json_config)
        
        return {
            'success': True,
            'message': response_data.get('message', 'Despliegue exitoso'),
            'deployment_details': deployment_details,
            'processed_json': processed_json
        }
    else:
        logger.error(f"Error en despliegue Linux: {response_data.get('message')}")
        return {
            'success': False,
            'message': 'Error durante el despliegue en cluster Linux',
            'error': response_data.get('message', 'Unknown deployment error'),
            'deployment_details': response_data.get('deployment_details'),
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
        
        # Extraer slice_id
        solicitud_json = json_config.get('solicitud_json', {})
        slice_id_str = solicitud_json.get('id_slice')
        
        try:
            slice_id = int(slice_id_str) if slice_id_str else None
        except (ValueError, TypeError):
            slice_id = None
        
        if not slice_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El campo 'solicitud_json.id_slice' es requerido"
            )
        
        logger.info(f"Procesando despliegue de slice {slice_id} en zona '{zona_despliegue}'")
        
        # Validar zona soportada
        if zona_despliegue not in ORCHESTRATORS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zona de despliegue '{zona_despliegue}' no soportada. Zonas válidas: {list(ORCHESTRATORS.keys())}"
            )
        
        # Validar que el orquestador esté configurado
        if zona_despliegue == 'openstack' and ORCHESTRATORS['openstack']['base_url'] is None:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Orquestador OpenStack aún no implementado"
            )
        
        # Desplegar según zona
        if zona_despliegue == 'linux':
            result = await deploy_to_linux(json_config)
        else:
            # Placeholder para OpenStack
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Despliegue en OpenStack no implementado aún"
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
            # Error durante el despliegue → ejecutar rollback
            logger.error(f"Error en despliegue, ejecutando rollback para slice {slice_id}")
            
            # Intentar eliminar slice
            if zona_despliegue == 'linux':
                delete_result = await delete_from_linux(slice_id)
            else:
                delete_result = {'success': False, 'message': 'Rollback no implementado para esta zona'}
            
            error_message = f"Problema al desplegar slice {slice_id}. "
            if delete_result.get('success'):
                error_message += "Rollback ejecutado exitosamente (recursos limpiados)."
            else:
                error_message += f"Advertencia: Rollback falló - {delete_result.get('message')}"
            
            return DeploySliceResponse(
                success=False,
                message=error_message,
                zone=zona_despliegue,
                slice_id=slice_id,
                deployment_details={
                    'deployment_error': result.get('error'),
                    'rollback_executed': delete_result.get('success', False),
                    'rollback_details': delete_result
                },
                error=result.get('error', 'Deployment failed')
            )
        
        else:
            # Despliegue exitoso
            logger.info(f"Despliegue exitoso para slice {slice_id}")
            
            return DeploySliceResponse(
                success=True,
                message=f"Slice {slice_id} desplegado exitosamente en {zona_despliegue}",
                zone=zona_despliegue,
                slice_id=slice_id,
                deployment_details=result.get('deployment_details'),
                processed_json=result.get('processed_json')
            )
        
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
        else:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Eliminación en OpenStack no implementada aún"
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=6200, workers=2)

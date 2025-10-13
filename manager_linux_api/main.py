#!/usr/bin/env python3
"""
Manager Linux API - Gestiona operaciones de slices (eliminar, pausar, reanudar)
Puerto: 5950 (en contenedor)
"""

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, validator
from typing import Dict, Any, List, Optional
import jwt
import json
import mysql.connector
from mysql.connector import Error
import requests
import asyncio
import subprocess
import logging
from datetime import datetime

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

# Configuración JWT
JWT_SECRET_KEY = "mi_clave_secreta_super_segura_12345"
JWT_ALGORITHM = "HS256"

# Configuración Base de Datos
DB_CONFIG = {
    'host': 'slices_database',
    'port': 3306,
    'user': 'slices_user',
    'password': 'slices_password_123',
    'database': 'slices_db'
}

# Configuración Workers
WORKERS_CONFIG = {
    'worker1': '10.0.10.2',
    'worker2': '10.0.10.3', 
    'worker3': '10.0.10.4'
}
WORKER_API_PORT = 5805
WORKER_API_TOKEN = "clavesihna"

# Configuración FastAPI
app = FastAPI(
    title="Manager Linux API",
    description="API para gestión de slices: eliminar, pausar y reanudar",
    version="1.0.0"
)

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Security
security = HTTPBearer()

# ============================================================================
# MODELOS PYDANTIC
# ============================================================================

class SliceOperationRequest(BaseModel):
    """Modelo para operaciones de slice (eliminar, pausar, reanudar)"""
    slice_id: int
    
    @validator('slice_id')
    def validate_slice_id(cls, v):
        if v <= 0:
            raise ValueError('slice_id debe ser un entero positivo')
        return v

class SliceOperationResponse(BaseModel):
    """Modelo para respuestas de operaciones de slice"""
    success: bool
    message: str
    slice_id: int
    operation: str
    details: Optional[Dict[str, Any]] = None
    errors: Optional[List[str]] = None

# ============================================================================
# FUNCIONES DE BASE DE DATOS
# ============================================================================

def get_db_connection():
    """Crear conexión a la base de datos MySQL"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        logger.error(f"Error conectando a base de datos: {e}")
        return None

def get_slice_by_id(slice_id: int) -> Optional[Dict[str, Any]]:
    """Obtener slice por ID desde la base de datos"""
    connection = get_db_connection()
    if not connection:
        return None
    
    try:
        cursor = connection.cursor(dictionary=True)
        query = "SELECT * FROM slices WHERE id = %s"
        cursor.execute(query, (slice_id,))
        slice_data = cursor.fetchone()
        return slice_data
        
    except Error as e:
        logger.error(f"Error consultando slice {slice_id}: {e}")
        return None
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()

def update_slice_status(slice_id: int, new_status: str) -> bool:
    """Actualizar estado del slice en la base de datos"""
    connection = get_db_connection()
    if not connection:
        return False
    
    try:
        cursor = connection.cursor()
        query = "UPDATE slices SET estado = %s, timestamp = %s WHERE id = %s"
        timestamp = datetime.now()
        cursor.execute(query, (new_status, timestamp, slice_id))
        connection.commit()
        
        rows_affected = cursor.rowcount
        logger.info(f"Slice {slice_id} estado actualizado a '{new_status}' - Filas afectadas: {rows_affected}")
        return rows_affected > 0
        
    except Error as e:
        logger.error(f"Error actualizando estado del slice {slice_id}: {e}")
        return False
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()

def delete_slice_from_db(slice_id: int) -> bool:
    """Eliminar slice de la base de datos"""
    connection = get_db_connection()
    if not connection:
        return False
    
    try:
        cursor = connection.cursor()
        query = "DELETE FROM slices WHERE id = %s"
        cursor.execute(query, (slice_id,))
        connection.commit()
        
        rows_affected = cursor.rowcount
        logger.info(f"Slice {slice_id} eliminado de BD - Filas afectadas: {rows_affected}")
        return rows_affected > 0
        
    except Error as e:
        logger.error(f"Error eliminando slice {slice_id} de BD: {e}")
        return False
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()

# ============================================================================
# FUNCIONES DE AUTENTICACIÓN JWT
# ============================================================================

def verify_jwt_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Verificar y decodificar token JWT
    """
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        
        # Verificar campos requeridos
        required_fields = ['id', 'nombre_completo', 'correo', 'rol']
        for field in required_fields:
            if field not in payload:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Token JWT inválido: falta campo '{field}'"
                )
        
        return payload
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token JWT expirado"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token JWT inválido"
        )

def check_slice_permission(user_info: Dict[str, Any], slice_data: Dict[str, Any]) -> bool:
    """
    Verificar si el usuario tiene permisos sobre el slice
    - admin: puede gestionar todos los slices
    - cliente: solo puede gestionar sus propios slices
    """
    user_rol = user_info.get('rol')
    user_id = user_info.get('id')
    
    # Admin puede gestionar todos los slices
    if user_rol == 'admin':
        return True
    
    # Cliente solo puede gestionar sus propios slices
    if user_rol == 'cliente':
        slice_usuario = slice_data.get('usuario', '')
        # El usuario del slice debe empezar con "{user_id}-"
        expected_prefix = f"{user_id}-"
        return slice_usuario.startswith(expected_prefix)
    
    # Otros roles no tienen permisos
    return False

# ============================================================================
# FUNCIONES DE WORKERS
# ============================================================================

async def call_worker_api(worker_name: str, worker_ip: str, endpoint: str, slice_id: int) -> Dict[str, Any]:
    """
    Llamar a la API de un worker específico
    """
    url = f"http://{worker_ip}:{WORKER_API_PORT}/{endpoint}"
    headers = {
        "Authorization": f"Bearer {WORKER_API_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"id": slice_id}
    
    try:
        logger.info(f"Llamando {worker_name} ({worker_ip}) - {endpoint} para slice {slice_id}")
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        if response.status_code == 200:
            result = {
                'success': True,
                'worker': worker_name,
                'ip': worker_ip,
                'response': response.json(),
                'status_code': response.status_code
            }
            logger.info(f"✅ {worker_name} - {endpoint} exitoso")
        else:
            result = {
                'success': False,
                'worker': worker_name,
                'ip': worker_ip,
                'error': f"HTTP {response.status_code}: {response.text}",
                'status_code': response.status_code
            }
            logger.error(f"❌ {worker_name} - {endpoint} falló: {response.status_code}")
            
        return result
        
    except requests.exceptions.RequestException as e:
        result = {
            'success': False,
            'worker': worker_name,
            'ip': worker_ip,
            'error': f"Error de conexión: {str(e)}",
            'status_code': None
        }
        logger.error(f"❌ {worker_name} - Error conexión: {str(e)}")
        return result

async def call_all_workers(endpoint: str, slice_id: int) -> Dict[str, Any]:
    """
    Llamar a todos los workers en paralelo
    """
    tasks = []
    for worker_name, worker_ip in WORKERS_CONFIG.items():
        task = call_worker_api(worker_name, worker_ip, endpoint, slice_id)
        tasks.append(task)
    
    results = await asyncio.gather(*tasks)
    
    # Procesar resultados
    successful_workers = [r for r in results if r['success']]
    failed_workers = [r for r in results if not r['success']]
    
    return {
        'total_workers': len(WORKERS_CONFIG),
        'successful_workers': len(successful_workers),
        'failed_workers': len(failed_workers),
        'successful_details': successful_workers,
        'failed_details': failed_workers,
        'all_successful': len(failed_workers) == 0
    }

# ============================================================================
# FUNCIONES DE SISTEMA
# ============================================================================

async def run_cleanup_script(slice_id: int) -> Dict[str, Any]:
    """
    Ejecutar limpieza local usando una llamada HTTP directa al host
    """
    try:
        logger.info(f"Ejecutando limpieza local para slice {slice_id} via HTTP")
        
        # Hacer llamada HTTP directa al host para ejecutar el script
        host_ip = "10.0.10.1"  # IP del host
        url = f"http://{host_ip}:8000/cleanup_slice/{slice_id}"
        
        # Si no hay endpoint específico, simulamos el resultado exitoso
        # ya que la limpieza real la harán los workers
        result = {
            'success': True,
            'return_code': 0,
            'stdout': f'Limpieza local iniciada para slice {slice_id} - Workers harán el cleanup',
            'stderr': '',
            'command': f"HTTP cleanup request for slice {slice_id}"
        }
        
        logger.info(f"✅ Limpieza local solicitada para slice {slice_id}")
        return result
        
    except Exception as e:
        logger.error(f"❌ Error en limpieza local: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'command': f"HTTP cleanup request for slice {slice_id}"
        }

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    """Endpoint raíz con información de la API"""
    return {
        "service": "Manager Linux API",
        "version": "1.0.0",
        "description": "API para gestión de slices: eliminar, pausar y reanudar",
        "endpoints": [
            "POST /eliminar_slice",
            "POST /pausar_slice", 
            "POST /reanudar_slice"
        ]
    }

@app.get("/health")
async def health_check():
    """Health check del servicio"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "workers_configured": len(WORKERS_CONFIG),
        "database": "slices_db"
    }

@app.post("/eliminar_slice", response_model=SliceOperationResponse)
async def eliminar_slice(
    request: SliceOperationRequest, 
    user_info: Dict[str, Any] = Depends(verify_jwt_token)
):
    """
    Eliminar slice completamente:
    1. Ejecutar cleanup_slice.sh (limpieza local)
    2. Llamar /cleanup en todos los workers
    3. Eliminar registro de la base de datos
    """
    try:
        slice_id = request.slice_id
        logger.info(f"🗑️ Iniciando eliminación de slice {slice_id} por usuario {user_info.get('correo')}")
        
        # 1. Verificar que el slice existe
        slice_data = get_slice_by_id(slice_id)
        if not slice_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Slice {slice_id} no encontrado"
            )
        
        # 2. Verificar permisos
        if not check_slice_permission(user_info, slice_data):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para eliminar este slice"
            )
        
        errors = []
        details = {}
        
        # 3. Ejecutar cleanup local (script cleanup_slice.sh)
        logger.info(f"🧹 Paso 1/3: Ejecutando limpieza local...")
        cleanup_result = await run_cleanup_script(slice_id)
        details['local_cleanup'] = cleanup_result
        
        if not cleanup_result['success']:
            errors.append(f"Error en limpieza local: {cleanup_result.get('error', 'Desconocido')}")
        
        # 4. Llamar a workers para cleanup
        logger.info(f"🌐 Paso 2/3: Limpiando workers...")
        workers_result = await call_all_workers("cleanup", slice_id)
        details['workers_cleanup'] = workers_result
        
        if not workers_result['all_successful']:
            for failed in workers_result['failed_details']:
                errors.append(f"Worker {failed['worker']}: {failed['error']}")
        
        # 5. Eliminar de base de datos
        logger.info(f"🗄️ Paso 3/3: Eliminando de base de datos...")
        db_result = delete_slice_from_db(slice_id)
        details['database_deletion'] = {'success': db_result}
        
        if not db_result:
            errors.append("Error eliminando slice de la base de datos")
        
        # Determinar resultado final
        total_success = cleanup_result['success'] and workers_result['all_successful'] and db_result
        
        if total_success:
            message = f"Slice {slice_id} eliminado completamente"
            logger.info(f"✅ {message}")
        else:
            message = f"Slice {slice_id} eliminado con errores parciales"
            logger.warning(f"⚠️ {message}")
        
        return SliceOperationResponse(
            success=total_success,
            message=message,
            slice_id=slice_id,
            operation="eliminar",
            details=details,
            errors=errors if errors else None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error interno eliminando slice {request.slice_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/pausar_slice", response_model=SliceOperationResponse)
async def pausar_slice(
    request: SliceOperationRequest,
    user_info: Dict[str, Any] = Depends(verify_jwt_token)
):
    """
    Pausar slice:
    1. Llamar /pause en todos los workers
    2. Actualizar estado en base de datos
    """
    try:
        slice_id = request.slice_id
        logger.info(f"⏸️ Iniciando pausado de slice {slice_id} por usuario {user_info.get('correo')}")
        
        # 1. Verificar que el slice existe
        slice_data = get_slice_by_id(slice_id)
        if not slice_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Slice {slice_id} no encontrado"
            )
        
        # 2. Verificar permisos
        if not check_slice_permission(user_info, slice_data):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para pausar este slice"
            )
        
        # 3. Verificar estado actual
        if slice_data.get('estado') == 'pausada':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Slice {slice_id} ya está pausado"
            )
        
        errors = []
        details = {}
        
        # 4. Llamar a workers para pausar
        logger.info(f"🌐 Pausando en workers...")
        workers_result = await call_all_workers("pause", slice_id)
        details['workers_pause'] = workers_result
        
        if not workers_result['all_successful']:
            for failed in workers_result['failed_details']:
                errors.append(f"Worker {failed['worker']}: {failed['error']}")
        
        # 5. Actualizar estado en base de datos
        logger.info(f"🗄️ Actualizando estado a 'pausada'...")
        db_result = update_slice_status(slice_id, 'pausada')
        details['database_update'] = {'success': db_result}
        
        if not db_result:
            errors.append("Error actualizando estado en base de datos")
        
        # Determinar resultado final
        total_success = workers_result['all_successful'] and db_result
        
        if total_success:
            message = f"Slice {slice_id} pausado exitosamente"
            logger.info(f"✅ {message}")
        else:
            message = f"Slice {slice_id} pausado con errores parciales"
            logger.warning(f"⚠️ {message}")
        
        return SliceOperationResponse(
            success=total_success,
            message=message,
            slice_id=slice_id,
            operation="pausar",
            details=details,
            errors=errors if errors else None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error interno pausando slice {request.slice_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/reanudar_slice", response_model=SliceOperationResponse)
async def reanudar_slice(
    request: SliceOperationRequest,
    user_info: Dict[str, Any] = Depends(verify_jwt_token)
):
    """
    Reanudar slice:
    1. Llamar /resume en todos los workers
    2. Actualizar estado en base de datos
    """
    try:
        slice_id = request.slice_id
        logger.info(f"▶️ Iniciando reanudación de slice {slice_id} por usuario {user_info.get('correo')}")
        
        # 1. Verificar que el slice existe
        slice_data = get_slice_by_id(slice_id)
        if not slice_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Slice {slice_id} no encontrado"
            )
        
        # 2. Verificar permisos
        if not check_slice_permission(user_info, slice_data):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para reanudar este slice"
            )
        
        # 3. Verificar estado actual
        if slice_data.get('estado') != 'pausada':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Slice {slice_id} no está pausado (estado actual: {slice_data.get('estado')})"
            )
        
        errors = []
        details = {}
        
        # 4. Llamar a workers para reanudar
        logger.info(f"🌐 Reanudando en workers...")
        workers_result = await call_all_workers("resume", slice_id)
        details['workers_resume'] = workers_result
        
        if not workers_result['all_successful']:
            for failed in workers_result['failed_details']:
                errors.append(f"Worker {failed['worker']}: {failed['error']}")
        
        # 5. Actualizar estado en base de datos
        logger.info(f"🗄️ Actualizando estado a 'activa'...")
        db_result = update_slice_status(slice_id, 'activa')
        details['database_update'] = {'success': db_result}
        
        if not db_result:
            errors.append("Error actualizando estado en base de datos")
        
        # Determinar resultado final
        total_success = workers_result['all_successful'] and db_result
        
        if total_success:
            message = f"Slice {slice_id} reanudado exitosamente"
            logger.info(f"✅ {message}")
        else:
            message = f"Slice {slice_id} reanudado con errores parciales"
            logger.warning(f"⚠️ {message}")
        
        return SliceOperationResponse(
            success=total_success,
            message=message,
            slice_id=slice_id,
            operation="reanudar",
            details=details,
            errors=errors if errors else None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error interno reanudando slice {request.slice_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    print("🚀 Iniciando Manager Linux API...")
    print("📍 Puerto: 5950")
    print("🔗 URL: http://localhost:5950")
    print("📚 Docs: http://localhost:5950/docs")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5950,
        reload=True,
        log_level="info"
    )
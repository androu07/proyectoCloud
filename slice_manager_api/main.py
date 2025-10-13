#!/usr/bin/env python3
"""
Slice Manager API - Gestiona slices de red con validación JWT y conexión a orquestador
Puerto: 5900 (en contenedor)
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
from datetime import datetime
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Slice Manager API", 
    version="1.0.0",
    description="API para gestión de slices de red con validación JWT y orquestación automática"
)

# Configuración JWT (debe ser la misma que auth_api y orquestador_api)
JWT_SECRET_KEY = "mi_clave_secreta_super_segura_12345"
JWT_ALGORITHM = "HS256"

# Configuración de base de datos MySQL
DB_CONFIG = {
    'host': 'slices_database',
    'database': 'slices_db',
    'user': 'slices_user',
    'password': 'slices_password_123',
    'port': 3306,
    'charset': 'utf8mb4',
    'collation': 'utf8mb4_unicode_ci'
}

# Configuración del orquestador (desde contenedor al host)
ORQUESTADOR_URL = "http://host:5807"  # Hostname del host donde corre orquestador_api
ORQUESTADOR_ENDPOINTS = {
    'crear_topologia': f"{ORQUESTADOR_URL}/crear-topologia",
    'desplegar_slice': f"{ORQUESTADOR_URL}/desplegar-slice"
}

security = HTTPBearer()

# ============================================================================
# MODELOS PYDANTIC
# ============================================================================

class VMConfig(BaseModel):
    """Modelo para configuración de VM"""
    nombre: str
    cores: str
    ram: str
    almacenamiento: str
    puerto_vnc: str = ""
    image: str
    conexiones_vlans: str = ""
    acceso: str
    server: str = ""

class TopologiaConfig(BaseModel):
    """Modelo para configuración de topología"""
    nombre: str
    cantidad_vms: str
    internet: str
    vms: List[VMConfig]

class SolicitudJSON(BaseModel):
    """Modelo para el JSON de solicitud (sin id_slice)"""
    cantidad_vms: str = ""
    vlans_separadas: str = ""
    vlans_usadas: str = ""
    vncs_separadas: str = ""
    conexion_topologias: str = ""
    topologias: List[TopologiaConfig]
    
    @validator('topologias')
    def validate_topologias(cls, v):
        if not v or len(v) == 0:
            raise ValueError('Debe incluir al menos una topología')
        return v

class SolicitudCreacionRequest(BaseModel):
    """Modelo para la solicitud completa de creación"""
    nombre_slice: str
    solicitud_json: SolicitudJSON
    
    @validator('nombre_slice')
    def validate_nombre_slice(cls, v):
        if not v or not v.strip():
            raise ValueError('El nombre_slice no puede estar vacío')
        return v.strip()

class SolicitudCreacionResponse(BaseModel):
    """Modelo para la respuesta de solicitud de creación"""
    success: bool
    message: str
    slice_id: Optional[int] = None
    slice_details: Optional[Dict[str, Any]] = None
    orquestador_response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

# ============================================================================
# FUNCIONES DE BASE DE DATOS
# ============================================================================

def get_db_connection():
    """Crear conexión a la base de datos MySQL"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        logger.error(f"Error conectando a MySQL: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error de conexión a base de datos"
        )

def insert_slice_to_db(usuario: str, nombre_slice: str, vms_json: Dict[str, Any]) -> int:
    """Insertar slice en la base de datos y retornar el ID generado"""
    connection = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Insertar slice
        insert_query = """
        INSERT INTO slices (usuario, nombre_slice, vms, estado, timestamp) 
        VALUES (%s, %s, %s, %s, %s)
        """
        
        timestamp = datetime.now()
        cursor.execute(insert_query, (
            usuario,
            nombre_slice, 
            json.dumps(vms_json),
            'creado',
            timestamp
        ))
        
        # Obtener el ID generado
        slice_id = cursor.lastrowid
        connection.commit()
        
        logger.info(f"Slice creado en BD: ID={slice_id}, Usuario={usuario}, Nombre={nombre_slice}")
        return slice_id
        
    except Error as e:
        logger.error(f"Error insertando slice en BD: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error guardando slice en base de datos"
        )
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()

def update_slice_status_and_vms(slice_id: int, new_status: str, updated_vms: Dict[str, Any]) -> bool:
    """Actualizar estado y VMs del slice"""
    connection = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        update_query = """
        UPDATE slices 
        SET estado = %s, vms = %s, timestamp = %s
        WHERE id = %s
        """
        
        timestamp = datetime.now()
        cursor.execute(update_query, (
            new_status,
            json.dumps(updated_vms),
            timestamp,
            slice_id
        ))
        
        connection.commit()
        rows_affected = cursor.rowcount
        
        logger.info(f"Slice actualizado: ID={slice_id}, Estado={new_status}, Filas={rows_affected}")
        return rows_affected > 0
        
    except Error as e:
        logger.error(f"Error actualizando slice en BD: {e}")
        return False
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()

# ============================================================================
# FUNCIONES DE VALIDACIÓN JWT
# ============================================================================

def verify_jwt_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Verificar token JWT del auth_api
    """
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        
        # Verificar que el token no haya expirado
        exp = payload.get("exp")
        if exp and datetime.utcnow().timestamp() > exp:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token caducado o inválido"
            )
        
        return payload
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token caducado o inválido"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token caducado o inválido"
        )

def format_user_from_token(token_payload: Dict[str, Any]) -> str:
    """
    Formatear usuario desde token JWT: {id}-{nombre_completo}
    """
    try:
        user_id = token_payload.get("id")
        nombre_completo = token_payload.get("nombre_completo", "")
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token JWT no contiene ID de usuario válido"
            )
        
        if not nombre_completo:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token JWT no contiene nombre_completo válido"
            )
        
        return f"{user_id}-{nombre_completo}"
        
    except Exception as e:
        logger.error(f"Error formateando usuario desde token: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error procesando información de usuario del token"
        )

# ============================================================================
# FUNCIONES DE COMUNICACIÓN CON ORQUESTADOR
# ============================================================================

async def send_to_orquestador(json_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enviar JSON al orquestador para despliegue
    """
    try:
        logger.info(f"Enviando al orquestador: slice_id={json_data.get('id_slice')}")
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        # Enviar al endpoint de despliegue completo
        response = requests.post(
            ORQUESTADOR_ENDPOINTS['desplegar_slice'],
            json={'json_config': json_data},
            headers=headers,
            timeout=300  # 5 minutos de timeout
        )
        
        response_data = response.json()
        
        logger.info(f"Respuesta orquestador: status={response.status_code}, success={response_data.get('success')}")
        
        return {
            'status_code': response.status_code,
            'success': response_data.get('success', False),
            'message': response_data.get('message', ''),
            'details': response_data
        }
        
    except requests.exceptions.Timeout:
        logger.error("Timeout comunicándose con orquestador")
        return {
            'status_code': 408,
            'success': False,
            'message': 'Timeout comunicándose con orquestador',
            'details': {'error': 'timeout'}
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Error comunicándose con orquestador: {e}")
        return {
            'status_code': 500,
            'success': False,
            'message': f'Error comunicándose con orquestador: {str(e)}',
            'details': {'error': str(e)}
        }

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    """Endpoint de prueba"""
    return {
        "service": "Slice Manager API",
        "version": "1.0.0",
        "status": "running",
        "port": 5900,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health_check():
    """Health check"""
    return {
        "status": "healthy",
        "service": "slice_manager_api",
        "timestamp": datetime.now().isoformat()
    }

@app.post("/solicitud_creacion", response_model=SolicitudCreacionResponse)
async def solicitud_creacion(
    request: SolicitudCreacionRequest,
    user_info: dict = Depends(verify_jwt_token)
):
    """
    Endpoint principal: Crear solicitud de slice con validación JWT y orquestación
    
    Flujo:
    1. Valida token JWT (no caducado, válido)
    2. Valida nombre_slice (no vacío)
    3. Valida estructura JSON de solicitud
    4. Guarda en BD con estado 'creado'
    5. Rellena id_slice en JSON
    6. Actualiza VMs en BD
    7. Envía a orquestador para despliegue
    8. Actualiza estado según respuesta del orquestador
    
    Parámetros:
    - Authorization: Bearer <JWT_TOKEN> (header)
    - nombre_slice: Nombre del slice (no vacío)
    - solicitud_json: JSON con estructura de topologías (sin id_slice)
    
    Retorna:
    - Detalles del slice creado y respuesta del orquestador
    """
    try:
        logger.info(f"Nueva solicitud de creación de slice")
        logger.info(f"Usuario: {user_info.get('correo', 'N/A')}")
        logger.info(f"Nombre slice: {request.nombre_slice}")
        
        # 1. Formatear usuario desde token
        usuario_formateado = format_user_from_token(user_info)
        logger.info(f"Usuario formateado: {usuario_formateado}")
        
        # 2. Convertir solicitud_json a dict y preparar para BD
        solicitud_dict = request.solicitud_json.dict()
        
        # 3. Guardar en BD (sin id_slice aún)
        slice_id = insert_slice_to_db(
            usuario=usuario_formateado,
            nombre_slice=request.nombre_slice,
            vms_json=solicitud_dict
        )
        
        # 4. Rellenar id_slice en el JSON
        solicitud_dict["id_slice"] = str(slice_id)
        
        # 5. Actualizar VMs en BD con id_slice incluido
        update_slice_status_and_vms(slice_id, 'creado', solicitud_dict)
        
        # 6. Enviar al orquestador para despliegue
        logger.info(f"Enviando slice {slice_id} al orquestador")
        orquestador_response = await send_to_orquestador(solicitud_dict)
        
        # 7. Actualizar estado según respuesta del orquestador
        if orquestador_response['success']:
            # Despliegue exitoso - actualizar estado a 'activa'
            # También actualizar con el JSON procesado del orquestador si está disponible
            processed_json = solicitud_dict
            
            # DEBUG: Log de la estructura de respuesta del orquestador
            logger.info(f"DEBUG: Estructura orquestador_response keys: {orquestador_response.keys()}")
            if 'details' in orquestador_response:
                logger.info(f"DEBUG: Estructura details keys: {orquestador_response['details'].keys()}")
                if 'deployment_details' in orquestador_response['details']:
                    logger.info(f"DEBUG: Estructura deployment_details keys: {orquestador_response['details']['deployment_details'].keys()}")
            
            # Buscar processed_config en diferentes ubicaciones posibles
            if 'details' in orquestador_response and 'processed_config' in orquestador_response['details']:
                processed_json = orquestador_response['details']['processed_config']
                logger.info(f"DEBUG: Encontrado processed_config en details")
            elif 'details' in orquestador_response and 'deployment_details' in orquestador_response['details'] and 'processed_config' in orquestador_response['details']['deployment_details']:
                processed_json = orquestador_response['details']['deployment_details']['processed_config']
                logger.info(f"DEBUG: Encontrado processed_config en deployment_details")
            else:
                logger.warning(f"DEBUG: No se encontró processed_config, usando JSON original")
            
            update_slice_status_and_vms(slice_id, 'activa', processed_json)
            
            logger.info(f"Slice {slice_id} desplegado exitosamente - estado: activa")
            
            return SolicitudCreacionResponse(
                success=True,
                message=f"Slice '{request.nombre_slice}' creado y desplegado exitosamente",
                slice_id=slice_id,
                slice_details={
                    'id': slice_id,
                    'usuario': usuario_formateado,
                    'nombre_slice': request.nombre_slice,
                    'estado': 'activa',
                    'timestamp': datetime.now().isoformat()
                },
                orquestador_response=orquestador_response
            )
        else:
            # Error en despliegue - mantener estado 'creado' y reportar error
            logger.warning(f"Error en despliegue de slice {slice_id}: {orquestador_response['message']}")
            
            return SolicitudCreacionResponse(
                success=False,
                message=f"Slice '{request.nombre_slice}' creado pero falló el despliegue: {orquestador_response['message']}",
                slice_id=slice_id,
                slice_details={
                    'id': slice_id,
                    'usuario': usuario_formateado,
                    'nombre_slice': request.nombre_slice,
                    'estado': 'creado',
                    'timestamp': datetime.now().isoformat()
                },
                orquestador_response=orquestador_response,
                error="deployment_failed"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error interno en solicitud_creacion: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )

@app.get("/listar_slices")
async def listar_slices(user_info: Dict[str, Any] = Depends(verify_jwt_token)):
    """
    Listar slices según el rol del usuario:
    - admin: Ve todos los slices
    - cliente: Solo ve sus propios slices (donde el ID del JWT coincida con el ID del slice)
    """
    try:
        user_id = user_info.get("id")
        user_rol = user_info.get("rol", "cliente")
        
        logger.info(f"Listando slices - Usuario ID: {user_id}, Rol: {user_rol}")
        
        connection = get_db_connection()
        if not connection:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error conectando a la base de datos"
            )
        
        cursor = connection.cursor(dictionary=True)
        
        if user_rol == "admin":
            # Admin ve todos los slices
            query = "SELECT * FROM slices ORDER BY timestamp DESC"
            cursor.execute(query)
            logger.info("Admin: Consultando todos los slices")
        else:
            # Cliente solo ve sus propios slices
            # Filtramos por slices que comiencen con "{user_id}-"
            query = "SELECT * FROM slices WHERE usuario LIKE %s ORDER BY timestamp DESC"
            cursor.execute(query, (f"{user_id}-%",))
            logger.info(f"Cliente ID {user_id}: Consultando solo sus slices")
        
        slices = cursor.fetchall()
        
        # Procesar los resultados para convertir JSON strings a objetos
        processed_slices = []
        for slice_data in slices:
            processed_slice = dict(slice_data)
            
            # Convertir el campo 'vms' de JSON string a objeto
            if processed_slice.get('vms'):
                try:
                    processed_slice['vms'] = json.loads(processed_slice['vms'])
                except json.JSONDecodeError as e:
                    logger.warning(f"Error parseando JSON en slice {processed_slice['id']}: {e}")
                    processed_slice['vms'] = {}
            
            # Convertir timestamp a string ISO si es datetime
            if processed_slice.get('timestamp'):
                if isinstance(processed_slice['timestamp'], datetime):
                    processed_slice['timestamp'] = processed_slice['timestamp'].isoformat()
            
            processed_slices.append(processed_slice)
        
        result = {
            "success": True,
            "message": f"Slices recuperados exitosamente para rol '{user_rol}'",
            "total_slices": len(processed_slices),
            "slices": processed_slices,
            "user_info": {
                "id": user_id,
                "rol": user_rol,
                "correo": user_info.get("correo", "")
            }
        }
        
        logger.info(f"Slices listados exitosamente: {len(processed_slices)} slices para usuario {user_id} (rol: {user_rol})")
        return result
        
    except HTTPException:
        raise
    except Error as e:
        logger.error(f"Error de base de datos en listar_slices: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error consultando slices en la base de datos"
        )
    except Exception as e:
        logger.error(f"Error interno en listar_slices: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()

# ============================================================================
# FUNCIONES DE COMUNICACIÓN CON MANAGER LINUX
# ============================================================================

async def call_manager_linux(operation: str, slice_id: int, jwt_token: str) -> Dict[str, Any]:
    """
    Llamar al Manager Linux API para operaciones de slice
    """
    try:
        manager_linux_url = "http://manager_linux:5950"  # Manager Linux container
        url = f"{manager_linux_url}/{operation}_slice"
        
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json"
        }
        payload = {"slice_id": slice_id}
        
        logger.info(f"Llamando Manager Linux: {operation} slice {slice_id}")
        
        response = requests.post(url, json=payload, headers=headers, timeout=120)
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"✅ Manager Linux - {operation} slice {slice_id} exitoso")
            return {
                'success': True,
                'status_code': response.status_code,
                'data': result
            }
        else:
            error_msg = f"HTTP {response.status_code}"
            try:
                error_data = response.json()
                error_msg = error_data.get('detail', error_msg)
            except:
                error_msg = response.text
            
            logger.error(f"❌ Manager Linux - {operation} slice {slice_id} falló: {error_msg}")
            return {
                'success': False,
                'status_code': response.status_code,
                'error': error_msg
            }
            
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error comunicación con Manager Linux: {str(e)}")
        return {
            'success': False,
            'status_code': None,
            'error': f"Error de conexión: {str(e)}"
        }

# ============================================================================
# MODELOS PARA NUEVOS ENDPOINTS
# ============================================================================

class SliceActionRequest(BaseModel):
    """Modelo para acciones de slice (pausar, reanudar, eliminar)"""
    slice_id: int
    
    @validator('slice_id')
    def validate_slice_id(cls, v):
        if v <= 0:
            raise ValueError('slice_id debe ser un entero positivo')
        return v

class SliceActionResponse(BaseModel):
    """Modelo para respuestas de acciones de slice"""
    success: bool
    message: str
    slice_id: int
    operation: str
    manager_linux_response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

# ============================================================================
# NUEVOS ENDPOINTS DE GESTIÓN DE SLICES
# ============================================================================

@app.post("/pausar_slice", response_model=SliceActionResponse)
async def pausar_slice(
    request: SliceActionRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Pausar un slice usando Manager Linux API
    """
    try:
        slice_id = request.slice_id
        jwt_token = credentials.credentials
        
        logger.info(f"⏸️ Solicitud pausar slice {slice_id}")
        
        # Llamar al Manager Linux API
        result = await call_manager_linux("pausar", slice_id, jwt_token)
        
        if result['success']:
            return SliceActionResponse(
                success=True,
                message=f"Slice {slice_id} pausado exitosamente",
                slice_id=slice_id,
                operation="pausar",
                manager_linux_response=result['data']
            )
        else:
            return SliceActionResponse(
                success=False,
                message=f"Error pausando slice {slice_id}",
                slice_id=slice_id,
                operation="pausar",
                error=result['error']
            )
            
    except Exception as e:
        logger.error(f"Error interno pausando slice {request.slice_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/reanudar_slice", response_model=SliceActionResponse)
async def reanudar_slice(
    request: SliceActionRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Reanudar un slice usando Manager Linux API
    """
    try:
        slice_id = request.slice_id
        jwt_token = credentials.credentials
        
        logger.info(f"▶️ Solicitud reanudar slice {slice_id}")
        
        # Llamar al Manager Linux API
        result = await call_manager_linux("reanudar", slice_id, jwt_token)
        
        if result['success']:
            return SliceActionResponse(
                success=True,
                message=f"Slice {slice_id} reanudado exitosamente",
                slice_id=slice_id,
                operation="reanudar",
                manager_linux_response=result['data']
            )
        else:
            return SliceActionResponse(
                success=False,
                message=f"Error reanudando slice {slice_id}",
                slice_id=slice_id,
                operation="reanudar",
                error=result['error']
            )
            
    except Exception as e:
        logger.error(f"Error interno reanudando slice {request.slice_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/eliminar_slice", response_model=SliceActionResponse)
async def eliminar_slice(
    request: SliceActionRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Eliminar un slice usando Manager Linux API
    """
    try:
        slice_id = request.slice_id
        jwt_token = credentials.credentials
        
        logger.info(f"🗑️ Solicitud eliminar slice {slice_id}")
        
        # Llamar al Manager Linux API
        result = await call_manager_linux("eliminar", slice_id, jwt_token)
        
        if result['success']:
            return SliceActionResponse(
                success=True,
                message=f"Slice {slice_id} eliminado exitosamente",
                slice_id=slice_id,
                operation="eliminar",
                manager_linux_response=result['data']
            )
        else:
            return SliceActionResponse(
                success=False,
                message=f"Error eliminando slice {slice_id}",
                slice_id=slice_id,
                operation="eliminar",
                error=result['error']
            )
            
    except Exception as e:
        logger.error(f"Error interno eliminando slice {request.slice_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    print("🚀 Iniciando Slice Manager API...")
    print("📍 Puerto: 5900")
    print("🔗 URL: http://localhost:5900")
    print("📚 Docs: http://localhost:5900/docs")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5900,
        reload=True,
        log_level="info"
    )

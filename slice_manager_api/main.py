from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, validator
import jwt
import os
import httpx
from typing import Optional, Any, List
import json
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Slice Manager API - Gateway de Seguridad",
    version="1.0.0",
    description="Middleware de autenticación y autorización para todas las APIs"
)

# Configuración
JWT_SECRET = os.getenv('JWT_SECRET_KEY', 'mi_clave_secreta_super_segura_12345')
JWT_ALGORITHM = 'HS256'
IMAGE_MANAGER_URL = os.getenv('IMAGE_MANAGER_URL', 'http://image_manager_api:5700')
IMAGE_MANAGER_TOKEN = os.getenv('IMAGE_MANAGER_TOKEN', 'clavesihna')
QUEUE_MANAGER_URL = os.getenv('QUEUE_MANAGER_URL', 'http://queue_manager:6100')
DRIVERS_URL = os.getenv('DRIVERS_URL', 'http://drivers:6200')

# Configuración de BD
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'slices_db'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'database': os.getenv('DB_NAME', 'slices_db'),
    'user': os.getenv('DB_USER', 'slices_user'),
    'password': os.getenv('DB_PASSWORD', 'slices_pass123')
}

security = HTTPBearer()

# ==================== MODELOS ====================
class UserPayload(BaseModel):
    id: int
    nombre_completo: str
    correo: str
    rol: str
    exp: int
    iat: int

# Modelos para creación de slices
class VMConfig(BaseModel):
    nombre: str
    cores: str
    ram: str
    almacenamiento: str
    puerto_vnc: str = ""
    image: str
    conexiones_vlans: str = ""
    internet: str
    server: str = ""
    
    @validator('internet')
    def validate_internet(cls, v):
        if v not in ['si', 'no']:
            raise ValueError('internet debe ser "si" o "no"')
        return v

class Topologia(BaseModel):
    nombre: str
    cantidad_vms: str
    vms: List[VMConfig]
    
    @validator('cantidad_vms')
    def validate_cantidad_vms(cls, v):
        try:
            cantidad = int(v)
            if cantidad < 2 or cantidad > 6:
                raise ValueError('cantidad_vms debe ser entre 2 y 6')
        except ValueError as e:
            if 'invalid literal' in str(e):
                raise ValueError('cantidad_vms debe ser un número')
            raise e
        return v

class SolicitudJSON(BaseModel):
    id_slice: str = ""
    cantidad_vms: str
    vlans_separadas: str = ""
    vlans_usadas: str = ""
    vncs_separadas: str = ""
    conexion_topologias: str = ""
    topologias: List[Topologia]
    
    @validator('cantidad_vms')
    def validate_cantidad_vms(cls, v):
        try:
            cantidad = int(v)
            if cantidad < 2 or cantidad > 11:
                raise ValueError('cantidad_vms debe ser entre 2 y 11')
        except ValueError as e:
            if 'invalid literal' in str(e):
                raise ValueError('cantidad_vms debe ser un número')
            raise e
        return v
    
    @validator('id_slice')
    def validate_id_slice_empty(cls, v):
        if v != "":
            raise ValueError('id_slice debe estar vacío en la petición inicial')
        return v
    
    @validator('vlans_separadas', 'vlans_usadas', 'vncs_separadas')
    def validate_empty_fields(cls, v):
        if v != "":
            raise ValueError('Este campo debe estar vacío en la petición inicial')
        return v
    
    @validator('topologias')
    def validate_topologias(cls, v):
        if len(v) < 1 or len(v) > 3:
            raise ValueError('Debe haber entre 1 y 3 topologías')
        return v

class SliceCreationRequest(BaseModel):
    nombre_slice: str
    zona_despliegue: str
    solicitud_json: SolicitudJSON
    
    @validator('zona_despliegue')
    def validate_zona_despliegue(cls, v):
        if v not in ['linux', 'openstack']:
            raise ValueError('zona_despliegue debe ser "linux" o "openstack"')
        return v

# Verificar y decodificar JWT
def verify_jwt_token(token: str) -> dict:
    """Verificar token JWT y retornar payload"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
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

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Obtener usuario actual desde JWT"""
    return verify_jwt_token(credentials.credentials)

def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Verificar que el usuario tenga rol de admin"""
    if user.get('rol') != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado: se requieren privilegios de administrador"
        )
    return user

# Función para hacer proxy a image_manager_api
async def proxy_to_image_manager(
    method: str,
    path: str,
    data: Optional[dict] = None,
    files: Optional[dict] = None,
    params: Optional[dict] = None
) -> tuple[int, Any]:
    """
    Hacer proxy de la petición al image_manager_api
    Retorna: (status_code, response_data)
    """
    url = f"{IMAGE_MANAGER_URL}{path}"
    headers = {
        "Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"
    }
    
    try:
        async with httpx.AsyncClient(timeout=300.0, verify=False) as client:
            if method == "GET":
                response = await client.get(url, headers=headers, params=params)
            elif method == "POST":
                if files:
                    response = await client.post(url, headers=headers, files=files, data=data)
                else:
                    headers["Content-Type"] = "application/json"
                    response = await client.post(url, headers=headers, json=data)
            elif method == "DELETE":
                response = await client.delete(url, headers=headers)
            else:
                raise HTTPException(
                    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                    detail=f"Método {method} no soportado"
                )
            
            # Intentar parsear como JSON
            try:
                response_data = response.json()
            except:
                response_data = {"message": response.text}
            
            return response.status_code, response_data
            
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timeout al comunicarse con image_manager_api"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Error al comunicarse con image_manager_api: {str(e)}"
        )

# ==================== ENDPOINTS RAÍZ ====================

@app.get("/")
async def root():
    return {
        "message": "Slice Manager API - Gateway de Seguridad",
        "status": "activo",
        "version": "1.0.0",
        "endpoints": {
            "image_manager": "/img-mngr/*"
        }
    }

@app.get("/health")
async def health_check():
    return {
        "status": "OK",
        "services": {
            "image_manager_api": IMAGE_MANAGER_URL
        }
    }

# ==================== ENDPOINTS IMAGE MANAGER ====================

@app.post("/img-mngr/import-image")
async def import_image_from_url(
    request: Request,
    admin_user: dict = Depends(require_admin)
):
    """
    Importar imagen desde URL (solo admin)
    Proxy a: POST /import-image del image_manager_api
    """
    try:
        body = await request.json()
        status_code, response_data = await proxy_to_image_manager(
            method="POST",
            path="/import-image",
            data=body
        )
        
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=response_data)
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/img-mngr/upload-image")
async def upload_image_file(
    request: Request,
    admin_user: dict = Depends(require_admin)
):
    """
    Subir imagen como archivo (solo admin)
    Proxy a: POST /upload-image del image_manager_api
    """
    try:
        # Obtener form data
        form = await request.form()
        
        # Preparar files y data para el proxy
        files = {}
        data = {}
        
        for key, value in form.items():
            if hasattr(value, 'file'):  # Es un archivo
                files[key] = (value.filename, value.file, value.content_type)
            else:  # Es un campo normal
                data[key] = value
        
        status_code, response_data = await proxy_to_image_manager(
            method="POST",
            path="/upload-image",
            data=data,
            files=files
        )
        
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=response_data)
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.get("/img-mngr/list-images")
async def list_images(
    admin_user: dict = Depends(require_admin)
):
    """
    Listar todas las imágenes (solo admin)
    Proxy a: GET /list-images del image_manager_api
    """
    try:
        status_code, response_data = await proxy_to_image_manager(
            method="GET",
            path="/list-images"
        )
        
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=response_data)
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.delete("/img-mngr/delete-image/{image_id}")
async def delete_image(
    image_id: int,
    admin_user: dict = Depends(require_admin)
):
    """
    Eliminar imagen por ID (solo admin)
    Proxy a: DELETE /delete-image/{image_id} del image_manager_api
    """
    try:
        status_code, response_data = await proxy_to_image_manager(
            method="DELETE",
            path=f"/delete-image/{image_id}"
        )
        
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=response_data)
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.get("/img-mngr/download")
async def download_image(
    nombre: str,
    admin_user: dict = Depends(require_admin)
):
    """
    Descargar imagen por nombre (solo admin)
    Proxy a: GET /download?nombre={nombre} del image_manager_api
    """
    try:
        from fastapi.responses import StreamingResponse
        
        url = f"{IMAGE_MANAGER_URL}/download"
        headers = {"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
        params = {"nombre": nombre}
        
        async with httpx.AsyncClient(timeout=300.0, verify=False) as client:
            response = await client.get(url, headers=headers, params=params)
            
            if response.status_code >= 400:
                try:
                    error_data = response.json()
                except:
                    error_data = {"detail": response.text}
                raise HTTPException(status_code=response.status_code, detail=error_data)
            
            # Streaming de la descarga
            return StreamingResponse(
                iter([response.content]),
                media_type=response.headers.get('content-type', 'application/octet-stream'),
                headers={
                    'Content-Disposition': response.headers.get('Content-Disposition', f'attachment; filename="{nombre}.qcow2.zst"'),
                    'X-Image-Format': response.headers.get('X-Image-Format', 'qcow2.zst'),
                    'X-Image-Name': response.headers.get('X-Image-Name', nombre)
                }
            )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

# ==================== ENDPOINTS SLICE CREATION ====================

@app.post("/slices/create")
async def create_slice(
    slice_request: SliceCreationRequest,
    user: dict = Depends(get_current_user)
):
    """
    Crear un nuevo slice (requiere autenticación JWT)
    
    Flujo completo:
    1. Valida JSON y guarda slice en BD (estado: creando)
    2. Obtiene id_slice del auto-increment
    3. Envía a queue_manager para mapeo de workers
    4. Actualiza BD con JSON mapeado + timestamp_creacion
    5. Envía a drivers para despliegue en cluster
    6. Actualiza BD con JSON final + timestamp_despliegue
    """
    connection = None
    cursor = None
    slice_id = None
    
    try:
        # Validar conexion_topologias según número de topologías
        num_topologias = len(slice_request.solicitud_json.topologias)
        conexion_topologias = slice_request.solicitud_json.conexion_topologias
        
        if num_topologias == 1:
            if conexion_topologias != "":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="conexion_topologias debe estar vacío cuando solo hay 1 topología"
                )
        elif num_topologias == 2:
            if not conexion_topologias or '-' not in conexion_topologias:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="conexion_topologias debe tener formato 'vmX-vmY' cuando hay 2 topologías"
                )
            if ',' in conexion_topologias:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Solo debe haber una conexión entre topologías cuando hay 2 topologías"
                )
        elif num_topologias == 3:
            if not conexion_topologias or '-' not in conexion_topologias:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="conexion_topologias debe tener formato 'vmX-vmY,vmW-vmZ' cuando hay 3 topologías"
                )
        
        # Validar que cada VM tenga puerto_vnc, conexiones_vlans y server vacíos
        for topologia in slice_request.solicitud_json.topologias:
            for vm in topologia.vms:
                if vm.puerto_vnc != "":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"puerto_vnc de {vm.nombre} debe estar vacío en la petición inicial"
                    )
                if vm.conexiones_vlans != "":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"conexiones_vlans de {vm.nombre} debe estar vacío en la petición inicial"
                    )
                if vm.server != "":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"server de {vm.nombre} debe estar vacío en la petición inicial"
                    )
        
        # ==== PASO 1: Crear slice en BD (estado: creando) ====
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        insert_query = """
            INSERT INTO slices 
            (usuario, nombre_slice, tipo) 
            VALUES (%s, %s, %s)
        """
        cursor.execute(insert_query, (
            user['id'],
            slice_request.nombre_slice,
            'creando'
        ))
        connection.commit()
        
        # Obtener el ID generado
        slice_id = cursor.lastrowid
        logger.info(f"Slice {slice_id} creado en BD - Estado: creando")
        
        # Crear el JSON completo preservando el orden original
        request_dict = json.loads(slice_request.json())
        request_dict['solicitud_json']['id_slice'] = str(slice_id)
        
        # ==== PASO 2: Mapeo de workers (queue_manager + vm_placement) ====
        logger.info(f"Slice {slice_id}: Iniciando mapeo de workers...")
        
        try:
            # 2.1 Encolar en queue_manager
            async with httpx.AsyncClient(timeout=60.0) as client:
                enqueue_response = await client.post(
                    f"{QUEUE_MANAGER_URL}/enqueue-placement",
                    json=request_dict,
                    headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                )
                
                if enqueue_response.status_code != 200:
                    raise Exception(f"Error al encolar: {enqueue_response.text}")
            
            # 2.2 Procesar desde la cola (obtiene mapeo de workers)
            async with httpx.AsyncClient(timeout=60.0) as client:
                process_response = await client.post(
                    f"{QUEUE_MANAGER_URL}/process-from-queue",
                    headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                )
                
                if process_response.status_code != 200:
                    raise Exception(f"Error al procesar cola: {process_response.text}")
                
                result = process_response.json()
            
            # 2.3 Obtener el JSON con servers asignados
            mapped_json = result['result']['peticion_json']
            logger.info(f"Slice {slice_id}: Mapeo de workers completado")
            
        except Exception as e:
            logger.error(f"Slice {slice_id}: Error en mapeo de workers: {str(e)}")
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error en mapeo de workers: {str(e)}"
            )
        
        # ==== PASO 3: Guardar JSON mapeado + timestamp_creacion ====
        timestamp_creacion = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        update_query = """
            UPDATE slices 
            SET peticion_json = %s,
                timestamp_creacion = %s
            WHERE id = %s
        """
        cursor.execute(update_query, (
            json.dumps(mapped_json, ensure_ascii=False),
            timestamp_creacion,
            slice_id
        ))
        connection.commit()
        logger.info(f"Slice {slice_id}: JSON mapeado guardado con timestamp_creacion")
        
        # ==== PASO 4: Desplegar en cluster (drivers) ====
        logger.info(f"Slice {slice_id}: Iniciando despliegue en cluster {slice_request.zona_despliegue}...")
        
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:  # 5 min timeout para despliegue
                deploy_response = await client.post(
                    f"{DRIVERS_URL}/deploy-slice",
                    json={"json_config": mapped_json},
                    headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                )
                
                deploy_result = deploy_response.json()
                
                # Analizar respuesta
                if deploy_response.status_code != 200:
                    error_detail = deploy_result.get('detail', {})
                    
                    # Error de conexión con orquestador
                    if isinstance(error_detail, dict) and 'Conexión fallida' in error_detail.get('message', ''):
                        logger.error(f"Slice {slice_id}: Conexión fallida con orquestador")
                        cursor.close()
                        connection.close()
                        raise HTTPException(
                            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Conexión fallida con orquestador {slice_request.zona_despliegue}"
                        )
                    
                    # Error durante despliegue (ya se ejecutó rollback en drivers)
                    logger.error(f"Slice {slice_id}: Problema al desplegar - {error_detail}")
                    cursor.close()
                    connection.close()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=error_detail
                    )
                
                # Despliegue exitoso
                if not deploy_result.get('success'):
                    logger.error(f"Slice {slice_id}: Despliegue no exitoso")
                    cursor.close()
                    connection.close()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=deploy_result.get('error', 'Error desconocido en despliegue')
                    )
                
                logger.info(f"Slice {slice_id}: Despliegue completado exitosamente")
                
                # Obtener JSON procesado completo del orquestador
                processed_json = deploy_result.get('processed_json', mapped_json)
                
        except httpx.TimeoutException:
            logger.error(f"Slice {slice_id}: Timeout en despliegue")
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Timeout durante el despliegue (>5 minutos)"
            )
        except httpx.ConnectError:
            logger.error(f"Slice {slice_id}: Error de conexión con drivers")
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No se pudo conectar con el servicio de drivers"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Slice {slice_id}: Error inesperado en despliegue: {str(e)}")
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error inesperado durante el despliegue: {str(e)}"
            )
        
        # ==== PASO 5: Actualizar BD con JSON final + timestamp_despliegue + estado ====
        timestamp_despliegue = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        update_final_query = """
            UPDATE slices 
            SET peticion_json = %s,
                timestamp_despliegue = %s,
                tipo = %s,
                estado = %s
            WHERE id = %s
        """
        cursor.execute(update_final_query, (
            json.dumps(processed_json, ensure_ascii=False),
            timestamp_despliegue,
            'desplegado',
            'corriendo',
            slice_id
        ))
        connection.commit()
        logger.info(f"Slice {slice_id}: JSON final guardado con timestamp_despliegue - Estado: desplegado/corriendo")
        
        cursor.close()
        connection.close()
        
        return {
            "success": True,
            "message": f"Slice {slice_id} creado y desplegado exitosamente",
            "slice_id": slice_id,
            "nombre_slice": slice_request.nombre_slice,
            "zona_despliegue": slice_request.zona_despliegue,
            "usuario_id": user['id'],
            "usuario_correo": user['correo'],
            "tipo": "desplegado",
            "estado": "corriendo",
            "timestamp_creacion": timestamp_creacion,
            "timestamp_despliegue": timestamp_despliegue,
            "peticion_json": processed_json
        }
        
    except HTTPException:
        # Limpiar conexión si está abierta
        if cursor:
            cursor.close()
        if connection:
            connection.close()
        raise
    except Exception as e:
        logger.error(f"Error inesperado en create_slice: {str(e)}")
        if cursor:
            cursor.close()
        if connection:
            connection.close()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )
        
    except HTTPException:
        raise
    except Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en base de datos: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/slices/{slice_id}/process-placement")
async def process_placement(
    slice_id: int,
    user: dict = Depends(get_current_user)
):
    """
    Procesar placement de VMs para un slice
    1. Obtiene el JSON de la BD
    2. Lo envía al queue_manager
    3. Procesa desde la cola
    4. Actualiza la BD con los servers asignados
    """
    try:
        # Obtener el slice de la BD
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        query = "SELECT peticion_json FROM slices WHERE id = %s AND usuario = %s"
        cursor.execute(query, (slice_id, user['id']))
        slice_data = cursor.fetchone()
        
        if not slice_data:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Slice {slice_id} no encontrado o no pertenece al usuario"
            )
        
        peticion_json = json.loads(slice_data['peticion_json'])
        
        # 1. Encolar en queue_manager
        async with httpx.AsyncClient(timeout=60.0) as client:
            enqueue_response = await client.post(
                f"{QUEUE_MANAGER_URL}/enqueue-placement",
                json=peticion_json,
                headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
            )
            
            if enqueue_response.status_code != 200:
                raise HTTPException(
                    status_code=enqueue_response.status_code,
                    detail=f"Error al encolar: {enqueue_response.text}"
                )
        
        # 2. Procesar desde la cola
        async with httpx.AsyncClient(timeout=60.0) as client:
            process_response = await client.post(
                f"{QUEUE_MANAGER_URL}/process-from-queue",
                headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
            )
            
            if process_response.status_code != 200:
                raise HTTPException(
                    status_code=process_response.status_code,
                    detail=f"Error al procesar cola: {process_response.text}"
                )
            
            result = process_response.json()
        
        # 3. Actualizar BD con el JSON que incluye servers asignados
        updated_json = result['result']['peticion_json']
        
        update_query = "UPDATE slices SET peticion_json = %s WHERE id = %s"
        cursor.execute(update_query, (
            json.dumps(updated_json, ensure_ascii=False),
            slice_id
        ))
        connection.commit()
        
        cursor.close()
        connection.close()
        
        return {
            "success": True,
            "message": "Placement procesado y actualizado exitosamente",
            "slice_id": slice_id,
            "total_vms_assigned": result['result']['total_vms_assigned'],
            "workers_used": result['result']['workers_used']
        }
        
    except HTTPException:
        raise
    except Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en base de datos: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

# ==================== ENDPOINTS DE GESTIÓN DE SLICES ====================

@app.get("/slices/list")
async def list_slices(
    user: dict = Depends(get_current_user)
):
    """
    Listar slices según el rol del usuario
    
    - Cliente: Solo sus slices (donde usuario == user_id)
    - Admin: Todos los slices
    
    Solo se listan slices con tipo='desplegado'
    """
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        if user['rol'] == 'admin':
            # Admin ve todos los slices desplegados
            query = """
                SELECT id, usuario, nombre_slice, tipo, estado, 
                       timestamp_creacion, timestamp_despliegue
                FROM slices 
                WHERE tipo = 'desplegado'
                ORDER BY id DESC
            """
            cursor.execute(query)
        else:
            # Cliente solo ve sus slices desplegados
            query = """
                SELECT id, usuario, nombre_slice, tipo, estado,
                       timestamp_creacion, timestamp_despliegue
                FROM slices 
                WHERE tipo = 'desplegado' AND usuario = %s
                ORDER BY id DESC
            """
            cursor.execute(query, (user['id'],))
        
        slices = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        return {
            "success": True,
            "total_slices": len(slices),
            "usuario_rol": user['rol'],
            "slices": slices
        }
        
    except Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en base de datos: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/slices/delete/{slice_id}")
async def delete_slice(
    slice_id: int,
    user: dict = Depends(get_current_user)
):
    """
    Eliminar un slice
    
    - Cliente: Solo puede eliminar sus propios slices con tipo='desplegado'
    - Admin: Puede eliminar cualquier slice sin restricciones
    """
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener información del slice
        cursor.execute("SELECT * FROM slices WHERE id = %s", (slice_id,))
        slice_data = cursor.fetchone()
        
        if not slice_data:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Slice {slice_id} no encontrado"
            )
        
        # Validaciones según rol
        if user['rol'] != 'admin':
            # Cliente: verificar que sea su slice y esté desplegado
            if slice_data['usuario'] != user['id']:
                cursor.close()
                connection.close()
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No tiene permisos para eliminar este slice"
                )
            
            if slice_data['tipo'] != 'desplegado':
                cursor.close()
                connection.close()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Solo se pueden eliminar slices desplegados"
                )
        
        # Extraer zona_despliegue del peticion_json
        peticion_json = slice_data['peticion_json']
        if isinstance(peticion_json, str):
            peticion_json = json.loads(peticion_json)
        
        # Buscar zona_despliegue en la raíz o en solicitud_json
        zona_despliegue = peticion_json.get('zona_despliegue')
        if not zona_despliegue and 'solicitud_json' in peticion_json:
            zona_despliegue = peticion_json.get('zona_despliegue', 'linux')
        if not zona_despliegue:
            zona_despliegue = 'linux'  # Default
        
        logger.info(f"Eliminando slice {slice_id} de zona {zona_despliegue}")
        
        # Llamar a drivers para eliminar en el cluster
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                delete_response = await client.post(
                    f"{DRIVERS_URL}/delete-slice",
                    json={
                        "slice_id": slice_id,
                        "zona_despliegue": zona_despliegue
                    },
                    headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                )
                
                delete_result = delete_response.json()
                
                if delete_response.status_code != 200 or not delete_result.get('success'):
                    cursor.close()
                    connection.close()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Error al eliminar slice en cluster: {delete_result.get('error', 'Unknown error')}"
                    )
                
        except httpx.TimeoutException:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Timeout al eliminar slice en cluster"
            )
        except httpx.ConnectError:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No se pudo conectar con el servicio de drivers"
            )
        
        # Actualizar estado en BD
        update_query = "UPDATE slices SET estado = %s WHERE id = %s"
        cursor.execute(update_query, ('eliminado', slice_id))
        connection.commit()
        
        cursor.close()
        connection.close()
        
        logger.info(f"Slice {slice_id} eliminado exitosamente")
        
        return {
            "success": True,
            "message": f"Slice {slice_id} eliminado exitosamente",
            "slice_id": slice_id,
            "estado": "eliminado"
        }
        
    except HTTPException:
        raise
    except Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en base de datos: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/slices/pause/{slice_id}")
async def pause_slice(
    slice_id: int,
    user: dict = Depends(get_current_user)
):
    """
    Pausar un slice
    
    - Cliente: Solo puede pausar sus propios slices con tipo='desplegado'
    - Admin: Puede pausar cualquier slice sin restricciones
    """
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener información del slice
        cursor.execute("SELECT * FROM slices WHERE id = %s", (slice_id,))
        slice_data = cursor.fetchone()
        
        if not slice_data:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Slice {slice_id} no encontrado"
            )
        
        # Validaciones según rol
        if user['rol'] != 'admin':
            # Cliente: verificar que sea su slice y esté desplegado
            if slice_data['usuario'] != user['id']:
                cursor.close()
                connection.close()
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No tiene permisos para pausar este slice"
                )
            
            if slice_data['tipo'] != 'desplegado':
                cursor.close()
                connection.close()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Solo se pueden pausar slices desplegados"
                )
        
        # Extraer zona_despliegue
        peticion_json = slice_data['peticion_json']
        if isinstance(peticion_json, str):
            peticion_json = json.loads(peticion_json)
        
        zona_despliegue = peticion_json.get('zona_despliegue', 'linux')
        
        logger.info(f"Pausando slice {slice_id} de zona {zona_despliegue}")
        
        # Llamar a drivers para pausar en el cluster
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                pause_response = await client.post(
                    f"{DRIVERS_URL}/pause-slice",
                    json={
                        "slice_id": slice_id,
                        "zona_despliegue": zona_despliegue
                    },
                    headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                )
                
                pause_result = pause_response.json()
                
                if pause_response.status_code != 200 or not pause_result.get('success'):
                    cursor.close()
                    connection.close()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Error al pausar slice en cluster: {pause_result.get('error', 'Unknown error')}"
                    )
                
        except httpx.TimeoutException:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Timeout al pausar slice en cluster"
            )
        except httpx.ConnectError:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No se pudo conectar con el servicio de drivers"
            )
        
        # Actualizar estado en BD
        update_query = "UPDATE slices SET estado = %s WHERE id = %s"
        cursor.execute(update_query, ('pausado', slice_id))
        connection.commit()
        
        cursor.close()
        connection.close()
        
        logger.info(f"Slice {slice_id} pausado exitosamente")
        
        return {
            "success": True,
            "message": f"Slice {slice_id} pausado exitosamente",
            "slice_id": slice_id,
            "estado": "pausado"
        }
        
    except HTTPException:
        raise
    except Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en base de datos: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/slices/resume/{slice_id}")
async def resume_slice(
    slice_id: int,
    user: dict = Depends(get_current_user)
):
    """
    Reanudar un slice pausado
    
    - Cliente: Solo puede reanudar sus propios slices con tipo='desplegado'
    - Admin: Puede reanudar cualquier slice sin restricciones
    """
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener información del slice
        cursor.execute("SELECT * FROM slices WHERE id = %s", (slice_id,))
        slice_data = cursor.fetchone()
        
        if not slice_data:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Slice {slice_id} no encontrado"
            )
        
        # Validaciones según rol
        if user['rol'] != 'admin':
            # Cliente: verificar que sea su slice y esté desplegado
            if slice_data['usuario'] != user['id']:
                cursor.close()
                connection.close()
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No tiene permisos para reanudar este slice"
                )
            
            if slice_data['tipo'] != 'desplegado':
                cursor.close()
                connection.close()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Solo se pueden reanudar slices desplegados"
                )
        
        # Extraer zona_despliegue
        peticion_json = slice_data['peticion_json']
        if isinstance(peticion_json, str):
            peticion_json = json.loads(peticion_json)
        
        zona_despliegue = peticion_json.get('zona_despliegue', 'linux')
        
        logger.info(f"Reanudando slice {slice_id} de zona {zona_despliegue}")
        
        # Llamar a drivers para reanudar en el cluster
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resume_response = await client.post(
                    f"{DRIVERS_URL}/resume-slice",
                    json={
                        "slice_id": slice_id,
                        "zona_despliegue": zona_despliegue
                    },
                    headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                )
                
                resume_result = resume_response.json()
                
                if resume_response.status_code != 200 or not resume_result.get('success'):
                    cursor.close()
                    connection.close()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Error al reanudar slice en cluster: {resume_result.get('error', 'Unknown error')}"
                    )
                
        except httpx.TimeoutException:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Timeout al reanudar slice en cluster"
            )
        except httpx.ConnectError:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No se pudo conectar con el servicio de drivers"
            )
        
        # Actualizar estado en BD
        update_query = "UPDATE slices SET estado = %s WHERE id = %s"
        cursor.execute(update_query, ('corriendo', slice_id))
        connection.commit()
        
        cursor.close()
        connection.close()
        
        logger.info(f"Slice {slice_id} reanudado exitosamente")
        
        return {
            "success": True,
            "message": f"Slice {slice_id} reanudado exitosamente",
            "slice_id": slice_id,
            "estado": "corriendo"
        }
        
    except HTTPException:
        raise
    except Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en base de datos: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5900, workers=2)

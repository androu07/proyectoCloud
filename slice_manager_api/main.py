from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator, root_validator, ValidationError
import jwt
import os
import httpx
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import pytz
import json
import logging
from typing import List, Optional, Any
import re
import pika
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Slice Manager API - Nuevo Flujo",
    version="2.0.0",
    description="API mejorada para gestión de slices con validaciones exhaustivas"
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Manejador personalizado para errores de validación de Pydantic"""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "success": False,
            "error": "Formato de solicitud inválido",
            "message": "El JSON enviado no cumple con el formato esperado"
        }
    )

# Configuración
JWT_SECRET = os.getenv('JWT_SECRET_KEY', 'mi_clave_secreta_super_segura_12345')
JWT_ALGORITHM = 'HS256'
IMAGE_MANAGER_URL = os.getenv('IMAGE_MANAGER_URL', 'http://image_manager_api:5700')
IMAGE_MANAGER_TOKEN = os.getenv('IMAGE_MANAGER_TOKEN', 'clavesihna')
DRIVERS_URL = os.getenv('DRIVERS_URL', 'http://drivers:6200')
VM_PLACEMENT_URL = os.getenv('VM_PLACEMENT_URL', 'http://vm_placement_api:6000')

# Configuración RabbitMQ
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', 'rabbitmq')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', 5672))
RABBITMQ_USER = os.getenv('RABBITMQ_USER', 'guest')
RABBITMQ_PASS = os.getenv('RABBITMQ_PASS', 'guest')

# Nombres de colas
VLAN_QUEUE_LINUX = 'vlan_mapping_linux'
VLAN_QUEUE_OPENSTACK = 'vlan_mapping_openstack'
VM_PLACEMENT_QUEUE_LINUX = 'vm_placement_linux'
VM_PLACEMENT_QUEUE_OPENSTACK = 'vm_placement_openstack'

# Configuración de BD
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'slices_db'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'database': os.getenv('DB_NAME', 'slices_db'),
    'user': os.getenv('DB_USER', 'slices_user'),
    'password': os.getenv('DB_PASSWORD', 'slices_pass123')
}

security = HTTPBearer()

# ==================== AUTENTICACIÓN ====================

def get_service_auth(credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
    """Verificar token de servicio interno"""
    if credentials.credentials != IMAGE_MANAGER_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de servicio inválido"
        )
    return True

# ==================== FUNCIONES RABBITMQ ====================

def get_rabbitmq_connection():
    """Crear conexión a RabbitMQ con reintentos"""
    max_retries = 5
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
            parameters = pika.ConnectionParameters(
                host=RABBITMQ_HOST,
                port=RABBITMQ_PORT,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300
            )
            connection = pika.BlockingConnection(parameters)
            logger.info(f"Conexión a RabbitMQ establecida en intento {attempt + 1}")
            return connection
        except Exception as e:
            logger.warning(f"Intento {attempt + 1}/{max_retries} falló: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                raise Exception(f"No se pudo conectar a RabbitMQ después de {max_retries} intentos")

def ensure_queues_exist():
    """Asegurar que todas las colas existan"""
    try:
        connection = get_rabbitmq_connection()
        channel = connection.channel()
        
        # Declarar las 4 colas
        channel.queue_declare(queue=VLAN_QUEUE_LINUX, durable=True)
        channel.queue_declare(queue=VLAN_QUEUE_OPENSTACK, durable=True)
        channel.queue_declare(queue=VM_PLACEMENT_QUEUE_LINUX, durable=True)
        channel.queue_declare(queue=VM_PLACEMENT_QUEUE_OPENSTACK, durable=True)
        
        connection.close()
        logger.info("Todas las colas RabbitMQ verificadas/creadas")
    except Exception as e:
        logger.error(f"Error al crear colas: {str(e)}")

def publish_to_queue(queue_name: str, message: dict):
    """Publicar mensaje en una cola específica"""
    try:
        connection = get_rabbitmq_connection()
        channel = connection.channel()
        channel.queue_declare(queue=queue_name, durable=True)
        
        message_json = json.dumps(message)
        channel.basic_publish(
            exchange='',
            routing_key=queue_name,
            body=message_json,
            properties=pika.BasicProperties(
                delivery_mode=2,  # Mensaje persistente
            )
        )
        
        connection.close()
        logger.info(f"Mensaje publicado en cola '{queue_name}'")
        return True
    except Exception as e:
        logger.error(f"Error al publicar en cola '{queue_name}': {str(e)}")
        raise Exception(f"Error al publicar en RabbitMQ: {str(e)}")

@app.on_event("startup")
async def startup_event():
    """Inicializar colas al arrancar"""
    import asyncio
    await asyncio.sleep(3)  # Esperar a que RabbitMQ esté listo
    ensure_queues_exist()

# ==================== MODELOS PYDANTIC ====================

class VMConfig(BaseModel):
    nombre: str
    nombre_ui: str
    cores: str
    ram: str
    almacenamiento: str
    puerto_vnc: str = ""
    image: str
    conexiones_vlans: str = ""
    internet: str
    server: str = ""
    id_flavor_openstack: str = ""
    
    @validator('nombre')
    def validate_nombre(cls, v):
        if not re.match(r'^vm\d+$', v):
            raise ValueError('nombre debe tener formato vmX donde X es un número')
        return v
    
    @validator('nombre_ui')
    def validate_nombre_ui(cls, v):
        if len(v) < 3 or len(v) > 30:
            raise ValueError('nombre_ui debe tener entre 3 y 30 caracteres')
        return v
    
    @validator('cores')
    def validate_cores(cls, v):
        if v not in ['1', '2']:
            raise ValueError('cores debe ser "1" o "2"')
        return v
    
    @validator('ram')
    def validate_ram(cls, v):
        if v.endswith('M'):
            try:
                val = int(v[:-1])
                if val < 256 or val > 999:
                    raise ValueError('ram con M debe ser entre 256 y 999')
            except ValueError:
                raise ValueError('ram con M debe ser un número válido')
        elif v.endswith('G'):
            try:
                val = float(v[:-1])
                if val < 1.0 or val > 1.5:
                    raise ValueError('ram con G debe ser entre 1 y 1.5')
            except ValueError:
                raise ValueError('ram con G debe ser un número válido')
        else:
            raise ValueError('ram debe terminar en M o G')
        return v
    
    @validator('almacenamiento')
    def validate_almacenamiento(cls, v):
        if v not in ['1G', '2G', '4G']:
            raise ValueError('almacenamiento debe ser "1G", "2G" o "4G"')
        return v
    
    @validator('image')
    def validate_image(cls, v):
        if not v or v.strip() == "":
            raise ValueError('image no puede estar vacío')
        return v
    
    @validator('internet')
    def validate_internet(cls, v):
        if v not in ['si', 'no']:
            raise ValueError('internet debe ser "si" o "no"')
        return v
    
    @validator('puerto_vnc', 'conexiones_vlans', 'server')
    def validate_empty_fields(cls, v):
        if v != "":
            raise ValueError('Este campo debe estar vacío en la petición inicial')
        return v

class Topologia(BaseModel):
    nombre: str
    cantidad_vms: str
    vms: List[VMConfig]
    
    @validator('nombre')
    def validate_nombre(cls, v):
        if v not in ['1vm', 'lineal', 'arbol', 'anillo']:
            raise ValueError('nombre debe ser "1vm", "lineal", "arbol" o "anillo"')
        return v
    
    @validator('cantidad_vms')
    def validate_cantidad_vms(cls, v, values):
        try:
            cantidad = int(v)
            nombre_topo = values.get('nombre', '')
            
            if nombre_topo == '1vm' and cantidad < 1:
                raise ValueError('topología "1vm" debe tener al menos 1 VM')
            elif nombre_topo == 'lineal':
                if cantidad < 2 or cantidad > 12:
                    raise ValueError('topología "lineal" debe tener entre 2 y 12 VMs')
            elif nombre_topo == 'arbol':
                if cantidad < 5 or cantidad > 12:
                    raise ValueError('topología "arbol" debe tener entre 5 y 12 VMs')
            elif nombre_topo == 'anillo':
                if cantidad < 3 or cantidad > 12:
                    raise ValueError('topología "anillo" debe tener entre 3 y 12 VMs')
                    
        except ValueError as e:
            if 'invalid literal' in str(e):
                raise ValueError('cantidad_vms debe ser un número')
            raise e
        return v
    
    @root_validator(skip_on_failure=True)
    def validate_cantidad_matches_vms(cls, values):
        cantidad_vms = values.get('cantidad_vms')
        vms = values.get('vms', [])
        
        if cantidad_vms:
            try:
                cantidad = int(cantidad_vms)
                if len(vms) != cantidad:
                    raise ValueError(f'cantidad_vms ({cantidad}) no coincide con el número de VMs en la lista ({len(vms)})')
            except ValueError as e:
                if 'invalid literal' not in str(e):
                    raise e
        
        return values

class SolicitudJSON(BaseModel):
    id_slice: str = ""
    total_vms: str
    vlans_usadas: str = ""
    conexiones_vms: str
    topologias: List[Topologia]
    
    @validator('id_slice')
    def validate_id_slice_empty(cls, v):
        if v != "":
            raise ValueError('Este campo debe estar vacío en la petición inicial')
        return v
    
    @validator('total_vms')
    def validate_total_vms(cls, v):
        try:
            total = int(v)
            if total < 2 or total > 12:
                raise ValueError('total_vms debe ser entre 2 y 12')
        except ValueError as e:
            if 'invalid literal' in str(e):
                raise ValueError('total_vms debe ser un número')
            raise e
        return v
    
    @validator('vlans_usadas')
    def validate_empty_fields(cls, v):
        if v != "":
            raise ValueError('Este campo debe estar vacío en la petición inicial')
        return v
    
    @validator('topologias')
    def validate_topologias(cls, v):
        if len(v) < 1:
            raise ValueError('Debe haber al menos 1 topología')
        return v
    
    @root_validator(skip_on_failure=True)
    def validate_total_vms_matches(cls, values):
        """Verificar que total_vms coincida con la suma de VMs en todas las topologías"""
        total_vms = values.get('total_vms')
        topologias = values.get('topologias', [])
        
        if total_vms:
            try:
                total_esperado = int(total_vms)
                total_actual = sum(len(topo.vms) for topo in topologias)
                
                if total_actual != total_esperado:
                    raise ValueError(f'total_vms ({total_esperado}) no coincide con la suma de VMs en topologías ({total_actual})')
            except ValueError as e:
                if 'invalid literal' not in str(e):
                    raise e
        
        return values
    
    @root_validator(skip_on_failure=True)
    def validate_vm_names_unique(cls, values):
        """Verificar que no haya nombres de VMs duplicados"""
        topologias = values.get('topologias', [])
        nombres_vms = []
        
        for topo in topologias:
            for vm in topo.vms:
                if vm.nombre in nombres_vms:
                    raise ValueError(f'Nombre de VM duplicado: {vm.nombre}')
                nombres_vms.append(vm.nombre)
        
        return values
    
    @root_validator(skip_on_failure=True)
    def validate_conexiones_vms(cls, values):
        """Validar formato y conectividad de conexiones_vms"""
        conexiones_vms = values.get('conexiones_vms', '')
        topologias = values.get('topologias', [])
        
        # Si solo hay 1 topología, conexiones_vms puede estar vacío
        if len(topologias) == 1:
            return values
        
        if not conexiones_vms or conexiones_vms.strip() == '':
            raise ValueError('conexiones_vms no puede estar vacío cuando hay más de 1 topología')
        
        # Obtener todas las VMs
        todas_vms = []
        for topo in topologias:
            todas_vms.extend([vm.nombre for vm in topo.vms])
        
        # Validar formato de conexiones
        conexiones = conexiones_vms.split(';')
        vms_conectadas = set()
        
        for conexion in conexiones:
            if not conexion.strip():
                continue
                
            if '-' not in conexion:
                raise ValueError(f'Conexión inválida: {conexion}. Formato debe ser vmX-vmY')
            
            partes = conexion.split('-')
            if len(partes) != 2:
                raise ValueError(f'Conexión inválida: {conexion}. Debe tener exactamente una conexión vmX-vmY')
            
            vm1, vm2 = partes[0].strip(), partes[1].strip()
            
            # Verificar formato vmX
            if not re.match(r'^vm\d+$', vm1) or not re.match(r'^vm\d+$', vm2):
                raise ValueError(f'Conexión inválida: {conexion}. Debe usar formato vmX')
            
            # Verificar que no sean la misma VM
            if vm1 == vm2:
                raise ValueError(f'Una VM no puede conectarse consigo misma: {conexion}')
            
            # Verificar que las VMs existan
            if vm1 not in todas_vms:
                raise ValueError(f'VM {vm1} en conexión no existe')
            if vm2 not in todas_vms:
                raise ValueError(f'VM {vm2} en conexión no existe')
            
            vms_conectadas.add(vm1)
            vms_conectadas.add(vm2)
        
        # Verificar que haya al menos una conexión entre topologías
        if len(topologias) > 1:
            # Agrupar VMs por topología
            vms_por_topo = []
            for topo in topologias:
                vms_por_topo.append(set([vm.nombre for vm in topo.vms]))
            
            # Verificar que haya al menos una conexión entre cada par de topologías
            hay_conexion_inter_topo = False
            for conexion in conexiones:
                if not conexion.strip():
                    continue
                vm1, vm2 = conexion.split('-')
                vm1, vm2 = vm1.strip(), vm2.strip()
                
                # Verificar si conecta diferentes topologías
                for i, topo1_vms in enumerate(vms_por_topo):
                    for j, topo2_vms in enumerate(vms_por_topo):
                        if i != j:
                            if (vm1 in topo1_vms and vm2 in topo2_vms) or (vm2 in topo1_vms and vm1 in topo2_vms):
                                hay_conexion_inter_topo = True
                                break
            
            if not hay_conexion_inter_topo:
                raise ValueError('Debe existir al menos una conexión entre diferentes topologías')
        
        return values

class SliceCreationRequest(BaseModel):
    nombre_slice: str
    zona_despliegue: str
    solicitud_json: SolicitudJSON
    
    @validator('nombre_slice')
    def validate_nombre_slice(cls, v):
        if len(v) < 3 or len(v) > 200:
            raise ValueError('nombre_slice debe tener entre 3 y 200 caracteres')
        return v
    
    @validator('zona_despliegue')
    def validate_zona_despliegue(cls, v):
        if v not in ['linux', 'openstack']:
            raise ValueError('zona_despliegue debe ser "linux" o "openstack"')
        return v
    
    @root_validator(skip_on_failure=True)
    def validate_flavor_openstack(cls, values):
        """Validar que id_flavor_openstack no esté vacío si zona es openstack"""
        zona = values.get('zona_despliegue')
        solicitud = values.get('solicitud_json')
        
        if zona == 'openstack' and solicitud:
            for topo in solicitud.topologias:
                for vm in topo.vms:
                    if not vm.id_flavor_openstack or vm.id_flavor_openstack.strip() == "":
                        raise ValueError(f'VM {vm.nombre}: id_flavor_openstack no puede estar vacío cuando zona_despliegue es "openstack"')
        
        return values

# ==================== AUTENTICACIÓN ====================

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

# ==================== FUNCIONES AUXILIARES ====================

def update_slice_state_based_on_vms(cursor, connection, slice_id: int, vms: list) -> str:
    """
    Actualizar el estado del slice según el estado de sus VMs
    
    Reglas:
    - Si al menos una VM está "Corriendo" → slice "corriendo"
    - Si todas las VMs están "Pausado" → slice "pausado"
    - Si todas las VMs están "Apagado" → slice "apagado"
    
    Returns:
        El nuevo estado del slice
    """
    if not vms:
        return "corriendo"  # Default si no hay VMs
    
    vm_states = [vm.get('estado', 'Corriendo') for vm in vms]
    
    # Contar estados
    corriendo_count = vm_states.count('Corriendo')
    pausado_count = vm_states.count('Pausado')
    apagado_count = vm_states.count('Apagado')
    
    total_vms = len(vm_states)
    
    # Determinar estado del slice
    if corriendo_count > 0:
        # Al menos una VM corriendo → slice corriendo
        new_state = 'corriendo'
    elif pausado_count == total_vms:
        # Todas las VMs pausadas → slice pausado
        new_state = 'pausado'
    elif apagado_count == total_vms:
        # Todas las VMs apagadas → slice apagado
        new_state = 'apagado'
    else:
        # Estado mixto (pausado + apagado) → default corriendo
        new_state = 'corriendo'
    
    # Actualizar estado en BD
    update_query = "UPDATE slices SET estado = %s WHERE id = %s"
    cursor.execute(update_query, (new_state, slice_id))
    connection.commit()
    
    logger.info(f"Slice {slice_id}: Estado actualizado a '{new_state}' (VMs: {corriendo_count} corriendo, {pausado_count} pausadas, {apagado_count} apagadas)")
    
    return new_state

# ==================== ENDPOINTS ====================

@app.get("/")
async def root():
    return {
        "message": "Slice Manager API - Nuevo Flujo v2.0",
        "status": "activo",
        "version": "2.0.0"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "OK",
        "service": "slice_manager_api",
        "version": "2.0.0",
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
    Crear un nuevo slice con validación exhaustiva y mapeo automático
    
    Flujo:
    1. Validar estructura JSON completa (automático con Pydantic)
    2. Guardar en BD con tipo='validado', estado=''
    3. Obtener slice_id generado
    4. Publicar en RabbitMQ para mapeo de VLANs (según zona)
    5. Retornar confirmación (procesamiento asíncrono)
    """
    connection = None
    cursor = None
    slice_id = None
    
    try:
        # ===== PASO 1: Guardar slice en BD =====
        lima_tz = pytz.timezone('America/Lima')
        timestamp_creacion = datetime.now(lima_tz).strftime("%Y-%m-%d %H:%M:%S")
        
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        peticion_json_str = json.dumps(
            json.loads(slice_request.json())['solicitud_json'],
            ensure_ascii=False
        )
        
        insert_query = """
            INSERT INTO slices 
            (usuario, nombre_slice, tipo, estado, zona_disponibilidad, peticion_json, timestamp_creacion) 
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, (
            user['id'],
            slice_request.nombre_slice,
            'validado',
            'encolado',
            slice_request.zona_despliegue,
            peticion_json_str,
            timestamp_creacion
        ))
        connection.commit()
        
        slice_id = cursor.lastrowid
        logger.info(f"Slice {slice_id} creado - Zona: {slice_request.zona_despliegue}")
        
        cursor.close()
        connection.close()
        
        # ===== PASO 2: Publicar en cola de VLANs según zona =====
        zona = slice_request.zona_despliegue
        vlan_queue = VLAN_QUEUE_LINUX if zona == 'linux' else VLAN_QUEUE_OPENSTACK
        
        vlan_message = {
            "slice_id": slice_id,
            "nombre_slice": slice_request.nombre_slice,
            "zona_despliegue": zona,
            "usuario_id": user['id']
        }
        
        try:
            publish_to_queue(vlan_queue, vlan_message)
            logger.info(f"Slice {slice_id}: Publicado en cola '{vlan_queue}' para mapeo de VLANs")
        except Exception as e:
            logger.error(f"Slice {slice_id}: Error al publicar en RabbitMQ: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al encolar slice: {str(e)}"
            )
        
        # ===== RETORNAR CONFIRMACIÓN =====
        # NOTA: Cambio de comportamiento - ahora hace polling hasta que termine
        logger.info(f"Slice {slice_id}: Iniciando polling cada 5s (máx 5 minutos)")
        
        import asyncio
        max_attempts = 60  # 60 intentos * 5s = 5 minutos
        attempt = 0
        
        while attempt < max_attempts:
            await asyncio.sleep(5)  # Esperar 5 segundos
            attempt += 1
            
            # Consultar estado en BD
            try:
                conn_poll = mysql.connector.connect(**DB_CONFIG)
                cur_poll = conn_poll.cursor(dictionary=True)
                cur_poll.execute("SELECT estado, tipo FROM slices WHERE id = %s", (slice_id,))
                slice_status = cur_poll.fetchone()
                cur_poll.close()
                conn_poll.close()
                
                if not slice_status:
                    logger.error(f"Slice {slice_id} desapareció de BD")
                    break
                
                estado = slice_status['estado']
                tipo = slice_status['tipo']
                
                logger.info(f"Slice {slice_id}: Polling {attempt}/{max_attempts} - estado={estado}, tipo={tipo}")
                
                # ===== CASO 1: DESPLIEGUE EXITOSO =====
                if estado == 'corriendo' and tipo == 'desplegado':
                    logger.info(f"Slice {slice_id}: ¡Desplegado exitosamente!")
                    return {
                        "success": True,
                        "message": f"Slice {slice_id} desplegado exitosamente",
                        "slice_id": slice_id,
                        "nombre_slice": slice_request.nombre_slice,
                        "zona_despliegue": zona,
                        "estado": "corriendo",
                        "tipo": "desplegado",
                        "polling_attempts": attempt
                    }
                
                # ===== CASO 2: ERROR EN DESPLIEGUE =====
                if tipo == 'error' or estado == 'error_despliegue':
                    logger.error(f"Slice {slice_id}: Error en despliegue, iniciando rollback...")
                    
                    # Hacer rollback completo: eliminar todo
                    try:
                        async with httpx.AsyncClient(timeout=120.0) as client:
                            rollback_response = await client.post(
                                f"{DRIVERS_URL}/delete-slice",
                                json={
                                    "slice_id": slice_id,
                                    "zona_despliegue": zona
                                },
                                headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                            )
                            logger.info(f"Slice {slice_id}: Rollback cluster: {rollback_response.json()}")
                    except Exception as rb_error:
                        logger.warning(f"Slice {slice_id}: Error en rollback cluster: {str(rb_error)}")
                    
                    # Eliminar security groups
                    try:
                        async with httpx.AsyncClient(timeout=30.0) as client:
                            sg_response = await client.delete(
                                f"{DRIVERS_URL}/security-groups-{zona}/slice/{slice_id}",
                                headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                            )
                            logger.info(f"Slice {slice_id}: Rollback SG: {sg_response.json()}")
                    except Exception as sg_error:
                        logger.warning(f"Slice {slice_id}: Error en rollback SG: {str(sg_error)}")
                    
                    # Eliminar tracking
                    try:
                        async with httpx.AsyncClient(timeout=30.0) as client:
                            track_response = await client.delete(
                                f"{VM_PLACEMENT_URL}/delete-assigned-resources/{slice_id}",
                                params={"zona": zona},
                                headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                            )
                            logger.info(f"Slice {slice_id}: Rollback tracking: {track_response.json()}")
                    except Exception as track_error:
                        logger.warning(f"Slice {slice_id}: Error en rollback tracking: {str(track_error)}")
                    
                    # Eliminar de BD
                    try:
                        conn_del = mysql.connector.connect(**DB_CONFIG)
                        cur_del = conn_del.cursor()
                        cur_del.execute("DELETE FROM slices WHERE id = %s", (slice_id,))
                        conn_del.commit()
                        cur_del.close()
                        conn_del.close()
                        logger.info(f"Slice {slice_id}: Eliminado de BD")
                    except Exception as db_error:
                        logger.error(f"Slice {slice_id}: Error eliminando de BD: {str(db_error)}")
                    
                    return {
                        "success": False,
                        "message": f"Error en despliegue del slice {slice_id}. Rollback completado.",
                        "slice_id": slice_id,
                        "error": f"Estado: {estado}, Tipo: {tipo}",
                        "rollback": "completed",
                        "polling_attempts": attempt
                    }
                
            except Exception as poll_error:
                logger.error(f"Slice {slice_id}: Error en polling: {str(poll_error)}")
                continue
        
        # ===== TIMEOUT =====
        logger.warning(f"Slice {slice_id}: Timeout después de 5 minutos de polling")
        return {
            "success": False,
            "message": f"Timeout: El slice {slice_id} aún está procesándose después de 5 minutos",
            "slice_id": slice_id,
            "nombre_slice": slice_request.nombre_slice,
            "zona_despliegue": zona,
            "estado": "timeout",
            "nota": "Use /slices/info/{id} para verificar estado manualmente"
        }
        
    except HTTPException:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
        raise
    except Error as e:
        logger.error(f"Error en base de datos: {str(e)}")
        if cursor:
            cursor.close()
        if connection:
            connection.close()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en base de datos: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error inesperado: {str(e)}")
        if cursor:
            cursor.close()
        if connection:
            connection.close()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

# ==================== ENDPOINTS DE CONSULTA DE SLICES ====================

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
        
        # Si no hay slices, retornar mensaje informativo
        if len(slices) == 0:
            return {
                "success": True,
                "total_slices": 0,
                "usuario_rol": user['rol'],
                "message": "No tiene slices desplegados",
                "slices": []
            }
        
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

@app.get("/slices/info/{slice_id}")
async def get_slice_info(
    slice_id: int,
    user: dict = Depends(get_current_user)
):
    """
    Obtener información completa de un slice incluyendo VMs
    
    - Cliente: Solo puede ver sus propios slices
    - Admin: Puede ver cualquier slice
    """
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener slice completo
        cursor.execute("SELECT * FROM slices WHERE id = %s", (slice_id,))
        slice_data = cursor.fetchone()
        
        cursor.close()
        connection.close()
        
        if not slice_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Slice {slice_id} no encontrado"
            )
        
        # Validar permisos: cliente solo puede ver sus slices
        if user['rol'] != 'admin' and slice_data['usuario'] != user['id']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para ver este slice"
            )
        
        # Parsear peticion_json si es string
        peticion_json = slice_data['peticion_json']
        if isinstance(peticion_json, str):
            peticion_json = json.loads(peticion_json)
        
        # Parsear vncs si es JSON
        vncs = slice_data.get('vncs')
        if vncs and isinstance(vncs, str):
            vncs = json.loads(vncs)
        
        # Parsear vms si es JSON
        vms = slice_data.get('vms')
        if vms and isinstance(vms, str):
            vms = json.loads(vms)
        
        return {
            "success": True,
            "slice": {
                "id": slice_data['id'],
                "usuario": slice_data['usuario'],
                "nombre_slice": slice_data['nombre_slice'],
                "estado": slice_data['estado'],
                "timestamp_creacion": slice_data['timestamp_creacion'],
                "timestamp_despliegue": slice_data['timestamp_despliegue'],
                "vlans": slice_data.get('vlans'),
                "vncs": vncs,
                "vms": vms,
                "peticion_json": peticion_json
            }
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

# ==================== CALLBACK DE VM PLACEMENT ====================

@app.post("/slices/deploymentready/{slice_id}")
async def deployment_ready_callback(
    slice_id: int,
    payload: dict,
    authorized: bool = Depends(get_service_auth)
):
    """
    Callback de vm_placement_api cuando el JSON está listo para despliegue
    
    Nuevo flujo optimizado:
    1. Guardar JSON completo (con workers/VLANs mapeados) en BD
    2. Construir JSON simplificado para despliegue (solo: nombre, flavor, image, conexiones_vlans, server)
    3. Enviar a drivers → recibe solo vnc_mapping
    4. Actualizar campo puerto_vnc en vms de la BD
    
    Payload esperado:
    {
        "nombre_slice": "...",
        "zona_despliegue": "linux",
        "solicitud_json": { ... }  // JSON con workers y VLANs mapeados
    }
    """
    try:
        logger.info(f"[SLICE_MANAGER] Callback recibido para slice {slice_id}")
        
        zona_despliegue = payload.get('zona_despliegue')
        solicitud_json = payload.get('solicitud_json')
        nombre_slice = payload.get('nombre_slice')
        
        if not all([zona_despliegue, solicitud_json]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Faltan campos requeridos: zona_despliegue, solicitud_json"
            )
        
        # ==== PASO 1: Guardar JSON completo y VMs en BD ====
        logger.info(f"[SLICE_MANAGER] Slice {slice_id}: Guardando JSON mapeado en BD...")
        
        all_vms = []
        for topology in solicitud_json.get('topologias', []):
            for vm in topology.get('vms', []):
                vm['estado'] = 'Desplegando'
                vm['puerto_vnc'] = ''  # Se llenará después del despliegue
                all_vms.append(vm)
        
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor()
        
        peticion_json_str = json.dumps(solicitud_json, ensure_ascii=False)
        vms_json_str = json.dumps(all_vms, ensure_ascii=False)
        
        update_query = """
            UPDATE slices 
            SET tipo = %s,
                estado = %s,
                peticion_json = %s,
                vms = %s
            WHERE id = %s
        """
        cursor.execute(update_query, (
            'mapeado',
            'desplegando',
            peticion_json_str,
            vms_json_str,
            slice_id
        ))
        connection.commit()
        cursor.close()
        connection.close()
        
        logger.info(f"[SLICE_MANAGER] Slice {slice_id}: JSON guardado, construyendo payload simplificado...")
        
        # ==== PASO 2: Construir JSON simplificado para despliegue ====
        simplified_vms = []
        for topology in solicitud_json.get('topologias', []):
            for vm in topology.get('vms', []):
                simplified_vm = {
                    'nombre': vm.get('nombre'),
                    'image': vm.get('image'),
                    'conexiones_vlans': vm.get('conexiones_vlans', ''),
                    'server': vm.get('server')
                }
                
                # Para Linux: construir flavor (cores;ram;almacenamiento)
                # Para OpenStack: usar id_flavor_openstack directamente
                if zona_despliegue == 'linux':
                    cores = vm.get('cores', '1')
                    ram = vm.get('ram', '512M')
                    almacenamiento = vm.get('almacenamiento', '1G')
                    simplified_vm['flavor'] = f"{cores};{ram};{almacenamiento}"
                elif zona_despliegue == 'openstack':
                    simplified_vm['id_flavor_openstack'] = vm.get('id_flavor_openstack')
                
                simplified_vms.append(simplified_vm)
        
        # Payload simplificado - diferente estructura según zona
        if zona_despliegue == 'linux':
            # Linux: estructura con topologias
            simplified_json = {
                'zona_despliegue': zona_despliegue,
                'id_slice': str(slice_id),
                'topologias': [
                    {
                        'vms': simplified_vms
                    }
                ]
            }
        elif zona_despliegue == 'openstack':
            # OpenStack: lista plana de vms (sin topologias)
            simplified_json = {
                'zona_despliegue': zona_despliegue,
                'id_slice': str(slice_id),
                'vms': simplified_vms
            }
        else:
            # Fallback para otras zonas
            simplified_json = {
                'zona_despliegue': zona_despliegue,
                'id_slice': str(slice_id),
                'topologias': [
                    {
                        'vms': simplified_vms
                    }
                ]
            }
        
        driver_payload = {
            "json_config": simplified_json
        }
        
        # ============ LOGGING DEL JSON SIMPLIFICADO ============
        logger.info(f"[SLICE_MANAGER] Slice {slice_id}: JSON SIMPLIFICADO CONSTRUIDO:")
        logger.info(f"{'='*100}")
        logger.info(json.dumps(simplified_json, indent=2, ensure_ascii=False))
        logger.info(f"{'='*100}")
        
        logger.info(f"[SLICE_MANAGER] Slice {slice_id}: Llamando a drivers con JSON simplificado...")
        
        # ==== PASO 3: Llamar a drivers con JSON simplificado ====
        async with httpx.AsyncClient(timeout=600.0) as client:
            driver_response = await client.post(
                f"{DRIVERS_URL}/deploy-slice",
                json=driver_payload,
                headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
            )
        
        if driver_response.status_code != 200:
            logger.error(f"[SLICE_MANAGER] Slice {slice_id}: Error HTTP en drivers: {driver_response.text}")
            # Actualizar estado a error en BD
            connection = mysql.connector.connect(**DB_CONFIG)
            cursor = connection.cursor()
            cursor.execute("UPDATE slices SET estado = %s, tipo = %s WHERE id = %s", 
                          ('error_despliegue', 'error', slice_id))
            connection.commit()
            cursor.close()
            connection.close()
            # IMPORTANTE: Retornar success=True para que vm_placement haga ACK y NO reencole
            # El error ya quedó registrado en BD
            return {
                "success": True,
                "message": f"Error HTTP en despliegue (registrado en BD)",
                "slice_id": slice_id,
                "error": driver_response.text
            }
        
        driver_result = driver_response.json()
        
        if not driver_result.get('success'):
            error_msg = driver_result.get('error', 'Despliegue fallido en orquestador')
            logger.error(f"[SLICE_MANAGER] Slice {slice_id}: Despliegue fallido - {error_msg}")
            # Actualizar estado a error en BD
            connection = mysql.connector.connect(**DB_CONFIG)
            cursor = connection.cursor()
            cursor.execute("UPDATE slices SET estado = %s, tipo = %s WHERE id = %s", 
                          ('error_despliegue', 'error', slice_id))
            connection.commit()
            cursor.close()
            connection.close()
            # IMPORTANTE: Retornar success=True para que vm_placement haga ACK y NO reencole
            # El error ya quedó registrado en BD
            return {
                "success": True,
                "message": f"Error en orquestador (registrado en BD)",
                "slice_id": slice_id,
                "error": error_msg
            }
        
        # ==== PASO 4: Actualizar puerto_vnc en vms (solo para Linux) ====
        # OpenStack NO usa VNC, Linux sí
        if zona_despliegue == 'linux':
            vnc_mapping = driver_result.get('vnc_mapping', {})
            
            logger.info(f"[SLICE_MANAGER] Slice {slice_id}: Despliegue exitoso, actualizando VNC en BD...")
            logger.info(f"[SLICE_MANAGER] VNC mapping recibido: {vnc_mapping}")
            
            # Actualizar puerto_vnc en cada VM
            for vm in all_vms:
                vm_name = vm.get('nombre')
                if vnc_mapping and vm_name in vnc_mapping:
                    vm['puerto_vnc'] = str(vnc_mapping[vm_name])
                    vm['estado'] = 'Corriendo'
                else:
                    logger.warning(f"[SLICE_MANAGER] No se encontró VNC para VM {vm_name}")
                    vm['puerto_vnc'] = ''
                    vm['estado'] = 'Error'
        else:
            # OpenStack: solo actualizar estado
            logger.info(f"[SLICE_MANAGER] Slice {slice_id}: Despliegue OpenStack exitoso")
            for vm in all_vms:
                vm['estado'] = 'Corriendo'
                vm['puerto_vnc'] = 'N/A'  # OpenStack no usa VNC en este sistema
        
        # Timestamp de despliegue
        lima_tz = pytz.timezone('America/Lima')
        timestamp_despliegue = datetime.now(lima_tz).strftime("%Y-%m-%d %H:%M:%S")
        
        # Actualizar BD con VNC
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor()
        
        vms_json_str = json.dumps(all_vms, ensure_ascii=False)
        
        update_query = """
            UPDATE slices 
            SET tipo = %s,
                estado = %s,
                vms = %s,
                timestamp_despliegue = %s
            WHERE id = %s
        """
        cursor.execute(update_query, (
            'desplegado',
            'corriendo',
            vms_json_str,
            timestamp_despliegue,
            slice_id
        ))
        connection.commit()
        cursor.close()
        connection.close()
        
        logger.info(f"[SLICE_MANAGER] Slice {slice_id}: BD actualizada - {len(all_vms)} VMs desplegadas")
        
        response_data = {
            "success": True,
            "message": f"Slice {slice_id} desplegado y actualizado exitosamente",
            "slice_id": slice_id,
            "total_vms": len(all_vms),
            "estado": "corriendo"
        }
        
        # Agregar vnc_ports solo para Linux
        if zona_despliegue == 'linux':
            response_data["vnc_ports"] = driver_result.get('vnc_mapping', {})
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SLICE_MANAGER] Error en callback para slice {slice_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error procesando callback: {str(e)}"
        )

# ==================== ENDPOINTS DE GESTIÓN DE SLICES ====================

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
        
        # Obtener zona_disponibilidad directamente de la BD
        zona_despliegue = slice_data.get('zona_disponibilidad', 'linux')
        
        logger.info(f"Eliminando slice {slice_id} de zona {zona_despliegue}")
        
        # ==== PASO 1: Llamar a drivers para eliminar en el cluster ====
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
                    logger.warning(f"Error eliminando en cluster: {delete_result.get('error', 'Unknown')}")
                
        except httpx.TimeoutException:
            logger.warning(f"Timeout eliminando slice en cluster (continuando con limpieza)")
        except httpx.ConnectError:
            logger.warning(f"Error conectando con drivers (continuando con limpieza)")
        except Exception as e:
            logger.warning(f"Error eliminando en cluster: {str(e)} (continuando con limpieza)")
        
        # ==== PASO 2: Eliminar security groups del slice ====
        try:
            logger.info(f"Eliminando security groups del slice {slice_id}")
            async with httpx.AsyncClient(timeout=30.0) as client:
                sg_response = await client.delete(
                    f"{DRIVERS_URL}/security-groups-{zona_despliegue}/slice/{slice_id}",
                    headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                )
                
                if sg_response.status_code == 200:
                    sg_result = sg_response.json()
                    logger.info(f"Security groups eliminados: {sg_result.get('deleted_count', 0)}")
                else:
                    logger.warning(f"Error eliminando security groups (no crítico): {sg_response.text}")
        except Exception as sg_error:
            logger.warning(f"No se pudieron eliminar security groups (no crítico): {str(sg_error)}")
        
        # ==== PASO 3: Eliminar recursos asignados del tracking de VM placement ====
        try:
            logger.info(f"Eliminando recursos de tracking para slice {slice_id} en zona {zona_despliegue}")
            async with httpx.AsyncClient(timeout=30.0) as client:
                tracking_response = await client.delete(
                    f"{VM_PLACEMENT_URL}/delete-assigned-resources/{slice_id}",
                    params={"zona": zona_despliegue},
                    headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                )
                
                if tracking_response.status_code == 200:
                    tracking_result = tracking_response.json()
                    logger.info(f"Tracking limpiado: {tracking_result.get('vms_removed', 0)} VMs removidas")
                else:
                    logger.warning(f"Error al limpiar tracking (no crítico): {tracking_response.text}")
        except Exception as track_error:
            logger.warning(f"No se pudo limpiar tracking (no crítico): {str(track_error)}")
        
        # ==== PASO 4: Eliminar slice de la BD ====
        delete_query = "DELETE FROM slices WHERE id = %s"
        cursor.execute(delete_query, (slice_id,))
        connection.commit()
        
        cursor.close()
        connection.close()
        
        logger.info(f"Slice {slice_id} eliminado completamente de la BD")
        
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
        
        # Actualizar estado en BD del slice
        update_query = "UPDATE slices SET estado = %s WHERE id = %s"
        cursor.execute(update_query, ('pausado', slice_id))
        
        # Obtener y actualizar el JSON de VMs
        cursor.execute("SELECT vms FROM slices WHERE id = %s", (slice_id,))
        vms_data = cursor.fetchone()
        
        if vms_data and vms_data['vms']:
            vms_json = vms_data['vms']
            if isinstance(vms_json, str):
                vms_json = json.loads(vms_json)
            
            # Actualizar estado de cada VM en el JSON
            for vm in vms_json:
                vm['estado'] = 'Pausado'
            
            # Guardar el JSON actualizado
            update_vms_query = "UPDATE slices SET vms = %s WHERE id = %s"
            cursor.execute(update_vms_query, (json.dumps(vms_json), slice_id))
        
        connection.commit()
        
        cursor.close()
        connection.close()
        
        logger.info(f"Slice {slice_id} y sus VMs pausados exitosamente")
        
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
        
        # Actualizar estado en BD del slice
        update_query = "UPDATE slices SET estado = %s WHERE id = %s"
        cursor.execute(update_query, ('corriendo', slice_id))
        
        # Obtener y actualizar el JSON de VMs
        cursor.execute("SELECT vms FROM slices WHERE id = %s", (slice_id,))
        vms_data = cursor.fetchone()
        
        if vms_data and vms_data['vms']:
            vms_json = vms_data['vms']
            if isinstance(vms_json, str):
                vms_json = json.loads(vms_json)
            
            # Actualizar estado de cada VM en el JSON
            for vm in vms_json:
                vm['estado'] = 'Corriendo'
            
            # Guardar el JSON actualizado
            update_vms_query = "UPDATE slices SET vms = %s WHERE id = %s"
            cursor.execute(update_vms_query, (json.dumps(vms_json), slice_id))
        
        connection.commit()
        
        cursor.close()
        connection.close()
        
        logger.info(f"Slice {slice_id} y sus VMs reanudados exitosamente")
        
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

# ==================== ENDPOINTS DE OPERACIONES DE VM INDIVIDUAL ====================

@app.post("/slices/{slice_id}/vms/pause/{vm_name}")
async def pause_vm(
    slice_id: int,
    vm_name: str,
    user: dict = Depends(get_current_user)
):
    """
    Pausar una VM específica de un slice
    
    - Cliente: Solo puede pausar VMs de sus propios slices
    - Admin: Puede pausar VMs de cualquier slice
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
        
        # Validar permisos
        if user['rol'] != 'admin' and slice_data['usuario'] != user['id']:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para pausar VMs de este slice"
            )
        
        # Extraer zona_despliegue
        peticion_json = slice_data['peticion_json']
        if isinstance(peticion_json, str):
            peticion_json = json.loads(peticion_json)
        
        zona_despliegue = peticion_json.get('zona_despliegue', 'linux')
        
        logger.info(f"Pausando VM {vm_name} del slice {slice_id}")
        
        # Llamar a drivers
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{DRIVERS_URL}/pause-vm",
                    json={
                        "slice_id": slice_id,
                        "vm_name": vm_name,
                        "zona_despliegue": zona_despliegue
                    },
                    headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                )
                
                result = response.json()
                
                if response.status_code != 200 or not result.get('success'):
                    cursor.close()
                    connection.close()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Error al pausar VM: {result.get('error', 'Unknown error')}"
                    )
                
        except httpx.TimeoutException:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Timeout al pausar VM"
            )
        except httpx.ConnectError:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No se pudo conectar con el servicio de drivers"
            )
        
        # Actualizar estado de la VM en BD
        vms = slice_data.get('vms')
        if vms and isinstance(vms, str):
            vms = json.loads(vms)
        
        if vms:
            # Buscar y actualizar el estado de la VM
            for vm in vms:
                if vm.get('nombre') == vm_name:
                    vm['estado'] = 'Pausado'
                    break
            
            # Guardar VMs actualizadas
            vms_json_str = json.dumps(vms, ensure_ascii=False)
            update_vms_query = "UPDATE slices SET vms = %s WHERE id = %s"
            cursor.execute(update_vms_query, (vms_json_str, slice_id))
            connection.commit()
            
            # Actualizar estado del slice según estados de VMs
            new_slice_state = update_slice_state_based_on_vms(cursor, connection, slice_id, vms)
        
        cursor.close()
        connection.close()
        
        logger.info(f"VM {vm_name} pausada exitosamente")
        
        return {
            "success": True,
            "message": f"VM {vm_name} pausada exitosamente",
            "slice_id": slice_id,
            "vm_name": vm_name,
            "vm_estado": "Pausado",
            "slice_estado": new_slice_state if vms else "corriendo"
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

@app.post("/slices/{slice_id}/vms/resume/{vm_name}")
async def resume_vm(
    slice_id: int,
    vm_name: str,
    user: dict = Depends(get_current_user)
):
    """
    Reanudar una VM pausada de un slice
    
    - Cliente: Solo puede reanudar VMs de sus propios slices
    - Admin: Puede reanudar VMs de cualquier slice
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
        
        # Validar permisos
        if user['rol'] != 'admin' and slice_data['usuario'] != user['id']:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para reanudar VMs de este slice"
            )
        
        # Extraer zona_despliegue
        peticion_json = slice_data['peticion_json']
        if isinstance(peticion_json, str):
            peticion_json = json.loads(peticion_json)
        
        zona_despliegue = peticion_json.get('zona_despliegue', 'linux')
        
        logger.info(f"Reanudando VM {vm_name} del slice {slice_id}")
        
        # Llamar a drivers
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{DRIVERS_URL}/resume-vm",
                    json={
                        "slice_id": slice_id,
                        "vm_name": vm_name,
                        "zona_despliegue": zona_despliegue
                    },
                    headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                )
                
                result = response.json()
                
                if response.status_code != 200 or not result.get('success'):
                    cursor.close()
                    connection.close()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Error al reanudar VM: {result.get('error', 'Unknown error')}"
                    )
                
        except httpx.TimeoutException:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Timeout al reanudar VM"
            )
        except httpx.ConnectError:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No se pudo conectar con el servicio de drivers"
            )
        
        # Actualizar estado de la VM en BD
        vms = slice_data.get('vms')
        if vms and isinstance(vms, str):
            vms = json.loads(vms)
        
        if vms:
            # Buscar y actualizar el estado de la VM
            for vm in vms:
                if vm.get('nombre') == vm_name:
                    vm['estado'] = 'Corriendo'
                    break
            
            # Guardar VMs actualizadas
            vms_json_str = json.dumps(vms, ensure_ascii=False)
            update_vms_query = "UPDATE slices SET vms = %s WHERE id = %s"
            cursor.execute(update_vms_query, (vms_json_str, slice_id))
            connection.commit()
            
            # Actualizar estado del slice según estados de VMs
            new_slice_state = update_slice_state_based_on_vms(cursor, connection, slice_id, vms)
        
        cursor.close()
        connection.close()
        
        logger.info(f"VM {vm_name} reanudada exitosamente")
        
        return {
            "success": True,
            "message": f"VM {vm_name} reanudada exitosamente",
            "slice_id": slice_id,
            "vm_name": vm_name,
            "vm_estado": "Corriendo",
            "slice_estado": new_slice_state if vms else "corriendo"
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

@app.post("/slices/{slice_id}/vms/shutdown/{vm_name}")
async def shutdown_vm(
    slice_id: int,
    vm_name: str,
    user: dict = Depends(get_current_user)
):
    """
    Apagar (shutdown) una VM específica de un slice
    
    - Cliente: Solo puede apagar VMs de sus propios slices
    - Admin: Puede apagar VMs de cualquier slice
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
        
        # Validar permisos
        if user['rol'] != 'admin' and slice_data['usuario'] != user['id']:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para apagar VMs de este slice"
            )
        
        # Extraer zona_despliegue
        peticion_json = slice_data['peticion_json']
        if isinstance(peticion_json, str):
            peticion_json = json.loads(peticion_json)
        
        zona_despliegue = peticion_json.get('zona_despliegue', 'linux')
        
        logger.info(f"Apagando VM {vm_name} del slice {slice_id}")
        
        # Llamar a drivers
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{DRIVERS_URL}/shutdown-vm",
                    json={
                        "slice_id": slice_id,
                        "vm_name": vm_name,
                        "zona_despliegue": zona_despliegue
                    },
                    headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                )
                
                result = response.json()
                
                if response.status_code != 200 or not result.get('success'):
                    cursor.close()
                    connection.close()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Error al apagar VM: {result.get('error', 'Unknown error')}"
                    )
                
        except httpx.TimeoutException:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Timeout al apagar VM"
            )
        except httpx.ConnectError:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No se pudo conectar con el servicio de drivers"
            )
        
        # Actualizar estado de la VM en BD
        vms = slice_data.get('vms')
        if vms and isinstance(vms, str):
            vms = json.loads(vms)
        
        if vms:
            # Buscar y actualizar el estado de la VM
            for vm in vms:
                if vm.get('nombre') == vm_name:
                    vm['estado'] = 'Apagado'
                    break
            
            # Guardar VMs actualizadas
            vms_json_str = json.dumps(vms, ensure_ascii=False)
            update_vms_query = "UPDATE slices SET vms = %s WHERE id = %s"
            cursor.execute(update_vms_query, (vms_json_str, slice_id))
            connection.commit()
            
            # Actualizar estado del slice según estados de VMs
            new_slice_state = update_slice_state_based_on_vms(cursor, connection, slice_id, vms)
        
        cursor.close()
        connection.close()
        
        logger.info(f"VM {vm_name} apagada exitosamente")
        
        return {
            "success": True,
            "message": f"VM {vm_name} apagada exitosamente",
            "slice_id": slice_id,
            "vm_name": vm_name,
            "vm_estado": "Apagado",
            "slice_estado": new_slice_state if vms else "corriendo"
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

@app.post("/slices/{slice_id}/vms/start/{vm_name}")
async def start_vm(
    slice_id: int,
    vm_name: str,
    user: dict = Depends(get_current_user)
):
    """
    Encender (start) una VM específica de un slice
    
    - Cliente: Solo puede encender VMs de sus propios slices
    - Admin: Puede encender VMs de cualquier slice
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
        
        # Validar permisos
        if user['rol'] != 'admin' and slice_data['usuario'] != user['id']:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para encender VMs de este slice"
            )
        
        # Extraer zona_despliegue
        peticion_json = slice_data['peticion_json']
        if isinstance(peticion_json, str):
            peticion_json = json.loads(peticion_json)
        
        zona_despliegue = peticion_json.get('zona_despliegue', 'linux')
        
        logger.info(f"Encendiendo VM {vm_name} del slice {slice_id}")
        
        # Llamar a drivers
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{DRIVERS_URL}/start-vm",
                    json={
                        "slice_id": slice_id,
                        "vm_name": vm_name,
                        "zona_despliegue": zona_despliegue
                    },
                    headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                )
                
                result = response.json()
                
                if response.status_code != 200 or not result.get('success'):
                    cursor.close()
                    connection.close()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Error al encender VM: {result.get('error', 'Unknown error')}"
                    )
                
        except httpx.TimeoutException:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Timeout al encender VM"
            )
        except httpx.ConnectError:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No se pudo conectar con el servicio de drivers"
            )
        
        # Actualizar estado de la VM en BD
        vms = slice_data.get('vms')
        if vms and isinstance(vms, str):
            vms = json.loads(vms)
        
        if vms:
            # Buscar y actualizar el estado de la VM
            for vm in vms:
                if vm.get('nombre') == vm_name:
                    vm['estado'] = 'Corriendo'
                    break
            
            # Guardar VMs actualizadas
            vms_json_str = json.dumps(vms, ensure_ascii=False)
            update_vms_query = "UPDATE slices SET vms = %s WHERE id = %s"
            cursor.execute(update_vms_query, (vms_json_str, slice_id))
            connection.commit()
            
            # Actualizar estado del slice según estados de VMs
            new_slice_state = update_slice_state_based_on_vms(cursor, connection, slice_id, vms)
        
        cursor.close()
        connection.close()
        
        logger.info(f"VM {vm_name} encendida exitosamente")
        
        return {
            "success": True,
            "message": f"VM {vm_name} encendida exitosamente",
            "slice_id": slice_id,
            "vm_name": vm_name,
            "vm_estado": "Corriendo",
            "slice_estado": new_slice_state if vms else "corriendo"
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

# ==================== ENDPOINTS DE OPERACIONES DE SLICE COMPLETO ====================

@app.post("/slices/shutdown/{slice_id}")
async def shutdown_slice(
    slice_id: int,
    user: dict = Depends(get_current_user)
):
    """
    Apagar todas las VMs de un slice
    
    - Cliente: Solo puede apagar sus propios slices
    - Admin: Puede apagar cualquier slice
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
        
        # Validar permisos
        if user['rol'] != 'admin' and slice_data['usuario'] != user['id']:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para apagar este slice"
            )
        
        # Extraer zona_despliegue
        peticion_json = slice_data['peticion_json']
        if isinstance(peticion_json, str):
            peticion_json = json.loads(peticion_json)
        
        zona_despliegue = peticion_json.get('zona_despliegue', 'linux')
        
        logger.info(f"Apagando todas las VMs del slice {slice_id}")
        
        # Llamar a drivers
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{DRIVERS_URL}/shutdown-slice",
                    json={
                        "slice_id": slice_id,
                        "zona_despliegue": zona_despliegue
                    },
                    headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                )
                
                result = response.json()
                
                if response.status_code != 200 or not result.get('success'):
                    cursor.close()
                    connection.close()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Error al apagar slice: {result.get('error', 'Unknown error')}"
                    )
                
        except httpx.TimeoutException:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Timeout al apagar slice"
            )
        except httpx.ConnectError:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No se pudo conectar con el servicio de drivers"
            )
        
        # Actualizar estado del slice en BD
        update_query = "UPDATE slices SET estado = %s WHERE id = %s"
        cursor.execute(update_query, ('apagado', slice_id))
        
        # Obtener y actualizar el JSON de VMs
        cursor.execute("SELECT vms FROM slices WHERE id = %s", (slice_id,))
        vms_data = cursor.fetchone()
        
        if vms_data and vms_data['vms']:
            vms_json = vms_data['vms']
            if isinstance(vms_json, str):
                vms_json = json.loads(vms_json)
            
            # Actualizar estado de cada VM en el JSON
            for vm in vms_json:
                vm['estado'] = 'Apagado'
            
            # Guardar el JSON actualizado
            update_vms_query = "UPDATE slices SET vms = %s WHERE id = %s"
            cursor.execute(update_vms_query, (json.dumps(vms_json), slice_id))
        
        connection.commit()
        
        cursor.close()
        connection.close()
        
        logger.info(f"Slice {slice_id} y sus VMs apagados exitosamente")
        
        return {
            "success": True,
            "message": f"Slice {slice_id} apagado exitosamente",
            "slice_id": slice_id,
            "estado": "apagado",
            "workers_results": result.get('workers_results')
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

@app.post("/slices/start/{slice_id}")
async def start_slice(
    slice_id: int,
    user: dict = Depends(get_current_user)
):
    """
    Encender todas las VMs de un slice
    
    - Cliente: Solo puede encender sus propios slices
    - Admin: Puede encender cualquier slice
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
        
        # Validar permisos
        if user['rol'] != 'admin' and slice_data['usuario'] != user['id']:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para encender este slice"
            )
        
        # Extraer zona_despliegue
        peticion_json = slice_data['peticion_json']
        if isinstance(peticion_json, str):
            peticion_json = json.loads(peticion_json)
        
        zona_despliegue = peticion_json.get('zona_despliegue', 'linux')
        
        logger.info(f"Encendiendo todas las VMs del slice {slice_id}")
        
        # Llamar a drivers
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{DRIVERS_URL}/start-slice",
                    json={
                        "slice_id": slice_id,
                        "zona_despliegue": zona_despliegue
                    },
                    headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                )
                
                result = response.json()
                
                if response.status_code != 200 or not result.get('success'):
                    cursor.close()
                    connection.close()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Error al encender slice: {result.get('error', 'Unknown error')}"
                    )
                
        except httpx.TimeoutException:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Timeout al encender slice"
            )
        except httpx.ConnectError:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No se pudo conectar con el servicio de drivers"
            )
        
        # Actualizar estado del slice en BD
        update_query = "UPDATE slices SET estado = %s WHERE id = %s"
        cursor.execute(update_query, ('corriendo', slice_id))
        
        # Obtener y actualizar el JSON de VMs
        cursor.execute("SELECT vms FROM slices WHERE id = %s", (slice_id,))
        vms_data = cursor.fetchone()
        
        if vms_data and vms_data['vms']:
            vms_json = vms_data['vms']
            if isinstance(vms_json, str):
                vms_json = json.loads(vms_json)
            
            # Actualizar estado de cada VM en el JSON
            for vm in vms_json:
                vm['estado'] = 'Corriendo'
            
            # Guardar el JSON actualizado
            update_vms_query = "UPDATE slices SET vms = %s WHERE id = %s"
            cursor.execute(update_vms_query, (json.dumps(vms_json), slice_id))
        
        connection.commit()
        
        cursor.close()
        connection.close()
        
        logger.info(f"Slice {slice_id} y sus VMs encendidos exitosamente")
        
        return {
            "success": True,
            "message": f"Slice {slice_id} encendido exitosamente",
            "slice_id": slice_id,
            "estado": "corriendo",
            "workers_results": result.get('workers_results')
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

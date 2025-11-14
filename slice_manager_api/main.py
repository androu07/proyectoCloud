from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, validator, root_validator
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Slice Manager API - Nuevo Flujo",
    version="2.0.0",
    description="API mejorada para gestión de slices con validaciones exhaustivas"
)

# Configuración
JWT_SECRET = os.getenv('JWT_SECRET_KEY', 'mi_clave_secreta_super_segura_12345')
JWT_ALGORITHM = 'HS256'
IMAGE_MANAGER_URL = os.getenv('IMAGE_MANAGER_URL', 'http://image_manager_api:5700')
IMAGE_MANAGER_TOKEN = os.getenv('IMAGE_MANAGER_TOKEN', 'clavesihna')
NET_SEC_URL = os.getenv('NET_SEC_URL', 'http://net_sec_api:6300')
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

# ==================== MODELOS PYDANTIC ====================

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
    
    @validator('nombre')
    def validate_nombre(cls, v):
        if not re.match(r'^vm\d+$', v):
            raise ValueError('nombre debe tener formato vmX donde X es un número')
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
            
            if nombre_topo == '1vm' and cantidad != 1:
                raise ValueError('topología "1vm" debe tener exactamente 1 VM')
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
    vncs_usadas: str = ""
    conexiones_vms: str
    topologias: List[Topologia]
    
    @validator('id_slice')
    def validate_id_slice_empty(cls, v):
        if v != "":
            raise ValueError('id_slice debe estar vacío en la petición inicial')
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
    
    @validator('vlans_usadas', 'vncs_usadas')
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
    4. Llamar a net_sec_api para mapeo de VLANs y network
    5. Enviar JSON mapeado a queue_manager para mapeo de servers
    6. Retornar resumen completo
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
            (usuario, nombre_slice, tipo, estado, peticion_json, timestamp_creacion) 
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, (
            user['id'],
            slice_request.nombre_slice,
            'validado',
            '',
            peticion_json_str,
            timestamp_creacion
        ))
        connection.commit()
        
        slice_id = cursor.lastrowid
        logger.info(f"Slice {slice_id} creado - Tipo: validado")
        
        cursor.close()
        connection.close()
        
        # ===== PASO 2: Mapeo de VLANs y Network (net_sec_api) =====
        logger.info(f"Slice {slice_id}: Iniciando mapeo de VLANs y network...")
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                net_sec_response = await client.post(
                    f"{NET_SEC_URL}/map-vlans",
                    json={"slice_id": slice_id}
                )
                
                if net_sec_response.status_code != 200:
                    raise Exception(f"Error en net_sec_api: {net_sec_response.text}")
                
                net_sec_result = net_sec_response.json()
                logger.info(f"Slice {slice_id}: VLANs y network mapeados exitosamente")
                
                # JSON mapeado con id_slice, vlans_usadas y network
                mapped_json = net_sec_result['mapped_json']
                
        except Exception as e:
            logger.error(f"Slice {slice_id}: Error en mapeo de VLANs/network: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error en mapeo de VLANs y network: {str(e)}"
            )
        
        # ===== PASO 3: Mapeo de servers via queue_manager =====
        logger.info(f"Slice {slice_id}: Iniciando mapeo de servers...")
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                # Crear estructura completa para enviar directamente a vm_placement via queue
                complete_request = {
                    "nombre_slice": slice_request.nombre_slice,
                    "zona_despliegue": slice_request.zona_despliegue,
                    "solicitud_json": mapped_json
                }
                
                # Encolar
                enqueue_response = await client.post(
                    f"{QUEUE_MANAGER_URL}/enqueue-placement",
                    json=complete_request,
                    headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                )
                
                if enqueue_response.status_code != 200:
                    raise Exception(f"Error al encolar: {enqueue_response.text}")
                
                logger.info(f"Slice {slice_id}: Encolado exitosamente")
                
                # Procesar inmediatamente desde la cola
                process_response = await client.post(
                    f"{QUEUE_MANAGER_URL}/process-from-queue",
                    headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                )
                
                if process_response.status_code != 200:
                    raise Exception(f"Error al procesar cola: {process_response.text}")
                
                queue_result = process_response.json()
                
                if not queue_result.get('success'):
                    raise Exception("Cola vacía o error al procesar")
                
                # Obtener el JSON con servers mapeados
                placement_result = queue_result.get('result', {})
                complete_request_with_servers = placement_result.get('peticion_json', {})
                mapped_with_servers = complete_request_with_servers.get('solicitud_json', {})
                
                # IMPRIMIR JSON COMPLETO DESPUÉS DEL MAPEO DE SERVERS
                logger.info(f"\n{'='*80}")
                logger.info(f"Slice {slice_id}: JSON DESPUÉS DEL MAPEO DE SERVERS")
                logger.info(f"{'='*80}")
                logger.info(json.dumps(mapped_with_servers, indent=2, ensure_ascii=False))
                logger.info(f"{'='*80}\n")
                
                logger.info(f"Slice {slice_id}: Mapeo de servers completado")
                
        except Exception as e:
            logger.error(f"Slice {slice_id}: Error en mapeo de servers: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error en mapeo de servers: {str(e)}"
            )
        
        # ===== PASO 4: Enviar al driver para despliegue =====
        logger.info(f"Slice {slice_id}: Enviando al driver para despliegue en {slice_request.zona_despliegue}...")
        
        # Preparar payload completo para el driver
        driver_payload = {
            "json_config": {
                "nombre_slice": slice_request.nombre_slice,
                "zona_despliegue": slice_request.zona_despliegue,
                "solicitud_json": mapped_with_servers
            }
        }
        
        logger.info(f"\n{'='*80}")
        logger.info(f"Slice {slice_id}: JSON COMPLETO PARA ENVIAR AL DRIVER")
        logger.info(f"{'='*80}")
        logger.info(json.dumps(driver_payload, indent=2, ensure_ascii=False))
        logger.info(f"{'='*80}\n")
        
        # Llamar al driver para despliegue
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                driver_response = await client.post(
                    f"{DRIVERS_URL}/deploy-slice",
                    json=driver_payload,
                    headers={"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
                )
                
                if driver_response.status_code != 200:
                    raise Exception(f"Error en driver: {driver_response.text}")
                
                driver_result = driver_response.json()
                
                if not driver_result.get('success'):
                    error_msg = driver_result.get('error', 'Despliegue fallido')
                    logger.error(f"Slice {slice_id}: Despliegue fallido - {error_msg}")
                    raise Exception(f"Despliegue fallido: {error_msg}")
                
                # Obtener el JSON procesado con puertos VNC asignados
                processed_json = driver_result.get('processed_json', {})
                
                # IMPRIMIR JSON FINAL CON PUERTOS VNC
                logger.info(f"\n{'='*80}")
                logger.info(f"Slice {slice_id}: JSON FINAL DESPUÉS DEL DESPLIEGUE")
                logger.info(f"{'='*80}")
                logger.info(json.dumps(processed_json, indent=2, ensure_ascii=False))
                logger.info(f"{'='*80}\n")
                
                logger.info(f"Slice {slice_id}: Despliegue exitoso")
                
        except Exception as e:
            logger.error(f"Slice {slice_id}: Error en despliegue: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error en despliegue: {str(e)}"
            )
        
        # ===== PASO 5: Actualizar BD con datos del despliegue =====
        logger.info(f"Slice {slice_id}: Actualizando BD con datos del despliegue...")
        
        try:
            connection = mysql.connector.connect(**DB_CONFIG)
            cursor = connection.cursor(dictionary=True)
            
            # El processed_json ya viene con los puertos VNC asignados por el orquestador
            # Extraer todas las VMs de todas las topologías desde processed_json
            all_vms = []
            for topology in processed_json.get('topologias', []):
                for vm in topology.get('vms', []):
                    # Agregar campo estado a cada VM
                    vm['estado'] = 'Corriendo'
                    all_vms.append(vm)
            
            # Timestamp de despliegue
            timestamp_despliegue = datetime.now(lima_tz).strftime("%Y-%m-%d %H:%M:%S")
            
            # Preparar datos para actualizar
            peticion_json_str = json.dumps(processed_json, ensure_ascii=False)
            vms_json_str = json.dumps(all_vms, ensure_ascii=False)
            
            # Actualizar BD (sin columna vncs)
            update_query = """
                UPDATE slices 
                SET tipo = %s,
                    estado = %s,
                    peticion_json = %s,
                    vms = %s,
                    timestamp_despliegue = %s
                WHERE id = %s
            """
            cursor.execute(update_query, (
                'desplegado',
                'corriendo',
                peticion_json_str,
                vms_json_str,
                timestamp_despliegue,
                slice_id
            ))
            connection.commit()
            
            cursor.close()
            connection.close()
            
            logger.info(f"Slice {slice_id}: BD actualizada - tipo=desplegado, estado=corriendo")
            logger.info(f"Slice {slice_id}: VMs guardadas: {len(all_vms)} VMs con puertos VNC")
            
        except Error as e:
            logger.error(f"Slice {slice_id}: Error al actualizar BD: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al actualizar BD después del despliegue: {str(e)}"
            )
        
        # ===== PASO 6: Retornar resumen completo =====
        return {
            "success": True,
            "message": f"Slice {slice_id} creado, mapeado y desplegado exitosamente",
            "slice_id": slice_id,
            "nombre_slice": slice_request.nombre_slice,
            "zona_despliegue": slice_request.zona_despliegue,
            "usuario_id": user['id'],
            "usuario_correo": user['correo'],
            "tipo": "desplegado",
            "estado": "corriendo",
            "timestamp_creacion": timestamp_creacion,
            "timestamp_despliegue": timestamp_despliegue,
            "networking": {
                "vlans_allocated": net_sec_result['vlans_allocated'],
                "vlans_string": net_sec_result['vlans_string'],
                "network_allocated": net_sec_result['network_allocated'],
                "total_links": net_sec_result['total_links'],
                "vlan_mapping": net_sec_result['vlan_mapping']
            },
            "deployment": {
                "status": "deployed",
                "zone": slice_request.zona_despliegue,
                "total_vms": len(all_vms),
                "processed_json": processed_json
            }
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
        
        # Actualizar estado de todas las VMs en BD
        vms = slice_data.get('vms')
        if vms and isinstance(vms, str):
            vms = json.loads(vms)
        
        if vms:
            # Actualizar estado de todas las VMs a "Apagado"
            for vm in vms:
                vm['estado'] = 'Apagado'
            
            # Guardar VMs actualizadas
            vms_json_str = json.dumps(vms, ensure_ascii=False)
            update_vms_query = "UPDATE slices SET vms = %s WHERE id = %s"
            cursor.execute(update_vms_query, (vms_json_str, slice_id))
            connection.commit()
        
        # Actualizar estado del slice en BD
        update_query = "UPDATE slices SET estado = %s WHERE id = %s"
        cursor.execute(update_query, ('apagado', slice_id))
        connection.commit()
        
        cursor.close()
        connection.close()
        
        logger.info(f"Slice {slice_id} apagado exitosamente")
        
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
        
        # Actualizar estado de todas las VMs en BD
        vms = slice_data.get('vms')
        if vms and isinstance(vms, str):
            vms = json.loads(vms)
        
        if vms:
            # Actualizar estado de todas las VMs a "Corriendo"
            for vm in vms:
                vm['estado'] = 'Corriendo'
            
            # Guardar VMs actualizadas
            vms_json_str = json.dumps(vms, ensure_ascii=False)
            update_vms_query = "UPDATE slices SET vms = %s WHERE id = %s"
            cursor.execute(update_vms_query, (vms_json_str, slice_id))
            connection.commit()
        
        # Actualizar estado del slice en BD
        update_query = "UPDATE slices SET estado = %s WHERE id = %s"
        cursor.execute(update_query, ('corriendo', slice_id))
        connection.commit()
        
        cursor.close()
        connection.close()
        
        logger.info(f"Slice {slice_id} encendido exitosamente")
        
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

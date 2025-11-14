#!/usr/bin/env python3

import subprocess
import asyncio
import os
import hashlib
import time
import base64
import sys
import grp
import aiohttp
from typing import List, Tuple, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends, status, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import uvicorn
import logging
import libvirt
import xml.etree.ElementTree as ET
from xml.dom import minidom

# Verificar permisos de libvirt al inicio
def check_libvirt_permissions():
    """Verificar que el usuario tenga permisos de libvirt"""
    try:
        # Obtener grupos del usuario actual
        groups = [grp.getgrgid(g).gr_name for g in os.getgroups()]
        
        if 'libvirt' not in groups and os.geteuid() != 0:
            print("=" * 60)
            print("⚠️  ADVERTENCIA: No tienes permisos de libvirt")
            print("=" * 60)
            print("\nEjecuta uno de estos comandos:\n")
            print("1. Opción rápida (recomendado):")
            print("   sg libvirt -c 'python3 vm_node_manager.py'\n")
            print("2. O agregar permanentemente:")
            print("   sudo usermod -aG libvirt $USER")
            print("   Luego cierra sesión y vuelve a entrar\n")
            print("3. O ejecutar con sudo:")
            print("   sudo python3 vm_node_manager.py\n")
            print("=" * 60)
            
            # Intentar conectar de todas formas
            try:
                conn = libvirt.open("qemu:///system")
                if conn:
                    conn.close()
                    print("✓ Conexión a libvirt exitosa a pesar de la advertencia")
                    return True
            except libvirt.libvirtError as e:
                print(f"✗ Error al conectar a libvirt: {e}")
                print("\nNo se puede continuar sin permisos de libvirt.")
                print("=" * 60)
                sys.exit(1)
        else:
            print("✓ Permisos de libvirt verificados correctamente")
            return True
    except Exception as e:
        print(f"⚠️  No se pudo verificar permisos: {e}")
        return True  # Continuar de todas formas

# Verificar permisos al importar
check_libvirt_permissions()

# Configuración
SECRET_TOKEN = "clavesihna"
security = HTTPBearer()

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Conexión a libvirt
# Usar socket con permisos de grupo libvirt
LIBVIRT_URI = "qemu:///system"

# Configuración del Image Manager API
IMAGE_MANAGER_URL = "https://192.168.203.1"
IMAGE_MANAGER_TOKEN = "clavesihna"
IMAGES_DIR = "/var/lib/virt/images"

# Hostname del worker
WORKER_HOSTNAME = "Worker 1"

# Control de concurrencia global
operation_lock = asyncio.Lock()

# Locks por ID para evitar operaciones concurrentes en el mismo ID
id_locks = {}

app = FastAPI(
    title="VM Management API",
    description="API Completa para Crear, Pausar, Reanudar y Eliminar VMs por ID",
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Modelos Pydantic para requests
class CreateVMRequest(BaseModel):
    id: int = Field(..., ge=1, le=9999, description="ID único de la VM")
    vm_name: str = Field(..., min_length=1, max_length=50, description="Nombre de la VM")
    ovs_name: str = Field(..., description="Nombre del bridge OVS")
    cpu_cores: int = Field(..., ge=1, le=32, description="Número de cores de CPU")
    ram_size: str = Field(..., description="Tamaño de RAM (ej: 512M, 1G, 2G)")
    storage_size: str = Field(..., description="Tamaño de almacenamiento (ej: 10G, 20G)")
    vnc_port: int = Field(..., ge=1, le=99, description="Puerto VNC (se suma a 5900)")
    image: str = Field(..., description="Nombre de la imagen (ej: cirros-0.5.1-x86_64-disk.img)")
    vlans: str = Field(..., description="VLANs separadas por coma (ej: '100,200,300')")

class VMOperationRequest(BaseModel):
    id: int = Field(..., ge=1, le=9999, description="ID de las VMs a operar")

class SingleVMOperationRequest(BaseModel):
    id: int = Field(..., ge=1, le=9999, description="ID del slice")
    vm_name: str = Field(..., min_length=1, max_length=50, description="Nombre de la VM (ej: vm1, vm2, vm3)")

class StatusRequest(BaseModel):
    id: int = Field(..., ge=1, le=9999, description="ID para verificar estado")

# Modelos Pydantic para responses
class VMInfo(BaseModel):
    name: str
    uuid: str
    id: int
    status: str
    ram_mb: float
    cpu_time: str
    vcpus: int

class TAPInterface(BaseModel):
    name: str
    state: str
    vlan: int

class VMResponse(BaseModel):
    success: bool
    message: str
    details: Optional[Dict[str, Any]] = None

class StatusResponse(BaseModel):
    success: bool
    id: int
    total_vms: int
    running_vms: int
    paused_vms: int
    vms: List[VMInfo] = []
    tap_interfaces: List[TAPInterface] = []
    disk_images: List[str] = []
    cloud_init_isos: List[str] = []

# Autenticación
async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    if credentials.credentials != SECRET_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

# Funciones auxiliares libvirt
def get_libvirt_connection():
    """Obtener conexión a libvirt"""
    try:
        conn = libvirt.open(LIBVIRT_URI)
        if conn is None:
            raise Exception("Error conectando a libvirt")
        return conn
    except libvirt.libvirtError as e:
        logger.error(f"Error libvirt: {str(e)}")
        raise Exception(f"Error conectando a libvirt: {str(e)}")

async def run_sudo_command(command: str, timeout: int = 30) -> Tuple[bool, str]:
    """Ejecutar comando con sudo usando contraseña"""
    try:
        cmd = f'echo "grupouno" | sudo -S {command}'
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        
        output = (stdout.decode() + stderr.decode()).strip()
        success = process.returncode == 0
        
        return success, output
    except asyncio.TimeoutError:
        return False, "Timeout ejecutando comando"
    except Exception as e:
        return False, f"Error ejecutando comando: {str(e)}"

async def get_id_lock(vm_id: int) -> asyncio.Lock:
    """Obtener lock específico para un ID"""
    if vm_id not in id_locks:
        id_locks[vm_id] = asyncio.Lock()
    return id_locks[vm_id]

async def download_image_from_manager(image_name: str) -> Tuple[bool, str]:
    """Descargar imagen desde Image Manager API"""
    try:
        # URL del endpoint de descarga
        url = f"{IMAGE_MANAGER_URL}/images/download"
        params = {"nombre": image_name}
        headers = {"Authorization": f"Bearer {IMAGE_MANAGER_TOKEN}"}
        
        # Ruta temporal para descargar
        temp_path = f"/tmp/{image_name}.qcow2"
        # Ruta final
        image_path = f"{IMAGES_DIR}/{image_name}.qcow2"
        
        logger.info(f"Descargando imagen '{image_name}' desde Image Manager...")
        
        # Configurar SSL (desactivar verificación para desarrollo)
        import ssl
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=300)) as response:
                
                if response.status == 200:
                    # Descargar el archivo a /tmp primero
                    total_size = int(response.headers.get('content-length', 0))
                    downloaded = 0
                    
                    with open(temp_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            # Log de progreso cada 10MB
                            if total_size > 0 and downloaded % (10 * 1024 * 1024) < 8192:
                                progress = (downloaded / total_size) * 100
                                logger.info(f"Descarga: {progress:.1f}% ({downloaded}/{total_size} bytes)")
                    
                    logger.info(f"Imagen descargada a {temp_path}, moviendo a {image_path}...")
                    
                    # Mover con sudo al directorio final
                    success, output = await run_sudo_command(f'mv "{temp_path}" "{image_path}"')
                    if not success:
                        # Si falla, intentar limpiar
                        try:
                            os.unlink(temp_path)
                        except:
                            pass
                        return False, f"Error moviendo imagen: {output}"
                    
                    # Dar permisos adecuados
                    await run_sudo_command(f'chmod 644 "{image_path}"')
                    await run_sudo_command(f'chown libvirt-qemu:kvm "{image_path}" || true')
                    
                    logger.info(f"Imagen '{image_name}.qcow2' descargada exitosamente")
                    return True, image_path
                
                elif response.status == 404:
                    error_msg = f"Imagen '{image_name}' no encontrada en Image Manager"
                    logger.error(error_msg)
                    return False, error_msg
                
                elif response.status == 401:
                    error_msg = "Error de autenticación con Image Manager"
                    logger.error(error_msg)
                    return False, error_msg
                
                else:
                    error_text = await response.text()
                    error_msg = f"Error HTTP {response.status}: {error_text}"
                    logger.error(error_msg)
                    return False, error_msg
                    
    except asyncio.TimeoutError:
        error_msg = "Timeout descargando imagen (>5 min)"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Error descargando imagen: {str(e)}"
        logger.error(error_msg)
        # Limpiar archivo temporal si existe
        try:
            temp_path = f"/tmp/{image_name}.qcow2"
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except:
            pass
        return False, error_msg

async def ensure_image_exists(image_name: str) -> Tuple[bool, str, str]:
    """
    Asegurar que la imagen existe, descargándola si es necesario
    
    Returns:
        Tuple[bool, str, str]: (success, image_path, message)
    """
    try:
        # Usar el nombre de la imagen tal cual viene
        image_path = f"{IMAGES_DIR}/{image_name}"
        
        # Verificar si la imagen ya existe
        if os.path.exists(image_path):
            logger.info(f"Imagen '{image_name}' encontrada localmente")
            return True, image_path, "Imagen encontrada localmente"
        
        # Si no existe, retornar error (descarga desactivada temporalmente)
        error_msg = f"Imagen '{image_name}' no encontrada en {IMAGES_DIR}"
        logger.error(error_msg)
        return False, "", error_msg
            
    except Exception as e:
        error_msg = f"Error verificando imagen: {str(e)}"
        logger.error(error_msg)
        return False, "", error_msg

def get_vm_state_string(state: int) -> str:
    """Convertir estado libvirt a string legible"""
    states = {
        libvirt.VIR_DOMAIN_NOSTATE: 'SIN_ESTADO',
        libvirt.VIR_DOMAIN_RUNNING: 'CORRIENDO',
        libvirt.VIR_DOMAIN_BLOCKED: 'BLOQUEADO',
        libvirt.VIR_DOMAIN_PAUSED: 'PAUSADO',
        libvirt.VIR_DOMAIN_SHUTDOWN: 'APAGANDO',
        libvirt.VIR_DOMAIN_SHUTOFF: 'APAGADO',
        libvirt.VIR_DOMAIN_CRASHED: 'CRASHEADO',
        libvirt.VIR_DOMAIN_PMSUSPENDED: 'SUSPENDIDO'
    }
    return states.get(state, f'DESCONOCIDO({state})')

def get_running_vms(vm_id: int) -> List[Dict[str, Any]]:
    """Obtener VMs corriendo para un ID específico usando libvirt"""
    vm_pattern = f"id{vm_id}-"
    vms = []
    
    try:
        conn = get_libvirt_connection()
        
        # Obtener todas las VMs (activas e inactivas)
        all_domains = conn.listAllDomains(0)
        
        for domain in all_domains:
            try:
                name = domain.name()
                if name.startswith(vm_pattern):
                    state, _ = domain.state()
                    info = domain.info()
                    
                    # info[0] = state, info[1] = max memory, info[2] = memory usado, 
                    # info[3] = num virtual CPUs, info[4] = cpu time in nanoseconds
                    memory_mb = info[2] / 1024  # Convertir de KB a MB
                    cpu_time = f"{info[4] / 1e9:.2f}s"  # Convertir nanosegundos a segundos
                    
                    vms.append({
                        'name': name,
                        'uuid': domain.UUIDString(),
                        'id': domain.ID() if domain.ID() >= 0 else -1,
                        'status': get_vm_state_string(state),
                        'ram_mb': memory_mb,
                        'cpu_time': cpu_time,
                        'vcpus': info[3]
                    })
            except libvirt.libvirtError as e:
                logger.warning(f"Error obteniendo info de dominio: {str(e)}")
                continue
        
        conn.close()
    except Exception as e:
        logger.error(f"Error listando VMs con libvirt: {str(e)}")
    
    return vms

async def get_tap_interfaces(vm_id: int) -> List[Dict[str, Any]]:
    """Obtener interfaces TAP para un ID específico"""
    vm_pattern = f"id{vm_id}-"
    
    success, output = await run_sudo_command("ip link show")
    if not success:
        return []
    
    interfaces = []
    for line in output.split('\n'):
        # Buscar interfaces con el patrón id{vm_id}-vm1-tap{vlan}
        if vm_pattern in line and '-t' in line:
            # Extraer nombre de interfaz
            parts = line.split(':')
            if len(parts) >= 2:
                interface_name = parts[1].strip()
                
                # Extraer VLAN del nombre
                vlan = 0
                try:
                    if '-t' in interface_name:
                        vlan_part = interface_name.split('-t')[-1]
                        vlan = int(vlan_part)
                except:
                    pass
                
                # Determinar estado
                state = 'DOWN'
                if 'UP' in line:
                    state = 'UP'
                elif 'DOWN' in line:
                    state = 'DOWN'
                
                interfaces.append({
                    'name': interface_name,
                    'state': state,
                    'vlan': vlan
                })
    
    return interfaces

async def get_disk_images(vm_id: int) -> List[str]:
    """Obtener imágenes de disco para un ID específico"""
    vm_pattern = f"id{vm_id}-"
    
    try:
        files = os.listdir('/var/lib/virt/images/')
        return [f for f in files if f.startswith(vm_pattern) and f.endswith('.qcow2')]
    except:
        return []

async def get_cloud_init_isos(vm_id: int) -> List[str]:
    """Obtener ISOs cloud-init para un ID específico"""
    vm_pattern = f"id{vm_id}-"
    
    try:
        files = os.listdir('/var/lib/virt/images/')
        return [f for f in files if f.startswith(vm_pattern) and f.endswith('-cloud-init.iso')]
    except:
        return []

# =============================================================================
# LÓGICAS PRINCIPALES DE OPERACIONES
# =============================================================================

async def create_vm_internal(request: CreateVMRequest) -> Dict[str, Any]:
    """Lógica interna para crear VM usando libvirt"""
    
    lock = await get_id_lock(request.id)
    
    async with lock:
        try:
            # Verificar/descargar imagen
            success, image_path, message = await ensure_image_exists(request.image)
            
            if not success:
                return {
                    'success': False,
                    'message': f'Error con la imagen: {message}',
                    'details': {'error': 'image_not_available'}
                }
            
            steps = [message]  # Agregar primer paso
            
            # Configuraciones derivadas
            hostname = f"id{request.id}-{request.vm_name}"
            vm_disk_path = f"/var/lib/virt/images/{hostname}.qcow2"
            
            # Parsear VLANs
            try:
                vlans = [vlan.strip() for vlan in request.vlans.split(',')]
                for vlan in vlans:
                    if not 1 <= int(vlan) <= 4094:
                        return {
                            'success': False,
                            'message': f'VLAN {vlan} fuera de rango válido (1-4094)',
                            'details': {'error': 'invalid_vlan'}
                        }
            except ValueError:
                return {
                    'success': False,
                    'message': 'Formato de VLANs inválido',
                    'details': {'error': 'invalid_vlan_format'}
                }
            
            # 1. Verificar que el directorio existe
            if not os.path.exists('/var/lib/virt/images'):
                success, _ = await run_sudo_command("mkdir -p /var/lib/virt/images")
                if not success:
                    return {
                        'success': False,
                        'message': 'Error creando directorios',
                        'details': {'error': 'directory_creation_failed'}
                    }
            steps.append("Directorios verificados")
            
            # 2. Crear imagen delta
            create_img_cmd = f'qemu-img create -f qcow2 -F qcow2 -b "{image_path}" "{vm_disk_path}" {request.storage_size}'
            success, output = await run_sudo_command(create_img_cmd)
            if success:
                steps.append("Imagen delta creada")
            else:
                return {
                    'success': False,
                    'message': f'Error creando imagen delta: {output}',
                    'details': {'error': 'image_creation_failed'}
                }
            
            # 3. Crear configuración cloud-init
            cloud_init_result = await create_cloud_init_config(hostname, image_path, vlans)
            if cloud_init_result['success']:
                steps.append("Configuración cloud-init creada")
                cloud_init_iso = cloud_init_result['iso_path']
            else:
                await run_sudo_command(f'rm -f "{vm_disk_path}"')
                return {
                    'success': False,
                    'message': cloud_init_result['message'],
                    'details': {'error': 'cloud_init_failed'}
                }
            
            # 4. Crear interfaces TAP
            tap_result = await create_tap_interfaces(request.id, request.vm_name, vlans, request.ovs_name)
            if tap_result['success']:
                steps.append(f"Interfaces TAP creadas: {len(tap_result['interfaces'])}")
                tap_interfaces = tap_result['interfaces']
                mac_addresses = tap_result['mac_addresses']
            else:
                # Limpiar recursos creados
                await run_sudo_command(f'rm -f "{vm_disk_path}" "{cloud_init_iso}"')
                return {
                    'success': False,
                    'message': tap_result['message'],
                    'details': {'error': 'tap_creation_failed'}
                }
            
            # 5. Crear XML de definición de VM usando libvirt
            vm_xml = create_domain_xml(
                hostname=hostname,
                ram_mb=parse_memory_size(request.ram_size),
                cpu_cores=request.cpu_cores,
                vnc_port=5900 + request.vnc_port,
                vm_disk_path=vm_disk_path,
                cloud_init_iso=cloud_init_iso,
                tap_interfaces=tap_interfaces,
                mac_addresses=mac_addresses
            )
            
            # 6. Definir e iniciar VM con libvirt
            try:
                conn = get_libvirt_connection()
                
                # Definir el dominio (VM)
                domain = conn.defineXML(vm_xml)
                if domain is None:
                    raise Exception("Error definiendo dominio")
                
                steps.append("VM definida en libvirt")
                
                # Iniciar la VM
                if domain.create() < 0:
                    raise Exception("Error iniciando VM")
                
                steps.append("VM iniciada")
                
                # Obtener información de la VM
                vm_uuid = domain.UUIDString()
                vm_id_libvirt = domain.ID()
                
                conn.close()
                
                # Resultado exitoso
                return {
                    'success': True,
                    'message': f'VM {hostname} creada exitosamente',
                    'details': {
                        'hostname': hostname,
                        'uuid': vm_uuid,
                        'id': vm_id_libvirt,
                        'vnc_port': 5900 + request.vnc_port,
                        'vlans': vlans,
                        'tap_interfaces': len(tap_interfaces),
                        'steps': steps
                    }
                }
                
            except libvirt.libvirtError as e:
                logger.error(f"Error libvirt creando VM: {str(e)}")
                await cleanup_failed_creation(request.id, tap_interfaces, request.ovs_name, vm_disk_path, cloud_init_iso)
                return {
                    'success': False,
                    'message': f'Error libvirt: {str(e)}',
                    'details': {'error': 'libvirt_error'}
                }
            
        except Exception as e:
            logger.error(f"Error interno creando VM: {str(e)}")
            return {
                'success': False,
                'message': f'Error interno: {str(e)}',
                'details': {'error': 'internal_error'}
            }

async def pause_vms_internal(vm_id: int) -> Dict[str, Any]:
    """Lógica interna para pausar VMs usando libvirt"""
    
    lock = await get_id_lock(vm_id)
    
    async with lock:
        try:
            vm_pattern = f"id{vm_id}-"
            conn = get_libvirt_connection()
            
            all_domains = conn.listAllDomains(0)
            target_domains = [d for d in all_domains if d.name().startswith(vm_pattern)]
            
            if not target_domains:
                conn.close()
                return {
                    'success': False,
                    'message': f'No se encontraron VMs para ID {vm_id}',
                    'details': {'paused_count': 0, 'error_count': 0}
                }
            
            # Filtrar VMs que están corriendo (no pausadas)
            running_domains = []
            already_paused = 0
            
            for domain in target_domains:
                state, _ = domain.state()
                if state == libvirt.VIR_DOMAIN_RUNNING:
                    running_domains.append(domain)
                elif state == libvirt.VIR_DOMAIN_PAUSED:
                    already_paused += 1
            
            if not running_domains:
                conn.close()
                return {
                    'success': True,
                    'message': f'Todas las VMs del ID {vm_id} ya están pausadas',
                    'details': {'paused_count': 0, 'already_paused': already_paused}
                }
            
            # Pausar cada VM
            paused_count = 0
            error_count = 0
            paused_vms = []
            
            for domain in running_domains:
                try:
                    if domain.suspend() == 0:
                        paused_count += 1
                        paused_vms.append(domain.name())
                    else:
                        error_count += 1
                except libvirt.libvirtError as e:
                    logger.warning(f"Error pausando {domain.name()}: {str(e)}")
                    error_count += 1
            
            conn.close()
            
            if error_count == 0:
                return {
                    'success': True,
                    'message': f'ID {vm_id} pausado correctamente - {paused_count} VMs pausadas',
                    'details': {'paused_count': paused_count, 'paused_vms': paused_vms}
                }
            else:
                return {
                    'success': paused_count > 0,
                    'message': f'ID {vm_id} parcialmente pausado - {paused_count} exitosas, {error_count} errores',
                    'details': {'paused_count': paused_count, 'error_count': error_count, 'paused_vms': paused_vms}
                }
                
        except Exception as e:
            logger.error(f"Error pausando VMs ID {vm_id}: {str(e)}")
            return {
                'success': False,
                'message': f'Error interno pausando VMs: {str(e)}',
                'details': {'error': 'internal_error'}
            }

async def resume_vms_internal(vm_id: int) -> Dict[str, Any]:
    """Lógica interna para reanudar VMs usando libvirt"""
    
    lock = await get_id_lock(vm_id)
    
    async with lock:
        try:
            vm_pattern = f"id{vm_id}-"
            conn = get_libvirt_connection()
            
            all_domains = conn.listAllDomains(0)
            target_domains = [d for d in all_domains if d.name().startswith(vm_pattern)]
            
            if not target_domains:
                conn.close()
                return {
                    'success': False,
                    'message': f'No se encontraron VMs para ID {vm_id}',
                    'details': {'resumed_count': 0, 'error_count': 0}
                }
            
            # Filtrar VMs que están pausadas
            paused_domains = []
            already_running = 0
            
            for domain in target_domains:
                state, _ = domain.state()
                if state == libvirt.VIR_DOMAIN_PAUSED:
                    paused_domains.append(domain)
                elif state == libvirt.VIR_DOMAIN_RUNNING:
                    already_running += 1
            
            if not paused_domains:
                conn.close()
                return {
                    'success': True,
                    'message': f'Todas las VMs del ID {vm_id} ya están corriendo',
                    'details': {'resumed_count': 0, 'already_running': already_running}
                }
            
            # Reanudar cada VM pausada
            resumed_count = 0
            error_count = 0
            resumed_vms = []
            
            for domain in paused_domains:
                try:
                    if domain.resume() == 0:
                        resumed_count += 1
                        resumed_vms.append(domain.name())
                    else:
                        error_count += 1
                except libvirt.libvirtError as e:
                    logger.warning(f"Error reanudando {domain.name()}: {str(e)}")
                    error_count += 1
            
            conn.close()
            
            if error_count == 0:
                return {
                    'success': True,
                    'message': f'ID {vm_id} reanudado correctamente - {resumed_count} VMs reanudadas',
                    'details': {'resumed_count': resumed_count, 'resumed_vms': resumed_vms}
                }
            else:
                return {
                    'success': resumed_count > 0,
                    'message': f'ID {vm_id} parcialmente reanudado - {resumed_count} exitosas, {error_count} errores',
                    'details': {'resumed_count': resumed_count, 'error_count': error_count, 'resumed_vms': resumed_vms}
                }
                
        except Exception as e:
            logger.error(f"Error reanudando VMs ID {vm_id}: {str(e)}")
            return {
                'success': False,
                'message': f'Error interno reanudando VMs: {str(e)}',
                'details': {'error': 'internal_error'}
            }

async def cleanup_vms_internal(vm_id: int) -> Dict[str, Any]:
    """Lógica interna para limpiar VMs usando libvirt"""
    
    lock = await get_id_lock(vm_id)
    
    async with lock:
        try:
            vm_pattern = f"id{vm_id}-"
            steps = []
            errors = []
            
            # 1. Detener y eliminar VMs usando libvirt
            conn = get_libvirt_connection()
            all_domains = conn.listAllDomains(0)
            target_domains = [d for d in all_domains if d.name().startswith(vm_pattern)]
            
            if target_domains:
                steps.append(f"Deteniendo y eliminando {len(target_domains)} VMs")
                for domain in target_domains:
                    try:
                        # Destruir VM si está corriendo
                        if domain.isActive():
                            domain.destroy()  # Forzar apagado
                        
                        # Remover definición persistente
                        domain.undefine()
                        steps.append(f"VM {domain.name()} eliminada")
                    except libvirt.libvirtError as e:
                        logger.warning(f"Error eliminando {domain.name()}: {str(e)}")
                        errors.append(f"Error eliminando VM {domain.name()}")
            else:
                steps.append("No hay VMs en libvirt")
            
            conn.close()
            
            # 2. Eliminar interfaces TAP
            tap_interfaces = await get_tap_interfaces(vm_id)
            if tap_interfaces:
                removed_count = 0
                for tap in tap_interfaces:
                    # Remover del bridge OVS
                    await run_sudo_command(f"ovs-vsctl --if-exists del-port {tap['name']}")
                    
                    # Eliminar interfaz del sistema
                    success, _ = await run_sudo_command(f"ip link del {tap['name']}")
                    if success:
                        removed_count += 1
                
                steps.append(f"Eliminadas {removed_count} interfaces TAP")
            else:
                steps.append("No hay interfaces TAP que eliminar")
            
            # 3. Eliminar imágenes de disco
            success, _ = await run_sudo_command(f"rm -f /var/lib/virt/images/{vm_pattern}*.qcow2")
            if success:
                steps.append("Imágenes de disco eliminadas")
            else:
                errors.append("Error eliminando imágenes de disco")
            
            # 4. Eliminar ISOs cloud-init
            success, _ = await run_sudo_command(f"rm -f /var/lib/virt/images/{vm_pattern}*-cloud-init.iso")
            if success:
                steps.append("ISOs cloud-init eliminados")
            else:
                errors.append("Error eliminando ISOs cloud-init")
            
            # Verificación final
            remaining_vms = get_running_vms(vm_id)
            
            if not remaining_vms and not errors:
                return {
                    'success': True,
                    'message': f'ID {vm_id} eliminado completamente',
                    'details': {'steps': steps, 'cleanup_count': len(steps)}
                }
            elif remaining_vms:
                return {
                    'success': False,
                    'message': f'ID {vm_id} parcialmente eliminado - quedan {len(remaining_vms)} VMs',
                    'details': {'steps': steps, 'errors': errors, 'remaining_vms': len(remaining_vms)}
                }
            else:
                return {
                    'success': len(errors) < len(steps),
                    'message': f'ID {vm_id} mayormente eliminado con algunos errores menores',
                    'details': {'steps': steps, 'errors': errors}
                }
                
        except Exception as e:
            logger.error(f"Error limpiando VMs ID {vm_id}: {str(e)}")
            return {
                'success': False,
                'message': f'Error interno limpiando VMs: {str(e)}',
                'details': {'error': 'internal_error'}
            }

async def pause_single_vm_internal(vm_id: int, vm_name: str) -> Dict[str, Any]:
    """Lógica interna para pausar una VM específica de un slice"""
    
    lock = await get_id_lock(vm_id)
    
    async with lock:
        try:
            # Construir nombre completo de la VM
            full_vm_name = f"id{vm_id}-{vm_name}"
            
            conn = get_libvirt_connection()
            
            # Buscar la VM específica
            try:
                domain = conn.lookupByName(full_vm_name)
            except libvirt.libvirtError:
                conn.close()
                return {
                    'success': False,
                    'message': f'No se encontró la {vm_name} en {WORKER_HOSTNAME}',
                    'details': {'error': 'vm_not_found', 'worker': WORKER_HOSTNAME}
                }
            
            # Verificar estado actual
            state, _ = domain.state()
            
            if state == libvirt.VIR_DOMAIN_PAUSED:
                conn.close()
                return {
                    'success': True,
                    'message': f'VM {full_vm_name} ya está pausada',
                    'details': {'already_paused': True}
                }
            
            if state != libvirt.VIR_DOMAIN_RUNNING:
                conn.close()
                return {
                    'success': False,
                    'message': f'VM {full_vm_name} no está corriendo (estado: {get_vm_state_string(state)})',
                    'details': {'error': 'vm_not_running', 'current_state': get_vm_state_string(state)}
                }
            
            # Pausar la VM
            try:
                if domain.suspend() == 0:
                    conn.close()
                    return {
                        'success': True,
                        'message': f'VM {full_vm_name} pausada exitosamente',
                        'details': {'vm_name': full_vm_name}
                    }
                else:
                    conn.close()
                    return {
                        'success': False,
                        'message': f'Error pausando VM {full_vm_name}',
                        'details': {'error': 'pause_failed'}
                    }
            except libvirt.libvirtError as e:
                conn.close()
                logger.error(f"Error libvirt pausando {full_vm_name}: {str(e)}")
                return {
                    'success': False,
                    'message': f'Error libvirt pausando VM: {str(e)}',
                    'details': {'error': 'libvirt_error'}
                }
                
        except Exception as e:
            logger.error(f"Error pausando VM {vm_name} del ID {vm_id}: {str(e)}")
            return {
                'success': False,
                'message': f'Error interno pausando VM: {str(e)}',
                'details': {'error': 'internal_error'}
            }

async def resume_single_vm_internal(vm_id: int, vm_name: str) -> Dict[str, Any]:
    """Lógica interna para reanudar una VM específica de un slice"""
    
    lock = await get_id_lock(vm_id)
    
    async with lock:
        try:
            # Construir nombre completo de la VM
            full_vm_name = f"id{vm_id}-{vm_name}"
            
            conn = get_libvirt_connection()
            
            # Buscar la VM específica
            try:
                domain = conn.lookupByName(full_vm_name)
            except libvirt.libvirtError:
                conn.close()
                return {
                    'success': False,
                    'message': f'No se encontró la {vm_name} en {WORKER_HOSTNAME}',
                    'details': {'error': 'vm_not_found', 'worker': WORKER_HOSTNAME}
                }
            
            # Verificar estado actual
            state, _ = domain.state()
            
            if state == libvirt.VIR_DOMAIN_RUNNING:
                conn.close()
                return {
                    'success': True,
                    'message': f'VM {full_vm_name} ya está corriendo',
                    'details': {'already_running': True}
                }
            
            if state != libvirt.VIR_DOMAIN_PAUSED:
                conn.close()
                return {
                    'success': False,
                    'message': f'VM {full_vm_name} no está pausada (estado: {get_vm_state_string(state)})',
                    'details': {'error': 'vm_not_paused', 'current_state': get_vm_state_string(state)}
                }
            
            # Reanudar la VM
            try:
                if domain.resume() == 0:
                    conn.close()
                    return {
                        'success': True,
                        'message': f'VM {full_vm_name} reanudada exitosamente',
                        'details': {'vm_name': full_vm_name}
                    }
                else:
                    conn.close()
                    return {
                        'success': False,
                        'message': f'Error reanudando VM {full_vm_name}',
                        'details': {'error': 'resume_failed'}
                    }
            except libvirt.libvirtError as e:
                conn.close()
                logger.error(f"Error libvirt reanudando {full_vm_name}: {str(e)}")
                return {
                    'success': False,
                    'message': f'Error libvirt reanudando VM: {str(e)}',
                    'details': {'error': 'libvirt_error'}
                }
                
        except Exception as e:
            logger.error(f"Error reanudando VM {vm_name} del ID {vm_id}: {str(e)}")
            return {
                'success': False,
                'message': f'Error interno reanudando VM: {str(e)}',
                'details': {'error': 'internal_error'}
            }

async def shutdown_single_vm_internal(vm_id: int, vm_name: str) -> Dict[str, Any]:
    """Lógica interna para apagar una VM específica de un slice"""
    
    lock = await get_id_lock(vm_id)
    
    async with lock:
        try:
            # Construir nombre completo de la VM
            full_vm_name = f"id{vm_id}-{vm_name}"
            
            conn = get_libvirt_connection()
            
            # Buscar la VM específica
            try:
                domain = conn.lookupByName(full_vm_name)
            except libvirt.libvirtError:
                conn.close()
                return {
                    'success': False,
                    'message': f'No se encontró la {vm_name} en {WORKER_HOSTNAME}',
                    'details': {'error': 'vm_not_found', 'worker': WORKER_HOSTNAME}
                }
            
            # Verificar estado actual
            state, _ = domain.state()
            
            if state == libvirt.VIR_DOMAIN_SHUTOFF:
                conn.close()
                return {
                    'success': True,
                    'message': f'VM {full_vm_name} ya está apagada',
                    'details': {'already_shutoff': True}
                }
            
            # Apagar la VM forzadamente (destroy = apagado inmediato)
            try:
                if domain.destroy() == 0:
                    conn.close()
                    return {
                        'success': True,
                        'message': f'VM {full_vm_name} apagada exitosamente',
                        'details': {'vm_name': full_vm_name}
                    }
                else:
                    conn.close()
                    return {
                        'success': False,
                        'message': f'Error apagando VM {full_vm_name}',
                        'details': {'error': 'shutdown_failed'}
                    }
            except libvirt.libvirtError as e:
                conn.close()
                logger.error(f"Error libvirt apagando {full_vm_name}: {str(e)}")
                return {
                    'success': False,
                    'message': f'Error libvirt apagando VM: {str(e)}',
                    'details': {'error': 'libvirt_error'}
                }
                
        except Exception as e:
            logger.error(f"Error apagando VM {vm_name} del ID {vm_id}: {str(e)}")
            return {
                'success': False,
                'message': f'Error interno apagando VM: {str(e)}',
                'details': {'error': 'internal_error'}
            }

async def start_single_vm_internal(vm_id: int, vm_name: str) -> Dict[str, Any]:
    """Lógica interna para encender una VM específica de un slice"""
    
    lock = await get_id_lock(vm_id)
    
    async with lock:
        try:
            # Construir nombre completo de la VM
            full_vm_name = f"id{vm_id}-{vm_name}"
            
            conn = get_libvirt_connection()
            
            # Buscar la VM específica
            try:
                domain = conn.lookupByName(full_vm_name)
            except libvirt.libvirtError:
                conn.close()
                return {
                    'success': False,
                    'message': f'No se encontró la {vm_name} en {WORKER_HOSTNAME}',
                    'details': {'error': 'vm_not_found', 'worker': WORKER_HOSTNAME}
                }
            
            # Verificar estado actual
            state, _ = domain.state()
            
            if state == libvirt.VIR_DOMAIN_RUNNING:
                conn.close()
                return {
                    'success': True,
                    'message': f'VM {full_vm_name} ya está corriendo',
                    'details': {'already_running': True}
                }
            
            if state != libvirt.VIR_DOMAIN_SHUTOFF:
                conn.close()
                return {
                    'success': False,
                    'message': f'VM {full_vm_name} no está apagada (estado: {get_vm_state_string(state)})',
                    'details': {'error': 'vm_not_shutoff', 'current_state': get_vm_state_string(state)}
                }
            
            # Encender la VM
            try:
                if domain.create() == 0:
                    conn.close()
                    return {
                        'success': True,
                        'message': f'VM {full_vm_name} encendida exitosamente',
                        'details': {'vm_name': full_vm_name}
                    }
                else:
                    conn.close()
                    return {
                        'success': False,
                        'message': f'Error encendiendo VM {full_vm_name}',
                        'details': {'error': 'start_failed'}
                    }
            except libvirt.libvirtError as e:
                conn.close()
                logger.error(f"Error libvirt encendiendo {full_vm_name}: {str(e)}")
                return {
                    'success': False,
                    'message': f'Error libvirt encendiendo VM: {str(e)}',
                    'details': {'error': 'libvirt_error'}
                }
                
        except Exception as e:
            logger.error(f"Error encendiendo VM {vm_name} del ID {vm_id}: {str(e)}")
            return {
                'success': False,
                'message': f'Error interno encendiendo VM: {str(e)}',
                'details': {'error': 'internal_error'}
            }

async def shutdown_slice_internal(vm_id: int) -> Dict[str, Any]:
    """Lógica interna para apagar todas las VMs de un slice"""
    
    lock = await get_id_lock(vm_id)
    
    async with lock:
        try:
            vm_pattern = f"id{vm_id}-"
            conn = get_libvirt_connection()
            
            all_domains = conn.listAllDomains(0)
            target_domains = [d for d in all_domains if d.name().startswith(vm_pattern)]
            
            if not target_domains:
                conn.close()
                return {
                    'success': False,
                    'message': f'No se encontraron VMs para ID {vm_id}',
                    'details': {'shutdown_count': 0, 'error_count': 0}
                }
            
            # Filtrar VMs que están corriendo o pausadas (pueden apagarse)
            active_domains = []
            already_shutoff = 0
            
            for domain in target_domains:
                state, _ = domain.state()
                if state in [libvirt.VIR_DOMAIN_RUNNING, libvirt.VIR_DOMAIN_PAUSED]:
                    active_domains.append(domain)
                elif state == libvirt.VIR_DOMAIN_SHUTOFF:
                    already_shutoff += 1
            
            if not active_domains:
                conn.close()
                return {
                    'success': True,
                    'message': f'Todas las VMs del ID {vm_id} ya están apagadas',
                    'details': {'shutdown_count': 0, 'already_shutoff': already_shutoff}
                }
            
            # Apagar cada VM activa
            shutdown_count = 0
            error_count = 0
            shutdown_vms = []
            
            for domain in active_domains:
                try:
                    if domain.destroy() == 0:
                        shutdown_count += 1
                        shutdown_vms.append(domain.name())
                    else:
                        error_count += 1
                except libvirt.libvirtError as e:
                    logger.warning(f"Error apagando {domain.name()}: {str(e)}")
                    error_count += 1
            
            conn.close()
            
            if error_count == 0:
                return {
                    'success': True,
                    'message': f'ID {vm_id} apagado correctamente - {shutdown_count} VMs apagadas',
                    'details': {'shutdown_count': shutdown_count, 'shutdown_vms': shutdown_vms}
                }
            else:
                return {
                    'success': shutdown_count > 0,
                    'message': f'ID {vm_id} parcialmente apagado - {shutdown_count} exitosas, {error_count} errores',
                    'details': {'shutdown_count': shutdown_count, 'error_count': error_count, 'shutdown_vms': shutdown_vms}
                }
                
        except Exception as e:
            logger.error(f"Error apagando VMs ID {vm_id}: {str(e)}")
            return {
                'success': False,
                'message': f'Error interno apagando VMs: {str(e)}',
                'details': {'error': 'internal_error'}
            }

async def start_slice_internal(vm_id: int) -> Dict[str, Any]:
    """Lógica interna para encender todas las VMs de un slice"""
    
    lock = await get_id_lock(vm_id)
    
    async with lock:
        try:
            vm_pattern = f"id{vm_id}-"
            conn = get_libvirt_connection()
            
            all_domains = conn.listAllDomains(0)
            target_domains = [d for d in all_domains if d.name().startswith(vm_pattern)]
            
            if not target_domains:
                conn.close()
                return {
                    'success': False,
                    'message': f'No se encontraron VMs para ID {vm_id}',
                    'details': {'started_count': 0, 'error_count': 0}
                }
            
            # Filtrar VMs que están apagadas
            shutoff_domains = []
            already_running = 0
            
            for domain in target_domains:
                state, _ = domain.state()
                if state == libvirt.VIR_DOMAIN_SHUTOFF:
                    shutoff_domains.append(domain)
                elif state == libvirt.VIR_DOMAIN_RUNNING:
                    already_running += 1
            
            if not shutoff_domains:
                conn.close()
                return {
                    'success': True,
                    'message': f'Todas las VMs del ID {vm_id} ya están corriendo',
                    'details': {'started_count': 0, 'already_running': already_running}
                }
            
            # Encender cada VM apagada
            started_count = 0
            error_count = 0
            started_vms = []
            
            for domain in shutoff_domains:
                try:
                    if domain.create() == 0:
                        started_count += 1
                        started_vms.append(domain.name())
                    else:
                        error_count += 1
                except libvirt.libvirtError as e:
                    logger.warning(f"Error encendiendo {domain.name()}: {str(e)}")
                    error_count += 1
            
            conn.close()
            
            if error_count == 0:
                return {
                    'success': True,
                    'message': f'ID {vm_id} encendido correctamente - {started_count} VMs encendidas',
                    'details': {'started_count': started_count, 'started_vms': started_vms}
                }
            else:
                return {
                    'success': started_count > 0,
                    'message': f'ID {vm_id} parcialmente encendido - {started_count} exitosas, {error_count} errores',
                    'details': {'started_count': started_count, 'error_count': error_count, 'started_vms': started_vms}
                }
                
        except Exception as e:
            logger.error(f"Error encendiendo VMs ID {vm_id}: {str(e)}")
            return {
                'success': False,
                'message': f'Error interno encendiendo VMs: {str(e)}',
                'details': {'error': 'internal_error'}
            }

# =============================================================================
# FUNCIONES AUXILIARES PARA CREAR VMS
# =============================================================================

def parse_memory_size(size_str: str) -> int:
    """Convertir string de memoria (512M, 1G, 2G) a MB"""
    size_str = size_str.upper().strip()
    
    if size_str.endswith('G'):
        return int(float(size_str[:-1]) * 1024)
    elif size_str.endswith('M'):
        return int(size_str[:-1])
    elif size_str.endswith('K'):
        return int(float(size_str[:-1]) / 1024)
    else:
        # Asumir MB si no hay unidad
        return int(size_str)

def create_domain_xml(hostname: str, ram_mb: int, cpu_cores: int, vnc_port: int,
                     vm_disk_path: str, cloud_init_iso: str, tap_interfaces: List[str],
                     mac_addresses: List[str]) -> str:
    """Crear XML de definición de dominio para libvirt"""
    
    # Crear estructura XML
    domain = ET.Element('domain', type='kvm')
    
    # Nombre
    name = ET.SubElement(domain, 'name')
    name.text = hostname
    
    # Memoria (en KB para libvirt)
    memory = ET.SubElement(domain, 'memory', unit='KiB')
    memory.text = str(ram_mb * 1024)
    
    current_memory = ET.SubElement(domain, 'currentMemory', unit='KiB')
    current_memory.text = str(ram_mb * 1024)
    
    # vCPUs
    vcpu = ET.SubElement(domain, 'vcpu', placement='static')
    vcpu.text = str(cpu_cores)
    
    # OS
    os_elem = ET.SubElement(domain, 'os')
    type_elem = ET.SubElement(os_elem, 'type', arch='x86_64', machine='pc')
    type_elem.text = 'hvm'
    ET.SubElement(os_elem, 'boot', dev='hd')
    
    # Features
    features = ET.SubElement(domain, 'features')
    ET.SubElement(features, 'acpi')
    ET.SubElement(features, 'apic')
    
    # CPU
    cpu = ET.SubElement(domain, 'cpu', mode='host-passthrough', check='none')
    
    # Clock
    clock = ET.SubElement(domain, 'clock', offset='utc')
    
    # Poder
    on_poweroff = ET.SubElement(domain, 'on_poweroff')
    on_poweroff.text = 'destroy'
    on_reboot = ET.SubElement(domain, 'on_reboot')
    on_reboot.text = 'restart'
    on_crash = ET.SubElement(domain, 'on_crash')
    on_crash.text = 'destroy'
    
    # Devices
    devices = ET.SubElement(domain, 'devices')
    
    # Emulator
    emulator = ET.SubElement(devices, 'emulator')
    emulator.text = '/usr/bin/qemu-system-x86_64'
    
    # Disco principal
    disk = ET.SubElement(devices, 'disk', type='file', device='disk')
    ET.SubElement(disk, 'driver', name='qemu', type='qcow2')
    ET.SubElement(disk, 'source', file=vm_disk_path)
    ET.SubElement(disk, 'target', dev='vda', bus='virtio')
    
    # Disco cloud-init (usar IDE o SATA para CDROM, no virtio)
    disk_cdrom = ET.SubElement(devices, 'disk', type='file', device='cdrom')
    ET.SubElement(disk_cdrom, 'driver', name='qemu', type='raw')
    ET.SubElement(disk_cdrom, 'source', file=cloud_init_iso)
    ET.SubElement(disk_cdrom, 'target', dev='hda', bus='ide')
    ET.SubElement(disk_cdrom, 'readonly')
    
    # Interfaces de red - Usar type='ethernet' sin scripts
    for i, (tap_name, mac_addr) in enumerate(zip(tap_interfaces, mac_addresses)):
        interface = ET.SubElement(devices, 'interface', type='ethernet')
        ET.SubElement(interface, 'mac', address=mac_addr)
        ET.SubElement(interface, 'target', dev=tap_name, managed='no')
        ET.SubElement(interface, 'model', type='e1000')
    
    # VNC
    graphics = ET.SubElement(devices, 'graphics', type='vnc', port=str(vnc_port), 
                            autoport='no', listen='0.0.0.0')
    ET.SubElement(graphics, 'listen', type='address', address='0.0.0.0')
    
    # Console serial
    console = ET.SubElement(devices, 'console', type='pty')
    ET.SubElement(console, 'target', type='serial', port='0')
    
    # Convertir a string XML formateado
    xml_str = ET.tostring(domain, encoding='unicode')
    
    # Formatear bonito (opcional pero útil para debugging)
    try:
        dom = minidom.parseString(xml_str)
        return dom.toprettyxml(indent="  ")
    except:
        return xml_str

async def create_cloud_init_config(hostname: str, image: str, vlans: List[str]) -> Dict[str, Any]:
    """Crear configuración cloud-init"""
    try:
        user_data_file = f"/home/ubuntu/user-data-{hostname}.yaml"
        meta_data_file = f"/home/ubuntu/meta-data-{hostname}.yaml"
        cloud_init_iso = f"/var/lib/virt/images/{hostname}-cloud-init.iso"
        
        # Detectar tipo de imagen
        if "cirros" in image.lower():
            os_type = "cirros"
        elif "ubuntu" in image.lower():
            os_type = "ubuntu"
        elif "alpine" in image.lower():
            os_type = "alpine"
        else:
            os_type = "generic"
        
        # Crear contenido user-data
        user_data_content = create_user_data_content(hostname, os_type, vlans)
        
        # Escribir user-data directamente en Python (sin sudo)
        try:
            with open(user_data_file, 'w') as f:
                f.write(user_data_content)
        except Exception as e:
            return {'success': False, 'message': f'Error escribiendo user-data: {str(e)}'}
        
        # Crear meta-data
        meta_data_content = f"""instance-id: {hostname}-{int(time.time())}
local-hostname: {hostname}
"""
        
        try:
            with open(meta_data_file, 'w') as f:
                f.write(meta_data_content)
        except Exception as e:
            return {'success': False, 'message': f'Error escribiendo meta-data: {str(e)}'}
        
        # Crear ISO
        iso_cmd = f'genisoimage -output "{cloud_init_iso}" -volid cidata -joliet -rock "{user_data_file}" "{meta_data_file}"'
        success, output = await run_sudo_command(iso_cmd)
        
        # Limpiar archivos temporales
        try:
            os.unlink(user_data_file)
            os.unlink(meta_data_file)
        except:
            pass  # No importa si no se pueden eliminar
        
        if success:
            return {'success': True, 'message': 'Cloud-init creado', 'iso_path': cloud_init_iso}
        else:
            return {'success': False, 'message': f'Error creando ISO: {output}'}
            
    except Exception as e:
        return {'success': False, 'message': f'Error configurando cloud-init: {str(e)}'}

def create_user_data_content(hostname: str, os_type: str, vlans: List[str]) -> str:
    """Crear contenido user-data según tipo de OS - Solo configuración de usuarios"""
    
    base_config = f"""#cloud-config
hostname: {hostname}
manage_etc_hosts: true
"""
    
    # Configuración de usuarios según tipo de OS
    user_config = ""
    if os_type == "cirros":
        # Cirros no necesita user-data, viene con usuario por defecto
        user_config = ""
    elif os_type == "ubuntu":
        user_config = """
users:
  - name: ubuntu
    plain_text_passwd: ubuntu
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock_passwd: false
"""
    elif os_type == "alpine":
        user_config = """
users:
  - name: alpine
    plain_text_passwd: alpine
    shell: /bin/ash
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock_passwd: false
    groups: wheel
"""
    else:  # generic
        user_config = """
users:
  - name: user
    plain_text_passwd: password
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock_passwd: false
"""
    
    return base_config + user_config

async def create_tap_interfaces(vm_id: int, vm_name: str, vlans: List[str], ovs_name: str) -> Dict[str, Any]:
    """Crear interfaces TAP para cada VLAN"""
    try:
        tap_interfaces = []
        mac_addresses = []
        
        for i, vlan in enumerate(vlans):
            tap_name = f"id{vm_id}-{vm_name}-t{vlan}"
            
            # Generar MAC address única
            interface_hash = hashlib.md5(f"id{vm_id}-{vm_name}-{vlan}-{i}".encode()).hexdigest()[:8]
            mac_parts = []
            for j in range(0, 8, 2):
                mac_parts.append(interface_hash[j:j+2])
            mac_addr = "52:54:" + ":".join(mac_parts[:4])
            
            # Crear interfaz TAP
            success, output = await run_sudo_command(f"ip tuntap add mode tap name {tap_name}")
            if not success:
                return {'success': False, 'message': f'Error creando TAP {tap_name}: {output}'}
            
            # Cambiar permisos para que libvirt pueda usar la interfaz
            success, output = await run_sudo_command(f"chown libvirt-qemu:kvm /dev/net/tun || true")
            
            # Levantar interfaz
            success, output = await run_sudo_command(f"ip link set dev {tap_name} up")
            if not success:
                await run_sudo_command(f"ip link del {tap_name}")
                return {'success': False, 'message': f'Error levantando {tap_name}: {output}'}
            
            # Conectar al bridge OVS
            success, output = await run_sudo_command(f'ovs-vsctl add-port {ovs_name} {tap_name} tag={vlan}')
            if not success:
                await run_sudo_command(f"ip link del {tap_name}")
                return {'success': False, 'message': f'Error conectando {tap_name} a OVS: {output}'}
            
            tap_interfaces.append(tap_name)
            mac_addresses.append(mac_addr)
        
        return {
            'success': True,
            'message': f'Creadas {len(tap_interfaces)} interfaces TAP',
            'interfaces': tap_interfaces,
            'mac_addresses': mac_addresses
        }
        
    except Exception as e:
        return {'success': False, 'message': f'Error interno creando TAPs: {str(e)}'}

async def cleanup_failed_creation(vm_id: int, tap_interfaces: List[str], ovs_name: str, 
                                vm_disk_path: str, cloud_init_iso: str):
    """Limpiar recursos en caso de fallo en creación"""
    for tap_name in tap_interfaces:
        await run_sudo_command(f"ovs-vsctl --if-exists del-port {ovs_name} {tap_name}")
        await run_sudo_command(f"ip link del {tap_name}")
    
    await run_sudo_command(f'rm -f "{vm_disk_path}" "{cloud_init_iso}"')

# =============================================================================
# ENDPOINTS DE LA API
# =============================================================================

@app.get("/health")
async def health_check():
    """Endpoint de salud"""
    return {"status": "ok", "service": "VM Management API", "version": "3.0.0"}

@app.get("/status/{vm_id}", response_model=StatusResponse)
async def get_vm_status(vm_id: int, token: str = Depends(verify_token)):
    """Obtener estado detallado de VMs por ID"""
    try:
        if not 1 <= vm_id <= 9999:
            raise HTTPException(status_code=400, detail="ID debe estar entre 1 y 9999")
        
        # Obtener información
        vms = get_running_vms(vm_id)
        tap_interfaces = await get_tap_interfaces(vm_id)
        disk_images = await get_disk_images(vm_id)
        cloud_init_isos = await get_cloud_init_isos(vm_id)
        
        # Contar estados
        running_count = len([vm for vm in vms if vm['status'] == 'CORRIENDO'])
        paused_count = len([vm for vm in vms if vm['status'] == 'PAUSADO'])
        
        # Convertir a modelos Pydantic
        vm_infos = [
            VMInfo(
                name=vm['name'],
                uuid=vm['uuid'],
                id=vm['id'],
                status=vm['status'],
                ram_mb=vm['ram_mb'],
                cpu_time=vm['cpu_time'],
                vcpus=vm['vcpus']
            )
            for vm in vms
        ]
        
        tap_infos = [
            TAPInterface(
                name=tap['name'],
                state=tap['state'],
                vlan=tap['vlan']
            )
            for tap in tap_interfaces
        ]
        
        return StatusResponse(
            success=True,
            id=vm_id,
            total_vms=len(vms),
            running_vms=running_count,
            paused_vms=paused_count,
            vms=vm_infos,
            tap_interfaces=tap_infos,
            disk_images=disk_images,
            cloud_init_isos=cloud_init_isos
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo estado ID {vm_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.post("/create", response_model=VMResponse)
async def create_vm_endpoint(request: CreateVMRequest, token: str = Depends(verify_token)):
    """Crear nueva VM"""
    try:
        if not 1 <= request.id <= 9999:
            raise HTTPException(status_code=400, detail="ID debe estar entre 1 y 9999")
        
        # Verificar que no existan VMs con el mismo ID y nombre
        existing_vms = get_running_vms(request.id)
        hostname = f"id{request.id}-{request.vm_name}"
        for vm in existing_vms:
            if vm['name'] == hostname:
                raise HTTPException(status_code=400, detail=f"Ya existe VM con nombre {hostname}")
        
        # Ejecutar creación
        result = await create_vm_internal(request)
        
        if result['success']:
            return VMResponse(
                success=True,
                message=result['message'],
                details=result['details']
            )
        else:
            raise HTTPException(status_code=400, detail=result['message'])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creando VM: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.post("/pause", response_model=VMResponse)
async def pause_vms_endpoint(request: VMOperationRequest, token: str = Depends(verify_token)):
    """Pausar VMs por ID"""
    try:
        if not 1 <= request.id <= 9999:
            raise HTTPException(status_code=400, detail="ID debe estar entre 1 y 9999")
        
        result = await pause_vms_internal(request.id)
        
        return VMResponse(
            success=result['success'],
            message=result['message'],
            details=result['details']
        )
        
    except Exception as e:
        logger.error(f"Error pausando VMs ID {request.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.post("/resume", response_model=VMResponse)
async def resume_vms_endpoint(request: VMOperationRequest, token: str = Depends(verify_token)):
    """Reanudar VMs por ID"""
    try:
        if not 1 <= request.id <= 9999:
            raise HTTPException(status_code=400, detail="ID debe estar entre 1 y 9999")
        
        result = await resume_vms_internal(request.id)
        
        return VMResponse(
            success=result['success'],
            message=result['message'],
            details=result['details']
        )
        
    except Exception as e:
        logger.error(f"Error reanudando VMs ID {request.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.post("/cleanup", response_model=VMResponse)
async def cleanup_vms_endpoint(request: VMOperationRequest, token: str = Depends(verify_token)):
    """Limpiar completamente VMs por ID"""
    try:
        if not 1 <= request.id <= 9999:
            raise HTTPException(status_code=400, detail="ID debe estar entre 1 y 9999")
        
        result = await cleanup_vms_internal(request.id)
        
        return VMResponse(
            success=result['success'],
            message=result['message'],
            details=result['details']
        )
        
    except Exception as e:
        logger.error(f"Error limpiando VMs ID {request.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.post("/pause-vm", response_model=VMResponse)
async def pause_single_vm_endpoint(request: SingleVMOperationRequest, token: str = Depends(verify_token)):
    """Pausar una VM específica de un slice"""
    try:
        if not 1 <= request.id <= 9999:
            raise HTTPException(status_code=400, detail="ID debe estar entre 1 y 9999")
        
        result = await pause_single_vm_internal(request.id, request.vm_name)
        
        return VMResponse(
            success=result['success'],
            message=result['message'],
            details=result['details']
        )
        
    except Exception as e:
        logger.error(f"Error pausando VM {request.vm_name} del ID {request.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.post("/resume-vm", response_model=VMResponse)
async def resume_single_vm_endpoint(request: SingleVMOperationRequest, token: str = Depends(verify_token)):
    """Reanudar una VM específica de un slice"""
    try:
        if not 1 <= request.id <= 9999:
            raise HTTPException(status_code=400, detail="ID debe estar entre 1 y 9999")
        
        result = await resume_single_vm_internal(request.id, request.vm_name)
        
        return VMResponse(
            success=result['success'],
            message=result['message'],
            details=result['details']
        )
        
    except Exception as e:
        logger.error(f"Error reanudando VM {request.vm_name} del ID {request.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.post("/shutdown-vm", response_model=VMResponse)
async def shutdown_single_vm_endpoint(request: SingleVMOperationRequest, token: str = Depends(verify_token)):
    """Apagar una VM específica de un slice"""
    try:
        if not 1 <= request.id <= 9999:
            raise HTTPException(status_code=400, detail="ID debe estar entre 1 y 9999")
        
        result = await shutdown_single_vm_internal(request.id, request.vm_name)
        
        return VMResponse(
            success=result['success'],
            message=result['message'],
            details=result['details']
        )
        
    except Exception as e:
        logger.error(f"Error apagando VM {request.vm_name} del ID {request.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.post("/start-vm", response_model=VMResponse)
async def start_single_vm_endpoint(request: SingleVMOperationRequest, token: str = Depends(verify_token)):
    """Encender una VM específica de un slice"""
    try:
        if not 1 <= request.id <= 9999:
            raise HTTPException(status_code=400, detail="ID debe estar entre 1 y 9999")
        
        result = await start_single_vm_internal(request.id, request.vm_name)
        
        return VMResponse(
            success=result['success'],
            message=result['message'],
            details=result['details']
        )
        
    except Exception as e:
        logger.error(f"Error encendiendo VM {request.vm_name} del ID {request.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.post("/shutdown", response_model=VMResponse)
async def shutdown_slice_endpoint(request: VMOperationRequest, token: str = Depends(verify_token)):
    """Apagar todas las VMs de un slice"""
    try:
        if not 1 <= request.id <= 9999:
            raise HTTPException(status_code=400, detail="ID debe estar entre 1 y 9999")
        
        result = await shutdown_slice_internal(request.id)
        
        return VMResponse(
            success=result['success'],
            message=result['message'],
            details=result['details']
        )
        
    except Exception as e:
        logger.error(f"Error apagando VMs ID {request.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.post("/start", response_model=VMResponse)
async def start_slice_endpoint(request: VMOperationRequest, token: str = Depends(verify_token)):
    """Encender todas las VMs de un slice"""
    try:
        if not 1 <= request.id <= 9999:
            raise HTTPException(status_code=400, detail="ID debe estar entre 1 y 9999")
        
        result = await start_slice_internal(request.id)
        
        return VMResponse(
            success=result['success'],
            message=result['message'],
            details=result['details']
        )
        
    except Exception as e:
        logger.error(f"Error encendiendo VMs ID {request.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

# =============================================================================
# CONFIGURACIÓN DE ARRANQUE
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=5805,
        workers=1,
        log_level="info"
    )

#!/usr/bin/env python3

import subprocess
import psutil
import asyncio
import os
import hashlib
import time
import shutil
import base64
from typing import List, Tuple, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends, status, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import uvicorn
import logging

# Configuración
SECRET_TOKEN = "clavesihna"
security = HTTPBearer()

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

class StatusRequest(BaseModel):
    id: int = Field(..., ge=1, le=9999, description="ID para verificar estado")

# Modelos Pydantic para responses
class VMInfo(BaseModel):
    name: str
    pid: int
    status: str
    ram_mb: float
    cpu_time: str

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

# Funciones auxiliares
async def run_sudo_command(command: str, timeout: int = 30) -> Tuple[bool, str]:
    """Ejecutar comando con sudo usando contraseña"""
    try:
        cmd = f'echo "alejandro" | sudo -S {command}'
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

def get_process_status(pid: int) -> str:
    """Obtener estado de un proceso"""
    try:
        with open(f'/proc/{pid}/stat', 'r') as f:
            status_code = f.read().split()[2]
        
        status_map = {
            'R': 'CORRIENDO',
            'S': 'DURMIENDO', 
            'T': 'PAUSADO',
            'Z': 'ZOMBIE'
        }
        return status_map.get(status_code, f'DESCONOCIDO({status_code})')
    except:
        return 'DESCONOCIDO'

def get_running_vms(vm_id: int) -> List[Dict[str, Any]]:
    """Obtener VMs corriendo para un ID específico"""
    vm_pattern = f"id{vm_id}-"
    vms = []
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['name'] == 'qemu-system-x86_64':
                cmdline = ' '.join(proc.info['cmdline'] or [])
                if f"-name {vm_pattern}" in cmdline:
                    # Extraer nombre de VM
                    vm_name = "unknown"
                    for part in proc.info['cmdline'] or []:
                        if part.startswith(vm_pattern):
                            vm_name = part
                            break
                    
                    # Obtener información adicional del proceso
                    try:
                        process = psutil.Process(proc.info['pid'])
                        memory_mb = process.memory_info().rss / (1024 * 1024)
                        cpu_time = str(process.cpu_times())
                        status = get_process_status(proc.info['pid'])
                    except:
                        memory_mb = 0
                        cpu_time = "?"
                        status = "DESCONOCIDO"
                    
                    vms.append({
                        'name': vm_name,
                        'pid': proc.info['pid'],
                        'status': status,
                        'ram_mb': memory_mb,
                        'cpu_time': cpu_time
                    })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    
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
                
                # Extraer VLAN del nombre: id{id}-{name}-t{vlan} (siguiendo vm_create.sh)
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
    """Lógica interna para crear VM basada en vm_create.sh"""
    
    lock = await get_id_lock(request.id)
    
    async with lock:
        try:
            # Verificar y construir ruta de imagen
            image_path = request.image
            if not os.path.isabs(request.image):
                image_path = f"/var/lib/virt/images/{request.image}"
            
            if not os.path.exists(image_path):
                return {
                    'success': False,
                    'message': f'Imagen no encontrada: {image_path}',
                    'details': {'error': 'image_not_found'}
                }
            
            # Configuraciones derivadas
            hostname = f"id{request.id}-{request.vm_name}"
            vm_disk_path = f"/var/lib/virt/images/{hostname}.qcow2"
            pid_file = f"/var/run/vm-pids/{hostname}-qemu.pid"
            
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
            
            steps = []
            
            # 1. Crear directorios necesarios
            success, _ = await run_sudo_command("mkdir -p /var/lib/virt/images /var/run/vm-pids")
            if success:
                steps.append("Directorios creados")
            else:
                return {
                    'success': False,
                    'message': 'Error creando directorios',
                    'details': {'error': 'directory_creation_failed'}
                }
            
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
            
            # 5. Construir y ejecutar comando QEMU
            qemu_cmd = build_qemu_command(
                hostname=hostname,
                ram_size=request.ram_size,
                cpu_cores=request.cpu_cores,
                vnc_port=request.vnc_port,
                vm_disk_path=vm_disk_path,
                cloud_init_iso=cloud_init_iso,
                tap_interfaces=tap_interfaces,
                mac_addresses=mac_addresses,
                pid_file=pid_file
            )
            
            success, output = await run_sudo_command(qemu_cmd, timeout=60)
            if success:
                steps.append("VM iniciada con QEMU")
            else:
                # Limpiar todo en caso de error
                await cleanup_failed_creation(request.id, tap_interfaces, request.ovs_name, vm_disk_path, cloud_init_iso)
                return {
                    'success': False,
                    'message': f'Error iniciando QEMU: {output}',
                    'details': {'error': 'qemu_start_failed'}
                }
            
            # 6. Verificar que la VM está corriendo
            await asyncio.sleep(3)
            
            # Buscar el proceso
            vm_pid = None
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'] == 'qemu-system-x86_64':
                        cmdline = ' '.join(proc.info['cmdline'] or [])
                        if f"-name {hostname}" in cmdline:
                            vm_pid = proc.info['pid']
                            break
                except:
                    continue
            
            if not vm_pid:
                await cleanup_failed_creation(request.id, tap_interfaces, request.ovs_name, vm_disk_path, cloud_init_iso)
                return {
                    'success': False,
                    'message': 'VM creada pero no se pudo verificar',
                    'details': {'error': 'vm_verification_failed'}
                }
            
            # Resultado exitoso
            return {
                'success': True,
                'message': f'VM {hostname} creada exitosamente',
                'details': {
                    'hostname': hostname,
                    'pid': vm_pid,
                    'vnc_port': f"59{request.vnc_port:02d}",
                    'vlans': vlans,
                    'tap_interfaces': len(tap_interfaces),
                    'steps': steps
                }
            }
            
        except Exception as e:
            logger.error(f"Error interno creando VM: {str(e)}")
            return {
                'success': False,
                'message': f'Error interno: {str(e)}',
                'details': {'error': 'internal_error'}
            }

async def pause_vms_internal(vm_id: int) -> Dict[str, Any]:
    """Lógica interna para pausar VMs basada en pause_by_id.sh"""
    
    lock = await get_id_lock(vm_id)
    
    async with lock:
        try:
            vms = get_running_vms(vm_id)
            
            if not vms:
                return {
                    'success': False,
                    'message': f'No se encontraron VMs para ID {vm_id}',
                    'details': {'paused_count': 0, 'error_count': 0}
                }
            
            # Filtrar VMs que están corriendo (no pausadas)
            running_vms = [vm for vm in vms if vm['status'] != 'PAUSADO']
            
            if not running_vms:
                return {
                    'success': True,
                    'message': f'Todas las VMs del ID {vm_id} ya están pausadas',
                    'details': {'paused_count': 0, 'already_paused': len(vms)}
                }
            
            # Pausar cada VM
            paused_count = 0
            error_count = 0
            paused_vms = []
            
            for vm in running_vms:
                success, _ = await run_sudo_command(f"kill -STOP {vm['pid']}")
                if success:
                    # Verificar que se pausó
                    await asyncio.sleep(1)
                    if get_process_status(vm['pid']) == 'PAUSADO':
                        paused_count += 1
                        paused_vms.append(vm['name'])
                    else:
                        error_count += 1
                else:
                    error_count += 1
            
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
    """Lógica interna para reanudar VMs basada en resume_by_id.sh"""
    
    lock = await get_id_lock(vm_id)
    
    async with lock:
        try:
            vms = get_running_vms(vm_id)
            
            if not vms:
                return {
                    'success': False,
                    'message': f'No se encontraron VMs para ID {vm_id}',
                    'details': {'resumed_count': 0, 'error_count': 0}
                }
            
            # Filtrar VMs que están pausadas
            paused_vms = [vm for vm in vms if vm['status'] == 'PAUSADO']
            
            if not paused_vms:
                running_count = len([vm for vm in vms if vm['status'] in ['CORRIENDO', 'DURMIENDO']])
                return {
                    'success': True,
                    'message': f'Todas las VMs del ID {vm_id} ya están corriendo',
                    'details': {'resumed_count': 0, 'already_running': running_count}
                }
            
            # Reanudar cada VM pausada
            resumed_count = 0
            error_count = 0
            resumed_vms = []
            
            for vm in paused_vms:
                success, _ = await run_sudo_command(f"kill -CONT {vm['pid']}")
                if success:
                    # Verificar que se reanudó
                    await asyncio.sleep(1)
                    status = get_process_status(vm['pid'])
                    if status in ['CORRIENDO', 'DURMIENDO']:
                        resumed_count += 1
                        resumed_vms.append(vm['name'])
                    else:
                        error_count += 1
                else:
                    error_count += 1
            
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
    """Lógica interna para limpiar VMs basada en cleanup_by_id.sh"""
    
    lock = await get_id_lock(vm_id)
    
    async with lock:
        try:
            vm_pattern = f"id{vm_id}-"
            steps = []
            errors = []
            
            # 1. Detener procesos QEMU
            vms = get_running_vms(vm_id)
            if vms:
                steps.append(f"Deteniendo {len(vms)} VMs")
                for vm in vms:
                    # Intentar cierre graceful
                    success, _ = await run_sudo_command(f"kill -TERM {vm['pid']}")
                    if success:
                        await asyncio.sleep(2)
                        
                        # Verificar si aún existe y forzar si es necesario
                        try:
                            proc = psutil.Process(vm['pid'])
                            if proc.is_running():
                                success, _ = await run_sudo_command(f"kill -KILL {vm['pid']}")
                                if not success:
                                    errors.append(f"Error cerrando VM {vm['name']}")
                        except psutil.NoSuchProcess:
                            pass  # Ya terminó
                    else:
                        errors.append(f"Error deteniendo VM {vm['name']}")
            else:
                steps.append("No hay VMs corriendo")
            
            # 2. Eliminar archivos PID
            success, _ = await run_sudo_command(f"rm -f /var/run/vm-pids/{vm_pattern}*-qemu.pid")
            if success:
                steps.append("Archivos PID eliminados")
            else:
                errors.append("Error eliminando archivos PID")
            
            # 3. Eliminar interfaces TAP
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
            
            # 4. Eliminar imágenes de disco
            success, _ = await run_sudo_command(f"rm -f /var/lib/virt/images/{vm_pattern}*.qcow2")
            if success:
                steps.append("Imágenes de disco eliminadas")
            else:
                errors.append("Error eliminando imágenes de disco")
            
            # 5. Eliminar ISOs cloud-init
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

# =============================================================================
# FUNCIONES AUXILIARES PARA CREAR VMS
# =============================================================================

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
    """Crear contenido user-data según tipo de OS"""
    
    base_config = f"""#cloud-config
hostname: {hostname}
manage_etc_hosts: true
"""
    
    # Comandos para configurar interfaces
    runcmd_config = ""
    for i, vlan in enumerate(vlans):
        if os_type == "cirros":
            runcmd_config += f"  - sudo /sbin/cirros-dhcpc up eth{i}\n"
        elif os_type == "alpine":
            runcmd_config += f"  - ip link set eth{i} up\n"
            runcmd_config += f"  - udhcpc -i eth{i} -b -p /var/run/udhcpc.eth{i}.pid\n"
        else:  # ubuntu o generic
            runcmd_config += f"  - ip link set eth{i} up\n"
            runcmd_config += f"  - dhclient -r eth{i} || true\n"
            runcmd_config += f"  - dhclient eth{i} || udhcpc -i eth{i} &\n"
    
    # Configuración específica por OS
    user_config = ""
    if os_type == "ubuntu":
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

packages:
  - sudo
  - openssh
  - dhcpcd

package_update: true
"""
    
    # Comandos finales
    final_commands = f"""
runcmd:
  - echo "VM {hostname} iniciada correctamente"
  - sleep 5
{runcmd_config}  - sleep 3
  - echo "Configuración completada" > /tmp/cloud-init-done
"""
    
    if os_type == "alpine":
        final_commands += """  - rc-update add sshd default
  - rc-service sshd start
"""
    
    return base_config + user_config + final_commands

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

def build_qemu_command(hostname: str, ram_size: str, cpu_cores: int, vnc_port: int, 
                      vm_disk_path: str, cloud_init_iso: str, tap_interfaces: List[str], 
                      mac_addresses: List[str], pid_file: str) -> str:
    """Construir comando QEMU completo"""
    
    qemu_cmd = f"""qemu-system-x86_64 \\
    -enable-kvm \\
    -m {ram_size} \\
    -smp {cpu_cores} \\
    -name {hostname} \\
    -vnc 0.0.0.0:{vnc_port}"""
    
    # Agregar interfaces de red
    for i, (tap_name, mac_addr) in enumerate(zip(tap_interfaces, mac_addresses)):
        qemu_cmd += f""" \\
    -netdev tap,id=net{i},ifname={tap_name},script=no,downscript=no \\
    -device e1000,netdev=net{i},mac={mac_addr}"""
    
    # Agregar discos y configuración final
    qemu_cmd += f""" \\
    -drive file={vm_disk_path},format=qcow2,if=virtio \\
    -drive file={cloud_init_iso},format=raw,if=virtio \\
    -boot c \\
    -daemonize \\
    -pidfile {pid_file}"""
    
    return qemu_cmd

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
        running_count = len([vm for vm in vms if vm['status'] in ['CORRIENDO', 'DURMIENDO']])
        paused_count = len([vm for vm in vms if vm['status'] == 'PAUSADO'])
        
        # Convertir a modelos Pydantic
        vm_infos = [
            VMInfo(
                name=vm['name'],
                pid=vm['pid'],
                status=vm['status'],
                ram_mb=vm['ram_mb'],
                cpu_time=vm['cpu_time']
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

# =============================================================================
# CONFIGURACIÓN DE ARRANQUE
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=5805,
        workers=1,  # Para operaciones con sudo, mejor usar 1 worker
        log_level="info"
    )

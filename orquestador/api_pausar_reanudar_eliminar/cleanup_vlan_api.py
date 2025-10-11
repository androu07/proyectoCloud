#!/usr/bin/env python3

import subprocess
import psutil
import asyncio
import os
import signal
from typing import List, Tuple, Optional
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import uvicorn

# Configuración
SECRET_TOKEN = "clavesihna"
security = HTTPBearer()

# Control de concurrencia
operation_lock = asyncio.Lock()

# Lock para operaciones de limpieza por VLAN (evitar concurrencia)
vlan_locks = {}

app = FastAPI(
    title="CLEANUP VLAN API",
    description="API para limpiar configuraciones de VLAN (DHCP, namespaces, OVS)",
    version="1.0.0",
    docs_url=None,
    redoc_url=None
)

# Modelos
class CleanupRequest(BaseModel):
    vlan_id: int = Field(..., ge=1, le=4094, description="ID de VLAN a limpiar")
    ovs_bridge: Optional[str] = Field(None, description="Bridge OVS específico (opcional)")

class CleanupResponse(BaseModel):
    success: bool
    message: str

class VlanResource(BaseModel):
    name: str
    type: str
    status: str

class StatusResponse(BaseModel):
    vlan_id: int
    exists: bool
    resources: List[VlanResource] = []
    total_count: int = 0

# Autenticación
async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    if credentials.credentials != SECRET_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

# Funciones utilitarias
async def get_vlan_lock(vlan_id: int) -> asyncio.Lock:
    """Obtener lock específico para una VLAN"""
    if vlan_id not in vlan_locks:
        vlan_locks[vlan_id] = asyncio.Lock()
    return vlan_locks[vlan_id]

async def run_sudo_command(command: str, timeout: int = 30) -> Tuple[bool, str]:
    """Ejecutar comando con sudo usando la contraseña"""
    try:
        cmd = f'echo "alejandro" | sudo -S {command}'
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "Timeout ejecutando comando"
    except Exception as e:
        return False, f"Error ejecutando comando: {str(e)}"

def vlan_exists(vlan_id: int) -> bool:
    """Verificar si existe algún recurso de la VLAN"""
    namespace = f"id{vlan_id}-dhcp"
    dnsmasq_pid_file = f"/var/run/dhcp/id{vlan_id}-dnsmasq.pid"
    
    try:
        # Verificar namespace
        result = subprocess.run(
            'echo "alejandro" | sudo -S ip netns list',
            shell=True, capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and namespace in result.stdout:
            return True
        
        # Verificar proceso dnsmasq
        if os.path.exists(dnsmasq_pid_file):
            return True
        
        # Verificar interfaces
        result = subprocess.run(
            'echo "alejandro" | sudo -S ip link show',
            shell=True, capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for iface in [f"id{vlan_id}-nsvt", f"id{vlan_id}-ovsvt", f"id{vlan_id}-gw"]:
                if iface in result.stdout:
                    return True
    except:
        pass
    
    return False

def get_vlan_resources(vlan_id: int) -> list:
    """Obtener lista de recursos para una VLAN específica"""
    resources = []
    namespace = f"id{vlan_id}-dhcp"
    veth_ns = f"id{vlan_id}-nsvt"
    veth_ovs = f"id{vlan_id}-ovsvt"
    ovs_internal = f"id{vlan_id}-gw"
    dnsmasq_pid_file = f"/var/run/dhcp/id{vlan_id}-dnsmasq.pid"
    
    try:
        # Verificar namespace
        result = subprocess.run(
            'echo "alejandro" | sudo -S ip netns list',
            shell=True, capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and namespace in result.stdout:
            resources.append({
                'name': namespace,
                'type': 'namespace',
                'status': 'active'
            })
        
        # Verificar interfaces
        result = subprocess.run(
            'echo "alejandro" | sudo -S ip link show',
            shell=True, capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for iface in [veth_ns, veth_ovs, ovs_internal]:
                if iface in result.stdout:
                    resources.append({
                        'name': iface,
                        'type': 'interface',
                        'status': 'active'
                    })
        
        # Verificar proceso dnsmasq
        if os.path.exists(dnsmasq_pid_file):
            try:
                with open(dnsmasq_pid_file, 'r') as f:
                    pid = int(f.read().strip())
                    try:
                        proc = psutil.Process(pid)
                        status = 'running' if proc.is_running() else 'stopped'
                        resources.append({
                            'name': f'dnsmasq-{vlan_id}',
                            'type': 'process',
                            'status': status
                        })
                    except psutil.NoSuchProcess:
                        resources.append({
                            'name': f'dnsmasq-{vlan_id}',
                            'type': 'process',
                            'status': 'dead'
                        })
            except:
                pass
    
    except Exception:
        pass
    
    return resources

async def cleanup_vlan_internal(vlan_id: int, ovs_bridge: Optional[str] = None) -> dict:
    """Lógica interna para limpiar VLAN con control de concurrencia"""
    
    # Obtener lock para esta VLAN
    lock = await get_vlan_lock(vlan_id)
    
    async with lock:
        namespace = f"id{vlan_id}-dhcp"
        veth_ns = f"id{vlan_id}-nsvt"
        veth_ovs = f"id{vlan_id}-ovsvt"
        ovs_internal = f"id{vlan_id}-gw"
        dnsmasq_pid_file = f"/var/run/dhcp/id{vlan_id}-dnsmasq.pid"
        dnsmasq_lease_file = f"/var/lib/dhcp/id{vlan_id}-dnsmasq.leases"
        
        # 1. Detener servidor DHCP
        if os.path.exists(dnsmasq_pid_file):
            try:
                with open(dnsmasq_pid_file, 'r') as f:
                    dnsmasq_pid = int(f.read().strip())
                
                try:
                    proc = psutil.Process(dnsmasq_pid)
                    if proc.is_running():
                        # Terminar gracefully
                        proc.terminate()
                        await asyncio.sleep(2)
                        
                        # Verificar si aún está corriendo
                        if proc.is_running():
                            proc.kill()
                            await asyncio.sleep(1)
                except psutil.NoSuchProcess:
                    pass
                
                # Eliminar archivo PID
                os.remove(dnsmasq_pid_file)
                
            except Exception:
                pass
        
        # 2. Eliminar namespace
        success, output = await run_sudo_command(f"ip netns list | grep -q {namespace}")
        if success:
            # Matar procesos en el namespace
            success_pids, pids_output = await run_sudo_command(f"ip netns pids {namespace}")
            if success_pids and pids_output.strip():
                for pid in pids_output.strip().split('\n'):
                    if pid.strip():
                        await run_sudo_command(f"kill -9 {pid.strip()}")
            
            # Eliminar namespace
            await run_sudo_command(f"ip netns del {namespace}")
        
        # 3. Eliminar puertos del bridge OVS
        if ovs_bridge:
            # Bridge específico
            success, output = await run_sudo_command(f"ovs-vsctl br-exists {ovs_bridge}")
            if success:
                # Eliminar puertos
                await run_sudo_command(f"ovs-vsctl --if-exists del-port {ovs_bridge} {veth_ovs}")
                await run_sudo_command(f"ovs-vsctl --if-exists del-port {ovs_bridge} {ovs_internal}")
        else:
            # Buscar en todos los bridges
            success, bridges_output = await run_sudo_command("ovs-vsctl list-br")
            if success and bridges_output.strip():
                for bridge in bridges_output.strip().split('\n'):
                    if bridge.strip():
                        await run_sudo_command(f"ovs-vsctl --if-exists del-port {bridge.strip()} {veth_ovs}")
                        await run_sudo_command(f"ovs-vsctl --if-exists del-port {bridge.strip()} {ovs_internal}")
        
        # 4. Limpiar interfaces restantes
        # Limpiar IPs de interfaz interna
        success, output = await run_sudo_command(f"ip addr show {ovs_internal}")
        if success and "inet " in output:
            await run_sudo_command(f"ip addr flush dev {ovs_internal}")
        
        # Eliminar interfaces
        for iface in [veth_ovs, ovs_internal]:
            success, output = await run_sudo_command(f"ip link show {iface}")
            if success:
                await run_sudo_command(f"ip link del {iface}")
        
        # 5. Eliminar archivos de configuración
        files_to_remove = [
            dnsmasq_lease_file,
            f"/var/run/dhcp/id{vlan_id}*",
            f"/var/lib/dhcp/id{vlan_id}*"
        ]
        
        for file_pattern in files_to_remove:
            await run_sudo_command(f"rm -f {file_pattern}")
        
        # Verificación final
        remaining = get_vlan_resources(vlan_id)
        
        # Determinar éxito
        success_overall = len(remaining) == 0
        
        if success_overall:
            message = f"VLAN {vlan_id} limpiada completamente"
        else:
            message = f"VLAN {vlan_id} limpiada parcialmente - {len(remaining)} recursos restantes"
        
        return {
            'success': success_overall,
            'message': message
        }

# Endpoints
@app.get("/health")
async def health_check():
    try:
        return {"status": "ok"}
    except:
        return {"status": "error"}

@app.get("/status/{vlan_id}", response_model=StatusResponse)
async def get_vlan_status(vlan_id: int, token: str = Depends(verify_token)):
    try:
        if not 1 <= vlan_id <= 4094:
            raise HTTPException(status_code=400, detail="VLAN ID debe estar entre 1 y 4094")
        
        # Obtener información detallada de recursos
        resources_data = get_vlan_resources(vlan_id)
        exists = len(resources_data) > 0
        
        # Convertir a modelos Pydantic
        resources = [
            VlanResource(
                name=resource['name'],
                type=resource['type'],
                status=resource['status']
            )
            for resource in resources_data
        ]
        
        return StatusResponse(
            vlan_id=vlan_id,
            exists=exists,
            resources=resources,
            total_count=len(resources)
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Error verificando VLAN")

@app.post("/cleanup", response_model=CleanupResponse)
async def cleanup_vlan_endpoint(request: CleanupRequest, token: str = Depends(verify_token)):
    try:
        if not 1 <= request.vlan_id <= 4094:
            raise HTTPException(status_code=400, detail="VLAN ID debe estar entre 1 y 4094")
        
        # Ejecutar limpieza con control de concurrencia
        result = await cleanup_vlan_internal(request.vlan_id, request.ovs_bridge)
        
        return CleanupResponse(
            success=result['success'],
            message=result['message']
        )
        
    except Exception as e:
        return CleanupResponse(success=False, message=f"Error interno: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5803)
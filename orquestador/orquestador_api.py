#!/usr/bin/env python3
"""
API del Orquestador - Procesa JSONs de topología y genera configuraciones completas
Puerto: 5806 (local, no en contenedor)
"""

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Dict, Any, List, Tuple
import jwt
import json
import tempfile
import os
from datetime import datetime
import sys
import traceback
import asyncio

# Importar el procesador de topologías
sys.path.append('/home/ubuntu/red_contenedores/orquestador/backupp')
from calculo import TopologyVLANAssigner
import requests
import asyncio
import subprocess

app = FastAPI(
    title="API del Orquestador", 
    version="1.0.0",
    description="Procesa configuraciones de topología y genera JSONs completos para despliegue"
)

# Configuración JWT (debe ser la misma que auth_api)
JWT_SECRET_KEY = "mi_clave_secreta_super_segura_12345"
JWT_ALGORITHM = "HS256"

# Configuración de workers
WORKERS_CONFIG = {
    'worker1': '10.0.10.2',
    'worker2': '10.0.10.3', 
    'worker3': '10.0.10.4'
}
WORKER_API_PORT = 5805
CPRE_VLAN_API_TOKEN = "clavesihna"
SUDO_PASSWORD = "alejandro"

security = HTTPBearer()

class TopologyRequest(BaseModel):
    """Modelo para la solicitud de creación de topología"""
    json_config: Dict[Any, Any]

class TopologyResponse(BaseModel):
    """Modelo para la respuesta de creación de topología"""
    success: bool
    message: str
    result: Dict[Any, Any] = None
    error: str = None

class DeployRequest(BaseModel):
    """Modelo para la solicitud de despliegue completo"""
    json_config: Dict[Any, Any]

class DeployResponse(BaseModel):
    """Modelo para la respuesta de despliegue completo"""
    success: bool
    message: str
    deployment_details: Dict[str, Any] = None
    error: str = None

def verify_jwt_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Verifica el token JWT del auth_api
    """
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        
        # Verificar que el token no haya expirado
        exp = payload.get("exp")
        if exp and datetime.utcnow().timestamp() > exp:
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

# =============================================================================
# FUNCIONES AUXILIARES PARA DESPLIEGUE
# =============================================================================

async def run_sudo_command(command: str, timeout: int = 30) -> tuple[bool, str]:
    """Ejecutar comando con sudo usando contraseña"""
    try:
        cmd = f'echo "{SUDO_PASSWORD}" | sudo -S {command}'
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

def calculate_subnet(vlan: int) -> str:
    """Calcular subnet basado en VLAN (lógica de net_create.sh)"""
    if vlan <= 255:
        return f"10.1.{vlan}"
    else:
        second_octet = ((vlan - 1) // 255) + 1
        third_octet = ((vlan - 1) % 255) + 1
        return f"10.{second_octet}.{third_octet}"

async def create_dhcp_namespaces(slice_id: str, vlans_usadas: str, ovs_bridge: str = "br-cloud") -> dict:
    """
    Crear namespaces DHCP usando net_create.sh con el rango completo de VLANs
    """
    try:
        print(f"\n🌐 Creando namespaces DHCP para slice {slice_id}")
        print(f"VLANs: {vlans_usadas}, Bridge: {ovs_bridge}")
        
        # Parsear el rango de VLANs
        start_vlan, end_vlan = map(int, vlans_usadas.split(';'))
        
        print(f"   🚀 Ejecutando net_create.sh para rango completo {vlans_usadas}...")
        
        # Comando net_create.sh con el rango completo en background - escapar el punto y coma
        net_create_cmd = f"/home/ubuntu/red_contenedores/orquestador/backupp/net_create.sh {slice_id} '{vlans_usadas}' {ovs_bridge} &"
        
        success, output = await run_sudo_command(net_create_cmd)
        
        print(f"   📋 Salida del comando: {output}")
        
        # Crear lista de VLANs esperadas
        created_vlans = []
        for vlan_id in range(start_vlan, end_vlan + 1):
            # Calcular subnet para registro
            subnet = calculate_subnet(vlan_id)
            
            created_vlans.append({
                'vlan_id': vlan_id,
                'namespace': f"id{slice_id}-ns{vlan_id}",
                'subnet': f"{subnet}.0/24",
                'gateway': f"{subnet}.1",
                'dhcp_range': f"{subnet}.10-{subnet}.22"
            })
        
        print(f"   ✅ net_create.sh ejecutado para {len(created_vlans)} VLANs")
        
        # Pausa más larga para que el script complete su trabajo
        print(f"   ⏳ Esperando que net_create.sh complete el setup...")
        await asyncio.sleep(5)
        
        return {
            'success': True,
            'message': f'Namespaces DHCP iniciados con net_create.sh: {len(created_vlans)} VLANs',
            'created_vlans': created_vlans,
            'partial_success': False,
            'command_output': output
        }
            
    except Exception as e:
        return {
            'success': False,
            'message': f'Error ejecutando net_create.sh: {str(e)}',
            'error': 'internal_error'
        }

async def cleanup_workers(slice_id: str) -> dict:
    """
    Limpieza en todos los workers usando la API de cleanup
    """
    cleanup_results = {
        'successful_workers': [],
        'failed_workers': []
    }
    
    for worker_name, worker_ip in WORKERS_CONFIG.items():
        try:
            print(f"   🧹 Limpiando worker {worker_name} ({worker_ip})...")
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {CPRE_VLAN_API_TOKEN}"
            }
            
            payload = {"id": int(slice_id)}
            url = f"http://{worker_ip}:{WORKER_API_PORT}/cleanup"
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                cleanup_results['successful_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'response': response.json()
                })
                print(f"   ✅ Worker {worker_name} limpiado exitosamente")
            else:
                cleanup_results['failed_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'error': f"HTTP {response.status_code}: {response.text}"
                })
                print(f"   ❌ Error limpiando worker {worker_name}: {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            cleanup_results['failed_workers'].append({
                'worker': worker_name,
                'ip': worker_ip,
                'error': f"Connection error: {str(e)}"
            })
            print(f"   ❌ Error conexión worker {worker_name}: {str(e)}")
    
    return cleanup_results

async def verify_deployment_and_cleanup_on_error(slice_id: str, expected_vlans: list) -> dict:
    """
    Verificación final simplificada del despliegue y cleanup automático en caso de errores
    """
    try:
        print(f"\n🔍 VERIFICACIÓN FINAL del slice {slice_id}")
        
        verification_results = {
            'namespaces': [],
            'dnsmasq_processes': [],
            'ovs_ports': []
        }
        
        # Listar namespaces
        print("📋 Listando namespaces...")
        success, output = await run_sudo_command("ip netns list")
        if success:
            all_namespaces = output.strip().split('\n') if output.strip() else []
            slice_namespaces = [ns for ns in all_namespaces if f"id{slice_id}-ns" in ns]
            verification_results['namespaces'] = slice_namespaces
            print(f"   Namespaces encontrados: {slice_namespaces}")
        
        # Listar procesos dnsmasq
        print("📋 Listando procesos dnsmasq...")
        success, output = await run_sudo_command(f'ps aux | grep dnsmasq | grep "id{slice_id}-" | grep -v grep')
        if success and output.strip():
            processes = output.strip().split('\n')
            verification_results['dnsmasq_processes'] = [p.split()[1] for p in processes]
            print(f"   Procesos dnsmasq encontrados: {verification_results['dnsmasq_processes']}")
        
        # Listar puertos OVS
        print("📋 Listando puertos OVS...")
        success, output = await run_sudo_command(f'ovs-vsctl list-ports br-cloud | grep "^id{slice_id}-"')
        if success and output.strip():
            verification_results['ovs_ports'] = output.strip().split('\n')
            print(f"   Puertos OVS encontrados: {verification_results['ovs_ports']}")
        
        # Verificar si tenemos al menos los componentes básicos
        expected_namespaces = len(expected_vlans)
        found_namespaces = len(verification_results['namespaces'])
        found_processes = len(verification_results['dnsmasq_processes'])
        found_ports = len(verification_results['ovs_ports'])
        
        # Criterio simplificado: al menos debe haber namespaces DHCP
        deployment_success = found_namespaces >= expected_namespaces
        
        print(f"\n📊 Resumen verificación:")
        print(f"   • Namespaces: {found_namespaces}/{expected_namespaces}")
        print(f"   • Procesos dnsmasq: {found_processes}")
        print(f"   • Puertos OVS: {found_ports}")
        
        if deployment_success:
            print(f"✅ Verificación exitosa - Infraestructura DHCP operativa")
            
            return {
                'success': True,
                'message': 'Despliegue verificado exitosamente',
                'details': verification_results
            }
        else:
            print(f"❌ Verificación falló - Infraestructura DHCP incompleta")
            
            # CLEANUP AUTOMÁTICO LOCAL Y EN WORKERS
            print(f"🧹 Ejecutando cleanup automático para slice {slice_id}")
            
            # Cleanup local
            cleanup_cmd = f"/home/ubuntu/red_contenedores/orquestador/backupp/cleanup_slice.sh {slice_id}"
            cleanup_success, cleanup_output = await run_sudo_command(cleanup_cmd)
            
            # Cleanup en workers
            print(f"🧹 Ejecutando cleanup en workers...")
            worker_cleanup = await cleanup_workers(slice_id)
            
            return {
                'success': False,
                'message': f'Error en verificación: infraestructura DHCP incompleta. Cleanup ejecutado.',
                'details': verification_results,
                'cleanup_executed': True,
                'local_cleanup_success': cleanup_success,
                'local_cleanup_output': cleanup_output,
                'worker_cleanup': worker_cleanup
            }
            
    except Exception as e:
        return {
            'success': False,
            'message': f'Error en verificación final: {str(e)}',
            'error': 'verification_error'
        }

async def deploy_vm_to_worker(worker_ip: str, vm_config: dict, slice_id: str) -> dict:
    """
    Desplegar una VM en un worker específico usando cpre_vlan_api
    """
    try:
        # Preparar payload para la API del worker
        payload = {
            "id": int(slice_id),
            "vm_name": vm_config["nombre"],
            "ovs_name": "br-cloud",
            "cpu_cores": int(vm_config["cores"]),
            "ram_size": vm_config["ram"],
            "storage_size": vm_config["almacenamiento"],
            "vnc_port": int(vm_config["puerto_vnc"]),
            "image": vm_config["image"],
            "vlans": vm_config["conexiones_vlans"]
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CPRE_VLAN_API_TOKEN}"
        }
        
        # Hacer petición a la API del worker
        url = f"http://{worker_ip}:{WORKER_API_PORT}/create"
        
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            return {
                'success': True,
                'message': f'VM {vm_config["nombre"]} desplegada exitosamente en {vm_config["server"]}',
                'worker_response': result
            }
        else:
            return {
                'success': False,
                'message': f'Error desplegando VM {vm_config["nombre"]}: {response.text}',
                'status_code': response.status_code
            }
            
    except requests.exceptions.Timeout:
        return {
            'success': False,
            'message': f'Timeout desplegando VM {vm_config["nombre"]} en {vm_config["server"]}',
            'error': 'timeout'
        }
    except Exception as e:
        return {
            'success': False,
            'message': f'Error interno desplegando VM {vm_config["nombre"]}: {str(e)}',
            'error': 'internal_error'
        }

async def deploy_all_vms(processed_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Desplegar todas las VMs del slice procesado en sus workers correspondientes
    """
    try:
        slice_id = processed_config["id_slice"]
        print(f"\n🚀 Desplegando VMs para slice {slice_id}")
        
        deployed_vms = []
        failed_vms = []
        
        # Iterar por todas las topologías
        for topology in processed_config["topologias"]:
            print(f"\n📐 Desplegando topología: {topology['nombre']}")
            
            # Iterar por todas las VMs de la topología
            for vm in topology["vms"]:
                vm_name = vm["nombre"]
                worker_name = vm["server"]
                
                print(f"   Desplegando {vm_name} en {worker_name}...")
                
                # Verificar que el worker existe
                if worker_name not in WORKERS_CONFIG:
                    failed_vms.append({
                        'vm_name': vm_name,
                        'worker': worker_name,
                        'error': f'Worker {worker_name} no configurado'
                    })
                    continue
                
                worker_ip = WORKERS_CONFIG[worker_name]
                
                # Desplegar VM
                result = await deploy_vm_to_worker(worker_ip, vm, slice_id)
                
                if result['success']:
                    deployed_vms.append({
                        'vm_name': vm_name,
                        'worker': worker_name,
                        'worker_ip': worker_ip,
                        'vnc_port': f"59{int(vm['puerto_vnc']):02d}",
                        'vlans': vm['conexiones_vlans']
                    })
                    print(f"   ✅ {vm_name} desplegada exitosamente")
                else:
                    failed_vms.append({
                        'vm_name': vm_name,
                        'worker': worker_name,
                        'worker_ip': worker_ip,
                        'error': result['message']
                    })
                    print(f"   ❌ Error desplegando {vm_name}: {result['message']}")
        
        return {
            'success': len(failed_vms) == 0,
            'message': f'Despliegue VMs: {len(deployed_vms)} exitosas, {len(failed_vms)} fallidas',
            'deployed_vms': deployed_vms,
            'failed_vms': failed_vms,
            'total_vms': len(deployed_vms) + len(failed_vms)
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'Error interno desplegando VMs: {str(e)}',
            'error': 'internal_error'
        }

@app.get("/")
async def root():
    """Endpoint de prueba"""
    return {
        "service": "Orquestador API",
        "version": "1.0.0",
        "status": "running",
        "port": 5807,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health_check():
    """Endpoint de health check"""
    return {
        "status": "healthy",
        "service": "orquestador_api",
        "timestamp": datetime.now().isoformat()
    }

@app.post("/crear-topologia", response_model=TopologyResponse)
async def crear_topologia(
    request: TopologyRequest
    # user_info: dict = Depends(verify_jwt_token)  # Comentado temporalmente para pruebas
):
    """
    Endpoint principal: procesa el JSON de topología y retorna la configuración completa
    
    Parámetros:
    - Authorization: Bearer <JWT_TOKEN> (header)
    - json_config: Configuración de topología con formato ejemplo_despliegue.json
    
    Retorna:
    - JSON completo con VLANs, VNC, servers asignados
    """
    try:
        print(f"\n🚀 Nueva solicitud de creación de topología")
        print(f"👤 Usuario: TEST (auth disabled)")
        print(f"📝 Slice ID: {request.json_config.get('id_slice', 'N/A')}")
        
        # Validar estructura básica del JSON
        required_fields = ['id_slice', 'topologias']
        for field in required_fields:
            if field not in request.json_config:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Campo requerido faltante: {field}"
                )
        
        # Crear archivos temporales para el procesamiento
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_input:
            json.dump(request.json_config, temp_input, indent=4, ensure_ascii=False)
            temp_input_path = temp_input.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_output:
            temp_output_path = temp_output.name
        
        try:
            # Procesar con calculo.py
            print(f"🔄 Procesando configuración...")
            assigner = TopologyVLANAssigner()
            assigner.fill_json(temp_input_path, temp_output_path)
            
            # Leer resultado
            with open(temp_output_path, 'r', encoding='utf-8') as f:
                result_config = json.load(f)
            
            print(f"✅ Procesamiento completado exitosamente")
            print(f"📊 Resultado: {len(result_config.get('topologias', []))} topologías, "
                  f"{result_config.get('cantidad_vms', 'N/A')} VMs")
            
            return TopologyResponse(
                success=True,
                message="Topología procesada exitosamente",
                result=result_config
            )
            
        finally:
            # Limpiar archivos temporales
            try:
                os.unlink(temp_input_path)
                os.unlink(temp_output_path)
            except:
                pass
                
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error en procesamiento: {str(e)}")
        traceback.print_exc()
        
        return TopologyResponse(
            success=False,
            message="Error interno del servidor",
            error=str(e)
        )

@app.get("/test-auth")
async def test_auth(user_info: dict = Depends(verify_jwt_token)):
    """
    Endpoint de prueba para verificar autenticación JWT
    """
    return {
        "message": "Token válido",
        "user_info": user_info,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/desplegar-slice", response_model=DeployResponse)
async def desplegar_slice(
    request: DeployRequest
    # user_info: dict = Depends(verify_jwt_token)  # Comentado temporalmente para pruebas
):
    """
    Endpoint completo: procesa el JSON, crea namespaces DHCP y despliega VMs
    
    Flujo:
    1. Procesa el JSON de configuración (calcula VLANs, VNC, servers)
    2. Crea namespaces DHCP con net_create.sh lógica
    3. Despliega VMs en workers usando cpre_vlan_api
    
    Parámetros:
    - Authorization: Bearer <JWT_TOKEN> (header)
    - json_config: Configuración de topología con formato ejemplo_despliegue.json
    
    Retorna:
    - Detalles completos del despliegue
    """
    try:
        print(f"\n🎯 INICIANDO DESPLIEGUE COMPLETO DE SLICE")
        # print(f"👤 Usuario: {user_info.get('correo', 'Desconocido')}")
        print(f"📝 Slice ID: {request.json_config.get('id_slice', 'N/A')}")
        
        deployment_details = {
            'slice_id': request.json_config.get('id_slice'),
            'steps': [],
            'timing': {}
        }
        start_time = datetime.now()
        
        # PASO 1: Procesar configuración de topología
        print(f"\n📋 PASO 1: Procesando configuración de topología...")
        step_start = datetime.now()
        
        # Validar estructura básica del JSON
        required_fields = ['id_slice', 'topologias']
        for field in required_fields:
            if field not in request.json_config:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Campo requerido faltante: {field}"
                )
        
        # Crear archivos temporales para el procesamiento
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_input:
            json.dump(request.json_config, temp_input, indent=4, ensure_ascii=False)
            temp_input_path = temp_input.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_output:
            temp_output_path = temp_output.name
        
        try:
            # Procesar con calculo.py
            assigner = TopologyVLANAssigner()
            assigner.fill_json(temp_input_path, temp_output_path)
            
            # Leer resultado
            with open(temp_output_path, 'r', encoding='utf-8') as f:
                processed_config = json.load(f)
            
            step_time = (datetime.now() - step_start).total_seconds()
            deployment_details['timing']['topology_processing'] = step_time
            deployment_details['steps'].append({
                'step': 1,
                'name': 'Procesamiento de topología',
                'status': 'SUCCESS',
                'time_seconds': step_time,
                'details': {
                    'total_topologies': len(processed_config.get('topologias', [])),
                    'total_vms': processed_config.get('cantidad_vms'),
                    'vlans_used': processed_config.get('vlans_usadas')
                }
            })
            
            print(f"✅ Topología procesada exitosamente ({step_time:.2f}s)")
            print(f"   • {len(processed_config.get('topologias', []))} topologías")
            print(f"   • {processed_config.get('cantidad_vms')} VMs")
            print(f"   • VLANs usadas: {processed_config.get('vlans_usadas')}")
            
        finally:
            # Limpiar archivos temporales
            try:
                os.unlink(temp_input_path)
                os.unlink(temp_output_path)
            except:
                pass
        
        # PASO 2: Crear namespaces DHCP
        print(f"\n🌐 PASO 2: Creando namespaces DHCP...")
        step_start = datetime.now()
        
        slice_id = processed_config['id_slice']
        vlans_used = processed_config['vlans_usadas']
        
        dhcp_result = await create_dhcp_namespaces(slice_id, vlans_used)
        
        step_time = (datetime.now() - step_start).total_seconds()
        deployment_details['timing']['dhcp_namespaces'] = step_time
        # Determinar status del paso basado en el resultado
        step_status = 'SUCCESS'
        if not dhcp_result['success']:
            step_status = 'ERROR'
        elif dhcp_result.get('partial_success', False):
            step_status = 'PARTIAL'
        
        deployment_details['steps'].append({
            'step': 2,
            'name': 'Creación namespaces DHCP',
            'status': step_status,
            'time_seconds': step_time,
            'details': dhcp_result
        })
        
        created_vlans = dhcp_result.get('created_vlans', [])
        
        if dhcp_result['success']:
            if dhcp_result.get('partial_success', False):
                print(f"⚠️  Namespaces DHCP creados parcialmente ({step_time:.2f}s)")
                print(f"   • {len(created_vlans)} VLANs configuradas exitosamente")
                if 'errors' in dhcp_result:
                    print(f"   • {len(dhcp_result['errors'])} errores encontrados")
            else:
                print(f"✅ Namespaces DHCP creados exitosamente ({step_time:.2f}s)")
                print(f"   • {len(created_vlans)} VLANs configuradas")
        else:
            print(f"❌ Error critico creando namespaces DHCP: {dhcp_result['message']}")
            return DeployResponse(
                success=False,
                message=f"Error critico creando namespaces DHCP: {dhcp_result['message']}",
                deployment_details=deployment_details,
                error="dhcp_creation_failed"
            )
        
        # PASO 3: Desplegar VMs en workers
        print(f"\n🚀 PASO 3: Desplegando VMs en workers...")
        step_start = datetime.now()
        
        vm_deployment_result = await deploy_all_vms(processed_config)
        
        step_time = (datetime.now() - step_start).total_seconds()
        deployment_details['timing']['vm_deployment'] = step_time
        deployment_details['steps'].append({
            'step': 3,
            'name': 'Despliegue de VMs',
            'status': 'SUCCESS' if vm_deployment_result['success'] else 'PARTIAL',
            'time_seconds': step_time,
            'details': vm_deployment_result
        })
        
        deployed_vms = vm_deployment_result.get('deployed_vms', [])
        failed_vms = vm_deployment_result.get('failed_vms', [])
        
        print(f"🏁 Despliegue VMs completado ({step_time:.2f}s)")
        print(f"   • {len(deployed_vms)} VMs desplegadas exitosamente")
        print(f"   • {len(failed_vms)} VMs fallidas")
        
        # PASO 4: Verificación final y cleanup en caso de errores
        print(f"\n🔍 PASO 4: Verificación final del despliegue...")
        step_start = datetime.now()
        
        expected_vlans = dhcp_result.get('created_vlans', [])
        verification_result = await verify_deployment_and_cleanup_on_error(slice_id, expected_vlans)
        
        step_time = (datetime.now() - step_start).total_seconds()
        deployment_details['timing']['verification'] = step_time
        deployment_details['steps'].append({
            'step': 4,
            'name': 'Verificación final',
            'status': 'SUCCESS' if verification_result['success'] else 'ERROR',
            'time_seconds': step_time,
            'details': verification_result
        })
        
        # Si la verificación falla, retornar error inmediatamente
        if not verification_result['success']:
            total_time = (datetime.now() - start_time).total_seconds()
            deployment_details['timing']['total'] = total_time
            
            error_message = f"No se pudo crear la topología para slice {slice_id}. {verification_result['message']}"
            
            print(f"\n❌ DESPLIEGUE FALLIDO ({total_time:.2f}s)")
            print(f"Error: {error_message}")
            
            return DeployResponse(
                success=False,
                message=error_message,
                deployment_details=deployment_details,
                error="topology_creation_failed"
            )
        
        print(f"✅ Verificación final exitosa ({step_time:.2f}s)")
        
        # RESUMEN FINAL (solo si la verificación fue exitosa)
        total_time = (datetime.now() - start_time).total_seconds()
        deployment_details['timing']['total'] = total_time
        deployment_details['processed_config'] = processed_config
        deployment_details['summary'] = {
            'total_topologies': len(processed_config.get('topologias', [])),
            'total_vms': len(deployed_vms) + len(failed_vms),
            'successful_vms': len(deployed_vms),
            'failed_vms': len(failed_vms),
            'dhcp_vlans_created': len(dhcp_result.get('created_vlans', [])),
            'deployment_time_seconds': total_time,
            'verification_passed': True
        }
        
        vm_success = len(failed_vms) == 0
        message = f"Slice {slice_id} desplegado y verificado exitosamente - {len(deployed_vms)}/{len(deployed_vms) + len(failed_vms)} VMs"
        
        print(f"\n🎉 DESPLIEGUE COMPLETADO ({total_time:.2f}s)")
        print(f"Status: {'ÉXITO TOTAL' if vm_success else 'ÉXITO PARCIAL'}")
        print(f"Mensaje: {message}")
        
        return DeployResponse(
            success=True,  # Siempre True si llegamos aquí (verificación pasó)
            message=message,
            deployment_details=deployment_details
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error en despliegue: {str(e)}")
        traceback.print_exc()
        
        return DeployResponse(
            success=False,
            message="Error interno del servidor durante el despliegue",
            error=str(e)
        )

if __name__ == "__main__":
    import uvicorn
    print("🚀 Iniciando API del Orquestador...")
    print("📍 Puerto: 5807")
    print("🔗 URL: http://localhost:5807")
    print("📚 Docs: http://localhost:5807/docs")
    
    uvicorn.run(
        "orquestador_api:app",
        host="0.0.0.0",
        port=5807,
        reload=True,
        log_level="info"
    )
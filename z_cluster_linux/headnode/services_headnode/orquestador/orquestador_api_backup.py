#!/usr/bin/env python3
"""
API del Orquestador - Coordinador central para gestión de slices en cluster Linux
Puerto: 5805
Versión: 3.1 - Con gestión de puertos VNC (MongoDB)
"""

from fastapi import FastAPI, HTTPException, Depends, status, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import jwt
import json
from datetime import datetime
import traceback
import requests
import logging
import shutil
import os

# Importar gestor de puertos VNC
from vnc_manager import VNCPortManager, count_vms_by_worker

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Orquestador API - Cluster Linux", 
    version="3.1",
    description="Coordinador central para despliegue y gestión de slices multi-worker con VNC Manager",
    redoc_url="/redoc"
)

# =============================================================================
# CONFIGURACIÓN
# =============================================================================

# JWT
JWT_SECRET_KEY = "mi_clave_secreta_super_segura_12345"
JWT_ALGORITHM = "HS256"

# Workers del cluster Linux
WORKERS_CONFIG = {
    'worker1': '192.168.201.2',
    'worker2': '192.168.201.3', 
    'worker3': '192.168.201.4'
}

# API de workers (vm_node_manager.py)
WORKER_API_PORT = 5805
WORKER_API_TOKEN = "clavesihna"

# NFS Shared Storage
NFS_IMAGES_PATH = "/mnt/nfs/shared"

security = HTTPBearer()

# Gestor de puertos VNC (MongoDB)
vnc_manager = None

# =============================================================================
# EVENTOS DE STARTUP/SHUTDOWN
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Inicializar VNC Manager y crear directorio de imágenes al arrancar"""
    global vnc_manager
    try:
        vnc_manager = VNCPortManager()
        logger.info("VNC Manager inicializado correctamente")
        
        # Crear directorio de imágenes si no existe
        os.makedirs(NFS_IMAGES_PATH, exist_ok=True)
        logger.info(f"Directorio de imágenes NFS: {NFS_IMAGES_PATH}")
    except Exception as e:
        logger.error(f"Error inicializando VNC Manager: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cerrar conexión a MongoDB al apagar"""
    global vnc_manager
    if vnc_manager:
        vnc_manager.close()
        logger.info("VNC Manager cerrado")

# =============================================================================
# MODELOS PYDANTIC
# =============================================================================

class TopologyRequest(BaseModel):
    """Modelo para solicitud de procesamiento de topología"""
    json_config: Dict[Any, Any] = Field(..., description="JSON de configuración de topología")

class TopologyResponse(BaseModel):
    """Respuesta de procesamiento de topología"""
    success: bool
    message: str
    result: Optional[Dict[Any, Any]] = None
    error: Optional[str] = None

class DeployRequest(BaseModel):
    """Modelo para despliegue completo de slice"""
    json_config: Dict[Any, Any] = Field(..., description="JSON de configuración completo")

class DeployResponse(BaseModel):
    """Respuesta de despliegue completo"""
    success: bool
    message: str
    deployment_details: Optional[Dict[str, Any]] = None
    processed_config: Optional[Dict[str, Any]] = None  # JSON con VNC rellenados
    error: Optional[str] = None

class SliceOperationRequest(BaseModel):
    """Modelo para operaciones sobre slice (pausar/reanudar/eliminar)"""
    slice_id: int = Field(..., ge=1, le=9999, description="ID del slice")

class SingleVMOperationRequest(BaseModel):
    """Modelo para operaciones sobre VM individual"""
    slice_id: int = Field(..., ge=1, le=9999, description="ID del slice")
    vm_name: str = Field(..., min_length=1, max_length=50, description="Nombre de la VM (ej: vm1, vm2)")

class SliceOperationResponse(BaseModel):
    """Respuesta de operaciones sobre slice"""
    success: bool
    message: str
    slice_id: int
    workers_results: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class SliceStatusResponse(BaseModel):
    """Respuesta de consulta de estado de slice"""
    success: bool
    slice_id: int
    total_vms: int
    running_vms: int
    paused_vms: int
    workers_status: Dict[str, Any]
    vms_detail: Optional[List[Dict[str, Any]]] = None

    vms_detail: Optional[List[Dict[str, Any]]] = None

# =============================================================================
# AUTENTICACIÓN JWT
# =============================================================================

def verify_jwt_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verifica el token JWT del auth_api"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        
        # Verificar expiración
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
# FUNCIONES AUXILIARES DE PROCESAMIENTO
# =============================================================================

def normalize_json_config(json_config: Dict[Any, Any]) -> Dict[Any, Any]:
    """
    Normaliza el JSON de entrada con formato anidado
    
    Formato esperado:
    {
        "nombre_slice": "...",
        "zona_despliegue": "...",
        "solicitud_json": {
            "id_slice": "1",  # string → se convierte a int
            "topologias": [
                {
                    "vms": [
                        {"server": "worker1"}  # Debe ser worker1/2/3
                    ]
                }
            ]
        }
    }
    """
    # Extraer el contenido de solicitud_json
    if 'solicitud_json' not in json_config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El JSON debe contener el campo 'solicitud_json'"
        )
    
    config = json_config['solicitud_json'].copy()
    
    # Convertir id_slice a int si viene como string
    if 'id_slice' in config and isinstance(config['id_slice'], str):
        config['id_slice'] = int(config['id_slice'])
    
    return config

def validate_deployment_json(json_config: Dict[Any, Any]) -> None:
    """
    Valida que el JSON tenga la estructura correcta para despliegue directo
    
    Estructura esperada:
    {
        "id_slice": 1,  # int
        "topologias": [
            {
                "nombre": "lineal",  # string (opcional)
                "vms": [
                    {
                        "nombre": "vm1",
                        "server": "worker1",
                        "cores": "1",
                        "ram": "512M",
                        "almacenamiento": "1G",
                        "puerto_vnc": "1",
                        "image": "cirros",
                        "conexiones_vlans": "1,2"
                    }
                ]
            }
        ]
    }
    
    HTTPException: Si falta algún campo requerido o tiene formato incorrecto
    """
    # Validar campos de nivel raíz
    if 'id_slice' not in json_config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campo requerido faltante: id_slice"
        )
    
    if 'topologias' not in json_config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campo requerido faltante: topologias"
        )
    
    # Validar que topologias sea un array
    if not isinstance(json_config['topologias'], list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El campo 'topologias' debe ser un array"
        )
    
    if len(json_config['topologias']) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe haber al menos una topología"
        )
    
    # Validar cada topología
    for i, topology in enumerate(json_config['topologias']):
        if not isinstance(topology, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Topología {i} debe ser un objeto"
            )
        
        # Validar que tenga array de VMs
        if 'vms' not in topology:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Topología {i} ('{topology.get('nombre', 'sin nombre')}'): falta campo 'vms'"
            )
        
        if not isinstance(topology['vms'], list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Topología {i}: el campo 'vms' debe ser un array"
            )
        
        if len(topology['vms']) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Topología {i} ('{topology.get('nombre', 'sin nombre')}'): debe tener al menos una VM"
            )
        
        # Validar cada VM
        required_vm_fields = ['nombre', 'server', 'cores', 'ram', 'almacenamiento', 
                             'puerto_vnc', 'image', 'conexiones_vlans']
        
        for j, vm in enumerate(topology['vms']):
            if not isinstance(vm, dict):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Topología {i}, VM {j}: debe ser un objeto"
                )
            
            # Validar campos requeridos
            for field in required_vm_fields:
                if field not in vm:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Topología {i}, VM {j} ('{vm.get('nombre', 'sin nombre')}'): falta campo requerido '{field}'"
                    )
            
            # Validar que server sea worker1/2/3
            if vm['server'] not in ['worker1', 'worker2', 'worker3']:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"VM '{vm['nombre']}': server debe ser 'worker1', 'worker2' o 'worker3', recibido '{vm['server']}'"
                )

# =============================================================================
# FUNCIONES AUXILIARES PARA COMUNICACIÓN CON WORKERS
# =============================================================================

async def call_worker_api(worker_ip: str, endpoint: str, method: str = "POST", 
                         payload: Optional[Dict] = None, timeout: int = 60) -> Dict[str, Any]:
    """
    Llamada a la API de un worker (vm_node_manager.py)
    
    Args:
        worker_ip: IP del worker
        endpoint: Endpoint de la API (ej: /create, /pause, /resume, /cleanup)
        method: Método HTTP (POST o GET)
        payload: Datos a enviar (para POST)
        timeout: Timeout en segundos
    
    Returns:
        Dict con resultado de la llamada
    """
    try:
        url = f"http://{worker_ip}:{WORKER_API_PORT}{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {WORKER_API_TOKEN}"
        }
        
        if method == "POST":
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        else:  # GET
            response = requests.get(url, headers=headers, timeout=timeout)
        
        if response.status_code == 200:
            return {
                'success': True,
                'status_code': 200,
                'data': response.json()
            }
        else:
            return {
                'success': False,
                'status_code': response.status_code,
                'error': response.text
            }
            
    except requests.exceptions.Timeout:
        return {
            'success': False,
            'error': 'timeout',
            'message': f'Timeout conectando a worker {worker_ip}'
        }
    except requests.exceptions.ConnectionError:
        return {
            'success': False,
            'error': 'connection_error',
            'message': f'Error de conexión a worker {worker_ip}'
        }
    except Exception as e:
        return {
            'success': False,
            'error': 'internal_error',
            'message': f'Error interno: {str(e)}'
        }

async def create_vm_on_worker(worker_ip: str, vm_config: Dict, slice_id: int) -> Dict[str, Any]:
    """
    Crear una VM en un worker específico
    """
    try:
        # Preparar payload según CreateVMRequest de vm_node_manager.py
        payload = {
            "id": slice_id,
            "vm_name": vm_config["nombre"],
            "ovs_name": "br-cloud",  # Bridge OVS estándar
            "cpu_cores": int(vm_config["cores"]),
            "ram_size": vm_config["ram"],
            "storage_size": vm_config["almacenamiento"],
            "vnc_port": int(vm_config["puerto_vnc"]),
            "image": vm_config["image"],
            "vlans": vm_config["conexiones_vlans"]  # String "100,200,300"
        }
        
        result = await call_worker_api(worker_ip, "/create", "POST", payload, timeout=120)
        
        return {
            'success': result.get('success', False),
            'vm_name': vm_config["nombre"],
            'worker_response': result.get('data'),
            'error': result.get('error')
        }
        
    except Exception as e:
        return {
            'success': False,
            'vm_name': vm_config.get("nombre", "unknown"),
            'error': f'Error interno: {str(e)}'
        }

async def get_slice_status_from_workers(slice_id: int) -> Dict[str, Any]:
    """
    Consultar estado de un slice en todos los workers
    """
    workers_status = {}
    total_vms = 0
    running_vms = 0
    paused_vms = 0
    all_vms = []
    
    for worker_name, worker_ip in WORKERS_CONFIG.items():
        try:
            # Endpoint: GET /status/{vm_id} del vm_node_manager.py
            result = await call_worker_api(worker_ip, f"/status/{slice_id}", "GET", timeout=30)
            
            if result['success']:
                data = result['data']
                worker_total = data.get('total_vms', 0)
                worker_running = data.get('running_vms', 0)
                worker_paused = data.get('paused_vms', 0)
                
                total_vms += worker_total
                running_vms += worker_running
                paused_vms += worker_paused
                
                workers_status[worker_name] = {
                    'success': True,
                    'ip': worker_ip,
                    'total_vms': worker_total,
                    'running_vms': worker_running,
                    'paused_vms': worker_paused,
                    'vms': data.get('vms', [])
                }
                
                # Agregar VMs con info del worker
                for vm in data.get('vms', []):
                    all_vms.append({
                        **vm,
                        'worker': worker_name,
                        'worker_ip': worker_ip
                    })
            else:
                workers_status[worker_name] = {
                    'success': False,
                    'ip': worker_ip,
                    'error': result.get('error', 'Unknown error')
                }
                
        except Exception as e:
            workers_status[worker_name] = {
                'success': False,
                'ip': worker_ip,
                'error': str(e)
            }
    
    return {
        'total_vms': total_vms,
        'running_vms': running_vms,
        'paused_vms': paused_vms,
        'workers_status': workers_status,
        'vms': all_vms
    }

async def pause_slice_on_workers(slice_id: int) -> Dict[str, Any]:
    """
    Pausar todas las VMs de un slice en todos los workers
    """
    results = {
        'successful_workers': [],
        'failed_workers': []
    }
    
    for worker_name, worker_ip in WORKERS_CONFIG.items():
        try:
            # Endpoint: POST /pause con VMOperationRequest
            payload = {"id": slice_id}
            result = await call_worker_api(worker_ip, "/pause", "POST", payload, timeout=60)
            
            if result['success']:
                results['successful_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'response': result['data']
                })
            else:
                results['failed_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'error': result.get('error', 'Unknown error')
                })
                
        except Exception as e:
            results['failed_workers'].append({
                'worker': worker_name,
                'ip': worker_ip,
                'error': str(e)
            })
    
    return results

async def resume_slice_on_workers(slice_id: int) -> Dict[str, Any]:
    """
    Reanudar todas las VMs de un slice en todos los workers
    """
    results = {
        'successful_workers': [],
        'failed_workers': []
    }
    
    for worker_name, worker_ip in WORKERS_CONFIG.items():
        try:
            # Endpoint: POST /resume con VMOperationRequest
            payload = {"id": slice_id}
            result = await call_worker_api(worker_ip, "/resume", "POST", payload, timeout=60)
            
            if result['success']:
                results['successful_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'response': result['data']
                })
            else:
                results['failed_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'error': result.get('error', 'Unknown error')
                })
                
        except Exception as e:
            results['failed_workers'].append({
                'worker': worker_name,
                'ip': worker_ip,
                'error': str(e)
            })
    
    return results

async def cleanup_slice_on_workers(slice_id: int) -> Dict[str, Any]:
    """
    Eliminar completamente un slice en todos los workers
    """
    results = {
        'successful_workers': [],
        'failed_workers': []
    }
    
    for worker_name, worker_ip in WORKERS_CONFIG.items():
        try:
            # Endpoint: POST /cleanup con VMOperationRequest
            payload = {"id": slice_id}
            result = await call_worker_api(worker_ip, "/cleanup", "POST", payload, timeout=120)
            
            if result['success']:
                results['successful_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'response': result['data']
                })
            else:
                results['failed_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'error': result.get('error', 'Unknown error')
                })
                
        except Exception as e:
            results['failed_workers'].append({
                'worker': worker_name,
                'ip': worker_ip,
                'error': str(e)
            })
    
    return results

async def find_vm_worker(slice_id: int, vm_name: str) -> Optional[str]:
    """
    Busca en qué worker está desplegada una VM específica
    
    Returns:
        IP del worker si se encuentra, None si no existe
    """
    for worker_name, worker_ip in WORKERS_CONFIG.items():
        try:
            result = await call_worker_api(worker_ip, f"/status/{slice_id}", "GET", timeout=10)
            
            if result['success']:
                vms = result['data'].get('vms', [])
                # Buscar la VM por nombre (formato: id{slice_id}-{vm_name})
                expected_name = f"id{slice_id}-{vm_name}"
                for vm in vms:
                    if vm.get('name') == expected_name:
                        return worker_ip
        except:
            continue
    
    return None

async def pause_single_vm_on_worker(worker_ip: str, slice_id: int, vm_name: str) -> Dict[str, Any]:
    """Pausar una VM específica en un worker"""
    payload = {"id": slice_id, "vm_name": vm_name}
    return await call_worker_api(worker_ip, "/pause-vm", "POST", payload, timeout=30)

async def resume_single_vm_on_worker(worker_ip: str, slice_id: int, vm_name: str) -> Dict[str, Any]:
    """Reanudar una VM específica en un worker"""
    payload = {"id": slice_id, "vm_name": vm_name}
    return await call_worker_api(worker_ip, "/resume-vm", "POST", payload, timeout=30)

async def shutdown_single_vm_on_worker(worker_ip: str, slice_id: int, vm_name: str) -> Dict[str, Any]:
    """Apagar una VM específica en un worker"""
    payload = {"id": slice_id, "vm_name": vm_name}
    return await call_worker_api(worker_ip, "/shutdown-vm", "POST", payload, timeout=30)

async def start_single_vm_on_worker(worker_ip: str, slice_id: int, vm_name: str) -> Dict[str, Any]:
    """Encender una VM específica en un worker"""
    payload = {"id": slice_id, "vm_name": vm_name}
    return await call_worker_api(worker_ip, "/start-vm", "POST", payload, timeout=30)

async def shutdown_slice_on_workers(slice_id: int) -> Dict[str, Any]:
    """Apagar todas las VMs de un slice en todos los workers"""
    results = {
        'successful_workers': [],
        'failed_workers': []
    }
    
    for worker_name, worker_ip in WORKERS_CONFIG.items():
        try:
            payload = {"id": slice_id}
            result = await call_worker_api(worker_ip, "/shutdown", "POST", payload, timeout=60)
            
            if result['success']:
                results['successful_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'response': result['data']
                })
            else:
                results['failed_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'error': result.get('error', 'Unknown error')
                })
                
        except Exception as e:
            results['failed_workers'].append({
                'worker': worker_name,
                'ip': worker_ip,
                'error': str(e)
            })
    
    return results

async def start_slice_on_workers(slice_id: int) -> Dict[str, Any]:
    """Encender todas las VMs de un slice en todos los workers"""
    results = {
        'successful_workers': [],
        'failed_workers': []
    }
    
    for worker_name, worker_ip in WORKERS_CONFIG.items():
        try:
            payload = {"id": slice_id}
            result = await call_worker_api(worker_ip, "/start", "POST", payload, timeout=60)
            
            if result['success']:
                results['successful_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'response': result['data']
                })
            else:
                results['failed_workers'].append({
                    'worker': worker_name,
                    'ip': worker_ip,
                    'error': result.get('error', 'Unknown error')
                })
                
        except Exception as e:
            results['failed_workers'].append({
                'worker': worker_name,
                'ip': worker_ip,
                'error': str(e)
            })
    
    return results

# =============================================================================
# LÓGICA PRINCIPAL DE DESPLIEGUE
# =============================================================================

async def deploy_all_vms(processed_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Desplegar todas las VMs del slice procesado en sus workers correspondientes
    
    Args:
        processed_config: JSON procesado con VLANs, VNC y servers ya asignados
    
    Returns:
        Dict con resultado del despliegue
    """
    try:
        slice_id = processed_config["id_slice"]
        print(f"\nDesplegando VMs para slice {slice_id}")
        
        deployed_vms = []
        failed_vms = []
        
        # Iterar por todas las topologías
        for topology in processed_config["topologias"]:
            print(f"\nDesplegando topología: {topology['nombre']}")
            
            # Iterar por todas las VMs de la topología
            for vm in topology["vms"]:
                vm_name = vm["nombre"]
                worker_name = vm["server"]
                
                print(f"   Desplegando {vm_name} en {worker_name}...")
                
                # Verificar que el worker existe en la configuración
                if worker_name not in WORKERS_CONFIG:
                    failed_vms.append({
                        'vm_name': vm_name,
                        'worker': worker_name,
                        'error': f'Worker {worker_name} no configurado en WORKERS_CONFIG'
                    })
                    print(f"   [ERROR] Worker {worker_name} no configurado")
                    continue
                
                worker_ip = WORKERS_CONFIG[worker_name]
                
                # Desplegar VM en el worker
                result = await create_vm_on_worker(worker_ip, vm, slice_id)
                
                if result['success']:
                    deployed_vms.append({
                        'vm_name': vm_name,
                        'worker': worker_name,
                        'worker_ip': worker_ip,
                        'vnc_port': f"59{int(vm['puerto_vnc']):02d}",
                        'vlans': vm['conexiones_vlans'],
                        'cores': vm['cores'],
                        'ram': vm['ram']
                    })
                    print(f"   [OK] {vm_name} desplegada exitosamente")
                else:
                    failed_vms.append({
                        'vm_name': vm_name,
                        'worker': worker_name,
                        'worker_ip': worker_ip,
                        'error': result.get('error', 'Unknown error')
                    })
                    print(f"   [ERROR] Error desplegando {vm_name}: {result.get('error')}")
        
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

# =============================================================================
# ENDPOINTS DE LA API
# =============================================================================

@app.get("/")
async def root():
    """Endpoint raíz - información del servicio"""
    return {
        "service": "Orquestador API - Cluster Linux",
        "version": "3.0.0",
        "status": "running",
        "port": 5807,
        "workers": list(WORKERS_CONFIG.keys()),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health_check():
    """Health check del orquestador"""
    return {
        "status": "healthy",
        "service": "orquestador_api",
        "timestamp": datetime.now().isoformat()
    }

@app.post("/image-importer")
async def import_image(file: UploadFile = File(...)):
    """
    Importar imagen de VM al almacenamiento NFS compartido
    
    Recibe un archivo de imagen (qcow2, img, raw, etc.) y lo guarda
    en el directorio NFS /mnt/nfs/shared/images/ para que todos los
    workers puedan acceder a él.
    
    Args:
        file: Archivo de imagen a importar
    
    Returns:
        JSON con información de la imagen importada
    """
    try:
        # Validar que se recibió un archivo
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se recibió ningún archivo"
            )
        
        logger.info(f"Recibiendo imagen: {file.filename}")
        
        # Ruta destino en NFS
        destination_path = os.path.join(NFS_IMAGES_PATH, file.filename)
        
        # Verificar si el archivo ya existe
        if os.path.exists(destination_path):
            file_size = os.path.getsize(destination_path)
            logger.warning(f"La imagen {file.filename} ya existe ({file_size} bytes)")
            return {
                "success": True,
                "message": f"Imagen {file.filename} ya existe en el almacenamiento compartido",
                "filename": file.filename,
                "path": destination_path,
                "size_bytes": file_size,
                "already_existed": True
            }
        
        # Guardar el archivo
        start_time = datetime.now()
        total_bytes = 0
        
        with open(destination_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):  # Leer en chunks de 1MB
                buffer.write(chunk)
                total_bytes += len(chunk)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Obtener tamaño final del archivo
        file_size = os.path.getsize(destination_path)
        
        logger.info(f"Imagen guardada: {file.filename} ({file_size} bytes) en {duration:.2f}s")
        
        return {
            "success": True,
            "message": f"Imagen {file.filename} importada exitosamente",
            "filename": file.filename,
            "path": destination_path,
            "size_bytes": file_size,
            "size_mb": round(file_size / (1024 * 1024), 2),
            "upload_time_seconds": round(duration, 2),
            "nfs_shared": True,
            "available_to_workers": ["worker1", "worker2", "worker3"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error importando imagen: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error importando imagen: {str(e)}"
        )

@app.delete("/image-delete/{image_id}")
async def delete_image(image_id: int):
    """
    Eliminar una imagen base del almacenamiento NFS compartido
    
    Las imágenes base se nombran con el formato: image_{id}
    Por ejemplo: image_1, image_2, etc.
    
    Args:
        image_id: ID de la imagen a eliminar
    
    Returns:
        JSON con resultado de la operación
    """
    try:
        if image_id < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="image_id debe ser un número positivo"
            )
        
        # Buscar el archivo con el patrón image_{id}*
        image_pattern = f"image_{image_id}"
        logger.info(f"Buscando imagen con patrón: {image_pattern}")
        
        # Listar archivos en NFS que coincidan con el patrón
        matching_files = []
        if os.path.exists(NFS_IMAGES_PATH):
            for filename in os.listdir(NFS_IMAGES_PATH):
                if filename.startswith(image_pattern):
                    matching_files.append(filename)
        
        if not matching_files:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No se encontró ninguna imagen con ID {image_id} (buscando 'image_{image_id}*')"
            )
        
        # Si hay múltiples coincidencias, tomar la primera
        image_filename = matching_files[0]
        image_path = os.path.join(NFS_IMAGES_PATH, image_filename)
        
        # Verificar que sea un archivo
        if not os.path.isfile(image_path):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{image_filename}' no es un archivo válido"
            )
        
        # Obtener información del archivo antes de eliminarlo
        file_size = os.path.getsize(image_path)
        
        # Eliminar archivo
        os.remove(image_path)
        logger.info(f"Imagen eliminada: {image_filename} ({file_size} bytes)")
        
        return {
            "success": True,
            "message": f"Imagen con ID {image_id} eliminada exitosamente",
            "image_id": image_id,
            "filename": image_filename,
            "path": image_path,
            "size_bytes": file_size,
            "size_mb": round(file_size / (1024 * 1024), 2),
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error eliminando imagen ID {image_id}: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error eliminando imagen: {str(e)}"
        )

# =============================================================================
# FUNCIÓN AUXILIAR PARA DESPLIEGUE CON REINTENTOS
# =============================================================================

async def attempt_deploy_slice(json_config: Dict, slice_id: int, attempt_number: int) -> Dict:
    """
    Intenta desplegar un slice (función auxiliar para reintentos)
    
    Returns:
        Dict con resultado del despliegue:
        - success: bool
        - deployment_details: Dict con detalles
        - error: str (si falla)
        - retry_needed: bool (True si es error de VNC duplicado)
    """
    deployment_details = {
        'slice_id': slice_id,
        'attempt': attempt_number,
        'steps': [],
        'timing': {}
    }
    start_time = datetime.now()
    
    try:
        # PASO 1.5: Reservar puertos VNC
        print(f"\n[Intento {attempt_number}] Reservando puertos VNC...")
        step_start = datetime.now()
        
        vms_by_worker = count_vms_by_worker(json_config)
        allocated_vnc_ports = vnc_manager.reserve_vnc_ports(slice_id, vms_by_worker)
        
        if not allocated_vnc_ports:
            step_time = (datetime.now() - step_start).total_seconds()
            deployment_details['steps'].append({
                'step': 1.5,
                'name': 'Reserva de puertos VNC',
                'status': 'FAILED',
                'time_seconds': step_time,
                'details': {'error': 'Slice ya existe o no hay puertos disponibles'}
            })
            return {
                'success': False,
                'deployment_details': deployment_details,
                'error': 'VNC reservation failed',
                'retry_needed': False  # No reintentar si no hay puertos
            }
        
        # Asignar puertos VNC a las VMs
        vnc_port_index = {worker: 0 for worker in ['worker1', 'worker2', 'worker3']}
        for topology in json_config.get('topologias', []):
            for vm in topology.get('vms', []):
                worker = vm.get('server', '')
                if worker in allocated_vnc_ports:
                    ports_list = allocated_vnc_ports[worker]
                    if vnc_port_index[worker] < len(ports_list):
                        vm['puerto_vnc'] = str(ports_list[vnc_port_index[worker]])
                        vnc_port_index[worker] += 1
        
        step_time = (datetime.now() - step_start).total_seconds()
        deployment_details['timing']['vnc_reservation'] = step_time
        deployment_details['steps'].append({
            'step': 1.5,
            'name': 'Reserva de puertos VNC',
            'status': 'SUCCESS',
            'time_seconds': step_time,
            'details': {'allocated_ports': allocated_vnc_ports, 'vms_by_worker': vms_by_worker}
        })
        
        print(f"[Intento {attempt_number}] Puertos VNC asignados: {allocated_vnc_ports}")
        
        # PASO 2: Desplegar VMs
        print(f"[Intento {attempt_number}] Desplegando VMs en workers...")
        step_start = datetime.now()
        
        vm_deployment_result = await deploy_all_vms(json_config)
        
        step_time = (datetime.now() - step_start).total_seconds()
        deployment_details['timing']['vm_deployment'] = step_time
        
        deployed_vms = vm_deployment_result.get('deployed_vms', [])
        failed_vms = vm_deployment_result.get('failed_vms', [])
        
        # Si hay VMs fallidas, hacer rollback
        if len(failed_vms) > 0:
            print(f"[Intento {attempt_number}] {len(failed_vms)} VMs fallaron - Ejecutando rollback...")
            
            # Rollback: Limpiar VMs desplegadas
            cleanup_start = datetime.now()
            cleanup_results = await cleanup_slice_on_workers(slice_id)
            cleanup_time = (datetime.now() - cleanup_start).total_seconds()
            
            # Liberar puertos VNC
            vnc_released = vnc_manager.release_vnc_ports(slice_id)
            
            deployment_details['steps'].append({
                'step': 2,
                'name': 'Despliegue de VMs',
                'status': 'FAILED',
                'time_seconds': step_time,
                'details': vm_deployment_result
            })
            
            deployment_details['steps'].append({
                'step': 3,
                'name': 'Rollback - Limpieza',
                'status': 'SUCCESS',
                'time_seconds': cleanup_time,
                'details': cleanup_results
            })
            
            deployment_details['steps'].append({
                'step': 3.5,
                'name': 'Rollback - Liberación VNC',
                'status': 'SUCCESS' if vnc_released else 'WARNING',
                'details': {'vnc_released': vnc_released}
            })
            
            deployment_details['timing']['cleanup'] = cleanup_time
            
            # Detectar si es error de puerto VNC duplicado (race condition)
            vnc_conflict = any('vnc_port' in str(vm.get('error', '')).lower() or 
                              'already in use' in str(vm.get('error', '')).lower() 
                              for vm in failed_vms)
            
            return {
                'success': False,
                'deployment_details': deployment_details,
                'error': f"{len(failed_vms)} VMs failed",
                'retry_needed': vnc_conflict,  # Reintentar si es conflicto VNC
                'failed_vms': failed_vms
            }
        
        # Despliegue exitoso
        deployment_details['steps'].append({
            'step': 2,
            'name': 'Despliegue de VMs',
            'status': 'SUCCESS',
            'time_seconds': step_time,
            'details': vm_deployment_result
        })
        
        deployment_details['timing']['total'] = (datetime.now() - start_time).total_seconds()
        
        return {
            'success': True,
            'deployment_details': deployment_details,
            'deployed_vms': deployed_vms,
            'processed_config': json_config  # Devolver JSON con VNC rellenados
        }
        
    except Exception as e:
        # Error inesperado - liberar VNC si se reservó
        vnc_manager.release_vnc_ports(slice_id)
        
        return {
            'success': False,
            'deployment_details': deployment_details,
            'error': str(e),
            'retry_needed': False
        }

@app.post("/desplegar-slice", response_model=DeployResponse)
async def desplegar_slice(
    request: DeployRequest
):
    """
    Despliega un slice completo con JSON ya procesado (con reintentos ante race conditions)
    
    Flujo:
    1. Normaliza JSON (extrae solicitud_json y convierte id_slice)
    2. Valida estructura del JSON (campos requeridos)
    3. Intenta desplegar con máximo 3 reintentos (ante conflictos VNC)
    4. Si falla después de 3 intentos, retorna error detallado
    
    Reintentos:
    - Se reintentan automáticamente conflictos de puertos VNC (race condition)
    - Máximo 3 intentos
    - Cada reintento hace cleanup completo (VMs + reserva VNC)
    
    Formato esperado: ver documentación anterior
    
    Retorna:
    - Detalles completos del despliegue con estado por worker
    - En caso de error: indica intentos realizados y error final
    """
    MAX_ATTEMPTS = 3
    slice_id = None
    
    try:
        # Normalizar JSON (extraer solicitud_json y convertir id_slice)
        json_config = normalize_json_config(request.json_config)
        slice_id = json_config.get('id_slice')
        
        print(f"\n{'='*60}")
        print(f"INICIANDO DESPLIEGUE DE SLICE {slice_id}")
        print(f"{'='*60}")
        
        overall_start_time = datetime.now()
        
        # PASO 1: Validar estructura del JSON
        print(f"\nPASO 1: Validando estructura del JSON...")
        step_start = datetime.now()
        
        validate_deployment_json(json_config)
        
        validation_time = (datetime.now() - step_start).total_seconds()
        
        print(f"JSON validado correctamente ({validation_time:.4f}s)")
        print(f"   • {len(json_config.get('topologias', []))} topologías")
        print(f"   • {sum(len(t.get('vms', [])) for t in json_config.get('topologias', []))} VMs")
        
        # PASO 2: Intentar despliegue (con reintentos)
        all_attempts = []
        last_result = None
        
        for attempt in range(1, MAX_ATTEMPTS + 1):
            print(f"\n{'='*60}")
            print(f"INTENTO {attempt}/{MAX_ATTEMPTS}")
            print(f"{'='*60}")
            
            # Intentar despliegue
            result = await attempt_deploy_slice(json_config, slice_id, attempt)
            all_attempts.append(result)
            last_result = result
            
            if result['success']:
                # ¡Éxito!
                total_time = (datetime.now() - overall_start_time).total_seconds()
                
                print(f"\n{'='*60}")
                print(f"DESPLIEGUE EXITOSO (intento {attempt}/{MAX_ATTEMPTS})")
                print(f"{'='*60}")
                
                deployment_details = result['deployment_details']
                deployment_details['timing']['validation'] = validation_time
                deployment_details['timing']['total'] = total_time
                deployment_details['total_attempts'] = attempt
                
                # Agregar paso de validación
                deployment_details['steps'].insert(0, {
                    'step': 1,
                    'name': 'Validación de JSON',
                    'status': 'SUCCESS',
                    'time_seconds': validation_time,
                    'details': {
                        'total_topologies': len(json_config.get('topologias', [])),
                        'total_vms': sum(len(t.get('vms', [])) for t in json_config.get('topologias', []))
                    }
                })
                
                return DeployResponse(
                    success=True,
                    message=f"Slice {slice_id} desplegado exitosamente - {len(result['deployed_vms'])} VMs creadas" + 
                            (f" (tras {attempt} intentos)" if attempt > 1 else ""),
                    deployment_details=deployment_details,
                    processed_config=result.get('processed_config')  # JSON con VNC rellenados
                )
            
            # Falló - verificar si debemos reintentar
            if not result.get('retry_needed', False):
                # No es un error reinentable (ej: sin puertos disponibles)
                print(f"\nError NO reintentar: {result.get('error')}")
                break
            
            # Es un error de race condition - reintentar
            if attempt < MAX_ATTEMPTS:
                print(f"\nConflicto detectado - Reintentando...")
                import time
                time.sleep(0.1 * attempt)  # Backoff exponencial
            else:
                print(f"\nMaximo de intentos alcanzado")
        
        # Todos los intentos fallaron
        total_time = (datetime.now() - overall_start_time).total_seconds()
        
        print(f"\n{'='*60}")
        print(f"DESPLIEGUE FALLIDO despues de {len(all_attempts)} intentos")
        print(f"{'='*60}")
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                'error': f'Despliegue fallido después de {len(all_attempts)} intentos',
                'slice_id': slice_id,
                'total_attempts': len(all_attempts),
                'last_error': last_result.get('error'),
                'failed_vms': last_result.get('failed_vms', []),
                'all_attempts': all_attempts,
                'total_time_seconds': total_time
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error inesperado: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del servidor: {str(e)}"
        )

@app.get("/estado-slice/{slice_id}", response_model=SliceStatusResponse)
async def estado_slice(
    slice_id: int
):
    """
    Consulta el estado de un slice en todos los workers
    
    Retorna información detallada de todas las VMs del slice,
    agrupadas por worker.
    """
    try:
        if not 1 <= slice_id <= 9999:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="slice_id debe estar entre 1 y 9999"
            )
        
        print(f"\nConsultando estado del slice {slice_id}")
        
        status_data = await get_slice_status_from_workers(slice_id)
        
        return SliceStatusResponse(
            success=True,
            slice_id=slice_id,
            total_vms=status_data['total_vms'],
            running_vms=status_data['running_vms'],
            paused_vms=status_data['paused_vms'],
            workers_status=status_data['workers_status'],
            vms_detail=status_data['vms']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error consultando estado: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")


@app.post("/pausar-slice", response_model=SliceOperationResponse)
async def pausar_slice(
    request: SliceOperationRequest
):
    """
    Pausa todas las VMs de un slice en todos los workers
    
    Las VMs pausadas mantienen su estado en memoria pero
    no consumen CPU. Pueden reanudarse con /reanudar-slice.
    """
    try:
        slice_id = request.slice_id
        
        if not 1 <= slice_id <= 9999:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="slice_id debe estar entre 1 y 9999"
            )
        
        print(f"\nPausando slice {slice_id}")
        
        results = await pause_slice_on_workers(slice_id)
        
        success = len(results['failed_workers']) == 0
        total_workers = len(results['successful_workers']) + len(results['failed_workers'])
        
        message = f"Slice {slice_id} pausado en {len(results['successful_workers'])}/{total_workers} workers"
        
        return SliceOperationResponse(
            success=success,
            message=message,
            slice_id=slice_id,
            workers_results=results
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error pausando slice: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.post("/reanudar-slice", response_model=SliceOperationResponse)
async def reanudar_slice(
    request: SliceOperationRequest
):
    """
    Reanuda todas las VMs pausadas de un slice en todos los workers
    
    Solo afecta a VMs que estén en estado PAUSADO.
    VMs apagadas (SHUTOFF) no se ven afectadas.
    """
    try:
        slice_id = request.slice_id
        
        if not 1 <= slice_id <= 9999:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="slice_id debe estar entre 1 y 9999"
            )
        
        print(f"\nReanudando slice {slice_id}")
        
        results = await resume_slice_on_workers(slice_id)
        
        success = len(results['failed_workers']) == 0
        total_workers = len(results['successful_workers']) + len(results['failed_workers'])
        
        message = f"Slice {slice_id} reanudado en {len(results['successful_workers'])}/{total_workers} workers"
        
        return SliceOperationResponse(
            success=success,
            message=message,
            slice_id=slice_id,
            workers_results=results
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error reanudando slice: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.post("/eliminar-slice", response_model=SliceOperationResponse)
async def eliminar_slice(
    request: SliceOperationRequest
):
    """
    Elimina completamente un slice: VMs, discos, interfaces TAP, etc.
    
    ADVERTENCIA: Esta operación es DESTRUCTIVA e IRREVERSIBLE.
    Se eliminarán todas las VMs y sus datos asociados en todos los workers.
    
    También libera los puertos VNC reservados para este slice.
    """
    try:
        slice_id = request.slice_id
        
        if not 1 <= slice_id <= 9999:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="slice_id debe estar entre 1 y 9999"
            )
        
        print(f"\nEliminando slice {slice_id}")
        
        # Limpiar recursos en workers
        results = await cleanup_slice_on_workers(slice_id)
        
        # Liberar puertos VNC
        print(f"Liberando puertos VNC del slice {slice_id}...")
        vnc_released = vnc_manager.release_vnc_ports(slice_id)
        
        if vnc_released:
            print(f"   Puertos VNC liberados")
        else:
            print(f"   No se encontraron puertos VNC para liberar (slice no existia o ya liberado)")
        
        results['vnc_ports_released'] = vnc_released
        
        success = len(results['failed_workers']) == 0
        total_workers = len(results['successful_workers']) + len(results['failed_workers'])
        
        message = f"Slice {slice_id} eliminado en {len(results['successful_workers'])}/{total_workers} workers"
        
        if vnc_released:
            message += " (puertos VNC liberados)"
        
        return SliceOperationResponse(
            success=success,
            message=message,
            slice_id=slice_id,
            workers_results=results
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error eliminando slice: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

# =============================================================================
# ENDPOINTS DE OPERACIONES DE VM INDIVIDUAL
# =============================================================================

@app.post("/pausar-vm", response_model=SliceOperationResponse)
async def pausar_vm_individual(
    request: SingleVMOperationRequest
):
    """
    Pausa una VM específica de un slice
    
    Busca automáticamente en qué worker está la VM y ejecuta la operación.
    """
    try:
        slice_id = request.slice_id
        vm_name = request.vm_name
        
        if not 1 <= slice_id <= 9999:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="slice_id debe estar entre 1 y 9999"
            )
        
        print(f"\nPausando VM '{vm_name}' del slice {slice_id}")
        
        # Buscar en qué worker está la VM
        worker_ip = await find_vm_worker(slice_id, vm_name)
        
        if not worker_ip:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No se encontró la VM '{vm_name}' en ningún worker"
            )
        
        # Pausar la VM
        result = await pause_single_vm_on_worker(worker_ip, slice_id, vm_name)
        
        if result['success']:
            return SliceOperationResponse(
                success=True,
                message=f"VM '{vm_name}' del slice {slice_id} pausada exitosamente",
                slice_id=slice_id,
                workers_results={'worker_ip': worker_ip, 'response': result['data']}
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get('error', 'Error pausando VM')
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error pausando VM: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.post("/reanudar-vm", response_model=SliceOperationResponse)
async def reanudar_vm_individual(
    request: SingleVMOperationRequest
):
    """
    Reanuda una VM específica de un slice
    
    Busca automáticamente en qué worker está la VM y ejecuta la operación.
    """
    try:
        slice_id = request.slice_id
        vm_name = request.vm_name
        
        if not 1 <= slice_id <= 9999:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="slice_id debe estar entre 1 y 9999"
            )
        
        print(f"\nReanudando VM '{vm_name}' del slice {slice_id}")
        
        # Buscar en qué worker está la VM
        worker_ip = await find_vm_worker(slice_id, vm_name)
        
        if not worker_ip:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No se encontró la VM '{vm_name}' en ningún worker"
            )
        
        # Reanudar la VM
        result = await resume_single_vm_on_worker(worker_ip, slice_id, vm_name)
        
        if result['success']:
            return SliceOperationResponse(
                success=True,
                message=f"VM '{vm_name}' del slice {slice_id} reanudada exitosamente",
                slice_id=slice_id,
                workers_results={'worker_ip': worker_ip, 'response': result['data']}
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get('error', 'Error reanudando VM')
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error reanudando VM: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.post("/apagar-vm", response_model=SliceOperationResponse)
async def apagar_vm_individual(
    request: SingleVMOperationRequest
):
    """
    Apaga una VM específica de un slice
    
    Busca automáticamente en qué worker está la VM y ejecuta la operación.
    """
    try:
        slice_id = request.slice_id
        vm_name = request.vm_name
        
        if not 1 <= slice_id <= 9999:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="slice_id debe estar entre 1 y 9999"
            )
        
        print(f"\nApagando VM '{vm_name}' del slice {slice_id}")
        
        # Buscar en qué worker está la VM
        worker_ip = await find_vm_worker(slice_id, vm_name)
        
        if not worker_ip:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No se encontró la VM '{vm_name}' en ningún worker"
            )
        
        # Apagar la VM
        result = await shutdown_single_vm_on_worker(worker_ip, slice_id, vm_name)
        
        if result['success']:
            return SliceOperationResponse(
                success=True,
                message=f"VM '{vm_name}' del slice {slice_id} apagada exitosamente",
                slice_id=slice_id,
                workers_results={'worker_ip': worker_ip, 'response': result['data']}
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get('error', 'Error apagando VM')
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error apagando VM: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.post("/encender-vm", response_model=SliceOperationResponse)
async def encender_vm_individual(
    request: SingleVMOperationRequest
):
    """
    Enciende una VM específica de un slice
    
    Busca automáticamente en qué worker está la VM y ejecuta la operación.
    """
    try:
        slice_id = request.slice_id
        vm_name = request.vm_name
        
        if not 1 <= slice_id <= 9999:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="slice_id debe estar entre 1 y 9999"
            )
        
        print(f"\nEncendiendo VM '{vm_name}' del slice {slice_id}")
        
        # Buscar en qué worker está la VM
        worker_ip = await find_vm_worker(slice_id, vm_name)
        
        if not worker_ip:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No se encontró la VM '{vm_name}' en ningún worker"
            )
        
        # Encender la VM
        result = await start_single_vm_on_worker(worker_ip, slice_id, vm_name)
        
        if result['success']:
            return SliceOperationResponse(
                success=True,
                message=f"VM '{vm_name}' del slice {slice_id} encendida exitosamente",
                slice_id=slice_id,
                workers_results={'worker_ip': worker_ip, 'response': result['data']}
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get('error', 'Error encendiendo VM')
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error encendiendo VM: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

# =============================================================================
# ENDPOINTS DE OPERACIONES DE SLICE COMPLETO
# =============================================================================

@app.post("/apagar-slice", response_model=SliceOperationResponse)
async def apagar_slice(
    request: SliceOperationRequest
):
    """
    Apaga todas las VMs de un slice en todos los workers
    """
    try:
        slice_id = request.slice_id
        
        if not 1 <= slice_id <= 9999:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="slice_id debe estar entre 1 y 9999"
            )
        
        print(f"\nApagando todas las VMs del slice {slice_id}")
        
        results = await shutdown_slice_on_workers(slice_id)
        
        success = len(results['failed_workers']) == 0
        total_workers = len(results['successful_workers']) + len(results['failed_workers'])
        
        message = f"Slice {slice_id} apagado en {len(results['successful_workers'])}/{total_workers} workers"
        
        return SliceOperationResponse(
            success=success,
            message=message,
            slice_id=slice_id,
            workers_results=results
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error apagando slice: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.post("/encender-slice", response_model=SliceOperationResponse)
async def encender_slice(
    request: SliceOperationRequest
):
    """
    Enciende todas las VMs de un slice en todos los workers
    """
    try:
        slice_id = request.slice_id
        
        if not 1 <= slice_id <= 9999:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="slice_id debe estar entre 1 y 9999"
            )
        
        print(f"\nEncendiendo todas las VMs del slice {slice_id}")
        
        results = await start_slice_on_workers(slice_id)
        
        success = len(results['failed_workers']) == 0
        total_workers = len(results['successful_workers']) + len(results['failed_workers'])
        
        message = f"Slice {slice_id} encendido en {len(results['successful_workers'])}/{total_workers} workers"
        
        return SliceOperationResponse(
            success=success,
            message=message,
            slice_id=slice_id,
            workers_results=results
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error encendiendo slice: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

# =============================================================================
# CONFIGURACIÓN DE ARRANQUE
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    print("=" * 60)
    print("Iniciando Orquestador API - Cluster Linux")
    print("=" * 60)
    print(f"Puerto: 5805")
    print(f"URL: http://localhost:5805")
    print(f"Workers configurados: {', '.join(WORKERS_CONFIG.keys())}")
    print("=" * 60)
    
    uvicorn.run(
        "orquestador_api:app",
        host="0.0.0.0",
        port=5805,
        reload=True,
        log_level="info"
    )


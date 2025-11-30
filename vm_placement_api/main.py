from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Any
import os
import pika
import json
import logging
import threading
import time
import httpx
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import pytz

# Importar el algoritmo de placement
from placement_algorithm import VMPlacementAlgorithm, PlacementTracker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="VM Placement API",
    version="2.0.0",
    description="API para asignar VMs a workers y enviar al driver"
)

# Configuración
SERVICE_TOKEN = os.getenv('SERVICE_TOKEN', 'clavesihna')
DRIVERS_URL = os.getenv('DRIVERS_URL', 'http://drivers:6200')
SLICE_MANAGER_URL = os.getenv('SLICE_MANAGER_URL', 'http://slice_manager_api:5900')

# Configuración RabbitMQ
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', 'rabbitmq')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', 5672))
RABBITMQ_USER = os.getenv('RABBITMQ_USER', 'guest')
RABBITMQ_PASS = os.getenv('RABBITMQ_PASS', 'guest')

# Nombres de colas
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
tracker = PlacementTracker()

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
            logger.info(f"[VM_PLACEMENT] Conexión a RabbitMQ establecida en intento {attempt + 1}")
            return connection
        except Exception as e:
            logger.warning(f"[VM_PLACEMENT] Intento {attempt + 1}/{max_retries} falló: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                raise Exception(f"No se pudo conectar a RabbitMQ después de {max_retries} intentos")

def process_vm_placement(slice_id: int, zona_despliegue: str, solicitud_json: dict, nombre_slice: str):
    """
    Procesar asignación de workers usando el algoritmo de placement y enviar al driver
    Retorna True si es exitoso, False si falla
    """
    try:
        # ===== PASO 1: Asignar workers usando el algoritmo de placement =====
        logger.info(f"[VM_PLACEMENT] Slice {slice_id}: Iniciando asignación con algoritmo de placement")
        
        placement = VMPlacementAlgorithm(zona_despliegue)
        success, message = placement.assign_vms(slice_id, solicitud_json)
        
        if not success:
            logger.error(f"[VM_PLACEMENT] Slice {slice_id}: Error en placement - {message}")
            
            # Actualizar BD con error
            try:
                connection = mysql.connector.connect(**DB_CONFIG)
                cursor = connection.cursor()
                
                cursor.execute(
                    "UPDATE slices SET tipo = %s, estado = %s WHERE id = %s",
                    ('error_placement', message, slice_id)
                )
                connection.commit()
                cursor.close()
                connection.close()
            except Exception as db_error:
                logger.error(f"[VM_PLACEMENT] Error actualizando BD: {str(db_error)}")
            
            return False
        
        logger.info(f"[VM_PLACEMENT] Slice {slice_id}: {message}")
        
        # Contar VMs asignadas
        total_vms_assigned = sum(len(topo.get('vms', [])) for topo in solicitud_json.get('topologias', []))
        logger.info(f"[VM_PLACEMENT] Slice {slice_id}: {total_vms_assigned} VMs asignadas a workers")
        
        # ===== PASO 2: Notificar a slice_manager que el JSON está listo =====
        logger.info(f"[VM_PLACEMENT] Slice {slice_id}: JSON listo, notificando a slice_manager...")
        
        # Preparar callback payload
        callback_payload = {
            "nombre_slice": nombre_slice,
            "zona_despliegue": zona_despliegue,
            "solicitud_json": solicitud_json
        }
        
        # Llamar a slice_manager para que despliegue
        import requests
        callback_response = requests.post(
            f"{SLICE_MANAGER_URL}/slices/deploymentready/{slice_id}",
            json=callback_payload,
            headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
            timeout=300
        )
        
        if callback_response.status_code != 200:
            logger.error(f"[VM_PLACEMENT] Slice {slice_id}: Error en callback a slice_manager: {callback_response.text}")
            # Rollback del tracking
            tracker.remove_slice(zona_despliegue, slice_id)
            return False
        
        callback_result = callback_response.json()
        
        if not callback_result.get('success'):
            error_msg = callback_result.get('detail', 'Callback fallido')
            logger.error(f"[VM_PLACEMENT] Slice {slice_id}: Callback fallido - {error_msg}")
            # Rollback del tracking
            tracker.remove_slice(zona_despliegue, slice_id)
            return False
        
        logger.info(f"[VM_PLACEMENT] Slice {slice_id}: Despliegue completado exitosamente")
        
        return True
        
    except Exception as e:
        logger.error(f"[VM_PLACEMENT] Error procesando slice {slice_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Actualizar estado a error en BD
        try:
            connection = mysql.connector.connect(**DB_CONFIG)
            cursor = connection.cursor()
            cursor.execute("UPDATE slices SET estado = %s WHERE id = %s", ('error_despliegue', slice_id))
            connection.commit()
            cursor.close()
            connection.close()
        except:
            pass
        
        return False

def consume_vm_queue(queue_name: str, zona: str):
    """
    Consumer worker para procesar mensajes de una cola de VM placement
    Se ejecuta en un thread separado
    """
    logger.info(f"[VM_PLACEMENT] Iniciando consumer para cola '{queue_name}' (zona: {zona})")
    
    while True:
        try:
            connection = get_rabbitmq_connection()
            channel = connection.channel()
            channel.queue_declare(queue=queue_name, durable=True)
            channel.basic_qos(prefetch_count=1)
            
            def callback(ch, method, properties, body):
                try:
                    message = json.loads(body)
                    nombre_slice = message.get('nombre_slice')
                    zona_despliegue = message.get('zona_despliegue')
                    solicitud_json = message.get('solicitud_json')
                    slice_id = int(solicitud_json.get('id_slice'))
                    
                    logger.info(f"[VM_PLACEMENT] Procesando slice {slice_id} ('{nombre_slice}') de zona '{zona_despliegue}'")
                    logger.info(f"{'='*100}")
                    logger.info(f"[VM_PLACEMENT] JSON RECIBIDO CON VLANs MAPEADAS:")
                    logger.info(json.dumps(solicitud_json, indent=2, ensure_ascii=False))
                    logger.info(f"{'='*100}\n")
                    
                    # Procesar asignación de workers y despliegue
                    success = process_vm_placement(slice_id, zona_despliegue, solicitud_json, nombre_slice)
                    
                    if success:
                        # ACK: mensaje procesado exitosamente
                        ch.basic_ack(delivery_tag=method.delivery_tag)
                        logger.info(f"[VM_PLACEMENT] Slice {slice_id} procesado y desplegado exitosamente")
                    else:
                        # NACK: reencolar mensaje
                        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                        logger.error(f"[VM_PLACEMENT] Slice {slice_id} falló, reencolando...")
                        
                except Exception as e:
                    logger.error(f"[VM_PLACEMENT] Error en callback: {str(e)}")
                    # NACK sin reencolar para evitar loops infinitos
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            
            channel.basic_consume(queue=queue_name, on_message_callback=callback)
            logger.info(f"[VM_PLACEMENT] Consumer '{queue_name}' esperando mensajes...")
            channel.start_consuming()
            
        except Exception as e:
            logger.error(f"[VM_PLACEMENT] Error en consumer '{queue_name}': {str(e)}")
            time.sleep(5)  # Esperar antes de reintentar

def start_consumers():
    """Iniciar consumers en threads separados"""
    # Consumer para Linux
    thread_linux = threading.Thread(
        target=consume_vm_queue,
        args=(VM_PLACEMENT_QUEUE_LINUX, 'linux'),
        daemon=True
    )
    thread_linux.start()
    logger.info("[VM_PLACEMENT] Thread consumer Linux iniciado")
    
    # Consumer para OpenStack
    thread_openstack = threading.Thread(
        target=consume_vm_queue,
        args=(VM_PLACEMENT_QUEUE_OPENSTACK, 'openstack'),
        daemon=True
    )
    thread_openstack.start()
    logger.info("[VM_PLACEMENT] Thread consumer OpenStack iniciado")

@app.on_event("startup")
async def startup_event():
    """Inicializar consumers al arrancar"""
    import asyncio
    await asyncio.sleep(3)  # Esperar a que RabbitMQ esté listo
    start_consumers()
    logger.info("[VM_PLACEMENT] Consumers RabbitMQ ACTIVADOS")

# ==================== ENDPOINTS ====================

# Autenticación
def get_service_auth(credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
    """Verificar token de servicio"""
    if credentials.credentials != SERVICE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de servicio inválido"
        )
    return True

@app.get("/")
async def root():
    return {
        "message": "VM Placement API - RabbitMQ Consumer",
        "status": "activo",
        "version": "2.0.0",
        "algorithm": "Prometheus-based Capacity+Stability Scoring"
    }

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "OK",
        "service": "vm_placement_api",
        "version": "2.0.0",
        "queues": [VM_PLACEMENT_QUEUE_LINUX, VM_PLACEMENT_QUEUE_OPENSTACK]
    }

@app.delete("/delete-assigned-resources/{slice_id}")
async def delete_assigned_resources(slice_id: int, zona: str):
    """
    Eliminar recursos asignados del tracking cuando se elimina un slice
    
    Args:
        slice_id: ID del slice a eliminar
        zona: Zona de despliegue ('linux' o 'openstack')
    
    Returns:
        Mensaje de éxito con cantidad de VMs eliminadas
    """
    try:
        logger.info(f"[DELETE_RESOURCES] Eliminando recursos del slice {slice_id} en zona {zona}")
        
        # Verificar zona válida
        if zona not in ['linux', 'openstack']:
            raise HTTPException(
                status_code=400,
                detail=f"Zona inválida: {zona}. Debe ser 'linux' o 'openstack'"
            )
        
        # Contar VMs antes de eliminar
        tracking_data = tracker.load_tracking(zona)
        total_vms_removed = 0
        
        for worker_name, worker_data in tracking_data.items():
            vms = worker_data.get('vms', [])
            original_count = len(vms)
            # Contar VMs que pertenecen a este slice
            vms_to_remove = [vm for vm in vms if vm.get('nombre', '').startswith(f'id{slice_id}_')]
            total_vms_removed += len(vms_to_remove)
        
        # Eliminar del tracking
        tracker.remove_slice(zona, slice_id)
        
        logger.info(f"[DELETE_RESOURCES] Slice {slice_id}: {total_vms_removed} VMs eliminadas del tracking en zona {zona}")
        
        return {
            "success": True,
            "message": f"Recursos del slice {slice_id} eliminados exitosamente",
            "slice_id": slice_id,
            "zona": zona,
            "vms_removed": total_vms_removed
        }
        
    except Exception as e:
        logger.error(f"[DELETE_RESOURCES] Error eliminando recursos del slice {slice_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error eliminando recursos: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=6000, workers=1)

from fastapi import FastAPI, HTTPException, Depends, status, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx
import pika
import json
import os
import asyncio
from typing import Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Queue Manager API",
    version="1.0.0",
    description="Gestor de colas con RabbitMQ para peticiones de placement"
)

# Configuración
SERVICE_TOKEN = os.getenv('SERVICE_TOKEN', 'clavesihna')
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', 'rabbitmq')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', 5672))
RABBITMQ_USER = os.getenv('RABBITMQ_USER', 'guest')
RABBITMQ_PASS = os.getenv('RABBITMQ_PASS', 'guest')
VM_PLACEMENT_URL = os.getenv('VM_PLACEMENT_URL', 'http://vm_placement_api:6000')
QUEUE_NAME = 'vm_placement_queue'

security = HTTPBearer()

# Autenticación
def get_service_auth(credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
    """Verificar token de servicio"""
    if credentials.credentials != SERVICE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de servicio inválido"
        )
    return True

def get_rabbitmq_connection():
    """Crear conexión a RabbitMQ"""
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        credentials=credentials,
        heartbeat=600,
        blocked_connection_timeout=300
    )
    return pika.BlockingConnection(parameters)

def ensure_queue_exists():
    """Asegurar que la cola existe"""
    try:
        connection = get_rabbitmq_connection()
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME, durable=True)
        connection.close()
        logger.info(f"Cola '{QUEUE_NAME}' verificada/creada")
    except Exception as e:
        logger.error(f"Error al crear cola: {str(e)}")

@app.on_event("startup")
async def startup_event():
    """Inicializar cola al arrancar"""
    await asyncio.sleep(2)  # Esperar a que RabbitMQ esté listo
    ensure_queue_exists()

@app.get("/")
async def root():
    return {
        "message": "Queue Manager API - RabbitMQ FIFO",
        "status": "activo",
        "version": "1.0.0",
        "queue": QUEUE_NAME
    }

@app.post("/enqueue-placement")
async def enqueue_placement(
    request: dict,
    background_tasks: BackgroundTasks,
    authorized: bool = Depends(get_service_auth)
):
    """
    Encolar petición de placement para procesamiento asíncrono
    """
    try:
        connection = get_rabbitmq_connection()
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME, durable=True)
        
        # Publicar mensaje en la cola
        message = json.dumps(request)
        channel.basic_publish(
            exchange='',
            routing_key=QUEUE_NAME,
            body=message,
            properties=pika.BasicProperties(
                delivery_mode=2,  # Mensaje persistente
            )
        )
        
        connection.close()
        logger.info(f"Mensaje encolado para slice_id: {request.get('solicitud_json', {}).get('id_slice', 'unknown')}")
        
        return {
            "success": True,
            "message": "Petición encolada exitosamente",
            "queue": QUEUE_NAME,
            "slice_id": request.get('solicitud_json', {}).get('id_slice')
        }
        
    except Exception as e:
        logger.error(f"Error al encolar: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al encolar petición: {str(e)}"
        )

@app.post("/process-from-queue")
async def process_from_queue(
    authorized: bool = Depends(get_service_auth)
):
    """
    Procesar siguiente mensaje de la cola (FIFO)
    Envía al vm_placement y retorna el resultado
    """
    try:
        connection = get_rabbitmq_connection()
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME, durable=True)
        
        # Obtener un mensaje
        method_frame, header_frame, body = channel.basic_get(queue=QUEUE_NAME, auto_ack=False)
        
        if method_frame is None:
            connection.close()
            return {
                "success": False,
                "message": "Cola vacía",
                "queue": QUEUE_NAME
            }
        
        # Procesar mensaje
        request_data = json.loads(body)
        logger.info(f"Procesando slice_id: {request_data.get('solicitud_json', {}).get('id_slice')}")
        
        # Enviar a vm_placement
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{VM_PLACEMENT_URL}/assign-workers",
                json=request_data,
                headers={"Authorization": f"Bearer {SERVICE_TOKEN}"}
            )
            
            if response.status_code != 200:
                # No hacer ACK si falla
                channel.basic_nack(delivery_tag=method_frame.delivery_tag, requeue=True)
                connection.close()
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Error en vm_placement: {response.text}"
                )
            
            result = response.json()
        
        # Confirmar procesamiento (ACK)
        channel.basic_ack(delivery_tag=method_frame.delivery_tag)
        connection.close()
        
        return {
            "success": True,
            "message": "Mensaje procesado exitosamente",
            "result": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al procesar cola: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al procesar cola: {str(e)}"
        )

@app.get("/queue-status")
async def queue_status(
    authorized: bool = Depends(get_service_auth)
):
    """Obtener estado de la cola"""
    try:
        connection = get_rabbitmq_connection()
        channel = connection.channel()
        queue = channel.queue_declare(queue=QUEUE_NAME, durable=True, passive=True)
        message_count = queue.method.message_count
        connection.close()
        
        return {
            "queue": QUEUE_NAME,
            "pending_messages": message_count,
            "status": "active"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al obtener estado: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=6100, workers=1)

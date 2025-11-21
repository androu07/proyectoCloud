from fastapi import FastAPI, HTTPException, Depends, status, UploadFile, File, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import os
import subprocess
import httpx
from pathlib import Path
import mysql.connector
from mysql.connector import Error
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="API Gestor de Imágenes",
    version="2.0.0",
    description="API para gestión de imágenes de VM"
)

# Configuración
DOWNLOAD_TOKEN = os.getenv('DOWNLOAD_TOKEN', 'clavesihna')
IMAGES_DIR = os.getenv('IMAGES_DIR', '/var/lib/images')
MAX_IMAGE_SIZE = 1 * 1024 * 1024 * 1024  # 1GB en bytes

# URLs de clusters
LINUX_CLUSTER_URL = "http://192.168.203.1:5805/image-importer"
OPENSTACK_CLUSTER_URL = "http://192.168.204.1:5805/image-importer"

# Configuración de BD
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'imagenes_db'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'database': os.getenv('DB_NAME', 'imagenes_db'),
    'user': os.getenv('DB_USER', 'images_user'),
    'password': os.getenv('DB_PASSWORD', 'images_pass123')
}

security = HTTPBearer()
Path(IMAGES_DIR).mkdir(parents=True, exist_ok=True)

# Modelos
class ImageResponse(BaseModel):
    success: bool
    message: str
    image_id: int = None
    nombre: str = None
    nombre_imagen: str = None
    size_gb: float = None
    formato: str = None
    id_openstack: str = None

class ImageListItem(BaseModel):
    id: int
    nombre: str
    descripcion: str
    nombre_imagen: str
    formato: str
    tamano_gb: float
    tipo_importacion: str
    fecha_importacion: str
    id_openstack: str = None

# Autenticación
def verify_service_token(token: str) -> bool:
    return token == DOWNLOAD_TOKEN

async def get_service_auth(credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
    if not verify_service_token(credentials.credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de servicio inválido"
        )
    return True

# Funciones auxiliares
def detect_image_format(image_path: str) -> str:
    """Detectar formato real de la imagen"""
    try:
        result = subprocess.run(
            ['qemu-img', 'info', '--output=json', image_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            import json
            info = json.loads(result.stdout)
            return info.get('format', 'raw')
        return 'raw'
    except:
        return 'raw'

def get_file_extension(filename: str) -> str:
    """Obtener extensión del archivo"""
    return Path(filename).suffix

def validate_image_size(image_path: str) -> tuple[bool, str, float]:
    """Validar tamaño de imagen"""
    try:
        size_bytes = os.path.getsize(image_path)
        size_gb = size_bytes / (1024 * 1024 * 1024)
        
        if size_bytes > MAX_IMAGE_SIZE:
            return False, f"Imagen muy grande: {size_gb:.2f} GB. Máximo: 1 GB", size_gb
        
        return True, "", size_gb
    except Exception as e:
        return False, f"Error al verificar tamaño: {str(e)}", 0

def validate_image_with_qemu(image_path: str) -> tuple[bool, str]:
    """Validar que la imagen no esté corrupta"""
    try:
        result = subprocess.run(
            ['qemu-img', 'check', image_path],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode != 0:
            return False, "Imagen corrupta o inválida"
        return True, ""
    except Exception as e:
        return False, f"Error al validar imagen: {str(e)}"

async def download_image(url: str, dest_path: str) -> tuple[bool, str]:
    """Descargar imagen desde URL"""
    try:
        result = subprocess.run(
            ['wget', '-q', '--timeout=60', '--tries=3', '-O', dest_path, url],
            capture_output=True,
            timeout=300
        )
        if result.returncode != 0:
            return False, "Error al descargar la imagen"
        return True, ""
    except Exception as e:
        return False, f"Error en descarga: {str(e)}"

async def upload_to_linux_cluster(file_path: str) -> tuple[bool, str]:
    """Subir imagen al cluster Linux"""
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            with open(file_path, 'rb') as f:
                files = {'file': f}
                response = await client.post(LINUX_CLUSTER_URL, files=files)
                
                if response.status_code == 200:
                    return True, "Imagen subida al cluster Linux"
                else:
                    return False, f"Error al subir a Linux: {response.text}"
    except Exception as e:
        return False, f"Error conexión cluster Linux: {str(e)}"

async def upload_to_openstack_cluster(file_path: str, nombre: str) -> tuple[bool, str, str]:
    """Subir imagen al cluster OpenStack y obtener ID"""
    try:
        # Determinar disk_format para OpenStack
        disk_format_map = {
            '.qcow2': 'qcow2',
            '.img': 'qcow2',
            '.raw': 'raw',
            '.vmdk': 'vmdk',
            '.vdi': 'vdi'
        }
        extension = get_file_extension(file_path)
        disk_format = disk_format_map.get(extension.lower(), 'qcow2')
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            with open(file_path, 'rb') as f:
                files = {'file': ('image' + extension, f, 'application/octet-stream')}
                data = {
                    'name': nombre,
                    'disk_format': disk_format
                }
                response = await client.post(OPENSTACK_CLUSTER_URL, files=files, data=data)
                
                if response.status_code == 200:
                    result = response.json()
                    openstack_id = result.get('id', result.get('image_id', ''))
                    return True, "Imagen subida a OpenStack", openstack_id
                else:
                    return False, f"Error al subir a OpenStack: {response.text}", ""
    except Exception as e:
        return False, f"Error conexión cluster OpenStack: {str(e)}", ""

def save_to_database(nombre: str, descripcion: str, nombre_imagen: str, formato: str, 
                     size_gb: float, tipo_importacion: str, id_openstack: str = None) -> int:
    """Guardar metadatos en BD y retornar ID"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor()
        
        query = """
            INSERT INTO imagenes 
            (nombre, descripcion, nombre_imagen, formato, tamano_gb, tipo_importacion, id_openstack)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (nombre, descripcion, nombre_imagen, formato, size_gb, tipo_importacion, id_openstack))
        connection.commit()
        
        image_id = cursor.lastrowid
        cursor.close()
        connection.close()
        
        return image_id
    except Exception as e:
        raise Exception(f"Error al guardar en BD: {str(e)}")

def update_openstack_id(image_id: int, openstack_id: str):
    """Actualizar el ID de OpenStack en la BD"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor()
        
        query = "UPDATE imagenes SET id_openstack = %s WHERE id = %s"
        cursor.execute(query, (openstack_id, image_id))
        connection.commit()
        
        cursor.close()
        connection.close()
    except Exception as e:
        raise Exception(f"Error al actualizar OpenStack ID: {str(e)}")

def rename_image_file(original_path: str, image_id: int) -> tuple[str, str]:
    """Renombrar archivo a image_{id} manteniendo extensión"""
    extension = get_file_extension(original_path)
    new_filename = f"image_{image_id}{extension}"
    new_path = os.path.join(IMAGES_DIR, new_filename)
    
    os.rename(original_path, new_path)
    return new_path, new_filename

# ==================== ENDPOINTS ====================

@app.get("/")
async def root():
    return {
        "service": "Image Manager API",
        "version": "2.0.0",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/import-image", response_model=ImageResponse)
async def import_image_from_url(
    nombre: str = Form(...),
    descripcion: str = Form(...),
    url: str = Form(...),
    authorized: bool = Depends(get_service_auth)
):
    """
    Importar imagen desde URL
    - Descarga imagen desde URL
    - Valida tamaño y formato
    - Guarda metadatos en BD
    - Sube a clusters Linux y OpenStack
    - Retorna información completa
    """
    temp_file = None
    final_file = None
    
    try:
        # Validaciones de entrada
        if len(nombre) > 30:
            raise HTTPException(status_code=400, detail="El nombre no puede superar 30 caracteres")
        if len(descripcion) > 100:
            raise HTTPException(status_code=400, detail="La descripción no puede superar 100 caracteres")
        
        # Descargar imagen
        temp_file = os.path.join(IMAGES_DIR, f"temp_{os.urandom(8).hex()}")
        logger.info(f"Descargando imagen desde {url}")
        success, error_msg = await download_image(url, temp_file)
        if not success:
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Validar tamaño
        valid, error_msg, size_gb = validate_image_size(temp_file)
        if not valid:
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Validar imagen con qemu
        valid, error_msg = validate_image_with_qemu(temp_file)
        if not valid:
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Detectar formato
        formato = detect_image_format(temp_file)
        extension = get_file_extension(url) or f".{formato}"
        
        # Guardar en BD (sin openstack_id aún)
        logger.info("Guardando metadatos en BD")
        image_id = save_to_database(
            nombre=nombre,
            descripcion=descripcion,
            nombre_imagen="",  # Se actualizará después del rename
            formato=formato,
            size_gb=size_gb,
            tipo_importacion='url',
            id_openstack=None
        )
        
        # Renombrar archivo
        final_file, nombre_imagen = rename_image_file(temp_file, image_id)
        temp_file = None  # Ya fue renombrado
        
        # Actualizar nombre_imagen en BD
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor()
        cursor.execute("UPDATE imagenes SET nombre_imagen = %s WHERE id = %s", (nombre_imagen, image_id))
        connection.commit()
        cursor.close()
        connection.close()
        
        # Subir a cluster Linux
        logger.info("Subiendo imagen a cluster Linux")
        success, msg = await upload_to_linux_cluster(final_file)
        if not success:
            logger.warning(f"Error al subir a Linux: {msg}")
        
        # Subir a cluster OpenStack
        logger.info("Subiendo imagen a cluster OpenStack")
        success, msg, openstack_id = await upload_to_openstack_cluster(final_file, nombre)
        if success and openstack_id:
            update_openstack_id(image_id, openstack_id)
            logger.info(f"OpenStack ID: {openstack_id}")
        else:
            logger.warning(f"Error al subir a OpenStack: {msg}")
            openstack_id = None
        
        return ImageResponse(
            success=True,
            message="Imagen importada exitosamente",
            image_id=image_id,
            nombre=nombre,
            nombre_imagen=nombre_imagen,
            size_gb=round(size_gb, 2),
            formato=formato,
            id_openstack=openstack_id
        )
        
    except HTTPException:
        # Limpiar archivos temporales
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)
        if final_file and os.path.exists(final_file):
            os.remove(final_file)
        raise
    except Exception as e:
        # Limpiar archivos temporales
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)
        if final_file and os.path.exists(final_file):
            os.remove(final_file)
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.post("/upload-image", response_model=ImageResponse)
async def upload_image_file(
    nombre: str = Form(...),
    descripcion: str = Form(...),
    file: UploadFile = File(...),
    authorized: bool = Depends(get_service_auth)
):
    """
    Subir imagen desde archivo
    - Recibe archivo multipart
    - Valida tamaño y formato
    - Guarda metadatos en BD
    - Sube a clusters Linux y OpenStack
    - Retorna información completa
    """
    temp_file = None
    final_file = None
    
    try:
        # Validaciones de entrada
        if len(nombre) > 30:
            raise HTTPException(status_code=400, detail="El nombre no puede superar 30 caracteres")
        if len(descripcion) > 100:
            raise HTTPException(status_code=400, detail="La descripción no puede superar 100 caracteres")
        
        # Guardar archivo temporalmente
        temp_file = os.path.join(IMAGES_DIR, f"temp_{os.urandom(8).hex()}")
        logger.info(f"Recibiendo archivo: {file.filename}")
        
        with open(temp_file, 'wb') as f:
            content = await file.read()
            f.write(content)
        
        # Validar tamaño
        valid, error_msg, size_gb = validate_image_size(temp_file)
        if not valid:
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Validar imagen con qemu
        valid, error_msg = validate_image_with_qemu(temp_file)
        if not valid:
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Detectar formato
        formato = detect_image_format(temp_file)
        extension = get_file_extension(file.filename) or f".{formato}"
        
        # Guardar en BD (sin openstack_id aún)
        logger.info("Guardando metadatos en BD")
        image_id = save_to_database(
            nombre=nombre,
            descripcion=descripcion,
            nombre_imagen="",
            formato=formato,
            size_gb=size_gb,
            tipo_importacion='archivo',
            id_openstack=None
        )
        
        # Renombrar archivo
        final_file, nombre_imagen = rename_image_file(temp_file, image_id)
        temp_file = None
        
        # Actualizar nombre_imagen en BD
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor()
        cursor.execute("UPDATE imagenes SET nombre_imagen = %s WHERE id = %s", (nombre_imagen, image_id))
        connection.commit()
        cursor.close()
        connection.close()
        
        # Subir a cluster Linux
        logger.info("Subiendo imagen a cluster Linux")
        success, msg = await upload_to_linux_cluster(final_file)
        if not success:
            logger.warning(f"Error al subir a Linux: {msg}")
        
        # Subir a cluster OpenStack
        logger.info("Subiendo imagen a cluster OpenStack")
        success, msg, openstack_id = await upload_to_openstack_cluster(final_file, nombre)
        if success and openstack_id:
            update_openstack_id(image_id, openstack_id)
            logger.info(f"OpenStack ID: {openstack_id}")
        else:
            logger.warning(f"Error al subir a OpenStack: {msg}")
            openstack_id = None
        
        return ImageResponse(
            success=True,
            message="Imagen subida exitosamente",
            image_id=image_id,
            nombre=nombre,
            nombre_imagen=nombre_imagen,
            size_gb=round(size_gb, 2),
            formato=formato,
            id_openstack=openstack_id
        )
        
    except HTTPException:
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)
        if final_file and os.path.exists(final_file):
            os.remove(final_file)
        raise
    except Exception as e:
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)
        if final_file and os.path.exists(final_file):
            os.remove(final_file)
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.get("/list-images")
async def list_images(authorized: bool = Depends(get_service_auth)):
    """Listar todas las imágenes"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        query = "SELECT * FROM imagenes ORDER BY fecha_importacion DESC"
        cursor.execute(query)
        images = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        # Convertir datetime a string
        for img in images:
            if img.get('fecha_importacion'):
                img['fecha_importacion'] = str(img['fecha_importacion'])
        
        return {
            "success": True,
            "total": len(images),
            "images": images
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al listar imágenes: {str(e)}")

@app.delete("/delete-image/{image_id}")
async def delete_image(image_id: int, authorized: bool = Depends(get_service_auth)):
    """Eliminar imagen por ID de ambos clusters y BD local"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener información de la imagen
        cursor.execute("SELECT * FROM imagenes WHERE id = %s", (image_id,))
        image = cursor.fetchone()
        
        if not image:
            cursor.close()
            connection.close()
            raise HTTPException(status_code=404, detail="Imagen no encontrada")
        
        cursor.close()
        connection.close()
        
        # Eliminar del cluster Linux
        logger.info(f"Eliminando imagen {image_id} del cluster Linux")
        linux_success = False
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                linux_url = f"http://cluster-linux:5805/image-delete/{image_id}"
                logger.info(f"URL Linux: {linux_url}")
                response = await client.delete(linux_url)
                logger.info(f"Linux response status: {response.status_code}")
                logger.info(f"Linux response body: {response.text}")
                if response.status_code == 200:
                    logger.info("Imagen eliminada del cluster Linux")
                    linux_success = True
                else:
                    logger.warning(f"Error al eliminar de Linux: Status {response.status_code}, Response: {response.text}")
        except Exception as e:
            logger.error(f"Excepción al conectar con cluster Linux: {str(e)}")
        
        # Eliminar del cluster OpenStack (si tiene id_openstack)
        openstack_success = False
        if image.get('id_openstack'):
            logger.info(f"Eliminando imagen del cluster OpenStack (ID: {image['id_openstack']})")
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    openstack_url = "http://cluster-openstack:5805/image-delete"
                    logger.info(f"URL OpenStack: {openstack_url}")
                    # Usar request() genérico para DELETE con multipart/form-data (equivalente a curl -F)
                    logger.info(f"Enviando image_id: {image['id_openstack']}")
                    response = await client.request(
                        method='DELETE',
                        url=openstack_url,
                        files={'image_id': (None, image['id_openstack'])}
                    )
                    logger.info(f"OpenStack response status: {response.status_code}")
                    logger.info(f"OpenStack response body: {response.text}")
                    if response.status_code == 200:
                        logger.info("Imagen eliminada del cluster OpenStack")
                        openstack_success = True
                    else:
                        logger.warning(f"Error al eliminar de OpenStack: Status {response.status_code}, Response: {response.text}")
            except Exception as e:
                logger.error(f"Excepción al conectar con cluster OpenStack: {str(e)}")
        
        # Eliminar archivo físico local
        image_path = os.path.join(IMAGES_DIR, image['nombre_imagen'])
        if os.path.exists(image_path):
            os.remove(image_path)
            logger.info(f"Archivo local eliminado: {image['nombre_imagen']}")
        
        # COMENTADO: Eliminar de BD
        # cursor.execute("DELETE FROM imagenes WHERE id = %s", (image_id,))
        # connection.commit()
        logger.info(f"BD NO ELIMINADA (comentado para pruebas)")
        
        logger.info(f"Resultado - Linux: {linux_success}, OpenStack: {openstack_success}")
        
        return {
            "success": True,
            "message": f"Prueba de eliminación - Linux: {linux_success}, OpenStack: {openstack_success}",
            "linux_deleted": linux_success,
            "openstack_deleted": openstack_success
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error general en delete_image: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al eliminar imagen: {str(e)}")

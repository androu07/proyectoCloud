from fastapi import FastAPI, HTTPException, Depends, status, UploadFile, File, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import os
import subprocess
import httpx
from datetime import datetime
from pathlib import Path
import mysql.connector
from mysql.connector import Error

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
OPENSTACK_CLUSTER_URL = "http://192.168.203.2:5805/image-importer"

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

async def upload_to_openstack_cluster(file_path: str, nombre: str, formato: str) -> tuple[bool, str, str]:
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
    """Guardar imagen en la base de datos y retornar el ID"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor()
        
        # Leer el archivo
        with open(image_path, 'rb') as f:
            image_data = f.read()
        
        # Convertir tamaño a GB
        size_gb = size_bytes / (1024 * 1024 * 1024)
        
        # Insertar en BD
        query = """
            INSERT INTO imagenes (nombre, tamano_gb, formato, archivo)
            VALUES (%s, %s, %s, %s)
        """
        cursor.execute(query, (nombre, size_gb, formato, image_data))
        connection.commit()
        
        image_id = cursor.lastrowid
        
        cursor.close()
        connection.close()
        
        return image_id
        
    except Exception as e:
        raise Exception(f"Error al guardar en BD: {str(e)}")
    except Exception as e:
        raise Exception(f"Error: {str(e)}")

# Función para detectar formato de imagen
def detect_image_format_sync(image_path: str) -> str:
    """Detectar formato real de la imagen usando qemu-img"""
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

# Función para convertir imagen a qcow2 comprimido
def convert_to_qcow2_sync(source_path: str, dest_path: str, source_format: str = None) -> tuple[bool, str]:
    """Convertir imagen a formato qcow2 comprimido"""
    try:
        # Si no se especifica formato, detectarlo
        if not source_format:
            source_format = detect_image_format_sync(source_path)
        
        print(f"Convirtiendo de {source_format} a qcow2 comprimido...")
        
        # Convertir con compresión
        result = subprocess.run(
            ['qemu-img', 'convert',
             '-f', source_format,
             '-O', 'qcow2',
             '-c',  # Compresión
             source_path,
             dest_path],
            capture_output=True,
            text=True,
            timeout=600  # 10 minutos máximo
        )
        
        if result.returncode != 0:
            return False, f"Error al convertir: {result.stderr}"
        
        print(f"Conversión completada: {os.path.getsize(dest_path) / (1024*1024):.2f} MB")
        return True, ""
        
    except subprocess.TimeoutExpired:
        return False, "Timeout al convertir imagen"
    except Exception as e:
        return False, f"Error en conversión: {str(e)}"

# Función para comprimir con zstd
def compress_with_zstd_sync(source_path: str, dest_path: str) -> tuple[bool, str]:
    """Comprimir archivo con zstd nivel 19 (máxima compresión)"""
    try:
        print(f"Comprimiendo con zstd nivel 19...")
        
        result = subprocess.run(
            ['zstd', '-19', '--rm', source_path, '-o', dest_path],
            capture_output=True,
            text=True,
            timeout=900  # 15 minutos máximo
        )
        
        if result.returncode != 0:
            return False, f"Error al comprimir con zstd: {result.stderr}"
        
        original_size = os.path.getsize(source_path) if os.path.exists(source_path) else 0
        compressed_size = os.path.getsize(dest_path)
        
        if original_size > 0:
            ratio = (1 - compressed_size / original_size) * 100
            print(f"Compresión zstd completada: {compressed_size / (1024*1024):.2f} MB (ahorro: {ratio:.1f}%)")
        else:
            print(f"Compresión zstd completada: {compressed_size / (1024*1024):.2f} MB")
        
        return True, ""
        
    except subprocess.TimeoutExpired:
        return False, "Timeout al comprimir con zstd"
    except Exception as e:
        return False, f"Error en compresión zstd: {str(e)}"

# Función para aplicar sparsify (solo para imágenes raw grandes)
def sparsify_image_sync(source_path: str, dest_path: str) -> tuple[bool, str]:
    """Aplicar virt-sparsify para eliminar espacio vacío (solo raw)"""
    try:
        print(f"Aplicando sparsify...")
        
        result = subprocess.run(
            ['virt-sparsify', source_path, dest_path],
            capture_output=True,
            text=True,
            timeout=1800  # 30 minutos máximo
        )
        
        if result.returncode != 0:
            print(f"Sparsify falló: {result.stderr}")
            return False, f"Error al aplicar sparsify: {result.stderr}"
        
        original_size = os.path.getsize(source_path)
        sparse_size = os.path.getsize(dest_path)
        reduction = (1 - sparse_size / original_size) * 100
        
        print(f"Sparsify completado: {sparse_size / (1024*1024):.2f} MB (reducción: {reduction:.1f}%)")
        return True, ""
        
    except subprocess.TimeoutExpired:
        return False, "Timeout al aplicar sparsify"
    except Exception as e:
        return False, f"Error en sparsify: {str(e)}"

# Validación 1: Formato de URL
def validate_image_format(url: str) -> tuple[bool, str]:
    valid_extensions = ['.qcow2', '.img', '.raw', '.vmdk', '.vdi']
    if any(url.lower().endswith(ext) for ext in valid_extensions):
        return True, ""
    return False, f"URL no válida. Debe terminar en: {', '.join(valid_extensions)}"

# Validación 2: Descargar imagen
def download_image_sync(url: str, dest_path: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ['wget', '-q', '--timeout=60', '--tries=3', '-O', dest_path, url],
            capture_output=True,
            timeout=300
        )
        if result.returncode != 0:
            return False, "Error al descargar la imagen. URL incorrecta o no accesible"
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "Timeout al descargar la imagen"
    except Exception as e:
        return False, f"Error en descarga: {str(e)}"

# Validación 3: Tamaño de imagen
def validate_image_size(image_path: str) -> tuple[bool, str, float]:
    try:
        size_bytes = os.path.getsize(image_path)
        size_mb = size_bytes / (1024 * 1024)
        
        if size_bytes > MAX_IMAGE_SIZE:
            return False, f"Imagen muy grande: {size_mb:.2f} MB. Máximo permitido: 2048 MB", size_mb
        return True, "", size_mb
    except Exception as e:
        return False, f"Error al verificar tamaño: {str(e)}", 0

# Validación 4: Verificar interfaz gráfica con virt-inspector
def validate_no_gui_sync(image_path: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ['virt-inspector', '-a', image_path],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        # Si virt-inspector no puede leer la imagen, intentamos con qemu-img
        if result.returncode != 0:
            print(f"virt-inspector falló con código {result.returncode}")
            print(f"stderr: {result.stderr}")
            
            # Intentar validar con qemu-img info como alternativa
            try:
                qemu_result = subprocess.run(
                    ['qemu-img', 'info', image_path],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if qemu_result.returncode == 0:
                    print("qemu-img pudo leer la imagen, consideramos que es válida")
                    return True, ""  # Si qemu-img puede leerla, es válida
            except Exception as e:
                print(f"qemu-img también falló: {e}")
            
            return False, f"No se pudo inspeccionar la imagen: {result.stderr[:200]}"
        
        # Buscar indicadores de GUI en el output
        output_lower = result.stdout.lower()
        gui_indicators = ['gnome', 'kde', 'xfce', 'x11', 'xorg', 'desktop', 'gdm', 'lightdm']
        
        for indicator in gui_indicators:
            if indicator in output_lower:
                return False, f"Imagen rechazada: Detectada interfaz gráfica ({indicator})"
        
        return True, ""
        
    except subprocess.TimeoutExpired:
        return False, "Timeout al inspeccionar la imagen"
    except FileNotFoundError:
        return False, "virt-inspector no está instalado en el sistema"
    except Exception as e:
        return False, f"Error en inspección: {str(e)}"

# Validación 5: Verificar que la imagen no esté corrupta
def validate_image_integrity_sync(image_path: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ['virt-inspector', '-a', image_path],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        # Si virt-inspector no puede leer la imagen, intentamos con qemu-img
        if result.returncode != 0:
            print(f"virt-inspector falló en integridad con código {result.returncode}")
            
            # Si hay indicadores explícitos de corrupción, rechazar
            error_output = result.stderr.lower()
            if 'corrupt' in error_output or 'damaged' in error_output:
                return False, "Imagen corrupta o dañada"
            
            # Intentar validar con qemu-img como alternativa
            try:
                qemu_result = subprocess.run(
                    ['qemu-img', 'check', image_path],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                # qemu-img check devuelve 0 si está ok, 2 si tiene errores reparables, 3 si está corrupta
                if qemu_result.returncode == 0 or qemu_result.returncode == 2:
                    print("qemu-img check: imagen válida")
                    return True, ""
                else:
                    return False, "Imagen corrupta (qemu-img check falló)"
            except Exception as e:
                print(f"qemu-img check también falló: {e}")
                # Si ambos fallan pero no hay signos de corrupción, permitir
                return True, ""
        
        return True, ""
        
    except subprocess.TimeoutExpired:
        return False, "Timeout al verificar integridad de la imagen"
    except Exception as e:
        return False, f"Error en verificación: {str(e)}"

# Proceso completo de importación con optimización
async def import_image_process(url: str, nombre: str) -> tuple[bool, str, dict]:
    # Generar nombre temporal único para descarga
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    temp_filename = f"temp_{timestamp}_{os.path.basename(url)}"
    image_path = os.path.join(IMAGES_DIR, temp_filename)
    
    # Obtener formato de la URL
    formato_original = os.path.splitext(url)[1].lstrip('.')
    
    info = {"nombre": nombre, "formato": formato_original}
    
    # Archivos temporales
    qcow2_path = None
    zst_path = None
    sparse_path = None
    
    try:
        # Validación 1: Formato
        valid, error = validate_image_format(url)
        if not valid:
            return False, error, info
        
        # Validación 2: Descarga
        loop = asyncio.get_event_loop()
        valid, error = await loop.run_in_executor(thread_pool, download_image_sync, url, image_path)
        if not valid:
            if os.path.exists(image_path):
                os.remove(image_path)
            return False, error, info
        
        # Validación 3: Tamaño
        valid, error, size_mb = validate_image_size(image_path)
        size_bytes_original = os.path.getsize(image_path)
        size_gb = size_bytes_original / (1024 * 1024 * 1024)
        info["size_gb_original"] = round(size_gb, 2)
        
        if not valid:
            os.remove(image_path)
            return False, error, info
        
        # Validación 4: No GUI
        valid, error = await loop.run_in_executor(thread_pool, validate_no_gui_sync, image_path)
        if not valid:
            os.remove(image_path)
            return False, error, info
        
        # OPTIMIZACIÓN: Detectar formato real
        formato_real = await loop.run_in_executor(thread_pool, detect_image_format_sync, image_path)
        print(f"Formato detectado: {formato_real}")
        
        # PASO 1: Sparsify (solo si es raw y grande >500MB)
        image_to_convert = image_path
        if formato_real == 'raw' and size_bytes_original > 500 * 1024 * 1024:
            sparse_path = image_path.replace(f'.{formato_original}', '_sparse.img')
            valid, error = await loop.run_in_executor(
                thread_pool, sparsify_image_sync, image_path, sparse_path
            )
            if valid:
                image_to_convert = sparse_path
                # Borrar original
                os.remove(image_path)
            else:
                print(f"Sparsify falló, continuando sin sparsify: {error}")
        
        # PASO 2: Convertir a qcow2 comprimido
        qcow2_path = os.path.join(IMAGES_DIR, f"temp_{timestamp}.qcow2")
        valid, error = await loop.run_in_executor(
            thread_pool, convert_to_qcow2_sync, image_to_convert, qcow2_path, formato_real
        )
        
        if not valid:
            return False, f"Error al convertir a qcow2: {error}", info
        
        # Borrar archivo intermedio si existe
        if sparse_path and os.path.exists(sparse_path):
            os.remove(sparse_path)
        elif os.path.exists(image_path):
            os.remove(image_path)
        
        # PASO 3: Comprimir con zstd
        zst_path = qcow2_path + '.zst'
        valid, error = await loop.run_in_executor(
            thread_pool, compress_with_zstd_sync, qcow2_path, zst_path
        )
        
        if not valid:
            return False, f"Error al comprimir con zstd: {error}", info
        
        # qemu-img convert con --rm ya borró el qcow2, pero por si acaso:
        if os.path.exists(qcow2_path):
            os.remove(qcow2_path)
        
        # Obtener tamaño final
        size_bytes_final = os.path.getsize(zst_path)
        size_gb_final = size_bytes_final / (1024 * 1024 * 1024)
        info["size_gb"] = round(size_gb_final, 2)
        info["formato"] = "qcow2.zst"
        
        reduction = (1 - size_bytes_final / size_bytes_original) * 100
        print(f"Reducción total: {info['size_gb_original']} GB → {info['size_gb']} GB ({reduction:.1f}%)")
        
        # Guardar en BD
        image_id = await loop.run_in_executor(
            thread_pool, 
            save_image_to_db_sync, 
            zst_path, 
            nombre, 
            "qcow2.zst",
            size_bytes_final
        )
        info["image_id"] = image_id
        
        # Eliminar archivo temporal
        os.remove(zst_path)
        
        return True, "Imagen importada y optimizada exitosamente", info
        
    except Exception as e:
        # Limpieza de archivos temporales
        for temp_file in [image_path, qcow2_path, zst_path, sparse_path]:
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)
        return False, str(e), info

# Proceso de importación para archivo subido con optimización
async def import_uploaded_file(file: UploadFile, nombre: str) -> tuple[bool, str, dict]:
    # Generar nombre temporal único
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    temp_filename = f"temp_{timestamp}_{file.filename}"
    image_path = os.path.join(IMAGES_DIR, temp_filename)
    
    # Obtener formato del nombre del archivo
    formato_original = os.path.splitext(file.filename)[1].lstrip('.')
    
    info = {"nombre": nombre, "formato": formato_original}
    
    # Archivos temporales
    qcow2_path = None
    zst_path = None
    sparse_path = None
    
    try:
        # Validación 1: Formato
        valid, error = validate_image_format(file.filename)
        if not valid:
            return False, error, info
        
        # Guardar archivo temporalmente
        try:
            with open(image_path, 'wb') as f:
                shutil.copyfileobj(file.file, f)
        except Exception as e:
            return False, f"Error al guardar archivo: {str(e)}", info
        
        # Validación 2: Tamaño
        valid, error, size_mb = validate_image_size(image_path)
        size_bytes_original = os.path.getsize(image_path)
        size_gb = size_bytes_original / (1024 * 1024 * 1024)
        info["size_gb_original"] = round(size_gb, 2)
        
        if not valid:
            os.remove(image_path)
            return False, error, info
        
        # Validación 3: No GUI
        loop = asyncio.get_event_loop()
        valid, error = await loop.run_in_executor(thread_pool, validate_no_gui_sync, image_path)
        if not valid:
            os.remove(image_path)
            return False, error, info
        
        # Validación 4: Integridad
        valid, error = await loop.run_in_executor(thread_pool, validate_image_integrity_sync, image_path)
        if not valid:
            os.remove(image_path)
            return False, error, info
        
        # OPTIMIZACIÓN: Detectar formato real
        formato_real = await loop.run_in_executor(thread_pool, detect_image_format_sync, image_path)
        print(f"Formato detectado: {formato_real}")
        
        # PASO 1: Sparsify (solo si es raw y grande >500MB)
        image_to_convert = image_path
        if formato_real == 'raw' and size_bytes_original > 500 * 1024 * 1024:
            sparse_path = image_path.replace(f'.{formato_original}', '_sparse.img')
            valid, error = await loop.run_in_executor(
                thread_pool, sparsify_image_sync, image_path, sparse_path
            )
            if valid:
                image_to_convert = sparse_path
                # Borrar original
                os.remove(image_path)
            else:
                print(f"Sparsify falló, continuando sin sparsify: {error}")
        
        # PASO 2: Convertir a qcow2 comprimido
        qcow2_path = os.path.join(IMAGES_DIR, f"temp_{timestamp}.qcow2")
        valid, error = await loop.run_in_executor(
            thread_pool, convert_to_qcow2_sync, image_to_convert, qcow2_path, formato_real
        )
        
        if not valid:
            return False, f"Error al convertir a qcow2: {error}", info
        
        # Borrar archivo intermedio si existe
        if sparse_path and os.path.exists(sparse_path):
            os.remove(sparse_path)
        elif os.path.exists(image_path):
            os.remove(image_path)
        
        # PASO 3: Comprimir con zstd
        zst_path = qcow2_path + '.zst'
        valid, error = await loop.run_in_executor(
            thread_pool, compress_with_zstd_sync, qcow2_path, zst_path
        )
        
        if not valid:
            return False, f"Error al comprimir con zstd: {error}", info
        
        # Borrar qcow2 si existe
        if os.path.exists(qcow2_path):
            os.remove(qcow2_path)
        
        # Obtener tamaño final
        size_bytes_final = os.path.getsize(zst_path)
        size_gb_final = size_bytes_final / (1024 * 1024 * 1024)
        info["size_gb"] = round(size_gb_final, 2)
        info["formato"] = "qcow2.zst"
        
        reduction = (1 - size_bytes_final / size_bytes_original) * 100
        print(f"Reducción total: {info['size_gb_original']} GB → {info['size_gb']} GB ({reduction:.1f}%)")
        
        # Guardar en BD
        image_id = await loop.run_in_executor(
            thread_pool, 
            save_image_to_db_sync, 
            zst_path, 
            nombre, 
            "qcow2.zst",
            size_bytes_final
        )
        info["image_id"] = image_id
        
        # Eliminar archivo temporal
        os.remove(zst_path)
        
        return True, "Imagen subida y optimizada exitosamente", info
        
    except Exception as e:
        # Limpieza de archivos temporales
        for temp_file in [image_path, qcow2_path, zst_path, sparse_path]:
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)
        return False, str(e), info

# Endpoints
@app.get("/")
async def root():
    return {
        "message": "API Importador de Imágenes",
        "status": "activo",
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "OK",
        "timestamp": datetime.utcnow().isoformat(),
        "images_directory": IMAGES_DIR,
        "max_size_mb": MAX_IMAGE_SIZE / (1024 * 1024)
    }

@app.post("/import-image", response_model=ImageResponse)
async def import_image_by_url(
    request: ImageUrlRequest,
    authorized: bool = Depends(get_service_auth)
):
    """
    Importar imagen desde URL con validaciones:
    1. Formato de archivo válido
    2. URL accesible y descargable
    3. Tamaño <= 2GB
    4. Sin interfaz gráfica
    5. Guardar en BD y eliminar archivo local
    """
    try:
        success, message, info = await import_image_process(request.url, request.nombre)
        
        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
        
        return ImageResponse(
            message=message,
            success=True,
            image_id=info.get("image_id"),
            image_name=info.get("nombre"),
            size_gb=info.get("size_gb"),
            formato=info.get("formato")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.post("/upload-image", response_model=ImageResponse)
async def upload_image_file(
    nombre: str = Form(...),
    file: UploadFile = File(...),
    authorized: bool = Depends(get_service_auth)
):
    """
    Subir imagen como archivo con validaciones:
    1. Formato de archivo válido
    2. Tamaño <= 2GB
    3. Sin interfaz gráfica
    4. Imagen no corrupta
    5. Guardar en BD y eliminar archivo local
    """
    try:
        success, message, info = await import_uploaded_file(file, nombre)
        
        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
        
        return ImageResponse(
            message=message,
            success=True,
            image_id=info.get("image_id"),
            image_name=info.get("nombre"),
            size_gb=info.get("size_gb"),
            formato=info.get("formato")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )

@app.get("/list-images")
async def list_images(authorized: bool = Depends(get_service_auth)):
    """
    Listar todas las imágenes almacenadas en la base de datos
    """
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        query = """
            SELECT id, nombre, tamano_gb, formato, 
                   LENGTH(archivo) as archivo_bytes, 
                   fecha_importacion 
            FROM imagenes 
            ORDER BY fecha_importacion DESC
        """
        cursor.execute(query)
        images = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        return {
            "success": True,
            "count": len(images),
            "images": images
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al listar imágenes: {str(e)}"
        )

@app.delete("/delete-image/{image_id}")
async def delete_image(
    image_id: int,
    authorized: bool = Depends(get_service_auth)
):
    """
    Eliminar una imagen del catálogo por su ID
    """
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Verificar si la imagen existe
        cursor.execute("SELECT id, nombre FROM imagenes WHERE id = %s", (image_id,))
        image = cursor.fetchone()
        
        if not image:
            cursor.close()
            connection.close()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Imagen con ID {image_id} no encontrada"
            )
        
        # Eliminar la imagen
        cursor.execute("DELETE FROM imagenes WHERE id = %s", (image_id,))
        connection.commit()
        
        cursor.close()
        connection.close()
        
        return {
            "success": True,
            "message": f"Imagen '{image['nombre']}' eliminada exitosamente",
            "deleted_id": image_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al eliminar imagen: {str(e)}"
        )

@app.get("/download")
async def download_image(
    nombre: str,
    authorized: bool = Depends(get_service_auth)
):
    """
    Descargar imagen por nombre (requiere token 'clavesihna')
    Retorna la imagen comprimida en formato qcow2.zst
    """
    try:
        from fastapi.responses import StreamingResponse
        import io
        
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Buscar imagen por nombre
        query = "SELECT id, nombre, formato, archivo FROM imagenes WHERE nombre = %s"
        cursor.execute(query, (nombre,))
        image = cursor.fetchone()
        
        cursor.close()
        connection.close()
        
        if not image:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Imagen '{nombre}' no encontrada"
            )
        
        # Obtener el archivo (BLOB)
        image_data = image['archivo']
        formato = image['formato']
        
        # Preparar nombre del archivo para descarga
        filename = f"{nombre}.{formato}" if formato else f"{nombre}.qcow2.zst"
        
        # Crear streaming response
        return StreamingResponse(
            io.BytesIO(image_data),
            media_type='application/octet-stream',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'X-Image-Format': formato,
                'X-Image-Name': nombre
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al descargar imagen: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5700, workers=4)

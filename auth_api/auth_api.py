from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from typing import Optional
import mysql.connector
from mysql.connector import Error
import mysql.connector.pooling
import bcrypt
import jwt
from datetime import datetime, timedelta
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

app = FastAPI(title="API de Autenticación", version="1.0.0")

# Configuración de la base de datos
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'database': os.getenv('DB_NAME', 'usuarios_db'),
    'user': os.getenv('DB_USER', 'app_user'),
    'password': os.getenv('DB_PASSWORD', 'app_password123')
}

# Pool de conexiones para concurrencia
DB_POOL_CONFIG = {
    **DB_CONFIG,
    'pool_name': 'auth_pool',
    'pool_size': 10,
    'pool_reset_session': True,
    'autocommit': True
}

# Inicializar pool de conexiones
try:
    connection_pool = mysql.connector.pooling.MySQLConnectionPool(**DB_POOL_CONFIG)
except Error as e:
    print(f"Error creando pool de conexiones: {e}")
    connection_pool = None

# ThreadPoolExecutor para operaciones bloqueantes
thread_pool = ThreadPoolExecutor(max_workers=20)

# Configuración JWT
JWT_SECRET = os.getenv('JWT_SECRET_KEY', 'mi_clave_secreta_super_segura_12345')
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_HOURS = 1

security = HTTPBearer()

# Modelos Pydantic
class LoginRequest(BaseModel):
    correo: EmailStr
    password: str

class LoginResponse(BaseModel):
    message: str
    token: str
    user_info: dict

class UserInfo(BaseModel):
    id: int
    nombre: str
    apellidos: str
    correo: str
    rol: str

# Conexión a la base de datos usando pool
@contextmanager
def get_db_connection():
    connection = None
    try:
        if connection_pool:
            connection = connection_pool.get_connection()
        else:
            connection = mysql.connector.connect(**DB_CONFIG)
        yield connection
    except Error as e:
        print(f"Error al conectar con la base de datos: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error de conexión con la base de datos"
        )
    finally:
        if connection and connection.is_connected():
            connection.close()

# Funciones auxiliares
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verificar contraseña con bcrypt"""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_jwt_token(user_data: dict) -> str:
    """Crear token JWT"""
    payload = {
        'id': user_data['id'],
        'nombre_completo': f"{user_data['nombre']} {user_data['apellidos']}",
        'correo': user_data['correo'],
        'rol': user_data['rol'],
        'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def get_user_by_email_sync(correo: str):
    """Obtener usuario por correo electrónico (versión síncrona)"""
    with get_db_connection() as connection:
        cursor = connection.cursor(dictionary=True)
        query = "SELECT id, nombre, apellidos, correo, password, rol FROM usuarios WHERE correo = %s"
        cursor.execute(query, (correo,))
        user = cursor.fetchone()
        cursor.close()
        return user

async def get_user_by_email(correo: str):
    """Obtener usuario por correo electrónico (versión asíncrona)"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(thread_pool, get_user_by_email_sync, correo)

# Endpoints
@app.get("/")
async def root():
    return {"message": "API de Autenticación y Autorización", "status": "activo"}

def check_db_health_sync():
    """Verificar salud de la base de datos (versión síncrona)"""
    try:
        with get_db_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            return "OK"
    except:
        return "Error"

@app.get("/health")
async def health_check():
    """Endpoint de verificación de salud"""
    loop = asyncio.get_event_loop()
    db_status = await loop.run_in_executor(thread_pool, check_db_health_sync)
    
    return {
        "status": "OK",
        "database": db_status,
        "timestamp": datetime.utcnow().isoformat(),
        "pool_info": {
            "pool_size": connection_pool.pool_size if connection_pool else "N/A",
            "pool_name": connection_pool.pool_name if connection_pool else "N/A"
        }
    }

@app.post("/login", response_model=LoginResponse)
async def login(login_data: LoginRequest):
    """Endpoint de autenticación de usuarios"""
    try:
        # Buscar usuario en la base de datos (asíncrono)
        user = await get_user_by_email(login_data.correo)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciales inválidas"
            )
        
        # Verificar contraseña
        if not verify_password(login_data.password, user['password']):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciales inválidas"
            )
        
        # Crear token JWT
        token = create_jwt_token(user)
        
        # Preparar información del usuario (sin la contraseña)
        user_info = {
            'id': user['id'],
            'nombre': user['nombre'],
            'apellidos': user['apellidos'],
            'correo': user['correo'],
            'rol': user['rol']
        }
        
        return LoginResponse(
            message="Autenticación exitosa",
            token=token,
            user_info=user_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error en login: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor"
        )

@app.post("/verify-token")
async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Endpoint para verificar la validez de un token JWT"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        
        return {
            "valid": True,
            "user_data": {
                "id": payload.get('id'),
                "nombre_completo": payload.get('nombre_completo'),
                "correo": payload.get('correo'),
                "rol": payload.get('rol')
            },
            "expires_at": payload.get('exp')
        }
        
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
    except Exception as e:
        print(f"Error verificando token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
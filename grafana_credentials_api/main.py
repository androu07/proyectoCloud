from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import jwt
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor

app = FastAPI(
    title="API de Credenciales de Grafana", 
    version="1.0.0",
    description="API para enviar credenciales de Grafana a usuarios admin autenticados"
)

# Configuración JWT (debe coincidir con auth_api)
JWT_SECRET = os.getenv('JWT_SECRET_KEY', 'mi_clave_secreta_super_segura_12345')
JWT_ALGORITHM = 'HS256'

# Configuración de correo (configurar según tu proveedor de email)
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
SMTP_USERNAME = os.getenv('SMTP_USERNAME', 'tu-email@gmail.com')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', 'tu-password')

# Credenciales de Grafana
GRAFANA_USERNAME = "admin"
GRAFANA_PASSWORD = "admin123"
GRAFANA_URL = "https://localhost:8443/grafana/login"

security = HTTPBearer()
thread_pool = ThreadPoolExecutor(max_workers=10)

# Modelos Pydantic
class CredentialsRequest(BaseModel):
    message: str = "Solicitud de credenciales de Grafana"

class CredentialsResponse(BaseModel):
    message: str
    email_sent: bool
    user_email: str
    grafana_url: str
    credentials_info: dict

# Función para verificar y decodificar JWT
def verify_jwt_token(token: str) -> dict:
    """Verificar y decodificar el token JWT"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
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

# Función para obtener usuario actual desde JWT
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Obtener información del usuario actual desde el JWT"""
    token = credentials.credentials
    payload = verify_jwt_token(token)
    return payload

# Función para enviar correo (síncrona)
def send_email_sync(recipient_email: str, recipient_name: str) -> bool:
    """Enviar correo con las credenciales de Grafana"""
    try:
        # Crear mensaje
        msg = MIMEMultipart()
        msg['From'] = SMTP_USERNAME
        msg['To'] = recipient_email
        msg['Subject'] = "Credenciales de Acceso a Grafana - Red de Contenedores"
        
        # Cuerpo del correo
        body = f"""
        Hola {recipient_name},

        Has solicitado las credenciales de acceso al dashboard de Grafana de la Red de Contenedores.

        Información de acceso:
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        🌐 URL: {GRAFANA_URL}
        👤 Usuario: {GRAFANA_USERNAME}
        🔐 Contraseña: {GRAFANA_PASSWORD}
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        Desde Grafana podrás:
        • Visualizar métricas de rendimiento de los contenedores
        • Monitorear el estado de la infraestructura
        • Crear dashboards personalizados
        • Configurar alertas

        IMPORTANTE: Mantén estas credenciales seguras y no las compartas.

        Saludos,
        Sistema de Red de Contenedores
        Generado el: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # Enviar correo
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        text = msg.as_string()
        server.sendmail(SMTP_USERNAME, recipient_email, text)
        server.quit()
        
        return True
        
    except Exception as e:
        print(f"Error enviando correo: {e}")
        return False

# Función asíncrona para enviar correo
async def send_email_async(recipient_email: str, recipient_name: str) -> bool:
    """Enviar correo de forma asíncrona"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(thread_pool, send_email_sync, recipient_email, recipient_name)

# Endpoints
@app.get("/")
async def root():
    return {
        "message": "API de Credenciales de Grafana",
        "status": "activo",
        "description": "Envía credenciales de Grafana a usuarios admin autenticados",
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check():
    """Endpoint de verificación de salud"""
    return {
        "status": "OK",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "grafana_credentials_api"
    }

@app.post("/send-credentials", response_model=CredentialsResponse)
async def send_grafana_credentials(
    request: CredentialsRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Enviar credenciales de Grafana por correo electrónico.
    Solo usuarios con rol 'admin' pueden acceder a este endpoint.
    """
    try:
        # Verificar que el usuario tenga rol de admin
        user_role = current_user.get('rol')
        if user_role != 'admin':
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acceso denegado. Se requiere rol 'admin' para acceder a esta API. Tu rol actual: '{user_role}'"
            )
        
        # Obtener información del usuario
        user_email = current_user.get('correo')
        user_name = current_user.get('nombre_completo', 'Usuario')
        
        if not user_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se pudo obtener el correo del usuario desde el token"
            )
        
        # Enviar correo con las credenciales
        email_sent = await send_email_async(user_email, user_name)
        
        if not email_sent:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al enviar el correo electrónico"
            )
        
        return CredentialsResponse(
            message=f"Las credenciales de Grafana han sido enviadas exitosamente a {user_email}",
            email_sent=True,
            user_email=user_email,
            grafana_url=GRAFANA_URL,
            credentials_info={
                "username": GRAFANA_USERNAME,
                "note": "La contraseña ha sido enviada por correo electrónico por seguridad"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error en send_grafana_credentials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor"
        )

@app.get("/verify-access")
async def verify_access(current_user: dict = Depends(get_current_user)):
    """
    Verificar si el usuario actual tiene acceso a la API (solo admins)
    """
    user_role = current_user.get('rol')
    if user_role != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Acceso denegado. Se requiere rol 'admin'. Tu rol actual: '{user_role}'"
        )
    
    return {
        "access_granted": True,
        "user_info": {
            "id": current_user.get('id'),
            "name": current_user.get('nombre_completo'),
            "email": current_user.get('correo'),
            "role": current_user.get('rol')
        },
        "message": "Usuario autorizado para acceder a las credenciales de Grafana"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5800)
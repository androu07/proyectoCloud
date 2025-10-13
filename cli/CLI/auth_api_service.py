"""
Servicio para comunicación con la API de autenticación externa
"""

import requests
import os
from typing import Optional, Dict
from dotenv import load_dotenv
import urllib3

# Deshabilitar advertencias de SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Cargar variables de entorno
load_dotenv()

def log_debug(msg):
    with open('auth_debug.log', 'a', encoding='utf-8') as f:
        f.write(msg + '\n')

log_debug('[IMPORT] auth_api_service.py importado')

class AuthAPIService:
    """Servicio para autenticación contra API externa"""
    
    ROLE_MAPPING = {
        'admin': 'admin',
        'cliente': 'cliente',
        'usuario_avanzado': 'usuario_avanzado'
    }
    
    def __init__(self):
        self.api_url = os.getenv('AUTH_API_URL', 'https://localhost:8443/auth')
        self.token = None
        self.user_data = None
        self.user_role = None
        
        log_debug(f"[DEBUG] API URL configurada: {self.api_url}")
    
    def login(self, correo: str, password: str) -> bool:
        log_debug(f"[LOGIN] INICIO método login para: {correo}")
        try:
            url = f"{self.api_url}/login"
            payload = {
                "correo": correo,
                "password": password
            }
        
            print(f"[DEBUG] URL: {url}")
            log_debug(f"[DEBUG] URL: {url}")
            print(f"[DEBUG] Intentando login con: {correo}")
            log_debug(f"[DEBUG] Intentando login con: {correo}")
            log_debug(f"[LOGIN] Entrando a login con correo: {correo}")
            
            response = requests.post(
                url,
                json=payload,
                timeout=10,
                verify=False
            )
            print(f"[DEBUG] Status Code: {response.status_code}")
            log_debug(f"[DEBUG] Status Code: {response.status_code}")
            print(f"[DEBUG] Respuesta: {response.text}")
            log_debug(f"[DEBUG] Respuesta: {response.text}")
            if response.status_code == 200:
                data = response.json()
                self.token = data.get('token')
                # Extraer user_info de la respuesta
                user_info = data.get('user_info', {})
                self.user_data = {
                    'correo': user_info.get('correo', correo),
                    'nombre': user_info.get('nombre', ''),
                    'apellidos': user_info.get('apellidos', ''),
                    'id': user_info.get('id', ''),
                    'rol': user_info.get('rol', 'cliente')
                }
                api_role = self.user_data.get('rol', '').lower()
                print(f"[DEBUG] API Role recibido: '{api_role}'")
                log_debug(f"[DEBUG] API Role recibido: '{api_role}'")
                self.user_role = self.ROLE_MAPPING.get(api_role, 'cliente')
                print(f"[DEBUG] Role mapeado: '{self.user_role}'")
                log_debug(f"[DEBUG] Role mapeado: '{self.user_role}'")
                print(f"[DEBUG] ✅ Login exitoso")
                log_debug(f"[DEBUG] ✅ Login exitoso")
                log_debug(f"[DEBUG] Usuario: {self.user_data.get('nombre', 'N/A')}")
                print(f"[DEBUG] Rol final: {self.user_role}")
                log_debug(f"[DEBUG] Rol final: {self.user_role}")
                return True
            print(f"[DEBUG] ❌ Login falló con status code: {response.status_code}")
            log_debug(f"[DEBUG] ❌ Login falló con status code: {response.status_code}")
            print(f"[DEBUG] Respuesta: {response.text}")
            log_debug(f"[DEBUG] Respuesta: {response.text}")
            print("[ERROR] ❌ El logueo no fue correcto, verifique su usuario y contraseña.")
            input("[INFO] Presione Enter para intentar nuevamente o Ctrl+C para salir...")
            return False
            
        except requests.exceptions.ConnectionError as e:
            log_debug(f"[ERROR] No se puede conectar con la API: {e}")
            log_debug("[INFO] ¿Está el túnel SSH activo?")
            return False
        except requests.exceptions.RequestException as e:
            log_debug(f"[ERROR] Error en la solicitud HTTP: {e}")
            return False
        except Exception as e:
            log_debug(f"[ERROR] Error desconocido en login: {e}")
            return False

    
    def verify_token(self) -> bool:
        if not self.token:
            log_debug("[ERROR] No se ha proporcionado un token.")
            return False
        
        try:
            url = f"{self.api_url}/verify-token"
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=5,
                verify=False
            )
            return response.status_code == 200
        except:
            return False
    
    def check_health(self) -> bool:
        try:
            url = f"{self.api_url}/health"
            response = requests.get(url, timeout=5, verify=False)
            return response.status_code == 200
        except:
            return False
    
    def get_user_data(self) -> Optional[Dict]:
        return self.user_data
    
    def get_user_role(self) -> Optional[str]:
        return self.user_role
    
    def get_user_email(self) -> Optional[str]:
        return self.user_data.get('email') if self.user_data else None
    
    def get_user_name(self) -> Optional[str]:
        return self.user_data.get('nombre') if self.user_data else None
    
    def is_authenticated(self) -> bool:
        return self.token is not None
    
    def has_role(self, role: str) -> bool:
        return self.user_role == role.lower()
    
    def logout(self):
        log_debug("[DEBUG] Cerrando sesión...")
        self.token = None
        self.user_data = None
        self.user_role = None
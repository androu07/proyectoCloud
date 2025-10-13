"""
Servicio para comunicación con la API de autenticación externa
Adaptado para trabajar con HTTPS y manejo de roles
"""

import requests
import os
from typing import Optional, Dict
from dotenv import load_dotenv
import urllib3

# Deshabilitar advertencias de SSL para desarrollo (localhost)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Cargar variables de entorno
load_dotenv()


class AuthAPIService:
    """Servicio para autenticación contra API externa con soporte de roles"""
    
    # Mapeo de roles de la API al sistema local
    ROLE_MAPPING = {
        'admin': 'admin',
        'cliente': 'cliente',
        'usuario_avanzado': 'usuario_avanzado'
    }
    
    def __init__(self):
        # Usar HTTPS en puerto 8443
        self.api_url = os.getenv('AUTH_API_URL', 'https://localhost:8443/auth')
        self.token = None
        self.user_data = None
        self.user_role = None
        
        # DEBUG: Mostrar URL que se está usando
        print(f"[DEBUG] API URL configurada: {self.api_url}")
    
    def login(self, correo: str, password: str) -> bool:
        """
        Autenticar contra la API externa
        
        Args:
            correo: Email del usuario
            password: Contraseña
            
        Returns:
            True si el login fue exitoso
        """
        try:
            url = f"{self.api_url}/login"
            payload = {
                "correo": correo,
                "password": password
            }
            
            # DEBUG: Mostrar lo que se está enviando
            print(f"[DEBUG] URL: {url}")
            print(f"[DEBUG] Payload: {{correo: {correo}, password: ***}}")
            
            # verify=False para desarrollo con certificados self-signed
            response = requests.post(
                url,
                json=payload,
                timeout=10,
                verify=False  # IMPORTANTE: En producción usar certificados válidos
            )
            
            # DEBUG: Mostrar respuesta
            print(f"[DEBUG] Status Code: {response.status_code}")
            print(f"[DEBUG] Response: {response.text[:200]}...")
            
            if response.status_code == 200:
                data = response.json()
                
                # Extraer token y datos del usuario
                self.token = data.get('token')
                self.user_data = data.get('user_info', {})
                
                # Extraer y mapear el rol
                api_role = self.user_data.get('rol', '').lower()
                print(f"[DEBUG] API Role recibido: '{api_role}'")
                self.user_role = self.ROLE_MAPPING.get(api_role, 'cliente')
                print(f"[DEBUG] Role mapeado: '{self.user_role}'")
                
                print(f"[DEBUG] ✅ Login exitoso")
                print(f"[DEBUG] Token recibido: {self.token[:20]}..." if self.token else "[DEBUG] No token")
                print(f"[DEBUG] Usuario: {self.user_data.get('nombre', 'N/A')}")
                print(f"[DEBUG] Email: {self.user_data.get('email', 'N/A')}")
                print(f"[DEBUG] Rol final: {self.user_role}")
                
                return True
            
            print(f"[DEBUG] ❌ Login falló con status {response.status_code}")
            return False
            
        except requests.exceptions.SSLError as e:
            print(f"[ERROR] Error de SSL (certificado): {e}")
            print("[INFO] Asegúrate de que el servidor esté usando HTTPS correctamente")
            return False
        except requests.exceptions.ConnectionError as e:
            print(f"[ERROR] No se puede conectar con la API: {e}")
            print(f"[INFO] Verifica que el servicio esté corriendo en {self.api_url}")
            return False
        except requests.exceptions.Timeout as e:
            print(f"[ERROR] Timeout al conectar con la API: {e}")
            return False
        except Exception as e:
            print(f"[ERROR] Error inesperado en login: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def verify_token(self) -> bool:
        """
        Verificar si el token actual es válido
        
        Returns:
            True si el token es válido
        """
        if not self.token:
            print("[DEBUG] No hay token para verificar")
            return False
        
        try:
            url = f"{self.api_url}/verify-token"
            
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.token}"
                },
                timeout=5,
                verify=False  # Para desarrollo
            )
            
            is_valid = response.status_code == 200
            print(f"[DEBUG] Token válido: {is_valid}")
            
            return is_valid
            
        except Exception as e:
            print(f"[ERROR] Error verificando token: {e}")
            return False
    
    def check_health(self) -> bool:
        """
        Verificar si la API de autenticación está disponible
        
        Returns:
            True si la API responde correctamente
        """
        try:
            url = f"{self.api_url}/health"
            
            response = requests.get(
                url,
                timeout=5,
                verify=False
            )
            
            is_healthy = response.status_code == 200
            print(f"[DEBUG] API Health Check: {'✅ OK' if is_healthy else '❌ FAIL'}")
            
            return is_healthy
            
        except Exception as e:
            print(f"[ERROR] API no disponible: {e}")
            return False
    
    def get_user_data(self) -> Optional[Dict]:
        """
        Obtiene los datos del usuario autenticado
        
        Returns:
            Diccionario con datos del usuario o None
        """
        return self.user_data
    
    def get_user_role(self) -> Optional[str]:
        """
        Obtiene el rol del usuario autenticado
        
        Returns:
            String con el rol del usuario o None
        """
        return self.user_role
    
    def get_user_email(self) -> Optional[str]:
        """
        Obtiene el email del usuario autenticado
        
        Returns:
            Email del usuario o None
        """
        return self.user_data.get('email') if self.user_data else None
    
    def get_user_name(self) -> Optional[str]:
        """
        Obtiene el nombre del usuario autenticado
        
        Returns:
            Nombre del usuario o None
        """
        return self.user_data.get('nombre') if self.user_data else None
    
    def is_authenticated(self) -> bool:
        """
        Verifica si hay un usuario autenticado
        
        Returns:
            True si hay sesión activa
        """
        return self.token is not None and self.user_data is not None
    
    def has_role(self, role: str) -> bool:
        """
        Verifica si el usuario tiene un rol específico
        
        Args:
            role: Rol a verificar ('admin', 'cliente', 'usuario_avanzado')
            
        Returns:
            True si el usuario tiene ese rol
        """
        return self.user_role == role.lower()
    
    def logout(self):
        """Cerrar sesión y limpiar datos"""
        print("[DEBUG] Cerrando sesión...")
        self.token = None
        self.user_data = None
        self.user_role = None
        print("[DEBUG] ✅ Sesión cerrada")


# Funciones de utilidad para usar en el CLI

def login_prompt(auth_service: AuthAPIService) -> bool:
    """
    Muestra un prompt de login y autentica al usuario
    
    Args:
        auth_service: Instancia del servicio de autenticación
        
    Returns:
        True si el login fue exitoso
    """
    print("\n" + "="*50)
    print("  🔐 PUCP Cloud Orchestrator - Login")
    print("="*50)
    
    correo = input("📧 Email: ").strip()
    
    # Importar getpass para ocultar password
    from getpass import getpass
    password = getpass("🔑 Password: ")
    
    print("\n⏳ Autenticando...")
    
    if auth_service.login(correo, password):
        print(f"\n✅ Bienvenido, {auth_service.get_user_name()}!")
        print(f"👤 Rol: {auth_service.get_user_role()}")
        return True
    else:
        print("\n❌ Credenciales inválidas")
        return False


def require_role(auth_service: AuthAPIService, required_role: str) -> bool:
    """
    Verifica si el usuario tiene el rol requerido
    
    Args:
        auth_service: Instancia del servicio de autenticación
        required_role: Rol requerido
        
    Returns:
        True si el usuario tiene el rol necesario
    """
    if not auth_service.is_authenticated():
        print("❌ Debe iniciar sesión primero")
        return False
    
    if not auth_service.has_role(required_role):
        print(f"❌ Acceso denegado. Se requiere rol: {required_role}")
        print(f"   Tu rol actual: {auth_service.get_user_role()}")
        return False
    
    return True


# Ejemplo de uso
if __name__ == "__main__":
    # Crear instancia del servicio
    auth = AuthAPIService()
    
    # Verificar salud de la API
    print("\n🏥 Verificando disponibilidad de la API...")
    if not auth.check_health():
        print("⚠️  La API de autenticación no está disponible")
        print("💡 Asegúrate de que el servicio Docker esté corriendo:")
        print("   sudo docker compose up -d")
        exit(1)
    
    # Prompt de login
    if login_prompt(auth):
        # Verificar token
        print("\n🔍 Verificando token...")
        if auth.verify_token():
            print("✅ Token válido")
        
        # Mostrar información del usuario
        print("\n" + "="*50)
        print("📋 Información de sesión:")
        print(f"   Nombre: {auth.get_user_name()}")
        print(f"   Email: {auth.get_user_email()}")
        print(f"   Rol: {auth.get_user_role()}")
        print("="*50)
        
        # Ejemplo de verificación de roles
        print("\n🔐 Verificando permisos...")
        if require_role(auth, 'admin'):
            print("✅ Tienes permisos de administrador")
        else:
            print("ℹ️  No tienes permisos de administrador")
        
        # Cerrar sesión
        auth.logout()
    else:
        print("\n⚠️  No se pudo iniciar sesión")
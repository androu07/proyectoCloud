"""
Sistema de Orquestación PUCP Cloud
Main principal con autenticación externa vía API
"""

from core.slice_manager.manager import SliceManager
from core.auth_manager import AuthManager
from core.slice_manager.models import UserRole, SliceCreate, TopologyType
from shared.ui_helpers import print_header
from shared.colors import Colors
from shared.topology.ascii_drawer import draw_topology
from roles.admin.admin_menu import admin_menu
from roles.cliente.cliente_menu import cliente_menu
from shared.ui_styles import print_banner, print_credential, print_section
from shared.ui_helpers import login_screen

# Importar el servicio de API externa
from auth_api_service import AuthAPIService
from getpass import getpass
import sys


# ============================================================================
# FUNCIONES DE LOGIN CON API EXTERNA
# ============================================================================


def check_api_availability(auth_service: AuthAPIService) -> bool:
    """
    Verificar si la API de autenticación está disponible
    
    Args:
        auth_service: Instancia del servicio de autenticación
        
    Returns:
        True si la API está disponible
    """
    print(f"\n{Colors.CYAN}⏳ Verificando API de autenticación...{Colors.RESET}")
    
    if auth_service.check_health():
        print(f"{Colors.GREEN}✅ API disponible - Usando autenticación externa{Colors.RESET}\n")
        return True
    else:
        print(f"{Colors.YELLOW}⚠️  API de autenticación no disponible{Colors.RESET}")
        print(f"{Colors.CYAN}� Continuando con autenticación local{Colors.RESET}\n")
        return False

def login_with_api(auth_manager: AuthManager, auth_service: AuthAPIService) -> bool:
    """Realizar login con API externa o local como fallback"""
    
    # Verificar si la API está disponible
    api_available = check_api_availability(auth_service)
    
    max_intentos = 3
    
    for intento in range(max_intentos):
        # Llamar a la función de pantalla de login SOLO para pedir datos
        correo, password = login_screen(auth_manager)
        if not correo or not password:
            print(f"\n{Colors.RED}❌ Email y contraseña son requeridos{Colors.ENDC}")
            continue
        
        # Intentar autenticación con API si está disponible
        if api_available:
            print(f"\n{Colors.CYAN}⏳ Autenticando con API externa...{Colors.ENDC}")
            try:
                if auth_service.login(correo, password):
                    user_data = auth_service.get_user_data()
                    if user_data:
                        from core.slice_manager.models import UserRole
                        
                        # Convertir rol de string a enum
                        role_str = user_data.get('rol', 'cliente').lower()
                        role = UserRole.ADMIN if role_str == 'admin' else UserRole.CLIENTE
                        
                        # Login exitoso con API
                        auth_manager.external_login(
                            email=user_data.get('correo', correo),
                            name=user_data.get('nombre', ''),
                            role=role,
                            token=auth_service.token,
                            api_data=user_data
                        )
                        print(f"\n{Colors.GREEN}✅ Login exitoso con API como {role.value}{Colors.ENDC}")
                        return True
                    else:
                        print(f"\n{Colors.RED}❌ No se pudieron obtener datos del usuario{Colors.ENDC}")
                else:
                    print(f"\n{Colors.RED}❌ Credenciales inválidas en API{Colors.ENDC}")
            except Exception as e:
                print(f"\n{Colors.RED}❌ Error de conexión con API: {e}{Colors.ENDC}")
                api_available = False  # Marcar API como no disponible para el resto de intentos
        
        # Si la API no está disponible o falló, usar autenticación local
        if not api_available:
            print(f"\n{Colors.CYAN}⏳ Usando autenticación local...{Colors.ENDC}")
            
            # Autenticación local simple (cualquier email/password válido)
            if correo and password:
                from core.slice_manager.models import UserRole
                
                # Determinar rol basado en email (simple lógica local)
                role = UserRole.ADMIN if ('admin' in correo.lower() or 
                                        'rodrigolujanf28@gmail.com' == correo.lower()) else UserRole.CLIENTE
                
                # Crear usuario local sin API
                user_data = {
                    'correo': correo,
                    'nombre': correo.split('@')[0],  # Usar parte antes del @
                    'rol': 'admin' if role == UserRole.ADMIN else 'cliente'
                }
                
                # Usar el método external_login para crear el usuario correctamente
                auth_manager.external_login(
                    email=user_data.get('correo', correo),
                    name=user_data.get('nombre', ''),
                    role=role,
                    token='local_token',  # Token local ficticio
                    api_data=user_data
                )
                print(f"\n{Colors.GREEN}✅ Login local exitoso como {role.value}{Colors.ENDC}")
                return True
    
    print(f"\n{Colors.RED}❌ Máximo número de intentos alcanzado{Colors.ENDC}")
    return False

def login_screen_api(auth_manager: AuthManager, auth_service: AuthAPIService):
    """
    Pantalla de login usando API externa
    
    Args:
        auth_manager: Gestor de autenticación local
        auth_service: Servicio de API externa
    """
    while not auth_manager.current_user:
        if not login_with_api(auth_manager, auth_service):
            print(f"\n{Colors.YELLOW}¿Desea intentar nuevamente? (s/n): {Colors.RESET}", end='')
            if input().lower() not in ['s', 'si', 'yes', 'y']:
                print(f"\n{Colors.CYAN}Saliendo del sistema...{Colors.RESET}")
                sys.exit(0)


# ============================================================================
# FUNCIÓN PRINCIPAL
# ============================================================================

def main():
    """Función principal del sistema con autenticación externa"""
    
    # Inicializar componentes
    slice_manager = SliceManager()
    auth_manager = AuthManager()
    auth_service = AuthAPIService()  # Servicio de API externa
    
    try:
        while True:
            # Login con API externa
            if not auth_manager.current_user:
                login_screen_api(auth_manager, auth_service)
            
            # Verificar que el token siga siendo válido (solo si usamos API externa)
            if auth_manager.current_user and hasattr(auth_service, 'token') and auth_service.token and auth_service.token != 'local_token':
                if not auth_service.verify_token():
                    print(f"\n{Colors.YELLOW}⚠️  Su sesión ha expirado. Por favor, inicie sesión nuevamente.{Colors.RESET}")
                    auth_manager.logout()
                    auth_service.logout()
                    continue
            
            # Redirigir según rol
            if auth_manager.current_user:
                try:
                    if auth_manager.current_user.role == UserRole.ADMIN:
                        admin_menu(auth_manager, slice_manager, auth_service)

                    elif auth_manager.current_user.role == UserRole.CLIENTE:
                        cliente_menu(auth_manager, slice_manager, auth_service)

                except KeyboardInterrupt:
                    print(f"\n\n{Colors.YELLOW}Operación cancelada por el usuario{Colors.RESET}")
                    respuesta = input(f"\n{Colors.CYAN}¿Desea cerrar sesión? (s/n): {Colors.RESET}").lower()
                    if respuesta in ['s', 'si', 'yes', 'y']:
                        auth_manager.logout()
                        auth_service.logout()
                        print(f"{Colors.GREEN}✅ Sesión cerrada{Colors.RESET}")
                    continue
    
    except KeyboardInterrupt:
        print(f"\n\n{Colors.CYAN}Saliendo del sistema...{Colors.RESET}")
        if auth_manager.current_user:
            auth_service.logout()
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.RED}❌ Error inesperado: {e}{Colors.RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
import os
import time
import getpass 
from .colors import Colors
"""
Utilidades compartidas para la interfaz de usuario
"""

import os
import time
from .colors import Colors

# ============================================================================
# COLORES PARA LA TERMINAL
# ============================================================================
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    OKGREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

# ============================================================================
# FUNCIONES DE INTERFAZ DE USUARIO
# ============================================================================

def clear_screen():
    """Limpiar la pantalla de la terminal"""
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header(user=None):
    """Imprimir encabezado principal"""
    clear_screen()
    print(Colors.BOLD + Colors.BLUE + "="*60 + Colors.ENDC)
    print(Colors.BOLD + Colors.GREEN + "     BIENVENIDO A PUCP CLOUD ORCHESTRATOR" + Colors.ENDC)
    print(Colors.BOLD + Colors.BLUE + "="*60 + Colors.ENDC)
    if user:
        print(f"  Usuario: {Colors.YELLOW}{user.username}{Colors.ENDC} | Rol: {Colors.GREEN}{user.role.value.upper()}{Colors.ENDC}")
        print(Colors.BLUE + "-"*60 + Colors.ENDC)


def login_screen(auth_manager) -> tuple:
    """Pantalla de login: solo pide correo y password y los retorna"""
    print_header()
    print("\n" + Colors.BOLD + "  AUTENTICACIÓN" + Colors.ENDC)
    print("  " + "-"*30)
    print("\n  " + Colors.YELLOW + "Autenticación con API Externa" + Colors.ENDC)
    print("  Ingrese sus credenciales:")
    print()
    correo = input("  Email: ")
    password = getpass.getpass("  Contraseña: ")
    return correo, password

def pause(message: str = "\n  Presione Enter para continuar..."):
    """Pausa la ejecución hasta que el usuario presione Enter"""
    input(message)


def show_success(message: str):
    """Muestra un mensaje de éxito"""
    print(Colors.GREEN + f"\n  ✓ {message}" + Colors.ENDC)


def show_error(message: str):
    """Muestra un mensaje de error"""
    print(Colors.RED + f"\n  ✗ {message}" + Colors.ENDC)


def show_info(message: str):
    """Muestra un mensaje informativo"""
    print(Colors.BLUE + f"\n  ℹ {message}" + Colors.ENDC)


def get_menu_choice() -> str:
    """Solicita al usuario que seleccione una opción del menú"""
    return input("\n  Seleccione opción: ")


def confirm_action(message: str) -> bool:
    """Solicita confirmación del usuario"""
    response = input(f"\n  {message} (s/n): ").lower()
    return response == 's'
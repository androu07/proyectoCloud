"""
Estilos y formatos para el CLI
"""

from shared.colors import Colors


def print_banner(texto, color=Colors.CYAN):
    """Banner principal"""
    print("\n" + "="*70)
    print(f"{color}{texto:^70}{Colors.ENDC}")
    print("="*70 + "\n")


def print_section(texto, color=Colors.YELLOW):
    """Sección"""
    print(f"\n{color}{texto}{Colors.ENDC}")
    print("-"*40)


def print_option(numero, texto, color=Colors.GREEN):
    """Opción de menú"""
    print(f"{color}  {numero}. {texto}{Colors.ENDC}")


def print_credential(usuario, password):
    """Mostrar credencial"""
    print(f"{Colors.GREEN}  • {usuario} / {password}{Colors.ENDC}")


def print_separator():
    """Separador"""
    print("="*70)


def print_subseparator():
    """Sub-separador"""
    print("-"*70)
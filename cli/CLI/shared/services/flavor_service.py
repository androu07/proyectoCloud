"""
Servicio de gestión de flavors (tamaños de VMs)
"""

from shared.ui_helpers import show_error


def get_flavor_specs(flavor_name: str) -> dict:
    """
    Obtener especificaciones de un flavor
    Args:
        flavor_name: Nombre del flavor
    Returns:
        Diccionario con especificaciones (cpu, memory, disk)
    """
    # Flavors personalizados según requerimiento del usuario
    flavors = {
        'f1': {'cpu': 1, 'memory': 500, 'disk': 1},
        'f2': {'cpu': 1, 'memory': 500, 'disk': 2},
        'f3': {'cpu': 1, 'memory': 500, 'disk': 2.5},
        'f4': {'cpu': 1, 'memory': 750, 'disk': 1},
        'f5': {'cpu': 1, 'memory': 750, 'disk': 2},
        'f6': {'cpu': 1, 'memory': 750, 'disk': 2.5}
    }
    return flavors.get(flavor_name, flavors['f1'])


def select_flavor() -> str:
    """
    Seleccionar un flavor para las VMs de forma interactiva
    Returns:
        Nombre del flavor seleccionado
    """
    print("\n  Flavors disponibles:")
    print("  1. 1 core | 500M RAM | 1G Disk")
    print("  2. 1 core | 500M RAM | 2G Disk")
    print("  3. 1 core | 500M RAM | 2.5G Disk")
    print("  4. 1 core | 750M RAM | 1G Disk")
    print("  5. 1 core | 750M RAM | 2G Disk")
    print("  6. 1 core | 750M RAM | 2.5G Disk")

    choice = input("\n  Seleccione flavor (1-6): ")

    flavors = ['f1', 'f2', 'f3', 'f4', 'f5', 'f6']

    if choice.isdigit() and 1 <= int(choice) <= 6:
        return flavors[int(choice) - 1]

    show_error("Opción inválida, usando 'f1' por defecto")
    return 'f1'  # Default


def list_flavors() -> dict:
    """
    Obtiene la lista completa de flavors disponibles
    Returns:
        Diccionario con todos los flavors
    """
    return {
        'f1': {'cpu': 1, 'memory': 500, 'disk': 1},
        'f2': {'cpu': 1, 'memory': 500, 'disk': 2},
        'f3': {'cpu': 1, 'memory': 500, 'disk': 2.5},
        'f4': {'cpu': 1, 'memory': 750, 'disk': 1},
        'f5': {'cpu': 1, 'memory': 750, 'disk': 2},
        'f6': {'cpu': 1, 'memory': 750, 'disk': 2.5}
    }
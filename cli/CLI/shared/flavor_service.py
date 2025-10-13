# --- FUNCIONES DE TOPOLOGÍA MIXTA Y DETALLES MEJORADOS ---
def get_flavor_specs(flavor_name):
    """Obtener especificaciones de un flavor"""
    flavors = {
        'tiny': {'cpu': 1, 'memory': 512, 'disk': 1},
        'small': {'cpu': 1, 'memory': 2048, 'disk': 20},
        'medium': {'cpu': 2, 'memory': 4096, 'disk': 40},
        'large': {'cpu': 4, 'memory': 8192, 'disk': 80},
        'xlarge': {'cpu': 8, 'memory': 16384, 'disk': 160}
    }
    return flavors.get(flavor_name, flavors['small'])

def select_flavor():
    """Seleccionar un flavor para las VMs"""
    print("\n  Flavors disponibles:")
    print("  1. Tiny   (1 vCPU, 512MB RAM, 1GB Disk), Cirros-0.5.1")
    print("  2. Small  (1 vCPU, 2GB RAM, 20GB Disk), Cirros-0.5.1")
    print("  3. Medium (2 vCPU, 4GB RAM, 40GB Disk), Cirros-0.5.1")
    print("  4. Large  (4 vCPU, 8GB RAM, 80GB Disk), Cirros-0.5.1")
    print("  5. XLarge (8 vCPU, 16GB RAM, 160GB Disk), Cirros-0.5.1")
    choice = input("\n  Seleccione flavor (1-5): ")
    flavors = ['tiny', 'small', 'medium', 'large', 'xlarge']
    if choice.isdigit() and 1 <= int(choice) <= 5:
        return flavors[int(choice) - 1]
    return 'small'  # Default
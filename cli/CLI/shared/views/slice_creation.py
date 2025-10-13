

"""Vista para creación de slices"""

from shared.ui_helpers import print_header, pause, show_success, show_error
from shared.colors import Colors
from shared.topology.ascii_drawer import draw_topology
from core.slice_manager.models import SliceCreate, TopologyType, VM
from shared.services.flavor_service import select_flavor, get_flavor_specs

def create_slice_basic(slice_manager, user):
    """Crear slice básico (CLIENTE)"""
    print_header(user)
    print(Colors.BOLD + "\n  CREAR SLICE" + Colors.ENDC)
    
    name = input("\n  Nombre del slice: ")
    # Validar que no exista un slice con el mismo nombre y estado activo/creating
    # Filtrar correctamente por usuario y nombre
    existing = [s for s in slice_manager.get_slices() if s.name == name and s.owner == user.username and s.status in ("creating", "active")]
    if existing:
        print(Colors.RED + f"\n  Ya existe un slice activo/creando con ese nombre." + Colors.ENDC)
        input("\n  Presione Enter para continuar...")
        return
    
    print("\nTopologías disponibles:")
    print("1. Lineal")
    print("2. Anillo")
    print("3. Árbol")
    print("4. Malla")
    print("5. Bus")
    
    topology_choice = input("Seleccione topología (1-5): ")
    topologies = {
        '1': 'lineal',
        '2': 'anillo',
        '3': 'arbol',
        '4': 'malla',
        '5': 'bus'
    }
    
    topology = topologies.get(topology_choice, 'lineal')
    
    num_vms = int(input("  Número de VMs: "))
    vms_data = []
    for i in range(num_vms):
        print(f"\n  VM {i+1}:")
        cpu = int(input(f"    CPUs para VM {i+1} (default 1): ") or "1")
        memory = int(input(f"    Memoria MB para VM {i+1} (default 1024): ") or "1024")
        disk = int(input(f"    Disco GB para VM {i+1} (default 10): ") or "10")
        vms_data.append({
            'name': f"VM{i+1}",
            'cpu': cpu,
            'memory': memory,
            'disk': disk
        })

    try:
        topology_enum = TopologyType(topology)
    except ValueError:
        topology_enum = TopologyType.LINEAR

    # SliceCreate no soporta vms personalizados, así que pasamos solo el número y la primera VM como ejemplo
    slice_obj = SliceCreate(
        name=name,
        topology=topology_enum,
        num_vms=num_vms,
        cpu=vms_data[0]['cpu'],
        memory=vms_data[0]['memory'],
        disk=vms_data[0]['disk']
    )

    # Crear lista de VMs personalizadas
    from slice_manager.models import VM
    from slice_manager.models import VM
    vms_override = []
    for i in range(num_vms):
        vms_override.append(VM(
            id=f"slice_temp_vm_{i}",
            name=f"VM{i+1}",
            cpu=vms_data[i]['cpu'],
            memory=vms_data[i]['memory'],
            disk=vms_data[i]['disk'],
            status="pending",
            flavor="small"
        ))

    # Crear slice pasando vms_override
    slice = slice_manager.create_slice(slice_obj, user.username, vms_override=vms_override)

    print(Colors.GREEN + f"\n  ✓ Slice creado: {slice.id}" + Colors.ENDC)

    # Mostrar dibujo de la topología
    draw_topology(slice.topology, len(slice.vms))

    input("\n  Presione Enter para continuar...")



def create_mixed_slice(slice_manager, user):
    """Crear un slice con topología mixta"""
    print_header(user)
    print(Colors.BOLD + "\n  CREAR SLICE CON TOPOLOGÍA MIXTA" + Colors.ENDC)
    name = input("\n  Nombre del slice: ")
    topology_segments = []
    # Primera topología (obligatoria)
    segment = create_topology_segment(1)
    topology_segments.append(segment)
    # Preguntar si quiere añadir más topologías (máximo 4)
    for i in range(2, 5):  # Permite hasta 4 topologías
        add_more = input(f"\n  ¿Desea añadir otra topología al slice? (s/n): ")
        if add_more.lower() != 's':
            break
        segment = create_topology_segment(i)
        topology_segments.append(segment)
    # Crear el slice con los segmentos de topología
    slice_data = {
        'name': name,
        'topology': 'mixta',
        'topology_segments': topology_segments
    }
    slice = slice_manager.create_mixed_slice(slice_data, user.username)
    print(Colors.GREEN + f"\n  ✓ Slice mixto creado: {slice.id}" + Colors.ENDC)
    print(f"  Total de topologías: {len(topology_segments)}")
    print(f"  Total de VMs: {sum(seg['num_vms'] for seg in topology_segments)}")
    input("\n  Presione Enter para continuar...")


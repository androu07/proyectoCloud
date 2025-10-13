def create_topology_segment(segment_number):
    """Crear un segmento de topología"""
    print(f"\n  --- TOPOLOGÍA {segment_number} ---")
    print("  Tipos de topología:")
    print("  1. VM Individual")
    print("  2. Lineal")
    print("  3. Anillo")
    print("  4. Árbol")
    print("  5. Malla")
    print("  6. Bus")
    topo_choice = input("  Seleccione tipo (1-6): ")
    topo_types = {
        '1': 'single_vm',
        '2': 'lineal',
        '3': 'anillo',
        '4': 'arbol',
        '5': 'malla',
        '6': 'bus'
    }
    topology_type = topo_types.get(topo_choice, 'lineal')
    # Determinar número de VMs según la topología
    if topology_type == 'single_vm':
        num_vms = 1
    else:
        if topology_type == 'lineal':
            print("  Número de VMs (2-10): ", end="")
            num_vms = int(input())
            num_vms = max(2, min(10, num_vms))
        elif topology_type == 'anillo':
            print("  Número de VMs (3-10): ", end="")
            num_vms = int(input())
            num_vms = max(3, min(10, num_vms))
        else:
            print("  Número de VMs (2-10): ", end="")
            num_vms = int(input())
            num_vms = max(2, min(10, num_vms))
    # Seleccionar flavor
    flavor = select_flavor()
    return {
        'type': topology_type,
        'num_vms': num_vms,
        'flavor': flavor
    }
def ver_detalles_slice(slice_manager, user=None):
    """Permite seleccionar y ver detalles completos de un slice, incluyendo el dibujo de la topología"""
    if user:
        slices = [s for s in slice_manager.get_slices() if getattr(s, 'usuario', None) == user.username]
    else:
        slices = slice_manager.get_slices()
    
    if not slices:
        print("\nNo hay slices disponibles.")
        input("Presione Enter para continuar...")
        return

    print("\nSlices disponibles:")
    for i, s in enumerate(slices, 1):
        print(f"  {i}. {s.name} (ID: {s.id})")

    choice = input("\nSeleccione el número del slice (0 para cancelar): ")
    if choice == '0' or not choice.isdigit():
        return
    
    idx = int(choice) - 1
    if idx < 0 or idx >= len(slices):
        print("Opción inválida.")
        return
    
    s = slices[idx]
    print(f"\n{'='*40}\nDETALLES DEL SLICE\n{'='*40}")
    print(f"ID: {s.id}")
    print(f"Nombre: {s.name}")
    print(f"Topología: {s.topology.value}")
    # print(f"Propietario: {s.owner}")
    print(f"Creado: {s.created_at}")
    print(f"Estado: {getattr(s, 'status', 'N/A')}")
    print(f"VMs: {len(s.vms)}")
    print(f"CPU por VM: {s.vms[0].cpu if s.vms else 'N/A'}")
    print(f"Memoria por VM: {s.vms[0].memory if s.vms else 'N/A'} MB")
    print(f"Disco por VM: {s.vms[0].disk if s.vms else 'N/A'} GB")
    
    print(f"\n--- Dibujo de la topología (ASCII) ---")
    draw_topology(s.topology.value, len(s.vms))
    
    print(f"\n¿Desea ver la topología en modo gráfico? (s/n): ", end="")
    ver_grafico = input().lower()
    if ver_grafico == 's':
        draw_topology_graph(s.topology.value, len(s.vms))
    
    print(f"\nMáquinas Virtuales:")
    for vm in s.vms:
        print(f"  - {vm.name} | CPU: {vm.cpu} | RAM: {vm.memory}MB | Disco: {vm.disk}GB | Estado: {getattr(vm, 'status', 'N/A')}")
    
    input("\nPresione Enter para continuar...")

def show_slice_details_enhanced(slice_manager, user=None):
    """Mostrar detalles mejorados del slice con conexiones"""
    print_header(user)
    print(Colors.BOLD + "\n  DETALLES DE SLICE" + Colors.ENDC)
    if user:
        slices = [s for s in slice_manager.get_slices() if getattr(s, 'usuario', None) == user.username]
    else:
        slices = slice_manager.list_slices()
    if not slices:
        print("\n  No hay slices disponibles")
        input("\n  Presione Enter para continuar...")
        return
    # Mostrar lista de slices
    print("\n  Slices disponibles:")
    for i, s in enumerate(slices, 1):
        print(f"  {i}. {s.name} ({s.id})")
    choice = input("\n  Seleccione slice (0 para cancelar): ")
    if choice == '0' or not choice.isdigit():
        return
    idx = int(choice) - 1
    if idx < 0 or idx >= len(slices):
        print("  Opción inválida")
        return
    slice = slices[idx]
    # Mostrar información general
    print(f"\n{'='*50}")
    print(f"  SLICE: {slice.name}")
    print(f"{'='*50}")
    print(f"  ID: {slice.id}")
    print(f"  Propietario: {slice.owner}")
    topo_type = slice.topology.value if hasattr(slice.topology, 'value') else slice.topology
    print(f"  Topología: {topo_type.capitalize()}")
    print(f"  Estado: {slice.status}")

    # Opción para mostrar imagen de la topología
    print("\n  Opciones de visualización:")
    print("  1. Ver topología como imagen (grafo)")
    print("  0. Volver")
    opt = input("\n  Seleccione opción: ")
    if opt == '1':
        # Si es Enum, usar .value, si es str, usar directamente
        topo_type = slice.topology.value if hasattr(slice.topology, 'value') else slice.topology
        draw_topology_graph(topo_type, len(slice.vms))
        input("\n  Presione Enter para continuar...")
    print(f"  Creado: {slice.created_at}")
    # Mostrar enlaces según la topología
    print(f"\n  Enlaces:")
    print("  +---------+---------+")
    print("  | nodo1   | nodo2   |")
    print("  +---------+---------+")
    topo_type = slice.topology.value if hasattr(slice.topology, 'value') else slice.topology
    if topo_type == 'lineal':
        for i in range(len(slice.vms) - 1):
            print(f"  | VM{i}     | VM{i+1}     |")
    elif topo_type == 'anillo':
        for i in range(len(slice.vms)):
            next_vm = (i + 1) % len(slice.vms)
            print(f"  | VM{i}     | VM{next_vm}     |")
    elif topo_type == 'malla':
        for i in range(len(slice.vms)):
            for j in range(i + 1, len(slice.vms)):
                print(f"  | VM{i}     | VM{j}     |")
    elif topo_type == 'arbol':
        # Árbol binario simple
        for i in range(1, len(slice.vms)):
            parent = (i - 1) // 2
            print(f"  | VM{parent}     | VM{i}     |")
    elif topo_type == 'bus':
        for i in range(len(slice.vms)):
            print(f"  | Bus     | VM{i}     |")
    elif topo_type == 'mixta':
        print(f"\n  Enlaces por segmentos:")
        # Mostrar las conexiones de cada segmento
        current_vm = 0
        
        # Primer segmento (lineal con 2 VMs)
        print("\n  Segmento 1 (Lineal):")
        print(f"  | VM{current_vm}     | VM{current_vm+1}     |")
        
        # Segundo segmento (anillo con 4 VMs)
        print("\n  Segmento 2 (Anillo):")
        start_vm = current_vm + 2
        for i in range(4):
            next_vm = start_vm + ((i + 1) % 4)
            print(f"  | VM{start_vm + i}     | VM{next_vm}     |")
        
        # Conexión entre segmentos
        print("\n  Conexión entre segmentos:")
        print(f"  | VM1     | VM2     |")
    print("  +---------+---------+")
    # Mostrar detalles de VMs
    print(f"\n  Máquinas Virtuales:")
    print("  +" + "="*60 + "+")
    print("  | nombre   | recursos                                      |")
    print("  +" + "="*10 + "+" + "="*48 + "+")
    for vm in slice.vms:
        resources = f"almacenamiento: {vm.disk}GB, coresCpu: {vm.cpu}, ram: {vm.memory/1024:.0f}GB"
        vm_name = vm.name[:8].ljust(8)
        print(f"  | {vm_name} | {resources:<47} |")
    print("  +" + "="*60 + "+")
    # Mostrar gráfico ASCII de la topología
    print(f"\n  Visualización de la topología:")
    draw_topology(slice.topology, len(slice.vms))
    input("\n  Presione Enter para continuar...")
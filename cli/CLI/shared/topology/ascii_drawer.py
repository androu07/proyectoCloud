
def draw_topology(topology_type: str, num_vms: int):
    """Visualización ASCII clara y profesional de topologías"""
    
    if topology_type == 'lineal' or topology_type == 'linear':
        # Cadena lineal
        print("  ", end="")
        for i in range(num_vms):
            print(f"[VM{i}]", end="")
            if i < num_vms - 1:
                print("──", end="")
        print("\n")

    elif topology_type == 'anillo' or topology_type == 'ring':
        # Representación de anillo
        if num_vms <= 6:
            # Dibujo ASCII para pocos nodos
            if num_vms == 3:
                print("      ╔═VM0═╗")
                print("      ║     ║")
                print("    VM2═════VM1")
            elif num_vms == 4:
                print("    VM0═════VM1")
                print("     ║       ║")
                print("     ║       ║")
                print("    VM3═════VM2")
            elif num_vms == 5:
                print("        VM0")
                print("       ╱   ╲")
                print("     VM4   VM1")
                print("      │     │")
                print("     VM3───VM2")
            elif num_vms == 6:
                print("     VM0───VM1")
                print("      │     │")
                print("    VM5     VM2")
                print("      │     │")
                print("     VM4───VM3")
        else:
            # Representación textual para muchos nodos
            print("  ┌─────────────────────────┐")
            print("  │    Anillo Circular      │")
            print("  └─────────────────────────┘")
            print("\n  Conexiones:")
            for i in range(min(5, num_vms)):
                next_node = (i + 1) % num_vms
                print(f"    VM{i} ↔ VM{next_node}")
            if num_vms > 5:
                print(f"    ... ({num_vms - 5} conexiones más)")
    
    elif topology_type == 'arbol' or topology_type == 'tree':
        print("         [VM0]")
        print("        /  |  \\")
        if num_vms >= 3:
            print("    VM1  VM2  VM3")
        if num_vms >= 7:
            print("    / \\   |   / \\")
            print("  VM4 VM5 VM6 VM7")
    
    elif topology_type == 'malla' or topology_type == 'mesh':
        if num_vms <= 4:
            print("  Todos ↔ Todos")
            print("  ┌───────────┐")
            for i in range(num_vms):
                print(f"  │    VM{i}    │")
            print("  └───────────┘")
        else:
            print(f"  Malla completa: {num_vms} nodos")
            print(f"  Enlaces totales: {num_vms*(num_vms-1)//2}")
    
    elif topology_type == 'bus':
        print("  ═══════[BUS CENTRAL]═══════")
        for i in range(num_vms):
            print(f"           │")
            print(f"         [VM{i}]")
    
    # Información adicional
    print(f"\n  Estado: Activo")
    print(f"  Conexiones: Establecidas")
    print()  # Línea en blanco al final


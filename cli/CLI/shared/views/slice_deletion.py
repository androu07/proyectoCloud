def delete_any_slice(slice_manager):
    """Eliminar CUALQUIER slice (SUPERADMIN)"""
    print_header()
    print(Colors.BOLD + "\n  ELIMINAR CUALQUIER SLICE" + Colors.ENDC)
    
    slices = slice_manager.get_slices()
    if not slices:
        print("\n  No hay slices para eliminar")
    else:
        for i, s in enumerate(slices, 1):
            print(f"  {i}. {s.id} - {s.name}")
        
        choice = input("\n  Seleccione slice (0 para cancelar): ")
        if choice != '0' and choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(slices):
                if input(f"  ¿Confirmar eliminación? (s/n): ").lower() == 's':
                    slice_manager.delete_slice(slices[idx].id)
                    print(Colors.GREEN + "  ✓ Slice eliminado" + Colors.ENDC)
    
    input("\n  Presione Enter para continuar...")


def delete_my_slice(slice_manager, user):
    """Eliminar MI slice (CLIENTE)"""
    print_header(user)
    print(Colors.BOLD + "\n  ELIMINAR MI SLICE" + Colors.ENDC)
    
    my_slices = [s for s in slice_manager.get_slices() if getattr(s, 'usuario', None) == user.username]
    
    if not my_slices:
        print("\n  No tienes slices para eliminar")
    else:
        for i, s in enumerate(my_slices, 1):
            print(f"  {i}. {s.name}")
        
        choice = input("\n  Seleccione slice (0 para cancelar): ")
        if choice != '0' and choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(my_slices):
                if input(f"  ¿Confirmar eliminación? (s/n): ").lower() == 's':
                    slice_manager.delete_slice(my_slices[idx].id)
                    print(Colors.GREEN + "  ✓ Slice eliminado" + Colors.ENDC)
    
    input("\n  Presione Enter para continuar...")
"""Funciones para editar slices existentes"""

from shared.ui_helpers import print_header, pause, show_success, show_error, show_info, confirm_action
from shared.colors import Colors
from shared.services.flavor_service import select_flavor, get_flavor_specs
import json
import os


def editar_slice(slice_api, auth_manager):
    """
    Editar un slice existente: agregar VMs, modificar topología
    
    Args:
        slice_api: Servicio de API de slices
        auth_manager: Gestor de autenticación
    """
    print_header(auth_manager.current_user)
    print(Colors.BOLD + "\n  EDITAR SLICE" + Colors.ENDC)
    print("  " + "="*50)
    
    try:
        # Asegurar que BASE_JSON esté definido
        if not BASE_JSON:
            BASE_JSON = os.path.join(os.path.dirname(__file__), '..', '..', 'base_de_datos.json')
        # Leer slices locales del usuario desde base_de_datos.json
        BASE_JSON = os.path.join(os.path.dirname(__file__), '..', '..', 'base_de_datos.json')
        VMS_JSON = os.path.join(os.path.dirname(__file__), '..', '..', 'vms.json')
        if os.path.exists(BASE_JSON):
            with open(BASE_JSON, 'r', encoding='utf-8') as f:
                data = json.load(f) or []
            slices = data if isinstance(data, list) else data.get('slices', [])
        else:
            slices = []

        # Filtrar slices del usuario actual (admin puede ver todos)
        usuario_actual = auth_manager.get_current_user_email()
        user_role = getattr(auth_manager, 'user_role', 'cliente')
        if user_role == 'admin':
            slices_usuario = slices
        else:
            slices_usuario = [s for s in slices if s.get('usuario') == usuario_actual]

        if not slices_usuario:
            show_info("No tienes slices para editar")
            pause()
            return

        # Mostrar slices disponibles
        print(f"\n{Colors.YELLOW}  Seleccione slice a editar:{Colors.ENDC}")
        for i, s in enumerate(slices_usuario, 1):
            nombre = s.get('nombre', s.get('nombre_slice', ''))
            vms_count = len(s.get('vms', []))
            usuario = s.get('usuario', 'N/A')
            # Mostrar propietario si es admin
            if user_role == 'admin':
                print(f"  {i}. {nombre} (VLAN: {s.get('vlan')}, VMs: {vms_count}, Topología: {s.get('topologia')}, Usuario: {usuario})")
            else:
                print(f"  {i}. {nombre} (VLAN: {s.get('vlan')}, VMs: {vms_count}, Topología: {s.get('topologia')})")

        print(f"  0. Cancelar")

        choice = input(f"\n{Colors.CYAN}  Opción: {Colors.ENDC}").strip()

        if choice == '0':
            print(f"\n{Colors.YELLOW}  Operación cancelada{Colors.ENDC}")
            pause()
            return

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(slices_usuario):
                slice_seleccionado = slices_usuario[idx]
                
                # Menú de edición
                print(f"\n{Colors.GREEN}  Editando: {slice_seleccionado.get('nombre')}{Colors.ENDC}")
                print(f"\n{Colors.YELLOW}  ¿Qué desea editar?{Colors.ENDC}")
                print("  1. Agregar VMs al slice")
                print("  2. Modificar topología")
                print("  3. Eliminar VMs del slice")
                print("  0. Cancelar")
                
                edit_choice = input(f"\n{Colors.CYAN}  Opción: {Colors.ENDC}").strip()
                
                cambios = False
                if edit_choice == '1':
                    agregar_vms_a_slice(slice_seleccionado, slices, BASE_JSON, VMS_JSON)
                    cambios = True
                elif edit_choice == '2':
                    modificar_topologia_slice(slice_seleccionado, slices, BASE_JSON)
                    cambios = True
                elif edit_choice == '3':
                    eliminar_vms_de_slice(slice_seleccionado, slices, BASE_JSON, VMS_JSON)
                    cambios = True
                elif edit_choice == '0':
                    print(f"\n{Colors.YELLOW}  Edición cancelada{Colors.ENDC}")
                else:
                    print(f"\n{Colors.RED}  ❌ Opción inválida{Colors.ENDC}")
                if cambios:
                    show_success("Cambios guardados en base_de_datos.json y vms.json")
            else:
                print(f"\n{Colors.RED}  ❌ Opción inválida{Colors.ENDC}")

        except ValueError:
            print(f"\n{Colors.RED}  ❌ Debe ingresar un número{Colors.ENDC}")
        except Exception as e:
            show_error(f"Error: {str(e)}")

    except Exception as e:
        show_error(f"Error al cargar slices: {str(e)}")
    
    pause()


def agregar_vms_a_slice(slice_seleccionado, data, VMS_JSON, BASE_YAML):
    """Agregar nuevas VMs a un slice existente"""
    print(f"\n{Colors.CYAN}  AGREGAR VMs AL SLICE{Colors.ENDC}")
    
    try:
        cantidad = input(f"\n{Colors.CYAN}  ¿Cuántas VMs desea agregar? {Colors.ENDC}").strip()
        cantidad = int(cantidad)
        if cantidad <= 0:
            print(f"\n{Colors.RED}  Debe agregar al menos 1 VM{Colors.ENDC}")
            return
        vlan = slice_seleccionado.get('vlan', 1)
        vms_actuales = slice_seleccionado.get('vms', [])
        num_vms_actuales = len(vms_actuales)
        if os.path.exists(VMS_JSON):
            with open(VMS_JSON, 'r', encoding='utf-8') as f:
                vms_data_json = json.load(f)
            total_vms = len(vms_data_json.get('vms', []))
        else:
            total_vms = 0
        nuevas_vms = []
        for i in range(cantidad):
            num_vm = num_vms_actuales + i + 1
            print(f"\n{Colors.YELLOW}  --- Configuración VM {num_vm} ---{Colors.ENDC}")
            flavor = select_flavor()
            specs = get_flavor_specs(flavor)
            ip = f"10.7.{vlan}.{num_vm+1}"
            puerto_vnc = 5900 + total_vms + num_vm
            vm = {
                'nombre': f"vm{num_vm}",
                'cpu': specs['cpu'],
                'disk': specs['disk'],
                'memory': specs['memory'],
                'flavor': flavor,
                'ip': ip,
                'puerto_vnc': puerto_vnc,
                'usuario': slice_seleccionado.get('usuario')
            }
            nuevas_vms.append(vm)
            vms_actuales.append(vm)
        slice_seleccionado['vms'] = vms_actuales
        with open(BASE_JSON, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        from shared.data_store import guardar_vms
        guardar_vms(nuevas_vms)
        show_success(f"{cantidad} VM(s) agregada(s) exitosamente al slice")
    except ValueError:
        print(f"\n{Colors.RED}  ❌ Valor inválido{Colors.ENDC}")
    except Exception as e:
        show_error(f"Error al agregar VMs: {str(e)}")


def modificar_topologia_slice(slice_seleccionado, data, BASE_YAML):
    """Modificar la topología de un slice existente"""
    # Asegurar que BASE_JSON esté definido
    if BASE_JSON is None or BASE_JSON == '':
        BASE_JSON = os.path.join(os.path.dirname(__file__), '..', '..', 'base_de_datos.json')
    print(f"\n{Colors.CYAN}  MODIFICAR TOPOLOGÍA{Colors.ENDC}")
    print(f"\n{Colors.YELLOW}  Topología actual: {slice_seleccionado.get('topologia')}{Colors.ENDC}")
    print(f"\n  Seleccione nueva topología:")
    print("  1. Lineal")
    print("  2. Malla")
    print("  3. Árbol")
    print("  4. Anillo")
    print("  5. Bus")
    print("  6. Manual")
    print("  0. Cancelar")
    choice = input(f"\n{Colors.CYAN}  Opción: {Colors.ENDC}").strip()
    topologias = {
        '1': 'lineal',
        '2': 'malla',
        '3': 'arbol',
        '4': 'anillo',
        '5': 'bus',
        '6': 'manual'
    }
    if choice == '0':
        print(f"\n{Colors.YELLOW}  Operación cancelada{Colors.ENDC}")
        return
    if choice in topologias:
        nueva_topologia = topologias[choice]
        slice_seleccionado['topologia'] = nueva_topologia
        with open(BASE_JSON, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        show_success(f"Topología cambiada a '{nueva_topologia}'")
    else:
        print(f"\n{Colors.RED}  ❌ Opción inválida{Colors.ENDC}")


def eliminar_vms_de_slice(slice_seleccionado, data, VMS_JSON, BASE_YAML):
    """Eliminar VMs de un slice existente"""
    print(f"\n{Colors.CYAN}  ELIMINAR VMs DEL SLICE{Colors.ENDC}")
    
    # Asegurar que BASE_JSON esté definido
    if not BASE_JSON:
        BASE_JSON = os.path.join(os.path.dirname(__file__), '..', '..', 'base_de_datos.json')
    vms_actuales = slice_seleccionado.get('vms', [])
    if not vms_actuales:
        print(f"\n{Colors.YELLOW}  No hay VMs para eliminar en este slice{Colors.ENDC}")
        return
    print(f"\n{Colors.YELLOW}  VMs en el slice:{Colors.ENDC}")
    for i, vm in enumerate(vms_actuales, 1):
        print(f"  {i}. {vm.get('nombre')} (IP: {vm.get('ip')}, CPU: {vm.get('cpu')}, RAM: {vm.get('memory')} MB)")
    print(f"  0. Cancelar")
    choice = input(f"\n{Colors.CYAN}  Seleccione VM a eliminar: {Colors.ENDC}").strip()
    if choice == '0':
        print(f"\n{Colors.YELLOW}  Operación cancelada{Colors.ENDC}")
        return
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(vms_actuales):
            vm_a_eliminar = vms_actuales[idx]
            if confirm_action(f"¿Eliminar VM '{vm_a_eliminar.get('nombre')}'?"):
                vms_actuales.pop(idx)
                slice_seleccionado['vms'] = vms_actuales
                with open(BASE_JSON, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                if os.path.exists(VMS_JSON):
                    with open(VMS_JSON, 'r', encoding='utf-8') as f:
                        vms_data = json.load(f)
                    vms_data['vms'] = [vm for vm in vms_data.get('vms', []) 
                                       if vm.get('nombre') != vm_a_eliminar.get('nombre') 
                                       or vm.get('ip') != vm_a_eliminar.get('ip')]
                    with open(VMS_JSON, 'w', encoding='utf-8') as f:
                        json.dump(vms_data, f, indent=2, ensure_ascii=False)
                show_success(f"VM '{vm_a_eliminar.get('nombre')}' eliminada exitosamente")
            else:
                print(f"\n{Colors.YELLOW}  Eliminación cancelada{Colors.ENDC}")
        else:
            print(f"\n{Colors.RED}  ❌ Opción inválida{Colors.ENDC}")
    except ValueError:
        print(f"\n{Colors.RED}  ❌ Debe ingresar un número{Colors.ENDC}")
    except Exception as e:
        show_error(f"Error al eliminar VM: {str(e)}")

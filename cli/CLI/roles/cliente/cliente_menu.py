"""Menú principal para el rol CLIENTE"""

from shared.ui_helpers import print_header, get_menu_choice, pause
from shared.colors import Colors
from shared.views.slice_builder import SliceBuilder
import os


def cliente_menu(auth_manager, slice_manager, auth_service=None):
    """
    Menú del cliente con funcionamiento local
    
    Args:
        auth_manager: Gestor de autenticación local
        slice_manager: Gestor de slices
        auth_service: Servicio de API externa (no usado)
    """
    
    while True:
        # Encabezado unificado
        print(Colors.BLUE + "="*70 + Colors.ENDC)
        print(Colors.BOLD + Colors.GREEN + "\n  BIENVENIDO A PUCP CLOUD ORCHESTRATOR".center(70) + Colors.ENDC)
        print(Colors.BLUE + "="*70 + Colors.ENDC)

        # Usuario y rol
        user_email = auth_manager.get_current_user_email()
        print(f"\n  Usuario: {Colors.YELLOW}{user_email}{Colors.ENDC} | Rol: {Colors.GREEN}CLIENTE{Colors.ENDC}")
        print(Colors.BLUE + "-"*70 + Colors.ENDC)

        # Título del menú
        print_header(auth_manager.current_user)
        print(Colors.BOLD + "\n  MENÚ CLIENTE" + Colors.ENDC)
        print("  " + "="*50)

        # Sección Mis Recursos
        print(Colors.YELLOW + "\n  Gestión de Slices:" + Colors.ENDC)
        print("  1. Crear Nuevo Slice")
        print("  2. Ver mis slices")
        print("  3. Eliminar Slice")
        print("  4. Activar/Desactivar Slice")
        print(Colors.RED + "\n  0. Cerrar Sesión" + Colors.ENDC)

        choice = input("\nSeleccione opción: ")

        if choice == '1':
            _crear_slice(auth_manager, slice_manager, slice_builder=SliceBuilder)
        elif choice == '2':
            ver_mis_slices_y_detalles(auth_manager, slice_manager)
        elif choice == '3':
            _eliminar_slice_cliente(auth_manager, slice_manager)
        elif choice == '4':
            _pausar_reactivar_slice(auth_manager, slice_manager)
        elif choice == '0':
            _cerrar_sesion(auth_manager, auth_service)
            return
        else:
            print(f"\n{Colors.RED}  ❌ Opción inválida{Colors.ENDC}")
            pause()


def _pausar_reactivar_slice(auth_manager, slice_manager):
    """Permite pausar o reactivar un slice del usuario actual usando la API remota"""
    from shared.ui_helpers import print_header, pause
    from shared.colors import Colors
    import os
    
    user = auth_manager.current_user
    print_header(user)
    print(Colors.BOLD + "\n  PAUSAR/REANUDAR SLICE" + Colors.ENDC)
    print("  " + "="*80)
    
    # Obtener token JWT
    token = getattr(auth_manager, 'api_token', None) or getattr(auth_manager, 'token', None)
    if not token:
        print(f"\n{Colors.RED}[ERROR] No se pudo obtener token de autenticación{Colors.ENDC}")
        pause()
        return
    
    # Configurar servicio API
    from core.services.slice_api_service import SliceAPIService
    api_url = os.getenv('SLICE_API_URL', 'https://localhost:8443')
    user_email = getattr(user, 'email', None) or getattr(user, 'username', '')
    slice_api = SliceAPIService(api_url, token, user_email)
    
    # Obtener slices desde la API remota
    print(f"\n{Colors.CYAN}⏳ Cargando slices desde el servidor remoto...{Colors.ENDC}")
    slices = slice_api.list_my_slices()
    
    if not slices:
        print(f"\n{Colors.YELLOW}  📋 No tienes slices creados{Colors.ENDC}")
        pause()
        return
    
    # Mostrar lista de slices con su estado
    print(f"\n{Colors.GREEN}  Tus slices:{Colors.ENDC}\n")
    for idx, s in enumerate(slices, 1):
        slice_id = s.get('id', 'N/A')
        nombre = s.get('nombre_slice', 'Sin nombre')
        estado = s.get('estado', 'N/A')
        estado_color = Colors.GREEN if estado == 'activa' else Colors.YELLOW
        print(f"  {idx}. {nombre} (ID: {slice_id}) - Estado: {estado_color}{estado}{Colors.ENDC}")
    
    print(f"  0. Cancelar")
    
    # Seleccionar slice
    choice = input(f"\n{Colors.CYAN}Seleccione el slice: {Colors.ENDC}").strip()
    if choice == '0':
        print(f"\n{Colors.YELLOW}  Operación cancelada{Colors.ENDC}")
        pause()
        return
    
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(slices):
            slice_sel = slices[idx]
            slice_id = slice_sel.get('id')
            nombre = slice_sel.get('nombre_slice', 'Sin nombre')
            estado_actual = slice_sel.get('estado', 'activa')
            
            # Determinar acción
            if estado_actual == 'activa':
                accion = 'pausar'
                print(f"\n{Colors.YELLOW}¿Desea PAUSAR el slice '{nombre}'? (s/n): {Colors.ENDC}", end="")
            else:
                accion = 'reanudar'
                print(f"\n{Colors.GREEN}¿Desea REANUDAR el slice '{nombre}'? (s/n): {Colors.ENDC}", end="")
            
            confirmacion = input().strip().lower()
            if confirmacion != 's':
                print(f"\n{Colors.YELLOW}  Operación cancelada{Colors.ENDC}")
                pause()
                return
            
            # Llamar al endpoint correspondiente
            if accion == 'pausar':
                result = slice_api.pausar_slice(slice_id)
            else:
                result = slice_api.reanudar_slice(slice_id)
            
            # Mostrar resultado
            if result.get('ok'):
                print(f"\n{Colors.GREEN}✅ {result.get('message')}{Colors.ENDC}")
            else:
                print(f"\n{Colors.RED}❌ Error: {result.get('error')}{Colors.ENDC}")
        else:
            print(f"\n{Colors.RED}  ❌ Opción inválida{Colors.ENDC}")
    except ValueError:
        print(f"\n{Colors.RED}  ❌ Debe ingresar un número{Colors.ENDC}")
    except Exception as e:
        print(f"\n{Colors.RED}❌ Error inesperado: {str(e)}{Colors.ENDC}")
    
    pause()


def _eliminar_slice_cliente(auth_manager, slice_manager):
    """Permite eliminar un slice del usuario actual usando la API remota"""
    from shared.ui_helpers import print_header, pause
    from shared.colors import Colors
    import os
    
    user = auth_manager.current_user
    print_header(user)
    print(Colors.BOLD + "\n  ELIMINAR SLICE" + Colors.ENDC)
    print("  " + "="*80)
    
    # Obtener token JWT
    token = getattr(auth_manager, 'api_token', None) or getattr(auth_manager, 'token', None)
    if not token:
        print(f"\n{Colors.RED}[ERROR] No se pudo obtener token de autenticación{Colors.ENDC}")
        pause()
        return
    
    # Configurar servicio API
    from core.services.slice_api_service import SliceAPIService
    api_url = os.getenv('SLICE_API_URL', 'https://localhost:8443')
    api_service = SliceAPIService(api_url=api_url, token=token)
    
    # Listar slices del usuario
    slices = api_service.list_my_slices()
    
    if not slices:
        print(f"\n{Colors.YELLOW}  ℹ️  No tienes slices creados{Colors.ENDC}")
        pause()
        return
    
    # Mostrar slices disponibles en formato tabla
    print(f"\n{Colors.BOLD}  Slices disponibles:{Colors.ENDC}")
    print("  " + "-"*80)
    print(f"  {'ID':<5} {'Nombre':<30} {'Estado':<15} {'Fecha/Hora':<20}")
    print("  " + "-"*80)
    
    for s in slices:
        slice_id = s.get('id', 'N/A')
        nombre = s.get('nombre_slice', 'Sin nombre')
        estado = s.get('estado', 'desconocido')
        timestamp = s.get('timestamp', 'N/A')
        print(f"  {slice_id:<5} {nombre:<30} {estado:<15} {timestamp:<20}")
    
    print("  " + "-"*80)
    
    # Solicitar ID del slice a eliminar
    try:
        slice_id_input = input(f"\n{Colors.YELLOW}Ingrese el ID del slice a eliminar (0 para cancelar): {Colors.ENDC}")
        slice_id = int(slice_id_input)
        
        if slice_id == 0:
            print(f"\n{Colors.YELLOW}  ℹ️  Operación cancelada{Colors.ENDC}")
            pause()
            return
        
        # Verificar que el slice existe y pertenece al usuario
        slice_encontrado = None
        for s in slices:
            if s.get('id') == slice_id:
                slice_encontrado = s
                break
        
        if not slice_encontrado:
            print(f"\n{Colors.RED}  ❌ Slice no encontrado o no tienes permisos{Colors.ENDC}")
            pause()
            return
        
        # Confirmar eliminación
        nombre_slice = slice_encontrado.get('nombre_slice', 'Sin nombre')
        confirmacion = input(f"\n{Colors.RED}¿Está seguro de eliminar el slice '{nombre_slice}' (ID: {slice_id})? (s/n): {Colors.ENDC}").lower()
        
        if confirmacion != 's':
            print(f"\n{Colors.YELLOW}  ℹ️  Operación cancelada{Colors.ENDC}")
            pause()
            return
        
        # Llamar a la API para eliminar
        print(f"\n{Colors.YELLOW}  ⏳ Eliminando slice...{Colors.ENDC}")
        result = api_service.eliminar_slice(slice_id)
        
        # Mostrar resultado
        if result.get('ok'):
            print(f"\n{Colors.GREEN}✅ {result.get('message')}{Colors.ENDC}")
        else:
            print(f"\n{Colors.RED}❌ Error: {result.get('error')}{Colors.ENDC}")
            
    except ValueError:
        print(f"\n{Colors.RED}  ❌ Debe ingresar un número válido{Colors.ENDC}")
    except Exception as e:
        print(f"\n{Colors.RED}❌ Error inesperado: {str(e)}{Colors.ENDC}")
    
    pause()


def _verificar_sesion(auth_service, auth_manager):
    """
    Verificar si la sesión con la API sigue siendo válida
    
    Args:
        auth_service: Servicio de API externa
        auth_manager: Gestor de autenticación local
        
    Returns:
        True si la sesión es válida, False si expiró
    """
    if not auth_service:
        return True  # Si no hay auth_service, no verificamos
    
    if not auth_service.verify_token():
        print(f"\n{Colors.RED}⚠️  Su sesión ha expirado{Colors.ENDC}")
        print(f"{Colors.YELLOW}Por favor, inicie sesión nuevamente{Colors.ENDC}")
        auth_manager.logout()
        auth_service.logout()
        pause()
        return False
    
    return True


def _verificar_estado_sesion(auth_service):
    """Verificar y mostrar estado de la sesión"""
    print_header(None)
    print(Colors.BOLD + "\n  ESTADO DE SESIÓN" + Colors.ENDC)
    print("  " + "="*50)
    
    print(f"\n{Colors.CYAN}⏳ Verificando token con la API...{Colors.ENDC}")
    
    if auth_service.verify_token():
        print(f"{Colors.GREEN}✅ Sesión válida y activa{Colors.ENDC}")
        print(f"{Colors.CYAN}Token autenticado correctamente{Colors.ENDC}")
        
        # Mostrar info adicional del usuario si está disponible
        user_data = auth_service.get_user_data()
        if user_data:
            print(f"\n{Colors.YELLOW}Información del usuario:{Colors.ENDC}")
            print(f"  • Nombre: {user_data.get('nombre', 'N/A')}")
            print(f"  • Email: {user_data.get('email', 'N/A')}")
            print(f"  • Rol: {user_data.get('rol', 'N/A')}")
    else:
        print(f"{Colors.RED}❌ Sesión inválida o expirada{Colors.ENDC}")
        print(f"{Colors.YELLOW}Deberá iniciar sesión nuevamente{Colors.ENDC}")
    
    pause()


def _crear_slice(auth_manager, slice_manager, slice_builder):
    """
    Crear un nuevo slice usando el constructor interactivo
    
    Args:
        auth_manager: Gestor de autenticación
        slice_builder: Clase SliceBuilder para construcción interactiva
    """
    print_header(auth_manager.current_user)
    print(Colors.BOLD + "\n  CREAR NUEVO SLICE" + Colors.ENDC)
    print("  " + "="*50 + "\n")
    try:
        builder = slice_builder(auth_manager.current_user)
        datos = builder.start()
        if isinstance(datos, tuple) and len(datos) == 6:
            nombre, topologia, vms_data, salida_internet, conexion_topologias, topologias_json = datos
            if nombre and topologia and vms_data and topologias_json:
                # Construir el JSON para la API
                solicitud_json = {
                    "id_slice": "",
                    "cantidad_vms": str(len(vms_data)),
                    "vlans_separadas": "",
                    "vlans_usadas": "",
                    "vncs_separadas": "",
                    "conexion_topologias": conexion_topologias,
                    "topologias": topologias_json
                }
                from core.services.slice_api_service import SliceAPIService
                api_url = os.getenv('SLICE_API_URL', 'https://localhost:8443')
                token = getattr(auth_manager, 'api_token', None) or getattr(auth_manager, 'token', None)
                
                if not token:
                    print(f"{Colors.RED}[ERROR] No se pudo obtener token de autenticación{Colors.ENDC}")
                    print(f"{Colors.YELLOW}Guardando slice localmente...{Colors.ENDC}")
                    from shared.data_store import guardar_slice
                    user_email = getattr(auth_manager.current_user, 'email', None) or getattr(auth_manager.current_user, 'username', '')
                    slice_obj = {
                        'nombre': nombre,
                        'topologia': topologia,
                        'vms': vms_data,
                        'salida_internet': salida_internet,
                        'usuario': user_email,
                        'conexion_topologias': conexion_topologias,
                        'topologias': topologias_json
                    }
                    guardar_slice(slice_obj)
                    print(f"{Colors.GREEN}Slice '{nombre}' guardado localmente{Colors.ENDC}")
                    pause()
                    return
                
                user_email = getattr(auth_manager.current_user, 'email', None) or getattr(auth_manager.current_user, 'username', None)
                slice_api = SliceAPIService(api_url, token, user_email)
                
                print(f"\n{Colors.CYAN}⏳ Enviando solicitud de creación de slice a la API...{Colors.ENDC}")
                print(f"   URL: {api_url}/slices/solicitud_creacion")
                
                resp = slice_api.create_slice_api(nombre, solicitud_json)
                
                if resp.get("ok"):
                    print(f"\n{Colors.GREEN}✅ Slice '{nombre}' creado exitosamente en la API remota{Colors.ENDC}")
                    print(f"  • Nombre: {nombre}")
                    print(f"  • Topología: {topologia}")
                    print(f"  • VMs: {len(vms_data)}")
                    pause()
                    return
                else:
                    error_msg = resp.get('error', 'Error desconocido')
                    status = resp.get('status', 'N/A')
                    print(f"\n{Colors.RED}❌ Error al crear slice en la API{Colors.ENDC}")
                    print(f"   Status: {status}")
                    print(f"   Error: {error_msg}")
                    print(f"\n{Colors.YELLOW}⚠️  Guardando localmente como respaldo...{Colors.ENDC}")
                    from shared.data_store import guardar_slice
                    slice_obj = {
                        'nombre': nombre,
                        'topologia': topologia,
                        'vms': vms_data,
                        'salida_internet': salida_internet,
                        'usuario': user_email,
                        'conexion_topologias': conexion_topologias,
                        'topologias': topologias_json
                    }
                    guardar_slice(slice_obj)
                    print(f"{Colors.GREEN}Slice '{nombre}' guardado localmente{Colors.ENDC}")
                    pause()
                    return
            else:
                print(f"\n{Colors.YELLOW}  Creación cancelada{Colors.ENDC}")
        else:
            print(f"{Colors.RED}  ❌ Error: Formato de datos inesperado al crear slice: {datos}{Colors.ENDC}")
            pause()
    except Exception as e:
        from shared.ui_helpers import show_error
        show_error(f"Error inesperado: {str(e)}")
        print(f"{Colors.RED}  Detalles técnicos: {e}{Colors.ENDC}")
def _ver_mis_slices(user, auth_manager=None):
    """
    Ver slices del usuario obtenidos desde la API remota
    
    Estructura de la BD remota:
    - id: INT AUTO_INCREMENT PRIMARY KEY
    - usuario: VARCHAR(100) NOT NULL
    - nombre_slice: VARCHAR(200) NOT NULL
    - vms: JSON (no se muestra en la lista)
    - estado: VARCHAR(50) DEFAULT 'plantilla'
    - timestamp: TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    
    Args:
        user: Usuario actual
        auth_manager: Gestor de autenticación (para obtener token)
    """
    from inspect import currentframe
    
    # Si no se pasó auth_manager, intentar obtenerlo del contexto
    if not auth_manager:
        frame = currentframe()
        while frame:
            if 'auth_manager' in frame.f_locals:
                auth_manager = frame.f_locals['auth_manager']
                break
            frame = frame.f_back
    
    print_header(user)
    print(Colors.BOLD + "\n  MIS SLICES" + Colors.ENDC)
    print("  " + "="*80)
    
    # Obtener token JWT
    token = None
    if auth_manager:
        if hasattr(auth_manager, 'token'):
            token = auth_manager.token
        elif hasattr(auth_manager, 'get_api_token'):
            token = auth_manager.get_api_token()
    
    if not token:
        print(f"\n{Colors.RED}[ERROR] No se pudo obtener token de autenticación{Colors.ENDC}")
        print(f"\n{Colors.YELLOW}  No tienes slices creados{Colors.ENDC}")
        pause()
        return
    
    # Configurar servicio API
    from core.services.slice_api_service import SliceAPIService
    api_url = os.getenv('SLICE_API_URL', 'https://localhost:8443')
    user_email = getattr(user, 'email', None) or getattr(user, 'username', '')
    slice_api = SliceAPIService(api_url, token, user_email)
    
    # Obtener slices desde la API remota
    print(f"\n{Colors.CYAN}⏳ Cargando slices desde el servidor remoto...{Colors.ENDC}")
    slices = slice_api.list_my_slices()
    
    if not slices:
        print(f"\n{Colors.YELLOW}  📋 No tienes slices creados{Colors.ENDC}")
        print(f"{Colors.CYAN}  Usa la opción 1 para crear tu primer slice{Colors.ENDC}")
    else:
        print(f"\n{Colors.GREEN}  Total de slices: {len(slices)}{Colors.ENDC}\n")
        
        # Encabezados de la tabla
        print(f"{Colors.CYAN}{'ID':<8} {'Nombre del Slice':<35} {'Estado':<15} {'Fecha/Hora':<20}{Colors.ENDC}")
        print("-" * 80)
        
        # Mostrar cada slice
        for s in slices:
            slice_id = str(s.get('id', 'N/A'))[:7]
            nombre = str(s.get('nombre_slice', 'Sin nombre'))[:34]
            estado = str(s.get('estado', 'plantilla'))[:14]
            timestamp = str(s.get('timestamp', 'N/A'))[:19]
            
            print(f"{slice_id:<8} {nombre:<35} {estado:<15} {timestamp:<20}")
    
    pause()


def _editar_slice(auth_manager):
    """Llama a la función de edición de slices desde slice_editor.py"""
    try:
        from roles.cliente.slice_editor import editar_slice
        editar_slice(auth_manager)
    except ImportError as e:
        print(f"\nError importando editor: {e}")
    except Exception as e:
        print(f"\nError al editar slice: {e}")


def _eliminar_slice(auth_manager, slice_manager):
    """
    Eliminar un slice del usuario
    
    Args:
        auth_manager: Gestor de autenticación
        slice_manager: Gestor de slices
    """
    print_header(auth_manager.current_user)
    print(Colors.BOLD + "\n  ELIMINAR SLICE" + Colors.ENDC)
    print("  " + "="*50)
    
    # Verificar permisos
    if not auth_manager.has_permission("delete_own_slice"):
        print(f"\n{Colors.RED}  ❌ No tiene permisos para eliminar slices{Colors.ENDC}")
        pause()
        return
    
    try:
        # Obtener slices del usuario usando SliceManager
        usuario_actual_email = getattr(auth_manager.current_user, 'email', '')
        usuario_actual_username = getattr(auth_manager.current_user, 'username', '')
        
        # Obtener todos los slices del SliceManager
        all_slices = slice_manager.get_slices()
        
        # Filtrar slices del usuario actual (usando email o username)
        # Filtrar slices del usuario actual (usando email o username, robusto)
        def es_mi_slice(s):
            if isinstance(s, dict):
                slice_user = s.get('usuario') or s.get('owner') or s.get('user')
                return slice_user == usuario_actual_email or slice_user == usuario_actual_username
            else:
                slice_owner = (getattr(s, 'owner', None) or 
                              getattr(s, 'usuario', None) or 
                              getattr(s, 'user', None))
                return slice_owner == usuario_actual_email or slice_owner == usuario_actual_username
        slices_usuario = [s for s in all_slices if es_mi_slice(s)]

        if not slices_usuario:
            from shared.ui_helpers import show_info
            show_info("No tienes slices para eliminar")
            pause()
            return

        print(f"\n{Colors.YELLOW}  Seleccione slice a eliminar:{Colors.ENDC}")
        for i, s in enumerate(slices_usuario, 1):
            # Mostrar el nombre real si existe, si no mostrar la topología principal como nombre
            nombre = getattr(s, 'name', None)
            if not nombre or nombre == '' or nombre == s.id:
                # Si no hay nombre, usar la topología principal como nombre
                nombre = getattr(s, 'topology', 'sin nombre')
            print(f"  {i}. {nombre}")

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
                from shared.ui_helpers import confirm_action, show_success, show_error

                print(f"\n{Colors.RED}  ⚠️  ADVERTENCIA:{Colors.ENDC}")
                print(f"  Esta acción eliminará permanentemente el slice")
                print(f"  '{slice_seleccionado.name}' y todas sus VMs")

                if confirm_action(f"¿Confirmar eliminación?"):
                    print(f"\n{Colors.CYAN}⏳ Eliminando slice...{Colors.ENDC}")
                    # Eliminar slice usando SliceManager
                    if slice_manager.delete_slice(slice_seleccionado.id):
                        show_success("Slice eliminado exitosamente")
                    else:
                        show_error("No se pudo eliminar el slice")
                else:
                    print(f"\n{Colors.YELLOW}  Eliminación cancelada{Colors.ENDC}")
            else:
                print(f"\n{Colors.RED}  ❌ Opción inválida{Colors.ENDC}")

        except ValueError:
            print(f"\n{Colors.RED}  ❌ Debe ingresar un número{Colors.ENDC}")
        except Exception as e:
            from shared.ui_helpers import show_error
            show_error(f"Error: {str(e)}")

    except Exception as e:
        from shared.ui_helpers import show_error
        show_error(f"Error al cargar slices: {str(e)}")

    pause()


def _cerrar_sesion(auth_manager, auth_service):
    """
    Cerrar sesión limpiando ambos sistemas
    
    Args:
        auth_manager: Gestor de autenticación local
        auth_service: Servicio de API externa
    """
    print(f"\n{Colors.CYAN}👋 Cerrando sesión...{Colors.ENDC}")
    
    # Cerrar sesión local
    auth_manager.logout()
    print(f"{Colors.GREEN}  ✅ Sesión local cerrada{Colors.ENDC}")
    
    # Cerrar sesión en la API externa si existe
    if auth_service:
        auth_service.logout()
        print(f"{Colors.GREEN}  ✅ Sesión API cerrada{Colors.ENDC}")
    
    print(f"\n{Colors.CYAN}¡Hasta pronto!{Colors.ENDC}")
    pause()

def ver_mis_slices_y_detalles(auth_manager, slice_manager):
    """
    Ver slices del usuario desde la API remota
    
    Estructura de la BD remota:
    - id: INT AUTO_INCREMENT PRIMARY KEY
    - usuario: VARCHAR(100) NOT NULL
    - nombre_slice: VARCHAR(200) NOT NULL
    - vms: JSON (no se muestra en la tabla)
    - estado: VARCHAR(50) DEFAULT 'plantilla'
    - timestamp: TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    """
    from shared.ui_helpers import print_header, pause
    from shared.colors import Colors
    import os
    
    user = auth_manager.current_user
    print_header(user)
    print(Colors.BOLD + "\n  MIS SLICES" + Colors.ENDC)
    print("  " + "="*80)
    
    # Obtener token JWT
    token = getattr(auth_manager, 'api_token', None) or getattr(auth_manager, 'token', None)
    if not token:
        print(f"\n{Colors.RED}[ERROR] No se pudo obtener token de autenticación{Colors.ENDC}")
        print(f"\n{Colors.YELLOW}  No tienes slices creados{Colors.ENDC}")
        pause()
        return
    
    # Configurar servicio API
    from core.services.slice_api_service import SliceAPIService
    api_url = os.getenv('SLICE_API_URL', 'https://localhost:8443')
    user_email = getattr(user, 'email', None) or getattr(user, 'username', '')
    slice_api = SliceAPIService(api_url, token, user_email)
    
    # Obtener slices desde la API remota
    print(f"\n{Colors.CYAN}⏳ Cargando slices desde el servidor remoto...{Colors.ENDC}")
    slices = slice_api.list_my_slices()
    
    if not slices:
        print(f"\n{Colors.YELLOW}  📋 No tienes slices creados{Colors.ENDC}")
        print(f"{Colors.CYAN}  Usa la opción 1 para crear tu primer slice{Colors.ENDC}")
        pause()
        return
    
    print(f"\n{Colors.GREEN}  Total de slices: {len(slices)}{Colors.ENDC}\n")
    
    # Encabezados de la tabla
    print(f"{Colors.CYAN}{'ID':<8} {'Nombre del Slice':<35} {'Estado':<15} {'Fecha/Hora':<20}{Colors.ENDC}")
    print("-" * 80)
    
    # Mostrar cada slice
    for s in slices:
        slice_id = str(s.get('id', 'N/A'))[:7]
        nombre = str(s.get('nombre_slice', 'Sin nombre'))[:34]
        estado = str(s.get('estado', 'plantilla'))[:14]
        timestamp = str(s.get('timestamp', 'N/A'))[:19]
        
        print(f"{slice_id:<8} {nombre:<35} {estado:<15} {timestamp:<20}")
    
    # Preguntar si desea ver detalles de algún slice
    print(f"\n{Colors.CYAN}¿Deseas ver los detalles de algún slice? (s/n): {Colors.ENDC}", end="")
    respuesta = input().strip().lower()
    
    if respuesta == 's':
        slice_id_input = input(f"\n{Colors.CYAN}Ingresa el ID del slice: {Colors.ENDC}").strip()
        
        # Buscar el slice por ID
        slice_encontrado = None
        for s in slices:
            if str(s.get('id')) == slice_id_input:
                slice_encontrado = s
                break
        
        if slice_encontrado:
            _mostrar_detalles_slice(slice_encontrado)
        else:
            print(f"\n{Colors.RED}❌ No se encontró un slice con ID: {slice_id_input}{Colors.ENDC}")
    
    pause()


def _mostrar_detalles_slice(slice_data):
    """Muestra los detalles completos de un slice incluyendo VMs y topologías"""
    from shared.colors import Colors
    from shared.ui_helpers import pause
    import json
    
    print(f"\n{Colors.BOLD}{Colors.GREEN}{'='*80}{Colors.ENDC}")
    print(f"{Colors.BOLD}  DETALLES DEL SLICE{Colors.ENDC}")
    print(f"{Colors.GREEN}{'='*80}{Colors.ENDC}")
    
    # Información básica del slice
    print(f"\n{Colors.CYAN}📋 Información General:{Colors.ENDC}")
    print(f"  ID:            {slice_data.get('id', 'N/A')}")
    print(f"  Nombre:        {slice_data.get('nombre_slice', 'Sin nombre')}")
    print(f"  Usuario:       {slice_data.get('usuario', 'N/A')}")
    print(f"  Estado:        {slice_data.get('estado', 'N/A')}")
    print(f"  Fecha/Hora:    {slice_data.get('timestamp', 'N/A')}")
    
    # Mostrar VMs si existen
    vms_data = slice_data.get('vms')
    if vms_data:
        print(f"\n{Colors.CYAN}🖥️  Máquinas Virtuales:{Colors.ENDC}")
        
        # Si vms es un string JSON, parsearlo
        if isinstance(vms_data, str):
            try:
                vms_data = json.loads(vms_data)
            except:
                print(f"  {Colors.RED}Error al parsear datos de VMs{Colors.ENDC}")
                vms_data = None
        
        if vms_data:
            # Verificar si es un dict o una lista
            if isinstance(vms_data, dict):
                # Si es un objeto con estructura de topologías
                if 'topologias' in vms_data:
                    topologias = vms_data.get('topologias', [])
                    for idx, topo in enumerate(topologias, 1):
                        print(f"\n  {Colors.YELLOW}Topología {idx}:{Colors.ENDC}")
                        print(f"    Nombre:        {topo.get('nombre', 'N/A')}")
                        print(f"    Cantidad VMs:  {topo.get('cantidad_vms', 'N/A')}")
                        print(f"    Internet:      {topo.get('internet', 'no')}")
                        
                        vms_list = topo.get('vms', [])
                        if vms_list:
                            print(f"\n    {Colors.CYAN}VMs en esta topología:{Colors.ENDC}")
                            for vm in vms_list:
                                print(f"\n      • {Colors.BOLD}{vm.get('nombre', 'VM sin nombre')}{Colors.ENDC}")
                                print(f"        Cores:          {vm.get('cores', 'N/A')}")
                                print(f"        RAM:            {vm.get('ram', 'N/A')}")
                                print(f"        Almacenamiento: {vm.get('almacenamiento', 'N/A')}")
                                print(f"        Imagen:         {vm.get('image', 'N/A')}")
                                print(f"        Acceso:         {vm.get('acceso', 'no')}")
                                
                                # Puerto VNC (sumar 5900 al valor de la API)
                                puerto_vnc_raw = vm.get('puerto_vnc', '')
                                if puerto_vnc_raw:
                                    try:
                                        puerto_calculado = 5900 + int(puerto_vnc_raw)
                                        print(f"        Puerto VNC:     {Colors.GREEN}{puerto_calculado}{Colors.ENDC}")
                                    except (ValueError, TypeError):
                                        print(f"        Puerto VNC:     {Colors.YELLOW}{puerto_vnc_raw}{Colors.ENDC}")
                                else:
                                    print(f"        Puerto VNC:     {Colors.YELLOW}No asignado{Colors.ENDC}")
                                
                                # Servidor físico
                                servidor = vm.get('server', '')
                                if servidor:
                                    print(f"        Servidor:       {Colors.GREEN}{servidor}{Colors.ENDC}")
                                else:
                                    print(f"        Servidor:       {Colors.YELLOW}No asignado{Colors.ENDC}")
                                
                                # Conexiones VLANs
                                conexiones = vm.get('conexiones_vlans', '')
                                if conexiones:
                                    print(f"        VLANs:          {Colors.GREEN}{conexiones}{Colors.ENDC}")
                                else:
                                    print(f"        VLANs:          {Colors.YELLOW}Sin VLANs{Colors.ENDC}")
                else:
                    # Es un dict simple con VMs
                    for vm_key, vm_data in vms_data.items():
                        if isinstance(vm_data, dict):
                            print(f"\n  • {Colors.BOLD}{vm_key}{Colors.ENDC}")
                            for key, value in vm_data.items():
                                print(f"    {key}: {value}")
            elif isinstance(vms_data, list):
                # Es una lista de VMs
                for idx, vm in enumerate(vms_data, 1):
                    print(f"\n  • {Colors.BOLD}VM {idx}{Colors.ENDC}")
                    if isinstance(vm, dict):
                        print(f"    Nombre:         {vm.get('nombre', 'N/A')}")
                        print(f"    Cores:          {vm.get('cores', 'N/A')}")
                        print(f"    RAM:            {vm.get('ram', 'N/A')}")
                        print(f"    Almacenamiento: {vm.get('almacenamiento', 'N/A')}")
                        print(f"    Imagen:         {vm.get('image', 'N/A')}")
    else:
        print(f"\n{Colors.YELLOW}  No hay información de VMs disponible{Colors.ENDC}")
    
    print(f"\n{Colors.GREEN}{'='*80}{Colors.ENDC}")
    # No llamar pause() aquí para evitar doble pausa
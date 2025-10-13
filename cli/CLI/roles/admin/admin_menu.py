"""Menú principal para el rol ADMIN - Ejemplo adaptado"""

from shared.ui_helpers import print_header, get_menu_choice, pause
from shared.colors import Colors
from shared.views.slice_builder import SliceBuilder
from core.services.slice_api_service import SliceAPIService
import os


def admin_menu(auth_manager, slice_manager, auth_service=None):
    """
    Menú principal para administradores
    
    Args:
        auth_manager: Gestor de autenticación local
        slice_manager: Gestor de slices
        auth_service: Servicio de API externa (opcional)
    """
    
    # Obtener token - priorizar auth_service si está disponible
    if auth_service and auth_service.token:
        token = auth_service.token
    elif hasattr(auth_manager, 'api_service') and auth_manager.api_service:
        token = auth_manager.api_service.token
    elif auth_manager.get_api_token():
        token = auth_manager.get_api_token()
    else:
        print(f"{Colors.RED}[ERROR] No se pudo obtener token de autenticación{Colors.ENDC}")
        pause()
        return
    
    # Configurar URL de la API
    api_url = os.getenv('SLICE_API_URL', 'https://localhost:8443')
    
    # Obtener email del usuario
    user_email = auth_manager.get_current_user_email()
    
    # Inicializar servicio de slices
    slice_api = SliceAPIService(api_url, token, user_email)
    
    while True:
        # Verificar sesión
        if auth_service and not _verificar_sesion(auth_service, auth_manager):
            break

        # Encabezado unificado
        print(Colors.BLUE + "="*70 + Colors.ENDC)
        print(Colors.BOLD + Colors.GREEN + "\n  PUCP CLOUD ORCHESTRATOR - PANEL DE ADMINISTRACIÓN".center(70) + Colors.ENDC)
        print(Colors.BLUE + "="*70 + Colors.ENDC)

        # Usuario y rol
        user_email = auth_manager.get_current_user_email()
        user_name = auth_manager.get_current_user_name()
        print(f"\n  Administrador: {Colors.YELLOW}{user_name} ({user_email}){Colors.ENDC} | Rol: {Colors.RED}ADMIN{Colors.ENDC}")
        print(Colors.BLUE + "-"*70 + Colors.ENDC)

        print_header(auth_manager.current_user)
        print(Colors.BOLD + "\n  MENÚ ADMINISTRADOR" + Colors.ENDC)
        print("  " + "="*60)

        print(Colors.YELLOW + "\n  Gestión de Slices:" + Colors.ENDC)
        print("  1. Ver slice")
        print("  2. Crear Slice")
        print("  3. Eliminar Slice")
        print("  4. Servicio de Monitoreo")
        print("  5. Pausar/Reanudar Slice")
        print(Colors.RED + "\n  0. Cerrar Sesión" + Colors.ENDC)

        choice = input("\nSeleccione opción: ")

        if choice == '1':
            _submenu_ver_slice_admin(auth_manager, slice_manager)
        elif choice == '2':
            # Crear slice como admin usando el mismo flujo y formato que el cliente
            try:
                builder = SliceBuilder(auth_manager.current_user)
                datos = builder.start()
                # print(f"[DEBUG] Datos retornados por builder.start(): {datos}")
                if isinstance(datos, tuple) and len(datos) == 6:
                    nombre, topologia, vms_data, salida_internet, conexion_topologias, topologias_json = datos
                    if nombre and topologia and vms_data and topologias_json:
                        # Crear slice en la API remota
                        print(f"{Colors.CYAN}⏳ Enviando slice a la API remota...{Colors.ENDC}")
                        
                        # Preparar solicitud_json para la API
                        solicitud_json = {
                            "cantidad_vms": str(len(vms_data)),
                            "vlans_separadas": "",
                            "vlans_usadas": "",
                            "vncs_separadas": "",
                            "conexion_topologias": conexion_topologias,
                            "topologias": topologias_json
                        }
                        
                        # Obtener token y configurar API
                        token = getattr(auth_manager, 'api_token', None) or getattr(auth_manager, 'token', None)
                        if token:
                            api_url = os.getenv('SLICE_API_URL', 'https://localhost:8443')
                            admin_email = auth_manager.get_current_user_email()
                            slice_api_local = SliceAPIService(api_url, token, admin_email)
                            
                            # Crear slice en la API
                            resultado = slice_api_local.create_slice_api(nombre, solicitud_json)
                            
                            if resultado.get('ok'):
                                print(f"{Colors.GREEN}✅ Slice '{nombre}' creado exitosamente en la API remota{Colors.ENDC}")
                                print(f"  • Nombre: {nombre}")
                                print(f"  • Topología: {topologia}")
                                print(f"  • VMs: {len(vms_data)}")
                            else:
                                print(f"{Colors.YELLOW}⚠️  Advertencia: Error al crear en API remota: {resultado.get('error')}{Colors.ENDC}")
                                print(f"{Colors.CYAN}Guardando slice localmente como respaldo...{Colors.ENDC}")
                                from shared.data_store import guardar_slice
                                slice_obj = {
                                    'nombre': nombre,
                                    'topologia': topologia,
                                    'vms': vms_data,
                                    'salida_internet': salida_internet,
                                    'usuario': admin_email,
                                    'conexión_topologias': conexion_topologias,
                                    'topologias': topologias_json
                                }
                                guardar_slice(slice_obj)
                                print(f"{Colors.GREEN}Slice guardado localmente{Colors.ENDC}")
                        else:
                            print(f"{Colors.RED}[ERROR] No se pudo obtener token de autenticación{Colors.ENDC}")
                            print(f"{Colors.CYAN}Guardando slice localmente...{Colors.ENDC}")
                            from shared.data_store import guardar_slice
                            admin_email = auth_manager.get_current_user_email()
                            slice_obj = {
                                'nombre': nombre,
                                'topologia': topologia,
                                'vms': vms_data,
                                'salida_internet': salida_internet,
                                'usuario': admin_email,
                                'conexión_topologias': conexion_topologias,
                                'topologias': topologias_json
                            }
                            guardar_slice(slice_obj)
                            print(f"{Colors.GREEN}Slice guardado localmente{Colors.ENDC}")
                        
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
            return
        elif choice == '3':
            _eliminar_slice_admin(auth_manager, slice_manager)
        elif choice == '4':
            _servicio_monitoreo()
        elif choice == '5':
            _pausar_reanudar_slice_admin(auth_manager, slice_manager)
        elif choice == '0':
            _cerrar_sesion(auth_manager, auth_service)
            break
        else:
            print(f"\n{Colors.RED}  ❌ Opción inválida{Colors.ENDC}")
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

def _submenu_ver_slice_admin(auth_manager, slice_manager):
    """Menú para ver slices"""
    _ver_slices_clientes(slice_manager, auth_manager)

def _ver_slices_clientes(slice_manager, auth_manager):
    """
    Ver TODOS los slices del sistema (de todos los usuarios, incluido el admin)
    Usa la API remota para obtener todos los slices
    
    Muestra: ID, Nombre del Slice, Estado, Fecha/Hora
    """
    from shared.ui_helpers import print_header, pause
    from shared.colors import Colors
    import os
    
    print_header(None)
    print(Colors.BOLD + "\n  TODOS LOS SLICES DEL SISTEMA" + Colors.ENDC)
    print("  " + "="*90)
    
    # Obtener token JWT
    token = getattr(auth_manager, 'api_token', None) or getattr(auth_manager, 'token', None)
    if not token:
        print(f"\n{Colors.RED}[ERROR] No se pudo obtener token de autenticación{Colors.ENDC}")
        pause()
        return
    
    # Configurar servicio API
    api_url = os.getenv('SLICE_API_URL', 'https://localhost:8443')
    user_email = auth_manager.get_current_user_email()
    slice_api_local = SliceAPIService(api_url, token, user_email)
    
    # Obtener TODOS los slices desde la API
    print(f"\n{Colors.CYAN}⏳ Cargando slices desde el servidor remoto...{Colors.ENDC}")
    all_slices = slice_api_local.list_all_slices()
    
    if not all_slices:
        print(f"\n{Colors.YELLOW}  No hay slices en el sistema{Colors.ENDC}")
        pause()
        return
    
    print(f"\n{Colors.GREEN}  Total de slices: {len(all_slices)}{Colors.ENDC}\n")
    
    # Mostrar tabla con las columnas: ID, Nombre del Slice, Usuario, Estado, Fecha/Hora
    print(f"{Colors.CYAN}{'ID':<8} {'Nombre del Slice':<35} {'Usuario':<25} {'Estado':<15} {'Fecha/Hora':<20}{Colors.ENDC}")
    print("-" * 105)
    
    for s in all_slices:
        slice_id = str(s.get('id', 'N/A'))[:7]
        nombre = str(s.get('nombre_slice', 'Sin nombre'))[:34]
        usuario = str(s.get('usuario', 'N/A'))[:24]
        estado = str(s.get('estado', 'plantilla'))[:14]
        timestamp = str(s.get('timestamp', 'N/A'))[:19]
        
        print(f"{slice_id:<8} {nombre:<35} {usuario:<25} {estado:<15} {timestamp:<20}")
    
    # Preguntar si desea ver detalles de algún slice
    print(f"\n{Colors.CYAN}¿Deseas ver los detalles de algún slice? (s/n): {Colors.ENDC}", end="")
    respuesta = input().strip().lower()
    
    if respuesta == 's':
        slice_id_input = input(f"\n{Colors.CYAN}Ingresa el ID del slice: {Colors.ENDC}").strip()
        
        # Buscar el slice por ID
        slice_encontrado = None
        for s in all_slices:
            if str(s.get('id')) == slice_id_input:
                slice_encontrado = s
                break
        
        if slice_encontrado:
            _mostrar_detalles_slice_admin(slice_encontrado)
        else:
            print(f"\n{Colors.RED}❌ No se encontró un slice con ID: {slice_id_input}{Colors.ENDC}")
    
    pause()


def _mostrar_detalles_slice_admin(slice_data):
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


def _ver_mis_slices_admin(auth_manager, slice_manager):
    """
    Ver solo los slices creados por el ADMIN ACTUAL
    Usa la API remota y filtra por el usuario admin actual
    
    Estructura de datos de la API:
    - id: INT
    - usuario: "1-Admin Name" (formato: id-Nombre)
    - nombre_slice: VARCHAR(200)
    - vms: JSON
    - estado: VARCHAR(50)
    - timestamp: TIMESTAMP
    """
    from shared.ui_helpers import print_header, pause
    from shared.colors import Colors
    import os
    
    print_header(auth_manager.current_user)
    print(Colors.BOLD + "\n  MIS SLICES (ADMIN)" + Colors.ENDC)
    print("  " + "="*80)
    
    # Obtener token JWT
    token = getattr(auth_manager, 'api_token', None) or getattr(auth_manager, 'token', None)
    if not token:
        print(f"\n{Colors.RED}[ERROR] No se pudo obtener token de autenticación{Colors.ENDC}")
        print(f"\n{Colors.YELLOW}  No tienes slices creados{Colors.ENDC}")
        pause()
        return
    
    # Configurar servicio API
    api_url = os.getenv('SLICE_API_URL', 'https://localhost:8443')
    user_email = auth_manager.get_current_user_email()
    slice_api = SliceAPIService(api_url, token, user_email)
    
    # Obtener slices desde la API remota
    print(f"\n{Colors.CYAN}⏳ Cargando mis slices desde el servidor remoto...{Colors.ENDC}")
    
    # Para admin, list_my_slices() devolverá solo sus slices (filtrado por token JWT en backend)
    slices = slice_api.list_my_slices()
    
    if not slices:
        print(f"\n{Colors.YELLOW}  📋 No tienes slices como admin{Colors.ENDC}")
        print(f"{Colors.CYAN}  Usa la opción 2 para crear tu primer slice{Colors.ENDC}")
        pause()
        return
    
    print(f"\n{Colors.GREEN}  Total de mis slices: {len(slices)}{Colors.ENDC}\n")
    
    # Mostrar tabla
    print(f"{Colors.CYAN}{'ID':<8} {'Nombre del Slice':<35} {'Estado':<15} {'Fecha/Hora':<20}{Colors.ENDC}")
    print("-" * 80)
    
    for s in slices:
        slice_id = str(s.get('id', 'N/A'))[:7]
        nombre = str(s.get('nombre_slice', 'Sin nombre'))[:34]
        estado = str(s.get('estado', 'plantilla'))[:14]
        timestamp = str(s.get('timestamp', 'N/A'))[:19]
        
        print(f"{slice_id:<8} {nombre:<35} {estado:<15} {timestamp:<20}")
    
    pause()


def _eliminar_todos_los_slices_admin(slice_manager):
    """
    Eliminar cualquier slice del sistema (Admin puede eliminar todos)
    Muestra todos los slices con el email del usuario propietario
    
    Args:
        slice_manager: Gestor de slices
    """
    from shared.ui_helpers import print_header, pause, confirm_action, show_success, show_error
    from shared.colors import Colors
    
    print_header(None)
    print(Colors.BOLD + "\n  ELIMINAR SLICE (ADMIN)" + Colors.ENDC)
    print("  " + "="*70)
    
    # Obtener todos los slices
    slices = slice_manager.get_slices()
    
    if not slices:
        show_error("No hay slices en el sistema para eliminar")
        pause()
        return
    
    print(f"\n{Colors.YELLOW}  Seleccione slice a eliminar:{Colors.ENDC}")
    print(f"{Colors.CYAN}{'N°':<4} {'Nombre del Slice':<25} {'Usuario/Email':<35}{Colors.ENDC}")
    print("-" * 64)
    
    for i, s in enumerate(slices, 1):
        nombre = getattr(s, 'name', getattr(s, 'nombre', 'Sin nombre'))[:24]
        usuario = getattr(s, 'owner', getattr(s, 'usuario', 'N/A'))[:34]
        print(f"{i:<4} {nombre:<25} {usuario:<35}")
    
    print(f"\n  0. Cancelar")
    
    choice = input(f"\n{Colors.CYAN}  Opción: {Colors.ENDC}").strip()
    
    if choice == '0':
        print(f"\n{Colors.YELLOW}  Operación cancelada{Colors.ENDC}")
        pause()
        return
    
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(slices):
            slice_seleccionado = slices[idx]
            slice_nombre = getattr(slice_seleccionado, 'name', getattr(slice_seleccionado, 'nombre', 'Sin nombre'))
            slice_usuario = getattr(slice_seleccionado, 'owner', getattr(slice_seleccionado, 'usuario', 'N/A'))
            
            print(f"\n{Colors.RED}  ⚠️  ADVERTENCIA (ADMIN):{Colors.ENDC}")
            print(f"  Esta acción eliminará permanentemente el slice")
            print(f"  '{slice_nombre}' del usuario '{slice_usuario}'")
            print(f"  y todas sus VMs asociadas")
            
            if confirm_action(f"¿Confirmar eliminación?"):
                print(f"\n{Colors.CYAN}⏳ Eliminando slice...{Colors.ENDC}")
                # Eliminar slice usando SliceManager
                if slice_manager.delete_slice(slice_seleccionado.id):
                    show_success("Slice eliminado exitosamente por Admin")
                else:
                    show_error("No se pudo eliminar el slice")
            else:
                print(f"\n{Colors.YELLOW}  Eliminación cancelada{Colors.ENDC}")
        else:
            print(f"\n{Colors.RED}  ❌ Opción inválida{Colors.ENDC}")
    
    except ValueError:
        print(f"\n{Colors.RED}  ❌ Debe ingresar un número{Colors.ENDC}")
    except Exception as e:
        show_error(f"Error: {str(e)}")
    
    pause()


def _pausar_reanudar_slice_admin(auth_manager, slice_manager):
    """Permite al admin pausar o reanudar cualquier slice del sistema usando la API remota"""
    from shared.ui_helpers import print_header, pause
    from shared.colors import Colors
    import os
    
    user = auth_manager.current_user
    print_header(user)
    print(Colors.BOLD + "\n  PAUSAR/REANUDAR SLICE (ADMIN)" + Colors.ENDC)
    print("  " + "="*80)
    
    # Obtener token JWT
    token = getattr(auth_manager, 'api_token', None) or getattr(auth_manager, 'token', None)
    if not token:
        print(f"\n{Colors.RED}[ERROR] No se pudo obtener token de autenticación{Colors.ENDC}")
        pause()
        return
    
    # Configurar servicio API
    api_url = os.getenv('SLICE_API_URL', 'https://localhost:8443')
    user_email = auth_manager.get_current_user_email()
    slice_api = SliceAPIService(api_url, token, user_email)
    
    # Obtener TODOS los slices desde la API remota (admin puede ver todos)
    print(f"\n{Colors.CYAN}⏳ Cargando slices desde el servidor remoto...{Colors.ENDC}")
    slices = slice_api.list_all_slices()
    
    if not slices:
        print(f"\n{Colors.YELLOW}  📋 No hay slices en el sistema{Colors.ENDC}")
        pause()
        return
    
    # Mostrar lista de slices con su estado
    print(f"\n{Colors.GREEN}  Slices del sistema:{Colors.ENDC}\n")
    print(f"{Colors.CYAN}{'N°':<4} {'ID':<8} {'Nombre del Slice':<30} {'Usuario':<25} {'Estado':<15}{Colors.ENDC}")
    print("-" * 82)
    
    for idx, s in enumerate(slices, 1):
        slice_id = str(s.get('id', 'N/A'))[:7]
        nombre = str(s.get('nombre_slice', 'Sin nombre'))[:29]
        usuario = str(s.get('usuario', 'N/A'))[:24]
        estado_raw = s.get('estado', 'activa')
        
        # Normalizar estado para mostrar
        if estado_raw.lower() in ['activa', 'activo']:
            estado_mostrar = 'activo'
            estado_color = Colors.GREEN
        elif estado_raw.lower() in ['pausado', 'pausada', 'inactiva', 'inactivo']:
            estado_mostrar = 'pausado'
            estado_color = Colors.YELLOW
        else:
            estado_mostrar = estado_raw
            estado_color = Colors.CYAN
        
        print(f"{idx:<4} {slice_id:<8} {nombre:<30} {usuario:<25} {estado_color}{estado_mostrar:<15}{Colors.ENDC}")
    
    print(f"\n  0. Cancelar")
    
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
            usuario = slice_sel.get('usuario', 'N/A')
            estado_raw = slice_sel.get('estado', 'activa')
            
            # Normalizar estado para determinar acción
            estado_normalizado = estado_raw.lower()
            if estado_normalizado in ['activa', 'activo']:
                accion = 'pausar'
                print(f"\n{Colors.YELLOW}¿Desea PAUSAR el slice '{nombre}' del usuario '{usuario}'?{Colors.ENDC}")
                print(f"   Estado actual: {Colors.GREEN}activo{Colors.ENDC} → Nuevo estado: {Colors.YELLOW}pausado{Colors.ENDC}")
                print(f"\n   Confirmar (s/n): ", end="")
            elif estado_normalizado in ['pausado', 'pausada', 'inactiva', 'inactivo']:
                accion = 'reanudar'
                print(f"\n{Colors.GREEN}¿Desea REANUDAR el slice '{nombre}' del usuario '{usuario}'?{Colors.ENDC}")
                print(f"   Estado actual: {Colors.YELLOW}pausado{Colors.ENDC} → Nuevo estado: {Colors.GREEN}activo{Colors.ENDC}")
                print(f"\n   Confirmar (s/n): ", end="")
            else:
                print(f"\n{Colors.RED}❌ Estado no reconocido: {estado_raw}{Colors.ENDC}")
                pause()
                return
            
            confirmacion = input().strip().lower()
            if confirmacion != 's':
                print(f"\n{Colors.YELLOW}  Operación cancelada{Colors.ENDC}")
                pause()
                return
            
            # Llamar al endpoint correspondiente
            print(f"\n{Colors.CYAN}⏳ Procesando...{Colors.ENDC}")
            if accion == 'pausar':
                result = slice_api.pausar_slice(slice_id)
            else:
                result = slice_api.reanudar_slice(slice_id)
            
            # Mostrar resultado
            if result.get('ok'):
                print(f"\n{Colors.GREEN}✅ {result.get('message')}{Colors.ENDC}")
                if accion == 'pausar':
                    print(f"   Nuevo estado: {Colors.YELLOW}pausado{Colors.ENDC}")
                else:
                    print(f"   Nuevo estado: {Colors.GREEN}activo{Colors.ENDC}")
            else:
                print(f"\n{Colors.RED}❌ Error: {result.get('error')}{Colors.ENDC}")
        else:
            print(f"\n{Colors.RED}  ❌ Opción inválida{Colors.ENDC}")
    except ValueError:
        print(f"\n{Colors.RED}  ❌ Debe ingresar un número{Colors.ENDC}")
    except Exception as e:
        print(f"\n{Colors.RED}❌ Error inesperado: {str(e)}{Colors.ENDC}")
    
    pause()


def _eliminar_slice_admin(auth_manager, slice_manager):
    """Permite al admin eliminar cualquier slice usando la API remota"""
    from shared.ui_helpers import print_header, pause
    from shared.colors import Colors
    import os
    
    user = auth_manager.current_user
    print_header(user)
    print(Colors.BOLD + "\n  ELIMINAR SLICE (ADMIN)" + Colors.ENDC)
    print("  " + "="*80)
    
    # Obtener token JWT
    token = getattr(auth_manager, 'api_token', None) or getattr(auth_manager, 'token', None)
    if not token:
        print(f"\n{Colors.RED}[ERROR] No se pudo obtener token de autenticación{Colors.ENDC}")
        pause()
        return
    
    # Configurar servicio API
    api_url = os.getenv('SLICE_API_URL', 'https://localhost:8443')
    slice_api = SliceAPIService(api_url=api_url, token=token)
    
    # Listar TODOS los slices (admin puede ver todos)
    slices = slice_api.list_all_slices()
    
    if not slices:
        print(f"\n{Colors.YELLOW}  ℹ️  No hay slices en el sistema{Colors.ENDC}")
        pause()
        return
    
    # Mostrar slices disponibles en formato tabla
    print(f"\n{Colors.BOLD}  Slices disponibles:{Colors.ENDC}")
    print("  " + "-"*95)
    print(f"  {'ID':<5} {'Nombre':<25} {'Usuario':<25} {'Estado':<15} {'Fecha/Hora':<20}")
    print("  " + "-"*95)
    
    for s in slices:
        slice_id = s.get('id', 'N/A')
        nombre = s.get('nombre_slice', 'Sin nombre')
        usuario = s.get('usuario', 'Desconocido')
        estado = s.get('estado', 'desconocido')
        timestamp = s.get('timestamp', 'N/A')
        print(f"  {slice_id:<5} {nombre:<25} {usuario:<25} {estado:<15} {timestamp:<20}")
    
    print("  " + "-"*95)
    
    # Solicitar ID del slice a eliminar
    try:
        slice_id_input = input(f"\n{Colors.YELLOW}Ingrese el ID del slice a eliminar (0 para cancelar): {Colors.ENDC}")
        slice_id = int(slice_id_input)
        
        if slice_id == 0:
            print(f"\n{Colors.YELLOW}  ℹ️  Operación cancelada{Colors.ENDC}")
            pause()
            return
        
        # Verificar que el slice existe
        slice_encontrado = None
        for s in slices:
            if s.get('id') == slice_id:
                slice_encontrado = s
                break
        
        if not slice_encontrado:
            print(f"\n{Colors.RED}  ❌ Slice no encontrado{Colors.ENDC}")
            pause()
            return
        
        # Confirmar eliminación
        nombre_slice = slice_encontrado.get('nombre_slice', 'Sin nombre')
        usuario_slice = slice_encontrado.get('usuario', 'Desconocido')
        confirmacion = input(f"\n{Colors.RED}¿Está seguro de eliminar el slice '{nombre_slice}' (ID: {slice_id}) del usuario '{usuario_slice}'? (s/n): {Colors.ENDC}").lower()
        
        if confirmacion != 's':
            print(f"\n{Colors.YELLOW}  ℹ️  Operación cancelada{Colors.ENDC}")
            pause()
            return
        
        # Llamar a la API para eliminar
        print(f"\n{Colors.YELLOW}  ⏳ Eliminando slice...{Colors.ENDC}")
        result = slice_api.eliminar_slice(slice_id)
        
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


def _ver_mis_slices_admin(auth_manager, slice_manager):
    """
    Ver solo los slices creados por el ADMIN ACTUAL
    Usa la API remota y filtra por el usuario admin actual
    
    Estructura de datos de la API:
    - id: INT
    - usuario: "1-Admin Name" (formato: id-Nombre)
    - nombre_slice: VARCHAR(200)
    - vms: JSON
    - estado: VARCHAR(50)
    - timestamp: TIMESTAMP
    """
    from shared.ui_helpers import print_header, pause
    from shared.colors import Colors
    import os
    
    print_header(auth_manager.current_user)
    print(Colors.BOLD + "\n  MIS SLICES (ADMIN)" + Colors.ENDC)
    print("  " + "="*80)
    
    # Obtener token JWT
    token = getattr(auth_manager, 'api_token', None) or getattr(auth_manager, 'token', None)
    if not token:
        print(f"\n{Colors.RED}[ERROR] No se pudo obtener token de autenticación{Colors.ENDC}")
        print(f"\n{Colors.YELLOW}  No tienes slices creados{Colors.ENDC}")
        pause()
        return
    
    # Configurar servicio API
    api_url = os.getenv('SLICE_API_URL', 'https://localhost:8443')
    user_email = auth_manager.get_current_user_email()
    slice_api = SliceAPIService(api_url, token, user_email)
    
    # Obtener slices desde la API remota
    print(f"\n{Colors.CYAN}⏳ Cargando mis slices desde el servidor remoto...{Colors.ENDC}")
    
    # Para admin, list_my_slices() devolverá solo sus slices (filtrado por token JWT en backend)
    slices = slice_api.list_my_slices()
    
    if not slices:
        print(f"\n{Colors.YELLOW}  📋 No tienes slices como admin{Colors.ENDC}")
        print(f"{Colors.CYAN}  Usa la opción 2 para crear tu primer slice{Colors.ENDC}")
        pause()
        return
    
    print(f"\n{Colors.GREEN}  Total de mis slices: {len(slices)}{Colors.ENDC}\n")
    
    # Mostrar tabla
    print(f"{Colors.CYAN}{'ID':<8} {'Nombre del Slice':<35} {'Estado':<15} {'Fecha/Hora':<20}{Colors.ENDC}")
    print("-" * 80)
    
    for s in slices:
        slice_id = str(s.get('id', 'N/A'))[:7]
        nombre = str(s.get('nombre_slice', 'Sin nombre'))[:34]
        estado = str(s.get('estado', 'plantilla'))[:14]
        timestamp = str(s.get('timestamp', 'N/A'))[:19]
        
        print(f"{slice_id:<8} {nombre:<35} {estado:<15} {timestamp:<20}")
    
    pause()


def _servicio_monitoreo():
    """Solicita credenciales de Grafana vía API y muestra la respuesta"""
    import requests
    import json
    print("\n" + Colors.CYAN + "SERVICIO DE MONITOREO" + Colors.ENDC)
    print("  " + "="*50)
    # Obtener token JWT y email del usuario desde el contexto de autenticación
    from inspect import currentframe
    frame = currentframe()
    while frame:
        if 'auth_manager' in frame.f_locals:
            auth_manager = frame.f_locals['auth_manager']
            break
        frame = frame.f_back
    else:
        auth_manager = None
    token = None
    email = None
    if auth_manager:
        if hasattr(auth_manager, 'token'):
            token = auth_manager.token
        elif hasattr(auth_manager, 'get_api_token'):
            token = auth_manager.get_api_token()
        if hasattr(auth_manager, 'get_current_user_email'):
            email = auth_manager.get_current_user_email()
    if not token:
        print(f"{Colors.RED}No se pudo obtener el token JWT de autenticación.{Colors.ENDC}")
        input("\nPresiona Enter para continuar..."); return
    url = "https://localhost:8443/monitoring/send-credentials"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    data = {"message": "Solicitud de credenciales de Grafana"}
    try:
        response = requests.post(url, headers=headers, data=json.dumps(data), verify=False)
        if response.ok:
            # Mostrar solo mensaje amigable
            print(f"\n{Colors.GREEN}Las credenciales de Grafana han sido enviadas exitosamente a {email}.{Colors.ENDC}")
            print(f"{Colors.BLUE}La contraseña ha sido enviada por correo electrónico por seguridad{Colors.ENDC}")
        else:
            print(f"{Colors.RED}Error: {response.text}{Colors.ENDC}")
    except Exception as e:
        print(f"{Colors.RED}Error al contactar la API de monitoreo: {e}{Colors.ENDC}")
    input("\nPresiona Enter para continuar...")


def _verificar_sesion(auth_service, auth_manager):
    """Verificar si la sesión con la API sigue siendo válida"""
    if not auth_service:
        return True
    
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
        user_data = auth_service.get_user_data()
        if user_data:
            print(f"\n{Colors.YELLOW}Información del usuario:{Colors.ENDC}")
            print(f"  • Nombre: {user_data.get('nombre', 'N/A')}")
            print(f"  • Email: {user_data.get('email', 'N/A')}")
            print(f"  • Rol: {user_data.get('rol', 'N/A')}")
    else:
        print(f"{Colors.RED}❌ Sesión inválida o expirada{Colors.ENDC}")
    
    pause()


def _ver_todos_slices(slice_api, auth_manager):
    """
    Ver todos los slices del sistema (Admin puede ver todos)
    
    Args:
        slice_api: Servicio de API de slices
        auth_manager: Gestor de autenticación
    """
    print_header(auth_manager.current_user)
    print(Colors.BOLD + "\n  TODOS LOS SLICES" + Colors.ENDC)
    print("  " + "="*50)
    
    try:
        print(f"\n{Colors.CYAN}⏳ Cargando slices...{Colors.ENDC}")
        # Leer todos los slices desde base_de_datos.json
        import json, os
        BASE_JSON = os.path.join(os.path.dirname(__file__), '..', '..', 'base_de_datos.json')
        if os.path.exists(BASE_JSON):
            with open(BASE_JSON, 'r', encoding='utf-8') as f:
                data = json.load(f) or []
            slices = data if isinstance(data, list) else data.get('slices', [])
        else:
            slices = []

        if not slices:
            print(f"\n{Colors.YELLOW}  � No hay slices en el sistema{Colors.ENDC}")
        else:
            print(f"\n{Colors.GREEN}  Total de slices: {len(slices)}{Colors.ENDC}\n")
            for i, s in enumerate(slices, 1):
                nombre = s.get('nombre', s.get('nombre_slice', ''))
                if not nombre or nombre == '' or nombre == s.get('id', None):
                    nombre = s.get('topologia', s.get('topology', 'sin nombre'))
                usuario = s.get('usuario', 'N/A')
                print(f"{Colors.YELLOW}  [{i}] {nombre}{Colors.ENDC}")
                print(f"      Usuario: {Colors.CYAN}{usuario}{Colors.ENDC}")
                print(f"      ID: {Colors.CYAN}{s.get('id', 'N/A')}{Colors.ENDC}")
                print(f"      VLAN: {Colors.GREEN}{s.get('vlan', 'N/A')}{Colors.ENDC}")
                print(f"      Topología: {s.get('topologia', 'N/A')}")
                print(f"      VMs: {len(s.get('vms', []))}")
                print(f"      Estado: {s.get('estado', 'activo')}")
                print()
    except Exception as e:
        from shared.ui_helpers import show_error
        show_error(f"Error al cargar slices: {str(e)}")
    pause()


def _ver_slices_por_usuario(slice_api, auth_manager):
    """Ver slices de un usuario específico"""
    if not auth_manager.has_permission("view_all_slices"):
        print(f"\n{Colors.RED}  ❌ No tiene permisos{Colors.ENDC}")
        pause()
        return
    
    print_header(auth_manager.current_user)
    print(Colors.BOLD + "\n  SLICES POR USUARIO" + Colors.ENDC)
    print("  " + "="*50)
    
    email = input(f"\n{Colors.CYAN}  Email del usuario: {Colors.ENDC}").strip()
    
    if email:
        print(f"\n{Colors.CYAN}⏳ Buscando slices de {email}...{Colors.ENDC}")
        print(f"\n{Colors.YELLOW}💡 Implementar búsqueda por usuario{Colors.ENDC}")
    
    pause()


def _crear_slice_admin(slice_api, auth_manager):
    """
    Crear un nuevo slice como administrador usando el constructor interactivo
    
    Args:
        slice_api: Servicio de API de slices
        auth_manager: Gestor de autenticación
    """
    print_header(auth_manager.current_user)
    print(Colors.BOLD + "\n  CREAR NUEVO SLICE (ADMIN)" + Colors.ENDC)
    print("  " + "="*50 + "\n")
    
    # Verificar permisos
    if not auth_manager.has_permission("create_slice"):
        print(f"\n{Colors.RED}  ❌ No tiene permisos para crear slices{Colors.ENDC}")
        print(f"{Colors.YELLOW}  Contacte al administrador{Colors.ENDC}")
        pause()
        return
    
    try:
        # Usar constructor interactivo
        builder = SliceBuilder(auth_manager.current_user)
        nombre, topologia, vms_data = builder.start()
        
        if nombre and topologia and vms_data:
            # DESHABILITADO: Crear slice en API
            # try:
            #     print(f"\n{Colors.CYAN}⏳ Creando slice en la API...{Colors.ENDC}")
            #     resultado = slice_api.create_slice(nombre, topologia, vms_data)
            #     if resultado:
            #         from shared.ui_helpers import show_success
            #         vlan = resultado.get('vlan', 'N/A')
            #         slice_id = resultado.get('id', 'N/A')
            #         show_success(f"Slice creado exitosamente")
            #         print(f"\n{Colors.GREEN}  Detalles del Slice:{Colors.ENDC}")
            #         print(f"  • ID: {slice_id}")
            #         print(f"  • VLAN: {vlan}")
            #         print(f"  • Nombre: {nombre}")
            #         print(f"  • Topología: {topologia}")
            #         print(f"  • VMs: {len(vms_data)}")
            #     else:
            #         raise Exception("API no respondió correctamente")
            # except Exception:
            #     # Ocultar logs de error de API, solo mostrar mensaje de guardado local
            
            # Trabajar solo con archivos locales
            vlan = 'local'
            slice_id = 'local'
            print(f"{Colors.CYAN}📁 Guardando slice localmente...{Colors.ENDC}")
            
            # Guardar slice y VMs en archivos SIEMPRE (solo JSON)
            try:
                from shared.data_store import guardar_slice, guardar_vms
                # Guardar slice primero para obtener el id y vlan reales
                user_email = getattr(auth_manager.current_user, 'email', None)
                user_owner = user_email if user_email else getattr(auth_manager.current_user, 'username', '')
                slice_obj = {
                    'id': slice_id,
                    'nombre': nombre,
                    'usuario': user_owner,
                    'vlan': vlan,
                    'topologia': topologia,
                    'vms': vms_data
                }
                guardar_slice(slice_obj)

                # Leer cuántas VMs existen ya en vms.json para calcular puerto_vnc
                import json, os
                VMS_JSON = os.path.join(os.path.dirname(__file__), '..', '..', 'vms.json')
                if os.path.exists(VMS_JSON):
                    with open(VMS_JSON, 'r', encoding='utf-8') as f:
                        vms_data_json = json.load(f)
                    total_vms = len(vms_data_json.get('vms', []))
                else:
                    total_vms = 0

                vms_guardar = []
                for idx, vm in enumerate(vms_data):
                    num_vm = idx + 1
                    ip = f"10.7.1.{num_vm+1}"
                    puerto_vnc = 5900 + total_vms + num_vm
                    vm_dict = dict(vm)
                    vm_dict['usuario'] = getattr(auth_manager.current_user, 'username', '')
                    vm_dict['nombre'] = f"vm{num_vm}"
                    vm_dict['ip'] = ip
                    vm_dict['puerto_vnc'] = puerto_vnc
                    vms_guardar.append(vm_dict)

                guardar_vms(vms_guardar)
                print(f"{Colors.OKGREEN}✔ Slice y VMs guardados correctamente en base_de_datos.json y vms.json{Colors.ENDC}")
            except Exception as e:
                print(f"{Colors.RED}  [WARN] No se pudo guardar en base_de_datos.json o vms.json: {e}{Colors.ENDC}")
        else:
            print(f"\n{Colors.YELLOW}  Creación cancelada{Colors.ENDC}")
    
    except Exception as e:
        from shared.ui_helpers import show_error
        show_error(f"Error inesperado: {str(e)}")
        print(f"{Colors.RED}  Detalles técnicos: {e}{Colors.ENDC}")
    
    pause()


def _editar_slice_admin(slice_api, auth_manager):
    """Llama a la función de edición de slices desde slice_editor.py (admin puede editar cualquier slice)"""
    try:
        from roles.cliente.slice_editor import editar_slice
        editar_slice(slice_api, auth_manager)
    except ImportError as e:
        print(f"\nError importando editor: {e}")
    except Exception as e:
        print(f"\nError al editar slice: {e}")

def _ver_detalles_slice(slice_api, auth_manager):
    """Ver detalles de cualquier slice"""
    if not auth_manager.has_permission("view_all_slices"):
        print(f"\n{Colors.RED}  ❌ No tiene permisos{Colors.ENDC}")
        pause()
        return
    
    print_header(auth_manager.current_user)
    print(Colors.BOLD + "\n  DETALLES DE SLICE" + Colors.ENDC)
    print("  " + "="*50)
    
    slice_id = input(f"\n{Colors.CYAN}  ID del slice: {Colors.ENDC}").strip()
    
    try:
        print(f"\n{Colors.CYAN}⏳ Cargando slices...{Colors.ENDC}")
        # Leer todos los slices desde base_de_datos.json
        import json, os
        BASE_JSON = os.path.join(os.path.dirname(__file__), '..', '..', 'base_de_datos.json')
        if os.path.exists(BASE_JSON):
            with open(BASE_JSON, 'r', encoding='utf-8') as f:
                data = json.load(f) or []
            slices = data if isinstance(data, list) else data.get('slices', [])
        else:
            slices = []

        if not slices:
            print(f"\n{Colors.YELLOW}  � No hay slices en el sistema{Colors.ENDC}")
        else:
            print(f"\n{Colors.GREEN}  Total de slices: {len(slices)}{Colors.ENDC}\n")
            for i, s in enumerate(slices, 1):
                nombre = s.get('nombre', s.get('nombre_slice', 'Sin nombre'))
                usuario = s.get('usuario', 'N/A')
                print(f"{Colors.YELLOW}  [{i}] {nombre}{Colors.ENDC}")
                print(f"      Usuario: {Colors.CYAN}{usuario}{Colors.ENDC}")
                print(f"      ID: {Colors.CYAN}{s.get('id', 'N/A')}{Colors.ENDC}")
                print(f"      VLAN: {Colors.GREEN}{s.get('vlan', 'N/A')}{Colors.ENDC}")
                print(f"      Topología: {s.get('topologia', 'N/A')}")
                print(f"      VMs: {len(s.get('vms', []))}")
                print(f"      Estado: {s.get('estado', 'activo')}")
                print()
    except Exception as e:
        from shared.ui_helpers import show_error
        show_error(f"Error al cargar slices: {str(e)}")
    pause()
    
    pause()


def _gestionar_usuarios(auth_manager):
    """Gestionar usuarios del sistema"""
    if not auth_manager.has_permission("manage_users"):
        print(f"\n{Colors.RED}  ❌ No tiene permisos para gestionar usuarios{Colors.ENDC}")
        pause()
        return
    
    print_header(auth_manager.current_user)
    print(Colors.BOLD + "\n  GESTIÓN DE USUARIOS" + Colors.ENDC)
    print("  " + "="*60)
    
    print(f"\n{Colors.YELLOW}💡 Los usuarios se gestionan en el sistema de autenticación{Colors.ENDC}")
    print(f"{Colors.CYAN}Acciones disponibles:{Colors.ENDC}")
    
    # Obtener token y configurar API service
    token = getattr(auth_manager, 'api_token', None) or getattr(auth_manager, 'token', None)
    if not token:
        print(f"\n{Colors.RED}[ERROR] No se pudo obtener token de autenticación{Colors.ENDC}")
        pause()
        return
    
    api_url = os.getenv('SLICE_API_URL', 'https://localhost:8443')
    user_email = auth_manager.get_current_user_email()
    slice_api = SliceAPIService(api_url, token, user_email)
    
    try:
        # Usar constructor interactivo
        builder = SliceBuilder(auth_manager.current_user)
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
                print(f"{Colors.CYAN}Enviando solicitud de creación de slice a la API...{Colors.ENDC}")
                resp = slice_api.create_slice_api(nombre, solicitud_json)
                if resp.get("ok"):
                    print(f"{Colors.GREEN}Slice '{nombre}' creado exitosamente en la API{Colors.ENDC}")
                    print(f"  • Nombre: {nombre}")
                    print(f"  • Topología: {topologia}")
                    print(f"  • VMs: {len(vms_data)}")
                    pause()
                    return
                else:
                    print(f"{Colors.RED}  ❌ Error al crear slice en la API: {resp.get('error')}{Colors.ENDC}")
                    print(f"{Colors.YELLOW}  Guardando localmente como respaldo...{Colors.ENDC}")
                    from shared.data_store import guardar_slice
                    user_email = getattr(auth_manager.current_user, 'email', None)
                    user_owner = user_email if user_email else getattr(auth_manager.current_user, 'username', '')
                    slice_obj = {
                        'nombre': nombre,
                        'topologia': topologia,
                        'vms': vms_data,
                        'salida_internet': salida_internet,
                        'usuario': user_owner,
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
        print(f"{Colors.RED}Error inesperado: {e}{Colors.ENDC}")
        pause()
"""Vista para ver slices del cliente"""

from shared.ui_helpers import print_header
from shared.colors import Colors
from core.services.slice_api_service import SliceAPIService
import os

def view_my_slices(user, slice_manager, auth_manager=None):
    """
    Muestra los slices del usuario obtenidos desde la API remota
    
    Campos de la BD remota:
    - id: INT AUTO_INCREMENT PRIMARY KEY
    - usuario: VARCHAR(100) NOT NULL
    - nombre_slice: VARCHAR(200) NOT NULL
    - vms: JSON (no se lista en la tabla)
    - estado: VARCHAR(50) DEFAULT 'plantilla'
    - timestamp: TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    """
    print_header(user)
    print(Colors.BOLD + "\n  MIS SLICES" + Colors.ENDC)
    print("  " + "="*80)
    
    # Obtener token y configurar API service
    token = None
    user_email = getattr(user, 'email', None) or getattr(user, 'username', '')
    
    # Intentar obtener token desde auth_manager
    if auth_manager:
        if hasattr(auth_manager, 'token'):
            token = auth_manager.token
        elif hasattr(auth_manager, 'get_api_token'):
            token = auth_manager.get_api_token()
    
    if not token:
        print(f"\n{Colors.RED}[ERROR] No se pudo obtener token de autenticación{Colors.ENDC}")
        print("\n  No tienes slices creados")
        input("\n  Presione Enter para continuar...")
        return
    
    # Configurar servicio API
    api_url = os.getenv('SLICE_API_URL', 'https://localhost:8443')
    slice_api = SliceAPIService(api_url, token, user_email)
    
    # Obtener slices desde la API remota
    print(f"\n{Colors.CYAN}⏳ Cargando slices desde el servidor...{Colors.ENDC}")
    slices = slice_api.list_my_slices()
    
    if not slices:
        print(f"\n{Colors.YELLOW}  No tienes slices creados{Colors.ENDC}")
    else:
        print(f"\n{Colors.GREEN}  Total de slices: {len(slices)}{Colors.ENDC}\n")
        
        # Encabezados de la tabla
        print(f"{Colors.CYAN}{'ID':<6} {'Nombre del Slice':<30} {'Estado':<15} {'Fecha/Hora':<20}{Colors.ENDC}")
        print("-" * 80)
        
        # Mostrar cada slice
        for s in slices:
            slice_id = str(s.get('id', 'N/A'))[:5]
            nombre = str(s.get('nombre_slice', 'Sin nombre'))[:29]
            estado = str(s.get('estado', 'plantilla'))[:14]
            timestamp = str(s.get('timestamp', 'N/A'))[:19]
            
            print(f"{slice_id:<6} {nombre:<30} {estado:<15} {timestamp:<20}")
    
    input("\n  Presione Enter para continuar...")
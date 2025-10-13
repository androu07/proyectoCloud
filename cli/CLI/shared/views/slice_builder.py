"""
Constructor interactivo de slices paso a paso
"""

from shared.ui_helpers import print_header, pause, show_success, show_error, show_info, confirm_action
from shared.colors import Colors
from shared.services.flavor_service import select_flavor, get_flavor_specs
from typing import List, Dict, Tuple


class SliceBuilder:
    """Constructor interactivo de slices"""
    
    def __init__(self, user):
        self.user = user
        self.nombre_slice = ""
        self.vms = []  # Lista de VMs: {"nombre": "vm1", "flavor": "small", ...}
        self.enlaces = []  # Lista de tuplas: (vm_origen, vm_destino)
        self.topologias = []  # Lista de topologías: {"tipo": "lineal", "vms": [0, 1, 2]}
        self.vlan = None  # Se asignará automáticamente
        self.salida_internet = "no"
    
    def start(self) -> Tuple[str, str, List[Dict], str]:
        """
        Inicia el proceso de creación de slice
        
        Returns:
            (nombre_slice, topologia_str, vms_data, salida_internet)
        """
        print_header(self.user)
        print(Colors.BOLD + "\n  CONSTRUCTOR DE SLICE" + Colors.ENDC)
        print("  " + "="*50)
        
        # Paso 1: Nombre del slice
        self.nombre_slice = self._solicitar_nombre()
        if self.nombre_slice is None:
            return None, None, None, None
        
        while True:
            print_header(self.user)
            print(Colors.BOLD + f"\n  SLICE: {self.nombre_slice}" + Colors.ENDC)
            print("  " + "="*50)
            
            # Mostrar resumen actual
            self._mostrar_resumen()
            
            # Menú de opciones
            print(Colors.YELLOW + "\n  Opciones:" + Colors.ENDC)
            topologias_count = len(self.topologias)
            max_topologias = 3
            if topologias_count >= max_topologias:
                print(f"  1. Agregar topologías de red definidas ({topologias_count}/{max_topologias}) - LÍMITE ALCANZADO")
            else:
                print(f"  1. Agregar topologías de red definidas ({topologias_count}/{max_topologias})")
            print("  2. Agregar enlaces")
            print("  3. Configurar conexión remota")
            print("  4. Configurar salida a internet")
            print("  5. Ver Resumen Detallado")
            print(Colors.GREEN + "  6. Finalizar y Crear Slice" + Colors.ENDC)
            print(Colors.RED + "  0. Cancelar" + Colors.ENDC)

            choice = input("\n  Seleccione opción: ")
            if choice == '1':
                self._agregar_topologia()
            elif choice == '2':
                self._agregar_enlaces()
            elif choice == '3':
                self._configurar_conexion_remota()
            elif choice == '4':
                self._configurar_salida_internet()
            elif choice == '5':
                self._mostrar_resumen_detallado()
            elif choice == '6':
                if self._validar_configuracion():
                    datos_slice = self._generar_datos_slice()
                    return datos_slice
                else:
                    show_error("Configuración incompleta")
                    pause()
            elif choice == '0':
                if confirm_action("¿Cancelar creación del slice?"):
                    return None, None, None, None
            # Fin del manejo de opciones
        
    def _solicitar_nombre(self) -> str:
        """Solicita el nombre del slice. Permite cancelar con '0'."""
        while True:
            nombre = input("\n  Nombre del slice (máx 20 caracteres, 0 para cancelar): ").strip()
            if nombre == '0':
                print("\nOperación cancelada. Regresando al menú principal...")
                return None
            if not nombre:
                show_error("El nombre no puede estar vacío")
                continue
            if len(nombre) > 20:
                show_error("El nombre debe tener máximo 20 caracteres")
                continue
            return nombre
                # Línea inválida eliminada
    # Método _agregar_nodos eliminado por estar duplicado y mal indentado

    def _agregar_topologia(self):
        """Agregar topología"""
        # Verificar límite de topologías
        if len(self.topologias) >= 3:
            show_error("Ya has alcanzado el límite máximo de 3 topologías por slice.")
            pause()
            return
        # Ir directamente a la lista de topologías predefinidas
        self._agregar_topologia_con_vms()

    def _configurar_conexion_remota(self):
        if not self.vms:
            show_error("Primero debe agregar VMs.")
            pause()
            return
        print("\nSeleccione las VMs que tendrán conexión remota (separadas por coma, ej: 1,3):")
        for i, vm in enumerate(self.vms, 1):
            actual = vm.get("conexion_remota", "no")
            print(f"  {i}. {vm['nombre']} (Conexión remota: {actual})")
        seleccion = input("Ingrese números de VMs: ").strip()
        indices = set()
        if seleccion:
            try:
                indices = set(int(x.strip())-1 for x in seleccion.split(",") if x.strip().isdigit())
            except Exception:
                show_error("Selección inválida.")
                pause()
                return
        for i, vm in enumerate(self.vms):
            vm["conexion_remota"] = "si" if i in indices else "no"
        show_success("Configuración de conexión remota actualizada.")
        pause()
        return

    def _configurar_salida_internet(self):
        print("\n¿Toda la topología debe tener salida a internet?")
        print("  1. Sí")
        print("  2. No")
        opt = input("Seleccione opción [2]: ").strip()
        if opt == '1':
            self.salida_internet = "si"
        else:
            self.salida_internet = "no"
        show_success(f"Salida a internet configurada: {self.salida_internet.upper()}")
        pause()
    
    def _agregar_vms_individuales(self):
        """Agregar VMs una por una"""
        while True:
            num_vm = len(self.vms) + 1
            print(f"\n  VM {num_vm}:")
            # Seleccionar flavor
            flavor = select_flavor()
            specs = get_flavor_specs(flavor)
            print("    Seleccionar imagen:")
            print("      1. cirros-0.5.1-x86_64-disk.img")
            print("      2. ubuntu-18.04-minimal-cloudimg-amd64.img")
            print("      3. generic_alpine-3.20.0-x86_64-bios-cloudinit-r0.qcow2")
            img_opt = input("      Opción [1]: ").strip()
            if img_opt == '2':
                imagen = "ubuntu-18.04-minimal-cloudimg-amd64.img"
            elif img_opt == '3':
                imagen = "generic_alpine-3.20.0-x86_64-bios-cloudinit-r0.qcow2"
            else:
                imagen = "cirros-0.5.1-x86_64-disk.img"
            vm_data = {
                "nombre": f"vm{num_vm}",
                "flavor": flavor,
                "cpu": specs['cpu'],
                "memory": specs['memory'],
                "disk": specs['disk'],
                "imagen": imagen
            }
            self.vms.append(vm_data)
            show_success(f"VM{num_vm} agregada ({flavor})")
            if not confirm_action("¿Agregar otra VM?"):
                break
    
    def _agregar_topologia_con_vms(self):
        """Agregar una topología completa con sus VMs"""
        print("\n  Topologías disponibles:")
        print("  1. Lineal (mínimo 2 VMs)")
        print("  2. Anillo (mínimo 3 VMs)")
        print("  3. Árbol (mínimo 5 VMs)")

        topo_choice = input("\n  Seleccione topología (0 para cancelar): ")
        if topo_choice == '0':
            print("\nOperación cancelada. Regresando al menú principal...")
            return

        topo_tipos = {
            '1': ('lineal', 2),
            '2': ('anillo', 3),
            '3': ('arbol', 5)
        }

        topo_tipo, min_vms = topo_tipos.get(topo_choice, ('lineal', 2))

        # Validación de cantidad máxima de VMs según cantidad de topologías
        topologias_actuales = len(self.topologias) + 1  # Incluyendo la que se va a agregar
        vms_actuales = len(self.vms)
        if topologias_actuales == 1:
            max_vms_total = 9
        else:
            max_vms_total = 12

        while True:
            try:
                num_vms_input = input(f"\n  Número de VMs para {topo_tipo} (mínimo {min_vms}, máximo {max_vms_total - vms_actuales}, 0 para cancelar): ")
                if num_vms_input == '0':
                    print("\nOperación cancelada. Regresando al menú principal...")
                    return
                num_vms = int(num_vms_input)
                if num_vms < min_vms:
                    show_error(f"La topología {topo_tipo} requiere al menos {min_vms} VMs.")
                elif num_vms > (max_vms_total - vms_actuales):
                    show_error(f"No puedes superar el máximo permitido de {max_vms_total} VMs en total para este slice.")
                else:
                    break
            except ValueError:
                show_error("Debe ingresar un número válido.")

        # Crear VMs con distintos flavors
        inicio_vm = len(self.vms) + 1
        vms_indices = []

        for i in range(num_vms):
            num_vm = inicio_vm + i
            print(f"\n  Seleccionando flavor para la VM {num_vm}:")
            # Solicitar flavor para cada VM de manera individual
            flavor = select_flavor()
            specs = get_flavor_specs(flavor)
            print("    Seleccionar imagen:")
            print("      1. cirros-0.5.1-x86_64-disk.img")
            print("      2. ubuntu-18.04-minimal-cloudimg-amd64.img")
            print("      3. generic_alpine-3.20.0-x86_64-bios-cloudinit-r0.qcow2")
            img_opt = input("      Opción [1]: ").strip()
            if img_opt == '2':
                imagen = "ubuntu-18.04-minimal-cloudimg-amd64.img"
            elif img_opt == '3':
                imagen = "generic_alpine-3.20.0-x86_64-bios-cloudinit-r0.qcow2"
            else:
                imagen = "cirros-0.5.1-x86_64-disk.img"
            vm_data = {
                "nombre": f"vm{num_vm}",
                "flavor": flavor,
                "cpu": specs['cpu'],
                "memory": specs['memory'],
                "disk": specs['disk'],
                "imagen": imagen
            }
            self.vms.append(vm_data)
            vms_indices.append(len(self.vms) - 1)
            show_success(f"VM{num_vm} agregada ({flavor})")

        # Guardar topología
        self.topologias.append({
            "tipo": topo_tipo,
            "vms": vms_indices,
            "num_vms": num_vms
        })

        # Crear enlaces automáticamente según la topología
        self._crear_enlaces_automaticos(topo_tipo, vms_indices)

        show_success(f"Topología {topo_tipo} con {num_vms} VMs agregada")
        pause()
        return


    
    def _crear_enlaces_automaticos(self, tipo: str, vms_indices: List[int]):
        """Crea enlaces automáticos según el tipo de topología"""
        if tipo == 'lineal':
            for i in range(len(vms_indices) - 1):
                self.enlaces.append((vms_indices[i], vms_indices[i + 1]))
        elif tipo == 'anillo':
            for i in range(len(vms_indices)):
                next_idx = (i + 1) % len(vms_indices)
                self.enlaces.append((vms_indices[i], vms_indices[next_idx]))
        elif tipo == 'arbol':
            for i in range(1, len(vms_indices)):
                parent = (i - 1) // 2
                self.enlaces.append((vms_indices[parent], vms_indices[i]))
    
    def _agregar_enlaces(self):
        """Agregar enlaces manualmente entre VMs"""
        if len(self.vms) < 2:
            show_error("Necesita al menos 2 VMs para crear enlaces")
            pause()
            return

        print_header(self.user)
        print(Colors.BOLD + "\n  AGREGAR ENLACES" + Colors.ENDC)
        print("  " + "="*50)

        # Mostrar topologías existentes
        if self.topologias:
            print("\n  Topologías existentes:")
            for idx, topo in enumerate(self.topologias, 1):
                tipo = topo.get('tipo', 'N/A')
                vms_idx = topo.get('vms', [])
                vms_nombres = ', '.join(self.vms[i]['nombre'] for i in vms_idx)
                print(f"  {idx}. Tipo: {tipo} | VMs: {vms_nombres}")
        else:
            print("\n  No hay topologías existentes.")

        # Mostrar VMs disponibles
        print("\n  VMs disponibles:")
        for i, vm in enumerate(self.vms, 1):
            print(f"  {i}. {vm['nombre']} ({vm['flavor']})")

        # Mostrar enlaces existentes
        if self.enlaces:
            print("\n  Enlaces existentes:")
            for origen, destino in self.enlaces:
                print(f"  • {self.vms[origen]['nombre']} ↔ {self.vms[destino]['nombre']}")

        while True:
            print()
            origen = input("  VM origen (número, 0 para cancelar, o Enter para terminar): ")
            if origen == '0':
                print("\nOperación cancelada. Regresando al menú principal...")
                return
            if not origen:
                break
            destino = input("  VM destino (0 para cancelar): ")
            if destino == '0':
                print("\nOperación cancelada. Regresando al menú principal...")
                return

            try:
                origen_num = int(origen)
                destino_num = int(destino)

                # Convertir de números basados en 1 a índices basados en 0
                origen_idx = origen_num - 1
                destino_idx = destino_num - 1

                if 0 <= origen_idx < len(self.vms) and 0 <= destino_idx < len(self.vms):
                    if origen_idx != destino_idx:
                        # Evitar duplicados
                        enlace = (min(origen_idx, destino_idx), max(origen_idx, destino_idx))
                        if enlace not in self.enlaces:
                            self.enlaces.append(enlace)
                            show_success(f"Enlace creado: {self.vms[origen_idx]['nombre']} ↔ {self.vms[destino_idx]['nombre']}")
                        else:
                            show_error("Este enlace ya existe")
                    else:
                        show_error("No puede enlazar una VM consigo misma")
                else:
                    show_error("Índices de VM inválidos")
            except ValueError:
                show_error("Debe ingresar números")
    
    def _mostrar_resumen(self):
        """Muestra resumen compacto"""
        remotas = sum(1 for vm in self.vms if vm.get('conexion_remota', 'no') == 'si')
        salida = getattr(self, 'salida_internet', 'no') or 'no'
        print(f"\n  VMs: {len(self.vms)} | Enlaces: {len(self.enlaces)} | Topologías: {len(self.topologias)} | Remotas: {remotas} | Internet: {salida}")
    
    def _mostrar_resumen_detallado(self):
        """Muestra resumen completo de la configuración"""
        print_header(self.user)
        print(Colors.BOLD + f"\n  RESUMEN: {self.nombre_slice}" + Colors.ENDC)
        print("  " + "="*50)
        
        # Flags globales
        print(Colors.YELLOW + "\n  Opciones del Slice:" + Colors.ENDC)
        salida = getattr(self, 'salida_internet', 'no') or 'no'
        print(f"  • Salida a internet: {salida}")

        # VMs
        print(Colors.YELLOW + "\n  Máquinas Virtuales:" + Colors.ENDC)
        for i, vm in enumerate(self.vms, 1):
            conexion = vm.get('conexion_remota', 'no')
            imagen = vm.get('imagen', 'cirros-0.5.1-x86_64-disk.img')
            print(f"  {i}. {vm['nombre']} - Flavor: {vm['flavor']} ({vm['cpu']} CPU, {vm['memory']}MB RAM, {vm['disk']}GB) | Imagen: {imagen} | Conexión remota: {conexion}")
        
        # Enlaces
        print(Colors.YELLOW + "\n  Enlaces:" + Colors.ENDC)
        if self.enlaces:
            for origen, destino in self.enlaces:
                print(f"  • {self.vms[origen]['nombre']} ↔ {self.vms[destino]['nombre']}")
        else:
            print("  (Sin enlaces)")
        
        # Topologías
        print(Colors.YELLOW + "\n  Topologías:" + Colors.ENDC)
        if self.topologias:
            for topo in self.topologias:
                vms_nombres = [self.vms[idx]['nombre'] for idx in topo['vms']]
                print(f"  • {topo['tipo']}: {', '.join(vms_nombres)}")
        else:
            print("  (Manual/Sin topología definida)")
        
        pause()
    
    def _es_conexo(self) -> bool:
        """Verifica si todas las VMs están conectadas en un solo grupo (grafo conexo)"""
        if not self.vms or not self.enlaces:
            return False
        n = len(self.vms)
        visitados = set()
        from collections import deque
        q = deque()
        q.append(0)
        while q:
            actual = q.popleft()
            if actual in visitados:
                continue
            visitados.add(actual)
            for a, b in self.enlaces:
                if a == actual and b not in visitados:
                    q.append(b)
                elif b == actual and a not in visitados:
                    q.append(a)
        return len(visitados) == n

    def _validar_configuracion(self) -> bool:
        """Valida que la configuración sea válida"""
        if len(self.vms) == 0:
            show_error("Debe agregar al menos una VM")
            return False
        if not self._es_conexo():
            show_error("No se puede crear el slice: las topologías no están unidas. Todas las VMs deben estar conectadas.")
            return False
        return True
    
    def _generar_datos_slice(self) -> Tuple[str, str, List[Dict], str, str, list]:
        """
        Genera los datos finales para enviar a la API
        
        Returns:
            (nombre_slice, topologia_str, vms_data, salida_internet)
        """
        # Generar string de topología
        if self.topologias:
            topo_parts = []
            for topo in self.topologias:
                topo_parts.append(f"{topo['tipo']}-{topo['num_vms']}VMS")
            topologia_str = "+".join(topo_parts)
        else:
            topologia_str = f"manual-{len(self.vms)}VMS"

        # Preparar datos de VMs (se calcularán IPs y puertos en el backend)
        vms_data = []
        for vm in self.vms:
            vms_data.append({
                "nombre": vm['nombre'],
                "flavor": vm['flavor'],
                "cpu": vm['cpu'],
                "memory": vm['memory'],
                "disk": vm['disk'],
                "conexion_remota": vm.get('conexion_remota', 'no'),
                "imagen": vm.get('imagen', '')
            })

        # Construir el campo 'conexión_topologias' según la cantidad de topologías
        enlaces_str = ''
        if len(self.topologias) == 2 and self.enlaces:
            # Solo un enlace: el último
            origen, destino = self.enlaces[-1]
            enlaces_str = f"{self.vms[origen]['nombre']}-{self.vms[destino]['nombre']}"
        elif len(self.topologias) == 3 and len(self.enlaces) >= 2:
            # Dos enlaces: los dos últimos
            enlaces = self.enlaces[-2:]
            enlaces_str = ';'.join(f"{self.vms[o]['nombre']}-{self.vms[d]['nombre']}" for o, d in enlaces)
        # Si hay 1 topología o no hay enlaces, queda vacío

        # Preparar lista de topologías para el JSON final
        topologias_json = []
        for topo in self.topologias:
            vms_json = []
            for idx in topo.get('vms', []):
                vm = self.vms[idx]
                vms_json.append({
                    "nombre": vm['nombre'],
                    "cores": str(vm.get('cpu', 1)),
                    "ram": f"{vm.get('memory', 512)}M",
                    "almacenamiento": f"{vm.get('disk', 1)}G",
                    "puerto_vnc": "",
                    "image": vm.get('imagen', ''),
                    "conexiones_vlans": "",
                    "acceso": vm.get('conexion_remota', 'no'),
                    "server": ""
                })
            topologias_json.append({
                "nombre": topo.get('tipo', ''),
                "cantidad_vms": str(len(topo.get('vms', []))),
                "internet": self.salida_internet,
                "vms": vms_json
            })
        return self.nombre_slice, topologia_str, vms_data, self.salida_internet, enlaces_str, topologias_json
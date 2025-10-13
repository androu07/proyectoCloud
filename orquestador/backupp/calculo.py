#!/usr/bin/env python3
"""
Script para rellenar automáticamente campos en el JSON de configuración de VMs
- puerto_vnc: según round-robin de workers
- conexiones_vlans: según topología
- vlans_usadas: rango de VLANs utilizadas
"""

import json
import sys
from typing import Dict, List, Tuple


class TopologyVLANAssigner:
    def __init__(self):
        self.workers = ['worker1', 'worker2', 'worker3']
    
    def parse_range(self, range_str: str) -> Tuple[int, int]:
        """
        Parsea un rango del tipo "21;30" y retorna (min, max)
        """
        parts = range_str.split(';')
        return int(parts[0]), int(parts[1])
    
    def assign_vnc_ports(self, vms: List[Dict], vnc_range: str) -> List[Dict]:
        """
        Asigna puertos VNC según round-robin de workers
        
        Cada worker tiene su propio contador de puertos.
        Ejemplo: vnc_range = "21;30"
        - worker1: VMs 0,3,6,... usan puertos 21,22,23,...
        - worker2: VMs 1,4,7,... usan puertos 21,22,23,...
        - worker3: VMs 2,5,8,... usan puertos 21,22,23,...
        """
        start_port, end_port = self.parse_range(vnc_range)
        
        # Contador de VMs por worker
        worker_counters = {
            'worker1': 0,
            'worker2': 0,
            'worker3': 0
        }
        
        for vm in vms:
            server = vm.get('server', '')
            
            if server in worker_counters:
                # Asignar puerto: start_port + número de VMs ya asignadas a este worker
                port = start_port + worker_counters[server]
                vm['puerto_vnc'] = str(port)
                worker_counters[server] += 1
            else:
                vm['puerto_vnc'] = ""
        
        return vms
    
    def get_topology_links(self, topology_name: str, num_vms: int) -> List[Tuple[int, int]]:
        """
        Retorna lista de enlaces (vm1, vm2) según la topología
        Las VMs están numeradas desde 1
        
        Topologías soportadas: lineal, anillo, arbol
        """
        topology_name = topology_name.lower()
        
        if topology_name == 'lineal' or topology_name == 'linear':
            return self.linear_links(num_vms)
        elif topology_name == 'anillo' or topology_name == 'ring':
            return self.ring_links(num_vms)
        elif topology_name == 'arbol' or topology_name == 'tree':
            # Por defecto: árbol binario (2 ramas)
            return self.tree_links(num_vms, branches=2)
        else:
            raise ValueError(f"Topología desconocida: {topology_name}. "
                           f"Topologías soportadas: lineal, anillo, arbol")
    
    def linear_links(self, num_vms: int) -> List[Tuple[int, int]]:
        """vm1--vm2--vm3--..."""
        return [(i, i+1) for i in range(1, num_vms)]
    
    def ring_links(self, num_vms: int) -> List[Tuple[int, int]]:
        """vm1--vm2--vm3--...--vm1"""
        links = [(i, i+1) for i in range(1, num_vms)]
        links.append((num_vms, 1))  # Cerrar el anillo
        return links
    
    def tree_links(self, num_vms: int, branches: int = 2) -> List[Tuple[int, int]]:
        """Árbol con número de ramas por nodo"""
        links = []
        vm_counter = 2  # Empezar desde vm2 (vm1 es raíz)
        parent_queue = [1]
        
        while vm_counter <= num_vms and parent_queue:
            next_parents = []
            for parent in parent_queue:
                for _ in range(branches):
                    if vm_counter > num_vms:
                        break
                    links.append((parent, vm_counter))
                    next_parents.append(vm_counter)
                    vm_counter += 1
                if vm_counter > num_vms:
                    break
            parent_queue = next_parents
        
        return links
    
    def assign_vlans_to_vms(self, links: List[Tuple[int, int]], num_vms: int, 
                           vlan_range: str) -> Tuple[Dict[int, List[int]], int, int]:
        """
        Asigna VLANs a cada VM según los enlaces
        
        Returns:
            - dict: {vm_number: [list of vlans]}
            - min_vlan: VLAN mínima usada
            - max_vlan: VLAN máxima usada
        """
        start_vlan, end_vlan = self.parse_range(vlan_range)
        
        # Inicializar diccionario de VLANs por VM
        vm_vlans = {i: [] for i in range(1, num_vms + 1)}
        
        # Asignar una VLAN a cada enlace
        current_vlan = start_vlan
        
        for vm1, vm2 in links:
            if current_vlan > end_vlan:
                raise ValueError(f"No hay suficientes VLANs disponibles. "
                               f"Necesitas al menos {len(links)} VLANs.")
            
            # Agregar esta VLAN a ambas VMs del enlace
            if current_vlan not in vm_vlans[vm1]:
                vm_vlans[vm1].append(current_vlan)
            if current_vlan not in vm_vlans[vm2]:
                vm_vlans[vm2].append(current_vlan)
            
            current_vlan += 1
        
        max_vlan_used = current_vlan - 1
        
        # Ordenar las VLANs de cada VM
        for vm in vm_vlans:
            vm_vlans[vm].sort()
        
        return vm_vlans, start_vlan, max_vlan_used
    
    def parse_topology_connections(self, connections_str: str) -> List[Tuple[str, str]]:
        """
        Parsea el string de conexiones entre topologías
        Ejemplo: "vm1-vm6" -> [("vm1", "vm6")]
        Ejemplo: "vm2-vm6;vm7-vm11" -> [("vm2", "vm6"), ("vm7", "vm11")]
        """
        if not connections_str or connections_str.strip() == "":
            return []
        
        connections = []
        for connection in connections_str.split(';'):
            if '-' in connection:
                vm1, vm2 = connection.strip().split('-')
                connections.append((vm1.strip(), vm2.strip()))
        
        return connections

    def find_vm_by_name(self, vm_name: str, topologias: List[Dict]) -> Tuple[int, int, Dict]:
        """
        Encuentra una VM por nombre en todas las topologías
        Retorna: (topology_index, vm_index, vm_dict)
        """
        for topo_idx, topo in enumerate(topologias):
            for vm_idx, vm in enumerate(topo['vms']):
                if vm['nombre'] == vm_name:
                    return topo_idx, vm_idx, vm
        raise ValueError(f"VM '{vm_name}' no encontrada en ninguna topología")

    def pre_process_json(self, config: Dict) -> Dict:
        """
        Pre-procesa el JSON inicial completando los campos faltantes:
        - vlans_separadas: calculado por ID
        - vncs_separadas: calculado por ID  
        - server: asignado por round-robin
        """
        slice_id = int(config['id_slice'])
        
        # 1. Calcular vlans_separadas
        max_vlan = int(slice_id * 10 * 1.5)
        min_vlan = max_vlan - 14
        config['vlans_separadas'] = f"{min_vlan};{max_vlan}"
        
        # 2. Calcular vncs_separadas
        max_vnc = slice_id * 4
        min_vnc = max_vnc - 3
        config['vncs_separadas'] = f"{min_vnc};{max_vnc}"
        
        # 3. Asignar servers por round-robin global
        vm_counter = 0
        for topo in config['topologias']:
            for vm in topo['vms']:
                if not vm.get('server') or vm.get('server') == "":
                    worker_index = vm_counter % 3
                    vm['server'] = self.workers[worker_index]
                    vm_counter += 1
        
        return config

    def fill_json(self, input_file: str, output_file: str):
        """
        Procesa el archivo JSON de entrada y genera el archivo de salida con asignaciones VLAN/VNC
        """
        try:
            print(f"📂 Leyendo archivo de entrada: {input_file}")
            
            # Leer archivo de entrada
            with open(input_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            print(f"✅ Archivo cargado correctamente")
            
            # Pre-procesar el JSON si hay campos vacíos
            needs_preprocessing = (
                not config.get('vlans_separadas') or 
                not config.get('vncs_separadas') or
                any(not vm.get('server') for topo in config.get('topologias', []) for vm in topo.get('vms', []))
            )
            
            if needs_preprocessing:
                print("🔄 Pre-procesando JSON para completar campos faltantes...")
                config = self.pre_process_json(config)
                print("✅ Pre-procesamiento completado")
            
            # Procesar cada topología
            all_vms = []
            vlan_range_min, vlan_range_max = self.parse_range(config['vlans_separadas'])
            current_vlan = vlan_range_min  # Contador global de VLANs
            global_vlan_min = current_vlan
            global_vlan_max = current_vlan - 1
            
            print(f"\n🏗️ Procesando {len(config['topologias'])} topología(s)...")
            
            for topo_idx, topology in enumerate(config['topologias']):
                print(f"\n📐 Procesando topología {topo_idx + 1}: {topology.get('nombre', 'Sin nombre')}")
                
                vms = topology['vms']
                num_vms = len(vms)
                topology_name = topology.get('nombre', '').lower()
                
                # Obtener enlaces según la topología
                links = self.get_topology_links(topology_name, num_vms)
                print(f"   Enlaces generados: {links}")
                
                # Asignar VLANs a VMs usando el contador global
                vm_vlans = {i: [] for i in range(1, num_vms + 1)}
                
                # Asignar una VLAN única a cada enlace
                for vm1, vm2 in links:
                    if current_vlan > vlan_range_max:
                        raise ValueError(f"No hay suficientes VLANs disponibles. VLAN {current_vlan} excede el máximo {vlan_range_max}")
                    
                    # Agregar esta VLAN a ambas VMs del enlace
                    if current_vlan not in vm_vlans[vm1]:
                        vm_vlans[vm1].append(current_vlan)
                    if current_vlan not in vm_vlans[vm2]:
                        vm_vlans[vm2].append(current_vlan)
                    
                    current_vlan += 1
                    global_vlan_max = max(global_vlan_max, current_vlan - 1)
                
                # Asignar VLANs a cada VM
                for vm_idx, vm in enumerate(vms, 1):
                    vlans = vm_vlans[vm_idx]
                    vlan_list = []
                    
                    # Agregar VLAN 999 PRIMERO si el VM tiene acceso = "si"
                    if vm.get('acceso', '').lower() == 'si':
                        vlan_list.append('999')
                    
                    # Agregar las VLANs de topología (ordenadas)
                    vlans.sort()
                    vlan_list.extend(map(str, vlans))
                    
                    vm['conexiones_vlans'] = ','.join(vlan_list)
                    
                    all_vms.append(vm)
                    print(f"   VM {vm['nombre']}: VLANs {vm['conexiones_vlans']}")
            
            # Procesar conexiones inter-topología
            if config.get('conexion_topologias') or config.get('conexión_topologias'):
                conexiones_key = 'conexión_topologias' if 'conexión_topologias' in config else 'conexion_topologias'
                print(f"\n🔗 Procesando conexiones inter-topología: {config[conexiones_key]}")
                connections = self.parse_topology_connections(config[conexiones_key])
                
                for vm1_name, vm2_name in connections:
                    try:
                        # Encontrar ambas VMs
                        topo1_idx, vm1_idx, vm1 = self.find_vm_by_name(vm1_name, config['topologias'])
                        topo2_idx, vm2_idx, vm2 = self.find_vm_by_name(vm2_name, config['topologias'])
                        
                        # Verificar que no exceda el rango
                        if current_vlan > vlan_range_max:
                            raise ValueError(f"No hay suficientes VLANs para conexión inter-topología. VLAN {current_vlan} excede el máximo {vlan_range_max}")
                        
                        # Asignar nueva VLAN para la conexión inter-topología
                        inter_vlan = current_vlan
                        current_vlan += 1
                        global_vlan_max = max(global_vlan_max, inter_vlan)
                        
                        # Agregar VLAN a ambas VMs
                        if vm1.get('conexiones_vlans'):
                            vm1['conexiones_vlans'] += f',{inter_vlan}'
                        else:
                            vm1['conexiones_vlans'] = str(inter_vlan)
                        
                        if vm2.get('conexiones_vlans'):
                            vm2['conexiones_vlans'] += f',{inter_vlan}'
                        else:
                            vm2['conexiones_vlans'] = str(inter_vlan)
                        
                        print(f"   Conexión {vm1_name} ↔ {vm2_name}: VLAN {inter_vlan}")
                        
                    except ValueError as e:
                        print(f"   ⚠️ Error en conexión {vm1_name}-{vm2_name}: {e}")
            
            # Asignar puertos VNC
            print(f"\n🖥️ Asignando puertos VNC...")
            vnc_range = config['vncs_separadas']
            all_vms = self.assign_vnc_ports(all_vms, vnc_range)
            
            # Actualizar vlans_usadas
            config['vlans_usadas'] = f"{global_vlan_min};{global_vlan_max}"
            
            print(f"\n✅ Procesamiento completado")
            print(f"VLANs utilizadas: {config['vlans_usadas']}")
            
            # Guardar archivo de salida
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            
            print(f"\n💾 Archivo guardado: {output_file}")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def print_summary(self, config: Dict):
        """
        Imprime un resumen de la configuración generada
        """
        print("\n" + "="*60)
        print("RESUMEN DE CONFIGURACIÓN")
        print("="*60)
        
        print(f"\nSlice ID: {config['id_slice']}")
        print(f"Total VMs: {config['cantidad_vms']}")
        print(f"VLANs disponibles: {config['vlans_separadas']}")
        print(f"VLANs usadas: {config['vlans_usadas']}")
        print(f"Puertos VNC disponibles: {config['vncs_separadas']}")
        
        for topo_idx, topo in enumerate(config['topologias'], 1):
            print(f"\nTopología {topo_idx}:")
            print(f"  Nombre: {topo['nombre']}")
            print(f"  Cantidad VMs: {topo.get('cantidad_vms', 'N/A')}")
            print(f"  Internet: {topo.get('internet', 'N/A')}")
            
            if 'workers' in topo:
                print(f"  Workers: {len(topo['workers'])}")
                for worker_idx, worker in enumerate(topo['workers'], 1):
                    print(f"    Worker {worker_idx}:")
                    print(f"      VMs: {len(worker['vms'])}")
                    for vm in worker['vms']:
                        print(f"        VM {vm['vm_id']}: VLAN {vm['vlan']}, VNC {vm['vnc']}")
            
            if 'vms' in topo:
                print(f"  VMs configuradas: {len(topo['vms'])}")
                for vm in topo['vms']:
                    vnc_info = vm.get('puerto_vnc', vm.get('vnc', 'N/A'))
                    vlan_info = vm.get('conexiones_vlans', vm.get('vlan', 'N/A'))
                    print(f"    • {vm['nombre']}: VNC {vnc_info}, VLAN {vlan_info}")


def main():
    """
    Función principal
    """
    if len(sys.argv) < 2:
        print("Uso: python3 calculo.py <input.json> [output.json]")
        print("\nEjemplo:")
        print("  python3 calculo.py ejemplo.json")
        print("  python3 calculo.py ejemplo.json salida.json")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    try:
        # Leer JSON de entrada
        with open(input_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        print(f"Leyendo configuracion desde: {input_file}")
        
        # Crear el asignador
        assigner = TopologyVLANAssigner()
        
        # Procesar el JSON
        print("Procesando configuracion...")
        if output_file:
            assigner.fill_json(input_file, output_file)
        else:
            # Si no hay archivo de salida, crear uno temporal para procesar
            temp_output = "temp_output.json"
            assigner.fill_json(input_file, temp_output)
            
            # Leer el resultado y mostrarlo
            with open(temp_output, 'r', encoding='utf-8') as f:
                filled_config = json.load(f)
            
            print("\n" + "="*60)
            print("JSON GENERADO:")
            print("="*60)
            print(json.dumps(filled_config, indent=4, ensure_ascii=False))
            
            # Limpiar archivo temporal
            import os
            os.remove(temp_output)
            return
        
        # El procesamiento ya se hizo arriba
        if output_file:
            print(f"\n✅ Configuracion guardada en: {output_file}")
        
        # Leer el archivo final para mostrar resumen
        final_file = output_file if output_file else temp_output
        with open(final_file, 'r', encoding='utf-8') as f:
            filled_config = json.load(f)
        
        # Mostrar resumen
        assigner.print_summary(filled_config)
    
    except FileNotFoundError:
        print(f"Error: No se encontro el archivo {input_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error al parsear JSON: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"Error de validacion: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error inesperado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
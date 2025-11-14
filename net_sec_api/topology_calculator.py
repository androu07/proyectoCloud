#!/usr/bin/env python3
"""
Módulo para generar enlaces de topologías de red
- Generación de enlaces según tipo de topología (1vm, lineal, anillo, árbol)
- Procesamiento de conexiones inter-topología
"""

from typing import List, Tuple


class TopologyLinksGenerator:
    def __init__(self):
        pass
    
    def get_topology_links(self, topology_name: str, num_vms: int) -> List[Tuple[int, int]]:
        """
        Retorna lista de enlaces (vm1, vm2) según la topología
        Las VMs están numeradas desde 1 dentro de cada topología
        
        Topologías soportadas: 1vm, lineal, anillo, arbol
        """
        topology_name = topology_name.lower()
        
        if topology_name == '1vm':
            return []  # 1vm no tiene conexiones internas
        elif topology_name == 'lineal' or topology_name == 'linear':
            return self.linear_links(num_vms)
        elif topology_name == 'anillo' or topology_name == 'ring':
            return self.ring_links(num_vms)
        elif topology_name == 'arbol' or topology_name == 'tree':
            # Por defecto: árbol binario (2 ramas)
            return self.tree_links(num_vms, branches=2)
        else:
            raise ValueError(f"Topología desconocida: {topology_name}. "
                           f"Topologías soportadas: 1vm, lineal, anillo, arbol")
    
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
    
    def parse_vms_connections(self, connections_str: str) -> List[Tuple[str, str]]:
        """
        Parsea el string de conexiones entre vms que aparece en el parametro "conexiones_vms"
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

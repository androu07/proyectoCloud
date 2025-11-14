#!/usr/bin/env python3
"""
VNC Manager - Gestión de puertos VNC reservados por slice
Pool de puertos: 0-1000 por worker
"""

import os
from typing import Dict, List, Optional, Set
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import logging

logger = logging.getLogger(__name__)

# Configuración MongoDB
MONGODB_URL = os.getenv('MONGODB_URL', 'mongodb://localhost:27017/vncs_db')
VNC_PORT_MIN = 1
VNC_PORT_MAX = 1000

class VNCPortManager:
    """Gestor de puertos VNC con MongoDB"""
    
    def __init__(self):
        """Inicializa conexión a MongoDB"""
        try:
            self.client = MongoClient(MONGODB_URL, serverSelectionTimeoutMS=5000)
            # Verificar conexión
            self.client.admin.command('ping')
            
            self.db = self.client.get_default_database()
            self.collection = self.db['vncs']
            
            logger.info(f"✓ Conectado a MongoDB: {MONGODB_URL}")
            
        except ConnectionFailure as e:
            logger.error(f"Error conectando a MongoDB: {e}")
            raise
    
    def get_used_ports_by_worker(self, slice_id: Optional[int] = None) -> Dict[str, Set[int]]:
        """
        Obtiene puertos VNC usados por worker
        
        Args:
            slice_id: Si se especifica, excluye este slice (útil para actualizaciones)
        
        Returns:
            Dict con puertos usados por worker:
            {
                'worker1': {1, 2, 5},
                'worker2': {1, 3, 4},
                'worker3': {2, 7}
            }
        """
        used_ports = {
            'worker1': set(),
            'worker2': set(),
            'worker3': set()
        }
        
        # Query: todos los slices (o todos excepto uno específico)
        query = {} if slice_id is None else {'id_slice': {'$ne': slice_id}}
        
        for doc in self.collection.find(query):
            vnc_ports = doc.get('vnc_ports', {})
            
            for worker, ports_str in vnc_ports.items():
                if ports_str:  # Si no está vacío
                    # Convertir "1,2,3" a {1, 2, 3}
                    ports = {int(p.strip()) for p in ports_str.split(',') if p.strip()}
                    used_ports[worker].update(ports)
        
        return used_ports
    
    def find_available_ports(self, worker: str, count: int, 
                            used_ports: Dict[str, Set[int]]) -> Optional[List[int]]:
        """
        Encuentra 'count' puertos disponibles para un worker
        
        Args:
            worker: Nombre del worker (worker1/2/3)
            count: Número de puertos necesarios
            used_ports: Dict de puertos ya usados
        
        Returns:
            Lista de puertos disponibles o None si no hay suficientes
        """
        # Obtener puertos ocupados (o conjunto vacío si no hay)
        occupied = used_ports.get(worker, set())
        available = []
        
        # Buscar puertos disponibles en el rango
        for port in range(VNC_PORT_MIN, VNC_PORT_MAX + 1):
            if port not in occupied:
                available.append(port)
                if len(available) == count:
                    return available
        
        # No hay suficientes puertos disponibles
        return None
    
    def reserve_vnc_ports(self, slice_id: int, vms_by_worker: Dict[str, int]) -> Optional[Dict[str, List[int]]]:
        """
        Reserva puertos VNC para un nuevo slice
        
        Args:
            slice_id: ID del slice
            vms_by_worker: Dict con cantidad de VMs por worker
                          Ejemplo: {'worker1': 2, 'worker2': 3, 'worker3': 1}
        
        Returns:
            Dict con puertos asignados por worker o None si no hay suficientes
            Ejemplo: {'worker1': [1, 2], 'worker2': [1, 2, 3], 'worker3': [5]}
        """
        try:
            # 1. Verificar si el slice ya existe
            existing = self.collection.find_one({'id_slice': slice_id})
            if existing:
                logger.warning(f"Slice {slice_id} ya tiene puertos VNC reservados")
                return None
            
            # 2. Obtener puertos usados (excluyendo este slice si existiera)
            used_ports = self.get_used_ports_by_worker(slice_id)
            
            # 3. Buscar puertos disponibles para cada worker
            allocated_ports = {}
            
            for worker, vm_count in vms_by_worker.items():
                if vm_count == 0:
                    allocated_ports[worker] = []
                    continue
                
                ports = self.find_available_ports(worker, vm_count, used_ports)
                
                if ports is None:
                    logger.error(f"No hay {vm_count} puertos VNC disponibles para {worker}")
                    return None
                
                allocated_ports[worker] = ports
                
                # Actualizar puertos usados para siguientes iteraciones
                used_ports[worker].update(ports)
            
            # 4. Guardar en MongoDB
            vnc_ports_str = {}
            for worker, ports in allocated_ports.items():
                vnc_ports_str[worker] = ','.join(map(str, ports)) if ports else ""
            
            document = {
                'id_slice': slice_id,
                'vnc_ports': vnc_ports_str
            }
            
            self.collection.insert_one(document)
            
            logger.info(f"✓ Puertos VNC reservados para slice {slice_id}: {allocated_ports}")
            
            return allocated_ports
            
        except Exception as e:
            logger.error(f"Error reservando puertos VNC: {e}")
            return None
    
    def release_vnc_ports(self, slice_id: int) -> bool:
        """
        Libera puertos VNC de un slice (cuando se elimina)
        
        Args:
            slice_id: ID del slice
        
        Returns:
            True si se liberaron correctamente, False si hubo error
        """
        try:
            result = self.collection.delete_one({'id_slice': slice_id})
            
            if result.deleted_count > 0:
                logger.info(f"✓ Puertos VNC liberados para slice {slice_id}")
                return True
            else:
                logger.warning(f"No se encontraron puertos VNC para slice {slice_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error liberando puertos VNC: {e}")
            return False
    
    def get_slice_vnc_ports(self, slice_id: int) -> Optional[Dict[str, str]]:
        """
        Obtiene puertos VNC asignados a un slice
        
        Args:
            slice_id: ID del slice
        
        Returns:
            Dict con puertos por worker o None si no existe
            Ejemplo: {'worker1': '1,2', 'worker2': '1,2,3', 'worker3': '5'}
        """
        try:
            doc = self.collection.find_one({'id_slice': slice_id})
            
            if doc:
                return doc.get('vnc_ports', {})
            else:
                return None
                
        except Exception as e:
            logger.error(f"Error obteniendo puertos VNC del slice {slice_id}: {e}")
            return None
    
    def list_all_reservations(self) -> List[Dict]:
        """
        Lista todas las reservas de puertos VNC
        
        Returns:
            Lista de documentos con reservas
        """
        try:
            return list(self.collection.find({}, {'_id': 0}))
        except Exception as e:
            logger.error(f"Error listando reservas: {e}")
            return []
    
    def close(self):
        """Cierra conexión a MongoDB"""
        if self.client:
            self.client.close()
            logger.info("Conexión a MongoDB cerrada")


# Función auxiliar para contar VMs por worker desde JSON
def count_vms_by_worker(json_config: Dict) -> Dict[str, int]:
    """
    Cuenta cuántas VMs hay por worker en la configuración
    
    Args:
        json_config: JSON con topologías y VMs
    
    Returns:
        Dict con conteo: {'worker1': 2, 'worker2': 3, 'worker3': 1}
    """
    vm_counts = {
        'worker1': 0,
        'worker2': 0,
        'worker3': 0
    }
    
    for topology in json_config.get('topologias', []):
        for vm in topology.get('vms', []):
            server = vm.get('server', '')
            if server in vm_counts:
                vm_counts[server] += 1
    
    return vm_counts


if __name__ == "__main__":
    """Pruebas básicas"""
    import sys
    
    # Configurar logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )
    
    try:
        manager = VNCPortManager()
        
        print("\n" + "="*60)
        print("PRUEBA VNC PORT MANAGER")
        print("="*60)
        
        # Ejemplo 1: Reservar puertos para slice 1
        vms_by_worker = {
            'worker1': 2,
            'worker2': 3,
            'worker3': 1
        }
        
        print(f"\n1. Reservando puertos para slice 1...")
        print(f"   VMs por worker: {vms_by_worker}")
        
        allocated = manager.reserve_vnc_ports(1, vms_by_worker)
        
        if allocated:
            print(f"   ✓ Puertos asignados: {allocated}")
        else:
            print(f"   ✗ Error en reserva")
        
        # Listar todas las reservas
        print(f"\n2. Reservas actuales:")
        reservations = manager.list_all_reservations()
        for res in reservations:
            print(f"   Slice {res['id_slice']}: {res['vnc_ports']}")
        
        # Liberar puertos
        print(f"\n3. Liberando puertos del slice 1...")
        if manager.release_vnc_ports(1):
            print(f"   ✓ Puertos liberados")
        
        manager.close()
        
        print("\n" + "="*60 + "\n")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

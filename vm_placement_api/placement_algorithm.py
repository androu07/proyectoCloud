"""
Módulo de algoritmo de VM Placement
Implementa el sistema de scoring y asignación de VMs a workers
"""

import json
import os
import logging
import requests
from typing import Dict, List, Tuple, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Configuración
PROMETHEUS_URL = os.getenv('PROMETHEUS_URL', 'http://prometheus:9090')
TRACKING_DIR = "/app/placement_tracking"

# Allocation ratios (valores de OpenStack)
ALLOCATION_RATIOS = {
    'cpu': 16,
    'ram': 1.5,
    'disk': 1
}

# Pesos para Capacity Score
CAP_WEIGHTS = {
    'ram': 0.5,
    'cpu': 0.3,
    'disk': 0.2
}

# Pesos para Stability Score
STAB_WEIGHTS = {
    'ram': 0.65,
    'cpu': 0.15,
    'disk': 0.2
}

# Peso del score final
FINAL_WEIGHTS = {
    'capacity': 0.6,
    'stability': 0.4
}

# Mapeo de workers por zona
WORKERS_BY_ZONE = {
    'linux': ['worker1', 'worker2', 'worker3'],
    'openstack': ['worker4', 'worker5', 'worker6']
}

# IPs de workers para Prometheus
WORKER_IPS = {
    'worker1': '192.168.201.2',
    'worker2': '192.168.201.3',
    'worker3': '192.168.201.4',
    'worker4': '192.168.202.2',
    'worker5': '192.168.202.3',
    'worker6': '192.168.202.4'
}


class PlacementTracker:
    """Maneja el tracking de recursos asignados en archivos JSON"""
    
    def __init__(self):
        Path(TRACKING_DIR).mkdir(parents=True, exist_ok=True)
    
    def _get_file_path(self, zona: str) -> str:
        """Obtener ruta del archivo de tracking por zona"""
        return os.path.join(TRACKING_DIR, f"tracking_{zona}.json")
    
    def load_tracking(self, zona: str) -> Dict:
        """Cargar tracking de zona"""
        file_path = self._get_file_path(zona)
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                return json.load(f)
        
        # Inicializar estructura si no existe
        workers = WORKERS_BY_ZONE.get(zona, [])
        return {worker: {'vms': []} for worker in workers}
    
    def save_tracking(self, zona: str, data: Dict):
        """Guardar tracking de zona"""
        file_path = self._get_file_path(zona)
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def add_vm(self, zona: str, worker: str, slice_id: int, vm_data: Dict):
        """Agregar VM al tracking"""
        tracking = self.load_tracking(zona)
        
        if worker not in tracking:
            tracking[worker] = {'vms': []}
        
        # Formato: id{slice_id}_vmX
        vm_entry = {
            'nombre': f"id{slice_id}_{vm_data['nombre']}",
            'cores': vm_data['cores'],
            'ram': vm_data['ram'],
            'almacenamiento': vm_data['almacenamiento']
        }
        
        tracking[worker]['vms'].append(vm_entry)
        self.save_tracking(zona, tracking)
        logger.info(f"[TRACKING] Agregada VM {vm_entry['nombre']} a {worker} en zona {zona}")
    
    def remove_slice(self, zona: str, slice_id: int):
        """Eliminar todas las VMs de un slice del tracking"""
        tracking = self.load_tracking(zona)
        prefix = f"id{slice_id}_"
        removed_count = 0
        
        for worker in tracking:
            original_count = len(tracking[worker]['vms'])
            tracking[worker]['vms'] = [
                vm for vm in tracking[worker]['vms']
                if not vm['nombre'].startswith(prefix)
            ]
            removed_count += original_count - len(tracking[worker]['vms'])
        
        self.save_tracking(zona, tracking)
        logger.info(f"[TRACKING] Eliminadas {removed_count} VMs del slice {slice_id} en zona {zona}")
        return removed_count
    
    def get_assigned_resources(self, zona: str, worker: str) -> Dict[str, float]:
        """Calcular recursos asignados de un worker"""
        tracking = self.load_tracking(zona)
        
        if worker not in tracking or not tracking[worker]['vms']:
            return {'cpu': 0, 'ram': 0, 'disk': 0}
        
        assigned_cpu = 0
        assigned_ram = 0  # en GB
        assigned_disk = 0  # en GB
        
        for vm in tracking[worker]['vms']:
            # CPU (directo)
            assigned_cpu += int(vm['cores'])
            
            # RAM (convertir M/G a GB)
            ram_str = vm['ram']
            if ram_str.endswith('G'):
                assigned_ram += float(ram_str[:-1])
            elif ram_str.endswith('M'):
                assigned_ram += float(ram_str[:-1]) / 1024
            
            # Disco (convertir M/G a GB)
            disk_str = vm['almacenamiento']
            if disk_str.endswith('G'):
                assigned_disk += float(disk_str[:-1])
            elif disk_str.endswith('M'):
                assigned_disk += float(disk_str[:-1]) / 1024
        
        return {
            'cpu': assigned_cpu,
            'ram': assigned_ram,
            'disk': assigned_disk
        }


class PrometheusClient:
    """Cliente para consultar métricas de Prometheus"""
    
    @staticmethod
    def query(query_str: str) -> float:
        """Ejecutar query en Prometheus y retornar valor"""
        try:
            response = requests.get(
                f"{PROMETHEUS_URL}/api/v1/query",
                params={"query": query_str},
                timeout=10
            )
            result = response.json()
            
            if result['status'] == 'success' and result['data']['result']:
                return float(result['data']['result'][0]['value'][1])
            return 0.0
        except Exception as e:
            logger.error(f"[PROMETHEUS] Error en query: {str(e)}")
            return 0.0
    
    @staticmethod
    def check_cluster_availability(zona: str) -> Tuple[bool, str]:
        """
        Verificar si el cluster está disponible mediante blackbox a headnode
        Retorna (disponible, mensaje)
        
        Args:
            zona: 'linux' o 'openstack'
        
        Returns:
            (True, "Cluster disponible") si UP
            (False, "Cluster no disponible") si DOWN
        """
        # Mapeo de headnodes
        headnode_ips = {
            'linux': '192.168.203.1',
            'openstack': '192.168.204.1'
        }
        
        headnode_ip = headnode_ips.get(zona)
        if not headnode_ip:
            logger.error(f"[CLUSTER_CHECK] Zona desconocida: {zona}")
            return False, f"Zona desconocida: {zona}"
        
        try:
            # Query para verificar conectividad al headnode
            cluster_state = PrometheusClient.query(
                f'probe_success{{job="blackbox-headnodes", instance="{headnode_ip}", cluster="{zona}"}}'
            )
            
            if cluster_state == 1:
                logger.info(f"[CLUSTER_CHECK] Cluster {zona} ({headnode_ip}): DISPONIBLE ✓")
                return True, f"Cluster {zona} disponible"
            else:
                logger.error(f"[CLUSTER_CHECK] Cluster {zona} ({headnode_ip}): NO DISPONIBLE ✗")
                return False, f"Cluster {zona} no está disponible (headnode caído)"
                
        except Exception as e:
            logger.error(f"[CLUSTER_CHECK] Error verificando cluster {zona}: {str(e)}")
            return False, f"Error verificando disponibilidad del cluster {zona}: {str(e)}"
    
    @staticmethod
    def get_worker_metrics(worker: str, zona: str) -> Dict:
        """
        Obtener todas las métricas de un worker
        Usa promedio de 10 minutos para evitar picos engañosos
        """
        worker_ip = WORKER_IPS.get(worker)
        if not worker_ip:
            logger.error(f"[PROMETHEUS] IP no encontrada para {worker}")
            return None
        
        instance = f"{worker_ip}:9100"
        blackbox_job = f"blackbox-workers-{zona}"
        
        try:
            # Total de recursos
            total_cpu = PrometheusClient.query(
                f'count(node_cpu_seconds_total{{mode="idle", instance="{instance}"}}) by (instance)'
            )
            
            total_ram_bytes = PrometheusClient.query(
                f'node_memory_MemTotal_bytes{{instance="{instance}"}}'
            )
            total_ram_gb = total_ram_bytes / (1024**3)
            
            total_disk_bytes = PrometheusClient.query(
                f'node_filesystem_size_bytes{{instance="{instance}", mountpoint="/", fstype!="tmpfs"}}'
            )
            total_disk_gb = total_disk_bytes / (1024**3)
            
            # Recursos usados (promedio de 10 minutos)
            used_cpu_percent = PrometheusClient.query(
                f'100 - (avg_over_time(avg by (instance) (rate(node_cpu_seconds_total{{mode="idle", instance="{instance}"}}[5m]))[10m:]) * 100)'
            )
            # Convertir % a cores usados
            used_cpu = (used_cpu_percent / 100) * total_cpu
            
            used_ram_bytes = PrometheusClient.query(
                f'avg_over_time((node_memory_MemTotal_bytes{{instance="{instance}"}} - node_memory_MemAvailable_bytes{{instance="{instance}"}})[10m:])'
            )
            used_ram_gb = used_ram_bytes / (1024**3)
            
            used_disk_bytes = PrometheusClient.query(
                f'avg_over_time((node_filesystem_size_bytes{{instance="{instance}", mountpoint="/", fstype!="tmpfs"}} - node_filesystem_avail_bytes{{instance="{instance}", mountpoint="/", fstype!="tmpfs"}})[10m:])'
            )
            used_disk_gb = used_disk_bytes / (1024**3)
            
            # Estado del worker (Blackbox Exporter)
            state_value = PrometheusClient.query(
                f'probe_success{{job="{blackbox_job}", instance="{worker_ip}"}}'
            )
            state = "up" if state_value == 1 else "down"
            
            return {
                'total_cpu': total_cpu,
                'total_ram': total_ram_gb,
                'total_disk': total_disk_gb,
                'used_cpu': used_cpu,
                'used_ram': used_ram_gb,
                'used_disk': used_disk_gb,
                'state': state
            }
            
        except Exception as e:
            logger.error(f"[PROMETHEUS] Error obteniendo métricas de {worker}: {str(e)}")
            return None


class VMPlacementAlgorithm:
    """Algoritmo de asignación de VMs a workers"""
    
    def __init__(self, zona: str):
        self.zona = zona
        self.tracker = PlacementTracker()
        self.workers = WORKERS_BY_ZONE.get(zona, [])
    
    def calculate_available_resources(self, worker_metrics: Dict, assigned: Dict) -> Dict[str, float]:
        """
        Calcular recursos disponibles usando allocation ratios
        Formula: RECURSO_disp = RECURSO_total * allocation_ratio - RECURSO_asignado
        """
        return {
            'cpu': (worker_metrics['total_cpu'] * ALLOCATION_RATIOS['cpu']) - assigned['cpu'],
            'ram': (worker_metrics['total_ram'] * ALLOCATION_RATIOS['ram']) - assigned['ram'],
            'disk': (worker_metrics['total_disk'] * ALLOCATION_RATIOS['disk']) - assigned['disk']
        }
    
    def can_fit_vm(self, available: Dict, vm_requirements: Dict) -> bool:
        """Validar si una VM cabe en los recursos disponibles"""
        return (
            available['cpu'] >= vm_requirements['cpu'] and
            available['ram'] >= vm_requirements['ram'] and
            available['disk'] >= vm_requirements['disk']
        )
    
    def calculate_capacity_score(self, available: Dict, total: Dict, worker_name: str = "") -> float:
        """
        Calcular Capacity Score
        Formula: 0.5 * (RAM_disp/RAM_total) + 0.3 * (CPU_disp/CPU_total) + 0.2 * (DISCO_disp/DISCO_total)
        """
        # Aplicar allocation ratios a totales para el cálculo
        total_with_ratio = {
            'cpu': total['cpu'] * ALLOCATION_RATIOS['cpu'],
            'ram': total['ram'] * ALLOCATION_RATIOS['ram'],
            'disk': total['disk'] * ALLOCATION_RATIOS['disk']
        }
        
        ram_ratio = available['ram'] / total_with_ratio['ram'] if total_with_ratio['ram'] > 0 else 0
        cpu_ratio = available['cpu'] / total_with_ratio['cpu'] if total_with_ratio['cpu'] > 0 else 0
        disk_ratio = available['disk'] / total_with_ratio['disk'] if total_with_ratio['disk'] > 0 else 0
        
        score = (
            CAP_WEIGHTS['ram'] * ram_ratio +
            CAP_WEIGHTS['cpu'] * cpu_ratio +
            CAP_WEIGHTS['disk'] * disk_ratio
        )
        
        if worker_name:
            logger.info(f"[SCORING]   Capacity Score para {worker_name}:")
            logger.info(f"[SCORING]     Total con ratios: CPU={total_with_ratio['cpu']:.1f}, RAM={total_with_ratio['ram']:.2f}GB, Disk={total_with_ratio['disk']:.2f}GB")
            logger.info(f"[SCORING]     Ratios: RAM={ram_ratio:.4f}, CPU={cpu_ratio:.4f}, Disk={disk_ratio:.4f}")
            logger.info(f"[SCORING]     Cálculo: {CAP_WEIGHTS['ram']}*{ram_ratio:.4f} + {CAP_WEIGHTS['cpu']}*{cpu_ratio:.4f} + {CAP_WEIGHTS['disk']}*{disk_ratio:.4f} = {score:.4f}")
        
        return max(0.0, min(1.0, score))  # Normalizar entre 0 y 1
    
    def calculate_stability_score(self, used: Dict, total: Dict, worker_name: str = "") -> float:
        """
        Calcular Stability Score
        Formula: 1 - (0.65 * (RAM_usada/RAM_total) + 0.15 * (CPU_usada/CPU_total) + 0.2 * (DISCO_usado/DISCO_total))
        """
        ram_ratio = used['ram'] / total['ram'] if total['ram'] > 0 else 0
        cpu_ratio = used['cpu'] / total['cpu'] if total['cpu'] > 0 else 0
        disk_ratio = used['disk'] / total['disk'] if total['disk'] > 0 else 0
        
        saturation = (
            STAB_WEIGHTS['ram'] * ram_ratio +
            STAB_WEIGHTS['cpu'] * cpu_ratio +
            STAB_WEIGHTS['disk'] * disk_ratio
        )
        
        score = 1 - saturation
        
        if worker_name:
            logger.info(f"[SCORING]   Stability Score para {worker_name}:")
            logger.info(f"[SCORING]     Uso: CPU={used['cpu']:.2f}/{total['cpu']}, RAM={used['ram']:.2f}/{total['ram']:.2f}GB, Disk={used['disk']:.2f}/{total['disk']:.2f}GB")
            logger.info(f"[SCORING]     Ratios de uso: RAM={ram_ratio:.4f}, CPU={cpu_ratio:.4f}, Disk={disk_ratio:.4f}")
            logger.info(f"[SCORING]     Saturación: {STAB_WEIGHTS['ram']}*{ram_ratio:.4f} + {STAB_WEIGHTS['cpu']}*{cpu_ratio:.4f} + {STAB_WEIGHTS['disk']}*{disk_ratio:.4f} = {saturation:.4f}")
            logger.info(f"[SCORING]     Score: 1 - {saturation:.4f} = {score:.4f}")
        
        return max(0.0, min(1.0, score))  # Normalizar entre 0 y 1
    
    def calculate_final_score(self, cap_score: float, stab_score: float) -> float:
        """
        Calcular score final
        Formula: 0.6 * CapScore + 0.4 * StabScore
        """
        return FINAL_WEIGHTS['capacity'] * cap_score + FINAL_WEIGHTS['stability'] * stab_score
    
    def parse_vm_requirements(self, vm: Dict) -> Dict[str, float]:
        """Convertir requerimientos de VM a formato numérico (GB)"""
        # CPU
        cpu = float(vm['cores'])
        
        # RAM
        ram_str = vm['ram']
        if ram_str.endswith('G'):
            ram = float(ram_str[:-1])
        elif ram_str.endswith('M'):
            ram = float(ram_str[:-1]) / 1024
        else:
            ram = 0
        
        # Disk
        disk_str = vm['almacenamiento']
        if disk_str.endswith('G'):
            disk = float(disk_str[:-1])
        elif disk_str.endswith('M'):
            disk = float(disk_str[:-1]) / 1024
        else:
            disk = 0
        
        return {'cpu': cpu, 'ram': ram, 'disk': disk}
    
    def find_best_worker(self, vm_requirements: Dict, workers_data: Dict) -> Optional[str]:
        """
        Encontrar el mejor worker para una VM usando el algoritmo de scoring
        Retorna el nombre del worker o None si ninguno puede alojarla
        """
        logger.info(f"{'='*80}")
        logger.info(f"[SCORING] Buscando mejor worker para VM:")
        logger.info(f"[SCORING]   Requerimientos: CPU={vm_requirements['cpu']}, RAM={vm_requirements['ram']:.2f}GB, Disk={vm_requirements['disk']:.2f}GB")
        logger.info(f"{'='*80}")
        
        candidates = []
        
        for worker, data in workers_data.items():
            logger.info(f"\n[SCORING] Evaluando {worker}:")
            
            if data['state'] != 'up':
                logger.info(f"[SCORING]   ❌ Estado: DOWN - DESCARTADO")
                continue
            
            # Regla 1: Validación de recursos mínimos
            logger.info(f"[SCORING]   Recursos disponibles: CPU={data['available']['cpu']}, RAM={data['available']['ram']:.2f}GB, Disk={data['available']['disk']:.2f}GB")
            
            if not self.can_fit_vm(data['available'], vm_requirements):
                logger.info(f"[SCORING]   ❌ Recursos insuficientes - DESCARTADO")
                continue
            
            logger.info(f"[SCORING]   ✓ Recursos suficientes")
            
            # Regla 2: Capacity Score
            cap_score = self.calculate_capacity_score(data['available'], data['total'], worker)
            
            # Regla 3: Stability Score
            stab_score = self.calculate_stability_score(data['used'], data['total'], worker)
            
            # Regla 4: Score Final
            final_score = self.calculate_final_score(cap_score, stab_score)
            
            candidates.append({
                'worker': worker,
                'cap_score': cap_score,
                'stab_score': stab_score,
                'final_score': final_score
            })
            
            logger.info(f"[SCORING]   📊 Scores → Capacity={cap_score:.4f}, Stability={stab_score:.4f}, FINAL={final_score:.4f}")
        
        if not candidates:
            logger.info(f"\n[SCORING] ❌ No hay workers candidatos disponibles\n")
            return None
        
        # Seleccionar el worker con mejor score
        best = max(candidates, key=lambda x: x['final_score'])
        logger.info(f"\n[SCORING] ✅ GANADOR: {best['worker']} con score final de {best['final_score']:.4f}")
        logger.info(f"{'='*80}\n")
        return best['worker']
    
    def assign_vms(self, slice_id: int, solicitud_json: Dict) -> Tuple[bool, str]:
        """
        Asignar todas las VMs del slice a workers
        Retorna (éxito, mensaje)
        """
        logger.info(f"[PLACEMENT] Iniciando asignación para slice {slice_id} en zona {self.zona}")
        
        # ===== PASO 0: VERIFICAR DISPONIBILIDAD DEL CLUSTER =====
        cluster_available, cluster_msg = PrometheusClient.check_cluster_availability(self.zona)
        
        if not cluster_available:
            error_msg = f"No se puede desplegar en el cluster {self.zona}: {cluster_msg}"
            logger.error(f"[PLACEMENT] Slice {slice_id}: {error_msg}")
            return False, error_msg
        
        logger.info(f"[PLACEMENT] Slice {slice_id}: {cluster_msg} - Continuando con asignación")
        
        # ===== PASO 1: Obtener métricas de todos los workers =====
        workers_data = {}
        all_down = True
        
        for worker in self.workers:
            metrics = PrometheusClient.get_worker_metrics(worker, self.zona)
            
            if metrics is None:
                logger.warning(f"[PLACEMENT] No se pudieron obtener métricas de {worker}")
                continue
            
            if metrics['state'] == 'up':
                all_down = False
            
            assigned = self.tracker.get_assigned_resources(self.zona, worker)
            available = self.calculate_available_resources(metrics, assigned)
            
            workers_data[worker] = {
                'total': {
                    'cpu': metrics['total_cpu'],
                    'ram': metrics['total_ram'],
                    'disk': metrics['total_disk']
                },
                'assigned': assigned,
                'used': {
                    'cpu': metrics['used_cpu'],
                    'ram': metrics['used_ram'],
                    'disk': metrics['used_disk']
                },
                'available': available,
                'state': metrics['state']
            }
            
            logger.info(
                f"[PLACEMENT] {worker}: Total CPU={metrics['total_cpu']}, "
                f"RAM={metrics['total_ram']:.2f}GB, Disk={metrics['total_disk']:.2f}GB, "
                f"State={metrics['state']}"
            )
        
        if all_down or not workers_data:
            return False, f"No se puede desplegar en esta AZ ({self.zona}): todos los workers están caídos o sin métricas"
        
        # Verificar si hay recursos disponibles en la zona
        total_available_cpu = sum(w['available']['cpu'] for w in workers_data.values() if w['state'] == 'up')
        total_available_ram = sum(w['available']['ram'] for w in workers_data.values() if w['state'] == 'up')
        
        if total_available_cpu <= 0 and total_available_ram <= 0:
            return False, f"No se puede desplegar en esta AZ ({self.zona}): recursos asignados al 100%"
        
        # Procesar cada VM
        vms_assigned = []
        
        for topologia in solicitud_json.get('topologias', []):
            for vm in topologia.get('vms', []):
                vm_requirements = self.parse_vm_requirements(vm)
                logger.info(
                    f"[PLACEMENT] Procesando VM {vm['nombre']}: "
                    f"CPU={vm_requirements['cpu']}, RAM={vm_requirements['ram']:.2f}GB, "
                    f"Disk={vm_requirements['disk']:.2f}GB"
                )
                
                # Encontrar el mejor worker
                selected_worker = self.find_best_worker(vm_requirements, workers_data)
                
                if selected_worker is None:
                    # No hay worker disponible, hacer rollback
                    logger.error(
                        f"[PLACEMENT] No se encontró worker para VM {vm['nombre']}, "
                        f"haciendo rollback del slice {slice_id}"
                    )
                    self.tracker.remove_slice(self.zona, slice_id)
                    return False, f"No se puede desplegar el slice por falta de recursos (VM {vm['nombre']} no pudo ser asignada)"
                
                # Asignar el worker a la VM
                vm['server'] = selected_worker
                vms_assigned.append(f"{vm['nombre']}->{selected_worker}")
                
                # Guardar en tracking
                self.tracker.add_vm(self.zona, selected_worker, slice_id, vm)
                
                # Actualizar recursos disponibles para próxima VM
                workers_data[selected_worker]['available']['cpu'] -= vm_requirements['cpu']
                workers_data[selected_worker]['available']['ram'] -= vm_requirements['ram']
                workers_data[selected_worker]['available']['disk'] -= vm_requirements['disk']
                
                workers_data[selected_worker]['assigned']['cpu'] += vm_requirements['cpu']
                workers_data[selected_worker]['assigned']['ram'] += vm_requirements['ram']
                workers_data[selected_worker]['assigned']['disk'] += vm_requirements['disk']
        
        logger.info(f"[PLACEMENT] Asignación exitosa: {', '.join(vms_assigned)}")
        return True, f"Asignadas {len(vms_assigned)} VMs exitosamente"

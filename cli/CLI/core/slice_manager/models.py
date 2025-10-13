from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional
from enum import Enum
from datetime import datetime
@dataclass

class SliceCreate:
    name: str
    topology: 'TopologyType'
    num_vms: int
    cpu: int = 1
    memory: int = 1024
    disk: int = 10
    flavor: str = "small"
    topology_segments: List['TopologySegment'] = field(default_factory=list)

class TopologyType(Enum):
    SINGLE_VM = "single_vm"
    LINEAR = "lineal"
    RING = "anillo"
    TREE = "arbol"
    MESH = "malla"
    BUS = "bus"
    MIXED = "mixta"

class FlavorType(Enum):
    TINY = "tiny"      # 1 CPU, 512MB RAM, 1GB Disk
    SMALL = "small"    # 1 CPU, 2GB RAM, 20GB Disk
    MEDIUM = "medium"  # 2 CPU, 4GB RAM, 40GB Disk
    LARGE = "large"    # 4 CPU, 8GB RAM, 80GB Disk
    XLARGE = "xlarge"  # 8 CPU, 16GB RAM, 160GB Disk

class UserRole(Enum):
    ADMIN = "admin"
    CLIENTE = "cliente"
    USUARIO_AVANZADO = "usuario_avanzado"

@dataclass
class User:
    username: str
    password: str
    role: UserRole

@dataclass
class VM:
    id: str
    name: str
    cpu: int
    memory: int
    disk: int
    flavor: str = "small"
    status: str = "pending"
    host: str = None
    ip: str = None
    topology_group: int = 0  # Para identificar a qué sub-topología pertenece
    connections: List[str] = field(default_factory=list)  # IDs de VMs conectadas
    conexion_remota: str = None  # Nuevo campo opcional
    imagen: str = None  # Nuevo campo opcional

    def to_dict(self):
        return asdict(self)

@dataclass
class TopologySegment:
    """Representa un segmento de topología dentro de un slice mixto"""
    type: TopologyType
    vms: List[VM]
    flavor: FlavorType
    
    def to_dict(self):
        return {
            'type': self.type.value,
            'vms': [vm.to_dict() for vm in self.vms],
            'flavor': self.flavor.value
        }

@dataclass
class Slice:
    id: str
    name: str
    topology: TopologyType
    vms: List[VM]
    owner: str
    created_at: str
    status: str = "activa"  # Estado por defecto: activa (solo puede ser "activa" o "inactiva")
    topology_segments: List[TopologySegment] = field(default_factory=list)
    salida_internet: str = None  # Nuevo campo opcional

    def to_dict(self):
        if hasattr(self.topology, 'value'):
            topology_val = self.topology.value
        else:
            topology_val = self.topology
        return {
            'id': self.id,
            'name': self.name,
            'topology': topology_val,
            'vms': [vm.to_dict() for vm in self.vms],
            'owner': self.owner,
            'created_at': self.created_at,
            'status': self.status,
            'topology_segments': [seg.to_dict() for seg in self.topology_segments],
            'salida_internet': self.salida_internet
        }
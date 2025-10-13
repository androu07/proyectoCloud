import json
import os
from datetime import datetime
from typing import List, Optional
from .models import Slice, VM, SliceCreate, TopologyType, TopologySegment, FlavorType
import uuid


class SliceManager:
    def __init__(self):
        # Buscar base_de_datos.json en el directorio raíz del proyecto
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(current_dir))
        self.database_file = os.path.join(project_root, "base_de_datos.json")
        self.slices: List[Slice] = self._load_slices()
    
    def _load_slices(self) -> List[Slice]:
        slices = []
        if os.path.exists(self.database_file):
            try:
                with open(self.database_file, 'r', encoding='utf-8') as f:
                    json_data = json.load(f)
                    if json_data:
                        for item in json_data:
                            slice_id = item.get('id_slice', '')
                            topologias = item.get('topologias', [])
                            # Tomar la primera topología como principal
                            topo = topologias[0] if topologias else {}
                            vms = []
                            for vm_data in topo.get('vms', []):
                                # Permitir valores decimales en almacenamiento
                                almacenamiento_str = vm_data.get('almacenamiento', '1G').replace('G','')
                                try:
                                    disk_val = int(float(almacenamiento_str))
                                except Exception:
                                    disk_val = 1
                                vm = VM(
                                    id=vm_data.get('nombre', ''),
                                    name=vm_data.get('nombre', ''),
                                    cpu=int(vm_data.get('cores', '1')),
                                    memory=int(vm_data.get('ram', '512M').replace('M','')),
                                    disk=disk_val,
                                    flavor=vm_data.get('image', 'f1'),
                                    conexion_remota=vm_data.get('acceso', 'no'),
                                    imagen=vm_data.get('image', '')
                                )
                                vms.append(vm)
                            slice_obj = Slice(
                                id=slice_id,
                                name=slice_id,
                                topology=topo.get('nombre', 'lineal'),
                                vms=vms,
                                owner=item.get('owner', ''),
                                created_at=datetime.now(),
                                status='activa',  # Estado por defecto: activa
                                salida_internet=topo.get('internet', 'no')
                            )
                            slices.append(slice_obj)
            except Exception as e:
                print(f"Error loading database JSON slices: {e}")
        print(f"[DEBUG] Cargados {len(slices)} slices desde {self.database_file}")
        return slices
    
    def _save_slices(self):
        """Guardar todos los slices en base_de_datos.json en el formato ejemplo (lista de objetos)"""
        import uuid
        data = []
        for idx, slice in enumerate(self.slices):
            vms_data = []
            for vm in slice.vms:
                vms_data.append({
                    "nombre": getattr(vm, 'name', ''),
                    "cores": str(getattr(vm, 'cpu', 1)),
                    "ram": f"{getattr(vm, 'memory', 512)}M",
                    "almacenamiento": f"{getattr(vm, 'disk', 1)}G",
                    "puerto_vnc": "",
                    "image": getattr(vm, 'imagen', ''),
                    "conexiones_vlans": "",
                    "acceso": getattr(vm, 'conexion_remota', 'no'),
                    "server": ""
                })
            cantidad_vms = str(len(vms_data))
            topologia_nombre = getattr(slice, 'topology', 'lineal')
            if hasattr(topologia_nombre, 'value'):
                topologia_nombre = topologia_nombre.value
            salida_internet = getattr(slice, 'salida_internet', 'no')
            topologia_obj = {
                "nombre": topologia_nombre,
                "cantidad_vms": cantidad_vms,
                "internet": salida_internet,
                "vms": vms_data
            }
            new_slice = {
                "id_slice": "",
                "cantidad_vms": cantidad_vms,
                "vlans_separadas": str(idx + 1),
                "vlans_usadas": "",
                "vncs_separadas": "",
                "conexión_topologias": "",
                "topologias": [topologia_obj]
            }
            data.append(new_slice)
        with open(self.database_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[DEBUG] Guardados {len(data)} slices en {self.database_file}")
    
    def create_slice(self, slice_data: SliceCreate, owner: str = "cliente", vms_override: list = None) -> Slice:
        """Crear slice de forma síncrona"""
        slice_id = f"slice_{uuid.uuid4().hex[:12]}"

        # Usar vms_override si está presente, si no crear VMs por defecto
        if vms_override is not None:
            vms = vms_override
        else:
            vms = []
            for i in range(slice_data.num_vms):
                vm = VM(
                    id=f"{slice_id}_vm_{i}",
                    name=f"{slice_data.name}_vm_{i}",
                    cpu=slice_data.cpu,
                    memory=slice_data.memory,
                    disk=slice_data.disk,
                    status="pending",
                    flavor="f1"
                )
                vms.append(vm)

        # Crear slice
        new_slice = Slice(
            id=slice_id,
            name=slice_data.name,
            topology=slice_data.topology,
            vms=vms,
            owner=owner,
            created_at=datetime.now(),
            status="activa"  # Estado por defecto: activa
        )

        self.slices.append(new_slice)
        self._save_slices()
        
        print(f"[DEBUG] Slice creado: {slice_id}")
        print(f"[DEBUG] Total slices en memoria: {len(self.slices)}")

        return new_slice
    
    def get_slices(self, owner: Optional[str] = None) -> List[Slice]:
        if owner:
            return [s for s in self.slices if s.owner == owner]
        return self.slices
    
    def get_slice(self, slice_id: str) -> Optional[Slice]:
        for slice in self.slices:
            if slice.id == slice_id:
                return slice
        return None
    
    def delete_slice(self, slice_id: str) -> bool:
        original_count = len(self.slices)
        self.slices = [s for s in self.slices if s.id != slice_id]
        
        if len(self.slices) < original_count:
            self._save_slices()
            return True
        return False
    
    def update_slice_status(self, slice_id: str, status: str) -> bool:
        slice = self.get_slice(slice_id)
        if slice:
            slice.status = status
            self._save_slices()
            return True
        return False
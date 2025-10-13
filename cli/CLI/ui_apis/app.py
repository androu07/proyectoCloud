from fastapi import FastAPI, HTTPException, Depends, status, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from typing import Optional, List, Dict
from pydantic import BaseModel
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.slice_manager.models import SliceCreate, Slice, VM, TopologyType
from core.slice_manager.manager import SliceManager

# Modelos de respuesta simplificados
class Token(BaseModel):
    access_token: str
    token_type: str

class SliceResponse(BaseModel):
    message: str
    slice: Optional[dict] = None

class SlicesListResponse(BaseModel):
    slices: List[dict]
    total: int

class SliceStatusUpdate(BaseModel):
    status: str

# Pydantic model for API (to avoid dataclass forward reference issues)
class SliceCreateAPI(BaseModel):
    name: str
    topology: str  # Will be converted to TopologyType enum
    num_vms: int
    cpu: int = 1
    memory: int = 1024
    disk: int = 10
    flavor: str = "small"
    topology_segments: List[dict] = []

# Configuración de FastAPI
app = FastAPI(
    title="PUCP Cloud Orchestrator API",
    description="API para gestión de slices en cloud privado",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Autenticación
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Instancia del manager
slice_manager = SliceManager()

# Función para verificar token (simplificada)
async def get_current_user(token: str = Depends(oauth2_scheme)):
    # Aquí implementarías validación real del JWT
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido"
        )
    return {"username": "admin", "role": "admin"}

# === ENDPOINTS ===

@app.get("/")
async def root():
    return {
        "service": "PUCP Cloud Orchestrator",
        "version": "1.0.0",
        "status": "running"
    }

@app.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Endpoint de autenticación"""
    # Aquí implementarías autenticación real
    if form_data.username and form_data.password:
        return {
            "access_token": "fake-jwt-token",
            "token_type": "bearer"
        }
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales incorrectas"
    )

@app.post("/api/slices", response_model=SliceResponse, status_code=status.HTTP_201_CREATED)
async def create_slice(
    slice_data: SliceCreateAPI,
    current_user: dict = Depends(get_current_user)
):
    """Crear un nuevo slice"""
    try:
        # Convert Pydantic model to dataclass
        slice_create_dc = SliceCreate(
            name=slice_data.name,
            topology=TopologyType(slice_data.topology),
            num_vms=slice_data.num_vms,
            cpu=slice_data.cpu,
            memory=slice_data.memory,
            disk=slice_data.disk,
            flavor=slice_data.flavor,
            topology_segments=slice_data.topology_segments
        )
        slice = await slice_manager.create_slice(slice_create_dc, current_user["username"])
        return SliceResponse(
            message="Slice creado exitosamente",
            slice=slice
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@app.get("/api/slices", response_model=SlicesListResponse)
async def get_slices(
    owner: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Listar slices"""
    slices = slice_manager.get_slices(owner)
    return SlicesListResponse(
        slices=slices,
        total=len(slices)
    )

@app.get("/api/slices/{slice_id}")
async def get_slice(
    slice_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Obtener detalles de un slice"""
    slice = slice_manager.get_slice(slice_id)
    if not slice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Slice no encontrado"
        )
    return {"slice": slice}

@app.delete("/api/slices/{slice_id}")
async def delete_slice(
    slice_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Eliminar un slice"""
    if not slice_manager.delete_slice(slice_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Slice no encontrado"
        )
    return {"message": "Slice eliminado exitosamente"}

@app.put("/api/slices/{slice_id}/status")
async def update_slice_status(
    slice_id: str,
    status_update: SliceStatusUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Actualizar estado del slice"""
    if not slice_manager.update_slice_status(slice_id, status_update.status):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Slice no encontrado"
        )
    return {"message": "Estado actualizado exitosamente"}

@app.get("/api/health")
async def health_check():
    """Health check del servicio"""
    return {
        "status": "healthy",
        "service": "UI-APIs",
        "slices_count": len(slice_manager.slices)
    }

# Endpoint para crear slice desde servicio externo (formato especial)
@app.post("/slices/solicitud_creacion")
async def solicitud_creacion(payload: dict = Body(...), current_user: dict = Depends(get_current_user)):
    """
    Recibe una solicitud de creación de slice en formato especial (nombre_slice y solicitud_json), lo guarda y lo hace visible en los listados estándar.
    """
    nombre_slice = payload.get("nombre_slice")
    solicitud_json = payload.get("solicitud_json")
    # Mapear el JSON recibido a SliceCreate (adaptar según tu modelo)
    try:
        # Extraer datos básicos
        cantidad_vms = int(solicitud_json.get("cantidad_vms", 1))
        topologias = solicitud_json.get("topologias", [])
        # Tomar la primera topología como principal
        topo = topologias[0] if topologias else {}
        topology_name = topo.get("nombre", "lineal")
        internet = topo.get("internet", "no")
        vms_data = topo.get("vms", [])
        # Crear lista de VMs
        from core.slice_manager.models import VM, SliceCreate, TopologyType
        vms = []
        for vm in vms_data:
            vms.append(VM(
                id=vm.get("nombre", ""),
                name=vm.get("nombre", ""),
                cpu=int(vm.get("cores", "1")),
                memory=int(vm.get("ram", "500M").replace("M", "")),
                disk=int(float(vm.get("almacenamiento", "1G").replace("G", ""))),
                flavor="small",
                status="pending",
                conexion_remota=vm.get("acceso", "no"),
                imagen=vm.get("image", "")
            ))
        # Crear objeto SliceCreate
        slice_create = SliceCreate(
            name=nombre_slice,
            topology=TopologyType(topology_name) if topology_name in TopologyType._value2member_map_ else TopologyType.LINEAR,
            num_vms=cantidad_vms,
            cpu=1,
            memory=512,
            disk=1,
            flavor="small"
        )
        # Eliminar id_slice del json antes de guardar
        if "id_slice" in solicitud_json:
            solicitud_json["id_slice"] = ""
        # Crear el slice usando el manager
        slice_obj = slice_manager.create_slice(slice_create, current_user["username"], vms_override=vms)
        return {
            "message": "Slice creado y guardado correctamente (servicio externo)",
            "slice": slice_obj.to_dict() if hasattr(slice_obj, 'to_dict') else str(slice_obj)
        }
    except Exception as e:
        return {"error": str(e), "message": "Error al crear el slice desde el servicio externo"}

# Endpoint alternativo para listar slices (compatibilidad)
@app.get("/slices/listar_slices")
async def listar_slices(current_user: dict = Depends(get_current_user)):
    """
    Listar todos los slices (endpoint alternativo para compatibilidad)
    """
    slices = slice_manager.get_slices()
    return {
        "slices": slices,
        "total": len(slices)
    }


if __name__ == "__main__":
    import uvicorn
    print("=== PUCP Cloud Orchestrator API ===")
    print("Servidor iniciado en: https://localhost:8443")
    # Run without reload to avoid import string requirement
    uvicorn.run(app, host="0.0.0.0", port=8443)
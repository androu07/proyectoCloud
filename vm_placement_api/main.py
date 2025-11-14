from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Any
import os

app = FastAPI(
    title="VM Placement API",
    version="1.0.0",
    description="API para asignar VMs a workers usando Round-Robin"
)

# Configuración
SERVICE_TOKEN = os.getenv('SERVICE_TOKEN', 'clavesihna')
WORKERS = ['worker1', 'worker2', 'worker3']

security = HTTPBearer()

# Autenticación
def get_service_auth(credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
    """Verificar token de servicio"""
    if credentials.credentials != SERVICE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de servicio inválido"
        )
    return True

@app.get("/")
async def root():
    return {
        "message": "VM Placement API - Round-Robin Worker Assignment",
        "status": "activo",
        "version": "1.0.0"
    }

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "OK",
        "service": "vm_placement_api",
        "version": "1.0.0",
        "workers": WORKERS
    }

@app.post("/assign-workers")
async def assign_workers(
    request: dict,
    authorized: bool = Depends(get_service_auth)
):
    """
    Asignar workers a las VMs usando Round-Robin
    Recibe el JSON completo y retorna con los servers asignados
    """
    try:
        # Validar que tenga la estructura esperada
        if 'solicitud_json' not in request or 'topologias' not in request['solicitud_json']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="JSON inválido: falta 'solicitud_json' o 'topologias'"
            )
        
        # Contador para Round-Robin
        worker_index = 0
        total_vms_assigned = 0
        
        # Recorrer todas las topologías y VMs
        for topologia in request['solicitud_json']['topologias']:
            if 'vms' not in topologia:
                continue
                
            for vm in topologia['vms']:
                # Asignar worker usando Round-Robin
                vm['server'] = WORKERS[worker_index % len(WORKERS)]
                worker_index += 1
                total_vms_assigned += 1
        
        return {
            "success": True,
            "message": "Workers asignados exitosamente",
            "total_vms_assigned": total_vms_assigned,
            "workers_used": WORKERS,
            "peticion_json": request
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al asignar workers: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=6000, workers=2)

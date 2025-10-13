#!/usr/bin/env python3
"""
Cleanup API - API simple para ejecutar cleanup_slice.sh en el host
Puerto: 8888
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import logging

# Configuración
CLEANUP_SCRIPT_PATH = "/home/ubuntu/red_contenedores/manager_linux_api/cleanup_slice.sh"
SUDO_PASSWORD = "alejandro"

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Cleanup API", version="1.0.0")

class CleanupRequest(BaseModel):
    slice_id: int
    ovs_bridge: str = "br-cloud"

@app.post("/cleanup_slice")
async def cleanup_slice(request: CleanupRequest):
    """
    Ejecutar script de cleanup para un slice
    """
    try:
        slice_id = request.slice_id
        ovs_bridge = request.ovs_bridge
        
        logger.info(f"🧹 Ejecutando cleanup para slice {slice_id}")
        
        # Ejecutar el script de cleanup con sudo -S
        command = f"echo '{SUDO_PASSWORD}' | sudo -S {CLEANUP_SCRIPT_PATH} {slice_id} {ovs_bridge}"
        
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        success = result.returncode == 0
        
        logger.info(f"{'✅' if success else '❌'} Cleanup slice {slice_id} - código: {result.returncode}")
        
        return {
            "success": success,
            "slice_id": slice_id,
            "return_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
        
    except subprocess.TimeoutExpired:
        logger.error(f"⏱️ Timeout ejecutando cleanup para slice {request.slice_id}")
        raise HTTPException(status_code=408, detail="Timeout ejecutando cleanup")
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "cleanup_api"}

if __name__ == "__main__":
    import uvicorn
    print("🚀 Iniciando Cleanup API en el host...")
    print("📍 Puerto: 8888")
    print("🔗 URL: http://localhost:8888")
    uvicorn.run(app, host="0.0.0.0", port=8888)

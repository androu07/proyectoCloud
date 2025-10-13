from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.slice_manager.models import SliceCreate, Slice, VM, TopologyType
from core.slice_manager.manager import SliceManager
from pydantic import BaseModel

# Modelos Pydantic para API
class SliceResponse(BaseModel):
    message: str
    slice: Optional[dict] = None

class SlicesListResponse(BaseModel):
    slices: List[dict]
    total: int

# Configuración de FastAPI
app = FastAPI(
    title="PUCP Cloud Orchestrator - Local Dev",
    description="Backend local solo para desarrollo",
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

# Instancia del manager
slice_manager = SliceManager()

@app.get("/")
async def root():
    return {
        "service": "Local Dev Backend",
        "status": "running",
        "note": "Use SSH tunnel to remote server for production: ssh -NL 8443:localhost:443 ubuntu@10.20.12.97 -p 5801"
    }

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "Local Dev"}

# Servidor
if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*70)
    print("LOCAL DEV BACKEND - Solo para desarrollo")
    print("="*70)
    print("Para producción usa: ssh -NL 8443:localhost:443 ubuntu@10.20.12.97 -p 5801")
    print("="*70 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8080)

#!/bin/bash

echo "========================================="
echo "    INICIALIZANDO INFRAESTRUCTURA CLOUD    "
echo "========================================="

OVS_NAME="$1"
PASSWORD="grupouno"

echo "Bridge OVS a crear: $OVS_NAME"
echo ""

# ============================================
# INICIALIZAR HEAD NODE
# ============================================
echo "=== 1. INICIALIZANDO HEAD NODE ==="
echo "Ejecutando init_headnode.sh..."

if [[ -f "./init_headnode.sh" ]]; then
    echo "$PASSWORD" | sudo -S ./init_headnode.sh "$OVS_NAME"
    echo "Head node inicializado correctamente"
    echo "$PASSWORD" | sudo -S ./node_exporter.sh
else
    echo "ERROR: No se encuentra init_headnode.sh en el directorio actual"
    exit 1
fi

echo ""

# ============================================
# INICIALIZAR WORKERS
# ============================================
echo "=== 2. INICIALIZANDO WORKERS ==="

# Lista de workers
WORKERS=("192.168.201.2" "192.168.201.3" "192.168.201.4")
WORKER_NAMES=("Worker-1" "Worker-2" "Worker-3")

for i in "${!WORKERS[@]}"; do
    WORKER_IP="${WORKERS[$i]}"
    WORKER_NAME="${WORKER_NAMES[$i]}"
    
    echo ""
    echo "--- Inicializando $WORKER_NAME ($WORKER_IP) ---"
    
    # Verificar conectividad SSH
    
    ssh ubuntu@"$WORKER_IP" << EOF
        echo "Cambiando al directorio scripts_app..."
        cd scripts_app

        echo "Verificando script init_worker.sh..."
        if [[ ! -f "init_worker.sh" ]]; then
            echo "ERROR: No se encuentra init_worker.sh"
            exit 1
        fi
        
        echo "Ejecutando init_worker.sh con sudo..."
        chmod +x init_worker.sh
        
        echo "$PASSWORD" | sudo -S ./init_worker.sh "$OVS_NAME"
        
        echo "$PASSWORD" | sudo -S ./node_exporter.sh

        echo "Worker inicializado correctamente"
EOF

    if [[ $? -eq 0 ]]; then
        echo "$WORKER_NAME inicializado correctamente"
    else
        echo "ERROR: Falló la inicialización de $WORKER_NAME"
    fi
done

echo ""
echo "========================================="
echo "    INFRAESTRUCTURA INICIALIZADA"
echo "========================================="
#!/bin/bash

set -e  # Exit on any error

echo "========================================="
echo "    INICIALIZANDO INFRAESTRUCTURA CLOUD    "
echo "========================================="

OVS_NAME="$1"
PASSWORD="alejandro"

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
WORKERS=("10.0.10.2" "10.0.10.3" "10.0.10.4")
WORKER_NAMES=("Worker-1" "Worker-2" "Worker-3")

for i in "${!WORKERS[@]}"; do
    WORKER_IP="${WORKERS[$i]}"
    WORKER_NAME="${WORKER_NAMES[$i]}"
    
    echo ""
    echo "--- Inicializando $WORKER_NAME ($WORKER_IP) ---"
    
    # Verificar conectividad SSH
    echo "Verificando conectividad SSH..."
    if ! ssh -o ConnectTimeout=10 -o BatchMode=yes ubuntu@"$WORKER_IP" "echo 'Conectado'" 2>/dev/null; then
        echo "ERROR: No se puede conectar por SSH a $WORKER_IP"
        continue
    fi
    
    ssh ubuntu@"$WORKER_IP" << EOF
        echo "Cambiando al directorio scripts_orquestacion..."
        cd scripts_orquestacion
        
        echo "Verificando script init_worker.sh..."
        if [[ ! -f "init_worker.sh" ]]; then
            echo "ERROR: No se encuentra init_worker.sh"
            exit 1
        fi
        
        echo "Ejecutando init_worker.sh con sudo..."
        chmod +x init_worker.sh
        echo "$PASSWORD" | sudo -S ./init_worker.sh "$OVS_NAME"
        
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
echo "    RESUMEN DE INICIALIZACIÓN"
echo "========================================="

# Verificar head node
echo "Head Node:"
if ovs-vsctl br-exists "$OVS_NAME" 2>/dev/null; then
    echo "  Bridge $OVS_NAME creado en el Headnode"
    echo "  Puertos: $(ovs-vsctl list-ports "$OVS_NAME" | tr '\n' ' ')"
else
    echo "  ERROR: Bridge $OVS_NAME NO encontrado"
fi

echo ""
echo "Workers:"

echo ""
echo "========================================="
echo "    INFRAESTRUCTURA INICIALIZADA"
echo "========================================="
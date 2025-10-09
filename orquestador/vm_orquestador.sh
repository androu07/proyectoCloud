#!/bin/bash

set -e  # Exit on any error

# Parametros
VLAN_ID="$1"
CANTIDAD_VMS="$2"
PASSWORD="alejandro"
IMAGE_NAME="cirros-0.5.1-x86_64-disk.img"

echo "========================================="
echo "    VM ORQUESTADOR - VLAN $VLAN_ID"
echo "========================================="
echo "VLAN ID: $VLAN_ID"
echo "Cantidad de VMs: $CANTIDAD_VMS"
echo ""

# ============================================
# 1. CREAR NAMESPACE DHCP EN HEAD NODE
# ============================================
echo "=== 1. CREANDO NAMESPACE DHCP ==="
echo "Ejecutando net_create.sh en head node..."

# Ejecutar net_create
echo "$PASSWORD" | sudo -S ./net_create.sh "$VLAN_ID" "br-cloud" "$CANTIDAD_VMS"

if [[ $? -eq 0 ]]; then
    echo "OK: Namespace DHCP creado correctamente"
else
    echo "ERROR: Falló la creación del namespace DHCP"
    exit 1
fi

echo ""

# ============================================
# 2. CALCULAR DISTRIBUCIÓN DE VMS EN WORKERS
# ============================================
echo "=== 2. CALCULANDO DISTRIBUCIÓN DE VMS ==="

# Lista de workers
WORKERS=("10.0.10.2" "10.0.10.3" "10.0.10.4")
WORKER_NAMES=("Worker-1" "Worker-2" "Worker-3")

# Calcular distribución secuencial
declare -A VM_COUNT_PER_WORKER
declare -A VM_LIST_PER_WORKER

# Inicializar contadores
for i in "${!WORKERS[@]}"; do
    VM_COUNT_PER_WORKER[${WORKERS[$i]}]=0
    VM_LIST_PER_WORKER[${WORKERS[$i]}]=""
done

# Distribuir VMs secuencialmente
VM_COUNTER=1
for ((vm=1; vm<=CANTIDAD_VMS; vm++)); do
    WORKER_INDEX=$(( (vm-1) % 3 ))
    WORKER_IP="${WORKERS[$WORKER_INDEX]}"
    
    VM_COUNT_PER_WORKER[$WORKER_IP]=$((VM_COUNT_PER_WORKER[$WORKER_IP] + 1))
    
    if [[ -z "${VM_LIST_PER_WORKER[$WORKER_IP]}" ]]; then
        VM_LIST_PER_WORKER[$WORKER_IP]="$VM_COUNTER"
    else
        VM_LIST_PER_WORKER[$WORKER_IP]="${VM_LIST_PER_WORKER[$WORKER_IP]} $VM_COUNTER"
    fi
    
    VM_COUNTER=$((VM_COUNTER + 1))
done

# Mostrar distribución
echo "Distribución de VMs:"
for i in "${!WORKERS[@]}"; do
    WORKER_IP="${WORKERS[$i]}"
    WORKER_NAME="${WORKER_NAMES[$i]}"
    COUNT="${VM_COUNT_PER_WORKER[$WORKER_IP]}"
    VMS="${VM_LIST_PER_WORKER[$WORKER_IP]}"
    
    if [[ $COUNT -gt 0 ]]; then
        echo "  $WORKER_NAME ($WORKER_IP): $COUNT VMs [VMs: $VMS]"
    else
        echo "  $WORKER_NAME ($WORKER_IP): 0 VMs"
    fi
done

echo ""

# ============================================
# 3. OBTENER PUERTOS VNC USADOS EN WORKERS
# ============================================
echo "=== 3. VERIFICANDO PUERTOS VNC USADOS ==="

declare -A USED_VNC_PORTS
declare -A NEXT_VNC_PORT

for i in "${!WORKERS[@]}"; do
    WORKER_IP="${WORKERS[$i]}"
    WORKER_NAME="${WORKER_NAMES[$i]}"
    
    # Solo verificar workers que tendrán VMs
    if [[ ${VM_COUNT_PER_WORKER[$WORKER_IP]} -gt 0 ]]; then
        echo "Verificando puertos VNC en $WORKER_NAME ($WORKER_IP)..."
        
        # Obtener puertos VNC usados
        USED_PORTS=$(ssh ubuntu@"$WORKER_IP" "
            pgrep -f qemu | while read pid; do
                ps -p \$pid -o args --no-headers | grep -o 'vnc [^:]*:[0-9]*' | cut -d: -f2 || true
            done | sort -n
        " 2>/dev/null || echo "")
        
        if [[ -n "$USED_PORTS" ]]; then
            USED_VNC_PORTS[$WORKER_IP]="$USED_PORTS"
            LAST_PORT=$(echo "$USED_PORTS" | tail -1)
            NEXT_VNC_PORT[$WORKER_IP]=$((LAST_PORT + 1))
            echo "  Puertos usados: $(echo $USED_PORTS | tr '\n' ' ')"
            echo "  Próximo puerto disponible: ${NEXT_VNC_PORT[$WORKER_IP]}"
        else
            USED_VNC_PORTS[$WORKER_IP]=""
            NEXT_VNC_PORT[$WORKER_IP]=1
            echo "  Sin puertos VNC usados"
            echo "  Próximo puerto disponible: 1"
        fi
    fi
done

echo ""

# ============================================
# 4. DESPLEGAR VMS EN WORKERS
# ============================================
echo "=== 4. DESPLEGANDO VMS EN WORKERS ==="

for i in "${!WORKERS[@]}"; do
    WORKER_IP="${WORKERS[$i]}"
    WORKER_NAME="${WORKER_NAMES[$i]}"
    VM_COUNT="${VM_COUNT_PER_WORKER[$WORKER_IP]}"
    
    # Solo desplegar en workers que tengan VMs asignadas
    if [[ $VM_COUNT -gt 0 ]]; then
        echo ""
        echo "--- Desplegando en $WORKER_NAME ($WORKER_IP) ---"
        echo "VMs a desplegar: $VM_COUNT"
        
        # Verificar conectividad SSH
        if ! ssh -o ConnectTimeout=10 -o BatchMode=yes ubuntu@"$WORKER_IP" "echo 'Conectado'" 2>/dev/null; then
            echo "ERROR: No se puede conectar por SSH a $WORKER_IP"
            echo "Saltando este worker..."
            continue
        fi
        
        # Obtener lista de VMs para este worker
        VM_LIST="${VM_LIST_PER_WORKER[$WORKER_IP]}"
        VNC_PORT_START="${NEXT_VNC_PORT[$WORKER_IP]}"
        
        # Desplegar cada VM en este worker
        VM_INDEX=0
        for VM_NUM in $VM_LIST; do
            VM_NAME="id${VLAN_ID}-VM${VM_NUM}"
            VNC_PORT=$((VNC_PORT_START + VM_INDEX))
            
            echo "  Creando VM: $VM_NAME (VNC: 590$VNC_PORT)"
            
            # Ejecutar vm_create.sh en el worker remoto
            ssh ubuntu@"$WORKER_IP" << EOF
                echo "Cambiando al directorio scripts_orquestacion..."
                cd scripts_orquestacion
                
                echo "Verificando script vm_create.sh..."
                if [[ ! -f "vm_create.sh" ]]; then
                    echo "ERROR: No se encuentra vm_create.sh"
                    exit 1
                fi
                
                echo "Ejecutando vm_create.sh para $VM_NAME..."
                echo "$PASSWORD" | sudo -S ./vm_create.sh \\
                    "$VM_NAME" \\
                    "$VLAN_ID" \\
                    "$VNC_PORT" \\
                    "br-cloud" \\
                    "$IMAGE_NAME"
EOF

            if [[ $? -eq 0 ]]; then
                echo "    OK: $VM_NAME creada correctamente en $WORKER_NAME"
            else
                echo "    ERROR: Falló la creación de $VM_NAME en $WORKER_NAME"
            fi
            
            VM_INDEX=$((VM_INDEX + 1))
            sleep 2  # Pequeña pausa entre VMs
        done
    fi
done

echo ""
echo "========================================="
echo "    DESPLIEGUE COMPLETADO"
echo "========================================="

# ============================================
# 5. RESUMEN FINAL
# ============================================
echo "=== RESUMEN DEL DESPLIEGUE ==="
echo "VLAN ID: $VLAN_ID"
echo "Total VMs desplegadas: $CANTIDAD_VMS"
echo ""

echo "Distribución por worker:"
for i in "${!WORKERS[@]}"; do
    WORKER_IP="${WORKERS[$i]}"
    WORKER_NAME="${WORKER_NAMES[$i]}"
    COUNT="${VM_COUNT_PER_WORKER[$WORKER_IP]}"
    
    if [[ $COUNT -gt 0 ]]; then
        VM_LIST="${VM_LIST_PER_WORKER[$WORKER_IP]}"
        VNC_START="${NEXT_VNC_PORT[$WORKER_IP]}"
        VNC_END=$((VNC_START + COUNT - 1))
        
        echo "  $WORKER_NAME ($WORKER_IP):"
        echo "    VMs: $COUNT [$(echo $VM_LIST | sed "s/ /, /g")]"
        echo "    Puertos VNC: 590$VNC_START - 590$VNC_END"
        echo "    Nombres: $(echo $VM_LIST | sed "s/\([0-9]*\)/id${VLAN_ID}-VM\1/g" | sed "s/ /, /g")"
    fi
done

echo ""
echo "Información de acceso:"
echo "  - Subnet: 10.7.${VLAN_ID}.0/24"
echo "  - DHCP Range: 10.7.${VLAN_ID}.1 - 10.7.${VLAN_ID}.${CANTIDAD_VMS}"
echo "  - Gateway: 10.7.${VLAN_ID}.$((CANTIDAD_VMS + 1))"
echo "  - Usuario VMs: cirros / Password: gocubsgo"
echo ""
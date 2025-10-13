#!/bin/bash

set -e  # Exit on any error

# Parametros
VLAN_ID="$1"
CANTIDAD_VMS="$2"
IMAGE_NAME="$3"
PASSWORD="alejandro"

echo "========================================="
echo "    VM ORQUESTADOR - VLAN $VLAN_ID"
echo "========================================="
echo "VLAN ID: $VLAN_ID"
echo "Cantidad de VMs: $CANTIDAD_VMS"

# Validar cantidad de VMs
if [[ $CANTIDAD_VMS -lt 2 || $CANTIDAD_VMS -gt 10 ]]; then
    echo "ERROR: La cantidad de VMs debe estar entre 2 y 10"
    echo "Cantidad proporcionada: $CANTIDAD_VMS"
    exit 1
fi

# Calcular rango de puertos VNC para esta VLAN
MAX_VNC=$((VLAN_ID * 10))
MIN_VNC=$((VLAN_ID * 10 - 9))

echo "Rango VNC reservado para VLAN $VLAN_ID: [$MIN_VNC - $MAX_VNC]"
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
# 3. ASIGNAR PUERTOS VNC PARA CADA VM
# ============================================
echo "=== 3. ASIGNANDO PUERTOS VNC ==="

# Calcular puertos VNC secuencialmente desde MIN_VNC
declare -A VNC_PORT_ASSIGNMENT
VNC_COUNTER=$MIN_VNC

for ((vm=1; vm<=CANTIDAD_VMS; vm++)); do
    VNC_PORT_ASSIGNMENT[$vm]=$VNC_COUNTER
    echo "VM $vm -> Puerto VNC: $VNC_COUNTER (590$VNC_COUNTER)"
    VNC_COUNTER=$((VNC_COUNTER + 1))
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
        
        # Desplegar cada VM en este worker
        for VM_NUM in $VM_LIST; do
            VM_NAME="id${VLAN_ID}-VM${VM_NUM}"
            VNC_PORT="${VNC_PORT_ASSIGNMENT[$VM_NUM]}"
            
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
        
        echo "  $WORKER_NAME ($WORKER_IP):"
        echo "    VMs: $COUNT [$(echo $VM_LIST | sed "s/ /, /g")]"
        
        # Mostrar puertos VNC para cada VM de este worker
        VNC_PORTS=""
        for VM_NUM in $VM_LIST; do
            if [[ -z "$VNC_PORTS" ]]; then
                VNC_PORTS="590${VNC_PORT_ASSIGNMENT[$VM_NUM]}"
            else
                VNC_PORTS="$VNC_PORTS, 590${VNC_PORT_ASSIGNMENT[$VM_NUM]}"
            fi
        done
        echo "    Puertos VNC: $VNC_PORTS"
        echo "    Nombres: $(echo $VM_LIST | sed "s/\([0-9]*\)/id${VLAN_ID}-VM\1/g" | sed "s/ /, /g")"
    fi
done

echo ""
echo "Información de acceso:"
echo "  - Subnet: 10.7.${VLAN_ID}.0/24"
echo "  - DHCP Range: 10.7.${VLAN_ID}.1 - 10.7.${VLAN_ID}.${CANTIDAD_VMS}"
echo "  - Gateway: 10.7.${VLAN_ID}.$((CANTIDAD_VMS + 1))"
echo "  - Rango VNC para VLAN $VLAN_ID: [$MIN_VNC-$MAX_VNC] (puertos 590$MIN_VNC-590$MAX_VNC)"
echo "  - Puertos VNC usados: $MIN_VNC-$((MIN_VNC + CANTIDAD_VMS - 1))"
echo "  - Usuario VMs: cirros / Password: gocubsgo"
echo ""
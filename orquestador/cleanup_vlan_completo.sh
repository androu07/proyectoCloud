#!/bin/bash

set -e  # Exit on any error

# Parámetros
VLAN_ID="$1"
OVS_BRIDGE="$2"

# Validaciones
if [[ -z "$VLAN_ID" || -z "$OVS_BRIDGE" ]]; then
    echo "ERROR: Todos los parametros son requeridos"
    echo "Uso: $0 VLAN_ID OVS_BRIDGE"
    echo "Ejemplo: $0 100 br-cloud"
    exit 1
fi

# Configuración
PASSWORD="alejandro"
WORKERS=("Worker-1" "Worker-2" "Worker-3")
WORKER_SCRIPT_PATH="scripts_orquestacion/cleanup_vlan.sh"

echo "========================================="
echo "    LIMPIEZA COMPLETA DE VLAN $VLAN_ID"
echo "========================================="
echo "VLAN ID: $VLAN_ID"
echo "OVS Bridge: $OVS_BRIDGE"
echo "Workers: ${WORKERS[*]}"
echo ""

# Función para ejecutar comandos con sudo usando contraseña
execute_with_sudo() {
    local command="$1"
    echo "$PASSWORD" | sudo -S $command
}

# Función para ejecutar comandos remotos con sudo usando contraseña
execute_remote_sudo() {
    local host="$1"
    local command="$2"
    echo "$PASSWORD" | ssh -o StrictHostKeyChecking=no "$host" "echo '$PASSWORD' | sudo -S $command"
}

echo "PASO 1: Limpiando VLAN $VLAN_ID en HEADNODE..."
echo "----------------------------------------------"
if execute_with_sudo "./cleanup_vlan.sh $VLAN_ID $OVS_BRIDGE"; then
    echo "✓ Headnode: VLAN $VLAN_ID limpiada exitosamente"
else
    echo "✗ Error: Fallo al limpiar VLAN $VLAN_ID en headnode"
    echo "Continuando con workers..."
fi
echo ""

echo "PASO 2: Limpiando VLAN $VLAN_ID en WORKERS..."
echo "----------------------------------------------"
for worker in "${WORKERS[@]}"; do
    echo "Limpiando VLAN $VLAN_ID en $worker..."
    
    if execute_remote_sudo "$worker" "cd /home/ubuntu && ./$WORKER_SCRIPT_PATH $VLAN_ID"; then
        echo "✓ $worker: VLAN $VLAN_ID limpiada exitosamente"
    else
        echo "✗ $worker: Error al limpiar VLAN $VLAN_ID"
    fi
    echo ""
done

echo "========================================="
echo "       LIMPIEZA COMPLETA FINALIZADA"
echo "========================================="
echo "VLAN $VLAN_ID ha sido eliminada de:"
echo "  - Headnode (namespace DHCP, interfaces OVS, reglas iptables)"
echo "  - Todos los workers (VMs, interfaces TAP, configuración OVS)"
echo ""
echo "Verificación recomendada:"
echo "  - Headnode: ip netns list | grep id$VLAN_ID"
echo "  - Workers: ssh Worker-X 'ps aux | grep qemu | grep id$VLAN_ID'"
echo ""
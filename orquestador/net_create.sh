#!/bin/bash

set -e  # Exit on any error

# Parametros
ID="$1"
VLANS="$2"
OVS_BRIDGE="$3"
GATEWAY_IP="$4"
DHCP_RANGE_SIZE=5

# Verificar parámetros
if [ -z "$ID" ] || [ -z "$VLANS" ] || [ -z "$OVS_BRIDGE" ] || [ -z "$GATEWAY_IP" ]; then
    echo "ERROR: Faltan parámetros"
    echo "Uso: $0 <id> <vlans> <ovs_bridge> <gateway_ip>"
    echo "Ejemplo: $0 test1 1;4 br0 192.168.1.1"
    exit 1
fi

# Verificar que se ejecuta como root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Este script debe ejecutarse como root o con sudo"
    exit 1
fi

# Verificar que el bridge OVS existe
if ! ovs-vsctl br-exists "$OVS_BRIDGE"; then
    echo "ERROR: Bridge OVS $OVS_BRIDGE no existe"
    exit 1
fi

# Parsear rango de VLANs
IFS=';' read -r START_VLAN END_VLAN <<< "$VLANS"

# Validar rango de VLANs
if ! [[ "$START_VLAN" =~ ^[0-9]+$ ]] || ! [[ "$END_VLAN" =~ ^[0-9]+$ ]]; then
    echo "ERROR: El rango de VLANs debe ser numérico"
    exit 1
fi

if [ "$START_VLAN" -gt "$END_VLAN" ]; then
    echo "ERROR: El VLAN inicial no puede ser mayor que el final"
    exit 1
fi

# Función para calcular subnet basado en VLAN
calculate_subnet() {
    local vlan=$1
    if [ "$vlan" -le 255 ]; then
        echo "10.1.$vlan"
    else
        # Para VLANs > 255, calcular el segundo y tercer octeto
        local second_octet=$(( (vlan - 1) / 255 + 1 ))
        local third_octet=$(( (vlan - 1) % 255 + 1 ))
        echo "10.$second_octet.$third_octet"
    fi
}

# Crear directorios necesarios
mkdir -p /var/run/dhcp /var/lib/dhcp

# Calcular subnet de la primera VLAN (para el gateway)
FIRST_VLAN_SUBNET=$(calculate_subnet "$START_VLAN")

echo "========================================="
echo "   CREANDO NAMESPACES DHCP PARA VLANS $START_VLAN-$END_VLAN"
echo "   ID: $ID"
echo "========================================="
echo "Bridge OVS: $OVS_BRIDGE"
echo "Configuración: Cada VLAN tendrá su propio gateway interno"
echo "Primera VLAN: $START_VLAN (subnet: $FIRST_VLAN_SUBNET.0/24)"
echo "Gateway base IP: $GATEWAY_IP"
echo ""

# Habilitar IP forwarding una sola vez
sysctl -w net.ipv4.ip_forward=1 > /dev/null
echo "IP forwarding habilitado"

# Procesar cada VLAN en el rango
for VLAN_ID in $(seq "$START_VLAN" "$END_VLAN"); do
    echo ""
    echo "-----------------------------------------"
    echo "Procesando VLAN $VLAN_ID"
    echo "-----------------------------------------"
    
    # Definir variables usando el nuevo esquema de nomenclatura con id
    NAMESPACE="id${ID}-ns${VLAN_ID}"
    VETH_OVS="id${ID}-vovs${VLAN_ID}"
    VETH_NS="id${ID}-vns${VLAN_ID}"
    OVS_INTERNAL_IFACE="id${ID}-gw${VLAN_ID}"
    
    # Calcular subnet para esta VLAN
    SUBNET=$(calculate_subnet "$VLAN_ID")
    IP_NAMESPACE="${SUBNET}.2"
    START_IP="${SUBNET}.10"
    END_IP="${SUBNET}.$((10 + DHCP_RANGE_SIZE - 1))"
    
    # Archivos de configuración específicos para esta VLAN
    DNSMASQ_PID_FILE="/var/run/dhcp/id${ID}-dnsmasq-${VLAN_ID}.pid"
    DNSMASQ_LEASE_FILE="/var/lib/dhcp/id${ID}-dnsmasq-${VLAN_ID}.leases"
    
    # Determinar si esta VLAN es la del gateway principal
    IS_GATEWAY_VLAN=false
    if [ "$VLAN_ID" -eq "$START_VLAN" ]; then
        IS_GATEWAY_VLAN=true
        VLAN_GATEWAY_IP="$GATEWAY_IP"
    else
        # Para las demás VLANs, usar la .1 de su subnet como gateway
        VLAN_GATEWAY_IP="${SUBNET}.1"
    fi
    
    echo "Configuración VLAN $VLAN_ID:"
    echo "  - Namespace: $NAMESPACE"
    echo "  - Subnet: $SUBNET.0/24"
    echo "  - DHCP Server IP: $IP_NAMESPACE"
    echo "  - DHCP Range: $START_IP - $END_IP"
    echo "  - Gateway: $VLAN_GATEWAY_IP"
    if [ "$IS_GATEWAY_VLAN" = true ]; then
        echo "  - [PRIMERA VLAN] Puerto interno OVS con gateway configurado"
    else
        echo "  - [VLAN ADICIONAL] Puerto interno OVS con gateway propio"
    fi
    
    # Verificar si el namespace ya existe
    if ip netns list | grep -q "^${NAMESPACE}$"; then
        echo "ERROR: Namespace $NAMESPACE ya existe"
        echo "Para eliminar: sudo ./cleanup_vlan.sh $ID $OVS_BRIDGE"
        continue
    fi
    
    # Crear namespace
    ip netns add "$NAMESPACE"
    echo "  ✓ Namespace $NAMESPACE creado"
    
    # Crear pair veth
    ip link add "$VETH_OVS" type veth peer name "$VETH_NS"
    echo "  ✓ Veth pair creado: $VETH_OVS <-> $VETH_NS"
    
    # Mover una punta al namespace
    ip link set "$VETH_NS" netns "$NAMESPACE"
    
    # Conectar la otra punta al bridge OVS con VLAN tag
    ovs-vsctl add-port "$OVS_BRIDGE" "$VETH_OVS" tag="$VLAN_ID"
    echo "  ✓ Puerto $VETH_OVS agregado al bridge con VLAN $VLAN_ID"
    
    # Levantar interfaces
    ip link set "$VETH_OVS" up
    ip netns exec "$NAMESPACE" ip link set dev lo up
    ip netns exec "$NAMESPACE" ip link set dev "$VETH_NS" up
    
    # Configurar IP en el namespace
    ip netns exec "$NAMESPACE" ip addr add "$IP_NAMESPACE/24" dev "$VETH_NS"
    echo "  ✓ IP $IP_NAMESPACE/24 asignada a $VETH_NS en namespace"
    
    # Crear interfaz interna en OVS para todas las VLANs (cada una actúa como gateway)
    ovs-vsctl add-port "$OVS_BRIDGE" "$OVS_INTERNAL_IFACE" tag="$VLAN_ID" -- set interface "$OVS_INTERNAL_IFACE" type=internal
    echo "  ✓ Interfaz interna $OVS_INTERNAL_IFACE creada en OVS"
    
    # Levantar interfaz interna y asignar IP del gateway
    ip link set "$OVS_INTERNAL_IFACE" up
    ip addr add "${VLAN_GATEWAY_IP}/24" dev "$OVS_INTERNAL_IFACE"
    echo "  ✓ Gateway $VLAN_GATEWAY_IP asignado a interfaz $OVS_INTERNAL_IFACE"
    
    # Configurar ruta por defecto en namespace hacia el gateway
    ip netns exec "$NAMESPACE" ip route add default via "$VLAN_GATEWAY_IP" dev "$VETH_NS"
    echo "  ✓ Ruta por defecto configurada en namespace"
    
    # Iniciar servidor DHCP en el namespace
    echo "  ⚙ Iniciando dnsmasq en namespace $NAMESPACE..."
    # Todas las VLANs ahora tienen gateway - anunciar el gateway correspondiente en DHCP
    ip netns exec "$NAMESPACE" dnsmasq \
        --interface="$VETH_NS" \
        --bind-interfaces \
        --dhcp-range="${START_IP},${END_IP},255.255.255.0" \
        --dhcp-option=3,"$VLAN_GATEWAY_IP" \
        --pid-file="$DNSMASQ_PID_FILE" \
        --dhcp-leasefile="$DNSMASQ_LEASE_FILE" \
        --no-daemon &
    
    # Obtener PID y guardarlo
    DNSMASQ_PID=$!
    echo "$DNSMASQ_PID" > "$DNSMASQ_PID_FILE"
    
    # Verificar que dnsmasq se inició correctamente
    sleep 1
    if [[ -f "$DNSMASQ_PID_FILE" ]] && kill -0 "$(cat "$DNSMASQ_PID_FILE")" 2>/dev/null; then
        DNSMASQ_PID=$(cat "$DNSMASQ_PID_FILE")
        echo "  ✓ Servidor DHCP iniciado correctamente (PID: $DNSMASQ_PID)"
    else
        echo "  ✗ ERROR: No se pudo iniciar el servidor DHCP para VLAN $VLAN_ID"
        continue
    fi
    
    echo "  ✓ VLAN $VLAN_ID configurada exitosamente"
done

echo ""
echo "========================================="
echo "   CONFIGURACIÓN COMPLETADA"
echo "========================================="
echo "ID: $ID"
echo "VLANs configuradas: $START_VLAN-$END_VLAN"
echo "Bridge OVS: $OVS_BRIDGE"
echo ""
echo "Para eliminar todo: sudo ./cleanup_vlan.sh $ID $OVS_BRIDGE"
echo ""
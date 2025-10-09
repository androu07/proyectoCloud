#!/bin/bash

set -e  # Exit on any error

# Parametros
VLAN_ID="$1"
OVS_BRIDGE="$2"
DHCP_RANGE_SIZE="$3"
BASE_SUBNET="10.7"

# Validaciones
if [[ -z "$VLAN_ID" || -z "$OVS_BRIDGE" || -z "$DHCP_RANGE_SIZE" ]]; then
    echo "ERROR: Todos los parametros son requeridos"
    echo "Uso: $0 VLAN_ID OVS_BRIDGE DHCP_RANGE_SIZE"
    echo "Ejemplo: $0 100 br-cloud 50"
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

# Configuración de red
SUBNET="${BASE_SUBNET}.${VLAN_ID}.0/24"
START_IP="${BASE_SUBNET}.${VLAN_ID}.1"
END_IP="${BASE_SUBNET}.${VLAN_ID}.${DHCP_RANGE_SIZE}"
GATEWAY="${BASE_SUBNET}.${VLAN_ID}.$((1 + DHCP_RANGE_SIZE))"
IP_NAMESPACE="${BASE_SUBNET}.${VLAN_ID}.$((2 + DHCP_RANGE_SIZE))"
NAMESPACE="id${VLAN_ID}-dhcp"
VETH_NS="id${VLAN_ID}-nsvt"
VETH_OVS="id${VLAN_ID}-ovsvt"
OVS_INTERNAL_IFACE="id${VLAN_ID}-gw"
DNSMASQ_PID_FILE="/var/run/dhcp/id${VLAN_ID}-dnsmasq.pid"
DNSMASQ_LEASE_FILE="/var/lib/dhcp/id${VLAN_ID}-dnsmasq.leases"

echo "========================================="
echo "   CREANDO NAMESPACE DHCP PARA VLAN $VLAN_ID"
echo "========================================="
echo "Bridge OVS: $OVS_BRIDGE"
echo "Subnet: $SUBNET"
echo "DHCP Range: $START_IP - $END_IP"
echo "Gateway: $GATEWAY"
echo "Namespace IP: $IP_NAMESPACE"
echo ""

# Crear directorios necesarios
mkdir -p /var/run/dhcp /var/lib/dhcp

# Verificar si el namespace ya existe
if ip netns list | grep -q "^${NAMESPACE}$"; then
    echo "ERROR: Namespace $NAMESPACE ya existe"
    echo "Para eliminar: sudo ./cleanup_vlan.sh $VLAN_ID $OVS_BRIDGE"
    exit 1
fi

# Crear namespace
ip netns add "$NAMESPACE"
echo "Namespace $NAMESPACE creado"

# Crear pair veth
ip link add "$VETH_OVS" type veth peer name "$VETH_NS"
echo "Veth pair creado: $VETH_OVS <-> $VETH_NS"

# Mover una punta al namespace
ip link set "$VETH_NS" netns "$NAMESPACE"

# Conectar la otra punta al bridge OVS con VLAN tag
ovs-vsctl add-port "$OVS_BRIDGE" "$VETH_OVS" tag="$VLAN_ID"
echo "Puerto $VETH_OVS agregado al bridge con VLAN $VLAN_ID"

# Levantar interfaces
ip link set "$VETH_OVS" up
ip netns exec "$NAMESPACE" ip link set dev lo up
ip netns exec "$NAMESPACE" ip link set dev "$VETH_NS" up

# Configurar IP en el namespace
ip netns exec "$NAMESPACE" ip addr add "$IP_NAMESPACE/24" dev "$VETH_NS"
echo "IP $IP_NAMESPACE/24 asignada a $VETH_NS en namespace"

# Crear interfaz interna en OVS para actuar como gateway
ovs-vsctl add-port "$OVS_BRIDGE" "$OVS_INTERNAL_IFACE" tag="$VLAN_ID" -- set interface "$OVS_INTERNAL_IFACE" type=internal
echo "Interfaz interna $OVS_INTERNAL_IFACE creada en OVS"

# Levantar interfaz interna y asignar IP del gateway
ip link set "$OVS_INTERNAL_IFACE" up
ip addr add "${GATEWAY}/24" dev "$OVS_INTERNAL_IFACE"
echo "Gateway $GATEWAY asignado a interfaz $OVS_INTERNAL_IFACE"

# Habilitar IP forwarding
sysctl -w net.ipv4.ip_forward=1 > /dev/null
echo "IP forwarding habilitado"

# Configurar ruta por defecto en namespace hacia el gateway
ip netns exec "$NAMESPACE" ip route add default via "$GATEWAY" dev "$VETH_NS"
echo "Ruta por defecto configurada en namespace"

# Iniciar servidor DHCP en el namespace
echo "Iniciando dnsmasq en namespace $NAMESPACE..."
ip netns exec "$NAMESPACE" dnsmasq \
    --interface="$VETH_NS" \
    --bind-interfaces \
    --dhcp-range="${START_IP},${END_IP},255.255.255.0" \
    --dhcp-option=3,"$GATEWAY" \
    --pid-file="$DNSMASQ_PID_FILE" \
    --dhcp-leasefile="$DNSMASQ_LEASE_FILE" \
    --no-daemon &

# Obtener PID y guardarlo
DNSMASQ_PID=$!
echo "$DNSMASQ_PID" > "$DNSMASQ_PID_FILE"

# Verificar que dnsmasq se inició correctamente
if [[ -f "$DNSMASQ_PID_FILE" ]] && kill -0 "$(cat "$DNSMASQ_PID_FILE")" 2>/dev/null; then
    DNSMASQ_PID=$(cat "$DNSMASQ_PID_FILE")
    echo "Servidor DHCP iniciado correctamente (PID: $DNSMASQ_PID)"
else
    echo "ERROR: No se pudo iniciar el servidor DHCP"
    exit 1
fi

echo ""
echo "========================================="
echo "   VLAN $VLAN_ID DHCP CONFIGURADO OK"
echo "========================================="
echo "Configuración:"
echo "  - Namespace: $NAMESPACE"
echo "  - VLAN ID: $VLAN_ID"
echo "  - Subnet: $SUBNET"
echo "  - Gateway: $GATEWAY (en interfaz $OVS_INTERNAL_IFACE)"
echo "  - DHCP Range: $START_IP - $END_IP"
echo "  - DHCP Server IP: $IP_NAMESPACE"
echo "  - PID File: $DNSMASQ_PID_FILE"
echo "  - Lease File: $DNSMASQ_LEASE_FILE"
echo ""
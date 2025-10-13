#!/bin/bash

set -e  # Exit on any error

# Parámetros
VLAN_ID="$1"
BASE_SUBNET="10.7"

# Verificar que se ejecuta como root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Este script debe ejecutarse como root o con sudo"
    exit 1
fi

# Configuración de red
SUBNET="${BASE_SUBNET}.${VLAN_ID}.0/24"
OVS_INTERNAL_IFACE="id${VLAN_ID}-gw"

# Detectar interfaz de Internet (la que tiene ruta por defecto)
INTERNET_IFACE=$(ip route | grep default | head -1 | awk '{print $5}')

if [[ -z "$INTERNET_IFACE" ]]; then
    echo "ERROR: No se pudo detectar la interfaz de Internet"
    echo "Verifica que tengas una ruta por defecto configurada"
    exit 1
fi

echo "========================================="
echo " CONFIGURANDO ACCESO A INTERNET VLAN $VLAN_ID"
echo "========================================="
echo "VLAN ID: $VLAN_ID"
echo "Subnet: $SUBNET"
echo "Interfaz Gateway: $OVS_INTERNAL_IFACE"
echo "Interfaz Internet: $INTERNET_IFACE"
echo ""

# Verificar que la interfaz gateway de la VLAN existe
if ! ip link show "$OVS_INTERNAL_IFACE" &>/dev/null; then
    echo "ERROR: Interfaz $OVS_INTERNAL_IFACE no existe"
    echo "Primero ejecuta net_create.sh para crear la VLAN $VLAN_ID"
    exit 1
fi

# Configurar NAT (MASQUERADE) para la VLAN
echo "Configurando NAT para subnet $SUBNET..."
iptables -t nat -A POSTROUTING -s "$SUBNET" -o "$INTERNET_IFACE" -j MASQUERADE

# Permitir forwarding desde la VLAN hacia Internet
echo "Permitiendo forwarding desde VLAN hacia Internet..."
iptables -A FORWARD -i "$OVS_INTERNAL_IFACE" -o "$INTERNET_IFACE" -j ACCEPT

# Permitir forwarding de respuestas desde Internet hacia la VLAN
echo "Permitiendo forwarding de respuestas desde Internet hacia VLAN..."
iptables -A FORWARD -i "$INTERNET_IFACE" -o "$OVS_INTERNAL_IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT

echo ""
echo "========================================="
echo "   ACCESO A INTERNET CONFIGURADO OK"
echo "========================================="
echo "Configuración aplicada:"
echo "  - NAT habilitado para subnet $SUBNET"
echo "  - Forwarding permitido desde $OVS_INTERNAL_IFACE hacia $INTERNET_IFACE"
echo "  - Forwarding de respuestas permitido desde $INTERNET_IFACE hacia $OVS_INTERNAL_IFACE"
echo "  - IP forwarding habilitado en el sistema"
echo ""
echo "Las VMs en VLAN $VLAN_ID ahora tienen acceso a Internet"
echo ""

# Mostrar reglas aplicadas
echo "Reglas iptables aplicadas:"
echo "------------------------"
echo "NAT:"
iptables -t nat -L POSTROUTING -n --line-numbers | grep "$SUBNET"
echo ""
echo "FORWARD:"
iptables -L FORWARD -n --line-numbers | grep "$OVS_INTERNAL_IFACE\|$INTERNET_IFACE" | head -2
echo ""
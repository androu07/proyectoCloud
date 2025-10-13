#!/bin/bash

set -e  # Exit on any error

# Parámetros
ID="$1"
VLAN_RANGE="$2"  # Puede ser una sola VLAN o rango "a;z"
BASE_SUBNET="10.1"

# Verificar que se ejecuta como root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Este script debe ejecutarse como root o con sudo"
    exit 1
fi

# Función para procesar rango de VLANs
parse_vlan_range() {
    local vlan_input="$1"
    local vlans=()
    
    if [[ "$vlan_input" == *";"* ]]; then
        # Es un rango "a;z"
        IFS=';' read -ra RANGE <<< "$vlan_input"
        local start_vlan="${RANGE[0]}"
        local end_vlan="${RANGE[1]}"
        
        # Validar que el rango sea válido
        if [[ "$start_vlan" -gt "$end_vlan" ]]; then
            echo "ERROR: El VLAN inicial ($start_vlan) no puede ser mayor que el final ($end_vlan)"
            exit 1
        fi
        
        # Generar lista de VLANs en el rango
        for ((i=start_vlan; i<=end_vlan; i++)); do
            vlans+=("$i")
        done
    else
        # Es una sola VLAN
        vlans=("$vlan_input")
    fi
    
    echo "${vlans[@]}"
}

# Obtener lista de VLANs a configurar
VLAN_LIST=($(parse_vlan_range "$VLAN_RANGE"))

# Verificar que se ejecuta como root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Este script debe ejecutarse como root o con sudo"
    exit 1
fi

# Detectar interfaz de Internet (la que tiene ruta por defecto)
INTERNET_IFACE=$(ip route | grep default | head -1 | awk '{print $5}')

if [[ -z "$INTERNET_IFACE" ]]; then
    echo "ERROR: No se pudo detectar la interfaz de Internet"
    echo "Verifica que tengas una ruta por defecto configurada"
    exit 1
fi

echo "========================================="
echo " CONFIGURANDO ACCESO A INTERNET"
echo "========================================="
echo "VLANs a configurar: ${VLAN_LIST[*]}"
echo "Total VLANs: ${#VLAN_LIST[@]}"
echo "Interfaz Internet: $INTERNET_IFACE"
echo ""

# Habilitar IP forwarding
echo 1 > /proc/sys/net/ipv4/ip_forward

# Contador de VLANs configuradas
configured_count=0
skipped_count=0

# Procesar cada VLAN
for VLAN_ID in "${VLAN_LIST[@]}"; do
    SUBNET="${BASE_SUBNET}.${VLAN_ID}.0/24"
    OVS_INTERNAL_IFACE="id${ID}-gw${VLAN_ID}"
    
    echo "Configurando VLAN $VLAN_ID..."
    echo "  Subnet: $SUBNET"
    echo "  Interfaz Gateway: $OVS_INTERNAL_IFACE"
    
    # Verificar que la interfaz gateway de la VLAN existe
    if ! ip link show "$OVS_INTERNAL_IFACE" &>/dev/null; then
        echo "  ⚠️  ADVERTENCIA: Interfaz $OVS_INTERNAL_IFACE no existe - VLAN $VLAN_ID saltada"
        echo "     Primero ejecuta net_create.sh para crear la VLAN $VLAN_ID"
        ((skipped_count++))
        continue
    fi
    
    # Verificar si ya existen reglas para esta VLAN (evitar duplicados)
    if iptables -t nat -C POSTROUTING -s "$SUBNET" -o "$INTERNET_IFACE" -j MASQUERADE &>/dev/null; then
        echo "  ℹ️  Reglas NAT ya existen para VLAN $VLAN_ID - saltando"
        ((skipped_count++))
        continue
    fi
    
    # Configurar NAT (MASQUERADE) para la VLAN
    echo "  📡 Configurando NAT para subnet $SUBNET..."
    iptables -t nat -A POSTROUTING -s "$SUBNET" -o "$INTERNET_IFACE" -j MASQUERADE
    
    # Permitir forwarding desde la VLAN hacia Internet
    echo "  ↗️  Permitiendo forwarding desde VLAN hacia Internet..."
    iptables -A FORWARD -i "$OVS_INTERNAL_IFACE" -o "$INTERNET_IFACE" -j ACCEPT
    
    # Permitir forwarding de respuestas desde Internet hacia la VLAN
    echo "  ↙️  Permitiendo forwarding de respuestas desde Internet hacia VLAN..."
    iptables -A FORWARD -i "$INTERNET_IFACE" -o "$OVS_INTERNAL_IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT
    
    echo "  ✅ VLAN $VLAN_ID configurada exitosamente"
    ((configured_count++))
    echo ""
done

echo ""
echo "========================================="
echo "   RESUMEN DE CONFIGURACIÓN"
echo "========================================="
echo "VLANs configuradas: $configured_count"
echo "VLANs saltadas: $skipped_count"
echo "Total procesadas: ${#VLAN_LIST[@]}"
echo ""

if [[ $configured_count -gt 0 ]]; then
    echo "✅ Acceso a Internet habilitado para las VLANs configuradas"
    echo ""
    echo "Configuración aplicada:"
    echo "  - NAT habilitado para las subnets correspondientes"
    echo "  - Forwarding permitido bidireccional"
    echo "  - IP forwarding habilitado en el sistema"
    echo ""
    
    # Mostrar resumen de reglas aplicadas
    echo "Reglas iptables aplicadas:"
    echo "------------------------"
    echo "NAT (POSTROUTING):"
    for VLAN_ID in "${VLAN_LIST[@]}"; do
        SUBNET="${BASE_SUBNET}.${VLAN_ID}.0/24"
        if iptables -t nat -C POSTROUTING -s "$SUBNET" -o "$INTERNET_IFACE" -j MASQUERADE &>/dev/null; then
            echo "  VLAN $VLAN_ID: $SUBNET -> $INTERNET_IFACE (MASQUERADE)"
        fi
    done
    echo ""
else
    echo "⚠️  No se configuraron nuevas VLANs para acceso a Internet"
    echo "   Verifica que las VLANs existan o que no estén ya configuradas"
fi

echo ""
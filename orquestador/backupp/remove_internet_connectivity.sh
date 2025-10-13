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

# Obtener lista de VLANs a limpiar
VLAN_LIST=($(parse_vlan_range "$VLAN_RANGE"))

# Detectar interfaz de Internet (la que tiene ruta por defecto)
INTERNET_IFACE=$(ip route | grep default | head -1 | awk '{print $5}')

if [[ -z "$INTERNET_IFACE" ]]; then
    echo "ERROR: No se pudo detectar la interfaz de Internet"
    echo "Verifica que tengas una ruta por defecto configurada"
    exit 1
fi

echo "========================================="
echo " REMOVIENDO ACCESO A INTERNET"
echo "========================================="
echo "VLANs a limpiar: ${VLAN_LIST[*]}"
echo "Total VLANs: ${#VLAN_LIST[@]}"
echo "Interfaz Internet: $INTERNET_IFACE"
echo ""

# Contador de VLANs procesadas
removed_count=0
not_found_count=0

# Procesar cada VLAN
for VLAN_ID in "${VLAN_LIST[@]}"; do
    SUBNET="${BASE_SUBNET}.${VLAN_ID}.0/24"
    OVS_INTERNAL_IFACE="id${ID}-gw${VLAN_ID}"
    
    echo "Procesando VLAN $VLAN_ID..."
    echo "  Subnet: $SUBNET"
    echo "  Interfaz Gateway: $OVS_INTERNAL_IFACE"
    
    # Variables para trackear si se encontraron reglas
    nat_found=false
    forward1_found=false
    forward2_found=false
    
    # Remover regla NAT (MASQUERADE)
    echo "  🔍 Buscando regla NAT..."
    if iptables -t nat -C POSTROUTING -s "$SUBNET" -o "$INTERNET_IFACE" -j MASQUERADE &>/dev/null; then
        echo "  🗑️  Removiendo regla NAT para subnet $SUBNET..."
        iptables -t nat -D POSTROUTING -s "$SUBNET" -o "$INTERNET_IFACE" -j MASQUERADE
        nat_found=true
    else
        echo "  ℹ️  No se encontró regla NAT para VLAN $VLAN_ID"
    fi
    
    # Remover regla FORWARD desde VLAN hacia Internet
    echo "  🔍 Buscando regla FORWARD (VLAN->Internet)..."
    if iptables -C FORWARD -i "$OVS_INTERNAL_IFACE" -o "$INTERNET_IFACE" -j ACCEPT &>/dev/null; then
        echo "  🗑️  Removiendo regla FORWARD desde VLAN hacia Internet..."
        iptables -D FORWARD -i "$OVS_INTERNAL_IFACE" -o "$INTERNET_IFACE" -j ACCEPT
        forward1_found=true
    else
        echo "  ℹ️  No se encontró regla FORWARD (VLAN->Internet) para VLAN $VLAN_ID"
    fi
    
    # Remover regla FORWARD de respuestas desde Internet hacia VLAN
    echo "  🔍 Buscando regla FORWARD (Internet->VLAN)..."
    if iptables -C FORWARD -i "$INTERNET_IFACE" -o "$OVS_INTERNAL_IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT &>/dev/null; then
        echo "  🗑️  Removiendo regla FORWARD de respuestas desde Internet hacia VLAN..."
        iptables -D FORWARD -i "$INTERNET_IFACE" -o "$OVS_INTERNAL_IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT
        forward2_found=true
    else
        echo "  ℹ️  No se encontró regla FORWARD (Internet->VLAN) para VLAN $VLAN_ID"
    fi
    
    # Determinar el resultado para esta VLAN
    if $nat_found || $forward1_found || $forward2_found; then
        echo "  ✅ VLAN $VLAN_ID: Reglas de Internet removidas exitosamente"
        ((removed_count++))
    else
        echo "  ⚠️  VLAN $VLAN_ID: No tenía acceso a Internet configurado"
        ((not_found_count++))
    fi
    echo ""
done

echo ""
echo "========================================="
echo "   RESUMEN DE LIMPIEZA"
echo "========================================="
echo "VLANs con reglas removidas: $removed_count"
echo "VLANs sin reglas existentes: $not_found_count"
echo "Total procesadas: ${#VLAN_LIST[@]}"
echo ""

if [[ $removed_count -gt 0 ]]; then
    echo "✅ Acceso a Internet removido exitosamente para $removed_count VLAN(s)"
    echo ""
    echo "Acciones realizadas:"
    echo "  - Reglas NAT (MASQUERADE) eliminadas"
    echo "  - Reglas FORWARD bidireccionales eliminadas"
    echo "  - Las VMs en las VLANs ya NO tienen acceso a Internet"
    echo ""
    
    # Verificar si quedan reglas relacionadas con estas VLANs
    echo "Verificación post-limpieza:"
    echo "-------------------------"
    remaining_rules=false
    
    for VLAN_ID in "${VLAN_LIST[@]}"; do
        SUBNET="${BASE_SUBNET}.${VLAN_ID}.0/24"
        OVS_INTERNAL_IFACE="id${ID}-gw${VLAN_ID}"
        
        # Verificar NAT
        if iptables -t nat -L POSTROUTING -n | grep -q "$SUBNET"; then
            echo "⚠️  ADVERTENCIA: Aún existen reglas NAT para VLAN $VLAN_ID"
            remaining_rules=true
        fi
        
        # Verificar FORWARD
        if iptables -L FORWARD -n | grep -q "$OVS_INTERNAL_IFACE"; then
            echo "⚠️  ADVERTENCIA: Aún existen reglas FORWARD para VLAN $VLAN_ID"
            remaining_rules=true
        fi
    done
    
    if ! $remaining_rules; then
        echo "✅ Limpieza completa - No se detectaron reglas residuales"
    fi
    
else
    echo "ℹ️  No se removieron reglas - Las VLANs especificadas no tenían acceso a Internet configurado"
fi

echo ""
echo "📋 Para verificar el estado actual de iptables:"
echo "   NAT: iptables -t nat -L POSTROUTING -n --line-numbers"
echo "   FORWARD: iptables -L FORWARD -n --line-numbers"
echo ""
#!/bin/bash

# No usar set -e para que no se detenga en errores menores

# Parámetros
ID="$1"
OVS_BRIDGE="$2"

# Verificar parámetros
if [ -z "$ID" ] || [ -z "$OVS_BRIDGE" ]; then
    echo "ERROR: Faltan parámetros"
    echo "Uso: $0 <id> <ovs_bridge>"
    echo "Ejemplo: $0 1 br-cloud"
    exit 1
fi

# Verificar que se ejecuta como root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Este script debe ejecutarse como root o con sudo"
    exit 1
fi

echo "========================================="
echo "   LIMPIANDO RECURSOS PARA ID: $ID"
echo "========================================="
echo "Bridge OVS: $OVS_BRIDGE"
echo ""

echo "1. Deteniendo procesos dnsmasq..."
# Buscar y matar procesos dnsmasq basados en archivos PID
for pid_file in /var/run/dhcp/id${ID}-dnsmasq-*.pid; do
    if [ -f "$pid_file" ]; then
        if pid=$(cat "$pid_file" 2>/dev/null) && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null && echo "  ✓ Proceso dnsmasq detenido (PID: $pid)"
        fi
        rm -f "$pid_file" && echo "  ✓ Archivo PID eliminado: $pid_file"
    fi
done

echo ""
echo "2. Eliminando archivos de lease..."
# Eliminar archivos de lease
for lease_file in /var/lib/dhcp/id${ID}-dnsmasq-*.leases; do
    if [ -f "$lease_file" ]; then
        rm -f "$lease_file" && echo "  ✓ Archivo lease eliminado: $lease_file"
    fi
done

echo ""
echo "3. Eliminando namespaces de red..."
# Eliminar namespaces - usar una aproximación más simple
namespaces=$(ip netns list 2>/dev/null | grep "^id${ID}-ns" | awk '{print $1}' || true)
for ns in $namespaces; do
    if [ -n "$ns" ]; then
        if ip netns delete "$ns" 2>/dev/null; then
            echo "  ✓ Namespace eliminado: $ns"
        else
            echo "  ⚠ No se pudo eliminar namespace: $ns"
        fi
    fi
done

echo ""
echo "4. Eliminando puertos del bridge OVS..."
# Verificar que el bridge OVS existe
if ! ovs-vsctl br-exists "$OVS_BRIDGE" 2>/dev/null; then
    echo "  ⚠ Bridge OVS $OVS_BRIDGE no existe, saltando eliminación de puertos"
else
    # Eliminar puertos veth del bridge OVS
    ports=$(ovs-vsctl list-ports "$OVS_BRIDGE" 2>/dev/null | grep "^id${ID}-" || true)
    for port in $ports; do
        if [ -n "$port" ]; then
            if ovs-vsctl del-port "$OVS_BRIDGE" "$port" 2>/dev/null; then
                echo "  ✓ Puerto eliminado del bridge: $port"
            else
                echo "  ⚠ No se pudo eliminar puerto: $port"
            fi
        fi
    done
fi

echo ""
echo "5. Eliminando interfaces veth restantes..."
# Eliminar interfaces veth que puedan haber quedado
interfaces=$(ip link show 2>/dev/null | grep "id${ID}-v" | awk -F': ' '{print $2}' | awk -F'@' '{print $1}' || true)
for iface in $interfaces; do
    if [ -n "$iface" ]; then
        if ip link delete "$iface" 2>/dev/null; then
            echo "  ✓ Interfaz veth eliminada: $iface"
        else
            echo "  ⚠ No se pudo eliminar: $iface"
        fi
    fi
done

echo ""
echo "6. Eliminando interfaces internas OVS (gateways)..."
# Eliminar interfaces internas OVS (gateways) - ya se eliminaron en el paso 4, pero verificamos
gateways=$(ip link show 2>/dev/null | grep "id${ID}-gw" | awk -F': ' '{print $2}' | awk -F'@' '{print $1}' || true)
for iface in $gateways; do
    if [ -n "$iface" ]; then
        # Primero eliminar del OVS si existe
        if ovs-vsctl br-exists "$OVS_BRIDGE" 2>/dev/null; then
            ovs-vsctl --if-exists del-port "$OVS_BRIDGE" "$iface" 2>/dev/null
        fi
        # La interfaz se elimina automáticamente al eliminarla del OVS
        echo "  ✓ Interfaz gateway eliminada: $iface"
    fi
done

echo ""
echo "========================================="
echo "   LIMPIEZA COMPLETADA"
echo "========================================="
echo "ID limpiado: $ID"
echo ""
echo "✓ Limpieza exitosa. Todos los recursos con prefijo 'id${ID}-' han sido eliminados."
echo ""
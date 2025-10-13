#!/bin/bash

# Script para limpiar todo lo creado por net_create.sh
# Uso: ./cleanup_slice.sh <slice_id>
# Ejemplo: ./cleanup_slice.sh 1

if [ $# -eq 0 ]; then
    echo "❌ Error: Falta el parámetro slice_id"
    echo "Uso: $0 <slice_id>"
    echo "Ejemplo: $0 1"
    exit 1
fi

SLICE_ID="$1"
SUDO_PASSWORD="alejandro"

echo "🧹 Iniciando limpieza del slice: $SLICE_ID"
echo "🔍 Buscando recursos con prefijo: id${SLICE_ID}-"

# Función para ejecutar comandos con sudo
run_sudo() {
    echo "$SUDO_PASSWORD" | sudo -S "$@" 2>/dev/null
}

# 1. Detener procesos dnsmasq del slice
echo ""
echo "🛑 Deteniendo procesos DHCP (dnsmasq)..."
DNSMASQ_PIDS=$(ps aux | grep "dnsmasq.*id${SLICE_ID}-" | grep -v grep | awk '{print $2}')
if [ ! -z "$DNSMASQ_PIDS" ]; then
    for pid in $DNSMASQ_PIDS; do
        echo "   Deteniendo dnsmasq PID: $pid"
        run_sudo kill -9 "$pid"
    done
else
    echo "   ℹ️  No se encontraron procesos dnsmasq para slice $SLICE_ID"
fi

# 2. Eliminar archivos PID y lease de dnsmasq
echo ""
echo "🗂️  Eliminando archivos de configuración DHCP..."
run_sudo rm -f /var/run/dhcp/id${SLICE_ID}-dnsmasq-*.pid
run_sudo rm -f /var/lib/dhcp/id${SLICE_ID}-dnsmasq-*.leases
echo "   ✅ Archivos DHCP eliminados"

# 3. Eliminar namespaces de red
echo ""
echo "🌐 Eliminando namespaces de red..."
NAMESPACES=$(run_sudo ip netns list | grep "^id${SLICE_ID}-" | awk '{print $1}')
if [ ! -z "$NAMESPACES" ]; then
    for ns in $NAMESPACES; do
        echo "   Eliminando namespace: $ns"
        run_sudo ip netns delete "$ns"
    done
else
    echo "   ℹ️  No se encontraron namespaces para slice $SLICE_ID"
fi

# 3b. Limpiar archivos residuales de namespaces
echo "🗂️  Limpiando archivos residuales de namespaces..."
run_sudo rm -f /run/netns/id${SLICE_ID}-*
echo "   ✅ Archivos residuales de namespaces eliminados"

# 4. Eliminar puertos OVS (interfaces internas y veth)
echo ""
echo "🔌 Eliminando puertos OVS..."
OVS_PORTS=$(run_sudo ovs-vsctl list-ports br-cloud | grep "^id${SLICE_ID}-")
if [ ! -z "$OVS_PORTS" ]; then
    for port in $OVS_PORTS; do
        echo "   Eliminando puerto OVS: $port"
        run_sudo ovs-vsctl del-port br-cloud "$port"
    done
else
    echo "   ℹ️  No se encontraron puertos OVS para slice $SLICE_ID"
fi

# 5. Limpiar interfaces veth residuales (por si acaso)
echo ""
echo "🔗 Limpiando interfaces veth residuales..."
VETH_INTERFACES=$(ip link show | grep "id${SLICE_ID}-" | awk -F: '{print $2}' | awk '{print $1}')
if [ ! -z "$VETH_INTERFACES" ]; then
    for iface in $VETH_INTERFACES; do
        echo "   Eliminando interfaz: $iface"
        run_sudo ip link delete "$iface" 2>/dev/null || true
    done
else
    echo "   ℹ️  No se encontraron interfaces veth residuales"
fi

# 6. Verificación final
echo ""
echo "🔍 Verificación final..."

# Verificar namespaces
REMAINING_NS=$(run_sudo ip netns list | grep "^id${SLICE_ID}-" | wc -l)
echo "   Namespaces restantes: $REMAINING_NS"

# Verificar puertos OVS
REMAINING_PORTS=$(run_sudo ovs-vsctl list-ports br-cloud | grep "^id${SLICE_ID}-" | wc -l)
echo "   Puertos OVS restantes: $REMAINING_PORTS"

# Verificar procesos dnsmasq
REMAINING_DNSMASQ=$(ps aux | grep "dnsmasq.*id${SLICE_ID}-" | grep -v grep | wc -l)
echo "   Procesos dnsmasq restantes: $REMAINING_DNSMASQ"

echo ""
if [ "$REMAINING_NS" -eq 0 ] && [ "$REMAINING_PORTS" -eq 0 ] && [ "$REMAINING_DNSMASQ" -eq 0 ]; then
    echo "✅ Limpieza completada exitosamente para slice $SLICE_ID"
    echo "🎉 Todos los recursos han sido eliminados"
else
    echo "⚠️  Limpieza completada con advertencias:"
    [ "$REMAINING_NS" -gt 0 ] && echo "   - Quedan $REMAINING_NS namespaces"
    [ "$REMAINING_PORTS" -gt 0 ] && echo "   - Quedan $REMAINING_PORTS puertos OVS"
    [ "$REMAINING_DNSMASQ" -gt 0 ] && echo "   - Quedan $REMAINING_DNSMASQ procesos dnsmasq"
fi

echo ""
echo "📋 Resumen de limpieza para slice $SLICE_ID completado"
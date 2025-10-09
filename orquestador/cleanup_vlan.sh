#!/bin/bash

# No exit on error para cleanup - continuamos aunque algo falle
set +e

# Parametros
VLAN_ID="$1"
OVS_BRIDGE="$2"

# Validaciones
if [[ -z "$VLAN_ID" ]]; then
    echo "ERROR: VLAN_ID es requerido"
    echo "Uso: $0 VLAN_ID [OVS_BRIDGE]"
    echo "Ejemplo: $0 100 br-cloud"
    exit 1
fi

# Verificar que tenemos acceso sudo
if ! sudo -n true 2>/dev/null; then
    echo "ERROR: Este script requiere permisos sudo"
    echo "Ejecuta: sudo $0 $*"
    exit 1
fi

# Configuración basada en el patrón id${VLAN_ID}
NAMESPACE="id${VLAN_ID}-dhcp"
VETH_NS="id${VLAN_ID}-nsvt"
VETH_OVS="id${VLAN_ID}-ovsvt"
OVS_INTERNAL_IFACE="id${VLAN_ID}-gw"
DNSMASQ_PID_FILE="/var/run/dhcp/id${VLAN_ID}-dnsmasq.pid"
DNSMASQ_LEASE_FILE="/var/lib/dhcp/id${VLAN_ID}-dnsmasq.leases"

echo "========================================="
echo "   LIMPIANDO CONFIGURACION VLAN $VLAN_ID"
echo "========================================="
echo "Namespace: $NAMESPACE"
echo "Interfaces: $VETH_NS, $VETH_OVS, $OVS_INTERNAL_IFACE"
echo ""

# 1. Detener servidor DHCP
echo "=== 1. DETENIENDO SERVIDOR DHCP ==="
if [[ -f "$DNSMASQ_PID_FILE" ]]; then
    DNSMASQ_PID=$(cat "$DNSMASQ_PID_FILE")
    if sudo kill -0 "$DNSMASQ_PID" 2>/dev/null; then
        echo "Deteniendo dnsmasq (PID: $DNSMASQ_PID)..."
        sudo kill "$DNSMASQ_PID"
        sleep 2
        # Forzar kill si aún está corriendo
        if sudo kill -0 "$DNSMASQ_PID" 2>/dev/null; then
            echo "Forzando terminación de dnsmasq..."
            sudo kill -9 "$DNSMASQ_PID" 2>/dev/null || true
        fi
        echo "Servidor DHCP detenido"
    else
        echo "Proceso dnsmasq ya no está corriendo"
    fi
    sudo rm -f "$DNSMASQ_PID_FILE"
else
    echo "No se encontró archivo PID del servidor DHCP"
fi

# 2. Eliminar namespace (esto también elimina las interfaces dentro)
echo ""
echo "=== 2. ELIMINANDO NAMESPACE ==="
if sudo ip netns list | grep -q "${NAMESPACE}"; then
    echo "Eliminando namespace $NAMESPACE..."
    # Primero intentar matar cualquier proceso en el namespace
    sudo ip netns pids "$NAMESPACE" 2>/dev/null | while read pid; do
        echo "Matando proceso $pid en namespace $NAMESPACE"
        sudo kill -9 "$pid" 2>/dev/null || true
    done
    sleep 1
    # Luego eliminar el namespace
    sudo ip netns del "$NAMESPACE" 2>/dev/null || true
    # Verificar que se eliminó
    if sudo ip netns list | grep -q "${NAMESPACE}"; then
        echo "WARNING: Namespace $NAMESPACE aún existe"
    else
        echo "Namespace $NAMESPACE eliminado"
    fi
else
    echo "Namespace $NAMESPACE no existe"
fi

# 3. Eliminar puertos del bridge OVS
echo ""
echo "=== 3. ELIMINANDO PUERTOS OVS ==="

# Eliminar puertos del OVS (si existe el bridge)
if [[ -n "$OVS_BRIDGE" ]] && sudo ovs-vsctl br-exists "$OVS_BRIDGE"; then
    # Eliminar puerto veth - usar --if-exists para evitar errores
    echo "Eliminando puerto veth $VETH_OVS del bridge $OVS_BRIDGE..."
    sudo ovs-vsctl --if-exists del-port "$OVS_BRIDGE" "$VETH_OVS"
    echo "Puerto veth $VETH_OVS eliminado (si existía)"

    # Eliminar interfaz interna gateway
    echo "Eliminando interfaz gateway $OVS_INTERNAL_IFACE del bridge $OVS_BRIDGE..."
    # Primero eliminar la IP asignada si existe
    if sudo ip addr show "$OVS_INTERNAL_IFACE" 2>/dev/null | grep -q "inet "; then
        echo "Eliminando IPs de interfaz $OVS_INTERNAL_IFACE..."
        sudo ip addr flush dev "$OVS_INTERNAL_IFACE" 2>/dev/null || true
    fi
    # Luego eliminar el puerto del bridge OVS
    sudo ovs-vsctl --if-exists del-port "$OVS_BRIDGE" "$OVS_INTERNAL_IFACE"
    echo "Interfaz gateway $OVS_INTERNAL_IFACE eliminada (si existía)"
else
    echo "Bridge OVS no especificado o no existe, intentando limpiar en todos los bridges..."
    
    # Buscar en todos los bridges OVS existentes
    for bridge in $(sudo ovs-vsctl list-br 2>/dev/null || true); do
        echo "Verificando bridge $bridge..."
        
        # Limpiar puerto veth
        echo "Eliminando $VETH_OVS del bridge $bridge (si existe)..."
        sudo ovs-vsctl --if-exists del-port "$bridge" "$VETH_OVS" 2>/dev/null || true
        
        # Limpiar interfaz gateway
        echo "Eliminando interfaz gateway $OVS_INTERNAL_IFACE del bridge $bridge (si existe)..."
        # Eliminar IPs primero
        if sudo ip addr show "$OVS_INTERNAL_IFACE" 2>/dev/null | grep -q "inet "; then
            sudo ip addr flush dev "$OVS_INTERNAL_IFACE" 2>/dev/null || true
        fi
        sudo ovs-vsctl --if-exists del-port "$bridge" "$OVS_INTERNAL_IFACE" 2>/dev/null || true
    done
fi

# 4. Limpiar interfaces de red restantes
echo ""
echo "=== 4. LIMPIANDO INTERFACES RESTANTES ==="

# Eliminar veth pair si existe (normalmente se elimina con el namespace)
if sudo ip link show "$VETH_OVS" 2>/dev/null; then
    echo "Eliminando interfaz $VETH_OVS..."
    sudo ip link del "$VETH_OVS" 2>/dev/null || true
    echo "Interfaz $VETH_OVS eliminada"
else
    echo "Interfaz $VETH_OVS no existe"
fi

# Eliminar interfaz interna si existe
if sudo ip link show "$OVS_INTERNAL_IFACE" 2>/dev/null; then
    echo "Eliminando interfaz $OVS_INTERNAL_IFACE..."
    sudo ip link del "$OVS_INTERNAL_IFACE" 2>/dev/null || true
    echo "Interfaz $OVS_INTERNAL_IFACE eliminada"
else
    echo "Interfaz $OVS_INTERNAL_IFACE no existe"
fi

# 5. Eliminar archivos de configuración
echo ""
echo "=== 5. LIMPIANDO ARCHIVOS ==="

if [[ -f "$DNSMASQ_LEASE_FILE" ]]; then
    echo "Eliminando archivo de leases $DNSMASQ_LEASE_FILE..."
    sudo rm -f "$DNSMASQ_LEASE_FILE"
    echo "Archivo de leases eliminado"
else
    echo "Archivo de leases no existe"
fi

# Limpiar cualquier otro archivo relacionado
sudo rm -f "/var/run/dhcp/id${VLAN_ID}"* 2>/dev/null || true
sudo rm -f "/var/lib/dhcp/id${VLAN_ID}"* 2>/dev/null || true

echo ""
echo "========================================="
echo "   LIMPIEZA VLAN $VLAN_ID COMPLETADA"
echo "========================================="

# Verificación final detallada
echo "=== VERIFICACION FINAL ==="
echo "1. Namespaces con 'id${VLAN_ID}':"
REMAINING_NS=$(sudo ip netns list 2>/dev/null | grep "id${VLAN_ID}" || true)
if [[ -z "$REMAINING_NS" ]]; then
    echo "   ✓ Ningún namespace encontrado"
else
    echo "   ✗ QUEDAN: $REMAINING_NS"
fi

echo ""
echo "2. Interfaces con 'id${VLAN_ID}':"
REMAINING_IFACES=$(sudo ip link show 2>/dev/null | grep "id${VLAN_ID}" || true)
if [[ -z "$REMAINING_IFACES" ]]; then
    echo "   ✓ Ninguna interfaz encontrada"
else
    echo "   ✗ QUEDAN: $REMAINING_IFACES"
fi

echo ""
echo "3. Puertos OVS con VLAN $VLAN_ID:"
if [[ -n "$OVS_BRIDGE" ]] && sudo ovs-vsctl br-exists "$OVS_BRIDGE" 2>/dev/null; then
    REMAINING_PORTS=$(sudo ovs-vsctl show 2>/dev/null | grep -A 4 -B 1 "tag: $VLAN_ID" || true)
    if [[ -z "$REMAINING_PORTS" ]]; then
        echo "   ✓ Ningún puerto con VLAN $VLAN_ID encontrado"
    else
        echo "   ✗ QUEDAN:"
        echo "$REMAINING_PORTS"
    fi
else
    echo "   Bridge $OVS_BRIDGE no existe o no especificado"
fi

echo ""
echo "4. Procesos dnsmasq relacionados:"
REMAINING_PROCS=$(ps aux 2>/dev/null | grep "id${VLAN_ID}" | grep -v grep || true)
if [[ -z "$REMAINING_PROCS" ]]; then
    echo "   ✓ Ningún proceso encontrado"
else
    echo "   ✗ QUEDAN: $REMAINING_PROCS"
fi

echo ""
if [[ -z "$REMAINING_NS" && -z "$REMAINING_IFACES" && -z "$REMAINING_PORTS" && -z "$REMAINING_PROCS" ]]; then
    echo "✓ LIMPIEZA COMPLETADA EXITOSAMENTE"
else
    echo "✗ LIMPIEZA INCOMPLETA - Revisar elementos restantes arriba"
    echo ""
    echo "Comandos para limpieza manual:"
    echo "  sudo ip netns del id${VLAN_ID}-dhcp"
    echo "  sudo ovs-vsctl del-port $OVS_BRIDGE id${VLAN_ID}-ovsvt"
    echo "  sudo ovs-vsctl del-port $OVS_BRIDGE id${VLAN_ID}-gw"
    echo "  sudo killall -9 dnsmasq"
fi
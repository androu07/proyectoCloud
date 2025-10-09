#!/bin/bash

set -e  # Exit on any error

# Parametros
OVS_NAME="$1"
IFACE="ens4"

echo "=== Inicializando Headnode ==="
echo "OVS Bridge: $OVS_NAME"
echo "Interface: ens4"

# Verificar que se ejecuta como root o con sudo
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Este script debe ejecutarse como root o con sudo"
    exit 1
fi

# Crear directorio para lease file
mkdir -p /var/lib/dhcp
mkdir -p /var/run/dhcp

# Creando un ovs
echo "Creando bridge OVS: $OVS_NAME"
ovs-vsctl add-br "$OVS_NAME"

# Agregar interfaz física al bridge y activarla juntos con el ovs
ovs-vsctl add-port "$OVS_NAME" "$IFACE"
ip link set dev "$IFACE" up
ip link set dev "$OVS_NAME" up

# Verificar configuración
echo "=== Estado final del Headnode ==="
echo "Bridge OVS:"
ovs-vsctl show

echo -e "\nInterfaces del bridge:"
ovs-vsctl list-ports "$OVS_NAME"
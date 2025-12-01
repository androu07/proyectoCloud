#!/bin/bash

# Script para instalar VM Node Manager como servicio systemd
echo "=== Instalando VM Node Manager como servicio systemd ==="

# Verificar que existe el archivo Python
if [ ! -f /home/ubuntu/scripts_app/mngmt/vm_node_manager.py ]; then
    echo "Error: No se encuentra vm_node_manager.py en /home/ubuntu/scripts_app/mngmt/"
    exit 1
fi

# Verificar que el usuario está en el grupo libvirt
if ! groups ubuntu | grep -q libvirt; then
    echo "Advertencia: El usuario ubuntu no está en el grupo libvirt"
    echo "Ejecuta: sudo usermod -aG libvirt ubuntu"
fi

# Copiar servicio systemd
echo "Configurando servicio systemd..."
sudo cp /home/ubuntu/scripts_app/mngmt/vm_node_manager.service /etc/systemd/system/

# Recargar systemd
sudo systemctl daemon-reload

# Habilitar y arrancar servicio
sudo systemctl enable vm_node_manager
sudo systemctl start vm_node_manager

# Esperar un momento
sleep 2

# Verificar estado
echo ""
echo "=== Estado del servicio ==="
sudo systemctl status vm_node_manager --no-pager
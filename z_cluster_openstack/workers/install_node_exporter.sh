#!/bin/bash

# Script para instalar Node Exporter como servicio systemd
echo "=== Instalando Node Exporter como servicio systemd ==="

# Descargar Node Exporter
echo "Descargando Node Exporter..."
wget -O /tmp/node_exporter.tar.gz https://github.com/prometheus/node_exporter/releases/download/v1.6.1/node_exporter-1.6.1.linux-amd64.tar.gz

# Extraer
cd /tmp
tar xzf node_exporter.tar.gz

# Crear directorio de instalación
echo "Instalando en /opt/node_exporter..."
sudo mkdir -p /opt/node_exporter
sudo cp node_exporter-1.6.1.linux-amd64/node_exporter /opt/node_exporter/
sudo chown -R ubuntu:ubuntu /opt/node_exporter

# Copiar servicio systemd
echo "Configurando servicio systemd..."
sudo cp /home/ubuntu/scripts_app/node_exporter.service /etc/systemd/system/

# Recargar systemd
sudo systemctl daemon-reload

# Habilitar y arrancar servicio
sudo systemctl enable node_exporter
sudo systemctl start node_exporter

# Verificar estado
echo ""
echo "=== Estado del servicio ==="
sudo systemctl status node_exporter --no-pager

# Limpiar
rm -rf /tmp/node_exporter*

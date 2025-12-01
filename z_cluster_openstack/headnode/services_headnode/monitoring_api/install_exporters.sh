#!/bin/bash

# Script para instalar Node Exporter y Blackbox Exporter como servicios systemd
# Uso: sudo bash install_exporters.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Instalador de Exporters para Prometheus ==="
echo "Directorio del script: $SCRIPT_DIR"
echo ""

# Función para instalar Node Exporter
install_node_exporter() {
    echo "[1/2] Instalando Node Exporter..."
    
    # Crear directorio
    mkdir -p /opt/node_exporter
    cd /tmp
    
    # Descargar
    echo "  Descargando Node Exporter v1.6.1..."
    wget -q -O node_exporter.tar.gz https://github.com/prometheus/node_exporter/releases/download/v1.6.1/node_exporter-1.6.1.linux-amd64.tar.gz
    
    # Extraer e instalar
    tar xzf node_exporter.tar.gz
    cp node_exporter-1.6.1.linux-amd64/node_exporter /opt/node_exporter/
    chmod +x /opt/node_exporter/node_exporter
    rm -rf node_exporter-1.6.1.linux-amd64 node_exporter.tar.gz
    
    echo "  Node Exporter instalado en /opt/node_exporter/"
    
    # Instalar servicio systemd
    if [ -f "$SCRIPT_DIR/node_exporter.service" ]; then
        cp "$SCRIPT_DIR/node_exporter.service" /etc/systemd/system/
        systemctl daemon-reload
        systemctl enable node_exporter.service
        systemctl restart node_exporter.service
        echo "  Servicio node_exporter habilitado e iniciado"
    else
        echo "  ADVERTENCIA: No se encontró node_exporter.service en $SCRIPT_DIR"
    fi
    
    echo ""
}

# Función para instalar Blackbox Exporter
install_blackbox_exporter() {
    echo "[2/2] Instalando Blackbox Exporter..."
    
    # Crear directorio
    mkdir -p /opt/blackbox_exporter
    cd /tmp
    
    # Descargar
    echo "  Descargando Blackbox Exporter v0.24.0..."
    wget -q -O blackbox_exporter.tar.gz https://github.com/prometheus/blackbox_exporter/releases/download/v0.24.0/blackbox_exporter-0.24.0.linux-amd64.tar.gz
    
    # Extraer e instalar
    tar xzf blackbox_exporter.tar.gz
    cp blackbox_exporter-0.24.0.linux-amd64/blackbox_exporter /opt/blackbox_exporter/
    chmod +x /opt/blackbox_exporter/blackbox_exporter
    rm -rf blackbox_exporter-0.24.0.linux-amd64 blackbox_exporter.tar.gz
    
    # Crear configuración
    cat > /opt/blackbox_exporter/blackbox.yml <<'EOF'
modules:
  icmp:
    prober: icmp
    timeout: 5s
    icmp:
      preferred_ip_protocol: "ip4"
  http_2xx:
    prober: http
    timeout: 5s
    http:
      valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
      valid_status_codes: []
      method: GET
      preferred_ip_protocol: "ip4"
  tcp_connect:
    prober: tcp
    timeout: 5s
EOF
    
    echo "  Blackbox Exporter instalado en /opt/blackbox_exporter/"
    
    # Instalar servicio systemd
    if [ -f "$SCRIPT_DIR/blackbox_exporter.service" ]; then
        cp "$SCRIPT_DIR/blackbox_exporter.service" /etc/systemd/system/
        systemctl daemon-reload
        systemctl enable blackbox_exporter.service
        systemctl restart blackbox_exporter.service
        echo "  Servicio blackbox_exporter habilitado e iniciado"
    else
        echo "  ADVERTENCIA: No se encontró blackbox_exporter.service en $SCRIPT_DIR"
    fi
    
    echo ""
}

# Verificar permisos root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Este script debe ejecutarse como root (usa sudo)"
    exit 1
fi

# Instalar ambos exporters
install_node_exporter
install_blackbox_exporter

# Resumen
echo "=== Instalacion completada ==="
echo ""
echo "Servicios instalados:"
systemctl status node_exporter --no-pager | head -3
echo ""
systemctl status blackbox_exporter --no-pager | head -3
echo ""
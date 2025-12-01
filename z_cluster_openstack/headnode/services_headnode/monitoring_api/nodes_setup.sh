#!/bin/bash

# Script para configurar Node Exporter y Blackbox Exporter en el headnode como servicios systemd
echo "=== Configurando Monitoring en Headnode ==="

# ==================== NODE EXPORTER ====================
echo ""
echo "[1/3] Instalando Node Exporter..."

# Crear directorio permanente para Node Exporter
mkdir -p /opt/node_exporter
cd /tmp

# Descargar Node Exporter
wget -O node_exporter.tar.gz https://github.com/prometheus/node_exporter/releases/download/v1.6.1/node_exporter-1.6.1.linux-amd64.tar.gz

# Extraer e instalar
tar xzf node_exporter.tar.gz
cp node_exporter-1.6.1.linux-amd64/node_exporter /opt/node_exporter/
chmod +x /opt/node_exporter/node_exporter
rm -rf node_exporter-1.6.1.linux-amd64 node_exporter.tar.gz

echo "Node Exporter instalado en /opt/node_exporter/"

# ==================== BLACKBOX EXPORTER ====================
echo ""
echo "[2/3] Instalando Blackbox Exporter..."

# Crear directorio permanente para Blackbox Exporter
mkdir -p /opt/blackbox_exporter
cd /tmp

# Descargar Blackbox Exporter
wget -O blackbox_exporter.tar.gz https://github.com/prometheus/blackbox_exporter/releases/download/v0.24.0/blackbox_exporter-0.24.0.linux-amd64.tar.gz

# Extraer e instalar
tar xzf blackbox_exporter.tar.gz
cp blackbox_exporter-0.24.0.linux-amd64/blackbox_exporter /opt/blackbox_exporter/
chmod +x /opt/blackbox_exporter/blackbox_exporter
rm -rf blackbox_exporter-0.24.0.linux-amd64 blackbox_exporter.tar.gz

# Crear archivo de configuración
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

echo "Blackbox Exporter instalado en /opt/blackbox_exporter/"

# ==================== CONFIGURAR SERVICIOS SYSTEMD ====================
echo ""
echo "[3/3] Configurando servicios systemd..."

# Obtener ruta del directorio del script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Copiar archivos de servicio
cp "$SCRIPT_DIR/node_exporter.service" /etc/systemd/system/
cp "$SCRIPT_DIR/blackbox_exporter.service" /etc/systemd/system/

# Recargar systemd
systemctl daemon-reload

# Habilitar servicios para inicio automático
systemctl enable node_exporter.service
systemctl enable blackbox_exporter.service

# Iniciar servicios
systemctl start node_exporter.service
systemctl start blackbox_exporter.service

echo "Servicios systemd configurados y habilitados"

# ==================== RESUMEN ====================
echo ""
echo "=== Configuracion completada exitosamente ==="
echo ""
echo "Servicios en ejecucion:"
echo "  1. Node Exporter - Puerto 9100"
echo "  2. Blackbox Exporter - Puerto 9115"
echo ""
echo "Comandos utiles:"
echo "  Ver estado:"
echo "    systemctl status node_exporter"
echo "    systemctl status blackbox_exporter"
echo ""
echo "  Ver logs:"
echo "    journalctl -u node_exporter -f"
echo "    journalctl -u blackbox_exporter -f"
echo ""
echo "  Reiniciar servicios:"
echo "    systemctl restart node_exporter"
echo "    systemctl restart blackbox_exporter"
echo ""
echo "  Detener servicios:"
echo "    systemctl stop node_exporter"
echo "    systemctl stop blackbox_exporter"
echo ""
echo "  Verificar funcionamiento:"
echo "    curl http://localhost:9100/metrics"
echo "    curl 'http://localhost:9115/probe?module=icmp&target=192.168.201.2'"
echo ""

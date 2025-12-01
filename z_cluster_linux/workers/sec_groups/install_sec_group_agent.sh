#!/bin/bash

# Security Group Agent - Installation Script
# Este script instala el Security Group Agent como un servicio systemd

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="security-group-agent"
SERVICE_FILE="${SERVICE_NAME}.service"
INSTALL_DIR="/home/ubuntu/scripts_app/sec_groups"
LOG_FILE="/var/log/security_group_agent.log"

echo "========================================="
echo "Security Group Agent - Instalador"
echo "========================================="
echo ""

# Verificar que se ejecuta como root
if [ "$EUID" -ne 0 ]; then 
    echo "ERROR: Este script debe ejecutarse como root (sudo)"
    exit 1
fi

echo "Ejecutando como root"
echo ""

# Verificar que existen los archivos necesarios
if [ ! -f "${SCRIPT_DIR}/security_group_agent.py" ]; then
    echo "ERROR: No se encuentra security_group_agent.py en ${SCRIPT_DIR}"
    exit 1
fi

if [ ! -f "${SCRIPT_DIR}/${SERVICE_FILE}" ]; then
    echo "ERROR: No se encuentra ${SERVICE_FILE} en ${SCRIPT_DIR}"
    exit 1
fi

echo "Archivos necesarios encontrados"
echo ""

# Instalar dependencias de Python
echo "Instalando dependencias de Python..."
if [ -f "${SCRIPT_DIR}/requirements.txt" ]; then
    pip3 install -r "${SCRIPT_DIR}/requirements.txt" > /dev/null 2>&1
    echo "Dependencias instaladas"
else
    echo "Warning: No se encontró requirements.txt"
fi
echo ""

# Crear directorio de logs si no existe
echo "Configurando logs..."
touch "${LOG_FILE}"
chmod 644 "${LOG_FILE}"
echo "Log file creado: ${LOG_FILE}"
echo ""

# Detener servicio si ya existe
echo "Deteniendo servicios existentes..."
if systemctl is-active --quiet ${SERVICE_NAME}; then
    systemctl stop ${SERVICE_NAME}
    echo "Servicio ${SERVICE_NAME} detenido"
else
    echo "No hay servicios previos ejecutándose"
fi
echo ""

# Matar procesos antiguos del agente
echo "Limpiando procesos antiguos..."
pkill -f security_group_agent.py 2>/dev/null || true
sleep 2
echo "Procesos antiguos eliminados"
echo ""

# Copiar archivo de servicio a systemd
echo "Instalando servicio systemd..."
cp "${SCRIPT_DIR}/${SERVICE_FILE}" /etc/systemd/system/
chmod 644 "/etc/systemd/system/${SERVICE_FILE}"
echo "Archivo de servicio copiado a /etc/systemd/system/"
echo ""

# Recargar systemd
echo "Recargando systemd..."
systemctl daemon-reload
echo "Systemd recargado"
echo ""

# Habilitar servicio para inicio automático
echo "Habilitando inicio automático..."
systemctl enable ${SERVICE_NAME}
echo "Servicio habilitado para inicio automático"
echo ""

# Iniciar servicio
echo "Iniciando servicio..."
systemctl start ${SERVICE_NAME}
sleep 3
echo ""

# Verificar estado
echo "Verificando estado del servicio..."
if systemctl is-active --quiet ${SERVICE_NAME}; then
    echo "Servicio ${SERVICE_NAME} está ACTIVO"
    echo ""
    systemctl status ${SERVICE_NAME} --no-pager -l
    echo ""
    
    # Probar endpoint de health
    echo "Probando endpoint de salud..."
    sleep 2
    if curl -s http://localhost:5810/health > /dev/null 2>&1; then
        echo "Endpoint de salud respondiendo correctamente"
        curl -s http://localhost:5810/health | python3 -m json.tool 2>/dev/null || curl -s http://localhost:5810/health
    else
        echo "Warning: El endpoint de salud no responde (puede tardar unos segundos en iniciar)"
    fi
else
    echo "ERROR: El servicio no pudo iniciarse"
    echo ""
    echo "Logs del servicio:"
    journalctl -u ${SERVICE_NAME} -n 50 --no-pager
    exit 1
fi
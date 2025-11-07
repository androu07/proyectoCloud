#!/bin/bash

# Script simple para ejecutar Node Exporter en workers
echo "=== Iniciando Node Exporter en Worker ==="

# Descargar y ejecutar directamente
wget -O /tmp/node_exporter.tar.gz https://github.com/prometheus/node_exporter/releases/download/v1.6.1/node_exporter-1.6.1.linux-amd64.tar.gz
cd /tmp
tar xzf node_exporter.tar.gz
cd node_exporter-1.6.1.linux-amd64

# Ejecutar Node Exporter en segundo plano
echo "Iniciando Node Exporter en segundo plano..."
nohup ./node_exporter > node_exporter.log 2>&1 &

# Obtener el PID del proceso
NODE_PID=$!
echo "Node Exporter iniciado con PID: $NODE_PID"
echo "Puerto: 9100"
echo "Log: /tmp/node_exporter-1.6.1.linux-amd64/node_exporter.log"
echo ""
echo "Comandos útiles:"
echo "  Ver proceso: ps aux | grep node_exporter"
echo "  Ver logs: tail -f /tmp/node_exporter-1.6.1.linux-amd64/node_exporter.log"
echo "  Detener: kill $NODE_PID"
echo "  Verificar: curl http://localhost:9100/metrics"

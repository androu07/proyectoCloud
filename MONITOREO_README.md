# 📊 Servicio de Monitoreo con Prometheus y Grafana

## 🏗️ Arquitectura del Monitoreo

```
Head Node (Docker Compose)
├── Prometheus (Puerto 9090)
├── Grafana (Puerto 3000)
├── Node Exporter (Puerto 9100)
└── cAdvisor (Puerto 8081)

Workers 1, 2, 3
└── Node Exporter (Puerto 9100)
```

## 🚀 Pasos de Instalación

### 1. En el Head Node (tu máquina actual)

```bash
# Levantar todos los servicios
cd /home/ubuntu/red_contenedores
docker compose up -d
```

### 2. En cada Worker Node

```bash
# Copiar y ejecutar el script en cada worker
chmod +x install_node_exporter_workers.sh
sudo ./install_node_exporter_workers.sh
```

### 3. Configurar IPs de Workers

Edita el archivo `prometheus/prometheus.yml` y reemplaza:
- `WORKER1_IP` con la IP real del Worker 1
- `WORKER2_IP` con la IP real del Worker 2  
- `WORKER3_IP` con la IP real del Worker 3

Luego reinicia Prometheus:
```bash
docker compose restart prometheus
```

## 🌐 Acceso a los Servicios

### A través del API Gateway (Traefik)
- **Grafana**: http://tu-ip/grafana
  - Usuario: `admin`
  - Contraseña: `admin123`
- **Prometheus**: http://tu-ip/prometheus

### Acceso directo
- **Grafana**: http://tu-ip:3000
- **Prometheus**: http://tu-ip:9090
- **Node Exporter**: http://tu-ip:9100
- **cAdvisor**: http://tu-ip:8081

## 📈 Dashboard incluido

Se incluye un dashboard básico con:
- ✅ CPU usage por nodo
- ✅ Memoria usage por nodo
- ✅ Uso de disco por nodo
- ✅ CPU usage de contenedores
- ✅ Memoria usage de contenedores

## 🔧 Comandos útiles

```bash
# Ver logs de servicios de monitoreo
docker compose logs prometheus
docker compose logs grafana

# Reiniciar servicios
docker compose restart prometheus grafana

# Verificar métricas
curl http://localhost:9090/api/v1/targets

# Ver métricas del node exporter
curl http://localhost:9100/metrics
```

## 📊 Métricas Disponibles

### Sistema (Node Exporter)
- CPU usage, load average
- Memoria total, usada, disponible
- Disco usage, I/O
- Red: bytes in/out, packets

### Contenedores (cAdvisor)  
- CPU usage por contenedor
- Memoria usage por contenedor
- Red por contenedor
- Filesystem usage

### Prometheus
- Métricas propias de Prometheus
- Estado de targets
- Tiempo de scraping

## 🚨 Troubleshooting

### Si Prometheus no puede acceder a los workers:
1. Verificar conectividad de red
2. Verificar que Node Exporter esté corriendo en workers
3. Verificar firewall (puerto 9100)

### Si Grafana no muestra datos:
1. Verificar que Prometheus esté funcionando
2. Verificar datasource configuration
3. Verificar queries en el dashboard

## 🔒 Seguridad

- Cambiar password default de Grafana
- Configurar autenticación en Prometheus si es necesario
- Usar firewall para limitar acceso a puertos de monitoreo
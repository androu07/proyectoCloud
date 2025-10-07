# Red de Contenedores - Infraestructura Cloud# Red de Contenedores - Infraestructura de Autenticación



## Túnel SSH para Acceso a Servicios API## Descripción

Para acceder a los servicios enrutados por Traefik desde tu computadora:

El token contiene:

**id**: ID del usuario

ssh -L 8080:localhost:80 -L 8443:localhost:443 ubuntu@10.20.12.97 -p 5801- **nombre_completo**: Nombre + apellidos

- **correo**: Email del usuario

- **rol**: Rol del usuario (admin/cliente/usuario_avanzado)

---- **exp**: Fecha de expiración (1 hora)

- **iat**: Fecha de creación

## **api_gateway_service** - Traefik (Enrutador Principal)

**Descripción**: Proxy reverso que enruta todas las peticiones HTTPS a los servicios internos## Acceso Remoto desde tu Computadora

**Ruta API**: `https://localhost:8443:8080` (Dashboard)

**Ejemplo de uso**:### Túnel SSH para pruebas

Para probar las APIs desde tu computadora local:

# Ver dashboard de Traefik desde navegador

https://localhost:8443:8080# Crear túnel SSH para el puerto 80  en donde corre el API Gateway

ssh -NL 8080:localhost:80 ubuntu@10.20.12.97 -p 5801



---# Crear túnel SSH para el Dashboard de Traefik (opcional)

ssh -NL 8081:localhost:8080 ubuntu@10.20.12.97 -p 5801

## **prometheus_service** - Recolección de Métricas

**Descripción**: Sistema de monitoreo que recolecta métricas de la infraestructura### Una vez establecido el túnel, puedes usar:

**Ruta API**: `https://localhost:8443/prometheus`

**Ejemplo de uso**:# Login desde tu computadora

curl -X POST "http://localhost:8080/auth/login" \

# Consultar métricas de CPU     -H "Content-Type: application/json" \

curl -k "https://localhost:8443/prometheus/api/v1/query?query=node_cpu_seconds_total"     -d '{

       "correo": "rodrigolujanf28@gmail.com",

# Ver interfaz web desde navegador       "password": "andres123"

https://localhost:8443/prometheus     }'


# Verificar token desde tu computadora

---curl -X POST "http://localhost:8080/auth/verify-token" \

     -H "Authorization: Bearer YOUR_JWT_TOKEN_HERE"

## **grafana_service** - Visualización de Dashboards

**Descripción**: Plataforma de visualización de métricas y dashboards# Dashboard Traefik desde tu navegador

**Ruta API**: `https://localhost:8443/grafana`# http://localhost:8081

**Credenciales**: admin / admin123

**Ejemplo de uso**:# Red de Contenedores - Infraestructura Cloud


# Acceder desde navegador## Túnel SSH para Acceso Remoto

https://localhost:8443/grafana Para acceder a los servicios desde tu computadora:


# API para crear dashboard

curl -k -X POST "https://localhost:8443/grafana/api/dashboards/db" \# Túnel para HTTP y HTTPS

     -H "Content-Type: application/json" \ssh -L 8080:localhost:80 -L 8443:localhost:443 ubuntu@10.20.12.97 -p 5801

     -u admin:admin123 \

     -d '{"dashboard": {"title": "Mi Dashboard"}}'

## Servicios Disponibles



---### Contenedores Enrutados por Traefik



## **auth_service** - API de Autenticación JWT *(Comentado)*| Contenedor | Descripción | Ruta API (HTTPS) | Estado |

**Descripción**: API REST para autenticación de usuarios y generación de tokens JWT|------------|-------------|------------------|---------|

**Ruta API**: `https://localhost:8443/auth`| **api_gateway_service** | Traefik - Enrutador principal | `https://localhost:8443:8080` (Dashboard) | ✅ Activo |

**Ejemplo de uso**:
| **prometheus_service** | Recolección de métricas | `https://localhost:8443/prometheus` | ✅ Activo |

| **grafana_service** | Visualización de dashboards | `https://localhost:8443/grafana` | ✅ Activo |

# Login para obtener token JWT| **auth_service** | API de Autenticación JWT | `https://localhost:8443/auth` | ❌ Comentado (HTTPS listo) |

curl -k -X POST "https://localhost:8443/auth/login" \| **usuarios_de_red_db** | Base de datos MySQL | - (Solo interno) | ❌ Comentado |

     -H "Content-Type: application/json" \

     -d '{### Credenciales de Acceso

       "correo": "rodrigolujanf28@gmail.com",- **Grafana**: admin / admin123

       "password": "andres123"

     }'## Arquitectura de Red



# Verificar token### Red Única: `red_cloud`

curl -k -X POST "https://localhost:8443/auth/verify-token" \- **api_gateway** (Traefik): Puerto 80 - ÚNICO punto de entrada

     -H "Authorization: Bearer YOUR_JWT_TOKEN"- **auth_api**: Solo accesible internamente a través del API Gateway

- **mysql_db**: Solo accesible internamente

# Health check

curl -k "https://localhost:8443/auth/health"### Enrutamiento con Traefik

- `http://localhost/auth/*` → `auth_api` (interno)

- `http://localhost:8080` → Dashboard Traefik (desarrollo)

**Usuarios disponibles**:

- Admin: rodrigolujanf28@gmail.com / andres123**Seguridad**: No se puede acceder directamente a las APIs, todo pasa por el API Gateway.

- Cliente: maria.garcia@email.com / maria456  

- Avanzado: carlos.rodriguez@empresa.com / carlos789## Comandos Docker



---

# Levantar servicios

## **usuarios_de_red_db** - Base de Datos MySQL *(Comentado)*sudo docker compose up -d

**Descripción**: Base de datos MySQL con tabla de usuarios para autenticación

**Ruta API**: Solo acceso interno (no expuesto)# Ver logs

**Ejemplo de uso**: Usado internamente por auth_servicesudo docker compose logs -f [nombre_servicio]



---# Parar servicios  

sudo docker compose down

## Comandos Docker

# Levantar servicios## Configuración de Grafana

sudo docker compose up -d

### Data Source Prometheus

# Ver logs- **URL**: `http://prometheus:9090/prometheus`

sudo docker compose logs -f [nombre_servicio]- **Access**: Server (default)



# Parar servicios## API de Autenticación (cuando esté activa)

sudo docker compose down

### Endpoints HTTPS disponibles:
- **Login**: `POST https://localhost:8443/auth/login`
- **Verify Token**: `POST https://localhost:8443/auth/verify-token`
- **Health Check**: `GET https://localhost:8443/auth/health`

### Usuarios de Base de Datos:
| Usuario | Email | Password | Rol |
|---------|-------|----------|-----|
| Admin | rodrigolujanf28@gmail.com | andres123 | admin |
| Cliente | maria.garcia@email.com | maria456 | cliente |
| Avanzado | carlos.rodriguez@empresa.com | carlos789 | usuario_avanzado |

### Ejemplo de uso con HTTPS:
# Login con HTTPS
curl -X POST "https://localhost:8443/auth/login" \
     -H "Content-Type: application/json" \
     -d '{
       "correo": "rodrigolujanf28@gmail.com",
       "password": "andres123"
     }'


## Comandos para Usar

### Levantar toda la infraestructura
cd /home/ubuntu/red_contenedores
docker-compose up -d

### Ver logs de un servicio específico
docker-compose logs -f auth_api
docker-compose logs -f mysql_db

### Detener todos los servicios
docker-compose down

### Reconstruir un servicio
docker-compose build auth_api
docker-compose up -d auth_api

## API Endpoints

### API de Autenticación (A través del API Gateway)

#### Health Check
GET http://localhost/auth/health


#### Login
POST http://localhost/auth/login
Content-Type: application/json

{
    "correo": "rodrigolujanf28@gmail.com",
    "password": "andres123"
}


#### Verificar Token
POST http://localhost/auth/verify-token
Authorization: Bearer <tu_token_jwt>

## Ejemplo de Uso con curl

### Login
curl -X POST "http://localhost/auth/login" \
     -H "Content-Type: application/json" \
     -d '{
       "correo": "rodrigolujanf28@gmail.com",
       "password": "andres123"
     }'

### Verificar Token
curl -X POST "http://localhost/auth/verify-token" \
     -H "Authorization: Bearer YOUR_JWT_TOKEN_HERE"

## Estructura del Token JWT

El token contiene:
- **id**: ID del usuario
- **nombre_completo**: Nombre + apellidos
- **correo**: Email del usuario
- **rol**: Rol del usuario (admin/cliente/usuario_avanzado)
- **exp**: Fecha de expiración (1 hora)
- **iat**: Fecha de creación

## Concurrencia y Rendimiento

### FastAPI + Uvicorn
La API está optimizada para manejar múltiples solicitudes concurrentes:

- **Pool de conexiones MySQL**: 10 conexiones simultáneas
- **ThreadPoolExecutor**: 20 workers para operaciones bloqueantes
- **Endpoints asíncronos**: Usan `async/await` para no bloquear el event loop
- **Uvicorn ASGI server**: Maneja requests concurrentemente

### Usuarios Disponibles
- **Admin**: rodrigolujanf28@gmail.com / andres123
- **Cliente**: maria.garcia@email.com / maria456  
- **Usuario Avanzado**: carlos.rodriguez@empresa.com / carlos789

## Base de Datos

### Tabla usuarios
```sql
CREATE TABLE usuarios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    apellidos VARCHAR(100) NOT NULL,
    correo VARCHAR(150) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    rol VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

---

# 📊 Sistema de Logging y Monitoreo

## Arquitectura de Logging

### Componentes del Sistema
- **Traefik**: Genera logs de acceso en formato JSON
- **Loki**: Almacena y indexa los logs de forma eficiente
- **Promtail**: Recolecta y procesa logs de Traefik y contenedores
- **Grafana**: Visualiza logs con dashboards y consultas

## 🔍 Información de Auditoría y Trazabilidad

### Datos que Proporcionan los Logs
- **¿Quién?** → IP del cliente + User Agent
- **¿Cuándo?** → Timestamp exacto de cada request
- **¿Qué hizo?** → Endpoint accedido (`/auth/login`, `/auth/verify`)
- **¿Cómo terminó?** → Status code (éxito/fallo)
- **¿Cuánto tardó?** → Duración del request

### Métricas de Tráfico Disponibles
- **Requests por segundo/minuto/hora**
- **Volumen total de requests por día**
- **Picos de tráfico y patrones de uso**
- **APIs más utilizadas**
- **Servicios backend más accedidos**

### Análisis de Códigos de Estado
- **Distribución de status codes** (200, 404, 500, etc.)
- **Tasa de errores por servicio**
- **Errores 4xx vs 5xx**
- **Porcentaje de requests exitosos**

### Información de Clientes
- **Top IPs más activas**
- **User Agents más comunes**
- **Detección de bots/crawlers**
- **Patrones de uso por ubicación**

## 🚨 Detección de Actividades Sospechosas

### Casos de Uso Forenses
- **Brute force attacks** → Múltiples `/auth/login` fallidos desde la misma IP
- **Acceso no autorizado** → Requests sin token JWT válido
- **Escalación de privilegios** → Usuario intentando acceder APIs restringidas
- **Ataques de enumeración** → Muchos 404s seguidos (buscando endpoints)
- **Rate limiting abuse** → Demasiados requests por minuto

### Ejemplo de Log de Traefik
```json
{
  "time": "2025-10-07T14:30:45Z",
  "ClientAddr": "192.168.1.100:54321",
  "RequestMethod": "POST",
  "RequestPath": "/auth/login",
  "DownstreamStatus": 401,
  "Duration": 250000000,
  "request_User-Agent": "Mozilla/5.0...",
  "ServiceName": "auth-api"
}
```

## 🔍 Consultas de Investigación en Loki

### Consultas Básicas de Seguridad
```logql
# Usuario específico por IP
{job="traefik-access"} |= "192.168.1.100"

# Fallos de login (intentos de brute force)
{job="traefik-access"} | json | status="401" | path="/auth/login"

# Actividad sospechosa (muchos errores 4xx)
{job="traefik-access"} | json | status=~"4.." | count > 10

# Timeline de actividad de un usuario
{job="traefik-access"} |= "IP_SOSPECHOSA" | json | line_format "{{.time}} {{.method}} {{.path}} {{.status}}"

# Errores de servidor (5xx)
{job="traefik-access"} | json | status=~"5.."

# Requests más lentos
{job="traefik-access"} | json | Duration > 1000000000
```

### Consultas de Análisis de Tráfico
```logql
# Top endpoints más utilizados
topk(10, sum by (path) (count_over_time({job="traefik-access"} | json [1h])))

# Métodos HTTP más comunes
sum by (method) (count_over_time({job="traefik-access"} | json [1h]))

# IPs más activas
topk(10, sum by (client_ip) (count_over_time({job="traefik-access"} | json [1h])))
```

## ⚡ Alertas Automáticas Recomendadas

### Alertas de Seguridad
- **Brute Force**: Más de 5 fallos de login en 1 minuto desde misma IP
- **Acceso no autorizado**: Múltiples 401/403 en corto tiempo
- **Reconocimiento**: IP nueva con muchos 404s consecutivos
- **DDoS**: Más de 1000 requests por minuto desde misma IP

### Alertas de Sistema
- **Error de servidor**: Status 500 en APIs críticas
- **Alta latencia**: Response time > 5 segundos
- **Tasa de error**: > 5% de requests con errores
- **Caída de servicio**: Sin requests en 5 minutos

## 📊 Acceso a Logs en Grafana

### URLs de Acceso
- **Grafana**: `https://localhost:8443/grafana/`
- **Explore Logs**: Menu → Explore → Seleccionar Loki datasource
- **Dashboard**: "Traefik - Logs y Accesos" (creado automáticamente)

### Credenciales
- **Usuario**: admin
- **Contraseña**: admin123

## 🛠️ Configuración de Datasources

### Loki Datasource
- **URL**: `http://loki:3100`
- **Access**: Server (proxy)
- **Max Lines**: 1000

### Prometheus Datasource  
- **URL**: `http://prometheus:9090`
- **Access**: Server (proxy)

## 📋 Casos de Uso Investigativos

### Investigación de Incidentes
1. **"¿Quién intentó hackear el sistema?"**
   - Filtrar por múltiples 401/403 consecutivos
   - Revisar IPs con patrones anómalos

2. **"¿Qué hizo el usuario X ayer?"**
   - Buscar por IP específica + rango de tiempo
   - Analizar secuencia de requests

3. **"¿Cuándo empezó el ataque?"** 
   - Buscar primer error anómalo en timeline
   - Correlacionar con métricas de sistema

4. **"¿Qué endpoints están siendo atacados?"**
   - Agrupar errores por path
   - Identificar patrones de reconocimiento

### Performance y Monitoreo
- **Latencia por endpoint**: Identificar APIs lentas
- **Patrones de uso**: Horarios pico y valles
- **SLA real**: Disponibilidad y tiempo de respuesta
- **Capacidad**: Proyección de crecimiento
# Red de Contenedores - Infraestructura de Autenticación

## Descripción

El token contiene:
- **id**: ID del usuario
- **nombre_completo**: Nombre + apellidos
- **correo**: Email del usuario
- **rol**: Rol del usuario (admin/cliente/usuario_avanzado)
- **exp**: Fecha de expiración (1 hora)
- **iat**: Fecha de creación

## Acceso Remoto desde tu Computadora

### Túnel SSH para pruebas
Para probar las APIs desde tu computadora local:

# Crear túnel SSH para el puerto 80  en donde corre el API Gateway
ssh -L 8080:localhost:80 ubuntu@10.20.12.97 -p 5801

# Crear túnel SSH para el Dashboard de Traefik (opcional)
ssh -L 8081:localhost:8080 ubuntu@10.20.12.97 -p 5801

### Una vez establecido el túnel, puedes usar:

# Login desde tu computadora
curl -X POST "http://localhost:8080/auth/login" \
     -H "Content-Type: application/json" \
     -d '{
       "correo": "rodrigolujanf28@gmail.com",
       "password": "andres123"
     }'

# Verificar token desde tu computadora
curl -X POST "http://localhost:8080/auth/verify-token" \
     -H "Authorization: Bearer YOUR_JWT_TOKEN_HERE"

# Dashboard Traefik desde tu navegador
# http://localhost:8081

## contenedores con arquitectura de microservicios que incluye:

- **Base de datos MySQL**: Contiene la tabla de usuarios
- **API de Autenticación**: Servicio FastAPI para login y manejo de tokens JWT
- **API Gateway**: Enrutador de tráfico entre redes

## Arquitectura de Red

### Red Única: `red_cloud`
- **api_gateway** (Traefik): Puerto 80 - ÚNICO punto de entrada
- **auth_api**: Solo accesible internamente a través del API Gateway
- **mysql_db**: Solo accesible internamente

### Enrutamiento con Traefik
- `http://localhost/auth/*` → `auth_api` (interno)
- `http://localhost:8080` → Dashboard Traefik (desarrollo)

**Seguridad**: No se puede acceder directamente a las APIs, todo pasa por el API Gateway.

## Usuarios de Prueba

### Usuario Admin
- **Email**: rodrigolujanf28@gmail.com
- **Password**: andres123
- **Rol**: admin

### Usuario Cliente
- **Email**: maria.garcia@email.com  
- **Password**: maria456
- **Rol**: cliente

### Usuario Avanzado
- **Email**: carlos.rodriguez@empresa.com
- **Password**: carlos789
- **Rol**: usuario_avanzado

## Comandos para Usar

### Levantar toda la infraestructura
```bash
cd /home/ubuntu/red_contenedores
docker-compose up -d
```

### Ver logs de un servicio específico
```bash
docker-compose logs -f auth_api
docker-compose logs -f mysql_db
```

### Detener todos los servicios
```bash
docker-compose down
```

### Reconstruir un servicio
```bash
docker-compose build auth_api
docker-compose up -d auth_api
```

## API Endpoints

### API de Autenticación (A través del API Gateway)

#### Health Check
```bash
GET http://localhost/auth/health
```

#### Login
```bash
POST http://localhost/auth/login
Content-Type: application/json

{
    "correo": "rodrigolujanf28@gmail.com",
    "password": "andres123"
}
```

#### Verificar Token
```bash
POST http://localhost/auth/verify-token
Authorization: Bearer <tu_token_jwt>
```

## Ejemplo de Uso con curl

### Login
```bash
curl -X POST "http://localhost/auth/login" \
     -H "Content-Type: application/json" \
     -d '{
       "correo": "rodrigolujanf28@gmail.com",
       "password": "andres123"
     }'
```

### Verificar Token
```bash
curl -X POST "http://localhost/auth/verify-token" \
     -H "Authorization: Bearer YOUR_JWT_TOKEN_HERE"
```

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
-- Crear base de datos para slices si no existe
CREATE DATABASE IF NOT EXISTS slices_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Crear usuario de aplicación y otorgar permisos
CREATE USER IF NOT EXISTS 'slices_user'@'%' IDENTIFIED BY 'slices_pass123';
GRANT ALL PRIVILEGES ON slices_db.* TO 'slices_user'@'%';
FLUSH PRIVILEGES;

-- Usar la base de datos
USE slices_db;

-- Crear tabla slices con la nueva estructura solicitada
CREATE TABLE IF NOT EXISTS slices (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usuario INT NOT NULL,
    nombre_slice VARCHAR(200),
    tipo VARCHAR(50),
    estado VARCHAR(50),
    network VARCHAR(15),
    peticion_json JSON,
    vlans VARCHAR(200),
    vms JSON,
    timestamp_creacion VARCHAR(50),
    timestamp_despliegue VARCHAR(50)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
-- Crear base de datos para slices si no existe
CREATE DATABASE IF NOT EXISTS slices_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Usar la base de datos
USE slices_db;

-- Crear tabla slices con la estructura solicitada
CREATE TABLE IF NOT EXISTS slices (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usuario VARCHAR(100) NOT NULL,
    nombre_slice VARCHAR(200) NOT NULL,
    descripcion TEXT,
    vms JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
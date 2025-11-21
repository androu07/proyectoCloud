-- Crear la base de datos si no existe
CREATE DATABASE IF NOT EXISTS usuarios_db;

-- Crear usuario de aplicación y otorgar permisos
CREATE USER IF NOT EXISTS 'app_user'@'%' IDENTIFIED BY 'app_password123';
GRANT ALL PRIVILEGES ON usuarios_db.* TO 'app_user'@'%';
FLUSH PRIVILEGES;

-- Usar la base de datos
USE usuarios_db;

-- Crear la tabla usuarios
CREATE TABLE IF NOT EXISTS usuarios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    apellidos VARCHAR(100) NOT NULL,
    correo VARCHAR(150) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    rol VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Insertar usuarios de ejemplo
-- Usuario admin: Andres Lujan
-- Password hasheado para 'andres123' usando bcrypt
INSERT INTO usuarios (nombre, apellidos, correo, password, rol) VALUES 
('Andres', 'Lujan', 'rodrigolujanf28@gmail.com', '$2b$12$2vizEle521r9iJMgseHT6eXOrEYEMxpLHWAMFlZTOR3tiTEpjgv/S', 'admin');

-- Usuario cliente: Maria Garcia
-- Password hasheado para 'maria456' usando bcrypt
INSERT INTO usuarios (nombre, apellidos, correo, password, rol) VALUES 
('Maria', 'Garcia', 'maria.garcia@email.com', '$2b$12$oT5pjKLyZvlKax3/oA4GN.PJitxNu/47lxZ2FAn5zK0CnQ6PxuDLu', 'cliente');
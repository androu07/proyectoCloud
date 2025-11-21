-- Crear la base de datos si no existe
CREATE DATABASE IF NOT EXISTS imagenes_db;

-- Crear usuario de aplicación y otorgar permisos
CREATE USER IF NOT EXISTS 'images_user'@'%' IDENTIFIED BY 'images_pass123';
GRANT ALL PRIVILEGES ON imagenes_db.* TO 'images_user'@'%';
FLUSH PRIVILEGES;

-- Usar la base de datos
USE imagenes_db;

-- Crear tabla de imágenes (solo metadatos, sin archivo)
CREATE TABLE IF NOT EXISTS imagenes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(30) NOT NULL,
    descripcion VARCHAR(100),
    nombre_imagen VARCHAR(50) NOT NULL UNIQUE,
    formato VARCHAR(20) NOT NULL,
    tamano_gb DECIMAL(10, 2) NOT NULL,
    tipo_importacion ENUM('url', 'archivo') NOT NULL,
    fecha_importacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    id_openstack VARCHAR(100)
);


-- Tabla de Security Groups
CREATE TABLE IF NOT EXISTS security_groups (
    id INT AUTO_INCREMENT PRIMARY KEY,
    slice_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    rules JSON,
    is_default BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'TRUE solo para el SG default creado en el despliegue del slice',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_sg_per_slice (slice_id, name),
    INDEX idx_slice (slice_id),
    INDEX idx_default (slice_id, is_default)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Insertar Security Group por defecto como ejemplo
INSERT INTO security_groups (slice_id, name, description, rules, is_default) VALUES 
(
    0,  -- slice_id 0 = template para copiar cuando se creen nuevos slices
    'default',
    'Security group por defecto',
    '[
        {
            "id": 1,
            "direction": "egress",
            "ether_type": "IPv4",
            "protocol": "any",
            "port_range": "any",
            "remote_ip_prefix": "0.0.0.0/0",
            "remote_security_group": null,
            "description": "Permitir todo tráfico saliente IPv4"
        },
        {
            "id": 2,
            "direction": "egress",
            "ether_type": "IPv6",
            "protocol": "any",
            "port_range": "any",
            "remote_ip_prefix": "::/0",
            "remote_security_group": null,
            "description": "Permitir todo tráfico saliente IPv6"
        },
        {
            "id": 3,
            "direction": "ingress",
            "ether_type": "IPv4",
            "protocol": "any",
            "port_range": "any",
            "remote_ip_prefix": null,
            "remote_security_group": "default",
            "description": "Permitir desde mismo grupo IPv4"
        },
        {
            "id": 4,
            "direction": "ingress",
            "ether_type": "IPv6",
            "protocol": "any",
            "port_range": "any",
            "remote_ip_prefix": null,
            "remote_security_group": "default",
            "description": "Permitir desde mismo grupo IPv6"
        }
    ]',
    TRUE  -- Este es el template default
)
ON DUPLICATE KEY UPDATE 
    description = VALUES(description),
    rules = VALUES(rules),
    is_default = VALUES(is_default);

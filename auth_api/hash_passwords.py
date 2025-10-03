#!/usr/bin/env python3
"""
Script para generar contraseñas hasheadas con bcrypt
"""

import bcrypt

def hash_password(password: str) -> str:
    """Hashear una contraseña usando bcrypt"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """Verificar una contraseña hasheada"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

if __name__ == "__main__":
    # Generar hashes para las contraseñas
    admin_password = "andres123"
    client_password = "maria456"
    
    admin_hash = hash_password(admin_password)
    client_hash = hash_password(client_password)
    
    print("=== CONTRASEÑAS HASHEADAS ===")
    print(f"Admin (andres123): {admin_hash}")
    print(f"Cliente (maria456): {client_hash}")
    
    print("\n=== VERIFICACIÓN ===")
    print(f"Admin verificación: {verify_password(admin_password, admin_hash)}")
    print(f"Cliente verificación: {verify_password(client_password, client_hash)}")
    
    # Las contraseñas usadas en el init.sql
    sql_admin_hash = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"
    sql_client_hash = "$2b$12$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi"
    
    print(f"\nSQL Admin hash verificación: {verify_password(admin_password, sql_admin_hash)}")
    print(f"SQL Cliente hash verificación: {verify_password(client_password, sql_client_hash)}")
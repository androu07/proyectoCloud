"""
Gestor de Autenticación
Versión extendida para soportar autenticación externa vía API
"""

from .slice_manager.models import User, UserRole
import hashlib
from typing import Optional, Dict


class AuthManager:
    """
    Gestor de autenticación que soporta:
    - Autenticación local (hardcoded) para desarrollo
    - Autenticación externa vía API
    """
    
    def __init__(self):
        # Usuarios hardcodeados para fallback (si la API no está disponible)
        self.users = {
            "admin": User("admin", self._hash_password("admin"), UserRole.ADMIN),
            "cliente": User("cliente", self._hash_password("cliente"), UserRole.CLIENTE),
            "avanzado": User("avanzado", self._hash_password("avanzado"), UserRole.USUARIO_AVANZADO)
        }
    
        self.current_user = None
        self.api_token = None  # Token de la API externa
        self.api_user_data = None  # Datos adicionales de la API
        self._init_permissions()
    
    def _hash_password(self, password: str) -> str:
        """Hash simple para contraseñas"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def _init_permissions(self):
        """Definir permisos según roles"""
        self.permissions = {
            UserRole.ADMIN: [
                "access_all_system",
                "manage_global_resources",
                "monitor_all",
                "access_all_logs",
                "manage_global_security",
                "provision_area_clusters",
                "access_ui",
                "manage_slices",
                "manage_topologies",
                "access_apis",
                "deploy_all_clusters",
                "configure_firewall",
                "access_area_resources",
                "access_test_plans_role",
                "view_all_slices",
                "delete_any_slice",
                "edit_any_slice",
                "create_slice"
            ],
            UserRole.CLIENTE: [
                "access_ui",
                "manage_slices",
                "access_apis",
                "deploy_all_clusters",
                "access_assigned_resources",
                "view_own_logs",
                "create_slice",
                "view_own_slices",
                "edit_own_slice",
                "delete_own_slice"
            ],
            UserRole.USUARIO_AVANZADO: [
            "access_all_system",
            "manage_global_resources",
            "monitor_all",
            "access_ui",
            "manage_slices",
            "manage_topologies",
            "access_apis",
            "deploy_all_clusters",
            "access_area_resources",
            "view_all_slices",
            "create_slice",
            "edit_own_slice",
            "delete_own_slice"
            ]
        }
    
    def login(self, username: str, password: str) -> bool:
        """
        Autenticación local (hardcoded)
        Usado como fallback si la API no está disponible
        
        Args:
            username: Nombre de usuario
            password: Contraseña
            
        Returns:
            True si el login fue exitoso
        """
        if username in self.users:
            user = self.users[username]
            if user.password == self._hash_password(password):
                self.current_user = user
                return True
        return False
    
    def external_login(self, email: str, name: str, role: UserRole, 
                      token: str, api_data: Dict) -> bool:
        """
        Crear sesión local usando datos de autenticación externa (API)
        
        Args:
            email: Email del usuario (usado como username)
            name: Nombre completo del usuario
            role: Rol del usuario (UserRole)
            token: Token JWT de la API
            api_data: Datos adicionales del usuario desde la API
            
        Returns:
            True siempre (si se llama, asumimos que la API ya validó)
        """
        # Crear objeto User con datos externos
        # Nota: no necesitamos password ya que la autenticación fue externa
        self.current_user = User(
            username=email,
            password="",  # No aplica para login externo
            role=role
        )
        # Guardar datos adicionales
        self.api_token = token
        self.api_user_data = api_data
        # Asegurar que el usuario tenga nombre completo
        if name:
            self.current_user.full_name = name
        elif api_data and api_data.get('nombre'):
            self.current_user.full_name = api_data.get('nombre')
        else:
            self.current_user.full_name = email
    # print(f"[DEBUG] Sesión local creada para {email} con rol {role.value} y nombre {self.current_user.full_name}")
        return True
    
    def logout(self) -> bool:
        """Cerrar sesión"""
        self.current_user = None
        self.api_token = None
        self.api_user_data = None
        return True
    
    def has_permission(self, action: str) -> bool:
        """
        Verificar si el usuario actual tiene un permiso específico
        
        Args:
            action: Acción a verificar
            
        Returns:
            True si tiene el permiso
        """
        if not self.current_user:
            return False
        
        role = self.current_user.role
        user_permissions = self.permissions.get(role, [])
        
        return action in user_permissions
    
    def can_manage_slice(self, slice_owner: str) -> bool:
        """
        Verificar si el usuario puede gestionar un slice específico
        
        Args:
            slice_owner: Email del propietario del slice
            
        Returns:
            True si puede gestionar el slice
        """
        if not self.current_user:
            return False
        
        # SUPERADMIN y ADMIN pueden gestionar cualquier slice
        if self.current_user.role in [UserRole.SUPERADMIN, UserRole.ADMIN]:
            return True
        
        # Cliente solo puede gestionar sus propios slices
        return self.current_user.username == slice_owner
    
    def get_current_user_email(self) -> Optional[str]:
        """Obtener email del usuario actual"""
        if self.current_user:
            return self.current_user.username
        return None
    
    def get_current_user_name(self) -> Optional[str]:
        """Obtener nombre del usuario actual"""
        if self.current_user:
            if hasattr(self.current_user, 'full_name'):
                return self.current_user.full_name
            return self.current_user.username
        return None
    
    def get_api_token(self) -> Optional[str]:
        """Obtener token de la API (si existe)"""
        return self.api_token
    
    def get_api_user_data(self) -> Optional[Dict]:
        """Obtener datos adicionales del usuario desde la API"""
        return self.api_user_data
    
    def is_external_session(self) -> bool:
        """Verificar si la sesión actual es de autenticación externa"""
        return self.api_token is not None
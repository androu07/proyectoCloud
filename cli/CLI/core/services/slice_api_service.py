"""
Servicio para comunicación con la API de slices
"""

import requests
import os
from typing import List, Dict, Optional
import urllib3

# Deshabilitar warnings de SSL para certificados autofirmados
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class SliceAPIService:

    def create_slice_api(self, nombre_slice: str, solicitud_json: dict) -> dict:
        """
        Crea un slice usando el endpoint /slices/solicitud_creacion (servicio externo)
        Args:
            nombre_slice: nombre del slice
            solicitud_json: dict con la estructura completa de la solicitud (ver ejemplo curl)
        Returns:
            dict con la respuesta de la API o error
        """
        payload = {
            "nombre_slice": nombre_slice,
            "solicitud_json": solicitud_json
        }
        try:
            response = requests.post(
                f"{self.api_url}/slices/solicitud_creacion",
                headers=self.headers,
                json=payload,
                verify=False,
                timeout=60  # Aumentado a 60 segundos para operaciones de creación
            )
            print(f"[DEBUG] Status code: {response.status_code}")
            print(f"[DEBUG] Response text: {response.text[:200]}")
            if response.status_code in (200, 201):
                return {"ok": True, "data": response.json()}
            else:
                return {"ok": False, "error": response.text, "status": response.status_code}
        except requests.exceptions.Timeout:
            error_msg = "Timeout: El servidor tardó más de 60 segundos en responder. Verifique que el túnel SSH esté activo."
            print(f"[DEBUG] {error_msg}")
            return {"ok": False, "error": error_msg}
        except requests.exceptions.ConnectionError as e:
            error_msg = f"Error de conexión: No se pudo conectar al servidor. Verifique el túnel SSH: {str(e)}"
            print(f"[DEBUG] {error_msg}")
            return {"ok": False, "error": error_msg}
        except Exception as e:
            print(f"[DEBUG] Exception: {type(e).__name__}: {str(e)}")
            return {"ok": False, "error": str(e)}
    def list_all_slices(self) -> list:
        """
        Listar todos los slices (para admin)
        Usa el endpoint /slices/listar_slices del servidor remoto
        
        Respuesta esperada:
        {
          "success": true,
          "slices": [{"id": 5, "usuario": "...", "nombre_slice": "...", "vms": {...}, "estado": "activa", "timestamp": "..."}]
        }
        """
        try:
            response = requests.get(
                f"{self.api_url}/slices/listar_slices",
                headers=self.headers,
                verify=False,
                timeout=20  # Aumentado a 20 segundos
            )
            if response.status_code == 200:
                data = response.json()
                # La API devuelve {"success": true, "slices": [...], "total_slices": N}
                return data.get('slices', [])
            else:
                print(f"[ERROR] Error al listar slices: {response.status_code} - {response.text}")
                return []
        except requests.exceptions.Timeout:
            print(f"[ERROR] Timeout al listar slices. Verifique el túnel SSH.")
            return []
        except requests.exceptions.ConnectionError as e:
            print(f"[ERROR] Error de conexión al listar slices: {str(e)}")
            return []
        except Exception as e:
            print(f"[ERROR] Error al listar slices: {e}")
            return []

    def list_my_slices(self) -> list:
        """
        Listar los slices del usuario autenticado (cliente)
        Usa el endpoint /slices/listar_slices del servidor remoto
        
        Respuesta esperada:
        {
          "success": true,
          "slices": [{"id": 5, "usuario": "...", "nombre_slice": "...", "vms": {...}, "estado": "activa", "timestamp": "..."}]
        }
        """
        try:
            response = requests.get(
                f"{self.api_url}/slices/listar_slices",
                headers=self.headers,
                verify=False,
                timeout=20  # Aumentado a 20 segundos
            )
            if response.status_code == 200:
                data = response.json()
                # La API devuelve {"success": true, "slices": [...], "total_slices": N}
                all_slices = data.get('slices', [])
                
                # Los slices ya están filtrados por el backend según el token JWT
                # No necesitamos filtrar por usuario aquí
                return all_slices
            else:
                print(f"[ERROR] Error al listar mis slices: {response.status_code} - {response.text}")
                return []
        except requests.exceptions.Timeout:
            print(f"[ERROR] Timeout al listar slices. Verifique el túnel SSH.")
            return []
        except requests.exceptions.ConnectionError as e:
            print(f"[ERROR] Error de conexión al listar slices: {str(e)}")
            return []
        except Exception as e:
            print(f"[ERROR] Error al listar mis slices: {e}")
            return []
    """Servicio para gestión de slices con API externa"""
    
    def __init__(self, api_url: str, token: str, user_email: str = None):
        """
        Inicializa el servicio
        
        Args:
            api_url: URL base de la API (ej: http://localhost:8080)
            token: Token JWT de autenticación
            user_email: Email del usuario actual (opcional, para filtrado local)
        """
        self.api_url = api_url.rstrip('/')
        self.token = token
        self.user_email = user_email
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    
    def create_slice(self, nombre: str, topologia: str, vms_data: List[Dict]) -> Optional[Dict]:
        """
        Crear un nuevo slice
        
        Args:
            nombre: Nombre del slice
            topologia: String de topología (ej: "lineal-3VMS" o "arbol-4VMS+anillo-2VMS")
            vms_data: Lista de diccionarios con datos de VMs
            
        Returns:
            Datos del slice creado o None si falla
        """
        try:
            payload = {
                "nombre_slice": nombre,
                "topologia": topologia,
                "vms": vms_data
            }
            
            response = requests.post(
                f"{self.api_url}/slices/create",
                json=payload,
                headers=self.headers,
                verify=False,
                timeout=10
            )
            
            if response.status_code == 201:
                return response.json()
            else:
                print(f"[ERROR] Error al crear slice: {response.status_code}")
                print(f"[ERROR] {response.text}")
                return None
                
        except requests.exceptions.ConnectionError:
            print("[ERROR] No se puede conectar con la API de slices")
            return None
        except Exception as e:
            print(f"[ERROR] Error al crear slice: {e}")
            return None
    
    def get_my_slices(self) -> List[Dict]:
        """
        Obtener todos los slices del usuario actual
        
        Returns:
            Lista de slices
        """
        try:
            response = requests.get(
                f"{self.api_url}/slices/my-slices",
                headers=self.headers,
                verify=False,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get('slices', [])
            else:
                # print(f"[ERROR] Error al obtener slices: {response.status_code}")
                return self._get_slices_from_local()
                
        except requests.exceptions.ConnectionError:
            # print("[ERROR] No se puede conectar con la API de slices")
            # print("No se pudo conectar con la API. El slice y las VMs se guardarán localmente...")
            return self._get_slices_from_local()
        except Exception as e:
            # print(f"[ERROR] Error al obtener slices: {e}")
            return self._get_slices_from_local()
    
    def _get_slices_from_local(self) -> List[Dict]:
        """Leer slices desde base_de_datos.json cuando la API no está disponible"""
        import json
        import os
        
        try:
            BASE_JSON = os.path.join(os.path.dirname(__file__), '..', '..', 'base_de_datos.json')
            
            if os.path.exists(BASE_JSON):
                with open(BASE_JSON, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
                
                all_slices = data.get('slices', [])
                
                # Filtrar por usuario actual si tenemos el email
                if self.user_email:
                    all_slices = [s for s in all_slices if s.get('usuario') == self.user_email]
                
                return [
                    {
                        'id': s.get('id'),
                        'nombre_slice': s.get('nombre'),
                        'vlan': s.get('vlan'),
                        'topologia': s.get('topologia'),
                        'vms': s.get('vms', []),
                        'estado': s.get('estado', 'activo'),
                        'usuario': s.get('usuario')
                    }
                    for s in all_slices
                ]
            else:
                return []
        except Exception as e:
            # print(f"[ERROR] No se pudo leer base_de_datos.json: {e}")
            return []
    
    def get_slice_details(self, slice_id: int) -> Optional[Dict]:
        """
        Obtener detalles de un slice específico
        
        Args:
            slice_id: ID del slice
            
        Returns:
            Datos detallados del slice o None
        """
        try:
            response = requests.get(
                f"{self.api_url}/slices/{slice_id}",
                headers=self.headers,
                verify=False,
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                # print(f"[ERROR] Error al obtener detalles: {response.status_code}")
                return self._get_slice_details_from_local(slice_id)
                
        except Exception as e:
            # print(f"[ERROR] Error al obtener detalles: {e}")
            return self._get_slice_details_from_local(slice_id)
    
    def _get_slice_details_from_local(self, slice_id) -> Optional[Dict]:
        """Leer detalles de un slice desde base_de_datos.json"""
        import json
        import os
        
        try:
            BASE_JSON = os.path.join(os.path.dirname(__file__), '..', '..', 'base_de_datos.json')
            
            if os.path.exists(BASE_JSON):
                with open(BASE_JSON, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
                
                slices = data.get('slices', [])
                
                # Buscar el slice por ID
                for s in slices:
                    if str(s.get('id')) == str(slice_id):
                        return {
                            'id': s.get('id'),
                            'nombre_slice': s.get('nombre'),
                            'vlan': s.get('vlan'),
                            'topologia': s.get('topologia'),
                            'vms': s.get('vms', []),
                            'estado': s.get('estado', 'activo'),
                            'usuario': s.get('usuario')
                        }
                
                return None
            else:
                return None
        except Exception as e:
            # print(f"[ERROR] No se pudo leer detalles desde base_de_datos.json: {e}")
            return None
    
    def delete_slice(self, slice_id: int) -> bool:
        """
        Eliminar un slice
        
        Args:
            slice_id: ID del slice a eliminar
            
        Returns:
            True si se eliminó correctamente
        """
        try:
            response = requests.delete(
                f"{self.api_url}/slices/{slice_id}",
                headers=self.headers,
                verify=False,
                timeout=10
            )
            
            return response.status_code == 200
                
        except Exception as e:
            print(f"[ERROR] Error al eliminar slice: {e}")
            return False
    
    def pausar_slice(self, slice_id: int) -> dict:
        """
        Pausar un slice
        
        Args:
            slice_id: ID del slice a pausar
            
        Returns:
            dict con {"ok": bool, "message": str, "error": str (opcional)}
        """
        try:
            payload = {"slice_id": slice_id}
            response = requests.post(
                f"{self.api_url}/slices/pausar_slice",
                headers=self.headers,
                json=payload,
                verify=False,
                timeout=30  # Aumentado a 30 segundos
            )
            
            if response.status_code == 200:
                data = response.json()
                return {"ok": True, "message": data.get("message", "Slice pausado correctamente")}
            else:
                return {"ok": False, "error": response.text, "status": response.status_code}
                
        except requests.exceptions.Timeout:
            return {"ok": False, "error": "Timeout: El servidor tardó más de 30 segundos. Verifique el túnel SSH."}
        except requests.exceptions.ConnectionError as e:
            return {"ok": False, "error": f"Error de conexión: {str(e)}"}
        except Exception as e:
            return {"ok": False, "error": f"Error al pausar slice: {str(e)}"}
    
    def reanudar_slice(self, slice_id: int) -> dict:
        """
        Reanudar un slice
        
        Args:
            slice_id: ID del slice a reanudar
            
        Returns:
            dict con {"ok": bool, "message": str, "error": str (opcional)}
        """
        try:
            payload = {"slice_id": slice_id}
            response = requests.post(
                f"{self.api_url}/slices/reanudar_slice",
                headers=self.headers,
                json=payload,
                verify=False,
                timeout=30  # Aumentado a 30 segundos
            )
            
            if response.status_code == 200:
                data = response.json()
                return {"ok": True, "message": data.get("message", "Slice reanudado correctamente")}
            else:
                return {"ok": False, "error": response.text, "status": response.status_code}
                
        except requests.exceptions.Timeout:
            return {"ok": False, "error": "Timeout: El servidor tardó más de 30 segundos. Verifique el túnel SSH."}
        except requests.exceptions.ConnectionError as e:
            return {"ok": False, "error": f"Error de conexión: {str(e)}"}
        except Exception as e:
            return {"ok": False, "error": f"Error al reanudar slice: {str(e)}"}
    
    def eliminar_slice(self, slice_id):
        """
        Eliminar un slice
        
        Args:
            slice_id: ID del slice a eliminar
            
        Returns:
            dict con {"ok": bool, "message": str, "error": str (opcional)}
        """
        try:
            payload = {"slice_id": slice_id}
            response = requests.post(
                f"{self.api_url}/slices/eliminar_slice",
                headers=self.headers,
                json=payload,
                verify=False,
                timeout=30  # Aumentado a 30 segundos
            )
            
            if response.status_code == 200:
                data = response.json()
                return {"ok": True, "message": data.get("message", "Slice eliminado correctamente")}
            else:
                return {"ok": False, "error": response.text, "status": response.status_code}
                
        except requests.exceptions.Timeout:
            return {"ok": False, "error": "Timeout: El servidor tardó más de 30 segundos. Verifique el túnel SSH."}
        except requests.exceptions.ConnectionError as e:
            return {"ok": False, "error": f"Error de conexión: {str(e)}"}
        except Exception as e:
            return {"ok": False, "error": f"Error al eliminar slice: {str(e)}"}

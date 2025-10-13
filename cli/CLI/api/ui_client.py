import requests
from tabulate import tabulate
import json

class UIClient:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
        self.token = None
        self.headers = {}
    
    def login(self, username, password):
        """Autenticarse y obtener token"""
        response = requests.post(
            f"{self.base_url}/token",
            data={"username": username, "password": password}
        )
        
        if response.status_code == 200:
            data = response.json()
            self.token = data['access_token']
            self.headers = {"Authorization": f"Bearer {self.token}"}
            print(f"✅ Login exitoso como {username}")
            return True
        else:
            print("❌ Error de autenticación")
            return False
    
    def create_slice(self):
        """Crear un nuevo slice"""
        print("\n=== Crear Nuevo Slice ===")
        
        name = input("Nombre del slice: ")
        
        print("\nTopologías disponibles:")
        topologies = ["linear", "ring", "tree", "mesh", "bus"]
        for i, t in enumerate(topologies, 1):
            print(f"  {i}. {t.upper()}")
        
        top_idx = int(input("Seleccione topología (1-5): ")) - 1
        topology = topologies[top_idx]
        
        num_vms = int(input("Número de VMs (1-20): "))
        cpu = int(input("CPUs por VM (default 1): ") or "1")
        memory = int(input("Memoria MB (default 1024): ") or "1024")
        disk = int(input("Disco GB (default 10): ") or "10")
        
        data = {
            "name": name,
            "topology": topology,
            "num_vms": num_vms,
            "cpu": cpu,
            "memory": memory,
            "disk": disk
        }
        
        response = requests.post(
            f"{self.base_url}/api/slices",
            json=data,
            headers=self.headers
        )
        
        if response.status_code == 201:
            result = response.json()
            slice = result['slice']
            print(f"\n✅ Slice creado exitosamente!")
            print(f"ID: {slice['id']}")
            print(f"Estado: {slice['status']}")
            print(f"VMs creadas: {len(slice['vms'])}")
        else:
            print(f"❌ Error: {response.text}")
    
    def list_slices(self):
        """Listar todos los slices"""
        response = requests.get(
            f"{self.base_url}/api/slices",
            headers=self.headers
        )
        
        if response.status_code == 200:
            data = response.json()
            slices = data['slices']
            
            if not slices:
                print("\n📭 No hay slices creados")
                return
            
            print(f"\n=== Slices Activos ({data['total']}) ===")
            
            table_data = []
            for s in slices:
                table_data.append([
                    s['id'][:15] + "...",
                    s['name'],
                    s['topology'].upper(),
                    len(s['vms']),
                    s['status'],
                    s['owner']
                ])
            
            headers = ["ID", "Nombre", "Topología", "VMs", "Estado", "Owner"]
            print(tabulate(table_data, headers=headers, tablefmt="grid"))
        else:
            print(f"❌ Error: {response.text}")
    
    def view_slice_details(self):
        """Ver detalles de un slice"""
        slice_id = input("\nID del slice: ")
        
        response = requests.get(
            f"{self.base_url}/api/slices/{slice_id}",
            headers=self.headers
        )
        
        if response.status_code == 200:
            data = response.json()
            slice = data['slice']
            
            print(f"\n=== Detalles del Slice ===")
            print(f"ID: {slice['id']}")
            print(f"Nombre: {slice['name']}")
            print(f"Topología: {slice['topology'].upper()}")
            print(f"Estado: {slice['status']}")
            print(f"Propietario: {slice['owner']}")
            print(f"Creado: {slice['created_at']}")
            
            print(f"\n--- VMs ({len(slice['vms'])}) ---")
            for vm in slice['vms']:
                print(f"  • {vm['name']}")
                print(f"    CPU: {vm['cpu']} | RAM: {vm['memory']}MB | Disco: {vm['disk']}GB")
                print(f"    Estado: {vm['status']} | Host: {vm['host'] or 'No asignado'}")
        else:
            print(f"❌ Slice no encontrado")
    
    def delete_slice(self):
        """Eliminar un slice"""
        slice_id = input("\nID del slice a eliminar: ")
        
        confirm = input(f"⚠️  ¿Confirma eliminar {slice_id}? (s/n): ")
        if confirm.lower() != 's':
            print("Operación cancelada")
            return
        
        response = requests.delete(
            f"{self.base_url}/api/slices/{slice_id}",
            headers=self.headers
        )
        
        if response.status_code == 200:
            print("✅ Slice eliminado exitosamente")
        else:
            print(f"❌ Error: {response.text}")
    
    def run(self):
        """Ejecutar cliente interactivo"""
        print("\n╔════════════════════════════════════╗")
        print("║  PUCP Cloud Orchestrator - CLI     ║")
        print("║  FastAPI Edition v1.0              ║")
        print("╚════════════════════════════════════╝")
        
        # Login
        print("\n--- Autenticación ---")
        username = input("Usuario: ")
        password = input("Contraseña: ")
        
        if not self.login(username, password):
            return
        
        while True:
            print("\n--- Menú Principal ---")
            print("1. Crear Slice")
            print("2. Listar Slices")
            print("3. Ver Detalles de Slice")
            print("4. Eliminar Slice")
            print("5. Salir")
            
            choice = input("\nOpción: ")
            
            if choice == '1':
                self.create_slice()
            elif choice == '2':
                self.list_slices()
            elif choice == '3':
                self.view_slice_details()
            elif choice == '4':
                self.delete_slice()
            elif choice == '5':
                print("\n👋 ¡Hasta luego!")
                break
            else:
                print("❌ Opción inválida")

if __name__ == "__main__":
    client = UIClient()
    client.run()
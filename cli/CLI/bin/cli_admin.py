import sys

class SliceManager:
    def __init__(self):
        self.slices = {}  # Almacenará los slices en formato {ID: slice_data}
        self.current_id = 0

    def create_slice(self, slice_name, availability_zone, num_cpus, ram, disk):
        """Crea un nuevo slice."""
        slice_id = self.current_id
        self.slices[slice_id] = {
            'name': slice_name,
            'availability_zone': availability_zone,
            'cpu': num_cpus,
            'ram': ram,
            'disk': disk,
            'status': 'created'
        }
        self.current_id += 1
        print(f"Slice '{slice_name}' creado con ID: {slice_id}")

    def delete_slice(self, slice_id):
        """Elimina un slice dado un ID."""
        if slice_id in self.slices:
            del self.slices[slice_id]
            print(f"Slice con ID: {slice_id} eliminado.")
        else:
            print(f"Slice con ID: {slice_id} no encontrado.")

    def list_slices(self):
        """Lista todos los slices disponibles."""
        if not self.slices:
            print("No hay slices disponibles.")
        else:
            print("Slices disponibles:")
            for slice_id, data in self.slices.items():
                print(f"ID: {slice_id}, Nombre: {data['name']}, Estado: {data['status']}")

    def update_slice(self, slice_id, slice_name=None, availability_zone=None, num_cpus=None, ram=None, disk=None):
        """Actualiza un slice existente."""
        if slice_id in self.slices:
            slice = self.slices[slice_id]
            if slice_name:
                slice['name'] = slice_name
            if availability_zone:
                slice['availability_zone'] = availability_zone
            if num_cpus:
                slice['cpu'] = num_cpus
            if ram:
                slice['ram'] = ram
            if disk:
                slice['disk'] = disk
            print(f"Slice con ID: {slice_id} actualizado.")
        else:
            print(f"Slice con ID: {slice_id} no encontrado.")

    def manage_user(self, action, user_type):
        """Gestiona usuarios."""
        actions = {
            '1': 'Crear',
            '2': 'Editar',
            '3': 'Bloquear',
            '4': 'Eliminar'
        }
        user_types = {
            '1': 'Superadmin',
            '2': 'Admin',
            '3': 'Cliente'
        }
        print(f"Acción: {actions[action]}, Tipo de Usuario: {user_types[user_type]}")

def display_main_menu():
    """Muestra el menú principal."""
    print("\nGestión de Proyecto - CLI")
    print("1. Gestionar Slices")
    print("2. Gestionar Usuarios")
    print("3. Salir")

def display_slice_menu():
    """Muestra las opciones de gestión de slices."""
    print("\nGestión de Slices:")
    print("1. Crear Slice")
    print("2. Eliminar Slice")
    print("3. Listar Slices")
    print("4. Actualizar Slice")
    print("5. Regresar al menú principal")

def display_user_menu():
    """Muestra las opciones de gestión de usuarios."""
    print("\nGestión de Usuarios:")
    print("1. Crear")
    print("2. Editar")
    print("3. Bloquear")
    print("4. Eliminar")
    print("5. Regresar al menú principal")

def get_resource_input():
    """Obtiene la entrada de recursos para el slice."""
    print("\nOpciones de recursos:")

    # Zona de disponibilidad
    print("1. Zona 1")
    print("2. Zona 2")
    availability_zone = input("Seleccione la Zona de Disponibilidad (1 o 2): ")

    # Nro de CPUs
    print("1. 1 CPU")
    print("2. 2 CPUs")
    print("3. 4 CPUs")
    num_cpus = input("Seleccione el número de CPUs (1, 2 o 4): ")

    # Memoria RAM
    print("1. 1 GB RAM")
    print("2. 2 GB RAM")
    print("3. 4 GB RAM")
    ram = input("Seleccione la memoria RAM (1, 2 o 4 GB): ")

    # Discos Duros
    print("1. 50GB SSD")
    print("2. 100GB SSD")
    print("3. 150GB SSD")
    disk = input("Seleccione el disco duro (50GB, 100GB o 150GB): ")

    return availability_zone, num_cpus, ram, disk

def manage_user_input():
    """Obtiene la entrada para gestión de usuarios."""
    print("\nAcciones disponibles para usuarios:")
    print("1. Crear")
    print("2. Editar")
    print("3. Bloquear")
    print("4. Eliminar")
    action = input("Seleccione la acción a realizar (1, 2, 3 o 4): ")

    print("\nTipos de usuarios disponibles:")
    print("1. Superadmin")
    print("2. Admin")
    print("3. Cliente")
    user_type = input("Seleccione el tipo de usuario (1, 2 o 3): ")

    return action, user_type

def main():
    manager = SliceManager()

    while True:
        display_main_menu()
        choice = input("Seleccione una opción: ")

        if choice == '1':
            while True:
                display_slice_menu()
                slice_choice = input("Seleccione una opción: ")

                if slice_choice == '1':
                    slice_name = input("Ingrese el nombre del slice: ")
                    availability_zone, num_cpus, ram, disk = get_resource_input()
                    manager.create_slice(slice_name, availability_zone, num_cpus, ram, disk)

                elif slice_choice == '2':
                    slice_id = int(input("Ingrese el ID del slice a eliminar: "))
                    manager.delete_slice(slice_id)

                elif slice_choice == '3':
                    manager.list_slices()

                elif slice_choice == '4':
                    slice_id = int(input("Ingrese el ID del slice a actualizar: "))
                    slice_name = input("Nuevo nombre del slice (deje vacío para no cambiarlo): ")
                    availability_zone, num_cpus, ram, disk = get_resource_input()
                    manager.update_slice(slice_id, slice_name or None, availability_zone or None, num_cpus or None, ram or None, disk or None)

                elif slice_choice == '5':
                    break  # Regresar al menú principal

                else:
                    print("Opción no válida. Intente nuevamente.")

        elif choice == '2':
            while True:
                display_user_menu()
                user_choice = input("Seleccione una opción: ")

                if user_choice == '1' or user_choice == '2' or user_choice == '3' or user_choice == '4':
                    action, user_type = manage_user_input()
                    manager.manage_user(action, user_type)

                elif user_choice == '5':
                    break  # Regresar al menú principal

                else:
                    print("Opción no válida. Intente nuevamente.")

        elif choice == '3':
            print("Saliendo del gestor de slices.")
            sys.exit()

        else:
            print("Opción no válida. Intente nuevamente.")

if __name__ == "__main__":
    main()

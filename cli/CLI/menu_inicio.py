from slices.CRUD_slices import listar_slices , crear_slice, borrar_slice

# Menú Usuario:
def menu_usuario():
    while True:
        print("********************")
        print("*** Menú Usuario ***")
        print("********************")
        print("1. Listar Slices")
        print("2. Crear Slice")
        print("3. Editar Slice")
        print("4. Borrar Slice")
        print("5. Salir")
        opcion_usuario = input("Seleccione una opción: ")

        match opcion_usuario:
            case "1":
                listar_slices()
            case "2":
                crear_slice()
            case "3":
                #manage_topologia_users(user_id)
                print("ingreso a 3")
            case "4":
                borrar_slice()
            case "5":
                break
            case _:
                print("Opción Inválida")


# Menú principal
def main():
    while True:
        print("******************")
        print("*** BIENVENIDO ***")
        print("******************")
        print("1. Menú Usuario")
        print("2. Menú Administrador")
        opcion = input("Seleccione una opción: ")
        """
        print("Ingrese sus credenciales:\n")
        user = input("Usuario: ")
        password = input("Contraseña: ")

        #usuario = authenticate_user(user, password)
        
        #if usuario:
        """
        match opcion:
            case "1":
            #if usuario.rol == 'usuario':
                menu_usuario()
            #elif usuario.rol = 'administrador':
            case "2":
                while True:
                    print("**************************")
                    print("*** Menú Administrador ***")
                    print("**************************")
                    print("1. Configurar Slices")
                    print("2. Monitorear Recursos")
                    print("3. Registrar Nuevo Usuario")
                    print("4. Salir")
                    opcion_admin = input("Seleccione una opción: ")

                    match opcion_admin:
                        case "1":
                            #list_users()
                            print("ingreso a 1")
                        case "2":
                            #create_user()
                            print("ingreso a 2")
                        case "3":
                            #edit_user()
                            print("ingreso a 3")
                        case "4":
                            break
                        case _:
                            print("Opción Inválida")


if __name__ == "__main__":
    main()
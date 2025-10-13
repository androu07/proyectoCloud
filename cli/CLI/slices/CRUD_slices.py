#mostrar detalles de un slice:
def mostrar_detalles_slice():
    print("***********************")
    print("Slice: {Nombre Slice}")
    print("***********************")
    print("Tipo de Topología: {lineal, malla, arbol, etc}")
    print("Máquinas Virtuales (VMs):")
    print("+-------+-----------+-----------------------------------------------------------+")
    print("| N*Vm  | Nombre    | Recursos                                                  |")
    print("+-------+-----------+-----------------------------------------------------------+")
    #for index in vms:  
    for index in range(3):
        print(f"| vm{index+1}   | nombre    | CPU-Cores: 2 core(s) , RAM: 2 GB , Almacenamiento: 10 GB  |")
        print("+-------+-----------+-----------------------------------------------------------+")
    """
    print("| vm1   | nombre    | CPU-Cores: 2 core(s) , RAM: 2 GB , Almacenamiento: 10 GB  |")
    print("+-------+-----------+-----------------------------------------------------------+")
    print("| vm2   | nombre    | CPU-Cores: 3 core(s) , RAM: 3 GB , Almacenamiento: 15 GB  |")
    print("+-------+-----------+-----------------------------------------------------------+")
    """
    print("Enlaces:")
    print("+-----+-----------------+-----------------+")
    print("| N*  | nodo1           | nodo2           |")
    print("+-----+-----------------+-----------------+")
    #for index in enlaces:  
    for index in range(3):
        print(f"| {index+1}   | vm1: nombre     | vm2: nombre     |")
        print("+-----+-----------------+-----------------+")
    """
    print("| 1   | vm1: nombre     | vm2: nombre     |")
    print("+-----+-----------------+-----------------+")
    print("| 2   | vm2: nombre     | vm3: nombre     |")
    print("+-----+-----------------+-----------------+")
    """
    print("Zona de Disponibilidad: {nombre de zona}")
    print("Topología:")
    print("Gráfica de Topología") #guardado en BD o generado al momento


#listar slices del usuario
def listar_slices():
    while True:
        print("***********************")
        print("*** Lista de Slices ***")
        print("***********************")

        #Buscar desde BD o API los slices del usuario

        #for index,slice in slices:
        index = 0
        for index in range(5): #index va de 0 a 4
            #print(f"{index+1}: Slice: {slice.nombre}")
            print(f"{index+1}) Slice: {index+1}")
            #Si es el último elemento
            if index == len(range(5)) - 1:
                print(f"{index+2}) Salir")
        
        print("Seleccione un Slice para ver sus detalles")
        print(f"o escoja la opción {index+2} para volver al menú principal")

        opciones = [str(i) for i in range(1,index+3)] #array del n* de cada opcion como string
        opcion = input("Seleccione una opción: ")

        match opcion:
            case _ if opcion in opciones[:-1]: #si la opcion esta entre el array desde [1 a n-1]
                mostrar_detalles_slice()
            case _ if opcion == str(index+2): #si la opcion = n (o index+2)
                break
            case _:
                print("Opción Inválida")

def crear_slice():
    print("***********************")
    print("***** Crear Slice *****")
    print("***********************")
    nombre=input("Nombre del Slice: ")
    print("Seleccione una Topología para el Slice: ")
    print("1) Lineal")
    print("2) Malla")
    print("3) Árbol")
    print("4) Anillo")
    print("5) Bus")
    print("6) Personalizado")
    opciones = [str(i) for i in range(1,7)] #array del n* de cada opcion como string
    while True:
        topologia = input("Seleccione el slice a borrar: ")

        match topologia:
            case _ if topologia in opciones[:-1]: #si la opcion esta entre el array desde [1 a n-1]
                break
            case _:
                print("Opción Inválida")

    while True:
        try:
            n_vms_str = int(input("Número de VMs para el Slice: "))
        except Exception:
            print("Debe ingresar un número entero")
        else: 
            break #codigo que se ejecuta si no hubo excepcion

    n_vms = int(n_vms_str)
    for index in range(n_vms):
        nombre=input(f"Nombre de VM{index+1}: ")
        while True:
            try:
                cores_str = int(input("Cantidad de CPU-Cores: "))
            except Exception:
                print("Debe ingresar un número entero")
            else: 
                break #codigo que se ejecuta si no hubo excepcion
        cores=int(cores_str)
        while True:
            try:
                ram_str = int(input("Cantidad de Memoria RAM (GB): "))
            except Exception:
                print("Debe ingresar un número entero")
            else: 
                break #codigo que se ejecuta si no hubo excepcion
        ram=int(ram_str)
        while True:
            try:
                almacenamiento_str = int(input("Cantidad de Almacenamiento (GB): "))
            except Exception:
                print("Debe ingresar un número entero")
            else: 
                break #codigo que se ejecuta si no hubo excepcion
        almacenamiento=int(almacenamiento_str)
    
    while True:
    #Buscar desde BD las zonas de disponibilidad
        print("Seleccione la Zona de Disponibilidad para el despliegue del Slice")
        #for az in zonas_disponibilidad:
        index = 0
        for index in range(5): 
            print(f"{index+1}) AZ: nombre_zona")

        opciones = [str(i) for i in range(1,index+1)] #array del n* de cada opcion como string
        zona_disponibilidad_str = input("Ingrese opcion: ")

        match zona_disponibilidad_str:
            case _ if zona_disponibilidad_str in opciones: #si la opcion esta entre el array desde [1 a n-1]
                break
            case _:
                print("Opción Inválida")
    zona_disponibilidad = int(zona_disponibilidad_str)

def borrar_slice():
    flag = True
    while flag:
        print("***********************")
        print("*** Lista de Slices ***")
        print("***********************")

        #Buscar desde BD o API los slices del usuario

        #for index,slice in slices:
        index = 0
        for index in range(5): #index va de 0 a 4
            #print(f"{index+1}: Slice: {slice.nombre}")
            print(f"{index+1}) Slice: {index+1}")

        opciones = [str(i) for i in range(1,index+3)] #array del n* de cada opcion como string
        opcion = input("Seleccione el slice a borrar: ")

        match opcion:
            case _ if opcion in opciones[:-1]: #si la opcion esta entre el array desde [1 a n-1]
                mostrar_detalles_slice()
                print("Revise los detalles mostrados del slice y verifique si desea " \
                "realizar el borrado del slice, ya que la acción es irreversible y se " \
                "perderán todas las configuraciones y datos del slice")
                print("Luego de ello , seleccione una opción:")
                while True:
                    print("1) Confirmar Borrado")
                    print("2) Escoger otro Slice")
                    print("3) Salir")
                    opcion2 = input("Ingrese Opcion: ")

                    match opcion2:
                        case "1":
                            #borrar_slice_desplegado() #borrar el slice desplegado 
                            print("Slice borrado correctamente")
                            flag = False
                            break
                        case "2":
                            break
                        case "3":
                            flag = False
                            break
            case _:
                print("Opción Inválida")
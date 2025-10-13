import json
import os

BASE_JSON = os.path.join(os.path.dirname(__file__), '..', 'base_de_datos.json')
VMS_JSON = os.path.join(os.path.dirname(__file__), '..', 'vms.json')

def guardar_slice(slice_data):
    """Agrega un slice al archivo base_de_datos.json en el formato ejemplo (lista de objetos)"""
    import uuid
    # print("[DEBUG] guardar_slice llamado con:", slice_data)
    import sys
    sys.stdout.flush()
    try:
        if os.path.exists(BASE_JSON):
            with open(BASE_JSON, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = []
    except Exception as e:
        print("[ERROR] Al leer base_de_datos.json:", e)
        data = []
    # Generar nuevo slice en formato ejemplo
    # El id_slice será incremental: 1, 2, 3, ...
    if data:
        # Buscar el mayor id_slice actual (ignorando los vacíos o no numéricos)
        ids = [int(s.get('id_slice')) for s in data if str(s.get('id_slice')).isdigit()]
        new_id = str(max(ids) + 1) if ids else "1"
    else:
        new_id = "1"
    # Esperar que slice_data['topologias'] sea una lista de topologías completas (cada una con su info y VMs)
    topologias = slice_data.get('topologias')
    if not topologias:
        # Compatibilidad: si no viene la lista, usar el flujo anterior (1 sola topología)
        vms_data = slice_data.get('vms', [])
        cantidad_vms = str(len(vms_data))
        vlans_separadas = str(len(data) + 1)
        topologia_nombre = slice_data.get('topologia', 'lineal')
        salida_internet = slice_data.get('salida_internet', 'no')
        topologia_obj = {
            "nombre": topologia_nombre,
            "cantidad_vms": cantidad_vms,
            "internet": salida_internet,
            "vms": []
        }
        for vm in vms_data:
            topologia_obj["vms"].append({
                "nombre": vm.get("nombre", ""),
                "cores": str(vm.get("cpu", 1)),
                "ram": f"{vm.get('memory', 512)}M",
                "almacenamiento": f"{vm.get('disk', 1)}G",
                "puerto_vnc": "",
                "image": vm.get("imagen", ""),
                "conexiones_vlans": "",
                "acceso": vm.get("conexion_remota", "no"),
                "server": ""
            })
        topologias = [topologia_obj]
        cantidad_vms = str(len(vms_data))
    else:
        # Si viene la lista de topologías, calcular cantidad_vms sumando todas
        cantidad_vms = str(sum(int(t.get('cantidad_vms', len(t.get('vms', [])))) for t in topologias))
        vlans_separadas = str(len(data) + 1)

    new_slice = {
        "id_slice": new_id,
        "cantidad_vms": cantidad_vms,
        "vlans_separadas": vlans_separadas,
        "vlans_usadas": "",
        "vncs_separadas": "",
        "conexión_topologias": slice_data.get('conexión_topologias', ''),
        "topologias": topologias,
        "owner": slice_data.get('usuario', '')
    }
    data.append(new_slice)
    # Solución: limpiar caracteres problemáticos antes de guardar
    def clean_surrogates(obj):
        if isinstance(obj, dict):
            return {k: clean_surrogates(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_surrogates(x) for x in obj]
        elif isinstance(obj, str):
            return obj.encode('utf-8', 'surrogatepass').decode('utf-8', 'ignore')
        else:
            return obj
    data_clean = clean_surrogates(data)
    try:
        with open(BASE_JSON, 'w', encoding='utf-8') as f:
            json.dump(data_clean, f, indent=2, ensure_ascii=False)
    # print("[DEBUG] Slice guardado exitosamente en base_de_datos.json")
    except Exception as e:
        print("[ERROR] Al guardar base_de_datos.json:", e)

def guardar_vms(vms_list):
    """Agrega VMs al archivo vms.json (sobrescribe todo el array)"""
    if os.path.exists(VMS_JSON):
        with open(VMS_JSON, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = {"vms": []}
    data['vms'].extend(vms_list)
    with open(VMS_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

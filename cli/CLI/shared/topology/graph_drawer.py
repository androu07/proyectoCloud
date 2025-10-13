
# ============================================================================
# FUNCIONES DE VISUALIZACIÓN DE TOPOLOGÍAS
# ============================================================================

def draw_topology_graph(topology_type: str, num_vms: int):
    """Dibuja la topología como un grafo usando networkx y matplotlib"""
    G = nx.Graph()
    labels = {i: f"Máquina {i+1}" for i in range(num_vms)}
    
    # Crear nodos
    for i in range(num_vms):
        G.add_node(i)
    
    # Crear conexiones según topología
    if topology_type == 'lineal':
        for i in range(num_vms-1):
            G.add_edge(i, i+1)
    elif topology_type == 'anillo':
        for i in range(num_vms):
            G.add_edge(i, (i+1) % num_vms)
    elif topology_type == 'arbol':
        # Simple árbol binario
        for i in range(1, num_vms):
            G.add_edge((i-1)//2, i)
    elif topology_type == 'malla':
        for i in range(num_vms):
            for j in range(i+1, num_vms):
                G.add_edge(i, j)
    elif topology_type == 'bus':
        for i in range(num_vms):
            G.add_edge(i, 'bus')
        labels['bus'] = 'Bus Central'
    elif topology_type == 'mixta':
        # Para topología mixta, crear un layout más simple con todas las VMs
        for i in range(num_vms-1):
            G.add_edge(i, i+1)  # Conectar VMs secuencialmente
        # Conectar última con primera para hacer un círculo
        G.add_edge(num_vms-1, 0)
    
    # Configurar layout según topología
    pos = None
    if topology_type == 'anillo':
        pos = nx.circular_layout(G)
    elif topology_type == 'lineal':
        pos = nx.spring_layout(G)
    elif topology_type == 'arbol':
        pos = nx.spring_layout(G)
    elif topology_type == 'malla':
        pos = nx.spring_layout(G)
    elif topology_type == 'bus':
        pos = nx.spring_layout(G)
    elif topology_type == 'mixta':
        pos = nx.spring_layout(G, k=1)
    
    # Dibujar grafo
    plt.figure(figsize=(8, 8))
    nx.draw(G, pos, with_labels=True, labels=labels, node_color='skyblue', 
            node_size=1500, font_size=10, font_weight='bold', arrows=False)
    plt.title(f"Topología: {topology_type.capitalize()} ({num_vms} VMs)")
    plt.show()


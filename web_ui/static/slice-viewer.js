// Slice Viewer - Visualización de slice desplegado
let network = null;
let nodes = null;
let edges = null;
let sliceData = null;

document.addEventListener('DOMContentLoaded', function() {
    const sliceId = window.sliceId; // Pasado desde el template
    loadSliceData(sliceId);
    
    // Event listener para exportar JSON
    const exportBtn = document.getElementById('exportJsonBtn');
    if (exportBtn) {
        exportBtn.addEventListener('click', exportSliceJson);
    }
});

function loadSliceData(sliceId) {
    fetch(`/api/slice/${sliceId}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Error al cargar el slice');
            }
            return response.json();
        })
        .then(data => {
            sliceData = data;
            displaySliceInfo(data);
            renderTopology(data);
        })
        .catch(error => {
            console.error('Error:', error);
            showError('No se pudo cargar el slice: ' + error.message);
        });
}

function displaySliceInfo(data) {
    // Actualizar nombre del slice en el input
    const sliceNameInput = document.getElementById('sliceName');
    if (sliceNameInput) {
        sliceNameInput.value = data.nombre_slice || '';
    }
    
    // Actualizar título de la página
    const sliceNameDisplay = document.getElementById('sliceNameDisplay');
    if (sliceNameDisplay) {
        sliceNameDisplay.textContent = data.nombre_slice || 'Slice';
    }
    
    // Actualizar título del documento
    document.title = `${data.nombre_slice || 'Slice'} - Detalle`;
}

function renderTopology(data) {
    // Ocultar loading
    const loadingState = document.querySelector('.loading-state');
    if (loadingState) {
        loadingState.style.display = 'none';
    }
    
    // Mostrar network
    const networkDiv = document.getElementById('network');
    if (networkDiv) {
        networkDiv.style.display = 'block';
    }
    
    // Parsear peticion_json
    let peticionJson;
    try {
        if (typeof data.peticion_json === 'string') {
            peticionJson = JSON.parse(data.peticion_json);
        } else {
            peticionJson = data.peticion_json;
        }
    } catch (e) {
        console.error('Error parsing peticion_json:', e);
        showError('Error al parsear JSON del slice');
        return;
    }
    
    console.log('Peticion JSON:', peticionJson);
    
    if (!peticionJson) {
        showError('Datos de slice inválidos');
        return;
    }
    
    // El peticion_json tiene directamente las topologias
    const topologias = peticionJson.topologias || [];
    
    if (topologias.length === 0) {
        showError('No hay topologías en el slice');
        return;
    }
    
    // Crear nodos y aristas desde las topologías
    const nodesArray = [];
    const edgesArray = [];
    let nodeId = 1;
    let edgeId = 0;
    
    // Mapear VMs por nombre para buscar conexiones
    const vmByName = {};
    
    // Procesar cada topología
    topologias.forEach((topologia, topoIndex) => {
        const vms = topologia.vms || [];
        const baseX = (topoIndex - 1) * 450;
        const baseY = 0;
        const radius = 120;
        
        vms.forEach((vm, vmIndex) => {
            // Calcular posición
            let x, y;
            const vmCount = vms.length;
            
            if (topologia.nombre === '1vm') {
                // VMs individuales en posiciones distribuidas
                const col = vmIndex % 3;
                const row = Math.floor(vmIndex / 3);
                x = baseX + col * 200;
                y = baseY + row * 200;
            } else {
                // Disposición circular para topologías
                const angle = (2 * Math.PI * vmIndex) / vmCount - Math.PI / 2;
                x = baseX + radius * Math.cos(angle);
                y = baseY + radius * Math.sin(angle);
            }
            
            const vmNode = {
                id: nodeId,
                label: vm.nombre_ui || vm.nombre || `vm${nodeId}`,
                title: `${vm.nombre}\nCores: ${vm.cores}\nRAM: ${vm.ram}\nDisco: ${vm.almacenamiento}`,
                x: x,
                y: y,
                shape: 'image',
                image: createNodeImage(nodeId),
                size: 20,
                physics: false,
                vlans: vm.conexiones_vlans || ''
            };
            
            nodesArray.push(vmNode);
            vmByName[vm.nombre] = { id: nodeId, vlans: vm.conexiones_vlans || '' };
            
            nodeId++;
        });
    });
    
    // Crear aristas basadas en VLANs compartidas
    const vlanConnections = {};  // { vlanId: [vm1, vm2, ...] }
    
    // Agrupar VMs por VLAN
    Object.entries(vmByName).forEach(([vmName, vmData]) => {
        const vlans = vmData.vlans.split(',').map(v => v.trim()).filter(v => v);
        vlans.forEach(vlan => {
            if (!vlanConnections[vlan]) {
                vlanConnections[vlan] = [];
            }
            vlanConnections[vlan].push({ name: vmName, id: vmData.id });
        });
    });
    
    // Crear conexiones entre VMs que comparten VLANs
    const addedConnections = new Set();
    Object.entries(vlanConnections).forEach(([vlan, vmsInVlan]) => {
        // Conectar cada VM con las otras en la misma VLAN
        for (let i = 0; i < vmsInVlan.length; i++) {
            for (let j = i + 1; j < vmsInVlan.length; j++) {
                const vm1 = vmsInVlan[i];
                const vm2 = vmsInVlan[j];
                
                // Crear un ID único para esta conexión (ordenado para evitar duplicados)
                const connKey = [vm1.id, vm2.id].sort((a, b) => a - b).join('-');
                
                if (!addedConnections.has(connKey)) {
                    edgesArray.push({
                        id: edgeId++,
                        from: vm1.id,
                        to: vm2.id,
                        color: { color: '#8b5cf6', highlight: '#7c3aed' },
                        width: 3
                    });
                    addedConnections.add(connKey);
                }
            }
        }
    });
    
    // Agregar conexiones manuales adicionales (conexiones_vms)
    const conexionesStr = peticionJson.conexiones_vms || '';
    if (conexionesStr) {
        const conexiones = conexionesStr.split(';');  // Separación por punto y coma
        conexiones.forEach(conn => {
            if (!conn.trim()) return;
            
            const match = conn.match(/vm(\d+)-vm(\d+)/);
            if (match) {
                const from = parseInt(match[1]);
                const to = parseInt(match[2]);
                
                // Verificar que no esté duplicada
                const connKey = [from, to].sort((a, b) => a - b).join('-');
                
                if (!addedConnections.has(connKey)) {
                    edgesArray.push({
                        id: edgeId++,
                        from: from,
                        to: to,
                        color: { color: '#f59e0b', highlight: '#d97706' },
                        width: 4,
                        dashes: [10, 5]
                    });
                    addedConnections.add(connKey);
                }
            }
        });
    }
    
    // Inicializar vis.js
    nodes = new vis.DataSet(nodesArray);
    edges = new vis.DataSet(edgesArray);
    
    const container = document.getElementById('network');
    const networkData = { nodes: nodes, edges: edges };
    const options = {
        physics: {
            enabled: false
        },
        interaction: {
            dragNodes: false,
            dragView: true,
            zoomView: true
        },
        nodes: {
            borderWidth: 2,
            borderWidthSelected: 3,
            color: {
                border: '#667eea',
                background: '#ffffff',
                highlight: {
                    border: '#764ba2',
                    background: '#f0f0f0'
                }
            },
            font: {
                size: 12,
                color: '#1e293b',
                face: 'Inter, Arial'
            }
        },
        edges: {
            smooth: {
                type: 'continuous',
                roundness: 0.5
            },
            width: 2,
            color: {
                color: '#94a3b8',
                highlight: '#667eea'
            }
        }
    };
    
    network = new vis.Network(container, networkData, options);
    
    // Ajustar vista
    setTimeout(() => {
        network.fit({
            animation: {
                duration: 500,
                easingFunction: 'easeInOutQuad'
            }
        });
    }, 100);
}

function createNodeImage(nodeId) {
    const colors = ['#8b5cf6', '#ec4899', '#10b981', '#f59e0b', '#3b82f6', '#ef4444'];
    const color = colors[(nodeId - 1) % colors.length];
    
    const svg = `
        <svg xmlns="http://www.w3.org/2000/svg" width="60" height="60">
            <rect width="60" height="60" rx="8" fill="${color}"/>
            <rect x="8" y="35" width="44" height="4" rx="2" fill="white" opacity="0.8"/>
            <rect x="15" y="15" width="30" height="15" rx="2" fill="white" opacity="0.3"/>
        </svg>
    `;
    
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
}

function exportSliceJson() {
    if (!sliceData || !sliceData.peticion_json) {
        alert('No hay datos para exportar');
        return;
    }
    
    // Parsear si es string
    let jsonData;
    try {
        if (typeof sliceData.peticion_json === 'string') {
            jsonData = JSON.parse(sliceData.peticion_json);
        } else {
            jsonData = sliceData.peticion_json;
        }
    } catch (e) {
        alert('Error al procesar JSON');
        return;
    }
    
    // Crear blob y descargar
    const jsonStr = JSON.stringify(jsonData, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    
    const a = document.createElement('a');
    a.href = url;
    a.download = `${sliceData.nombre_slice || 'slice'}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function showError(message) {
    const loadingState = document.querySelector('.loading-state');
    if (loadingState) {
        loadingState.innerHTML = `
            <div style="text-align: center; color: #ef4444;">
                <svg width="64" height="64" style="margin-bottom: 16px;">
                    <circle cx="32" cy="32" r="30" stroke="#ef4444" stroke-width="2" fill="none"/>
                    <line x1="20" y1="20" x2="44" y2="44" stroke="#ef4444" stroke-width="2"/>
                    <line x1="44" y1="20" x2="20" y2="44" stroke="#ef4444" stroke-width="2"/>
                </svg>
                <p style="font-size: 18px; font-weight: 600; margin: 0;">${message}</p>
            </div>
        `;
    }
}

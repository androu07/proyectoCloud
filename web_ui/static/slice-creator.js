// Slice Creator with vis.js
let network = null;
let nodes = null;
let edges = null;
let topologies = [];
let topologyCounter = 0;
let currentNodeId = 1; // Comenzar en 1 para evitar problemas con validaciones falsy
let currentEdgeId = 0;
let selectedNode = null;
let isConnectingMode = false;
let connectingFrom = null;
let availableImages = []; // Cache de imágenes disponibles

// Initialize
document.addEventListener('DOMContentLoaded', function () {
    initializeEventListeners();
    updateTopologyCounter();
    updateVmCounter();
    loadNextSliceName();
    loadAvailableImages();
});

function initializeEventListeners() {
    // Add topology button
    document.getElementById('addTopologyBtn').addEventListener('click', function () {
        if (topologyCounter < 3) {
            openTopologyModal();
        } else {
            alert('Máximo 3 topologías permitidas');
        }
    });

    // Topology modal buttons
    document.getElementById('acceptTopologyBtn').addEventListener('click', addTopology);
    document.getElementById('closeTopologyModal').addEventListener('click', closeTopologyModal);

    // Cambiar número de VMs según tipo de topología
    document.getElementById('topologyType').addEventListener('change', function () {
        updateVmCountOptions(this.value);
    });

    // VM modal buttons
    document.getElementById('saveVmBtn').addEventListener('click', saveVmConfig);
    document.getElementById('closeVmModal').addEventListener('click', closeVmModal);

    // Create slice button
    document.getElementById('createSliceBtn').addEventListener('click', createSlice);

    // Exit edit button
    document.getElementById('exitEditBtn').addEventListener('click', exitEditMode);

    // Add VM button
    document.getElementById('addVmBtn').addEventListener('click', addIndividualVm);

    // Close modals when clicking outside
    window.addEventListener('click', function (event) {
        if (event.target.classList.contains('modal')) {
            event.target.style.display = 'none';
        }
    });
}

function loadNextSliceName() {
    // Cargar el siguiente nombre de slice único desde el servidor
    fetch('/api/next-slice-name')
        .then(response => response.json())
        .then(data => {
            if (data.success && data.name) {
                document.getElementById('sliceName').value = data.name;
            }
        })
        .catch(error => {
            console.error('Error cargando nombre de slice:', error);
            // Mantener el valor por defecto si hay error
        });
}

function loadAvailableImages() {
    // Cargar lista de imágenes disponibles
    fetch('/api/images/list')
        .then(response => response.json())
        .then(data => {
            if (data.success && data.images) {
                availableImages = data.images;
                populateImageSelect();
            }
        })
        .catch(error => {
            console.error('Error cargando imágenes:', error);
        });
}

function populateImageSelect() {
    const vmOSSelect = document.getElementById('vmOS');
    if (!vmOSSelect) return;
    
    // Limpiar opciones existentes
    vmOSSelect.innerHTML = '';
    
    // Agregar imágenes desde la BD (ya ordenadas por tamaño)
    availableImages.forEach((image, index) => {
        const option = document.createElement('option');
        option.value = JSON.stringify({
            id: image.id,
            id_openstack: image.id_openstack,
            nombre: image.nombre
        });
        option.textContent = image.nombre;
        // Seleccionar la primera imagen por defecto
        if (index === 0) {
            option.selected = true;
        }
        vmOSSelect.appendChild(option);
    });
    
    // Si no hay imágenes, agregar opción por defecto
    if (availableImages.length === 0) {
        const option = document.createElement('option');
        option.value = JSON.stringify({
            id: null,
            id_openstack: null,
            nombre: 'cirros'
        });
        option.textContent = 'Cirros (default)';
        vmOSSelect.appendChild(option);
    }
}

function openTopologyModal() {
    document.getElementById('topologyType').value = ''; // Reset selection
    document.getElementById('vmCount').innerHTML = '<option value="">Seleccione tipo primero</option>';
    document.getElementById('topologyModal').style.display = 'block';
}

function updateVmCountOptions(topologyType) {
    const vmCountSelect = document.getElementById('vmCount');
    let minVms, defaultVms;

    // Configurar mínimo y por defecto según tipo
    switch (topologyType) {
        case 'lineal':
            minVms = 2;
            defaultVms = 2;
            break;
        case 'arbol':
            // Árbol requiere al menos 5 VMs para una estructura razonable
            minVms = 5;
            defaultVms = 5;
            break;
        case 'anillo':
            minVms = 3;
            defaultVms = 3;
            break;
        default:
            minVms = 2;
            defaultVms = 4;
    }

    // Generar opciones desde el mínimo hasta 7
    let options = '';
    for (let i = minVms; i <= 7; i++) {
        const selected = (i === defaultVms) ? ' selected' : '';
        options += `<option value="${i}"${selected}>${i}</option>`;
    }

    vmCountSelect.innerHTML = options;
}

function closeTopologyModal() {
    document.getElementById('topologyModal').style.display = 'none';
}

function openVmModal(nodeId) {
    console.log('openVmModal called with nodeId:', nodeId, 'Type:', typeof nodeId);
    selectedNode = nodeId;
    const node = nodes.get(nodeId);
    console.log('Retrieved node:', node);
    if (!node) {
        console.error('Node not found for ID:', nodeId);
        return;
    }
    document.getElementById('vmName').value = node.label || node.name || '';
    
    // Establecer el valor del select de imagen
    if (node.imageData) {
        const imageValue = JSON.stringify({
            id: node.imageData.id,
            id_openstack: node.imageData.id_openstack,
            nombre: node.imageData.nombre
        });
        document.getElementById('vmOS').value = imageValue;
    }
    
    document.getElementById('vmFlavor').value = node.flavor || 'f7';
    document.getElementById('vmInternet').checked = node.internet || false;
    document.getElementById('vmModal').style.display = 'block';
}

function closeVmModal() {
    document.getElementById('vmModal').style.display = 'none';
    selectedNode = null;
}

function saveVmConfig() {
    if (selectedNode !== null && selectedNode !== undefined) {
        const name = document.getElementById('vmName').value;
        const osValue = document.getElementById('vmOS').value;
        const flavor = document.getElementById('vmFlavor').value;
        const internet = document.getElementById('vmInternet').checked;

        // Parsear el objeto de imagen que contiene id, id_openstack y nombre
        let imageData;
        try {
            imageData = JSON.parse(osValue);
        } catch (e) {
            // Fallback si no es JSON válido
            imageData = { id: null, id_openstack: null, nombre: osValue };
        }

        nodes.update({
            id: selectedNode,
            label: name,
            os: imageData.nombre,
            imageData: imageData, // Guardar el objeto completo
            flavor: flavor,
            internet: internet
        });
    }
    closeVmModal();
}

function deleteNodeAndTopology(nodeId) {
    const node = nodes.get(nodeId);
    const nodeName = node.label || node.name;
    
    if (confirm(`¿Estás seguro de eliminar "${nodeName}"?`)) {
        // Obtener y eliminar todas las aristas conectadas a este nodo
        const allEdges = edges.get();
        const edgesToRemove = allEdges.filter(edge => 
            edge.from === nodeId || edge.to === nodeId
        ).map(edge => edge.id);
        
        edges.remove(edgesToRemove);
        nodes.remove(nodeId);
        
        // NO eliminar la topología del array, solo el nodo
        // Las VMs de 1 VM se agrupan todas juntas en el JSON
        
        updateTopologyCounter();
        updateVmCounter();
        updateCreateButton();
    }
}

function deleteTopologyFromNode(nodeId) {
    const node = nodes.get(nodeId);
    const topologyName = node.topologyName;
    
    if (!topologyName) {
        alert('Esta VM no pertenece a ninguna topología');
        return;
    }
    
    if (confirm(`¿Estás seguro de eliminar la topología "${topologyName}"?`)) {
        // Obtener todos los nodos de esta topología
        const topologyNodes = nodes.get().filter(n => n.topologyName === topologyName);
        const nodeIds = topologyNodes.map(n => n.id);
        
        // Obtener y eliminar todas las aristas conectadas a estos nodos
        const allEdges = edges.get();
        const edgesToRemove = allEdges.filter(edge => 
            nodeIds.includes(edge.from) || nodeIds.includes(edge.to)
        ).map(edge => edge.id);
        
        edges.remove(edgesToRemove);
        nodes.remove(nodeIds);
        
        // Eliminar la topología del array
        const topoIndex = topologies.findIndex(t => t.name === topologyName);
        if (topoIndex !== -1) {
            topologies.splice(topoIndex, 1);
        }
        
        updateTopologyCounter();
        updateVmCounter();
        updateCreateButton();
    }
}

function addTopology() {
    const name = 'Topología ' + (topologyCounter + 1);
    const type = document.getElementById('topologyType').value;
    const vmCount = parseInt(document.getElementById('vmCount').value);

    if (!type) {
        alert('Por favor complete todos los campos');
        return;
    }

    // Validar máximo de VMs
    const currentVmCount = nodes ? nodes.get().length : 0;
    if (currentVmCount + vmCount > 12) {
        alert(`No se puede agregar la topología. Excedería el límite de 12 VMs (actualmente: ${currentVmCount}, intentando agregar: ${vmCount})`);
        return;
    }

    if (!network) {
        initializeNetwork();
    }

    const topology = createTopologyNodes(name, type, vmCount, topologyCounter);
    topologies.push(topology);
    topologyCounter++;

    updateTopologyCounter();
    updateVmCounter();
    updateCreateButton();
    closeTopologyModal();

    // Hide empty state and show network
    const emptyState = document.querySelector('.canvas-empty-state');
    if (emptyState) emptyState.style.display = 'none';

    const networkDiv = document.getElementById('network');
    networkDiv.style.display = 'block';
    networkDiv.style.width = '100%';
    networkDiv.style.height = '100%';

    // Show exit edit button
    const exitBtn = document.getElementById('exitEditBtn');
    if (exitBtn) exitBtn.style.display = 'flex';

    // Show add VM button
    const addVmBtn = document.getElementById('addVmBtn');
    if (addVmBtn) addVmBtn.style.display = 'flex';

    // Center the view
    setTimeout(() => {
        network.fit({
            animation: {
                duration: 1000,
                easingFunction: 'easeInOutQuad'
            }
        });
    }, 100);
}

function initializeNetwork() {
    const container = document.getElementById('network');

    nodes = new vis.DataSet([]);
    edges = new vis.DataSet([]);

    const data = { nodes: nodes, edges: edges };
    const options = {
        nodes: {
            shape: 'image',
            image: 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(`
                <svg width="48" height="48" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
                    <!-- Monitor -->
                    <rect x="6" y="8" width="36" height="24" rx="2" fill="%23667eea" stroke="%234c51bf" stroke-width="2"/>
                    <!-- Screen -->
                    <rect x="9" y="11" width="30" height="18" rx="1" fill="%238b5cf6"/>
                    <!-- Screen glare -->
                    <rect x="11" y="13" width="12" height="8" rx="1" fill="%23a78bfa" opacity="0.4"/>
                    <!-- Stand base -->
                    <rect x="18" y="32" width="12" height="3" rx="1.5" fill="%23667eea"/>
                    <!-- Stand neck -->
                    <rect x="22" y="29" width="4" height="3" fill="%234c51bf"/>
                    <!-- Keyboard -->
                    <rect x="12" y="38" width="24" height="6" rx="1" fill="%23475569"/>
                    <rect x="14" y="40" width="3" height="2" rx="0.5" fill="%23cbd5e1"/>
                    <rect x="18" y="40" width="3" height="2" rx="0.5" fill="%23cbd5e1"/>
                    <rect x="22" y="40" width="3" height="2" rx="0.5" fill="%23cbd5e1"/>
                    <rect x="26" y="40" width="3" height="2" rx="0.5" fill="%23cbd5e1"/>
                    <rect x="30" y="40" width="3" height="2" rx="0.5" fill="%23cbd5e1"/>
                </svg>
            `),
            size: 20,
            font: {
                size: 12,
                color: '#1e293b',
                background: 'rgba(255,255,255,0.95)',
                strokeWidth: 0
            },
            borderWidth: 0,
            borderWidthSelected: 2,
            shapeProperties: {
                useBorderWithImage: true
            },
            chosen: {
                node: function (values, id, selected, hovering) {
                    if (selected || hovering) {
                        values.size = 22;
                        values.borderWidth = 2;
                        values.borderColor = '#667eea';
                    }
                }
            }
        },
        edges: {
            width: 4,
            color: {
                color: '#a78bfa',
                highlight: '#8b5cf6',
                hover: '#7c3aed'
            },
            smooth: {
                enabled: true,
                type: 'dynamic',
                roundness: 0.5
            },
            arrows: { to: false },
            shadow: {
                enabled: true,
                color: 'rgba(139, 92, 246, 0.3)',
                size: 5,
                x: 0,
                y: 0
            }
        },
        physics: {
            enabled: false
        },
        interaction: {
            dragNodes: true,
            dragView: true,
            zoomView: true,
            hover: true
        },
        manipulation: {
            enabled: false
        }
    };

    network = new vis.Network(container, data, options);

    // Add zoom controls into the Create topology view (two buttons: zoom in / zoom out)
    try {
        createZoomControls(container);
    } catch (e) {
        console.warn('No se pudieron crear los controles de zoom al inicializar la red:', e);
    }

    // Double click to configure VM
    network.on('doubleClick', function (params) {
        console.log('Double click event:', params);
        console.log('Nodes clicked:', params.nodes);
        if (params.nodes.length > 0) {
            console.log('Opening modal for node:', params.nodes[0]);
            openVmModal(params.nodes[0]);
        }
    });

    // Single click for selecting nodes to create edge
    let firstNodeForEdge = null;
    network.on('click', function (params) {
        if (params.nodes.length > 0) {
            const nodeId = params.nodes[0];

            if (firstNodeForEdge === null) {
                // First node selected
                firstNodeForEdge = nodeId;
                network.selectNodes([nodeId]);
            } else if (firstNodeForEdge !== nodeId) {
                // Second node selected - try to create edge
                const existingEdges = edges.get();
                const edgeExists = existingEdges.some(e =>
                    (e.from === firstNodeForEdge && e.to === nodeId) ||
                    (e.from === nodeId && e.to === firstNodeForEdge)
                );

                if (!edgeExists) {
                    // Create new edge
                    edges.add({
                        id: currentEdgeId++,
                        from: firstNodeForEdge,
                        to: nodeId
                    });
                }

                firstNodeForEdge = null;
                network.unselectAll();
            }
        } else {
            // Click on empty space - deselect
            firstNodeForEdge = null;
            network.unselectAll();
        }
    });

    // Right click context menu for nodes and edges
    const canvas = container.getElementsByTagName('canvas')[0];
    canvas.addEventListener('contextmenu', function (event) {
        event.preventDefault();

        const nodeId = network.getNodeAt({
            x: event.offsetX,
            y: event.offsetY
        });

        const edgeId = network.getEdgeAt({
            x: event.offsetX,
            y: event.offsetY
        });

        if (nodeId !== undefined) {
            showNodeContextMenu(event, nodeId);
        } else if (edgeId !== undefined) {
            showEdgeContextMenu(event, edgeId);
        }
    });
}

// Create zoom controls (two buttons) dynamically inside the topology canvas wrapper
function createZoomControls(container) {
    if (!container || !container.parentElement) return;
    // prevent duplicates
    if (document.getElementById('zoomControls')) return;

    const controls = document.createElement('div');
    controls.id = 'zoomControls';
    controls.className = 'zoom-controls';

    const makeBtn = (id, label, title, handler) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.id = id;
        b.className = 'zoom-btn';
        b.title = title;
        b.textContent = label;
        b.addEventListener('click', handler);
        return b;
    };

    const zoomIn = makeBtn('zoomInBtn', '+', 'Aumentar zoom', function () { zoomBy(1.2); });
    const zoomOut = makeBtn('zoomOutBtn', '−', 'Reducir zoom', function () { zoomBy(1 / 1.2); });

    controls.appendChild(zoomIn);
    controls.appendChild(zoomOut);

    // Insert controls into the canvas wrapper so they float above the network
    container.parentElement.insertBefore(controls, container);
}

function zoomBy(factor) {
    if (!network) return;
    try {
        const currentScale = network.getScale();
        let newScale = currentScale * factor;
        newScale = Math.max(0.2, Math.min(2.5, newScale));
        network.moveTo({ scale: newScale, animation: { duration: 200, easingFunction: 'easeInOutQuad' } });
    } catch (e) {
        console.warn('Zoom error:', e);
    }
}

function showNodeContextMenu(event, nodeId) {
    // Remove existing context menu if any
    const existingMenu = document.getElementById('nodeContextMenu');
    if (existingMenu) {
        existingMenu.remove();
    }

    // Create context menu
    const menu = document.createElement('div');
    menu.id = 'nodeContextMenu';
    menu.style.position = 'fixed';
    menu.style.left = event.clientX + 'px';
    menu.style.top = event.clientY + 'px';
    menu.style.background = 'white';
    menu.style.border = '1px solid #e2e8f0';
    menu.style.borderRadius = '8px';
    menu.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)';
    menu.style.padding = '8px 0';
    menu.style.zIndex = '10000';
    menu.style.minWidth = '150px';

    // Configurar option
    const configOption = document.createElement('div');
    configOption.textContent = 'Configurar';
    configOption.style.padding = '10px 16px';
    configOption.style.cursor = 'pointer';
    configOption.style.fontSize = '14px';
    configOption.style.color = '#667eea';
    configOption.style.fontWeight = '500';
    configOption.style.transition = 'background 0.2s';

    configOption.addEventListener('mouseenter', function () {
        configOption.style.background = '#ede9fe';
    });

    configOption.addEventListener('mouseleave', function () {
        configOption.style.background = 'transparent';
    });

    configOption.addEventListener('click', function () {
        openVmModal(nodeId);
        menu.remove();
    });

    menu.appendChild(configOption);

    // Divider
    const divider = document.createElement('div');
    divider.style.height = '1px';
    divider.style.background = '#e2e8f0';
    divider.style.margin = '4px 0';
    menu.appendChild(divider);

    // Verificar si es una VM de la topología especial "Individual" (VMs solitarias)
    const node = nodes.get(nodeId);
    const topologyName = node.topologyName;
    
    let isSingleNodeDeletion = false;
    
    // Si la topología es "Individual", siempre borrar solo el nodo (VMs solitarias)
    if (topologyName === 'Individual') {
        isSingleNodeDeletion = true;
    } else {
        // Para topologías reales, verificar si tiene vmCount === 1
        const topology = topologies.find(t => t.name === topologyName);
        if (topology) {
            isSingleNodeDeletion = topology.vmCount === 1;
        }
    }

    // Delete option (Nodo o Topología según el caso)
    const deleteOption = document.createElement('div');
    deleteOption.textContent = isSingleNodeDeletion ? 'Borrar Nodo' : 'Borrar Topología';
    deleteOption.style.padding = '10px 16px';
    deleteOption.style.cursor = 'pointer';
    deleteOption.style.fontSize = '14px';
    deleteOption.style.color = '#ef4444';
    deleteOption.style.fontWeight = '500';
    deleteOption.style.transition = 'background 0.2s';

    deleteOption.addEventListener('mouseenter', function () {
        deleteOption.style.background = '#fee2e2';
    });

    deleteOption.addEventListener('mouseleave', function () {
        deleteOption.style.background = 'transparent';
    });

    deleteOption.addEventListener('click', function () {
        if (isSingleNodeDeletion) {
            deleteNodeAndTopology(nodeId);
        } else {
            deleteTopologyFromNode(nodeId);
        }
        menu.remove();
    });

    menu.appendChild(deleteOption);
    document.body.appendChild(menu);

    // Close menu when clicking outside
    setTimeout(() => {
        const closeMenu = function (e) {
            if (!menu.contains(e.target)) {
                menu.remove();
                document.removeEventListener('click', closeMenu);
            }
        };
        document.addEventListener('click', closeMenu);
    }, 100);
}

function showEdgeContextMenu(event, edgeId) {
    // Verificar si el enlace es de una topología definida
    const edge = edges.get(edgeId);
    if (edge.isTopologyEdge) {
        return; // No mostrar menú para enlaces de topología
    }

    // Remove existing context menu if any
    const existingMenu = document.getElementById('edgeContextMenu');
    if (existingMenu) {
        existingMenu.remove();
    }

    // Create context menu
    const menu = document.createElement('div');
    menu.id = 'edgeContextMenu';
    menu.style.position = 'fixed';
    menu.style.left = event.clientX + 'px';
    menu.style.top = event.clientY + 'px';
    menu.style.background = 'white';
    menu.style.border = '1px solid #e2e8f0';
    menu.style.borderRadius = '8px';
    menu.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)';
    menu.style.padding = '8px 0';
    menu.style.zIndex = '10000';
    menu.style.minWidth = '150px';

    const deleteOption = document.createElement('div');
    deleteOption.textContent = 'Eliminar Enlace';
    deleteOption.style.padding = '10px 16px';
    deleteOption.style.cursor = 'pointer';
    deleteOption.style.fontSize = '14px';
    deleteOption.style.color = '#ef4444';
    deleteOption.style.fontWeight = '500';
    deleteOption.style.transition = 'background 0.2s';

    deleteOption.addEventListener('mouseenter', function () {
        deleteOption.style.background = '#fee2e2';
    });

    deleteOption.addEventListener('mouseleave', function () {
        deleteOption.style.background = 'transparent';
    });

    deleteOption.addEventListener('click', function () {
        showDeleteEdgeModal(edgeId);
        menu.remove();
    });

    menu.appendChild(deleteOption);
    document.body.appendChild(menu);

    // Close menu when clicking outside
    setTimeout(() => {
        const closeMenu = function (e) {
            if (!menu.contains(e.target)) {
                menu.remove();
                document.removeEventListener('click', closeMenu);
            }
        };
        document.addEventListener('click', closeMenu);
    }, 100);
}

function showDeleteEdgeModal(edgeId) {
    const edge = edges.get(edgeId);
    const fromNode = nodes.get(edge.from);
    const toNode = nodes.get(edge.to);
    const modal = createConfirmModal(
        'Eliminar Enlace',
        `¿Estás seguro de eliminar el enlace entre "${fromNode.label}" y "${toNode.label}"?`,
        function () {
            deleteEdge(edgeId);
        }
    );
    document.body.appendChild(modal);
}

function createConfirmModal(title, message, onConfirm) {
    // Create modal overlay
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.style.display = 'flex';
    modal.style.alignItems = 'center';
    modal.style.justifyContent = 'center';

    // Create modal content
    const modalContent = document.createElement('div');
    modalContent.className = 'modal-content';
    modalContent.style.maxWidth = '400px';

    // Modal header
    const modalHeader = document.createElement('div');
    modalHeader.className = 'modal-header';

    const modalTitle = document.createElement('h3');
    modalTitle.textContent = title;
    modalTitle.style.margin = '0';

    // Create close button (X)
    const closeBtn = document.createElement('button');
    closeBtn.className = 'modal-close';
    closeBtn.innerHTML = '&times;';
    closeBtn.addEventListener('click', function () {
        modal.remove();
    });

    modalHeader.appendChild(modalTitle);
    modalHeader.appendChild(closeBtn);

    // Modal body
    const modalBody = document.createElement('div');
    modalBody.className = 'modal-body';

    const modalMessage = document.createElement('p');
    modalMessage.textContent = message;
    modalMessage.style.margin = '0';
    modalMessage.style.fontSize = '14px';
    modalMessage.style.color = '#475569';

    modalBody.appendChild(modalMessage);

    // Modal footer
    const modalFooter = document.createElement('div');
    modalFooter.className = 'modal-footer';
    modalFooter.style.justifyContent = 'space-between';
    modalFooter.style.alignItems = 'center';

    // Vista de Edición text
    const editModeText = document.createElement('span');
    editModeText.textContent = 'Vista de Edición';
    editModeText.style.fontSize = '13px';
    editModeText.style.color = '#64748b';
    editModeText.style.fontWeight = '500';

    const confirmBtn = document.createElement('button');
    confirmBtn.className = 'btn btn-danger';
    confirmBtn.textContent = 'Eliminar';
    confirmBtn.addEventListener('click', function () {
        onConfirm();
        modal.remove();
    });

    modalFooter.appendChild(editModeText);
    modalFooter.appendChild(confirmBtn);

    // Assemble modal
    modalContent.appendChild(modalHeader);
    modalContent.appendChild(modalBody);
    modalContent.appendChild(modalFooter);
    modal.appendChild(modalContent);

    // Close modal when clicking outside
    modal.addEventListener('click', function (event) {
        if (event.target === modal) {
            modal.remove();
        }
    });

    return modal;
}

function deleteNode(nodeId) {
    // Remove all edges connected to this node
    const connectedEdges = edges.get({
        filter: function (edge) {
            return edge.from === nodeId || edge.to === nodeId;
        }
    });

    edges.remove(connectedEdges.map(e => e.id));

    // Remove the node
    nodes.remove(nodeId);
}

function deleteEdge(edgeId) {
    edges.remove(edgeId);
}

function getNodeColor(index) {
    const colors = [
        { main: '#8b5cf6', dark: '#7c3aed', screen: '#a78bfa' }, // Purple
        { main: '#10b981', dark: '#059669', screen: '#34d399' }, // Green
        { main: '#f59e0b', dark: '#d97706', screen: '#fbbf24' }, // Orange
        { main: '#ef4444', dark: '#dc2626', screen: '#f87171' }, // Red
        { main: '#3b82f6', dark: '#2563eb', screen: '#60a5fa' }, // Blue
        { main: '#ec4899', dark: '#db2777', screen: '#f472b6' }, // Pink
    ];
    return colors[index % colors.length];
}

function createNodeImage(index) {
    const color = getNodeColor(index);
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(`
        <svg width="48" height="48" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
            <!-- Monitor -->
            <rect x="6" y="8" width="36" height="24" rx="2" fill="${color.main}" stroke="${color.dark}" stroke-width="2"/>
            <!-- Screen -->
            <rect x="9" y="11" width="30" height="18" rx="1" fill="${color.screen}"/>
            <!-- Screen glare -->
            <rect x="11" y="13" width="12" height="8" rx="1" fill="white" opacity="0.3"/>
            <!-- Stand base -->
            <rect x="18" y="32" width="12" height="3" rx="1.5" fill="${color.main}"/>
            <!-- Stand neck -->
            <rect x="22" y="29" width="4" height="3" fill="${color.dark}"/>
            <!-- Keyboard -->
            <rect x="12" y="38" width="24" height="6" rx="1" fill="#475569"/>
            <rect x="14" y="40" width="3" height="2" rx="0.5" fill="#fbbf24"/>
            <rect x="18" y="40" width="3" height="2" rx="0.5" fill="#34d399"/>
            <rect x="22" y="40" width="3" height="2" rx="0.5" fill="#f472b6"/>
            <rect x="26" y="40" width="3" height="2" rx="0.5" fill="#60a5fa"/>
            <rect x="30" y="40" width="3" height="2" rx="0.5" fill="#f87171"/>
        </svg>
    `);
}

function createTopologyNodes(name, type, vmCount, topologyId) {
    const newNodes = [];
    const newEdges = [];
    const startId = currentNodeId;

    // Calculate base position for this topology
    // Layout horizontal: 3 topologías en fila
    const baseX = (topologyId - 1) * 450; // -450, 0, 450
    const baseY = 0; // Todas a la misma altura
    const radius = 120;

    // Create nodes with calculated positions
    for (let i = 0; i < vmCount; i++) {
        const nodeId = currentNodeId++;
        let x, y;

        // Calculate position based on topology type
        switch (type) {
            case 'anillo': // Ring - circular layout
            case 'malla': // Mesh - also circular for clarity
                const angle = (2 * Math.PI * i) / vmCount - Math.PI / 2;
                x = baseX + radius * Math.cos(angle);
                y = baseY + radius * Math.sin(angle);
                break;
            case 'estrella': // Star - center + circle
                if (i === 0) {
                    x = baseX;
                    y = baseY;
                } else {
                    const starAngle = (2 * Math.PI * (i - 1)) / (vmCount - 1) - Math.PI / 2;
                    x = baseX + radius * Math.cos(starAngle);
                    y = baseY + radius * Math.sin(starAngle);
                }
                break;
            case 'arbol': // Tree - hierarchical layout
                const level = Math.floor(Math.log2(i + 1));
                const posInLevel = i - (Math.pow(2, level) - 1);
                const nodesInLevel = Math.pow(2, level);
                const levelWidth = 250;
                x = baseX + (posInLevel - (nodesInLevel - 1) / 2) * (levelWidth / nodesInLevel);
                y = baseY + level * 100 - 50;
                break;
            case 'lineal': // Linear - horizontal line
                const spacing = 100;
                x = baseX + (i - (vmCount - 1) / 2) * spacing;
                y = baseY;
                break;
            case 'bus': // Bus - main line with nodes below
                if (i === 0) {
                    // First node is the bus line (horizontal)
                    x = baseX;
                    y = baseY - 80;
                } else {
                    // Other nodes connect to the bus
                    const busSpacing = 100;
                    x = baseX + ((i - 1) - (vmCount - 2) / 2) * busSpacing;
                    y = baseY;
                }
                break;
            default:
                x = baseX;
                y = baseY;
        }

        newNodes.push({
            id: nodeId,
            label: `vm${nodeId}`,
            name: `vm${nodeId}`,
            topologyId: topologyId,
            topologyIndex: topologyId,
            topologyName: name,
            topologyType: type,
            os: availableImages.length > 0 ? availableImages[0].nombre : 'cirros',
            imageData: availableImages.length > 0 ? {
                id: availableImages[0].id,
                id_openstack: availableImages[0].id_openstack,
                nombre: availableImages[0].nombre
            } : { id: null, id_openstack: null, nombre: 'cirros' },
            flavor: 'f7',
            internet: false,
            x: x,
            y: y,
            fixed: false,
            physics: false,
            image: createNodeImage(i),
            configured: true
        });
    }

    // Create edges based on topology type
    switch (type) {
        case 'anillo': // Ring
            for (let i = 0; i < vmCount; i++) {
                const from = startId + i;
                const to = startId + ((i + 1) % vmCount);
                newEdges.push({ id: currentEdgeId++, from: from, to: to, isTopologyEdge: true });
            }
            break;
        case 'estrella': // Star
            const center = startId;
            for (let i = 1; i < vmCount; i++) {
                newEdges.push({ id: currentEdgeId++, from: center, to: startId + i, isTopologyEdge: true });
            }
            break;
        case 'malla': // Mesh
            for (let i = 0; i < vmCount; i++) {
                for (let j = i + 1; j < vmCount; j++) {
                    newEdges.push({ id: currentEdgeId++, from: startId + i, to: startId + j, isTopologyEdge: true });
                }
            }
            break;
        case 'arbol': // Tree
            for (let i = 1; i < vmCount; i++) {
                const parent = startId + Math.floor((i - 1) / 2);
                newEdges.push({ id: currentEdgeId++, from: parent, to: startId + i, isTopologyEdge: true });
            }
            break;
        case 'lineal': // Linear - connect nodes in sequence
            for (let i = 0; i < vmCount - 1; i++) {
                newEdges.push({ id: currentEdgeId++, from: startId + i, to: startId + i + 1, isTopologyEdge: true });
            }
            break;
        case 'bus': // Bus - first node (bus) connects to all others
            const busNode = startId;
            for (let i = 1; i < vmCount; i++) {
                newEdges.push({ id: currentEdgeId++, from: busNode, to: startId + i, isTopologyEdge: true });
            }
            break;
    }

    nodes.add(newNodes);
    edges.add(newEdges);

    return { id: topologyId, name: name, type: type, vmCount: vmCount, nodes: newNodes.map(n => n.id) };
}

function addEdgeBetweenTopologies(from, to) {
    // Check if edge already exists
    const existingEdges = edges.get();
    const edgeExists = existingEdges.some(e =>
        (e.from === from && e.to === to) || (e.from === to && e.to === from)
    );

    if (!edgeExists) {
        edges.add({
            id: currentEdgeId++,
            from: from,
            to: to,
            color: { color: '#f59e0b', highlight: '#d97706' },
            width: 4,
            dashes: [10, 5],
            isTopologyEdge: false  // Marcar como conexión manual
        });
    }
}

function updateTopologyCounter() {
    const currentCount = topologies.length;
    document.getElementById('topologyCounter').textContent = `${currentCount}/3 topologías`;

    if (currentCount >= 3) {
        document.getElementById('addTopologyBtn').disabled = true;
        document.getElementById('addTopologyBtn').style.opacity = '0.5';
        document.getElementById('addTopologyBtn').style.cursor = 'not-allowed';
    } else {
        document.getElementById('addTopologyBtn').disabled = false;
        document.getElementById('addTopologyBtn').style.opacity = '1';
        document.getElementById('addTopologyBtn').style.cursor = 'pointer';
    }
}

function updateCreateButton() {
    const createBtn = document.getElementById('createSliceBtn');
    if (topologies.length > 0) {
        createBtn.disabled = false;
        createBtn.style.opacity = '1';
        createBtn.style.cursor = 'pointer';
    } else {
        createBtn.disabled = true;
        createBtn.style.opacity = '0.5';
        createBtn.style.cursor = 'not-allowed';
    }
}

function updateVmCounter() {
    const vmCounterElement = document.getElementById('vmCounter');
    if (!vmCounterElement) {
        return;
    }
    
    const currentVmCount = nodes ? nodes.get().length : 0;
    vmCounterElement.textContent = `${currentVmCount}/12 VMs`;
    
    if (currentVmCount >= 12) {
        vmCounterElement.style.color = '#ef4444';
    } else {
        vmCounterElement.style.color = '#64748b';
    }
}

function createSlice() {
    const sliceName = document.getElementById('sliceName').value.trim();
    const availabilityZone = document.getElementById('availabilityZone').value;

    if (!sliceName) {
        alert('Por favor ingrese un nombre para el slice');
        return;
    }

    if (topologies.length === 0) {
        alert('Por favor agregue al menos una topología');
        return;
    }

    // Determinar zona de despliegue según availability zone
    const zonaDespliegue = availabilityZone === 'az-east' ? 'linux' : 'openstack';

    // Flavor mapping to OpenStack specifications with real IDs
    const flavorMap = {
        'f7': {  // 1 CPU - 0.5 GB RAM - 1G SSD
            id_flavor_openstack: '97ae963c-9a2f-4060-b0fc-fe81e2139396',
            cores: '1',
            ram: '512M',
            almacenamiento: '1G'
        },
        'f4': {  // 1 CPU - 0.5 GB RAM - 2G SSD
            id_flavor_openstack: '5b9bf881-240c-476e-87b5-87b649a6f93a',
            cores: '1',
            ram: '512M',
            almacenamiento: '2G'
        },
        'f11': {  // 1 CPU - 1 GB RAM - 1G SSD
            id_flavor_openstack: 'c98c31aa-e307-4b7a-a603-aa54f48ea08c',
            cores: '1',
            ram: '1024M',
            almacenamiento: '1G'
        },
        'f5': {  // 1 CPU - 1 GB RAM - 2G SSD
            id_flavor_openstack: '6caab6e5-9acc-42a4-aaa9-219f029d74c7',
            cores: '1',
            ram: '1024M',
            almacenamiento: '2G'
        },
        'f2': {  // 1 CPU - 1.5 GB RAM - 1G SSD
            id_flavor_openstack: '1e300b94-765c-4dcf-bc0f-e66a839a33f0',
            cores: '1',
            ram: '1536M',
            almacenamiento: '1G'
        },
        'f9': {  // 1 CPU - 1.5 GB RAM - 2G SSD
            id_flavor_openstack: 'c8fe35d8-9b63-4e82-a74e-1d1ae8af3800',
            cores: '1',
            ram: '1536M',
            almacenamiento: '2G'
        },
        'f13': {  // 1 CPU - 1.5 GB RAM - 3G SSD
            id_flavor_openstack: 'a9359dfd-3b9a-4d70-a2fa-24c32f34dd19',
            cores: '1',
            ram: '1536M',
            almacenamiento: '3G'
        },
        'f14': {  // 1 CPU - 1.5 GB RAM - 4G SSD
            id_flavor_openstack: '4ca10e44-bb14-4117-baac-fb9449dbb6cc',
            cores: '1',
            ram: '1536M',
            almacenamiento: '4G'
        },
        'f6': {  // 2 CPUs - 0.5 GB RAM - 1G SSD
            id_flavor_openstack: '7dd9272d-7fa1-445b-95e7-e6ebb2c8fdf8',
            cores: '2',
            ram: '512M',
            almacenamiento: '1G'
        },
        'f3': {  // 2 CPUs - 0.5 GB RAM - 2G SSD
            id_flavor_openstack: '2bf7e914-6cfe-4225-904d-0f25048367bd',
            cores: '2',
            ram: '512M',
            almacenamiento: '2G'
        },
        'f10': {  // 2 CPUs - 1 GB RAM - 1G SSD
            id_flavor_openstack: 'c89bed82-b0f2-4280-a6a3-7894a102658c',
            cores: '2',
            ram: '1024M',
            almacenamiento: '1G'
        },
        'f8': {  // 2 CPUs - 1 GB RAM - 2G SSD
            id_flavor_openstack: 'ade4cd83-c927-4248-9827-ba6294723be4',
            cores: '2',
            ram: '1024M',
            almacenamiento: '2G'
        },
        'f1': {  // 2 CPUs - 1.5 GB RAM - 1G SSD
            id_flavor_openstack: '0ea7f874-5c51-492f-a0e2-94f89eea6c4f',
            cores: '2',
            ram: '1536M',
            almacenamiento: '1G'
        },
        'f12': {  // 2 CPUs - 1.5 GB RAM - 2G SSD
            id_flavor_openstack: 'e019c355-1daf-43c3-86d3-861e5480a85c',
            cores: '2',
            ram: '1536M',
            almacenamiento: '2G'
        }
    };

    // Image mapping to OpenStack image UUIDs
    const imageMap = {
        'cirros': '1d85719e-ba3a-46d2-86fa-919fd5b1a78a',
        'ubuntu': '1d85719e-ba3a-46d2-86fa-919fd5b1a78a',
        'debian': '1d85719e-ba3a-46d2-86fa-919fd5b1a78a',
        'centos': '1d85719e-ba3a-46d2-86fa-919fd5b1a78a'
    };

    // Build topologias array in the new format
    const topologiasArray = [];
    let globalVmCounter = 1;

    // Process each topology
    topologies.forEach((topology, topoIndex) => {
        // Get all nodes for this topology
        const topologyNodes = nodes.get().filter(node => node.topologyName === topology.name);

        // Build VMs array for this topology
        const vmsArray = topologyNodes.map((node, nodeIndex) => {
            const flavorKey = node.flavor || 'f7';
            const flavorSpec = flavorMap[flavorKey] || flavorMap['f7'];
            
            // Determinar ID de imagen según zona de despliegue
            let imageId;
            if (node.imageData) {
                // Usar id (string) o id_openstack según la zona - SIEMPRE como string
                imageId = zonaDespliegue === 'linux' ? String(node.imageData.id) : String(node.imageData.id_openstack || '');
            } else {
                // Fallback a imagen por defecto si no hay imageData
                imageId = '';
            }

            // Use current globalVmCounter value for nombre, then increment
            const vmNumber = globalVmCounter++;

            return {
                nombre: `vm${vmNumber}`,
                nombre_ui: node.label || `vm${vmNumber}`,
                cores: flavorSpec.cores,
                ram: flavorSpec.ram,
                almacenamiento: flavorSpec.almacenamiento,
                id_flavor_openstack: flavorSpec.id_flavor_openstack,
                puerto_vnc: '',
                image: imageId,
                conexiones_vlans: '',
                internet: node.internet ? 'si' : 'no',
                server: ''
            };
        });

        // Determine topology name based on type
        let topologyName = topology.type;

        // Check if this is an individual VM topology (topologyName contains "Individual")
        if (topology.name === 'Individual' || topologyNodes.length === 1) {
            topologyName = '1vm';
        }

        topologiasArray.push({
            nombre: topologyName,
            cantidad_vms: String(vmsArray.length),
            vms: vmsArray
        });
    });

    // Process individual VMs (those not belonging to any topology)
    const individualVms = nodes.get().filter(node => node.topologyName === 'Individual' || !node.topologyName);
    if (individualVms.length > 0) {
        // Group all individual VMs into a single topology
        const individualVmsArray = individualVms.map(node => {
            const flavorKey = node.flavor || 'f7';
            const flavorSpec = flavorMap[flavorKey] || flavorMap['f7'];
            
            // Determinar ID de imagen según zona de despliegue
            let imageId;
            if (node.imageData) {
                // SIEMPRE convertir a string
                imageId = zonaDespliegue === 'linux' ? String(node.imageData.id) : String(node.imageData.id_openstack || '');
            } else {
                imageId = '';
            }

            return {
                nombre: `vm${globalVmCounter++}`,
                nombre_ui: node.label || node.name,
                cores: flavorSpec.cores,
                ram: flavorSpec.ram,
                almacenamiento: flavorSpec.almacenamiento,
                id_flavor_openstack: flavorSpec.id_flavor_openstack,
                puerto_vnc: '',
                image: imageId,
                conexiones_vlans: '',
                internet: node.internet ? 'si' : 'no',
                server: ''
            };
        });

        topologiasArray.push({
            nombre: '1vm',
            cantidad_vms: String(individualVmsArray.length),
            vms: individualVmsArray
        });
    }

    // Build connections string (format: "vm1-vm4") - solo conexiones manuales
    const edgesData = edges.get();
    const manualEdges = edgesData.filter(edge => !edge.isTopologyEdge);  // Filtrar conexiones de topología
    const connectionStrings = manualEdges.map(edge => {
        const fromNode = nodes.get(edge.from);
        const toNode = nodes.get(edge.to);

        // Find VM numbers by matching nodes
        let fromVmNum = 1;
        let toVmNum = 1;
        let currentVmNum = 1;

        // Iterate through all topologies to find the VM numbers
        for (const topo of topologiasArray) {
            for (const vm of topo.vms) {
                if (vm.nombre_ui === (fromNode.label || fromNode.name)) {
                    fromVmNum = currentVmNum;
                }
                if (vm.nombre_ui === (toNode.label || toNode.name)) {
                    toVmNum = currentVmNum;
                }
                currentVmNum++;
            }
        }

        return `vm${fromVmNum}-vm${toVmNum}`;
    }).join(';');  // Cambiar separador a punto y coma

    // Calculate total VMs
    const totalVms = topologiasArray.reduce((sum, topo) => sum + parseInt(topo.cantidad_vms), 0);

    // Build the final OpenStack-formatted JSON
    const sliceData = {
        nombre_slice: sliceName,
        zona_despliegue: zonaDespliegue,
        solicitud_json: {
            id_slice: '',
            total_vms: String(totalVms),
            vlans_usadas: '',
            conexiones_vms: connectionStrings,
            topologias: topologiasArray
        }
    };

    // Send to server
    showLoadingModal('Desplegando slice...', 'Creando VMs y configurando red. Esto puede tomar varios minutos.');
    
    fetch(createUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
        body: JSON.stringify(sliceData)
    })
        .then(async response => {
            const contentType = response.headers.get('content-type') || '';
            // If server returned JSON, parse it. Otherwise read as text for debugging.
            if (contentType.includes('application/json')) {
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.message || 'Error al crear el slice');
                }
                return data;
            }
            const text = await response.text();
            // Throw a controlled error so it's handled in the catch below
            const err = new Error('Non-JSON response from server');
            err.body = text;
            err.status = response.status;
            throw err;
        })
        .then(data => {
            closeLoadingModal();
            if (data && data.success) {
                showSuccessModal('Slice desplegado exitosamente', data.message || 'El slice se ha creado y desplegado correctamente.');
                // Redirigir a la lista de slices después de 2 segundos
                setTimeout(() => {
                    window.location.href = indexUrl;
                }, 2000);
            } else {
                showErrorModal('Error', (data && data.message) || 'No se pudo crear el slice');
            }
        })
        .catch(error => {
            closeLoadingModal();
            console.error('Create slice error:', error);
            if (error && error.body) {
                // Server returned HTML or plaintext (likely an error page). Show a helpful message.
                showErrorModal('Error del servidor', 'La respuesta del servidor no era JSON. Revisa la consola para más detalles.');
                console.error('Server response body:', error.body);
            } else {
                showErrorModal('Error', error.message || 'Error al crear el slice');
            }
        });
}

function showSuccessModal(title, message) {
    const modal = document.createElement('div');
    modal.className = 'notification-modal';
    modal.innerHTML = `
        <div class="notification-content success">
            <div class="notification-icon">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                    <polyline points="22 4 12 14.01 9 11.01"></polyline>
                </svg>
            </div>
            <h3>${title}</h3>
            <p>${message}</p>
            <button class="notification-btn" onclick="window.location.href='${indexUrl}'">Aceptar</button>
        </div>
    `;
    document.body.appendChild(modal);
    setTimeout(() => modal.classList.add('show'), 10);
}

function showErrorModal(title, message) {
    const modal = document.createElement('div');
    modal.className = 'notification-modal';
    modal.innerHTML = `
        <div class="notification-content error">
            <div class="notification-icon">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="15" y1="9" x2="9" y2="15"></line>
                    <line x1="9" y1="9" x2="15" y2="15"></line>
                </svg>
            </div>
            <h3>${title}</h3>
            <p>${message}</p>
            <button class="notification-btn" onclick="this.closest('.notification-modal').remove()">Aceptar</button>
        </div>
    `;
    document.body.appendChild(modal);
    setTimeout(() => modal.classList.add('show'), 10);
}

function showLoadingModal(title, message) {
    const modal = document.createElement('div');
    modal.id = 'loadingModal';
    modal.className = 'notification-modal show';
    modal.innerHTML = `
        <div class="notification-content loading">
            <div class="notification-icon">
                <div class="spinner"></div>
            </div>
            <h3>${title}</h3>
            <p>${message}</p>
        </div>
    `;
    document.body.appendChild(modal);
}

function closeLoadingModal() {
    const modal = document.getElementById('loadingModal');
    if (modal) {
        modal.remove();
    }
}

function exitEditMode() {
    // Clear all network data
    if (nodes) nodes.clear();
    if (edges) edges.clear();

    // Reset counters
    topologies = [];
    topologyCounter = 0;
    currentNodeId = 1; // Comenzar en 1 para evitar problemas con validaciones falsy
    currentEdgeId = 0;

    // Hide network and show empty state
    const networkDiv = document.getElementById('network');
    if (networkDiv) networkDiv.style.display = 'none';

    const emptyState = document.querySelector('.canvas-empty-state');
    if (emptyState) emptyState.style.display = 'block';

    // Hide exit button
    const exitBtn = document.getElementById('exitEditBtn');
    if (exitBtn) exitBtn.style.display = 'none';

    // Hide add VM button
    const addVmBtn = document.getElementById('addVmBtn');
    if (addVmBtn) addVmBtn.style.display = 'none';

    // Re-enable add topology button
    const addTopologyBtn = document.getElementById('addTopologyBtn');
    addTopologyBtn.disabled = false;
    addTopologyBtn.style.opacity = '1';
    addTopologyBtn.style.cursor = 'pointer';

    // Update UI
    updateTopologyCounter();
    updateCreateButton();
}

function addIndividualVm() {
    if (!network) {
        console.error("Network not initialized");
        return;
    }

    if (nodes.length === 0) {
        alert('Debe haber al menos una topología para añadir una VM individual');
        return;
    }

    // Validar máximo de VMs
    const currentVmCount = nodes.get().length;
    if (currentVmCount >= 12) {
        alert('No se puede agregar más VMs. Se ha alcanzado el límite máximo de 12 VMs.');
        return;
    }

    // Obtener el centro actual del canvas visible
    const viewPosition = network.getViewPosition();

    // Crear nueva VM con nombre VMx usando colores como las otras VMs
    const newNode = {
        id: currentNodeId,
        label: currentNodeId + 'vm',
        name: currentNodeId + 'vm',
        topologyId: null,
        topologyIndex: null,
        topologyName: 'Individual',
        os: availableImages.length > 0 ? availableImages[0].nombre : 'cirros',
        imageData: availableImages.length > 0 ? {
            id: availableImages[0].id,
            id_openstack: availableImages[0].id_openstack,
            nombre: availableImages[0].nombre
        } : { id: null, id_openstack: null, nombre: 'cirros' },
        flavor: 'f7',
        internet: false,
        x: viewPosition.x,
        y: viewPosition.y,
        fixed: {
            x: false,
            y: false
        },
        physics: false,
        shape: 'image',
        image: createNodeImage(currentNodeId),
        size: 20,
        borderWidth: 0,
        borderWidthSelected: 2,
        shapeProperties: {
            useBorderWithImage: true
        },
        chosen: true,
        configured: true
    };

    nodes.add(newNode);
    currentNodeId++;

    // Actualizar contador de VMs
    updateVmCounter();

    // Seleccionar el nuevo nodo para facilitar su arrastre
    network.selectNodes([newNode.id]);

    // Pequeño redraw
    setTimeout(() => {
        network.redraw();
    }, 50);
}

// Enable connecting mode with Ctrl+Click
document.addEventListener('keydown', function (e) {
    if (e.ctrlKey && topologies.length > 1) {
        isConnectingMode = true;
        document.body.style.cursor = 'crosshair';
    }
});

document.addEventListener('keyup', function (e) {
    if (!e.ctrlKey) {
        isConnectingMode = false;
        connectingFrom = null;
        document.body.style.cursor = 'default';
        if (network) network.unselectAll();
    }
});


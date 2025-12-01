// Slice Editor
let network=null,nodes=null,edges=null,selectedNode=null,currentNodeId=0,currentEdgeId=0;

function getNodeColor(i){
  const c=[
    {main:'#8b5cf6',dark:'#7c3aed',screen:'#a78bfa'},
    {main:'#10b981',dark:'#059669',screen:'#34d399'},
    {main:'#f59e0b',dark:'#d97706',screen:'#fbbf24'},
    {main:'#ef4444',dark:'#dc2626',screen:'#f87171'},
    {main:'#3b82f6',dark:'#2563eb',screen:'#60a5fa'},
    {main:'#ec4899',dark:'#db2777',screen:'#f472b6'}
  ];
  return c[i%c.length]
}

function createNodeImage(i){
  const c=getNodeColor(i);
  return 'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(`<svg width="48" height="48" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg"><rect x="6" y="8" width="36" height="24" rx="2" fill="${c.main}" stroke="${c.dark}" stroke-width="2"/><rect x="9" y="11" width="30" height="18" rx="1" fill="${c.screen}"/><rect x="11" y="13" width="12" height="8" rx="1" fill="white" opacity="0.3"/><rect x="18" y="32" width="12" height="3" rx="1.5" fill="${c.main}"/><rect x="22" y="29" width="4" height="3" fill="${c.dark}"/><rect x="12" y="38" width="24" height="6" rx="1" fill="#475569"/><rect x="14" y="40" width="3" height="2" rx="0.5" fill="#fbbf24"/><rect x="18" y="40" width="3" height="2" rx="0.5" fill="#34d399"/><rect x="22" y="40" width="3" height="2" rx="0.5" fill="#f472b6"/><rect x="26" y="40" width="3" height="2" rx="0.5" fill="#60a5fa"/><rect x="30" y="40" width="3" height="2" rx="0.5" fill="#f87171"/></svg>`)
}

// Calcular posiciones basadas en el tipo de topología
function calculateNodePositions(topology, vms) {
  const positions = [];
  const vmCount = vms.length;
  const type = topology.type ? topology.type.toLowerCase() : 'lineal';
  const radius = 120;
  
  switch(type) {
    case 'anillo':
      for (let i = 0; i < vmCount; i++) {
        const angle = (2 * Math.PI * i / vmCount) - Math.PI / 2;
        positions.push({
          x: radius * Math.cos(angle),
          y: radius * Math.sin(angle)
        });
      }
      break;
      
    case 'estrella':
      positions.push({ x: 0, y: 0 });
      for (let i = 1; i < vmCount; i++) {
        const angle = (2 * Math.PI * (i - 1) / (vmCount - 1)) - Math.PI / 2;
        positions.push({
          x: radius * Math.cos(angle),
          y: radius * Math.sin(angle)
        });
      }
      break;
      
    case 'arbol':
      for (let i = 0; i < vmCount; i++) {
        const level = Math.floor(Math.log2(i + 1));
        const posInLevel = i - (Math.pow(2, level) - 1);
        const nodesInLevel = Math.pow(2, level);
        const levelWidth = 250;
        positions.push({
          x: (posInLevel - (nodesInLevel - 1) / 2) * (levelWidth / nodesInLevel),
          y: level * 100 - 50
        });
      }
      break;
      
    case 'lineal':
      const spacing = 100;
      for (let i = 0; i < vmCount; i++) {
        positions.push({
          x: (i - (vmCount - 1) / 2) * spacing,
          y: 0
        });
      }
      break;
      
    case 'bus':
      positions.push({ x: 0, y: -80 });
      const busSpacing = 100;
      for (let i = 1; i < vmCount; i++) {
        positions.push({
          x: ((i - 1) - (vmCount - 2) / 2) * busSpacing,
          y: 0
        });
      }
      break;
      
    case 'malla':
      const cols = Math.ceil(Math.sqrt(vmCount));
      const rows = Math.ceil(vmCount / cols);
      for (let i = 0; i < vmCount; i++) {
        const row = Math.floor(i / cols);
        const col = i % cols;
        positions.push({
          x: (col - (cols - 1) / 2) * 100,
          y: (row - (rows - 1) / 2) * 100
        });
      }
      break;
      
    default:
      for (let i = 0; i < vmCount; i++) {
        positions.push({
          x: (i - (vmCount - 1) / 2) * 100,
          y: 0
        });
      }
  }
  
  return positions;
}

function loadSliceTopology(){
  fetch(`/api/slice/${sliceName}`)
    .then(r=>r.json())
    .then(res=>{
      if(res.success&&res.data){
        const d=res.data;
        nodes=new vis.DataSet();
        edges=new vis.DataSet();
        let ni=0;
        
        if(d.topologies&&Array.isArray(d.topologies)){
          d.topologies.forEach((t,ti)=>{
            if(t.vms&&Array.isArray(t.vms)){
              const positions = calculateNodePositions(t, t.vms);
              const baseX = ti * 400;
              
              t.vms.forEach((v,vi)=>{
                const nid=currentNodeId++;
                const pos = positions[vi] || { x: 0, y: 0 };
                
                nodes.add({
                  id:nid,
                  label:v.name||`vm-${nid}`,
                  name:v.name||`vm-${nid}`,
                  os:v.os||'cirros',
                  flavor:v.flavor||'f1',
                  internet:v.internet||false,
                  shape:'image',
                  image:createNodeImage(ni++),
                  size:20,
                  x:pos.x + baseX,
                  y:pos.y,
                  fixed:false,
                  physics:false
                })
              })
            }
          });
          
          if(d.connections&&Array.isArray(d.connections)){
            d.connections.forEach(c=>{
              const an=nodes.get(),
                    fn=an.find(n=>n.name===c.from),
                    tn=an.find(n=>n.name===c.to);
              if(fn&&tn)edges.add({id:currentEdgeId++,from:fn.id,to:tn.id})
            })
          }
        }else if(d.vms&&Array.isArray(d.vms)){
          d.vms.forEach((v,i)=>{
            const nid=currentNodeId++;
            nodes.add({
              id:nid,
              label:v.name||`vm-${nid}`,
              name:v.name||`vm-${nid}`,
              os:v.os||'cirros',
              flavor:v.flavor||'f1',
              internet:v.internet||false,
              shape:'image',
              image:createNodeImage(i),
              size:20,
              x:(i-d.vms.length/2)*100,
              y:0,
              fixed:false,
              physics:false
            })
          });
          
          if(d.connections&&Array.isArray(d.connections)){
            d.connections.forEach(c=>{
              const an=nodes.get(),
                    fn=an.find(n=>n.name===c.from),
                    tn=an.find(n=>n.name===c.to);
              if(fn&&tn)edges.add({id:currentEdgeId++,from:fn.id,to:tn.id})
            })
          }
        }
        
        if(nodes.get().length > 0){
          initializeNetwork();
        }else{
          console.warn('No hay nodos para mostrar');
        }
      }else{
        console.error('No se pudieron cargar los datos del slice');
      }
    })
    .catch(e=>{
      console.error('Error cargando topología:',e);
    })
}

function initializeNetwork(){
  const c=document.getElementById('network'),
        d={nodes,edges},
        o={
          nodes:{
            shape:'image',
            size:20,
            font:{size:12,color:'#1e293b',background:'rgba(255,255,255,0.95)',strokeWidth:0},
            borderWidth:0,
            borderWidthSelected:2,
            shapeProperties:{useBorderWithImage:true},
            chosen:{node:(v,id,s,h)=>{if(s||h){v.size=22;v.borderWidth=2;v.borderColor='#667eea'}}}
          },
          edges:{
            width:4,
            color:{color:'#a78bfa',highlight:'#8b5cf6',hover:'#7c3aed'},
            smooth:{enabled:true,type:'dynamic',roundness:0.5},
            arrows:{to:false},
            shadow:{enabled:true,color:'rgba(139,92,246,0.3)',size:5,x:0,y:0}
          },
          physics:{enabled:false},
          interaction:{dragNodes:true,dragView:true,zoomView:true,hover:true},
          manipulation:{enabled:false}
        };
  
  network=new vis.Network(c,d,o);
  
  const e=document.querySelector('.canvas-empty-state');
  if(e)e.style.display='none';
  const n=document.getElementById('network');
  n.style.display='block';
  
  createZoomControls(c);
  
  network.on('doubleClick',p=>{if(p.nodes.length>0)openVmModal(p.nodes[0])});
  
  let f=null;
  network.on('click',p=>{
    if(p.nodes.length>0){
      const nid=p.nodes[0];
      if(!f){
        f=nid;
        network.selectNodes([nid])
      }else if(f!==nid){
        const ee=edges.get(),
              ex=ee.some(e=>(e.from===f&&e.to===nid)||(e.from===nid&&e.to===f));
        if(!ex)edges.add({id:currentEdgeId++,from:f,to:nid});
        f=null;
        network.unselectAll()
      }
    }else{
      f=null;
      network.unselectAll()
    }
  });
  
  const cv=c.getElementsByTagName('canvas')[0];
  cv.addEventListener('contextmenu',ev=>{
    ev.preventDefault();
    const nid=network.getNodeAt({x:ev.offsetX,y:ev.offsetY}),
          eid=network.getEdgeAt({x:ev.offsetX,y:ev.offsetY});
    if(nid!==undefined)showNodeContextMenu(ev,nid);
    else if(eid!==undefined)showEdgeContextMenu(ev,eid)
  });
  
  setTimeout(()=>network.fit({animation:{duration:1000,easingFunction:'easeInOutQuad'}}),100)
}
function createZoomControls(c){if(!c||!c.parentElement||document.getElementById('zoomControls'))return;const ctrl=document.createElement('div');ctrl.id='zoomControls';ctrl.className='zoom-controls';const mkBtn=(id,lbl,ttl,h)=>{const b=document.createElement('button');b.type='button';b.id=id;b.className='zoom-btn';b.title=ttl;b.textContent=lbl;b.addEventListener('click',h);return b};ctrl.appendChild(mkBtn('zoomInBtn','+','Aumentar zoom',()=>zoomBy(1.2)));ctrl.appendChild(mkBtn('zoomOutBtn','','Reducir zoom',()=>zoomBy(1/1.2)));c.parentElement.insertBefore(ctrl,c)}
function zoomBy(f){if(!network)return;try{const cs=network.getScale();let ns=cs*f;ns=Math.max(0.2,Math.min(2.5,ns));network.moveTo({scale:ns,animation:{duration:200,easingFunction:'easeInOutQuad'}})}catch(e){console.warn('Zoom error:',e)}}
function openVmModal(nid){
  selectedNode=nid;
  const n=nodes.get(nid);
  document.getElementById('vmName').value=n.name||n.label;
  document.getElementById('vmOS').value=n.os||'cirros';
  document.getElementById('vmFlavor').value=n.flavor||'f1';
  document.getElementById('vmInternet').checked=n.internet||false;
  document.getElementById('vmModal').style.display='flex'
}
function closeVmModal(){
  document.getElementById('vmModal').style.display='none';
  selectedNode=null
}
function saveVmConfig(){
  if(selectedNode){
    const nm=document.getElementById('vmName').value,
          os=document.getElementById('vmOS').value,
          fl=document.getElementById('vmFlavor').value,
          it=document.getElementById('vmInternet').checked;
    nodes.update({id:selectedNode,label:nm,name:nm,os:os,flavor:fl,internet:it})
  }
  closeVmModal()
}
function showNodeContextMenu(ev,nid){const em=document.getElementById('nodeContextMenu');if(em)em.remove();const m=document.createElement('div');m.id='nodeContextMenu';m.style.cssText=`position:fixed;left:${ev.clientX}px;top:${ev.clientY}px;background:white;border:1px solid #e2e8f0;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.15);padding:8px 0;z-index:10000;min-width:150px`;const o=document.createElement('div');o.textContent='Eliminar Nodo';o.style.cssText=`padding:10px 16px;cursor:pointer;font-size:14px;color:#ef4444;font-weight:500;transition:background 0.2s`;o.addEventListener('mouseenter',()=>o.style.background='#fee2e2');o.addEventListener('mouseleave',()=>o.style.background='transparent');o.addEventListener('click',()=>{if(confirm(`¿Eliminar el nodo "${nodes.get(nid).label}"?`)){const ce=edges.get({filter:e=>e.from===nid||e.to===nid});edges.remove(ce.map(e=>e.id));nodes.remove(nid)}m.remove()});m.appendChild(o);document.body.appendChild(m);setTimeout(()=>{const cl=e=>{if(!m.contains(e.target)){m.remove();document.removeEventListener('click',cl)}};document.addEventListener('click',cl)},100)}
function showEdgeContextMenu(ev,eid){const em=document.getElementById('edgeContextMenu');if(em)em.remove();const m=document.createElement('div');m.id='edgeContextMenu';m.style.cssText=`position:fixed;left:${ev.clientX}px;top:${ev.clientY}px;background:white;border:1px solid #e2e8f0;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.15);padding:8px 0;z-index:10000;min-width:150px`;const o=document.createElement('div');o.textContent='Eliminar Enlace';o.style.cssText=`padding:10px 16px;cursor:pointer;font-size:14px;color:#ef4444;font-weight:500;transition:background 0.2s`;o.addEventListener('mouseenter',()=>o.style.background='#fee2e2');o.addEventListener('mouseleave',()=>o.style.background='transparent');o.addEventListener('click',()=>{const e=edges.get(eid),fn=nodes.get(e.from),tn=nodes.get(e.to);if(confirm(`¿Eliminar el enlace entre "${fn.label}" y "${tn.label}"?`))edges.remove(eid);m.remove()});m.appendChild(o);document.body.appendChild(m);setTimeout(()=>{const cl=e=>{if(!m.contains(e.target)){m.remove();document.removeEventListener('click',cl)}};document.addEventListener('click',cl)},100)}
document.addEventListener('DOMContentLoaded',()=>{document.getElementById('closeVmModal').addEventListener('click',closeVmModal);document.getElementById('saveVmBtn').addEventListener('click',saveVmConfig);document.getElementById('saveSliceBtn').addEventListener('click',()=>{const sn=document.getElementById('sliceName').value;if(!sn){alert('Por favor ingrese un nombre para el slice');return}const vms=nodes.get().map(n=>({name:n.name||n.label,os:n.os||'cirros',flavor:n.flavor||'f1',internet:n.internet||false})),conns=edges.get().map(e=>({from:nodes.get(e.from).name||nodes.get(e.from).label,to:nodes.get(e.to).name||nodes.get(e.to).label})),sd={name:sn,vms,connections:conns},fd=new FormData();fd.append('slice_data',JSON.stringify(sd));fetch(updateUrl,{method:'POST',body:fd}).then(r=>{if(r.ok)window.location.href=detailUrl;else alert('Error al actualizar el slice')}).catch(e=>{console.error('Error:',e);alert('Error de conexión')})});setTimeout(loadSliceTopology,500)});

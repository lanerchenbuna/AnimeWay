/* AnimeWay local component. WGS84 / Web Mercator, visible tiles only; no remote JS. */
(() => {
  'use strict';
  const el=document.getElementById('map'), tiles=document.getElementById('tiles'), pins=document.getElementById('pins');
  const origin=window.location.origin;
  let args=null, center=[139.7,35.68], zoom=12, initialized=false, cameraId=null, timer=null, tileFailed=false;
  let tileNodes=new Map(), pointers=new Map(), gesture=null;
  const wrap=x=>((x+180)%360+360)%360-180, clamp=(v,a,b)=>Math.min(b,Math.max(a,v));
  const world=z=>256*Math.pow(2,z);
  function project(lon,lat,z){const s=world(z),r=clamp(lat,-85.051128,85.051128)*Math.PI/180;return [(lon+180)/360*s,(1-Math.asinh(Math.tan(r))/Math.PI)/2*s];}
  function unproject(x,y,z){const s=world(z);return [wrap(x/s*360-180),Math.atan(Math.sinh(Math.PI*(1-2*y/s)))*180/Math.PI];}
  function send(type,extra={}){window.parent.postMessage({isStreamlitMessage:true,type,...extra},origin);}
  function event(kind,extra={}){if(args)send('streamlit:setComponentValue',{dataType:'json',value:{kind,context:args.context,event_id:crypto.randomUUID(),...extra}});}
  function viewport(){const c=project(...center,zoom),w=el.clientWidth,h=el.clientHeight;const sw=unproject(c[0]-w/2,c[1]+h/2,zoom),ne=unproject(c[0]+w/2,c[1]-h/2,zoom);return [w>=world(zoom)?-180:sw[0],clamp(sw[1],-90,90),w>=world(zoom)?180:ne[0],clamp(ne[1],-90,90)];}
  function notify(){clearTimeout(timer);timer=setTimeout(()=>event('viewport',{bbox:viewport(),zoom,camera_id:cameraId}),220);}
  function fit(box,padding=40){let [w,s,e,n]=box;if(e<w)e+=360;center=[wrap((w+e)/2),(s+n)/2];const a=project(w,n,0),b=project(e,s,0);zoom=clamp(Math.min(Math.log2(Math.max(50,el.clientWidth-padding)/Math.max(.001,b[0]-a[0])),Math.log2(Math.max(50,el.clientHeight-padding)/Math.max(.001,b[1]-a[1]))),0,18);const mid=unproject((a[0]+b[0])/2,(a[1]+b[1])/2,0);center=mid;}
  function zoomAt(next,x=el.clientWidth/2,y=el.clientHeight/2){const c=project(...center,zoom),ratio=Math.pow(2,clamp(next,0,19)-zoom);const anchor=[c[0]+x-el.clientWidth/2,c[1]+y-el.clientHeight/2];zoom=clamp(next,0,19);center=unproject(anchor[0]*ratio-x+el.clientWidth/2,anchor[1]*ratio-y+el.clientHeight/2,zoom);draw();notify();}
  function draw(){
    if(!args||el.clientWidth<20)return;
    el.dataset.viewport=JSON.stringify(viewport());el.dataset.zoom=String(zoom);
    const w=el.clientWidth,h=el.clientHeight,c=project(...center,zoom),z=Math.floor(zoom),scale=Math.pow(2,zoom-z),size=256*scale;
    const ox=c[0]-w/2,oy=c[1]-h/2,count=2**z,keep=new Set();
    if(args.tiles_enabled){
      for(let y=Math.floor(oy/size);y<=Math.floor((oy+h)/size);y++)for(let x=Math.floor(ox/size);x<=Math.floor((ox+w)/size);x++){
        if(y<0||y>=count||keep.size>=64)continue;
        const key=`${z}/${x}/${y}`;keep.add(key);let node=tileNodes.get(key);
        if(!node){node=document.createElement('img');node.className='tile';node.alt='';node.referrerPolicy='origin';node.draggable=false;node.onload=()=>{};node.onerror=()=>{node.style.visibility='hidden';if(!tileFailed){tileFailed=true;document.getElementById('notice').textContent=args.labels.tile_error;event('tile_error');}};node.src=`https://tile.openstreetmap.org/${z}/${((x%count)+count)%count}/${y}.png`;tiles.append(node);tileNodes.set(key,node);}
        Object.assign(node.style,{left:`${x*size-ox}px`,top:`${y*size-oy}px`,width:`${size+1}px`,height:`${size+1}px`});
      }
    }
    for(const [key,node] of tileNodes){if(!keep.has(key)){node.remove();tileNodes.delete(key);}}
    pins.replaceChildren();
    const rows=args.result.mode==='clusters'?[...args.result.clusters].sort((a,b)=>a.count-b.count):args.result.features;
    for(const p of rows){const xy=project(p.lon,p.lat,zoom);let dx=xy[0]-c[0];const s=world(zoom);if(dx>s/2)dx-=s;if(dx<-s/2)dx+=s;const x=w/2+dx,y=h/2+xy[1]-c[1];if(x<-30||x>w+30||y<-30||y>h+30)continue;
      const button=document.createElement('button');button.className='pin';button.style.left=`${x}px`;button.style.top=`${y}px`;button.dataset.placeId=p.id;
      if(args.result.mode==='clusters'){button.classList.add('cluster');button.textContent=String(p.count);button.setAttribute('aria-label',`${p.count} ${args.labels.cluster}`);button.onclick=()=>{const [a,b]=p.extent;let west=a.lon,east=b.lon;if(east<west)east+=360;const pad=Math.max(.003,(east-west)*.08),latPad=Math.max(.003,(b.lat-a.lat)*.08);fit([wrap(west-pad),Math.max(-85,a.lat-latPad),wrap(east+pad),Math.min(85,b.lat+latPad)]);draw();notify();};}
      else{button.classList.add(p.content_level||'basic');if(p.id===args.selected_id)button.classList.add('selected');if(args.saved_ids.includes(p.id))button.classList.add('saved');if(['closed','forbidden','prohibited','no_entry','restricted'].includes(p.access_status))button.classList.add('closed');button.title=p.name;button.setAttribute('aria-label',p.name);button.onclick=()=>{clearTimeout(timer);event('select',{id:p.id});};}
      pins.append(button);
    }
    document.getElementById('help').textContent=args.labels.help;
    if(!tileFailed)document.getElementById('notice').textContent=args.result.requires_zoom?args.labels.cluster_hint:(args.tiles_enabled?'':args.labels.no_tiles);
    send('streamlit:setFrameHeight',{height:el.clientHeight+30});
  }
  const local=e=>{const r=el.getBoundingClientRect();return [e.clientX-r.left,e.clientY-r.top];};
  el.addEventListener('pointerdown',e=>{if(e.target.closest('button,a'))return;el.focus({preventScroll:true});pointers.set(e.pointerId,local(e));el.setPointerCapture(e.pointerId);gesture=null;el.classList.add('dragging');});
  el.addEventListener('pointermove',e=>{if(!pointers.has(e.pointerId))return;const previous=pointers.get(e.pointerId),next=local(e);pointers.set(e.pointerId,next);if(pointers.size===1){const c=project(...center,zoom);center=unproject(c[0]-(next[0]-previous[0]),clamp(c[1]-(next[1]-previous[1]),0,world(zoom)),zoom);draw();}
    else{const [a,b]=[...pointers.values()],dist=Math.hypot(a[0]-b[0],a[1]-b[1]);if(gesture>1&&dist>1)zoomAt(zoom+Math.log2(dist/gesture),(a[0]+b[0])/2,(a[1]+b[1])/2);gesture=dist;} });
  for(const type of ['pointerup','pointercancel'])el.addEventListener(type,e=>{pointers.delete(e.pointerId);gesture=null;if(!pointers.size){el.classList.remove('dragging');notify();}});
  el.addEventListener('wheel',e=>{e.preventDefault();const [x,y]=local(e);zoomAt(zoom+(e.deltaY<0?.5:-.5),x,y);},{passive:false});
  el.addEventListener('keydown',e=>{if(e.target!==el)return;const moves={ArrowLeft:[-100,0],ArrowRight:[100,0],ArrowUp:[0,-100],ArrowDown:[0,100]};if(moves[e.key]){e.preventDefault();const c=project(...center,zoom),d=moves[e.key];center=unproject(c[0]+d[0],clamp(c[1]+d[1],0,world(zoom)),zoom);draw();notify();}else if(['+','=','-'].includes(e.key)){e.preventDefault();zoomAt(zoom+(e.key==='-'?-1:1));}});
  document.getElementById('plus').onclick=()=>zoomAt(zoom+1);document.getElementById('minus').onclick=()=>zoomAt(zoom-1);
  window.addEventListener('message',e=>{if(e.source!==window.parent||e.origin!==origin||e.data?.type!=='streamlit:render')return;args=e.data.args;el.setAttribute('aria-label',args.labels.map);renderCamera();});
  function renderCamera(){if(!args||el.clientWidth<20)return;if(!initialized){fit(args.bbox);initialized=true;notify();}if(args.camera&&args.camera.id!==cameraId){cameraId=args.camera.id;fit(args.camera.bbox,args.camera.padding??40);notify();}draw();}
  new ResizeObserver(()=>{renderCamera();if(initialized)notify();}).observe(el);
  send('streamlit:componentReady',{apiVersion:1});send('streamlit:setFrameHeight',{height:440});
})();

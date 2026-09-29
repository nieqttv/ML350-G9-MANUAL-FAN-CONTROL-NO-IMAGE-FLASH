
 let temperatureSheetCache={key:"",url:null};
 function temperatureSheet(sensors,lowerFanMissing){
  const live=sensors.filter(t=>Number.isFinite(t.celsius)),key=Number(lowerFanMissing)+"|"+live.map(t=>[t.name,t.x,t.y,t.celsius].join(":")).join("|");
  if(temperatureSheetCache.key===key)return temperatureSheetCache.url;
  if(!live.length)return null;
  const size=16,field=new Float64Array(256),fixed=new Uint8Array(256);
  for(let gy=0;gy<size;gy++)for(let gx=0;gx<size;gx++){
   let sum=0,weight=0;
   for(const t of live){const d=(gx-t.x)**2+(gy-t.y)**2,w=1/(d+.01);sum+=t.celsius*w;weight+=w;}
   field[gy*size+gx]=sum/weight;
  }
  for(const t of live){const i=t.y*size+t.x;field[i]=fixed[i]?Math.max(field[i],t.celsius):t.celsius;fixed[i]=1;}
  for(let iteration=0;iteration<240;iteration++){
   let delta=0;
   for(let gy=0;gy<size;gy++)for(let gx=0;gx<size;gx++){
    const i=gy*size+gx;if(fixed[i])continue;
    let sum=0,weight=0;
    const along=lowerFanMissing&&gx<4?.85:1.65,cross=.7;
    if(gx){sum+=field[i-1]*cross;weight+=cross;}if(gx<15){sum+=field[i+1]*cross;weight+=cross;}
    if(gy){sum+=field[i-16]*along*1.25;weight+=along*1.25;}
    if(gy<15){sum+=field[i+16]*along*.8;weight+=along*.8;}
    const next=sum/weight;delta=Math.max(delta,Math.abs(next-field[i]));field[i]=next;
   }
   if(delta<.005)break;
  }
  const spread=new Float64Array(field.length);
  for(let gy=0;gy<size;gy++)for(let gx=0;gx<size;gx++){
   const i=gy*size+gx;let sum=0,weight=0;
   const lower=lowerFanMissing&&gx<4;
   for(let dy=-2;dy<=2;dy++)for(let dx=-2;dx<=2;dx++){
    const w=Math.exp(-dx*dx/1.7-dy*dy/(lower?3.3:6))*(dy<0?(lower?1.1:1.4):1);
    const nx=Math.max(0,Math.min(15,gx+dx)),ny=Math.max(0,Math.min(15,gy+dy));
    sum+=field[ny*size+nx]*w;weight+=w;
   }
   spread[i]=fixed[i]?field[i]:field[i]*.5+sum/weight*.5;
  }
  const cubic=(a,b,c,d,t)=>b+.5*t*(c-a+t*(2*a-5*b+4*c-d+t*(3*(b-c)+d-a)));
  const get=(x,y)=>spread[Math.max(0,Math.min(15,y))*16+Math.max(0,Math.min(15,x))];
  const sample=(x,y)=>{
   x=Math.max(0,Math.min(15,x));y=Math.max(0,Math.min(15,y));
   const ix=Math.floor(x),iy=Math.floor(y),dx=x-ix,dy=y-iy,rows=[];
   for(let j=-1;j<=2;j++)rows.push(cubic(get(ix-1,iy+j),get(ix,iy+j),get(ix+1,iy+j),get(ix+2,iy+j),dx));
   return cubic(...rows,dy);
  };
  const stops=[[20,[47,79,110]],[40,[67,143,151]],[60,[174,192,135]],[75,[217,161,98]],[90,[193,87,77]]];
  const color=t=>{
   t=Math.max(20,Math.min(90,t));let i=1;while(i<stops.length-1&&t>stops[i][0])i++;
   const [a,ca]=stops[i-1],[b,cb]=stops[i],ratio=(t-a)/(b-a);return ca.map((v,k)=>Math.round(v+(cb[k]-v)*ratio));
  };
  const width=384,height=232,canvas=document.createElement("canvas");canvas.width=width;canvas.height=height;
  const context=canvas.getContext("2d");if(!context)return null;
  const pixels=context.createImageData(width,height);
  const minimum=Math.min(...live.map(t=>t.celsius)),maximum=Math.max(...live.map(t=>t.celsius));
  for(let py=0;py<height;py++)for(let px=0;px<width;px++){
   const value=Math.max(minimum,Math.min(maximum,sample(15.8-16.6*py/(height-1),15.8-16.6*px/(width-1)))),rgb=color(value),offset=(py*width+px)*4;
   pixels.data[offset]=rgb[0];pixels.data[offset+1]=rgb[1];pixels.data[offset+2]=rgb[2];pixels.data[offset+3]=255;
  }
  context.putImageData(pixels,0,0);
  temperatureSheetCache={key,url:canvas.toDataURL("image/png")};return temperatureSheetCache.url;
 }

 const selectedSensor=J(null);
 function temperatureMap(m){
  const hw=m.management||{},fresh=hw.iloConnected&&clock.value/1000-hw.sampledAt<45;
  const cpuFresh=fanStatus.value&&clock.value/1000-fanStatus.value.sampledAt<12;
  const sensors=(hw.temperatures||[]).map(t=>{
   const match=t.name.match(/^0[23]-CPU ([12])$/),sid=match?Number(match[1])-1:null;
   const host=cpuFresh?fanStatus.value.cpuTemperatures?.find(c=>c.id===sid):null;
   const socket=m.sockets?.find(c=>c.id===sid);
   const hostValue=host?.maximum??(clock.value/1000-m.sampledAt<10?socket?.temperature:null);
   return {...t,celsius:match?hostValue:(fresh?t.celsius:null),host:!!match,critical:match?(host?.critical??93):t.critical};
  });
  const located=sensors.filter(t=>Number.isInteger(t.x)&&Number.isInteger(t.y)&&t.x>=0&&t.x<=15&&t.y>=0&&t.y<=15);
  const missing=sensors.filter(t=>!located.includes(t));
  const selected=located.find(t=>t.name===selectedSensor.value)||located.reduce((a,b)=>!a||(b.celsius??-1)>(a.celsius??-1)?b:a,null);
  const short=t=>t.name.replace(/^\d+-/,"");


  const fanActive=n=>hw.fans?.some(f=>f.name==="Fan "+n&&Number(f.percent)>0);
  const lowerFanMissing=[1,2,3].every(fanActive)&&hw.fans?.some(f=>f.name==="Fan 4"&&Number(f.percent)===0);
  const sheet=fresh?temperatureSheet(located,lowerFanMissing):null;
  const heatsinks=located.filter(t=>/^0[23]-CPU [12]$/.test(t.name)).map(t=>{
   const x=28+(15.8-t.y)/16.6*904,y=28+(15.8-t.x)/16.6*544;
   return h("g",{class:"ts-map-heatsink",transform:"translate("+x+" "+y+")"},[
    h("rect",{x:-50,y:-37,width:100,height:74,rx:5}),
    ...[-24,-16,-8,0,8,16,24].map(offset=>h("path",{d:"M-42 "+offset+" H42"}))
   ]);
  });
  const pick=e=>{
   const rect=e.currentTarget.getBoundingClientRect(),px=(e.clientX-rect.left)/rect.width*960,py=(e.clientY-rect.top)/rect.height*600;
   const gx=15.8-16.6*(py-28)/544,gy=15.8-16.6*(px-28)/904;
   const nearest=located.reduce((a,b)=>!a||(b.x-gx)**2+(b.y-gy)**2<(a.x-gx)**2+(a.y-gy)**2?b:a,null);
   if(nearest)selectedSensor.value=nearest.name;
  };
  return h("section",{class:"ts-temperature-map","aria-label":"Server temperature map"},[
   h("div",{class:"ts-map-heading"},[h("div",{class:"ts-model"},"Temperature map"),h("span",{class:"ts-muted"},"ML350 Gen9")]),
   h("div",{class:"ts-map-scroll"},[
    h("div",{class:"ts-map-ends"},[h("span",null,"OUTLET / PCIe"),h("span",null,"FRONT / INLET")]),
    h("svg",{viewBox:"0 0 960 600",class:"ts-map-svg ts-map-sheet",role:"img",tabindex:0,"aria-label":"Continuous server temperature map, outlet and PCIe at left, front inlet at right",onPointermove:pick,onPointerdown:pick,onKeydown:e=>{
     if(!["ArrowRight","ArrowLeft","ArrowUp","ArrowDown"].includes(e.key))return;e.preventDefault();
     const index=located.findIndex(t=>t.name===selected?.name),step=e.key==="ArrowRight"||e.key==="ArrowDown"?1:-1;
     selectedSensor.value=located[(index+step+located.length)%located.length]?.name;
    }},[
     h("defs",null,[h("clipPath",{id:"ts-thermal-sheet-clip"},[h("rect",{x:28,y:28,width:904,height:544,rx:12})])]),
     h("rect",{x:27,y:27,width:906,height:546,rx:13,class:"ts-map-chassis"}),
     sheet?h("image",{href:sheet,x:28,y:28,width:904,height:544,preserveAspectRatio:"none","clip-path":"url(#ts-thermal-sheet-clip)"}):null,
     sheet?h("g",{class:"ts-map-outlines","aria-hidden":"true"},[
      h("path",{d:"M55 215 H505 C540 215 550 240 580 240 H904"}),
      h("path",{d:"M55 395 H505 C540 395 550 370 580 370 H904"}),
      ...heatsinks
     ]):null
    ])
   ]),
   h("div",{class:"ts-map-legend"},[h("span",null,"20°C"),h("span",{class:"ts-map-gradient"}),h("span",null,"90°C")]),
   selected?h("div",{class:"ts-map-detail","aria-live":"polite"},[
    h("div",null,[h("strong",null,short(selected)),h("span",{class:"ts-muted"},selected.host?"CPU package / cores":selected.location||"")]),
    h("strong",null,temp(selected.celsius))
   ]):h("div",{class:"ts-muted"},"Sensor positions unavailable"),
   h("select",{class:"ts-map-select","aria-label":"Temperature sensor",value:selected?.name,onChange:e=>selectedSensor.value=e.target.value},located.map(t=>h("option",{value:t.name},short(t)+" · "+temp(t.celsius)))),
   ...missing.map(t=>h("div",{class:"ts-sensor-row"},[h("span",null,short(t)),h("strong",null,temp(t.celsius))]))
  ]);
 }

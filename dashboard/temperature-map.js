
 let temperatureSheetCache={key:"",url:null};
 function temperatureSheet(sensors){
  const live=sensors.filter(t=>Number.isFinite(t.celsius)),key=live.map(t=>[t.name,t.x,t.y,t.celsius].join(":")).join("|");
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
    let sum=0,count=0;
    if(gx){sum+=field[i-1];count++;}if(gx<15){sum+=field[i+1];count++;}
    if(gy){sum+=field[i-16];count++;}if(gy<15){sum+=field[i+16];count++;}
    const next=sum/count;delta=Math.max(delta,Math.abs(next-field[i]));field[i]=next;
   }
   if(delta<.005)break;
  }
  const cubic=(a,b,c,d,t)=>b+.5*t*(c-a+t*(2*a-5*b+4*c-d+t*(3*(b-c)+d-a)));
  const get=(x,y)=>field[Math.max(0,Math.min(15,y))*16+Math.max(0,Math.min(15,x))];
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
  const canvas=document.createElement("canvas");canvas.width=canvas.height=256;
  const context=canvas.getContext("2d");if(!context)return null;
  const pixels=context.createImageData(256,256);
  const minimum=Math.min(...live.map(t=>t.celsius)),maximum=Math.max(...live.map(t=>t.celsius));
  for(let py=0;py<256;py++)for(let px=0;px<256;px++){
   const value=Math.max(minimum,Math.min(maximum,sample(-.8+16.6*px/255,15.8-16.6*py/255))),rgb=color(value),offset=(py*256+px)*4;
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
  const x=t=>60+t.x*40,y=t=>660-t.y*40;
  const color=t=>!Number.isFinite(t)?"var(--taelo-text2)":t<45?"#67a99e":t<65?"#b8ad78":t<80?"#ce975f":"#d8786d";
  const short=t=>t.name.replace(/^\d+-/,"");


  const sheet=fresh?temperatureSheet(located):null;
  const pick=e=>{
   const rect=e.currentTarget.getBoundingClientRect(),gx=((e.clientX-rect.left)/rect.width*720-60)/40,gy=(660-(e.clientY-rect.top)/rect.height*720)/40;
   const nearest=located.reduce((a,b)=>!a||(b.x-gx)**2+(b.y-gy)**2<(a.x-gx)**2+(a.y-gy)**2?b:a,null);
   if(nearest)selectedSensor.value=nearest.name;
  };
  return h("section",{class:"ts-temperature-map","aria-label":"Server temperature map"},[
   h("div",{class:"ts-map-heading"},[h("div",{class:"ts-model"},"Temperature map"),h("span",{class:"ts-muted"},"ML350 Gen9")]),
   h("div",{class:"ts-map-scroll"},[
    h("svg",{viewBox:"0 0 720 720",class:"ts-map-svg ts-map-sheet",role:"img",tabindex:0,"aria-label":"Continuous server temperature map, front at bottom and rear at top",onPointermove:pick,onPointerdown:pick,onKeydown:e=>{
     if(!["ArrowRight","ArrowLeft","ArrowUp","ArrowDown"].includes(e.key))return;e.preventDefault();
     const index=located.findIndex(t=>t.name===selected?.name),step=e.key==="ArrowRight"||e.key==="ArrowDown"?1:-1;
     selectedSensor.value=located[(index+step+located.length)%located.length]?.name;
    }},[
     h("defs",null,[h("clipPath",{id:"ts-thermal-sheet-clip"},[h("rect",{x:28,y:28,width:664,height:664,rx:12})])]),
     h("rect",{x:27,y:27,width:666,height:666,rx:13,class:"ts-map-chassis"}),
     sheet?h("image",{href:sheet,x:28,y:28,width:664,height:664,preserveAspectRatio:"none","clip-path":"url(#ts-thermal-sheet-clip)"}):null,
     h("text",{x:360,y:18,"text-anchor":"middle",class:"ts-map-edge"},"REAR"),
     h("text",{x:360,y:716,"text-anchor":"middle",class:"ts-map-edge"},"FRONT")
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


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

  const label=t=>{
   const n=short(t);
   if(/^CPU [12]$/.test(n))return n;
   if(n.includes("DIMM"))return n.split(" ")[0]+" DIMM";
   if(n.startsWith("PCI "))return n.replace(" Zone","");
   if(n==="Inlet Ambient")return "INLET";
   if(n==="Sys Exhaust")return "EXHAUST";
   if(n==="Storage Batt")return "BATTERY";
   if(n.startsWith("P/S"))return n.replace("P/S ","PSU ");
   if(n==="Chipset Zone")return "CHIP Z";
   if(n==="Chipset")return "CHIP";
   if(n==="iLO Zone")return "iLO";
   if(n.includes("Mem"))return n.replace("VR ","").replace(" Mem "," VR");
   return n.replace("VR ","").replace(" Zone"," Z")+" VR";
  };
  const dimensions=t=>{
   const n=short(t);
   return /^CPU [12]$/.test(n)?[72,48]:n.includes("DIMM")?[64,44]:/INLET|EXHAUST|BATTERY/.test(label(t))?[82,44]:n.startsWith("P/S")?[58,44]:/^VR P[12]$/.test(n)?[58,36]:[34,34];
  };
  return h("section",{class:"ts-temperature-map","aria-label":"Server temperature map"},[
   h("div",{class:"ts-map-heading"},[h("div",{class:"ts-model"},"Temperature map"),h("span",{class:"ts-muted"},"ML350 Gen9")]),
   h("div",{class:"ts-map-scroll"},[
    h("svg",{viewBox:"0 0 720 720",class:"ts-map-svg ts-map-schematic",role:"group","aria-label":"ML350 Gen9 sensor layout. Front at the bottom, rear at the top."},[
     h("rect",{x:28,y:28,width:664,height:664,rx:16,class:"ts-map-chassis"}),
     h("rect",{x:40,y:82,width:640,height:406,rx:10,class:"ts-map-board"}),
     h("text",{x:360,y:18,"text-anchor":"middle",class:"ts-map-edge"},"REAR"),
     h("text",{x:360,y:716,"text-anchor":"middle",class:"ts-map-edge"},"FRONT"),
     ...[180,360,540].map(cx=>h("path",{d:"M"+cx+" 596V548m-5 6 5-6 5 6",class:"ts-map-airflow"})),
     ...located.map(t=>{
      const [w,ht]=dimensions(t),cx=x(t),cy=y(t),cpu=/^CPU [12]$/.test(short(t));
      return h("g",{key:t.name,role:"button",tabindex:0,"aria-label":short(t)+": "+temp(t.celsius),"aria-pressed":selected?.name===t.name,class:"ts-map-node"+(selected?.name===t.name?" is-selected":""),onMouseenter:()=>selectedSensor.value=t.name,onFocus:()=>selectedSensor.value=t.name,onClick:()=>selectedSensor.value=t.name,onKeydown:e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();selectedSensor.value=t.name;}}},[
       h("title",null,short(t)+" · "+temp(t.celsius)),
       cpu?h("rect",{x:cx-w/2-4,y:cy-ht/2-4,width:w+8,height:ht+8,rx:4,class:"ts-map-socket"}):null,
       h("rect",{x:cx-w/2,y:cy-ht/2,width:w,height:ht,rx:4,class:"ts-map-chip"}),
       h("text",{x:cx,y:cy-(cpu?7:5),"text-anchor":"middle",class:"ts-map-chip-label",style:{fontSize:cpu?"10px":w>50?"9px":"6.8px"}},label(t)),
       h("text",{x:cx,y:cy+(cpu?13:10),"text-anchor":"middle",class:"ts-map-chip-value",style:{fontSize:cpu?"18px":w>50?"15px":"12px"}},Number.isFinite(t.celsius)?Math.round(t.celsius)+"°":"—"),
       h("rect",{x:cx-w/2+5,y:cy+ht/2-3,width:w-10,height:1.5,rx:.7,fill:color(t.celsius)})
      ]);
     })
    ])
   ]),
   selected?h("div",{class:"ts-map-detail","aria-live":"polite"},[
    h("div",null,[h("strong",null,short(selected)),h("span",{class:"ts-muted"},selected.host?"CPU package / cores":selected.location||"")]),
    h("strong",null,temp(selected.celsius))
   ]):h("div",{class:"ts-muted"},"Sensor positions unavailable"),
   h("select",{class:"ts-map-select","aria-label":"Temperature sensor",value:selected?.name,onChange:e=>selectedSensor.value=e.target.value},located.map(t=>h("option",{value:t.name},short(t)+" · "+temp(t.celsius)))),
   ...missing.map(t=>h("div",{class:"ts-sensor-row"},[h("span",null,short(t)),h("strong",null,temp(t.celsius))]))
  ]);
 }

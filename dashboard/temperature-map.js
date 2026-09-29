
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
  return h("section",{class:"ts-temperature-map","aria-label":"Server temperature map"},[
   h("div",{class:"ts-map-heading"},[h("div",{class:"ts-model"},"Temperature map"),h("span",{class:"ts-muted"},located.length+" sensors")]),
   h("div",{class:"ts-map-scroll"},[
    h("svg",{viewBox:"0 0 720 720",class:"ts-map-svg",role:"group","aria-label":"ML350 Gen9 sensor positions. Front at the bottom, rear at the top."},[
     h("defs",null,located.map((t,i)=>h("radialGradient",{id:"ts-heat-"+i},[h("stop",{offset:"0%","stop-color":color(t.celsius),"stop-opacity":".28"}),h("stop",{offset:"100%","stop-color":color(t.celsius),"stop-opacity":"0"})]))),
     h("rect",{x:28,y:28,width:664,height:664,rx:24,class:"ts-map-chassis"}),
     ...[0,3,6,9,12,15].flatMap(v=>[h("line",{x1:60+v*40,x2:60+v*40,y1:60,y2:660,class:"ts-map-grid"}),h("line",{x1:60,x2:660,y1:60+v*40,y2:60+v*40,class:"ts-map-grid"})]),
     h("text",{x:360,y:18,"text-anchor":"middle",class:"ts-map-edge"},"REAR"),
     h("text",{x:360,y:716,"text-anchor":"middle",class:"ts-map-edge"},"FRONT"),
     ...located.filter(t=>Number.isFinite(t.celsius)).map(t=>h("circle",{cx:x(t),cy:y(t),r:84,fill:"url(#ts-heat-"+located.indexOf(t)+")","pointer-events":"none"})),
     ...located.map(t=>h("g",{key:t.name,role:"button",tabindex:0,"aria-label":short(t)+": "+temp(t.celsius),"aria-pressed":selected?.name===t.name,class:"ts-map-node"+(selected?.name===t.name?" is-selected":""),onMouseenter:()=>selectedSensor.value=t.name,onFocus:()=>selectedSensor.value=t.name,onClick:()=>selectedSensor.value=t.name,onKeydown:e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();selectedSensor.value=t.name;}}},[
      h("title",null,short(t)+" · "+temp(t.celsius)),
      h("circle",{cx:x(t),cy:y(t),r:18,fill:"var(--taelo-surface)",stroke:color(t.celsius),"stroke-width":selected?.name===t.name?3:1.5}),
      h("text",{x:x(t),y:y(t)+4,"text-anchor":"middle",class:"ts-map-reading"},Number.isFinite(t.celsius)?Math.round(t.celsius)+"°":"—")
     ]))
    ])
   ]),
   selected?h("div",{class:"ts-map-detail","aria-live":"polite"},[
    h("div",null,[h("strong",null,short(selected)),h("span",{class:"ts-muted"},selected.host?"CPU package / cores":selected.location||"")]),
    h("strong",{style:{color:color(selected.celsius)}},temp(selected.celsius))
   ]):h("div",{class:"ts-muted"},"Sensor positions unavailable"),
   h("select",{class:"ts-map-select","aria-label":"Temperature sensor",value:selected?.name,onChange:e=>selectedSensor.value=e.target.value},located.map(t=>h("option",{value:t.name},short(t)+" · "+temp(t.celsius)))),
   h("div",{class:"ts-map-legend"},[h("span",null,"20°C"),h("span",{class:"ts-map-gradient"}),h("span",null,"90°C")]),
   ...missing.map(t=>h("div",{class:"ts-sensor-row"},[h("span",null,short(t)),h("strong",null,temp(t.celsius))]))
  ]);
 }

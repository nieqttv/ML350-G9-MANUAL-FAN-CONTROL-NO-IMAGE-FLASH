
 const fanStatus=J(null),fanDraft=J(21),fanPending=J(null),fanError=J("");
 const fanView=J("manual"),curveDraft=J([[40,20],[50,30],[60,45],[70,65],[80,100]]),curveDirty=J(false);
 let fanReadBusy=false,fanEditing=false,fanHydrated=false;
 async function refreshFan(){
  if(fanReadBusy||disposed||!isAdmin())return;
  fanReadBusy=true;
  try{
   const r=await Ji.getCurrentUserCustom("taelo_fan_control",{headers:{"Cache-Control":"no-cache"}}),v=r.data.data;
   if(v?.version!==3)throw Error("Invalid fan status");
   if(disposed)return;fanStatus.value=v;
   if(!fanHydrated){fanView.value=v.mode==="curve"?"curve":"manual";fanHydrated=true;}
   if(fanPending.value&&v.ack?.id===fanPending.value.id){fanError.value=v.ack.ok?"":v.ack.error||"Fan change failed";if(v.ack.ok&&fanPending.value.mode==="curve")curveDirty.value=false;fanPending.value=null;}
   if(fanPending.value&&Date.now()-fanPending.value.sentAt>18000){fanError.value="Change not confirmed";fanPending.value=null;}
   if(!fanEditing&&!fanPending.value)fanDraft.value=v.targetPercent??Math.round(v.fans?.[0]?.percent||21);
   if(!curveDirty.value&&!fanPending.value&&v.curve)curveDraft.value=v.curve.map(p=>[...p]);
  }catch{if(!disposed)fanError.value="Fan controls unavailable";}
  finally{fanReadBusy=false;}
 }
 async function sendFan(command){
  if(fanPending.value||!isAdmin())return;
  const id=Date.now().toString(36)+"-"+Math.random().toString(36).slice(2);
  fanPending.value={id,sentAt:Date.now(),mode:command.mode};fanError.value="";fanEditing=false;
  try{await Ji.uploadUserCustom("taelo_fan_request",{data:{id,createdAt:Date.now()/1000,...command}});await refreshFan();}
  catch{fanPending.value=null;fanError.value="Could not send fan change";}
 }
 function setFan(output,mode="percentage"){fanDraft.value=output;return sendFan({output,mode});}
 function curveProblem(){
  const p=curveDraft.value;
  if(p.some((v,i)=>v.some(x=>!Number.isInteger(x))||v[0]<20||v[0]>85||v[1]<1||v[1]>100||(i&&(v[0]<=p[i-1][0]||v[1]<p[i-1][1]))))return "Use rising temperatures (20–85°C) and nondecreasing fan speeds (1–100%).";
  return p.at(-1)[1]!==100?"The final point must reach 100%.":"";
 }
 function curveChart(){
  const p=curveDraft.value,fx=t=>38+(t-20)/65*444,fy=v=>166-v*1.36;
  const points=p.filter(v=>v.every(Number.isFinite)),path=points.map((v,i)=>(i?"L":"M")+fx(v[0])+","+fy(v[1])).join(" ");
  const f=fanStatus.value,live=f?.curveTemperature,output=f?.targetPercent;
  return h("svg",{class:"ts-curve-chart",viewBox:"0 0 510 194",role:"img","aria-label":"Fan curve: CPU temperature in degrees Celsius against fan speed percentage"},[
   ...[25,50,75,100].flatMap(v=>[h("line",{x1:38,x2:482,y1:fy(v),y2:fy(v),class:"ts-curve-grid"}),h("text",{x:30,y:fy(v)+4,"text-anchor":"end"},v+"%")]),
   ...[20,40,60,80].map(t=>h("text",{x:fx(t),y:186,"text-anchor":"middle"},t+"°")),
   h("path",{d:path,class:"ts-curve-line"}),
   ...points.map((v,i)=>h("circle",{cx:fx(v[0]),cy:fy(v[1]),r:4,class:"ts-curve-point"})),
   Number.isFinite(live)&&Number.isFinite(output)?h("circle",{cx:fx(Math.max(20,Math.min(85,live))),cy:fy(output),r:6,class:"ts-curve-live"}):null
  ]);
 }
 function fanControl(){
  const f=fanStatus.value,live=f&&clock.value/1000-f.updatedAt<12,ready=live&&f.ready&&f.boostAvailable,disabled=!ready||!!fanPending.value;
  const change=e=>{const value=Number(e.target.value);if(Number.isInteger(value)&&value>=1&&value<=100)setFan(value);else{fanError.value="Enter 1–100%";fanEditing=false;}};
  const problem=curveProblem();
  const editPoint=(i,k,value)=>{curveDirty.value=true;const p=curveDraft.value.map(v=>[...v]);p[i][k]=value===""?null:Number(value);curveDraft.value=p;};
  return h("div",{class:"ts-fan-control"},[
   h("div",{class:"ts-fan-heading"},[
    h("span",null,"Fan control"),
    h("div",{class:"ts-fan-mode",role:"group","aria-label":"Fan control editor"},["manual","curve"].map(mode=>h("button",{type:"button",class:fanView.value===mode?"is-active":"","aria-pressed":fanView.value===mode,onClick:()=>fanView.value=mode},mode==="manual"?"Manual":"Curve")))
   ]),
   fanView.value==="manual"?h("div",null,[
    h("div",{class:"ts-fan-heading ts-fan-speed"},[
     h("label",{for:"taelo-fan-output"},"Fan speed"),
     h("div",{class:"ts-fan-value"},[
      h("input",{type:"number",min:1,max:100,step:1,value:fanDraft.value,disabled,"aria-label":"Fan speed percentage",onFocus:()=>{fanEditing=true;},onInput:e=>{fanEditing=true;fanDraft.value=e.target.value;},onChange:change,onBlur:()=>{fanEditing=false;}}),h("span",null,"%")
     ])
    ]),
    h("input",{id:"taelo-fan-output",type:"range",min:1,max:100,step:1,value:fanDraft.value,disabled,"aria-label":"Fan speed","aria-valuetext":fanDraft.value+" percent",onInput:e=>{fanEditing=true;fanDraft.value=Number(e.target.value);},onChange:change,onBlur:()=>{fanEditing=false;}})
   ]):h("div",{class:"ts-curve-editor"},[
    h("div",{class:"ts-curve-cpus"},(f?.cpuTemperatures||[]).map(c=>h("span",null,["CPU "+(c.id+1),h("strong",null,c.maximum.toFixed(0)+"°C")]))),
    curveChart(),
    h("div",{class:"ts-curve-points"},curveDraft.value.map((p,i)=>h("div",{class:"ts-curve-edit",key:i},[
     h("span",{class:"ts-muted"},"Point "+(i+1)),
     h("label",null,[h("input",{type:"number",min:20,max:85,step:1,value:p[0],"aria-label":"Point "+(i+1)+" temperature",disabled:!!fanPending.value,onInput:e=>editPoint(i,0,e.target.value)}),h("span",null,"°C")]),
     h("label",null,[h("input",{type:"number",min:1,max:100,step:1,value:p[1],"aria-label":"Point "+(i+1)+" fan speed",disabled:!!fanPending.value,onInput:e=>editPoint(i,1,e.target.value)}),h("span",null,"%")])
    ]))),
    problem?h("div",{class:"ts-warning",role:"status"},problem):null,
    h("div",{class:"ts-curve-source"},[h("span",{class:"ts-muted"},"Hottest CPU · "+(Number.isFinite(f?.curveTemperature)?f.curveTemperature.toFixed(0)+"°C":"—")),h("button",{type:"button",class:"ts-fan-default",disabled:disabled||!!problem,onClick:()=>sendFan({mode:"curve",curve:curveDraft.value.map(p=>[...p])})},f?.curveActive?"Save curve":"Apply curve")])
   ]),
   h("div",{class:"ts-fan-actions"},[
    h("span",{class:"ts-muted",role:"status"},fanPending.value?"Applying…":f?.restoreNeeded?"Restoring default…":f?.curveActive?"Curve · "+f.targetPercent+"%":f?.boostActive?"Manual · "+f.targetPercent+"%":"Automatic"),
    h("button",{type:"button",class:"ts-fan-default",disabled:!!fanPending.value,onClick:()=>setFan(100,"automatic")},"Default")
   ]),
   fanError.value||f?.error?h("div",{class:"ts-warning",role:"alert"},fanError.value||f.error):null,
   !ready&&!fanError.value&&!f?.error?h("div",{class:"ts-muted"},"Controls unavailable"):null
  ]);
 }

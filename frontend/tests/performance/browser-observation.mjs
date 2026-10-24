/** Date-only fixture clock. Do not use Playwright clock: it replaces performance entries and timers. */
export function installDateOnlyClock(epoch) {
 const NativeDate=globalThis.Date;
 const fixed=Number(epoch);
 if(!Number.isFinite(fixed))throw Error('Invalid synthetic wall clock');
 globalThis.Date=new Proxy(NativeDate,{
  construct(target,args,newTarget){return Reflect.construct(target,args.length?args:[fixed],newTarget);},
  apply(){return new NativeDate(fixed).toString();},
  get(target,key,receiver){return key==='now'?()=>fixed:Reflect.get(target,key,receiver);},
 });
}
/** Runs before application scripts; records native visible-geometry DOM-ready times, not driver polling time. */
export function observeBrowser() {
 performance.setResourceTimingBufferSize(2000);
 window.__perf={pending:0,started:0,longTasks:[],markers:{}};
 try{new PerformanceObserver(list=>window.__perf.longTasks.push(...list.getEntries().map(e=>({startTime:e.startTime,duration:e.duration})))).observe({type:'longtask',buffered:true});}catch{}
 const nativeFetch=window.fetch.bind(window);
 window.fetch=async(...args)=>{window.__perf.pending++;window.__perf.started++;try{const response=await nativeFetch(...args);for(const method of ['json','text','arrayBuffer','blob']){const read=response[method].bind(response);response[method]=async(...values)=>{window.__perf.pending++;try{return await read(...values);}finally{window.__perf.pending--;}};}return response;}finally{window.__perf.pending--;}};
 const needles=[['daily','合成基准指数'],['stock-600001','合成证券 600001'],['stock-600002','合成证券 600002'],['news-600001','合成主资讯 600001'],['sectors','板块中心'],['pcb','AI 服务器用 PCB 可理解为 AI 机柜内的电气互连骨架']];
 function settleMarker(marker,attempt=0){
  if(attempt>300)return;
  const started=window.__perf.started;
  requestAnimationFrame(()=>requestAnimationFrame(()=>{
   if(window.__perf.pending===0&&window.__perf.started===started)marker.uiSettledAt=performance.now();
   else settleMarker(marker,attempt+1);
  }));
 }
 function inspect(){
  for(const [key,needle]of needles){
   if(window.__perf.markers[key])continue;
   const node=[...document.querySelectorAll('h1,h2,h3,p,a,span')].find(e=>(key==='pcb'?e.textContent.startsWith(needle):e.textContent===needle)&&e.getClientRects().length>0&&e.getBoundingClientRect().width>0&&e.getBoundingClientRect().height>0&&getComputedStyle(e).visibility==='visible');
   if(node){const marker={at:performance.now(),uiSettledAt:null};window.__perf.markers[key]=marker;settleMarker(marker);}
  }
 }
 new MutationObserver(inspect).observe(document,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['hidden','style','class']});
 document.addEventListener('DOMContentLoaded',inspect,{once:true});
}
export function assertNativeTelemetry(row) {
 const documentFlow=/cold|reload|document/.test(row.name);
 if(!Number.isFinite(row.firstUsefulMs)||row.firstUsefulMs<0)throw Error('Missing native visible-content timestamp');
 if(!Number.isFinite(row.uiSettledMs)||row.uiSettledMs<row.firstUsefulMs)throw Error('Missing native UI-settle timestamp');
 if(documentFlow){
  if(!row.navigation||!Number.isFinite(row.navigation.responseEnd))throw Error('Missing native navigation timing');
  if(!row.requests.some(r=>r.path.endsWith('.js')&&r.decodedBytes>0))throw Error('Missing native JavaScript resource timings');
  if(!row.paints.some(p=>p.name==='first-contentful-paint'&&p.startTime>0))throw Error('Missing native FCP timing');
 }
 if(row.name==='daily-cold'&&(!row.requests.some(r=>r.path==='/api/daily-review')||row.fetchStarted<1))throw Error('Missing real synthetic API request observation');
}

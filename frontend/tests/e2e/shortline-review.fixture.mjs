import {readFileSync} from 'node:fs';
import {isDeepStrictEqual} from 'node:util';
export const golden=JSON.parse(readFileSync(new URL('../fixtures/shortline-review-browser.json',import.meta.url),'utf8'));
export const DAY='2026-07-31';
export function createShortlineFixture(origin){
 const calls=[],violations=[],saved=new Map();let scenario='daily',malformed=false;
 const deny=reason=>{violations.push(reason);return {kind:'deny'};};
 return {calls,violations,saved,setScenario:value=>{if(!Object.hasOwn(golden,value))throw Error('unknown scenario');scenario=value;},malformedNext:()=>{malformed=true;},
 handle(raw,method='GET',body){
 const u=new URL(raw);if(!u.pathname.startsWith('/api/shortline-review/'))return null;
 calls.push({path:u.pathname,search:u.search,method,body});if(u.origin!==origin)return deny('wrong origin');
 if(method==='GET'&&u.pathname==='/api/shortline-review/versions'){
  const date=['2026-07-31','2026-07-30','2026-07-29'].find(d=>['daily','weekly'].some(m=>u.search===`?trade_date=${d}&mode=${m}`));
  if(!date)return deny('bad versions query');const mode=u.searchParams.get('mode');
  return {kind:'json',body:{data:[...saved.values()].filter(v=>v.trade_date===date&&v.mode===mode).map(({generation_id,mode,trade_date,created_at,status})=>({generation_id,mode,trade_date,created_at,status}))}};
 }
 if(method==='GET'&&u.pathname==='/api/shortline-review/preview'&&u.search===`?trade_date=${DAY}&mode=${golden[scenario].preview.mode}`)return {kind:'json',body:{data:structuredClone(golden[scenario].preview)}};
 if(method==='GET'&&/^\/api\/shortline-review\/version\/[a-f0-9]{32}$/.test(u.pathname)&&!u.search){
  const v=saved.get(u.pathname.split('/').at(-1));if(!v)return deny('unknown version');const value=structuredClone(v);if(malformed){malformed=false;value.bundle.trade_date='2026-07-30';}return {kind:'json',body:{data:value}};
 }
 if(method==='POST'&&u.pathname==='/api/shortline-review/generate'&&!u.search){
  const g=golden[scenario];if(!g.events||!body||!/^[a-f0-9]{32}$/.test(body.generation_id))return deny('invalid generation');
  const expected={trade_date:DAY,mode:g.preview.mode,bundle_id:g.preview.bundle_id,generation_id:body.generation_id,llm:{provider:'cli-codex',baseURL:'',apiKey:'',model:'SYNTHETIC_OFFLINE'}};
  if(!isDeepStrictEqual(body,expected)||saved.has(body.generation_id))return deny('generation payload mismatch');
  const events=structuredClone(g.events);for(const e of events)if(e.type==='done')e.generation_id=body.generation_id;
  const version=structuredClone(g.version);version.generation_id=body.generation_id;
  return {kind:'stream',body:events.map(e=>JSON.stringify(e)).join('\n')+'\n',commit:()=>saved.set(version.generation_id,version)};
 }
 return deny('unexpected shortline request');
 }};
}

import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import { readFileSync } from 'node:fs';
import * as filing from '../src/lib/filingEvidence.ts';
const evidence = { id:'evidence-one', edit_token:'current-token' };
const doc = id => ({id,evidence_id:evidence.id,issuer:'600519',form:'10-K',source_title:`Report ${id}`,source_identity:'user-file',revision:id,source_date:null,source_url:'javascript:alert(1)',sha256:`hash-${id}`,sections:[{key:'document',title:'Full text'}],warnings:[]});
const context = documents => ({documents,original_text_status:documents.length?'REGISTERED_UNVERIFIED':'UNAVAILABLE'});
const nodes = t => t==null||typeof t!=='object'?[]:Array.isArray(t)?t.flatMap(nodes):[t,...nodes(t.props?.children)];
const text = t => t==null||typeof t==='boolean'?'':typeof t!=='object'?String(t):Array.isArray(t)?t.map(text).join(''):text(t.props?.children);
const button = (t,label) => nodes(t).find(n=>n.type==='button'&&text(n).includes(label));
const field = (t,label) => nodes(t).find(n=>n.props?.['aria-label']===label);
const tick = () => new Promise(r=>setImmediate(r));
function harness(request) {
  const slots=[],calls=[];let cursor=0;let pending=[];
  const react={
    useState(init){const i=cursor++;if(!(i in slots))slots[i]=init;return[slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v;}];},
    useRef(init){const i=cursor++;return slots[i]??={current:init};},
    useEffect(effect,deps){const i=cursor++;const old=slots[i];if(!old||deps.some((d,j)=>d!==old.deps[j]))pending.push(()=>{old?.cleanup?.();slots[i]={deps,cleanup:effect()};});},
  };
  const exports={};const mods={react,'react/jsx-runtime':{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})},'@/lib/filingEvidence':{...filing,filingRequest:async(...args)=>{calls.push(args);return request(...args);}}};
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/components/research/FilingEvidenceCard.tsx',import.meta.url),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports,require:n=>mods[n],Error,URL});
  return {calls,unmount(){for(const slot of slots)slot?.cleanup?.();},render(){cursor=0;pending=[];const result=exports.FilingEvidenceCard({evidence});pending.forEach(f=>f());return result;}};
}
function fill(h,label,value){field(h.render(),label).props.onChange({target:{value}});}
test('registration is explicit, cancelled form never writes, duplicate click sends one immutable registration',async()=>{
  const h=harness(async path=>path.startsWith('/context/')?context([]):doc('one'));
  h.render();await tick();assert.match(text(h.render()),/原始文档不可用/);assert.equal(h.calls.length,1);
  button(h.render(),'登记用户原文').props.onClick();fill(h,'原文','Discard');button(h.render(),'取消登记').props.onClick();assert.equal(h.calls.length,1);
  button(h.render(),'登记用户原文').props.onClick();
  fill(h,'来源文档身份（如本地文件名/登记编号）','local.txt');fill(h,'版本标识','v1');fill(h,'来源标题','Annual report');fill(h,'原文','Sales\t1,234.00\n<script>no execution</script>');
  const save=button(h.render(),'确认保存未核验原文');save.props.onClick();save.props.onClick();await tick();
  const writes=h.calls.filter(c=>c[0].startsWith('/documents/'));
  assert.equal(writes.length,1);assert.equal(writes[0][1].expected_edit_token,'current-token');assert.equal(writes[0][1].source_date,null);assert.match(writes[0][1].text,/1,234.00/);
});
test('actual card renders original text safely, hides unsafe source jump, and closes detail',async()=>{
  const h=harness(async path=>path.startsWith('/context/')?context([doc('one')]):{...doc('one'),text:'<script>alert(1)</script>\n1\t2'});
  h.render();await tick();button(h.render(),'查看保留原文').props.onClick();await tick();
  const tree=h.render();assert.ok(nodes(tree).some(n=>n.type==='pre'&&n.props.children.includes('<script>')));
  assert.equal(nodes(tree).some(n=>n.type==='script'||n.props?.dangerouslySetInnerHTML||n.type==='a'),false);
  button(tree,'关闭原文').props.onClick();assert.equal(nodes(h.render()).some(n=>n.type==='pre'),false);
});
test('comparison highlights exact before and after and selection changes clear result',async()=>{
  const h=harness(async path=>path.startsWith('/context/')?context([doc('one'),doc('two')]):{before:{sha256:'old'},after:{sha256:'new'},changes:[{kind:'replace',before:'100\t200\n',after:'100\t300\n'}]});
  h.render();await tick();fill(h,'旧文档','one');fill(h,'新文档','two');button(h.render(),'比较原文差异').props.onClick();await tick();
  assert.match(text(h.render()),/非模型推断/);assert.match(text(h.render()),/100\t200/);assert.match(text(h.render()),/100\t300/);
  fill(h,'新文档','one');assert.equal(field(h.render(),'原文差异结果'),undefined);assert.equal(button(h.render(),'比较原文差异').props.disabled,true);
});
test('late read after navigation/unmount cannot display old original text',async()=>{
  let finish;const h=harness(path=>path.startsWith('/context/')?Promise.resolve(context([doc('one')])):new Promise(r=>{finish=r;}));
  h.render();await tick();button(h.render(),'查看保留原文').props.onClick();h.unmount();finish({...doc('one'),text:'late original'});await tick();assert.doesNotMatch(text(h.render()),/late original/);
});
test('write conflict stays visible without automatic retry or fabricated result',async()=>{
  const h=harness(async path=>{if(path.startsWith('/context/'))return context([]);throw Error('证据已变化，请刷新');});
  h.render();await tick();button(h.render(),'登记用户原文').props.onClick();fill(h,'来源文档身份（如本地文件名/登记编号）','local');fill(h,'版本标识','v1');fill(h,'来源标题','Title');fill(h,'原文','text');button(h.render(),'确认保存未核验原文').props.onClick();await tick();assert.match(text(h.render()),/证据已变化/);assert.equal(h.calls.filter(c=>c[0].startsWith('/documents/')).length,1);
});

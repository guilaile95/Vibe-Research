import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import * as annotations from '../src/lib/researchAnnotations.ts';
const source=readFileSync(new URL('../src/components/ui/ResearchAnnotationPanel.tsx',import.meta.url),'utf8');
const context={code:'000001',bar_period:'day',snapshot_id:'a'.repeat(64),token:'b'.repeat(64),expires_at:'2026-10-20T00:00:00+00:00',points:[['2026-10-16','10','12','9','11','20']]};
const row={id:'note',code:'000001',bar_period:'day',snapshot_id:context.snapshot_id,date:'2026-10-16',text:'<img src=x onerror=alert(1)>',price:0,link_kind:null,link_id:null,created_at:'2026-10-19'};
const label=x=>x==null?'':typeof x==='object'?Array.isArray(x)?x.map(label).join(' '):label(x.props?.children):String(x);
const nodes=x=>!x||typeof x!=='object'?[]:Array.isArray(x)?x.flatMap(nodes):[x,...nodes(x.props?.children)];
function harness(props={code:'000001',context,selectedDate:'2026-10-16',dates:['2026-10-16']}) {
 const slots=[],effects=[],calls=[];let cursor=0,pending=[],tree;
 const hooks={useState(initial){const i=cursor++;if(!(i in slots))slots[i]=initial;return [slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v;}];},useRef(initial){const i=cursor++;return slots[i]??(slots[i]={current:initial});},useEffect(fn,deps){const i=cursor++;if(!effects[i]||deps.some((d,j)=>d!==effects[i].deps[j]))pending.push(()=>{effects[i]?.cleanup?.();effects[i]={deps,cleanup:fn()};});}};
 const request=(...args)=>new Promise((resolve,reject)=>calls.push({args,resolve,reject}));
 const exports={};const jsx=(type,props)=>typeof type==='function'?type(props):({type,props});
 const mods={'react':hooks,'react/jsx-runtime':{jsx,jsxs:jsx},'react-router-dom':{Link:props=>jsx('a',{...props,href:props.to})},'@/lib/api':{request},'@/lib/researchAnnotations':annotations};
 vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2020}}).outputText,{exports,require:n=>mods[n],AbortController});
 return {calls,render(next=props){props=next;cursor=0;tree=exports.ResearchAnnotationPanel(props);const queued=pending;pending=[];queued.forEach(f=>f());return tree;},get tree(){return tree;},button(text){return nodes(tree).find(x=>x.type==='button'&&label(x)===text);},input(type){return nodes(tree).find(x=>x.type===type);},unmount(){effects.forEach(x=>x?.cleanup?.());}};
}
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
function real(x,key='root'){if(x==null||typeof x!=='object')return x;if(Array.isArray(x))return x.map((v,i)=>real(v,String(i)));const {children,...props}=x.props??{};return React.createElement(x.type,{...props,key},real(children));}
test('actual panel loads, explicitly saves once, reads persisted rows and renders source text escaped',async()=>{
 const h=harness();h.render();h.button('手工研究标注').props.onClick();h.render();
 assert.equal(h.calls.length,1);h.calls[0].resolve({records:[]});await flush();h.render();
 h.input('textarea').props.onChange({target:{value:row.text}});h.render();
 const save=h.button('追加保存标注');assert.equal(save.props.disabled,false);
 save.props.onClick();save.props.onClick();assert.equal(h.calls.length,2);
 assert.equal(h.calls[1].args[1],'POST');assert.equal(h.calls[1].args[2].date,'2026-10-16');
 h.calls[1].resolve(row);await flush();h.render();assert.equal(h.calls.length,3);
 h.calls[2].resolve({records:[row,{...row,id:'foreign',code:'000002'}]});await flush();h.render();
 assert.equal(nodes(h.tree).filter(n=>n.props?.['data-testid']==='research-annotation').length,1);
 const html=renderToStaticMarkup(real(h.tree));assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<img/);
 assert.match(label(h.tree),/本快照精确日期匹配/);h.unmount();
});
test('selection change clears draft and a late save cannot clear newer selection or show stale success',async()=>{
 const h=harness();h.render();h.button('手工研究标注').props.onClick();h.render();h.calls[0].resolve({records:[]});await flush();h.render();
 h.input('textarea').props.onChange({target:{value:'old'}});h.render();h.button('追加保存标注').props.onClick();
 h.render({code:'000001',context,selectedDate:'2026-10-17',dates:['2026-10-16']});h.render();assert.equal(h.input('textarea').props.value,'');
 h.calls[1].resolve(row);await flush();h.render();assert.doesNotMatch(label(h.tree),/已保存 2026/);assert.equal(h.button('追加保存标注').props.disabled,true);h.unmount();
});
test('unmounted reads are ignored and absent verified context disables save without hiding archived notes',async()=>{
 const h=harness({code:'000001',context:null,selectedDate:'2026-10-16',dates:['2026-10-16']});h.render();h.button('手工研究标注').props.onClick();h.render();
 assert.equal(h.button('追加保存标注').props.disabled,true);h.calls[0].resolve({records:[row]});await flush();h.render();assert.match(label(h.tree),/未映射/);
 h.button('重新读取标注').props.onClick();h.render();h.unmount();h.calls[1].resolve({records:[{...row,text:'late'}]});await flush();h.render();assert.doesNotMatch(label(h.tree),/late/);
});
test('failure retains draft and requests readback before retry',async()=>{
 const h=harness();h.render();h.button('手工研究标注').props.onClick();h.render();h.calls[0].resolve({records:[]});await flush();h.render();
 h.input('textarea').props.onChange({target:{value:'keep me'}});h.render();h.button('追加保存标注').props.onClick();h.calls[1].reject(new Error('network'));await flush();h.render();
 assert.equal(h.input('textarea').props.value,'keep me');assert.match(label(h.tree),/保存结果未确认/);h.unmount();
});

import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const nodes=x=>!x||typeof x!=='object'?[]:Array.isArray(x)?x.flatMap(nodes):[x,...nodes(x.props?.children)];
const label=x=>x==null?'':typeof x==='string'?x:Array.isArray(x)?x.map(label).join(''):typeof x==='object'?label(x.props?.children):String(x);
function harness(){let cursor=0,fail=false;const state=[],saved=[];const exports={};const modules={'react':{useRef:v=>{const i=cursor++;return state[i]??={current:v}},useState:v=>{const i=cursor++;if(!(i in state))state[i]=v;return[state[i],v=>state[i]=v]}},'react/jsx-runtime':{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})},'lucide-react':{Check:()=>null,BookmarkPlus:()=>null},'@/lib/notes':{addNote:(...args)=>{if(fail)throw Error('quota');saved.push(args)}}};
vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/components/ui/SaveNoteButton.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,{exports,require:n=>modules[n],Error});
return {saved,setFail:v=>fail=v,render:props=>{cursor=0;return exports.SaveNoteButton(props)}};
}
test('save button passes generation separately; generation change resets saved state; quota failure remains retryable',async()=>{
 const h=harness(),props={kind:'复盘',title:'合成',content:'原文',generation:{generatedAt:'original'}};
 let tree=h.render(props);await nodes(tree).find(n=>n.type==='button').props.onClick();assert.equal(h.saved[0][4],props.generation);assert.equal(h.saved[0][3],undefined);
 tree=h.render(props);assert.equal(nodes(tree).find(n=>n.type==='button').props.disabled,true);
 const changed={...props,generation:{generatedAt:'later'}};tree=h.render(changed);assert.equal(nodes(tree).find(n=>n.type==='button').props.disabled,false);
 h.setFail(true);await nodes(tree).find(n=>n.type==='button').props.onClick();tree=h.render(changed);assert.match(label(tree),/quota/);assert.equal(nodes(tree).find(n=>n.type==='button').props.disabled,false);
 h.setFail(false);await nodes(tree).find(n=>n.type==='button').props.onClick();assert.equal(h.saved.length,2);
});

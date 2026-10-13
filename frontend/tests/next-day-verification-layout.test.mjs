/** Production JSX structure; pixel/scrollport acceptance remains the CI browser's job. */
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const require=createRequire(import.meta.url);
const view=JSON.parse(readFileSync(new URL('./fixtures/next-day-verification.json',import.meta.url),'utf8')).open_empty;
const compiled=await build({entryPoints:[fileURLToPath(new URL('../src/components/dailyReview/NextDayVerificationCard.tsx',import.meta.url))],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],plugins:[{name:'bounded-render-boundaries',setup(b){
 b.onResolve({filter:/^@\/lib\/nextDayVerification$/},()=>({path:fileURLToPath(new URL('../src/lib/nextDayVerification.ts',import.meta.url))}));
 b.onResolve({filter:/^@\/(lib\/api|components\/ui\/GlassCard)$/},args=>({path:args.path,namespace:'stub'}));
 b.onLoad({filter:/.*/,namespace:'stub'},args=>({contents:args.path.endsWith('/api')?'export function request(){throw Error("render must not request")}':'import {createElement} from "react";export function GlassCard(props){return createElement("div",props)}',loader:'js'}));
}}]});
function render(draft){
 let index=0;const states=['2026-07-31',view,draft,false,false,'',false,0];
 const mockReact={...React,useEffect(){},useRef:value=>({current:value}),useState:()=>[states[index++],()=>{}]};
 const module={exports:{}};new Function('require','module','exports',compiled.outputFiles[0].text)(name=>name==='react'?mockReact:require(name),module,module.exports);
 return renderToStaticMarkup(React.createElement(module.exports.NextDayVerificationCard,{initialDate:'2026-07-31'}));
}
for(const withReason of [false,true])test(`mobile compact controls preserve all eight conditions, reason=${withReason}`,()=>{
 const html=render(withReason?[{metric:'limit_up_count',direction:'up',reason:'Synthetic prior condition'}]:[]);
 assert.equal((html.match(/<select /g)||[]).length,8);
 for(const metric of view.metrics){assert.ok(html.includes(metric.label+'方向'));assert.ok(html.includes(metric.label));}
 assert.match(html,/<fieldset[^>]*class="space-y-2 sm:space-y-3 disabled:opacity-70"/);
 assert.equal((html.match(/class="rounded border border-border p-2 sm:p-3"/g)||[]).length,8);
 assert.match(html,/持平阈值/);assert.match(html,withReason?/保存整晚条件/:/保存为空（清除本晚条件）/);
 if(withReason)assert.match(html,/aria-label="涨停家数理由"[^>]*value="Synthetic prior condition"/);
 assert.doesNotMatch(html,/<fieldset[^>]*(?:hidden|max-height|overflow-hidden)/);
});

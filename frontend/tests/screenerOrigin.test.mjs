import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import ts from 'typescript';
const source=ts.createSourceFile('screener-browser.mjs',readFileSync(new URL('./e2e/full-market-source-to-sink.browser.mjs',import.meta.url),'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.JS);
const find=name=>source.statements.find(node=>ts.isFunctionDeclaration(node)&&node.name?.text===name);
const start=find('startBackend');assert.ok(start);
test('real backend setup passes only its selected frontend origin to production security',async()=>{
 let options;
 const spawn=(_command,_args,opts)=>{options=opts;return {stdout:{on(){}},stderr:{on(){}}};};
 const make=new Function('getFreePort','resolvePython','spawn','backendDir','path','__dirname','backendGuardLogs','waitHttp','stopProcess',`${start.getText(source)};return startBackend;`);
 const startBackend=make(async()=>45000,()=>({command:'python',prefix:[]}),spawn,'backend',path,'tests/e2e',[],async()=>{},async()=>{});
 await startBackend('/tmp/fixture/rdp','/tmp/fixture','http://127.0.0.1:41979');
 assert.equal(options.env.VR_ALLOW_ORIGINS,'http://127.0.0.1:41979');
 assert.equal(options.env.VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH,'1');
 assert.equal(options.env.VR_SCREENER_NETWORK_LOG,path.join('/tmp/fixture','network-guard-45000.json'));
});
for(const name of ['runNormalScenario','runFailureClearsScenario','runModeSwitchScenario','runUnavailableScenario','runCandidateCoverageScenario'])test(`${name} allocates and passes its exact origin before backend import`,()=>{
 const node=find(name);assert.ok(node);const text=node.getText(source);
 assert.ok(text.indexOf('const frontendPort = await getFreePort()') < text.indexOf('const backend = await startBackend('));
 assert.ok(text.indexOf('const baseUrl =') < text.indexOf('const backend = await startBackend('));
 const calls=[];function visit(n){if(ts.isCallExpression(n)&&n.expression.getText(source)==='startBackend')calls.push(n);ts.forEachChild(n,visit);}visit(node);
 assert.equal(calls.length,1);assert.equal(calls[0].arguments.length,3);assert.equal(calls[0].arguments[2].getText(source),'baseUrl');
 assert.match(text,/startStaticServer\(frontendDist, frontendPort, backend.port/);
});


test('backend allocation cannot reuse the selected frontend port',async()=>{
 let calls=0,actualArgs;
 const make=new Function('getFreePort','resolvePython','spawn','backendDir','path','__dirname','backendGuardLogs','waitHttp','stopProcess',`${start.getText(source)};return startBackend;`);
 const backend=make(async()=>++calls===1?41979:45000,()=>({command:'python',prefix:[]}),(_c,args)=>{actualArgs=args;return {stdout:{on(){}},stderr:{on(){}}};},'backend',path,'tests/e2e',[],async()=>{},async()=>{});
 await backend('/tmp/fixture/rdp','/tmp/fixture','http://127.0.0.1:41979');
 assert.equal(calls,2);assert.equal(actualArgs.at(-1),'45000');
});

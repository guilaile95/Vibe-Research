/** Deterministic build-byte census, not a latency claim. Run against baseline and candidate dist. */
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { gzipSync } from 'node:zlib';
export function measureBuild(directory) {
 const dist=resolve(directory),html=readFileSync(join(dist,'index.html'),'utf8');
 const entryPaths=[...html.matchAll(/(?:src|href)="\/([^\"]+\.js)"/g)].map(match=>match[1]);
 const entry=entryPaths.map(path=>{const bytes=readFileSync(join(dist,path));return {path,bytes:bytes.length,gzipBytes:gzipSync(bytes).length};});
 const all=readdirSync(join(dist,'assets')).filter(path=>path.endsWith('.js')).map(name=>{const path=`assets/${name}`,bytes=readFileSync(join(dist,path));return {path,bytes:bytes.length,gzipBytes:gzipSync(bytes).length};});
 const needle='AI 服务器用 PCB 可理解为 AI 机柜内的电气互连骨架';
 const eagerPcbBody=entryPaths.some(path=>readFileSync(join(dist,path),'utf8').includes(needle));
 const pcbContentChunks=all.filter(row=>readFileSync(join(dist,row.path),'utf8').includes(needle)).map(row=>row.path);
 assert.ok(pcbContentChunks.length>0,'Complete checked-in PCB body must remain in production build');
 return {entry,entryBytes:entry.reduce((s,r)=>s+r.bytes,0),entryGzipBytes:entry.reduce((s,r)=>s+r.gzipBytes,0),allJavaScriptBytes:all.reduce((s,r)=>s+r.bytes,0),javascriptChunkCount:all.length,eagerPcbBody,pcbContentChunks};
}
if(process.argv[1]&&import.meta.url===new URL(`file://${resolve(process.argv[1])}`).href){
 const report=measureBuild(process.argv[2]);if(process.argv[3])writeFileSync(process.argv[3],JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
}

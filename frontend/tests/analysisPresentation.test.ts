import test from 'node:test';
import assert from 'node:assert/strict';
import { isCompletedAnalysis, rssNotAnalyzedMessage } from '../src/lib/analysisPresentation.ts';
const success = {status:'SUCCESS',artifact_id:'synthetic-original',generated_at:'2026-10-22T00:00:00Z',counts:{total_news:1,analyzed_news:1,hotlist_count:1,rss_count:0,hotlist_analyzed:1,rss_analyzed:0}};
test('only identifiable complete analysis can replace a previous result',()=>{
 assert.equal(isCompletedAnalysis(success),true);
 for(const value of [null,{}, {...success,status:'ERROR'}, {...success,status:'SKIPPED'}, {...success,artifact_id:''}, {...success,counts:null}, {...success,counts:{...success.counts,rss_analyzed:-1}}, {...success,counts:{...success.counts,rss_analyzed:'0'}}]) assert.equal(isCompletedAnalysis(value),false);
});
test('zero RSS is not no incremental information and unknown coverage does not invent a reason',()=>{
 for(const reason of ['disabled','no_items','budget_exhausted','source_unavailable',undefined]){
  assert.match(rssNotAnalyzedMessage(reason),/本次未分析RSS/);
  assert.match(rssNotAnalyzedMessage(reason),/不代表无新增信息/);
 }
 assert.match(rssNotAnalyzedMessage(),/原因未记录/);
 assert.match(rssNotAnalyzedMessage('disabled'),/已关闭/);
});

// Structural guardrails supplement (not replace) the production-browser state matrix.
import { readFileSync } from 'node:fs';
test('today error handlers preserve confirmed lists and require readiness before writes',()=>{
 const source=readFileSync(new URL('../src/pages/DailyReview.tsx',import.meta.url),'utf8');
 const reload=source.slice(source.indexOf('  const reloadWatchList ='),source.indexOf('  useEffect(() => {\n    mountedRef.current = true;'));
 const persist=source.slice(source.indexOf('  const persistWatch ='),source.indexOf('  const addWatch ='));
 assert.match(reload,/r.status === "corrupted" \|\| r.migrationError/);
 assert.doesNotMatch(reload.slice(reload.indexOf('    } catch')),/setWatchCodes|setWatchEtag|saveWatchAuthoritative/);
 assert.match(persist,/watchListState !== "ready" \|\| watchListBusy.current/);
 assert.doesNotMatch(persist.slice(persist.indexOf('    } catch')),/setWatchCodes|setWatchEtag|saveWatchAuthoritative/);
 assert.match(source,/watchListState === "ready" \? "还没有关注股票/);
 assert.match(source,/candidateWorkspaceHref\(code, `\$\{location.pathname\}\$\{location.search\}#today-watch-\$\{code\}`\)/);
});
test('analysis rejects late completions and guards double submission',()=>{
 const source=readFileSync(new URL('../src/components/native-intel/AiAnalysisRegion.tsx',import.meta.url),'utf8');
 assert.match(source,/if \(busyRef.current\) return/);
 assert.match(source,/request === requestRef.current/);
 assert.match(source,/return \(\) => \{ requestRef.current \+= 1; \};\n  \}, \[mode, scope\]\)/);
 assert.ok(source.indexOf('if (!isCompletedAnalysis(res))')<source.indexOf('setAnalysis(res)'));
 assert.doesNotMatch(source,/暂无异常异动信号|暂无显著热点态势|暂无显著舆情争议/);
});

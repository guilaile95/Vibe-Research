# Bounded tool-projection coverage disclosure

## 中文交付摘要（2026-10-06，未发布的本地候选）

本次仅完成本地修复与验收，**没有发布、合并、部署或切换正在运行的服务**。
源码与测试验收坐标为 `57e20c21c12417979d455f98c459364fc4adea00`；后续本报告的文档提交不改变该实现。
README 与 AGENTS 没有把本次候选写成已发布，因此保留原文。

### 实际变化

- 原先问答长回复、研报字段或新闻记录被裁剪后仍可能显示完整返回；现在分别披露来源窗口、适配裁剪和上下文截断，前端显示“返回受限”。
- 原先新闻链接、研报编号及公告原始时间在送给 AI 前丢失；现在保留已返回的原始值。危险链接被省略，过长引用不会变成伪造的省略号链接。
- 原先同一问答毫秒时间戳会随服务器时区变成不同日期；现在统一输出北京时间，仍保留原有分钟格式。
- 列表形状、条数上限、HTTP 返回合同和请求次数保持不变；没有补抓全文。问答回复时间的来源语义尚不明确，继续记为未知，不用提问时间代替。

### 验收与剩余事项

- 最终去重后端组合：**724 通过、1 项既有跳过，27 个测试文件**；包括真实内存 HTTP 路由的失败/空结果区分、缓存与健康记录。
- 完整前端单测：**978 通过，0 失败/跳过**；TypeScript 与 Vite 构建通过，保留既有大体积 chunk 警告。
- 实际生成的 5 工具、12 个流事件通过前端解析、标签与存储回读；此项单独说明，不加入上述两个套件计数。
- 语法与空白检查通过。较早章节的 373、264、281、688 等阶段计数均为历史，不叠加为总成绩。
- 已知失败：MCP HTTP 集成因现有代理所需 `socksio` 缺失而受阻，未安装依赖、改代理或绕路重试；该失败不算进通过数。
- 未完成：独立 CodeRabbit 审查、全后端/Windows/浏览器验收、真实来源/模型质量、远端 CI 和发布。审查与发布仍待授权。

安全可补的 HTTP 验收缺口已用现有离线用例关闭；没有发现需要继续修改产品的组合缺陷。
下一步为独立审查及获准后的交付，不继续推测性扩展字段。

### 复现命令与回退坐标

在仓库根目录、已安装锁文件所需依赖的环境运行。`PYTHON` 指向现有后端解释器；下列命令不安装依赖，不启动浏览器，不调用真实来源或模型。测试自身隔离临时数据目录。

```bash
PYTHON="${PYTHON:-backend/.venv/bin/python}"
FILES=$( {
  rg -l '^(import (chat|ai_tools|debate)|from (chat|ai_tools|debate) import)' backend/tests
  printf '%s\n' backend/tests/test_critical_data_disclosures_adapter.py \
    backend/tests/test_mcp_stdio_encoding.py backend/tests/test_native_intel_agent_tools.py \
    backend/tests/test_report_page_chat.py backend/tests/test_public_feed_errors.py
} | sort -u )
ACCEPTANCE_TMP=$(mktemp -d)
PYTHONPATH=backend "$PYTHON" -m pytest -q -rs -m 'not live' \
  --basetemp="$ACCEPTANCE_TMP/pytest" $FILES
npm --prefix frontend run build
npm --prefix frontend test
"$PYTHON" -m py_compile backend/astock.py backend/ai_tools.py backend/chat.py \
  backend/tests/test_tool_source_provenance.py backend/tests/test_investor_qa_timezone.py
git diff --check
```

混合工具组合用例会在上述临时目录写出不含真实数据的 `combined-tool-events.json`。接续复验其前端解析及存储回读：

```bash
EVENTS=$(find "$ACCEPTANCE_TMP/pytest" -name combined-tool-events.json -print -quit)
node --experimental-strip-types --input-type=module - "$EVENTS" <<'JS'
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { applyNdjsonLine, createNdjsonProtocolState } from './frontend/src/lib/api.ts';
import { applyChatToolResult, parseStoredChatTools } from './frontend/src/lib/chatToolStatus.ts';
const events = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const state = createNdjsonProtocolState();
let tools = [];
for (const event of events) applyNdjsonLine(state, JSON.stringify(event), {
  onTool: (name, args, callId) => tools.push({name, arg: '', callId, status: 'pending', truncated: false}),
  onToolResult: result => { tools = applyChatToolResult(tools, result); },
});
assert.equal(state.sawError, false);
assert.equal(events.length, 12);
assert.deepEqual(tools.map(t => [t.name, t.status, t.truncated]), [
  ['query_news', 'partial', true], ['query_reports', 'partial', false],
  ['query_industry_reports', 'success', false], ['query_announcements', 'partial', false],
  ['query_investor_qa', 'partial', false],
]);
assert.deepEqual(parseStoredChatTools(JSON.parse(JSON.stringify(tools))), tools);
console.log('5 tools / 12 generated events: PASS');
JS
```

本次修复栈之前的对照/回退基线为 `f4922ddadae8c4c297821e757f85a8bb80c3f0a2`，tree 为 `4c8cb09ab015073e9ac1f68e40d17209d3211b9b`。
需要回退时先保留工作区与后续改动，审核该基线到候选的差异并使用普通反向提交；本轮没有执行回退、重写历史或删除分支。

## Verified gaps

On baseline `f4922dd`, source readers feed adapters in `backend/ai_tools.py`,
which discard rows, fields or text before `chat._serialize_tool_result` applies
its separate 6,000-character JSON budget. The serializer already discloses its
own compaction, but cannot detect material discarded upstream.

Actual baseline adapter/serializer execution with synthetic strings:

| Fixture | Source text | Adapter text | Model text | Old outcome |
| --- | ---: | ---: | ---: | --- |
| Q&A: one question character + 400 answer characters + four-character qualification | 405 | 401 | 401 | success, context truncated=false |
| Q&A: 30 rows, each 250 question and 500 answer characters | 22,500 | 7,200 (12 rows) | 3,656 (8 rows) | success, context truncated=true |

The model-text count includes ellipses introduced by context compaction. The
qualification regression fails on the old adapter because `success != partial`.
These strings are synthetic, not financial assertions.

Three additional below-budget fixtures reproduce the same missing disclosure:

- `query_reports`: an actual source `infoCode` field is projected out; only
  title/date/organization/rating remain
- `query_news`: source `新闻内容` is projected out; only title/time/source remain
- `query_industry_reports`: `infoCode` is projected out; only
  title/date/organization/industry remain

All three baseline regression cases fail with `success, truncated=false` instead
of `partial, truncated=false`. The initial disclosure fix did not forward discarded content. The later provenance
slice below preserves selected source references while continuing to omit full text.

## Final compatibility-preserving contract

All four tool results **remain arrays**, including `[]` for empty results.
Original selected fields, ordering, row limits, and Q&A text caps remain intact.
The Q&A missing-answer display placeholder `（未回复）` is preserved. It is not
additional corroboration of a source's completeness.

Coverage is attached to the **first real row only**; no artificial metadata row
is inserted and no empty result becomes evidence. New fields on that row:

- `status`: partial when the adapter omitted rows, selected-row text, or (for
  report/news tools) fields; otherwise success
- `adapter_coverage`: input/output/omitted row counts and either omitted Unicode
  character counts or omitted field counts **in selected rows only**
- `note`: source-window and excerpt/metadata-only limitations

Each Q&A row also has `question_truncated` and `answer_truncated` flags. Coverage
scope is `adapter_input_before_context_compaction`. These are metadata, not observations.
Output counts describe the adapter stage, not final model delivery after further
context compaction. Character/field counts exclude dropped rows. Q&A's existing
company/answerer field projection is unchanged and is not included in its text counts.

Chat prioritizes adapter coverage when compacting. Its envelope `truncated` still
means **context** compaction only. Therefore partial with truncated=false is
intentional for adapter-only omissions. Existing recursive limitation detection
propagates the first-row partial status to Chat events and Debate sections.

The initial local commit `c867d24` used an object envelope for Q&A. Follow-on
compatibility validation removed that unneeded shape change before publication;
use the final array contract described here, not the intermediate object contract.
Additive metadata may still affect external consumers that reject unknown fields;
external MCP consumers cannot be enumerated, and their compatibility is not proven.

## Consumer tracing and executable checks

- Chat sync and streaming paths execute the registered handler and serialize arbitrary
  JSON; synthetic executions verify actual projected results and partial trace/events
- MCP `tools/call` JSON-encodes `chat._exec_tool`; actual dispatch tests verify arrays
  and coverage with no added pseudo-row
- Debate's normal dossier includes reports and news; actual `_fetch_section` tests
  verify partial sections instead of an unrestricted success. Q&A and industry reports
  are not in its normal dossier, though the generic path accepts them
- HTTP `/api/investor-qa`, `/api/reports` and `/api/news` call `astock` directly;
  executable reader checks preserve their source fields and response shapes
- Frontend Chat consumes result status events, not the internal raw tool payload;
  no in-repository typed Q&A array consumer was found beyond these generic dispatchers
- Legacy Q&A field readers are exercised by projecting the original three keys;
  array length/order, text caps and placeholder values match the baseline contract

Report readers still request at most one page. Source window size does not
establish complete historical coverage. No extra source/model call is added.

## News source-reader slice

A separate execution against `656d892` reproduced the earlier news-reader gap:
20 synthetic provider-frame rows became 15 reader rows before adapter projection.
The adapter correctly reported input_rows=15 and omitted_rows=0, but its successful
status did not disclose the five rows omitted by the requested reader limit.
The new source-only regression fails on that baseline (`success != partial`).

`astock.stock_news` adds an opt-in `with_coverage=True` result containing rows and
source coverage. The AI news adapter opts in and attaches `source_coverage` to its
first real row, separately from `adapter_coverage`:

- scope: `provider_response_before_requested_limit`
- provider_response_rows: number of rows in the actual frame returned by the provider
- returned_rows and omitted_rows: the local requested-limit selection
- requested_limit: still 15 for this tool
- total_history_rows: always null because this response does not establish that total

The 20-row fixture reports 20 observed / 15 returned / 5 omitted at the source stage,
then 15 observed / 15 returned / 0 omitted at the adapter stage. This does not mean
20 news items exist in all history, nor that omitted items have any particular meaning.
If the provider returns only 15 or fewer rows, no extra omission is inferred. A missing
provider response keeps unknown counts as null rather than claiming zero total history.
No extra page fetch, model round, storage, source selection or readback is introduced.

Default and strict reader calls still return their existing lists. HTTP `/api/news`
still returns `{data: rows}` with its requested limit, validation and error semantics.
The provider frame is not mutated. The route/reader had no news cache to migrate;
no cache or cache-key contract is changed. Shared serialization treats source coverage
as metadata and retains observed omission counts under normal Chat/Debate compaction.

Fourteen source-window regressions cover empty/below/exact/over-limit frames, opt-in
and legacy strict/non-strict results, missing response vs empty frame, unchanged HTTP
reads after AI reads, one source request per invocation and context compaction.

## Validation and limits (2026-10-06)

373 focused backend tests and 4 frontend status tests pass. These include 44
backend coverage/compatibility cases. Tests cover exact
Unicode limits, metadata-only emptiness, field/row omission counts, preservation
of source inputs, two-stage compaction, unchanged source-call bounds, MCP, sync and
streaming Chat, HTTP readers, and Debate. Baseline Q&A and three projection cases
fail as expected on the old implementations. Syntax and whitespace checks pass.

These are functional regressions, not an independent code review or a substitute
for CodeRabbit review. No browser, real provider/model evaluation, full backend
suite, frontend build, remote CI, merge or deployment was performed for this change.

This work discloses omissions rather than recovering them. Repeating the same tool
is not a readback mechanism, and a post-adapter cache cannot restore discarded text.
Announcements and other list caps, GPU summaries, and other source-reader truncation
remain separate candidates requiring concrete reproduction before further changes.
Expansion stops after this source-layer slice.


## Source-provenance preservation slice (2026-10-06)

Baseline `afe0a47` reproduced four independent model-facing failures through actual
`chat.run_chat` tool execution with offline provider/LLM fixtures: news lost
`新闻链接`, both report tools lost `infoCode`, and announcements lost `notice_at`
and `url`. All four new assertions failed with missing keys before implementation.
News/report dates and publisher names already survived below the context budget;
no replacement dates or publishers are synthesized.

The adapters now forward those existing string references when present. News and
announcement links must be absolute HTTP(S) URLs with a host, without credentials,
backslashes, whitespace/control characters or malformed port/host syntax. Invalid
references are omitted and counted by existing adapter coverage. A permitted URL
is still unverified source data; it is not proof that its destination was opened,
that its claims are true, or that a future fetch would be authorized/safe. No URL
is fetched here and no report PDF URL is constructed from its ID.

Announcements retain their original title/date/type and array/order/15-row contract,
adding original source time/link and the same first-real-row coverage/note contract.
The actual source-reader fixture includes two same-day notices at 09:30 and 16:30:
model delivery now distinguishes those source timestamps instead of only their
identical display dates. Timestamps are preserved verbatim, with no timezone,
precision or historical-availability claim added by this change.

Chat/Debate context compaction prioritizes these reference fields plus existing
news/report dates and publishers. Citation strings remain exact or become null
when too long for that compaction tier; they never become fabricated ellipsis
links or shortened report IDs. The envelope still discloses context truncation.
Full news/report/announcement text is not recovered. Retaining a reference does not
create a readback tool, add requests, or establish historical completeness.

Validation against the final source: 264 focused backend checks passed, 1 skipped
(including 49 new provenance cases); syntax and whitespace checks passed. The
focused set covers actual Chat model-message delivery, MCP dispatch, Debate,
source-reader/HTTP compatibility, unsafe/missing metadata, source immutability,
row caps, empty arrays and compaction. Previous projection tests now use a synthetic
`abstract` field for still-omitted report content rather than expecting `infoCode`
to disappear.

An earlier broader invocation reported 258 passed, 1 skipped, 1 failed:
`test_native_intel_mcp_client.py::test_real_mcp_client_e2e` could not initialize its
HTTP client because `socksio` is absent for the environment's configured SOCKS
proxy. The proxy/dependencies were not altered and that check was not retried.
One newly authored HTTP test initially used an unsupported `limit` argument;
corrected to the existing route signature and passed in the final focused run.
No browser, live provider/model, full backend suite, frontend build/test, independent
CodeRabbit review, publication, remote CI, merge or deployment was performed for
this slice. The previous slice's counts above remain historical, not added to this
run's totals.

## Investor Q&A deployment-timezone correction (2026-10-06)

On provenance baseline `737e9cd`, the actual investor-Q&A reader converted provider
`pubDate` using the server's local timezone. For synthetic epoch `1791217800000`,
three isolated subprocess environments produced these reader/HTTP/AI values:

| Process timezone | Baseline output | Corrected output |
| --- | --- | --- |
| UTC | 2026-10-05 16:30 | 2026-10-06 00:30 |
| Asia/Shanghai | 2026-10-06 00:30 | 2026-10-06 00:30 |
| UTC−5 (`Etc/GMT+5`) | 2026-10-05 11:30 | 2026-10-06 00:30 |

The repository's existing adapter already specifies millisecond conversion. The
installed AKShare adapter and its [upstream implementation](https://raw.githubusercontent.com/akfamily/akshare/main/akshare/stock_feature/stock_irm_cninfo.py)
(read 2026-10-06, `pubDate` mapping and lines 114–118) explicitly convert the same
endpoint's field from Unix milliseconds/UTC to Asia/Shanghai. This is corroborating
adapter-source evidence, not a live provider probe or a published CNINFO API SLA.

The fix adds an explicit UTC+8 timezone to the existing conversion, matching the
modern Beijing-time convention already used in this repository. The platform
started in 2010, after Shanghai's historical DST period; this is not a generic
historical-timezone converter. It retains the minute-resolution string format,
unknown empty strings, row fields/order and two existing requests per reader call.
The HTTP 15-minute cache contract is unchanged. No machine/global timezone was
modified; subprocess `TZ` only controlled each disposable test process.

Seventeen new tests cover UTC/Shanghai/negative-offset processes, cross-date
rollover, integer/float millisecond values, minute formatting, unknown values,
existing malformed provider behavior (HTTP 502 / AI error), and unchanged valid
reader strings. Provider-side timestamp strings were already unsupported and
remain unsupported; no permissive date parser was added. The three process-TZ
cases are explicitly POSIX-only; numeric conversion checks run cross-platform.

Final focused backend run: 281 passed, 1 skipped (the pre-existing superseded
native-intel test); syntax and whitespace checks passed. Baseline reproduction
was 2 failures / 1 pass. No browser, provider/model request, install, proxy change,
independent review, full suite, frontend check, publication, CI or deployment ran.
The separate MCP proxy dependency failure recorded above remains unresolved and
was not retried in this slice.

## Reply-time investigation and cumulative acceptance (2026-10-06)

The reply-time investigation stopped at a semantic evidence boundary. The primary
AKShare source linked above maps `attachedPubDate` from the **same list endpoint**
to an ignored field. Its separate question-detail endpoint maps `replyDate` to
answer time. This does not establish that `attachedPubDate` means the same thing,
its timestamp unit, or first public availability. No recorded provider payload in
this checkout established the missing mapping; no live provider request was made.

An offline execution changed only synthetic `attachedPubDate` across same-time,
next-day, null and malformed values. All four produced identical actual reader,
HTTP and AI outputs, with `ask_time = 2026-10-06 00:30`; unanswered rows remained
unanswered. This proves raw-field loss, not the lost field's real semantics or
that a model actually inferred historical availability. No `answer_time` field,
question-time fallback or stronger historical-availability assertion was added.
Reply time remains unknown until authoritative semantics can be established.

The cumulative acceptance run covers the complete local change stack from
`f4922dd` through the timestamp fix, with one new composition regression. It runs
five tools in one actual streaming Chat round: news source-window and adapter
omissions plus context compaction, stock-report IDs, industry-report success,
rejected announcement links, and actual Q&A epoch conversion plus answer clipping.
Twelve generated events were replayed through the real frontend NDJSON parser,
status-label mapping and JSON storage/hydration. All five tool identities/outcomes
stayed separate, including partial-without-context-truncation and success.

Final unique suite totals (not sums of earlier runs):

- Backend selected aggregate: **724 passed, 1 skipped**, 27 files. Selection is
  every `backend/tests` file with a top-level import of `chat`, `ai_tools` or
  `debate`, plus `test_critical_data_disclosures_adapter.py`,
  `test_mcp_stdio_encoding.py`, `test_native_intel_agent_tools.py` and
  `test_report_page_chat.py` and `test_public_feed_errors.py`, deduplicated; run with `-m "not live"` and isolated
  synthetic data/report/review paths. The skip is the existing superseded
  native-intel test, not a newly suppressed failure.
- Frontend full unit suite: **978 passed**, zero failed/skipped.
- Frontend `npm run build`: TypeScript and Vite passed. Vite's >500 kB chunk warning
  remains a warning; no bundling/refactor work was introduced.
- Generated backend-event → frontend-parser/storage replay: **5 tools / 12 events
  passed**, reported separately from both suite totals.
- Python syntax and Git whitespace checks passed.

The frontend reused installed dependencies with an identical package-lock hash;
no package installation or lock change occurred. The newly authored composition
fixture initially looked for a tool-message `name`; corrected to the actual
`tool_call_id` association before the successful final aggregate. No production
composition defect was found. This acceptance adds tests/documentation only.

The known MCP HTTP-client integration failure due to missing `socksio` under the
configured proxy remains **failed/environment-blocked**, outside this selected
aggregate, and was not retried or worked around. Full backend collection, browser
acceptance, live provider/model quality, Windows execution, independent CodeRabbit
review, remote CI, publication, merge and deployment remain unrun for this stack.
The next step is review/authorized delivery of this bounded stack, not more
speculative field-by-field expansion.

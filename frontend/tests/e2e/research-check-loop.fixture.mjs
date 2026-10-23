// Synthetic, read-only transport contracts. No browser, server, model or private data.
import assert from 'node:assert/strict';
import { navigationEvidencePage } from './research-navigation.fixture.mjs';
const report = (id, title, hash) => ({ id, title, name: `${id}.pdf`, size: 123, ext: '.pdf', ts: 1, industry: 'synthetic', source_url: `https://example.com/${id}.pdf`, publish_date: '2025-01-24', file_sha256: hash.repeat(64), page_count: 2, text_index_status: 'SEARCHABLE' });
export const originalReport = report('synthetic-original', '原预告（合成文本）', 'a');
export const revisedReport = report('synthetic-revised', '修订预告（合成文本）', 'b');
export const originalText = '合成证券600519，2024年全年，合并报表，归属于上市公司股东的净利润，单位：万元；预计盈利648.13至753.93万元。这是测试转录，不是实际原PDF。';
export const revisedText = '合成证券600519，2024年全年，合并报表，归属于上市公司股东的净利润，单位：万元；预计亏损594.25至891.37万元。修订预告不是实际业绩。测试转录，不是实际原PDF。';
export const discoveryItem = {
  security_code: '600519', name: '合成公司', strategy: 'SWING', sector: '合成行业', themes: [], discovery_state: 'QUEUED', condition_match: 'FULL_CONDITIONS', research_priority: 'MEDIUM',
  reason_codes: ['SYNTHETIC_RETURN_20D'], supporting_observations: [{ code: 'RETURN_20D', label: '20日收益（合成）', value: 0.12, source_ref: 'synthetic:history-source' }],
  uncertainties: ['FUNDAMENTAL_FRESHNESS_UNKNOWN'], data_health: 'partial', catalyst_status: 'PARTIAL', fundamental_status: 'PARTIAL', evidence_gate: 'PARTIAL',
  restricted_universe: { status: 'UNKNOWN', reason_codes: [], listing_age_status: 'UNKNOWN' }, discovered_at: '2026-10-22T02:00:00Z', as_of: '2026-10-21', provenance_refs: ['synthetic:market-source', 'synthetic:announcement-directory'],
};
export const discoverySnapshot = {
  schema_version: 'full-market-discovery.v0.1', status: 'partial', as_of: '2026-10-21', fetched_at: '2026-10-22T02:01:00Z', last_successful_at: null, refresh_attempted_at: null,
  market_context: { status: 'partial', core_universe_count: 100, outside_core_count: 2, sector_count: 1, market_average_change_pct: null, amount_median: null, turnover_active_threshold: null, source_ref: 'synthetic:market-source' }, funnel: { core_universe: 100, cheap_scan_passed: 30, qualification_candidates: 24, queue_items: { SHORT: 0, SWING: 1, MEDIUM: 0 }, excluded: 0 },
  coverage: { universe: 'PROVIDER_SH_SZ_CORE_A_SHARES_EXCLUDES_BEIJING', qualification_limit: 24, qualification_omitted: 6, qualification_order: 'STRATEGY_AMOUNT_DESC_THEN_CODE_DEDUPLICATED', queue_limit: 12, queue_eligible: { SHORT: 0, SWING: 1, MEDIUM: 0 }, queue_omitted: { SHORT: 0, SWING: 0, MEDIUM: 0 }, queue_order: 'RESEARCH_PRIORITY_THEN_SECURITY_CODE', filter_scope: 'RETURNED_QUEUE_ONLY', excluded_total: 0, excluded_omitted: 0 },
  datasets: [
    { dataset_id: 'market.a_share_snapshot', status: 'normal', as_of: '2026-10-21', fetched_at: '2026-10-22T02:01:00Z', reason_code: null, provenance_refs: ['synthetic:market-source'] },
    { dataset_id: 'announcements.recent', status: 'partial', as_of: '2026-10-21', fetched_at: '2026-10-22T02:01:00Z', reason_code: 'SOURCE_PARTIAL', provenance_refs: ['synthetic:announcement-directory'], request_status: 'PARTIAL', material_completeness: 'UNKNOWN', source_coverage: { scope: 'SYNTHETIC_RECENT_DIRECTORY', window_complete: false, full_text_included: false } },
  ], queues: { SHORT: [], SWING: [discoveryItem], MEDIUM: [] }, excluded: [], limitations: ['合成目录；公告窗口未证明查全，不包含原文', '这是有限候选队列；行业筛选不重新扫描全行业。'], cache: { hit: false, age_seconds: null, refresh_failed: false },
};

export function researchCheckReadReply(path, search = '', reportStage = 0) {
  const params = new URLSearchParams(search);
  // Discovery opts out of data unwrapping. MyReports/evidence/campaign/thesis
  // use backend data envelopes. NativeIntel security context is a raw object.
  if (path === '/api/screener/discovery') return discoverySnapshot;
  if (path === '/api/myreports') return { data: reportStage ? [originalReport, revisedReport] : [originalReport] };
  if (path === '/api/myreports/fulltext-search') {
    const record = [originalReport, revisedReport].find(item => item.id === params.get('report_ids'));
    assert.ok(record && (record.id === originalReport.id || reportStage === 1));
    return { data: [{ report_id: record.id, title: record.title, name: record.name, page: 1, snippet: '合成命中仅用于定位，不是已读正文。', score: 1, publish_date: record.publish_date, institution: 'Synthetic fixture', source_url: record.source_url, extraction_kind: 'DOCUMENT_TEXT' }] };
  }
  if (path === '/api/evidence') return { data: navigationEvidencePage([], params) };
  if (path === '/api/campaigns') return { data: [] };
  if (path === '/api/thesis') return { data: { items: [], total: 0, limit: Number(params.get('limit') || 50), offset: Number(params.get('offset') || 0) } };
  if (path === '/api/native-intel/security-context/600519') return { status: 'normal', retrieved_at: '2026-10-22T02:01:00Z', authority_ref: 'vibe:native-intel:synthetic', usage_boundary: 'observation_only_not_an_investment_authority', security: { code: '600519', company_name: '合成公司' }, mapping: { status: 'MAPPED', term_count: 1, terms: [{ term: '600519', term_kind: 'security_code', source_ref: 'synthetic' }], errors: [] }, window_hours: 24, observation: { items: [], item_count: 0, mention_count: 0, source_count: 0, first_seen_at: null, last_seen_at: null }, rank_history: { available: false, reason: 'synthetic_has_no_rank' } };
  return null;
}
export function researchCheckPageReadReply(input, reportStage = 0) {
  const record = [originalReport, revisedReport].find(item => item.id === input.report_id);
  assert.ok(record && (record.id === originalReport.id || reportStage === 1), 'T0 cannot retrieve later information');
  assert.equal(input.expected_file_sha256, record.file_sha256);
  assert.deepEqual(input.selected_report_ids, [record.id]);
  const text = record.id === originalReport.id ? originalText : revisedText;
  const requested = Array.from({ length: input.page_to - input.page_from + 1 }, (_, i) => input.page_from + i);
  return { data: { report_id: record.id, file_sha256: record.file_sha256, scope: 'INDEXED_PAGE_TEXT_ONLY', full_report_read: false, requested, returned_chars: text.length, complete_requested_text: requested.length === 1,
    coverage: { readable: [requested[0]], omitted: requested.slice(1), invalid: [], unreadable: [], error: [] }, items: requested.map((page, i) => i ? ({ page, status: 'omitted', reason: 'BUDGET' }) : ({ page, status: 'readable', reason: 'AVAILABLE', text, returned_chars: text.length, indexed_chars: text.length, truncated: false })) } };
}

// Deliberately non-UUID IDs accepted by the existing model. No user records.
export function resumeContextFixture() {
  const specs = [
    [' Q1 /?&=#+% ', '600519', 'watching', 3],
    ['Q2-已解决', '600519', 'resolved', 3],
    ['B-Q1', '000001', 'watching', 1],
    ['B-Q2', '000001', 'archived', 1],
    ['paused-empty', '600519', 'paused', 0],
  ];
  const questions = [], rounds = [];
  for (const [id, securityCode, status, count] of specs) {
    const chain = Array.from({ length: count }, (_, i) => ({ id: `${id}/轮次 ${i + 1}?&=#+%`, questionId: id, securityCode,
      parentRoundId: i ? `${id}/轮次 ${i}?&=#+%` : null, createdAt: 100 + i, materials: [], calculation: null,
      judgement: `${id} 第${i + 1}轮原判断`, limitations: '合成局部材料，非真实研究', nextMaterial: '下一项合成材料', reviewedMaterialKeys: [], ignoredMaterialKeys: [], coverage: 'partial' }));
    questions.push({ id, securityCode, question: `合成接续问题 ${id}`, origin: { kind: 'manual', label: '导航回归合成夹具', capturedAt: 99 }, createdAt: 100, updatedAt: 100 + Math.max(0, count - 1), revision: count, headRoundId: chain.at(-1)?.id ?? null, status, reviewedMaterialKeys: [] });
    rounds.push(...chain);
  }
  return { questions, rounds };
}

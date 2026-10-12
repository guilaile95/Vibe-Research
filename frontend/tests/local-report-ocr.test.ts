import test from 'node:test';
import assert from 'node:assert/strict';
import { parseLocalReportOcrReceipt, parseLocalReportIdentity, validateReportPageOcrResponse, parseLocalOcrCapability } from '../src/lib/localReportOcr.ts';
const receipt = () => ({ schema_version: 'local_ocr_report_receipt.v1', report_id: 'synthetic', file_sha256: 'a'.repeat(64), status: 'SEARCHABLE', indexed_at: '2026-10-12T10:00:00Z',
  extraction: { schema_version: 'local_ocr_preview.v1', status: 'OCR_UNVERIFIED', source_sha256: 'a'.repeat(64), engine: 'local-tesseract', language: 'eng', source_truth_verified: false,
    limitations: ['uncertain synthetic text'], pages: [{ page_number: 1, source_sha256: 'a'.repeat(64), image_sha256: 'b'.repeat(64), text_sha256: 'c'.repeat(64), mean_word_confidence: 93 }] } });
test('saved OCR receipt is source/report/language/hash/uncertainty bound', () => {
  assert.equal(parseLocalReportOcrReceipt(receipt(), 'synthetic', 'a'.repeat(64), 'eng').extraction.pages.length, 1);
  for (const change of [{ report_id: 'other' }, { file_sha256: 'b'.repeat(64) }, { status: 'OK' }, { schema_version: 'v0' }, { indexed_at: 'unknown' }]) {
    assert.throws(() => parseLocalReportOcrReceipt({ ...receipt(), ...change }, 'synthetic', 'a'.repeat(64), 'eng'));
  }
  for (const change of [{ language: 'chi_sim+eng' }, { engine: 'remote' }, { source_truth_verified: true }, { source_sha256: 'b'.repeat(64) }, { pages: [] }, { schema_version: 'v0' }]) {
    const value = receipt(); Object.assign(value.extraction, change);
    assert.throws(() => parseLocalReportOcrReceipt(value, 'synthetic', 'a'.repeat(64), 'eng'));
  }
  for (const change of [{ page_number: 2 }, { image_sha256: 'bad' }, { text_sha256: 'bad' }, { mean_word_confidence: NaN }, { source_sha256: 'b'.repeat(64) }]) {
    const value = receipt(); Object.assign(value.extraction.pages[0], change);
    assert.throws(() => parseLocalReportOcrReceipt(value, 'synthetic', 'a'.repeat(64), 'eng'));
  }
});

test('receipt timestamp rejects normalization and requires timezone', () => {
  for (const indexed_at of ['0000-01-01T00:00:00Z', '2026-02-30T12:00:00Z', '2026-10-12T24:00:00Z', '2026-10-12T12:60:00Z', '2026-10-12T12:00:00', '2026-10-12T12:00:00+14:30', '2026-10-12T12:00:00+24:00']) {
    assert.throws(() => parseLocalReportOcrReceipt({ ...receipt(), indexed_at }, 'synthetic', 'a'.repeat(64), 'eng'));
  }
  for (const indexed_at of ['2024-02-29T23:59:59.123456+00:00', '2026-10-12T12:00:00+08:00']) {
    assert.equal(parseLocalReportOcrReceipt({ ...receipt(), indexed_at }, 'synthetic', 'a'.repeat(64), 'eng').indexed_at, indexed_at);
  }
});


test('legacy read-only identity binds code, extension and immutable digest', () => {
  const identity = { report_id: 'legacy', extension: '.png', file_sha256: 'a'.repeat(64), writes: 0 };
  assert.equal(parseLocalReportIdentity(identity, 'legacy', '.png'), 'a'.repeat(64));
  for (const changes of [{ report_id: 'other' }, { extension: '.pdf' }, { file_sha256: 'bad' }, { writes: 1 }, { path: '/private' }]) {
    assert.throws(() => parseLocalReportIdentity({ ...identity, ...changes }, 'legacy', '.png'));
  }
});

test('page reader rejects malformed or foreign OCR metadata before rendering', () => {
  const value = { report_id: 'synthetic', file_sha256: 'a'.repeat(64), scope: 'INDEXED_PAGE_TEXT_ONLY', full_report_read: false,
    requested: [1], returned_chars: 4, items: [{ page: 1, status: 'readable', reason: 'INDEXED_TEXT', text: 'text' }],
    coverage: { readable: [1], omitted: [], invalid: [], unreadable: [], error: [] }, extraction: receipt().extraction };
  assert.doesNotThrow(() => validateReportPageOcrResponse(value, 'synthetic', 'a'.repeat(64)));
  assert.doesNotThrow(() => validateReportPageOcrResponse({ ...value, extraction: undefined }, 'synthetic', 'a'.repeat(64)));
  for (const extraction of [{ ...value.extraction, pages: null }, { ...value.extraction, engine: {} }, { ...value.extraction, source_sha256: 'b'.repeat(64) }, { ...value.extraction, limitations: {} }, { ...value.extraction, extra: 'private' }]) {
    assert.throws(() => validateReportPageOcrResponse({ ...value, extraction }, 'synthetic', 'a'.repeat(64)));
  }
  assert.throws(() => validateReportPageOcrResponse({ ...value, items: [{ page: 1, status: 'readable', reason: '__proto__' }] }, 'synthetic', 'a'.repeat(64)));
});


test('capability requires consistent local engine, resource and installed language status', () => {
  const value = { engine: 'local-tesseract', image: true, pdf: true, status: 'AVAILABLE', automatic_language_fallback: false,
    english_language_status: 'INSTALLED_QUALITY_NOT_VERIFIED', chinese_language_status: 'CHINESE_LANGUAGE_UNAVAILABLE' };
  assert.equal(parseLocalOcrCapability(value).image, true);
  assert.equal(parseLocalOcrCapability({ ...value, image: false, pdf: false, status: 'DEPENDENCY_UNAVAILABLE' }).image, false);
  for (const changes of [{ image: {} }, { engine: 'remote' }, { status: 'DEPENDENCY_UNAVAILABLE' }, { image: false, status: 'DEPENDENCY_UNAVAILABLE' },
    { english_language_status: 'ENGLISH_LANGUAGE_UNAVAILABLE' }, { english_language_status: {} }, { chinese_language_status: 'READY' }, { automatic_language_fallback: true }]) {
    assert.throws(() => parseLocalOcrCapability({ ...value, ...changes }));
  }
});

"""Local, unverified document research. Never fetches or invokes a model.

Registration stores exact user-supplied text and source assertions immutably.
The existing evidence claim and formal thesis remain separate authorities.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

import evidence_thesis_service as svc
import evidence_thesis_store as store

MAX_TEXT = 200_000
FORMS = {'10-K', '10-K/A', '10-Q', '10-Q/A', '8-K', '8-K/A', 'announcement'}


class Conflict(ValueError):
    pass


def safe_url(value):
    try:
        parsed = urlsplit(value or '')
        if parsed.scheme in ('https', 'http') and parsed.hostname and not parsed.username and not parsed.password and not any(c.isspace() or ord(c) < 32 for c in value):
            return value
    except ValueError:
        pass
    return None


def structure(text, form):
    """Conservative plain-text Item extraction; ambiguous headings never guessed.

    Original whitespace, numbers and tables survive via exact character offsets.
    TOC page-number lines are excluded; duplicate keys disable Item extraction.
    10-Q Items require an explicit Part I/II; 10-K has global Item numbering.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise ValueError('原文须为 1–200000 字的纯文本')
    if form not in FORMS:
        raise ValueError('不支持的文档类型')
    sections = [{'key': 'document', 'title': '完整原文', 'start': 0, 'end': len(text)}]
    if form == 'announcement':
        return sections, ['公告仅提供完整原文；未推断章节或附件']
    part, offset, headings, keys, ambiguous = None, 0, [], set(), False
    part_offsets = []
    saw_toc, saw_toc_page = False, False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.upper() == 'TABLE OF CONTENTS':
            saw_toc = True
        pm = re.fullmatch(r'PART\s+(I|II|III|IV)\s*[.:]?', stripped, re.I)
        if pm:
            part = pm[1].upper()
            part_offsets.append(offset)
        match = re.fullmatch(r'ITEM\s+(\d{1,2}(?:\.\d{2}|[A-C])?)\s*[.:]?\s+(.{1,150})', stripped, re.I)
        page_reference = bool(re.search(r'(?:\.{2,}|\s)\s*\d+\s*$', stripped))
        if match and page_reference and saw_toc:
            saw_toc_page = True
        if match and not page_reference:
            if saw_toc and not saw_toc_page:
                ambiguous = True
            number = match[1].upper()
            quarterly = form.startswith('10-Q')
            if quarterly and part not in ('I', 'II'):
                ambiguous = True
            else:
                key = f'part-{part}/item-{number}' if quarterly else f'item-{number}'
                if key in keys:
                    ambiguous = True
                keys.add(key)
                headings.append({'key': key, 'title': stripped, 'start': offset})
        offset += len(line)
    if ambiguous:
        return sections, ['章节标题重复或 Part 缺失；仅保留完整原文，拒绝猜测目录与正文']
    for i, heading in enumerate(headings):
        heading['end'] = headings[i + 1]['start'] if i + 1 < len(headings) else len(text)
        if form.startswith('10-Q'):
            heading['end'] = min([heading['end']] + [p for p in part_offsets if heading['start'] < p < heading['end']])
        sections.append(heading)
    return sections, ([] if headings else ['未识别可靠 Item 标题；仅提供完整原文'])


def _ensure(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS research_filing_documents (
        id TEXT PRIMARY KEY, evidence_id TEXT NOT NULL, issuer TEXT NOT NULL,
        payload TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS research_filing_issuer ON research_filing_documents(issuer)')
    conn.execute('CREATE INDEX IF NOT EXISTS research_filing_evidence ON research_filing_documents(evidence_id)')


def _evidence(conn, evidence_id):
    row = store._get_evidence_row(conn, evidence_id)
    if not row or row['deleted']:
        raise ValueError('证据不存在或已删除')
    if row['subject_type'] != 'stock' or row['evidence_type'] not in ('financial_filing', 'announcement'):
        raise ValueError('仅支持个股财报或公告证据')
    return store._evidence_row_to_dict(row)


def _document(conn, document_id):
    if not store._table_exists(conn, 'research_filing_documents'):
        raise ValueError('文档不存在')
    row = conn.execute('SELECT payload FROM research_filing_documents WHERE id=?', (document_id,)).fetchone()
    if not row:
        raise ValueError('文档不存在')
    return json.loads(row['payload'])


def register(evidence_id, payload, db_path=None):
    sections, warnings = structure(payload['text'], payload['form'])
    for field in ('source_identity', 'revision', 'source_title'):
        if not isinstance(payload[field], str) or not payload[field].strip() or len(payload[field]) > 300:
            raise ValueError('来源身份、版本及标题须为 1–300 字')
    try:
        datetime.strptime(payload['source_date'], '%Y-%m-%d') if payload.get('source_date') else None
    except (ValueError, TypeError):
        raise ValueError('请填写来源日期 YYYY-MM-DD') from None
    if payload.get('source_url') and not safe_url(payload['source_url']):
        raise ValueError('来源链接必须是无凭据的 HTTP(S) URL')
    def write(conn):
        evidence = _evidence(conn, evidence_id)
        if evidence['edit_token'] != payload['expected_edit_token']:
            raise Conflict('证据已变化，请刷新后重新确认')
        previous = None
        if payload.get('corrects_id'):
            previous = _document(conn, payload['corrects_id'])
            if previous['evidence_id'] != evidence_id or previous['form'] != payload['form'] or previous['source_identity'] != payload['source_identity']:
                raise Conflict('更正必须属于同一证据、文档身份及类型')
            if previous['revision'] == payload['revision']:
                raise Conflict('更正须使用新版本标识')
        _ensure(conn)
        documents = [json.loads(r[0]) for r in conn.execute('SELECT payload FROM research_filing_documents WHERE evidence_id=?', (evidence_id,))]
        if len(documents) >= 100:
            raise ValueError('单条证据最多登记 100 个文档版本')
        if any(d['source_identity'] == payload['source_identity'] and d['revision'] == payload['revision'] for d in documents):
            raise Conflict('来源身份及版本已登记；请使用新版本进行更正')
        doc = {key: payload.get(key) for key in ('source_identity', 'revision', 'source_title', 'source_date', 'source_url', 'form', 'text', 'corrects_id')}
        doc.update(id=str(uuid.uuid4()), evidence_id=evidence_id, issuer=evidence['subject_id'],
                   evidence_snapshot=evidence, provenance='USER_SUPPLIED_UNVERIFIED',
                   registered_at=datetime.now(timezone.utc).isoformat(), strict_asof_eligible=False,
                   sha256=hashlib.sha256(payload['text'].encode()).hexdigest(),
                   sections=sections, warnings=warnings, attachments=[], attachments_status='NOT_REGISTERED')
        conn.execute('INSERT INTO research_filing_documents VALUES (?,?,?,?)',
                     (doc['id'], evidence_id, doc['issuer'], json.dumps(doc, ensure_ascii=False)))
        return doc
    return store.write_transaction(svc.resolve_db_path(db_path), write)


def context(evidence_id, db_path=None):
    def read(conn):
        evidence = _evidence(conn, evidence_id)
        docs = []
        own_exists = False
        if store._table_exists(conn, 'research_filing_documents'):
            own_exists = conn.execute('SELECT 1 FROM research_filing_documents WHERE evidence_id=? LIMIT 1', (evidence_id,)).fetchone() is not None
            docs = [json.loads(r[0]) for r in conn.execute("""SELECT d.payload FROM research_filing_documents d
                JOIN evidence_records e ON e.id=d.evidence_id
                WHERE d.issuer=? AND e.deleted=0 AND e.subject_type='stock'
                  AND e.evidence_type IN ('financial_filing','announcement')
                ORDER BY (d.evidence_id=?) DESC, d.rowid DESC LIMIT 101""", (evidence['subject_id'], evidence_id))]
        has_more = len(docs) > 100
        docs = docs[:100]
        return {'evidence': evidence, 'documents': [{k: v for k, v in d.items() if k not in ('text', 'evidence_snapshot')} for d in docs], 'has_more': has_more,
                'original_text_status': 'REGISTERED_UNVERIFIED' if own_exists else 'UNAVAILABLE',
                'notice': '资讯摘要与证据主张不是原始文档。仅比较已登记的用户纯文本；来源与完整性未经核验。'}
    return store.read_transaction(svc.resolve_db_path(db_path), read)


def compare(payload, db_path=None):
    def read(conn):
        old, new = [_document(conn, payload[key]) for key in ('before_id', 'after_id')]
        for doc in (old, new):
            _evidence(conn, doc['evidence_id'])
        if old['id'] == new['id']:
            raise Conflict('请选择两个不同文档版本')
        if old['issuer'] != new['issuer'] or old['form'] != new['form']:
            raise Conflict('仅允许同一发行人、完全相同申报类型的比较（修订类型不混用）')
        texts = []
        for doc in (old, new):
            section = next((s for s in doc['sections'] if s['key'] == payload['section']), None)
            if not section:
                raise Conflict('两个文档必须均有同一可靠章节')
            texts.append(doc['text'][section['start']:section['end']].splitlines(keepends=True))
        if max(map(len, texts)) > 2000 or len(texts[0]) * len(texts[1]) > 1_000_000:
            raise ValueError('比较超出复杂度限制，请选择更小的可靠章节；未截断原文')
        changes = [{'kind': tag, 'before': ''.join(texts[0][a:b]), 'after': ''.join(texts[1][c:d])}
                   for tag, a, b, c, d in difflib.SequenceMatcher(None, *texts, autojunk=False).get_opcodes()]
        return {'before': {k: old[k] for k in ('id', 'sha256', 'revision', 'source_identity')},
                'after': {k: new[k] for k in ('id', 'sha256', 'revision', 'source_identity')},
                'section': payload['section'], 'changes': changes, 'method': 'EXACT_LINE_DIFF',
                'interpretation': 'NOT_GENERATED', 'provenance': 'USER_SUPPLIED_UNVERIFIED'}
    return store.read_transaction(svc.resolve_db_path(db_path), read)


def document(document_id, db_path=None):
    def read(conn):
        doc = _document(conn, document_id)
        _evidence(conn, doc['evidence_id'])
        return doc
    return store.read_transaction(svc.resolve_db_path(db_path), read)

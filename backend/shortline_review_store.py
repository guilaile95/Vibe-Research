"""Append-only segmented reviews in the existing review DB; no import-time I/O."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

import review_history
from daily_review_basis import _stamp
import review_store
import short_term_fact_store as facts_store
import shortline_review_contract as C

TABLE = "shortline_review_versions"
SQL = f"""CREATE TABLE IF NOT EXISTS {TABLE} (
 generation_id TEXT PRIMARY KEY, mode TEXT NOT NULL, trade_date TEXT NOT NULL,
 bundle_id TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
 created_at TEXT NOT NULL
)"""


def read_image(path=None):
    """Stable bounded source bytes to private SQLite memory; no WAL/SHM creation."""
    path=Path(path or review_history.resolve_review_db_path())
    if any(p.is_symlink() for p in (path,*path.parents)): raise ValueError("review archive unavailable")
    if not path.exists(): return None
    def fingerprint():
        if any(p.is_symlink() for p in (path,*path.parents)): raise ValueError("review archive unavailable")
        s=path.stat()
        if not stat.S_ISREG(s.st_mode) or not 100<=s.st_size<=64*1024*1024: raise ValueError("review archive unavailable")
        for suffix in ("-wal","-journal","-shm"):
            p=Path(str(path)+suffix)
            if p.is_symlink() or (p.exists() and (not p.is_file() or (suffix!="-shm" and p.stat().st_size))): raise ValueError("review archive busy")
        return facts_store._archive_stat_fingerprint(s)
    before=fingerprint();descriptor=None
    def read():
        nonlocal descriptor
        with os.fdopen(os.open(path,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)),"rb") as f:
            current=facts_store._archive_stat_fingerprint(os.fstat(f.fileno()))
            if not facts_store._archive_descriptor_matches_path(before,current): raise ValueError("review archive changed")
            if descriptor is not None and current!=descriptor: raise ValueError("review archive changed")
            descriptor=current;raw=f.read(64*1024*1024+1)
            if facts_store._archive_stat_fingerprint(os.fstat(f.fileno()))!=descriptor: raise ValueError("review archive changed")
        if len(raw)!=before[2] or fingerprint()!=before: raise ValueError("review archive changed")
        return raw
    raw=read()
    if read()!=raw or raw[:16]!=b"SQLite format 3\0" or raw[18:20] not in (b"\x01\x01",b"\x02\x02"): raise ValueError("review archive invalid")
    page_size=int.from_bytes(raw[16:18],"big");page_size=65536 if page_size==1 else page_size
    pages=int.from_bytes(raw[28:32],"big")
    if page_size<512 or page_size>65536 or page_size&(page_size-1) or len(raw)%page_size or not 1<=pages<=len(raw)//page_size:raise ValueError("review archive invalid")
    private=bytearray(raw);private[18:20]=b"\x01\x01"
    conn=sqlite3.connect(":memory:");conn.row_factory=sqlite3.Row
    try: conn.deserialize(bytes(private));conn.execute("PRAGMA query_only=ON");conn.execute("PRAGMA trusted_schema=OFF")
    except Exception: conn.close();raise
    return conn


def table_exists(conn,name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() is not None


def read_daily_snapshot(day):
    C.day(day);conn=read_image()
    if conn is None:return None
    try:
        if not table_exists(conn,"daily_review_snapshots"):return None
        row=conn.execute("SELECT * FROM daily_review_snapshots WHERE trade_date=? ORDER BY generated_at DESC,id DESC LIMIT 1",(day,)).fetchone()
        if row is None:return None
        value=review_store._row_to_full(row);review=value["review"]
        if type(review) is not dict or review.get("trade_date")!=day or review_store._payload_hash(review)!=value["payload_hash"]:raise ValueError("snapshot identity mismatch")
        for key in ("generated_at","schema_version","status","data_cutoff"):
            if review.get(key)!=value[key]:raise ValueError("snapshot metadata mismatch")
        return value
    finally:conn.close()


def validate_version(value):
    keys={"schema_version","generation_id","mode","trade_date","bundle","stages","created_at","model_provider","model_name","status","fact_verification"}
    if type(value) is not dict or set(value)!=keys or value["schema_version"]!=C.SCHEMA:raise ValueError("invalid review version")
    if type(value["generation_id"]) is not str or not re.fullmatch(r"[0-9a-f]{32}",value["generation_id"]):raise ValueError("invalid generation identity")
    C.validate_bundle(value["bundle"])
    if value["mode"]!=value["bundle"]["mode"] or value["trade_date"]!=value["bundle"]["trade_date"]:raise ValueError("version identity mismatch")
    if value["status"] not in ("generated_unverified","requires_review") or value["fact_verification"]!="NOT_PERFORMED":raise ValueError("invalid verification claim")
    for k in ("created_at","model_provider","model_name"):
        if type(value[k]) is not str or not 1<=len(value[k])<=120:raise ValueError("invalid version metadata")
    _stamp(value["created_at"])
    stages=value["stages"];expected=[x[0] for x in C.plan(value["mode"])]+["summary"]
    if type(stages) is not list or [x.get("id") if type(x)is dict else None for x in stages]!=expected:raise ValueError("invalid saved stages")
    eligible=[]
    for index,s in enumerate(stages):
        if set(s)!={"id","label","status","text","audit","reason_codes","evidence_ids","bundle_id"} or s["bundle_id"]!=value["bundle"]["bundle_id"]:raise ValueError("invalid stage identity")
        if s["status"] not in C.STATUSES or type(s["text"]) is not str or len(s["text"])>C.MAX_SECTION_CHARS:raise ValueError("invalid stage output")
        if type(s["reason_codes"]) is not list or len(s["reason_codes"])>20 or any(type(x)is not str or not re.fullmatch(r"[A-Z_]{1,64}",x) for x in s["reason_codes"]):raise ValueError("invalid stage errors")
        if type(s["evidence_ids"]) is not list or len(s["evidence_ids"])>C.MAX_EVIDENCE*5 or any(type(x)is not str or not re.fullmatch(r"ev-[0-9a-f]{16}",x) for x in s["evidence_ids"]):raise ValueError("invalid stage references")
        evidence = value["bundle"]["sections"][index]["evidence"] if index < len(stages)-1 else eligible
        if s["evidence_ids"] != [e["id"] for e in evidence]:raise ValueError("stage scope mismatch")
        expected_label = C.plan(value["mode"])[index][1] if index < len(stages)-1 else "汇总"
        if s["label"] != expected_label:raise ValueError("stage label mismatch")
        empty={"status":"not_run","reason_codes":[],"unknown_reference_count":0,"arithmetic_warning_count":0,"unbound_number_count":0,"fact_verification":"NOT_PERFORMED"}
        if s["status"] == "skipped":
            if any(e["value"] is not None for e in evidence) or s["text"] or s["audit"]!=empty:raise ValueError("invalid skipped stage")
        elif s["status"] in ("generated","requires_review"):
            audit=C.audit_text(s["text"],evidence)
            expected="requires_review" if audit["status"]=="requires_review" else "generated"
            if not s["text"].strip() or not evidence or s["audit"]!=audit or s["status"]!=expected or s["reason_codes"]!=audit["reason_codes"]:raise ValueError("stage audit mismatch")
            if s["status"]=="generated" and index<len(stages)-1:
                known={e["id"] for e in eligible};eligible.extend(e for e in evidence if e["id"] not in known)
        else:raise ValueError("incomplete stage cannot be saved")
    expected_status="requires_review" if any(s["status"]=="requires_review" for s in stages) else "generated_unverified"
    if value["status"]!=expected_status or not any(s["text"] for s in stages):raise ValueError("invalid overall review status")
    if len(C.canonical(value).encode())>C.MAX_VERSION_BYTES:raise ValueError("version exceeds limit")
    return value


def _decode(row):
    if len(row["payload_json"].encode())>C.MAX_VERSION_BYTES:raise ValueError("oversized stored version")
    value=json.loads(row["payload_json"])
    if C.digest(value)!=row["payload_hash"]:raise ValueError("stored version hash mismatch")
    validate_version(value)
    if any(value[k]!=row[k] for k in ("generation_id","mode","trade_date")) or value["bundle"]["bundle_id"]!=row["bundle_id"]:raise ValueError("stored version identity mismatch")
    return value


def get_version(generation_id):
    if type(generation_id)is not str or not re.fullmatch(r"[0-9a-f]{32}",generation_id):raise ValueError("invalid generation identity")
    conn=read_image()
    if conn is None:return None
    try:
        if not table_exists(conn,TABLE):return None
        row=conn.execute(f"SELECT * FROM {TABLE} WHERE generation_id=?",(generation_id,)).fetchone()
        return _decode(row) if row else None
    finally:conn.close()


def list_versions(day,mode):
    C.day(day);C.plan(mode);conn=read_image()
    if conn is None:return []
    try:
        if not table_exists(conn,TABLE):return []
        rows=conn.execute(f"SELECT * FROM {TABLE} WHERE trade_date=? AND mode=? ORDER BY created_at DESC,generation_id DESC LIMIT 30",(day,mode)).fetchall()
        values=[_decode(row) for row in rows]
        return [{k:v[k] for k in ("generation_id","mode","trade_date","created_at","status")} for v in values]
    finally:conn.close()


def append_version(value,should_cancel=lambda:False):
    validate_version(value)
    if should_cancel():raise ValueError("review cancelled")
    path=Path(review_history.resolve_review_db_path())
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError("unsafe review archive")
    path.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(path,timeout=5);conn.row_factory=sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE");conn.execute(SQL)
        row=conn.execute(f"SELECT * FROM {TABLE} WHERE generation_id=?",(value["generation_id"],)).fetchone()
        if row:
            old=_decode(row)
            if old["bundle"]["bundle_id"]!=value["bundle"]["bundle_id"]:raise ValueError("generation reuse conflict")
            conn.rollback();return old
        conn.execute(f"INSERT INTO {TABLE} VALUES (?,?,?,?,?,?,?)",(value["generation_id"],value["mode"],value["trade_date"],value["bundle"]["bundle_id"],C.canonical(value),C.digest(value),value["created_at"]))
        if should_cancel():raise ValueError("review cancelled")
        conn.commit();return value
    except Exception:conn.rollback();raise
    finally:conn.close()

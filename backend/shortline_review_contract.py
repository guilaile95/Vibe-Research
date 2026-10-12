"""Finite evidence-only contracts for segmented reviews; no providers or model calls."""
from __future__ import annotations
from datetime import date, datetime, timezone
import hashlib
import json
import math
import re

SCHEMA = "shortline-segmented-review.v1"
DAILY = (("sentiment", "情绪"), ("capital", "资金"), ("theme", "题材"), ("dragon_tiger", "龙虎榜"), ("leader", "龙头"))
WEEKLY = (("trend", "情绪走势"), ("themes", "题材轮动"), ("verify", "验证回看"))
MAX_EVIDENCE = 160
MAX_SECTION_CHARS = 12000
MAX_TOTAL_CHARS = 60000
MAX_BUNDLE_BYTES = 256 * 1024
MAX_SECTION_INPUT_BYTES = 32 * 1024
MAX_PROMPT_BYTES = 256 * 1024
MAX_VERSION_BYTES = 1024 * 1024
MAX_STAGE_SECONDS = 180
MAX_TOTAL_SECONDS = 720
STATUSES = {"generated", "requires_review", "skipped", "failed"}
BASIS = {"selection_mode": "CURRENT_STORED_POSTHOC", "point_in_time_claim": "NONE", "canonical_authority": False}


def day(value):
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value): raise ValueError("invalid review date")
    date.fromisoformat(value)
    return value


def plan(mode):
    if mode not in ("daily", "weekly"): raise ValueError("invalid review mode")
    return DAILY if mode == "daily" else WEEKLY


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()


def safe_text(value, size=120):
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(value))[:size]


def evidence_from(source, day_value, identity, value, *, maximum=MAX_EVIDENCE, origin="UNCLASSIFIED"):
    """Bounded deterministic paths; numeric values and limited descriptive strings only.

    Caller supplies an allowlisted market-only subtree; never pass accounts/journals.
    Metadata, source errors, prompts and arbitrary raw strings are not evidence.
    """
    out, omitted = [], 0
    text_keys = {"stock_code", "code", "name", "stock_name", "tag", "label", "state", "direction", "actual_direction", "actual", "metric", "verdict", "target_date", "set_date"}
    blocked = {"account", "portfolio", "holdings", "trades", "reason", "warnings", "error", "raw", "capture", "evidence", "source", "source_ids", "limitations", "generated_at", "fetched_at", "captured_at", "snapshot_at", "stored_at"}
    def walk(node, path, key, depth):
        nonlocal omitted
        if depth > 10: omitted += 1; return
        if type(node) is dict:
            for k in sorted(node):
                if type(k) is str and k not in blocked and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", k): walk(node[k], path + "." + k, k, depth + 1)
            return
        if type(node) is list:
            for i, item in enumerate(node[:300]): walk(item, f"{path}[{i}]", key, depth + 1)
            omitted += max(0, len(node) - 300); return
        valid = node is None or (type(node) in (int, float) and math.isfinite(node) and abs(node) <= 1e15) or (type(node) is str and key in text_keys)
        if not valid: return
        if len(out) >= maximum: omitted += 1; return
        val = safe_text(node) if type(node) is str else node
        unit = "percentage_points" if key.endswith("_pct") else "ratio" if key.endswith(("_rate", "_ratio")) else "YUAN" if key.endswith("_yuan") else "source_native"
        item = {"source": source, "trade_date": day_value, "source_identity": identity, "path": path, "value": val, "unit": unit,"origin":origin}
        item["id"] = "ev-" + digest(item)[:16]
        out.append(item)
    walk(value, source, "", 0)
    return out, omitted


def validate_bundle(bundle):
    if type(bundle) is not dict or set(bundle) != {"schema_version", "mode", "trade_date", "days", "sections", "bundle_id", *BASIS}:
        raise ValueError("invalid evidence bundle")
    if bundle["schema_version"] != SCHEMA or any(type(bundle[k]) is not type(v) or bundle[k] != v for k,v in BASIS.items()): raise ValueError("invalid evidence authority")
    specs = plan(bundle["mode"]); day(bundle["trade_date"])
    days = bundle["days"]
    if type(days) is not list or not 1 <= len(days) <= 10 or days != sorted(set(days)) or any(day(d) > bundle["trade_date"] for d in days): raise ValueError("invalid evidence dates")
    if bundle["mode"] == "daily" and days != [bundle["trade_date"]]: raise ValueError("invalid daily window")
    sections = bundle["sections"]
    if type(sections) is not list or [x.get("id") if type(x) is dict else None for x in sections] != [s[0] for s in specs]: raise ValueError("invalid evidence sections")
    for section, (sid,label) in zip(sections,specs):
        if set(section) != {"id","label","evidence","gaps","omitted_count"} or section["label"] != label: raise ValueError("invalid section contract")
        if type(section["evidence"]) is not list or len(section["evidence"]) > MAX_EVIDENCE: raise ValueError("excessive section evidence")
        if type(section["gaps"]) is not list or len(section["gaps"]) > 100 or any(type(x) is not str or not re.fullmatch(r"[A-Z0-9_:-]{1,100}",x) for x in section["gaps"]): raise ValueError("invalid gap codes")
        if type(section["omitted_count"]) is not int or not 0 <= section["omitted_count"] <= 100000: raise ValueError("invalid omission count")
        if len(canonical(section).encode())>MAX_SECTION_INPUT_BYTES:raise ValueError("section input exceeds limit")
        ids=set()
        for item in section["evidence"]:
            if type(item) is not dict or set(item)!={"id","source","trade_date","source_identity","path","value","unit","origin"}: raise ValueError("invalid evidence record")
            if item["trade_date"] not in days or item["id"] in ids: raise ValueError("invalid evidence identity/date")
            ids.add(item["id"])
            if item["origin"] not in ("FIXTURE","ACQUIRED","UNCLASSIFIED"):raise ValueError("invalid source origin")
            if not all(type(item[k]) is str and len(item[k]) <= limit for k,limit in (("source",64),("source_identity",64),("path",400),("unit",32))): raise ValueError("unbounded evidence metadata")
            if not re.fullmatch(r"[0-9a-f]{64}",item["source_identity"]): raise ValueError("invalid source identity")
            v=item["value"]
            if not (v is None or (type(v) in (int,float) and math.isfinite(v) and abs(v)<=1e15) or (type(v) is str and len(v)<=120)): raise ValueError("invalid evidence value")
            base={k:v for k,v in item.items() if k!="id"}
            if item["id"] != "ev-"+digest(base)[:16]: raise ValueError("evidence digest mismatch")
    base={k:v for k,v in bundle.items() if k!="bundle_id"}
    if bundle["bundle_id"] != digest(base) or len(canonical(bundle).encode()) > MAX_BUNDLE_BYTES: raise ValueError("bundle hash/size mismatch")
    return bundle


def finalize_bundle(mode, end, days, sections):
    b={"schema_version":SCHEMA,"mode":mode,"trade_date":end,"days":days,"sections":sections,**BASIS}
    b["bundle_id"]=digest(b)
    return validate_bundle(b)


def audit_text(text, evidence):
    import ai_answer_quality
    refs=set(re.findall(r"ev-[A-Za-z0-9_-]+",text));known={e["id"] for e in evidence}
    unknown=sorted(refs-known)[:20]
    equations=ai_answer_quality.ratio_equation_warnings(text)
    numeric={float(e["value"]) for e in evidence if type(e["value"]) in (int,float)}
    # A deliberately conservative unsupported-number signal, never a truth gate.
    prose=re.sub(r"ev-[A-Za-z0-9_-]+|\b\d{4}-\d{2}-\d{2}\b|\b\d{6}\b", "", text)
    numbers=[float(x) for x in re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?",prose)[:200]]
    loose=sum(not any(abs(n-k)<=1e-6*max(1,abs(k)) for k in numeric) for n in numbers)
    issues=[]
    if unknown: issues.append("UNKNOWN_EVIDENCE_REFERENCE")
    if equations: issues.append("ARITHMETIC_CONTRADICTION")
    if loose: issues.append("UNBOUND_NUMBER")
    if numbers and not refs: issues.append("MISSING_NUMERIC_CITATION")
    return {"status":"requires_review" if issues else "no_detected_issue_not_verified", "reason_codes":issues,
            "unknown_reference_count":len(unknown),"arithmetic_warning_count":len(equations),"unbound_number_count":loose,
            "fact_verification":"NOT_PERFORMED"}

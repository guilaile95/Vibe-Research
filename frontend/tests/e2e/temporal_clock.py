"""Test-only domain clock. Production app never imports this module.

The file is private to one temporary E2E data directory. Both the HTTP process
and fixture subprocesses read it so advancing to review time never changes a
frozen decision's identity or bypasses temporal input validation.
"""
from datetime import datetime, timezone
import importlib
import os
from pathlib import Path


def utc_now_iso():
    instant = datetime.fromisoformat(Path(os.environ["E2E_CLOCK_FILE"]).read_text().strip().replace("Z", "+00:00"))
    if instant.tzinfo is None or instant.utcoffset().total_seconds() != 0:
        raise ValueError("E2E clock must be UTC")
    return instant.isoformat(timespec="microseconds").replace("+00:00", "Z")


def now():
    return datetime.fromisoformat(utc_now_iso().replace("Z", "+00:00"))


def install(setattr_fn=setattr):
    if not os.environ.get("E2E_CLOCK_FILE"):
        return
    utc_now_iso()  # Fail closed on missing/malformed fixture files.
    # Install commit clock before ChallengePorts captures it at module import.
    clocks = {
        "decision_commit_runtime": "utc_now_iso",
        "frozen_decision_service": "_utc_now_iso",
        "campaign_ai_draft_service": "utc_now_iso",
        "evidence_thesis_service": "_utc_now_iso",
        "evidence_thesis_store": "_utc_now_iso",
        "decision_trace_store": "_utc_now",
        "account_reality_service": "_utc_now",
        "position_reality_service": "_utc_now",
        "trade_ledger_store": "_utc_now",
        "trade_attribution_runtime": "_now",
        "formal_decision_outcome_runtime": "_now",
        "decision_inbox_runtime_assembler": "_utc_now_iso",
    }
    for module, field in clocks.items():
        setattr_fn(importlib.import_module(module), field, utc_now_iso)
    setattr_fn(importlib.import_module("trade_ledger_service"), "_execution_now", now)
    # Campaign timestamps use datetime directly rather than a clock port.
    class CampaignDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = now()
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    setattr_fn(importlib.import_module("campaign_service"), "datetime", CampaignDateTime)
    # Also handle imports made before install (unit tests and seed helpers).
    from dataclasses import replace
    challenge = importlib.import_module("decision_challenge_runtime")
    setattr_fn(challenge, "PRODUCTION_PORTS", replace(challenge.PRODUCTION_PORTS, clock=utc_now_iso))

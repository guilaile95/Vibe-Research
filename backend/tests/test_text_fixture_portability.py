"""Emulate Windows text defaults without changing process-wide UTF-8 settings."""
import ast
from pathlib import Path

import pytest

import test_filing_evidence as filing_tests
import test_research_quality_diagnostics as quality_tests
import test_valuation_digestion_contract as valuation_tests


def test_fixture_boundaries_explicitly_select_utf8():
    for module in (quality_tests, valuation_tests):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        reads = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "read_text"]
        assert reads
        for call in reads:
            assert any(keyword.arg == "encoding" and isinstance(keyword.value, ast.Constant)
                       and keyword.value.value == "utf-8" for keyword in call.keywords), (
                module.__name__, call.lineno, "UTF-8 fixture must not use locale default"
            )


def test_fixture_readers_work_with_cp1252_default(monkeypatch):
    original = Path.open

    def windows_default(path, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if "b" not in mode and encoding in (None, "locale"):
            encoding = "cp1252"
        return original(path, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, "open", windows_default)
    # Prove this emulation would catch the original locale-dependent read.
    with pytest.raises(UnicodeDecodeError):
        (quality_tests.FIXTURES / "company_research/US-AAPL.json").read_text()
    record, bundle = quality_tests.company()
    assert record and bundle
    assert valuation_tests.example_digest(60, 1, 2) == 1.0
    # Exercise the other non-ASCII dynamic fixture paths under the same default.
    quality_tests.test_saved_comparison_contract_keeps_qualified_source_ids()
    assert quality_tests.case_and_runs()[0]
    for label in ("irrelevant", "cross_company", "conflicting", "missing", "prompt_injection"):
        quality_tests.test_noise_inputs_without_saved_responses_have_no_robustness_evidence(label)


def test_oversized_filing_keeps_full_payload_with_short_pytest_ids():
    marks = [mark for mark in filing_tests.test_invalid_text.pytestmark if mark.name == "parametrize"]
    assert len(marks) == 1
    mark = marks[0]
    values, ids = mark.args[1], mark.kwargs["ids"]
    assert ids == ["empty", "whitespace", "over-limit"]
    assert len(values[-1]) == 200001
    assert values[-1] == "x" * 200001
    assert len(set(ids)) == len(values)
    for case_id in ids:
        nodeid = f"tests/test_filing_evidence.py::test_invalid_text[{case_id}] (teardown)"
        assert len(nodeid) < 128  # Far below Windows environment-variable limit.

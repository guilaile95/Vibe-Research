"""Synthetic arithmetic/transport regressions, NOT a real-model quality run."""
import pytest

import ai_answer_quality as quality


@pytest.mark.parametrize("equation,expected", [
    ("12÷20=−60%", "60%"),  # EV17's reported sign error.
    ("(8 - 20) / 20 = 60%", "-60%"),
    ("(10.1−7.2)÷7.2=28.7%", "40.277778%"),
    ("-12 / 20 = +60%", "-60%"),
    ("12 / -20 = 60%", "-60%"),
    ("(-8 - -20) / 20 = -60%", "60%"),
    ("12/20 × 100 = -60%", "60%"),
    ("12/20 × 100% = -60%", "60%"),
    ("12/20=-60％", "60%"),
    ("12/0=0%", "分母为 0"),
    ("原文错误示例：`12÷20=−60%`，不能采用", "60%"),
])
def test_literal_mismatch_is_reported_without_rewriting_or_source_claim(equation, expected):
    warnings = quality.ratio_equation_warnings(equation)
    assert len(warnings) == 1
    assert equation.strip("`") in warnings[0] or "12÷20=−60%" in warnings[0]
    assert expected in warnings[0]


@pytest.mark.parametrize("text", [
    "12÷20=60%", "(8−20)/20=−60%", "(10.1-7.2)/7.2=40.28%",
    "1/3=33.3%", "2/3=66.67%", "1/8=13%", "1/8=12%",
    "-12/-20=60%", "(8 - -20)/20=140%", "0/20=0%",
    "12/20×100%=60%", "12/20*100=60%",
    # Unsupported units, variables, chained expressions and grouped digits must
    # not be silently reduced to a supported suffix with a different meaning.
    "12亿元/20亿元=-60%", "12万元/20亿元=0.006%", "x12/20=-60%",
    "10 + 12/20=-60%", "10 - 12/20=-60%", "10 * (12-20)/20=40%",
    "1,012/20=-60%", "1, 012/20=-60%", "1e12/20=-60%",
    "(12/20)=-60%", "12/20/2=-60%", "12/20=60%xyz",
    "9999999999999999999/20=-60%", "12/20=60.1234567890123%",
    # Correct arithmetic does not establish an appropriate denominator.
    "(10.1-7.2)/10.1=28.71%",
    "S07-A第4页：同比25%；来源冲突值45和52不能证明区间",
])
def test_correct_rounding_and_unsupported_syntax_are_not_flagged(text):
    assert quality.ratio_equation_warnings(text) == []


@pytest.mark.parametrize("rhs", [
    "20% + 40%", "120% / 2", "30% * 2", "30%×2", "120%÷2",
    "80%−20%", "20%+40%", "120%\n / 2", "30%\t* 2",
    "20% ＋ 40%", "80% － 20%", "30% · 2", r"30% \times 2",
    "30% (2)", "30% ^ 2", "30% = x", "30% 2",
])
def test_compound_rhs_is_skipped_including_streamed_operator(rhs):
    text = f"12/20 = {rhs}"
    assert quality.ratio_equation_warnings(text) == []
    split = text.index("%") + 1
    original = [{"type": "delta", "text": text[:split]},
                {"type": "delta", "text": text[split:]}, {"type": "done"}]
    assert list(quality.audit_report_stream(iter(original))) == original


@pytest.mark.parametrize("text", [
    "1 ＋ 12/20 = 160%", "2 · 12/20 = 120%", "1 － 12/20 = 40%",
    "1 ＋\n 12/20 = 160%", "2 ·\t12/20 = 120%",
    "2 ^ 12/20 = 120%", r"2 \ 12/20 = 120%",
    r"2 \times 12/20 = 120%", r"2 \cdot 12/20 = 120%",
])
def test_compound_lhs_uses_same_conservative_operator_boundary(text):
    assert quality.ratio_equation_warnings(text) == []


def test_findings_are_bounded_and_deduplicated():
    assert len(quality.ratio_equation_warnings("12/20=-60%。" * 20)) == 1
    assert len(quality.ratio_equation_warnings("；".join(f"{n}/20=-60%" for n in range(10)))) == 3
    assert quality.ratio_equation_warnings("12/20=-60%" + "x" * quality._MAX_ANSWER_CHARS) == []


def test_stream_keeps_original_deltas_and_done_while_checking_across_chunks():
    original = [{"type": "delta", "text": "更正：12÷"}, {"type": "delta", "text": "20=−60%"},
                {"type": "done", "trace": [], "rounds": 1}]
    result = list(quality.audit_report_stream(iter(original)))
    assert result[:2] == original[:2] and result[-1] is original[-1]
    assert len(result) == 4
    assert "确定性算式复核提示" in result[-2]["text"]
    assert "含引述" in result[-2]["text"]
    assert "不代表核实来源、分母选择或整体结论" in result[-2]["text"]


@pytest.mark.parametrize("ending", [[], [{"type": "error", "message": "stopped"}],
    [{"type": "error", "message": "stopped"}, {"type": "done"}]])
def test_failed_or_incomplete_turn_has_no_audit_note(ending):
    original = [{"type": "delta", "text": "12/20=-60%"}, *ending]
    assert list(quality.audit_report_stream(iter(original))) == original


def test_normal_stream_and_oversized_stream_are_unchanged():
    for text in ["12/20=60%", "12/20=-60%" + " " * quality._MAX_ANSWER_CHARS]:
        original = [{"type": "delta", "text": text}, {"type": "done"}]
        assert list(quality.audit_report_stream(iter(original))) == original


def test_cancelling_audit_closes_upstream_without_extra_consumption():
    consumed = []
    closed = []
    def upstream():
        try:
            consumed.append(1)
            yield {"type": "delta", "text": "12/20=-60%"}
            consumed.append(2)
            yield {"type": "done"}
        finally:
            closed.append(True)
    stream = quality.audit_report_stream(upstream())
    next(stream)
    stream.close()
    assert consumed == [1] and closed == [True]


# Reuse the existing report fixture: synthetic PDF and isolated report directory.
from test_report_page_chat import setup, request, events  # noqa: E402, F401


@pytest.mark.parametrize("provider", ["api", "cli-codex"])
@pytest.mark.parametrize("explicit_pages", [True, False])
def test_report_http_path_audits_both_providers_without_retry(setup, monkeypatch, provider, explicit_pages):
    import app as app_module
    report, _ = setup
    called = []
    def synthetic(*args, **kwargs):
        called.append(True)
        yield {"type": "delta", "text": "更正后为8亿元，12÷"}
        yield {"type": "delta", "text": "20=−60%"}
        yield {"type": "done"}
    monkeypatch.setattr(app_module.chat_layer, "run_chat_stream", synthetic)
    monkeypatch.setattr(app_module.agent_runtime, "stream_chat", synthetic)
    overrides = {} if explicit_pages else {"report_page_context": None}
    result = events(request(report, provider, **overrides))
    assert called == [True]
    assert [event["type"] for event in result] == ["sources", "delta", "delta", "delta", "done"]
    assert "确定性算式复核提示" in result[-2]["text"] and "60%" in result[-2]["text"]


def test_non_report_chat_is_outside_this_bounded_audit(setup, monkeypatch):
    import app as app_module
    report, _ = setup
    original = [{"type": "delta", "text": "12/20=-60%"}, {"type": "done"}]
    monkeypatch.setattr(app_module.chat_layer, "run_chat_stream", lambda *args, **kwargs: iter(original))
    assert events(request(report, report_page_context=None, report_ids=[])) == original

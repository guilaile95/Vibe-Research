"""Pure synthetic grammar checks; arithmetic consistency never verifies facts."""
from decimal import Decimal, localcontext
from fractions import Fraction
import random

import pytest

import ai_answer_quality as quality


def diagnostic(text):
    records = quality._arithmetic_diagnostics(text)
    assert len(records) == 1, (text, records)
    return records[0]


@pytest.mark.parametrize("text,status,actual", [
    ("2亿元+3万元=5亿元", "mismatch", "2.0003"),
    ("2亿元+3万元=2.0003亿元", "consistent", "2.0003"),
    ("2亿+3万=2.0003亿", "consistent", "2.0003"),
    ("12万元/20亿元=60%", "mismatch", "0.006"),
    ("12万元/20亿元=0.006%", "consistent", "0.006"),
    ("2元+3元=5亿元", "mismatch", "0.00000005"),
    ("20000元+30000元=5万元", "consistent", "5"),
    ("1万亿元-5000亿元=0.5万亿元", "consistent", "0.5"),
    ("35%×200亿元=7000亿元", "mismatch", "70"),
    ("35%×200亿元=70亿元", "consistent", "70"),
    ("200亿元×35％=70亿元", "consistent", "70"),
    ("35%-20%=15%", "consistent", "15"),
    ("12万股/20万股=60%", "consistent", "60"),
    ("12元/20元=0.6倍", "consistent", "0.6"),
    ("1+2×3=9", "mismatch", "7"),
    ("1+2×3=7", "consistent", "7"),
    ("(1+2)×3=9", "consistent", "9"),
    ("8/2/2=2", "consistent", "2"),
    ("8/(2/2)=8", "consistent", "8"),
    ("-2×-3+1=-5", "mismatch", "7"),
    ("-2×-3+1=7", "consistent", "7"),
    ("−(2+3)×2=−10", "consistent", "-10"),
    ("2--3=5", "consistent", "5"),
    ("1+2+3=6", "consistent", "6"),
    ("1+2+3=7", "mismatch", "6"),
    ("12/20*100%=60%", "consistent", "60"),
    ("12/20*100=60%", "consistent", "60"),
    ("(8-20)/20*100=-60%", "consistent", "-60"),
    ("12/20*1000=60%", "mismatch", "60000"),
    ("12/20*100=60", "consistent", "60"),
    ("1+2＝3", "consistent", "3"),
])
def test_explicit_whole_expression_units_precedence_and_legacy_shape(text, status, actual):
    item = diagnostic(text)
    assert item.status == status and item.recomputed == Decimal(actual)
    assert item.raw == text and text[item.start:item.end] == text
    assert bool(quality.ratio_equation_warnings(text)) == (status == "mismatch")


@pytest.mark.parametrize("text,status", [
    ("444.64÷453.90−1=+0.2%", "mismatch"),
    ("444.64÷453.90−1=−2.04%", "consistent"),
    ("444.64亿÷4539000万−1=−2.04%", "consistent"),
    ("444.64亿÷45390万−1=−2.04%", "mismatch"),
    ("1÷3≈33.4%", "mismatch"),
    ("1÷3≈33.3%", "consistent"),
    ("40÷69≈58.0%", "consistent"),
    ("30÷49≈100%", "mismatch"),
    ("100−161≈−100", "mismatch"),
    ("48.5+48.5≈100", "consistent"),
    ("2199+0≈2200", "consistent"),
    ("10000+0=10001", "mismatch"),
    ("1.5+0=1", "consistent"),
    ("1.500000000001+0=1", "mismatch"),
    ("-1.5+0=-1", "consistent"),
    ("-1.500000000001+0=-1", "mismatch"),
    ("95+0≈100", "consistent"),
    ("94.999999999999+0≈100", "mismatch"),
    ("105+0≈100", "consistent"),
    ("105.000000000001+0≈100", "mismatch"),
    ("-105+0≈-100", "consistent"),
    ("-105.000000000001+0≈-100", "mismatch"),
    ("0.5+0≈0", "consistent"),
    ("0.500000000001+0≈0", "mismatch"),
    ("1.005+0≈1.00", "consistent"),
    ("1.005000000001+0≈1.00", "mismatch"),
    ("100.5+0=100", "consistent"),
    ("100.500000000001+0=100", "mismatch"),
    ("95+0≈100.0", "mismatch"),
    ("0.100000000001+0=0.100000000000", "mismatch"),
])
def test_yoy_and_display_grid_without_relative_error_floor(text, status):
    assert diagnostic(text).status == status


@pytest.mark.parametrize("displayed,approximate,expected", [
    ("2200", True, "50"), ("100", True, "5"), ("20", True, "1"),
    ("3", True, "0.5"), ("0", True, "0.5"), ("000", True, "0.5"),
    ("-100", True, "5"), ("−100", True, "5"), ("100.0", True, "0.05"),
    ("58.0", True, "0.05"), ("100", False, "0.5"), ("1.00", False, "0.005"),
])
def test_exact_approximation_tolerance_contract(displayed, approximate, expected):
    assert quality._tolerance(displayed, approximate) == Decimal(expected)


@pytest.mark.parametrize("text", [
    "100元+20%=100.2元", "2亿元+3=5亿元", "2元+3=5亿元",
    "19005.40-16821.09=2184.31亿元", "100元+20股=120元",
    "1元*2元=2元", "100亿元/8000万股=125元", "1/2元=0.5",
    "1元+2元=3股", "1亿+2亿=3", "35%+20=55%",
    "1亿%=1000000", "2万倍+3万倍=5万倍",
    "12/20=50%~70%", "12/20=50%～70%", "12/20=50%–70%",
    "12/20=50%—70%", "12/20=50% ± 10%", "12/20=50% 至 70%",
    "10–12/20=50%", "10—12/20=50%", "结论——12/20=50%",
    "12/20=[50%,70%]", "12/20=50%+10%", "12/20=120%/2",
    "1 ＋ 12/20=160%", "12/20=20% ＋ 40%", "2 · 12/20=120%",
    r"2 \times 12/20=120%", r"2 \cdot 12/20=120%", "2^12/20=50%",
    "x12/20=-60%", "x+12/20=-60%", "1e12/20=-60%",
    "1,012/20=-60%", "1, 012/20=-60%", "2026H1 12/20=-60%",
    "12 [ev-a]/20=-60%", "2(12/20)=120%", "12/20=60%=x",
    "--2+3=5", "1++-2=3", "1+2=--3", "1+2=NaN", "1+2=inf",
    "1/0+2元=3元", "1/0=0%+100%", "√12/20=-60%",
])
def test_unsupported_whole_candidates_never_become_passes_or_partial_warnings(text):
    items = quality._arithmetic_diagnostics(text)
    assert items and all(item.status == "unsupported" for item in items)
    assert quality.ratio_equation_warnings(text) == []


def test_resource_limits_and_no_tail_recovery():
    assert diagnostic("+".join(["1"] * 15) + "=15").status == "consistent"
    assert diagnostic("+".join(["1"] * 16) + "=16").reason == "operation_limit"
    assert diagnostic("(" * 4 + "1+1" + ")" * 4 + "=2").status == "consistent"
    assert diagnostic("(" * 5 + "1+1" + ")" * 5 + "=2").reason == "depth_limit"
    assert diagnostic("1" + " " * 507 + "+1=2").status == "consistent"
    assert diagnostic("1" + " " * 508 + "+1=2").reason == "candidate_limit"
    max_tokens = "+" + "+".join(["1亿元"] * 15) + "=15亿元"
    assert diagnostic(max_tokens).status == "consistent"  # 64 tokens, 16 operands.
    assert diagnostic("(" + max_tokens + ")").reason == "token_limit"
    assert diagnostic("999999999999999999+0=999999999999999999").status == "consistent"
    assert diagnostic("9999999999999999999+0=0").reason == "number_limit"
    assert diagnostic("0.1234567890123+0=0").reason == "number_limit"
    huge = "*".join(["999999999999999999"] * 8) + "=0"
    assert diagnostic(huge).reason == "magnitude_limit"
    tiny = "1/" + "/".join(["999999999999999999"] * 8) + "=0"
    assert diagnostic(tiny).reason == "magnitude_limit"
    assert quality._arithmetic_diagnostics("1+1=3" + " " * quality._MAX_ANSWER_CHARS) == []
    tail = "+".join(["1"] * 17) + "+12/20=-60%"
    assert diagnostic(tail).status == "unsupported"
    assert quality.ratio_equation_warnings(tail) == []


def test_precision_is_set_before_parsing_and_tiny_output_is_not_zero():
    text = "999999999999999999.123456789012元+0元=999999999999999999.123456789012元"
    with localcontext() as ctx:
        ctx.prec = 6
        assert diagnostic(text).status == "consistent"
    warning, = quality.ratio_equation_warnings("1/100000000000000000=0.000000000001%")
    assert "0.000000000000001%" in warning
    warning, = quality.ratio_equation_warnings("0.100000000001+0=0.100000000000")
    assert "约为 0.100000000001" in warning
    # Exact comparison avoids false mismatches caused by a repeating quotient.
    assert diagnostic("1/3*3-1=0").status == "consistent"
    assert diagnostic("1/3*3-0.5=1").status == "consistent"
    assert diagnostic("1/7*7-0.5=1").status == "consistent"
    assert diagnostic("1/3*3-0.500000000001=1").status == "mismatch"


def test_seeded_arithmetic_properties_against_exact_fraction_oracle():
    rng = random.Random(220061011)
    for _ in range(120):
        a, b, c = (rng.randrange(-100, 101) for _ in range(3))
        divisor = rng.choice((2, 4, 5, 10))
        expressions = [
            (f"{a}+{b}*{c}", Fraction(a) + Fraction(b) * c),
            (f"({a}-{b})/{divisor}", (Fraction(a) - b) / divisor),
            (f"{a}/{divisor}+{c}", Fraction(a, divisor) + c),
        ]
        for lhs, rational in expressions:
            exact = Decimal(rational.numerator) / Decimal(rational.denominator)
            assert diagnostic(f"{lhs}={exact:.6f}").status == "consistent"
            assert diagnostic(f"{lhs}={exact + 1:.6f}").status == "mismatch"
            # Unsupported suffixes invalidate the WHOLE candidate.
            assert diagnostic(f"{lhs}={exact + 1:.6f}+1").status == "unsupported"


def test_seeded_unit_conversion_properties():
    rng = random.Random(22)
    for _ in range(100):
        yuan, wan = rng.randrange(-100000, 100000), rng.randrange(-100, 100)
        exact = Decimal(yuan) / 10000 + wan
        lhs = f"{yuan}元+{wan}万元"
        assert diagnostic(f"{lhs}={exact:.4f}万元").status == "consistent"
        assert diagnostic(f"{lhs}={exact + 1:.4f}万元").status == "mismatch"


def test_offsets_bounded_dedup_and_unknown_do_not_swallow_independent_error():
    text = "说明：12/20=50%～70%；2亿元+3万元=5亿元。"
    unsupported, wrong = quality._arithmetic_diagnostics(text)
    assert unsupported.status == "unsupported" and wrong.status == "mismatch"
    assert text[wrong.start:wrong.end] == wrong.raw == "2亿元+3万元=5亿元"
    assert len(quality.ratio_equation_warnings(text * 10)) == 1
    assert len(quality.ratio_equation_warnings("；".join(f"{n}+1=100" for n in range(10)))) == 3


@pytest.mark.parametrize("text", ["1/0=0%", "1/-0=0%", "1/(2-2)=0", "1元/0=0元"])
def test_supported_zero_denominator_is_undefined_not_consistent(text):
    assert diagnostic(text).status == "undefined"
    assert "分母为 0" in quality.ratio_equation_warnings(text)[0]


def test_rational_resource_limit_fails_closed(monkeypatch):
    monkeypatch.setattr(quality, "_MAX_RATIONAL_BITS", 4)
    assert diagnostic("17/3=6").reason == "rational_limit"
    assert quality.ratio_equation_warnings("17/3=6") == []


def test_independent_operand_and_operation_limits(monkeypatch):
    monkeypatch.setattr(quality, "_MAX_OPERANDS", 2)
    assert diagnostic("1+1=2").reason == "operand_limit"
    monkeypatch.setattr(quality, "_MAX_OPERANDS", 16)
    monkeypatch.setattr(quality, "_MAX_OPERATIONS", 1)
    assert diagnostic("1+1+1=3").reason == "operation_limit"


def test_repeating_quotient_half_grid_both_signs():
    for text in ["1/3*3-0.5=1", "1/7*7-0.5=1", "-(1/3*3)+0.5=-1"]:
        assert diagnostic(text).status == "consistent"
    for text in ["1/3*3-0.500000000001=1", "-(1/3*3)+0.500000000001=-1"]:
        assert diagnostic(text).status == "mismatch"


def test_exact_comparison_remains_authoritative_when_decimal_display_rounds(monkeypatch):
    # A synthetic 1995-bit rational is inside the bit budget yet its difference
    # from a half-grid boundary is beyond the 512-digit display precision.
    exact = Fraction(1, 2) - Fraction(1, 10**600)
    monkeypatch.setattr(quality, "_evaluate", lambda node: quality._Quantity(Decimal("0.5"), "scalar", exact=exact))
    assert diagnostic("1+1=1").status == "mismatch"


@pytest.mark.parametrize("text,status", [
    ("19005.40元-16821.09元≈2200元", "consistent"),
    ("19005.40元-16821.09元=2200元", "mismatch"),
    ("19005.40元-16821.09元≈2300元", "mismatch"),
    ("15/60≈20%", "mismatch"),
    ("52/4≈10倍", "mismatch"),
    ("10/3≈3倍", "consistent"),
])
def test_approximate_units_and_zero_place_caps(text, status):
    assert diagnostic(text).status == status


@pytest.mark.parametrize("text", [
    "0.35*100=35%", "(12/20)*100=60%", "12/20*100.0=60%",
    "12/20*100+0=60%", "100*(12/20)=60%", "0.35*(100)=35%",
    "(12/20*100)/2=30%", "12/20*(-100)=-60%",
])
def test_unrecognized_percent_display_conventions_are_unknown(text):
    item = diagnostic(text)
    assert item.status == "unsupported" and item.reason == "ambiguous_percent_display"
    assert quality.ratio_equation_warnings(text) == []


@pytest.mark.parametrize("text,status", [
    (".35*100=35%", "unsupported"),  # Leading-dot literals are outside grammar.
    ("35%*100=35%", "mismatch"),  # Explicit percent is scaled twice.
    ("35%*100=3500%", "consistent"),
    ("0.35*100%=35%", "consistent"),
    ("0.35*100倍=35%", "mismatch"),  # Explicit multiplier is not a display cue.
    ("0.35元*100=35%", "unsupported"),  # Wrong result dimension.
    ("0.35元*100=35元", "consistent"),
    ("12/(20*100)=0.6%", "consistent"),  # Denominator scale stays literal.
    ("12/(20*100)=0.06%", "mismatch"),
    ("12/20*100=60%", "consistent"),
    ("12/20*100=-60%", "mismatch"),
])
def test_percent_display_ambiguity_does_not_change_explicit_units(text, status):
    assert diagnostic(text).status == status


@pytest.mark.parametrize("text", [
    "1'200/20=60", "1’200/20=60", "1'200/20=6000%", "1‘200/20=60",
    "6/1=3!", "3!+1+1=8", "6/1=3！", "3！+1+1=8",
    "`2`+3+4=9", "'2'+3+4=9", '"2"+3+4=9', "‘2’+3+4=9",
    "1:2+3=3.5", "1：2+3=3.5", "12:20/10=6%",
    "1?2:3+4=2", "1?2+3:9+10=5", "1?0:1/0=0",
    "1？0：1/0=0", "1，200/20=60", "1'200/0=60",
    "6/1=3!+0", "1/(3!)+1=1.166667", "1 + `2`/0=0",
    "1λ:1/0=0", "1甲：1/0=0", "甲1：1/0=0",
])
@pytest.mark.parametrize("spaced", [False, True])
def test_unsupported_punctuation_never_splits_prefix_or_tail(text, spaced):
    if spaced:
        text = text.translate(str.maketrans({char: f" \n{char}\t " for char in "'’‘`\"!！:：?？，"}))
    records = quality._arithmetic_diagnostics(text)
    assert records and all(record.status == "unsupported" for record in records)
    assert quality.ratio_equation_warnings(text) == []
    for split in range(len(text) + 1):
        original = [{"type": "delta", "text": text[:split]},
                    {"type": "delta", "text": text[split:]}, {"type": "done"}]
        assert list(quality.audit_report_stream(iter(original))) == original


@pytest.mark.parametrize("opening,closing", [("'", "'"), ('"', '"'), ("`", "`"), ("‘", "’"), ("“", "”")])
@pytest.mark.parametrize("prefix", ["", "说明：", "原文错误示例："])
def test_only_complete_standalone_quoted_equations_are_unwrapped(opening, closing, prefix):
    text = f"{prefix}{opening} 12/20=-60% {closing}，不能采用"
    item = diagnostic(text)
    assert item.status == "mismatch" and item.raw == "12/20=-60%"
    assert text[item.start:item.end] == item.raw
    assert "60%" in quality.ratio_equation_warnings(text)[0]


def test_true_sentences_prose_colons_and_unknown_spans_remain_independent():
    text = "说明：1'200/20=60；计算：12/20=-60%。另算：1+1=3"
    records = quality._arithmetic_diagnostics(text)
    assert [item.status for item in records] == ["unsupported", "mismatch", "mismatch"]
    assert len(quality.ratio_equation_warnings(text)) == 2
    for item in records:
        assert text[item.start:item.end] == item.raw
    assert quality.ratio_equation_warnings("更正后为8亿元，12/20=-60%")


@pytest.mark.parametrize("text", [
    "壹：2+3=3.5", "甲：1/0=0", "说明甲：1/0=0",
    "说明：1:2+3=3.5", "说明：1？0：1/0=0", "说明：甲：1/0=0",
    "说明：`2`+3+4=9", "说明`1`：1/0=0", "1甲：1/0=0",
    "甲" * 90 + "说明：1/0=0", '"1\'200/20=60"', "1+1='3'",
])
def test_prose_label_exception_cannot_strip_variables_numbers_or_markup(text):
    assert all(item.status == "unsupported" for item in quality._arithmetic_diagnostics(text))
    assert quality.ratio_equation_warnings(text) == []


def test_quoted_whitespace_cannot_bypass_candidate_budget():
    text = "'" + " " * 508 + "1+1=3'"
    assert diagnostic(text).reason == "candidate_limit"
    assert quality.ratio_equation_warnings(text) == []

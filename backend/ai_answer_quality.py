"""Bounded, offline checks of literal arithmetic in report-chat drafts.

This is not a semantic evidence or model-quality evaluator. It cannot validate
the choice of denominator, comparable periods/adjustments, citations, or forecasts.
It never changes a model's answer or turns a draft into an authoritative result.
"""
from __future__ import annotations

from decimal import Decimal, localcontext
import re


_MAX_ANSWER_CHARS = 120_000
_MAX_FINDINGS = 3
# Both sides use the same continuation alphabet. Unknown composed arithmetic is
# skipped rather than treating a recognized fragment as the whole equation.
_EXPRESSION_CONTINUATIONS = frozenset("+-−*/×÷=^%％(0123456789·＋－\\")
# Deliberately small grammar: literal a/b or (a-b)/c equals a percentage.
# No eval, units, variables, exponents, chained arithmetic, or financial inference.
_NUMBER = r"[+\-−]?[0-9]{1,18}(?:\.[0-9]{1,12})?"
_EQUATION = re.compile(
    rf"(?<![\w.+\-−*/×÷()%])"
    rf"(?P<numerator>{_NUMBER}|\(\s*(?P<left>{_NUMBER})\s*[-−]\s*(?P<right>{_NUMBER})\s*\))"
    rf"\s*[/÷]\s*(?P<denominator>{_NUMBER})"
    rf"(?:\s*[*×]\s*100\s*%?)?\s*=\s*(?P<claimed>{_NUMBER})\s*[%％]"
    rf"(?![\w.%％])"
)


def _decimal(text):
    return Decimal(text.replace("−", "-"))


def ratio_equation_warnings(text: str) -> list[str]:
    """Find demonstrably inconsistent literal equations, allowing normal rounding.

    Quoted equations are also checked as literal text; a finding does not assert
    that the author endorsed it. Unknown syntax and oversized drafts are skipped,
    never reported as a pass. Results are bounded and deduplicated.
    """
    if len(text) > _MAX_ANSWER_CHARS:
        return []
    warnings = []
    seen = set()
    with localcontext() as ctx:
        ctx.prec = 64
        for match in _EQUATION.finditer(text):
            # Do not misread a supported prefix/suffix of a larger expression.
            # A percentage can be only the first RHS operand: 12/20 = 20% +
            # 40% is correct, but outside this deliberately small grammar.
            previous = match.start() - 1
            while previous >= 0 and text[previous].isspace():
                previous -= 1
            if previous >= 0 and (text[previous] in _EXPRESSION_CONTINUATIONS or text[previous] in ".,"):
                continue
            # A spelled-out LaTeX operator ends in a letter, not its backslash.
            if re.search(r"\\[A-Za-z]+$", text[max(0, previous - 31):previous + 1]):
                continue
            following = match.end()
            while following < len(text) and text[following].isspace():
                following += 1
            if following < len(text) and text[following] in _EXPRESSION_CONTINUATIONS:
                continue
            denominator = _decimal(match["denominator"])
            if denominator == 0:
                message = "分母为 0，百分比未定义"
            else:
                numerator = (_decimal(match["left"]) - _decimal(match["right"])) if match["left"] is not None else _decimal(match["numerator"])
                actual = numerator / denominator * 100
                claimed = _decimal(match["claimed"])
                # Half a unit in the last displayed decimal place, in percentage
                # points. Do not reject 1/3=33.3% merely for being rounded.
                tolerance = Decimal(5).scaleb(claimed.as_tuple().exponent - 1)
                if abs(actual - claimed) <= tolerance:
                    continue
                rounded = format(actual, ".6f").rstrip("0").rstrip(".")
                message = f"按式中字面数字计算约为 {rounded}%"
            equation = match.group(0)
            if equation in seen:
                continue
            seen.add(equation)
            warnings.append(f"「{equation}」：{message}")
            if len(warnings) >= _MAX_FINDINGS:
                break
    return warnings


def audit_report_stream(events):
    """Preserve streaming; add an explicit check note before successful completion.

    Failed/incomplete turns are not annotated. No provider retry, storage, network,
    or additional model request occurs. Existing delta/done event contracts suffice.
    """
    parts = []
    chars = 0
    failed = False
    try:
        for event in events:
            if event.get("type") == "delta" and isinstance(event.get("text"), str):
                chars += len(event["text"])
                if chars <= _MAX_ANSWER_CHARS:
                    parts.append(event["text"])
                else:
                    parts.clear()
            elif event.get("type") == "error":
                failed = True
            elif event.get("type") == "done" and not failed and chars <= _MAX_ANSWER_CHARS:
                warnings = ratio_equation_warnings("".join(parts))
                if warnings:
                    yield {"type": "delta", "text": "\n\n【确定性算式复核提示】\n" + "\n".join(warnings)
                           + "\n仅复核上述字面算式（含引述），不代表核实来源、分母选择或整体结论；请核对原文，勿直接据此决策。"}
            yield event
    finally:
        close = getattr(events, "close", None)
        if close is not None:
            close()

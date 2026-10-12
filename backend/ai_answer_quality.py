"""Bounded, offline checks of literal arithmetic in report-chat drafts.

Arithmetic consistency is not evidence of source quality, correct periods,
denominators, currencies, or forecasts. Unsupported text is never a pass.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from decimal import Decimal, DecimalException, ROUND_HALF_EVEN, localcontext
import re


_MAX_ANSWER_CHARS = 120_000
_MAX_FINDINGS = 3
_MAX_CANDIDATE_CHARS = 512
_MAX_TOKENS = 64
_MAX_OPERANDS = 16  # Both sides combined.
_MAX_OPERATIONS = 14  # Binary LHS operations; unary signs also consume tokens.
_MAX_DEPTH = 4
_MAX_MAGNITUDE = 128
_MAX_RATIONAL_BITS = 4096
# Shared extraction alphabet includes UNSUPPORTED continuations intentionally.
# An unsupported whole expression must never become a supported prefix or tail.
_EXPRESSION_CONTINUATIONS = frozenset("+-−*/×÷=^%％(0123456789·＋－~～–—±至到\\")
_CANDIDATE = re.compile(
    "[" + re.escape("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_.,"
                      "万亿元股倍)%％＝≈[]{}<>≤≥√∞'’‘`\"“”!:：?！？" + "".join(sorted(_EXPRESSION_CONTINUATIONS))) + r"\s]+"
)
_DELIMITERS = frozenset(";；。，")
_QUOTE_PAIRS = {"'": "'", '"': '"', "`": "`", "‘": "’", "“": "”"}
# Exact prose labels, not an arbitrary Chinese/variable prefix grammar.
_PROSE_LABELS = frozenset(("说明", "计算", "更正", "另算", "原文错误示例"))
_NUMBER = r"[+\-−]?[0-9]{1,18}(?:\.[0-9]{1,12})?"
_LEGACY_DISPLAY = re.compile(
    rf"(?:{_NUMBER}|\(\s*{_NUMBER}\s*[-−]\s*{_NUMBER}\s*\))"
    rf"\s*[/÷]\s*{_NUMBER}\s*[*×]\s*100\s*"
)
_TOKEN = re.compile(r"[0-9]+(?:\.[0-9]+)?|万亿|[万亿元股倍%％+\-−*/×÷()=＝≈]")
_SCALE = {"万": Decimal(10000), "亿": Decimal(100000000), "万亿": Decimal(1000000000000)}
_SCALARS = frozenset(("scalar", "percent"))


class _Unsupported(ValueError):
    pass


@dataclass(frozen=True)
class _Quantity:
    value: Decimal
    kind: str
    factor: Decimal = Decimal(1)
    unit: str = ""
    displayed: str = ""
    exact: Fraction = Fraction(0)


@dataclass(frozen=True)
class _Diagnostic:
    raw: str
    start: int
    end: int
    status: str  # consistent, mismatch, undefined, unsupported; never verified.
    reason: str = ""
    recomputed: Decimal | None = None  # In the displayed RHS unit.
    tolerance: Decimal | None = None
    unit: str = ""


def _decimal(text):
    return Decimal(text.replace("−", "-"))


def _tokens(text):
    out = []
    pos = 0
    for match in _TOKEN.finditer(text):
        if text[pos:match.start()].strip():
            raise _Unsupported("unsupported_token")
        token = match.group()
        if token[0].isdigit():
            integer, _, fractional = token.partition(".")
            if len(integer) > 18 or len(fractional) > 12:
                raise _Unsupported("number_limit")
        out.append(token)
        if len(out) > _MAX_TOKENS:
            raise _Unsupported("token_limit")
        pos = match.end()
    if text[pos:].strip():
        raise _Unsupported("unsupported_token")
    return out


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self.operands = 0
        self.operations = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ""

    def pop(self):
        token = self.peek()
        if not token:
            raise _Unsupported("incomplete_expression")
        self.pos += 1
        return token

    def quantity(self, allow_sign=True):
        sign = ""
        if allow_sign and self.peek() in ("+", "-", "−"):
            sign = self.pop()
        raw = self.pop()
        if not raw[0].isdigit():
            raise _Unsupported("expected_number")
        self.operands += 1
        if self.operands > _MAX_OPERANDS:
            raise _Unsupported("operand_limit")
        factor = Decimal(1)
        scale = self.pop() if self.peek() in _SCALE else ""
        if scale:
            factor = _SCALE[scale]
        suffix = self.pop() if self.peek() in ("元", "股", "倍", "%", "％") else ""
        if scale and suffix in ("倍", "%", "％"):
            raise _Unsupported("ambiguous_unit")
        kind = suffix if suffix in ("元", "股") else "scaled" if scale else "scalar"
        if suffix in ("%", "％"):
            kind, factor = "percent", Decimal("0.01")
        displayed = sign + raw
        return _Quantity(_decimal(displayed) * factor, kind, factor, scale + ("%" if suffix == "％" else suffix), displayed,
                         Fraction(_decimal(displayed)) * Fraction(factor))

    def atom(self, depth):
        sign = None
        if self.peek() in ("+", "-", "−"):
            sign = self.pop()
        if self.peek() == "(":
            if depth >= _MAX_DEPTH:
                raise _Unsupported("depth_limit")
            self.pop()
            node = self.expression(depth + 1)
            if self.pop() != ")":
                raise _Unsupported("unclosed_parenthesis")
        else:
            node = ("quantity", self.quantity(allow_sign=False))
        return ("negative", node) if sign in ("-", "−") else node

    def operation(self):
        self.operations += 1
        if self.operations > _MAX_OPERATIONS:
            raise _Unsupported("operation_limit")

    def product(self, depth):
        node = self.atom(depth)
        while self.peek() in ("*", "×", "/", "÷"):
            op = self.pop()
            self.operation()
            node = (op, node, self.atom(depth))
        return node

    def expression(self, depth=0):
        node = self.product(depth)
        while self.peek() in ("+", "-", "−"):
            op = self.pop()
            self.operation()
            node = (op, node, self.product(depth))
        return node


def _bounded_exact(exact):
    if max(exact.numerator.bit_length(), exact.denominator.bit_length()) > _MAX_RATIONAL_BITS:
        raise _Unsupported("rational_limit")
    return exact


def _bounded(value):
    if not value.is_finite() or (value and abs(value.adjusted()) > _MAX_MAGNITUDE):
        raise _Unsupported("magnitude_limit")
    return value


def _result_kind(op, left, right):
    if op in ("+", "-", "−"):
        if left != right:
            raise _Unsupported("incompatible_units")
        return left
    if op in ("*", "×"):
        if left not in _SCALARS and right not in _SCALARS:
            raise _Unsupported("unsupported_dimensions")
        return right if left == "scalar" else left if right in _SCALARS else right
    if right not in _SCALARS:
        if left != right:
            raise _Unsupported("unsupported_dimensions")
        return "scalar"
    return "scalar" if left == right else left


def _infer_kind(node):
    if node[0] == "quantity":
        return node[1].kind
    if node[0] == "negative":
        return _infer_kind(node[1])
    return _result_kind(node[0], _infer_kind(node[1]), _infer_kind(node[2]))


def _evaluate(node):
    op = node[0]
    if op == "quantity":
        return node[1]
    if op == "negative":
        value = _evaluate(node[1])
        return _Quantity(-value.value, value.kind, exact=-value.exact)
    left, right = _evaluate(node[1]), _evaluate(node[2])
    kind = _result_kind(op, left.kind, right.kind)
    if op in ("+", "-", "−"):
        exact = left.exact + right.exact if op == "+" else left.exact - right.exact
    elif op in ("*", "×"):
        exact = left.exact * right.exact
    else:
        if right.exact == 0:
            raise ZeroDivisionError
        exact = left.exact / right.exact
    # Decimal alone can move a repeating quotient across an inclusive rounding
    # boundary (1/3*3-0.5=1). Keep a bounded exact companion for comparisons.
    _bounded_exact(exact)
    value = Decimal(exact.numerator) / Decimal(exact.denominator)
    return _Quantity(_bounded(value), kind, exact=exact)


def _has_percent_literal(node):
    if node[0] == "quantity":
        return node[1].kind == "percent"
    return any(_has_percent_literal(child) for child in node[1:])


def _has_display_hundred(node):
    def bare_hundred(child):
        if child[0] == "negative":
            child = child[1]
        return (child[0] == "quantity" and child[1].kind == "scalar"
                and not child[1].unit and child[1].exact == 100)
    if node[0] == "quantity":
        return False
    if node[0] in ("*", "×") and (bare_hundred(node[1]) or bare_hundred(node[2])):
        return True
    # A factor in a denominator is not a percentage-display conversion.
    children = node[1:2] if node[0] in ("/", "÷") else node[1:]
    return any(_has_display_hundred(child) for child in children)


def _tolerance(displayed, approximate):
    """RHS units: half displayed decimal grid; ≈ integers may round zeroes.

    Integer ≈ tolerance = min(half trailing-zero grid,
    max(5% * abs(stated), 0.5)). '=' never gets relative/absolute floors.
    Decimal ≈ values get ONLY half their last displayed decimal place.
    """
    value = _decimal(displayed)
    half = Decimal(5).scaleb(value.as_tuple().exponent - 1)
    if not approximate or "." in displayed:
        return half
    digits = displayed.lstrip("+-−")
    zeroes = len(digits) - len(digits.rstrip("0")) if value else 0
    coarse = Decimal("0.5") * (Decimal(10) ** zeroes)
    return min(coarse, max(abs(value) * Decimal("0.05"), Decimal("0.5")))


def _check_candidate_inner(raw, start, end):
    def unsupported(reason):
        return _Diagnostic(raw, start, end, "unsupported", reason)
    if len(raw) > _MAX_CANDIDATE_CHARS:
        return unsupported("candidate_limit")
    try:
        tokens = _tokens(raw)
        if sum(t in ("=", "＝", "≈") for t in tokens) != 1:
            return unsupported("relation_count")
        parser = _Parser(tokens)
        node = parser.expression()
        relation = parser.pop()
        if relation not in ("=", "＝", "≈") or not parser.operations:
            return unsupported("expected_equation")
        rhs = parser.quantity()
        if parser.peek():
            return unsupported("compound_rhs")
        # Only after full parsing can a calculation become an error diagnostic.
        with localcontext() as ctx:
            ctx.prec = 512
            kind = _infer_kind(node)
            if kind != rhs.kind and not (kind in _SCALARS and rhs.kind in _SCALARS):
                return unsupported("ambiguous_result_unit")
            lhs = re.split("[=＝≈]", raw, maxsplit=1)[0].strip()
            legacy_display = rhs.kind == "percent" and _LEGACY_DISPLAY.fullmatch(lhs)
            # Bare ×100 is also a common display convention beyond the narrow
            # legacy shape. Do not call those ambiguous forms either right or
            # wrong. Explicit percent operands retain literal scaling semantics.
            if (rhs.kind == "percent" and not legacy_display
                    and _has_display_hundred(node) and not _has_percent_literal(node)):
                return unsupported("ambiguous_percent_display")
            result = _evaluate(node)
            exact = result.exact
            if legacy_display:
                exact /= 100  # Existing ratio ×100 = displayed-percent notation.
            exact = _bounded_exact(exact / Fraction(rhs.factor))
            actual = _bounded(Decimal(exact.numerator) / Decimal(exact.denominator))
            stated = _decimal(rhs.displayed)
            tolerance = _tolerance(rhs.displayed, relation == "≈")
            difference = _bounded_exact(exact - Fraction(stated))
            status = "consistent" if abs(difference) <= Fraction(tolerance) else "mismatch"
            return _Diagnostic(raw, start, end, status, recomputed=actual, tolerance=tolerance, unit=rhs.unit)
    except _Unsupported as exc:
        return unsupported(str(exc))
    except ZeroDivisionError:
        return _Diagnostic(raw, start, end, "undefined", "zero_denominator")
    except (DecimalException, OverflowError):
        return unsupported("numeric_limit")


def _check_candidate(raw, start, end):
    with localcontext() as ctx:
        ctx.prec = 512
        ctx.rounding = ROUND_HALF_EVEN
        return _check_candidate_inner(raw, start, end)


def _safe_boundary(text, index):
    if index < 0 or index >= len(text):
        return True
    if text[index] not in _DELIMITERS:
        return False
    if text[index] == "，":
        left, right = index - 1, index + 1
        while left >= 0 and text[left].isspace():
            left -= 1
        while right < len(text) and text[right].isspace():
            right += 1
        # A numeric grouping comma is not an independent sentence boundary.
        if left >= 0 and right < len(text) and text[left].isdigit() and text[right].isdigit():
            return False
    return True


def _standalone_prose_label(text, end):
    # Inspect a bounded complete label only; never salvage a suffix of a longer
    # label, numeric expression, variable name, ternary or inline annotation.
    start = max(0, end - 81)
    prefix = text[start:end]
    boundary = max((prefix.rfind(char) for char in _DELIMITERS), default=-1)
    if boundary >= 0:
        if not _safe_boundary(text, start + boundary):
            return False
        prefix = prefix[boundary + 1:]
    elif start:
        return False
    return prefix.strip() in _PROSE_LABELS


def _arithmetic_diagnostics(text):
    """Whole maximal candidates only: never retry a substring after rejection."""
    if len(text) > _MAX_ANSWER_CHARS:
        return []
    out = []
    for match in _CANDIDATE.finditer(text):
        raw = match.group().strip()
        if not any(char in raw for char in "=＝≈"):
            continue
        start = match.start() + len(match.group()) - len(match.group().lstrip())
        end = match.end() - len(match.group()) + len(match.group().rstrip())
        if len(raw) > _MAX_CANDIDATE_CHARS:
            out.append(_Diagnostic(raw, start, end, "unsupported", "candidate_limit"))
            continue
        before_ok = _safe_boundary(text, match.start() - 1)
        if raw.startswith((":", "：")) and _standalone_prose_label(text, match.start()):
            raw = raw[1:]
            start += 1 + len(raw) - len(raw.lstrip())
            raw = raw.lstrip()
            before_ok = True
        # Apostrophes, backticks and punctuation stay inside the candidate.
        # Only one complete, standalone quote pair may surround the equation;
        # inline markup, grouped digits and trailing factorials are not stripped.
        if raw and raw[0] in _QUOTE_PAIRS and len(raw) > 1 and raw[-1] == _QUOTE_PAIRS[raw[0]]:
            inner = raw[1:-1]
            start += 1 + len(inner) - len(inner.lstrip())
            end -= 1 + len(inner) - len(inner.rstrip())
            raw = inner.strip()
        if not before_ok or not _safe_boundary(text, match.end()):
            out.append(_Diagnostic(raw, start, end, "unsupported", "unsafe_boundary"))
        else:
            out.append(_check_candidate(raw, start, end))
    return out


def _display_value(value, tolerance):
    # Preserve six-place legacy output, but do not round a tiny nonzero result
    # to zero or erase a mismatch visible at the RHS's finer precision.
    places = max(6, -tolerance.adjusted() + 2, -value.adjusted() + 6 if value else 0)
    return format(value, f".{min(140, places)}f").rstrip("0").rstrip(".") or "0"


def ratio_equation_warnings(text: str) -> list[str]:
    """Compatibility wrapper: diagnostics only, no rewriting or pass label."""
    warnings, seen = [], set()
    for item in _arithmetic_diagnostics(text):
        if item.status not in ("mismatch", "undefined") or item.raw in seen:
            continue
        seen.add(item.raw)
        if item.status == "undefined":
            message = "分母为 0，算式未定义"
        else:
            number = _display_value(item.recomputed, item.tolerance)
            message = f"按式中字面数字计算约为 {number}{item.unit}"
        warnings.append(f"「{item.raw}」：{message}")
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

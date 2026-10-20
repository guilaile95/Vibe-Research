#!/usr/bin/env python3
"""Read saved local JSON exports only; print diagnostics without mutating them."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from research_quality_diagnostics import MAX_BYTES, compare_noise, evaluate


def _invalid_constant(value):
    raise ValueError('NONFINITE_JSON')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def read(path, raw=False):
    if path is None:
        return None
    with Path(path).open('rb') as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('INPUT_TOO_LARGE')
    text = data.decode('utf-8')
    return text if raw else json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    report = commands.add_parser('report')
    report.add_argument('--kind', choices=['company', 'comparison', 'daily'], required=True)
    report.add_argument('--report', required=True)
    report.add_argument('--evidence', help='Company frozen bundle or comparison frozen pair JSON')
    report.add_argument('--context', help='Daily exact original context bytes, never a reconstructed current context')
    report.add_argument('--labels', help='Optional hash-bound human labels JSON')
    noise = commands.add_parser('noise')
    noise.add_argument('--case', required=True)
    noise.add_argument('--baseline')
    noise.add_argument('--perturbed')
    args = parser.parse_args()
    try:
        if args.command == 'report':
            result = evaluate(args.kind, read(args.report), read(args.evidence),
                              context_text=read(args.context, raw=True), labels=read(args.labels))
        else:
            result = compare_noise(read(args.case), read(args.baseline), read(args.perturbed))
    except (OSError, ValueError, UnicodeError, RecursionError):
        print(json.dumps({'status': 'FAIL', 'reason': 'LOCAL_INPUT_UNREADABLE_OR_INVALID'}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Incomplete evaluation is visibly distinct from a passing gate.
    status = result.get('overall', result.get('status'))
    return 1 if status == 'FAIL' else 3 if status == 'NOT_EVALUATED' else 0


if __name__ == '__main__':
    raise SystemExit(main())

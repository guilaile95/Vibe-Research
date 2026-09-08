"""Compatibility CLI for the former signal-effect-study prototype.

The calculation now lives in :mod:`historical_signal_validation` so the API
and the original prototype share exactly one research protocol.
"""
from __future__ import annotations

import argparse
import json

from historical_signal_validation import (
    HISTORICAL_VALIDITY,
    LIMITATIONS,
    SIGNAL_ID,
    SIGNAL_VERSION,
    SCHEMA_VERSION,
    SMA_FAST,
    SMA_SLOW,
    VALIDITY_REASONS,
    WINDOWS,
    _load_series_from_rdp,
    _sma,
    _stats,
    build_report,
    run_study,
    study_series,
    write_outputs,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="sma20_gt_sma60 signal validation (RESEARCH ONLY)")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--codes", required=True, help="comma separated 6-digit codes")
    parser.add_argument("--benchmark-code", default=None)
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--out-prefix", required=True)
    args = parser.parse_args(argv)
    codes = [code.strip() for code in args.codes.split(",") if code.strip()]
    benchmark = (
        _load_series_from_rdp(args.data_root, [args.benchmark_code], args.date_from, args.date_to).get(args.benchmark_code)
        if args.benchmark_code
        else None
    )
    series = _load_series_from_rdp(args.data_root, codes, args.date_from, args.date_to)
    import research_data_plane as rdp

    manifest = rdp.read_manifest(args.data_root)
    provenance = {
        "root": str(args.data_root),
        "dataset_id": manifest.get("dataset_id"),
        "adjustment": manifest.get("adjustment"),
        "license_status": manifest.get("license_status"),
        "coverage_start": manifest.get("coverage_start"),
        "coverage_end": manifest.get("coverage_end"),
        "artifact_sha256": manifest.get("artifact_sha256"),
        "requested_date_from": args.date_from,
        "requested_date_to": args.date_to,
        "requested_sample_codes": codes,
        "sample_codes_with_data": sorted(series),
        "sample_codes_missing_data": [code for code in codes if code not in series],
        "requested_benchmark_code": args.benchmark_code,
        "benchmark_available": benchmark is not None,
        "benchmark_in_sample_list": args.benchmark_code in codes if args.benchmark_code else False,
    }
    report = build_report(series, benchmark, provenance)
    outputs = write_outputs(report, args.out_prefix)
    print(json.dumps({"outputs": outputs, "historical_validity": HISTORICAL_VALIDITY}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

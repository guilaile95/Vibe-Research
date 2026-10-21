"""Bounded, predeclared SMA sensitivity study. No optimizer or trading engine."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import historical_signal_validation as hsv
import research_data_plane as rdp

VERSION = 'rolling-signal-validation.v1'
PRESET = ((15, 60), (20, 60), (25, 60))
MAX_OBSERVATIONS = 5000
MAX_WORK = 300000


class RollingSignalValidationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    signal_id: Literal['sma20_gt_sma60'] = 'sma20_gt_sma60'
    codes: list[str] = Field(min_length=1, max_length=20)
    benchmark_code: str | None = None
    selection_from: str
    selection_to: str
    holdout_from: str
    holdout_to: str
    rolling_calendar_days: int = Field(default=90, ge=30, le=366, strict=True)
    parameter_preset: Literal['sma-fast-neighbors-v1'] = 'sma-fast-neighbors-v1'
    frozen_parameter: Literal['15/60', '20/60', '25/60'] = '20/60'

    @field_validator('codes')
    @classmethod
    def codes_valid(cls, value):
        if any(len(c) != 6 or not c.isascii() or not c.isdigit() for c in value):
            raise ValueError('six-digit sample codes required')
        return sorted(set(value))

    @field_validator('benchmark_code')
    @classmethod
    def benchmark_valid(cls, value):
        if value is not None and (len(value) != 6 or not value.isascii() or not value.isdigit()):
            raise ValueError('six-digit benchmark required')
        return value

    @model_validator(mode='after')
    def dates_valid(self):
        for key in ('selection_from', 'selection_to', 'holdout_from', 'holdout_to'):
            raw = getattr(self, key)
            if date.fromisoformat(raw).isoformat() != raw:
                raise ValueError('canonical YYYY-MM-DD required')
        if not self.selection_from <= self.selection_to < self.holdout_from <= self.holdout_to:
            raise ValueError('selection and frozen holdout must be ordered and disjoint')
        if (date.fromisoformat(self.holdout_to) - date.fromisoformat(self.selection_from)).days > 3660:
            raise ValueError('study range exceeds ten-year work cap')
        if self.benchmark_code in self.codes:
            raise ValueError('benchmark must be independent of sample codes')
        if len(segments(self)) > 48:
            raise ValueError('rolling segment work cap exceeded (48)')
        return self


def segments(body):
    out = []
    for role in ('selection', 'holdout'):
        start = date.fromisoformat(getattr(body, role + '_from'))
        stop = date.fromisoformat(getattr(body, role + '_to'))
        out.append({'id': role, 'role': role, 'from': start.isoformat(), 'to': stop.isoformat(), 'aggregate': True})
        while start <= stop:
            end = min(stop, start + timedelta(days=body.rolling_calendar_days - 1))
            out.append({'id': f'{role}:{start}', 'role': role, 'from': start.isoformat(), 'to': end.isoformat(), 'aggregate': False})
            start = end + timedelta(days=1)
    return out


def identity(body, snapshot):
    # Declaration is sealed before reading prices; all tries remain visible.
    value = {'version': VERSION, 'request': body.model_dump(), 'snapshot': snapshot, 'grid': PRESET, 'windows': hsv.WINDOWS}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _load(codes, snapshot, end, cancelled):
    series = {}
    for code in codes:
        dates, closes = [], []
        offset = 0
        while True:
            if cancelled():
                return None
            page = rdp.query_daily_bars(snapshot_id=snapshot, code=code, date_to=end, limit=rdp._MAX_LIMIT, offset=offset)
            if page.get('snapshot_id') != snapshot:
                raise rdp.ResearchDataPlaneValidationError('rolling snapshot receipt mismatch')
            rows = page.get('rows') or []
            if len(dates) + len(rows) > MAX_OBSERVATIONS:
                raise ValueError('stored-observation work cap exceeded')
            for row in rows:
                dates.append(row['trade_date'])
                closes.append(None if row.get('close') is None else float(row['close']))
            if not rows or page.get('next_offset') is None:
                break
            offset += len(rows)
        if dates:
            series[code] = (dates, closes)
    return series


def _coverage(series, start, end, fast, slow):
    out = {}
    for code, (dates, closes) in series.items():
        indexes = [i for i, day in enumerate(dates) if start <= day <= end]
        selected = [dates[i] for i in indexes]
        gaps = [{'from': a, 'to': b, 'calendar_days': (date.fromisoformat(b) - date.fromisoformat(a)).days}
                for a, b in zip(selected, selected[1:]) if (date.fromisoformat(b) - date.fromisoformat(a)).days > 1]
        # Gaps are calendar spacing, not inferred missing trading sessions.
        fast_values, slow_values = hsv._sma(closes, fast), hsv._sma(closes, slow)
        out[code] = {'stored_observations': len(indexes), 'evaluable_observations': sum(fast_values[i] is not None and slow_values[i] is not None for i in indexes),
                     'warmup_observations_before_segment': sum(d < start for d in dates),
                     'first_date': selected[0] if selected else None, 'last_date': selected[-1] if selected else None,
                     'calendar_gap_count': len(gaps), 'calendar_gaps': gaps[:20], 'calendar_gaps_omitted': max(0, len(gaps) - 20)}
    return out


def _bucket(rows, series, start, end, horizon, unknown_dates):
    selected = []
    for original in rows:
        if not original['signal_date'] or not start <= original['signal_date'] <= end:
            continue
        row = dict(original)
        dates = series[row['code']][0]
        index = dates.index(row['signal_date']) + horizon
        label_end = dates[index] if index < len(dates) else None
        row['label_end_date'] = label_end
        if label_end is not None and label_end > end:
            row.update(status='PURGED_LABEL_END', exit_date=label_end, exit_close=None, return_pct=None,
                       benchmark_return_pct=None, excess_return_pct=None, benchmark_missing_reason=None, is_failure=False, is_worst=False)
        selected.append(row)
    scored = [r for r in selected if r['status'] == 'EVALUATED']
    worst = min(scored, key=lambda row: row['return_pct']) if scored else None
    for row in selected:
        row['is_worst'] = row is worst
    return {'events_total': len(selected), 'events_evaluated': len(scored),
            'events_immature': sum(r['status'] == 'IMMATURE' for r in selected),
            'events_missing_exit': sum(r['status'] == 'MISSING_EXIT' for r in selected),
            'events_purged_label_end': sum(r['status'] == 'PURGED_LABEL_END' for r in selected),
            'events_excluded_unknown_prior': sum(start <= d <= end for d in unknown_dates),
            'benchmark_events_missing': sum(r['excess_return_pct'] is None for r in scored),
            'signal_return': hsv._stats([r['return_pct'] for r in scored]),
            'excess_return': hsv._stats([r['excess_return_pct'] for r in scored if r['excess_return_pct'] is not None]),
            'rows': selected}


def evaluate_series(body, series, benchmark, snapshot, cancelled=lambda: False):
    """Pure bounded evaluation; selection never uses labels from holdout."""
    if sum(len(v[0]) for v in series.values()) * len(PRESET) * len(segments(body)) > MAX_WORK:
        raise ValueError('parameter study work cap exceeded')
    for dates, closes in [*series.values(), *([benchmark] if benchmark else [])]:
        if len(dates) != len(closes) or len(dates) > MAX_OBSERVATIONS or dates != sorted(set(dates)):
            raise ValueError('invalid observation sequence or work cap')
        if any(d > body.holdout_to for d in dates):
            raise ValueError('observations beyond frozen holdout')
        if any(c is not None and (not math.isfinite(c) or c <= 0) for c in closes):
            raise ValueError('invalid close')
    report = {'schema_version': VERSION, 'status': 'normal' if series else 'unavailable', 'research_only': True,
              'request': body.model_dump(), 'input_fingerprint': identity(body, snapshot),
              'data': {'snapshot_id': snapshot, 'missing_codes': [c for c in body.codes if c not in series],
                       'benchmark_available': benchmark is not None, 'benchmark_code': body.benchmark_code},
              'declaration': {'parameter_preset': body.parameter_preset, 'all_parameters': [f'{f}/{s}' for f,s in PRESET],
                              'frozen_parameter': body.frozen_parameter, 'selection_policy': 'USER_PREDECLARED_NO_OPTIMIZATION',
                              'holdout_policy': 'frozen request and snapshot; any changed declaration is a new study; viewing neighbors consumes this holdout for future selection'},
              'protocol': {'horizons_stored_observations': list(hsv.WINDOWS), 'rolling_window_unit': 'calendar_days',
                           'warmup': 'all stored history through T; same history for every segment and parameter',
                           'work_cap': {'observation_parameter_segment_units': MAX_WORK, 'observations_per_code': MAX_OBSERVATIONS, 'segments': 48},
                           'purge': 'label end must be within each segment; no cross-boundary labels scored',
                           'gaps': 'calendar spacing only; trading calendar NOT_EVALUATED',
                           'benchmark': 'independent series, exact signal and label-end date joins; no fill'},
              'historical_validity': {'status': 'NOT_PROVEN', 'historical_universe': 'NOT_EVALUATED', 'corporate_actions': 'NOT_EVALUATED', 'investable_backtest': 'NOT_EVALUATED'},
              'limitations': list(hsv.LIMITATIONS), 'trials': [], 'formal_state_write': {'performed': False}}
    for fast, slow in PRESET:
        if cancelled():
            report['status'] = 'cancelled'
            break
        study = hsv.run_study(series, benchmark, sma_fast=fast, sma_slow=slow)
        unknown_dates = [day for item in study['studies_by_code'].values() for day in item['excluded_unknown_prior_dates']]
        trial = {'parameter': f'{fast}/{slow}', 'frozen_primary': f'{fast}/{slow}' == body.frozen_parameter, 'segments': []}
        for segment in segments(body):
            if cancelled():
                report['status'] = 'cancelled'
                break
            trial['segments'].append({**segment, 'coverage': _coverage({c: series.get(c, ([], [])) for c in body.codes}, segment['from'], segment['to'], fast, slow),
                                      'results': {str(w): _bucket(study['windows'][str(w)]['rows'], series, segment['from'], segment['to'], w, unknown_dates) for w in hsv.WINDOWS}})
        report['trials'].append(trial)
        if report['status'] == 'cancelled':
            break
    report['metrics'] = {k: {'status': 'SUPPORTED', 'value': v} for k, v in {'trial_count': len(report['trials']), 'segment_count': sum(len(t['segments']) for t in report['trials']),
        'evaluated_count': sum(b['events_evaluated'] for t in report['trials'] for s in t['segments'] if s['aggregate'] for b in s['results'].values()),
        'purged_count': sum(b['events_purged_label_end'] for t in report['trials'] for s in t['segments'] if s['aggregate'] for b in s['results'].values())}.items()}
    return report


def evaluate_rdp(body: RollingSignalValidationRequest, cancelled: Callable[[], bool] | None = None):
    cancelled = cancelled or (lambda: False)
    manifest = rdp.read_manifest()
    snapshot = manifest['snapshot_id']
    # Freeze request/snapshot before the first price read; never re-read latest pointer.
    seed = identity(body, snapshot)
    series = _load(body.codes, snapshot, body.holdout_to, cancelled)
    bench = _load([body.benchmark_code], snapshot, body.holdout_to, cancelled) if body.benchmark_code and series is not None else {}
    report = evaluate_series(body, series or {}, (bench or {}).get(body.benchmark_code), snapshot, cancelled)
    report['input_fingerprint'] = seed
    report['data'].update({key: manifest.get(key) for key in ('adjustment', 'source_kind', 'artifact_sha256', 'coverage_start', 'coverage_end')})
    return report

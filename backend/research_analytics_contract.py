"""Bounded, declarative, research-only calculation inputs. Never executable code."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

Number = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=-1e12, le=1e12)]
Positive = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=1e-6, le=1e12)]
Nonnegative = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0, le=1e12)]
Code = Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{1,32}$")]
Day = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
Currency = Literal['CNY', 'HKD', 'USD']


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_assignment=True)

    @field_validator('*', mode='after')
    @classmethod
    def calendar_day(cls, value, info):
        if info.field_name in {'date', 'ex_date', 'pay_date', 'date_from', 'date_to'} and value is not None:
            date.fromisoformat(value)
        return value


class Bar(Contract):
    date: Day
    open: Positive | None = None
    close: Positive | None = None
    suspended: StrictBool | None = None
    limit_up: StrictBool | None = None
    limit_down: StrictBool | None = None
    price_limit_rule: Literal['BOUNDED', 'NO_DAILY_LIMIT'] | None = None
    upper_price_limit: Positive | None = None
    lower_price_limit: Positive | None = None

    @model_validator(mode='after')
    def price_limits(self):
        if self.price_limit_rule == 'BOUNDED' and self.upper_price_limit is not None and self.lower_price_limit is not None:
            if self.lower_price_limit > self.upper_price_limit:
                raise ValueError('lower price limit exceeds upper')
        if self.price_limit_rule == 'NO_DAILY_LIMIT' and (self.upper_price_limit is not None or self.lower_price_limit is not None):
            raise ValueError('no-limit declaration conflicts with bounds')
        return self


class Action(Contract):
    ex_date: Day
    pay_date: Day
    split_ratio: Positive = 1.0
    # Declared per pre-action share; payable may remain a receivable at window end.
    dividend_per_old_share: Nonnegative = 0.0

    @model_validator(mode='after')
    def order(self):
        if self.pay_date < self.ex_date:
            raise ValueError('action payment precedes ex date')
        return self


class Instrument(Contract):
    code: Code
    currency: Currency
    market: Literal['CN', 'HK', 'US']
    weight: Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
    lot_size: Annotated[int, Field(strict=True, ge=1, le=100000)] | None = None
    settlement_sessions: Annotated[int, Field(strict=True, ge=0, le=10)] | None = None
    fee_bps: Annotated[float, Field(strict=True, ge=0, le=1000, allow_inf_nan=False)] | None = None
    min_fee: Nonnegative | None = None
    slippage_bps: Annotated[float, Field(strict=True, ge=0, le=1000, allow_inf_nan=False)] | None = None
    corporate_actions_complete: StrictBool = False
    actions: list[Action] = Field(default_factory=list, max_length=200)
    bars: list[Bar] = Field(default_factory=list, max_length=2000)

    @model_validator(mode='after')
    def unique(self):
        dates = [b.date for b in self.bars]
        if dates != sorted(set(dates)):
            raise ValueError('bar dates must be unique and ascending')
        actions = [a.ex_date for a in self.actions]
        if actions != sorted(set(actions)):
            raise ValueError('action ex dates must be unique and ascending')
        if self.market == 'CN' and self.settlement_sessions is not None and self.settlement_sessions < 1:
            raise ValueError('CN equities require at least T+1 settlement')
        return self


class Panel(Contract):
    sessions: list[Day] = Field(min_length=2, max_length=2000)
    # Session calendar is an explicit supplied contract, never inferred from weekdays.
    calendar_source: Annotated[str, Field(min_length=1, max_length=120)]
    source_label: Annotated[str, Field(min_length=1, max_length=120)]
    price_basis: Literal['RAW_WITH_EXPLICIT_ACTIONS']
    instruments: list[Instrument] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def aligned(self):
        if self.sessions != sorted(set(self.sessions)):
            raise ValueError('sessions must be unique and ascending')
        for day in self.sessions:
            date.fromisoformat(day)
        codes = [i.code for i in self.instruments]
        if len(set(codes)) != len(codes):
            raise ValueError('duplicate instrument identity')
        if len({i.currency for i in self.instruments}) != 1:
            raise ValueError('currencies must be calculated separately; no implicit FX')
        if len({i.market for i in self.instruments}) != 1:
            raise ValueError('one market calendar per panel')
        if sum(i.weight for i in self.instruments) > 1 + 1e-12:
            raise ValueError('long-only gross exposure cannot exceed one')
        for instrument in self.instruments:
            if any(b.date not in self.sessions for b in instrument.bars):
                raise ValueError('bar outside declared session calendar')
            if any(a.ex_date not in self.sessions for a in instrument.actions):
                raise ValueError('corporate action outside declared session calendar')
        return self


class Strategy(Contract):
    name: Literal['BUY_AND_HOLD', 'SMA_CROSS']
    fast: Annotated[int, Field(strict=True, ge=1, le=100)] = 5
    slow: Annotated[int, Field(strict=True, ge=2, le=250)] = 20

    @model_validator(mode='after')
    def windows(self):
        if self.fast >= self.slow:
            raise ValueError('fast must be less than slow')
        return self


class SimulationRequest(Panel):
    initial_cash: Positive
    strategy: Strategy
    terminal_liquidation: StrictBool = False
    benchmark: Instrument | None = None
    robustness: StrictBool = True


class ScenarioRequest(Panel):
    benchmark: Instrument | None = None
    event_dates: list[Day] = Field(default_factory=list, max_length=50)
    event_horizon: Annotated[int, Field(strict=True, ge=1, le=60)] = 5
    pre_event_horizon: Annotated[int, Field(strict=True, ge=0, le=20)] = 5
    event_alignment: Literal["EXACT_SESSION", "NEXT_SESSION"] = "EXACT_SESSION"


class Valuation(Contract):
    date: Day
    value: Nonnegative
    flow_begin: Number = 0.0
    flow_end: Number = 0.0


class PerformanceRequest(Contract):
    currency: Currency
    scope: Literal['WHOLE_ACCOUNT', 'STOCK_BASKET']
    source_label: Annotated[str, Field(min_length=1, max_length=120)]
    valuations: list[Valuation] = Field(min_length=2, max_length=2000)
    fees_complete: StrictBool
    corporate_actions_complete: StrictBool
    coverage_complete: StrictBool

    @model_validator(mode='after')
    def dates(self):
        dates = [v.date for v in self.valuations]
        if dates != sorted(set(dates)):
            raise ValueError('valuation dates must be unique and ascending')
        if self.valuations[0].flow_begin or self.valuations[0].flow_end:
            raise ValueError('opening valuation already includes opening capital; first flows must be zero')
        return self


class Opening(Contract):
    code: Code
    quantity: Nonnegative


class LedgerPerformanceRequest(Panel):
    opening: list[Opening] = Field(default_factory=list, max_length=20)
    # Explicit attestation is required because legacy ledger rows used default zero fees.
    ledger_fees_confirmed: StrictBool = False
    opening_positions_complete: StrictBool = False


class RdpRequest(Contract):
    codes: list[Annotated[str, Field(pattern=r'^\d{6}$')]] = Field(min_length=1, max_length=20)
    date_from: Day
    date_to: Day

    @model_validator(mode='after')
    def bounds(self):
        if self.date_to < self.date_from or len(set(self.codes)) != len(self.codes):
            raise ValueError('invalid date bounds or duplicate code')
        return self

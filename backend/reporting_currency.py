"""Reporting currency normalization, independent of listing/quote currency."""
_CURRENCIES = {"美元": "USD", "港元": "HKD", "人民币": "CNY", "USD": "USD", "HKD": "HKD", "CNY": "CNY"}


def reporting_currency(value: object) -> str | None:
    return _CURRENCIES.get(value.strip()) if isinstance(value, str) else None

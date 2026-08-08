"""Platform-aware test collection rules for backend contracts."""
from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items) -> None:  # noqa: ARG001
    """Keep Windows filename semantics on Windows instead of inventing them on POSIX."""
    if os.name == "nt":
        return

    target = "test_alert_rule_store.py::test_uri_windows_question_mark_safe_failure"
    for item in items:
        if item.nodeid.endswith(target):
            item.add_marker(
                pytest.mark.skip(
                    reason="Windows-only filename contract: '?' is valid on POSIX filesystems"
                )
            )

"""pytest 配置：把 backend 目录加进 sys.path，注册 live 标记，隔离用户数据目录。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

# Configure before any application/store import. Inherited per-store overrides
# outrank VR_DATA_DIR; resetting three directories alone is not isolation.
from pathlib import Path

_REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPOSITORY / "tools"))
from validation_environment import configure_pytest_environment, legacy_private_inputs_present

if legacy_private_inputs_present(_REPOSITORY):
    raise RuntimeError("Test isolation blocked: legacy private inputs exist in checkout")
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="vr-test-data-")
configure_pytest_environment(Path(_TEST_DATA_DIR), os.environ)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: 打真实数据源的网络冒烟测（会联网、可能受上游/限流影响；默认可 -m 'not live' 跳过）",
    )

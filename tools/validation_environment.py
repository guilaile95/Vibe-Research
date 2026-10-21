"""Side-effect-free policy for test storage isolation (no application imports).

This is not a network/filesystem sandbox and cannot undo third-party plugins
loaded before conftest. Tests can explicitly replace these defaults with owned
synthetic fixtures after collection starts.
"""
from __future__ import annotations

from pathlib import Path
import stat
from typing import MutableMapping

DIRECTORIES = {
    "HOME": "home", "TMPDIR": "tmp", "XDG_CONFIG_HOME": "config",
    "XDG_CACHE_HOME": "cache", "XDG_DATA_HOME": "xdg-data",
    "XDG_STATE_HOME": "state", "USERPROFILE": "home",
    "APPDATA": "appdata", "LOCALAPPDATA": "localappdata",
    "TEMP": "tmp", "TMP": "tmp", "VR_DATA_DIR": "data",
    "VR_REPORTS_DIR": "reports", "VR_FACT_LAKE_ROOT": "fact-lake",
    "VIBE_RESEARCH_RESEARCH_DATA_DIR": "research-data",
}
AUTOMATIC_TASK_FLAGS = (
    "VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH", "VIBE_NATIVE_INTEL_DISABLE_SCHEDULER",
)
PATH_NAMES = (*DIRECTORIES, "VIBE_RESEARCH_REVIEW_DB")


def storage_environment(root: Path) -> dict[str, str]:
    """Create only owned directories; all application defaults resolve here."""
    root = root.resolve()
    result = {}
    for name, directory in DIRECTORIES.items():
        path = root / directory
        if path.resolve() != path:
            raise ValueError("isolation directory must not be a symlink")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        result[name] = str(path)
    result["VIBE_RESEARCH_REVIEW_DB"] = str(root / "data" / "daily_reviews.sqlite3")
    result.update({flag: "1" for flag in AUTOMATIC_TASK_FLAGS})
    return result


def unsafe_inherited_name(name: str) -> bool:
    """Drop overrides, provider authority, proxy routing and test artifact sinks.

    Prefix removal covers future application database overrides without another
    stale hand-maintained list. Preserve OS/process bootstrap (PATH/SystemRoot)
    so the same policy works on Windows and POSIX.
    """
    upper = name.upper()
    return (
        upper.startswith(("VR_", "VIBE_", "OPENAI_", "ANTHROPIC_", "CODEX_",
                          "TUSHARE_", "HITHINK_"))
        or upper.endswith(("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_GOLDEN_DIR"))
        or upper in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                     "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE",
                     "SSL_CERT_DIR", "NETRC", "HOMEDRIVE", "HOMEPATH"}
    )


def configure_pytest_environment(root: Path, environ: MutableMapping[str, str]) -> None:
    """Run before collecting application modules; never inspect secret values."""
    safe = storage_environment(root)
    for name in list(environ):
        if unsafe_inherited_name(name):
            del environ[name]
    environ.update(safe)


def legacy_private_inputs_present(repository: Path) -> bool:
    """Metadata only; never follow links or read legacy user files."""
    cache = repository / "backend" / ".cache"
    try:
        mode = cache.lstat().st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISDIR(mode):
        return True
    for name in ("portfolio.json", "myreports"):
        try:
            (cache / name).lstat()
        except FileNotFoundError:
            continue
        return True
    return False

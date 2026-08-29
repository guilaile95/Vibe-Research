"""Complete, offline Vibe data bundle built on ``local_data_snapshot``.

Run from ``backend``::

    python -m vibe_data_backup snapshot --output ARCHIVE.zip
    python -m vibe_data_backup verify --archive ARCHIVE.zip
    python -m vibe_data_backup restore --archive ARCHIVE.zip --target EMPTY_DIR
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import socket
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Callable, Iterable

import local_data_snapshot as snapshot
import research_data_plane_path
import review_db_path


BUNDLE_SCHEMA_VERSION = "vibe_data_backup.bundle.v0.1"
BUNDLE_CONSISTENCY_CONTRACT = "QUIESCENT_PRE_POST_SOURCE_STAT_V0.1"
BACKUP_REFUSED = "BACKUP_REFUSED_ACTIVE_OR_UNCERTAIN_WRITER"

QUIESCENT = "QUIESCENT"
ACTIVE = "ACTIVE"
UNCERTAIN = "UNCERTAIN"

_KNOWN_PORTS = (8900, 5899)
_EXCLUDED_NAMES = frozenset(
    {".git", ".venv", ".vibe-runtime", "node_modules", "runtime"}
)
_ASSET_STATUSES = frozenset(
    {"PRESENT", "ABSENT_OPTIONAL", "EXTERNAL_OVERRIDE_INCLUDED"}
)
_DB_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
_SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
_BUNDLE_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_POSSIBLE_VIBE_HOSTS = frozenset(
    {
        "node",
        "npm",
        "npx",
        "powershell",
        "py",
        "python",
        "pythonw",
        "pwsh",
        "uvicorn",
        "vite",
    }
)
_REQUIRED_ASSET_NAMES = frozenset(
    {
        "data_root",
        "shared_review_db",
        "reports",
        "fact_lake",
        "research_data_plane",
    }
)

QuiescentProbe = Callable[[], object]


class BundleError(snapshot.LocalSnapshotError):
    """The complete-bundle contract is invalid."""


class BackupRefused(BundleError):
    """A complete recovery point cannot be proven quiescent."""


def _configured_path(name: str, default: Path | None = None) -> Path | None:
    raw = os.environ.get(name, "").strip()
    if raw:
        return Path(raw).expanduser().absolute()
    return default.absolute() if default is not None else None


def _data_root() -> Path:
    root = _configured_path("VR_DATA_DIR", Path.home() / ".vibe-research")
    assert root is not None
    return root


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _relative_to(path: Path, root: Path) -> Path | None:
    try:
        return path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None


def _db_archive_name(path: Path) -> str:
    suffix = path.suffix.lower()
    return "database" + (suffix if suffix in _DB_SUFFIXES else ".db")


def _override_names() -> list[str]:
    return sorted(
        name
        for name in os.environ
        if (
            (name.startswith("VIBE_RESEARCH_") and name.endswith("_DB"))
            or name == "VIBE_NATIVE_INTEL_DB"
        )
        and name != review_db_path.REVIEW_DB_ENV
        and os.environ.get(name, "").strip()
    )


def _asset(name: str, kind: str, prefix: str, status: str) -> dict[str, str]:
    return {
        "name": name,
        "kind": kind,
        "archive_prefix": prefix,
        "status": status,
    }


def _database_entries(archive_path: str, database_path: Path) -> list[tuple[str, Path]]:
    """Return one external SQLite file plus any existing plain sidecars."""
    entries = [(archive_path, database_path)]
    for suffix in _SQLITE_SIDECAR_SUFFIXES:
        sidecar = Path(str(database_path) + suffix)
        if _plain_path_exists(sidecar, "SQLite sidecar", "file"):
            entries.append((archive_path + suffix, sidecar))
    return entries


def _assert_no_orphan_sidecars(database_path: Path, label: str) -> None:
    for suffix in _SQLITE_SIDECAR_SUFFIXES:
        if _plain_path_exists(Path(str(database_path) + suffix), label, "file"):
            raise BundleError(f"{label} 主库缺失但存在 orphan sidecar")


def _plain_path_exists(path: Path, label: str, kind: str) -> bool:
    try:
        entry_stat = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise BundleError(f"无法读取 {label} 路径状态") from exc
    violation = snapshot._entry_violation(entry_stat)
    expected = stat.S_ISREG(entry_stat.st_mode) if kind == "file" else stat.S_ISDIR(
        entry_stat.st_mode
    )
    if violation is not None or not expected:
        raise BundleError(f"{label} 不是 plain {kind}")
    return True


def _collect_directories(root: Path, archive_prefix: str) -> list[tuple[str, Path]]:
    """Collect safe directory paths so empty directories survive restore."""
    directories = [(archive_prefix, root.resolve())]
    for dirpath, dirnames, _filenames in os.walk(root.resolve(), followlinks=False):
        here = Path(dirpath)
        dirnames[:] = sorted(name for name in dirnames if name not in _EXCLUDED_NAMES)
        for name in dirnames:
            child = here / name
            if not _plain_path_exists(child, "数据目录", "directory"):
                raise BundleError("数据目录在收集期间消失")
            relative = child.relative_to(root.resolve()).as_posix()
            archive_path = f"{archive_prefix}/{relative}"
            if not _safe_bundle_prefix(archive_path):
                raise BundleError("数据目录 archive prefix 不可信")
            directories.append((archive_path, child.resolve()))
    return directories


def discover_bundle_sources() -> tuple[
    list[tuple[str, Path]], dict, tuple[tuple[Path, str], ...]
]:
    """Discover only the explicitly contracted Vibe persistence roots."""
    data_root = _data_root()
    if not _plain_path_exists(data_root, "VR_DATA_DIR", "directory"):
        raise BundleError("VR_DATA_DIR 不存在或不是目录")
    if (data_root / ".git").exists() or (data_root / ".git").is_symlink():
        raise BundleError("VR_DATA_DIR 指向 Git worktree，拒绝备份")

    review_db = review_db_path.resolve_review_db_path()
    review_explicit = bool(os.environ.get(review_db_path.REVIEW_DB_ENV, "").strip())
    review_configured_path = (
        Path(os.environ[review_db_path.REVIEW_DB_ENV].strip()).expanduser().absolute()
        if review_explicit
        else review_db
    )
    reports = _configured_path("VR_REPORTS_DIR", data_root / "myreports")
    reports_explicit = bool(os.environ.get("VR_REPORTS_DIR", "").strip())
    fact_lake = _configured_path("VR_FACT_LAKE_ROOT")
    research_data = research_data_plane_path.resolve_research_data_root().absolute()
    research_data_explicit = bool(
        os.environ.get(research_data_plane_path.RESEARCH_DATA_DIR_ENV, "").strip()
    )

    groups: list[tuple[str, Path]] = []
    assets: list[dict[str, str]] = []
    protected_paths: list[tuple[Path, str]] = [(data_root, "directory")]
    single_files: list[tuple[str, Path]] = []

    review_present = _plain_path_exists(
        review_configured_path, "shared daily-review DB", "file"
    )
    if review_explicit and not review_present:
        raise BundleError("显式 shared daily-review DB 不存在")
    if not review_present:
        _assert_no_orphan_sidecars(review_configured_path, "shared daily-review DB")
    review_status = "PRESENT"
    if review_present and review_explicit and _relative_to(review_db, data_root) is None:
        review_status = "EXTERNAL_OVERRIDE_INCLUDED"
    assets.append(
        _asset(
            "shared_review_db",
            "file",
            "shared-review/daily_reviews.sqlite3",
            review_status if review_present else "ABSENT_OPTIONAL",
        )
    )
    protected_paths.append((review_db, "file"))
    protected_paths.extend(
        (Path(str(review_db) + suffix), "file")
        for suffix in _SQLITE_SIDECAR_SUFFIXES
    )
    if review_present:
        single_files.extend(
            _database_entries("shared-review/daily_reviews.sqlite3", review_db)
        )

    if reports is not None and _plain_path_exists(reports, "reports", "directory"):
        if reports.resolve() == data_root.resolve():
            reports_prefix = "data"
        else:
            reports_prefix = "reports"
            groups.append((reports_prefix, reports))
        reports_status = "PRESENT"
        if reports_explicit and _relative_to(reports, data_root) is None:
            reports_status = "EXTERNAL_OVERRIDE_INCLUDED"
        assets.append(_asset("reports", "directory", reports_prefix, reports_status))
    else:
        assets.append(_asset("reports", "directory", "reports", "ABSENT_OPTIONAL"))
    if reports is not None:
        protected_paths.append((reports, "directory"))

    if fact_lake is not None and _plain_path_exists(fact_lake, "Fact Lake", "directory"):
        if fact_lake.resolve() == data_root.resolve():
            fact_prefix = "data"
        elif reports is not None and fact_lake.resolve() == reports.resolve():
            fact_prefix = "reports"
        else:
            fact_prefix = "fact-lake"
            groups.insert(0, (fact_prefix, fact_lake))
        fact_status = (
            "EXTERNAL_OVERRIDE_INCLUDED"
            if _relative_to(fact_lake, data_root) is None
            else "PRESENT"
        )
        assets.append(_asset("fact_lake", "directory", fact_prefix, fact_status))
    else:
        assets.append(_asset("fact_lake", "directory", "fact-lake", "ABSENT_OPTIONAL"))
    if fact_lake is not None:
        protected_paths.append((fact_lake, "directory"))

    if _plain_path_exists(research_data, "Research Data Plane", "directory"):
        same_root_prefix = next(
            (
                prefix
                for prefix, root in [("data", data_root), *groups]
                if root.resolve() == research_data.resolve()
            ),
            None,
        )
        research_prefix = same_root_prefix or "research-data"
        if same_root_prefix is None:
            groups.append((research_prefix, research_data))
        research_status = (
            "EXTERNAL_OVERRIDE_INCLUDED"
            if research_data_explicit
            and _relative_to(research_data, data_root) is None
            else "PRESENT"
        )
        assets.append(
            _asset(
                "research_data_plane",
                "directory",
                research_prefix,
                research_status,
            )
        )
    else:
        assets.append(
            _asset(
                "research_data_plane",
                "directory",
                "research-data",
                "ABSENT_OPTIONAL",
            )
        )
    protected_paths.append((research_data, "directory"))

    external_overrides: list[tuple[str, Path]] = []
    configured_overrides: list[tuple[str, Path, bool]] = []
    for env_name in _override_names():
        db_path = Path(os.environ[env_name].strip()).expanduser().absolute()
        exists = _plain_path_exists(db_path, env_name, "file")
        if not exists:
            raise BundleError(f"显式数据库不存在: {env_name}")
        outside_data_root = _relative_to(db_path, data_root) is None
        configured_overrides.append((env_name, db_path, outside_data_root))
        protected_paths.append((db_path, "file"))
        protected_paths.extend(
            (Path(str(db_path) + suffix), "file")
            for suffix in _SQLITE_SIDECAR_SUFFIXES
        )
        if outside_data_root:
            slug = env_name.lower().replace("_", "-")
            external_overrides.extend(
                _database_entries(
                    f"external-db/{slug}/{_db_archive_name(db_path)}", db_path
                )
            )

    # Deeper logical roots win so a parent never consumes a child partition first.
    raw_entries: list[tuple[str, Path]] = list(single_files) + external_overrides
    raw_directories: list[tuple[str, Path]] = []
    directory_groups = groups + [("data", data_root)]
    directory_groups.sort(key=lambda item: (-len(item[1].resolve().parts), item[0]))
    for prefix, root in directory_groups:
        raw_directories.extend(_collect_directories(root, prefix))
        raw_entries.extend(
            snapshot.collect_snapshot_sources(
                root,
                archive_prefix=prefix,
                excluded_names=_EXCLUDED_NAMES,
            )
        )

    entries: list[tuple[str, Path]] = []
    source_to_archive: dict[str, str] = {}
    archive_paths: set[str] = set()
    for archive_path, source in raw_entries:
        key = _path_key(source)
        if key in source_to_archive:
            continue
        if archive_path in archive_paths:
            raise BundleError(f"逻辑分区 archive path 冲突: {archive_path!r}")
        source_to_archive[key] = archive_path
        archive_paths.add(archive_path)
        entries.append((archive_path, source.resolve()))
    entries.sort(key=lambda item: item[0])

    directories: list[dict[str, str]] = []
    seen_directory_sources: set[str] = set()
    seen_directory_prefixes: set[str] = set()
    for archive_prefix, source in raw_directories:
        source_key = _path_key(source)
        if source_key in seen_directory_sources:
            continue
        if archive_prefix in seen_directory_prefixes:
            raise BundleError(f"逻辑分区 directory prefix 冲突: {archive_prefix!r}")
        seen_directory_sources.add(source_key)
        seen_directory_prefixes.add(archive_prefix)
        directories.append({"archive_prefix": archive_prefix, "status": "PRESENT"})
    directories.sort(key=lambda entry: entry["archive_prefix"])

    assets.insert(0, _asset("data_root", "directory", "data", "PRESENT"))
    for env_name, db_path, outside_data_root in configured_overrides:
        archive_path = source_to_archive.get(_path_key(db_path))
        if archive_path is None:
            raise BundleError(f"已配置数据库未进入逻辑数据包: {env_name}")
        status = "EXTERNAL_OVERRIDE_INCLUDED" if outside_data_root else "PRESENT"
        assets.append(_asset(env_name, "file", archive_path, status))

    bundle = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "consistency_contract": BUNDLE_CONSISTENCY_CONTRACT,
        "excluded_names": sorted(_EXCLUDED_NAMES),
        "assets": assets,
        "directories": directories,
    }
    return entries, bundle, tuple(protected_paths)


def _port_state(port: int) -> str:
    refused = {errno.ECONNREFUSED, getattr(errno, "WSAECONNREFUSED", 10061)}
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(0.3)
        result = sock.connect_ex(("127.0.0.1", port))
    except OSError:
        return UNCERTAIN
    finally:
        sock.close()
    if result == 0:
        return ACTIVE
    return QUIESCENT if result in refused else UNCERTAIN


def _looks_like_vibe_process(command: str, executable: str = "") -> bool:
    text = f"{executable} {command}".replace("\\", "/").lower()
    return (
        "start-vibe.ps1" in text
        or ("uvicorn" in text and "app:app" in text)
        or (("vite" in text or "npm" in text) and "--port" in text and "5899" in text)
    )


def _windows_process_state() -> str:
    script = (
        "$ErrorActionPreference='Stop';"
        "$p=Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,Name,ExecutablePath,CommandLine;"
        "ConvertTo-Json -Compress -InputObject @($p)"
    )
    try:
        result = subprocess.run(
            [
                "pwsh.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return UNCERTAIN
        rows = json.loads(result.stdout.lstrip("\ufeff") or "null")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return UNCERTAIN
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list) or not rows:
        return UNCERTAIN
    uncertain_host = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        command = str(row.get("CommandLine") or "")
        executable = str(row.get("ExecutablePath") or "")
        if _looks_like_vibe_process(command, executable):
            return ACTIVE
        host = str(row.get("Name") or executable)
        host = host.replace("\\", "/").rsplit("/", 1)[-1].lower()
        host = host.rsplit(".", 1)[0]
        if not command.strip() and (not host or host in _POSSIBLE_VIBE_HOSTS):
            uncertain_host = True
    return UNCERTAIN if uncertain_host else QUIESCENT


def _linux_process_state(proc_root: Path = Path("/proc")) -> str:
    if not proc_root.is_dir():
        return UNCERTAIN
    saw_process = False
    for entry in proc_root.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except FileNotFoundError:
            continue
        except (OSError, PermissionError):
            try:
                if hasattr(os, "geteuid") and entry.stat().st_uid == os.geteuid():
                    return UNCERTAIN
            except OSError:
                continue
            continue
        saw_process = True
        command = raw.replace(b"\0", b" ").decode("utf-8", errors="replace")
        if _looks_like_vibe_process(command):
            return ACTIVE
    return QUIESCENT if saw_process else UNCERTAIN


def _process_state() -> str:
    if os.name == "nt":
        return _windows_process_state()
    if sys.platform.startswith("linux"):
        return _linux_process_state()
    return UNCERTAIN


def default_quiescent_probe(
    *,
    ports: Iterable[int] = _KNOWN_PORTS,
    process_probe: Callable[[], str] = _process_state,
) -> str:
    for port in ports:
        state = _port_state(int(port))
        if state != QUIESCENT:
            return state
    try:
        state = process_probe()
    except Exception:  # noqa: BLE001 - any uncertainty must fail closed
        return UNCERTAIN
    return state if state in {QUIESCENT, ACTIVE} else UNCERTAIN


def _assert_quiescent(probe: QuiescentProbe) -> None:
    try:
        state = probe()
    except Exception as exc:  # noqa: BLE001 - public refusal is intentionally fixed
        raise BackupRefused(BACKUP_REFUSED) from exc
    if state is not True and state != QUIESCENT:
        raise BackupRefused(BACKUP_REFUSED)


def _source_state(entries: Iterable[tuple[str, Path]]) -> tuple[tuple, ...]:
    state = []
    for archive_path, source in entries:
        try:
            st = os.lstat(source)
        except OSError as exc:
            raise BackupRefused(BACKUP_REFUSED) from exc
        state.append(
            (archive_path, _path_key(source), st.st_mode, st.st_size, st.st_mtime_ns)
        )
    return tuple(sorted(state))


def _bundle_state(entries: list[tuple[str, Path]], bundle: dict) -> tuple:
    assets = tuple(
        sorted(
            (
                asset["name"],
                asset["kind"],
                asset["archive_prefix"],
                asset["status"],
            )
            for asset in bundle["assets"]
        )
    )
    directories = tuple(
        (entry["archive_prefix"], entry["status"])
        for entry in bundle["directories"]
    )
    return _source_state(entries), assets, directories


def _output_conflicts(
    output: Path, protected_paths: Iterable[tuple[Path, str]]
) -> bool:
    resolved = output.resolve()
    for path, kind in protected_paths:
        if kind == "file" and resolved == path.resolve():
            return True
        if kind == "directory" and _relative_to(resolved, path) is not None:
            return True
    return False


def _safe_bundle_prefix(prefix: object) -> bool:
    if not isinstance(prefix, str) or not prefix:
        return False
    return snapshot._member_name_violation(f"{prefix}/_") is None


def _has_excluded_component(path: str) -> bool:
    return any(part.casefold() in _EXCLUDED_NAMES for part in path.split("/"))


def _validate_bundle(manifest: dict) -> dict:
    bundle = manifest.get("vibe_bundle")
    if not isinstance(bundle, dict):
        raise BundleError("archive 缺少 vibe_bundle manifest")
    if bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise BundleError("vibe_bundle schema version 不受支持")
    if bundle.get("consistency_contract") != BUNDLE_CONSISTENCY_CONTRACT:
        raise BundleError("vibe_bundle consistency contract 不受支持")
    if set(bundle) != {
        "schema_version",
        "consistency_contract",
        "excluded_names",
        "assets",
        "directories",
    }:
        raise BundleError("vibe_bundle 字段不合法")
    if bundle.get("excluded_names") != sorted(_EXCLUDED_NAMES):
        raise BundleError("vibe_bundle exclusion contract 不受支持")
    assets = bundle.get("assets")
    if not isinstance(assets, list):
        raise BundleError("vibe_bundle assets 不是数组")
    raw_directories = bundle.get("directories")
    if not isinstance(raw_directories, list):
        raise BundleError("vibe_bundle directories 不是数组")
    directory_prefixes: set[str] = set()
    portable_directories: dict[tuple[str, ...], str] = {}
    for index, directory in enumerate(raw_directories):
        if not isinstance(directory, dict) or set(directory) != {
            "archive_prefix",
            "status",
        }:
            raise BundleError(f"vibe_bundle directories[{index}] 字段不合法")
        prefix = directory["archive_prefix"]
        if not _safe_bundle_prefix(prefix):
            raise BundleError(f"vibe_bundle directories[{index}] prefix 不可信")
        if _has_excluded_component(prefix):
            raise BundleError(f"vibe_bundle directories[{index}] 命中排除项")
        if directory["status"] != "PRESENT":
            raise BundleError(f"vibe_bundle directories[{index}] status 不合法")
        if prefix in directory_prefixes:
            raise BundleError(f"vibe_bundle directories[{index}] prefix 重复")
        directory_prefixes.add(prefix)
        portable_key = snapshot._windows_member_key(prefix)
        portable_peer = portable_directories.get(portable_key)
        if portable_peer is not None and portable_peer != prefix:
            raise BundleError(
                "vibe_bundle directory 在 Windows 上碰撞: "
                f"{portable_peer!r} 与 {prefix!r}"
            )
        portable_directories.setdefault(portable_key, prefix)

    file_paths = {
        entry.get("path")
        for entry in manifest.get("files", [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    if any(_has_excluded_component(path) for path in file_paths):
        raise BundleError("vibe_bundle file path 命中排除项")
    portable_files = {
        snapshot._windows_member_key(path): path for path in file_paths
    }
    for portable_key, prefix in portable_directories.items():
        conflicting_file = portable_files.get(portable_key)
        if conflicting_file is not None:
            raise BundleError(
                "vibe_bundle file/directory 路径冲突: "
                f"{conflicting_file!r} 与 {prefix!r}"
            )
        for end in range(1, len(portable_key)):
            conflicting_file = portable_files.get(portable_key[:end])
            if conflicting_file is not None:
                raise BundleError(
                    "vibe_bundle file/directory 拓扑冲突: "
                    f"文件 {conflicting_file!r} 是目录 {prefix!r} 的祖先"
                )
    names: set[str] = set()
    present_files: set[str] = set()
    present_directories: set[str] = set()
    absent_assets: list[tuple[str, str, int]] = []
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            raise BundleError(f"vibe_bundle assets[{index}] 不是 object")
        if set(asset) != {"name", "kind", "archive_prefix", "status"}:
            raise BundleError(f"vibe_bundle assets[{index}] 字段不合法")
        if not isinstance(asset["name"], str) or not _BUNDLE_NAME_RE.fullmatch(
            asset["name"]
        ):
            raise BundleError(f"vibe_bundle assets[{index}] name 不合法")
        if asset["name"] in names:
            raise BundleError(f"vibe_bundle assets[{index}] name 重复")
        names.add(asset["name"])
        if asset["kind"] not in {"file", "directory"}:
            raise BundleError(f"vibe_bundle assets[{index}] kind 不合法")
        if asset["status"] not in _ASSET_STATUSES:
            raise BundleError(f"vibe_bundle assets[{index}] status 不合法")
        if not _safe_bundle_prefix(asset["archive_prefix"]):
            raise BundleError(f"vibe_bundle assets[{index}] archive prefix 不可信")
        prefix = asset["archive_prefix"]
        if _has_excluded_component(prefix):
            raise BundleError(f"vibe_bundle assets[{index}] 命中排除项")
        present = asset["status"] in {"PRESENT", "EXTERNAL_OVERRIDE_INCLUDED"}
        if asset["kind"] == "file" and present and prefix not in file_paths:
            raise BundleError(f"vibe_bundle assets[{index}] file 未登记")
        if asset["kind"] == "directory" and present and prefix not in directory_prefixes:
            raise BundleError(f"vibe_bundle assets[{index}] directory 未登记")
        if present and asset["kind"] == "file":
            present_files.add(prefix)
        elif present:
            present_directories.add(prefix)
        else:
            absent_assets.append((asset["kind"], prefix, index))
    if not _REQUIRED_ASSET_NAMES.issubset(names):
        raise BundleError("vibe_bundle 缺少核心资产声明")

    registered = file_paths | directory_prefixes
    for kind, prefix, index in absent_assets:
        blocked = {prefix}
        if kind == "file":
            blocked.update(prefix + suffix for suffix in _SQLITE_SIDECAR_SUFFIXES)
        if any(path in blocked or path.startswith(prefix + "/") for path in registered):
            raise BundleError(f"vibe_bundle assets[{index}] absence 与内容冲突")

    for path in file_paths:
        if path in present_files:
            continue
        if any(
            path == prefix + suffix
            for prefix in present_files
            if Path(prefix).suffix.lower() in _DB_SUFFIXES
            for suffix in _SQLITE_SIDECAR_SUFFIXES
        ):
            continue
        if any(path.startswith(prefix + "/") for prefix in present_directories):
            continue
        raise BundleError(f"vibe_bundle file 未被资产声明覆盖: {path!r}")

    for prefix in directory_prefixes:
        if not any(
            prefix == root or prefix.startswith(root + "/")
            for root in present_directories
        ):
            raise BundleError(f"vibe_bundle directory 未被资产声明覆盖: {prefix!r}")
    return bundle


def _publish_no_replace(staged: Path, output: Path) -> None:
    if os.name == "nt":
        try:
            os.rename(staged, output)
        except FileExistsError as exc:
            raise BundleError("输出 archive 已存在，拒绝覆盖") from exc
        return
    try:
        os.link(staged, output)
    except FileExistsError as exc:
        raise BundleError("输出 archive 已存在，拒绝覆盖") from exc
    staged.unlink()


def create_bundle(
    output_archive,
    *,
    quiescent_probe: QuiescentProbe = default_quiescent_probe,
) -> dict:
    output = Path(output_archive)
    if output.exists() or output.is_symlink():
        raise BundleError("输出 archive 已存在，拒绝覆盖")
    if not output.parent.is_dir():
        raise BundleError("输出目录不存在")

    _assert_quiescent(quiescent_probe)
    entries, bundle, protected_paths = discover_bundle_sources()
    if _output_conflicts(output, protected_paths):
        raise BundleError("输出 archive 不得位于被备份目录内")
    before = _bundle_state(entries, bundle)

    staged = output.parent / f".{output.name}.{uuid.uuid4().hex}.staged.zip"
    try:
        snapshot.create_snapshot_from_files(
            entries,
            staged,
            manifest_extension={"vibe_bundle": bundle},
        )
        manifest = snapshot.read_verified_manifest(staged)
        verified_bundle = _validate_bundle(manifest)

        try:
            after_entries, after_bundle, _ = discover_bundle_sources()
            after = _bundle_state(after_entries, after_bundle)
        except BackupRefused:
            raise
        except Exception as exc:  # noqa: BLE001 - changed/unknown source refuses publish
            raise BackupRefused(BACKUP_REFUSED) from exc
        if before != after:
            raise BackupRefused(BACKUP_REFUSED)
        _assert_quiescent(quiescent_probe)

        _publish_no_replace(staged, output)
        return {
            "status": "OK",
            "operation": "snapshot",
            "file_count": manifest["file_count"],
            "total_bytes": manifest["total_bytes"],
            "vibe_bundle_schema": verified_bundle["schema_version"],
            "assets": verified_bundle["assets"],
        }
    finally:
        staged.unlink(missing_ok=True)


def verify_bundle(archive_path) -> dict:
    report = snapshot.verify_snapshot(archive_path)
    if report["status"] != "OK":
        return report
    try:
        manifest = snapshot.read_verified_manifest(archive_path)
        bundle = _validate_bundle(manifest)
    except (snapshot.VerifyError, BundleError) as exc:
        return {"status": "FAILED", "operation": "verify", "errors": [str(exc)]}
    return {
        **report,
        "vibe_bundle_schema": bundle["schema_version"],
        "assets": bundle["assets"],
    }


def restore_bundle(archive_path, target_dir) -> dict:
    try:
        manifest = snapshot.read_verified_manifest(archive_path)
        bundle = _validate_bundle(manifest)
    except (snapshot.VerifyError, BundleError) as exc:
        raise snapshot.RestoreRefused(
            "archive 未通过完整 Vibe 数据包验证，restore 拒绝执行"
        ) from exc

    result = snapshot.restore_snapshot(archive_path, target_dir)
    target = Path(target_dir)
    try:
        for directory in bundle["directories"]:
            target.joinpath(*directory["archive_prefix"].split("/")).mkdir(
                parents=True, exist_ok=True
            )
    except OSError as exc:
        raise snapshot.RestoreFailed(
            "restore 后无法重建 manifest 声明的空目录"
        ) from exc
    return {
        **result,
        "vibe_bundle_schema": bundle["schema_version"],
        "assets": bundle["assets"],
    }


def main(argv=None, *, quiescent_probe: QuiescentProbe | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vibe_data_backup",
        description="完整 Vibe 本地数据离线备份 / 验证 / 恢复",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("snapshot")
    create.add_argument("--output", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--archive", required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("--archive", required=True)
    restore.add_argument("--target", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "snapshot":
            result = create_bundle(
                args.output,
                quiescent_probe=quiescent_probe or default_quiescent_probe,
            )
            code = snapshot.EXIT_OK
        elif args.command == "verify":
            result = verify_bundle(args.archive)
            code = snapshot.EXIT_OK if result["status"] == "OK" else snapshot.EXIT_VERIFY_FAILED
        else:
            result = restore_bundle(args.archive, args.target)
            code = snapshot.EXIT_OK
    except BackupRefused:
        result = {"status": "REFUSED", "reason": BACKUP_REFUSED}
        code = snapshot.EXIT_RESTORE_REFUSED
    except snapshot.RestoreRefused as exc:
        result = {"status": "REFUSED", "reason": str(exc)}
        code = snapshot.EXIT_RESTORE_REFUSED
    except snapshot.RestoreFailed as exc:
        result = {"status": "FAILED", "reason": str(exc)}
        code = snapshot.EXIT_RESTORE_FAILED
    except (BundleError, snapshot.LocalSnapshotError) as exc:
        result = {"status": "FAILED", "reason": str(exc)}
        code = snapshot.EXIT_SNAPSHOT_FAILED
    except OSError as exc:
        result = {"status": "FAILED", "reason": f"IO 错误: {type(exc).__name__}"}
        code = snapshot.EXIT_ERROR
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())

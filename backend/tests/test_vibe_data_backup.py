from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import local_data_snapshot as local_snapshot
import vibe_data_backup as backup


def _clear_bundle_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if (
            name in {"VR_DATA_DIR", "VR_REPORTS_DIR", "VR_FACT_LAKE_ROOT"}
            or (name.startswith("VIBE_RESEARCH_") and name.endswith("_DB"))
            or name == "VIBE_NATIVE_INTEL_DB"
        ):
            monkeypatch.delenv(name, raising=False)


def _minimal_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _clear_bundle_env(monkeypatch)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("VR_DATA_DIR", str(data))
    missing_review = tmp_path / "default-review" / "daily_reviews.sqlite3"
    monkeypatch.setattr(
        backup.review_db_path, "resolve_review_db_path", lambda: missing_review
    )
    return data


def _sqlite(path: Path, value: str = "fixture") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE records (value TEXT NOT NULL)")
        connection.execute("INSERT INTO records VALUES (?)", (value,))


def _wal_sqlite_snapshot(path: Path) -> None:
    """Create a self-consistent synthetic SQLite main/WAL/SHM triplet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = path.parent / "fixture-writer.sqlite3"
    connection = sqlite3.connect(writer)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE records (value TEXT NOT NULL)")
        connection.execute("INSERT INTO records VALUES ('committed-in-wal')")
        connection.commit()
        for suffix in ("", "-wal", "-shm"):
            source = Path(str(writer) + suffix)
            Path(str(path) + suffix).write_bytes(source.read_bytes())
    finally:
        connection.close()
        writer.unlink(missing_ok=True)


def _quick_check(path: Path) -> str:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        return connection.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        connection.close()


def _forge_bundle_manifest(source: Path, target: Path, mutate) -> None:
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(
        target, "w", zipfile.ZIP_DEFLATED
    ) as output:
        for info in original.infolist():
            raw = original.read(info.filename)
            if info.filename == local_snapshot.MANIFEST_MEMBER_NAME:
                manifest = json.loads(raw.decode("utf-8"))
                mutate(manifest["vibe_bundle"])
                raw = (
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
                    + "\n"
                ).encode("utf-8")
            output.writestr(info.filename, raw)


def _synthetic_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    _clear_bundle_env(monkeypatch)
    data = tmp_path / "data"
    review = tmp_path / "review" / "daily_reviews.sqlite3"
    reports = tmp_path / "reports"
    fact = tmp_path / "fact-lake"
    external = tmp_path / "external" / "custom.sqlite3"

    data.mkdir()
    (data / "portfolio.json").write_text(
        json.dumps({"holdings": [], "closed": []}), encoding="utf-8"
    )
    _sqlite(data / "native_intel.sqlite3")
    _sqlite(review)
    reports.mkdir()
    (reports / "report.md").write_text("synthetic report", encoding="utf-8")
    (reports / "empty-folder").mkdir()
    (fact / "raw").mkdir(parents=True)
    (fact / "canonical").mkdir()
    (fact / "raw" / "item.json").write_text('{"ok": true}', encoding="utf-8")
    _sqlite(fact / "control.sqlite3")
    _wal_sqlite_snapshot(external)

    # These names are explicitly outside the complete bundle contract.
    for excluded in ("runtime", ".venv", "node_modules", ".vibe-runtime"):
        hidden = data / excluded
        hidden.mkdir()
        (hidden / "must-not-back-up.txt").write_text("excluded", encoding="utf-8")

    monkeypatch.setenv("VR_DATA_DIR", str(data))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(review))
    monkeypatch.setenv("VR_REPORTS_DIR", str(reports))
    monkeypatch.setenv("VR_FACT_LAKE_ROOT", str(fact))
    monkeypatch.setenv("VIBE_RESEARCH_CUSTOM_DB", str(external))
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DB", str(data / "native_intel.sqlite3"))
    return {
        "data": data,
        "review": review,
        "reports": reports,
        "fact": fact,
        "external": external,
    }


def test_complete_bundle_snapshot_verify_restore_drill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _synthetic_bundle(tmp_path, monkeypatch)
    archive = tmp_path / "complete.zip"

    result = backup.create_bundle(archive, quiescent_probe=lambda: backup.QUIESCENT)
    assert result["status"] == "OK"
    assert backup.verify_bundle(archive)["status"] == "OK"

    manifest = local_snapshot.read_verified_manifest(archive)
    bundle = manifest["vibe_bundle"]
    assert bundle["schema_version"] == backup.BUNDLE_SCHEMA_VERSION
    assert str(tmp_path) not in json.dumps(bundle)
    statuses = {asset["name"]: asset["status"] for asset in bundle["assets"]}
    assert statuses == {
        "data_root": "PRESENT",
        "shared_review_db": "EXTERNAL_OVERRIDE_INCLUDED",
        "reports": "EXTERNAL_OVERRIDE_INCLUDED",
        "fact_lake": "EXTERNAL_OVERRIDE_INCLUDED",
        "VIBE_NATIVE_INTEL_DB": "PRESENT",
        "VIBE_RESEARCH_CUSTOM_DB": "EXTERNAL_OVERRIDE_INCLUDED",
    }

    restored = tmp_path / "restored"
    restore = backup.restore_bundle(archive, restored)
    assert restore["status"] == "OK"
    assert json.loads((restored / "data" / "portfolio.json").read_text(encoding="utf-8"))[
        "holdings"
    ] == []
    assert json.loads((restored / "fact-lake" / "raw" / "item.json").read_text()) == {
        "ok": True
    }

    restored_sqlite = [
        restored / "data" / "native_intel.sqlite3",
        restored / "shared-review" / "daily_reviews.sqlite3",
        restored / "fact-lake" / "control.sqlite3",
        restored
        / "external-db"
        / "vibe-research-custom-db"
        / "database.sqlite3",
    ]
    external_restored = restored_sqlite[-1]
    assert Path(str(external_restored) + "-wal").is_file()
    assert Path(str(external_restored) + "-shm").is_file()

    expected = {
        entry["path"]: (entry["size"], entry["sha256"])
        for entry in manifest["files"]
    }
    actual = {}
    for path in restored.rglob("*"):
        if path.is_file():
            raw = path.read_bytes()
            actual[path.relative_to(restored).as_posix()] = (
                len(raw),
                hashlib.sha256(raw).hexdigest(),
            )
    assert actual == expected
    assert [_quick_check(path) for path in restored_sqlite] == ["ok"] * 4
    assert not any("must-not-back-up.txt" in name for name in actual)
    assert (restored / "fact-lake" / "canonical").is_dir()
    assert (restored / "reports" / "empty-folder").is_dir()
    assert paths["external"].is_file()  # restore drill never modifies its synthetic sources


def test_optional_absence_is_recorded_without_creating_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _minimal_data_root(tmp_path, monkeypatch)

    archive = tmp_path / "empty.zip"
    backup.create_bundle(archive, quiescent_probe=lambda: True)
    manifest = local_snapshot.read_verified_manifest(archive)
    statuses = {
        asset["name"]: asset["status"]
        for asset in manifest["vibe_bundle"]["assets"]
    }
    assert statuses["shared_review_db"] == "ABSENT_OPTIONAL"
    assert statuses["reports"] == "ABSENT_OPTIONAL"
    assert statuses["fact_lake"] == "ABSENT_OPTIONAL"

    target = tmp_path / "target"
    backup.restore_bundle(archive, target)
    assert (target / "data").is_dir()
    assert not (target / "reports").exists()
    assert not (target / "fact-lake").exists()
    assert not (target / "shared-review").exists()


@pytest.mark.parametrize("missing_kind", ["review", "override"])
def test_explicit_missing_database_refuses_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_kind: str
) -> None:
    _minimal_data_root(tmp_path, monkeypatch)
    missing = tmp_path / "missing" / "database.sqlite3"
    if missing_kind == "review":
        monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(missing))
        monkeypatch.setattr(
            backup.review_db_path,
            "resolve_review_db_path",
            lambda: missing,
        )
    else:
        monkeypatch.setenv("VIBE_RESEARCH_LAZY_DB", str(missing))

    output = tmp_path / f"{missing_kind}.zip"
    with pytest.raises(backup.BundleError, match="显式"):
        backup.create_bundle(output, quiescent_probe=lambda: backup.QUIESCENT)
    assert not output.exists()
    assert not missing.parent.exists()


def test_default_review_orphan_sidecar_refuses_optional_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _minimal_data_root(tmp_path, monkeypatch)
    review = backup.review_db_path.resolve_review_db_path()
    review.parent.mkdir(parents=True)
    Path(str(review) + "-wal").write_bytes(b"synthetic orphan")
    output = tmp_path / "orphan.zip"
    with pytest.raises(backup.BundleError, match="orphan sidecar"):
        backup.create_bundle(output, quiescent_probe=lambda: backup.QUIESCENT)
    assert not output.exists()


@pytest.mark.parametrize("parent", ["fact", "data"])
def test_nested_directory_assets_keep_the_deeper_logical_partition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parent: str
) -> None:
    data = _minimal_data_root(tmp_path, monkeypatch)
    fact = tmp_path / "fact"
    if parent == "fact":
        reports = fact / "reports"
        fact.mkdir()
        (fact / "fact.json").write_text("{}", encoding="utf-8")
        monkeypatch.setenv("VR_FACT_LAKE_ROOT", str(fact))
        parent_prefix = "fact-lake"
    else:
        reports = data / "reports"
        (data / "data.json").write_text("{}", encoding="utf-8")
        parent_prefix = "data"
    reports.mkdir()
    (reports / "report.md").write_text("synthetic", encoding="utf-8")
    monkeypatch.setenv("VR_REPORTS_DIR", str(reports))

    archive = tmp_path / f"{parent}.zip"
    backup.create_bundle(archive, quiescent_probe=lambda: backup.QUIESCENT)
    files = {
        entry["path"] for entry in local_snapshot.read_verified_manifest(archive)["files"]
    }
    assert "reports/report.md" in files
    assert f"{parent_prefix}/reports/report.md" not in files


def test_fact_lake_child_is_not_consumed_by_reports_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _minimal_data_root(tmp_path, monkeypatch)
    reports = tmp_path / "reports"
    fact = reports / "fact"
    fact.mkdir(parents=True)
    (reports / "report.md").write_text("synthetic", encoding="utf-8")
    (fact / "fact.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("VR_REPORTS_DIR", str(reports))
    monkeypatch.setenv("VR_FACT_LAKE_ROOT", str(fact))

    archive = tmp_path / "reports-parent.zip"
    backup.create_bundle(archive, quiescent_probe=lambda: backup.QUIESCENT)
    files = {
        entry["path"] for entry in local_snapshot.read_verified_manifest(archive)["files"]
    }
    assert "reports/report.md" in files
    assert "fact-lake/fact.json" in files
    assert "reports/fact/fact.json" not in files


def test_git_worktree_data_root_and_existing_output_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _minimal_data_root(tmp_path, monkeypatch)
    (data / ".git").write_text("gitdir: synthetic", encoding="utf-8")
    with pytest.raises(backup.BundleError, match="Git worktree"):
        backup.create_bundle(
            tmp_path / "worktree.zip", quiescent_probe=lambda: backup.QUIESCENT
        )

    (data / ".git").unlink()
    output = tmp_path / "existing.zip"
    output.write_bytes(b"do-not-overwrite")
    with pytest.raises(backup.BundleError, match="拒绝覆盖"):
        backup.create_bundle(output, quiescent_probe=lambda: backup.QUIESCENT)
    assert output.read_bytes() == b"do-not-overwrite"


def test_publish_race_never_replaces_concurrently_created_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = tmp_path / "staged.zip"
    output = tmp_path / "final.zip"
    staged.write_bytes(b"verified-archive")
    if os.name == "nt":
        real_publish = backup.os.rename

        def racing_publish(source, destination):
            Path(destination).write_bytes(b"concurrent-owner")
            return real_publish(source, destination)

        monkeypatch.setattr(backup.os, "rename", racing_publish)
    else:
        real_publish = backup.os.link

        def racing_publish(source, destination):
            Path(destination).write_bytes(b"concurrent-owner")
            return real_publish(source, destination)

        monkeypatch.setattr(backup.os, "link", racing_publish)
    with pytest.raises(backup.BundleError, match="拒绝覆盖"):
        backup._publish_no_replace(staged, output)
    assert output.read_bytes() == b"concurrent-owner"
    assert staged.read_bytes() == b"verified-archive"


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink creation is deterministic in CI")
def test_configured_asset_symlink_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _minimal_data_root(tmp_path, monkeypatch)
    real_reports = tmp_path / "real-reports"
    real_reports.mkdir()
    linked_reports = tmp_path / "linked-reports"
    os.symlink(real_reports, linked_reports)
    monkeypatch.setenv("VR_REPORTS_DIR", str(linked_reports))
    with pytest.raises(backup.BundleError, match="plain directory"):
        backup.create_bundle(
            tmp_path / "symlink.zip", quiescent_probe=lambda: backup.QUIESCENT
        )


def test_active_temporary_port_refuses_without_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _minimal_data_root(tmp_path, monkeypatch)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    archive = tmp_path / "refused.zip"
    try:
        probe = lambda: backup.default_quiescent_probe(
            ports=(port,), process_probe=lambda: backup.QUIESCENT
        )
        with pytest.raises(backup.BackupRefused, match=backup.BACKUP_REFUSED):
            backup.create_bundle(archive, quiescent_probe=probe)
    finally:
        listener.close()
    assert not archive.exists()


def test_active_temporary_process_and_uncertain_probe_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _minimal_data_root(tmp_path, monkeypatch)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        process_probe = lambda: backup.ACTIVE if child.poll() is None else backup.QUIESCENT
        with pytest.raises(backup.BackupRefused, match=backup.BACKUP_REFUSED):
            backup.create_bundle(tmp_path / "process.zip", quiescent_probe=process_probe)
    finally:
        child.terminate()
        child.wait(timeout=10)

    def uncertain():
        raise PermissionError("synthetic process inventory denial")

    with pytest.raises(backup.BackupRefused, match=backup.BACKUP_REFUSED):
        backup.create_bundle(tmp_path / "uncertain.zip", quiescent_probe=uncertain)
    assert not (tmp_path / "process.zip").exists()
    assert not (tmp_path / "uncertain.zip").exists()


def test_postflight_active_refuses_staged_archive_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _minimal_data_root(tmp_path, monkeypatch)
    (data / "settings.json").write_text("{}", encoding="utf-8")
    states = iter((backup.QUIESCENT, backup.ACTIVE))
    output = tmp_path / "postflight.zip"
    with pytest.raises(backup.BackupRefused, match=backup.BACKUP_REFUSED):
        backup.create_bundle(output, quiescent_probe=lambda: next(states))
    assert not output.exists()
    assert not list(tmp_path.glob(".*.staged.zip"))


def test_source_change_during_snapshot_refuses_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _minimal_data_root(tmp_path, monkeypatch)
    source = data / "settings.json"
    source.write_text("{}", encoding="utf-8")
    real_create = local_snapshot.create_snapshot_from_files

    def create_then_mutate(*args, **kwargs):
        result = real_create(*args, **kwargs)
        source.write_text('{"changed":true}', encoding="utf-8")
        return result

    monkeypatch.setattr(local_snapshot, "create_snapshot_from_files", create_then_mutate)
    output = tmp_path / "changed.zip"
    with pytest.raises(backup.BackupRefused, match=backup.BACKUP_REFUSED):
        backup.create_bundle(output, quiescent_probe=lambda: backup.QUIESCENT)
    assert not output.exists()


def test_process_matcher_and_linux_probe_use_only_synthetic_rows(tmp_path: Path) -> None:
    assert backup._looks_like_vibe_process("python -m uvicorn app:app --port 43210")
    assert not backup._looks_like_vibe_process("python -c 'import time; time.sleep(1)'")

    fake_proc = tmp_path / "424242"
    fake_proc.mkdir()
    (fake_proc / "cmdline").write_bytes(b"python\0-m\0uvicorn\0app:app\0")
    assert backup._linux_process_state(tmp_path) == backup.ACTIVE


def test_windows_process_probe_fails_closed_only_for_possible_vibe_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def run_with(rows):
        def fake_run(command, **_kwargs):
            captured.append(command)
            return subprocess.CompletedProcess(command, 0, json.dumps(rows), "")

        monkeypatch.setattr(backup.subprocess, "run", fake_run)
        return backup._windows_process_state()

    system = {"Name": "System", "ExecutablePath": None, "CommandLine": None}
    assert run_with([system]) == backup.QUIESCENT
    assert run_with([{"ProcessId": 42}]) == backup.UNCERTAIN
    assert (
        run_with([system, {"Name": "python.exe", "CommandLine": None}])
        == backup.UNCERTAIN
    )
    assert (
        run_with(
            [
                {"Name": "node.exe", "CommandLine": None},
                {
                    "Name": "python.exe",
                    "ExecutablePath": "C:\\Python\\python.exe",
                    "CommandLine": "python -m uvicorn app:app --port 8900",
                },
            ]
        )
        == backup.ACTIVE
    )
    assert all(
        "ProcessId,Name,ExecutablePath,CommandLine" in call[-1] for call in captured
    )


def test_cli_snapshot_verify_restore_uses_injected_quiescence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = _minimal_data_root(tmp_path, monkeypatch)
    (data / "settings.json").write_text('{"theme":"dark"}', encoding="utf-8")
    archive = tmp_path / "cli.zip"
    target = tmp_path / "cli-restored"

    assert (
        backup.main(
            ["snapshot", "--output", str(archive)],
            quiescent_probe=lambda: backup.QUIESCENT,
        )
        == local_snapshot.EXIT_OK
    )
    assert json.loads(capsys.readouterr().out)["status"] == "OK"
    assert backup.main(["verify", "--archive", str(archive)]) == local_snapshot.EXIT_OK
    assert json.loads(capsys.readouterr().out)["status"] == "OK"
    assert (
        backup.main(
            ["restore", "--archive", str(archive), "--target", str(target)]
        )
        == local_snapshot.EXIT_OK
    )
    assert json.loads(capsys.readouterr().out)["status"] == "OK"
    assert json.loads((target / "data" / "settings.json").read_text())["theme"] == "dark"


def test_restore_rejects_unsafe_bundle_empty_directory_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _minimal_data_root(tmp_path, monkeypatch)
    source = tmp_path / "source.zip"
    backup.create_bundle(source, quiescent_probe=lambda: True)

    forged = tmp_path / "forged.zip"
    _forge_bundle_manifest(
        source,
        forged,
        lambda bundle: bundle["assets"][0].update(archive_prefix="../escape"),
    )

    report = backup.verify_bundle(forged)
    assert report["status"] == "FAILED"
    target = tmp_path / "target"
    with pytest.raises(local_snapshot.RestoreRefused):
        backup.restore_bundle(forged, target)
    assert not target.exists()

    missing_assets = local_snapshot.read_verified_manifest(source)
    missing_assets["vibe_bundle"]["assets"] = []
    with pytest.raises(backup.BundleError, match="核心资产"):
        backup._validate_bundle(missing_assets)


@pytest.mark.parametrize(
    "directory_prefixes",
    [
        ["data/Foo", "data/foo"],
        ["data/settings.json"],
    ],
)
def test_restore_rejects_windows_colliding_bundle_directories_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    directory_prefixes: list[str],
) -> None:
    data = _minimal_data_root(tmp_path, monkeypatch)
    (data / "settings.json").write_text("{}", encoding="utf-8")
    source = tmp_path / "source.zip"
    backup.create_bundle(source, quiescent_probe=lambda: True)

    forged = tmp_path / "forged.zip"

    def add_directories(bundle: dict) -> None:
        bundle["directories"].extend(
            {"archive_prefix": prefix, "status": "PRESENT"}
            for prefix in directory_prefixes
        )

    _forge_bundle_manifest(source, forged, add_directories)
    assert backup.verify_bundle(forged)["status"] == "FAILED"
    target = tmp_path / "target"
    with pytest.raises(local_snapshot.RestoreRefused):
        backup.restore_bundle(forged, target)
    assert not target.exists()

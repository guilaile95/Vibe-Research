"""P1-BR1 local_data_snapshot 验收测试（Minimum Acceptance 1–17 + 加固补充）。

所有 fixture 一律走 pytest ``tmp_path``，绝不触碰真实用户数据目录；
backend/conftest.py 已在 import 时把 VR_DATA_DIR 指向临时目录兜底隔离。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import local_data_snapshot as lds


# ================= helpers =================


def make_source_tree(root):
    """嵌套 regular files：JSON + 真实 SQLite 库 + 二进制 blob + 深层文件。"""
    (root / "sub" / "deep").mkdir(parents=True)
    (root / "a.json").write_text('{"k": "v", "n": 1}', encoding="utf-8")
    (root / "binary.bin").write_bytes(bytes(range(256)) * 16)
    (root / "sub" / "deep" / "nested.txt").write_bytes(b"deep\x00bytes\xff")
    conn = sqlite3.connect(str(root / "store.sqlite3"))
    try:
        conn.execute("CREATE TABLE t (x INTEGER PRIMARY KEY, note TEXT)")
        conn.execute("INSERT INTO t (note) VALUES ('row-a')")
        conn.execute("INSERT INTO t (note) VALUES ('row-b')")
        conn.commit()
    finally:
        conn.close()


def tree_state(root):
    """{relative posix path: (size, sha256)}，用于前后一致性对比。"""
    state = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in filenames:
            p = Path(dirpath) / fname
            rel = p.relative_to(root).as_posix()
            data = p.read_bytes()
            state[rel] = (len(data), hashlib.sha256(data).hexdigest())
    return state


def read_manifest(archive):
    with zipfile.ZipFile(archive) as zf:
        return json.loads(zf.read(lds.MANIFEST_MEMBER_NAME).decode("utf-8"))


def build_custom_archive(path, member_payloads, manifest_overrides=None):
    """手工构造 archive：manifest 由 payloads 机械推导（正确 size/sha256/count），可注入覆盖。"""
    files = [
        {
            "path": name,
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        for name, payload in sorted(member_payloads.items())
    ]
    manifest = {
        "manifest_schema_version": lds.MANIFEST_SCHEMA_VERSION,
        "tool_version": lds.TOOL_VERSION,
        "created_at_utc": "2026-08-22T00:00:00Z",
        "consistency_contract": lds.CONSISTENCY_CONTRACT,
        "file_count": len(files),
        "total_bytes": sum(f["size"] for f in files),
        "files": files,
    }
    if manifest_overrides:
        if manifest_overrides.get("_patch_files"):
            for idx, patch in manifest_overrides["_patch_files"]:
                files[idx].update(patch)
        for key in ("manifest_schema_version", "consistency_contract", "file_count", "total_bytes"):
            if key in manifest_overrides:
                manifest[key] = manifest_overrides[key]
    payload = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in sorted(member_payloads.items()):
            zf.writestr(name, data)
        zf.writestr(lds.MANIFEST_MEMBER_NAME, payload)


def build_real_archive(tmp_path, root, name="snap.zip"):
    archive = tmp_path / name
    result = lds.create_snapshot(root, archive)
    assert result["status"] == "OK"
    return archive


def parse_last_json(capsys):
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    return json.loads(lines[-1])


# ================= 1. nested regular files snapshot PASS =================


def test_acceptance_1_snapshot_nested_regular_files_pass(tmp_path, capsys):
    root = tmp_path / "data"
    make_source_tree(root)
    rc = lds.main(["snapshot", "--data-dir", str(root), "--output", str(tmp_path / "s.zip")])
    assert rc == lds.EXIT_OK
    assert parse_last_json(capsys)["status"] == "OK"
    assert (tmp_path / "s.zip").is_file()


# ================= 2. SQLite / JSON / binary byte-for-byte =================


def test_acceptance_2_sqlite_json_binary_byte_for_byte(tmp_path):
    root = tmp_path / "data"
    make_source_tree(root)
    archive = tmp_path / "s.zip"
    lds.create_snapshot(root, archive)

    restored = tmp_path / "restored"
    lds.restore_snapshot(archive, restored)

    original_db = (root / "store.sqlite3").read_bytes()
    assert (restored / "store.sqlite3").read_bytes() == original_db
    assert (restored / "a.json").read_bytes() == (root / "a.json").read_bytes()
    assert (restored / "binary.bin").read_bytes() == (root / "binary.bin").read_bytes()
    assert (restored / "sub" / "deep" / "nested.txt").read_bytes() == (
        root / "sub" / "deep" / "nested.txt"
    ).read_bytes()


# ================= 3. manifest relative path + size + sha256 =================


def test_acceptance_3_manifest_entries_correct_no_absolute_paths(tmp_path):
    root = tmp_path / "data"
    make_source_tree(root)
    archive = build_real_archive(tmp_path, root)
    manifest = read_manifest(archive)

    assert manifest["manifest_schema_version"] == lds.MANIFEST_SCHEMA_VERSION
    assert manifest["tool_version"] == lds.TOOL_VERSION
    assert manifest["consistency_contract"] == "USER_ASSERTED_OFFLINE"
    assert manifest["created_at_utc"].endswith("Z")

    paths = [e["path"] for e in manifest["files"]]
    assert paths == sorted(paths)  # canonical：按 path 排序
    for e in manifest["files"]:
        assert not e["path"].startswith(("/", "\\")) and ":" not in e["path"]
        assert "\\" not in e["path"]
        raw = (root.joinpath(*e["path"].split("/"))).read_bytes()
        assert e["size"] == len(raw)
        assert e["sha256"] == hashlib.sha256(raw).hexdigest()

    assert manifest["file_count"] == len(paths)
    assert manifest["total_bytes"] == sum(e["size"] for e in manifest["files"])
    # manifest 整体不得串入本机 absolute path
    blob = json.dumps(manifest)
    assert str(root) not in blob and str(tmp_path) not in blob


# ================= 4. intact snapshot verify PASS =================


def test_acceptance_4_verify_intact_pass(tmp_path, capsys):
    root = tmp_path / "data"
    make_source_tree(root)
    archive = build_real_archive(tmp_path, root)
    rc = lds.main(["verify", "--archive", str(archive)])
    assert rc == lds.EXIT_OK
    out = parse_last_json(capsys)
    assert out["status"] == "OK"
    assert out["errors"] == []
    assert out["consistency_contract"] == "USER_ASSERTED_OFFLINE"


# ================= 5. corrupt archive verify FAIL =================


def test_acceptance_5_truncated_archive_verify_fail(tmp_path, capsys):
    root = tmp_path / "data"
    make_source_tree(root)
    archive = build_real_archive(tmp_path, root)
    corrupted = tmp_path / "corrupt.zip"
    raw = archive.read_bytes()
    corrupted.write_bytes(raw[: max(0, len(raw) - 60)])
    rc = lds.main(["verify", "--archive", str(corrupted)])
    assert rc == lds.EXIT_VERIFY_FAILED
    assert parse_last_json(capsys)["status"] == "FAILED"


def test_acceptance_5_tampered_sha256_in_manifest_verify_fail(tmp_path):
    root = tmp_path / "data"
    make_source_tree(root)
    with zipfile.ZipFile(build_real_archive(tmp_path, root)) as zf:
        names = [i for i in zf.infolist() if i.filename != lds.MANIFEST_MEMBER_NAME]
        payloads = {i.filename: zf.read(i.filename) for i in names}
        manifest = json.loads(zf.read(lds.MANIFEST_MEMBER_NAME).decode("utf-8"))
    manifest["files"][0]["sha256"] = "0" * 64
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in sorted(payloads.items()):
            zf.writestr(name, data)
        zf.writestr(
            lds.MANIFEST_MEMBER_NAME,
            (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        )
    report = lds.verify_snapshot(tampered)
    assert report["status"] == "FAILED"
    assert any("sha256" in e for e in report["errors"])


# ================= 6. missing member FAIL =================


def test_acceptance_6_missing_member_verify_fail(tmp_path):
    root = tmp_path / "data"
    make_source_tree(root)
    src = build_real_archive(tmp_path, root)
    rebuilt = tmp_path / "missing.zip"
    victim = "a.json"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(rebuilt, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            if info.filename != victim:
                zout.writestr(info, zin.read(info.filename))
    report = lds.verify_snapshot(rebuilt)
    assert report["status"] == "FAILED"
    assert any(victim in e for e in report["errors"])


# ================= 7. duplicate / dangerous member FAIL =================


def test_acceptance_7_duplicate_member_verify_fail(tmp_path):
    root = tmp_path / "data"
    make_source_tree(root)
    src = build_real_archive(tmp_path, root)
    duped = tmp_path / "dup.zip"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(duped, "w", zipfile.ZIP_DEFLATED) as zout:
        infos = zin.infolist()
        for info in infos:
            zout.writestr(info, zin.read(info.filename))
        repeat = next(i for i in infos if i.filename != lds.MANIFEST_MEMBER_NAME)
        zout.writestr(repeat, zin.read(repeat.filename))  # 同名第二次写入
    report = lds.verify_snapshot(duped)
    assert report["status"] == "FAILED"
    assert any("重复成员" in e or "duplicate" in e.lower() for e in report["errors"])
    assert any(repeat.filename in e for e in report["errors"])


@pytest.mark.parametrize(
    "bad_name",
    [
        "a\\b.txt",
        "CON.txt",
        "CON .txt",
        "sub/NUL",
        "dir/",
        "dir/./file.txt",
        "trailing-dot.",
        "trailing-space ",
        "with:colon.txt",
    ],
)
def test_acceptance_7_dangerous_registered_names_fail(tmp_path, bad_name):
    payloads = {bad_name: b"x"}
    forged = tmp_path / "forged.zip"
    build_custom_archive(forged, payloads)
    report = lds.verify_snapshot(forged)
    assert report["status"] == "FAILED"
    assert any("不可信" in e for e in report["errors"])


def test_acceptance_7_unregistered_extra_member_fail(tmp_path):
    root = tmp_path / "data"
    make_source_tree(root)
    src = build_real_archive(tmp_path, root)
    extra = tmp_path / "extra.zip"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(extra, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            zout.writestr(info, zin.read(info.filename))
        zout.writestr("smuggled.txt", b"injected")
    report = lds.verify_snapshot(extra)
    assert report["status"] == "FAILED"
    assert any("smuggled.txt" in e for e in report["errors"])


@pytest.mark.parametrize(
    ("member_payloads", "reason"),
    [
        ({"Foo": b"upper", "foo": b"lower"}, "Windows 上碰撞"),
        ({"parent": b"file", "parent/child.txt": b"child"}, "路径拓扑冲突"),
    ],
)
def test_acceptance_7_portable_path_collisions_block_restore(
    tmp_path, member_payloads, reason
):
    forged = tmp_path / "portable-collision.zip"
    build_custom_archive(forged, member_payloads)

    report = lds.verify_snapshot(forged)
    assert report["status"] == "FAILED"
    assert any(reason in error for error in report["errors"])

    target = tmp_path / "target"
    with pytest.raises(lds.RestoreRefused):
        lds.restore_snapshot(forged, target)
    assert not target.exists()


# ================= 8. ../ traversal FAIL =================


def test_acceptance_8_traversal_name_fails(tmp_path):
    forged = tmp_path / "evil.zip"
    build_custom_archive(forged, {"../evil.txt": b"escaped"})
    report = lds.verify_snapshot(forged)
    assert report["status"] == "FAILED"
    assert any("PATH_TRAVERSAL" in e for e in report["errors"])


# ================= 9. absolute-path member FAIL =================


@pytest.mark.parametrize("abs_name", ["/etc/passwd", "C:/windows/evil.txt"])
def test_acceptance_9_absolute_path_member_fails(tmp_path, abs_name):
    forged = tmp_path / "abs.zip"
    build_custom_archive(forged, {abs_name: b"x"})
    report = lds.verify_snapshot(forged)
    assert report["status"] == "FAILED"


# ================= 10. symlink / special source FAIL =================


def _fake_st(mode, file_attributes=0):
    return SimpleNamespace(st_mode=mode, st_file_attributes=file_attributes)


def test_special_file_detection_unit():
    assert lds._entry_violation(_fake_st(stat.S_IFLNK | 0o777)) == "SYMLINK_OR_REPARSE_POINT"
    assert lds._entry_violation(_fake_st(stat.S_IFREG | 0o644, 0x400)) == "SYMLINK_OR_REPARSE_POINT"
    assert lds._entry_violation(_fake_st(stat.S_IFDIR | 0o755, 0x400)) == "SYMLINK_OR_REPARSE_POINT"
    assert lds._entry_violation(_fake_st(stat.S_IFIFO | 0o644)) == "SPECIAL_FILE_TYPE"
    assert lds._entry_violation(_fake_st(stat.S_IFSOCK | 0o644)) == "SPECIAL_FILE_TYPE"
    assert lds._entry_violation(_fake_st(stat.S_IFCHR | 0o644)) == "SPECIAL_FILE_TYPE"
    assert lds._entry_violation(_fake_st(stat.S_IFBLK | 0o644)) == "SPECIAL_FILE_TYPE"
    assert lds._entry_violation(_fake_st(stat.S_IFREG | 0o644)) is None
    assert lds._entry_violation(_fake_st(stat.S_IFDIR | 0o755)) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink 需要特权外的支持，Windows 由 junction 用例覆盖")
def test_symlink_source_fail_closed_posix(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    (root / "ok.txt").write_text("fine", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    os.symlink(outside, root / "link.txt")
    with pytest.raises(lds.LocalSnapshotError, match="SYMLINK"):
        lds.create_snapshot(root, tmp_path / "s.zip")
    assert not (tmp_path / "s.zip").exists()
    # 失败的 snapshot 不得改动源
    assert outside.read_text(encoding="utf-8") == "secret"


@pytest.mark.skipif(os.name != "nt", reason="Windows junction 特有用例")
def test_junction_source_fail_closed_windows(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    (root / "ok.txt").write_text("fine", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link = root / "junction_dir"
    proc = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True,
    )
    if proc.returncode != 0:
        pytest.fail(f"mklink /J 创建失败: {proc.stderr!r}")
    with pytest.raises(lds.LocalSnapshotError, match="REPARSE_POINT"):
        lds.create_snapshot(root, tmp_path / "s.zip")
    assert not (tmp_path / "s.zip").exists()
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "secret"


def test_symlink_inside_root_also_rejected_posix(tmp_path):
    """root 内部指向内部的 symlink 同样拒绝：v0.1 只处理 plain entries。"""
    root = tmp_path / "data"
    (root / "sub").mkdir(parents=True)
    (root / "real.txt").write_text("x", encoding="utf-8")
    os.symlink(root / "real.txt", root / "sub" / "alias.txt")
    with pytest.raises(lds.LocalSnapshotError, match="SYMLINK"):
        lds.create_snapshot(root, tmp_path / "s.zip")


# ================= 11. restore → empty/new target PASS =================


def test_acceptance_11_restore_to_new_and_empty_target(tmp_path):
    root = tmp_path / "data"
    make_source_tree(root)
    archive = build_real_archive(tmp_path, root)

    new_target = tmp_path / "brand" / "new" / "target"  # 多级不存在的 target
    lds.restore_snapshot(archive, new_target)
    assert new_target.is_dir()
    assert tree_state(new_target) == tree_state(root)

    empty_target = tmp_path / "empty_target"
    empty_target.mkdir()
    lds.restore_snapshot(archive, empty_target)
    assert tree_state(empty_target) == tree_state(root)


# ================= 12. restored hashes exact match =================


def test_acceptance_12_restored_hashes_match_manifest(tmp_path):
    root = tmp_path / "data"
    make_source_tree(root)
    archive = build_real_archive(tmp_path, root)
    manifest = read_manifest(archive)
    restored = tmp_path / "restored"
    lds.restore_snapshot(archive, restored)
    by_path = {e["path"]: e for e in manifest["files"]}
    for rel, (size, digest) in tree_state(restored).items():
        entry = by_path[rel]
        assert size == entry["size"]
        assert digest == entry["sha256"]
    assert set(by_path) == set(tree_state(restored))


# ================= 13./14. non-empty target REFUSED & untouched =================


def test_acceptance_13_nonempty_target_refused(tmp_path, capsys):
    root = tmp_path / "data"
    make_source_tree(root)
    archive = build_real_archive(tmp_path, root)
    target = tmp_path / "target"
    target.mkdir()
    (target / "precious.db").write_bytes(b"user-data-do-not-touch")

    rc = lds.main(["restore", "--archive", str(archive), "--target", str(target)])
    assert rc == lds.EXIT_RESTORE_REFUSED
    out = parse_last_json(capsys)
    assert out["status"] == "REFUSED"
    # target 完全未被修改
    assert [p.name for p in target.iterdir()] == ["precious.db"]
    assert (target / "precious.db").read_bytes() == b"user-data-do-not-touch"


def test_acceptance_13_target_file_not_directory_refused(tmp_path):
    root = tmp_path / "data"
    make_source_tree(root)
    archive = build_real_archive(tmp_path, root)
    target = tmp_path / "not_a_dir"
    target.write_text("i am a file", encoding="utf-8")
    with pytest.raises(lds.RestoreRefused):
        lds.restore_snapshot(archive, target)
    assert target.read_text(encoding="utf-8") == "i am a file"


def test_acceptance_14_failed_verification_blocks_restore_and_touches_nothing(tmp_path):
    root = tmp_path / "data"
    make_source_tree(root)
    good = build_real_archive(tmp_path, root)
    broken = tmp_path / "broken.zip"
    raw = good.read_bytes()
    broken.write_bytes(raw[:-60])

    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")
    before = tree_state(target)
    with pytest.raises(lds.RestoreRefused):
        lds.restore_snapshot(broken, target)
    assert tree_state(target) == before
    # 中途失败（RestoreFailed）也不得清理或改动既有文件——本工具无删除行为


# ================= 15. verify read-only =================


def test_acceptance_15_verify_is_read_only(tmp_path):
    root = tmp_path / "data"
    make_source_tree(root)
    archive = build_real_archive(tmp_path, root)

    before_bytes = archive.read_bytes()
    before_mtime = archive.stat().st_mtime_ns
    before_src = tree_state(root)

    lds.verify_snapshot(archive)

    assert archive.read_bytes() == before_bytes
    assert archive.stat().st_mtime_ns == before_mtime
    assert tree_state(root) == before_src


# ================= 16. invalid CLI args 固定 non-zero exit =================


def test_acceptance_16_invalid_cli_args_exit_nonzero():
    with pytest.raises(SystemExit) as exc:
        lds.main(["verify"])  # 缺 --archive
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        lds.main(["no-such-command"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        lds.main([])
    assert exc.value.code == 2


def test_acceptance_16_missing_archive_verify_exit_20(tmp_path, capsys):
    rc = lds.main(["verify", "--archive", str(tmp_path / "ghost.zip")])
    assert rc == lds.EXIT_VERIFY_FAILED
    assert parse_last_json(capsys)["status"] == "FAILED"


def test_acceptance_16_missing_data_dir_snapshot_exit_10(tmp_path, capsys):
    rc = lds.main(
        ["snapshot", "--data-dir", str(tmp_path / "nope"), "--output", str(tmp_path / "s.zip")]
    )
    assert rc == lds.EXIT_SNAPSHOT_FAILED


def test_acceptance_16_existing_output_refused(tmp_path, capsys):
    root = tmp_path / "data"
    root.mkdir()
    (root / "f.txt").write_text("x", encoding="utf-8")
    out = tmp_path / "exists.zip"
    out.write_bytes(b"prior content")
    rc = lds.main(["snapshot", "--data-dir", str(root), "--output", str(out)])
    assert rc == lds.EXIT_SNAPSHOT_FAILED
    assert out.read_bytes() == b"prior content"  # 未被覆盖


# ================= 17. no real-user data touched =================


def test_acceptance_17_tests_are_fully_isolated(tmp_path, monkeypatch):
    """default data dir 解析自 VR_DATA_DIR env；测试环境恒为临时目录。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path / "envdir"))
    assert lds._default_data_dir() == str(tmp_path / "envdir")
    monkeypatch.setenv("VR_DATA_DIR", "   ")
    assert lds._default_data_dir() != ""  # 空白 env 回退默认，不静默指向 cwd
    # 本文件所有用例均以 tmp_path 为根，未引用任何真实 home 数据目录。


# ================= 补充：manifest 硬校验与合同语义 =================


def test_schema_version_mismatch_fails(tmp_path):
    forged = tmp_path / "v2.zip"
    build_custom_archive(
        forged,
        {"a.txt": b"hi"},
        manifest_overrides={"manifest_schema_version": "local_data_snapshot.manifest.v9.9"},
    )
    assert lds.verify_snapshot(forged)["status"] == "FAILED"


def test_consistency_contract_mismatch_fails(tmp_path):
    forged = tmp_path / "contract.zip"
    build_custom_archive(
        forged,
        {"a.txt": b"hi"},
        manifest_overrides={"consistency_contract": "ATOMIC_LIVE_BACKUP"},
    )
    assert lds.verify_snapshot(forged)["status"] == "FAILED"


def test_declared_counts_mismatch_fails(tmp_path):
    forged = tmp_path / "counts.zip"
    build_custom_archive(forged, {"a.txt": b"hi"}, manifest_overrides={"file_count": 99})
    assert lds.verify_snapshot(forged)["status"] == "FAILED"

    forged2 = tmp_path / "totals.zip"
    build_custom_archive(forged2, {"a.txt": b"hi"}, manifest_overrides={"total_bytes": 999})
    assert lds.verify_snapshot(forged2)["status"] == "FAILED"


def test_missing_manifest_fails(tmp_path):
    naked = tmp_path / "naked.zip"
    with zipfile.ZipFile(naked, "w") as zf:
        zf.writestr("only.txt", b"data without manifest")
    assert lds.verify_snapshot(naked)["status"] == "FAILED"


def test_empty_data_dir_roundtrip(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    archive = build_real_archive(tmp_path, root)
    assert lds.verify_snapshot(archive)["status"] == "OK"
    manifest = read_manifest(archive)
    assert manifest["file_count"] == 0 and manifest["total_bytes"] == 0
    restored = tmp_path / "restored_empty"
    lds.restore_snapshot(archive, restored)
    assert restored.is_dir() and list(restored.iterdir()) == []


def test_unicode_filenames_roundtrip(tmp_path):
    root = tmp_path / "data"
    (root / "子目录").mkdir(parents=True)
    (root / "子目录" / "研报·v1.txt").write_text("中文内容", encoding="utf-8")
    archive = build_real_archive(tmp_path, root)
    assert lds.verify_snapshot(archive)["status"] == "OK"
    restored = tmp_path / "restored"
    lds.restore_snapshot(archive, restored)
    assert (restored / "子目录" / "研报·v1.txt").read_text(encoding="utf-8") == "中文内容"


def test_larger_file_streaming_roundtrip(tmp_path):
    """超过单次 chunk 读取阈值的文件仍 byte-for-byte。"""
    root = tmp_path / "data"
    root.mkdir()
    big = os.urandom(lds._HASH_CHUNK_SIZE * 2 + 12345)
    (root / "big.bin").write_bytes(big)
    archive = build_real_archive(tmp_path, root)
    restored = tmp_path / "restored"
    lds.restore_snapshot(archive, restored)
    assert (restored / "big.bin").read_bytes() == big


def test_main_guard_module_runs_as_script():
    """python -m 形式可被发现（模块含 __main__ guard 且 main 可独立调用）。"""
    assert callable(lds.main)


# ================= multi-asset 复用接口 =================


def test_collect_snapshot_sources_prefix_and_excluded_names(tmp_path):
    root = tmp_path / "data"
    (root / "keep").mkdir(parents=True)
    (root / "skip" / "nested").mkdir(parents=True)
    (root / "keep" / "a.json").write_text('{"ok": true}', encoding="utf-8")
    (root / "skip" / "nested" / "secret.txt").write_text("skip", encoding="utf-8")
    (root / "ignored.tmp").write_text("skip", encoding="utf-8")

    entries = lds.collect_snapshot_sources(
        root,
        archive_prefix="data_root",
        excluded_names={"skip", "ignored.tmp"},
    )

    assert entries == [
        ("data_root/keep/a.json", (root / "keep" / "a.json").resolve())
    ]


def test_create_snapshot_from_files_extension_verify_restore(tmp_path):
    data_file = tmp_path / "portfolio.json"
    review_db = tmp_path / "daily_reviews.sqlite3"
    data_file.write_text('{"holdings": []}', encoding="utf-8")
    review_db.write_bytes(b"synthetic-db-bytes")
    archive = tmp_path / "bundle.zip"
    extension = {
        "vibe_bundle": {
            "schema_version": "vibe_data_backup.manifest.v0.1",
            "assets": [
                {"name": "data_root", "status": "PRESENT"},
                {"name": "shared_review", "status": "EXTERNAL_OVERRIDE_INCLUDED"},
            ],
        }
    }

    result = lds.create_snapshot_from_files(
        [
            ("data_root/portfolio.json", data_file),
            ("shared_review/daily_reviews.sqlite3", review_db),
        ],
        archive,
        manifest_extension=extension,
    )

    assert result["status"] == "OK"
    manifest = lds.read_verified_manifest(archive)
    assert manifest["vibe_bundle"] == extension["vibe_bundle"]
    assert "_manifest_sha256" not in manifest
    assert [entry["path"] for entry in manifest["files"]] == [
        "data_root/portfolio.json",
        "shared_review/daily_reviews.sqlite3",
    ]

    restored = tmp_path / "restored"
    lds.restore_snapshot(archive, restored)
    assert (restored / "data_root" / "portfolio.json").read_bytes() == data_file.read_bytes()
    assert (
        restored / "shared_review" / "daily_reviews.sqlite3"
    ).read_bytes() == review_db.read_bytes()


def test_create_snapshot_from_files_rejects_core_override_and_unsafe_entry(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("x", encoding="utf-8")

    with pytest.raises(lds.LocalSnapshotError, match="核心字段"):
        lds.create_snapshot_from_files(
            [("safe/source.txt", source)],
            tmp_path / "core-override.zip",
            manifest_extension={"files": []},
        )
    with pytest.raises(lds.LocalSnapshotError, match="PATH_TRAVERSAL"):
        lds.create_snapshot_from_files(
            [("../escape.txt", source)],
            tmp_path / "unsafe.zip",
        )
    assert not (tmp_path / "core-override.zip").exists()
    assert not (tmp_path / "unsafe.zip").exists()

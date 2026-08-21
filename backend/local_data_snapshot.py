"""P1-BR1 本地数据快照与恢复演练 CLI（离线 / quiesced snapshot，v0.1）。

用法：

    python -m local_data_snapshot snapshot --data-dir DIR --output ARCHIVE.zip
    python -m local_data_snapshot verify   --archive ARCHIVE.zip
    python -m local_data_snapshot restore  --archive ARCHIVE.zip --target DIR

定位：在未来真实持仓 / 交易使用前，为本机 Vibe data directory 提供
可验证的恢复路径。数据一律当作 opaque bytes——本工具不理解也不迁移
portfolio.json / Trade Ledger / Account Events / Thesis / Evidence /
Frozen Decision / Security config / DB schema 等任何业务语义。

一致性合同（诚实边界）：

- v0.1 是 OFFLINE / QUIESCED SNAPSHOT。程序无法证明 Vibe 服务已停止，
  因此 manifest 恒记 ``CONSISTENCY = USER_ASSERTED_OFFLINE``；
  不声称 atomic live backup、多库事务快照或 point-in-time consistency。
- 本 Slice 不做 process lock / daemon coordination / online backup。

安全契约：

- 快照仅收录 regular files；symlink / junction / 其他 reparse point /
  FIFO / socket / device 一律 fail closed，绝不跟随逃逸出 data root。
- manifest 只含 relative path / size / SHA-256 / 计数 / 合同版本，
  不写入用户机器 absolute path。
- verify 为只读：不改 archive、不改 source、不改真实 VR_DATA_DIR；
  任何不可信 archive 结构（绝对路径、``..`` 穿越、反斜杠成员名、
  Windows 保留设备名、重复成员、缺失成员、损坏成员、未登记成员、
  schema 版本不符）全部 fail closed。
- restore 只允许写入用户显式指定的 target：target 不存在或为空目录
  才能执行；非空 REFUSE，绝不删除 / 覆盖 / 清空已有数据；
  restore 前必须先完整通过 integrity verification；
  失败的 restore 不修改 target 已有数据（部分写入的新文件如实报告，
  不做自动清理——本工具不做任何删除行为）。

exit code：0 成功；2 参数错误；10 快照失败；20 verify 失败；
30 restore 拒绝（target 非空 / archive 未通过验证等策略性拒绝）；
31 restore 执行失败；15 其他内部错误。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_SNAPSHOT_FAILED = 10
EXIT_VERIFY_FAILED = 20
EXIT_RESTORE_REFUSED = 30
EXIT_RESTORE_FAILED = 31
EXIT_ERROR = 15

# manifest 在 archive 内的固定成员名与 schema 版本（verify 严格匹配，不猜测兼容）。
MANIFEST_MEMBER_NAME = "vibe-research-snapshot-manifest-v0.1.json"
MANIFEST_SCHEMA_VERSION = "local_data_snapshot.manifest.v0.1"
TOOL_VERSION = "p1-br1.v0.1"
CONSISTENCY_CONTRACT = "USER_ASSERTED_OFFLINE"

_HASH_CHUNK_SIZE = 1024 * 1024

# Windows 保留设备名（不分扩展名）；restore 目标可能在 Windows，命中即拒。
_WINDOWS_RESERVED_STEMS = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400  # os.stat_result.st_file_attributes（Windows only）


class LocalSnapshotError(RuntimeError):
    """快照工具失败基类；message 面向本机操作者。"""


class VerifyError(LocalSnapshotError):
    """archive 未通过完整性 / 结构验证（fail closed）。"""


class RestoreRefused(LocalSnapshotError):
    """策略性拒绝：target 非空 / 不是目录 / archive 未通过前置验证等。"""


class RestoreFailed(LocalSnapshotError):
    """restore 已获准执行但中途失败；不自动清理，如实报告。"""


def _is_reparse_point(st: os.stat_result) -> bool:
    """Windows junction 与 symlink 都是 reparse point；POSIX 恒 False。

    Python 3.11 的 pathlib/os.path.islink 不识别 junction，必须查
    FILE_ATTRIBUTE_REPARSE_POINT，否则 directory junction 会被 os.walk
    当普通目录跟进，造成快照越出 data root。
    """
    return bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _entry_violation(st: os.stat_result) -> str | None:
    """lstat 结果不是 plain regular file / plain directory 时返回违规定性，否则 None。"""
    if stat.S_ISLNK(st.st_mode) or _is_reparse_point(st):
        return "SYMLINK_OR_REPARSE_POINT"
    if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
        return "SPECIAL_FILE_TYPE"
    return None


# snapshot 收集期间的 data root（用于错误信息里的相对化展示，不进 manifest）。
_current_root: list[Path] = [Path(".")]


def _assert_plain_entry(path: Path, expect: str) -> None:
    try:
        st = os.lstat(path)
    except OSError as e:
        raise LocalSnapshotError(f"无法读取条目状态: {e}") from e
    violation = _entry_violation(st)
    if violation is not None:
        raise LocalSnapshotError(
            f"data root 内出现不允许的{expect}类型（{violation}）: "
            f"{path.relative_to(_current_root[0]).as_posix()}；fail closed"
        )


# ================= SHA-256 =================


def _sha256_of_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
    return total, digest.hexdigest()


def _sha256_of_stream(stream) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = stream.read(_HASH_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        digest.update(chunk)
    return total, digest.hexdigest()


# ================= 成员名校验（防 zip slip / 不可信结构） =================


def _member_name_violation(name: str) -> str | None:
    """archive 成员名不安全时返回定性，否则 None。成员名一律视为不可信输入。"""
    if not name or "\x00" in name:
        return "EMPTY_OR_NULL_BYTE"
    if "\\" in name:
        return "BACKSLASH_IN_NAME"
    if ":" in name:
        return "COLON_IN_NAME"  # 盘符（C:/x）等；合法 relative posix 名不含冒号
    if name.startswith("/"):
        return "ABSOLUTE_PATH"
    if name.endswith("/"):
        return "DIRECTORY_ENTRY"  # v0.1 archive 不写目录条目
    parts = name.split("/")
    if any(p == ".." for p in parts):
        return "PATH_TRAVERSAL"
    if any(p == "" for p in parts):
        return "EMPTY_PATH_SEGMENT"
    if any(p.split(".")[0].upper() in _WINDOWS_RESERVED_STEMS for p in parts):
        return "WINDOWS_RESERVED_NAME"
    return None


def _validate_manifest_payload_shape(manifest: dict) -> list[str]:
    """schema/字段/类型逐项硬校验；返回错误列表（可为空）。"""
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest 根必须是 JSON object"]
    if manifest.get("manifest_schema_version") != MANIFEST_SCHEMA_VERSION:
        errors.append(
            f"manifest_schema_version 不受支持: {manifest.get('manifest_schema_version')!r}"
        )
    if manifest.get("consistency_contract") != CONSISTENCY_CONTRACT:
        errors.append(
            f"consistency_contract 不符: {manifest.get('consistency_contract')!r}"
        )
    if not isinstance(manifest.get("created_at_utc"), str):
        errors.append("created_at_utc 缺失或类型错误")
    if not isinstance(manifest.get("tool_version"), str):
        errors.append("tool_version 缺失或类型错误")
    files = manifest.get("files")
    if not isinstance(files, list):
        errors.append("files 缺失或类型错误")
        return errors
    seen_paths: set[str] = set()
    total = 0
    for i, entry in enumerate(files):
        if not isinstance(entry, dict):
            errors.append(f"files[{i}] 不是 object")
            continue
        p = entry.get("path")
        if not isinstance(p, str):
            errors.append(f"files[{i}].path 缺失或类型错误")
            continue
        violation = _member_name_violation(p)
        if violation is not None:
            errors.append(f"files[{i}].path 不可信（{violation}）: {p!r}")
            continue
        if p in seen_paths:
            errors.append(f"files 中重复 path: {p!r}")
        seen_paths.add(p)
        size = entry.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            errors.append(f"files[{i}].size 缺失或非法")
        else:
            total += size
        sha = entry.get("sha256")
        if (
            not isinstance(sha, str)
            or len(sha) != 64
            or any(c not in "0123456789abcdef" for c in sha)
        ):
            errors.append(f"files[{i}].sha256 缺失或格式非法: {p!r}")
    declared_count = manifest.get("file_count")
    if declared_count != len(files):
        errors.append(f"file_count 不符: 声明 {declared_count!r} 实际 {len(files)}")
    declared_total = manifest.get("total_bytes")
    if declared_total != total:
        errors.append(f"total_bytes 不符: 声明 {declared_total!r} 实际 {total}")
    return errors


# ================= snapshot =================


def create_snapshot(data_dir, output_archive) -> dict:
    """把 data root 下的 regular files 打包成带 canonical manifest 的 zip。

    输出 archive 已存在则拒绝（不覆盖）。写入走同目录临时文件 +
    rename，避免半成品冒充成品。
    """
    root = Path(data_dir)
    if not root.is_dir():
        raise LocalSnapshotError(f"data dir 不存在或不是目录: {root.name}")
    resolved_root = root.resolve()
    _current_root[0] = resolved_root

    output = Path(output_archive)
    if output.exists() or output.is_symlink():
        raise LocalSnapshotError(f"输出 archive 已存在，拒绝覆盖: {output.name}")
    if not output.parent.is_dir():
        raise LocalSnapshotError(f"输出目录不存在: {output.parent.name}")

    # 收集阶段：逐条目 lstat，任何 symlink / junction / special file 都 fail closed。
    collected: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(resolved_root, followlinks=False):
        here = Path(dirpath)
        for dname in sorted(dirnames):
            _assert_plain_entry(here / dname, "目录")
        for fname in sorted(filenames):
            child = here / fname
            _assert_plain_entry(child, "文件")
            size, digest = _sha256_of_file(child)
            collected.append(
                {
                    "path": child.relative_to(resolved_root).as_posix(),
                    "size": size,
                    "sha256": digest,
                }
            )
    collected.sort(key=lambda e: e["path"])

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "consistency_contract": CONSISTENCY_CONTRACT,
        "file_count": len(collected),
        "total_bytes": sum(e["size"] for e in collected),
        "files": collected,
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")

    fd, tmp_name = tempfile.mkstemp(
        dir=str(output.parent), prefix=output.name + ".", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as raw, zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as zf:
            for entry in collected:
                zf.write(resolved_root / entry["path"], arcname=entry["path"])
            zf.writestr(MANIFEST_MEMBER_NAME, manifest_bytes)
        # rename 前复检目标仍不存在（缩小 no-overwrite 的竞态窗口；Windows 上
        # rename 到已存在目标本就失败，POSIX 窗口内的并发创建属用户自担）。
        if output.exists():
            raise LocalSnapshotError(f"输出 archive 已存在，拒绝覆盖: {output.name}")
        os.rename(tmp_path, output)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    return {
        "status": "OK",
        "operation": "snapshot",
        "file_count": manifest["file_count"],
        "total_bytes": manifest["total_bytes"],
        "consistency_contract": CONSISTENCY_CONTRACT,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }


# ================= verify（只读） =================


def verify_snapshot(archive_path) -> dict:
    """只读验证 archive：结构与完整性全部 PASS 才返回 OK，否则错误列表齐全。

    不修改 archive、source 或任何数据目录。
    """
    errors, zf, manifest = _verify_archive(Path(archive_path))
    if zf is not None:
        zf.close()
    if errors:
        return {
            "status": "FAILED",
            "operation": "verify",
            "errors": errors,
        }
    return {
        "status": "OK",
        "operation": "verify",
        "file_count": manifest["file_count"],
        "total_bytes": manifest["total_bytes"],
        "consistency_contract": manifest["consistency_contract"],
        "manifest_sha256": manifest["_manifest_sha256"],
        "errors": [],
    }


def _verify_archive(archive: Path):
    """共享验证核心：返回 (errors, zipfile 句柄或 None, manifest 或 None)。"""
    errors: list[str] = []
    try:
        zf = zipfile.ZipFile(archive, "r")
    except (zipfile.BadZipFile, OSError) as e:
        return [f"archive 无法作为 zip 打开（损坏或缺失）: {type(e).__name__}"], None, None

    try:
        names = zf.namelist()
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            errors.append(f"重复成员: {duplicates!r}")

        manifest_count = names.count(MANIFEST_MEMBER_NAME)
        if manifest_count != 1:
            errors.append(
                f"manifest 成员数量异常: 期望恰好 1 个 {MANIFEST_MEMBER_NAME!r}，实际 {manifest_count}"
            )
            return errors, None, None

        try:
            manifest_raw = zf.read(MANIFEST_MEMBER_NAME)
        except (zipfile.BadZipFile, OSError, RuntimeError) as e:
            errors.append(f"manifest 成员读取失败（损坏）: {type(e).__name__}")
            return errors, None, None
        manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
        try:
            manifest = json.loads(manifest_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            errors.append(f"manifest 不是合法 UTF-8 JSON: {type(e).__name__}")
            return errors, None, None

        shape_errors = _validate_manifest_payload_shape(manifest)
        if shape_errors:
            errors.extend(shape_errors)
            return errors, None, None
        manifest["_manifest_sha256"] = manifest_sha256

        expected_files = {e["path"]: e for e in manifest["files"]}
        actual_names = set(names) - {MANIFEST_MEMBER_NAME}
        missing = sorted(set(expected_files) - actual_names)
        unexpected = sorted(actual_names - set(expected_files))
        if missing:
            errors.append(f"缺失成员: {missing!r}")
        if unexpected:
            errors.append(f"未登记的可疑成员: {unexpected!r}")
        if missing or unexpected:
            return errors, None, None

        for entry in manifest["files"]:
            name = entry["path"]
            try:
                with zf.open(name) as member:
                    size, digest = _sha256_of_stream(member)
            except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as e:
                errors.append(f"成员读取失败（损坏或不支持）: {name!r}: {type(e).__name__}")
                continue
            if size != entry["size"]:
                errors.append(
                    f"size 不符: {name!r} 声明 {entry['size']} 实际 {size}"
                )
            if digest != entry["sha256"]:
                errors.append(f"sha256 不符: {name!r}")
        if errors:
            return errors, None, None
        return [], zf, manifest
    except BaseException:
        zf.close()
        raise


# ================= restore =================


def restore_snapshot(archive_path, target_dir) -> dict:
    """验证后恢复到显式 target；target 必须不存在或为空目录，否则 REFUSE。"""
    archive = Path(archive_path)
    errors, zf, manifest = _verify_archive(archive)
    if errors or zf is None or manifest is None:
        if zf is not None:
            zf.close()
        raise RestoreRefused(
            "archive 未通过完整性验证，restore 拒绝执行；target 未被修改"
            f"（首个原因: {errors[0] if errors else 'unknown'}）"
        )

    target = Path(target_dir)
    try:
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_dir():
                raise RestoreRefused(f"target 已存在且不是目录，拒绝: {target.name}")
            existing = [p.name for p in target.iterdir()]
            if existing:
                raise RestoreRefused(
                    f"target 非空（{len(existing)} 个条目），拒绝 restore；"
                    "本工具绝不删除或覆盖已有数据"
                )
        else:
            target.mkdir(parents=True)

        written: list[tuple[Path, dict]] = []
        for entry in sorted(manifest["files"], key=lambda e: e["path"]):
            dest = target.joinpath(*entry["path"].split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(entry["path"]) as src, open(dest, "wb") as out:
                while True:
                    chunk = src.read(_HASH_CHUNK_SIZE)
                    if not chunk:
                        break
                    out.write(chunk)
            written.append((dest, entry))

        # 恢复后全量重哈希：restored bytes 必须与 manifest 精确一致。
        for dest, entry in written:
            size, digest = _sha256_of_file(dest)
            if size != entry["size"] or digest != entry["sha256"]:
                raise RestoreFailed(
                    f"restore 后校验失败（不清理已写入文件，请人工处理后重试）: "
                    f"{entry['path']!r} 与 manifest 不一致"
                )
    finally:
        zf.close()

    return {
        "status": "OK",
        "operation": "restore",
        "file_count": manifest["file_count"],
        "total_bytes": manifest["total_bytes"],
        "consistency_contract": manifest["consistency_contract"],
    }


# ================= CLI =================


def _default_data_dir() -> str:
    return os.environ.get("VR_DATA_DIR", "").strip() or str(
        Path.home() / ".vibe-research"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="local_data_snapshot",
        description="P1-BR1 本地数据快照 / 验证 / 安全恢复演练（离线 quiesced snapshot）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_snap = sub.add_parser("snapshot", help="打包 data dir 为带 manifest 的 zip")
    p_snap.add_argument("--data-dir", default=_default_data_dir())
    p_snap.add_argument("--output", required=True)

    p_verify = sub.add_parser("verify", help="只读验证既有 archive")
    p_verify.add_argument("--archive", required=True)

    p_restore = sub.add_parser("restore", help="验证后恢复到显式 target（必须为空或不存在）")
    p_restore.add_argument("--archive", required=True)
    p_restore.add_argument("--target", required=True)

    args = parser.parse_args(argv)

    try:
        if args.command == "snapshot":
            result = create_snapshot(args.data_dir, args.output)
            exit_code = EXIT_OK
        elif args.command == "verify":
            result = verify_snapshot(args.archive)
            exit_code = EXIT_OK if result["status"] == "OK" else EXIT_VERIFY_FAILED
        elif args.command == "restore":
            result = restore_snapshot(args.archive, args.target)
            exit_code = EXIT_OK
        else:  # argparse required=True 已拦截，防御性兜底
            parser.error(f"未知子命令: {args.command}")
            return EXIT_USAGE
    except RestoreRefused as e:
        print(json.dumps({"status": "REFUSED", "reason": str(e)}, ensure_ascii=False))
        return EXIT_RESTORE_REFUSED
    except RestoreFailed as e:
        print(json.dumps({"status": "FAILED", "reason": str(e)}, ensure_ascii=False))
        return EXIT_RESTORE_FAILED
    except (VerifyError, LocalSnapshotError) as e:
        print(json.dumps({"status": "FAILED", "reason": str(e)}, ensure_ascii=False))
        return (
            EXIT_VERIFY_FAILED
            if isinstance(e, VerifyError)
            else EXIT_SNAPSHOT_FAILED
        )
    except OSError as e:
        print(
            json.dumps(
                {"status": "FAILED", "reason": f"IO 错误: {type(e).__name__}"},
                ensure_ascii=False,
            )
        )
        return EXIT_ERROR
    print(json.dumps(result, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

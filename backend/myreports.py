"""我的研报 —— 用户上传/归档自己的研报文件，存本地、不上传、不进开源仓库。

设计取舍：
- 走 base64 JSON 上传（不引入 python-multipart 依赖，契合本项目「秒装必可用」）；研报文件不大，够用。
- 存到 `VR_REPORTS_DIR`（默认 ~/.vibe-research/myreports/，也可用 VR_DATA_DIR 换根目录）——用户私有资料，绝不进仓、不上传。
  放仓库外，重新下载/覆盖项目文件夹不会丢（issue #12）；≤v0.1.1 存 backend/.cache/myreports/，首次启动自动迁移（复制，旧目录保留作备份）。
- 元数据存目录内 index.json；按文件名关键词自动打「行业」标签（best-effort，未命中记「未分类」）。

研报是用户私有数据，只落本地磁盘。
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path

_OLD_DEFAULT_DIR = Path(__file__).resolve().parent / ".cache" / "myreports"  # ≤v0.1.1 旧位置
_DATA_DIR = Path(os.environ.get("VR_DATA_DIR") or Path.home() / ".vibe-research")
_DEFAULT_DIR = _DATA_DIR / "myreports"
# 空串视同未设置（与 VR_DATA_DIR 语义一致，避免 Path("") 落到进程工作目录）
REPORTS_DIR = Path(os.environ.get("VR_REPORTS_DIR") or str(_DEFAULT_DIR))


def _migrate_legacy() -> None:
    """旧版研报在仓库内 .cache/ 里，重下载项目会丢；迁到用户目录（显式设了 VR_REPORTS_DIR 或新位置已有则不动）。"""
    try:
        if os.environ.get("VR_REPORTS_DIR") or REPORTS_DIR.exists() or not _OLD_DEFAULT_DIR.exists():
            return
        tmp = REPORTS_DIR.with_name(REPORTS_DIR.name + ".migrate.tmp")
        if tmp.exists():
            shutil.rmtree(tmp)  # 上次中断留下的半截目录，重来
        shutil.copytree(_OLD_DEFAULT_DIR, tmp)
        os.replace(tmp, REPORTS_DIR)  # 同盘原子改名：复制中断不会留半套研报挡住下次重试
    except OSError as e:
        # 迁移失败不阻塞启动，但要出声——旧数据原样保留在 _OLD_DEFAULT_DIR，可手工复制
        print(f"[vibe-research] 研报数据迁移失败（旧数据仍在 {_OLD_DEFAULT_DIR}）: {e}", file=sys.stderr)


_migrate_legacy()
_LOCK = threading.Lock()  # 索引读-改-写串行化（与 portfolio.py 同款），防并发上传/删除互相覆盖

MAX_BYTES = 25 * 1024 * 1024  # 单文件上限 25MB
# 允许的文档类型（白名单——不存可执行 / 网页等，避免下载回放风险）
ALLOWED_EXT = {
    ".pdf", ".doc", ".docx", ".txt", ".md", ".markdown",
    ".csv", ".xls", ".xlsx", ".ppt", ".pptx",
    ".png", ".jpg", ".jpeg", ".webp",
}

# 文件名关键词 → 行业标签（顺序即优先级，先命中先用）。纯文件名匹配、零依赖、离线可用。
_INDUSTRY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("人形机器人", ["人形", "机器人", "humanoid", "谐波", "丝杠", "滚柱", "灵巧手", "减速器", "optimus", "宇树", "特斯拉"]),
    ("光互联", ["光互联", "硅光", "cpo", "光模块", "磷化铟", "inp", "光芯片", "源杰", "中际旭创", "天孚"]),
    ("HBM存储", ["hbm", "存储", "内存", "dram", "长鑫", "美光", "海力士", "颗粒", "闪存", "nand"]),
    ("AI算力", ["算力", "gpu", "英伟达", "nvidia", "服务器", "液冷", "pcb", "交换机", "cowos", "沪电", "工业富联"]),
    ("半导体", ["半导体", "芯片", "晶圆", "光刻", "封测", "台积电", "刻蚀", "存储芯片"]),
    ("新能源", ["锂电", "电池", "光伏", "储能", "固态", "钠电", "宁德", "比亚迪"]),
    ("创新药", ["创新药", "医药", "生物", "cxo", "临床", "adc", "glp", "药明"]),
    ("商业航天", ["航天", "卫星", "火箭", "星链", "starlink", "spacex", "蓝箭"]),
    ("电力电网", ["电力", "电网", "特高压", "变压器", "输配电", "燃气轮机"]),
]


class ReportError(ValueError):
    """上传/校验类错误（对应 HTTP 400/413）。"""


class ReportIndexCorruptedError(RuntimeError):
    """研报索引文件损坏，已停止读写以避免覆盖。"""
    MESSAGE = (
        "本地研报索引文件损坏，已停止读写以避免覆盖；"
        "请检查 index.json，并在有备份时从 index.json.bak 恢复"
    )

    def __init__(self):
        super().__init__(self.MESSAGE)


def _index_path() -> Path:
    return REPORTS_DIR / "index.json"


def _tmp_name(base: str) -> str:
    return f"{base}.tmp.{os.urandom(4).hex()}"


def _validate_index_data(data):
    if not isinstance(data, list):
        raise ReportIndexCorruptedError()
    for entry in data:
        if not isinstance(entry, dict):
            raise ReportIndexCorruptedError()
        rid = entry.get("id")
        if not isinstance(rid, str) or not rid:
            raise ReportIndexCorruptedError()
        ext = entry.get("ext")
        if not isinstance(ext, str):
            raise ReportIndexCorruptedError()
    return data

def _ensure_dir() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> list[dict]:
    ip = _index_path()
    if not ip.exists():
        return []
    try:
        raw = ip.read_bytes()
    except OSError:
        raise
    try:
        text = raw.decode("utf-8")
    except (UnicodeDecodeError, UnicodeError):
        raise ReportIndexCorruptedError() from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ReportIndexCorruptedError() from None
    return _validate_index_data(data)


def _save_index(items: list[dict]) -> None:
    ip = _index_path()
    ip.parent.mkdir(parents=True, exist_ok=True)
    bak_path = ip.with_name(ip.name + ".bak")
    bak_tmp = None
    data_tmp = None
    try:
        if ip.exists():
            try:
                existing_raw = ip.read_bytes()
            except OSError:
                raise
            try:
                existing_text = existing_raw.decode("utf-8")
                existing_data = json.loads(existing_text)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ReportIndexCorruptedError() from None
            _validate_index_data(existing_data)

            bak_tmp = _tmp_name(str(bak_path))
            import shutil
            shutil.copy2(ip, bak_tmp)
            os.replace(bak_tmp, bak_path)
            bak_tmp = None

        data_tmp = _tmp_name(str(ip))
        text = json.dumps(items, ensure_ascii=False, indent=2)
        with open(data_tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(data_tmp, ip)
        data_tmp = None
    finally:
        for tmp in (bak_tmp, data_tmp):
            if tmp is not None and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def classify(filename: str) -> str:
    """按文件名关键词判行业；未命中记「未分类」。"""
    low = filename.lower()
    for industry, kws in _INDUSTRY_KEYWORDS:
        if any(kw.lower() in low for kw in kws):
            return industry
    return "未分类"


def _sanitize_name(name: str) -> str:
    """只保留基名，去掉路径分隔符；空名给个兜底。"""
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    return base or "未命名"


def list_reports() -> list[dict]:
    """按上传时间倒序返回元数据列表。"""
    return sorted(_load_index(), key=lambda r: r.get("ts", 0), reverse=True)


def save_report(name: str, content_b64: str) -> dict:
    """解码 base64 存盘 + 打行业标签 + 记录元数据。返回该条元数据。"""
    fname = _sanitize_name(name)
    ext = os.path.splitext(fname)[1].lower()
    if ext not in ALLOWED_EXT:
        raise ReportError(f"不支持的文件类型 {ext or '（无扩展名）'}；支持：PDF / Word / txt / md / 表格 / 图片")
    # base64 可能带 data:URI 前缀（前端 FileReader.readAsDataURL），剥掉逗号前半段
    if content_b64.startswith("data:"):
        parts = content_b64.split(",", 1)
        if len(parts) < 2:
            raise ReportError("无效的 data URI（缺少逗号分隔的 base64 数据）")
        raw_b64 = parts[1]
    else:
        raw_b64 = content_b64
    try:
        blob = base64.b64decode(raw_b64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ReportError(f"文件内容解码失败：{e}") from e
    if not blob:
        raise ReportError("文件为空")
    if len(blob) > MAX_BYTES:
        raise ReportError(f"文件过大（{len(blob) // 1024 // 1024}MB），上限 {MAX_BYTES // 1024 // 1024}MB")

    rid = uuid.uuid4().hex
    meta = {
        "id": rid,
        "name": fname,
        "industry": classify(fname),
        "size": len(blob),
        "ext": ext,
        "ts": int(time.time() * 1000),
    }

    with _LOCK:
        items = _load_index()

        # 写实体文件
        _ensure_dir()
        entity_tmp = _tmp_name(str(REPORTS_DIR / rid))
        try:
            with open(entity_tmp, "wb") as f:
                f.write(blob)
                f.flush()
                os.fsync(f.fileno())
            entity_path = REPORTS_DIR / f"{rid}{ext}"
            os.replace(entity_tmp, entity_path)
            entity_tmp = None
        finally:
            if entity_tmp is not None and os.path.exists(entity_tmp):
                try:
                    os.remove(entity_tmp)
                except OSError:
                    pass

        items.append(meta)
        try:
            _save_index(items)
        except BaseException:
            ep = REPORTS_DIR / f"{rid}{ext}"
            try:
                ep.unlink(missing_ok=True)
            except OSError:
                pass
            raise
    return meta


def report_path(rid: str) -> tuple[Path, str] | None:
    """按 id 取 (磁盘路径, 原始文件名)；不存在返回 None。"""
    for r in _load_index():
        if r.get("id") == rid:
            p = REPORTS_DIR / f"{rid}{r.get('ext', '')}"
            return (p, r.get("name", rid)) if p.exists() else None
    return None


def delete_report(rid: str) -> bool:
    """删文件 + 移除索引条目。删成功（或本就不在）返回是否命中。"""
    with _LOCK:
        items = _load_index()
        hit = next((r for r in items if r.get("id") == rid), None)
        if hit is None:
            return False

        new_items = [r for r in items if r.get("id") != rid]
        _save_index(new_items)

        fp = REPORTS_DIR / f"{rid}{hit.get('ext', '')}"
        try:
            fp.unlink(missing_ok=True)
        except OSError:
            pass
    return True

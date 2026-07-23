"""我的研报 —— 用户上传/归档自己的研报文件，存本地、不上传、不进开源仓库。

设计取舍：
- 走 base64 JSON 上传（不引入 python-multipart 依赖，契合本项目「秒装必可用」）；研报文件不大，够用。
- 存到 `VR_REPORTS_DIR`（默认 ~/.vibe-research/myreports/，也可用 VR_DATA_DIR 换根目录）——用户私有资料，绝不进仓、不上传。
  放仓库外，重新下载/覆盖项目文件夹不会丢（issue #12）；≤v0.1.1 存 backend/.cache/myreports/，首次启动自动迁移（复制，旧目录保留作备份）。
- 元数据存目录内 index.json；按文件名关键词自动打「行业」标签（best-effort，未命中记「未分类」）。
- 统一研档档案：支持丰富元数据（标题 / 机构 / 发布日期 / 关联赛道 / 来源 / 类型）、SHA-256 去重、按时间·产业·机构浏览、全文检索。
  新字段全部可选、向后兼容：旧 index.json 在首次启动时一次性自动升级（幂等、原子写、失败不阻塞启动）。

研报是用户私有数据，只落本地磁盘。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

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
    # PCB 独立成类（不再折进 AI算力）：文件名含 pcb / 印制电路板 / 覆铜板 / 生益 / 胜宏 / 深南电路 等即归此类。
    ("PCB", ["pcb", "印制电路板", "覆铜板", "hdi", "背板", "backplane", "铜中板", "高速板", "low loss", "low-loss",
             "megtron", "isola", "rogers", "panasonic", "it-968", "生益", "胜宏", "沪电", "深南电路", "华正", "ortho", "hvlp"]),
    ("人形机器人", ["人形", "机器人", "humanoid", "谐波", "丝杠", "滚柱", "灵巧手", "减速器", "optimus", "宇树", "特斯拉"]),
    ("光互联", ["光联", "硅光", "cpo", "光模块", "磷化铟", "inp", "光芯片", "源杰", "中际旭创", "天孚"]),
    ("HBM存储", ["hbm", "存储", "内存", "dram", "长鑫", "美光", "海力士", "颗粒", "闪存", "nand"]),
    ("AI算力", ["算力", "gpu", "英伟达", "nvidia", "服务器", "液冷", "交换机", "cowos", "沪电", "工业富联"]),
    ("半导体", ["半导体", "芯片", "晶圆", "光刻", "封测", "台积电", "刻蚀", "存储芯片"]),
    ("新能源", ["锂电", "电池", "光伏", "储能", "固态", "钠电", "宁德", "比亚迪"]),
    ("创新药", ["创新药", "医药", "生物", "cxo", "临床", "adc", "glp", "药明"]),
    ("商业航天", ["航天", "卫星", "火箭", "星链", "starlink", "spacex", "蓝箭"]),
    ("电力电网", ["电力", "电网", "特高压", "变压器", "输配电", "燃气轮机"]),
]

# 研报来源类型白名单（空串视同未设置）。
_SOURCE_KINDS = ("report", "whitepaper", "company_filing", "news", "standard", "other")

# 发布日期格式：YYYY / YYYY-MM / YYYY-MM-DD（月 01-12、日 01-31 范围校验，拒绝 2025-13-45 等明显非法值）。
_PUBLISH_DATE_RE = re.compile(
    r"^\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?$"
)


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


class ReportEntry(TypedDict):
    """index.json 条目的严格 schema（运行时由 _validate_report_entry 强制校验）。"""
    id: str
    name: str
    ext: str
    size: int
    ts: int
    industry: str
    file_sha256: str
    imported_at: str
    title: str
    institution: str
    publish_date: str
    sector_keys: list[str]
    source_url: str
    source_kind: str


def _index_path() -> Path:
    return REPORTS_DIR / "index.json"


def _tmp_name(base: str) -> str:
    return f"{base}.tmp.{os.urandom(4).hex()}"


def _validate_index_data(data):
    """宽松校验（加载 / 保存通用）：只核查 id + ext，向后兼容旧格式条目与测试夹具。"""
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


def _validate_report_entry(entry) -> None:
    """严格校验单个条目：必填字段 + 类型 + 额外字段禁止（extra="forbid"）。不符即抛 ReportIndexCorruptedError。"""
    if not isinstance(entry, dict):
        raise ReportIndexCorruptedError()
    allowed = {
        "id", "name", "ext", "size", "ts", "industry",
        "file_sha256", "imported_at", "title", "institution",
        "publish_date", "sector_keys", "source_url", "source_kind",
    }
    extra = set(entry.keys()) - allowed
    if extra:
        raise ReportIndexCorruptedError()

    def _check_str(key: str, non_empty: bool = False) -> None:
        v = entry.get(key)
        if not isinstance(v, str) or (non_empty and not v):
            raise ReportIndexCorruptedError()

    def _check_num(key: str) -> None:
        v = entry.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ReportIndexCorruptedError()

    _check_str("id", non_empty=True)
    _check_str("name", non_empty=True)
    _check_str("ext")
    _check_num("size")
    if entry["size"] < 0:
        raise ReportIndexCorruptedError()
    _check_num("ts")
    _check_str("industry")
    _check_str("file_sha256")
    _check_str("imported_at")
    _check_str("title")
    _check_str("institution")
    _check_str("publish_date")
    _check_str("source_url")
    _check_str("source_kind")
    sector_keys = entry.get("sector_keys")
    if not isinstance(sector_keys, list):
        raise ReportIndexCorruptedError()
    for sk in sector_keys:
        if not isinstance(sk, str):
            raise ReportIndexCorruptedError()


def _ensure_dir() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> list[dict]:
    """按 id 取 (磁盘路径, 原始文件名)；不存在返回 None。"""
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
    # 先验证待保存的新数据，非法则立即抛错，不动任何文件
    _validate_index_data(items)

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


def _ms_to_iso(ts: float) -> str:
    """毫秒 epoch → ISO 8601（UTC）；失败回退到当前时间，绝不返回空串。"""
    try:
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return datetime.now(timezone.utc).isoformat()


def _upgrade_entry(e: dict) -> None:
    """把一条旧格式条目就地补全为新 schema（不写盘）。"""
    name = e.get("name", "")
    ext = e.get("ext", "")
    # 展示标题：默认取文件名去掉扩展名；无扩展名则用文件名本身。
    title = os.path.splitext(name)[0] if ext else name
    e["title"] = title or name
    # 归档日期：从旧 ts（毫秒 epoch）派生，服务器设定。
    e["imported_at"] = _ms_to_iso(e.get("ts", 0))
    # SHA-256：实体文件还在就算一个，否则留空（不伪造）。
    rid = e.get("id", "")
    entity_path = REPORTS_DIR / f"{rid}{ext}" if rid else None
    if entity_path is not None and entity_path.exists():
        try:
            e["file_sha256"] = hashlib.sha256(entity_path.read_bytes()).hexdigest()
        except OSError:
            e["file_sha256"] = ""
    else:
        e["file_sha256"] = ""
    e.setdefault("institution", "")
    e.setdefault("publish_date", "")
    e.setdefault("sector_keys", [])
    e.setdefault("source_url", "")
    e.setdefault("source_kind", "")


def _migrate_index() -> None:
    """首次启动一次性把旧 index.json 升级到新 schema。幂等、原子写、失败不阻塞启动（告警后继续）。"""
    try:
        ip = _index_path()
        if not ip.exists():
            return
        items = _load_index()
        changed = False
        for e in items:
            if "imported_at" in e:
                continue  # 已升级，跳过
            _upgrade_entry(e)
            changed = True
        if not changed:
            return
        # 升级后严格校验全部条目，确保写回去的是合法数据。
        for e in items:
            _validate_report_entry(e)
        _save_index(items)
    except Exception as e:  # noqa: BLE001
        # 迁移失败不阻塞启动；旧条目原样保留，下次启动会重试。
        print(f"[vibe-research] 研报索引元数据迁移失败（旧条目保留，不影响启动）：{e}", file=sys.stderr)


# 首次启动一次性迁移（与 _migrate_legacy 同在 import 时运行，模块级幂等）。
_migrate_index()


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


def save_report(
    name: str,
    content_b64: str,
    *,
    title: str | None = None,
    institution: str | None = None,
    publish_date: str | None = None,
    sector_keys: list[str] | None = None,
    source_url: str | None = None,
    source_kind: str | None = None,
) -> dict:
    """解码 base64 存盘 + 打行业标签 + 记录元数据。返回该条元数据。

    新字段全部可选（keyword-only），向后兼容：旧前端只传 name + content_b64 仍正常工作。
    """
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

    # 元数据校验（fail-closed：非法输入立即 400，不写任何文件）。
    if publish_date:
        if not _PUBLISH_DATE_RE.match(publish_date):
            raise ReportError("发布日期格式应为 YYYY-MM-DD / YYYY-MM / YYYY")
    if sector_keys is not None:
        if not isinstance(sector_keys, list) or any(not isinstance(x, str) for x in sector_keys):
            raise ReportError("sector_keys 须为字符串列表")
    if source_kind is not None and source_kind not in _SOURCE_KINDS:
        raise ReportError(f"source_kind 无效，支持：{' / '.join(_SOURCE_KINDS)}")

    file_sha256 = hashlib.sha256(blob).hexdigest()
    rid = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)

    meta: dict = {
        "id": rid,
        "name": fname,
        "industry": classify(fname),
        "size": len(blob),
        "ext": ext,
        "ts": now_ms,
        "file_sha256": file_sha256,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "title": title if title else (os.path.splitext(fname)[0] or fname),
        "institution": institution or "",
        "publish_date": publish_date or "",
        "sector_keys": list(sector_keys) if sector_keys else [],
        "source_url": source_url or "",
        "source_kind": source_kind or "",
    }
    # 新条目写入前严格校验（确保进入索引的每条数据都符合 schema）。
    _validate_report_entry(meta)

    with _LOCK:
        items = _load_index()

        # SHA-256 去重：同内容已归档则不再写重复文件，返回既有条目 + deduped 标记。
        for e in items:
            if e.get("file_sha256") == file_sha256:
                return {**e, "deduped": True}

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
        except Exception:
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


def update_report_meta(rid: str, changes: dict) -> dict | None:
    """部分更新元数据（PATCH）。不允许改 id / name / ext / size / ts / 内容；更新后严格校验。
    条目不存在返回 None。"""
    allowed = {"title", "institution", "publish_date", "sector_keys", "source_url", "source_kind"}
    unknown = set(changes) - allowed
    if unknown:
        raise ReportError(f"不可修改的字段：{', '.join(sorted(unknown))}")

    if "publish_date" in changes:
        pd = changes["publish_date"]
        if pd and not _PUBLISH_DATE_RE.match(pd):
            raise ReportError("发布日期格式应为 YYYY-MM-DD / YYYY-MM / YYYY")
    if "sector_keys" in changes:
        sk = changes["sector_keys"]
        if not isinstance(sk, list) or any(not isinstance(x, str) for x in sk):
            raise ReportError("sector_keys 须为字符串列表")
    if "source_kind" in changes:
        sk = changes["source_kind"]
        if sk and sk not in _SOURCE_KINDS:
            raise ReportError(f"source_kind 无效，支持：{' / '.join(_SOURCE_KINDS)}")

    with _LOCK:
        items = _load_index()
        entry = next((e for e in items if e.get("id") == rid), None)
        if entry is None:
            return None
        for k, v in changes.items():
            entry[k] = v
        _validate_report_entry(entry)
        _save_index(items)
        return entry


def _report_year_month(e: dict) -> tuple[str | None, str | None]:
    """从条目提取 (年, 月) 用于时间浏览：优先 publish_date，缺失则回退到 imported_at。"""
    pd = e.get("publish_date", "")
    if pd:
        parts = pd.split("-")
        year = parts[0]
        month = "-".join(parts[:2]) if len(parts) >= 2 else None
        return year, month
    ia = e.get("imported_at", "")
    if ia:
        year = ia[:4]
        month = ia[:7] if len(ia) >= 7 else None
        return year, month
    return None, None


def build_browse(items: list[dict], group: str, sector_key: str | None = None) -> dict:
    """按 year / industry / institution 分组浏览。纯函数（无 HTTP / IO），单测友好。"""
    if group not in ("year", "industry", "institution"):
        raise ValueError(f"unknown browse group: {group}")

    rows = [e for e in items if sector_key is None or sector_key in e.get("sector_keys", [])]

    if group == "year":
        year_map: dict[str, dict[str, int]] = {}      # year -> month -> count
        year_count: dict[str, int] = {}
        for e in rows:
            year, month = _report_year_month(e)
            if not year:
                year = "未知"
            year_count[year] = year_count.get(year, 0) + 1
            if month:
                year_map.setdefault(year, {})
                year_map[year][month] = year_map[year].get(month, 0) + 1
        groups = []
        for year in year_count:
            months = [{"key": m, "label": m, "count": c} for m, c in year_map.get(year, {}).items()]
            months.sort(key=lambda x: x["key"], reverse=True)
            groups.append({"key": year, "label": year, "count": year_count[year], "months": months})
        groups.sort(key=lambda x: x["key"], reverse=True)
        return {"groups": groups, "total": len(rows)}

    if group == "industry":
        ind_map: dict[str, dict[str, object]] = {}  # industry -> {count, sector_keys:set}
        for e in rows:
            ind = e.get("industry") or "未分类"
            slot = ind_map.setdefault(ind, {"count": 0, "sector_keys": set()})
            slot["count"] += 1
            for sk in e.get("sector_keys", []):
                slot["sector_keys"].add(sk)
        groups = []
        for ind, slot in ind_map.items():
            groups.append({
                "key": ind,
                "label": ind,
                "count": slot["count"],
                "sector_keys": sorted(slot["sector_keys"]),
            })
        groups.sort(key=lambda x: (x["key"] == "未分类", -x["count"], x["key"]))
        return {"groups": groups, "total": len(rows)}

    # institution
    inst_map: dict[str, dict[str, object]] = {}  # key -> {label, count}
    for e in rows:
        inst = e.get("institution", "")
        if not inst:
            key, label = "__unknown__", "未确认机构"
        else:
            key, label = inst, inst
        slot = inst_map.setdefault(key, {"label": label, "count": 0})
        slot["count"] += 1
    groups = [{"key": k, "label": v["label"], "count": v["count"]} for k, v in inst_map.items()]
    # 未确认机构 排最末，其余按数量降序。
    groups.sort(key=lambda x: (x["key"] == "__unknown__", -x["count"], x["label"]))
    return {"groups": groups, "total": len(rows)}


def search_reports(items: list[dict], q: str) -> list[dict]:
    """全文检索：匹配 name / title / institution / sector_keys。纯函数，单测友好。"""
    query = (q or "").strip().lower()
    if not query:
        return []
    hits = []
    for e in items:
        hay = " ".join(str(e.get(k, "")) for k in ("name", "title", "institution"))
        hay += " " + " ".join(e.get("sector_keys", []))
        if query in hay.lower():
            hits.append(e)
    return hits

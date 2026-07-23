"""我的研报 —— 用户上传/归档自己的研报文件，存本地、不上传、不进开源仓库。

设计取舍：
- 走 base64 JSON 上传（不引入 python-multipart 依赖，契合本项目「秒装必可用」）；研报文件不大，够用。
- 存到 `VR_REPORTS_DIR`（默认 ~/.vibe-research/myreports/，也可用 VR_DATA_DIR 换根目录）——用户私有资料，绝不进仓、不上传。
  放仓库外，重新下载/覆盖项目文件夹不会丢（issue #12）；≤v0.1.1 存 backend/.cache/myreports/，首次启动自动迁移（复制，旧目录保留作备份）。
- 元数据存目录内 index.json；按文件名关键词自动打「行业」标签（best-effort，未命中记「未分类」）。
- 统一研档档案：支持丰富元数据（标题 / 机构 / 发布日期 / 关联赛道 / 来源 / 类型）、SHA-256 去重、按时间·产业·机构浏览、全文检索。
- 新字段全部可选、向后兼容：旧 index.json 在读取时即时规范化（不写回、不创建 .bak、不计算 SHA-256），
  用户显式上传 / 编辑 / 删除时才写索引。禁止在 import / 启动 / 只读 GET 时重写用户真实 index.json。

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

# 来源链接 scheme 白名单：只允许空串、http://、https://。拒绝 javascript: / data: / file: / ftp: 与无 scheme 的本地路径。
_SOURCE_URL_RE = re.compile(r"^(?:|https?://.+)$", re.IGNORECASE)

# 元数据字段长度上限（防滥用 / 注入）。
FIELD_MAX_LENGTH = {"title": 500, "institution": 200, "source_url": 2000, "source_kind": 50}
# sector_keys 条目上限。
MAX_SECTOR_KEYS = 20


class ReportError(ValueError):
    """上传/校验类错误（对应 HTTP 400/413）。"""


class ReportIndexCorruptedError(RuntimeError):
    """本地研报索引文件损坏，已停止读写以避免覆盖。"""
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
    # a-stock-data 外部研报元数据（导入时填充，可选 / 向后兼容）。
    source_provider: str
    external_id: str
    info_code: str
    report_scope: str
    report_type: str


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
        "source_provider", "external_id", "info_code", "report_scope", "report_type",
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
    # 外部元数据字段（a-stock-data 导入）：可选；存在时必须是字符串。
    for _opt in ("source_provider", "external_id", "info_code", "report_scope", "report_type"):
        if _opt in entry:
            if not isinstance(entry[_opt], str):
                raise ReportIndexCorruptedError()
    sector_keys = entry.get("sector_keys")
    if not isinstance(sector_keys, list):
        raise ReportIndexCorruptedError()
    for sk in sector_keys:
        if not isinstance(sk, str):
            raise ReportIndexCorruptedError()


# ---------------------------------------------------------------------------
# 板块注册表（用于 sector_keys 白名单校验）。
# 从 sectors.json 读取，失败时降级为不校验（不阻塞研报功能）。
# ---------------------------------------------------------------------------
_SECTOR_KEYS_CACHE: frozenset[str] | None = None


def _valid_sector_keys() -> frozenset[str] | None:
    """返回合法 sector key 集合；读取失败返回 None（降级为不校验）。"""
    global _SECTOR_KEYS_CACHE
    if _SECTOR_KEYS_CACHE is not None:
        return _SECTOR_KEYS_CACHE
    try:
        sectors_json = Path(__file__).resolve().parent.parent / "frontend" / "src" / "data" / "sectors.json"
        raw = json.loads(sectors_json.read_text(encoding="utf-8"))
        _SECTOR_KEYS_CACHE = frozenset(s["key"] for s in raw.get("sectors", []))
    except Exception:
        _SECTOR_KEYS_CACHE = None
    return _SECTOR_KEYS_CACHE


def _ensure_dir() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> list[dict]:
    """加载并严格校验 index.json（写入前必须经过此函数）。"""
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


# ---------------------------------------------------------------------------
# 读时规范化（不写回、不计算 SHA-256、不创建 .bak）。
# 目的：旧 index.json 不写回也能读取；缺失的新字段返回安全默认值。
# ---------------------------------------------------------------------------

def _ms_to_iso(ts: float) -> str:
    """毫秒 epoch → ISO 8601（UTC）；失败回退到当前时间，绝不返回空串。"""
    try:
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return datetime.now(timezone.utc).isoformat()


def _normalize_entry_for_read(e: dict) -> dict:
    """把一条旧格式条目补全为新 schema 的只读副本（不写盘、不计算 SHA-256）。返回新 dict。

    关键：已有非空 title 必须保留，不得无条件用文件名覆盖。
    """
    name = e.get("name", "") if isinstance(e.get("name"), str) else ""
    ext = e.get("ext", "") if isinstance(e.get("ext"), str) else ""
    fallback_title = os.path.splitext(name)[0] if ext else name
    fallback_title = fallback_title or name or "未命名"
    normalized = dict(e)  # 浅拷贝，不动原条目
    existing_title = e.get("title")
    if isinstance(existing_title, str) and existing_title.strip():
        normalized["title"] = existing_title
    else:
        normalized["title"] = fallback_title
    normalized.setdefault("imported_at", _ms_to_iso(e.get("ts", 0) or 0))
    normalized.setdefault("file_sha256", "")
    normalized.setdefault("institution", "")
    normalized.setdefault("publish_date", "")
    normalized.setdefault("sector_keys", [])
    normalized.setdefault("source_url", "")
    normalized.setdefault("source_kind", "")
    # a-stock 外部元数据：缺省安全默认值
    normalized.setdefault("source_provider", "")
    normalized.setdefault("external_id", "")
    normalized.setdefault("info_code", "")
    normalized.setdefault("report_scope", "")
    normalized.setdefault("report_type", "")
    if not isinstance(normalized.get("sector_keys"), list):
        normalized["sector_keys"] = []
    return normalized


def _load_index_normalized() -> list[dict]:
    out: list[dict] = []
    for e in _load_index():
        out.append(_normalize_entry_for_read(e))
    return out


def _load_index_raw() -> list[dict]:
    """读时规范化加载：旧 index.json 不写回也能读取，缺失字段返回安全默认值。"""
    return _load_index_normalized()


# ---------------------------------------------------------------------------
# 显式迁移（仅用户调用或测试触发，禁止在 import / 只读 GET 时自动执行）。
# ---------------------------------------------------------------------------

def _migrate_index() -> None:
    """一次性把旧 index.json 升级为新 schema。幂等、原子写、失败不阻塞启动（告警后继续）。"""
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


def _upgrade_entry(e: dict) -> None:
    """把一条旧格式条目就地补全为新 schema（写盘前用）。会计算 SHA-256。保留已有 title。"""
    name = e.get("name", "") if isinstance(e.get("name"), str) else ""
    ext = e.get("ext", "") if isinstance(e.get("ext"), str) else ""
    if not (isinstance(e.get("title"), str) and e["title"].strip()):
        title = os.path.splitext(name)[0] if ext else name
        e["title"] = title or name or "未命名"
    e["imported_at"] = e.get("imported_at") or _ms_to_iso(e.get("ts", 0) or 0)
    rid = e.get("id", "")
    entity_path = REPORTS_DIR / f"{rid}{ext}" if rid else None
    if not e.get("file_sha256"):
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
    e.setdefault("source_provider", "")
    e.setdefault("external_id", "")
    e.setdefault("info_code", "")
    e.setdefault("report_scope", "")
    e.setdefault("report_type", "")


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


# ---------------------------------------------------------------------------
# 校验辅助
# ---------------------------------------------------------------------------

def _is_valid_publish_date(value: str) -> bool:
    """真实日历校验：YYYY / YYYY-MM / YYYY-MM-DD，拒绝 2026-02-31、2026-13、0000 等。"""
    if not _PUBLISH_DATE_RE.match(value):
        return False
    year = int(value[:4])
    if year == 0:
        return False
    parts = value.split("-")
    try:
        if len(parts) == 1:
            datetime(year, 1, 1)
        elif len(parts) == 2:
            datetime(year, int(parts[1]), 1)
        else:
            datetime(year, int(parts[1]), int(parts[2]))
        return True
    except ValueError:
        return False


def _is_valid_source_url(value: str) -> bool:
    """来源链接 scheme校验：只允许空串、http://、https://。"""
    return bool(_SOURCE_URL_RE.match(value))


def _normalize_sector_keys(value: list[str] | None) -> list[str]:
    """sector_keys 去重 + 保持顺序；返回 None 表示输入非法。"""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > MAX_SECTOR_KEYS:
        return None
    for v in value:
        if not isinstance(v, str) or not v:
            return None
    seen: set[str] = set()
    out: list[str] = []
    for v in value:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


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
    """按上传时间降序返回元数据的规范化只读副本（不写盘）。"""
    items = _load_index_raw()
    return sorted(items, key=lambda r: r.get("ts", 0), reverse=True)


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
        if not _is_valid_publish_date(publish_date):
            raise ReportError("发布日期格式无效或为不存在日期；应为 YYYY-MM-DD / YYYY-MM / YYYY")
    if source_url and not _is_valid_source_url(source_url):
        raise ReportError("来源链接仅允许 http:// 或 https://")
    if source_kind is not None and source_kind not in _SOURCE_KINDS:
        raise ReportError(f"source_kind 无效，支持：{' / '.join(_SOURCE_KINDS)}")
    if title is not None and len(title) > FIELD_MAX_LENGTH["title"]:
        raise ReportError(f"标题过长（{len(title)}），上限 {FIELD_MAX_LENGTH['title']}")
    if institution is not None and len(institution) > FIELD_MAX_LENGTH["institution"]:
        raise ReportError(f"机构过长（{len(institution)}），上限 {FIELD_MAX_LENGTH['institution']}")
    if source_url is not None and len(source_url) > FIELD_MAX_LENGTH["source_url"]:
        raise ReportError(f"来源链接过长（{len(source_url)}），上限 {FIELD_MAX_LENGTH['source_url']}")

    # sector_keys 规范化 + 白名单校验。未提供（None）→ 默认 []。
    if sector_keys is None:
        norm_keys: list[str] = []
    else:
        norm_keys = _normalize_sector_keys(list(sector_keys))
        if norm_keys is None:
            raise ReportError(f"sector_keys 须为非空字符串列表，每项 ≤{MAX_SECTOR_KEYS} 项")
        allowed_keys = _valid_sector_keys()
        if allowed_keys is not None:
            bad = [k for k in norm_keys if k not in allowed_keys]
            if bad:
                raise ReportError(f"sector_keys 含未知板块：{', '.join(bad)}")

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
        "sector_keys": norm_keys,
        "source_url": source_url or "",
        "source_kind": source_kind or "",
        "source_provider": "",
        "external_id": "",
        "info_code": "",
        "report_scope": "",
        "report_type": "",
    }
    # 新条目写入前严格校验（确保进入索引的每条数据都符合 schema）。
    _validate_report_entry(meta)

    with _LOCK:
        items = _load_index()

        # SHA-256 去重：同内容已归档则合并 sector_keys + 仅补空字段，不写重复文件。
        for e in items:
            if e.get("file_sha256") == file_sha256:
                merged_keys = list(e.get("sector_keys", []))
                for k in norm_keys:
                    if k not in merged_keys:
                        merged_keys.append(k)
                e["sector_keys"] = merged_keys
                # 仅补旧记录中为空的合法元数据，不静默覆盖用户已有非空元数据。
                if not e.get("institution") and institution:
                    e["institution"] = institution
                if not e.get("publish_date") and publish_date:
                    e["publish_date"] = publish_date
                if not e.get("source_url") and source_url:
                    e["source_url"] = source_url
                if not e.get("source_kind") and source_kind:
                    e["source_kind"] = source_kind
                if not e.get("title") or e["title"] == os.path.splitext(e.get("name", ""))[0]:
                    if title:
                        e["title"] = title
                _save_index(items)
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


def _merge_empty_fields(entry: dict, incoming: dict, keys: tuple[str, ...]) -> None:
    """仅把 incoming 中非空值补进 entry 的空字段；不覆盖已有非空。"""
    for k in keys:
        if not entry.get(k) and incoming.get(k):
            entry[k] = incoming[k]


def import_report_bytes(
    *,
    name: str,
    content: bytes,
    metadata: dict | None = None,
) -> dict:
    """正式公共导入入口：原子写实体 + 索引，支持 external_id / SHA-256 去重。

    由 app 层完成请求校验与 PDF 下载后调用。本函数负责：
    - 元数据校验
    - 去重优先级：source_provider+external_id → file_sha256 →（不创建新文件）
    - sector_keys 合并
    - 实体/索引原子写；失败回滚；临时文件清理
    - 返回条目，重复时带 deduped=True
    """
    if not content:
        raise ReportError("文件内容为空")
    if len(content) > MAX_BYTES:
        raise ReportError(f"文件过大（{len(content) // 1024 // 1024}MB），上限 {MAX_BYTES // 1024 // 1024}MB")

    meta_in = dict(metadata or {})
    fname = _sanitize_name(name)
    ext = os.path.splitext(fname)[1].lower() or ".pdf"
    if ext not in ALLOWED_EXT:
        raise ReportError(f"不支持的文件类型 {ext}；支持：PDF / Word / txt / md / 表格 / 图片")

    title = meta_in.get("title")
    if title is not None and not isinstance(title, str):
        raise ReportError("title 必须是字符串")
    institution = meta_in.get("institution") or ""
    publish_date = meta_in.get("publish_date") or ""
    source_url = meta_in.get("source_url") or ""
    source_kind = meta_in.get("source_kind") or "report"
    sector_keys_raw = meta_in.get("sector_keys")
    source_provider = meta_in.get("source_provider") or ""
    external_id = meta_in.get("external_id") or ""
    info_code = meta_in.get("info_code") or ""
    report_scope = meta_in.get("report_scope") or ""
    report_type = meta_in.get("report_type") or ""
    industry = meta_in.get("industry") or classify(fname)

    if publish_date and not _is_valid_publish_date(publish_date):
        raise ReportError("发布日期格式无效或为不存在日期；应为 YYYY-MM-DD / YYYY-MM / YYYY")
    if source_url and not _is_valid_source_url(source_url):
        raise ReportError("来源链接仅允许 http:// 或 https://")
    if source_kind and source_kind not in _SOURCE_KINDS:
        raise ReportError(f"source_kind 无效，支持：{' / '.join(_SOURCE_KINDS)}")
    if title is not None and len(title) > FIELD_MAX_LENGTH["title"]:
        raise ReportError(f"标题过长（{len(title)}），上限 {FIELD_MAX_LENGTH['title']}")
    if institution and len(institution) > FIELD_MAX_LENGTH["institution"]:
        raise ReportError(f"机构过长（{len(institution)}），上限 {FIELD_MAX_LENGTH['institution']}")
    if source_url and len(source_url) > FIELD_MAX_LENGTH["source_url"]:
        raise ReportError(f"来源链接过长（{len(source_url)}），上限 {FIELD_MAX_LENGTH['source_url']}")

    if sector_keys_raw is None:
        norm_keys: list[str] = []
    else:
        norm_keys = _normalize_sector_keys(list(sector_keys_raw))
        if norm_keys is None:
            raise ReportError(f"sector_keys 须为非空字符串列表，每项 ≤{MAX_SECTOR_KEYS} 项")
        allowed_keys = _valid_sector_keys()
        if allowed_keys is not None:
            bad = [k for k in norm_keys if k not in allowed_keys]
            if bad:
                raise ReportError(f"sector_keys 含未知板块：{', '.join(bad)}")

    file_sha256 = hashlib.sha256(content).hexdigest()
    display_title = (title.strip() if isinstance(title, str) and title.strip() else None) or (
        os.path.splitext(fname)[0] or fname
    )

    fill_fields = (
        "institution", "publish_date", "source_url", "source_kind",
        "source_provider", "external_id", "info_code", "report_scope", "report_type",
    )
    incoming_fill = {
        "institution": institution,
        "publish_date": publish_date,
        "source_url": source_url,
        "source_kind": source_kind,
        "source_provider": source_provider,
        "external_id": external_id,
        "info_code": info_code,
        "report_scope": report_scope if isinstance(report_scope, str) else "",
        "report_type": report_type,
        "title": display_title,
    }

    with _LOCK:
        items = _load_index()

        # 1) external identity 去重
        if source_provider and external_id:
            for e in items:
                if e.get("source_provider") == source_provider and e.get("external_id") == external_id:
                    merged_keys = list(e.get("sector_keys") or [])
                    for k in norm_keys:
                        if k not in merged_keys:
                            merged_keys.append(k)
                    e["sector_keys"] = merged_keys
                    _merge_empty_fields(e, incoming_fill, fill_fields)
                    if not e.get("title") or e["title"] == os.path.splitext(e.get("name", "") or "")[0]:
                        e["title"] = display_title
                    _upgrade_entry(e)
                    _validate_report_entry(e)
                    _save_index(items)
                    return {**e, "deduped": True}

        # 2) SHA-256 去重
        for e in items:
            if e.get("file_sha256") == file_sha256:
                merged_keys = list(e.get("sector_keys") or [])
                for k in norm_keys:
                    if k not in merged_keys:
                        merged_keys.append(k)
                e["sector_keys"] = merged_keys
                _merge_empty_fields(e, incoming_fill, fill_fields)
                if not e.get("title") or e["title"] == os.path.splitext(e.get("name", "") or "")[0]:
                    e["title"] = display_title
                _upgrade_entry(e)
                _validate_report_entry(e)
                _save_index(items)
                return {**e, "deduped": True}

        rid = uuid.uuid4().hex
        now_ms = int(time.time() * 1000)
        meta: dict = {
            "id": rid,
            "name": fname,
            "industry": industry if isinstance(industry, str) else classify(fname),
            "size": len(content),
            "ext": ext,
            "ts": now_ms,
            "file_sha256": file_sha256,
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "title": display_title,
            "institution": institution,
            "publish_date": publish_date,
            "sector_keys": norm_keys,
            "source_url": source_url,
            "source_kind": source_kind,
            "source_provider": source_provider,
            "external_id": external_id,
            "info_code": info_code,
            "report_scope": report_scope if isinstance(report_scope, str) else "",
            "report_type": report_type,
        }
        _validate_report_entry(meta)

        _ensure_dir()
        entity_tmp = _tmp_name(str(REPORTS_DIR / rid))
        entity_path = REPORTS_DIR / f"{rid}{ext}"
        try:
            with open(entity_tmp, "wb") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(entity_tmp, entity_path)
            entity_tmp = None
        except Exception:
            if entity_tmp is not None and os.path.exists(entity_tmp):
                try:
                    os.remove(entity_tmp)
                except OSError:
                    pass
            raise
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
            try:
                entity_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return meta


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
    """部分更新元数据（PATCH）。

    语义：
      - 字段未出现（exclude_unset）：保持原值；
      - 字符串字段传 ""：明确清空；sector_keys 传 []：明确清空；
      - 任意字段传 null：拒绝 HTTP 400；
      - 标题传 ""：拒绝 400（禁止无法展示的空标题）。
    只规范化当前待写记录，不批量迁移整个索引。
    不允许改 id / name / ext / size / ts / 内容；条目不存在返回 None。
    """
    allowed = {"title", "institution", "publish_date", "sector_keys", "source_url", "source_kind"}
    unknown = set(changes) - allowed
    if unknown:
        raise ReportError(f"不可修改的字段：{', '.join(sorted(unknown))}")

    # null 明确拒绝（HTTP 400）。
    for k, v in changes.items():
        if v is None:
            raise ReportError(f"字段 {k} 不允许为 null；如需清空字符串请传 ''")

    if "title" in changes:
        t = changes["title"]
        if not isinstance(t, str) or not t.strip():
            raise ReportError("标题不能为空")
        if len(t) > FIELD_MAX_LENGTH["title"]:
            raise ReportError(f"标题过长（{len(t)}），上限 {FIELD_MAX_LENGTH['title']}")
    if "publish_date" in changes:
        pd = changes["publish_date"]
        if pd and not _is_valid_publish_date(pd):
            raise ReportError("发布日期格式无效或为不存在日期；应为 YYYY-MM-DD / YYYY-MM / YYYY")
    if "source_url" in changes:
        su = changes["source_url"]
        if su and not _is_valid_source_url(su):
            raise ReportError("来源链接仅允许 http:// 或 https://")
        if su and len(su) > FIELD_MAX_LENGTH["source_url"]:
            raise ReportError(f"来源链接过长（{len(su)}），上限 {FIELD_MAX_LENGTH['source_url']}")
    if "source_kind" in changes:
        sk = changes["source_kind"]
        if sk and sk not in _SOURCE_KINDS:
            raise ReportError(f"source_kind 无效，支持：{' / '.join(_SOURCE_KINDS)}")
    if "institution" in changes:
        inst = changes["institution"]
        if inst and len(inst) > FIELD_MAX_LENGTH["institution"]:
            raise ReportError(f"机构过长（{len(inst)}），上限 {FIELD_MAX_LENGTH['institution']}")

    # sector_keys 规范化 + 白名单校验。
    if "sector_keys" in changes:
        norm = _normalize_sector_keys(changes["sector_keys"])
        if norm is None:
            raise ReportError(f"sector_keys 须为非空字符串列表，每项 ≤{MAX_SECTOR_KEYS} 项")
        allowed_keys = _valid_sector_keys()
        if allowed_keys is not None:
            bad = [k for k in norm if k not in allowed_keys]
            if bad:
                raise ReportError(f"sector_keys 含未知板块：{', '.join(bad)}")
        changes["sector_keys"] = norm

    with _LOCK:
        items = _load_index()
        entry = next((e for e in items if e.get("id") == rid), None)
        if entry is None:
            return None
        # 旧条目 PATCH 时只规范化当前记录，不要求整库迁移。
        _upgrade_entry(entry)
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

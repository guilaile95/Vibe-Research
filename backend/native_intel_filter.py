"""Native Intel 个人兴趣过滤引擎（TREND-PARITY Wave 2）。

支持双轨过滤模式：
1. 关键词/正则过滤模式（Keyword Filtering）：
   - 支持多字段（title + summary）匹配（VIBE_NATIVE_SUPERSET）
   - 全局排除词（global_excludes）与全局过滤词（filter_terms / !term）：命中即排除（Exclude Wins）
   - 空规则组（no groups）：除排除规则外匹配全部资讯
   - 规则组内：
     - required 必须词（+term）：必须全部命中（AND）
     - includes 普通词（normal terms）：至少命中一个（OR）
     - excludes 分组专属排除词：命中则该组不匹配
     - max_count 限制每组最大输出条数
   - 正则表达式：支持 /pattern/ 及尾部 flags 语法（如 /pattern/i, /pattern/g）统一忽略大小写
2. AI 智能过滤模式（AI Intelligent Filter）：
   - 阶段 A：从自然语言兴趣描述中提取结构化分类标签（Fail-closed 严格校验）
   - 阶段 A'：对比新旧标签集计算变化率（change_ratio），输出 keep / add / remove
   - 阶段 B：批量评估资讯相关性并给出分值（0.0 ~ 1.0），min_score 阈值筛选
   - 状态追踪与缓存：区分 CLASSIFIED / NOT_RELEVANT / ERROR，成功未匹配条目落库缓存不重复请求
   - 统一模型通道：严格使用当前有效 AI 配置（Codex Subscription 或 API Compatible），绝无隐式 Provider 切换
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import chat

logger = logging.getLogger(__name__)

METHOD_KEYWORD = "keyword"
METHOD_AI = "ai"
VALID_METHODS = {METHOD_KEYWORD, METHOD_AI}
DEFAULT_MIN_SCORE = 0.7
DEFAULT_RECLASSIFY_THRESHOLD = 0.6


@dataclass
class KeywordGroup:
    name: str
    includes: list[str] = field(default_factory=list)
    required: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    max_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "includes": list(self.includes),
            "required": list(self.required),
            "excludes": list(self.excludes),
        }
        if self.max_count is not None:
            d["max_count"] = self.max_count
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KeywordGroup:
        mc = data.get("max_count")
        max_count = int(mc) if mc is not None and str(mc).isdigit() else None
        return cls(
            name=str(data.get("name") or "").strip(),
            includes=[str(x).strip() for x in data.get("includes") or [] if str(x).strip()],
            required=[str(x).strip() for x in data.get("required") or [] if str(x).strip()],
            excludes=[str(x).strip() for x in data.get("excludes") or [] if str(x).strip()],
            max_count=max_count,
        )


@dataclass
class KeywordRules:
    global_excludes: list[str] = field(default_factory=list)
    filter_terms: list[str] = field(default_factory=list)
    groups: list[KeywordGroup] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "global_excludes": list(self.global_excludes),
            "filter_terms": list(self.filter_terms),
            "groups": [g.to_dict() for g in self.groups],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KeywordRules:
        raw_groups = data.get("groups") or []
        groups = [KeywordGroup.from_dict(g) for g in raw_groups if isinstance(g, dict)]
        global_excludes = [
            str(x).strip() for x in data.get("global_excludes") or [] if str(x).strip()
        ]
        filter_terms = [
            str(x).strip() for x in data.get("filter_terms") or [] if str(x).strip()
        ]
        return cls(
            global_excludes=global_excludes,
            filter_terms=filter_terms,
            groups=groups,
        )


def get_default_keyword_rules() -> KeywordRules:
    return KeywordRules(
        global_excludes=["震惊", "/赌博|博彩/"],
        filter_terms=[],
        groups=[
            KeywordGroup(
                name="半导体与算力",
                includes=["芯片", "光刻机", "半导体", "英伟达", "算力", "GPU"],
                required=[],
                excludes=[],
            ),
            KeywordGroup(
                name="机器人与具身智能",
                includes=["机器人", "人形机器人", "具身智能", "减速器", "/机械狗|四足/"],
                required=[],
                excludes=["机器人动画"],
            ),
            KeywordGroup(
                name="智能出行与新能源",
                includes=["自动驾驶", "智驾", "比亚迪", "特斯拉", "刀片电池", "固态电池"],
                required=[],
                excludes=[],
            ),
        ],
    )


DEFAULT_INTERESTS_TEXT = """我主要关注：
1. 机器人与具身智能：关注人形机器人、减速器、伺服电机、传感器、四足机器狗等产业落地与核心零部件供应链。
2. 液冷与 AI 算力：关注数据中心液冷技术（冷板、浸没、CDU）、GPU 算力芯片、半导体设备与光刻机。
3. 智能汽车与自动驾驶：关注特斯拉 FSD、高阶辅助驾驶、固态电池技术突破与车规级芯片。

重点关注可能对 A 股产业链和上市公司产生实质影响的产业动态、大单订单与政策催化。
不想看娱乐八卦、明星绯闻和泛社会民生琐事。"""


# ---------------------------------------------------------------------------
# Pattern Matcher: plain substring + /regex/ (with optional trailing flags)
# ---------------------------------------------------------------------------

def _match_pattern(pattern: str, text: str) -> bool:
    """匹配单个规则项：若以 '/' 开头且包含结尾 '/'，则视为正则；否则视为大小写不敏感子串。"""
    pat = pattern.strip()
    if not pat:
        return False
    if pat.startswith("/") and len(pat) >= 2:
        last_slash = pat.rfind("/")
        if last_slash > 0:
            regex_str = pat[1:last_slash]
            try:
                return bool(re.search(regex_str, text, re.IGNORECASE))
            except re.error:
                logger.warning("非法正则表达式规则: %s", pat)
                return False
    return pat.lower() in text.lower()


def evaluate_keyword_rules(
    title: str,
    summary: str | None,
    rules: KeywordRules | dict[str, Any],
) -> tuple[bool, list[str]]:
    """基于本地关键词与正则规则评估条目是否匹配。

    返回值：(is_matched, matched_group_names)
    - 匹配范围：title + summary (VIBE_NATIVE_SUPERSET)
    - 全局排除（global_excludes）与全局过滤词（filter_terms）：任一命中立即排除（Exclude Wins）
    - 空规则组（no groups）：除排除规则外，匹配全部资讯
    - 分组逻辑：
      - 分组排除检查（group.excludes）：命中任一则该组不匹配
      - 必须词检查（group.required）：若配置了 required，必须全部命中 (AND)
      - 普通词检查（group.includes）：若配置了 includes，至少命中一个 (OR)
      - 若同时配置 required 与 includes：所有 required 必须命中 AND 至少一个 includes 命中
    """
    if isinstance(rules, dict):
        rules = KeywordRules.from_dict(rules)

    target_text = f"{title or ''} {summary or ''}".strip()
    if not target_text:
        return False, []

    # 1. 全局排除检查（最高优先级 Exclude Wins）
    for g_exc in rules.global_excludes:
        if _match_pattern(g_exc, target_text):
            return False, []
    for f_term in rules.filter_terms:
        if _match_pattern(f_term, target_text):
            return False, []

    # 2. 空规则组：匹配全部资讯
    if not rules.groups:
        return True, []

    # 3. 分组匹配检查
    matched_groups: list[str] = []
    for grp in rules.groups:
        # 分组排除检查
        excluded = False
        for exc in grp.excludes:
            if _match_pattern(exc, target_text):
                excluded = True
                break
        if excluded:
            continue

        # 检查必须词 (required) - 必须全部命中
        required_ok = True
        if grp.required:
            for req in grp.required:
                if not _match_pattern(req, target_text):
                    required_ok = False
                    break
        if not required_ok:
            continue

        # 检查普通词 (includes) - 至少命中一个
        includes_ok = True
        if grp.includes:
            has_inc = False
            for inc in grp.includes:
                if _match_pattern(inc, target_text):
                    has_inc = True
                    break
            includes_ok = has_inc
        elif not grp.required:
            # 既无 required 也无 includes，空分组不匹配
            includes_ok = False

        if required_ok and includes_ok:
            matched_groups.append(grp.name or "默认分组")

    return (len(matched_groups) > 0, matched_groups)


# ---------------------------------------------------------------------------
# Profile Fingerprint Computation
# ---------------------------------------------------------------------------

def compute_keyword_fingerprint(rules: KeywordRules | dict[str, Any]) -> str:
    if isinstance(rules, KeywordRules):
        d = rules.to_dict()
    else:
        d = rules
    raw = json.dumps(d, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def normalize_interests_text(text: str) -> str:
    lines = []
    for line in (text or "").strip().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return "\n".join(lines)


def compute_ai_fingerprint(interests_text: str, tags: list[dict[str, Any]]) -> str:
    norm_interests = normalize_interests_text(interests_text)
    tags_canonical = json.dumps(
        sorted(
            [{"tag": str(t.get("tag") or t.get("name") or "").strip().lower(), "description": str(t.get("description") or "").strip()} for t in tags],
            key=lambda x: x["tag"],
        ),
        ensure_ascii=False,
    )
    payload = f"{norm_interests}\n---\n{tags_canonical}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def compute_profile_fingerprint(
    method: str,
    rules: KeywordRules | dict[str, Any] | None,
    interests_text: str = "",
    tags: list[dict[str, Any]] | None = None,
) -> str:
    if method == METHOD_KEYWORD:
        return compute_keyword_fingerprint(rules or {})
    return compute_ai_fingerprint(interests_text, tags or [])


# ---------------------------------------------------------------------------
# Unified AI Boundary & Execution
# ---------------------------------------------------------------------------

EXTRACT_TAGS_SYSTEM_PROMPT = """你是一个专业的金融与产业资讯分析助手。
你的任务是从用户给定的个人兴趣偏好描述中，提炼出 3 到 8 个高度概括、适合对财经新闻与热榜进行分类打标的结构化标签。

输出格式要求：
请严格输出一个合法 JSON 对象，格式如下：
{
  "tags": [
    {
      "id": 1,
      "tag": "标签名称（2-8字）",
      "description": "该标签涵盖的具体领域和关键词范畴说明"
    }
  ]
}
禁止输出除 JSON 以外的任何分析前言或总结后记。"""

UPDATE_TAGS_SYSTEM_PROMPT = """你是一个专业的个人资讯兴趣标签维护助手。
系统已经有一组现存分类标签，现在用户更新了个人兴趣偏好描述。
请对比现存标签与新描述，评估哪些标签应当保留、新增或移除，并计算整体变动率（change_ratio，取值 0.0 到 1.0）。

输出格式要求：
请严格输出一个合法 JSON 对象，格式如下：
{
  "keep": [
    {"tag": "保留标签名称", "description": "说明"}
  ],
  "add": [
    {"tag": "新增标签名称", "description": "说明"}
  ],
  "remove": [
    "移除标签名称"
  ],
  "change_ratio": 0.25
}
禁止输出除 JSON 以外的任何文本。"""

BATCH_CLASSIFY_SYSTEM_PROMPT = """你是一个严格、敏锐的投资研究资讯智能分类器。
你的任务是根据给定的用户兴趣标签列表，评估一批新闻资讯与用户关注领域的相关性。

评估规则：
1. 仅对与用户关注标签存在明确行业关联、上下游供应链影响或重大政策/订单催化的条目进行打标。
2. 泛泛的娱乐八卦、社会无关新闻、或者与标签关系微弱的条目，请直接忽略，不要出现在输出列表中。
3. 严格使用提供的 tag_id，不得自行捏造标签 ID。
4. score 表示相关度置信度（取值范围 0.0 到 1.0）。

输出格式要求：
请输出一个合法 JSON 数组，仅包含符合关注条件的新闻打标结果。如果都不符合，输出空数组 []。
[
  {
    "id": 101,
    "tag_id": 1,
    "score": 0.95
  }
]
禁止输出除 JSON 数组以外的任何解释性文本。"""


def get_provider_identity(cfg: dict[str, Any] | None) -> str:
    """提取安全的 Provider 标识符，绝不包含 API Key 等凭证信息。"""
    if not cfg or not cfg.get("provider"):
        return "unknown"
    prov = str(cfg["provider"]).strip()
    model = str(cfg.get("model") or "default").strip()
    return f"{prov}:{model}"


def _invoke_llm_text(
    cfg: dict[str, Any] | None,
    messages: list[dict[str, str]],
    model_runner: Callable[[Any, list[dict[str, str]]], str] | None = None,
) -> str:
    """统一模型调用，收集完整响应文本。

    安全与路由原则：
    1. model_runner 仅用于自动化测试与 fixture 注入。
    2. 生产路径严禁隐式 fallback 到 cli-codex；若前端未提供有效 cfg，显式抛出 AI_CONFIG_REQUIRED。
    3. 严格执行所选 provider：cli-codex 走 Agent Runtime，openai-compatible 校验必填字段。
    4. 绝不将 apiKey / 凭证泄露至异常消息或日志中。
    """
    if model_runner is not None:
        return model_runner(cfg, messages)

    if not cfg or not cfg.get("provider"):
        raise ValueError("AI_CONFIG_REQUIRED: 尚未提供有效 AI 配置，请先在前端配置模型接入")

    provider = str(cfg["provider"]).strip()
    if provider not in ("cli-codex", "openai-compatible"):
        raise ValueError(f"UNSUPPORTED_AI_PROVIDER: 不受支持的 AI Provider '{provider}'")

    effective_cfg = dict(cfg)
    if provider == "openai-compatible":
        if not effective_cfg.get("baseURL") or not effective_cfg.get("apiKey") or not effective_cfg.get("model"):
            raise ValueError("AI_CONFIG_INCOMPLETE: API Compatible 模式需要完整的 baseURL、apiKey 和 model 配置")
    elif provider == "cli-codex":
        if not effective_cfg.get("model"):
            effective_cfg["model"] = "gpt-5-codex"

    parts: list[str] = []
    for event in chat.stream_messages(effective_cfg, messages, use_tools=False):
        if not isinstance(event, dict):
            continue
        etype = event.get("type")
        if etype == "delta":
            piece = event.get("text")
            if piece:
                parts.append(str(piece))
        elif etype == "error":
            err_msg = str(event.get("error") or event.get("message") or "AI 调用返回错误")
            raise RuntimeError(err_msg)
        elif etype == "done":
            break
    return "".join(parts)


def _extract_json_block(text: str) -> str:
    raw = text.strip()
    if raw.startswith("```"):
        first_newline = raw.find("\n")
        last_block = raw.rfind("```")
        if first_newline != -1 and last_block != -1 and last_block > first_newline:
            raw = raw[first_newline + 1:last_block].strip()

    if raw.startswith("[") and raw.endswith("]"):
        return raw
    if raw.startswith("{") and raw.endswith("}"):
        return raw

    bracket_match = re.search(r"\[[\s\S]*\]", raw)
    if bracket_match:
        return bracket_match.group(0)

    brace_match = re.search(r"\{[\s\S]*\}", raw)
    if brace_match:
        return brace_match.group(0)

    return raw


def extract_interest_tags(
    interests_text: str,
    cfg: dict[str, Any] | None = None,
    model_runner: Callable[[Any, list[dict[str, str]]], str] | None = None,
) -> list[dict[str, Any]]:
    """阶段 A：从自然语言兴趣描述中提取结构化分类标签。

    Fail-closed：解析失败时抛出 ValueError，不返回损坏数据。
    """
    clean_text = interests_text.strip()
    if not clean_text:
        raise ValueError("兴趣描述文本为空")

    messages = [
        {"role": "system", "content": EXTRACT_TAGS_SYSTEM_PROMPT},
        {"role": "user", "content": f"用户的兴趣描述如下：\n\n{clean_text}\n\n请提取出新闻分类标签，输出严格 JSON。"},
    ]

    raw_response = _invoke_llm_text(cfg, messages, model_runner)
    json_str = _extract_json_block(raw_response)
    try:
        data = json.loads(json_str)
    except Exception as exc:
        raise ValueError(f"标签提取响应 JSON 解析失败: {exc}\n原始响应: {raw_response[:200]}") from exc

    raw_tags = data.get("tags") if isinstance(data, dict) else data
    if not isinstance(raw_tags, list) or not raw_tags:
        raise ValueError(f"提取结果中未找到有效 tags 列表: {raw_response[:200]}")

    validated_tags: list[dict[str, Any]] = []
    for idx, t in enumerate(raw_tags, start=1):
        if not isinstance(t, dict):
            continue
        tag_name = str(t.get("tag") or t.get("name") or "").strip()
        desc = str(t.get("description") or "").strip()
        if tag_name:
            validated_tags.append({
                "id": idx,
                "tag": tag_name,
                "description": desc,
            })

    if not validated_tags:
        raise ValueError("未能提取出任何有效标签")

    return validated_tags


def update_interest_tags(
    old_tags: list[dict[str, Any]],
    new_interests_text: str,
    cfg: dict[str, Any] | None = None,
    model_runner: Callable[[Any, list[dict[str, str]]], str] | None = None,
) -> dict[str, Any]:
    """阶段 A'：对比旧标签集与新兴趣描述，给出增量更新方案与变化度。

    返回格式：
    {
      "keep": [{"tag": str, "description": str}],
      "add": [{"tag": str, "description": str}],
      "remove": [str],
      "change_ratio": float,
      "new_tags": [{"id": int, "tag": str, "description": str}]
    }
    """
    clean_text = new_interests_text.strip()
    if not clean_text:
        raise ValueError("新兴趣描述文本为空")

    old_tags_json = json.dumps(
        [{"tag": t.get("tag"), "description": t.get("description", "")} for t in old_tags],
        ensure_ascii=False,
        indent=2,
    )

    messages = [
        {"role": "system", "content": UPDATE_TAGS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"## 当前标签集\n\n{old_tags_json}\n\n## 新的兴趣描述\n\n{clean_text}\n\n请对比并返回标签更新方案（keep / add / remove / change_ratio）。",
        },
    ]

    raw_response = _invoke_llm_text(cfg, messages, model_runner)
    json_str = _extract_json_block(raw_response)
    try:
        data = json.loads(json_str)
    except Exception as exc:
        raise ValueError(f"更新方案 JSON 解析失败: {exc}\n原始响应: {raw_response[:200]}") from exc

    if not isinstance(data, dict):
        raise ValueError("更新方案格式错误，预期 JSON 对象")

    keep = data.get("keep") or []
    add = data.get("add") or []
    remove = data.get("remove") or []
    raw_ratio = data.get("change_ratio")

    try:
        change_ratio = float(raw_ratio if raw_ratio is not None else 0.5)
    except (ValueError, TypeError):
        change_ratio = 0.5
    change_ratio = max(0.0, min(1.0, change_ratio))

    new_tags: list[dict[str, Any]] = []
    idx = 1
    for k in keep:
        t_name = str(k.get("tag") if isinstance(k, dict) else k).strip()
        t_desc = str(k.get("description") if isinstance(k, dict) else "").strip()
        if t_name:
            new_tags.append({"id": idx, "tag": t_name, "description": t_desc})
            idx += 1

    for a in add:
        t_name = str(a.get("tag") if isinstance(a, dict) else a).strip()
        t_desc = str(a.get("description") if isinstance(a, dict) else "").strip()
        if t_name and not any(nt["tag"] == t_name for nt in new_tags):
            new_tags.append({"id": idx, "tag": t_name, "description": t_desc})
            idx += 1

    return {
        "keep": keep,
        "add": add,
        "remove": remove,
        "change_ratio": change_ratio,
        "new_tags": new_tags,
    }


def classify_items_batch(
    items: list[dict[str, Any]],
    tags: list[dict[str, Any]],
    interests_text: str = "",
    cfg: dict[str, Any] | None = None,
    batch_size: int = 15,
    model_runner: Callable[[Any, list[dict[str, str]]], str] | None = None,
) -> tuple[list[dict[str, Any]], list[int], list[int]]:
    """阶段 B：批量对新闻资讯进行标签相关性评估。

    返回：(succeeded, not_relevant_ids, failed_item_ids)
    - succeeded: 命中的条目列表，每个包含 item_id, primary_tag, relevance_score
    - not_relevant_ids: 在成功的批次中，被 AI 判定不匹配或遗漏的条目 ID（用于写入 NOT_RELEVANT 分析缓存）
    - failed_item_ids: 调用异常失败的批次条目 ID（可重试，绝不造假）

    精度防护：
    - score 为 0.0 时严格保留 0.0，绝不因 falsy 判断转换为 0.5。
    - 严格隔离不可信热榜正文，防止提示词注入。
    """
    if not items or not tags:
        return [], [], []

    tag_by_id = {int(t["id"]): str(t["tag"]) for t in tags if "id" in t and "tag" in t}
    tags_prompt = "\n".join(
        f"- ID: {t['id']}, 标签: {t['tag']}, 说明: {t.get('description', '')}"
        for t in tags
    )

    succeeded: list[dict[str, Any]] = []
    not_relevant_ids: list[int] = []
    failed_item_ids: list[int] = []

    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        batch_id_to_item = {int(b["item_id"]): b for b in batch}

        items_payload = []
        for b in batch:
            items_payload.append({
                "id": int(b["item_id"]),
                "title": str(b.get("title") or "").strip(),
                "summary": str(b.get("summary") or "").strip()[:180],
            })

        user_content = (
            f"## 待分类新闻列表（共 {len(items_payload)} 条）\n\n"
            f"```json\n{json.dumps(items_payload, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## 个人关注分类标签\n{tags_prompt}\n\n"
            f"请仔细甄别上述新闻。仅返回有明确关联价值的新闻打标结果（JSON 数组）。"
            f"无关新闻不要输出。示例格式：\n"
            '[{"id": 1, "tag_id": 1, "score": 0.9}]'
        )

        messages = [
            {"role": "system", "content": BATCH_CLASSIFY_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        try:
            raw_response = _invoke_llm_text(cfg, messages, model_runner)
            json_str = _extract_json_block(raw_response)
            parsed_results = json.loads(json_str)
            if not isinstance(parsed_results, list):
                raise ValueError(f"响应格式错误，预期数组: {raw_response[:200]}")

            # 收集每个 item 的最高分分类
            best_by_id: dict[int, dict[str, Any]] = {}
            for item_res in parsed_results:
                if not isinstance(item_res, dict):
                    continue
                item_id = item_res.get("id")
                tag_id = item_res.get("tag_id")
                raw_score = item_res.get("score")
                if raw_score is None:
                    score = 0.5
                else:
                    try:
                        score = float(raw_score)
                    except (ValueError, TypeError):
                        score = 0.5

                if item_id not in batch_id_to_item:
                    continue
                if tag_id not in tag_by_id:
                    continue
                tag_name = tag_by_id[tag_id]

                if score > 1.0:
                    score = score / 100.0
                score = max(0.0, min(1.0, score))

                if item_id not in best_by_id or score > best_by_id[item_id]["relevance_score"]:
                    best_by_id[item_id] = {
                        "item_id": item_id,
                        "primary_tag": tag_name,
                        "relevance_score": score,
                    }

            matched_in_batch = set(best_by_id.keys())
            for item_id, res in best_by_id.items():
                succeeded.append(res)

            # 该批次中成功评估但未匹配的项判定为 NOT_RELEVANT
            for b in batch:
                bid = int(b["item_id"])
                if bid not in matched_in_batch:
                    not_relevant_ids.append(bid)

        except Exception as exc:
            logger.warning("AI 分类批次失败 (%s 条): %s", len(batch), exc)
            for b in batch:
                failed_item_ids.append(int(b["item_id"]))

    return succeeded, not_relevant_ids, failed_item_ids

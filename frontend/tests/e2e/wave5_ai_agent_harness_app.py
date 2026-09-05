"""FastAPI harness for Native Intel Wave 5 AI Analysis and Agent Tools browser E2E tests."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_backend_dir = str(Path(__file__).resolve().parents[3] / "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from fastapi import FastAPI
from fastapi.responses import JSONResponse

import native_intel_ai as ai
import native_intel_router
import native_intel_service as service
import native_intel_store as store

DB_PATH = os.environ.get("VIBE_NATIVE_INTEL_DB", str(Path(__file__).resolve().parents[3] / "vibe_data" / "native_intel.sqlite3"))
now_dt = datetime.now(timezone.utc)
NOW = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
ONE_DAY_AGO = (now_dt - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

app = FastAPI()
app.include_router(native_intel_router.router)

simulate_error = False


def _mock_llm_stream(cfg, messages, *, use_tools=False):
    global simulate_error
    if simulate_error:
        yield {"type": "error", "message": "AI Provider simulated network failure"}
        return

    content = ""
    for m in messages:
        c = m.get("content", "")
        if c:
            content += c + "\n"

    # 1. Single Translation
    if "你是一名专业翻译" in content:
        if "Data center liquid cooling demand rises" in content:
            yield {"type": "delta", "text": "数据中心液冷需求持续攀升"}
        else:
            yield {"type": "delta", "text": "【AI 翻译】" + content[:30]}
        yield {"type": "done"}
        return

    # 2. Batch Translation
    if "你是一名专业批量翻译助手" in content:
        yield {"type": "delta", "text": "[1] 标题阿尔法\n[2] 数据中心液冷需求持续攀升\n[3] 标题伽马"}
        yield {"type": "done"}
        return

    # 3. Entity extraction
    if "实体识别专家" in content or "ENTITY_EXTRACTION" in content or "实体提取分析师" in content or "提取实体与概念" in content:
        res = [
            {"type": "company", "name": "中芯国际", "evidence": "晶圆代工龙头", "confidence": 0.95},
            {"type": "concept", "name": "液冷技术", "evidence": "高密算力散热支撑", "confidence": 0.90},
            {"type": "industry", "name": "半导体", "evidence": "硬科技核心赛道", "confidence": 0.88},
        ]
        yield {"type": "delta", "text": "```json\n" + json.dumps(res, ensure_ascii=False) + "\n```"}
        yield {"type": "done"}
        return

    # 4. Sentiment analysis
    if "舆情风向与争议分析师" in content or "SENTIMENT" in content or "舆论倾向与争议分析" in content:
        res = {
            "sentiment": "positive",
            "controversy": False,
            "confidence": 0.85,
            "reasoning": "行业景气上行，核心技术获订单支撑。"
        }
        yield {"type": "delta", "text": "```json\n" + json.dumps(res, ensure_ascii=False) + "\n```"}
        yield {"type": "done"}
        return

    # 4. Deep Analysis (Default)
    analysis_res = {
        "core_trends": [
            {
                "trend_name": "AI算力与液冷渗透率提速",
                "significance": "数据中心能耗指标收紧，液冷成为智算中心刚需标配。",
                "confidence": 0.92,
                "driver": "超节点AI集群功耗突破千瓦，传统风冷面临物理极限。",
                "related_items": [1, 2],
                "sources": ["cls-hot", "weibo-tech"]
            }
        ],
        "sentiment_controversy": {
            "overall_sentiment": "positive",
            "score": 0.78,
            "bullish_signals": ["龙头芯片厂获得大规模算力集群订单", "液冷CDU量产交付加速"],
            "bearish_signals": ["部分元器件存在供应偏紧交期延长风险"],
            "controversy_points": []
        },
        "signals": [
            {
                "signal_name": "高密算力CDU关键部件扩产",
                "signal_type": "weak_signal",
                "evidence": "上游快讯显示快换接头与冷却液供应链正在扩增产能备货。",
                "impact": "可能带动液冷产业链在下半年业绩提前兑现。"
            }
        ],
        "rss_insights": [
            {
                "source_id": "rss-semiconductor",
                "insight": "行业深度文章持续探讨先进制程与先进封装协同演进。"
            }
        ],
        "outlook_strategy": {
            "short_term_outlook": "短期关注算力链条中液冷和芯片关键环节交付节奏。",
            "medium_term_outlook": "中期关注商业化落地与下游云厂商资本开支指引。",
            "risk_factors": ["宏观宏观预期变动", "海外供应链政策波动"],
            "observation_suggestions": ["跟踪周末产业供应链调研动态", "关注行业展会订单线索"]
        },
        "standalone_summaries": [
            {
                "source_id": "standalone-exclusive",
                "summary": "独家专栏强调算力底层基础设施自主可控长期价值。"
            }
        ]
    }
    yield {"type": "delta", "text": "```json\n" + json.dumps(analysis_res, ensure_ascii=False) + "\n```"}
    yield {"type": "done"}


import chat
chat.stream_messages = _mock_llm_stream


@app.on_event("startup")
def setup():
    store.initialize_store(DB_PATH)

    # Hotlist source
    store.upsert_sources(
        [
            {
                "source_id": "cls-hot",
                "name": "财联社热门",
                "hint": "macro",
                "url": "https://cls.cn/hot",
                "source_type": "hotlist",
                "has_real_rank": True,
                "enabled": True,
            },
            {
                "source_id": "weibo-tech",
                "name": "科技热搜",
                "hint": "tech",
                "url": "https://weibo.com/tech",
                "source_type": "hotlist",
                "has_real_rank": True,
                "enabled": True,
            }
        ],
        DB_PATH,
    )

    # RSS source
    store.insert_user_source(
        source_id="rss-semiconductor",
        name="半导体行业快讯",
        url="https://example.com/semi.xml",
        hint="tech",
        enabled=True,
        max_age_days=None,
        db_path=DB_PATH,
    )

    # Seed observations
    run_id = "run-wave5-init"
    store.start_run(run_id, "fixture", 3, DB_PATH)

    obs = [
        ("cls-hot", "k-cooling-1", "https://example.com/cooling", "Data center liquid cooling demand rises", "Hyperscalers ramp up liquid cooling deployment for next-gen AI clusters.", 1, True),
        ("weibo-tech", "k-chip-2", "https://example.com/chip", "国产先进芯片封装技术取得新进展", "某半导体晶圆厂宣布新一代算力芯片完成封测验证。", 2, True),
        ("rss-semiconductor", "k-rss-3", "https://example.com/rss3", "全球算力供应链观察：液冷CDU与高带宽存储协同", "深度分析液冷产业渗透率与产业链各环节关键厂商。", None, False),
    ]

    for sid, ikey, url, title, summary, rank, has_rank in obs:
        it = {
            "item_key": f"{sid}:{ikey}",
            "canonical_url": url,
            "url": url,
            "title": title,
            "title_key": title,
            "summary": summary,
            "hint": "tech",
            "published_at": NOW,
            "published_ts": int(now_dt.timestamp()),
            "rank": rank,
        }
        store.upsert_observation(run_id, sid, it, observed_at=NOW, has_real_rank=has_rank, db_path=DB_PATH)
        store.record_source_run(run_id, sid, status=store.SOURCE_RUN_OK, item_count=1, db_path=DB_PATH)

    store.finish_run(run_id, status=store.RUN_STATUS_OK, source_ok=3, source_failed=0, item_seen=3, item_new=3, db_path=DB_PATH)

    # Enable Wave 5 in config initially
    store.update_native_intel_config({
        "regions_enabled": {
            "hotlist": True,
            "rss": True,
            "standalone": True,
            "new_items": False,
            "ai_analysis": True,
        },
        "region_order": ["ai_analysis", "hotlist", "rss", "standalone"],
        "ai_analysis_enabled": True,
        "ai_analysis_provider": "cli-codex",
        "ai_analysis_model": "gpt-5-codex",
        "ai_translation_enabled": True,
    }, DB_PATH)


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.post("/__test/simulate-ai-error")
def set_simulate_error(enable: bool = True):
    global simulate_error
    simulate_error = enable
    return {"simulate_error": simulate_error}


@app.get("/api/native-intel/status")
def get_status():
    return service.get_status(DB_PATH)

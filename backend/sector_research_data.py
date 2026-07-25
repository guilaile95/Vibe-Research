"""板块研究数据服务 —— 复用 a-stock-data 能力，为板块研究工作台提供：
- 行业研报发现（eastmoney_industry_reports）
- 个股研报发现（eastmoney_reports）
- 研报归一化 / 相关性评分
- 板块动态数据（一致预期 / 公告 / 新闻）
- 板块数据源注册表（关键词 / 代表公司 / 回溯天数 / 动态面板）

不重新实现东财接口；全部委托 backend/astock.py。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import astock

# 单次发现返回上限：必须 ≤ 服务端缓存容量，保证「可见即可导入」。
MAX_DISCOVERY_RESULTS = 300

# ---------------------------------------------------------------------------
# PCB 代表公司（代码经校验，禁止混用）
# ---------------------------------------------------------------------------

PCB_COMPANY_CODES = {
    "002463": "沪电股份",
    "002916": "深南电路",
    "300476": "胜宏科技",
    "603228": "景旺电子",
    "600183": "生益科技",
}


# ---------------------------------------------------------------------------
# 板块数据源注册表（第一轮只要求 PCB 真实可用）
# ---------------------------------------------------------------------------


@dataclass
class SectorDataSource:
    """单个板块的研报/数据源配置。"""

    key: str
    label: str
    report_keywords: list[str] = field(default_factory=list)
    representative_company_codes: list[str] = field(default_factory=list)
    representative_companies: dict[str, str] = field(default_factory=dict)
    report_lookback_days: int = 365
    dynamic_panels: list[str] = field(default_factory=list)


# PCB 数据源：关键词覆盖高速 PCB / 覆铜板 / HDI / 高速材料等。
PCB_SOURCES = SectorDataSource(
    key="pcb",
    label="PCB（印制电路板）",
    report_keywords=[
        "PCB", "印制电路板", "覆铜板", "高速PCB", "AI服务器PCB", "服务器PCB",
        "交换机PCB", "HDI", "高多层板", "背板", "正交背板", "铜中板",
        "低轮廓铜箔", "112G", "224G", "448G", "覆铜板材料",
    ],
    representative_company_codes=["002463", "002916", "300476", "603228", "600183"],
    representative_companies={
        "002463": "沪电股份",
        "002916": "深南电路",
        "300476": "胜宏科技",
        "603228": "景旺电子",
        "600183": "生益科技",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# HUMANOID 数据源
HUMANOID_SOURCES = SectorDataSource(
    key="humanoid",
    label="人形机器人",
    report_keywords=[
        "人形机器人", "具身智能", "谐波减速器", "行星滚柱丝杠", "空心杯电机",
        "灵巧手", "无框力矩电机", "伺服驱动器", "六维力传感器",
    ],
    representative_company_codes=["002050", "601689", "002896", "603728", "300124", "688017"],
    representative_companies={
        "002050": "三花智控",
        "601689": "拓普集团",
        "002896": "中大力德",
        "603728": "鸣志电器",
        "300124": "汇川技术",
        "688017": "绿的谐波",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# AI-COMPUTING 数据源
AICOMPUTING_SOURCES = SectorDataSource(
    key="ai-computing",
    label="AI算力",
    report_keywords=[
        "AI算力", "AI服务器", "智算中心", "算力芯片", "无损网络",
        "冷板液冷", "浸没液冷", "800G交换机", "NVLink", "液冷服务器",
    ],
    representative_company_codes=["000977", "603019", "000938", "601138", "688256", "688041"],
    representative_companies={
        "000977": "浪潮信息",
        "603019": "中科曙光",
        "000938": "紫光股份",
        "601138": "工业富联",
        "688256": "寒武纪",
        "688041": "海光信息",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# HBM 数据源
HBM_SOURCES = SectorDataSource(
    key="hbm",
    label="HBM（高带宽内存）",
    report_keywords=[
        "HBM", "高带宽内存", "HBM3e", "HBM4", "TSV", "硅通孔",
        "MR-MUF", "颗粒塑封料", "GMC", "2.5D", "3D", "CoWoS",
    ],
    representative_company_codes=["002409", "300475", "600641", "688535", "600584", "002156"],
    representative_companies={
        "002409": "雅克科技",
        "300475": "香农芯创",
        "600641": "太极实业",
        "688535": "华海诚科",
        "600584": "长电科技",
        "002156": "通富微电",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# CPO 数据源
CPO_SOURCES = SectorDataSource(
    key="cpo",
    label="光互联与CPO",
    report_keywords=[
        "CPO", "共封装光学", "光模块", "800G光模块", "1.6T光模块",
        "硅光", "LPO", "EML", "CW激光器", "光芯片", "FA光纤阵列",
    ],
    representative_company_codes=["300308", "300502", "300394", "688498", "002281", "000988"],
    representative_companies={
        "300308": "中际旭创",
        "300502": "新易盛",
        "300394": "天孚通信",
        "688498": "源杰科技",
        "002281": "光迅科技",
        "000988": "华工科技",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# SEMICONDUCTOR 数据源
SEMICONDUCTOR_SOURCES = SectorDataSource(
    key="semiconductor",
    label="半导体国产替代",
    report_keywords=[
        "半导体", "晶圆制造", "刻蚀机", "薄膜沉积", "CMP", "光刻机",
        "EDA", "光刻胶", "溅射靶材", "抛光液", "电子特气", "半导体材料",
        "半导体设备", "国产替代", "中芯国际", "北方华创", "中微公司",
    ],
    representative_company_codes=["688981", "002371", "688012", "688019"],
    representative_companies={
        "688981": "中芯国际",
        "002371": "北方华创",
        "688012": "中微公司",
        "688019": "安集科技",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# SMART-DRIVING 数据源
SMARTDRIVING_SOURCES = SectorDataSource(
    key="smart-driving",
    label="智能驾驶",
    report_keywords=[
        "智能驾驶", "自动驾驶", "ADAS", "域控制器", "线控制动",
        "激光雷达", "毫米波雷达", "车载摄像头", "高精地图", "V2X",
        "智能座舱", "HUD", "德赛西威", "经纬恒润",
    ],
    representative_company_codes=["002920", "688326", "300496", "603596", "002284"],
    representative_companies={
        "002920": "德赛西威",
        "688326": "经纬恒润",
        "300496": "中科创达",
        "603596": "伯特利",
        "002284": "亚太股份",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# SOLID-STATE-BATTERY 数据源
SSBATTERY_SOURCES = SectorDataSource(
    key="solid-state-battery",
    label="固态电池",
    report_keywords=[
        "固态电池", "半固态电池", "硫化物电解质", "氧化物电解质",
        "锂金属负极", "硅碳负极", "电解液", "锂盐", "LiFSI",
        "宁德时代", "国轩高科", "赣锋锂业", "当升科技",
    ],
    representative_company_codes=["300750", "002074", "002460", "300073", "002709", "300037", "300450"],
    representative_companies={
        "300750": "宁德时代",
        "002074": "国轩高科",
        "002460": "赣锋锂业",
        "300073": "当升科技",
        "002709": "天赐材料",
        "300037": "新宙邦",
        "300450": "先导智能",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# LOW-ALTITUDE 数据源
LOWALTITUDE_SOURCES = SectorDataSource(
    key="low-altitude",
    label="低空经济",
    report_keywords=[
        "低空经济", "eVTOL", "通航", "无人机", "空中交通",
        "直升机", "飞行汽车", "空管系统", "航空运营",
        "亿航", "峰飞", "中直股份", "中信海直",
    ],
    representative_company_codes=["600038", "000099", "688631", "301091", "002085"],
    representative_companies={
        "600038": "中直股份",
        "000099": "中信海直",
        "688631": "莱斯信息",
        "301091": "深城交",
        "002085": "万丰奥威",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# INNOVATIVE-DRUG 数据源
INNOVATIVEDRUG_SOURCES = SectorDataSource(
    key="innovative-drug",
    label="创新药",
    report_keywords=[
        "创新药", "ADC", "双抗", "PD-1", "License-out", "出海",
        "临床管线", "靶点", "CXO", "CRDMO", "恒瑞医药", "百济神州",
        "药明康德", "凯莱英", "荣昌生物",
    ],
    representative_company_codes=["600276", "603259", "688235", "688331", "002821"],
    representative_companies={
        "600276": "恒瑞医药",
        "603259": "药明康德",
        "688235": "百济神州",
        "688331": "荣昌生物",
        "002821": "凯莱英",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# FUSION 数据源
FUSION_SOURCES = SectorDataSource(
    key="fusion",
    label="可控核聚变",
    report_keywords=[
        "可控核聚变", "核聚变", "托卡马克", "磁约束", "超导磁体",
        "第一壁", "偏滤器", "等离子体", "ITER", "聚变堆",
        "西部超导", "联创光电", "安泰科技", "国光电气",
    ],
    representative_company_codes=["600363", "000969", "688776", "688122", "601611"],
    representative_companies={
        "600363": "联创光电",
        "000969": "安泰科技",
        "688776": "国光电气",
        "688122": "西部超导",
        "601611": "中国核建",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# DEFENSE 数据源
DEFENSE_SOURCES = SectorDataSource(
    key="defense",
    label="军工",
    report_keywords=[
        "军工", "国防军工", "航空发动机", "军工信息化", "军用航空",
        "舰船", "航天装备", "主机厂", "航发动力", "中航沈飞",
        "中国船舶", "中航光电", "航天电器",
    ],
    representative_company_codes=["600760", "600150", "002025", "002179", "600893", "688563"],
    representative_companies={
        "600760": "中航沈飞",
        "600150": "中国船舶",
        "002025": "航天电器",
        "002179": "中航光电",
        "600893": "航发动力",
        "688563": "航材股份",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# BUSINESS-SPACE 数据源
BUSINESSSPACE_SOURCES = SectorDataSource(
    key="business-space",
    label="商业航天",
    report_keywords=[
        "商业航天", "运载火箭", "可复用火箭", "卫星制造", "卫星互联网",
        "星座", "测控", "航天电子", "中国卫星", "航天宏图",
        "银河电子", "欧比特", "天银机电",
    ],
    representative_company_codes=["002519", "688066", "300342", "300053", "600118", "600879"],
    representative_companies={
        "002519": "银河电子",
        "688066": "航天宏图",
        "300342": "天银机电",
        "300053": "欧比特",
        "600118": "中国卫星",
        "600879": "航天电子",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# POWER-GRID 数据源
POWERGRID_SOURCES = SectorDataSource(
    key="power-grid",
    label="电网与特高压",
    report_keywords=[
        "特高压", "电网", "输配电", "柔直", "变压器",
        "组合电器", "智能电网", "新能源接入", "国电南瑞",
        "许继电气", "特变电工", "思源电气", "平高电气",
    ],
    representative_company_codes=["600406", "000400", "600089", "002028", "600312"],
    representative_companies={
        "600406": "国电南瑞",
        "000400": "许继电气",
        "600089": "特变电工",
        "002028": "思源电气",
        "600312": "平高电气",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# AI-APPLICATION 数据源
AIAPPLICATION_SOURCES = SectorDataSource(
    key="ai-application",
    label="AI应用",
    report_keywords=[
        "AI应用", "大模型应用", "Agent", "办公AI", "编程Agent",
        "多模态", "垂直大模型", "AI软件", "科大讯飞", "金山办公",
        "同花顺", "拓尔思", "昆仑万维",
    ],
    representative_company_codes=["002230", "688111", "300033", "300229", "300418"],
    representative_companies={
        "002230": "科大讯飞",
        "688111": "金山办公",
        "300033": "同花顺",
        "300229": "拓尔思",
        "300418": "昆仑万维",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# AI-HARDWARE 数据源
AIHARDWARE_SOURCES = SectorDataSource(
    key="ai-hardware",
    label="AI硬件",
    report_keywords=[
        "AI硬件", "AI眼镜", "端侧AI", "端侧芯片", "可穿戴",
        "智能家居", "边缘计算", "AIoT", "歌尔股份", "瑞芯微",
        "全志科技", "科大讯飞",
    ],
    representative_company_codes=["002241", "603893", "300458", "002230"],
    representative_companies={
        "002241": "歌尔股份",
        "603893": "瑞芯微",
        "300458": "全志科技",
        "002230": "科大讯飞",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# ENERGY-STORAGE 数据源
ENERGYSTORAGE_SOURCES = SectorDataSource(
    key="energy-storage",
    label="储能",
    report_keywords=[
        "储能", "电化学储能", "新型储能", "储能系统", "PCS",
        "变流器", "电网侧储能", "储能集成", "宁德时代", "阳光电源",
        "比亚迪", "科士达", "盛弘股份",
    ],
    representative_company_codes=["300750", "300274", "002594", "002518", "300693"],
    representative_companies={
        "300750": "宁德时代",
        "300274": "阳光电源",
        "002594": "比亚迪",
        "002518": "科士达",
        "300693": "盛弘股份",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# DATA-ELEMENT 数据源
DATAELEMENT_SOURCES = SectorDataSource(
    key="data-element",
    label="数据要素",
    report_keywords=[
        "数据要素", "数据确权", "数据交易", "数据交易所", "公共数据",
        "数据安全", "数据资产", "数据流通", "易华录", "人民网",
        "上海钢联", "云赛智联", "深桑达",
    ],
    representative_company_codes=["300212", "603000", "300226", "600602", "000032"],
    representative_companies={
        "300212": "易华录",
        "603000": "人民网",
        "300226": "上海钢联",
        "600602": "云赛智联",
        "000032": "深桑达A",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# RESOURCES 数据源
RESOURCES_SOURCES = SectorDataSource(
    key="resources",
    label="资源卡口",
    report_keywords=[
        "稀土", "锗", "铟", "镓", "钨", "钼", "锂", "钴", "镍",
        "关键矿产", "战略资源", "北方稀土", "中国稀土",
        "云南锗业", "华友钴业", "株冶集团",
    ],
    representative_company_codes=["600111", "000831", "002428", "600961", "603799"],
    representative_companies={
        "600111": "北方稀土",
        "000831": "中国稀土",
        "002428": "云南锗业",
        "600961": "株冶集团",
        "603799": "华友钴业",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# AI-PHARMA 数据源
AIPHARMA_SOURCES = SectorDataSource(
    key="ai-pharma",
    label="生物医药",
    report_keywords=[
        "生物医药", "AI制药", "基因治疗", "细胞治疗", "CXO",
        "医疗器械", "生物技术", "药明康德", "泰格医药",
        "华大基因", "迈瑞医疗", "联影医疗",
    ],
    representative_company_codes=["603259", "300347", "300676", "300760", "688271"],
    representative_companies={
        "603259": "药明康德",
        "300347": "泰格医药",
        "300676": "华大基因",
        "300760": "迈瑞医疗",
        "688271": "联影医疗",
    },
    report_lookback_days=365,
    dynamic_panels=["profit_forecast", "announcements", "individual_info"],
)

# 注册表：key -> SectorDataSource。
SECTOR_SOURCES: dict[str, SectorDataSource] = {
    PCB_SOURCES.key: PCB_SOURCES,
    HUMANOID_SOURCES.key: HUMANOID_SOURCES,
    AICOMPUTING_SOURCES.key: AICOMPUTING_SOURCES,
    HBM_SOURCES.key: HBM_SOURCES,
    CPO_SOURCES.key: CPO_SOURCES,
    SEMICONDUCTOR_SOURCES.key: SEMICONDUCTOR_SOURCES,
    SMARTDRIVING_SOURCES.key: SMARTDRIVING_SOURCES,
    SSBATTERY_SOURCES.key: SSBATTERY_SOURCES,
    LOWALTITUDE_SOURCES.key: LOWALTITUDE_SOURCES,
    INNOVATIVEDRUG_SOURCES.key: INNOVATIVEDRUG_SOURCES,
    FUSION_SOURCES.key: FUSION_SOURCES,
    DEFENSE_SOURCES.key: DEFENSE_SOURCES,
    BUSINESSSPACE_SOURCES.key: BUSINESSSPACE_SOURCES,
    POWERGRID_SOURCES.key: POWERGRID_SOURCES,
    AIAPPLICATION_SOURCES.key: AIAPPLICATION_SOURCES,
    AIHARDWARE_SOURCES.key: AIHARDWARE_SOURCES,
    ENERGYSTORAGE_SOURCES.key: ENERGYSTORAGE_SOURCES,
    DATAELEMENT_SOURCES.key: DATAELEMENT_SOURCES,
    RESOURCES_SOURCES.key: RESOURCES_SOURCES,
    AIPHARMA_SOURCES.key: AIPHARMA_SOURCES,
}


def get_sector_source(key: str) -> SectorDataSource | None:
    return SECTOR_SOURCES.get(key)


def list_sector_source_keys() -> list[str]:
    return list(SECTOR_SOURCES.keys())


# ---------------------------------------------------------------------------
# 研报归一化
# ---------------------------------------------------------------------------

# 东财 reportapi 字段可能是 camelCase 或 snake_case：
#   infoCode / info_code, orgName / orgSName / org_name,
#   publishDate / publish_date, industryName / industry_name,
#   stockCode / code / rcode, stockName / companyName / ssecName,
#   rating / emRating
# 字段缺失时使用 null，不得猜测。

_PDF_HOST_ALLOW = ("pdf.dfcfw.com", "pdfcdn.eastmoney.com")


def _safe_strip(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _first_present(raw: dict, *keys: str) -> str | None:
    """按键顺序取第一个非空字段；不猜测。"""
    for k in keys:
        v = _safe_strip(raw.get(k))
        if v is not None:
            return v
    return None


def normalize_report(raw: dict) -> dict:
    """把东财原始研报 dict 归一化为统一研报结构。缺失字段用 null，不猜测。"""
    info_code = _first_present(raw, "infoCode", "info_code")
    institution = _first_present(raw, "orgName", "orgSName", "org_name")
    publish_date = _first_present(raw, "publishDate", "publish_date")
    industry_name = _first_present(raw, "industryName", "industry_name")
    company_code = _first_present(raw, "stockCode", "code", "rcode")
    company_name = _first_present(raw, "stockName", "companyName", "ssecName")
    rating = _first_present(raw, "rating", "emRating")
    pdf_url = astock.pdf_url(info_code) if info_code else None

    if company_code:
        report_scope = "company"
    elif industry_name:
        report_scope = "industry"
    else:
        report_scope = None

    return {
        "source_provider": "eastmoney",
        "external_id": info_code,
        "info_code": info_code,
        "title": _safe_strip(raw.get("title")),
        "institution": institution,
        "publish_date": publish_date,
        "industry_name": industry_name,
        "company_code": company_code,
        "company_name": company_name,
        "rating": rating,
        "pdf_url": pdf_url,
        "report_scope": report_scope,
        "report_type": "brokerage",
        "matched_keywords": [],
        "relevance_score": 0,
    }


# 研报相关性评分：标题命中关键词 + 公司代表 + 评级。

_RATING_SCORE = {
    "买入": 3, "增持": 2, "推荐": 2, "持有": 1, "中性": 1, "卖出": 0,
    "强烈推荐": 3, "审慎推荐": 2,
}


def score_report_relevance(norm: dict, keywords: list[str], company_codes: list[str]) -> int:
    """对归一化研报评分：关键词命中 + 代表公司 + 评级。"""
    score = 0
    title = (norm.get("title") or "").lower()
    hits = [k for k in keywords if k and k.lower() in title]
    score += len(hits) * 5
    norm["matched_keywords"] = hits
    if norm.get("company_code") and norm["company_code"] in company_codes:
        score += 8
    rating = norm.get("rating") or ""
    score += _RATING_SCORE.get(str(rating).strip(), 0)
    return score


# ---------------------------------------------------------------------------
# 发现服务
# ---------------------------------------------------------------------------


@dataclass
class DiscoveryResult:
    source_key: str
    discovered: list[dict] = field(default_factory=list)
    filtered: list[dict] = field(default_factory=list)
    error: str | None = None
    total_discovered: int = 0
    returned: int = 0
    truncated: bool = False


def _parse_publish_date(value: str | None) -> date | None:
    """解析 YYYY-MM-DD / YYYY-MM / YYYY；非法或空 → None（不伪造）。"""
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # 截取日期前缀（东财可能带时间）
    s = s[:10]
    for fmt, n in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y", 4)):
        try:
            part = s[:n]
            return datetime.strptime(part, fmt).date()
        except ValueError:
            continue
    return None


def _within_lookback(publish_date: str | None, lookback_days: int, *, today: date | None = None) -> tuple[bool, bool]:
    """返回 (keep, date_unknown)。

    合法日期：在 [today-lookback, today] 内保留；更早丢弃。
    缺失/非法：保留，date_unknown=True（不伪装为今天）。
    """
    today = today or datetime.now(timezone.utc).date()
    d = _parse_publish_date(publish_date)
    if d is None:
        return True, True
    earliest = today - timedelta(days=int(lookback_days))
    return (earliest <= d <= today), False


def _fetch_industry_raw(lookback: int, max_pages: int, keywords: list[str]) -> list[dict]:
    """拉取行业研报并按关键词过滤标题。"""
    raw_rows = astock.eastmoney_industry_reports(
        keywords=None, days=lookback, max_pages=max_pages,
    )
    if keywords:
        raw_rows = [r for r in raw_rows if any(k in (r.get("title") or "") for k in keywords)]
    return raw_rows


def _fetch_company_raw(company_codes: list[str], max_pages: int) -> list[dict]:
    """顺序拉取代表公司研报，按 external_id（info_code）去重。"""
    raw_rows: list[dict] = []
    seen: set[str] = set()
    for code in company_codes:
        for r in astock.eastmoney_reports(code, max_pages=max_pages):
            info = _first_present(r, "infoCode", "info_code")
            if info and info in seen:
                continue
            if info:
                seen.add(info)
            raw_rows.append(r)
    return raw_rows


def _sort_discovered(rows: list[dict]) -> None:
    """relevance_score desc；已知日期 publish_date desc；未知日期排后；external_id 兜底。"""
    rows.sort(key=lambda n: n.get("external_id") or "")
    rows.sort(key=lambda n: n.get("publish_date") or "", reverse=True)
    rows.sort(key=lambda n: 1 if n.get("date_unknown") else 0)  # 未知日期靠后
    rows.sort(key=lambda n: n.get("relevance_score") or 0, reverse=True)


def discover_sector_reports(
    sector_key: str,
    *,
    days: int | None = None,
    max_pages: int = 3,
    scope: str = "industry",
    max_results: int = MAX_DISCOVERY_RESULTS,
) -> DiscoveryResult:
    """发现板块研报（只返回发现结果，不自动归档）。

    scope: "industry" | "company" | "all"（由调用方校验非法值并返回 400）。
    industry / company / all 均按 days 回溯过滤 publish_date。
    排序后截断至 max_results，保证返回列表可全部写入导入缓存。
    """
    src = get_sector_source(sector_key)
    if src is None:
        return DiscoveryResult(source_key=sector_key, error=f"未注册的板块：{sector_key}")
    lookback = days if days is not None else src.report_lookback_days
    keywords = src.report_keywords
    company_codes = src.representative_company_codes

    result = DiscoveryResult(source_key=sector_key)
    try:
        if scope == "company":
            raw_rows = _fetch_company_raw(company_codes, max_pages)
        elif scope == "all":
            industry_rows = _fetch_industry_raw(lookback, max_pages, keywords)
            company_rows = _fetch_company_raw(company_codes, max_pages)
            seen: set[str] = set()
            raw_rows = []
            for r in industry_rows + company_rows:
                info = _first_present(r, "infoCode", "info_code")
                if info and info in seen:
                    continue
                if info:
                    seen.add(info)
                raw_rows.append(r)
        else:
            # 默认 industry（调用方应对非法 scope 返回 400）
            raw_rows = _fetch_industry_raw(lookback, max_pages, keywords)

        normalized: list[dict] = []
        for r in raw_rows:
            n = normalize_report(r)
            keep, date_unknown = _within_lookback(n.get("publish_date"), lookback)
            if not keep:
                continue
            n["date_unknown"] = date_unknown
            n["relevance_score"] = score_report_relevance(n, keywords, company_codes)
            normalized.append(n)

        filtered = [
            n for n in normalized
            if n.get("title") and (
                n.get("matched_keywords") or n.get("company_code") in company_codes
            )
        ]
        _sort_discovered(normalized)
        _sort_discovered(filtered)

        # 展示与缓存使用同一截断列表（优先 filtered，否则 discovered）
        primary = filtered if filtered else normalized
        total = len(primary)
        limit = max(1, int(max_results)) if max_results else MAX_DISCOVERY_RESULTS
        truncated = total > limit
        primary = primary[:limit]
        # discovered 与 filtered 同步截断后的可见集
        visible_ids = {n.get("external_id") for n in primary if n.get("external_id")}
        result.discovered = primary
        result.filtered = [n for n in filtered if n.get("external_id") in visible_ids][:limit]
        if not result.filtered:
            result.filtered = list(primary)
        result.total_discovered = total
        result.returned = len(primary)
        result.truncated = truncated
    except Exception as e:  # noqa: BL001
        result.error = str(e)
    return result


def _safe_panel_error(exc: BaseException) -> str:
    """不向前端暴露堆栈；仅返回简短安全信息。"""
    name = type(exc).__name__
    if name == "DependencyMissing":
        return "依赖未安装"
    msg = str(exc).strip()
    if not msg:
        return f"{name}"
    # 截断路径与过长内容
    if len(msg) > 120:
        msg = msg[:117] + "..."
    if "Traceback" in msg or "\\" in msg or "/home/" in msg:
        return name
    return msg


def _panel_ok(summary: dict | None = None) -> dict:
    """仅返回受控摘要，不附带原始接口响应。"""
    return {"status": "ok", "summary": summary or {}, "error": None}


def _panel_err(exc: BaseException) -> dict:
    return {"status": "error", "summary": {}, "error": _safe_panel_error(exc)}


def _summarize_individual_info(data) -> dict:
    """从 astock.individual_info 返回中提取最小摘要。"""
    if not isinstance(data, dict):
        return {}
    summary = {}
    for k in ("股票简称", "name", "简称", "公司名称"):
        if data.get(k):
            summary["name"] = str(data[k])[:50]
            break
    for k in ("所属行业", "industry", "行业"):
        if data.get(k):
            summary["industry"] = str(data[k])[:80]
            break
    for k in ("总市值", "流通市值", "market_cap"):
        if data.get(k):
            summary["market_cap"] = str(data[k])[:30]
            break
    for k in ("主营业务", "business", "经营范围"):
        if data.get(k):
            summary["business"] = str(data[k])[:200]
            break
    return summary


def _summarize_profit_forecast(data: list | dict | None) -> dict:
    """解析 astock.profit_forecast() 的真实 list[dict]（或偶发 dict）。

    不把列表长度伪装成机构覆盖数；字段缺失不猜测。
    """
    if data is None:
        return {"note": "无一致预期数据"}
    rows: list[dict]
    if isinstance(data, list):
        rows = [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        # 兼容偶发整包 dict
        inner = data.get("data") or data.get("list") or data.get("records")
        if isinstance(inner, list):
            rows = [r for r in inner if isinstance(r, dict)]
        else:
            rows = [data]
    else:
        return {"note": "已取得一致预期数据，暂无法结构化摘要"}

    if not rows:
        return {"note": "无一致预期数据"}

    def _year_key(row: dict) -> str:
        for k in ("年度", "预测年度", "year", "YEAR", "年份", "最新年度"):
            v = row.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
        return ""

    # 选「年度」字符串最大者（通常为最新预测年）
    best = max(rows, key=lambda r: _year_key(r))
    summary: dict = {"record_count": len(rows)}

    y = _year_key(best)
    if y:
        summary["year"] = y[:10]

    # EPS / 均值
    for k in ("均值", "预测EPS", "EPS", "eps", "预测每股收益", "基本每股收益"):
        v = best.get(k)
        if v is not None and str(v).strip() not in ("", "-", "--"):
            summary["eps"] = str(v).strip()[:50]
            summary["forecast"] = summary["eps"]
            break

    # 机构数：不得用 len(rows)
    for k in ("预测机构数", "机构数", "机构家数", "coverage", "分析师数"):
        v = best.get(k)
        if v is not None and str(v).strip() not in ("", "-", "--"):
            summary["coverage"] = str(v).strip()[:20]
            break

    # 净利润预测（可选）
    for k in ("预测净利润", "净利润", "net_profit"):
        v = best.get(k)
        if v is not None and str(v).strip() not in ("", "-", "--"):
            if "forecast" not in summary:
                summary["forecast"] = str(v).strip()[:50]
            break

    if len(summary) <= 1:  # 仅 record_count
        return {"note": "已取得一致预期数据，暂无法结构化摘要", "record_count": len(rows)}
    return summary


def _summarize_announcements(data) -> dict:
    """从 astock.announcements 返回中提取摘要。"""
    summary = {}
    if isinstance(data, list):
        summary["count"] = len(data)
        if data:
            first = data[0]
            if isinstance(first, dict):
                for k in ("标题", "title", "公告标题"):
                    if first.get(k):
                        summary["latest_title"] = str(first[k])[:120]
                        break
                for k in ("日期", "date", "公告日期"):
                    if first.get(k):
                        summary["latest_date"] = str(first[k])[:20]
                        break
    elif isinstance(data, dict) and "list" in data:
        return _summarize_announcements(data["list"])
    return summary


def get_sector_dynamic_data(sector_key: str) -> dict:
    """拉取板块动态数据（一致预期 / 公告 / 新闻）。

    合同：
      source / fetched_at / status(normal|partial|unavailable) / warnings / companies
    单家失败不导致整包空白。
    """
    from datetime import datetime, timezone

    src = get_sector_source(sector_key)
    if src is None:
        return {
            "sector_key": sector_key,
            "source": "a-stock-data",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "status": "unavailable",
            "warnings": [f"未注册的板块：{sector_key}"],
            "companies": [],
            "error": f"未注册的板块：{sector_key}",
        }

    codes = src.representative_company_codes
    name_map = src.representative_companies
    panels_enabled = list(src.dynamic_panels)
    companies: list[dict] = []
    warnings: list[str] = []
    ok_panels = 0
    fail_panels = 0

    for code in codes:
        company: dict = {
            "code": code,
            "name": name_map.get(code) or "",
            "panels": {},
        }
        if "individual_info" in panels_enabled:
            try:
                data = astock.individual_info(code)
                summary = _summarize_individual_info(data)
                company["panels"]["individual_info"] = _panel_ok(summary)
                # 尝试补名称
                if not company["name"] and summary.get("name"):
                    company["name"] = summary["name"]
                ok_panels += 1
            except Exception as e:  # noqa: BL001
                company["panels"]["individual_info"] = _panel_err(e)
                fail_panels += 1
                warnings.append(f"{code} 基本面：{_safe_panel_error(e)}")
        if "profit_forecast" in panels_enabled:
            try:
                data = astock.profit_forecast(code)
                summary = _summarize_profit_forecast(data)
                company["panels"]["profit_forecast"] = _panel_ok(summary)
                ok_panels += 1
            except Exception as e:  # noqa: BL001
                company["panels"]["profit_forecast"] = _panel_err(e)
                fail_panels += 1
                warnings.append(f"{code} 一致预期：{_safe_panel_error(e)}")
        if "announcements" in panels_enabled:
            try:
                anns = astock.announcements(code, limit=10)
                summary = _summarize_announcements(anns)
                company["panels"]["announcements"] = _panel_ok(summary)
                ok_panels += 1
            except Exception as e:  # noqa: BL001
                company["panels"]["announcements"] = _panel_err(e)
                fail_panels += 1
                warnings.append(f"{code} 公告：{_safe_panel_error(e)}")
        companies.append(company)

    if ok_panels == 0:
        status = "unavailable"
    elif fail_panels == 0:
        status = "normal"
    else:
        status = "partial"

    return {
        "sector_key": sector_key,
        "source": "a-stock-data",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "warnings": warnings[:20],
        "companies": companies,
    }


def pdf_url_allowed(url: str | None) -> bool:
    """校验 PDF URL 域名是否在允许列表，且为 HTTPS。用于导入接口的 SSRF 防护。"""
    if not url:
        return False
    if not url.startswith("https://"):
        return False
    try:
        host = url.split("/", 3)[2].split(":")[0].lower()
    except (IndexError, ValueError):
        return False
    return host in _PDF_HOST_ALLOW

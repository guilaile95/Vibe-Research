"""Public-source research contracts. No orders, accounts or implicit collection."""
from datetime import date, datetime, timezone
import hashlib
import json
import math
import re

VERSION = 'public-research.v1'
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
# Fixed endpoint + subject identities, never caller-provided URLs or board names.
SOURCES = {
    'public_polymarket': {'label': 'Polymarket 事件定价', 'subjects': ('markets',), 'provider': 'polymarket', 'endpoint': 'gamma_markets', 'stale_days': 1,
        'guard': '预测市场价格不是客观概率或事实；低流动性与价差可能失真，只读公开行情，不下单。'},
    'public_kalshi': {'label': 'Kalshi 事件定价', 'subjects': ('markets',), 'provider': 'kalshi', 'endpoint': 'trade_api_markets', 'stale_days': 1,
        'guard': '预测市场价格不是客观概率或事实；买卖报价和末次成交不同，缺报价不是零概率，不下单。'},
    'tw_monthly_revenue': {'label': '台湾月营收', 'subjects': ('2383', '6274', '2368', '3081'), 'provider': 'finmind', 'endpoint': 'TaiwanStockMonthRevenue', 'stale_days': 70,
        'guard': '台系供应链营收不是 A 股本公司营收；同比仅同发行人同月同源序列，合并口径及修订可比性未获证实则正式同比保持未知。'},
    'dram_spot_thermo': {'label': 'DRAM / NAND 现货', 'subjects': ('DDR5', 'NAND_TLC', 'DDR4'), 'provider': 'github-community', 'endpoint': 'dram_community_json', 'stale_days': 14,
        'guard': '社区转录 DRAMeXchange，非官方一手，可能转录错误或停更；DRAM 不是 HBM 价格；规格未知不得跨规格比较。'},
    'cn_commodity_futures': {'label': '大宗连续期货', 'subjects': ('CU0', 'SN0', 'AL0', 'NI0', 'SI0'), 'provider': 'sina', 'endpoint': 'InnerFuturesNewService.getDailyKLine', 'stale_days': 10,
        'guard': '连续合约不是可交割合约，换月及调整规则未披露，不计算跨合约收益；期货价不是本公司采购价；工业硅主要受光伏需求影响。'},
    'hiring_anchor_signal': {'label': '公开招聘信号', 'subjects': ('greenhouse:lightmatter', 'greenhouse:asteralabs', 'ashby:cerebras', 'ashby:openai', 'greenhouse:xai', 'greenhouse:anthropic'), 'provider': 'ats-public', 'endpoint': 'public_job_board', 'stale_days': 7,
        'guard': '岗位数是招聘意图，不是产能或已聘人数；移除岗位不代表完成招聘；仅同公司同 ATS 比较。Workday 未接入不等于零岗位。'},
}


def stamp(value):
    if type(value) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)', value):
        raise ValueError('invalid timestamp')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return result.astimezone(timezone.utc)


def utc(value):
    return stamp(value).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def day(value):
    if type(value) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('invalid date')
    date.fromisoformat(value)
    return value


def text(value, maximum=512):
    if type(value) is not str or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError('invalid text')
    return value


def number(value, *, maximum=1e18):
    if type(value) is str and re.fullmatch(r'\d+(?:\.\d+)?', value):
        value = float(value)
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError('invalid finite number')
    return float(value)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def decode(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('invalid source byte budget')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def reject(_):
        raise ValueError('nonfinite JSON')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)


def rows(value):
    if type(value) is not list or len(value) > MAX_ROWS:
        raise ValueError('invalid row budget or shape')
    return value


def identity(source, subject):
    if source not in SOURCES or subject not in SOURCES[source]['subjects']:
        raise ValueError('unsupported public source identity')
    return SOURCES[source]


def request_spec(source, subject):
    identity(source, subject)
    if source == 'public_polymarket':
        return 'https://gamma-api.polymarket.com/markets?limit=100&active=true&closed=false&order=volume24hr&ascending=false'
    if source == 'public_kalshi':
        return 'https://api.elections.kalshi.com/trade-api/v2/markets?limit=200&status=open'
    if source == 'tw_monthly_revenue':
        return f'https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMonthRevenue&data_id={subject}&start_date=2020-01-01'
    if source == 'dram_spot_thermo':
        return ('https://raw.githubusercontent.com/titled-agent-001/ddr4-pricing-log/main/ddr4-pricing.json' if subject == 'DDR4' else 'https://raw.githubusercontent.com/nlee756525/dram-prices/main/history.json')
    if source == 'cn_commodity_futures':
        return f'https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_V21052021_4_12=/InnerFuturesNewService.getDailyKLine?symbol={subject}&type=2021_04_12'
    ats, board = subject.split(':')
    return (f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs' if ats == 'greenhouse' else f'https://api.ashbyhq.com/posting-api/job-board/{board}')

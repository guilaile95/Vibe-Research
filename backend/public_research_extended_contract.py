"""Date-owned market and company input identities; no transport activation."""
from datetime import datetime, timezone
import re
from urllib.parse import urlencode
import public_research_contract as C

INDICES = {'sh000001': '上证指数', 'sz399001': '深证成指', 'sz399006': '创业板指', 'sh000300': '沪深300',
           'sh000905': '中证500', 'sh000852': '中证1000', 'sh000688': '科创50', 'bj899050': '北证50', 'sz399106': '深证综指（成交额）'}
GLOBAL = ('global_quote_ref', 'global_financials_pit', 'yahoo_consensus')
CN = ('cn_quote_ref', 'cn_financials_ytd', 'cn_consensus')
MARKET = ('em_market_trend', 'index_valuation', 'chinabond_yield_curve')
SPECS = {
 'em_market_trend': ('指数趋势与两市成交额', 'eastmoney', 'push2his_index_daily', '指数为未复权日收盘；固定交易日窗口缺日保持未知，不拿更早数据替代；同一原始版本内计算，不证明历史当时已知。'),
 'index_valuation': ('沪深300官方估值', 'csindex', 'official_indicator_xls', '官方近期文件，市盈率总股本与计算股本口径分列；股息率为百分数，不含PB，不代表估值建议。'),
 'chinabond_yield_curve': ('中债国债收益率曲线', 'chinabond', 'historyQuery_treasury', '收益率单位为百分数，可为负数；不是债券价格或持有期回报。没有完整债市日历，不把整天缺失解释为休市。'),
 'global_quote_ref': ('港美股报价与基准', 'tencent', 'same_response_security_benchmark', '个股与基准来自同一响应；参考日是基准报价日期，不是官方交易日历。交易时段只按当地时钟推断，不能由基准陈旧断言休市。'),
 'global_financials_pit': ('港美股公告日筛选财务', 'eastmoney', 'GMAININDICATOR', '当前存储版本按公告日及报告期末筛选；历史值可能重述、旧公告日可能被覆盖，不是历史版本PIT，不证明当时已知。'),
 'yahoo_consensus': ('港美股年度一致预期', 'yahoo', 'quoteSummary_earningsTrend', '年度分析师预期不是公司承诺或事实；使用报告币种，可能不同于股票报价币种；不提供升级降级评级。'),
 'cn_quote_ref': ('A股报价与基准原始回执', 'tencent', 'same_response_security_benchmark', '同一响应的A股报价与上证基准，逐个核验源标识及北京时间；不是历史行情回放，晚于截止日仅供诊断。'),
 'cn_financials_ytd': ('A股累计财务原始回执', 'eastmoney', 'RPT_DMSK_FN_INCOME', '替代来源的报告期累计财务，源证券标识逐行核验；不是单季或TTM；扣非缺失保留，不用归母替代；当前版本不证明历史当时已知。'),
 'cn_consensus': ('A股年度一致预期', 'ths', 'worth_consensus_html', '同花顺年度EPS一致预期，均值/最小/最大/机构数分别保留；不是单篇研报预测，不构成评级或公司承诺。'),
}


def parse_subject(source, subject):
    if source not in SPECS or type(subject) is not str or subject.count('@') != 1:
        raise ValueError('invalid extended research identity')
    key, cutoff = subject.split('@')
    C.day(cutoff)
    if cutoff > datetime.now(timezone.utc).date().isoformat():
        raise ValueError('future research cutoff')
    if source in GLOBAL + CN:
        if key.count(':') != 1:
            raise ValueError('market identity required')
        market, symbol = key.split(':')
        if source in GLOBAL:
            if not ((market == 'US' and re.fullmatch(r'[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,3})?', symbol)) or (market == 'HK' and re.fullmatch(r'\d{5}', symbol) and symbol != '00000')):
                raise ValueError('invalid global symbol')
        elif market != 'A' or not re.fullmatch(r'(?:60|68|00|30|43|83|87|88|92)\d{4}', symbol):
            raise ValueError('invalid CN symbol')
        return key, cutoff, market, symbol
    if (source == 'em_market_trend' and key not in INDICES or source == 'index_valuation' and key != '000300'
        or source == 'chinabond_yield_curve' and key != 'treasury'):
        raise ValueError('invalid market subject')
    return key, cutoff, 'CN', key


def source_spec(source, subject):
    parse_subject(source, subject)
    label, provider, endpoint, guard = SPECS[source]
    return {'label': label, 'provider': provider, 'endpoint': endpoint, 'guard': guard, 'subjects': (), 'stale_days': 1}


def request_spec(source, subject):
    key, cutoff, market, symbol = parse_subject(source, subject)
    if source == 'em_market_trend':
        secid = ('1.' if key.startswith('sh') else '0.') + key[2:]
        return 'https://push2his.eastmoney.com/api/qt/stock/kline/get?' + urlencode({'secid': secid, 'fields1': 'f1,f2,f3', 'fields2': 'f51,f53,f57', 'klt': '101', 'fqt': '0', 'end': cutoff.replace('-', ''), 'lmt': '600'})
    if source == 'index_valuation':
        return 'https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/indicator/000300indicator.xls'
    if source == 'chinabond_yield_curve':
        return 'https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/historyQuery?' + urlencode({'startDate': cutoff, 'endDate': cutoff, 'gjqx': 0, 'qxId': 'hzsylqx', 'locale': 'cn_ZH'})
    if source in ('global_quote_ref','cn_quote_ref'):
        stock, benchmark = quote_keys(market,symbol)
        return f'https://qt.gtimg.cn/q={stock},{benchmark}'
    if source in ('global_financials_pit', 'cn_financials_ytd'):
        secucode = symbol.replace('.', '_') + ('.HK' if market == 'HK' else '.O' if market == 'US' else '.SH' if symbol.startswith(('60', '68')) else '.BJ' if symbol.startswith(('43', '83', '87', '88', '92')) else '.SZ')
        # US datacenter uses SECURITY_CODE rather than assuming a Nasdaq/NYSE suffix.
        field, value = ('SECURITY_CODE', symbol.replace('.', '_')) if market == 'US' else ('SECUCODE', secucode)
        report = f'RPT_{market}F10_FN_GMAININDICATOR' if source == 'global_financials_pit' else 'RPT_DMSK_FN_INCOME'
        return 'https://datacenter-web.eastmoney.com/api/data/v1/get?' + urlencode({'reportName': report, 'columns': 'ALL', 'filter': f'({field}="{value}")', 'pageSize': 60, 'pageNumber': 1, 'sortColumns': 'REPORT_DATE', 'sortTypes': '-1'})
    if source == 'yahoo_consensus':
        yahoo = f'{int(symbol):04d}.HK' if market == 'HK' else symbol.replace('.', '-')
        return f'https://query2.finance.yahoo.com/v10/finance/quoteSummary/{yahoo}?modules=earningsTrend,earnings,price'
    return f'https://basic.10jqka.com.cn/new/{symbol}/worth.html'


def dataset(source, subject):
    parse_subject(source, subject)
    return 'research_' + source + '_' + C.digest(subject)[:32] + '_v1'


def quote_keys(market,symbol):
    if market=='US': return 'us'+symbol,'usINX'
    if market=='HK': return 'r_hk'+symbol,'hkHSI'
    return ('sh' if symbol.startswith(('60','68')) else 'bj' if symbol.startswith(('43','83','87','88','92')) else 'sz')+symbol,'sh000001'

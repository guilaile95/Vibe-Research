"""Provider-shaped synthetic bytes only. No downloaded executable or live payload."""
from io import BytesIO
import public_research_contract as C
import public_research_extended_contract as E
import trade_calendar

CUTOFF='2026-09-30'
CAPTURED='2026-10-01T12:00:00.000000Z'


def raw(source,subject):
    key,cutoff,market,symbol=E.parse_subject(source,subject)
    if source=='em_market_trend':
        dates=[d for d in trade_calendar._load_calendar() if d<=cutoff][-300:]
        return C.canonical({'data':{'code':key[2:],'market':1 if key.startswith('sh') else 0,'klines':[f'{day},{100+i},{1000+i}' for i,day in enumerate(dates)]}}).encode()
    if source=='chinabond_yield_curve':
        return ('<html><table><tr>'+''.join('<th>'+h+'</th>' for h in ['曲线名称','日期','3月','6月','1年','3年','5年','7年','10年','30年'])+'</tr><tr><td>中债国债收益率曲线</td><td>'+cutoff+'</td>'+''.join('<td>'+str(v)+'</td>' for v in [-.25,.5,1,1.2,1.4,1.6,1.8,2])+'</tr></table></html>').encode()
    if source=='index_valuation':
        return biff_rows([['日期Date','指数代码IndexCode','市盈率1（总股本）P/E1','市盈率2（计算用股本）P/E2','股息率1（总股本）D/P1','股息率2（计算用股本）D/P2'],[cutoff,'000300',-3,14,2.5,2.1]])
    if source in ('global_quote_ref','cn_quote_ref'):
        rows=[]
        for ticker,ident in [(E.quote_keys(market,symbol)[0],symbol),(E.quote_keys(market,symbol)[1],'INX' if market=='US' else 'HSI' if market=='HK' else '000001')]:
            fields=['']*76;fields[1]='Synthetic '+ident;fields[2]=ident;fields[3]='150';fields[4]='148';fields[6]='1000';fields[30]=cutoff.replace('-','')+'150000' if market=='A' else cutoff+' 16:00:00';fields[35]='USD';fields[75]='HKD'
            rows.append('v_'+ticker+'="'+'~'.join(fields)+'";')
        return '\n'.join(rows).encode('gbk')
    if source in ('global_financials_pit','cn_financials_ytd'):
        cn=source=='cn_financials_ytd'; secucode=symbol+('.SH' if cn else '.HK' if market=='HK' else '.O')
        row={'SECURITY_CODE':symbol,'SECUCODE':secucode,'NOTICE_DATE':'2026-08-10 00:00:00','START_DATE':'2025-10-01 00:00:00','REPORT_DATE':'2026-06-30 00:00:00','DATE_TYPE_CODE':'004','CURRENCY':'人民币' if market=='HK' or cn else '美元','REPORT_TYPE':'provider consolidated label','OPERATE_INCOME':1200000,'TOTAL_OPERATE_INCOME':1200000,'PARENT_HOLDER_NETPROFIT':-20000,'HOLDER_PROFIT':-20000,'PARENT_NETPROFIT':-20000,'BASIC_EPS':-.25}
        rows=[row,{**row,'NOTICE_DATE':None,'REPORT_DATE':'2026-03-31 00:00:00'},{**row,'NOTICE_DATE':'2026-10-10 00:00:00'}]
        return C.canonical({'success':True,'result':{'data':rows,'count':len(rows)}}).encode()
    if source=='yahoo_consensus':
        provider=f'{int(symbol):04d}.HK' if market=='HK' else symbol.replace('.','-')
        return C.canonical({'quoteSummary':{'error':None,'result':[{'price':{'symbol':provider,'currency':'HKD' if market=='HK' else 'USD'},'earnings':{'financialCurrency':'CNY' if market=='HK' else 'USD'},'earningsTrend':{'trend':[{'period':period,'endDate':end,'earningsEstimate':{'avg':{'raw':-1},'low':{'raw':-2},'high':{'raw':0},'numberOfAnalysts':{'raw':5}},'revenueEstimate':{'avg':{'raw':1000000}}} for period,end in [('0y','2026-09-30'),('+1y','2027-09-30')]]}}]}}).encode()
    return ('<html><head><title>Synthetic('+symbol+')估值分析</title></head><table><caption>年度一致预期每股收益（元/股）</caption><tr><th>年度</th><th>预测机构数</th><th>最小值</th><th>均值</th><th>最大值</th></tr>'+''.join(f'<tr><td>{y}年</td><td>5</td><td>-2</td><td>-1</td><td>0</td></tr>' for y in (2026,2027,2028))+'</table></html>').encode('gbk')


def seed(lake):
    from public_research_archive import persist_capture
    specs=[(s,k+'@'+CUTOFF) for s,keys in [('em_market_trend',E.INDICES),('index_valuation',['000300']),('chinabond_yield_curve',['treasury'])] for k in keys]
    specs += [(s,f'{m}:{code}@{CUTOFF}') for m,code,sources in [('US','AAPL',E.GLOBAL),('HK','00700',E.GLOBAL),('A','600000',E.CN)] for s in sources]
    for source,subject in specs: persist_capture(lake,raw(source,subject),source,subject,CAPTURED,fixture=True)


def biff_rows(table):
    """Small genuine BIFF8 workbook fixture, independently written inert data."""
    import struct
    record=lambda code,payload:struct.pack('<HH',code,len(payload))+payload
    bof=lambda kind:record(0x809,struct.pack('<HHHHII',0x600,kind,0xDBB,1996,0x41,6))
    base=bof(5)+record(0x42,struct.pack('<H',1200)); name=b'Sheet1'
    bounds=lambda offset:record(0x85,struct.pack('<IBBB',offset,0,0,len(name))+b'\0'+name)
    base+=bounds(len(base)+len(bounds(0))+4)+record(0xA,b'')
    sheet=bof(16)+record(0x200,struct.pack('<IIHHH',0,len(table),0,len(table[0]),0))
    for i,row in enumerate(table):
        for j,value in enumerate(row):
            if isinstance(value,str):sheet+=record(0x204,struct.pack('<HHHHB',i,j,0,len(value),1)+value.encode('utf-16le'))
            else:sheet+=record(0x203,struct.pack('<HHHd',i,j,0,value))
    return base+sheet+record(0xA,b'')

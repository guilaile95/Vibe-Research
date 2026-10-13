"""In-process HTTP inventory for the offline browser harness; no server/browser.

Uses the unchanged production security middleware and RDP/screener routes. Dates,
rows and filters mirror the two fixed seedRdpFixture cases in the browser test.
Browser click/React readiness and held-proxy timing remain separate CI evidence.
"""
import asyncio
import csv
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path

# Same pre-guard loop construction as Uvicorn, including Windows socketpair.
loop = asyncio.SelectorEventLoop()
import screener_offline_harness_app as harness
import research_data_plane as rdp
import screener_service as service
from fastapi.testclient import TestClient

root = Path(os.environ['VR_DATA_DIR'])
origin = os.environ['VR_ALLOW_ORIGINS']
assert origin == 'http://127.0.0.1:41979'
assert harness.product._ALLOWED_ORIGINS == [origin]
inventory = []


def seed(kind, folder):
    target = root/folder
    target.mkdir()
    source = target/('candidate-window.csv' if kind == 'candidate' else 'full-market.csv')
    with source.open('w',newline='') as f:
        w=csv.writer(f); w.writerow(['code','trade_date','open','high','low','close','volume'])
        if kind == 'candidate':
            for i in range(150):
                day=(date(2026,1,1)+timedelta(days=i)).isoformat()
                close=10+i/10 if i<120 else 1
                w.writerow(['000001',day,close,close+1,close-.5,close,1000+i])
                if i<30:
                    other=20-i/10
                    w.writerow(['000003',day,other,other+1,other-.5,other,1000+i])
        else:
            for i in range(65):
                day=(date(2026,1,2)+timedelta(days=i)).isoformat()
                for code,base,volume in [('000001',10,100),('000002',20,200)]:
                    close=base+i
                    w.writerow([code,day,close,close+1,close-1,close,volume+i])
            w.writerow(['600519','2026-03-07',12,13,11,12,300])
    manifest=rdp.import_csv(source,root=target/'rdp')
    return target/'rdp',manifest


normal,normal_manifest=seed('normal','normal')
candidate,candidate_manifest=seed('candidate','candidate')
corrupt,corrupt_manifest=seed('normal','corrupt')
artifact=corrupt/'artifacts'/f"{corrupt_manifest['artifact_sha256']}.parquet"
with artifact.open('ab') as f: f.write(b'tampered-by-#220-e2e')
missing=root/'missing'
missing.mkdir()


def fingerprint():
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


before=fingerprint()
filters=[{'metric':'return_20d','operator':'gte','value':0}]
base_params={'latest':'true','filters':json.dumps(filters),'sort_by':'return_20d','sort_order':'desc','limit':'50','offset':'0'}
body={'codes':['000001'],'conditions':[{'id':'price_gt_sma20'}]}
service_calls=[]
original=service.evaluate_screener

def counted(*args,**kwargs):
    service_calls.append(1)
    return original(*args,**kwargs)

service.evaluate_screener=counted
with TestClient(harness.app,base_url='http://127.0.0.1:45000',backend_options={'loop_factory':lambda:loop}) as client:
    def request(label,method,path,*,params=None,body=None,post_origin=origin):
        headers={'host':'127.0.0.1:45000'}
        if path != '/api/health':
            mode='full-market' if path == '/api/screener/full-market' else 'candidate'
            headers.update({'referer':origin+'/screener?mode='+mode,'sec-fetch-site':'same-origin'})
        if body is not None: headers.update({'origin':post_origin,'content-type':'application/json'})
        result=client.request(method,path,params=params,json=body,headers=headers)
        inventory.append({'case':label,'method':method,'path':path,'params':params,'headers':headers,'body':body,'http_status':result.status_code})
        return result
    assert request('startup-health','GET','/api/health').status_code==200
    os.environ['VIBE_RESEARCH_RESEARCH_DATA_DIR']=str(normal)
    for label,params,codes in [
        ('full-market-default',base_params,['000001','000002']),
        ('full-market-and',{**base_params,'filters':json.dumps(filters+[{'metric':'latest_close','operator':'lt','value':80}])},['000001']),
        ('held-proxy-upstream-request',base_params,['000001','000002']),
    ]:
        result=request(label,'GET','/api/screener/full-market',params=params)
        assert result.status_code==200,result.text
        value=result.json();assert value['status']=='normal'
        assert sorted(row['code'] for row in value['rows'])==codes
        assert value['coverage']['row_count']==131 and value['coverage']['current_count']==3
    os.environ['VIBE_RESEARCH_RESEARCH_DATA_DIR']=str(candidate)
    for label,codes,status,counts in [
        ('candidate-latest',['000001'],'normal',(0,1,0)),
        ('candidate-partial',['000001','000002'],'partial',(0,1,1)),
        ('candidate-empty',['000002'],'unavailable',(0,0,1)),
    ]:
        result=request(label,'POST','/api/screener/evaluate',body={**body,'codes':codes})
        assert result.status_code==200,result.text
        value=result.json();assert value['status']==value['research_data']['status']==status
        assert tuple(len(value[key]) for key in ['matched','rejected','unavailable'])==counts
        assert value['batch_coverage']['requested_count']==len(codes)
        if value['rejected']:
            row=value['rejected'][0]
            assert row['trade_date']=='2026-05-30' and row['condition_results'][0]['passed'] is False
            assert row['data_coverage']['returned_rows']==120 and row['data_coverage']['start']=='2026-01-31'
            assert row['data_coverage']['artifact_sha256']==candidate_manifest['artifact_sha256']
        if value['unavailable']:
            row=value['unavailable'][0]
            assert row['matched'] is None and row['data_coverage']['returned_rows']==0
    for untrusted in ['http://127.0.0.1:41980','http://localhost:41979','https://untrusted.invalid','null','http://127.0.0.1:5899']:
        previous=len(service_calls)
        result=request('reject-other-origin','POST','/api/screener/evaluate',body=body,post_origin=untrusted)
        assert result.status_code==403 and result.json()=={'detail':'Origin not allowed'},result.text
        assert len(service_calls)==previous,'Rejected origin reached screener route'
    # Same backend origin remains an intentional production-policy allowance.
    assert request('same-backend-origin-control','POST','/api/screener/evaluate',body=body,post_origin='http://127.0.0.1:45000').status_code==200
    for label,dataset,reason in [('missing',missing,'research bulk dataset is not configured'),('corrupt',corrupt,'Full Market 数据校验失败')]:
        os.environ['VIBE_RESEARCH_RESEARCH_DATA_DIR']=str(dataset)
        result=request(label,'GET','/api/screener/full-market',params=base_params)
        assert result.status_code==200,result.text
        value=result.json();assert value['status']=='unavailable' and value['rows']==[]
        assert reason in ' '.join(value['limitations'])
assert harness.violations==[],harness.violations
assert fingerprint()==before,'Read-only requests changed the isolated fixture files'
print(json.dumps({'inventory':inventory,'forbidden_attempts':harness.violations,'fixture_files_unchanged':True}))

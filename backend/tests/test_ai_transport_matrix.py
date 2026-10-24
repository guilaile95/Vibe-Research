"""No-network protocol matrix: TCP pinning and both TLS identities."""
import io, asyncio, socket
from types import SimpleNamespace
from unittest.mock import patch
import model_transport as t
import httpcore, httpx, urllib3.connection

def test_protocol_matrix():
    for host,address in [('model.invalid','8.8.8.8'),('::1','::1')]:
     for scheme in ['http','https']:
      for proxy_scheme in [None,'http','https']:
       proxy=t.BoundEndpoint('proxy.invalid',8080,'9.9.9.9',proxy_scheme) if proxy_scheme else None
       ep=t.BoundEndpoint(host,443 if scheme=='https' else 80,address,scheme,proxy,f'{proxy_scheme}://proxy.invalid:8080' if proxy else None)
       url=f'{scheme}://'+(f'[{host}]' if ':' in host else host)+'/v1/chat/completions'
       writes=[]; names=[]; connects=[]
       class Sock:
        def settimeout(self,*a):pass
        def sendall(self,v):writes.append(v)
        def makefile(self,*a,**k):return io.BytesIO(b'HTTP/1.1 200 Connection established\r\n\r\n' if writes[-1].startswith(b'CONNECT') else b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}')
        def close(self):pass
       def conn(addr,*a,**k):connects.append(addr);return Sock()
       def tls(*a,**k):
        names.append(k['server_hostname']);assert k['cert_reqs'] in ('CERT_REQUIRED',2)
        return SimpleNamespace(socket=k.get('sock') or a[0],is_verified=True)
       with patch.object(t,'create_connection',conn), patch.object(urllib3.connection,'_ssl_wrap_socket_and_match_hostname',tls),patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')):
        r=t.post(url,endpoint=ep,json={},timeout=1,allow_redirects=False);assert r.json()=={};r.close()
       assert connects==[(proxy.address,8080) if proxy else (address,ep.port)],(host,scheme,proxy_scheme,connects)
       expected=([proxy.host] if proxy_scheme=='https' else [])+([host] if scheme=='https' else [])
       assert names==expected,(host,scheme,proxy_scheme,names,expected)
       print('PASS requests',host,scheme,proxy_scheme or 'direct')
    for host,address in [('model.invalid','8.8.8.8'),('::1','::1')]:
     for scheme in ['http','https']:
      for proxy_scheme in [None,'http','https']:
       proxy=t.BoundEndpoint('proxy.invalid',8080,'9.9.9.9',proxy_scheme) if proxy_scheme else None
       ep=t.BoundEndpoint(host,443 if scheme=='https' else 80,address,scheme,proxy,f'{proxy_scheme}://proxy.invalid:8080' if proxy else None)
       url=f'{scheme}://'+(f'[{host}]' if ':' in host else host)+'/v1/chat/completions'
       writes=[]; names=[]; connects=[]
       class Stream(httpcore.AsyncNetworkStream):
        async def read(self,*a,**kw):return b'HTTP/1.1 200 Connection established\r\n\r\n' if writes[-1].startswith(b'CONNECT') else b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}'
        async def write(self,data,*a,**kw):
         if data:writes.append(data)
        async def aclose(self):pass
        def get_extra_info(self,key):return None
        async def start_tls(self,ssl_context,server_hostname=None,timeout=None):
         names.append(server_hostname); assert ssl_context.check_hostname and ssl_context.verify_mode==2;return self
       async def connect(self,host,port,**kw):connects.append((host,port));return Stream()
       async def run():
        wire,headers=t.proxy_request(url,{},ep)
        async with httpx.AsyncClient(transport=t.async_transport(ep),trust_env=False) as client:
         r=await client.post(wire,headers=headers,json={});assert r.json()=={}
       with patch.object(httpcore.AnyIOBackend,'connect_tcp',connect),patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')):
        asyncio.run(run())
       assert connects==[(proxy.address,8080) if proxy else (address,ep.port)],(host,scheme,proxy_scheme,connects)
       expected=([proxy.host] if proxy_scheme=='https' else [])+([host] if scheme=='https' else [])
       assert names==expected,(host,scheme,proxy_scheme,names,expected)
       print('PASS httpx',host,scheme,proxy_scheme or 'direct')

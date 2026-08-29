import json, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9222/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '') and 'ffa/g/create' in (x.get('url') or '')), None)
if not t:
    for port in (9223, 9400):
        try:
            targets = json.loads(urlopen(f'http://127.0.0.1:{port}/json/list', timeout=3).read())
            t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), None)
            if t: break
        except: continue
if not t:
    print('No publish page')
    sys.exit(1)

ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
mid=[0]
def cdp(m,p=None):
    mid[0]+=1; ws.send(json.dumps({'id':mid[0],'method':m,'params':p or {}}))
    dl=time.time()+20
    while time.time()<dl:
        raw=ws.recv();msg=json.loads(raw)
        if msg.get('id')==mid[0]: return msg
    return {}

cdp('Runtime.enable')
cdp('Fetch.enable', {'patterns': [{'urlPattern': '*addWithSchema*', 'requestStage': 'Request'}]})

# 检查页面状态
r = cdp('Runtime.evaluate', {
    'expression': "JSON.stringify({url:location.href,title:document.title,errs:Array.from(document.querySelectorAll('.style_errorSubTitle__mjzpJ')).map(function(e){return e.textContent.trim()}).slice(0,8),pubBtn:Array.from(document.querySelectorAll('button')).filter(function(b){return(b.textContent||'').indexOf('发布')!==-1&&b.offsetHeight>0}).length})",
    'returnByValue': True
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
d = json.loads(val)
print('Errors:', d.get('errs',[]))
print('Publish btn:', d.get('pubBtn',0))

# 如果有发布按钮，直接点击+拦截
if d.get('pubBtn', 0) > 0:
    print('Clicking publish...')
    cdp('Runtime.evaluate', {
        'expression': "var b=document.querySelectorAll('button');for(var i=0;i<b.length;i++){if((b[i].textContent||'').indexOf('发布')!==-1&&b[i].offsetHeight>0&&!b[i].disabled){b[i].click();break;}}",
        'returnByValue': True
    })
    
    deadline = time.time() + 30
    while time.time() < deadline:
        try: raw = ws.recv()
        except: break
        try: msg = json.loads(raw)
        except: continue
        if msg.get('method') == 'Fetch.requestPaused' and 'addWithSchema' in msg['params']['request']['url']:
            req = msg['params']['request']; rid = msg['params']['requestId']
            pd = req.get('postData','')
            body_data = json.loads(pd) if pd else {}
            print('\n=== TOKEN CAPTURED ===')
            print('__token:', body_data.get('__token','')[:40])
            at = body_data.get('request_extra',{}).get('_aToken','')
            print('_aToken:', at[:50])
            print('n_token:', body_data.get('context',{}).get('n_token','')[:40])
            
            out = r'E:\Script Project\Dyin\beiufen\2.0\tmp_runtime_probe_live\token_NOW.json'
            with open(out, 'w', encoding='utf-8') as f:
                json.dump({'url':req['url'],'postData':pd,'headers':req.get('headers',{})}, f, ensure_ascii=False, indent=2)
            print(f'Saved: {out}')
            
            cdp('Fetch.continueRequest', {'requestId': rid})
            ws.close()
            sys.exit(0)

ws.close()
print('Not captured - form may have validation errors')

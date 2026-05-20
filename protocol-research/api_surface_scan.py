# -*- coding: utf-8 -*-
"""全景 API 测绘: 测试所有只读端点, 挖掘有用功能"""
import json, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9222/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), targets[0])
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
ws.settimeout(3)
mid = [0]

def cdp(m, p=None, timeout=20):
    mid[0] += 1
    ws.send(json.dumps({'id': mid[0], 'method': m, 'params': p or {}}))
    dl = time.time() + timeout
    while time.time() < dl:
        try:
            raw = ws.recv()
            msg = json.loads(raw)
            if msg.get('id') == mid[0]:
                return msg
        except:
            continue
    return {}

cdp('Runtime.enable')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) { window.__fxgWebpackRequire = req; }]);
            window.__fxgPost = window.__fxgWebpackRequire(90665).bE;
            window.__fxgGet = window.__fxgWebpackRequire(28974).J;
            return JSON.stringify({ok: true});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})

# 有意义的只读/非提交端点
endpoints = {
    'GET (read)': {
        '/product/tproduct/list': {'page': 1, 'size': 3},
        '/product/tproduct/getCategoryDetail': {'category_id': '1000010267'},
        '/product/tproduct/getCategoryDocument': {'category_id': '1000010267'},
        '/product/tproduct/getRecommendTitle': {'category_id': '1000010267'},
        '/product/tproduct/getTag': {},
        '/product/tproduct/getShareButtonConfig': {},
        '/product/tproduct/getBadWordHint': {'text': '测试'},
        '/product/tproduct/searchCategoryN': {'name': '袜子', 'level': 1},
        '/product/tproduct/getCascadeList': {'category_id': '1000010267'},
        '/product/tproduct/predictCategoryN': {'title': '夏季薄款中筒棉袜'},
        '/product/tproduct/getNativeCode': {},
        '/product/tproduct/listBanner': {},
        '/product/tproduct/getFeedbackParentProperty': {'category_id': '1000010267'},
        '/product/tproduct/brandPrefix': {},
    },
    'POST (probe)': {
        '/product/tproduct/getProductTemplate': {},
        '/product/tproduct/listProductTemplate': {},
        '/product/tproduct/collectInfo': {},
        '/product/tproduct/getPreGeneratedMaterial': {},
        '/product/tproduct/previewDetail': {},
        '/product/attribute/check': {},
    }
}

results = {}

for method, eps in endpoints.items():
    for path, body in eps.items():
        args = {'timeout': 10000}
        if method == 'GET (read)':
            qs = '&'.join(f'{k}={v}' for k, v in body.items())
            url = f'{path}?{qs}' if qs else path
            expr = f'''
                (async function() {{
                    var result = await window.__fxgGet('{url}', {{timeout: 10000}});
                    return JSON.stringify({{code: result.code||result.errno, msg: (result.msg||'').substring(0, 80), hasData: !!result.data}});
                }})()
            '''
        else:
            body_json = json.dumps(body, ensure_ascii=False)
            expr = f'''
                (async function() {{
                    try {{
                        var result = await window.__fxgPost('{path}', {body_json}, {{timeout: 10000}});
                        return JSON.stringify({{code: result.code||result.errno, msg: (result.msg||'').substring(0, 80), hasData: !!result.data}});
                    }} catch(e) {{
                        return JSON.stringify({{code: e.code||e.errno, msg: (e.msg||e.message||'').substring(0, 80), hasData: false}});
                    }}
                }})()
            '''

        r = cdp('Runtime.evaluate', {
            'expression': expr,
            'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
        })
        val = ((r.get('result') or {}).get('result') or {}).get('value', '')
        result = json.loads(val) if isinstance(val, str) else (val or {})
        code = result.get('code', '?')
        has_data = result.get('hasData', False)
        msg = result.get('msg', '')
        status = 'DATA' if has_data else ('OK' if code == 0 else f'ERR:{code}')
        print(f'  {status:10s} {path:55s} {msg[:60]}')
        results[f'{path}'] = {'code': code, 'hasData': has_data, 'msg': msg}

print()
print('='*60)
print(f'Scanned {len(results)} endpoints')
useful = [k for k, v in results.items() if v['hasData']]
print(f'With data: {len(useful)}')
for u in useful:
    print(f'  USEFUL: {u}')

ws.close()

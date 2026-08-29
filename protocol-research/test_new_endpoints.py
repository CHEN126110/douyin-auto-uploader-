# -*- coding: utf-8 -*-
"""测试新发现的 API 端点: canCreateGood, batch, publishClickStat"""
import json, time, datetime, random, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9222/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), targets[0])
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
ws.settimeout(3)
mid = [0]

def cdp(m, p=None, timeout=25):
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

# inject webpack
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) { window.__fxgWebpackRequire = req; }]);
            var r = window.__fxgWebpackRequire;
            window.__fxgPost = r(90665).bE;
            window.__fxgGet = r(28974).J;
            return JSON.stringify({ok: true});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})

# ============================================================
# 1. canCreateGood — 发布前预检
# ============================================================
print('='*60)
print('Test 1: canCreateGood (pre-flight check)')
print('='*60)

for create_flag in ['1', '0']:
    r = cdp('Runtime.evaluate', {
        'expression': f'''
            (async function() {{
                try {{
                    var result = await window.__fxgGet('/product/tproduct/canCreateGood?is_create={create_flag}', {{timeout: 10000}});
                    return JSON.stringify({{errno: result.errno, code: result.code, msg: result.msg, data: result.data ? JSON.stringify(result.data).substring(0, 500) : null}});
                }} catch(e) {{
                    return JSON.stringify({{error: true, errno: e.errno, code: e.code, msg: e.msg}});
                }}
            }})()
        ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
    })
    val = ((r.get('result') or {}).get('result') or {}).get('value', '')
    result = json.loads(val) if isinstance(val, str) else (val or {})
    print(f'  is_create={create_flag}: code={result.get("code")} msg="{result.get("msg","")}" data={result.get("data","")[:300]}')

# ============================================================
# 2. batch — 批量创建
# ============================================================
print()
print('='*60)
print('Test 2: batch endpoint')
print('='*60)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            try {
                var result = await window.__fxgPost('/product/tproduct/batch', {}, {timeout: 10000});
                return JSON.stringify({errno: result.errno, code: result.code, msg: result.msg, data: result.data ? JSON.stringify(result.data).substring(0, 300) : null});
            } catch(e) {
                return JSON.stringify({error: true, errno: e.errno, code: e.code, msg: e.msg});
            }
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
result = json.loads(val) if isinstance(val, str) else (val or {})
print(f'  POST batch(empty): code={result.get("code")} msg="{result.get("msg","")}"')

# ============================================================
# 3. publishClickStat — 发布点击统计
# ============================================================
print()
print('='*60)
print('Test 3: publishClickStat (behavior tracking)')
print('='*60)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            try {
                var result = await window.__fxgPost('/product/tproduct/publishClickStat', {
                    click_type: 'manual',
                    product_id: '0',
                    check_status: 2
                }, {timeout: 10000});
                return JSON.stringify({errno: result.errno, code: result.code, msg: result.msg, data: result.data ? JSON.stringify(result.data).substring(0, 200) : null});
            } catch(e) {
                return JSON.stringify({error: true, errno: e.errno, code: e.code, msg: e.msg});
            }
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
result = json.loads(val) if isinstance(val, str) else (val or {})
print(f'  publishClickStat: code={result.get("code")} msg="{result.get("msg","")}"')

# ============================================================
# 4. searchSpuN — SPU 搜索 (可能触发不同的认证路径)
# ============================================================
print()
print('='*60)
print('Test 4: searchSpuN (SPU search)')
print('='*60)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            try {
                var result = await window.__fxgPost('/product/tproduct/searchSpuN', {
                    query: '中筒袜',
                    category_id: '1000010267',
                    page: 1,
                    size: 5
                }, {timeout: 10000});
                return JSON.stringify({errno: result.errno, code: result.code, msg: result.msg, data: result.data ? 'exists' : null});
            } catch(e) {
                return JSON.stringify({error: true, errno: e.errno, code: e.code, msg: e.msg});
            }
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
result = json.loads(val) if isinstance(val, str) else (val or {})
print(f'  searchSpuN: code={result.get("code")} msg="{result.get("msg","")}"')

# ============================================================
# 5. list — 获取商品列表 (验证请求通道)
# ============================================================
print()
print('='*60)
print('Test 5: product list (verify request channel works)')
print('='*60)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            try {
                var result = await window.__fxgPost('/product/tproduct/list', {
                    page: 1,
                    size: 2,
                    status: 'all'
                }, {timeout: 10000});
                return JSON.stringify({errno: result.errno, code: result.code, msg: result.msg, data: result.data ? 'exists(' + JSON.stringify(result.data).length + ')' : null});
            } catch(e) {
                return JSON.stringify({error: true, errno: e.errno, code: e.code, msg: e.msg});
            }
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
result = json.loads(val) if isinstance(val, str) else (val or {})
print(f'  list: code={result.get("code")} msg="{result.get("msg","")}"')

# ============================================================
# 6. categoryOptionsN — 类目选项 (验证参数)
# ============================================================
print()
print('='*60)
print('Test 6: categoryOptionsN (property suggestions)')
print('='*60)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            try {
                var result = await window.__fxgPost('/product/tproduct/categoryOptionsN', {
                    category_id: '1000010267',
                    property_id: '785',
                    value_name: '棉'
                }, {timeout: 10000});
                return JSON.stringify({errno: result.errno, code: result.code, msg: result.msg, data: result.data ? 'exists' : null});
            } catch(e) {
                return JSON.stringify({error: true, errno: e.errno, code: e.code, msg: e.msg});
            }
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
result = json.loads(val) if isinstance(val, str) else (val or {})
print(f'  categoryOptionsN: code={result.get("code")} msg="{result.get("msg","")}"')

ws.close()

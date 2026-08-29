# -*- coding: utf-8 -*-
"""深挖: 封锁后状态分析 + batch端点 + __token刷新 + 不同Appid"""
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
# 1. 封锁后 canCreateGood 状态
# ============================================================
print('='*60)
print('1. Post-block canCreateGood status')
print('='*60)

for params in ['is_create=1', 'is_create=0']:
    r = cdp('Runtime.evaluate', {
        'expression': f'''
            (async function() {{
                var result = await window.__fxgGet('/product/tproduct/canCreateGood?{params}', {{timeout: 10000}});
                return JSON.stringify({{errno: result.errno, code: result.code, msg: result.msg, data: JSON.stringify(result.data)}});
            }})()
        ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
    })
    val = ((r.get('result') or {}).get('result') or {}).get('value', '')
    result = json.loads(val) if isinstance(val, str) else (val or {})
    print(f'  {params}: {result.get("data","")[:500]}')

# ============================================================
# 2. 提取当前 __token 值
# ============================================================
print()
print('='*60)
print('2. __token analysis')
print('='*60)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var cookies = document.cookie.split(';');
            var tokens = {};
            cookies.forEach(function(c) {
                var parts = c.trim().split('=');
                var key = parts[0].trim();
                if (key.includes('token') || key.includes('csrf') || key.includes('session')) {
                    tokens[key] = parts.slice(1).join('=').substring(0, 40);
                }
            });
            // Also get __token from webpack context
            return JSON.stringify(tokens);
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 5000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  Token cookies: {val[:500]}')

# ============================================================
# 3. 测试 batch 端点 (带正确参数格式)
# ============================================================
print()
print('='*60)
print('3. Batch endpoint test')
print('='*60)

# 尝试不同 body 格式
batch_tests = [
    ('empty', {}),
    ('array', []),
    ('products_array', {'products': []}),
    ('list_array', {'list': []}),
    ('data_array', {'data': []}),
    ('batch_request', {'batch_request': {'products': []}}),
]

for label, body in batch_tests:
    body_json = json.dumps(body, ensure_ascii=False)
    r = cdp('Runtime.evaluate', {
        'expression': f'''
            (async function() {{
                try {{
                    var result = await window.__fxgPost('/product/tproduct/batch', {body_json}, {{timeout: 10000}});
                    return JSON.stringify({{errno: result.errno, code: result.code, msg: result.msg}});
                }} catch(e) {{
                    return JSON.stringify({{error: true, errno: e.errno, code: e.code, msg: e.msg}});
                }}
            }})()
        ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
    })
    val = ((r.get('result') or {}).get('result') or {}).get('value', '')
    result = json.loads(val) if isinstance(val, str) else (val or {})
    print(f'  {label}: code={result.get("code")} msg="{result.get("msg","")}"')

# ============================================================
# 4. 搜索 webpack 中 batch 的调用方式
# ============================================================
print()
print('='*60)
print('4. Batch endpoint source code')
print('='*60)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            var chunk = window[chunkName];
            var full = JSON.stringify(chunk, function(k,v) {
                if (typeof v === 'function') return v.toString();
                return v;
            });

            // Find context around batch endpoint usage
            var idx = full.indexOf('/product/tproduct/batch');
            var results = {};
            if (idx >= 0) {
                results.ctx1 = full.substring(Math.max(0, idx - 300), idx + 500);
                // Find second occurrence
                var idx2 = full.indexOf('/product/tproduct/batch', idx + 1);
                if (idx2 >= 0) {
                    results.ctx2 = full.substring(Math.max(0, idx2 - 300), idx2 + 500);
                }
            }

            // Also search for 'batchLaunch' or 'batchPublish' or 'batchCreate'
            var batchPatterns = ['batchLaunch', 'batchPublish', 'batchCreate', 'batchUpload', 'batchAdd'];
            batchPatterns.forEach(function(p) {
                var bi = full.indexOf(p);
                if (bi >= 0) {
                    results[p] = full.substring(Math.max(0, bi - 200), bi + 300);
                }
            });

            return JSON.stringify(results);
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 30000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:4000]}')

# ============================================================
# 5. 测试用不同 X-TT-From-Appid
# ============================================================
print()
print('='*60)
print('5. Alternative app IDs')
print('='*60)

# 搜索 webpack 中所有 X-TT-From-Appid 值
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            var chunk = window[chunkName];
            var full = JSON.stringify(chunk, function(k,v) {
                if (typeof v === 'function') return v.toString();
                return v;
            });

            // Find X-TT-From-Appid values
            var pattern = /X-TT-From-Appid[^"]*"([^"]+)"/g;
            var matches = [];
            var m;
            while ((m = pattern.exec(full)) !== null) {
                if (matches.indexOf(m[1]) < 0) matches.push(m[1]);
            }

            // Also find appid in URLs
            var appidPattern = /appid[=:]\s*(\d+)/g;
            var appids = [];
            while ((m = appidPattern.exec(full)) !== null) {
                if (appids.indexOf(m[1]) < 0) appids.push(m[1]);
            }

            return JSON.stringify({appIds: appids, fromAppIds: matches});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 30000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:1000]}')

# ============================================================
# 6. 查找所有 \"Launch\" / \"Publish\" 相关的 API
# ============================================================
print()
print('='*60)
print('6. Alternative publish endpoints')
print('='*60)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            var chunk = window[chunkName];
            var full = JSON.stringify(chunk, function(k,v) {
                if (typeof v === 'function') return v.toString();
                return v;
            });

            // Find all API paths with launch/publish/batch/create keywords
            var patterns = [
                /\\/product\\/[^'\\]*launch[^'\\]*/g,
                /\\/product\\/[^'\\]*publish[^'\\]*/g,
                /\\/product\\/[^'\\]*batch[^'\\]*/g,
                /\\/product\\/[^'\\]*create[^'\\]*/g,
                /\\/product\\/[^'\\]*import[^'\\]*/g,
                /\\/tproduct\\/[^'\\]*launch[^'\\]*/g,
                /\\/tproduct\\/[^'\\]*publish[^'\\]*/g,
            ];

            var found = new Set();
            patterns.forEach(function(p) {
                var matches = full.match(p) || [];
                matches.forEach(function(m) { found.add(m); });
            });

            return JSON.stringify({paths: Array.from(found).sort()});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 30000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:2000]}')

ws.close()

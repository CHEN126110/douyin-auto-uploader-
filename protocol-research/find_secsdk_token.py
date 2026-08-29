# -*- coding: utf-8 -*-
"""查找安全 SDK 的 _aToken 生成函数。"""
import json, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9222/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), targets[0])
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
ws.settimeout(2)
mid = [0]

def send_cdp(m, p=None):
    mid[0] += 1
    ws.send(json.dumps({'id': mid[0], 'method': m, 'params': p or {}}))
    return mid[0]

def recv_until(msg_id, timeout_sec=30):
    dl = time.time() + timeout_sec
    while time.time() < dl:
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        except:
            break
        try:
            msg = json.loads(raw)
        except:
            continue
        if msg.get('id') == msg_id:
            return msg
    return {}

# 1. Search for secsdk, _aToken, request_extra in ALL page scripts
print('[1] Searching all scripts on page...')
send_cdp('Runtime.enable')
recv_until(mid[0], timeout_sec=5)

send_cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = {inlineScripts: [], externalScripts: []};
            var scripts = document.querySelectorAll('script');
            scripts.forEach(function(s, i) {
                var src = s.src || '';
                var text = s.textContent || '';
                if (text.includes('_aToken') || text.includes('aToken') || text.includes('request_extra') || text.includes('secsdk')) {
                    if (src) {
                        results.externalScripts.push({index: i, src: src.substring(0, 120)});
                    } else {
                        // Find the relevant snippet
                        var idx = text.indexOf('_aToken');
                        if (idx < 0) idx = text.indexOf('request_extra');
                        if (idx < 0) idx = text.indexOf('secsdk');
                        results.inlineScripts.push({
                            index: i,
                            snippet: text.substring(Math.max(0, idx - 30), idx + 150)
                        });
                    }
                }
            });
            return JSON.stringify(results);
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 10000
})
r = recv_until(mid[0], timeout_sec=15)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:1000]}')

# 2. Search window/global objects for secsdk/token generators
print('[2] Searching global objects for security SDK...')
send_cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var found = [];
            var searchTerms = ['secsdk', 'acrawler', 'byted', '_aToken', 'aToken', 'csrf', 'sign', 'bogus', 'msToken'];

            // Search window properties
            for (var k in window) {
                var kLower = k.toLowerCase();
                for (var t = 0; t < searchTerms.length; t++) {
                    if (kLower.includes(searchTerms[t].toLowerCase())) {
                        try {
                            var v = window[k];
                            var type = typeof v;
                            if (type === 'function') {
                                found.push({key: k, type: 'function', str: v.toString().substring(0, 120)});
                            } else if (type === 'string' && v.length < 200) {
                                found.push({key: k, type: 'string', val: v.substring(0, 80)});
                            } else if (type === 'object' && v !== null) {
                                found.push({key: k, type: 'object', keys: Object.keys(v).slice(0, 10)});
                            } else {
                                found.push({key: k, type: type});
                            }
                        } catch(e) {
                            found.push({key: k, type: 'error'});
                        }
                    }
                }
            }

            // Also check document.currentScript and nearby scripts
            return JSON.stringify({windowItems: found.slice(0, 20)});
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 10000
})
r = recv_until(mid[0], timeout_sec=15)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
result = json.loads(val) if val else {}
print(f'    Window items: {json.dumps(result.get("windowItems", [])[:5], ensure_ascii=False)[:800]}')

# 3. Check cookies for secsdk tokens
print('[3] Checking cookies from CDP...')
send_cdp('Network.enable')
recv_until(mid[0], timeout_sec=5)

send_cdp('Network.getAllCookies')
r = recv_until(mid[0], timeout_sec=10)
cookies = ((r.get('result') or {}).get('cookies') or [])
# Filter for relevant cookies
relevant = [c for c in cookies if any(t in (c.get('name','')+c.get('domain','')).lower()
    for t in ['token','csrf','sec','sdk','sign','bid','uid','session'])]
print(f'    Relevant cookies ({len(relevant)}):')
for c in relevant[:20]:
    print(f'      {c["name"]} = {c.get("value","")[:60]}... (domain: {c.get("domain","")})')

# 4. Try to extract _aToken by making a lightweight API call through the page
print('[4] Trying to extract _aToken from page network interceptor...')
# Enable Network tracking for addWithSchema specifically
send_cdp('Fetch.enable', {
    'patterns': [{'urlPattern': '*getSchema*', 'requestStage': 'Request'}]
})
recv_until(mid[0], timeout_sec=5)

# Make a getSchema request and capture all auth headers/body
send_cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            // Use the page's post function to make a getSchema request
            // This will go through all auth interceptors
            if (!window.__fxgWebpackRequire) {
                var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
                window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) {
                    window.__fxgWebpackRequire = req;
                }]);
            }
            var req = window.__fxgWebpackRequire;
            var post = req(90665).bE;
            var pid = req(68671).T({useUrlParams: true, useWindowCache: true});

            var result = await post('/product/tproduct/getSchema', {
                context: {
                    category_id: '1000010267',
                    operation_type: 'normal',
                    ability: [],
                    feature: {session_publish_id: 'helper_' + pid}
                },
                model: void 0
            }, {timeout: 15000});

            return JSON.stringify({errno: result.errno, code: result.code, msg: result.msg, hasData: !!result.data});
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 20000
})
sid = mid[0]

# Wait and collect Fetch events
dl = time.time() + 25
intercepted_schema = []
while time.time() < dl:
    try:
        raw = ws.recv()
    except websocket.WebSocketTimeoutException:
        continue
    except:
        break
    try:
        msg = json.loads(raw)
    except:
        continue

    rid = msg.get('id')
    method = msg.get('method', '')

    if method == 'Fetch.requestPaused':
        params = msg.get('params', {})
        req = params.get('request', {})
        url = req.get('url', '')
        post_data = req.get('postData', '')
        headers = req.get('headers', {})
        print(f'\n    Intercepted getSchema: {url[:200]}')
        print(f'    Headers: {json.dumps({k:v for k,v in headers.items() if k not in ("Cookie",)}, ensure_ascii=False)[:300]}')
        print(f'    Body: {post_data[:300]}')
        intercepted_schema.append({'url': url, 'body': post_data, 'headers': headers})
        send_cdp('Fetch.continueRequest', {'requestId': params.get('requestId', '')})

    if rid == sid:
        val = ((msg.get('result') or {}).get('result') or {}).get('value', '')
        print(f'\n    Result: {val[:300]}')
        break

# 5. Now try to find the _aToken generator by examining the body transformer
print('\n[5] Examining webpack post interceptor chain...')
send_cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var req = window.__fxgWebpackRequire;
            // post function source analysis
            var postFn = req(90665).bE;

            // Look at what variables are captured in the closure
            // The post function toString shows it calls eJ(e,t,"request")
            // Let's find eJ function
            var results = {};

            // Search the chunk's module map for functions that handle request body transformation
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            var modules = window[chunkName][1];

            // Find modules that contain 'request_extra', '_aToken', 'aToken', 'secsdk'
            var atokenMods = [];
            var bodyTransformMods = [];
            Object.keys(modules).forEach(function(k) {
                var src = String(modules[k]);
                if (src.includes('_aToken') || src.includes('request_extra')) {
                    atokenMods.push(k);
                }
                if (src.includes('body') && (src.includes('transform') || src.includes('interceptor') || src.includes('request'))) {
                    bodyTransformMods.push(k);
                }
            });

            results.atokenModules = atokenMods;
            results.bodyModules = bodyTransformMods.slice(0, 20);
            results.totalModules = Object.keys(modules).length;

            // Also check: does module 90665 import/require other modules?
            var postModSrc = String(modules['90665'] || '');
            results.postModLength = postModSrc.length;
            // Extract require calls from post module
            var requireCalls = postModSrc.match(/req\(\d+\)/g) || [];
            results.postRequires = requireCalls.slice(0, 30);

            return JSON.stringify(results);
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 10000
})
r = recv_until(mid[0], timeout_sec=15)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:1500]}')

ws.close()

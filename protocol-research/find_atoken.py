# -*- coding: utf-8 -*-
"""在页面中搜索 _aToken 生成逻辑和 request_extra 构造方式。"""
import json, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9222/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), targets[0])
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
ws.settimeout(2)
mid = [0]

def cdp(m, p=None, timeout=20):
    mid[0] += 1
    msg_id = mid[0]
    ws.send(json.dumps({'id': msg_id, 'method': m, 'params': p or {}}))
    dl = time.time() + timeout
    while time.time() < dl:
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        try:
            msg = json.loads(raw)
        except:
            continue
        if msg.get('id') == msg_id:
            return msg
        # Log other events
        if msg.get('method') == 'Runtime.consoleAPICalled':
            pass  # ignore console
    return {}

# Enable Runtime
cdp('Runtime.enable')

# 1. Search for _aToken in all scripts
print('[1] Searching for _aToken in page...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = [];
            // Search all script tags
            var scripts = document.querySelectorAll('script');
            scripts.forEach(function(s, i) {
                if (s.textContent && s.textContent.includes('_aToken')) {
                    results.push({type: 'script_tag', index: i, src: s.src ? s.src.substring(0, 80) : 'inline'});
                }
            });
            // Search webpack modules
            if (window.__fxgWebpackRequire) {
                // Try to search the webpack chunk for _aToken
                var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
                if (chunkName) {
                    // The chunk is an array of [moduleId, moduleSource]
                    var modules = window[chunkName];
                    if (modules && modules.length > 0) {
                        // Second element is the module map
                        var modMap = modules[1];
                        if (modMap) {
                            results.push({type: 'webpack_module_count', count: Object.keys(modMap).length});
                            // Search module source for _aToken
                            var found = [];
                            Object.keys(modMap).forEach(function(k) {
                                var src = String(modMap[k]);
                                if (src.includes('_aToken') || src.includes('aToken')) {
                                    found.push(k);
                                }
                            });
                            results.push({type: 'aToken_modules', ids: found});
                        }
                    }
                }
            }
            return JSON.stringify(results);
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:500]}')

# 2. Try to find the webpack module that generates request_extra / _aToken
print('[2] Searching for request_extra construction...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = {};
            if (!window.__fxgWebpackRequire) {
                var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
                window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) {
                    window.__fxgWebpackRequire = req;
                }]);
            }
            var req = window.__fxgWebpackRequire;

            // Try to find modules related to request_extra, aToken, anti-bot
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            var modules = window[chunkName][1];

            // Search for key terms
            var searches = ['request_extra', 'aToken', '_aToken', 'secsdk', 'csrf', 'bogus', 'msToken'];
            var found = {};
            searches.forEach(function(term) {
                var ids = [];
                Object.keys(modules).forEach(function(k) {
                    if (String(modules[k]).includes(term)) {
                        ids.push(k);
                    }
                });
                if (ids.length > 0) found[term] = ids;
            });

            results.module_searches = found;
            return JSON.stringify(results);
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
result = json.loads(val) if val else {}
print(f'    {json.dumps(result, ensure_ascii=False)[:1500]}')

# 3. Try to find _aToken from window/global scope
print('[3] Searching for _aToken in global scope...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = {};
            // Check common global objects
            var globals = [window, window.__fxgReq, window.__fxgWebpackRequire];
            var found = [];
            // Search window for _aToken related properties
            Object.keys(window).forEach(function(k) {
                if (k.toLowerCase().includes('atoken') || k.toLowerCase().includes('token') && k.length < 30) {
                    try {
                        var v = window[k];
                        if (typeof v === 'string' && v.length < 200) {
                            found.push({key: k, val: v.substring(0, 80)});
                        }
                    } catch(e) {}
                }
            });
            results.windowTokens = found.slice(0, 10);

            // Try to call window.__secsdk to get csrf token
            if (typeof window.byted_acrawler !== 'undefined') {
                results.has_byted_acrawler = true;
            }
            if (typeof window.__secsdk_csrftoken !== 'undefined') {
                results.csrf = String(window.__secsdk_csrftoken).substring(0, 50);
            }

            return JSON.stringify(results);
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:800]}')

# 4. The most practical approach: capture _aToken from a real page request
# Let's try to make a simple request through the page and capture it
print('[4] Capturing _aToken from page context...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            // Check if there's an _aToken in the current page state
            // Often it's stored in sessionStorage, localStorage, or a global variable
            var storage = {};
            try {
                for (var i = 0; i < sessionStorage.length; i++) {
                    var key = sessionStorage.key(i);
                    if (key && (key.includes('token') || key.includes('Token'))) {
                        storage['session_' + key] = sessionStorage.getItem(key).substring(0, 50);
                    }
                }
                for (var i = 0; i < localStorage.length; i++) {
                    var key = localStorage.key(i);
                    if (key && (key.includes('token') || key.includes('Token'))) {
                        storage['local_' + key] = localStorage.getItem(key).substring(0, 50);
                    }
                }
            } catch(e) {}

            // Check cookies
            var cookieTokens = document.cookie.split(';').filter(function(c) {
                return c.toLowerCase().includes('token') || c.toLowerCase().includes('csrf');
            }).map(function(c) { return c.trim().substring(0, 80); });

            return JSON.stringify({storage: storage, cookies: cookieTokens});
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:1000]}')

ws.close()

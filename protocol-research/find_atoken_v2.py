# -*- coding: utf-8 -*-
"""深入追踪 _aToken 来源: React fiber, webpack模块, 安全SDK"""
import json, time, sys, os
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

# ============================================================
# 1. 通过 React fiber 查找 _aToken 相关的 state/props
# ============================================================
print('[1] Searching React fiber tree for _aToken...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = {found: [], searched: 0};
            var rootEl = document.getElementById('app');
            if (!rootEl) return JSON.stringify({error: 'no #app'});

            var fiberKey = Object.keys(rootEl).find(function(k) { return k.startsWith('__react'); });
            if (!fiberKey) return JSON.stringify({error: 'no react fiber key', keys: Object.keys(rootEl).slice(0, 10)});

            results.fiberKey = fiberKey;

            // Walk the fiber tree looking for _aToken or request_extra
            function walkFiber(fiber, depth) {
                if (!fiber || depth > 20 || results.searched > 50000) return;
                results.searched++;

                // Check memoizedState and memoizedProps for _aToken
                try {
                    var state = fiber.memoizedState;
                    var props = fiber.memoizedProps;
                    var strState = JSON.stringify(state);
                    var strProps = JSON.stringify(props);

                    if (strState.includes('_aToken') || strState.includes('request_extra')) {
                        results.found.push({type: 'memoizedState', depth: depth, tag: fiber.tag, snippet: strState.substring(0, 200)});
                    }
                    if (strProps.includes('_aToken') || strProps.includes('request_extra')) {
                        results.found.push({type: 'memoizedProps', depth: depth, tag: fiber.tag, snippet: strProps.substring(0, 200)});
                    }
                } catch(e) {}

                // Also check for pending props and update queue
                try {
                    var pq = fiber.pendingProps;
                    if (pq && JSON.stringify(pq).includes('_aToken')) {
                        results.found.push({type: 'pendingProps', depth: depth, tag: fiber.tag, snippet: JSON.stringify(pq).substring(0, 200)});
                    }
                } catch(e) {}

                // Check the return (parent) for context
                walkFiber(fiber.child, depth + 1);
                walkFiber(fiber.sibling, depth);
            }

            walkFiber(rootEl[fiberKey], 0);

            return JSON.stringify(results);
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 30000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:1500]}')

# ============================================================
# 2. 搜索 webpack chunk 中所有含有 _aToken/request_extra 的代码
# ============================================================
print('\n[2] Deep search in webpack modules...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = {};
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            if (!chunkName) return JSON.stringify({error: 'chunk not found'});

            var chunkData = window[chunkName];
            results.chunkType = typeof chunkData;
            results.chunkIsArray = Array.isArray(chunkData);

            // Try to stringify the entire chunk and search
            try {
                var fullStr = JSON.stringify(chunkData, function(key, val) {
                    if (typeof val === 'function') return val.toString();
                    return val;
                });
                results.fullLen = fullStr.length;
                var atokenIdx = fullStr.indexOf('_aToken');
                var reqExtraIdx = fullStr.indexOf('request_extra');
                if (atokenIdx >= 0) {
                    results.aTokenSnippet = fullStr.substring(Math.max(0, atokenIdx - 100), atokenIdx + 200);
                }
                if (reqExtraIdx >= 0) {
                    results.reqExtraSnippet = fullStr.substring(Math.max(0, reqExtraIdx - 100), reqExtraIdx + 200);
                }
            } catch(e) {
                results.stringifyError = e.message;
            }

            // Try to dump the first level structure
            if (Array.isArray(chunkData)) {
                results.arrayLen = chunkData.length;
                results.itemTypes = chunkData.map(function(item, i) {
                    if (typeof item === 'object' && item !== null) {
                        return 'obj:' + Object.keys(item).length + 'keys';
                    }
                    return typeof item;
                });
            }

            return JSON.stringify(results);
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:2000]}')

# ============================================================
# 3. 监控 Network — 查找页面的任何 addWithSchema 请求来提取 _aToken
# ============================================================
print('\n[3] Setting up Network monitoring to capture _aToken from page...')
cdp('Network.enable')

# 查看最近有无 addWithSchema 请求
time.sleep(1)
print('  (Network monitoring active — waiting for any addWithSchema traffic)')

# ============================================================
# 4. 尝试从 secsdk.glue / bdms SDK 获取 _aToken
# ============================================================
print('\n[4] Probing security SDKs for _aToken generation...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = {};

            // bdms SDK
            if (window.bdms) {
                results.bdmsKeys = Object.keys(window.bdms).slice(0, 20);
                if (window.bdms._aToken) results.bdms_aToken = window.bdms._aToken.substring(0, 50);
                if (typeof window.bdms.getToken === 'function') {
                    try { results.bdmsToken = window.bdms.getToken(); } catch(e) {}
                }
            }

            // _sdkGlue
            if (window._sdkGlueVersionMap) {
                results.sdkGlueVersionMap = window._sdkGlueVersionMap;
            }
            if (window._SdkGlueInit) {
                results.sdkGlueInit = typeof window._SdkGlueInit;
            }

            // __glue_t
            if (window.__glue_t) {
                results.glue_t_type = typeof window.__glue_t;
                if (typeof window.__glue_t === 'object') {
                    results.glue_t_keys = Object.keys(window.__glue_t).slice(0, 10);
                }
            }

            // Try to find the function that creates _aToken from secsdk
            // The secsdk might have a method like 'sign' or 'encrypt' that generates _aToken
            if (window.secsdk) {
                // Deep inspect secsdk for any method that takes a body and returns a string
                var allMethods = [];
                var obj = window.secsdk;
                function collectMethods(o, prefix) {
                    if (!o || typeof o !== 'object') return;
                    Object.keys(o).forEach(function(k) {
                        var full = prefix + '.' + k;
                        if (typeof o[k] === 'function') {
                            allMethods.push(full);
                        } else if (typeof o[k] === 'object' && o[k] !== null && !k.startsWith('native')) {
                            collectMethods(o[k], full);
                        }
                    });
                }
                collectMethods(window.secsdk, 'secsdk');
                results.secsdkMethods = allMethods.slice(0, 30);
            }

            // Check for any sign/encrypt functions in page scope
            var signFuncs = [];
            Object.keys(window).forEach(function(k) {
                try {
                    if (typeof window[k] === 'function' && (k.includes('sign') || k.includes('encrypt') || k.includes('token'))) {
                        signFuncs.push(k);
                    }
                } catch(e) {}
            });
            results.signFuncs = signFuncs.slice(0, 10);

            return JSON.stringify(results);
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:2000]}')

# ============================================================
# 5. 搜索所有内联脚本中包含 _aToken 的代码
# ============================================================
print('\n[5] Searching ALL inline scripts for _aToken generation...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = [];
            var scripts = document.querySelectorAll('script:not([src])');
            scripts.forEach(function(s, i) {
                var text = s.textContent || '';
                if (text.includes('_aToken') || text.includes('aToken') || text.includes('request_extra')) {
                    var idx = text.indexOf('_aToken');
                    if (idx < 0) idx = text.indexOf('request_extra');
                    if (idx < 0) idx = text.indexOf('aToken');
                    results.push({
                        scriptIndex: i,
                        snippet: text.substring(Math.max(0, idx - 80), idx + 250)
                    });
                }
            });
            return JSON.stringify(results);
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:2000]}')

ws.close()

# -*- coding: utf-8 -*-
"""提取并调用 genSignatureNew / ek 生成有效的 request_extra._aToken"""
import json, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9222/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), targets[0])
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
ws.settimeout(3)
mid = [0]

def cdp(m, p=None, timeout=30):
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
# Step 1: 从 chunk[33] 提取 genSignatureNew 和 ek 函数
# ============================================================
print('[1] Extracting genSignatureNew and ek from chunk[33]...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            var chunk = window[chunkName];
            var entry33 = chunk[33];
            var results = {};

            if (!Array.isArray(entry33)) {
                results.error = 'chunk[33] is not array, type=' + typeof entry33;
                return JSON.stringify(results);
            }

            var ids = entry33[0];
            var funcs = entry33[1];

            if (!ids || !funcs) {
                results.error = 'no ids or funcs';
                return JSON.stringify(results);
            }

            var idList = Array.isArray(ids) ? ids : Object.keys(ids);
            results.moduleCount = idList.length;

            // Find the function containing genSignatureNew
            idList.forEach(function(id) {
                var func = funcs[id];
                if (typeof func === 'function') {
                    var src = func.toString();
                    if (src.includes('genSignatureNew')) {
                        window.__genSigFactory = func;
                        window.__genSigId = id;
                        results.genSigId = id;
                        results.genSigSrcLen = src.length;
                        // Extract genSignatureNew implementation
                        var idx = src.indexOf('genSignatureNew');
                        results.genSigSnippet = src.substring(idx, idx + 300);
                    }
                    if (src.includes('function ek') || src.includes('ek=function') || src.includes(',ek=')) {
                        window.__ekFactory = func;
                        window.__ekId = id;
                        results.ekId = id;
                    }
                }
            });

            // Also search OTHER chunk entries for ek
            if (!window.__ekFactory) {
                for (var i = 0; i < chunk.length; i++) {
                    var entry = chunk[i];
                    if (!Array.isArray(entry)) continue;
                    var eIds = entry[0], eFuncs = entry[1];
                    if (!eIds || !eFuncs) continue;
                    var eIdList = Array.isArray(eIds) ? eIds : Object.keys(eIds);
                    for (var j = 0; j < eIdList.length; j++) {
                        var eId = eIdList[j];
                        var eFunc = eFuncs[eId];
                        if (typeof eFunc === 'function') {
                            var eSrc = eFunc.toString();
                            // Look for ek function definition with crypto/signature patterns
                            if ((eSrc.includes('createSign') || eSrc.includes('createHash') ||
                                 eSrc.includes('CryptoJS') || eSrc.includes('HMAC') ||
                                 eSrc.includes('_aToken')) && eSrc.length < 3000) {
                                results['ek_candidate_' + i + '_' + eId] = eSrc.substring(0, 300);
                            }
                        }
                    }
                }
            }

            return JSON.stringify(results);
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:2500]}')
print()

# ============================================================
# Step 2: 调用 genSignatureNew 的工厂函数来获取模块导出
# ============================================================
print('[2] Calling module factory to get genSignatureNew...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = {};

            if (!window.__genSigFactory) {
                results.error = 'no __genSigFactory';
                return JSON.stringify(results);
            }

            // Inject webpack require
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) {
                window.__fxgWebpackRequire = req;
            }]);
            var req = window.__fxgWebpackRequire;

            // The module factory has signature: function(e, t, n) { ... e.exports = {...} }
            // e = module, t = exports (or __webpack_exports__), n = __webpack_require__
            var moduleObj = {exports: {}};

            try {
                window.__genSigFactory.call(moduleObj.exports, moduleObj, moduleObj.exports, req);
                results.exportsKeys = Object.keys(moduleObj.exports).slice(0, 30);

                // Search for genSignatureNew, setSignatureConfig, publishGoods
                var search = ['genSignatureNew', 'setSignatureConfig', 'checkPublishRisk', 'publishGoods', 'ek'];
                search.forEach(function(name) {
                    for (var k in moduleObj.exports) {
                        if (moduleObj.exports[k] && typeof moduleObj.exports[k] === 'object') {
                            if (name in moduleObj.exports[k]) {
                                results['has_' + name] = k;
                            }
                        }
                        if (k === name || k.includes(name)) {
                            results['key_' + name] = k;
                        }
                    }
                });

                window.__genSigExports = moduleObj.exports;
            } catch(e) {
                results.callError = e.message;
                results.callStack = e.stack ? e.stack.substring(0, 500) : '';
            }

            return JSON.stringify(results);
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:2500]}')
print()

# ============================================================
# Step 3: 如果找到 genSignatureNew, 尝试调用它
# ============================================================
print('[3] Calling genSignatureNew...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = {};
            var exports = window.__genSigExports;
            if (!exports) {
                results.error = 'no exports';
                return JSON.stringify(results);
            }

            // Find the object containing genSignatureNew
            var genSigObj = null;
            for (var k in exports) {
                if (exports[k] && typeof exports[k] === 'object' && exports[k].genSignatureNew) {
                    genSigObj = exports[k];
                    results.genSigKey = k;
                }
            }

            if (!genSigObj) {
                results.error = 'genSignatureNew not found in exports';
                results.allKeys = [];
                for (var k in exports) {
                    if (typeof exports[k] === 'object') {
                        var subKeys = Object.keys(exports[k]);
                        if (subKeys.length > 0) {
                            results.allKeys.push({key: k, subKeys: subKeys.slice(0, 10)});
                        }
                    }
                }
                return JSON.stringify(results);
            }

            // Try to call genSignatureNew
            try {
                var sigResult = genSigObj.genSignatureNew();
                results.sigResult = JSON.stringify(sigResult);

                // Also check setSignatureConfig
                if (genSigObj.setSignatureConfig) {
                    results.hasSetSigConfig = true;
                    // This method needs this.goodsStore and this.schemaForm - we can't easily call it
                }
            } catch(e) {
                results.sigError = e.message;
                if (e.stack) results.sigStack = e.stack.substring(0, 300);
            }

            return JSON.stringify(results);
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:3000]}')

ws.close()

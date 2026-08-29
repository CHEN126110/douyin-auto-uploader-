# -*- coding: utf-8 -*-
"""研究页面状态管理: 找到 Vue/Pinia store, 尝试注入表单数据, 触发页面自己的提交。"""
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
cdp('Page.enable')

r = cdp('Runtime.evaluate', {'expression': 'window.location.href', 'returnByValue': True})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
if '/create' not in str(val):
    print('Navigating to create page...')
    cdp('Page.navigate', {'url': 'https://fxg.jinritemai.com/ffa/g/create'}, timeout=30)
    time.sleep(5)

# ============================================================
# 1. Vue App 分析
# ============================================================
print('[1] Vue App analysis...')
queries = [
    ('Vue app instance', '''
        (function() {
            var results = {};
            var app = document.querySelector('#app');
            if (!app) { results.error = '#app not found'; return JSON.stringify(results); }

            var vueApp = app.__vue_app__;
            if (!vueApp) { results.error = '__vue_app__ not found'; return JSON.stringify(results); }

            results.hasVue = true;
            results.version = vueApp.version;

            // Get root component
            var root = vueApp._instance;
            if (root) {
                var proxy = root.proxy || root;
                var keys = Object.keys(proxy).filter(function(k) { return k !== '$' && !k.startsWith('_'); });
                results.rootKeys = keys.slice(0, 30);

                // Check for Pinia store
                if (proxy.$pinia) {
                    results.hasPinia = true;
                    var stores = proxy.$pinia._s;
                    var storeMap = {};
                    Object.keys(stores).forEach(function(id) {
                        var s = stores[id];
                        var stateKeys = Object.keys(s.$state || s || {});
                        storeMap[id] = {stateKeys: stateKeys.slice(0, 20), hasProduct: stateKeys.some(function(k) { return k.includes('product') || k.includes('form') || k.includes('publish'); })};
                    });
                    results.piniaStores = storeMap;
                }

                // Check for Vuex
                if (proxy.$store) {
                    results.hasVuex = true;
                    var stateKeys = Object.keys(proxy.$store.state || {});
                    results.vuexStateKeys = stateKeys.slice(0, 30);
                }
            }

            return JSON.stringify(results);
        })()
    '''),
    ('Vue component tree', '''
        (function() {
            var results = [];
            var app = document.querySelector('#app');
            if (!app || !app.__vue_app__) return JSON.stringify({error: 'no vue'});

            function walk(vnode, depth) {
                if (!vnode || depth > 3) return;
                var comp = vnode.component;
                if (comp) {
                    var name = comp.type ? (comp.type.name || comp.type.__name || 'Anonymous') : 'Anonymous';
                    var props = comp.props ? Object.keys(comp.props).slice(0, 10) : [];
                    var hasSubmit = props.some(function(k) { return k.includes('submit') || k.includes('publish') || k.includes('save'); });
                    results.push({name: name, depth: depth, props: props.slice(0, 5), hasSubmit: hasSubmit});
                }
                if (vnode.children && vnode.children.forEach) {
                    vnode.children.forEach(function(c) { walk(c, depth + 1); });
                }
            }

            // Try to access internal Vue internals
            var root = app.__vue_app__._instance;
            if (root && root.subTree) {
                walk(root.subTree, 0);
            }

            return JSON.stringify(results.slice(0, 30));
        })()
    '''),
    ('Pinia store detail', '''
        (function() {
            var results = {};
            var app = document.querySelector('#app');
            if (!app || !app.__vue_app__) return JSON.stringify({error: 'no vue'});
            var pinia = app.__vue_app__._instance.proxy.$pinia;
            if (!pinia) return JSON.stringify({error: 'no pinia'});

            var stores = pinia._s;
            Object.keys(stores).forEach(function(id) {
                var s = stores[id];
                var state = s.$state || s;
                var keys = Object.keys(state);
                // Filter to relevant keys
                var relevant = keys.filter(function(k) {
                    return ['product', 'form', 'publish', 'schema', 'model', 'category', 'spec', 'sku', 'title', 'pic', 'image', 'goods', 'spu'].some(function(t) {
                        return k.toLowerCase().includes(t);
                    });
                });
                if (relevant.length > 0) {
                    results[id] = {relevantKeys: relevant};
                    // Get sample values
                    relevant.slice(0, 5).forEach(function(k) {
                        try {
                            var v = state[k];
                            results[id][k] = typeof v === 'object' ? ('object:' + JSON.stringify(v).substring(0, 100)) : String(v).substring(0, 80);
                        } catch(e) {}
                    });
                }
            });

            return JSON.stringify(results);
        })()
    '''),
]

for label, expr in queries:
    r = cdp('Runtime.evaluate', {
        'expression': expr,
        'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
    })
    val = ((r.get('result') or {}).get('result') or {}).get('value', '')
    print(f'\n  [{label}]')
    # Try to pretty print JSON
    try:
        d = json.loads(val) if isinstance(val, str) else val
        print(f'  {json.dumps(d, ensure_ascii=False, indent=2)[:1500]}')
    except:
        print(f'  {str(val)[:500]}')

# ============================================================
# 2. 查找表单提交处理函数
# ============================================================
print('\n\n[2] Searching for form submit handlers...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = {};

            // Search for submit-related functions in window
            var windowFuncs = Object.keys(window).filter(function(k) {
                try {
                    return typeof window[k] === 'function' && (
                        k.includes('submit') || k.includes('publish') || k.includes('save') ||
                        k.includes('addWithSchema') || k.includes('create')
                    );
                } catch(e) { return false; }
            });
            results.windowSubmitFuncs = windowFuncs.slice(0, 10);

            // Check for any event listeners on document/body that handle form submissions
            // Try to find the module that calls addWithSchema directly
            // Look for the function that constructs the full body with _aToken etc.
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            if (chunkName) {
                var modules = window[chunkName][1];
                var moduleIds = Object.keys(modules);

                // Search for modules that contain addWithSchema AND _aToken
                var submitMods = [];
                moduleIds.forEach(function(k) {
                    var src = String(modules[k]);
                    if (src.includes('addWithSchema') && (src.includes('_aToken') || src.includes('request_extra'))) {
                        submitMods.push({id: k, len: src.length});
                    }
                });
                results.addWithSchemaModules = submitMods;

                // Search for modules that construct the full publish body
                var bodyMods = [];
                moduleIds.forEach(function(k) {
                    var src = String(modules[k]);
                    if (src.includes('request_extra') || src.includes('_aToken')) {
                        bodyMods.push({id: k, len: src.length});
                    }
                });
                results.requestExtraModules = bodyMods;
            }

            return JSON.stringify(results);
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:1000]}')

# ============================================================
# 3. 尝试直接访问 Pinia store 并修改状态
# ============================================================
print('\n\n[3] Trying to access and inspect Pinia store actions...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = {};
            var app = document.querySelector('#app');
            if (!app || !app.__vue_app__) return JSON.stringify({error: 'no vue'});
            var pinia = app.__vue_app__._instance.proxy.$pinia;
            if (!pinia) return JSON.stringify({error: 'no pinia'});

            // List all stores with their actions/getters
            var stores = pinia._s;
            Object.keys(stores).forEach(function(id) {
                var s = stores[id];
                // Get all methods (actions)
                var methods = [];
                for (var k in s) {
                    if (typeof s[k] === 'function' && !k.startsWith('$') && !k.startsWith('_')) {
                        methods.push(k);
                    }
                }
                if (methods.length > 0) {
                    results[id] = {actions: methods.slice(0, 20)};

                    // Check for publish/submit/save actions specifically
                    var submitActions = methods.filter(function(m) {
                        return ['publish', 'submit', 'save', 'create', 'add', 'draft'].some(function(t) {
                            return m.toLowerCase().includes(t);
                        });
                    });
                    if (submitActions.length > 0) {
                        results[id].submitActions = submitActions;
                    }
                }
            });

            return JSON.stringify(results);
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:1500]}')

ws.close()

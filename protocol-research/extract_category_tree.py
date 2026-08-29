# -*- coding: utf-8 -*-
"""从发品页面提取真实类目树，用于多类目Schema研究"""
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

cdp('Runtime.enable', timeout=10)
cdp('Page.enable', timeout=10)

# 确保在发品页面
r = cdp('Runtime.evaluate', {
    'expression': 'window.location.href',
    'returnByValue': True
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'Current page: {val}')

if '/ffa/g/create' not in str(val):
    print('Navigating to create page...')
    cdp('Page.navigate', {'url': 'https://fxg.jinritemai.com/ffa/g/create'}, timeout=30)
    time.sleep(5)

# 1. 搜索类目相关数据 — 可能在 React/Vue state 或 webpack modules 中
print('\n[1] Searching for category data in page state...')

queries = [
    # 查找类目树 API 响应缓存
    ('Category tree in localStorage', '''
        (function() {
            var results = [];
            for (var i = 0; i < localStorage.length; i++) {
                var key = localStorage.key(i);
                if (key && (key.includes('category') || key.includes('cate') || key.includes('class'))) {
                    results.push({key: key, len: (localStorage.getItem(key) || '').length});
                }
            }
            return JSON.stringify(results);
        })()
    '''),
    # 查找 Vuex/Pinia store 中的类目数据
    ('Store inspection', '''
        (function() {
            var results = {};
            var app = document.querySelector('#app');
            if (app && app.__vue_app__) {
                results.hasVue = true;
                var vm = app.__vue_app__._instance;
                if (vm && vm.proxy) {
                    var store = vm.proxy.$store || vm.proxy.store;
                    if (store) {
                        var stateKeys = Object.keys(store.state || store.$state || {});
                        results.storeKeys = stateKeys.slice(0, 20);
                        // Look for category-related state
                        var catKey = stateKeys.find(function(k) { return k.includes('cat') || k.includes('cate'); });
                        if (catKey) {
                            var catData = store.state[catKey];
                            results.catStateKey = catKey;
                            results.catStateType = typeof catData;
                            if (catData && typeof catData === 'object') {
                                results.catStateKeys = Object.keys(catData).slice(0, 10);
                            }
                        }
                    }
                }
            }
            return JSON.stringify(results);
        })()
    '''),
    # 查找类目选择器数据 (可能在DOM数据属性中)
    ('DOM data attributes', '''
        (function() {
            var elements = document.querySelectorAll('[data-category], [data-cat-id], [data-category-tree]');
            var results = [];
            elements.forEach(function(el) {
                var attrs = {};
                for (var i = 0; i < el.attributes.length; i++) {
                    var a = el.attributes[i];
                    if (a.name.includes('cat') || a.name.includes('data-')) {
                        attrs[a.name] = a.value.substring(0, 100);
                    }
                }
                results.push({tag: el.tagName, text: (el.textContent||'').trim().substring(0, 50), attrs: attrs});
            });
            return JSON.stringify(results.slice(0, 10));
        })()
    '''),
    # 搜索 webpack modules 中的类目树
    ('Webpack category tree search', '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            if (!chunkName) return JSON.stringify({error: 'chunk not found'});
            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) { window.__fxgWebpackRequire = req; }]);
            var req = window.__fxgWebpackRequire;

            // Try to find module that provides category data
            // Look at commonly used module IDs for category-related functionality
            var results = {};
            var modules = window[chunkName][1];
            var moduleIds = Object.keys(modules);

            // Search for category tree patterns in module source
            var catMods = [];
            moduleIds.forEach(function(k) {
                var src = String(modules[k]);
                if (src.includes('categoryTree') || src.includes('category_tree') || src.includes('getCategory')) {
                    catMods.push({id: k, len: src.length});
                }
            });
            results.categoryModules = catMods.slice(0, 10);
            results.totalModules = moduleIds.length;

            return JSON.stringify(results);
        })()
    '''),
]

for label, expr in queries:
    r = cdp('Runtime.evaluate', {
        'expression': expr,
        'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
    })
    val = ((r.get('result') or {}).get('result') or {}).get('value', '')
    print(f'  {label}: {val[:500]}')
    print()

# 2. 尝试从 Network 请求中捕获类目API
print('[2] Attempting to find category tree API endpoint...')
# 已知的类目树 API 可能路径
cat_apis = [
    '/product/tproduct/getCategoryTree',
    '/product/category/getCategoryTree',
    '/product/tproduct/getCategory',
    '/shop/fg/category/list',
    '/ffa/category/tree',
]

r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            var apis = %s;
            var results = {};
            for (var i = 0; i < apis.length; i++) {
                try {
                    var resp = await fetch(apis[i], {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
                    var text = await resp.text();
                    results[apis[i]] = text.substring(0, 150);
                } catch(e) {
                    results[apis[i]] = 'error: ' + e.message;
                }
            }
            return JSON.stringify(results);
        })()
    ''' % json.dumps(cat_apis),
    'returnByValue': True, 'awaitPromise': True, 'timeout': 30000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  API probes: {val[:800]}')

# 3. 检查页面中类目选择相关的交互按钮
print('\n[3] Looking for category selector elements...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = [];
            // Look for category selector
            var allText = document.body.innerText || '';
            var catIdx = allText.indexOf('类目');
            if (catIdx > 0) {
                results.push({type: 'page_text', snippet: allText.substring(Math.max(0, catIdx - 20), catIdx + 100)});
            }
            // Find clickable elements mentioning category
            var els = document.querySelectorAll('*');
            els.forEach(function(el) {
                var text = (el.textContent || '').trim();
                if (text === '选择类目' || text === '请选择类目' || text === '切换类目') {
                    results.push({tag: el.tagName, text: text, clickable: el.onclick !== null || el.getAttribute('role') === 'button'});
                }
            });
            return JSON.stringify(results.slice(0, 5));
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 5000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:500]}')

ws.close()

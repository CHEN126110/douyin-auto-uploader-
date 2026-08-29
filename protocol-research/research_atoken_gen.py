# -*- coding: utf-8 -*-
"""在发品页加载表单后，通过 React fiber 调用 genSignatureNew 生成 _aToken。
必须在封锁窗口期外执行。
"""
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
cdp('Page.enable')
cdp('DOM.enable')

# ============================================================
# 1. 导航到发品页 + 注入 webpack
# ============================================================
print('[1] Navigating to create page + injecting webpack...')
cdp('Page.navigate', {'url': 'https://fxg.jinritemai.com/ffa/g/create'}, timeout=30)
time.sleep(5)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            if (!chunkName) return JSON.stringify({error: 'chunk not found'});
            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) {
                window.__fxgWebpackRequire = req;
            }]);
            var req = window.__fxgWebpackRequire;
            window.__fxgPost = req(90665).bE;
            window.__fxgPublishId = req(68671).T({useUrlParams: true, useWindowCache: true});
            return JSON.stringify({ok: true, pid: window.__fxgPublishId});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  Webpack: {val[:150]}')

# ============================================================
# 2. 通过选择类目来触发表单加载
# ============================================================
print('[2] Triggering form load by setting category via page API...')

# 尝试通过 webpack 模块直接设置类目（不用DOM操作）
r = cdp('Runtime.evaluate', {
    'expression': f'''
        (async function() {{
            var results = {{}};

            // 方式1: 直接通过 getSchema + 检查 fiber 树变化
            // 先检查当前 fiber 节点数
            var rootEl = document.getElementById('app');
            var fiberKey = Object.keys(rootEl).find(function(k) {{ return k.startsWith('__react'); }});
            results.hasFiber = !!fiberKey;

            if (fiberKey) {{
                var count = 0;
                function countFibers(f) {{
                    if (!f || count > 100000) return;
                    count++;
                    countFibers(f.child);
                    countFibers(f.sibling);
                }}
                countFibers(rootEl[fiberKey]);
                results.fiberCount = count;
            }}

            // 方式2: 尝试通过修改 location hash 或 store 状态来触发
            // 很多 React 应用通过 URL 参数或 store 状态来管理类目选择

            // 方式3: 直接用 webpack post 调用 getSchema 后，尝试注入 store
            // 先检查 window 上有没有 store 对象
            var storeKeys = Object.keys(window).filter(function(k) {{
                return k.includes('store') || k.includes('Store') || k.includes('state');
            }});
            results.storeKeys = storeKeys.slice(0, 10);

            return JSON.stringify(results);
        }})()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:800]}')

# ============================================================
# 3. 搜索页面上的 React 组件 —— 重点找 GoodsPublish 或类似组件
# ============================================================
print('\n[3] Searching for publish component in fiber tree...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var rootEl = document.getElementById('app');
            var fiberKey = Object.keys(rootEl).find(function(k) { return k.startsWith('__react'); });
            if (!fiberKey) return JSON.stringify({error: 'no fiber'});

            var results = {components: [], searched: 0};
            var req = window.__fxgWebpackRequire;

            function walkFiber(fiber, depth) {
                if (!fiber || depth > 20 || results.searched > 50000) return;
                results.searched++;

                try {
                    var fiberType = fiber.type;
                    if (fiberType) {
                        var name = '';
                        if (typeof fiberType === 'function') {
                            name = fiberType.name || fiberType.displayName || '';
                            // If it's the module 90912 class
                            if (fiberType.prototype && fiberType.prototype.genSignatureNew) {
                                results.genSigComponent = {
                                    depth: depth,
                                    name: name,
                                    hasStateNode: !!fiber.stateNode,
                                    stateNodeType: fiber.stateNode ? typeof fiber.stateNode : 'null'
                                };
                                if (fiber.stateNode) {
                                    window.__genSigInstance = fiber.stateNode;
                                }
                            }
                        }

                        // Also check for common publish-related component names
                        if (name && (name.includes('Publish') || name.includes('Goods') ||
                            name.includes('publish') || name.includes('Create'))) {
                            results.components.push({
                                depth: depth, name: name,
                                protoMethods: fiberType.prototype ?
                                    Object.getOwnPropertyNames(fiberType.prototype).slice(0, 15) : []
                            });
                        }
                    }
                } catch(e) {}

                walkFiber(fiber.child, depth + 1);
                walkFiber(fiber.sibling, depth);
            }

            walkFiber(rootEl[fiberKey], 0);
            return JSON.stringify(results);
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 30000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:2500]}')

# ============================================================
# 4. 尝试使用 CDP 点击"选择类目"按钮来加载表单
# ============================================================
print('\n[4] Trying to click category selector to load form...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = {};
            // Find the category selection trigger element
            var allElements = document.querySelectorAll('*');
            var catTrigger = null;
            allElements.forEach(function(el) {
                var text = (el.textContent || '').trim();
                if (text === '选择类目' || text === '点击选择类目' || text === '请选择商品类目') {
                    catTrigger = {
                        tag: el.tagName,
                        text: text,
                        className: el.className.substring(0, 80),
                        rect: el.getBoundingClientRect()
                    };
                }
            });
            results.catTrigger = catTrigger;

            // Also look for the step indicator ("下一步" button etc)
            var buttons = document.querySelectorAll('button');
            var btnInfo = [];
            buttons.forEach(function(b) {
                var text = (b.textContent || '').trim();
                if (text && text.length < 20) {
                    btnInfo.push({text: text, disabled: b.disabled, className: b.className.substring(0, 50)});
                }
            });
            results.buttons = btnInfo.slice(0, 10);

            return JSON.stringify(results);
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 5000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:1500]}')

# ============================================================
# 5. 如果找到了 genSignatureNew 实例，直接调用
# ============================================================
if '__genSigInstance' in str(val):
    print('\n[5] Calling genSignatureNew on found instance...')
    r = cdp('Runtime.evaluate', {
        'expression': '''
            (function() {
                var inst = window.__genSigInstance;
                if (!inst) return JSON.stringify({error: 'no instance'});
                try {
                    var r = inst.genSignatureNew();
                    if (r && r.request_extra) {
                        window.__generatedSignature = r.request_extra;
                    }
                    return JSON.stringify({
                        success: true,
                        request_extra: r ? JSON.stringify(r.request_extra) : 'null',
                        hasSignError: r ? r._signError : 'null'
                    });
                } catch(e) {
                    return JSON.stringify({error: e.message});
                }
            })()
        ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
    })
    val = ((r.get('result') or {}).get('result') or {}).get('value', '')
    print(f'  {val[:1000]}')

# 保存任何捕获到的签名
r = cdp('Runtime.evaluate', {
    'expression': 'window.__generatedSignature ? JSON.stringify(window.__generatedSignature) : "none"',
    'returnByValue': True, 'awaitPromise': True, 'timeout': 5000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'\n  Captured signature: {val[:500]}')

ws.close()

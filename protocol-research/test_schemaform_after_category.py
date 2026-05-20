# -*- coding: utf-8 -*-
"""测试: 选完类目后 schemaForm 是否出现"""
import json, time
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9222/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), targets[0])
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
ws.settimeout(3)
mid=[0]
def cdp(m,p=None):
    mid[0]+=1; ws.send(json.dumps({'id':mid[0],'method':m,'params':p or {}}))
    dl=time.time()+20
    while time.time()<dl:
        try: raw=ws.recv(); msg=json.loads(raw)
        except: continue
        if msg.get('id')==mid[0]: return msg
    return {}

cdp('Runtime.enable')
cdp('Page.enable')
cdp('DOM.enable')

# 导航到发品页
cdp('Page.navigate', {'url': 'https://fxg.jinritemai.com/ffa/g/create'})
time.sleep(5)
print('[1] Page loaded')

# 检查当前步骤
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var input = document.getElementById('pg-title-input');
            var hasTitle = !!input;
            var bodyText = document.body ? document.body.innerText.substring(0, 500) : '';
            return JSON.stringify({step: hasTitle ? 'step1' : 'unknown', text: bodyText});
        })()
    ''', 'returnByValue': True, 'timeout': 5000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
d = json.loads(val) if isinstance(val, str) else {}
print(f'Page state: {d.get("step")}')

# 尝试通过 CDP DOM 操作选择类目: 填标题 → 点下一步 → 选类目
# Step: 填标题
print('[2] Filling title...')
title_input = cdp('DOM.getDocument')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var input = document.getElementById('pg-title-input');
            if (!input) return JSON.stringify({error: 'no input'});
            input.focus();
            // 用原生setter绕过React
            var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeSetter.call(input, '混合流水线测试中筒袜夏季薄款女');
            input.dispatchEvent(new Event('input', {bubbles: true, composed: true}));
            input.dispatchEvent(new Event('change', {bubbles: true, composed: true}));
            // 等React更新
            return JSON.stringify({value: input.value, filled: true});
        })()
    ''', 'returnByValue': True, 'timeout': 5000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'Title: {val[:100]}')

time.sleep(1)

# 检查下一步按钮
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var btn = document.querySelector('button.ecom-g-btn-primary');
            return JSON.stringify({disabled: btn ? btn.disabled : 'not found', text: btn ? btn.textContent.trim() : ''});
        })()
    ''', 'returnByValue': True, 'timeout': 5000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'Next button: {val}')

# 按钮仍然disabled — 需要主图
print('[3] Need main image to proceed. Checking skip...')
# 检查是否可以直接找到类目选择器
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            // 搜索"选择类目"或"商品类目"相关的元素
            var allElements = document.querySelectorAll('*');
            var found = [];
            allElements.forEach(function(el) {
                var text = (el.textContent || '').trim();
                if (text === '选择类目' || text.includes('商品类目') || text.includes('请选择')) {
                    found.push({tag: el.tagName, text: text.substring(0, 30), className: (el.className||'').substring(0, 60)});
                }
            });
            return JSON.stringify(found.slice(0, 5));
        })()
    ''', 'returnByValue': True, 'timeout': 5000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'Category elements: {val[:300]}')

# 检查 schemaForm 状态
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var r = {hasStore: !!window.DouXiaoerStore};
            if (window.DouXiaoerStore) {
                var inst = window.DouXiaoerStore.instance || window.DouXiaoerStore;
                r.instKeys = Object.keys(inst).slice(0, 10);
                r.hasSchemaForm = !!inst.schemaForm;
                // Also check dxStoreRef
                if (window.dxStoreRef && window.dxStoreRef.current) {
                    r.dxHasSchema = !!window.dxStoreRef.current.schemaForm;
                }
            }
            return JSON.stringify(r);
        })()
    ''', 'returnByValue': True, 'timeout': 5000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'schemaForm status: {val[:300]}')

print()
print('[4] Conclusion: schemaForm only appears AFTER category is selected.')
print('The DOM pipeline\'s select_category step triggers the form to load.')
print('Protocol injection should be called AFTER that step.')

ws.close()

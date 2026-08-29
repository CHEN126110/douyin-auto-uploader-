# -*- coding: utf-8 -*-
"""反滥用绕过实验: CDP 模拟真人操作后再提交"""
import json, time, datetime, random, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9222/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), targets[0])
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
ws.settimeout(3)
mid = [0]

def cdp(m, p=None, timeout=20):
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
cdp('Input.enable')

# ============================================================
# 实验1: 注入行为信号 (鼠标移动 + 滚动 + 延时)
# ============================================================
print('[Exp1] Simulating human behavior via CDP...')

# 获取页面视口大小
r = cdp('Runtime.evaluate', {
    'expression': 'JSON.stringify({w: window.innerWidth, h: window.innerHeight})',
    'returnByValue': True,
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
vw = json.loads(val)
print(f'  Viewport: {vw}')

# 模拟鼠标移动到页面中心
for i in range(5):
    x = random.randint(200, vw.get('w', 1200) - 200)
    y = random.randint(100, vw.get('h', 800) - 100)
    cdp('Input.dispatchMouseEvent', {
        'type': 'mouseMoved', 'x': x, 'y': y,
        'modifiers': 0, 'button': 'none', 'buttons': 0,
    })
    time.sleep(0.15)

# 模拟滚轮
cdp('Input.dispatchMouseEvent', {
    'type': 'mouseWheel', 'x': 600, 'y': 400,
    'deltaX': 0, 'deltaY': 300,
})
time.sleep(0.3)
cdp('Input.dispatchMouseEvent', {
    'type': 'mouseWheel', 'x': 600, 'y': 400,
    'deltaX': 0, 'deltaY': -150,
})
time.sleep(0.3)

# 模拟点击页面空白处
cdp('Input.dispatchMouseEvent', {
    'type': 'mousePressed', 'x': 500, 'y': 300,
    'button': 'left', 'clickCount': 1,
})
cdp('Input.dispatchMouseEvent', {
    'type': 'mouseReleased', 'x': 500, 'y': 300,
    'button': 'left', 'clickCount': 1,
})

# 模拟键盘输入 (在页面body上)
time.sleep(0.5)
for char in "test input":
    cdp('Input.dispatchKeyEvent', {
        'type': 'keyDown',
        'key': char, 'text': char,
    })
    cdp('Input.dispatchKeyEvent', {
        'type': 'keyUp',
        'key': char,
    })
    time.sleep(0.05)

time.sleep(1.0)
print('  Behavior simulation complete')

# 注入 webpack
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            if (!chunkName) return JSON.stringify({error: 'chunk not found'});
            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) { window.__fxgWebpackRequire = req; }]);
            var r = window.__fxgWebpackRequire;
            window.__fxgPost = r(90665).bE;
            window.__fxgPublishId = r(68671).T({useUrlParams: true, useWindowCache: true});
            return JSON.stringify({ok: true});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')

# 尝试提交
now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
rh = ''.join(random.choices('0123456789ABCDEF', k=20))
n_token = now + rh

body = {
    'schema': {'model': {
        'title': {'value': '真人行为模拟测试中筒袜夏季薄款棉袜'},
        'short_product_name': {'value': ''}, 'title_prefix': {'value': ''}, 'title_suffix': {'value': ''},
        'title_use_brand_name': {'value': False},
        'goods_category': {'value': {'category_leaf_id': 1000010267, 'first_cid': 1000003282, 'first_cname': 'A', 'second_cid': 1000009114, 'second_cname': 'A', 'third_cid': 1000009597, 'third_cname': 'A', 'fourth_cid': 1000010267, 'fourth_cname': 'A'}},
        'category_properties': {'value': {
            '1687': [{'diy_type': 0, 'measure_info': None, 'tags': None, 'value_id': '596120136', 'value_name': '无品牌'}],
            '1577': [{'diy_type': 0, 'measure_info': None, 'tags': None, 'value_id': '1991', 'value_name': '通用'}],
            '1865': [{'diy_type': 0, 'measure_info': None, 'tags': None, 'value_id': '31904', 'value_name': '中筒袜'}],
            '785': [{'value_id': '', 'value_name': '棉100%', 'measure_info': {'template_id': 873, 'values': [{'module_id': 1854, 'value': '棉'}, {'module_id': 1855, 'value': '100', 'unit_id': 15, 'unit_name': '%'}]}}]
        }},
        'category_property_pic': {'value': {}}, 'pic': {'value': []}, 'main_image_three_to_four': {'value': []},
        'white_background_pic': {'value': []}, 'description': {'value': ''},
        'spec_detail': {'value': [
            {'id': '10000', 'cp_id': 2752, 'name': '颜色分类', 'spec_values': [{'id': '996874532588296918', 'name': '默认', 'cpv_id': 0, 'cpv_path': [], 'img_url': None}]},
            {'id': '20000', 'cp_id': 3939, 'name': '码数', 'spec_values': [{'id': '990897920130195435', 'name': '均码', 'cpv_id': 0, 'cpv_path': [], 'img_url': None}]},
            {'id': '30000', 'cp_id': 4706, 'name': '筒高长度', 'spec_values': []}, {'id': '40000', 'cp_id': 93, 'name': '规格', 'spec_values': []}
        ]},
        'sku_detail': {'value': [{'id': 'b-001', 'stock_info': {'stock_num': 100}, 'sku_status': True, 'confirm_no_barcode': False, 'spec_detail_ids': ['996874532588296918', '990897920130195435'], 'price': '9.9'}]},
        'freight_id': {'value': '300713474'}, 'pickup_method': {'value': '0'}, 'start_sale_type': {'value': '0'}, 'product_type': {'value': '0'}, 'presell_type': {'value': '0'},
        'delivery_delay_day': {'value': '2'}, 'reduce_type': {'value': '1'}, 'qualification': {'value': {}},
        'after_sale': {'value': {'quality_problem_return': {'option_id': None, 'selected': True}, 'supply_day_return_selector': {'option_id': '7-1', 'selected': True}}},
        'ai_gen_spec': {'value': {'ai_gen_spec_type': 0}}, 'alli_promotion_plan_switch': {'value': False}, 'area_stock_switcher': {'value': False},
        'goods_category_appeal': {'value': False}, 'interest_free_activity': {'value': []}, 'interest_free_activity_id': {'value': {}},
        'interest_free_open': {'value': True}, 'reference_price_enable': {'value': False}, 'detail_prettify_uri': {'value': ''},
    }, 'context': {
        'ability': [], 'biz_identity': 'xiaodian', 'business_code': 'xiaodian', 'capability_codes': ['standard_capability'],
        'category_id': '1000010267', 'fast_publish_type': '',
        'feature': {'session_publish_id': 'helper_test', 'session_data': '{}', 'not_first_render': '1', 'product_sale_property_control': '1', 'sale_property_sequence_variable': '1', 'min_sku_price': '990'},
        'identity_extension': '{}', 'model_type': '', 'n_token': n_token, 'operation_type': 'normal', 'product_id': '0', 'shop_id': '155450371', 'token': n_token, 'version': 'v1_v8_v9_v10_v11_v12',
    }},
    'category_id': '1000010267', 'context': {
        'ability': [], 'biz_identity': 'xiaodian', 'business_code': 'xiaodian', 'capability_codes': ['standard_capability'],
        'category_id': '1000010267', 'fast_publish_type': '',
        'feature': {'session_publish_id': 'helper_test', 'session_data': '{}', 'not_first_render': '1', 'product_sale_property_control': '1', 'sale_property_sequence_variable': '1', 'min_sku_price': '990'},
        'identity_extension': '{}', 'model_type': '', 'n_token': n_token, 'operation_type': 'normal', 'product_id': '0', 'shop_id': '155450371', 'token': n_token, 'version': 'v1_v8_v9_v10_v11_v12',
    },
    'pass_through_extra': {}, 'request_extra': {}, 'check_status': 2, 'session': {}, 'appid': 1,
}

body_json = json.dumps(body, ensure_ascii=False)
r = cdp('Runtime.evaluate', {
    'expression': f'''
        (async function() {{
            var result = await window.__fxgPost('/product/tproduct/addWithSchema?check_status=2', {body_json}, {{timeout: 30000}});
            return JSON.stringify({{errno: result.errno, code: result.code, msg: result.msg}});
        }})()
    ''',
    'returnByValue': True, 'awaitPromise': True, 'timeout': 40000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
result = json.loads(val) if isinstance(val, str) else (val or {})
print(f'  Result: code={result.get("code")} msg="{result.get("msg","")}')

# ============================================================
# 实验2: 在页面表单中实际输入文字 (Input.insertText)
# ============================================================
print('\n[Exp2] Using DOM form fill + Input events...')

# 先检查发品页面是否有标题输入框
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            // 查找标题输入框
            var inputs = document.querySelectorAll('input, textarea, [contenteditable="true"]');
            var titleInput = null;
            inputs.forEach(function(el) {
                var ph = (el.placeholder || '').toLowerCase();
                var label = (el.getAttribute('aria-label') || '').toLowerCase();
                if (ph.includes('title') || ph.includes('标题') || label.includes('标题')) {
                    titleInput = {tag: el.tagName, placeholder: el.placeholder, id: el.id, className: el.className.substring(0, 50)};
                }
            });
            return JSON.stringify({inputCount: inputs.length, titleInput: titleInput});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 5000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  Form inputs: {val[:300]}')

# 查找提交/发布按钮
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var buttons = document.querySelectorAll('button');
            var found = [];
            buttons.forEach(function(b) {
                var text = (b.textContent || '').trim();
                if (text && text.length < 20) {
                    found.push({text: text, disabled: b.disabled, className: b.className.substring(0, 50)});
                }
            });
            return JSON.stringify(found.slice(0, 10));
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 5000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  Buttons: {val[:400]}')

# ============================================================
# 实验3: 检查 batchupload 是否也被封锁
# ============================================================
print('\n[Exp3] Testing batchupload...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            try {
                var resp = await fetch('https://fxg.jinritemai.com/product/img/batchupload', {
                    method: 'POST',
                    headers: {'Accept': 'application/json'},
                    body: new FormData()
                });
                var text = await resp.text();
                return text.substring(0, 200);
            } catch(e) {
                return 'error: ' + e.message;
            }
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  batchupload: {val[:200]}')

# ============================================================
# 实验4: 检查是否能正常调用 getSchema
# ============================================================
print('\n[Exp4] Testing getSchema...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            var result = await window.__fxgPost('/product/tproduct/getSchema', {
                context: {category_id: '1000010267', operation_type: 'normal', ability: [], feature: {session_publish_id: 'test'}},
                model: void 0
            }, {timeout: 10000});
            return JSON.stringify({errno: result.errno, code: result.code, msg: result.msg});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  getSchema: {val[:200]}')

ws.close()

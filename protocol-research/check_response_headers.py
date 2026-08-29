# -*- coding: utf-8 -*-
"""捕获 HTTP 响应头 — 查找 RateLimit/Retry-After 等限频信息"""
import json, time, datetime, random, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9222/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), targets[0])
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
ws.settimeout(2)
mid = [0]
responses = []

def cdp(m, p=None):
    mid[0] += 1
    ws.send(json.dumps({'id': mid[0], 'method': m, 'params': p or {}}))
    dl = time.time() + 20
    while time.time() < dl:
        try:
            raw = ws.recv()
            msg = json.loads(raw)
            if msg.get('method') == 'Network.responseReceived':
                resp = msg.get('params', {}).get('response', {})
                url = resp.get('url', '')
                if any(kw in url for kw in ['addWithSchema', 'canCreateGood', 'getSchema', 'publishClickStat']):
                    responses.append({
                        'url': url[:200],
                        'status': resp.get('status'),
                        'statusText': resp.get('statusText', ''),
                        'headers': dict(resp.get('headers', {})),
                    })
            if msg.get('id') == mid[0]:
                return msg
        except:
            continue
    return {}

cdp('Network.enable')
cdp('Runtime.enable')

# inject
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) { window.__fxgWebpackRequire = req; }]);
            window.__fxgPost = window.__fxgWebpackRequire(90665).bE;
            window.__fxgGet = window.__fxgWebpackRequire(28974).J;
            return JSON.stringify({ok: true});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})

# Test 1: canCreateGood headers
print('=== canCreateGood ===')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            await window.__fxgGet('/product/tproduct/canCreateGood?is_create=1', {timeout: 10000});
            return 'ok';
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
})
time.sleep(1)
for resp in responses:
    if 'canCreateGood' in resp.get('url', ''):
        print(f'  Status: {resp["status"]} {resp.get("statusText","")}')
        for k, v in sorted(resp.get('headers', {}).items()):
            print(f'    {k}: {v}')

# Test 2: addWithSchema headers (blocked state)
print()
print('=== addWithSchema (blocked state) ===')

now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
rh = ''.join(random.choices('0123456789ABCDEF', k=20))
n_token = now + rh

body = {
    'schema': {'model': {
        'title': {'value': 'HTTP头分析测试'},
        'short_product_name': {'value': ''}, 'title_prefix': {'value': ''}, 'title_suffix': {'value': ''},
        'title_use_brand_name': {'value': False},
        'goods_category': {'value': {'category_leaf_id': 1000010267, 'first_cid': 1000003282, 'first_cname': 'A'}},
        'category_properties': {'value': {
            '1687': [{'value_id': '596120136', 'value_name': '无品牌'}],
            '1577': [{'value_id': '1991', 'value_name': '通用'}],
            '1865': [{'value_id': '31904', 'value_name': '中筒袜'}],
            '785': [{'value_id': '', 'value_name': '棉100%', 'measure_info': {'template_id': 873, 'values': [{'module_id': 1854, 'value': '棉'}, {'module_id': 1855, 'value': '100', 'unit_id': 15, 'unit_name': '%'}]}}]
        }},
        'category_property_pic': {'value': {}}, 'pic': {'value': []}, 'main_image_three_to_four': {'value': []},
        'white_background_pic': {'value': []}, 'description': {'value': ''},
        'spec_detail': {'value': [
            {'id': '10000', 'cp_id': 2752, 'name': '颜色分类', 'spec_values': [{'id': '996874532588296918', 'name': '默认', 'cpv_id': 0, 'cpv_path': [], 'img_url': None}]},
            {'id': '20000', 'cp_id': 3939, 'name': '码数', 'spec_values': [{'id': '990897920130195435', 'name': '均码', 'cpv_id': 0, 'cpv_path': [], 'img_url': None}]}
        ]},
        'sku_detail': {'value': [{'id': 'hdr-001', 'stock_info': {'stock_num': 100}, 'sku_status': True, 'confirm_no_barcode': False, 'spec_detail_ids': ['996874532588296918', '990897920130195435'], 'price': '9.9'}]},
        'freight_id': {'value': '300713474'}, 'pickup_method': {'value': '0'}, 'start_sale_type': {'value': '0'},
        'product_type': {'value': '0'}, 'presell_type': {'value': '0'}, 'delivery_delay_day': {'value': '2'},
        'reduce_type': {'value': '1'}, 'qualification': {'value': {}},
        'after_sale': {'value': {'quality_problem_return': {'option_id': None, 'selected': True}, 'supply_day_return_selector': {'option_id': '7-1', 'selected': True}}},
        'ai_gen_spec': {'value': {'ai_gen_spec_type': 0}}, 'alli_promotion_plan_switch': {'value': False},
        'area_stock_switcher': {'value': False}, 'goods_category_appeal': {'value': False},
        'interest_free_activity': {'value': []}, 'interest_free_activity_id': {'value': {}},
        'interest_free_open': {'value': True}, 'reference_price_enable': {'value': False},
        'detail_prettify_uri': {'value': ''},
    }, 'context': {
        'ability': [], 'biz_identity': 'xiaodian', 'business_code': 'xiaodian',
        'capability_codes': ['standard_capability'], 'category_id': '1000010267', 'fast_publish_type': '',
        'feature': {'session_publish_id': 'helper_test', 'session_data': '{}', 'not_first_render': '1'},
        'identity_extension': '{}', 'model_type': '', 'n_token': n_token, 'operation_type': 'normal',
        'product_id': '0', 'shop_id': '155450371', 'token': n_token, 'version': 'v1_v8_v9_v10_v11_v12',
    }},
    'category_id': '1000010267', 'context': {
        'ability': [], 'biz_identity': 'xiaodian', 'business_code': 'xiaodian',
        'capability_codes': ['standard_capability'], 'category_id': '1000010267', 'fast_publish_type': '',
        'feature': {'session_publish_id': 'helper_test', 'session_data': '{}', 'not_first_render': '1'},
        'identity_extension': '{}', 'model_type': '', 'n_token': n_token, 'operation_type': 'normal',
        'product_id': '0', 'shop_id': '155450371', 'token': n_token, 'version': 'v1_v8_v9_v10_v11_v12',
    },
    'pass_through_extra': {}, 'request_extra': {}, 'check_status': 0, 'session': {}, 'appid': 1,
}

body_json = json.dumps(body, ensure_ascii=False)
r = cdp('Runtime.evaluate', {
    'expression': f'''
        (async function() {{
            var result = await window.__fxgPost('/product/tproduct/addWithSchema?check_status=0', {body_json}, {{timeout: 30000}});
            return JSON.stringify({{code: result.code, msg: result.msg}});
        }})()
    ''',
    'returnByValue': True, 'awaitPromise': True, 'timeout': 40000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
result = json.loads(val) if isinstance(val, str) else (val or {})
blocked = '非官方' in str(result.get('msg', '')) or '异常' in str(result.get('msg', ''))
print(f'  code={result.get("code")} blocked={blocked} msg={result.get("msg","")[:80]}')

time.sleep(1)
for resp in responses:
    if 'addWithSchema' in resp.get('url', ''):
        print(f'  Status: {resp["status"]} {resp.get("statusText","")}')
        # Print ALL headers
        for k, v in sorted(resp.get('headers', {}).items()):
            print(f'    {k}: {v[:200]}')

# Also check if there are any X-RateLimit or similar headers across ALL responses
print()
print('=== Checking for rate-limit headers across all responses ===')
rate_headers = set()
for resp in responses:
    for k in resp.get('headers', {}):
        kl = k.lower()
        if any(t in kl for t in ['rate', 'limit', 'retry', 'quota', 'throttle', 'x-ratelimit']):
            rate_headers.add(k)

if rate_headers:
    print(f'  Found: {rate_headers}')
else:
    print(f'  NO rate-limit headers found in any response')
    print(f'  Total responses captured: {len(responses)}')

ws.close()

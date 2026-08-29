# -*- coding: utf-8 -*-
"""模拟页面真实发布流程: canCreateGood → publishClickStat → delay → submit"""
import json, time, datetime, random, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9222/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), targets[0])
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
ws.settimeout(3)
mid = [0]

def cdp(m, p=None):
    mid[0] += 1
    ws.send(json.dumps({'id': mid[0], 'method': m, 'params': p or {}}))
    dl = time.time() + 20
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
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) { window.__fxgWebpackRequire = req; }]);
            var r = window.__fxgWebpackRequire;
            window.__fxgPost = r(90665).bE;
            window.__fxgGet = r(28974).J;
            return JSON.stringify({ok: true});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})

# ============================================================
# 1. 深度测试 canCreateGood
# ============================================================
print('=== canCreateGood 深度测试 ===')
for params in ['is_create=1', 'is_create=0', 'is_create=1&product_id=0']:
    r = cdp('Runtime.evaluate', {
        'expression': f'''
            (async function() {{
                var result = await window.__fxgGet('/product/tproduct/canCreateGood?{params}', {{timeout: 10000}});
                return JSON.stringify(result);
            }})()
        ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
    })
    val = ((r.get('result') or {}).get('result') or {}).get('value', '')
    result = json.loads(val) if isinstance(val, str) else (val or {})
    cd = result.get('data', {})
    print(f'  {params}: can_create={cd.get("can_create","?")} limit_reason={json.dumps(cd.get("limit_reason",""), ensure_ascii=False)}')

# ============================================================
# 2. 模拟页面流程: pre-check → clickStat → delay → submit
# ============================================================
print()
print('=== 模拟页面流程提交 ===')

now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
rh = ''.join(random.choices('0123456789ABCDEF', k=20))
n_token = now + rh

# Step A: canCreateGood
r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            var result = await window.__fxgGet('/product/tproduct/canCreateGood?is_create=1', {timeout: 10000});
            return JSON.stringify({can_create: result.data ? result.data.can_create : '?'});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
pre = json.loads(val) if isinstance(val, str) else (val or {})
print(f'  [1] canCreateGood: can_create={pre.get("can_create","?")}')

# Step B: publishClickStat
r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            var result = await window.__fxgGet('/product/tproduct/publishClickStat?check_status=0', {timeout: 5000});
            return JSON.stringify({code: result.code});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
click = json.loads(val) if isinstance(val, str) else (val or {})
print(f'  [2] publishClickStat: code={click.get("code","?")}')

# Step C: random delay
delay = random.uniform(2, 5)
print(f'  [3] Delay: {delay:.1f}s')
time.sleep(delay)

# Step D: submit
body = {
    'schema': {'model': {
        'title': {'value': '模拟流程测试商品中筒袜'},
        'short_product_name': {'value': ''}, 'title_prefix': {'value': ''}, 'title_suffix': {'value': ''},
        'title_use_brand_name': {'value': False},
        'goods_category': {'value': {'category_leaf_id': 1000010267, 'first_cid': 1000003282, 'first_cname': 'A', 'second_cid': 1000009114, 'second_cname': 'A', 'third_cid': 1000009597, 'third_cname': 'A', 'fourth_cid': 1000010267, 'fourth_cname': 'A'}},
        'category_properties': {'value': {'1687': [{'value_id': '596120136', 'value_name': '无品牌'}], '1577': [{'value_id': '1991', 'value_name': '通用'}], '1865': [{'value_id': '31904', 'value_name': '中筒袜'}], '785': [{'value_id': '', 'value_name': '棉100%', 'measure_info': {'template_id': 873, 'values': [{'module_id': 1854, 'value': '棉'}, {'module_id': 1855, 'value': '100', 'unit_id': 15, 'unit_name': '%'}]}}]}},
        'category_property_pic': {'value': {}}, 'pic': {'value': []}, 'main_image_three_to_four': {'value': []}, 'white_background_pic': {'value': []}, 'description': {'value': ''},
        'spec_detail': {'value': [{'id': '10000', 'cp_id': 2752, 'name': '颜色分类', 'spec_values': [{'id': '996874532588296918', 'name': '默认', 'cpv_id': 0, 'cpv_path': [], 'img_url': None}]}, {'id': '20000', 'cp_id': 3939, 'name': '码数', 'spec_values': [{'id': '990897920130195435', 'name': '均码', 'cpv_id': 0, 'cpv_path': [], 'img_url': None}]}]},
        'sku_detail': {'value': [{'id': 'sim-001', 'stock_info': {'stock_num': 100}, 'sku_status': True, 'confirm_no_barcode': False, 'spec_detail_ids': ['996874532588296918', '990897920130195435'], 'price': '9.9'}]},
        'freight_id': {'value': '300713474'}, 'pickup_method': {'value': '0'}, 'start_sale_type': {'value': '0'}, 'product_type': {'value': '0'}, 'presell_type': {'value': '0'}, 'delivery_delay_day': {'value': '2'}, 'reduce_type': {'value': '1'}, 'qualification': {'value': {}}, 'after_sale': {'value': {'quality_problem_return': {'option_id': None, 'selected': True}, 'supply_day_return_selector': {'option_id': '7-1', 'selected': True}}}, 'ai_gen_spec': {'value': {'ai_gen_spec_type': 0}}, 'alli_promotion_plan_switch': {'value': False}, 'area_stock_switcher': {'value': False}, 'goods_category_appeal': {'value': False}, 'interest_free_activity': {'value': []}, 'interest_free_activity_id': {'value': {}}, 'interest_free_open': {'value': True}, 'reference_price_enable': {'value': False}, 'detail_prettify_uri': {'value': ''},
    }, 'context': {'ability': [], 'biz_identity': 'xiaodian', 'business_code': 'xiaodian', 'capability_codes': ['standard_capability'], 'category_id': '1000010267', 'fast_publish_type': '', 'feature': {'session_publish_id': 'helper_test', 'session_data': '{}', 'not_first_render': '1', 'product_sale_property_control': '1', 'sale_property_sequence_variable': '1', 'min_sku_price': '990'}, 'identity_extension': '{}', 'model_type': '', 'n_token': n_token, 'operation_type': 'normal', 'product_id': '0', 'shop_id': '155450371', 'token': n_token, 'version': 'v1_v8_v9_v10_v11_v12'}},
    'category_id': '1000010267', 'context': {'ability': [], 'biz_identity': 'xiaodian', 'business_code': 'xiaodian', 'capability_codes': ['standard_capability'], 'category_id': '1000010267', 'fast_publish_type': '', 'feature': {'session_publish_id': 'helper_test', 'session_data': '{}', 'not_first_render': '1', 'product_sale_property_control': '1', 'sale_property_sequence_variable': '1', 'min_sku_price': '990'}, 'identity_extension': '{}', 'model_type': '', 'n_token': n_token, 'operation_type': 'normal', 'product_id': '0', 'shop_id': '155450371', 'token': n_token, 'version': 'v1_v8_v9_v10_v11_v12'},
    'pass_through_extra': {}, 'request_extra': {}, 'check_status': 0, 'session': {}, 'appid': 1,
}
body_json = json.dumps(body, ensure_ascii=False)
r = cdp('Runtime.evaluate', {
    'expression': f'''
        (async function() {{
            var result = await window.__fxgPost('/product/tproduct/addWithSchema?check_status=0', {body_json}, {{timeout: 30000}});
            return JSON.stringify({{errno: result.errno, code: result.code, msg: result.msg, data: result.data ? (typeof result.data === \"string\" ? JSON.parse(result.data).product_id : result.data.product_id) : null}});
        }})()
    ''',
    'returnByValue': True, 'awaitPromise': True, 'timeout': 40000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
result = json.loads(val) if isinstance(val, str) else (val or {})
pid = result.get('data', '')
blocked = '非官方' in str(result.get('msg', '')) or '异常' in str(result.get('msg', ''))
print(f'  [4] Submit: code={result.get("code")} pid={pid} blocked={blocked} msg="{result.get("msg","")}"')

ws.close()

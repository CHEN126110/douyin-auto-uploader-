# -*- coding: utf-8 -*-
"""测试: 页面刷新 + 草稿模式 + 冷却后提交"""
import json, sys, os, time, datetime, random
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
    dl = time.time() + 25
    while time.time() < dl:
        try:
            raw = ws.recv()
            msg = json.loads(raw)
            if msg.get('id') == mid[0]:
                return msg
        except:
            continue
    return {}

# 1. 刷新发品页
print('[1] Navigating to create page...')
cdp('Page.enable')
cdp('Page.navigate', {'url': 'https://fxg.jinritemai.com/ffa/g/create'})
time.sleep(5)

# 2. 注入 webpack
print('[2] Injecting webpack...')
cdp('Runtime.enable')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            if (!chunkName) return JSON.stringify({error: 'chunk not found'});
            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) {
                window.__fxgWebpackRequire = req;
            }]);
            var r = window.__fxgWebpackRequire;
            window.__fxgPost = r(90665).bE;
            window.__fxgPublishId = r(68671).T({useUrlParams: true, useWindowCache: true});
            return JSON.stringify({ok: true, pid: window.__fxgPublishId});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:200]}')

# 3. 测试 1: check_status=0 (草稿), 价格0.01
print('[3] Test: check_status=0, price=0.01...')
now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
rh = ''.join(random.choices('0123456789ABCDEF', k=20))
n_token = now + rh

body = {
    'schema': {'model': {
        'title': {'value': '草稿测试最低价格001元商品'},
        'short_product_name': {'value': ''}, 'title_prefix': {'value': ''}, 'title_suffix': {'value': ''},
        'title_use_brand_name': {'value': False},
        'goods_category': {'value': {'category_leaf_id': 1000010267, 'first_cid': 1000003282, 'first_cname': 'A', 'second_cid': 1000009114, 'second_cname': 'A', 'third_cid': 1000009597, 'third_cname': 'A', 'fourth_cid': 1000010267, 'fourth_cname': 'A'}},
        'category_properties': {'value': {
            '1687': [{'diy_type': 0, 'measure_info': None, 'tags': None, 'value_id': '596120136', 'value_name': '无品牌'}],
            '1577': [{'diy_type': 0, 'measure_info': None, 'tags': None, 'value_id': '1991', 'value_name': '通用'}],
            '1865': [{'diy_type': 0, 'measure_info': None, 'tags': None, 'value_id': '31904', 'value_name': '中筒袜'}],
            '785': [{'value_id': '', 'value_name': '棉100%', 'measure_info': {'template_id': 873, 'values': [{'module_id': 1854, 'value': '棉'}, {'module_id': 1855, 'value': '100', 'unit_id': 15, 'unit_name': '%'}]}}]
        }},
        'category_property_pic': {'value': {}},
        'pic': {'value': []}, 'main_image_three_to_four': {'value': []}, 'white_background_pic': {'value': []},
        'description': {'value': ''},
        'spec_detail': {'value': [
            {'id': '10000', 'cp_id': 2752, 'name': '颜色分类', 'spec_values': [{'id': '996874532588296918', 'name': '默认', 'cpv_id': 0, 'cpv_path': [], 'img_url': None}]},
            {'id': '20000', 'cp_id': 3939, 'name': '码数', 'spec_values': [{'id': '990897920130195435', 'name': '均码', 'cpv_id': 0, 'cpv_path': [], 'img_url': None}]},
            {'id': '30000', 'cp_id': 4706, 'name': '筒高长度', 'spec_values': []},
            {'id': '40000', 'cp_id': 93, 'name': '规格', 'spec_values': []}
        ]},
        'sku_detail': {'value': [{'id': 'test-sku-draft-1', 'stock_info': {'stock_num': 100}, 'sku_status': True, 'confirm_no_barcode': False, 'spec_detail_ids': ['996874532588296918', '990897920130195435'], 'price': '0.01'}]},
        'freight_id': {'value': '300713474'}, 'pickup_method': {'value': '0'}, 'start_sale_type': {'value': '0'}, 'product_type': {'value': '0'}, 'presell_type': {'value': '0'},
        'delivery_delay_day': {'value': '2'}, 'reduce_type': {'value': '1'}, 'qualification': {'value': {}},
        'after_sale': {'value': {'quality_problem_return': {'option_id': None, 'selected': True}, 'supply_day_return_selector': {'option_id': '7-1', 'selected': True}}},
        'ai_gen_spec': {'value': {'ai_gen_spec_type': 0}}, 'alli_promotion_plan_switch': {'value': False}, 'area_stock_switcher': {'value': False},
        'goods_category_appeal': {'value': False}, 'interest_free_activity': {'value': []}, 'interest_free_activity_id': {'value': {}},
        'interest_free_open': {'value': True}, 'reference_price_enable': {'value': False}, 'detail_prettify_uri': {'value': ''},
    }, 'context': {
        'ability': [], 'biz_identity': 'xiaodian', 'business_code': 'xiaodian', 'capability_codes': ['standard_capability'],
        'category_id': '1000010267', 'fast_publish_type': '',
        'feature': {'session_publish_id': 'helper_test', 'session_data': '{}', 'not_first_render': '1', 'product_sale_property_control': '1', 'sale_property_sequence_variable': '1', 'min_sku_price': '1'},
        'identity_extension': '{}', 'model_type': '', 'n_token': n_token, 'operation_type': 'normal', 'product_id': '0', 'shop_id': '155450371', 'token': n_token, 'version': 'v1_v8_v9_v10_v11_v12',
    }},
    'category_id': '1000010267', 'context': {
        'ability': [], 'biz_identity': 'xiaodian', 'business_code': 'xiaodian', 'capability_codes': ['standard_capability'],
        'category_id': '1000010267', 'fast_publish_type': '',
        'feature': {'session_publish_id': 'helper_test', 'session_data': '{}', 'not_first_render': '1', 'product_sale_property_control': '1', 'sale_property_sequence_variable': '1', 'min_sku_price': '1'},
        'identity_extension': '{}', 'model_type': '', 'n_token': n_token, 'operation_type': 'normal', 'product_id': '0', 'shop_id': '155450371', 'token': n_token, 'version': 'v1_v8_v9_v10_v11_v12',
    },
    'pass_through_extra': {}, 'request_extra': {}, 'check_status': 0, 'session': {}, 'appid': 1,
}

body_json = json.dumps(body, ensure_ascii=False)
r = cdp('Runtime.evaluate', {
    'expression': f'''
        (async function() {{
            var result = await window.__fxgPost('/product/tproduct/addWithSchema?check_status=0', {body_json}, {{timeout: 30000}});
            return JSON.stringify(result);
        }})()
    ''',
    'returnByValue': True, 'awaitPromise': True, 'timeout': 40000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
if isinstance(val, str):
    result = json.loads(val)
else:
    result = val if val else {}
print(f'    errno={result.get("errno")} code={result.get("code")} msg="{result.get("msg","")}"')
d = result.get('data')
if d:
    pid = d.get('product_id', '') if isinstance(d, dict) else str(d)
    if pid:
        print(f'    product_id: {pid}')

# 4. 测试 2: 正常价格 + 图片 (60秒冷却后)
print('[4] Waiting 60s cooldown...')
time.sleep(60)

print('[5] Test: check_status=2, price=9.9, with image...')
now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
rh = ''.join(random.choices('0123456789ABCDEF', k=20))
n_token = now + rh

# 修改 body
body['schema']['model']['title']['value'] = '冷却后正常提交测试九块九商品'
body['schema']['model']['price'] = {'value': [{'url': 'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_646be43f717bf456b1061922110578b9_sx_3180433_www1440-1440'}]}
body['schema']['model']['main_image_three_to_four'] = {'value': [{'url': 'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_689e487ff9f6368e3a20f1e43aac2922_sx_348932_www1440-1920'}]}
body['schema']['model']['white_background_pic'] = {'value': [{'url': 'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_d1a3c94d03948b1127a789a7ec5c9e1b_sx_1958777_www1440-1440'}]}
body['schema']['model']['sku_detail']['value'][0]['price'] = '9.9'
body['check_status'] = 2
body['schema']['context']['feature']['min_sku_price'] = '990'
body['context']['feature']['min_sku_price'] = '990'
body['schema']['context']['n_token'] = n_token
body['context']['n_token'] = n_token
body['schema']['context']['token'] = n_token
body['context']['token'] = n_token

body_json = json.dumps(body, ensure_ascii=False)
r = cdp('Runtime.evaluate', {
    'expression': f'''
        (async function() {{
            var result = await window.__fxgPost('/product/tproduct/addWithSchema?check_status=2', {body_json}, {{timeout: 30000}});
            return JSON.stringify(result);
        }})()
    ''',
    'returnByValue': True, 'awaitPromise': True, 'timeout': 40000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
if isinstance(val, str):
    result = json.loads(val)
else:
    result = val if val else {}
print(f'    errno={result.get("errno")} code={result.get("code")} msg="{result.get("msg","")}"')
d = result.get('data')
if d:
    pid = d.get('product_id', '') if isinstance(d, dict) else str(d)
    if pid:
        print(f'    product_id: {pid}')

ws.close()

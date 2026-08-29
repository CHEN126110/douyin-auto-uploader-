# -*- coding: utf-8 -*-
"""反滥用绕过实验:
1. 轮换 s_v_web_id 指纹
2. 测试 editWithSchema 端点
3. 调用 checkPublishRisk 预检
"""
import json, time, datetime, random, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9222/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), targets[0])
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
ws.settimeout(3)
mid = [0]
submission_count = [0]

def cdp(m, p=None, timeout=25):
    mid[0] += 1
    msg_id = mid[0]
    ws.send(json.dumps({'id': msg_id, 'method': m, 'params': p or {}}))
    dl = time.time() + timeout
    while time.time() < dl:
        try:
            raw = ws.recv()
            msg = json.loads(raw)
            if msg.get('id') == msg_id:
                return msg
            # Log other interesting events
            method = msg.get('method', '')
        except:
            continue
    return {}

cdp('Runtime.enable')
cdp('Page.enable')
cdp('Network.enable')

# ============================================================
# Part 1: 分析 s_v_web_id cookie
# ============================================================
print('='*60)
print('Part 1: s_v_web_id analysis')
print('='*60)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var cookies = document.cookie.split(';');
            var results = {};
            cookies.forEach(function(c) {
                var parts = c.trim().split('=');
                if (parts[0].trim() === 's_v_web_id') {
                    results.value = parts.slice(1).join('=');
                    results.full = c.trim();
                }
            });
            return JSON.stringify(results);
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 5000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'Current s_v_web_id: {val[:200]}')

# Can we delete and regenerate s_v_web_id?
print('\nTesting s_v_web_id regeneration...')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            // Delete the cookie
            document.cookie = 's_v_web_id=; domain=.jinritemai.com; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
            document.cookie = 's_v_web_id=; domain=jinritemai.com; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
            document.cookie = 's_v_web_id=; domain=fxg.jinritemai.com; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';

            // Also try clearing via CDP
            var after = document.cookie.split(';').filter(function(c) { return c.includes('s_v_web_id'); });
            return JSON.stringify({deleted: true, remaining: after});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 5000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  Delete result: {val[:300]}')

# Now reload the page to trigger new s_v_web_id generation
print('  Reloading page to regenerate fingerprint...')
cdp('Page.reload', {'ignoreCache': True}, timeout=30)
time.sleep(5)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var cookies = document.cookie.split(';');
            var svid = '';
            cookies.forEach(function(c) {
                if (c.includes('s_v_web_id')) svid = c.trim();
            });
            return JSON.stringify({new_s_v_web_id: svid});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 5000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  After reload: {val[:300]}')

# ============================================================
# Part 2: 测试 editWithSchema 端点
# ============================================================
print('\n' + '='*60)
print('Part 2: Testing editWithSchema endpoint')
print('='*60)

# inject webpack
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) { window.__fxgWebpackRequire = req; }]);
            var r = window.__fxgWebpackRequire;
            window.__fxgPost = r(90665).bE;
            window.__fxgPublishId = r(68671).T({useUrlParams: true, useWindowCache: true});
            return JSON.stringify({ok: true, pid: window.__fxgPublishId});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')

def quick_submit(label, url_path, check_status, extra_request=None):
    """统一提交函数"""
    submission_count[0] += 1
    now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    rh = ''.join(random.choices('0123456789ABCDEF', k=20))
    n_token = now + rh

    body = {
        'schema': {'model': {
            'title': {'value': f'Bypass test {label} {submission_count[0]}'},
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
            'sku_detail': {'value': [{'id': f'bp-{submission_count[0]:03d}', 'stock_info': {'stock_num': 100}, 'sku_status': True, 'confirm_no_barcode': False, 'spec_detail_ids': ['996874532588296918', '990897920130195435'], 'price': '9.9'}]},
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
            'feature': {'session_publish_id': 'helper_test', 'session_data': '{}', 'not_first_render': '1',
                       'product_sale_property_control': '1', 'sale_property_sequence_variable': '1', 'min_sku_price': '990'},
            'identity_extension': '{}', 'model_type': '', 'n_token': n_token, 'operation_type': 'normal',
            'product_id': '0', 'shop_id': '155450371', 'token': n_token, 'version': 'v1_v8_v9_v10_v11_v12',
        }},
        'category_id': '1000010267', 'context': {
            'ability': [], 'biz_identity': 'xiaodian', 'business_code': 'xiaodian',
            'capability_codes': ['standard_capability'], 'category_id': '1000010267', 'fast_publish_type': '',
            'feature': {'session_publish_id': 'helper_test', 'session_data': '{}', 'not_first_render': '1',
                       'product_sale_property_control': '1', 'sale_property_sequence_variable': '1', 'min_sku_price': '990'},
            'identity_extension': '{}', 'model_type': '', 'n_token': n_token, 'operation_type': 'normal',
            'product_id': '0', 'shop_id': '155450371', 'token': n_token, 'version': 'v1_v8_v9_v10_v11_v12',
        },
        'pass_through_extra': {}, 'request_extra': {}, 'check_status': check_status, 'session': {}, 'appid': 1,
    }

    if extra_request:
        body.update(extra_request)

    body_json = json.dumps(body, ensure_ascii=False)
    r = cdp('Runtime.evaluate', {
        'expression': f'''
            (async function() {{
                var result = await window.__fxgPost('{url_path}?check_status={check_status}', {body_json}, {{timeout: 30000}});
                return JSON.stringify({{errno: result.errno, code: result.code, msg: result.msg, data: result.data ? (typeof result.data === "string" ? JSON.parse(result.data).product_id : result.data.product_id) : null}});
            }})()
        ''',
        'returnByValue': True, 'awaitPromise': True, 'timeout': 40000
    })
    val = ((r.get('result') or {}).get('result') or {}).get('value', '')
    result = json.loads(val) if isinstance(val, str) else (val or {})
    pid = result.get('data', '')
    blocked = '非官方' in str(result.get('msg', '')) or '异常' in str(result.get('msg', ''))
    print(f'  [{label}] #{submission_count[0]} code={result.get("code")} pid={pid} blocked={blocked} msg={result.get("msg","")[:60]}')
    return result

# Test 1: addWithSchema (baseline, 草稿)
print('\n--- addWithSchema baseline ---')
r1 = quick_submit('add_draft', '/product/tproduct/addWithSchema', 0)

# Test 2: addWithSchema (baseline, 发布)
print('\n--- addWithSchema publish ---')
r2 = quick_submit('add_pub', '/product/tproduct/addWithSchema', 2)

# Test 3: editWithSchema (草稿) — but need a valid product_id to edit
print('\n--- editWithSchema test ---')
# We need an existing product ID to edit. Use the draft we just created.
# But we can also test if the endpoint is reachable
r3 = quick_submit('edit_no_id', '/product/tproduct/editWithSchema', 0)

print('\n' + '='*60)
print('Summary:')
for name, r in [('add_draft', r1), ('add_pub', r2), ('edit_draft', r3)]:
    blocked = '非官方' in str(r.get('msg', '')) or '异常' in str(r.get('msg', ''))
    print(f'  {name}: code={r.get("code")} blocked={blocked} msg={r.get("msg","")[:60]}')

print(f'\nTotal submissions this session: {submission_count[0]}')

ws.close()

# -*- coding: utf-8 -*-
"""尝试获取 secsdk token 并结合真实 body 格式进行提交。"""
import json, time, sys, datetime, random, string
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9222/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), targets[0])
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
ws.settimeout(2)
mid = [0]
intercepted = []

def send_cdp(m, p=None):
    mid[0] += 1
    ws.send(json.dumps({'id': mid[0], 'method': m, 'params': p or {}}))
    return mid[0]

def recv_until(msg_id, timeout_sec=40):
    dl = time.time() + timeout_sec
    while time.time() < dl:
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        except:
            break
        try:
            msg = json.loads(raw)
        except:
            continue
        rid = msg.get('id')
        method = msg.get('method', '')

        if method == 'Fetch.requestPaused':
            params = msg.get('params', {})
            req = params.get('request', {})
            url = req.get('url', '')
            if 'addWithSchema' in url:
                print(f'\n>>> INTERCEPTED: {url[:300]}')
                print(f'    Body: {req.get("postData","")[:600]}')
                intercepted.append({'url': url, 'body': req.get('postData', ''), 'headers': req.get('headers', {})})
            send_cdp('Fetch.continueRequest', {'requestId': params.get('requestId', '')})
            continue

        if rid == msg_id:
            return msg
    return {}

# Setup
send_cdp('Fetch.enable', {
    'patterns': [{'urlPattern': '*addWithSchema*', 'requestStage': 'Request'}]
})
recv_until(mid[0], timeout_sec=5)

send_cdp('Runtime.enable')
recv_until(mid[0], timeout_sec=5)

# 1. Try to get token from secsdk
print('[1] Getting secsdk csrf token...')
send_cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            var results = {};

            if (window.secsdk && window.secsdk.csrf) {
                // Try fetchToken - this should get a new CSRF token
                try {
                    var token = await window.secsdk.csrf.fetchToken();
                    results.fetchToken = token ? token.substring(0, 50) + '...' : 'null/empty';
                } catch(e) {
                    results.fetchTokenError = e.message;
                }

                // Try fetchTokenFromLocal
                try {
                    var localToken = await window.secsdk.csrf.fetchTokenFromLocal();
                    results.localToken = localToken ? localToken.substring(0, 50) + '...' : 'null/empty';
                } catch(e) {
                    results.localTokenError = e.message;
                }

                // Get current token map
                results.tokenMap = window.secsdk.csrf.tokenMap;

                // Get protection config
                results.protectionConfig = window.secsdk.csrf.protectionConfig;
                results.whiteListConfig = window.secsdk.csrf.whiteListConfig;
            }

            return JSON.stringify(results);
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 10000
})
r = recv_until(mid[0], timeout_sec=15)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:1500]}')

# 2. Generate proper n_token and use full body
print('[2] Building complete body with all tokens...')

# Generate n_token = YYYYMMDDHHMMSS + 20 random hex chars
now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
random_hex = ''.join(random.choices('0123456789ABCDEF', k=20))
n_token = now + random_hex

# Use the shop_id from the real request
shop_id = '155450371'

body = {
    "schema": {
        "model": {
            "title": {"value": "协议测试-中筒袜夏季薄款纯色透气棉质堆堆袜女"},
            "short_product_name": {"value": ""},
            "title_prefix": {"value": ""},
            "title_suffix": {"value": ""},
            "title_use_brand_name": {"value": False},
            "goods_category": {"value": {
                "category_leaf_id": 1000010267, "first_cid": 1000003282, "first_cname": "服装",
                "second_cid": 1000009114, "second_cname": "内衣裤袜",
                "third_cid": 1000009597, "third_cname": "袜子",
                "fourth_cid": 1000010267, "fourth_cname": "中筒袜"
            }},
            "category_properties": {"value": {
                "1687": [{"diy_type": 0, "measure_info": None, "tags": None, "value_id": "596120136", "value_name": "无品牌"}],
                "1577": [{"diy_type": 0, "measure_info": None, "tags": None, "value_id": "1991", "value_name": "通用"}],
                "1865": [{"diy_type": 0, "measure_info": None, "tags": None, "value_id": "31904", "value_name": "中筒袜"}],
                "785": [
                    {"value_id": "", "value_name": "棉75%", "measure_info": {"template_id": 873, "values": [{"module_id": 1854, "prefix": "", "suffix": "", "value": "棉"}, {"module_id": 1855, "prefix": "", "suffix": "", "value": "75", "unit_id": 15, "unit_name": "%"}]}},
                    {"value_id": "", "value_name": "氨纶25%", "measure_info": {"template_id": 873, "values": [{"module_id": 1854, "prefix": "", "suffix": "", "value": "氨纶"}, {"module_id": 1855, "prefix": "", "suffix": "", "value": "25", "unit_id": 15, "unit_name": "%"}]}}
                ]
            }},
            "category_property_pic": {"value": {}},
            "pic": {"value": []},
            "main_image_three_to_four": {"value": []},
            "white_background_pic": {"value": []},
            "description": {"value": ""},
            "spec_detail": {"value": [
                {"id": "10000", "cp_id": 2752, "name": "颜色分类", "spec_values": [
                    {"id": "996874532588296918", "name": "白色", "cpv_id": 35497, "cpv_path": [{"cp_id": 4471, "cpv_id": 7054}, {"cp_id": 2752, "cpv_id": 35497}], "img_url": None}
                ]},
                {"id": "20000", "cp_id": 3939, "name": "码数", "spec_values": [
                    {"id": "990897920130195435", "name": "均码", "cpv_id": 38314, "cpv_path": [{"cp_id": 4705, "cpv_id": 38314}, {"cp_id": 3939, "cpv_id": 38314}]}
                ]},
                {"id": "30000", "cp_id": 4706, "name": "筒高长度", "spec_values": []},
                {"id": "40000", "cp_id": 93, "name": "规格", "spec_values": []}
            ]},
            "sku_detail": {"value": [
                {"id": "ee59e0bb88bc-391d48-8ad5c93ded4a", "stock_info": {"stock_num": 100}, "sku_status": True, "confirm_no_barcode": False, "spec_detail_ids": ["996874532588296918", "990897920130195435"], "price": "12.9"}
            ]},
            "freight_id": {"value": "300713474"},
            "pickup_method": {"value": "0"}, "start_sale_type": {"value": "0"}, "product_type": {"value": "0"}, "presell_type": {"value": "0"},
            "delivery_delay_day": {"value": "2"}, "reduce_type": {"value": "1"}, "qualification": {"value": {}},
            "after_sale": {"value": {"quality_problem_return": {"option_id": None, "selected": True}, "supply_day_return_selector": {"option_id": "7-1", "selected": True}}},
            "ai_gen_spec": {"value": {"ai_gen_spec_type": 0}},
            "alli_promotion_plan_switch": {"value": False}, "area_stock_switcher": {"value": False},
            "goods_category_appeal": {"value": False}, "interest_free_activity": {"value": []},
            "interest_free_activity_id": {"value": {"activity_template_id": "IFA202508061521201431032346"}},
            "interest_free_open": {"value": True}, "reference_price_enable": {"value": False},
            "detail_prettify_uri": {"value": ""},
        },
        "context": {
            "ability": [], "biz_identity": "xiaodian", "business_code": "xiaodian",
            "capability_codes": ["standard_capability"], "category_id": "1000010267", "fast_publish_type": "",
            "feature": {
                "session_publish_id": "helper_155450371177849527570085",
                "session_data": '{"stock_incr_mode":false,"only_update_stock":null}',
                "not_first_render": "1",
                "product_sale_property_control": "1",
                "sale_property_sequence_variable": "1",
                "min_sku_price": "1290",
            },
            "identity_extension": '{"Data":{}}', "model_type": "",
            "n_token": n_token,
            "operation_type": "normal",
            "product_id": "0",
            "shop_id": shop_id,
            "token": n_token,
            "version": "v1_v8_v9_v10_v11_v12",
        },
    },
    "category_id": "1000010267",
    "context": {
        "ability": [], "biz_identity": "xiaodian", "business_code": "xiaodian",
        "capability_codes": ["standard_capability"], "category_id": "1000010267", "fast_publish_type": "",
        "feature": {
            "session_publish_id": "helper_155450371177849527570085",
            "session_data": '{"stock_incr_mode":false,"only_update_stock":null}',
            "not_first_render": "1",
            "product_sale_property_control": "1",
            "sale_property_sequence_variable": "1",
            "min_sku_price": "1290",
        },
        "identity_extension": '{"Data":{}}', "model_type": "",
        "n_token": n_token,
        "operation_type": "normal",
        "product_id": "0",
        "shop_id": shop_id,
        "token": n_token,
        "version": "v1_v8_v9_v10_v11_v12",
    },
    "pass_through_extra": {},
    "request_extra": {},
    "check_status": 2,
    "session": {},
    "appid": 1,
}

print(f'    n_token: {n_token}')
print(f'    shop_id: {shop_id}')

body_json = json.dumps(body, ensure_ascii=False)

# 3. Test with webpack post
print('[3] Testing with webpack post()...')
send_cdp('Runtime.evaluate', {
    'expression': f'''
        (async function() {{
            try {{
                // Ensure webpack is setup
                if (!window.__fxgWebpackRequire) {{
                    var chunkName = Object.keys(window).find(function(k) {{ return k.includes('@ecom-mcenter/ffa-goods'); }});
                    window[chunkName].push([[Math.floor(Math.random() * 1e9)], {{}}, function(req) {{
                        window.__fxgWebpackRequire = req;
                    }}]);
                }}
                var post = window.__fxgWebpackRequire(90665).bE;
                var result = await post('/product/tproduct/addWithSchema?check_status=2', {body_json}, {{timeout: 30000}});
                return JSON.stringify({{errno: result.errno, code: result.code, msg: result.msg, data: result.data ? 'exists' : null}});
            }} catch(e) {{
                return JSON.stringify({{error: true, errno: e.errno, code: e.code, msg: e.msg}});
            }}
        }})()
    ''',
    'returnByValue': True, 'awaitPromise': True, 'timeout': 40000
})
post_id = mid[0]
r = recv_until(post_id, timeout_sec=50)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    Result: {val[:600]}')

# 4. Try with _aToken from the real capture (reuse old one)
print('\n[4] Testing with real _aToken from previous capture...')
real_aToken = "VkZaU41ZrMVZOVVZXV0dST1pXMU9ORlJXVWxKbFZURnhWMVJPVG1GclJYbFVWbEphWkRBMVZWcDZRbE5TUjNONVZWWlNVbVZyT1VWWFZFWlFVa2RqZDFSVlVrNU5Sa1l6VUZRd1BRPT0="

body['request_extra'] = {'_aToken': real_aToken}
body_json2 = json.dumps(body, ensure_ascii=False)

send_cdp('Runtime.evaluate', {
    'expression': f'''
        (async function() {{
            try {{
                var post = window.__fxgWebpackRequire(90665).bE;
                var result = await post('/product/tproduct/addWithSchema?check_status=2', {body_json2}, {{timeout: 30000}});
                return JSON.stringify({{errno: result.errno, code: result.code, msg: result.msg, data: result.data ? 'exists' : null}});
            }} catch(e) {{
                return JSON.stringify({{error: true, errno: e.errno, code: e.code, msg: e.msg}});
            }}
        }})()
    ''',
    'returnByValue': True, 'awaitPromise': True, 'timeout': 40000
})
post_id = mid[0]
r = recv_until(post_id, timeout_sec=50)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    Result with _aToken: {val[:600]}')

# 5. Try generating _aToken from the bdms SDK
print('\n[5] Exploring bdms SDK for token generation...')
send_cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = {};
            // Check if bdms.js exposed any global
            var bdmsKeys = Object.keys(window).filter(function(k) {
                return k.toLowerCase().includes('bdm') || k.toLowerCase().includes('risk') || k.toLowerCase().includes('glue');
            });
            results.bdmsKeys = bdmsKeys;

            // Check for any object with _aToken related methods
            Object.keys(window).forEach(function(k) {
                try {
                    var v = window[k];
                    if (v && typeof v === 'object' && v._aToken) {
                        results[k + '._aToken'] = v._aToken.substring(0, 50);
                    }
                    if (v && typeof v === 'object' && typeof v.getAtoken === 'function') {
                        results[k + '.getAtoken'] = 'function exists';
                    }
                } catch(e) {}
            });

            return JSON.stringify(results);
        })()
    ''',
    'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
r = recv_until(mid[0], timeout_sec=15)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:800]}')

ws.close()

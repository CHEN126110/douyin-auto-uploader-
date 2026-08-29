# -*- coding: utf-8 -*-
"""尝试通过页面底层 axios/fetch 实例发送请求，利用已有拦截器生成完整认证信息。"""
import json, time, sys
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
                print(f'    Body: {req.get("postData","")[:500]}')
                intercepted.append({'url': url, 'body': req.get('postData', ''), 'headers': req.get('headers', {})})
            send_cdp('Fetch.continueRequest', {'requestId': params.get('requestId', '')})
            continue

        if rid == msg_id:
            return msg
    return {}

# Enable Fetch interception
send_cdp('Fetch.enable', {
    'patterns': [{'urlPattern': '*addWithSchema*', 'requestStage': 'Request'}]
})
recv_until(mid[0], timeout_sec=5)

# Enable Runtime
send_cdp('Runtime.enable')
recv_until(mid[0], timeout_sec=5)

# Strategy: Find and use the page's own fetch mechanism
# The webpack post() uses an axios-like instance with interceptors
# Let's find it and use it directly

print('[1] Searching for axios/fetch instance...')
send_cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            if (!window.__fxgWebpackRequire) {
                window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) {
                    window.__fxgWebpackRequire = req;
                }]);
            }
            var req = window.__fxgWebpackRequire;

            // Examine module 90665 (post function) — look at what it wraps
            var postMod = req(90665);
            // Find axios/http instance
            var httpInstance = null;
            // Check if postMod has an underlying HTTP client
            for (var k in postMod) {
                if (typeof postMod[k] === 'function') {
                    var fnStr = postMod[k].toString().substring(0, 200);
                }
            }

            // Try to find any XMLHttpRequest or fetch wrapper
            var results = {postModKeys: Object.keys(postMod).slice(0, 20)};

            // Try req(28974) which is the GET function
            var getMod = req(28974);
            results.getModKeys = Object.keys(getMod).slice(0, 20);

            // Try to find axios on window or in modules
            results.hasAxios = typeof window.axios !== 'undefined';

            // Check module cache for http-related modules
            var cache = req.c || req.m || {};
            results.cacheKeys = Object.keys(cache).length;

            // Try to find the actual http request function
            // postMod.bE is the post function - let's see its source
            if (postMod.bE) {
                results.postSource = postMod.bE.toString().substring(0, 500);
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
print(f'    {val[:1000]}')

# 2. Try to find the function that generates request_extra
print('[2] Looking for request_extra generator...')
send_cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var req = window.__fxgWebpackRequire;
            // Look for modules that export functions related to request transformation
            var found = [];
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            var modules = window[chunkName][1];

            Object.keys(modules).forEach(function(k) {
                var src = String(modules[k]);
                if (src.includes('request_extra') || src.includes('_aToken')) {
                    found.push({id: k, snippet: src.substring(Math.max(0, src.indexOf('request_extra') - 50), src.indexOf('request_extra') + 100)});
                }
            });

            return JSON.stringify({modulesWithRequestExtra: found.slice(0, 5)});
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 10000
})
r = recv_until(mid[0], timeout_sec=15)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:800]}')

# 3. Try using the page's native fetch with all headers
print('[3] Trying native page fetch with manual body...')
body = {
    "schema": {
        "model": {
            "title": {"value": "协议测试-中筒袜夏季薄款纯色透气棉质堆堆袜女"},
            "short_product_name": {"value": ""},
            "title_prefix": {"value": ""},
            "title_suffix": {"value": ""},
            "title_use_brand_name": {"value": False},
            "goods_category": {"value": {"category_leaf_id": 1000010267, "first_cid": 1000003282, "first_cname": "服装", "second_cid": 1000009114, "second_cname": "内衣裤袜", "third_cid": 1000009597, "third_cname": "袜子", "fourth_cid": 1000010267, "fourth_cname": "中筒袜"}},
            "category_properties": {"value": {"1687": [{"diy_type": 0, "measure_info": None, "tags": None, "value_id": "596120136", "value_name": "无品牌"}], "1577": [{"diy_type": 0, "measure_info": None, "tags": None, "value_id": "1991", "value_name": "通用"}], "1865": [{"diy_type": 0, "measure_info": None, "tags": None, "value_id": "31904", "value_name": "中筒袜"}], "785": [{"value_id": "", "value_name": "棉75%", "measure_info": {"template_id": 873, "values": [{"module_id": 1854, "value": "棉"}, {"module_id": 1855, "value": "75", "unit_id": 15, "unit_name": "%"}]}}, {"value_id": "", "value_name": "氨纶25%", "measure_info": {"template_id": 873, "values": [{"module_id": 1854, "value": "氨纶"}, {"module_id": 1855, "value": "25", "unit_id": 15, "unit_name": "%"}]}}]}},
            "category_property_pic": {"value": {}},
            "pic": {"value": []},
            "main_image_three_to_four": {"value": []},
            "white_background_pic": {"value": []},
            "description": {"value": ""},
            "spec_detail": {"value": [
                {"id": "10000", "cp_id": 2752, "name": "颜色分类", "spec_values": [
                    {"id": "996874532588296900", "name": "白色", "cpv_id": 0, "cpv_path": [], "img_url": None}
                ]},
                {"id": "20000", "cp_id": 3939, "name": "码数", "spec_values": [{"id": "990897920130195400", "name": "均码", "cpv_id": 0, "cpv_path": [], "img_url": None}]},
                {"id": "30000", "cp_id": 4706, "name": "筒高长度", "spec_values": []},
                {"id": "40000", "cp_id": 93, "name": "规格", "spec_values": []}
            ]},
            "sku_detail": {"value": [
                {"id": "sku_001", "stock_info": {"stock_num": 100}, "sku_status": True, "confirm_no_barcode": False, "spec_detail_ids": ["996874532588296900", "990897920130195400"], "price": "9.9"}
            ]},
            "freight_id": {"value": "300713474"},
            "pickup_method": {"value": "0"}, "start_sale_type": {"value": "0"}, "product_type": {"value": "0"}, "presell_type": {"value": "0"},
            "delivery_delay_day": {"value": "2"}, "reduce_type": {"value": "1"}, "qualification": {"value": {}},
            "after_sale": {"value": {"quality_problem_return": {}, "supply_day_return_selector": {}}},
            "ai_gen_spec": {"value": {"ai_gen_spec_type": 0}},
            "alli_promotion_plan_switch": {"value": False}, "area_stock_switcher": {"value": False},
            "goods_category_appeal": {"value": False}, "interest_free_activity": {"value": []},
            "interest_free_activity_id": {"value": {}}, "interest_free_open": {"value": True},
            "reference_price_enable": {"value": False}, "detail_prettify_uri": {"value": ""},
        },
        "context": {
            "ability": [], "biz_identity": "xiaodian", "business_code": "xiaodian",
            "capability_codes": ["standard_capability"], "category_id": "1000010267", "fast_publish_type": "",
            "feature": {"session_publish_id": "helper_155450371177849527570085", "session_data": '{"stock_incr_mode":false,"only_update_stock":null}', "not_first_render": "1"},
            "identity_extension": '{"Data":{}}', "model_type": "", "n_token": "", "operation_type": "normal",
            "product_id": "0", "shop_id": "", "token": "", "version": "v1_v8_v9_v10_v11_v12",
        },
    },
    "category_id": "1000010267",
    "context": {
        "ability": [], "biz_identity": "xiaodian", "business_code": "xiaodian",
        "capability_codes": ["standard_capability"], "category_id": "1000010267", "fast_publish_type": "",
        "feature": {"session_publish_id": "helper_155450371177849527570085", "session_data": '{"stock_incr_mode":false,"only_update_stock":null}', "not_first_render": "1"},
        "identity_extension": '{"Data":{}}', "model_type": "", "n_token": "", "operation_type": "normal",
        "product_id": "0", "shop_id": "", "token": "", "version": "v1_v8_v9_v10_v11_v12",
    },
    "pass_through_extra": {}, "request_extra": {}, "check_status": 2, "session": {}, "appid": 1,
}
body_json = json.dumps(body, ensure_ascii=False)

send_cdp('Runtime.evaluate', {
    'expression': f'''
        (async function() {{
            try {{
                var resp = await fetch('/product/tproduct/addWithSchema?check_status=2', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json;charset=UTF-8'}},
                    body: JSON.stringify({body_json}),
                    credentials: 'include'
                }});
                var text = await resp.text();
                return JSON.stringify({{status: resp.status, body: text.substring(0, 500)}});
            }} catch(e) {{
                return JSON.stringify({{error: e.message || String(e)}});
            }}
        }})()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 30000
})
r = recv_until(mid[0], timeout_sec=35)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    Native fetch result: {val[:600]}')

# 4. Try to extract the full authenticated body by watching the page submit a real product
# Use the page's global store/model to trigger submit
print('[4] Checking page store/model for submit action...')
send_cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var results = {};
            // Check for Vue/Pinia/Redux store
            var appEl = document.getElementById('app') || document.querySelector('[data-app]');
            if (appEl && appEl.__vue_app__) {
                results.hasVue = true;
            }

            // Check for global store
            var storeKeys = Object.keys(window).filter(function(k) {
                return k.toLowerCase().includes('store') || k.toLowerCase().includes('state');
            });
            results.storeKeys = storeKeys.slice(0, 10);

            // Find the submit button or form
            var submitBtn = document.querySelector('button:contains("发布"), button:contains("提交"), button:contains("保存")');
            results.hasSubmitBtn = !!submitBtn;

            return JSON.stringify(results);
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 10000
})
r = recv_until(mid[0], timeout_sec=15)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:500]}')

print(f'\n[5] Total intercepted: {len(intercepted)}')
for i, req in enumerate(intercepted):
    print(f'\n  Intercepted #{i+1}:')
    print(f'    URL: {req["url"][:250]}')

ws.close()

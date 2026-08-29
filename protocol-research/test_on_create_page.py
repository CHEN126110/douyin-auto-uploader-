# -*- coding: utf-8 -*-
"""导航到发品页，完整初始化后测试协议提交。"""
import json, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9222/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), targets[0])
tab_id = t['id']
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
ws.settimeout(3)
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
                print(f'\n>>> INTERCEPTED: {url[:200]}')
                print(f'    Body ({len(req.get("postData",""))} chars): {req.get("postData","")[:500]}')
                intercepted.append({'url': url, 'body': req.get('postData', '')})
            send_cdp('Fetch.continueRequest', {'requestId': params.get('requestId', '')})
            continue

        if method == 'Page.frameStoppedLoading':
            print(f'    Page frame loaded')

        if rid == msg_id:
            return msg
    return {}

# 1. Navigate to create page
print('[1] Navigating to /ffa/g/create...')
send_cdp('Page.enable')
recv_until(mid[0], timeout_sec=5)

send_cdp('Page.navigate', {'url': 'https://fxg.jinritemai.com/ffa/g/create'})
r = recv_until(mid[0], timeout_sec=30)
print(f'    Navigated')

# 2. Wait for page to fully load
print('[2] Waiting for page to load...')
time.sleep(5)

# Check current URL
send_cdp('Runtime.evaluate', {
    'expression': 'window.location.href',
    'returnByValue': True
})
r = recv_until(mid[0], timeout_sec=10)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    Current URL: {val}')

# 3. Enable Fetch interception for addWithSchema
print('[3] Setting up Fetch interception...')
send_cdp('Fetch.enable', {
    'patterns': [{'urlPattern': '*addWithSchema*', 'requestStage': 'Request'}]
})
recv_until(mid[0], timeout_sec=5)

# 4. Inject webpack and get publishId
print('[4] Injecting webpack...')
send_cdp('Runtime.enable')
recv_until(mid[0], timeout_sec=5)

send_cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            // Wait for page to fully init
            await new Promise(r => setTimeout(r, 2000));

            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            if (!chunkName) return JSON.stringify({error: 'chunk not found', keys: Object.keys(window).filter(function(k) { return k.includes('ffa'); })});

            if (!window.__fxgWebpackRequire) {
                window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) {
                    window.__fxgWebpackRequire = req;
                }]);
            }

            var req = window.__fxgWebpackRequire;
            var pid = req(68671).T({useUrlParams: true, useWindowCache: true, writeWindowCache: true});
            window.__fxgPost = req(90665).bE;
            window.__fxgGet = req(28974).J;
            window.__fxgPublishId = pid;

            // Also get csrf token from page context
            var csrfToken = '';
            try {
                csrfToken = window.__secsdk_csrftoken || window.secsdk_csrftoken || '';
            } catch(e) {}

            // Get shop_id from page
            var shopId = '';
            try {
                var state = window.__INITIAL_STATE__ || window.__STORE__ || {};
                shopId = (state.shop || {}).shop_id || '';
            } catch(e) {}

            return JSON.stringify({ok: true, publishId: pid, csrf: csrfToken ? csrfToken.substring(0,30)+'...' : 'none', shopId: shopId});
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 15000
})
r = recv_until(mid[0], timeout_sec=20)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:300]}')

# 5. Try the full protocol submit
print('[5] Testing addWithSchema via webpack post()...')

body = {
    "schema": {
        "model": {
            "title": {"value": "协议测试-中筒袜夏季薄款纯色透气棉质堆堆袜女"},
            "short_product_name": {"value": ""},
            "title_prefix": {"value": ""},
            "title_suffix": {"value": ""},
            "title_use_brand_name": {"value": False},
            "goods_category": {"value": {"category_leaf_id": 1000010267, "first_cid": 1000003282, "first_cname": "服装", "second_cid": 1000009114, "second_cname": "内衣裤袜", "third_cid": 1000009597, "third_cname": "袜子", "fourth_cid": 1000010267, "fourth_cname": "中筒袜"}},
            "category_properties": {"value": {"1687": [{"diy_type": 0, "measure_info": None, "tags": None, "value_id": "596120136", "value_name": "无品牌"}], "1577": [{"diy_type": 0, "measure_info": None, "tags": None, "value_id": "1991", "value_name": "通用"}], "1865": [{"diy_type": 0, "measure_info": None, "tags": None, "value_id": "31904", "value_name": "中筒袜"}], "785": [{"value_id": "", "value_name": "棉75%", "measure_info": {"template_id": 873, "values": [{"module_id": 1854, "prefix": "", "suffix": "", "value": "棉"}, {"module_id": 1855, "prefix": "", "suffix": "", "value": "75", "unit_id": 15, "unit_name": "%"}]}}, {"value_id": "", "value_name": "氨纶25%", "measure_info": {"template_id": 873, "values": [{"module_id": 1854, "prefix": "", "suffix": "", "value": "氨纶"}, {"module_id": 1855, "prefix": "", "suffix": "", "value": "25", "unit_id": 15, "unit_name": "%"}]}}]}},
            "category_property_pic": {"value": {}},
            "pic": {"value": [{"url": "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_646be43f717bf456b1061922110578b9_sx_3180433_www1440-1440"}]},
            "main_image_three_to_four": {"value": [{"url": "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_689e487ff9f6368e3a20f1e43aac2922_sx_348932_www1440-1920"}]},
            "white_background_pic": {"value": []},
            "description": {"value": ""},
            "spec_detail": {"value": [
                {"id": "10000", "cp_id": 2752, "name": "颜色分类", "spec_values": [
                    {"id": "996874532588296900", "name": "白色", "cpv_id": 0, "cpv_path": [], "img_url": None},
                    {"id": "996874532588296901", "name": "黑色", "cpv_id": 0, "cpv_path": [], "img_url": None}
                ]},
                {"id": "20000", "cp_id": 3939, "name": "码数", "spec_values": [{"id": "990897920130195400", "name": "均码", "cpv_id": 0, "cpv_path": [], "img_url": None}]},
                {"id": "30000", "cp_id": 4706, "name": "筒高长度", "spec_values": []},
                {"id": "40000", "cp_id": 93, "name": "规格", "spec_values": []}
            ]},
            "sku_detail": {"value": [
                {"id": "sku_test_001", "stock_info": {"stock_num": 100}, "sku_status": True, "confirm_no_barcode": False, "spec_detail_ids": ["996874532588296900", "990897920130195400"], "price": "12.9"},
                {"id": "sku_test_002", "stock_info": {"stock_num": 100}, "sku_status": True, "confirm_no_barcode": False, "spec_detail_ids": ["996874532588296901", "990897920130195400"], "price": "12.9"}
            ]},
            "freight_id": {"value": "300713474"},
            "pickup_method": {"value": "0"},
            "start_sale_type": {"value": "0"},
            "product_type": {"value": "0"},
            "presell_type": {"value": "0"},
            "delivery_delay_day": {"value": "2"},
            "reduce_type": {"value": "1"},
            "qualification": {"value": {}},
            "after_sale": {"value": {"quality_problem_return": {}, "supply_day_return_selector": {}}},
            "ai_gen_spec": {"value": {"ai_gen_spec_type": 0}},
            "alli_promotion_plan_switch": {"value": False},
            "area_stock_switcher": {"value": False},
            "goods_category_appeal": {"value": False},
            "interest_free_activity": {"value": []},
            "interest_free_activity_id": {"value": {}},
            "interest_free_open": {"value": True},
            "reference_price_enable": {"value": False},
            "detail_prettify_uri": {"value": ""},
        },
        "context": {
            "ability": [],
            "biz_identity": "xiaodian",
            "business_code": "xiaodian",
            "capability_codes": ["standard_capability"],
            "category_id": "1000010267",
            "fast_publish_type": "",
            "feature": {
                "session_publish_id": "helper_155450371177849477678689",
                "session_data": '{"stock_incr_mode":false,"only_update_stock":null}',
                "not_first_render": "1",
            },
            "identity_extension": '{"Data":{}}',
            "model_type": "",
            "n_token": "",
            "operation_type": "normal",
            "product_id": "0",
            "shop_id": "",
            "token": "",
            "version": "v1_v8_v9_v10_v11_v12",
        },
    },
    "category_id": "1000010267",
    "context": {
        "ability": [],
        "biz_identity": "xiaodian",
        "business_code": "xiaodian",
        "capability_codes": ["standard_capability"],
        "category_id": "1000010267",
        "fast_publish_type": "",
        "feature": {
            "session_publish_id": "helper_155450371177849477678689",
            "session_data": '{"stock_incr_mode":false,"only_update_stock":null}',
            "not_first_render": "1",
        },
        "identity_extension": '{"Data":{}}',
        "model_type": "",
        "n_token": "",
        "operation_type": "normal",
        "product_id": "0",
        "shop_id": "",
        "token": "",
        "version": "v1_v8_v9_v10_v11_v12",
    },
    "pass_through_extra": {},
    "request_extra": {},
    "check_status": 2,
    "session": {},
    "appid": 1,
}

body_json = json.dumps(body, ensure_ascii=False)

send_cdp('Runtime.evaluate', {
    'expression': f'''
        (async function() {{
            try {{
                var post = window.__fxgPost;
                if (!post) {{
                    var chunkName = Object.keys(window).find(function(k) {{ return k.includes('@ecom-mcenter/ffa-goods'); }});
                    window[chunkName].push([[Math.floor(Math.random() * 1e9)], {{}}, function(req) {{
                        window.__fxgWebpackRequire = req;
                    }}]);
                    post = window.__fxgWebpackRequire(90665).bE;
                }}
                var result = await post('/product/tproduct/addWithSchema?check_status=2', {body_json}, {{timeout: 30000}});
                return JSON.stringify({{errno: result.errno, code: result.code, msg: result.msg, data: result.data ? 'exists' : null}});
            }} catch(e) {{
                return JSON.stringify({{error: true, errno: e.errno, code: e.code, msg: e.msg}});
            }}
        }})()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 40000
})
post_id = mid[0]
r = recv_until(post_id, timeout_sec=50)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    Result: {val[:800]}')

print(f'\n[6] Intercepted {len(intercepted)} requests')

ws.close()

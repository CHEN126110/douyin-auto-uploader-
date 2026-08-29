# -*- coding: utf-8 -*-
"""用 CDP Fetch.enable 拦截 webpack post() 发出的实际请求，诊断 10002 错误根因。
修复版：在等待 Runtime.evaluate 时同步处理 Fetch.requestPaused 事件。"""
import json, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9222/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), targets[0])
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
ws.settimeout(2)  # 2s timeout for recv
mid = [0]
intercepted = []

def send_cdp(m, p=None):
    mid[0] += 1
    ws.send(json.dumps({'id': mid[0], 'method': m, 'params': p or {}}))
    return mid[0]

def recv_until(msg_id, extra_handlers=None, timeout_sec=40):
    """等待指定 id 的响应，同时处理其他事件"""
    dl = time.time() + timeout_sec
    while time.time() < dl:
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        except Exception as e:
            print(f'  WS recv error: {e}')
            break
        try:
            msg = json.loads(raw)
        except:
            continue

        rid = msg.get('id')
        method = msg.get('method', '')

        # 处理 Fetch 拦截事件
        if method == 'Fetch.requestPaused':
            params = msg.get('params', {})
            request = params.get('request', {})
            post_data = request.get('postData', '')
            url = request.get('url', '')
            headers = request.get('headers', {})
            request_id = params.get('requestId', '')

            print(f'\n>>> INTERCEPTED: {url[:200]}')
            print(f'    Body ({len(post_data)} chars): {post_data[:500]}')

            intercepted.append({
                'url': url,
                'headers': {k: v for k, v in headers.items() if k not in ('Cookie',)},
                'body': post_data,
            })

            # 继续请求
            send_cdp('Fetch.continueRequest', {'requestId': request_id})
            continue

        # 检查是否是我们等待的响应
        if rid == msg_id:
            return msg

    return {}

# 1. 启用 Fetch 拦截
print('[1] Enabling Fetch interception...')
send_cdp('Fetch.enable', {
    'patterns': [{'urlPattern': '*addWithSchema*', 'requestStage': 'Request'}]
})
recv_until(mid[0], timeout_sec=10)
print('    Fetch enabled')

# 2. 注入 webpack require
print('[2] Injecting webpack...')
send_cdp('Runtime.enable')
recv_until(mid[0], timeout_sec=5)

send_cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            if (!chunkName) return JSON.stringify({error: 'chunk not found'});
            if (!window.__fxgWebpackRequire) {
                window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) {
                    window.__fxgWebpackRequire = req;
                }]);
            }
            var req = window.__fxgWebpackRequire;
            var pid = req(68671).T({useUrlParams: true, useWindowCache: true, writeWindowCache: true});
            window.__fxgPost = req(90665).bE;
            window.__fxgPublishId = pid;
            return JSON.stringify({ok: true, publishId: pid});
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': False,
    'timeout': 10000
})
r = recv_until(mid[0], timeout_sec=15)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'    {val[:200]}')

# 3. 构建 body (使用与真实请求一致的 cpv_id/cpv_path/after_sale)
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
            "white_background_pic": {"value": [{"url": "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_d1a3c94d03948b1127a789a7ec5c9e1b_sx_1958777_www1440-1440"}]},
            "description": {"value": ""},
            "spec_detail": {"value": [
                {"id": "10000", "cp_id": 2752, "name": "颜色分类", "spec_values": [
                    {"id": "996874532588296918", "name": "白色", "cpv_id": 35497, "cpv_path": [{"cp_id": 4471, "cpv_id": 7054}, {"cp_id": 2752, "cpv_id": 35497}], "img_url": None},
                    {"id": "995353169998108238", "name": "黑色", "cpv_id": 24860, "cpv_path": [{"cp_id": 4471, "cpv_id": 11846}, {"cp_id": 2752, "cpv_id": 24860}], "img_url": None}
                ]},
                {"id": "20000", "cp_id": 3939, "name": "码数", "spec_values": [{"id": "990897920130195435", "name": "均码", "cpv_id": 38314, "cpv_path": [{"cp_id": 4705, "cpv_id": 38314}, {"cp_id": 3939, "cpv_id": 38314}]}]},
                {"id": "30000", "cp_id": 4706, "name": "筒高长度", "spec_values": []},
                {"id": "40000", "cp_id": 93, "name": "规格", "spec_values": []}
            ]},
            "sku_detail": {"value": [
                {"id": "ee59e0bb88bc-391d48-8ad5c93ded4a", "stock_info": {"stock_num": 100}, "sku_status": True, "confirm_no_barcode": False, "spec_detail_ids": ["996874532588296918", "990897920130195435"], "price": "12.9"},
                {"id": "89cffe80318b-c48e3a-089096a13536", "stock_info": {"stock_num": 100}, "sku_status": True, "confirm_no_barcode": False, "spec_detail_ids": ["995353169998108238", "990897920130195435"], "price": "12.9"}
            ]},
            "freight_id": {"value": "300713474"},
            "pickup_method": {"value": "0"},
            "start_sale_type": {"value": "0"},
            "product_type": {"value": "0"},
            "presell_type": {"value": "0"},
            "delivery_delay_day": {"value": "2"},
            "reduce_type": {"value": "1"},
            "qualification": {"value": {}},
            "after_sale": {"value": {"quality_problem_return": {"option_id": None, "selected": True}, "supply_day_return_selector": {"option_id": "7-1", "selected": True}}},
            "ai_gen_spec": {"value": {"ai_gen_spec_type": 0}},
            "alli_promotion_plan_switch": {"value": False},
            "area_stock_switcher": {"value": False},
            "goods_category_appeal": {"value": False},
            "interest_free_activity": {"value": []},
            "interest_free_activity_id": {"value": {"activity_template_id": "IFA202508061521201431032346"}},
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
                "session_publish_id": "helper_155450371177834006902853",
                "session_data": '{"stock_incr_mode":false,"only_update_stock":null}',
                "not_first_render": "1",
                "product_sale_property_control": "1",
                "sale_property_sequence_variable": "1",
                "min_sku_price": "1290",
            },
            "identity_extension": '{"Data":{}}',
            "model_type": "",
            "n_token": "",
            "operation_type": "normal",
            "product_id": "0",
            "shop_id": "155450371",
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
            "session_publish_id": "helper_155450371177834006902853",
            "session_data": '{"stock_incr_mode":false,"only_update_stock":null}',
            "not_first_render": "1",
            "product_sale_property_control": "1",
            "sale_property_sequence_variable": "1",
            "min_sku_price": "1290",
        },
        "identity_extension": '{"Data":{}}',
        "model_type": "",
        "n_token": "",
        "operation_type": "normal",
        "product_id": "0",
        "shop_id": "155450371",
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

# 4. 发送请求
print(f'[3] Calling post() with body ({len(body_json)} chars)...')

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
                return JSON.stringify({{errno: result.errno, code: result.code, msg: result.msg}});
            }} catch(e) {{
                return JSON.stringify({{error: true, errno: e.errno, code: e.code, msg: e.msg}});
            }}
        }})()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 40000
})

post_msg_id = mid[0]
print(f'    (msgId={post_msg_id}, waiting for response + Fetch events...)')

# 5. 等待 post() 响应，同时处理 Fetch 事件
r = recv_until(post_msg_id, timeout_sec=50)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'[4] post() result: {val[:800]}')

# 6. 继续收尾消息
print(f'[5] Intercepted {len(intercepted)} requests total')
for i, req in enumerate(intercepted):
    print(f'\n  Req #{i+1}:')
    print(f'    URL: {req["url"][:300]}')
    print(f'    Body: {req["body"][:500]}')

# Save
out = r'E:\Script Project\Dyin\beiufen\2.0\tmp_runtime_probe_live\debug_intercepted.json'
with open(out, 'w', encoding='utf-8') as f:
    json.dump({
        'result': json.loads(val) if val else {},
        'intercepted': intercepted
    }, f, ensure_ascii=False, indent=2)
print(f'\nSaved: {out}')

ws.close()

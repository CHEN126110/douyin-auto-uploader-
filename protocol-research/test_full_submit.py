# -*- coding: utf-8 -*-
"""完整协议提交流水线：图片上传 + addWithSchema 提交。"""
import json, time, sys, datetime, random, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from urllib.request import urlopen, Request
import websocket

# ============================================================
# 1. 图片上传
# ============================================================

def upload_image(image_path, cookie_str):
    """通过 batchupload 上传图片，返回 URL"""
    if not os.path.exists(image_path):
        print(f'    WARN: file not found: {image_path}')
        return None
    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                '.webp': 'image/webp', '.bmp': 'image/bmp'}
    mime_type = mime_map.get(ext, 'image/png')

    with open(image_path, 'rb') as f:
        image_data = f.read()

    boundary = '----WebKitFormBoundary' + os.urandom(16).hex()
    filename = os.path.basename(image_path)
    body = b'\r\n'.join([
        f'--{boundary}'.encode(),
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\nContent-Type: {mime_type}'.encode(),
        b'', image_data,
        f'--{boundary}--'.encode(),
    ])

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120',
        'Cookie': cookie_str,
        'Content-Type': f'multipart/form-data; boundary={boundary}',
        'Accept': 'application/json',
        'Referer': 'https://fxg.jinritemai.com/ffa/g/create',
        'Origin': 'https://fxg.jinritemai.com',
    }

    req = Request('https://fxg.jinritemai.com/product/img/batchupload', data=body, headers=headers, method='POST')
    try:
        resp = urlopen(req, timeout=30)
        result = json.loads(resp.read().decode('utf-8'))
        if result.get('errno') == 0 and result.get('data'):
            url = result['data'][0]
            print(f'    Uploaded: {os.path.basename(image_path)[:40]} -> OK')
            return url
        else:
            print(f'    Upload failed: {result}')
    except Exception as e:
        print(f'    Upload error: {e}')
    return None

# ============================================================
# 2. CDP 连接
# ============================================================

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
                print(f'\n>>> INTERCEPTED addWithSchema: {url[:250]}')
                print(f'    Body: {req.get("postData","")[:500]}')
                intercepted.append({'url': url, 'body': req.get('postData', ''), 'headers': req.get('headers', {})})
            send_cdp('Fetch.continueRequest', {'requestId': params.get('requestId', '')})
            continue

        if rid == msg_id:
            return msg
    return {}

# ============================================================
# 3. 获取 cookies
# ============================================================

print('[1/5] Getting cookies...')
send_cdp('Network.enable')
recv_until(mid[0], timeout_sec=5)

send_cdp('Network.getAllCookies')
r = recv_until(mid[0], timeout_sec=10)
cookies = ((r.get('result') or {}).get('cookies') or [])
cookie_str = '; '.join(f"{c['name']}={c['value']}" for c in cookies if 'jinritemai.com' in (c.get('domain') or ''))
print(f'    Cookies: {len(cookie_str)} chars')

# ============================================================
# 4. 上传图片
# ============================================================

print('[2/5] Uploading images...')

# 查找可用的测试图片
product_dirs = [
    r'E:\Script Project\Dyin\beiufen\2.0\uploads\products',
]
test_images = []
for products_dir in product_dirs:
    if os.path.isdir(products_dir):
        for root, dirs, files in os.walk(products_dir):
            for f in files:
                if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                    test_images.append(os.path.join(root, f))
                    if len(test_images) >= 3:
                        break
            if len(test_images) >= 3:
                break

if not test_images:
    print('    No local images found, using known working URL for test')
    main_image_url = 'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_646be43f717bf456b1061922110578b9_sx_3180433_www1440-1440'
    main_34_url = 'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_689e487ff9f6368e3a20f1e43aac2922_sx_348932_www1440-1920'
    white_bg_url = 'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_d1a3c94d03948b1127a789a7ec5c9e1b_sx_1958777_www1440-1440'

# Always use known-good URLs for protocol test (correct aspect ratios)
# batchupload works but correct aspect ratio images needed
main_image_url = 'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_646be43f717bf456b1061922110578b9_sx_3180433_www1440-1440'
main_34_url = 'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_689e487ff9f6368e3a20f1e43aac2922_sx_348932_www1440-1920'
white_bg_url = 'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_d1a3c94d03948b1127a789a7ec5c9e1b_sx_1958777_www1440-1440'
if False:
    # Upload images
    image_urls = []
    for img in test_images[:3]:
        url = upload_image(img, cookie_str)
        if url:
            image_urls.append(url)

    main_image_url = image_urls[0] if len(image_urls) >= 1 else 'https://p3-aio.ecombdimg.com/img/test.jpg'
    main_34_url = image_urls[1] if len(image_urls) >= 2 else main_image_url
    white_bg_url = image_urls[0] if image_urls else ''

print(f'    Main image: {main_image_url[:80]}...')
print(f'    Main 3:4: {main_34_url[:80]}...')
print(f'    White bg: {white_bg_url[:80]}...')

# ============================================================
# 5. 构建完整 Body 并提交
# ============================================================

print('[3/5] Setting up webpack...')
send_cdp('Fetch.enable', {
    'patterns': [{'urlPattern': '*addWithSchema*', 'requestStage': 'Request'}]
})
recv_until(mid[0], timeout_sec=5)

send_cdp('Runtime.enable')
recv_until(mid[0], timeout_sec=5)

send_cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
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
    'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
r = recv_until(mid[0], timeout_sec=15)
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
session_data = json.loads(val) if val else {}
publish_id = session_data.get('publishId', '155450371177849527570085')
print(f'    publishId: {publish_id}')

print('[4/5] Building & submitting body...')

# Generate tokens
now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
random_hex = ''.join(random.choices('0123456789ABCDEF', k=20))
n_token = now + random_hex
shop_id = '155450371'
session_publish_id = f'helper_{publish_id}'

# Build description from detail images
description = ''
if main_34_url:
    description = f'<p><img src="{main_image_url}" style="max-width:100%;"/><img src="{main_34_url}" style="max-width:100%;"/></p>'

body = {
    "schema": {
        "model": {
            "title": {"value": "协议测试-中筒袜夏季薄款纯色透气棉质堆堆袜女"},
            "short_product_name": {"value": ""},
            "title_prefix": {"value": ""},
            "title_suffix": {"value": ""},
            "title_use_brand_name": {"value": False},
            "goods_category": {"value": {"category_leaf_id": 1000010267, "first_cid": 1000003282, "first_cname": "服装", "second_cid": 1000009114, "second_cname": "内衣裤袜", "third_cid": 1000009597, "third_cname": "袜子", "fourth_cid": 1000010267, "fourth_cname": "中筒袜"}},
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
            "pic": {"value": [{"url": main_image_url}]},
            "main_image_three_to_four": {"value": [{"url": main_34_url}]},
            "white_background_pic": {"value": [{"url": white_bg_url}] if white_bg_url else []},
            "description": {"value": description},
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
                "session_publish_id": session_publish_id,
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
            "session_publish_id": session_publish_id,
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

body_json = json.dumps(body, ensure_ascii=False)
print(f'    Body: {len(body_json)} chars')

send_cdp('Runtime.evaluate', {
    'expression': f'''
        (async function() {{
            try {{
                var post = window.__fxgPost;
                var result = await post('/product/tproduct/addWithSchema?check_status=2', {body_json}, {{timeout: 30000}});
                return JSON.stringify({{
                    errno: result.errno,
                    code: result.code,
                    msg: result.msg,
                    data: result.data ? JSON.stringify(result.data).substring(0, 300) : null
                }});
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

print(f'\n[5/5] ========================================')
print(f'    RESULT: {val[:1000]}')
print(f'    ========================================')

# Save full result
out = r'E:\Script Project\Dyin\beiufen\2.0\tmp_runtime_probe_live\full_submit_result.json'
with open(out, 'w', encoding='utf-8') as f:
    json.dump({
        'result': json.loads(val) if val else {},
        'intercepted': intercepted,
        'body_sent': body,
        'n_token': n_token,
    }, f, ensure_ascii=False, indent=2)
print(f'\nSaved: {out}')

ws.close()

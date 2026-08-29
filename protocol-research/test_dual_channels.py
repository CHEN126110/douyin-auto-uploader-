# -*- coding: utf-8 -*-
"""新账号实验: 90665.bE vs 28974.b 是否有独立计数器"""
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

cdp('Runtime.enable')
cdp('Page.enable')
cdp('Page.navigate', {'url': 'https://fxg.jinritemai.com/ffa/g/create'})
time.sleep(5)

# 注入所有需要的函数
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) { window.__fxgWebpackRequire = req; }]);
            var req = window.__fxgWebpackRequire;
            window.__post_custom = req(90665).bE;   // 我们一直在用的
            window.__post_axios = req(28974).b;      // 页面用的 axios
            window.__get = req(28974).J;              // GET

            // 提取 shop_id
            var shopId = '';
            try {
                var cookies = document.cookie.split(';');
                for (var i = 0; i < cookies.length; i++) {
                    var c = cookies[i].trim();
                    if (c.startsWith('ecom_gray_shop_id=')) shopId = c.split('=')[1];
                }
            } catch(e) {}
            window.__shopId = shopId;
            return JSON.stringify({ok: true, shopId: shopId});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
sess = json.loads(val) if isinstance(val, str) else (val or {})
shop_id = sess.get('shopId', '177886360')
print(f'shop_id={shop_id}')

results = []

def submit_one(label, channel, check_status=0):
    """提交一个测试商品"""
    TITLE = f'通道测试{label}中筒袜女款{random.randint(100,999)}'

    body = {'schema':{'model':{
        'title':{'value':TITLE},
        'short_product_name':{'value':''},'title_prefix':{'value':''},'title_suffix':{'value':''},
        'title_use_brand_name':{'value':False},
        'goods_category':{'value':{'category_leaf_id':1000010267,'first_cid':1000003282,'first_cname':'A','second_cid':1000009114,'second_cname':'A','third_cid':1000009597,'third_cname':'A','fourth_cid':1000010267,'fourth_cname':'A'}},
        'category_properties':{'value':{
            '1687':[{'value_id':'596120136','value_name':'无品牌'}],
            '1577':[{'value_id':'1991','value_name':'通用'}],
            '1865':[{'value_id':'31904','value_name':'中筒袜'}],
            '785':[{'value_id':'','value_name':'棉100%','measure_info':{'template_id':873,'values':[{'module_id':1854,'value':'棉'},{'module_id':1855,'value':'100','unit_id':15,'unit_name':'%'}]}}]
        }},
        'category_property_pic':{'value':{}},'pic':{'value':[]},'main_image_three_to_four':{'value':[]},'white_background_pic':{'value':[]},'description':{'value':''},
        'spec_detail':{'value':[
            {'id':'10000','cp_id':2752,'name':'颜色分类','spec_values':[{'id':'996874532588296918','name':'默认','cpv_id':0,'cpv_path':[],'img_url':None}]},
            {'id':'20000','cp_id':3939,'name':'码数','spec_values':[{'id':'990897920130195435','name':'均码','cpv_id':0,'cpv_path':[],'img_url':None}]}
        ]},
        'sku_detail':{'value':[{'id':f'ch{label}-{random.randint(0,9999)}','stock_info':{'stock_num':100},'sku_status':True,'confirm_no_barcode':False,'spec_detail_ids':['996874532588296918','990897920130195435'],'price':'9.9'}]},
        'freight_id':{'value':'300713474'},'pickup_method':{'value':'0'},'start_sale_type':{'value':'0'},'product_type':{'value':'0'},'presell_type':{'value':'0'},
        'delivery_delay_day':{'value':'2'},'reduce_type':{'value':'1'},'qualification':{'value':{}},
        'after_sale':{'value':{'quality_problem_return':{'option_id':None,'selected':True},'supply_day_return_selector':{'option_id':'7-1','selected':True}}},
        'ai_gen_spec':{'value':{'ai_gen_spec_type':0}},'alli_promotion_plan_switch':{'value':False},'area_stock_switcher':{'value':False},
        'goods_category_appeal':{'value':False},'interest_free_activity':{'value':[]},'interest_free_activity_id':{'value':{}},
        'interest_free_open':{'value':True},'reference_price_enable':{'value':False},'detail_prettify_uri':{'value':''},
    },'context':{
        'ability':[],'biz_identity':'xiaodian','business_code':'xiaodian','capability_codes':['standard_capability'],
        'category_id':'1000010267','fast_publish_type':'',
        'feature':{'session_publish_id':'helper_test','session_data':'{}','not_first_render':'1','product_sale_property_control':'1','sale_property_sequence_variable':'1','min_sku_price':'990'},
        'identity_extension':'{}','model_type':'','n_token':n_token,'operation_type':'normal',
        'product_id':'0','shop_id':shop_id,'token':n_token,'version':'v1_v8_v9_v10_v11_v12',
    }},'category_id':'1000010267','context':{
        'ability':[],'biz_identity':'xiaodian','business_code':'xiaodian','capability_codes':['standard_capability'],
        'category_id':'1000010267','fast_publish_type':'',
        'feature':{'session_publish_id':'helper_test','session_data':'{}','not_first_render':'1','product_sale_property_control':'1','sale_property_sequence_variable':'1','min_sku_price':'990'},
        'identity_extension':'{}','model_type':'','n_token':n_token,'operation_type':'normal',
        'product_id':'0','shop_id':shop_id,'token':n_token,'version':'v1_v8_v9_v10_v11_v12',
    },'pass_through_extra':{},'request_extra':{},'check_status':check_status,'session':{},'appid':1}

    now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    n_token_local = now + ''.join(random.choices('0123456789ABCDEF', k=20))
    body['schema']['context']['n_token'] = n_token_local
    body['schema']['context']['token'] = n_token_local
    body['context']['n_token'] = n_token_local
    body['context']['token'] = n_token_local

    body_json = json.dumps(body, ensure_ascii=False)
    r = cdp('Runtime.evaluate', {
        'expression': f'''
            (async function() {{
                var postFunc = window.__post_{channel};
                try {{
                    var result = await postFunc('/product/tproduct/addWithSchema?check_status={check_status}', {body_json}, {{timeout: 30000}});
                    return JSON.stringify({{code: result.code||result.errno, msg: result.msg||'', pid: result.data ? (typeof result.data === "string" ? JSON.parse(result.data).product_id : result.data.product_id) : null}});
                }} catch(e) {{
                    return JSON.stringify({{error: true, code: e.code||e.errno, msg: e.msg||e.message||String(e)}});
                }}
            }})()
        ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 40000
    })
    val = ((r.get('result') or {}).get('result') or {}).get('value', '')
    result = json.loads(val) if isinstance(val, str) else (val or {})
    pid = result.get('pid', '')
    msg = str(result.get('msg', ''))
    blocked = '非官方' in msg or '异常' in msg
    status = 'BLOCKED' if blocked else ('OK' if pid else 'FAIL')
    print(f'  [{label}] channel={channel} code={result.get("code")} pid={pid} {status}')
    results.append({'label': label, 'channel': channel, 'pid': pid, 'status': status, 'msg': msg[:60]})
    return result

# ============================================================
# 实验矩阵
# ============================================================
n_token = datetime.datetime.now().strftime('%Y%m%d%H%M%S') + 'AAAA' + 'B'*16

print()
print('=== Phase 1: Baseline — 90665.bE (our usual path) ===')
r1 = submit_one('A1_custom', 'custom', 0)

print()
print('=== Phase 2: Axios — 28974.b (page path) ===')
r2 = submit_one('B1_axios', 'axios', 0)

print()
print('=== Phase 3: Interleaved — alternate channels ===')
r3 = submit_one('A2_custom', 'custom', 0)
r4 = submit_one('B2_axios', 'axios', 0)

print()
print('=== Phase 4: publishClickStat before each ===')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            await window.__get('/product/tproduct/publishClickStat?check_status=0', {timeout: 5000});
            return 'ok';
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
print('  publishClickStat called')
r5 = submit_one('C1_clickstat', 'custom', 0)

print()
print('='*60)
print('SUMMARY:')
for r in results:
    print(f'  {r["label"]}: channel={r["channel"]} {r["status"]} pid={r.get("pid","")[:16]}')
print(f'  Total submissions: {len(results)}')

ws.close()

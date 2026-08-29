# -*- coding: utf-8 -*-
"""关键实验: 90665.bE vs 28974.b — 是否独立计数器
策略: 只用 custom 通道推到极限 (找到custom的限额N)
      然后立即切换到 axios 通道 — 如果axios还能提交, 则是独立计数器
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

# 注入
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) { window.__fxgWebpackRequire = req; }]);
            var req = window.__fxgWebpackRequire;
            window.__post_custom = req(90665).bE;
            window.__post_axios = req(28974).b;
            window.__get = req(28974).J;
            var shopId = '';
            try {
                var cookies = document.cookie.split(';');
                for (var i = 0; i < cookies.length; i++) {
                    var c = cookies[i].trim();
                    if (c.startsWith('ecom_gray_shop_id=')) shopId = c.split('=')[1];
                }
            } catch(e) {}
            window.__shopId = shopId;
            return JSON.stringify({shopId: shopId});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
sess = json.loads(val) if isinstance(val, str) else (val or {})
shop_id = sess.get('shopId', '177886360')
print(f'shop_id={shop_id}')

# Global n_token (will be updated per submission)
base_n_token = datetime.datetime.now().strftime('%Y%m%d%H%M%S')

stats = {'custom_ok': 0, 'custom_blocked': False,
         'axios_ok': 0, 'axios_blocked': False}

def quick_submit(label, channel, cs=0):
    sid = random.randint(0, 9999)
    now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    nt = now + ''.join(random.choices('0123456789ABCDEF', k=20))

    body = {'schema':{'model':{
        'title':{'value':f'计数器测试{label}{sid}'},
        'short_product_name':{'value':''},'title_prefix':{'value':''},'title_suffix':{'value':''},'title_use_brand_name':{'value':False},
        'goods_category':{'value':{'category_leaf_id':1000010267,'first_cid':1000003282,'first_cname':'A','second_cid':1000009114,'second_cname':'A','third_cid':1000009597,'third_cname':'A','fourth_cid':1000010267,'fourth_cname':'A'}},
        'category_properties':{'value':{'1687':[{'value_id':'596120136','value_name':'无品牌'}],'1577':[{'value_id':'1991','value_name':'通用'}],'1865':[{'value_id':'31904','value_name':'中筒袜'}],'785':[{'value_id':'','value_name':'棉100%','measure_info':{'template_id':873,'values':[{'module_id':1854,'value':'棉'},{'module_id':1855,'value':'100','unit_id':15,'unit_name':'%'}]}}]}},
        'category_property_pic':{'value':{}},'pic':{'value':[]},'main_image_three_to_four':{'value':[]},'white_background_pic':{'value':[]},'description':{'value':''},
        'spec_detail':{'value':[{'id':'10000','cp_id':2752,'name':'颜色分类','spec_values':[{'id':'996874532588296918','name':'默认','cpv_id':0,'cpv_path':[],'img_url':None}]},{'id':'20000','cp_id':3939,'name':'码数','spec_values':[{'id':'990897920130195435','name':'均码','cpv_id':0,'cpv_path':[],'img_url':None}]}]},
        'sku_detail':{'value':[{'id':f'ctr{sid}','stock_info':{'stock_num':100},'sku_status':True,'confirm_no_barcode':False,'spec_detail_ids':['996874532588296918','990897920130195435'],'price':'9.9'}]},
        'freight_id':{'value':'300713474'},'pickup_method':{'value':'0'},'start_sale_type':{'value':'0'},'product_type':{'value':'0'},'presell_type':{'value':'0'},'delivery_delay_day':{'value':'2'},'reduce_type':{'value':'1'},'qualification':{'value':{}},
        'after_sale':{'value':{'quality_problem_return':{'option_id':None,'selected':True},'supply_day_return_selector':{'option_id':'7-1','selected':True}}},
        'ai_gen_spec':{'value':{'ai_gen_spec_type':0}},'alli_promotion_plan_switch':{'value':False},'area_stock_switcher':{'value':False},'goods_category_appeal':{'value':False},'interest_free_activity':{'value':[]},'interest_free_activity_id':{'value':{}},'interest_free_open':{'value':True},'reference_price_enable':{'value':False},'detail_prettify_uri':{'value':''},
    },'context':{'ability':[],'biz_identity':'xiaodian','business_code':'xiaodian','capability_codes':['standard_capability'],'category_id':'1000010267','fast_publish_type':'','feature':{'session_publish_id':'helper_ctr','session_data':'{}','not_first_render':'1','product_sale_property_control':'1','sale_property_sequence_variable':'1','min_sku_price':'990'},'identity_extension':'{}','model_type':'','n_token':nt,'operation_type':'normal','product_id':'0','shop_id':shop_id,'token':nt,'version':'v1_v8_v9_v10_v11_v12'}},
    'category_id':'1000010267','context':{'ability':[],'biz_identity':'xiaodian','business_code':'xiaodian','capability_codes':['standard_capability'],'category_id':'1000010267','fast_publish_type':'','feature':{'session_publish_id':'helper_ctr','session_data':'{}','not_first_render':'1','product_sale_property_control':'1','sale_property_sequence_variable':'1','min_sku_price':'990'},'identity_extension':'{}','model_type':'','n_token':nt,'operation_type':'normal','product_id':'0','shop_id':shop_id,'token':nt,'version':'v1_v8_v9_v10_v11_v12'},
    'pass_through_extra':{},'request_extra':{},'check_status':cs,'session':{},'appid':1}

    body_json = json.dumps(body, ensure_ascii=False)
    r = cdp('Runtime.evaluate', {
        'expression': f'''
            (async function() {{
                var postFunc = window.__post_{channel};
                try {{
                    var result = await postFunc('/product/tproduct/addWithSchema?check_status={cs}', {body_json}, {{timeout: 30000}});
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
    return pid, blocked, msg

# ============================================================
# Phase 1: 只用 custom 通道, 每次间隔10秒, 推到极限
# ============================================================
print()
print('=== Phase 1: 只用 custom (90665.bE), 推到极限 ===')
print('(Starting from ~6 total submissions today)')

for i in range(1, 12):
    pid, blocked, msg = quick_submit(f'C{i}', 'custom')
    if pid:
        stats['custom_ok'] += 1
        print(f'  custom #{i}: OK pid={pid[:16]}')
    elif blocked:
        stats['custom_blocked'] = True
        print(f'  custom #{i}: BLOCKED! msg={msg[:60]}')
        break
    else:
        print(f'  custom #{i}: FAIL msg={msg[:60]}')
        break

    if i < 11:
        time.sleep(10)

print(f'\nCustom channel: {stats["custom_ok"]} OK, blocked={stats["custom_blocked"]}')

# ============================================================
# Phase 2: 立即切换到 axios 通道
# ============================================================
if stats['custom_blocked']:
    print()
    print('=== Phase 2: Custom已封, 立即切到 axios (28974.b) ===')
    for i in range(1, 5):
        pid, blocked, msg = quick_submit(f'A{i}', 'axios')
        if pid:
            stats['axios_ok'] += 1
            print(f'  axios #{i}: OK pid={pid[:16]}')
        elif blocked:
            stats['axios_blocked'] = True
            print(f'  axios #{i}: BLOCKED! msg={msg[:60]}')
            break
        else:
            print(f'  axios #{i}: FAIL msg={msg[:60]}')
            break
        time.sleep(5)

    print()
    print('='*60)
    print('RESULT:')
    if stats['axios_ok'] > 0 and stats['custom_blocked']:
        print(f'>>> INDEPENDENT COUNTERS! custom blocked but axios still works!')
    else:
        print(f'>>> SHARED COUNTER - both channels blocked')

print(f'custom: {stats["custom_ok"]}OK blocked={stats["custom_blocked"]}')
print(f'axios:  {stats["axios_ok"]}OK blocked={stats["axios_blocked"]}')

ws.close()

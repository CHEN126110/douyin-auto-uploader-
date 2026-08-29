# -*- coding: utf-8 -*-
"""混合方案: CDP模拟人类行为 + publishClickStat + 协议提交
测试: 完整的CDP交互信号是否能阻止反滥用计数
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
submit_count = [0]

def cdp(m, p=None, timeout=25):
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
cdp('Page.enable')
cdp('Input.enable')

# Navigate to create page
cdp('Page.navigate', {'url': 'https://fxg.jinritemai.com/ffa/g/create'})
time.sleep(5)

# Inject webpack
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) { window.__fxgWebpackRequire = req; }]);
            var req = window.__fxgWebpackRequire;
            window.__fxgPost = req(90665).bE;
            window.__fxgGet = req(28974).J;
            window.__shopId = '';
            try {
                var cookies = document.cookie.split(';');
                for (var i = 0; i < cookies.length; i++) {
                    var c = cookies[i].trim();
                    if (c.startsWith('ecom_gray_shop_id=')) window.__shopId = c.split('=')[1];
                }
            } catch(e) {}
            return JSON.stringify({shopId: window.__shopId});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
sess = json.loads(val) if isinstance(val, str) else (val or {})
shop_id = sess.get('shopId', '177886360')
print(f'shop_id={shop_id}')

def simulate_human_behavior():
    """模拟真人在页面上的操作序列"""
    # 1. 获取视口
    r = cdp('Runtime.evaluate', {
        'expression': 'JSON.stringify({w: window.innerWidth, h: window.innerHeight})',
        'returnByValue': True
    })
    val = ((r.get('result') or {}).get('result') or {}).get('value', '')
    vw = json.loads(val) if isinstance(val, str) else {'w': 1920, 'h': 1080}

    # 2. 鼠标移动到标题输入框区域 (通常在页面中部偏上)
    for i in range(3):
        x = random.randint(400, 800)
        y = random.randint(250, 350)
        cdp('Input.dispatchMouseEvent', {
            'type': 'mouseMoved', 'x': x, 'y': y,
            'modifiers': 0, 'button': 'none', 'buttons': 0,
        })
        time.sleep(0.1)

    # 3. 点击标题输入框 (模拟选中输入框)
    cdp('Input.dispatchMouseEvent', {
        'type': 'mousePressed', 'x': 550, 'y': 300,
        'button': 'left', 'clickCount': 1,
    })
    cdp('Input.dispatchMouseEvent', {
        'type': 'mouseReleased', 'x': 550, 'y': 300,
        'button': 'left', 'clickCount': 1,
    })
    time.sleep(0.2)

    # 4. 模拟键盘输入几个字符
    for char in "Test Title":
        cdp('Input.dispatchKeyEvent', {
            'type': 'keyDown', 'key': char, 'text': char,
        })
        cdp('Input.dispatchKeyEvent', {
            'type': 'keyUp', 'key': char,
        })
        time.sleep(random.uniform(0.03, 0.08))

    # 5. 鼠标移动到其他地方
    for i in range(2):
        x = random.randint(500, 800)
        y = random.randint(400, 600)
        cdp('Input.dispatchMouseEvent', {
            'type': 'mouseMoved', 'x': x, 'y': y,
            'modifiers': 0, 'button': 'none', 'buttons': 0,
        })
        time.sleep(0.1)

    # 6. 模拟滚轮
    cdp('Input.dispatchMouseEvent', {
        'type': 'mouseWheel', 'x': 600, 'y': 500,
        'deltaX': 0, 'deltaY': 100,
    })
    time.sleep(0.1)

def submit_hybrid(label, with_behavior=False):
    submit_count[0] += 1

    if with_behavior:
        print(f'  [{label}] Simulating human behavior...')
        simulate_human_behavior()
        time.sleep(0.5)

    # publishClickStat
    r = cdp('Runtime.evaluate', {
        'expression': '''
            (async function() {
                await window.__fxgGet('/product/tproduct/publishClickStat?check_status=2', {timeout: 5000});
                return 'ok';
            })()
        ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
    })

    # Build body and submit
    now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    nt = now + ''.join(random.choices('0123456789ABCDEF', k=20))
    body = {
        'schema':{'model':{
            'title':{'value':f'混合测试{label}{submit_count[0]}'},
            'short_product_name':{'value':''},'title_prefix':{'value':''},'title_suffix':{'value':''},'title_use_brand_name':{'value':False},
            'goods_category':{'value':{'category_leaf_id':1000010267,'first_cid':1000003282,'first_cname':'A'}},
            'category_properties':{'value':{'1687':[{'value_id':'596120136','value_name':'无品牌'}],'1577':[{'value_id':'1991','value_name':'通用'}],'1865':[{'value_id':'31904','value_name':'中筒袜'}],'785':[{'value_id':'','value_name':'棉100%','measure_info':{'template_id':873,'values':[{'module_id':1854,'value':'棉'},{'module_id':1855,'value':'100','unit_id':15,'unit_name':'%'}]}}]}},
            'category_property_pic':{'value':{}},'pic':{'value':[]},'main_image_three_to_four':{'value':[]},'white_background_pic':{'value':[]},'description':{'value':''},
            'spec_detail':{'value':[{'id':'10000','cp_id':2752,'name':'颜色分类','spec_values':[{'id':'996874532588296918','name':'默认','cpv_id':0,'cpv_path':[],'img_url':None}]},{'id':'20000','cp_id':3939,'name':'码数','spec_values':[{'id':'990897920130195435','name':'均码','cpv_id':0,'cpv_path':[],'img_url':None}]}]},
            'sku_detail':{'value':[{'id':f'hy{submit_count[0]}','stock_info':{'stock_num':100},'sku_status':True,'confirm_no_barcode':False,'spec_detail_ids':['996874532588296918','990897920130195435'],'price':'9.9'}]},
            'freight_id':{'value':'300713474'},'pickup_method':{'value':'0'},'start_sale_type':{'value':'0'},'product_type':{'value':'0'},'presell_type':{'value':'0'},'delivery_delay_day':{'value':'2'},'reduce_type':{'value':'1'},'qualification':{'value':{}},'after_sale':{'value':{'quality_problem_return':{'option_id':None,'selected':True},'supply_day_return_selector':{'option_id':'7-1','selected':True}}},'ai_gen_spec':{'value':{'ai_gen_spec_type':0}},'alli_promotion_plan_switch':{'value':False},'area_stock_switcher':{'value':False},'goods_category_appeal':{'value':False},'interest_free_activity':{'value':[]},'interest_free_activity_id':{'value':{}},'interest_free_open':{'value':True},'reference_price_enable':{'value':False},'detail_prettify_uri':{'value':''},
        },'context':{'ability':[],'biz_identity':'xiaodian','business_code':'xiaodian','capability_codes':['standard_capability'],'category_id':'1000010267','fast_publish_type':'','feature':{'session_publish_id':'helper_test','session_data':'{}','not_first_render':'1','product_sale_property_control':'1','sale_property_sequence_variable':'1','min_sku_price':'990'},'identity_extension':'{}','model_type':'','n_token':nt,'operation_type':'normal','product_id':'0','shop_id':shop_id,'token':nt,'version':'v1_v8_v9_v10_v11_v12'}},
        'category_id':'1000010267','context':{'ability':[],'biz_identity':'xiaodian','business_code':'xiaodian','capability_codes':['standard_capability'],'category_id':'1000010267','fast_publish_type':'','feature':{'session_publish_id':'helper_test','session_data':'{}','not_first_render':'1','product_sale_property_control':'1','sale_property_sequence_variable':'1','min_sku_price':'990'},'identity_extension':'{}','model_type':'','n_token':nt,'operation_type':'normal','product_id':'0','shop_id':shop_id,'token':nt,'version':'v1_v8_v9_v10_v11_v12'},
        'pass_through_extra':{},'request_extra':{},'check_status':0,'session':{},'appid':1,
    }
    body_json = json.dumps(body, ensure_ascii=False)
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
    pid = result.get('pid', '')
    msg = str(result.get('msg', ''))
    blocked = '非官方' in msg or '异常' in msg
    status = 'OK' if pid else ('BLOCKED' if blocked else 'FAIL')
    print(f'  [{label}] code={result.get("code")} pid={pid[:16] if pid else "-"} {status} msg={msg[:50]}')
    return pid, blocked

# ============================================================
# 实验: 交替测试 有行为模拟 vs 无行为模拟
# ============================================================
print()
print('=== Phase 1: 无行为模拟 (baseline) ===')
p1, b1 = submit_hybrid('NO_BEHAVIOR', with_behavior=False)
time.sleep(5)

print()
print('=== Phase 2: 有行为模拟 (CDP mouse/keyboard) ===')
p2, b2 = submit_hybrid('WITH_BEHAVIOR', with_behavior=True)
time.sleep(5)

print()
print('=== Phase 3: 有行为 (测试2) ===')
p3, b3 = submit_hybrid('BEHAVIOR2', with_behavior=True)
time.sleep(5)

print()
print('=== Phase 4: 无行为 (对照) ===')
p4, b4 = submit_hybrid('NO_BEHAVIOR2', with_behavior=False)

print()
ok_str = lambda p: 'OK' if p else 'BLOCKED'
print(f'Total: {submit_count[0]} submissions')
print(f'Results: B1={ok_str(p1)} B2={ok_str(p2)} B3={ok_str(p3)} B4={ok_str(p4)}')

ws.close()

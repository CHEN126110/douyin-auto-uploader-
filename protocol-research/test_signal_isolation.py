# -*- coding: utf-8 -*-
"""信号隔离实验: 逐个排除DOM vs 协议的差异
测试变量: session_publish_id 唯一性, n_token 格式, 请求间隔模式
"""
import json, time, datetime, random, uuid
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9222/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), targets[0])
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
ws.settimeout(3)
mid=[0]
def cdp(m,p=None):
    mid[0]+=1; ws.send(json.dumps({'id':mid[0],'method':m,'params':p or {}}))
    dl=time.time()+20
    while time.time()<dl:
        try: raw=ws.recv(); msg=json.loads(raw)
        except: continue
        if msg.get('id')==mid[0]: return msg
    return {}

cdp('Runtime.enable')
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var c = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            window[c].push([[Math.floor(Math.random() * 1e9)], {}, function(req) { window.__fxgWebpackRequire = req; }]);
            window.__fxgPost = window.__fxgWebpackRequire(90665).bE;
            window.__fxgGet = window.__fxgWebpackRequire(28974).J;
            window.__fxgPid = window.__fxgWebpackRequire(68671).T({useUrlParams:true,useWindowCache:true});
            return JSON.stringify({ok:true, pid: window.__fxgPid});
        })()
    ''', 'returnByValue': True, 'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
sess_data = json.loads(val) if isinstance(val, str) else (val or {})
publish_id = sess_data.get('pid','unknown')
print(f'publishId={publish_id[:20]}...')

# 记录每次提交的时间和session_publish_id
results = []

def quick_submit(label, **overrides):
    now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    # DOM流水线每次生成唯一的session_publish_id: helper_<uniquePublishId>
    spid = overrides.get('session_publish_id', f'helper_{publish_id}_{label}_{random.randint(1000,9999)}')
    nt = overrides.get('n_token', now + ''.join(random.choices('0123456789ABCDEF', k=20)))

    title = overrides.get('title', f'信号测试{label}{random.randint(10,99)}')

    body = {
        'schema':{'model':{
            'title':{'value':title},'short_product_name':{'value':''},'title_prefix':{'value':''},'title_suffix':{'value':''},'title_use_brand_name':{'value':False},
            'goods_category':{'value':{'category_leaf_id':1000010267,'first_cid':1000003282,'first_cname':'A'}},
            'category_properties':{'value':{'1687':[{'value_id':'596120136','value_name':'无品牌'}],'1577':[{'value_id':'1991','value_name':'通用'}],'1865':[{'value_id':'31904','value_name':'中筒袜'}],'785':[{'value_id':'','value_name':'棉100%','measure_info':{'template_id':873,'values':[{'module_id':1854,'value':'棉'},{'module_id':1855,'value':'100','unit_id':15,'unit_name':'%'}]}}]}},
            'category_property_pic':{'value':{}},'pic':{'value':[]},'main_image_three_to_four':{'value':[]},'white_background_pic':{'value':[]},'description':{'value':''},
            'spec_detail':{'value':[{'id':'10000','cp_id':2752,'name':'颜色分类','spec_values':[{'id':f'clr{random.randint(1000,9999)}','name':'默认','cpv_id':0,'cpv_path':[],'img_url':None}]},{'id':'20000','cp_id':3939,'name':'码数','spec_values':[{'id':f'sz{random.randint(1000,9999)}','name':'均码','cpv_id':0,'cpv_path':[],'img_url':None}]}]},
            'sku_detail':{'value':[{'id':f'sig-{random.randint(0,9999)}','stock_info':{'stock_num':random.randint(50,200)},'sku_status':True,'confirm_no_barcode':False,'spec_detail_ids':['clr0000','sz0000'],'price':f'{random.randint(8,15)}.{random.randint(0,99):02d}'}]},
            'freight_id':{'value':'300713474'},'pickup_method':{'value':'0'},'start_sale_type':{'value':'0'},'product_type':{'value':'0'},'presell_type':{'value':'0'},'delivery_delay_day':{'value':'2'},'reduce_type':{'value':'1'},'qualification':{'value':{}},'after_sale':{'value':{'quality_problem_return':{'option_id':None,'selected':True},'supply_day_return_selector':{'option_id':'7-1','selected':True}}},'ai_gen_spec':{'value':{'ai_gen_spec_type':0}},'alli_promotion_plan_switch':{'value':False},'area_stock_switcher':{'value':False},'goods_category_appeal':{'value':False},'interest_free_activity':{'value':[]},'interest_free_activity_id':{'value':{}},'interest_free_open':{'value':True},'reference_price_enable':{'value':False},'detail_prettify_uri':{'value':''},
        },'context':{'ability':[],'biz_identity':'xiaodian','business_code':'xiaodian','capability_codes':['standard_capability'],'category_id':'1000010267','fast_publish_type':'','feature':{'session_publish_id':spid,'session_data':'{}','not_first_render':'1','product_sale_property_control':'1','sale_property_sequence_variable':'1','min_sku_price':f'{random.randint(500,1500)}'},'identity_extension':'{}','model_type':'','n_token':nt,'operation_type':'normal','product_id':'0','shop_id':'155450371','token':nt,'version':'v1_v8_v9_v10_v11_v12'}},
        'category_id':'1000010267','context':{'ability':[],'biz_identity':'xiaodian','business_code':'xiaodian','capability_codes':['standard_capability'],'category_id':'1000010267','fast_publish_type':'','feature':{'session_publish_id':spid,'session_data':'{}','not_first_render':'1','product_sale_property_control':'1','sale_property_sequence_variable':'1','min_sku_price':f'{random.randint(500,1500)}'},'identity_extension':'{}','model_type':'','n_token':nt,'operation_type':'normal','product_id':'0','shop_id':'155450371','token':nt,'version':'v1_v8_v9_v10_v11_v12'},
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
    pid = result.get('pid','')
    msg = str(result.get('msg',''))
    blocked = '非官方' in msg or '异常' in msg
    status = 'BLOCKED' if blocked else ('OK' if pid else 'FAIL')
    print(f'  {label}: {status} pid={pid[:16] if pid else "-"} spid={spid[:30]}')
    return {'pid': pid, 'blocked': blocked, 'code': result.get('code',0)}

print()
print('=== 信号隔离实验 ===')
print('变量: 每次使用不同的 session_publish_id + 随机价格/库存/标题')
print('目标: 最大化多样性, 看看是否比固定数据撑更久')
print()

for i in range(1, 9):
    res = quick_submit(f'B{i}')
    results.append(res)
    if res['blocked']:
        print(f'>>> 第{i}次被封!')
        break
    time.sleep(5)

print()
print(f'成功: {sum(1 for r in results if r["pid"])} 次')
print(f'剩余安全额度(估算): {10 - len(results)} 次')

ws.close()

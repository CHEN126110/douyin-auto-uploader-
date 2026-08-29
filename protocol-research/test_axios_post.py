# -*- coding: utf-8 -*-
"""用页面自己的 axios POST (28974.b) 替代 90665.bE"""
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

TITLE = 'Axios通道测试中筒袜女款商品'

r = cdp('Runtime.evaluate', {
    'expression': f'''
        (async function() {{
            var chunkName = Object.keys(window).find(function(k) {{ return k.includes('@ecom-mcenter/ffa-goods'); }});
            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {{}}, function(req) {{ window.__fxgWebpackRequire = req; }}]);
            var req = window.__fxgWebpackRequire;

            var axiosPost = req(28974).b;

            var model = {{
                title:{{value:'{TITLE}'}},
                short_product_name:{{value:''}}, title_prefix:{{value:''}}, title_suffix:{{value:''}},
                title_use_brand_name:{{value:false}},
                goods_category:{{value:{{category_leaf_id:1000010267,first_cid:1000003282,first_cname:'A',second_cid:1000009114,second_cname:'A',third_cid:1000009597,third_cname:'A',fourth_cid:1000010267,fourth_cname:'A'}}}},
                category_properties:{{value:{{
                    '1687':[{{value_id:'596120136',value_name:'无品牌'}}],
                    '1577':[{{value_id:'1991',value_name:'通用'}}],
                    '1865':[{{value_id:'31904',value_name:'中筒袜'}}],
                    '785':[{{value_id:'',value_name:'棉100%',measure_info:{{template_id:873,values:[{{module_id:1854,value:'棉'}},{{module_id:1855,value:'100',unit_id:15,unit_name:'%'}}]}}}}]
                }}}},
                category_property_pic:{{value:{{}}}}, pic:{{value:[]}}, main_image_three_to_four:{{value:[]}},
                white_background_pic:{{value:[]}}, description:{{value:''}},
                spec_detail:{{value:[
                    {{id:'10000',cp_id:2752,name:'颜色分类',spec_values:[{{id:'996874532588296918',name:'默认',cpv_id:0,cpv_path:[],img_url:null}}]}},
                    {{id:'20000',cp_id:3939,name:'码数',spec_values:[{{id:'990897920130195435',name:'均码',cpv_id:0,cpv_path:[],img_url:null}}]}}
                ]}},
                sku_detail:{{value:[{{id:'axio-001',stock_info:{{stock_num:100}},sku_status:true,confirm_no_barcode:false,spec_detail_ids:['996874532588296918','990897920130195435'],price:'9.9'}}]}},
                freight_id:{{value:'300713474'}}, pickup_method:{{value:'0'}}, start_sale_type:{{value:'0'}},
                product_type:{{value:'0'}}, presell_type:{{value:'0'}}, delivery_delay_day:{{value:'2'}},
                reduce_type:{{value:'1'}}, qualification:{{value:{{}}}},
                after_sale:{{value:{{quality_problem_return:{{option_id:null,selected:true}},supply_day_return_selector:{{option_id:'7-1',selected:true}}}}}},
                ai_gen_spec:{{value:{{ai_gen_spec_type:0}}}}, alli_promotion_plan_switch:{{value:false}},
                area_stock_switcher:{{value:false}}, goods_category_appeal:{{value:false}},
                interest_free_activity:{{value:[]}}, interest_free_activity_id:{{value:{{}}}},
                interest_free_open:{{value:true}}, reference_price_enable:{{value:false}},
                detail_prettify_uri:{{value:''}},
            }};

            // Build full body like page does (same as module 51313.dc)
            var body = {{
                schema: {{model: model, context: {{}}}},
                category_id: '1000010267',
                context: {{
                    category_id: '1000010267',
                    operation_type: 'normal',
                    version: 'v1_v8_v9_v10_v11_v12'
                }},
                pass_through_extra: {{}},
                request_extra: {{}},
                check_status: 0,
                session: {{}},
                appid: 1,
            }};

            try {{
                var result = await axiosPost(
                    '/product/tproduct/addWithSchema?check_status=0',
                    body,
                    {{timeout: 30000}}
                );
                return JSON.stringify({{code: result.code || result.errno, msg: result.msg || '', pid: result.data ? (typeof result.data === 'string' ? JSON.parse(result.data).product_id : result.data.product_id) : null, channel: '28974.b/axios'}});
            }} catch(e) {{
                return JSON.stringify({{error: true, code: e.code || e.errno, msg: e.msg || e.message || String(e), channel: '28974.b/axios'}});
            }}
        }})()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 40000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
result = json.loads(val) if isinstance(val, str) else (val or {})
pid = result.get('pid', '')
msg = result.get('msg', '')
blocked = '非官方' in str(msg) or '异常' in str(msg)
print(f'code={result.get("code")} pid={pid}')
print(f'msg="{msg}"')
print(f'channel={result.get("channel","?")}')
if blocked:
    print('>>> STILL BLOCKED (even via axios)')
elif pid:
    print('>>> SUCCESS via axios! This is the key!')
else:
    print(f'>>> Validation: {msg}')

ws.close()

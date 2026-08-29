# -*- coding: utf-8 -*-
import json, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9333/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), targets[0])
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
mid=[0]
def cdp(m,p=None):
    mid[0]+=1; ws.send(json.dumps({'id':mid[0],'method':m,'params':p or {}}))
    dl=time.time()+40
    while time.time()<dl:
        raw=ws.recv();msg=json.loads(raw)
        if msg.get('id')==mid[0]: return msg
    return {}

cdp('Runtime.enable')

body = {
    "schema": {
        "title": "protocol-test-sock",
        "goods_category": {"category_leaf_id": 1000010267, "first_cid": 1000003282, "first_cname": "fu zhuang", "second_cid": 1000009114, "second_cname": "nei yi", "third_cid": 1000009597, "third_cname": "wa zi", "fourth_cid": 1000010267, "fourth_cname": "zhong tong"},
        "category_properties": {
            "1687": [{"diy_type":0,"measure_info":None,"tags":None,"value_id":"596120136","value_name":"shang pin ji"}],
            "1577": [{"diy_type":0,"measure_info":None,"tags":None,"value_id":"1991","value_name":"tong yong"}],
            "1865": [{"diy_type":0,"measure_info":None,"tags":None,"value_id":"31904","value_name":"zhong tong"}],
            "785": [{"value_id":"","value_name":"cotton","measure_info":{"template_id":873,"values":[{"module_id":1854,"value":"cotton"},{"module_id":1855,"value":"80","unit_id":15,"unit_name":"%"}]}}]
        },
        "pickup_method":"0","start_sale_type":"0","product_type":"0","presell_type":"0","freight_id":"300713474",
        "pic":[{"url":"https://p3-aio.ecombdimg.com/img/t.jpg"}],
        "main_image_three_to_four":[{"url":"https://p3-aio.ecombdimg.com/img/t2.jpg"}],
        "white_background_pic":[],"main_pic_video":[],"description":"","qualification":{},
        "spec_detail":[
            {"id":"10000","cp_id":2752,"name":"color","spec_values":[{"source_index":1,"id":"dry_10000_1","name":"white","img_url":None,"measure_info":None}]}
        ],
        "sku_detail":[
            {"id":"dry_sku_1","source_index":1,"spec_detail_ids":["dry_10000_1"],"sku_pic":[],"spec_names":{"color":"white"},"price":"12.90","stock":100}
        ]
    }
}

body_json = json.dumps(body, ensure_ascii=False)

r = cdp('Runtime.evaluate', {
    'expression': '''
        (async function() {
            try {
                var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
                if (!window.__fxgWebpackRequire) {
                    window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) {
                        window.__fxgWebpackRequire = req;
                    }]);
                }
                var post = window.__fxgWebpackRequire(90665).bE;

                // First, get publishId and test if getSchema works
                var req = window.__fxgWebpackRequire;
                var get = req(28974).J;
                var pid = req(68671).T({useUrlParams: true, useWindowCache: true});

                // Test getSchema works (confirms auth is valid)
                var schemaResult = null;
                try {
                    schemaResult = await post('/product/tproduct/getSchema', {context:{category_id:'1000010267',operation_type:'normal',ability:[],feature:{session_publish_id:'helper_'+pid}}}, {timeout:10000});
                } catch(e) {
                    schemaResult = {error: e.msg || String(e)};
                }

                // Test addWithSchema with publish_id in URL
                try {
                    var result = await post('/product/tproduct/addWithSchema?check_status=0', ''' + body_json + ''', {timeout: 30000});
                    return JSON.stringify({ok: true, schemaOk: !!(schemaResult && !schemaResult.error), addResult: {errno: result.errno, code: result.code, msg: result.msg}});
                } catch(err) {
                    return JSON.stringify({
                        schemaOk: !!(schemaResult && !schemaResult.error),
                        addErr: {errno: err.errno, code: err.code, msg: err.msg, st: err.st}
                    });
                }
            } catch(e) {
                return JSON.stringify({fatal: (e||{}).message || String(e)});
            }
        })()
    ''',
    'returnByValue': True,
    'awaitPromise': True,
    'timeout': 40000
})

val = ((r.get('result') or {}).get('result') or {}).get('value', '')
result = json.loads(val)
print(json.dumps(result, ensure_ascii=False, indent=2)[:2000])

ws.close()

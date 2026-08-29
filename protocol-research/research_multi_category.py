# -*- coding: utf-8 -*-
"""多类目 Schema 研究 — 通过 getSchema 拉取不同类目属性进行横向对比。
getSchema 是读操作，不受反滥用封锁影响。
"""
import json, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from urllib.request import urlopen
import websocket

targets = json.loads(urlopen('http://127.0.0.1:9222/json/list', timeout=3).read())
t = next((x for x in targets if 'jinritemai.com' in (x.get('url') or '')), targets[0])
ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
ws.settimeout(3)
mid = [0]

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

# 注入 webpack
r = cdp('Runtime.evaluate', {
    'expression': '''
        (function() {
            var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
            if (!chunkName) return JSON.stringify({error: 'chunk not found'});
            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) { window.__fxgWebpackRequire = req; }]);
            window.__fxgPost = window.__fxgWebpackRequire(90665).bE;
            return JSON.stringify({ok: true});
        })()
    ''', 'returnByValue': True, 'awaitPromise': True, 'timeout': 10000
})
val = ((r.get('result') or {}).get('result') or {}).get('value', '')
print(f'Webpack: {val[:60]}')

# ============================================================
# 类目列表 — 从文档和平台获取已知类目ID
# ============================================================
categories = {
    # 已验证的类目ID (从之前的真实发布获取)
    '中筒袜': 1000010267,
    # 其他类目 — 尝试获取
    'T恤': 1000011448,
    '连裤袜': 1000009602,
    '男T恤': 1000011640,
    '毛巾': 1000012760,
}

def get_schema_info(cat_id, cat_name):
    """获取类目Schema并提取关键信息"""
    r = cdp('Runtime.evaluate', {
        'expression': f'''
            (async function() {{
                var result = await window.__fxgPost('/product/tproduct/getSchema', {{
                    context: {{category_id: '{cat_id}', operation_type: 'normal', ability: [], feature: {{session_publish_id: 'research'}}}},
                    model: void 0
                }}, {{timeout: 10000}});
                return JSON.stringify(result);
            }})()
        ''',
        'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
    })
    val = ((r.get('result') or {}).get('result') or {}).get('value', '')
    if isinstance(val, str):
        schema = json.loads(val)
    else:
        schema = val or {}

    if schema.get('code') != 0 or not schema.get('data'):
        return {'name': cat_name, 'id': cat_id, 'error': schema.get('msg', 'unknown'), 'properties': []}

    try:
        items = schema['data']['model']['category_properties']['items']
    except (KeyError, TypeError):
        return {'name': cat_name, 'id': cat_id, 'error': 'no category_properties in response', 'properties': []}
    props = []
    required_count = 0
    for item in items:
        pid = item['id']
        label = item.get('label', '')
        req = item.get('required', False)
        opts = item.get('options', [])
        opt_count = len(opts)
        has_measure = any(o.get('measure_info') for o in opts) if opts else False

        if req:
            required_count += 1

        props.append({
            'id': pid, 'label': label, 'required': req,
            'option_count': opt_count, 'has_measure': has_measure,
            'first_options': [o.get('value_name', '') for o in opts[:3]],
            'first_value_ids': [str(o.get('value_id', '')) for o in opts[:3]],
        })

    return {
        'name': cat_name, 'id': cat_id,
        'total': len(props), 'required': required_count,
        'properties': props,
    }

# ============================================================
# 逐个拉取
# ============================================================
results = []
for name, cid in categories.items():
    print(f'  Fetching: {name} ({cid})...')
    info = get_schema_info(cid, name)
    err = info.get('error', '')
    if err:
        print(f'    ERROR: {err}')
    else:
        print(f'    {info["total"]} 属性, {info["required"]} 必填')
    results.append(info)
    time.sleep(0.5)  # 读操作也稍微间隔一下

# ============================================================
# 横线对比
# ============================================================
print('\n' + '=' * 80)
print('多类目横向对比')
print('=' * 80)

# 收集所有属性 ID 和标签
all_prop_ids = {}
for r in results:
    for p in r['properties']:
        pid = p['id']
        if pid not in all_prop_ids:
            all_prop_ids[pid] = {'label': p['label'], 'categories': {}}
        all_prop_ids[pid]['categories'][r['name']] = p['required']

# 高频必填属性 (出现在 ≥3 个类目且必填)
print('\n[高频必填属性]')
common_required = []
for pid, info in all_prop_ids.items():
    cats = info['categories']
    req_cats = [c for c, req in cats.items() if req]
    if len(req_cats) >= 2:
        common_required.append((pid, info['label'], req_cats, len(cats)))
common_required.sort(key=lambda x: -x[3])
for pid, label, req_cats, total in common_required:
    print(f'  id={pid} {label}: 必填于 {req_cats}, 出现在{total}个类目')

# 各类目特有属性
print('\n[各类目特有属性]')
all_cat_names = [r['name'] for r in results if not r.get('error')]
for r in results:
    if r.get('error'):
        continue
    own_props = []
    for p in r['properties']:
        pid = p['id']
        if len(all_prop_ids[pid]['categories']) == 1:
            own_props.append(f"{p['label']}({pid})")
    if own_props:
        print(f'  {r["name"]}: {own_props}')

# 每类目必填属性清单
print('\n[各类目必填属性]')
for r in results:
    if r.get('error'):
        continue
    req_props = [f"{p['label']}({p['id']})" for p in r['properties'] if p['required']]
    print(f'  {r["name"]} ({r["total"]}个/{r["required"]}必填): {req_props}')

# 保存原始数据
out = r'E:\Script Project\Dyin\beiufen\2.0\tmp_runtime_probe_live\multi_category_schemas.json'
with open(out, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f'\n完整数据: {out}')

ws.close()

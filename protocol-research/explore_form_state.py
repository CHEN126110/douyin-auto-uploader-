# -*- coding: utf-8 -*-
"""通过 DrissionPage run_cdp 探索表单状态注入 — 仅在流水线运行时可用"""
import json, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 这个脚本要从 DOM 流水线上下文中调用
# 使用 main_tab.run_cdp() 而非独立 CDP 连接

SKU_INJECTION_JS = '''
(async function() {
    var results = {};

    // 找到 DouXiaoerStore 实例
    var store = window.DouXiaoerStore;
    if (!store) { results.error = 'DouXiaoerStore not found'; return JSON.stringify(results); }

    // 获取 schemaForm
    var instance = store.instance || store;
    var sf = instance.schemaForm;
    if (!sf) {
        // 尝试从其他路径获取
        var fiberKey = Object.keys(document.getElementById('app')).find(function(k) { return k.startsWith('__react'); });
        results.fiberKey = fiberKey || 'none';
        results.error = 'schemaForm not found';
        return JSON.stringify(results);
    }

    results.sfExists = true;

    // 读取当前 spec_detail 和 sku_detail 状态
    try {
        var specNode = sf.n('spec_detail');
        var skuNode = sf.n('sku_detail');
        results.specValue = JSON.stringify(specNode.state.value).substring(0, 500);
        results.skuValue = JSON.stringify(skuNode.state.value).substring(0, 500);
    } catch(e) {
        results.readError = e.message;
    }

    // 列出 schemaForm 的所有子节点 (表单项)
    try {
        var nodes = sf.node ? sf.node() : null;
        if (nodes && nodes.state && nodes.state.children) {
            results.fieldNames = Object.keys(nodes.state.children).slice(0, 50);
        }
    } catch(e) {}

    return JSON.stringify(results);
})()
'''

# 注入 SKU 数据的 JS 模板
INJECT_SKU_JS = '''
(async function() {
    var store = window.DouXiaoerStore;
    var instance = store.instance || store;
    var sf = instance.schemaForm;

    // 注入 spec_detail
    var specData = %s;
    var specNode = sf.n('spec_detail');
    specNode.setState({value: specData}, 'protocol_inject');

    // 注入 sku_detail
    var skuData = %s;
    var skuNode = sf.n('sku_detail');
    skuNode.setState({value: skuData}, 'protocol_inject');

    // 触发页面更新
    if (specNode.emit) specNode.emit('change', specData);
    if (skuNode.emit) skuNode.emit('change', skuData);

    return JSON.stringify({injected: true, specCount: specData.length, skuCount: skuData.length});
})()
'''

def build_sku_injection(sku_list, price, stock=100):
    """构建 SKU 注入数据"""
    colors = list(set(s.get('name', '默认') for s in sku_list)) if sku_list else ['默认']

    spec_detail = [
        {
            'id': '10000', 'cp_id': 2752, 'name': '颜色分类',
            'spec_values': [
                {'id': str(996874532588296900 + i + 18), 'name': c, 'cpv_id': 0, 'cpv_path': [], 'img_url': None}
                for i, c in enumerate(colors)
            ]
        },
        {
            'id': '20000', 'cp_id': 3939, 'name': '码数',
            'spec_values': [{'id': '990897920130195435', 'name': '均码', 'cpv_id': 0, 'cpv_path': [], 'img_url': None}]
        },
        {'id': '30000', 'cp_id': 4706, 'name': '筒高长度', 'spec_values': []},
        {'id': '40000', 'cp_id': 93, 'name': '规格', 'spec_values': []},
    ]

    color_ids = [sv['id'] for sv in spec_detail[0]['spec_values']]
    size_id = spec_detail[1]['spec_values'][0]['id']

    import uuid
    sku_detail = []
    for i, color in enumerate(colors):
        sid = str(uuid.uuid4())[:8] + '-' + str(uuid.uuid4())[:6] + '-' + str(uuid.uuid4())[:12]
        sku_detail.append({
            'id': sid,
            'stock_info': {'stock_num': stock},
            'sku_status': True,
            'confirm_no_barcode': False,
            'spec_detail_ids': [color_ids[i] if i < len(color_ids) else color_ids[0], size_id],
            'price': str(price),
        })

    return json.dumps(spec_detail, ensure_ascii=False), json.dumps(sku_detail, ensure_ascii=False)


if __name__ == '__main__':
    # 示例: 3个颜色SKU, 价格12.9, 库存100
    sku_list = [{'name': '白色'}, {'name': '黑色'}, {'name': '灰色'}]
    spec_js, sku_js = build_sku_injection(sku_list, 12.9, 100)

    injection_code = INJECT_SKU_JS % (spec_js, sku_js)

    print('=== SKU 注入 JS 代码 ===')
    print(injection_code[:2000])
    print()
    print('用法: main_tab.run_cdp("Runtime.evaluate", {"expression": injection_code, "returnByValue": True, "awaitPromise": True})')

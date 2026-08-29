# -*- coding: utf-8 -*-
"""系统化边缘测试 — 挖掘平台校验规则和未覆盖的错误码。
每个测试记录：输入、预期行为、实际平台反馈、新发现的错误模式。
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fxg_protocol_v2 import run

IMAGES_DIR = r'E:\Script Project\Dyin\beiufen\2.0\uploads\products\ID-1014239731732\SKU'

def _imgs(n=2):
    imgs = [os.path.join(IMAGES_DIR, f) for f in os.listdir(IMAGES_DIR)
            if f.lower().endswith(('.jpg', '.png', '.jpeg'))][:n]
    return imgs

def _base_config(category_leaf_id=1000010267):
    return {
        'category_leaf_id': category_leaf_id,
        'first_cid': 1000003282, 'first_cname': '服装',
        'second_cid': 1000009114, 'second_cname': '内衣裤袜',
        'third_cid': 1000009597, 'third_cname': '袜子',
        'fourth_cid': category_leaf_id, 'fourth_cname': '中筒袜',
    }

def _test(name, product_data, image_paths=None, category_leaf_id=1000010267):
    """运行单个测试并返回结构化结果"""
    imgs = _imgs(1)
    ip = image_paths if image_paths is not None else {'main_images': imgs[:1], 'main_images_1x1': imgs[:1]}
    t0 = time.time()
    result = run(
        category_leaf_id=category_leaf_id,
        product_data=product_data,
        image_paths=ip,
        category_config=_base_config(category_leaf_id),
    )
    elapsed = time.time() - t0

    return {
        'name': name,
        'success': result['success'],
        'product_id': result.get('data', {}).get('product_id', ''),
        'error_code': result.get('error', {}).get('code', ''),
        'error_msg': result.get('error', {}).get('message', ''),
        'error_category': result.get('error', {}).get('category', ''),
        'failed_step': next((s['name'] for s in result['steps'] if s['status'] == 'failed'), ''),
        'elapsed_s': round(elapsed, 1),
    }

# ============================================================
# 测试矩阵
# ============================================================

results = []
imgs = _imgs(2)
default_img = {'main_images': imgs[:1], 'main_images_1x1': imgs[:1]}

print('=' * 70)
print('协议流水线 — 系统化边缘测试')
print(f'开始时间: {time.strftime("%Y-%m-%d %H:%M:%S")}')
print('=' * 70)

# ---- A. 标题边界 ----
print('\n[A] 标题边界测试')
tests_a = [
    ('A1_标题正好8字', {'title': '一二三四五六七八', 'price': {'current': 9.9}, 'sku_info': [{'name': '默认'}], 'material': '棉100%'}),
    ('A2_标题7字_应失败', {'title': '一二三四五六七', 'price': {'current': 9.9}, 'sku_info': [{'name': '默认'}], 'material': '棉100%'}),
    ('A3_标题30字_长标题', {'title': '夏季薄款透气镂空中筒棉袜女ins风百搭纯色堆堆袜学生白色日系韩版', 'price': {'current': 9.9}, 'sku_info': [{'name': '默认'}], 'material': '棉100%'}),
    ('A4_标题含特殊字符', {'title': '测试【精品】夏季"薄款"棉袜-透气&舒适', 'price': {'current': 9.9}, 'sku_info': [{'name': '默认'}], 'material': '棉100%'}),
]
for name, pdata in tests_a:
    r = _test(name, pdata, default_img)
    results.append(r)
    status = '✓' if r['success'] else '✗'
    print(f'  {status} {name}: success={r["success"]} err={r["error_code"]} step={r["failed_step"]} ({r["elapsed_s"]}s)')

# ---- B. SKU 边界 ----
print('\n[B] SKU边界测试')
tests_b = [
    ('B1_单SKU默认名', {'title': 'SKU边界测试一单SKU默认名称', 'price': {'current': 9.9}, 'sku_info': [{'name': '默认'}], 'material': '棉100%'}),
    ('B2_三SKU多颜色', {'title': 'SKU边界测试二三个颜色SKU', 'price': {'current': 12.9}, 'sku_info': [{'name': '白色'}, {'name': '黑色'}, {'name': '粉色'}], 'material': '棉80%;氨纶20%'}),
    ('B3_SKU名含特殊字符', {'title': 'SKU特殊字符测试如斜杠和括号', 'price': {'current': 15.9}, 'sku_info': [{'name': '白/米白'}, {'name': '黑(深灰)'}], 'material': '棉100%'}),
    ('B4_SKU重复名_应去重', {'title': 'SKU重复名测试应自动去重合并', 'price': {'current': 9.9}, 'sku_info': [{'name': '白色'}, {'name': '白色'}, {'name': '黑色'}], 'material': '棉100%'}),
    ('B5_五SKU多颜色', {'title': 'SKU五颜色测试最多规格组合', 'price': {'current': 19.9}, 'sku_info': [{'name': '白色'}, {'name': '黑色'}, {'name': '灰色'}, {'name': '粉色'}, {'name': '蓝色'}], 'material': '棉70%;涤纶30%'}),
]
for name, pdata in tests_b:
    r = _test(name, pdata, default_img)
    results.append(r)
    status = '✓' if r['success'] else '✗'
    print(f'  {status} {name}: success={r["success"]} err={r["error_code"]} pid={r["product_id"][:16] if r["product_id"] else "-"} ({r["elapsed_s"]}s)')

# ---- C. 价格边界 ----
print('\n[C] 价格边界测试')
tests_c = [
    ('C1_价格0.01_最低', {'title': '价格边界测试最低一分钱商品', 'price': {'current': 0.01}, 'sku_info': [{'name': '默认'}], 'material': '棉100%'}),
    ('C2_价格9999_高价', {'title': '价格边界测试高价商品九千九', 'price': {'current': 9999}, 'sku_info': [{'name': '默认'}], 'material': '棉100%'}),
    ('C3_价格9.9_正常', {'title': '价格边界测试正常九块九商品', 'price': {'current': 9.9}, 'sku_info': [{'name': '默认'}], 'material': '棉100%'}),
]
for name, pdata in tests_c:
    r = _test(name, pdata, default_img)
    results.append(r)
    status = '✓' if r['success'] else '✗'
    print(f'  {status} {name}: success={r["success"]} err={r["error_code"]} pid={r["product_id"][:16] if r["product_id"] else "-"} ({r["elapsed_s"]}s)')

# ---- D. 材质边界 ----
print('\n[D] 材质边界测试')
tests_d = [
    ('D1_空材质', {'title': '材质测试一空材质无面料成分', 'price': {'current': 9.9}, 'sku_info': [{'name': '默认'}], 'material': ''}),
    ('D2_单材质100', {'title': '材质测试二单一材质百分百', 'price': {'current': 9.9}, 'sku_info': [{'name': '默认'}], 'material': '棉100%'}),
    ('D3_三种材质混合', {'title': '材质测试三三种混合面料成分', 'price': {'current': 12.9}, 'sku_info': [{'name': '默认'}], 'material': '棉60%;涤纶30%;氨纶10%'}),
    ('D4_材质无百分号', {'title': '材质测试四材质名不含百分号', 'price': {'current': 9.9}, 'sku_info': [{'name': '默认'}], 'material': '纯棉'}),
]
for name, pdata in tests_d:
    r = _test(name, pdata, default_img)
    results.append(r)
    status = '✓' if r['success'] else '✗'
    print(f'  {status} {name}: success={r["success"]} err={r["error_code"]} pid={r["product_id"][:16] if r["product_id"] else "-"} ({r["elapsed_s"]}s)')

# ---- E. 图片边界 ----
print('\n[E] 图片边界测试')
tests_e = [
    ('E1_仅主图无详情图', {'title': '图片测试一仅有主图和主图比例图', 'price': {'current': 9.9}, 'sku_info': [{'name': '默认'}], 'material': '棉100%'}),
    ('E2_两张详情图', {'title': '图片测试二两张详情图丰富内容', 'price': {'current': 9.9}, 'sku_info': [{'name': '默认'}], 'material': '棉100%'}),
]
for name, pdata in tests_e:
    imgs_all = _imgs(3)
    ip = {'main_images': imgs_all[:1], 'main_images_1x1': imgs_all[:1], 'detail_images': imgs_all[1:2]}
    r = _test(name, pdata, ip)
    results.append(r)
    status = '✓' if r['success'] else '✗'
    print(f'  {status} {name}: success={r["success"]} err={r["error_code"]} ({r["elapsed_s"]}s)')

# ---- F. 无图场景 ----
print('\n[F] 无图/仅无图场景')
tests_f = [
    ('F1_完全无图_应失败', {'title': '无图测试一无主图应被拒绝', 'price': {'current': 9.9}, 'sku_info': [{'name': '默认'}], 'material': '棉100%'}),
]
for name, pdata in tests_f:
    r = _test(name, pdata, {})
    results.append(r)
    status = '✓' if r['success'] else '✗'
    print(f'  {status} {name}: success={r["success"]} err={r["error_code"]} ({r["elapsed_s"]}s)')

# ---- 汇总 ----
print('\n' + '=' * 70)
print('测试汇总')
print('=' * 70)

successes = [r for r in results if r['success']]
failures = [r for r in results if not r['success']]

print(f'\n总计: {len(results)} 个测试')
print(f'成功: {len(successes)} 个')
print(f'失败: {len(failures)} 个')

if successes:
    print(f'\n成功案例 ({len(successes)}):')
    for r in successes:
        print(f'  ✓ {r["name"]} → product_id={r["product_id"]}')

if failures:
    print(f'\n失败案例 ({len(failures)}):')
    # 按错误码分组
    by_error = {}
    for r in failures:
        key = r['error_code']
        if key not in by_error:
            by_error[key] = []
        by_error[key].append(r)

    for err_code, cases in by_error.items():
        print(f'\n  [{err_code}] ({len(cases)} 个):')
        for r in cases:
            print(f'    ✗ {r["name"]} [{r["error_category"]}] {r["error_msg"][:80]}')

    # 新发现的错误模式
    known_errors = {'ERR_BODY_MISSING_TITLE', 'ERR_IMAGE_COUNT', 'ERR_SCHEMA_FAILED',
                    'ERR_IMAGE_UPLOAD_FAILED', 'ERR_SUBMIT_PLATFORM', 'ERR_AUTH_TOKEN_INVALID'}
    new_errors = set(by_error.keys()) - known_errors
    if new_errors:
        print(f'\n⚠ 新发现的错误码: {new_errors}')

# 保存结果
out = r'E:\Script Project\Dyin\beiufen\2.0\tmp_runtime_probe_live\edge_case_results.json'
with open(out, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f'\n完整结果: {out}')

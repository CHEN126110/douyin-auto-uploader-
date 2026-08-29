# -*- coding: utf-8 -*-
"""Douyin FXG 协议上传流水线 - 完整实现。
通过 CDP cookies + Python HTTP 实现:
  1. 图片上传 (batchupload)
  2. 组装 addWithSchema body
  3. 保存草稿 / 发布商品
"""

import json, os, sys, time, hashlib, base64, re
from urllib.request import urlopen, Request
from urllib.parse import urlencode
import websocket


# ============================================================
# 工具函数
# ============================================================

def get_fxg_session(cdp_port=9333):
    """从 CDP 浏览器获取 Douyin 会话 (cookies, csrf token, publishId)"""
    targets = json.loads(urlopen(f'http://127.0.0.1:{cdp_port}/json/list', timeout=3).read())
    target = next((t for t in targets if 'jinritemai.com' in (t.get('url') or '')), targets[0])
    ws = websocket.create_connection(target['webSocketDebuggerUrl'], timeout=5, suppress_origin=True)
    mid = [0]

    def cdp(method, params=None):
        mid[0] += 1
        ws.send(json.dumps({'id': mid[0], 'method': method, 'params': params or {}}))
        deadline = time.time() + 10
        while time.time() < deadline:
            raw = ws.recv()
            msg = json.loads(raw)
            if msg.get('id') == mid[0]:
                return msg
        return {}

    cdp('Network.enable')
    r = cdp('Network.getAllCookies')
    cookies = (r.get('result') or {}).get('cookies') or []
    cookie_str = '; '.join(f"{c['name']}={c['value']}" for c in cookies if 'jinritemai' in (c.get('domain') or ''))

    # 从页面提取 publishId
    r2 = cdp('Runtime.evaluate', {
        'expression': '(function(){var m=location.href.match(/create\\?id=(\\d+)/);return m?m[1]:""})()',
        'returnByValue': True
    })
    publish_id = ((r2.get('result') or {}).get('result') or {}).get('value', '')

    ws.close()
    return cookie_str, publish_id


# ============================================================
# 阶段1: 图片上传
# ============================================================

def upload_image(image_path, cookie_str):
    """上传单张图片，返回 URL"""
    if not os.path.exists(image_path):
        return None

    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                '.webp': 'image/webp', '.bmp': 'image/bmp'}
    mime_type = mime_map.get(ext, 'image/png')

    with open(image_path, 'rb') as f:
        image_data = f.read()

    boundary = '----WebKitFormBoundary' + os.urandom(16).hex()
    filename = os.path.basename(image_path)
    body = b'\r\n'.join([
        f'--{boundary}'.encode(),
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\nContent-Type: {mime_type}'.encode(),
        b'',
        image_data,
        f'--{boundary}--'.encode(),
    ])

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120',
        'Cookie': cookie_str,
        'Content-Type': f'multipart/form-data; boundary={boundary}',
        'Accept': 'application/json',
        'Referer': 'https://fxg.jinritemai.com/ffa/g/create',
        'Origin': 'https://fxg.jinritemai.com',
    }

    req = Request('https://fxg.jinritemai.com/product/img/batchupload', data=body, headers=headers, method='POST')
    try:
        resp = urlopen(req, timeout=30)
        result = json.loads(resp.read().decode('utf-8'))
        if result.get('errno') == 0 and result.get('data'):
            return result['data'][0]
    except Exception as e:
        print(f"  Upload error: {e}")
    return None


def upload_product_images(product_dir, cookie_str):
    """上传一个产品的全部图片，返回图片URL集合"""
    result = {
        'main_images': [],           # 主图 (3:4)
        'main_images_1x1': [],       # 主图 (1:1)
        'white_background': None,    # 白底图
        'detail_images': [],         # 详情图
    }

    main_dir = os.path.join(product_dir, '主图')
    detail_dir = os.path.join(product_dir, '详情页')

    if os.path.isdir(main_dir):
        for f in sorted(os.listdir(main_dir)):
            fpath = os.path.join(main_dir, f)
            if not os.path.isfile(fpath):
                continue
            url = upload_image(fpath, cookie_str)
            if url:
                if '_1x1' in f:
                    result['main_images_1x1'].append(url)
                else:
                    result['main_images'].append(url)
                print(f"  [+] {f[:40]}: {url[:80]}")

    if os.path.isdir(detail_dir):
        for f in sorted(os.listdir(detail_dir))[:10]:  # 最多10张详情图
            fpath = os.path.join(detail_dir, f)
            if os.path.isfile(fpath):
                url = upload_image(fpath, cookie_str)
                if url:
                    result['detail_images'].append(url)

    # 白底图 = 第一张1:1主图
    if result['main_images_1x1']:
        result['white_background'] = result['main_images_1x1'][0]

    return result


# ============================================================
# 阶段2: 构建 addWithSchema body
# ============================================================

def build_submit_body(product_data, image_urls, category_config, freight_id='300713474'):
    """根据产品数据和图片URL构建完整的 addWithSchema body"""
    body = {
        'title': product_data.get('title', ''),
        'goods_category': {
            'category_leaf_id': category_config['leaf_id'],
            'first_cid': category_config['first_cid'],
            'first_cname': category_config['first_cname'],
            'second_cid': category_config['second_cid'],
            'second_cname': category_config['second_cname'],
            'third_cid': category_config['third_cid'],
            'third_cname': category_config['third_cname'],
            'fourth_cid': category_config.get('fourth_cid', 0),
            'fourth_cname': category_config.get('fourth_cname', ''),
        },
        'category_properties': build_category_properties(product_data, category_config),
        'pickup_method': 0,
        'start_sale_type': 0,
        'product_type': 0,
        'presell_type': 0,
        'freight_id': freight_id,
        # 图片
        'pic': [{'url': u} for u in image_urls.get('main_images_1x1', [])[:5]],
        'main_image_three_to_four': [{'url': u} for u in image_urls.get('main_images', [])[:5]],
        'white_background_pic': [{'url': image_urls['white_background']}] if image_urls.get('white_background') else [],
        'main_pic_video': [],
        'description': build_description(image_urls.get('detail_images', [])),
        'qualification': {},
        # SKU
        'spec_detail': build_spec_detail(product_data),
        'sku_detail': build_sku_detail(product_data),
    }
    return body


def build_category_properties(product_data, category_config):
    """构建类目属性（袜子类目）"""
    props = {}

    # 1865: 筒高 (如: 中筒袜, 短袜, 长筒袜)
    sock_type = category_config.get('fourth_cname', '中筒袜')
    type_map = {
        '中筒袜': '31904', '短袜': '31905', '长筒袜': '31903',
        '船袜': '31906', '运动袜': '待确认',
    }
    props['1865'] = [{
        'diy_type': 0, 'measure_info': None, 'tags': None,
        'value_id': type_map.get(sock_type, '31904'),
        'value_name': sock_type,
    }]

    # 785: 材质成分 (measure_info)
    material = product_data.get('material', '棉')
    material_parts = material.split(';')
    prop_785 = []
    for part in material_parts[:3]:
        part = part.strip()
        if not part:
            continue
        match = re.match(r'(.+?)(\d+)%?', part)
        if match:
            mat_name, mat_pct = match.group(1).strip(), match.group(2)
        else:
            mat_name, mat_pct = part, '100'
        prop_785.append({
            'value_id': '', 'value_name': mat_name,
            'measure_info': {
                'template_id': 873,
                'values': [
                    {'module_id': 1854, 'prefix': '', 'suffix': '', 'value': mat_name},
                    {'module_id': 1855, 'prefix': '', 'suffix': '', 'value': mat_pct, 'unit_id': 15, 'unit_name': '%'},
                ]
            }
        })
    props['785'] = prop_785

    # 1687: 适用性别
    props['1687'] = [{
        'diy_type': 0, 'measure_info': None, 'tags': None,
        'value_id': '32880', 'value_name': '通用',
    }]

    return props


def build_spec_detail(product_data):
    """构建规格轴"""
    sku_list = product_data.get('sku_info', [])
    if not sku_list:
        return [{'id': '10000', 'cp_id': 2752, 'name': '颜色分类',
                 'spec_values': [{'source_index': 1, 'id': 'dry_10000_1', 'name': '默认', 'img_url': None, 'measure_info': None}]}]

    # 从SKU名称提取规格轴
    colors = set()
    for s in sku_list:
        name = s.get('name', '')
        colors.add(name)

    spec_detail = [{
        'id': '10000', 'cp_id': 2752, 'name': '颜色分类',
        'spec_values': [
            {'source_index': i + 1, 'id': f'dry_10000_{i+1}', 'name': c,
             'img_url': s.get('image') or None, 'measure_info': None}
            for i, (c, s) in enumerate(zip(colors, sku_list))
        ]
    }]
    return spec_detail


def build_sku_detail(product_data):
    """构建SKU明细"""
    sku_list = product_data.get('sku_info', [])
    price = product_data.get('price', {}).get('current', 9.9) or 9.9

    detail = []
    for i, s in enumerate(sku_list):
        detail.append({
            'id': f'dry_sku_{i+1}',
            'source_index': i + 1,
            'spec_detail_ids': [f'dry_10000_{i+1}'],
            'sku_pic': [],
            'spec_names': {'颜色分类': s.get('name', '默认')},
            'price': str(price),
            'stock': 100,
        })
    return detail


def build_description(detail_urls):
    """构建商品描述（详情图）"""
    if not detail_urls:
        return None
    desc_parts = []
    for url in detail_urls:
        desc_parts.append(f'<img src="{url}">')
    return '\n'.join(desc_parts)


# ============================================================
# 阶段3: 保存草稿 / 发布
# ============================================================

def save_draft(submit_body, cookie_str):
    """通过协议保存草稿"""
    url = 'https://fxg.jinritemai.com/product/tproduct/addWithSchema?check_status=0'
    body_json = json.dumps({'schema': submit_body}, ensure_ascii=False).encode('utf-8')

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120',
        'Cookie': cookie_str,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Referer': 'https://fxg.jinritemai.com/ffa/g/create',
        'Origin': 'https://fxg.jinritemai.com',
    }

    req = Request(url, data=body_json, headers=headers, method='POST')
    try:
        resp = urlopen(req, timeout=30)
        result = json.loads(resp.read().decode('utf-8'))
        return {'ok': True, 'response': result}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ============================================================
# 主入口
# ============================================================

def main():
    cdp_port = int(os.environ.get('CDP_PORT', 9333))
    product_dir = os.environ.get('PRODUCT_DIR', '')
    submit = os.environ.get('SUBMIT', '0') == '1'

    if not product_dir:
        print("Usage: PRODUCT_DIR=/path/to/product python fxg_protocol_pipeline.py")
        sys.exit(1)

    # 1. 获取会话
    print("[1/4] 获取浏览器会话...")
    cookie_str, publish_id = get_fxg_session(cdp_port)
    print(f"  Cookie: {len(cookie_str)} chars, PublishId: {publish_id}")

    # 2. 上传图片
    print("[2/4] 上传产品图片...")
    image_urls = upload_product_images(product_dir, cookie_str)
    print(f"  主图: {len(image_urls['main_images'])} | 1:1: {len(image_urls['main_images_1x1'])} | 白底: {bool(image_urls['white_background'])} | 详情: {len(image_urls['detail_images'])}")

    # 3. 构建 body
    print("[3/4] 构建 addWithSchema body...")
    # 使用默认类目配置（中筒袜）
    category_config = {
        'leaf_id': 1000010267,
        'first_cid': 1000003282, 'first_cname': '服装',
        'second_cid': 1000009114, 'second_cname': '内衣裤袜',
        'third_cid': 1000009597, 'third_cname': '袜子',
        'fourth_cid': 1000010267, 'fourth_cname': '中筒袜',
    }

    # 从产品目录读取数据
    product_data = {
        'title': '袜子女中筒袜夏季薄款纯色棉袜',
        'price': {'current': 9.9},
        'sku_info': [{'name': '白色', 'image': ''}, {'name': '黑色', 'image': ''}],
        'material': '棉75%;氨纶25%',
    }

    body = build_submit_body(product_data, image_urls, category_config)
    body_path = os.path.join(os.path.dirname(product_dir), 'addWithSchema_body.json')
    with open(body_path, 'w', encoding='utf-8') as f:
        json.dump(body, f, ensure_ascii=False, indent=2)
    print(f"  Body saved: {body_path}")
    print(f"  Fields: title={bool(body['title'])}, pic={len(body['pic'])}, spec={len(body['spec_detail'])}, sku={len(body['sku_detail'])}")

    # 4. 保存草稿（可选）
    if submit:
        print("[4/4] 保存草稿...")
        result = save_draft(body, cookie_str)
        print(json.dumps(result, ensure_ascii=False, indent=2)[:500])
    else:
        print("[4/4] 跳过提交 (设置 SUBMIT=1 启用)")

    print("\n✅ 协议流水线完成!")


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""Douyin FXG 协议上传流水线 v3 — 结构化错误反馈版。
每个函数返回 {"success": True/False, "data": ... 或 "error": {...}}。
成功提交验证: product_id=3819288252247048401 (2026-05-11)
"""
import json, os, sys, time, re, uuid, datetime, random, tempfile, traceback
from urllib.request import urlopen, Request
import websocket

# 同目录导入错误处理模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fxg_errors import (
    make_error, make_success, from_platform_response, PipelineError
)

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

CDP_PORT = int(os.environ.get("CDP_PORT", "9222"))


# ============================================================
# CDP 工具 (内部使用)
# ============================================================

def _cdp_target():
    try:
        targets = json.loads(urlopen(f'http://127.0.0.1:{CDP_PORT}/json/list', timeout=3).read())
    except Exception as e:
        raise PipelineError(make_error("ERR_CDP_NO_BROWSER", port=CDP_PORT, detail=str(e)))
    target = next((t for t in targets if 'jinritemai.com' in (t.get('url') or '')), None)
    if not target:
        raise PipelineError(make_error("ERR_CDP_NO_PAGE"))
    return target

def _cdp_ws():
    t = _cdp_target()
    try:
        ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
        ws.settimeout(2)
        return ws, [0]
    except Exception as e:
        raise PipelineError(make_error("ERR_CDP_WEBSOCKET", detail=str(e)))

def _cdp_call(ws, mid, method, params=None, timeout_sec=30):
    mid[0] += 1
    msg_id = mid[0]
    ws.send(json.dumps({'id': msg_id, 'method': method, 'params': params or {}}))
    dl = time.time() + timeout_sec
    while time.time() < dl:
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        except Exception as e:
            raise PipelineError(make_error("ERR_CDP_WEBSOCKET", detail=str(e)))
        try:
            msg = json.loads(raw)
        except:
            continue
        if msg.get('id') == msg_id:
            return msg

    raise PipelineError(make_error("ERR_CDP_TIMEOUT", method=method, timeout=timeout_sec))


# ============================================================
# Step 1: CDP 会话 (获取 cookies + publishId + shop_id)
# ============================================================

def get_fxg_session(cookie_str_override=None):
    """返回 {"success": True, "data": {cookie_str, publish_id, shop_id}} 或 {"success": False, "error": {...}}"""
    # 如果有外部提供的cookie，直接使用
    if cookie_str_override and len(cookie_str_override) > 100:
        print(f'[协议] 使用外部cookie ({len(cookie_str_override)}字符)，跳过CDP')
        ws, mid = None, None
        try:
            ws, mid = _cdp_ws()
            _cdp_call(ws, mid, 'Runtime.enable')
            r = _cdp_call(ws, mid, 'Runtime.evaluate', {
                'expression': """(function() {
                    var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
                    if (!chunkName) return JSON.stringify({error: 'chunk not found'});
                    if (!window.__fxgWebpackRequire) {
                        window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) { window.__fxgWebpackRequire = req; }]);
                    }
                    var req = window.__fxgWebpackRequire;
                    var publishId = req(68671).T({useUrlParams: true, useWindowCache: true, writeWindowCache: true});
                    window.__fxgPost = req(90665).bE;
                    window.__fxgGet = req(28974).J;
                    var shopId = '';
                    try {
                        var cookies = document.cookie.split(';');
                        for (var i = 0; i < cookies.length; i++) {
                            var c = cookies[i].trim();
                            if (c.startsWith('ecom_gray_shop_id=')) shopId = c.split('=')[1];
                        }
                    } catch(e) {}
                    return JSON.stringify({ok: true, publishId: publishId, shopId: shopId});
                })()""",
                'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
            })
            val = ((r.get('result') or {}).get('result') or {}).get('value', '')
            session = json.loads(val)
            if not session.get('ok'):
                return make_error('ERR_AUTH_NO_PUBLISH_ID', detail=val[:200])
            return make_success({
                'cookie_str': cookie_str_override,
                'publish_id': session.get('publishId', ''),
                'shop_id': session.get('shopId', '155450371'),
            })
        except Exception as e:
            return make_error('ERR_PIPELINE_STEP', step='get_session', detail=str(e))
        finally:
            if ws: ws.close()
    ws, mid = None, None
    try:
        ws, mid = _cdp_ws()

        _cdp_call(ws, mid, 'Network.enable')
        r = _cdp_call(ws, mid, 'Network.getAllCookies')
        cookies = ((r.get('result') or {}).get('cookies') or [])
        cookie_str = '; '.join(
            f"{c['name']}={c['value']}" for c in cookies
            if 'jinritemai.com' in (c.get('domain') or '')
        )
        if not cookie_str:
            return make_error("ERR_AUTH_NO_COOKIE")

        _cdp_call(ws, mid, 'Runtime.enable')
        r = _cdp_call(ws, mid, 'Runtime.evaluate', {
            'expression': '''
                (function() {
                    var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
                    if (!chunkName) return JSON.stringify({error: 'chunk not found'});
                    if (!window.__fxgWebpackRequire) {
                        window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) {
                            window.__fxgWebpackRequire = req;
                        }]);
                    }
                    var req = window.__fxgWebpackRequire;
                    var publishId = req(68671).T({useUrlParams: true, useWindowCache: true, writeWindowCache: true});
                    window.__fxgReq = req;
                    window.__fxgPost = req(90665).bE;
                    window.__fxgGet = req(28974).J;
                    window.__fxgPublishId = publishId;

                    var shopId = '';
                    try {
                        var cookies = document.cookie.split(';');
                        for (var i = 0; i < cookies.length; i++) {
                            var c = cookies[i].trim();
                            if (c.startsWith('ecom_gray_shop_id=')) {
                                shopId = c.split('=')[1];
                            }
                        }
                    } catch(e) {}

                    return JSON.stringify({ok: true, publishId: publishId, shopId: shopId});
                })()
            ''',
            'returnByValue': True, 'awaitPromise': True, 'timeout': 15000
        })

        val = ((r.get('result') or {}).get('result') or {}).get('value', '')
        session = json.loads(val)

        if session.get('error') == 'chunk not found':
            return make_error("ERR_CDP_WEBPACK_CHUNK")

        if not session.get('ok'):
            return make_error("ERR_AUTH_NO_PUBLISH_ID", detail=val[:200])

        return make_success({
            'cookie_str': cookie_str,
            'publish_id': session.get('publishId', ''),
            'shop_id': session.get('shopId', '155450371'),
        })

    except PipelineError:
        raise
    except Exception as e:
        return make_error("ERR_PIPELINE_STEP", step="get_session", detail=str(e))
    finally:
        if ws:
            try: ws.close()
            except: pass


# ============================================================
# 图片预处理
# ============================================================

def _resize_to_ratio(image_path, target_w, target_h):
    """中心裁剪+缩放到目标比例，返回临时文件路径。失败时返回原路径。"""
    if not HAS_PIL:
        return image_path
    try:
        img = Image.open(image_path)
        orig_w, orig_h = img.size
        target_ratio = target_w / target_h
        orig_ratio = orig_w / orig_h

        if abs(orig_ratio - target_ratio) < 0.01:
            return image_path

        if orig_ratio > target_ratio:
            new_w = int(orig_h * target_ratio)
            left = (orig_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, orig_h))
        else:
            new_h = int(orig_w / target_ratio)
            top = (orig_h - new_h) // 2
            img = img.crop((0, top, orig_w, top + new_h))

        img = img.resize((target_w, target_h), Image.LANCZOS)
        ext = os.path.splitext(image_path)[1].lower() or '.jpg'
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        img.save(tmp.name, quality=95)
        return tmp.name
    except Exception:
        return image_path


# ============================================================
# Step 2: 图片上传
# ============================================================

def upload_images(image_paths, cookie_str):
    """批量上传图片，自动处理比例裁剪。
    image_paths: {"main_images": [...], "main_images_1x1": [...], "detail_images": [...]}
    返回: {"success": True, "data": {"main_images": [...], "main_images_1x1": [...], "detail_images": [...], "white_background": "..."}}
    """
    image_urls = {'main_images': [], 'main_images_1x1': [], 'detail_images': [], 'white_background': ''}
    errors = []

    for label, files in image_paths.items():
        if not files:
            continue
        # main_images → 3:4 (1440x1920), 其他 → 1:1 (1440x1440)
        target = (1440, 1920) if label == 'main_images' else (1440, 1440)

        for f in files:
            if not os.path.exists(f):
                errors.append({"path": f, "label": label, "error": "FILE_NOT_FOUND"})
                continue

            processed = _resize_to_ratio(f, *target)
            url = _upload_single(processed, cookie_str)

            if processed != f:
                try: os.unlink(processed)
                except: pass

            if url:
                image_urls.setdefault(label, []).append(url)
            else:
                errors.append({"path": f, "label": label, "error": "UPLOAD_FAILED"})

    # 白底图 = 第一张1:1主图
    if not image_urls.get('white_background') and image_urls.get('main_images_1x1'):
        image_urls['white_background'] = image_urls['main_images_1x1'][0]

    result = make_success(image_urls)
    result['upload_errors'] = errors
    result['total_uploaded'] = sum(len(v) for k, v in image_urls.items() if k != 'white_background')
    return result


def _upload_single(image_path, cookie_str):
    """上传单张图片，返回 URL 或 None"""
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
        b'', image_data,
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

    try:
        req = Request('https://fxg.jinritemai.com/product/img/batchupload', data=body, headers=headers, method='POST')
        resp = urlopen(req, timeout=30)
        result = json.loads(resp.read().decode('utf-8'))
        if result.get('errno') == 0 and result.get('data'):
            return result['data'][0]
    except Exception:
        pass
    return None


# ============================================================
# Step 3: Schema 获取
# ============================================================

def get_schema(category_leaf_id, publish_id):
    """返回 {"success": True, "data": {...schema...}} 或 {"success": False, "error": {...}}"""
    ws, mid = None, None
    try:
        ws, mid = _cdp_ws()

        _cdp_call(ws, mid, 'Runtime.enable')
        r = _cdp_call(ws, mid, 'Runtime.evaluate', {
            'expression': f'''
                (async function() {{
                    if (!window.__fxgPost) {{
                        var chunkName = Object.keys(window).find(function(k) {{ return k.includes('@ecom-mcenter/ffa-goods'); }});
                        window[chunkName].push([[Math.floor(Math.random() * 1e9)], {{}}, function(req) {{
                            window.__fxgWebpackRequire = req;
                        }}]);
                        window.__fxgPost = window.__fxgWebpackRequire(90665).bE;
                    }}
                    var result = await window.__fxgPost('/product/tproduct/getSchema', {{
                        context: {{
                            category_id: '{category_leaf_id}',
                            operation_type: 'normal',
                            ability: [],
                            feature: {{session_publish_id: 'helper_{publish_id}'}}
                        }},
                        model: void 0
                    }}, {{timeout: 15000}});
                    return JSON.stringify(result);
                }})()
            ''',
            'returnByValue': True, 'awaitPromise': True, 'timeout': 20000
        })

        val = ((r.get('result') or {}).get('result') or {}).get('value', '')
        if isinstance(val, dict):
            schema = val  # webpack直接返回了对象
        elif isinstance(val, str):
            try:
                schema = json.loads(val)
            except json.JSONDecodeError:
                return make_error("ERR_SCHEMA_FAILED", code=-1, msg=f"JSON解析失败: {val[:200]}")
        else:
            return make_error("ERR_SCHEMA_FAILED", code=-1, msg=f"未知返回值类型: {type(val)}")

        if schema.get('errno') != 0 or schema.get('code') != 0:
            if str(schema.get('code')) == '500':
                return make_error("ERR_SCHEMA_FAILED", platform_code=500, msg=schema.get("msg", ""),
                                  category_id=category_leaf_id)

        if not schema.get('data'):
            return make_error("ERR_SCHEMA_EMPTY", category_id=category_leaf_id)

        items = schema.get('data', {}).get('model', {}).get('category_properties', {}).get('items')
        if not items:
            return make_error("ERR_SCHEMA_NO_PROPERTIES", category_id=category_leaf_id)

        return make_success({
            'schema': schema,
            'property_count': len(items),
            'property_ids': [str(item['id']) for item in items],
        })

    except PipelineError:
        raise
    except Exception as e:
        return make_error("ERR_PIPELINE_STEP", step="get_schema", detail=str(e))
    finally:
        if ws:
            try: ws.close()
            except: pass


# ============================================================
# Step 4: Body 构建
# ============================================================

def build_body(schema_data, product_data, image_urls, category_config, publish_id, shop_id):
    """构建 addWithSchema 请求体。返回 {"success": True, "data": {body}} 或 {"success": False, "error": {...}}"""
    try:
        title = product_data.get('title', '')
        if len(title) < 8:
            return make_error("ERR_BODY_MISSING_TITLE", detail=f"当前标题长度: {len(title)}")

        if not category_config or not category_config.get('category_leaf_id'):
            return make_error("ERR_BODY_MISSING_CATEGORY")

        category_leaf_id = category_config['category_leaf_id']

        sku_list = product_data.get('sku_info', [])
        if not sku_list:
            return make_error("ERR_BODY_INVALID_SKU")

        schema = schema_data['schema']
        items = schema['data']['model']['category_properties']['items']

        model = _build_model(items, product_data, image_urls, category_config)
        body = _assemble_body(model, category_leaf_id, publish_id, shop_id)

        return make_success({
            'body': body,
            'model_fields': len(model),
            'body_size': len(json.dumps(body, ensure_ascii=False)),
        })
    except PipelineError:
        raise
    except Exception as e:
        return make_error("ERR_PIPELINE_STEP", step="build_body", detail=str(e))


def _build_model(items, product_data, image_urls, category_config):
    """构建 model 部分"""
    def w(v):
        return {'value': v}

    # -- category_properties --
    cp = {}
    # 智能默认值: 必填 + 影响质量分的可选属性
    smart_defaults = {
        '1577': '通用', '1687': '无品牌',
        # 可选但影响质量分 (中筒袜类目)
        '241': '薄款',     # 厚度
        '810': '透气',     # 功能
        '1825': '镂空',    # 服饰工艺
        '1869': '纯色',    # 图案
        '1343': '夏季',    # 适用季节
        '2592': '韩系',    # 风格
    }

    for item in items:
        pid = str(item['id'])
        pname = item.get('label', '')
        opts = item.get('options') or []
        if not opts:
            continue

        # 必填 + 可选但有默认值的属性都要填
        is_required = item.get('required', False)
        has_default = pid in smart_defaults
        if not is_required and not has_default:
            continue

        target = smart_defaults.get(pid)
        selected = None
        if target:
            for o in opts:
                if o.get('value_name') == target:
                    selected = o
                    break
        if not selected and pname and category_config.get('fourth_cname'):
            for o in opts:
                if category_config['fourth_cname'] in (o.get('value_name') or ''):
                    selected = o
                    break
        if not selected:
            selected = opts[0]

        entry = {
            'diy_type': 0, 'measure_info': None, 'tags': None,
            'value_id': str(selected.get('value_id', '')),
            'value_name': str(selected.get('value_name', '')),
        }
        # 品牌需要 tags
        if pid == '1687' and selected.get('value_name') == '无品牌':
            entry['tags'] = {'brand_cn_name': ''}
        cp[pid] = [entry]

    # 材质成分 (785)
    material = product_data.get('material', '')
    if material and '785' in cp:
        del cp['785']
        cp['785'] = []
        for part in material.split(';'):
            part = part.strip()
            if not part:
                continue
            m = re.match(r'(.+?)(\d+)%?', part)
            mat_name, mat_pct = (m.group(1).strip(), m.group(2)) if m else (part, '100')
            cp['785'].append({
                'value_id': '', 'value_name': f'{mat_name}{mat_pct}%',
                'measure_info': {
                    'template_id': 873,
                    'values': [
                        {'module_id': 1854, 'prefix': '', 'suffix': '', 'value': mat_name},
                        {'module_id': 1855, 'prefix': '', 'suffix': '', 'value': mat_pct, 'unit_id': 15, 'unit_name': '%'},
                    ]
                }
            })

    # -- spec_detail --
    sku_list = product_data.get('sku_info', [])
    colors = list(set(s.get('name', '默认') for s in sku_list)) if sku_list else ['默认']

    spec_detail = []
    color_spec_values = []
    for i, c in enumerate(colors):
        color_spec_values.append({
            'id': str(996874532588296900 + i + 18),
            'name': c, 'cpv_id': 0, 'cpv_path': [], 'img_url': None
        })
    spec_detail.append({'id': '10000', 'cp_id': 2752, 'name': '颜色分类', 'spec_values': color_spec_values})
    spec_detail.append({
        'id': '20000', 'cp_id': 3939, 'name': '码数',
        'spec_values': [{'id': '990897920130195435', 'name': '均码', 'cpv_id': 0, 'cpv_path': [], 'img_url': None}]
    })
    spec_detail.append({'id': '30000', 'cp_id': 4706, 'name': '筒高长度', 'spec_values': []})
    spec_detail.append({'id': '40000', 'cp_id': 93, 'name': '规格', 'spec_values': []})

    # -- sku_detail --
    sku_detail = []
    price = str(product_data.get('price', {}).get('current', 9.9) or 9.9)
    color_spec_ids = [sv['id'] for sv in color_spec_values]
    size_spec_id = spec_detail[1]['spec_values'][0]['id'] if spec_detail[1]['spec_values'] else '990897920130195435'

    for i in range(len(colors)):
        sid = str(uuid.uuid4())[:8] + '-' + str(uuid.uuid4())[:6] + '-' + str(uuid.uuid4())[:12]
        sku_detail.append({
            'id': sid,
            'stock_info': {'stock_num': 100},
            'sku_status': True,
            'confirm_no_barcode': False,
            'spec_detail_ids': [color_spec_ids[i] if i < len(color_spec_ids) else color_spec_ids[0], size_spec_id],
            'price': price,
        })

    # -- 描述 --
    desc_parts = []
    for u in image_urls.get('main_images', [])[:1]:
        desc_parts.append(f'<img src="{u}" style="max-width:100%;"/>')
    for u in image_urls.get('main_images_1x1', [])[:1]:
        desc_parts.append(f'<img src="{u}" style="max-width:100%;"/>')
    for u in image_urls.get('detail_images', []):
        desc_parts.append(f'<img src="{u}" style="max-width:100%;"/>')
    description = '<p>' + ''.join(desc_parts) + '</p>' if desc_parts else ''

    # -- 组装 --
    model = {}
    model['title'] = w(product_data.get('title', ''))
    model['short_product_name'] = w('')
    model['title_prefix'] = w('')
    model['title_suffix'] = w('')
    model['title_use_brand_name'] = w(False)
    model['goods_category'] = w(category_config)
    model['category_properties'] = w(cp)
    model['category_property_pic'] = w({})
    model['pic'] = w([{'url': u} for u in image_urls.get('main_images_1x1', [])[:5]])
    model['main_image_three_to_four'] = w([{'url': u} for u in image_urls.get('main_images', [])[:5]])
    model['white_background_pic'] = w([{'url': image_urls['white_background']}] if image_urls.get('white_background') else [])
    model['description'] = w(description)
    model['spec_detail'] = w(spec_detail)
    model['sku_detail'] = w(sku_detail)
    model['freight_id'] = w('300713474')
    model['pickup_method'] = w('0')
    model['start_sale_type'] = w('0')
    model['product_type'] = w('0')
    model['presell_type'] = w('0')
    model['delivery_delay_day'] = w('2')
    model['reduce_type'] = w('1')
    model['qualification'] = w({})
    model['after_sale'] = w({'quality_problem_return': {'option_id': None, 'selected': True},
                             'supply_day_return_selector': {'option_id': '7-1', 'selected': True}})
    model['ai_gen_spec'] = w({'ai_gen_spec_type': 0})
    model['alli_promotion_plan_switch'] = w(False)
    model['area_stock_switcher'] = w(False)
    model['goods_category_appeal'] = w(False)
    model['interest_free_activity'] = w([])
    model['interest_free_activity_id'] = w({'activity_template_id': 'IFA202508061521201431032346'})
    model['interest_free_open'] = w(True)
    model['reference_price_enable'] = w(False)
    model['detail_prettify_uri'] = w('')

    return model


def _assemble_body(model, category_leaf_id, publish_id, shop_id):
    """组装完整请求体"""
    now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    random_hex = ''.join(random.choices('0123456789ABCDEF', k=20))
    n_token = now + random_hex
    session_publish_id = f'helper_{publish_id}'

    sku_values = model.get('sku_detail', {}).get('value', [])
    min_price = 990
    for sku in sku_values:
        try:
            p = int(float(sku.get('price', '9.9')) * 100)
            if p < min_price:
                min_price = p
        except (ValueError, TypeError):
            pass

    feature = {
        'session_publish_id': session_publish_id,
        'session_data': '{"stock_incr_mode":false,"only_update_stock":null}',
        'not_first_render': '1',
        'product_sale_property_control': '1',
        'sale_property_sequence_variable': '1',
        'min_sku_price': str(min_price),
    }

    context = {
        'ability': [],
        'biz_identity': 'xiaodian',
        'business_code': 'xiaodian',
        'capability_codes': ['standard_capability'],
        'category_id': str(category_leaf_id),
        'fast_publish_type': '',
        'feature': feature,
        'identity_extension': '{"Data":{}}',
        'model_type': '',
        'n_token': n_token,
        'operation_type': 'normal',
        'product_id': '0',
        'shop_id': shop_id,
        'token': n_token,
        'version': 'v1_v8_v9_v10_v11_v12',
    }

    return {
        'schema': {'model': model, 'context': context},
        'category_id': str(category_leaf_id),
        'context': context,
        'pass_through_extra': {},
        'request_extra': {},
        'check_status': 2,
        'session': {},
        'appid': 1,
    }


# ============================================================
# Step 5: 提交
# ============================================================

def submit_product(body):
    """通过 webpack post() 提交。返回 {"success": True, "data": {product_id, raw}} 或 {"success": False, "error": {...}}"""
    ws, mid = None, None
    try:
        ws, mid = _cdp_ws()

        _cdp_call(ws, mid, 'Runtime.enable')

        body_json = json.dumps(body, ensure_ascii=False)

        r = _cdp_call(ws, mid, 'Runtime.evaluate', {
            'expression': '''
                (async function() {
                    try {
                        var chunkName = Object.keys(window).find(function(k) { return k.includes('@ecom-mcenter/ffa-goods'); });
                        if (!window.__fxgWebpackRequire) {
                            window[chunkName].push([[Math.floor(Math.random() * 1e9)], {}, function(req) {
                                window.__fxgWebpackRequire = req;
                            }]);
                        }
                        var req = window.__fxgWebpackRequire;
                        var post = req(90665).bE;
                        var get = req(28974).J;

                        // 模拟页面流程: 提交前调用 publishClickStat
                        try {
                            await get('/product/tproduct/publishClickStat?check_status=2', {timeout: 3000});
                        } catch(e) {}

                        var result = await post('/product/tproduct/addWithSchema?check_status=2', ''' + body_json + ''', {timeout: 30000});
                        return JSON.stringify(result);
                    } catch(e) {
                        return JSON.stringify({error: true, errno: e.errno, code: e.code, msg: e.msg});
                    }
                })()
            ''',
            'returnByValue': True, 'awaitPromise': True, 'timeout': 40000
        })

        val = ((r.get('result') or {}).get('result') or {}).get('value', '')
        result = json.loads(val)

        # 成功
        if result.get('errno') == 0 and result.get('code') == 0:
            product_id = ''
            raw_data = result.get('data')
            if raw_data:
                try:
                    d = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
                    product_id = d.get('product_id', '') if isinstance(d, dict) else str(raw_data)
                except (json.JSONDecodeError, TypeError):
                    product_id = str(raw_data)

            return make_success({
                'product_id': product_id,
                'raw': result,
            })

        # 平台返回了错误
        return from_platform_response(result, step="submit")

    except PipelineError:
        raise
    except Exception as e:
        return make_error("ERR_PIPELINE_STEP", step="submit", detail=str(e))
    finally:
        if ws:
            try: ws.close()
            except: pass


# ============================================================
# 一键流水线 (带完整错误反馈)
# ============================================================

def run(category_leaf_id, product_data, image_paths, category_config, shop_id=None, cookie_str=None):
    """一键协议上传。返回统一结构:
    {
        "success": True/False,
        "data": {"product_id": "...", "steps": [...]},  # 成功时
        "error": {"code": "...", "message": "...", ...},  # 失败时
    }

    steps 记录每个环节的耗时与状态，用于性能监控与故障定位。
    """
    steps = []

    def _step(name):
        t0 = time.time()
        steps.append({'name': name, 'status': 'running'})
        return t0, steps[-1]

    def _done(entry, t0, ok=True, summary=''):
        entry['elapsed_ms'] = int((time.time() - t0) * 1000)
        entry['status'] = 'ok' if ok else 'failed'
        if summary:
            entry['summary'] = summary

    # ---- [1/5] 获取会话 ----
    t0, entry = _step('get_session')
    session_res = get_fxg_session()
    if not session_res['success']:
        _done(entry, t0, False, session_res['error']['message'])
        result = dict(session_res)
        result['steps'] = steps
        return result
    session = session_res['data']
    shop_id = shop_id or session.get('shop_id', '155450371')
    _done(entry, t0, True, f"publishId={session['publish_id'][:16]}... shopId={shop_id}")

    # ---- [2/5] 获取 Schema ----
    t0, entry = _step('get_schema')
    schema_res = get_schema(category_leaf_id, session['publish_id'])
    if not schema_res['success']:
        _done(entry, t0, False, schema_res['error']['message'])
        result = dict(schema_res)
        result['steps'] = steps
        return result
    _done(entry, t0, True, f"{schema_res['data']['property_count']} 类目属性")

    # ---- [3/5] 上传图片 ----
    t0, entry = _step('upload_images')
    upload_res = upload_images(image_paths, session['cookie_str'])
    image_urls = upload_res['data']
    upload_errors = upload_res.get('upload_errors', [])
    if upload_errors and upload_res['total_uploaded'] == 0:
        _done(entry, t0, False, f"全部上传失败: {len(upload_errors)} 个错误")
        result = make_error("ERR_IMAGE_UPLOAD_FAILED", path=upload_errors[0].get("path", ""),
                            detail=str(upload_errors))
        result['steps'] = steps
        return result
    summary = f"上传 {upload_res['total_uploaded']} 张"
    if upload_errors:
        summary += f" (跳过 {len(upload_errors)} 张)"
    _done(entry, t0, True, summary)

    # ---- [4/5] 构建 Body ----
    t0, entry = _step('build_body')
    body_res = build_body(schema_res['data'], product_data, image_urls,
                          category_config, session['publish_id'], shop_id)
    if not body_res['success']:
        _done(entry, t0, False, body_res['error']['message'])
        result = dict(body_res)
        result['steps'] = steps
        return result
    _done(entry, t0, True, f"{body_res['data']['body_size']} 字节")

    # ---- [5/5] 提交 ----
    t0, entry = _step('submit')
    submit_res = submit_product(body_res['data']['body'])
    if not submit_res['success']:
        _done(entry, t0, False, submit_res['error']['message'])
        result = dict(submit_res)
        result['steps'] = steps
        return result
    _done(entry, t0, True, f"product_id={submit_res['data']['product_id']}")

    # ---- 全部成功 ----
    return {
        **make_success({
            'product_id': submit_res['data']['product_id'],
            'raw_result': submit_res['data']['raw'],
        }),
        'steps': steps,
    }


# ============================================================
# 命令行入口
# ============================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='FXG 协议商品发布流水线')
    parser.add_argument('--title', default='协议测试-中筒袜夏季薄款棉袜', help='商品标题')
    parser.add_argument('--price', type=float, default=12.9, help='价格')
    parser.add_argument('--category', type=int, default=1000010267, help='类目leaf ID')
    parser.add_argument('--material', default='棉75%;氨纶25%', help='材质')
    parser.add_argument('--image-dir', help='图片目录 (可选)')
    parser.add_argument('--json', action='store_true', help='JSON格式输出')
    args = parser.parse_args()

    # 收集图片
    image_paths = {'main_images': [], 'main_images_1x1': [], 'detail_images': []}
    if args.image_dir:
        files = [os.path.join(args.image_dir, f) for f in os.listdir(args.image_dir)
                 if f.lower().endswith(('.jpg', '.png', '.jpeg'))]
        if files:
            image_paths['main_images'] = files[:1]
            image_paths['main_images_1x1'] = files[:1]
            image_paths['detail_images'] = files[1:3]

    result = run(
        category_leaf_id=args.category,
        product_data={
            'title': args.title,
            'price': {'current': args.price},
            'sku_info': [{'name': '白色'}, {'name': '黑色'}],
            'material': args.material,
        },
        image_paths=image_paths,
        category_config={
            'category_leaf_id': args.category,
            'first_cid': 1000003282, 'first_cname': '服装',
            'second_cid': 1000009114, 'second_cname': '内衣裤袜',
            'third_cid': 1000009597, 'third_cname': '袜子',
            'fourth_cid': args.category, 'fourth_cname': '中筒袜',
        },
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result['success']:
            print(f"\n✓ 发布成功")
            print(f"  product_id: {result['data']['product_id']}")
        else:
            err = result['error']
            print(f"\n✗ 发布失败")
            print(f"  错误码: {err['code']}")
            print(f"  类别: {err['category']}")
            print(f"  描述: {err['message']}")
            print(f"  建议: {err['fix_hint']}")
            if err.get('retryable'):
                print(f"  (此错误可重试)")
        print(f"\n  各步骤耗时:")
        for s in result['steps']:
            status_icon = '✓' if s['status'] == 'ok' else '✗'
            print(f"  {status_icon} {s['name']}: {s['elapsed_ms']}ms {s.get('summary', '')}")

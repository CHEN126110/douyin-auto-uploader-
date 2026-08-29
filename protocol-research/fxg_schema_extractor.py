# -*- coding: utf-8 -*-
"""动态 Schema 提取器 - 从 getSchema API 自动构建完整 addWithSchema body。

用法:
  from fxg_schema_extractor import SchemaExtractor
  extractor = SchemaExtractor(cdp_port=9333)
  body = extractor.build_submit_body(
      category_leaf_id=1000010267,  # 中筒袜
      product_data={'title': '...', 'sku_info': [...], 'price': 9.9},
      image_urls={'main_images': [...], ...},
  )
"""

import json, time, re
from urllib.request import urlopen
import websocket


class SchemaExtractor:
    """从抖音 getSchema API 提取类目元数据，自动构建 addWithSchema body"""

    def __init__(self, cdp_port=9333):
        self.cdp_port = cdp_port
        self._publish_id = None
        self._cookie_str = None
        self._schema_cache = {}  # category_leaf_id -> schema

    # ---- CDP 会话 ----

    def _cdp_connect(self):
        targets = json.loads(urlopen(f'http://127.0.0.1:{self.cdp_port}/json/list', timeout=3).read())
        target = next((t for t in targets if 'jinritemai.com' in (t.get('url') or '')), targets[0])
        ws = websocket.create_connection(target['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
        self._msg_id = [0]
        self._ws = ws
        return ws

    def _cdp(self, method, params=None, timeout=15):
        self._msg_id[0] += 1
        self._ws.send(json.dumps({'id': self._msg_id[0], 'method': method, 'params': params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self._ws.recv()
            msg = json.loads(raw)
            if msg.get('id') == self._msg_id[0]:
                return msg
        return {}

    def _cdp_close(self):
        try:
            self._ws.close()
        except:
            pass

    def ensure_session(self):
        """获取 cookies 和 publishId"""
        if self._cookie_str and self._publish_id:
            return

        self._cdp_connect()
        r = self._cdp('Network.enable')
        r = self._cdp('Network.getAllCookies')
        cookies = (r.get('result') or {}).get('cookies') or []
        self._cookie_str = '; '.join(
            f"{c['name']}={c['value']}" for c in cookies
            if 'jinritemai.com' in (c.get('domain') or '')
        )

        r = self._cdp('Runtime.evaluate', {
            'expression': '''
                (function() {
                    try {
                        for (var i = 0; i < sessionStorage.length; i++) {
                            var k = sessionStorage.key(i);
                            if (k.indexOf('publish') !== -1 || k.indexOf('create') !== -1) {
                                var v = sessionStorage.getItem(k);
                                var m = v.match(/(\\d{15,})/);
                                if (m) return m[1];
                            }
                        }
                    } catch(e) {}
                    return '';
                })()
            ''',
            'returnByValue': True
        })
        pid_raw = ((r.get('result') or {}).get('result') or {}).get('value', '')
        self._publish_id = pid_raw or '155450371177832138836357'  # fallback

        self._cdp_close()

    # ---- Schema 获取 ----

    def get_schema(self, category_leaf_id, force_refresh=False):
        """获取指定类目的完整 schema（带缓存）"""
        if not force_refresh and category_leaf_id in self._schema_cache:
            return self._schema_cache[category_leaf_id]

        self.ensure_session()
        self._cdp_connect()

        r = self._cdp('Runtime.evaluate', {
            'expression': f'''
                (async function() {{
                    var resp = await fetch('/product/tproduct/getSchema', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify({{
                            context: {{
                                category_id: '{category_leaf_id}',
                                operation_type: 'normal',
                                ability: [],
                                feature: {{session_publish_id: 'helper_{self._publish_id}'}}
                            }},
                            model: void 0
                        }})
                    }});
                    return await resp.text();
                }})()
            ''',
            'returnByValue': True,
            'awaitPromise': True,
            'timeout': 20000
        })

        self._cdp_close()
        val = ((r.get('result') or {}).get('result') or {}).get('value', '')
        schema = json.loads(val)
        self._schema_cache[category_leaf_id] = schema
        return schema

    # ---- Schema 解析 ----

    def parse_category_properties(self, schema):
        """解析类目属性，返回 {property_id: {name, required, options, type}}"""
        model = schema['data']['model']
        items = model['category_properties']['items']
        result = {}
        for item in items:
            pid = str(item['id'])
            result[pid] = {
                'name': item.get('label', ''),
                'required': item.get('required', False),
                'options': item.get('options') or [],
            }
        return result

    def parse_spec_detail(self, schema):
        """解析规格轴"""
        model = schema['data']['model']
        sd = model['spec_detail']
        return sd.get('value', []) if isinstance(sd, dict) else (sd if isinstance(sd, list) else [])

    # 属性默认值映射（优先选择更通用的值）
    SMART_DEFAULTS = {
        '1577': '通用',       # 适用性别 → 通用
        '1687': '商品级',     # 品牌 → 商品级(=无品牌)
    }

    def get_default_values(self, category_props, category_name=''):
        """为所有必填属性生成默认值，优先匹配 SMART_DEFAULTS 和类目名"""
        defaults = {}
        for pid, prop in category_props.items():
            if not prop['required']:
                continue
            opts = prop['options']
            if opts:
                # 优先使用智能默认值
                target_name = self.SMART_DEFAULTS.get(pid)
                if not target_name and pid in ('1865',):  # 筒高: 匹配类目名
                    target_name = category_name

                selected = None
                if target_name:
                    for o in opts:
                        if o.get('value_name', '') == target_name:
                            selected = o
                            break
                if not selected:
                    selected = opts[0]  # fallback: 第一个

                defaults[pid] = {
                    'value_id': str(selected.get('value_id', '')),
                    'value_name': str(selected.get('value_name', '')),
                    'diy_type': 0,
                    'measure_info': None,
                    'tags': None,
                }
            else:
                defaults[pid] = None  # 需要外部输入
        return defaults

    # ---- Body 构建 ----

    def build_submit_body(self, category_leaf_id, product_data, image_urls,
                          category_config=None, freight_id='300713474'):
        """构建完整的 addWithSchema body。

        Args:
            category_leaf_id: 类目叶子ID
            product_data: {title, price, sku_info, material?}
            image_urls: {main_images: [url], main_images_1x1: [url], white_background: url, detail_images: [url]}
            category_config: 可选，覆盖类目链 {first_cid, first_cname, ...}
            freight_id: 运费模板ID

        Returns:
            完整的 addWithSchema body dict
        """
        schema = self.get_schema(category_leaf_id)
        props = self.parse_category_properties(schema)
        specs = self.parse_spec_detail(schema)
        cat_name = (category_config or {}).get('fourth_cname', '')
        defaults = self.get_default_values(props, cat_name)

        # ---- category_properties ----
        cp_body = {}
        for pid, default_val in defaults.items():
            if default_val is None:
                continue  # 需要外部输入（如材质成分 measure_info）
            cp_body[pid] = [default_val]

        # 从 product_data 补充材质成分 (property 785)
        material = product_data.get('material', '')
        if material and '785' in props:
            parts = [p.strip() for p in material.split(';') if p.strip()]
            cp_body['785'] = []
            for part in parts[:3]:
                m = re.match(r'(.+?)(\d+)%?', part)
                if m:
                    mat_name, mat_pct = m.group(1).strip(), m.group(2)
                else:
                    mat_name, mat_pct = part, '100'
                cp_body['785'].append({
                    'value_id': '', 'value_name': mat_name,
                    'measure_info': {
                        'template_id': 873,
                        'values': [
                            {'module_id': 1854, 'prefix': '', 'suffix': '', 'value': mat_name},
                            {'module_id': 1855, 'prefix': '', 'suffix': '', 'value': mat_pct, 'unit_id': 15, 'unit_name': '%'},
                        ]
                    }
                })

        # ---- spec_detail ----
        sku_list = product_data.get('sku_info', [])
        colors = list(set(s.get('name', '默认') for s in sku_list)) if sku_list else ['默认']

        spec_detail = []
        for spec in specs:
            sid = spec.get('id', '')
            sname = spec.get('name', '')
            svals = spec.get('spec_values') or spec.get('values') or []
            if sname == '颜色分类' or '颜色' in sname:
                spec_detail.append({
                    'id': sid, 'cp_id': spec.get('cp_id', 0), 'name': sname,
                    'spec_values': [
                        {'source_index': i + 1, 'id': f'dry_{sid}_{i+1}', 'name': c, 'img_url': None, 'measure_info': None}
                        for i, c in enumerate(colors)
                    ]
                })
            elif svals:
                # 使用第一个预定义值
                first_val = svals[0]
                spec_detail.append({
                    'id': sid, 'cp_id': spec.get('cp_id', 0), 'name': sname,
                    'spec_values': [
                        {'source_index': 1, 'id': str(first_val.get('id', '')), 'name': str(first_val.get('name', '')), 'img_url': None, 'measure_info': None}
                    ]
                })

        # ---- sku_detail ----
        sku_detail = []
        price = product_data.get('price', {}).get('current', 9.9) or 9.9
        for i, color in enumerate(colors):
            spec_ids = [sv['spec_values'][0]['id'] if sv['spec_values'] else 'dry_1_1' for sv in spec_detail]
            # 颜色轴使用对应index, 其他轴使用第一个值
            final_ids = []
            for j, sv in enumerate(spec_detail):
                if j == 0:  # 颜色轴
                    final_ids.append(sv['spec_values'][i]['id'] if i < len(sv['spec_values']) else sv['spec_values'][0]['id'])
                else:
                    final_ids.append(sv['spec_values'][0]['id'])
            sku_detail.append({
                'id': f'dry_sku_{i+1}',
                'source_index': i + 1,
                'spec_detail_ids': final_ids,
                'sku_pic': [],
                'spec_names': {sv['name']: sv['spec_values'][min(i, len(sv['spec_values'])-1)]['name'] for sv in spec_detail},
                'price': str(price),
                'stock': 100,
            })

        # ---- goods_category ----
        if category_config:
            goods_cat = {
                'category_leaf_id': category_leaf_id,
                'first_cid': category_config['first_cid'],
                'first_cname': category_config['first_cname'],
                'second_cid': category_config['second_cid'],
                'second_cname': category_config['second_cname'],
                'third_cid': category_config['third_cid'],
                'third_cname': category_config['third_cname'],
                'fourth_cid': category_config.get('fourth_cid', category_leaf_id),
                'fourth_cname': category_config.get('fourth_cname', ''),
            }
        else:
            goods_cat = {'category_leaf_id': category_leaf_id}

        # ---- description ----
        detail_urls = image_urls.get('detail_images', [])
        desc = '\n'.join(f'<img src="{u}">' for u in detail_urls) if detail_urls else ''

        # ---- 组装完整 body ----
        body = {
            'title': product_data.get('title', ''),
            'goods_category': goods_cat,
            'category_properties': cp_body,
            'pickup_method': '0',
            'start_sale_type': '0',
            'product_type': '0',
            'presell_type': '0',
            'freight_id': freight_id,
            'pic': [{'url': u} for u in image_urls.get('main_images_1x1', [])[:5]],
            'main_image_three_to_four': [{'url': u} for u in image_urls.get('main_images', [])[:5]],
            'white_background_pic': [{'url': image_urls['white_background']}] if image_urls.get('white_background') else [],
            'main_pic_video': [],
            'description': desc,
            'qualification': {},
            'spec_detail': spec_detail,
            'sku_detail': sku_detail,
        }
        return body

    # ---- 完整流水线 ----

    def run_pipeline(self, category_leaf_id, product_data, image_urls, category_config=None, submit=False):
        """一键运行完整流水线: schema → body → 图片上传 → 保存草稿"""
        print('[1/3] 获取 Schema...')
        body = self.build_submit_body(category_leaf_id, product_data, image_urls, category_config)
        print(f'  Body: title={bool(body["title"])} pic={len(body["pic"])} spec={len(body["spec_detail"])} sku={len(body["sku_detail"])}')
        print(f'  category_properties: {len(body["category_properties"])} 项')

        if submit:
            print('[2/3] 保存草稿...')
            url = 'https://fxg.jinritemai.com/product/tproduct/addWithSchema?check_status=0'
            body_json = json.dumps({'schema': body}, ensure_ascii=False).encode('utf-8')
            from urllib.request import Request as _Req, urlopen as _urlopen
            req = _Req(url, data=body_json, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120',
                'Cookie': self._cookie_str,
                'Content-Type': 'application/json',
                'Referer': 'https://fxg.jinritemai.com/ffa/g/create',
                'Origin': 'https://fxg.jinritemai.com',
            }, method='POST')
            try:
                resp = _urlopen(req, timeout=30)
                result = json.loads(resp.read().decode('utf-8'))
                print(f'  结果: {json.dumps(result, ensure_ascii=False)[:300]}')
            except Exception as e:
                print(f'  提交失败: {e}')
        else:
            print('[2/3] 跳过提交 (submit=False)')

        print('[3/3] 完成!')
        return body

# -*- coding: utf-8 -*-
"""淘宝采集的 SKU 契约：规格组合是记录，图片是该记录的素材，不由图片数量生成 SKU。"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re


def money(value, *, cents=False):
    if value is None or value == '' or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value)) / (100 if cents else 1)
    except InvalidOperation as exc:
        raise ValueError('SKU价格不是明确数值') from exc
    if not amount.is_finite() or amount <= 0:
        return None
    return float(amount)


def image_url(value):
    value = str(value or '').strip()
    return 'https:' + value if value.startswith('//') else value


def sku_key(sku):
    if sku.get('sku_id'):
        return 'sku:' + str(sku['sku_id'])
    identity = sku.get('prop_path') or sku.get('spec_values') or sku.get('name')
    if not identity:
        raise ValueError('SKU缺少规格身份')
    return 'spec:' + hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def validate_skus(rows, *, require_images=False):
    if not isinstance(rows, list) or not rows:
        raise ValueError('未能提取SKU规格，不能把图片列表当作规格')
    result, identities, names = [], set(), set()
    for index, original in enumerate(rows, 1):
        if not isinstance(original, dict) or not str(original.get('name') or '').strip():
            raise ValueError('SKU缺少完整规格名称')
        row = deepcopy(original)
        row['name'] = row['name'].strip()
        key = sku_key(row)
        if key in identities:
            raise ValueError('采集结果重复了同一个SKU身份：' + row['name'])
        # 多个不同 ID 同名也不能静默丢弃其中一条。
        if row['name'] in names:
            raise ValueError('不同SKU缺少可区分的完整规格：' + row['name'])
        row['sku_key'] = key
        row['index'] = index
        row['image'] = image_url(row.get('image'))
        if require_images and not row['image']:
            raise ValueError('SKU缺少对应规格图，未用主图替代：' + row['name'])
        row['price'] = money(row.get('price'))
        identities.add(key)
        names.add(row['name'])
        result.append(row)
    return result


def from_ice(payload):
    """只枚举平台 skuBase.skus 的真实组合，以 pid:vid 绑定名称和图片。"""
    if not isinstance(payload, dict) or payload.get('error'):
        return None
    base = payload.get('skuBase')
    core = payload.get('skuCore') or {}
    info = core.get('sku2info') or {}
    item = payload.get('item') or {}
    main = [image_url(url) for url in item.get('images') or [] if url]
    data = {'title': str(item.get('title') or '').strip(), 'main_images': main,
            'detail_images': [], 'parameters': [], 'sku_info': [], 'sku_source': 'ice',
            'price': {'current': money((info.get('0', {}).get('price') or {}).get('priceMoney'), cents=True) or 0,
                      'original': None, 'currency': 'CNY'}}
    desc = image_url(item.get('pcADescUrl') or item.get('pcDescUrl'))
    if desc:
        data['_pc_desc_url'] = desc
    if not isinstance(base, dict) or not isinstance(base.get('props'), list) or not isinstance(base.get('skus'), list):
        return data
    properties = {}
    for prop in base['props']:
        pid = str(prop.get('pid', ''))
        if not pid or pid in properties or not prop.get('name'):
            raise ValueError('结构化SKU属性身份不完整或重复')
        values = {}
        for value in prop.get('values') or []:
            vid = str(value.get('vid', ''))
            if not vid or vid in values or not value.get('name'):
                raise ValueError('结构化SKU属性值身份不完整或重复')
            values[vid] = value
        properties[pid] = (str(prop['name']), values)
    rows = []
    seen_ids = {}
    for sku in base['skus']:
        sid = str(sku.get('skuId') or '')
        if not sid:
            raise ValueError('结构化SKU缺少skuId')
        pairs = [part.split(':', 1) for part in str(sku.get('propPath') or '').split(';') if part]
        chosen = {}
        for pair in pairs:
            if len(pair) != 2 or pair[0] not in properties or pair[1] not in properties[pair[0]][1] or pair[0] in chosen:
                raise ValueError('SKU规格路径不能完整映射到属性值：' + sid)
            chosen[pair[0]] = pair[1]
        if set(chosen) != set(properties):
            raise ValueError('SKU规格路径缺少属性：' + sid)
        specs, images = {}, []
        for pid, (name, values) in properties.items():
            value = values[chosen[pid]]
            specs[name] = str(value['name'])
            url = image_url(value.get('image') or value.get('imageUrl') or value.get('img') or value.get('imgUrl'))
            if url:
                images.append(url)
        if len(set(images)) > 1:
            raise ValueError('同一SKU多个规格轴提供不同图片，图片归属需要明确：' + sid)
        price = money(((info.get(sid) or {}).get('price') or {}).get('priceMoney'), cents=True)
        row = {'sku_id': sid, 'name': ' / '.join(specs.values()), 'spec_values': specs,
               'prop_path': ';'.join(pid + ':' + chosen[pid] for pid in properties),
               'image': images[0] if images else '', 'image_source': 'sku_property',
               'price': price, 'price_source': 'sku_price' if price is not None else 'missing',
               'source': 'taobao_ice', 'type': '规格组合'}
        if sid in seen_ids:
            if seen_ids[sid] != row:
                raise ValueError('同一skuId出现互相冲突的资料：' + sid)
            continue
        seen_ids[sid] = row
        rows.append(row)
    if not base['skus'] and not properties and info.get('0'):
        # 只有平台明确声明无规格时，商品主图才是该唯一默认项的图片来源。
        rows = [{'sku_id': '0', 'name': '默认', 'spec_values': {}, 'image': main[0] if main else '',
                 'image_source': 'explicit_no_variants', 'price': data['price']['current'],
                 'price_source': 'default_sku', 'source': 'taobao_ice', 'type': '规格组合'}]
    if rows:
        data['sku_info'] = validate_skus(rows)
        if not data['price']['current']:
            prices = [row['price'] for row in rows if row['price'] is not None]
            if prices:
                data['price']['current'] = min(prices)
    return data


DOM_GROUPS_JS = r'''return (() => {
  const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);
    return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';};
  const exactRoots=Array.from(document.querySelectorAll('#skuOptionsArea')).filter(visible);
  const roots=exactRoots.length?exactRoots:Array.from(document.querySelectorAll('[class*="skuWrapper"]')).filter(visible)
    .filter(el=>!el.parentElement.closest('[class*="skuWrapper"]'));
  if(roots.length!==1)return {groups:[],error:'sku_root_not_unique'};
  const selector='[class*="skuItem"]';
  const groups=[];
  for(const group of Array.from(roots[0].querySelectorAll(selector)).filter(visible)){
    const labels=Array.from(group.querySelectorAll('[class*="ItemLabel"],[data-sku-label]'))
      .filter(el=>el.closest(selector)===group&&visible(el));
    if(!labels.length)continue;
    const label=labels[0];
    const leaves=Array.from(label.querySelectorAll('span')).filter(el=>visible(el)&&!el.children.length
      &&!el.closest('button,a,[role=button]')&&(el.textContent||'').trim());
    const name=(leaves.length?leaves[0].textContent:label.textContent||'').trim();
    const values=Array.from(group.querySelectorAll('[class*="valueItem"]')).filter(el=>visible(el)&&el.closest(selector)===group);
    // 原生 li/button 仅用于没有 valueItem 的组，不能和外层 valueItem 同时枚举。
    const candidates=values.length?values:Array.from(group.querySelectorAll('li,button,[role=option]'))
      .filter(el=>visible(el)&&el.closest(selector)===group&&!label.contains(el));
    const options=candidates.filter(el=>!candidates.some(parent=>parent!==el&&parent.contains(el)));
    const rows=[];
    for(const option of options){
      const named=option.querySelector('span[title],[data-value-name],span')||option;
      const value=(option.getAttribute('title')||named.getAttribute('title')||named.textContent||'').trim();
      if(!value)continue;
      const imgs=Array.from(option.querySelectorAll('img')).map(img=>img.getAttribute('data-src')
        ||img.getAttribute('data-ks-lazyload')||img.getAttribute('src')||'').filter(Boolean);
      const urls=[...new Set(imgs.map(src=>src.startsWith('//')?'https:'+src:src))];
      if(urls.length>1)return {groups:[],error:'sku_option_image_ambiguous'};
      rows.push({name:value,image:urls[0]||'',vid:option.getAttribute('data-vid')||'',
        price:option.getAttribute('data-price')||null});
    }
    if(name&&rows.length)groups.push({name,pid:group.getAttribute('data-pid')||'',values:rows});
  }
  return {groups};
})()'''


def from_dom_groups(payload):
    """单一可变规格轴与固定属性可直接组成 SKU；多个可变轴需真实组合表。"""
    if not isinstance(payload, dict) or payload.get('error'):
        raise ValueError('商品规格区域无法唯一识别：' + str((payload or {}).get('error') or 'invalid_payload'))
    groups, by_group = [], {}
    for original in payload.get('groups') or []:
        name = str(original.get('name') or '').strip()
        values, by_value = [], {}
        for value in original.get('values') or []:
            row = {'name': str(value.get('name') or '').strip(), 'image': image_url(value.get('image')),
                   'vid': str(value.get('vid') or ''), 'price': money(value.get('price'))}
            if not row['name']:
                raise ValueError('DOM规格值缺少名称')
            identity = row['vid'] or row['name']
            if identity in by_value:
                if by_value[identity] != row:
                    raise ValueError('同一规格值存在不同内容，不能按名称丢弃：' + row['name'])
                continue
            by_value[identity] = row
            values.append(row)
        if not name or not values:
            raise ValueError('DOM规格属性不完整')
        group = {'name': name, 'pid': str(original.get('pid') or ''), 'values': values}
        identity = group['pid'] or name
        if identity in by_group:
            if by_group[identity] != group:
                raise ValueError('页面存在互相冲突的规格组：' + name)
            continue
        by_group[identity] = group
        groups.append(group)
    if not groups:
        return []
    variable = [group for group in groups if len(group['values']) > 1]
    if len(variable) > 1:
        raise ValueError('页面展示多个可变规格轴，但缺少实际可售SKU组合；不能猜测笛卡尔积')
    varying = variable[0] if variable else groups[0]
    rows = []
    for value in varying['values']:
        chosen = [(group, value if group is varying else group['values'][0]) for group in groups]
        specs = {group['name']: option['name'] for group, option in chosen}
        images = {option['image'] for _, option in chosen if option['image']}
        if len(images) > 1:
            raise ValueError('规格组合的图片来源不唯一')
        rows.append({'name': ' / '.join(specs.values()), 'spec_values': specs,
                     'image': next(iter(images), ''), 'image_source': 'dom_option',
                     'price': value['price'], 'price_source': 'option_price' if value['price'] is not None else 'missing',
                     'source': 'taobao_dom', 'type': '规格组合'})
    return validate_skus(rows)


def bind_local_files(product):
    """按采集记录绑定下载结果；目录里多出来的图片不能产生额外 SKU。"""
    from PIL import Image
    declared_root = Path(product.get('download_path') or '').absolute()
    for directory in (declared_root, *declared_root.parents, declared_root / 'SKU'):
        if directory.is_symlink() or (directory.exists() and getattr(directory.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('采集图片目录不能经过链接或目录联接')
    root = declared_root.resolve(strict=True)
    sku_root = root / 'SKU'
    if not sku_root.is_dir():
        raise ValueError('未找到SKU文件夹')
    rows = validate_skus(product.get('sku_info'))
    image_files = [path for path in sku_root.rglob('*') if path.is_file()
                   and path.suffix.lower() in {'.jpg', '.jpeg', '.webp', '.png', '.bmp', '.gif'}]
    result, used = [], set()
    for source in rows:
        local = source.get('local_image_path')
        if local:
            file = Path(local)
            if not file.is_absolute():
                file = root / file
            candidates = [file]
        else:
            # 旧采集结果没有路径回执时仅允许序号+完整名称或完整文件名精确匹配。
            safe_name = re.sub(r'[\\/:*?"<>|]', '_', source['name'][:50])
            stems = {safe_name, f"{source['index']:02d}_{safe_name}"}
            candidates = [path for path in image_files if path.stem in stems]
        if len(candidates) != 1:
            raise ValueError('SKU图片缺失或无法唯一对应完整规格：' + source['name'])
        file = candidates[0]
        actual = file.resolve(strict=True)
        if not actual.is_relative_to(sku_root.resolve()) or file.is_symlink() or actual in used:
            raise ValueError('SKU图片路径越界或同一文件被重复绑定')
        if source.get('image_sha256') and hashlib.sha256(actual.read_bytes()).hexdigest() != source['image_sha256']:
            raise ValueError('SKU图片已改变：' + source['name'])
        with Image.open(actual) as image:
            image.verify()
        used.add(actual)
        result.append({'file_name': actual.stem, 'dir_name': actual.parent.name,
                       'name': source['name'], 'path': str(actual), 'price': source['price'] if source['price'] is not None else '',
                       'sku_id': str(source.get('sku_id') or ''), 'sku_key': source['sku_key'],
                       'spec_values': source.get('spec_values') or {},
                       'image_source': source.get('image_source') or 'captured_sku',
                       'price_source': source.get('price_source') or 'captured_sku'})
    return result


def download_assets(product, product_url, base_dir, *, extract_sku=True):
    """一次下载一份 SKU 清单；全部必需素材成功后再切换目录，旧批次保留备份。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from io import BytesIO
    import uuid
    import requests
    from PIL import Image, UnidentifiedImageError

    rows = validate_skus(product.get('sku_info'), require_images=True) if extract_sku else []
    identity = str(product.get('product_id') or '')
    if not re.fullmatch(r'\d+', identity):
        raise ValueError('商品素材目录缺少有效商品编号')
    base = Path(base_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    destination = base / ('ID-' + identity)
    if destination.is_symlink() or (destination.exists() and getattr(destination.lstat(), 'st_file_attributes', 0) & 0x400):
        raise ValueError('商品素材目录不能是链接或目录联接')
    run_id = uuid.uuid4().hex
    staging_base = base.parent / '.capture-staging'
    backup_base = base.parent / '.capture-backups'
    for owned in (staging_base, backup_base):
        owned.mkdir(exist_ok=True)
        if owned.resolve().parent != base.parent or owned.is_symlink():
            raise ValueError('采集临时目录或备份目录越界')
    staging = staging_base / run_id / destination.name
    for folder in ('主图', 'SKU', '详情页'):
        (staging / folder).mkdir(parents=True)

    jobs = []
    for index, url in enumerate(product.get('main_images') or [], 1):
        url = image_url(url)
        jobs.append({'url': url, 'stem': f'主图/主图_{index:02d}', 'required': True})
        if 'alicdn.com' in url:
            original = re.sub(r'(?:_\.webp|\.webp)$', '', url)
            original = re.sub(r'_(?:\d+x\d+q?\d*|q\d+)\.jpg_?$', '', original)
            jobs.append({'url': original + '_800x800xz.jpg', 'stem': f'主图/主图_{index:02d}_1x1', 'required': False})
    for index, sku in enumerate(rows, 1):
        name = re.sub(r'[\\/:*?"<>|]', '_', sku['name'][:50])
        jobs.append({'url': sku['image'], 'stem': f'SKU/{index:02d}_{name}', 'required': True, 'sku': sku})
    for index, url in enumerate(product.get('detail_images') or [], 1):
        jobs.append({'url': image_url(url), 'stem': f'详情页/详情_{index:03d}', 'required': True})

    grouped = {}
    for job in jobs:
        grouped.setdefault(job['url'], []).append(job)
    failures, warnings = [], []
    extensions = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'GIF': '.gif', 'BMP': '.bmp'}
    with requests.Session() as session:
        session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                                'Referer': product_url})
        def fetch(url):
            if not url.startswith(('https://', 'http://')):
                raise ValueError('图片地址无效')
            response = session.get(url, timeout=15)
            response.raise_for_status()
            content = response.content
            with Image.open(BytesIO(content)) as image:
                suffix = extensions.get(image.format)
                if not suffix or min(image.size) < 2:
                    raise ValueError('下载内容不是受支持的有效图片')
                image.verify()
            return content, suffix
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(fetch, url): entries for url, entries in grouped.items()}
            for future in as_completed(futures):
                entries = futures[future]
                try:
                    content, suffix = future.result()
                except Exception as exc:
                    status = getattr(getattr(exc, 'response', None), 'status_code', None)
                    if status is not None:
                        reason = 'HTTP ' + str(status)
                    elif isinstance(exc, requests.Timeout):
                        reason = '图片请求超时'
                    elif isinstance(exc, requests.ConnectionError):
                        reason = '图片网络连接失败'
                    elif isinstance(exc, requests.RequestException):
                        reason = type(exc).__name__
                    elif isinstance(exc, (ValueError, UnidentifiedImageError)):
                        reason = str(exc)
                    else:
                        reason = type(exc).__name__ + '：' + str(exc)
                    for job in entries:
                        message = job['stem'] + '：' + reason
                        (failures if job['required'] else warnings).append(message)
                    continue
                digest = hashlib.sha256(content).hexdigest()
                for job in entries:
                    relative = job['stem'] + suffix
                    (staging / relative).write_bytes(content)
                    if 'sku' in job:
                        job['sku']['local_image_path'] = relative
                        job['sku']['image_sha256'] = digest
    if failures:
        raise ValueError('本批图片下载未完成，原商品目录已保留：' + '；'.join(failures[:5])
                         + '；本批临时目录：' + str(staging))
    # 本地交接只需路径/摘要与规格身份，不保存可能带签名参数的远程地址。
    local_rows = [{key: value for key, value in row.items() if key != 'image'} for row in rows]
    manifest = {'version': 1, 'product_id': identity, 'sku_info': local_rows, 'warnings': warnings}
    (staging / 'capture_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    archived = backup_base / (destination.name + '-' + run_id)
    moved_old = False
    # 两个目标都由固定基目录与本批 ID 构成，移动前再次核对解析后的边界。
    if destination.resolve().parent != base or archived.resolve().parent != backup_base.resolve():
        raise ValueError('采集目录切换的目标越界')
    if destination.exists():
        destination.rename(archived)
        moved_old = True
    try:
        staging.rename(destination)
    except OSError:
        if moved_old and not destination.exists():
            archived.rename(destination)
        raise
    product['sku_info'] = rows
    product['download_warnings'] = warnings
    return str(destination)

# -*- coding: utf-8 -*-
"""链接采集：直接调用对打（续）——详情图 / 单品快照 / 三级回退采集 / 属性 / 端口选择 / 入库（2026-10-20）。"""
import json
import os

import scen_capture as S
from scen_capture_direct import DOM_GROUPS, ICE_JSON, ICE_PLAIN, call, drain, jsonable, page_with

CDN_URLS = ['//img.alicdn.com/a/1.jpg', 'https://img.alicdn.com/a/2.png_400x400.png', '//img.alicdn.com/a/s.gif',
            'https://gw.alicdn.com/placeholder-1.jpg', 'https://other.example.com/x.jpg', 'https://img.taobaocdn.com/b/3.webp',
            'https://img.alicdn.com/a/4', '//img.alicdn.com/a/1.jpg', 'https://img.alicdn.com/a/5.jpeg?x=1']


def make_png(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fp:
        fp.write(S.PNG_BYTES)


def make_product_dir(ctx, pid, names=('白色_均码', '灰色_均码')):
    """造一个能通过 bind_local_files 校验的采集目录：SKU 图是真 PNG，文件名为「序号_名称」。"""
    root = os.path.join(ctx.data_dir, 'uploads', 'products', 'ID-' + pid)
    make_png(os.path.join(root, '主图', '主图_01.jpg'))
    for index, name in enumerate(names, 1):
        make_png(os.path.join(root, 'SKU', '%02d_%s.jpg' % (index, name)))
    return root


def product_for(ctx, pid, root=None):
    return {'product_id': pid, 'title': '袜子' + pid, 'price': {'current': 9.9, 'original': None, 'currency': 'CNY'},
            'main_images': ['https://img.alicdn.com/m/%s.jpg' % pid], 'detail_images': [],
            'sku_info': [{'name': '白色 / 均码', 'index': 1, 'image': 'https://x/w.jpg', 'price': 9.9},
                         {'name': '灰色 / 均码', 'index': 2, 'image': 'https://x/g.jpg', 'price': 9.9}],
            'download_path': root or make_product_dir(ctx, pid, ('白色 _ 均码', '灰色 _ 均码')), 'url': 'https://item.taobao.com/item.htm?id=' + pid,
            'captured_attributes': {'version': 1, 'source': 'visible_product_parameters_v1', 'status': 'captured',
                                    'attributes': [{'name': '材质', 'value': '纯棉'}]}}


# ------------------------------------------------------------------------------------------ 详情图 / 单品快照
def desc_and_snapshot(ctx):
    out = {}
    f = lambda name: S.fn(ctx, name)           # noqa: E731
    state = ctx.state
    desc_js = ('var sels = [', CDN_URLS)
    call(out, 'desc_via_browser', f('_collect_taobao_desc_images_via_browser'), page_with(ctx, extra_js=[desc_js]))
    call(out, 'desc_via_browser_limit', f('_collect_taobao_desc_images_via_browser'), page_with(ctx, extra_js=[desc_js]), 2)
    call(out, 'desc_via_browser_none', f('_collect_taobao_desc_images_via_browser'), page_with(ctx, extra_js=[desc_js[:1] + (None,)]))
    call(out, 'desc_scroll_errors', f('_collect_taobao_desc_images_via_browser'),
         page_with(ctx, extra_js=[('window.scrollTo(0, 0)', RuntimeError('scroll failed')), desc_js]))
    for url in ('//desc.taobao.com/desc/555', 'https://desc.taobao.com/desc/broken', 'https://x.com/h.fail', 'https://x.com/other'):
        call(out, 'fetch_desc(%s)' % url, f('_fetch_taobao_desc_images'), None, url)
    cache = S.mtop_cache_of(ctx)
    cache.clear()
    cache['555000'] = {'title': '缓存标题', 'priceDecoded': '1590', 'image': '//img.alicdn.com/c/cache.jpg'}
    cache['666000'] = {'title': '', 'priceDecoded': 'abc', 'image': ''}
    dom = [('var selectors = ["', ' 页面标题 '), ('parsePriceText', 20.8), ('function cleanList', {
        'main': ['https://img.alicdn.com/main/1.jpg'], 'detail': ['https://img.alicdn.com/main/1.jpg', 'https://img.alicdn.com/d/2.jpg']}),
        ('skuOptionsArea', DOM_GROUPS)]
    call(out, 'snapshot_cached', f('_extract_taobao_tmall_product_snapshot'), page_with(ctx, extra_js=dom), S.URL_TAOBAO)
    call(out, 'snapshot_bad_cache', f('_extract_taobao_tmall_product_snapshot'), page_with(ctx, extra_js=dom), S.URL_TMALL, include_skus=False)
    call(out, 'snapshot_no_cache_no_title', f('_extract_taobao_tmall_product_snapshot'),
         page_with(ctx, extra_js=[('var selectors = ["', ''), ('parsePriceText', 0), ('function cleanList', None), ('skuOptionsArea', {'groups': []})]),
         'https://item.taobao.com/item.htm?id=1')
    call(out, 'snapshot_sku_error', f('_extract_taobao_tmall_product_snapshot'),
         page_with(ctx, extra_js=dom[:3] + [('skuOptionsArea', {'error': 'sku_root_not_unique'})]), 'https://item.taobao.com/item.htm?id=2')
    cache.clear()
    drain(ctx, out, 'drained')
    return out


# ------------------------------------------------------------------------------------------ 单品三级回退采集（真实函数）
HTML_OK = ('<title>HTTP商品</title>"priceMoney":"2080","images":["https://img.example.invalid/main.jpg","//img.example.invalid/m2.jpg"]'
           + ' ' * 10001)
HTML_PLAIN_TITLE = '<title>商品详情</title>' + ' ' * 10001


def product_capture(ctx):
    import src.taobao_capture as taobao_capture
    out = {}
    f = lambda name: S.fn(ctx, name)           # noqa: E731
    state = ctx.state
    real_download = taobao_capture.download_assets
    taobao_capture.download_assets = lambda product, url, base, extract_sku=True: 'ASSETS:' + str(product.get('product_id')) + ':' + str(extract_sku)
    try:
        dom = [('var selectors = ["', ' 页面标题 '), ('parsePriceText', 20.8), ('function cleanList', {
            'main': ['https://img.alicdn.com/main/1.jpg'], 'detail': ['https://img.alicdn.com/d/2.jpg']}), ('skuOptionsArea', DOM_GROUPS)]
        base = dict(start_url=S.URL_TAOBAO, extra_js=[('__ICE_APP_CONTEXT__', ICE_JSON)] + dom)
        state['cdp_port'] = 9401

        def capture(label, options=None, mtop_cache=None, url=S.URL_TAOBAO, **behavior):
            S.mtop_cache_of(ctx).clear()
            S.set_cookie_state(ctx, '', 0.0)
            page = page_with(ctx, **dict(base, **behavior))
            kwargs = {} if mtop_cache is None else {'mtop_cache': mtop_cache}
            call(out, label, f('_capture_taobao_tmall_product_for_store'), page, url, options if options is not None else {}, **kwargs)
        # Tier 1：ICE 成功，详情图靠 pcDescUrl 二次读取
        capture('ice_ok_desc_from_url')
        capture('ice_ok_no_download', {'download_images': False})
        capture('ice_ok_extract_sku_off', {'extract_sku': False, 'extract_params': False})
        # 页面还停在上一件商品：先导航进目标商品；导航后仍不对就报错
        capture('navigate_into_product', start_url='https://item.taobao.com/item.htm?id=111', nav_map={S.URL_TAOBAO: S.URL_TAOBAO})
        capture('navigate_fails', start_url='https://item.taobao.com/item.htm?id=111', get_redirect='https://item.taobao.com/item.htm?id=222')
        # Tier 2：ICE 没有数据 → HTTP 正则 → DOM 补全
        no_ice = [('__ICE_APP_CONTEXT__', json.dumps({'error': 'no_ice_data'}))] + dom
        capture('http_regex_then_dom', extra_js=no_ice, item_html=HTML_OK)
        capture('http_plain_title', extra_js=no_ice, item_html=HTML_PLAIN_TITLE)
        capture('http_request_fails', extra_js=no_ice, item_html=HTML_OK, item_error=True)
        capture('http_short_html', extra_js=no_ice, item_html='<title>x</title>')
        state['cdp_port'] = None
        capture('http_without_cookies', extra_js=no_ice, item_html=HTML_OK)
        state['cdp_port'] = 9401
        capture('dom_only_no_sku', extra_js=no_ice[:1] + dom[:3] + [('skuOptionsArea', {'groups': []})])
        capture('dom_only_no_title', extra_js=no_ice[:1] + [('var selectors = ["', ''), ('parsePriceText', 0), ('function cleanList', {'main': [], 'detail': []}),
                                                           ('skuOptionsArea', DOM_GROUPS)])
        capture('dom_without_sku_needed', {'extract_sku': False}, extra_js=no_ice[:1] + dom[:3])
        capture('mtop_cache_fills_gaps', mtop_cache={'555000': {'title': '缓存标题', 'image': '//img.alicdn.com/c.jpg', 'soldCount': '1000+'}},
                extra_js=[('__ICE_APP_CONTEXT__', json.dumps({'error': 'x'})), ('var selectors = ["', ''), ('parsePriceText', 0), ('function cleanList', None),
                          ('skuOptionsArea', DOM_GROUPS)])
        capture('ice_without_variants', extra_js=[('__ICE_APP_CONTEXT__', ICE_PLAIN)] + dom[:3])
        capture('attributes_invalid', extra_js=[('__ICE_APP_CONTEXT__', ICE_JSON)] + dom, attrs='not a dict')
        capture('detail_images_from_browser', extra_js=[('var sels = [', CDN_URLS)] + [('__ICE_APP_CONTEXT__', ICE_JSON)] + dom)
        out['mtop_cache'] = sorted(S.mtop_cache_of(ctx))
    finally:
        taobao_capture.download_assets = real_download
        S.mtop_cache_of(ctx).clear()
        S.set_cookie_state(ctx, '', 0.0)
    drain(ctx, out, 'drained')
    return out


# ------------------------------------------------------------------------------------------ 属性 / 端口选择 / 入库
def attributes_ports_import(ctx):
    out = {}
    f = lambda name: S.fn(ctx, name)           # noqa: E731
    state = ctx.state
    envelope = {'version': 1, 'source': 'visible_product_parameters_v1', 'status': 'captured', 'attributes': [{'name': '材质', 'value': '纯棉'}]}
    empty = {'version': 1, 'source': 'visible_product_parameters_v1', 'status': 'not_found', 'attributes': []}
    for label, attrs, options in (('captured', envelope, {}), ('not_found', empty, {'extract_params': True}),
                                  ('disabled', envelope, {'extract_params': False}), ('invalid', 'oops', {}), ('bad_source', dict(envelope, source='x'), {})):
        value = {}
        call(out, 'product_attributes_' + label, lambda: (f('_capture_product_attributes')(page_with(ctx, attrs=attrs), value, options), value)[1])

    profile = f('_get_capture_browser_user_data_path')()
    out['profile_tail'] = os.path.relpath(profile, ctx.data_dir).replace('\\', '/')

    def browser(port, profile_dir=profile, host='127.0.0.1'):
        return {'debug_address': '%s:%s' % (host, port), 'user_data_dir': profile_dir}
    select = f('_select_capture_browser_port')
    cases = [
        ('free_first', [], {'ok': True}, set()),
        ('own_browser', [browser(9402)], {'ok': True}, set()),
        ('own_browser_localhost', [browser(9403, host='localhost')], {'ok': True}, set()),
        ('own_browser_unverified', [browser(9402)], {'ok': False, 'error': '[WinError 10048] busy'}, set()),
        ('own_browser_unverified_no_error', [browser(9402)], {'ok': False}, set()),
        ('other_profile', [browser(9400, 'other')], {'ok': True}, set()),
        ('no_profile', [browser(9400, '')], {'ok': True}, set()),
        ('bad_addresses', [{'debug_address': 'junk'}, {'debug_address': '127.0.0.1:abc'}, {'debug_address': '127.0.0.1:70000'},
                           {'debug_address': '10.0.0.1:9400'}, {'debug_address': ''}, {}], {'ok': True}, set()),
        ('occupied_by_others', [browser(9400, 'x'), browser(9401, 'y')], {'ok': True}, set()),
        ('ports_busy', [], {'ok': True}, {9400, 9401, 9405}),
        ('all_busy', [], {'ok': True}, set(range(9400, 9500))),
    ]
    for label, browsers, verification, occupied in cases:
        state['browsers'], state['verification'], state['occupied'] = browsers, verification, occupied
        call(out, 'port_' + label, select)
    state['browsers'], state['verification'], state['occupied'] = [], {'ok': True}, set()

    # ---- 入库（真实数据库）----
    record_model = ctx.Record
    root = make_product_dir(ctx, '9001', ('白色 _ 均码', '灰色 _ 均码'))
    product = product_for(ctx, '9001', root)
    importer = f('_import_capture_product_record')
    call(out, 'import_ok', importer, product)
    call(out, 'import_again_replaces', importer, dict(product, title='新标题 长筒'))
    out['records'] = [{'name': r.name, 'title': r.title, 'clazz': r.clazz, 'status': r.status, 'type': r.type,
                       'source': r.import_source, 'managed': r.managed_files, 'attrs': r.captured_attributes} for r in record_model.select()]
    from datetime import datetime
    record_model.create(name='ID-9001', path=os.path.normpath(root), type=2, status=0, repo=1, title='重复', clazz=2, content='[]',
                        remark='', update_time=datetime(2026, 1, 1))
    call(out, 'import_duplicate_history', importer, product)
    record_model.delete().where(record_model.title == '重复').execute()
    call(out, 'import_no_path', importer, dict(product, download_path=''))
    call(out, 'import_missing_dir', importer, dict(product, download_path=os.path.join(root, 'nope')))
    call(out, 'import_bad_attributes', importer, dict(product, captured_attributes={'version': 2}))
    call(out, 'import_missing_sku_image', importer, dict(product, sku_info=product['sku_info'] + [{'name': '粉色 / 均码', 'index': 3}]))
    record_model.delete().execute()

    # ---- 店铺任务函数直接调用：任务不存在 ----
    call(out, 'store_capture_unknown_task', f('_run_taobao_tmall_store_capture'), page_with(ctx), 'no-such-task', S.URL_STORE, {}, None)
    drain(ctx, out, 'drained')
    return out

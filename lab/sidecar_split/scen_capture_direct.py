# -*- coding: utf-8 -*-
"""链接采集：不经 HTTP 的直接调用对打（2026-10-20）。

路由层够不到的函数和分支（纯函数的各种输入、协议提取、cookie 缓存、端口选择、store 分页……）在这里逐个调用，
旧版调 app.py 里的原函数，新版调 helpers 里的函数 / 服务对象的方法；返回值（或异常的「类型: 文本」）必须逐字相同。
"""
import json
import os
import sys
import types
from types import SimpleNamespace

import scen_capture as S

ICE_JSON = json.dumps({
    'item': {'itemId': '555000', 'title': '纯棉中筒袜', 'images': ['//img.alicdn.com/main1.jpg', 'https://img.alicdn.com/main2.jpg'],
             'pcDescUrl': '//desc.taobao.com/desc/555000'},
    'skuBase': {'props': [{'pid': '1627207', 'name': '颜色', 'values': [
        {'vid': '28341', 'name': '白', 'image': '//img.alicdn.com/sku/w.jpg'}, {'vid': '28342', 'name': '灰'}]}],
        'skus': [{'skuId': '9001', 'propPath': '1627207:28341'}, {'skuId': '9002', 'propPath': '1627207:28342'}]},
    'skuCore': {'sku2info': {'0': {'price': {'priceMoney': '2080'}}, '9001': {'price': {'priceMoney': '2080'}},
                             '9002': {'price': {'priceMoney': '2280'}}}}}, ensure_ascii=False)
ICE_MISMATCH = ICE_JSON.replace('"itemId": "555000"', '"itemId": "123"')
ICE_PLAIN = json.dumps({'item': {'itemId': '555000', 'title': '无规格袜', 'images': ['//img.alicdn.com/p.jpg']},
                        'skuCore': {'sku2info': {'0': {'price': {'priceMoney': '1590'}}}}}, ensure_ascii=False)
DOM_GROUPS = {'groups': [{'name': '颜色', 'pid': '1', 'values': [
    {'name': '白', 'image': '//img.alicdn.com/s/w.jpg', 'vid': 'a', 'price': '9.9'},
    {'name': '灰', 'image': '//img.alicdn.com/s/g.jpg', 'vid': 'b', 'price': None}]}]}


def jsonable(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=repr))


def call(out, label, func, *args, **kwargs):
    try:
        out[label] = {'ok': jsonable(func(*args, **kwargs))}
    except BaseException as exc:                       # noqa: BLE001 —— 要把异常原样记录下来对比
        out[label] = {'error': '%s: %s' % (type(exc).__name__, exc)}


def page_with(ctx, **overrides):
    S.reset_behavior(ctx, **overrides)
    page = S.FakePage(ctx.state)
    ctx.state['page'] = page
    return page


def drain(ctx, out, key):
    log, downloads = S._drain(ctx)
    out[key] = {'log': log, 'downloads': downloads}


# ------------------------------------------------------------------------------------------ 纯函数
def pure_helpers(ctx):
    out = {}
    f = lambda name: S.fn(ctx, name)           # noqa: E731
    urls = ['https://detail.1688.com/offer/1.html', 'http://DETAIL.TMALL.COM/item.htm?id=2', 'https://item.taobao.com/item.htm?id=3',
            'https://shop1.taobao.com/search.htm', 'https://shop12.tmall.com/', 'https://brand.tmall.com/',
            'https://store.taobao.com/shop/view_shop.htm', 'https://shop.m.taobao.com/x', 'https://www.taobao.com/',
            'detail.tmall.com/item.htm?id=4', 'https://example.com/', '', None, 'https://item.taobao.com/item_5.html',
            'https://detail.tmall.hk/item.htm?id=6', 'https://x.tmall.com/category.htm', 'https://x.taobao.com/y.htm?z=view_shop',
            'https://login.1688.com/a', 'https://login.alibaba.com/b', 'https://login.taobao.com/c', 'https://login.tmall.com/d',
            'https://detail.1688.com/offer/778899.html?id=1&offerId=2', 'https://x.1688.com/offer/55', 'https://x.1688.com/?offerId=66',
            'https://detail.tmall.hk/item.htm?from=tmall.com', 'https://item.taobao.hk/item.htm?x=taobao.com',
            'https://item.taobao.com/item.htm/view_shop?id=3',
            '//item.taobao.com/item.htm?id=1', '/relative/path/item.htm?id=2', 'https://x.tmall.com/detail?item_id=77']
    for name in ('_detect_capture_source_platform', '_is_1688_capture_url', '_is_taobao_tmall_capture_url', '_is_1688_login_url',
                 '_is_taobao_login_url', '_is_taobao_tmall_product_url', '_is_taobao_tmall_store_url',
                 '_extract_capture_product_id', '_extract_taobao_tmall_item_id', '_normalize_taobao_tmall_item_url'):
        for url in urls:
            call(out, '%s(%r)' % (name, url), f(name), url)
    for url in ('', 'https://item.taobao.com/item.htm?id=1', 'https://m.tb.cn/h.ok', 'https://m.tb.cn/h.bad', 'https://m.tb.cn/h.fail',
                '复制打开淘宝 https://detail.tmall.com/item.htm?id=9 ，'):
        call(out, '_resolve_capture_redirect_url(%r)' % url, f('_resolve_capture_redirect_url'), url)
    for value in (None, 3, 4.5, '¥12.5元', 'abc', '', '1,234.5'):
        call(out, '_parse_capture_price(%r)' % (value,), f('_parse_capture_price'), value)
    nested_cycle = {'a': []}
    nested_cycle['a'].append(nested_cycle)
    price_cases = [None, [], {}, {'price': '3.5'}, {'discountPrice': 2, 'price': 0}, {'promotionPrice': '¥7'},
                   {'x': {'finalPrice': 4}}, {'stockPrice': 9, 'list': [{'price': 8}]}, {'skuInfo': [1, 'a', {'currentPrice': '5.5'}]},
                   {'inventory': {'price': 1}}, {'a': {'b': {'c': {'d': {'e': {'price': 3}}}}}}, {'bookCount': 5, 'qtyPrice': 6},
                   {'priceTag': {'unit': 'x', 'priceValue': '12'}}, nested_cycle, {'x': 'price'}, {'priceText': '免费'},
                   {'priceList': [{'price': 8}]}, {'priceList': [1, 'a', {'currentPrices': [{'price': 0}], 'price': 0}, [{'priceBox': {'price': 6}}]]},
                   {'a': {'price': 0, '': 5, 'stockCount': 3, 'priceX': []}}, {'priceA': {'priceB': {'priceC': {'priceD': {'priceE': {'priceF': 5}}}}}},
                   {'priceList': [[], (), {'priceZero': 0}]}, {'priceBox': {'': 5, 'qty': 1}}]
    selfref = {'priceSelf': None}
    selfref['priceSelf'] = selfref
    price_cases.append(selfref)
    for index, case in enumerate(price_cases):
        call(out, '_extract_capture_price_from_mapping(#%d)' % index, f('_extract_capture_price_from_mapping'), case, 1.5)
    snapshots = [
        {}, {'sku_props': [{'prop': '颜色', 'value': [{'name': '红', 'imageUrl': '//x/r.jpg'}, {'name': '', 'image': 'a'},
                                                     {'name': '蓝', 'imgUrl': 'http://x/b.jpg'}, {'name': '绿', 'image': 'ftp://x'}]},
                            {'name': '尺码', 'value': [{'name': 'M'}]}, {'value': None}]},
        {'sku_props': [{'prop': '颜色', 'value': [{'name': '红', 'image': '//x/r.jpg'}]}],
         'sku_map': [{'specAttrs': '红&gt;L', 'skuId': 1, 'price': '3'}, {'specAttrs': '', 'specId': 2}, {'specAttrs': '红>XL>x', 'stock': 0}]},
        {'sku_map': [{'specAttrs': 'A', 'canBookCount': 7}]},
    ]
    for index, snap in enumerate(snapshots):
        for clean in (None, lambda u: u.upper(), lambda u: '', lambda u: (_ for _ in ()).throw(RuntimeError('x'))):
            call(out, '_build_1688_sku_info(case%d,%s)' % (index, 'fn' if clean else None), f('_build_1688_sku_info'), snap, clean, 4.5)
    chain_a = OSError('[WinError 10048] address in use')
    chain_b = RuntimeError('wrapped')
    chain_b.__cause__ = chain_a
    cyc = RuntimeError('cycle')
    cyc.__context__ = cyc
    winerr = OSError('x')
    winerr.winerror = 10055
    reasoned = RuntimeError('r')
    reasoned.reason = ValueError('[WinError 10024] too many')
    for label, exc in (('chain', chain_b), ('cycle', cyc), ('winerror', winerr), ('reason', reasoned), ('plain', ValueError('plain')),
                       ('text', RuntimeError('采集浏览器已启动：[WinError 10048] address in use')),
                       ('args', RuntimeError(OSError('[WinError 10024] limit'))), ('empty', Exception())):
        call(out, '_capture_failure_details(%s)' % label, f('_capture_failure_details'), exc)
    for task in (None, {}, {'status': 'failed'}, {'status': 'running'}, {'error_code': '1688_antibot_verification'},
                 {'error_code': 'login_timeout', 'status': 'failed'}, {'error_code': 'triggered_antibot_verification'},
                 {'error_code': 'capture_network_resources_exhausted', 'message': '资源不足'}, {'error_code': 'capture_network_resources_exhausted'}):
        call(out, '_capture_task_recovery_info(%r)' % (task,), f('_capture_task_recovery_info'), task)
    for title in (None, '', '船袜男', '短筒袜', '短袜子', '中筒', '长筒袜', '袜套', '连裤袜', 5):
        call(out, 'infer_clazz_from_title(%r)' % (title,), f('infer_clazz_from_title'), title)
    for env in (None, '5', 'abc', '1', '9999', '-3', ' 12 '):
        if env is None:
            os.environ.pop('CAPTURE_TEST_WAIT', None)
        else:
            os.environ['CAPTURE_TEST_WAIT'] = env
        call(out, '_capture_wait_seconds(%r)' % env, f('_capture_wait_seconds'), 'CAPTURE_TEST_WAIT', 50)
    os.environ.pop('CAPTURE_TEST_WAIT', None)
    call(out, '_infer_capture_image_ext', lambda: [f('_infer_capture_image_ext')(u, c) for u, c in (
        ('a.png', ''), ('a.GIF?x', ''), ('a.webp', ''), ('a.jpg', ''), ('', 'image/png'), ('x', 'image/gif'), ('x', 'IMAGE/WEBP'), (None, None))])
    call(out, '_append_query_params', lambda: [f('_append_query_params')(u, p) for u, p in (
        ('https://a.com/p?x=1', {'y': 2}), ('https://a.com/p', {'y': None, 'z': 'é'}), ('https://a.com/p?x=1&x=2', {'x': 3}))])
    for html in ('', 'abc', '<script>__ICE_APP_CONTEXT__ = 1</script>', 'x __ICE_APP_CONTEXT__ y var b = {"a": {"s": "}"}, "c": [1]} tail',
                 'x __ICE_APP_CONTEXT__ var b = {"a": "unterminated', 'x __ICE_APP_CONTEXT__ var b = {bad json}', '__ICE_APP_CONTEXT__ var b = {"q\\"x": 1}'):
        call(out, '_parse_ice_from_html(%r)' % html[:40], f('_parse_ice_from_html'), html)
    call(out, '_mtop_post_fetch', f('_mtop_post_fetch'), 'cookie=1', 'tok', '123', '456', 2, cat_id=3, keyword='袜')
    return out


def protocol_artifacts(ctx):
    out = {}
    f = lambda name: S.fn(ctx, name)           # noqa: E731
    engine = ctx.state['engine']
    S.set_dep(ctx, 'engine', None)
    call(out, 'start_without_engine', f('_start_protocol_capture_record'), source_url=S.URL_1688, task_id='t0', options={'a': 1}, product_id='1')
    S.set_dep(ctx, 'engine', engine)
    runs_before = len(engine.runs)
    call(out, 'start_ok', lambda: _runtime_view(f('_start_protocol_capture_record')(
        source_url='http://detail.tmall.com/item.htm?id=2', task_id='t1', options={'k': [1, 2]}, product_id='2')))
    engine.fail_build = True
    call(out, 'start_build_fails', f('_start_protocol_capture_record'), source_url=S.URL_1688, task_id='t2', options=None)
    engine.fail_build = False
    call(out, 'start_default_args', lambda: _runtime_view(f('_start_protocol_capture_record')(source_url='https://x.com/', task_id='t3')))
    out['engine_runs_added'] = len(engine.runs) - runs_before
    runtime = f('_start_protocol_capture_record')(source_url=S.URL_1688, task_id='t4', options={}, product_id='3')
    call(out, 'write_none_runtime', f('_write_protocol_capture_artifact_json'), None, 's', 'n', {'a': 1})
    call(out, 'write_ok', f('_write_protocol_capture_artifact_json'), runtime, 's', 'n', {'a': 1}, artifact_type='x')
    engine.fail_writes = True
    call(out, 'write_fails', f('_write_protocol_capture_artifact_json'), runtime, 's', 'n', {'a': 1})
    engine.fail_writes = False
    call(out, 'finalize_none_runtime', f('_finalize_protocol_capture_record'), None, task_id='t', source_url='u', status='s', progress=1, message='m')
    call(out, 'finalize_with_result', f('_finalize_protocol_capture_record'), runtime, task_id='t4', source_url='u', status='completed',
         progress=100, message='ok', result={'products': [1]})
    call(out, 'finalize_with_error', f('_finalize_protocol_capture_record'), runtime, task_id='t4', source_url='u', status='failed',
         progress=0, message='bad', error='E')
    out['engine'] = {'runs': engine.runs[runs_before:], 'writes': engine.writes[:]}
    engine.runs.clear()
    engine.writes.clear()
    return out


def _runtime_view(runtime):
    if runtime is None:
        return None
    return {'root': runtime['root'], 'keys': sorted(runtime), 'started': runtime['context'].started_at}


# ------------------------------------------------------------------------------------------ 本机代理检测（真实函数 + 假的 winreg / psutil）
def proxy_risk(ctx):
    out = {}
    real = S.REAL_PROXY_RISK[ctx.mode]
    saved = {name: sys.modules.get(name) for name in ('winreg', 'psutil')}

    def install(enable, server, procs, ifaces, stats, reg_error=None, psutil_error=None, stats_error=None):
        winreg = types.ModuleType('winreg')
        winreg.HKEY_CURRENT_USER = object()

        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def open_key(root, path):
            if reg_error:
                raise reg_error
            return Key()

        def query(key, name):
            value = {'ProxyEnable': enable, 'ProxyServer': server}[name]
            if value is FileNotFoundError:
                raise FileNotFoundError(name)
            return (value,)
        winreg.OpenKey, winreg.QueryValueEx = open_key, query
        sys.modules['winreg'] = winreg
        psutil = types.ModuleType('psutil')
        if psutil_error:
            psutil.process_iter = lambda attrs=None: (_ for _ in ()).throw(psutil_error)
        else:
            psutil.process_iter = lambda attrs=None: [SimpleNamespace(info={'name': n}) for n in procs]
        psutil.net_if_addrs = lambda: ifaces
        psutil.net_if_stats = (lambda: (_ for _ in ()).throw(stats_error)) if stats_error else (lambda: stats)
        sys.modules['psutil'] = psutil
    import socket
    v4 = SimpleNamespace(family=socket.AF_INET)
    v6 = SimpleNamespace(family=socket.AF_INET6)
    try:
        cases = {
            'nothing': dict(enable=0, server='', procs=['explorer.exe'], ifaces={'以太网': [v4]}, stats={}),
            'system_proxy': dict(enable=1, server='127.0.0.1:7897', procs=[], ifaces={}, stats={}),
            'system_proxy_no_server': dict(enable=1, server=FileNotFoundError, procs=[], ifaces={}, stats={}),
            'enable_missing': dict(enable=FileNotFoundError, server='', procs=[], ifaces={}, stats={}),
            'clash_and_tun_ipv4': dict(enable=0, server='', procs=['Clash.exe', 'verge-mihomo.exe', 'xray.exe', 'x.exe', ''],
                                       ifaces={'Meta': [v4], 'Wi-Fi': [v4]}, stats={'Meta': SimpleNamespace(isup=False)}),
            'tun_isup_only': dict(enable=0, server='', procs=['sing-box'], ifaces={'wintun0': [v6]}, stats={'wintun0': SimpleNamespace(isup=True)}),
            'tun_down': dict(enable=0, server='', procs=[], ifaces={'tap1': [v6]}, stats={'tap1': SimpleNamespace(isup=False)}),
            'registry_error': dict(enable=0, server='', procs=['mihomo'], ifaces={}, stats={}, reg_error=OSError('no registry')),
            'stats_error': dict(enable=0, server='', procs=['clash'], ifaces={}, stats={}, stats_error=RuntimeError('no stats')),
            'psutil_error': dict(enable=1, server='s', procs=[], ifaces={}, stats={}, psutil_error=RuntimeError('no psutil')),
        }
        for label, kwargs in cases.items():
            install(**kwargs)
            call(out, label, real)
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return out


# ------------------------------------------------------------------------------------------ 页面相关的提取函数
def page_extractors(ctx):
    out = {}
    f = lambda name: S.fn(ctx, name)           # noqa: E731
    snapshot = {'title': 'x'}
    call(out, 'snapshot_1688_dict', f('_extract_1688_context_snapshot'), page_with(ctx, snapshot=snapshot))
    call(out, 'snapshot_1688_none', f('_extract_1688_context_snapshot'), page_with(ctx, snapshot=None))
    call(out, 'snapshot_1688_error', f('_extract_1688_context_snapshot'), page_with(ctx, snapshot=RuntimeError('js error')))
    for label, antibot in (('true', [True]), ('false', [False]), ('none', [None]), ('error', [RuntimeError('js boom')])):
        call(out, 'antibot_' + label, f('_is_1688_antibot_page'), page_with(ctx, antibot=antibot))
    for url in ('', '  ', 'https://detail.1688.com/desc/1', 'https://img.alicdn.com/desc/broken', 'https://x.com/other'):
        call(out, '1688_detail_images(%r)' % url, f('_collect_1688_detail_images'), url)
    sel = [('text', ' 标题 '), ('empty', ''), ('none', None), ('error', RuntimeError('x'))]
    for label, value in sel:
        call(out, 'text_by_selectors_' + label, f('_extract_text_by_selectors'),
             page_with(ctx, extra_js=[('var selectors = ["', value)]), ['h1', '.t'])
    for label, run in (('json_string', ICE_JSON), ('json_plain', ICE_PLAIN), ('dict', json.loads(ICE_JSON)), ('error', json.dumps({'error': 'no_ice_data'})),
                       ('mismatch', ICE_MISMATCH), ('none', None)):
        call(out, 'ice_' + label, f('_extract_taobao_ice_data'),
             page_with(ctx, start_url='https://item.taobao.com/item.htm?id=555000', extra_js=[('__ICE_APP_CONTEXT__', run)]))
    call(out, 'ice_bad_sku', f('_extract_taobao_ice_data'), page_with(ctx, start_url=S.URL_TAOBAO, extra_js=[(
        '__ICE_APP_CONTEXT__', json.dumps({'item': {'title': 'x'}, 'skuBase': {'props': [{'pid': '1', 'name': 'a', 'values': []}], 'skus': [{'skuId': '1', 'propPath': 'x:y'}]}}))]))
    drain(ctx, out, 'drained')
    return out


# ------------------------------------------------------------------------------------------ CDP / cookies / mtop
def cdp_and_mtop(ctx):
    out = {}
    f = lambda name: S.fn(ctx, name)           # noqa: E731
    state = ctx.state
    call(out, 'cdp_cookies_ok', f('_cdp_get_cookies_and_token'), 9401)
    S.reset_behavior(ctx, targets=[])
    call(out, 'cdp_cookies_no_targets', f('_cdp_get_cookies_and_token'), 9402)
    S.reset_behavior(ctx, targets=[{'type': 'page', 'url': 'https://www.baidu.com', 'webSocketDebuggerUrl': 'ws://127.0.0.1:9402/p'}])
    call(out, 'cdp_cookies_non_taobao_target', f('_cdp_get_cookies_and_token'), 9402)
    S.reset_behavior(ctx, targets=[{'type': 'page', 'url': 'https://x', 'webSocketDebuggerUrl': 'ws://fail/p'}])
    call(out, 'cdp_cookies_ws_fail', f('_cdp_get_cookies_and_token'), 9402)
    S.reset_behavior(ctx, ws_bad_ids=True)
    call(out, 'cdp_cookies_reply_timeout', f('_cdp_get_cookies_and_token'), 9402)
    S.reset_behavior(ctx)
    call(out, 'cdp_cookies_urlopen_fail', f('_cdp_get_cookies_and_token'), 9411)
    drain(ctx, out, 'drained_cdp')

    # ---- 浏览器 cookie 缓存（带 60 秒有效期的服务状态）----
    clock = state['clock']
    clock.now = 5000.0
    S.set_cookie_state(ctx, '', 0.0)
    state['cdp_port'] = None
    call(out, 'cookies_no_port', f('_get_browser_cookies_for_http'))
    state['cdp_port'] = 9401
    S.reset_behavior(ctx)
    call(out, 'cookies_fetch', f('_get_browser_cookies_for_http'))
    out['cookie_state_after_fetch'] = list(S.cookie_state(ctx))
    call(out, 'cookies_cached', f('_get_browser_cookies_for_http'))
    clock.now += 59
    call(out, 'cookies_cached_59s', f('_get_browser_cookies_for_http'))
    clock.now += 2
    S.reset_behavior(ctx, cookies=[{'domain': '.tmall.com', 'name': 'a', 'value': 'b'}])
    call(out, 'cookies_expired_refetch', f('_get_browser_cookies_for_http'))
    out['cookie_state_after_refetch'] = list(S.cookie_state(ctx))
    S.set_cookie_state(ctx, '', 0.0)
    S.reset_behavior(ctx, targets=[{'type': 'service_worker', 'url': 'x'}])
    call(out, 'cookies_no_page_target', f('_get_browser_cookies_for_http'))
    S.reset_behavior(ctx, targets=[{'type': 'page', 'url': 'x', 'webSocketDebuggerUrl': 'ws://fail/p'}])
    call(out, 'cookies_ws_fail', f('_get_browser_cookies_for_http'))
    S.reset_behavior(ctx, ws_bad_ids=True)
    call(out, 'cookies_reply_timeout', f('_get_browser_cookies_for_http'))
    S.reset_behavior(ctx)
    drain(ctx, out, 'drained_cookies')

    # ---- mtop 店铺商品分页 ----
    S.mtop_cache_of(ctx).clear()
    item = lambda i, **kw: dict({'itemId': i, 'title': 'T' + i, 'image': '//img/%s.jpg' % i, 'discountPrice': '9.9', 'priceEncoded': False,       # noqa: E731
                                 'vagueSold365': '100+', 'itemUrl': '//item.taobao.com/item.htm?id=' + i,
                                 'itemSkuUrl': 'u', 'skuInfoList': [{'skuId': 1, 'skuImageUrl': 'i', 'itemSkuUrl': 'u', 'skuPropertyText': '红'}]}, **kw)
    ok_page_1 = json.dumps({'ret': ['SUCCESS::ok'], 'data': {'data': [item('1'), item('2'), item('1'), {'title': 'noid'}], 'totalCnt': 3, 'hasNext': True}})
    ok_page_2 = json.dumps({'ret': ['SUCCESS::ok'], 'data': {'data': [item('3', itemUrl='')], 'totalCnt': 3, 'hasNext': False}})
    shop = {'shopId': '123', 'sellerId': '456'}

    def next_page(page, script):
        if not state['mtop_pages']:
            return ''
        value = state['mtop_pages'].pop(0)
        return value() if callable(value) else value

    def mtop(pages, **overrides):
        state['mtop_pages'] = list(pages)
        shop_info = overrides.pop('shop', shop)
        return page_with(ctx, extra_js=[('var gc = window.g_config', shop_info), ('fetch(', next_page)], **overrides)
    call(out, 'mtop_two_pages', f('_collect_store_products_via_mtop'), mtop([ok_page_1, ok_page_2]), 100)
    out['mtop_cache_keys'] = sorted(S.mtop_cache_of(ctx))
    S.mtop_cache_of(ctx).clear()
    call(out, 'mtop_max_products', f('_collect_store_products_via_mtop'), mtop([ok_page_1, ok_page_2]), 1)
    S.mtop_cache_of(ctx).clear()
    call(out, 'mtop_errors_then_ok', f('_collect_store_products_via_mtop'), mtop(['ERROR: x', '', 'not json', ok_page_2]))
    S.mtop_cache_of(ctx).clear()
    S.mtop_cache_of(ctx).clear()
    call(out, 'mtop_bad_json_then_ok', f('_collect_store_products_via_mtop'), mtop(['not json', ok_page_2]))
    S.mtop_cache_of(ctx).clear()
    call(out, 'mtop_three_errors', f('_collect_store_products_via_mtop'), mtop(['ERROR: a', 'ERROR: b', 'ERROR: c', ok_page_2]))
    bad_ret = json.dumps({'ret': ['FAIL_SYS_TOKEN_EMPTY::x'], 'data': {}})
    plain_ret = json.dumps({'ret': ['FAIL::other'], 'data': {}})
    call(out, 'mtop_token_refresh', f('_collect_store_products_via_mtop'), mtop([bad_ret, ok_page_2]))
    S.mtop_cache_of(ctx).clear()
    S.mtop_cache_of(ctx).clear()
    # 第一次拿到 token，服务端说 token 失效后，刷新 cookies 时已经拿不到 token
    call(out, 'mtop_token_refresh_fails', f('_collect_store_products_via_mtop'),
         mtop([lambda: (state['behavior'].__setitem__('cookies', []), bad_ret)[1], ok_page_2]), 100)
    S.reset_behavior(ctx)
    S.mtop_cache_of(ctx).clear()
    call(out, 'mtop_plain_failures', f('_collect_store_products_via_mtop'), mtop([plain_ret, plain_ret, plain_ret]))
    call(out, 'mtop_empty_items', f('_collect_store_products_via_mtop'), mtop([json.dumps({'ret': ['SUCCESS'], 'data': {'data': [], 'hasNext': True}})]))
    call(out, 'mtop_no_shop_info', f('_collect_store_products_via_mtop'), mtop([ok_page_1], shop=None))
    call(out, 'mtop_no_shop_id', f('_collect_store_products_via_mtop'), mtop([ok_page_1], shop={'shopId': '', 'sellerId': '1'}))
    call(out, 'mtop_js_error', f('_collect_store_products_via_mtop'), mtop([ok_page_1], shop=RuntimeError('js died')))
    state['cdp_port'] = None
    call(out, 'mtop_no_cdp_port', f('_collect_store_products_via_mtop'), mtop([ok_page_1]))
    state['cdp_port'] = 9401
    call(out, 'mtop_no_token', f('_collect_store_products_via_mtop'),
         mtop([ok_page_1], cookies=[{'domain': '.taobao.com', 'name': 'cna', 'value': 'v'}]))
    S.reset_behavior(ctx)

    # ---- 店铺商品链接 ----
    S.mtop_cache_of(ctx).clear()
    page = mtop([ok_page_1, ok_page_2])
    page._url = 'about:blank'
    call(out, 'store_urls_navigates', f('_collect_taobao_tmall_store_product_urls'), page, 'shop123.taobao.com/search.htm')
    page = mtop([ok_page_1, ok_page_2])
    page._url = 'https://shop123.taobao.com/'
    S.mtop_cache_of(ctx).clear()
    call(out, 'store_urls_already_there', f('_collect_taobao_tmall_store_product_urls'), page, 'https://shop123.taobao.com/search.htm', 2)
    page = mtop([ok_page_1, ok_page_2])
    page._url = 'about:blank'
    page.state['behavior']['get_errors'] = {'tmall': RuntimeError('nav failed')}
    S.mtop_cache_of(ctx).clear()
    call(out, 'store_urls_tmall_nav_fails', f('_collect_taobao_tmall_store_product_urls'), page, 'https://shop9.tmall.com/')
    fake_items = [{'itemId': '1', 'itemUrl': '//item.taobao.com/item.htm?id=1'}, {'itemId': '1', 'itemUrl': 'dup'}, {'title': 'noid'},
                  {'itemId': '2', 'itemUrl': 'item.taobao.com/item.htm?id=2'}, {'itemId': '3', 'itemUrl': 'https://item.taobao.com/item.htm?id=3'},
                  {'itemId': '4'}, {'itemId': '5', 'itemUrl': '  '}]
    page = page_with(ctx, start_url='https://shop1.tmall.com/')
    S.patch_fn(ctx, '_collect_store_products_via_mtop', lambda page, max_products=1000: list(fake_items))   # page_with 会还原替换，所以放在它后面
    call(out, 'store_urls_item_variants_tmall', f('_collect_taobao_tmall_store_product_urls'), page, 'https://shop1.tmall.com/', 4)
    page = page_with(ctx, start_url='https://shop1.taobao.com/')
    S.patch_fn(ctx, '_collect_store_products_via_mtop', lambda page, max_products=1000: list(fake_items))
    call(out, 'store_urls_item_variants_taobao', f('_collect_taobao_tmall_store_product_urls'), page, 'shop1.taobao.com')
    S.restore_patches(ctx)
    call(out, 'store_urls_nothing', f('_collect_taobao_tmall_store_product_urls'), mtop([], shop=None), 'https://shop1.taobao.com/')
    S.mtop_cache_of(ctx).clear()
    drain(ctx, out, 'drained_mtop')
    out['sleeps'] = list(state['clock'].sleeps)
    return out


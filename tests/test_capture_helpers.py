# -*- coding: utf-8 -*-
"""链接采集的无状态函数（src/sidecar/capture_helpers.py）。

这些函数是 2026-10-20 从 app.py 原样搬出来的，搬迁前后的输出由新旧对打（lab/sidecar_split/scen_capture*.py）逐字比对过；
这里把它们当前的行为钉成测试，之后拆 ``start_capture`` / 改提取逻辑时靠它们兜底。
断言来自对现有实现的实测，属于「特征化测试」：改了行为就要有意识地改断言。
"""
import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from capture_test_support import capture_helpers as h

PRODUCT_1688 = 'https://detail.1688.com/offer/123456.html?spm=a'


# ------------------------------------------------------------------------------------------ URL 识别
@pytest.mark.parametrize('url,platform,is_product,is_store', [
    (PRODUCT_1688, '1688', False, False),
    ('http://DETAIL.TMALL.COM/item.htm?id=2', 'tmall', True, False),
    ('https://item.taobao.com/item.htm?id=3', 'taobao', True, False),
    ('https://item.taobao.com/item.htm/view_shop?id=3', 'taobao', True, False),         # 路径里有 view_shop 的商品页也不是店铺页
    ('https://shop1.taobao.com/search.htm', 'taobao', False, True),
    ('https://brand.tmall.com/', 'tmall', False, True),
    ('https://x.tmall.com/category.htm', 'tmall', False, True),
    ('https://store.taobao.com/shop/view_shop.htm', 'taobao', False, True),
    ('https://www.taobao.com/', 'taobao', False, False),
    ('https://example.com/', 'unknown', False, False),
    ('', 'unknown', False, False),
])
def test_url_classification(url, platform, is_product, is_store):
    assert h._detect_capture_source_platform(url) == platform
    assert h._is_taobao_tmall_product_url(url) is is_product
    assert h._is_taobao_tmall_store_url(url) is is_store


def test_product_pages_are_never_mistaken_for_store_pages():
    # 商品详情页必须排除，否则会破坏现有单品采集
    assert h._is_taobao_tmall_store_url('https://item.taobao.com/item.htm?id=3') is False
    assert h._is_taobao_tmall_store_url('https://detail.tmall.com/item.htm?id=2') is False


def test_login_pages_belong_to_their_own_platform():
    assert h._is_1688_login_url('https://login.1688.com/a') and h._is_1688_login_url('https://login.alibaba.com/b')
    assert not h._is_1688_login_url('https://login.taobao.com/c')
    assert h._is_taobao_login_url('https://login.taobao.com/c') and h._is_taobao_login_url('https://login.tmall.com/d')
    assert not h._is_taobao_login_url('https://login.1688.com/a')
    assert h._is_1688_capture_url(PRODUCT_1688) and not h._is_1688_capture_url('https://item.taobao.com/x')
    assert h._is_taobao_tmall_capture_url('https://detail.tmall.com/x') and not h._is_taobao_tmall_capture_url(PRODUCT_1688)


def test_product_id_comes_from_the_url_and_falls_back_to_the_clock(monkeypatch):
    assert h._extract_capture_product_id(PRODUCT_1688) == '123456'
    assert h._extract_capture_product_id('https://detail.tmall.com/item.htm?id=2') == '2'
    assert h._extract_capture_product_id('https://x.1688.com/?offerId=66') == '66'
    monkeypatch.setattr(h.system_time, 'time', lambda: 1800000000.9)
    assert h._extract_capture_product_id('https://example.com/') == 'product_1800000000'


def test_item_id_helpers_for_store_pages():
    assert h._extract_taobao_tmall_item_id('https://x/item_88.html') == '88'
    assert h._normalize_taobao_tmall_item_url('//item.taobao.com/item.htm?id=9&x=1') == 'https://item.taobao.com/item.htm?id=9'
    assert h._normalize_taobao_tmall_item_url('/relative/item.htm?id=2') == ''
    assert h._normalize_taobao_tmall_item_url('https://other.com/item.htm?id=2') == ''


# ------------------------------------------------------------------------------------------ 短链
class _Resp:
    def __init__(self, url):
        self.url = url
        self.closed = False

    def close(self):
        self.closed = True


def test_non_short_links_are_only_normalized(monkeypatch):
    monkeypatch.setattr('requests.get', Mock(side_effect=AssertionError('不该联网')))
    assert h._resolve_capture_redirect_url('') == ('', '')
    assert h._resolve_capture_redirect_url('https://item.taobao.com/item.htm?id=1&spm=a') == ('https://item.taobao.com/item.htm?id=1&spm=a', '')


def test_short_link_resolves_to_a_supported_host(monkeypatch):
    response = _Resp('https://item.taobao.com/item.htm?id=555')
    monkeypatch.setattr('requests.get', Mock(return_value=response))
    final, short = h._resolve_capture_redirect_url('https://m.tb.cn/h.abc')
    assert (final, short) == ('https://item.taobao.com/item.htm?id=555', 'https://m.tb.cn/h.abc') and response.closed


def test_short_link_failures_are_reported_in_chinese(monkeypatch):
    monkeypatch.setattr('requests.get', Mock(side_effect=OSError('timeout')))
    with pytest.raises(ValueError, match='解析淘宝短链失败：timeout'):
        h._resolve_capture_redirect_url('https://m.tb.cn/h.abc')
    monkeypatch.setattr('requests.get', Mock(return_value=_Resp('https://evil.example.com/x')))
    with pytest.raises(ValueError, match='域名不受支持：evil.example.com'):
        h._resolve_capture_redirect_url('https://m.tb.cn/h.abc')


# ------------------------------------------------------------------------------------------ 价格 / 1688 SKU
@pytest.mark.parametrize('value,expected', [(None, 0.0), (3, 3.0), (4.5, 4.5), ('¥12.5元', 12.5), ('abc', 0.0), ('', 0.0)])
def test_parse_capture_price(value, expected):
    assert h._parse_capture_price(value) == expected


@pytest.mark.parametrize('item,expected', [
    ({'price': '3.5'}, 3.5),
    ({'discountPrice': 2, 'price': 0}, 2.0),                 # 优先键里第一个大于 0 的
    ({'priceList': [{'price': 8}]}, 8.0),                    # 带 price 字样的嵌套键可以往里找
    ({'stockPrice': 9}, 1.5),                                # 库存 / 数量类的键不算价格，取默认值
    ({'a': {'priceX': 5}}, 1.5),                             # 不带 price 字样的外层键不往里找
    (None, 1.5), ({}, 1.5),
])
def test_extract_capture_price_from_mapping(item, expected):
    assert h._extract_capture_price_from_mapping(item, 1.5) == expected


def test_price_search_survives_cycles_and_deep_nesting():
    cyclic = {'priceSelf': None}
    cyclic['priceSelf'] = cyclic
    assert h._extract_capture_price_from_mapping(cyclic, 1.5) == 1.5
    deep = {'priceA': {'priceB': {'priceC': {'priceD': {'priceE': {'priceF': 5}}}}}}
    assert h._extract_capture_price_from_mapping(deep, 1.5) == 1.5          # 最多往下找 4 层


SNAPSHOT = {'sku_props': [{'prop': '颜色', 'value': [{'name': '红', 'imageUrl': '//x/r.jpg'}, {'name': '蓝'}]},
                          {'prop': '尺码', 'value': [{'name': 'M'}]}],
            'sku_map': [{'specAttrs': '红&gt;M', 'skuId': 1, 'price': '3', 'canBookCount': 7}, {'specAttrs': '', 'specId': 2}]}


def test_1688_sku_info_from_the_sku_map():
    assert h._build_1688_sku_info(SNAPSHOT, None, 4.5) == [
        {'type': '颜色 / 尺码', 'name': '红 / M', 'vid': '1', 'image': 'https://x/r.jpg', 'price': 3.0, 'stock': 7, 'index': 1},
        {'type': '颜色 / 尺码', 'name': 'SKU2', 'vid': '2', 'image': '', 'price': 4.5, 'stock': None, 'index': 2},
    ]


def test_1688_sku_info_without_a_sku_map_lists_every_property_value():
    rows = h._build_1688_sku_info({'sku_props': SNAPSHOT['sku_props']}, None, 4.5)
    assert [(r['type'], r['name'], r['vid'], r['price']) for r in rows] == [
        ('颜色', '红', '1688_1', 4.5), ('颜色', '蓝', '1688_2', 4.5), ('尺码', 'M', '1688_3', 4.5)]
    assert rows[0]['image'] == 'https://x/r.jpg' and rows[1]['image'] == ''
    assert h._build_1688_sku_info({}, None, 4.5) == []


def test_1688_image_cleaner_falls_back_to_the_builtin_rule_only_when_it_is_missing_or_broken():
    def broken(url):
        raise RuntimeError('x')
    snapshot = {'sku_props': [{'prop': '颜色', 'value': [{'name': '红', 'imageUrl': '//x/r.jpg'}]}]}
    assert h._build_1688_sku_info(snapshot, None, 1.0)[0]['image'] == 'https://x/r.jpg'          # 没有清洗函数：内置规则补全协议
    assert h._build_1688_sku_info(snapshot, broken, 1.0)[0]['image'] == 'https://x/r.jpg'        # 清洗函数抛异常：同样回落
    assert h._build_1688_sku_info(snapshot, lambda url: '', 1.0)[0]['image'] == ''               # 清洗函数明确说「不要」就是不要
    assert h._build_1688_sku_info(snapshot, lambda url: url.upper(), 1.0)[0]['image'] == '//X/R.JPG'


def test_1688_detail_images_are_deduplicated_and_failures_are_empty(monkeypatch):
    page = SimpleNamespace(text='<img src="//cbu01.alicdn.com/a.jpg"> "https://img.tbcdn.com/b.png" <img src="//cbu01.alicdn.com/a.jpg">',
                           raise_for_status=lambda: None)
    monkeypatch.setattr('requests.get', Mock(return_value=page))
    assert h._collect_1688_detail_images('https://img.alicdn.com/desc/1.html') == [
        '//cbu01.alicdn.com/a.jpg', 'https://img.tbcdn.com/b.png']
    assert h._collect_1688_detail_images('  ') == []
    monkeypatch.setattr('requests.get', Mock(side_effect=OSError('down')))
    assert h._collect_1688_detail_images('https://img.alicdn.com/desc/1.html') == []


# ------------------------------------------------------------------------------------------ 任务状态
def test_failure_details_unwrap_hidden_socket_errors():
    inner = OSError('x')
    inner.winerror = 10055
    outer = RuntimeError('浏览器未启动')
    outer.__cause__ = inner
    details = h._capture_failure_details(outer)
    assert details['error_code'] == 'capture_network_resources_exhausted' and 'WinError 10055' in details['message']
    assert h._capture_failure_details(ValueError('plain')) == {'error_code': 'ValueError', 'message': '采集失败: plain'}


@pytest.mark.parametrize('task,can_retry,user_action,hint', [
    ({'status': 'failed'}, True, False, ''),
    ({'status': 'running'}, False, False, ''),
    ({'error_code': 'login_timeout'}, True, True, '请先在浏览器里完成平台登录，再点击重试采集。'),
    ({'error_code': '1688_antibot_verification'}, True, True, '请先在采集浏览器里完成 1688 访问验证，再点击重试采集。'),
    ({'error_code': 'triggered_antibot_verification'}, True, True, '请先在浏览器里完成平台安全验证，再点击重试采集。'),
    (None, False, False, ''),
])
def test_recovery_info(task, can_retry, user_action, hint):
    assert h._capture_task_recovery_info(task) == {'can_retry': can_retry, 'user_action_required': user_action, 'action_hint': hint}


def test_wait_seconds_are_read_from_the_environment_and_clamped(monkeypatch):
    for raw, expected in (('5', 5), ('abc', 50), ('1', 2), ('9999', 600), ('-3', 2), (None, 50)):
        if raw is None:
            monkeypatch.delenv('CAPTURE_TEST_WAIT', raising=False)
        else:
            monkeypatch.setenv('CAPTURE_TEST_WAIT', raw)
        assert h._capture_wait_seconds('CAPTURE_TEST_WAIT', 50) == expected


@pytest.mark.parametrize('title,clazz', [('船袜男', 0), ('短筒袜', 1), ('中筒', 2), ('长筒袜', 3), ('袜套', 4), ('连裤袜', 2), (None, 2), (5, 2)])
def test_infer_clazz_from_title(title, clazz):
    assert h.infer_clazz_from_title(title) == clazz


# ------------------------------------------------------------------------------------------ 协议采集产物
class _Store:
    def __init__(self, fail=False):
        self.writes, self.fail = [], fail

    def write_json(self, stage, name, payload, artifact_type='json'):
        if self.fail:
            raise OSError('disk full')
        self.writes.append((stage, name, artifact_type, payload))
        return name


def test_artifact_writing_never_raises():
    runtime = {'store': _Store(), 'root': '/r'}
    assert h._write_protocol_capture_artifact_json(None, 's', 'n', {}) is None
    assert h._write_protocol_capture_artifact_json(runtime, 's', 'n', {'a': 1}, artifact_type='x') == 'n'
    assert runtime['store'].writes == [('s', 'n', 'x', {'a': 1})]
    assert h._write_protocol_capture_artifact_json({'store': _Store(fail=True)}, 's', 'n', {}) is None


def test_finalizing_writes_a_summary_and_the_result_only_when_there_is_one():
    runtime = {'store': _Store(), 'root': '/r'}
    h._finalize_protocol_capture_record(runtime, task_id='t', source_url='u', status='failed', progress=0, message='m', error='E')
    h._finalize_protocol_capture_record(runtime, task_id='t', source_url='u', status='completed', progress=100, message='ok', result={'p': 1})
    h._finalize_protocol_capture_record(None, task_id='t', source_url='u', status='x', progress=1, message='m')
    stages = [(w[0], w[1]) for w in runtime['store'].writes]
    assert stages == [('session', 'task-summary'), ('session', 'task-summary'), ('import_manifest', 'capture-result')]
    summary = runtime['store'].writes[0][3]
    assert summary['error'] == 'E' and summary['artifact_root'] == '/r' and summary['status'] == 'failed'
    assert runtime['store'].writes[2][3] == {'p': 1}


def test_browser_profile_directory_follows_the_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('DOUYIN_DATA_DIR', str(tmp_path))
    path = h._get_capture_browser_user_data_path()
    assert path == str(tmp_path / 'capture-browser-profile') and (tmp_path / 'capture-browser-profile').is_dir()


# ------------------------------------------------------------------------------------------ 页面脚本的薄封装
def test_page_script_wrappers():
    assert h._extract_1688_context_snapshot(SimpleNamespace(run_js=lambda js: None)) == {}
    assert h._extract_1688_context_snapshot(SimpleNamespace(run_js=lambda js: {'title': 'x'})) == {'title': 'x'}
    assert h._is_1688_antibot_page(SimpleNamespace(run_js=lambda js: True)) is True
    assert h._is_1688_antibot_page(SimpleNamespace(run_js=lambda js: None)) is False
    broken = SimpleNamespace(run_js=Mock(side_effect=RuntimeError('boom')))
    assert h._is_1688_antibot_page(broken) is False                          # 读不出来就当不是验证页，不挡采集
    assert h._extract_text_by_selectors(SimpleNamespace(run_js=lambda js: ' 标题 '), ['h1']) == '标题'
    assert h._extract_text_by_selectors(broken, ['h1']) == ''


def test_ice_data_must_belong_to_the_current_product():
    ice = json.dumps({'item': {'itemId': '123', 'title': 'x'}, 'skuCore': {'sku2info': {'0': {'price': {'priceMoney': '1590'}}}}})
    page = SimpleNamespace(url='https://item.taobao.com/item.htm?id=555', run_js=lambda js: ice)
    with pytest.raises(ValueError, match='仍属于上一件商品'):
        h._extract_taobao_ice_data(page)
    page.url = 'https://item.taobao.com/item.htm?id=123'
    data = h._extract_taobao_ice_data(page)
    assert data['title'] == 'x' and data['price']['current'] == 15.9
    assert h._extract_taobao_ice_data(SimpleNamespace(url=page.url, run_js=lambda js: json.dumps({'error': 'no_ice_data'}))) is None


def test_ice_html_parser_reads_the_embedded_context():
    html = 'x __ICE_APP_CONTEXT__ y var b = {"a": {"s": "}"}, "c": [1]} tail'
    assert h._parse_ice_from_html(html) == {'a': {'s': '}'}, 'c': [1]}
    assert h._parse_ice_from_html('') == {} and h._parse_ice_from_html('__ICE_APP_CONTEXT__ var b = {bad json}') == {}


# ------------------------------------------------------------------------------------------ 本机代理检测
def _install_fake_system(monkeypatch, *, enable=0, server='', procs=(), ifaces=None, stats=None):
    winreg = types.ModuleType('winreg')
    winreg.HKEY_CURRENT_USER = object()

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False
    winreg.OpenKey = lambda root, path: Key()
    winreg.QueryValueEx = lambda key, name: ({'ProxyEnable': enable, 'ProxyServer': server}[name],)
    psutil = types.ModuleType('psutil')
    psutil.process_iter = lambda attrs=None: [SimpleNamespace(info={'name': name}) for name in procs]
    psutil.net_if_addrs = lambda: ifaces or {}
    psutil.net_if_stats = lambda: stats or {}
    monkeypatch.setitem(sys.modules, 'winreg', winreg)
    monkeypatch.setitem(sys.modules, 'psutil', psutil)


def test_proxy_risk_is_empty_without_any_sign(monkeypatch):
    _install_fake_system(monkeypatch, procs=['explorer.exe'])
    assert h._detect_local_proxy_risk() == ''


def test_proxy_risk_lists_every_sign_it_found(monkeypatch):
    import socket
    _install_fake_system(monkeypatch, enable=1, server='127.0.0.1:7897', procs=['Clash.exe', 'xray.exe'],
                         ifaces={'Meta': [SimpleNamespace(family=socket.AF_INET)]}, stats={'Meta': SimpleNamespace(isup=False)})
    text = h._detect_local_proxy_risk()
    assert '系统代理开启(127.0.0.1:7897)' in text and 'Clash/Mihomo' in text and 'xray' in text and 'TUN 虚拟网卡启用(Meta)' in text
    assert text.startswith('⚠️ 检测到本地代理可能导致登录二维码空白')


def test_proxy_risk_check_never_breaks_the_capture(monkeypatch):
    _install_fake_system(monkeypatch)
    monkeypatch.setitem(sys.modules, 'psutil', None)                          # import psutil 抛 ImportError
    assert h._detect_local_proxy_risk() == ''

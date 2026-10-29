# -*- coding: utf-8 -*-
"""采集服务（src/sidecar/capture_service.py）的状态与协议提取逻辑：cookie 缓存、mtop 分页、店铺批量采集循环、协议采集记录。

``CaptureService`` 的依赖都由构造函数注入，这里全部用假件；浏览器页面用 ``SimpleNamespace`` + 脚本应答。
新旧对打场景（lab/sidecar_split/scen_capture*.py）已经证明这些方法搬迁前后输出一致，这里把它们当前的行为钉下来，
之后拆 ``start_capture`` / 改提取逻辑时靠它们兜底。
"""
import json
import sys
import threading
import types
import urllib.request
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from capture_fake_world import FakeEngine
from capture_test_support import capture_service, make_service


class Clock:
    """虚拟时钟：sleep 只拨表不睡觉，记录每次睡了多久。"""

    def __init__(self, now=1000.0):
        self.now, self.sleeps = now, []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(capture_service, 'system_time', SimpleNamespace(time=fake.time, sleep=fake.sleep))
    return fake


# ------------------------------------------------------------------------------------------ 协议采集记录
def test_protocol_record_is_optional_and_never_breaks_a_capture(capsys):
    assert make_service(protocol_capture_engine=None).start_protocol_capture_record(source_url='u', task_id='t') is None
    assert capsys.readouterr().out == ''                                                # 没有引擎就是没有，不该当成「初始化失败」去刷日志
    engine = FakeEngine('/runs/1')
    runtime = make_service(protocol_capture_engine=engine).start_protocol_capture_record(
        source_url='https://detail.tmall.com/item.htm?id=2', task_id='t1', options={'k': [1]}, product_id='2')
    assert runtime['root'] == '/runs/1' and sorted(runtime) == ['context', 'root', 'store']
    assert engine.runs == [{'source_url': 'https://detail.tmall.com/item.htm?id=2', 'platform': 'tmall', 'product_id': '2'}]
    assert [w[:2] for w in engine.writes] == [('session', 'plan'), ('session', 'platform-profiles'), ('session', 'task-meta')]
    meta = engine.writes[-1][2]
    assert meta['task_id'] == 't1' and meta['options'] == {'k': [1]} and meta['source_platform'] == 'tmall'

    broken = SimpleNamespace(build_run_context=Mock(side_effect=RuntimeError('boom')))
    assert make_service(protocol_capture_engine=broken).start_protocol_capture_record(source_url='u', task_id='t') is None
    assert '协议化采集调试运行初始化失败，已跳过: boom' in capsys.readouterr().out


# ------------------------------------------------------------------------------------------ CDP cookies
class CDP:
    """假的 CDP：/json/list 返回标签页，websocket 对 Network.getAllCookies 回复 cookies。"""

    def __init__(self, monkeypatch, targets, cookies):
        self.targets, self.cookies, self.list_calls = targets, cookies, 0
        cdp = self

        class Body:
            def __init__(self, data):
                self.data = data

            def read(self):
                return self.data

        def urlopen(url, timeout=None):
            cdp.list_calls += 1
            return Body(json.dumps(cdp.targets).encode())
        monkeypatch.setattr(urllib.request, 'urlopen', urlopen)

        class WS:
            def __init__(self):
                self.pending = []

            def send(self, raw):
                self.pending.append(json.loads(raw))

            def recv(self):
                message = self.pending.pop(0)
                result = {'cookies': cdp.cookies} if message['method'] == 'Network.getAllCookies' else {}
                return json.dumps({'id': message['id'], 'result': result})

            def close(self):
                pass
        websocket = types.ModuleType('websocket')
        websocket.create_connection = lambda url, **kw: WS()
        monkeypatch.setitem(sys.modules, 'websocket', websocket)


PAGE_TARGET = {'type': 'page', 'url': 'https://item.taobao.com/item.htm?id=1', 'webSocketDebuggerUrl': 'ws://127.0.0.1:9401/p'}
COOKIES = [{'domain': '.taobao.com', 'name': '_m_h5_tk', 'value': 'tok123_999'}, {'domain': '.tmall.com', 'name': 'cna', 'value': 'abc'},
           {'domain': '.other.com', 'name': 'x', 'value': 'y'}, {'domain': '.taobao.com', 'name': '', 'value': 'novalue'}]


def test_cdp_cookies_and_mtop_token(monkeypatch):
    CDP(monkeypatch, [{'type': 'service_worker', 'url': 'x'}, PAGE_TARGET], COOKIES)
    header, token = make_service()._cdp_get_cookies_and_token(9401)
    assert header == '_m_h5_tk=tok123_999; cna=abc' and token == 'tok123'             # 只留淘宝 / 天猫域，token 取 _m_h5_tk 下划线前


def test_cdp_cookie_failures_return_empty_instead_of_raising(monkeypatch):
    service = make_service()
    CDP(monkeypatch, [], COOKIES)
    assert service._cdp_get_cookies_and_token(9401) == ('', '')
    monkeypatch.setattr(urllib.request, 'urlopen', Mock(side_effect=OSError('refused')))
    assert service._cdp_get_cookies_and_token(9401) == ('', '')


def test_browser_cookie_cache_lasts_sixty_seconds(monkeypatch, clock):
    cdp = CDP(monkeypatch, [PAGE_TARGET], COOKIES[:3])
    service = make_service(find_cdp_port=lambda: 9401)
    assert service._get_browser_cookies_for_http() == '_m_h5_tk=tok123_999; cna=abc'
    assert cdp.list_calls == 1 and service._browser_cookie_ts == clock.now
    clock.now += 59
    assert service._get_browser_cookies_for_http() == '_m_h5_tk=tok123_999; cna=abc' and cdp.list_calls == 1      # 缓存命中
    clock.now += 2
    cdp.cookies = [{'domain': '.tmall.com', 'name': 'a', 'value': 'b'}]
    assert service._get_browser_cookies_for_http() == 'a=b' and cdp.list_calls == 2                              # 过期重取


def test_browser_cookies_are_empty_without_a_debug_port_or_page(monkeypatch, clock):
    assert make_service(find_cdp_port=lambda: None)._get_browser_cookies_for_http() == ''
    CDP(monkeypatch, [{'type': 'service_worker', 'url': 'x'}], COOKIES)
    assert make_service(find_cdp_port=lambda: 9401)._get_browser_cookies_for_http() == ''


# ------------------------------------------------------------------------------------------ mtop 店铺商品分页
def item(item_id, **extra):
    return dict({'itemId': item_id, 'title': 'T' + item_id, 'image': '//img/%s.jpg' % item_id, 'discountPrice': '9.9',
                 'itemUrl': '//item.taobao.com/item.htm?id=' + item_id,
                 'skuInfoList': [{'skuId': 1, 'skuImageUrl': 'i', 'itemSkuUrl': 'u', 'skuPropertyText': '红'}]}, **extra)


def mtop_response(items, has_next=False, ret='SUCCESS::ok'):
    return json.dumps({'ret': [ret], 'data': {'data': items, 'totalCnt': len(items), 'hasNext': has_next}})


class MtopPage:
    def __init__(self, pages, shop=None):
        self.pages = list(pages)
        self.shop = {'shopId': '123', 'sellerId': '456'} if shop is None else shop

    def run_js(self, script, **kwargs):
        if 'fetch(' in script:
            return self.pages.pop(0) if self.pages else ''
        return self.shop


def mtop_service(monkeypatch, tokens=None):
    CDP(monkeypatch, [PAGE_TARGET], COOKIES)
    return make_service(find_cdp_port=lambda: 9401)


def test_mtop_pages_are_deduplicated_and_cached(monkeypatch, clock):
    service = mtop_service(monkeypatch)
    page = MtopPage([mtop_response([item('1'), item('2'), item('1'), {'title': '没有 id'}], has_next=True),
                     mtop_response([item('3', itemUrl='')])])
    products = service._collect_store_products_via_mtop(page, 100)
    assert [p['itemId'] for p in products] == ['1', '2', '3']
    assert products[0]['skuList'] == [{'skuId': '1', 'skuImageUrl': 'i', 'skuUrl': 'u', 'skuText': '红'}]
    assert sorted(service.mtop_product_cache) == ['1', '2', '3']                       # 单品采集会复用这份缓存
    assert clock.sleeps == [0.3]                                                       # 翻页之间只歇 0.3 秒


def test_mtop_respects_the_product_limit_and_gives_up_after_three_errors(monkeypatch, clock):
    service = mtop_service(monkeypatch)
    page = MtopPage([mtop_response([item('1'), item('2')], has_next=True), mtop_response([item('3')])])
    assert [p['itemId'] for p in service._collect_store_products_via_mtop(page, 1)] == ['1']
    service = mtop_service(monkeypatch)
    page = MtopPage(['ERROR: a', 'ERROR: b', 'ERROR: c', mtop_response([item('9')])])
    assert service._collect_store_products_via_mtop(page, 100) == []
    assert clock.sleeps[-2:] == [2, 2]


def test_mtop_refreshes_the_token_when_the_server_rejects_it(monkeypatch, clock):
    cdp = CDP(monkeypatch, [PAGE_TARGET], COOKIES)
    service = make_service(find_cdp_port=lambda: 9401)
    page = MtopPage([mtop_response([], ret='FAIL_SYS_TOKEN_EMPTY::x'), mtop_response([item('3')])])
    assert [p['itemId'] for p in service._collect_store_products_via_mtop(page, 100)] == ['3']
    assert cdp.list_calls == 2                                                          # 开头取一次 token，被服务端拒绝后重新取一次


def test_mtop_without_shop_info_or_debug_port_returns_nothing(monkeypatch, clock):
    service = mtop_service(monkeypatch)
    assert service._collect_store_products_via_mtop(MtopPage([mtop_response([item('1')])], shop={'shopId': ''}), 100) == []
    assert clock.sleeps == [5]                                                         # 读不到店铺 id 时等 5 秒再试一次
    no_port = make_service(find_cdp_port=lambda: None)
    assert no_port._collect_store_products_via_mtop(MtopPage([mtop_response([item('1')])]), 100) == []


def test_store_product_urls_follow_the_mtop_items(monkeypatch, clock):
    service = make_service()
    items = [{'itemId': '1', 'itemUrl': '//item.taobao.com/item.htm?id=1'}, {'itemId': '1', 'itemUrl': 'dup'}, {'title': '没有 id'},
             {'itemId': '2', 'itemUrl': 'item.taobao.com/item.htm?id=2'}, {'itemId': '3'}, {'itemId': '4', 'itemUrl': '  '}]
    monkeypatch.setattr(service, '_collect_store_products_via_mtop', lambda page, max_products=1000: list(items))
    page = SimpleNamespace(url='https://shop1.taobao.com/', get=Mock())
    assert service._collect_taobao_tmall_store_product_urls(page, 'shop1.taobao.com') == [
        'https://item.taobao.com/item.htm?id=1', 'https://item.taobao.com/item.htm?id=2',
        'https://item.taobao.com/item.htm?id=3', 'https://item.taobao.com/item.htm?id=4']
    page.get.assert_not_called()                                                        # 已经在店铺页，不重复导航
    page = SimpleNamespace(url='about:blank', get=Mock())
    urls = service._collect_taobao_tmall_store_product_urls(page, 'https://shop9.tmall.com/', 2)
    assert urls == ['https://item.taobao.com/item.htm?id=1', 'https://item.taobao.com/item.htm?id=2']       # 最多取 2 个
    page.get.assert_called_once_with('https://shop9.tmall.com/', timeout=25)
    monkeypatch.setattr(service, '_collect_store_products_via_mtop', lambda page, max_products=1000: [])
    assert service._collect_taobao_tmall_store_product_urls(SimpleNamespace(url='https://shop1.taobao.com/', get=Mock()), 'x') == []


# ------------------------------------------------------------------------------------------ 店铺批量采集循环
def store_service(monkeypatch, urls, outcomes, **kw):
    service = make_service(**kw)
    service.tasks['t'] = {'task_id': 't', 'status': 'running', 'progress': 0, 'message': ''}
    calls = []
    monkeypatch.setattr(service, '_collect_taobao_tmall_store_product_urls',
                        lambda page, store_url, max_products=1000, max_pages=50: (calls.append((max_products, max_pages)), list(urls))[1])

    def capture(page, url, options, mtop_cache=None):
        outcome = outcomes.get(url)
        if isinstance(outcome, BaseException):
            raise outcome
        return {'product_id': url[-1], 'sku_info': [1, 2], 'url': url}
    monkeypatch.setattr(service, 'capture_taobao_tmall_product_for_store', capture)
    return service, calls


def test_store_capture_collects_every_product_and_pauses_after_three_verifications(monkeypatch, clock):
    urls = ['http://s/%d' % i for i in range(1, 7)]
    outcomes = {urls[1]: Exception('触发验证'), urls[2]: Exception('PUNISH page'), urls[3]: Exception('跳转 sec.taobao.com'),
                urls[5]: Exception('其他错误')}
    service, calls = store_service(monkeypatch, urls, outcomes)
    service.run_taobao_tmall_store_capture(object(), 't', 'https://shop1.taobao.com/', {'request_interval_seconds': 1, 'max_store_products': 50,
                                                                                         'max_store_pages': 3}, None)
    task = service.tasks['t']
    assert calls == [(50, 3)]
    assert (task['status'], task['progress'], task['message']) == ('completed', 100, '店铺采集完成：成功 2 个，失败 4 个')
    result = task['result']
    assert result['capture_type'] == 'store' and result['sku_count'] == 4 and result['product_urls'] == urls
    assert [e['url'] for e in result['errors']] == [urls[1], urls[2], urls[3], urls[5]]
    assert clock.sleeps.count(30) == 1 and clock.sleeps.count(1.0) == 5                  # 连续 3 次验证后暂停 30 秒；其余每件之间歇 1 秒


def test_store_capture_failures_are_loud(monkeypatch, clock):
    service, _ = store_service(monkeypatch, [], {})
    with pytest.raises(Exception, match='未从店铺页面找到商品链接'):
        service.run_taobao_tmall_store_capture(object(), 't', 'https://shop1.taobao.com/', {}, None)
    service, _ = store_service(monkeypatch, ['http://s/1', 'http://s/2'], {'http://s/1': Exception('a'), 'http://s/2': Exception('b')})
    with pytest.raises(Exception, match='店铺商品采集全部失败，失败数量: 2'):
        service.run_taobao_tmall_store_capture(object(), 't', 'https://shop1.taobao.com/', {}, None)
    assert service.tasks['t']['status'] == 'running'                                   # 失败由调用方记到任务上，这里不偷偷改状态


def test_store_capture_stops_when_the_task_was_cancelled(monkeypatch, clock):
    service, _ = store_service(monkeypatch, ['http://s/1', 'http://s/2', 'http://s/3'], {})
    original = service.capture_taobao_tmall_product_for_store

    def cancel_after_first(page, url, options, mtop_cache=None):
        result = original(page, url, options, mtop_cache=mtop_cache)
        service.tasks['t']['status'] = 'failed'                                        # 用户取消
        return result
    monkeypatch.setattr(service, 'capture_taobao_tmall_product_for_store', cancel_after_first)
    service.run_taobao_tmall_store_capture(object(), 't', 'https://shop1.taobao.com/', {}, None)
    assert service.tasks['t']['status'] == 'failed' and 'result' not in service.tasks['t']


def test_store_capture_reuses_the_mtop_cache(monkeypatch, clock):
    service, _ = store_service(monkeypatch, ['http://s/1'], {})
    seen = []
    monkeypatch.setattr(service, 'capture_taobao_tmall_product_for_store',
                        lambda page, url, options, mtop_cache=None: (seen.append(mtop_cache), {'product_id': '1', 'sku_info': []})[1])
    service.run_taobao_tmall_store_capture(object(), 't', 'https://shop1.taobao.com/', {}, None)
    assert seen == [service.mtop_product_cache]

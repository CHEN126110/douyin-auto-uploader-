# -*- coding: utf-8 -*-
"""链接采集线程会碰到的「外部世界」的假件：DrissionPage、websocket、requests、urlopen、time.sleep。

测试用 ``FakeWorld().install(monkeypatch)`` 一次装好，用完 monkeypatch 自动还原。
``world.behavior`` 控制假标签页怎么应答；``world.gate`` 用来让采集线程在下一次 sleep 里挂起（做确定性的取消 / 互斥测试）。
"""
import json
import sys
import threading
import time
import types
import urllib.request
from types import SimpleNamespace
from urllib.error import URLError

from capture_test_support import capture_routes

PAGE_1688 = 'https://detail.1688.com/offer/123456.html'


def png_bytes():
    from io import BytesIO
    import random
    from PIL import Image
    image = Image.frombytes('L', (32, 32), random.Random(7).randbytes(32 * 32))      # 不可压缩的噪点：约 1KB，PIL 能校验
    buffer = BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()


class FakePage:
    """按 world.behavior 应答的假标签页；run_js 按脚本里的特征片段分派。"""

    def __init__(self, world):
        self.world = world
        self.tab_id = 'tab-1'
        self.url = world.behavior['start_url']

    def get(self, url, timeout=None):
        self.world.log.append(('page.get', url))
        self.url = url

    def add_init_js(self, script):
        self.world.log.append(('page.add_init_js',))

    def run_js(self, script, *args, **kwargs):
        behavior = self.world.behavior
        if '_____tmd_____' in script:
            return behavior['antibot']
        if 'return !!(window.context?.result?.global?.globalData?.model?.offerDetail?.subject)' in script:
            return True
        if "return { offer_id: String(od.offerId || '') }" in script:
            return behavior['ready']
        if 'flattenImages' in script:
            return behavior['snapshot']
        if 'visible_product_parameters_v1' in script:
            return behavior['attrs']
        return None


class FakeWorld:
    def __init__(self):
        self.log = []
        self.sleeps = []
        self.downloads = []
        self.gate = None                       # 设置后，采集线程的下一次 sleep 会挂起，直到 gate.set()
        self.entered = threading.Event()
        self.png = png_bytes()
        self.behavior = {
            'start_url': PAGE_1688,
            'antibot': False,
            'ready': {'offer_id': '123456'},
            'attrs': {'version': 1, 'source': 'visible_product_parameters_v1', 'status': 'captured',
                      'attributes': [{'name': '材质', 'value': '纯棉'}]},
            'snapshot': {
                'title': ' 儿童纯棉袜 ',
                'main_images': ['//cbu01.alicdn.com/img/a.jpg', 'https://cbu01.alicdn.com/img/b.png'],
                'current_prices': [{'price': '6.80'}],
                'sku_props': [{'prop': '颜色', 'value': [{'name': '白色', 'imageUrl': '//cbu01.alicdn.com/sku/white.jpg'},
                                                       {'name': '灰色', 'imageUrl': 'https://cbu01.alicdn.com/sku/gray.png'}]}],
                'sku_map': [{'specAttrs': '白色', 'skuId': 11, 'price': '6.80'}, {'specAttrs': '灰色', 'skuId': 12, 'price': '7.20'}],
                'detail_url': 'https://img.alicdn.com/desc/123456.html',
            },
        }

    def install(self, monkeypatch):
        world = self
        drission = types.ModuleType('DrissionPage')
        drission.ChromiumOptions = lambda: SimpleNamespace(**{name: (lambda *a, **k: None) for name in (
            'headless', 'set_paths', 'set_user', 'set_load_mode', 'set_user_agent', 'set_argument')})
        drission.ChromiumPage = lambda options: FakePage(world)
        monkeypatch.setitem(sys.modules, 'DrissionPage', drission)

        websocket = types.ModuleType('websocket')

        class WS:
            def settimeout(self, value):
                pass

            def send(self, raw):
                world.log.append(('ws.send', json.loads(raw).get('method')))

            def close(self):
                pass
        websocket.create_connection = lambda url, **kw: WS()
        monkeypatch.setitem(sys.modules, 'websocket', websocket)

        class Body:
            def __init__(self, data):
                self.data = data

            def read(self):
                return self.data

        def urlopen(target, timeout=None):
            url = getattr(target, 'full_url', target)
            if '/json/list' in url:
                return Body(json.dumps([{'type': 'page', 'id': 'tab-1',
                                         'webSocketDebuggerUrl': 'ws://127.0.0.1:9400/devtools/page/tab-1'}]).encode())
            raise URLError('refused')
        monkeypatch.setattr(urllib.request, 'urlopen', urlopen)
        monkeypatch.setattr(capture_routes, 'urlopen', urlopen)

        import requests

        class Response:
            def __init__(self, url, status=200, content=b'', text=''):
                self.url, self.status_code, self.content, self.text = url, status, content, text

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise requests.HTTPError('HTTP %d' % self.status_code)

            def close(self):
                pass

        class Session:
            def __init__(self):
                self.headers = {}

            def get(self, url, timeout=None):
                world.downloads.append(url)
                return Response(url, content=world.png)

        def get(url, **kwargs):
            world.log.append(('requests.get', url))
            return Response(url, text='<img src="//img.alicdn.com/d/1.jpg">')
        monkeypatch.setattr(requests, 'get', get)
        monkeypatch.setattr(requests, 'Session', Session)

        def sleep(seconds):
            world.sleeps.append(seconds)
            gate = world.gate
            if gate is not None and threading.current_thread() is not threading.main_thread():
                world.gate = None
                world.entered.set()
                gate.wait(15)
        monkeypatch.setattr(time, 'sleep', sleep)
        return self


class FakeEngine:
    """协议采集引擎：记录写入，不落盘。"""

    def __init__(self, root='/protocol-debug/run-1'):
        self.root, self.runs, self.writes = root, [], []

    def build_run_context(self, *, source_url, source_platform, product_id, metadata):
        self.runs.append({'source_url': source_url, 'platform': source_platform, 'product_id': product_id})
        engine = self
        store = SimpleNamespace(root=self.root, write_json=lambda stage, name, payload, artifact_type='json': engine.writes.append((stage, name, payload)))
        return SimpleNamespace(started_at='2026-01-01T00:00:00'), store

    def export_plan(self):
        return {'plan': True}

    def export_platform_profiles(self):
        return {'profiles': []}


def wait_until(predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    raise AssertionError('等待条件超时')

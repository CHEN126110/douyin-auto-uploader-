# -*- coding: utf-8 -*-
"""链接采集（/api/capture/*）的新旧对打场景（2026-10-20）。

走 app.py 自己的装配（``new_via_app=True``）：旧版用搬迁前的 app.py，新版用搬迁后的 app.py + src/sidecar/capture_*。
同一套假件、同一套请求，响应、任务字典、假件调用记录、落盘文件必须逐字相同。

假件（不连真实浏览器 / 网络）：
  - ``DrissionPage``：``sys.modules`` 里换成假模块（采集线程里是函数内延迟导入）；假页面按「行为表」应答 ``run_js`` / ``get`` / ``url``；
  - ``websocket`` / ``requests`` / ``urllib.request.urlopen``：假的，记录调用；图片下载走假 ``Session``；
  - 时间：``time.sleep`` / ``time.time`` 换成虚拟时钟（睡眠只拨表不真睡；每个启动请求前把表拨到固定值，任务 id 因此可预测）；
  - 协议采集引擎、采集浏览器端口探测、本机代理检测：按模式各自替换（旧版是 app.py 的全局，新版是服务对象 / 路由模块的属性）。
采集线程是后台线程：每个启动请求的 after 钩子等到线程结束再取快照，保证顺序确定。
"""
import hashlib
import json
import os
import sys
import threading
import time
import types
import urllib.request
from types import SimpleNamespace
from urllib.error import URLError

from scenarios import SCENARIOS
from slice_defs_capture import DEAD_FUNCS, HELPER_FUNCS, SERVICE_METHODS

REAL_TIME = time.time
REAL_SLEEP = time.sleep


def _png_bytes():
    from io import BytesIO
    from PIL import Image
    import random
    image = Image.frombytes('L', (32, 32), random.Random(7).randbytes(32 * 32))      # 不可压缩的噪点，PNG 约 1KB
    buffer = BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()


REAL_PROXY_RISK = {}                 # 模式 -> 真实的 _detect_local_proxy_risk（安装假件前先留一份，直接调用对打时用）
PNG_BYTES = _png_bytes()          # 约 1KB，大于下载逻辑里「小于 100 字节算占位图」的阈值，且 PIL 能校验
START_CLOCK = 1_800_000_000
HELPER_NAMES = set(HELPER_FUNCS) | set(DEAD_FUNCS)
WORKER = '_run_capture_task_with_lock_release'      # 采集后台线程的函数名（Python 3.10+ 会出现在线程名里）

PAGE_1688 = 'https://detail.1688.com/offer/123456.html'
URL_1688 = PAGE_1688 + '?spm=a.b'
URL_TAOBAO = 'https://item.taobao.com/item.htm?id=555000'
URL_TMALL = 'https://detail.tmall.com/item.htm?id=666000'
URL_STORE = 'https://shop123.taobao.com/search.htm'


# ---------------------------------------------------------------------------------------------- 模式无关的访问器
def _svc(ctx):
    return ctx.mod.capture_service


def tasks_of(ctx):
    return ctx.mod.capture_tasks if ctx.mode == 'old' else _svc(ctx).tasks


def lock_of(ctx):
    return ctx.mod._capture_lock if ctx.mode == 'old' else _svc(ctx).lock


def running_id(ctx):
    return ctx.mod._capture_running_task_id if ctx.mode == 'old' else _svc(ctx).running_task_id


def set_running_id(ctx, value):
    if ctx.mode == 'old':
        ctx.mod._capture_running_task_id = value
    else:
        _svc(ctx).running_task_id = value


def mtop_cache_of(ctx):
    return ctx.mod._mtop_product_cache if ctx.mode == 'old' else _svc(ctx).mtop_product_cache


def cookie_state(ctx):
    if ctx.mode == 'old':
        return ctx.mod._browser_cookie_str, ctx.mod._browser_cookie_ts
    return _svc(ctx)._browser_cookie_str, _svc(ctx)._browser_cookie_ts


def set_cookie_state(ctx, text, stamp):
    if ctx.mode == 'old':
        ctx.mod._browser_cookie_str, ctx.mod._browser_cookie_ts = text, stamp
    else:
        _svc(ctx)._browser_cookie_str, _svc(ctx)._browser_cookie_ts = text, stamp


def _modules():
    import src.sidecar.capture_helpers as helpers
    import src.sidecar.capture_routes as routes
    import src.sidecar.capture_service as service
    return helpers, service, routes


def fn(ctx, old_name):
    """旧函数名 -> 当前模式下可调用的函数对象。"""
    if ctx.mode == 'old':
        return getattr(ctx.mod, old_name)
    if old_name in HELPER_NAMES:
        return getattr(_modules()[0], old_name)
    return getattr(_svc(ctx), SERVICE_METHODS[old_name])


def patch_fn(ctx, old_name, value, permanent=False):
    """替换一个函数并让所有调用方都看到它（旧版：app 模块全局；新版：服务方法 / 各模块里按名导入的那份）。

    非 permanent 的替换会在下一个请求的 before 钩子（reset_behavior）里被 restore_patches 还原。"""
    undo = []
    if ctx.mode == 'old':
        undo.append((lambda m, n, o: setattr(m, n, o), ctx.mod, old_name, getattr(ctx.mod, old_name)))
        setattr(ctx.mod, old_name, value)
    elif old_name in HELPER_NAMES:
        for module in _modules():
            if hasattr(module, old_name):
                undo.append((lambda m, n, o: setattr(m, n, o), module, old_name, getattr(module, old_name)))
                setattr(module, old_name, value)
    else:
        service, attr = _svc(ctx), SERVICE_METHODS[old_name]
        if attr in service.__dict__:
            undo.append((lambda s, a, o: setattr(s, a, o), service, attr, service.__dict__[attr]))
        else:
            undo.append((lambda s, a, o: delattr(s, a), service, attr, None))
        setattr(service, attr, value)
    if not permanent:
        ctx.state.setdefault('restores', []).extend(undo)


def restore_patches(ctx):
    for func, target, name, original in reversed(ctx.state.pop('restores', [])):
        func(target, name, original)


_DEPS = {   # 键 -> (旧版 app 全局名, 新版服务对象属性名)
    'discover': ('discover_debuggable_browsers', '_discover_debuggable_browsers'),
    'verify': ('_verify_debug_browser', '_verify_debug_browser'),
    'normalize': ('_normalize_debug_address', '_normalize_debug_address'),
    'port_free': ('_is_local_port_available', '_is_local_port_available'),
    'engine': ('_PROTOCOL_CAPTURE_ENGINE', '_protocol_capture_engine'),
    'find_cdp': ('_find_cdp_port', '_find_cdp_port'),
}


def set_dep(ctx, key, value):
    old, new = _DEPS[key]
    if ctx.mode == 'old':
        setattr(ctx.mod, old, value)
    else:
        setattr(_svc(ctx), new, value)


def set_routes_global(ctx, name, value):
    """start_capture 直接用的全局名（urlopen）：旧版在 app 模块里，新版在路由模块里。"""
    if ctx.mode == 'old':
        setattr(ctx.mod, name, value)
    else:
        setattr(_modules()[2], name, value)


# ---------------------------------------------------------------------------------------------- 虚拟时钟
class Clock:
    def __init__(self):
        self.now = float(START_CLOCK)
        self.sleeps = []
        self.block_next = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        if self.block_next and threading.current_thread() is not threading.main_thread():
            self.block_next = False
            self.entered.set()
            self.release.wait(15)
        self.now += seconds


# ---------------------------------------------------------------------------------------------- 假件
class _Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeWS:
    def __init__(self, state, url):
        self.state, self.url, self.pending = state, url, []

    def settimeout(self, value):
        self.state['log'].append(['ws.settimeout', self.url, value])

    def send(self, raw):
        message = json.loads(raw)
        self.state['log'].append(['ws.send', self.url, message.get('method')])
        behavior = self.state['behavior']
        if behavior.get('ws_send_fail_first') and not self.state.get('ws_send_failed'):
            self.state['ws_send_failed'] = True
            raise OSError('模拟 send 失败')
        self.pending.append(message)

    def recv(self):
        if self.state['behavior'].get('ws_bad_ids'):
            self.state['clock'].now += 6          # 一直收不到对得上号的回复：直到超过 10 秒的等待上限
            return json.dumps({'id': self.pending[-1]['id'] + 1000, 'result': {}})
        message = self.pending.pop(0)
        reply = {'id': message['id'], 'result': {}}
        if message.get('method') == 'Network.getAllCookies':
            reply['result'] = {'cookies': self.state['behavior']['cookies']}
        return json.dumps(reply)

    def close(self):
        self.state['log'].append(['ws.close', self.url])


class FakeOptions:
    def __init__(self, state):
        self._state = state

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self._state['log'].append(['options.' + name, list(args), kwargs])
        return method


class FakePage:
    """按「行为表」应答的假标签页。run_js 按脚本里的特征片段分派。"""

    def __init__(self, state):
        self.state = state
        self._url = state['behavior']['start_url']
        self._reads = 0
        self.antibot_calls = 0

    @property
    def tab_id(self):
        behavior = self.state['behavior']
        if behavior.get('tab_id_error'):
            raise RuntimeError('模拟读取 tab_id 失败')
        return behavior.get('tab_id', 'tab-1')

    @property
    def url(self):
        behavior = self.state['behavior']
        sequence = behavior.get('url_sequence')
        if sequence:
            value = sequence[min(self._reads, len(sequence) - 1)]
            self._reads += 1
            return value(self) if callable(value) else value
        return self._url

    def get(self, url, timeout=None):
        behavior = self.state['behavior']
        self.state['log'].append(['page.get', url, timeout])
        for needle, error in behavior.get('get_errors', {}).items():
            if needle in url:
                raise error
        self._url = behavior.get('get_redirect') or behavior.get('nav_map', {}).get(url, url)
        if (behavior.get('url_sequence') and behavior.get('stop_sequence_after_get')
                and url not in ('https://www.taobao.com', 'https://www.tmall.com')):
            behavior['url_sequence'] = None

    def add_init_js(self, script):
        self.state['log'].append(['page.add_init_js', len(script)])
        if self.state['behavior'].get('init_js_fail'):
            raise RuntimeError('add_init_js 不可用')

    def run_js(self, script, *args, **kwargs):
        behavior = self.state['behavior']
        head = ' '.join(script.split())[:70]
        self.state['log'].append(['page.run_js', head, kwargs])
        for needle, handler in behavior['js']:
            if needle in script:
                value = handler(self, script) if callable(handler) else handler
                if isinstance(value, BaseException):
                    raise value
                return value
        return None


def _antibot_handler(page, script):
    sequence = page.state['behavior']['antibot']
    index = page.antibot_calls
    page.antibot_calls += 1
    value = sequence[min(index, len(sequence) - 1)]
    return value(page) if callable(value) else value


def _cdp_ready(page, script):
    sequence = page.state['behavior']['cdp_ready']
    index = page.state.setdefault('cdp_ready_calls', 0)
    page.state['cdp_ready_calls'] = index + 1
    return sequence[min(index, len(sequence) - 1)]


def _page_ready(page, script):
    return page.state['behavior']['ready']


def default_behavior():
    snapshot = {
        'title': ' 儿童纯棉袜 ',
        'main_images': ['//cbu01.alicdn.com/img/a.jpg', 'https://cbu01.alicdn.com/img/b.png'] + [
            'https://cbu01.alicdn.com/img/m%d.webp' % i for i in range(12)],
        'current_prices': [{'price': '6.80'}],
        'sku_props': [
            {'prop': '颜色', 'value': [{'name': '白色', 'imageUrl': '//cbu01.alicdn.com/sku/white.jpg'},
                                     {'name': '灰色', 'imageUrl': 'https://cbu01.alicdn.com/sku/gray.gif'},
                                     {'name': '粉色', 'image': 'https://cbu01.alicdn.com/sku/pink.png'}]},
            {'prop': '尺码', 'value': [{'name': '均码'}]}],
        'sku_map': [
            {'specAttrs': '白色&gt;均码', 'skuId': 11, 'price': '6.80', 'canBookCount': 99},
            {'specAttrs': '灰色>均码', 'skuId': 12, 'discountPrice': 7.2, 'stock': 5},
            {'specAttrs': '粉色>均码', 'specId': 13, 'quantity': 3}],
        'detail_url': 'https://img.alicdn.com/desc/123456.html',
    }
    envelope = {'version': 1, 'source': 'visible_product_parameters_v1', 'status': 'captured',
                'attributes': [{'name': '材质', 'value': '纯棉'}]}
    return {
        'start_url': PAGE_1688,
        'url_sequence': None,
        'get_errors': {},
        'nav_map': {},
        'init_js_fail': False,
        'page_error': None,
        'antibot': [False],
        'ready': {'offer_id': '123456'},
        'cdp_ready': [True],
        'snapshot': snapshot,
        'attrs': envelope,
        'cookies': [{'domain': '.taobao.com', 'name': '_m_h5_tk', 'value': 'tok123_999'},
                    {'domain': '.tmall.com', 'name': 'cna', 'value': 'abc'},
                    {'domain': '.other.com', 'name': 'x', 'value': 'y'},
                    {'domain': '.taobao.com', 'name': '', 'value': 'novalue'}],
        'targets': [{'type': 'service_worker', 'id': 'sw', 'url': 'x', 'webSocketDebuggerUrl': 'ws://x/sw'},
                    {'type': 'page', 'id': 'other-tab', 'url': 'https://www.taobao.com',
                     'webSocketDebuggerUrl': 'ws://127.0.0.1:9400/devtools/page/other-tab'},
                    {'type': 'page', 'id': 'tab-1', 'url': PAGE_1688,
                     'webSocketDebuggerUrl': 'ws://127.0.0.1:9400/devtools/page/tab-1'}],
        'js': [],
    }


def _js_table(behavior):
    return [
        ('_____tmd_____', _antibot_handler),
        ('return !!(window.context?.result?.global?.globalData?.model?.offerDetail?.subject)', _cdp_ready),
        ("return { offer_id: String(od.offerId || '') }", _page_ready),
        ('flattenImages', lambda page, script: page.state['behavior']['snapshot']),
        ('visible_product_parameters_v1', lambda page, script: page.state['behavior']['attrs']),
    ]


def reset_behavior(ctx, **overrides):
    restore_patches(ctx)
    extra = overrides.pop('extra_js', [])
    behavior = default_behavior()
    behavior['js'] = list(extra) + _js_table(behavior)
    behavior.update(overrides)
    ctx.state['behavior'] = behavior
    ctx.state['cdp_ready_calls'] = 0
    ctx.state['ws_send_failed'] = False
    ctx.state['clock'].block_next = False
    ctx.state['clock'].entered.clear()
    ctx.state['clock'].release.clear()


def install_fakes(ctx):
    state = ctx.state
    state['log'] = []
    state['downloads'] = []
    state['clock'] = clock = Clock()
    time.time, time.sleep = clock.time, clock.sleep

    # ---- DrissionPage ----
    drission = types.ModuleType('DrissionPage')
    drission.ChromiumOptions = lambda: FakeOptions(state)

    def make_page(options):
        error = state['behavior'].get('page_error')
        if error is not None:
            raise error
        page = FakePage(state)
        state['page'] = page
        state['log'].append(['ChromiumPage'])
        return page
    drission.ChromiumPage = make_page
    sys.modules['DrissionPage'] = drission
    state['drission'] = drission

    # ---- websocket / urlopen / requests ----
    websocket = types.ModuleType('websocket')

    def create_connection(url, **kwargs):
        state['log'].append(['ws.connect', url, sorted(kwargs)])
        if 'fail' in url:
            raise OSError('模拟 websocket 连接失败')
        return FakeWS(state, url)
    websocket.create_connection = create_connection
    sys.modules['websocket'] = websocket

    def fake_urlopen(target, timeout=None):
        url = getattr(target, 'full_url', target)
        state['log'].append(['urlopen', url, timeout])
        if '/json/list' in url:
            if ':9411/' in url:
                raise URLError('refused')
            return _Body(json.dumps(state['behavior']['targets']).encode('utf-8'))
        if 'item.htm' in url:
            if state['behavior'].get('item_error'):
                raise URLError('模拟 HTTP 请求失败')
            return _Body(state['behavior'].get('item_html', '').encode('utf-8'))
        if 'h5api.m.taobao.com' in url:
            return _Body(json.dumps({'ret': ['SUCCESS::调用成功'], 'data': {'items': []}}).encode('utf-8'))
        raise URLError('refused')
    urllib.request.urlopen = fake_urlopen
    set_routes_global(ctx, 'urlopen', fake_urlopen)

    import requests

    class Response:
        def __init__(self, url, status=200, content=b'', text=''):
            self.url, self.status_code, self.content, self.text = url, status, content, text

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError('HTTP %d' % self.status_code)

        def close(self):
            state['log'].append(['response.close', self.url])

    def fake_get(url, **kwargs):
        state['log'].append(['requests.get', url, sorted(kwargs)])
        if 'h.fail' in url:
            raise requests.ConnectionError('模拟短链解析失败')
        if 'h.bad' in url:
            return Response('https://evil.example.com/landing')
        if 'h.ok' in url:
            return Response('https://item.taobao.com/item.htm?id=555000&spm=x')
        if 'desc/broken' in url:
            return Response(url, status=500)
        if 'desc/' in url:
            return Response(url, text=(
                '<img src="//img.alicdn.com/d/1.jpg"> <img data-src="https://img.alicdn.com/d/2.png"> '
                '"//gw.alicdn.com/d/3.jpg_400x400.jpg" <img src="//img.alicdn.com/d/s.gif"> '
                '<script src="//g.alicdn.com/x/app.js"></script> <img src="//img.alicdn.com/d/placeholder.jpg"> '
                '<img src="//img.alicdn.com/d/1.jpg">'))
        return Response(url, text='')

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=None):
            state['downloads'].append(url)
            if 'boom' in url:
                raise OSError('模拟下载异常')
            if '404' in url:
                return Response(url, status=404)
            if 'tiny' in url:
                return Response(url, content=b'x' * 10)
            return Response(url, content=PNG_BYTES)
    requests.get = fake_get
    requests.Session = FakeSession

    # ---- 协议采集引擎 / 端口探测 / 本机代理检测 ----
    class Store:
        def __init__(self, engine, root):
            self.engine, self.root = engine, root

        def write_json(self, stage, name, payload, artifact_type='json'):
            if self.engine.fail_writes:
                raise OSError('模拟产物写入失败')
            self.engine.writes.append([stage, name, artifact_type, json.loads(json.dumps(payload, default=str))])

    class Engine:
        def __init__(self):
            self.runs, self.writes = [], []
            self.fail_build = False
            self.fail_writes = False

        def build_run_context(self, *, source_url, source_platform, product_id, metadata):
            if self.fail_build:
                raise RuntimeError('模拟初始化失败')
            self.runs.append({'source_url': source_url, 'platform': source_platform, 'product_id': product_id,
                              'metadata': metadata})
            return (SimpleNamespace(started_at='2026-01-01T00:00:00'),
                    Store(self, os.path.join(ctx.data_dir, 'protocol-debug', 'run-%d' % len(self.runs))))

        def export_plan(self):
            return {'plan': True}

        def export_platform_profiles(self):
            return {'profiles': ['1688', 'taobao']}
    state['engine'] = Engine()
    set_dep(ctx, 'engine', state['engine'])

    state['occupied'] = set()
    set_dep(ctx, 'discover', lambda verify=False: state['browsers'])
    set_dep(ctx, 'normalize', lambda address: address.replace('localhost', '127.0.0.1'))
    set_dep(ctx, 'verify', lambda address, timeout=None: state['verification'])
    set_dep(ctx, 'port_free', lambda host, port: port not in state['occupied'])
    set_dep(ctx, 'find_cdp', lambda: state['cdp_port'])
    state['browsers'] = []
    state['verification'] = {'ok': True}
    state['cdp_port'] = 9401
    state['proxy_hint'] = ''
    REAL_PROXY_RISK[ctx.mode] = fn(ctx, '_detect_local_proxy_risk')
    def fake_proxy_risk():
        hint = state['proxy_hint']
        if isinstance(hint, BaseException):
            raise hint
        return hint
    patch_fn(ctx, '_detect_local_proxy_risk', fake_proxy_risk, permanent=True)
    state['mode_prefs'] = None
    original = ctx.mod.settings_manager.get_settings
    state['real_get_settings'] = original

    def get_settings():
        prefs = state['mode_prefs']
        if prefs is None:
            return original()
        if prefs == 'boom':
            raise RuntimeError('模拟读取设置失败')
        return SimpleNamespace(automation_config={'capture_preferences': prefs})
    ctx.mod.settings_manager.get_settings = get_settings
    reset_behavior(ctx)


# ---------------------------------------------------------------------------------------------- 等待与快照
def _workers():
    return [t for t in threading.enumerate() if WORKER in t.name]


def wait_workers_done(timeout=20.0):
    deadline = REAL_TIME() + timeout
    while REAL_TIME() < deadline:
        if not _workers():
            return
        threading.Event().wait(0.01)
    raise AssertionError('采集线程没有在 %.0f 秒内结束' % timeout)


def wait_until(predicate, timeout=20.0):
    deadline = REAL_TIME() + timeout
    while REAL_TIME() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    raise AssertionError('等待条件超时')


def tid(k, url):
    from capture_url_utils import normalize_capture_url
    return 'capture_%d_%s' % (START_CLOCK + 1000 * k, hashlib.md5(normalize_capture_url(url).encode()).hexdigest()[:8])


def _drain(ctx):
    log = ctx.state['log'][:]
    ctx.state['log'].clear()
    downloads = sorted(ctx.state['downloads'])
    ctx.state['downloads'].clear()
    return log, downloads


def _task_view(ctx, task_id):
    with lock_of(ctx):
        task = tasks_of(ctx).get(task_id)
        return json.loads(json.dumps(task, ensure_ascii=False, default=str)) if task is not None else None


def begin(k, **overrides):
    """启动请求的 before 钩子：重置假件行为，并把虚拟时钟拨到 k 对应的固定值。"""
    def before(ctx):
        reset_behavior(ctx, **overrides)
        ctx.state['clock'].now = float(START_CLOCK + 1000 * k)
    return before


def settle(task_id, extra=None):
    """启动请求的 after 钩子：等采集线程结束，返回任务快照 + 假件调用记录。"""
    def after(ctx):
        wait_workers_done()
        log, downloads = _drain(ctx)
        view = {'task': _task_view(ctx, task_id), 'log': log, 'downloads': downloads,
                'running_id': running_id(ctx)}
        if extra:
            view['extra'] = extra(ctx)
        return view
    return after


def snapshot_after(ctx):
    wait_workers_done()
    log, downloads = _drain(ctx)
    return {'log': log, 'downloads': downloads, 'running_id': running_id(ctx)}


def tree(root):
    out = []
    for base, _, names in os.walk(root):
        for name in sorted(names):
            path = os.path.join(base, name)
            out.append([os.path.relpath(path, root).replace('\\', '/'), os.path.getsize(path)])
    return sorted(out)


def products_tree(ctx):
    return tree(os.path.join(ctx.data_dir, 'uploads', 'products'))



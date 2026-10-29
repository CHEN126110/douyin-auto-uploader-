# -*- coding: utf-8 -*-
"""店铺会话（/api/shop/*）与 CDP 调试浏览器（/api/debug/*）的新旧对打场景（2026-10-19）。

old：直接加载搬迁前的 app.py，给它的模块全局打补丁（get_page 等）。
new：加载搬迁后的 app.py（真实的装配代码），把注入端口里「外部能力」那几个字段换成同一套假件。
两边用同一套请求、同一套假件；账户注册表用真实的 ``src.shop_session``（隔离数据目录里的文件），
所以注册表读写、目录清理这些逻辑是真跑的，只有浏览器 / 进程 / 网络是假的。
响应、注册表落盘内容、假件调用记录、调试产物文件清单必须逐字相同。
"""
import dataclasses
import json
import os
import subprocess
import sys
import types
import urllib.error
import urllib.request

from scenarios import SCENARIOS

DEBUG_URL = 'https://fxg.jinritemai.com/ffa/g/create'


# ====================================================================================== 假件
class _BrokenStates:
    @property
    def is_displayed(self):
        raise RuntimeError('状态不可用')


class FakeElement:
    def __init__(self, ctx, locator, index, text, displayed=True, tag='div', fail_on=(), quirky=False):
        self.ctx, self.locator, self.index = ctx, locator, index
        self._text = text
        self._tag, self._displayed, self._fail_on, self._quirky = tag, displayed, set(fail_on), quirky
        self.states = _BrokenStates() if quirky else types.SimpleNamespace(is_displayed=displayed)
        self.scroll = types.SimpleNamespace(to_center=lambda: self._log('scroll.to_center'))

    @property
    def text(self):
        if self._quirky:
            raise RuntimeError('文本不可读')
        return self._text

    def _log(self, *entry):
        self.ctx.state['calls'].append(['element', self.locator, self.index, *entry])

    def _maybe_fail(self, what):
        if what in self._fail_on:
            raise RuntimeError('元素操作失败: %s' % what)

    def run_js(self, script):
        if self._quirky:
            raise RuntimeError('脚本不可用')
        if 'tagName' in script:
            return self._tag
        if 'outerHTML' in script:
            return '<%s class="x">%s</%s>' % (self._tag, self._text, self._tag)
        return None

    def attr(self, name):
        if self._quirky:
            raise RuntimeError('属性不可读')
        return {'id': 'el-%d' % self.index, 'class': 'cls', 'attr-field-id': 'field-%d' % self.index,
                'value': 'v%d' % self.index, 'placeholder': 'p'}.get(name)

    def click(self, by_js=False):
        self._maybe_fail('click')
        self._log('click', by_js)

    def hover(self):
        self._maybe_fail('hover')
        self._log('hover')

    def clear(self, by_js=False):
        self._maybe_fail('clear')
        self._log('clear', by_js)

    def input(self, value, clear=True):
        self._maybe_fail('input')
        self._log('input', value, clear)


class FakeTab:
    def __init__(self, ctx, address):
        self.ctx, self.address = ctx, address
        self._url = DEBUG_URL
        self._title = '抖店-发布商品'
        self.ready_state = 'complete'

    @property
    def url(self):
        if self.ctx.state.get('url_fail'):
            raise RuntimeError('地址不可读')
        return self._url

    @url.setter
    def url(self, value):
        self._url = value

    @property
    def title(self):
        if self.ctx.state.get('title_fail'):
            raise RuntimeError('标题不可读')
        return self._title

    @property
    def html(self):
        if self.ctx.state.get('html_fail'):
            raise RuntimeError('读取 html 失败')
        return '<html><body>fake page %s</body></html>' % self.address

    def run_js(self, script):
        if self.ctx.state.get('snapshot_fail'):
            raise RuntimeError('页面脚本执行失败')
        if 'maxFields' in script:
            return {
                'url': self._url, 'title': self._title, 'ready_state': self.ready_state,
                'scroll': {'x': 0, 'y': 12},
                'field_items': [{'index': 0, 'field_id': '商品标题', 'text': '标题'}],
                'control_items': [{'index': 0, 'tag': 'button', 'type': '', 'text': '保存', 'value': '',
                                   'attr_field_id': ''}],
                'overlay_items': [],
                'upload_signals': {'upload_busy': False},
            }
        if 'document.readyState' in script:
            return self.ready_state
        return None

    def eles(self, locator, timeout=1.0):
        self.ctx.state['calls'].append(['eles', locator, timeout])
        if 'boom' in locator:
            raise RuntimeError('定位器炸了')
        if 'none' in locator:
            return []
        if 'quirky' in locator:
            return [FakeElement(self.ctx, locator, 0, '', quirky=True)]
        if 'long' in locator:
            return [FakeElement(self.ctx, locator, 0, '长' * 400)]
        if 'hidden' in locator:
            return [FakeElement(self.ctx, locator, 0, '隐藏的', displayed=False)]
        fail_on = ('click', 'input') if 'fail' in locator else ()
        return [FakeElement(self.ctx, locator, 0, '第一个', fail_on=fail_on),
                FakeElement(self.ctx, locator, 1, '第二个', displayed=False, tag='span')]

    def get(self, url):
        self.ctx.state['calls'].append(['tab.get', url])
        self.url = url

    def get_screenshot(self, path=None, name=None, full_page=False):
        if self.ctx.state.get('screenshot_fail'):
            raise RuntimeError('截图失败')
        with open(os.path.join(path, name), 'wb') as fp:
            fp.write(b'\x89PNG fake screenshot')


class FakePage:
    def __init__(self, ctx, address):
        self.ctx = ctx
        self.address = address
        self.latest_tab = 'tab-1'
        self._tab = FakeTab(ctx, address)

    @property
    def browser(self):
        if self.ctx.state.get('broken_browser'):
            raise RuntimeError('浏览器对象已失效')
        return types.SimpleNamespace(address=self.address)

    def get_tab(self, ident):
        if self.ctx.state.pop('tab_fail_once', False):
            raise RuntimeError('标签页刚被关闭')
        if self.ctx.state.get('tab_fail'):
            raise RuntimeError('标签页已关闭')
        return self._tab


class FakeProcess:
    pid = 4321

    def __init__(self, ctx):
        self.ctx = ctx
        self.returncode = None

    def poll(self):
        code = self.ctx.state.get('proc_exit')
        if code is not None:
            self.returncode = code
        return code

    def kill(self):
        self.ctx.state['calls'].append(['proc.kill'])
        if self.ctx.state.get('kill_fail'):
            raise RuntimeError('杀进程失败')


class FakeUuid:
    """让 shop_session 生成的目录名可预测：00000001、00000002……"""

    def __init__(self):
        self.counter = 0

    def uuid4(self):
        self.counter += 1
        return types.SimpleNamespace(hex='%08x' % self.counter + '0' * 24)


def normalize_address(value):
    return str(value or '').strip().replace('http://', '').rstrip('/')


def make_fakes(ctx):
    st = ctx.state

    def log(*entry):
        st['calls'].append(list(entry))

    def get_page(url, profile_name=None, **kwargs):
        log('get_page', url, profile_name, sorted(kwargs))
        if st.get('open_fail'):
            raise RuntimeError('打不开浏览器')
        return FakePage(ctx, st.get('page_address', '127.0.0.1:9333'))

    def attach(address, existing_only=False):
        log('attach', address, existing_only)
        if st.get('attach_fail'):
            raise RuntimeError('连接调试浏览器失败')
        return FakePage(ctx, address)

    def discover(verify=False):
        log('discover', verify)
        return json.loads(json.dumps(st.get('browsers', [])))

    def verify(address, timeout=2.0):
        log('verify', address, timeout)
        port = int(address.rsplit(':', 1)[-1])
        if port in st.get('open_ports', ()) or (st.get('ready_after_popen') and st.get('popen_started')):
            return {'ok': True, 'address': address}
        if st.get('verify_error'):
            return {'ok': False, 'error': st['verify_error']}
        return {'ok': False}

    def chrome():
        log('chrome_path')
        return st.get('chrome_path')

    def port_free(host, port):
        log('port_free', host, port)
        return port in st.get('free_ports', ())

    def reusable(verify=False, preferred_profile=None):
        log('find_reusable', verify, preferred_profile)
        if st.get('reusable_fail'):
            raise RuntimeError('枚举浏览器失败')
        return json.loads(json.dumps(st.get('reusable', {})))

    return types.SimpleNamespace(
        get_page=get_page, attach=attach, discover=discover, verify=verify, chrome=chrome,
        port_free=port_free, reusable=reusable, normalize=normalize_address,
    )


# ====================================================================================== 装配
def install_common(ctx):
    """两种模式共用的补丁：进程 / 网络 / 账户注册表里碰外部世界的那几个函数。"""
    from src import shop_session
    st = ctx.state

    def popen(command, **kwargs):
        st['calls'].append(['popen', [os.path.basename(str(command[0]))] + list(command[1:]),
                            sorted(kwargs)])
        st['popen_started'] = True
        return FakeProcess(ctx)

    subprocess.Popen = popen

    class _Resp:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return self.body

    def urlopen_cm(url, timeout=None):
        port = int(url.split('//')[1].split('/')[0].rsplit(':', 1)[-1])
        targets = st.get('xhs_targets', {}).get(port)
        if targets is None:
            raise urllib.error.URLError('refused')
        st['calls'].append(['urlopen', port])
        return _Resp(json.dumps(targets).encode('utf-8'))

    urllib.request.urlopen = urlopen_cm

    shop_session.uuid = FakeUuid()
    real = {name: getattr(shop_session, name) for name in (
        'observe_identity', 'create_profile', 'set_active_profile', 'remove_profile', 'list_profiles')}

    def wrap(name):
        def call(*args, **kwargs):
            st['calls'].append([name, [a for a in args], sorted(kwargs)])
            failure = st.get('fail', {}).get(name)
            if failure is not None:
                raise failure
            replacement = st.get('override', {}).get(name)
            if replacement is not None:
                return replacement(*args, **kwargs)
            return real[name](*args, **kwargs)
        return call

    for name in real:
        setattr(shop_session, name, wrap(name))

    def identity(debug_address, platform='douyin', timeout=10.0):
        st['calls'].append(['read_account_identity', debug_address, platform, timeout])
        failure = st.get('fail', {}).get('read_account_identity')
        if failure is not None:
            raise failure
        effect = st.get('identity_effect')
        if effect is not None:
            effect(ctx)
        return json.loads(json.dumps(st.get('identity', {'status': 'no_browser'})))

    def freight(debug_address, timeout=10.0):
        st['calls'].append(['read_freight_templates', debug_address, timeout])
        return json.loads(json.dumps(st.get('freight', {'status': 'no_browser', 'templates': []})))

    def taobao_freight(debug_address, timeout=10.0):
        st['calls'].append(['read_taobao_freight_templates', debug_address, timeout])
        return json.loads(json.dumps(st.get('freight', {'status': 'not_captured', 'templates': []})))

    shop_session.read_account_identity = identity
    shop_session.read_freight_templates = freight
    shop_session.read_taobao_freight_templates = taobao_freight


def patch_old(ctx):
    mod = ctx.mod
    f = make_fakes(ctx)
    mod.get_page = f.get_page
    mod.attach_existing_debug_browser = f.attach
    mod.discover_debuggable_browsers = f.discover
    mod._verify_debug_browser = f.verify
    mod.get_chrome_path = f.chrome
    mod._is_local_port_available = f.port_free
    mod._normalize_debug_address = f.normalize
    mod._find_reusable_logged_in_fxg_browser = f.reusable
    mod.repo_root = ctx.data_dir
    ctx.state['debug_state'] = lambda: mod._browser_debug_state
    install_common(ctx)


def patch_new(ctx):
    mod = ctx.mod
    f = make_fakes(ctx)
    debug = mod.browser_debug
    debug._browser = dataclasses.replace(
        debug._browser, discover_browsers=f.discover, normalize_address=f.normalize, verify_browser=f.verify,
        attach_existing=f.attach, open_page=f.get_page, chrome_path=f.chrome, is_port_available=f.port_free)
    debug._repo_root = ctx.data_dir
    shop = mod.shop_session_service
    shop._browser = dataclasses.replace(
        shop._browser, open_page=f.get_page, normalize_address=f.normalize, find_reusable_browser=f.reusable)
    ctx.state['debug_state'] = lambda: debug._state
    install_common(ctx)


def build_new(ctx):
    return []   # 新版走 app.py 自己的装配（new_via_app）


def _initial_state(ctx):
    ctx.state.update(calls=[], browsers=[], open_ports=set(), free_ports=set(), fail={})


# ====================================================================================== 探针
def _scrub_state(ctx):
    state = ctx.state['debug_state']()
    sessions = state['sessions']
    return {
        'current_session_id': state['current_session_id'],
        'session_ids': sorted(sessions),
        'event_counts': [len(s['events']) for _sid, s in sorted(sessions.items())],
        'last_error_stage': (state['last_error'] or {}).get('stage'),
        'browser_instance': state['browser_instance'],
    }


def _registry(ctx):
    path = os.path.join(ctx.data_dir, 'shop_profiles.json')
    if not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8') as fp:
        return json.load(fp)


def _page_address(ctx):
    page = ctx.mod.gui.page
    return None if page is None else page.address


def snap(ctx):
    calls = list(ctx.state['calls'])
    del ctx.state['calls'][:]
    return {'calls': calls, 'gui_page': _page_address(ctx), 'debug': _scrub_state(ctx),
            'registry': _registry(ctx)}


def _tree(root):
    out = []
    if os.path.isdir(root):
        for dirpath, dirs, files in os.walk(root):
            dirs.sort()
            for name in sorted(files):
                path = os.path.join(dirpath, name)
                out.append([os.path.relpath(path, root).replace('\\', '/'), os.path.getsize(path)])
    return out


def final_debug(ctx):
    return {'files': _tree(os.path.join(ctx.data_dir, 'output', 'browser-debug')),
            'tail_calls': snap(ctx)['calls']}


# ====================================================================================== 请求构造
def R(method, path, payload=None, **hooks):
    opts = {'after': snap}
    if 'before' in hooks:
        opts['before'] = hooks['before']
    return (method, path, payload, opts)


def S(**changes):
    """before 钩子：改写场景状态。"""
    def hook(ctx):
        ctx.state.update(changes)
    return hook


def chain(*hooks):
    def hook(ctx):
        for h in hooks:
            h(ctx)
    return hook


def reset_page(ctx):
    ctx.mod.gui.page = None


def set_page(address):
    def hook(ctx):
        ctx.mod.gui.page = FakePage(ctx, address)
    return hook


def make_session_with_page(ctx):
    set_page('127.0.0.1:9333')(ctx)


def set_frozen(ctx):
    sys.frozen = True      # 打包形态：调试产物目录取 get_app_root()


def clear_frozen(ctx):
    if hasattr(sys, 'frozen'):
        del sys.frozen


def fill_events(ctx):
    """把当前会话的事件塞到上限，下一个事件进来时必须被截断。"""
    state = ctx.state['debug_state']()
    session = state['sessions'][state['current_session_id']]
    session['events'] = [{'timestamp': 't', 'type': 'x', 'message': 'm', 'data': {}} for _ in range(200)]


def remove_artifacts_dir(ctx):
    import shutil
    state = ctx.state['debug_state']()
    shutil.rmtree(state['sessions'][state['current_session_id']]['artifacts_dir'], ignore_errors=True)


def early_probe(ctx):
    mod = ctx.mod
    ctx.state['calls'].append(['early', mod._latest_browser_debug_error_after() is None,
                               mod._find_debug_browser_process('') is None,
                               mod._find_debug_browser_process('127.0.0.1:1') is None,
                               mod._get_gui_page_debug_address()])


# ====================================================================================== 调试浏览器
def debug_requests(ctx):
    B = '/api/debug/browser'
    reqs = [
        # ---- 没有任何浏览器 / 会话时的每个提前返回
        R('GET', B + '/session', None, before=early_probe),
        R('GET', B + '/last-error'),
        R('GET', B + '/context'),
        R('POST', B + '/query', {}),
        R('POST', B + '/query', {'locator': 'css:#a'}),
        R('POST', B + '/wait', {}),
        R('POST', B + '/wait', {'condition': 'present', 'locator': 'css:#a'}),
        R('POST', B + '/action', {}),
        R('POST', B + '/action', {'action': 'click', 'locator': 'css:#a'}),
        R('POST', B + '/capture', {}),
        R('GET', B + '/discover?verify=0', None, before=S(browsers=[{'debug_address': '127.0.0.1:9333', 'pid': 11}])),
        R('GET', B + '/discover'),
        R('GET', B + '/discover?verify=false'),
        # ---- ensure：不创建浏览器 / 非法模式 / attach 缺地址
        # 有页面但还没有任何会话：查询本身成功，只是事件记不下来
        R('POST', B + '/query', {'locator': 'css:#a'}, before=set_page('127.0.0.1:9333')),
        R('GET', B + '/context', None),
        R('POST', B + '/ensure', {'create_browser': False}, before=reset_page),
        R('GET', B + '/session'),
        R('POST', B + '/ensure', {'mode': 'bogus'}),
        R('POST', B + '/ensure', {'mode': 'attach'}),
        R('POST', B + '/ensure', {'mode': 'attach', 'debug_address': '127.0.0.1:9333'}, before=S(attach_fail=True)),
        # ---- ensure：托管模式（managed）打开 / 复用 / 重新打开
        R('POST', B + '/ensure', {}, before=chain(S(attach_fail=False, open_fail=True), reset_page)),
        R('POST', B + '/ensure', {'label': '主流程 调试', 'include_html': True, 'limit': 99}, before=S(open_fail=False)),
        R('POST', B + '/ensure', {}),
        R('POST', B + '/ensure', {'url': 'https://fxg.jinritemai.com/other', 'navigate': True}),
        R('POST', B + '/ensure', {'url': 'https://fxg.jinritemai.com/ignored'}),
        R('POST', B + '/ensure', {}, before=S(tab_fail=True)),
        R('POST', B + '/ensure', {'create_browser': False}, before=S(tab_fail=True)),
        R('POST', B + '/ensure', {}, before=chain(S(tab_fail=False, broken_browser=True), set_page('127.0.0.1:9333'))),
        R('POST', B + '/ensure', {}, before=S(broken_browser=False, tab_fail_once=True)),
        R('POST', B + '/ensure', {'new_session': True, 'label': 'a//b'}, before=set_frozen),
        R('POST', B + '/ensure', {'new_session': True, 'label': '第二个/会话 X'}, before=clear_frozen),
        # ---- ensure：attach 模式
        R('POST', B + '/ensure', {'mode': 'attach', 'debug_address': 'http://127.0.0.1:9334/'},
          before=chain(S(browsers=[{'debug_address': '127.0.0.1:9334', 'pid': 22, 'browser_name': 'Chrome',
                                     'exe': 'C:/chrome.exe', 'user_data_dir': 'C:/ud', 'profile_directory': 'Default'}]),
                       reset_page)),
        R('POST', B + '/ensure', {'mode': 'attach', 'debug_address': '127.0.0.1:9334', 'existing_only': False}),
        R('POST', B + '/ensure', {'mode': 'attach', 'debug_address': '127.0.0.1:9335'}),
        R('GET', B + '/session'),
        R('POST', B + '/ensure', {'mode': 'attach', 'debug_address': '127.0.0.1:9335'}, before=S(tab_fail=True)),
        R('POST', B + '/ensure', {'mode': 'attach', 'debug_address': '127.0.0.1:9336'}, before=S(attach_fail=True)),
        # ---- 会话上限：连续建 10 个，只留最近 8 个
    ]
    for index in range(10):
        reqs.append(R('POST', B + '/ensure', {'new_session': True, 'label': 'bulk %d' % index},
                      before=chain(S(attach_fail=False, tab_fail=False), make_session_with_page)))
    reqs += [
        R('GET', B + '/session'),
        # ---- launch
        R('POST', B + '/launch', {}, before=S(open_ports={9333})),
        R('POST', B + '/launch', {'reuse_existing': False}),
        R('POST', B + '/launch', {'port': 9333}, before=S(open_ports={9333})),
        R('POST', B + '/launch', {'port': 'abc'}),
        R('POST', B + '/launch', {'port': 70000}),
        R('POST', B + '/launch', {'port': 0}),
        R('POST', B + '/launch', {'port': 9400}, before=S(open_ports=set(), free_ports=set())),
        R('POST', B + '/launch', {'port': 9400, 'url': ' https://x.test/a ', 'profile_name': '店铺 A!'},
          before=S(free_ports={9400}, chrome_path=None)),
        R('POST', B + '/launch', {'port': 9400, 'browser_path': os.path.join(ctx.data_dir, 'missing.exe')}),
        R('POST', B + '/launch', {'port': 9400, 'browser_path': sys.executable, 'timeout': 'bad'},
          before=S(proc_exit=3, popen_started=False)),
        R('POST', B + '/launch', {'port': 9400, 'browser_path': sys.executable, 'timeout': 1, 'navigate': True,
                                  'url': 'https://x.test/b', 'limit': 3, 'label': 'L启动'},
          before=chain(S(proc_exit=None, popen_started=False, verify_error='连接被拒绝'), reset_page)),
        R('POST', B + '/launch', {'port': 9400, 'browser_path': sys.executable, 'timeout': 1},
          before=S(verify_error=None, popen_started=False)),
        R('POST', B + '/launch', {'port': 9400, 'browser_path': sys.executable, 'timeout': 1},
          before=S(kill_fail=True, popen_started=False)),
        R('POST', B + '/launch', {'port': 9400, 'browser_path': sys.executable, 'timeout': 5,
                                  'user_data_dir': os.path.join(ctx.data_dir, 'custom-ud'), 'new_session': True},
          before=chain(S(ready_after_popen=True, popen_started=False), reset_page)),
        R('POST', B + '/launch', {'timeout': 5, 'url': 'https://x.test/auto', 'include_html': True},
          before=chain(S(open_ports=set(), free_ports={9340}, chrome_path=sys.executable, popen_started=False), reset_page)),
        R('POST', B + '/launch', {'timeout': 5}, before=S(free_ports=set(), popen_started=False)),
        R('POST', B + '/launch', {'timeout': 5}, before=S(free_ports={9340}, tab_fail=True, popen_started=False)),
        R('POST', B + '/launch', {'timeout': 1, 'port': ''}, before=S(open_ports={9341}, ready_after_popen=False,
                                                                       kill_fail=False)),
        # ---- context
        R('GET', B + '/context', None, before=chain(S(tab_fail=False), set_page('127.0.0.1:9333'))),
        R('GET', B + '/context?include_html=1&locator=css:%23a&locator_type=css&limit=2'),
        R('GET', B + '/context?locator=//div&locator_type=xpath&limit=0'),
        R('GET', B + '/context?locator=css:.none'),
        R('GET', B + '/context', None, before=S(tab_fail=True)),
        R('GET', B + '/context?locator=css:.boom'),
        R('GET', B + '/context?include_html=true', None, before=chain(S(tab_fail=False, html_fail=True),
                                                                        set_page('127.0.0.1:9333'))),
        # ---- query
        R('POST', B + '/query', {'locator': 'css:#a'}, before=S(tab_fail=False, html_fail=False)),
        R('POST', B + '/query', {'locator': 'css:long', 'only_visible': False}),
        R('POST', B + '/query', {'locator': 'css:quirky'}),
        R('POST', B + '/query', {'locator': 'css:quirky', 'only_visible': False, 'include_html': True}),
        R('POST', B + '/query', {'locator': 'css:#a'}, before=fill_events),
        R('POST', B + '/query', {'locator': 'css:#a', 'only_visible': False, 'include_html': True, 'limit': 1}),
        R('POST', B + '/query', {'locator': '#plain', 'locator_type': 'css', 'timeout': 99}),
        R('POST', B + '/query', {'locator': '//div', 'locator_type': 'xpath', 'timeout': 'x', 'limit': 'x'}),
        R('POST', B + '/query', {'locator': 'css:.none'}),
        R('POST', B + '/query', {'locator': 'css:.hidden'}),
        R('POST', B + '/query', {'locator': 'css:.boom'}),
        R('POST', B + '/query', {'locator': 'css:#a'}, before=chain(S(screenshot_fail=True, html_fail=True), set_page('127.0.0.1:9333'))),
        R('POST', B + '/query', {'locator': 'css:.boom'}),
        R('POST', B + '/query', {'locator': 'css:#a', 'create_browser': True}, before=chain(S(screenshot_fail=False, html_fail=False), reset_page)),
        R('POST', B + '/query', {'locator': 'css:#a'}, before=S(tab_fail=True)),
        # ---- wait
        R('POST', B + '/wait', {'condition': 'present', 'locator': 'css:#a'}, before=chain(S(tab_fail=False), set_page('127.0.0.1:9333'))),
        R('POST', B + '/wait', {'condition': 'VISIBLE', 'locator': 'css:#a', 'count': 1, 'include_html': True}),
        R('POST', B + '/wait', {'condition': 'visible', 'locator': 'css:.hidden', 'timeout': 0.2, 'interval': 0.05}),
        R('POST', B + '/wait', {'condition': 'visible', 'locator': 'css:.hidden', 'timeout': 0.2,
                                 'capture_on_timeout': False}),
        R('POST', B + '/wait', {'condition': 'absent', 'locator': 'css:.none'}),
        R('POST', B + '/wait', {'condition': 'hidden', 'locator': 'css:.hidden', 'only_visible': False, 'timeout': 'bad',
                                 'interval': 'bad'}),
        R('POST', B + '/wait', {'condition': 'present', 'locator': 'css:#a', 'count': 5, 'timeout': 0.2}),
        R('POST', B + '/wait', {'condition': 'url_contains', 'text': 'jinritemai'}),
        R('POST', B + '/wait', {'condition': 'url_contains'}),
        R('POST', B + '/wait', {'condition': 'url_contains', 'text': 'nope', 'timeout': 0.2}),
        R('POST', B + '/wait', {'condition': 'title_contains', 'text': '抖店'}),
        R('POST', B + '/wait', {'condition': 'title_contains'}),
        R('POST', B + '/wait', {'condition': 'ready_state'}),
        R('POST', B + '/wait', {'condition': 'ready_state', 'text': 'loading', 'timeout': 0.2}),
        R('POST', B + '/wait', {'condition': 'url_contains', 'text': 'x', 'timeout': 0.2}, before=S(url_fail=True)),
        R('POST', B + '/wait', {'condition': 'title_contains', 'text': 'x', 'timeout': 0.2},
          before=S(url_fail=False, title_fail=True)),
        R('POST', B + '/wait', {'condition': 'ready_state', 'timeout': 0.2}, before=S(title_fail=False, snapshot_fail=True)),
        R('POST', B + '/wait', {'condition': 'present'}, before=S(snapshot_fail=False)),
        R('POST', B + '/wait', {'condition': 'bogus_condition'}),
        R('POST', B + '/wait', {'condition': 'present', 'locator': 'css:.boom'}),
        R('POST', B + '/wait', {'condition': 'url_contains', 'text': 'x', 'url': 'https://fxg.jinritemai.com/n',
                                 'navigate': True, 'create_browser': True}),
        R('POST', B + '/wait', {'condition': 'present', 'locator': 'css:#a'}, before=S(tab_fail=True)),
        # ---- action
        R('POST', B + '/action', {'action': 'navigate'}, before=chain(S(tab_fail=False), set_page('127.0.0.1:9333'))),
        R('POST', B + '/action', {'action': 'navigate', 'url': 'https://fxg.jinritemai.com/nav'}),
        R('POST', B + '/action', {'action': 'CLICK'}),
        R('POST', B + '/action', {'action': 'click', 'locator': 'css:#a'}),
        R('POST', B + '/action', {'action': 'click', 'locator': 'css:#a', 'by_js': False, 'only_visible': False,
                                   'index': 1}),
        R('POST', B + '/action', {'action': 'click', 'locator': 'css:#a', 'index': 9}),
        R('POST', B + '/action', {'action': 'hover', 'locator': 'css:#a', 'timeout': 9}),
        R('POST', B + '/action', {'action': 'scroll', 'locator': 'css:#a', 'locator_type': 'css'}),
        R('POST', B + '/action', {'action': 'clear', 'locator': 'css:#a'}),
        R('POST', B + '/action', {'action': 'input', 'locator': 'css:#a'}),
        R('POST', B + '/action', {'action': 'input', 'locator': 'css:#a', 'value': 123, 'clear': False}),
        R('POST', B + '/action', {'action': 'input', 'locator': 'css:#a', 'value': '', 'timeout': 'x'}),
        R('POST', B + '/action', {'action': 'dance', 'locator': 'css:#a'}),
        R('POST', B + '/action', {'action': 'click', 'locator': 'css:quirky'}),
        R('POST', B + '/action', {'action': 'click', 'locator': 'css:.none'}),
        R('POST', B + '/action', {'action': 'click', 'locator': 'css:.boom'}),
        R('POST', B + '/action', {'action': 'click', 'locator': 'css:fail'}),
        R('POST', B + '/action', {'action': 'input', 'locator': 'css:fail', 'value': 'x'}),
        R('POST', B + '/action', {'action': 'click', 'locator': 'css:#a', 'create_browser': True,
                                   'url': 'https://fxg.jinritemai.com/a', 'navigate': True}, before=reset_page),
        R('POST', B + '/action', {'action': 'click', 'locator': 'css:#a'}, before=S(tab_fail=True)),
        # ---- capture
        R('POST', B + '/capture', {}, before=chain(S(tab_fail=False), set_page('127.0.0.1:9333'))),
        R('POST', B + '/capture', {'label': '手动 截图', 'include_html': False, 'session_label': '另一个/会话'}),
        R('POST', B + '/capture', {'include_html': 0}, before=S(screenshot_fail=True)),
        R('POST', B + '/capture', {}, before=S(html_fail=True, snapshot_fail=True)),
        R('POST', B + '/capture', {}, before=S(html_fail=False, snapshot_fail=True, url_fail=True)),
        R('POST', B + '/capture', {}, before=S(tab_fail=True, url_fail=False, snapshot_fail=False)),
        # ---- 上传流水线写入的错误报告（只能经 app.py 里的别名调用）
        R('GET', B + '/last-error', None, before=chain(S(tab_fail=False, html_fail=False, snapshot_fail=False,
                                                          screenshot_fail=False), set_page('127.0.0.1:9333'),
                                                        lambda c: record_error(c, 'upload_stage', stage_tab=True))),
        R('GET', B + '/session', None, before=lambda c: record_error(c, 'second/stage', stage_tab=False)),
        R('GET', B + '/last-error', None, before=lambda c: (remove_artifacts_dir(c),
                                                             record_error(c, 'dir_removed', stage_tab=True))),
        R('GET', B + '/last-error', None, before=latest_probe),
    ]
    return reqs


def record_error(ctx, stage, stage_tab):
    tab = ctx.mod.gui.page.get_tab('tab-1') if stage_tab else None
    report = ctx.mod._record_browser_automation_error(
        stage, RuntimeError('上传失败: ' + stage), 'Traceback (fake)', tab=tab, extra={'record_id': 7})
    ctx.state['calls'].append(['record_error', stage, sorted(report), report.get('report_path') is not None])


def latest_probe(ctx):
    mod = ctx.mod
    report = mod._get_last_browser_debug_error() if hasattr(mod, '_get_last_browser_debug_error') else \
        mod.browser_debug.get_last_error()
    captured = report['captured_at']
    results = {
        'no_arg': mod._latest_browser_debug_error_after() is not None,
        'older': mod._latest_browser_debug_error_after('2000-01-01T00:00:00') is not None,
        'same': mod._latest_browser_debug_error_after(captured) is not None,
        'newer': mod._latest_browser_debug_error_after('2999-01-01T00:00:00') is not None,
    }
    ctx.state['calls'].append(['latest_error_after', results])
    ctx.state['calls'].append(['pure', mod._debug_bool(None, True), mod._debug_bool('Yes'), mod._debug_bool('no'),
                               mod._debug_bool(True, False), mod._debug_int('7', 1, 0, 5), mod._debug_int('x', 3),
                               mod._debug_int(None, 3, minimum=4)])


SCENARIOS['debug'] = dict(
    setup=_initial_state,
    patch_old=patch_old,
    patch_new=patch_new,
    build_new=build_new,
    new_via_app=True,
    requests=debug_requests,
    final=final_debug,
)

# -*- coding: utf-8 -*-
"""抖店上传（/api/upload/*、/api/protocol/fxg/runtime-options、/start）的新旧对打场景（2026-10-21，上传域第二步）。

走 app.py 自己的装配（``new_via_app=True``）：旧版用搬迁前的 app.py（页面操作已在 upload_steps.py，流水线 / 任务 / 路由还在 app.py），
新版用搬迁后的 app.py + ``src/sidecar/upload_service.py`` / ``upload_routes.py``。同一套假件、同一套请求，响应、任务字典、
假件调用记录、诊断日志、进程环境变量必须逐字相同（时间戳规整掉）。

假件分两层，旧版换 app.py 的模块全局，新版换服务对象上两个端口的字段（frozen dataclass，用 ``dataclasses.replace``）：
  - 14 个页面步骤：按「行为表」应答并记录每次调用收到的参数（商品记录取 id、标签页取名字）；
  - 浏览器 / CDP 能力：``get_page``、图片列表、计时、睡眠、复用浏览器、CDP 探测、自动化错误记录；
  - 进程级的：后台线程（同步执行，任务在启动请求里就跑完，不用等线程）、``uuid.uuid4``（确定性序列）、``urllib.request.urlopen`` /
    ``websocket`` / ``fxg_protocol_v4``（协议流水线的外部世界）、``subprocess.run`` / ``shutil.which``（协议运行时配置探针）、
    ``tempfile.gettempdir``（调试注入文件）、设置管理器的 ``get_settings``（可指定第 N 次调用抛错）。
入口文件路径（``__file__`` / 服务的 ``app_file``）换成隔离目录里的 app.py：诊断日志（run_task_diag.log / protocol_diag.log）落在那里，也一并比较。
商品表在需要时被改动（清空 / 全部改成已发布 / 加几条特殊记录），下一个请求开始前用快照还原。

⚠️ 这份场景故意把“一键发布全部”的现状钉住：worker 载入全部记录（含 status=1 / 2 的），而不是接口数出来的 status=0 的那几条
（方案文档「未决问题」第 30 条）。新旧一致，所以它不是搬迁引入的；以后修这个问题时，这份对打的相关请求会（也应该）变红。
"""
import dataclasses
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime
from types import SimpleNamespace

from scenarios import SCENARIOS

DEFAULT, TAOBAO = 'upload-browser-profile', 'taobao-bbbbbbbb'
STEP_FIELDS = [  # (端口字段, app.py 里的旧全局名)
    ('settle_between_records', '_settle_between_records'), ('wait_login_complete', '_wait_login_complete'),
    ('prepare_record_assets', '_prepare_record_assets'), ('dismiss_pending_browser_alert', '_dismiss_pending_browser_alert'),
    ('open_publish_page', '_open_publish_page'), ('fill_title_for_record', '_fill_title_for_record'),
    ('select_category_and_prepare_attributes', '_select_category_and_prepare_attributes'),
    ('fill_category_attributes', '_fill_category_attributes'), ('upload_main_images', '_upload_main_images'),
    ('upload_media_assets', '_upload_media_assets'), ('configure_sku_entries', '_configure_sku_entries'),
    ('configure_sku_structure', '_configure_sku_structure'),
    ('fill_price_stock_and_delivery', '_fill_price_stock_and_delivery'), ('submit_publish', '_submit_publish'),
]
ASSETS = {'main_pic_list': ['main.jpg'], 'diaopai_pic': 'diaopai.jpg', 'sub_pic_list': ['sub.jpg'], 'my_video': 'v.mp4',
          'white_pic': 'white.jpg', 'detail_pic_list': ['d1.jpg'], 'sku_list': [{'name': '白色', 'price': 9.9}]}
STAMP = re.compile(r'\d{8}_\d{6}')
DEFAULT_AUTOMATION = {'publish_mode': 'dom', 'shipping_template': '中通包邮', 'material_compositions': []}
PROTOCOL_OK = {'success': True, 'data': {'product_id': 'P123456789012345678', 'path': '/p', 'stopped_before_submit': False}, 'steps': [1]}


def svc(ctx):
    return ctx.mod.upload_service


def tasks_of(ctx):
    return ctx.mod._upload_tasks if ctx.mode == 'old' else svc(ctx).tasks


def lock_of(ctx):
    return ctx.mod._upload_tasks_lock if ctx.mode == 'old' else svc(ctx).lock


def _json_safe(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=repr))


def brief(value):
    if isinstance(value, str):
        return STAMP.sub('<stamp>', value)                 # 计时会话 id 里带着 %Y%m%d_%H%M%S 的挂钟时间
    if hasattr(value, 'id') and hasattr(value, 'name') and not isinstance(value, (str, bytes)):
        return ['record', value.id]
    if isinstance(value, FakeTab):
        return 'tab'
    if callable(value):
        return 'callable'
    return value


class FakeTab:
    def __init__(self, ctx, url='https://fxg.jinritemai.com/ffa/g/create'):
        self._ctx = ctx
        self._url = url

    def _guard(self):
        if self._ctx.state['behavior'].get('tab_props_raise'):
            raise RuntimeError('标签页已关闭')

    @property
    def url(self):
        self._guard()
        return self._url

    @property
    def title(self):
        self._guard()
        return '发布商品'

    def get(self, url):
        self._ctx.state['log'].append(['tab.get', url])
        if self._ctx.state['behavior'].get('tab_get_fails'):
            raise RuntimeError('导航失败')


class FakePage:
    def __init__(self, ctx, tab_error=None):
        self._ctx = ctx
        self.latest_tab = 'tab-1'
        self._tab_error = tab_error

    def get_tab(self, _id):
        if self._tab_error:
            raise RuntimeError(self._tab_error)
        return FakeTab(self._ctx)


class SyncThread:
    """同步“线程”：start() 里直接跑完，异常像真线程一样不往外抛（只记下来）；``hook`` 在目标函数开始前执行（用来模拟“启动后、开跑前被取消”）。"""
    errors = []
    hook = None

    def __init__(self, target, args=(), daemon=None, **kwargs):
        self._target, self._args = target, args

    def start(self):
        try:
            if SyncThread.hook:
                SyncThread.hook()
            self._target(*self._args)
        except BaseException as exc:                        # noqa: BLE001
            SyncThread.errors.append(type(exc).__name__ + ': ' + str(exc))


# ---------------------------------------------------------------------------------------------- 假件
def step_fake(ctx, name):
    def call(*args, **kwargs):
        ctx.state['log'].append([name] + [brief(a) for a in args])
        behavior = ctx.state['behavior'].get(name)
        if behavior is not None:
            return behavior(ctx, *args)
        return {'prepare_record_assets': lambda: (dict(ASSETS), ''), 'open_publish_page': lambda: True,
                'submit_publish': lambda: True, 'wait_login_complete': lambda: True}.get(name, lambda: None)()
    call.__name__ = name
    return call


def raises(message):
    def behavior(*_args):
        raise RuntimeError(message)
    return behavior


def cancel_running(ctx, *_args):
    with lock_of(ctx):
        for task in tasks_of(ctx).values():
            if task.get('status') == 'running':
                task['cancelled'] = True


def browser_fakes(ctx):
    log = ctx.state['log']

    def logged(name, result=None):
        def call(*args, **kwargs):
            log.append([name] + [brief(a) for a in args] + ([sorted(kwargs.items())] if kwargs else []))
            return result
        call.__name__ = name
        return call

    def open_page(url, profile_name=None):
        log.append(['open_page', url, profile_name])
        if ctx.state['behavior'].get('open_page_fails'):
            raise RuntimeError('chrome 起不来')
        return FakePage(ctx)

    def attach(report):
        log.append(['attach_reusable_browser'])
        mode = ctx.state['behavior'].get('attach_tab')
        if mode == 'tab_only':                     # 只给标签页，不修好 gui.page（走“取标签页失败 -> 重新附着”那条分支）
            return FakeTab(ctx)
        if mode:
            ctx.mod.gui.page = FakePage(ctx)
            return FakeTab(ctx)
        return None

    def record_error(stage, exc, detail, tab=None, extra=None):
        log.append(['record_automation_error', stage, str(exc), 'Traceback' in detail, brief(tab),
                    {'record_id': extra['record_id'], 'record_name': extra['record_name'],
                     'stages': [[s['stage'], s['status'], s['error']] for s in extra['stage_timings']]}])
        if ctx.state['behavior'].get('record_error_raises'):
            raise RuntimeError('记录错误本身也失败了')

    def pics(size):
        if ctx.state['behavior'].get('pics_raise'):
            raise OSError('目录没了')
        return ctx.state['pics'].get(size, [])
    return {
        'open_page': open_page,
        'get_pic_list': lambda record, size: pics(size),
        'get_detail_pic_list': lambda record: pics('detail'),
        'reset_category_expanded_state': logged('reset_category_expanded_state'),
        'timer_start_session': logged('timer_start_session', None),
        'timer_end_session': logged('timer_end_session', {'steps': 0}),
        'timer_record': logged('timer_record'),
        'time': SimpleNamespace(sleep=lambda seconds: log.append(['sleep', seconds])),
        'normalize_debug_address': lambda value: str(value or ''),
        'discover_debuggable_browsers': lambda **kw: ctx.state['browsers'],
        'fetch_cdp_page_targets': lambda address: ctx.state['targets'].get(address, []),
        'attach_reusable_browser': attach,
        'find_cdp_port': lambda: ctx.state['behavior'].get('cdp_port'),
        'record_automation_error': record_error,
        'latest_error_after': lambda started_at: {'stage': 'diag', 'after': bool(started_at)},
    }


# 旧版 app.py 里这些端口字段对应的全局名
OLD_BROWSER_NAMES = {
    'open_page': 'get_page', 'get_pic_list': 'get_pic_list', 'get_detail_pic_list': 'get_detail_pic_list',
    'reset_category_expanded_state': 'reset_category_expanded_state', 'timer_start_session': 'timer_start_session',
    'timer_end_session': 'timer_end_session', 'timer_record': 'timer_record', 'time': 'time',
    'normalize_debug_address': '_normalize_debug_address', 'discover_debuggable_browsers': 'discover_debuggable_browsers',
    'fetch_cdp_page_targets': 'fetch_cdp_page_targets', 'attach_reusable_browser': '_attach_reusable_logged_in_fxg_browser',
    'find_cdp_port': '_find_cdp_port', 'record_automation_error': '_record_browser_automation_error',
    'latest_error_after': '_latest_browser_debug_error_after',
}


def install(ctx):
    """旧版换 app.py 的模块全局，新版换服务对象上端口的字段；进程级的假件两边完全一样。"""
    state = ctx.state
    steps = {field: step_fake(ctx, field) for field, _ in STEP_FIELDS}
    browser = browser_fakes(ctx)
    app_dir = os.path.join(ctx.data_dir, 'entry')
    os.makedirs(app_dir, exist_ok=True)
    fake_time = SimpleNamespace(sleep=lambda seconds: state['log'].append(['sleep', seconds]), time=__import__('time').time,
                                perf_counter=__import__('time').perf_counter)
    import src.sidecar.upload_routes as routes_module
    import src.sidecar.upload_service as service_module

    def probe_run(command, **kwargs):
        env = kwargs['env']
        outcome = state['probe']
        state['log'].append(['probe_run', [os.path.basename(command[0]), os.path.basename(command[1])],
                             {k: env[k] for k in ('CATEGORY_KEYWORDS', 'CATEGORY_KEYWORD', 'CATEGORY_ID', 'CDP_LIST_URL', 'TARGET_HINT',
                                                  'OPERATION_TYPE', 'INCLUDE_FREIGHT') if k in env}, kwargs['timeout']])
        return SimpleNamespace(returncode=outcome['code'], stdout=outcome['stdout'], stderr=outcome['stderr'])
    fake_subprocess = SimpleNamespace(run=probe_run)
    fake_shutil = SimpleNamespace(which=lambda name: None if state['behavior'].get('no_node') else 'C:/node/node.exe')
    SyncThread.errors = []
    SyncThread.hook = None
    ctx.mod.__file__ = os.path.join(app_dir, 'app.py')       # get_app_root() / 诊断日志 / mcp 目录推导都按这个位置算，新旧一致
    if ctx.mode == 'old':
        mod = ctx.mod
        for field, old in STEP_FIELDS:
            setattr(mod, old, steps[field])
        for field, old in OLD_BROWSER_NAMES.items():
            setattr(mod, old, browser[field])
        mod.threading = SimpleNamespace(Thread=SyncThread)
        mod.system_time = fake_time
        mod.subprocess = fake_subprocess
        mod.shutil = fake_shutil
    else:
        service = svc(ctx)
        service._steps = dataclasses.replace(service._steps, **steps)
        service._browser = dataclasses.replace(service._browser, **browser)
        service._app_file = os.path.join(app_dir, 'app.py')
        routes_module.threading = SimpleNamespace(Thread=SyncThread)
        service_module.system_time = fake_time
        service_module.subprocess = fake_subprocess
        service_module.shutil = fake_shutil

    # ---- 进程级（两边一样）
    counter = state['uuid_counter']
    uuid.uuid4 = lambda: uuid.UUID(int=(counter.__setitem__(0, counter[0] + 1) or counter[0]) << 96)
    import src.utils
    src.utils.get_page = browser['open_page']                 # _ensure_protocol_browser 里函数内的 ``from src.utils import get_page``
    settings = ctx.mod.settings_manager

    def get_settings():
        state['settings_calls'] += 1
        if state['behavior'].get('settings_raise') == state['settings_calls']:
            raise RuntimeError('设置读不了')
        return SimpleNamespace(automation_config=dict(state['automation']))
    settings.get_settings = get_settings
    settings.normalize_automation_config = lambda config: dict(config)
    tempdir = os.path.join(ctx.data_dir, 'tmp')
    os.makedirs(tempdir, exist_ok=True)
    tempfile.gettempdir = lambda: tempdir

    class Response:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

    import urllib.request

    def urlopen(url, timeout=None):
        state['log'].append(['urlopen', url])
        handler = state['urlopen']
        if handler is None:
            raise OSError('拒绝连接')
        return Response(json.dumps(handler(url)).encode('utf-8'))
    urllib.request.urlopen = urlopen

    class FakeSocket:
        def __init__(self, cookies, href):
            self._messages = [json.dumps({'id': 2, 'result': {'cookies': cookies}}),
                              json.dumps({'id': 3, 'result': {'result': {'value': href}}})]
            self._timed_out = False

        def settimeout(self, _s):
            pass

        def send(self, payload):
            pass

        def recv(self):
            mode = state['behavior'].get('ws')
            if mode == 'timeout_first' and not self._timed_out:
                self._timed_out = True
                raise TimeoutError('读超时')
            if mode == 'recv_error':
                raise RuntimeError('连接断了')
            return self._messages.pop(0)

        def close(self):
            pass

    def create_connection(url, **kw):
        if state['behavior'].get('ws') == 'connect_fails':
            raise OSError('连不上 WebSocket')
        return FakeSocket([{'domain': '.jinritemai.com'}] * state['cookie_count'], state['href'])
    sys.modules['websocket'] = SimpleNamespace(create_connection=create_connection, WebSocketTimeoutException=TimeoutError)

    def protocol_run(**kwargs):
        state['log'].append(['protocol_run', kwargs['category_leaf_id'], kwargs['product_data']['title'],
                             kwargs['product_data']['price'], kwargs['product_data']['sku_info'],
                             kwargs['product_data']['material'], kwargs['image_paths'], kwargs['cdp_port'],
                             kwargs['shipping_template_name'], kwargs['stop_before_submit']])
        kwargs['progress_callback'](42, '协议进度', '上传图片', [{'name': 'a', 'status': 'ok', 'elapsed_ms': 12.7, 'summary': 3}])
        result = state['protocol_result']
        if isinstance(result, Exception):
            raise result
        return result
    state['protocol_module'] = SimpleNamespace(run=protocol_run)
    sys.modules['fxg_protocol_v4'] = state['protocol_module']


# ---------------------------------------------------------------------------------------------- 数据与请求
def _entry(slug, platform, label=None):
    return {'profile_name': slug, 'platform': platform, 'label': label, 'created_at': '2026-10-01T09:00:00',
            'shop_id': None, 'shop_name': None, 'last_seen_at': None, 'seen_count': 0}


def setup(ctx):
    from src import shop_session
    shop_session.save_registry({'active_profile': DEFAULT, 'profiles': {DEFAULT: _entry(DEFAULT, 'douyin'), TAOBAO: _entry(TAOBAO, 'taobao', '乙淘宝')}})
    state = ctx.state
    state.update(log=[], behavior={}, automation=dict(DEFAULT_AUTOMATION), pics={}, browsers=[], targets={}, urlopen=None,
                 cookie_count=3, href='https://fxg.jinritemai.com/ffa/g/create', protocol_result=PROTOCOL_OK,
                 probe={'code': 0, 'stdout': '{"options": [1]}', 'stderr': ''}, uuid_counter=[0], seen=0, settings_calls=0)
    image = os.path.join(ctx.data_dir, 'main.jpg')
    with open(image, 'wb') as fp:
        fp.write(b'img')
    state['image'] = image
    mcp = os.path.join(ctx.data_dir, 'mcp')
    os.makedirs(os.path.join(mcp, 'scripts'))
    with open(os.path.join(mcp, 'scripts', 'probe-fxg-runtime-options.mjs'), 'w', encoding='utf-8') as fp:
        fp.write('// probe')
    state['mcp'] = mcp
    os.environ.pop('NODE_BINARY', None)
    os.environ.pop('CDP_PORT', None)
    content = json.dumps([{'name': '白色', 'price': 9.9, 'path': 'SKU/白.jpg'}, {'name': '黑色', 'price': 11}], ensure_ascii=False)
    state['base_content'] = content
    R = ctx.Record
    R.create(id=301, name='白袜_货号_a_商品甲', status=0, content=content, **_common())
    R.create(id=302, name='白袜_货号_b_商品乙', status=0, content=content, **_common(clazz='1', repo=0))
    R.create(id=303, name='白袜_货号_c_已发布', status=1, content=content, **_common())
    R.create(id=304, name='白袜_货号_d_待确认', status=2, content=content, **_common(title=''))


def _common(**over):
    values = dict(type=1, update_time=datetime(2026, 1, 1), source_url='https://example.invalid/x', path='uploads/products/x',
                  repo=5, clazz='2', title='标题')
    values.update(over)
    return values


# ---- 商品表：改动前存快照，下一个请求开始前还原
def restore_table(ctx):
    backup = ctx.state.pop('table_backup', None)
    if backup is None:
        return
    for row in list(ctx.Record.select()):
        row.delete_instance()
    for data in backup:
        ctx.Record.create(**data)


def mutate_table(ctx, change):
    if 'table_backup' not in ctx.state:
        ctx.state['table_backup'] = [dict(row.__data__) for row in ctx.Record.select().order_by(ctx.Record.id)]
    change(ctx)


def add_records(*specs):
    """specs: (id, name, content 或 callable(ctx) -> content, 额外字段)。"""
    def change(ctx):
        for rid, name, content, over in specs:
            ctx.Record.create(id=rid, name=name, status=0, content=content(ctx) if callable(content) else content, **_common(**over))
    return change


def empty_table(ctx):
    for row in list(ctx.Record.select()):
        row.delete_instance()


def mark_all(status):
    return lambda ctx: ctx.Record.update(status=status).execute()


def set_active(name):
    from src import shop_session
    registry = shop_session.load_registry()
    if registry['active_profile'] != name:
        registry['active_profile'] = name
        shop_session.save_registry(registry)


def cfg(behavior=None, automation=None, active_page=True, seed=None, pics=None, protocol=None, urlopen=None, cookie_count=3,
        href='https://fxg.jinritemai.com/ffa/g/create', probe=None, browsers=None, targets=None, cleanup_tasks=False,
        db=None, active=DEFAULT, thread_hook=None, mcp_env=True, no_module=False):
    def before(ctx):
        state = ctx.state
        restore_table(ctx)
        state['behavior'] = dict(behavior or {})
        state['settings_calls'] = 0
        state['automation'] = dict(DEFAULT_AUTOMATION, **(automation or {}))
        state['pics'] = dict(pics if pics is not None else {'800': [state['image']], '750': [state['image']], 'detail': [state['image']]})
        state['urlopen'] = urlopen
        state['cookie_count'], state['href'] = cookie_count, href
        state['protocol_result'] = protocol if protocol is not None else PROTOCOL_OK
        state['probe'] = dict({'code': 0, 'stdout': '{"options": [1]}', 'stderr': ''}, **(probe or {}))
        state['browsers'], state['targets'] = browsers or [], targets or {}
        sys.modules['fxg_protocol_v4'] = None if no_module else state['protocol_module']
        if mcp_env:
            os.environ['DOUYIN_MCP_SERVER_DIR'] = state['mcp']
        else:
            os.environ.pop('DOUYIN_MCP_SERVER_DIR', None)
        set_active(active)
        SyncThread.hook = (lambda: thread_hook(ctx)) if thread_hook else None
        if active_page is True:
            ctx.mod.gui.page = FakePage(ctx)
        elif active_page is None:
            ctx.mod.gui.page = None
        else:
            ctx.mod.gui.page = FakePage(ctx, tab_error=active_page)
        if cleanup_tasks:
            with lock_of(ctx):
                tasks_of(ctx).clear()
        if seed:
            with lock_of(ctx):
                tasks_of(ctx).update(seed)
        if db:
            mutate_table(ctx, db)
    return before


def view(ctx):
    """任务表 + 自上次以来的假件记录 + 进程环境 + 线程里没捕获的异常。"""
    state = ctx.state
    with lock_of(ctx):
        tasks = _json_safe(tasks_of(ctx))
    log = _json_safe(state['log'][state['seen']:])
    state['seen'] = len(state['log'])
    return {'tasks': tasks, 'log': log, 'cdp_port_env': os.environ.get('CDP_PORT'), 'thread_errors': list(SyncThread.errors),
            'has_page': bool(ctx.mod.gui.page)}


def _inject_files(ctx, content):
    tempdir = tempfile.gettempdir()
    result, error = os.path.join(tempdir, 'sku_inject_result.json'), os.path.join(tempdir, 'sku_inject_error.txt')
    for path in (result, error):
        if os.path.isdir(path):
            os.rmdir(path)
        elif os.path.exists(path):
            os.remove(path)
    if content == 'dirs':                                    # 文件位置上是目录：open 会抛，接口里的裸 except 吞掉
        os.makedirs(result)
        os.makedirs(error)
    elif content is not None:
        with open(result, 'w', encoding='utf-8') as fp:
            fp.write(content[0])
        if content[1]:
            with open(error, 'w', encoding='utf-8') as fp:
                fp.write(content[1])
    return content


def requests(ctx):
    out = []

    def req(method, path, payload=None, before=None, after=view):
        out.append((method, path, payload, {'before': before, 'after': after}))

    START, START_ALL, ENSURE = '/api/upload/start', '/api/upload/start-all', '/api/upload/ensure-session'
    FINAL = {'stop_before_submit': False, 'confirm_final_publish': True}

    def throw(error):
        return lambda c, *a: (_ for _ in ()).throw(error)

    # ---- /api/upload/start：校验
    req('POST', START, {'platform': 'taobao'}, cfg())
    req('POST', START, {'account_profile': 'someone-else'}, cfg())
    req('POST', START, {'stop_before_submit': False}, cfg())
    req('POST', START, {'record_id': 999}, cfg())
    req('POST', START, {'expected_record_revision': 'abc'}, cfg())
    req('POST', START, {'record_id': 301, 'expected_record_revision': 'stale'}, cfg())
    req('POST', START, {'record_id': 301}, cfg(active=TAOBAO))                                             # 当前账户是淘宝：平台门禁拒绝
    # ---- 启动：DOM 路线（同步线程，请求返回时任务已结束）
    req('POST', START, {'record_id': 301}, cfg())                                                          # 默认：停在提交前
    req('POST', START, dict({'record_id': 301}, account_profile=DEFAULT, **FINAL), cfg())                  # 最终发布（带当前账户快照）
    req('POST', START, {'record_id': 301, 'stop_before_submit': True}, cfg(behavior={'fill_title_for_record': throw(ValueError('标题炸了'))}))
    req('POST', START, dict({'record_id': 302}, **FINAL), cfg(behavior={'prepare_record_assets': lambda c, record: (None, '标题为空！！！')}))
    req('POST', START, dict({'record_id': 301}, **FINAL), cfg(behavior={'open_publish_page': lambda c, tab, report: False}))
    req('POST', START, dict({'record_id': 301}, **FINAL), cfg(behavior={'submit_publish': raises('提交未确认')}))
    req('POST', START, dict({'record_id': 301}, **FINAL), cfg(behavior={'configure_sku_structure': raises('码数下拉未能展开')}))
    req('POST', START, {'record_id': 301}, cfg(behavior={'fill_title_for_record': throw(ValueError('又炸了')), 'record_error_raises': True}))   # 记录错误本身也失败
    req('POST', START, {'record_id': 301}, cfg(active_page=None, behavior={'attach_tab': True}))            # 没有浏览器：复用已有的
    req('POST', START, {'record_id': 301}, cfg(active_page=None, behavior={'open_page_fails': True}))        # 启动浏览器失败
    req('POST', START, {'record_id': 301}, cfg(active_page=None))                                          # 没有浏览器、新开一个
    req('POST', START, {'record_id': 301}, cfg(active_page='页面已关闭', behavior={'attach_tab': True}))      # 页面失效后重新附着（附着后页面恢复）
    req('POST', START, {'record_id': 301}, cfg(active_page='页面已关闭', behavior={'attach_tab': 'tab_only'}))   # 页面失效、附着只给标签页
    req('POST', START, {'record_id': 301}, cfg(active_page='页面已关闭'))                                   # 页面失效后重开
    req('POST', START, {'record_id': 301}, cfg(active_page='页面已关闭', behavior={'open_page_fails': True}))   # 页面失效、重开失败
    req('POST', START, {'record_id': 301}, cfg(behavior={'tab_get_fails': True}))                          # 导航失败两次
    req('POST', START, {'record_id': 301}, cfg(behavior={'wait_login_complete': lambda c, tab, report: False}))   # 等登录超时
    req('POST', START, {'record_id': 301}, cfg(automation={'publish_mode': 'official'}))
    req('POST', START, {'record_id': 301}, cfg(behavior={'settings_raise': 2}))                             # 流水线里读设置失败：generic 的“意外错误”
    req('POST', START, {'record_id': 301}, cfg(behavior={'settings_raise': 1}))                             # worker 自己读设置失败
    req('POST', START, {'record_id': 301}, cfg(db=empty_table))                                            # 商品表是空的（记录被删了）
    req('POST', START, {'record_id': 301}, cfg(thread_hook=lambda c: cancel_all_pending(c)))               # 启动后、开跑前被取消
    req('POST', START, {'record_id': 301}, cfg(behavior={'dismiss_pending_browser_alert': cancel_running}))    # 流程开始前被取消
    # ---- 配置读取：材质 / 运费模板 / 水洗标图
    req('POST', START, {'record_id': 301}, cfg(automation={'shipping_template': '  顺丰  ', 'material_compositions': [
        {'material': ' 棉 ', 'percentage': '60.9'}, {'material': '', 'percentage': 10}, 'bad', {'material': '氨纶', 'percentage': 'x'},
        {'material': '涤纶', 'percentage': 40}], 'wash_label_tag_image_path': '/no/such/tag.png'}))
    # ---- 一键发布全部（现状：worker 载入全部记录，而不是数出来的 status=0 那几条）
    req('POST', START_ALL, {'platform': 'taobao'}, cfg())
    req('POST', START_ALL, {'account_profile': 'someone-else'}, cfg())
    req('POST', START_ALL, {}, cfg(active=TAOBAO))
    req('POST', START_ALL, {'stop_before_submit': False}, cfg())
    req('POST', START_ALL, {}, cfg())
    req('POST', START_ALL, FINAL, cfg())
    req('POST', START_ALL, {}, cfg(db=mark_all(1)))                                                        # 没有待上传的商品
    req('POST', START_ALL, {}, cfg(behavior={'fill_title_for_record': lambda c, tab, record: (_ for _ in ()).throw(ValueError('第%d条炸了' % record.id)) if record.id == 302 else None}))
    # ---- 状态 / 取消 / 列表
    seeded = {'run1': {'task_id': 'run1', 'status': 'running', 'created_at': '2026-10-02T10:00:00', 'platform': 'douyin'},
              'done1': {'task_id': 'done1', 'status': 'success', 'created_at': '2026-10-01T10:00:00'}}
    req('GET', '/api/upload/status/nope', None, cfg(seed=seeded))
    req('GET', '/api/upload/status/run1', None, cfg())
    req('POST', '/api/upload/cancel/nope', None, cfg())
    for status in ('success', 'completed', 'failed', 'cancelled'):
        req('POST', '/api/upload/cancel/c-' + status, None, cfg(seed={'c-' + status: {'task_id': 'c-' + status, 'status': status}}))
    req('POST', '/api/upload/cancel/run1', None, cfg())
    req('GET', '/api/upload/tasks', None, cfg(active_page=None))
    req('GET', '/api/upload/tasks', None, cfg(cleanup_tasks=True))
    req('POST', START_ALL, {}, cfg(behavior={'settle_between_records': lambda c, tab: cancel_running(c)}))   # 批量中途被取消
    # ---- 会话
    req('POST', ENSURE, {}, cfg(active_page=None, behavior={'attach_tab': True}))
    req('POST', ENSURE, {}, cfg(active_page=None, behavior={'open_page_fails': True}))
    req('POST', ENSURE, {}, cfg())
    req('POST', ENSURE, {}, cfg(behavior={'tab_get_fails': True}))
    req('POST', ENSURE, {}, cfg(behavior={'tab_props_raise': True}))
    req('POST', ENSURE, {}, cfg(behavior={'wait_login_complete': raises('登录检测炸了')}))
    req('POST', ENSURE, {}, cfg(active=TAOBAO))
    # ---- 旧 /start（同步，不建任务）
    req('POST', '/start', {'record_id': 301}, cfg(cleanup_tasks=True))
    req('POST', '/start', {'record_id': 301, 'stop_before_submit': False}, cfg())
    req('POST', '/start', dict({'record_id': 302}, **FINAL), cfg())
    req('POST', '/start', {'record_id': 999}, cfg())
    # ---- 协议流水线（经任务 worker 与旧 /start 两个入口）
    proto = {'publish_mode': 'protocol', 'shipping_template': '顺丰', 'material_compositions': [{'material': '棉', 'percentage': 80}, {'material': '氨纶', 'percentage': 20}]}
    online = lambda url: [{'type': 'page', 'url': 'https://fxg.jinritemai.com/home', 'webSocketDebuggerUrl': 'ws://x'}]
    cancel_while_polling = lambda url: (cancel_running(ctx), online(url))[1]
    extra = add_records(
        (305, '白袜_货号_e_没价格', json.dumps([{'name': '白色', 'price': 0}]), {}),
        (306, '白袜_货号_f_坏内容', 'not json', {}),
        (307, '白袜_货号_g_怪SKU', lambda c: json.dumps([{'name': 'A', 'price': 'x', 'quantity': 'many', 'path': c.state['image']},
                                                       {'name': 'B', 'price': 7, 'stock': 8}, {'name': 'C', 'price': 6, 'path': '/missing.jpg'}]), {}))
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=online))
    req('POST', START, dict({'record_id': 301}, **FINAL), cfg(automation=proto, urlopen=online))                 # 最终发布成功
    req('POST', START, dict({'record_id': 301}, **FINAL), cfg(automation=proto, urlopen=online,
                                                                protocol={'success': False, 'error': {'message': '类目不对', 'detail': '请重选'}, 'steps': []}))
    req('POST', START, dict({'record_id': 301}, **FINAL), cfg(automation=proto, urlopen=online, protocol={'success': False}))
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=online, protocol={'success': True, 'data': {'product_id': 'P1', 'stopped_before_submit': True}, 'steps': []}))
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=online, protocol=RuntimeError('网络断了')))     # 流水线抛异常
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=online, no_module=True))                       # 协议模块导入失败
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=online, cookie_count=0))                      # 一直没登录
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=online, href='https://fxg.jinritemai.com/login?x=1'))
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=online, behavior={'ws': 'timeout_first'}))     # 读 WebSocket 超时一次再继续
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=online, behavior={'ws': 'recv_error'}))        # 读 WebSocket 出错
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=online, behavior={'ws': 'connect_fails'}))     # 连不上 WebSocket
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=online, pics={'800': []}))                    # 没有主图
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=online, pics={'800': [ctx.state['image']], '750': [], 'detail': []}))   # 3:4 缺失用 1:1 回退
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=online, behavior={'pics_raise': True}))       # 取图片列表出错
    req('POST', START, {'record_id': 304}, cfg(automation=proto, urlopen=online))                                      # 标题为空：取记录名
    req('POST', START, {'record_id': 302}, cfg(automation=proto, urlopen=online, pics={'800': ['/missing.jpg'], '750': [], 'detail': []}))
    req('POST', START, {'record_id': 999}, cfg(automation=proto, urlopen=online))
    req('POST', START, {'record_id': 305}, cfg(automation=proto, urlopen=online, db=extra))                            # 没有有效价格
    req('POST', START, {'record_id': 306}, cfg(automation=proto, urlopen=online, db=extra))                            # 记录内容不是 JSON
    req('POST', START, {'record_id': 307}, cfg(automation=proto, urlopen=online, db=extra))                            # SKU 的价格 / 数量怪异，有一张存在的 SKU 图
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=cancel_while_polling))                       # 登录检测期间被取消，流程在记录循环里发现
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=online, thread_hook=lambda c: cancel_all_pending(c)))   # 协议模式：启动后、开跑前被取消
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=online, behavior={'settings_raise': 1}))      # 协议模式：worker 读设置失败
    req('POST', START_ALL, {}, cfg(automation=proto, urlopen=online))                                                 # 全部记录、两条之间停 2 秒
    req('POST', START_ALL, {}, cfg(automation=proto, urlopen=online, protocol={'success': False, 'error': 'plain', 'steps': []}))   # 全部失败
    req('POST', '/start', {'record_id': 301}, cfg(automation=proto, urlopen=online))
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=None))                                        # 找不到 /json/list：协议浏览器起不来
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=None, behavior={'cdp_port': 9444}))           # 新开浏览器后找到端口，但一直没登录
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=None, behavior={'open_page_fails': True}))     # 新开浏览器失败
    req('POST', START, {'record_id': 301}, cfg(automation=proto, urlopen=lambda url: [], browsers=[{'debug_address': '127.0.0.1:9501'}, {'debug_address': '127.0.0.1:9502'}],
                                                targets={'127.0.0.1:9501': [{'url': 'https://example.com'}], '127.0.0.1:9502': [{'url': 'https://fxg.jinritemai.com/x'}]}))   # 进程枚举找到已有浏览器
    # ---- 调试注入文件 / 协议运行时配置
    for content in (None, ('{"ok": 1}', 'boom'), ('not json', ''), 'dirs'):
        req('GET', '/api/upload/debug/injection', None, cfg(), after=lambda c, content=content: dict(view(c), files=_inject_files(c, content)))
    probe_payload = {'categoryKeywords': ' 袜子 , 船袜,', 'category_id': 123, 'includeFreight': False, 'timeoutSeconds': 1000,
                     'cdp_list_url': 'http://127.0.0.1:9333/json/list', 'target_url_contains': 'ffa', 'operation_type': 'edit'}
    req('POST', '/api/protocol/fxg/runtime-options', {}, cfg())
    req('POST', '/api/protocol/fxg/runtime-options', probe_payload, cfg())
    req('POST', '/api/protocol/fxg/runtime-options', {'category_keyword': '袜子'}, cfg(probe={'code': 2, 'stderr': '脚本报错'}))
    req('POST', '/api/protocol/fxg/runtime-options', {'category_keyword': '袜子'}, cfg(probe={'code': 2, 'stdout': 'out', 'stderr': ''}))
    req('POST', '/api/protocol/fxg/runtime-options', {'category_keyword': '袜子'}, cfg(probe={'code': 3, 'stdout': '', 'stderr': ''}))
    req('POST', '/api/protocol/fxg/runtime-options', {'category_keyword': '袜子'}, cfg(probe={'code': 0, 'stdout': ' '}))
    req('POST', '/api/protocol/fxg/runtime-options', {'category_keyword': '袜子'}, cfg(probe={'code': 0, 'stdout': 'not json'}))
    req('POST', '/api/protocol/fxg/runtime-options', {'category_keyword': '袜子'}, cfg(behavior={'no_node': True}))
    req('POST', '/api/protocol/fxg/runtime-options', {'category_keyword': '袜子'}, cfg(mcp_env=False))               # 没配 mcp 目录：找不到脚本
    req('POST', '/api/protocol/fxg/runtime-options', {'category_keyword': '袜子'}, cfg(mcp_env=False), after=lambda c: dict(view(c), made=_make_default_mcp(c)))
    req('POST', '/api/protocol/fxg/runtime-options', {'category_keyword': '袜子'}, cfg(mcp_env=False))               # 入口旁边有 mcp-server：用它
    # ---- 账户切换 / 保存 / 更新器读到的任务表
    seed_running = {'busy': {'task_id': 'busy', 'status': 'running', 'record_id': None, 'platform': 'douyin'}}
    req('POST', '/save_info', {'_id': 301, 'title': '改标题'}, cfg(cleanup_tasks=True, seed=seed_running))
    req('GET', '/internal/update-readiness', None, cfg(cleanup_tasks=True, seed=seed_running))
    req('GET', '/internal/update-readiness', None, cfg(cleanup_tasks=True))
    return out


def cancel_all_pending(ctx):
    with lock_of(ctx):
        for task in tasks_of(ctx).values():
            if task.get('status') == 'pending':
                task['cancelled'] = True


def _make_default_mcp(ctx):
    """在入口文件旁边造一个 mcp-server/scripts/probe-fxg-runtime-options.mjs，后面的请求（没配环境变量）会走到第二个候选。"""
    scripts = os.path.join(ctx.data_dir, 'entry', 'mcp-server', 'scripts')
    os.makedirs(scripts, exist_ok=True)
    with open(os.path.join(scripts, 'probe-fxg-runtime-options.mjs'), 'w', encoding='utf-8') as fp:
        fp.write('// probe')
    return True


def final(ctx):
    restore_table(ctx)
    entry = os.path.join(ctx.data_dir, 'entry')
    logs = {}
    for name in ('run_task_diag.log', 'protocol_diag.log'):
        path = os.path.join(entry, name)
        logs[name] = open(path, encoding='utf-8').read().splitlines() if os.path.exists(path) else None
    return {'diag_logs': logs, 'cdp_port_env': os.environ.get('CDP_PORT'), 'tasks': _json_safe(tasks_of(ctx)),
            'records': [[r.id, r.status] for r in ctx.Record.select().order_by(ctx.Record.id)]}


SCENARIOS['upload'] = dict(setup=setup, patch_old=install, patch_new=install, new_via_app=True, requests=requests, final=final)

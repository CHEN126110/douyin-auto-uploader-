# -*- coding: utf-8 -*-
"""淘宝发布（/api/taobao/*）的新旧对打场景（2026-10-20）。

走 app.py 自己的装配（``new_via_app=True``）：旧版用搬迁前的 app.py，新版用搬迁后的 app.py + src/sidecar/taobao_*。
同一套假件、同一套请求，响应、任务字典、假件调用记录、落盘文件必须逐字相同。

⚠️ 2026-10-21 起「必须逐字相同」不再成立：批量发布的三个既有问题（外加同日补修的第 25 条）作为独立的行为修改修掉了（旧版 = 搬迁前的 app.py，保持原样），
新旧对打因此有 18 个请求不同（``cmp`` 直接比；其中 2 个只是任务 id 整体后移造成的，规整 id 后剩 16 个实质差异），``final`` 里只有 ``env`` 一项不同，分五类——
类目关键词（旧 ``'2'`` / 新 ``'中筒袜'``）、有任务在跑时 ``start-all``（旧：照样启动；新：409）、
批量里翻译抛 ValueError（旧：线程崩溃、任务停在 ``pending``；新：只让那一条失败）、批量运行中的状态（旧 ``pending`` / 新 ``running``）、
批量跑完后进程里的 ``TAOBAO_MEDIA_ROUTE``（旧：一直留着 ``protocol``；新：还原成进来时的样子，所以每个跑完批量的请求的 ``media_route_env`` 和 ``final.env`` 都不同）。
旧版在有任务在跑时多创建的那个任务还会让假 uuid 多走一格，后面的任务 id 整体差 1，直到 ``uuid_at`` 重置。
逐项的差异清单和复现方法见 docs/架构重构方案_2026-10-18.md 的 12.3；这份场景的价值现在是「差异恰好就是这些、没有别的」，不是「diff 为空」。

用的是**真实**的 ``taobao_publish`` 包和 ``src.shop_session`` 账户注册表（落在隔离数据目录里），只把会连浏览器 / 平台的地方换成假件：
  - ``pipeline.run_from_record``：按「行为表」应答，记录每次调用收到的全部参数（授权快照、素材准备回调、取消钩子的当时取值、环境变量 …）；
  - ``folder_import.make_preparer``、``desktop.desktop_readiness / prepare_product / export_packet``：假的；
  - 账户的浏览器：旧版换 app.py 里的别名，新版换 ``shop_session_service`` 对象的方法（服务类持有的就是它）；
  - ``uuid.uuid4``：确定性序列，任务 id 因此可预测；``_bootstrap_log``：记录而不写文件。
发布线程是后台线程：每个启动请求的 after 钩子等线程结束再取快照；``hold`` 行为让流水线停在半路，用来稳定地测并发 / 取消。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime
from types import SimpleNamespace

from scenarios import SCENARIOS
from slice_defs_taobao import SERVICE_METHODS

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
PKG_ROOT = os.path.join(REPO, 'taobao-publisher')
# 商品目录放在系统临时目录下的固定位置：素材记录的文件名是（商品 id、目录、账户）的摘要，
# 两次运行（旧 / 新）的目录必须相同，摘要才可比
PRODUCTS = os.path.join(tempfile.gettempdir(), 'taobao_diff_products')

DEFAULT, DOUYIN, TAOBAO, XHS = 'upload-browser-profile', 'shop-aaaaaaaa', 'taobao-bbbbbbbb', 'xhs-cccccccc'
START = '/api/taobao/publish/start'
START_ALL = '/api/taobao/publish/start-all'
PREPARE = '/api/taobao/publish/prepare'
EXPORT = '/api/taobao/publish/export'
STATUS = '/api/taobao/publish/status/'
CANCEL = '/api/taobao/publish/cancel/'
TASKS = '/api/taobao/publish/tasks'
READINESS = '/api/taobao/readiness'

HELPER_NAMES = ('_parse_taobao_publish_options', '_taobao_product_from_record')
EXPECTED_PIPELINE_KWARGS = {
    'dry_run', 'stop_before_submit', 'authorization', 'progress_callback', 'cdp_list_url', 'account_profile',
    'media_preparer', 'write_artifact', 'should_cancel', 'listing_mode', 'save_draft',
}


# ---------------------------------------------------------------------------------------------- 模式无关的访问器
def _svc(ctx):
    return ctx.mod.taobao_service


def tasks_of(ctx):
    return ctx.mod._taobao_tasks if ctx.mode == 'old' else _svc(ctx).tasks


def lock_of(ctx):
    return ctx.mod._taobao_tasks_lock if ctx.mode == 'old' else _svc(ctx).lock


def helpers_module():
    import src.sidecar.taobao_helpers as helpers
    return helpers


def fn(ctx, old_name):
    """旧函数名 -> 当前模式下可调用的函数对象。"""
    if old_name in HELPER_NAMES:
        return getattr(ctx.mod if ctx.mode == 'old' else helpers_module(), old_name)
    if ctx.mode == 'old':
        return getattr(ctx.mod, old_name)
    return getattr(_svc(ctx), SERVICE_METHODS[old_name])


def const(ctx, name):
    return getattr(ctx.mod if ctx.mode == 'old' else helpers_module(), name)


# ---------------------------------------------------------------------------------------------- 假件
def _json_safe(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=repr))


class Result:
    def __init__(self, payload):
        self._payload = payload

    def to_dict(self):
        return json.loads(json.dumps(self._payload))


def _steps(*names):
    return [{'name': name, 'status': 'ok'} for name in names]


def _complete_verification():
    from taobao_publish.verification import WHOLE_FORM_SCOPE
    return {
        'complete': True, 'status': 'complete',
        'required_field_coverage': {
            'known': True, 'completePage': True, 'scope': WHOLE_FORM_SCOPE, 'rowCount': 3,
            'required': [{'label': '宝贝标题', 'hitCount': 1, 'supportedReader': True}],
            'checked': [{'label': '宝贝标题', 'value': '甲标题'}], 'checkedCount': 1,
        },
    }


def _observation(product_dir, name='白色.jpg'):
    return {'path': os.path.join(product_dir, 'SKU', name), 'role': 'sku', 'name': name,
            'sha256': 'a' * 64, 'status': 'located', 'folder_path': ['袜子', '甲']}


def make_pipeline(ctx):
    state = ctx.state

    def run_from_record(row, request_payload, **kw):
        behavior = state['pipeline']
        auth = kw['authorization']
        call = {
            'row_id': row.get('id'), 'request': request_payload,
            'dry_run': kw['dry_run'], 'stop_before_submit': kw['stop_before_submit'],
            'auth': [auth.source, sorted(auth.granted), auth.submit_unlocked],
            'cdp_list_url': kw['cdp_list_url'], 'account_profile': kw['account_profile'],
            'media_preparer': kw['media_preparer'], 'write_artifact': kw['write_artifact'],
            'listing_mode': kw['listing_mode'], 'save_draft': kw['save_draft'],
            'media_route_env': os.environ.get('TAOBAO_MEDIA_ROUTE'),
            'cancel_at_entry': kw['should_cancel'](),
            'unexpected_kwargs': sorted(set(kw) - EXPECTED_PIPELINE_KWARGS),
        }
        state['pipeline_calls'].append(call)
        progress = kw['progress_callback']
        progress(10, '开始', 'session', _steps('session'))
        if behavior.get('hold') and (behavior.get('hold_on') in (None, row.get('id'))):
            state['entered'].set()
            state['release'].wait(20)
        call['cancel_after_hold'] = kw['should_cancel']()
        progress(60, '填写中', 'fill', _steps('session', 'fill'))
        if behavior.get('mutate_tasks'):
            behavior['mutate_tasks'](ctx)
            progress(80, '收尾', 'verify', _steps('session', 'fill', 'verify'))      # 任务已不在表里：进度回调要安静地返回
        if behavior.get('raise'):
            raise behavior['raise']
        kind = behavior.get('kind', 'ok')
        if kind == 'ok_per_record':
            kind = behavior['per_record'].get(row.get('id'), 'ok')
        if kind == 'raise_per_record':
            raise RuntimeError('模拟：这条商品的流水线崩溃')
        if kind == 'cancelled' or (behavior.get('cancel_aware') and call['cancel_after_hold']):
            return Result({'success': False, 'steps': _steps('session'), 'dry_run': kw['dry_run'],
                           'stopped_before_submit': kw['stop_before_submit'],
                           'error': {'code': 'CANCELLED', 'message': '流水线在阶段边界停止'}, 'blockers': []})
        if kind == 'fail':
            return Result({'success': False, 'steps': _steps('session') + [{'name': 'fill', 'status': 'failed'}],
                           'dry_run': kw['dry_run'], 'stopped_before_submit': kw['stop_before_submit'],
                           'error': {'code': 'FILL_FAILED', 'message': behavior.get('fail_message', '填写阶段未通过')},
                           'blockers': ['标题为空', '类目未选择']})
        if kind == 'fail_silent':
            return Result({'success': False, 'steps': [], 'error': None, 'blockers': None})
        steps = _steps('session', 'fill')
        if behavior.get('draft'):
            steps.append({'name': 'save_draft', 'status': 'ok'})
        elif behavior.get('draft_skipped'):
            steps.append({'name': 'save_draft', 'status': 'skipped'})
        data = {}
        if behavior.get('verification') == 'complete':
            data['form_verification'] = _complete_verification()
        elif behavior.get('verification') == 'incomplete':
            data['form_verification'] = {'complete': False, 'status': 'partial'}
        elif behavior.get('verification') == 'complete_but_dry_run_flag':
            data['form_verification'] = _complete_verification()
        elif behavior.get('verification') == 'complete_no_coverage':
            data['form_verification'] = {'complete': True, 'status': 'complete'}       # 自称完整，但没有整页必填的覆盖证据
        if behavior.get('observations'):
            data['media_observations'] = behavior['observations']
        payload = {'success': True, 'steps': steps, 'data': data, 'error': None, 'blockers': [],
                   'dry_run': kw['dry_run'], 'stopped_before_submit': kw['stop_before_submit']}
        if behavior.get('verification') == 'complete_but_dry_run_flag':
            payload['dry_run'] = True            # 回执自称是 dry-run：不能认定「完整填写」
        if behavior.get('empty_payload_steps'):
            payload['steps'] = []
        return Result(payload)
    return run_from_record


def _desktop_effect(ctx, key, ok_value):
    mode = ctx.state['desktop'].get(key, 'ok')
    if mode == 'ok':
        return ok_value
    raise {'value_error': ValueError('模拟：资料不合法'), 'import_error': ImportError('模拟：缺依赖'),
           'os_error': OSError('模拟：磁盘错误'), 'runtime_error': RuntimeError('模拟：未预期的错误')}[mode]


def install_package_fakes(ctx):
    """真实的 taobao_publish 包 + 只替换会连浏览器 / 平台的几个入口（两种模式都一样）。"""
    state = ctx.state
    if PKG_ROOT not in sys.path:
        sys.path.insert(0, PKG_ROOT)
    from taobao_publish import desktop, folder_import, pipeline
    from taobao_publish.verification import whole_form_coverage_confirmed
    # 夹具必须真的让「整页必填已确认」成立，否则 worker 里相应的那条消息分支永远走不到
    assert whole_form_coverage_confirmed(_complete_verification()['required_field_coverage'])

    def desktop_readiness():
        return _desktop_effect(ctx, 'readiness', {'ready': True, 'checks': ['contracts', 'assets']})

    def prepare_product(record, overrides):
        return _desktop_effect(ctx, 'prepare', {'record_id': record.get('id'), 'overrides': overrides, 'ok': True})

    def export_packet(record, overrides, output_base):
        def make():
            os.makedirs(str(output_base), exist_ok=True)
            with open(os.path.join(str(output_base), 'packet-%s.json' % record.get('id')), 'w', encoding='utf-8') as fp:
                json.dump({'record_id': record.get('id'), 'overrides': overrides}, fp, ensure_ascii=False, sort_keys=True)
            return {'record_id': record.get('id'), 'output_base': str(output_base)}
        return _desktop_effect(ctx, 'export', make) if state['desktop'].get('export', 'ok') != 'ok' else make()

    desktop.desktop_readiness = desktop_readiness
    desktop.prepare_product = prepare_product
    desktop.export_packet = export_packet
    folder_import.make_preparer = lambda profile, url: 'preparer(%s|%s)' % (profile, url)
    pipeline.run_from_record = make_pipeline(ctx)


def install_mode_fakes(ctx):
    """账户的浏览器能力、启动日志、uuid：旧版换 app.py 的全局，新版换服务对象的属性。"""
    state = ctx.state

    def activate_profile(profile_name, open_browser=False, browser_url=None, **kwargs):
        state['shop_calls'].append(['activate', profile_name, open_browser, browser_url, sorted(kwargs)])
        mode = state['shop'].get('activate', 'ok')
        if mode == 'ok':
            return {'active_profile': profile_name, 'browser_opened': True, 'debug_address': 'localhost:9501'}
        if mode == 'wrong_profile':
            return {'active_profile': 'other-00000000', 'browser_opened': True, 'debug_address': '127.0.0.1:9501'}
        if mode == 'not_opened':
            return {'active_profile': profile_name, 'browser_opened': False, 'browser_error': 'Chrome启动失败'}
        if mode == 'not_opened_silent':
            return {'active_profile': profile_name, 'browser_opened': False}
        if mode == 'no_address':
            return {'active_profile': profile_name, 'browser_opened': True, 'debug_address': ''}
        if mode == 'os_error':
            raise OSError('模拟：无法启动浏览器进程')
        raise KeyError('profile')

    def resolve_active_browser(platform=None, **kwargs):
        state['shop_calls'].append(['resolve', platform, sorted(kwargs)])
        if state['shop'].get('resolve', 'ok') == 'ok':
            return '127.0.0.1:9502', {'pid': 4242}, 'fake'
        return '', None, 'none'

    def bootstrap_log(message):
        state['logs'].append(message)

    if ctx.mode == 'old':
        ctx.mod._activate_shop_profile = activate_profile
        ctx.mod._resolve_active_shop_browser = resolve_active_browser
        ctx.mod._bootstrap_log = bootstrap_log
    else:
        service = ctx.mod.shop_session_service
        service.activate_profile = activate_profile
        service.resolve_active_browser = resolve_active_browser
        _svc(ctx)._bootstrap_log = bootstrap_log

    # 保存商品成功时响应里有 update_time（精确到分钟），把 app 里的 time 换成固定值
    ctx.mod.time = SimpleNamespace(now=lambda: datetime(2026, 10, 20, 12, 0, 0), sleep=lambda seconds: None)

    counter = state['uuid_counter']

    def uuid4():
        counter[0] += 1
        return uuid.UUID(int=(0x1000 + counter[0]) << 96)
    uuid.uuid4 = uuid4


def install(ctx):
    install_package_fakes(ctx)
    install_mode_fakes(ctx)


# ---------------------------------------------------------------------------------------------- 夹具
def _entry(slug, platform, label=None):
    return {'profile_name': slug, 'platform': platform, 'label': label, 'created_at': '2026-10-01T09:00:00',
            'shop_id': None, 'shop_name': None, 'last_seen_at': None, 'seen_count': 0}


def setup(ctx):
    from src import shop_session
    shop_session.save_registry({
        'active_profile': TAOBAO,
        'profiles': {DEFAULT: _entry(DEFAULT, 'douyin'), DOUYIN: _entry(DOUYIN, 'douyin', '甲店'),
                     TAOBAO: _entry(TAOBAO, 'taobao', '乙淘宝'), XHS: _entry(XHS, 'xiaohongshu', '丙小红书')},
    })
    state = ctx.state
    state.update(pipeline={}, desktop={}, shop={}, pipeline_calls=[], logs=[], shop_calls=[], seen={},
                 uuid_counter=[0], entered=threading.Event(), release=threading.Event())
    shutil.rmtree(PRODUCTS, ignore_errors=True)
    os.makedirs(PRODUCTS)

    def product(slug, names):
        base = os.path.join(PRODUCTS, slug)
        os.makedirs(os.path.join(base, 'SKU'))
        content = []
        for index, name in enumerate(names):
            path = os.path.join(base, 'SKU', name + '.jpg')
            with open(path, 'wb') as fp:
                fp.write(b'img-' + name.encode('utf-8'))
            content.append({'path': path, 'name': name, 'price': 12.5 + index})
        return base, content

    base_a, content_a = product('prod_a', ['白色', '黑色'])
    base_b, content_b = product('prod_b', ['灰色'])
    base_s, content_s = product('prod_s', ['红色'])
    state['dirs'] = {'a': base_a, 'b': base_b, 's': base_s}
    state['contents'] = {'a': content_a, 'b': content_b, 's': content_s}
    R = ctx.Record
    common = dict(type=1, update_time=datetime(2026, 1, 1), source_url='https://example.invalid/x')
    R.create(id=201, name='袜子甲', path=base_a, status=0, repo=5, title='甲标题', clazz='2',
             content=json.dumps(content_a, ensure_ascii=False), **common)
    R.create(id=202, name='袜子乙', path=base_b, status=0, repo=0, title='', clazz='1',
             content=json.dumps(content_b, ensure_ascii=False), **common)
    R.create(id=203, name='相对路径', path='uploads/products/C', status=1, repo=1, title='丙', clazz='3',
             content=json.dumps([{'path': 'c.jpg', 'name': '丙色', 'price': 9}], ensure_ascii=False), **common)
    R.create(id=204, name='保存用', path=base_s, status=1, repo=7, title='保存前的标题', clazz='2',
             content=json.dumps(content_s, ensure_ascii=False), **common)


# ---------------------------------------------------------------------------------------------- 钩子
def join_workers(timeout=20.0):
    deadline = time.monotonic() + timeout
    names = ('publish_task', 'publish_batch_task')
    for thread in [t for t in threading.enumerate() if any(n in t.name for n in names)]:
        thread.join(max(0.0, deadline - time.monotonic()))
    left = [t.name for t in threading.enumerate() if any(n in t.name for n in names)]
    assert not left, '淘宝发布线程没有按时结束: %s' % left


def tid(n):
    """``cfg(uuid_at=n)`` 之后创建的第一个任务的 id（假 uuid4 是确定性序列，前 8 位是十六进制的 0x1000 + 序号）。"""
    return '%08x' % (0x1000 + n)


def cfg(pipeline=None, desktop=None, shop=None, env=None, active=None, do=None, uuid_at=None):
    """请求前把假件行为重置为默认值再叠加覆盖；当前账户默认是淘宝账户；环境变量 / 任务表 / 任务 id 序号按需设定。"""
    active = TAOBAO if active is None else active

    def before(ctx):
        join_workers()                       # 上一个请求留下的发布线程必须先结束，否则它会和这次的重置赛跑
        state = ctx.state
        if uuid_at is not None:
            state['uuid_counter'][0] = uuid_at - 1
        state['pipeline'] = dict(pipeline or {})
        state['desktop'] = dict(desktop or {})
        state['shop'] = dict(shop or {})
        state['entered'].clear()
        state['release'].clear()
        if env is None:
            os.environ.pop('TAOBAO_MEDIA_ROUTE', None)
        else:
            os.environ['TAOBAO_MEDIA_ROUTE'] = env
        from src import shop_session
        registry = shop_session.load_registry()
        if registry['active_profile'] != active:
            registry['active_profile'] = active
            shop_session.save_registry(registry)
        if do is not None:
            do(ctx)
    return before


def view(ctx, extra=None):
    """等发布线程结束，取任务表和自上次以来的假件记录。"""
    join_workers()
    state = ctx.state
    out = {}
    with lock_of(ctx):
        out['tasks'] = _json_safe(tasks_of(ctx))
    for key in ('pipeline_calls', 'logs', 'shop_calls'):
        seen = state['seen'].get(key, 0)
        out[key] = _json_safe(state[key][seen:])
        state['seen'][key] = len(state[key])
    out['media_route_env'] = os.environ.get('TAOBAO_MEDIA_ROUTE')
    if extra:
        out.update(extra(ctx))
    return out


def settle(extra=None):
    return lambda ctx: view(ctx, extra)


def hold_entered(ctx):
    assert ctx.state['entered'].wait(20), '流水线没有按时进入 hold'
    return view_without_join(ctx)


def view_without_join(ctx):
    state = ctx.state
    with lock_of(ctx):
        tasks = _json_safe(tasks_of(ctx))
    return {'tasks': tasks, 'calls_so_far': len(state['pipeline_calls'])}


def release_and_settle(ctx):
    right_after = view_without_join(ctx)
    ctx.state['release'].set()
    out = view(ctx)
    out['before_release'] = right_after
    return out


def seed_task(task_id, status, record_id=None, **extra):
    def do(ctx):
        with lock_of(ctx):
            tasks_of(ctx)[task_id] = dict({'task_id': task_id, 'platform': 'taobao', 'status': status,
                                           'record_id': record_id, 'record_name': '种子任务',
                                           'created_at': '2026-10-02T10:00:00'}, **extra)
    return do


def clear_tasks(ctx):
    with lock_of(ctx):
        tasks_of(ctx).clear()


def delete_tasks_midway(ctx):
    """流水线跑到一半，任务从表里消失（比如被人清掉）：进度回调和收尾都得安静地返回。"""
    clear_tasks(ctx)


def with_other_task(ctx):
    seed_task('other', 'running', record_id=202)(ctx)


def reset_default_pipeline_state(ctx):
    pass


def make_extra_record(ctx):
    ctx.Record.create(id=205, name='没有目录', path='', status=0, repo=1, title='', clazz='2',
                      content=json.dumps([{'path': 'x.jpg', 'name': '黄色', 'price': 8}], ensure_ascii=False),
                      type=1, update_time=datetime(2026, 1, 5), source_url='https://example.invalid/e')


def drop_extra_record(ctx):
    ctx.Record.delete().where(ctx.Record.id == 205).execute()


def make_status_zero_none(ctx):
    ctx.Record.update(status=1).where(ctx.Record.status == 0).execute()


def restore_status_zero(ctx):
    ctx.Record.update(status=0).where(ctx.Record.id.in_([201, 202])).execute()


def failing_receipts(ctx):
    import src.product_media as product_media
    ctx.state['orig_save_receipts'] = product_media.save_receipts

    def boom(storage, record, profile, observations):
        raise OSError('模拟：目录记录写盘失败')
    product_media.save_receipts = boom


def restore_receipts(ctx):
    import src.product_media as product_media
    original = ctx.state.pop('orig_save_receipts', None)
    if original is not None:
        product_media.save_receipts = original


def tree(root):
    out = []
    if os.path.isdir(root):
        for base, _dirs, files in os.walk(root):
            for name in sorted(files):
                path = os.path.join(base, name)
                with open(path, 'rb') as fp:
                    body = fp.read()
                try:
                    body = json.loads(body.decode('utf-8'))
                except (ValueError, UnicodeDecodeError):
                    body = '<%d bytes>' % len(body)
                out.append([os.path.relpath(path, root).replace(os.sep, '/'), body])
    return sorted(out, key=lambda item: item[0])


# ---------------------------------------------------------------------------------------------- 请求
def req(method, path, payload=None, before=None, after=None, **opts):
    if before:
        opts['before'] = before
    if after:
        opts['after'] = after
    return (method, path, payload, opts)


def product_payload(**extra):
    base = {'title': '棉袜', 'category_keyword': '中筒袜',
            'skus': [{'spec_values': {'颜色分类': '白色'}, 'price': 12.5, 'stock': 3}]}
    base.update(extra)
    return base


def fill_body(record_id=201, **extra):
    body = {'record_id': record_id, 'platform': 'taobao', 'account_profile': TAOBAO, 'fill_only': True,
            'dry_run': False, 'stop_before_submit': True, 'product': product_payload()}
    body.update(extra)
    return body


def requests(ctx):
    state_dirs = ctx.state['dirs']
    sku_white = os.path.join(state_dirs['a'], 'SKU', '白色.jpg')
    sku_black = os.path.join(state_dirs['a'], 'SKU', '黑色.jpg')
    rev201 = ctx.mod._product_edit_revision(dict(ctx.Record.get_by_id(201).__data__))
    c = cfg()
    out = []
    add = out.append

    # ------------------------------------------------------------------ 1. 就绪度 / 资料检查 / 导出
    add(req('GET', READINESS, before=c))
    for mode in ('import_error', 'os_error', 'value_error', 'runtime_error'):
        add(req('GET', READINESS, before=cfg(desktop={'readiness': mode})))
    for route in (PREPARE, EXPORT):
        add(req('POST', route, None, before=c, data='not json', content_type='text/plain'))
        add(req('POST', route, [1], before=c))
        add(req('POST', route, {'record_id': 201, 'extra': 1}, before=c))
        add(req('POST', route, {'record_id': 201, 'platform': 'douyin'}, before=c))
        for bad in (None, True, '201', 0, -3, 1.5):
            add(req('POST', route, {'record_id': bad}, before=c))
        add(req('POST', route, {}, before=c))
        add(req('POST', route, {'record_id': 201, 'overrides': [1]}, before=c))
        add(req('POST', route, {'record_id': 201, 'account_profile': 'other-00000000'}, before=c))
        add(req('POST', route, {'record_id': 201, 'account_profile': '  '}, before=c))
        add(req('POST', route, {'record_id': 999}, before=c))
        add(req('POST', route, {'record_id': 201}, before=cfg(active=DOUYIN)))
        add(req('POST', route, {'record_id': 201, 'overrides': {'title': 'x'}, 'account_profile': TAOBAO},
                before=cfg(active=TAOBAO)))
    key = {PREPARE: 'prepare', EXPORT: 'export'}
    for route in (PREPARE, EXPORT):
        add(req('POST', route, {'record_id': 201}, before=cfg(desktop={key[route]: 'value_error'})))
        add(req('POST', route, {'record_id': 201}, before=cfg(desktop={key[route]: 'import_error'})))
        add(req('POST', route, {'record_id': 201}, before=cfg(desktop={key[route]: 'os_error'})))
        add(req('POST', route, {'record_id': 201}, before=cfg(desktop={key[route]: 'runtime_error'})))
    add(req('GET', TASKS, before=c, after=settle(lambda ctx: {'packets': tree(os.path.join(ctx.data_dir, 'taobao_publish_packets'))})))

    # ------------------------------------------------------------------ 2. 启动：请求校验（不起线程）
    add(req('POST', START, None, before=c, data='not json', content_type='text/plain'))
    add(req('POST', START, [1], before=c))
    add(req('POST', START, [], before=c))
    add(req('POST', START, {'record_id': 201, 'platform': 'douyin'}, before=c))
    add(req('POST', START, {'record_id': 201, 'unknown': 1}, before=c))
    for flag in ('dry_run', 'stop_before_submit', 'fill_only', 'save_draft'):
        for bad in ('false', 1, None):
            add(req('POST', START, {'record_id': 201, flag: bad}, before=c))
    for mode in (5, ['立刻上架'], 'bogus', '  立刻上架  '):
        add(req('POST', START, {'record_id': 201, 'listing_mode': mode, 'account_profile': TAOBAO}, before=cfg(shop={'resolve': 'none'})))
    for bad in (None, True, '201', 0, -1, 2.0):
        add(req('POST', START, {'record_id': bad}, before=c))
    add(req('POST', START, {'record_id': 201, 'account_profile': 'other-00000000'}, before=c))
    add(req('POST', START, {'record_id': 201, 'account_profile': 7}, before=c))
    add(req('POST', START, {'record_id': 201}, before=cfg(active=DOUYIN)))
    add(req('POST', START, {'record_id': 201, 'fill_only': True}, before=c))                      # dry_run 默认 True
    add(req('POST', START, {'record_id': 201, 'fill_only': True, 'dry_run': False, 'stop_before_submit': False}, before=c))
    add(req('POST', START, {'record_id': 999, 'account_profile': TAOBAO}, before=c))
    for bad in (5, 'abc', '0' * 63 + 'g', 'A' * 64, None, ''):
        add(req('POST', START, {'record_id': 201, 'expected_record_revision': bad}, before=cfg(shop={'resolve': 'none'})))
    add(req('POST', START, {'record_id': 201, 'expected_record_revision': '0' * 64}, before=cfg(shop={'resolve': 'none'})))
    # 商品资料翻译的各种错误
    for product in ([], 'x', 5, {'title': 7}, {'title': ''}, {'title': '袜' * 31}, {'title': 'A' * 61},
                    {'guide_title': '好' * 16}, {'guide_title': ['x']}, {'sku_mode': 'weird'},
                    {'category_keyword': '  '}, {'category_keyword': 5}, {'category_id': True}, {'category_id': 'abc'},
                    {'category_id': '-5'}, {'category_id': 0}, {'category_id': 1.5}, {'props': 'x'}, {'props': [1]},
                    {'skus': 'x'}, {'skus': [1]}, {'skus': [{'price': 'x'}]}, {'skus': [{'price': float('inf')}]},
                    {'skus': [{'price': 0}]}, {'skus': [{'price': True}]}, {'skus': [{'stock': -1}]},
                    {'skus': [{'stock': 1.5}]}, {'skus': [{'image_path': ''}]}, {'skus': [{'image_path': 5}]},
                    {'skus': [{'image_path': os.path.join(state_dirs['a'], 'SKU', '不存在.jpg')}]},
                    {'skus': [{'image_path': os.path.join(state_dirs['b'], 'SKU', '灰色.jpg')}]},
                    {'skus': [{'image_path': os.path.join(state_dirs['a'], '..', 'prod_b', 'SKU', '灰色.jpg')}]},
                    {'skus': [{'image_path': sku_white}, {'image_path': sku_black}]}):
        body = fill_body(product=product)
        add(req('POST', START, body, before=cfg(shop={'resolve': 'none'}, pipeline={'kind': 'ok'}),
                after=settle()))
    # 记录目录异常：无目录 / 相对目录
    add(req('POST', START, fill_body(record_id=202, product=product_payload(skus=[{'image_path': 'x.jpg'}])), before=c,
            after=settle()))
    add(req('POST', START, fill_body(record_id=203, product=product_payload(skus=[{'image_path': 'c.jpg'}])), before=c,
            after=settle()))

    # ------------------------------------------------------------------ 3. 启动：浏览器与准入
    for mode in ('wrong_profile', 'not_opened', 'not_opened_silent', 'no_address', 'os_error', 'key_error'):
        add(req('POST', START, fill_body(), before=cfg(shop={'activate': mode}), after=settle()))
    add(req('POST', START, {'record_id': 201, 'account_profile': TAOBAO}, before=cfg(shop={'resolve': 'none'}), after=settle()))
    add(req('POST', START, {'record_id': 201, 'account_profile': TAOBAO}, before=cfg(), after=settle()))  # 校对路径成功

    # ------------------------------------------------------------------ 4. 启动：成功路径与 worker 的各个分支
    flows = [
        ('填写 + 整页必填已确认', fill_body(), {'verification': 'complete'}, None),
        ('填写 + 整页必填未确认', fill_body(), {'verification': 'incomplete'}, None),
        ('填写 + 没有回读', fill_body(), {}, None),
        ('填写 + 回执自称 dry-run', fill_body(), {'verification': 'complete_but_dry_run_flag'}, None),
        ('填写 + 自称完整但缺整页必填覆盖证据', fill_body(), {'verification': 'complete_no_coverage'}, None),
        ('填写 + 保存草稿已做', fill_body(save_draft=True), {'verification': 'complete', 'draft': True}, None),
        ('填写 + 草稿被跳过', fill_body(save_draft=True), {'draft_skipped': True}, None),
        ('填写 + 上架方式', fill_body(listing_mode='定时上架'), {'verification': 'complete'}, None),
        ('直接发布', fill_body(fill_only=False, stop_before_submit=False, dry_run=False), {'draft': True}, None),
        ('校对（dry-run）', {'record_id': 201, 'account_profile': TAOBAO, 'product': product_payload()}, {}, None),
        ('流水线失败', fill_body(), {'kind': 'fail'}, None),
        ('流水线失败（没有信息）', fill_body(), {'kind': 'fail_silent'}, None),
        ('流水线报已取消', fill_body(), {'kind': 'cancelled'}, None),
        ('流水线抛异常', fill_body(), {'raise': RuntimeError('模拟：流水线崩溃')}, None),
        ('素材记录写入成功', fill_body(), {'verification': 'complete', 'observations': [_observation(ctx.state['dirs']['a'])]}, None),
        ('素材记录写入失败（结构）', fill_body(), {'observations': [{'path': 'x'}]}, None),
        ('素材记录写入失败（磁盘）', fill_body(), {'observations': [_observation(ctx.state['dirs']['a'])]}, 'receipts'),
        ('环境变量原值要还原', fill_body(), {'verification': 'complete'}, 'env'),
        ('任务中途从表里消失', fill_body(), {'mutate_tasks': delete_tasks_midway}, None),
        ('任务中途从表里消失后又抛异常', fill_body(),
         {'mutate_tasks': delete_tasks_midway, 'raise': RuntimeError('模拟：任务没了流水线又崩溃')}, None),
        ('带版本号', fill_body(expected_record_revision=rev201), {'verification': 'complete'}, None),
    ]
    def media_view(ctx):
        return {'media_catalog': tree(os.path.join(ctx.data_dir, 'media_catalog'))}

    def flow_after(special):
        def after(ctx):
            out = view(ctx, media_view)               # 先等发布线程结束，再还原对 save_receipts 的替换
            if special == 'receipts':
                restore_receipts(ctx)
            return out
        return after

    for _label, body, pipeline, special in flows:
        add(req('POST', START, body,
                before=cfg(pipeline=pipeline, env='dom' if special == 'env' else None,
                           do=failing_receipts if special == 'receipts' else None),
                after=flow_after(special)))
    add(req('GET', TASKS, before=c, after=settle()))

    # ------------------------------------------------------------------ 5. 并发 / 取消 / 状态
    held, keep = tid(500), (lambda ctx: None)       # keep：不重置假件行为（后台线程还停在流水线里）
    add(req('POST', START, fill_body(), before=cfg(pipeline={'hold': True, 'cancel_aware': True}, uuid_at=500),
            after=hold_entered))
    add(req('POST', START, fill_body(), before=keep))                                          # 已有任务在跑 -> account_change_blocked 409
    add(req('POST', START, {'record_id': 201, 'account_profile': TAOBAO, 'product': product_payload()},
            before=keep))                                                                      # 校对路径：到锁内才 409
    add(req('GET', TASKS, before=keep))
    add(req('POST', CANCEL + held, None, before=keep))
    add(req('GET', STATUS + held, before=keep))
    add(req('POST', CANCEL + held, None, before=keep))                                         # 重复取消：仍然是「已请求」
    add(req('POST', '/save_info', {'_id': 201, 'title': '新标题'}, before=keep))                 # 同一商品正在发布
    add(req('POST', '/save_info', {'_id': 202, 'title': '另一个商品'}, before=keep))             # 其它商品不受影响
    add(req('GET', '/internal/update-readiness', before=keep))
    add(req('GET', STATUS + held, before=keep, after=release_and_settle))
    add(req('POST', CANCEL + held, None, before=c))                                            # 已结束：无需取消
    add(req('GET', STATUS + held, before=c))
    add(req('GET', STATUS + 'nope', before=c))
    add(req('POST', CANCEL + 'nope', None, before=c))
    add(req('GET', '/internal/update-readiness', before=c))
    add(req('GET', TASKS, before=c, after=settle()))

    # 任务表里有别的商品在跑 / 批量任务在跑 / 记录范围无法确认
    add(req('POST', '/save_info', {'_id': 201, 'title': '别的商品在跑'}, before=cfg(do=seed_task('t-other', 'running', record_id=202))))
    add(req('POST', '/save_info', {'_id': 201, 'title': '批量在跑'}, before=cfg(do=seed_task('t-batch', 'pending', record_id=None))))
    add(req('POST', '/save_info', {'_id': 201, 'title': '范围无法确认'}, before=cfg(do=seed_task('t-bad', 'running', record_id='abc'))))
    add(req('POST', '/save_info', {'_id': 201, 'title': '已结束的不拦'}, before=cfg(do=seed_task('t-done', 'succeeded', record_id=201))))
    add(req('POST', START, fill_body(), before=cfg(do=seed_task('t-run', 'running', record_id=202)), after=settle()))
    add(req('POST', START, {'record_id': 201, 'account_profile': TAOBAO}, before=cfg(do=seed_task('t-run2', 'pending', record_id=202)),
            after=settle()))                                                                   # 校对路径
    add(req('GET', '/internal/update-readiness', before=cfg(do=seed_task('t-run3', 'running'))))
    # 有别的任务在跑时启动批量：旧版没有准入检查，照样启动（还多创建一个任务）；新版与单品同一套准入，409（2026-10-21 起的预期差异）
    add(req('POST', START_ALL, {'account_profile': TAOBAO}, before=cfg(do=seed_task('t-run4', 'running', record_id=202)),
            after=settle()))
    add(req('GET', TASKS, before=cfg(do=clear_tasks), after=settle()))

    # ------------------------------------------------------------------ 6. 保存时校验标题（淘宝）
    def save_body(**extra):
        body = {'_id': 204, 'for_publish': True, 'platform': 'taobao', 'account_profile': TAOBAO, 'title': '保存用的标题',
                'repo': 7, 'clazz': 2, 'attr_size': 1, 'attr_path_1': ctx.state['contents']['s'][0]['path'],
                'attr_name_1': '红色', 'attr_price_1': 9.9}
        body.update(extra)
        return body
    add(req('POST', '/save_info', save_body(title='袜' * 31), before=c))
    add(req('POST', '/save_info', save_body(title='A' * 61), before=c))
    add(req('POST', '/save_info', save_body(title='袜' * 30), before=c))
    add(req('POST', '/save_info', save_body(title='  '), before=c))
    add(req('POST', '/save_info', save_body(platform='douyin'), before=c))

    # ------------------------------------------------------------------ 7. 批量发布
    add(req('POST', START_ALL, None, before=c, data='not json', content_type='text/plain', after=settle()))   # 读不出 JSON 按 {} 处理：照样启动
    add(req('POST', START_ALL, [1], before=c))
    add(req('POST', START_ALL, {'platform': 'douyin'}, before=c))
    add(req('POST', START_ALL, {'dry_run': 'no'}, before=c))
    add(req('POST', START_ALL, {'unknown': 1}, before=c))
    add(req('POST', START_ALL, {'account_profile': 'other-00000000'}, before=c))
    add(req('POST', START_ALL, {}, before=cfg(active=DOUYIN)))
    add(req('POST', START_ALL, {'account_profile': TAOBAO}, before=cfg(do=make_status_zero_none)))      # 没有待上传商品
    add(req('POST', START_ALL, {'account_profile': TAOBAO}, before=cfg(do=restore_status_zero, shop={'activate': 'not_opened'}),
            after=settle()))
    batch_flows = [
        ('批量全成功（校对）', {'account_profile': TAOBAO}, {}),
        ('批量全成功（填写）', {'account_profile': TAOBAO, 'fill_only': True, 'dry_run': False}, {'verification': 'complete'}),
        ('批量直接发布', {'account_profile': TAOBAO, 'fill_only': False, 'dry_run': False, 'stop_before_submit': False,
                    'listing_mode': '放入仓库', 'save_draft': True}, {'draft': True}),
        ('批量有失败', {'account_profile': TAOBAO}, {'kind': 'ok_per_record', 'per_record': {202: 'fail'}}),
        ('批量全失败', {'account_profile': TAOBAO}, {'kind': 'fail'}),
        ('批量一条抛异常', {'account_profile': TAOBAO}, {'kind': 'ok_per_record', 'per_record': {201: 'raise_per_record'}}),
        ('批量不带账户标识', {}, {}),
    ]
    for _label, body, pipeline in batch_flows:
        add(req('POST', START_ALL, body, before=cfg(pipeline=pipeline), after=settle()))
    # 批量取消：第一条跑着的时候取消，第二条开始前发现
    add(req('POST', START_ALL, {'account_profile': TAOBAO}, before=cfg(pipeline={'hold': True, 'hold_on': 201}, uuid_at=600),
            after=hold_entered))
    add(req('POST', CANCEL + tid(600), None, before=keep))
    add(req('GET', STATUS + tid(600), before=keep, after=release_and_settle))
    add(req('GET', TASKS, before=c, after=settle()))
    # 批量里途中任务消失
    add(req('POST', START_ALL, {'account_profile': TAOBAO}, before=cfg(pipeline={'mutate_tasks': delete_tasks_midway}),
            after=settle()))
    # 批量里某条记录的翻译直接抛 ValueError（商品目录不存在）：旧版工作线程崩溃、任务永远停在 pending；新版只让这一条失败（2026-10-21 起的预期差异）
    add(req('POST', START_ALL, {'account_profile': TAOBAO}, before=cfg(do=make_extra_record), after=settle()))
    add(req('GET', '/internal/update-readiness', before=c))
    add(req('GET', TASKS, before=cfg(do=lambda ctx: (clear_tasks(ctx), drop_extra_record(ctx))), after=settle()))

    # ------------------------------------------------------------------ 8. 直接调用
    add(req('GET', TASKS, before=c, after=direct_probe))
    return out


# ---------------------------------------------------------------------------------------------- 直接调用对打
def call(out, label, func, *args, **kwargs):
    try:
        result = func(*args, **kwargs)
        out.append([label, 'ok', _json_safe(result)])
    except Exception as exc:  # noqa: BLE001  —— 要的就是它抛什么
        out.append([label, 'raise', type(exc).__name__, str(exc)])


def direct_probe(ctx):
    out = []
    state = ctx.state
    dirs = state['dirs']
    R = ctx.Record

    # --- 纯函数：发布开关解析
    parse = fn(ctx, '_parse_taobao_publish_options')
    for data in (None, [], 'x', {}, {'record_id': 1}, {'dry_run': False}, {'dry_run': 'false'}, {'dry_run': 0},
                 {'stop_before_submit': False, 'dry_run': False}, {'fill_only': True}, {'fill_only': None},
                 {'save_draft': True}, {'save_draft': 'yes'}, {'listing_mode': None}, {'listing_mode': ''},
                 {'listing_mode': ' 定时上架 '}, {'listing_mode': '立刻上架'}, {'listing_mode': '放入仓库'},
                 {'listing_mode': 3}, {'listing_mode': 'x'}, {'product': {}, 'expected_record_revision': 'a'},
                 {'platform': 'taobao', 'account_profile': 'p', 'record_id': 2}, {'bad': 1}):
        call(out, 'parse', parse, data)
    out.append(['consts', list(const(ctx, 'TAOBAO_LISTING_MODES')),
                {str(k): v for k, v in const(ctx, '_CATEGORY_LABELS').items()}])      # scrub 只认字符串键

    # --- 纯函数：从商品记录构造载荷
    from_record = fn(ctx, '_taobao_product_from_record')
    for record_id in (201, 202, 203, 204):
        call(out, 'from_record(row %d)' % record_id, from_record, R.get_by_id(record_id))
    fake = SimpleNamespace
    for label, rec in (
        ('int clazz', fake(content=json.dumps([{'name': '白', 'price': 3, 'path': 'a.jpg'}]), clazz=4, repo=2,
                           title=' 标题 ', name=' 名字 ')),
        ('unknown int clazz', fake(content='[]', clazz=9, repo=None, title=None, name='n')),
        ('str clazz', fake(content='[]', clazz=' 短袜 ', repo=1, title='', name='  ')),
        ('none clazz', fake(content=None, clazz=None, repo=0, title='t', name='n')),
        ('bad json', fake(content='{oops', clazz=0, repo=1, title='t', name='n')),
        ('mixed skus', fake(content=json.dumps([1, {'name': '', 'price': 1}, {'name': 'a', 'price': 0},
                                                {'name': 'b', 'price': 'x'}, {'name': 'c', 'price': '2.5', 'path': ' p.jpg '},
                                                {'name': None, 'price': 1}, {'price': 3, 'name': 'd', 'path': None}]),
                            clazz=1, repo='3', title='t', name='n')),
        ('content not list', fake(content=json.dumps({'a': 1}), clazz=1, repo=1, title='t', name='n')),
    ):
        call(out, 'from_record(%s)' % label, from_record, rec)

    # --- 商品资料翻译（带 / 不带记录）
    payload = fn(ctx, '_taobao_product_request_payload')
    rows = {key: dict(R.get_by_id(rid).__data__) for key, rid in (('a', 201), ('b', 202), ('rel', 203))}
    sku_a = state['contents']['a']
    cases = [
        (None, None), ([], None), ({}, None), ({'title': ' 标题 '}, None), ({'title': '袜' * 30}, None),
        ({'title': '袜' * 31}, None), ({'title': '袜' * 29 + 'AB'}, None), ({'title': '袜' * 29 + 'ABC'}, None),
        ({'guide_title': ' 导购 '}, None), ({'guide_title': '好' * 15}, None), ({'guide_title': '好' * 16}, None),
        ({'freight_template_name': ' 模板 ', 'outer_id': ' 编码 '}, None), ({'outer_id': 1}, None),
        ({'sku_mode': 'standard'}, None), ({'sku_mode': 'custom'}, None), ({'sku_mode': None}, None),
        ({'category_path': ' 女装 > 袜子 >  > 中筒袜 '}, None), ({'category_path': '  '}, None), ({'category_path': 5}, None),
        ({'category_path': 'a>b', 'category_id': '123'}, None), ({'category_keyword': ' 中筒袜 ', 'category_id': 456}, None),
        ({'category_id': '012'}, None), ({'category_id': ''}, None), ({'category_id': None}, None), ({'category_id': '１２'}, None),
        ({'props': []}, None), ({'props': [{'a': 1}]}, None), ({'props': [{'a': 1}, 2]}, None),
        ({'skus': []}, None), ({'skus': [{'price': 1, 'stock': 2}]}, None), ({'skus': [{'price': 1.5, 'stock': 0}]}, None),
        ({'skus': [{'price': float('nan')}]}, None), ({'skus': [{'stock': 2 ** 2000}]}, None),
        ({'skus': [{'price': 10 ** 400}]}, None), ({'skus': [{'price': -1}]}, None), ({'skus': [{'stock': 1.0}]}, None),
        ({'skus': [{'image_path': 'x.jpg'}]}, None),
        ({'skus': [{'image_path': sku_a[0]['path']}]}, rows['a']),
        ({'skus': [{'image_path': os.path.join('SKU', '白色.jpg')}]}, rows['a']),
        ({'skus': [{'image_path': sku_a[0]['path']}, {'image_path': sku_a[1]['path'], 'price': 3}]}, rows['a']),
        ({'skus': [{'image_path': os.path.join(dirs['b'], 'SKU', '灰色.jpg')}]}, rows['a']),
        ({'skus': [{'image_path': os.path.join(dirs['a'], 'SKU', 'nothere.jpg')}]}, rows['a']),
        ({'skus': [{'image_path': '../outside.jpg'}]}, rows['a']),
        ({'skus': [{'image_path': sku_a[0]['path']}]}, rows['b']),
        ({'skus': [{'image_path': 'c.jpg'}]}, rows['rel']),
        ({'skus': [{'image_path': sku_a[0]['path']}]}, dict(rows['a'], content=json.dumps(sku_a))),
        ({'skus': [{'image_path': sku_a[0]['path']}]}, dict(rows['a'], content='{oops')),
        ({'skus': [{'image_path': sku_a[0]['path']}]}, dict(rows['a'], content=json.dumps({'a': 1}))),
        ({'skus': [{'image_path': sku_a[0]['path']}]}, dict(rows['a'], content=json.dumps([1, 2]))),
        ({'skus': [{'image_path': sku_a[0]['path']}]}, dict(rows['a'], content=[{'path': sku_a[0]['path']}, {'name': 'no path'}])),
        ({'skus': [{'image_path': sku_a[0]['path']}]}, dict(rows['a'], content=None)),
        ({'skus': [{'price': 3}]}, rows['a']),
        ({'title': '标题', 'category_keyword': '中筒袜', 'sku_mode': 'custom', 'outer_id': 'o',
          'skus': [{'spec_values': {'颜色分类': '白色'}, 'price': 12, 'stock': 3, 'image_path': sku_a[1]['path']}]}, rows['a']),
    ]
    for product, record in cases:
        call(out, 'payload', payload, product, record=record)
    call(out, 'payload(无 record 形参)', payload, {'title': '只给标题'})

    # --- 加载器：sys.path 副作用和 frozen 分支
    for label, frozen in (('源码运行', False), ('打包运行', True)):
        saved = list(sys.path)
        had = getattr(sys, 'frozen', None)
        if frozen:
            sys.frozen = True
        try:
            for name in ('_load_taobao_desktop', '_load_taobao_pipeline'):
                sys.path[:] = [p for p in sys.path if os.path.abspath(p) != os.path.abspath(PKG_ROOT)]
                result = fn(ctx, name)()
                out.append([label, name, getattr(result, '__name__', repr(result)),
                            any(os.path.abspath(p) == os.path.abspath(PKG_ROOT) for p in sys.path),
                            sys.path[0]])             # 实际插入的那个字符串（相对路径与绝对路径在 cwd 恰好是仓库根时 abspath 相同，只比 abspath 会漏）
        finally:
            sys.path[:] = saved
            if frozen:
                if had is None:
                    del sys.frozen
                else:
                    sys.frozen = had

    # --- 浏览器地址
    for resolve in ('ok', 'none'):
        state['shop'] = {'resolve': resolve}
        call(out, 'cdp_list_url(%s)' % resolve, fn(ctx, '_taobao_cdp_list_url'))
    for active, activate in ((TAOBAO, 'ok'), (DOUYIN, 'ok'), (TAOBAO, 'wrong_profile'), (TAOBAO, 'not_opened'),
                             (TAOBAO, 'not_opened_silent'), (TAOBAO, 'no_address'), (TAOBAO, 'os_error')):
        cfg(shop={'activate': activate}, active=active)(ctx)
        call(out, 'ensure_fill_browser(%s,%s)' % (active, activate), fn(ctx, '_ensure_taobao_fill_browser'))
    cfg(active=TAOBAO)(ctx)
    out.append(['shop_calls', _json_safe(state['shop_calls'][state['seen'].get('shop_calls', 0):])])
    state['seen']['shop_calls'] = len(state['shop_calls'])

    # --- worker 直接调用：任务不在表里 / 批量没有记录
    clear_tasks(ctx)
    cfg(pipeline={'verification': 'complete'})(ctx)
    options = {'dry_run': False, 'stop_before_submit': True, 'fill_only': True, 'cdp_list_url': 'http://127.0.0.1:9501/json/list'}
    call(out, 'run_task(任务不在表里)', fn(ctx, '_run_taobao_publish_task'), 'ghost', rows['a'], {'record_id': 201}, options)
    out.append(['run_task 后环境变量', os.environ.get('TAOBAO_MEDIA_ROUTE')])
    seed_task('direct', 'pending', record_id=201, account_profile=TAOBAO)(ctx)
    call(out, 'run_task(缺可选键)', fn(ctx, '_run_taobao_publish_task'), 'direct', rows['a'], {'record_id': 201},
         {'dry_run': True, 'stop_before_submit': True, 'cdp_list_url': 'u'})
    call(out, 'run_task(缺必填键)', fn(ctx, '_run_taobao_publish_task'), 'direct', rows['a'], {'record_id': 201}, {})
    out.append(['direct 任务', _json_safe(tasks_of(ctx)['direct'])])
    clear_tasks(ctx)
    make_status_zero_none(ctx)
    seed_task('batch-empty', 'pending')(ctx)
    call(out, 'run_batch(没有记录)', fn(ctx, '_run_taobao_publish_batch_task'), 'batch-empty', {})
    restore_status_zero(ctx)
    call(out, 'run_batch(任务不在表里)', fn(ctx, '_run_taobao_publish_batch_task'), 'ghost',
         {'dry_run': True, 'cdp_list_url': 'u', 'account_profile': TAOBAO})
    out.append(['batch-empty 任务', _json_safe(tasks_of(ctx)['batch-empty'])])
    out.append(['pipeline 调用', _json_safe(state['pipeline_calls'][state['seen'].get('pipeline_calls', 0):])])
    state['seen']['pipeline_calls'] = len(state['pipeline_calls'])
    clear_tasks(ctx)

    # --- app.py 里读任务字典的几个函数
    for label, task in (('空', None), ('进行中', ('a', 'running')), ('等待中', ('b', 'pending')), ('已结束', ('c', 'succeeded'))):
        clear_tasks(ctx)
        if task:
            seed_task(task[0], task[1], record_id=201)(ctx)
        out.append(['publish_tasks_running(%s)' % label, bool(ctx.mod._publish_tasks_running())])
        with ctx.mod.app.test_request_context('/'):
            blocked = ctx.mod._record_edit_blocked(201)
            out.append(['record_edit_blocked(%s)' % label, None if blocked is None else [blocked[0].get_json(), blocked[1]]])
        out.append(['active_update_tasks(%s)' % label, _json_safe(ctx.mod._active_update_tasks())])
    clear_tasks(ctx)
    return {'direct': out, 'dirs_tree': tree(os.path.join(ctx.data_dir, 'media_catalog'))}


def final(ctx):
    join_workers()
    return {'tasks': _json_safe(tasks_of(ctx)), 'logs': _json_safe(ctx.state['logs']),
            'env': os.environ.get('TAOBAO_MEDIA_ROUTE'), 'uuid_calls': ctx.state['uuid_counter'][0],
            'packets': tree(os.path.join(ctx.data_dir, 'taobao_publish_packets')),
            'media_catalog': tree(os.path.join(ctx.data_dir, 'media_catalog')),
            'records': [[r.id, r.title, r.status] for r in ctx.Record.select().order_by(ctx.Record.id)]}


SCENARIOS['taobao'] = dict(
    setup=setup,
    patch_old=install,
    patch_new=install,
    new_via_app=True,
    requests=requests,
    final=final,
)

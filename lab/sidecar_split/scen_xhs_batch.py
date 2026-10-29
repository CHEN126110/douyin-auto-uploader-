# -*- coding: utf-8 -*-
"""小红书批量填表（/api/xhs/fill-batch、fill-status、fill-cancel）的新旧对打场景（2026-10-20）。

走 app.py 自己的装配（``new_via_app=True``）：新版连同 ``xhs_batch`` 服务的创建、端口段常量的传入、
以及 ``/api/xhs/status``、``/api/xhs/fill-only`` 用到的 ``_xhs_runner_with_account_port`` 一起对打。

假件：
  - ``src.sidecar.xhs_routes.default_runner`` / ``default_status_probe``：不连浏览器，只记录收到的参数；
    按标题返回成功 / 失败（带 blocked 原因）/ 抛异常，并可被一个“闸门”卡住（用来做确定性的取消流程）；
  - ``get_pic_list``：固定返回几张存在 / 不存在的图，某个商品抛错；
  - ``urllib.request.urlopen``：只在需要扫描端口的请求期间替换，假装 9503 上有小红书页面；
  - ``uuid.uuid4``：计数器，任务 id 才可比较。
worker 是后台线程：每次启动后用 after 钩子等到任务结束再继续，保证顺序确定。
"""
import json
import os
import threading
import time
import urllib.request
import uuid
from urllib.error import URLError

from scenarios import SCENARIOS, make_records

XHS_URL = 'https://ark.xiaohongshu.com/app-item/good/create'
TERMINAL = ('succeeded', 'failed', 'cancelled')


def _tasks(ctx):
    return ctx.mod._xhs_tasks if ctx.mode == 'old' else ctx.mod.xhs_batch.tasks


def _lock(ctx):
    return ctx.mod._xhs_tasks_lock if ctx.mode == 'old' else ctx.mod.xhs_batch.lock


def _call_worker(ctx, task_id, payload):
    fn = ctx.mod._run_xhs_fill_batch_task if ctx.mode == 'old' else ctx.mod.xhs_batch.run_fill_batch_task
    return fn(task_id, payload)


def _snapshot(ctx):
    with _lock(ctx):
        return {tid: dict(task) for tid, task in sorted(_tasks(ctx).items())}


def _wait_terminal(ctx, task_id, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with _lock(ctx):
            task = _tasks(ctx).get(task_id)
            if task and task.get('status') in TERMINAL:
                return
        time.sleep(0.02)
    raise AssertionError('任务 %s 没有在 %.0f 秒内结束' % (task_id, timeout))


def _wait_runner_calls(ctx, count, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(ctx.state['runner_calls']) >= count:
            return
        time.sleep(0.02)
    raise AssertionError('执行器没有被调用到第 %d 次' % count)


class _Resp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _fake_urlopen(url, timeout=None):
    if ':9501/' in url:
        return _Resp(b'not json')                                    # 解析失败：继续扫下一个
    if ':9502/' in url:
        return _Resp(json.dumps([{'type': 'worker', 'url': XHS_URL}]).encode('utf-8'))   # 不是 page：不算
    if ':9503/' in url:
        return _Resp(json.dumps([{'type': 'page', 'url': 'https://example.com/'},
                                 {'type': 'page', 'url': XHS_URL}]).encode('utf-8'))
    raise URLError('refused')


def _refuse_all(url, timeout=None):
    raise URLError('refused')


def _scan_with(fake):
    def before(ctx):
        ctx.state.setdefault('real_urlopen', urllib.request.urlopen)
        urllib.request.urlopen = fake
    return before


def _restore_urlopen(ctx):
    if 'real_urlopen' in ctx.state:
        urllib.request.urlopen = ctx.state.pop('real_urlopen')


def _install_fakes(ctx):
    state = ctx.state
    state['runner_calls'] = []
    state['gate'] = None

    def fake_runner(payload):
        state['runner_calls'].append(json.loads(json.dumps(payload, ensure_ascii=False)))
        gate = state['gate']
        if gate is not None:
            gate.wait(15)
        title = payload.get('title')
        if title == 'T5':
            raise RuntimeError('模拟填表异常')
        if title == '纯棉中筒袜男':
            return {'ok': False, 'blocked': ['缺少主图', '类目未选']}
        return {'ok': True, 'echo_port': payload.get('port')}

    def fake_probe(port=None):
        return {'port': port, 'visibility': 'visible'}

    import src.sidecar.xhs_routes as xhs_routes
    xhs_routes.default_runner = fake_runner
    xhs_routes.default_status_probe = fake_probe

    imgs = state['imgs']

    def fake_pic_list(record, key):
        if key == '800':
            return [imgs['main.jpg']] if record.id in (101, 102, 107) else []
        if record.id == 105:
            raise RuntimeError('目录读取失败')
        if record.id == 101:
            return [imgs['detail.jpg'], os.path.join(os.path.dirname(imgs['detail.jpg']), 'gone.jpg')]
        return []
    state['fake_pic_list'] = fake_pic_list

    counter = {'n': 0}

    def fake_uuid4():
        counter['n'] += 1
        return uuid.UUID(int=counter['n'] << 96)          # str(...)[:8] 依次是 00000001、00000002……
    uuid.uuid4 = fake_uuid4


def patch_old(ctx):
    _install_fakes(ctx)
    ctx.mod.get_pic_list = ctx.state['fake_pic_list']


def patch_new(ctx):
    _install_fakes(ctx)
    ctx.mod.xhs_batch._get_pic_list = ctx.state['fake_pic_list']


def setup(ctx):
    make_records(ctx)                    # 101 / 102 状态 0，103 状态 1
    root = os.path.join(ctx.data_dir, 'xhs_files')
    os.makedirs(root, exist_ok=True)
    imgs = {}
    for name in ('main.jpg', 'detail.jpg', 'sku.jpg'):
        path = os.path.join(root, name)
        with open(path, 'wb') as fp:
            fp.write(b'x')
        imgs[name] = path
    ctx.state['imgs'] = imgs
    R = ctx.Record
    # 101：SKU 里有一张存在的图、一张不存在的图、一个不是字典的元素、一个空路径
    R.update(content=json.dumps([{'name': '白', 'path': imgs['sku.jpg']},
                                 {'name': '无图', 'path': os.path.join(root, 'nope.jpg')},
                                 'junk', {'name': '空', 'path': ''}], ensure_ascii=False)).where(R.id == 101).execute()
    common = dict(path='uploads/products/X', type=1, repo=1, remark='', update_time=R.get_by_id(101).update_time)
    R.create(id=104, name='', title='', status=0, clazz='2', content='[]', **common)               # 标题为空
    R.create(id=105, name='坏内容二号', title='T5', status=0, clazz='x', content='not json', **common)  # 执行器抛异常 / 类目认不出
    R.create(id=106, name='空内容', title='T6', status=0, clazz=None, content='', **common)            # content 为空串 / 类目为 None
    R.create(id=107, name='长筒袜款', title='T7', status=0, clazz='长筒袜', content='[]', **common)     # 类目直接是中文名


def _activate_xhs_account(ctx):
    ctx.mod.shop_session.set_active_profile('xhs-test', label='小红书测试', platform='xiaohongshu')


def _start_and_wait(task_id):
    def after(ctx):
        _wait_terminal(ctx, task_id)
        return {'tasks': _snapshot(ctx), 'runner_calls': len(ctx.state['runner_calls'])}
    return after


def _block_runner_then_wait_first_call(ctx):
    ctx.state['gate'] = threading.Event()
    ctx.state['calls_before'] = len(ctx.state['runner_calls'])


def _wait_blocked_runner(ctx):
    _wait_runner_calls(ctx, ctx.state['calls_before'] + 1)
    return {'tasks': _snapshot(ctx)}


def _release_and_wait(task_id):
    def before(ctx):
        ctx.state['gate'].set()
        _wait_terminal(ctx, task_id)
        ctx.state['gate'] = None
        _restore_urlopen(ctx)
    return before


def _set_all_status(value):
    def before(ctx):
        ctx.Record.update(status=value).execute()
    return before


def _reopen_records_and_seed_old_tasks(ctx):
    """记录恢复为待上传，并往任务字典里塞一批旧任务：用来触发清理（超过保留条数 / 超过 TTL / 运行中 / 时间戳损坏）。"""
    from datetime import datetime, timedelta
    ctx.Record.update(status=0).where(ctx.Record.id.in_([101, 102])).execute()
    ctx.Record.update(status=1).where(ctx.Record.id.not_in([101, 102])).execute()
    now = datetime.now()
    with _lock(ctx):
        tasks = _tasks(ctx)
        for index in range(25):
            stamp = (now - timedelta(minutes=60 - index)).isoformat()
            tasks['seed%02d' % index] = {'task_id': 'seed%02d' % index, 'status': 'succeeded',
                                         'created_at': stamp, 'finished_at': stamp}
        old = (now - timedelta(hours=30)).isoformat()
        tasks['expired'] = {'task_id': 'expired', 'status': 'failed', 'created_at': old, 'finished_at': old}
        tasks['still-running'] = {'task_id': 'still-running', 'status': 'running', 'created_at': old,
                                  'finished_at': None}
        tasks['broken-stamp'] = {'task_id': 'broken-stamp', 'status': 'cancelled',
                                 'created_at': '不是时间', 'finished_at': '也不是'}


def _direct_worker_calls(ctx):
    """不经 HTTP 直接调 worker：覆盖路由层永远走不到的分支（没有待上传商品 / 任务已被清理）。"""
    ctx.Record.update(status=1).execute()
    with _lock(ctx):
        _tasks(ctx)['direct-empty'] = {'task_id': 'direct-empty', 'status': 'pending', 'message': '', 'progress': 0}
    _call_worker(ctx, 'direct-empty', {})                 # 没有待上传商品：任务标记失败
    _call_worker(ctx, 'unknown-id', {})                   # 没有待上传商品且任务不存在：直接返回
    ctx.Record.update(status=0).where(ctx.Record.id.in_([101, 107])).execute()
    before = len(ctx.state['runner_calls'])
    _call_worker(ctx, 'ghost-task', {'port': 9557})       # 任务字典里没有这个 id：逐个跑完后直接返回
    return {'tasks': _snapshot(ctx), 'runner_calls_added': len(ctx.state['runner_calls']) - before}


def requests(ctx):
    batch = '/api/xhs/fill-batch'
    fill_only = '/api/xhs/fill-only'
    scan = _scan_with(_fake_urlopen)
    return [
        # ---- 账户门禁：当前账户是抖店，进不了小红书路线 ----
        ('POST', batch, {}),
        ('GET', '/api/xhs/status', None),
        ('POST', fill_only, {'title': 'T'}),
        # ---- 参数 ----
        ('POST', batch, [1], {'before': _activate_xhs_account}),
        # ---- 正常跑完一批（有成功 / 失败 / 异常 / 标题为空 / 类目认不出）----
        ('POST', batch, {'port': 9555, 'allow_upload': True, 'service_values': {'物流模板': '自定义'}},
         {'after': _start_and_wait('00000001')}),
        ('GET', '/api/xhs/fill-status/00000001', None),
        ('GET', '/api/xhs/fill-status/missing', None),
        ('POST', '/api/xhs/fill-cancel/00000001', {}),
        ('POST', '/api/xhs/fill-cancel/missing', {}),
        # ---- 取消流程：执行器被闸门卡住，取消后释放，第二个商品之前就收到取消 ----
        ('POST', batch, {}, {'before': lambda c: (_block_runner_then_wait_first_call(c), scan(c)),
                             'after': _wait_blocked_runner}),
        ('POST', '/api/xhs/fill-cancel/00000002', {}),
        ('GET', '/api/xhs/fill-status/00000002', None),
        ('GET', '/api/xhs/fill-status/00000002', None, {'before': _release_and_wait('00000002')}),
        # ---- 没有待上传商品 ----
        ('POST', batch, {}, {'before': _set_all_status(1)}),
        # ---- 清理旧任务 ----
        ('POST', batch, {'port': 9556}, {'before': _reopen_records_and_seed_old_tasks,
                                         'after': _start_and_wait('00000003')}),
        # ---- 直接调 worker 的边界分支 ----
        ('GET', '/health', None, {'after': _direct_worker_calls}),
        # ---- 同一套装配里的另外两个小红书接口（用到 debug_port）----
        ('POST', fill_only, {'title': ' 标题X ', 'images': ['a.jpg'], 'category': ' 中筒袜 ',
                             'service_values': {'k': 'v'}, 'allow_upload': True}, {'before': scan}),
        ('POST', fill_only, {'title': 'Y', 'port': 9777}),
        ('POST', fill_only, {'title': 'Y', 'port': 'abc'}),
        ('GET', '/api/xhs/status', None),
        ('GET', '/api/xhs/status', None, {'before': _scan_with(_refuse_all)}),
        ('GET', '/health', None, {'after': lambda c: (_restore_urlopen(c), {})[1]}),
    ]


def final(ctx):
    return {
        'runner_calls': ctx.state['runner_calls'],
        'tasks': _snapshot(ctx),
        'records': [{'id': r.id, 'status': r.status} for r in ctx.Record.select().order_by(ctx.Record.id)],
    }


SCENARIOS['xhs_batch'] = dict(
    setup=setup,
    patch_old=patch_old,
    patch_new=patch_new,
    new_via_app=True,
    requests=requests,
    final=final,
)

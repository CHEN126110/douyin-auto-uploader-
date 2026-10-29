# -*- coding: utf-8 -*-
"""店铺会话（/api/shop/*）新旧对打场景。假件与装配见 scen_shop_debug.py。

账户注册表用真实的 ``src.shop_session``（落在隔离数据目录里），所以添加 / 切换 / 移除账户、
实测身份写回注册表这些逻辑是真跑的；浏览器、进程、CDP 读身份都是假的。
"""
import json
import os

from scenarios import SCENARIOS
from scen_shop_debug import (
    R, S, build_new, chain, patch_new, patch_old, reset_page, set_page, snap, _initial_state,
)

P = '/api/shop'
DEFAULT = 'upload-browser-profile'
DOUYIN, TAOBAO, XHS = 'shop-aaaaaaaa', 'taobao-bbbbbbbb', 'xhs-cccccccc'


def _entry(slug, platform, label=None, **extra):
    base = {'profile_name': slug, 'platform': platform, 'label': label, 'created_at': '2026-10-01T09:00:00',
            'shop_id': None, 'shop_name': None, 'last_seen_at': None, 'seen_count': 0}
    base.update(extra)
    return base


def setup(ctx):
    _initial_state(ctx)
    from src import shop_session
    shop_session.save_registry({
        'active_profile': DOUYIN,
        'profiles': {
            DEFAULT: _entry(DEFAULT, 'douyin'),
            DOUYIN: _entry(DOUYIN, 'douyin', '甲店备注', shop_id='1001', shop_name='甲店',
                           last_seen_at='2026-10-02T10:00:00', seen_count=2),
            TAOBAO: _entry(TAOBAO, 'taobao', '乙淘宝'),
            XHS: _entry(XHS, 'xiaohongshu', '丙小红书', last_seen_at='2026-10-03T10:00:00'),
        },
    })


def udir(ctx, slug):
    return os.path.join(ctx.data_dir, slug)


def set_active(slug):
    def hook(ctx):
        from src import shop_session
        # 直接改注册表文件；这一步不是被测路径，不能被包装器记进调用日志
        registry = shop_session.load_registry()
        registry['active_profile'] = slug
        shop_session.save_registry(registry)
    return hook


def edit_registry(mutate):
    def hook(ctx):
        from src import shop_session
        registry = shop_session.load_registry()
        mutate(registry)
        shop_session.save_registry(registry)
    return hook


def make_dir(slug, with_file=True):
    def hook(ctx):
        path = udir(ctx, slug)
        os.makedirs(path, exist_ok=True)
        if with_file:
            with open(os.path.join(path, 'marker.txt'), 'w', encoding='utf-8') as fp:
                fp.write('login data')
    return hook


def running_task(kind, status):
    def hook(ctx):
        tasks = ctx.mod._upload_tasks if kind == 'upload' else _taobao_task_dict(ctx)
        tasks.clear()
        tasks['t1'] = {'status': status, 'platform': kind}
    return hook


def _taobao_task_dict(ctx):
    """淘宝任务字典：2026-10-20 前在 app.py 里是模块全局 ``_taobao_tasks``，现在是 ``taobao_service.tasks``。"""
    service = getattr(ctx.mod, 'taobao_service', None)
    return service.tasks if service is not None else ctx.mod._taobao_tasks


def clear_tasks(ctx):
    ctx.mod._upload_tasks.clear()
    _taobao_task_dict(ctx).clear()


def registry_file(ctx):
    return os.path.join(ctx.data_dir, 'shop_profiles.json')


def guard_probe(ctx):
    """直接调用账户门禁函数（它们被上传 / 淘宝 / 小红书 / 保存等入口使用，不在 /api/shop/* 里）。"""
    mod = ctx.mod
    from src import shop_session
    out = []

    def call(label, fn, *args):
        result = fn(*args)
        if isinstance(result, tuple):
            result = [result[0].get_json(), result[1]]
        out.append([label, list(args), result])

    original_active = shop_session.load_registry()['active_profile']
    with mod.app.test_request_context('/'):
        for active in (DOUYIN, TAOBAO, XHS, original_active):
            registry = shop_session.load_registry()
            registry['active_profile'] = active
            shop_session.save_registry(registry)
            out.append(['active', active, mod._active_shop_profile(), mod._active_shop_account()])
            for expected in ('douyin', 'taobao', 'xiaohongshu', 'other'):
                call('require', mod._require_publish_platform, expected)
            for snapshot in (None, '', '  ', 5, [], active, 'someone-else-00000000'):
                call('require', mod._require_publish_platform, 'douyin', snapshot)
                call('require', mod._require_publish_platform, 'taobao', snapshot)
        # 注册表读不出来：必须 503，不能悄悄回落到抖店
        with open(registry_file(ctx), 'r', encoding='utf-8') as fp:
            backup = fp.read()
        for broken in ('{not json', '[]', json.dumps({'active_profile': 'ghost-00000000', 'profiles': {}}),
                       json.dumps({'active_profile': 'ghost-00000000', 'profiles': {DOUYIN: {'platform': 'douyin'}}})):
            with open(registry_file(ctx), 'w', encoding='utf-8') as fp:
                fp.write(broken)
            try:
                account = mod._active_shop_account()
            except Exception as exc:       # 要的就是它抛什么
                account = [type(exc).__name__, str(exc)]
            out.append(['broken', broken[:20], account])
            call('require', mod._require_publish_platform, 'douyin')
        with open(registry_file(ctx), 'w', encoding='utf-8') as fp:
            fp.write(backup)
        # 装饰器：保留原函数名，并且持有同一把账户锁
        wrapped = mod._with_shop_account_lock(lambda value: value + 1)
        out.append(['decorator', wrapped(1), wrapped.__name__, type(mod._shop_account_lock).__name__])
        held = []

        def inside():
            held.append(mod._shop_account_lock.acquire(blocking=False))
            mod._shop_account_lock.release()
            return 1
        mod._with_shop_account_lock(inside)()
        out.append(['reentrant', held])
    ctx.state['calls'].append(['guard', out])


def reusable_selected(address, user_data_dir, url='https://fxg.jinritemai.com/ffa/mshop/homepage/index'):
    browser = {'debug_address': address, 'user_data_dir': user_data_dir, 'profile_directory': 'Default',
               'pid': 100}
    return {'status': 'ready', 'selected_browser': browser, 'eligible_browsers': [browser],
            'targets_by_address': {address: [{'type': 'page', 'url': url}]}, 'browser_count': 1}


def reusable_open(address, url):
    browser = {'debug_address': address, 'user_data_dir': '', 'pid': 101}
    return {'status': 'not_found', 'selected_browser': None, 'eligible_browsers': [browser],
            'targets_by_address': {address: [{'type': 'page', 'url': url}]}, 'browser_count': 1}


def reusable_taobao(address, urls):
    browser = {'debug_address': address, 'user_data_dir': '', 'pid': 102}
    return {'eligible_browsers': [browser],
            'targets_by_address': {address: [{'type': 'page', 'url': u} for u in urls]}}


LOGGED_IN = {'status': 'logged_in', 'shop_id': '1001', 'shop_name': '甲店', 'page_url': 'https://fxg/home',
             'error': None, 'detail': None}


def shop_requests(ctx):
    reqs = []

    def add(*args, **kwargs):
        reqs.append(R(*args, **kwargs))

    # ---- 账户列表
    add('GET', P + '/profiles')
    add('GET', P + '/profiles', None, before=S(fail={'list_profiles': RuntimeError('注册表读取失败')}))
    add('GET', P + '/profiles', None, before=lambda c: (c.state.update(fail={}), guard_probe(c)))
    # ---- current：没有浏览器
    add('GET', P + '/current')
    # ---- current：抖店，复用到属于当前账户的浏览器（confirmed → changed → 其它状态）
    add('GET', P + '/current', None, before=S(
        reusable=reusable_selected('127.0.0.1:9501', udir(ctx, DOUYIN)), identity=dict(LOGGED_IN)))
    add('GET', P + '/current', None, before=S(identity=dict(LOGGED_IN, shop_id='2002', shop_name='乙店')))
    add('GET', P + '/current', None, before=S(identity={'status': 'logged_out', 'shop_id': None, 'shop_name': None,
                                                         'error': '尚未登录', 'detail': 'x'}))
    add('GET', P + '/current', None, before=S(identity={'status': 'logged_in', 'shop_id': None, 'shop_name': None}))
    # 浏览器属于另一个账户 → conflict，不写注册表
    add('GET', P + '/current', None, before=S(
        reusable=reusable_selected('127.0.0.1:9502', udir(ctx, TAOBAO)), identity=dict(LOGGED_IN)))
    # 浏览器目录不属于任何已登记账户 → owner 为空，不写注册表
    add('GET', P + '/current', None, before=S(
        reusable=reusable_selected('127.0.0.1:9503', os.path.join(ctx.data_dir, 'elsewhere', 'x')),
        identity=dict(LOGGED_IN)))
    # 写注册表失败 → warning
    add('GET', P + '/current', None, before=S(
        reusable=reusable_selected('127.0.0.1:9501', udir(ctx, DOUYIN)), identity=dict(LOGGED_IN),
        fail={'observe_identity': OSError('磁盘已满')}))
    add('GET', P + '/current', None, before=S(fail={'observe_identity': ValueError('平台不匹配')}))
    # 读身份本身抛异常 → 接口级错误
    add('GET', P + '/current', None, before=S(fail={'read_account_identity': RuntimeError('CDP 断开')}))
    # 已有 GUI 页面：来源是 gui_page，浏览器信息来自进程枚举
    add('GET', P + '/current', None, before=chain(
        S(fail={}, identity=dict(LOGGED_IN), browsers=[
            {'debug_address': '127.0.0.1:9504', 'user_data_dir': udir(ctx, DOUYIN), 'profile_directory': 'Default'}]),
        set_page('127.0.0.1:9504')))
    add('GET', P + '/current', None, before=S(browsers=[]))
    # 抖店：枚举复用浏览器抛异常 → 当作没找到；候选无地址被跳过；只有一个停在登录页的浏览器 → open_browser
    add('GET', P + '/current', None, before=chain(reset_page, set_active(DOUYIN), S(
        reusable_fail=True, fail={}, identity=dict(LOGGED_IN))))
    add('GET', P + '/current', None, before=S(reusable_fail=False, reusable={
        'selected_browser': None,
        'eligible_browsers': [{'debug_address': '', 'user_data_dir': ''}, {'debug_address': '127.0.0.1:9520',
                                                                          'user_data_dir': ''}],
        'targets_by_address': {'127.0.0.1:9520': [{'type': 'page', 'url': 'devtools://x'},
                                                  {'type': 'background_page', 'url': 'https://fxg.jinritemai.com/'},
                                                  {'type': 'page', 'url': 'https://fxg.jinritemai.com/login'}]}}))
    add('GET', P + '/current', None, before=S(reusable=reusable_open('127.0.0.1:9521', 'https://example.com/')))
    # 竞态：读身份期间，注册表里这个账户的平台被别处改了 → conflict
    add('GET', P + '/current', None, before=S(
        reusable=reusable_selected('127.0.0.1:9501', udir(ctx, DOUYIN)), identity=dict(LOGGED_IN),
        identity_effect=lambda c: edit_registry(lambda r: r['profiles'][DOUYIN].__setitem__('platform', 'taobao'))(c)))
    add('GET', P + '/current', None, before=chain(
        S(identity_effect=None),
        edit_registry(lambda r: r['profiles'][DOUYIN].__setitem__('platform', 'douyin'))))
    # 当前账户在注册表里不存在
    add('GET', P + '/current', None, before=chain(reset_page, set_active('ghost-00000000')))
    # ---- current：淘宝
    add('GET', P + '/current', None, before=chain(
        set_active(TAOBAO), S(browsers=[], identity={'status': 'logged_in', 'shop_id': 'tb-1', 'shop_name': '淘宝店',
                                                      'account_id': 'unb-9'},
                              reusable=reusable_taobao('127.0.0.1:9510', [
                                  'devtools://x', 'https://www.taobao.com/', 'https://item.upload.taobao.com/sell/x']))))
    add('GET', P + '/current', None, before=S(
        reusable=reusable_taobao('127.0.0.1:9511', ['https://www.taobao.com/'])))
    add('GET', P + '/current', None, before=S(reusable=reusable_taobao('127.0.0.1:9512', ['https://example.com/'])))
    add('GET', P + '/current', None, before=S(reusable={
        'eligible_browsers': [{'debug_address': ''}, {'debug_address': '127.0.0.1:9514'}],
        'targets_by_address': {'127.0.0.1:9514': [{'type': 'service_worker', 'url': 'https://www.taobao.com/'}]}}))
    add('GET', P + '/current', None, before=S(reusable_fail=True))
    add('GET', P + '/current', None, before=S(
        reusable_fail=False, reusable=reusable_taobao('127.0.0.1:9513', ['https://item.upload.taobao.com/a']),
        identity={'status': 'logged_in', 'shop_id': None, 'shop_name': None, 'account_id': 'unb-9'}))
    # ---- current：小红书
    add('GET', P + '/current', None, before=chain(
        set_active(XHS), S(identity={'status': 'logged_in', 'shop_id': 'xhs-1', 'shop_name': '小红书店'},
                           xhs_targets={9505: [{'type': 'page', 'url': 'devtools://x'},
                                               {'type': 'page', 'url': 'https://customer.xiaohongshu.com/x'},
                                               {'type': 'page', 'url': 'https://ark.xiaohongshu.com/app'}]})))
    add('GET', P + '/current', None, before=S(xhs_targets={9506: [{'type': 'page',
                                                                    'url': 'https://school.xiaohongshu.com/'}]}))
    add('GET', P + '/current', None, before=S(xhs_targets={9507: [{'type': 'service_worker', 'url': 'x'}]}))
    add('GET', P + '/current', None, before=S(xhs_targets={9508: [{'type': 'page', 'url': 'https://example.com/'}]}))
    add('GET', P + '/current', None, before=S(xhs_targets={}))
    # ---- freight-templates
    add('GET', P + '/freight-templates', None, before=set_active(DOUYIN))
    add('GET', P + '/freight-templates', None, before=S(
        reusable=reusable_selected('127.0.0.1:9501', udir(ctx, DOUYIN)), identity=dict(LOGGED_IN),
        freight={'status': 'ok', 'templates': [{'id': 't1', 'name': '包邮'}], 'shop_id': '1001', 'current': None}))
    add('GET', P + '/freight-templates', None, before=S(
        freight={'status': 'ok', 'templates': [{'id': 't1', 'name': '包邮'}], 'shop_id': '9999',
                 'current': {'id': 't1'}}))
    add('GET', P + '/freight-templates', None, before=S(fail={'read_account_identity': RuntimeError('身份读取失败')}))
    add('GET', P + '/freight-templates', None, before=chain(
        S(fail={}), set_active(TAOBAO),
        S(browsers=[], reusable=reusable_taobao('127.0.0.1:9510', ['https://item.upload.taobao.com/x']),
          identity={'status': 'logged_in', 'shop_id': 'tb-1', 'shop_name': '淘宝店'},
          freight={'status': 'not_captured', 'templates': [], 'shop_id': None,
                   'current': '包邮模板', 'error': None, 'detail': 'd'})))
    add('GET', P + '/freight-templates', None, before=chain(set_active(DOUYIN), S(reusable={})))
    add('GET', P + '/freight-templates', None, before=set_active('ghost-00000000'))   # 抛异常 → 500
    # ---- add：参数校验
    add('POST', P + '/add', [], before=set_active(DOUYIN))
    add('POST', P + '/add', {'unknown': 1})
    add('POST', P + '/add', {'label': 5})
    add('POST', P + '/add', {'label': 'x' * 61})
    add('POST', P + '/add', {'open_browser': 'yes'})
    add('POST', P + '/add', {'platform': 'tmall'})
    add('POST', P + '/add', {'platform': 7})
    reqs.append(('POST', P + '/add', None, {'after': snap, 'data': 'bad', 'content_type': 'application/json'}))
    # ---- add：运行中的任务阻止账户变更
    add('POST', P + '/add', {'platform': 'taobao'}, before=running_task('upload', 'running'))
    add('POST', P + '/add', {'platform': 'taobao'}, before=running_task('upload', 'pending'))
    add('POST', P + '/add', {'platform': 'taobao'}, before=running_task('taobao', 'running'))
    add('POST', P + '/add', {'platform': 'taobao'}, before=running_task('taobao', 'pending'))
    add('POST', P + '/add', {'platform': 'taobao'}, before=running_task('upload', 'success'))
    # ---- add：成功路径
    add('POST', P + '/add', None, before=chain(clear_tasks, S(page_address='127.0.0.1:9601')))
    add('POST', P + '/add', {'platform': 'douyin', 'label': ' 新抖店 ', 'open_browser': False})
    add('POST', P + '/add', {'platform': 'taobao', 'label': '另一个淘宝'})
    add('POST', P + '/add', {'platform': 'taobao'})          # 复用空容器 taobao-bbbbbbbb
    add('POST', P + '/add', {'platform': 'xiaohongshu', 'open_browser': True})
    add('POST', P + '/add', {'platform': 'TAOBAO', 'label': None, 'open_browser': False})
    add('POST', P + '/add', {'platform': 'douyin'}, before=S(open_fail=True))
    add('POST', P + '/add', {'platform': 'douyin', 'open_browser': False}, before=S(open_fail=True))
    add('POST', P + '/add', {'platform': 'douyin'}, before=S(open_fail=False, fail={'create_profile': RuntimeError('磁盘只读')}))
    add('POST', P + '/add', {'platform': 'douyin'}, before=S(fail={'create_profile': ValueError('名称重复')}))
    add('POST', P + '/add', {'platform': 'douyin'}, before=S(fail={'set_active_profile': ValueError('不能激活')}))
    add('POST', P + '/add', {'platform': 'douyin'}, before=S(fail={'set_active_profile': OSError('注册表写入失败')}))
    # ---- switch：参数校验
    add('POST', P + '/switch', None, before=S(fail={}))
    add('POST', P + '/switch', [])
    add('POST', P + '/switch', {'profile_name': DOUYIN, 'extra': 1})
    add('POST', P + '/switch', {})
    add('POST', P + '/switch', {'profile_name': 5})
    add('POST', P + '/switch', {'profile_name': '   '})
    add('POST', P + '/switch', {'profile_name': DOUYIN, 'open_browser': 'no'})
    add('POST', P + '/switch', {'profile_name': DOUYIN}, before=running_task('upload', 'running'))
    add('POST', P + '/switch', {'profile_name': DOUYIN}, before=running_task('taobao', 'pending'))
    add('POST', P + '/switch', {'profile_name': '不存在的账户'}, before=clear_tasks)
    add('POST', P + '/switch', {'profile_name': 'ghost-00000000'})
    # ---- switch：成功路径（旧浏览器句柄必须被丢弃）
    add('POST', P + '/switch', {'profile_name': DOUYIN}, before=chain(
        set_page('127.0.0.1:9701'), lambda c: c.mod._set_browser_debug_instance({'debug_address': '127.0.0.1:9701'})))
    add('POST', P + '/switch', {'profile_name': TAOBAO, 'open_browser': False}, before=set_page('127.0.0.1:9702'))
    add('POST', P + '/switch', {'profile_name': XHS})
    add('POST', P + '/switch', {'profile_name': DEFAULT})
    add('POST', P + '/switch', {' profile_name ': 1})
    add('POST', P + '/switch', {'profile_name': ' ' + DOUYIN + ' ', 'open_browser': True})
    add('POST', P + '/switch', {'profile_name': DOUYIN}, before=S(open_fail=True))
    add('POST', P + '/switch', {'profile_name': DOUYIN}, before=S(open_fail=False, fail={'set_active_profile': ValueError('不能切换')}))
    add('POST', P + '/switch', {'profile_name': DOUYIN}, before=S(fail={'set_active_profile': RuntimeError('意外')}))
    add('POST', P + '/switch', {'profile_name': DOUYIN}, before=S(
        fail={}, override={'set_active_profile': lambda *a, **k: 'shop-eeeeeeee'}))
    add('POST', P + '/switch', {'profile_name': DOUYIN}, before=S(override={}))
    # ---- forget：参数校验
    add('POST', P + '/forget', None, before=S(fail={}))
    add('POST', P + '/forget', [])
    add('POST', P + '/forget', {})
    add('POST', P + '/forget', {'profile_name': 5})
    add('POST', P + '/forget', {'profile_name': '  '})
    add('POST', P + '/forget', {'profile_name': DOUYIN, 'purge': 'true'})
    add('POST', P + '/forget', {'profile_name': DOUYIN}, before=running_task('upload', 'running'))
    add('POST', P + '/forget', {'profile_name': DOUYIN}, before=running_task('taobao', 'running'))
    add('POST', P + '/forget', {'profile_name': 'ghost-00000000'}, before=clear_tasks)
    # ---- forget：受保护的默认账户 / 默认空占位
    # 前面的 add 流程把默认占位复用并写上了备注，所以它现在是「有备注的默认账户」，不能当空占位移除
    add('POST', P + '/forget', {'profile_name': DEFAULT}, before=set_active(DOUYIN))
    add('POST', P + '/forget', {'profile_name': DEFAULT}, before=edit_registry(
        lambda r: r['profiles'].__setitem__(DEFAULT, _entry(DEFAULT, 'douyin', shop_id='9')))
    )
    add('POST', P + '/forget', {'profile_name': DEFAULT}, before=edit_registry(
        lambda r: r['profiles'].__setitem__(DEFAULT, _entry(DEFAULT, 'douyin'))))
    add('POST', P + '/forget', {'profile_name': DEFAULT}, before=edit_registry(
        lambda r: r['profiles'].__setitem__(DEFAULT, _entry(DEFAULT, 'douyin'))))
    # ---- forget：成功（只摘记录 / 连目录一起删 / 目录不存在 / 删当前账户后交接）
    add('POST', P + '/forget', {'profile_name': XHS}, before=make_dir(XHS))
    add('POST', P + '/forget', {'profile_name': 'taobao-00000001', 'purge': True}, before=make_dir('taobao-00000001'))
    add('POST', P + '/forget', {'profile_name': TAOBAO, 'purge': True})
    add('POST', P + '/forget', {'profile_name': 'xhs-00000002'}, before=edit_registry(
        lambda r: r['profiles'].__setitem__('xhs-00000002', _entry('xhs-00000002', 'xiaohongshu'))))
    add('POST', P + '/forget', {'profile_name': DOUYIN, 'purge': True}, before=chain(set_active(DOUYIN), make_dir(DOUYIN)))
    add('POST', P + '/forget', {'profile_name': DOUYIN})
    # ---- forget：目录没删干净（记录已摘掉）/ 注册表写入失败 / 意外异常
    add('POST', P + '/forget', {'profile_name': 'shop-00000009', 'purge': True}, before=chain(
        edit_registry(lambda r: r['profiles'].__setitem__('shop-00000009', _entry('shop-00000009', 'douyin'))),
        make_dir('shop-00000009'), S(override={'remove_profile': lambda *a, **k: True})))
    add('POST', P + '/forget', {'profile_name': 'shop-00000009'}, before=S(
        override={}, fail={'remove_profile': OSError('注册表写入失败')}))
    add('POST', P + '/forget', {'profile_name': 'shop-00000009'}, before=S(fail={'remove_profile': ValueError('不能移除')}))
    add('POST', P + '/forget', {'profile_name': 'shop-00000009'}, before=S(fail={'remove_profile': RuntimeError('意外')}))
    return reqs


def final_shop(ctx):
    names = sorted(n for n in os.listdir(ctx.data_dir) if os.path.isdir(os.path.join(ctx.data_dir, n)))
    return {'dirs': [n for n in names if n not in ('logs', 'output', 'uploads', 'runtime')],
            'registry': snap(ctx)['registry']}


SCENARIOS['shop'] = dict(
    setup=setup,
    patch_old=patch_old,
    patch_new=patch_new,
    build_new=build_new,
    new_via_app=True,
    requests=shop_requests,
    final=final_shop,
)

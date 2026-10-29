# -*- coding: utf-8 -*-
"""链接采集：HTTP 流程对打 + 场景注册（2026-10-20）。

请求按「参数与错误 → 1688 主流程与各失败分支 → 淘宝 / 天猫 → 店铺 → 互斥与取消 → 导入 → 直接调用」排列。
每个会起采集线程的请求，before 钩子把假件行为 / 虚拟时钟重置到固定值（任务 id 因此可预测），after 钩子等线程结束再取快照。
"""
import json
import os
import sys

import scen_capture as S
import scen_capture_direct as D1
import scen_capture_direct2 as D2
from scenarios import SCENARIOS

START = '/api/capture/start'
LOGIN_1688 = 'https://login.1688.com/member/signin.htm'
LOGIN_TAOBAO = 'https://login.taobao.com/member/login.jhtml'
PUNISH = 'https://sec.taobao.com/query.htm?punish=1'
PAGE_OTHER = 'https://detail.1688.com/offer/999.html'
HOME_1688 = 'https://www.1688.com/'


# ------------------------------------------------------------------------------------------ 钩子
def prep(k, *, prefs=None, engine=(False, False), fakes=None, proxy='', occupied=(), block=False, **behavior):
    """启动请求的 before：重置假件行为（同时还原上个请求替换的函数）、虚拟时钟、设置偏好、引擎故障开关，按需替换函数。"""
    def before(ctx):
        S.reset_behavior(ctx, **behavior)
        state = ctx.state
        state['clock'].now = float(S.START_CLOCK + 1000 * k)
        state['mode_prefs'] = prefs
        state['proxy_hint'] = proxy
        state['occupied'] = set(occupied)
        state['engine'].fail_build, state['engine'].fail_writes = engine
        state['clock'].block_next = block
        for old_name, make in (fakes or {}).items():
            S.patch_fn(ctx, old_name, make(ctx))
    return before


def settle(task_id, extra=None):
    return S.settle(task_id, extra)


def wait_blocked(ctx):
    S.wait_until(lambda: ctx.state['clock'].entered.is_set())
    return {'running_id': S.running_id(ctx), 'task': None}


def release_and_settle(task_id):
    def after(ctx):
        right_after_cancel = S.running_id(ctx)               # 取消刚返回、采集线程还挂着的时候，互斥锁是不是已经释放了
        ctx.state['clock'].release.set()
        view = S.settle(task_id)(ctx)
        view['running_id_right_after_cancel'] = right_after_cancel
        return view
    return after


def seed_ghost_task(ctx):
    """往任务字典里放一个「运行中、但不是互斥锁持有者」的任务（取消它不该顺手释放别人的互斥锁）。"""
    with S.lock_of(ctx):
        S.tasks_of(ctx)['ghost'] = {'task_id': 'ghost', 'url': 'u', 'status': 'running', 'progress': 50, 'message': '提取中',
                                    'error_code': '', 'platform': '1688', 'capture_mode': 'dom', 'result': None,
                                    'created_at': '2026-01-01T00:00:00', 'cancelled': False}


def cancel_when_blocked(ctx):
    S.wait_until(lambda: ctx.state['clock'].entered.is_set())


def block_then(value):
    """antibot / url 序列里用的条目：被读到时让采集线程在下一次 sleep 里挂起，并返回 value。"""
    def entry(page):
        page.state['clock'].block_next = True
        return value
    return entry


def with_drission_missing(ctx):
    ctx.state['saved_drission'] = sys.modules.get('DrissionPage')
    sys.modules['DrissionPage'] = None


def restore_drission(task_id):
    def after(ctx):
        S.wait_workers_done()                       # 先等采集线程跑完（它在函数内才导入 DrissionPage），再还原假模块
        sys.modules['DrissionPage'] = ctx.state['saved_drission']
        return S.settle(task_id)(ctx)
    return after


def records_view(ctx):
    return {'records': [{'name': r.name, 'title': r.title, 'clazz': r.clazz, 'type': r.type, 'source': r.import_source,
                         'url': r.source_url, 'managed': r.managed_files, 'attrs': r.captured_attributes,
                         'skus': len(json.loads(r.content or '[]'))} for r in ctx.Record.select().order_by(ctx.Record.id)]}


# ------------------------------------------------------------------------------------------ 淘宝 / 店铺用的假采集函数
def product_payload(ctx, url, *, with_download):
    from capture_url_utils import normalize_capture_url          # noqa: F401  —— 保证 capture_url_utils 已在 sys.path
    import re
    pid = re.search(r'id=(\d+)', url).group(1)
    if with_download:             # 目录和 SKU 图都是真的（能通过导入校验）
        data = D2.product_for(ctx, pid)
        data['detail_images'] = ['https://img.alicdn.com/d/%s_1.jpg' % pid]
        return data
    imgs = ['https://img.alicdn.com/m/%s_1.jpg' % pid, 'https://img.alicdn.com/m/%s_tiny.png' % pid,
            'https://img.alicdn.com/m/%s_404.webp' % pid, 'https://img.alicdn.com/m/%s_boom.gif' % pid, '//img.alicdn.com/m/%s_2.jpeg' % pid]
    data = {'product_id': pid, 'title': '袜子' + pid, 'price': {'current': 9.9, 'original': None, 'currency': 'CNY'},
            'main_images': imgs, 'detail_images': ['https://img.alicdn.com/d/%s_1.jpg' % pid, 'https://img.alicdn.com/d/%s_tiny.jpg' % pid],
            'sku_info': [{'index': 1, 'name': '白色/均码', 'image': 'https://img.alicdn.com/s/%s_w.jpg' % pid, 'price': 9.9},
                         {'index': 2, 'name': '灰色*:?', 'image': 'https://img.alicdn.com/s/%s_g.png' % pid, 'price': 9.9},
                         {'index': 3, 'name': '无图', 'image': '', 'price': 9.9}],
            'parameters': [], 'url': url}
    return data


def fake_capture(with_download=True, fail=None, per_url=None):
    def make(ctx):
        def capture(page, product_url, options, mtop_cache=None):
            ctx.state['log'].append(['fake_capture', product_url, dict(options or {}), mtop_cache is not None])
            if per_url and product_url in per_url:
                outcome = per_url[product_url]
                if isinstance(outcome, BaseException):
                    raise outcome
                if outcome == 'block':
                    ctx.state['clock'].block_next = True
            elif fail is not None:
                raise fail
            return product_payload(ctx, product_url, with_download=with_download)
        return capture
    return make


def fake_store_urls(urls):
    def make(ctx):
        def collect(page, store_url, max_products=1000, max_pages=50):
            ctx.state['log'].append(['fake_store_urls', store_url, max_products, max_pages])
            return list(urls)
        return collect
    return make


def store_item(n):
    return 'https://item.taobao.com/item.htm?id=%d' % (7000 + n)


def combine(*makers_by_name):
    merged = {}
    for mapping in makers_by_name:
        merged.update(mapping)
    return merged


# ------------------------------------------------------------------------------------------ 请求列表
def requests(ctx):
    R = []
    add = R.append
    u16 = S.URL_1688
    cap = '/api/capture/'

    def run(k, url, payload_extra=None, extra=None, **kw):
        payload = {'url': url}
        payload.update(payload_extra or {})
        add(('POST', START, payload, {'before': prep(k, **kw), 'after': settle(S.tid(k, url), extra)}))
        return S.tid(k, url)

    # ---- 参数与错误（不起线程）----
    add(('POST', START, None))
    add(('POST', START, {}))
    add(('POST', START, {'url': '   '}))
    add(('POST', START, {'url': 'https://example.com/a'}))
    add(('POST', START, {'url': 'https://m.tb.cn/h.fail'}))
    add(('POST', START, {'url': 'https://m.tb.cn/h.bad'}))
    add(('GET', cap + 'status/none', None))
    add(('GET', cap + 'history', None))
    add(('POST', cap + 'cancel/none', {}))

    # ---- 1688 主流程 ----
    t1 = run(1, u16, extra=S.products_tree)
    add(('GET', cap + 'status/' + t1, None))
    add(('GET', cap + 'history', None))
    add(('POST', cap + 'cancel/' + t1, {}))
    add(('POST', cap + 'import', {'task_id': t1}, {'after': records_view}))
    add(('POST', cap + 'import', {'task_id': t1}, {'after': records_view}))

    # ---- 1688 各失败 / 分支 ----
    run(2, u16, antibot=[True])                                                   # 风控验证一直不过：超时
    run(3, u16, antibot=[True, True, False])                                      # 风控验证中途通过
    run(5, u16, start_url=PAGE_OTHER, get_redirect=PAGE_OTHER)                    # URL 与目标商品不一致，重导航也不对
    run(6, u16, ready={'offer_id': '777'})                                        # offerDetail 填的是别的商品
    run(7, u16, ready=None, snapshot={})                                          # 18 秒内没填充，快照也是空
    run(8, u16, snapshot=RuntimeError('模拟快照异常'))                              # 快照抛异常
    run(9, u16, proxy='⚠️ 代理提示', start_url=LOGIN_1688, url_sequence=[LOGIN_1688, LOGIN_1688, LOGIN_1688, S.PAGE_1688])
    run(10, u16, start_url=LOGIN_1688, url_sequence=[LOGIN_1688, LOGIN_1688, HOME_1688], stop_sequence_after_get=True)
    run(11, u16, proxy='⚠️ 代理提示', start_url=LOGIN_1688, url_sequence=[LOGIN_1688])                  # 登录等待超时（带代理提示）
    run(12, u16, start_url=LOGIN_TAOBAO, url_sequence=[LOGIN_TAOBAO])                                  # 1688 任务落在淘宝登录页上
    run(13, u16, start_url=LOGIN_1688, url_sequence=[LOGIN_1688, LOGIN_1688, HOME_1688],
        get_errors={'123456': RuntimeError('重新导航失败')})
    add(('POST', START, {'url': u16}, {'before': lambda c: (prep(14)(c), with_drission_missing(c)), 'after': restore_drission(S.tid(14, u16))}))
    err = OSError('[WinError 10048] address in use')
    err.winerror = 10048
    run(15, u16, page_error=err)                                                  # 网络资源耗尽
    run(16, u16, occupied=range(9400, 9500))                                      # 没有可用的采集浏览器端口
    run(17, u16, init_js_fail=True)                                               # add_init_js 不可用，降级为 run_js
    run(18, u16, init_js_fail=True, extra_js=[('[capture-init]', RuntimeError('注入失败'))])
    run(19, u16, targets=[{'type': 'page', 'id': 'tab-1', 'url': 'x', 'webSocketDebuggerUrl': 'ws://fail/p'}])        # CDP 连接失败，降级 page.get
    run(20, u16, targets=[{'type': 'page', 'id': 'tab-1', 'url': 'x', 'webSocketDebuggerUrl': 'ws://fail/p'}],
        get_errors={'123456': RuntimeError('导航失败')})                              # 连降级导航也失败
    run(21, u16, targets=[{'type': 'service_worker', 'id': 'sw', 'url': 'x'}])    # 没有 page 目标
    run(22, u16, tab_id='')                                                       # 当前标签页 id 为空：取第一个 page 目标
    run(23, u16, tab_id_error=True)                                               # 读 tab_id 抛异常
    run(24, u16, {'options': {'download_images': False, 'extract_sku': True, 'extract_params': False}})
    run(25, u16, {'options': {'download_images': True, 'extract_params': True, 'save_path': 'uploads/custom'}},
        extra=S.products_tree, prefs={'alibaba_1688_mode': 'protocol'})
    run(26, u16, engine=(True, False))                                            # 协议采集引擎初始化失败
    run(27, u16, engine=(False, True), prefs={'alibaba_1688_mode': 'protocol', 'taobao_tmall_mode': 'dom'})
    run(28, u16, prefs='boom')                                                    # 读取采集偏好失败
    run(29, u16, ready=RuntimeError('页面脚本异常'))                                  # 就绪检查一直抛异常
    run(30, u16, snapshot={'title': 'T30', 'offer_images': ['//cbu01.alicdn.com/o.jpg'], 'current_prices': [{'price': 'abc'}],
                           'sku_props': [], 'sku_map': [], 'detail_url': ''})
    run(31, u16, snapshot={'title': 'T31', 'main_images': ['https://cbu01.alicdn.com/m.jpg'], 'current_prices': [],
                           'sku_props': [{'prop': '颜色', 'value': [{'name': '红'}]}], 'sku_map': [],
                           'detail_url': 'https://img.alicdn.com/desc/broken'})

    def url_unavailable(page):
        raise RuntimeError('页面地址暂时读不到')
    run(32, u16, url_sequence=[S.PAGE_1688, S.PAGE_1688, url_unavailable, S.PAGE_1688], stop_sequence_after_get=True)     # 读取页面地址抛异常
    run(33, u16, start_url=PAGE_OTHER, get_redirect=PAGE_OTHER, get_errors={'123456': RuntimeError('重新导航失败')})       # 不一致，重新导航也抛异常
    run(34, u16, cdp_ready=[False, RuntimeError('页面脚本异常'), True])                                                    # CDP 导航后轮询 window.context
    run(35, u16, ws_send_fail_first=True)                                                                                 # 注册持久化脚本失败，不影响采集
    run(36, u16, prefs={'alibaba_1688_mode': 'weird'})                                                                    # 非法的采集方式回落到 dom
    run(37, u16, proxy=RuntimeError('代理检测崩了'))                                                                       # 登录检测整体异常：吞掉继续
    run(38, u16, antibot=[True, False], get_errors={'123456': RuntimeError('刷新失败')})                                    # 验证通过后重新进入商品页失败

    # ---- 淘宝 / 天猫 ----
    ut, um = S.URL_TAOBAO, S.URL_TMALL
    cap_ok = {'_capture_taobao_tmall_product_for_store': fake_capture(True)}
    cap_dl = {'_capture_taobao_tmall_product_for_store': fake_capture(False)}
    run(40, ut, start_url=ut, fakes=cap_ok, extra=S.products_tree)
    run(41, um, start_url=um, fakes=cap_dl, extra=S.products_tree)
    run(42, ut, start_url=ut, fakes=cap_ok, get_errors={'www.taobao.com': RuntimeError('首页访问失败')})
    run(43, ut, start_url=ut, fakes=cap_ok, get_errors={'item.htm': RuntimeError('页面刷新了')})
    run(44, ut, start_url=ut, fakes=cap_ok, get_errors={'item.htm': RuntimeError('网络错误')})
    run(45, ut, start_url=ut, fakes=cap_ok, url_sequence=[PUNISH, PUNISH, ut])
    run(46, ut, start_url=ut, fakes=cap_ok, url_sequence=[PUNISH])
    run(48, ut, start_url=ut, fakes=cap_ok, url_sequence=[LOGIN_TAOBAO, LOGIN_TAOBAO, ut])
    run(49, ut, start_url=ut, fakes=cap_ok, proxy='⚠️ 代理提示', url_sequence=[LOGIN_TAOBAO])
    run(50, ut, start_url=ut, fakes=cap_ok, url_sequence=[LOGIN_TAOBAO, LOGIN_TAOBAO, 'https://www.taobao.com/'])
    run(51, ut, start_url=ut, fakes={'_capture_taobao_tmall_product_for_store': fake_capture(fail=ValueError('商品标题或主图未能完整读取'))})
    run(52, ut, {'options': {'save_path': 'D:/not-created/uploads'}}, start_url=ut, fakes=cap_dl, prefs={'taobao_tmall_mode': 'protocol'})
    def id_returns_empty(ctx):
        calls = {'n': 0}

        def fake(url):
            calls['n'] += 1
            return 'x' if calls['n'] == 1 else ''
        return fake

    def id_raises(ctx):
        calls = {'n': 0}

        def fake(url):
            calls['n'] += 1
            if calls['n'] > 1:
                raise RuntimeError('提取商品 ID 失败')
            return 'x'
        return fake
    run(55, ut, start_url=ut, fakes=combine(cap_ok, {'_extract_capture_product_id': id_returns_empty}))
    run(56, ut, start_url=ut, fakes=combine(cap_ok, {'_extract_capture_product_id': id_raises}))
    # 淘宝短链解析成功后启动任务
    run(53, 'https://item.taobao.com/item.htm?id=555000&spm=x', start_url=ut, fakes=cap_ok)
    add(('POST', START, {'url': 'https://m.tb.cn/h.ok'}, {'before': prep(54, start_url=ut, fakes=cap_ok),
                                                         'after': settle(S.tid(54, 'https://item.taobao.com/item.htm?id=555000&spm=x'))}))

    # ---- 店铺 ----
    us = S.URL_STORE
    urls = [store_item(i) for i in range(1, 7)]
    verify = {store_item(2): Exception('触发验证'), store_item(3): Exception('PUNISH page'), store_item(4): Exception('跳转到 sec.taobao.com'),
              store_item(6): Exception('其他错误')}
    store_fakes = combine({'_collect_taobao_tmall_store_product_urls': fake_store_urls(urls)},
                          {'_capture_taobao_tmall_product_for_store': fake_capture(True, per_url=verify)})
    run(60, us, {'options': {'request_interval_seconds': 1, 'max_store_products': 50, 'max_store_pages': 3}}, start_url=us, fakes=store_fakes)
    run(61, us, start_url=us, fakes={'_collect_taobao_tmall_store_product_urls': fake_store_urls([])})
    all_fail = {u: Exception('采集不了') for u in urls[:2]}
    run(62, us, start_url=us, fakes=combine({'_collect_taobao_tmall_store_product_urls': fake_store_urls(urls[:2])},
                                            {'_capture_taobao_tmall_product_for_store': fake_capture(True, per_url=all_fail)}))
    run(63, us, start_url=us, url_sequence=[LOGIN_TAOBAO, LOGIN_TAOBAO, us],
        fakes=combine({'_collect_taobao_tmall_store_product_urls': fake_store_urls(urls[:1])},
                      {'_capture_taobao_tmall_product_for_store': fake_capture(True)}))
    add(('POST', cap + 'import', {'task_id': S.tid(60, us)}, {'after': records_view}))
    add(('POST', cap + 'import', {'task_id': S.tid(62, us)}, {'after': records_view}))                  # 任务失败了，没有 result
    add(('POST', cap + 'import', {'task_id': 'direct', 'product_data': {'capture_type': 'store', 'products': [
        {'download_path': '', 'url': 'u1'}, 'junk']}}, {'after': records_view}))
    # 店铺采集中途被取消：第一件商品采完后在请求间隔里挂起，取消后唤醒，下一轮循环发现任务已失败而返回
    cancel_urls = urls[:3]
    cancel_fakes = combine({'_collect_taobao_tmall_store_product_urls': fake_store_urls(cancel_urls)},
                           {'_capture_taobao_tmall_product_for_store': fake_capture(True, per_url={cancel_urls[0]: 'block'})})
    add(('POST', START, {'url': us}, {'before': prep(64, start_url=us, fakes=cancel_fakes), 'after': wait_blocked}))
    add(('POST', cap + 'cancel/' + S.tid(64, us), {}, {'after': release_and_settle(S.tid(64, us))}))

    # ---- 取消正在等待风控验证的 1688 任务 ----
    add(('POST', START, {'url': u16}, {'before': prep(65, antibot=[block_then(True)]), 'after': wait_blocked}))
    add(('POST', cap + 'cancel/' + S.tid(65, u16), {}, {'after': release_and_settle(S.tid(65, u16))}))
    # ---- 取消正在等待安全验证的淘宝任务 ----
    add(('POST', START, {'url': ut}, {'before': prep(66, start_url=ut, fakes=cap_ok, url_sequence=[block_then(PUNISH)]), 'after': wait_blocked}))
    add(('POST', cap + 'cancel/' + S.tid(66, ut), {}, {'after': release_and_settle(S.tid(66, ut))}))
    # ---- 取消正在等待登录的淘宝任务 ----
    add(('POST', START, {'url': ut}, {'before': prep(67, start_url=ut, fakes=cap_ok, url_sequence=[LOGIN_TAOBAO, block_then(LOGIN_TAOBAO)]),
                                      'after': wait_blocked}))
    add(('POST', cap + 'cancel/' + S.tid(67, ut), {}, {'after': release_and_settle(S.tid(67, ut))}))

    # ---- 互斥：第一个任务挂起时，第二个被拒绝；取消后第三个可以正常启动 ----
    add(('POST', START, {'url': u16}, {'before': prep(70, block=True), 'after': wait_blocked}))
    add(('POST', START, {'url': um}))                                              # 已有任务在跑：被拒绝
    add(('POST', cap + 'cancel/ghost', {}, {'before': seed_ghost_task, 'after': lambda c: {'running_id': S.running_id(c)}}))
    add(('POST', cap + 'cancel/' + S.tid(70, u16), {}, {'after': release_and_settle(S.tid(70, u16))}))
    run(72, u16)
    # ---- 启动过程中出错：互斥锁必须被释放 ----
    def broken_start(ctx):
        def start(**kwargs):
            raise RuntimeError('协议记录初始化异常')
        return start
    add(('POST', START, {'url': u16}, {'before': prep(73, fakes={'_start_protocol_capture_record': broken_start}),
                                       'after': lambda c: {'running_id': S.running_id(c), 'tasks': sorted(S.tasks_of(c))[-3:]}}))
    run(74, u16)

    add(('GET', cap + 'history', None))                                            # 前面已经有很多任务：看排序

    # ---- 导入 ----
    add(('POST', cap + 'import', {}))
    add(('POST', cap + 'import', {'task_id': 't'}))
    add(('POST', cap + 'import', {'task_id': 'x', 'product_data': {'download_path': 'nope', 'title': 'x'}}))
    add(('POST', cap + 'import', {'task_id': 'x', 'product_data': {}}))
    add(('POST', cap + 'import', None))

    # ---- 不经 HTTP 的直接调用 ----
    for name, func in (('pure', D1.pure_helpers), ('protocol', D1.protocol_artifacts), ('proxy', D1.proxy_risk),
                       ('extractors', D1.page_extractors), ('cdp_mtop', D1.cdp_and_mtop), ('desc_snapshot', D2.desc_and_snapshot),
                       ('product_capture', D2.product_capture), ('attrs_ports_import', D2.attributes_ports_import)):
        add(('GET', '/health', None, {'after': func}))
    return R


def setup(ctx):
    S.install_fakes(ctx)


def patch(ctx):
    pass


def final(ctx):
    from collections import Counter
    engine = ctx.state['engine']
    with S.lock_of(ctx):
        tasks = json.loads(json.dumps(S.tasks_of(ctx), ensure_ascii=False, default=str))
    clock = ctx.state['clock']
    return {'tasks': tasks, 'running_id': S.running_id(ctx), 'engine_runs': engine.runs, 'engine_writes': engine.writes,
            'sleep_count': len(clock.sleeps), 'sleep_total': sum(clock.sleeps),
            'sleep_histogram': sorted(Counter(clock.sleeps).items()),
            'mtop_cache': sorted(S.mtop_cache_of(ctx)), 'cookies': list(S.cookie_state(ctx)),
            'products': S.products_tree(ctx), 'records': records_view(ctx)['records']}


SCENARIOS['capture'] = dict(
    setup=lambda ctx: None,
    patch_old=setup,
    patch_new=setup,
    new_via_app=True,
    requests=requests,
    final=final,
)

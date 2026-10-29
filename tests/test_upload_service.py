# -*- coding: utf-8 -*-
"""``UploadService`` 的直接测试（2026-10-21 从 app.py 搬出）。

搬出之前这些函数是 app.py 里互相调用的模块级函数，只能靠 ``exec`` 源码文本或整套 Flask 来测；现在服务对象的依赖都是注入的，
所以这里直接构造真实的 ``UploadService``，页面步骤 / 浏览器 / 设置 / 商品表 / 日志全部换成剧本替身（见 ``tests/upload_test_support.py``），
一个真实的浏览器、数据库、网络都不碰。

覆盖：停在提交前的判定矩阵、记录与配置的读取、发布浏览器会话的每条分支、DOM 流水线（成功 / 停在提交前 / 步骤失败 / 素材不全 /
页面未就绪 / 取消 / 会话失败 / 意外异常 / 协议模式分派）、后台 worker 的每个结局、纯协议流水线的主要路径、
找已有抖店浏览器、协议运行时配置探针、阶段耗时日志，以及“导入本模块不会拖进浏览器库”。
"""
import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.sidecar import upload_service  # noqa: E402
from upload_test_support import (  # noqa: E402
    DEFAULT_ASSETS, STEP_NAMES, World, make_record, make_upload_service,
)

RECORDS = [make_record(1), make_record(2, name='白袜_货号_y_商品二')]
FLOW_STAGES = ['prepare_record_assets', 'open_publish_page', 'fill_title_for_record', 'upload_main_images',
               'select_category_and_prepare_attributes', 'fill_category_attributes', 'upload_media_assets',
               'configure_sku_entries', 'configure_sku_structure', 'fill_price_stock_and_delivery', 'submit_publish',
               'settle_between_records']


class FakeTab:
    def __init__(self, url='https://fxg.jinritemai.com/ffa/g/create', fail_get=0):
        self.url = url
        self.title = '发布商品'
        self.gets = []
        self._fail_get = fail_get

    def get(self, url):
        self.gets.append(url)
        if len(self.gets) <= self._fail_get:
            raise RuntimeError('导航失败%d' % len(self.gets))


class FakePage:
    def __init__(self, tab=None, tab_error=None):
        self.latest_tab = 'tab-1'
        self._tab = tab or FakeTab()
        self._tab_error = tab_error

    def get_tab(self, _tab_id):
        if self._tab_error:
            raise self._tab_error
        return self._tab


@pytest.fixture
def world(tmp_path):
    return World(tmp_path, records=RECORDS)


@pytest.fixture(autouse=True)
def restore_sys_path():
    """流水线会往 sys.path 里插目录（协议模块的位置）：每个用例结束后还原，别污染后面的测试。"""
    saved = list(sys.path)
    yield
    sys.path[:] = saved


def flow(world, **kwargs):
    """跑 DOM 流水线，会话建立直接给一个标签页（会话本身在别处测）。"""
    tab = kwargs.pop('tab', None) or FakeTab()
    world.service.ensure_publish_session = lambda report: (tab, None)
    return world.service.execute_upload_flow(**kwargs), tab


# ============================================================================================ 停在提交前的判定
@pytest.mark.parametrize('data, expected', [
    (None, (True, False)),
    ({}, (True, False)),
    ({'stop_before_submit': True}, (True, False)),
    ({'stopBeforeSubmit': True}, (True, False)),
    ({'stop_before_submit': False, 'confirm_final_publish': True}, (False, True)),
    ({'stopBeforeSubmit': False, 'confirmFinalPublish': True}, (False, True)),
    ({'stop_before_submit': 'false', 'confirm_final_publish': 'yes'}, (False, True)),
    ({'stop_before_submit': True, 'confirm_final_publish': True}, (True, True)),    # 只要停在提交前，确认与否都不影响
    ({'stop_before_submit': 'off', 'confirm_final_publish': '1'}, (False, True)),
])
def test_resolve_stop_before_submit(data, expected):
    assert make_upload_service().resolve_stop_before_submit(data) == expected


@pytest.mark.parametrize('data', [
    {'stop_before_submit': False},
    {'stopBeforeSubmit': False, 'confirm_final_publish': False},
    {'stop_before_submit': 'false', 'confirm_final_publish': 'no'},
    {'stop_before_submit': False, 'confirmFinalPublish': None},
])
def test_final_publish_without_confirmation_is_refused(data):
    """最终发布必须显式确认：没确认就只能做“停在提交前”的预检，绝不悄悄发出去。"""
    with pytest.raises(ValueError) as excinfo:
        make_upload_service().resolve_stop_before_submit(data)
    assert 'confirm_final_publish=true' in str(excinfo.value)


# ============================================================================================ 记录与配置
def test_load_records_by_id(world):
    records, error = world.service._load_upload_records(2)
    assert error is None and [r.id for r in records] == [2]


def test_load_records_unknown_id(world):
    assert world.service._load_upload_records(99) == (None, '指定产品不存在')


def test_load_records_empty_table(tmp_path):
    assert World(tmp_path).service._load_upload_records() == (None, '没有待上传数据！')


def test_load_records_without_id_returns_every_record_regardless_of_status(tmp_path):
    """⚠️ 现状如此（搬迁没改）：不带 id 时取**全部**记录，不按 status 过滤。

    而 ``/api/upload/start-all`` 只拿 ``status == 0`` 的记录来算“N 个商品”，worker 却用这里取到的全部记录跑——
    已发布（status=1）和“已提交待确认”（status=2）的商品都会被再发一遍。淘宝 / 小红书的批量发布都带了 ``status == 0``。
    见方案文档「未决问题」第 30 条；改这个行为时同步改这条测试。
    """
    world = World(tmp_path, records=[make_record(1, status=0), make_record(2, status=1), make_record(3, status=2)])
    records, error = world.service._load_upload_records()
    assert error is None and [r.id for r in records] == [1, 2, 3]


def config(tmp_path, **automation):
    return World(tmp_path, automation=automation).service._load_upload_runtime_config()


def test_runtime_config_defaults(tmp_path):
    template, materials, wash = config(tmp_path)
    assert (template, materials, wash) == ('中通包邮', [('棉', '75'), ('氨纶', '25')], '')


def test_runtime_config_materials_are_cleaned(tmp_path):
    template, materials, _ = config(
        tmp_path, shipping_template='  顺丰  ',
        material_compositions=[{'material': ' 棉 ', 'percentage': '60.9'}, {'material': '', 'percentage': 10}, 'bad',
                               {'material': '氨纶', 'percentage': 'x'}, {'material': '涤纶', 'percentage': 40}])
    assert template == '顺丰'
    assert materials == [('棉', '60.9'), ('涤纶', '40')]          # 保留小数；没名字 / 非数字 / 非字典的丢掉


def test_runtime_config_falls_back_when_every_material_is_invalid(tmp_path):
    _, materials, _ = config(tmp_path, material_compositions=[{'material': '棉', 'percentage': 'abc'}])
    assert materials == [('棉', '75'), ('氨纶', '25')]


def test_runtime_config_blank_template_uses_default(tmp_path):
    assert config(tmp_path, shipping_template='   ')[0] == '中通包邮'


def test_runtime_config_wash_label_image_must_exist(tmp_path, capsys):
    image = tmp_path / 'tag.png'
    image.write_bytes(b'x')
    assert config(tmp_path, wash_label_tag_image_path=str(image))[2] == str(image)
    assert config(tmp_path, wash_label_tag_image_path=str(tmp_path / 'missing.png'))[2] == ''
    assert '水洗标/吊牌图不存在' in capsys.readouterr().out


# ============================================================================================ 阶段耗时日志
def test_stage_timing_returns_the_result_and_records_an_ok_entry(world):
    timings = []
    result = world.service._run_stage_with_timing(timings, make_record(5), 'fill_title', lambda a, b=0: a + b, 1, b=2)
    assert result == 3
    assert [(t['stage'], t['status'], t['record_id'], t['error']) for t in timings] == [('fill_title', 'ok', 5, None)]
    logged = [json.loads(line) for line in Path(world.service._stage_timing_log_path).read_text(encoding='utf-8').splitlines()]
    assert logged == timings


def test_stage_timing_marks_a_false_result_as_failed_but_still_returns_it(world):
    timings = []
    assert world.service._run_stage_with_timing(timings, make_record(5), 'open', lambda: False) is False
    assert (timings[0]['status'], timings[0]['error']) == ('failed', 'stage returned False')


def test_stage_timing_records_the_error_and_reraises(world):
    timings = []

    def boom():
        raise ValueError('炸了')
    with pytest.raises(ValueError, match='炸了'):
        world.service._run_stage_with_timing(timings, make_record(5), 'submit', boom)
    assert (timings[0]['status'], timings[0]['error']) == ('failed', '炸了')


def test_timing_log_failures_never_break_the_flow(world, tmp_path):
    world.service._stage_timing_log_path = str(tmp_path)            # 目录当文件打开：写日志必然失败
    world.service._append_stage_timing_log({'x': 1})                  # 不抛即可


# ============================================================================================ 发布浏览器会话
def session_world(tmp_path, *, page=None, **overrides):
    return World(tmp_path, page=page, **overrides)


def test_session_opens_a_new_browser_when_there_is_none(tmp_path):
    tab = FakeTab()
    page = FakePage(tab)
    world = session_world(tmp_path, browser_overrides={'open_page': lambda url, profile_name=None: world.calls.append(('open_page', url, profile_name)) or page})
    main_tab, error = world.service.ensure_publish_session(lambda *a: None)
    assert (main_tab, error) == (tab, None)
    assert world.state.page is page
    assert ('open_page', 'https://example.invalid/ffa/g/create', 'shop-a') in world.calls
    assert tab.gets == []                         # 刚开的浏览器已经在发布页，不再导航
    assert world.count('wait_login_complete') == 1


def test_session_reuses_an_attached_browser_and_navigates_to_the_publish_page(tmp_path):
    tab = FakeTab(url='https://fxg.jinritemai.com/home')
    world = session_world(tmp_path, browser_overrides={'attach_reusable_browser': lambda report: world.state.__setattr__('page', FakePage(tab)) or tab})
    main_tab, error = world.service.ensure_publish_session(lambda *a: None)
    assert (main_tab, error) == (tab, None)
    assert tab.gets == ['https://example.invalid/ffa/g/create']
    assert world.count('dismiss_pending_browser_alert') == 1


def test_session_open_failure_is_reported(tmp_path, capsys):
    def fail(*_a, **_k):
        raise RuntimeError('chrome 起不来')
    world = session_world(tmp_path, browser_overrides={'open_page': fail})
    assert world.service.ensure_publish_session(lambda *a: None) == (None, '浏览器启动失败：chrome 起不来')
    assert world.state.page is None


def test_session_only_reattaches_when_the_current_tab_is_not_a_logged_in_page(tmp_path):
    attached = []
    for url, expected in (('https://fxg.jinritemai.com/ffa/g/create', 0), ('https://sso.douyin.com/login', 1), ('', 1)):
        tab = FakeTab(url=url)
        world = session_world(tmp_path, page=FakePage(tab),
                              browser_overrides={'attach_reusable_browser': lambda report, attached=attached: attached.append(1) or None})
        attached.clear()
        main_tab, error = world.service.ensure_publish_session(lambda *a: None)
        assert (main_tab, error) == (tab, None) and len(attached) == expected


def test_session_recovers_from_a_dead_page_through_an_attached_browser(tmp_path):
    tab = FakeTab()
    world = session_world(tmp_path, page=FakePage(tab_error=RuntimeError('页面已关闭')),
                          browser_overrides={'attach_reusable_browser': lambda report: tab})
    # 第一次取标签页就失败（既用来读 URL 也用来取 main_tab）：走“重新附着”那条分支
    main_tab, error = world.service.ensure_publish_session(lambda *a: None)
    assert (main_tab, error) == (tab, None)
    assert tab.gets == ['https://example.invalid/ffa/g/create']


def test_session_reopen_failure_is_reported(tmp_path):
    def fail(*_a, **_k):
        raise RuntimeError('重开失败')
    world = session_world(tmp_path, page=FakePage(tab_error=RuntimeError('页面已关闭')), browser_overrides={'open_page': fail})
    assert world.service.ensure_publish_session(lambda *a: None) == (None, '浏览器恢复失败：重开失败')


def test_session_login_timeout_message_carries_the_limit(tmp_path):
    world = session_world(tmp_path, page=FakePage(), behaviors={'wait_login_complete': False})
    main_tab, error = world.service.ensure_publish_session(lambda *a: None)
    assert main_tab is None and '等待登录超时（3 秒内未检测到已登录的抖店页面）' in error


def test_session_navigation_is_retried_once_then_reported(tmp_path):
    tab = FakeTab(fail_get=2)
    world = session_world(tmp_path, page=FakePage(tab))
    assert world.service.ensure_publish_session(lambda *a: None) == (None, '打开发布页面失败：导航失败1')
    assert len(tab.gets) == 2 and world.count('dismiss_pending_browser_alert') == 2
    tab = FakeTab(fail_get=1)
    world = session_world(tmp_path, page=FakePage(tab))
    assert world.service.ensure_publish_session(lambda *a: None)[1] is None


# ============================================================================================ DOM 流水线
def test_dom_flow_runs_every_stage_for_every_record_in_order(world):
    result, tab = flow(world)
    assert result['success'] is True
    assert world.stages() == FLOW_STAGES * 2
    assert world.count('reset_category_expanded_state') == 2 and world.count('timer_start_session') == 2
    assert world.count('timer_end_session') == 2
    assert [call[-1] for call in world.calls if call[0] == 'submit_publish'] == [('record', 1), ('record', 2)]


def test_dom_flow_message_names_each_record(world):
    result, _ = flow(world)
    assert result['msg'] == '商品一 -> 操作成功！\n商品二 -> 操作成功！'
    assert result['data'] is None


def test_dom_flow_passes_each_stage_the_right_arguments(world):
    flow(world, record_id=1)
    by_name = {call[0]: call for call in world.calls}
    assets = DEFAULT_ASSETS
    assert by_name['upload_main_images'][-1] == assets['main_pic_list']
    assert by_name['select_category_and_prepare_attributes'][-1] == assets['diaopai_pic']
    assert by_name['upload_media_assets'][2:] == (assets['sub_pic_list'], assets['my_video'], assets['white_pic'], assets['detail_pic_list'])
    assert by_name['configure_sku_entries'][2:] == (assets['sku_list'], '备注', ('record', 1))
    assert by_name['fill_price_stock_and_delivery'][-2:] == (assets['sku_list'], '中通包邮')
    assert by_name['fill_category_attributes'][3:] == ([('棉', '75'), ('氨纶', '25')], assets['diaopai_pic'], '')


def test_dom_flow_uses_this_products_material_not_the_global_default(tmp_path):
    product = make_record(1, title='秋冬中筒袜', remark='材质：桑蚕丝6.4%;羊毛93.6%')
    world = World(tmp_path, records=[product])
    result, _tab = flow(world, record_id=1)
    assert result['success'] is True
    by_name = {call[0]: call for call in world.calls}
    assert by_name['fill_category_attributes'][3] == [('桑蚕丝', '6.4'), ('羊毛', '93.6')]


def test_incomplete_material_blocks_every_record_before_opening_a_browser(tmp_path):
    records = [make_record(1), make_record(2, remark='材质：羊毛6.4%')]
    world = World(tmp_path, records=records)
    world.service.ensure_publish_session = Mock(return_value=(FakeTab(), None))
    result = world.service.execute_upload_flow()
    assert result['success'] is False and '材质成分不完整' in result['msg']
    world.service.ensure_publish_session.assert_not_called()
    assert world.stages() == []


def test_stop_before_submit_never_submits_and_says_so(world):
    result, _ = flow(world, record_id=1, stop_before_submit=True)
    assert result['success'] is True and '商品一 -> 操作成功（已截停未发布）！' in result['msg']
    assert 'submit_publish' not in world.names()
    assert ('timer_record', '提交阶段', '提交前截停', 0, 0, True) in world.calls


def test_failing_stage_is_reported_diagnosed_and_does_not_stop_the_batch(world):
    world.behaviors['fill_title_for_record'] = lambda tab, record: (_ for _ in ()).throw(ValueError('标题炸了')) if record.id == 1 else None
    result, _ = flow(world)
    assert result['success'] is False
    assert result['msg'] == '商品一 -> 操作失败[标题炸了]！\n商品二 -> 操作成功！'
    stage, message, detail, extra = world.automation_errors[0]
    assert (stage, message) == ('fill_title', '标题炸了') and 'ValueError' in detail
    assert extra['extra']['record_id'] == 1 and extra['extra']['record_name'] == '白袜_货号_x_商品一'
    assert extra['extra']['stage_timings'][-1]['status'] == 'failed'
    # 失败的记录后面的阶段不再执行，但收尾（耗时汇总、记录间停顿）照常做
    first_record = world.names()[:world.names().index('settle_between_records') + 1]
    assert 'upload_main_images' not in first_record and 'settle_between_records' in first_record


def test_asset_problems_fail_that_record_before_touching_the_page(world):
    world.behaviors['prepare_record_assets'] = lambda record: (None, '标题为空！！！') if record.id == 1 else (dict(DEFAULT_ASSETS), '')
    result, _ = flow(world)
    assert result['msg'] == '商品一 -> 操作失败[标题为空！！！]！\n商品二 -> 操作成功！'
    assert world.count('open_publish_page') == 1 and world.automation_errors == []


def test_page_not_ready_aborts_the_whole_batch(world):
    world.behaviors['open_publish_page'] = False
    result, _ = flow(world)
    assert result == {'success': False, 'msg': '页面未就绪，请稍后重试', 'data': None}
    assert world.count('prepare_record_assets') == 1                  # 第二条记录根本没开始
    assert world.count('settle_between_records') == 1                 # 但这一条的收尾做了


def test_a_task_cancelled_before_a_record_stops_the_flow(world):
    world.service.tasks['t1'] = {'task_id': 't1', 'cancelled': True, 'status': 'running'}
    result, _ = flow(world, task_id='t1')
    assert result == {'success': True, 'msg': '任务已取消', 'data': None}
    assert world.stages() == []
    assert world.service.tasks['t1']['status'] == 'cancelled' and world.service.tasks['t1']['finished_at']


def test_cancel_between_records_stops_after_the_current_one(world):
    world.service.tasks['t1'] = {'task_id': 't1', 'cancelled': False, 'status': 'running'}
    world.behaviors['settle_between_records'] = lambda tab: world.service.tasks['t1'].__setitem__('cancelled', True)
    result, _ = flow(world, task_id='t1')
    assert result['msg'] == '任务已取消' and world.count('prepare_record_assets') == 1


def test_unknown_task_id_is_not_a_cancel(world):
    result, _ = flow(world, task_id='nope')
    assert result['success'] is True and world.count('prepare_record_assets') == 2


def test_session_failure_is_returned_as_is(world):
    world.service.ensure_publish_session = lambda report: (None, '浏览器启动失败：x')
    assert world.service.execute_upload_flow() == {'success': False, 'msg': '浏览器启动失败：x', 'data': None}
    assert world.stages() == []


def test_load_failure_is_returned_before_any_browser_work(tmp_path):
    world = World(tmp_path)
    world.service.ensure_publish_session = lambda report: pytest.fail('不该建立会话')
    assert world.service.execute_upload_flow() == {'success': False, 'msg': '没有待上传数据！', 'data': None}


def test_official_publish_mode_is_not_implemented(tmp_path):
    world = World(tmp_path, records=RECORDS, automation={'publish_mode': 'official'})
    result = world.service.execute_upload_flow()
    assert result['success'] is False and '官方API模式尚未实现' in result['msg']


def test_unexpected_errors_become_a_generic_failure_message(tmp_path, capsys):
    world = World(tmp_path, records=RECORDS)
    world.settings.get_settings = Mock(side_effect=RuntimeError('设置炸了'))
    result = world.service.execute_upload_flow()
    assert result['success'] is False and '发生了一个意外的错误，请检查控制台日志。' in result['msg']
    assert '设置炸了' in capsys.readouterr().out


def test_progress_callback_gets_the_milestones_and_its_errors_are_swallowed(world):
    seen = []

    def callback(progress, message):
        seen.append(progress)
        raise RuntimeError('界面断了')
    flow(world, record_id=1, progress_callback=callback)
    assert seen[:4] == [12, 15, 16, 32]                              # 读取任务 / 会话就绪 / 开始处理 / 上传主图
    assert seen[-1] == 98


def test_protocol_mode_is_delegated_to_the_protocol_flow(tmp_path):
    world = World(tmp_path, records=RECORDS, automation={'publish_mode': 'protocol'})
    world.service._execute_protocol_flow = Mock(return_value={'success': True, 'msg': '协议跑完', 'data': {'results': []}})
    result = world.service.execute_upload_flow(record_id=1, progress_callback=print, task_id='t9', stop_before_submit=True)
    assert result['msg'] == '协议跑完'
    world.service._execute_protocol_flow.assert_called_once_with(
        record_id=1, progress_callback=print, task_id='t9', stop_before_submit=True,
        record_materials={1: [('棉', '75'), ('氨纶', '25')]})
    assert any(p.endswith('protocol-research') for p in sys.path[:3])    # 协议模块的位置被放到了 sys.path 最前面
    assert world.names() == []                                           # DOM 路线的任何步骤都没碰


# ============================================================================================ 后台 worker
def worker_world(tmp_path, **kwargs):
    world = World(tmp_path, records=RECORDS, **kwargs)
    world.service.tasks['t1'] = {'task_id': 't1', 'status': 'pending', 'progress': 0, 'cancelled': False}
    return world


def task_of(world, task_id='t1'):
    return world.service.tasks[task_id]


def test_worker_success_marks_the_task_done(tmp_path):
    world = worker_world(tmp_path)
    world.service.execute_upload_flow = Mock(return_value={'success': True, 'msg': '全部完成'})
    world.service.run_upload_task('t1', 1, True)
    task = task_of(world)
    assert (task['status'], task['progress'], task['message'], task['error']) == ('success', 100, '全部完成', None)
    assert task['started_at'] and task['finished_at']
    kwargs = world.service.execute_upload_flow.call_args.kwargs
    assert (kwargs['record_id'], kwargs['stop_before_submit'], kwargs['task_id']) == (1, True, 't1')


def test_worker_success_without_a_message_says_done(tmp_path):
    world = worker_world(tmp_path)
    world.service.execute_upload_flow = Mock(return_value={'success': True})
    world.service.run_upload_task('t1')
    assert task_of(world)['message'] == '上传完成'


def test_worker_failure_keeps_the_reason_and_the_browser_diagnosis(tmp_path):
    world = worker_world(tmp_path)
    world.service.execute_upload_flow = Mock(return_value={'success': False, 'msg': '商品一 -> 操作失败[x]！'})
    world.service.run_upload_task('t1')
    task = task_of(world)
    assert (task['status'], task['progress'], task['message'], task['error']) == ('failed', 100, '上传失败', '商品一 -> 操作失败[x]！')
    assert task['debug_report'] == world.latest_error


def test_worker_failure_without_a_reason(tmp_path):
    world = worker_world(tmp_path)
    world.service.execute_upload_flow = Mock(return_value={'success': False})
    world.service.run_upload_task('t1')
    assert task_of(world)['error'] == '上传失败（未知原因）'


def test_worker_exception_fails_the_task(tmp_path, capsys):
    world = worker_world(tmp_path)
    world.service.execute_upload_flow = Mock(side_effect=RuntimeError('流水线炸了'))
    world.service.run_upload_task('t1')
    task = task_of(world)
    assert (task['status'], task['message'], task['error']) == ('failed', '上传失败', '流水线炸了')
    assert task['debug_report'] == world.latest_error and task['finished_at']


def test_worker_cancelled_before_start_never_runs_the_flow(tmp_path):
    world = worker_world(tmp_path)
    task_of(world)['cancelled'] = True
    world.service.execute_upload_flow = Mock()
    world.service.run_upload_task('t1')
    assert task_of(world)['status'] == 'cancelled' and task_of(world)['message'] == '任务已被用户取消'
    world.service.execute_upload_flow.assert_not_called()


def test_worker_cancel_during_the_run_wins_over_the_result(tmp_path):
    world = worker_world(tmp_path)

    def flow_result(**_kwargs):
        task_of(world)['cancelled'] = True
        return {'success': True, 'msg': '跑完了'}
    world.service.execute_upload_flow = flow_result
    world.service.run_upload_task('t1')
    task = task_of(world)
    assert (task['status'], task['message'], task['progress']) == ('cancelled', '任务已被用户取消', 100)


def test_worker_with_an_unknown_task_does_nothing(tmp_path):
    world = worker_world(tmp_path)
    world.service.execute_upload_flow = Mock()
    world.service.run_upload_task('missing')
    world.service.execute_upload_flow.assert_not_called()


def test_worker_task_removed_midway_is_not_resurrected(tmp_path):
    world = worker_world(tmp_path)
    world.service.execute_upload_flow = lambda **_k: (world.service.tasks.clear(), {'success': True})[1]
    world.service.run_upload_task('t1')
    assert world.service.tasks == {}


def test_worker_progress_callback_is_clamped_and_ignores_cancelled_tasks(tmp_path):
    world = worker_world(tmp_path)
    captured = {}

    def flow_result(**kwargs):
        captured['callback'] = kwargs['progress_callback']
        return {'success': True}
    world.service.execute_upload_flow = flow_result
    world.service.run_upload_task('t1')
    callback = captured['callback']
    task = task_of(world)
    task['status'] = 'running'
    callback(150, '快好了')
    assert (task['progress'], task['message']) == (99, '快好了')
    callback(-5, '')
    assert (task['progress'], task['message']) == (0, '快好了')       # 空消息不覆盖
    task['cancelled'] = True
    callback(50, '不该写进去')
    assert (task['progress'], task['message']) == (0, '快好了')


def test_worker_writes_a_diagnostic_line_next_to_the_entry_file(tmp_path):
    world = worker_world(tmp_path)
    world.service.execute_upload_flow = Mock(return_value={'success': True})
    world.service.run_upload_task('t1', 7)
    log = (tmp_path / 'run_task_diag.log').read_text(encoding='utf-8')
    assert 'publish_mode=dom record_id=7 task_id=t1' in log


def test_worker_in_protocol_mode_reports_the_protocol_results(tmp_path):
    world = worker_world(tmp_path, automation={'publish_mode': 'protocol'})
    results = [{'record': '商品一', 'status': 'ok'}]
    seen = {}

    def protocol(**kwargs):
        seen.update(kwargs)
        kwargs['progress_callback'](150, '协议进行中', 'step-x', [{'name': 's'}])
        return {'success': True, 'msg': '发布完成', 'data': {'results': results}}
    world.service._execute_protocol_flow = protocol
    world.service.execute_upload_flow = Mock()
    world.service.run_upload_task('t1', None, True)
    task = task_of(world)
    assert (task['status'], task['progress'], task['message'], task['current_step']) == ('success', 100, '发布完成', '完成')
    assert task['debug_report'] == results and task['error'] is None
    assert seen['stop_before_submit'] is True and seen['task_id'] == 't1'
    world.service.execute_upload_flow.assert_not_called()


def test_worker_in_protocol_mode_failure(tmp_path):
    world = worker_world(tmp_path, automation={'publish_mode': 'protocol'})
    world.service._execute_protocol_flow = Mock(return_value={'success': False, 'msg': '', 'data': None})
    world.service.run_upload_task('t1')
    task = task_of(world)
    assert (task['status'], task['error'], task['debug_report']) == ('failed', '协议模式失败', None)


# ============================================================================================ 找已有的抖店浏览器
def finder_world(tmp_path, browsers, targets_by_address, profile_text=None, fetch=None):
    def discover(**_kwargs):
        if isinstance(browsers, Exception):
            raise browsers
        return browsers
    world = World(tmp_path, browser_overrides={
        'discover_debuggable_browsers': discover,
        'fetch_cdp_page_targets': fetch or (lambda address: targets_by_address[address]),
    })
    world.service._shop_session = SimpleNamespace(
        filter_browsers_for_profile=lambda found, profile: found,
        browser_profile_text=lambda browser: (profile_text or {}).get(browser['debug_address'], ''),
    )
    return world


FXG_TAB = [{'url': 'https://fxg.jinritemai.com/ffa/g/create'}]


def test_finder_prefers_the_active_shops_browser(tmp_path):
    world = finder_world(tmp_path, [{'debug_address': '127.0.0.1:9501'}, {'debug_address': '127.0.0.1:9502'}],
                         {'127.0.0.1:9501': FXG_TAB, '127.0.0.1:9502': FXG_TAB},
                         profile_text={'127.0.0.1:9502': 'chrome-profile-shop-a'})
    assert world.service._find_cdp_port_with_jinritemai() == 9502


def test_finder_skips_browsers_without_a_douyin_tab(tmp_path):
    world = finder_world(tmp_path, [{'debug_address': '127.0.0.1:9501'}, {'debug_address': '127.0.0.1:9502'}],
                         {'127.0.0.1:9501': [{'url': 'https://example.com'}], '127.0.0.1:9502': FXG_TAB})
    assert world.service._find_cdp_port_with_jinritemai() == 9502


def test_finder_ignores_a_browser_whose_targets_cannot_be_read(tmp_path, monkeypatch):
    def broken(address):
        raise OSError('连不上')
    world = finder_world(tmp_path, [{'debug_address': '127.0.0.1:9501'}], {}, fetch=broken)
    monkeypatch.setattr('urllib.request.urlopen', lambda url, timeout=None: (_ for _ in ()).throw(OSError('拒绝连接')))
    assert world.service._find_cdp_port_with_jinritemai() is None


def test_finder_falls_back_to_the_two_historic_default_ports(tmp_path, monkeypatch):
    world = finder_world(tmp_path, RuntimeError('枚举失败'), {})
    asked = []

    class Response:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

    def fake_urlopen(url, timeout=None):
        asked.append(url)
        if ':9223/' in url:
            return Response(json.dumps(FXG_TAB).encode('utf-8'))
        raise OSError('拒绝连接')
    monkeypatch.setattr('urllib.request.urlopen', fake_urlopen)
    assert world.service._find_cdp_port_with_jinritemai() == 9223
    assert asked == ['http://127.0.0.1:9222/json/list', 'http://127.0.0.1:9223/json/list']
    monkeypatch.setattr('urllib.request.urlopen', lambda url, timeout=None: (_ for _ in ()).throw(OSError('x')))
    assert world.service._find_cdp_port_with_jinritemai() is None


def test_ensure_protocol_browser_reuses_an_existing_douyin_browser(tmp_path):
    world = World(tmp_path)
    world.service._find_cdp_port_with_jinritemai = lambda: 9333
    assert world.service._ensure_protocol_browser() == (9333, None)


# ============================================================================================ 纯协议流水线
class FakeSocket:
    def __init__(self, cookies, href):
        self._messages = [json.dumps({'id': 2, 'result': {'cookies': cookies}}),
                          json.dumps({'id': 3, 'result': {'result': {'value': href}}})]
        self.sent = []

    def settimeout(self, _seconds):
        pass

    def send(self, payload):
        self.sent.append(json.loads(payload)['method'])

    def recv(self):
        return self._messages.pop(0)

    def close(self):
        pass


@pytest.fixture
def protocol_env(tmp_path, monkeypatch):
    """协议流水线的外部世界：CDP 的 /json/list、登录检测的 WebSocket、`fxg_protocol_v4.run`，以及图片文件。"""
    env = SimpleNamespace(href='https://fxg.jinritemai.com/ffa/g/create', cookie_count=3, run_calls=[], run_result={
        'success': True, 'data': {'product_id': 'P123456789012345678', 'path': '/p', 'stopped_before_submit': False}, 'steps': [1]})

    class Response:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

    monkeypatch.setattr('urllib.request.urlopen', lambda url, timeout=None: Response(json.dumps([{
        'type': 'page', 'url': 'https://fxg.jinritemai.com/home', 'webSocketDebuggerUrl': 'ws://x'}]).encode('utf-8')))
    websocket = SimpleNamespace(
        create_connection=lambda url, **k: FakeSocket([{'domain': '.jinritemai.com'}] * env.cookie_count, env.href),
        WebSocketTimeoutException=TimeoutError)
    monkeypatch.setitem(sys.modules, 'websocket', websocket)

    def run(**kwargs):
        env.run_calls.append(kwargs)
        return env.run_result
    monkeypatch.setitem(sys.modules, 'fxg_protocol_v4', SimpleNamespace(run=run))
    monkeypatch.setenv('CDP_PORT', '0')                          # 流水线登录成功后会写这个环境变量：teardown 时由 monkeypatch 还原
    monkeypatch.setattr(upload_service, 'system_time', SimpleNamespace(
        sleep=lambda s: None, time=__import__('time').time, perf_counter=__import__('time').perf_counter))
    image = tmp_path / 'main.jpg'
    image.write_bytes(b'x')
    env.image = str(image)
    return env


def protocol_world(tmp_path, protocol_env, records=None, main_images=True, **kwargs):
    world = World(tmp_path, records=[make_record(1)] if records is None else records, automation={'publish_mode': 'protocol', 'shipping_template': '顺丰'},
                  browser_overrides={'get_pic_list': lambda record, size: [protocol_env.image] if main_images and size == '800' else [],
                                     'get_detail_pic_list': lambda record: [protocol_env.image]}, **kwargs)
    world.service._ensure_protocol_browser = lambda: (9333, None)
    return world


def test_protocol_flow_stops_when_no_browser_can_be_started(tmp_path):
    world = World(tmp_path, records=RECORDS)
    world.service._ensure_protocol_browser = lambda: (None, None)
    result = world.service._execute_protocol_flow()
    assert result['success'] is False and '无法启动Chrome浏览器' in result['msg']


def test_protocol_flow_times_out_when_the_user_never_logs_in(tmp_path, protocol_env):
    protocol_env.cookie_count = 0
    world = protocol_world(tmp_path, protocol_env)
    reports = []
    result = world.service._execute_protocol_flow(progress_callback=lambda pct, msg: reports.append((pct, msg)))
    assert result['success'] is False and '登录超时' in result['msg']
    assert reports[0] == (5, '检测登录状态...') and len(reports) == 61           # 60 次轮询 + 起始提示
    assert protocol_env.run_calls == []


def test_protocol_flow_a_login_page_does_not_count_as_logged_in(tmp_path, protocol_env):
    protocol_env.href = 'https://fxg.jinritemai.com/login?x=1'
    world = protocol_world(tmp_path, protocol_env)
    assert '登录超时' in world.service._execute_protocol_flow()['msg']


def test_protocol_flow_publishes_with_the_translated_product(tmp_path, protocol_env):
    world = protocol_world(tmp_path, protocol_env, records=[make_record(1, clazz='1', repo='50', title='  标题  ')])
    world.service.tasks['t1'] = {'task_id': 't1', 'status': 'running', 'cancelled': False}
    result = world.service._execute_protocol_flow(record_id=1, task_id='t1', stop_before_submit=False)
    assert result['success'] is True and result['msg'] == '发布完成：1/1 个商品'
    assert result['data']['results'][0]['product_id'] == 'P123456789012345678'
    call = protocol_env.run_calls[0]
    assert call['category_leaf_id'] == 1000010266                      # clazz '1' -> 短袜
    assert call['product_data']['title'] == '标题' and call['product_data']['price'] == {'current': 9.9}
    assert call['product_data']['sku_info'] == [{'name': '白色', 'image_path': 'SKU/白.jpg', 'price': 9.9, 'stock': 50}]
    assert call['image_paths']['main_1x1'] == [protocol_env.image] and call['image_paths']['main_3x4'] == [protocol_env.image]
    assert call['shipping_template_name'] == '顺丰' and call['cdp_port'] == 9333 and call['stop_before_submit'] is False


def test_protocol_flow_stop_before_submit_message(tmp_path, protocol_env):
    protocol_env.run_result = {'success': True, 'data': {'product_id': 'P1', 'stopped_before_submit': True}, 'steps': []}
    world = protocol_world(tmp_path, protocol_env)
    result = world.service._execute_protocol_flow(stop_before_submit=True)
    assert result['msg'] == '协议预检完成：1/1 个商品已到提交前截停点'


def test_protocol_flow_failure_carries_the_platforms_reason(tmp_path, protocol_env):
    protocol_env.run_result = {'success': False, 'error': {'message': '类目不对', 'detail': '请重选'}, 'steps': []}
    world = protocol_world(tmp_path, protocol_env)
    result = world.service._execute_protocol_flow()
    assert result['success'] is False and result['msg'].startswith('发布失败：类目不对：请重选')
    assert result['data']['results'][0]['status'] == 'failed'


def test_protocol_flow_refuses_a_product_without_a_price_instead_of_inventing_one(tmp_path, protocol_env):
    world = protocol_world(tmp_path, protocol_env, records=[make_record(1, content='[{"name": "白色", "price": 0}]')])
    result = world.service._execute_protocol_flow()
    assert result['success'] is False and '未配置有效 SKU 价格' in result['msg']
    assert protocol_env.run_calls == []


def test_protocol_flow_needs_a_main_image(tmp_path, protocol_env):
    world = protocol_world(tmp_path, protocol_env, main_images=False)
    result = world.service._execute_protocol_flow()
    assert result['success'] is False and '未找到主图' in result['msg']


def test_protocol_flow_reports_a_missing_protocol_module(tmp_path, protocol_env, monkeypatch):
    monkeypatch.setitem(sys.modules, 'fxg_protocol_v4', None)             # import 会抛 ImportError
    world = protocol_world(tmp_path, protocol_env)
    result = world.service._execute_protocol_flow()
    assert result['success'] is False and '协议模块未找到' in result['msg']


def test_protocol_flow_a_crashing_run_fails_only_that_record(tmp_path, protocol_env):
    calls = []

    def run(**kwargs):
        calls.append(kwargs['product_data']['title'])
        if len(calls) == 1:
            raise RuntimeError('网络断了')
        return protocol_env.run_result
    sys.modules['fxg_protocol_v4'] = SimpleNamespace(run=run)
    world = protocol_world(tmp_path, protocol_env, records=[make_record(1, title='甲'), make_record(2, title='乙', name='白袜_货号_y_商品二')])
    result = world.service._execute_protocol_flow()
    assert result['success'] is True and result['msg'] == '发布完成：1/2 个商品'
    assert [r['status'] for r in result['data']['results']] == ['failed', 'ok']
    assert world.sleeps == [2]                                           # 两条之间停 2 秒（走注入的计时 sleep）


def test_protocol_flow_cancel_between_records(tmp_path, protocol_env):
    world = protocol_world(tmp_path, protocol_env, records=[make_record(1), make_record(2)])
    world.service.tasks['t1'] = {'task_id': 't1', 'status': 'running', 'cancelled': True}
    result = world.service._execute_protocol_flow(task_id='t1')
    assert result == {'success': True, 'msg': '任务已取消', 'data': None}
    assert world.service.tasks['t1']['status'] == 'cancelled' and protocol_env.run_calls == []


def test_protocol_flow_progress_steps_are_mirrored_into_the_task(tmp_path, protocol_env):
    def run(**kwargs):
        kwargs['progress_callback'](42, '正在传图', '上传图片', [{'name': 'a', 'status': 'ok', 'elapsed_ms': 12.7, 'summary': 3}])
        return protocol_env.run_result
    sys.modules['fxg_protocol_v4'] = SimpleNamespace(run=run)
    world = protocol_world(tmp_path, protocol_env)
    world.service.tasks['t1'] = {'task_id': 't1', 'status': 'running', 'cancelled': False}
    world.service._execute_protocol_flow(task_id='t1')
    task = world.service.tasks['t1']
    assert (task['current_step'], task['progress'], task['message']) == ('上传图片', 42, '正在传图')
    assert task['steps'] == [{'name': 'a', 'status': 'ok', 'elapsed_ms': 12, 'summary': '3'}]


def test_protocol_flow_closes_the_browser_it_started_itself(tmp_path, protocol_env):
    world = protocol_world(tmp_path, protocol_env)
    quits = []
    world.service._ensure_protocol_browser = lambda: (9333, SimpleNamespace(quit=lambda: quits.append(1)))
    world.service._execute_protocol_flow()
    assert quits == [1]


def test_protocol_flow_writes_its_diagnostics_next_to_the_entry_file(tmp_path, protocol_env):
    world = protocol_world(tmp_path, protocol_env)
    world.service._execute_protocol_flow(record_id=1)
    log = (tmp_path / 'protocol_diag.log').read_text(encoding='utf-8')
    assert 'START record_id=1' in log and 'protocol_run_v4 OK: pid=' in log


# ============================================================================================ 协议运行时配置探针
@pytest.fixture
def probe_env(tmp_path, monkeypatch):
    mcp = tmp_path / 'mcp'
    (mcp / 'scripts').mkdir(parents=True)
    (mcp / 'scripts' / 'probe-fxg-runtime-options.mjs').write_text('// probe', encoding='utf-8')
    monkeypatch.setenv('DOUYIN_MCP_SERVER_DIR', str(mcp))
    monkeypatch.setenv('NODE_BINARY', 'node-under-test')
    runs = []
    outcome = SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr='')
    monkeypatch.setattr(upload_service, 'subprocess', SimpleNamespace(
        run=lambda command, **kwargs: runs.append((command, kwargs)) or outcome))
    return SimpleNamespace(mcp=mcp, runs=runs, outcome=outcome)


def test_probe_runs_the_script_with_the_payload_in_its_environment(world, probe_env):
    result = world.service.run_fxg_runtime_options_probe({
        'categoryKeywords': ' 袜子 , 船袜,', 'category_id': 123, 'cdpListUrl': 'http://127.0.0.1:9333/json/list',
        'targetUrlContains': 'ffa', 'operation_type': 'edit', 'includeFreight': False, 'timeoutSeconds': 1000})
    assert result == {'ok': True}
    command, kwargs = probe_env.runs[0]
    assert command == ['node-under-test', str(probe_env.mcp / 'scripts' / 'probe-fxg-runtime-options.mjs')]
    env = kwargs['env']
    assert env['CATEGORY_KEYWORDS'] == '袜子,船袜' and env['CATEGORY_ID'] == '123' and env['INCLUDE_FREIGHT'] == '0'
    assert env['CDP_LIST_URL'] == 'http://127.0.0.1:9333/json/list' and env['TARGET_HINT'] == 'ffa' and env['OPERATION_TYPE'] == 'edit'
    assert kwargs['timeout'] == 180 and kwargs['cwd'] == str(probe_env.mcp)         # 超时上限 180 秒


def test_probe_requires_a_category(world, probe_env):
    with pytest.raises(ValueError, match='缺少类目关键词或类目 ID'):
        world.service.run_fxg_runtime_options_probe({})


def test_probe_reports_a_missing_script_and_a_missing_node(world, probe_env, monkeypatch):
    (probe_env.mcp / 'scripts' / 'probe-fxg-runtime-options.mjs').unlink()
    with pytest.raises(RuntimeError, match='未找到运行时配置探针脚本'):
        world.service.run_fxg_runtime_options_probe({'category_id': 1})
    (probe_env.mcp / 'scripts' / 'probe-fxg-runtime-options.mjs').write_text('//', encoding='utf-8')
    monkeypatch.delenv('NODE_BINARY')
    monkeypatch.setattr(upload_service, 'shutil', SimpleNamespace(which=lambda name: None))
    with pytest.raises(RuntimeError, match='未找到 node 可执行文件'):
        world.service.run_fxg_runtime_options_probe({'category_id': 1})


@pytest.mark.parametrize('outcome, message', [
    (SimpleNamespace(returncode=2, stdout='', stderr='脚本报错'), '运行时配置探针失败: 脚本报错'),
    (SimpleNamespace(returncode=2, stdout='out', stderr=''), '运行时配置探针失败: out'),
    (SimpleNamespace(returncode=3, stdout='', stderr=''), '运行时配置探针失败: 3'),
    (SimpleNamespace(returncode=0, stdout='  ', stderr=''), '运行时配置探针没有返回数据。'),
    (SimpleNamespace(returncode=0, stdout='not json', stderr=''), '运行时配置探针返回非 JSON 数据'),
])
def test_probe_failures_are_explained(world, probe_env, outcome, message):
    probe_env.outcome.returncode, probe_env.outcome.stdout, probe_env.outcome.stderr = outcome.returncode, outcome.stdout, outcome.stderr
    with pytest.raises(RuntimeError) as excinfo:
        world.service.run_fxg_runtime_options_probe({'category_keyword': '袜子'})
    assert message in str(excinfo.value)


def test_mcp_dir_resolution_order(world, tmp_path, monkeypatch):
    monkeypatch.setenv('DOUYIN_MCP_SERVER_DIR', str(tmp_path / 'explicit'))
    assert world.service._resolve_protocol_mcp_server_dir() == str(tmp_path / 'explicit')
    monkeypatch.delenv('DOUYIN_MCP_SERVER_DIR')
    # 入口文件在 <tmp>/app.py：源码形态的 mcp-server 在入口往上三级；都不存在时落到第一个候选
    first = tmp_path.parent.parent.parent / 'mcp-server'
    assert world.service._resolve_protocol_mcp_server_dir() == str(first)
    (tmp_path / 'mcp-server').mkdir()                                      # get_app_root() 返回 tmp_path：第二个候选存在
    assert world.service._resolve_protocol_mcp_server_dir() == str(tmp_path / 'mcp-server')


def test_category_keyword_normalization():
    normalize = upload_service._normalize_protocol_category_keywords
    assert normalize([' 袜子 ', '', '船袜', 3]) == ['袜子', '船袜', '3']
    assert normalize('袜子, 船袜 ,,') == ['袜子', '船袜']
    assert normalize(None) == [] and normalize(5) == []


# ============================================================================================ 服务对象本身
def test_every_service_gets_its_own_state():
    first, second = make_upload_service(), make_upload_service()
    first.tasks['x'] = {}
    assert second.tasks == {} and first.lock is not second.lock


def test_page_state_is_read_from_the_port_every_time(tmp_path):
    """GUI 兼容模式会把 ``gui`` 重绑成新对象：服务不能缓存页面状态，每次都问端口。"""
    holder = {'state': SimpleNamespace(page='first')}
    world = World(tmp_path, browser_overrides={'page_state': lambda: holder['state']})
    assert world.service.page_state().page == 'first'
    holder['state'] = SimpleNamespace(page='rebound')
    assert world.service.page_state().page == 'rebound'


def test_importing_the_service_and_routes_does_not_pull_in_the_browser_library():
    code = ('import sys; import src.sidecar.upload_service, src.sidecar.upload_routes; '
            'bad = [m for m in ("src.utils", "DrissionPage", "sidecar_app_under_test", "app") if m in sys.modules]; '
            'print("BAD=" + ",".join(bad))')
    done = subprocess.run([sys.executable, '-c', code], cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8', timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().endswith('BAD='), done.stdout


def test_all_step_names_used_by_the_helper_are_real_port_fields():
    from dataclasses import fields
    assert set(STEP_NAMES) <= {f.name for f in fields(upload_service.UploadStepsPort)}


# ============================================================================================ 补：覆盖报告里剩下的、值得守的分支
def test_session_recovers_by_reopening_the_browser_after_the_page_died(tmp_path):
    tab = FakeTab()
    pages = {'dead': FakePage(tab_error=RuntimeError('页面已关闭'))}
    world = session_world(tmp_path, page=pages['dead'],
                          browser_overrides={'open_page': lambda url, profile_name=None: FakePage(tab)})
    main_tab, error = world.service.ensure_publish_session(lambda *a: None)
    assert (main_tab, error) == (tab, None)
    assert world.state.page is not pages['dead'] and tab.gets == []        # 重新打开的浏览器已在发布页，不再导航


def test_ensure_protocol_browser_starts_a_new_browser_when_none_is_open(tmp_path, monkeypatch):
    import src.utils
    opened = []
    monkeypatch.setattr(src.utils, 'get_page', lambda url, profile_name=None: opened.append((url, profile_name)) or 'page')
    monkeypatch.setattr(upload_service, 'system_time', SimpleNamespace(sleep=lambda s: None))
    world = World(tmp_path, browser_overrides={'find_cdp_port': lambda: 9444})
    world.service._find_cdp_port_with_jinritemai = lambda: None
    assert world.service._ensure_protocol_browser() == (9444, 'page')
    assert opened == [('https://fxg.jinritemai.com', 'shop-a')]


def test_ensure_protocol_browser_gives_up_cleanly(tmp_path, monkeypatch, capsys):
    import src.utils

    def broken(url, profile_name=None):
        raise RuntimeError('chrome 起不来')
    monkeypatch.setattr(src.utils, 'get_page', broken)
    world = World(tmp_path)
    world.service._find_cdp_port_with_jinritemai = lambda: None
    assert world.service._ensure_protocol_browser() == (None, None)
    assert 'get_page() 启动失败: chrome 起不来' in capsys.readouterr().out
    monkeypatch.setattr(src.utils, 'get_page', lambda url, profile_name=None: 'page')
    monkeypatch.setattr(upload_service, 'system_time', SimpleNamespace(sleep=lambda s: None))
    assert world.service._ensure_protocol_browser() == (None, None)         # 启动了但找不到调试端口


def test_protocol_flow_in_a_packaged_app_reads_the_bundle_directory(tmp_path, protocol_env, monkeypatch):
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(bundle), raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'sidecar' / 'python-backend.exe'))
    (tmp_path / 'sidecar').mkdir()
    world = protocol_world(tmp_path, protocol_env)
    world.service._execute_protocol_flow(record_id=1)
    assert str(bundle / 'protocol-research-clean-20260505' / 'scripts') in sys.path[:3]
    assert (tmp_path / 'sidecar' / 'protocol_diag.log').is_file()             # 打包后诊断日志写在 exe 旁边


def test_protocol_flow_survives_image_lookups_that_fail_and_settings_that_cannot_be_read(tmp_path, protocol_env, capsys):
    def broken(*_args):
        raise OSError('目录没了')
    world = protocol_world(tmp_path, protocol_env)
    world.service._browser = world.service._browser.__class__(**dict(
        world.service._browser.__dict__, get_pic_list=lambda record, size: [protocol_env.image] if size == '800' else broken(),
        get_detail_pic_list=broken))
    world.settings.get_settings = Mock(side_effect=RuntimeError('设置读不了'))
    result = world.service._execute_protocol_flow(
        record_materials={1: [('桑蚕丝', '6.4'), ('羊毛', '93.6')]})
    out = capsys.readouterr().out
    assert result['success'] is True
    assert '获取750主图失败' in out and '获取详情图失败' in out
    call = protocol_env.run_calls[0]
    # 材质已在发布前审核；设置读取失败时只有运费留空，不重新用全局默认覆盖商品。
    assert call['product_data']['material'] == '桑蚕丝6.4%;羊毛93.6%'
    assert call['shipping_template_name'] == ''


def test_protocol_flow_sku_numbers_come_from_the_sku_then_the_product(tmp_path, protocol_env):
    content = json.dumps([{'name': 'A', 'price': 5, 'quantity': 3}, {'name': 'B', 'price': 'x', 'stock': 8},
                          {'name': 'C', 'price': 7, 'quantity': 'many'}])
    world = protocol_world(tmp_path, protocol_env, records=[make_record(1, content=content, repo='20')])
    world.service._execute_protocol_flow()
    skus = protocol_env.run_calls[0]['product_data']['sku_info']
    assert [(s['name'], s['price'], s['stock']) for s in skus] == [('A', 5.0, 3), ('B', 5.0, 8), ('C', 7.0, 0)]
    assert protocol_env.run_calls[0]['product_data']['price'] == {'current': 5.0}


def test_protocol_flow_collects_sku_images_that_exist(tmp_path, protocol_env):
    content = json.dumps([{'name': 'A', 'price': 5, 'path': protocol_env.image}, {'name': 'B', 'price': 6, 'path': str(tmp_path / 'missing.jpg')}])
    world = protocol_world(tmp_path, protocol_env, records=[make_record(1, content=content)])
    world.service._execute_protocol_flow()
    assert protocol_env.run_calls[0]['image_paths']['sku'] == [protocol_env.image]


def test_protocol_flow_reports_when_there_is_nothing_to_publish_or_load(tmp_path, protocol_env):
    world = protocol_world(tmp_path, protocol_env, records=[])
    result = world.service._execute_protocol_flow()
    assert result['success'] is False and result['msg'] == '没有待上传数据！'


def test_worker_diagnostic_log_failures_do_not_stop_the_task(tmp_path):
    world = worker_world(tmp_path)
    blocker = tmp_path / 'not-a-directory'
    blocker.write_text('x', encoding='utf-8')
    world.service._app_file = str(blocker / 'app.py')                          # 日志目录其实是个文件：写不进去
    world.service.execute_upload_flow = Mock(return_value={'success': True, 'msg': 'ok'})
    world.service.run_upload_task('t1')
    assert task_of(world)['status'] == 'success'


def test_protocol_progress_is_ignored_once_the_task_is_cancelled(tmp_path):
    world = worker_world(tmp_path, automation={'publish_mode': 'protocol'})

    def protocol(**kwargs):
        task_of(world)['cancelled'] = True
        kwargs['progress_callback'](50, '不该写进去', 'x', [])
        return {'success': True, 'msg': 'ok', 'data': {}}
    world.service._execute_protocol_flow = protocol
    world.service.run_upload_task('t1')
    task = task_of(world)
    assert task['progress'] == 100 and task['message'] == 'ok'                  # 以最终结果为准，取消后的中间进度没有写进去

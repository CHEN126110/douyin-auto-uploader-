# -*- coding: utf-8 -*-
"""Sidecar 入口冒烟：在子进程里真实导入 app.py（隔离数据目录），守三件事。

1. 能导入，且路由表与 tests/fixtures/sidecar_routes.txt 一致。新增 / 删除 / 改名路由时必须同步更新
   这份快照——它是前端、MCP 与本入口之间的 URL 契约，拆分 Blueprint 时靠它保证一条路由都不丢。
2. 函数里不引用模块没有定义的全局名。用 symtable 按编译器的作用域规则计算，不会把局部变量误报成全局。
3. 批量发布用到的 Record 辅助函数能真跑（它们曾因 `_json` 未定义，在第一条记录就抛 NameError）。
4. 账户门禁 / 调试浏览器 / 店铺会话三个服务在 app.py 里的接线：别名指向同一批对象、共用同一把账户锁、
   页面状态跟随 ``gui`` 被换掉（GUI 兼容模式会重绑它）、「有发布任务在跑」真的读到上传 / 淘宝任务字典。
   这部分是 Blueprint 单元测试够不着的（它们都用假端口），只有真实导入 app.py 才能验证。
5. 导入 / 小红书批量填表 / 链接采集 / 淘宝发布的装配：服务拿到的是 app.py 里真实的商品表、端口段、路径规则和日志；
   路由层用的是同一个服务；更新器的「有没有采集 / 淘宝任务在跑」读的是对应服务的锁和任务表；这些状态不再有模块级副本。
6. 上传域的页面操作（``src/sidecar/upload_steps.py``）：app.py 里同名的那批步骤函数 / 常量就是从那里导入的同一个对象（不是副本），
   进程级的交互恢复钩子注册的是那里的弹层清理函数。
7. 上传域的服务侧（``upload_service.py`` / ``upload_routes.py``）：服务拿到 app.py 里真实的商品表 / 账户门禁 / 设置 / 账户注册表 / 日志 / 路径，
   两个端口里的每个字段都是 app.py 里对应的那个对象（逐个核对，包括 ``steps`` 端口里的 14 个页面步骤），路由用的是同一个服务和同一道门，
   页面状态跟随 ``gui`` 被换掉，更新器 / 账户切换 / 保存商品读到的是 ``upload_service`` 的任务表，上传相关的旧别名和模块级状态都没有了。

子进程是为了不污染测试进程：导入 app.py 会初始化数据库、加载设置、写启动日志。
"""

from __future__ import annotations

import builtins
import json
import os
import subprocess
import sys
import symtable
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
APP_PATH = REPO / "tauri-app" / "python-sidecar" / "app.py"
ROUTE_SNAPSHOT = Path(__file__).with_name("fixtures") / "sidecar_routes.txt"

#: 子进程脚本：按 app.py 的真实路径加载（repo_root 等路径推导与线上一致），打印一行 JSON。
PROBE = r"""
import importlib.util, json, sys, types
from types import SimpleNamespace

repo, app_path = sys.argv[1], sys.argv[2]
sys.path[:0] = [repo, app_path.rsplit('\\', 1)[0].rsplit('/', 1)[0]]
spec = importlib.util.spec_from_file_location('sidecar_app_under_test', app_path)
module = importlib.util.module_from_spec(spec)
sys.modules['sidecar_app_under_test'] = module
spec.loader.exec_module(module)
from src.sidecar.taobao_helpers import _taobao_product_from_record

rules = sorted(
    (rule.rule, sorted(m for m in rule.methods if m not in ('HEAD', 'OPTIONS')))
    for rule in module.app.url_map.iter_rules()
)
routes = ['%s %s' % (','.join(methods), path) for path, methods in rules]

content = json.dumps([{'name': '白 / 均码', 'price': 8.9, 'path': ''}, {'name': '无价格', 'price': 0}],
                     ensure_ascii=False)


def closed_over(func, obj):
    # obj 是不是 func 闭包里捕获的变量之一（用来确认 Blueprint 工厂拿到的是 app.py 里那个真实对象）
    return any(cell.cell_contents is obj for cell in (func.__closure__ or ()))


def make_record(**overrides):
    fields = dict(id=1, name='测试商品', title='标题', clazz=2, repo=3, content=content, __data__={})
    fields.update(overrides)
    return SimpleNamespace(**fields)


def wiring_report():
    m = module
    guard, debug, shop = m.shop_accounts, m.browser_debug, m.shop_session_service
    report = {}
    report['account_lock_is_shared'] = m._shop_account_lock is guard.lock
    report['guard_aliases_are_bound_to_the_guard'] = (
        m._active_shop_profile == guard.active_profile and m._active_shop_account == guard.active_account
        and m._with_shop_account_lock == guard.with_lock
        and m._require_publish_platform == guard.require_publish_platform)
    # 淘宝是这几个别名的唯一使用者：搬走以后别名也一起删了，别让它们以「死代码」的形式留下
    report['aliases_only_taobao_used_are_gone'] = not any(
        hasattr(m, name) for name in ('_account_change_blocked', '_resolve_active_shop_browser', '_activate_shop_profile'))
    report['debug_aliases_are_bound_to_the_service'] = (
        m._get_current_browser_tab == debug.get_current_tab and m._snapshot_browser_context == debug.snapshot_context
        and m._set_browser_debug_instance == debug.set_browser_instance
        and m._find_debug_browser_process == debug.find_browser_process
        and m._get_gui_page_debug_address == debug.gui_page_debug_address)
    report['shop_port_reuses_the_debug_service'] = (
        shop._browser.gui_page_debug_address == debug.gui_page_debug_address
        and shop._browser.find_browser_process == debug.find_browser_process
        and shop._browser.set_debug_browser_instance == debug.set_browser_instance
        and shop._browser.find_reusable_browser is m._find_reusable_logged_in_fxg_browser
        and shop._browser.open_page is m.get_page)
    report['shop_service_uses_the_shared_guard'] = shop._accounts is guard
    report['ports_carry_the_apps_constants'] = (
        debug.browser.host == m._DEBUG_BROWSER_HOST and debug.browser.port_start == m._DEBUG_BROWSER_PORT_START
        and debug.browser.port_end == m._DEBUG_BROWSER_PORT_END
        and debug.browser.default_url == m._BROWSER_DEBUG_DEFAULT_URL == m._PUBLISH_CREATE_URL
        and shop._browser.host == m._DEBUG_BROWSER_HOST
        and shop._browser.shop_port_start == m._SHOP_BROWSER_PORT_START
        and shop._browser.shop_port_end == m._SHOP_BROWSER_PORT_END)
    report['debug_artifacts_root_comes_from_the_app'] = (
        debug._repo_root == m.repo_root and debug._get_app_root == m.get_app_root)
    report['blueprints_are_registered'] = {'shop', 'debug_browser', 'folder_import', 'xhs_batch', 'capture', 'taobao'} <= set(m.app.blueprints)

    # 链接采集：服务拿到 app.py 里真实的依赖（商品表 / 日志 / 协议引擎 / 共用函数 / 端口段）
    cap = m.capture_service
    report['capture_service_is_wired_to_the_apps_state'] = (
        cap._record_model is m.Record and cap.logger is m.app.logger
        and cap._protocol_capture_engine is m._PROTOCOL_CAPTURE_ENGINE
        and cap._find_cdp_port is m._find_cdp_port and cap._load_capture_attributes is m._load_capture_attributes
        and cap._normalize_save_path is m.normalize_save_path and cap._is_local_port_available is m._is_local_port_available
        and cap._normalize_debug_address is m._normalize_debug_address and cap._verify_debug_browser is m._verify_debug_browser
        and cap._discover_debuggable_browsers is m.discover_debuggable_browsers
        and cap._debug_host == m._DEBUG_BROWSER_HOST and cap._capture_port_start == m._CAPTURE_BROWSER_PORT_START
        and cap._capture_port_end == m._CAPTURE_BROWSER_PORT_END)
    # 路由层：同一个服务，路径规则 / 应用根目录 / 设置管理器也是 app.py 里的那几个
    start_view = m.app.view_functions['capture.start_capture']
    report['capture_routes_use_the_same_service_and_app_paths'] = (
        closed_over(start_view, cap) and closed_over(start_view, m.normalize_save_path)
        and closed_over(start_view, m.get_app_root) and closed_over(start_view, m.settings_manager))
    # 更新器的「有没有任务在跑」读的是采集服务的锁和任务 id
    before_flag = m._active_update_tasks()['capture']
    cap.running_task_id = 'probe-running'
    try:
        during_flag = m._active_update_tasks()['capture']
    finally:
        cap.running_task_id = None
    report['update_readiness_reads_the_capture_service'] = (before_flag, during_flag, m._active_update_tasks()['capture']) == (0, 1, 0)
    # 采集的进程级状态只存在于服务对象上（不要再往 app.py 加模块级字典）
    report['capture_state_has_no_module_level_copy'] = not any(
        hasattr(m, name) for name in ('capture_tasks', '_capture_lock', '_capture_running_task_id',
                                       '_mtop_product_cache', '_browser_cookie_str', '_browser_cookie_ts'))

    # 淘宝发布：服务拿到 app.py 里真实的商品表 / 账户门禁 / 店铺会话服务 / 路径解析 / 启动日志；
    # 路由层用的是同一个服务和同一把账户门禁；更新器与保存商品的编辑保护读的是它的任务表
    tb = m.taobao_service
    report['taobao_service_is_wired_to_the_apps_state'] = (
        tb._record_model is m.Record and tb._repo_root == m.repo_root and tb._accounts is guard and tb._shop_service is shop
        and tb._normalize_debug_address is m._normalize_debug_address and tb._resolve_data_file is m.resolve_data_file
        and tb._bootstrap_log is m._bootstrap_log)
    status_view = m.app.view_functions['taobao.taobao_publish_status']
    start_view = m.app.view_functions['taobao.taobao_publish_start']
    report['taobao_routes_use_the_same_service_and_guard'] = (
        closed_over(status_view, tb) and closed_over(start_view, guard)         # start 被账户锁装饰器包了一层：包装器闭包里是 guard
        and closed_over(start_view.__wrapped__, tb) and closed_over(start_view.__wrapped__, m._require_product_revision))
    flags = []
    for status in ('running', 'pending', 'succeeded'):
        tb.tasks['probe-task'] = {'status': status}
        try:
            flags.append(m._active_update_tasks()['taobao_publish'])
        finally:
            tb.tasks.pop('probe-task', None)
    report['update_readiness_reads_the_taobao_service'] = (flags, m._active_update_tasks()['taobao_publish']) == ([1, 1, 0], 0)
    # 淘宝的进程级状态只存在于服务对象上；两个纯常量搬进了 taobao_helpers
    report['taobao_state_has_no_module_level_copy'] = not any(
        hasattr(m, name) for name in ('_taobao_tasks', '_taobao_tasks_lock', 'TAOBAO_LISTING_MODES', '_CATEGORY_LABELS'))

    # 小红书批量填表：服务拿到 app.py 的真实商品表、账户浏览器端口段和 shop_session；
    # 路由层用的是同一把账户门禁；glue 函数（fill-only / status 用的端口）读的是同一个服务
    xhs = m.xhs_batch
    report['xhs_batch_service_is_wired_to_the_apps_state'] = (
        xhs._record_model is m.Record and xhs._shop_session is m.shop_session
        and xhs._host == m._DEBUG_BROWSER_HOST and xhs._port_start == m._SHOP_BROWSER_PORT_START
        and xhs._port_end == m._SHOP_BROWSER_PORT_END and xhs._get_pic_list is m.get_pic_list)
    # fill-only / status 两个接口的端口也来自这个服务（glue 函数在 app.py 里）
    import src.sidecar.xhs_routes as xhs_routes
    saved = (xhs_routes.default_runner, xhs_routes.default_status_probe, xhs.debug_port)
    try:
        xhs_routes.default_runner = lambda payload: dict(payload)
        xhs_routes.default_status_probe = lambda port=None: {'port': port}
        xhs.debug_port = lambda port=None: ('from-service', port)
        report['xhs_fill_only_and_status_ports_come_from_the_batch_service'] = (
            m._xhs_runner_with_account_port({'title': 'x', 'port': 5})['port'] == ('from-service', 5)
            and m._xhs_status_probe_with_account_port()['port'] == ('from-service', None))
    finally:
        xhs_routes.default_runner, xhs_routes.default_status_probe, xhs.debug_port = saved
    batch_view = m.app.view_functions['xhs_batch.xhs_fill_batch']
    report['xhs_batch_routes_share_the_account_guard_and_service'] = (
        closed_over(batch_view, m.shop_accounts) and closed_over(batch_view, xhs))

    # 本地文件夹导入：走 app.py 自己的装配（真实的 Record 和 src.utils.split_number_prefix），
    # 文件名 `1 蓝色-加厚.png` 只有在注入的是真函数时才会得到 `蓝色+加厚`
    import os
    folder = os.path.join(os.environ['DOUYIN_DATA_DIR'], 'wiring-import', '货号X')
    os.makedirs(os.path.join(folder, 'SKU'), exist_ok=True)
    open(os.path.join(folder, 'SKU', '1 蓝色-加厚.png'), 'wb').close()
    imported = m.app.test_client().post('/api/import/folders', json={'paths': [folder]}).get_json()
    row = m.Record.get_or_none(m.Record.path == os.path.abspath(folder))
    names = [s['name'] for s in json.loads(row.content)] if row else None
    report['import_route_uses_the_real_record_and_name_rules'] = bool(
        imported and imported['success'] and imported['data']['imported_count'] == 1 and names == ['蓝色+加厚'])
    if row:
        row.delete_instance()

    # 页面状态必须是 app.py 当前的 ``gui``：GUI 兼容模式会在启动后换掉这个对象
    original = m.gui
    report['page_state_is_the_current_gui'] = (
        debug.browser.page_state() is original and shop._browser.page_state() is original
        and m.upload_service.page_state() is original)
    try:
        m.gui = SimpleNamespace(page=None)
        report['page_state_follows_a_rebound_gui'] = (
            debug.browser.page_state() is m.gui and shop._browser.page_state() is m.gui
            and m.upload_service.page_state() is m.gui and debug.browser.page_state() is not original)
    finally:
        m.gui = original

    # 「有发布任务在跑」读的是 app.py 里真实的上传 / 淘宝任务字典
    outcomes = []
    registries = {'upload_service.tasks': lambda: m.upload_service.tasks, 'taobao_service.tasks': lambda: m.taobao_service.tasks}
    with m.app.test_request_context('/'):
        outcomes.append(guard.account_change_blocked() is None)
        for registry_name, status, blocked in (('upload_service.tasks', 'running', True), ('upload_service.tasks', 'pending', True),
                                              ('taobao_service.tasks', 'running', True), ('taobao_service.tasks', 'pending', True),
                                              ('upload_service.tasks', 'success', False), ('taobao_service.tasks', 'failed', False)):
            registry = registries[registry_name]()
            registry['probe-task'] = {'status': status}
            try:
                result = guard.account_change_blocked()
                outcomes.append((result is not None) == blocked and (result is None or result[1] == 409))
            finally:
                registry.pop('probe-task', None)
        outcomes.append(guard.account_change_blocked() is None)
    report['account_change_follows_the_real_task_dicts'] = all(outcomes)

    # 上传域的页面操作搬进了 upload_steps.py：app.py 里的同名只是从那里导入的同一个对象；
    # 交互恢复钩子是 src.utils 里的进程级单例，注册进去的必须是那里的弹层清理函数（钩子没注册上不会报错，只是弹层不再被自动清掉）。
    from src.sidecar import upload_steps as steps
    import src.utils as utils_module
    imported_steps = (
        '_PUBLISH_CREATE_URL', '_PUBLISH_LOGIN_WAIT_SECONDS', '_configure_sku_entries', '_configure_sku_structure',
        '_dismiss_interfering_overlays', '_dismiss_pending_browser_alert', '_fill_category_attributes',
        '_fill_price_stock_and_delivery', '_fill_title_for_record', '_open_publish_page', '_prepare_record_assets',
        '_select_category_and_prepare_attributes', '_settle_between_records', '_submit_publish', '_upload_main_images',
        '_upload_media_assets', '_wait_login_complete')
    report['upload_steps_are_imported_not_copied'] = all(getattr(m, n) is getattr(steps, n) for n in imported_steps)
    report['interaction_recovery_hook_is_the_overlay_dismisser'] = (
        utils_module._interaction_recovery_hook is steps._dismiss_interfering_overlays)

    # 上传域服务侧：服务拿到 app.py 里真实的状态与能力（不是副本、不是另一份）
    up = m.upload_service
    report['upload_service_is_wired_to_the_apps_state'] = (
        up._record_model is m.Record and up._accounts is guard and up._settings_manager is m.settings_manager
        and up._shop_session is m.shop_session and up.logger is m.app.logger and up._get_app_root is m.get_app_root
        and up._app_file == m.__file__ and up._repo_root == m.repo_root
        and up._stage_timing_log_path == m._UPLOAD_STAGE_TIMING_LOG_PATH)
    port = up._browser
    report['upload_browser_port_carries_the_apps_functions'] = (
        port.open_page is m.get_page and port.get_pic_list is m.get_pic_list and port.get_detail_pic_list is m.get_detail_pic_list
        and port.reset_category_expanded_state is m.reset_category_expanded_state
        and port.timer_start_session is m.timer_start_session and port.timer_end_session is m.timer_end_session
        and port.timer_record is m.timer_record and port.time is m.time
        and port.normalize_debug_address is m._normalize_debug_address
        and port.discover_debuggable_browsers is m.discover_debuggable_browsers
        and port.fetch_cdp_page_targets is m.fetch_cdp_page_targets
        and port.is_logged_in_fxg_target_url is m.is_logged_in_fxg_target_url
        and port.attach_reusable_browser is m._attach_reusable_logged_in_fxg_browser
        and port.find_cdp_port is m._find_cdp_port
        and port.record_automation_error == debug.record_automation_error
        and port.latest_error_after == debug.latest_error_after)
    step_fields = ('settle_between_records', 'wait_login_complete', 'prepare_record_assets', 'dismiss_pending_browser_alert',
                   'open_publish_page', 'fill_title_for_record', 'select_category_and_prepare_attributes', 'fill_category_attributes',
                   'upload_main_images', 'upload_media_assets', 'configure_sku_entries', 'configure_sku_structure',
                   'fill_price_stock_and_delivery', 'submit_publish')
    report['upload_steps_port_carries_the_steps'] = (
        all(getattr(up._steps, field) is getattr(steps, '_' + field) for field in step_fields)
        and up._steps.create_url == steps._PUBLISH_CREATE_URL and up._steps.login_wait_seconds == steps._PUBLISH_LOGIN_WAIT_SECONDS)
    start_view = m.app.view_functions['upload.upload_start']
    plain_view = m.app.view_functions['upload.upload_status']
    report['upload_routes_use_the_same_service_and_guard'] = (
        closed_over(plain_view, up) and closed_over(start_view, guard)           # start 被账户锁装饰器包了一层：包装器闭包里是 guard
        and closed_over(start_view.__wrapped__, up) and closed_over(start_view.__wrapped__, m.Record)
        and closed_over(start_view.__wrapped__, m._require_product_revision))
    # /start 与 /api/upload/*、协议运行时配置接口都在同一个蓝图里，URL 不变
    report['upload_blueprint_serves_the_same_urls'] = (
        'upload' in m.app.blueprints
        and {m.app.view_functions[name] is not None for name in ('upload.start', 'upload.protocol_fxg_runtime_options')} == {True})
    flags = []
    for status in ('running', 'pending', 'success'):
        up.tasks['probe-task'] = {'status': status}
        try:
            flags.append(m._active_update_tasks()['douyin_publish'])
        finally:
            up.tasks.pop('probe-task', None)
    report['update_readiness_reads_the_upload_service'] = (flags, m._active_update_tasks()['douyin_publish']) == ([1, 1, 0], 0)
    # 上传的进程级状态只存在于服务对象上；只给上传用的旧别名和搬走的函数在 app.py 里都没有了
    report['upload_state_has_no_module_level_copy'] = not any(hasattr(m, name) for name in (
        '_upload_tasks', '_upload_tasks_lock', '_record_browser_automation_error', '_latest_browser_debug_error_after',
        '_debug_bool', '_debug_int', '_run_upload_task', '_execute_upload_flow', '_execute_protocol_flow',
        '_ensure_publish_session', '_serialize_upload_task', '_load_upload_records', '_resolve_upload_stop_before_submit'))
    return report


print('PROBE_RESULT=' + json.dumps({
    'wiring': wiring_report(),
    'routes': routes,
    'taobao_product': _taobao_product_from_record(make_record()),
    'taobao_broken_content': _taobao_product_from_record(make_record(content='not json'))['skus'],
    'xhs_images': module.xhs_batch.images_from_record(make_record()),
    'xhs_images_broken_content': module.xhs_batch.images_from_record(make_record(content='not json')),
}, ensure_ascii=False))
"""


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("sidecar-data")
    env = dict(os.environ, SIDECAR_MODE="1", DOUYIN_DATA_DIR=str(data_dir), PYTHONUTF8="1",
               PYTHONIOENCODING="utf-8")
    done = subprocess.run(
        [sys.executable, "-c", PROBE, str(REPO), str(APP_PATH).replace("\\", "/")],
        capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(REPO), timeout=300,
    )
    assert done.returncode == 0, "导入 app.py 失败:\n" + done.stderr[-3000:]
    line = next(l for l in done.stdout.splitlines() if l.startswith("PROBE_RESULT="))
    return json.loads(line[len("PROBE_RESULT="):])


def test_route_table_matches_snapshot(probe):
    expected = ROUTE_SNAPSHOT.read_text(encoding="utf-8").splitlines()
    assert probe["routes"] == expected, (
        "路由表与 tests/fixtures/sidecar_routes.txt 不一致。"
        "如果是有意新增 / 调整接口，请同步更新快照、tauri-app/src/services/api.ts 与 mcp-server。"
    )


def test_batch_record_helpers_parse_sku_content(probe):
    product = probe["taobao_product"]
    assert product["title"] == "标题"
    assert product["category_keyword"] == "中筒袜"
    assert product["skus"] == [{"spec_values": {"颜色分类": "白 / 均码"}, "price": 8.9, "stock": 3}]
    # Record.content 不是合法 JSON 时按「没有 SKU」处理，而不是整个批量任务崩掉。
    assert probe["taobao_broken_content"] == []
    # 小红书：SKU 的 path 为空、目录里也没有图，所以是空列表；关键是不抛 NameError。
    assert probe["xhs_images"] == []
    assert probe["xhs_images_broken_content"] == []


def test_services_are_wired_to_the_shared_app_state(probe):
    broken = sorted(name for name, ok in probe["wiring"].items() if not ok)
    assert broken == [], "app.py 的装配接线有问题: %s" % broken
    assert len(probe["wiring"]) >= 24                                # 探针本身没有悄悄少测


MODULE_DUNDERS = {"__file__", "__name__", "__doc__", "__package__", "__spec__", "__loader__",
                  "__builtins__", "__path__", "__qualname__", "__class__"}


def _undefined_globals(path: Path):
    source = path.read_text(encoding="utf-8-sig")
    if any(line.strip().startswith("from ") and "import *" in line for line in source.splitlines()):
        return []  # 通配导入的名字静态算不出来
    top = symtable.symtable(source, str(path), "exec")
    defined = {s.get_name() for s in top.get_symbols()
               if s.is_assigned() or s.is_imported() or s.is_namespace()}
    found = []

    def walk(table, trail):
        for child in table.get_children():
            current = trail + [child.get_name()]
            for sym in child.get_symbols():
                name = sym.get_name()
                if (sym.is_referenced() and sym.is_global() and not sym.is_assigned()
                        and name not in defined and name not in MODULE_DUNDERS
                        and not hasattr(builtins, name)):
                    found.append("%s:%s %s 引用了未定义的全局名 %r"
                                 % (path.relative_to(REPO), child.get_lineno(), ".".join(current), name))
            walk(child, current)

    walk(top, [])
    return found


SCANNED = [APP_PATH] + sorted((REPO / "src").rglob("*.py"))


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: str(p.relative_to(REPO)))
def test_no_function_references_an_undefined_global(path):
    assert _undefined_globals(path) == []

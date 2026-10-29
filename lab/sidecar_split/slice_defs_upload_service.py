# -*- coding: utf-8 -*-
"""抖店上传（第二步：服务侧）的搬迁规格（2026-10-21）：两个切片，必须按 upload_service → upload_routes 链式运行，
并且要在第一步（slice_defs_upload.py 的 upload_steps，已安装）之后——输入是第一步完成后的 app.py。

  upload_service  ``UploadService``：任务字典 + 互斥锁（原来是 app.py 的 ``_upload_tasks`` / ``_upload_tasks_lock``），加上要用到它们、账户门禁或
                  浏览器会话的方法：发布浏览器会话、DOM 流水线、协议流水线、后台 worker、协议运行时配置探针、阶段耗时日志。
                  两个端口 dataclass（``UploadStepsPort`` 页面步骤、``UploadBrowserPort`` 来自 src.utils / app.py 的浏览器与 CDP 能力）是手写的。
  upload_routes   八个接口（7 条 /api/upload/* + /api/protocol/fxg/runtime-options）+ GUI 兼容的 /start + 任务 JSON 化的小函数。

留在 app.py、经注入传入的（别的域也在用）：
  get_app_root、_find_cdp_port（及它用的 _protocol_cdp_port_candidates，采集也在用）、_attach_reusable_logged_in_fxg_browser
  （同时接在运营闭环 / 店铺会话的端口上）、_require_product_revision（保存商品、淘宝也在用）、Record、settings_manager、shop_session、
  app.logger、app.py 自己的 __file__ / repo_root、阶段耗时日志的路径。

app.py 里读上传任务字典的三处（发布任务在跑检查、保存商品的编辑保护、更新器的任务计数）改为直接读 ``upload_service``；
随之无人使用的四个别名（``_record_browser_automation_error`` / ``_latest_browser_debug_error_after`` / ``_debug_bool`` / ``_debug_int``）一并删除。
"""
from slice_tool import Slice

SLICES = {}

# ------------------------------------------------------------------------------------------ 服务类
# 旧函数名 -> 方法名。路由要调用的是公开名；只在服务内部用的保持原名（带下划线）。
PUBLIC_METHODS = {
    '_ensure_publish_session': 'ensure_publish_session',
    '_execute_upload_flow': 'execute_upload_flow',
    '_resolve_upload_stop_before_submit': 'resolve_stop_before_submit',
    '_run_upload_task': 'run_upload_task',
    '_run_fxg_runtime_options_probe': 'run_fxg_runtime_options_probe',
}
PRIVATE_METHODS = [
    '_append_stage_timing_log', '_run_stage_with_timing', '_resolve_protocol_mcp_server_dir', '_load_upload_records',
    '_load_upload_runtime_config', '_find_cdp_port_with_jinritemai', '_ensure_protocol_browser', '_execute_protocol_flow',
]
SERVICE_FUNCS = list(PUBLIC_METHODS) + PRIVATE_METHODS

# 页面步骤端口：(端口字段, upload_steps.py 里的函数名)
STEP_FIELDS = [
    ('settle_between_records', '_settle_between_records'),
    ('wait_login_complete', '_wait_login_complete'),
    ('prepare_record_assets', '_prepare_record_assets'),
    ('dismiss_pending_browser_alert', '_dismiss_pending_browser_alert'),
    ('open_publish_page', '_open_publish_page'),
    ('fill_title_for_record', '_fill_title_for_record'),
    ('select_category_and_prepare_attributes', '_select_category_and_prepare_attributes'),
    ('fill_category_attributes', '_fill_category_attributes'),
    ('upload_main_images', '_upload_main_images'),
    ('upload_media_assets', '_upload_media_assets'),
    ('configure_sku_entries', '_configure_sku_entries'),
    ('configure_sku_structure', '_configure_sku_structure'),
    ('fill_price_stock_and_delivery', '_fill_price_stock_and_delivery'),
    ('submit_publish', '_submit_publish'),
]
# 页面步骤端口里的常量：(端口字段, 类型, app.py 里的名字)
STEP_CONSTS = [
    ('create_url', 'str', '_PUBLISH_CREATE_URL'),
    ('login_wait_seconds', 'float', '_PUBLISH_LOGIN_WAIT_SECONDS'),
]
# 浏览器端口：(端口字段, 类型, app.py 里的表达式)，表达式同时是 app.py 装配时传的实参、也是被替换的旧全局名（如果两者相同）
BROWSER_FIELDS = [
    ('page_state', 'Callable[[], Any]', 'lambda: gui', 'gui'),
    ('open_page', 'Callable[..., Any]', 'get_page', 'get_page'),
    ('get_pic_list', 'Callable[..., Any]', 'get_pic_list', 'get_pic_list'),
    ('get_detail_pic_list', 'Callable[..., Any]', 'get_detail_pic_list', 'get_detail_pic_list'),
    ('reset_category_expanded_state', 'Callable[[], None]', 'reset_category_expanded_state', 'reset_category_expanded_state'),
    ('timer_start_session', 'Callable[..., Any]', 'timer_start_session', 'timer_start_session'),
    ('timer_end_session', 'Callable[[], Any]', 'timer_end_session', 'timer_end_session'),
    ('timer_record', 'Callable[..., Any]', 'timer_record', 'timer_record'),
    ('time', 'Any', 'time', 'time'),
    ('normalize_debug_address', 'Callable[[str], str]', '_normalize_debug_address', '_normalize_debug_address'),
    ('discover_debuggable_browsers', 'Callable[..., Any]', 'discover_debuggable_browsers', 'discover_debuggable_browsers'),
    ('fetch_cdp_page_targets', 'Callable[..., Any]', 'fetch_cdp_page_targets', 'fetch_cdp_page_targets'),
    ('is_logged_in_fxg_target_url', 'Callable[[str], bool]', 'is_logged_in_fxg_target_url', 'is_logged_in_fxg_target_url'),
    ('attach_reusable_browser', 'Callable[..., Any]', '_attach_reusable_logged_in_fxg_browser', '_attach_reusable_logged_in_fxg_browser'),
    ('find_cdp_port', 'Callable[[], Any]', '_find_cdp_port', '_find_cdp_port'),
    ('record_automation_error', 'Callable[..., Any]', 'browser_debug.record_automation_error', '_record_browser_automation_error'),
    ('latest_error_after', 'Callable[..., Any]', 'browser_debug.latest_error_after', '_latest_browser_debug_error_after'),
]

STEPS_PORT_DOC = ('发布页的页面级操作（``upload_steps.py`` 里的函数），由应用入口一次性注入；流水线只通过它们碰页面。'
                  '``create_url`` / ``login_wait_seconds`` 是发布页地址和等待登录的上限（常量也在 ``upload_steps.py``）。')
BROWSER_PORT_DOC = ('流水线需要的浏览器与 CDP 能力，由应用入口一次性注入；本模块不导入 ``src.utils`` / DrissionPage。\n\n'
                    '    ``page_state`` 是无参函数，每次调用返回当前的共享页面状态（带 ``page`` 属性的对象），含义同 ``ShopBrowserPort.page_state``：\n'
                    '    必须每次取最新的 ``gui``，GUI 兼容模式启动后会把它重绑成 ``Gui`` 实例。``time`` 是 ``src.utils`` 里带计时的 sleep 提供者'
                    '（``time.sleep``），不是标准库的 ``time``。\n'
                    '    ``record_automation_error`` / ``latest_error_after`` 来自 ``BrowserDebugService``；``attach_reusable_browser`` / ``find_cdp_port`` '
                    '还接在运营闭环 / 采集的装配上，所以留在 app.py。')


def _port_class(name, doc, lines):
    body = '\n'.join('    %s' % line for line in lines)
    return '@dataclass(frozen=True)\nclass %s:\n    """%s"""\n\n%s\n' % (name, doc, body)


UPLOAD_PORT_PRELUDE = (
    _port_class('UploadStepsPort', STEPS_PORT_DOC,
                ['%s: Callable[..., Any]' % field for field, _ in STEP_FIELDS]
                + ['%s: %s' % (field, annotation) for field, annotation, _ in STEP_CONSTS])
    + '\n\n'
    + _port_class('UploadBrowserPort', BROWSER_PORT_DOC, ['%s: %s' % (field, annotation) for field, annotation, _, _ in BROWSER_FIELDS])
)

# 旧的全局名 -> 实例属性（服务类里）
SERVICE_INJECTED = {
    'Record': 'self._record_model',
    'settings_manager': 'self._settings_manager',
    'shop_session': 'self._shop_session',
    'repo_root': 'self._repo_root',
    '__file__': 'self._app_file',
    'get_app_root': 'self._get_app_root',
    '_active_shop_profile': 'self._accounts.active_profile',
    '_UPLOAD_STAGE_TIMING_LOG_PATH': 'self._stage_timing_log_path',
    'app': 'self',                                          # app.logger -> self.logger（后台线程里没有应用上下文，用注入的 logger）
}
SERVICE_STATE = [
    ('_upload_tasks', 'self.tasks'),
    ('_upload_tasks_lock', 'self.lock'),
]
# 页面步骤 / 浏览器能力：旧的全局名 -> 端口属性
STEP_MAP = {old: 'self._steps.' + field for field, old in STEP_FIELDS}
STEP_MAP.update({old: 'self._steps.' + field for field, _annotation, old in STEP_CONSTS})
BROWSER_MAP = {old: 'self._browser.' + field + ('()' if field == 'page_state' else '') for field, _a, _e, old in BROWSER_FIELDS}

_SERVICE_NAME_MAP = {old: 'self.' + new for old, new in PUBLIC_METHODS.items()}
_SERVICE_NAME_MAP.update({name: 'self.' + name for name in PRIVATE_METHODS})
_SERVICE_NAME_MAP.update(SERVICE_INJECTED)
_SERVICE_NAME_MAP.update(dict(SERVICE_STATE))
_SERVICE_NAME_MAP.update(STEP_MAP)
_SERVICE_NAME_MAP.update(BROWSER_MAP)
# `_debug_bool` / `_debug_int` 只是 app.py 里对 debug_browser_service 两个纯函数的别名：直接用原名（该模块不碰浏览器，可以安全导入）
_SERVICE_NAME_MAP.update({'_debug_bool': 'debug_bool', '_debug_int': 'debug_int'})

# 构造服务的装配代码（落在 app.py 里，手写，不参与 AST 重放；由冒烟测试的接线探针守着）
_BROWSER_ARGS = ',\n'.join('        %s=%s' % (field, expr) for field, _a, expr, _old in BROWSER_FIELDS)
_STEPS_ARGS = ',\n'.join(['        %s=%s' % (field, old) for field, old in STEP_FIELDS]
                         + ['        %s=%s' % (field, old) for field, _a, old in STEP_CONSTS])
CONSTRUCTION = (
    'upload_service = UploadService(\n'
    '    record_model=Record, accounts=shop_accounts, settings_manager=settings_manager, shop_session=shop_session,\n'
    '    logger=app.logger, get_app_root=get_app_root, app_file=__file__, repo_root=repo_root,\n'
    '    stage_timing_log_path=_UPLOAD_STAGE_TIMING_LOG_PATH,\n'
    '    browser=UploadBrowserPort(\n' + _BROWSER_ARGS + ',\n    ),\n'
    '    steps=UploadStepsPort(\n' + _STEPS_ARGS + ',\n    ),\n'
    ')'
)

SLICES['upload_service'] = Slice(
    key='upload_service',
    module_file='upload_service.py',
    doc=('抖店上传服务：任务字典与互斥锁、发布浏览器会话、DOM 流水线、纯协议流水线、后台 worker、协议运行时配置探针、阶段耗时日志。\n\n'
         '任务字典 ``tasks`` 和互斥锁 ``lock`` 原来是 ``app.py`` 的模块全局（``_upload_tasks`` / ``_upload_tasks_lock``），'
         '现在是 ``UploadService`` 实例的属性，由应用入口创建一次。\n\n'
         '页面级操作（清弹层、填标题、传图、配 SKU、填价格库存、提交……）不在这里，在 ``upload_steps.py``，经 ``UploadStepsPort`` 注入；'
         '``src.utils`` 里的浏览器工具、CDP 探测、图片列表、计时经 ``UploadBrowserPort`` 注入。'
         '这个模块不导入 ``src.utils`` / DrissionPage / ``app.py``，导入它不会初始化浏览器。\n\n'
         '与 app.py 旧名字的对应：\n'
         + '\n'.join('  %-38s -> %s' % (old, 'UploadService.' + new) for old, new in PUBLIC_METHODS.items())
         + '\n  ' + ' / '.join(PRIVATE_METHODS[:3]) + '\n  ' + ' / '.join(PRIVATE_METHODS[3:6]) + '\n  ' + ' / '.join(PRIVATE_METHODS[6:])
         + '  -> 同名的私有方法\n'
         '  _upload_tasks / _upload_tasks_lock     -> tasks / lock\n'
         '  _normalize_protocol_category_keywords  -> 本模块的同名模块级函数'),
    class_name='UploadService',
    class_doc=('一个应用一个实例，持有抖店上传任务的全部进程内状态。\n\n'
               '    ``record_model`` 是商品表；``accounts`` 是 ``ShopAccountGuard``（当前账户的 profile）；``browser`` / ``steps`` 是两个端口；\n'
               '    ``settings_manager`` / ``shop_session`` 是设置管理器和账户注册表模块（测试里换成假件）；\n'
               '    ``logger`` 是应用入口的 ``app.logger``——后台线程里没有 Flask 应用上下文，日志不能走 ``current_app``；\n'
               '    ``get_app_root`` 决定打包后的资源根目录（白底图 / 调试产物也在用），``app_file`` / ``repo_root`` 是 app.py 自己的文件路径和仓库根\n'
               '    （诊断日志、``sys.path`` 的推导依赖入口文件的位置，所以由入口传进来，不能在本模块里用 ``__file__``）；\n'
               '    ``stage_timing_log_path`` 是阶段耗时日志的路径。'),
    class_params=['record_model', 'accounts', 'browser', 'steps', 'settings_manager', 'shop_session', 'logger',
                  'get_app_root', 'app_file', 'repo_root', 'stage_timing_log_path'],
    wrap_init=True,
    init_lines=[
        'self._record_model = record_model',
        'self._accounts = accounts',
        'self._browser = browser',
        'self._steps = steps',
        'self._settings_manager = settings_manager',
        'self._shop_session = shop_session',
        'self.logger = logger',
        'self._get_app_root = get_app_root',
        'self._app_file = app_file',
        'self._repo_root = repo_root',
        'self._stage_timing_log_path = stage_timing_log_path',
    ],
    state_assigns=SERVICE_STATE,
    funcs=SERVICE_FUNCS,
    module_funcs=['_normalize_protocol_category_keywords'],
    prelude=UPLOAD_PORT_PRELUDE,
    manual_methods=(
        '    def page_state(self):\n'
        '        """当前共享的页面状态（带 ``page`` 属性的对象）；路由层要读 ``page`` 判断“有没有浏览器”。"""\n'
        '        return self._browser.page_state()\n'
    ),
    name_map=_SERVICE_NAME_MAP,
    per_func=dict(
        {old: {'new_name': new} for old, new in PUBLIC_METHODS.items()},
        # `_ensure_protocol_browser` 自己 ``from src.utils import get_page``（函数内的局部导入，原样保留），
        # 这里的 get_page 是那个局部名，不能被改成端口属性
        _ensure_protocol_browser={'name_map_exclude': ['get_page']},
    ),
    import_overrides={
        'dataclass': 'from dataclasses import dataclass',
        'Callable': 'from typing import Callable',
        'Any': 'from typing import Any',
    },
    app_import=('from src.sidecar.upload_service import UploadBrowserPort, UploadService, UploadStepsPort\n'
                'from src.sidecar.upload_routes import create_upload_blueprint'),
    insert_after=[('capture_service', CONSTRUCTION)],
    app_edits=[
        # 「有没有发布任务在跑」「编辑保护」「更新器的任务检查」：改为直接读 upload_service
        ("    with _upload_tasks_lock:\n"
         "        running = any(task.get('status') in ('pending', 'running') for task in _upload_tasks.values())\n",
         "    with upload_service.lock:\n"
         "        running = any(task.get('status') in ('pending', 'running') for task in upload_service.tasks.values())\n"),
        ('    for tasks, lock in ((_upload_tasks, _upload_tasks_lock), (taobao_service.tasks, taobao_service.lock)):\n',
         '    for tasks, lock in ((upload_service.tasks, upload_service.lock), (taobao_service.tasks, taobao_service.lock)):\n'),
        ("    with _upload_tasks_lock:\n"
         "        douyin = sum(t.get('status') in ('pending', 'running') for t in _upload_tasks.values())\n",
         "    with upload_service.lock:\n"
         "        douyin = sum(t.get('status') in ('pending', 'running') for t in upload_service.tasks.values())\n"),
        # 四个别名随上传一起变得无人使用：上传是它们的唯一使用者
        ('# 调试浏览器的状态与实现在 src/sidecar/debug_browser_service.py。上传 / 淘宝 / 采集等业务域还留在本文件，\n'
         '# 继续按原来的函数名使用；这些域拆出去时再改为直接依赖 browser_debug。\n',
         '# 调试浏览器的状态与实现在 src/sidecar/debug_browser_service.py。店铺会话 / 运营闭环的端口装配、\n'
         '# 以及 _attach_reusable_logged_in_fxg_browser 还在用下面这几个旧函数名；上传已直接依赖 browser_debug（经 UploadBrowserPort）。\n'),
        ('_record_browser_automation_error = browser_debug.record_automation_error\n', ''),
        ('_latest_browser_debug_error_after = browser_debug.latest_error_after\n', ''),
        ('_debug_bool = debug_bool\n_debug_int = debug_int\n', ''),
        ('# 账户门禁的实现在 src/sidecar/shop_accounts.py。上传 / 小红书 / 保存等业务域还留在本文件，\n',
         '# 账户门禁的实现在 src/sidecar/shop_accounts.py。小红书 / 保存等业务域和店铺会话的装配还留在本文件，\n'),
        # 工具的导入清理在 app_edits 之前做，且按名字判断“还在用”：`debug_bool` / `debug_int` 当时还被两个别名行用着，
        # `subprocess` 则被某个函数里的局部导入遮住了——这两处精确改一行（模块级那行，不会碰缩进的局部导入）
        ('from src.sidecar.debug_browser_service import (\n    BrowserDebugService,\n    DebugBrowserPort,\n    debug_bool,\n    debug_int,\n)\n',
         'from src.sidecar.debug_browser_service import BrowserDebugService, DebugBrowserPort\n'),
        ('import socket\nimport subprocess\nimport tempfile\n', 'import socket\nimport tempfile\n'),
    ],
)

# ------------------------------------------------------------------------------------------ 路由
_ROUTES_NAME_MAP = {
    '_upload_tasks': 'service.tasks',
    '_upload_tasks_lock': 'service.lock',
    '_run_upload_task': 'service.run_upload_task',
    '_ensure_publish_session': 'service.ensure_publish_session',
    '_execute_upload_flow': 'service.execute_upload_flow',
    '_resolve_upload_stop_before_submit': 'service.resolve_stop_before_submit',
    '_run_fxg_runtime_options_probe': 'service.run_fxg_runtime_options_probe',
    'gui': 'service.page_state()',
    '_active_shop_account': 'accounts.active_account',
    '_require_publish_platform': 'accounts.require_publish_platform',
    '_require_product_revision': 'require_product_revision',
}

SLICES['upload_routes'] = Slice(
    key='upload_routes',
    module_file='upload_routes.py',
    doc=('抖店上传接口：/api/upload/{start,ensure-session,status,cancel,debug/injection,start-all,tasks}、'
         '/api/protocol/fxg/runtime-options，以及 GUI 兼容模式的 /start。\n\n'
         '这些接口只做 HTTP 适配和请求校验；任务字典、互斥锁、发布浏览器会话、流水线和 worker 在 ``UploadService``，'
         '账户门禁在 ``ShopAccountGuard``，页面级操作在 ``upload_steps``。\n\n'
         '与 app.py 旧名字的对应：\n'
         '  _with_shop_account_lock / _require_publish_platform / _active_shop_account\n'
         '                                  -> accounts.with_lock / require_publish_platform / active_account\n'
         '  _upload_tasks / _upload_tasks_lock -> service.tasks / service.lock\n'
         '  gui.page（有没有浏览器）          -> service.page_state().page\n'
         '  _require_product_revision        -> 工厂参数 require_product_revision（保存商品、淘宝也在用，留在应用入口）\n'
         '  _serialize_upload_task           -> 本模块的同名模块级函数（任务的 JSON 形态属于 HTTP 层）'),
    factory='create_upload_blueprint',
    blueprint_name='upload',
    params=['service', 'accounts', 'record_model', 'require_product_revision'],
    aliases=['Record = record_model'],
    factory_doc=('``service`` 是 ``UploadService``（任务状态、发布浏览器会话、流水线、worker）；``accounts`` 是 ``ShopAccountGuard``'
                 '（账户锁与平台门禁）；\n'
                 '    ``record_model`` 是商品表；``require_product_revision`` 校验界面带来的商品资料版本（保存商品、淘宝也在用，所以留在应用入口）。'),
    funcs=['protocol_fxg_runtime_options', 'start', 'upload_start', 'upload_ensure_session', 'upload_status', 'upload_cancel',
           'upload_debug_injection', 'upload_start_all', 'upload_tasks'],
    module_funcs=['_serialize_upload_task'],
    name_map=_ROUTES_NAME_MAP,
    decorator_name_map={'app': 'routes', '_with_shop_account_lock': 'accounts.with_lock'},
    registration=('app.register_blueprint(create_upload_blueprint(\n'
                  '    service=upload_service, accounts=shop_accounts, record_model=Record,\n'
                  '    require_product_revision=_require_product_revision,\n'
                  '))\n'),
)

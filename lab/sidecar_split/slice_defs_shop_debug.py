# -*- coding: utf-8 -*-
"""店铺会话（/api/shop/*）与 CDP 调试浏览器（/api/debug/*）的搬迁规格（2026-10-19）。

五个切片必须按 accounts -> debug_service -> debug_routes -> shop_service -> shop_routes 的顺序链式运行：
后一个切片的输入是前一个切片生成的 app.py。改写表里出现的新名字（self.* / accounts.* / service.*）是声明过的、
会被 verify() 在原 AST 上重放的改写；除此之外函数体逐字不变。手写的部分（端口 dataclass、__init__、
account_change_blocked、_publish_tasks_running）不参与 AST 重放，由测试守护，见各处注释。
"""
from slice_tool import Slice

SLICES = {}

# ------------------------------------------------------------------------------------------ 1. 账户门禁
SLICES['accounts'] = Slice(
    key='accounts',
    module_file='shop_accounts.py',
    doc=('账户门禁：当前账户及其绑定平台、账户锁，以及发布入口与账户切换之间的互斥检查。\n\n'
         '登录态全部寄生在 Chrome 用户数据目录里，应用只在本地注册表（``shop_session``）里记「当前账户」和它绑定的平台。\n'
         '上传 / 淘宝 / 小红书 / 保存等入口都要先过这里的门：平台对得上、账户没被换掉，才允许继续；\n'
         '账户切换与这些入口共用同一把锁，避免「校验通过之后账户被另一个请求换成别的」。\n\n'
         '与 app.py 旧函数名的对应：\n'
         '  _shop_account_lock        -> ShopAccountGuard.lock\n'
         '  _active_shop_profile      -> ShopAccountGuard.active_profile\n'
         '  _active_shop_account      -> ShopAccountGuard.active_account\n'
         '  _with_shop_account_lock   -> ShopAccountGuard.with_lock（装饰器）\n'
         '  _require_publish_platform -> ShopAccountGuard.require_publish_platform\n'
         '  _account_change_blocked   -> ShopAccountGuard.account_change_blocked'),
    class_name='ShopAccountGuard',
    class_doc=('由应用入口创建一次；锁属于实例，不同实例互不影响。\n\n'
               '    ``shop_session`` 与 ``has_running_publish_tasks`` 由调用方注入：前者是账户注册表（测试里换成假件），\n'
               '    后者回答「现在有没有发布任务在跑」——任务字典属于上传 / 淘宝业务域，本类不碰它们。'),
    class_params=['shop_session', 'has_running_publish_tasks'],
    init_lines=[
        'self._shop_session = shop_session',
        'self._has_running_publish_tasks = has_running_publish_tasks',
    ],
    state_assigns=[('_shop_account_lock', 'self._lock')],
    class_extra=(
        '    @property\n'
        '    def lock(self):\n'
        '        """账户锁本体。媒体 / 白底图等 Blueprint 要拿同一把锁，所以对外暴露。"""\n'
        '        return self._lock\n'
    ),
    funcs=['_active_shop_profile', '_active_shop_account', '_with_shop_account_lock',
           '_require_publish_platform'],
    name_map={
        'shop_session': 'self._shop_session',
        '_shop_account_lock': 'self._lock',
        '_active_shop_account': 'self.active_account',
    },
    per_func={
        '_active_shop_profile': {'new_name': 'active_profile'},
        '_active_shop_account': {'new_name': 'active_account'},
        '_with_shop_account_lock': {'new_name': 'with_lock'},
        '_require_publish_platform': {'new_name': 'require_publish_platform'},
    },
    # 手写：把原 _account_change_blocked 的「查任务字典」和「拼 409 响应」拆开。
    # 任务字典（_upload_tasks / _taobao_tasks）是上传 / 淘宝域的状态，还留在 app.py；
    # 这两段合起来与原函数逐行等价，由 tests/test_shop_accounts.py 守护。
    manual_methods=(
        '    def account_change_blocked(self):\n'
        '        running = self._has_running_publish_tasks()\n'
        '        if running:\n'
        "            return jsonify(success=False, msg='发布任务运行中，请完成或取消后再切换账户'), 409\n"
        '        return None\n'
    ),
    app_replacements={
        '_account_change_blocked': (
            'def _publish_tasks_running():\n'
            '    with _upload_tasks_lock:\n'
            "        running = any(task.get('status') in ('pending', 'running') for task in _upload_tasks.values())\n"
            '    with _taobao_tasks_lock:\n'
            "        running = running or any(task.get('status') in ('pending', 'running')\n"
            '                                 for task in _taobao_tasks.values())\n'
            '    return running\n'
        ),
    },
    insert_after=[('_publish_tasks_running', (
        'shop_accounts = ShopAccountGuard(\n'
        '    shop_session=shop_session, has_running_publish_tasks=_publish_tasks_running,\n'
        ')\n'
        '# 账户门禁的实现在 src/sidecar/shop_accounts.py。上传 / 淘宝 / 小红书 / 保存等业务域还留在本文件，\n'
        '# 继续按原来的函数名使用；这些域拆出去时再改为直接依赖 shop_accounts。\n'
        '_shop_account_lock = shop_accounts.lock\n'
        '_active_shop_profile = shop_accounts.active_profile\n'
        '_active_shop_account = shop_accounts.active_account\n'
        '_with_shop_account_lock = shop_accounts.with_lock\n'
        '_require_publish_platform = shop_accounts.require_publish_platform\n'
        '_account_change_blocked = shop_accounts.account_change_blocked\n'
    ))],
    app_import='from src.sidecar.shop_accounts import ShopAccountGuard',
    comment_edits=[(
        '            # 本函数会被 tests/test_shop_platform_api.py 用 ast 抽取单独 exec（不含 import ✗），\n'
        '            # 所以这里**不能**调用 platform_label() 或引用 shop_session —— 用内联映射 ✓。\n',
        '            # 提示语里的平台短名内联在这里，与 shop_routes 里 platform_label 的完整名不是同一份映射。\n',
    )],
)

# ------------------------------------------------------------------------------------ 2. 调试浏览器服务
DEBUG_PORT_PRELUDE = '''\
@dataclass(frozen=True)
class DebugBrowserPort:
    """调试浏览器服务需要的外部能力，由应用入口一次性注入。

    各字段对应 app.py / src.utils 里已有的实现，本模块不导入浏览器自动化库。
    ``page_state`` 是无参函数，每次调用返回当前的共享页面状态（带 ``page`` 属性的对象）：必须每次取最新值，
    因为 GUI 兼容模式会在启动后换掉这个对象，缓存引用会让两边各持一份 ``page``。
    """

    page_state: Callable[[], Any]
    active_profile: Callable[[], str]
    discover_browsers: Callable[..., Any]
    normalize_address: Callable[[str], str]
    verify_browser: Callable[..., Any]
    attach_existing: Callable[..., Any]
    open_page: Callable[..., Any]
    chrome_path: Callable[[], Any]
    is_port_available: Callable[[str, int], bool]
    host: str
    port_start: int
    port_end: int
    default_url: str
'''

DEBUG_RENAMES = {
    # 方法（原来是 app.py 的模块函数）
    '_debug_root_dir': 'self._debug_root_dir',
    '_create_browser_debug_session': 'self.create_session',
    '_get_browser_debug_session': 'self.get_session',
    '_append_browser_debug_event': 'self.append_event',
    '_set_last_browser_debug_error': 'self.set_last_error',
    '_get_last_browser_debug_error': 'self.get_last_error',
    '_set_browser_debug_instance': 'self.set_browser_instance',
    '_get_browser_debug_instance': 'self.get_browser_instance',
    '_latest_browser_debug_error_after': 'self.latest_error_after',
    '_find_debug_browser_process': 'self.find_browser_process',
    '_get_default_debug_browser_user_data_dir': 'self._get_default_debug_browser_user_data_dir',
    '_select_debug_browser_port': 'self._select_debug_browser_port',
    '_resolve_debug_browser_launch_path': 'self._resolve_debug_browser_launch_path',
    '_launch_attachable_debug_browser': 'self.launch_attachable_browser',
    '_get_gui_page_debug_address': 'self.gui_page_debug_address',
    '_get_current_browser_tab': 'self.get_current_tab',
    '_snapshot_browser_context': 'self.snapshot_context',
    '_capture_browser_debug_artifacts': 'self.capture_artifacts',
    '_record_browser_automation_error': 'self.record_automation_error',
    # 模块级纯函数（只有对外用到的才改成公开名字）
    '_debug_bool': 'debug_bool',
    '_debug_int': 'debug_int',
    '_serialize_browser_debug_session': 'serialize_session',
    '_query_browser_elements': 'query_elements',
    '_get_browser_target_element': 'get_target_element',
    '_wait_for_browser_condition': 'wait_for_condition',
}

SLICES['debug_service'] = Slice(
    key='debug_service',
    module_file='debug_browser_service.py',
    doc=('调试浏览器服务：调试会话、事件、错误报告与调试浏览器实例的进程级状态，以及围绕它们的页面查询 / 等待 / 截图能力。\n\n'
         '状态属于 ``BrowserDebugService`` 实例（由应用入口创建一次），不再是模块级全局字典；浏览器相关能力\n'
         '（打开页面、连接已有浏览器、枚举调试进程……）全部经 ``DebugBrowserPort`` 注入，本模块不导入浏览器自动化库，\n'
         '也不反向导入 app.py。\n\n'
         '与 app.py 旧函数名的对应（只列对外有调用方的；其余私有函数保持原名）：\n'
         '  _create_browser_debug_session     -> BrowserDebugService.create_session\n'
         '  _get_browser_debug_session        -> BrowserDebugService.get_session\n'
         '  _append_browser_debug_event       -> BrowserDebugService.append_event\n'
         '  _set/_get_last_browser_debug_error -> BrowserDebugService.set_last_error / get_last_error\n'
         '  _set/_get_browser_debug_instance  -> BrowserDebugService.set_browser_instance / get_browser_instance\n'
         '  _latest_browser_debug_error_after -> BrowserDebugService.latest_error_after\n'
         '  _find_debug_browser_process       -> BrowserDebugService.find_browser_process\n'
         '  _launch_attachable_debug_browser  -> BrowserDebugService.launch_attachable_browser\n'
         '  _get_gui_page_debug_address       -> BrowserDebugService.gui_page_debug_address\n'
         '  _get_current_browser_tab          -> BrowserDebugService.get_current_tab\n'
         '  _snapshot_browser_context         -> BrowserDebugService.snapshot_context\n'
         '  _capture_browser_debug_artifacts  -> BrowserDebugService.capture_artifacts\n'
         '  _record_browser_automation_error  -> BrowserDebugService.record_automation_error\n'
         '  _debug_bool / _debug_int          -> debug_bool / debug_int（模块级函数）\n'
         '  _serialize_browser_debug_session  -> serialize_session\n'
         '  _query_browser_elements / _get_browser_target_element / _wait_for_browser_condition\n'
         '                                    -> query_elements / get_target_element / wait_for_condition'),
    prelude=DEBUG_PORT_PRELUDE,
    consts=['_BROWSER_DEBUG_MAX_EVENTS', '_BROWSER_DEBUG_MAX_SESSIONS'],
    module_funcs=['_debug_now_iso', '_debug_bool', '_debug_int', '_debug_normalize_text', '_debug_slug',
                  '_serialize_browser_debug_session', '_collect_browser_page_bits', '_normalize_debug_locator',
                  '_summarize_debug_element', '_query_browser_elements', '_get_browser_target_element',
                  '_evaluate_browser_wait_condition', '_wait_for_browser_condition'],
    class_name='BrowserDebugService',
    class_doc=('一个应用一个实例，持有调试会话 / 事件 / 最近一次错误报告 / 调试浏览器实例这些状态。\n\n'
               '    ``browser`` 是 ``DebugBrowserPort``；``repo_root`` 与 ``get_app_root`` 决定调试产物（截图、页面快照、\n'
               '    错误报告）落在哪个目录。'),
    class_params=['browser', 'repo_root', 'get_app_root'],
    init_lines=[
        'self._browser = browser',
        'self._repo_root = repo_root',
        'self._get_app_root = get_app_root',
    ],
    state_assigns=[('_browser_debug_lock', 'self._lock'), ('_browser_debug_state', 'self._state')],
    class_extra=(
        '    @property\n'
        '    def browser(self):\n'
        '        """注入的浏览器端口；路由里的「枚举调试浏览器」直接用它。"""\n'
        '        return self._browser\n'
    ),
    funcs=['_debug_root_dir', '_create_browser_debug_session', '_get_browser_debug_session',
           '_append_browser_debug_event', '_set_last_browser_debug_error', '_get_last_browser_debug_error',
           '_set_browser_debug_instance', '_get_browser_debug_instance', '_latest_browser_debug_error_after',
           '_find_debug_browser_process', '_get_default_debug_browser_user_data_dir',
           '_select_debug_browser_port', '_resolve_debug_browser_launch_path',
           '_launch_attachable_debug_browser', '_get_gui_page_debug_address', '_get_current_browser_tab',
           '_snapshot_browser_context', '_capture_browser_debug_artifacts', '_record_browser_automation_error'],
    name_map=dict(DEBUG_RENAMES, **{
        # 状态
        '_browser_debug_lock': 'self._lock',
        '_browser_debug_state': 'self._state',
        # 注入的浏览器能力
        'gui': 'self._browser.page_state()',
        'get_page': 'self._browser.open_page',
        'attach_existing_debug_browser': 'self._browser.attach_existing',
        'discover_debuggable_browsers': 'self._browser.discover_browsers',
        '_normalize_debug_address': 'self._browser.normalize_address',
        '_verify_debug_browser': 'self._browser.verify_browser',
        'get_chrome_path': 'self._browser.chrome_path',
        '_active_shop_profile': 'self._browser.active_profile',
        '_is_local_port_available': 'self._browser.is_port_available',
        '_DEBUG_BROWSER_HOST': 'self._browser.host',
        '_DEBUG_BROWSER_PORT_START': 'self._browser.port_start',
        '_DEBUG_BROWSER_PORT_END': 'self._browser.port_end',
        '_BROWSER_DEBUG_DEFAULT_URL': 'self._browser.default_url',
        # 调试产物目录
        'get_app_root': 'self._get_app_root',
        'repo_root': 'self._repo_root',
    }),
    per_func={
        '_debug_bool': {'new_name': 'debug_bool'},
        '_debug_int': {'new_name': 'debug_int'},
        '_serialize_browser_debug_session': {'new_name': 'serialize_session'},
        '_query_browser_elements': {'new_name': 'query_elements'},
        '_get_browser_target_element': {'new_name': 'get_target_element'},
        '_wait_for_browser_condition': {'new_name': 'wait_for_condition'},
        '_create_browser_debug_session': {'new_name': 'create_session'},
        '_get_browser_debug_session': {'new_name': 'get_session'},
        '_append_browser_debug_event': {'new_name': 'append_event'},
        '_set_last_browser_debug_error': {'new_name': 'set_last_error'},
        '_get_last_browser_debug_error': {'new_name': 'get_last_error'},
        '_set_browser_debug_instance': {'new_name': 'set_browser_instance'},
        '_get_browser_debug_instance': {'new_name': 'get_browser_instance'},
        '_latest_browser_debug_error_after': {'new_name': 'latest_error_after'},
        '_find_debug_browser_process': {'new_name': 'find_browser_process'},
        '_launch_attachable_debug_browser': {'new_name': 'launch_attachable_browser'},
        '_get_gui_page_debug_address': {'new_name': 'gui_page_debug_address'},
        '_get_current_browser_tab': {'new_name': 'get_current_tab'},
        '_snapshot_browser_context': {'new_name': 'snapshot_context'},
        '_capture_browser_debug_artifacts': {'new_name': 'capture_artifacts'},
        '_record_browser_automation_error': {'new_name': 'record_automation_error'},
    },
    import_overrides={
        'dataclass': 'from dataclasses import dataclass',
        'Any': 'from typing import Any',
        'Callable': 'from typing import Callable',
    },
    insert_after=[('_is_local_port_available', (
        'browser_debug = BrowserDebugService(\n'
        '    browser=DebugBrowserPort(\n'
        '        page_state=lambda: gui,\n'
        '        active_profile=_active_shop_profile,\n'
        '        discover_browsers=discover_debuggable_browsers,\n'
        '        normalize_address=_normalize_debug_address,\n'
        '        verify_browser=_verify_debug_browser,\n'
        '        attach_existing=attach_existing_debug_browser,\n'
        '        open_page=get_page,\n'
        '        chrome_path=get_chrome_path,\n'
        '        is_port_available=_is_local_port_available,\n'
        '        host=_DEBUG_BROWSER_HOST,\n'
        '        port_start=_DEBUG_BROWSER_PORT_START,\n'
        '        port_end=_DEBUG_BROWSER_PORT_END,\n'
        '        default_url=_BROWSER_DEBUG_DEFAULT_URL,\n'
        '    ),\n'
        '    repo_root=repo_root,\n'
        '    get_app_root=get_app_root,\n'
        ')\n'
        '# 调试浏览器的状态与实现在 src/sidecar/debug_browser_service.py。上传 / 淘宝 / 采集等业务域还留在本文件，\n'
        '# 继续按原来的函数名使用；这些域拆出去时再改为直接依赖 browser_debug。\n'
        '_get_current_browser_tab = browser_debug.get_current_tab\n'
        '_snapshot_browser_context = browser_debug.snapshot_context\n'
        '_record_browser_automation_error = browser_debug.record_automation_error\n'
        '_latest_browser_debug_error_after = browser_debug.latest_error_after\n'
        '_set_browser_debug_instance = browser_debug.set_browser_instance\n'
        '_find_debug_browser_process = browser_debug.find_browser_process\n'
        '_get_gui_page_debug_address = browser_debug.gui_page_debug_address\n'
        '_debug_bool = debug_bool\n'
        '_debug_int = debug_int\n'
    ))],
    app_import=('from src.sidecar.debug_browser_service import (\n'
                '    BrowserDebugService,\n'
                '    DebugBrowserPort,\n'
                '    debug_bool,\n'
                '    debug_int,\n'
                ')'),
)

# ------------------------------------------------------------------------------------ 3. 调试浏览器路由
SLICES['debug_routes'] = Slice(
    key='debug_routes',
    module_file='debug_browser_routes.py',
    doc=('CDP 调试浏览器接口（/api/debug/browser/*）：确保 / 启动 / 查询 / 等待 / 操作 / 截图 / 读取最近一次错误。\n\n'
         '这些接口只做 HTTP 适配；状态与浏览器能力都在 ``BrowserDebugService``（见 debug_browser_service.py）。'),
    factory='create_debug_browser_blueprint',
    blueprint_name='debug_browser',
    params=['service'],
    factory_doc='``service`` 是 ``BrowserDebugService``：调试会话状态和浏览器能力都由它持有。',
    funcs=['debug_browser_ensure', 'debug_browser_discover', 'debug_browser_launch', 'debug_browser_session',
           'debug_browser_context', 'debug_browser_query', 'debug_browser_wait', 'debug_browser_action',
           'debug_browser_capture', 'debug_browser_last_error'],
    name_map={
        '_debug_bool': 'debug_bool',
        '_debug_int': 'debug_int',
        '_serialize_browser_debug_session': 'serialize_session',
        '_query_browser_elements': 'query_elements',
        '_get_browser_target_element': 'get_target_element',
        '_wait_for_browser_condition': 'wait_for_condition',
        '_create_browser_debug_session': 'service.create_session',
        '_get_browser_debug_session': 'service.get_session',
        '_get_current_browser_tab': 'service.get_current_tab',
        '_snapshot_browser_context': 'service.snapshot_context',
        '_append_browser_debug_event': 'service.append_event',
        '_launch_attachable_debug_browser': 'service.launch_attachable_browser',
        '_set_browser_debug_instance': 'service.set_browser_instance',
        '_get_browser_debug_instance': 'service.get_browser_instance',
        '_get_last_browser_debug_error': 'service.get_last_error',
        '_capture_browser_debug_artifacts': 'service.capture_artifacts',
        'discover_debuggable_browsers': 'service.browser.discover_browsers',
    },
    import_overrides={
        'time': 'import time',
        'debug_bool': 'from .debug_browser_service import debug_bool',
        'debug_int': 'from .debug_browser_service import debug_int',
        'serialize_session': 'from .debug_browser_service import serialize_session',
        'query_elements': 'from .debug_browser_service import query_elements',
        'get_target_element': 'from .debug_browser_service import get_target_element',
        'wait_for_condition': 'from .debug_browser_service import wait_for_condition',
    },
    app_import='from src.sidecar.debug_browser_routes import create_debug_browser_blueprint',
    registration='app.register_blueprint(create_debug_browser_blueprint(service=browser_debug))\n',
)

# ------------------------------------------------------------------------------------ 4. 店铺会话服务
SHOP_PORT_PRELUDE = '''\
@dataclass(frozen=True)
class ShopBrowserPort:
    """店铺会话需要的浏览器能力，由应用入口一次性注入；本模块不导入浏览器自动化库。

    ``page_state`` 是无参函数，每次调用返回当前的共享页面状态（带 ``page`` 属性的对象），含义同
    ``DebugBrowserPort.page_state``。``host`` / ``shop_port_start`` / ``shop_port_end`` 是店铺浏览器的
    调试地址与端口段（与 src/utils.py 的 _SHOP_BROWSER_PORT_* 必须一致），其它业务域也在用，所以留在 app.py。
    """

    page_state: Callable[[], Any]
    open_page: Callable[..., Any]
    normalize_address: Callable[[str], str]
    gui_page_debug_address: Callable[[], str]
    find_browser_process: Callable[[str], Any]
    find_reusable_browser: Callable[..., Any]
    set_debug_browser_instance: Callable[[Any], None]
    host: str
    shop_port_start: int
    shop_port_end: int
'''

SLICES['shop_service'] = Slice(
    key='shop_service',
    module_file='shop_service.py',
    doc=('店铺会话服务：找出「发布流程这一刻会用到的浏览器」、实测当前登录的店铺、切换账户时丢弃旧浏览器句柄并打开登录页。\n\n'
         '设计前提：应用自己不存 cookie，登录态全部寄生在 Chrome 用户数据目录里。所以「当前登录哪个店」只能从真正会被\n'
         '发布流程用到的那个浏览器上实测，不能从 profile 名字推断——名字是意图，cookie 才是事实。\n\n'
         '浏览器能力经 ``ShopBrowserPort`` 注入，账户门禁来自 ``ShopAccountGuard``；本模块不导入浏览器自动化库，\n'
         '也不反向导入 app.py。\n\n'
         '与 app.py 旧函数名的对应：\n'
         '  _resolve_active_shop_browser -> ShopSessionService.resolve_active_browser\n'
         '  _build_shop_current_payload  -> ShopSessionService.build_current_payload\n'
         '  _activate_shop_profile       -> ShopSessionService.activate_profile'),
    prelude=SHOP_PORT_PRELUDE,
    consts=['_SHOP_LOGIN_URL', '_TAOBAO_SHOP_LOGIN_URL'],
    module_funcs=['_shop_profile_matches'],
    class_name='ShopSessionService',
    class_doc=('一个应用一个实例。``accounts`` 是 ``ShopAccountGuard``，``browser`` 是 ``ShopBrowserPort``，\n'
               '    ``shop_session`` 是账户注册表模块（测试里换成假件）。'),
    class_params=['accounts', 'browser', 'shop_session'],
    init_lines=[
        'self._accounts = accounts',
        'self._browser = browser',
        'self._shop_session = shop_session',
    ],
    funcs=['_resolve_taobao_shop_browser', '_resolve_xiaohongshu_shop_browser', '_resolve_active_shop_browser',
           '_build_shop_current_payload', '_activate_shop_profile'],
    name_map={
        'shop_session': 'self._shop_session',
        'app': 'current_app',
        '_active_shop_account': 'self._accounts.active_account',
        '_find_reusable_logged_in_fxg_browser': 'self._browser.find_reusable_browser',
        '_normalize_debug_address': 'self._browser.normalize_address',
        '_get_gui_page_debug_address': 'self._browser.gui_page_debug_address',
        '_find_debug_browser_process': 'self._browser.find_browser_process',
        '_set_browser_debug_instance': 'self._browser.set_debug_browser_instance',
        'gui': 'self._browser.page_state()',
        'get_page': 'self._browser.open_page',
        '_DEBUG_BROWSER_HOST': 'self._browser.host',
        '_SHOP_BROWSER_PORT_START': 'self._browser.shop_port_start',
        '_SHOP_BROWSER_PORT_END': 'self._browser.shop_port_end',
        '_resolve_taobao_shop_browser': 'self._resolve_taobao_shop_browser',
        '_resolve_xiaohongshu_shop_browser': 'self._resolve_xiaohongshu_shop_browser',
        '_resolve_active_shop_browser': 'self.resolve_active_browser',
        '_activate_shop_profile': 'self.activate_profile',
    },
    per_func={
        '_resolve_active_shop_browser': {'new_name': 'resolve_active_browser'},
        '_build_shop_current_payload': {'new_name': 'build_current_payload'},
        '_activate_shop_profile': {'new_name': 'activate_profile'},
    },
    import_overrides={
        'dataclass': 'from dataclasses import dataclass',
        'Any': 'from typing import Any',
        'Callable': 'from typing import Callable',
        'current_app': 'from flask import current_app',
    },
    insert_after=[('_debug_int', (
        'shop_session_service = ShopSessionService(\n'
        '    accounts=shop_accounts,\n'
        '    browser=ShopBrowserPort(\n'
        '        page_state=lambda: gui,\n'
        '        open_page=get_page,\n'
        '        normalize_address=_normalize_debug_address,\n'
        '        gui_page_debug_address=_get_gui_page_debug_address,\n'
        '        find_browser_process=_find_debug_browser_process,\n'
        '        find_reusable_browser=_find_reusable_logged_in_fxg_browser,\n'
        '        set_debug_browser_instance=_set_browser_debug_instance,\n'
        '        host=_DEBUG_BROWSER_HOST,\n'
        '        shop_port_start=_SHOP_BROWSER_PORT_START,\n'
        '        shop_port_end=_SHOP_BROWSER_PORT_END,\n'
        '    ),\n'
        '    shop_session=shop_session,\n'
        ')\n'
        '# 淘宝填表流程还在本文件，继续按原来的函数名使用；它拆出去时再改为直接依赖 shop_session_service。\n'
        '_resolve_active_shop_browser = shop_session_service.resolve_active_browser\n'
        '_activate_shop_profile = shop_session_service.activate_profile\n'
    ))],
    app_import='from src.sidecar.shop_service import ShopBrowserPort, ShopSessionService',
    # 区块注释「店铺会话（登录 / 查看 / 切换）」原本盖着这一组函数；函数搬走后它变成孤立注释，
    # 设计前提那段已经写进 shop_service.py 的模块文档里，这里删掉。
    app_edits=[(
        '# ========================= 店铺会话（登录 / 查看 / 切换）=========================\n'
        '#\n'
        '# 设计前提：应用自己不存 cookie，登录态全部寄生在 Chrome 用户数据目录里。\n'
        '# 所以「当前登录哪个店」这件事只能从**真正会被发布流程用到的那个浏览器**上实测，\n'
        '# 不能从 profile 名字推断——名字是意图，cookie 才是事实。\n'
        '\n\n',
        '',
    )],
    comment_edits=[(
        '            # ⚠️ 这里**不能**写 `shop_session.XHS_HOME_URL` ✗：本函数会被\n'
        '            # `tests/test_shop_platform_api.py` 用 ast 抽取后单独 exec（只含模块级常量 + 指定函数），\n'
        '            # 那个上下文里没有 `from src import shop_session` → 会在 open_browser=True 分支上\n'
        '            # 抛 NameError（实测：5 条店铺接口测试因此失败 ✗）。该测试的注释正是警告这件事。\n'
        '            # 共享库里的 `shop_session.XHS_HOME_URL` 仍是应用其它位置的唯一来源 ✓，两处需保持一致。\n',
        '            # ⚠️ 这里**不能**写 `shop_session.XHS_HOME_URL` ✗：测试注入的 `shop_session` 是假件，\n'
        '            # 没有这个属性，会在 open_browser=True 分支上抛 AttributeError。\n'
        '            # 共享库里的 `shop_session.XHS_HOME_URL` 仍是应用其它位置的唯一来源 ✓，两处需保持一致。\n',
    )],
)

# ------------------------------------------------------------------------------------ 5. 店铺会话路由
SLICES['shop_routes'] = Slice(
    key='shop_routes',
    module_file='shop_routes.py',
    doc=('店铺会话接口（/api/shop/*）：当前登录的店铺、运费模板、账户列表、添加 / 切换 / 移除账户。\n\n'
         '这些接口只做 HTTP 适配；账户门禁在 ``ShopAccountGuard``，浏览器会话在 ``ShopSessionService``。'),
    factory='create_shop_blueprint',
    blueprint_name='shop',
    params=['accounts', 'service', 'shop_session'],
    factory_doc=('``accounts`` 是 ``ShopAccountGuard``（账户锁与平台门禁），``service`` 是 ``ShopSessionService``\n'
                 '    （浏览器会话与身份实测），``shop_session`` 是账户注册表模块（测试里换成假件）。'),
    funcs=['platform_label', 'shop_current', 'shop_freight_templates', 'shop_profiles', 'shop_add',
           'shop_switch', 'shop_forget'],
    name_map={
        'app': 'current_app',
        '_account_change_blocked': 'accounts.account_change_blocked',
        '_active_shop_account': 'accounts.active_account',
        '_active_shop_profile': 'accounts.active_profile',
        '_build_shop_current_payload': 'service.build_current_payload',
        '_activate_shop_profile': 'service.activate_profile',
        '_resolve_active_shop_browser': 'service.resolve_active_browser',
    },
    decorator_name_map={'app': 'routes', '_with_shop_account_lock': 'accounts.with_lock'},
    import_overrides={'current_app': 'from flask import current_app'},
    doc_edits={'platform_label': [
        ('⚠️ 本函数会被 `tests/test_shop_platform_api.py` 用 ast 抽取单独 exec ✓，',
         '⚠️ 测试（`tests/test_shop_routes.py`、`tests/test_shop_platform_api.py`）注入的 `shop_session` 是**假件**，'),
        ('那里的 `shop_session` 是**测试注入的假件**（只提供 normalize_platform 等少量属性 ✗）',
         '只提供 normalize_platform 等少量属性 ✗'),
    ]},
    app_import='from src.sidecar.shop_routes import create_shop_blueprint',
    registration=('app.register_blueprint(create_shop_blueprint(\n'
                  '    accounts=shop_accounts, service=shop_session_service, shop_session=shop_session,\n'
                  '))\n'),
)

# 必须按这个顺序链式运行
ORDER = ['accounts', 'debug_service', 'debug_routes', 'shop_service', 'shop_routes']

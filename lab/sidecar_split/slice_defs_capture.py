# -*- coding: utf-8 -*-
"""链接采集（/api/capture/*）的搬迁规格（2026-10-20）：三个切片，必须按 capture_helpers → capture_service → capture_routes 链式运行。

  capture_helpers  无状态函数（URL 识别 / 价格与 SKU 解析 / 1688 页面快照 / 淘宝 ICE 提取 / 失败原因归类 …），搬成模块级函数；
  capture_service  ``CaptureService``：任务字典 / 互斥锁 / 正在运行的任务 id / mtop 缓存 / cookie 缓存，加上要用到它们或日志的方法；
  capture_routes   五个接口（``start_capture`` 一个函数 1100+ 行，含后台线程里的整套采集流程，按「先机械搬迁、再拆」原样保留）。

留在 app.py 的（别的业务域也在用，或模块级代码直接引用），经注入传入：
  normalize_save_path / get_app_root（路径规则依赖入口文件位置，白底图服务也在用）、_is_local_port_available（调试浏览器端口对象在用）、
  _find_cdp_port / _load_capture_attributes（上传 / 淘宝域共用）、_PROTOCOL_CAPTURE_ENGINE、
  _normalize_debug_address / _verify_debug_browser / discover_debuggable_browsers（来自 src.utils，会拖进浏览器库）。
"""
from slice_tool import Slice

SLICES = {}

# capture_url_utils 原来在 tauri-app/python-sidecar/ 里靠入口目录进 sys.path；这是个纯模块，同一批搬进了 src/，新模块用包内路径导入
URL_UTILS_IMPORTS = {name: 'from src.capture_url_utils import %s' % name
                     for name in ('capture_url_host', 'is_taobao_short_link', 'normalize_capture_url')}

# ------------------------------------------------------------------------------------------ 无状态函数
# 只依赖入参和标准库 / 轻量库；不碰任务字典、锁、浏览器单例、Flask 请求上下文，也不写日志（写日志要 app.logger）。
HELPER_FUNCS = [
    '_detect_capture_source_platform', '_write_protocol_capture_artifact_json', '_finalize_protocol_capture_record',
    '_get_capture_browser_user_data_path', 'infer_clazz_from_title', '_capture_wait_seconds',
    '_capture_failure_details', '_capture_task_recovery_info', '_is_1688_capture_url',
    '_is_taobao_tmall_capture_url', '_resolve_capture_redirect_url', '_is_1688_login_url', '_is_taobao_login_url',
    '_detect_local_proxy_risk', '_is_taobao_tmall_product_url', '_is_taobao_tmall_store_url',
    '_extract_capture_product_id', '_parse_capture_price', '_extract_capture_price_from_mapping',
    '_extract_1688_context_snapshot', '_is_1688_antibot_page', '_collect_1688_detail_images',
    '_build_1688_sku_info', '_extract_text_by_selectors', '_extract_taobao_ice_data',
]
# 整个仓库里没有任何调用方的函数（搬迁时发现）。先原样保留在 helpers 里，是否删除由使用者决定。
DEAD_FUNCS = [
    '_extract_taobao_tmall_item_id', '_normalize_taobao_tmall_item_url', '_append_query_params', '_mtop_post_fetch',
    '_infer_capture_image_ext', '_parse_ice_from_html',
]

SLICES['capture_helpers'] = Slice(
    key='capture_helpers',
    module_file='capture_helpers.py',
    doc=('链接采集的无状态函数：URL 识别与归一、价格 / SKU 解析、1688 页面快照、淘宝 ICE 数据提取、失败原因归类、'
         '协议采集产物写入等。\n\n'
         '这里的函数只依赖入参和标准库 / 轻量库，不碰任务字典、锁、浏览器单例和 Flask 请求上下文；'
         '需要这些的函数在 ``capture_service.CaptureService``。\n\n'
         '搬迁时发现下面 6 个函数在整个仓库里没有任何调用方，先原样保留：'
         + '、'.join('``%s``' % n for n in DEAD_FUNCS) + '。'),
    module_funcs=HELPER_FUNCS + DEAD_FUNCS,
    import_overrides=URL_UTILS_IMPORTS,
)

# ------------------------------------------------------------------------------------------ 服务类
# 旧函数名 -> 方法名。路由要调用的改成公开名，其余保持原名（下划线开头 = 类内部使用）。
SERVICE_METHODS = {
    '_start_protocol_capture_record': 'start_protocol_capture_record',
    '_select_capture_browser_port': 'select_capture_browser_port',
    '_capture_product_attributes': 'capture_product_attributes',
    '_cdp_get_cookies_and_token': '_cdp_get_cookies_and_token',
    '_collect_store_products_via_mtop': '_collect_store_products_via_mtop',
    '_collect_taobao_tmall_store_product_urls': '_collect_taobao_tmall_store_product_urls',
    '_collect_taobao_desc_images_via_browser': '_collect_taobao_desc_images_via_browser',
    '_fetch_taobao_desc_images': '_fetch_taobao_desc_images',
    '_extract_taobao_tmall_product_snapshot': '_extract_taobao_tmall_product_snapshot',
    '_download_capture_product_images': '_download_capture_product_images',
    '_get_browser_cookies_for_http': '_get_browser_cookies_for_http',
    '_capture_taobao_tmall_product_for_store': 'capture_taobao_tmall_product_for_store',
    '_run_taobao_tmall_store_capture': 'run_taobao_tmall_store_capture',
    '_import_capture_product_record': 'import_capture_product_record',
}
# 路由层要调用的（也就是被改成公开名的）
PUBLIC_METHODS = {old: new for old, new in SERVICE_METHODS.items() if old != new}

# 服务类从应用入口拿到的东西：旧的全局名 -> 实例属性
SERVICE_INJECTED = {
    'Record': 'self._record_model',
    '_find_cdp_port': 'self._find_cdp_port',
    '_load_capture_attributes': 'self._load_capture_attributes',
    'normalize_save_path': 'self._normalize_save_path',
    '_is_local_port_available': 'self._is_local_port_available',
    '_normalize_debug_address': 'self._normalize_debug_address',
    '_verify_debug_browser': 'self._verify_debug_browser',
    'discover_debuggable_browsers': 'self._discover_debuggable_browsers',
    '_DEBUG_BROWSER_HOST': 'self._debug_host',
    '_CAPTURE_BROWSER_PORT_START': 'self._capture_port_start',
    '_CAPTURE_BROWSER_PORT_END': 'self._capture_port_end',
    '_PROTOCOL_CAPTURE_ENGINE': 'self._protocol_capture_engine',
}
# 原来的模块全局状态 -> 实例属性（``global`` 声明随之删除）
SERVICE_STATE = [
    ('capture_tasks', 'self.tasks'),
    ('_capture_lock', 'self.lock'),
    ('_capture_running_task_id', 'self.running_task_id'),
    ('_mtop_product_cache', 'self.mtop_product_cache'),
    ('_browser_cookie_str', 'self._browser_cookie_str'),
    ('_browser_cookie_ts', 'self._browser_cookie_ts'),
]

_SERVICE_NAME_MAP = {old: 'self.' + new for old, new in SERVICE_METHODS.items()}
_SERVICE_NAME_MAP.update(SERVICE_INJECTED)
_SERVICE_NAME_MAP.update(dict(SERVICE_STATE))
_SERVICE_NAME_MAP['app'] = 'self'           # app.logger -> self.logger（后台线程里没有应用上下文，不能用 current_app）

# 其余函数（helpers 里的）在服务 / 路由模块里按原名使用，经 import_overrides 从 .capture_helpers 导入
HELPER_IMPORTS = {name: 'from .capture_helpers import %s' % name for name in HELPER_FUNCS}

SLICES['capture_service'] = Slice(
    key='capture_service',
    module_file='capture_service.py',
    doc=('链接采集服务：任务字典与互斥锁、淘宝 / 天猫店铺批量采集、单品 ICE → HTTP → DOM 三级提取、采集浏览器端口选择、'
         '采集结果入库。\n\n'
         '任务字典 ``tasks``、互斥锁 ``lock``、正在运行的任务 id ``running_task_id``、mtop 商品缓存和浏览器 cookie 缓存'
         '原来是 ``app.py`` 的模块全局（靠 ``global`` 声明读写），现在是 ``CaptureService`` 实例的属性，由应用入口创建一次；'
         '``global`` 声明随之去掉。\n\n'
         '这个类不导入 ``src.utils`` / DrissionPage / ``app.py``：浏览器相关能力、路径规则、端口占用检查都由应用入口注入；'
         '``logger`` 是应用入口传入的 ``app.logger``——后台线程里没有 Flask 应用上下文，不能用 ``current_app``。\n\n'
         '与 app.py 旧函数名的对应：\n'
         + '\n'.join('  %-42s -> CaptureService.%s' % (old, new) for old, new in SERVICE_METHODS.items())
         + '\n  capture_tasks / _capture_lock / _capture_running_task_id -> tasks / lock / running_task_id'
         + '\n  _mtop_product_cache / _browser_cookie_str / _browser_cookie_ts -> mtop_product_cache / _browser_cookie_str / _browser_cookie_ts'),
    class_name='CaptureService',
    class_doc=('一个应用一个实例，持有采集任务的全部进程内状态。\n\n'
               '    ``record_model`` 是商品表；``logger`` 是 ``app.logger``；``protocol_capture_engine`` 是可选的协议采集引擎（没有就是 None）；\n'
               '    ``find_cdp_port`` / ``load_capture_attributes`` 与上传、淘宝域共用，``normalize_save_path`` 与白底图服务共用，'
               '``is_local_port_available`` 与调试浏览器共用，所以都留在应用入口；\n'
               '    ``normalize_debug_address`` / ``verify_debug_browser`` / ``discover_browsers`` 在 src.utils 里（会连带导入浏览器库），所以注入；\n'
               '    ``debug_host`` / ``capture_port_start`` / ``capture_port_end`` 是采集浏览器的调试地址和端口段。'),
    class_params=['record_model', 'logger', 'protocol_capture_engine', 'find_cdp_port', 'load_capture_attributes',
                  'normalize_save_path', 'is_local_port_available', 'normalize_debug_address', 'verify_debug_browser',
                  'discover_browsers', 'debug_host', 'capture_port_start', 'capture_port_end'],
    wrap_init=True,
    init_lines=[
        'self._record_model = record_model',
        'self.logger = logger',
        'self._protocol_capture_engine = protocol_capture_engine',
        'self._find_cdp_port = find_cdp_port',
        'self._load_capture_attributes = load_capture_attributes',
        'self._normalize_save_path = normalize_save_path',
        'self._is_local_port_available = is_local_port_available',
        'self._normalize_debug_address = normalize_debug_address',
        'self._verify_debug_browser = verify_debug_browser',
        'self._discover_debuggable_browsers = discover_browsers',
        'self._debug_host = debug_host',
        'self._capture_port_start = capture_port_start',
        'self._capture_port_end = capture_port_end',
    ],
    state_assigns=SERVICE_STATE,
    funcs=list(SERVICE_METHODS),
    name_map=_SERVICE_NAME_MAP,
    per_func={old: {'new_name': new} for old, new in PUBLIC_METHODS.items()},
    import_overrides=HELPER_IMPORTS,
    app_import='from src.sidecar.capture_service import CaptureService',
    insert_after=[('_active_update_tasks', (
        'capture_service = CaptureService(\n'
        '    record_model=Record, logger=app.logger, protocol_capture_engine=_PROTOCOL_CAPTURE_ENGINE,\n'
        '    find_cdp_port=_find_cdp_port, load_capture_attributes=_load_capture_attributes,\n'
        '    normalize_save_path=normalize_save_path, is_local_port_available=_is_local_port_available,\n'
        '    normalize_debug_address=_normalize_debug_address, verify_debug_browser=_verify_debug_browser,\n'
        '    discover_browsers=discover_debuggable_browsers, debug_host=_DEBUG_BROWSER_HOST,\n'
        '    capture_port_start=_CAPTURE_BROWSER_PORT_START, capture_port_end=_CAPTURE_BROWSER_PORT_END,\n'
        ')'
    ))],
    app_edits=[
        # 更新器的「有没有任务在跑」检查读的是采集的锁和任务 id：改为读服务对象
        ('    with _capture_lock:\n        capture = int(_capture_running_task_id is not None)\n',
         '    with capture_service.lock:\n        capture = int(capture_service.running_task_id is not None)\n'),
    ],
)

# ------------------------------------------------------------------------------------------ 路由
_ROUTES_NAME_MAP = {
    'capture_tasks': 'service.tasks',
    '_capture_lock': 'service.lock',
    '_capture_running_task_id': 'service.running_task_id',
    'app': 'service',                       # app.logger -> service.logger
}
_ROUTES_NAME_MAP.update({old: 'service.' + new for old, new in PUBLIC_METHODS.items()})

SLICES['capture_routes'] = Slice(
    key='capture_routes',
    module_file='capture_routes.py',
    doc=('商品链接采集接口（/api/capture/*）：启动 / 状态 / 历史 / 取消 / 导入。\n\n'
         '``start_capture`` 一个函数 1100+ 行（里面的后台线程跑着整套采集流程），按「先机械搬迁、再拆」的原则原样保留；'
         '状态都在 ``CaptureService``。后台线程里没有 Flask 应用上下文，所以日志走 ``service.logger``（应用入口传入的 ``app.logger``），'
         '不能用 ``current_app``。'),
    factory='create_capture_blueprint',
    blueprint_name='capture',
    params=['service', 'normalize_save_path', 'get_app_root', 'settings_manager'],
    factory_doc=('``service`` 是 ``CaptureService``（任务状态、日志、提取逻辑）；``normalize_save_path`` / ``get_app_root`` 留在应用入口'
                 '（路径规则依赖入口文件的位置，别的业务域也在用）；``settings_manager`` 提供用户保存的采集方式偏好。'),
    funcs=['start_capture', 'get_capture_status', 'get_capture_history', 'cancel_capture', 'import_capture_result'],
    name_map=_ROUTES_NAME_MAP,
    import_overrides=dict(HELPER_IMPORTS, urlopen='from urllib.request import urlopen', **URL_UTILS_IMPORTS),
    comment_edits=[
        ('# 注：函数顶部已经 `global _capture_running_task_id`，这里不能再声明一次',
         '# 注：任务 id 和互斥锁现在是 service 的属性（原来的 global 声明随搬迁去掉了）'),
    ],
    app_import='from src.sidecar.capture_routes import create_capture_blueprint',
    registration=('app.register_blueprint(create_capture_blueprint(\n'
                  '    service=capture_service, normalize_save_path=normalize_save_path, get_app_root=get_app_root,\n'
                  '    settings_manager=settings_manager,\n'
                  '))\n'),
)

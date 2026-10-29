# -*- coding: utf-8 -*-
"""淘宝发布（/api/taobao/*）的搬迁规格（2026-10-20）：三个切片，必须按 taobao_helpers → taobao_service → taobao_routes 链式运行。

  taobao_helpers  两个纯函数（发布开关解析 / 从商品记录构造请求载荷）和它们用到的两个常量；
  taobao_service  ``TaobaoPublishService``：任务字典 / 互斥锁，加上要用到它们、账户门禁或店铺会话的方法
                  （加载淘宝模块、取浏览器调试地址、拉起素材中心浏览器、请求翻译、单品 / 批量发布 worker）；
  taobao_routes   八个接口（就绪度 / 资料检查 / 导出资料包 / 启动发布 / 批量发布 / 进度 / 取消 / 任务列表）+ 请求体解析小函数。

留在 app.py 的（别的业务域也在用），经注入传入：
  Record（商品表）、repo_root、resolve_data_file、_bootstrap_log、_normalize_debug_address（来自 src.utils，会拖进浏览器库）、
  _require_product_revision（保存商品 / 抖店上传也在用）；账户门禁和店铺会话直接依赖 ``shop_accounts`` / ``shop_session_service``
  （两个别名 ``_resolve_active_shop_browser`` / ``_activate_shop_profile`` / ``_account_change_blocked`` 随之变成无人使用，一并删除）。

app.py 里读淘宝任务字典 / 翻译函数的 4 处（发布任务在跑检查、保存商品的编辑保护、保存时校验标题、更新器的任务检查）
改为直接读 ``taobao_service``。
"""
from slice_tool import Slice

SLICES = {}

# ------------------------------------------------------------------------------------------ 纯函数 + 常量
SLICES['taobao_helpers'] = Slice(
    key='taobao_helpers',
    module_file='taobao_helpers.py',
    doc=('淘宝发布的无状态部分：发布开关的解析与校验、从商品记录构造请求载荷，以及它们用到的常量。\n\n'
         '这里的函数只依赖入参和标准库，不碰任务字典、锁、账户、浏览器和 Flask 请求上下文——所以能脱离账户状态直接单测。'
         '需要这些的逻辑在 ``taobao_service.TaobaoPublishService``。\n\n'
         '函数名保持 app.py 里的原名（含下划线前缀），便于新旧对照。'),
    consts=['TAOBAO_LISTING_MODES', '_CATEGORY_LABELS'],
    module_funcs=['_parse_taobao_publish_options', '_taobao_product_from_record'],
)

# ------------------------------------------------------------------------------------------ 服务类
# 旧函数名 -> 方法名。路由要调用的是公开名；``_load_taobao_pipeline`` 也改成公开名，测试要替换它。
SERVICE_METHODS = {
    '_load_taobao_desktop': 'load_desktop',
    '_load_taobao_pipeline': 'load_pipeline',
    '_taobao_cdp_list_url': 'cdp_list_url',
    '_ensure_taobao_fill_browser': 'ensure_fill_browser',
    '_taobao_product_request_payload': 'product_request_payload',
    '_run_taobao_publish_task': 'run_publish_task',
    '_run_taobao_publish_batch_task': 'run_publish_batch_task',
}

# 服务类从应用入口拿到的东西：旧的全局名 -> 实例属性
SERVICE_INJECTED = {
    'Record': 'self._record_model',
    'repo_root': 'self._repo_root',
    '_active_shop_account': 'self._accounts.active_account',
    '_resolve_active_shop_browser': 'self._shop_service.resolve_active_browser',
    '_activate_shop_profile': 'self._shop_service.activate_profile',
    '_normalize_debug_address': 'self._normalize_debug_address',
    'resolve_data_file': 'self._resolve_data_file',
    '_bootstrap_log': 'self._bootstrap_log',
}
# 原来的模块全局状态 -> 实例属性
SERVICE_STATE = [
    ('_taobao_tasks', 'self.tasks'),
    ('_taobao_tasks_lock', 'self.lock'),
]

_SERVICE_NAME_MAP = {old: 'self.' + new for old, new in SERVICE_METHODS.items()}
_SERVICE_NAME_MAP.update(SERVICE_INJECTED)
_SERVICE_NAME_MAP.update(dict(SERVICE_STATE))

HELPER_IMPORTS = {
    '_parse_taobao_publish_options': 'from .taobao_helpers import _parse_taobao_publish_options',
    '_taobao_product_from_record': 'from .taobao_helpers import _taobao_product_from_record',
}

SLICES['taobao_service'] = Slice(
    key='taobao_service',
    module_file='taobao_service.py',
    doc=('淘宝发布服务：任务字典与互斥锁、淘宝模块的延迟加载、当前淘宝账户的浏览器地址、素材中心浏览器的拉起、'
         '界面资料 → 流水线请求的翻译、单品发布与批量发布的后台 worker。\n\n'
         '任务字典 ``tasks`` 和互斥锁 ``lock`` 原来是 ``app.py`` 的模块全局（``_taobao_tasks`` / ``_taobao_tasks_lock``），'
         '现在是 ``TaobaoPublishService`` 实例的属性，由应用入口创建一次。\n\n'
         '这个类不导入 ``src.utils`` / DrissionPage / ``app.py``，也不在导入时加载 ``taobao_publish`` 包'
         '（``load_desktop`` / ``load_pipeline`` 在请求里才加载，缺依赖只让淘宝接口不可用，不影响 Sidecar 启动）；'
         '账户门禁、店铺会话、路径解析、日志都由应用入口注入。\n\n'
         '与 app.py 旧名字的对应：\n'
         + '\n'.join('  %-42s -> %s' % (old, new) for old, new in (
             [(old, 'TaobaoPublishService.' + new) for old, new in SERVICE_METHODS.items()]
             + [('_taobao_tasks / _taobao_tasks_lock', 'tasks / lock'),
                ('_active_shop_account', 'accounts.active_account'),
                ('_resolve_active_shop_browser', 'shop_service.resolve_active_browser'),
                ('_activate_shop_profile', 'shop_service.activate_profile')]))),
    class_name='TaobaoPublishService',
    class_doc=('一个应用一个实例，持有淘宝发布任务的全部进程内状态。\n\n'
               '    ``record_model`` 是商品表；``repo_root`` 用来在源码运行时把 ``taobao-publisher`` 放进 sys.path；\n'
               '    ``accounts`` 是 ``ShopAccountGuard``（当前账户），``shop_service`` 是 ``ShopSessionService``（取 / 拉起账户的浏览器）；\n'
               '    ``normalize_debug_address`` 在 src.utils 里（会连带导入浏览器库），所以注入；\n'
               '    ``resolve_data_file`` 决定图片目录记录落在哪个数据目录；``bootstrap_log`` 是应用入口的启动日志。'),
    class_params=['record_model', 'repo_root', 'accounts', 'shop_service', 'normalize_debug_address',
                  'resolve_data_file', 'bootstrap_log'],
    wrap_init=True,
    init_lines=[
        'self._record_model = record_model',
        'self._repo_root = repo_root',
        'self._accounts = accounts',
        'self._shop_service = shop_service',
        'self._normalize_debug_address = normalize_debug_address',
        'self._resolve_data_file = resolve_data_file',
        'self._bootstrap_log = bootstrap_log',
    ],
    state_assigns=SERVICE_STATE,
    funcs=list(SERVICE_METHODS),
    name_map=_SERVICE_NAME_MAP,
    per_func={old: {'new_name': new} for old, new in SERVICE_METHODS.items()},
    import_overrides=HELPER_IMPORTS,
    doc_edits={'_taobao_product_request_payload': [
        # 原文把它叫「纯函数」，但标题 / 导购标题的长度规则要经 load_desktop() 读本地契约；搬成服务方法后这句话更容易误导
        ('**纯函数，便于单测。**',
         '**不碰任务表和锁，便于单测**（标题 / 导购标题的长度规则要经 ``load_desktop`` 读本地契约）。'),
    ]},
    comment_edits=[
        # 这两处注释提到「测试会 exec 本函数」：测试现在直接构造真实服务对象调用本方法，不再从 app.py 里抽函数 exec
        ('# 会 exec 本函数并**真的调用它**（`:300`、`:315`）——所以必须在收尾还原，',
         '# 会构造真实的服务对象并**真的调用本方法**——所以必须在收尾还原，'),
        ('# 而测试会 exec 本函数并真的调用它。不还原 = 把 `protocol` 泄漏给同一进程里',
         '# 而测试会真的调用本方法。不还原 = 把 `protocol` 泄漏给同一进程里'),
    ],
    app_import='from src.sidecar.taobao_service import TaobaoPublishService',
    insert_after=[('shop_session_service', (
        'taobao_service = TaobaoPublishService(\n'
        '    record_model=Record, repo_root=repo_root, accounts=shop_accounts, shop_service=shop_session_service,\n'
        '    normalize_debug_address=_normalize_debug_address, resolve_data_file=resolve_data_file,\n'
        '    bootstrap_log=_bootstrap_log,\n'
        ')'
    ))],
    app_edits=[
        # 账户门禁别名：淘宝发布是 ``_account_change_blocked`` 的唯一使用者，随它一起搬走
        ('# 账户门禁的实现在 src/sidecar/shop_accounts.py。上传 / 淘宝 / 小红书 / 保存等业务域还留在本文件，\n',
         '# 账户门禁的实现在 src/sidecar/shop_accounts.py。上传 / 小红书 / 保存等业务域还留在本文件，\n'),
        ('_account_change_blocked = shop_accounts.account_change_blocked\n', ''),
        # 店铺会话别名：同理，淘宝填表流程是它们的唯一使用者
        ('# 淘宝填表流程还在本文件，继续按原来的函数名使用；它拆出去时再改为直接依赖 shop_session_service。\n'
         '_resolve_active_shop_browser = shop_session_service.resolve_active_browser\n'
         '_activate_shop_profile = shop_session_service.activate_profile\n', ''),
        # 「有没有发布任务在跑」「编辑保护」「保存时校验标题」「更新器的任务检查」：改为直接读 taobao_service
        ('    with _taobao_tasks_lock:\n'
         '        running = running or any(task.get(\'status\') in (\'pending\', \'running\')\n'
         '                                 for task in _taobao_tasks.values())\n',
         '    with taobao_service.lock:\n'
         '        running = running or any(task.get(\'status\') in (\'pending\', \'running\')\n'
         '                                 for task in taobao_service.tasks.values())\n'),
        ('    for tasks, lock in ((_upload_tasks, _upload_tasks_lock), (_taobao_tasks, _taobao_tasks_lock)):\n',
         '    for tasks, lock in ((_upload_tasks, _upload_tasks_lock), (taobao_service.tasks, taobao_service.lock)):\n'),
        ("            _taobao_product_request_payload({'title': updates['title']})\n",
         "            taobao_service.product_request_payload({'title': updates['title']})\n"),
        ('    with _taobao_tasks_lock:\n'
         '        taobao = sum(t.get(\'status\') in (\'pending\', \'running\') for t in _taobao_tasks.values())\n',
         '    with taobao_service.lock:\n'
         '        taobao = sum(t.get(\'status\') in (\'pending\', \'running\') for t in taobao_service.tasks.values())\n'),
    ],
)

# ------------------------------------------------------------------------------------------ 路由
_ROUTES_NAME_MAP = {
    'app': 'current_app',                                  # app.logger -> current_app.logger（请求线程里有应用上下文）
    '_load_taobao_desktop': 'service.load_desktop',
    '_taobao_cdp_list_url': 'service.cdp_list_url',
    '_ensure_taobao_fill_browser': 'service.ensure_fill_browser',
    '_taobao_product_request_payload': 'service.product_request_payload',
    '_run_taobao_publish_task': 'service.run_publish_task',
    '_run_taobao_publish_batch_task': 'service.run_publish_batch_task',
    '_taobao_tasks': 'service.tasks',
    '_taobao_tasks_lock': 'service.lock',
    '_active_shop_account': 'accounts.active_account',
    '_require_publish_platform': 'accounts.require_publish_platform',
    '_account_change_blocked': 'accounts.account_change_blocked',
    '_require_product_revision': 'require_product_revision',
}

SLICES['taobao_routes'] = Slice(
    key='taobao_routes',
    module_file='taobao_routes.py',
    doc=('淘宝发布接口（/api/taobao/*）：就绪度 / 资料检查 / 导出资料包 / 启动发布 / 批量发布 / 进度 / 取消 / 任务列表。\n\n'
         '这些接口只做 HTTP 适配和请求校验；任务字典、互斥锁、淘宝模块的加载、浏览器和 worker 在 ``TaobaoPublishService``，'
         '账户门禁在 ``ShopAccountGuard``，发布开关的解析在 ``taobao_helpers``。\n\n'
         '与 app.py 旧名字的对应：\n'
         '  _taobao_product_request（请求体解析）-> create_taobao_blueprint 里的同名小函数\n'
         '  _with_shop_account_lock / _require_publish_platform / _account_change_blocked / _active_shop_account\n'
         '                                       -> accounts.with_lock / require_publish_platform / account_change_blocked / active_account\n'
         '  _require_product_revision            -> 工厂参数 require_product_revision（保存商品、抖店上传也在用，留在应用入口）'),
    factory='create_taobao_blueprint',
    blueprint_name='taobao',
    params=['service', 'accounts', 'record_model', 'resolve_data_file', 'require_product_revision'],
    aliases=['Record = record_model'],
    factory_doc=('``service`` 是 ``TaobaoPublishService``（任务状态、淘宝模块、浏览器、worker）；``accounts`` 是 ``ShopAccountGuard``'
                 '（账户锁与平台门禁）；\n'
                 '    ``record_model`` 是商品表；``resolve_data_file`` 决定资料包落在哪个数据目录；'
                 '``require_product_revision`` 校验界面带来的商品资料版本（保存商品、抖店上传也在用，所以留在应用入口）。'),
    funcs=['_taobao_product_request', 'taobao_readiness', 'taobao_prepare', 'taobao_export', 'taobao_publish_start',
           'taobao_publish_start_all', 'taobao_publish_status', 'taobao_publish_cancel', 'taobao_publish_tasks'],
    name_map=_ROUTES_NAME_MAP,
    decorator_name_map={'app': 'routes', '_with_shop_account_lock': 'accounts.with_lock'},
    import_overrides=dict(HELPER_IMPORTS, current_app='from flask import current_app'),
    comment_edits=[
        # 这两处注释点名了已经不存在的全局名 / 函数名，改成现在的写法
        ('# ⚠️ **准入检查只有一处，在下面拿 `_taobao_tasks_lock` 的那个块里**（与"插入任务"同一把锁）。',
         '# ⚠️ **准入检查只有一处，在下面拿 `service.lock` 的那个块里**（与"插入任务"同一把锁）。'),
        ('# 在锁内被 409 挡下。这个代价是**刻意接受**的——`_ensure_taobao_fill_browser()`',
         '# 在锁内被 409 挡下。这个代价是**刻意接受**的——`service.ensure_fill_browser()`'),
    ],
    app_import='from src.sidecar.taobao_routes import create_taobao_blueprint',
    registration=('app.register_blueprint(create_taobao_blueprint(\n'
                  '    service=taobao_service, accounts=shop_accounts, record_model=Record,\n'
                  '    resolve_data_file=resolve_data_file, require_product_revision=_require_product_revision,\n'
                  '))\n'),
)

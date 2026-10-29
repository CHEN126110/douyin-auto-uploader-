# -*- coding: utf-8 -*-
"""本地文件夹导入（/api/import/folders）与小红书批量填表（/api/xhs/fill-batch 等）的搬迁规格（2026-10-20）。

两个域都很小、几乎不与别的域共享函数：导入只依赖 Record 和 ``split_number_prefix``（后者在 src.utils 里，
而 src.utils 会连带导入浏览器库，所以由应用入口注入）；小红书批量填表见下方的 ``xhs_batch``。
"""
from slice_tool import Slice

SLICES = {}

# ------------------------------------------------------------------------------------------ 本地文件夹导入
SLICES['import_folders'] = Slice(
    key='import_folders',
    module_file='import_routes.py',
    doc=('本地文件夹导入接口（/api/import/folders）：把含 SKU 图片的文件夹整理成商品记录。\n\n'
         '每个文件夹里要有名字含 ``SKU`` 的子目录；其中的图片文件名决定 SKU 名称，同名（忽略大小写）只保留第一个。'),
    factory='create_import_blueprint',
    blueprint_name='folder_import',
    params=['record_model', 'split_number_prefix'],
    aliases=['Record = record_model'],
    factory_doc=('``split_number_prefix`` 由应用入口注入：它在 ``src.utils`` 里，而 ``src.utils`` 会连带导入浏览器库，'
                 '接口模块不该为一个 8 行的纯函数依赖它。'),
    module_funcs=['_find_sku_folder', '_collect_image_files', '_dedup_sku_list', '_build_duplicate_groups'],
    funcs=['_derive_sku_name', 'import_folders'],
    name_map={'app': 'current_app'},
    import_overrides={'current_app': 'from flask import current_app'},
    app_import='from src.sidecar.import_routes import create_import_blueprint',
    registration=('app.register_blueprint(create_import_blueprint(\n'
                  '    record_model=Record, split_number_prefix=split_number_prefix,\n'
                  '))\n'),
)

# ------------------------------------------------------------------------------------------ 小红书批量填表
# 必须按 xhs_batch_service -> xhs_batch_routes 的顺序链式运行。
SLICES['xhs_batch_service'] = Slice(
    key='xhs_batch_service',
    module_file='xhs_batch_service.py',
    doc=('小红书千帆批量填表服务：任务字典与锁、批量 worker、已结束任务的清理，以及从 Record 取图片 / 类目 / 调试端口。\n\n'
         '任务字典是进程内的，所以属于 ``XhsBatchService`` 实例（由应用入口创建一次），不再是 ``app.py`` 的模块全局；\n'
         '真正去填表的 ``default_runner`` 仍在 ``xhs_routes`` 里按调用时延迟导入，本模块不导入浏览器库、不反向导入 app.py。\n\n'
         '与 app.py 旧函数名的对应：\n'
         '  _xhs_tasks / _xhs_tasks_lock      -> XhsBatchService.tasks / lock\n'
         '  _xhs_images_from_record           -> XhsBatchService.images_from_record\n'
         '  _xhs_category_from_record         -> XhsBatchService.category_from_record\n'
         '  _run_xhs_fill_batch_task          -> XhsBatchService.run_fill_batch_task\n'
         '  _prune_xhs_tasks_locked           -> XhsBatchService.prune_finished_locked\n'
         '  _xhs_debug_port                   -> XhsBatchService.debug_port\n'
         '  _XHS_DEFAULT_SERVICE_VALUES       -> XhsBatchService.DEFAULT_SERVICE_VALUES'),
    consts=['_XHS_CATEGORY_LABELS', '_XHS_DEFAULT_SERVICE_VALUES', 'XHS_TASK_KEEP_FINISHED',
            'XHS_TASK_FINISHED_TTL_HOURS'],
    class_name='XhsBatchService',
    class_doc=('一个应用一个实例，持有批量填表的任务字典和锁。\n\n'
               '    ``record_model`` 是商品表；``get_pic_list`` 取商品目录里的图片（在 src.utils 里，会连带导入浏览器库，所以注入）；\n'
               '    ``shop_session`` 提供小红书页面域名；``host`` / ``port_start`` / ``port_end`` 是账户浏览器的调试地址和端口段。'),
    class_params=['record_model', 'get_pic_list', 'shop_session', 'host', 'port_start', 'port_end'],
    init_lines=[
        'self._record_model = record_model',
        'self._get_pic_list = get_pic_list',
        'self._shop_session = shop_session',
        'self._host = host',
        'self._port_start = port_start',
        'self._port_end = port_end',
    ],
    state_assigns=[('_xhs_tasks', 'self.tasks'), ('_xhs_tasks_lock', 'self.lock')],
    class_extra=(
        '    #: 路由层要用的默认服务信息取值（模块常量的只读引用）。\n'
        '    DEFAULT_SERVICE_VALUES = _XHS_DEFAULT_SERVICE_VALUES\n'
    ),
    funcs=['_xhs_images_from_record', '_xhs_category_from_record', '_run_xhs_fill_batch_task',
           '_prune_xhs_tasks_locked', '_xhs_debug_port'],
    name_map={
        '_xhs_tasks': 'self.tasks',
        '_xhs_tasks_lock': 'self.lock',
        'Record': 'self._record_model',
        'get_pic_list': 'self._get_pic_list',
        'shop_session': 'self._shop_session',
        '_SHOP_BROWSER_PORT_START': 'self._port_start',
        '_SHOP_BROWSER_PORT_END': 'self._port_end',
        '_DEBUG_BROWSER_HOST': 'self._host',
        '_xhs_images_from_record': 'self.images_from_record',
        '_xhs_category_from_record': 'self.category_from_record',
        '_xhs_debug_port': 'self.debug_port',
    },
    per_func={
        '_xhs_images_from_record': {'new_name': 'images_from_record'},
        '_xhs_category_from_record': {'new_name': 'category_from_record'},
        '_run_xhs_fill_batch_task': {'new_name': 'run_fill_batch_task'},
        '_prune_xhs_tasks_locked': {'new_name': 'prune_finished_locked'},
        '_xhs_debug_port': {'new_name': 'debug_port'},
    },
    app_import='from src.sidecar.xhs_batch_service import XhsBatchService',
    insert_after=[('_active_update_tasks', (
        'xhs_batch = XhsBatchService(\n'
        '    record_model=Record, get_pic_list=get_pic_list, shop_session=shop_session,\n'
        '    host=_DEBUG_BROWSER_HOST, port_start=_SHOP_BROWSER_PORT_START, port_end=_SHOP_BROWSER_PORT_END,\n'
        ')'
    ))],
    app_edits=[
        ("    payload['port'] = _xhs_debug_port(payload.get('port'))",
         "    payload['port'] = xhs_batch.debug_port(payload.get('port'))"),
        ('    return _probe(port=_xhs_debug_port())', '    return _probe(port=xhs_batch.debug_port())'),
    ],
)

SLICES['xhs_batch_routes'] = Slice(
    key='xhs_batch_routes',
    module_file='xhs_batch_routes.py',
    doc=('小红书千帆批量填表接口（/api/xhs/fill-batch、fill-status、fill-cancel）：依次对 status=0 的商品只填表、不提交。\n\n'
         '这些接口只做 HTTP 适配；任务字典和 worker 在 ``XhsBatchService``。和 ``xhs_routes`` 一样，这里**没有任何提交 / 保存草稿 / 上架类路由**。'),
    factory='create_xhs_batch_blueprint',
    blueprint_name='xhs_batch',
    params=['record_model', 'service', 'accounts'],
    aliases=['Record = record_model'],
    factory_doc=('``service`` 是 ``XhsBatchService``（任务字典与 worker），``accounts`` 是 ``ShopAccountGuard``\n'
                 '    （当前账户不是小红书千帆就不让进这条路线）。'),
    funcs=['xhs_fill_batch', 'xhs_fill_status', 'xhs_fill_cancel'],
    name_map={
        '_require_publish_platform': 'accounts.require_publish_platform',
        '_xhs_tasks': 'service.tasks',
        '_xhs_tasks_lock': 'service.lock',
        '_prune_xhs_tasks_locked': 'service.prune_finished_locked',
        '_run_xhs_fill_batch_task': 'service.run_fill_batch_task',
        '_XHS_DEFAULT_SERVICE_VALUES': 'service.DEFAULT_SERVICE_VALUES',
    },
    app_import='from src.sidecar.xhs_batch_routes import create_xhs_batch_blueprint',
    registration=('app.register_blueprint(create_xhs_batch_blueprint(\n'
                  '    record_model=Record, service=xhs_batch, accounts=shop_accounts,\n'
                  '))\n'),
)


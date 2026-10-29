# -*- coding: utf-8 -*-
"""各业务域的搬迁规格。"""
from slice_tool import Slice

SLICES = {}

SLICES['ai'] = Slice(
    key='ai',
    module_file='ai_routes.py',
    doc='发布优化 LLM 配置与连通性接口（/api/ai/*）。\n\n外部 AI 对运营闭环是禁用的（见 ``AI_POLICY``）；这里只服务「发布优化」所允许的厂商。',
    factory='create_ai_blueprint',
    blueprint_name='ai',
    funcs=['get_ai_config', 'save_ai_config', 'test_ai_connection', 'list_ai_models'],
    factory_doc='不需要注入依赖：设置、LLM 客户端都直接来自 src 下的轻量模块。',
    app_import='from src.sidecar.ai_routes import create_ai_blueprint',
    registration='app.register_blueprint(create_ai_blueprint())\n',
)

SLICES['title'] = Slice(
    key='title',
    module_file='title_routes.py',
    doc='商品标题生成与热门关键词接口。\n\n其中智能标题 / 热门关键词两组返回的是模板与示例数据（AI 组件已移除），专业标题走 ``src.professional_title_generator``。',
    factory='create_title_blueprint',
    blueprint_name='title',
    params=['record_model'],
    aliases=['Record = record_model'],
    funcs=['generate_smart_title', 'generate_smart_title_enhanced', 'get_trending_keywords',
           'refresh_trending_keywords', 'generate_professional_title'],
    name_map={'app': 'current_app'},
    import_overrides={'current_app': 'from flask import current_app', 'time': 'import time'},
    app_import='from src.sidecar.title_routes import create_title_blueprint',
    registration='app.register_blueprint(create_title_blueprint(record_model=Record))\n',
)


SLICES['settings'] = Slice(
    key='settings',
    module_file='settings_routes.py',
    doc='用户设置接口（/settings*）：读取 / 保存 / 重置设置、发布模式、水洗标 / 吊牌图管理。',
    factory='create_settings_blueprint',
    blueprint_name='settings',
    params=['get_runtime_data_path'],
    factory_doc='``get_runtime_data_path`` 由应用入口注入：它决定设置与素材落在哪个数据目录。',
    consts=['_AUTOMATION_ASSETS_DIR_NAME', '_WASH_LABEL_TAG_IMAGE_BASENAME',
            '_ALLOWED_AUTOMATION_IMAGE_EXTENSIONS'],
    module_funcs=['_is_path_within_dir', '_settings_to_payload'],
    funcs=['_get_automation_assets_dir', '_delete_managed_automation_image_files',
           '_resolve_managed_automation_image_path', '_delete_managed_wash_label_tag_image_files',
           '_resolve_managed_wash_label_tag_image_path', 'get_settings', 'update_settings',
           'import_automation_wash_label_tag_image', 'preview_automation_wash_label_tag_image',
           'remove_automation_wash_label_tag_image', 'publish_mode', 'reset_settings'],
    app_import='from src.sidecar.settings_routes import create_settings_blueprint',
    registration='app.register_blueprint(create_settings_blueprint(get_runtime_data_path=get_runtime_data_path))\n',
)

SLICES['pricing'] = Slice(
    key='pricing',
    module_file='pricing_routes.py',
    doc='智能定价与成本配置接口（/api/pricing/*）。',
    factory='create_pricing_blueprint',
    blueprint_name='pricing',
    params=['record_model', 'get_runtime_data_path'],
    aliases=['Record = record_model'],
    factory_doc='``get_runtime_data_path`` 由应用入口注入：它决定 pricing_config.json 落在哪个数据目录。',
    consts=['DEFAULT_PRICING_TEMPLATE'],
    module_funcs=['_pricing_cost_items'],
    funcs=['_load_pricing_config', '_save_pricing_config', 'calculate_smart_prices', 'save_cost_config',
           'force_reload_pricing_config', 'get_pricing_config', 'add_cost_item', 'update_cost_item',
           'delete_cost_item', 'get_cost_items', 'get_pricing_templates', 'save_profit_margin_config'],
    name_map={'app': 'current_app'},
    import_overrides={'current_app': 'from flask import current_app'},
    app_import='from src.sidecar.pricing_routes import create_pricing_blueprint',
    registration=('app.register_blueprint(create_pricing_blueprint(\n'
                  '    record_model=Record, get_runtime_data_path=get_runtime_data_path,\n'
                  '))\n'),
)


# 店铺会话 + 调试浏览器（2026-10-19）：五个切片，必须链式运行，见 slice_defs_shop_debug.py
from slice_defs_shop_debug import SLICES as _SHOP_DEBUG_SLICES  # noqa: E402

SLICES.update(_SHOP_DEBUG_SLICES)


# 本地文件夹导入 + 小红书批量填表（2026-10-20），见 slice_defs_import_xhs.py
from slice_defs_import_xhs import SLICES as _IMPORT_XHS_SLICES  # noqa: E402

SLICES.update(_IMPORT_XHS_SLICES)


# 链接采集（2026-10-20）：三个切片，必须按 capture_helpers → capture_service → capture_routes 链式运行，见 slice_defs_capture.py
from slice_defs_capture import SLICES as _CAPTURE_SLICES  # noqa: E402

SLICES.update(_CAPTURE_SLICES)


# 淘宝发布（2026-10-20）：三个切片，必须按 taobao_helpers → taobao_service → taobao_routes 链式运行，见 slice_defs_taobao.py
from slice_defs_taobao import SLICES as _TAOBAO_SLICES  # noqa: E402

SLICES.update(_TAOBAO_SLICES)


# 抖店上传（2026-10-21）：第一步 upload_steps（页面级操作），第二步见 slice_defs_upload.py
from slice_defs_upload import SLICES as _UPLOAD_SLICES  # noqa: E402

SLICES.update(_UPLOAD_SLICES)


# 抖店上传第二步（2026-10-21）：服务侧，必须在第一步之后按 upload_service → upload_routes 链式运行，见 slice_defs_upload_service.py
from slice_defs_upload_service import SLICES as _UPLOAD_SERVICE_SLICES  # noqa: E402

SLICES.update(_UPLOAD_SERVICE_SLICES)

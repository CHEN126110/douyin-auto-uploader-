# -*- coding: utf-8 -*-
"""抖店上传（/api/upload/*、/api/protocol/fxg/*、/start）的搬迁规格（2026-10-21）：分两步，这个文件现在只有第一步。

第一步  upload_steps   发布页的页面级操作（62 个函数 + 1 个异常类 + 13 个常量）。
                       整个闭包里有 65 个定义（64 个函数 + 1 个异常类）「不碰任何服务状态」——不读写任务字典 / 锁 / ``gui`` / 账户别名 / 路径与端口常量，
                       也不调用会碰这些状态的函数（``lab`` 里用「状态名 + 调用者传递闭包」算出来的，不是凭印象分的）。
                       它们只靠入参里的标签页对象、标准库、``src.utils`` 里的浏览器工具和本模块常量工作，所以原样搬成模块级函数，
                       **不需要任何改写**——函数体逐字不动，``verify`` 重放的改写规则是空的。
                       其中 ``_serialize_upload_task``（任务的 JSON 化）和 ``_normalize_protocol_category_keywords``
                       （协议流水线的类目词规整）不是页面操作，留给第二步放进任务服务模块。
第二步  upload_service / upload_routes（任务字典 + 锁 + 浏览器会话 + 两条流水线 + 八个接口），见后续切片。

留在 app.py 的、第一步之后要从 upload_steps 导入的：``app_import`` 里那一串——是搬迁后 app.py 里仍被引用的名字
（流水线函数调用的步骤、被调试浏览器默认地址引用的 ``_PUBLISH_CREATE_URL``、登录等待常量、``_dismiss_interfering_overlays``
的交互恢复钩子注册）。

这个模块直接导入 ``src.utils``（``allow_src_utils=True``）：页面操作本来就依赖那套浏览器工具，注入二十六个函数没有意义。
其余 ``src/sidecar`` 模块仍然不导入 ``src.utils``，需要页面操作时由 app.py 把函数作为端口注入。
"""
from slice_tool import Slice

SLICES = {}

# 62 个函数 + 1 个异常类；顺序无所谓，工具按 app.py 里的行号排序
STEP_FUNCS = [
    # 登录等待 / 素材准备 / 记录之间的停顿
    '_settle_between_records', '_wait_login_complete', '_prepare_record_assets',
    # 弹层、元素查找与点击的基础件
    '_dismiss_pending_browser_alert', '_build_overlay_button_selector', '_first_visible_selector_index',
    '_find_first_visible_element', '_click_element_safely', '_is_element_displayed', '_dismiss_interfering_overlays',
    '_get_current_tab_url', '_is_any_selector_visible', '_is_element_lost_error', '_field_exists', '_first_existing_field_name',
    # 页面阶段、打开发布页、标题
    '_detect_publish_page_stage', '_click_return_to_old_version', '_open_publish_page',
    '_get_title_input', '_find_title_brand_name_checkbox', '_checkbox_is_checked', '_ensure_title_brand_name_disabled',
    '_title_field_stable', '_fill_title_for_record',
    # 类目、属性、水洗标 / 吊牌
    '_select_category_and_prepare_attributes', '_fill_category_attributes',
    '_upload_wash_label_or_tag_image', '_wash_label_manual_material_tip_visible', '_wash_label_material_ocr_spinning',
    '_wash_label_needs_configured_material_fill', '_fill_fabric_material_if_wash_label_unrecognized',
    # 主图 / 白底图 / 详情图上传、AI 主图
    '_upload_main_images', '_find_ai_main_image_panel', '_find_ai_main_image_action', '_drive_ai_main_image_actions',
    '_wait_for_detail_upload_area_ready', '_normalize_upload_numeric_text', '_upload_media_assets',
    # 价格库存区、SKU 规格
    '_find_price_stock_root', '_scroll_to_price_stock_area', '_find_manual_sku_mode_button', '_ensure_manual_sku_entry_mode',
    '_configure_sku_entries', '_sku_color_type_exists', '_find_goods_spec_field', '_find_add_spec_type_button',
    '_find_pending_spec_type_selector', '_find_visible_spec_type_option', '_find_create_spec_type_entry',
    '_find_custom_spec_type_input', '_press_enter', '_ensure_color_sku_type', '_sku_size_has_uniform',
    '_find_size_value_picker', '_find_uniform_size_group', '_find_uniform_size_leaf', '_size_menu_candidates_text',
    '_uniform_size_leaf_checked', '_find_size_confirm_button', '_configure_sku_structure', '_fill_price_stock_and_delivery',
    # 提交发布及其结果判定
    'PublishUnconfirmedError', '_submit_publish',
]

STEP_CONSTS = [
    '_PUBLISH_CREATE_URL', '_PUBLISH_LOGIN_WAIT_SECONDS', '_PUBLISH_LOGIN_WAIT_POLL_SECONDS',
    '_INTERFERING_OVERLAY_TEXTS', '_VISIBLE_SELECTOR_PROBE_JS', '_PUBLISH_STEP1_SELECTORS', '_PUBLISH_STEP2_SELECTORS',
    '_PUBLISH_STAGE_PROBE_JS', '_WASH_LABEL_MANUAL_MATERIAL_TIP', '_PRICE_STOCK_ROW_SCAN_JS', '_SUBMIT_CONFIRM_TIMEOUT',
    '_SUBMIT_RESULT_BUTTONS', '_SUBMIT_STATE_PROBE_JS',
]

SLICES['upload_steps'] = Slice(
    key='upload_steps',
    module_file='upload_steps.py',
    doc=('抖店发布页（fxg.jinritemai.com/ffa/g/create）的页面级操作：清弹层、标题与品牌名、类目与属性、水洗标 / 吊牌、'
         '主图 / 白底图 / 详情图上传、SKU 规格、价格库存与发货、提交发布及其结果判定。\n\n'
         '这里的函数只靠入参里的标签页对象、标准库、``src.utils`` 里的浏览器工具和本模块常量工作，'
         '不碰任务字典、锁、账户、``gui`` 和 Flask 请求上下文——所以能脱离任务状态直接单测（用假的标签页对象）。'
         '任务生命周期、浏览器会话和流程编排在 ``upload_service.UploadService``，HTTP 在 ``upload_routes``。\n\n'
         '函数名保持 app.py 里的原名（含下划线前缀），便于新旧对照；函数体与搬迁前逐字相同。\n\n'
         '这个模块直接导入 ``src.utils``（页面操作本来就依赖那套浏览器工具）；其余 ``src/sidecar`` 模块不应导入它，'
         '需要页面操作时由应用入口把函数作为端口注入。'),
    module_funcs=STEP_FUNCS,
    consts=STEP_CONSTS,
    allow_src_utils=True,
    interleave=True,
    # 搬迁后 app.py 里仍被引用的名字（第一遍空跑后用 pyflakes 的 undefined name 数出来的，全部属于被搬走的集合）：
    # 两个常量（调试浏览器默认地址、登录等待）+ 15 个流水线要调用的步骤。
    app_import=('from src.sidecar.upload_steps import (\n'
                '    _PUBLISH_CREATE_URL,\n'
                '    _PUBLISH_LOGIN_WAIT_SECONDS,\n'
                '    _configure_sku_entries,\n'
                '    _configure_sku_structure,\n'
                '    _dismiss_interfering_overlays,\n'
                '    _dismiss_pending_browser_alert,\n'
                '    _fill_category_attributes,\n'
                '    _fill_price_stock_and_delivery,\n'
                '    _fill_title_for_record,\n'
                '    _open_publish_page,\n'
                '    _prepare_record_assets,\n'
                '    _select_category_and_prepare_attributes,\n'
                '    _settle_between_records,\n'
                '    _submit_publish,\n'
                '    _upload_main_images,\n'
                '    _upload_media_assets,\n'
                '    _wait_login_complete,\n'
                ')'),
    # `Decimal` 搬走前被模块级导入的全局名用着；搬走后 app.py 里只剩一处函数内的局部导入，模块级这行成了孤儿。
    # 工具按名字判断「还在用」所以没清掉，这里精确删一行（以 \n 开头，不会误伤缩进的局部导入）。
    app_edits=[('\nfrom decimal import Decimal\n', '\n')],
)

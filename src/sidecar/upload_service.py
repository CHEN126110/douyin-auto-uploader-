# -*- coding: utf-8 -*-
"""抖店上传服务：任务字典与互斥锁、发布浏览器会话、DOM 流水线、纯协议流水线、后台 worker、协议运行时配置探针、阶段耗时日志。

任务字典 ``tasks`` 和互斥锁 ``lock`` 原来是 ``app.py`` 的模块全局（``_upload_tasks`` / ``_upload_tasks_lock``），现在是 ``UploadService`` 实例的属性，由应用入口创建一次。

页面级操作（清弹层、填标题、传图、配 SKU、填价格库存、提交……）不在这里，在 ``upload_steps.py``，经 ``UploadStepsPort`` 注入；``src.utils`` 里的浏览器工具、CDP 探测、图片列表、计时经 ``UploadBrowserPort`` 注入。这个模块不导入 ``src.utils`` / DrissionPage / ``app.py``，导入它不会初始化浏览器。

与 app.py 旧名字的对应：
  _ensure_publish_session                -> UploadService.ensure_publish_session
  _execute_upload_flow                   -> UploadService.execute_upload_flow
  _resolve_upload_stop_before_submit     -> UploadService.resolve_stop_before_submit
  _run_upload_task                       -> UploadService.run_upload_task
  _run_fxg_runtime_options_probe         -> UploadService.run_fxg_runtime_options_probe
  _append_stage_timing_log / _run_stage_with_timing / _resolve_protocol_mcp_server_dir
  _load_upload_records / _load_upload_runtime_config / _find_cdp_port_with_jinritemai
  _ensure_protocol_browser / _execute_protocol_flow  -> 同名的私有方法
  _upload_tasks / _upload_tasks_lock     -> tasks / lock
  _normalize_protocol_category_keywords  -> 本模块的同名模块级函数"""
import copy
import json
import os
import shutil
import subprocess
import threading
import time as system_time
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from src.material_evidence import (
    MaterialEvidenceError,
    format_material_percentage,
    resolve_material_composition,
)
from src.professional_title_generator import sanitize_no_brand_title_text
from .debug_browser_service import debug_bool, debug_int
from .responses import api_error, api_ok


@dataclass(frozen=True)
class UploadStepsPort:
    """发布页的页面级操作（``upload_steps.py`` 里的函数），由应用入口一次性注入；流水线只通过它们碰页面。``create_url`` / ``login_wait_seconds`` 是发布页地址和等待登录的上限（常量也在 ``upload_steps.py``）。"""

    settle_between_records: Callable[..., Any]
    wait_login_complete: Callable[..., Any]
    prepare_record_assets: Callable[..., Any]
    dismiss_pending_browser_alert: Callable[..., Any]
    open_publish_page: Callable[..., Any]
    fill_title_for_record: Callable[..., Any]
    select_category_and_prepare_attributes: Callable[..., Any]
    fill_category_attributes: Callable[..., Any]
    upload_main_images: Callable[..., Any]
    upload_media_assets: Callable[..., Any]
    configure_sku_entries: Callable[..., Any]
    configure_sku_structure: Callable[..., Any]
    fill_price_stock_and_delivery: Callable[..., Any]
    submit_publish: Callable[..., Any]
    create_url: str
    login_wait_seconds: float


@dataclass(frozen=True)
class UploadBrowserPort:
    """流水线需要的浏览器与 CDP 能力，由应用入口一次性注入；本模块不导入 ``src.utils`` / DrissionPage。

    ``page_state`` 是无参函数，每次调用返回当前的共享页面状态（带 ``page`` 属性的对象），含义同 ``ShopBrowserPort.page_state``：
    必须每次取最新的 ``gui``，GUI 兼容模式启动后会把它重绑成 ``Gui`` 实例。``time`` 是 ``src.utils`` 里带计时的 sleep 提供者（``time.sleep``），不是标准库的 ``time``。
    ``record_automation_error`` / ``latest_error_after`` 来自 ``BrowserDebugService``；``attach_reusable_browser`` / ``find_cdp_port`` 还接在运营闭环 / 采集的装配上，所以留在 app.py。"""

    page_state: Callable[[], Any]
    open_page: Callable[..., Any]
    get_pic_list: Callable[..., Any]
    get_detail_pic_list: Callable[..., Any]
    reset_category_expanded_state: Callable[[], None]
    timer_start_session: Callable[..., Any]
    timer_end_session: Callable[[], Any]
    timer_record: Callable[..., Any]
    time: Any
    normalize_debug_address: Callable[[str], str]
    discover_debuggable_browsers: Callable[..., Any]
    fetch_cdp_page_targets: Callable[..., Any]
    is_logged_in_fxg_target_url: Callable[[str], bool]
    attach_reusable_browser: Callable[..., Any]
    find_cdp_port: Callable[[], Any]
    record_automation_error: Callable[..., Any]
    latest_error_after: Callable[..., Any]


def _normalize_protocol_category_keywords(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(',') if item.strip()]
    return []


class UploadService:
    """一个应用一个实例，持有抖店上传任务的全部进程内状态。

    ``record_model`` 是商品表；``accounts`` 是 ``ShopAccountGuard``（当前账户的 profile）；``browser`` / ``steps`` 是两个端口；
    ``settings_manager`` / ``shop_session`` 是设置管理器和账户注册表模块（测试里换成假件）；
    ``logger`` 是应用入口的 ``app.logger``——后台线程里没有 Flask 应用上下文，日志不能走 ``current_app``；
    ``get_app_root`` 决定打包后的资源根目录（白底图 / 调试产物也在用），``app_file`` / ``repo_root`` 是 app.py 自己的文件路径和仓库根
    （诊断日志、``sys.path`` 的推导依赖入口文件的位置，所以由入口传进来，不能在本模块里用 ``__file__``）；
    ``stage_timing_log_path`` 是阶段耗时日志的路径。"""

    def __init__(
            self, *,
            record_model,
            accounts,
            browser,
            steps,
            settings_manager,
            shop_session,
            logger,
            get_app_root,
            app_file,
            repo_root,
            stage_timing_log_path,
    ):
        self._record_model = record_model
        self._accounts = accounts
        self._browser = browser
        self._steps = steps
        self._settings_manager = settings_manager
        self._shop_session = shop_session
        self.logger = logger
        self._get_app_root = get_app_root
        self._app_file = app_file
        self._repo_root = repo_root
        self._stage_timing_log_path = stage_timing_log_path
        self.tasks = {}
        self.lock = threading.Lock()

    def _append_stage_timing_log(self, entry):
        try:
            with open(self._stage_timing_log_path, 'a', encoding='utf-8', errors='replace') as fp:
                fp.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except Exception:
            pass

    def _run_stage_with_timing(self, stage_timings, record, stage_name, func, *args, **kwargs):
        started_at = datetime.now().isoformat()
        perf_started_at = system_time.perf_counter()
        error_message = None
        result = None
        try:
            result = func(*args, **kwargs)
            return result
        except Exception as exc:
            error_message = str(exc)
            raise
        finally:
            duration_ms = round((system_time.perf_counter() - perf_started_at) * 1000, 2)
            stage_failed = bool(error_message) or result is False
            entry = {
                'type': 'stage',
                'captured_at': datetime.now().isoformat(),
                'started_at': started_at,
                'stage': stage_name,
                'duration_ms': duration_ms,
                'record_id': getattr(record, 'id', None),
                'record_name': getattr(record, 'name', ''),
                'status': 'failed' if stage_failed else 'ok',
                'error': error_message or ('stage returned False' if result is False else None),
            }
            stage_timings.append(entry)
            self._append_stage_timing_log(entry)
            print(f'[阶段耗时] {stage_name}: {duration_ms}ms')

    def _resolve_protocol_mcp_server_dir(self):
        explicit_dir = os.environ.get('DOUYIN_MCP_SERVER_DIR')
        if explicit_dir:
            return os.path.abspath(explicit_dir)

        source_project_root = os.path.abspath(os.path.join(os.path.dirname(self._app_file), '..', '..', '..'))
        candidates = [
            os.path.join(source_project_root, 'mcp-server'),
            os.path.join(self._get_app_root(), 'mcp-server'),
        ]
        for candidate in candidates:
            if os.path.isdir(candidate):
                return candidate
        return candidates[0]

    def run_fxg_runtime_options_probe(self, payload):
        mcp_dir = self._resolve_protocol_mcp_server_dir()
        script_path = os.path.join(mcp_dir, 'scripts', 'probe-fxg-runtime-options.mjs')
        if not os.path.isfile(script_path):
            raise RuntimeError(f'未找到运行时配置探针脚本: {script_path}')

        node_binary = os.environ.get('NODE_BINARY') or shutil.which('node')
        if not node_binary:
            raise RuntimeError('未找到 node 可执行文件，无法运行 MCP 探针。')

        category_keywords = _normalize_protocol_category_keywords(
            payload.get('category_keywords') or payload.get('categoryKeywords')
        )
        category_keyword = str(
            payload.get('category_keyword') or payload.get('categoryKeyword') or ''
        ).strip()
        category_id = str(payload.get('category_id') or payload.get('categoryId') or '').strip()
        if not category_keywords and not category_keyword and not category_id:
            raise ValueError('缺少类目关键词或类目 ID。')

        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        if category_keywords:
            env['CATEGORY_KEYWORDS'] = ','.join(category_keywords)
        if category_keyword:
            env['CATEGORY_KEYWORD'] = category_keyword
        if category_id:
            env['CATEGORY_ID'] = category_id
        if payload.get('cdp_list_url') or payload.get('cdpListUrl'):
            env['CDP_LIST_URL'] = str(payload.get('cdp_list_url') or payload.get('cdpListUrl')).strip()
        if payload.get('target_url_contains') or payload.get('targetUrlContains'):
            env['TARGET_HINT'] = str(payload.get('target_url_contains') or payload.get('targetUrlContains')).strip()
        if payload.get('operation_type') or payload.get('operationType'):
            env['OPERATION_TYPE'] = str(payload.get('operation_type') or payload.get('operationType')).strip()
        if payload.get('include_freight') is False or payload.get('includeFreight') is False:
            env['INCLUDE_FREIGHT'] = '0'

        timeout_seconds = debug_int(payload.get('timeout_seconds') or payload.get('timeoutSeconds'), 60, 5, 180)
        process = subprocess.run(
            [node_binary, script_path],
            cwd=mcp_dir,
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout_seconds,
            check=False,
        )
        if process.returncode != 0:
            stderr = (process.stderr or '').strip()
            stdout = (process.stdout or '').strip()
            raise RuntimeError(f'运行时配置探针失败: {stderr or stdout or process.returncode}')
        stdout = (process.stdout or '').strip()
        if not stdout:
            raise RuntimeError('运行时配置探针没有返回数据。')
        try:
            return json.loads(stdout)
        except Exception as exc:
            raise RuntimeError(f'运行时配置探针返回非 JSON 数据: {str(exc)}')

    def _load_upload_records(self, record_id=None):
        if record_id:
            record = self._record_model.get_or_none(self._record_model.id == record_id)
            if not record:
                return None, '指定产品不存在'
            return [record], None

        record_list = list(self._record_model.select().execute())
        if len(record_list) == 0:
            return None, '没有待上传数据！'
        return record_list, None

    def _load_upload_runtime_config(self):
        user_settings = self._settings_manager.get_settings()
        automation_config = self._settings_manager.normalize_automation_config(user_settings.automation_config)
        shipping_template_name = str(automation_config.get('shipping_template') or '中通包邮').strip() or '中通包邮'
        wash_label_tag_image_path = str(automation_config.get('wash_label_tag_image_path') or '').strip()
        configured_materials = []
        for item in automation_config.get('material_compositions') or []:
            if not isinstance(item, dict):
                continue
            material_name = str(item.get('material') or '').strip()
            percentage = item.get('percentage')
            if not material_name:
                continue
            try:
                percentage_text = format_material_percentage(percentage)
            except (TypeError, ValueError):
                percentage_text = ''
            configured_materials.append((material_name, percentage_text))
        configured_materials = [item for item in configured_materials if item[0] and item[1]]
        if not configured_materials:
            # 兼容历史配置的缺省值；只有商品本身没有材质证据时才允许使用。
            configured_materials = [('棉', '75'), ('氨纶', '25')]
        if wash_label_tag_image_path and not os.path.isfile(wash_label_tag_image_path):
            print(f'自动化设置中的水洗标/吊牌图不存在，已跳过: {wash_label_tag_image_path}')
            wash_label_tag_image_path = ''
        return shipping_template_name, configured_materials, wash_label_tag_image_path

    def _resolve_upload_materials(self, records, configured_materials):
        resolved = {}
        for record in records:
            try:
                decision = resolve_material_composition(record, configured_materials)
            except MaterialEvidenceError as exc:
                raise MaterialEvidenceError(f'{getattr(record, "name", "商品")}：{exc}') from exc
            resolved[record.id] = list(decision.materials)
            print(f'[材质] {record.name}：来源={decision.source}，内容={decision.text}')
        return resolved

    def ensure_publish_session(self, report_progress):
        opened_new_browser = False
        # 发布用哪个店铺，取决于用哪个 Chrome 用户数据目录。
        # 这里解析一次，后面所有 get_page 都用同一个，避免半路换店。
        active_profile = self._accounts.active_profile()

        if self._browser.page_state().page:
            try:
                current_tab = self._browser.page_state().page.get_tab(self._browser.page_state().page.latest_tab)
                current_url = str(current_tab.url or '')
            except Exception:
                current_url = ''
            if not self._browser.is_logged_in_fxg_target_url(current_url):
                reusable_tab = self._browser.attach_reusable_browser(report_progress)
                if reusable_tab is not None:
                    opened_new_browser = False

        if not self._browser.page_state().page:
            reusable_tab = self._browser.attach_reusable_browser(report_progress)
            if reusable_tab is None:
                report_progress(13, '正在打开浏览器并进入发布页面')
                try:
                    self._browser.page_state().page = self._browser.open_page(self._steps.create_url, profile_name=active_profile)
                    opened_new_browser = True
                except Exception as exc:
                    traceback.print_exc()
                    return None, f'浏览器启动失败：{exc}'

        try:
            main_tab = self._browser.page_state().page.get_tab(self._browser.page_state().page.latest_tab)
        except Exception:
            reusable_tab = self._browser.attach_reusable_browser(report_progress)
            if reusable_tab is not None:
                main_tab = reusable_tab
            else:
                report_progress(13, '正在重新打开浏览器并进入发布页面')
                try:
                    self._browser.page_state().page = self._browser.open_page(self._steps.create_url, profile_name=active_profile)
                    opened_new_browser = True
                except Exception as exc:
                    traceback.print_exc()
                    return None, f'浏览器恢复失败：{exc}'
                main_tab = self._browser.page_state().page.get_tab(self._browser.page_state().page.latest_tab)

        if not opened_new_browser:
            report_progress(13, '正在进入商品发布页面')
            try:
                self._steps.dismiss_pending_browser_alert(main_tab)
                main_tab.get(self._steps.create_url)
            except Exception as exc:
                try:
                    self._steps.dismiss_pending_browser_alert(main_tab)
                    main_tab.get(self._steps.create_url)
                except Exception:
                    traceback.print_exc()
                    return None, f'打开发布页面失败：{exc}'

        if not self._steps.wait_login_complete(main_tab, report_progress):
            return None, '等待登录超时（{} 秒内未检测到已登录的抖店页面），请在浏览器中完成登录后重新开始发布'.format(
                self._steps.login_wait_seconds
            )

        return main_tab, None

    def execute_upload_flow(self, record_id=None, progress_callback=None, stop_before_submit=False, task_id=None):
        """
        单条商品自动化流水线（顺序即耗时复盘基准）：
        open_publish_page → fill_title → upload_main_images → select_category → fill_category_attributes
        → upload_media_assets → configure_sku_entries → configure_sku_structure →（价格库存等）→ submit。
        显性固定停顿：每条 record 结束后 sleep(3)（防请求过快）；详情前 AI 主图分支内 sleep(3)；
        采集任务等非本流水线另有 sleep(2~3)。阶段耗时查运行目录下 upload-stage-timing.jsonl。
        """
        msg_list = []

        def _report_progress(progress, message):
            if not callable(progress_callback):
                return
            try:
                progress_callback(progress, message)
            except Exception:
                traceback.print_exc()

        try:
            # 读取发布模式
            user_settings = self._settings_manager.get_settings()
            ac = self._settings_manager.normalize_automation_config(user_settings.automation_config)
            publish_mode = ac.get('publish_mode', 'dom')
            print(f'[路由] 发布模式: {publish_mode}')

            # 官方API模式 (待实现)
            if publish_mode == 'official':
                return api_error(msg='官方API模式尚未实现，请在设置中切换为DOM或协议模式')

            # 读取记录和配置(所有模式共用)
            record_list, load_error = self._load_upload_records(record_id)
            if load_error:
                return api_error(msg=load_error)
            _report_progress(12, '已读取上传任务，正在初始化自动化参数')
            shipping_template_name, configured_materials, wash_label_tag_image_path = self._load_upload_runtime_config()
            try:
                # 两种发布模式都在碰浏览器之前核实材质，避免写入后才发现资料不完整。
                record_materials = self._resolve_upload_materials(record_list, configured_materials)
            except MaterialEvidenceError as exc:
                message = f'材质校验未通过：{exc}'
                _report_progress(12, message)
                return api_error(msg=message)

            # 纯协议模式：独立CDP连接，不需要DOM浏览器
            if publish_mode == 'protocol':
                print('[路由] 启动纯协议流水线...')
                import sys as _sys
                _base = _sys._MEIPASS if getattr(_sys, 'frozen', False) else os.path.dirname(os.path.abspath(self._app_file))
                _sys.path.insert(0, os.path.join(_base, 'protocol-research'))
                return self._execute_protocol_flow(
                    record_id=record_id,
                    progress_callback=progress_callback,
                    task_id=task_id,
                    stop_before_submit=stop_before_submit,
                    record_materials=record_materials,
                )

            # DOM模式：原有流程
            print('开始上传流程...')
            main_tab, session_error = self.ensure_publish_session(_report_progress)
            if session_error:
                return api_error(msg=session_error)
            _report_progress(15, '上传浏览器会话已就绪')

            for record in record_list:
                # 检查取消标志
                if task_id:
                    with self.lock:
                        t = self.tasks.get(task_id)
                        if t and t.get('cancelled'):
                            t['status'] = 'cancelled'
                            t['message'] = '任务已被用户取消'
                            t['finished_at'] = datetime.now().isoformat()
                            return api_ok(msg='任务已取消')

                # 类目展开状态是 src/utils.py 的模块级全局缓存，一旦置 True 就不再复位；
                # 不在每条记录开始时重置，第 2 个商品起类目属性区不会展开，
                # 品牌/适用人群/适用性别/筒高等字段全部定位不到。
                self._browser.reset_category_expanded_state()

                record_ok = False
                error_tip = ''
                stopped_before_submit = False
                current_stage = 'prechecks'
                stage_timings = []
                record_started_at = datetime.now().isoformat()
                record_perf_started_at = system_time.perf_counter()
                timer_session_id = f'upload_record_{getattr(record, "id", "unknown")}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
                self._browser.timer_start_session(timer_session_id)
                _report_progress(16, f'正在处理商品：{record.name}')

                try:
                    record_assets, error_tip = self._steps.prepare_record_assets(record)
                    if error_tip:
                        continue

                    current_stage = 'open_publish_page'
                    if not self._run_stage_with_timing(
                        stage_timings,
                        record,
                        current_stage,
                        self._steps.open_publish_page,
                        main_tab,
                        _report_progress,
                    ):
                        return api_error('页面未就绪，请稍后重试')

                    current_stage = 'fill_title'
                    self._run_stage_with_timing(
                        stage_timings,
                        record,
                        current_stage,
                        self._steps.fill_title_for_record,
                        main_tab,
                        record,
                    )

                    current_stage = 'upload_main_images'
                    _report_progress(32, '正在上传主图并选择类目')
                    self._run_stage_with_timing(
                        stage_timings,
                        record,
                        current_stage,
                        self._steps.upload_main_images,
                        main_tab,
                        record,
                        record_assets['main_pic_list'],
                    )

                    current_stage = 'select_category'
                    self._run_stage_with_timing(
                        stage_timings,
                        record,
                        current_stage,
                        self._steps.select_category_and_prepare_attributes,
                        main_tab,
                        record,
                        record_assets['diaopai_pic'],
                    )

                    current_stage = 'fill_category_attributes'
                    _report_progress(46, '正在填写类目属性与面料材质')
                    self._run_stage_with_timing(
                        stage_timings,
                        record,
                        current_stage,
                        self._steps.fill_category_attributes,
                        main_tab,
                        record,
                        record_materials[record.id],
                        record_assets['diaopai_pic'],
                        wash_label_tag_image_path,
                    )

                    current_stage = 'upload_media_assets'
                    _report_progress(60, '正在上传主图视频、白底图与详情图')
                    self._run_stage_with_timing(
                        stage_timings,
                        record,
                        current_stage,
                        self._steps.upload_media_assets,
                        main_tab,
                        record_assets['sub_pic_list'],
                        record_assets['my_video'],
                        record_assets['white_pic'],
                        record_assets['detail_pic_list'],
                    )

                    current_stage = 'configure_sku_entries'
                    _report_progress(74, '正在填写规格与SKU信息')
                    self._run_stage_with_timing(
                        stage_timings,
                        record,
                        current_stage,
                        self._steps.configure_sku_entries,
                        main_tab,
                        record_assets['sku_list'],
                        record.remark,
                        record,
                    )

                    current_stage = 'configure_sku_structure'
                    _report_progress(78, '正在选择码数')
                    self._run_stage_with_timing(
                        stage_timings,
                        record,
                        current_stage,
                        self._steps.configure_sku_structure,
                        main_tab,
                    )

                    current_stage = 'fill_price_and_stock'
                    _report_progress(84, '正在填写价格库存与发货配置')
                    self._run_stage_with_timing(
                        stage_timings,
                        record,
                        current_stage,
                        self._steps.fill_price_stock_and_delivery,
                        main_tab,
                        record,
                        record_assets['sku_list'],
                        shipping_template_name,
                    )

                    if stop_before_submit:
                        current_stage = 'stop_before_submit'
                        _report_progress(95, '已到提交前截停点，本次不会发布商品')
                        stopped_before_submit = True
                        record_ok = True
                        self._browser.timer_record('提交阶段', '提交前截停', 0, 0, True)
                    else:
                        current_stage = 'submit_publish'
                        _report_progress(95, '正在提交发布请求')
                        record_ok = self._run_stage_with_timing(
                            stage_timings,
                            record,
                            current_stage,
                            self._steps.submit_publish,
                            main_tab,
                            record,
                        )

                except Exception as e:
                    detailed_error = traceback.format_exc()
                    print('------------- 详细错误报告 -------------')
                    print(detailed_error)
                    print('------------------------------------')
                    try:
                        self._browser.record_automation_error(
                            current_stage,
                            e,
                            detailed_error,
                            tab=main_tab,
                            extra={
                                'record_id': record.id,
                                'record_name': record.name,
                                'stage_timings': copy.deepcopy(stage_timings),
                            }
                        )
                    except Exception:
                        traceback.print_exc()

                    if not error_tip:
                        error_tip = str(e)

                finally:
                    fi_arr = record.name.split('_')
                    fi_name_tuple = record.name if len(fi_arr) < 4 else fi_arr[3],
                    fi_name = fi_name_tuple[0] if isinstance(fi_name_tuple, tuple) else fi_name_tuple

                    if record_ok:
                        suffix = '（已截停未发布）' if stopped_before_submit else ''
                        msg_list.append(f'{fi_name} -> 操作成功{suffix}！')
                    else:
                        msg_list.append(f'{fi_name} -> 操作失败[{error_tip}]！')

                    record_duration_ms = round((system_time.perf_counter() - record_perf_started_at) * 1000, 2)
                    substep_summary = self._browser.timer_end_session()
                    self._append_stage_timing_log({
                        'type': 'record_summary',
                        'captured_at': datetime.now().isoformat(),
                        'started_at': record_started_at,
                        'record_id': getattr(record, 'id', None),
                        'record_name': getattr(record, 'name', ''),
                        'timer_session_id': timer_session_id,
                        'status': 'ok' if record_ok else 'failed',
                        'current_stage': current_stage,
                        'duration_ms': record_duration_ms,
                        'error': error_tip,
                        'stage_count': len(stage_timings),
                        'stage_timings': stage_timings,
                        'substep_summary': substep_summary,
                    })
                    print(f'[整单耗时] {record.name}: {record_duration_ms}ms')
                    self._steps.settle_between_records(main_tab)
        except:
            print('------------- 致误报告 -------------')
            print(traceback.format_exc())
            print('------------------------------------')
            msg_list.append('发生了一个意外的错误，请检查控制台日志。')

        _report_progress(98, '已完成自动化流程，正在汇总结果')
        combined_msg = chr(10).join(msg_list)
        if '操作失败' in combined_msg or '意外的错误' in combined_msg:
            return api_error(msg=combined_msg)
        return api_ok(msg=combined_msg)

    def resolve_stop_before_submit(self, data):
        payload = data or {}
        raw_stop = payload.get('stop_before_submit', payload.get('stopBeforeSubmit', True))
        stop_before_submit = debug_bool(raw_stop, True)
        confirm_final_publish = debug_bool(
            payload.get('confirm_final_publish', payload.get('confirmFinalPublish')),
            False,
        )

        if not stop_before_submit and not confirm_final_publish:
            raise ValueError('最终发布需要 confirm_final_publish=true；未确认时只能执行 stop_before_submit 预检')

        return stop_before_submit, confirm_final_publish

    def _find_cdp_port_with_jinritemai(self):
        """找出**已经打开抖店 tab** 的那个浏览器的调试端口。

        先按进程枚举：Chrome 的调试端口就写在命令行里，0.03 秒能拿全，
        而且不受端口范围限制——每份账号信息现在各占一个端口，写死范围一定会漏。
        枚举优先当前选中的那份账号信息，避免多店铺时抢到别人的浏览器。

        枚举不到才回退到探端口，且只探两个历史默认端口：
        逐个探 169 个端口本机实测要 68 秒，而我们自己启的浏览器枚举一定找得到。

        返回: 命中的端口；找不到返回 None
        """
        from urllib.request import urlopen as _urlopen

        def _has_fxg_tab(address):
            try:
                targets = self._browser.fetch_cdp_page_targets(address)
            except Exception:
                return False
            return any('jinritemai.com' in (t.get('url') or '') for t in targets)

        try:
            browsers = self._browser.discover_debuggable_browsers(verify=False)
            browsers = self._shop_session.filter_browsers_for_profile(browsers, self._accounts.active_profile())
        except Exception:
            browsers = []

        active_dir_marker = (self._accounts.active_profile() or '').lower()
        ordered = sorted(
            browsers,
            key=lambda b: active_dir_marker not in self._shop_session.browser_profile_text(b),
        )
        for browser in ordered:
            address = self._browser.normalize_debug_address(browser.get('debug_address') or '')
            if not address or not _has_fxg_tab(address):
                continue
            try:
                return int(address.rsplit(':', 1)[-1])
            except Exception:
                continue

        for port in (9222, 9223):
            try:
                targets = json.loads(_urlopen(f'http://127.0.0.1:{port}/json/list', timeout=0.4).read())
            except Exception:
                continue
            for t in targets:
                if 'jinritemai.com' in (t.get('url') or ''):
                    return port
        return None

    def _ensure_protocol_browser(self):
        """确保协议模式有可用的 Chrome 调试端口。
        优先复用已经打开抖店 tab 的浏览器；找不到才用 get_page() 启动新浏览器。
        返回: (cdp_port, browser_page)
        """
        # 1. 优先找已有抖店 tab 的端口（避开纯采集浏览器）
        port = self._find_cdp_port_with_jinritemai()
        if port:
            print(f'[协议] 复用已有抖店浏览器调试端口: {port}')
            return port, None

        # 2. 找不到才启新浏览器
        print('[协议] 未检测到带抖店 tab 的 Chrome，通过 DOM 流程启动浏览器...')
        try:
            from src.utils import get_page
            page = get_page('https://fxg.jinritemai.com', profile_name=self._accounts.active_profile())
            system_time.sleep(2)
            # 启动后再按"有抖店 tab"挑一次
            port = self._find_cdp_port_with_jinritemai() or self._browser.find_cdp_port()
            if port:
                print(f'[协议] 浏览器已启动，调试端口: {port}')
                return port, page
        except Exception as e:
            print(f'[协议] get_page() 启动失败: {e}')
            import traceback
            traceback.print_exc()

        return None, None

    def _execute_protocol_flow(self, record_id=None, progress_callback=None, task_id=None,
                               stop_before_submit=False, record_materials=None):
        """纯协议流水线 v4：CDP会话 + HTTP图片上传 + Schema获取 + 离线Body构造 + webpack提交"""
        import json as _json, sys as _sys
        if record_materials is None:
            # 直接调用协议服务也执行同一套校验，不能绕过主流程的材质安全闸。
            early_records, early_error = self._load_upload_records(record_id)
            if early_error:
                return api_error(msg=early_error)
            try:
                _default_materials = self._load_upload_runtime_config()[1]
            except Exception as exc:
                return api_error(msg=f'读取发布配置失败：{exc}')
            try:
                record_materials = self._resolve_upload_materials(early_records, _default_materials)
            except MaterialEvidenceError as exc:
                return api_error(msg=f'材质校验未通过：{exc}')
        if getattr(_sys, 'frozen', False):
            _base = _sys._MEIPASS
        else:
            _base = self._repo_root
        _sys.path.insert(0, os.path.join(_base, 'protocol-research-clean-20260505', 'scripts'))

        # === 自动启动浏览器 + 等待登录 ===
        _proto_port, _proto_page = self._ensure_protocol_browser()
        if not _proto_port:
            return api_error(msg='无法启动Chrome浏览器。请确保Chrome已安装，然后重试')

        # 等待用户登录（检查是否有有效的 jinritemai cookie）
        def _report(pct, msg):
            if progress_callback:
                try: progress_callback(pct, msg)
                except: pass

        _report(5, '检测登录状态...')
        from urllib.request import urlopen as _cdp_urlopen
        _logged_in = False
        for _wait_i in range(60):  # 最多等 2 分钟
            try:
                targets = json.loads(_cdp_urlopen(f'http://127.0.0.1:{_proto_port}/json/list', timeout=2).read())
                # 修复：移除 '/ffa/g/' 路径限制。
                # 原始逻辑要求 URL 必须含 /ffa/g/，导致用户在任意其他 fxg 子页面（如首页、设置页等）
                # 时 page_target 永远为 None，即使已登录也一直报"请在浏览器中登录"。
                # 只需满足：① 是 page 类型 tab ② URL 含 jinritemai.com ③ 非 devtools 页面
                page_target = next((
                    t for t in targets
                    if t.get('type') == 'page'
                    and 'jinritemai.com' in (t.get('url') or '')
                    and not (t.get('url') or '').startswith('devtools://')
                ), None)
                if page_target:
                    import websocket as _ws_login
                    # 合并到单个 WebSocket 连接：同时获取 cookies 和当前 href，避免两次连接竞争
                    ws = _ws_login.create_connection(page_target['webSocketDebuggerUrl'], timeout=5, suppress_origin=True)
                    ws.settimeout(3)
                    ws.send(json.dumps({'id': 1, 'method': 'Network.enable'}))
                    ws.send(json.dumps({'id': 2, 'method': 'Network.getAllCookies'}))
                    ws.send(json.dumps({'id': 3, 'method': 'Runtime.evaluate', 'params': {
                        'expression': 'window.location.href', 'returnByValue': True
                    }}))
                    dl = system_time.time() + 8
                    cookies_raw = None
                    page_url = ''
                    got_cookies = False
                    got_url = False
                    while system_time.time() < dl and not (got_cookies and got_url):
                        try:
                            raw = ws.recv()
                            msg = json.loads(raw)
                            if msg.get('id') == 2:
                                cookies_raw = msg.get('result', {}).get('cookies', [])
                                got_cookies = True
                            elif msg.get('id') == 3:
                                page_url = (msg.get('result', {}).get('result', {}) or {}).get('value', '')
                                got_url = True
                        except _ws_login.WebSocketTimeoutException:
                            continue
                        except Exception:
                            break
                    ws.close()

                    jinritemai_cookies = [c for c in (cookies_raw or []) if 'jinritemai.com' in (c.get('domain') or '')]
                    # 优先用 CDP eval 取到的精确 href；取不到时降级用 tab 列表里的 url
                    _cur_url = page_url or (page_target.get('url') or '')
                    self.logger.info(f'[登录检测] url={_cur_url[:80]} jinritemai_cookies={len(jinritemai_cookies)} wait={_wait_i+1}s')

                    if len(jinritemai_cookies) >= 3 and 'login' not in _cur_url.lower():
                        _logged_in = True
            except Exception as _le:
                self.logger.debug(f'[登录检测] 异常（忽略）: {_le}')

            if _logged_in:
                _report(10, '已登录，开始上传...')
                break

            _report(5, f'请在浏览器中登录抖店后台...({_wait_i+1}s)')
            system_time.sleep(2)

        if not _logged_in:
            return api_error(msg='登录超时。请在浏览器中打开 https://fxg.jinritemai.com 并登录后重试')
        # 设置环境变量让 v4 使用正确的端口
        os.environ['CDP_PORT'] = str(_proto_port)

        # === 文件日志诊断（写入 exe 同目录，确保可见） ===
        from datetime import datetime as _diag_dt
        # 在 frozen 模式下使用 exe 所在目录，dev 模式使用脚本目录
        if getattr(_sys, 'frozen', False):
            _diag_log_dir = os.path.dirname(_sys.executable)
        else:
            _diag_log_dir = os.path.dirname(os.path.abspath(self._app_file))
        _diag_log_path = os.path.join(_diag_log_dir, 'protocol_diag.log')
        def _diag(msg):
            try:
                with open(_diag_log_path, 'a', encoding='utf-8') as _f:
                    _f.write(f'{_diag_dt.now().isoformat()} | {msg}\n')
            except Exception as _diag_e:
                # 回退：写入用户临时目录
                try:
                    import tempfile as _tf
                    _fallback = os.path.join(_tf.gettempdir(), 'protocol_diag_fallback.log')
                    with open(_fallback, 'a', encoding='utf-8') as _f:
                        _f.write(f'{_diag_dt.now().isoformat()} | LOG_ERROR: {_diag_e} | {msg}\n')
                except:
                    pass
        _diag(f'START record_id={record_id} frozen={getattr(_sys, "frozen", False)} base={_base}')
        _diag(f'sys.path[0]={_sys.path[0]}')
        _diag(f'proto_dir_exists={os.path.isdir(os.path.join(_base, "protocol-research"))}')
        _diag(f'log_path={_diag_log_path}')

        _report(10, '协议模式：读取上传任务')
        record_list, load_error = self._load_upload_records(record_id)
        _diag(f'load_records: count={len(record_list) if record_list else 0} error={load_error}')
        if load_error:
            _diag(f'RETURN load_error: {load_error}')
            return api_error(msg=load_error)

        results = []
        total = len(record_list)

        for idx, record in enumerate(record_list):
            if task_id:
                with self.lock:
                    t = self.tasks.get(task_id)
                    if t and t.get('cancelled'):
                        t['status'] = 'cancelled'
                        t['message'] = '任务已被用户取消'
                        return api_ok(msg='任务已取消')

            _report(20 + int((idx/total)*70), f'协议模式：处理 {record.name} ({idx+1}/{total})')

            # 从record提取协议流水线需要的参数
            try:
                sku_list = _json.loads(record.content) if record.content else []
            except (_json.JSONDecodeError, TypeError):
                sku_list = []

            # 标题：优先 record.title，其次 record.name
            product_title = sanitize_no_brand_title_text(
                (record.title or '').strip() or (record.name or '').strip()
            ) or '协议发布商品'

            # 价格：从 SKU 中取第一个有效价格；若没有任何有效价格则中止该商品发布
            # 历史上这里 fallback 到 9.9 元，会让用户的高价商品被默默以 9.9 元提交，已撤销该兜底
            price_val = 0.0
            for s in (sku_list or []):
                try:
                    p = float(s.get('price', 0))
                    if p > 0:
                        price_val = p
                        break
                except (ValueError, TypeError):
                    continue
            if price_val <= 0:
                err_msg = f'{record.name}: 未配置有效 SKU 价格，无法发布。请先在产品列表中填写每个 SKU 的单价'
                _diag(f'RETURN no valid price: {record.name}')
                results.append({'record': record.name, 'status': 'failed', 'error': err_msg})
                _report(20 + int(((idx+1)/total)*70), f'协议: {record.name} 缺少价格')
                continue

            # 把每个 SKU 的真实价格/库存透传给协议层，避免协议层再兜底
            sku_info_payload = []
            try:
                product_level_stock = int(float(record.repo or 0))
            except (ValueError, TypeError):
                product_level_stock = 0
            for s in (sku_list or []):
                try:
                    sp = float(s.get('price', 0)) or price_val
                except (ValueError, TypeError):
                    sp = price_val
                try:
                    sk = int(s.get('quantity', 0) or s.get('stock', 0) or product_level_stock or 0)
                except (ValueError, TypeError):
                    sk = 0
                sku_info_payload.append({
                    'name': s.get('name', '默认'),
                    'image_path': s.get('path', ''),
                    'price': sp,
                    'stock': sk,
                })
            if not sku_info_payload:
                sku_info_payload = [{'name': '默认', 'image_path': '', 'price': price_val, 'stock': product_level_stock}]

            # 与 DOM 共用发布前的逐商品材质校验结果；不再从全局默认配置重复覆盖。
            material_str = ';'.join(
                f'{name}{percentage}%'
                for name, percentage in record_materials.get(record.id, ())
            )
            _diag(f'material resolved: {material_str or "EMPTY"}')

            product_data = {
                'title': product_title,
                'price': {'current': price_val},
                'sku_info': sku_info_payload,
                'material': material_str,
            }

            # 收集图片路径（与DOM流程一致，从文件系统标准目录读取）
            image_paths = {'main_images': [], 'main_images_1x1': [], 'detail_images': [], 'sku_images': []}
            try:
                # 1:1 方图 (800) → main_images_1x1 → 用于 pic 字段
                main_pics = self._browser.get_pic_list(record, '800')
                image_paths['main_images_1x1'] = [p for p in main_pics[:5] if os.path.isfile(p)]
            except Exception as e:
                print(f'[协议] 获取800主图失败: {e}')

            try:
                # 3:4 主图 (750) → main_images → 用于 main_image_three_to_four
                sub_pics = self._browser.get_pic_list(record, '750')
                image_paths['main_images'] = [p for p in sub_pics[:5] if os.path.isfile(p)]
            except Exception as e:
                print(f'[协议] 获取750主图失败: {e}')

            try:
                # 详情图
                detail_pics = self._browser.get_detail_pic_list(record)
                image_paths['detail_images'] = [p for p in detail_pics if os.path.isfile(p)]
            except Exception as e:
                print(f'[协议] 获取详情图失败: {e}')

            # 如果 3:4 主图缺失，用 1:1 方图回退
            if not image_paths['main_images'] and image_paths['main_images_1x1']:
                image_paths['main_images'] = list(image_paths['main_images_1x1'])
                print('[协议] 3:4主图缺失，使用1:1方图回退')

            # 收集 SKU 规格图
            image_paths['sku_images'] = []
            for s in sku_list:
                sku_path = s.get('path', '')
                if sku_path and os.path.isfile(sku_path):
                    image_paths['sku_images'].append(sku_path)

            _diag(f'images: 1x1={len(image_paths["main_images_1x1"])} 3:4={len(image_paths["main_images"])} detail={len(image_paths["detail_images"])} sku={len(image_paths["sku_images"])}')
            if not image_paths['main_images_1x1']:
                _diag('RETURN no main_images_1x1')
                return api_error(msg=f'{record.name}: 未找到主图（请确保主图/800 或 主图 目录下有图片）')

            # 类目映射：clazz → wazi_dict → leaf_id + 类目层级
            _clazz_to_leaf = {
                '0': {'leaf_id': 1000010268, 'name': '船袜',
                      'first_cid': 1000003282, 'first_cname': '服装',
                      'second_cid': 1000009114, 'second_cname': '内衣裤袜',
                      'third_cid': 1000009597, 'third_cname': '袜子'},
                '1': {'leaf_id': 1000010266, 'name': '短袜',
                      'first_cid': 1000003282, 'first_cname': '服装',
                      'second_cid': 1000009114, 'second_cname': '内衣裤袜',
                      'third_cid': 1000009597, 'third_cname': '袜子'},
                '2': {'leaf_id': 1000010267, 'name': '中筒袜',
                      'first_cid': 1000003282, 'first_cname': '服装',
                      'second_cid': 1000009114, 'second_cname': '内衣裤袜',
                      'third_cid': 1000009597, 'third_cname': '袜子'},
                '3': {'leaf_id': 1000010269, 'name': '长筒袜',
                      'first_cid': 1000003282, 'first_cname': '服装',
                      'second_cid': 1000009114, 'second_cname': '内衣裤袜',
                      'third_cid': 1000009597, 'third_cname': '袜子'},
                '4': {'leaf_id': 1000010270, 'name': '袜套',
                      'first_cid': 1000003282, 'first_cname': '服装',
                      'second_cid': 1000009114, 'second_cname': '内衣裤袜',
                      'third_cid': 1000009597, 'third_cname': '袜子'},
            }
            raw_clazz = str(getattr(record, 'clazz', '') or '').strip()
            clazz_info = _clazz_to_leaf.get(raw_clazz, _clazz_to_leaf['2'])  # 默认中筒袜
            leaf_id = clazz_info['leaf_id']
            _clazz_name = clazz_info.get('name', '未知')
            print(f'[协议] clazz={raw_clazz} -> {_clazz_name} (leaf_id={leaf_id})')

            category_config = {
                'category_leaf_id': leaf_id,
                'first_cid': clazz_info['first_cid'], 'first_cname': clazz_info['first_cname'],
                'second_cid': clazz_info['second_cid'], 'second_cname': clazz_info['second_cname'],
                'third_cid': clazz_info['third_cid'], 'third_cname': clazz_info['third_cname'],
                'fourth_cid': leaf_id, 'fourth_cname': clazz_info['name'],
            }

            try:
                from fxg_protocol_v4 import run as protocol_run_v4
                print('[协议] fxg_protocol_v4 导入成功')
                _diag('import fxg_protocol_v4 OK')
            except ImportError as e:
                import traceback as _tb
                print(f'[协议] 导入失败: {e}')
                _tb.print_exc()
                _diag(f'import FAILED: {e}')
                return api_error(msg=f'协议模块未找到: {e}')

            _diag(f'calling protocol_run_v4: leaf={leaf_id} title_len={len(product_title)}')

            # 构造 v4 兼容的步骤回调，同时更新 task state
            def _v4_progress(pct, msg, step_name=None, steps=None):
                _report(pct, msg)
                if task_id and step_name:
                    with self.lock:
                        t = self.tasks.get(task_id)
                        if t:
                            t['current_step'] = step_name
                            t['progress'] = pct
                            t['message'] = msg
                            if steps:
                                t['steps'] = [{
                                    'name': s.get('name', ''),
                                    'status': s.get('status', ''),
                                    'elapsed_ms': int(s.get('elapsed_ms', 0)),
                                    'summary': str(s.get('summary', '')),
                                } for s in steps]

            # 把用户在设置里选择的运费模板名透传给协议层，
            # 协议层会实时拉取店铺模板列表后按名称匹配 ID，避免历史的硬编码 ID 问题
            shipping_template_name = ''
            try:
                _ss = self._settings_manager.get_settings()
                _ac_now = self._settings_manager.normalize_automation_config(_ss.automation_config)
                shipping_template_name = str(_ac_now.get('shipping_template') or '').strip()
            except Exception as _se:
                _diag(f'load shipping_template from settings failed: {_se}')

            try:
                result = protocol_run_v4(
                    category_leaf_id=int(category_config['category_leaf_id']),
                    product_data=product_data,
                    image_paths={
                        'main_3x4': image_paths.get('main_images', []),
                        'main_1x1': image_paths.get('main_images_1x1', []),
                        'detail': image_paths.get('detail_images', []),
                        'sku': image_paths.get('sku_images', []),
                    },
                    category_config=category_config,
                    progress_callback=_v4_progress,
                    cdp_port=_proto_port,
                    shipping_template_name=shipping_template_name,
                    stop_before_submit=stop_before_submit,
                )
                if isinstance(result, dict) and result.get('success'):
                    pid = result.get('data', {}).get('product_id', '')
                    stopped = bool(result.get('data', {}).get('stopped_before_submit'))
                    results.append({'record': record.name, 'product_id': pid, 'status': 'ok',
                                    'path': result.get('data', {}).get('path', ''),
                                    'stopped_before_submit': stopped,
                                    'steps': result.get('steps', [])})
                    if stopped:
                        _report(20 + int(((idx+1)/total)*70), f'协议: {record.name} 预检通过（已截停）')
                        _diag('protocol_run_v4 OK: stopped_before_submit')
                    else:
                        _report(20 + int(((idx+1)/total)*70), f'协议: {record.name} OK ({pid[:16]})')
                        _diag(f'protocol_run_v4 OK: pid={pid}')
                else:
                    err = (result or {}).get('error', {}) if isinstance(result, dict) else {}
                    err_msg = err.get('message', str(err)[:50]) if isinstance(err, dict) else str(result)[:50]
                    if isinstance(err, dict):
                        err_detail = str(err.get('detail') or err.get('fix_hint') or '').strip()
                        if err_detail and err_detail not in err_msg:
                            err_msg = f'{err_msg}：{err_detail}'
                    results.append({'record': record.name, 'status': 'failed', 'error': err_msg,
                                    'steps': result.get('steps', [])})
                    _report(20 + int(((idx+1)/total)*70), f'协议: {record.name} 失败')
                    _diag(f'protocol_run_v4 FAILED: {err_msg}')
            except Exception as e:
                import traceback as _tb
                _tb.print_exc()
                results.append({'record': record.name, 'status': 'failed', 'error': str(e)[:100]})
                _report(20 + int(((idx+1)/total)*70), f'协议: {record.name} 异常')
                _diag(f'protocol_run_v4 EXCEPTION: {e}')

            # 协议模式下每次提交间隔2秒
            if idx < total - 1:
                self._browser.time.sleep(2)

        success_count = sum(1 for r in results if r.get('status') == 'ok')
        _diag(f'DONE: success_count={success_count}/{total} results={results}')

        # 清理自动启动的浏览器（只关闭我们自己启动的页面，不关用户原有的）
        if _proto_page is not None:
            try:
                _proto_page.quit()
            except Exception:
                pass

        if success_count == 0 and total > 0:
            # 收集失败原因（取第一个有 error 的结果）
            first_error = ''
            for r in results:
                if r.get('error'):
                    first_error = str(r['error'])[:200]
                    break
            if not first_error:
                first_error = '请确认Chrome浏览器已启动并已登录抖店后台'
            return api_error(msg=f'发布失败：{first_error}', data={'results': results})
        elif success_count == 0:
            return api_error(msg='没有可发布的商品，请先导入商品数据', data={'results': results})
        if stop_before_submit:
            return api_ok(msg=f'协议预检完成：{success_count}/{total} 个商品已到提交前截停点', data={'results': results})
        return api_ok(msg=f'发布完成：{success_count}/{total} 个商品', data={'results': results})

    def run_upload_task(self, task_id: str, record_id=None, stop_before_submit=False):
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            task['status'] = 'running'
            task['progress'] = 10
            task['message'] = '正在启动浏览器并准备上传'
            task['started_at'] = datetime.now().isoformat()

        try:
            # 检查是否已被取消
            with self.lock:
                t = self.tasks.get(task_id)
                if t and t.get('cancelled'):
                    t['status'] = 'cancelled'
                    t['message'] = '任务已被用户取消'
                    t['finished_at'] = datetime.now().isoformat()
                    return

            # 读取发布模式: protocol / official / dom
            user_settings = self._settings_manager.get_settings()
            ac = self._settings_manager.normalize_automation_config(user_settings.automation_config)
            publish_mode = ac.get('publish_mode', 'dom')

            # 文件日志诊断 (_run_upload_task)
            import sys as _rt_sys
            _rt_log = os.path.join(os.path.dirname(_rt_sys.executable) if getattr(_rt_sys, 'frozen', False) else os.path.dirname(os.path.abspath(self._app_file)), 'run_task_diag.log')
            try:
                with open(_rt_log, 'a', encoding='utf-8') as _f:
                    _f.write(f'{datetime.now().isoformat()} | _run_upload_task: publish_mode={publish_mode} record_id={record_id} task_id={task_id}\n')
            except:
                pass

            if publish_mode == 'protocol':
                def _protocol_progress_callback(pct, msg, step_name=None, steps=None):
                    with self.lock:
                        t = self.tasks.get(task_id)
                        if not t or t.get('cancelled'):
                            return
                        t['progress'] = max(0, min(int(pct), 99))
                        t['message'] = str(msg)
                        if step_name:
                            t['current_step'] = str(step_name)
                        if steps:
                            t['steps'] = list(steps)

                with self.lock:
                    t = self.tasks.get(task_id)
                    if t: t['message'] = '协议模式：正在初始化CDP会话'
                result = self._execute_protocol_flow(
                    record_id=record_id,
                    progress_callback=_protocol_progress_callback,
                    task_id=task_id,
                    stop_before_submit=stop_before_submit,
                )
                success = bool(result.get('success'))
                message = str(result.get('msg') or '')
                result_data = result.get('data') or {}
                try:
                    with open(_rt_log, 'a', encoding='utf-8') as _f:
                        _f.write(f'{datetime.now().isoformat()} | result: success={success} msg={message} data_keys={list(result_data.keys())}\n')
                except:
                    pass
                with self.lock:
                    t = self.tasks.get(task_id)
                    if t:
                        t['progress'] = 100
                        t['status'] = 'success' if success else 'failed'
                        t['message'] = message
                        t['current_step'] = '完成'
                        t['error'] = None if success else (result.get('msg') or '协议模式失败')
                        t['debug_report'] = result_data.get('results') if result_data else None
                        t['finished_at'] = datetime.now().isoformat()
                return

            def _task_progress_callback(progress, message):
                with self.lock:
                    task = self.tasks.get(task_id)
                    if not task or task.get('cancelled'):
                        return
                    safe_progress = max(0, min(int(progress), 99))
                    task['progress'] = safe_progress
                    if message:
                        task['message'] = str(message)

            result = self.execute_upload_flow(
                record_id=record_id,
                progress_callback=_task_progress_callback,
                stop_before_submit=stop_before_submit,
                task_id=task_id,
            )

            success = bool(result.get('success'))
            message = str(result.get('msg') or '')

            with self.lock:
                task = self.tasks.get(task_id)
                if not task:
                    return
                if task.get('cancelled'):
                    task['status'] = 'cancelled'
                    task['message'] = '任务已被用户取消'
                    task['progress'] = 100
                    task['finished_at'] = datetime.now().isoformat()
                elif success:
                    task['status'] = 'success'
                    task['progress'] = 100
                    task['message'] = message or '上传完成'
                    task['error'] = None
                    task['finished_at'] = datetime.now().isoformat()
                else:
                    task['status'] = 'failed'
                    task['progress'] = 100
                    task['message'] = '上传失败'
                    task['error'] = message or '上传失败（未知原因）'
                    task['debug_report'] = self._browser.latest_error_after(task.get('started_at'))
                    task['finished_at'] = datetime.now().isoformat()
        except Exception as e:
            traceback.print_exc()
            with self.lock:
                task = self.tasks.get(task_id)
                if not task:
                    return
                task['status'] = 'failed'
                task['progress'] = 100
                task['message'] = '上传失败'
                task['error'] = str(e)
                task['finished_at'] = datetime.now().isoformat()
                task['debug_report'] = self._browser.latest_error_after(task.get('started_at'))

    def page_state(self):
        """当前共享的页面状态（带 ``page`` 属性的对象）；路由层要读 ``page`` 判断“有没有浏览器”。"""
        return self._browser.page_state()

# -*- coding: utf-8 -*-
# BUILD_MARKER_V3_20260521

import traceback, os as _boot_os
# === SIDE-EFFECT MARKER: 启动时写入标记文件 ===
try:
    _marker_dir = _boot_os.path.dirname(_boot_os.path.abspath(__file__))
    _marker_path = _boot_os.path.join(_marker_dir, 'BOOT_MARKER_V3.log')
    with open(_marker_path, 'w', encoding='utf-8') as _mf:
        _mf.write('app.py loaded: V3 marker present\n')
except Exception as _ex:
    try:
        with open(_boot_os.path.join(_boot_os.environ.get('TEMP', '/tmp'), 'BOOT_MARKER_V3_fallback.log'), 'w', encoding='utf-8') as _mf:
            _mf.write(f'app.py loaded but marker write failed: {_ex}\n')
    except:
        pass
from typing import Optional
from dataclasses import asdict
import time as system_time
import os
import sys
import copy
import html
import importlib
import builtins
import re
import socket
import subprocess
import tempfile
import uuid
import ctypes
import signal
from decimal import Decimal, InvalidOperation


def _resolve_bootstrap_log_path():
    data_dir = os.environ.get('DOUYIN_DATA_DIR')
    if data_dir:
        log_dir = os.path.join(data_dir, 'logs')
    else:
        local_app_data = os.environ.get('LOCALAPPDATA')
        if local_app_data:
            log_dir = os.path.join(local_app_data, 'com.dyin.sock-publisher', 'logs')
        else:
            log_dir = os.path.join(tempfile.gettempdir(), 'dyin-sock-publisher-logs')
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        log_dir = tempfile.gettempdir()
    return os.path.join(log_dir, 'python-backend.bootstrap.log')


_BOOTSTRAP_LOG_PATH = _resolve_bootstrap_log_path()


def _bootstrap_log(message):
    try:
        with open(_BOOTSTRAP_LOG_PATH, 'a', encoding='utf-8', errors='replace') as fp:
            fp.write(f"{message}\n")
    except Exception:
        pass


def _bootstrap_excepthook(exc_type, exc_value, exc_tb):
    formatted = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        _bootstrap_log('=== unhandled exception ===')
        _bootstrap_log(formatted)
    except Exception:
        pass
    try:
        if sys.stderr is not None:
            sys.stderr.write(formatted)
            sys.stderr.flush()
    except Exception:
        pass


sys.excepthook = _bootstrap_excepthook
_EARLY_SIDECAR_MODE = str(os.environ.get('SIDECAR_MODE', '')).strip().lower()
_bootstrap_log(f"bootstrap start frozen={getattr(sys, 'frozen', False)} sidecar_raw={os.environ.get('SIDECAR_MODE')!r}")


def print(*args, **kwargs):
    try:
        return builtins.print(*args, **kwargs)
    except UnicodeEncodeError:
        file = kwargs.get('file', sys.stdout)
        sep = kwargs.get('sep', ' ')
        end = kwargs.get('end', '\n')
        flush = kwargs.get('flush', False)
        encoding = getattr(file, 'encoding', 'utf-8') or 'utf-8'
        text = sep.join(str(arg) for arg in args)
        safe_text = text.encode(encoding, errors='replace').decode(encoding, errors='replace')
        return builtins.print(safe_text, end=end, file=file, flush=flush)

class _SafeConsoleStream:
    def __init__(self, stream):
        self._stream = stream
        self.encoding = getattr(stream, 'encoding', 'utf-8') or 'utf-8'

    def write(self, text):
        if text is None:
            return 0
        if not isinstance(text, str):
            text = str(text)
        try:
            return self._stream.write(text)
        except UnicodeEncodeError:
            safe_text = text.encode(self.encoding, errors='replace').decode(self.encoding, errors='replace')
            return self._stream.write(safe_text)

    def flush(self):
        return self._stream.flush()

    def isatty(self):
        return self._stream.isatty()

    def fileno(self):
        return self._stream.fileno()

    def reconfigure(self, *args, **kwargs):
        if hasattr(self._stream, 'reconfigure'):
            result = self._stream.reconfigure(*args, **kwargs)
            self.encoding = getattr(self._stream, 'encoding', self.encoding) or self.encoding
            return result
        return None

    def __getattr__(self, name):
        return getattr(self._stream, name)


if sys.stdout is not None:
    sys.stdout = _SafeConsoleStream(sys.stdout)
if sys.stderr is not None:
    sys.stderr = _SafeConsoleStream(sys.stderr)

if sys.platform == 'win32' and _EARLY_SIDECAR_MODE not in ('1', 'true', 'yes', 'on'):
    try:
        Gui = importlib.import_module('src.gui').Gui
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

if getattr(sys, 'frozen', False) and _EARLY_SIDECAR_MODE not in ('1', 'true', 'yes', 'on'):
    try:
        base_dir = os.path.dirname(sys.executable)
        os.add_dll_directory(base_dir)
        internal_dir = os.path.join(base_dir, '_internal')
        if os.path.isdir(internal_dir):
            os.add_dll_directory(internal_dir)
            os.add_dll_directory(os.path.join(internal_dir, 'PySide6'))
            os.add_dll_directory(os.path.join(internal_dir, 'shiboken6'))
            os.environ['QT_PLUGIN_PATH'] = os.path.join(internal_dir, 'PySide6', 'plugins')
            os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.path.join(internal_dir, 'PySide6', 'plugins', 'platforms')
            os.environ['PATH'] = internal_dir + os.pathsep + os.path.join(internal_dir, 'PySide6') + os.pathsep + os.path.join(internal_dir, 'shiboken6') + os.pathsep + os.environ.get('PATH', '')
        else:
            meipass = getattr(sys, '_MEIPASS', base_dir)
            os.add_dll_directory(meipass)
            os.add_dll_directory(os.path.join(meipass, 'PySide6'))
            os.add_dll_directory(os.path.join(meipass, 'shiboken6'))
            os.environ['QT_PLUGIN_PATH'] = os.path.join(meipass, 'PySide6', 'plugins')
            os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.path.join(meipass, 'PySide6', 'plugins', 'platforms')
            os.environ['PATH'] = meipass + os.pathsep + os.path.join(meipass, 'PySide6') + os.pathsep + os.path.join(meipass, 'shiboken6') + os.pathsep + os.environ.get('PATH', '')
    except Exception:
        pass
_bootstrap_log('import flask start')
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
_bootstrap_log('import flask done')

# 开发模式下，sidecar 位于 tauri-app/python-sidecar，需要把项目根目录加入 sys.path
repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if not getattr(sys, 'frozen', False):
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

_bootstrap_log('import runtime_paths start')
from src.runtime_paths import bootstrap_runtime_environment, resolve_data_file
_bootstrap_log('import runtime_paths done')

bootstrap_runtime_environment(
    seed_files={
        'cfg.yaml': ['cfg.yaml', os.path.join(repo_root, 'tauri-app', 'cfg.yaml'), os.path.join(repo_root, 'cfg.yaml')],
        'sqlite.db': ['sqlite.db', os.path.join(repo_root, 'sqlite.db')],
        'pricing_config.json': ['pricing_config.json', os.path.join(repo_root, 'pricing_config.json')],
        'user_settings.json': ['user_settings.json', os.path.join(repo_root, 'tauri-app', 'user_settings.json'), os.path.join(repo_root, 'user_settings.json')],
        'trending_keywords.db': ['trending_keywords.db', os.path.join(repo_root, 'trending_keywords.db')],
    }
)
_bootstrap_log('bootstrap_runtime_environment done')

_bootstrap_log('import orm start')
from src.orm import Record
_bootstrap_log('import orm done')
_bootstrap_log('import utils start')
from src.utils import *
from src.utils import _wait_until, _ensure_section_ready, _normalize_debug_address, _verify_debug_browser, attach_existing_debug_browser, discover_debuggable_browsers, _find_ai_material_tool_panel, _is_upload_busy, _xpath_literal, fetch_cdp_page_targets, is_logged_in_fxg_target_url, select_logged_in_fxg_debug_browser
_bootstrap_log('import utils done')
_bootstrap_log('import config start')
from src.config import settings_manager, LLM_PROVIDER_PRESETS, ALLOWED_PUBLISH_AI_PROVIDERS, MATERIAL_NAME_MAX_LENGTH
from src.llm_client import LLMClient, LLMError
_bootstrap_log('import config done')
_bootstrap_log('import ops_engine start')
from src.ops_engine import (
    AI_POLICY,
    DAILY_NET_PROFIT_TARGET,
    OperatingCostInput,
    ProductCandidateInput,
    ProductEvaluationInput,
    StockPlanInput,
    apply_candidate_pricing_to_skus,
    build_conversion_asset_pack,
    build_conversion_experiment_plan,
    build_daily_plan,
    build_daily_review,
    build_detail_conversion_audit,
    build_detail_improvement_suggestions,
    build_main_video_upload_stop_gate,
    build_material_gap_plan,
    build_no_brand_remediation_plan,
    build_no_brand_title_audit,
    build_ops_execution_queue,
    build_first_order_decision_matrix,
    build_net_profit_verification_matrix,
    build_portfolio_path_to_500,
    build_post_save_conversion_monitor,
    build_profit_ladder_to_500,
    build_publish_preflight_evidence,
    build_publish_preflight_safety,
    build_save_edit_human_gate,
    build_profit_ramp_plan,
    build_product_record_mappings,
    build_product_candidate_list,
    build_search_conversion_work_package,
    build_sourcing_profit_gate,
    build_strategy_action_reconcile_plan,
    build_supplier_quote_intake,
    build_supplier_quote_plan,
    build_stock_plan,
    calculate_operating_profit,
    enforce_no_external_ai_settings,
    evaluate_product,
    extract_sku_goods_costs,
    get_ops_ledger,
    merge_observed_shop_metrics,
)
_bootstrap_log('import ops_engine done')
_bootstrap_log('import professional_title_generator start')
from src.professional_title_generator import (
    get_professional_generator,
    ProductInfo as ProfessionalProductInfo,
    sanitize_no_brand_title_text,
)
_bootstrap_log('import professional_title_generator done')
_bootstrap_log('import enhanced_category_selector start')
from src.enhanced_category_selector import smart_select_category
_bootstrap_log('import enhanced_category_selector done')
from capture_url_utils import capture_url_host, is_taobao_short_link, normalize_capture_url
_bootstrap_log('import protocol_capture optional start')
try:
    from protocol_capture import ProtocolCaptureEngine
    _bootstrap_log('import protocol_capture optional done')
except Exception as _protocol_capture_import_error:
    ProtocolCaptureEngine = None
    _bootstrap_log(f'import protocol_capture optional skipped: {_protocol_capture_import_error}')
import json
import base64
import shutil
from datetime import datetime, timedelta
import threading


# 🔧 获取程序根目录（支持打包后的可执行文件）
def get_app_root():
    """
    获取应用程序的根目录
    - 开发环境：返回脚本所在目录
    - 打包后（PyInstaller）：返回可执行文件所在目录
    """
    data_dir = os.environ.get('DOUYIN_DATA_DIR')
    if data_dir:
        return data_dir
    env_resource_dir = os.environ.get('DOUYIN_RESOURCE_DIR')
    if env_resource_dir:
        return env_resource_dir
    elif getattr(sys, 'frozen', False):
        # 如果是打包后的可执行文件
        return os.path.dirname(sys.executable)
    else:
        # 如果是开发环境
        return os.path.dirname(os.path.abspath(__file__))


# 🔧 获取资源路径（支持打包后的可执行文件）
def get_resource_path(relative_path):
    """
    获取资源文件的绝对路径
    - 开发环境：相对于脚本目录
    - 打包后：相对于_MEIPASS临时目录（PyInstaller）
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller会创建临时文件夹，将路径存储在_MEIPASS中
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    return os.path.join(base_path, relative_path)


# 🔧 规范化保存路径（支持相对路径和绝对路径）
def normalize_save_path(path):
    """
    规范化保存路径
    - 如果是绝对路径，直接返回
    - 如果是相对路径，相对于程序根目录
    - 统一使用操作系统的路径分隔符
    """
    # 先统一使用正斜杠（跨平台兼容）
    path = path.replace('\\', '/')
    
    # 检查是否为绝对路径（Windows: C:/ 或 D:/, Linux/Mac: /）
    is_absolute = os.path.isabs(path) or (len(path) > 2 and path[1] == ':')
    
    if is_absolute:
        # 绝对路径：直接规范化并返回
        result = os.path.normpath(path)
    else:
        # 相对路径：相对于程序根目录
        result = os.path.normpath(os.path.join(get_app_root(), path))
    
    # 统一使用当前操作系统的路径分隔符
    return result


def get_runtime_data_path(file_name, legacy_fallback=None):
    fallback = legacy_fallback or os.path.join(os.path.dirname(__file__), file_name)
    return str(resolve_data_file(file_name, legacy_fallback=fallback))


_AUTOMATION_ASSETS_DIR_NAME = 'automation_assets'
_WASH_LABEL_TAG_IMAGE_BASENAME = 'wash_label_tag_image'
_ALLOWED_AUTOMATION_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}


def _get_automation_assets_dir():
    assets_dir = get_runtime_data_path(_AUTOMATION_ASSETS_DIR_NAME)
    os.makedirs(assets_dir, exist_ok=True)
    return assets_dir


def _is_path_within_dir(path_value, directory):
    try:
        resolved_path = os.path.abspath(path_value)
        resolved_dir = os.path.abspath(directory)
        return os.path.commonpath([resolved_path, resolved_dir]) == resolved_dir
    except Exception:
        return False


def _delete_managed_automation_image_files(base_name):
    assets_dir = _get_automation_assets_dir()
    for file_name in os.listdir(assets_dir):
        if not file_name.startswith(f'{base_name}.'):
            continue
        file_path = os.path.join(assets_dir, file_name)
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
        except Exception:
            continue


def _resolve_managed_automation_image_path(source_path, base_name, label):
    extension = os.path.splitext(source_path)[1].lower()
    if extension not in _ALLOWED_AUTOMATION_IMAGE_EXTENSIONS:
        raise ValueError(f'仅支持 jpg、jpeg、png、bmp、webp 格式的{label}')
    file_name = f'{base_name}{extension}'
    return os.path.join(_get_automation_assets_dir(), file_name)


def _delete_managed_wash_label_tag_image_files():
    _delete_managed_automation_image_files(_WASH_LABEL_TAG_IMAGE_BASENAME)


def _resolve_managed_wash_label_tag_image_path(source_path):
    return _resolve_managed_automation_image_path(source_path, _WASH_LABEL_TAG_IMAGE_BASENAME, '水洗标/吊牌图')


def _get_runtime_log_dir():
    try:
        log_dir = os.path.dirname(_BOOTSTRAP_LOG_PATH) or tempfile.gettempdir()
        os.makedirs(log_dir, exist_ok=True)
        return log_dir
    except Exception:
        return tempfile.gettempdir()


_UPLOAD_STAGE_TIMING_LOG_PATH = os.path.join(_get_runtime_log_dir(), 'upload-stage-timing.jsonl')
_PROTOCOL_CAPTURE_ENGINE = ProtocolCaptureEngine() if ProtocolCaptureEngine else None


def _protocol_publish_debug_enabled():
    # 协议化上传仍处于研究阶段，不能挂到正式 DOM 自动化流水线。
    return False


def _append_stage_timing_log(entry):
    try:
        with open(_UPLOAD_STAGE_TIMING_LOG_PATH, 'a', encoding='utf-8', errors='replace') as fp:
            fp.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass


def _start_protocol_publish_record(record):
    return None


def _write_protocol_artifact_json(protocol_runtime, stage, name, payload, artifact_type='json'):
    return None


def _finalize_protocol_publish_record(protocol_runtime, *, record, status, current_stage, error_tip, stage_timings, duration_ms):
    return None


def _detect_capture_source_platform(url: str) -> str:
    if _is_1688_capture_url(url):
        return '1688'
    if 'tmall.com' in str(url or '').lower():
        return 'tmall'
    if _is_taobao_tmall_capture_url(url):
        return 'taobao'
    return 'unknown'


def _start_protocol_capture_record(*, source_url: str, task_id: str, options: Optional[dict] = None, product_id: str = ''):
    if not _PROTOCOL_CAPTURE_ENGINE:
        return None
    try:
        platform = _detect_capture_source_platform(source_url)
        context, store = _PROTOCOL_CAPTURE_ENGINE.build_run_context(
            source_url=source_url,
            source_platform=platform,
            product_id=product_id,
            metadata={
                'task_id': task_id,
                'options': copy.deepcopy(options or {}),
            },
        )
        store.write_json('session', 'plan', _PROTOCOL_CAPTURE_ENGINE.export_plan(), artifact_type='protocol-plan')
        store.write_json(
            'session',
            'platform-profiles',
            _PROTOCOL_CAPTURE_ENGINE.export_platform_profiles(),
            artifact_type='platform-profiles',
        )
        store.write_json(
            'session',
            'task-meta',
            {
                'task_id': task_id,
                'source_url': source_url,
                'source_platform': platform,
                'product_id': product_id,
                'options': copy.deepcopy(options or {}),
                'started_at': context.started_at,
            },
            artifact_type='task-meta',
        )
        runtime = {'context': context, 'store': store, 'root': str(store.root)}
        print(f'协议化采集调试目录: {runtime["root"]}')
        return runtime
    except Exception as exc:
        print(f'协议化采集调试运行初始化失败，已跳过: {exc}')
        return None


def _write_protocol_capture_artifact_json(protocol_runtime, stage, name, payload, artifact_type='json'):
    if not protocol_runtime:
        return None
    try:
        return protocol_runtime['store'].write_json(stage, name, payload, artifact_type=artifact_type)
    except Exception as exc:
        print(f'协议化采集产物写入失败，已跳过: stage={stage} name={name} error={exc}')
        return None


def _finalize_protocol_capture_record(
    protocol_runtime,
    *,
    task_id: str,
    source_url: str,
    status: str,
    progress: int,
    message: str,
    error: str = '',
    result: Optional[dict] = None,
):
    if not protocol_runtime:
        return
    _write_protocol_capture_artifact_json(
        protocol_runtime,
        'session',
        'task-summary',
        {
            'task_id': task_id,
            'source_url': source_url,
            'status': status,
            'progress': progress,
            'message': message,
            'error': error,
            'artifact_root': protocol_runtime.get('root'),
            'finished_at': datetime.now().isoformat(),
        },
        artifact_type='task-summary',
    )
    if result:
        _write_protocol_capture_artifact_json(
            protocol_runtime,
            'import_manifest',
            'capture-result',
            result,
            artifact_type='capture-result',
        )


def _run_stage_with_timing(stage_timings, record, stage_name, func, *args, **kwargs):
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
        _append_stage_timing_log(entry)
        print(f'[阶段耗时] {stage_name}: {duration_ms}ms')


def _settle_between_records(main_tab):
    try:
        if main_tab:
            _wait_until(
                lambda: not _is_upload_busy(main_tab),
                timeout=0.4,
                interval=0.05,
            )
    except Exception:
        pass
    system_time.sleep(0.1)


app = Flask(__name__, template_folder=constants.run_path, static_folder=constants.run_path, static_url_path='')
CORS(app, resources={r"/*": {"origins": "*"}})
app.config['JWT_SECRET_KEY'] = constants.secret
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = 604800
# 启用调试模式和详细日志
app.config['DEBUG'] = False  # 🔧 修复：禁用调试模式避免多线程信号处理冲突
import logging
logging.basicConfig(level=logging.INFO)  # 🔧 降低日志级别
app.logger.setLevel(logging.INFO)
# 禁用模板缓存
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
open_url_list = ['/admin', '/component', '/login', '/captcha']


class _GuiState:
    def __init__(self):
        self.page = None


gui = _GuiState()


_PUBLISH_CREATE_URL = 'https://fxg.jinritemai.com/ffa/g/create'
_BROWSER_DEBUG_DEFAULT_URL = _PUBLISH_CREATE_URL
_BROWSER_DEBUG_MAX_EVENTS = 200
_BROWSER_DEBUG_MAX_SESSIONS = 8
_DEBUG_BROWSER_HOST = '127.0.0.1'
_DEBUG_BROWSER_PORT_START = 9333
_DEBUG_BROWSER_PORT_END = 9399
_CAPTURE_BROWSER_PORT_START = 9400
_CAPTURE_BROWSER_PORT_END = 9499
_browser_debug_lock = threading.Lock()
_browser_debug_state = {
    'current_session_id': None,
    'sessions': {},
    'last_error': None,
    'browser_instance': None,
}
_sidecar_shutdown_event = threading.Event()
_sidecar_parent_watchdog = None


def is_sidecar_mode() -> bool:
    value = str(os.environ.get('SIDECAR_MODE', '')).strip().lower()
    if value in ('1', 'true', 'yes', 'on'):
        return True
    if getattr(sys, 'frozen', False):
        executable_name = os.path.basename(sys.executable).lower()
        if executable_name in ('python-backend.exe', 'python-backend'):
            return True
    return False


def get_sidecar_port() -> int:
    try:
        return int(os.environ.get('SIDECAR_PORT', '5001'))
    except ValueError:
        return 5001


def get_sidecar_parent_pid():
    raw_value = str(os.environ.get('PARENT_PID', '')).strip()
    if not raw_value:
        return None
    try:
        parent_pid = int(raw_value)
    except ValueError:
        return None
    return parent_pid if parent_pid > 0 else None


def _is_process_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False

    if os.name == 'nt':
        process_query_limited_information = 0x1000
        synchronize = 0x00100000
        wait_timeout = 0x00000102
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited_information | synchronize, False, pid)
        if not handle:
            error_code = kernel32.GetLastError()
            return error_code == 5
        try:
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _request_sidecar_shutdown(reason: str, exit_code: int = 0):
    if _sidecar_shutdown_event.is_set():
        return

    _sidecar_shutdown_event.set()
    _bootstrap_log(f'sidecar shutdown requested: {reason}')
    try:
        print(f'🛑 Sidecar 即将退出：{reason}')
    except Exception:
        pass

    try:
        if sys.stdout is not None:
            sys.stdout.flush()
        if sys.stderr is not None:
            sys.stderr.flush()
    except Exception:
        pass

    os._exit(exit_code)


def _sidecar_parent_watchdog_loop(parent_pid: int, poll_interval: float = 0.5):
    _bootstrap_log(f'parent watchdog started: parent_pid={parent_pid}')
    while not _sidecar_shutdown_event.wait(poll_interval):
        if not _is_process_alive(parent_pid):
            _bootstrap_log(f'parent watchdog detected dead parent: parent_pid={parent_pid}')
            _request_sidecar_shutdown(f'父进程已退出（pid={parent_pid}）', exit_code=0)
            return


def _install_sidecar_signal_handlers():
    def _handle_signal(signum, _frame):
        _bootstrap_log(f'sidecar received signal: {signum}')
        _request_sidecar_shutdown(f'收到退出信号 {signum}', exit_code=0)

    for signal_name in ('SIGTERM', 'SIGINT', 'SIGBREAK'):
        sig = getattr(signal, signal_name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _handle_signal)
        except Exception:
            continue


def _start_sidecar_parent_watchdog():
    global _sidecar_parent_watchdog

    if _sidecar_parent_watchdog and _sidecar_parent_watchdog.is_alive():
        return

    parent_pid = get_sidecar_parent_pid()
    if not parent_pid:
        _bootstrap_log('parent watchdog skipped: missing PARENT_PID')
        return

    if not _is_process_alive(parent_pid):
        _bootstrap_log(f'parent watchdog found dead parent before startup: parent_pid={parent_pid}')
        _request_sidecar_shutdown(f'启动时父进程已退出（pid={parent_pid}）', exit_code=0)
        return

    _sidecar_parent_watchdog = threading.Thread(
        target=_sidecar_parent_watchdog_loop,
        args=(parent_pid,),
        name='sidecar-parent-watchdog',
        daemon=True,
    )
    _sidecar_parent_watchdog.start()


def run_flask_server(port: int) -> None:
    print(f"🌐 Flask服务将在 http://127.0.0.1:{port} 运行")
    app.run(
        host='127.0.0.1',
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True
    )


@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    return response


@app.get('/health')
def health():
    return jsonify({
        'success': True,
        'status': 'ok',
        'message': 'Backend is healthy',
        'mode': 'sidecar' if is_sidecar_mode() else 'gui',
        'port': get_sidecar_port() if is_sidecar_mode() else 5000
    })


def _ops_request_data():
    return request.get_json(silent=True) or {}


def _ops_float(data, key, default=0):
    try:
        value = data.get(key, default) if isinstance(data, dict) else default
        if value in ('', None):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _ops_int(data, key, default=0):
    try:
        value = data.get(key, default) if isinstance(data, dict) else default
        if value in ('', None):
            return int(default)
        return int(float(value))
    except Exception:
        return int(default)


def _ops_pricing_defaults():
    defaults = {
        'shipping_cost': 0.0,
        'packaging_cost': 0.0,
        'platform_commission_rate': 0.0,
    }
    try:
        settings = settings_manager.get_settings()
        for item in (settings.cost_items or []):
            if not isinstance(item, dict):
                continue
            name = str(item.get('name') or '')
            cost_type = str(item.get('cost_type') or '')
            try:
                value = float(item.get('value') or 0)
            except Exception:
                value = 0.0
            if cost_type == 'fixed' and '运费' in name:
                defaults['shipping_cost'] = value
            elif cost_type == 'fixed' and '包装' in name:
                defaults['packaging_cost'] = value
            elif cost_type == 'percentage' and ('佣金' in name or '平台' in name):
                defaults['platform_commission_rate'] = value / 100 if value > 1 else value
    except Exception:
        pass
    return defaults


def _ops_record_context(record_id):
    if not record_id:
        return None, [], None
    try:
        record = Record.get_by_id(record_id)
    except Exception:
        return None, [], None
    try:
        sku_list = json.loads(record.content or '[]')
        if not isinstance(sku_list, list):
            sku_list = []
    except Exception:
        sku_list = []
    return record, sku_list, {
        'record_id': record.id,
        'name': record.name,
        'title': record.title,
        'status': record.status,
        'repo': record.repo,
        'clazz': record.clazz,
        'sku_count': len(sku_list),
        'source_url': record.source_url,
    }


def _ops_first_sku_price(sku_list):
    for sku in sku_list:
        if not isinstance(sku, dict):
            continue
        try:
            price = float(sku.get('price') or 0)
        except Exception:
            price = 0
        if price > 0:
            return price
    return 0.0


def _ops_sku_prices(sku_list):
    return extract_sku_goods_costs(sku_list or [])


def _ops_current_sku_prices(sku_list):
    prices = []
    for sku in sku_list or []:
        if not isinstance(sku, dict):
            continue
        price = _ops_float(sku, 'price', 0)
        if price > 0:
            prices.append(price)
    return prices


def _ops_build_local_product_candidates(data):
    limit = max(min(_ops_int(data, 'limit', 20), 100), 1)
    defaults = _ops_pricing_defaults()
    shipping_cost = _ops_float(data, 'shipping_cost', defaults['shipping_cost'])
    packaging_cost = _ops_float(data, 'packaging_cost', defaults['packaging_cost'])
    platform_commission_rate = _ops_float(data, 'platform_commission_rate', defaults['platform_commission_rate'])
    target_net_margin = _ops_float(data, 'target_net_margin', _ops_float(data, 'targetNetMargin', 0.30))
    expected_daily_orders = _ops_int(data, 'expected_daily_orders', _ops_int(data, 'expectedDailyOrders', 0))
    promotion_cost = _ops_float(data, 'promotion_cost', _ops_float(data, 'promotionCost', 0))
    records = (
        Record.select()
        .order_by(Record.id.desc())
        .limit(limit)
    )
    candidate_inputs = []
    record_contexts = []
    for record in records:
        try:
            sku_list = json.loads(record.content or '[]')
            if not isinstance(sku_list, list):
                sku_list = []
        except Exception:
            sku_list = []
        record_contexts.append({
            'record_id': record.id,
            'name': record.name,
            'title': record.title,
            'status': record.status,
            'repo': record.repo,
            'clazz': record.clazz,
            'sku_count': len(sku_list),
            'source_url': record.source_url,
        })
        candidate_inputs.append(ProductCandidateInput(
            record_id=record.id,
            title=str(record.title or record.name or ''),
            sku_prices=_ops_sku_prices(sku_list),
            current_sku_prices=_ops_current_sku_prices(sku_list),
            shipping_cost=shipping_cost,
            packaging_cost=packaging_cost,
            platform_commission_rate=platform_commission_rate,
            promotion_cost=promotion_cost,
            target_net_margin=target_net_margin,
            expected_daily_orders=expected_daily_orders,
        ))
    return {
        'candidates': build_product_candidate_list(candidate_inputs),
        'records': record_contexts,
        'cost_defaults': {
            'shipping_cost': shipping_cost,
            'packaging_cost': packaging_cost,
            'platform_commission_rate': platform_commission_rate,
            'promotion_cost': promotion_cost,
            'target_net_margin': target_net_margin,
        },
    }


def _ops_local_record_mapping_rows():
    rows = []
    for record in Record.select().order_by(Record.id.asc()):
        rows.append({
            'record_id': int(record.id),
            'title': record.title or '',
            'name': record.name or '',
            'path': record.path or '',
            'source_url': getattr(record, 'source_url', '') or '',
        })
    return rows


def _ops_current_browser_snapshot():
    try:
        tab, _meta = _get_current_browser_tab(create_if_missing=False)
    except Exception as exc:
        return {
            'status': 'not_ready',
            'error': str(exc),
            'has_browser': bool(gui.page),
        }
    if not tab:
        return {
            'status': 'not_ready',
            'error': 'Browser is not running.',
            'has_browser': False,
        }
    try:
        snapshot = _snapshot_browser_context(tab, limit=8, include_html=False)
        url = str(snapshot.get('url') or '')
        title = str(snapshot.get('title') or '')
        page_ready = bool(url and title and 'login' not in url.lower())
        return {
            'status': 'ready' if page_ready else 'needs_login_or_navigation',
            'has_browser': True,
            'url': url,
            'title': title,
            'snapshot': snapshot,
        }
    except Exception as exc:
        return {
            'status': 'not_ready',
            'error': str(exc),
            'has_browser': True,
        }


def _find_reusable_logged_in_fxg_browser(verify=False):
    browsers = discover_debuggable_browsers(verify=verify)
    targets_by_address = {}
    for browser in browsers:
        address = _normalize_debug_address(browser.get('debug_address') or '')
        if not address:
            continue
        targets_by_address[address] = fetch_cdp_page_targets(address)
    selected = select_logged_in_fxg_debug_browser(browsers, targets_by_address)
    return {
        'status': 'ready' if selected else 'not_found',
        'selected_browser': selected,
        'browser_count': len(browsers),
        'target_counts': {
            address: len(targets)
            for address, targets in targets_by_address.items()
        },
    }


def _ops_reusable_fxg_browser_snapshot():
    try:
        return _find_reusable_logged_in_fxg_browser(verify=True)
    except Exception as exc:
        return {
            'status': 'error',
            'error': str(exc),
        }


def _ops_find_product_issue_action(action_id):
    if not action_id:
        return None
    try:
        for item in get_ops_ledger().list_product_issue_actions(limit=200):
            if int(item.get('id') or 0) == int(action_id):
                return item
    except Exception:
        return None
    return None


def _ops_product_from_action(data):
    """解析请求里的 product；缺失时按 action_id 回查运营账本补齐。为空返回 None。"""
    product = data.get('product') if isinstance(data.get('product'), dict) else {}
    action_id = _ops_int(data, 'action_id', _ops_int(data, 'actionId', 0))
    if not product and action_id:
        actions = get_ops_ledger().list_product_issue_actions(limit=500)
        for action in actions:
            if int(action.get('id') or 0) == action_id:
                product = {
                    'action_id': action.get('id'),
                    'product_id': action.get('product_id'),
                    'title': action.get('title'),
                    'recent_30d_sales': action.get('recent_30d_sales'),
                }
                break
    if not product:
        return None
    return product


def _ops_default_candidate_video_path(product_id):
    value = str(product_id or '').strip()
    if not value:
        return ''
    candidate = os.path.join(repo_root, 'output', 'ops-materials', value, 'candidate-main-video.mp4')
    return candidate


def _ops_publish_preflight_page_snapshot():
    try:
        tab, _meta = _get_current_browser_tab(create_if_missing=False)
    except Exception as exc:
        tab = None
        first_error = str(exc)
    else:
        first_error = ''
    if not tab:
        tab = _attach_reusable_logged_in_fxg_browser(lambda _progress, _message: None)
    if not tab:
        return {
            'status': 'not_ready',
            'error': first_error or 'Browser is not running.',
            'has_browser': bool(gui.page),
        }

    try:
        snapshot = _snapshot_browser_context(tab, limit=20, include_html=False)
    except Exception:
        snapshot = {}

    script = """
    return (() => {
      const normalize = (value, limit = 500) => String(value || '').replace(/\\s+/g, ' ').trim().slice(0, limit);
      const isVisible = (el) => {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
      };
      const nodes = Array.from(document.querySelectorAll('label, div, span, section, [attr-field-id]')).filter(isVisible);
      const brandTexts = nodes
        .map((el) => normalize(el.innerText || el.getAttribute('aria-label') || '', 180))
        .filter((text) => text.includes('品牌'))
        .slice(0, 12);
      const titleValues = Array.from(document.querySelectorAll('input, textarea'))
        .filter(isVisible)
        .map((el) => normalize(el.value || '', 120))
        .filter(Boolean)
        .slice(0, 20);
      const labelNodes = nodes.filter((el) => normalize(el.innerText || el.getAttribute('aria-label') || '', 120).includes('使用品牌名'));
      let titleUseBrandNameChecked = null;
      if (labelNodes.length) {
        titleUseBrandNameChecked = false;
        for (const node of labelNodes) {
          const label = node.closest('label') || node;
          const checkbox = label.querySelector('input[type="checkbox"]') || node.querySelector('input[type="checkbox"]');
          const ariaChecked = String(label.getAttribute('aria-checked') || node.getAttribute('aria-checked') || '').toLowerCase();
          const className = String(label.className || node.className || '').toLowerCase();
          if ((checkbox && checkbox.checked) || ariaChecked === 'true' || /checked/.test(className)) {
            titleUseBrandNameChecked = true;
            break;
          }
        }
      }
      return {
        url: location.href,
        title: document.title,
        body_text: normalize(document.body ? document.body.innerText || '' : '', 4000),
        brand_text: brandTexts.join(' | '),
        brand_texts: brandTexts,
        title_values: titleValues,
        title_use_brand_name_visible: labelNodes.length > 0,
        title_use_brand_name_checked: titleUseBrandNameChecked
      };
    })();
    """
    try:
        page_evidence = tab.run_js(script) or {}
    except Exception as exc:
        page_evidence = {
            'error': str(exc),
        }
    merged = {
        **(snapshot or {}),
        **(page_evidence if isinstance(page_evidence, dict) else {}),
        'has_browser': True,
    }
    merged['status'] = 'ready' if merged.get('url') and 'login' not in str(merged.get('url')).lower() else 'needs_login_or_navigation'
    return merged


def _ops_resolve_publish_preflight_context(data):
    action_id = _ops_int(data, 'action_id', _ops_int(data, 'actionId', 0))
    record_id = _ops_int(data, 'record_id', _ops_int(data, 'recordId', 0))
    issue_action = _ops_find_product_issue_action(action_id)
    record, _sku_list, record_context = _ops_record_context(record_id)

    expected_product_id = str(
        data.get('expected_product_id')
        or data.get('expectedProductId')
        or data.get('product_id')
        or data.get('productId')
        or (issue_action or {}).get('product_id')
        or ''
    ).strip()
    expected_title = str(
        data.get('expected_title')
        or data.get('expectedTitle')
        or (record.title if record else '')
        or (issue_action or {}).get('title')
        or ''
    ).strip()
    candidate_video_path = str(
        data.get('candidate_video_path')
        or data.get('candidateVideoPath')
        or _ops_default_candidate_video_path(expected_product_id)
        or ''
    ).strip()

    page_snapshot = data.get('page_snapshot') if isinstance(data.get('page_snapshot'), dict) else None
    if page_snapshot is None:
        page_snapshot = _ops_publish_preflight_page_snapshot()

    preflight = build_publish_preflight_safety(
        page_snapshot=page_snapshot,
        expected_product_id=expected_product_id,
        expected_title=expected_title,
        candidate_video_path=candidate_video_path,
    )

    return {
        'action_id': action_id,
        'record_id': record_id,
        'record': record,
        'record_context': record_context,
        'issue_action': issue_action,
        'expected_product_id': expected_product_id,
        'expected_title': expected_title,
        'candidate_video_path': candidate_video_path,
        'page_snapshot': page_snapshot,
        'preflight': preflight,
    }


def _ops_current_or_reusable_fxg_tab():
    try:
        tab, _meta = _get_current_browser_tab(create_if_missing=False)
    except Exception:
        tab = None
    if tab:
        return tab
    return _attach_reusable_logged_in_fxg_browser(lambda _progress, _message: None)


def _ops_main_video_field_snapshot(tab):
    script = """
    return (() => {
      const normalize = (value, limit = 500) => String(value || '').replace(/\\s+/g, ' ').trim().slice(0, limit);
      const isVisible = (el) => {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
      };
      const field = document.querySelector('[attr-field-id="主图视频"]');
      const mediaNodes = field
        ? Array.from(field.querySelectorAll('video, img, canvas, [class*="video"], [class*="Video"]')).filter(isVisible)
        : [];
      const html = field ? String(field.outerHTML || '') : '';
      const hasSuccessCard = /styles_item-success|item-success|upload-item-success/.test(html);
      const hasVideoAssetSign = /video-play-sign|tos-cn-v|video_id|vid=/.test(html);
      const localUploadCount = field
        ? Array.from(field.querySelectorAll('label, button, div'))
            .filter(isVisible)
            .filter((el) => normalize(el.innerText || el.getAttribute('aria-label') || '', 40).includes('本地上传'))
            .length
        : 0;
      return {
        exists: !!field,
        text: field ? normalize(field.innerText || '', 1000) : '',
        media_count: mediaNodes.length,
        has_video_tag: field ? Array.from(field.querySelectorAll('video')).some(isVisible) : false,
        has_success_card: hasSuccessCard,
        has_video_asset_sign: hasVideoAssetSign,
        file_input_count: field ? field.querySelectorAll('input[type="file"]').length : 0,
        visible_local_upload_count: localUploadCount,
        upload_busy: /上传中/.test(document.body ? document.body.innerText || '' : '')
          || Array.from(document.querySelectorAll('.ecom-g-btn-loading-icon')).some(isVisible)
      };
    })();
    """
    try:
        result = tab.run_js(script) or {}
        return result if isinstance(result, dict) else {}
    except Exception as exc:
        return {'error': str(exc)}


def _ops_wait_main_video_upload_settled(tab, before_snapshot=None, timeout=20.0, interval=0.2):
    before_media_count = 0
    if isinstance(before_snapshot, dict):
        try:
            before_media_count = int(before_snapshot.get('media_count') or 0)
        except Exception:
            before_media_count = 0

    started_at = system_time.time()
    seen_busy = False
    idle_checks = 0
    last_snapshot = {}
    while system_time.time() - started_at < timeout:
        last_snapshot = _ops_main_video_field_snapshot(tab)
        busy = bool(last_snapshot.get('upload_busy'))
        try:
            busy = busy or bool(_is_upload_busy(tab))
        except Exception:
            pass
        if busy:
            seen_busy = True
            idle_checks = 0
        else:
            idle_checks += 1
            try:
                media_count = int(last_snapshot.get('media_count') or 0)
            except Exception:
                media_count = 0
            if idle_checks >= 3 and (seen_busy or media_count > before_media_count or system_time.time() - started_at >= 1.2):
                return {
                    'settled': True,
                    'seen_busy': seen_busy,
                    'duration_seconds': round(system_time.time() - started_at, 2),
                    'before_media_count': before_media_count,
                    'after_media_count': media_count,
                    'field_snapshot': last_snapshot,
                }
        system_time.sleep(interval)

    return {
        'settled': False,
        'seen_busy': seen_busy,
        'duration_seconds': round(system_time.time() - started_at, 2),
        'before_media_count': before_media_count,
        'after_media_count': int(last_snapshot.get('media_count') or 0) if isinstance(last_snapshot, dict) else 0,
        'field_snapshot': last_snapshot,
    }


@app.get('/api/ops/ai-policy')
def ops_ai_policy():
    return api_ok('外部 AI 已禁用', data={
        'ai_policy': dict(AI_POLICY),
        'model_configs': [],
    })


@app.get('/api/ops/health')
def ops_health_check():
    try:
        browsers = discover_debuggable_browsers(verify=True)
    except Exception as exc:
        browsers = []
        browser_discovery_error = str(exc)
    else:
        browser_discovery_error = None

    return api_ok('运营闭环健康检查完成', data={
        'target_net_profit': DAILY_NET_PROFIT_TARGET,
        'backend': {
            'status': 'ok',
            'mode': 'sidecar' if is_sidecar_mode() else 'gui',
            'port': get_sidecar_port() if is_sidecar_mode() else 5000,
        },
        'mcp': {
            'server_name': 'douyin-publisher',
            'backend_url': f'http://127.0.0.1:{get_sidecar_port() if is_sidecar_mode() else 5000}',
            'status': 'available_when_mcp_server_is_running',
        },
        'cdp': {
            'discoverable_browser_count': len(browsers),
            'browsers': browsers,
            'error': browser_discovery_error,
        },
        'browser': _ops_current_browser_snapshot(),
        'reusable_fxg_browser': _ops_reusable_fxg_browser_snapshot(),
        'ai_policy': dict(AI_POLICY),
        'safety_gates': [
            '登录与验证码由用户完成',
            '付款与投放扣费不自动确认',
            '最终发布确认保留人工安全闸',
            '未读到真实后台数据时不生成虚假利润结论',
        ],
    })


@app.post('/api/ops/publish-preflight-safety')
def ops_publish_preflight_safety():
    try:
        data = _ops_request_data()
        context = _ops_resolve_publish_preflight_context(data)
        action_id = context['action_id']
        preflight = context['preflight']

        updated_action = None
        events = []
        if action_id:
            existing_evidence = (
                (context['issue_action'] or {}).get('evidence')
                if isinstance(context['issue_action'], dict)
                else None
            )
            existing_upload_evidence = bool(
                isinstance(existing_evidence, dict)
                and (
                    existing_evidence.get('mutation_type') == 'main_video_upload_only'
                    or isinstance(existing_evidence.get('upload_result'), dict)
                )
            )
            note = (
                '上传前安全预检通过：仅允许在人工安全闸下上传素材并截停在保存/发布前'
                if preflight.get('ready_for_upload_preflight')
                else '上传前安全预检未通过：' + '；'.join(item.get('message', '') for item in preflight.get('blockers', []))
            )
            if existing_upload_evidence:
                note = str((context['issue_action'] or {}).get('action_note') or note)
            updated_action = get_ops_ledger().update_product_issue_action(
                action_id=action_id,
                action_status='in_progress',
                note=note,
                evidence=build_publish_preflight_evidence(
                    preflight,
                    record=context['record_context'],
                    issue_action=context['issue_action'],
                    existing_evidence=existing_evidence,
                ),
            )
            events = get_ops_ledger().list_product_issue_action_events(action_id=action_id, limit=5)

        return api_ok('发布前安全预检完成', data={
            'preflight': preflight,
            'page_snapshot': context['page_snapshot'],
            'record': context['record_context'],
            'issue_action': context['issue_action'],
            'updated_action': updated_action,
            'events': events,
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'发布前安全预检失败: {str(exc)}')


@app.post('/api/ops/upload-main-video-preflight')
def ops_upload_main_video_preflight():
    try:
        data = _ops_request_data()
        context = _ops_resolve_publish_preflight_context(data)
        action_id = context['action_id']
        preflight = context['preflight']
        initial_gate = build_main_video_upload_stop_gate(preflight)

        updated_action = None
        events = []
        if not initial_gate.get('ready_to_attempt_upload'):
            if action_id:
                updated_action = get_ops_ledger().update_product_issue_action(
                    action_id=action_id,
                    action_status='in_progress',
                    note='主图视频上传截停未执行：' + '；'.join(item.get('message', '') for item in initial_gate.get('blockers', [])),
                    evidence={
                        'preflight': preflight,
                        'upload_gate': initial_gate,
                        'record': context['record_context'],
                        'issue_action': context['issue_action'],
                        'shop_mutation': False,
                        'no_upload': True,
                        'no_save': True,
                        'no_publish': True,
                        'no_ad_or_payment': True,
                    },
                )
                events = get_ops_ledger().list_product_issue_action_events(action_id=action_id, limit=5)
            return api_error('主图视频上传截停安全闸未通过', data={
                'preflight': preflight,
                'upload_gate': initial_gate,
                'page_snapshot': context['page_snapshot'],
                'record': context['record_context'],
                'issue_action': context['issue_action'],
                'updated_action': updated_action,
                'events': events,
                'ai_policy': dict(AI_POLICY),
            })

        tab = _ops_current_or_reusable_fxg_tab()
        if not tab:
            return api_error('主图视频上传截停失败：未找到可复用的已登录抖店浏览器', data={
                'preflight': preflight,
                'upload_gate': initial_gate,
                'ai_policy': dict(AI_POLICY),
            })

        candidate_video_path = str(preflight.get('candidate_video_path') or '').strip()
        before_video_field = _ops_main_video_field_snapshot(tab)
        try:
            video_area = tab.ele('xpath://div[@attr-field-id="主图视频"]', timeout=3)
            if not video_area:
                raise Exception('未找到主图视频区域')
            video_area.scroll.to_see()
            video_area.scroll.to_center()
        except Exception as exc:
            return api_error(f'主图视频上传截停失败：{str(exc)}', data={
                'preflight': preflight,
                'upload_gate': initial_gate,
                'before_video_field': before_video_field,
                'ai_policy': dict(AI_POLICY),
            })

        upload_error = ''
        try:
            upload_file(
                tab,
                [candidate_video_path],
                '主图视频',
                target_field_id='主图视频',
                wait_for_finish=False,
            )
        except Exception as exc:
            upload_error = str(exc)

        settle_result = _ops_wait_main_video_upload_settled(tab, before_snapshot=before_video_field)
        upload_result = {
            'upload_triggered': not bool(upload_error),
            'upload_error': upload_error,
            'candidate_video_path': candidate_video_path,
            'before_video_field': before_video_field,
            'settle': settle_result,
            'upload_confirmed': bool(
                not upload_error
                and (
                    settle_result.get('seen_busy')
                    or int(settle_result.get('after_media_count') or 0) > int(settle_result.get('before_media_count') or 0)
                )
            ),
            'save_publish_performed': False,
            'no_save': True,
            'no_publish': True,
            'no_ad_or_payment': True,
        }
        post_upload_snapshot = _ops_publish_preflight_page_snapshot()
        upload_gate = build_main_video_upload_stop_gate(
            preflight,
            upload_attempted=True,
            upload_result=upload_result,
            post_upload_snapshot=post_upload_snapshot,
        )

        if action_id:
            note = (
                '主图视频已触发上传并在保存/发布前截停；未保存、未发布、未投放'
                if upload_result.get('upload_triggered')
                else f'主图视频上传触发失败并已截停：{upload_error}'
            )
            updated_action = get_ops_ledger().update_product_issue_action(
                action_id=action_id,
                action_status='in_progress',
                note=note,
                evidence={
                    'preflight': preflight,
                    'upload_gate': upload_gate,
                    'upload_result': upload_result,
                    'post_upload_snapshot': post_upload_snapshot,
                    'record': context['record_context'],
                    'issue_action': context['issue_action'],
                    'shop_mutation': bool(upload_result.get('upload_triggered')),
                    'mutation_type': 'main_video_upload_only' if upload_result.get('upload_triggered') else 'none',
                    'no_save': True,
                    'no_publish': True,
                    'no_ad_or_payment': True,
                },
            )
            events = get_ops_ledger().list_product_issue_action_events(action_id=action_id, limit=5)

        if upload_error or upload_gate.get('blockers'):
            return api_error('主图视频上传截停后校验未通过', data={
                'preflight': preflight,
                'upload_gate': upload_gate,
                'upload_result': upload_result,
                'post_upload_snapshot': post_upload_snapshot,
                'record': context['record_context'],
                'issue_action': context['issue_action'],
                'updated_action': updated_action,
                'events': events,
                'ai_policy': dict(AI_POLICY),
            })

        return api_ok('主图视频已触发上传并在保存/发布前截停', data={
            'preflight': preflight,
            'upload_gate': upload_gate,
            'upload_result': upload_result,
            'post_upload_snapshot': post_upload_snapshot,
            'record': context['record_context'],
            'issue_action': context['issue_action'],
            'updated_action': updated_action,
            'events': events,
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'主图视频上传截停失败: {str(exc)}')


@app.post('/api/ops/save-edit-human-gate')
def ops_save_edit_human_gate():
    try:
        data = _ops_request_data()
        context = _ops_resolve_publish_preflight_context(data)
        action_id = context['action_id']
        preflight = context['preflight']
        issue_action = context['issue_action'] if isinstance(context['issue_action'], dict) else {}
        upload_evidence = issue_action.get('evidence') if isinstance(issue_action.get('evidence'), dict) else {}

        tab = _ops_current_or_reusable_fxg_tab()
        if not tab:
            return api_error('保存前人工安全闸检查失败：未找到可复用的已登录抖店浏览器', data={
                'preflight': preflight,
                'ai_policy': dict(AI_POLICY),
            })

        main_video_field = _ops_main_video_field_snapshot(tab)
        page_snapshot = _ops_publish_preflight_page_snapshot()
        page_snapshot['main_video_field'] = main_video_field
        gate = build_save_edit_human_gate(
            preflight,
            upload_evidence=upload_evidence,
            page_snapshot=page_snapshot,
        )

        updated_action = None
        events = []
        if action_id:
            note = (
                '保存前人工安全闸已就绪：可请求用户确认保存当前编辑页；仍未自动保存、未发布、未投放'
                if gate.get('ready_for_human_save_confirmation')
                else '保存前人工安全闸未通过：' + '；'.join(item.get('message', '') for item in gate.get('blockers', []))
            )
            next_evidence = {
                **upload_evidence,
                'save_edit_human_gate': gate,
                'latest_preflight': preflight,
                'record': context['record_context'],
                'issue_action': {
                    key: value
                    for key, value in issue_action.items()
                    if key not in ('evidence', 'evidence_json')
                },
                'no_auto_save': True,
                'no_publish': True,
                'no_ad_or_payment': True,
            }
            updated_action = get_ops_ledger().update_product_issue_action(
                action_id=action_id,
                action_status='in_progress',
                note=note,
                evidence=next_evidence,
            )
            events = get_ops_ledger().list_product_issue_action_events(action_id=action_id, limit=5)

        return api_ok('保存前人工安全闸检查完成', data={
            'save_edit_human_gate': gate,
            'preflight': preflight,
            'page_snapshot': page_snapshot,
            'record': context['record_context'],
            'issue_action': context['issue_action'],
            'updated_action': updated_action,
            'events': events,
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'保存前人工安全闸检查失败: {str(exc)}')


@app.post('/api/ops/evaluate-product')
def ops_evaluate_product():
    try:
        data = _ops_request_data()
        record_id = _ops_int(data, 'record_id', _ops_int(data, 'recordId', 0))
        record, sku_list, record_context = _ops_record_context(record_id)
        defaults = _ops_pricing_defaults()
        title = str(data.get('title') or (record.title if record else '') or (record.name if record else '') or '')
        sale_price = _ops_float(data, 'sale_price', _ops_float(data, 'salePrice', _ops_first_sku_price(sku_list)))
        goods_cost = _ops_float(data, 'goods_cost', _ops_float(data, 'goodsCost', 0))
        evaluation = evaluate_product(ProductEvaluationInput(
            record_id=record_id,
            title=title,
            sale_price=sale_price,
            goods_cost=goods_cost,
            shipping_cost=_ops_float(data, 'shipping_cost', defaults['shipping_cost']),
            packaging_cost=_ops_float(data, 'packaging_cost', defaults['packaging_cost']),
            platform_commission_rate=_ops_float(data, 'platform_commission_rate', defaults['platform_commission_rate']),
            promotion_cost=_ops_float(data, 'promotion_cost', 0),
            refund_loss=_ops_float(data, 'refund_loss', 0),
            after_sale_loss=_ops_float(data, 'after_sale_loss', 0),
            expected_daily_orders=_ops_int(data, 'expected_daily_orders', 0),
        ))
        saved = get_ops_ledger().save_product_evaluation(evaluation)
        return api_ok('单品经营净利评估完成', data={
            'evaluation': asdict(evaluation),
            'saved_snapshot': saved,
            'record': record_context,
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'单品评估失败: {str(exc)}')


@app.post('/api/ops/stock-plan')
def ops_stock_plan():
    try:
        data = _ops_request_data()
        record_id = _ops_int(data, 'record_id', _ops_int(data, 'recordId', 0))
        _record, sku_list, record_context = _ops_record_context(record_id)
        sku_count = _ops_int(data, 'sku_count', len(sku_list) or 1)
        stock_plan = build_stock_plan(StockPlanInput(
            record_id=record_id,
            sku_count=sku_count,
            expected_daily_orders=_ops_int(data, 'expected_daily_orders', 0),
            replenishment_days=_ops_int(data, 'replenishment_days', 1),
            can_restock_same_day=bool(data.get('can_restock_same_day', True)),
            max_per_sku_without_sales_signal=_ops_int(data, 'max_per_sku_without_sales_signal', 2),
        ))
        saved = get_ops_ledger().save_stock_plan(stock_plan)
        return api_ok('备货建议已生成', data={
            'stock_plan': asdict(stock_plan),
            'saved_snapshot': saved,
            'record': record_context,
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'备货建议生成失败: {str(exc)}')


@app.post('/api/ops/product-candidates')
def ops_product_candidates():
    try:
        data = _ops_request_data()
        candidate_data = _ops_build_local_product_candidates(data)
        return api_ok('本地商品候选评估完成', data={
            'candidates': candidate_data['candidates'],
            'records': candidate_data['records'],
            'cost_defaults': candidate_data['cost_defaults'],
            'target_net_profit': DAILY_NET_PROFIT_TARGET,
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'本地商品候选评估失败: {str(exc)}')


@app.post('/api/ops/apply-candidate-pricing')
def ops_apply_candidate_pricing():
    try:
        data = _ops_request_data()
        record_id = _ops_int(data, 'record_id', _ops_int(data, 'recordId', 0))
        dry_run = bool(data.get('dry_run', data.get('dryRun', True)))
        if not record_id:
            return api_error('record_id 不能为空')
        record, sku_list, record_context = _ops_record_context(record_id)
        if not record:
            return api_error(f'商品不存在: {record_id}')

        candidate_data = _ops_build_local_product_candidates({
            **data,
            'limit': max(_ops_int(data, 'limit', 20), 20),
        })
        candidate = None
        for item in candidate_data['candidates']:
            if int(item.get('record_id') or 0) == record_id:
                candidate = item
                break
        if not candidate:
            return api_error(f'未生成商品候选: {record_id}')

        sale_price = _ops_float(data, 'sale_price', _ops_float(data, 'salePrice', candidate.get('recommended_sale_price', 0)))
        pricing_result = apply_candidate_pricing_to_skus(sku_list, sale_price)
        saved = False
        if not dry_run:
            record.content = json.dumps(pricing_result['skus'], ensure_ascii=False)
            record.update_time = time.now()
            record.save()
            saved = True

        refreshed_record, refreshed_skus, refreshed_context = _ops_record_context(record_id)
        return api_ok('候选商品售价应用完成' if saved else '候选商品售价 dry-run 完成', data={
            'dry_run': dry_run,
            'saved': saved,
            'record': refreshed_context or record_context,
            'candidate': candidate,
            'pricing': {
                'sale_price': pricing_result['sale_price'],
                'updated_count': pricing_result['updated_count'],
                'changes': pricing_result['changes'],
            },
            'current_sku_prices': [
                {
                    'name': sku.get('name'),
                    'price': sku.get('price'),
                    'ops_goods_cost': sku.get('ops_goods_cost'),
                }
                for sku in (refreshed_skus if saved else pricing_result['skus'])
                if isinstance(sku, dict)
            ],
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'候选商品售价应用失败: {str(exc)}')


@app.post('/api/ops/daily-plan')
def ops_daily_plan():
    try:
        data = _ops_request_data()
        metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else data
        if not metrics:
            latest = get_ops_ledger().list_daily_snapshots(limit=1)
            metrics = latest[0] if latest else {}
        diagnostic_signals = data.get('diagnostic_signals') or data.get('diagnosticSignals')
        if isinstance(diagnostic_signals, dict):
            metrics = {
                **(metrics or {}),
                'diagnostic_signals': diagnostic_signals,
            }
        plan = build_daily_plan(metrics)
        return api_ok('每日运营计划已生成', data={
            'daily_plan': plan,
            'source': 'request' if data else 'latest_snapshot',
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'每日运营计划生成失败: {str(exc)}')


@app.post('/api/ops/search-conversion-work-package')
def ops_search_conversion_work_package():
    try:
        data = _ops_request_data()
        ledger = get_ops_ledger()
        metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else None
        if metrics is None:
            latest = ledger.list_daily_snapshots(limit=1)
            metrics = latest[0] if latest else {}

        actions = data.get('product_issue_actions') or data.get('productIssueActions')
        if not isinstance(actions, list):
            actions = ledger.list_product_issue_actions(limit=max(min(_ops_int(data, 'limit', 100), 500), 1))

        package = build_search_conversion_work_package(
            metrics=metrics,
            product_issue_actions=actions,
            target_net_profit=_ops_float(data, 'target_net_profit', _ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
            action_id=_ops_int(data, 'action_id', _ops_int(data, 'actionId', 0)) or None,
        )
        return api_ok('搜索承接工作包已生成', data={
            'search_conversion_work_package': package,
            'metrics_source': 'request' if isinstance(data.get('metrics'), dict) else 'latest_snapshot',
            'actions_source': 'request' if isinstance(data.get('product_issue_actions') or data.get('productIssueActions'), list) else 'ledger',
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'搜索承接工作包生成失败: {str(exc)}')


@app.post('/api/ops/daily-review')
def ops_daily_review():
    try:
        data = _ops_request_data()
        metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
        if not metrics:
            latest = get_ops_ledger().list_daily_snapshots(limit=1)
            metrics = latest[0] if latest else {}
        diagnostic_signals = data.get('diagnostic_signals') or data.get('diagnosticSignals')
        if isinstance(diagnostic_signals, dict):
            metrics = {
                **(metrics or {}),
                'diagnostic_signals': diagnostic_signals,
            }
        candidate_data = _ops_build_local_product_candidates(data)
        review = build_daily_review(metrics, candidate_data['candidates'])
        return api_ok('每日经营复盘已生成', data={
            'review': review,
            'metrics_source': 'request' if isinstance(data.get('metrics'), dict) and data.get('metrics') else 'latest_snapshot',
            'candidates': candidate_data['candidates'],
            'records': candidate_data['records'],
            'cost_defaults': candidate_data['cost_defaults'],
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'每日经营复盘生成失败: {str(exc)}')


@app.post('/api/ops/detail-conversion-audit')
def ops_detail_conversion_audit():
    try:
        data = _ops_request_data()
        metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
        if not metrics:
            latest = get_ops_ledger().list_daily_snapshots(limit=1)
            metrics = latest[0] if latest else {}
        page_snapshot = data.get('page_snapshot') or data.get('pageSnapshot')
        if not isinstance(page_snapshot, dict):
            return api_error('page_snapshot 不能为空')
        audit = build_detail_conversion_audit(metrics, page_snapshot)
        product_title = str(data.get('product_title') or data.get('productTitle') or page_snapshot.get('product_title') or page_snapshot.get('productTitle') or '')
        suggestions = build_detail_improvement_suggestions(product_title, audit) if product_title else None
        return api_ok('详情承接审计完成', data={
            'audit': audit,
            'suggestions': suggestions,
            'metrics_source': 'request' if isinstance(data.get('metrics'), dict) and data.get('metrics') else 'latest_snapshot',
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'详情承接审计失败: {str(exc)}')


@app.post('/api/ops/conversion-asset-pack')
def ops_conversion_asset_pack():
    try:
        data = _ops_request_data()
        metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
        if not metrics:
            latest = get_ops_ledger().list_daily_snapshots(limit=1)
            metrics = latest[0] if latest else {}

        product = data.get('product') if isinstance(data.get('product'), dict) else {}
        detail_audit = data.get('detail_audit') or data.get('detailAudit')
        page_snapshot = data.get('page_snapshot') or data.get('pageSnapshot')
        if not isinstance(detail_audit, dict) and isinstance(page_snapshot, dict):
            detail_audit = build_detail_conversion_audit(metrics, page_snapshot)
        if not isinstance(detail_audit, dict):
            detail_audit = {}

        suggestions = data.get('suggestions') if isinstance(data.get('suggestions'), dict) else None
        if suggestions is None:
            title = str(product.get('title') or product.get('product_title') or product.get('productTitle') or '')
            suggestions = build_detail_improvement_suggestions(title, detail_audit) if title else None

        pack = build_conversion_asset_pack(
            product=product,
            audit=detail_audit,
            suggestions=suggestions,
            metrics=metrics,
            target_net_profit=_ops_float(data, 'target_net_profit', _ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
        )
        return api_ok('无品牌转化素材包已生成', data={
            'conversion_asset_pack': pack,
            'metrics_source': 'request' if isinstance(data.get('metrics'), dict) and data.get('metrics') else 'latest_snapshot',
            'detail_audit_source': 'request' if isinstance(data.get('detail_audit') or data.get('detailAudit'), dict) else ('page_snapshot' if isinstance(page_snapshot, dict) else 'empty'),
            'safe_to_auto_upload': False,
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'无品牌转化素材包生成失败: {str(exc)}')


@app.post('/api/ops/conversion-experiment-plan')
def ops_conversion_experiment_plan():
    try:
        data = _ops_request_data()
        metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
        if not metrics:
            latest = get_ops_ledger().list_daily_snapshots(limit=1)
            metrics = latest[0] if latest else {}

        detail_audit = data.get('detail_audit') or data.get('detailAudit')
        page_snapshot = data.get('page_snapshot') or data.get('pageSnapshot')
        if not isinstance(detail_audit, dict) and isinstance(page_snapshot, dict):
            detail_audit = build_detail_conversion_audit(metrics, page_snapshot)
        if not isinstance(detail_audit, dict):
            detail_audit = {}

        profit_plan = data.get('profit_plan') or data.get('profitPlan')
        if not isinstance(profit_plan, dict):
            candidate_data = _ops_build_local_product_candidates(data)
            profit_plan = build_profit_ramp_plan(metrics, candidate_data['candidates'])

        plan = build_conversion_experiment_plan(metrics, detail_audit, profit_plan)
        return api_ok('转化实验计划已生成', data={
            'conversion_experiment_plan': plan,
            'metrics_source': 'request' if isinstance(data.get('metrics'), dict) and data.get('metrics') else 'latest_snapshot',
            'detail_audit_source': 'request' if isinstance(data.get('detail_audit') or data.get('detailAudit'), dict) else ('page_snapshot' if isinstance(page_snapshot, dict) else 'empty'),
            'profit_plan_source': 'request' if isinstance(data.get('profit_plan') or data.get('profitPlan'), dict) else 'local_candidates',
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'转化实验计划生成失败: {str(exc)}')


@app.post('/api/ops/profit-ramp-plan')
def ops_profit_ramp_plan():
    try:
        data = _ops_request_data()
        metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
        if not metrics:
            latest = get_ops_ledger().list_daily_snapshots(limit=1)
            metrics = latest[0] if latest else {}
        candidate_data = _ops_build_local_product_candidates(data)
        plan = build_profit_ramp_plan(metrics, candidate_data['candidates'])
        return api_ok('日净利目标拆解已生成', data={
            'profit_ramp_plan': plan,
            'metrics_source': 'request' if isinstance(data.get('metrics'), dict) and data.get('metrics') else 'latest_snapshot',
            'candidate_count': len(candidate_data['candidates']),
            'top_candidate': candidate_data['candidates'][0] if candidate_data['candidates'] else None,
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'日净利目标拆解生成失败: {str(exc)}')


@app.post('/api/ops/profit-ladder-to-500')
def ops_profit_ladder_to_500():
    try:
        data = _ops_request_data()
        metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
        if not metrics:
            latest = get_ops_ledger().list_daily_snapshots(limit=1)
            metrics = latest[0] if latest else {}

        product = data.get('product') if isinstance(data.get('product'), dict) else {}
        cost_scenarios = data.get('cost_scenarios') or data.get('costScenarios')
        if not isinstance(cost_scenarios, list) or not cost_scenarios:
            cost_scenarios = [
                {'scenario_id': 'floor_quote', 'label': '低成本报价', 'goods_cost': 1.5},
                {'scenario_id': 'target_quote', 'label': '目标报价', 'goods_cost': 2.0},
                {'scenario_id': 'mid_quote', 'label': '中位报价', 'goods_cost': 5.0},
                {'scenario_id': 'high_quote', 'label': '高成本报价', 'goods_cost': 8.0},
            ]

        ladder = build_profit_ladder_to_500(
            metrics=metrics,
            product=product,
            cost_scenarios=cost_scenarios,
            target_net_profit=_ops_float(data, 'target_net_profit', _ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
        )
        return api_ok('500元净利阶梯已生成', data={
            'profit_ladder_to_500': ladder,
            'metrics_source': 'request' if isinstance(data.get('metrics'), dict) and data.get('metrics') else 'latest_snapshot',
            'scenario_count': len(cost_scenarios),
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'500元净利阶梯生成失败: {str(exc)}')


@app.post('/api/ops/sync-shop-metrics')
def ops_sync_shop_metrics():
    try:
        data = _ops_request_data()
        metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
        browser_snapshot = data.get('browser') if isinstance(data.get('browser'), dict) else _ops_current_browser_snapshot()
        audit_metrics = data.get('audit_metrics') if isinstance(data.get('audit_metrics'), list) else []
        ledger = get_ops_ledger()
        audit_rows = []

        if browser_snapshot.get('url') or browser_snapshot.get('title'):
            audit_rows.extend(ledger.save_browser_metric_audit([
                {
                    'metric_name': 'browser_page',
                    'metric_value': browser_snapshot.get('title') or '',
                    'page_url': browser_snapshot.get('url') or '',
                    'status': browser_snapshot.get('status') or 'observed',
                }
            ]))
        if audit_metrics:
            audit_rows.extend(ledger.save_browser_metric_audit(audit_metrics))

        if not metrics:
            return api_ok('浏览器状态已记录，但没有读取到经营指标；未生成利润快照', data={
                'synced': False,
                'browser': browser_snapshot,
                'audit_rows': audit_rows,
                'message': '需要在已登录抖店经营页面提供或读取订单、退款、推广等指标后再入账',
                'ai_policy': dict(AI_POLICY),
            })

        previous_snapshots = ledger.list_daily_snapshots(limit=10)
        metrics = merge_observed_shop_metrics(metrics, previous_snapshots)
        snapshot = ledger.save_daily_snapshot({
            'snapshot_date': metrics.get('snapshot_date'),
            'net_profit': metrics.get('net_profit', 0),
            'net_profit_verified': bool(metrics.get('net_profit_verified', 'net_profit' in metrics)),
            'gross_sales': metrics.get('gross_sales', 0),
            'orders_count': metrics.get('orders_count', 0),
            'product_exposure_count': metrics.get('product_exposure_count', 0),
            'product_click_count': metrics.get('product_click_count', 0),
            'search_exposure_count': metrics.get('search_exposure_count', 0),
            'refund_amount': metrics.get('refund_amount', 0),
            'after_sale_amount': metrics.get('after_sale_amount', 0),
            'promotion_cost': metrics.get('promotion_cost', 0),
            'experience_score': metrics.get('experience_score'),
            'source': metrics.get('source') or data.get('source') or 'browser',
            'status': metrics.get('status') or 'partial',
            'notes': metrics.get('notes') or '',
            'raw_payload': metrics.get('raw_payload') or data.get('raw_payload') or {},
        })
        plan = build_daily_plan(metrics)
        return api_ok('经营指标同步完成', data={
            'synced': True,
            'snapshot': snapshot,
            'daily_plan': plan,
            'browser': browser_snapshot,
            'audit_rows': audit_rows,
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'经营指标同步失败: {str(exc)}')


@app.post('/api/ops/sync-strategy-signals')
def ops_sync_strategy_signals():
    try:
        data = _ops_request_data()
        signals = data.get('signals')
        if not isinstance(signals, dict):
            signals = data.get('diagnostic_signals') or data.get('diagnosticSignals')
        if not isinstance(signals, dict) or not signals:
            return api_error('diagnostic_signals 不能为空')

        signals = dict(signals)
        if not signals.get('raw_payload') and data.get('raw_payload'):
            signals['raw_payload'] = data.get('raw_payload')
        if data.get('source') and not signals.get('source'):
            signals['source'] = data.get('source')

        ledger = get_ops_ledger()
        audit_metrics = data.get('audit_metrics') if isinstance(data.get('audit_metrics'), list) else []
        browser_snapshot = data.get('browser') if isinstance(data.get('browser'), dict) else {}
        audit_rows = []
        if browser_snapshot.get('url') or browser_snapshot.get('title'):
            audit_rows.extend(ledger.save_browser_metric_audit([
                {
                    'metric_name': 'strategy_browser_page',
                    'metric_value': browser_snapshot.get('title') or '',
                    'page_url': browser_snapshot.get('url') or '',
                    'status': browser_snapshot.get('status') or 'observed',
                }
            ]))
        if audit_metrics:
            audit_rows.extend(ledger.save_browser_metric_audit(audit_metrics))

        saved = ledger.save_strategy_snapshot(signals)
        latest = ledger.list_daily_snapshots(limit=1)
        metrics = latest[0] if latest else {}
        review_metrics = {
            **(metrics or {}),
            'diagnostic_signals': signals,
        }
        candidate_data = _ops_build_local_product_candidates(data)
        review = build_daily_review(review_metrics, candidate_data['candidates'])
        return api_ok('诊断信号同步完成', data={
            'synced': True,
            'saved_strategy_snapshot': saved['snapshot'],
            'product_issue_actions': saved['product_issue_actions'],
            'review': review,
            'metrics_source': 'latest_snapshot' if metrics else 'empty_snapshot',
            'audit_rows': audit_rows,
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'诊断信号同步失败: {str(exc)}')


@app.get('/api/ops/daily-snapshots')
def ops_daily_snapshots():
    try:
        limit = _ops_int(request.args, 'limit', 20)
        return api_ok('经营快照读取成功', data={
            'snapshots': get_ops_ledger().list_daily_snapshots(limit=limit),
            'target_net_profit': DAILY_NET_PROFIT_TARGET,
        })
    except Exception as exc:
        return api_error(f'经营快照读取失败: {str(exc)}')


@app.get('/api/ops/strategy-snapshots')
def ops_strategy_snapshots():
    try:
        limit = _ops_int(request.args, 'limit', 20)
        action_status = str(request.args.get('action_status') or request.args.get('actionStatus') or '').strip()
        ledger = get_ops_ledger()
        return api_ok('诊断快照读取成功', data={
            'snapshots': ledger.list_strategy_snapshots(limit=limit),
            'product_issue_actions': ledger.list_product_issue_actions(
                limit=limit,
                action_status=action_status or None,
            ),
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        return api_error(f'诊断快照读取失败: {str(exc)}')


@app.get('/api/ops/product-issue-actions')
def ops_product_issue_actions():
    try:
        limit = _ops_int(request.args, 'limit', 20)
        action_status = str(request.args.get('action_status') or request.args.get('actionStatus') or '').strip()
        action_id = _ops_int(request.args, 'action_id', _ops_int(request.args, 'actionId', 0))
        ledger = get_ops_ledger()
        return api_ok('商品问题待办读取成功', data={
            'product_issue_actions': ledger.list_product_issue_actions(
                limit=limit,
                action_status=action_status or None,
            ),
            'events': ledger.list_product_issue_action_events(
                action_id=action_id or None,
                limit=limit,
            ),
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        return api_error(f'商品问题待办读取失败: {str(exc)}')


@app.get('/api/ops/no-brand-title-audit')
def ops_no_brand_title_audit():
    try:
        limit = _ops_int(request.args, 'limit', 200)
        action_status = str(request.args.get('action_status') or request.args.get('actionStatus') or '').strip()
        actions = get_ops_ledger().list_product_issue_actions(
            limit=max(min(limit, 500), 1),
            action_status=action_status or None,
        )
        return api_ok('无品牌标题审计完成', data={
            'audit': build_no_brand_title_audit(actions),
            'source_action_count': len(actions),
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'无品牌标题审计失败: {str(exc)}')


@app.post('/api/ops/no-brand-remediation-plan')
def ops_no_brand_remediation_plan():
    try:
        data = _ops_request_data()
        limit = max(min(_ops_int(data, 'limit', 200), 500), 1)
        action_status = str(data.get('action_status') or data.get('actionStatus') or '').strip()
        actions = data.get('product_issue_actions') if isinstance(data.get('product_issue_actions'), list) else None
        if actions is None:
            actions = get_ops_ledger().list_product_issue_actions(
                limit=limit,
                action_status=action_status or None,
            )
        plan = build_no_brand_remediation_plan(actions)
        return api_ok('无品牌整改计划已生成', data={
            'no_brand_remediation_plan': plan,
            'source_action_count': len(actions),
            'actions_source': 'request' if isinstance(data.get('product_issue_actions'), list) else 'ledger',
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'无品牌整改计划生成失败: {str(exc)}')


@app.post('/api/ops/reconcile-strategy-actions')
def ops_reconcile_strategy_actions():
    try:
        data = _ops_request_data()
        limit = max(min(_ops_int(data, 'limit', 500), 500), 1)
        apply_updates = bool(data.get('apply', data.get('applyUpdates', False)))
        latest_strategy_snapshot_id = _ops_int(
            data,
            'latest_strategy_snapshot_id',
            _ops_int(data, 'latestStrategySnapshotId', 0),
        )
        ledger = get_ops_ledger()
        actions = data.get('product_issue_actions') if isinstance(data.get('product_issue_actions'), list) else None
        if actions is None:
            actions = ledger.list_product_issue_actions(limit=limit)
        plan = build_strategy_action_reconcile_plan(
            product_issue_actions=actions,
            latest_strategy_snapshot_id=latest_strategy_snapshot_id or None,
        )

        applied = []
        if apply_updates:
            for update in plan.get('local_ledger_updates') or []:
                if not isinstance(update, dict):
                    continue
                action_id = _ops_int(update, 'action_id', 0)
                action_status = str(update.get('recommended_status') or '').strip()
                if not action_id or not action_status:
                    continue
                applied.append(ledger.update_product_issue_action(
                    action_id=action_id,
                    action_status=action_status,
                    note=str(update.get('note') or ''),
                    evidence=update.get('evidence') if isinstance(update.get('evidence'), dict) else {},
                ))

        return api_ok('诊断待办状态对齐完成', data={
            'strategy_action_reconcile_plan': plan,
            'applied': applied,
            'applied_count': len(applied),
            'dry_run': not apply_updates,
            'actions_source': 'request' if isinstance(data.get('product_issue_actions'), list) else 'ledger',
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'诊断待办状态对齐失败: {str(exc)}')


@app.post('/api/ops/product-issue-actions/<int:action_id>')
def ops_update_product_issue_action(action_id):
    try:
        data = _ops_request_data()
        action_status = data.get('action_status') or data.get('actionStatus') or data.get('status')
        if not action_status:
            return api_error('action_status 不能为空')
        evidence = data.get('evidence') if isinstance(data.get('evidence'), dict) else {}
        updated = get_ops_ledger().update_product_issue_action(
            action_id=action_id,
            action_status=str(action_status),
            note=str(data.get('note') or data.get('action_note') or data.get('actionNote') or ''),
            evidence=evidence,
        )
        events = get_ops_ledger().list_product_issue_action_events(action_id=action_id, limit=5)
        return api_ok('商品问题待办状态已更新', data={
            'updated_action': updated,
            'events': events,
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'商品问题待办状态更新失败: {str(exc)}')


@app.post('/api/ops/sync-product-record-mappings')
def ops_sync_product_record_mappings():
    try:
        data = _ops_request_data()
        limit = max(min(_ops_int(data, 'limit', 50), 200), 1)
        min_confidence = _ops_float(data, 'min_confidence', _ops_float(data, 'minConfidence', 0.72))
        action_status = str(data.get('action_status') or data.get('actionStatus') or '').strip()
        ledger = get_ops_ledger()
        actions = data.get('product_issue_actions') if isinstance(data.get('product_issue_actions'), list) else None
        if actions is None:
            actions = ledger.list_product_issue_actions(
                limit=limit,
                action_status=action_status or None,
            )
        shop_products = []
        for action in actions:
            if not isinstance(action, dict):
                continue
            shop_products.append({
                'action_id': action.get('id') or action.get('action_id') or action.get('actionId'),
                'product_id': action.get('product_id') or action.get('productId'),
                'title': action.get('title') or '',
            })
        local_records = _ops_local_record_mapping_rows()
        mappings = build_product_record_mappings(
            shop_products=shop_products,
            local_records=local_records,
            min_confidence=min_confidence,
        )
        saved = ledger.save_product_record_mappings(mappings)
        summary = {
            'total': len(saved),
            'matched': len([item for item in saved if item.get('match_status') == 'matched']),
            'unmatched': len([item for item in saved if item.get('match_status') == 'unmatched']),
            'local_record_count': len(local_records),
        }
        return api_ok('线上商品与本地 Record 映射已生成', data={
            'summary': summary,
            'mappings': saved,
            'local_records': local_records,
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'线上商品与本地 Record 映射失败: {str(exc)}')


@app.get('/api/ops/product-record-mappings')
def ops_product_record_mappings():
    try:
        limit = _ops_int(request.args, 'limit', 20)
        match_status = str(request.args.get('match_status') or request.args.get('matchStatus') or '').strip()
        return api_ok('线上商品与本地 Record 映射读取成功', data={
            'mappings': get_ops_ledger().list_product_record_mappings(
                limit=limit,
                match_status=match_status or None,
            ),
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        return api_error(f'线上商品与本地 Record 映射读取失败: {str(exc)}')


@app.post('/api/ops/material-gap-plan')
def ops_material_gap_plan():
    try:
        data = _ops_request_data()
        limit = max(min(_ops_int(data, 'limit', 100), 500), 1)
        action_status = str(data.get('action_status') or data.get('actionStatus') or '').strip()
        ledger = get_ops_ledger()

        actions = data.get('product_issue_actions') if isinstance(data.get('product_issue_actions'), list) else None
        if actions is None:
            actions = ledger.list_product_issue_actions(
                limit=limit,
                action_status=action_status or None,
            )

        mappings = data.get('product_record_mappings') if isinstance(data.get('product_record_mappings'), list) else None
        if mappings is None:
            mappings = ledger.list_product_record_mappings(limit=limit)

        no_brand_audit = data.get('no_brand_audit') or data.get('noBrandAudit')
        if not isinstance(no_brand_audit, dict):
            no_brand_audit = None

        plan = build_material_gap_plan(actions, mappings, no_brand_audit=no_brand_audit)
        return api_ok('素材缺口采集计划已生成', data={
            'material_gap_plan': plan,
            'source_action_count': len(actions),
            'source_mapping_count': len(mappings),
            'actions_source': 'request' if isinstance(data.get('product_issue_actions'), list) else 'ledger',
            'mappings_source': 'request' if isinstance(data.get('product_record_mappings'), list) else 'ledger',
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'素材缺口采集计划生成失败: {str(exc)}')


@app.post('/api/ops/sourcing-profit-gate')
def ops_sourcing_profit_gate():
    try:
        data = _ops_request_data()
        product = _ops_product_from_action(data)
        if not product:
            return api_error('product 或 action_id 不能为空')

        scenarios = data.get('scenarios') if isinstance(data.get('scenarios'), list) else []
        gate = build_sourcing_profit_gate(
            product=product,
            scenarios=scenarios,
            target_net_profit=_ops_float(data, 'target_net_profit', _ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
        )
        return api_ok('采购利润闸已生成', data={
            'sourcing_profit_gate': gate,
            'scenario_count': len(scenarios),
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'采购利润闸生成失败: {str(exc)}')


@app.post('/api/ops/supplier-quote-plan')
def ops_supplier_quote_plan():
    try:
        data = _ops_request_data()
        product = _ops_product_from_action(data)
        if not product:
            return api_error('product 或 action_id 不能为空')

        sourcing_profit_gate = data.get('sourcing_profit_gate') or data.get('sourcingProfitGate')
        if not isinstance(sourcing_profit_gate, dict):
            scenarios = data.get('scenarios') if isinstance(data.get('scenarios'), list) else []
            sourcing_profit_gate = build_sourcing_profit_gate(product=product, scenarios=scenarios)
        supplier_candidates = data.get('supplier_candidates') or data.get('supplierCandidates')
        if not isinstance(supplier_candidates, list):
            supplier_candidates = []

        plan = build_supplier_quote_plan(product, sourcing_profit_gate, supplier_candidates)
        return api_ok('供应商询价计划已生成', data={
            'supplier_quote_plan': plan,
            'candidate_count': len(supplier_candidates),
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'供应商询价计划生成失败: {str(exc)}')


@app.post('/api/ops/supplier-quote-intake')
def ops_supplier_quote_intake():
    try:
        data = _ops_request_data()
        product = _ops_product_from_action(data)
        if not product:
            return api_error('product 或 action_id 不能为空')

        supplier_quote = data.get('supplier_quote') or data.get('supplierQuote')
        if not isinstance(supplier_quote, dict):
            return api_error('supplier_quote 不能为空')

        sourcing_profit_gate = data.get('sourcing_profit_gate') or data.get('sourcingProfitGate')
        if not isinstance(sourcing_profit_gate, dict):
            scenarios = data.get('scenarios') if isinstance(data.get('scenarios'), list) else []
            sourcing_profit_gate = build_sourcing_profit_gate(product=product, scenarios=scenarios)

        intake = build_supplier_quote_intake(
            product=product,
            sourcing_profit_gate=sourcing_profit_gate,
            supplier_quote=supplier_quote,
            target_net_profit=_ops_float(data, 'target_net_profit', _ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
        )
        return api_ok('供应商报价回传判定已生成', data={
            'supplier_quote_intake': intake,
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'供应商报价回传判定失败: {str(exc)}')


@app.post('/api/ops/execution-queue')
def ops_execution_queue():
    try:
        data = _ops_request_data()
        limit = max(min(_ops_int(data, 'limit', 100), 500), 1)
        action_status = str(data.get('action_status') or data.get('actionStatus') or '').strip()
        ledger = get_ops_ledger()

        metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else None
        if metrics is None:
            latest = ledger.list_daily_snapshots(limit=1)
            metrics = latest[0] if latest else {}

        actions = data.get('product_issue_actions') if isinstance(data.get('product_issue_actions'), list) else None
        if actions is None:
            actions = ledger.list_product_issue_actions(
                limit=limit,
                action_status=action_status or None,
            )

        material_gap_plan = data.get('material_gap_plan') or data.get('materialGapPlan')
        if not isinstance(material_gap_plan, dict):
            mappings = data.get('product_record_mappings') if isinstance(data.get('product_record_mappings'), list) else None
            if mappings is None:
                mappings = ledger.list_product_record_mappings(limit=limit)
            no_brand_audit = data.get('no_brand_audit') or data.get('noBrandAudit')
            if not isinstance(no_brand_audit, dict):
                no_brand_audit = None
            material_gap_plan = build_material_gap_plan(actions, mappings, no_brand_audit=no_brand_audit)

        supplier_quote_plan = (
            data.get('supplier_quote_plan')
            or data.get('supplierQuotePlan')
            or data.get('supplier_quote_plans')
            or data.get('supplierQuotePlans')
        )
        conversion_experiment_plan = data.get('conversion_experiment_plan') or data.get('conversionExperimentPlan')
        if not isinstance(conversion_experiment_plan, dict):
            conversion_experiment_plan = None

        queue = build_ops_execution_queue(
            metrics=metrics,
            product_issue_actions=actions,
            material_gap_plan=material_gap_plan,
            supplier_quote_plan=supplier_quote_plan,
            conversion_experiment_plan=conversion_experiment_plan,
            target_net_profit=_ops_float(data, 'target_net_profit', _ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
        )
        return api_ok('运营执行队列已生成', data={
            'execution_queue': queue,
            'metrics_source': 'request' if isinstance(data.get('metrics'), dict) else 'latest_snapshot',
            'actions_source': 'request' if isinstance(data.get('product_issue_actions'), list) else 'ledger',
            'source_action_count': len(actions),
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'运营执行队列生成失败: {str(exc)}')


@app.post('/api/ops/portfolio-path-to-500')
def ops_portfolio_path_to_500():
    try:
        data = _ops_request_data()
        limit = max(min(_ops_int(data, 'limit', 100), 500), 1)
        action_status = str(data.get('action_status') or data.get('actionStatus') or '').strip()
        ledger = get_ops_ledger()

        metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else None
        if metrics is None:
            latest = ledger.list_daily_snapshots(limit=1)
            metrics = latest[0] if latest else {}

        actions = data.get('product_issue_actions') or data.get('productIssueActions')
        if not isinstance(actions, list):
            actions = ledger.list_product_issue_actions(
                limit=limit,
                action_status=action_status or None,
            )

        plan = build_portfolio_path_to_500(
            metrics=metrics,
            product_issue_actions=actions,
            target_net_profit=_ops_float(data, 'target_net_profit', _ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
        )
        return api_ok('500元组合路径已生成', data={
            'portfolio_path_to_500': plan,
            'metrics_source': 'request' if isinstance(data.get('metrics'), dict) else 'latest_snapshot',
            'actions_source': 'request' if isinstance(data.get('product_issue_actions') or data.get('productIssueActions'), list) else 'ledger',
            'source_action_count': len(actions),
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'500元组合路径生成失败: {str(exc)}')


@app.post('/api/ops/first-order-decision-matrix')
def ops_first_order_decision_matrix():
    try:
        data = _ops_request_data()
        ledger = get_ops_ledger()

        baseline_metrics = data.get('baseline_metrics') or data.get('baselineMetrics')
        if not isinstance(baseline_metrics, dict):
            latest = ledger.list_daily_snapshots(limit=1)
            baseline_metrics = latest[0] if latest else {}

        current_metrics = data.get('current_metrics') or data.get('currentMetrics') or data.get('metrics')
        if not isinstance(current_metrics, dict):
            current_metrics = baseline_metrics

        action = data.get('action') if isinstance(data.get('action'), dict) else None
        action_id = _ops_int(data, 'action_id', _ops_int(data, 'actionId', 0))
        if action is None and action_id:
            actions = ledger.list_product_issue_actions(limit=500)
            for row in actions:
                if int(row.get('id') or 0) == int(action_id):
                    action = row
                    break
        if action is None:
            action = {}

        save_gate = data.get('save_gate') or data.get('saveGate')
        if not isinstance(save_gate, dict):
            evidence = action.get('evidence') if isinstance(action.get('evidence'), dict) else {}
            save_gate = evidence.get('save_edit_human_gate') if isinstance(evidence.get('save_edit_human_gate'), dict) else {}

        matrix = build_first_order_decision_matrix(
            baseline_metrics=baseline_metrics,
            current_metrics=current_metrics,
            action=action,
            save_gate=save_gate,
            target_net_profit=_ops_float(data, 'target_net_profit', _ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
            saved_confirmed=bool(data.get('saved_confirmed') if 'saved_confirmed' in data else data.get('savedConfirmed', False)),
        )
        return api_ok('首单决策矩阵已生成', data={
            'first_order_decision_matrix': matrix,
            'baseline_metrics_source': 'request' if isinstance(data.get('baseline_metrics') or data.get('baselineMetrics'), dict) else 'latest_snapshot',
            'current_metrics_source': 'request' if isinstance(data.get('current_metrics') or data.get('currentMetrics') or data.get('metrics'), dict) else 'baseline_metrics',
            'action_source': 'request' if isinstance(data.get('action'), dict) else ('ledger' if action_id else 'empty'),
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'首单决策矩阵生成失败: {str(exc)}')


@app.post('/api/ops/net-profit-verification-matrix')
def ops_net_profit_verification_matrix():
    try:
        data = _ops_request_data()
        orders = data.get('orders') if isinstance(data.get('orders'), list) else []
        matrix = build_net_profit_verification_matrix(
            orders=orders,
            target_net_profit=_ops_float(data, 'target_net_profit', _ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
        )
        return api_ok('经营净利核验矩阵已生成', data={
            'net_profit_verification_matrix': matrix,
            'orders_source': 'request' if isinstance(data.get('orders'), list) else 'empty',
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'经营净利核验矩阵生成失败: {str(exc)}')


@app.post('/api/ops/post-save-conversion-monitor')
def ops_post_save_conversion_monitor():
    try:
        data = _ops_request_data()
        ledger = get_ops_ledger()

        metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else None
        if metrics is None:
            latest = ledger.list_daily_snapshots(limit=1)
            metrics = latest[0] if latest else {}

        action = data.get('action') if isinstance(data.get('action'), dict) else None
        action_id = _ops_int(data, 'action_id', _ops_int(data, 'actionId', 0))
        if action is None and action_id > 0:
            actions = ledger.list_product_issue_actions(limit=500)
            action = next(
                (item for item in actions if int(item.get('id') or 0) == action_id),
                {},
            )
        if action is None:
            action = {}

        save_gate = data.get('save_gate') or data.get('saveGate')
        if not isinstance(save_gate, dict):
            save_gate = {}
        if not save_gate and isinstance(action, dict):
            action_evidence = action.get('evidence')
            if not isinstance(action_evidence, dict):
                evidence_json = action.get('evidence_json')
                if evidence_json:
                    try:
                        parsed_evidence = json.loads(str(evidence_json))
                        action_evidence = parsed_evidence if isinstance(parsed_evidence, dict) else {}
                    except Exception:
                        action_evidence = {}
            if isinstance(action_evidence, dict) and isinstance(action_evidence.get('save_edit_human_gate'), dict):
                save_gate = dict(action_evidence.get('save_edit_human_gate') or {})

        conversion_experiment_plan = data.get('conversion_experiment_plan') or data.get('conversionExperimentPlan')
        if not isinstance(conversion_experiment_plan, dict):
            conversion_experiment_plan = None

        raw_saved_confirmed = data.get('saved_confirmed', data.get('savedConfirmed', False))
        saved_confirmed = (
            raw_saved_confirmed is True
            or str(raw_saved_confirmed).strip().lower() in {'1', 'true', 'yes', 'y'}
        )

        monitor = build_post_save_conversion_monitor(
            metrics=metrics,
            action=action,
            save_gate=save_gate,
            conversion_experiment_plan=conversion_experiment_plan,
            target_net_profit=_ops_float(data, 'target_net_profit', _ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
            saved_confirmed=saved_confirmed,
        )
        return api_ok('保存后转化复盘闸已生成', data={
            'post_save_conversion_monitor': monitor,
            'metrics_source': 'request' if isinstance(data.get('metrics'), dict) else 'latest_snapshot',
            'action_source': 'request' if isinstance(data.get('action'), dict) else ('ledger' if action_id > 0 else 'empty'),
            'ai_policy': dict(AI_POLICY),
        })
    except Exception as exc:
        traceback.print_exc()
        return api_error(f'保存后转化复盘闸生成失败: {str(exc)}')


@app.post('/internal/terminate')
def terminate_backend():
    remote_addr = str(request.remote_addr or '').strip()
    if remote_addr not in {'127.0.0.1', '::1', '::ffff:127.0.0.1'}:
        return jsonify({
            'success': False,
            'message': 'forbidden',
        }), 403

    def _shutdown_later():
        system_time.sleep(0.2)
        if is_sidecar_mode():
            _request_sidecar_shutdown('收到本地终止请求', exit_code=0)
        os._exit(0)

    threading.Thread(target=_shutdown_later, daemon=True).start()
    return jsonify({
        'success': True,
        'message': 'terminating',
    })


def _debug_now_iso():
    return datetime.now().isoformat()


def _debug_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _debug_int(value, default, minimum=None, maximum=None):
    try:
        number = int(value)
    except Exception:
        number = default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _debug_normalize_text(value, limit=300):
    text = ' '.join(str(value or '').split())
    if limit and len(text) > limit:
        return text[:limit] + '...'
    return text


def _debug_slug(value):
    raw = str(value or 'debug')
    chars = []
    for ch in raw:
        if ch.isalnum():
            chars.append(ch.lower())
        else:
            chars.append('_')
    slug = ''.join(chars).strip('_')
    while '__' in slug:
        slug = slug.replace('__', '_')
    return slug[:64] or 'debug'


def _debug_root_dir():
    if getattr(sys, 'frozen', False):
        base_dir = get_app_root()
    else:
        base_dir = repo_root
    target = os.path.join(base_dir, 'output', 'browser-debug')
    os.makedirs(target, exist_ok=True)
    return target


def _create_browser_debug_session(label='manual'):
    session_id = f"{_debug_slug(label)}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    artifacts_dir = os.path.join(_debug_root_dir(), session_id)
    os.makedirs(artifacts_dir, exist_ok=True)
    session = {
        'session_id': session_id,
        'label': label,
        'created_at': _debug_now_iso(),
        'updated_at': _debug_now_iso(),
        'artifacts_dir': artifacts_dir,
        'events': [],
    }

    with _browser_debug_lock:
        _browser_debug_state['sessions'][session_id] = session
        _browser_debug_state['current_session_id'] = session_id

        ordered_ids = sorted(
            _browser_debug_state['sessions'].keys(),
            key=lambda item: _browser_debug_state['sessions'][item].get('created_at', '')
        )
        while len(ordered_ids) > _BROWSER_DEBUG_MAX_SESSIONS:
            stale_id = ordered_ids.pop(0)
            _browser_debug_state['sessions'].pop(stale_id, None)
            if _browser_debug_state.get('current_session_id') == stale_id:
                _browser_debug_state['current_session_id'] = None

    return session


def _get_browser_debug_session(create=False, label='manual'):
    with _browser_debug_lock:
        current_id = _browser_debug_state.get('current_session_id')
        session = _browser_debug_state['sessions'].get(current_id) if current_id else None

    if session or not create:
        return session
    return _create_browser_debug_session(label=label)


def _append_browser_debug_event(event_type, message, data=None, session_id=None):
    session = None
    with _browser_debug_lock:
        resolved_session_id = session_id or _browser_debug_state.get('current_session_id')
        if resolved_session_id:
            session = _browser_debug_state['sessions'].get(resolved_session_id)
        if not session:
            return None

        event = {
            'timestamp': _debug_now_iso(),
            'type': event_type,
            'message': message,
            'data': data or {},
        }
        session['events'].append(event)
        if len(session['events']) > _BROWSER_DEBUG_MAX_EVENTS:
            session['events'] = session['events'][-_BROWSER_DEBUG_MAX_EVENTS:]
        session['updated_at'] = event['timestamp']
        return copy.deepcopy(event)


def _set_last_browser_debug_error(report):
    with _browser_debug_lock:
        _browser_debug_state['last_error'] = copy.deepcopy(report)


def _get_last_browser_debug_error():
    with _browser_debug_lock:
        report = _browser_debug_state.get('last_error')
        return copy.deepcopy(report) if report else None


def _set_browser_debug_instance(instance):
    with _browser_debug_lock:
        _browser_debug_state['browser_instance'] = copy.deepcopy(instance) if instance else None


def _get_browser_debug_instance():
    with _browser_debug_lock:
        instance = _browser_debug_state.get('browser_instance')
        return copy.deepcopy(instance) if instance else None


def _latest_browser_debug_error_after(started_at=None):
    report = _get_last_browser_debug_error()
    if not report:
        return None
    if not started_at:
        return report
    captured_at = report.get('captured_at')
    if captured_at and captured_at >= started_at:
        return report
    return None


def _serialize_browser_debug_session(session, include_events=False, recent_event_count=20):
    if not session:
        return None
    data = {
        'session_id': session.get('session_id'),
        'label': session.get('label'),
        'created_at': session.get('created_at'),
        'updated_at': session.get('updated_at'),
        'artifacts_dir': session.get('artifacts_dir'),
        'event_count': len(session.get('events', [])),
    }
    if include_events:
        data['events'] = session.get('events', [])[-recent_event_count:]
    return data


def _find_debug_browser_process(debug_address):
    normalized_address = _normalize_debug_address(debug_address or '')
    if not normalized_address:
        return None

    for item in discover_debuggable_browsers(verify=False):
        current_address = _normalize_debug_address(item.get('debug_address') or '')
        if current_address == normalized_address:
            return item
    return None


def _get_default_debug_browser_user_data_dir(profile_name='default'):
    safe_profile = _debug_slug(profile_name or 'default') or 'default'
    target = os.path.join(_debug_root_dir(), 'profiles', safe_profile)
    os.makedirs(target, exist_ok=True)
    return target


def _is_local_port_available(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _get_capture_browser_user_data_path():
    from src.runtime_paths import get_data_dir, get_runtime_root

    data_dir = get_data_dir(create=True)
    base_dir = data_dir if data_dir is not None else (get_runtime_root() / 'runtime')
    profile_dir = base_dir / 'capture-browser-profile'
    profile_dir.mkdir(parents=True, exist_ok=True)
    return str(profile_dir)


def _select_capture_browser_port():
    for port in range(_CAPTURE_BROWSER_PORT_START, _CAPTURE_BROWSER_PORT_END + 1):
        debug_address = f'{_DEBUG_BROWSER_HOST}:{port}'
        verification = _verify_debug_browser(debug_address, timeout=0.2)
        if verification.get('ok'):
            return port
        if _is_local_port_available(_DEBUG_BROWSER_HOST, port):
            return port
    raise Exception('未找到可用的采集浏览器调试端口')


def _select_debug_browser_port(port=None):
    if port is not None:
        try:
            resolved_port = int(port)
        except Exception:
            raise Exception(f'Invalid debug port: {port}')
        if resolved_port < 1 or resolved_port > 65535:
            raise Exception(f'Invalid debug port: {resolved_port}')

        debug_address = f'{_DEBUG_BROWSER_HOST}:{resolved_port}'
        verification = _verify_debug_browser(debug_address, timeout=0.5)
        if verification.get('ok'):
            return {
                'port': resolved_port,
                'debug_address': debug_address,
                'verification': verification,
                'reused_existing': True,
            }
        if not _is_local_port_available(_DEBUG_BROWSER_HOST, resolved_port):
            raise Exception(f'Port {resolved_port} is already in use by another process.')
        return {
            'port': resolved_port,
            'debug_address': debug_address,
            'verification': None,
            'reused_existing': False,
        }

    for candidate in range(_DEBUG_BROWSER_PORT_START, _DEBUG_BROWSER_PORT_END + 1):
        debug_address = f'{_DEBUG_BROWSER_HOST}:{candidate}'
        verification = _verify_debug_browser(debug_address, timeout=0.5)
        if verification.get('ok'):
            return {
                'port': candidate,
                'debug_address': debug_address,
                'verification': verification,
                'reused_existing': True,
            }
        if _is_local_port_available(_DEBUG_BROWSER_HOST, candidate):
            return {
                'port': candidate,
                'debug_address': debug_address,
                'verification': None,
                'reused_existing': False,
            }

    raise Exception('No available debug port was found in the configured range.')


def _resolve_debug_browser_launch_path(browser_path=None):
    candidate = os.path.abspath(str(browser_path).strip()) if browser_path else ''
    if candidate:
        if not os.path.exists(candidate):
            raise Exception(f'Browser executable was not found: {candidate}')
        return candidate

    detected = get_chrome_path()
    if detected:
        detected = os.path.abspath(detected)
        if os.path.exists(detected):
            return detected

    raise Exception('Chrome executable was not found. Provide browser_path explicitly.')


def _launch_attachable_debug_browser(
    browser_path=None,
    port=None,
    url=None,
    user_data_dir=None,
    profile_name='default',
    timeout=10.0,
    reuse_existing=True,
):
    selection = _select_debug_browser_port(port=port)
    debug_address = selection['debug_address']
    effective_url = (url or '').strip() or 'about:blank'
    target_user_data_dir = os.path.abspath(
        user_data_dir or _get_default_debug_browser_user_data_dir(profile_name=profile_name)
    )
    os.makedirs(target_user_data_dir, exist_ok=True)

    if selection['reused_existing']:
        if not reuse_existing:
            raise Exception(f'Debug browser is already running at {debug_address}.')
        existing_browser = _find_debug_browser_process(debug_address) or {}
        return {
            'debug_address': debug_address,
            'port': selection['port'],
            'pid': existing_browser.get('pid'),
            'browser_name': existing_browser.get('browser_name'),
            'browser_path': existing_browser.get('browser_path') or existing_browser.get('exe'),
            'user_data_dir': existing_browser.get('user_data_dir') or target_user_data_dir,
            'profile_directory': existing_browser.get('profile_directory') or '',
            'url': effective_url,
            'launched': False,
            'reused_existing': True,
            'verification': selection['verification'],
            'profile_name': profile_name or 'default',
        }

    resolved_browser_path = _resolve_debug_browser_launch_path(browser_path=browser_path)
    command = [
        resolved_browser_path,
        f'--remote-debugging-port={selection["port"]}',
        f'--user-data-dir={target_user_data_dir}',
        '--no-first-run',
        '--no-default-browser-check',
        effective_url,
    ]

    creationflags = 0
    if os.name == 'nt':
        creationflags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)

    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    deadline = system_time.time() + max(1.0, float(timeout))
    last_error = 'timeout'
    while system_time.time() < deadline:
        if process.poll() is not None:
            raise Exception(f'Debug browser exited early with code {process.returncode}.')

        verification = _verify_debug_browser(debug_address, timeout=0.5)
        if verification.get('ok'):
            attached_browser = _find_debug_browser_process(debug_address) or {}
            return {
                'debug_address': debug_address,
                'port': selection['port'],
                'pid': attached_browser.get('pid') or process.pid,
                'browser_name': attached_browser.get('browser_name') or 'Chrome',
                'browser_path': attached_browser.get('browser_path') or attached_browser.get('exe') or resolved_browser_path,
                'user_data_dir': attached_browser.get('user_data_dir') or target_user_data_dir,
                'profile_directory': attached_browser.get('profile_directory') or '',
                'url': effective_url,
                'launched': True,
                'reused_existing': False,
                'verification': verification,
                'profile_name': profile_name or 'default',
            }

        last_error = verification.get('error') or last_error
        system_time.sleep(0.25)

    try:
        process.kill()
    except Exception:
        pass
    raise Exception(f'Debug browser did not become ready at {debug_address}: {last_error}')


def _get_gui_page_debug_address():
    if not gui.page:
        return ''
    try:
        browser = getattr(gui.page, 'browser', None)
        return getattr(browser, 'address', '') or getattr(gui.page, 'address', '') or ''
    except Exception:
        return ''


def _get_current_browser_tab(create_if_missing=False, url=None, navigate=False, mode='managed', debug_address=None, existing_only=False):
    meta = {
        'mode': mode or 'managed',
        'created_browser': False,
        'reused_browser': False,
        'attached_browser': False,
        'navigated': False,
        'debug_address': '',
    }
    target_url = url or _BROWSER_DEBUG_DEFAULT_URL
    mode = str(mode or 'managed').strip().lower()

    if mode not in ('managed', 'attach'):
        raise Exception(f'Unsupported browser mode: {mode}')

    if mode == 'attach':
        normalized_address = _normalize_debug_address(debug_address or '')
        if not normalized_address:
            raise Exception('Attach mode requires debug_address.')

        current_address = _normalize_debug_address(_get_gui_page_debug_address())
        if not gui.page or current_address != normalized_address:
            gui.page = attach_existing_debug_browser(normalized_address, existing_only=existing_only or True)
            meta['attached_browser'] = True
        meta['debug_address'] = normalized_address
        browser_info = _find_debug_browser_process(normalized_address) or {}
        existing_instance = _get_browser_debug_instance() or {}
        if _normalize_debug_address(existing_instance.get('debug_address') or '') != normalized_address:
            existing_instance = {}
        _set_browser_debug_instance({
            **existing_instance,
            'debug_address': normalized_address,
            'pid': browser_info.get('pid') or existing_instance.get('pid'),
            'browser_name': browser_info.get('browser_name') or existing_instance.get('browser_name'),
            'browser_path': browser_info.get('browser_path') or browser_info.get('exe') or existing_instance.get('browser_path'),
            'user_data_dir': browser_info.get('user_data_dir') or existing_instance.get('user_data_dir'),
            'profile_directory': browser_info.get('profile_directory') or existing_instance.get('profile_directory'),
            'source': existing_instance.get('source') or 'attach',
            'updated_at': _debug_now_iso(),
        })
    elif not gui.page:
        if not create_if_missing:
            return None, meta
        gui.page = get_page(target_url)
        meta['created_browser'] = True
        meta['navigated'] = True
        _set_browser_debug_instance(None)

    try:
        tab = gui.page.get_tab(gui.page.latest_tab)
        meta['reused_browser'] = not meta['created_browser'] and not meta['attached_browser']
    except Exception:
        if mode == 'attach':
            raise
        if not create_if_missing:
            raise
        gui.page = get_page(target_url)
        meta['created_browser'] = True
        meta['reused_browser'] = False
        meta['navigated'] = True
        tab = gui.page.get_tab(gui.page.latest_tab)
        _set_browser_debug_instance(None)

    if not meta.get('debug_address'):
        meta['debug_address'] = _normalize_debug_address(_get_gui_page_debug_address())

    if navigate and url:
        tab.get(url)
        meta['navigated'] = True

    return tab, meta


def _collect_browser_page_bits(tab, max_fields=30, max_controls=30):
    script = """
    const maxFields = %d;
    const maxControls = %d;
    const maxOverlays = 12;
    const normalize = (value, limit = 160) => String(value || '').replace(/\\s+/g, ' ').trim().slice(0, limit);
    const isVisible = (el) => {
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
    };
    const fieldItems = Array.from(document.querySelectorAll('[attr-field-id]'))
      .filter(isVisible)
      .slice(0, maxFields)
      .map((el, index) => ({
        index,
        field_id: el.getAttribute('attr-field-id') || '',
        text: normalize(el.innerText, 180)
      }));
    const controlItems = Array.from(document.querySelectorAll('button, input, textarea, select, [role="button"]'))
      .filter(isVisible)
      .slice(0, maxControls)
      .map((el, index) => ({
        index,
        tag: (el.tagName || '').toLowerCase(),
        type: el.getAttribute('type') || '',
        text: normalize(el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '', 140),
        value: normalize(el.value || '', 80),
        attr_field_id: el.getAttribute('attr-field-id') || ''
      }));
    const overlayItems = Array.from(document.querySelectorAll(
      '[role="dialog"], .ecom-g-modal, .ecom-g-popover, [class*="guide"], [class*="Guide"], [class*="tour"], [class*="Tour"], [class*="coach"], [class*="Coach"]'
    ))
      .filter(isVisible)
      .slice(0, maxOverlays)
      .map((el, index) => ({
        index,
        tag: (el.tagName || '').toLowerCase(),
        class_name: el.className || '',
        role: el.getAttribute('role') || '',
        text: normalize(el.innerText || el.getAttribute('aria-label') || '', 220)
      }));
    const hasVisibleNode = (selectors) => selectors.some((selector) => {
      try {
        return Array.from(document.querySelectorAll(selector)).some(isVisible);
      } catch (error) {
        return false;
      }
    });
    const uploadSignals = {
      upload_busy: hasVisibleNode(['.ecom-g-btn-loading-icon']) || /上传中/.test(document.body ? document.body.innerText || '' : ''),
      crop_popup_visible: hasVisibleNode(['.ecom-g-modal-title', '.ecom-g-modal']),
      ai_material_tool_visible: hasVisibleNode(['.auxo-drawer-wrapper-body', '.ecom-g-modal', '[class*="drawer"]', '[class*="Drawer"]']),
      smart_crop_prompt_visible: hasVisibleNode(['[role="dialog"]', '.ecom-g-modal']),
      visible_local_upload_count: Array.from(document.querySelectorAll('label, button, div'))
        .filter(isVisible)
        .filter((el) => normalize(el.innerText || el.getAttribute('aria-label') || '', 40).includes('本地上传'))
        .length
    };
    uploadSignals.crop_popup_visible = uploadSignals.crop_popup_visible && /图片裁剪/.test(document.body ? document.body.innerText || '' : '');
    uploadSignals.ai_material_tool_visible = uploadSignals.ai_material_tool_visible && /AI素材工具/.test(document.body ? document.body.innerText || '' : '');
    uploadSignals.smart_crop_prompt_visible = uploadSignals.smart_crop_prompt_visible && /智能裁剪为1:1主图|当前还有.*不是1:1比例/.test(document.body ? document.body.innerText || '' : '');
    return {
      url: location.href,
      title: document.title,
      ready_state: document.readyState,
      scroll: { x: window.scrollX, y: window.scrollY },
      field_items: fieldItems,
      control_items: controlItems,
      overlay_items: overlayItems,
      upload_signals: uploadSignals
    };
    """ % (max_fields, max_controls)

    try:
        return tab.run_js(script) or {}
    except Exception:
        return {}


def _normalize_debug_locator(locator, locator_type='raw'):
    value = str(locator or '').strip()
    if not value:
        raise Exception('Locator is required.')
    locator_type = str(locator_type or 'raw').strip().lower()
    if locator_type == 'css':
        return value if value.startswith('css:') else f'css:{value}'
    if locator_type == 'xpath':
        return value if value.startswith('xpath:') else f'xpath:{value}'
    return value


def _summarize_debug_element(element, index, include_html=False):
    summary = {
        'index': index,
        'text': '',
        'tag': '',
        'id': '',
        'class_name': '',
        'attr_field_id': '',
        'value': '',
        'placeholder': '',
        'displayed': False,
    }

    try:
        summary['text'] = _debug_normalize_text(element.text, 240)
    except Exception:
        pass
    try:
        summary['tag'] = _debug_normalize_text(
            element.run_js('return (this.tagName || "").toLowerCase();'),
            40
        )
    except Exception:
        pass

    for attr_name, key_name in (
        ('id', 'id'),
        ('class', 'class_name'),
        ('attr-field-id', 'attr_field_id'),
        ('value', 'value'),
        ('placeholder', 'placeholder'),
    ):
        try:
            summary[key_name] = _debug_normalize_text(element.attr(attr_name), 240)
        except Exception:
            pass

    try:
        summary['displayed'] = bool(element.states.is_displayed)
    except Exception:
        pass

    if include_html:
        try:
            summary['outer_html'] = _debug_normalize_text(
                element.run_js('return this.outerHTML || "";'),
                1200
            )
        except Exception:
            summary['outer_html'] = ''

    return summary


def _query_browser_elements(tab, locator, locator_type='raw', timeout=1.0, limit=10, include_html=False, only_visible=False):
    normalized_locator = _normalize_debug_locator(locator, locator_type)
    elements = tab.eles(normalized_locator, timeout=timeout) or []
    if only_visible:
        visible_items = []
        for item in elements:
            try:
                if item.states.is_displayed:
                    visible_items.append(item)
            except Exception:
                continue
        elements = visible_items

    matches = []
    for index, element in enumerate(elements[:limit]):
        matches.append(_summarize_debug_element(element, index, include_html=include_html))

    return {
        'locator': normalized_locator,
        'match_count': len(elements),
        'matches': matches,
    }


def _get_browser_target_element(tab, locator, locator_type='raw', timeout=1.0, index=0, only_visible=True):
    normalized_locator = _normalize_debug_locator(locator, locator_type)
    elements = tab.eles(normalized_locator, timeout=timeout) or []
    if only_visible:
        filtered = []
        for element in elements:
            try:
                if element.states.is_displayed:
                    filtered.append(element)
            except Exception:
                continue
        elements = filtered

    if not elements:
        raise Exception(f'No element matched locator: {normalized_locator}')
    if index < 0 or index >= len(elements):
        raise Exception(f'Element index {index} is out of range for locator: {normalized_locator}')
    return elements[index], normalized_locator, len(elements)


def _snapshot_browser_context(tab, locator=None, locator_type='raw', limit=5, include_html=False):
    page_bits = _collect_browser_page_bits(tab)
    session = _get_browser_debug_session(create=False)
    context = {
        'session': _serialize_browser_debug_session(session, include_events=True, recent_event_count=15),
        'url': page_bits.get('url') or getattr(tab, 'url', ''),
        'title': page_bits.get('title') or '',
        'ready_state': page_bits.get('ready_state') or '',
        'scroll': page_bits.get('scroll') or {'x': 0, 'y': 0},
        'visible_fields': page_bits.get('field_items') or [],
        'visible_controls': page_bits.get('control_items') or [],
        'visible_overlays': page_bits.get('overlay_items') or [],
        'upload_signals': page_bits.get('upload_signals') or {},
    }

    if locator:
        context['query'] = _query_browser_elements(
            tab,
            locator,
            locator_type=locator_type,
            timeout=1.0,
            limit=limit,
            include_html=include_html,
            only_visible=False,
        )

    if include_html:
        try:
            context['html_excerpt'] = _debug_normalize_text(tab.html, 4000)
        except Exception:
            context['html_excerpt'] = ''

    return context


def _evaluate_browser_wait_condition(
    tab,
    condition,
    locator=None,
    locator_type='raw',
    expected_text='',
    count=1,
    only_visible=True,
):
    normalized_condition = str(condition or '').strip().lower()
    expected_text = str(expected_text or '').strip()
    count = max(0, int(count or 0))
    current_url = ''
    current_title = ''
    ready_state = ''

    try:
        current_url = str(getattr(tab, 'url', '') or '')
    except Exception:
        current_url = ''

    try:
        current_title = str(getattr(tab, 'title', '') or '')
    except Exception:
        current_title = ''

    try:
        ready_state = str(tab.run_js('return document.readyState || "";') or '')
    except Exception:
        ready_state = ''

    state = {
        'condition': normalized_condition,
        'locator': locator,
        'locator_type': locator_type,
        'expected_text': expected_text,
        'count': count,
        'only_visible': bool(only_visible),
        'url': current_url,
        'title': current_title,
        'ready_state': ready_state,
        'matched': False,
    }

    if normalized_condition in ('present', 'visible', 'absent', 'hidden'):
        if not locator:
            raise Exception(f'locator is required for condition: {normalized_condition}')
        query = _query_browser_elements(
            tab,
            locator,
            locator_type=locator_type,
            timeout=0.1,
            limit=min(max(count, 1), 10),
            include_html=False,
            only_visible=normalized_condition in ('visible', 'hidden') and only_visible,
        )
        observed_count = int(query.get('match_count') or 0)
        state['query'] = query
        state['observed_count'] = observed_count

        if normalized_condition in ('present', 'visible'):
            state['matched'] = observed_count >= max(count, 1)
        elif normalized_condition in ('absent', 'hidden'):
            state['matched'] = observed_count <= 0
        return state

    if normalized_condition == 'url_contains':
        state['matched'] = expected_text in current_url if expected_text else bool(current_url)
        return state

    if normalized_condition == 'title_contains':
        state['matched'] = expected_text in current_title if expected_text else bool(current_title)
        return state

    if normalized_condition == 'ready_state':
        expected_state = expected_text or 'complete'
        state['expected_text'] = expected_state
        state['matched'] = ready_state == expected_state
        return state

    raise Exception(f'Unsupported wait condition: {normalized_condition}')


def _wait_for_browser_condition(
    tab,
    condition,
    locator=None,
    locator_type='raw',
    expected_text='',
    count=1,
    only_visible=True,
    timeout=10.0,
    interval=0.1,
):
    deadline = system_time.time() + max(0.1, float(timeout))
    sleep_interval = max(0.02, min(float(interval), 1.0))
    last_state = None

    while system_time.time() < deadline:
        last_state = _evaluate_browser_wait_condition(
            tab,
            condition=condition,
            locator=locator,
            locator_type=locator_type,
            expected_text=expected_text,
            count=count,
            only_visible=only_visible,
        )
        if last_state.get('matched'):
            return True, last_state
        system_time.sleep(sleep_interval)

    last_state = _evaluate_browser_wait_condition(
        tab,
        condition=condition,
        locator=locator,
        locator_type=locator_type,
        expected_text=expected_text,
        count=count,
        only_visible=only_visible,
    )
    return bool(last_state.get('matched')), last_state


def _capture_browser_debug_artifacts(tab, label='snapshot', include_html=True, session_label='manual'):
    session = _get_browser_debug_session(create=True, label=session_label)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    base_name = f"{timestamp}_{_debug_slug(label)}"
    screenshot_path = os.path.join(session['artifacts_dir'], f'{base_name}.png')
    html_path = os.path.join(session['artifacts_dir'], f'{base_name}.html')
    context_path = os.path.join(session['artifacts_dir'], f'{base_name}.json')
    artifacts = {
        'session_id': session.get('session_id'),
        'artifacts_dir': session.get('artifacts_dir'),
        'screenshot_path': None,
        'html_path': None,
        'context_path': None,
    }

    if tab:
        try:
            tab.get_screenshot(
                path=session['artifacts_dir'],
                name=f'{base_name}.png',
                full_page=False,
            )
            artifacts['screenshot_path'] = screenshot_path
        except Exception as exc:
            artifacts['screenshot_error'] = str(exc)

        try:
            context = _snapshot_browser_context(tab, include_html=False)
            with open(context_path, 'w', encoding='utf-8') as fp:
                json.dump(context, fp, ensure_ascii=False, indent=2)
            artifacts['context_path'] = context_path
        except Exception as exc:
            artifacts['context_error'] = str(exc)

        if include_html:
            try:
                with open(html_path, 'w', encoding='utf-8') as fp:
                    fp.write(tab.html or '')
                artifacts['html_path'] = html_path
            except Exception as exc:
                artifacts['html_error'] = str(exc)

    _append_browser_debug_event(
        'artifact',
        f'Captured browser artifacts for {label}',
        data=artifacts,
        session_id=session.get('session_id')
    )
    return artifacts


def _record_browser_automation_error(stage, error, traceback_text, tab=None, extra=None):
    session = _get_browser_debug_session(create=True, label='upload-error')
    artifacts = _capture_browser_debug_artifacts(
        tab,
        label=f'error_{stage}',
        include_html=True,
        session_label=session.get('label') or 'upload-error'
    )
    report = {
        'captured_at': _debug_now_iso(),
        'stage': stage,
        'error': str(error),
        'traceback': traceback_text,
        'artifacts': artifacts,
        'page': _snapshot_browser_context(tab, include_html=False) if tab else None,
        'extra': extra or {},
        'session': _serialize_browser_debug_session(session, include_events=True, recent_event_count=20),
    }
    report_path = os.path.join(
        session['artifacts_dir'],
        f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{_debug_slug(stage)}_report.json"
    )
    try:
        with open(report_path, 'w', encoding='utf-8') as fp:
            json.dump(report, fp, ensure_ascii=False, indent=2)
        report['report_path'] = report_path
    except Exception as exc:
        report['report_path_error'] = str(exc)

    _set_last_browser_debug_error(report)
    _append_browser_debug_event(
        'automation_error',
        f'Automation failed at stage: {stage}',
        data={
            'error': str(error),
            'report_path': report.get('report_path'),
        },
        session_id=session.get('session_id')
    )
    return report


@app.post('/api/debug/browser/ensure')
def debug_browser_ensure():
    data = request.get_json(silent=True) or {}
    label = data.get('label') or 'manual'
    new_session = _debug_bool(data.get('new_session'))
    create_browser = _debug_bool(data.get('create_browser'), True)
    navigate = _debug_bool(data.get('navigate'))
    mode = str(data.get('mode') or 'managed').strip().lower()
    debug_address = (data.get('debug_address') or '').strip() or None
    existing_only = _debug_bool(data.get('existing_only'), mode == 'attach')
    url = (data.get('url') or '').strip() or None

    session = _create_browser_debug_session(label) if new_session else _get_browser_debug_session(create=True, label=label)

    try:
        tab, meta = _get_current_browser_tab(
            create_if_missing=create_browser,
            url=url,
            navigate=navigate,
            mode=mode,
            debug_address=debug_address,
            existing_only=existing_only,
        )
    except Exception as exc:
        return api_error(f'Failed to prepare browser: {str(exc)}')

    if not tab:
        return api_error('Browser is not running. Set create_browser=true to launch it.')

    snapshot = _snapshot_browser_context(
        tab,
        limit=_debug_int(data.get('limit'), 5, minimum=1, maximum=20),
        include_html=_debug_bool(data.get('include_html'))
    )
    _append_browser_debug_event(
        'ensure_browser',
        'Browser is ready for debugging.',
        data={
            'url': snapshot.get('url'),
            'title': snapshot.get('title'),
            'meta': meta,
        },
        session_id=session.get('session_id')
    )

    return api_ok('Debug browser is ready.', data={
        'session': _serialize_browser_debug_session(session, include_events=True, recent_event_count=10),
        'browser': meta,
        'snapshot': snapshot,
    })


@app.get('/api/debug/browser/discover')
def debug_browser_discover():
    verify = _debug_bool(request.args.get('verify'), True)
    browsers = discover_debuggable_browsers(verify=verify)
    return api_ok('Discover debug browsers completed.', data={
        'count': len(browsers),
        'browsers': browsers,
    })


@app.post('/api/debug/browser/launch')
def debug_browser_launch():
    data = request.get_json(silent=True) or {}
    label = data.get('label') or 'launch'
    new_session = _debug_bool(data.get('new_session'))
    navigate = _debug_bool(data.get('navigate'), bool(data.get('url')))
    reuse_existing = _debug_bool(data.get('reuse_existing'), True)
    profile_name = (data.get('profile_name') or 'default').strip() or 'default'
    browser_path = (data.get('browser_path') or '').strip() or None
    user_data_dir = (data.get('user_data_dir') or '').strip() or None
    url = (data.get('url') or '').strip() or None

    port = data.get('port')
    if port in ('', None):
        port = None

    try:
        timeout = float(data.get('timeout') or 10.0)
    except Exception:
        timeout = 10.0

    session = _create_browser_debug_session(label) if new_session else _get_browser_debug_session(create=True, label=label)

    try:
        launched_browser = _launch_attachable_debug_browser(
            browser_path=browser_path,
            port=port,
            url=url,
            user_data_dir=user_data_dir,
            profile_name=profile_name,
            timeout=timeout,
            reuse_existing=reuse_existing,
        )
        _set_browser_debug_instance(launched_browser)
        tab, meta = _get_current_browser_tab(
            create_if_missing=False,
            url=url,
            navigate=navigate,
            mode='attach',
            debug_address=launched_browser['debug_address'],
            existing_only=True,
        )
    except Exception as exc:
        return api_error(f'Failed to launch debug browser: {str(exc)}')

    if not tab:
        return api_error('Debug browser was launched but no tab is available.')

    snapshot = _snapshot_browser_context(
        tab,
        limit=_debug_int(data.get('limit'), 5, minimum=1, maximum=20),
        include_html=_debug_bool(data.get('include_html'))
    )
    _append_browser_debug_event(
        'launch_browser',
        'Debug browser launched and attached.',
        data={
            'launched_browser': launched_browser,
            'meta': meta,
            'url': snapshot.get('url'),
            'title': snapshot.get('title'),
        },
        session_id=session.get('session_id')
    )

    return api_ok('Debug browser launched.', data={
        'session': _serialize_browser_debug_session(session, include_events=True, recent_event_count=10),
        'browser': meta,
        'launched_browser': launched_browser,
        'snapshot': snapshot,
    })


@app.get('/api/debug/browser/session')
def debug_browser_session():
    session = _get_browser_debug_session(create=False)
    return api_ok('Current browser debug session loaded.', data={
        'session': _serialize_browser_debug_session(session, include_events=True, recent_event_count=30),
        'browser_instance': _get_browser_debug_instance(),
        'last_error': _get_last_browser_debug_error(),
    })


@app.get('/api/debug/browser/context')
def debug_browser_context():
    include_html = _debug_bool(request.args.get('include_html'))
    locator = request.args.get('locator')
    locator_type = request.args.get('locator_type') or 'raw'
    limit = _debug_int(request.args.get('limit'), 5, minimum=1, maximum=20)

    try:
        tab, _ = _get_current_browser_tab(create_if_missing=False)
    except Exception as exc:
        return api_error(f'Failed to access browser: {str(exc)}')

    if not tab:
        return api_error('Browser is not running.')

    snapshot = _snapshot_browser_context(
        tab,
        locator=locator,
        locator_type=locator_type,
        limit=limit,
        include_html=include_html
    )
    return api_ok('Browser context loaded.', data=snapshot)


@app.post('/api/debug/browser/query')
def debug_browser_query():
    data = request.get_json(silent=True) or {}
    locator = data.get('locator')
    if not locator:
        return api_error('Locator is required.')

    locator_type = data.get('locator_type') or 'raw'
    include_html = _debug_bool(data.get('include_html'))
    only_visible = _debug_bool(data.get('only_visible'), True)
    limit = _debug_int(data.get('limit'), 10, minimum=1, maximum=50)

    try:
        timeout = float(data.get('timeout') or 1.0)
    except Exception:
        timeout = 1.0
    timeout = max(0.1, min(timeout, 5.0))

    try:
        tab, _ = _get_current_browser_tab(create_if_missing=_debug_bool(data.get('create_browser')))
    except Exception as exc:
        return api_error(f'Failed to access browser: {str(exc)}')

    if not tab:
        return api_error('Browser is not running.')

    try:
        result = _query_browser_elements(
            tab,
            locator,
            locator_type=locator_type,
            timeout=timeout,
            limit=limit,
            include_html=include_html,
            only_visible=only_visible
        )
        _append_browser_debug_event(
            'query',
            f'Queried locator: {result.get("locator")}',
            data={
                'match_count': result.get('match_count'),
                'only_visible': only_visible,
            }
        )
        return api_ok('Browser element query completed.', data={
            'query': result,
            'snapshot': _snapshot_browser_context(tab, limit=min(limit, 10), include_html=False),
        })
    except Exception as exc:
        artifacts = _capture_browser_debug_artifacts(tab, label='query_failed', include_html=True)
        return api_error(
            f'Failed to query browser elements: {str(exc)}',
            data={'artifacts': artifacts}
        )


@app.post('/api/debug/browser/wait')
def debug_browser_wait():
    data = request.get_json(silent=True) or {}
    condition = str(data.get('condition') or '').strip().lower()
    if not condition:
        return api_error('condition is required.')

    locator = data.get('locator')
    locator_type = data.get('locator_type') or 'raw'
    expected_text = data.get('text')
    only_visible = _debug_bool(data.get('only_visible'), True)
    count = _debug_int(data.get('count'), 1, minimum=0, maximum=50)
    include_html = _debug_bool(data.get('include_html'))
    capture_on_timeout = _debug_bool(data.get('capture_on_timeout'), True)

    try:
        timeout = float(data.get('timeout') or 10.0)
    except Exception:
        timeout = 10.0
    timeout = max(0.1, min(timeout, 30.0))

    try:
        interval = float(data.get('interval') or 0.1)
    except Exception:
        interval = 0.1
    interval = max(0.02, min(interval, 1.0))

    try:
        tab, meta = _get_current_browser_tab(
            create_if_missing=_debug_bool(data.get('create_browser')),
            url=(data.get('url') or '').strip() or None,
            navigate=_debug_bool(data.get('navigate'))
        )
    except Exception as exc:
        return api_error(f'Failed to access browser: {str(exc)}')

    if not tab:
        return api_error('Browser is not running.')

    try:
        matched, wait_state = _wait_for_browser_condition(
            tab,
            condition=condition,
            locator=locator,
            locator_type=locator_type,
            expected_text=expected_text,
            count=count,
            only_visible=only_visible,
            timeout=timeout,
            interval=interval,
        )
        snapshot = _snapshot_browser_context(
            tab,
            locator=locator if locator else None,
            locator_type=locator_type,
            limit=5,
            include_html=include_html,
        )
        payload = {
            'condition': condition,
            'locator': locator,
            'locator_type': locator_type,
            'text': expected_text,
            'count': count,
            'only_visible': only_visible,
            'timeout': timeout,
            'interval': interval,
            'matched': matched,
            'browser': meta,
            'state': wait_state,
        }

        if matched:
            _append_browser_debug_event(
                'wait',
                f'Wait condition matched: {condition}',
                data=payload
            )
            return api_ok('Browser wait condition matched.', data={
                'result': payload,
                'snapshot': snapshot,
            })

        artifacts = None
        if capture_on_timeout:
            artifacts = _capture_browser_debug_artifacts(
                tab,
                label=f'wait_{condition}_timeout',
                include_html=include_html,
                session_label='manual'
            )
        payload['artifacts'] = artifacts
        _append_browser_debug_event(
            'wait_timeout',
            f'Wait condition timed out: {condition}',
            data=payload
        )
        return api_error(
            f'Browser wait timed out: {condition}',
            data={
                'result': payload,
                'snapshot': snapshot,
                'artifacts': artifacts,
            }
        )
    except Exception as exc:
        artifacts = _capture_browser_debug_artifacts(
            tab,
            label=f'wait_{condition}_failed',
            include_html=True,
            session_label='manual'
        )
        _append_browser_debug_event(
            'wait_error',
            f'Browser wait failed: {condition}',
            data={
                'error': str(exc),
                'condition': condition,
                'locator': locator,
                'artifacts': artifacts,
            }
        )
        return api_error(
            f'Browser wait failed: {str(exc)}',
            data={'artifacts': artifacts}
        )


@app.post('/api/debug/browser/action')
def debug_browser_action():
    data = request.get_json(silent=True) or {}
    action = str(data.get('action') or '').strip().lower()
    if not action:
        return api_error('Action is required.')

    try:
        timeout = float(data.get('timeout') or 1.0)
    except Exception:
        timeout = 1.0
    timeout = max(0.1, min(timeout, 5.0))

    locator = data.get('locator')
    locator_type = data.get('locator_type') or 'raw'
    element_index = _debug_int(data.get('index'), 0, minimum=0, maximum=50)
    only_visible = _debug_bool(data.get('only_visible'), True)
    value = data.get('value')

    try:
        tab, meta = _get_current_browser_tab(
            create_if_missing=_debug_bool(data.get('create_browser')),
            url=(data.get('url') or '').strip() or None,
            navigate=_debug_bool(data.get('navigate'))
        )
    except Exception as exc:
        return api_error(f'Failed to access browser: {str(exc)}')

    if not tab:
        return api_error('Browser is not running.')

    try:
        action_result = {
            'action': action,
            'locator': locator,
            'locator_type': locator_type,
            'index': element_index,
            'browser': meta,
        }

        if action == 'navigate':
            target_url = (data.get('url') or '').strip()
            if not target_url:
                return api_error('url is required for navigate action.')
            tab.get(target_url)
            action_result['url'] = target_url
        else:
            if not locator:
                return api_error('Locator is required for this action.')

            target, normalized_locator, match_count = _get_browser_target_element(
                tab,
                locator,
                locator_type=locator_type,
                timeout=timeout,
                index=element_index,
                only_visible=only_visible
            )
            action_result['resolved_locator'] = normalized_locator
            action_result['match_count'] = match_count

            if action == 'click':
                target.scroll.to_center()
                target.click(by_js=_debug_bool(data.get('by_js'), True))
            elif action == 'hover':
                target.scroll.to_center()
                target.hover()
            elif action == 'scroll':
                target.scroll.to_center()
            elif action == 'clear':
                target.click(by_js=True)
                target.clear(by_js=True)
            elif action == 'input':
                if value is None:
                    return api_error('value is required for input action.')
                target.scroll.to_center()
                target.input(str(value), clear=_debug_bool(data.get('clear'), True))
            else:
                return api_error(f'Unsupported action: {action}')

        time.sleep(0.1)
        snapshot = _snapshot_browser_context(
            tab,
            locator=locator if action != 'navigate' else None,
            locator_type=locator_type,
            limit=5,
            include_html=False
        )
        _append_browser_debug_event(
            'action',
            f'Executed browser action: {action}',
            data=action_result
        )
        return api_ok('Browser action completed.', data={
            'result': action_result,
            'snapshot': snapshot,
        })
    except Exception as exc:
        artifacts = _capture_browser_debug_artifacts(tab, label=f'action_{action}_failed', include_html=True)
        _append_browser_debug_event(
            'action_error',
            f'Browser action failed: {action}',
            data={
                'error': str(exc),
                'locator': locator,
                'action': action,
                'artifacts': artifacts,
            }
        )
        return api_error(
            f'Browser action failed: {str(exc)}',
            data={'artifacts': artifacts}
        )


@app.post('/api/debug/browser/capture')
def debug_browser_capture():
    data = request.get_json(silent=True) or {}
    label = data.get('label') or 'manual_capture'
    include_html = _debug_bool(data.get('include_html'), True)

    try:
        tab, _ = _get_current_browser_tab(create_if_missing=False)
    except Exception as exc:
        return api_error(f'Failed to access browser: {str(exc)}')

    if not tab:
        return api_error('Browser is not running.')

    artifacts = _capture_browser_debug_artifacts(
        tab,
        label=label,
        include_html=include_html,
        session_label=data.get('session_label') or 'manual'
    )
    return api_ok('Browser artifacts captured.', data=artifacts)


@app.get('/api/debug/browser/last-error')
def debug_browser_last_error():
    report = _get_last_browser_debug_error()
    if not report:
        return api_ok('No browser debug error report is available.', data=None)
    return api_ok('Latest browser debug error report loaded.', data=report)


def _resolve_protocol_mcp_server_dir():
    explicit_dir = os.environ.get('DOUYIN_MCP_SERVER_DIR')
    if explicit_dir:
        return os.path.abspath(explicit_dir)

    source_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    candidates = [
        os.path.join(source_project_root, 'mcp-server'),
        os.path.join(get_app_root(), 'mcp-server'),
    ]
    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate
    return candidates[0]


def _normalize_protocol_category_keywords(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(',') if item.strip()]
    return []


def _run_fxg_runtime_options_probe(payload):
    mcp_dir = _resolve_protocol_mcp_server_dir()
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

    timeout_seconds = _debug_int(payload.get('timeout_seconds') or payload.get('timeoutSeconds'), 60, 5, 180)
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


@app.post('/api/protocol/fxg/runtime-options')
def protocol_fxg_runtime_options():
    try:
        payload = request.get_json(silent=True) or {}
        result = _run_fxg_runtime_options_probe(payload)
        return api_ok('运行时配置读取成功。', data=result)
    except Exception as exc:
        return api_error(str(exc))


@app.route('/delete_sku', methods=['POST'])
def delete_sku():
    data = request.get_json()
    sku_path = data.get('sku_path')
    record_id = data.get('record_id')
    if not sku_path or not record_id:
        return api_error('参数错误')

    try:
        record = Record.get_by_id(record_id)
        sku_list = json.loads(record.content)
        target_sku = next((sku for sku in sku_list if sku.get('path') == sku_path), None)
        if target_sku and _is_capture_managed_record(record):
            moved = _move_path_to_recycle_bin(str(target_sku.get('path') or ''))
            if moved:
                print(f"采集导入SKU图片已移动到回收站: {target_sku.get('path')}")
            else:
                print(f"采集导入SKU图片不存在，仅移除SKU记录: {target_sku.get('path')}")
        # 过滤掉要删除的 SKU
        sku_list = [sku for sku in sku_list if sku['path'] != sku_path]
        record.content = json.dumps(sku_list)
        record.save()

        return api_ok('SKU 删除成功')
    except Exception as e:
        traceback.print_exc()
        return api_error(f'删除失败：{str(e)}')


@app.get('/')
def index():
    """根路径：仅返回 sidecar 存活标识"""
    return api_ok('sidecar running')


@app.get('/api/products')
def get_products():
    """API: 获取产品列表（用于实时更新）"""
    try:
        record_list = []
        for record in Record.select().order_by(Record.update_time.desc()).execute():
            arr = record.name.split('_')
            record_list.append({
                'id': record.id,
                'name': record.name if len(arr) < 4 else arr[3],
                'update_time': record.update_time.strftime('%Y-%m-%d %H:%M')
            })
        
        app.logger.info(f'📋 API返回产品列表: {len(record_list)} 个商品')
        return jsonify({
            'success': True,
            'products': record_list
        })
    except Exception as e:
        app.logger.error(f'❌ 获取产品列表失败: {str(e)}')
        return jsonify({
            'success': False,
            'message': f'获取产品列表失败: {str(e)}'
        })



@app.get('/load_detail')
def load_detail():
    try:
        record_id = request.args.get('_id')
        load_images = request.args.get('images', 'true').lower() == 'true'
        
        record = Record.get_by_id(record_id)
        arr = record.name.split('_')
        sku_list = json.loads(record.content)
        
        # 根据images参数决定是否加载图片的Base64数据
        for sku in sku_list:
            if load_images:
                # 完整模式：加载Base64图片
                try:
                    if os.path.exists(sku['path']):
                        with open(sku['path'], 'rb') as img_file:
                            encoded_string = base64.b64encode(img_file.read()).decode('utf-8')
                            sku['url'] = f"data:image/jpeg;base64,{encoded_string}"
                    else:
                        # 图片文件不存在，使用占位符
                        sku['url'] = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iI2Y1ZjVmNSIvPjx0ZXh0IHg9IjUwIiB5PSI1MCIgZm9udC1mYW1pbHk9IkFyaWFsIiBmb250LXNpemU9IjEyIiBmaWxsPSIjOTk5IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBkeT0iLjNlbSI+SW1hZ2UgTm90IEZvdW5kPC90ZXh0Pjwvc3ZnPg=='
                        print(f"⚠️ 图片文件不存在: {sku['path']}")
                except Exception as img_error:
                    # 图片加载失败，使用占位符
                    sku['url'] = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iI2Y1ZjVmNSIvPjx0ZXh0IHg9IjUwIiB5PSI1MCIgZm9udC1mYW1pbHk9IkFyaWFsIiBmb250LXNpemU9IjEyIiBmaWxsPSIjOTk5IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBkeT0iLjNlbSI+TG9hZCBFcnJvcjwvdGV4dD48L3N2Zz4K'
                    print(f"⚠️ 图片加载失败: {sku['path']}, 错误: {img_error}")
            else:
                if 'url' in sku:
                    sku.pop('url', None)
        
        clazz_value = None
        if record.clazz is not None and str(record.clazz).strip() != '':
            try:
                clazz_value = int(str(record.clazz).strip())
            except Exception:
                clazz_value = None

        return api_ok(msg='操作成功！', data={
            'id': record.id,
            'title': record.title,
            'repo': record.repo,
            'name': record.name if len(arr) < 4 else arr[3],
            'path': record.path,
            'clazz': clazz_value,
            'remark': record.remark,
            'content': sku_list
        })
    except Exception as e:
        traceback.print_exc()
        return api_error(msg=f'操作失败：{str(e)}')


@app.delete('/delete_all')
def delete_all():
    try:
        records = list(Record.select())
        for record in records:
            _delete_product_record(record)
        return api_ok(msg='清空成功！')
    except Exception as e:
        print(f"清空产品失败: {str(e)}")
        return api_error(msg=f'清空失败：{str(e)}')


@app.post('/save_info')
def save_info():
    try:
        request_data = request.get_json()
        if not request_data:
            return api_error(msg='请求数据为空！')
        
        _id = request_data.get('_id')
        if not _id:
            return api_error(msg='记录ID不能为空！')
        
        record = Record.get_by_id(_id)
        if not record:
            return api_error(msg='记录不存在！')
        
        # 更新类目
        try:
            clazz = request_data.get('clazz')
            if clazz is not None and str(clazz).strip():
                record.clazz = int(clazz)
        except (ValueError, TypeError) as e:
            print(f"⚠️ 类目转换失败: {e}")
        
        # 更新基本信息
        record.title = request_data.get('title', '')
        record.remark = request_data.get('remark', '')
        
        # 更新仓库
        try:
            repo = request_data.get('repo')
            if repo is not None and str(repo).strip():
                record.repo = int(repo)
        except (ValueError, TypeError) as e:
            print(f"⚠️ 仓库转换失败: {e}")
        
        # 更新SKU数据
        try:
            original_content = json.loads(record.content)
            arr = {}
            for dt in original_content:
                arr[dt['path']] = dt
            
            attr_size = int(request_data.get('attr_size', 0))
            for i in range(attr_size):
                path_key = f'attr_path_{i + 1}'
                name_key = f'attr_name_{i + 1}'
                price_key = f'attr_price_{i + 1}'
                
                attr_path = request_data.get(path_key)
                if attr_path and attr_path in arr:
                    arr[attr_path]['name'] = request_data.get(name_key, '')
                    # 价格处理，确保是数字
                    try:
                        price_value = request_data.get(price_key, '0')
                        arr[attr_path]['price'] = float(price_value) if price_value else 0.0
                    except (ValueError, TypeError):
                        arr[attr_path]['price'] = 0.0
                        print(f"⚠️ 价格转换失败，使用默认值0: {price_key}")
            
            record.content = json.dumps(list(arr.values()))
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"❌ SKU数据处理失败: {str(e)}")
            return api_error(msg=f'SKU数据处理失败：{str(e)}')
        
        # 更新时间并保存
        try:
            record.update_time = time.now()
            record.save()
            print(f"✅ 记录保存成功: ID={record.id}, 标题={record.title}")
            
            return api_ok(msg='保存成功！', data={
                'id': record.id,
                'update_time': record.update_time.strftime('%Y-%m-%d %H:%M')
            })
        except Exception as save_error:
            print(f"❌ 数据库保存失败: {str(save_error)}")
            return api_error(msg=f'数据库保存失败：{str(save_error)}')
        
    except Exception as e:
        print(f"❌ 保存操作异常: {str(e)}")
        traceback.print_exc()
        return api_error(msg=f'保存失败：{str(e)}')


def _wait_login_complete(page, report_progress):
    for idx in range(150):
        current_url = str(page.url or '')
        if '/homepage' in current_url or '/ffa/g/create' in current_url:
            return True
        if idx % 25 == 0:
            report_progress(14, '等待登录完成，请在浏览器中完成登录')
        time.sleep(0.2)
    return False


def _attach_reusable_logged_in_fxg_browser(report_progress):
    try:
        reusable = _find_reusable_logged_in_fxg_browser(verify=True)
    except Exception as exc:
        print(f'查找已登录抖店浏览器失败: {exc}')
        return None

    selected = reusable.get('selected_browser') or {}
    debug_address = _normalize_debug_address(selected.get('debug_address') or '')
    if not debug_address:
        return None

    matched_url = selected.get('matched_url') or ''
    report_progress(13, f'复用已登录抖店浏览器 {debug_address}')
    print(f'复用已登录抖店浏览器: {debug_address} {matched_url}')
    try:
        tab, _meta = _get_current_browser_tab(
            create_if_missing=False,
            mode='attach',
            debug_address=debug_address,
            existing_only=True,
        )
        return tab
    except Exception as exc:
        print(f'附着已登录抖店浏览器失败: {exc}')
        return None


def _load_upload_records(record_id=None):
    if record_id:
        record = Record.get_or_none(Record.id == record_id)
        if not record:
            return None, '指定产品不存在'
        return [record], None

    record_list = list(Record.select().execute())
    if len(record_list) == 0:
        return None, '没有待上传数据！'
    return record_list, None


def _load_upload_runtime_config():
    user_settings = settings_manager.get_settings()
    automation_config = settings_manager.normalize_automation_config(user_settings.automation_config)
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
            percentage_text = str(int(float(percentage)))
        except Exception:
            percentage_text = ''
        configured_materials.append((material_name, percentage_text))
    configured_materials = [item for item in configured_materials if item[0] and item[1]]
    if not configured_materials:
        configured_materials = [('棉', '75'), ('氨纶', '25')]
    if wash_label_tag_image_path and not os.path.isfile(wash_label_tag_image_path):
        print(f'自动化设置中的水洗标/吊牌图不存在，已跳过: {wash_label_tag_image_path}')
        wash_label_tag_image_path = ''
    return shipping_template_name, configured_materials, wash_label_tag_image_path


def _ensure_publish_session(report_progress):
    opened_new_browser = False

    if gui.page:
        try:
            current_tab = gui.page.get_tab(gui.page.latest_tab)
            current_url = str(current_tab.url or '')
        except Exception:
            current_url = ''
        if not is_logged_in_fxg_target_url(current_url):
            reusable_tab = _attach_reusable_logged_in_fxg_browser(report_progress)
            if reusable_tab is not None:
                opened_new_browser = False

    if not gui.page:
        reusable_tab = _attach_reusable_logged_in_fxg_browser(report_progress)
        if reusable_tab is None:
            report_progress(13, '正在打开浏览器并进入发布页面')
            try:
                gui.page = get_page(_PUBLISH_CREATE_URL)
                opened_new_browser = True
            except Exception as exc:
                traceback.print_exc()
                return None, f'浏览器启动失败：{exc}'

    try:
        main_tab = gui.page.get_tab(gui.page.latest_tab)
    except Exception:
        reusable_tab = _attach_reusable_logged_in_fxg_browser(report_progress)
        if reusable_tab is not None:
            main_tab = reusable_tab
        else:
            report_progress(13, '正在重新打开浏览器并进入发布页面')
            try:
                gui.page = get_page(_PUBLISH_CREATE_URL)
                opened_new_browser = True
            except Exception as exc:
                traceback.print_exc()
                return None, f'浏览器恢复失败：{exc}'
            main_tab = gui.page.get_tab(gui.page.latest_tab)

    if not opened_new_browser:
        report_progress(13, '正在进入商品发布页面')
        try:
            _dismiss_pending_browser_alert(main_tab)
            main_tab.get(_PUBLISH_CREATE_URL)
        except Exception as exc:
            try:
                _dismiss_pending_browser_alert(main_tab)
                main_tab.get(_PUBLISH_CREATE_URL)
            except Exception:
                traceback.print_exc()
                return None, f'打开发布页面失败：{exc}'

    if not _wait_login_complete(main_tab, report_progress):
        return None, '超时未登录！！！'

    return main_tab, None


def _dismiss_pending_browser_alert(main_tab):
    try:
        main_tab.handle_alert(next_one=True)
    except Exception:
        pass


def _prepare_record_assets(record):
    if not record.title:
        return None, '标题为空！！！'
    if not record.clazz:
        return None, '类目为空！！！'
    if not str(record.repo):
        return None, '库存为空！！！'

    try:
        main_pic_list = get_pic_list(record, '800')
    except:
        return None, '未找到主图或者主图不全！！！'

    try:
        sub_pic_list = get_pic_list(record, '750')
        if record.type == 2 and len(sub_pic_list) == 0:
            print('ID模式：没有3:4主图，将使用平台自带的1:1导入功能')
    except:
        if record.type == 1:
            return None, '未找到4:3主图或者4:3主图不全！！！'
        sub_pic_list = []
        print('ID模式：获取3:4主图时出现异常，将使用平台自带的1:1导入功能')

    try:
        detail_pic_list = get_detail_pic_list(record)
    except:
        return None, '未找到详情图！！！'

    diaopai_pic = get_diaopai_pic(record)
    my_video = get_my_video(record)

    sku_list = json.loads(record.content)
    if len(sku_list) == 0:
        return None, '未找到sku信息！！！'

    for sku_item in sku_list:
        if not sku_item['name'] or sku_item['price'] is None:
            return None, 'sku信息不全！！！'
        try:
            float(sku_item['price'])
        except (ValueError, TypeError):
            return None, 'sku信息不全！！！'

    white_pic = get_white_pic(record, sku_list)
    return {
        'main_pic_list': main_pic_list,
        'sub_pic_list': sub_pic_list,
        'detail_pic_list': detail_pic_list,
        'diaopai_pic': diaopai_pic,
        'my_video': my_video,
        'sku_list': sku_list,
        'white_pic': white_pic,
    }, None


_INTERFERING_OVERLAY_TEXTS = (
    '我知道了',
    '知道了',
    '暂不',
    '跳过',
    '关闭引导',
    '关闭新手引导',
    '稍后再说',
    '下次再说',
    '以后再说',
)


def _build_overlay_button_selector(scope_expr=None):
    predicate_parts = []
    for text in _INTERFERING_OVERLAY_TEXTS:
        predicate_parts.append(f'normalize-space(.)="{text}"')
        predicate_parts.append(f'.//span[normalize-space(.)="{text}"]')
    predicate = ' or '.join(predicate_parts)
    base = '//*[self::button or @role="button"]'
    if scope_expr:
        base = f'//*[{scope_expr}]//*[self::button or @role="button"]'
    return f'xpath:{base}[{predicate}]'


_VISIBLE_SELECTOR_PROBE_JS = r'''
const specs = arguments[0] || [];
for (let i = 0; i < specs.length; i++) {
    const spec = specs[i];
    let nodes = [];
    try {
        if (spec.t === 'x') {
            const found = document.evaluate(spec.e, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
            for (let j = 0; j < found.snapshotLength; j++) nodes.push(found.snapshotItem(j));
        } else {
            nodes = Array.prototype.slice.call(document.querySelectorAll(spec.e));
        }
    } catch (err) {
        continue;
    }
    for (let k = 0; k < nodes.length; k++) {
        const node = nodes[k];
        if (!node || node.nodeType !== 1) continue;
        if (node.offsetParent || node.getClientRects().length > 0) return i;
    }
}
return -1;
'''


def _first_visible_selector_index(tab, selectors):
    """用一次 JS 批量判定哪个选择器命中可见元素。

    返回命中下标；全部落空返回 -1；JS 不可用返回 None（调用方回退原逐个探测）。

    DrissionPage 的 ele/eles 在**未命中时会阻塞满 timeout** 才返回，
    所以「准备 N 个候选选择器逐个试」的落空成本是 N × timeout，
    常见组合就是 1~2.5 秒的纯空转。先用一次 JS 判定可把它压成一次往返。
    """
    specs = []
    for selector in selectors:
        text = str(selector)
        if text.startswith('xpath:'):
            specs.append({'t': 'x', 'e': text[6:]})
        elif text.startswith('css:'):
            specs.append({'t': 'c', 'e': text[4:]})
        else:
            specs.append({'t': 'c', 'e': text})
    if not specs:
        return -1
    try:
        index = tab.run_js(_VISIBLE_SELECTOR_PROBE_JS, specs)
    except Exception:
        return None
    if isinstance(index, bool) or not isinstance(index, (int, float)):
        return None
    return int(index)


def _find_first_visible_element(tab, selectors, timeout=0.15):
    ordered = list(selectors)
    index = _first_visible_selector_index(tab, ordered)
    if index is not None:
        if index < 0:
            return None
        # 命中的选择器排到最前，其余保留作兜底（JS 可见性判据与
        # DrissionPage states.is_displayed 极少数情况下可能不一致）
        ordered = [ordered[index]] + [item for pos, item in enumerate(ordered) if pos != index]

    for selector in ordered:
        try:
            elements = tab.eles(selector, timeout=timeout)
        except Exception:
            continue
        for element in elements:
            try:
                if element and element.states.is_displayed:
                    return element
            except Exception:
                continue
    return None


def _click_element_safely(element):
    try:
        element.scroll.to_center()
    except Exception:
        pass
    for action in (
        lambda: element.click(),
        lambda: element.click(by_js=True),
        lambda: element.run_js('arguments[0].click();', element),
    ):
        try:
            action()
            return True
        except Exception:
            continue
    return False


def _is_element_displayed(element):
    if not element:
        return False
    try:
        return bool(element.states.is_displayed)
    except Exception:
        return False


def _dismiss_interfering_overlays(main_tab, context=''):
    total_actions = 0

    try:
        drag_controller = main_tab.ele('xpath://div[contains(@class,"index_DragController__")]', timeout=0.1)
        if drag_controller and drag_controller.states.is_displayed:
            main_tab.remove_ele(drag_controller)
            total_actions += 1
    except Exception:
        pass

    overlay_root = (
        'contains(@class,"ecom-g-modal") or contains(@class,"ecom-g-popover") '
        'or @role="dialog" or contains(@class,"guide") or contains(@class,"Guide") '
        'or contains(@class,"tour") or contains(@class,"Tour") '
        'or contains(@class,"coach") or contains(@class,"Coach")'
    )

    text_button_selector = _build_overlay_button_selector()
    scoped_text_button_selector = _build_overlay_button_selector(overlay_root)
    close_button_selector = (
        f'xpath://*[{overlay_root}]//*[self::button or @role="button"]'
        '[contains(@aria-label,"关闭") or contains(@title,"关闭") '
        'or contains(@class,"close") or contains(@class,"Close")]'
    )

    for _ in range(2):
        clicked = False
        selectors = [scoped_text_button_selector, text_button_selector]
        for text in ():
            selectors.extend([
                f'xpath://button[normalize-space(.)="{text}" or .//span[normalize-space(.)="{text}"]]',
                f'xpath://*[{overlay_root}]//*[self::button or @role="button"][normalize-space(.)="{text}" or .//span[normalize-space(.)="{text}"]]',
                f'xpath://*[{overlay_root}]//*[normalize-space(.)="{text}"]/ancestor::*[self::button or @role="button"][1]',
            ])
        selectors.extend([
            f'xpath://*[{overlay_root}]//*[self::button or @role="button"][contains(@aria-label,"关闭") or contains(@title,"关闭")]',
            f'xpath://*[{overlay_root}]//*[self::button or @role="button"][contains(@class,"close") or contains(@class,"Close")]',
        ])
        target = _find_first_visible_element(main_tab, selectors, timeout=0.02)
        if target and _click_element_safely(target):
            clicked = True
            total_actions += 1
            _wait_until(
                lambda: not _is_element_displayed(target),
                timeout=0.18,
                interval=0.03,
            )

        if not clicked:
            break

    if total_actions > 0:
        print(f'已处理干扰弹层{total_actions}次' + (f'，阶段: {context}' if context else ''))
    return total_actions


register_interaction_recovery_hook(_dismiss_interfering_overlays)


def _get_title_input(main_tab, timeout=0.3):
    title_field = main_tab.ele('xpath://div[@attr-field-id="商品标题"]', timeout=timeout)
    if not title_field:
        return None

    selectors = [
        'xpath:.//input[@id="pg-title-input"]',
        'xpath:.//input[@type="text"]',
        'xpath:.//input',
        'xpath:.//textarea',
    ]
    for selector in selectors:
        try:
            candidates = title_field.eles(selector, timeout=0.05)
        except Exception:
            candidates = []
        for item in candidates:
            try:
                if item and item.states.is_displayed:
                    return item
            except Exception:
                continue
    return None


def _find_title_brand_name_checkbox(main_tab):
    try:
        title_field = main_tab.ele('xpath://div[@attr-field-id="商品标题"]', timeout=0.2)
    except Exception:
        title_field = None
    if not title_field:
        return None, None

    label = None
    label_selectors = [
        'xpath:.//*[normalize-space(.)="使用品牌名"]/ancestor::label[1]',
        'xpath:.//*[contains(normalize-space(.),"使用品牌名")]/ancestor::label[1]',
    ]
    for selector in label_selectors:
        try:
            item = title_field.ele(selector, timeout=0.08)
        except Exception:
            item = None
        if item:
            label = item
            break

    checkbox = None
    search_scope = label or title_field
    checkbox_selectors = [
        'xpath:.//input[@type="checkbox"]',
        'xpath:.//*[@role="checkbox"]',
    ]
    for selector in checkbox_selectors:
        try:
            item = search_scope.ele(selector, timeout=0.08)
        except Exception:
            item = None
        if item:
            checkbox = item
            break
    return checkbox, label


def _checkbox_is_checked(element):
    if not element:
        return False
    for attr_name in ('checked', 'aria-checked'):
        try:
            raw_value = element.attr(attr_name)
        except Exception:
            raw_value = None
        if str(raw_value).strip().lower() in ('true', 'checked', '1'):
            return True
    try:
        return bool(
            element.run_js(
                'return !!this.checked || this.getAttribute("aria-checked") === "true" || '
                '!!(this.closest("label") && String(this.closest("label").className || "").includes("checked"));'
            )
        )
    except Exception:
        return False


def _ensure_title_brand_name_disabled(main_tab):
    checkbox, label = _find_title_brand_name_checkbox(main_tab)
    if not checkbox:
        return
    if not _checkbox_is_checked(checkbox):
        return

    print('取消标题区“使用品牌名”')
    target = label or checkbox
    if not _click_element_safely(target):
        raise Exception('标题区“使用品牌名”取消失败')

    if not _wait_until(
        lambda: not _checkbox_is_checked(_find_title_brand_name_checkbox(main_tab)[0]),
        timeout=0.8,
        interval=0.05,
    ):
        raise Exception('标题区“使用品牌名”仍处于勾选状态')


_PUBLISH_STEP1_SELECTORS = [
    'xpath://button[.//span[text()="下一步"]]',
    'xpath://span[text()="下一步"]/..',
    'xpath://div[contains(@class,"categorySelectorV2")]',
    'xpath://span[text()="手动选择"]/..',
]

_PUBLISH_STEP2_SELECTORS = [
    'xpath://div[@attr-field-id="价格与库存"]',
    'xpath://div[@id="goodsEditScrollContainer-价格库存"]',
    'xpath://div[@attr-field-id="售卖价"]',
    'xpath://div[@attr-field-id="订单库存计数"]',
    'xpath://div[@attr-field-id="主图3:4"]',
    'xpath://div[@attr-field-id="主图视频"]',
    'xpath://div[@attr-field-id="商品类目"]//*[text()="修改"]',
    'xpath://div[@attr-field-id="类目属性"]',
]


def _get_current_tab_url(main_tab):
    try:
        return str(main_tab.url or '')
    except Exception:
        return ''


def _is_any_selector_visible(main_tab, selectors, timeout=0.05):
    return _find_first_visible_element(main_tab, selectors, timeout=timeout) is not None


_PUBLISH_STAGE_PROBE_JS = r'''
const step2 = arguments[0] || [];
const step1 = arguments[1] || [];
const visible = function (node) {
    return !!node && node.nodeType === 1 && (node.offsetParent || node.getClientRects().length > 0);
};
const anyVisible = function (xpaths) {
    for (let i = 0; i < xpaths.length; i++) {
        try {
            const found = document.evaluate(xpaths[i], document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
            for (let j = 0; j < found.snapshotLength; j++) {
                if (visible(found.snapshotItem(j))) return true;
            }
        } catch (err) {
            continue;
        }
    }
    return false;
};
if (anyVisible(step2)) return 'step2';
const titleField = document.querySelector('[attr-field-id="商品标题"]');
let titleReady = false;
if (titleField) {
    titleReady = visible(titleField.querySelector('#pg-title-input') || titleField.querySelector('input') || titleField.querySelector('textarea'));
}
if (titleReady || anyVisible(step1)) return 'step1';
return 'unknown';
'''


def _detect_publish_page_stage(main_tab):
    current_url = _get_current_tab_url(main_tab)
    if '/ffa/g/create' not in current_url:
        return 'outside'

    # 一次 JS 判定整页阶段。原实现要逐个探测 13~18 条 XPath（约 0.6~0.9s），
    # 而本函数是 _wait_until(interval=0.1) 的判据，会让轮询间隔彻底失效。
    try:
        stage = main_tab.run_js(
            _PUBLISH_STAGE_PROBE_JS,
            [item[6:] for item in _PUBLISH_STEP2_SELECTORS],
            [item[6:] for item in _PUBLISH_STEP1_SELECTORS],
        )
    except Exception:
        stage = None
    if stage in ('step1', 'step2', 'unknown'):
        return stage

    # JS 不可用时回退到逐个探测
    if _is_any_selector_visible(main_tab, _PUBLISH_STEP2_SELECTORS, timeout=0.05):
        return 'step2'

    step1_selectors = list(_PUBLISH_STEP1_SELECTORS)
    title_input = _get_title_input(main_tab, timeout=0.05)
    if title_input:
        step1_selectors.append('xpath://div[@attr-field-id="商品标题"]')

    if _is_any_selector_visible(main_tab, step1_selectors, timeout=0.05):
        return 'step1'

    return 'unknown'


def _click_return_to_old_version(main_tab):
    """检测新版 AI 生成引导页并点击"返回旧版"按钮。

    2026-08 抖店新版发品页把"返回旧版"改成直接持有文本的
    <div class="styles-module_lightButton__...">，React onClick 绑定在该 div 自身。
    旧的 //span[text()="返回旧版"]/.. 选择器实测命中 0 个节点，导致 _open_publish_page
    在入口就返回失败。这里按文本直接命中持有点击句柄的元素本身，保留旧结构兜底。
    """
    btn = _find_first_visible_element(
        main_tab,
        [
            'xpath://div[normalize-space(text())="返回旧版"]',
            'xpath://*[normalize-space(text())="返回旧版"]',
            'xpath://button[.//span[text()="返回旧版"]]',
            'xpath://span[text()="返回旧版"]/..',
            'xpath://span[text()="返回旧版"]',
        ],
        timeout=0.5,
    )
    if not btn:
        return False
    print('检测到新版AI引导页，点击"返回旧版"')
    return _click_element_safely(btn)


def _open_publish_page(main_tab, report_progress):
    print('打开商品发布页面...')
    report_progress(22, '正在打开商品发布页面')
    _dismiss_pending_browser_alert(main_tab)

    def _settle_to_stage(targets, timeout):
        """轮询到页面进入目标阶段；停在新版 AI 引导页时点一次「返回旧版」。

        取代原先「固定 sleep(1.0) + 点返回旧版 + 固定 sleep(1.5)」的写法：
        那些延时没有任何判据，页面快时纯浪费、页面慢时又不够。
        """
        deadline = system_time.perf_counter() + timeout
        clicked_old = False
        stage = _detect_publish_page_stage(main_tab)
        while True:
            if stage in targets:
                return stage
            if stage == 'unknown' and not clicked_old:
                # AI 引导页在本函数的判据里就是 unknown
                clicked_old = _click_return_to_old_version(main_tab)
            if system_time.perf_counter() >= deadline:
                return stage
            system_time.sleep(0.1)
            stage = _detect_publish_page_stage(main_tab)

    # 会话可能刚导航到发布页，React 尚未 hydrate；先给一小段时间等它渲染，
    # 避免因为「检测早了一步」判成 unknown 而白白再整页重载一次。
    stage = _settle_to_stage(('step1', 'step2'), timeout=3.0)
    if stage not in ('step1', 'step2'):
        main_tab.get(_PUBLISH_CREATE_URL)
        stage = _settle_to_stage(('step1', 'step2'), timeout=10)
        if stage not in ('step1', 'step2'):
            return False

    if stage == 'step2':
        report_progress(22, '检测到停留在第二页面，正在返回第一页')
        main_tab.get(_PUBLISH_CREATE_URL)
        stage = _settle_to_stage(('step1',), timeout=10)
        if stage != 'step1':
            return False
    elif stage != 'step1':
        return False

    _dismiss_interfering_overlays(main_tab, context='open_publish_page')

    try:
        republish_btn = _find_first_visible_element(
            main_tab,
            ['xpath://span[text()="重新发布"]/../..'],
            timeout=0.15,
        )
        if republish_btn:
            republish_btn.click(by_js=True)
            _dismiss_interfering_overlays(main_tab, context='republish')
    except Exception:
        pass
    return True


def _fill_title_for_record(main_tab, record):
    _dismiss_interfering_overlays(main_tab, context='fill_title')
    input_element = _get_title_input(main_tab, timeout=0.4)
    if not input_element:
        raise Exception('未找到商品标题输入框')
    safe_title = sanitize_no_brand_title_text(record.title)
    if not safe_title:
        raise Exception('商品标题清理品牌后为空，不能继续发布')
    _ensure_title_brand_name_disabled(main_tab)
    input_element.click()
    time.sleep(0.05)
    input_element.input(safe_title)
    if not _wait_until(
        lambda: str(input_element.attr('value') or '').strip() == safe_title,
        timeout=0.8,
        interval=0.05,
    ):
        raise Exception('商品标题写入校验失败')
    try:
        drag = main_tab.ele('xpath://div[contains(@class,"index_DragController__")]', timeout=0.2)
        if drag:
            main_tab.remove_ele(drag)
    except Exception:
        pass
    _dismiss_interfering_overlays(main_tab, context='fill_title')


def _upload_main_images(main_tab, record, main_pic_list):
    upload_file(main_tab, main_pic_list, '主图', error_size='长宽比需为1:1' if record.type == 2 else None)
    handle_main_image_post_upload_prompts(main_tab, timeout=2.0)


def _select_category_and_prepare_attributes(main_tab, record, diaopai_pic):
    _dismiss_interfering_overlays(main_tab, context='select_category')
    print(f'开始智能类目选择: {wazi_dict.get(record.clazz)}')
    if not smart_select_category(main_tab, record.clazz):
        print('类目选择失败，已尝试推荐与手动选择。请检查页面结构或账号资质。')
        raise Exception('类目选择失败')
    print('智能类目选择成功')
    _dismiss_interfering_overlays(main_tab, context='select_category')

    gen_btn = main_tab.ele(
        'xpath://div[@data-better-log-outer-key="short_product_name"]'
        + '//span[contains(@class,"ecom-g-input-suffix")]//img',
        timeout=3,
    )
    if gen_btn:
        gen_btn.scroll.to_center()
        gen_btn.click(by_js=True)
        print('已点击生成短标题按钮')
    else:
        print('未找到生成短标题按钮，检查 XPath 或页面结构是否变化')

    _dismiss_interfering_overlays(main_tab, context='after_short_title')

    wash_tag_field_exists = False
    try:
        wash_tag_field_exists = bool(main_tab.ele('xpath://div[@attr-field-id="水洗标/吊牌图"]', timeout=0.3))
    except Exception:
        wash_tag_field_exists = False

    if diaopai_pic and str(record.clazz) != '0' and not wash_tag_field_exists:
        print('处理其他类目吊牌上传...')
        upload_file(main_tab, [diaopai_pic], '吊牌')
        _wait_until(
            lambda: bool(main_tab.ele('吊牌识别成功', timeout=0.05)) or bool(main_tab.ele('吊牌识别失败', timeout=0.05)),
            timeout=3.0,
            interval=0.05,
        )


def _upload_wash_label_or_tag_image(main_tab, diaopai_pic, configured_wash_label_tag_image_path):
    wash_tag_area = None
    try:
        wash_tag_area = main_tab.ele('xpath://div[@attr-field-id="水洗标/吊牌图"]', timeout=0.5)
    except Exception:
        wash_tag_area = None

    if not wash_tag_area:
        return False

    upload_path = ''
    if diaopai_pic and os.path.isfile(diaopai_pic):
        upload_path = diaopai_pic
    elif configured_wash_label_tag_image_path and os.path.isfile(configured_wash_label_tag_image_path):
        upload_path = configured_wash_label_tag_image_path

    if not upload_path:
        print('当前未提供吊牌/水洗标图片，将跳过图片上传并改为依赖面料材质配置')
        return False

    print('开始上传水洗标/吊牌图...')
    upload_file(
        main_tab,
        [upload_path],
        '水洗标/吊牌图',
        target_field_id='水洗标/吊牌图',
        wait_for_finish=False,
    )
    return True


# 与仓库根目录「吊牌.HTML」中抖音商品发布页一致：OCR 未解析材质时的固定提示
_WASH_LABEL_MANUAL_MATERIAL_TIP = '图片中未识别到材质信息，请手动填写'


def _wash_label_manual_material_tip_visible(main_tab):
    try:
        return bool(
            main_tab.ele(
                f'xpath://div[@attr-field-id="水洗标/吊牌图"]'
                f'//*[contains(normalize-space(.),"{_WASH_LABEL_MANUAL_MATERIAL_TIP}")]',
                timeout=0.06,
            )
        )
    except Exception:
        return False


def _wash_label_material_ocr_spinning(main_tab):
    try:
        return bool(
            main_tab.ele(
                'xpath://div[@attr-field-id="水洗标/吊牌图"]'
                '//*[contains(@class,"ecom-g-spin-spinning") or contains(@class,"ant-spin-spinning")]',
                timeout=0.05,
            )
        )
    except Exception:
        return False


def _wash_label_needs_configured_material_fill(main_tab, max_wait_sec=10.0, poll_sec=0.1):
    """
    先等「水洗标/吊牌图」区块内 Ant Spin 结束（表示 OCR 一轮结束），再判断是否出现固定提示。
    成功识别时不会出现该文案，可尽快结束；失败时文案在 attr-field-id 区块内，与吊牌.HTML 结构一致。
    """
    deadline = system_time.time() + max_wait_sec
    consecutive_idle = 0
    while system_time.time() < deadline:
        if _wash_label_manual_material_tip_visible(main_tab):
            return True
        if _wash_label_material_ocr_spinning(main_tab):
            consecutive_idle = 0
        else:
            consecutive_idle += 1
            if consecutive_idle >= 2:
                for _ in range(5):
                    if _wash_label_manual_material_tip_visible(main_tab):
                        return True
                    system_time.sleep(poll_sec)
                return False
        system_time.sleep(poll_sec)
    return _wash_label_manual_material_tip_visible(main_tab)


def _fill_fabric_material_if_wash_label_unrecognized(main_tab, configured_materials):
    if not _wash_label_needs_configured_material_fill(main_tab):
        return
    print('水洗标/吊牌图未识别到材质信息，按自动化配置填写面料材质')
    if not configured_materials:
        raise Exception('吊牌未识别到材质，但未配置面料材质（material_compositions）')
    material_ok = set_material_composition(main_tab, configured_materials)
    if not material_ok:
        raise Exception('面料材质填写失败（吊牌未识别且配置写入失败）')


def _field_exists(main_tab, field_name: str, timeout: float = 0.2) -> bool:
    try:
        return bool(main_tab.ele(f'xpath://div[@attr-field-id="{field_name}"]', timeout=timeout))
    except Exception:
        return False


def _first_existing_field_name(main_tab, field_names, timeout: float = 0.2):
    for field_name in field_names:
        if _field_exists(main_tab, field_name, timeout=timeout):
            return field_name
    return None


def _fill_category_attributes(main_tab, record, configured_materials, diaopai_pic, wash_label_tag_image_path):
    category_attr_timer_start = system_time.perf_counter()
    _dismiss_interfering_overlays(main_tab, context='fill_category_attributes')
    current_category_text = get_current_category_text(main_tab)
    current_sock_height = infer_sock_height_value(current_category_text, record.clazz)
    is_ship_socks = '船袜' in current_category_text
    material_field_name = _first_existing_field_name(main_tab, ('面料材质', '材质'))
    has_material_field = bool(material_field_name)
    has_audience_field = _field_exists(main_tab, '适用人群')
    has_gender_field = _field_exists(main_tab, '适用性别')
    has_sock_height_field = _field_exists(main_tab, '筒高')
    has_configured_materials = bool(configured_materials)
    has_wash_label_asset = bool(
        (diaopai_pic and os.path.isfile(diaopai_pic))
        or (wash_label_tag_image_path and os.path.isfile(wash_label_tag_image_path))
    )
    print(f'当前页面类目: {current_category_text or "未识别"}')
    if current_sock_height:
        print(f'当前页面筒高目标值: {current_sock_height}')

    if is_ship_socks:
        print('处理船袜类目属性...')
        main_tab.ele('xpath://div[@attr-field-id="主图3:4"]').scroll.to_see()

        if not ensure_no_brand(main_tab):
            raise Exception('品牌未能设置为「无品牌」')
        if has_material_field:
            material_ok = set_material_composition(main_tab, configured_materials, material_field_name)
            timer_record('类目属性阶段', f'{material_field_name}配置写入', 0, system_time.perf_counter() - category_attr_timer_start, material_ok)
            if not material_ok:
                raise Exception(f'{material_field_name}填写失败')
            print(f'船袜类目：已按用户设置写入{material_field_name}')
        else:
            print('页面无“面料材质/材质”字段，跳过材质配置')

    elif has_wash_label_asset:
        print('处理其他类目属性（有可用吊牌/水洗标图）...')
        step_timer_start = system_time.perf_counter()
        main_tab.ele('xpath://div[@attr-field-id="主图3:4"]').scroll.to_see()

        if not has_configured_materials:
            ss = main_tab.eles('xpath://div[@attr-field-id="面料材质"]//span[contains(@class,"styles_del__")]', timeout=0.5)
            for del_btn in ss:
                before_count = len(main_tab.eles('xpath://div[@attr-field-id="面料材质"]//span[contains(@class,"styles_del__")]', timeout=0.05) or [])
                del_btn.click(by_js=True)
                _wait_until(
                    lambda: len(main_tab.eles('xpath://div[@attr-field-id="面料材质"]//span[contains(@class,"styles_del__")]', timeout=0.03) or []) < before_count,
                    timeout=0.5,
                    interval=0.03,
                )

        if not ensure_no_brand(main_tab):
            raise Exception('品牌未能设置为「无品牌」')
        if has_audience_field:
            select_text(main_tab, '适用人群', '成人')
        if has_gender_field:
            select_text(main_tab, '适用性别', get_sex(record.title))
        if current_sock_height and has_sock_height_field:
            select_text(main_tab, '筒高', current_sock_height)
        timer_record('类目属性阶段', '基础属性', 0, system_time.perf_counter() - step_timer_start, True)

    else:
        print('处理其他类目属性（无吊牌/水洗标图，改走面料材质配置）...')
        main_tab.ele('xpath://div[@attr-field-id="主图3:4"]').scroll.to_see()
        step_timer_start = system_time.perf_counter()
        material_ok = True
        if has_material_field:
            material_ok = set_material_composition(main_tab, configured_materials, material_field_name)
            if not material_ok:
                raise Exception(f'{material_field_name}填写失败')
        else:
            print('页面无“面料材质/材质”字段，跳过材质配置')
        timer_record('类目属性阶段', f'{material_field_name or "材质"}配置写入', 0, system_time.perf_counter() - step_timer_start, material_ok)
        step_timer_start = system_time.perf_counter()
        if not ensure_no_brand(main_tab):
            raise Exception('品牌未能设置为「无品牌」')
        if has_audience_field:
            select_text(main_tab, '适用人群', '成人')
        if has_gender_field:
            select_text(main_tab, '适用性别', get_sex(record.title))
        if current_sock_height and has_sock_height_field:
            select_text(main_tab, '筒高', current_sock_height)
        timer_record('类目属性阶段', '基础属性', 0, system_time.perf_counter() - step_timer_start, True)

    _dismiss_interfering_overlays(main_tab, context='before_wash_label_upload')
    step_timer_start = system_time.perf_counter()
    uploaded_wash_label = _upload_wash_label_or_tag_image(main_tab, diaopai_pic, wash_label_tag_image_path)
    timer_record('类目属性阶段', '水洗标吊牌上传触发', 0, system_time.perf_counter() - step_timer_start, True)
    if uploaded_wash_label and has_configured_materials:
        step_timer_start = system_time.perf_counter()
        material_ok = set_material_composition(main_tab, configured_materials, material_field_name)
        timer_record('类目属性阶段', f'{material_field_name or "材质"}配置写入', 0, system_time.perf_counter() - step_timer_start, material_ok)
        if not material_ok:
            raise Exception(f'{material_field_name or "材质"}填写失败（配置写入失败）')
        print(f'已按配置写入{material_field_name or "材质"}，跳过水洗标/吊牌图 OCR 等待')
    elif uploaded_wash_label:
        step_timer_start = system_time.perf_counter()
        _fill_fabric_material_if_wash_label_unrecognized(main_tab, configured_materials)
        timer_record('类目属性阶段', '水洗标OCR判断', 0, system_time.perf_counter() - step_timer_start, True)
    timer_record('类目属性阶段', '总计', 0, system_time.perf_counter() - category_attr_timer_start, True)


def _find_ai_main_image_panel(main_tab):
    try:
        return main_tab.ele(
            'xpath://div[text()="AI智能做主图"]/ancestor::div[contains(@class,"styles_panel__") or contains(@class,"styles_wrapper__")][1]',
            timeout=0.1,
        )
    except Exception:
        return None


def _find_ai_main_image_action(panel, action_text):
    if not panel:
        return None
    selectors = (
        f'xpath:.//button[.//span[normalize-space(text())="{action_text}"]]',
        f'xpath:.//span[normalize-space(text())="{action_text}"]/ancestor::button[1]',
        f'xpath:.//*[normalize-space(text())="{action_text}"]/ancestor::button[1]',
    )
    for selector in selectors:
        try:
            button = panel.ele(selector, timeout=0.05)
        except Exception:
            button = None
        if not button:
            continue
        try:
            if button.states.is_displayed:
                return button
        except Exception:
            continue
    return None


def _drive_ai_main_image_actions(main_tab):
    """
    详情图上传前可能出现「AI智能做主图」面板。
    这里不再使用固定 3s/0.5s 停顿，而是按面板动作是否真正切换来推进。
    """
    panel = _find_ai_main_image_panel(main_tab)
    if not panel:
        return False

    apply_btn = _find_ai_main_image_action(panel, '应用')
    if apply_btn:
        try:
            apply_btn.click(by_js=True)
        except Exception:
            try:
                apply_btn.click()
            except Exception:
                pass
        _wait_until(
            lambda: bool(_find_ai_main_image_action(_find_ai_main_image_panel(main_tab), '上传'))
            or not _find_ai_main_image_panel(main_tab)
            or _is_upload_busy(main_tab),
            timeout=1.2,
            interval=0.05,
        )

    panel = _find_ai_main_image_panel(main_tab)
    upload_btn = _find_ai_main_image_action(panel, '上传')
    if not upload_btn:
        return False

    try:
        upload_btn.click(by_js=True)
    except Exception:
        try:
            upload_btn.click()
        except Exception:
            return False

    _wait_until(
        lambda: not _find_ai_main_image_panel(main_tab) or _is_upload_busy(main_tab),
        timeout=1.0,
        interval=0.05,
    )
    return True


def _wait_for_detail_upload_area_ready(main_tab, timeout=1.2, interval=0.05):
    detail_selectors = (
        'xpath://div[@attr-field-id="商品详情"]//label[.//input[@type="file"]]',
        'xpath://div[@attr-field-id="商品详情"]//div[contains(@class,"material-upload-button")]',
        'xpath://div[@attr-field-id="商品详情"]//*[contains(normalize-space(.),"上传图片")]',
    )
    return _wait_until(
        lambda: any(main_tab.ele(selector, timeout=0.05) for selector in detail_selectors),
        timeout=timeout,
        interval=interval,
    )


def _xpath_text_literal(value):
    value = str(value)
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ', "\'", '.join([f"'{part}'" for part in parts]) + ")"


def _normalize_upload_numeric_text(value):
    text = '' if value is None else str(value).strip()
    if not text:
        return ''
    cleaned = text.replace('￥', '').replace(',', '').strip()
    try:
        number = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return cleaned
    normalized = format(number.normalize(), 'f')
    if '.' in normalized:
        normalized = normalized.rstrip('0').rstrip('.')
    return normalized or '0'


def _upload_media_assets(main_tab, sub_pic_list, my_video, white_pic, detail_pic_list):
    media_timer_start = system_time.perf_counter()
    _dismiss_interfering_overlays(main_tab, context='upload_media_assets')

    step_timer_start = system_time.perf_counter()
    if len(sub_pic_list) > 0:
        _ensure_section_ready(main_tab, '主图3:4', timeout=12.0)
        upload_file(
            main_tab,
            sub_pic_list,
            '主图',
            error_size='长宽比需为3:4',
            target_field_id='主图3:4',
            wait_for_finish=False,
        )
    else:
        print("跳过3:4主图上传，尝试自动点击'从1:1主图智能裁剪'按钮")
        try:
            if click_field_action(main_tab, '主图3:4', '从1:1主图智能裁剪') or click_field_action(main_tab, '主图3:4', '从1:1主图一键填入'):
                print('成功触发3:4主图智能裁剪')
            else:
                print('未找到3:4主图智能裁剪按钮')
        except Exception as exc:
            print(f"自动点击3:4主图智能裁剪按钮失败: {str(exc)}")
            print('请手动点击3:4主图智能裁剪按钮')
    timer_record('媒体上传阶段', '3比4主图', 0, system_time.perf_counter() - step_timer_start, True)

    main_tab.ele('xpath://div[@attr-field-id="主图视频"]').scroll.to_see()
    _dismiss_interfering_overlays(main_tab, context='before_video_upload')

    step_timer_start = system_time.perf_counter()
    if my_video:
        print('开始上传主图视频...')
        upload_file(
            main_tab,
            [my_video],
            '主图视频',
            target_field_id='主图视频',
            wait_for_finish=False,
        )
    else:
        print('没有本地主图视频，尝试在主图视频区域内点击一键生成')
        if click_field_action(main_tab, '主图视频', '一键生成'):
            _wait_until(
                lambda: _is_upload_busy(main_tab) or bool(_find_ai_material_tool_panel(main_tab, timeout=0.05)),
                timeout=0.5,
                interval=0.03,
            )
        else:
            print('未找到可用的一键生成按钮，或按钮当前不可点击')
    timer_record('媒体上传阶段', '主图视频', 0, system_time.perf_counter() - step_timer_start, True)

    step_timer_start = system_time.perf_counter()
    upload_file(
        main_tab,
        [white_pic],
        '白底图',
        target_field_id='白底图',
        wait_for_finish=False,
    )
    white_prompt_timer_start = system_time.perf_counter()
    try:
        handle_white_bg_post_upload_prompts(main_tab, timeout=2.5)
    except Exception as exc:
        print(f'处理白底图上传后AI素材工具失败: {exc}')
    timer_record('媒体上传阶段', '白底图AI面板处理', 0, system_time.perf_counter() - white_prompt_timer_start, True)

    white_settle_timer_start = system_time.perf_counter()
    if not wait_white_bg_processing_complete(main_tab, timeout=3.0, interval=0.12, min_wait=0.35):
        print('白底图已触发上传，但平台自动处理未通过或未完成，按非阻塞流程继续后续发布步骤')
    timer_record('媒体上传阶段', '白底图状态短确认', 0, system_time.perf_counter() - white_settle_timer_start, True)
    try:
        close_ai_material_tool_panel(main_tab, timeout=0.2)
    except Exception:
        pass
    timer_record('媒体上传阶段', '白底图与AI收尾', 0, system_time.perf_counter() - step_timer_start, True)

    _dismiss_interfering_overlays(main_tab, context='before_detail_upload')
    step_timer_start = system_time.perf_counter()
    try:
        _drive_ai_main_image_actions(main_tab)
    except Exception:
        pass
    try:
        detail_block = main_tab.ele('xpath://div[@attr-field-id="商品详情"]', timeout=2)
        if detail_block:
            detail_block.scroll.to_see()
            _wait_for_detail_upload_area_ready(main_tab, timeout=0.6, interval=0.03)
    except Exception:
        pass
    upload_file(main_tab, detail_pic_list, '图片', extra=True, target_field_id='商品详情')
    timer_record('媒体上传阶段', '详情图', 0, system_time.perf_counter() - step_timer_start, True)
    timer_record('媒体上传阶段', '总计', 0, system_time.perf_counter() - media_timer_start, True)


def _find_price_stock_root(main_tab, timeout=0.2):
    selectors = [
        'xpath://div[@attr-field-id="价格与库存"]',
        'xpath://div[@id="goodsEditScrollContainer-价格库存"]',
        'xpath://div[@attr-field-id="售卖价"]/ancestor::div[@id="goodsEditScrollContainer-价格库存"][1]',
        'xpath://div[@attr-field-id="订单库存计数"]/ancestor::div[@id="goodsEditScrollContainer-价格库存"][1]',
    ]
    return _find_first_visible_element(main_tab, selectors, timeout=timeout)


def _scroll_to_price_stock_area(main_tab, timeout=2.0):
    price_stock_root = _find_price_stock_root(main_tab, timeout=0.1)
    if price_stock_root:
        try:
            price_stock_root.scroll.to_see()
        except Exception:
            try:
                price_stock_root.scroll.to_center()
            except Exception:
                pass
        return price_stock_root

    legacy_title = None
    try:
        legacy_title = main_tab.ele('xpath://span[text()="价格与库存"]', timeout=0.1)
    except Exception:
        legacy_title = None
    if legacy_title:
        try:
            legacy_title.scroll.to_see()
        except Exception:
            pass

    if _wait_until(lambda: bool(_find_price_stock_root(main_tab, timeout=0.05)), timeout=timeout, interval=0.05):
        return _find_price_stock_root(main_tab, timeout=0.1)
    raise Exception('未找到价格库存区域')


def _find_manual_sku_mode_button(main_tab):
    selectors = [
        'xpath://button[.//*[contains(normalize-space(.),"切换手动填写")] or contains(normalize-space(.),"切换手动填写")]',
        'xpath://*[contains(normalize-space(.),"切换手动填写")]/ancestor::button[1]',
    ]
    return _find_first_visible_element(main_tab, selectors, timeout=0.1)


def _ensure_manual_sku_entry_mode(main_tab):
    if _sku_color_type_exists(main_tab):
        return

    _scroll_to_price_stock_area(main_tab)
    switch_button = _find_manual_sku_mode_button(main_tab)
    if switch_button:
        print('切换规格设置 -> 手动填写')
        if not _click_element_safely(switch_button):
            raise Exception('SKU手动填写按钮点击失败')
        _wait_until(
            lambda: _sku_color_type_exists(main_tab) or bool(_find_add_spec_type_button(_find_goods_spec_field(main_tab))),
            timeout=2.0,
            interval=0.05,
        )

    if _find_manual_sku_mode_button(main_tab) and not _sku_color_type_exists(main_tab):
        raise Exception('SKU手动填写模式未成功展开')


def _configure_sku_entries(main_tab, sku_list, remark, record=None):
    _dismiss_interfering_overlays(main_tab, context='configure_sku_entries')
    _scroll_to_price_stock_area(main_tab)

    print('选择发货时间 -> 48小时')
    ship_time = main_tab.ele('xpath://span[text()="48小时"]', timeout=1)
    if not ship_time:
        raise Exception('未找到发货时间选项：48小时')
    ship_time.click()

    _ensure_manual_sku_entry_mode(main_tab)
    _ensure_color_sku_type(main_tab)

    # 勾选添加规格图片（SKU图片上传必需）
    print('勾选添加规格图片')
    add_spec_image = main_tab.ele('xpath://span[text()="添加规格图"]', timeout=1)
    if add_spec_image:
        add_spec_image.click(by_js=True)
    else:
        print('未找到添加规格图开关，跳过')

    guard = 0
    while True:
        guard += 1
        if guard > 128:
            raise Exception('清理颜色规格时出现异常循环')
        buttons = main_tab.eles('xpath://div[@id="skuValue-颜色分类"]//span[@data-kora="删除规格值"]', timeout=0.2) or []
        visible_buttons = []
        for btn in buttons:
            try:
                if btn and btn.states.is_displayed:
                    visible_buttons.append(btn)
            except Exception:
                continue
        if not visible_buttons:
            break
        before_count = len(visible_buttons)
        visible_buttons[-1].click(by_js=True)
        _wait_until(
            lambda: len([btn for btn in (main_tab.eles('xpath://div[@id="skuValue-颜色分类"]//span[@data-kora="删除规格值"]', timeout=0.05) or []) if btn and btn.states.is_displayed]) < before_count,
            timeout=0.8,
            interval=0.04,
        )

    for i, sku in enumerate(sku_list):
        set_sku_info(main_tab, i, sku, remark)
        if i < len(sku_list) - 1:
            sku_gap_start = system_time.perf_counter()
            while system_time.perf_counter() - sku_gap_start < 0.5:
                if not _is_upload_busy(main_tab):
                    break
                system_time.sleep(0.05)  # SKU间暂停，让页面完成图片处理


def _sku_color_type_exists(main_tab) -> bool:
    try:
        color_block = main_tab.ele('xpath://div[@id="skuValue-颜色分类"]', timeout=0.2)
        return bool(color_block and color_block.states.is_displayed)
    except Exception:
        return False


def _find_goods_spec_field(main_tab):
    selectors = [
        'xpath://div[@attr-field-id="商品规格"]',
        'xpath://div[@id="goodsEditScrollContainer-价格库存"]',
        'xpath://div[@attr-field-id="售卖价"]/ancestor::div[@id="goodsEditScrollContainer-价格库存"][1]',
    ]
    return _find_first_visible_element(main_tab, selectors, timeout=0.2)


def _find_add_spec_type_button(spec_field):
    if not spec_field:
        return None
    try:
        buttons = spec_field.eles(
            'xpath:.//button[.//span[contains(normalize-space(.),"添加规格类型")]]',
            timeout=0.2,
        ) or []
    except Exception:
        buttons = []
    for button in buttons:
        try:
            if button and button.states.is_displayed and button.states.is_enabled:
                return button
        except Exception:
            continue
    return None


def _find_pending_spec_type_selector(spec_field):
    if not spec_field:
        return None
    selectors = [
        'xpath:.//div[contains(@class,"ecom-g-select") and .//span[contains(normalize-space(.),"请选择规格类型")]]',
        'xpath:.//*[contains(normalize-space(.),"请选择规格类型")]/ancestor::div[contains(@class,"ecom-g-select")][1]',
    ]
    return _find_first_visible_element(spec_field, selectors, timeout=0.1)


def _find_visible_spec_type_option(main_tab, text):
    literal = _xpath_literal(text)
    selectors = [
        f'xpath://div[contains(@class,"ecom-g-select-dropdown") and not(contains(@class,"hidden"))]//*[normalize-space(.)={literal}]',
        f'xpath://div[contains(@class,"ecom-g-select-dropdown") and not(contains(@class,"hidden"))]//*[contains(normalize-space(.), {literal})]',
    ]
    return _find_first_visible_element(main_tab, selectors, timeout=0.08)


def _find_create_spec_type_entry(main_tab):
    selectors = [
        'xpath://div[contains(@class,"ecom-g-select-dropdown") and not(contains(@class,"hidden"))]//*[contains(@class,"styles_newSKU") and contains(normalize-space(.),"创建类型")]',
        'xpath://div[contains(@class,"ecom-g-select-dropdown") and not(contains(@class,"hidden"))]//*[contains(normalize-space(.),"创建类型")]',
    ]
    return _find_first_visible_element(main_tab, selectors, timeout=0.08)


def _find_custom_spec_type_input(main_tab):
    selectors = [
        'xpath://input[@placeholder="请输入规格类型"]',
        'xpath://div[contains(@class,"ecom-g-select-dropdown") and not(contains(@class,"hidden"))]//input[contains(@class,"styles_skuNameInput")]',
    ]
    return _find_first_visible_element(main_tab, selectors, timeout=0.08)


def _press_enter(main_tab):
    main_tab.run_cdp('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', windowsVirtualKeyCode=13)
    main_tab.run_cdp('Input.dispatchKeyEvent', type='keyUp', key='Enter', code='Enter', windowsVirtualKeyCode=13)


def _ensure_color_sku_type(main_tab):
    if _sku_color_type_exists(main_tab):
        return

    print('当前类目未生成颜色分类规格，创建颜色分类规格类型')
    spec_field = _find_goods_spec_field(main_tab)
    if not spec_field:
        raise Exception('未找到商品规格区域')

    add_type_button = _find_add_spec_type_button(spec_field)
    if not add_type_button:
        raise Exception('未找到添加规格类型按钮')
    add_type_button.scroll.to_center()
    add_type_button.click(by_js=True)

    if not _wait_until(lambda: bool(_find_pending_spec_type_selector(spec_field)), timeout=1.2, interval=0.04):
        raise Exception('添加规格类型后未出现规格类型选择器')

    spec_type_selector = _find_pending_spec_type_selector(spec_field)
    if not spec_type_selector or not _click_element_safely(spec_type_selector):
        raise Exception('规格类型选择器点击失败')

    if not _wait_until(
        lambda: bool(_find_visible_spec_type_option(main_tab, '颜色分类')) or bool(_find_create_spec_type_entry(main_tab)),
        timeout=1.2,
        interval=0.04,
    ):
        raise Exception('规格类型下拉未出现颜色分类或创建类型入口')

    color_option = _find_visible_spec_type_option(main_tab, '颜色分类')
    if color_option:
        if not _click_element_safely(color_option):
            raise Exception('颜色分类规格类型点击失败')
    else:
        create_entry = _find_create_spec_type_entry(main_tab)
        if not create_entry or not _click_element_safely(create_entry):
            raise Exception('创建规格类型入口点击失败')
        if not _wait_until(lambda: bool(_find_custom_spec_type_input(main_tab)), timeout=1.0, interval=0.04):
            raise Exception('未出现自定义规格类型输入框')
        custom_input = _find_custom_spec_type_input(main_tab)
        custom_input.click(by_js=True)
        custom_input.input('颜色分类', clear=True)
        if not _wait_until(lambda: custom_input.attr('value') == '颜色分类', timeout=0.5, interval=0.03):
            raise Exception('颜色分类规格类型未成功写入')
        _press_enter(main_tab)

    if not _wait_until(lambda: _sku_color_type_exists(main_tab), timeout=2.0, interval=0.05):
        raise Exception('颜色分类规格类型未创建成功')


def _sku_size_has_uniform(main_tab) -> bool:
    try:
        size_block = main_tab.ele('xpath://div[@id="skuValue-码数"]', timeout=0.2)
    except Exception:
        size_block = None
    if not size_block:
        return False
    selected_size_selectors = [
        'xpath:.//*[contains(@class,"ecom-g-cascader-picker") and contains(normalize-space(.),"均码")]',
        'xpath:.//*[contains(@class,"ecom-g-cascader-picker-label") and normalize-space(.)="均码"]',
        'xpath:.//*[contains(@class,"ecom-g-select-selection-item") and normalize-space(.)="均码"]',
        'xpath:.//*[contains(@class,"ecom-g-cascader-multiple-selection-item") and .//*[normalize-space(.)="均码"]]',
    ]
    for selector in selected_size_selectors:
        try:
            selected = size_block.ele(selector, timeout=0.05)
            if selected and selected.states.is_displayed:
                return True
        except Exception:
            continue
    try:
        price_stock_root = _find_price_stock_root(main_tab, timeout=0.05)
        if not price_stock_root:
            return False
        return bool(
            price_stock_root.ele(
                'xpath:.//td[contains(@class,"attr-column-field_spec_1")]//*[normalize-space(.)="均码"]',
                timeout=0.05,
            )
        )
    except Exception:
        return False


def _find_size_value_picker(main_tab):
    selectors = [
        'xpath://div[@id="skuValue-码数"]//div[contains(@class,"style_forCreate__")]//span[contains(@class,"ecom-g-cascader-multiple-placeholder") and contains(normalize-space(.),"码数")]/ancestor::div[contains(@class,"ecom-g-cascader-picker")][1]',
        'xpath://div[@id="skuValue-码数"]//div[contains(@class,"style_forCreate__")]//*[contains(@class,"ecom-g-cascader-picker")][1]',
        'xpath://div[@id="skuValue-码数"]//input',
    ]
    for selector in selectors:
        try:
            element = main_tab.ele(selector, timeout=0.3)
            if element and element.states.is_displayed:
                return element
        except Exception:
            continue
    return None


def _find_uniform_size_group(main_tab):
    return _find_first_visible_element(
        main_tab,
        [
            'xpath://div[contains(@class,"ecom-g-cascader-menus") and not(contains(@class,"hidden"))]//li[@title="均码" and contains(@class,"ecom-g-cascader-menu-item-expand")]',
            'xpath://div[contains(@class,"ecom-g-cascader-menus") and not(contains(@class,"hidden"))]//li[contains(@class,"ecom-g-cascader-menu-item-expand") and .//*[normalize-space(.)="均码"]]',
        ],
        timeout=0.05,
    )


def _find_uniform_size_leaf(main_tab):
    return _find_first_visible_element(
        main_tab,
        [
            'xpath://div[contains(@class,"ecom-g-cascader-menus") and not(contains(@class,"hidden"))]//li[@title="均码" and .//label[contains(@class,"ecom-g-cascader-menu-item-checkbox")]]',
            'xpath://div[contains(@class,"ecom-g-cascader-menus") and not(contains(@class,"hidden"))]//li[.//label[contains(@class,"ecom-g-cascader-menu-item-checkbox")] and .//*[normalize-space(.)="均码"]]',
        ],
        timeout=0.05,
    )


def _uniform_size_leaf_checked(main_tab) -> bool:
    leaf = _find_uniform_size_leaf(main_tab)
    if not leaf:
        return False
    try:
        return bool(
            leaf.ele(
                'xpath:.//*[contains(@class,"ecom-g-checkbox-checked") or @checked or @aria-checked="true"]',
                timeout=0.05,
            )
        )
    except Exception:
        return False


def _find_size_confirm_button(main_tab, require_enabled=False):
    buttons = main_tab.eles(
        'xpath://div[contains(@class,"ecom-g-cascader-menus") and not(contains(@class,"hidden"))]//button[.//span[contains(normalize-space(.),"确定")] or contains(normalize-space(.),"确定")]',
        timeout=0.1,
    ) or []
    for button in buttons:
        try:
            if not button.states.is_displayed:
                continue
            if require_enabled and not button.states.is_enabled:
                continue
            return button
        except Exception:
            continue
    return None


def _configure_sku_structure(main_tab):
    _dismiss_interfering_overlays(main_tab, context='configure_sku_structure')
    if _sku_size_has_uniform(main_tab):
        return

    print('选择均码')
    size_picker = _find_size_value_picker(main_tab)
    if not size_picker:
        print('当前类目没有码数规格轴，跳过均码选择')
        timer_record('SKU阶段', '码数规格轴不存在跳过', 0, 0, True)
        return
    size_picker.scroll.to_center()
    size_picker.click()

    if not _wait_until(
        lambda: bool(_find_uniform_size_group(main_tab)),
        timeout=1.2,
        interval=0.04,
    ):
        raise Exception('未找到码数均码分组选项')

    uniform_group = _find_uniform_size_group(main_tab)
    if not uniform_group or not _click_element_safely(uniform_group):
        raise Exception('码数均码分组点击失败')
    if not _wait_until(lambda: bool(_find_uniform_size_leaf(main_tab)), timeout=0.8, interval=0.04):
        raise Exception('未找到码数均码叶子选项')

    uniform_leaf = _find_uniform_size_leaf(main_tab)
    leaf_checkbox = None
    try:
        leaf_checkbox = uniform_leaf.ele('xpath:.//label[contains(@class,"ecom-g-cascader-menu-item-checkbox")]', timeout=0.05)
    except Exception:
        pass
    if not _click_element_safely(leaf_checkbox or uniform_leaf):
        raise Exception('码数均码叶子选项点击失败')
    if not _wait_until(
        lambda: _uniform_size_leaf_checked(main_tab) or bool(_find_size_confirm_button(main_tab, require_enabled=True)),
        timeout=1.0,
        interval=0.04,
    ):
        raise Exception('码数均码未成功勾选')

    confirm_button = _find_size_confirm_button(main_tab, require_enabled=True)
    if not confirm_button:
        raise Exception('码数确认按钮不可用')
    confirm_button.click()

    if not _wait_until(lambda: _sku_size_has_uniform(main_tab), timeout=2.5, interval=0.05):
        raise Exception('码数未成功选择为均码')
    _dismiss_interfering_overlays(main_tab, context='configure_sku_structure')


# 价格库存表整表扫描：一次 CDP 往返取回所有已渲染行的 key、规格文本与当前值，
# 替代「逐行 × 多次属性读取」的 DrissionPage 调用，显著降低填写过程的卡顿。
_PRICE_STOCK_ROW_SCAN_JS = r'''
const rows = this.querySelectorAll('tr[class*="ecom-g-table-row"]');
const out = [];
for (let i = 0; i < rows.length; i++) {
    const tr = rows[i];
    if (!tr.offsetParent && tr.getClientRects().length === 0) continue;
    const specs = tr.querySelectorAll('td[class*="attr-column-field_spec_"]');
    const texts = [];
    for (let j = 0; j < specs.length; j++) {
        const text = (specs[j].innerText || specs[j].textContent || '').replace(/\s+/g, ' ').trim();
        if (text) texts.push(text);
    }
    const priceInput = tr.querySelector('td[class*="attr-column-field_price"] input');
    const stockInput = tr.querySelector('td[class*="attr-column-field_stock_info"] input');
    out.push({
        key: tr.getAttribute('data-row-key') || '',
        texts: texts,
        price: priceInput ? (priceInput.value || '') : null,
        stock: stockInput ? (stockInput.value || '') : null
    });
}
return out;
'''


def _fill_price_stock_and_delivery(main_tab, record, sku_list, shipping_template_name):
    print('设置价格和库存...')
    _dismiss_interfering_overlays(main_tab, context='fill_price_and_stock')
    price_stock_root = _find_price_stock_root(main_tab)
    if not price_stock_root:
        raise Exception('未找到价格与库存区域')

    def _norm_text(value):
        return ' '.join(str(value or '').split()).strip()

    def _strip_tail_parentheses(value):
        text = _norm_text(value)
        while text:
            updated = re.sub(r'\s*[（(][^（）()]*[）)]\s*$', '', text).strip()
            if updated == text:
                break
            text = updated
        return text

    def _split_sku_name(value):
        text = _norm_text(value)
        parts = [part.strip() for part in re.split(r'\s+/\s+', text) if part.strip()]
        if len(parts) >= 2:
            return ' / '.join(parts[:-1]).strip(), _strip_tail_parentheses(parts[-1])
        return text, ''

    def _name_variants(value):
        variants = []
        raw = _norm_text(value)
        if raw:
            variants.append(raw)
        stripped = _strip_tail_parentheses(raw)
        if stripped and stripped not in variants:
            variants.append(stripped)
        inline_name, _ = _split_sku_name(raw)
        inline_name = _strip_tail_parentheses(inline_name)
        if inline_name and inline_name not in variants:
            variants.append(inline_name)
        return variants

    def _identity_from_texts(spec_texts):
        name_text = spec_texts[0] if spec_texts else ''
        size_text = _strip_tail_parentheses(spec_texts[1]) if len(spec_texts) > 1 else ''
        inline_name, inline_size = _split_sku_name(name_text)
        if inline_size and not size_text:
            size_text = inline_size
        if inline_name:
            name_text = inline_name
        return _norm_text(name_text), _norm_text(size_text)

    def _row_identity(row):
        spec_texts = []
        try:
            spec_cells = row.eles('xpath:./td[contains(@class,"attr-column-field_spec_")]', timeout=0.05) or []
        except Exception:
            spec_cells = []
        for cell in spec_cells:
            try:
                text = _norm_text(cell.text)
            except Exception:
                text = ''
            if text:
                spec_texts.append(text)
        return _identity_from_texts(spec_texts)

    def _row_matches(row_name, row_size, sku_name):
        expected_name, expected_size = _split_sku_name(sku_name)
        expected_names = set(_name_variants(expected_name or sku_name))
        row_names = set(_name_variants(row_name))
        if not expected_names.intersection(row_names):
            return False
        if expected_size and row_size and _strip_tail_parentheses(expected_size) != _strip_tail_parentheses(row_size):
            return False
        return True

    def _visible_rows(root):
        try:
            rows = root.eles('xpath:.//tr[contains(@class,"ecom-g-table-row")]', timeout=0.1) or []
        except Exception:
            rows = []
        result = []
        for row in rows:
            try:
                if row and row.states.is_displayed:
                    result.append(row)
            except Exception:
                continue
        return result

    def _row_key(row, row_name, row_size):
        try:
            key = _norm_text(row.attr('data-row-key'))
        except Exception:
            key = ''
        return key or f'{row_name}||{row_size}'

    def _input_in_row(row, field):
        try:
            return row.ele(f'xpath:./td[contains(@class,"attr-column-field_{field}")]//input', timeout=0.2)
        except Exception:
            return None

    def _scan_rows(root):
        """一次往返取回所有已渲染行的 key / 规格文本 / 当前值。

        逐行走 DrissionPage 属性读取每行要 4~5 次 CDP 往返（可见性、规格单元格、
        单元格文本、data-row-key），再叠加等待重渲染的轮询后可达数千次，
        是填写过程卡顿的主因。这里用一次整表 JS 扫描替代；
        JS 不可用时回退到逐行读取，保证功能不依赖该优化。

        返回 (rows, blank_row_count)，rows 元素为
        {'key','name','size','price','stock'}，name/size 已按既有规则规范化。
        """
        raw = None
        try:
            raw = root.run_js(_PRICE_STOCK_ROW_SCAN_JS)
        except Exception:
            raw = None

        rows = []
        blank = 0
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                texts = [_norm_text(text) for text in (item.get('texts') or [])]
                texts = [text for text in texts if text]
                name, size = _identity_from_texts(texts)
                if not name and not size:
                    blank += 1
                    continue
                rows.append({
                    'key': _norm_text(item.get('key')) or f'{name}||{size}',
                    'name': name,
                    'size': size,
                    'price': item.get('price'),
                    'stock': item.get('stock'),
                })
            return rows, blank

        for row in _visible_rows(root):
            name, size = _row_identity(row)
            if not name and not size:
                blank += 1
                continue
            rows.append({
                'key': _row_key(row, name, size),
                'name': name,
                'size': size,
                'price': None,
                'stock': None,
                'element': row,
            })
        return rows, blank

    def _find_row_by_identity(root, row_name, row_size):
        """没有 data-row-key 时的慢路径：遍历可见行按规格文本定位。"""
        for row in _visible_rows(root):
            name, size = _row_identity(row)
            if name == row_name and size == row_size:
                return row
        return None

    def _refresh_row(root, row_key):
        """按 data-row-key 重新解析行元素。

        虚拟列表在 scroll.to_center() 后可能重新挂载行，旧句柄随之失效，
        继续拿旧句柄取输入框只会得到 None。row_key 为回退值（name||size）时
        无法精确定位，返回 None 交由调用方走下一轮重扫。
        """
        if not row_key or '||' in row_key:
            return None
        try:
            return root.ele(f'xpath:.//tr[@data-row-key={_xpath_literal(row_key)}]', timeout=0.3)
        except Exception:
            return None

    def _holder():
        for selector in (
            'xpath:.//div[contains(@class,"ecom-g-table-tbody-virtual-holder")]',
            'xpath:.//div[contains(@class,"ecom-g-table-tbody-virtual") and contains(@class,"ecom-g-table-tbody")]',
        ):
            try:
                item = price_stock_root.ele(selector, timeout=0.1)
            except Exception:
                item = None
            if item:
                return item
        return None

    def _metrics(holder):
        if not holder:
            return {'top': 0, 'height': 0, 'total': 0}
        try:
            data = holder.run_js('return {top: this.scrollTop || 0, height: this.clientHeight || 0, total: this.scrollHeight || 0};') or {}
        except Exception:
            data = {}
        return {
            'top': int(data.get('top') or 0),
            'height': int(data.get('height') or 0),
            'total': int(data.get('total') or 0),
        }

    def _set_top(holder, top):
        if holder:
            holder.run_js('this.scrollTop = arguments[0]; this.dispatchEvent(new Event("scroll", {bubbles:true}));', int(top))

    def _row_keys_snapshot(root):
        """当前已渲染行的 key 序列，用来判断虚拟列表是否真的换了一批行。

        该函数在等待重渲染的轮询里被反复调用，必须走整表扫描的单次往返，
        否则每次轮询都要按行发起数十次 CDP 调用。
        """
        rows, _ = _scan_rows(root)
        return tuple(item['key'] for item in rows)

    def _scroll_rows_to(holder, root, target_top, previous_keys):
        """滚到指定位置，并等虚拟列表真正渲染出新的一批行。

        rc-virtual-list 的 scrollTop 是同步赋值、行渲染是 React 异步的，
        只等 scrollTop 数值到位会立刻通过（等于没等），随后读到的仍是上一屏的旧行，
        表现为「滚到底还剩最后几个 SKU 没填」。因此这里额外等待行 key 集合发生变化。
        """
        _set_top(holder, target_top)
        _wait_until(
            lambda: abs((_metrics(holder).get('top') or 0) - target_top) <= 2,
            timeout=0.5,
            interval=0.02,
        )
        if not previous_keys:
            return
        _wait_until(
            lambda: _row_keys_snapshot(root) not in ((), previous_keys),
            timeout=1.5,
            interval=0.05,
        )

    holder = _holder()
    if holder:
        _set_top(holder, 0)
        _wait_until(lambda: abs((_metrics(holder).get('top') or 0) - 0) <= 2, timeout=0.2, interval=0.02)

    processed_keys = set()
    pending_indexes = list(range(len(sku_list)))
    guard = 0
    rollback_count = 0
    last_keys = None
    while pending_indexes:
        guard += 1
        if guard > max(len(sku_list) * 8, 32):
            raise Exception('价格库存填写过程中出现异常循环，未能按顺序推进')

        price_stock_root = _find_price_stock_root(main_tab)
        if not price_stock_root:
            raise Exception('未找到价格与库存区域')
        holder = _holder()

        scanned_rows, blank_rows = _scan_rows(price_stock_root)
        if not scanned_rows and not blank_rows:
            raise Exception('未找到价格库存表格行')
        last_keys = tuple(item['key'] for item in scanned_rows)

        for item in scanned_rows:
            row_name, row_size = item['name'], item['size']
            row_key = item['key']
            if row_key in processed_keys:
                continue

            # 在所有尚未填写的 SKU 里找与当前行匹配的那一条。
            # 不能只匹配「下一个」SKU：虚拟滚动换屏会跳行，页面行序也不保证与
            # sku_list 顺序一致，按序匹配会让整屏行全部落空，最终卡死在滚动未推进。
            matched_index = None
            for candidate_index in pending_indexes:
                candidate_name = str(sku_list[candidate_index].get('name', '')).strip()
                if _row_matches(row_name, row_size, candidate_name):
                    matched_index = candidate_index
                    break
            if matched_index is None:
                continue

            sku = sku_list[matched_index]
            sku_name = str(sku.get('name', '')).strip()
            sku_price = _normalize_upload_numeric_text(sku.get('price'))
            sku_stock = _normalize_upload_numeric_text(record.repo)

            # 扫描时已带回当前值：命中目标值就无需重写（回滚重扫时可直接略过整屏）
            if (
                item.get('price') is not None
                and _normalize_upload_numeric_text(item.get('price')) == sku_price
                and _normalize_upload_numeric_text(item.get('stock')) == sku_stock
            ):
                processed_keys.add(row_key)
                pending_indexes.remove(matched_index)
                continue

            # 只对确实要填的行做 DOM 定位，避免整屏行都走一遍元素查找
            tr = item.get('element') or _refresh_row(price_stock_root, row_key)
            if tr is None:
                tr = _find_row_by_identity(price_stock_root, row_name, row_size)
            if tr is None:
                continue
            tr.scroll.to_center()

            # to_center() 可能触发虚拟列表重挂载，使 tr 句柄失效，
            # 先按 data-row-key 重新解析一次再取输入框。
            row_element = _refresh_row(price_stock_root, row_key) or tr
            price_input = _input_in_row(row_element, 'price')
            stock_input = _input_in_row(row_element, 'stock_info')
            if not price_input or not stock_input:
                # 多为重渲染导致的句柄失效，本轮跳过、交给下一轮以新句柄重扫；
                # 若确实是结构缺失，最终会带着「页面当前可见行」一并报错，不会被静默吞掉。
                continue

            filled_no = len(sku_list) - len(pending_indexes) + 1
            print(f'填写SKU价格库存 -> {filled_no}/{len(sku_list)}. {sku_name} | 价格:{sku_price} | 库存:{sku_stock}')

            price_input.input(sku_price, clear=True)
            stock_input.input(sku_stock, clear=True)

            expected_price = _normalize_upload_numeric_text(sku_price)
            expected_stock = _normalize_upload_numeric_text(sku_stock)

            def _written():
                return (
                    _normalize_upload_numeric_text(price_input.attr('value')) == expected_price
                    and _normalize_upload_numeric_text(stock_input.attr('value')) == expected_stock
                )

            if not _wait_until(_written, timeout=2.0, interval=0.1):
                price_value = _normalize_upload_numeric_text(price_input.attr('value'))
                stock_value = _normalize_upload_numeric_text(stock_input.attr('value'))
                raise Exception(
                    f'价格库存写入校验失败：{sku_name} -> 期望价格[{expected_price}] 实际价格[{price_value}] 期望库存[{expected_stock}] 实际库存[{stock_value}]'
                )

            processed_keys.add(row_key)
            pending_indexes.remove(matched_index)

        if blank_rows:
            print(f'跳过价格库存空白行：{blank_rows} 行')

        if not pending_indexes:
            break

        def _remaining_text():
            return '、'.join(
                str(sku_list[index].get('name', '')).strip() for index in pending_indexes[:5]
            )

        def _visible_rows_text():
            names = []
            for row in _visible_rows(price_stock_root):
                row_name, row_size = _row_identity(row)
                if not row_name and not row_size:
                    continue
                names.append(f'{row_name}+{row_size}' if row_size else row_name)
            return '、'.join(names[:8]) or '(无)'

        if not holder:
            raise Exception(
                f'价格库存可见行不足，剩余SKU未填写：{_remaining_text()}'
                f'｜页面当前可见行：{_visible_rows_text()}'
            )

        # 一律以页面真实滚动位置为准推进：填写时的 tr.scroll.to_center() 会在背后
        # 改变 scrollTop，若继续按本地维护的目标值回设，两者会来回拉扯，
        # 表现为「填到一半后可见行被拉回开头，再也推进不了」。
        data = _metrics(holder)
        viewport_height = data.get('height') or 0
        total_height = data.get('total') or 0
        current_top = data.get('top') or 0
        max_top = max(total_height - viewport_height, 0)
        # 步长取半屏，留足重叠区域，减少虚拟滚动跳行
        step = max(int(viewport_height * 0.50), 120) if viewport_height else 120
        next_top = min(current_top + step, max_top)
        if next_top <= current_top:
            # 已滚到底但还有 SKU 未填写——可能被跳行遗漏了，
            # 回滚到顶部重新完整扫描一遍（最多回滚 2 次防死循环）。
            # 清空 processed_keys 让每一行重新参与匹配；pending_indexes 保证已填的 SKU 不会重复写。
            if current_top > 0 and rollback_count < 2:
                rollback_count += 1
                print(f'价格库存滚动到底仍有 {len(pending_indexes)} 个SKU未填写，回滚重扫(第{rollback_count}次)')
                processed_keys.clear()
                _scroll_rows_to(holder, price_stock_root, 0, last_keys)
                last_keys = None
                continue
            raise Exception(
                f'价格库存滚动未推进，剩余SKU未填写：{_remaining_text()}'
                f'｜页面当前可见行：{_visible_rows_text()}'
            )
        _scroll_rows_to(holder, price_stock_root, next_top, last_keys)

    main_tab.ele('xpath://span[text()="售后服务承诺"]').scroll.to_see()
    select_text(main_tab, '运费模板', shipping_template_name, '包邮')
    youhui_btn = main_tab.ele('xpath://button[contains(@class,"marketing_sylva-switch-checked")]', timeout=1)
    if youhui_btn:
        print('取消商品优惠券勾选')
        youhui_btn.click(by_js=True)

    print('选择商品状态 -> 上架')
    main_tab.ele('xpath://span[text()="上架"]').click(by_js=True)

    try:
        switch = main_tab.ele('xpath://button[@dropdownclassname="auto-dropdown-id-支持联盟达人带货"]', timeout=2)
        if switch and switch.states.is_displayed:
            cls = switch.attr('class') or ''
            disabled_attr = switch.attr('disabled')
            if ('disabled' not in cls) and (disabled_attr is None):
                print('勾选支持联盟达人带货')
                switch.click(by_js=True)
                rate_input = main_tab.ele('xpath://label[@title="佣金率"]/../..//input', timeout=2)
                if rate_input:
                    print('输入佣金率：20%')
                    rate_input.input('20')
                    _wait_until(
                        lambda: _normalize_upload_numeric_text(rate_input.attr('value')) == '20',
                        timeout=0.6,
                        interval=0.03,
                    )
            else:
                print('联盟达人带货不可用，已跳过')
        else:
            print('未找到联盟达人带货开关，已跳过')
    except Exception:
        print('处理联盟达人带货失败，已跳过')


def _submit_publish(main_tab, record):
    print('发布商品')
    _dismiss_interfering_overlays(main_tab, context='submit_publish')
    main_tab.ele('xpath://span[text()="发布商品"]/..').click()
    # @class 全等匹配在组件追加 class 时会失效，这里放宽为 contains
    modal_selector = (
        'xpath://div[contains(@class,"ecom-g-modal-title") and normalize-space(text())="发布提醒"]/../..'
    )
    success_selector = '商品提交成功，继续发布商品视频，分享到抖音'

    def _handle_publish_modal():
        """处理「发布提醒」弹窗。

        该弹窗可能迟于点击若干秒才出现，因此必须在整个等待窗口内持续尝试：
        原实现只在前 1.2s 查一次，弹窗迟到就再也不会被点掉，
        随后白等满 12s 判定失败——而失败路径不落库，重跑即造成重复铺货。
        """
        try:
            modal = main_tab.ele(modal_selector, timeout=0.05)
        except Exception:
            return False
        if not modal:
            return False
        try:
            continue_btn = modal.ele(
                'xpath:.//div[text()="不修改，继续发布"]/ancestor::button', timeout=0.1
            )
        except Exception:
            continue_btn = None
        if not continue_btn:
            return False
        try:
            continue_btn.scroll.to_center()
            continue_btn.click()
        except Exception as exc:
            print(f'处理发布提醒弹窗失败: {exc}')
            return False
        print('已处理发布提醒弹窗')
        return True

    publish_ok = False
    deadline = system_time.perf_counter() + 13.0
    while True:
        try:
            if main_tab.ele(success_selector, timeout=0.05):
                publish_ok = True
                break
        except Exception:
            pass
        if _handle_publish_modal():
            _dismiss_interfering_overlays(main_tab, context='after_publish_click')
            continue
        if system_time.perf_counter() >= deadline:
            break
        system_time.sleep(0.15)

    if publish_ok:
        print('发布成功！')
        record.status = 1
        record.publish_time = time.now()
        record.save()
        return True

    # 未读到成功文案不等于一定没提交（文案改版、页面跳转都会这样），
    # 而失败路径不写 record.status，重跑会重复铺货——把现场信息打出来供人工确认。
    print('发布失败！')
    print(f'  当前页面: {_get_current_tab_url(main_tab)}')
    print('  若页面已离开发布页或商品已出现在商品列表，说明可能已提交成功，请先人工核对再重跑，避免重复铺货')
    return False


def _execute_upload_flow(record_id=None, progress_callback=None, stop_before_submit=False, task_id=None):
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
        user_settings = settings_manager.get_settings()
        ac = settings_manager.normalize_automation_config(user_settings.automation_config)
        publish_mode = ac.get('publish_mode', 'dom')
        print(f'[路由] 发布模式: {publish_mode}')

        # 官方API模式 (待实现)
        if publish_mode == 'official':
            return api_error(msg='官方API模式尚未实现，请在设置中切换为DOM或协议模式')

        # 读取记录和配置(所有模式共用)
        record_list, load_error = _load_upload_records(record_id)
        if load_error:
            return api_error(msg=load_error)
        _report_progress(12, '已读取上传任务，正在初始化自动化参数')
        shipping_template_name, configured_materials, wash_label_tag_image_path = _load_upload_runtime_config()

        # 纯协议模式：独立CDP连接，不需要DOM浏览器
        if publish_mode == 'protocol':
            print('[路由] 启动纯协议流水线...')
            import sys as _sys
            _base = _sys._MEIPASS if getattr(_sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
            _sys.path.insert(0, os.path.join(_base, 'protocol-research'))
            return _execute_protocol_flow(
                record_id=record_id,
                progress_callback=progress_callback,
                task_id=task_id,
                stop_before_submit=stop_before_submit,
            )

        # DOM模式：原有流程
        print('开始上传流程...')
        main_tab, session_error = _ensure_publish_session(_report_progress)
        if session_error:
            return api_error(msg=session_error)
        _report_progress(15, '上传浏览器会话已就绪')

        for record in record_list:
            # 检查取消标志
            if task_id:
                with _upload_tasks_lock:
                    t = _upload_tasks.get(task_id)
                    if t and t.get('cancelled'):
                        t['status'] = 'cancelled'
                        t['message'] = '任务已被用户取消'
                        t['finished_at'] = datetime.now().isoformat()
                        return api_ok(msg='任务已取消')

            # 类目展开状态是 src/utils.py 的模块级全局缓存，一旦置 True 就不再复位；
            # 不在每条记录开始时重置，第 2 个商品起类目属性区不会展开，
            # 品牌/适用人群/适用性别/筒高等字段全部定位不到。
            reset_category_expanded_state()

            record_ok = False
            error_tip = ''
            stopped_before_submit = False
            current_stage = 'prechecks'
            stage_timings = []
            record_started_at = datetime.now().isoformat()
            record_perf_started_at = system_time.perf_counter()
            timer_session_id = f'upload_record_{getattr(record, "id", "unknown")}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
            timer_start_session(timer_session_id)
            _report_progress(16, f'正在处理商品：{record.name}')

            try:
                record_assets, error_tip = _prepare_record_assets(record)
                if error_tip:
                    continue

                current_stage = 'open_publish_page'
                if not _run_stage_with_timing(
                    stage_timings,
                    record,
                    current_stage,
                    _open_publish_page,
                    main_tab,
                    _report_progress,
                ):
                    return api_error('页面未就绪，请稍后重试')

                current_stage = 'fill_title'
                _run_stage_with_timing(
                    stage_timings,
                    record,
                    current_stage,
                    _fill_title_for_record,
                    main_tab,
                    record,
                )

                current_stage = 'upload_main_images'
                _report_progress(32, '正在上传主图并选择类目')
                _run_stage_with_timing(
                    stage_timings,
                    record,
                    current_stage,
                    _upload_main_images,
                    main_tab,
                    record,
                    record_assets['main_pic_list'],
                )

                current_stage = 'select_category'
                _run_stage_with_timing(
                    stage_timings,
                    record,
                    current_stage,
                    _select_category_and_prepare_attributes,
                    main_tab,
                    record,
                    record_assets['diaopai_pic'],
                )

                current_stage = 'fill_category_attributes'
                _report_progress(46, '正在填写类目属性与面料材质')
                _run_stage_with_timing(
                    stage_timings,
                    record,
                    current_stage,
                    _fill_category_attributes,
                    main_tab,
                    record,
                    configured_materials,
                    record_assets['diaopai_pic'],
                    wash_label_tag_image_path,
                )

                current_stage = 'upload_media_assets'
                _report_progress(60, '正在上传主图视频、白底图与详情图')
                _run_stage_with_timing(
                    stage_timings,
                    record,
                    current_stage,
                    _upload_media_assets,
                    main_tab,
                    record_assets['sub_pic_list'],
                    record_assets['my_video'],
                    record_assets['white_pic'],
                    record_assets['detail_pic_list'],
                )

                current_stage = 'configure_sku_entries'
                _report_progress(74, '正在填写规格与SKU信息')
                _run_stage_with_timing(
                    stage_timings,
                    record,
                    current_stage,
                    _configure_sku_entries,
                    main_tab,
                    record_assets['sku_list'],
                    record.remark,
                    record,
                )

                current_stage = 'configure_sku_structure'
                _report_progress(78, '正在选择码数')
                _run_stage_with_timing(
                    stage_timings,
                    record,
                    current_stage,
                    _configure_sku_structure,
                    main_tab,
                )

                current_stage = 'fill_price_and_stock'
                _report_progress(84, '正在填写价格库存与发货配置')
                _run_stage_with_timing(
                    stage_timings,
                    record,
                    current_stage,
                    _fill_price_stock_and_delivery,
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
                    timer_record('提交阶段', '提交前截停', 0, 0, True)
                else:
                    current_stage = 'submit_publish'
                    _report_progress(95, '正在提交发布请求')
                    record_ok = _run_stage_with_timing(
                        stage_timings,
                        record,
                        current_stage,
                        _submit_publish,
                        main_tab,
                        record,
                    )

            except Exception as e:
                detailed_error = traceback.format_exc()
                print('------------- 详细错误报告 -------------')
                print(detailed_error)
                print('------------------------------------')
                try:
                    _record_browser_automation_error(
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
                substep_summary = timer_end_session()
                _append_stage_timing_log({
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
                _settle_between_records(main_tab)
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


@app.post('/start')
def start():
    request_data = request.get_json(silent=True) or {}
    try:
        stop_before_submit, _ = _resolve_upload_stop_before_submit(request_data)
    except ValueError as e:
        return api_error(msg=str(e))

    return _execute_upload_flow(
        record_id=request_data.get('record_id'),
        stop_before_submit=stop_before_submit,
    )


_upload_tasks = {}
_upload_tasks_lock = threading.Lock()


def _resolve_upload_stop_before_submit(data):
    payload = data or {}
    raw_stop = payload.get('stop_before_submit', payload.get('stopBeforeSubmit', True))
    stop_before_submit = _debug_bool(raw_stop, True)
    confirm_final_publish = _debug_bool(
        payload.get('confirm_final_publish', payload.get('confirmFinalPublish')),
        False,
    )

    if not stop_before_submit and not confirm_final_publish:
        raise ValueError('最终发布需要 confirm_final_publish=true；未确认时只能执行 stop_before_submit 预检')

    return stop_before_submit, confirm_final_publish


def _serialize_upload_task(task):
    return {
        'task_id': task.get('task_id'),
        'record_id': task.get('record_id'),
        'record_name': task.get('record_name'),
        'status': task.get('status'),
        'progress': task.get('progress', 0),
        'message': task.get('message', ''),
        'current_step': task.get('current_step'),
        'steps': task.get('steps') or [],
        'error': task.get('error'),
        'created_at': task.get('created_at'),
        'started_at': task.get('started_at'),
        'finished_at': task.get('finished_at'),
        'debug_report': task.get('debug_report'),
        'stop_before_submit': task.get('stop_before_submit', False),
        'final_publish_confirmed': task.get('final_publish_confirmed', False),
        'cancelled': task.get('cancelled', False),
    }


def _protocol_cdp_port_candidates():
    ports = [9222, 9223]
    ports.extend(range(_DEBUG_BROWSER_PORT_START, _DEBUG_BROWSER_PORT_END + 1))
    ports.extend(range(_CAPTURE_BROWSER_PORT_START, _CAPTURE_BROWSER_PORT_END + 1))

    seen = set()
    ordered_ports = []
    for port in ports:
        if port in seen:
            continue
        seen.add(port)
        ordered_ports.append(port)
    return ordered_ports


def _find_cdp_port_with_jinritemai():
    """扫描所有可能的 CDP 端口，挑出**已经打开抖店 tab** 的那个。
    避免协议发布错抢只打开了淘宝/天猫的采集浏览器。
    返回: 命中的端口；找不到返回 None
    """
    from urllib.request import urlopen as _urlopen
    for port in _protocol_cdp_port_candidates():
        try:
            targets = json.loads(_urlopen(f'http://127.0.0.1:{port}/json/list', timeout=0.4).read())
        except Exception:
            continue
        for t in targets:
            if 'jinritemai.com' in (t.get('url') or ''):
                return port
    return None


def _ensure_protocol_browser():
    """确保协议模式有可用的 Chrome 调试端口。
    优先复用已经打开抖店 tab 的浏览器；找不到才用 get_page() 启动新浏览器。
    返回: (cdp_port, browser_page)
    """
    # 1. 优先找已有抖店 tab 的端口（避开纯采集浏览器）
    port = _find_cdp_port_with_jinritemai()
    if port:
        print(f'[协议] 复用已有抖店浏览器调试端口: {port}')
        return port, None

    # 2. 找不到才启新浏览器
    print('[协议] 未检测到带抖店 tab 的 Chrome，通过 DOM 流程启动浏览器...')
    try:
        from src.utils import get_page
        page = get_page('https://fxg.jinritemai.com')
        system_time.sleep(2)
        # 启动后再按"有抖店 tab"挑一次
        port = _find_cdp_port_with_jinritemai() or _find_cdp_port()
        if port:
            print(f'[协议] 浏览器已启动，调试端口: {port}')
            return port, page
    except Exception as e:
        print(f'[协议] get_page() 启动失败: {e}')
        import traceback
        traceback.print_exc()

    return None, None


def _execute_protocol_flow(record_id=None, progress_callback=None, task_id=None, stop_before_submit=False):
    """纯协议流水线 v4：CDP会话 + HTTP图片上传 + Schema获取 + 离线Body构造 + webpack提交"""
    import json as _json, sys as _sys
    if getattr(_sys, 'frozen', False):
        _base = _sys._MEIPASS
    else:
        _base = repo_root
    _sys.path.insert(0, os.path.join(_base, 'protocol-research-clean-20260505', 'scripts'))

    # === 自动启动浏览器 + 等待登录 ===
    _proto_port, _proto_page = _ensure_protocol_browser()
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
                app.logger.info(f'[登录检测] url={_cur_url[:80]} jinritemai_cookies={len(jinritemai_cookies)} wait={_wait_i+1}s')

                if len(jinritemai_cookies) >= 3 and 'login' not in _cur_url.lower():
                    _logged_in = True
        except Exception as _le:
            app.logger.debug(f'[登录检测] 异常（忽略）: {_le}')

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
        _diag_log_dir = os.path.dirname(os.path.abspath(__file__))
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
    record_list, load_error = _load_upload_records(record_id)
    _diag(f'load_records: count={len(record_list) if record_list else 0} error={load_error}')
    if load_error:
        _diag(f'RETURN load_error: {load_error}')
        return api_error(msg=load_error)

    results = []
    total = len(record_list)

    for idx, record in enumerate(record_list):
        if task_id:
            with _upload_tasks_lock:
                t = _upload_tasks.get(task_id)
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

        # 材质：读取用户在设置中配置的材质组成，拼成 "棉75%;氨纶25%" 格式
        # 历史上这里 fallback 到 '棉75%;氨纶25%' 且 record.material 字段根本不存在，已修正
        material_str = ''
        try:
            _ms = settings_manager.get_settings()
            _ac = settings_manager.normalize_automation_config(_ms.automation_config)
            _materials = _ac.get('material_compositions') or []
            material_str = ';'.join(
                f"{m.get('material','').strip()}{int(m.get('percentage',0))}%"
                for m in _materials
                if m.get('material') and int(m.get('percentage', 0) or 0) > 0
            )
        except Exception as _me:
            _diag(f'load material from settings failed: {_me}')

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
            main_pics = get_pic_list(record, '800')
            image_paths['main_images_1x1'] = [p for p in main_pics[:5] if os.path.isfile(p)]
        except Exception as e:
            print(f'[协议] 获取800主图失败: {e}')

        try:
            # 3:4 主图 (750) → main_images → 用于 main_image_three_to_four
            sub_pics = get_pic_list(record, '750')
            image_paths['main_images'] = [p for p in sub_pics[:5] if os.path.isfile(p)]
        except Exception as e:
            print(f'[协议] 获取750主图失败: {e}')

        try:
            # 详情图
            detail_pics = get_detail_pic_list(record)
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
                with _upload_tasks_lock:
                    t = _upload_tasks.get(task_id)
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
            _ss = settings_manager.get_settings()
            _ac_now = settings_manager.normalize_automation_config(_ss.automation_config)
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
            time.sleep(2)

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


def _run_upload_task(task_id: str, record_id=None, stop_before_submit=False):
    with _upload_tasks_lock:
        task = _upload_tasks.get(task_id)
        if not task:
            return
        task['status'] = 'running'
        task['progress'] = 10
        task['message'] = '正在启动浏览器并准备上传'
        task['started_at'] = datetime.now().isoformat()

    try:
        # 检查是否已被取消
        with _upload_tasks_lock:
            t = _upload_tasks.get(task_id)
            if t and t.get('cancelled'):
                t['status'] = 'cancelled'
                t['message'] = '任务已被用户取消'
                t['finished_at'] = datetime.now().isoformat()
                return

        # 读取发布模式: protocol / official / dom
        user_settings = settings_manager.get_settings()
        ac = settings_manager.normalize_automation_config(user_settings.automation_config)
        publish_mode = ac.get('publish_mode', 'dom')

        # 文件日志诊断 (_run_upload_task)
        import sys as _rt_sys
        _rt_log = os.path.join(os.path.dirname(_rt_sys.executable) if getattr(_rt_sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__)), 'run_task_diag.log')
        try:
            with open(_rt_log, 'a', encoding='utf-8') as _f:
                _f.write(f'{datetime.now().isoformat()} | _run_upload_task: publish_mode={publish_mode} record_id={record_id} task_id={task_id}\n')
        except:
            pass

        if publish_mode == 'protocol':
            def _protocol_progress_callback(pct, msg, step_name=None, steps=None):
                with _upload_tasks_lock:
                    t = _upload_tasks.get(task_id)
                    if not t or t.get('cancelled'):
                        return
                    t['progress'] = max(0, min(int(pct), 99))
                    t['message'] = str(msg)
                    if step_name:
                        t['current_step'] = str(step_name)
                    if steps:
                        t['steps'] = list(steps)

            with _upload_tasks_lock:
                t = _upload_tasks.get(task_id)
                if t: t['message'] = '协议模式：正在初始化CDP会话'
            result = _execute_protocol_flow(
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
            with _upload_tasks_lock:
                t = _upload_tasks.get(task_id)
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
            with _upload_tasks_lock:
                task = _upload_tasks.get(task_id)
                if not task or task.get('cancelled'):
                    return
                safe_progress = max(0, min(int(progress), 99))
                task['progress'] = safe_progress
                if message:
                    task['message'] = str(message)

        result = _execute_upload_flow(
            record_id=record_id,
            progress_callback=_task_progress_callback,
            stop_before_submit=stop_before_submit,
            task_id=task_id,
        )

        success = bool(result.get('success'))
        message = str(result.get('msg') or '')

        with _upload_tasks_lock:
            task = _upload_tasks.get(task_id)
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
                task['debug_report'] = _latest_browser_debug_error_after(task.get('started_at'))
                task['finished_at'] = datetime.now().isoformat()
    except Exception as e:
        traceback.print_exc()
        with _upload_tasks_lock:
            task = _upload_tasks.get(task_id)
            if not task:
                return
            task['status'] = 'failed'
            task['progress'] = 100
            task['message'] = '上传失败'
            task['error'] = str(e)
            task['finished_at'] = datetime.now().isoformat()
            task['debug_report'] = _latest_browser_debug_error_after(task.get('started_at'))


@app.post('/api/upload/start')
def upload_start():
    data = request.get_json(silent=True) or {}
    try:
        stop_before_submit, final_publish_confirmed = _resolve_upload_stop_before_submit(data)
    except ValueError as e:
        return api_error(msg=str(e))

    record_id = data.get('record_id')
    record_name = '全部商品'

    if record_id:
        record = Record.get_or_none(Record.id == record_id)
        if not record:
            return api_error(msg='未找到要上传的商品')
        record_name = record.name or f'商品{record_id}'

    import uuid
    task_id = str(uuid.uuid4())[:8]
    task = {
        'task_id': task_id,
        'record_id': record_id,
        'record_name': record_name,
        'status': 'pending',
        'progress': 0,
        'message': '任务已创建',
        'current_step': None,
        'steps': [],
        'error': None,
        'created_at': datetime.now().isoformat(),
        'started_at': None,
        'finished_at': None,
        'debug_report': None,
        'stop_before_submit': stop_before_submit,
        'final_publish_confirmed': final_publish_confirmed,
        'cancelled': False,
    }

    with _upload_tasks_lock:
        _upload_tasks[task_id] = task

    worker = threading.Thread(target=_run_upload_task, args=(task_id, record_id, stop_before_submit), daemon=True)
    worker.start()

    return api_ok(msg='上传任务已启动', data={'task_id': task_id})


@app.post('/api/upload/ensure-session')
def upload_ensure_session():
    progress_events = []

    def _report_progress(progress, message):
        progress_events.append({
            'progress': int(progress),
            'message': str(message or '')
        })

    try:
        main_tab, error = _ensure_publish_session(_report_progress)
        if error:
            return api_error(msg=error, data={
                'browser_status': {
                    'has_browser': bool(gui.page),
                    'is_logged_in': False,
                    'current_url': None,
                    'title': None,
                },
                'events': progress_events[-20:],
            })

        current_url = None
        current_title = None
        try:
            current_url = main_tab.url
        except Exception:
            current_url = None
        try:
            current_title = main_tab.title
        except Exception:
            current_title = None

        return api_ok(msg='上传浏览器会话已就绪', data={
            'browser_status': {
                'has_browser': bool(gui.page),
                'is_logged_in': True,
                'current_url': current_url,
                'title': current_title,
            },
            'events': progress_events[-20:],
        })
    except Exception as e:
        traceback.print_exc()
        return api_error(msg=f'上传浏览器会话检查失败：{str(e)}', data={
            'browser_status': {
                'has_browser': bool(gui.page),
                'is_logged_in': False,
                'current_url': None,
                'title': None,
            },
            'events': progress_events[-20:],
        })


@app.get('/api/upload/status/<task_id>')
def upload_status(task_id):
    with _upload_tasks_lock:
        task = _upload_tasks.get(task_id)
        if not task:
            return api_error(msg='上传任务不存在')
        return api_ok(msg='获取任务状态成功', data=_serialize_upload_task(task))


@app.post('/api/upload/cancel/<task_id>')
def upload_cancel(task_id):
    with _upload_tasks_lock:
        task = _upload_tasks.get(task_id)
        if not task:
            return api_error(msg='上传任务不存在')
        if task.get('status') in ('success', 'completed', 'failed', 'cancelled'):
            return api_error(msg=f'任务已完成，无法取消（状态：{task["status"]}）')
        task['cancelled'] = True
        task['message'] = '正在取消...'
    return api_ok(msg='已发送取消指令，任务将在当前步骤完成后停止')


@app.get('/api/upload/debug/injection')
def upload_debug_injection():
    """读取协议注入调试文件"""
    import tempfile
    result_path = os.path.join(tempfile.gettempdir(), 'sku_inject_result.json')
    error_path = os.path.join(tempfile.gettempdir(), 'sku_inject_error.txt')
    data = {'result': None, 'error': None}
    try:
        if os.path.exists(result_path):
            with open(result_path, 'r', encoding='utf-8') as f:
                data['result'] = json.load(f)
    except: pass
    try:
        if os.path.exists(error_path):
            with open(error_path, 'r', encoding='utf-8') as f:
                data['error'] = f.read()
    except: pass
    return api_ok(msg='协议注入调试信息', data=data)


@app.post('/api/upload/start-all')
def upload_start_all():
    """启动全部商品上传"""
    data = request.get_json(silent=True) or {}
    try:
        stop_before_submit, final_publish_confirmed = _resolve_upload_stop_before_submit(data)
    except ValueError as e:
        return api_error(msg=str(e))

    records = list(Record.select().where(Record.status == 0).order_by(Record.id))
    if not records:
        return api_error(msg='没有待上传的商品')
    import uuid
    task_id = str(uuid.uuid4())[:8]
    task = {
        'task_id': task_id, 'record_id': None, 'record_name': f'全部({len(records)}个)',
        'status': 'pending', 'progress': 0, 'message': f'批量上传{len(records)}个商品',
        'current_step': None, 'steps': [],
        'error': None, 'created_at': datetime.now().isoformat(),
        'started_at': None, 'finished_at': None, 'debug_report': None,
        'stop_before_submit': stop_before_submit,
        'final_publish_confirmed': final_publish_confirmed,
        'cancelled': False,
    }
    with _upload_tasks_lock:
        _upload_tasks[task_id] = task
    worker = threading.Thread(target=_run_upload_task, args=(task_id, None, stop_before_submit), daemon=True)
    worker.start()
    return api_ok(msg=f'已启动批量上传({len(records)}个商品)', data={'task_id': task_id, 'count': len(records)})


@app.get('/api/upload/tasks')
def upload_tasks():
    with _upload_tasks_lock:
        tasks = [_serialize_upload_task(item) for item in _upload_tasks.values()]

    tasks.sort(key=lambda x: x.get('created_at') or '', reverse=True)
    running_task = next((item for item in tasks if item.get('status') in ('pending', 'running')), None)
    return api_ok(msg='获取任务列表成功', data={
        'tasks': tasks,
        'browser_status': {
            'current_task': running_task.get('task_id') if running_task else None,
            'has_browser': bool(gui.page),
            'is_running': bool(running_task),
        }
    })



@app.get('/menu_open')
def menu_open():
    try:
        _id = request.args.get('_id')
        if not _id:
            return api_error(msg='参数错误！')
        
        record = Record.get_by_id(_id)
        if not record:
            return api_error(msg='记录不存在！')
        
        # 打开文件夹
        import subprocess
        import platform
        
        folder_path = os.path.dirname(record.path)
        if platform.system() == 'Windows':
            os.startfile(folder_path)
        elif platform.system() == 'Darwin':  # macOS
            subprocess.run(['open', folder_path])
        else:  # Linux
            subprocess.run(['xdg-open', folder_path])
        
        return api_ok(msg='文件夹已打开！')
    except Exception as e:
        print(f"打开文件夹失败: {str(e)}")
        return api_error(msg=f'打开失败：{str(e)}')


def _is_truthy(value) -> bool:
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _is_capture_managed_record(record) -> bool:
    return (
        str(getattr(record, 'import_source', '') or '').strip().lower() == 'capture'
        and _is_truthy(getattr(record, 'managed_files', False))
    )


def _assert_safe_recycle_target(path: str) -> str:
    target_path = os.path.abspath(os.path.normpath(path or ''))
    if not target_path or not os.path.exists(target_path):
        return target_path
    root_path = os.path.abspath(os.path.splitdrive(target_path)[0] + os.sep)
    if target_path == root_path:
        raise ValueError('拒绝移动磁盘根目录到回收站')
    if os.path.dirname(target_path) == target_path:
        raise ValueError('拒绝移动系统根目录到回收站')
    return target_path


def _move_path_to_recycle_bin(path: str) -> bool:
    target_path = _assert_safe_recycle_target(path)
    if not target_path or not os.path.exists(target_path):
        return False
    if os.name != 'nt':
        raise RuntimeError('当前系统暂不支持回收站删除')

    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ('hwnd', wintypes.HWND),
            ('wFunc', wintypes.UINT),
            ('pFrom', wintypes.LPCWSTR),
            ('pTo', wintypes.LPCWSTR),
            ('fFlags', wintypes.WORD),
            ('fAnyOperationsAborted', wintypes.BOOL),
            ('hNameMappings', wintypes.LPVOID),
            ('lpszProgressTitle', wintypes.LPCWSTR),
        ]

    FO_DELETE = 3
    FOF_SILENT = 0x0004
    FOF_NOCONFIRMATION = 0x0010
    FOF_ALLOWUNDO = 0x0040
    FOF_NOERRORUI = 0x0400

    operation = SHFILEOPSTRUCTW()
    operation.hwnd = None
    operation.wFunc = FO_DELETE
    operation.pFrom = target_path + '\0\0'
    operation.pTo = None
    operation.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    operation.fAnyOperationsAborted = False
    operation.hNameMappings = None
    operation.lpszProgressTitle = None

    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0:
        raise OSError(f'移动到回收站失败，系统错误码: {result}')
    if operation.fAnyOperationsAborted:
        raise OSError('移动到回收站已被系统取消')
    return True


def _delete_product_record(record) -> None:
    if _is_capture_managed_record(record):
        moved = _move_path_to_recycle_bin(record.path)
        if moved:
            print(f"采集导入目录已移动到回收站: {record.path}")
        else:
            print(f"采集导入目录不存在，仅移除记录: {record.path}")
    Record.delete_by_id(record.id)


@app.get('/menu_delete')
def menu_delete():
    try:
        _id = request.args.get('_id')
        if not _id:
            return api_error(msg='参数错误！')
        
        record = Record.get_by_id(_id)
        if not record:
            return api_error(msg='记录不存在！')
        
        _delete_product_record(record)
        return api_ok(msg='产品删除成功！')
    except Exception as e:
        print(f"删除产品失败: {str(e)}")
        return api_error(msg=f'删除失败：{str(e)}')


def _derive_sku_name(file_name: str, dir_name: str, folder_name: str = '', sku_file_path: str = '') -> str:
    import re
    if folder_name.upper().startswith('C-'):
        normalized_path = sku_file_path.replace('\\', '/')
        if '自选备注' in dir_name or '/自选备注/' in normalized_path:
            return (dir_name or '自选备注').strip()
    arr = re.findall(r'\((.*?)\)', file_name)
    if arr:
        return str(arr[0]).strip()
    _, rest = split_number_prefix(file_name)
    candidate = (rest or file_name).replace('-', '+').strip()
    return candidate or dir_name


def _find_sku_folder(base_dir: str) -> str:
    for item in os.listdir(base_dir):
        if 'SKU' in item.upper():
            candidate = os.path.join(base_dir, item)
            if os.path.isdir(candidate):
                return candidate
    return ''


def _collect_image_files(start_dir: str):
    valid_ext = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')
    files = []
    for root, _, names in os.walk(start_dir):
        for name in sorted(names):
            if name.lower().endswith(valid_ext):
                files.append(os.path.join(root, name))
    return files


def _dedup_sku_list(sku_list):
    """按名称去重SKU，保留每个名称的第一个。返回 (去重后列表, 移除数量)"""
    seen_names = {}
    deduped = []
    removed = 0
    for sku in sku_list:
        key = str(sku.get('name', '')).strip().lower()
        if not key:
            deduped.append(sku)
            continue
        if key in seen_names:
            removed += 1
            continue
        seen_names[key] = True
        deduped.append(sku)
    return deduped, removed


def list_files_recursive(startpath):
    """递归遍历所有文件（ID模式）"""
    result = []
    for root, _, files in os.walk(startpath):
        for filename in sorted(files):
            if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
                result.append(os.path.join(root, filename))
    return result


def parse_downloaded_sku_file_name(file_stem: str):
    raw_name = html.unescape(str(file_stem or '')).strip()
    match = re.match(r'^(?:SKU[_\-\s]*)?(\d{1,4})[_\-\s]*(.*)$', raw_name, flags=re.IGNORECASE)
    if not match:
        return None, raw_name
    try:
        index_value = int(match.group(1))
    except Exception:
        index_value = None
    stripped_name = (match.group(2) or '').strip() or raw_name
    return index_value, stripped_name


def normalize_capture_sku_name(value):
    raw = html.unescape(str(value or ''))
    raw = raw.replace('&gt;', '>').replace('＞', '>').replace('/', '').replace('\\', '').replace('_', '')
    raw = re.sub(r'^(?:SKU)?\d+', '', raw, flags=re.IGNORECASE)
    raw = re.sub(r'[\s\-\+\(\)\[\]【】（）<>「」『』·.,，。:：;；!！?？"“”‘’]', '', raw)
    return raw


def infer_clazz_from_title(t: str) -> int:
    try:
        s = (t or '').lower()
        if '船袜' in s:
            return 0
        if ('短筒' in s) or ('短袜' in s):
            return 1
        if '中筒' in s:
            return 2
        if '长筒' in s:
            return 3
        if '袜套' in s:
            return 4
        return 2
    except Exception:
        return 2


def _build_duplicate_groups(sku_list):
    groups = {}
    for sku in sku_list:
        key = str(sku.get('name', '')).strip().lower()
        if not key:
            continue
        groups.setdefault(key, []).append(str(sku.get('path', '')))
    duplicate_groups = []
    for key, paths in groups.items():
        if len(paths) > 1:
            duplicate_groups.append({
                'display_name': key,
                'count': len(paths),
                'paths': paths
            })
    return duplicate_groups


@app.route('/api/import/folders', methods=['POST'])
def import_folders():
    try:
        data = request.get_json(silent=True) or {}
        paths = data.get('paths') or []
        if not isinstance(paths, list) or len(paths) == 0:
            return api_error('没有选择文件夹')

        normalized_paths = []
        seen = set()
        for raw in paths:
            if not isinstance(raw, str) or not raw.strip():
                continue
            abs_path = os.path.abspath(os.path.normpath(raw))
            path_key = abs_path.lower() if os.name == 'nt' else abs_path
            if path_key not in seen:
                seen.add(path_key)
                normalized_paths.append(abs_path)

        if len(normalized_paths) == 0:
            return api_error('没有有效的文件夹路径')

        imported_count = 0
        errors = []
        records_to_insert = []
        duplicate_sku_products = []

        for dir_path in normalized_paths:
            try:
                if not os.path.isdir(dir_path):
                    errors.append(f'{dir_path} 不是有效的文件夹')
                    continue

                sku_path = _find_sku_folder(dir_path)
                if not sku_path:
                    errors.append(f'{os.path.basename(dir_path)} 未找到SKU文件夹')
                    continue

                image_files = _collect_image_files(sku_path)
                if len(image_files) == 0:
                    errors.append(f'{os.path.basename(dir_path)} 未找到有效的SKU图片')
                    continue

                folder_name = os.path.basename(dir_path)
                sku_list = []
                seen_sku_path = set()
                for sku_file in image_files:
                    file_key = sku_file.lower() if os.name == 'nt' else sku_file
                    if file_key in seen_sku_path:
                        continue
                    seen_sku_path.add(file_key)
                    file_name = os.path.splitext(os.path.basename(sku_file))[0]
                    dir_name = os.path.basename(os.path.dirname(sku_file))
                    sku_list.append({
                        'file_name': file_name,
                        'dir_name': dir_name,
                        'name': _derive_sku_name(file_name, dir_name, folder_name, sku_file),
                        'path': sku_file,
                        'price': ''
                    })
                sku_list, dedup_count = _dedup_sku_list(sku_list)
                if dedup_count > 0:
                    app.logger.info(f'SKU去重: {folder_name} 移除了 {dedup_count} 个重复项')
                duplicate_groups = _build_duplicate_groups(sku_list)
                if duplicate_groups:
                    duplicate_sku_products.append({
                        'product_name': folder_name,
                        'path': dir_path,
                        'duplicate_groups': duplicate_groups
                    })

                records_to_insert.append({
                    'name': folder_name,
                    'path': dir_path,
                    'type': 2 if 'ID' in folder_name.upper() else 1,
                    'status': 0,
                    'repo': 100,
                    'title': '',
                    'clazz': 2,
                    'remark': '',
                    'content': json.dumps(sku_list, ensure_ascii=False),
                    'update_time': datetime.now(),
                    'import_source': 'manual',
                    'source_url': '',
                    'managed_files': False,
                })
                imported_count += 1
            except Exception as folder_error:
                errors.append(f'{os.path.basename(dir_path)}: {str(folder_error)}')

        if records_to_insert:
            db = Record._meta.database
            with db.atomic():
                paths_to_delete = [row['path'] for row in records_to_insert]
                Record.delete().where(Record.path.in_(paths_to_delete)).execute()
                Record.insert_many(records_to_insert).execute()

        result_msg = f'成功导入 {imported_count} 个文件夹'
        if errors:
            result_msg += f'，失败 {len(errors)} 个'
        if duplicate_sku_products:
            result_msg += f'，{len(duplicate_sku_products)} 个商品存在重复SKU名称'

        return api_ok(result_msg, {
            'imported_count': imported_count,
            'errors': errors,
            'duplicate_sku_products': duplicate_sku_products
        })
    except Exception as e:
        traceback.print_exc()
        return api_error(f'导入失败: {str(e)}')


# ====== 设置管理 API ======

@app.get('/settings')
def get_settings():
    """获取用户设置"""
    try:
        settings = settings_manager.get_settings()
        automation_config = settings_manager.normalize_automation_config(settings.automation_config)

        # 材质选项以「平台实采列表」为准：发布流程打开材质下拉时会顺带采集并缓存。
        # 缓存缺失（还没发过货）时退回内置默认，下拉本身支持自定义输入，不会卡住用户。
        material_meta = {}
        try:
            from src.material_options_cache import load_meta, load_options
            platform_options = load_options()
            material_meta = load_meta()
            if platform_options:
                merged = list(platform_options)
                seen = set(merged)
                for name in (automation_config.get('material_options') or []):
                    if name not in seen:
                        seen.add(name)
                        merged.append(name)
                automation_config = dict(automation_config)
                automation_config['material_options'] = merged
        except Exception as exc:
            material_meta = {'last_error': f'读取平台材质缓存失败: {exc}'}
        automation_config = dict(automation_config)
        automation_config['platform_material_options_meta'] = material_meta

        sanitized_settings = enforce_no_external_ai_settings({
            'pricing_config': settings.pricing_config,
            'cost_items': settings.cost_items,
            'model_configs': settings.model_configs,
            'automation_config': automation_config,
            'image_naming': {
                'supported_formats': settings.image_naming.supported_formats,
                'filename_filters': settings.image_naming.name_filters,
                'case_sensitive': not settings.image_naming.ignore_case,
            },
            'ui': {
                'image_hover_enabled': settings.ui_settings.enable_image_hover,
                'theme_mode': settings.ui_settings.theme_mode,
                'animations_enabled': settings.ui_settings.enable_animations,
            },
            'processing': {
                'auto_detect_folders': settings.processing.auto_detect_id_folders,
                'batch_mode_enabled': settings.processing.batch_processing_mode,
                'max_concurrent_operations': settings.processing.max_concurrent_tasks,
            }
        })
        # 发布优化模型配置允许保留(仅小米/DeepSeek)，覆盖 ops 净化对它的清空；
        # 回传时隐藏 api_key 明文，只标记是否已配置，避免密钥随设置接口外泄。
        masked_configs = []
        for cfg in (settings.model_configs or []):
            c = dict(cfg)
            c['api_key_set'] = bool(c.get('api_key'))
            c.pop('api_key', None)
            masked_configs.append(c)
        sanitized_settings['model_configs'] = masked_configs
        sanitized_settings['llm_provider_presets'] = LLM_PROVIDER_PRESETS
        return api_ok(msg='获取设置成功', data={'settings': sanitized_settings})
    except Exception as e:
        return api_error(f'获取设置失败: {str(e)}')


@app.post('/settings')
def update_settings():
    """更新用户设置"""
    try:
        data = request.get_json()
        
        # 转换前端字段名到后端字段名
        backend_data = {}
        
        if 'image_naming' in data:
            backend_data['image_naming'] = {
                'supported_formats': data['image_naming'].get('supported_formats'),
                'name_filters': data['image_naming'].get('filename_filters'),
                'ignore_case': not data['image_naming'].get('case_sensitive', False),
            }
        
        if 'ui' in data:
            backend_data['ui_settings'] = {
                'enable_image_hover': data['ui'].get('image_hover_enabled'),
                'theme_mode': data['ui'].get('theme_mode'),
                'enable_animations': data['ui'].get('animations_enabled'),
            }
        
        if 'processing' in data:
            backend_data['processing'] = {
                'auto_detect_id_folders': data['processing'].get('auto_detect_folders'),
                'batch_processing_mode': data['processing'].get('batch_mode_enabled'),
                'max_concurrent_tasks': data['processing'].get('max_concurrent_operations'),
            }

        if 'pricing_config' in data:
            backend_data['pricing_config'] = data.get('pricing_config')

        if 'cost_items' in data:
            backend_data['cost_items'] = data.get('cost_items')

        if 'model_configs' in data:
            # 发布优化模型配置：交由 config.sanitize_model_configs 校验(仅放行小米/DeepSeek)。
            # 前端未改密钥时可传 api_key_set 占位，此处与已存配置做合并保留旧密钥。
            incoming = data.get('model_configs') or []
            existing = {c.get('id'): c for c in (settings_manager.get_settings().model_configs or [])}
            merged = []
            for c in incoming:
                if not isinstance(c, dict):
                    continue
                c = dict(c)
                # 未提交新密钥(只回传占位)时，沿用已存密钥
                if not c.get('api_key') and c.get('id') in existing:
                    c['api_key'] = existing[c['id']].get('api_key', '')
                merged.append(c)
            backend_data['model_configs'] = merged

        if 'automation_config' in data:
            automation_config = data.get('automation_config') or {}
            normalized_automation = settings_manager.normalize_automation_config(automation_config)
            material_compositions = automation_config.get('material_compositions') or []
            if isinstance(material_compositions, list) and len(material_compositions) > 0:
                total_percentage = 0
                for item in material_compositions:
                    if not isinstance(item, dict):
                        continue
                    material_name = str(item.get('material') or '').strip()
                    # 允许自定义材质：平台会持续新增面料，按内置白名单拒绝会把新材质挡在外面。
                    # 这里只校验名称非空与长度，名称能否被平台接受由发布流程在真实页面上校验并报错。
                    if not material_name:
                        return api_error('材质名称不能为空')
                    if len(material_name) > MATERIAL_NAME_MAX_LENGTH:
                        return api_error(f'材质名称过长（上限 {MATERIAL_NAME_MAX_LENGTH} 字）：{material_name[:20]}…')
                    try:
                        total_percentage += int(float(item.get('percentage', 0) or 0))
                    except Exception:
                        continue
                if total_percentage != 100:
                    return api_error('材质面料含量总和必须等于100')
            backend_data['automation_config'] = normalized_automation
        
        if settings_manager.update_settings(backend_data):
            return api_ok(msg='设置保存成功')
        else:
            return api_error('设置保存失败')
    except Exception as e:
        return api_error(f'设置更新失败: {str(e)}')


@app.post('/settings/automation/wash-label/import')
def import_automation_wash_label_tag_image():
    """导入自动化设置中的水洗标/吊牌图到应用数据目录"""
    try:
        data = request.get_json(silent=True) or {}
        source_path = os.path.abspath(str(data.get('source_path') or '').strip())
        if not source_path:
            return api_error('缺少水洗标/吊牌图路径')
        if not os.path.isfile(source_path):
            return api_error('水洗标/吊牌图不存在')

        try:
            target_path = _resolve_managed_wash_label_tag_image_path(source_path)
        except ValueError as exc:
            return api_error(str(exc))

        _delete_managed_wash_label_tag_image_files()
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        shutil.copy2(source_path, target_path)

        return api_ok(msg='水洗标/吊牌图导入成功', data={
            'stored_path': target_path,
            'file_name': os.path.basename(target_path),
        })
    except Exception as e:
        traceback.print_exc()
        return api_error(f'导入水洗标/吊牌图失败: {str(e)}')


@app.get('/settings/automation/wash-label/preview')
def preview_automation_wash_label_tag_image():
    """返回当前配置的水洗标/吊牌图文件"""
    try:
        user_settings = settings_manager.get_settings()
        ac = settings_manager.normalize_automation_config(user_settings.automation_config)
        img_path = str(ac.get('wash_label_tag_image_path') or '').strip()
        if not img_path or not os.path.isfile(img_path):
            return '', 404
        return send_file(img_path)
    except Exception:
        return '', 404


@app.post('/settings/automation/wash-label/remove')
def remove_automation_wash_label_tag_image():
    """删除自动化设置中的水洗标/吊牌图"""
    try:
        data = request.get_json(silent=True) or {}
        stored_path = os.path.abspath(str(data.get('stored_path') or '').strip()) if data.get('stored_path') else ''
        assets_dir = _get_automation_assets_dir()

        if stored_path:
            if not _is_path_within_dir(stored_path, assets_dir):
                return api_error('只能删除应用数据目录中的水洗标/吊牌图')
            if os.path.isfile(stored_path):
                os.remove(stored_path)
        else:
            _delete_managed_wash_label_tag_image_files()

        return api_ok(msg='水洗标/吊牌图已删除')
    except Exception as e:
        traceback.print_exc()
        return api_error(f'删除水洗标/吊牌图失败: {str(e)}')


@app.route('/settings/publish-mode', methods=['GET', 'POST'])
def publish_mode():
    """获取或设置发布模式: protocol / official / dom"""
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        mode = str(data.get('publish_mode', 'dom')).strip().lower()
        if mode not in ('protocol', 'official', 'dom'):
            return api_error(msg=f'无效的发布模式: {mode}，可选值: protocol, official, dom')
        user_settings = settings_manager.get_settings()
        ac = settings_manager.normalize_automation_config(user_settings.automation_config)
        ac['publish_mode'] = mode
        user_settings.automation_config = ac
        settings_manager.save_settings(user_settings)
        return api_ok(msg=f'发布模式已设为: {mode}', data={'publish_mode': mode})
    else:
        user_settings = settings_manager.get_settings()
        ac = settings_manager.normalize_automation_config(user_settings.automation_config)
        mode = ac.get('publish_mode', 'dom')
        return api_ok(msg='获取发布模式', data={'publish_mode': mode})


@app.post('/settings/reset')
def reset_settings():
    """重置为默认设置"""
    try:
        if settings_manager.reset_to_defaults():
            settings = settings_manager.get_settings()
            automation_config = settings_manager.normalize_automation_config(settings.automation_config)
            return api_ok(msg='设置已重置为默认值', data={'settings': {
                'pricing_config': settings.pricing_config,
                'cost_items': settings.cost_items,
                'model_configs': settings.model_configs,
                'automation_config': automation_config,
                'image_naming': {
                    'supported_formats': settings.image_naming.supported_formats,
                    'filename_filters': settings.image_naming.name_filters,
                    'case_sensitive': not settings.image_naming.ignore_case,
                },
                'ui': {
                    'image_hover_enabled': settings.ui_settings.enable_image_hover,
                    'theme_mode': settings.ui_settings.theme_mode,
                    'animations_enabled': settings.ui_settings.enable_animations,
                },
                'processing': {
                    'auto_detect_folders': settings.processing.auto_detect_id_folders,
                    'batch_mode_enabled': settings.processing.batch_processing_mode,
                    'max_concurrent_operations': settings.processing.max_concurrent_tasks,
                }
            }})
        else:
            return api_error('重置设置失败')
    except Exception as e:
        return api_error(f'重置设置失败: {str(e)}')


@app.post('/api/generate_smart_title')
def generate_smart_title():
    """🧠 智能产品标题生成API"""
    try:
        data = request.get_json()
        record_id = data.get('record_id')
        
        if not record_id:
            return api_error('缺少产品ID参数')
        
        # 获取产品信息
        try:
            record = Record.get_by_id(record_id)
        except:
            return api_error('产品不存在')
        
        # 解析SKU列表
        sku_list = json.loads(record.content) if record.content else []
        
        base_name = sanitize_no_brand_title_text(record.name) if record.name else "产品"
        base_name = base_name or "产品"
        
        # 简化的标题建议
        suggestions_data = [
            {
                'title': f"{base_name} 优质商品",
                'confidence': 0.8,
                'reasoning': "基础标题模板",
                'tags': ["基础", "通用"],
                'character_count': len(f"{base_name} 优质商品")
            },
            {
                'title': f"精选 {base_name} 推荐",
                'confidence': 0.7,
                'reasoning': "推荐标题模板",
                'tags': ["推荐", "精选"],
                'character_count': len(f"精选 {base_name} 推荐")
            },
            {
                'title': f"{base_name} 热销款",
                'confidence': 0.6,
                'reasoning': "热销标题模板",
                'tags': ["热销", "流行"],
                'character_count': len(f"{base_name} 热销款")
            }
        ]
        
        return api_ok(msg='标题生成成功！', data={
            'suggestions': suggestions_data,
            'product_info': {
                'name': base_name,
                'category': record.clazz if record.clazz else 1,
                'sku_count': len(sku_list)
            }
        })
        
    except Exception as e:
        traceback.print_exc()
        return api_error(f'标题生成失败：{str(e)}')


@app.post('/api/generate_smart_title_enhanced')
def generate_smart_title_enhanced():
    """[AI组件移除] 简化版增强标题生成API"""
    try:
        data = request.get_json()
        record_id = data.get('record_id')
        use_trending = data.get('use_trending', True)  # 是否使用热门词抓取
        
        if not record_id:
            return api_error('缺少产品ID参数')
        
        # 获取产品信息
        try:
            record = Record.get_by_id(record_id)
        except:
            return api_error('产品不存在')
        
        # 解析SKU列表
        sku_list = json.loads(record.content) if record.content else []
        
        base_name = sanitize_no_brand_title_text(record.name) if record.name else "产品"
        base_name = base_name or "产品"
        
        # 简化的增强标题建议
        suggestions_data = [
            {
                'title': f"【热销】{base_name} 精品推荐",
                'confidence': 0.9,
                'reasoning': "增强热销标题模板",
                'tags': ["热销", "精品", "推荐"],
                'character_count': len(f"【热销】{base_name} 精品推荐")
            },
            {
                'title': f"限时特价 {base_name} 优质好货",
                'confidence': 0.85,
                'reasoning': "限时特价标题模板",
                'tags': ["限时", "特价", "优质"],
                'character_count': len(f"限时特价 {base_name} 优质好货")
            },
            {
                'title': f"新品上市 {base_name} 爆款推荐",
                'confidence': 0.8,
                'reasoning': "新品爆款标题模板",
                'tags': ["新品", "爆款", "推荐"],
                'character_count': len(f"新品上市 {base_name} 爆款推荐")
            },
            {
                'title': f"品质保证 {base_name} 厂家直销",
                'confidence': 0.75,
                'reasoning': "品质保证标题模板",
                'tags': ["品质", "保证", "直销"],
                'character_count': len(f"品质保证 {base_name} 厂家直销")
            }
        ]
        
        # 模拟热门关键词
        trending_keywords = [
            {'keyword': '热销', 'trend_score': 0.9, 'platform': '抖音'},
            {'keyword': '精品', 'trend_score': 0.8, 'platform': '淘宝'},
            {'keyword': '限时', 'trend_score': 0.7, 'platform': '京东'},
            {'keyword': '新品', 'trend_score': 0.6, 'platform': '拼多多'}
        ]
        
        # 模拟网络状态
        network_status = {
            'status': 'stable',
            'latency': 50,
            'success_rate': 0.95
        }
        
        return api_ok(msg='增强标题生成成功！', data={
            'suggestions': suggestions_data,
            'product_info': {
                'name': base_name,
                'category': record.clazz if record.clazz else 1,
                'sku_count': len(sku_list)
            },
            'trending_keywords': trending_keywords,
            'network_status': network_status,
            'generation_method': 'simplified_template'
        })
        
    except Exception as e:
        traceback.print_exc()
        # 如果增强版失败，降级到标准版
        try:
            return generate_smart_title()
        except:
            return api_error(f'标题生成失败：{str(e)}')


@app.get('/api/trending_keywords/<int:category_id>')
def get_trending_keywords(category_id):
    """📈 获取指定类目的热门关键词 - 简化版本（已移除AI组件）"""
    try:
        limit = request.args.get('limit', 10, type=int)
        
        # 基础关键词模板
        basic_keywords = [
            "优质", "精选", "热销", "推荐", "新款", 
            "时尚", "舒适", "耐用", "实用", "经典",
            "高品质", "性价比", "畅销", "爆款", "限时"
        ]
        
        keywords_data = []
        for i, keyword in enumerate(basic_keywords[:limit]):
            keywords_data.append({
                'keyword': keyword,
                'trend_score': round(0.8 - i * 0.05, 3),  # 模拟趋势分数
                'search_volume': 1000 - i * 50,  # 模拟搜索量
                'platform': '综合平台',
                'related_keywords': [f"{keyword}商品", f"{keyword}推荐"],
                'timestamp': datetime.now().isoformat()
            })
        
        return api_ok(msg='关键词获取成功！', data={
            'keywords': keywords_data,
            'category_id': category_id,
            'total_count': len(keywords_data)
        })
        
    except Exception as e:
        traceback.print_exc()
        return api_error(f'获取关键词失败：{str(e)}')


@app.post('/api/refresh_trending_keywords')
def refresh_trending_keywords():
    """🔄 手动刷新热门关键词 - 简化版本（已移除AI组件）"""
    try:
        data = request.get_json()
        category_id = data.get('category_id', 1)
        
        # 异步模拟刷新
        
        def refresh_async():
            try:
                # 模拟刷新过程
                time.sleep(1)  # 模拟网络请求时间
                print(f"🔄 模拟刷新类目 {category_id} 的关键词完成")
                
            except Exception as e:
                print(f"模拟刷新关键词失败: {e}")
        
        refresh_thread = threading.Thread(target=refresh_async, daemon=True)
        refresh_thread.start()
        
        return api_ok(msg='关键词刷新已启动，请稍后查看最新数据')
        
    except Exception as e:
        traceback.print_exc()
        return api_error(f'刷新关键词失败：{str(e)}')


@app.get('/api/network_status')
def get_network_status():
    """🌐 获取网络状态信息(已精简)"""
    try:
        return api_ok(msg='网络状态功能已禁用', data={
            'network_status': 'unknown',
            'cache_size': 0,
            'endpoints': {}
        })
    except Exception as e:
        traceback.print_exc()
        return api_error(f'获取网络状态失败：{str(e)}')


# 🚀 智能价格计算API - 重新实现

@app.post('/api/pricing/calculate_smart_prices')
def calculate_smart_prices():
    """Runtime smart pricing with dynamic unit price."""
    try:
        data = request.get_json(silent=True) or {}
        record_id = data.get('record_id')

        if not record_id:
            return jsonify({'success': False, 'error': 'missing record_id'})

        try:
            unit_price = float(data.get('unit_price', 0) or 0)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'invalid unit_price'})

        if unit_price <= 0:
            return jsonify({'success': False, 'error': 'unit_price must be greater than 0'})

        try:
            profit_margin = float(data.get('profit_margin', 0) or 0)
        except (TypeError, ValueError):
            profit_margin = 0.0

        record = Record.get_or_none(Record.id == int(record_id))
        if not record:
            return jsonify({'success': False, 'error': 'record not found'})

        sku_list = json.loads(record.content) if record.content else []
        if not sku_list:
            return jsonify({'success': False, 'error': 'sku list is empty'})

        default_cost_items = [
            {'name': '??', 'cost_type': 'fixed', 'value': 3},
            {'name': '???', 'cost_type': 'fixed', 'value': 0.5},
            {'name': '????', 'cost_type': 'percentage', 'value': 5},
        ]
        default_pricing_config = {'target_gross_margin': 30}

        pricing_config = dict(default_pricing_config)
        cost_items = list(default_cost_items)

        if settings_manager is not None:
            try:
                user_settings = settings_manager.get_settings()
                if getattr(user_settings, 'pricing_config', None):
                    pricing_config = dict(user_settings.pricing_config)
                if getattr(user_settings, 'cost_items', None):
                    cost_items = list(user_settings.cost_items)
            except Exception as settings_error:
                print(f'failed to load pricing settings, using defaults: {settings_error}')

        if profit_margin > 0:
            pricing_config['target_gross_margin'] = profit_margin if profit_margin > 1 else profit_margin * 100

        from src.smart_pricing_engine import SmartPricingEngine

        config_file = get_runtime_data_path('pricing_config.json')
        engine = SmartPricingEngine(config_file)
        pricing_data = engine.calculate_runtime_pricing(
            sku_list=sku_list,
            unit_price=unit_price,
            pricing_config=pricing_config,
            cost_items=cost_items,
        )

        pricing_results = pricing_data.get('pricing_results', [])
        if not pricing_results:
            return jsonify({'success': False, 'error': 'no pricing results returned'})

        statistics = pricing_data.get('statistics', {})
        config_used = pricing_data.get('config_used', {})
        print(
            f"smart pricing finished: skus={statistics.get('total_skus', 0)}, "
            f"unit_price={unit_price:.2f}, avg_price={statistics.get('average_price', 0):.2f}, "
            f"avg_margin={statistics.get('average_margin', 0):.1f}%"
        )
        print(
            f"pricing config used: target_margin={config_used.get('target_gross_margin', 0)}%, "
            f"fixed={config_used.get('fixed_costs', 0)}, percentage={config_used.get('percentage_costs', 0)}%"
        )

        response_payload = {
            'success': True,
            'message': f"smart pricing finished for {len(pricing_results)} skus",
            'data': pricing_data
        }
        return app.response_class(
            response=json.dumps(response_payload, ensure_ascii=False, default=str),
            status=200,
            mimetype='application/json'
        )
    except Exception as e:
        print(f'smart pricing failed: {e}')
        traceback.print_exc()
        response_payload = {
            'success': False,
            'error': f'smart pricing failed: {str(e)}'
        }
        return app.response_class(
            response=json.dumps(response_payload, ensure_ascii=False, default=str),
            status=200,
            mimetype='application/json'
        )


@app.post('/api/generate_professional_title')
def generate_professional_title():
    """🏆 专业产品标题生成API (60字符无重复)"""
    try:
        data = request.get_json()
        record_id = data.get('record_id')
        
        if not record_id:
            return api_error('缺少产品ID参数')
        
        # 获取产品信息
        try:
            record = Record.get_by_id(record_id)
        except:
            return api_error('产品不存在')
        
        # 解析SKU列表
        sku_list = json.loads(record.content) if record.content else []
        
        # 构建产品信息对象
        product_info = ProfessionalProductInfo(
            name=sanitize_no_brand_title_text(record.name),
            category=record.clazz if record.clazz else 2,
            remark=record.remark if record.remark else "",
            sku_list=sku_list
        )
        
        # 调用专业标题生成器
        professional_generator = get_professional_generator()
        title_suggestions = professional_generator.generate_professional_titles(product_info)
        
        # 格式化响应数据
        suggestions_data = []
        for suggestion in title_suggestions:
            suggestions_data.append({
                'title': suggestion.title,
                'confidence': suggestion.confidence,
                'character_count': suggestion.character_count,
                'tags': suggestion.tags,
                'reasoning': suggestion.reasoning,
                'blue_ocean_words': suggestion.blue_ocean_words
            })
        
        return api_ok(msg=f"专业标题生成成功！生成了 {len(suggestions_data)} 个60字符标题", data={
            'suggestions': suggestions_data,
            'product_info': {
                'name': product_info.name,
                'category': product_info.category,
                'sku_count': len(product_info.sku_list)
            },
            'generation_method': 'professional_60_chars'
        })
        
    except Exception as e:
        app.logger.error(f"专业标题生成失败: {e}")
        return api_error(f'生成失败: {str(e)}')


DEFAULT_PRICING_TEMPLATE = '默认袜子模板'


def _load_pricing_config():
    """读取 pricing_config.json；文件不存在时返回 None，由调用方决定补默认结构还是报错。"""
    config_file = get_runtime_data_path('pricing_config.json')
    if not os.path.exists(config_file):
        return None
    with open(config_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_pricing_config(config):
    """打上 last_updated 时间戳后写回 pricing_config.json。"""
    config['last_updated'] = system_time.strftime('%Y-%m-%d %H:%M:%S', system_time.localtime())
    config_file = get_runtime_data_path('pricing_config.json')
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _pricing_cost_items(config):
    """取默认模板的成本项列表。"""
    return config.get('templates', {}).get(DEFAULT_PRICING_TEMPLATE, {}).get('base_cost_items', [])


@app.post('/api/pricing/cost-config')
def save_cost_config():
    """保存成本配置API - 增强版"""
    try:
        data = request.get_json()
        
        # 🔧 增强数据验证
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})
            
        if 'cost_items' not in data:
            return jsonify({'success': False, 'error': '缺少成本项目数据'})
            
        if 'target_profit_rate' not in data:
            return jsonify({'success': False, 'error': '缺少目标利润率数据'})
        
        cost_items = data['cost_items']
        target_profit_rate = data['target_profit_rate']
        
        # 🔧 验证成本项目数据
        if not isinstance(cost_items, list):
            return jsonify({'success': False, 'error': '成本项目数据格式错误'})
            
        # 🔧 修复：允许空的成本项目列表（用户可能删除了所有项目）
        print(f"💾 保存成本配置: {len(cost_items)}个项目, 利润率: {target_profit_rate*100:.1f}%")
        
        # 🔧 验证每个成本项目的数据完整性（仅在有项目时验证）
        for i, item in enumerate(cost_items):
            if not isinstance(item, dict):
                return jsonify({'success': False, 'error': f'成本项目{i+1}数据格式错误'})
                
            required_fields = ['name', 'cost_type', 'value', 'description']
            for field in required_fields:
                if field not in item:
                    return jsonify({'success': False, 'error': f'成本项目{i+1}缺少{field}字段'})
            
            # 验证数值类型
            if not isinstance(item['value'], (int, float)):
                return jsonify({'success': False, 'error': f'成本项目{i+1}的值必须是数字'})
                
            if item['value'] < 0:
                return jsonify({'success': False, 'error': f'成本项目{i+1}的值不能为负数'})
                
            # 验证成本类型
            if item['cost_type'] not in ['fixed', 'percentage', 'per_unit']:
                return jsonify({'success': False, 'error': f'成本项目{i+1}的类型无效'})
        
        # 🔧 验证利润率
        if not isinstance(target_profit_rate, (int, float)):
            return jsonify({'success': False, 'error': '目标利润率必须是数字'})
            
        if target_profit_rate < 0 or target_profit_rate > 1:
            return jsonify({'success': False, 'error': '目标利润率必须在0-100%之间'})
        
        # 保存到配置文件
        config_file = get_runtime_data_path('pricing_config.json')
        
        # 🔧 确保配置目录存在
        config_dir = os.path.dirname(config_file)
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
        
        # 读取现有配置
        existing_config = _load_pricing_config()
        if existing_config is None:
            # 如果配置文件不存在，创建一个新的空配置
            existing_config = {}

        # 更新成本配置
        if 'templates' not in existing_config:
            existing_config['templates'] = {}

        if DEFAULT_PRICING_TEMPLATE not in existing_config['templates']:
            existing_config['templates'][DEFAULT_PRICING_TEMPLATE] = {}

        existing_config['templates'][DEFAULT_PRICING_TEMPLATE]['base_cost_items'] = cost_items
        existing_config['templates'][DEFAULT_PRICING_TEMPLATE]['profit_margin'] = target_profit_rate
        
        # 🔧 修复：保存营销价格配置，使用正确的字段名
        if 'marketing_pricing' in data:
            marketing_config = data['marketing_pricing']
            
            # 验证营销配置
            if isinstance(marketing_config, dict):
                # 设置默认值并验证
                validated_marketing = {
                    'enabled': bool(marketing_config.get('enabled', True)),
                    'strategy': marketing_config.get('strategy', 'charm'),
                    'price_range': marketing_config.get('price_range', 'low'),
                    'show_savings': bool(marketing_config.get('show_savings', False)),
                    'competitor_analysis': bool(marketing_config.get('competitor_analysis', False))
                }
                
                # 验证策略值
                valid_strategies = ['charm', 'prestige', 'bundle', 'competitive', 'none']
                if validated_marketing['strategy'] not in valid_strategies:
                    validated_marketing['strategy'] = 'charm'
                
                # 验证价格区间
                valid_ranges = ['low', 'mid', 'high', 'premium']
                if validated_marketing['price_range'] not in valid_ranges:
                    validated_marketing['price_range'] = 'low'
                
                existing_config['templates'][DEFAULT_PRICING_TEMPLATE]['marketing_config'] = validated_marketing
                print(f"✅ 营销配置已保存: {validated_marketing}")

        # 🔧 添加保存时间戳并保存配置
        _save_pricing_config(existing_config)
        print(f"✅ 配置已保存到: {config_file}")

        # 🔧 验证保存是否成功
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
                saved_items = _pricing_cost_items(saved_config)
                if len(saved_items) != len(cost_items):
                    print(f"⚠️ 保存验证失败: 期望{len(cost_items)}个项目，实际保存{len(saved_items)}个")
                else:
                    print(f"✅ 保存验证成功: {len(saved_items)}个成本项目")
        except Exception as e:
            print(f"⚠️ 保存验证失败: {e}")
        
        return jsonify({
            'success': True,
            'message': f'成本配置保存成功，包含{len(cost_items)}个成本项目',
            'data': {
                'cost_items_count': len(cost_items),
                'profit_margin': target_profit_rate,
                'saved_at': existing_config.get('last_updated')
            }
        })
        
    except Exception as e:
        traceback.print_exc()
        error_msg = f'保存成本配置失败：{str(e)}'
        print(f"❌ {error_msg}")
        return jsonify({
            'success': False,
            'error': error_msg,
            'details': traceback.format_exc() if app.debug else None
        })


@app.post('/api/pricing/reload-config')
def force_reload_pricing_config():
    """配置刷新API（简化版）"""
    try:
        data = request.get_json() or {}
        operation = data.get('operation', 'manual_reload')
        
        app.logger.info(f"🔄 收到配置刷新请求: {operation}")
        
        # 🔧 简化：只返回成功状态，不强制重载
        return jsonify({
            'success': True,
            'message': '配置已刷新',
            'operation': operation,
            'reload_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
    except Exception as e:
        app.logger.error(f"❌ 配置刷新失败: {e}")
        return jsonify({
            'success': False,
            'error': f'配置刷新失败: {str(e)}'
        }), 500


@app.get('/api/pricing/config')
def get_pricing_config():
    """获取价格配置API"""
    try:
        config = _load_pricing_config()

        if config is None:
            # 返回默认配置
            config = {
                'templates': {
                    DEFAULT_PRICING_TEMPLATE: {
                        'base_cost_items': [
                            {
                                'name': '原材料',
                                'cost_type': 'fixed',
                                'value': 5.0,
                                'description': '每双袜子的原材料成本',
                                'is_active': True
                            },
                            {
                                'name': '人工费',
                                'cost_type': 'fixed',
                                'value': 2.0,
                                'description': '每双袜子的人工成本',
                                'is_active': True
                            },
                            {
                                'name': '包装费',
                                'cost_type': 'fixed',
                                'value': 0.5,
                                'description': '每双袜子的包装成本',
                                'is_active': True
                            },
                            {
                                'name': '运费',
                                'cost_type': 'fixed',
                                'value': 1.5,
                                'description': '每双袜子的运费成本',
                                'is_active': True
                            },
                            {
                                'name': '平台费',
                                'cost_type': 'percentage',
                                'value': 0.08,
                                'description': '平台收取的费用比例',
                                'is_active': True
                            },
                            {
                                'name': '推广费',
                                'cost_type': 'percentage',
                                'value': 0.05,
                                'description': '推广营销费用比例',
                                'is_active': True
                            }
                        ],
                        'profit_margin': 0.30
                    }
                }
            }
        
        return jsonify({
            'success': True,
            'data': config
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'获取价格配置失败：{str(e)}'
        })


# 🚀 新增：成本项目精细化管理API

@app.post('/api/pricing/cost-item')
def add_cost_item():
    """添加单个成本项目API"""
    try:
        data = request.get_json()
        
        # 验证必需字段
        required_fields = ['name', 'cost_type', 'value', 'description']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'缺少必需字段: {field}'})
        
        # 验证成本类型
        if data['cost_type'] not in ['fixed', 'percentage', 'per_unit', 'platform_fee']:
            return jsonify({'success': False, 'error': '无效的成本类型'})
        
        # 验证数值
        if not isinstance(data['value'], (int, float)) or data['value'] < 0:
            return jsonify({'success': False, 'error': '成本值必须是非负数'})
        
        # 读取现有配置
        existing_config = _load_pricing_config()
        if existing_config is None:
            existing_config = {}

        # 确保配置结构存在
        if 'templates' not in existing_config:
            existing_config['templates'] = {}
        if DEFAULT_PRICING_TEMPLATE not in existing_config['templates']:
            existing_config['templates'][DEFAULT_PRICING_TEMPLATE] = {'base_cost_items': []}

        # 检查是否已存在同名项目
        cost_items = existing_config['templates'][DEFAULT_PRICING_TEMPLATE].get('base_cost_items', [])
        for item in cost_items:
            if item['name'] == data['name']:
                return jsonify({'success': False, 'error': f'成本项目 "{data["name"]}" 已存在'})
        
        # 添加新项目
        new_item = {
            'name': data['name'],
            'cost_type': data['cost_type'],
            'value': data['value'],
            'description': data['description'],
            'is_active': data.get('is_active', True)
        }
        
        cost_items.append(new_item)
        existing_config['templates'][DEFAULT_PRICING_TEMPLATE]['base_cost_items'] = cost_items

        # 保存配置
        _save_pricing_config(existing_config)

        return jsonify({
            'success': True,
            'message': f'成本项目 "{data["name"]}" 添加成功',
            'data': new_item
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'添加成本项目失败: {str(e)}'
        })


@app.put('/api/pricing/cost-item/<item_name>')
def update_cost_item(item_name):
    """修改单个成本项目API"""
    try:
        data = request.get_json()
        
        # 读取现有配置
        existing_config = _load_pricing_config()
        if existing_config is None:
            return jsonify({'success': False, 'error': '配置文件不存在'})

        # 查找并更新项目
        cost_items = _pricing_cost_items(existing_config)
        item_found = False
        
        for item in cost_items:
            if item['name'] == item_name:
                # 更新字段
                if 'cost_type' in data:
                    if data['cost_type'] not in ['fixed', 'percentage', 'per_unit', 'platform_fee']:
                        return jsonify({'success': False, 'error': '无效的成本类型'})
                    item['cost_type'] = data['cost_type']
                
                if 'value' in data:
                    if not isinstance(data['value'], (int, float)) or data['value'] < 0:
                        return jsonify({'success': False, 'error': '成本值必须是非负数'})
                    item['value'] = data['value']
                
                if 'description' in data:
                    item['description'] = data['description']
                
                if 'is_active' in data:
                    item['is_active'] = bool(data['is_active'])
                
                item_found = True
                break
        
        if not item_found:
            return jsonify({'success': False, 'error': f'成本项目 "{item_name}" 不存在'})
        
        # 保存配置
        _save_pricing_config(existing_config)

        return jsonify({
            'success': True,
            'message': f'成本项目 "{item_name}" 更新成功'
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'更新成本项目失败: {str(e)}'
        })


@app.delete('/api/pricing/cost-item/<item_name>')
def delete_cost_item(item_name):
    """删除单个成本项目API"""
    try:
        # 读取现有配置
        existing_config = _load_pricing_config()
        if existing_config is None:
            return jsonify({'success': False, 'error': '配置文件不存在'})

        # 查找并删除项目
        cost_items = _pricing_cost_items(existing_config)
        original_count = len(cost_items)
        
        # 过滤掉要删除的项目
        cost_items = [item for item in cost_items if item['name'] != item_name]
        
        if len(cost_items) == original_count:
            return jsonify({'success': False, 'error': f'成本项目 "{item_name}" 不存在'})
        
        # 更新配置
        existing_config['templates'][DEFAULT_PRICING_TEMPLATE]['base_cost_items'] = cost_items

        # 保存配置
        _save_pricing_config(existing_config)

        return jsonify({
            'success': True,
            'message': f'成本项目 "{item_name}" 删除成功',
            'remaining_items': len(cost_items)
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'删除成本项目失败: {str(e)}'
        })


@app.get('/api/pricing/cost-items')
def get_cost_items():
    """获取成本项目列表API"""
    try:
        config = _load_pricing_config()

        if config is not None:
            cost_items = _pricing_cost_items(config)
        else:
            cost_items = []
        
        return jsonify({
            'success': True,
            'data': {
                'cost_items': cost_items,
                'total_count': len(cost_items),
                'active_count': len([item for item in cost_items if item.get('is_active', True)])
            }
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'获取成本项目列表失败: {str(e)}'
        })


# 🚀 新增：模板管理API

@app.get('/api/pricing/templates')
def get_pricing_templates():
    """获取所有价格模板API"""
    try:
        # 暂时返回空列表，等待重构
        templates_info = []
        
        return jsonify({
            'success': True,
            'data': {
                'templates': templates_info,
                'total_count': len(templates_info)
            }
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'获取模板列表失败: {str(e)}'
        })


# 🚀 新增：智能价格计算API

# 🚀 新增：AI配置管理API

@app.get('/api/ai/config')
def get_ai_config():
    """获取AI配置API"""
    return api_ok('外部 AI 已禁用', data={
        'ai_policy': dict(AI_POLICY),
        'providers': {
            'deepseek': {'enabled': False, 'api_key': '', 'model': '', 'priority': 1},
            'openai': {'enabled': False, 'api_key': '', 'model': '', 'priority': 2},
            'claude': {'enabled': False, 'api_key': '', 'model': '', 'priority': 3},
        }
    })


@app.post('/api/ai/config')
def save_ai_config():
    """保存AI配置API"""
    return api_ok('外部 AI 已禁用，配置未保存', data={
        'ai_policy': dict(AI_POLICY),
        'model_configs': [],
    })


@app.post('/api/ai/test')
def test_ai_connection():
    """测试发布优化 LLM 连接（仅小米/DeepSeek）。
    payload: {provider: {api_key, model, api_base?/base_url?}}；逐个真实调用一次短 prompt。"""
    try:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict) or not data:
            return api_error('未提供模型配置')
        results = {}
        for provider, cfg in data.items():
            if not isinstance(cfg, dict):
                continue
            p = str(provider).strip().lower()
            if p not in ALLOWED_PUBLISH_AI_PROVIDERS:
                results[provider] = {
                    'success': False,
                    'error': f'仅支持发布优化厂商 {", ".join(ALLOWED_PUBLISH_AI_PROVIDERS)}，不支持 {provider}',
                }
                continue
            preset = LLM_PROVIDER_PRESETS.get(p, {})
            base_url = str(cfg.get('base_url') or cfg.get('api_base') or preset.get('base_url') or '')
            preset_models = preset.get('models') or []
            model = str(cfg.get('model') or cfg.get('model_name') or '') or (preset_models[0] if preset_models else '')
            client = LLMClient(p, str(cfg.get('api_key') or ''), base_url, model)
            try:
                ok, detail = client.test_connection(timeout=20)
                if ok:
                    results[provider] = {'success': True, 'reply': detail, 'model': model}
                else:
                    results[provider] = {'success': False, 'error': detail}
            except LLMError as e:
                results[provider] = {'success': False, 'error': str(e)}
            except Exception as e:
                results[provider] = {'success': False, 'error': f'测试失败：{e}'}
        if not results:
            return api_error('未提供有效的模型配置')
        return api_ok('测试完成', data=results)
    except Exception as e:
        traceback.print_exc()
        return api_error(f'测试失败：{e}')


@app.post('/api/ai/models')
def list_ai_models():
    """获取某厂商可用模型列表（OpenAI 兼容 GET /models）。
    payload: {provider, api_key?, api_base?/base_url?}；未传密钥时回退已存配置。"""
    try:
        data = request.get_json(silent=True) or {}
        provider = str(data.get('provider') or '').strip().lower()
        if provider not in ALLOWED_PUBLISH_AI_PROVIDERS:
            return api_error(f'仅支持 {", ".join(ALLOWED_PUBLISH_AI_PROVIDERS)}')
        preset = LLM_PROVIDER_PRESETS.get(provider, {})
        api_key = str(data.get('api_key') or '').strip()
        base_url = str(data.get('base_url') or data.get('api_base') or preset.get('base_url') or '').strip()
        # 前端未带密钥（如只回传占位）时，回退到已保存配置
        if not api_key:
            for c in (settings_manager.get_settings().model_configs or []):
                if str(c.get('provider') or '').lower() == provider and c.get('api_key'):
                    api_key = c.get('api_key')
                    if not base_url:
                        base_url = c.get('base_url') or c.get('api_base') or ''
                    break
        client = LLMClient(provider, api_key, base_url, '')
        ok, result = client.list_models()
        if ok:
            return api_ok('获取成功', data={'models': result})
        return api_error(result)
    except Exception as e:
        traceback.print_exc()
        return api_error(f'获取模型失败：{e}')


# 🚀 新增：毛利率配置API

@app.post('/api/pricing/profit-margin-config')
def save_profit_margin_config():
    """保存毛利率配置API - 实时保存"""
    try:
        data = request.get_json()
        
        # 验证请求数据
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})
            
        if 'profit_margin' not in data:
            return jsonify({'success': False, 'error': '缺少毛利率数据'})
        
        profit_margin = data['profit_margin']
        
        # 验证毛利率值
        if not isinstance(profit_margin, (int, float)):
            return jsonify({'success': False, 'error': '毛利率必须是数字'})
            
        if profit_margin < 0 or profit_margin > 100:
            return jsonify({'success': False, 'error': '毛利率必须在0-100%之间'})
        
        # 转换为小数形式
        profit_margin_decimal = profit_margin / 100.0
        
        # 读取现有配置
        existing_config = _load_pricing_config()
        if existing_config is None:
            existing_config = {}

        # 确保配置结构存在
        if 'templates' not in existing_config:
            existing_config['templates'] = {}
        if DEFAULT_PRICING_TEMPLATE not in existing_config['templates']:
            existing_config['templates'][DEFAULT_PRICING_TEMPLATE] = {'base_cost_items': []}

        # 更新毛利率
        existing_config['templates'][DEFAULT_PRICING_TEMPLATE]['profit_margin'] = profit_margin_decimal

        # 保存配置
        _save_pricing_config(existing_config)

        app.logger.info(f"✅ 毛利率已实时保存: {profit_margin}%")
        
        return jsonify({
            'success': True,
            'message': f'毛利率已保存为 {profit_margin}%',
            'data': {
                'profit_margin': profit_margin,
                'profit_margin_decimal': profit_margin_decimal,
                'saved_at': existing_config.get('last_updated')
            }
        })
        
    except Exception as e:
        traceback.print_exc()
        error_msg = f'保存毛利率配置失败：{str(e)}'
        app.logger.error(error_msg)
        return jsonify({
            'success': False,
            'error': error_msg
        })

# ========== 商品链接采集 API ==========

# 全局任务存储
capture_tasks = {}

# DOM 采集互斥锁：同一时刻只允许一个采集任务在跑，避免共享 capture-browser-profile
# 时 Chrome 同一 user_data_dir 只能挂一个实例的并发冲突。
_capture_lock = threading.Lock()
# 标记当前是否有采集任务在运行（task_id 形式）；释放时清零
_capture_running_task_id: Optional[str] = None


def _capture_wait_seconds(env_name: str, default_seconds: int = 120) -> int:
    try:
        value = int(os.environ.get(env_name, str(default_seconds)))
    except (TypeError, ValueError):
        value = default_seconds
    return max(2, min(value, 600))


# mtop 产品数据缓存 (itemId → {title, price, skuList...})，供单品采集复用
_mtop_product_cache: dict = {}

# 浏览器 cookies 缓存，避免重复 CDP 请求
_browser_cookie_str: str = ''
_browser_cookie_ts: float = 0.0


def _capture_task_recovery_info(task: dict) -> dict:
    error_code = str((task or {}).get('error_code') or '')
    retryable_codes = {
        '1688_antibot_verification',
        'triggered_antibot_verification',
        'login_timeout',
    }
    action_hints = {
        '1688_antibot_verification': '请先在采集浏览器里完成 1688 访问验证，再点击重试采集。',
        'triggered_antibot_verification': '请先在浏览器里完成平台安全验证，再点击重试采集。',
        'login_timeout': '请先在浏览器里完成平台登录，再点击重试采集。',
    }
    return {
        'can_retry': bool(error_code in retryable_codes or (task or {}).get('status') == 'failed'),
        'user_action_required': error_code in retryable_codes,
        'action_hint': action_hints.get(error_code, ''),
    }


def _is_1688_capture_url(url: str) -> bool:
    return '1688.com' in (url or '').lower()


def _is_taobao_tmall_capture_url(url: str) -> bool:
    lower_url = (url or '').lower()
    return 'taobao.com' in lower_url or 'tmall.com' in lower_url


def _resolve_capture_redirect_url(url: str):
    normalized_url = normalize_capture_url(url)
    if not normalized_url:
        return '', ''
    if not is_taobao_short_link(normalized_url):
        return normalized_url, ''

    try:
        import requests
        response = requests.get(
            normalized_url,
            allow_redirects=True,
            timeout=8,
            stream=True,
            headers={
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                ),
            },
        )
        final_url = normalize_capture_url(response.url)
        response.close()
    except Exception as exc:
        raise ValueError(f'解析淘宝短链失败：{exc}。请打开短链后复制最终的淘宝/天猫商品链接再试') from exc

    final_host = capture_url_host(final_url)
    if not final_host.endswith(('.taobao.com', '.tmall.com')) and final_host not in {'taobao.com', 'tmall.com'}:
        raise ValueError(f'淘宝短链解析后的域名不受支持：{final_host or "未知域名"}')
    return final_url, normalized_url


def _is_1688_login_url(url: str) -> bool:
    """1688 平台自己的登录页。属于 1688 平台，与淘宝登录页是不同实体。"""
    lower = (url or '').lower()
    return 'login.1688.com' in lower or 'login.alibaba.com' in lower


def _is_taobao_login_url(url: str) -> bool:
    """淘宝/天猫平台的登录页（也是阿里"会员通"统一登录入口）。属于淘宝平台，与 1688 登录页是不同实体。"""
    lower = (url or '').lower()
    return 'login.taobao.com' in lower or 'login.tmall.com' in lower


def _detect_local_proxy_risk() -> str:
    """检测本地代理 / TUN 环境，返回面向用户的诊断+解决提示（无风险返回空串）。

    淘宝/1688 的二维码登录依赖阿里风控脚本（baxia.js）向风控服务器换取 token。
    若本地代理（Clash / Mihomo 等）开启 TUN 模式，会在网卡层接管全部流量、把阿里
    请求绕到海外节点，风控按"海外数据中心 IP"判高风险拒发 token，二维码框就永远空白；
    或规则集直接 REJECT 阿里域名（如 *.mmstat.com）。这两种情况都不是浏览器代码能
    单方面修复的（流量在系统网络层就被接管），只能引导用户调整代理。

    所有检测异常一律吞掉返回空串，绝不阻断采集主流程。
    """
    reasons = []
    # 1) Windows 系统代理开关
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            try:
                enable = winreg.QueryValueEx(key, "ProxyEnable")[0]
            except FileNotFoundError:
                enable = 0
            if enable:
                try:
                    server = winreg.QueryValueEx(key, "ProxyServer")[0]
                except FileNotFoundError:
                    server = ""
                reasons.append(f"系统代理开启({server or '未知地址'})")
    except Exception:
        pass
    # 2) 代理软件进程 + TUN 虚拟网卡
    try:
        import psutil
        names = ('clash', 'mihomo', 'verge', 'v2ray', 'xray', 'sing-box', 'trojan', 'shadowsocks')
        found = set()
        for p in psutil.process_iter(['name']):
            nm = (p.info.get('name') or '').lower()
            for k in names:
                if k in nm:
                    found.add('Clash/Mihomo' if k in ('clash', 'mihomo', 'verge') else k)
                    break
        if found:
            reasons.append("代理软件运行中(" + "、".join(sorted(found)) + ")")
        try:
            import socket as _sock
            stats = psutil.net_if_stats()
            addrs = psutil.net_if_addrs()
            tun_keys = ('meta', 'tun', 'tap', 'wintun', 'clash', 'mihomo', 'wireguard')
            for ifname, addr_list in addrs.items():
                low = ifname.lower()
                if not any(k in low for k in tun_keys):
                    continue
                # 关键：Windows 上 psutil 对 TUN 虚拟网卡的 isup 常误报 False，
                # 改用"是否分到 IPv4 地址"判断是否真正启用
                # （Clash/Mihomo TUN 默认 fake-ip 网关 198.18.x.x）。
                has_ipv4 = any(getattr(a, 'family', None) == _sock.AF_INET for a in addr_list)
                is_up = getattr(stats.get(ifname), 'isup', False)
                if has_ipv4 or is_up:
                    reasons.append(f"TUN 虚拟网卡启用({ifname})")
                    break
        except Exception:
            pass
    except Exception:
        pass

    if not reasons:
        return ""
    return (
        "⚠️ 检测到本地代理可能导致登录二维码空白：" + "；".join(reasons) + "。"
        "代理(尤其 TUN 模式)会把淘宝流量绕到海外节点，阿里风控因此拒发二维码。"
        "解决任选其一：① 在 Clash/代理软件中临时关闭 TUN 模式或系统代理后重试；"
        "② 在代理规则里把 *.taobao.com、*.tmall.com、*.alicdn.com、*.mmstat.com 设为直连(DIRECT)；"
        "③ 直接用登录页右侧的『账号密码登录』(不依赖二维码)。"
    )


def _is_taobao_tmall_product_url(url: str) -> bool:
    """判断淘宝/天猫商品详情链接，避免店铺页被当成单品页。"""
    from urllib.parse import urlparse

    lower_url = (url or '').strip().lower()
    if not _is_taobao_tmall_capture_url(lower_url):
        return False

    parsed = urlparse(lower_url if re.match(r'^https?://', lower_url) else f'https://{lower_url}')
    host = parsed.netloc
    path = parsed.path
    if 'item.taobao.com' in host and ('/item.htm' in path or '/item_' in path):
        return True
    if 'detail.tmall.com' in host and ('/item.htm' in path or '/item_' in path):
        return True
    if re.search(r'(^|\.)detail\.tmall\.', host) and '/item' in path:
        return True
    if re.search(r'(^|\.)item\.taobao\.', host) and '/item' in path:
        return True
    return False


def _is_taobao_tmall_store_url(url: str) -> bool:
    """判断淘宝/天猫店铺链接。商品详情页必须排除，否则会破坏现有单品采集。"""
    from urllib.parse import urlparse

    raw_url = (url or '').strip()
    lower_url = raw_url.lower()
    if not _is_taobao_tmall_capture_url(lower_url) or _is_taobao_tmall_product_url(lower_url):
        return False

    parsed = urlparse(lower_url if re.match(r'^https?://', lower_url) else f'https://{lower_url}')
    host = parsed.netloc
    path = parsed.path or '/'

    if 'tmall.com' in host:
        tmall_store_hosts = {'brand.tmall.com', 'store.tmall.com', 'chaoshi.tmall.com', 'temai.tmall.com'}
        if host in tmall_store_hosts or re.match(r'(^|\.)shop\d*\.tmall\.com$', host):
            return True
    if re.match(r'(^|\.)shop\d*\.taobao\.com$', host):
        return True
    if host in {'store.taobao.com', 'shop.taobao.com', 'shop.m.taobao.com'}:
        return True
    if path.endswith('/search.htm') or path.endswith('/category.htm') or 'view_shop' in path:
        return True
    return False


def _extract_taobao_tmall_item_id(url: str) -> str:
    from urllib.parse import parse_qs, urlparse

    raw_url = (url or '').strip()
    parsed = urlparse(raw_url if re.match(r'^https?://', raw_url) else f'https://{raw_url}')
    query = parse_qs(parsed.query)
    for key in ('id', 'item_id', 'itemId'):
        value = query.get(key)
        if value and str(value[0]).strip():
            return str(value[0]).strip()
    match = re.search(r'item[_/-](\d+)', raw_url, flags=re.IGNORECASE)
    return match.group(1) if match else ''


def _normalize_taobao_tmall_item_url(url: str) -> str:
    """归一化商品链接，保留商品 id，减少店铺翻页时的重复链接。"""
    from urllib.parse import parse_qs, urlparse

    raw_url = html.unescape(str(url or '')).strip()
    if not raw_url:
        return ''
    if raw_url.startswith('//'):
        raw_url = 'https:' + raw_url
    if raw_url.startswith('/'):
        return ''
    if not re.match(r'^https?://', raw_url, flags=re.IGNORECASE):
        raw_url = 'https://' + raw_url

    parsed = urlparse(raw_url)
    host = parsed.netloc.lower()
    path = parsed.path
    if 'taobao.com' not in host and 'tmall.com' not in host:
        return ''

    query = parse_qs(parsed.query)
    item_id = ''
    for key in ('id', 'item_id', 'itemId'):
        if query.get(key):
            item_id = str(query[key][0]).strip()
            break
    if not item_id:
        match = re.search(r'item[_/-](\d+)', raw_url, flags=re.IGNORECASE)
        item_id = match.group(1) if match else ''
    if not item_id:
        return ''

    if 'tmall.com' in host:
        return f'https://detail.tmall.com/item.htm?id={item_id}'
    return f'https://item.taobao.com/item.htm?id={item_id}'


def _extract_capture_product_id(url: str) -> str:
    url = (url or '').strip()
    patterns = [
        r'[?&]id=(\d+)',
        r'/offer/(\d+)\.html',
        r'/offer/(\d+)(?:[/?#]|$)',
        r'offerId=(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return f"product_{int(system_time.time())}"


def _parse_capture_price(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r'(\d+(?:\.\d+)?)', str(value))
    return float(match.group(1)) if match else 0.0


def _extract_capture_price_from_mapping(item, default: float = 0.0) -> float:
    """Extract a positive price from nested capture payloads."""
    if not isinstance(item, dict):
        return default

    preferred_keys = (
        'price',
        'discountPrice',
        'promotionPrice',
        'salePrice',
        'skuPrice',
        'consignPrice',
        'specQuotePrice',
        'priceWithTax',
        'currentPrice',
        'finalPrice',
    )

    disallowed_key_fragments = (
        'stock',
        'count',
        'quantity',
        'qty',
        'book',
        'inventory',
    )

    def _looks_like_price_key(key) -> bool:
        key_text = str(key or '').strip().lower()
        if not key_text:
            return False
        if key_text in {str(name).lower() for name in preferred_keys}:
            return True
        if any(fragment in key_text for fragment in disallowed_key_fragments):
            return False
        return 'price' in key_text

    for key in preferred_keys:
        price = _parse_capture_price(item.get(key))
        if price > 0:
            return price

    seen = set()

    def walk(value, depth: int = 0, allow_scalar: bool = False) -> float:
        if depth > 4 or value is None:
            return 0.0
        value_id = id(value)
        if value_id in seen:
            return 0.0
        seen.add(value_id)

        if isinstance(value, (int, float, str)):
            return _parse_capture_price(value) if allow_scalar else 0.0

        if isinstance(value, dict):
            for key in preferred_keys:
                price = _parse_capture_price(value.get(key))
                if price > 0:
                    return price
            for nested_key, nested_value in value.items():
                if _looks_like_price_key(nested_key):
                    price = walk(nested_value, depth + 1, allow_scalar=True)
                    if price > 0:
                        return price
            return 0.0

        if isinstance(value, (list, tuple)):
            for nested_value in value:
                if not isinstance(nested_value, (dict, list, tuple)):
                    continue
                price = walk(nested_value, depth + 1, allow_scalar=allow_scalar)
                if price > 0:
                    return price
        return 0.0

    nested_price = walk(item)
    return nested_price if nested_price > 0 else default


def _extract_1688_context_snapshot(page):
    """读取 1688 页面 window.context 提取完整商品数据。

    数据路径 (2026-05 验证):
      title       → globalModel.offerDetail.subject
      main_images → globalModel.offerDetail.mainImageList  (注意：对象数组 {fullPathImageURI, imageURI})
      all_images  → globalModel.offerDetail.imageList      (同样是对象数组)
      price       → globalModel.tradeModel.offerPriceModel.currentPrices[].price
      sku_props   → globalModel.offerDetail.skuProps
      sku_map     → globalModel.tradeModel.skuMap
      detail_url  → data.description.fields.detailUrl

    JS 侧负责把图片对象数组扁平化为 URL 字符串数组，避免上层代码 startswith('http') 在
    dict 上抛 AttributeError 并被 except 吃掉导致"未找到图片文件"。
    """
    return page.run_js(
        '''
        return (() => {
            const ctx = window.context || {};
            const data = ctx?.result?.data || {};
            const globalModel = ctx?.result?.global?.globalData?.model || {};
            const offerDetail = globalModel?.offerDetail || {};
            const tradeModel = globalModel?.tradeModel || {};

            // 把 mainImageList / imageList 的对象数组扁平化为 URL 字符串数组
            function pickImageUrl(item) {
                if (!item) return '';
                if (typeof item === 'string') return item;
                if (typeof item === 'object') {
                    // 优先级：完整 URL > 尺寸 URL > 相对路径
                    return item.fullPathImageURI
                        || item.imageURI
                        || item.size310x310ImageURI
                        || item.size220x220ImageURI
                        || item.searchImageURI
                        || item.summImageURI
                        || '';
                }
                return '';
            }
            function flattenImages(list) {
                if (!Array.isArray(list)) return [];
                const result = [];
                const seen = new Set();
                for (const item of list) {
                    const u = pickImageUrl(item);
                    if (u && !seen.has(u)) {
                        seen.add(u);
                        result.push(u);
                    }
                }
                return result;
            }

            const mainImages = flattenImages(offerDetail?.mainImageList);
            const allImages  = flattenImages(offerDetail?.imageList);
            // 价格
            const currentPrices = Array.isArray(tradeModel?.offerPriceModel?.currentPrices)
                ? tradeModel.offerPriceModel.currentPrices
                : [];
            // SKU 属性定义
            const skuProps = Array.isArray(offerDetail?.skuProps)
                ? offerDetail.skuProps
                : [];
            // SKU 价格映射
            const skuMap = Array.isArray(tradeModel?.skuMap)
                ? tradeModel.skuMap
                : [];
            // 详情图
            const detailUrl = (data?.description?.fields && data.description.fields.detailUrl)
                || offerDetail?.detailUrl
                || '';

            return {
                title: offerDetail?.subject || '',
                main_images: mainImages,
                offer_images: allImages,
                current_prices: currentPrices,
                price_display: tradeModel?.priceDisplay || '',
                sku_props: skuProps,
                sku_map: skuMap,
                detail_url: detailUrl,
                parameters: tradeModel?.offerIDatacenterSellInfo || {},
                offer_id: offerDetail?.offerId || tradeModel?.offerId || '',
            };
        })()
        '''
    ) or {}


def _is_1688_antibot_page(page) -> bool:
    """检测当前页是否为 1688 风控/验证页。

    避免对"正常商品页"误判为验证页：1688 商品页渲染过程中，body 文本或外层 HTML
    可能瞬时包含 "验证"/"punish" 等子串（埋点脚本、商家详情、压缩 JS 变量名），若据此
    判为验证页，任务会卡在 120s 验证等待循环，而实际页面完全正常。

    判定优先级：1) 已有 offerDetail.subject → 正常商品页，直接 False；
    2) 无商品上下文时再看强风控标记 + 验证关键词。真验证页会整页替换、offerDetail 不填充。
    红线：本函数只做"区分正常页 vs 真验证页"，不绕过任何真实风控/验证码。
    """
    try:
        marker = page.run_js(
            '''
            return (() => {
                const href = location.href || '';
                const html = document.documentElement?.outerHTML || '';
                const text = document.body?.innerText || '';
                // 1) 已有商品标题 → 正常商品页，绝不判为验证页（避免渲染过程瞬时误判）
                const od = window.context?.result?.global?.globalData?.model?.offerDetail;
                if (od && od.subject && String(od.subject).length > 0) return false;
                // 2) 强风控特征：收紧 bare 'punish'，避免误匹配压缩 JS 变量名
                if (/_____tmd_____|x5sec|sufei-punish|punishpage|baxia-punish/i.test(href + html)) {
                    return true;
                }
                // 3) 文本验证关键词：仅在无商品上下文时才采信，避免商品详情文本误命中
                return /验证码|安全验证|访问验证/.test(text);
            })()
            '''
        )
        return bool(marker)
    except Exception:
        return False


def _collect_1688_detail_images(detail_url: str):
    detail_url = (detail_url or '').strip()
    if not detail_url:
        return []

    try:
        import requests

        response = requests.get(
            detail_url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            },
            timeout=20
        )
        response.raise_for_status()
        detail_html = response.text
    except Exception:
        return []

    image_urls = []
    seen = set()
    for match in re.finditer(r'((?:https?:)?//[^"\'<>\s]+(?:alicdn|tbcdn)\.com[^"\'<>\s]+)', detail_html, flags=re.IGNORECASE):
        image_url = html.unescape(match.group(1) or '').replace('\\/', '/').strip().rstrip('\\')
        if image_url not in seen:
            seen.add(image_url)
            image_urls.append(image_url)
    return image_urls


def _build_1688_sku_info(snapshot: dict, clean_url_fn, default_price: float):
    sku_props = snapshot.get('sku_props') or []
    sku_map = snapshot.get('sku_map') or []
    prop_titles = []
    value_image_map = {}

    # clean_url_fn 允许为 None：调用方有时不需要 URL 清洗逻辑，给个 no-op fallback
    def _clean(u):
        u = (u or '').strip()
        if not u:
            return ''
        if callable(clean_url_fn):
            try:
                return clean_url_fn(u) or ''
            except Exception:
                pass
        # 内置回退清洗：补全协议
        if u.startswith('//'):
            return 'https:' + u
        if u.startswith('http'):
            return u
        return ''

    for prop in sku_props:
        prop_name = str(prop.get('prop') or prop.get('name') or '').strip()
        if prop_name:
            prop_titles.append(prop_name)
        for value in prop.get('value') or []:
            value_name = str(value.get('name') or '').strip()
            raw_image = value.get('imageUrl') or value.get('image') or value.get('imgUrl') or ''
            cleaned_image = _clean(raw_image)
            if value_name and cleaned_image:
                value_image_map[value_name] = cleaned_image

    sku_info = []
    if sku_map:
        for index, item in enumerate(sku_map, start=1):
            spec_attrs = html.unescape(str(item.get('specAttrs') or '')).replace('&gt;', '>')
            spec_parts = [part.strip() for part in spec_attrs.split('>') if part and part.strip()]
            name = ' / '.join(spec_parts) if spec_parts else f'SKU{index}'
            image_url = ''
            for part in spec_parts:
                if part in value_image_map:
                    image_url = value_image_map[part]
                    break

            price = _extract_capture_price_from_mapping(item, default_price)
            stock = item.get('canBookCount') or item.get('stock') or item.get('quantity')
            sku_info.append({
                'type': ' / '.join(prop_titles) if prop_titles else '规格',
                'name': name,
                'vid': str(item.get('skuId') or item.get('specId') or index),
                'image': image_url,
                'price': price,
                'stock': stock,
                'index': index,
            })

    if sku_info:
        return sku_info

    flattened_values = []
    for prop in sku_props:
        prop_name = str(prop.get('prop') or prop.get('name') or '').strip() or '规格'
        for value in prop.get('value') or []:
            value_name = str(value.get('name') or '').strip()
            if not value_name:
                continue
            flattened_values.append({
                'type': prop_name,
                'name': value_name,
                'image': value_image_map.get(value_name, ''),
            })

    for index, item in enumerate(flattened_values, start=1):
        sku_info.append({
            'type': item['type'],
            'name': item['name'],
            'vid': f'1688_{index}',
            'image': item['image'],
            'price': default_price,
            'index': index,
        })

    return sku_info


def _extract_1688_parameters(snapshot: dict):
    raw_parameters = snapshot.get('parameters') or {}
    parameters = []
    for key, value in raw_parameters.items():
        if key in {'sellPointModel'}:
            continue
        if isinstance(value, (str, int, float)) and str(value).strip():
            parameters.append({
                'name': str(key).strip(),
                'value': str(value).strip(),
            })
    return parameters


def _append_query_params(url: str, params: dict) -> str:
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: value for key, value in params.items() if value is not None})
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))



def _find_cdp_port() -> int:
    """扫描本地 CDP 调试端口。覆盖发布、调试和采集浏览器端口段。"""
    from urllib.request import urlopen as _urlopen
    for port in _protocol_cdp_port_candidates():
        try:
            _urlopen(f'http://127.0.0.1:{port}/json/version', timeout=0.2).read()
            return port
        except Exception:
            continue
    return None


def _cdp_get_cookies_and_token(cdp_port: int) -> tuple:
    """通过 CDP WebSocket 获取所有 cookies 和 mtop token。
    返回 (cookies_header, mtop_token)，失败返回 ('', '')。"""
    try:
        import websocket
        import time
        from urllib.request import urlopen as _urlopen

        targets = json.loads(_urlopen(f'http://127.0.0.1:{cdp_port}/json/list', timeout=3).read())
        target = next(
            (t for t in targets if t.get('type') == 'page' and 'taobao' in (t.get('url') or '').lower()),
            targets[0] if targets else None,
        )
        if not target:
            return '', ''

        ws = websocket.create_connection(target['webSocketDebuggerUrl'], timeout=5, suppress_origin=True)
        _msg_id = [0]

        def _cdp(method, params=None):
            _msg_id[0] += 1
            ws.send(json.dumps({'id': _msg_id[0], 'method': method, 'params': params or {}}))
            deadline = time.time() + 10
            while time.time() < deadline:
                raw = ws.recv()
                msg = json.loads(raw)
                if msg.get('id') == _msg_id[0]:
                    return msg
            raise TimeoutError(method)

        _cdp('Network.enable')
        r = _cdp('Network.getAllCookies')
        ws.close()

        all_cookies = (r.get('result') or {}).get('cookies') or []
        parts = []
        mtop_token = ''
        for c in all_cookies:
            domain = c.get('domain', '')
            if 'taobao.com' not in domain and 'tmall.com' not in domain:
                continue
            name = c.get('name', '')
            value = c.get('value', '')
            if name and value:
                parts.append(f'{name}={value}')
                if name == '_m_h5_tk':
                    mtop_token = value.split('_')[0]
        return '; '.join(parts), mtop_token
    except Exception as e:
        app.logger.warning(f"⚠️ CDP cookie 提取失败: {e}")
        return '', ''


def _mtop_post_fetch(cookies_header: str, mtop_token: str, shop_id: str, seller_id: str, page_no: int,
                     cat_id: int = 0, keyword: str = '', order_type: str = 'popular',
                     sort_type: str = '', filter_type: str = '') -> dict:
    """纯 HTTP POST 调用 mtop API，不经过浏览器。
    支持筛选参数: cat_id(类目), keyword(搜索), order_type(排序), sort_type, filter_type。"""
    import hashlib
    import time
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode

    app_key = '12574478'
    api = 'mtop.taobao.shop.simple.item.fetch'
    data_obj = {
        'shopId': shop_id, 'sellerId': seller_id,
        'page': str(page_no), 'pageSize': '30',
        'orderType': order_type, 'sortType': sort_type,
        'catId': cat_id, 'keyword': keyword, 'filterType': filter_type,
    }
    data_str = json.dumps(data_obj, separators=(',', ':'))
    ts = str(int(time.time() * 1000))
    sign = hashlib.md5(f'{mtop_token}&{ts}&{app_key}&{data_str}'.encode()).hexdigest()

    query = urlencode({
        'jsv': '2.6.2', 'appKey': app_key, 't': ts, 'sign': sign,
        'api': api, 'v': '1.0', 'type': 'originaljson', 'timeout': '10000',
        'dataType': 'json', 'antiCreep': 'true',
    })
    url = f'https://h5api.m.taobao.com/h5/{api}/1.0/?{query}'
    body = urlencode({'data': data_str}).encode('utf-8')
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': f'https://shop{shop_id}.taobao.com/',
        'Origin': f'https://shop{shop_id}.taobao.com',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Cookie': cookies_header,
    }

    with urlopen(Request(url, data=body, headers=headers, method='POST'), timeout=15) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _collect_store_products_via_mtop(page, max_products: int = 1000,
                                     cat_id: int = 0, keyword: str = '',
                                     order_type: str = 'popular', decode_price: bool = True) -> list:
    """纯协议采集：CDP 提取 token + Python MD5 签名 + 浏览器 fetch() 发送 mtop API。
    零 DOM 操作、零滚动、零导航。请求通过浏览器 TLS 指纹，不触发反爬。
    返回 [{itemId, title, image, price, soldCount, itemUrl, skuList, ...}, ...]"""

    # 1. 获取 shopId/sellerId
    try:
        info = page.run_js(r"""
            var gc = window.g_config || {};
            var seller = gc.seller || {};
            return {
                shopId: String(seller.shopId || ''),
                sellerId: String(seller.userId || seller.sellerId || ''),
            };
        """)
        if not info or not info.get('shopId'):
            system_time.sleep(5)
            info = page.run_js(r"""
                var gc = window.g_config || {};
                var seller = gc.seller || {};
                return {shopId: String(seller.shopId||''), sellerId: String(seller.userId||seller.sellerId||'')};
            """)
            if not info or not info.get('shopId'):
                return []
        shop_id = info['shopId']
        seller_id = info.get('sellerId', '')
    except Exception:
        return []

    # 2. CDP 提取 mtop token
    cdp_port = _find_cdp_port()
    if not cdp_port:
        system_time.sleep(5)
        cdp_port = _find_cdp_port()
    if not cdp_port:
        return []

    cookies_header, mtop_token = _cdp_get_cookies_and_token(cdp_port)
    if not mtop_token:
        return []

    app.logger.info("📡 纯协议: shopId=%s, token=%s...", shop_id, mtop_token[:8])

    # 3. Python 签名 + 浏览器 fetch() 分页
    import hashlib
    from urllib.parse import urlencode as _urlencode

    all_products = []
    seen_ids = set()
    page_no = 1
    consecutive_errors = 0
    app_key = '12574478'
    api_path = 'mtop.taobao.shop.simple.item.fetch'

    while page_no <= 50 and len(all_products) < max_products:
        data_obj = {'shopId': shop_id, 'sellerId': seller_id, 'page': str(page_no), 'pageSize': '30'}
        data_str = json.dumps(data_obj, separators=(',', ':'))
        ts = str(int(system_time.time() * 1000))
        sign = hashlib.md5((mtop_token + '&' + ts + '&' + app_key + '&' + data_str).encode()).hexdigest()

        query = _urlencode({
            'jsv': '2.6.2', 'appKey': app_key, 't': ts, 'sign': sign,
            'api': api_path, 'v': '1.0', 'type': 'originaljson',
            'timeout': '10000', 'dataType': 'json',
        })
        api_url = 'https://h5api.m.taobao.com/h5/' + api_path + '/1.0/?' + query + '&data=' + _urlencode({'data': data_str})[5:]

        # 浏览器 fetch() 发送（浏览器 TLS + 自动 Cookie）
        js_code = (
            'return (async function() {'
            'try {'
            'var resp = await fetch(' + json.dumps(api_url) + ', {credentials: "include"});'
            'var text = await resp.text();'
            'return text;'
            '} catch(e) {'
            'return "ERROR: " + (e.message || String(e));'
            '}'
            '})();'
        )
        result = page.run_js(js_code, timeout=20) or ''

        if not result or result.startswith('ERROR'):
            app.logger.warning("📡 page %d: %s", page_no, str(result)[:100])
            consecutive_errors += 1
            if consecutive_errors >= 3:
                break
            system_time.sleep(2)
            continue

        try:
            resp_data = json.loads(result)
        except json.JSONDecodeError:
            app.logger.warning("📡 page %d: JSON解析失败", page_no)
            consecutive_errors += 1
            if consecutive_errors >= 3:
                break
            continue

        ret = resp_data.get('ret', [])
        if 'SUCCESS' not in str(ret):
            app.logger.warning("📡 page %d: %s", page_no, str(ret)[:80])
            consecutive_errors += 1
            if consecutive_errors >= 3:
                break
            if 'TOKEN' in str(ret) or 'ILLEGAL' in str(ret) or 'RGV587' in str(ret):
                cookies_header, mtop_token = _cdp_get_cookies_and_token(cdp_port)
                if not mtop_token:
                    break
            system_time.sleep(1)
            continue

        consecutive_errors = 0
        data = resp_data.get('data', {})
        items = data.get('data', [])
        total = data.get('totalCnt', 0)
        has_next = data.get('hasNext', False)
        new_count = 0

        for item in items:
            item_id = str(item.get('itemId', ''))
            if item_id and item_id not in seen_ids:
                seen_ids.add(item_id)
                sku_list = []
                for sku in (item.get('skuInfoList') or []):
                    sku_list.append({
                        'skuId': str(sku.get('skuId', '')),
                        'skuImageUrl': sku.get('skuImageUrl', ''),
                        'skuUrl': sku.get('itemSkuUrl', ''),
                        'skuText': sku.get('skuPropertyText', ''),
                    })
                all_products.append({
                    'itemId': item_id,
                    'title': item.get('title', ''),
                    'image': item.get('image', ''),
                    'price': item.get('discountPrice', ''),
                    'priceEncoded': item.get('priceEncoded', True),
                    'soldCount': item.get('vagueSold365', ''),
                    'itemUrl': item.get('itemUrl', ''),
                    'skuList': sku_list,
                    'icons': item.get('itemIconUrlList') or [],
                    'benefits': item.get('benefitPointList') or [],
                })
                new_count += 1

        app.logger.info("📡 page %d: +%d, 累计 %d/%d", page_no, new_count, len(all_products), total)

        if not has_next or not items:
            break
        page_no += 1
        system_time.sleep(0.3)

    app.logger.info("📡 纯协议完成: %d 个商品", len(all_products))

    for p in all_products:
        iid = str(p.get('itemId', ''))
        if iid:
            _mtop_product_cache[iid] = p

    return all_products[:max_products]

def _collect_taobao_tmall_store_product_urls(page, store_url: str, max_products: int = 1000, max_pages: int = 50) -> list:
    """从店铺页面收集商品详情链接。
    优先级: 1) mtop 纯协议 (不碰 DOM)  2) 传统 <a href> 兜底。"""
    product_urls = []
    seen_ids = set()
    store_url_norm = store_url if re.match(r'^https?://', store_url) else f'https://{store_url}'

    # ---------- 第一阶段: mtop 纯协议采集 (不碰 DOM) ----------
    # 检查是否已在店铺页（调用方已导航），避免冗余刷新
    current_url = (page.url or '').strip()
    if 'taobao.com' not in current_url and 'tmall.com' not in current_url:
        try:
            app.logger.info("📡 导航到店铺页...")
            page.get(store_url_norm, timeout=25)
            system_time.sleep(5)
        except Exception as nav_err:
            app.logger.warning(f"⚠️ 店铺页访问失败: {nav_err}")
    else:
        app.logger.info(f"📡 已在店铺页，跳过重复导航: {current_url[:80]}")

    mtop_products = _collect_store_products_via_mtop(page, max_products=max_products)
    if mtop_products:
        from urllib.parse import urlparse
        parsed = urlparse(store_url_norm)
        host = parsed.netloc or ''
        is_tmall = 'tmall.com' in host
        detail_host = 'detail.tmall.com' if is_tmall else 'item.taobao.com'
        for item in mtop_products:
            item_id = str(item.get('itemId', ''))
            if not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            raw_item_url = str(item.get('itemUrl', '') or '').strip()
            if raw_item_url:
                if raw_item_url.startswith('//'):
                    raw_item_url = 'https:' + raw_item_url
                elif not raw_item_url.startswith('http'):
                    raw_item_url = 'https://' + raw_item_url
                product_urls.append(raw_item_url)
            else:
                product_urls.append(f'https://{detail_host}/item.htm?id={item_id}')
            if len(product_urls) >= max_products:
                break
        app.logger.info(f"📡 mtop 协议采集完成，共 {len(product_urls)} 个商品链接")
        return product_urls

    # mtop 未获取到数据时，直接返回空列表（新版店铺无传统 <a href>）
    app.logger.warning("mtop 未获取到数据，请确保已登录淘宝且页面加载完整")
    return product_urls


def _extract_text_by_selectors(page, selectors: list) -> str:
    selector_script = json.dumps(selectors, ensure_ascii=False)
    try:
        return str(page.run_js(f'''
            var selectors = {selector_script};
            for (var i = 0; i < selectors.length; i++) {{
                var node = document.querySelector(selectors[i]);
                var text = node ? (node.textContent || node.innerText || '') : '';
                if (text && text.trim()) return text.trim();
            }}
            return '';
        ''') or '').strip()
    except Exception:
        return ''


def _extract_taobao_ice_data(page) -> dict:
    """协议级淘宝/天猫商品提取 — 从 __ICE_APP_CONTEXT__ 直接读取 SSR JSON。
    不依赖 CSS 选择器，不受页面 DOM 结构变化影响。

    数据路径:
      title     → res.item.title
      images    → res.item.images
      price     → res.skuCore.sku2info["0"].price.priceMoney (分)
      sku_base  → res.skuBase.skus + res.skuBase.props
      sku_core  → res.skuCore.sku2info (价格+库存)
      detail    → res.item.pcADescUrl (需二次请求获取HTML)
      params    → res.params.trackParams
    """
    result = page.run_js(r'''
        return (function() {
            var ice = window.__ICE_APP_CONTEXT__ || {};
            var home = ((ice.loaderData || {}).home || {}).data;
            if (!home) return JSON.stringify({error: 'no_ice_data'});
            var res = home.res || {};
            var item = res.item || {};
            var skuCore = res.skuCore || {};
            var skuBase = res.skuBase || {};

            var data = {};

            // 标题
            data.title = item.title || '';

            // 主图
            data.images = (item.images || []).slice(0, 12);

            // 价格 (从默认 SKU)
            var defaultSkuInfo = (skuCore.sku2info || {})['0'] || {};
            var priceMoney = ((defaultSkuInfo.price || {}).priceMoney) || '0';
            data.price = parseInt(priceMoney, 10) || 0;  // 分

            // SKU 列表
            var skus = skuBase.skus || [];
            var props = skuBase.props || [];
            var sku2info = skuCore.sku2info || {};

            // 构建 propId → propName 映射
            var propMap = {};
            (props || []).forEach(function(p) {
                var values = p.values || [];
                propMap[String(p.pid || '')] = {name: p.name || '', values: values};
            });

            // 属性值图片映射：vid → 图片URL。
            // 天猫 ICE 结构里颜色等属性值自带色卡图（image/imageUrl/img/imgUrl），
            // 每个 SKU 通过 propPath 里的 vid 取回自己的色卡图，保证 SKU 图与颜色身份一致。
            var vidImageMap = {};
            (props || []).forEach(function(p) {
                (p.values || []).forEach(function(v) {
                    var img = v.image || v.imageUrl || v.img || v.imgUrl || '';
                    img = String(img || '').trim();
                    if (img && img.indexOf('//') === 0) img = 'https:' + img;
                    if (img) vidImageMap[String(v.vid || '')] = img;
                });
            });

            // 构建 SKU 信息列表
            data.skuList = [];
            var seenNames = {};

            (skus || []).forEach(function(sku) {
                var propPath = sku.propPath || '';
                var skuId = sku.skuId || '';
                var info = sku2info[skuId] || {};

                // 解析 propPath 获取属性名称
                var parts = propPath.split(';');
                var nameParts = [];
                parts.forEach(function(part) {
                    if (!part) return;
                    var kv = part.split(':');
                    var pid = kv[0], vid = kv[1];
                    var prop = propMap[pid];
                    if (prop) {
                        var valObj = (prop.values || []).filter(function(v) { return String(v.vid || '') === vid; })[0];
                        nameParts.push(valObj ? valObj.name : vid);
                    }
                });

                var skuName = nameParts.join('+') || '默认';
                var skuPrice = ((info.price || {}).priceMoney) || priceMoney;
                // 从 propPath 的 vid 反查色卡图（取第一个有图的属性值，通常是颜色）
                var skuImage = '';
                for (var pi = 0; pi < parts.length; pi++) {
                    if (!parts[pi]) continue;
                    var vid2 = parts[pi].split(':')[1];
                    if (vid2 && vidImageMap[vid2]) { skuImage = vidImageMap[vid2]; break; }
                }

                // 去重
                if (seenNames[skuName]) return;
                seenNames[skuName] = true;

                data.skuList.push({
                    skuId: skuId,
                    name: skuName,
                    price: parseInt(skuPrice, 10) || 0,
                    image: skuImage,
                    quantity: parseInt(info.quantity || '0', 10) || 0
                });
            });

            // 如果没有解析到 SKU，创建默认条目
            if (!data.skuList.length) {
                data.skuList.push({
                    skuId: '0',
                    name: '默认',
                    price: data.price,
                    image: '',
                    quantity: 0
                });
            }

            // 详情图 URL (需二次请求)
            data.pcDescUrl = item.pcADescUrl || item.pcDescUrl || '';

            // 属性参数
            data.params = res.params || {};

            return JSON.stringify(data);
        })()
    ''')

    product_data = {
        'title': '',
        'price': {'current': 0, 'original': None, 'currency': 'CNY'},
        'main_images': [],
        'detail_images': [],
        'sku_info': [],
        'parameters': [],
    }

    try:
        ice_data = json.loads(result) if isinstance(result, str) else (result or {})

        if ice_data.get('error'):
            app.logger.warning(f"ICE提取失败: {ice_data['error']}")
            return None  # 返回 None 让调用者回退到 DOM

        product_data['title'] = str(ice_data.get('title') or '').strip()
        if ice_data.get('price'):
            product_data['price']['current'] = float(ice_data['price']) / 100.0

        product_data['main_images'] = [
            u if u.startswith('http') else ('https:' + u)
            for u in (ice_data.get('images') or [])
        ]

        for sku in ice_data.get('skuList') or []:
            product_data['sku_info'].append({
                'type': '规格',
                'name': str(sku.get('name') or '默认').strip(),
                'image': str(sku.get('image') or '').strip(),
                'price': float(sku.get('price', 0)) / 100.0 if sku.get('price') else product_data['price']['current'],
                'index': len(product_data['sku_info']) + 1,
            })

        if not product_data['sku_info']:
            product_data['sku_info'].append({
                'type': '规格', 'name': '默认', 'image': '',
                'price': product_data['price']['current'], 'index': 1,
            })

        # 参数
        params = ice_data.get('params') or {}
        product_data['parameters'] = [
            {'name': str(k), 'value': str(v)}
            for k, v in (params.get('trackParams') or {}).items()
        ]

        # 详情图 URL (需要二次请求 desc 页面提取图片)
        pc_desc_url = ice_data.get('pcDescUrl', '')
        if pc_desc_url and not pc_desc_url.startswith('http'):
            pc_desc_url = 'https:' + pc_desc_url

        if pc_desc_url and product_data['title']:
            product_data['_pc_desc_url'] = pc_desc_url

        app.logger.info(
            f"ICE提取成功: title={bool(product_data['title'])} "
            f"price={product_data['price']['current']} "
            f"images={len(product_data['main_images'])} "
            f"skus={len(product_data['sku_info'])}"
        )
        return product_data

    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        app.logger.warning(f"ICE数据解析失败: {e}")
        return None


def _collect_taobao_desc_images_via_browser(page, max_images: int = 80) -> list:
    """在当前商品页内分段滚动，触发宝贝描述懒加载后从 DOM 收集详情图。

    背景：天猫/淘宝详情描述是纯 JS 渲染 + 懒加载，pcDescUrl 的裸 HTML 里只有
    <script> 标签，HTTP 抓取拿不到图（2026-08 实证）。采集流程的页面会话是有效的，
    直接在页内滚动等描述模块渲染完毕再收图即可。

    只返回阿里 CDN 的真图片 URL（带图片扩展名），调用方负责去重/下载。
    """
    import re as _re

    # 分段滚动到底部，触发描述区懒加载
    try:
        page.run_js('window.scrollTo(0, 0)')
        for _ in range(16):
            page.run_js('window.scrollBy(0, 900)')
            system_time.sleep(0.6)
        page.run_js('window.scrollTo(0, document.body.scrollHeight)')
        system_time.sleep(1.5)
    except Exception as e:
        app.logger.warning(f"详情图滚动加载异常: {e}")

    collected = page.run_js(r'''
        var urls = [];
        var sels = [
            '#description img',
            '#container .descV8-singleImage img',
            '#container .descV8-container img',
            '.detail-content img',
            '.desc-root img',
            '[class*="descV8"] img',
            '[class*="detailDesc"] img',
            '[class*="detail-desc"] img'
        ];
        sels.forEach(function (s) {
            document.querySelectorAll(s).forEach(function (im) {
                var u = im.getAttribute('data-src') || im.getAttribute('data-ks-lazyload') || im.getAttribute('src') || '';
                if (!u) return;
                u = String(u).trim();
                if (u.indexOf('//') === 0) u = 'https:' + u;
                urls.push(u);
            });
        });
        return urls;
    ''') or []

    result = []
    for u in collected:
        if 'alicdn.com' not in u and 'taobaocdn' not in u:
            continue
        if 's.gif' in u or 'placeholder' in u.lower():
            continue
        if not _re.search(r'\.(?:jpg|jpeg|png|webp)(?:[_.?#]|$)', u, _re.IGNORECASE):
            continue
        if u not in result:
            result.append(u)
        if len(result) >= max_images:
            break

    # 回滚到顶部，避免影响后续 DOM 兜底提取的视口判断
    try:
        page.run_js('window.scrollTo(0, 0)')
    except Exception:
        pass
    return result


def _fetch_taobao_desc_images(page, pc_desc_url: str) -> list:
    """从淘宝 PC 详情页 URL 提取详情图列表（二次HTTP请求）。"""
    import requests as _requests
    try:
        if not pc_desc_url.startswith('http'):
            pc_desc_url = 'https:' + pc_desc_url
        resp = _requests.get(pc_desc_url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120',
            'Referer': 'https://item.taobao.com/',
        })
        html = resp.text
        # 详情页的图片通常在 <img> 标签或 JSON 数据中
        import re as _re
        img_urls = _re.findall(r'(?:src|data-src)=["\']([^"\']*(?:alicdn|taobaocdn|gw\.alicdn)[^"\']*)["\']', html)
        # 补充 JSON 内嵌图片 URL（desc 页常把图放在 "url":"//..." 这类字段里）
        img_urls += _re.findall(r'"((?:https?:)?//[^"\']*(?:alicdn|taobaocdn)[^"\']*)"', html)
        result = []
        for u in img_urls[:120]:
            u = u.strip()
            if not u or 's.gif' in u or 'placeholder' in u.lower():
                continue
            # 只保留真图片：路径必须带图片扩展名（允许 _尺寸/_裁剪 等 CDN 后缀）。
            # 否则 <script src="https://g.alicdn.com/....js"> 会被误当详情图下载，
            # 存成 .jpg 后内容是 JS（现场实证：详情_001.jpg 文件头是 !function...）。
            if not _re.search(r'\.(?:jpg|jpeg|png|webp)(?:[_.?#]|$)', u, _re.IGNORECASE):
                continue
            if not u.startswith('http'):
                u = 'https:' + u
            if u not in result:
                result.append(u)
        return result
    except Exception as e:
        app.logger.warning(f"详情图提取失败: {e}")
        return []


def _extract_taobao_tmall_product_snapshot(page, product_url: str) -> dict:
    product_id = _extract_capture_product_id(product_url)
    product_data = {
        'product_id': product_id,
        'title': '',
        'price': {'current': 0, 'original': None, 'currency': 'CNY'},
        'main_images': [],
        'detail_images': [],
        'sku_info': [],
        'parameters': [],
    }

    # 优先从 mtop 缓存获取已采集数据（避免重复 DOM 提取）
    cached = _mtop_product_cache.get(product_id) if product_id else None
    if cached:
        # 标题
        if cached.get('title'):
            product_data['title'] = str(cached['title'])
        # 价格（优先使用解码后的价格）
        decoded_price = cached.get('priceDecoded')
        if decoded_price:
            try:
                product_data['price']['current'] = float(int(str(decoded_price)) / 100)
            except (ValueError, TypeError):
                pass
        # SKU 信息
        sku_list = cached.get('skuList') or []
        if sku_list:
            product_data['sku_info'] = [
                {
                    'sku_id': str(s.get('skuId', '')),
                    'name': str(s.get('skuText', '')),
                    'image': str(s.get('skuImageUrl', '')),
                }
                for s in sku_list
            ]
        # 主图（mtop 返回首图，作为兜底）
        if cached.get('image'):
            product_data['main_images'] = [str(cached['image'])]

    product_data['title'] = _extract_text_by_selectors(page, [
        '.mainTitle--R75fTcZL',
        '[class*="mainTitle"]',
        '[class*="Title--"]',
        'h1',
    ]) or '未能获取标题'

    price_value = page.run_js(r'''
        function parsePriceText(raw) {
            if (raw === null || raw === undefined) return 0;
            var match = String(raw).replace(/[,，]/g, '').match(/(\d+(?:\.\d+)?)/);
            return match ? parseFloat(match[1]) : 0;
        }
        var selectors = [
            '.highlightPrice--asfw5V1e',
            '.tb-rmb-num',
            '[class*="highlightPrice"]',
            '[class*="priceText"]',
            '[class*="PriceText"]',
            '[class*="salesPrice"]',
            '[class*="mainPrice"]',
            '[class*="price--"]',
            '[class*="Price--"]',
            '[data-testid*="price"]',
            '.price-value',
            '.tb-property-cont .price'
        ];
        for (var i = 0; i < selectors.length; i++) {
            var node = document.querySelector(selectors[i]);
            var price = parsePriceText(node ? (node.textContent || node.innerText || '') : '');
            if (price > 0) return price;
        }
        return 0;
    ''')
    if price_value:
        product_data['price']['current'] = float(price_value)

    image_payload = page.run_js(r'''
        function cleanList(values) {
            var result = [];
            values.forEach(function(value) {
                if (!value) return;
                value = String(value).trim();
                if (!value || value.indexOf('s.gif') !== -1 || value.indexOf('O1CN01CYtPWu1MUBqQAUK9D') !== -1) return;
                if (value.indexOf('//') === 0) value = 'https:' + value;
                if (value.indexOf('alicdn.com') === -1 && value.indexOf('alicdn.net') === -1) return;
                if (result.indexOf(value) === -1) result.push(value);
            });
            return result;
        }
        function srcOf(img) {
            return img.getAttribute('data-src') || img.getAttribute('src') || img.getAttribute('data-ks-lazyload') || '';
        }
        var main = [];
        [
            '.thumbnailPic--QasTmWDm',
            '.thumbnailWrap--TikzqD8l img',
            '.thumbnailList--T63jJ6eM img',
            '[class*="thumbnail"] img',
            '[class*="PicGallery"] img'
        ].forEach(function(selector) {
            document.querySelectorAll(selector).forEach(function(img) { main.push(srcOf(img)); });
        });
        if (!main.length) {
            document.querySelectorAll('img').forEach(function(img) {
                var rect = img.getBoundingClientRect();
                if (rect.width >= 80 && rect.height >= 80 && rect.top < 900) main.push(srcOf(img));
            });
        }
        var detail = [];
        [
            '#container .descV8-singleImage img',
            '#container .descV8-container img',
            '#description img',
            '.detail-content img',
            '.desc-root img',
            '[class*="desc"] img',
            '[class*="detail"] img'
        ].forEach(function(selector) {
            document.querySelectorAll(selector).forEach(function(img) { detail.push(srcOf(img)); });
        });
        return { main: cleanList(main).slice(0, 12), detail: cleanList(detail).slice(0, 80) };
    ''') or {}

    product_data['main_images'] = image_payload.get('main') or []
    product_data['detail_images'] = [url for url in (image_payload.get('detail') or []) if url not in product_data['main_images']]

    sku_data_list = page.run_js(r'''
        function parsePriceText(raw) {
            if (raw === null || raw === undefined) return 0;
            var match = String(raw).replace(/[,，]/g, '').match(/(\d+(?:\.\d+)?)/);
            return match ? parseFloat(match[1]) : 0;
        }
        function defaultPrice() {
            var selectors = ['.highlightPrice--asfw5V1e', '.tb-rmb-num', '[class*="priceText"]', '[class*="PriceText"]', '[class*="price--"]'];
            for (var i = 0; i < selectors.length; i++) {
                var node = document.querySelector(selectors[i]);
                var price = parsePriceText(node ? (node.textContent || node.innerText || '') : '');
                if (price > 0) return price;
            }
            return 0;
        }
        function srcOf(node) {
            var img = node ? node.querySelector('img, [style*="background"]') : null;
            if (!img) return '';
            var src = img.getAttribute('data-src') || img.getAttribute('src') || img.getAttribute('data-ks-lazyload') || '';
            if (!src) {
                var style = img.getAttribute('style') || '';
                var match = style.match(/url\(["']?([^"')]+)["']?\)/);
                src = match ? match[1] : '';
            }
            if (src && src.indexOf('//') === 0) src = 'https:' + src;
            return src || '';
        }
        var result = [];
        var price = defaultPrice();
        var skuItems = document.querySelectorAll('#skuOptionsArea .skuItem--Z2AJB9Ew, #skuOptionsArea [class*="skuItem"], [class*="skuWrapper"] [class*="skuItem"]');
        skuItems.forEach(function(skuItem) {
            var titleNode = skuItem.querySelector('.ItemLabel--psS1SOyC span, [class*="ItemLabel"] span, [class*="label"]');
            var typeName = titleNode ? (titleNode.textContent || '').trim() : '规格';
            var values = skuItem.querySelectorAll('.valueItem--smR4pNt4, [class*="valueItem"], li, button');
            values.forEach(function(valueNode) {
                var nameNode = valueNode.querySelector('span[title], [title], span') || valueNode;
                var name = (nameNode.getAttribute && nameNode.getAttribute('title')) || (nameNode.textContent || '').trim();
                if (!name || name.length > 80) return;
                result.push({
                    type: typeName || '规格',
                    name: name,
                    image: srcOf(valueNode),
                    price: price,
                    index: result.length + 1
                });
            });
        });
        return result;
    ''') or []

    for index, sku in enumerate(sku_data_list, start=1):
        name = str((sku or {}).get('name') or '').strip()
        if not name:
            continue
        image = str((sku or {}).get('image') or '').strip()
        product_data['sku_info'].append({
            'type': str((sku or {}).get('type') or '规格').strip() or '规格',
            'name': name,
            'image': image,
            'price': float((sku or {}).get('price') or product_data['price']['current'] or 0),
            'index': index,
        })

    if not product_data['sku_info'] and product_data['main_images']:
        product_data['sku_info'].append({
            'type': '规格',
            'name': '默认',
            'image': product_data['main_images'][0],
            'price': product_data['price']['current'],
            'index': 1,
        })

    return product_data


def _infer_capture_image_ext(url: str, content_type: str = '') -> str:
    lower_type = (content_type or '').lower()
    lower_url = (url or '').lower()
    if 'image/png' in lower_type or '.png' in lower_url:
        return '.png'
    if 'image/gif' in lower_type or '.gif' in lower_url:
        return '.gif'
    if 'image/webp' in lower_type or '.webp' in lower_url:
        return '.webp'
    return '.jpg'


def _download_capture_product_images(product_data: dict, product_url: str, options: dict) -> str:
    import requests
    from concurrent.futures import ThreadPoolExecutor, as_completed

    base_save_path = normalize_save_path((options or {}).get('save_path', 'uploads/products'))
    product_id = product_data.get('product_id') or _extract_capture_product_id(product_url)
    parent_dir = os.path.join(base_save_path, f'ID-{product_id}')
    main_img_dir = os.path.join(parent_dir, '主图')
    sku_img_dir = os.path.join(parent_dir, 'SKU')
    detail_img_dir = os.path.join(parent_dir, '详情页')
    os.makedirs(main_img_dir, exist_ok=True)
    os.makedirs(sku_img_dir, exist_ok=True)
    os.makedirs(detail_img_dir, exist_ok=True)

    # 重复采集同一商品时先清空旧文件，避免上一次失败/旧版逻辑留下的脏文件
    # （如把 JS 存成的 .jpg）混入本次结果
    for _dir in (main_img_dir, sku_img_dir, detail_img_dir):
        for _name in os.listdir(_dir):
            _fp = os.path.join(_dir, _name)
            if os.path.isfile(_fp):
                try:
                    os.remove(_fp)
                except OSError:
                    pass

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': product_url,
    })

    def _looks_like_image(content: bytes) -> bool:
        """校验下载内容确实是图片（魔数检查），防止把防盗链返回的 JS/HTML 挑战页存成 .jpg。"""
        if not content or len(content) < 12:
            return False
        if content.startswith(b'RIFF'):
            return content[8:12] == b'WEBP'
        return content.startswith((b'\xff\xd8\xff', b'\x89PNG', b'GIF8', b'BM'))

    def download_image(img_url, filepath):
        try:
            if not img_url:
                return False
            if img_url.startswith('//'):
                img_url = 'https:' + img_url
            response = session.get(img_url, timeout=15)
            if response.status_code != 200 or len(response.content) < 100:
                return False
            if not _looks_like_image(response.content):
                return False
            with open(filepath, 'wb') as f:
                f.write(response.content)
            return True
        except Exception:
            return False

    import re as _re

    def _to_square_url(img_url, size=800):
        """将阿里CDN图片URL转换为1:1方图"""
        if not img_url or 'alicdn.com' not in str(img_url):
            return img_url
        cleaned = str(img_url)
        # 补充协议
        if cleaned.startswith('//'):
            cleaned = 'https:' + cleaned
        # 去除 CDN 处理后缀（按顺序，从最外层开始剥离）
        # _.webp, .webp, _q50.jpg_, _q50.jpg, _90x90.jpg, _90x90q30.jpg 等
        cleaned = _re.sub(r'_\.webp$', '', cleaned)
        cleaned = _re.sub(r'\.webp$', '', cleaned)
        cleaned = _re.sub(r'_q\d+\.jpg_?$', '', cleaned)
        cleaned = _re.sub(r'_\d+x\d+q\d+\.jpg_?$', '', cleaned)
        cleaned = _re.sub(r'_\d+x\d+\.jpg_?$', '', cleaned)
        # 添加方图裁剪后缀 (阿里CDN的 xz 参数=居中裁剪)
        return f'{cleaned}_{size}x{size}xz.jpg'

    jobs = []
    for i, img_url in enumerate(product_data.get('main_images') or [], start=1):
        # 主图: 同时下载原始比例和 1:1 方图
        jobs.append((img_url, os.path.join(main_img_dir, f"主图_{i:02d}{_infer_capture_image_ext(img_url, '')}")))
        square_url = _to_square_url(img_url)
        if square_url != img_url:
            jobs.append((square_url, os.path.join(main_img_dir, f"主图_{i:02d}_1x1.jpg")))
    for index, sku in enumerate(product_data.get('sku_info') or [], start=1):
        img_url = sku.get('image') or (product_data.get('main_images') or [''])[0]
        safe_name = re.sub(r'[\\/:*?"<>|]', '_', str(sku.get('name') or 'SKU')[:50])
        sku_index = int(sku.get('index') or index)
        jobs.append((img_url, os.path.join(sku_img_dir, f"{sku_index:02d}_{safe_name}{_infer_capture_image_ext(img_url, '')}")))
    for i, img_url in enumerate(product_data.get('detail_images') or [], start=1):
        jobs.append((img_url, os.path.join(detail_img_dir, f"详情_{i:03d}{_infer_capture_image_ext(img_url, '')}")))

    if jobs:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(download_image, img_url, filepath) for img_url, filepath in jobs]
            for future in as_completed(futures):
                future.result()

    return parent_dir


def _get_browser_cookies_for_http() -> str:
    """获取浏览器 cookies 用于 Python HTTP 请求（缓存60秒）"""
    global _browser_cookie_str, _browser_cookie_ts
    now = system_time.time()
    if _browser_cookie_str and (now - _browser_cookie_ts) < 60:
        return _browser_cookie_str

    cdp_port = _find_cdp_port()
    if not cdp_port:
        return ''

    import websocket as _ws
    from urllib.request import urlopen as _uopen
    try:
        targets = json.loads(_uopen(f'http://127.0.0.1:{cdp_port}/json/list', timeout=3).read())
        target = next((t for t in targets if t.get('type') == 'page'), None)
        if not target:
            return ''
        ws = _ws.create_connection(target['webSocketDebuggerUrl'], timeout=5, suppress_origin=True)
        mid = [0]
        def _cdp(m, p=None):
            mid[0] += 1
            ws.send(json.dumps({'id': mid[0], 'method': m, 'params': p or {}}))
            dl = system_time.time() + 10
            while system_time.time() < dl:
                raw = ws.recv()
                msg = json.loads(raw)
                if msg.get('id') == mid[0]:
                    return msg
            return {}
        _cdp('Network.enable')
        r = _cdp('Network.getAllCookies')
        ws.close()
        parts = []
        for c in (r.get('result') or {}).get('cookies', []):
            if 'taobao.com' in (c.get('domain', '')) or 'tmall.com' in (c.get('domain', '')):
                parts.append(f"{c['name']}={c['value']}")
        _browser_cookie_str = '; '.join(parts)
        _browser_cookie_ts = now
        return _browser_cookie_str
    except Exception:
        return ''


def _parse_ice_from_html(html: str) -> dict:
    """从单品页 SSR HTML 中提取 __ICE_APP_CONTEXT__ JSON"""
    import re as _re
    idx = html.find('__ICE_APP_CONTEXT__')
    if idx < 0:
        return {}
    # 在 ICE 之后的 200 字符内找 var b = {
    rest = html[idx:idx+200]
    bm = _re.search(r'var\s+b\s*=\s*\{', rest)
    if not bm:
        return {}
    start = idx + bm.end() - 1
    depth = 0
    in_str = False
    esc = False
    for i in range(start, min(start+200000, len(html))):
        ch = html[i]
        if esc:
            esc = False
            continue
        if ch == chr(92):
            esc = True
            continue
        if ch == chr(34) and not esc:
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:i+1])
                except json.JSONDecodeError:
                    return {}
    return {}


def _capture_taobao_tmall_product_for_store(page, product_url: str, options: dict, mtop_cache: dict = None) -> dict:
    """协议优先采集：ICE SSR数据 → HTTP正则 → DOM 三级回退。

    Tier 1: _extract_taobao_ice_data() — 读 __ICE_APP_CONTEXT__ JSON (最稳定)
    Tier 2: Python HTTP + 正则 — 不依赖浏览器页面状态
    Tier 3: DOM snapshot — 浏览器 CSS 选择器 (兜底)
    """

    product_id = _extract_capture_product_id(product_url)
    cached = (mtop_cache or {}).get(product_id) if product_id else None

    product_data = {
        'product_id': product_id,
        'title': '',
        'price': {'current': 0, 'original': None, 'currency': 'CNY'},
        'main_images': [],
        'detail_images': [],
        'sku_info': [],
        'parameters': [],
    }

    # ==== Tier 1: ICE 协议提取 (优先，不依赖 DOM 选择器) ====
    ice_data = None
    try:
        ice_data = _extract_taobao_ice_data(page)
    except Exception as e:
        app.logger.warning(f"ICE提取异常: {e}")

    if ice_data and ice_data.get('title') and ice_data['price']['current'] > 0:
        product_data.update(ice_data)
        pc_desc_url = ice_data.pop('_pc_desc_url', '')
        detail_imgs = []
        # 详情图优先走页内滚动懒加载采集（天猫详情纯 JS 渲染，裸 HTML 拿不到图）
        try:
            detail_imgs = _collect_taobao_desc_images_via_browser(page)
            if detail_imgs:
                app.logger.info(f"详情图(浏览器滚动懒加载): {len(detail_imgs)} 张")
        except Exception as e:
            app.logger.warning(f"详情图浏览器采集异常: {e}")
        # 兜底：pcDescUrl 二次 HTTP 抓取
        if not detail_imgs and pc_desc_url:
            try:
                detail_imgs = _fetch_taobao_desc_images(page, pc_desc_url)
            except Exception as e:
                app.logger.warning(f"详情图获取失败: {e}")
        if detail_imgs:
            product_data['detail_images'] = detail_imgs
        app.logger.info(f"ICE提取成功: title={product_data['title'][:30]} price={product_data['price']['current']} imgs={len(product_data['main_images'])} skus={len(product_data['sku_info'])} details={len(product_data['detail_images'])}")
    else:
        app.logger.info(f"ICE提取数据不完整，回退到HTTP正则+DOM")

    # ==== Tier 2: HTTP 正则 (ICE 失败时回退) ====
    if not product_data['price']['current']:
        import re as _re
        from urllib.request import Request as _Req, urlopen as _urlopen

        cookie_str = _get_browser_cookies_for_http()
        html = ''
        if cookie_str:
            try:
                req = _Req(product_url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120',
                    'Cookie': cookie_str,
                    'Accept': 'text/html,application/xhtml+xml',
                    'Referer': 'https://www.taobao.com/',
                })
                resp = _urlopen(req, timeout=15)
                html = resp.read().decode('utf-8', errors='replace')
            except Exception as e:
                app.logger.warning(f"HTTP请求失败: {e}")

        if html and len(html) > 10000:
            title_m = _re.search(r'<title>([^<]+)</title>', html)
            if title_m and title_m.group(1) != '商品详情':
                product_data['title'] = title_m.group(1)

            pm_m = _re.search(r'"priceMoney"\s*:\s*"(\d+)"', html)
            if pm_m:
                try:
                    product_data['price']['current'] = float(int(pm_m.group(1)) / 100)
                except (ValueError, TypeError):
                    pass

            img_m = _re.search(r'"images"\s*:\s*\[(.*?)\]', html)
            if img_m:
                img_urls = _re.findall(r'"((?:https?:)?//[^"]+)"', img_m.group(1))
                for u in img_urls:
                    url = u if u.startswith('http') else ('https:' + u)
                    if url not in product_data['main_images']:
                        product_data['main_images'].append(url)

            app.logger.info(f"REGEX: html={len(html)}b price={product_data['price']['current']} imgs={len(product_data['main_images'])} title={bool(title_m)}")

        # ==== Tier 3: DOM 回退 (HTTP 也失败时) ====
        if not product_data['price']['current']:
            app.logger.info(f"REGEX回退到page.get: {product_url[:60]}")
            try:
                page.get(product_url, timeout=30)
                system_time.sleep(1.5)
            except Exception as e:
                raise Exception(f'页面导航失败: {e}')
            product_data = _extract_taobao_tmall_product_snapshot(page, product_url)

    # 4. mtop 缓存补充
    if cached:
        if cached.get('title') and not product_data['title']:
            product_data['title'] = str(cached['title'])
        if cached.get('image') and not product_data['main_images']:
            product_data['main_images'] = [str(cached['image'])]
        if cached.get('soldCount'):
            product_data['sold_count'] = str(cached['soldCount'])
        mtop_skus = cached.get('skuList') or []
        if mtop_skus and not product_data['sku_info']:
            for s in mtop_skus:
                product_data['sku_info'].append({
                    'sku_id': str(s.get('skuId', '')),
                    'name': str(s.get('skuText', '')),
                    'price': 0,
                    'image': str(s.get('skuImageUrl', '')),
                })

    download_path = _download_capture_product_images(product_data, product_url, options)
    product_data.update({
        'download_path': download_path,
        'url': product_url,
        'captured_at': datetime.now().isoformat(),
    })
    return product_data

def _run_taobao_tmall_store_capture(page, task_id: str, task_url: str, options: dict, protocol_capture_runtime):
    max_products = int((options or {}).get('max_store_products') or 1000)
    max_pages = int((options or {}).get('max_store_pages') or 50)

    capture_tasks[task_id]['progress'] = 35
    capture_tasks[task_id]['message'] = '正在读取店铺商品列表...'
    product_urls = _collect_taobao_tmall_store_product_urls(
        page,
        task_url,
        max_products=max_products,
        max_pages=max_pages,
    )

    if not product_urls:
        raise Exception('未从店铺页面找到商品链接，请确认店铺页已登录且商品列表可见')

    # 采集间隔：避免频繁 page.get() 触发验证码（默认3秒，可配置）
    request_interval = float((options or {}).get('request_interval_seconds') or 3.0)

    products = []
    errors = []
    total = len(product_urls)
    consecutive_verifications = 0

    for index, product_url in enumerate(product_urls, start=1):
        if capture_tasks.get(task_id, {}).get('status') == 'failed':
            return

        # 连续验证码过多 → 暂停等待用户处理
        if consecutive_verifications >= 3:
            app.logger.warning(f"⏸️ 连续 {consecutive_verifications} 次验证码，暂停30秒...")
            capture_tasks[task_id]['message'] = f'触发验证码过多，暂停等待中 ({index}/{total})...'
            system_time.sleep(30)
            consecutive_verifications = 0

        capture_tasks[task_id]['progress'] = 35 + int((index - 1) / total * 60)
        capture_tasks[task_id]['message'] = f'正在采集店铺商品 {index}/{total}'
        app.logger.info(f"🏪 店铺商品采集 {index}/{total}: {product_url}")
        try:
            products.append(_capture_taobao_tmall_product_for_store(
                page, product_url, options, mtop_cache=_mtop_product_cache))
            consecutive_verifications = 0
        except Exception as product_error:
            err_str = str(product_error)
            app.logger.warning(f"⚠️ 店铺商品采集失败: {product_url}, error={err_str}")
            errors.append({'url': product_url, 'error': err_str})
            if '验证' in err_str or 'punish' in err_str.lower() or 'sec.taobao' in err_str:
                consecutive_verifications += 1

        # 请求间隔
        if index < total:
            system_time.sleep(request_interval)

    if not products:
        raise Exception(f'店铺商品采集全部失败，失败数量: {len(errors)}')

    result = {
        'capture_type': 'store',
        'title': f'店铺采集 {len(products)} 个商品',
        'store_url': task_url,
        'product_urls': product_urls,
        'products': products,
        'errors': errors,
        'sku_count': sum(len(product.get('sku_info') or []) for product in products),
        'task_id': task_id,
        'url': task_url,
        'captured_at': datetime.now().isoformat(),
    }

    capture_tasks[task_id]['status'] = 'completed'
    capture_tasks[task_id]['progress'] = 100
    capture_tasks[task_id]['message'] = f'店铺采集完成：成功 {len(products)} 个，失败 {len(errors)} 个'
    capture_tasks[task_id]['result'] = result
    _finalize_protocol_capture_record(
        protocol_capture_runtime,
        task_id=task_id,
        source_url=task_url,
        status='completed',
        progress=100,
        message=capture_tasks[task_id]['message'],
        result=result,
    )


@app.route('/api/capture/start', methods=['POST'])
def start_capture():
    """启动商品采集任务"""
    try:
        app.logger.info("=" * 80)
        app.logger.info("📥 收到采集请求")
        
        data = request.get_json()
        if not data:
            app.logger.error("❌ 无效的请求数据")
            return jsonify({'success': False, 'message': '无效的请求数据'})
        
        raw_url = str(data.get('url', '') or '').strip()
        url = normalize_capture_url(raw_url)
        options = data.get('options', {
            'download_images': True,
            'extract_sku': True,
            'extract_params': True
        })

        app.logger.info(f"🔗 采集URL: {url}")
        app.logger.info(f"⚙️ 采集选项: {options}")

        # 验证URL
        if not url:
            app.logger.error("❌ URL为空")
            return jsonify({'success': False, 'message': '请输入商品或店铺链接'})

        try:
            resolved_url, short_url = _resolve_capture_redirect_url(url)
            if short_url:
                app.logger.info(f"🔁 淘宝短链已解析: {short_url} -> {resolved_url}")
            url = resolved_url
        except ValueError as resolve_error:
            app.logger.error(f"❌ 短链解析失败: {resolve_error}")
            return jsonify({'success': False, 'message': str(resolve_error)})

        is_1688 = _is_1688_capture_url(url)
        is_taobao_tmall = _is_taobao_tmall_capture_url(url)
        if not is_1688 and not is_taobao_tmall:
            app.logger.error(f"❌ 不支持的URL: {url}")
            return jsonify({'success': False, 'message': '仅支持淘宝/天猫/1688商品链接，或淘宝/天猫店铺链接'})

        # 平台 + 采集方式由后端按 URL 自动识别，并从用户设置读取每平台的偏好。
        # 1688 与 淘宝/天猫 是两个独立平台，从 capture_preferences 分别取对应字段，不跨用。
        platform_choice = '1688' if is_1688 else 'taobao'
        try:
            _ms = settings_manager.get_settings()
            _ac = settings_manager.normalize_automation_config(_ms.automation_config)
            _prefs = _ac.get('capture_preferences') or {}
            if platform_choice == '1688':
                capture_mode = str(_prefs.get('alibaba_1688_mode') or 'dom').strip().lower()
            else:
                capture_mode = str(_prefs.get('taobao_tmall_mode') or 'dom').strip().lower()
            if capture_mode not in {'dom', 'protocol'}:
                capture_mode = 'dom'
        except Exception as _pref_err:
            app.logger.warning(f"⚠️ 读取采集偏好失败，回退默认 dom: {_pref_err}")
            capture_mode = 'dom'

        app.logger.info(f"🎯 平台: {platform_choice} | 采集方式: {capture_mode}（按用户设置自动选择）")

        product_id = _extract_capture_product_id(url)

        # 生成任务ID
        import hashlib
        task_id = f"capture_{int(system_time.time())}_{hashlib.md5(url.encode()).hexdigest()[:8]}"
        app.logger.info(f"🆔 生成任务ID: {task_id}")

        # 并发互斥：同一时刻只允许一个采集任务在跑，避免共享 capture-browser-profile 时
        # Chrome 单 user_data_dir 限制导致两个任务互相打断对方的页面状态。
        global _capture_running_task_id
        with _capture_lock:
            if _capture_running_task_id:
                running = _capture_running_task_id
                app.logger.warning(f"❌ 已有采集任务在跑: {running}，拒绝新请求 {task_id}")
                return jsonify({
                    'success': False,
                    'message': f'已有采集任务正在运行 ({running})，请等待完成或先取消后再试'
                })
            _capture_running_task_id = task_id
            app.logger.info(f"🔒 已占用采集互斥锁: {task_id}")

        protocol_capture_runtime = _start_protocol_capture_record(
            source_url=url,
            task_id=task_id,
            options=options,
            product_id=product_id,
        )
        
        # 创建任务
        task = {
            'task_id': task_id,
            'url': url,
            'original_url': raw_url if raw_url and raw_url != url else '',
            'options': options,
            'platform': platform_choice,
            'capture_mode': capture_mode,
            'status': 'pending',
            'progress': 0,
            'message': '任务创建成功',
            'created_at': datetime.now().isoformat(),
            'result': None,
            'error_code': '',
            'cancelled': False,
            'protocol_capture_root': protocol_capture_runtime.get('root') if protocol_capture_runtime else '',
        }
        
        capture_tasks[task_id] = task
        app.logger.info(f"✅ 任务已创建: {task_id}")
        
        # 在后台线程中启动采集
        def run_capture_task():
            # 在函数开头导入所需模块，避免作用域问题
            import traceback
            import re
            task_url = capture_tasks.get(task_id, {}).get('url', url)
            # 读取本任务的平台/采集方式（默认 auto + dom，保证旧调用兼容）
            task_platform = capture_tasks.get(task_id, {}).get('platform', 'auto')
            task_capture_mode = capture_tasks.get(task_id, {}).get('capture_mode', 'dom')

            try:
                app.logger.info(f"🚀 开始执行采集任务: {task_id}")
                app.logger.info(f"🎯 任务平台: {task_platform} | 采集方式: {task_capture_mode}")

                # 采集方式分发说明：
                #   - dom（默认）：当前已实现的两套独立提取路径
                #       · 1688  → JS 注入读取 window.context（不跨用淘宝协议）
                #       · 淘宝/天猫 → 浏览器内 mtop 客户端调用（不跨用 1688 协议）
                #   - protocol（预览版）：基于 CDP Network 域被动抓接口响应。
                #       完整实现需要枚举每个平台的关键接口并解析响应，工作量较大；
                #       本版本先把请求/响应原文落到 protocol_capture_root 目录便于离线复盘，
                #       数据提取仍走 DOM 路径以保证用户能拿到产品数据，不会出现"功能空转"。
                if task_capture_mode == 'protocol':
                    app.logger.warning(
                        "⚠️ 协议采集为预览版：本次仍按 DOM 路径完成数据提取，"
                        "协议层网络快照将被记录到 protocol_capture_root 供后续抓包分析"
                    )
                    capture_tasks[task_id]['message'] = '协议采集（预览版）：本次走 DOM 提取并记录协议层网络快照...'
                else:
                    app.logger.info("📋 采集方式: DOM 采集（读浏览器渲染数据）")

                # 更新任务状态
                capture_tasks[task_id]['status'] = 'running'
                capture_tasks[task_id]['progress'] = 10
                if not capture_tasks[task_id].get('message', '').startswith('协议采集'):
                    capture_tasks[task_id]['message'] = '正在启动浏览器...'
                app.logger.info(f"📊 进度: 10% - 正在启动浏览器...")
                
                # 使用DrissionPage进行采集（因为项目已经有了这个依赖）
                try:
                    from DrissionPage import ChromiumPage, ChromiumOptions
                    app.logger.info("✅ DrissionPage 导入成功")
                except ImportError as e:
                    app.logger.error(f"❌ DrissionPage 导入失败: {e}")
                    raise Exception(f"缺少依赖库 DrissionPage，请安装: pip install DrissionPage")
                
                # 配置浏览器（添加反爬虫策略）
                app.logger.info("⚙️ 配置浏览器选项...")
                co = ChromiumOptions()
                co.headless(False)  # 显示浏览器，方便用户登录
                capture_port = _select_capture_browser_port()
                capture_user_data_path = _get_capture_browser_user_data_path()
                co.set_paths(local_port=capture_port, user_data_path=capture_user_data_path)
                co.set_user('Default')
                app.logger.info(f"✅ 采集浏览器配置: port={capture_port}, user_data={capture_user_data_path}")
                co.set_load_mode('eager')  # 采集页常驻长连接资源，避免 page.get() 长时间等待 complete
                
                # 🛡️ 反爬虫策略配置
                # 1. 设置真实的User-Agent
                co.set_user_agent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

                # 2. 禁用自动化检测特征

                # 3. 添加更多反检测参数
                co.set_argument('--disable-dev-shm-usage')
                # co.set_argument('--no-sandbox')  # 已移除：会显示警告提示
                co.set_argument('--disable-gpu')

                # 4. 设置窗口大小（模拟真实用户）
                co.set_argument('--window-size=1920,1080')

                # 5. webdriver 标记由 addScriptToEvaluateOnNewDocument 里的 JS 覆盖处理。
                # --disable-blink-features=AutomationControlled 在 Chrome 120+ 已废弃，
                # 加了反而显示"不受支持的命令行标记"警告，不加。

                # 6. 强制不走系统代理（关键！）
                # 现场实测：用户机器开启 Clash 类本地代理(127.0.0.1:7897)时，规则集会拦截
                #   - g.alicdn.com/AWSC/...baxia*.js（阿里风控"八仙"脚本）
                #   - gm.mmstat.com / log.mmstat.com（阿里埋点）
                # 阿里登录页依赖 baxia.js 获取风控 token 才会调用 qrcode/generate.do 生成二维码，
                # baxia 被掐就会出现"二维码框存在但永远空白"的现象。
                # 1688/淘宝/天猫都是国内站点，采集浏览器直连即可，不需要也不应走系统代理。
                co.set_argument('--no-proxy-server')
                # 备用兜底：即便上面被某些场景忽略，bypass-list 也会强制绕过阿里域名
                co.set_argument(
                    '--proxy-bypass-list=<-loopback>;'
                    '*.taobao.com;*.tmall.com;*.alibaba.com;*.alibabagroup.com;'
                    '*.1688.com;*.alicdn.com;*.aliyun.com;*.alipay.com;'
                    '*.mmstat.com;*.alipayobjects.com'
                )

                app.logger.info("✅ 反爬虫策略已配置（含强制直连绕过本地代理）")
                
                # 更新进度
                capture_tasks[task_id]['progress'] = 20
                capture_tasks[task_id]['message'] = '正在启动采集浏览器...'
                app.logger.info(f"📊 进度: 20% - 正在启动采集浏览器...")
                
                # 创建页面
                app.logger.info("🌐 正在启动浏览器...")
                page = ChromiumPage(co)

                # ============== 持久化注入：反检测 + mmstat 埋点短路 ==============
                # 用 Page.addScriptToEvaluateOnNewDocument，每个新 document 加载前自动注入。
                # 旧的 page.run_js 只对当前空白页生效，page.get(商品页) 之后就失效了。
                #
                # mmstat 短路（关键）：
                #   现场实测：用户机器开 Clash / verge-mihomo / Mihomo 等本地代理工具时，
                #   规则集常把 *.mmstat.com（阿里埋点）加入 REJECT 名单，导致请求 SSL 失败。
                #   1688 详情页的初始化 JS 依赖埋点上报，埋点失败会触发 launch_regist_error
                #   并 abort 整个主框架，所有商品模块 JS 被级联取消，最终页面只剩空骨架。
                #   `--no-proxy-server` 启动参数对 TUN 模式代理无效（TUN 在网卡层接管）。
                #   这里在浏览器内 hook fetch / XHR / sendBeacon / Image，让所有 *.mmstat.com
                #   请求立即返回 fake 200，业务 JS 以为埋点成功，正常继续渲染。
                init_script = r'''
                (function () {
                  // 反检测
                  try {
                    Object.defineProperty(navigator, 'webdriver', { get: () => false });
                    Object.defineProperty(navigator, 'plugins',   { get: () => [1, 2, 3, 4, 5] });
                    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
                    if (window.navigator.permissions && window.navigator.permissions.query) {
                      const origQuery = window.navigator.permissions.query;
                      window.navigator.permissions.query = function (p) {
                        return p && p.name === 'notifications'
                          ? Promise.resolve({ state: Notification.permission })
                          : origQuery(p);
                      };
                    }
                  } catch (e) {}

                  // mmstat 短路 —— 绕过本地代理拦截阿里埋点导致的页面渲染中断
                  var BLOCK_PATTERNS = [ /mmstat\.com/i ];
                  function shouldFake(url) {
                    if (typeof url !== 'string') return false;
                    for (var i = 0; i < BLOCK_PATTERNS.length; i++) {
                      if (BLOCK_PATTERNS[i].test(url)) return true;
                    }
                    return false;
                  }

                  if (window.fetch) {
                    var origFetch = window.fetch;
                    window.fetch = function (input, init) {
                      var url = typeof input === 'string' ? input : (input && input.url) || '';
                      if (shouldFake(url)) {
                        return Promise.resolve(new Response('', { status: 200, headers: { 'Content-Type': 'text/plain' } }));
                      }
                      return origFetch.apply(this, arguments);
                    };
                  }

                  if (window.XMLHttpRequest) {
                    var origOpen = XMLHttpRequest.prototype.open;
                    var origSend = XMLHttpRequest.prototype.send;
                    XMLHttpRequest.prototype.open = function (method, url) {
                      try { this.__fakeUrl = shouldFake(url) ? url : null; } catch (e) {}
                      return origOpen.apply(this, arguments);
                    };
                    XMLHttpRequest.prototype.send = function () {
                      var self = this;
                      if (self.__fakeUrl) {
                        setTimeout(function () {
                          try {
                            Object.defineProperty(self, 'readyState',   { configurable: true, get: function () { return 4; } });
                            Object.defineProperty(self, 'status',       { configurable: true, get: function () { return 200; } });
                            Object.defineProperty(self, 'statusText',   { configurable: true, get: function () { return 'OK'; } });
                            Object.defineProperty(self, 'responseText', { configurable: true, get: function () { return ''; } });
                            Object.defineProperty(self, 'response',     { configurable: true, get: function () { return ''; } });
                            if (typeof self.onreadystatechange === 'function') self.onreadystatechange();
                            if (typeof self.onload === 'function') self.onload();
                            self.dispatchEvent(new Event('readystatechange'));
                            self.dispatchEvent(new Event('load'));
                            self.dispatchEvent(new Event('loadend'));
                          } catch (e) {}
                        }, 0);
                        return;
                      }
                      return origSend.apply(this, arguments);
                    };
                  }

                  if (navigator.sendBeacon) {
                    var origBeacon = navigator.sendBeacon.bind(navigator);
                    navigator.sendBeacon = function (url, data) {
                      if (shouldFake(url)) return true;
                      return origBeacon(url, data);
                    };
                  }

                  try { console.log('[capture-init] anti-detect + mmstat-shim installed'); } catch (e) {}
                })();
                '''
                try:
                    page.add_init_js(init_script)
                    app.logger.info("✅ init 脚本已持久化注入（反检测 + mmstat 短路）")
                except Exception as init_err:
                    # add_init_js 不可用时降级为 run_js（只对当前页面生效，但聊胜于无）
                    app.logger.warning(f"⚠️ add_init_js 失败，降级为 run_js: {init_err}")
                    try:
                        page.run_js(init_script)
                    except Exception as run_err:
                        app.logger.error(f"❌ 反检测/mmstat 脚本注入失败: {run_err}")
                
                # 从任务中获取URL
                is_1688 = _is_1688_capture_url(task_url)
                is_taobao_tmall = _is_taobao_tmall_capture_url(task_url)
                is_taobao_tmall_store = (not is_1688) and _is_taobao_tmall_store_url(task_url)
                capture_tasks[task_id]['message'] = '正在访问商品页面...'
                app.logger.info(f"📊 进度: 20% - 正在访问商品页面...")
                
                # 🛡️ 首页导航：建立浏览轨迹（1688 跳过避免触发风控）
                if not is_taobao_tmall_store and not is_1688:
                    try:
                        if 'tmall.com' in task_url:
                            page.get('https://www.tmall.com', timeout=15)
                        else:
                            page.get('https://www.taobao.com', timeout=15)
                        system_time.sleep(1)
                    except Exception as e:
                        app.logger.warning(f"⚠️ 首页访问失败: {e}")

                # 访问目标页面
                app.logger.info(f"🔗 正在访问: {task_url}")
                if is_1688:
                    # 1688: DrissionPage page.get 会因登录重定向触发刷新检测而崩溃，用 CDP 导航
                    # 关键：必须用本任务自己启动的 capture_port，不能用 _find_cdp_port() —
                    # 否则会扫到系统里其他 Chrome（如 DrissionPage 默认 9222），把别人的 Chrome
                    # 强制导航到 1688 商品页，而真正的采集浏览器还停在空白页。
                    try:
                        import websocket as _ws1688nav
                        cdp_port = capture_port
                        targets1688 = json.loads(urlopen(f'http://127.0.0.1:{cdp_port}/json/list', timeout=3).read())
                        # 优先选 DrissionPage 当前控制的那个 tab，避免误导航到其他 tab
                        current_tab_id = ''
                        try:
                            current_tab_id = str(getattr(page, 'tab_id', '') or '')
                        except Exception:
                            current_tab_id = ''
                        page_targets = [t for t in targets1688 if t.get('type') == 'page']
                        target_for_nav = None
                        if current_tab_id:
                            for t in page_targets:
                                if t.get('id') == current_tab_id:
                                    target_for_nav = t
                                    break
                        if target_for_nav is None and page_targets:
                            target_for_nav = page_targets[0]
                        if target_for_nav:
                            ws1688 = _ws1688nav.create_connection(target_for_nav['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
                            ws1688.settimeout(5)
                            # 双保险：在 Page.navigate 之前通过同一个 WebSocket 直接注册
                            # Page.addScriptToEvaluateOnNewDocument，确保 mmstat 短路脚本
                            # 在本次导航的新 document 加载前生效。
                            # add_init_js 依赖 DrissionPage API 是否可用；旧版 API 不可用时
                            # 会降级为 run_js（只对当前空白页生效），CDP 导航后就失效。
                            # 这里直接通过 CDP 再注册一次，不依赖 DrissionPage 版本。
                            try:
                                ws1688.send(json.dumps({
                                    'id': 0,
                                    'method': 'Page.addScriptToEvaluateOnNewDocument',
                                    'params': {'source': init_script},
                                }))
                            except Exception as _reg_err:
                                app.logger.warning(f"⚠️ 1688 CDP addScriptToEvaluateOnNewDocument 注册失败（不影响采集）: {_reg_err}")
                            ws1688.send(json.dumps({'id': 1, 'method': 'Page.enable'}))
                            ws1688.send(json.dumps({'id': 2, 'method': 'Page.navigate', 'params': {'url': task_url}}))
                            # 等待页面加载：基础 5 秒 + 轮询等 window.context 商品数据就绪
                            # （window.context 就绪 ≈ 1688 SPA 主框架渲染完成）
                            system_time.sleep(5)
                            for _w1688 in range(5):
                                try:
                                    if page.run_js(
                                        "return !!(window.context?.result?.global"
                                        "?.globalData?.model?.offerDetail?.subject)"
                                    ):
                                        app.logger.info(f"✅ 1688 window.context 就绪（约 {5 + _w1688 * 2}s）")
                                        break
                                except Exception:
                                    pass
                                system_time.sleep(2)
                            ws1688.close()
                    except Exception as _cdp_nav_err:
                        app.logger.warning(f"1688 CDP导航失败({_cdp_nav_err})，尝试DrissionPage")
                        try:
                            page.get(task_url, timeout=30)
                        except Exception as _dr_err:
                            app.logger.warning(f"1688导航异常，等待页面稳定: {_dr_err}")
                            system_time.sleep(5)
                else:
                    try:
                        page.get(task_url, timeout=30)
                    except Exception as nav_err:
                        err_str = str(nav_err)
                        if '刷新' in err_str or 'refresh' in err_str.lower():
                            app.logger.warning(f"页面刷新/重定向 ({err_str[:80]})，等待页面稳定...")
                            system_time.sleep(5)
                        else:
                            raise
                current_url = page.url
                app.logger.info(f"📍 当前URL: {current_url[:100]}")

                if is_1688 and _is_1688_antibot_page(page):
                    antibot_wait_seconds = _capture_wait_seconds('CAPTURE_ANTIBOT_WAIT_SECONDS', 120)
                    app.logger.warning(f"⚠️ 1688 触发风控验证页，等待用户处理（最多{antibot_wait_seconds}秒）...")
                    capture_tasks[task_id]['message'] = '⏳ 1688 触发访问验证，请在采集浏览器中完成验证...'
                    wait_deadline = system_time.time() + antibot_wait_seconds
                    while system_time.time() < wait_deadline:
                        if capture_tasks.get(task_id, {}).get('cancelled'):
                            return
                        system_time.sleep(2)
                        if not _is_1688_antibot_page(page):
                            app.logger.info("✅ 1688 验证通过，重新进入商品页")
                            try:
                                page.get(task_url, timeout=30)
                            except Exception:
                                pass
                            system_time.sleep(3)
                            break
                    else:
                        app.logger.error("❌ 1688 风控验证等待超时")
                        capture_tasks[task_id]['status'] = 'failed'
                        capture_tasks[task_id]['progress'] = 0
                        capture_tasks[task_id]['error_code'] = '1688_antibot_verification'
                        capture_tasks[task_id]['message'] = (
                            f'1688 触发访问验证，{antibot_wait_seconds} 秒内未完成验证。请在采集浏览器中完成验证后重新采集；'
                            '如果反复触发，先使用普通浏览器打开同一商品链接确认账号/网络环境正常。'
                        )
                        _finalize_protocol_capture_record(
                            protocol_capture_runtime,
                            task_id=task_id,
                            source_url=task_url,
                            status='failed',
                            progress=0,
                            message=capture_tasks[task_id]['message'],
                            error='1688_antibot_verification',
                        )
                        return

                if not is_1688 and ('punish' in current_url or 'sec.taobao.com' in current_url or 'bixi.alicdn.com' in current_url):
                    app.logger.warning("⚠️ 触发安全验证，等待用户处理（最多120秒）...")
                    capture_tasks[task_id]['message'] = '⏳ 触发安全验证，请在浏览器中完成验证...'
                    wait_count = 0
                    while wait_count < 60:
                        if capture_tasks.get(task_id, {}).get('cancelled'):
                            return
                        system_time.sleep(2)
                        wait_count += 1
                        current_url = page.url
                        if 'punish' not in current_url and 'sec.taobao.com' not in current_url and 'bixi.alicdn.com' not in current_url:
                            app.logger.info("✅ 验证通过，继续采集")
                            page.get(task_url, timeout=30)
                            system_time.sleep(3)
                            break
                    else:
                        app.logger.error("❌ 验证等待超时")
                        capture_tasks[task_id]['status'] = 'failed'
                        capture_tasks[task_id]['progress'] = 0
                        capture_tasks[task_id]['error_code'] = 'triggered_antibot_verification'
                        capture_tasks[task_id]['message'] = '验证等待超时，请手动完成验证后重新采集'
                        _finalize_protocol_capture_record(
                            protocol_capture_runtime,
                            task_id=task_id,
                            source_url=task_url,
                            status='failed',
                            progress=0,
                            message=capture_tasks[task_id]['message'],
                            error='triggered_antibot_verification',
                        )
                        return
                
                app.logger.info("✅ 页面访问成功，未被拦截")
                
                # 等待页面完全加载
                system_time.sleep(3)  # 等待3秒，确保页面完全渲染
                
                # 检查是否需要登录（通过URL判断，更快更准确）
                capture_tasks[task_id]['progress'] = 30
                capture_tasks[task_id]['message'] = '检测登录状态...'
                app.logger.info(f"📊 进度: 30% - 检测登录状态...")
                
                login_detected = False
                try:
                    # 获取当前页面URL
                    current_url = page.url
                    app.logger.info(f"🔍 当前URL: {current_url}")
                    
                    # 通过 URL 判断是否需要登录。
                    # 关键：1688 和淘宝/天猫是两个独立平台，登录页也是两套独立实体：
                    #   - 1688 任务：当前 URL 可能是 1688 自己的登录页（_is_1688_login_url），
                    #     也可能是淘宝"会员通"统一登录页（_is_taobao_login_url）；
                    #     只要 cookie 写到对应域名上，回到 detail.1688.com 后 **协议提取永远走 1688 的 window.context**，
                    #     绝不会因为登录页是淘宝域名就改用淘宝的 mtop 协议。
                    #   - 淘宝/天猫任务：只识别 _is_taobao_login_url，不会去看 1688 的登录页。
                    if is_1688:
                        on_login_page = (
                            _is_1688_login_url(current_url)
                            or _is_taobao_login_url(current_url)
                        )
                        login_hint_msg = (
                            '需要登录 1688，请在浏览器中完成登录（建议使用账号密码，扫码登录可能被风控）...'
                        )
                    else:
                        on_login_page = _is_taobao_login_url(current_url)
                        login_hint_msg = '需要登录淘宝/天猫，请在浏览器中完成登录...'

                    # 检测到登录页时，主动诊断本地代理/TUN 环境（二维码空白的常见根因），
                    # 把根因和解决办法直接推给用户，避免对着空白二维码干等到超时。
                    proxy_risk_hint = _detect_local_proxy_risk()

                    if on_login_page:
                        login_detected = True
                        app.logger.warning(f"⚠️ 检测到登录页面: {current_url[:120]}")
                        if proxy_risk_hint:
                            login_hint_msg = login_hint_msg + ' ' + proxy_risk_hint
                            app.logger.warning(f"🛑 代理环境风险: {proxy_risk_hint}")
                        capture_tasks[task_id]['message'] = login_hint_msg

                        # 等待用户登录（最多等待 120 秒）
                        wait_count = 0
                        app.logger.info("⏳ 等待用户完成登录（最多120秒）...")
                        while wait_count < 60 and login_detected:
                            if capture_tasks.get(task_id, {}).get('cancelled'):
                                return
                            system_time.sleep(2)
                            wait_count += 1

                            # 检查 URL 是否已离开登录页
                            current_url = page.url
                            if is_1688:
                                still_on_login = (
                                    _is_1688_login_url(current_url)
                                    or _is_taobao_login_url(current_url)
                                )
                            else:
                                still_on_login = _is_taobao_login_url(current_url)

                            if not still_on_login:
                                if is_taobao_tmall_store:
                                    login_detected = False
                                    app.logger.info(f"✅ 店铺登录完成，回到店铺链接: {task_url[:100]}")
                                    page.get(task_url, timeout=30)
                                    system_time.sleep(2)
                                    break
                                # 确认已经跳转回商品页面
                                if (
                                    (is_1688 and ('detail.1688.com' in current_url or 'offer.1688.com' in current_url or '/offer/' in current_url))
                                    or (not is_1688 and ('detail.tmall.com' in current_url or 'item.taobao.com' in current_url))
                                ):
                                    login_detected = False
                                    app.logger.info(f"✅ 登录完成，当前URL: {current_url[:100]}")
                                    # 等待页面稳定加载
                                    system_time.sleep(2)
                                    break
                                # 已经离开登录页但没回到商品页（1688 登录后常停在首页或中转页），
                                # 主动导航回原始商品链接
                                app.logger.info(
                                    f"✅ 已离开登录页但未跳回商品页，主动重新导航: {current_url[:80]}"
                                )
                                try:
                                    page.get(task_url, timeout=30)
                                    system_time.sleep(3)
                                    login_detected = False
                                    break
                                except Exception as _renav_err:
                                    app.logger.warning(f"⚠️ 登录后重新导航失败: {_renav_err}")
                                    # 继续等下一轮检测，不立刻判失败
                        
                        if login_detected:
                            app.logger.warning("⏰ 登录等待超时")
                            capture_tasks[task_id]['status'] = 'failed'
                            capture_tasks[task_id]['progress'] = 0
                            capture_tasks[task_id]['error_code'] = 'login_timeout'
                            timeout_msg = (
                                '1688 登录等待超时，当前会话仍停留在登录页，请先在浏览器中完成登录后再重试'
                                if is_1688
                                else '淘宝/天猫登录等待超时，当前会话仍停留在登录页，请先在浏览器中完成登录后再重试'
                            )
                            if proxy_risk_hint:
                                timeout_msg = timeout_msg + ' ' + proxy_risk_hint
                            capture_tasks[task_id]['message'] = timeout_msg
                            _finalize_protocol_capture_record(
                                protocol_capture_runtime,
                                task_id=task_id,
                                source_url=task_url,
                                status='failed',
                                progress=0,
                                message=capture_tasks[task_id]['message'],
                                error='login_timeout',
                            )
                            return
                    else:
                        app.logger.info("✅ 无需登录或已登录")
                except Exception as e:
                    app.logger.warning(f"⚠️ 登录检测异常: {e}")

                if is_taobao_tmall_store:
                    app.logger.info("🏪 检测到淘宝/天猫店铺链接，进入店铺批量采集分支")
                    _run_taobao_tmall_store_capture(page, task_id, task_url, options, protocol_capture_runtime)
                    return
                
                # 🔧 提取商品ID
                extracted_product_id = ''
                try:
                    extracted_product_id = _extract_capture_product_id(task_url)
                    if extracted_product_id:
                        app.logger.info(f"✅ 商品ID: {extracted_product_id}")
                    else:
                        app.logger.warning("⚠️ 未能从URL提取商品ID")
                        extracted_product_id = f"product_{int(system_time.time())}"
                except Exception as e:
                    app.logger.error(f"❌ 提取商品ID失败: {e}")
                    extracted_product_id = f"product_{int(system_time.time())}"
                
                # 🔧 协议采集单品
                capture_tasks[task_id]['progress'] = 50
                capture_tasks[task_id]['message'] = '正在提取商品信息...'
                app.logger.info(f"📊 进度: 50% - 正在提取商品信息...")

                if is_1688:
                    # ==== 1688 协议提取：window.context 数据 ====
                    app.logger.info("🔍 1688协议提取: 读取 window.context")
                    product_data = {
                        'product_id': _extract_capture_product_id(task_url),
                        'title': '',
                        'price': {'current': 0, 'original': None, 'currency': 'CNY'},
                        'main_images': [],
                        'detail_images': [],
                        'sku_info': [],
                        'parameters': [],
                    }

                    # ============================================================
                    # 关键校验：浏览器实际跳到的 offerId 必须等于 task_url 的 offerId
                    # ------------------------------------------------------------
                    # 之前的 CDP Page.navigate 只 sleep(5) 不等导航完成回调；如果导航被
                    # 1688 风控阻塞/CDP tab 选错/旧 profile 残留，浏览器可能还停在上一次
                    # 采集留下的商品页 (例如 1031073754824)，但 task_url 是另一个商品
                    # (例如 9999999)。此时 sidecar 会拿"上一次商品的 window.context 数据"
                    # 但 product_id 用"新商品的 offerId"算出来，结果就是"输入 A 链接，
                    # 采集到 B 商品数据"——这是严重的数据错配 bug，必须在提取前堵住。
                    # ============================================================
                    expected_pid = (_extract_capture_product_id(task_url) or '').strip()

                    def _current_page_pid():
                        try:
                            return (_extract_capture_product_id(page.url or '') or '').strip()
                        except Exception:
                            return ''

                    if expected_pid:
                        actual_pid = _current_page_pid()
                        if actual_pid != expected_pid:
                            app.logger.warning(
                                f"⚠️ 浏览器 URL 与目标商品不一致: expected={expected_pid} actual={actual_pid} "
                                f"current_url={(page.url or '')[:140]}；强制重新导航 1 次"
                            )
                            try:
                                page.get(task_url, timeout=30)
                                system_time.sleep(4)
                            except Exception as _renav_err:
                                app.logger.warning(f"重新导航异常: {_renav_err}")
                            actual_pid = _current_page_pid()
                            if actual_pid != expected_pid:
                                app.logger.error(
                                    f"❌ 重新导航后 URL 仍不匹配: expected={expected_pid} actual={actual_pid} "
                                    f"current_url={(page.url or '')[:200]}"
                                )
                                capture_tasks[task_id]['status'] = 'failed'
                                capture_tasks[task_id]['progress'] = 0
                                capture_tasks[task_id]['error_code'] = '1688_url_mismatch'
                                capture_tasks[task_id]['message'] = (
                                    f'浏览器未能跳转到目标商品 (期望 offerId={expected_pid}，'
                                    f'实际停在 {actual_pid or "未知页面"})。可能原因：1688 反爬拦截/页面跳转被本地代理阻断。'
                                    f'请关闭代理工具的 TUN 模式或在浏览器中手动访问 {task_url} 后重试。'
                                )
                                _finalize_protocol_capture_record(
                                    protocol_capture_runtime,
                                    task_id=task_id,
                                    source_url=task_url,
                                    status='failed',
                                    progress=0,
                                    message=capture_tasks[task_id]['message'],
                                    error='1688_url_mismatch',
                                )
                                return
                        app.logger.info(f"✅ URL 一致性校验通过: offerId={expected_pid}")

                    # 显式等待 window.context.result.global.globalData.model.offerDetail 填充
                    # 1688 用 eager load mode + set_load_mode('eager')，page.get() 提前返回，
                    # 此时 model 可能还没由 launch JS 写入。最多等 18s。
                    # 同时校验 offerDetail.offerId 等于 expected_pid，防止页面正在切换但 ctx
                    # 还是上一个商品的残留值。
                    wait_ready_start = system_time.time()
                    ready_ok = False
                    last_observed_offer_id = ''
                    while system_time.time() - wait_ready_start < 18:
                        try:
                            ready_info = page.run_js('''
                                return (() => {
                                    const od = window.context?.result?.global?.globalData?.model?.offerDetail;
                                    if (!od || !od.subject || od.subject.length === 0) return null;
                                    return { offer_id: String(od.offerId || '') };
                                })()
                            ''')
                            if ready_info:
                                observed_oid = str((ready_info or {}).get('offer_id') or '').strip()
                                last_observed_offer_id = observed_oid
                                # 双重校验：URL 一致 + offerDetail.offerId 也要一致
                                if not expected_pid or observed_oid == expected_pid:
                                    ready_ok = True
                                    break
                        except Exception:
                            pass
                        system_time.sleep(0.5)
                    elapsed = system_time.time() - wait_ready_start
                    if ready_ok:
                        app.logger.info(
                            f"✅ 1688 window.context.offerDetail 已就绪（等待 {elapsed:.1f}s, offerId={last_observed_offer_id}）"
                        )
                    else:
                        # offerDetail 未填充，或填充的 offerId 跟 task_url 不符
                        if expected_pid and last_observed_offer_id and last_observed_offer_id != expected_pid:
                            app.logger.error(
                                f"❌ window.context.offerDetail.offerId={last_observed_offer_id} 与目标 {expected_pid} 不符，"
                                f"采集会拿到错误商品；直接失败而不是吐错数据"
                            )
                            capture_tasks[task_id]['status'] = 'failed'
                            capture_tasks[task_id]['progress'] = 0
                            capture_tasks[task_id]['error_code'] = '1688_offerid_mismatch'
                            capture_tasks[task_id]['message'] = (
                                f'window.context 数据与目标商品不一致 (期望 offerId={expected_pid}，'
                                f'页面里是 {last_observed_offer_id})。可能浏览器残留了上次的页面状态。'
                                f'请手动刷新页面或重启采集浏览器后重试。'
                            )
                            _finalize_protocol_capture_record(
                                protocol_capture_runtime,
                                task_id=task_id,
                                source_url=task_url,
                                status='failed',
                                progress=0,
                                message=capture_tasks[task_id]['message'],
                                error='1688_offerid_mismatch',
                            )
                            return
                        app.logger.warning(
                            f"⚠️ 1688 window.context.offerDetail 未在 18s 内填充（last_observed_offer_id={last_observed_offer_id or '空'}），继续尝试提取"
                        )

                    try:
                        snapshot = _extract_1688_context_snapshot(page)
                        if snapshot and snapshot.get('title'):
                            product_data['title'] = str(snapshot['title']).strip()

                            # 主图
                            main_imgs = snapshot.get('main_images') or snapshot.get('offer_images') or []
                            product_data['main_images'] = [
                                u if u.startswith('http') else ('https:' + u)
                                for u in main_imgs[:12]
                            ]

                            # 价格
                            current_prices = snapshot.get('current_prices') or []
                            if current_prices:
                                try:
                                    price_val = float(current_prices[0].get('price', '0'))
                                    product_data['price']['current'] = price_val
                                except (ValueError, TypeError, KeyError):
                                    pass

                            # SKU
                            default_price = product_data['price']['current']
                            from urllib.request import urlopen as _urlopen_1688
                            sku_info = _build_1688_sku_info(snapshot, None, default_price)
                            if sku_info:
                                product_data['sku_info'] = sku_info
                            elif not product_data['sku_info']:
                                product_data['sku_info'].append({
                                    'type': '规格', 'name': '默认', 'image': '',
                                    'price': default_price, 'index': 1,
                                })

                            # 详情图
                            detail_url = snapshot.get('detail_url', '')
                            if detail_url:
                                detail_imgs = _collect_1688_detail_images(detail_url)
                                if detail_imgs:
                                    product_data['detail_images'] = detail_imgs

                            # 参数
                            parameters = _extract_1688_parameters(snapshot)
                            if parameters:
                                product_data['parameters'] = parameters

                            app.logger.info(
                                f"1688协议提取成功: title={bool(product_data['title'])} "
                                f"price={product_data['price']['current']} "
                                f"images={len(product_data['main_images'])} "
                                f"skus={len(product_data['sku_info'])} "
                                f"details={len(product_data['detail_images'])}"
                            )
                        else:
                            # 关键：1688 提取失败时不能回退到淘宝 mtop 协议（两个平台独立）。
                            # 直接报清晰的失败信息，让用户知道根因。
                            app.logger.error("❌ 1688 window.context 数据不可用，且不能跨用淘宝协议；本次采集失败。")
                            capture_tasks[task_id]['status'] = 'failed'
                            capture_tasks[task_id]['progress'] = 0
                            capture_tasks[task_id]['error_code'] = '1688_context_empty'
                            capture_tasks[task_id]['message'] = (
                                '1688 商品页 window.context 数据未填充，可能是页面没加载完整。'
                                '常见原因：本地代理工具（Clash / verge-mihomo 等）的 TUN 模式拦截了 mmstat 之外的关键资源；'
                                '请暂时关闭代理或在规则中放行 *.alicdn.com / *.1688.com / *.mmstat.com 后重试。'
                            )
                            _finalize_protocol_capture_record(
                                protocol_capture_runtime,
                                task_id=task_id,
                                source_url=task_url,
                                status='failed',
                                progress=0,
                                message=capture_tasks[task_id]['message'],
                                error='1688_context_empty',
                            )
                            return
                    except Exception as e:
                        # 同上：不跨协议回退。让错误信息明确指出根因。
                        app.logger.error(f"❌ 1688 协议提取异常: {e}")
                        capture_tasks[task_id]['status'] = 'failed'
                        capture_tasks[task_id]['progress'] = 0
                        capture_tasks[task_id]['error_code'] = '1688_extract_exception'
                        capture_tasks[task_id]['message'] = f'1688 协议提取失败: {str(e)[:120]}'
                        _finalize_protocol_capture_record(
                            protocol_capture_runtime,
                            task_id=task_id,
                            source_url=task_url,
                            status='failed',
                            progress=0,
                            message=capture_tasks[task_id]['message'],
                            error='1688_extract_exception',
                        )
                        return
                else:
                    # ==== 淘宝/天猫: ICE+HTTP+DOM 三级回退 ====
                    product_data = _capture_taobao_tmall_product_for_store(page, task_url, options)

                extracted_product_id = product_data.get('product_id', f"product_{int(system_time.time())}")
                platform_context = {}
                # 🔧 下载图片（改进版：按文件夹分类）
                capture_tasks[task_id]['progress'] = 70
                capture_tasks[task_id]['message'] = '正在下载图片...'
                app.logger.info(f"📊 进度: 70% - 正在下载图片...")
                
                download_path = None
                if options.get('download_images', True):
                    # 从配置获取基础保存路径，默认为 'uploads/products'
                    base_save_path = options.get('save_path', 'uploads/products')
                    
                    # 规范化路径（支持相对路径和绝对路径，支持打包后的可执行文件）
                    base_save_path = normalize_save_path(base_save_path)
                    
                    app.logger.info(f"📂 基础保存路径: {base_save_path}")
                    app.logger.info(f"📂 程序根目录: {get_app_root()}")
                    
                    # 使用ID-{商品ID}作为父文件夹名称（符合ID模式）
                    parent_dir = os.path.join(base_save_path, f'ID-{extracted_product_id}')
                    os.makedirs(parent_dir, exist_ok=True)
                    
                    app.logger.info(f"✅ 文件将保存到: {parent_dir}")
                    
                    # 创建子文件夹
                    main_img_dir = os.path.join(parent_dir, '主图')
                    sku_img_dir = os.path.join(parent_dir, 'SKU')
                    detail_img_dir = os.path.join(parent_dir, '详情页')
                    
                    os.makedirs(main_img_dir, exist_ok=True)
                    os.makedirs(sku_img_dir, exist_ok=True)
                    os.makedirs(detail_img_dir, exist_ok=True)
                    
                    app.logger.info(f"📁 创建文件夹结构: {parent_dir}")
                    
                    import requests
                    from concurrent.futures import ThreadPoolExecutor, as_completed
                    
                    session = requests.Session()
                    session.headers.update({
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    })
                    
                    total_images = len(product_data['main_images']) + len(product_data['detail_images']) + len([s for s in product_data['sku_info'] if s.get('image')])
                    downloaded = 0
                    
                    # 定义并行下载函数
                    def download_image(img_url, filepath, img_type, index):
                        """并行下载单张图片"""
                        try:
                            if img_url.startswith('//'):
                                img_url = 'https:' + img_url
                            
                            response = session.get(img_url, timeout=15)
                            
                            if response.status_code == 200:
                                # 检查图片大小，过滤1px占位图
                                if len(response.content) < 100:
                                    return {'success': False, 'reason': 'small_size', 'size': len(response.content)}
                                
                                with open(filepath, 'wb') as f:
                                    f.write(response.content)
                                
                                return {'success': True, 'size': len(response.content), 'type': img_type, 'index': index}
                            else:
                                return {'success': False, 'reason': 'http_error', 'status': response.status_code}
                        except Exception as e:
                            return {'success': False, 'reason': 'exception', 'error': str(e)}
                    
                    # 并行下载主图
                    app.logger.info(f"📥 开始并行下载主图: {len(product_data['main_images'])} 张")
                    main_download_count = 0
                    with ThreadPoolExecutor(max_workers=8) as executor:
                        futures = []
                        for i, img_url in enumerate(product_data['main_images']):
                            ext = _get_image_ext(img_url, '')
                            filename = f"主图_{i+1:02d}{ext}"
                            filepath = os.path.join(main_img_dir, filename)
                            future = executor.submit(download_image, img_url, filepath, 'main', i+1)
                            futures.append(future)
                        
                        # 等待所有任务完成
                        for future in as_completed(futures):
                            result = future.result()
                            if result['success']:
                                downloaded += 1
                                main_download_count += 1
                                progress = 70 + (downloaded / total_images) * 20
                                capture_tasks[task_id]['progress'] = int(progress)
                    
                    app.logger.info(f"✅ 主图下载完成: {main_download_count}/{len(product_data['main_images'])} 张")
                    
                    # 并行下载SKU图片
                    sku_with_image = [s for s in product_data['sku_info'] if s.get('image')]
                    app.logger.info(f"📥 开始并行下载SKU图片: {len(sku_with_image)} 张")
                    sku_download_count = 0
                    with ThreadPoolExecutor(max_workers=10) as executor:
                        futures = []
                        for sku in product_data['sku_info']:
                            if not sku.get('image'):
                                continue
                            
                            img_url = sku['image']
                            ext = _get_image_ext(img_url, '')
                            safe_name = re.sub(r'[\\/:*?"<>|]', '_', sku['name'][:50])
                            filename = f"{sku['index']:02d}_{safe_name}{ext}"
                            filepath = os.path.join(sku_img_dir, filename)
                            future = executor.submit(download_image, img_url, filepath, 'sku', sku['index'])
                            futures.append(future)
                        
                        # 等待所有任务完成
                        for future in as_completed(futures):
                            result = future.result()
                            if result['success']:
                                downloaded += 1
                                sku_download_count += 1
                                progress = 70 + (downloaded / total_images) * 20
                                capture_tasks[task_id]['progress'] = int(progress)
                    
                    app.logger.info(f"✅ SKU图片下载完成: {sku_download_count}/{len(sku_with_image)} 张")
                    
                    # 并行下载详情页图片
                    app.logger.info(f"📥 开始并行下载详情页图片: {len(product_data['detail_images'])} 张")
                    detail_download_count = 0
                    with ThreadPoolExecutor(max_workers=10) as executor:
                        futures = []
                        for i, img_url in enumerate(product_data['detail_images']):
                            ext = _get_image_ext(img_url, '')
                            filename = f"详情_{i+1:03d}{ext}"
                            filepath = os.path.join(detail_img_dir, filename)
                            future = executor.submit(download_image, img_url, filepath, 'detail', i+1)
                            futures.append(future)
                        
                        # 等待所有任务完成
                        for future in as_completed(futures):
                            result = future.result()
                            if result['success']:
                                downloaded += 1
                                detail_download_count += 1
                                progress = 70 + (downloaded / total_images) * 20
                                capture_tasks[task_id]['progress'] = int(progress)
                    
                    app.logger.info(f"✅ 详情图下载完成: {detail_download_count}/{len(product_data['detail_images'])} 张")
                    
                    download_path = parent_dir
                    app.logger.info(f"✅ 图片下载完成：共 {downloaded}/{total_images} 张")
                
                # 保持浏览器打开（用户可能需要继续浏览或验证其他商品）
                app.logger.info("✅ 采集完成，浏览器保持打开状态")
                app.logger.info("💡 提示：您可以在浏览器中继续浏览商品，或手动关闭浏览器")
                # page.quit()  # 已注释：不再自动关闭浏览器
                
                # 更新任务状态
                capture_tasks[task_id]['status'] = 'completed'
                capture_tasks[task_id]['progress'] = 100
                capture_tasks[task_id]['message'] = '采集完成'
                capture_tasks[task_id]['result'] = {
                    **product_data,
                    'download_path': download_path,
                    'task_id': task_id,
                    'url': task_url,
                    'captured_at': datetime.now().isoformat()
                }
                _finalize_protocol_capture_record(
                    protocol_capture_runtime,
                    task_id=task_id,
                    source_url=task_url,
                    status='completed',
                    progress=100,
                    message='采集完成',
                    result=capture_tasks[task_id]['result'],
                )
                
                app.logger.info("=" * 80)
                app.logger.info(f"✅✅✅ 采集任务完成: {task_id}")
                app.logger.info(f"📝 商品ID: {extracted_product_id}")
                app.logger.info(f"📝 标题: {product_data['title']}")
                app.logger.info(f"💰 价格: ¥{product_data['price']['current']}")
                app.logger.info(f"🖼️ 主图: {len(product_data['main_images'])} 张")
                app.logger.info(f"📸 详情图: {len(product_data['detail_images'])} 张")
                app.logger.info(f"📦 SKU: {len(product_data['sku_info'])} 个")
                app.logger.info(f"💾 下载目录: {download_path}")
                app.logger.info("=" * 80)
                
            except Exception as e:
                app.logger.error("=" * 80)
                app.logger.error(f"❌❌❌ 采集任务失败: {task_id}")
                app.logger.error(f"错误类型: {type(e).__name__}")
                app.logger.error(f"错误信息: {str(e)}")
                app.logger.error("详细堆栈:")
                app.logger.error(traceback.format_exc())
                app.logger.error("=" * 80)
                
                capture_tasks[task_id]['status'] = 'failed'
                capture_tasks[task_id]['progress'] = 0
                capture_tasks[task_id]['error_code'] = type(e).__name__
                capture_tasks[task_id]['message'] = f'采集失败: {str(e)}'
                _finalize_protocol_capture_record(
                    protocol_capture_runtime,
                    task_id=task_id,
                    source_url=task_url,
                    status='failed',
                    progress=0,
                    message=capture_tasks[task_id]['message'],
                    error=str(e),
                )
        
        # 辅助函数：获取图片扩展名
        def _get_image_ext(url, content_type=''):
            """根据URL和Content-Type确定图片扩展名"""
            # 优先从Content-Type判断
            if 'image/png' in content_type:
                return '.png'
            elif 'image/gif' in content_type:
                return '.gif'
            elif 'image/webp' in content_type:
                return '.webp'
            elif 'image/jpeg' in content_type or 'image/jpg' in content_type:
                return '.jpg'
            
            # 从URL判断
            if '.png' in url.lower():
                return '.png'
            elif '.gif' in url.lower():
                return '.gif'
            elif '.webp' in url.lower():
                return '.webp'
            elif '.jpg' in url.lower() or '.jpeg' in url.lower():
                return '.jpg'
            
            # 默认
            return '.jpg'
        
        # 在后台线程中运行，外层 wrapper 负责释放互斥锁，无论成功/失败/异常都会清零
        def _run_capture_task_with_lock_release():
            try:
                run_capture_task()
            finally:
                global _capture_running_task_id
                with _capture_lock:
                    if _capture_running_task_id == task_id:
                        _capture_running_task_id = None
                        app.logger.info(f"🔓 已释放采集互斥锁: {task_id}")

        import threading
        thread = threading.Thread(target=_run_capture_task_with_lock_release, daemon=True)
        thread.start()
        app.logger.info(f"🧵 后台线程已启动")
        
        # 构建响应
        response_data = {
            'success': True,
            'task_id': task_id,
            'data': {
                'task_id': task_id,
                'url': url,
            },
            'message': '采集任务已启动'
        }
        app.logger.info(f"📤 准备返回响应: {response_data}")
        
        response = jsonify(response_data)
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        app.logger.info(f"✅ 响应已返回，状态码: 200")
        
        return response
        
    except Exception as e:
        app.logger.error("=" * 80)
        app.logger.error("❌❌❌ 启动采集任务失败")
        app.logger.error(f"错误类型: {type(e).__name__}")
        app.logger.error(f"错误信息: {str(e)}")
        app.logger.error("详细堆栈:")
        app.logger.error(traceback.format_exc())
        app.logger.error("=" * 80)

        # 如果在"占锁之后、启动线程之前"挂了，必须释放锁，避免后续永远拒绝新任务
        # 注：函数顶部已经 `global _capture_running_task_id`，这里不能再声明一次
        _task_id_local = locals().get('task_id')
        if _task_id_local:
            with _capture_lock:
                if _capture_running_task_id == _task_id_local:
                    _capture_running_task_id = None
                    app.logger.info(f"🔓 启动失败已释放采集互斥锁: {_task_id_local}")

        return jsonify({
            'success': False,
            'message': f'启动任务失败: {str(e)}'
        })


@app.route('/api/capture/status/<task_id>', methods=['GET'])
def get_capture_status(task_id: str):
    """获取采集任务状态"""
    task = capture_tasks.get(task_id)
    
    if not task:
        return jsonify({
            'success': False,
            'message': '任务不存在'
        })
    
    recovery_info = _capture_task_recovery_info(task)
    return jsonify({
        'success': True,
        'task_id': task_id,
        'status': task['status'],
        'progress': task['progress'],
        'message': task['message'],
        'error_code': task.get('error_code', ''),
        **recovery_info,
        'platform': task.get('platform'),
        'capture_mode': task.get('capture_mode'),
        'result': task.get('result'),
        'created_at': task['created_at']
    })


@app.route('/api/capture/history', methods=['GET'])
def get_capture_history():
    tasks = []
    for task in capture_tasks.values():
        recovery_info = _capture_task_recovery_info(task)
        tasks.append({
            'task_id': task.get('task_id'),
            'url': task.get('url', ''),
            'status': task.get('status', 'pending'),
            'progress': task.get('progress', 0),
            'message': task.get('message', ''),
            'error_code': task.get('error_code', ''),
            **recovery_info,
            'platform': task.get('platform'),
            'capture_mode': task.get('capture_mode'),
            'created_at': task.get('created_at')
        })
    tasks.sort(key=lambda x: x.get('created_at') or '', reverse=True)
    return jsonify({
        'success': True,
        'data': {
            'tasks': tasks
        }
    })


@app.route('/api/capture/cancel/<task_id>', methods=['POST'])
def cancel_capture(task_id: str):
    task = capture_tasks.get(task_id)
    if not task:
        return jsonify({
            'success': False,
            'message': '任务不存在'
        }), 404

    if task.get('status') in ('completed', 'failed'):
        return jsonify({
            'success': True,
            'message': '任务已结束',
            'task_id': task_id
        })

    task['status'] = 'failed'
    task['progress'] = 0
    task['cancelled'] = True
    task['error_code'] = 'cancelled'
    task['message'] = '任务已取消'

    # 同步释放互斥锁，否则后续新任务会一直被"已有采集任务正在运行"拒绝
    global _capture_running_task_id
    with _capture_lock:
        if _capture_running_task_id == task_id:
            _capture_running_task_id = None
            app.logger.info(f"🔓 取消任务时释放采集互斥锁: {task_id}")

    return jsonify({
        'success': True,
        'message': '已取消采集任务',
        'task_id': task_id
    })


def _import_capture_product_record(product_data: dict) -> dict:
    """将单个采集商品写入待上传列表，供单品导入和店铺批量导入共用。"""
    title = product_data.get('title', '采集的商品')
    download_path_raw = product_data.get('download_path', '')
    download_path = os.path.normpath(download_path_raw) if download_path_raw else ''
    if not download_path or not os.path.exists(download_path):
        raise Exception(f'图片目录不存在: {download_path}')

    captured_sku_info = product_data.get('sku_info', []) or []
    captured_main_images = product_data.get('main_images', []) or []

    sku_path = None
    for folder_name in os.listdir(download_path):
        if 'SKU' in folder_name.upper():
            sku_path = os.path.join(download_path, folder_name)
            break
    if not sku_path or not os.path.exists(sku_path):
        raise Exception('未找到SKU文件夹')

    image_files = list_files_recursive(sku_path)
    if not image_files:
        main_path = None
        for folder_name in os.listdir(download_path):
            if '主图' in folder_name:
                main_path = os.path.join(download_path, folder_name)
                break
        local_main_images = list_files_recursive(main_path) if main_path and os.path.exists(main_path) else []
        if local_main_images and captured_sku_info:
            import shutil
            restored = []
            for index, captured_sku in enumerate(captured_sku_info, start=1):
                safe_name = re.sub(r'[\\/:*?"<>|]', '_', str(captured_sku.get('name') or f'SKU_{index}')[:50])
                source = local_main_images[(index - 1) % len(local_main_images)]
                target = os.path.join(sku_path, f"{index:02d}_{safe_name}{os.path.splitext(source)[1] or '.jpg'}")
                shutil.copyfile(source, target)
                restored.append(target)
            image_files = restored
    if not image_files:
        raise Exception('未找到图片文件')

    captured_sku_by_index = {}
    for enum_idx, captured_sku in enumerate(captured_sku_info, start=1):
        try:
            sku_index = int(captured_sku.get('index') or enum_idx)
        except Exception:
            sku_index = enum_idx
        captured_sku_by_index.setdefault(sku_index, captured_sku)

    sku_list = []
    for sku_file in image_files:
        file_name = os.path.basename(sku_file).split('.')[0]
        dir_name = os.path.basename(os.path.dirname(sku_file))
        file_index, name = parse_downloaded_sku_file_name(file_name)
        sku_price = ''
        matched_sku = captured_sku_by_index.get(file_index) if file_index is not None else None
        if matched_sku:
            sku_price = matched_sku.get('price', '')
            if matched_sku.get('name'):
                name = str(matched_sku.get('name')).strip()
        else:
            normalized_name = normalize_capture_sku_name(name)
            for captured_sku in captured_sku_info:
                captured_name = normalize_capture_sku_name(captured_sku.get('name'))
                if captured_name and (
                    captured_name == normalized_name
                    or captured_name in normalized_name
                    or normalized_name in captured_name
                ):
                    sku_price = captured_sku.get('price', '')
                    if captured_sku.get('name'):
                        name = str(captured_sku.get('name')).strip()
                    break

        sku_list.append({
            'file_name': file_name,
            'dir_name': dir_name,
            'name': name,
            'path': sku_file,
            'price': sku_price,
        })

    # SKU 去重
    sku_list, dedup_count = _dedup_sku_list(sku_list)
    if dedup_count > 0:
        app.logger.info(f'SKU去重: {folder_name} 移除了 {dedup_count} 个重复项')

    folder_name = os.path.basename(download_path)
    Record.delete().where(Record.path == download_path).execute()

    record = Record.create(
        name=folder_name,
        path=download_path,
        type=2,
        status=0,
        repo=100,
        title=title,
        clazz=infer_clazz_from_title(title),
        remark='',
        content=json.dumps(sku_list, ensure_ascii=False),
        update_time=datetime.now(),
        import_source='capture',
        source_url=str(product_data.get('url') or ''),
        managed_files=True,
    )
    return {
        'record_id': record.id,
        'record_name': folder_name,
        'sku_count': len(sku_list),
        'title': title,
    }


@app.route('/api/capture/import', methods=['POST'])
def import_capture_result():
    """导入采集结果到待上传列表"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'})
        
        task_id = data.get('task_id')
        product_data = data.get('product_data')
        task = capture_tasks.get(task_id) if task_id else None
        if task and task.get('result'):
            product_data = task.get('result')
        
        if not task_id or not product_data:
            return jsonify({
                'success': False,
                'message': '缺少必要参数'
            })

        if isinstance(product_data, dict) and product_data.get('capture_type') == 'store':
            imported_records = []
            import_errors = []
            for index, item in enumerate(product_data.get('products') or [], start=1):
                try:
                    imported_records.append(_import_capture_product_record(item))
                except Exception as item_error:
                    import_errors.append({
                        'index': index,
                        'url': item.get('url') if isinstance(item, dict) else '',
                        'error': str(item_error),
                    })

            if not imported_records:
                return jsonify({
                    'success': False,
                    'message': f"店铺商品导入失败，失败数量: {len(import_errors)}",
                    'data': {'errors': import_errors}
                })

            return jsonify({
                'success': True,
                'message': f"店铺商品已添加到待上传列表：成功 {len(imported_records)} 个，失败 {len(import_errors)} 个",
                'record_id': imported_records[0]['record_id'],
                'record_name': imported_records[0]['record_name'],
                'data': {
                    'imported_count': len(imported_records),
                    'records': imported_records,
                    'errors': import_errors,
                }
            })
        
        # 验证数据完整性
        title = product_data.get('title', '采集的商品')
        download_path_raw = product_data.get('download_path', '')
        
        # 规范化路径（处理混合分隔符的情况）
        if download_path_raw:
            download_path = os.path.normpath(download_path_raw)
        else:
            download_path = ''
        
        app.logger.info(f"📥 开始导入: {title}")
        app.logger.info(f"📂 原始路径: {download_path_raw}")
        app.logger.info(f"📂 规范化路径: {download_path}")
        app.logger.info(f"📂 路径是否存在: {os.path.exists(download_path) if download_path else 'N/A'}")
        
        # 检查下载目录是否存在
        if not download_path or not os.path.exists(download_path):
            error_msg = f'图片目录不存在: {download_path}'
            app.logger.error(f"❌ {error_msg}")
            
            # 列出父目录内容，帮助调试
            if download_path:
                parent_dir = os.path.dirname(download_path)
                if os.path.exists(parent_dir):
                    try:
                        contents = os.listdir(parent_dir)
                        app.logger.info(f"📂 父目录 {parent_dir} 的内容:")
                        for item in contents[:10]:  # 只显示前10个
                            item_path = os.path.join(parent_dir, item)
                            app.logger.info(f"   - {item} ({'目录' if os.path.isdir(item_path) else '文件'})")
                    except Exception as list_error:
                        app.logger.error(f"❌ 无法列出父目录内容: {list_error}")
                else:
                    app.logger.error(f"❌ 父目录也不存在: {parent_dir}")
            
            return jsonify({
                'success': False,
                'message': error_msg
            })
        
        # 从采集结果中获取SKU信息（包含价格）
        captured_sku_info = product_data.get('sku_info', [])
        captured_main_images = product_data.get('main_images', [])

        # 查找SKU目录（符合拖拽导入格式）
        sku_path = None
        for folder_name in os.listdir(download_path):
            if 'SKU' in folder_name.upper():
                sku_path = os.path.join(download_path, folder_name)
                break
        
        if not sku_path or not os.path.exists(sku_path):
            return jsonify({
                'success': False,
                'message': '未找到SKU文件夹'
            })
        
        def backfill_capture_sku_images(target_dir):
            """When SKU files are missing, rebuild them from local main images or captured URLs."""
            if not captured_sku_info:
                return []

            import requests
            import shutil

            def infer_image_ext(image_url: str) -> str:
                lower_url = (image_url or '').lower()
                if '.png' in lower_url:
                    return '.png'
                if '.gif' in lower_url:
                    return '.gif'
                if '.webp' in lower_url:
                    return '.webp'
                if '.jpeg' in lower_url or '.jpg' in lower_url:
                    return '.jpg'
                return '.jpg'

            def find_local_main_images():
                local_main_dir = None
                for folder_name in os.listdir(download_path):
                    if '主图' in folder_name:
                        local_main_dir = os.path.join(download_path, folder_name)
                        break
                if not local_main_dir or not os.path.exists(local_main_dir):
                    return []
                return list_files_recursive(local_main_dir)

            session = requests.Session()
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
            source_url = product_data.get('url', '')
            if source_url:
                headers['Referer'] = source_url
            session.headers.update(headers)

            restored_files = []
            fallback_main_url = captured_main_images[0] if captured_main_images else ''
            local_main_images = find_local_main_images()

            for idx, captured_sku in enumerate(captured_sku_info, start=1):
                safe_name = re.sub(r'[\\/:*?"<>|]', '_', str(captured_sku.get('name') or f'SKU_{idx}')[:50])
                local_main_file = local_main_images[(idx - 1) % len(local_main_images)] if local_main_images else ''
                remote_img_url = (captured_sku or {}).get('image') or fallback_main_url
                ext = infer_image_ext(remote_img_url or local_main_file)
                file_path = os.path.join(target_dir, f"{idx:02d}_{safe_name}{ext}")

                if os.path.exists(file_path):
                    restored_files.append(file_path)
                    continue

                if local_main_file and os.path.exists(local_main_file):
                    try:
                        shutil.copyfile(local_main_file, file_path)
                        restored_files.append(file_path)
                        continue
                    except Exception as copy_error:
                        app.logger.warning(f"⚠️ 复制主图回填SKU图片失败: idx={idx}, error={copy_error}")

                img_url = remote_img_url
                if not img_url:
                    continue

                if img_url.startswith('//'):
                    img_url = 'https:' + img_url

                try:
                    response = session.get(img_url, timeout=20)
                    if response.status_code == 200 and len(response.content) >= 100:
                        with open(file_path, 'wb') as img_file:
                            img_file.write(response.content)
                        restored_files.append(file_path)
                    else:
                        app.logger.warning(
                            f"⚠️ 无法回填SKU图片: idx={idx}, status={response.status_code}, bytes={len(response.content)}"
                        )
                except Exception as restore_error:
                    app.logger.warning(f"⚠️ 回填SKU图片失败: idx={idx}, error={restore_error}")

            return restored_files
        
        try:
            image_files = list_files_recursive(sku_path)
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'读取图片失败: {str(e)}'
            })
        
        if not image_files:
            app.logger.warning("⚠️ SKU目录中没有图片，尝试根据采集结果回填")
            image_files = backfill_capture_sku_images(sku_path)
        
        if not image_files:
            return jsonify({
                'success': False,
                'message': '未找到图片文件'
            })
        
        # 创建SKU列表（符合拖拽导入格式）
        sku_list = []

        captured_sku_by_index = {}
        for enum_idx, captured_sku in enumerate(captured_sku_info, start=1):
            try:
                sku_index = int(captured_sku.get('index') or enum_idx)
            except Exception:
                sku_index = enum_idx
            captured_sku_by_index.setdefault(sku_index, captured_sku)

        for sku_file in image_files:
            file_name = os.path.basename(sku_file).split('.')[0]
            dir_name = os.path.basename(os.path.dirname(sku_file))
            
            # 提取名称（兼容 "01_xxx" / "SKU_01_xxx" 等命名）
            file_index, name = parse_downloaded_sku_file_name(file_name)
             
            # 从采集结果中查找对应的价格
            sku_price = ''
            matched_sku = captured_sku_by_index.get(file_index) if file_index is not None else None

            if matched_sku:
                sku_price = matched_sku.get('price', '')
                if matched_sku.get('name'):
                    name = str(matched_sku.get('name')).strip()
            else:
                normalized_name = normalize_capture_sku_name(name)
                for captured_sku in captured_sku_info:
                    captured_name = normalize_capture_sku_name(captured_sku.get('name'))
                    if captured_name and (
                        captured_name == normalized_name
                        or captured_name in normalized_name
                        or normalized_name in captured_name
                    ):
                        sku_price = captured_sku.get('price', '')
                        if captured_sku.get('name'):
                            name = str(captured_sku.get('name')).strip()
                        break
             
            sku_list.append({
                'file_name': file_name,
                'dir_name': dir_name,
                'name': name,
                'path': sku_file,
                'price': sku_price  # 从采集结果中获取价格
            })
        
        # 创建Record记录（符合拖拽导入格式）
        folder_name = os.path.basename(download_path)  # 如 "ID-824656038619"
        
        # 删除旧记录（如果存在）
        Record.delete().where(Record.path == download_path).execute()
        
        now = datetime.now()

        inferred_clazz = infer_clazz_from_title(title)

        record = Record.create(
            name=folder_name,
            path=download_path,
            type=2,
            status=0,
            repo=100,
            title=title,
            clazz=inferred_clazz,
            remark='',
            content=json.dumps(sku_list, ensure_ascii=False),
            update_time=now,
            import_source='capture',
            source_url=str(product_data.get('url') or ''),
            managed_files=True,
        )
        
        app.logger.info(f"✅ 商品已自动导入: {folder_name}, Record ID: {record.id}, SKU数量: {len(sku_list)}")
        
        return jsonify({
            'success': True,
            'message': '商品已添加到待上传列表',
            'record_id': record.id,
            'record_name': folder_name,
            'data': {
                'record_id': record.id,
                'record_name': folder_name,
                'sku_count': len(sku_list),
            }
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'导入失败: {str(e)}'
        })

# ========== 商品链接采集 API 结束 ==========



if __name__ == '__main__':
    # 启用Flask调试日志
    logging.basicConfig(level=logging.INFO)
    app.logger.setLevel(logging.INFO)

    if is_sidecar_mode():
        port = get_sidecar_port()
        print(f"🚀 以 Tauri sidecar 模式启动，端口: {port}")
        try:
            _install_sidecar_signal_handlers()
            _start_sidecar_parent_watchdog()
            run_flask_server(port)
        except Exception as sidecar_error:
            print(f"❌ Sidecar 启动失败: {sidecar_error}")
            traceback.print_exc()
            sys.exit(1)
        sys.exit(0)
    
    # 检查logo文件路径
    logo_path = os.path.join(constants.run_path, 'admin', 'images', 'logo.png')
    
    # 如果logo不存在，使用备用路径
    if not os.path.exists(logo_path):
        alternative_paths = [
            os.path.join(os.path.dirname(__file__), 'web', 'admin', 'images', 'logo.png'),
            os.path.join(constants.root_path, 'web', 'admin', 'images', 'logo.png'),
            'web/admin/images/logo.png'
        ]
        
        for alt_path in alternative_paths:
            if os.path.exists(alt_path):
                logo_path = alt_path
                break
        else:
            logo_path = None
    
    try:
        # 🔧 优化GUI初始化，增加异常处理
        gui = Gui(
            title=f'{constants.name}（v{constants.version}）',
            logo=logo_path,
            width=1200,
            height=900,
            app=app
        )

        # Thread(wakeup_listen).start()  # 🔧 暂时禁用自动唤醒功能
        print("💡 启动GUI界面...")
        gui.start()
        
    except Exception as gui_error:
        print(f"❌ GUI启动失败: {gui_error}")
        
        # 如果GUI启动失败，至少启动Flask服务
        try:
            print("💡 请在浏览器中手动打开上述地址使用Web界面")
            run_flask_server(5001)
        except Exception as flask_error:
            print(f"❌ Flask服务启动也失败: {flask_error}")
            
            traceback.print_exc()
            sys.exit(1)

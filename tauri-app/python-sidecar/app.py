# -*- coding: utf-8 -*-

import traceback
import time as system_time
import os
import sys
import html
import importlib
import builtins
import re
import socket
import tempfile
import ctypes
import signal


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
from flask import Flask, request, jsonify
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
# 显式导入：这里原来是 `from src.utils import *`。通配导入有两个实际代价——
#   1) 静态分析（PyInstaller 的 modulegraph、IDE、pyflakes）看不到真实依赖，
#      少一个 hiddenimport 就要等打包后运行才炸；
#   2) 改名/删除 src.utils 里的符号时，app.py 里失效的引用不会被任何工具发现。
# 下面这份清单是用 AST 算出「app.py 真正 Load 到、且 src.utils 提供」的名字（2026-10-01），
# 改 src/utils.py 的对外符号时请同步这里。
from src.utils import (
    _is_upload_busy,
    _normalize_debug_address,
    _verify_debug_browser,
    attach_existing_debug_browser,
    constants,
    discover_debuggable_browsers,
    fetch_cdp_page_targets,
    get_chrome_path,
    get_detail_pic_list,
    get_page,
    get_pic_list,
    is_logged_in_fxg_target_url,
    register_interaction_recovery_hook,
    reset_category_expanded_state,
    select_logged_in_fxg_debug_browser,
    split_number_prefix,
    time,
    timer_end_session,
    timer_record,
    timer_start_session,
    upload_file,
)
_bootstrap_log('import utils done')
_bootstrap_log('import config start')
from src.config import (
    settings_manager,
)
from src import shop_session
from src.sidecar.media_routes import create_media_blueprint
from src.sidecar.whitebg_routes import create_whitebg_blueprint
from src.sidecar.whitebg_service import WhiteBgService
from src.sidecar.responses import api_error, api_ok
from src.sidecar.update_routes import create_update_blueprint
from src.sidecar.xhs_routes import create_xhs_blueprint
from src.sidecar.ops import OpsBrowserPort, create_ops_blueprint
from src.sidecar.ai_routes import create_ai_blueprint
from src.sidecar.title_routes import create_title_blueprint
from src.sidecar.settings_routes import create_settings_blueprint
from src.sidecar.pricing_routes import create_pricing_blueprint
from src.sidecar.shop_accounts import ShopAccountGuard
from src.sidecar.debug_browser_service import BrowserDebugService, DebugBrowserPort
from src.sidecar.debug_browser_routes import create_debug_browser_blueprint
from src.sidecar.shop_service import ShopBrowserPort, ShopSessionService
from src.sidecar.shop_routes import create_shop_blueprint
from src.sidecar.import_routes import create_import_blueprint
from src.sidecar.xhs_batch_service import XhsBatchService
from src.sidecar.xhs_batch_routes import create_xhs_batch_blueprint
from src.sidecar.capture_service import CaptureService
from src.sidecar.capture_routes import create_capture_blueprint
from src.sidecar.taobao_service import TaobaoPublishService
from src.sidecar.taobao_routes import create_taobao_blueprint
from src.sidecar.upload_steps import (
    _PUBLISH_CREATE_URL,
    _PUBLISH_LOGIN_WAIT_SECONDS,
    _configure_sku_entries,
    _configure_sku_structure,
    _dismiss_interfering_overlays,
    _dismiss_pending_browser_alert,
    _fill_category_attributes,
    _fill_price_stock_and_delivery,
    _fill_title_for_record,
    _open_publish_page,
    _prepare_record_assets,
    _select_category_and_prepare_attributes,
    _settle_between_records,
    _submit_publish,
    _upload_main_images,
    _upload_media_assets,
    _wait_login_complete,
)
from src.sidecar.upload_service import UploadBrowserPort, UploadService, UploadStepsPort
from src.sidecar.upload_routes import create_upload_blueprint
_bootstrap_log('import config done')
_bootstrap_log('import ops_engine start')
_bootstrap_log('import ops_engine done')
_bootstrap_log('import professional_title_generator start')
_bootstrap_log('import professional_title_generator done')
_bootstrap_log('import enhanced_category_selector start')
_bootstrap_log('import enhanced_category_selector done')
_bootstrap_log('import protocol_capture optional start')
try:
    from protocol_capture import ProtocolCaptureEngine
    _bootstrap_log('import protocol_capture optional done')
except Exception as _protocol_capture_import_error:
    ProtocolCaptureEngine = None
    _bootstrap_log(f'import protocol_capture optional skipped: {_protocol_capture_import_error}')
import json
import base64
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


def _start_protocol_publish_record(record):
    return None


def _write_protocol_artifact_json(protocol_runtime, stage, name, payload, artifact_type='json'):
    return None


def _finalize_protocol_publish_record(protocol_runtime, *, record, status, current_stage, error_tip, stage_timings, duration_ms):
    return None


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


_BROWSER_DEBUG_DEFAULT_URL = _PUBLISH_CREATE_URL
_DEBUG_BROWSER_HOST = '127.0.0.1'
_DEBUG_BROWSER_PORT_START = 9333
_DEBUG_BROWSER_PORT_END = 9399
_CAPTURE_BROWSER_PORT_START = 9400
_CAPTURE_BROWSER_PORT_END = 9499
# 店铺浏览器端口段，与 src/utils.py 的 _SHOP_BROWSER_PORT_* 必须一致
_SHOP_BROWSER_PORT_START = 9500
_SHOP_BROWSER_PORT_END = 9599
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


def _publish_tasks_running():
    with upload_service.lock:
        running = any(task.get('status') in ('pending', 'running') for task in upload_service.tasks.values())
    with taobao_service.lock:
        running = running or any(task.get('status') in ('pending', 'running')
                                 for task in taobao_service.tasks.values())
    return running


shop_accounts = ShopAccountGuard(
    shop_session=shop_session, has_running_publish_tasks=_publish_tasks_running,
)
# 账户门禁的实现在 src/sidecar/shop_accounts.py。小红书 / 保存等业务域和店铺会话的装配还留在本文件，
# 继续按原来的函数名使用；这些域拆出去时再改为直接依赖 shop_accounts。
_shop_account_lock = shop_accounts.lock
_active_shop_profile = shop_accounts.active_profile
_active_shop_account = shop_accounts.active_account
_with_shop_account_lock = shop_accounts.with_lock
_require_publish_platform = shop_accounts.require_publish_platform


def _find_reusable_logged_in_fxg_browser(verify=False, preferred_profile=None):
    """找一个可复用的「已登录抖店」浏览器。

    ``preferred_profile`` 传当前选中的店铺 profile 目录名。多店铺场景下没有它
    就会出现「界面显示 B 店、实际复用了还开着的 A 店浏览器」，而且不报错。
    """
    if preferred_profile is None:
        preferred_profile = _active_shop_profile()
    browsers = discover_debuggable_browsers(verify=verify)

    # 多店铺同时开着时，复用必须排除「属于别的店铺」的浏览器。
    # 否则「切到 B 店 → B 的浏览器没开 → 复用还开着的 A 店浏览器」会静默发错店，
    # 每一步都成功，事后完全查不出来。
    #
    # 过滤是双向的：不只保护非默认店铺，默认店铺同样不能反过来抢别人的浏览器。
    # 不属于任何已登记店铺的浏览器（比如协议探针那个独立 profile）仍然放行，
    # 保持历史行为——它不归属任何一家店，谈不上串店。
    total_before = len(browsers)
    browsers = shop_session.filter_browsers_for_profile(browsers, preferred_profile)
    filtered_out = total_before - len(browsers)

    targets_by_address = {}
    for browser in browsers:
        address = _normalize_debug_address(browser.get('debug_address') or '')
        if not address:
            continue
        targets_by_address[address] = fetch_cdp_page_targets(address)
    selected = select_logged_in_fxg_debug_browser(
        browsers, targets_by_address, preferred_profile=preferred_profile
    )
    return {
        'status': 'ready' if selected else 'not_found',
        'preferred_profile': preferred_profile,
        'skipped_other_profile_browsers': filtered_out,
        'selected_browser': selected,
        # 调用方常常还要在同一批候选里做别的判断（例如「有抖店页面但停在登录页」）。
        # 把结果带出去，省得再枚举一次进程、再拉一次 target 列表。
        'eligible_browsers': browsers,
        'targets_by_address': targets_by_address,
        'browser_count': len(browsers),
        'target_counts': {
            address: len(targets)
            for address, targets in targets_by_address.items()
        },
    }


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


def _is_local_port_available(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # 这里只检查端口是否空闲；SO_REUSEADDR 在 Windows 上会把已占用端口误判为空闲。
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


browser_debug = BrowserDebugService(
    browser=DebugBrowserPort(
        page_state=lambda: gui,
        active_profile=_active_shop_profile,
        discover_browsers=discover_debuggable_browsers,
        normalize_address=_normalize_debug_address,
        verify_browser=_verify_debug_browser,
        attach_existing=attach_existing_debug_browser,
        open_page=get_page,
        chrome_path=get_chrome_path,
        is_port_available=_is_local_port_available,
        host=_DEBUG_BROWSER_HOST,
        port_start=_DEBUG_BROWSER_PORT_START,
        port_end=_DEBUG_BROWSER_PORT_END,
        default_url=_BROWSER_DEBUG_DEFAULT_URL,
    ),
    repo_root=repo_root,
    get_app_root=get_app_root,
)
# 调试浏览器的状态与实现在 src/sidecar/debug_browser_service.py。店铺会话 / 运营闭环的端口装配、
# 以及 _attach_reusable_logged_in_fxg_browser 还在用下面这几个旧函数名；上传已直接依赖 browser_debug（经 UploadBrowserPort）。
_get_current_browser_tab = browser_debug.get_current_tab
_snapshot_browser_context = browser_debug.snapshot_context
_set_browser_debug_instance = browser_debug.set_browser_instance
_find_debug_browser_process = browser_debug.find_browser_process
_get_gui_page_debug_address = browser_debug.gui_page_debug_address


shop_session_service = ShopSessionService(
    accounts=shop_accounts,
    browser=ShopBrowserPort(
        page_state=lambda: gui,
        open_page=get_page,
        normalize_address=_normalize_debug_address,
        gui_page_debug_address=_get_gui_page_debug_address,
        find_browser_process=_find_debug_browser_process,
        find_reusable_browser=_find_reusable_logged_in_fxg_browser,
        set_debug_browser_instance=_set_browser_debug_instance,
        host=_DEBUG_BROWSER_HOST,
        shop_port_start=_SHOP_BROWSER_PORT_START,
        shop_port_end=_SHOP_BROWSER_PORT_END,
    ),
    shop_session=shop_session,
)


taobao_service = TaobaoPublishService(
    record_model=Record, repo_root=repo_root, accounts=shop_accounts, shop_service=shop_session_service,
    normalize_debug_address=_normalize_debug_address, resolve_data_file=resolve_data_file,
    bootstrap_log=_bootstrap_log,
)


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
                'status': record.status,
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
            'white_bg_path': record.white_bg_path or '',
            'clazz': clazz_value,
            'remark': record.remark,
            # 已删除：'notice'（购买须知）。界面已按用户要求撤掉该字段，桌面请求也不再
            # 转发它，回传就是一个没人接的键。ORM 里那一列仍保留（删列是破坏性操作，
            # 见 src/orm.py 的说明），只是代码不再使用。
            'content': sku_list
        })
    except Exception as e:
        traceback.print_exc()
        return api_error(msg=f'操作失败：{str(e)}')


@app.delete('/delete_all')
def delete_all():
    deleted_count = 0
    try:
        records = list(Record.select().order_by(Record.id))
        for record in records:
            _delete_product_record(record)
            deleted_count += 1
        return api_ok(msg='清空成功！')
    except Exception as e:
        app.logger.exception('清空产品失败，已删除 %s 个', deleted_count)
        return api_error(msg=f'清空中止，已删除 {deleted_count} 个商品，其余记录保留：{str(e)}')


def _product_edit_revision(row):
    """发布会消费的商品资料指纹；不含登录信息，也不依赖分钟级更新时间。"""
    import hashlib
    # 指纹里已去掉 'notice'：流水线不再消费这一列（界面不收集、不写发布表单），
    # 把它算进来只会让"改了须知"变成一次没有意义的「资料已改变」拒绝。
    fields = ('id', 'name', 'path', 'title', 'remark', 'repo', 'clazz', 'content')
    if any(field not in row for field in fields):
        raise ValueError('商品资料不完整，无法确认上传版本')
    payload = {field: row[field] for field in fields}
    payload['white_bg_path'] = row.get('white_bg_path') or ''
    if row.get('captured_attributes') not in (None, ''):
        attributes = _load_capture_attributes().normalize(row['captured_attributes'])
        if attributes is not None:
            payload['captured_attributes'] = attributes
    if isinstance(payload['content'], str):
        payload['content'] = json.loads(payload['content'])
    if not isinstance(payload['content'], list):
        raise ValueError('商品 SKU 资料不是有效列表')
    for field in ('repo', 'clazz'):
        if payload[field] is not None:
            payload[field] = int(payload[field])
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _require_product_revision(row, expected):
    if not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
        return jsonify(success=False, msg='商品资料版本无效，请重新保存后上传'), 400
    try:
        actual = _product_edit_revision(row)
    except (ValueError, TypeError) as exc:
        return jsonify(success=False, msg='当前商品资料无法校验：{}'.format(exc)), 503
    if actual != expected:
        return jsonify(success=False, msg='商品资料已改变，未启动上传，请重新保存后再试'), 409
    return None


def _record_edit_blocked(record_id):
    """禁止改动运行任务正在消费的记录；批量任务覆盖全部记录。"""
    for tasks, lock in ((upload_service.tasks, upload_service.lock), (taobao_service.tasks, taobao_service.lock)):
        with lock:
            for task in tasks.values():
                if task.get('status') not in ('pending', 'running'):
                    continue
                scope = task.get('record_id')
                if scope is None:
                    return jsonify(success=False, msg='批量发布任务运行中，请完成或取消后再保存'), 409
                try:
                    same_record = int(scope) == record_id
                except (TypeError, ValueError):
                    return jsonify(success=False, msg='发布任务所属商品无法确认，请等任务结束后再保存'), 409
                if same_record:
                    return jsonify(success=False, msg='当前商品正在发布，请完成或取消后再保存'), 409
    return None


def _validated_product_edits(data, record, for_publish=False):
    """全部验证成功后才返回更新值，不修改 ORM 对象，不制造零价格。"""
    import math
    from decimal import Decimal

    def integer(value, label, nullable=False):
        if value is None and nullable:
            return None
        if isinstance(value, bool):
            raise ValueError('{}必须是非负整数'.format(label))
        if isinstance(value, str):
            value = value.strip()
            if not value or not value.isascii() or not value.isdigit():
                raise ValueError('{}必须是非负整数'.format(label))
            value = int(value)
        if not isinstance(value, int) or value < 0:
            raise ValueError('{}必须是非负整数'.format(label))
        return value

    updates = {}
    # 已删除白名单里的 ('notice', '购买须知')：该字段已退役（界面不收集、流水线不消费），
    # 留着它等于继续接受一个没人能给出、也没人会读的键。
    for field, label in (('title', '标题'), ('remark', '备注')):
        if field in data:
            if not isinstance(data[field], str):
                raise ValueError('{}必须是文本'.format(label))
            updates[field] = data[field].strip()
    for field, label in (('repo', '库存'), ('clazz', '商品种类')):
        if field in data:
            updates[field] = integer(data[field], label, nullable=not for_publish)

    if for_publish:
        if not updates.get('title') or updates.get('repo') is None or updates.get('clazz') is None:
            raise ValueError('上传前必须提供当前标题、商品种类和库存')
        if 'attr_size' not in data:
            raise ValueError('上传前必须提供当前完整 SKU 列表')

    if 'attr_size' in data:
        count = integer(data['attr_size'], 'SKU数量')
        content = record.content
        if isinstance(content, str):
            content = json.loads(content)
        if not isinstance(content, list) or any(not isinstance(sku, dict) for sku in content):
            raise ValueError('当前商品 SKU 数据不是有效列表')
        content = [dict(sku) for sku in content]
        paths = [sku.get('path') for sku in content]
        if any(not isinstance(p, str) or not p for p in paths) or len(set(paths)) != len(paths):
            raise ValueError('当前商品 SKU 图片来源为空或重复，无法准确保存')
        if count != len(content):
            raise ValueError('SKU列表已变化，请重新加载当前商品后再保存')
        by_path = {sku['path']: sku for sku in content}
        seen = set()
        names = set()
        if for_publish and not count:
            raise ValueError('上传前至少需要一条 SKU')
        for i in range(1, count + 1):
            path_key, name_key, price_key = 'attr_path_{}'.format(i), 'attr_name_{}'.format(i), 'attr_price_{}'.format(i)
            source = data.get(path_key)
            if not isinstance(source, str) or source not in by_path or source in seen:
                raise ValueError('第{}条SKU来源不属于当前商品或重复，未保存'.format(i))
            seen.add(source)
            if name_key not in data or not isinstance(data[name_key], str):
                raise ValueError('第{}条SKU名称必须是文本'.format(i))
            name = data[name_key].strip()
            if for_publish and not name:
                raise ValueError('第{}条SKU名称不能为空'.format(i))
            normalized = ' '.join(name.split()).lower()
            if for_publish and normalized in names:
                raise ValueError('SKU名称重复，请先修改后再上传')
            names.add(normalized)
            value = data.get(price_key)
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise ValueError('第{}条SKU售价必须是有效数值'.format(i))
            try:
                price = float(value)
            except (ValueError, TypeError) as exc:
                raise ValueError('第{}条SKU售价必须是有效数值'.format(i)) from exc
            if not math.isfinite(price) or price < 0 or (for_publish and price <= 0):
                raise ValueError('第{}条SKU售价必须{}有效数值'.format(i, '是大于0的' if for_publish else '是非负'))
            if for_publish and Decimal(str(price)).normalize().as_tuple().exponent < -2:
                raise ValueError('第{}条SKU售价最多保留两位小数'.format(i))
            by_path[source]['name'] = name
            by_path[source]['price'] = price
            remark_key = 'attr_remark_{}'.format(i)
            if remark_key in data:
                if not isinstance(data[remark_key], str):
                    raise ValueError('第{}条SKU备注必须是文本'.format(i))
                # SKU 自己的备注；缺省保留原值，绝不用商品级 remark 补齐或覆盖。
                by_path[source]['remark'] = data[remark_key].strip()
            pair_key = 'attr_pair_count_{}'.format(i)
            if pair_key in data:
                if not isinstance(data[pair_key], str):
                    raise ValueError('第{}条SKU双数必须是文本'.format(i))
                specs = by_path[source].get('spec_values') or {}
                if not isinstance(specs, dict):
                    raise ValueError('第{}条SKU规格资料格式无效'.format(i))
                specs = dict(specs)
                pair_count = data[pair_key].strip()
                if pair_count:
                    specs['双数'] = pair_count
                else:
                    specs.pop('双数', None)
                by_path[source]['spec_values'] = specs
        updates['content'] = json.dumps(content, ensure_ascii=False)
    elif any(str(key).startswith('attr_') for key in data):
        raise ValueError('保存 SKU 必须提供完整数量和行数据')
    return updates


@app.post('/save_info')
@_with_shop_account_lock
def save_info():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        return jsonify(success=False, msg='保存需要有效的 JSON 对象'), 400
    record_id = data.get('_id')
    if isinstance(record_id, str) and record_id.isascii() and record_id.isdigit():
        record_id = int(record_id)
    if isinstance(record_id, bool) or not isinstance(record_id, int) or record_id <= 0:
        return jsonify(success=False, msg='请选择有效的商品编号'), 400
    for_publish = data.get('for_publish', False)
    if not isinstance(for_publish, bool):
        return jsonify(success=False, msg='for_publish 必须是布尔值'), 400
    if for_publish:
        platform = data.get('platform')
        if platform not in ('douyin', 'taobao') or not isinstance(data.get('account_profile'), str) or not data['account_profile'].strip():
            return jsonify(success=False, msg='上传前保存必须绑定当前店铺账户'), 400
        error = _require_publish_platform(platform, data['account_profile'])
        if error is not None:
            return error
    error = _record_edit_blocked(record_id)
    if error is not None:
        return error
    try:
        record = Record.get_by_id(record_id)
    except Record.DoesNotExist:
        return jsonify(success=False, msg='商品不存在，请刷新商品列表'), 404
    try:
        updates = _validated_product_edits(data, record, for_publish=for_publish)
        if for_publish and platform == 'taobao':
            # 使用填写入口相同的本地契约；无效标题不保存，也不启动浏览器。
            taobao_service.product_request_payload({'title': updates['title']})
        saved_row = dict(record.__data__)
        saved_row.update(updates)
        revision = _product_edit_revision(saved_row)
    except (ValueError, TypeError) as exc:
        return jsonify(success=False, msg=str(exc)), 400
    try:
        for field, value in updates.items():
            setattr(record, field, value)
        record.update_time = time.now()
        if record.save() != 1:
            raise RuntimeError('商品未写入数据库，可能已被删除')
        return api_ok(msg='保存成功！', data={
            'id': record.id, 'update_time': record.update_time.strftime('%Y-%m-%d %H:%M'),
            'record_revision': revision,
        })
    except Exception as exc:
        traceback.print_exc()
        return jsonify(success=False, msg='数据库保存失败：{}'.format(exc)), 500


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


register_interaction_recovery_hook(_dismiss_interfering_overlays)


def _xpath_text_literal(value):
    value = str(value)
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ', "\'", '.join([f"'{part}'" for part in parts]) + ")"


def _protocol_cdp_port_candidates():
    ports = [9222, 9223]
    ports.extend(range(_DEBUG_BROWSER_PORT_START, _DEBUG_BROWSER_PORT_END + 1))
    ports.extend(range(_CAPTURE_BROWSER_PORT_START, _CAPTURE_BROWSER_PORT_END + 1))
    # 每份店铺账号信息各占一个端口（src/utils.py 的 9500-9599），漏了这段
    # 非默认店铺的浏览器就扫不到。
    ports.extend(range(_SHOP_BROWSER_PORT_START, _SHOP_BROWSER_PORT_END + 1))

    seen = set()
    ordered_ports = []
    for port in ports:
        if port in seen:
            continue
        seen.add(port)
        ordered_ports.append(port)
    return ordered_ports


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
    from pathlib import Path
    import stat

    # 空字符串不能经 abspath 变成工作目录；Shell 文件操作也不能接收通配符。
    if not isinstance(path, str) or not path.strip() or not Path(path).is_absolute():
        raise ValueError('删除路径必须是明确的绝对路径')
    if any(character in path for character in ('\0', '*', '?')):
        raise ValueError('删除路径不能含空字符或通配符')
    target = Path(os.path.normpath(path))
    if target == target.parent:
        raise ValueError('拒绝移动磁盘或系统根目录到回收站')
    # 回收站没有可靠的网络共享撤销语义，不转为永久删除。
    if os.name == 'nt' and target.drive.startswith('\\\\'):
        raise ValueError('网络共享目录不支持回收站删除')
    for part in (target, *target.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue  # 已在资源管理器中删除的文件，仍可移除列表记录。
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('拒绝删除符号链接或目录联接，请使用商品原始目录')
    return str(target)


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
    if os.path.lexists(target_path):
        raise OSError('回收站操作结束后文件仍然存在，未删除商品记录')
    return True


def _delete_product_record(record) -> None:
    managed = _is_capture_managed_record(record)
    target_path = None
    if managed:
        target_path = _assert_safe_recycle_target(record.path)
        if os.path.normcase(os.path.basename(target_path)) != os.path.normcase(record.name):
            raise ValueError('商品目录名称与记录不一致，未删除文件')
        if os.path.exists(target_path) and not os.path.isdir(target_path):
            raise ValueError('采集商品路径不是文件夹，未删除文件')
    # 先在事务中确认数据库可写；回收失败时回滚记录，提交前不会对外显示删除成功。
    with Record._meta.database.atomic('IMMEDIATE'):
        if Record.delete_by_id(record.id) != 1:
            raise ValueError('商品记录已变化，请刷新列表')
        if managed:
            moved = _move_path_to_recycle_bin(target_path)
    if managed:
        app.logger.info('采集商品已删除，目录%s: %s', '已移入回收站' if moved else '原已不存在', target_path)


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


# ====== 设置管理 API ======


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


# 🚀 新增：成本项目精细化管理API


# 🚀 新增：模板管理API


# 🚀 新增：智能价格计算API

# 🚀 新增：AI配置管理API


# 🚀 新增：毛利率配置API


# ========== 商品链接采集 API ==========


def _load_capture_attributes():
    """采集资料与发布共用纯属性契约；不初始化浏览器或读取账户。"""
    if not getattr(sys, 'frozen', False):
        package_root = os.path.join(repo_root, 'taobao-publisher')
        if package_root not in sys.path:
            sys.path.insert(0, package_root)
    from taobao_publish import captured_attributes
    return captured_attributes


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


# ========== 商品链接采集 API 结束 ==========

# 图片接口只在这里组装依赖，HTTP 适配和任务状态由各自模块负责。
# 模型仍按需加载；与账户切换、发布、选图使用同一把账户锁。
whitebg_service = WhiteBgService(lambda: normalize_save_path('uploads/products'))
app.extensions['whitebg_service'] = whitebg_service


def _active_update_tasks():
    with upload_service.lock:
        douyin = sum(t.get('status') in ('pending', 'running') for t in upload_service.tasks.values())
    with taobao_service.lock:
        taobao = sum(t.get('status') in ('pending', 'running') for t in taobao_service.tasks.values())
    with capture_service.lock:
        capture = int(capture_service.running_task_id is not None)
    return {'capture': capture, 'douyin_publish': douyin, 'taobao_publish': taobao,
            'image_processing': whitebg_service.active_task_count()}


capture_service = CaptureService(
    record_model=Record, logger=app.logger, protocol_capture_engine=_PROTOCOL_CAPTURE_ENGINE,
    find_cdp_port=_find_cdp_port, load_capture_attributes=_load_capture_attributes,
    normalize_save_path=normalize_save_path, is_local_port_available=_is_local_port_available,
    normalize_debug_address=_normalize_debug_address, verify_debug_browser=_verify_debug_browser,
    discover_browsers=discover_debuggable_browsers, debug_host=_DEBUG_BROWSER_HOST,
    capture_port_start=_CAPTURE_BROWSER_PORT_START, capture_port_end=_CAPTURE_BROWSER_PORT_END,
)


upload_service = UploadService(
    record_model=Record, accounts=shop_accounts, settings_manager=settings_manager, shop_session=shop_session,
    logger=app.logger, get_app_root=get_app_root, app_file=__file__, repo_root=repo_root,
    stage_timing_log_path=_UPLOAD_STAGE_TIMING_LOG_PATH,
    browser=UploadBrowserPort(
        page_state=lambda: gui,
        open_page=get_page,
        get_pic_list=get_pic_list,
        get_detail_pic_list=get_detail_pic_list,
        reset_category_expanded_state=reset_category_expanded_state,
        timer_start_session=timer_start_session,
        timer_end_session=timer_end_session,
        timer_record=timer_record,
        time=time,
        normalize_debug_address=_normalize_debug_address,
        discover_debuggable_browsers=discover_debuggable_browsers,
        fetch_cdp_page_targets=fetch_cdp_page_targets,
        is_logged_in_fxg_target_url=is_logged_in_fxg_target_url,
        attach_reusable_browser=_attach_reusable_logged_in_fxg_browser,
        find_cdp_port=_find_cdp_port,
        record_automation_error=browser_debug.record_automation_error,
        latest_error_after=browser_debug.latest_error_after,
    ),
    steps=UploadStepsPort(
        settle_between_records=_settle_between_records,
        wait_login_complete=_wait_login_complete,
        prepare_record_assets=_prepare_record_assets,
        dismiss_pending_browser_alert=_dismiss_pending_browser_alert,
        open_publish_page=_open_publish_page,
        fill_title_for_record=_fill_title_for_record,
        select_category_and_prepare_attributes=_select_category_and_prepare_attributes,
        fill_category_attributes=_fill_category_attributes,
        upload_main_images=_upload_main_images,
        upload_media_assets=_upload_media_assets,
        configure_sku_entries=_configure_sku_entries,
        configure_sku_structure=_configure_sku_structure,
        fill_price_stock_and_delivery=_fill_price_stock_and_delivery,
        submit_publish=_submit_publish,
        create_url=_PUBLISH_CREATE_URL,
        login_wait_seconds=_PUBLISH_LOGIN_WAIT_SECONDS,
    ),
)


xhs_batch = XhsBatchService(
    record_model=Record, get_pic_list=get_pic_list, shop_session=shop_session,
    host=_DEBUG_BROWSER_HOST, port_start=_SHOP_BROWSER_PORT_START, port_end=_SHOP_BROWSER_PORT_END,
)


app.register_blueprint(create_update_blueprint(_active_update_tasks))


def _xhs_account_guard():
    """小红书路线的账户门：当前账户不是 xiaohongshu 就拒绝进入。"""
    return _require_publish_platform('xiaohongshu')


def _xhs_runner_with_account_port(payload):
    from src.sidecar.xhs_routes import default_runner as _runner
    payload = dict(payload or {})
    payload['port'] = xhs_batch.debug_port(payload.get('port'))
    return _runner(payload)


def _xhs_status_probe_with_account_port():
    from src.sidecar.xhs_routes import default_status_probe as _probe
    return _probe(port=xhs_batch.debug_port())


app.register_blueprint(create_xhs_blueprint(
    account_guard=_xhs_account_guard,
    runner=_xhs_runner_with_account_port,
    status_probe=_xhs_status_probe_with_account_port,
))
app.register_blueprint(create_media_blueprint(
    record_model=Record, active_account=_active_shop_account, resolve_data_file=resolve_data_file,
    edit_blocked=_record_edit_blocked, product_revision=_product_edit_revision,
    account_lock=_shop_account_lock, whitebg=whitebg_service,
))
app.register_blueprint(create_whitebg_blueprint(
    record_model=Record, account_lock=_shop_account_lock, service=whitebg_service,
))
app.register_blueprint(create_ops_blueprint(
    record_model=Record,
    browser=OpsBrowserPort(
        get_current_tab=_get_current_browser_tab,
        snapshot_context=_snapshot_browser_context,
        attach_reusable_tab=_attach_reusable_logged_in_fxg_browser,
        find_reusable_browser=_find_reusable_logged_in_fxg_browser,
        discover_browsers=discover_debuggable_browsers,
        upload_file=upload_file,
        is_upload_busy=_is_upload_busy,
        page_state=gui,
    ),
    is_sidecar_mode=is_sidecar_mode,
    get_sidecar_port=get_sidecar_port,
    repo_root=repo_root,
))
app.register_blueprint(create_ai_blueprint())
app.register_blueprint(create_title_blueprint(record_model=Record))
app.register_blueprint(create_settings_blueprint(get_runtime_data_path=get_runtime_data_path))
app.register_blueprint(create_pricing_blueprint(
    record_model=Record, get_runtime_data_path=get_runtime_data_path,
))
app.register_blueprint(create_debug_browser_blueprint(service=browser_debug))
app.register_blueprint(create_shop_blueprint(
    accounts=shop_accounts, service=shop_session_service, shop_session=shop_session,
))
app.register_blueprint(create_import_blueprint(
    record_model=Record, split_number_prefix=split_number_prefix,
))
app.register_blueprint(create_xhs_batch_blueprint(
    record_model=Record, service=xhs_batch, accounts=shop_accounts,
))
app.register_blueprint(create_capture_blueprint(
    service=capture_service, normalize_save_path=normalize_save_path, get_app_root=get_app_root,
    settings_manager=settings_manager,
))
app.register_blueprint(create_taobao_blueprint(
    service=taobao_service, accounts=shop_accounts, record_model=Record,
    resolve_data_file=resolve_data_file, require_product_revision=_require_product_revision,
))
app.register_blueprint(create_upload_blueprint(
    service=upload_service, accounts=shop_accounts, record_model=Record,
    require_product_revision=_require_product_revision,
))


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

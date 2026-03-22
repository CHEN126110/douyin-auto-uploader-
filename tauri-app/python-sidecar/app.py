# -*- coding: utf-8 -*-

import traceback
import time as system_time
import os
import sys
import copy
import uuid

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

if getattr(sys, 'frozen', False):
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
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

# 开发模式下，sidecar 位于 tauri-app/python-sidecar，需要把项目根目录加入 sys.path
if not getattr(sys, 'frozen', False):
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from src.orm import Record
from src.utils import *
from src.config import settings_manager
from src.gui import Gui
from src.thread import Thread
from src.professional_title_generator import get_professional_generator, ProductInfo as ProfessionalProductInfo
from src.enhanced_category_selector import smart_select_category
import json
import base64
from datetime import datetime, timedelta
import threading


# 🔧 获取程序根目录（支持打包后的可执行文件）
def get_app_root():
    """
    获取应用程序的根目录
    - 开发环境：返回脚本所在目录
    - 打包后（PyInstaller）：返回可执行文件所在目录
    """
    if getattr(sys, 'frozen', False):
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


_BROWSER_DEBUG_DEFAULT_URL = 'https://fxg.jinritemai.com/login/common'
_BROWSER_DEBUG_MAX_EVENTS = 200
_BROWSER_DEBUG_MAX_SESSIONS = 8
_browser_debug_lock = threading.Lock()
_browser_debug_state = {
    'current_session_id': None,
    'sessions': {},
    'last_error': None,
}


def is_sidecar_mode() -> bool:
    return os.environ.get('SIDECAR_MODE') == '1'


def get_sidecar_port() -> int:
    try:
        return int(os.environ.get('SIDECAR_PORT', '5001'))
    except ValueError:
        return 5001


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
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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


def _get_current_browser_tab(create_if_missing=False, url=None, navigate=False):
    meta = {
        'created_browser': False,
        'reused_browser': False,
        'navigated': False,
    }
    target_url = url or _BROWSER_DEBUG_DEFAULT_URL

    if not gui.page:
        if not create_if_missing:
            return None, meta
        gui.page = get_page(target_url)
        meta['created_browser'] = True
        meta['navigated'] = True

    try:
        tab = gui.page.get_tab(gui.page.latest_tab)
        meta['reused_browser'] = not meta['created_browser']
    except Exception:
        if not create_if_missing:
            raise
        gui.page = get_page(target_url)
        meta['created_browser'] = True
        meta['reused_browser'] = False
        meta['navigated'] = True
        tab = gui.page.get_tab(gui.page.latest_tab)

    if navigate and url:
        tab.get(url)
        meta['navigated'] = True

    return tab, meta


def _collect_browser_page_bits(tab, max_fields=30, max_controls=30):
    script = """
    const maxFields = %d;
    const maxControls = %d;
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
    return {
      url: location.href,
      title: document.title,
      ready_state: document.readyState,
      scroll: { x: window.scrollX, y: window.scrollY },
      field_items: fieldItems,
      control_items: controlItems
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
    url = (data.get('url') or '').strip() or None

    session = _create_browser_debug_session(label) if new_session else _get_browser_debug_session(create=True, label=label)

    try:
        tab, meta = _get_current_browser_tab(
            create_if_missing=create_browser,
            url=url,
            navigate=navigate
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


@app.get('/api/debug/browser/session')
def debug_browser_session():
    session = _get_browser_debug_session(create=False)
    return api_ok('Current browser debug session loaded.', data={
        'session': _serialize_browser_debug_session(session, include_events=True, recent_event_count=30),
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
        # 过滤掉要删除的 SKU
        sku_list = [sku for sku in sku_list if sku['path'] != sku_path]
        record.content = json.dumps(sku_list)
        record.save()

        return api_ok('SKU 删除成功')
    except Exception as e:
        traceback.print_exc()
        return api_error(f'删除失败：{str(e)}')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.get_json().get('username')
        password = request.get_json().get('password')
        remember = request.get_json().get('remember') == 'on'
        if username == 'your_username' and password == 'your_password':
            update_payload(username, remember)
            return api_ok('登录成功！')
        else:
            return api_error('账号密码不正确！')
    else:
        # gui.window.label.hide()  # 移除这行代码
        return render_template('login.html')


@app.delete('/logout')
def logout():
    try:
        update_payload(None, True)
        return api_ok('注销成功！')
    except:
        pass
    return api_error('注销失败！')


@app.get('/')
def index():
    record_list = []
    for record in Record.select().execute():
        arr = record.name.split('_')
        record_list.append({
            'id': record.id,
            'name': record.name if len(arr) < 4 else arr[3],
            'update_time': record.update_time.strftime('%Y-%m-%d %H:%M')
        })
    return render_template('/view/operate/index.html', ctx=constants, record_list=record_list)


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
        Record.delete().execute()
        return api_ok(msg='清空成功！')
    except:
        pass
    return api_error(msg='清空失败！')


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


@app.post('/start')
def start():
    msg_list = []
    try:
        # 🚀 启动上传流程
        print("🚀 开始上传流程...")

        request_data = request.get_json(silent=True) or {}
        record_id = request_data.get('record_id')

        if record_id:
            record = Record.get_or_none(Record.id == record_id)
            if not record:
                return api_error(msg='指定产品不存在')
            record_list = [record]
        else:
            record_list = list(Record.select().execute())

        if len(record_list) == 0:
            return api_error(msg='没有待上传数据！')

        user_settings = settings_manager.get_settings()
        automation_config = settings_manager.normalize_automation_config(user_settings.automation_config)
        shipping_template_name = str(automation_config.get('shipping_template') or '中通包邮').strip() or '中通包邮'
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
        
        # 确保 gui.page 存在且不为 None
        if not gui.page:
            gui.page = get_page('https://fxg.jinritemai.com/login/common')
            login_ok = False
            for _ in range(100):
                if '/homepage' in gui.page.url:
                    login_ok = True
                    break
                time.sleep(0.3)
            if not login_ok:
                return api_error('超时未登录！！！')
        
        try:
            main_tab = gui.page.get_tab(gui.page.latest_tab)
        except:
            gui.page = get_page('https://fxg.jinritemai.com/login/common')
            login_ok = False
            for _ in range(100):
                if '/homepage' in gui.page.url:
                    login_ok = True
                    break
                time.sleep(0.3)
            if not login_ok:
                return api_error('超时未登录！！！')
            main_tab = gui.page.get_tab(gui.page.latest_tab)
        gui.page.close_tabs(main_tab, others=True)
        for record in record_list:
            record_ok = False
            error_tip = ''
            current_stage = 'prechecks'

            try:
                if not record.title:
                    error_tip = '标题为空！！！'
                    continue
                if not record.clazz:
                    error_tip = '类目为空！！！'
                    continue
                if not str(record.repo):
                    error_tip = '库存为空！！！'
                    continue
                try:
                    main_pic_list = get_pic_list(record, '800')
                except:
                    error_tip = '未找到主图或者主图不全！！！'
                    continue
                try:
                    sub_pic_list = get_pic_list(record, '750')
                    # 🔧 ID模式下，如果返回空列表，说明没有3:4主图，这是正常的
                    if record.type == 2 and len(sub_pic_list) == 0:
                        print("ID模式：没有3:4主图，将使用平台自带的1:1导入功能")
                except:
                    # 标准模式下仍然需要3:4主图
                    if record.type == 1:
                        error_tip = '未找到4:3主图或者4:3主图不全！！！'
                        continue
                    else:
                        # ID模式下出现异常，设置为空列表
                        sub_pic_list = []
                        print("ID模式：获取3:4主图时出现异常，将使用平台自带的1:1导入功能")
                try:    
                    detail_pic_list = get_detail_pic_list(record)
                except:
                    error_tip = '未找到详情图！！！'
                    continue
                diaopai_pic = get_diaopai_pic(record)
                
                # 获取视频文件
                my_video = get_my_video(record)

                sku_list = json.loads(record.content)
                if len(sku_list) == 0:
                    error_tip = '未找到sku信息！！！'
                    continue
                sku_flag = False
                for sku_item in sku_list:
                    # 🔧 修复：价格可以为0，只需要检查name是否存在，price是否是数字
                    if not sku_item['name'] or sku_item['price'] is None:
                        sku_flag = True
                        break
                    # 检查price是否是有效数字（包括0）
                    try:
                        float(sku_item['price'])
                    except (ValueError, TypeError):
                        sku_flag = True
                        break
                if sku_flag:
                    error_tip = 'sku信息不全！！！'
                    continue
                white_pic = get_white_pic(record, sku_list)

                print('打开商品发布页面...')
                current_stage = 'open_publish_page'
                main_tab.handle_alert(next_one=True)
                main_tab.get('https://fxg.jinritemai.com/ffa/g/create')
                ready = False
                for _ in range(75):
                    if main_tab.ele('xpath://input[@id="pg-title-input"]', timeout=0.2) or \
                       main_tab.ele('xpath://span[text()="主图上传"]', timeout=0.2) or \
                       main_tab.ele('xpath://button//span[text()="下一步"]', timeout=0.2):
                        ready = True
                        break
                    time.sleep(0.2)
                if not ready:
                    return api_error('页面未就绪，请稍后重试')

                try:
                    main_tab.ele('xpath://span[text()="重新发布"]/../..', timeout=3).click(by_js=True)
                    time.sleep(1)
                    main_tab.ele('xpath://*[text()="我知道了"]', timeout=1)
                    time.sleep(0.5)
                except:
                    pass
                input_element = main_tab.ele('xpath://input[@placeholder="请输入2-60个字符（1-30个汉字）"]')
                input_element.click()
                time.sleep(0.1)
                input_element.input(record.title)
                time.sleep(0.1)
                try:
                    main_tab.remove_ele(main_tab.ele('xpath://div[contains(@class,"index_DragController__")]', timeout=1))
                except:
                    pass

                current_stage = 'upload_main_images'
                upload_file(main_tab, main_pic_list, '主图', error_size='长宽比需为1:1' if record.type == 2 else None)

                # 🚀 使用增强的类目选择器
                print(f'开始智能类目选择: {wazi_dict.get(record.clazz)}')
                current_stage = 'select_category'
                if not smart_select_category(main_tab, record.clazz):
                    print("❌ 类目选择失败，已尝试推荐与手动选择。请检查页面结构或账号资质。")
                    raise Exception("类目选择失败")
                else:
                    print("✅ 智能类目选择成功")

                gen_btn = main_tab.ele(
                    'xpath://div[@data-better-log-outer-key="short_product_name"]'
                    + '//span[contains(@class,"ecom-g-input-suffix")]//img',
                    timeout=3
                )

                # 2. 如果找到了，就点击；否则打印提示
                if gen_btn:
                    # 可选：滚动到中央，确保可见
                    gen_btn.scroll.to_center()
                    # 点击
                    gen_btn.click(by_js=True)
                    print("已点击生成短标题按钮")
                else:
                    print("未找到生成短标题按钮，检查 XPath 或页面结构是否变化")
                
                try:
                    main_tab.ele('xpath://*[text()="我知道了"]', timeout=1)
                except:
                    pass

                # 处理吊牌识别（仅非船袜类目）
                if diaopai_pic and str(record.clazz) != '0':
                    print('处理其他类目吊牌上传...')
                    upload_file(main_tab, [diaopai_pic], '吊牌')
                    for _ in range(30):
                        if main_tab.ele('吊牌识别成功', timeout=0.1):
                            break
                        if main_tab.ele('吊牌识别失败', timeout=0.1):
                            break
                        time.sleep(0.1)

                # 根据当前页面类目处理属性填写，避免 record.clazz 与二级页实际类目不一致
                current_stage = 'fill_category_attributes'
                current_category_text = get_current_category_text(main_tab)
                current_sock_height = infer_sock_height_value(current_category_text, record.clazz)
                is_ship_socks = '船袜' in current_category_text
                print(f'当前页面类目: {current_category_text or "未识别"}')
                if current_sock_height:
                    print(f'当前页面筒高目标值: {current_sock_height}')

                if is_ship_socks:  # 船袜类目
                    print('处理船袜类目属性...')
                    main_tab.ele('xpath://div[@attr-field-id="主图3:4"]').scroll.to_see()
                    time.sleep(0.1)
                    
                    # 船袜类目专门处理品牌和材质
                    select_text(main_tab, '品牌', '无品牌')
                    time.sleep(0.1)
                    # 针对船袜类目的材质输入框处理
                    try:
                        material_input = main_tab.ele('xpath://div[@attr-field-id="材质"]//input[@placeholder="请输入"]')
                        material_input.scroll.to_center()
                        material_input.click()
                        time.sleep(0.1)
                        material_input.input('棉')
                        time.sleep(0.1)
                        print('船袜类目：已填写材质为棉')
                    except Exception as e:
                        print(f'船袜类目材质填写失败: {str(e)}')
                        
                elif diaopai_pic:  # 其他类目且有吊牌
                    print('处理其他类目属性（有吊牌）...')
                    main_tab.ele('xpath://div[@attr-field-id="主图3:4"]').scroll.to_see()
                    time.sleep(0.1)
                    
                    # 删除现有面料材质，让吊牌识别结果生效
                    ss = main_tab.eles('xpath://div[@attr-field-id="面料材质"]//span[contains(@class,"styles_del__")]', timeout=1)
                    for del_btn in ss:
                        del_btn.click(by_js=True)   
                        time.sleep(0.3)
                    
                    # 填写其他必要属性
                    select_text(main_tab, '品牌', '无品牌')
                    select_text(main_tab, '适用人群', '成人')
                    select_text(main_tab, '适用性别', get_sex(record.title))
                    if current_sock_height:
                        select_text(main_tab, '筒高', current_sock_height)
                    
                else:  # 其他类目且没有吊牌
                    print('处理其他类目属性（无吊牌）...')
                    main_tab.ele('xpath://div[@attr-field-id="主图3:4"]').scroll.to_see()
                    time.sleep(0.1)
                    material_ok = set_material_composition(main_tab, configured_materials)
                    if not material_ok:
                        raise Exception('面料材质填写失败')
                    select_text(main_tab, '品牌', '无品牌')
                    select_text(main_tab, '适用人群', '成人')
                    select_text(main_tab, '适用性别', get_sex(record.title))
                    if current_sock_height:
                        select_text(main_tab, '筒高', current_sock_height)


                # 🔧 只有当sub_pic_list不为空时才上传3:4主图
                current_stage = 'upload_media_assets'
                if len(sub_pic_list) > 0:
                    upload_file(
                        main_tab,
                        sub_pic_list,
                        '主图',
                        error_size='长宽比需为3:4',
                        target_field_id='主图3:4',
                        wait_for_finish=False
                    )
                else:
                    print("跳过3:4主图上传，尝试自动点击'从1:1主图智能裁剪'按钮")
                    try:
                        if click_field_action(main_tab, '主图3:4', '从1:1主图智能裁剪') or click_field_action(main_tab, '主图3:4', '从1:1主图一键填入'):
                            print("✅ 成功触发3:4主图智能裁剪")
                            time.sleep(0.2)
                        else:
                            print("❌ 未找到3:4主图智能裁剪按钮")
                    except Exception as e:
                        print(f"❌ 自动点击3:4主图智能裁剪按钮失败: {str(e)}")
                        print("请手动点击3:4主图智能裁剪按钮")
                main_tab.ele('xpath://div[@attr-field-id="主图视频"]').scroll.to_see()
                time.sleep(0.1)

                if my_video:
                    print('开始上传主图视频...')
                    upload_file(
                        main_tab,
                        [my_video],
                        '主图视频',
                        target_field_id='主图视频',
                        wait_for_finish=False
                    )
                else:
                    print('没有本地主图视频，尝试在主图视频区域内点击一键生成')
                    if click_field_action(main_tab, '主图视频', '一键生成'):
                        time.sleep(0.2)
                    else:
                        print('未找到可用的一键生成按钮，或按钮当前不可点击')

                upload_file(
                    main_tab,
                    [white_pic],
                    '白底图',
                    target_field_id='白底图',
                    wait_for_finish=False
                )
                time.sleep(0.5)
                try:
                    apply_btn_list = main_tab.eles('xpath://div[text()="AI智能做主图"]/../../../..//span[text()="应用"]/..', timeout=1)
                    for item in apply_btn_list:
                        if item.states.is_displayed:
                            item.click()
                            time.sleep(3)
                            break
                    if len(apply_btn_list) > 0:
                        main_tab.ele('xpath://div[text()="AI智能做主图"]/../../../..//span[text()="上传"]/..', timeout=1).click()
                        time.sleep(0.5)
                except:
                    pass
                upload_file(main_tab, detail_pic_list, '图片', extra=True, target_field_id='商品详情')

                main_tab.ele('xpath://span[text()="价格与库存"]').scroll.to_see()
                time.sleep(0.1)

                print('选择发货时间 -> 48小时')
                main_tab.ele('xpath://span[text()="48小时"]').click()
                time.sleep(0.1)

                print('勾选添加规格图片')
                main_tab.ele('xpath://span[text()="添加规格图"]').click(by_js=True)
                time.sleep(0.1)

                ss = main_tab.eles('xpath://div[@id="skuValue-颜色分类"]//span[@data-kora="删除规格值"]', timeout=1)
                for del_btn in ss:
                    del_btn.click(by_js=True)
                    time.sleep(0.1)

                current_stage = 'configure_sku_entries'
                for i, sku in enumerate(sku_list):
                    set_sku_info(main_tab, i, sku, record.remark)

                current_stage = 'configure_sku_structure'
                print('选择均码')
                main_tab.ele('xpath://div[@id="skuValue-码数"]//input').scroll.to_center()
                time.sleep(0.1)
                main_tab.ele('xpath://div[@id="skuValue-码数"]//input').click()
                time.sleep(0.1)
                main_tab.ele('xpath://li[@title="均码"]').click()
                time.sleep(0.1)
                main_tab.eles('xpath://li[@title="均码"]')[1].click()
                time.sleep(0.5)
                try:

                    confirm_button = main_tab.ele('xpath://div[contains(@class,"styles_popupFooter__")]//button[.//span[starts-with(text(), "确定")]]', timeout=0.5)
                    confirm_button.click()
                except:
                    pass

                current_stage = 'fill_price_and_stock'
                print('设置价格和库存...')
                price_stock_root = main_tab.ele('xpath://div[@attr-field-id="价格与库存"]')
                if not price_stock_root:
                    raise Exception('未找到价格与库存区域')

                def _xpath_text_literal(value):
                    value = str(value)
                    if "'" not in value:
                        return f"'{value}'"
                    if '"' not in value:
                        return f'"{value}"'
                    parts = value.split("'")
                    return "concat(" + ', "\'", '.join([f"'{part}'" for part in parts]) + ")"

                for i, sku in enumerate(sku_list):
                    sku_name = str(sku.get('name', '')).strip()
                    sku_price = '' if sku.get('price') is None else str(sku.get('price'))
                    sku_stock = str(record.repo)
                    print(f'填写SKU价格库存 -> {i + 1}. {sku_name} | 价格:{sku_price} | 库存:{sku_stock}')

                    row_selector = (
                        'xpath://tr[contains(@class,"ecom-g-table-row")]'
                        f'[.//td[1]//div[contains(@class,"styles_specName__") and normalize-space(.)={_xpath_text_literal(sku_name)}]]'
                    )
                    row_list = price_stock_root.eles(f'xpath:.{row_selector[6:]}', timeout=1)
                    if not row_list:
                        raise Exception(f'未找到价格库存行：{sku_name}')

                    tr = row_list[-1]
                    tr.scroll.to_center()
                    time.sleep(0.1)

                    price_input = tr.ele('xpath:./td[3]//input', timeout=1)
                    stock_input = tr.ele('xpath:./td[4]//input', timeout=1)
                    if not price_input or not stock_input:
                        raise Exception(f'未找到价格或库存输入框：{sku_name}')

                    price_input.input(sku_price, clear=True)
                    time.sleep(0.1)
                    stock_input.input(sku_stock, clear=True)
                    time.sleep(0.1)

                    price_value = (price_input.attr('value') or '').strip()
                    stock_value = (stock_input.attr('value') or '').strip()
                    if price_value != sku_price or stock_value != sku_stock:
                        raise Exception(
                            f'价格库存写入校验失败：{sku_name} -> 价格[{price_value}] 库存[{stock_value}]'
                        )
                
                main_tab.ele('xpath://span[text()="售后服务承诺"]').scroll.to_see()
                time.sleep(0.1)

                select_text(main_tab, '运费模板', shipping_template_name, '包邮')
                time.sleep(0.1)
                youhui_btn = main_tab.ele('xpath://button[contains(@class,"marketing_sylva-switch-checked")]', timeout=1)
                if youhui_btn:
                    print('取消商品优惠券勾选')
                    youhui_btn.click(by_js=True)

                print('选择商品状态 -> 上架')
                main_tab.ele('xpath://span[text()="上架"]').click(by_js=True)
                time.sleep(0.1)

                try:
                    switch = main_tab.ele('xpath://button[@dropdownclassname="auto-dropdown-id-支持联盟达人带货"]', timeout=2)
                    if switch and switch.states.is_displayed:
                        cls = switch.attr('class') or ''
                        disabled_attr = switch.attr('disabled')
                        if ('disabled' not in cls) and (disabled_attr is None):
                            print('勾选支持联盟达人带货')
                            switch.click(by_js=True)
                            time.sleep(0.1)
                            rate_input = main_tab.ele('xpath://label[@title="佣金率"]/../..//input', timeout=2)
                            if rate_input:
                                print('输入佣金率：20%')
                                rate_input.input('20')
                                time.sleep(0.1)
                        else:
                            print('联盟达人带货不可用，已跳过')
                    else:
                        print('未找到联盟达人带货开关，已跳过')
                except:
                    print('处理联盟达人带货失败，已跳过')
                

                current_stage = 'submit_publish'
                print('发布商品')
                main_tab.ele('xpath://span[text()="发布商品"]/..').click()
                time.sleep(0.5)

                try:
                    # 等待弹窗出现（最多等5秒）
                    modal = main_tab.ele('xpath://div[@class="ecom-g-modal-title"][text()="发布提醒"]/../..', timeout=5)
                    
                    # 定位目标按钮（通过文本精准定位）
                    continue_btn = modal.ele('xpath:.//div[text()="不修改，继续发布"]/ancestor::button')
                    
                    # 确保按钮可见后点击
                    continue_btn.scroll.to_center()
                    continue_btn.click()
                    print('已处理发布提醒弹窗')
                except Exception as e:
                    print(f'未出现弹窗或处理失败: {str(e)}')
                publish_ok = False
                for _ in range(30):
                    if main_tab.ele('商品提交成功，继续发布商品视频，分享到抖音', timeout=0.5):
                        publish_ok = True
                        break
                    time.sleep(0.5)

                if publish_ok:
                    print('发布成功！')
                    record_ok = True
                    record.status = 1
                    record.publish_time = time.now()
                    record.save()
                else:
                    print('发布失败！！！')

            except Exception as e:
                # 获取完整的错误追踪信息
                detailed_error = traceback.format_exc()
                print("------------- 详细错误报告 -------------")
                print(detailed_error)
                print("------------------------------------")
                try:
                    _record_browser_automation_error(
                        current_stage,
                        e,
                        detailed_error,
                        tab=main_tab,
                        extra={
                            'record_id': record.id,
                            'record_name': record.name,
                        }
                    )
                except Exception:
                    traceback.print_exc()
                
                # 如果是脚本预设的错误提示，直接使用
                if not error_tip:
                    # 否则，使用异常的文本信息作为错误提示
                    error_tip = str(e)
            
            finally:
                fi_arr = record.name.split('_')
                # 确保 fi_name 是一个字符串
                fi_name_tuple = record.name if len(fi_arr) < 4 else fi_arr[3],
                fi_name = fi_name_tuple[0] if isinstance(fi_name_tuple, tuple) else fi_name_tuple

                if record_ok:
                    msg_list.append(f'{fi_name} -> 操作成功！')
                else:
                    msg_list.append(f'{fi_name} -> 操作失败[{error_tip}]！')
                time.sleep(3)
    except:
        print("------------- 致误报告 -------------")
        print(traceback.format_exc())
        print("------------------------------------")
        msg_list.append('发生了一个意外的错误，请检查控制台日志。')
        
    # 🔧 修复：检查是否有失败消息，决定返回成功还是失败
    combined_msg = '\n'.join(msg_list)
    if '操作失败' in combined_msg or '意外的错误' in combined_msg:
        return api_error(msg=combined_msg)
    else:
        return api_ok(msg=combined_msg)


_upload_tasks = {}
_upload_tasks_lock = threading.Lock()


def _serialize_upload_task(task):
    return {
        'task_id': task.get('task_id'),
        'record_id': task.get('record_id'),
        'record_name': task.get('record_name'),
        'status': task.get('status'),
        'progress': task.get('progress', 0),
        'message': task.get('message', ''),
        'error': task.get('error'),
        'created_at': task.get('created_at'),
        'started_at': task.get('started_at'),
        'finished_at': task.get('finished_at'),
        'debug_report': task.get('debug_report'),
    }


def _run_upload_task(task_id: str, record_id=None):
    with _upload_tasks_lock:
        task = _upload_tasks.get(task_id)
        if not task:
            return
        task['status'] = 'running'
        task['progress'] = 10
        task['message'] = '正在启动浏览器并准备上传'
        task['started_at'] = datetime.now().isoformat()

    try:
        payload = {}
        if record_id:
            payload['record_id'] = record_id

        with app.test_request_context('/start', method='POST', json=payload):
            result = start()

        success = bool(result.get('success'))
        message = str(result.get('msg') or '')

        with _upload_tasks_lock:
            task = _upload_tasks.get(task_id)
            if not task:
                return
            task['progress'] = 100
            task['finished_at'] = datetime.now().isoformat()
            if success:
                task['status'] = 'success'
                task['message'] = message or '上传完成'
                task['error'] = None
            else:
                task['status'] = 'failed'
                task['message'] = '上传失败'
                task['error'] = message or '上传失败（未知原因）'
                task['debug_report'] = _latest_browser_debug_error_after(task.get('started_at'))
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
        'error': None,
        'created_at': datetime.now().isoformat(),
        'started_at': None,
        'finished_at': None,
        'debug_report': None,
    }

    with _upload_tasks_lock:
        _upload_tasks[task_id] = task

    worker = threading.Thread(target=_run_upload_task, args=(task_id, record_id), daemon=True)
    worker.start()

    return api_ok(msg='上传任务已启动', data={'task_id': task_id})


@app.get('/api/upload/status/<task_id>')
def upload_status(task_id):
    with _upload_tasks_lock:
        task = _upload_tasks.get(task_id)
        if not task:
            return api_error(msg='上传任务不存在')
        return api_ok(msg='获取任务状态成功', data=_serialize_upload_task(task))


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


@app.get('/menu_delete')
def menu_delete():
    try:
        _id = request.args.get('_id')
        if not _id:
            return api_error(msg='参数错误！')
        
        record = Record.get_by_id(_id)
        if not record:
            return api_error(msg='记录不存在！')
        
        Record.delete_by_id(_id)
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
                    'update_time': datetime.now()
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
        return api_ok(msg='获取设置成功', data={'settings': {
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
            backend_data['model_configs'] = data.get('model_configs')

        if 'automation_config' in data:
            automation_config = data.get('automation_config') or {}
            material_compositions = automation_config.get('material_compositions') or []
            if isinstance(material_compositions, list) and len(material_compositions) > 0:
                total_percentage = 0
                for item in material_compositions:
                    if not isinstance(item, dict):
                        continue
                    try:
                        total_percentage += int(float(item.get('percentage', 0) or 0))
                    except Exception:
                        continue
                if total_percentage != 100:
                    return api_error('材质面料含量总和必须等于100')
            backend_data['automation_config'] = data.get('automation_config')
        
        if settings_manager.update_settings(backend_data):
            return api_ok(msg='设置保存成功')
        else:
            return api_error('设置保存失败')
    except Exception as e:
        return api_error(f'设置更新失败: {str(e)}')


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


@app.get('/settings/page')
def settings_page():
    """设置页面"""
    try:
        return render_template('/view/settings/index.html', ctx=constants)
    except Exception as e:
        traceback.print_exc()
        return api_error(f'页面加载失败：{str(e)}')


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
        
        base_name = record.name if record.name else "产品"
        
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
        
        base_name = record.name if record.name else "产品"
        
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


# 🔧 新增：控制GUI拖拽区域显示/隐藏的API - 添加防抖机制
# 防抖机制相关变量
_last_toggle_time = None
_toggle_lock = threading.Lock()
_debounce_interval = timedelta(milliseconds=300)  # 300ms防抖间隔

@app.post('/gui/toggle_drag_area')
def toggle_drag_area():
    """控制GUI拖拽区域的显示和隐藏 - 带防抖机制"""
    global _last_toggle_time
    
    try:
        # 🔧 防抖机制：避免频繁切换导致闪烁
        with _toggle_lock:
            current_time = datetime.now()
            if _last_toggle_time and (current_time - _last_toggle_time) < _debounce_interval:
                return api_ok('操作被防抖机制跳过')
            _last_toggle_time = current_time
        
        data = request.get_json()
        show = data.get('show', True)  # 默认显示
        
        # 🔧 使用线程安全的GUI操作方法
        if hasattr(gui, 'window') and gui.window and hasattr(gui.window, 'safe_toggle_label'):
            # 使用新的线程安全方法
            def safe_toggle():
                try:
                    success = gui.window.safe_toggle_label(show)
                    if success:
                        status = '已显示' if show else '已隐藏'
                        print(f'GUI拖拽区域{status}')
                    else:
                        print('GUI拖拽区域操作被跳过（正在更新中）')
                except Exception as e:
                    print(f'GUI操作异常: {str(e)}')
            
            # 🔧 直接调用，避免Qt事件循环问题
            safe_toggle()
                
            return api_ok('操作成功')
        else:
            error_msg = 'GUI窗口未初始化'
            print(f'❌ {error_msg}')
            return api_error(error_msg)
    except Exception as e:
        error_msg = f'控制GUI拖拽区域失败: {str(e)}'
        print(f'❌ {error_msg}')
        
        traceback.print_exc()
        return api_error(f'操作失败: {str(e)}')


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

        config_file = os.path.join(os.path.dirname(__file__), 'pricing_config.json')
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

        return jsonify({
            'success': True,
            'message': f"smart pricing finished for {len(pricing_results)} skus",
            'data': pricing_data
        })
    except Exception as e:
        print(f'smart pricing failed: {e}')
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'smart pricing failed: {str(e)}'
        })


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
            name=record.name,
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
        config_file = os.path.join(os.path.dirname(__file__), 'pricing_config.json')
        
        # 🔧 确保配置目录存在
        config_dir = os.path.dirname(config_file)
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
        
        # 读取现有配置
        existing_config = {}
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                existing_config = json.load(f)
        else:
            # 如果配置文件不存在，创建一个新的空配置
            existing_config = {}
        
        # 更新成本配置
        if 'templates' not in existing_config:
            existing_config['templates'] = {}
        
        if '默认袜子模板' not in existing_config['templates']:
            existing_config['templates']['默认袜子模板'] = {}
        
        existing_config['templates']['默认袜子模板']['base_cost_items'] = cost_items
        existing_config['templates']['默认袜子模板']['profit_margin'] = target_profit_rate
        
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
                
                existing_config['templates']['默认袜子模板']['marketing_config'] = validated_marketing
                print(f"✅ 营销配置已保存: {validated_marketing}")
        
        # 🔧 添加保存时间戳
        existing_config['last_updated'] = system_time.strftime('%Y-%m-%d %H:%M:%S', system_time.localtime())
        
        # 保存配置
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(existing_config, f, ensure_ascii=False, indent=2)
        print(f"✅ 配置已保存到: {config_file}")
        
        # 🔧 验证保存是否成功
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
                saved_items = saved_config.get('templates', {}).get('默认袜子模板', {}).get('base_cost_items', [])
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
        config_file = os.path.join(os.path.dirname(__file__), 'pricing_config.json')
        
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
        else:
            # 返回默认配置
            config = {
                'templates': {
                    '默认袜子模板': {
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
        config_file = os.path.join(os.path.dirname(__file__), 'pricing_config.json')
        existing_config = {}
        
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                existing_config = json.load(f)
        
        # 确保配置结构存在
        if 'templates' not in existing_config:
            existing_config['templates'] = {}
        if '默认袜子模板' not in existing_config['templates']:
            existing_config['templates']['默认袜子模板'] = {'base_cost_items': []}
        
        # 检查是否已存在同名项目
        cost_items = existing_config['templates']['默认袜子模板'].get('base_cost_items', [])
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
        existing_config['templates']['默认袜子模板']['base_cost_items'] = cost_items
        existing_config['last_updated'] = system_time.strftime('%Y-%m-%d %H:%M:%S', system_time.localtime())
        
        # 保存配置
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(existing_config, f, ensure_ascii=False, indent=2)
        
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
        config_file = os.path.join(os.path.dirname(__file__), 'pricing_config.json')
        if not os.path.exists(config_file):
            return jsonify({'success': False, 'error': '配置文件不存在'})
        
        with open(config_file, 'r', encoding='utf-8') as f:
            existing_config = json.load(f)
        
        # 查找并更新项目
        cost_items = existing_config.get('templates', {}).get('默认袜子模板', {}).get('base_cost_items', [])
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
        existing_config['last_updated'] = system_time.strftime('%Y-%m-%d %H:%M:%S', system_time.localtime())
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(existing_config, f, ensure_ascii=False, indent=2)
        
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
        config_file = os.path.join(os.path.dirname(__file__), 'pricing_config.json')
        if not os.path.exists(config_file):
            return jsonify({'success': False, 'error': '配置文件不存在'})
        
        with open(config_file, 'r', encoding='utf-8') as f:
            existing_config = json.load(f)
        
        # 查找并删除项目
        cost_items = existing_config.get('templates', {}).get('默认袜子模板', {}).get('base_cost_items', [])
        original_count = len(cost_items)
        
        # 过滤掉要删除的项目
        cost_items = [item for item in cost_items if item['name'] != item_name]
        
        if len(cost_items) == original_count:
            return jsonify({'success': False, 'error': f'成本项目 "{item_name}" 不存在'})
        
        # 更新配置
        existing_config['templates']['默认袜子模板']['base_cost_items'] = cost_items
        existing_config['last_updated'] = system_time.strftime('%Y-%m-%d %H:%M:%S', system_time.localtime())
        
        # 保存配置
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(existing_config, f, ensure_ascii=False, indent=2)
        
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
        config_file = os.path.join(os.path.dirname(__file__), 'pricing_config.json')
        
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                
            cost_items = config.get('templates', {}).get('默认袜子模板', {}).get('base_cost_items', [])
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
    try:
        config_file = os.path.join(os.path.dirname(__file__), 'ai_config.json')
        
        # 默认配置
        default_config = {
            'deepseek': {
                'enabled': True,
                'api_key': '',
                'model': 'deepseek-chat',
                'priority': 1
            },
            'openai': {
                'enabled': False,
                'api_key': '',
                'model': 'gpt-4',
                'priority': 2
            },
            'claude': {
                'enabled': False,
                'api_key': '',
                'model': 'claude-3-sonnet-20240229',
                'priority': 3
            }
        }
        
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 合并默认配置，确保所有字段都存在
                for provider in default_config:
                    if provider not in config:
                        config[provider] = default_config[provider]
                    else:
                        for key in default_config[provider]:
                            if key not in config[provider]:
                                config[provider][key] = default_config[provider][key]
        else:
            config = default_config
        
        # 隐藏API密钥的敏感信息
        safe_config = {}
        for provider, settings in config.items():
            safe_config[provider] = settings.copy()
            if safe_config[provider]['api_key']:
                # 只显示前4位和后4位
                key = safe_config[provider]['api_key']
                if len(key) > 8:
                    safe_config[provider]['api_key'] = key[:4] + '*' * (len(key) - 8) + key[-4:]
        
        return jsonify({
            'success': True,
            'data': safe_config
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'获取AI配置失败: {str(e)}'
        })


@app.post('/api/ai/config')
def save_ai_config():
    """保存AI配置API"""
    try:
        data = request.get_json()
        
        # 验证配置数据
        required_providers = ['deepseek', 'openai', 'claude']
        for provider in required_providers:
            if provider not in data:
                return jsonify({
                    'success': False,
                    'error': f'缺少{provider}配置'
                })
            
            provider_config = data[provider]
            required_fields = ['enabled', 'api_key', 'model', 'priority']
            for field in required_fields:
                if field not in provider_config:
                    return jsonify({
                        'success': False,
                        'error': f'{provider}配置缺少{field}字段'
                    })
        
        # 验证至少启用一个服务
        enabled_services = [p for p in data.values() if p.get('enabled')]
        if not enabled_services:
            return jsonify({
                'success': False,
                'error': '至少需要启用一个AI服务'
            })
        
        # 验证启用的服务都有API密钥
        for provider, config in data.items():
            if config.get('enabled') and not config.get('api_key'):
                provider_names = {
                    'deepseek': 'DeepSeek',
                    'openai': 'OpenAI',
                    'claude': 'Claude'
                }
                return jsonify({
                    'success': False,
                    'error': f'请填写{provider_names.get(provider, provider)}的API密钥'
                })
        
        # 保存配置
        config_file = os.path.join(os.path.dirname(__file__), 'ai_config.json')
        
        # 添加时间戳
        data['last_updated'] = system_time.strftime('%Y-%m-%d %H:%M:%S', system_time.localtime())
        
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print("🔄 AI配置已更新，建议重启应用以应用新配置")
        
        return jsonify({
            'success': True,
            'message': 'AI配置保存成功'
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'保存AI配置失败: {str(e)}'
        })


@app.post('/api/ai/test')
def test_ai_connection():
    """测试AI连接API"""
    try:
        data = request.get_json()
        
        test_results = {}
        
        # 测试每个启用的AI服务
        for provider, config in data.items():
            if not config.get('enabled'):
                continue
                
            provider_names = {
                'deepseek': 'DeepSeek',
                'openai': 'OpenAI',
                'claude': 'Claude'
            }
            
            try:
                api_key = config.get('api_key', '').strip()
                model = config.get('model', '')
                
                if not api_key:
                    test_results[provider] = {
                        'success': False,
                        'error': 'API密钥为空'
                    }
                    continue
                
                # 根据不同提供商测试连接
                if provider == 'deepseek':
                    success, error = test_deepseek_connection(api_key, model)
                elif provider == 'openai':
                    success, error = test_openai_connection(api_key, model)
                elif provider == 'claude':
                    success, error = test_claude_connection(api_key, model)
                else:
                    success, error = False, '未知的AI提供商'
                
                test_results[provider] = {
                    'success': success,
                    'error': error if not success else None
                }
                
            except Exception as e:
                test_results[provider] = {
                    'success': False,
                    'error': f'测试连接时出错: {str(e)}'
                }
        
        return jsonify({
            'success': True,
            'data': test_results
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'测试AI连接失败: {str(e)}'
        })


def test_deepseek_connection(api_key: str, model: str) -> tuple[bool, str]:
    """测试DeepSeek连接"""
    try:
        import requests
        
        url = "https://api.deepseek.com/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": "Hello, this is a connection test."}
            ],
            "max_tokens": 10,
            "temperature": 0.1
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if response.status_code == 200:
            return True, None
        elif response.status_code == 401:
            return False, "API密钥无效"
        elif response.status_code == 429:
            return False, "请求频率过高，请稍后再试"
        else:
            return False, f"HTTP {response.status_code}: {response.text[:100]}"
            
    except requests.exceptions.Timeout:
        return False, "连接超时"
    except requests.exceptions.ConnectionError:
        return False, "网络连接失败"
    except Exception as e:
        return False, f"连接测试失败: {str(e)}"


def test_openai_connection(api_key: str, model: str) -> tuple[bool, str]:
    """测试OpenAI连接"""
    try:
        import requests
        
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": "Hello, this is a connection test."}
            ],
            "max_tokens": 10,
            "temperature": 0.1
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if response.status_code == 200:
            return True, None
        elif response.status_code == 401:
            return False, "API密钥无效"
        elif response.status_code == 429:
            return False, "请求频率过高，请稍后再试"
        else:
            return False, f"HTTP {response.status_code}: {response.text[:100]}"
            
    except requests.exceptions.Timeout:
        return False, "连接超时"
    except requests.exceptions.ConnectionError:
        return False, "网络连接失败"
    except Exception as e:
        return False, f"连接测试失败: {str(e)}"


def test_claude_connection(api_key: str, model: str) -> tuple[bool, str]:
    """测试Claude连接"""
    try:
        import requests
        
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
        
        payload = {
            "model": model,
            "max_tokens": 10,
            "messages": [
                {"role": "user", "content": "Hello, this is a connection test."}
            ]
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if response.status_code == 200:
            return True, None
        elif response.status_code == 401:
            return False, "API密钥无效"
        elif response.status_code == 429:
            return False, "请求频率过高，请稍后再试"
        else:
            return False, f"HTTP {response.status_code}: {response.text[:100]}"
            
    except requests.exceptions.Timeout:
        return False, "连接超时"
    except requests.exceptions.ConnectionError:
        return False, "网络连接失败"
    except Exception as e:
        return False, f"连接测试失败: {str(e)}"


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
        config_file = os.path.join(os.path.dirname(__file__), 'pricing_config.json')
        existing_config = {}
        
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                existing_config = json.load(f)
        
        # 确保配置结构存在
        if 'templates' not in existing_config:
            existing_config['templates'] = {}
        if '默认袜子模板' not in existing_config['templates']:
            existing_config['templates']['默认袜子模板'] = {'base_cost_items': []}
        
        # 更新毛利率
        existing_config['templates']['默认袜子模板']['profit_margin'] = profit_margin_decimal
        existing_config['last_updated'] = system_time.strftime('%Y-%m-%d %H:%M:%S', system_time.localtime())
        
        # 保存配置
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(existing_config, f, ensure_ascii=False, indent=2)
        
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


# 🚀 新增：配置验证API

@app.post('/api/pricing/validate-config')
def validate_pricing_config():
    """验证价格配置有效性API"""
    try:
        data = request.get_json()
        
        validation_results = {
            'is_valid': True,
            'errors': [],
            'warnings': [],
            'suggestions': []
        }
        
        # 验证成本项目
        cost_items = data.get('cost_items', [])
        
        if len(cost_items) == 0:
            validation_results['warnings'].append('没有配置任何成本项目，可能影响价格计算准确性')
        
        # 验证每个成本项目
        for i, item in enumerate(cost_items):
            if not item.get('name'):
                validation_results['errors'].append(f'成本项目{i+1}缺少名称')
                validation_results['is_valid'] = False
            
            if item.get('cost_type') not in ['fixed', 'percentage', 'per_unit']:
                validation_results['errors'].append(f'成本项目{i+1}的类型无效')
                validation_results['is_valid'] = False
            
            if not isinstance(item.get('value'), (int, float)) or item.get('value', 0) < 0:
                validation_results['errors'].append(f'成本项目{i+1}的值无效')
                validation_results['is_valid'] = False
        
        # 验证利润率
        profit_margin = data.get('target_profit_rate', 0)
        if not isinstance(profit_margin, (int, float)) or profit_margin < 0 or profit_margin > 1:
            validation_results['errors'].append('利润率必须在0-100%之间')
            validation_results['is_valid'] = False
        elif profit_margin < 0.1:
            validation_results['warnings'].append('利润率过低，可能影响盈利能力')
        elif profit_margin > 0.5:
            validation_results['warnings'].append('利润率过高，可能影响产品竞争力')
        
        # 提供优化建议
        if len(cost_items) > 0:
            fixed_costs = [item for item in cost_items if item.get('cost_type') == 'fixed']
            percentage_costs = [item for item in cost_items if item.get('cost_type') == 'percentage']
            
            if len(fixed_costs) == 0:
                validation_results['suggestions'].append('建议添加一些固定成本项目（如包装、运费等）')
            
            if len(percentage_costs) == 0:
                validation_results['suggestions'].append('建议添加一些百分比成本项目（如平台费、推广费等）')
        
        return jsonify({
            'success': True,
            'data': validation_results
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'配置验证失败: {str(e)}'
        })
# ========== 商品链接采集 API ==========

# 全局任务存储
capture_tasks = {}

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
        
        url = data.get('url', '').strip()
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
            return jsonify({'success': False, 'message': '请输入商品链接'})
        
        if 'taobao.com' not in url and 'tmall.com' not in url:
            app.logger.error(f"❌ 不支持的URL: {url}")
            return jsonify({'success': False, 'message': '仅支持淘宝/天猫商品链接'})
        
        # 生成任务ID
        import hashlib
        task_id = f"capture_{int(system_time.time())}_{hashlib.md5(url.encode()).hexdigest()[:8]}"
        app.logger.info(f"🆔 生成任务ID: {task_id}")
        
        # 创建任务
        task = {
            'task_id': task_id,
            'url': url,
            'options': options,
            'status': 'pending',
            'progress': 0,
            'message': '任务创建成功',
            'created_at': datetime.now().isoformat(),
            'result': None
        }
        
        capture_tasks[task_id] = task
        app.logger.info(f"✅ 任务已创建: {task_id}")
        
        # URL清洗函数：处理阿里云CDN的各种后缀
        def clean_alicdn_url(url):
            """
            清洗阿里云CDN图片URL，去除缩略图和质量后缀
            例如：
            - https://.../xxx.jpg_90x90q30.jpg_.webp -> https://.../xxx.jpg
            - https://.../xxx.jpg_q50.jpg_.webp -> https://.../xxx.jpg
            - https://.../xxx.jpg_.webp -> https://.../xxx.jpg
            """
            if not url:
                return ''
            
            # 补全协议
            if url.startswith('//'):
                url = 'https:' + url
            elif not url.startswith('http'):
                return ''
            
            # 去掉URL参数
            url = url.split('?')[0]
            
            # 阿里云CDN图片URL处理规则（按优先级）
            import re
            
            # 1. 处理 _数字x数字q数字.jpg_.webp （如：_90x90q30.jpg_.webp）
            url = re.sub(r'_\d+x\d+q\d+\.jpg_\.webp$', '.jpg', url)
            
            # 2. 处理 _q数字.jpg_.webp （如：_q50.jpg_.webp）
            url = re.sub(r'_q\d+\.jpg_\.webp$', '.jpg', url)
            
            # 3. 处理 _.webp （通用webp后缀）
            url = re.sub(r'_\.webp$', '', url)
            
            # 4. 处理 .jpg_.webp
            url = re.sub(r'\.jpg_\.webp$', '.jpg', url)
            
            # 5. 处理 _数字x数字q数字.jpg （如：_90x90q30.jpg）
            url = re.sub(r'_\d+x\d+q\d+\.jpg$', '.jpg', url)
            
            # 6. 处理 _q数字.jpg （如：_q50.jpg）
            url = re.sub(r'_q\d+\.jpg$', '.jpg', url)
            
            # 7. 处理双后缀情况（如：.jpg.jpg、.png.jpg等）
            url = re.sub(r'\.(jpg|jpeg|png|gif|webp)\.(jpg|jpeg|png|gif|webp)$', r'.\1', url)
            
            # 8. 处理 -0-picasso 等特殊标记
            # picasso 是阿里的图片处理服务，URL格式: xxx-0-picasso.jpg
            # 这种URL通常是正常的，不需要特殊处理
            
            return url
        
        # 在后台线程中启动采集
        def run_capture_task():
            # 在函数开头导入所需模块，避免作用域问题
            import traceback
            import re
            
            try:
                app.logger.info(f"🚀 开始执行采集任务: {task_id}")
                
                # 更新任务状态
                capture_tasks[task_id]['status'] = 'running'
                capture_tasks[task_id]['progress'] = 10
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
                
                # 🛡️ 反爬虫策略配置
                # 1. 设置真实的User-Agent
                co.set_user_agent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
                
                # 2. 禁用自动化检测特征
                co.set_argument('--disable-blink-features=AutomationControlled')
                
                # 3. 添加更多反检测参数
                co.set_argument('--disable-dev-shm-usage')
                # co.set_argument('--no-sandbox')  # 已移除：会显示警告提示
                co.set_argument('--disable-gpu')
                
                # 4. 设置窗口大小（模拟真实用户）
                co.set_argument('--window-size=1920,1080')
                
                # 5. 禁用webdriver标志
                co.set_pref('excludeSwitches', ['enable-automation'])
                co.set_pref('useAutomationExtension', False)
                
                app.logger.info("✅ 反爬虫策略已配置")
                
                # 更新进度
                capture_tasks[task_id]['progress'] = 20
                capture_tasks[task_id]['message'] = '正在访问商品页面...'
                app.logger.info(f"📊 进度: 20% - 正在访问商品页面...")
                
                # 创建页面
                app.logger.info("🌐 正在启动浏览器...")
                page = ChromiumPage(co)
                
                # 🛡️ 注入反检测脚本
                page.run_js('''
                    // 移除webdriver标识
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => false
                    });
                    
                    // 伪造插件
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });
                    
                    // 伪造语言
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['zh-CN', 'zh', 'en']
                    });
                    
                    // 覆盖权限查询
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({ state: Notification.permission }) :
                            originalQuery(parameters)
                    );
                    
                    console.log('✅ 反检测脚本已注入');
                ''')
                
                # 从任务中获取URL
                task_url = capture_tasks[task_id]['url']
                
                # 🛡️ 先访问淘宝首页，建立正常浏览轨迹（反爬虫关键）
                try:
                    if 'tmall.com' in task_url:
                        app.logger.info("🏠 先访问天猫首页，建立浏览轨迹...")
                        page.get('https://www.tmall.com', timeout=15)
                    else:
                        app.logger.info("🏠 先访问淘宝首页，建立浏览轨迹...")
                        page.get('https://www.taobao.com', timeout=15)
                    system_time.sleep(2)  # 停留2秒，模拟真实用户浏览
                    app.logger.info("✅ 首页访问完成")
                except Exception as e:
                    app.logger.warning(f"⚠️ 访问首页失败，直接访问商品页（可能增加被拦截风险）: {e}")
                
                # 访问商品页面
                app.logger.info(f"🔗 正在访问商品页面: {task_url}")
                page.get(task_url, timeout=30)
                
                # 检查是否被拦截（关键检测）
                current_url = page.url
                app.logger.info(f"📍 页面加载后URL: {current_url[:100]}")
                
                if 'punish' in current_url or 'sec.taobao.com' in current_url or 'bixi.alicdn.com' in current_url:
                    app.logger.error("❌ 触发反爬虫验证！")
                    capture_tasks[task_id]['status'] = 'failed'
                    capture_tasks[task_id]['progress'] = 0
                    capture_tasks[task_id]['message'] = '❌ 触发反爬虫验证，需要手动处理'
                    
                    # 详细的错误提示
                    error_message = '''
【反爬虫拦截】
触发了淘宝/天猫的安全验证机制。

🔧 解决方法：
1. 在打开的浏览器窗口中完成滑块验证或人机验证
2. 验证通过后，浏览器会自动跳转到商品页面
3. 然后点击"重新采集"按钮即可

💡 预防建议：
- 避免频繁采集（建议间隔30秒以上）
- 首次采集前先手动登录淘宝账号
- 使用已登录的浏览器会话
- 采集速度不要太快
                    '''
                    app.logger.info(error_message)
                    
                    # 不立即关闭浏览器，让用户有机会完成验证
                    app.logger.info("⏳ 浏览器保持打开，等待用户完成验证...")
                    app.logger.info("💡 提示：完成验证后请重新点击采集按钮")
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
                    
                    # 通过URL判断是否需要登录（更快更准确）
                    if 'login.taobao.com' in current_url or 'login.tmall.com' in current_url:
                        login_detected = True
                        app.logger.warning("⚠️ 检测到登录页面（URL包含login）")
                        capture_tasks[task_id]['message'] = '需要登录，请在浏览器中完成登录...'
                        
                        # 等待用户登录（最多等待120秒）
                        wait_count = 0
                        app.logger.info("⏳ 等待用户完成登录（最多120秒）...")
                        while wait_count < 60 and login_detected:
                            system_time.sleep(2)
                            wait_count += 1
                            
                            # 检查URL是否变回商品详情页
                            current_url = page.url
                            if 'login.taobao.com' not in current_url and 'login.tmall.com' not in current_url:
                                # 确认已经跳转回商品页面
                                if 'detail.tmall.com' in current_url or 'item.taobao.com' in current_url:
                                    login_detected = False
                                    app.logger.info(f"✅ 登录完成，当前URL: {current_url[:100]}")
                                    # 等待页面稳定加载
                                    system_time.sleep(2)
                                    break
                        
                        if login_detected:
                            app.logger.warning("⏰ 登录等待超时")
                    else:
                        app.logger.info("✅ 无需登录或已登录")
                except Exception as e:
                    app.logger.warning(f"⚠️ 登录检测异常: {e}")
                
                # 🔧 提取商品ID
                product_id = ''
                try:
                    id_match = re.search(r'[?&]id=(\d+)', task_url)
                    if id_match:
                        product_id = id_match.group(1)
                        app.logger.info(f"✅ 商品ID: {product_id}")
                    else:
                        app.logger.warning("⚠️ 未能从URL提取商品ID")
                        product_id = f"product_{int(system_time.time())}"
                except Exception as e:
                    app.logger.error(f"❌ 提取商品ID失败: {e}")
                    product_id = f"product_{int(system_time.time())}"
                
                # 🔧 滚动页面到底部，确保所有懒加载图片都加载
                capture_tasks[task_id]['progress'] = 40
                capture_tasks[task_id]['message'] = '正在加载页面内容...'
                app.logger.info(f"📊 进度: 40% - 正在加载页面内容...")
                
                try:
                    # 🛡️ 模拟真实用户滚动（反爬虫关键）
                    app.logger.info("📍 模拟真实用户滚动...")
                    
                    # 1. 缓慢分段滚动到底部（更像真人）
                    page.run_js('''
                        (function() {
                            var scrollHeight = document.body.scrollHeight;
                            var currentScroll = 0;
                            var scrollStep = scrollHeight / 5;  // 分5段滚动
                            
                            function smoothScroll() {
                                currentScroll += scrollStep;
                                window.scrollTo({
                                    top: Math.min(currentScroll, scrollHeight),
                                    behavior: 'smooth'
                                });
                            }
                            
                            // 模拟用户滚动
                            for (var i = 0; i < 5; i++) {
                                setTimeout(smoothScroll, i * 300);  // 每300ms滚动一次
                            }
                        })();
                    ''')
                    system_time.sleep(2)  # 等待滚动完成
                    
                    # 2. 滚动回顶部（平滑滚动）
                    page.run_js('window.scrollTo({top: 0, behavior: "smooth"});')
                    system_time.sleep(1)
                    
                    app.logger.info("✅ 页面滚动完成（模拟真实用户行为）")
                except Exception as e:
                    app.logger.warning(f"⚠️ 页面滚动异常: {e}")
                    app.logger.warning(traceback.format_exc()[:300])
                
                # 提取商品信息
                capture_tasks[task_id]['progress'] = 50
                capture_tasks[task_id]['message'] = '正在提取商品信息...'
                app.logger.info(f"📊 进度: 50% - 正在提取商品信息...")
                
                product_data = {
                    'product_id': product_id,
                    'title': '',
                    'price': {'current': 0, 'original': None, 'currency': 'CNY'},
                    'main_images': [],  # 改为列表，存储所有主图
                    'detail_images': [],
                    'sku_info': [],
                    'parameters': []
                }
                
                # 提取标题
                try:
                    title_elem = page.s_ele('.mainTitle--R75fTcZL') or page.s_ele('h1')
                    if title_elem:
                        product_data['title'] = title_elem.text.strip()
                        app.logger.info(f"✅ 标题: {product_data['title'][:50]}...")
                    else:
                        app.logger.warning("⚠️ 未找到标题元素")
                except Exception as e:
                    app.logger.error(f"❌ 标题提取失败: {e}")
                    product_data['title'] = '未能获取标题'
                
                # 提取价格
                try:
                    price_elem = page.s_ele('.highlightPrice--asfw5V1e') or page.s_ele('.tb-rmb-num')
                    if price_elem:
                        price_text = price_elem.text
                        import re
                        price_match = re.search(r'(\d+\.?\d*)', price_text)
                        if price_match:
                            product_data['price']['current'] = float(price_match.group(1))
                            app.logger.info(f"✅ 价格: ¥{product_data['price']['current']}")
                        else:
                            app.logger.warning(f"⚠️ 价格文本格式异常: {price_text}")
                    else:
                        app.logger.warning("⚠️ 未找到价格元素")
                except Exception as e:
                    app.logger.error(f"❌ 价格提取失败: {e}")
                
                # 🔧 提取主图（所有缩略图）
                app.logger.info("📸 开始提取主图...")
                try:
                    # 提取所有主图缩略图
                    thumbnail_imgs = page.s_eles('.thumbnailPic--QasTmWDm')
                    if thumbnail_imgs:
                        for idx, img in enumerate(thumbnail_imgs):
                            src = img.attr('src')
                            if src:
                                # 使用统一的URL清洗函数
                                original_src = clean_alicdn_url(src)
                                if original_src and original_src not in product_data['main_images']:
                                    product_data['main_images'].append(original_src)
                                    app.logger.info(f"✅ 主图 {idx+1}: {original_src[:100]}...")
                        app.logger.info(f"✅ 共提取主图: {len(product_data['main_images'])} 张")
                    else:
                        app.logger.warning("⚠️ 未找到主图元素")
                except Exception as e:
                    app.logger.error(f"❌ 主图提取失败: {e}")
                
                # 🔧 提取详情图片（优化版：直接使用JavaScript，跳过慢速选择器）
                app.logger.info("📸 开始提取详情图片...")
                try:
                    # 直接使用JavaScript提取，避免DrissionPage选择器的延迟
                    detail_urls = page.run_js('''
                            var selectors = [
                                '#container .descV8-singleImage img',
                                '#container .descV8-container img',
                                '#container img',
                                '#description img',
                                '.detail-content img',
                                '.desc-root img'
                            ];
                            
                            var urls = [];
                            var foundImgs = false;
                            
                            for (var i = 0; i < selectors.length; i++) {
                                var imgs = document.querySelectorAll(selectors[i]);
                                if (imgs.length > 0) {
                                    console.log('找到图片使用选择器: ' + selectors[i] + ', 数量: ' + imgs.length);
                                    imgs.forEach(function(img) {
                                        var dataSrc = img.getAttribute('data-src');
                                        var src = img.getAttribute('src');
                                        var url = dataSrc || src;
                                        if (url && url.indexOf('s.gif') === -1 && url.indexOf('O1CN01CYtPWu1MUBqQAUK9D') === -1) {
                                            if (url.indexOf('alicdn.com') !== -1 && urls.indexOf(url) === -1) {
                                                urls.push(url);
                                            }
                                        }
                                    });
                                    foundImgs = true;
                                    break;  // 找到就停止
                                }
                            }
                            
                            if (!foundImgs) {
                                console.log('未找到任何详情图，尝试的选择器: ' + selectors.join(', '));
                            }
                            
                            return urls;
                        ''')
                        
                    app.logger.info(f"🔍 JavaScript提取到 {len(detail_urls) if detail_urls else 0} 个详情图URL")
                    
                    if detail_urls:
                        for idx, url in enumerate(detail_urls):
                            try:
                                # 使用统一的URL清洗函数
                                clean_url = clean_alicdn_url(url)
                                
                                # 验证是否为阿里云CDN图片
                                if clean_url and ('alicdn.com' in clean_url or 'img.alicdn.com' in clean_url):
                                    if clean_url not in product_data['detail_images']:
                                        product_data['detail_images'].append(clean_url)
                                        if len(product_data['detail_images']) <= 5 or len(product_data['detail_images']) % 10 == 0:
                                            app.logger.info(f"✅ 详情图 {len(product_data['detail_images'])}: {clean_url[:100]}...")
                            except Exception as img_e:
                                if idx < 5:
                                    app.logger.warning(f"⚠️ 处理图{idx+1}失败: {img_e}")
                    
                    app.logger.info(f"✅ 共提取详情图: {len(product_data['detail_images'])} 张")
                    
                    if len(product_data['detail_images']) == 0:
                        app.logger.warning("⚠️ 详情图提取结果为0，该商品可能没有详情图或页面结构变化")
                    
                except Exception as e:
                    app.logger.error(f"❌ 详情图提取失败: {e}")
                    app.logger.error(traceback.format_exc())
                
                # 🔧 提取SKU信息（优化版：直接使用JavaScript，跳过慢速选择器）
                app.logger.info("📦 开始提取SKU信息...")
                if options.get('extract_sku', True):
                    try:
                        # 1. 快速滚动到SKU区域（使用JavaScript）
                        try:
                            page.run_js('''
                                var skuArea = document.querySelector('.skuWrapper--iKSsnB_s') || document.getElementById('skuOptionsArea');
                                if (skuArea) {
                                    skuArea.scrollIntoView({behavior: "instant", block: "center"});
                                }
                            ''')
                            system_time.sleep(0.2)  # 从0.3秒减少到0.2秒
                        except Exception as e:
                            app.logger.warning(f"⚠️ SKU区域滚动失败: {e}")
                        
                        # 2. 提取SKU数据和价格（改进版：点击SKU获取真实价格）
                        app.logger.info("📦 开始提取SKU价格...")
                        
                        # 先获取基础SKU信息
                        sku_data_list = page.run_js('''
                                var skuItems = document.querySelectorAll('#skuOptionsArea .skuItem--Z2AJB9Ew');
                                var result = [];
                                
                                // 获取当前显示的价格（作为默认价格）
                                var defaultPrice = 0;
                                try {
                                    var priceElem = document.querySelector('.highlightPrice--asfw5V1e') || document.querySelector('.tb-rmb-num');
                                    if (priceElem) {
                                        var priceText = priceElem.textContent || priceElem.innerText;
                                        var priceMatch = priceText.match(/(\d+\.?\d*)/);
                                        if (priceMatch) {
                                            defaultPrice = parseFloat(priceMatch[1]);
                                        }
                                    }
                                } catch(e) {
                                    console.log('提取默认价格失败:', e);
                                }
                                
                                skuItems.forEach(function(skuItem, skuIdx) {
                                    // 获取SKU类型标题
                                    var titleElem = skuItem.querySelector('.ItemLabel--psS1SOyC span');
                                    var skuTitle = titleElem ? titleElem.textContent.trim() : '';
                                    
                                    // 获取该类型下的所有选项
                                    var valueItems = skuItem.querySelectorAll('.valueItem--smR4pNt4');
                                    
                                    valueItems.forEach(function(valueItem, valIdx) {
                                        // 提取名称
                                        var nameElem = valueItem.querySelector('span[title]');
                                        var skuName = nameElem ? nameElem.getAttribute('title') : valueItem.textContent.trim();
                                        
                                        // 提取图片
                                        var imgElem = valueItem.querySelector('.valueItemImg--GC9bH5my, img');
                                        var skuImage = '';
                                        if (imgElem) {
                                            skuImage = imgElem.getAttribute('data-src') || imgElem.getAttribute('src') || '';
                                        }
                                        
                                        // 提取vid
                                        var vid = valueItem.getAttribute('data-vid') || '';
                                        
                                        if (skuName) {
                                            result.push({
                                                type: skuTitle,
                                                name: skuName,
                                                vid: vid,
                                                image: skuImage,
                                                price: defaultPrice,  // 先使用默认价格
                                                index: valIdx + 1
                                            });
                                        }
                                    });
                                });
                                
                                return result;
                            ''')
                        
                        # 3. 尝试点击每个SKU选项获取准确价格（优化：仅点击第一个SKU类型）
                        if sku_data_list and len(sku_data_list) > 0:
                            app.logger.info("💰 开始获取SKU准确价格...")
                            try:
                                # 只处理第一个SKU类型（通常是颜色）
                                first_sku_type = sku_data_list[0].get('type', '')
                                same_type_skus = [s for s in sku_data_list if s.get('type') == first_sku_type]
                                
                                for sku_index, sku_data in enumerate(same_type_skus[:10]):  # 最多点击10个，避免过长
                                    try:
                                        vid = sku_data.get('vid')
                                        if vid:
                                            # 点击SKU选项
                                            click_result = page.run_js(f'''
                                                var targetItem = document.querySelector('.valueItem--smR4pNt4[data-vid="{vid}"]');
                                                if (targetItem && !targetItem.classList.contains('valueItem--disabled--YJfp_5JE')) {{
                                                    targetItem.click();
                                                    return true;
                                                }}
                                                return false;
                                            ''')
                                            
                                            if click_result:
                                                system_time.sleep(0.3)  # 等待价格更新
                                                
                                                # 获取更新后的价格
                                                current_price = page.run_js('''
                                                    var priceElem = document.querySelector('.highlightPrice--asfw5V1e') || document.querySelector('.tb-rmb-num');
                                                    if (priceElem) {
                                                        var priceText = priceElem.textContent || priceElem.innerText;
                                                        var priceMatch = priceText.match(/(\d+\.?\d*)/);
                                                        if (priceMatch) {
                                                            return parseFloat(priceMatch[1]);
                                                        }
                                                    }
                                                    return 0;
                                                ''')
                                                
                                                if current_price and current_price > 0:
                                                    sku_data['price'] = current_price
                                                    if sku_index < 3:  # 只打印前3个
                                                        app.logger.info(f"💰 SKU「{sku_data['name']}」价格: ¥{current_price}")
                                    except Exception as price_e:
                                        if sku_index < 3:
                                            app.logger.warning(f"⚠️ 获取SKU价格失败: {price_e}")
                                
                                app.logger.info(f"✅ SKU价格获取完成")
                            except Exception as e:
                                app.logger.warning(f"⚠️ SKU价格批量获取失败，使用默认价格: {e}")
                            
                        app.logger.info(f"🔍 JavaScript提取到 {len(sku_data_list) if sku_data_list else 0} 个SKU选项")
                        
                        if sku_data_list:
                            for sku_data in sku_data_list:
                                try:
                                    # 清洗SKU图片URL
                                    if sku_data.get('image'):
                                        raw_url = sku_data['image']
                                        # 跳过占位图
                                        if 's.gif' not in raw_url and 'O1CN01CYtPWu1MUBqQAUK9D' not in raw_url:
                                            sku_data['image'] = clean_alicdn_url(raw_url)
                                            if len(product_data['sku_info']) < 3:  # 只打印前3个
                                                app.logger.info(f"🔍 SKU原始: {raw_url[:80]}...")
                                                app.logger.info(f"✅ SKU清洗: {sku_data['image'][:80]}...")
                                        else:
                                            sku_data['image'] = ''  # 占位图，设为空
                                    
                                    product_data['sku_info'].append(sku_data)
                                    
                                    if len(product_data['sku_info']) <= 5 or len(product_data['sku_info']) % 10 == 0:
                                        price_info = f", 价格: ¥{sku_data.get('price', 0)}" if sku_data.get('price') else ""
                                        app.logger.info(f"✅ SKU {len(product_data['sku_info'])}: {sku_data['type']} - {sku_data['name'][:30]}{price_info}")
                                except Exception as sku_e:
                                    app.logger.warning(f"⚠️ 处理SKU失败: {sku_e}")
                            
                            app.logger.info(f"✅ 共提取SKU: {len(product_data['sku_info'])} 个")
                        else:
                            app.logger.warning("⚠️ 未找到SKU，该商品可能无规格选项或页面结构变化")
                        
                    except Exception as e:
                        app.logger.error(f"❌ SKU提取失败: {e}")
                        app.logger.error(traceback.format_exc())
                
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
                    parent_dir = os.path.join(base_save_path, f'ID-{product_id}')
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
                
                app.logger.info("=" * 80)
                app.logger.info(f"✅✅✅ 采集任务完成: {task_id}")
                app.logger.info(f"📝 商品ID: {product_id}")
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
                capture_tasks[task_id]['message'] = f'采集失败: {str(e)}'
        
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
        
        # 在后台线程中运行
        import threading
        thread = threading.Thread(target=run_capture_task, daemon=True)
        thread.start()
        app.logger.info(f"🧵 后台线程已启动")
        
        # 构建响应
        response_data = {
            'success': True,
            'task_id': task_id,
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
    
    return jsonify({
        'success': True,
        'task_id': task_id,
        'status': task['status'],
        'progress': task['progress'],
        'message': task['message'],
        'result': task.get('result'),
        'created_at': task['created_at']
    })


@app.route('/api/capture/history', methods=['GET'])
def get_capture_history():
    tasks = []
    for task in capture_tasks.values():
        tasks.append({
            'task_id': task.get('task_id'),
            'url': task.get('url', ''),
            'status': task.get('status', 'pending'),
            'progress': task.get('progress', 0),
            'message': task.get('message', ''),
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
    task['message'] = '任务已取消'

    return jsonify({
        'success': True,
        'message': '已取消采集任务',
        'task_id': task_id
    })


@app.route('/api/capture/import', methods=['POST'])
def import_capture_result():
    """导入采集结果到待上传列表"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'})
        
        task_id = data.get('task_id')
        product_data = data.get('product_data')
        
        if not task_id or not product_data:
            return jsonify({
                'success': False,
                'message': '缺少必要参数'
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
        
        # 递归获取SKU目录下的所有图片（ID模式：递归遍历）
        def list_files_recursive(startpath):
            """递归遍历所有文件（ID模式）"""
            result = []
            for root, _, files in os.walk(startpath):
                for filename in sorted(files):
                    if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
                        result.append(os.path.join(root, filename))
            return result
        
        try:
            image_files = list_files_recursive(sku_path)
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'读取图片失败: {str(e)}'
            })
        
        if not image_files:
            return jsonify({
                'success': False,
                'message': '未找到图片文件'
            })
        
        # 从采集结果中获取SKU信息（包含价格）
        captured_sku_info = product_data.get('sku_info', [])
        
        # 创建SKU列表（符合拖拽导入格式）
        sku_list = []
        for sku_file in image_files:
            file_name = os.path.basename(sku_file).split('.')[0]
            dir_name = os.path.basename(os.path.dirname(sku_file))
            
            # 提取名称（去掉序号前缀，如 "01_" ）
            name = file_name
            if '_' in file_name and file_name.split('_')[0].isdigit():
                name = '_'.join(file_name.split('_')[1:])
            
            # 从采集结果中查找对应的价格
            sku_price = ''
            for captured_sku in captured_sku_info:
                if captured_sku.get('name') == name or captured_sku.get('name') in name:
                    sku_price = captured_sku.get('price', '')
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
            update_time=now
        )
        
        app.logger.info(f"✅ 商品已自动导入: {folder_name}, Record ID: {record.id}, SKU数量: {len(sku_list)}")
        
        return jsonify({
            'success': True,
            'message': '商品已添加到待上传列表',
            'record_id': record.id,
            'record_name': folder_name
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
        
        # 异步初始化浏览器页面，避免阻塞GUI启动
        def init_browser():
            try:
                gui.page = get_page('https://fxg.jinritemai.com/login/common')
                print("✅ 浏览器页面初始化成功")
            except Exception as e:
                print(f"⚠️ 浏览器初始化失败: {e}")
                # 浏览器初始化失败不影响GUI显示
        
        # 在后台线程中初始化浏览器
        Thread(init_browser).start()
        
        # Thread(wakeup_listen).start()  # 🔧 暂时禁用自动唤醒功能
        print("💡 启动GUI界面...")
        gui.start()
        
    except Exception as gui_error:
        print(f"❌ GUI启动失败: {gui_error}")
        
        # 如果GUI启动失败，至少启动Flask服务
        try:
            print("💡 请在浏览器中手动打开上述地址使用Web界面")
            run_flask_server(5000)
        except Exception as flask_error:
            print(f"❌ Flask服务启动也失败: {flask_error}")
            
            traceback.print_exc()
            sys.exit(1)
if getattr(sys, 'frozen', False):
    base_dir = os.path.dirname(sys.executable)
    try:
        os.add_dll_directory(base_dir)
        internal_dir = os.path.join(base_dir, '_internal')
        if os.path.isdir(internal_dir):
            os.add_dll_directory(internal_dir)
            os.add_dll_directory(os.path.join(internal_dir, 'PySide6'))
            os.add_dll_directory(os.path.join(internal_dir, 'shiboken6'))
            os.environ['QT_PLUGIN_PATH'] = os.path.join(internal_dir, 'PySide6', 'plugins')
            os.environ['PATH'] = internal_dir + os.pathsep + os.path.join(internal_dir, 'PySide6') + os.pathsep + os.path.join(internal_dir, 'shiboken6') + os.pathsep + os.environ.get('PATH', '')
        else:
            meipass = getattr(sys, '_MEIPASS', base_dir)
            os.add_dll_directory(meipass)
            os.add_dll_directory(os.path.join(meipass, 'PySide6'))
            os.add_dll_directory(os.path.join(meipass, 'shiboken6'))
            os.environ['QT_PLUGIN_PATH'] = os.path.join(meipass, 'PySide6', 'plugins')
            os.environ['PATH'] = meipass + os.pathsep + os.path.join(meipass, 'PySide6') + os.pathsep + os.path.join(meipass, 'shiboken6') + os.pathsep + os.environ.get('PATH', '')
    except Exception:
        pass

from src.thread import Thread
from src.gui import Gui

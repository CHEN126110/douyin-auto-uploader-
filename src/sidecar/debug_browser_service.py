# -*- coding: utf-8 -*-
"""调试浏览器服务：调试会话、事件、错误报告与调试浏览器实例的进程级状态，以及围绕它们的页面查询 / 等待 / 截图能力。

状态属于 ``BrowserDebugService`` 实例（由应用入口创建一次），不再是模块级全局字典；浏览器相关能力
（打开页面、连接已有浏览器、枚举调试进程……）全部经 ``DebugBrowserPort`` 注入，本模块不导入浏览器自动化库，
也不反向导入 app.py。

与 app.py 旧函数名的对应（只列对外有调用方的；其余私有函数保持原名）：
  _create_browser_debug_session     -> BrowserDebugService.create_session
  _get_browser_debug_session        -> BrowserDebugService.get_session
  _append_browser_debug_event       -> BrowserDebugService.append_event
  _set/_get_last_browser_debug_error -> BrowserDebugService.set_last_error / get_last_error
  _set/_get_browser_debug_instance  -> BrowserDebugService.set_browser_instance / get_browser_instance
  _latest_browser_debug_error_after -> BrowserDebugService.latest_error_after
  _find_debug_browser_process       -> BrowserDebugService.find_browser_process
  _launch_attachable_debug_browser  -> BrowserDebugService.launch_attachable_browser
  _get_gui_page_debug_address       -> BrowserDebugService.gui_page_debug_address
  _get_current_browser_tab          -> BrowserDebugService.get_current_tab
  _snapshot_browser_context         -> BrowserDebugService.snapshot_context
  _capture_browser_debug_artifacts  -> BrowserDebugService.capture_artifacts
  _record_browser_automation_error  -> BrowserDebugService.record_automation_error
  _debug_bool / _debug_int          -> debug_bool / debug_int（模块级函数）
  _serialize_browser_debug_session  -> serialize_session
  _query_browser_elements / _get_browser_target_element / _wait_for_browser_condition
                                    -> query_elements / get_target_element / wait_for_condition"""
import copy
import json
import os
import subprocess
import sys
import threading
import time as system_time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


_BROWSER_DEBUG_MAX_EVENTS = 200
_BROWSER_DEBUG_MAX_SESSIONS = 8


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


def _debug_now_iso():
    return datetime.now().isoformat()


def debug_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def debug_int(value, default, minimum=None, maximum=None):
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


def serialize_session(session, include_events=False, recent_event_count=20):
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


def query_elements(tab, locator, locator_type='raw', timeout=1.0, limit=10, include_html=False, only_visible=False):
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


def get_target_element(tab, locator, locator_type='raw', timeout=1.0, index=0, only_visible=True):
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
        query = query_elements(
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


def wait_for_condition(
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


class BrowserDebugService:
    """一个应用一个实例，持有调试会话 / 事件 / 最近一次错误报告 / 调试浏览器实例这些状态。

    ``browser`` 是 ``DebugBrowserPort``；``repo_root`` 与 ``get_app_root`` 决定调试产物（截图、页面快照、
    错误报告）落在哪个目录。"""

    def __init__(self, *, browser, repo_root, get_app_root):
        self._browser = browser
        self._repo_root = repo_root
        self._get_app_root = get_app_root
        self._lock = threading.Lock()
        self._state = {
            'current_session_id': None,
            'sessions': {},
            'last_error': None,
            'browser_instance': None,
        }

    @property
    def browser(self):
        """注入的浏览器端口；路由里的「枚举调试浏览器」直接用它。"""
        return self._browser

    def _debug_root_dir(self):
        if getattr(sys, 'frozen', False):
            base_dir = self._get_app_root()
        else:
            base_dir = self._repo_root
        target = os.path.join(base_dir, 'output', 'browser-debug')
        os.makedirs(target, exist_ok=True)
        return target

    def create_session(self, label='manual'):
        session_id = f"{_debug_slug(label)}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        artifacts_dir = os.path.join(self._debug_root_dir(), session_id)
        os.makedirs(artifacts_dir, exist_ok=True)
        session = {
            'session_id': session_id,
            'label': label,
            'created_at': _debug_now_iso(),
            'updated_at': _debug_now_iso(),
            'artifacts_dir': artifacts_dir,
            'events': [],
        }

        with self._lock:
            self._state['sessions'][session_id] = session
            self._state['current_session_id'] = session_id

            ordered_ids = sorted(
                self._state['sessions'].keys(),
                key=lambda item: self._state['sessions'][item].get('created_at', '')
            )
            while len(ordered_ids) > _BROWSER_DEBUG_MAX_SESSIONS:
                stale_id = ordered_ids.pop(0)
                self._state['sessions'].pop(stale_id, None)
                if self._state.get('current_session_id') == stale_id:
                    self._state['current_session_id'] = None

        return session

    def get_session(self, create=False, label='manual'):
        with self._lock:
            current_id = self._state.get('current_session_id')
            session = self._state['sessions'].get(current_id) if current_id else None

        if session or not create:
            return session
        return self.create_session(label=label)

    def append_event(self, event_type, message, data=None, session_id=None):
        session = None
        with self._lock:
            resolved_session_id = session_id or self._state.get('current_session_id')
            if resolved_session_id:
                session = self._state['sessions'].get(resolved_session_id)
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

    def set_last_error(self, report):
        with self._lock:
            self._state['last_error'] = copy.deepcopy(report)

    def get_last_error(self):
        with self._lock:
            report = self._state.get('last_error')
            return copy.deepcopy(report) if report else None

    def set_browser_instance(self, instance):
        with self._lock:
            self._state['browser_instance'] = copy.deepcopy(instance) if instance else None

    def get_browser_instance(self):
        with self._lock:
            instance = self._state.get('browser_instance')
            return copy.deepcopy(instance) if instance else None

    def latest_error_after(self, started_at=None):
        report = self.get_last_error()
        if not report:
            return None
        if not started_at:
            return report
        captured_at = report.get('captured_at')
        if captured_at and captured_at >= started_at:
            return report
        return None

    def find_browser_process(self, debug_address):
        normalized_address = self._browser.normalize_address(debug_address or '')
        if not normalized_address:
            return None

        for item in self._browser.discover_browsers(verify=False):
            current_address = self._browser.normalize_address(item.get('debug_address') or '')
            if current_address == normalized_address:
                return item
        return None

    def _get_default_debug_browser_user_data_dir(self, profile_name='default'):
        safe_profile = _debug_slug(profile_name or 'default') or 'default'
        target = os.path.join(self._debug_root_dir(), 'profiles', safe_profile)
        os.makedirs(target, exist_ok=True)
        return target

    def _select_debug_browser_port(self, port=None):
        if port is not None:
            try:
                resolved_port = int(port)
            except Exception:
                raise Exception(f'Invalid debug port: {port}')
            if resolved_port < 1 or resolved_port > 65535:
                raise Exception(f'Invalid debug port: {resolved_port}')

            debug_address = f'{self._browser.host}:{resolved_port}'
            verification = self._browser.verify_browser(debug_address, timeout=0.5)
            if verification.get('ok'):
                return {
                    'port': resolved_port,
                    'debug_address': debug_address,
                    'verification': verification,
                    'reused_existing': True,
                }
            if not self._browser.is_port_available(self._browser.host, resolved_port):
                raise Exception(f'Port {resolved_port} is already in use by another process.')
            return {
                'port': resolved_port,
                'debug_address': debug_address,
                'verification': None,
                'reused_existing': False,
            }

        for candidate in range(self._browser.port_start, self._browser.port_end + 1):
            debug_address = f'{self._browser.host}:{candidate}'
            verification = self._browser.verify_browser(debug_address, timeout=0.5)
            if verification.get('ok'):
                return {
                    'port': candidate,
                    'debug_address': debug_address,
                    'verification': verification,
                    'reused_existing': True,
                }
            if self._browser.is_port_available(self._browser.host, candidate):
                return {
                    'port': candidate,
                    'debug_address': debug_address,
                    'verification': None,
                    'reused_existing': False,
                }

        raise Exception('No available debug port was found in the configured range.')

    def _resolve_debug_browser_launch_path(self, browser_path=None):
        candidate = os.path.abspath(str(browser_path).strip()) if browser_path else ''
        if candidate:
            if not os.path.exists(candidate):
                raise Exception(f'Browser executable was not found: {candidate}')
            return candidate

        detected = self._browser.chrome_path()
        if detected:
            detected = os.path.abspath(detected)
            if os.path.exists(detected):
                return detected

        raise Exception('Chrome executable was not found. Provide browser_path explicitly.')

    def launch_attachable_browser(
        self,
        browser_path=None,
        port=None,
        url=None,
        user_data_dir=None,
        profile_name='default',
        timeout=10.0,
        reuse_existing=True,
    ):
        selection = self._select_debug_browser_port(port=port)
        debug_address = selection['debug_address']
        effective_url = (url or '').strip() or 'about:blank'
        target_user_data_dir = os.path.abspath(
            user_data_dir or self._get_default_debug_browser_user_data_dir(profile_name=profile_name)
        )
        os.makedirs(target_user_data_dir, exist_ok=True)

        if selection['reused_existing']:
            if not reuse_existing:
                raise Exception(f'Debug browser is already running at {debug_address}.')
            existing_browser = self.find_browser_process(debug_address) or {}
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

        resolved_browser_path = self._resolve_debug_browser_launch_path(browser_path=browser_path)
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

            verification = self._browser.verify_browser(debug_address, timeout=0.5)
            if verification.get('ok'):
                attached_browser = self.find_browser_process(debug_address) or {}
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

    def gui_page_debug_address(self):
        if not self._browser.page_state().page:
            return ''
        try:
            browser = getattr(self._browser.page_state().page, 'browser', None)
            return getattr(browser, 'address', '') or getattr(self._browser.page_state().page, 'address', '') or ''
        except Exception:
            return ''

    def get_current_tab(self, create_if_missing=False, url=None, navigate=False, mode='managed', debug_address=None, existing_only=False):
        meta = {
            'mode': mode or 'managed',
            'created_browser': False,
            'reused_browser': False,
            'attached_browser': False,
            'navigated': False,
            'debug_address': '',
        }
        target_url = url or self._browser.default_url
        mode = str(mode or 'managed').strip().lower()

        if mode not in ('managed', 'attach'):
            raise Exception(f'Unsupported browser mode: {mode}')

        if mode == 'attach':
            normalized_address = self._browser.normalize_address(debug_address or '')
            if not normalized_address:
                raise Exception('Attach mode requires debug_address.')

            current_address = self._browser.normalize_address(self.gui_page_debug_address())
            if not self._browser.page_state().page or current_address != normalized_address:
                self._browser.page_state().page = self._browser.attach_existing(normalized_address, existing_only=existing_only or True)
                meta['attached_browser'] = True
            meta['debug_address'] = normalized_address
            browser_info = self.find_browser_process(normalized_address) or {}
            existing_instance = self.get_browser_instance() or {}
            if self._browser.normalize_address(existing_instance.get('debug_address') or '') != normalized_address:
                existing_instance = {}
            self.set_browser_instance({
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
        elif not self._browser.page_state().page:
            if not create_if_missing:
                return None, meta
            self._browser.page_state().page = self._browser.open_page(target_url, profile_name=self._browser.active_profile())
            meta['created_browser'] = True
            meta['navigated'] = True
            self.set_browser_instance(None)

        try:
            tab = self._browser.page_state().page.get_tab(self._browser.page_state().page.latest_tab)
            meta['reused_browser'] = not meta['created_browser'] and not meta['attached_browser']
        except Exception:
            if mode == 'attach':
                raise
            if not create_if_missing:
                raise
            self._browser.page_state().page = self._browser.open_page(target_url, profile_name=self._browser.active_profile())
            meta['created_browser'] = True
            meta['reused_browser'] = False
            meta['navigated'] = True
            tab = self._browser.page_state().page.get_tab(self._browser.page_state().page.latest_tab)
            self.set_browser_instance(None)

        if not meta.get('debug_address'):
            meta['debug_address'] = self._browser.normalize_address(self.gui_page_debug_address())

        if navigate and url:
            tab.get(url)
            meta['navigated'] = True

        return tab, meta

    def snapshot_context(self, tab, locator=None, locator_type='raw', limit=5, include_html=False):
        page_bits = _collect_browser_page_bits(tab)
        session = self.get_session(create=False)
        context = {
            'session': serialize_session(session, include_events=True, recent_event_count=15),
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
            context['query'] = query_elements(
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

    def capture_artifacts(self, tab, label='snapshot', include_html=True, session_label='manual'):
        session = self.get_session(create=True, label=session_label)
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
                context = self.snapshot_context(tab, include_html=False)
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

        self.append_event(
            'artifact',
            f'Captured browser artifacts for {label}',
            data=artifacts,
            session_id=session.get('session_id')
        )
        return artifacts

    def record_automation_error(self, stage, error, traceback_text, tab=None, extra=None):
        session = self.get_session(create=True, label='upload-error')
        artifacts = self.capture_artifacts(
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
            'page': self.snapshot_context(tab, include_html=False) if tab else None,
            'extra': extra or {},
            'session': serialize_session(session, include_events=True, recent_event_count=20),
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

        self.set_last_error(report)
        self.append_event(
            'automation_error',
            f'Automation failed at stage: {stage}',
            data={
                'error': str(error),
                'report_path': report.get('report_path'),
            },
            session_id=session.get('session_id')
        )
        return report

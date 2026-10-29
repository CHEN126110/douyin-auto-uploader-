# -*- coding: utf-8 -*-
"""CDP 调试浏览器接口（/api/debug/browser/*）：确保 / 启动 / 查询 / 等待 / 操作 / 截图 / 读取最近一次错误。

这些接口只做 HTTP 适配；状态与浏览器能力都在 ``BrowserDebugService``（见 debug_browser_service.py）。"""
import time

from flask import Blueprint, request

from .debug_browser_service import (
    debug_bool,
    debug_int,
    get_target_element,
    query_elements,
    serialize_session,
    wait_for_condition,
)
from .responses import api_error, api_ok


def create_debug_browser_blueprint(*, service):
    """``service`` 是 ``BrowserDebugService``：调试会话状态和浏览器能力都由它持有。"""
    routes = Blueprint('debug_browser', __name__)

    @routes.post('/api/debug/browser/ensure')
    def debug_browser_ensure():
        data = request.get_json(silent=True) or {}
        label = data.get('label') or 'manual'
        new_session = debug_bool(data.get('new_session'))
        create_browser = debug_bool(data.get('create_browser'), True)
        navigate = debug_bool(data.get('navigate'))
        mode = str(data.get('mode') or 'managed').strip().lower()
        debug_address = (data.get('debug_address') or '').strip() or None
        existing_only = debug_bool(data.get('existing_only'), mode == 'attach')
        url = (data.get('url') or '').strip() or None

        session = service.create_session(label) if new_session else service.get_session(create=True, label=label)

        try:
            tab, meta = service.get_current_tab(
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

        snapshot = service.snapshot_context(
            tab,
            limit=debug_int(data.get('limit'), 5, minimum=1, maximum=20),
            include_html=debug_bool(data.get('include_html'))
        )
        service.append_event(
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
            'session': serialize_session(session, include_events=True, recent_event_count=10),
            'browser': meta,
            'snapshot': snapshot,
        })

    @routes.get('/api/debug/browser/discover')
    def debug_browser_discover():
        verify = debug_bool(request.args.get('verify'), True)
        browsers = service.browser.discover_browsers(verify=verify)
        return api_ok('Discover debug browsers completed.', data={
            'count': len(browsers),
            'browsers': browsers,
        })

    @routes.post('/api/debug/browser/launch')
    def debug_browser_launch():
        data = request.get_json(silent=True) or {}
        label = data.get('label') or 'launch'
        new_session = debug_bool(data.get('new_session'))
        navigate = debug_bool(data.get('navigate'), bool(data.get('url')))
        reuse_existing = debug_bool(data.get('reuse_existing'), True)
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

        session = service.create_session(label) if new_session else service.get_session(create=True, label=label)

        try:
            launched_browser = service.launch_attachable_browser(
                browser_path=browser_path,
                port=port,
                url=url,
                user_data_dir=user_data_dir,
                profile_name=profile_name,
                timeout=timeout,
                reuse_existing=reuse_existing,
            )
            service.set_browser_instance(launched_browser)
            tab, meta = service.get_current_tab(
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

        snapshot = service.snapshot_context(
            tab,
            limit=debug_int(data.get('limit'), 5, minimum=1, maximum=20),
            include_html=debug_bool(data.get('include_html'))
        )
        service.append_event(
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
            'session': serialize_session(session, include_events=True, recent_event_count=10),
            'browser': meta,
            'launched_browser': launched_browser,
            'snapshot': snapshot,
        })

    @routes.get('/api/debug/browser/session')
    def debug_browser_session():
        session = service.get_session(create=False)
        return api_ok('Current browser debug session loaded.', data={
            'session': serialize_session(session, include_events=True, recent_event_count=30),
            'browser_instance': service.get_browser_instance(),
            'last_error': service.get_last_error(),
        })

    @routes.get('/api/debug/browser/context')
    def debug_browser_context():
        include_html = debug_bool(request.args.get('include_html'))
        locator = request.args.get('locator')
        locator_type = request.args.get('locator_type') or 'raw'
        limit = debug_int(request.args.get('limit'), 5, minimum=1, maximum=20)

        try:
            tab, _ = service.get_current_tab(create_if_missing=False)
        except Exception as exc:
            return api_error(f'Failed to access browser: {str(exc)}')

        if not tab:
            return api_error('Browser is not running.')

        snapshot = service.snapshot_context(
            tab,
            locator=locator,
            locator_type=locator_type,
            limit=limit,
            include_html=include_html
        )
        return api_ok('Browser context loaded.', data=snapshot)

    @routes.post('/api/debug/browser/query')
    def debug_browser_query():
        data = request.get_json(silent=True) or {}
        locator = data.get('locator')
        if not locator:
            return api_error('Locator is required.')

        locator_type = data.get('locator_type') or 'raw'
        include_html = debug_bool(data.get('include_html'))
        only_visible = debug_bool(data.get('only_visible'), True)
        limit = debug_int(data.get('limit'), 10, minimum=1, maximum=50)

        try:
            timeout = float(data.get('timeout') or 1.0)
        except Exception:
            timeout = 1.0
        timeout = max(0.1, min(timeout, 5.0))

        try:
            tab, _ = service.get_current_tab(create_if_missing=debug_bool(data.get('create_browser')))
        except Exception as exc:
            return api_error(f'Failed to access browser: {str(exc)}')

        if not tab:
            return api_error('Browser is not running.')

        try:
            result = query_elements(
                tab,
                locator,
                locator_type=locator_type,
                timeout=timeout,
                limit=limit,
                include_html=include_html,
                only_visible=only_visible
            )
            service.append_event(
                'query',
                f'Queried locator: {result.get("locator")}',
                data={
                    'match_count': result.get('match_count'),
                    'only_visible': only_visible,
                }
            )
            return api_ok('Browser element query completed.', data={
                'query': result,
                'snapshot': service.snapshot_context(tab, limit=min(limit, 10), include_html=False),
            })
        except Exception as exc:
            artifacts = service.capture_artifacts(tab, label='query_failed', include_html=True)
            return api_error(
                f'Failed to query browser elements: {str(exc)}',
                data={'artifacts': artifacts}
            )

    @routes.post('/api/debug/browser/wait')
    def debug_browser_wait():
        data = request.get_json(silent=True) or {}
        condition = str(data.get('condition') or '').strip().lower()
        if not condition:
            return api_error('condition is required.')

        locator = data.get('locator')
        locator_type = data.get('locator_type') or 'raw'
        expected_text = data.get('text')
        only_visible = debug_bool(data.get('only_visible'), True)
        count = debug_int(data.get('count'), 1, minimum=0, maximum=50)
        include_html = debug_bool(data.get('include_html'))
        capture_on_timeout = debug_bool(data.get('capture_on_timeout'), True)

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
            tab, meta = service.get_current_tab(
                create_if_missing=debug_bool(data.get('create_browser')),
                url=(data.get('url') or '').strip() or None,
                navigate=debug_bool(data.get('navigate'))
            )
        except Exception as exc:
            return api_error(f'Failed to access browser: {str(exc)}')

        if not tab:
            return api_error('Browser is not running.')

        try:
            matched, wait_state = wait_for_condition(
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
            snapshot = service.snapshot_context(
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
                service.append_event(
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
                artifacts = service.capture_artifacts(
                    tab,
                    label=f'wait_{condition}_timeout',
                    include_html=include_html,
                    session_label='manual'
                )
            payload['artifacts'] = artifacts
            service.append_event(
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
            artifacts = service.capture_artifacts(
                tab,
                label=f'wait_{condition}_failed',
                include_html=True,
                session_label='manual'
            )
            service.append_event(
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

    @routes.post('/api/debug/browser/action')
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
        element_index = debug_int(data.get('index'), 0, minimum=0, maximum=50)
        only_visible = debug_bool(data.get('only_visible'), True)
        value = data.get('value')

        try:
            tab, meta = service.get_current_tab(
                create_if_missing=debug_bool(data.get('create_browser')),
                url=(data.get('url') or '').strip() or None,
                navigate=debug_bool(data.get('navigate'))
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

                target, normalized_locator, match_count = get_target_element(
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
                    target.click(by_js=debug_bool(data.get('by_js'), True))
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
                    target.input(str(value), clear=debug_bool(data.get('clear'), True))
                else:
                    return api_error(f'Unsupported action: {action}')

            time.sleep(0.1)
            snapshot = service.snapshot_context(
                tab,
                locator=locator if action != 'navigate' else None,
                locator_type=locator_type,
                limit=5,
                include_html=False
            )
            service.append_event(
                'action',
                f'Executed browser action: {action}',
                data=action_result
            )
            return api_ok('Browser action completed.', data={
                'result': action_result,
                'snapshot': snapshot,
            })
        except Exception as exc:
            artifacts = service.capture_artifacts(tab, label=f'action_{action}_failed', include_html=True)
            service.append_event(
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

    @routes.post('/api/debug/browser/capture')
    def debug_browser_capture():
        data = request.get_json(silent=True) or {}
        label = data.get('label') or 'manual_capture'
        include_html = debug_bool(data.get('include_html'), True)

        try:
            tab, _ = service.get_current_tab(create_if_missing=False)
        except Exception as exc:
            return api_error(f'Failed to access browser: {str(exc)}')

        if not tab:
            return api_error('Browser is not running.')

        artifacts = service.capture_artifacts(
            tab,
            label=label,
            include_html=include_html,
            session_label=data.get('session_label') or 'manual'
        )
        return api_ok('Browser artifacts captured.', data=artifacts)

    @routes.get('/api/debug/browser/last-error')
    def debug_browser_last_error():
        report = service.get_last_error()
        if not report:
            return api_ok('No browser debug error report is available.', data=None)
        return api_ok('Latest browser debug error report loaded.', data=report)

    return routes

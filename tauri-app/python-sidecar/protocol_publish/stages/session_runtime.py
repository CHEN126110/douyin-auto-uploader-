from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


ArtifactWriter = Callable[[Any, str, str, Any, str], Any]


@dataclass(slots=True)
class PublishSessionStageDependencies:
    get_gui_page: Callable[[], Any]
    set_gui_page: Callable[[Any], Any]
    get_page: Callable[[str], Any]
    wait_login_complete: Callable[[Any, Any], bool]
    get_current_tab_url: Callable[[Any], str]


class PublishSessionStageExecutor:
    def __init__(self, dependencies: PublishSessionStageDependencies) -> None:
        self._deps = dependencies

    def execute(
        self,
        *,
        report_progress: Callable[[int, str], Any],
        publish_create_url: str,
        protocol_runtime: Any = None,
        artifact_writer: ArtifactWriter | None = None,
    ) -> dict[str, Any]:
        page = self._deps.get_gui_page()
        created_new_page = False
        restored_page = False

        if not page:
            report_progress(13, '正在启动浏览器并检查登录状态')
            page = self._deps.get_page(publish_create_url)
            self._deps.set_gui_page(page)
            created_new_page = True
            if not self._deps.wait_login_complete(page, report_progress):
                result = {
                    'ok': False,
                    'created_new_page': created_new_page,
                    'restored_page': restored_page,
                    'error': '超时未登录！！！',
                }
                self._write_artifact(artifact_writer, protocol_runtime, 'session', 'session-probe', result, 'session-probe')
                return result

        try:
            main_tab = page.get_tab(page.latest_tab)
        except Exception:
            report_progress(13, '正在恢复浏览器会话并检查登录状态')
            page = self._deps.get_page(publish_create_url)
            self._deps.set_gui_page(page)
            restored_page = True
            if not self._deps.wait_login_complete(page, report_progress):
                result = {
                    'ok': False,
                    'created_new_page': created_new_page,
                    'restored_page': restored_page,
                    'error': '超时未登录！！！',
                }
                self._write_artifact(artifact_writer, protocol_runtime, 'session', 'session-probe', result, 'session-probe')
                return result
            main_tab = page.get_tab(page.latest_tab)

        try:
            page.close_tabs(main_tab, others=True)
        except Exception:
            pass

        result = {
            'ok': True,
            'created_new_page': created_new_page,
            'restored_page': restored_page,
            'page_url': self._deps.get_current_tab_url(main_tab),
            'debug_address': '',
            'captured_at': datetime.now().isoformat(),
        }
        try:
            result['debug_address'] = str(getattr(getattr(main_tab, 'browser', None), 'address', '') or '')
        except Exception:
            result['debug_address'] = ''
        self._write_artifact(artifact_writer, protocol_runtime, 'session', 'session-probe', result, 'session-probe')
        result['main_tab'] = main_tab
        return result

    def _write_artifact(
        self,
        artifact_writer: ArtifactWriter | None,
        protocol_runtime: Any,
        stage: str,
        name: str,
        payload: Any,
        artifact_type: str,
    ) -> None:
        if not callable(artifact_writer):
            return
        artifact_writer(protocol_runtime, stage, name, payload, artifact_type=artifact_type)

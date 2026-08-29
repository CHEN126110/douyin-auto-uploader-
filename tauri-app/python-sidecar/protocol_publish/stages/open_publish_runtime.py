from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


ArtifactWriter = Callable[[Any, str, str, Any, str], Any]


@dataclass(slots=True)
class OpenPublishPageStageDependencies:
    wait_until: Callable[..., bool]
    dismiss_interfering_overlays: Callable[..., Any]
    get_current_tab_url: Callable[..., str]
    detect_publish_page_stage: Callable[..., str]
    find_first_visible_element: Callable[..., Any]
    click_element_safely: Callable[..., bool]


class OpenPublishPageStageExecutor:
    def __init__(self, dependencies: OpenPublishPageStageDependencies) -> None:
        self._deps = dependencies

    def execute(
        self,
        *,
        main_tab: Any,
        report_progress: Callable[[int, str], Any],
        publish_create_url: str,
        protocol_runtime: Any = None,
        artifact_writer: ArtifactWriter | None = None,
    ) -> dict[str, Any]:
        print('打开商品发布页面...')
        try:
            report_progress(22, '正在检查商品发布页面')
        except Exception:
            pass

        try:
            main_tab.handle_alert(next_one=True)
        except Exception:
            pass

        before = self._build_probe(main_tab)
        self._write_artifact(
            artifact_writer,
            protocol_runtime,
            'open_publish_page',
            'before-open',
            before,
            'open-publish-probe',
        )

        stage = before['stage']
        current_url = before['page_url']
        stabilized = False
        navigated = False
        navigation_reason = 'already-step1'

        if stage == 'unknown' and '/ffa/g/create' in current_url:
            try:
                report_progress(22, '正在等待发布页状态稳定')
            except Exception:
                pass
            stabilized = self._deps.wait_until(
                lambda: self._deps.detect_publish_page_stage(main_tab) in ('step1', 'step2'),
                timeout=1.2,
                interval=0.05,
            )
            stage = self._deps.detect_publish_page_stage(main_tab)

        if stage == 'step1':
            ready = True
        elif stage == 'step2':
            navigation_reason = 'reset-from-step2'
            navigated = True
            try:
                report_progress(22, '检测到停留在第二页面，正在返回第一页')
            except Exception:
                pass
            main_tab.get(publish_create_url)
            ready = self._deps.wait_until(
                lambda: self._deps.detect_publish_page_stage(main_tab) == 'step1',
                timeout=10,
                interval=0.05,
            )
        else:
            navigation_reason = f'open-from-{stage}'
            navigated = True
            try:
                report_progress(22, '正在打开商品发布第一页')
            except Exception:
                pass
            main_tab.get(publish_create_url)
            ready = self._deps.wait_until(
                lambda: self._deps.detect_publish_page_stage(main_tab) in ('step1', 'step2'),
                timeout=10,
                interval=0.05,
            )
            if ready and self._deps.detect_publish_page_stage(main_tab) == 'step2':
                navigation_reason = f'{navigation_reason}-step2-reset'
                main_tab.get(publish_create_url)
                ready = self._deps.wait_until(
                    lambda: self._deps.detect_publish_page_stage(main_tab) == 'step1',
                    timeout=10,
                    interval=0.05,
                )

        if not ready:
            after_failed = self._build_probe(main_tab)
            after_failed.update({
                'stabilized_before_navigation': stabilized,
                'navigated': navigated,
                'navigation_reason': navigation_reason,
                'ready': False,
            })
            self._write_artifact(
                artifact_writer,
                protocol_runtime,
                'open_publish_page',
                'after-open',
                after_failed,
                'open-publish-probe',
            )
            return after_failed

        self._deps.dismiss_interfering_overlays(main_tab, context='open_publish_page')
        republish_clicked = False
        try:
            republish_btn = self._deps.find_first_visible_element(
                main_tab,
                ['xpath://span[text()="重新发布"]/../..'],
                timeout=0.15,
            )
            if republish_btn and self._deps.click_element_safely(republish_btn):
                republish_clicked = True
                self._deps.dismiss_interfering_overlays(main_tab, context='republish')
        except Exception:
            pass

        after = self._build_probe(main_tab)
        after.update({
            'stabilized_before_navigation': stabilized,
            'navigated': navigated,
            'navigation_reason': navigation_reason,
            'republish_clicked': republish_clicked,
            'ready': after['stage'] == 'step1',
        })
        self._write_artifact(
            artifact_writer,
            protocol_runtime,
            'open_publish_page',
            'after-open',
            after,
            'open-publish-probe',
        )
        return after

    def _build_probe(self, main_tab: Any) -> dict[str, Any]:
        return {
            'captured_at': datetime.now().isoformat(),
            'page_url': self._deps.get_current_tab_url(main_tab),
            'stage': self._deps.detect_publish_page_stage(main_tab),
        }

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

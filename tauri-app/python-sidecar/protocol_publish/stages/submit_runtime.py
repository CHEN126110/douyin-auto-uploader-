from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


ArtifactWriter = Callable[[Any, str, str, Any, str], Any]


@dataclass(slots=True)
class SubmitPublishStageDependencies:
    dismiss_interfering_overlays: Callable[..., Any]
    wait_until: Callable[..., bool]
    get_current_tab_url: Callable[..., str]


class SubmitPublishStageExecutor:
    def __init__(self, dependencies: SubmitPublishStageDependencies) -> None:
        self._deps = dependencies

    def execute(
        self,
        *,
        main_tab: Any,
        record: Any,
        protocol_runtime: Any = None,
        artifact_writer: ArtifactWriter | None = None,
    ) -> dict[str, Any]:
        print('发布商品')
        self._deps.dismiss_interfering_overlays(main_tab, context='submit_publish')
        before = self._build_probe(main_tab, record)
        self._write_artifact(
            artifact_writer,
            protocol_runtime,
            'submit',
            'before-submit',
            before,
            'submit-probe',
        )

        main_tab.ele('xpath://span[text()="发布商品"]/..').click()
        self._deps.wait_until(
            lambda: self._is_publish_reminder_visible(main_tab)
            or self._is_publish_success_visible(main_tab)
            or self._has_publish_validation_error(main_tab),
            timeout=1.2,
            interval=0.05,
        )
        self._deps.dismiss_interfering_overlays(main_tab, context='after_publish_click')

        reminder_handled = self._handle_publish_reminder(main_tab)

        publish_ok = self._deps.wait_until(
            lambda: self._is_publish_success_visible(main_tab),
            timeout=12,
            interval=0.25,
        )

        if publish_ok:
            print('发布成功！')
            record.status = 1
            record.publish_time = datetime.now()
            record.save()
            after = self._build_probe(main_tab, record)
            after.update({
                'status': 'ok',
                'reminder_handled': reminder_handled,
            })
            self._write_artifact(
                artifact_writer,
                protocol_runtime,
                'submit',
                'after-submit',
                after,
                'submit-probe',
            )
            return after

        failure_messages = self._collect_failure_messages(main_tab)
        if failure_messages:
            failure_reason = '提交校验失败：' + '；'.join(failure_messages[:5])
        else:
            failure_reason = '提交发布后未检测到成功结果'

        after = self._build_probe(main_tab, record)
        after.update({
            'status': 'failed',
            'reminder_handled': reminder_handled,
            'failure_messages': failure_messages[:5],
            'failure_reason': failure_reason,
        })
        self._write_artifact(
            artifact_writer,
            protocol_runtime,
            'submit',
            'after-submit',
            after,
            'submit-probe',
        )
        print(f'发布失败：{failure_reason}')
        raise Exception(failure_reason)

    def _build_probe(self, main_tab: Any, record: Any) -> dict[str, Any]:
        return {
            'captured_at': datetime.now().isoformat(),
            'page_url': self._deps.get_current_tab_url(main_tab),
            'record_id': getattr(record, 'id', None),
            'record_name': getattr(record, 'name', ''),
        }

    def _is_publish_success_visible(self, main_tab: Any) -> bool:
        return bool(main_tab.ele('商品提交成功，继续发布商品视频，分享到抖音', timeout=0.1))

    def _is_publish_reminder_visible(self, main_tab: Any) -> bool:
        try:
            modal = main_tab.ele('xpath://div[@class="ecom-g-modal-title"][text()="发布提醒"]/../..', timeout=0.1)
        except Exception:
            modal = None
        return bool(modal)

    def _has_publish_validation_error(self, main_tab: Any) -> bool:
        selectors = [
            'xpath://div[@attr-field-id and (.//*[contains(@class,"style_errorSubTitle__")] or .//*[contains(@class,"ant-form-item-explain-error")] or contains(@class,"has-error"))]',
            'xpath://span[contains(@class,"style_errorSubTitle__")]',
            'xpath://div[contains(@class,"ant-form-item-explain-error")]//*[string-length(normalize-space()) > 0]',
        ]
        for selector in selectors:
            try:
                if main_tab.ele(selector, timeout=0.08):
                    return True
            except Exception:
                continue
        return False

    def _handle_publish_reminder(self, main_tab: Any) -> bool:
        try:
            modal = main_tab.ele('xpath://div[@class="ecom-g-modal-title"][text()="发布提醒"]/../..', timeout=0.3)
            if not modal:
                return False
            continue_btn = modal.ele('xpath:.//div[text()="不修改，继续发布"]/ancestor::button')
            continue_btn.scroll.to_center()
            continue_btn.click()
            print('已处理发布提醒弹窗')
            return True
        except Exception as exc:
            print(f'未出现弹窗或处理失败: {str(exc)}')
            return False

    def _collect_failure_messages(self, main_tab: Any) -> list[str]:
        failure_messages: list[str] = []

        try:
            field_nodes = main_tab.eles(
                'xpath://div[@attr-field-id and (.//*[contains(@class,"style_errorSubTitle__")] or .//*[contains(@class,"ant-form-item-explain-error")] or contains(@class,"has-error"))]',
                timeout=0.5,
            )
        except Exception:
            field_nodes = []

        for field_node in field_nodes:
            try:
                field_id = str(field_node.attr('attr-field-id') or '').strip()
            except Exception:
                field_id = ''

            error_texts: list[str] = []
            try:
                error_nodes = field_node.eles(
                    'xpath:.//*[contains(@class,"style_errorSubTitle__") or contains(@class,"ant-form-item-explain-error") or contains(text(),"请输入") or contains(text(),"请上传") or contains(text(),"请选择")]',
                    timeout=0.2,
                )
            except Exception:
                error_nodes = []

            for error_node in error_nodes:
                try:
                    raw_text = str(error_node.text or '').strip()
                except Exception:
                    raw_text = ''
                normalized = ' '.join(raw_text.split())
                if normalized and normalized not in error_texts:
                    error_texts.append(normalized)

            if error_texts:
                if field_id:
                    failure_messages.append(f'{field_id}: {error_texts[0]}')
                else:
                    failure_messages.append(error_texts[0])

        if failure_messages:
            return failure_messages

        try:
            error_nodes = main_tab.eles(
                'xpath://span[contains(@class,"style_errorSubTitle__")] | //div[contains(@class,"ant-form-item-explain-error")]//*[string-length(normalize-space()) > 0]',
                timeout=0.5,
            )
        except Exception:
            error_nodes = []

        for error_node in error_nodes:
            try:
                raw_text = str(error_node.text or '').strip()
            except Exception:
                raw_text = ''
            normalized = ' '.join(raw_text.split())
            if normalized and normalized not in failure_messages:
                failure_messages.append(normalized)
            if len(failure_messages) >= 5:
                break

        return failure_messages

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

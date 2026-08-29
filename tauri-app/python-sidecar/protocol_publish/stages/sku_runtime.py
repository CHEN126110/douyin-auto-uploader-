from __future__ import annotations

import time as native_time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


ArtifactWriter = Callable[[Any, str, str, Any, str], Any]


@dataclass(slots=True)
class SkuStageDependencies:
    dismiss_interfering_overlays: Callable[..., Any]
    wait_until: Callable[..., bool]
    timer_record: Callable[..., Any]
    get_current_tab_url: Callable[..., str]
    set_sku_info: Callable[..., Any]


class SkuEntriesStageExecutor:
    def __init__(self, dependencies: SkuStageDependencies) -> None:
        self._deps = dependencies

    def execute(
        self,
        *,
        main_tab: Any,
        sku_list: list[dict[str, Any]],
        remark: str,
        protocol_runtime: Any = None,
        artifact_writer: ArtifactWriter | None = None,
    ) -> dict[str, Any]:
        stage_timer_start = native_time.time()
        self._deps.dismiss_interfering_overlays(main_tab, context='configure_sku_entries')
        before = self._build_probe(main_tab, sku_list)
        self._write_artifact(artifact_writer, protocol_runtime, 'sku_entries', 'before-write', before, 'sku-probe')

        main_tab.ele('xpath://span[text()="价格与库存"]').scroll.to_see()

        print('选择发货时间 -> 48小时')
        ship_time = main_tab.ele('xpath://span[text()="48小时"]', timeout=1)
        if not ship_time:
            raise Exception('未找到发货时间选项：48小时')
        ship_time.click()

        print('勾选添加规格图片')
        add_spec_image = main_tab.ele('xpath://span[text()="添加规格图"]', timeout=1)
        if not add_spec_image:
            raise Exception('未找到添加规格图开关')
        add_spec_image.click(by_js=True)

        self._clear_existing_color_specs(main_tab)

        for index, sku in enumerate(sku_list):
            self._deps.set_sku_info(main_tab, index, sku, remark)

        after = self._build_probe(main_tab, sku_list)
        after.update({
            'status': 'ok',
            'duration_ms': round((native_time.time() - stage_timer_start) * 1000, 2),
        })
        self._write_artifact(artifact_writer, protocol_runtime, 'sku_entries', 'after-write', after, 'sku-probe')
        return after

    def _clear_existing_color_specs(self, main_tab: Any) -> None:
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
                return

            before_count = len(visible_buttons)
            visible_buttons[-1].click(by_js=True)
            if not self._deps.wait_until(
                lambda: self._count_visible_delete_buttons(main_tab) < before_count,
                timeout=0.8,
                interval=0.04,
            ):
                continue

    def _count_visible_delete_buttons(self, main_tab: Any) -> int:
        buttons = main_tab.eles('xpath://div[@id="skuValue-颜色分类"]//span[@data-kora="删除规格值"]', timeout=0.1) or []
        count = 0
        for btn in buttons:
            try:
                if btn and btn.states.is_displayed:
                    count += 1
            except Exception:
                continue
        return count

    def _build_probe(self, main_tab: Any, sku_list: list[dict[str, Any]]) -> dict[str, Any]:
        delete_count = self._count_visible_delete_buttons(main_tab)
        return {
            'captured_at': datetime.now().isoformat(),
            'page_url': self._deps.get_current_tab_url(main_tab),
            'sku_count': len(sku_list),
            'configured_skus': [str(item.get('name', '')).strip() for item in sku_list],
            'visible_delete_button_count': delete_count,
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


class SkuStructureStageExecutor:
    def __init__(self, dependencies: SkuStageDependencies) -> None:
        self._deps = dependencies

    def execute(
        self,
        *,
        main_tab: Any,
        protocol_runtime: Any = None,
        artifact_writer: ArtifactWriter | None = None,
    ) -> dict[str, Any]:
        stage_timer_start = native_time.time()
        self._deps.dismiss_interfering_overlays(main_tab, context='configure_sku_structure')
        before = self._build_probe(main_tab)
        self._write_artifact(artifact_writer, protocol_runtime, 'sku_structure', 'before-write', before, 'sku-structure-probe')

        if self._has_price_stock_rows(main_tab):
            after = self._build_probe(main_tab)
            after.update({
                'status': 'ok',
                'structure_ready_reason': 'price_stock_rows_ready',
                'duration_ms': round((native_time.time() - stage_timer_start) * 1000, 2),
            })
            self._write_artifact(artifact_writer, protocol_runtime, 'sku_structure', 'after-write', after, 'sku-structure-probe')
            return after

        print('选择均码')
        size_input = main_tab.ele('xpath://div[@id="skuValue-码数"]//input', timeout=1)
        if not size_input:
            raise Exception('未找到码数输入框')
        size_input.scroll.to_center()
        size_input.click()

        if not self._deps.wait_until(
            lambda: len(main_tab.eles('xpath://li[@title="均码"]', timeout=0.05) or []) >= 1,
            timeout=1.2,
            interval=0.04,
        ):
            raise Exception('未找到均码选项')

        options = main_tab.eles('xpath://li[@title="均码"]', timeout=0.2) or []
        visible_options = []
        for option in options:
            try:
                if option and option.states.is_displayed:
                    visible_options.append(option)
            except Exception:
                continue

        if not visible_options:
            raise Exception('均码选项不可见')

        visible_options[0].click()
        if len(visible_options) > 1:
            visible_options[-1].click()

        confirm_button = None

        def _structure_progressed() -> bool:
            nonlocal confirm_button
            try:
                buttons = main_tab.eles(
                    'xpath://div[contains(@class,"styles_popupFooter__")]//button[.//span[starts-with(text(), "确定")]]',
                    timeout=0.05,
                ) or []
            except Exception:
                buttons = []
            confirm_button = self._first_interactable_button(buttons)
            if confirm_button is not None:
                return True
            return self._has_size_tag(main_tab, '均码')

        if not self._deps.wait_until(_structure_progressed, timeout=1.2, interval=0.04):
            raise Exception('选择均码后未检测到结构变化')

        if confirm_button:
            confirm_button.click()
            if not self._deps.wait_until(
                lambda: not self._is_confirm_button_visible(main_tab) or self._has_size_tag(main_tab, '均码'),
                timeout=1.2,
                interval=0.04,
            ):
                raise Exception('码数结构确认后弹窗未关闭')

        self._deps.dismiss_interfering_overlays(main_tab, context='configure_sku_structure')
        after = self._build_probe(main_tab)
        after.update({
            'status': 'ok',
            'duration_ms': round((native_time.time() - stage_timer_start) * 1000, 2),
        })
        self._write_artifact(artifact_writer, protocol_runtime, 'sku_structure', 'after-write', after, 'sku-structure-probe')
        return after

    def _is_confirm_button_visible(self, main_tab: Any) -> bool:
        try:
            buttons = main_tab.eles(
                'xpath://div[contains(@class,"styles_popupFooter__")]//button[.//span[starts-with(text(), "确定")]]',
                timeout=0.05,
            ) or []
        except Exception:
            buttons = []
        return self._first_interactable_button(buttons) is not None

    def _first_interactable_button(self, buttons: list[Any]) -> Any | None:
        for button in buttons:
            try:
                if not button or not button.states.is_displayed:
                    continue
                class_name = str(button.attr('class') or '')
                disabled_attr = button.attr('disabled')
                if disabled_attr is not None or 'disabled' in class_name:
                    continue
                return button
            except Exception:
                continue
        return None

    def _has_size_tag(self, main_tab: Any, size_text: str) -> bool:
        selectors = [
            f'xpath://div[@id="skuValue-码数"]//*[normalize-space(text())="{size_text}"]',
            f'xpath://div[@id="skuValue-码数"]//span[normalize-space(text())="{size_text}"]',
            f'xpath://div[@id="skuValue-码数"]//li[@title="{size_text}"]',
        ]
        for selector in selectors:
            try:
                if main_tab.ele(selector, timeout=0.05):
                    return True
            except Exception:
                continue
        return False

    def _has_price_stock_rows(self, main_tab: Any) -> bool:
        try:
            price_stock_root = main_tab.ele('xpath://div[@attr-field-id="价格与库存"]', timeout=0.2)
        except Exception:
            price_stock_root = None
        if not price_stock_root:
            return False
        try:
            rows = price_stock_root.eles(
                'xpath:.//tr[contains(@class,"ecom-g-table-row") and .//td[contains(@class,"attr-column-field_price")]//input and .//td[contains(@class,"attr-column-field_stock_info")]//input]',
                timeout=0.2,
            ) or []
        except Exception:
            rows = []
        for row in rows:
            try:
                if row and row.states.is_displayed:
                    return True
            except Exception:
                continue
        return False

    def _build_probe(self, main_tab: Any) -> dict[str, Any]:
        return {
            'captured_at': datetime.now().isoformat(),
            'page_url': self._deps.get_current_tab_url(main_tab),
            'has_size_tag_junma': self._has_size_tag(main_tab, '均码'),
            'has_price_stock_rows': self._has_price_stock_rows(main_tab),
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

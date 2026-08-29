from __future__ import annotations

import json
import os
import re
import time as native_time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from .price_stock_protocol import (
    arm_price_stock_protocol_capture,
    read_price_stock_protocol_capture,
    replay_price_stock_protocol_request,
    reset_price_stock_protocol_capture,
)


ArtifactWriter = Callable[[Any, str, str, Any, str], Any]


@dataclass(slots=True)
class PriceStockStageDependencies:
    dismiss_interfering_overlays: Callable[..., Any]
    select_text: Callable[..., Any]
    wait_until: Callable[..., bool]
    timer_record: Callable[..., Any]
    get_current_tab_url: Callable[..., str]


def _xpath_text_literal(value: Any) -> str:
    value = str(value)
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ', "\'", '.join([f"'{part}'" for part in parts]) + ")"


def _normalize_numeric_text(value: Any) -> str:
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


def _normalize_price_stock_text(value: Any) -> str:
    return ' '.join(str(value or '').split()).strip()


def _normalize_price_stock_size_text(value: Any) -> str:
    normalized = _normalize_price_stock_text(value)
    while normalized:
        updated = re.sub(r'\s*[（(][^（）()]*[）)]\s*$', '', normalized).strip()
        if updated == normalized:
            break
        normalized = updated
    return normalized


def _split_price_stock_sku_name(value: Any) -> tuple[str, str]:
    normalized = _normalize_price_stock_text(value)
    if not normalized:
        return '', ''
    parts = [part.strip() for part in re.split(r'\s+/\s+', normalized) if part.strip()]
    if len(parts) >= 2:
        return ' / '.join(parts[:-1]).strip(), _normalize_price_stock_size_text(parts[-1])
    return normalized, ''


def _build_price_stock_name_core_variants(value: Any) -> list[str]:
    candidates: list[str] = []
    normalized = _normalize_price_stock_text(value)
    if normalized:
        candidates.append(normalized)

    current = normalized
    while current:
        updated = re.sub(r'\s*[\uFF08(][^\uFF08\uFF09()]*[\uFF09)]\s*$', '', current).strip()
        if not updated or updated == current:
            break
        candidates.append(updated)
        current = updated

    base_name, _ = _split_price_stock_sku_name(normalized)
    if base_name:
        candidates.append(base_name.strip())

    seen: list[str] = []
    for item in candidates:
        item = _normalize_price_stock_text(item)
        if item and item not in seen:
            seen.append(item)
    return seen


def _canonicalize_price_stock_row_identity(name_text: Any, size_text: Any) -> tuple[str, str]:
    normalized_name = _normalize_price_stock_text(name_text)
    normalized_size = _normalize_price_stock_size_text(size_text)
    inline_name, inline_size = _split_price_stock_sku_name(normalized_name)
    normalized_inline_name = inline_name.strip()
    normalized_inline_size = _normalize_price_stock_size_text(inline_size)

    if not normalized_size and normalized_inline_size:
        normalized_size = normalized_inline_size

    if normalized_inline_name:
        if not normalized_size or (normalized_inline_size and normalized_inline_size == normalized_size):
            normalized_name = normalized_inline_name

    normalized_name_variants = _build_price_stock_name_core_variants(normalized_name)
    if normalized_name_variants:
        normalized_name = normalized_name_variants[0]
    return normalized_name, normalized_size


def _build_price_stock_name_variants(value: Any) -> set[str]:
    return set(_build_price_stock_name_core_variants(value))


class PriceStockStageExecutor:
    def __init__(self, dependencies: PriceStockStageDependencies) -> None:
        self._deps = dependencies

    def execute(
        self,
        *,
        main_tab: Any,
        record: Any,
        sku_list: list[dict[str, Any]],
        shipping_template_name: str,
        protocol_runtime: Any = None,
        artifact_writer: ArtifactWriter | None = None,
    ) -> dict[str, Any]:
        print('设置价格和库存...')
        stage_timer_start = native_time.time()
        self._deps.dismiss_interfering_overlays(main_tab, context='fill_price_and_stock')
        price_stock_root, holder = self._get_price_stock_context(main_tab)
        before_snapshot = self._build_probe_snapshot(main_tab, record, sku_list, price_stock_root, holder)
        self._write_artifact(
            artifact_writer,
            protocol_runtime,
            'price_stock',
            'dom-probe-before-write',
            before_snapshot,
            'price-stock-dom-probe',
        )
        write_mode = str(os.getenv('DYIN_PRICE_STOCK_WRITE_MODE') or 'dom').strip().lower()
        if write_mode == 'dom':
            write_result = self._execute_dom_price_stock_write(main_tab=main_tab, record=record, sku_list=sku_list)
        else:
            write_result = self._execute_protocol_price_stock_write(
                main_tab=main_tab,
                record=record,
                sku_list=sku_list,
                protocol_runtime=protocol_runtime,
                artifact_writer=artifact_writer,
            )

        main_tab.ele('xpath://span[text()="售后服务承诺"]').scroll.to_see()

        self._deps.select_text(main_tab, '运费模板', shipping_template_name, '包邮')

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
                    rate_input = None

                    def _probe_rate_input() -> bool:
                        nonlocal rate_input
                        try:
                            rate_input = main_tab.ele('xpath://label[@title="佣金率"]/../..//input', timeout=0.05)
                        except Exception:
                            rate_input = None
                        return bool(rate_input)

                    self._deps.wait_until(_probe_rate_input, timeout=1.0, interval=0.03)
                    if rate_input:
                        print('输入佣金率：20%')
                        rate_input.input('20')
                        self._deps.wait_until(
                            lambda: _normalize_numeric_text(rate_input.attr('value')) == '20',
                            timeout=0.6,
                            interval=0.03,
                        )
                else:
                    print('联盟达人带货不可用，已跳过')
            else:
                print('未找到联盟达人带货开关，已跳过')
        except Exception:
            print('处理联盟达人带货失败，已跳过')

        after_snapshot = {
            **self._build_probe_snapshot(main_tab, record, sku_list, *self._get_price_stock_context(main_tab)),
            **write_result,
            'stage_duration_ms': round((native_time.time() - stage_timer_start) * 1000, 2),
            'shipping_template_name': shipping_template_name,
        }
        self._write_artifact(
            artifact_writer,
            protocol_runtime,
            'price_stock',
            'dom-probe-after-write',
            after_snapshot,
            'price-stock-dom-probe',
        )
        self._deps.timer_record('价格库存阶段', '总计', 0, native_time.time() - stage_timer_start, True)
        return after_snapshot

    def _execute_protocol_price_stock_write(
        self,
        *,
        main_tab: Any,
        record: Any,
        sku_list: list[dict[str, Any]],
        protocol_runtime: Any,
        artifact_writer: ArtifactWriter | None,
    ) -> dict[str, Any]:
        if str(os.getenv('DYIN_PRICE_STOCK_ENABLE_SAVE_DRAFT_PROBE') or '').strip() != '1':
            raise Exception('协议写入价格库存尚未启用：当前旧协议依赖保存草稿抓包，已禁止进入正式流水线')

        capture_arm_result = arm_price_stock_protocol_capture(main_tab)
        reset_price_stock_protocol_capture(main_tab)
        save_button = main_tab.ele('xpath://span[text()="保存草稿"]/..', timeout=1.5)
        if not save_button:
            raise Exception('协议写入价格库存失败：未找到保存草稿按钮')

        save_button.scroll.to_center()
        save_button.click(by_js=True)

        captured = None

        def _capture_ready() -> bool:
            nonlocal captured
            captured = read_price_stock_protocol_capture(main_tab)
            return bool(captured and captured.get('bodyText') and captured.get('url'))

        if not self._deps.wait_until(_capture_ready, timeout=3.0, interval=0.05):
            raise Exception('协议写入价格库存失败：未捕获到保存草稿请求')

        request_payload = self._build_protocol_request_payload(record=record, sku_list=sku_list, captured_request=captured)
        self._write_artifact(
            artifact_writer,
            protocol_runtime,
            'price_stock',
            'protocol-captured-request',
            {
                'captured_at': datetime.now().isoformat(),
                'capture_arm_result': capture_arm_result,
                'request_url': captured.get('url'),
                'request_method': captured.get('method'),
                'request_headers': captured.get('headers') or {},
                'request_body_preview': str(captured.get('bodyText') or '')[:2000],
            },
            'price-stock-protocol-request',
        )
        self._write_artifact(
            artifact_writer,
            protocol_runtime,
            'price_stock',
            'protocol-patched-request',
            request_payload['artifact_payload'],
            'price-stock-protocol-request',
        )

        replay_response = replay_price_stock_protocol_request(
            main_tab,
            url=str(captured.get('url') or ''),
            method=str(captured.get('method') or 'POST'),
            headers=captured.get('headers') or {},
            body_text=request_payload['body_text'],
        )
        replay_summary = self._normalize_protocol_response(replay_response)
        replay_summary['captured_at'] = datetime.now().isoformat()
        self._write_artifact(
            artifact_writer,
            protocol_runtime,
            'price_stock',
            'protocol-replay-response',
            replay_summary,
            'price-stock-protocol-response',
        )

        if not replay_summary.get('success'):
            raise Exception(f'协议写入价格库存失败：{replay_summary.get("failure_reason") or "服务端未返回成功"}')

        return {
            'write_mode': 'protocol',
            'protocol_capture_channel': captured.get('channel'),
            'protocol_request_url': captured.get('url'),
            'protocol_request_method': captured.get('method'),
            'protocol_write_count': request_payload['matched_count'],
            'protocol_rows': request_payload['matched_rows'],
            'protocol_response_status': replay_summary.get('status'),
        }

    def _build_protocol_request_payload(
        self,
        *,
        record: Any,
        sku_list: list[dict[str, Any]],
        captured_request: dict[str, Any],
    ) -> dict[str, Any]:
        raw_body = str(captured_request.get('bodyText') or '').strip()
        if not raw_body:
            raise Exception('协议写入价格库存失败：保存草稿请求体为空')

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise Exception(f'协议写入价格库存失败：保存草稿请求体不是有效 JSON: {exc}') from exc

        schema = payload.get('schema')
        model = schema.get('model') if isinstance(schema, dict) else None
        sku_detail = model.get('sku_detail') if isinstance(model, dict) else None
        spec_detail = model.get('spec_detail') if isinstance(model, dict) else None
        sku_rows = sku_detail.get('value') if isinstance(sku_detail, dict) else None
        spec_groups = spec_detail.get('value') if isinstance(spec_detail, dict) else None
        if not isinstance(sku_rows, list) or not isinstance(spec_groups, list):
            raise Exception('协议写入价格库存失败：保存草稿请求体缺少 sku_detail/spec_detail')

        normalized_stock_text = _normalize_numeric_text(getattr(record, 'repo', None))
        if not normalized_stock_text:
            raise Exception('协议写入价格库存失败：库存为空')
        try:
            stock_num = int(Decimal(normalized_stock_text))
        except (InvalidOperation, ValueError) as exc:
            raise Exception(f'协议写入价格库存失败：库存不是有效整数 -> {normalized_stock_text}') from exc
        if stock_num < 0:
            raise Exception(f'协议写入价格库存失败：库存不能为负数 -> {stock_num}')

        spec_value_name_map: dict[str, str] = {}
        for group in spec_groups:
            if not isinstance(group, dict):
                continue
            for item in group.get('spec_values') or []:
                if not isinstance(item, dict):
                    continue
                spec_id = _normalize_price_stock_text(item.get('id'))
                spec_name = _normalize_price_stock_text(item.get('name'))
                if spec_id and spec_name:
                    spec_value_name_map[spec_id] = spec_name

        remaining_expected: list[dict[str, Any]] = [
            {
                'name': str(item.get('name', '')).strip(),
                'price': _normalize_numeric_text(item.get('price')),
            }
            for item in sku_list
        ]
        matched_rows: list[dict[str, Any]] = []

        for row in sku_rows:
            if not isinstance(row, dict):
                continue
            row_spec_ids = [
                _normalize_price_stock_text(item)
                for item in (row.get('spec_detail_ids') or [])
                if _normalize_price_stock_text(item)
            ]
            row_label_parts = [spec_value_name_map[item] for item in row_spec_ids if spec_value_name_map.get(item)]
            row_label = ' / '.join(part for part in row_label_parts if part).strip()
            matched_index = None
            matched_expectation = None
            for index, expected in enumerate(remaining_expected):
                if not expected['name']:
                    continue
                matched, _, _ = self._row_matches_sku('', '', expected['name']) if not row_label else self._row_matches_sku(row_label, '', expected['name'])
                if matched:
                    matched_index = index
                    matched_expectation = expected
                    break
            if matched_index is None or matched_expectation is None:
                continue

            price_text = _normalize_numeric_text(matched_expectation.get('price'))
            if not price_text:
                raise Exception(f'协议写入价格库存失败：SKU {matched_expectation["name"]} 缺少价格')
            try:
                price_decimal = Decimal(price_text)
            except (InvalidOperation, ValueError) as exc:
                raise Exception(f'协议写入价格库存失败：SKU {matched_expectation["name"]} 价格无效 -> {price_text}') from exc
            if price_decimal <= Decimal('0'):
                raise Exception(f'协议写入价格库存失败：SKU {matched_expectation["name"]} 价格必须大于 0')

            row['price'] = price_text
            stock_info = row.get('stock_info') if isinstance(row.get('stock_info'), dict) else {}
            stock_info['stock_num'] = stock_num
            row['stock_info'] = stock_info
            matched_rows.append({
                'sku_name': matched_expectation['name'],
                'row_label': row_label,
                'spec_detail_ids': row_spec_ids,
                'price': price_text,
                'stock_num': stock_num,
            })
            remaining_expected.pop(matched_index)

        if remaining_expected:
            unresolved = '、'.join(item['name'] for item in remaining_expected[:6] if item['name'])
            available = '、'.join(self._build_protocol_available_rows(sku_rows, spec_value_name_map)[:10])
            detail = f'未匹配 SKU[{unresolved}]'
            if available:
                detail += f'，当前协议行[{available}]'
            raise Exception(f'协议写入价格库存失败：{detail}')

        payload_text = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        return {
            'body_text': payload_text,
            'matched_count': len(matched_rows),
            'matched_rows': matched_rows,
            'artifact_payload': {
                'captured_at': datetime.now().isoformat(),
                'matched_count': len(matched_rows),
                'matched_rows': matched_rows,
                'payload': payload,
            },
        }

    def _build_protocol_available_rows(self, sku_rows: list[dict[str, Any]], spec_value_name_map: dict[str, str]) -> list[str]:
        labels: list[str] = []
        for row in sku_rows:
            if not isinstance(row, dict):
                continue
            spec_ids = [
                _normalize_price_stock_text(item)
                for item in (row.get('spec_detail_ids') or [])
                if _normalize_price_stock_text(item)
            ]
            parts = [spec_value_name_map[item] for item in spec_ids if spec_value_name_map.get(item)]
            label = ' / '.join(part for part in parts if part).strip()
            if label:
                labels.append(label)
        return labels

    def _normalize_protocol_response(self, response: dict[str, Any]) -> dict[str, Any]:
        status = int(response.get('status') or 0)
        response_text = str(response.get('responseText') or '')
        body_json = None
        try:
            body_json = json.loads(response_text) if response_text else None
        except json.JSONDecodeError:
            body_json = None

        success = 200 <= status < 300
        failure_reason = ''
        if body_json is not None and isinstance(body_json, dict):
            if body_json.get('success') is False:
                success = False
            for key in ('code', 'status_code', 'statusCode', 'errno'):
                if key in body_json:
                    try:
                        if int(body_json.get(key)) != 0:
                            success = False
                            failure_reason = str(body_json.get('msg') or body_json.get('message') or body_json.get(key))
                    except Exception:
                        pass
                    break
            if not failure_reason:
                failure_reason = str(body_json.get('msg') or body_json.get('message') or '')
        elif not success:
            failure_reason = response_text[:300]

        return {
            'success': success,
            'status': status,
            'response_url': response.get('responseUrl') or '',
            'failure_reason': failure_reason.strip(),
            'response_json': body_json,
            'response_text_preview': response_text[:2000],
        }

    def _execute_dom_price_stock_write(
        self,
        *,
        main_tab: Any,
        record: Any,
        sku_list: list[dict[str, Any]],
    ) -> dict[str, Any]:
        processed_row_keys: set[str] = set()
        price_stock_root, holder = self._get_price_stock_context(main_tab)
        scroll_top = 0

        # 诊断快照: 记录表格初始状态
        try:
            visible_rows_snapshot = self._get_visible_rows(price_stock_root) if price_stock_root else []
            row_names_init = [self._extract_row_identity(r)[0] for r in visible_rows_snapshot[:10]]
            print(f'[价格库存诊断] 初始可见行: {len(visible_rows_snapshot)} 行, 名称: {row_names_init}')
        except Exception:
            pass
        if holder:
            self._set_holder_top(holder, scroll_top)
            self._deps.wait_until(
                lambda: abs((self._get_holder_metrics(holder).get('top') or 0) - scroll_top) <= 2,
                timeout=0.3,
                interval=0.02,
            )

        sku_index = 0
        guard = 0
        while sku_index < len(sku_list):
            guard += 1
            if guard > max(len(sku_list) * 8, 32):
                raise Exception('价格库存填写过程中出现异常循环，未能按顺序推进')

            price_stock_root, holder = self._get_price_stock_context(main_tab)
            if holder:
                self._set_holder_top(holder, scroll_top)
                self._deps.wait_until(
                    lambda: abs((self._get_holder_metrics(holder).get('top') or 0) - scroll_top) <= 2,
                    timeout=0.4,
                    interval=0.02,
                )

            visible_rows = self._get_visible_rows(price_stock_root)
            if not visible_rows:
                raise Exception('未找到价格库存表格行')

            # 如果所有可见行都已处理, 先滚动加载新行
            all_processed = all(
                self._get_row_key(r, *self._extract_row_identity(r)) in processed_row_keys
                for r in visible_rows
            )
            if all_processed and sku_index < len(sku_list):
                continue  # 回到外层循环, 触发滚动加载下一批

            for row in visible_rows:
                row_timer_start = native_time.time()
                row_name, row_size = self._extract_row_identity(row)
                row_key = self._get_row_key(row, row_name, row_size)
                if row_key in processed_row_keys:
                    continue
                if sku_index >= len(sku_list):
                    break

                sku = sku_list[sku_index]
                sku_name = str(sku.get('name', '')).strip()
                sku_price = _normalize_numeric_text(sku.get('price'))
                sku_stock = _normalize_numeric_text(getattr(record, 'repo', None))

                locate_timer_start = native_time.time()
                matched, expected_name, expected_size = self._row_matches_sku(row_name, row_size, sku_name)
                self._deps.timer_record('价格库存阶段', f'{sku_index + 1}-匹配当前行', 0, native_time.time() - locate_timer_start, matched)
                if not matched:
                    row_preview = '、'.join(self._summarize_rows(visible_rows))
                    detail = f'当前行[{row_name} / {row_size}] 期望规格[{expected_name}]'
                    if expected_size:
                        detail += f' 期望尺码[{expected_size}]'
                    if row_preview:
                        detail += f' 可见行[{row_preview}]'
                    raise Exception(f'价格库存顺序异常：第{sku_index + 1}个SKU {sku_name}（{detail}）')

                print(f'填写SKU价格库存 -> {sku_index + 1}. {sku_name} | 价格:{sku_price} | 库存:{sku_stock} | 行名:{row_name[:30]}')
                row.scroll.to_center()

                price_input = self._get_row_price_input(row, timeout=1)
                stock_input = self._get_row_stock_input(row, timeout=1)
                if not price_input or not stock_input:
                    raise Exception(f'未找到价格或库存输入框：{sku_name}')

                # 快速检查: 如果已经填了正确的值, 跳过
                existing_price = _normalize_numeric_text(price_input.attr('value'))
                existing_stock = _normalize_numeric_text(stock_input.attr('value'))
                expected_price = _normalize_numeric_text(sku_price)
                expected_stock = _normalize_numeric_text(sku_stock)
                if existing_price == expected_price and existing_stock == expected_stock:
                    print(f'  SKU {sku_index + 1} 价格库存已正确, 跳过')
                    processed_row_keys.add(row_key)
                    self._deps.timer_record('价格库存阶段', f'{sku_index + 1}-跳过已填写', 0, native_time.time() - row_timer_start, True)
                    sku_index += 1
                    continue

                price_input.input(sku_price, clear=True)
                stock_input.input(sku_stock, clear=True)

                def _price_stock_written() -> bool:
                    _, live_row = self._find_live_row(main_tab, row_key, row_name, row_size)
                    if not live_row:
                        return False
                    live_price_input = self._get_row_price_input(live_row, timeout=0.15)
                    live_stock_input = self._get_row_stock_input(live_row, timeout=0.15)
                    if not live_price_input or not live_stock_input:
                        return False
                    current_price = _normalize_numeric_text(live_price_input.attr('value'))
                    current_stock = _normalize_numeric_text(live_stock_input.attr('value'))
                    return current_price == expected_price and current_stock == expected_stock

                write_timer_start = native_time.time()
                if not self._deps.wait_until(_price_stock_written, timeout=0.5, interval=0.04):
                    _, live_row = self._find_live_row(main_tab, row_key, row_name, row_size)
                    live_price_input = self._get_row_price_input(live_row, timeout=0.15) if live_row else None
                    live_stock_input = self._get_row_stock_input(live_row, timeout=0.15) if live_row else None
                    price_value = _normalize_numeric_text(live_price_input.attr('value')) if live_price_input else ''
                    stock_value = _normalize_numeric_text(live_stock_input.attr('value')) if live_stock_input else ''
                    raise Exception(
                        f'价格库存写入校验失败：{sku_name} -> 期望价格[{expected_price}] 实际价格[{price_value}] 期望库存[{expected_stock}] 实际库存[{stock_value}]'
                    )

                processed_row_keys.add(row_key)
                self._deps.timer_record('价格库存阶段', f'{sku_index + 1}-写入校验', 0, native_time.time() - write_timer_start, True)
                self._deps.timer_record('价格库存阶段', f'{sku_index + 1}-总计', 0, native_time.time() - row_timer_start, True)
                sku_index += 1

            if sku_index >= len(sku_list):
                break

            price_stock_root, holder = self._get_price_stock_context(main_tab)
            if not holder:
                remaining = '、'.join(str(item.get('name', '')).strip() for item in sku_list[sku_index:sku_index + 5])
                raise Exception(f'价格库存表格可见行不足，剩余SKU未填写：{remaining}')

            metrics = self._get_holder_metrics(holder)
            viewport_height = metrics.get('height') or 0
            total_height = metrics.get('total') or 0
            current_top = metrics.get('top') or 0
            max_top = max(total_height - viewport_height, 0)
            step = max(int(viewport_height * 0.72), 180) if viewport_height else 180
            next_top = min(current_top + step, max_top)
            if next_top <= current_top:
                remaining = '、'.join(str(item.get('name', '')).strip() for item in sku_list[sku_index:sku_index + 5])
                raise Exception(f'价格库存滚动未推进，剩余SKU未填写：{remaining}')
            self._set_holder_top(holder, next_top)
            scroll_top = next_top
            self._deps.wait_until(
                lambda: (self._get_holder_metrics(holder).get('top') or 0) >= max(next_top - 2, 0),
                timeout=0.4,
                interval=0.02,
            )

        # 诊断: 完成后快照
        _, holder_final = self._get_price_stock_context(main_tab)
        final_visible = self._get_visible_rows(price_stock_root) if price_stock_root else []
        final_names = [self._extract_row_identity(r)[0] for r in final_visible[:10]]
        print(f'[价格库存诊断] 完成: 处理{len(processed_row_keys)}行, 最终可见{len(final_visible)}行')

        return {
            'write_mode': 'dom',
            'processed_row_keys': sorted(processed_row_keys),
            'processed_row_count': len(processed_row_keys),
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

    def _extract_row_identity(self, row: Any) -> tuple[str, str]:
        spec_texts: list[str] = []
        try:
            spec_cells = row.eles('xpath:./td[contains(@class,"attr-column-field_spec_")]', timeout=0.05) or []
        except Exception:
            spec_cells = []

        for cell in spec_cells:
            try:
                text = _normalize_price_stock_text(cell.text)
            except Exception:
                text = ''
            if text:
                spec_texts.append(text)

        name_text = spec_texts[0] if spec_texts else ''
        size_text = spec_texts[1] if len(spec_texts) > 1 else ''
        return _canonicalize_price_stock_row_identity(name_text, size_text)

    def _get_row_price_input(self, row: Any, timeout: float = 0.2) -> Any:
        if not row:
            return None
        try:
            return row.ele('xpath:./td[contains(@class,"attr-column-field_price")]//input', timeout=timeout)
        except Exception:
            return None

    def _get_row_stock_input(self, row: Any, timeout: float = 0.2) -> Any:
        if not row:
            return None
        try:
            return row.ele('xpath:./td[contains(@class,"attr-column-field_stock_info")]//input', timeout=timeout)
        except Exception:
            return None

    def _get_row_key(self, row: Any, row_name: str = '', row_size: str = '') -> str:
        try:
            row_key = _normalize_price_stock_text(row.attr('data-row-key'))
        except Exception:
            row_key = ''
        return row_key or f'{row_name}||{row_size}'

    def _summarize_rows(self, rows: list[Any], limit: int = 5) -> list[str]:
        summary: list[str] = []
        for row in rows[:limit]:
            try:
                name_text, size_text = self._extract_row_identity(row)
                if name_text or size_text:
                    summary.append(f'{name_text} / {size_text}'.strip(' /'))
            except Exception:
                continue
        return summary

    def _build_probe_snapshot(self, main_tab: Any, record: Any, sku_list: list[dict[str, Any]], price_stock_root: Any, holder: Any) -> dict[str, Any]:
        visible_rows = self._get_visible_rows(price_stock_root)
        row_items: list[dict[str, Any]] = []
        for row in visible_rows[:20]:
            try:
                row_name, row_size = self._extract_row_identity(row)
                row_key = self._get_row_key(row, row_name, row_size)
                price_input = self._get_row_price_input(row, timeout=0.05)
                stock_input = self._get_row_stock_input(row, timeout=0.05)
                row_items.append({
                    'row_key': row_key,
                    'row_name': row_name,
                    'row_size': row_size,
                    'price_value': _normalize_numeric_text(price_input.attr('value')) if price_input else '',
                    'stock_value': _normalize_numeric_text(stock_input.attr('value')) if stock_input else '',
                })
            except Exception:
                continue

        return {
            'captured_at': datetime.now().isoformat(),
            'page_url': self._deps.get_current_tab_url(main_tab),
            'record_id': getattr(record, 'id', None),
            'record_name': getattr(record, 'name', ''),
            'record_repo': getattr(record, 'repo', None),
            'holder_metrics': self._get_holder_metrics(holder),
            'visible_row_count': len(visible_rows),
            'visible_rows': row_items,
            'expected_skus': [
                {
                    'index': index + 1,
                    'name': str(sku.get('name', '')).strip(),
                    'price': _normalize_numeric_text(sku.get('price')),
                    'stock': _normalize_numeric_text(getattr(record, 'repo', None)),
                }
                for index, sku in enumerate(sku_list)
            ],
        }

    def _get_price_stock_root(self, main_tab: Any) -> Any:
        try:
            return main_tab.ele('xpath://div[@attr-field-id="价格与库存"]', timeout=0.5)
        except Exception:
            return None

    def _get_price_stock_context(self, main_tab: Any) -> tuple[Any, Any]:
        price_stock_root = self._get_price_stock_root(main_tab)
        if not price_stock_root:
            raise Exception('未找到价格与库存区域')
        return price_stock_root, self._get_virtual_holder(price_stock_root)

    def _get_virtual_holder(self, price_stock_root: Any) -> Any:
        for selector in (
            'xpath:.//div[contains(@class,"ecom-g-table-tbody-virtual-holder")]',
            'xpath:.//div[contains(@class,"ecom-g-table-tbody-virtual") and contains(@class,"ecom-g-table-tbody")]',
        ):
            try:
                holder = price_stock_root.ele(selector, timeout=0.1)
            except Exception:
                holder = None
            if holder:
                return holder
        return None

    def _get_holder_metrics(self, holder: Any) -> dict[str, int]:
        if not holder:
            return {'top': 0, 'height': 0, 'total': 0}
        try:
            metrics = holder.run_js(
                'return {top: this.scrollTop || 0, height: this.clientHeight || 0, total: this.scrollHeight || 0};'
            ) or {}
        except Exception:
            metrics = {}
        return {
            'top': int(metrics.get('top') or 0),
            'height': int(metrics.get('height') or 0),
            'total': int(metrics.get('total') or 0),
        }

    def _set_holder_top(self, holder: Any, top: int) -> None:
        if not holder:
            return
        safe_top = max(0, int(top or 0))
        try:
            holder.run_js('this.scrollTop = arguments[0];', safe_top)
        except Exception:
            holder.run_js(f'this.scrollTop = {safe_top};')

    def _get_visible_rows(self, price_stock_root: Any) -> list[Any]:
        rows = price_stock_root.eles(
            'xpath:.//tr[contains(@class,"ecom-g-table-row") and not(contains(@class,"ecom-g-table-row-level-"))]',
            timeout=0.2
        ) or []
        visible_rows: list[Any] = []
        for row in rows:
            try:
                if not row.states.is_displayed:
                    continue
                if not self._get_row_price_input(row, timeout=0.05):
                    continue
                if not self._get_row_stock_input(row, timeout=0.05):
                    continue
                visible_rows.append(row)
            except Exception:
                continue
        return visible_rows

    def _find_live_row(self, main_tab: Any, row_key: str, row_name: str = '', row_size: str = '') -> tuple[Any, Any]:
        price_stock_root = self._get_price_stock_root(main_tab)
        if not price_stock_root:
            return None, None

        if row_key and '||' not in row_key:
            try:
                literal = _xpath_text_literal(row_key)
                matched = price_stock_root.ele(f'xpath:.//tr[@data-row-key={literal}]', timeout=0.15)
                if matched and matched.states.is_displayed:
                    return price_stock_root, matched
            except Exception:
                pass

        for row in self._get_visible_rows(price_stock_root):
            try:
                current_name, current_size = self._extract_row_identity(row)
                current_key = self._get_row_key(row, current_name, current_size)
            except Exception:
                continue
            if current_key == row_key:
                return price_stock_root, row
            if current_name == row_name and current_size == row_size:
                return price_stock_root, row

        return price_stock_root, None

    def _row_matches_sku(self, row_name: str, row_size: str, sku_name: str) -> tuple[bool, str, str]:
        expected_name, expected_size = _split_price_stock_sku_name(sku_name)
        expected_full_name = _normalize_price_stock_text(sku_name)
        expected_name_variants: set[str] = set()
        expected_name_variants.update(_build_price_stock_name_variants(expected_full_name))
        expected_name_variants.update(_build_price_stock_name_variants(expected_name))
        row_base_name, row_inline_size = _split_price_stock_sku_name(row_name)
        normalized_row_size = _normalize_price_stock_size_text(row_size)
        row_name_variants: set[str] = set()
        row_name_variants.update(_build_price_stock_name_variants(row_name))
        row_name_variants.update(_build_price_stock_name_variants(row_base_name))
        size_matches = (
            not expected_size
            or normalized_row_size == expected_size
            or row_inline_size == expected_size
        )
        name_matches = bool(expected_name_variants & row_name_variants)
        return name_matches and size_matches, expected_name, expected_size

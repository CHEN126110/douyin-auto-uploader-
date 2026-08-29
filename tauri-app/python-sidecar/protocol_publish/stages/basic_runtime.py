from __future__ import annotations

import os
import time as native_time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


ArtifactWriter = Callable[[Any, str, str, Any, str], Any]


@dataclass(slots=True)
class BasicPublishStageDependencies:
    dismiss_interfering_overlays: Callable[..., Any]
    wait_until: Callable[..., bool]
    get_current_tab_url: Callable[..., str]
    get_title_input: Callable[..., Any]
    upload_file: Callable[..., Any]
    smart_select_category: Callable[..., bool]
    select_text: Callable[..., Any]
    set_material_composition: Callable[..., bool]
    get_current_category_text: Callable[..., str]
    infer_sock_height_value: Callable[..., str]
    get_sex: Callable[..., str]
    upload_wash_label_or_tag_image: Callable[..., bool]
    fill_fabric_material_if_wash_label_unrecognized: Callable[..., Any]


class TitleStageExecutor:
    def __init__(self, dependencies: BasicPublishStageDependencies) -> None:
        self._deps = dependencies

    def execute(self, *, main_tab: Any, record: Any, protocol_runtime: Any = None, artifact_writer: ArtifactWriter | None = None) -> dict[str, Any]:
        self._deps.dismiss_interfering_overlays(main_tab, context='fill_title')
        before = self._build_probe(main_tab, record)
        self._write_artifact(artifact_writer, protocol_runtime, 'title', 'before-write', before, 'title-probe')

        input_element = self._deps.get_title_input(main_tab, timeout=0.4)
        if not input_element:
            raise Exception('未找到商品标题输入框')
        input_element.click()
        input_element.input(record.title)
        if not self._deps.wait_until(
            lambda: str(input_element.attr('value') or '').strip() == str(record.title or '').strip(),
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
        self._deps.dismiss_interfering_overlays(main_tab, context='fill_title')

        after = self._build_probe(main_tab, record)
        after['status'] = 'ok'
        self._write_artifact(artifact_writer, protocol_runtime, 'title', 'after-write', after, 'title-probe')
        return after

    def _build_probe(self, main_tab: Any, record: Any) -> dict[str, Any]:
        return {
            'captured_at': datetime.now().isoformat(),
            'page_url': self._deps.get_current_tab_url(main_tab),
            'record_id': getattr(record, 'id', None),
            'record_name': getattr(record, 'name', ''),
            'title': getattr(record, 'title', ''),
        }

    def _write_artifact(self, artifact_writer: ArtifactWriter | None, protocol_runtime: Any, stage: str, name: str, payload: Any, artifact_type: str) -> None:
        if callable(artifact_writer):
            artifact_writer(protocol_runtime, stage, name, payload, artifact_type=artifact_type)


class MainImagesStageExecutor:
    def __init__(self, dependencies: BasicPublishStageDependencies) -> None:
        self._deps = dependencies

    def execute(self, *, main_tab: Any, record: Any, main_pic_list: list[str], protocol_runtime: Any = None, artifact_writer: ArtifactWriter | None = None) -> dict[str, Any]:
        before = self._build_probe(main_tab, record, main_pic_list)
        self._write_artifact(artifact_writer, protocol_runtime, 'main_images', 'before-upload', before, 'main-images-probe')
        self._deps.upload_file(main_tab, main_pic_list, '主图', error_size='长宽比需为1:1' if record.type == 2 else None)
        after = self._build_probe(main_tab, record, main_pic_list)
        after['status'] = 'ok'
        self._write_artifact(artifact_writer, protocol_runtime, 'main_images', 'after-upload', after, 'main-images-probe')
        return after

    def _build_probe(self, main_tab: Any, record: Any, main_pic_list: list[str]) -> dict[str, Any]:
        return {
            'captured_at': datetime.now().isoformat(),
            'page_url': self._deps.get_current_tab_url(main_tab),
            'record_id': getattr(record, 'id', None),
            'record_name': getattr(record, 'name', ''),
            'main_pic_count': len(main_pic_list),
            'record_type': getattr(record, 'type', None),
        }

    def _write_artifact(self, artifact_writer: ArtifactWriter | None, protocol_runtime: Any, stage: str, name: str, payload: Any, artifact_type: str) -> None:
        if callable(artifact_writer):
            artifact_writer(protocol_runtime, stage, name, payload, artifact_type=artifact_type)


class CategorySelectionStageExecutor:
    def __init__(self, dependencies: BasicPublishStageDependencies) -> None:
        self._deps = dependencies

    def execute(self, *, main_tab: Any, record: Any, diaopai_pic: str, protocol_runtime: Any = None, artifact_writer: ArtifactWriter | None = None) -> dict[str, Any]:
        self._deps.dismiss_interfering_overlays(main_tab, context='select_category')
        before = self._build_probe(main_tab, record)
        self._write_artifact(artifact_writer, protocol_runtime, 'category_selection', 'before-select', before, 'category-selection-probe')

        print(f'开始智能类目选择: {record.clazz}')
        if not self._deps.smart_select_category(main_tab, record.clazz):
            print('类目选择失败，已尝试推荐与手动选择。请检查页面结构或账号资质。')
            raise Exception('类目选择失败')
        print('智能类目选择成功')
        self._deps.dismiss_interfering_overlays(main_tab, context='select_category')

        gen_btn = main_tab.ele(
            'xpath://div[@data-better-log-outer-key="short_product_name"]//span[contains(@class,"ecom-g-input-suffix")]//img',
            timeout=3,
        )
        if gen_btn:
            gen_btn.scroll.to_center()
            gen_btn.click(by_js=True)
            print('已点击生成短标题按钮')
        else:
            print('未找到生成短标题按钮，检查 XPath 或页面结构是否变化')

        self._deps.dismiss_interfering_overlays(main_tab, context='after_short_title')

        wash_tag_field_exists = False
        try:
            wash_tag_field_exists = bool(main_tab.ele('xpath://div[@attr-field-id="水洗标/吊牌图"]', timeout=0.3))
        except Exception:
            wash_tag_field_exists = False

        tag_upload_attempted = False
        if diaopai_pic and str(record.clazz) != '0' and not wash_tag_field_exists:
            print('处理其他类目吊牌上传...')
            self._deps.upload_file(main_tab, [diaopai_pic], '吊牌')
            tag_upload_attempted = True
            self._deps.wait_until(
                lambda: bool(main_tab.ele('吊牌识别成功', timeout=0.05)) or bool(main_tab.ele('吊牌识别失败', timeout=0.05)),
                timeout=3.0,
                interval=0.05,
            )

        after = self._build_probe(main_tab, record)
        after.update({
            'status': 'ok',
            'wash_tag_field_exists': wash_tag_field_exists,
            'tag_upload_attempted': tag_upload_attempted,
        })
        self._write_artifact(artifact_writer, protocol_runtime, 'category_selection', 'after-select', after, 'category-selection-probe')
        return after

    def _build_probe(self, main_tab: Any, record: Any) -> dict[str, Any]:
        return {
            'captured_at': datetime.now().isoformat(),
            'page_url': self._deps.get_current_tab_url(main_tab),
            'record_id': getattr(record, 'id', None),
            'record_name': getattr(record, 'name', ''),
            'clazz': getattr(record, 'clazz', None),
        }

    def _write_artifact(self, artifact_writer: ArtifactWriter | None, protocol_runtime: Any, stage: str, name: str, payload: Any, artifact_type: str) -> None:
        if callable(artifact_writer):
            artifact_writer(protocol_runtime, stage, name, payload, artifact_type=artifact_type)


class CategoryAttributesStageExecutor:
    def __init__(self, dependencies: BasicPublishStageDependencies) -> None:
        self._deps = dependencies

    def execute(
        self,
        *,
        main_tab: Any,
        record: Any,
        configured_materials: list[tuple[str, str]],
        diaopai_pic: str,
        wash_label_tag_image_path: str,
        protocol_runtime: Any = None,
        artifact_writer: ArtifactWriter | None = None,
    ) -> dict[str, Any]:
        stage_timer_start = native_time.time()
        self._deps.dismiss_interfering_overlays(main_tab, context='fill_category_attributes')
        current_category_text = self._deps.get_current_category_text(main_tab)
        current_sock_height = self._deps.infer_sock_height_value(current_category_text, record.clazz)
        is_ship_socks = '船袜' in current_category_text
        has_wash_label_asset = bool(
            (diaopai_pic and os.path.isfile(diaopai_pic))
            or (wash_label_tag_image_path and os.path.isfile(wash_label_tag_image_path))
        )

        before = {
            'captured_at': datetime.now().isoformat(),
            'page_url': self._deps.get_current_tab_url(main_tab),
            'record_id': getattr(record, 'id', None),
            'record_name': getattr(record, 'name', ''),
            'current_category_text': current_category_text,
            'current_sock_height': current_sock_height,
            'is_ship_socks': is_ship_socks,
            'has_wash_label_asset': has_wash_label_asset,
        }
        self._write_artifact(artifact_writer, protocol_runtime, 'category_attributes', 'before-fill', before, 'category-attributes-probe')

        print(f'当前页面类目: {current_category_text or "未识别"}')
        if current_sock_height:
            print(f'当前页面筒高目标值: {current_sock_height}')

        if is_ship_socks:
            print('处理船袜类目属性...')
            self._run_step(
                main_tab=main_tab,
                step_name='滚动到类目属性区块',
                action=lambda: main_tab.ele('xpath://div[@attr-field-id="主图3:4"]').scroll.to_see(),
                protocol_runtime=protocol_runtime,
                artifact_writer=artifact_writer,
            )
            self._run_step(
                main_tab=main_tab,
                step_name='选择品牌',
                action=lambda: self._deps.select_text(main_tab, '品牌', '无品牌'),
                protocol_runtime=protocol_runtime,
                artifact_writer=artifact_writer,
            )
            self._run_step(
                main_tab=main_tab,
                step_name='填写船袜材质',
                action=lambda: self._fill_ship_sock_material(main_tab),
                protocol_runtime=protocol_runtime,
                artifact_writer=artifact_writer,
            )

        elif has_wash_label_asset:
            print('处理其他类目属性（有可用吊牌/水洗标图）...')
            self._run_step(
                main_tab=main_tab,
                step_name='滚动到类目属性区块',
                action=lambda: main_tab.ele('xpath://div[@attr-field-id="主图3:4"]').scroll.to_see(),
                protocol_runtime=protocol_runtime,
                artifact_writer=artifact_writer,
            )
            self._run_step(
                main_tab=main_tab,
                step_name='清理已有面料材质标签',
                action=lambda: self._clear_material_tags(main_tab),
                protocol_runtime=protocol_runtime,
                artifact_writer=artifact_writer,
            )
            self._run_step(
                main_tab=main_tab,
                step_name='选择品牌',
                action=lambda: self._deps.select_text(main_tab, '品牌', '无品牌'),
                protocol_runtime=protocol_runtime,
                artifact_writer=artifact_writer,
            )
            self._run_step(
                main_tab=main_tab,
                step_name='选择适用人群',
                action=lambda: self._deps.select_text(main_tab, '适用人群', '成人'),
                protocol_runtime=protocol_runtime,
                artifact_writer=artifact_writer,
            )
            self._run_step(
                main_tab=main_tab,
                step_name='选择适用性别',
                action=lambda: self._deps.select_text(main_tab, '适用性别', self._deps.get_sex(record.title)),
                protocol_runtime=protocol_runtime,
                artifact_writer=artifact_writer,
            )
            if current_sock_height:
                self._run_step(
                    main_tab=main_tab,
                    step_name='选择筒高',
                    action=lambda: self._deps.select_text(main_tab, '筒高', current_sock_height),
                    protocol_runtime=protocol_runtime,
                    artifact_writer=artifact_writer,
                )

        else:
            print('处理其他类目属性（无吊牌/水洗标图，改走面料材质配置）...')
            self._run_step(
                main_tab=main_tab,
                step_name='滚动到类目属性区块',
                action=lambda: main_tab.ele('xpath://div[@attr-field-id="主图3:4"]').scroll.to_see(),
                protocol_runtime=protocol_runtime,
                artifact_writer=artifact_writer,
            )
            self._run_step(
                main_tab=main_tab,
                step_name='填写面料材质',
                action=lambda: self._ensure_material_composition(main_tab, configured_materials),
                protocol_runtime=protocol_runtime,
                artifact_writer=artifact_writer,
            )
            self._run_step(
                main_tab=main_tab,
                step_name='选择品牌',
                action=lambda: self._deps.select_text(main_tab, '品牌', '无品牌'),
                protocol_runtime=protocol_runtime,
                artifact_writer=artifact_writer,
            )
            self._run_step(
                main_tab=main_tab,
                step_name='选择适用人群',
                action=lambda: self._deps.select_text(main_tab, '适用人群', '成人'),
                protocol_runtime=protocol_runtime,
                artifact_writer=artifact_writer,
            )
            self._run_step(
                main_tab=main_tab,
                step_name='选择适用性别',
                action=lambda: self._deps.select_text(main_tab, '适用性别', self._deps.get_sex(record.title)),
                protocol_runtime=protocol_runtime,
                artifact_writer=artifact_writer,
            )
            if current_sock_height:
                self._run_step(
                    main_tab=main_tab,
                    step_name='选择筒高',
                    action=lambda: self._deps.select_text(main_tab, '筒高', current_sock_height),
                    protocol_runtime=protocol_runtime,
                    artifact_writer=artifact_writer,
                )

        self._deps.dismiss_interfering_overlays(main_tab, context='before_wash_label_upload')
        uploaded_wash_label = self._run_step(
            main_tab=main_tab,
            step_name='上传水洗标/吊牌图',
            action=lambda: self._deps.upload_wash_label_or_tag_image(main_tab, diaopai_pic, wash_label_tag_image_path),
            protocol_runtime=protocol_runtime,
            artifact_writer=artifact_writer,
            include_result=True,
        )
        if uploaded_wash_label:
            self._run_step(
                main_tab=main_tab,
                step_name='按水洗标识别结果补面料材质',
                action=lambda: self._deps.fill_fabric_material_if_wash_label_unrecognized(main_tab, configured_materials),
                protocol_runtime=protocol_runtime,
                artifact_writer=artifact_writer,
            )

        after = {
            'captured_at': datetime.now().isoformat(),
            'page_url': self._deps.get_current_tab_url(main_tab),
            'record_id': getattr(record, 'id', None),
            'record_name': getattr(record, 'name', ''),
            'current_category_text': self._deps.get_current_category_text(main_tab),
            'current_sock_height': current_sock_height,
            'uploaded_wash_label': uploaded_wash_label,
            'duration_ms': round((native_time.time() - stage_timer_start) * 1000, 2),
            'status': 'ok',
        }
        self._write_artifact(artifact_writer, protocol_runtime, 'category_attributes', 'after-fill', after, 'category-attributes-probe')
        return after

    def _run_step(
        self,
        *,
        main_tab: Any,
        step_name: str,
        action: Callable[[], Any],
        protocol_runtime: Any = None,
        artifact_writer: ArtifactWriter | None = None,
        include_result: bool = False,
    ) -> Any:
        started_at = native_time.time()
        self._deps.dismiss_interfering_overlays(main_tab, context=f'fill_category_attributes:{step_name}:before')
        before_payload = {
            'captured_at': datetime.now().isoformat(),
            'page_url': self._deps.get_current_tab_url(main_tab),
            'step': step_name,
            'phase': 'before',
        }
        self._write_artifact(artifact_writer, protocol_runtime, 'category_attributes', f'step-{step_name}-before', before_payload, 'category-attributes-step')
        print(f'[类目属性] 开始: {step_name}')

        result = action()

        self._deps.dismiss_interfering_overlays(main_tab, context=f'fill_category_attributes:{step_name}:after')
        duration_ms = round((native_time.time() - started_at) * 1000, 2)
        after_payload = {
            'captured_at': datetime.now().isoformat(),
            'page_url': self._deps.get_current_tab_url(main_tab),
            'step': step_name,
            'phase': 'after',
            'duration_ms': duration_ms,
            'status': 'ok',
        }
        if include_result:
            after_payload['result'] = result
        self._write_artifact(artifact_writer, protocol_runtime, 'category_attributes', f'step-{step_name}-after', after_payload, 'category-attributes-step')
        print(f'[类目属性] 完成: {step_name} ({duration_ms}ms)')
        return result

    def _fill_ship_sock_material(self, main_tab: Any) -> None:
        try:
            material_input = main_tab.ele('xpath://div[@attr-field-id="材质"]//input[@placeholder="请输入"]')
            material_input.scroll.to_center()
            self._deps.dismiss_interfering_overlays(main_tab, context='fill_category_attributes:ship_material:input')
            material_input.click()
            material_input.input('棉')
            self._deps.wait_until(
                lambda: str(material_input.attr('value') or '').strip() == '棉',
                timeout=0.6,
                interval=0.03,
            )
            print('船袜类目：已填写材质为棉')
        except Exception as exc:
            raise Exception(f'船袜类目材质填写失败: {str(exc)}') from exc

    def _ensure_material_composition(self, main_tab: Any, configured_materials: list[tuple[str, str]]) -> None:
        material_ok = self._deps.set_material_composition(main_tab, configured_materials)
        if not material_ok:
            raise Exception('面料材质填写失败')

    def _clear_material_tags(self, main_tab: Any) -> None:
        idle_rounds = 0
        while True:
            self._deps.dismiss_interfering_overlays(main_tab, context='fill_category_attributes:clear_material_tags')
            buttons = main_tab.eles('xpath://div[@attr-field-id="面料材质"]//span[contains(@class,"styles_del__")]', timeout=0.2) or []
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
            try:
                visible_buttons[-1].click(by_js=True)
            except Exception as exc:
                idle_rounds += 1
                if idle_rounds >= 3:
                    raise Exception(f'清理面料材质标签失败: {str(exc)}') from exc
                continue
            if self._deps.wait_until(
                lambda: self._count_material_delete_buttons(main_tab) < before_count,
                timeout=0.8,
                interval=0.05,
            ):
                idle_rounds = 0
                continue
            idle_rounds += 1
            if idle_rounds >= 3:
                raise Exception('清理面料材质标签失败: 删除动作未生效')

    def _count_material_delete_buttons(self, main_tab: Any) -> int:
        buttons = main_tab.eles('xpath://div[@attr-field-id="面料材质"]//span[contains(@class,"styles_del__")]', timeout=0.1) or []
        count = 0
        for btn in buttons:
            try:
                if btn and btn.states.is_displayed:
                    count += 1
            except Exception:
                continue
        return count

    def _write_artifact(self, artifact_writer: ArtifactWriter | None, protocol_runtime: Any, stage: str, name: str, payload: Any, artifact_type: str) -> None:
        if callable(artifact_writer):
            artifact_writer(protocol_runtime, stage, name, payload, artifact_type=artifact_type)

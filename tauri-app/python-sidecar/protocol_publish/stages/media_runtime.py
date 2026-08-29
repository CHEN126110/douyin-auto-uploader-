from __future__ import annotations

import time as native_time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


ArtifactWriter = Callable[[Any, str, str, Any, str], Any]


@dataclass(slots=True)
class MediaStageDependencies:
    dismiss_interfering_overlays: Callable[..., Any]
    wait_until: Callable[..., bool]
    timer_record: Callable[..., Any]
    get_current_tab_url: Callable[..., str]
    upload_file: Callable[..., Any]
    click_field_action: Callable[..., Any]
    handle_white_bg_post_upload_prompts: Callable[..., Any]
    find_ai_material_tool_panel: Callable[..., Any]
    is_upload_busy: Callable[..., bool]
    drive_ai_main_image_actions: Callable[..., bool]
    wait_for_detail_upload_area_ready: Callable[..., bool]


class MediaStageExecutor:
    def __init__(self, dependencies: MediaStageDependencies) -> None:
        self._deps = dependencies

    def execute(
        self,
        *,
        main_tab: Any,
        sub_pic_list: list[str],
        my_video: str,
        white_pic: str,
        detail_pic_list: list[str],
        protocol_runtime: Any = None,
        artifact_writer: ArtifactWriter | None = None,
    ) -> dict[str, Any]:
        media_timer_start = native_time.time()
        self._deps.dismiss_interfering_overlays(main_tab, context='upload_media_assets')
        before = self._build_probe(main_tab, sub_pic_list, my_video, white_pic, detail_pic_list)
        self._write_artifact(artifact_writer, protocol_runtime, 'media', 'before-upload', before, 'media-probe')

        step_timer_start = native_time.time()
        if len(sub_pic_list) > 0:
            self._deps.upload_file(
                main_tab,
                sub_pic_list,
                '主图',
                error_size='长宽比需为3:4',
                target_field_id='主图3:4',
                wait_for_finish=False,
            )
        else:
            print("跳过3:4主图上传，尝试自动点击'从1:1主图智能裁剪'按钮")
            try:
                if self._deps.click_field_action(main_tab, '主图3:4', '从1:1主图智能裁剪') or self._deps.click_field_action(main_tab, '主图3:4', '从1:1主图一键填入'):
                    print('成功触发3:4主图智能裁剪')
                else:
                    print('未找到3:4主图智能裁剪按钮')
            except Exception as exc:
                print(f"自动点击3:4主图智能裁剪按钮失败: {str(exc)}")
                print('请手动点击3:4主图智能裁剪按钮')
        self._deps.timer_record('媒体上传阶段', '3比4主图', 0, native_time.time() - step_timer_start, True)

        main_tab.ele('xpath://div[@attr-field-id="主图视频"]').scroll.to_see()
        self._deps.dismiss_interfering_overlays(main_tab, context='before_video_upload')

        step_timer_start = native_time.time()
        if my_video:
            print('开始上传主图视频...')
            self._deps.upload_file(
                main_tab,
                [my_video],
                '主图视频',
                target_field_id='主图视频',
                wait_for_finish=False,
            )
        else:
            print('没有本地主图视频，尝试开启AI自动生成')
            ai_clicked = (
                self._deps.click_field_action(main_tab, '主图视频', '开启AI自动生成')
                or self._deps.click_field_action(main_tab, '主图视频', 'AI自动生成')
                or self._deps.click_field_action(main_tab, '主图视频', '一键生成')
            )
            if ai_clicked:
                self._deps.wait_until(
                    lambda: self._deps.is_upload_busy(main_tab) or bool(self._deps.find_ai_material_tool_panel(main_tab, timeout=0.05)),
                    timeout=0.5,
                    interval=0.03,
                )
            else:
                print('未找到AI生成按钮')
        self._deps.timer_record('媒体上传阶段', '主图视频', 0, native_time.time() - step_timer_start, True)

        step_timer_start = native_time.time()
        self._deps.upload_file(
            main_tab,
            [white_pic],
            '白底图',
            target_field_id='白底图',
            wait_for_finish=False,
        )
        try:
            self._deps.handle_white_bg_post_upload_prompts(main_tab, timeout=3.0)
        except Exception as exc:
            print(f'处理白底图上传后AI素材工具失败: {exc}')
        self._deps.wait_until(
            lambda: (not self._deps.find_ai_material_tool_panel(main_tab, timeout=0.05)) and (not self._deps.is_upload_busy(main_tab)),
            timeout=0.6,
            interval=0.03,
        )
        self._deps.timer_record('媒体上传阶段', '白底图与AI收尾', 0, native_time.time() - step_timer_start, True)

        self._deps.dismiss_interfering_overlays(main_tab, context='before_detail_upload')
        step_timer_start = native_time.time()
        try:
            self._deps.drive_ai_main_image_actions(main_tab)
        except Exception:
            pass
        try:
            detail_block = main_tab.ele('xpath://div[@attr-field-id="商品详情"]', timeout=2)
            if detail_block:
                detail_block.scroll.to_see()
                self._deps.wait_for_detail_upload_area_ready(main_tab, timeout=0.6, interval=0.03)
        except Exception:
            pass
        self._deps.upload_file(main_tab, detail_pic_list, '图片', extra=True, target_field_id='商品详情')
        self._deps.timer_record('媒体上传阶段', '详情图', 0, native_time.time() - step_timer_start, True)
        self._deps.timer_record('媒体上传阶段', '总计', 0, native_time.time() - media_timer_start, True)

        after = self._build_probe(main_tab, sub_pic_list, my_video, white_pic, detail_pic_list)
        after.update({
            'status': 'ok',
            'duration_ms': round((native_time.time() - media_timer_start) * 1000, 2),
        })
        self._write_artifact(artifact_writer, protocol_runtime, 'media', 'after-upload', after, 'media-probe')
        return after

    def _build_probe(
        self,
        main_tab: Any,
        sub_pic_list: list[str],
        my_video: str,
        white_pic: str,
        detail_pic_list: list[str],
    ) -> dict[str, Any]:
        return {
            'captured_at': datetime.now().isoformat(),
            'page_url': self._deps.get_current_tab_url(main_tab),
            'sub_pic_count': len(sub_pic_list),
            'has_video': bool(my_video),
            'has_white_pic': bool(white_pic),
            'detail_pic_count': len(detail_pic_list),
            'ai_material_panel_visible': bool(self._deps.find_ai_material_tool_panel(main_tab, timeout=0.05)),
            'upload_busy': bool(self._deps.is_upload_busy(main_tab)),
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

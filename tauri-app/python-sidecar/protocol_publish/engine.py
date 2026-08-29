from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .artifacts import ProtocolArtifactStore
from .models import (
    ProtocolCaptureArtifact,
    ProtocolCaptureEntry,
    ProtocolExecutionPlan,
    ProtocolStageDefinition,
)
from .stages import (
    BasicPublishStageDependencies,
    CategoryAttributesStageExecutor,
    CategorySelectionStageExecutor,
    MediaStageDependencies,
    MediaStageExecutor,
    MainImagesStageExecutor,
    OpenPublishPageStageDependencies,
    OpenPublishPageStageExecutor,
    PRICE_STOCK_STAGE_KEY,
    PriceStockDiscoveryProfile,
    PriceStockStageDependencies,
    PriceStockStageExecutor,
    PublishSessionStageDependencies,
    PublishSessionStageExecutor,
    SkuEntriesStageExecutor,
    SkuStageDependencies,
    SkuStructureStageExecutor,
    SubmitPublishStageDependencies,
    SubmitPublishStageExecutor,
    TitleStageExecutor,
    summarize_price_stock_capture,
)


def _now_iso() -> str:
    return datetime.now().isoformat()


@dataclass(slots=True)
class ProtocolRunContext:
    run_id: str
    record_id: int | None
    record_name: str
    started_at: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)


class ProtocolPublishEngine:
    """协议化上传引擎骨架。

    当前职责：
    - 固化阶段定义
    - 为协议化执行提供独立 run context
    - 将抓包与执行产物落盘

    后续职责：
    - 接入真实的价格库存 / SKU / 属性 / 媒体 / 发布阶段执行器
    """

    VERSION = "0.1.0"

    def __init__(self) -> None:
        self._plan = ProtocolExecutionPlan(
            engine="protocol-publish",
            version=self.VERSION,
            goal="完整稳定的抖音商品协议化上传流水线",
            stages=[
                ProtocolStageDefinition(
                    key="session",
                    title="会话与上下文",
                    description="获取已登录浏览器会话、Cookie、必要 headers 与页面上下文。",
                    protocol_ready=False,
                ),
                ProtocolStageDefinition(
                    key="open_publish_page",
                    title="进入发布页",
                    description="确保当前浏览器处于商品发布第一页，避免停留在第二页或其它页面。",
                    protocol_ready=False,
                    depends_on=["session"],
                ),
                ProtocolStageDefinition(
                    key="title",
                    title="商品标题",
                    description="填写商品标题并校验输入值。",
                    protocol_ready=False,
                    depends_on=["session", "open_publish_page"],
                ),
                ProtocolStageDefinition(
                    key="main_images",
                    title="主图",
                    description="上传商品主图并处理必要的裁剪确认。",
                    protocol_ready=False,
                    depends_on=["session", "open_publish_page", "title"],
                ),
                ProtocolStageDefinition(
                    key="category_selection",
                    title="类目选择",
                    description="执行智能类目选择、短标题生成与吊牌识别入口准备。",
                    protocol_ready=False,
                    depends_on=["session", "open_publish_page", "title", "main_images"],
                ),
                ProtocolStageDefinition(
                    key="category_attributes",
                    title="类目属性",
                    description="直接提交品牌、筒高、材质与其它可枚举属性。",
                    protocol_ready=False,
                    depends_on=["session", "open_publish_page", "category_selection", "main_images"],
                ),
                ProtocolStageDefinition(
                    key="media",
                    title="媒体上传",
                    description="接管主图、视频、白底图、详情图上传与素材绑定。",
                    protocol_ready=False,
                    depends_on=["session", "open_publish_page", "main_images", "category_selection", "category_attributes"],
                ),
                ProtocolStageDefinition(
                    key="sku_entries",
                    title="SKU条目",
                    description="填写颜色分类规格值、备注和规格图上传入口。",
                    protocol_ready=False,
                    depends_on=["session", "open_publish_page", "category_selection", "main_images", "media"],
                ),
                ProtocolStageDefinition(
                    key="sku_structure",
                    title="SKU结构",
                    description="直接提交规格值、规格图和 SKU 组合结构。",
                    protocol_ready=False,
                    depends_on=["session", "open_publish_page", "sku_entries", "category_selection", "main_images", "media"],
                ),
                ProtocolStageDefinition(
                    key="price_stock",
                    title="价格库存",
                    description="直接按 SKU 标识写入价格与库存，替代虚拟表格逐行 DOM 输入。",
                    protocol_ready=False,
                    depends_on=["session", "open_publish_page", "category_attributes", "media", "sku_entries", "sku_structure"],
                ),
                ProtocolStageDefinition(
                    key="submit",
                    title="提交发布",
                    description="提交商品草稿并返回服务端校验结果。",
                    protocol_ready=False,
                    depends_on=["session", "open_publish_page", "sku_entries", "price_stock", "sku_structure", "category_attributes", "media"],
                ),
            ],
        )

    @property
    def plan(self) -> ProtocolExecutionPlan:
        return self._plan

    def build_run_context(
        self,
        record_id: int | None = None,
        record_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[ProtocolRunContext, ProtocolArtifactStore]:
        run_id = f"protocol_{uuid.uuid4().hex[:12]}"
        context = ProtocolRunContext(
            run_id=run_id,
            record_id=record_id,
            record_name=str(record_name or ""),
            metadata=dict(metadata or {}),
        )
        return context, ProtocolArtifactStore(run_id=run_id)

    def export_plan(self) -> dict[str, Any]:
        return self._plan.to_dict()

    def export_discovery_profiles(self) -> dict[str, Any]:
        return {
          PRICE_STOCK_STAGE_KEY: PriceStockDiscoveryProfile().to_dict(),
        }

    def summarize_price_stock_discovery(self, payload: dict[str, Any]) -> dict[str, Any]:
        return summarize_price_stock_capture(payload)

    def execute_title_stage(
        self,
        *,
        main_tab: Any,
        record: Any,
        dependencies: BasicPublishStageDependencies,
        protocol_runtime: Any = None,
        artifact_writer: Any = None,
    ) -> dict[str, Any]:
        executor = TitleStageExecutor(dependencies)
        return executor.execute(
            main_tab=main_tab,
            record=record,
            protocol_runtime=protocol_runtime,
            artifact_writer=artifact_writer,
        )

    def execute_main_images_stage(
        self,
        *,
        main_tab: Any,
        record: Any,
        main_pic_list: list[str],
        dependencies: BasicPublishStageDependencies,
        protocol_runtime: Any = None,
        artifact_writer: Any = None,
    ) -> dict[str, Any]:
        executor = MainImagesStageExecutor(dependencies)
        return executor.execute(
            main_tab=main_tab,
            record=record,
            main_pic_list=main_pic_list,
            protocol_runtime=protocol_runtime,
            artifact_writer=artifact_writer,
        )

    def execute_category_selection_stage(
        self,
        *,
        main_tab: Any,
        record: Any,
        diaopai_pic: str,
        dependencies: BasicPublishStageDependencies,
        protocol_runtime: Any = None,
        artifact_writer: Any = None,
    ) -> dict[str, Any]:
        executor = CategorySelectionStageExecutor(dependencies)
        return executor.execute(
            main_tab=main_tab,
            record=record,
            diaopai_pic=diaopai_pic,
            protocol_runtime=protocol_runtime,
            artifact_writer=artifact_writer,
        )

    def execute_category_attributes_stage(
        self,
        *,
        main_tab: Any,
        record: Any,
        configured_materials: list[tuple[str, str]],
        diaopai_pic: str,
        wash_label_tag_image_path: str,
        dependencies: BasicPublishStageDependencies,
        protocol_runtime: Any = None,
        artifact_writer: Any = None,
    ) -> dict[str, Any]:
        executor = CategoryAttributesStageExecutor(dependencies)
        return executor.execute(
            main_tab=main_tab,
            record=record,
            configured_materials=configured_materials,
            diaopai_pic=diaopai_pic,
            wash_label_tag_image_path=wash_label_tag_image_path,
            protocol_runtime=protocol_runtime,
            artifact_writer=artifact_writer,
        )

    def execute_session_stage(
        self,
        *,
        report_progress: Any,
        publish_create_url: str,
        dependencies: PublishSessionStageDependencies,
        protocol_runtime: Any = None,
        artifact_writer: Any = None,
    ) -> dict[str, Any]:
        executor = PublishSessionStageExecutor(dependencies)
        return executor.execute(
            report_progress=report_progress,
            publish_create_url=publish_create_url,
            protocol_runtime=protocol_runtime,
            artifact_writer=artifact_writer,
        )

    def execute_open_publish_page_stage(
        self,
        *,
        main_tab: Any,
        report_progress: Any,
        publish_create_url: str,
        dependencies: OpenPublishPageStageDependencies,
        protocol_runtime: Any = None,
        artifact_writer: Any = None,
    ) -> dict[str, Any]:
        executor = OpenPublishPageStageExecutor(dependencies)
        return executor.execute(
            main_tab=main_tab,
            report_progress=report_progress,
            publish_create_url=publish_create_url,
            protocol_runtime=protocol_runtime,
            artifact_writer=artifact_writer,
        )

    def execute_price_stock_stage(
        self,
        *,
        main_tab: Any,
        record: Any,
        sku_list: list[dict[str, Any]],
        shipping_template_name: str,
        dependencies: PriceStockStageDependencies,
        protocol_runtime: Any = None,
        artifact_writer: Any = None,
    ) -> dict[str, Any]:
        executor = PriceStockStageExecutor(dependencies)
        return executor.execute(
            main_tab=main_tab,
            record=record,
            sku_list=sku_list,
            shipping_template_name=shipping_template_name,
            protocol_runtime=protocol_runtime,
            artifact_writer=artifact_writer,
        )

    def execute_sku_entries_stage(
        self,
        *,
        main_tab: Any,
        sku_list: list[dict[str, Any]],
        remark: str,
        dependencies: SkuStageDependencies,
        protocol_runtime: Any = None,
        artifact_writer: Any = None,
    ) -> dict[str, Any]:
        executor = SkuEntriesStageExecutor(dependencies)
        return executor.execute(
            main_tab=main_tab,
            sku_list=sku_list,
            remark=remark,
            protocol_runtime=protocol_runtime,
            artifact_writer=artifact_writer,
        )

    def execute_sku_structure_stage(
        self,
        *,
        main_tab: Any,
        dependencies: SkuStageDependencies,
        protocol_runtime: Any = None,
        artifact_writer: Any = None,
    ) -> dict[str, Any]:
        executor = SkuStructureStageExecutor(dependencies)
        return executor.execute(
            main_tab=main_tab,
            protocol_runtime=protocol_runtime,
            artifact_writer=artifact_writer,
        )

    def execute_media_stage(
        self,
        *,
        main_tab: Any,
        sub_pic_list: list[str],
        my_video: str,
        white_pic: str,
        detail_pic_list: list[str],
        dependencies: MediaStageDependencies,
        protocol_runtime: Any = None,
        artifact_writer: Any = None,
    ) -> dict[str, Any]:
        executor = MediaStageExecutor(dependencies)
        return executor.execute(
            main_tab=main_tab,
            sub_pic_list=sub_pic_list,
            my_video=my_video,
            white_pic=white_pic,
            detail_pic_list=detail_pic_list,
            protocol_runtime=protocol_runtime,
            artifact_writer=artifact_writer,
        )

    def execute_submit_stage(
        self,
        *,
        main_tab: Any,
        record: Any,
        dependencies: SubmitPublishStageDependencies,
        protocol_runtime: Any = None,
        artifact_writer: Any = None,
    ) -> dict[str, Any]:
        executor = SubmitPublishStageExecutor(dependencies)
        return executor.execute(
            main_tab=main_tab,
            record=record,
            protocol_runtime=protocol_runtime,
            artifact_writer=artifact_writer,
        )

    def record_capture(
        self,
        store: ProtocolArtifactStore,
        *,
        stage: str,
        source: str,
        method: str,
        url: str,
        request_headers: dict[str, Any] | None = None,
        request_body: Any = None,
        response_status: int | None = None,
        response_headers: dict[str, Any] | None = None,
        response_body: Any = None,
        response_body_preview: str = "",
        elapsed_ms: float | None = None,
        request_id: str = "",
        transport: str = "network",
        intercepted: bool = False,
        blocked: bool = False,
        blocked_error_reason: str = "",
        success: bool = True,
        error: str = "",
        meta: dict[str, Any] | None = None,
    ) -> ProtocolCaptureArtifact:
        entry = ProtocolCaptureEntry(
            stage=stage,
            source=source,
            method=method,
            url=url,
            request_id=str(request_id or ""),
            transport=str(transport or "network"),
            request_headers=dict(request_headers or {}),
            request_body=request_body,
            response_status=response_status,
            response_headers=dict(response_headers or {}),
            response_body=response_body,
            response_body_preview=response_body_preview,
            elapsed_ms=elapsed_ms,
            intercepted=intercepted,
            blocked=blocked,
            blocked_error_reason=str(blocked_error_reason or ""),
            success=success,
            error=str(error or ""),
            meta=dict(meta or {}),
        )
        return store.append_capture(entry)

    def import_cdp_capture_result(
        self,
        store: ProtocolArtifactStore,
        *,
        stage: str,
        capture_result: dict[str, Any],
        source: str = "cdp_fxg_protocol_capture",
    ) -> list[ProtocolCaptureArtifact]:
        return store.append_cdp_capture_result(
            stage=stage,
            capture_result=capture_result,
            source=source,
        )

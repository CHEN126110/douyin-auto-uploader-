from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .artifacts import CaptureArtifactStore
from .models import CaptureExecutionPlan, CaptureStageDefinition, SourcePlatformProfile


def _now_iso() -> str:
    return datetime.now().isoformat()


@dataclass
class CaptureRunContext:
    run_id: str
    source_url: str
    source_platform: str
    product_id: str = ""
    started_at: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)


class ProtocolCaptureEngine:
    """货源采集协议化引擎骨架。

    当前职责：
    - 固化三平台统一阶段规划
    - 输出平台画像
    - 为后续 1688 / 淘宝 / 天猫协议化采集提供独立运行上下文
    """

    VERSION = "0.1.0"

    def __init__(self) -> None:
        self._plan = CaptureExecutionPlan(
            engine="protocol-capture",
            version=self.VERSION,
            goal="完整稳定的 1688 / 淘宝 / 天猫协议化采集流水线",
            stages=[
                CaptureStageDefinition(
                    key="route_url",
                    title="链接路由",
                    description="统一规范化链接、识别平台、提取商品ID。",
                    protocol_ready=False,
                    platforms=["1688", "taobao", "tmall"],
                ),
                CaptureStageDefinition(
                    key="session",
                    title="会话确认",
                    description="确认浏览器、登录态、当前URL和必要上下文。",
                    protocol_ready=False,
                    platforms=["1688", "taobao", "tmall"],
                    depends_on=["route_url"],
                ),
                CaptureStageDefinition(
                    key="product_payload",
                    title="商品载荷",
                    description="提取标题、基础价格、主图、详情图、状态对象。",
                    protocol_ready=False,
                    platforms=["1688", "taobao", "tmall"],
                    depends_on=["session"],
                ),
                CaptureStageDefinition(
                    key="sku_payload",
                    title="SKU载荷",
                    description="提取 SKU 名称、规格图、价格、规格组合。",
                    protocol_ready=False,
                    platforms=["1688", "taobao", "tmall"],
                    depends_on=["product_payload"],
                ),
                CaptureStageDefinition(
                    key="asset_manifest",
                    title="素材清单",
                    description="生成主图、SKU图、详情图下载清单，不在此阶段耦合导入逻辑。",
                    protocol_ready=False,
                    platforms=["1688", "taobao", "tmall"],
                    depends_on=["product_payload", "sku_payload"],
                ),
                CaptureStageDefinition(
                    key="import_manifest",
                    title="导入清单",
                    description="生成标准导入清单，供现有导入器或未来协议导入器消费。",
                    protocol_ready=False,
                    platforms=["1688", "taobao", "tmall"],
                    depends_on=["asset_manifest"],
                ),
            ],
        )

        self._platforms = [
            SourcePlatformProfile(
                key="1688",
                title="1688",
                host_patterns=["1688.com", "detail.1688.com", "offer.1688.com"],
                state_sources=[
                    "window.context.result.data",
                    "tradeModel",
                    "Root.fields.dataJson",
                ],
                asset_sources=[
                    "gallery.mainImage",
                    "offerImgList",
                    "detailUrl",
                ],
                notes=[
                    "当前代码已经具备半协议化基础，优先级最高。",
                ],
            ),
            SourcePlatformProfile(
                key="taobao",
                title="淘宝",
                host_patterns=["taobao.com", "item.taobao.com"],
                state_sources=[
                    "页面初始化对象",
                    "页面脚本中的商品状态数据",
                ],
                asset_sources=[
                    "主图缩略图 DOM",
                    "详情图 DOM / 页面状态",
                ],
                notes=[
                    "当前仍以 DOM 为主，需要先剥离状态对象来源。",
                ],
            ),
            SourcePlatformProfile(
                key="tmall",
                title="天猫",
                host_patterns=["tmall.com", "detail.tmall.com"],
                state_sources=[
                    "页面初始化对象",
                    "页面脚本中的商品状态数据",
                ],
                asset_sources=[
                    "主图缩略图 DOM",
                    "详情图 DOM / 页面状态",
                ],
                notes=[
                    "与淘宝共享大部分采集链，但页面结构独立，需要独立证据。",
                ],
            ),
        ]

    @property
    def plan(self) -> CaptureExecutionPlan:
        return self._plan

    def build_run_context(
        self,
        *,
        source_url: str,
        source_platform: str,
        product_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[CaptureRunContext, CaptureArtifactStore]:
        run_id = f"capture_{uuid.uuid4().hex[:12]}"
        context = CaptureRunContext(
            run_id=run_id,
            source_url=str(source_url or "").strip(),
            source_platform=str(source_platform or "").strip(),
            product_id=str(product_id or "").strip(),
            metadata=dict(metadata or {}),
        )
        return context, CaptureArtifactStore(run_id=run_id)

    def export_plan(self) -> dict[str, Any]:
        return self._plan.to_dict()

    def export_platform_profiles(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self._platforms]

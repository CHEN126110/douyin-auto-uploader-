# -*- coding: utf-8 -*-
"""taobao-publish：淘宝商品「上传发布」流程的研究与开发子项目。

**当前状态（2026-10-05）**：**走 DOM 路线，11 个阶段全部已实现**，
其中 10 个已在真实页面上跑通完整链路（含上传主图、建 SKU 表、选运费模板），
只剩 ``submit`` 未实机执行——它按设计需要两把锁同时打开。

2026-10-05 新增**图片空间协议上传**（`upload_api` / `upload_client` /
`upload_page` / `picturecenter` / `cloud_index`）：把图直接 POST 到
``stream-upload.taobao.com/api/upload.api``，当场拿到 ``object.url`` 与
``pictureId``，不再依赖发布页的素材中心弹层。端点来自官方前端 bundle 原文
（`verified`），**运行时行为尚未实测**——真实字段名与目录接口的 version 仍
`unknown`，见 `docs/31` §3 与 `docs/33` §5。

> 上传只在**淘宝上架**流程里发生：必须过 `upload_image` 写授权门，
> 采集链路不引用任何上传模块（用户要求：日常采集不上传，避免图片空间堆积）。

契约面：**30 条选择器全部 verified**；字段映射的缺口只关 **mtop 协议路线**，
DOM 路线不依赖它们（``dom_write_ready`` 为真）。

公共 API::

    from taobao_publish import run, describe_readiness, WriteAuthorization

    readiness = describe_readiness()
    print(readiness.publish_route_ready)   # 现在为 True（DOM 路线可用）
    print(readiness.publishable)           # 「现在能不能一键发布」看这个

    result = run(local_product, {"title": "...", "skus": [...]})  # 默认 dry-run

红线速查：

* 写操作默认全关，需 ``TAOBAO_UPLOAD_ALLOW_WRITE``；提交还需
  ``TAOBAO_UPLOAD_ALLOW_SUBMIT=1``。
* 任何产物落盘前必须过 :mod:`taobao_publish.sanitize`。
* 证据不足时进 blockers，不用默认值糊过去。
* 协议上传**不重试**：平台限流（``BAXIA_BLOCKED``）的正确处置是停手交人工。
"""

from __future__ import annotations

from .authorization import WriteAuthorization, parse_grant
from .cdp_ws import CdpBrowser, describe_cookies
from .picturecenter import (
    PictureFile,
    PictureFolder,
    build_directory_add,
    build_directory_query,
    build_file_query,
    parse_directory_tree,
    parse_files,
)
from .upload_api import (
    DEFAULT_FOLDER_ID,
    UPLOAD_HOST,
    UPLOAD_PATH,
    UploadCandidate,
    UploadEndpoint,
    UploadOutcome,
    UploadReceipt,
    classify_upload_response,
    contract_summary as upload_contract_summary,
    validate_upload_name,
)
from .upload_client import (
    BatchUploadReport,
    CookieHttpTransport,
    PictureSpaceUploader,
    UploadCredentials,
    make_upload_product,
)
from .upload_page import (
    PageSession,
    PageUploadError,
    PageUploadReport,
    PictureSpacePageUploader,
    open_session,
)
from .constants import (
    EVIDENCE_CANDIDATE,
    EVIDENCE_REJECTED,
    EVIDENCE_UNKNOWN,
    EVIDENCE_VERIFIED,
    ENV_ALLOW_SUBMIT,
    ENV_ALLOW_WRITE,
    PUBLISH_WORKBENCH_URL,
    STAGE_LABELS,
    STAGE_ORDER,
    TAOBAO_CDP_LIST_URL,
    TAOBAO_CDP_PORT,
    WRITE_OPERATIONS,
)
from .contracts import (
    Contracts,
    load_contracts,
    validate_contracts,
    write_route_status,
)
from .errors import (
    Blocker,
    BlockerError,
    PreflightBlockedError,
    SubmitNotAuthorizedError,
    TaobaoPublishError,
    WriteNotAuthorizedError,
    describe_error,
)
from .mapping import (
    build_platform_payload,
    build_publish_item,
    collect_unmapped_fields,
    match_freight_template,
)
from .models import (
    CategoryRef,
    EvidenceRef,
    ImageSet,
    LocalProduct,
    LocalSku,
    PipelineResult,
    PropEntry,
    PublishItem,
    SkuEntry,
    StepRecord,
)
from .pipeline import Readiness, describe_readiness, run, run_from_record
from .preflight import (
    PageSnapshot,
    PreflightResult,
    run_preflight,
    run_static_preflight,
)

__all__ = [
    # 授权
    "WriteAuthorization",
    "parse_grant",
    "ENV_ALLOW_WRITE",
    "ENV_ALLOW_SUBMIT",
    "WRITE_OPERATIONS",
    # 常量
    "EVIDENCE_VERIFIED",
    "EVIDENCE_CANDIDATE",
    "EVIDENCE_UNKNOWN",
    "EVIDENCE_REJECTED",
    "PUBLISH_WORKBENCH_URL",
    "TAOBAO_CDP_PORT",
    "TAOBAO_CDP_LIST_URL",
    "STAGE_ORDER",
    "STAGE_LABELS",
    # 契约
    "Contracts",
    "load_contracts",
    "validate_contracts",
    "write_route_status",
    # 错误
    "Blocker",
    "BlockerError",
    "TaobaoPublishError",
    "WriteNotAuthorizedError",
    "SubmitNotAuthorizedError",
    "PreflightBlockedError",
    "describe_error",
    # 模型
    "LocalProduct",
    "LocalSku",
    "PublishItem",
    "SkuEntry",
    "PropEntry",
    "CategoryRef",
    "ImageSet",
    "EvidenceRef",
    "StepRecord",
    "PipelineResult",
    # 映射
    "build_publish_item",
    "build_platform_payload",
    "collect_unmapped_fields",
    "match_freight_template",
    # 预检
    "PageSnapshot",
    "PreflightResult",
    "run_preflight",
    "run_static_preflight",
    # 流水线
    "run",
    "run_from_record",
    "Readiness",
    "describe_readiness",
    # 图片空间协议上传（详见 docs/31、docs/33）
    "UPLOAD_HOST",
    "UPLOAD_PATH",
    "DEFAULT_FOLDER_ID",
    "UploadCandidate",
    "UploadEndpoint",
    "UploadOutcome",
    "UploadReceipt",
    "classify_upload_response",
    "validate_upload_name",
    "upload_contract_summary",
    "UploadCredentials",
    "CookieHttpTransport",
    "PictureSpaceUploader",
    "BatchUploadReport",
    "make_upload_product",
    "PageSession",
    "PageUploadError",
    "PageUploadReport",
    "PictureSpacePageUploader",
    "open_session",
    "CdpBrowser",
    "describe_cookies",
    "PictureFile",
    "PictureFolder",
    "build_directory_query",
    "build_directory_add",
    "build_file_query",
    "parse_directory_tree",
    "parse_files",
]

__version__ = "0.1.0"

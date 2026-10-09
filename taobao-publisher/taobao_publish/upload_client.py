# -*- coding: utf-8 -*-
"""图片空间协议上传的**传输层**与**客户端**。

设计要点（与仓库既有风格对齐）：

* **传输层可替换**：:class:`UploadTransport` 是一个最小协议，
  ``send(url, body, headers) -> (http_status, text)``。真实环境用
  :class:`CookieHttpTransport`（带 cookie 的 HTTP）或
  :class:`PageFetchTransport`（在已登录页面里 ``fetch``，凭证不出浏览器）；
  离线验证用测试里的假传输层或本地 mock 服务端。
* **协议层不做重试**：平台限流（``BAXIA_BLOCKED``）的正确处置是**停手交人工**，
  重试只会把风控窗口拖长。所以这里没有 retry 循环，只有「逐张发送 → 分类 → 
  遇到 stop 条件立即中断并保留已成功的回执」。
* **凭据不进产物**：cookie 与 ``_tb_token_`` 只在内存里流转，
  :meth:`UploadCredentials.describe` 只回长度与是否存在的布尔值。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .authorization import WriteAuthorization
from .constants import WRITE_UPLOAD_IMAGE
from .errors import TaobaoPublishError
from .upload_api import (
    FIELD_FILE,
    FIELD_NAME,
    FIELD_TOKEN,
    FIELD_WATER,
    FIELD_WATER_OFF_VALUE,
    MAX_FILES_PER_REQUEST,
    UploadCandidate,
    UploadEndpoint,
    UploadOutcome,
    UploadReceipt,
    build_request_body,
    check_batch,
    classify_upload_response,
    new_boundary,
    validate_image_url,
    validate_upload_name,
)

#: 上传请求的默认超时（秒）。单张 3MB 上限，30 秒足够；
#: 超时不当成「失败可重试」，而是如实报告（可能是风控在挂）。
DEFAULT_TIMEOUT: float = 30.0


# ---------------------------------------------------------------------------
# 凭据
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class UploadCredentials:
    """一次上传会话的凭据。**只在内存里流转。**

    :param cookie: 浏览器 ``Cookie`` 头的原文（含登录态）。
    :param tb_token: cookie ``_tb_token_`` 的值，同时作为 multipart 字段发送。
    :param referer: 上传请求的 Referer。图片空间是在发布页里被打开的，
        带上它比凭空发一个请求更像正常流量（但**是否被校验未取证**）。
    """

    cookie: str
    tb_token: str
    referer: str = "https://item.upload.taobao.com/"

    def __post_init__(self) -> None:
        if not isinstance(self.cookie, str) or not self.cookie.strip():
            raise ValueError("缺少登录 cookie：协议上传需要图片空间登录态")
        if not isinstance(self.tb_token, str) or not self.tb_token.strip():
            raise ValueError(
                "缺少 _tb_token_：图片空间上传要求它同时出现在 cookie 与表单字段里"
            )

    def __repr__(self) -> str:  # pragma: no cover - 防误打印
        return f"UploadCredentials(cookie_len={len(self.cookie)}, tb_token_len={len(self.tb_token)})"

    __str__ = __repr__

    def describe(self) -> Dict[str, Any]:
        """可安全落盘/上报的描述。**不含任何凭据内容。**"""

        return {
            "cookie_length": len(self.cookie),
            "tb_token_length": len(self.tb_token),
            "has_referer": bool(self.referer),
        }


# ---------------------------------------------------------------------------
# 传输层
# ---------------------------------------------------------------------------
class UploadTransport(Protocol):
    """最小传输协议。**必须**返回 ``(http_status, text)``。"""

    def send(self, url: str, body: bytes, headers: Mapping[str, str]) -> Tuple[int, str]:
        ...


class UploadTransportError(RuntimeError):
    """传输层自身失败（连不上、超时）。与「平台拒绝」是两件事。"""


@dataclass
class CookieHttpTransport:
    """用带 cookie 的 HTTP 直接发送。凭证只在本对象内存里。

    这条路适合「已经有 cookie 串」的环境（例如桌面端已经登录的调试浏览器，
    由调用方通过 CDP ``Network.getCookies`` 取一次，只在本进程内存里用）。
    """

    credentials: UploadCredentials
    timeout: float = DEFAULT_TIMEOUT
    opener: Optional[Callable[..., Any]] = None

    def send(self, url: str, body: bytes, headers: Mapping[str, str]) -> Tuple[int, str]:
        request_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": self.credentials.referer,
            "Origin": "https://item.upload.taobao.com",
            "Cookie": self.credentials.cookie,
        }
        request_headers.update({str(key): str(value) for key, value in headers.items()})
        request = Request(url, data=body, headers=request_headers, method="POST")
        open_fn = self.opener if self.opener is not None else urlopen
        try:
            with open_fn(request, timeout=self.timeout) as response:
                return int(response.status), response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            # HTTP 错误也要读 body：淘系风控页就是 200/4xx + HTML body。
            raw = exc.read() if hasattr(exc, "read") else b""
            return int(getattr(exc, "code", 0)), raw.decode("utf-8", errors="replace")
        except (URLError, OSError, TimeoutError) as exc:
            raise UploadTransportError(f"上传请求发送失败：{exc}") from exc


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BatchUploadReport:
    """整批上传的结果。**已成功的回执必须保留**，哪怕中途被限流停下。"""

    receipts: Tuple[UploadReceipt, ...] = ()
    failed: Tuple[Dict[str, Any], ...] = ()
    stopped_reason: str = ""
    attempted: int = 0
    authorization: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failed and not self.stopped_reason

    @property
    def should_stop(self) -> bool:
        return bool(self.stopped_reason)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "attempted": self.attempted,
            "receipt_count": len(self.receipts),
            "receipts": [item.to_dict() for item in self.receipts],
            "failed": [dict(item) for item in self.failed],
            "stopped_reason": self.stopped_reason,
            "authorization": dict(self.authorization),
        }


class PictureSpaceUploader:
    """把本地图片按协议送进图片空间。

    .. warning::
        构造后**不会**自动做任何事。每次调 :meth:`upload_one` / :meth:`upload_batch`
        都要过一次写授权门（``upload_image``）。
    """

    def __init__(
        self,
        transport: UploadTransport,
        credentials: UploadCredentials,
        *,
        endpoint_host: str | None = None,
        allow_insecure_host: bool = False,
    ) -> None:
        self._transport = transport
        self._credentials = credentials
        self._endpoint_host = endpoint_host
        self._allow_insecure_host = allow_insecure_host

    # -- 单张 ---------------------------------------------------------------
    def upload_one(
        self,
        candidate: UploadCandidate,
        *,
        folder_id: str,
        authorization: WriteAuthorization,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> UploadOutcome:
        """上传一张。**未授权直接抛错，不会发出请求。**"""

        authorization.require(WRITE_UPLOAD_IMAGE)
        endpoint = self._endpoint(folder_id)
        url = endpoint.build_url()
        boundary = new_boundary()
        body, content_type = build_request_body(
            candidate, token=self._credentials.tb_token, boundary=boundary
        )
        headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
        try:
            status, text = self._transport.send(url, body, headers)
        except UploadTransportError as exc:
            return UploadOutcome(
                ok=False,
                error_code="PLATFORM_ERROR",
                message=str(exc),
            )
        return classify_upload_response(
            http_status=status, text=text, name=candidate.name, folder_id=folder_id
        )

    # -- 整批 ---------------------------------------------------------------
    def upload_batch(
        self,
        candidates: Sequence[UploadCandidate],
        *,
        folder_id: str,
        authorization: WriteAuthorization,
        progress: Optional[Callable[[str], None]] = None,
    ) -> BatchUploadReport:
        """逐张上传整批。

        三条与 DOM 路线一致的行为约定：

        1. **本地护栏先行**：整批在发出第一个请求之前全部校验（体积/格式/重名）。
           一半成功一半失败的回执最难收拾。
        2. **限流即停**：任何一张命中风控，立刻停止本批剩余文件，
           **不重试**，并把已成功的回执原样带回去。
        3. **失败不掩盖**：每张失败都带平台原文。
        """

        authorization.require(WRITE_UPLOAD_IMAGE)
        check_batch(candidates)
        receipts: List[UploadReceipt] = []
        failed: List[Dict[str, Any]] = []
        stopped_reason = ""
        attempted = 0
        for index, candidate in enumerate(candidates, 1):
            if progress:
                progress(f"协议上传 {index}/{len(candidates)}：{candidate.name}")
            attempted += 1
            outcome = self.upload_one(
                candidate, folder_id=folder_id, authorization=authorization
            )
            if outcome.ok and outcome.receipt is not None:
                receipts.append(outcome.receipt)
                continue
            failed.append({"name": candidate.name, **outcome.describe()})
            if outcome.stopped:
                stopped_reason = outcome.message
                break
        return BatchUploadReport(
            receipts=tuple(receipts),
            failed=tuple(failed),
            stopped_reason=stopped_reason,
            attempted=attempted,
            authorization=authorization.to_dict(),
        )

    # -- 内部 ---------------------------------------------------------------
    def _endpoint(self, folder_id: str) -> UploadEndpoint:
        if self._endpoint_host:
            return UploadEndpoint(
                host=self._endpoint_host,
                folder_id=folder_id,
                allow_insecure_host=self._allow_insecure_host,
            )
        return UploadEndpoint(folder_id=folder_id)


#: 与 ``media_manifest.UploadedImageReceipt`` 对齐的字段名，便于把协议回执接进
#: 现有交接层（`prepare_media_batch` 要的是「相对路径 + 云端文件名 + 目录 + URL」）。
def receipt_to_manifest_row(
    receipt: UploadReceipt,
    *,
    relative_path: str,
    folder: Sequence[str],
    sha256: str,
) -> Dict[str, Any]:
    """把协议回执转成既有的媒体交接行。**不做任何字段猜测**。"""

    validate_image_url(receipt.url)
    validate_upload_name(receipt.name)
    return {
        "relative_path": relative_path,
        "name": receipt.name,
        "folder": list(folder),
        "url": receipt.url,
        "sha256": sha256,
        "uploaded_now": True,
        "picture_id": receipt.picture_id,
    }


def candidates_from_manifest(
    manifest: Any,
    *,
    names: Optional[Mapping[str, str]] = None,
) -> List[UploadCandidate]:
    """从 :class:`taobao_publish.media_manifest.ProductMediaManifest` 生成上传候选。

    :param names: ``相对路径 → 上传文件名`` 的可选改名表。**不给就沿用原文件名**，
        不做任何自动改名（自动改名会让回执与本地文件对不上）。
    """

    images = list(getattr(manifest, "images", ()) or ())
    if not images:
        raise ValueError("素材清单里没有图片")
    candidates: List[UploadCandidate] = []
    for image in images:
        relative = str(getattr(image, "relative_path", "") or "")
        if not relative:
            raise ValueError("素材清单条目缺少相对路径")
        name = names.get(relative) if names else None
        name = name or relative.rsplit("/", 1)[-1]
        candidates.append(
            UploadCandidate(
                path=str(manifest.source(relative)),
                name=name,
                size=int(getattr(image, "size", 0) or 0),
                sha256=str(getattr(image, "sha256", "") or ""),
            )
        )
    if len(candidates) > MAX_FILES_PER_REQUEST:
        raise ValueError(
            f"素材清单有 {len(candidates)} 张，超过平台单次上限 {MAX_FILES_PER_REQUEST} 张；"
            "调用方需要分批，本模块不自动切批"
        )
    return candidates


# ---------------------------------------------------------------------------
# 与流水线对接的适配器
# ---------------------------------------------------------------------------
def make_upload_product(
    uploader_factory: Callable[[str], PictureSpaceUploader],
    *,
    folder_resolver: Callable[[str, Tuple[str, ...]], str],
    authorization: WriteAuthorization,
    progress: Optional[Callable[[str], None]] = None,
) -> Callable[..., Any]:
    """产出一个符合 ``media_manifest.prepare_media_batch`` 约定的 ``upload_product``。

    :param uploader_factory: ``账户 → uploader``；账户变了要换一套凭据。
    :param folder_resolver: ``(账户, 从商品根开始的完整目录路径) → folderId``。
        必须逐级定位或创建实际目录并返回 ID；不同路径不能共用同一个 ID。
        此适配器不猜测目录接口，也不把待上传路径冒充实际远端目录回执。
    :param authorization: 写授权快照；未授权时在发出第一个请求之前就抛错。
    """

    from .media_manifest import (PreparedProductMedia, UploadedImageReceipt,
        ProductMediaPreparationError, build_media_manifest, validate_media_manifest)

    def upload_product(manifest: Any, directory: str, account_profile: str) -> Any:
        authorization.require(WRITE_UPLOAD_IMAGE)
        validate_media_manifest(manifest)
        snapshot = build_media_manifest(manifest.record_id, directory)
        if (snapshot.product_dir == manifest.product_dir or snapshot.digest != manifest.digest
                or snapshot.images != manifest.images or snapshot.directories != manifest.directories):
            raise ValueError('上传必须使用与本批清单一致的独立文件夹快照')
        groups = {}
        for image in snapshot.images:
            parts = PurePosixPath(image.relative_path).parts
            folder = (manifest.folder_name, *parts[:-1])
            candidate = UploadCandidate(str(snapshot.source(image.relative_path)), parts[-1], image.size, image.sha256)
            candidate.validate()
            validate_upload_name(candidate.name)
            groups.setdefault(folder, []).append((image, candidate))
        # 全部本地文件先验证，再允许解析器创建云端目录。
        folders = [(manifest.folder_name,)] + [
            (manifest.folder_name, *PurePosixPath(name).parts) for name in manifest.directories]
        directory_ids = {}
        for folder in folders:
            folder_id = folder_resolver(account_profile, folder)
            if not isinstance(folder_id, str) or not folder_id.strip():
                raise ValueError('云端目录缺少实际 ID：' + '/'.join(folder))
            if folder_id in directory_ids.values():
                raise ValueError('不同子目录被解析为同一云端目录：' + '/'.join(folder))
            directory_ids[folder] = folder_id
        uploader = uploader_factory(account_profile)
        receipts: List[UploadedImageReceipt] = []
        try:
            for folder, entries in groups.items():
                folder_id = directory_ids[folder]
                for offset in range(0, len(entries), MAX_FILES_PER_REQUEST):
                    batch = entries[offset:offset + MAX_FILES_PER_REQUEST]
                    report = uploader.upload_batch([candidate for _, candidate in batch],
                        folder_id=folder_id, authorization=authorization, progress=progress)
                    expected = {candidate.name: image for image, candidate in batch}
                    seen = set()
                    for receipt in report.receipts:
                        if receipt.name not in expected or receipt.name in seen or receipt.folder_id != folder_id:
                            raise ValueError('上传回执的文件名、唯一性或目录 ID 与本次请求不一致')
                        validate_image_url(receipt.url)
                        seen.add(receipt.name)
                        image = expected[receipt.name]
                        receipts.append(UploadedImageReceipt(image.relative_path, receipt.name,
                            folder, receipt.url, image.sha256, uploaded_now=True, picture_id=receipt.picture_id))
                    if report.failed or report.stopped_reason:
                        detail = report.stopped_reason or '; '.join(
                            f"{item.get('name')}：{item.get('message')}" for item in report.failed[:3])
                        raise TaobaoPublishError('IMAGE_UPLOAD_FAILED', detail)
                    if seen != expected.keys():
                        raise ValueError('上传端成功结果缺少本次目录的完整图片回执')
        except (OSError, ValueError, TaobaoPublishError, UploadTransportError) as exc:
            raise ProductMediaPreparationError(exc, manifest, account_profile, receipts) from exc
        return PreparedProductMedia(
            manifest=manifest,
            account_profile=account_profile,
            receipts=tuple(receipts),
        )

    return upload_product

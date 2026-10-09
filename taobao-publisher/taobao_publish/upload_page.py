# -*- coding: utf-8 -*-
"""把协议上传放进**已登录页面**里发出去（cookie 不出浏览器）。

## 为什么要有这一层

协议上传有两种发送方式：

1. **Python 侧 HTTP**（``upload_client.CookieHttpTransport``）：调用方自己提供
   cookie 串。适合已经拿到登录态的进程，但 cookie 必然要经过调用方内存。
2. **页面内 fetch**（本模块）：让**已登录的浏览器**自己发请求。cookie（含
   httpOnly）由浏览器自动附带，``_tb_token_`` 从页面读，cookie 值**从不进入
   Python 进程**，也不会出现在日志、产物或异常里。

第二种更符合本子项目的红线（不落敏感数据），也是实机取证时最像正常流量的方式：
请求带着真实的 ``Origin`` / ``Referer`` / ``User-Agent``。

## 分工

* 请求体由页面里的 ``FormData`` 组装（浏览器自己生成分隔串，与我们手写的
  multipart 编码器等价，但不需要把 cookie 搬来搬去）；
* **响应分类仍在 Python 侧**（:func:`taobao_publish.upload_api.classify_upload_response`），
  页面里只负责「发出去、把状态码和文本拿回来」，不在页面里判断成功失败。
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .authorization import WriteAuthorization
from .constants import WRITE_UPLOAD_IMAGE
from .cdp_ws import CdpBrowser, CdpClientError
from .upload_api import (
    FIELD_FILE,
    FIELD_NAME,
    FIELD_TOKEN,
    FIELD_WATER,
    FIELD_WATER_OFF_VALUE,
    UploadCandidate,
    UploadEndpoint,
    UploadOutcome,
    UploadReceipt,
    check_batch,
    classify_upload_response,
    validate_upload_name,
)

#: 在页面里发一次 multipart 上传的表达式。``PAYLOAD`` 由 Python 侧替换。
#:
#: 细节说明：
#:
#: * 文件内容以 base64 传进页面再还原成 ``File``——**不**用
#:   ``DOM.setFileInputFiles``，因为那要求页面上真有上传控件；
#:   协议路线的意义就是不需要控件。
#: * ``credentials: 'include'`` 让浏览器带上 cookie（含 httpOnly）。
#: * 响应文本原样取回，分类交给 Python 侧，**不在页面里判断成功**。
#: * 异常变成 ``{ok:false, error}`` 而不是抛出去，避免堆栈里带上请求头。
PAGE_UPLOAD_EXPRESSION = r"""
(async () => {
  const SPEC = PAYLOAD;
  const binary = atob(SPEC.base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  const form = new FormData();
  for (const field of SPEC.fields) {
    form.append(field[0], field[1]);
  }
  const blob = new Blob([bytes], { type: SPEC.contentType });
  form.append(SPEC.fileField, blob, SPEC.filename);
  // ⚠️ **用 XMLHttpRequest，不用 fetch。**
  //
  // 理由：官方客户端的图片上传走的是 XHR（bundle 原文 ``new XMLHttpRequest;
  // open("PUT", …)``，Plupload 也是 XHR），而阿里的风控 SDK（AWSC / ET，
  // 页面上实际加载了 ``awsc.js`` / ``et_f.js`` / ``baxiaCommon.js``）**主要挂在
  // XMLHttpRequest 上**做设备指纹与签名。用 fetch 发出去的请求可能拿不到这套
  // 指纹，于是被判定成「非官方客户端」——实测表现就是 ``RGV587_ERROR`` 风控。
  // 所以这里按平台自己的方式来：XHR + withCredentials。
  return await new Promise(resolve => {
    try {
      const request = new XMLHttpRequest();
      request.open('POST', SPEC.url, true);
      request.withCredentials = true;
      request.onload = () => {
        resolve({ ok: true, status: request.status, text: String(request.responseText || '') });
      };
      request.onerror = () => resolve({ ok: false, error: 'xhr_error' });
      request.ontimeout = () => resolve({ ok: false, error: 'xhr_timeout' });
      request.send(form);
    } catch (error) {
      resolve({ ok: false, error: String(error && error.message ? error.message : error) });
    }
  });
})()
"""


class PageUploadError(RuntimeError):
    """页面内上传失败（通道问题，不是平台拒绝）。"""


@dataclass
class PageSession:
    """一个已登录的页面上传会话。

    生命周期由调用方管理：:func:`open_session` 会**新开一页**（不动用户当前标签页），
    用完调 :meth:`close` 关掉它。
    """

    browser: CdpBrowser
    session_id: str
    target_id: str = ""
    page_url: str = ""

    # -- token ---------------------------------------------------------------
    def read_tb_token(self) -> str:
        """从页面读 ``_tb_token_``。

        这个 cookie **不是 httpOnly**（图片空间的 SDK 也是在页面里读它并作为
        表单字段发送的），所以页面里能读到。读不到就如实报错——
        上传缺这个字段会被平台拒，猜一个值只会更难查。
        """

        value = self.browser.evaluate(
            "(() => { const m = document.cookie.match(/(?:^|;\\s*)_tb_token_=([^;]*)/);"
            " return m ? decodeURIComponent(m[1]) : ''; })()",
            session_id=self.session_id,
            await_promise=False,
            timeout=15.0,
        )
        if not isinstance(value, str) or not value.strip():
            raise PageUploadError(
                "页面里读不到 _tb_token_：当前不是淘宝登录态，"
                "或该 cookie 变成了 httpOnly（那样协议上传需要换一种取 token 的方式）"
            )
        return value.strip()

    # -- 发送 ---------------------------------------------------------------
    def send_form_data(
        self,
        url: str,
        *,
        file_path: str,
        filename: str,
        fields: Sequence[Tuple[str, str]],
        content_type: str = "image/jpeg",
    ) -> Tuple[int, str]:
        """在页面里组 FormData 并发出去。返回 ``(http_status, text)``。"""

        with open(file_path, "rb") as stream:
            payload = stream.read()
        spec = {
            "url": url,
            "base64": base64.b64encode(payload).decode("ascii"),
            "filename": filename,
            "fileField": FIELD_FILE,
            "contentType": content_type,
            "fields": [list(item) for item in fields],
        }
        expression = PAGE_UPLOAD_EXPRESSION.replace(
            "PAYLOAD", json.dumps(spec, ensure_ascii=False), 1
        )
        try:
            result = self.browser.evaluate(expression, session_id=self.session_id, timeout=90.0)
        except CdpClientError as exc:
            raise PageUploadError(f"页面内发送上传请求失败：{exc}") from exc
        if not isinstance(result, Mapping) or result.get("ok") is not True:
            reason = (result or {}).get("error") if isinstance(result, Mapping) else "无返回"
            raise PageUploadError(f"页面内发送上传请求失败：{reason}")
        return int(result.get("status") or 0), str(result.get("text") or "")

    def close(self) -> None:
        """关掉本会话开的标签页（不碰用户的其它标签页）。"""

        target = self.target_id
        if target:
            self.browser.close_target(target)


def content_type_for(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".gif"):
        return "image/gif"
    if lowered.endswith(".bmp"):
        return "image/bmp"
    return "application/octet-stream"


def open_session(
    browser: CdpBrowser,
    *,
    url: str = "https://stream-upload.taobao.com/",
    settle_seconds: float = 4.0,
) -> PageSession:
    """开一个做上传用的工作页并附加。

    .. warning::
        * 页面地址**必须与上传端点同源**（默认 ``stream-upload.taobao.com``）：
          实测在其它 taobao 域页面里发这个请求会被浏览器以
          ``TypeError: Failed to fetch`` 拒掉（跨源 CORS）。
        * 导航后要等页面稳定再求值，否则 CDP 会报
          ``Execution context was destroyed``（实测）。
    """

    target = browser.new_page(url)
    session_id = browser.attach(target.target_id)
    if settle_seconds > 0:
        time.sleep(settle_seconds)
    return PageSession(
        browser=browser, session_id=session_id, target_id=target.target_id, page_url=target.url
    )


@dataclass(frozen=True, slots=True)
class PageUploadReport:
    """整批上传结果（页面路线）。字段与 ``upload_client.BatchUploadReport`` 对齐。"""

    receipts: Tuple[UploadReceipt, ...] = ()
    failed: Tuple[Dict[str, Any], ...] = ()
    stopped_reason: str = ""
    attempted: int = 0
    authorization: Mapping[str, Any] = field(default_factory=dict)
    challenge_url: str = ""
    """平台给出的人工验证入口（风控时才有）。**交给人去完成，不自动处理。**"""

    @property
    def ok(self) -> bool:
        return not self.failed and not self.stopped_reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "attempted": self.attempted,
            "receipt_count": len(self.receipts),
            "receipts": [item.to_dict() for item in self.receipts],
            "failed": [dict(item) for item in self.failed],
            "stopped_reason": self.stopped_reason,
            "challenge_url": self.challenge_url,
            "authorization": dict(self.authorization or {}),
        }


class PictureSpacePageUploader:
    """用**页面内 fetch** 把本地图片送进图片空间。

    与 :class:`taobao_publish.upload_client.PictureSpaceUploader` 的差别只有发送方式；
    URL 契约、本地护栏、响应分类、限流即停的语义**完全共用**。

    .. warning::
        每次上传都要过一次写授权门（``upload_image``）。
    """

    def __init__(
        self,
        session: PageSession,
        *,
        endpoint_host: Optional[str] = None,
    ) -> None:
        self._session = session
        self._endpoint_host = endpoint_host

    def upload_one(
        self,
        candidate: UploadCandidate,
        *,
        folder_id: str,
        authorization: WriteAuthorization,
        token: Optional[str] = None,
    ) -> UploadOutcome:
        authorization.require(WRITE_UPLOAD_IMAGE)
        candidate.validate()
        validate_upload_name(candidate.name)
        endpoint = UploadEndpoint(
            folder_id=folder_id, **({"host": self._endpoint_host} if self._endpoint_host else {})
        )
        url = endpoint.build_url()
        tb_token = token if token is not None else self._session.read_tb_token()
        # 字段顺序与 bundle 原文一致：water → name → _tb_token_ → （file 由页面 append）
        fields = [
            (FIELD_WATER, FIELD_WATER_OFF_VALUE),
            (FIELD_NAME, candidate.name),
            (FIELD_TOKEN, tb_token),
        ]
        try:
            status, text = self._session.send_form_data(
                url,
                file_path=candidate.path,
                filename=candidate.name,
                fields=fields,
                content_type=content_type_for(candidate.name),
            )
        except PageUploadError as exc:
            return UploadOutcome(ok=False, error_code="PLATFORM_ERROR", message=str(exc))
        except OSError as exc:
            return UploadOutcome(ok=False, error_code="IMAGE_UPLOAD_FAILED",
                                 message=f"读取本地图片失败：{exc}")
        return classify_upload_response(
            http_status=status, text=text, name=candidate.name, folder_id=folder_id
        )

    def upload_batch(
        self,
        candidates: Sequence[UploadCandidate],
        *,
        folder_id: str,
        authorization: WriteAuthorization,
        progress: Optional[Any] = None,
        pace_seconds: float = 0.0,
        on_receipt: Optional[Any] = None,
    ) -> PageUploadReport:
        """逐张上传整批。

        :param pace_seconds: 每张之间**主动留的间隔**。风控按频率触发，
            慢一点比撞上去再停手便宜。
        :param on_receipt: 每张成功后立刻回调——**断点续传**用：即使后面被风控
            打断，已成功的回执也已经交出去了，下次可以跳过。
        """
        authorization.require(WRITE_UPLOAD_IMAGE)
        check_batch(candidates)
        token = self._session.read_tb_token()
        receipts: List[UploadReceipt] = []
        failed: List[Dict[str, Any]] = []
        stopped_reason = ""
        challenge_url = ""
        attempted = 0
        for index, candidate in enumerate(candidates, 1):
            if callable(progress):
                progress(f"页面协议上传 {index}/{len(candidates)}：{candidate.name}")
            attempted += 1
            outcome = self.upload_one(
                candidate, folder_id=folder_id, authorization=authorization, token=token
            )
            if outcome.ok and outcome.receipt is not None:
                receipts.append(outcome.receipt)
                if callable(on_receipt):
                    on_receipt(outcome.receipt)
                if pace_seconds > 0 and index < len(candidates):
                    time.sleep(float(pace_seconds))
                continue
            failed.append({"name": candidate.name, **outcome.describe()})
            if outcome.stopped:
                stopped_reason = outcome.message
                challenge_url = outcome.challenge_url
                break
        return PageUploadReport(
            receipts=tuple(receipts),
            failed=tuple(failed),
            stopped_reason=stopped_reason,
            attempted=attempted,
            authorization=authorization.to_dict(),
            challenge_url=challenge_url,
        )

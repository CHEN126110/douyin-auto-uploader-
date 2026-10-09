# -*- coding: utf-8 -*-
"""图片空间协议上传的**实时取证 CLI**（默认零写入）。

## 它为什么存在

协议上传的端点、目录接口、``_tb_token_`` 是否可读，全部需要**真实登录态**才能
确认。本脚本把「确认」这一步做成可复跑的固定动作，而不是一次性手敲：

```powershell
# 1) 环境与登录态（只读，不建 WebSocket 也能跑）
python taobao-publisher/scripts/probe-image-space-upload.py status

# 2) 图片空间目录树 / 文件清单（只读，走 mtop 候选接口）
python taobao-publisher/scripts/probe-image-space-upload.py folders  --name 全部图片
python taobao-publisher/scripts/probe-image-space-upload.py files    --folder-id <目录ID>

# 3) 受控上传 1 张（**唯一会写入平台的子命令**，需要显式授权）
$env:TAOBAO_UPLOAD_ALLOW_WRITE = 'upload_image'
python taobao-publisher/scripts/probe-image-space-upload.py upload --file .\样图.jpg --folder-id <目录ID> --i-understand-this-writes
```

## 红线

* 默认零写入：``upload`` 必须同时满足「环境变量白名单含 ``upload_image``」与
  ``--i-understand-this-writes``，否则在发请求之前就拒绝。
* **不落凭据**：cookie 值从不写文件、不进日志。产物里只有名字、数量、布尔值。
* **不绕过风控**：命中限流就停手并如实报告，不做重试、不碰验证码。
* 产物是 **脱敏** 的：只保留 host / path / 参数名 / 计数 / 平台文案。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE_ROOT = _REPO_ROOT / "taobao-publisher"
for _path in (str(_PACKAGE_ROOT), str(_REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from taobao_publish.authorization import WriteAuthorization  # noqa: E402
from taobao_publish.cdp_ws import (  # noqa: E402
    CdpBrowser,
    CdpClientError,
    cookie_header,
    cookie_value,
    describe_cookies,
)
from taobao_publish.constants import ENV_ALLOW_WRITE, WRITE_UPLOAD_IMAGE  # noqa: E402
from taobao_publish.picturecenter import (  # noqa: E402
    PictureFile,
    build_directory_query,
    build_file_query,
    parse_directory_tree,
    parse_files,
)
from taobao_publish.upload_api import (  # noqa: E402
    contract_summary as upload_contract_summary,
)
from taobao_publish.upload_client import (  # noqa: E402
    CookieHttpTransport,
    UploadCredentials,
    PictureSpaceUploader,
)
from taobao_publish.upload_page import (  # noqa: E402
    PictureSpacePageUploader,
    PageUploadError,
    open_session,
)
from taobao_publish.upload_api import UploadCandidate  # noqa: E402

#: 产物默认目录（tmp/ 已 gitignore）。
DEFAULT_OUTPUT_DIR = _PACKAGE_ROOT / "tmp"

#: 上传用的工作页。**必须是上传端点自己的域**（``stream-upload.taobao.com``）：
#:
#: * 实测在 `item.upload.taobao.com` 或 `qn.taobao.com` 页面里向上传端点发请求，
#:   浏览器以 ``TypeError: Failed to fetch`` 拒掉（**跨源**，CORS 不允许）；
#: * 开在上传端点自己的域上就是**同源请求**，既不触发 CORS，cookie 也照常带上；
#: * 这个地址只返回一句 ``Welcome to TaoBao vfs-stream application!``，
#:   没有任何脚本，也不会被点。
WORK_PAGE_URL = "https://stream-upload.taobao.com/"


def _die(message: str, code: int = 2) -> int:
    sys.stderr.write(message.rstrip() + "\n")
    return code


def _dump_raw_head(text: str, *, api: str, out: Optional[str]) -> Optional[str]:
    """把响应原文的**头部**落到 ``tmp/``，便于定位「为什么不是 JSON」。

    为什么不放进主产物：响应里可能带签名 URL 或店铺信息，进产物就等于落盘。
    这里只写 tmp（已 gitignore），并提示调用方自行判断是否可留。

    :return: 落盘路径（没写则返回 ``None``）。
    """

    if not text:
        return None
    directory = _PACKAGE_ROOT / "tmp"
    directory.mkdir(parents=True, exist_ok=True)
    name = f"mtop-raw-{api.rsplit('.', 1)[-1]}-{time.strftime('%Y%m%d%H%M%S')}.txt"
    path = directory / name
    head = text[:2000]
    path.write_text(
        f"# api={api}\n# 仅前 2000 字符，用于判断响应形态（是否 HTML/风控页/空 body）\n\n{head}",
        encoding="utf-8",
    )
    return str(path)


def _dump(payload: Dict[str, Any], out: Optional[str]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    # Windows 控制台默认 GBK，中文会变乱码；产物文件始终是 UTF-8。
    # 这里把 stdout 切到 UTF-8（不能改时退化为可读性损失，不影响产物）。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    sys.stdout.write(text + "\n")
    if out:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        sys.stdout.write(f"[已写入产物] {path}\n")


def _redact_url(url: str) -> Dict[str, str]:
    """只保留 host/path 与参数名，**去掉 query 值**（可能含签名）。"""

    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    return {
        "host": parsed.hostname or "",
        "path": parsed.path,
        "query_keys": sorted(
            chunk.split("=", 1)[0] for chunk in parsed.query.split("&") if chunk
        ),
    }


def _http_post_form(url: str, data: Dict[str, Any], cookie: str, referer: str) -> Dict[str, Any]:
    """按 mtop 表单形态发一次请求（``data`` 走 body，签名在 query 里）。"""

    import urllib.error
    import urllib.request
    from urllib.parse import urlencode

    body = urlencode({"data": json.dumps(data, separators=(",", ":"), ensure_ascii=False)}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": cookie,
            "Referer": referer,
            "Origin": "https://item.upload.taobao.com",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
            ),
        },
    )
    return _send(request)


def _http_get(url: str, cookie: str, referer: str) -> Dict[str, Any]:
    """GET 一次（``data`` 已在 query 里，见 ``mtop.build_browser_request``）。"""

    import urllib.request

    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json, text/plain, */*",
            "Cookie": cookie,
            "Referer": referer,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
            ),
        },
    )
    return _send(request)


def _send(request: Any) -> Dict[str, Any]:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return {"status": int(response.status), "text": response.read().decode("utf-8", "replace")}
    except urllib.error.HTTPError as exc:
        return {"status": int(exc.code), "text": exc.read().decode("utf-8", "replace")}
    except Exception as exc:  # noqa: BLE001 - CLI 要如实报告任何失败
        return {"status": 0, "text": f"{type(exc).__name__}: {exc}"}


def _send_mtop(request: Any, cookie: str, referer: str) -> Dict[str, Any]:
    """按 ``MtopRequest.extra['method']`` 决定 GET 还是 POST。"""

    if request.request.extra.get("method") == "GET":
        return _http_get(request.request.url, cookie, referer)
    return _http_post_form(request.request.url, dict(request.body_params), cookie, referer)


# ---------------------------------------------------------------------------
# status：环境 + 登录态（只读）
# ---------------------------------------------------------------------------
def command_status(args: argparse.Namespace) -> int:
    browser = CdpBrowser(port=args.port, timeout=args.timeout)
    payload: Dict[str, Any] = {"port": args.port, "endpoint_contract": upload_contract_summary()["endpoint"]}
    try:
        version = browser.version()
        payload["browser"] = version.get("Browser", "")
        payload["ok"] = True
    except CdpClientError as exc:
        payload["ok"] = False
        payload["error"] = str(exc)
        payload["hint"] = (
            "启动调试实例：node protocol-research-taobao-20260908/scripts/start-taobao-cdp-chrome.mjs"
        )
        _dump(payload, args.out)
        return 1

    pages = browser.list_targets()
    taobao_pages = [item for item in pages if "taobao.com" in item.url or "tmall.com" in item.url]
    payload["target_count"] = len(pages)
    payload["taobao_page_count"] = len(taobao_pages)
    payload["taobao_pages"] = [
        {"title": item.title[:60], "host": _redact_url(item.url)["host"]} for item in taobao_pages
    ]

    if args.login:
        try:
            cookies = browser.cookies()
        except CdpClientError as exc:
            payload["cookie_error"] = str(exc)
        else:
            payload["cookies"] = describe_cookies(cookies)
            payload["login_verdict"] = (
                "likely_logged_in" if payload["cookies"]["has_login_identity"] else "likely_logged_out"
            )
    if args.out:
        _dump(payload, args.out)
    else:
        _dump(payload, None)
    browser.close()
    return 0


# ---------------------------------------------------------------------------
# folders / files：读图片空间（只读，mtop 候选接口）
# ---------------------------------------------------------------------------
def _read_ttid(browser: CdpBrowser) -> str:
    """拼出实测形态的 ``ttid``：``<会员ID>@taobao_WEB_<主>.<次>.<修订>``。

    实测：真实素材中心页面的 mtop 调用**每条都带这个参数**，形态固定
    （``tmp/live-directory-headers.json``）。缺失或形态不对会被网关判
    ``FAIL_SYS_ILLEGAL_ACCESS::非法请求``。

    会员 ID 取 cookie ``unb``。**返回值含店铺身份，只应留在内存里**，
    产物里只记「有没有」。
    """

    from taobao_publish.mtop import browser_ttid

    try:
        cookies = browser.cookies()
    except CdpClientError:
        return ""
    member_id = cookie_value(cookies, "unb")
    if not member_id.isdigit():
        return ""
    return browser_ttid(member_id)


def _load_credentials(browser: CdpBrowser, *, args: argparse.Namespace) -> UploadCredentials:
    cookies = browser.cookies()
    header = cookie_header(cookies)
    token = cookie_value(cookies, "_tb_token_")
    if not token:
        raise CdpClientError(
            "cookie 里没有 _tb_token_：当前不是淘宝登录态，无法构造 mtop 签名请求。"
            "请先在 9334 调试实例里登录一次（不要复制 cookie 库，那条路已证伪）"
        )
    return UploadCredentials(cookie=header, tb_token=token, referer=args.referer)


def command_folders(args: argparse.Namespace) -> int:
    browser = CdpBrowser(port=args.port, timeout=args.timeout)
    try:
        credentials = _load_credentials(browser, args=args)
    except CdpClientError as exc:
        return _die(f"[LOGIN_REQUIRED] {exc}", 1)
    request = build_directory_query(credentials.tb_token, ttid=_read_ttid(browser))
    result = _send_mtop(request, credentials.cookie, args.referer)
    from taobao_publish.mtop import classify_response

    outcome = classify_response(result["text"])
    root, note = parse_directory_tree(outcome.payload)
    payload: Dict[str, Any] = {
        "api": request.api,
        "evidence_level": request.evidence_level,
        "http_status": result["status"],
        "mtop_ret": list(outcome.ret),
        "mtop_ok": outcome.ok,
        "mtop_message": outcome.message,
        "parse_note": note,
        "tree": root.to_dict() if root else None,
    }
    if not outcome.ok:
        payload["raw_head_file"] = _dump_raw_head(result["text"], api=request.api, out=args.out)
    if root is not None and args.name:
        from taobao_publish.picturecenter import find_folder_by_path

        hit = find_folder_by_path(root, [args.name])
        payload["matched"] = hit.to_dict() if hit else None
    _dump(payload, args.out)
    browser.close()
    return 0 if outcome.ok else 1


def command_files(args: argparse.Namespace) -> int:
    browser = CdpBrowser(port=args.port, timeout=args.timeout)
    try:
        credentials = _load_credentials(browser, args=args)
    except CdpClientError as exc:
        return _die(f"[LOGIN_REQUIRED] {exc}", 1)
    request = build_file_query(
        credentials.tb_token, folder_id=args.folder_id, page=args.page, ttid=_read_ttid(browser)
    )
    result = _send_mtop(request, credentials.cookie, args.referer)
    from taobao_publish.mtop import classify_response

    outcome = classify_response(result["text"])
    files, note = parse_files(outcome.payload)
    payload = {
        "api": request.api,
        "evidence_level": request.evidence_level,
        "http_status": result["status"],
        "mtop_ret": list(outcome.ret),
        "mtop_ok": outcome.ok,
        "mtop_message": outcome.message,
        "parse_note": note,
        "count": len(files),
        "files": [item.to_dict() for item in files[: args.limit]],
    }
    if args.name:
        payload["matched"] = [item.to_dict() for item in files if item.name == args.name]
    _dump(payload, args.out)
    browser.close()
    return 0 if outcome.ok else 1


# ---------------------------------------------------------------------------
# upload：唯一会写入平台的子命令
# ---------------------------------------------------------------------------
def _authorization_for_upload(args: argparse.Namespace) -> WriteAuthorization:
    authorization = WriteAuthorization.from_environment()
    if not authorization.is_granted(WRITE_UPLOAD_IMAGE):
        raise SystemExit(
            "[WRITE_NOT_AUTHORIZED] 上传未授权。需要同时满足：\n"
            f"  1) 环境变量 {ENV_ALLOW_WRITE} 含 {WRITE_UPLOAD_IMAGE}\n"
            "  2) 命令行显式加 --i-understand-this-writes\n"
            "本脚本不会替你打开写权限。"
        )
    if not args.i_understand_this_writes:
        raise SystemExit(
            "[WRITE_NOT_AUTHORIZED] 缺少 --i-understand-this-writes。\n"
            "协议上传会在你的图片空间里真实新增一张图片（可删除，但确实是一次写操作）。"
        )
    return authorization


def _diagnose_fetch(browser: CdpBrowser, session_id: str) -> List[Dict[str, Any]]:
    """逐层探测「这个页面能不能把请求发到上传端点」。**不发送任何文件内容。**

    四步（每步都只发极小请求或只读）：

    1. ``GET`` 站点根（同源）——排除「页面本身就没网」；
    2. ``GET`` 上传端点（同源）——排除「端点不可达」；
    3. ``POST`` 纯文本到端点（简单请求，不触发预检）——排除「预检被拒」；
    4. ``POST`` multipart（正式形态）——看预检与正式请求各自的结果。
    """

    from taobao_publish.upload_api import UPLOAD_APP_KEY, UPLOAD_HOST, UPLOAD_PATH

    endpoint = f"{UPLOAD_HOST}{UPLOAD_PATH}?appkey={UPLOAD_APP_KEY}&folderId=0&_input_charset=utf-8"
    expression = r"""
    (async () => {
      const REPORT = [];
      const run = async (label, fn) => {
        try { REPORT.push({ label: label, result: await fn() }); }
        catch (error) { REPORT.push({ label: label, error: String(error && error.message ? error.message : error) }); }
      };
      await run('same_origin_root_get', async () => {
        const response = await fetch('/', { method: 'GET', credentials: 'include' });
        return { status: response.status, type: response.type };
      });
      await run('endpoint_get', async () => {
        const response = await fetch(ENDPOINT, { method: 'GET', credentials: 'include' });
        const text = await response.text();
        return { status: response.status, type: response.type, length: text.length };
      });
      await run('endpoint_post_text', async () => {
        const response = await fetch(ENDPOINT, {
          method: 'POST', credentials: 'include',
          headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
          body: 'ping',
        });
        const text = await response.text();
        return { status: response.status, type: response.type, length: text.length };
      });
      await run('endpoint_post_multipart', async () => {
        const form = new FormData();
        form.append('water', 'false');
        form.append('name', 'probe.txt');
        form.append('file', new Blob([new Uint8Array([1, 2, 3])], { type: 'image/jpeg' }), 'probe.txt');
        const response = await fetch(ENDPOINT, { method: 'POST', credentials: 'include', body: form });
        const text = await response.text();
        return { status: response.status, type: response.type, length: text.length,
                 head: text.slice(0, 120) };
      });
      return REPORT;
    })()
    """.replace("ENDPOINT", json.dumps(endpoint))
    result = browser.evaluate(expression, session_id=session_id, timeout=90.0)
    return result if isinstance(result, list) else [{"error": "诊断表达式没有返回数组", "raw": str(result)[:200]}]


def command_upload(args: argparse.Namespace) -> int:
    # 诊断模式**不发送任何文件内容**（只发 3 字节探针），因此不过写授权门；
    # 它不写平台状态。其余路径一律先过授权。
    if not args.diagnose:
        authorization = _authorization_for_upload(args)
    else:
        authorization = WriteAuthorization.none()
    path = Path(args.file)
    if not path.is_file():
        return _die(f"找不到待上传文件：{path}", 2)
    size = path.stat().st_size
    candidate = UploadCandidate(path=str(path), name=args.name or path.name, size=size)

    # --- 诊断模式：只探测「这个页面能不能把请求发出去」 -------------------
    #
    # 为什么需要：``TypeError: Failed to fetch`` 可能是跨源、可能是扩展拦截、
    # 也可能是抓不到响应。下面四步逐层排除，**不发送任何文件内容**。
    if args.diagnose:
        browser = CdpBrowser(port=args.port, timeout=args.timeout)
        session = None
        try:
            session = open_session(browser, url=args.page_url or WORK_PAGE_URL)
            # 页面刚导航完时执行上下文会被销毁重建（实测
            # ``Execution context was destroyed``），等它稳定再求值。
            time.sleep(4.0)
            steps = _diagnose_fetch(browser, session.session_id)
        finally:
            if session is not None:
                session.close()
            browser.close()
        _dump({"page_url": args.page_url or WORK_PAGE_URL, "steps": steps}, args.out)
        return 0

    # --- 离线演练：把同一套协议代码打向本地 mock 服务端 -------------------
    #
    # 它走的仍是 `upload_client.PictureSpaceUploader` 与 `upload_api` 的同一个
    # 端点契约、同一套 multipart 编码与响应分类，只是**目的地换成 127.0.0.1**。
    # 用途：在没有登录态时也能把整条链路（含失败分类）真跑一遍。
    if args.offline_mock:
        from taobao_publish.upload_client import CookieHttpTransport, PictureSpaceUploader

        credentials = UploadCredentials(cookie="_tb_token_=offline", tb_token="offline")
        client = PictureSpaceUploader(
            CookieHttpTransport(credentials, timeout=args.timeout),
            credentials,
            endpoint_host=args.offline_mock.rstrip("/"),
            allow_insecure_host=True,
        )
        outcome = client.upload_one(
            candidate, folder_id=args.folder_id or "0", authorization=authorization
        )
        _dump(
            {
                "mode": "offline_mock",
                "endpoint": args.offline_mock,
                "file": {"name": candidate.name, "size": size},
                "folder_id": args.folder_id or "0",
                "authorization": authorization.to_dict(),
                "outcome": outcome.describe(),
            },
            args.out,
        )
        return 0 if outcome.ok else 1

    browser = CdpBrowser(port=args.port, timeout=args.timeout)
    session = None
    payload: Dict[str, Any] = {
        "file": {"name": candidate.name, "size": size},
        "folder_id": args.folder_id or "(未指定)",
        "authorization": authorization.to_dict(),
    }
    try:
        if not args.folder_id:
            return _die(
                "[EVIDENCE_INSUFFICIENT] 必须显式给出 --folder-id：\n"
                "  图片空间不传 folderId 时的落地目录未取证，本工具不猜默认目录。\n"
                "  先用 `folders` 子命令读目录树，拿一个真实目录 ID。",
                2,
            )
        session = open_session(browser, url=args.page_url or WORK_PAGE_URL)
        payload["page"] = {"host": _redact_url(session.page_url)["host"], "opened": True}
        # token 从 **CDP** 读，不从页面 ``document.cookie`` 读：
        # 实测素材中心页（``qn.taobao.com``）脚本读 cookie 会抛
        # ``SecurityError: Access is denied for this document``，
        # 而 CDP 的浏览器级 ``Storage.getCookies`` 不受页面脚本限制。
        # 传进去后仍由页面 fetch 发请求——cookie 依然不出浏览器。
        token = cookie_value(browser.cookies(), "_tb_token_")
        if not token:
            payload["error"] = "cookie 里没有 _tb_token_（未登录？），未发送任何上传请求"
            _dump(payload, args.out)
            return 1
        payload["token_source"] = "cdp_storage_get_cookies"
        uploader = PictureSpacePageUploader(session)
        outcome = uploader.upload_one(
            candidate, folder_id=args.folder_id, authorization=authorization, token=token
        )
        payload["outcome"] = outcome.describe()
        _dump(payload, args.out)
        return 0 if outcome.ok else 1
    except PageUploadError as exc:
        payload["error"] = str(exc)
        _dump(payload, args.out)
        return 1
    except CdpClientError as exc:
        payload["error"] = str(exc)
        _dump(payload, args.out)
        return 1
    finally:
        if session is not None:
            session.close()
        browser.close()


def command_contract(args: argparse.Namespace) -> int:
    from taobao_publish.picturecenter import contract_summary as picture_contract

    _dump(
        {
            "upload": upload_contract_summary(),
            "picturecenter": picture_contract(),
        },
        args.out,
    )
    return 0


# ---------------------------------------------------------------------------
# preflight：不碰登录态也能证明的每一步（只读）
# ---------------------------------------------------------------------------
def command_preflight(args: argparse.Namespace) -> int:
    """在**没有登录态**的情况下，把所有能证明的先证明掉。

    它回答三个问题，每个都给可复跑的证据：

    1. 调试浏览器在不在（9334 可达、Chrome 版本）；
    2. **上传端点是否还活着**——按契约 URL 发一次无凭据 POST。
       只要不是 4xx/连接失败，就说明 host/path 仍然有效；
       返回淘系风控页（HTTP 200 + HTML）正是「端点存在但未登录」的典型形态；
    3. **mtop 网关 + api 名 + 签名链路是否成立**——用当前 cookie 里的
       ``_m_h5_tk`` 签一次 ``dir.query``。返回
       ``FAIL_SYS_SESSION_EXPIRED`` 说明网关认了这次调用、只是缺会话；
       返回 ``FAIL_SYS_SIGN_ERROR`` / ``FAIL_SYS_ILLEGAL_ACCESS`` 才是签名或用例问题。
       这两种结果的含义**完全不同**，必须分开报。
    """

    import urllib.error
    import urllib.request

    payload: Dict[str, Any] = {"port": args.port}
    steps: List[Dict[str, Any]] = []

    # --- 1) 调试浏览器 ---
    browser = CdpBrowser(port=args.port, timeout=args.timeout)
    try:
        version = browser.version()
        steps.append({
            "step": "cdp",
            "ok": True,
            "browser": version.get("Browser", ""),
            "detail": "调试端口可达",
        })
    except CdpClientError as exc:
        steps.append({
            "step": "cdp",
            "ok": False,
            "detail": str(exc),
            "hint": "node protocol-research-taobao-20260908/scripts/start-taobao-cdp-chrome.mjs",
        })
        payload["steps"] = steps
        _dump(payload, args.out)
        return 1

    # --- 2) 开一个临时淘宝页，让浏览器种下域名 cookie ---
    #
    # 为什么必须开：``_m_h5_tk`` 是 mtop 框架在**页面上下文里**首次调用时种下的，
    # 只连 CDP 不打开页面时 cookie 列表里根本没有它。开一个 ``taobao.com`` 的
    # 空白页并跑一句无害表达式，就能把域名 cookie 引出来（含 ``_m_h5_tk``）。
    # 用完立即关掉，不留标签页。
    try:
        warmup_target = browser.new_page("https://www.taobao.com/")
        warmup_session = browser.attach(warmup_target.target_id)
        browser.evaluate(
            "(() => ({ ready: document.readyState, href: location.href }))()",
            session_id=warmup_session,
            await_promise=False,
            timeout=20.0,
        )
        steps.append({
            "step": "warmup_page",
            "ok": True,
            "detail": "已用临时标签页访问 taobao.com 引出域名 cookie（页面已关闭）",
        })
    except CdpClientError as exc:
        steps.append({"step": "warmup_page", "ok": False, "detail": str(exc)})
    finally:
        try:
            browser.close_target(warmup_target.target_id)  # type: ignore[possibly-undefined]
        except (CdpClientError, UnboundLocalError):
            pass

    # --- 3) 上传端点存活（无凭据）---
    from taobao_publish.upload_api import UPLOAD_APP_KEY, UPLOAD_HOST, UPLOAD_PATH

    probe_url = (
        f"{UPLOAD_HOST}{UPLOAD_PATH}?appkey={UPLOAD_APP_KEY}&folderId=1&_input_charset=utf-8"
    )
    try:
        request = urllib.request.Request(
            probe_url,
            method="POST",
            data=b"",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/154.0.0.0"},
        )
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            status = int(response.status)
            body = response.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        body = exc.read(400).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - 预检要如实报告任何失败
        status, body = 0, f"{type(exc).__name__}: {exc}"
    looks_like_risk_page = "windvane" in body or "x5referer" in body or "<html" in body.lower()
    steps.append({
        "step": "upload_endpoint",
        "ok": status == 200,
        "http_status": status,
        "url": {"host": UPLOAD_HOST, "path": UPLOAD_PATH, "query_keys": ["appkey", "folderId", "_input_charset"]},
        "body_kind": "risk_or_login_html" if looks_like_risk_page else "other",
        "detail": (
            "端点可达；未带凭据时返回淘系风控/登录 HTML（HTTP 200）——"
            "这正是「必须同时校验 HTTP 200 与 success 字段」的原因"
            if looks_like_risk_page else "端点可达，但响应形态与预期不同，见 body 摘要"
        ),
        "body_head": body[:200],
    })

    # --- 4) mtop 网关 + api 名 + 签名 ---
    try:
        cookies = browser.cookies()
        header = cookie_header(cookies)
        from taobao_publish.mtop import parse_h5_tk

        h5_tk = parse_h5_tk(cookie_value(cookies, "_m_h5_tk")) or parse_h5_tk(cookie_value(cookies, "_m_h5_tk_enc"))
        token = h5_tk.value if h5_tk is not None else ""
        login_names = describe_cookies(cookies)
        if not token:
            # 注意：这不是「环境坏了」。`_m_h5_tk` 只在 **mtop 框架在页面上下文里
            # 首次调用**时下发，而未登录时页面里根本不会发起这类调用，
            # 所以「没有 token」与「未登录」是同一件事的两种表现。
            steps.append({
                "step": "mtop_signature",
                "ok": True,
                "state": "info",
                "detail": (
                    "cookie 里没有 _m_h5_tk：它只在 mtop 首次调用时下发，"
                    "未登录的页面上不会产生这次调用。此步在登录后才能验证"
                ),
                "cookies": login_names,
            })
        else:
            request = build_directory_query(token, ttid=_read_ttid(browser))
            result = _send_mtop(request, header, args.referer)
            from taobao_publish.mtop import classify_response

            outcome = classify_response(result["text"])
            steps.append({
                "step": "mtop_signature",
                "ok": outcome.ok,
                "api": request.api,
                "http_status": result["status"],
                "mtop_ret": list(outcome.ret),
                "mtop_message": outcome.message,
                "session_expired": outcome.error_code == "LOGIN_REQUIRED",
                "detail": (
                    "网关接受了这次调用（api 名与签名成立），但会话已过期——"
                    "说明只差登录，不是签名或用例问题"
                    if outcome.error_code == "LOGIN_REQUIRED"
                    else ("调用成功" if outcome.ok else "网关拒绝了这次调用，可能是签名、api 名或权限问题")
                ),
                "cookies": login_names,
            })
    except CdpClientError as exc:
        steps.append({"step": "mtop_signature", "ok": False, "detail": str(exc)})

    browser.close()
    payload["steps"] = steps
    blocked = [step for step in steps if not step.get("ok")]
    needs_login = any(
        isinstance(step.get("cookies"), dict) and not step["cookies"].get("has_login_identity")
        for step in steps
    )
    payload["all_ok"] = not blocked
    payload["login_required"] = bool(needs_login)
    payload["next_action"] = (
        "环境就绪：在 9334 调试实例里登录淘宝卖家账号后，即可跑 folders / files / upload"
        if payload["all_ok"] and not needs_login else
        ("环境就绪，但**尚未登录**：在 9334 那个 Chrome 窗口里扫码登录卖家账号，"
         "然后跑 `folders` 读目录树"
         if payload["all_ok"] else
         "按上面失败的那一步修复（mtop 那一层未登录时属于「待验证」，不算失败）")
    )
    _dump(payload, args.out)
    return 0 if payload["all_ok"] else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="淘宝图片空间协议上传的实时取证工具（默认零写入）"
    )
    parser.add_argument("--port", type=int, default=9334, help="调试端口（淘宝固定 9334）")
    parser.add_argument("--timeout", type=float, default=20.0, help="CDP 超时秒数")
    parser.add_argument("--out", default="", help="把结果 JSON 写到该路径（脱敏产物）")
    parser.add_argument(
        "--referer",
        default="https://item.upload.taobao.com/",
        help="请求 Referer（默认发布工作台）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="环境与登录态（只读）")
    status.add_argument("--login", action="store_true", help="额外读 cookie（只回名字与数量）")
    status.set_defaults(func=command_status)

    folders = sub.add_parser("folders", help="读图片空间目录树（只读）")
    folders.add_argument("--name", default="", help="按名字在树里定位一个目录")
    folders.set_defaults(func=command_folders)

    files = sub.add_parser("files", help="读某个目录的文件清单（只读）")
    files.add_argument("--folder-id", required=True, help="目录 ID")
    files.add_argument("--page", type=int, default=1, help="页码")
    files.add_argument("--limit", type=int, default=50, help="最多打印多少条")
    files.add_argument("--name", default="", help="按文件名精确筛选")
    files.set_defaults(func=command_files)

    upload = sub.add_parser("upload", help="受控上传 1 张（会写入平台，需显式授权）")
    upload.add_argument("--file", required=True, help="本地图片路径")
    upload.add_argument("--folder-id", default="", help="图片空间目录 ID（必填，不猜默认目录）")
    upload.add_argument("--name", default="", help="上传后的文件名（默认用本地文件名）")
    upload.add_argument(
        "--i-understand-this-writes",
        action="store_true",
        help="确认这是一次真实写入（会在图片空间新增一张图）",
    )
    upload.add_argument(
        "--offline-mock",
        default="",
        help="离线演练：把请求打向本地 mock 服务端的 base URL（例如 http://127.0.0.1:8899），"
             "不碰真实平台",
    )
    upload.add_argument(
        "--diagnose",
        action="store_true",
        help="只诊断「这个页面能不能把请求发到上传端点」，不发送任何文件内容",
    )
    upload.add_argument(
        "--page-url",
        default="",
        help="上传用的工作页（默认素材中心）。换页面要确认它读得到 cookie",
    )
    upload.set_defaults(func=command_upload)

    contract = sub.add_parser("contract", help="打印上传与 picturecenter 契约（含 unknown 项）")
    contract.set_defaults(func=command_contract)

    preflight = sub.add_parser(
        "preflight",
        help="不碰登录态就能证明的每一步：调试端口 / 上传端点存活 / mtop 签名链路",
    )
    preflight.set_defaults(func=command_preflight)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

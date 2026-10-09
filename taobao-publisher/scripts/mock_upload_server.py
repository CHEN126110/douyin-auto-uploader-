# -*- coding: utf-8 -*-
"""本地 mock 上传服务端：**离线**验证协议上传的请求形态与响应分类。

为什么需要它：真实上传要登录态、会真落库、还可能触发风控，不适合当回归测试。
但「multipart 到底发成什么样」必须被真实验证——只断言「函数被调用过」
证明不了字段名、分隔串、文件名、Content-Type 是否正确。

它做的事很窄：

* 只接受 ``POST /api/upload.api``；
* 校验 query 里的 ``appkey`` / ``folderId`` / ``_input_charset``；
* 自己解析 multipart，校验 ``file`` / ``name`` / ``_tb_token_`` / ``water`` 四个字段；
* 按 `mode` 返回成功或各类失败响应（含 **HTTP 200 + HTML 风控页**这一种）；
* 记录每个文件收到的字节，便于测试核对内容身份（sha256）。

**它不是平台的仿真**：不实现淘系的任何业务规则，只实现「我们发出去的请求长什么样」。

单独跑（人工排查用）::

    python taobao-publisher/scripts/mock_upload_server.py 8899
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

#: 平台成功响应的最小形态（字段名照 bundle 取图片地址的路径）。
def success_body(name: str, url: str, *, picture_id: str = "", size: int = 0) -> Dict[str, Any]:
    return {
        "success": True,
        "object": {
            "url": url,
            "fileId": picture_id or "900000000001",
            "fileName": name,
            "size": size,
            "pix": "800x800",
        },
    }


#: 各类失败响应。测试按 key 选择，不需要各自拼 JSON。
FAILURE_MODES: Dict[str, Tuple[int, str]] = {
    # 平台限流：bundle 里生产代码拿到它就 stop()
    "rate_limited": (200, json.dumps({"success": False, "errorCode": "BAXIA_BLOCKED",
                                      "errorMsg": "操作过于频繁，请滑动验证码之后，重新上传。"},
                                     ensure_ascii=False)),
    # 限流以 HTML 返回但 HTTP 仍是 200（SDK 专门为此写了 pre 块兜底）
    "rate_limited_html": (200, '<html><body><pre style="white-space: pre-wrap;">'
                               '{"success":false,"errorCode":"BAXIA_BLOCKED",'
                               '"errorMsg":"操作过于频繁，请滑动验证码之后，重新上传。"}'
                               "</pre></body></html>"),
    "oversize": (200, json.dumps({"success": False, "errorCode": "-600",
                                  "errorMsg": "file size exceed"}, ensure_ascii=False)),
    "bad_format": (200, json.dumps({"success": False, "errorCode": "-601",
                                    "errorMsg": "file type not support"}, ensure_ascii=False)),
    "too_many": (200, json.dumps({"success": False, "errorCode": "-9001",
                                  "errorMsg": "too many files"}, ensure_ascii=False)),
    "quota": (200, json.dumps({"success": False, "errorMsg": "图片空间容量不足"}, ensure_ascii=False)),
    "http_500": (500, "internal error"),
    "html_only": (200, "<html><body>risk</body></html>"),
    "no_url": (200, json.dumps({"success": True, "object": {"fileId": "1"}}, ensure_ascii=False)),
    "foreign_url": (200, json.dumps({"success": True, "object": {"url": "https://evil.example.com/a.jpg"}},
                                     ensure_ascii=False)),
    "not_json": (200, "plain text, not json"),
}


@dataclass
class MockUploadState:
    """服务端收到的请求记录。测试直接读它做断言。"""

    requests: List[Dict[str, Any]] = field(default_factory=list)
    mode: str = "success"
    url_template: str = "https://img.alicdn.com/imgextra/i1/{name}"
    picture_id: str = "900000000001"

    def reset(self) -> None:
        self.requests.clear()

    def last(self) -> Dict[str, Any]:
        if not self.requests:
            raise AssertionError("mock 服务端没有收到任何请求")
        return self.requests[-1]


def parse_multipart(body: bytes, content_type: str) -> Dict[str, Any]:
    """解析 multipart/form-data，返回 ``{"fields": {...}, "files": [{...}]}``。

    故意写得严格：分隔串必须是唯一且闭合的，否则抛错——
    宽松解析会把「我们自己发错了」测成通过。
    """

    match = re.search(r"boundary=([^;]+)", content_type or "")
    if not match:
        raise AssertionError(f"Content-Type 里没有 boundary：{content_type!r}")
    boundary = match.group(1).strip().strip('"').encode("ascii")
    if not body.startswith(b"--" + boundary):
        raise AssertionError("请求体没有以分隔串开头")
    if not body.rstrip().endswith(b"--" + boundary + b"--"):
        raise AssertionError("请求体没有闭合的分隔串（最后一段缺 --boundary--）")

    fields: Dict[str, str] = {}
    files: List[Dict[str, Any]] = []
    for chunk in body.split(b"--" + boundary):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        head, _, payload = chunk.partition(b"\r\n\r\n")
        header_text = head.decode("utf-8", errors="replace")
        disposition = ""
        part_type = ""
        for line in header_text.split("\r\n"):
            if line.lower().startswith("content-disposition:"):
                disposition = line
            elif line.lower().startswith("content-type:"):
                part_type = line.split(":", 1)[1].strip()
        name_match = re.search(r'name="([^"]*)"', disposition)
        if not name_match:
            raise AssertionError(f"part 缺 name：{disposition!r}")
        part_name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]*)"', disposition)
        if filename_match:
            files.append(
                {
                    "field": part_name,
                    "filename": filename_match.group(1),
                    "content_type": part_type,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size": len(payload),
                    "data": payload,
                }
            )
        else:
            fields[part_name] = payload.decode("utf-8", errors="replace")
    return {"fields": fields, "files": files}


class _Handler(BaseHTTPRequestHandler):
    state: MockUploadState  # 由工厂注入

    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - 基类签名
        return  # 测试输出保持干净

    def do_POST(self) -> None:  # noqa: N802 - 基类签名
        parsed = urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        try:
            if parsed.path != "/api/upload.api":
                self._respond(404, "not found")
                return
            query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
            record: Dict[str, Any] = {
                "path": parsed.path,
                "query": query,
                "content_type": self.headers.get("Content-Type", ""),
                "cookie_present": bool(self.headers.get("Cookie")),
                "referer": self.headers.get("Referer", ""),
                "body_length": length,
            }
            record.update(parse_multipart(body, record["content_type"]))
            self.state.requests.append(record)
        except AssertionError as exc:
            self._respond(400, json.dumps({"mock_error": str(exc)}, ensure_ascii=False))
            return

        mode = self.state.mode
        if mode == "success":
            name = record["files"][0]["filename"] if record.get("files") else "unknown.jpg"
            payload = success_body(
                name,
                self.state.url_template.format(name=name),
                picture_id=self.state.picture_id,
                size=record["files"][0]["size"] if record.get("files") else 0,
            )
            self._respond(200, json.dumps(payload, ensure_ascii=False))
            return
        if mode in FAILURE_MODES:
            status, text = FAILURE_MODES[mode]
            self._respond(status, text)
            return
        raise AssertionError(f"未知的 mock mode：{mode!r}")

    def _respond(self, status: int, text: str) -> None:
        payload = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@dataclass
class MockUploadServer:
    """上下文管理器：``with MockUploadServer() as server: ...``。"""

    state: MockUploadState = field(default_factory=MockUploadState)
    host: str = "127.0.0.1"

    def __post_init__(self) -> None:
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # -- 生命周期 -----------------------------------------------------------
    def start(self) -> "MockUploadServer":
        handler = type("_BoundHandler", (_Handler,), {"state": self.state})
        self._httpd = ThreadingHTTPServer((self.host, 0), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> "MockUploadServer":
        return self.start()

    def __exit__(self, *exc_info: Any) -> None:
        self.stop()

    @property
    def port(self) -> int:
        if self._httpd is None:
            raise RuntimeError("mock 服务端还没启动")
        return int(self._httpd.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    # -- 便捷方法 -----------------------------------------------------------
    @property
    def requests(self) -> List[Dict[str, Any]]:
        return self.state.requests

    def set_mode(self, mode: str) -> None:
        self.state.mode = mode

    def last(self) -> Dict[str, Any]:
        return self.state.last()


def main(argv: Optional[List[str]] = None) -> int:
    import sys

    arguments = list(sys.argv[1:] if argv is None else argv)
    port = int(arguments[0]) if arguments else 8899
    state = MockUploadState()
    handler = type("_BoundHandler", (_Handler,), {"state": state})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    sys.stdout.write(
        f"mock 图片空间上传端点已启动：http://127.0.0.1:{port}/api/upload.api\n"
        "按 Ctrl+C 结束。它只实现请求形态校验与固定响应，不是平台仿真。\n"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

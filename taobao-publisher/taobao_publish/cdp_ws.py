# -*- coding: utf-8 -*-
"""极简 CDP 客户端（标准库 WebSocket + HTTP）。

为什么要自己写：仓库里既有 Python 侧 CDP（``taobao_publish/cdp.py``，只读
``/json/list``，**不建 WebSocket**）和 Node 侧 CDP（``mcp-server/cdp-client.js``），
而协议上传的实时取证需要在 Python 里读 cookie、在页面上下文里发请求。
装第三方 websocket 库会给打包加依赖，所以这里按 RFC 6455 写最小实现。

能力范围**故意很窄**：``Runtime.evaluate`` / 浏览器级 ``Network.getAllCookies`` /
``Target`` 管理。不做拦截、不做网络监听、不做文件系统域操作。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


class CdpClientError(RuntimeError):
    """CDP 通道不可用。"""


# ---------------------------------------------------------------------------
# 最小 WebSocket 客户端
# ---------------------------------------------------------------------------
class WebSocketClient:
    """只支持 ``text`` 帧、无分片、无扩展的最小客户端。"""

    def __init__(self, url: str, *, timeout: float = 20.0) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in ("ws", "wss"):
            raise CdpClientError(f"不是 WebSocket 地址：{url}")
        self._timeout = timeout
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        raw = socket.create_connection((host, port), timeout=timeout)
        if parsed.scheme == "wss":
            context = ssl.create_default_context()
            raw = context.wrap_socket(raw, server_hostname=host)
        raw.settimeout(timeout)
        self._socket = raw
        # ⚠️ `_buffer` 必须在握手**之前**建好：握手响应里可能已经带上了第一帧，
        # 那时 `_handshake` 会往 `self._buffer` 里塞数据。
        self._buffer = bytearray()
        self._next_id = 1
        self._handshake(parsed, host, port)

    def _handshake(self, parsed, host: str, port: int) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._socket.sendall(request.encode("ascii"))
        header = b""
        deadline = time.monotonic() + self._timeout
        while b"\r\n\r\n" not in header:
            if time.monotonic() > deadline:
                raise CdpClientError("WebSocket 握手超时")
            chunk = self._socket.recv(4096)
            if not chunk:
                raise CdpClientError("WebSocket 握手期间连接被关闭")
            header += chunk
        head, _, rest = header.partition(b"\r\n\r\n")
        status_line = head.split(b"\r\n", 1)[0].decode("latin-1")
        if "101" not in status_line:
            raise CdpClientError(f"WebSocket 握手失败：{status_line}")
        self._buffer.extend(rest)

    # -- 收发 ---------------------------------------------------------------
    def _recv_exact(self, count: int) -> bytes:
        while len(self._buffer) < count:
            chunk = self._socket.recv(65536)
            if not chunk:
                raise CdpClientError("连接已关闭")
            self._buffer.extend(chunk)
        data = bytes(self._buffer[:count])
        del self._buffer[:count]
        return data

    def _send_frame(self, payload: bytes, *, opcode: int = 0x1) -> None:
        mask = os.urandom(4)
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack(">Q", length))
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self._socket.sendall(bytes(header) + masked)

    def _recv_frame(self) -> Tuple[int, bytes]:
        first, second = self._recv_exact(2)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._recv_exact(8))[0]
        if second & 0x80:
            mask = self._recv_exact(4)
        else:
            mask = b""
        payload = self._recv_exact(length)
        if mask:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def send_json(self, payload: Mapping[str, Any]) -> None:
        self._send_frame(json.dumps(payload).encode("utf-8"))

    def recv_json(self) -> Dict[str, Any]:
        while True:
            opcode, payload = self._recv_frame()
            if opcode == 0x8:  # close
                raise CdpClientError("CDP 连接被对端关闭")
            if opcode == 0x9:  # ping
                self._send_frame(payload, opcode=0xA)
                continue
            if opcode != 0x1:
                continue
            try:
                return json.loads(payload.decode("utf-8"))
            except ValueError as exc:
                raise CdpClientError(f"收到非法 JSON 帧：{exc}") from exc

    def close(self) -> None:
        try:
            self._send_frame(b"", opcode=0x8)
        except OSError:
            pass
        try:
            self._socket.close()
        except OSError:
            pass

    def __enter__(self) -> "WebSocketClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# HTTP（读 /json/*）
# ---------------------------------------------------------------------------
def _http_json(url: str, *, method: str = "GET", timeout: float = 5.0) -> Any:
    request = Request(url, method=method, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, OSError) as exc:
        raise CdpClientError(f"无法访问 {url}：{exc}") from exc
    if not body.strip():
        return None
    try:
        return json.loads(body)
    except ValueError as exc:
        raise CdpClientError(f"{url} 返回的不是 JSON：{exc}") from exc


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------
@dataclass
class CdpTarget:
    target_id: str
    url: str
    title: str = ""
    kind: str = "page"
    web_socket_url: str = ""


class CdpBrowser:
    """一个调试端口上的浏览器。``port=9334`` 是本子项目的研究实例。"""

    def __init__(self, port: int = 9334, *, host: str = "127.0.0.1", timeout: float = 20.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._browser_ws: Optional[WebSocketClient] = None

    # -- HTTP 探测 ----------------------------------------------------------
    @property
    def base(self) -> str:
        return f"http://{self.host}:{self.port}"

    def version(self) -> Dict[str, Any]:
        payload = _http_json(f"{self.base}/json/version", timeout=self.timeout)
        return payload if isinstance(payload, dict) else {}

    def list_targets(self) -> List[CdpTarget]:
        payload = _http_json(f"{self.base}/json/list", timeout=self.timeout)
        if not isinstance(payload, list):
            return []
        targets: List[CdpTarget] = []
        for item in payload:
            if not isinstance(item, Mapping):
                continue
            targets.append(
                CdpTarget(
                    target_id=str(item.get("id") or ""),
                    url=str(item.get("url") or ""),
                    title=str(item.get("title") or ""),
                    kind=str(item.get("type") or ""),
                    web_socket_url=str(item.get("webSocketDebuggerUrl") or ""),
                )
            )
        return targets

    def taobao_pages(self) -> List[CdpTarget]:
        return [
            item for item in self.list_targets()
            if item.kind == "page" and ("taobao.com" in item.url or "tmall.com" in item.url)
        ]

    def new_page(self, url: str = "about:blank") -> CdpTarget:
        payload = _http_json(f"{self.base}/json/new?{quote(url, safe='')}", method="PUT", timeout=self.timeout)
        if not isinstance(payload, Mapping) or not payload.get("id"):
            raise CdpClientError("无法创建新标签页")
        return CdpTarget(
            target_id=str(payload.get("id")),
            url=str(payload.get("url") or ""),
            title=str(payload.get("title") or ""),
            kind=str(payload.get("type") or "page"),
            web_socket_url=str(payload.get("webSocketDebuggerUrl") or ""),
        )

    def close_target(self, target_id: str) -> None:
        try:
            _http_json(f"{self.base}/json/close/{target_id}", timeout=self.timeout)
        except CdpClientError:
            pass

    # -- 浏览器级 WebSocket --------------------------------------------------
    def _browser_socket(self) -> WebSocketClient:
        if self._browser_ws is None:
            info = self.version()
            url = str(info.get("webSocketDebuggerUrl") or "")
            if not url:
                raise CdpClientError("调试端口没有返回浏览器级 WebSocket 地址")
            self._browser_ws = WebSocketClient(url, timeout=self.timeout)
        return self._browser_ws

    def call(self, method: str, params: Optional[Mapping[str, Any]] = None, *,
             session_id: str = "") -> Dict[str, Any]:
        """在浏览器级连接上发一条命令并等它的结果。

        .. warning::
            等待期间收到的事件会**被丢掉**。要同时收事件（例如 ``Network.*``），
            用 :meth:`send` + :meth:`drain_events`。
        """

        socket_client = self._browser_socket()
        message_id = socket_client._next_id
        socket_client._next_id += 1
        payload: Dict[str, Any] = {"id": message_id, "method": method, "params": dict(params or {})}
        if session_id:
            payload["sessionId"] = session_id
        socket_client.send_json(payload)
        deadline = time.monotonic() + self.timeout
        while True:
            if time.monotonic() > deadline:
                raise CdpClientError(f"{method} 超时")
            message = socket_client.recv_json()
            if message.get("id") != message_id:
                continue  # 事件或别的响应，跳过
            if "error" in message:
                raise CdpClientError(f"{method} 失败：{message['error'].get('message')}")
            return message.get("result") or {}

    # -- 事件（被动观察用） --------------------------------------------------
    def send(self, method: str, params: Optional[Mapping[str, Any]] = None, *,
             session_id: str = "") -> int:
        """发一条命令，**不等结果**。返回消息 id（事件仍留在队列里）。"""

        socket_client = self._browser_socket()
        message_id = socket_client._next_id
        socket_client._next_id += 1
        payload: Dict[str, Any] = {"id": message_id, "method": method, "params": dict(params or {})}
        if session_id:
            payload["sessionId"] = session_id
        socket_client.send_json(payload)
        return message_id

    def drain_events(self, *, deadline: float = 0.0, event_names: Tuple[str, ...] = ()) -> List[Dict[str, Any]]:
        """把队列里已有的**事件**取空（非阻塞）。

        :param deadline: 最多等到这个时刻（``time.monotonic()`` 口径）；``0`` 表示立即返回。
        :param event_names: 只保留这些事件名；空元组表示全要。
        :return: 事件消息列表（每条是原始 CDP 消息，含 ``method`` 与 ``params``）。
        """

        socket_client = self._browser_socket()
        events: List[Dict[str, Any]] = []
        while True:
            remaining = deadline - time.monotonic()
            try:
                socket_client._socket.settimeout(max(0.05, min(0.5, remaining)) if remaining > 0 else 0.05)
                message = socket_client.recv_json()
            except (socket.timeout, OSError):
                if remaining <= 0:
                    break
                continue
            except CdpClientError:
                break
            if "id" in message or "method" not in message:
                continue
            method = str(message.get("method") or "")
            if event_names and method not in event_names:
                continue
            events.append(message)
            if remaining <= 0 and not event_names:
                # 非阻塞模式下把当前已到的事件收完就走
                continue
        return events

    def attach(self, target_id: str) -> str:
        """给一个标签页建会话，返回 ``sessionId``。"""

        result = self.call("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        session_id = str(result.get("sessionId") or "")
        if not session_id:
            raise CdpClientError("附加到标签页失败：没有 sessionId")
        return session_id

    def create_frame_context(self, frame_id: str, *, timeout: float = 10.0) -> int:
        """给一个 frame 建**隔离世界**，返回其执行上下文 id。

        素材中心是 iframe 里的微应用：要在它的上下文里读/写，就得先拿到该 frame 的
        执行上下文。``flatten`` 会话下 ``Page.createIsolatedWorld`` 可以直接对
        frameId 调用，不需要单独 attach 到子目标。

        上下文 id 可以当 ``session_id`` 直接传给 :meth:`evaluate`——
        CDP 的 ``Runtime.evaluate`` 既接受 sessionId 也接受
        ``contextId``，这里传的是后者。
        """

        result = self.call(
            "Page.createIsolatedWorld",
            {"frameId": frame_id, "grantUniveralAccess": True, "worldName": "taobao-publish-probe"},
            timeout=timeout,
        )
        context_id = result.get("executionContextId")
        if not isinstance(context_id, int):
            raise CdpClientError("建隔离世界失败：没有 executionContextId")
        return context_id

    def evaluate(self, expression: str, *, session_id: str, await_promise: bool = True,
                 timeout: float = 30.0, execution_context_id: int = 0) -> Any:
        """在页面里跑一段表达式；默认等 Promise 兑现。

        :param execution_context_id: 指定执行上下文（iframe 内求值用）。
            不传就在主 frame 跑。**iframe 里的元素在主 frame 找不到**，
            所以需要点选图器 iframe 内的东西时必须指定。
        """

        params: Dict[str, Any] = {
            "expression": expression,
            "awaitPromise": await_promise,
            "returnByValue": True,
            "userGesture": False,
        }
        if execution_context_id:
            params["contextId"] = execution_context_id
        result = self.call("Runtime.evaluate", params, session_id=session_id)
        if result.get("exceptionDetails"):
            detail = result["exceptionDetails"]
            text = (detail.get("exception") or {}).get("description") or detail.get("text") or "未知异常"
            raise CdpClientError(f"页面内表达式抛错：{str(text)[:300]}")
        return (result.get("result") or {}).get("value")

    # -- cookie -------------------------------------------------------------
    def cookies(self, *, domains: Tuple[str, ...] = ("taobao.com", "tmall.com")) -> List[Dict[str, Any]]:
        """取浏览器全部 cookie（含 httpOnly）。**返回值含凭据，不要落盘。**"""

        try:
            result = self.call("Storage.getCookies", {})
            raw = result.get("cookies")
        except CdpClientError:
            result = self.call("Network.getAllCookies", {})
            raw = result.get("cookies")
        items = raw if isinstance(raw, list) else []
        wanted: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            domain = str(item.get("domain") or "").lstrip(".").lower()
            if any(domain == suffix or domain.endswith("." + suffix) for suffix in domains):
                wanted.append(dict(item))
        return wanted

    def close(self) -> None:
        if self._browser_ws is not None:
            self._browser_ws.close()
            self._browser_ws = None


def cookie_header(cookies: List[Mapping[str, Any]]) -> str:
    """拼成 ``Cookie`` 头。**返回值含登录态，只应留在内存里。**"""

    parts: List[str] = []
    seen = set()
    for item in cookies:
        name = str(item.get("name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        parts.append(f"{name}={item.get('value')}")
    return "; ".join(parts)


def cookie_value(cookies: List[Mapping[str, Any]], name: str) -> str:
    for item in cookies:
        if str(item.get("name") or "") == name:
            return str(item.get("value") or "")
    return ""


def describe_cookies(cookies: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """只回名字与数量，**不回值**。

    ``has_login_identity`` 只看 ``unb``（淘宝的会员数字 ID）。
    **不要**用 ``cookie2`` 判断登录：实测未登录时也会被种上 ``cookie2``
    与 ``_tb_token_``（页面访问就种），拿它们当登录证据会把「没登录」
    误判成「已登录」，然后用 token 空值去撞平台。
    """

    names = sorted({str(item.get("name") or "") for item in cookies if item.get("name")})
    return {
        "count": len(cookies),
        "names": names,
        "has_login_identity": "unb" in names,
        "has_tb_token": "_tb_token_" in names,
        "has_cookie2": "cookie2" in names,
    }

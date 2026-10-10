# -*- coding: utf-8 -*-
"""被动读取平台自己的 ``dir.query`` / ``file.query`` 响应。

## 为什么要它（真机 2026-10-10，两次代价）

素材中心的目录树与文件列表都是**异步渲染 + 虚拟列表**，DOM 读取会骗人：

* 「云端有没有这个商品目录」靠 DOM 树判断 → 节点没渲染出来就当**没有** →
  走「整目录导入」→ **每次运行都新建一个同名商品目录并重传全部 33 张**
  （实测目录 id 三次变化：``…856811516850`` → ``…859910507…`` → ``…858131335134``）。
* 「这一层有哪些文件」靠 DOM 读 → 页面一刷新/抖动就读不到 →
  「图片空间缺少原目录图片：SKU/01_奶白 _ 均码.jpg」（用户 2026-10-10 那次）。

平台自己在**进目录时**就会发 ``file.query``，响应里的 ``fileModule`` 是权威文件清单
（``name`` / ``fullUrl`` / ``pictureId`` / ``md5``）；``dir.query`` 的 ``data.dirs``
是权威目录树（含 ``id`` / ``pid`` / ``childrenSize``）。**这些请求本来就会发生**
——我们只是把它们收下来，不额外导航、更不刷新页面。

⚠️ 只读：本模块不做任何写操作，也不主动发请求（除了 ``Network.enable`` 让浏览器把
响应体留给我们）。看清了「读不到」与「不存在」的区别，是这个模块存在的唯一理由。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlsplit

from .cdp_ws import CdpBrowser

#: 素材中心页面的 URL 特征（发布流程里它就是「图片空间」那一页）。
PAGE_URL_MARKER = "sucai-tu"

#: 一个响应最多留多少条文件，避免超大目录把内存吃满（分页由平台的 ``page`` 字段控制，
#: 这里只读当前页；超出部分由调用方按 ``complete`` 判断，不猜）。
FILE_LIMIT = 200


def _parse_jsonp(text: str) -> Optional[dict]:
    """平台返回的是 JSONP（``callback({...})``）；纯 JSON 也接受。"""

    body = text.strip()
    if body.startswith("{"):
        try:
            return json.loads(body)
        except ValueError:
            return None
    start = body.find("(")
    end = body.rfind(")")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(body[start + 1:end])
    except ValueError:
        return None


class CloudListing:
    """一次会话内收下来的 ``dir.query`` / ``file.query`` 响应。"""

    def __init__(self, browser: CdpBrowser, session_id: int):
        self._browser = browser
        self._session = session_id
        self._pending: Dict[str, tuple] = {}
        self._directories: List[Dict[str, Any]] = []
        self._files: Dict[str, List[Dict[str, Any]]] = {}
        self._pages: Dict[str, Dict[str, Any]] = {}
        self._seen_dir = 0
        self._seen_file = 0

    # ------------------------------------------------------------------ 建立

    @classmethod
    def attach(cls, port: int, *, timeout: float = 20.0,
               url_marker: str = PAGE_URL_MARKER) -> "CloudListing":
        """连到素材中心那个标签页，打开 Network 域。**不改动页面。**"""

        browser = CdpBrowser(port=int(port), timeout=timeout)
        deadline = time.monotonic() + timeout
        while True:
            targets = [t for t in browser.list_targets()
                       if t.kind == "page" and url_marker in (t.url or "")]
            if targets:
                break
            if time.monotonic() >= deadline:
                browser.close()
                raise CloudListingUnavailable('没有找到素材中心页面（{}）'.format(url_marker))
            time.sleep(0.3)
        session = browser.attach(targets[0].target_id)
        browser.call("Network.enable", {"maxTotalBufferSize": 80_000_000,
                                        "maxResourceBufferSize": 20_000_000},
                     session_id=session)
        return cls(browser, session)

    def close(self) -> None:
        try:
            self._browser.call("Network.disable", session_id=self._session)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._browser.close()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 取树

    def reload_and_observe(self, *, wait: float = 8.0, observe: float = 5.0) -> bool:
        """刷新这个标签页，让平台重新发一次 ``dir.query``。

        ⚠️ **只在流程开始时用**（`import_directory` 刚进来、页面还没被动过）：
        平台只在**页面加载**时发目录清单，不刷新就永远拿不到权威目录树——
        而拿不到就只能靠 DOM 虚拟列表判断「云端有没有这个商品目录」，
        那正是「每次运行都新建同名目录 + 全量重传」的成因（真机 2026-10-10）。
        """

        targets = [t for t in self._browser.list_targets()
                   if t.kind == "page" and PAGE_URL_MARKER in (t.url or "")]
        if not targets:
            return False
        self._browser.send("Page.reload", {"ignoreCache": False}, session_id=self._session)
        time.sleep(max(0.0, wait))
        self.observe(observe)
        return self._seen_dir > 0

    # ------------------------------------------------------------------ 收集

    def observe(self, seconds: float = 4.0) -> None:
        """把这段时间内页面自己发出的请求/响应收下来（不点、不导航）。

        ``seconds=0`` 也会**至少收一趟**——离线测试与「刚点完马上读」都靠这一点。
        """

        end = time.monotonic() + max(0.0, seconds)
        while True:
            for event in self._browser.drain_events(
                    deadline=min(end, time.monotonic() + 1.2),
                    event_names=("Network.responseReceived", "Network.requestWillBeSent")):
                self._consume(event)
            if time.monotonic() >= end:
                return

    def _consume(self, event: dict) -> None:
        params = event.get("params") or {}
        if event.get("method") == "Network.requestWillBeSent":
            url = str((params.get("request") or {}).get("url") or "")
            kind = ("dir.query" if "dir.query" in url else
                    "file.query" if "file.query" in url else None)
            if kind is None:
                return
            match = re.search(r"[?&]data=([^&]+)", url)
            self._pending[str(params.get("requestId") or "")] = (
                kind, json.loads(unquote(match.group(1))) if match else {})
            return
        request_id = str(params.get("requestId") or "")
        if request_id not in self._pending:
            return
        kind, request = self._pending.pop(request_id)
        try:
            body = self._browser.call("Network.getResponseBody", {"requestId": request_id},
                                      session_id=self._session)
        except Exception:  # noqa: BLE001
            return
        parsed = _parse_jsonp(str(body.get("body") or ""))
        if not isinstance(parsed, dict):
            return
        data = parsed.get("data") or {}
        if kind == "dir.query":
            self._seen_dir += 1
            root = data.get("dirs") or {}
            self._directories = []
            self._flatten(root.get("children") if isinstance(root, dict) else root, 0)
        else:
            self._seen_file += 1
            cat_id = str(request.get("catId") or "")
            if not cat_id:
                return
            files = (data.get("fileModule") or [])[:FILE_LIMIT]
            self._files[cat_id] = [{
                "name": str(item.get("name") or ""),
                "url": str(item.get("fullUrl") or ""),
                "picture_id": str(item.get("pictureId") or ""),
                "md5": str(item.get("md5") or ""),
                "folder_id": str(item.get("pictureCategoryId") or cat_id),
            } for item in files]
            self._pages[cat_id] = {"page": data.get("page"), "total": data.get("total"),
                                  "count": len(data.get("fileModule") or [])}

    def _flatten(self, nodes, depth: int) -> None:
        for node in nodes or []:
            self._directories.append({
                "name": str(node.get("name") or ""),
                "id": str(node.get("id") or ""),
                "pid": str(node.get("pid") or ""),
                "children_size": node.get("childrenSize"),
                "depth": depth,
            })
            self._flatten(node.get("children"), depth + 1)

    # ------------------------------------------------------------------ 读取

    @property
    def dir_responses(self) -> int:
        return self._seen_dir

    @property
    def file_responses(self) -> int:
        return self._seen_file

    def directories(self) -> List[Dict[str, Any]]:
        """权威目录树（顶层在前，``depth`` 表示层级）。"""

        return list(self._directories)

    def directory_paths(self) -> Dict[str, List[Dict[str, Any]]]:
        """``{名字: [节点...]}``：按名字索引，方便判重名。"""

        index: Dict[str, List[Dict[str, Any]]] = {}
        for node in self._directories:
            index.setdefault(node["name"], []).append(node)
        return index

    def find_directories(self, name: str) -> List[Dict[str, Any]]:
        return [node for node in self._directories if node["name"] == name]

    def find_child(self, parent_id: str, name: str) -> Optional[Dict[str, Any]]:
        """按 ``pid`` + 名字找子目录——**不靠层级猜测**，同名子目录在不同商品下也不会串。"""

        for node in self._directories:
            if node["pid"] == str(parent_id) and node["name"] == name:
                return node
        return None

    def files(self, cat_id: str) -> Optional[List[Dict[str, Any]]]:
        """某个目录的文件清单；**没见过这个目录的响应就返回 ``None``**（≠ 空目录）。

        这个区分是整个模块的重点：``None`` 是「读不出来」，``[]`` 是「目录确实是空的」。
        """

        return self._files.get(str(cat_id))

    def page_info(self, cat_id: str) -> Dict[str, Any]:
        return self._pages.get(str(cat_id), {})


class CloudListingUnavailable(RuntimeError):
    """连不上素材中心页，或平台压根没发我们需要的请求。

    ⚠️ 出现它时**不能**把「读不到」当成「不存在」——必须如实上报。
    """

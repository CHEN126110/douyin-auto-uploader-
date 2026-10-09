# -*- coding: utf-8 -*-
"""在**素材中心**页面里找出「目录树到底走哪个 api」（只读、只观察）。

## 背景

`docs/31` 从 bundle 原文给出 `mtop.taobao.picturecenter.console.dir.query`，
但自己拼这个 api 实测被网关判 ``FAIL_SYS_ILLEGAL_ACCESS``；而在真实
``qn.taobao.com`` 素材中心页面上，目录树（`ID-xxxx`、`全部素材`…）**确实渲染出来了**。
所以要么调用形态还有差别，要么目录树走的是另一个 api。

这个脚本不再猜：**加载页面 → 被动收所有 mtop 请求与响应 → 在响应体里搜目录名**，
命中的那个就是答案，同时把它的 api 名、参数名、请求头携带情况、响应字段名一起记下来。

**只读**：不点击、不提交、不上传；产物只留形态与字段名，不留参数值/响应原文全文。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(_REPO_ROOT / "taobao-publisher"), str(_REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from taobao_publish.cdp_ws import CdpBrowser, CdpClientError  # noqa: E402

DEFAULT_URL = "https://qn.taobao.com/home.htm/material-center/mine-material/sucai-tu"
EVENTS: Tuple[str, ...] = (
    "Network.requestWillBeSent",
    "Network.requestWillBeSentExtraInfo",
    "Network.responseReceived",
)

#: 目录名里一定出现的标记。命中它说明这个响应体带目录树/文件列表。
DIRECTORY_MARKERS: Tuple[str, ...] = ("ID-", "全部素材", "pictureCategoryId", "dirName", "fileModule")

#: 响应里可能出现的字段名（用来对照我们解析器的键名假设）。
FIELD_HINTS: Tuple[str, ...] = (
    "pictureCategoryId", "dirId", "catId", "children", "subDirs", "name", "dirName",
    "fileModule", "pictureId", "fullUrl", "pixel", "status", "parentId", "total",
)


def _shape(url: str, method: str) -> Optional[Dict[str, Any]]:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    api = (query.get("api") or [""])[0]
    if not api:
        return None
    data_keys: List[str] = []
    raw_data = (query.get("data") or [""])[0]
    if raw_data:
        try:
            payload = json.loads(raw_data)
            if isinstance(payload, dict):
                data_keys = sorted(str(key) for key in payload.keys())
        except (ValueError, TypeError):
            data_keys = ["<data 不是 JSON>"]
    return {
        "api": api,
        "method": method.upper(),
        "version": (query.get("v") or [""])[0],
        "appKey": (query.get("appKey") or [""])[0],
        "jsv": (query.get("jsv") or [""])[0],
        "type": (query.get("type") or [""])[0],
        "query_keys": sorted(query.keys()),
        "data_keys": data_keys,
        "has_sign": "sign" in query,
        "has_callback": "callback" in query,
        "has_ttid": "ttid" in query,
    }


def _fields_in(text: str) -> List[str]:
    return [hint for hint in FIELD_HINTS if f'"{hint}"' in text]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="找出素材中心目录树走的 api（只读）")
    parser.add_argument("--port", type=int, default=9334)
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out", default="")
    parser.add_argument("--reload", action="store_true", default=True)
    arguments = parser.parse_args(argv)

    browser = CdpBrowser(port=arguments.port, timeout=30.0)
    try:
        version = browser.version()
    except CdpClientError as exc:
        sys.stderr.write(f"调试端口不可达：{exc}\n")
        return 1
    sys.stdout.write(f"浏览器：{version.get('Browser')}\n")

    target = browser.new_page("about:blank")
    session_id = browser.attach(target.target_id)
    browser.call(
        "Network.enable",
        {"maxTotalBufferSize": 40_000_000, "maxResourceBufferSize": 8_000_000},
        session_id=session_id,
    )
    browser.send("Page.navigate", {"url": arguments.url}, session_id=session_id)

    requests: Dict[str, Dict[str, Any]] = {}
    responded: Dict[str, Dict[str, Any]] = {}
    deadline = time.monotonic() + max(10.0, arguments.seconds)
    reloaded = False
    while time.monotonic() < deadline:
        if not reloaded and time.monotonic() > deadline - max(12.0, arguments.seconds * 0.5):
            browser.send("Page.reload", {"ignoreCache": False}, session_id=session_id)
            reloaded = True
        for event in browser.drain_events(deadline=min(deadline, time.monotonic() + 1.5), event_names=EVENTS):
            method = event.get("method") or ""
            params = event.get("params") or {}
            if method == "Network.requestWillBeSent":
                request = params.get("request") or {}
                shape = _shape(str(request.get("url") or ""), str(request.get("method") or "GET"))
                if shape is None:
                    continue
                headers = {str(key).lower(): True for key in (request.get("headers") or {})}
                shape["headers_present"] = sorted(
                    key for key in headers if key in ("referer", "origin", "cookie", "x-requested-with", "ttid")
                )
                requests[str(params.get("requestId") or "")] = shape
            elif method == "Network.requestWillBeSentExtraInfo":
                # 真实发出的 header 在这里（``requestWillBeSent`` 给的是未加 cookie 的那份）。
                # **只记名字与形态，不记值**：cookie/token 一律不落。
                request_id = str(params.get("requestId") or "")
                record = requests.get(request_id)
                if record is None:
                    continue
                headers = {str(key).lower(): value for key, value in (params.get("headers") or {}).items()}
                record["real_header_names"] = sorted(headers)
                record["has_cookie_header"] = "cookie" in headers
                if "ttid" in headers:
                    value = str(headers["ttid"])
                    # 只保留形态：把数字与版本号替换掉，避免把客户端标识落盘
                    record["ttid_shape"] = re.sub(r"\d+", "N", value)[:60]
                    record["ttid_length"] = len(value)
                if "referer" in headers:
                    record["referer_host"] = urlsplit(str(headers["referer"])).hostname or ""
                if "origin" in headers:
                    record["origin_host"] = urlsplit(str(headers["origin"])).hostname or ""
                record["accept_language_present"] = "accept-language" in headers
            elif method == "Network.responseReceived":
                request_id = str(params.get("requestId") or "")
                if request_id not in requests:
                    continue
                record = dict(requests[request_id])
                response = params.get("response") or {}
                record["http_status"] = response.get("status")
                responded[request_id] = record

    # 在响应体里搜目录/文件字段，找出真正带数据的那次调用
    hits: List[Dict[str, Any]] = []
    for request_id, record in responded.items():
        try:
            body = browser.call(
                "Network.getResponseBody", {"requestId": request_id}, session_id=session_id
            )
        except CdpClientError:
            continue
        if body.get("base64Encoded"):
            continue
        text = str(body.get("body") or "")
        matched = [marker for marker in DIRECTORY_MARKERS if marker in text]
        if not matched:
            continue
        record = dict(record)
        record["matched_markers"] = matched
        record["fields_seen"] = _fields_in(text)
        record["body_length"] = len(text)
        record["ret_head"] = text[:120]
        hits.append(record)

    browser.close_target(target.target_id)
    browser.close()

    payload = {
        "url": arguments.url,
        "mtop_call_count": len(responded),
        "directory_data_calls": hits,
        "all_apis": sorted({record.get("api", "") for record in responded.values()}),
        "note": "只记录形态、字段名与响应片段头部；不含 cookie/签名/完整 URL",
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    sys.stdout.write(text + "\n")
    out = arguments.out or str(
        _REPO_ROOT / "taobao-publisher" / "tmp"
        / f"material-center-directory-api-{time.strftime('%Y%m%d%H%M%S')}.json"
    )
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(text, encoding="utf-8")
    sys.stdout.write(f"[已写入产物] {out}\n")
    return 0 if hits else 2


if __name__ == "__main__":
    raise SystemExit(main())

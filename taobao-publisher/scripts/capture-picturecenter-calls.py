# -*- coding: utf-8 -*-
"""图片空间 `picturecenter.*` 调用的**真实形态抓取**（只读，只观察浏览器自己发的请求）。

## 它解决什么问题

自己拼的 `mtop.taobao.picturecenter.console.dir.query` 请求被网关判
``FAIL_SYS_ILLEGAL_ACCESS::非法请求``（实测），而同一套签名去打别的 api 是通的。
继续改参数就是瞎猜。真实页面**自己**一定发得出去这个调用——把它抓下来对照，
差别在哪里一眼就能看出来。

## 它做什么

1. 打开图片空间页面（默认 `qn.taobao.com` 素材中心）；
2. 用 CDP ``Network.enable`` **被动**收请求与响应（不注入、不改写、不阻断）；
3. 对命中 ``picturecenter`` 的调用，取 **完整 URL 的参数名列表**、方法、
   请求头里的 `Referer`/`Origin` 是否携带，以及**响应体**（用于判断调用成功与否）；
4. 产物只写**形态 + 小段响应片段**到 `tmp/`（不进仓库）。

**仍然不记录**：cookie 值、`sign`、`_m_h5_tk`、`ttid` 的值、完整 URL 原文。
"""

from __future__ import annotations

import argparse
import json
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

EVENTS: Tuple[str, ...] = ("Network.requestWillBeSent", "Network.responseReceived", "Network.loadingFinished")


def _shape(url: str, method: str, *, only_picturecenter: bool) -> Optional[Dict[str, Any]]:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    api = (query.get("api") or [""])[0]
    # ⚠️ 判据必须包含 `api` query 参数：mtop 的 URL 路径是 `/h5/<api>/<v>/`，
    # **路径里没有 "mtop" 字样**，只看 path 会把所有真实调用都过滤掉（踩过）。
    if not api and "mtop" not in parsed.path and "picturecenter" not in parsed.path:
        return None
    if only_picturecenter and "picturecenter" not in (api + parsed.path):
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
        "host": parsed.hostname or "",
        "path": parsed.path,
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="抓取图片空间 picturecenter 调用的真实形态（只读）")
    parser.add_argument("--port", type=int, default=9334)
    parser.add_argument("--seconds", type=float, default=35.0)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out", default="")
    parser.add_argument(
        "--all-mtop", action="store_true",
        help="不限 picturecenter：抓全部 mtop 调用（素材中心的目录树可能走别的 api）",
    )
    arguments = parser.parse_args(argv)

    browser = CdpBrowser(port=arguments.port, timeout=30.0)
    try:
        version = browser.version()
    except CdpClientError as exc:
        sys.stderr.write(f"调试端口不可达：{exc}\n")
        return 1
    sys.stdout.write(f"浏览器：{version.get('Browser')}\n")

    target = browser.new_page(arguments.url)
    session_id = browser.attach(target.target_id)
    browser.call("Network.enable", {"maxTotalBufferSize": 20_000_000, "maxResourceBufferSize": 5_000_000},
                 session_id=session_id)
    time.sleep(8)

    # 页面自报状态：确认到底加载到哪一步（不点任何东西）
    try:
        facts = browser.evaluate(
            "(() => ({ href: location.href, title: document.title,"
            " text: (document.body ? document.body.innerText : '').slice(0, 400),"
            " iframes: Array.from(document.querySelectorAll('iframe')).map(f => f.src).slice(0, 6) }))()",
            session_id=session_id, await_promise=False, timeout=15.0,
        )
    except CdpClientError as exc:
        facts = {"error": str(exc)}
    sys.stdout.write("页面事实：" + json.dumps(facts, ensure_ascii=False)[:700] + "\n")

    if isinstance(facts, dict) and facts.get("iframes"):
        sys.stdout.write("页面里还有 iframe，逐个附加后再等一轮…\n")
        for frame_url in facts["iframes"]:
            if not isinstance(frame_url, str) or "taobao" not in frame_url:
                continue
            try:
                sub = browser.new_page(frame_url)
                sub_session = browser.attach(sub.target_id)
                browser.call("Network.enable", {}, session_id=sub_session)
            except CdpClientError:
                continue

    responded: Dict[str, Dict[str, Any]] = {}
    request_ids: Dict[str, Dict[str, Any]] = {}
    deadline = time.monotonic() + max(8.0, arguments.seconds)
    while time.monotonic() < deadline:
        for event in browser.drain_events(deadline=min(deadline, time.monotonic() + 1.5), event_names=EVENTS):
            method = event.get("method") or ""
            params = event.get("params") or {}
            if method == "Network.requestWillBeSent":
                request = params.get("request") or {}
                shape = _shape(str(request.get("url") or ""), str(request.get("method") or "GET"), only_picturecenter=not arguments.all_mtop)
                if shape is None:
                    continue
                shape["request_headers_present"] = sorted(
                    key for key in (request.get("headers") or {})
                    if key.lower() in ("referer", "origin", "cookie", "x-requested-with")
                )
                shape["has_post_data"] = bool(request.get("postData"))
                request_ids[str(params.get("requestId") or "")] = shape
            elif method == "Network.responseReceived":
                request_id = str(params.get("requestId") or "")
                if request_id not in request_ids:
                    continue
                response = params.get("response") or {}
                record = dict(request_ids[request_id])
                record["http_status"] = response.get("status")
                record["mime"] = response.get("mimeType")
                record["request_id"] = request_id
                responded[request_id] = record

    # 取命中调用的响应片段（用于判断调用是否成功）
    for request_id, record in list(responded.items())[:40]:
        try:
            body = browser.call("Network.getResponseBody", {"requestId": request_id}, session_id=session_id)
            text = str(body.get("body") or "")
            if body.get("base64Encoded"):
                text = "<base64>"
            record["response_head"] = text[:400]
        except CdpClientError as exc:
            record["response_head"] = f"<取不到：{exc}>"

    browser.close_target(target.target_id)
    browser.close()

    payload = {
        "url": arguments.url,
        "page_facts": facts,
        "picturecenter_calls": [item for item in responded.values() if "picturecenter" in (item.get("api") or "")],
        "all_mtop_calls": list(responded.values()),
        "note": "只记录形态与响应片段；不含 cookie/签名/ttid 值/完整 URL",
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    sys.stdout.write(text + "\n")
    out = arguments.out or str(
        _REPO_ROOT / "taobao-publisher" / "tmp"
        / f"picturecenter-live-calls-{time.strftime('%Y%m%d%H%M%S')}.json"
    )
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(text, encoding="utf-8")
    sys.stdout.write(f"[已写入产物] {out}\n")
    return 0 if responded else 2


if __name__ == "__main__":
    raise SystemExit(main())

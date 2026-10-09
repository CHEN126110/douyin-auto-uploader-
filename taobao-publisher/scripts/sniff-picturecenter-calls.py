# -*- coding: utf-8 -*-
"""图片空间 api 调用形态的**被动嗅探**（只观察，不写、不点、不发业务请求）。

## 为什么需要它

`docs/31` 给出了图片空间用了哪些 api（bundle 原文，`verified`），但
**怎么调**没取证：version、网关、appKey、GET 还是 POST、`data` 放 query 还是 body。
自己拼一次会得到 ``FAIL_SYS_ILLEGAL_ACCESS``（本机实测），继续瞎猜就是浪费轮次。

这个脚本让**真实页面自己去发**这些请求，我们在浏览器进程侧用 CDP 的
``Network.requestWillBeSent`` 被动接收——不改写、不阻断、不伪造，也**不注入**页面。

**只记录形态**：api 名、version、appKey、方法、``data`` 在 query 还是 body、
参数名列表（不含值）、参数个数。
**绝不记录**：任何查询/表单的**值**、cookie、token、签名、完整 URL、响应内容。

## 用法

```powershell
python taobao-publisher/scripts/sniff-picturecenter-calls.py --seconds 30
python taobao-publisher/scripts/sniff-picturecenter-calls.py `
  --url "https://qn.taobao.com/home.htm/material-center/mine-material/sucai-tu"
```

产物写 ``taobao-publisher/tmp/picturecenter-call-shapes-<时间>.json``（tmp 不进仓库）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(_REPO_ROOT / "taobao-publisher"), str(_REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from taobao_publish.cdp_ws import CdpBrowser, CdpClientError  # noqa: E402

#: 图片空间入口候选（第一个来自 bundle 里的前端常量）。
DEFAULT_URLS = (
    "https://qn.taobao.com/home.htm/material-center/mine-material/sucai-tu",
    "https://item.upload.taobao.com/sell/ai/category.htm",
)

#: 只关心这些事件。
WANTED_EVENTS: Tuple[str, ...] = ("Network.requestWillBeSent",)


def _describe_shape(url: str, method: str, post_keys: List[str]) -> Optional[Dict[str, Any]]:
    """把一个请求压成**不含值**的形态描述。"""

    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    api = (query.get("api") or [""])[0]
    if not api and "mtop" not in parsed.path:
        # 顺带记录 upload.api 这类非 mtop 的上传请求（只记 path 与参数名）
        if "upload.api" not in parsed.path:
            return None
        return {
            "api": "",
            "kind": "upload_api",
            "host": parsed.hostname or "",
            "path": parsed.path,
            "method": method.upper(),
            "query_keys": sorted(query.keys()),
            "data_in_query": False,
            "data_keys": [],
            "body_keys": sorted(post_keys),
        }
    data_keys: List[str] = []
    raw_data = (query.get("data") or [""])[0]
    if raw_data:
        try:
            parsed_data = json.loads(raw_data)
            if isinstance(parsed_data, dict):
                data_keys = sorted(str(key) for key in parsed_data.keys())
        except (ValueError, TypeError):
            data_keys = ["<data 不是 JSON 对象>"]
    return {
        "api": api,
        "kind": "mtop",
        "host": parsed.hostname or "",
        "path": parsed.path,
        "method": method.upper(),
        "jsv": (query.get("jsv") or [""])[0],
        "appKey": (query.get("appKey") or [""])[0],
        "version": (query.get("v") or [""])[0],
        "type": (query.get("type") or [""])[0],
        "query_keys": sorted(query.keys()),
        "data_in_query": "data" in query,
        "data_keys": data_keys,
        "body_keys": sorted(post_keys),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="被动嗅探图片空间 mtop 调用形态（只记录形态）")
    parser.add_argument("--port", type=int, default=9334)
    parser.add_argument("--seconds", type=float, default=30.0, help="嗅探时长")
    parser.add_argument("--url", default="", help="要打开的页面（默认图片空间入口）")
    parser.add_argument("--no-reload", action="store_true", help="不要重新加载页面")
    parser.add_argument("--out", default="")
    arguments = parser.parse_args(argv)

    browser = CdpBrowser(port=arguments.port, timeout=30.0)
    try:
        version = browser.version()
    except CdpClientError as exc:
        sys.stderr.write(f"调试端口不可达：{exc}\n")
        return 1
    sys.stdout.write(f"浏览器：{version.get('Browser')}  端口 {arguments.port}\n")

    url = arguments.url or DEFAULT_URLS[0]
    target = browser.new_page(url)
    session_id = browser.attach(target.target_id)
    # 监听要在导航之前打开，否则第一次加载的请求收不到
    browser.call("Network.enable", {"maxTotalBufferSize": 10_000_000}, session_id=session_id)
    time.sleep(6)
    sys.stdout.write(f"已打开：{url}\n")

    if not arguments.no_reload:
        sys.stdout.write("重新加载页面以引出请求（只加载，不点击、不提交）…\n")
        browser.send("Page.reload", {"ignoreCache": False}, session_id=session_id)

    shapes: Dict[Tuple[str, ...], Dict[str, Any]] = {}
    counter: Counter = Counter()
    deadline = time.monotonic() + max(5.0, arguments.seconds)
    while time.monotonic() < deadline:
        for event in browser.drain_events(deadline=min(deadline, time.monotonic() + 1.0),
                                          event_names=WANTED_EVENTS):
            request = (event.get("params") or {}).get("request") or {}
            shape = _describe_shape(
                str(request.get("url") or ""),
                str(request.get("method") or "GET"),
                list((request.get("postData") or "").split("&")) if request.get("postData") else [],
            )
            if shape is None:
                continue
            # postData 是表单原文，这里只取字段名，值一律丢弃
            if shape["body_keys"]:
                shape["body_keys"] = sorted(
                    {chunk.split("=", 1)[0] for chunk in shape["body_keys"] if chunk}
                )
            key = (
                shape.get("kind", ""), shape.get("api", ""), shape.get("version", ""),
                shape.get("method", ""), str(shape.get("data_in_query", "")),
            )
            counter[key] += 1
            shapes.setdefault(key, shape)

    browser.close_target(target.target_id)
    browser.close()

    payload = {
        "url": url,
        "call_count": sum(counter.values()),
        "shapes": [
            dict(shape, occurrences=counter[key])
            for key, shape in sorted(shapes.items(), key=lambda pair: str(pair[0]))
        ],
        "note": "只记录调用形态（api/version/appKey/方法/参数名），不含任何参数值、cookie 或响应内容",
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    sys.stdout.write(text + "\n")
    out = arguments.out or str(
        _REPO_ROOT / "taobao-publisher" / "tmp"
        / f"picturecenter-call-shapes-{time.strftime('%Y%m%d%H%M%S')}.json"
    )
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(text, encoding="utf-8")
    sys.stdout.write(f"[已写入产物] {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""把发布工作台导航到指定一步，供后续只读勘察。

**只做导航，不填任何字段、不点保存、不提交。**

用法::

    # 走到「填写页」（catId 取自已归档证据 E-026）
    python taobao-publisher/scripts/navigate-workbench.py --address 127.0.0.1:9502 --cat-id 201581801

    # 回到类目搜索页
    python taobao-publisher/scripts/navigate-workbench.py --address 127.0.0.1:9502 --step category
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request

CATEGORY_URL = "https://item.upload.taobao.com/sell/ai/category.htm"


def publish_url(cat_id: str) -> str:
    """构造填写页 URL。

    参数形态来自已归档的实测证据（taobao-publisher/docs/08-页面实拍与流程.md，E-026）：
    ``catId`` 是**导航参数**，不是写入字段——``item.category_id`` 仍是 candidate。
    """

    query = {
        "catId": cat_id,
        "fromAICategory": "true",
        "fromAIPublish": "true",
        "newRouter": "1",
        "keyProps": "{}",
    }
    return "https://item.upload.taobao.com/sell/v2/publish.htm?" + urllib.parse.urlencode(query)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--cat-id", default="", help="叶子类目 ID")
    parser.add_argument("--step", choices=["category", "publish"], default="publish")
    parser.add_argument("--wait", type=float, default=12.0)
    args = parser.parse_args()

    if args.step == "publish" and not args.cat_id:
        parser.error("--step publish 需要 --cat-id")

    url = CATEGORY_URL if args.step == "category" else publish_url(args.cat_id)

    with urllib.request.urlopen("http://{}/json/list".format(args.address), timeout=5) as response:
        targets = json.loads(response.read().decode("utf-8"))
    pages = [
        t for t in targets
        if t.get("type") == "page" and "item.upload.taobao.com" in str(t.get("url") or "")
    ]
    if not pages:
        print("没有发布工作台页面")
        return 1
    page = pages[0]

    import websocket

    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=10, suppress_origin=True)
    ws.settimeout(3)
    ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
    ws.send(json.dumps({"id": 2, "method": "Page.navigate", "params": {"url": url}}))
    print("已请求导航到：{}".format(url))
    print("等待 {:.0f} 秒让页面渲染…".format(args.wait))
    time.sleep(args.wait)

    ws.send(json.dumps({"id": 3, "method": "Runtime.evaluate", "params": {
        "expression": "JSON.stringify({url: location.href.split('?')[0], title: document.title, ready: document.readyState})",
        "returnByValue": True,
    }}))
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            message = json.loads(ws.recv())
        except Exception:
            continue
        if message.get("id") == 3:
            value = (message.get("result") or {}).get("result", {}).get("value")
            info = json.loads(value) if isinstance(value, str) else {}
            print("当前页面：{}  「{}」  readyState={}".format(
                info.get("url"), info.get("title"), info.get("ready")))
            break
    ws.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

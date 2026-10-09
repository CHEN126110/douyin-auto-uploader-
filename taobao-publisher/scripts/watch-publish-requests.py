# -*- coding: utf-8 -*-
"""长效观察淘宝发布工作台的网络请求，供人工走一遍表单时取证。

**只观察，不点击、不填写、不提交、不上传。** 取证靠用户自己的操作产生流量，
本脚本只负责记录。

记录内容与**不记录**的内容（红线）：

  记录：host、path、HTTP 方法、资源类型、mtop 的 ``api`` 参数值、
        POST 体的**字段名**、响应状态码。
  不记录：任何 query **值**（含签名）、任何请求头、任何 cookie、
          POST 体字段的值、响应体内容。

用法::

    python taobao-publisher/scripts/watch-publish-requests.py --address 127.0.0.1:9502 --seconds 900

产物落在 ``taobao-publisher/tmp/``（已 gitignore）。要进仓库必须走
``python -m taobao_publish sanitize``。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

SCRIPT_DIR = Path(__file__).resolve().parent
SUBPROJECT = SCRIPT_DIR.parent
TMP_DIR = SUBPROJECT / "tmp"

#: 只记这些域名的请求——其余（CDN、埋点、字体）对发布流程没有价值。
INTERESTING_HOSTS = (
    "taobao.com",
    "tmall.com",
    "alibaba.com",
)

#: 明显是埋点/监控的 host，记了只会淹没有用信息。
NOISE_HOSTS = (
    "umdcv4.taobao.com",
    "alilog",
    "everyhelp",
    "servicehall",
    "helpcenter.taobao.com",
    "7b2w9j.tdum.alibaba.com",
)


def fetch_targets(address: str):
    with urllib.request.urlopen("http://{}/json/list".format(address), timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def pick_page(targets, host_hint: str):
    pages = [
        t for t in targets
        if t.get("type") == "page"
        and host_hint in str(t.get("url") or "")
        and not str(t.get("url") or "").startswith("devtools://")
    ]
    return pages[0] if pages else None


def is_interesting(url: str) -> bool:
    host = urlsplit(url).netloc
    if any(noise in host for noise in NOISE_HOSTS):
        return False
    return any(base in host for base in INTERESTING_HOSTS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502", help="CDP 调试地址")
    parser.add_argument("--host-hint", default="item.upload.taobao.com", help="目标页面域名")
    parser.add_argument("--seconds", type=float, default=900.0, help="观察时长")
    parser.add_argument("--out", default="", help="产物路径（默认 tmp/publish-requests-<时间戳>.json）")
    args = parser.parse_args()

    try:
        targets = fetch_targets(args.address)
    except Exception as exc:
        print("连不上调试端口 {}：{}".format(args.address, type(exc).__name__))
        return 1

    page = pick_page(targets, args.host_hint)
    if page is None:
        print("在 {} 上没有找到包含 {!r} 的页面。当前页面：".format(args.address, args.host_hint))
        for target in targets:
            if target.get("type") == "page":
                print("   ", target.get("url"))
        return 1

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    out_path = Path(args.out) if args.out else TMP_DIR / "publish-requests-{}.json".format(stamp)

    import websocket

    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=10, suppress_origin=True)
    ws.settimeout(2)
    ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
    ws.send(json.dumps({"id": 2, "method": "Page.enable"}))

    print("观察中：{}".format(page.get("url")))
    print("产物将写入：{}".format(out_path))
    print("时长 {:.0f} 秒。请正常操作页面（切 tab、展开下拉、选类目等），不要提交。".format(args.seconds))
    print()

    records = OrderedDict()
    started = time.time()
    last_report = 0.0

    def flush() -> None:
        payload = {
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "cdp_address": args.address,
            "page_url": urlsplit(str(page.get("url") or "")).path,
            "seconds_requested": args.seconds,
            "seconds_elapsed": round(time.time() - started, 1),
            "redaction": (
                "只含 host/path/方法/类型/mtop api 名/POST 字段名/状态码；"
                "不含 query 值、请求头、cookie、请求体值、响应体"
            ),
            "requests": list(records.values()),
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        while time.time() - started < args.seconds:
            try:
                message = json.loads(ws.recv())
            except Exception:
                continue

            method = message.get("method")
            params = message.get("params") or {}

            if method == "Network.requestWillBeSent":
                request = params.get("request") or {}
                url = str(request.get("url") or "")
                if not url.startswith("http") or not is_interesting(url):
                    continue
                parts = urlsplit(url)
                query = urllib.parse.parse_qs(parts.query)
                # mtop 的真实 API 名在 query 的 api 参数里；path 对它们全都一样。
                api_name = (query.get("api") or [""])[0]
                key = "{} {} {}".format(parts.netloc, parts.path, api_name)
                entry = records.get(key)
                if entry is None:
                    entry = {
                        "host": parts.netloc,
                        "path": parts.path,
                        "mtop_api": api_name or None,
                        "methods": [],
                        "types": [],
                        "query_param_names": sorted(query.keys()),
                        "post_field_names": [],
                        "count": 0,
                        "first_seen": datetime.now().isoformat(timespec="seconds"),
                    }
                    records[key] = entry
                entry["count"] += 1
                http_method = request.get("method")
                if http_method and http_method not in entry["methods"]:
                    entry["methods"].append(http_method)
                resource_type = params.get("type")
                if resource_type and resource_type not in entry["types"]:
                    entry["types"].append(resource_type)
                post_data = str(request.get("postData") or "")
                if post_data:
                    for name in urllib.parse.parse_qs(post_data).keys():
                        if name not in entry["post_field_names"]:
                            entry["post_field_names"].append(name)

            elif method == "Network.responseReceived":
                url = str(params.get("response", {}).get("url") or "")
                if not url.startswith("http") or not is_interesting(url):
                    continue
                parts = urlsplit(url)
                query = urllib.parse.parse_qs(parts.query)
                key = "{} {} {}".format(parts.netloc, parts.path, (query.get("api") or [""])[0])
                entry = records.get(key)
                if entry is not None:
                    status = params.get("response", {}).get("status")
                    entry["last_status"] = status
                    entry.setdefault("statuses", [])
                    if status not in entry["statuses"]:
                        entry["statuses"].append(status)

            now = time.time()
            if now - last_report >= 10.0:
                last_report = now
                flush()
                apis = sorted({r["mtop_api"] for r in records.values() if r.get("mtop_api")})
                print(
                    "[{:>5.0f}s] 不同请求 {} 个，其中 mtop 接口 {} 个".format(
                        now - started, len(records), len(apis)
                    ),
                    flush=True,
                )
    except KeyboardInterrupt:
        print("\n收到中断，落盘。")
    finally:
        flush()
        ws.close()

    apis = sorted({r["mtop_api"] for r in records.values() if r.get("mtop_api")})
    print()
    print("=" * 78)
    print("共 {} 个不同请求；mtop 接口 {} 个。".format(len(records), len(apis)))
    print("产物：{}".format(out_path))
    print("=" * 78)
    for api in apis:
        print("  mtop  {}".format(api))
    print()
    print("--- 非 CDN 的业务请求 ---")
    for entry in sorted(records.values(), key=lambda e: (e["host"], e["path"])):
        if "alicdn" in entry["host"] or "alibaba.com" in entry["host"] and "taobao" not in entry["host"]:
            continue
        print("  {:<32} {:<60} {}".format(entry["host"], entry["path"][:59], entry["count"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""在**页面里**调用图片空间 mtop 接口（只读）。

## 为什么不在 Python 里发

自己用 urllib 拼 header 发 ``mtop.taobao.picturecenter.console.dir.query``，无论
是 POST+body 还是 GET+query+JSONP，网关都判 ``FAIL_SYS_ILLEGAL_ACCESS::非法请求``
（实测）。而同一个 api 在浏览器里**每次都能成功**。差别只剩「请求是谁发的」：
浏览器的请求带着同源的 ``Referer``/``Origin``、真实的 ``ttid``、以及
mtop 客户端自己的 cookie 组合。

所以这里换一条更省事、也更稳的路：**在页面上下文里 ``fetch``**。

* 同源请求，不需要我们伪造任何 header；
* cookie（含 httpOnly）由浏览器自动带上；
* 响应原样取回，交给 Python 侧解析（**不在页面里判断成功失败**）。

**只读**：只用 GET，只调 ``*.query`` 这类读接口，不带任何写参数。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(_REPO_ROOT / "taobao-publisher"), str(_REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from taobao_publish.cdp_ws import CdpBrowser, CdpClientError  # noqa: E402
from taobao_publish.mtop import (  # noqa: E402
    BROWSER_JSV,
    BROWSER_TYPE,
    H5_APP_KEY_DEFAULT,
    MTOP_H5_HOST,
    classify_response,
    jsonp_callback_name,
    sign,
)
from taobao_publish.picturecenter import (  # noqa: E402
    build_directory_query,
    build_file_query,
    parse_directory_tree,
    parse_files,
)
from taobao_publish.upload_api import MTOP_API_DIR_QUERY, MTOP_API_FILE_QUERY  # noqa: E402

#: 用哪个页面作为调用来源。必须是 taobao.com 域的卖家页面，
#: 才能让 Referer/Origin 与真实调用一致。
PAGE_URL = "https://qn.taobao.com/home.htm/material-center/mine-material/sucai-tu"

#: 在页面里发一次 mtop 调用的表达式。``PAYLOAD`` 由 Python 侧替换。
#:
#: 关键点：
#: * ``credentials: 'include'`` —— 带上 cookie；
#: * 用 GET，``data`` 在 query（与真实页面一致）；
#: * 响应文本原样返回，**不在页面里判断成功与否**。
PAGE_MTOP_EXPRESSION = r"""
(async () => {
  const SPEC = PAYLOAD;
  try {
    const response = await fetch(SPEC.url, {
      method: 'GET',
      credentials: 'include',
      headers: { 'Accept': 'application/json, text/plain, */*' },
    });
    const text = await response.text();
    return { ok: true, status: response.status, text: text };
  } catch (error) {
    return { ok: false, error: String(error && error.message ? error.message : error) };
  }
})()
"""


def build_url(api: str, data: Dict[str, Any], *, token: str, callback: str) -> str:
    """拼出浏览器同形态的调用 URL（签名用仓库既有算法）。"""

    timestamp = str(int(time.time() * 1000))
    data_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    signature = sign(token, timestamp, H5_APP_KEY_DEFAULT, data_str)
    from urllib.parse import urlencode

    query = {
        "jsv": BROWSER_JSV,
        "appKey": H5_APP_KEY_DEFAULT,
        "t": timestamp,
        "sign": signature,
        "api": api,
        "v": "1.0",
        "type": BROWSER_TYPE,
        "dataType": "jsonp",
        "timeout": "10000",
        "data": data_str,
        "callback": callback,
    }
    return f"{MTOP_H5_HOST}/h5/{api}/1.0/?{urlencode(query)}"


def call_in_page(
    browser: CdpBrowser,
    session_id: str,
    api: str,
    data: Dict[str, Any],
    *,
    token: str,
    sequence: int = 1,
) -> Dict[str, Any]:
    """在页面里发一次 mtop GET，返回 ``{ok, status, text}`` 或 ``{ok:False, error}``。"""

    url = build_url(api, data, token=token, callback=jsonp_callback_name(sequence))
    expression = PAGE_MTOP_EXPRESSION.replace(
        "PAYLOAD", json.dumps({"url": url}, ensure_ascii=False), 1
    )
    result = browser.evaluate(expression, session_id=session_id, timeout=60.0)
    return result if isinstance(result, dict) else {"ok": False, "error": "无返回"}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="在页面里读图片空间目录/文件（只读）")
    parser.add_argument("--port", type=int, default=9334)
    parser.add_argument("--folder-id", default="", help="指定目录 ID 时改读文件清单")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--url", default=PAGE_URL)
    parser.add_argument("--out", default="")
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
    time.sleep(7)

    # token 在页面里读（`_tb_token_` 不是 httpOnly）
    token = browser.evaluate(
        "(() => { const m = document.cookie.match(/(?:^|;\\s*)_tb_token_=([^;]*)/);"
        " return m ? decodeURIComponent(m[1]) : ''; })()",
        session_id=session_id, await_promise=False, timeout=15.0,
    )
    if not isinstance(token, str) or not token:
        sys.stderr.write("页面里读不到 _tb_token_，未登录？\n")
        browser.close_target(target.target_id)
        browser.close()
        return 1

    payload: Dict[str, Any] = {"page": arguments.url, "token_present": True}
    if arguments.folder_id:
        api = MTOP_API_FILE_QUERY
        data = dict(build_file_query(token, folder_id=arguments.folder_id, page=arguments.page).body_params)
        payload["api"] = api
        result = call_in_page(browser, session_id, api, data, token=token, sequence=2)
    else:
        api = MTOP_API_DIR_QUERY
        data = dict(build_directory_query(token).body_params)
        payload["api"] = api
        result = call_in_page(browser, session_id, api, data, token=token, sequence=1)

    payload["transport"] = "in_page_fetch"
    payload["page_result"] = {"ok": result.get("ok"), "status": result.get("status"),
                              "error": result.get("error", "")}
    if result.get("ok"):
        outcome = classify_response(str(result.get("text") or ""))
        payload["mtop_ret"] = list(outcome.ret)
        payload["mtop_ok"] = outcome.ok
        payload["mtop_message"] = outcome.message
        if api == MTOP_API_DIR_QUERY:
            root, note = parse_directory_tree(outcome.payload)
            payload["parse_note"] = note
            payload["tree"] = root.to_dict() if root else None
        else:
            files, note = parse_files(outcome.payload)
            payload["parse_note"] = note
            payload["count"] = len(files)
            payload["files"] = [item.to_dict() for item in files[:30]]

    browser.close_target(target.target_id)
    browser.close()

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    sys.stdout.write(text + "\n")
    out = arguments.out or str(
        _REPO_ROOT / "taobao-publisher" / "tmp"
        / f"picturecenter-inpage-{time.strftime('%Y%m%d%H%M%S')}.json"
    )
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(text, encoding="utf-8")
    sys.stdout.write(f"[已写入产物] {out}\n")
    return 0 if payload.get("mtop_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())

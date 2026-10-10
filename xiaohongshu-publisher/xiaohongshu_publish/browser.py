# -*- coding: utf-8 -*-
"""小红书千帆：浏览器接入层（真机 CDP 9336）。

职责：只做"连接 + 浏览器专属动作"，业务顺序仍由 `flow.run_fill_only` 决定。
两个浏览器专属动作，都照真机实证实现：

1. **选可见标签页**（纪律 1）：优先取 `visibilityState === 'visible'` 的千帆标签页，
   否则 `Target.activateTarget` 激活；窗口在后台时激活无效（见 AGENTS.md）。
2. **上传图片**（两段式）：真实点『上传本地图片』（`input[type=file]` 此刻才挂载）
   → `DOM.querySelector('input[type=file]')` → `DOM.setFileInputFiles`；
   **成功判据是平台文案**「本次共成功上传 N 个文件，M 个文件上传失败」。

命令行（默认 dry-run，不传图、不写任何东西）：
    python -m xiaohongshu_publish.browser --title "……" [--upload a.jpg ...] [--yes]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "taobao-publisher") not in sys.path:
    sys.path.insert(0, str(REPO / "taobao-publisher"))

from taobao_publish.cdp_ws import CdpBrowser  # noqa: E402
from taobao_publish.page import PageClient  # noqa: E402

from .cdp import XhsPage  # noqa: E402

DEFAULT_PORT = 9336
CREATE_URL = "https://ark.xiaohongshu.com/app-item/good/create"

UPLOAD_TRIGGER = """(() => {
  const visible=e=>{const r=e.getBoundingClientRect();const s=getComputedStyle(e);
    return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
  const hits=Array.from(document.querySelectorAll('[class*="upload-trigger__label"]')).filter(visible);
  if(!hits.length) return {found:false};
  const r=hits[0].getBoundingClientRect();
  return {found:true, x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)};
})()"""

LOCAL_UPLOAD_BUTTON = """(() => {
  const visible=e=>{const r=e.getBoundingClientRect();const s=getComputedStyle(e);
    return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
  const hits=Array.from(document.querySelectorAll('button,[class*="d-button"],[role="button"]'))
    .filter(visible).filter(e=>(e.textContent||'').trim()==='上传本地图片');
  if(!hits.length) return {found:false};
  const r=hits[0].getBoundingClientRect();
  return {found:true, x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)};
})()"""

UPLOAD_RESULT = """(() => {
  const body=document.body.innerText||'';
  const m=body.match(/本次共成功上传\\s*(\\d+)\\s*个文件[，,]\\s*(\\d+)\\s*个文件上传失败/);
  return {success_text: m? m[0] : '', succeeded: m? Number(m[1]) : null,
          failed: m? Number(m[2]) : null, uploading:/上传中/.test(body)};
})()"""


def connect(port: int = DEFAULT_PORT) -> tuple[Any, XhsPage, Any, str]:
    """连接真机并返回 `(browser, page, client, session_id)`。

    优先选**可见**的千帆标签页（纪律 1）；没有可见的则激活第一个。
    """
    browser = CdpBrowser(port=port, timeout=25.0)
    targets = [t for t in browser.list_targets() if t.kind == "page"
               and "ark.xiaohongshu.com" in (t.url or "")]
    if not targets:
        browser.close()
        raise RuntimeError("没有千帆标签页：先启动 9336 调试实例并登录")
    chosen = None
    for target in targets:
        probe = PageClient.connect(target.web_socket_url, target_url=target.url)
        if probe.evaluate("document.visibilityState") == "visible" and chosen is None:
            chosen = (target, probe)
        else:
            probe.close()
    if chosen is None:
        target = targets[0]
        browser.call("Target.activateTarget", {"targetId": target.target_id})
        time.sleep(1.5)
        chosen = (target, PageClient.connect(target.web_socket_url, target_url=target.url))
    target, client = chosen
    session_id = browser.attach(target.target_id)
    page = XhsPage(client, browser=browser, target_id=target.target_id)
    return browser, page, client, session_id


def make_upload_fn(browser: Any, client: Any, session_id: Any, page: XhsPage):
    """生成 `upload_fn(paths)`：两段式上传 + 平台文案判据。"""

    def upload(paths: list) -> dict:
        pdf = [str(Path(p)) for p in paths]
        missing = [p for p in pdf if not Path(p).is_file()]
        if missing:
            return {"ok": False, "reason": "本地图片不存在", "missing": missing[:3]}
        too_big = [p for p in pdf if Path(p).stat().st_size > 5 * 1024 * 1024]
        if too_big:
            return {"ok": False, "reason": "有图片超过 5M，平台会拒绝", "files": too_big[:3]}

        # 抽屉没开就先点开（上传入口在抽屉里）
        if not page.drawer_state().get("drawers"):
            trigger = client.evaluate(UPLOAD_TRIGGER)
            if not trigger.get("found"):
                return {"ok": False, "reason": "找不到上传入口（upload-trigger__label）"}
            page.click(trigger["x"], trigger["y"])

        button = client.evaluate(LOCAL_UPLOAD_BUTTON)
        if not button.get("found"):
            return {"ok": False, "reason": "找不到「上传本地图片」按钮"}
        # 「上传本地图片」在抽屉里，是本动作的目标 → 绕过"抽屉开着就拒绝"的通用检查
        page._dispatch_click(button["x"], button["y"])  # noqa: SLF001 - 有意为之，见上句注释
        time.sleep(3.0)

        browser.call("DOM.enable", {}, session_id=session_id)
        document = browser.call("DOM.getDocument", {"depth": 1}, session_id=session_id)
        root = ((document or {}).get("root") or {}).get("nodeId")
        node = browser.call("DOM.querySelector",
                            {"nodeId": root, "selector": 'input[type="file"]'},
                            session_id=session_id)
        node_id = (node or {}).get("nodeId")
        if not node_id:
            return {"ok": False, "reason": "点击后仍未出现 input[type=file]"}
        browser.call("DOM.setFileInputFiles", {"files": pdf, "nodeId": node_id},
                     session_id=session_id)

        # 平台文案判据（不是素材列表的条数）
        deadline = time.monotonic() + 90
        result = {}
        while time.monotonic() < deadline:
            time.sleep(3.0)
            result = client.evaluate(UPLOAD_RESULT)
            if result.get("succeeded") is not None:
                break
        ok = bool(result.get("succeeded")) and not result.get("failed")
        return {"ok": ok, "expected": len(pdf), **result}
    return upload


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="小红书千帆 fill_only（默认 dry-run）")
    parser.add_argument("--title", required=True)
    parser.add_argument("--upload", nargs="*", default=[], help="本地图片路径（需配合 --yes）")
    parser.add_argument("--yes", action="store_true", help="显式授权上传（写入平台）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    from .flow import FillPlan, run_fill_only

    browser, page, client, session_id = connect(args.port)
    try:
        plan = FillPlan(title=args.title, images=args.upload, allow_upload=bool(args.yes))
        report = run_fill_only(page, plan,
                              upload_fn=make_upload_fn(browser, client, session_id, page))
    finally:
        client.close()
        browser.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

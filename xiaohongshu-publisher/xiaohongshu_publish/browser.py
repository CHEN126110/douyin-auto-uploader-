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


def _xhs_page_targets(browser: Any) -> list:
    """列出所有千帆标签页（每次现读，不缓存——`createTarget` 后列表有延迟）。

    导航/新开标签后 `list_targets()` **不会立刻反映**（见 AGENTS.md「最终一致」一节），
    因此调用方一律轮询 + 设上限，而不是查一次就下结论 ✓。
    """
    try:
        targets = browser.list_targets()
    except Exception as error:  # noqa: BLE001 - 如实带上原因，不吞错
        raise RuntimeError("读不到标签页列表：%s" % error) from error
    return [t for t in targets
            if t.kind == "page" and "ark.xiaohongshu.com" in (t.url or "")]


#: 把标签救成 `visible` 的候选手段（真机实测排序，2026-10-14 晚）。
#:
#: 为什么需要：`Target.activateTarget` **在当前环境 12 秒内完全无效** ✗
#: （浏览器窗口不在前台时，它只切"窗口内的当前标签"，不改窗口的前台状态），
#: 于是创建页标签始终 `hidden` → 按纪律 1 拒绝点击 → 整条流程无法开始。
#:
#: 逐个实测（都轮询确认，浏览器侧"最终一致"✓）：
#:   1. `Emulation.setFocusEmulationEnabled` → **立即 visible** ✓（本轮实际生效的手段）
#:   2. `Page.setWebLifecycleState {state:'active'}` → 之后也是 visible ✓
#:   3. `Page.bringToFront` → 之后也是 visible ✓
#: 三者都用 session 作用在**目标标签自己**身上；任何一个都不能省掉轮询 ✓。
_FOCUS_LEVERS = (
    ("Emulation.setFocusEmulationEnabled", {"enabled": True}),
    ("Page.setWebLifecycleState", {"state": "active"}),
    ("Page.bringToFront", {}),
)


def _try_focus_levers(browser: Any, target: Any) -> list:
    """让目标标签进入"可操作"状态；返回**每个手段是否报错**的证据列表。

    只改标签的聚焦 / 生命周期状态（浏览器侧，不是平台写入）✓；不点击、不填写。
    """
    applied: list = []
    try:
        session = browser.attach(target.target_id)
    except Exception as error:  # noqa: BLE001 - attach 失败也要如实带出
        return [{"lever": "attach", "error": str(error)[:160]}]
    for method, params in _FOCUS_LEVERS:
        try:
            browser.call(method, dict(params), session_id=session)
            applied.append({"lever": method, "ok": True})
        except Exception as error:  # noqa: BLE001 - 某个手段不支持不该中断其余手段
            applied.append({"lever": method, "ok": False, "error": str(error)[:160]})
    return applied


def _visible_probe(client: Any) -> bool:
    return client.evaluate("document.visibilityState") == "visible"


#: 评估"这个创建页标签里有多少已填内容"的表达式：只读，不点击不填写 ✓
#:
#: 为什么要它（2026-10-14 真机实测 ✗）：浏览器里**同时存在两个创建页标签**，
#: 表单状态（已传 22 图 + 已推进到四组页 + 标题）只在其中一个里，
#: 而**_两个都可能是 hidden**。旧实现只按"可见"挑 → 反复挑到空标签 →
#: 每次都要重传图片，用户看到的现象却像"表单自己丢了" ✗。
#: **可见性不是"哪个标签对"的判据** ✓；表单完成度才是。
FORM_STATE_PROBE = """(() => {
  const visible=e=>{const r=e.getBoundingClientRect();const s=getComputedStyle(e);
    return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
  const lines=(document.body.innerText||'').split('\\n').map(t=>t.trim()).filter(Boolean);
  const titleInput=Array.from(document.querySelectorAll('input[type=text]')).filter(visible)
    .find(e=>/品牌/.test(e.placeholder||''));
  return {
    href: location.href.split('?')[0],
    at_4groups: lines.includes('价格库存') || lines.includes('服务信息'),
    required_marks: document.querySelectorAll('[class*="required-icon"]').length,
    // 只数平台预览域上的图（其余是页面自身图标）
    uploaded_imgs: Array.from(document.querySelectorAll('img')).filter(visible)
      .filter(i => (i.getAttribute('src') || i.src || '').includes('ros-preview')).length,
    title_len: titleInput ? (titleInput.value || '').length : 0,
  };
})()"""


def _form_score(state: dict) -> tuple:
    """把一张表单的"已填程度"变成可比大小的元组（越大越该被选中）。

    排序依据（真机实测的可靠信号）：**已推进到四组页** > 平台图更多 > 必填标记更多 > 标题更长。
    刻意**不**把"可见"放进来：实测带表单的标签可能正是 hidden 的那个 ✗。
    """
    return (1 if state.get("at_4groups") else 0,
            int(state.get("uploaded_imgs") or 0),
            int(state.get("required_marks") or 0),
            int(state.get("title_len") or 0))


def _pick_richest_create_tab(targets: list) -> tuple:
    """从候选创建页标签里挑**表单最完整**的一个；返回 `(target, state, probe)`。

    读状态是只读的 ✓；读不到状态的候选会被跳过（不猜、不把它当首选）。
    调用方负责关掉未选中的 probe。
    """
    best = None
    for target in targets:
        probe = None
        try:
            probe = PageClient.connect(target.web_socket_url, target_url=target.url)
            state = probe.evaluate(FORM_STATE_PROBE) or {}
        except Exception:  # noqa: BLE001 - 读不到的候选跳过，不中断其余候选
            if probe is not None:
                probe.close()
            continue
        score = _form_score(state)
        if best is None or score > best[0]:
            if best is not None:
                best[3].close()
            best = (score, target, state, probe)
        else:
            probe.close()
    if best is None:
        raise RuntimeError("读到创建页标签，但都读不出表单状态（不做猜测）")
    return best[1], best[2], best[3]


def connect(port: int = DEFAULT_PORT) -> tuple[Any, XhsPage, Any, str]:
    """连接真机并返回 `(browser, page, client, session_id)`。

    选取规则（2026-10-14 第二次修正）：**创建页是硬前提，可见性只是它的一个属性**。
    顺序固定为：
      ① 有创建页标签且**可见** → 直接用（不做无谓的浏览器状态变更）；
      ② 有创建页标签但**在后台** → `Target.activateTarget` 把它带到前台再连（纪律 1）；
      ③ 激活无效（窗口本身在后台）或**根本没有创建页标签** → `Target.createTarget`
         新开一个，等它加载出创建页再连（新开标签实测可见）；
      ④ 以上都拿不到 → **明确报错**，绝不退化成"拿可见的那页凑合" ✗。

    为什么这样改（2026-10-14 真机踩过 ✗）：上一版虽然"创建页标签优先"，
    但选择循环写成"**第一个 `visible` 的标签就赢**"——创建页藏在后台时先被跳过，
    紧接着的可见首页（`app-system/home`）立刻占住 `chosen`，
    于是 ②③ 那段兜底（前置条件 `chosen is None`）**永远不执行** ✗，
    整条填表又跑在首页上：上传第一步找不到 `upload-trigger__label`，
    界面只报「图片上传未成功」，真实原因被完全掩盖 ✗。
    （上一版验收时创建页恰好在前台，所以显示了"通过"——环境依赖型绿灯。）

    因此**不再回退到"任意可见的千帆标签"**：那种回退与"创建页优先"互相矛盾，
    正是这个 bug 的来源。
    """
    browser = CdpBrowser(port=port, timeout=25.0)
    try:
        targets = _xhs_page_targets(browser)
        if not targets:
            raise RuntimeError("没有千帆标签页：先启动调试实例并登录")

        create_targets = [t for t in targets if "good/create" in (t.url or "")]
        probe = None
        chosen = None

        # ① 有创建页标签 → **按表单完成度挑**（不是按可见性 ✗）
        #    真机实测：可能同时开着多个创建页，表单只在其中一个里，而两个都可能是 hidden；
        #    只按"可见"挑会反复挑到空标签 → 看起来像"表单自己丢了" ✗。
        if create_targets:
            chosen, chosen_state, probe = _pick_richest_create_tab(create_targets)

            # ② 挑中的标签不可见 → 先 activateTarget，再走聚焦手段 + 轮询（纪律 1）
            if not _visible_probe(probe):
                browser.call("Target.activateTarget", {"targetId": chosen.target_id})
                _try_focus_levers(browser, chosen)
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    time.sleep(0.5)
                    if _visible_probe(probe):
                        break

            if not _visible_probe(probe):
                # ③ 救不活时分两种情况（**按表单内容区分**，这比一刀切更贴合真实需求）：
                if _form_score(chosen_state) != (0, 0, 0, 0):
                    # 有已填内容 → **绝不新开**（新开等于把已传的图/已填的字段丢掉 ✗），
                    # 如实报错让调用方处理（例如提示用户把窗口切到前台）✓
                    raise RuntimeError(
                        "创建页标签不可见但**已有已填内容**（图 {} 张 / 必填标记 {} 项）："
                        "拒绝新开标签以免丢失表单，按纪律 1 不做任何点击。"
                        "请把浏览器窗口切到前台后重试".format(
                            chosen_state.get("uploaded_imgs"), chosen_state.get("required_marks")))
                # 空表单：新开一个可操作的前台标签页划算（没有内容可丢）✓
                probe.close()
                probe = None
                chosen = None

        # ④ 没有创建页标签 / 挑中的空标签救不活 → 新开并等它加载出创建页
        if chosen is None:
            created = browser.call("Target.createTarget", {"url": CREATE_URL})
            new_id = (created or {}).get("targetId")
            fresh = None
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                fresh = next((t for t in _xhs_page_targets(browser)
                              if t.target_id == new_id and "good/create" in (t.url or "")), None)
                if fresh is not None:
                    break
                time.sleep(0.5)
            if fresh is None:
                raise RuntimeError(
                    "打不开商品创建页标签（%s）：Target.createTarget 未返回可用的创建页" % CREATE_URL)
            time.sleep(5.0)  # 新标签页要等它自己加载出首屏（导航会销毁执行上下文）
            probe = PageClient.connect(fresh.web_socket_url, target_url=fresh.url)
            # 新开标签**未必可见**（2026-10-14 实测：浏览器窗口不在前台时它是 hidden ✗）
            # → 同样先用聚焦手段救，再轮询；救不活就明确报错，**不硬点** ✓
            if not _visible_probe(probe):
                _try_focus_levers(browser, fresh)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    time.sleep(0.5)
                    if _visible_probe(probe):
                        break
            if not _visible_probe(probe):
                raise RuntimeError(
                    "新开的创建页标签不可见（已尝试 setFocusEmulationEnabled / "
                    "setWebLifecycleState / bringToFront 并轮询），按纪律 1 拒绝操作")
            chosen = fresh

        # ④ 落点必须真的是创建页，否则明确报错（防止再次跑错页面）
        href = probe.evaluate("location.href") or ""
        if "good/create" not in href:
            raise RuntimeError(
                "连接到的标签不是商品创建页（location.href=%r）" % href)

        session_id = browser.attach(chosen.target_id)
        page = XhsPage(probe, browser=browser, target_id=chosen.target_id)
        return browser, page, probe, session_id
    except Exception:
        browser.close()   # 失败路径不要泄漏连接（调用方拿不到 browser 就关不掉）
        raise


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

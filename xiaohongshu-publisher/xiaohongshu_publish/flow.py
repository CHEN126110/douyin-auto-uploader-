# -*- coding: utf-8 -*-
"""小红书千帆：`fill_only` 编排（填满、停在提交之前）。

边界（沿用 taobao-publisher 的红线）：
- **默认零写入**：上传图片属于平台写入，必须有 `allow_upload=True` 才执行，否则**拒绝并返回原因**；
- **永不提交**：本模块不点「提交商品」/「上架」/「保存草稿」——连入口都没有。
  「信息已确认，下一步」只是**组间推进**（不是提交），由 `allow_advance=True` 显式打开；
  未选类目时推进会被平台拦下：`错误：请选择商品类目`（真机实证）。

顺序是硬的（真机实证，表单不跨导航保留）：

    图片 → 标题（失焦）→ 选类目（先关抽屉！）→ 下一步
    → 读 required-icon 全集 → 按缺口填服务信息 → **停在提交前**
"""

from __future__ import annotations

from pathlib import Path

from dataclasses import dataclass, field
from typing import Any, Callable

from . import rules
from .cdp import XhsPage


@dataclass
class FillPlan:
    """一次 fill_only 的输入。"""

    title: str
    images: list = field(default_factory=list)      # 本地图片路径
    allow_upload: bool = False                      # 上传＝平台写入，必须显式授权
    allow_advance: bool = False                     # 是否允许点「信息已确认，下一步」（组间推进，非提交）
    category: str = ""                              # 要选中的类目短名，如「长筒袜」；空＝不代替人选
    service_values: dict = field(default_factory=dict)  # 服务信息组取值；缺的字段不猜


def required_gaps(page: XhsPage) -> dict:
    """读**平台自己的**必填判据，回答"还差什么"。

    两个来源（真机实证）：
    - `REQUIRED_FIELDS`：按平台的 `required-icon` 标记列出必填字段及其是否已填
      （标记是空文本元素 → `innerText` 里读不到 `*`，只能按 class 找）；
    - `JUDGES`：三套完成度计数（关键属性 N/7、其他属性 N/8、N 项必填）+ 发布助手占位语义。

    **不要**用"看起来重要"来猜必填项——这是本项目反复强调的纪律。
    """
    from . import page_scripts

    required = page.client.evaluate(page_scripts.REQUIRED_FIELDS) or {}
    judges = page.client.evaluate(page_scripts.JUDGES) or {}
    return {
        "required_count": required.get("required_count", 0),
        "unfilled": list(required.get("unfilled") or []),
        "filled": list(required.get("filled") or []),
        "judges": judges,
    }


#: 服务信息组的字段（真机实测的必填项；详见 `docs/07-字段测绘表.md` §8.9）
SERVICE_FIELDS = ("物流模板", "物流类型", "运费模板", "发货模式", "现货发货时间",
                  "开售时间", "售后服务")

#: 「信息已确认，下一步」——组间推进按钮（**不是**提交；真机文案）
NEXT_STEP_TEXT = "信息已确认，下一步"


def select_category(page: XhsPage, category: str) -> dict:
    """选中类目（真机已验证的交互：按文本找**被绘制**的最小匹配元素再点）。

    边界：
    - 先关抽屉（纪律 4）——上传后抽屉常还开着，不关就点不到类目；
    - 目标文本带「(未开通)」时**拒绝点选**（那是资质问题，只能人工办）；
    - 点完回读「已选类目」，没选上就如实报告，不假装成功。
    """
    from . import page_scripts

    category = (category or "").strip()
    if not category:
        return {"ok": False, "reason": "未提供类目名"}
    if "未开通" in category:
        return {"ok": False, "reason": "类目未开通，需人工在千帆后台办理资质", "category": category}
    if not page.close_drawer():
        return {"ok": False, "reason": "抽屉关不掉，按纪律 4 不操作类目控件"}
    found = page.client.evaluate(page_scripts.find_painted_script(
        category, selector="div,span,label,li,button"))
    if not found.get("ok"):
        return {"ok": False, "reason": "类目未找到或不可点：{}".format(found.get("reason")),
                "category": category}
    if "未开通" in (found.get("text") or ""):
        return {"ok": False, "reason": "命中的是未开通类目，拒绝点选",
                "category": category, "hit_text": found.get("text")}
    clicked = page.click(found["x"], found["y"], expect_text=category)
    if not clicked.get("clicked"):
        return {"ok": False, "reason": "类目点击被拒：{}".format(clicked.get("reason")),
                "category": category, "hit": clicked.get("hit")}
    state = page.state()
    selected = [line for line in (state.get("category_lines") or [])
                if "已选" in line and "未开通" not in line]
    return {"ok": True, "category": category, "selected_lines": selected,
            "errors": state.get("errors") or []}


def advance_next(page: XhsPage) -> dict:
    """点「信息已确认，下一步」推进到四组信息（组间推进，**不是**提交）。"""
    from . import page_scripts

    if not page.close_drawer():
        return {"ok": False, "reason": "抽屉关不掉，按纪律 4 不点下一步"}
    found = page.client.evaluate(page_scripts.find_painted_script(
        NEXT_STEP_TEXT, selector="button,[class*='d-button']", exact=False))
    if not found.get("ok"):
        return {"ok": False, "reason": "下一步按钮未找到：{}".format(found.get("reason"))}
    # 真机教训：点按钮要取**最小**匹配元素，取大的会点到动作栏容器
    clicked = page.click(found["x"], found["y"], expect_text="信息已确认")
    if not clicked.get("clicked"):
        return {"ok": False, "reason": "下一步点击被拒：{}".format(clicked.get("reason")),
                "hit": clicked.get("hit")}
    return {"ok": True, "text": found.get("text")}


def make_service_filler(page: XhsPage, values: dict | None = None):
    """生成 `fill_gaps` 用的 filler：**打开字段下拉 → 选值**，逐项填服务信息组。

    两半动作都取自真机验证过的表达式：`page_scripts.open_field_script`（行级定位 +
    采样未被覆盖的点）与 `page_scripts.pick_option_script`（只认被绘制的选项）。

    边界：
    - `values` 里**没有**的字段 → 明确报告「未提供取值（不猜）」，绝不瞎选；
    - 打开失败 / 选项没被绘制 → 报告该字段的具体原因，**继续下一项**（不静默跳过）；
    - 非服务信息组的字段 → 交给别的步骤（报告 `skipped`）；
    - **不点提交**，也不点「下一步」。
    """
    import time  # 局部导入：只在这个小助手用得到

    from . import page_scripts

    values = dict(values or {})

    def fill(gaps: dict) -> dict:
        outcome: dict = {}
        for label in gaps.get("unfilled") or []:
            if label not in SERVICE_FIELDS:
                outcome[label] = {"skipped": "非服务信息组字段，交由其它步骤处理"}
                continue
            value = values.get(label)
            if value is None:
                outcome[label] = {"skipped": "未提供取值（不猜）"}
                continue
            opened = page.client.evaluate(page_scripts.open_field_script(label))
            if not opened.get("ok"):
                outcome[label] = {"ok": False, "stage": "open",
                                  "reason": opened.get("reason")}
                continue
            page._dispatch_click(opened["x"], opened["y"])  # noqa: SLF001 - 库内协作
            time.sleep(1.5)
            picked = page.client.evaluate(page_scripts.pick_option_script(value))
            if not picked.get("ok"):
                outcome[label] = {"ok": False, "stage": "pick", "value": value,
                                  "reason": picked.get("reason")}
                continue
            page._dispatch_click(picked["x"], picked["y"])  # noqa: SLF001
            time.sleep(1.2)
            outcome[label] = {"ok": True, "value": value}
        return outcome

    return fill


def fill_gaps(page: XhsPage, filler, max_rounds: int = 3) -> dict:
    """「读缺口 → 补 → 复读」循环（fill_only 的收尾阶段）。

    `filler(gaps)` 由调用方注入，负责"按缺口做具体填写"（它才知道每个字段怎么填）；
    本函数只做三件事：**读平台判据 → 交给 filler → 复读**，并把每一轮都记成证据。

    边界：
    - **不做任何提交**，也不点「下一步」以外的东西；
    - 轮数有限（默认 3），缺口没变就停（避免无意义空转）；
    - `filler` 抛错则记录并停止（**不吞错**，也不假装填成功）。
    """
    history: list = []
    for round_index in range(max_rounds):
        gaps = required_gaps(page)
        unfilled = list(gaps.get("unfilled") or [])
        record: dict = {"round": round_index + 1, "unfilled": unfilled,
                        "judges": gaps.get("judges")}
        history.append(record)
        if not unfilled:
            record["note"] = "无必填缺口"
            break
        try:
            outcome = filler(gaps)
        except Exception as error:  # noqa: BLE001 - 记录后停止，不吞错
            record["error"] = str(error)
            break
        record["filled_by_hook"] = outcome
        if not outcome:
            record["note"] = "filler 未报告任何填写，停止循环"
            break
    return {"rounds": history, "final": required_gaps(page)}


def describe_images(paths: list) -> list:
    """上传前对图片做**只读自检**，结果写进报告（计划 1.2）。

    为什么需要它：上传失败时界面上只看到「图片上传未成功」✗，而真正的原因
    （路径不存在 / 超过 5M / 格式不对）都在**本地预检**里 —— 把这三项如实带出来，
    下一次失败就能一眼定位，不用再猜 ✓。

    只读、无副作用；不做任何平台写入 ✓。返回每条一项：
    ``{path, exists, size_mb, ok, problem}``。
    """
    described: list = []
    for raw in paths or []:
        text = str(raw)
        entry = {"path": text, "exists": False, "size_mb": None, "ok": False,
                 "problem": ""}
        try:
            candidate = Path(text)
            if not candidate.is_file():
                entry["problem"] = "本地图片不存在"
            else:
                size = candidate.stat().st_size
                entry["exists"] = True
                entry["size_mb"] = round(size / 1048576.0, 3)
                if size > 5 * 1024 * 1024:
                    entry["problem"] = "超过 5M（平台会拒绝）"
                elif candidate.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                    entry["problem"] = "格式平台不收（只收 .jpg/.jpeg/.png）"
                else:
                    entry["ok"] = True
        except OSError as error:  # noqa: BLE001 - 读不到就如实记，不吞错
            entry["problem"] = "无法读取：{}".format(error)
        described.append(entry)
    return described


def run_fill_only(page: XhsPage, plan: FillPlan,
                  upload_fn: Callable[[list], dict] | None = None) -> dict:
    """执行 fill_only。返回结构化结果（含逐步证据），不抛业务异常。

    `upload_fn(paths)` 由调用方注入（它需要 CDP 的 DOM 域，属于浏览器层职责）；
    未注入而 `plan.images` 非空时，会**明确报告无法上传**而不是假装成功。
    """
    report: dict = {"ok": True, "blocked": [], "steps": []}

    # 0) 先做本地校验：标题不合规就不要动页面（省一次真机往返）
    title_check = rules.check_title(plan.title)
    report["title_check"] = {"ok": title_check.ok, "units": title_check.units,
                             "words": title_check.words, "reasons": list(title_check.reasons)}
    if not title_check.ok:
        report["ok"] = False
        report["blocked"].append("标题不合规：" + title_check.describe())
        return report

    # 1) 纪律 4：抽屉必须关着，否则页面控件点不到
    if not page.close_drawer():
        report["ok"] = False
        report["blocked"].append("素材空间抽屉关不掉，按纪律 4 停止（不带着覆盖层操作页面）")
        return report

    # 2) 图片：写入操作 → 必须授权
    if plan.images:
        # 只读自检放在**授权判断之前**（计划 1.2）：未授权时也能看到"本来会传哪些图、是否存在"✓
        # —— 这一步不做任何平台写入 ✓，因此不需要授权。
        report["resolved_images"] = describe_images(plan.images)
        if not plan.allow_upload:
            report["ok"] = False
            report["blocked"].append(
                "未授权上传：{} 张图片未上传（allow_upload=False）".format(len(plan.images)))
            return report
        if upload_fn is None:
            report["ok"] = False
            report["blocked"].append("调用方未注入 upload_fn，无法上传图片")
            return report
        upload_result = page.run("upload_images", lambda: upload_fn(plan.images))
        report["steps"].append({"name": "upload_images", **upload_result})
        if not upload_result.get("ok"):
            report["ok"] = False
            report["blocked"].append("图片上传未成功，停止后续填写")
            return report

    # 3) 标题（原生 setter + 主动失焦，类目控件靠失焦解锁）
    set_result = page.set_title(plan.title)
    if not set_result.get("ok"):
        report["ok"] = False
        report["blocked"].append("标题写入失败：" + str(set_result.get("reason")))
        return report
    state = page.state()
    report["steps"].append({"name": "set_title", **set_result})
    report["state_after_title"] = state
    report["title_counter"] = state.get("title_counter", "")
    # 回读校验：写进去的值必须与计划一致（不信任"调用成功"）
    if (set_result.get("value") or "") != plan.title:
        report["ok"] = False
        report["blocked"].append("标题回读不一致，停止（可能被平台截断或改写）")
        return report

    # 4) 类目：未选时平台会拦「请选择商品类目」
    report["category_lines"] = state.get("category_lines", [])
    unopened = [line for line in state.get("category_lines", []) if "未开通" in line]
    if unopened:
        report["blocked"].append(
            "类目未开通（{} 项）：需人工在千帆后台办理类目资质".format(len(unopened)))
        report["category_unopened"] = unopened

    if plan.category:
        if unopened and any(plan.category in line for line in unopened):
            report["ok"] = False
            report["blocked"].append(
                "目标类目「{}」未开通，停止（不绕过平台资质）".format(plan.category))
            report["evidence"] = page.evidence()
            return report
        select_result = page.run(
            "select_category", lambda: select_category(page, plan.category))
        report["steps"].append({"name": "select_category", **select_result})
        if not select_result.get("ok"):
            report["ok"] = False
            report["blocked"].append(
                "类目「{}」选入失败：{}".format(plan.category, select_result.get("reason")))
            report["evidence"] = page.evidence()
            return report
        state = page.state()
        report["category_lines"] = state.get("category_lines", [])

    # 5) 组间推进（不是提交）：展开 基础/图文/价格库存/服务 四组信息
    if plan.allow_advance:
        if not plan.category and not any("已选" in line for line in report.get("category_lines") or []):
            report["ok"] = False
            report["blocked"].append("未选类目，拒绝点下一步（平台会拦：请选择商品类目）")
            report["evidence"] = page.evidence()
            return report
        advance_result = page.run("advance_next", lambda: advance_next(page))
        report["steps"].append({"name": "advance_next", **advance_result})
        if not advance_result.get("ok"):
            report["ok"] = False
            report["blocked"].append(
                "下一步推进失败：{}".format(advance_result.get("reason")))
            report["evidence"] = page.evidence()
            return report
        # 浏览器侧变更最终一致：给表单展开一点时间，再读缺口
        import time as _time
        _time.sleep(2.0)

        # 服务信息组：只填 values 里给了取值的字段，缺的一律「未提供取值（不猜）」
        if plan.service_values:
            filler = make_service_filler(page, plan.service_values)
            report["service_fill"] = fill_gaps(page, filler)

    # 6) 读平台自己的判据：还差哪些必填项（实现里不猜必填）
    try:
        report["gaps"] = required_gaps(page)
    except Exception as error:  # noqa: BLE001 - 判据读不到不该让整个填写失败
        report["gaps"] = {"error": str(error)}

    report["evidence"] = page.evidence()
    return report

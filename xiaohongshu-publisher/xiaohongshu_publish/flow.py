# -*- coding: utf-8 -*-
"""小红书千帆：`fill_only` 编排（填满、停在提交之前）。

边界（沿用 taobao-publisher 的红线）：
- **默认零写入**：上传图片属于平台写入，必须有 `allow_upload=True` 才执行，否则**拒绝并返回原因**；
- **永不提交**：本模块不点「提交商品」，也不点「信息已确认，下一步」——
  推进到下一组表单由调用方显式用 `allow_advance=True` 打开（当前默认关闭，
  且实测在类目未选时推进也会被平台拦下：`错误：请选择商品类目`）。

顺序是硬的（真机实证）：**图片 → 标题 → 失焦 → 类目控件才出现**。
"""

from __future__ import annotations

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
    allow_advance: bool = False                     # 是否允许点「下一步」（默认停在当前步）


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

    # 4) 类目：未选时平台会拦「请选择商品类目」；本模块只报告，不代替人做选择
    report["category_lines"] = state.get("category_lines", [])
    unopened = [line for line in state.get("category_lines", []) if "未开通" in line]
    if unopened:
        report["blocked"].append(
            "类目未开通（{} 项）：需人工在千帆后台办理类目资质".format(len(unopened)))
        report["category_unopened"] = unopened

    # 5) 读平台自己的判据：还差哪些必填项（实现里不猜必填）
    try:
        report["gaps"] = required_gaps(page)
    except Exception as error:  # noqa: BLE001 - 判据读不到不该让整个填写失败
        report["gaps"] = {"error": str(error)}

    report["evidence"] = page.evidence()
    return report

# -*- coding: utf-8 -*-
"""自检：把散在各处的「门」收成一次可跑完的检查。

这些门是过去几十轮里一次次踩坑攒下来的，原先分散在
``tests/check_all_builders.py``、``scripts/check-error-catalog.py``、
``scripts/check-hard-rules-coverage.py`` 与契约自检里——
**要记得跑五个地方，实际上就是不会跑**。

现在收成一个入口：

    python -m taobao_publish check

六道门：

1. **契约自检** —— 阶段登记表、选择器、字段映射是否自洽；
2. **构造器冒烟** —— 把每个 ``build_*`` 真的调一遍（花括号错误只在调用时抛）；
3. **错误目录完备性** —— 被抛出的码必须在目录里（4 种声明方式）；
4. **hard 规则覆盖** —— 契约里 ``hard: true`` 的规则，代码里必须出现；
5. **陈旧说法** —— 不许再出现「尚未实现」这类已经被实现掉的说法。
6. **动作守卫** —— 点「按条件挑出来的第一个」时，守卫必须是**精确计数**
   （``=== 1`` / ``!== 1``），不能是下界（``>= 1``）或真值（``if (x.length)``）——
   后两者在多命中时会**静默挑第一个**。

⚠️ 第 4 道只是**名字覆盖**。行为验证在 ``tests/test_every_hard_rule_fires.py``
里（11 条逐条喂越界输入）——名字出现**不等于**真的执行，
导购标题那条就是名字出现在 ``desktop.py``（人工准备路径），
而发布流水线根本不引用它。

**只读**：不连浏览器、不碰平台、不写文件。
"""

from __future__ import annotations

import ast
import inspect
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .contracts import SUBPROJECT_ROOT

#: 需要参数的构造器 → 给一组覆盖各分支的实参。
ARG_CASES: Dict[str, List[Tuple]] = {
    "build_set_expression": [("尺码", "M(37-41)")],
    "build_read_expression": [("尺码",)],
    "build_click_unique_text_expression": [(".result-item", "袜子")],
    "build_select_brand_expression": [("无品牌/无注册商标",)],
    "build_pick_brand_option_expression": [("无品牌/无注册商标",)],
    "build_search_in_brand_dropdown_expression": [("无品牌",)],
    "build_open_media_popup_expression": [(), ("3:4主图",)],
    "build_click_media_entry_expression": [("本地上传",), ("图片空间",)],
    "build_select_media_image_expression": [("详情_004.jpg",)],
    "build_media_image_expression": [("详情_004.jpg",)],
    # 按上传回执 ID 精确选图（确定性选择）：必须给 ID；select 两档都要能构造。
    "build_pick_media_by_id_expression": [
        (["1114908854813672480"],),
        (["1114908854813672480", "1114908854729358410"], False),
    ],
    # 详情：模块编辑器的「图片」入口 / 内容图回读 / 多选确定（都无参数）
    "build_open_detail_pic_module_expression": [()],
    "build_detail_content_images_expression": [()],
    "build_confirm_media_selection_expression": [()],
    "build_confirm_media_selection_in_frame_expression": [()],
    "build_read_detail_editor_state_expression": [()],
    "build_switch_detail_to_legacy_expression": [()],
    "build_confirm_detail_legacy_dialog_expression": [()],
    # SKU 自定义规格：图片落点（规格名**先聚焦再失焦**后才绑定交互）
    "build_open_sku_image_picker_expression": [("探测A",)],
    "build_focus_and_blur_sku_row_expression": [("探测A",)],
    "build_sku_row_points_expression": [("探测A",)],
    "build_read_sku_picker_state_expression": [()],
    # 预览覆盖层：放行(true) / 恢复(false) 两档都要能构造
    "build_suspend_preview_overlay_expression": [(True,), (False,)],
    # 上架时间：按文本选单选项。两档都要能构造——写入档 + **回读档**
    # （回读档只报状态不点击，是"读回确认"依赖的那条路径，不测就漏）。
    "build_choose_radio_by_text_expression": [
        ("上架时间", "放入仓库"),
        ("上架时间", "放入仓库", True),
        ("上架时间", "立刻上架", True),
    ],
    # 一次求值读回一组单选项的状态（"三个里恰好一个选中"靠它判）
    "build_radio_group_state_expression": [
        ("上架时间", ("立刻上架", "定时上架", "放入仓库")),
    ],
    # 按文本点按钮：提交与保存草稿**共用同一份守卫**（判据只有一份）
    "build_click_button_by_text_expression": [
        ("提交宝贝信息",),
        ("保存草稿",),
    ],
    # 详情：清空模块 / 通用二次确认
    "build_clear_detail_modules_expression": [()],
    "build_confirm_dialog_ok_expression": [()],
    # ⚠️ 这个构造器**必须给参数**（image_kind 无默认值）。
    # 旧的 tests/check_all_builders.py 里这个键**写了两次**，
    # Python 字典取后者，前一行是死代码——合并时才发现。
    "build_read_main_slots_expression": [("1:1主图",), ("3:4主图",)],
    "build_open_sku_drawer_expression": [()],
    "build_read_sku_drawer_state_expression": [()],
    "build_add_spec_row_expression": [("尺码",), ("颜色分类",)],
    "build_open_prop_dropdown_expression": [("品牌",)],
    "build_search_prop_options_expression": [("无品牌",)],
    "build_read_prop_value_expression": [("品牌",)],
    "build_open_spec_value_input_expression": [("尺码",)],
    "build_pick_spec_value_expression": [("M(37-41)",)],
    "build_set_prop_selected_expression": [("颜色分类", True), ("颜色分类", False)],
    "build_confirm_sku_expression": [()],
    "build_read_sku_table_expression": [()],
    # SKU 行的价格 / 库存：读不需要参数，写需要（行号, 价格, 库存）。
    "build_read_sku_row_numbers_expression": [()],
    # 读选项组（radio/checkbox）的选中项——需要一个标签参数。
    "build_read_selected_options_expression": [("发货时间",),
                                               ("提取方式",)],

    "build_set_sku_row_numbers_expression": [(0, "16.80", "200"),
                                              (1, "", "0")],

    "build_open_freight_expression": [()],
    "build_read_freight_options_expression": [()],
    "build_pick_freight_option_expression": [("极兔快递",)],
    "build_read_freight_value_expression": [()],
    "build_read_submit_state_expression": [()],
    "build_click_submit_expression": [()],
    "build_read_submit_outcome_expression": [()],
    "build_read_media_popup_expression": [()],
    "build_read_media_file_input_expression": [()],
    "build_read_media_space_images_expression": [()],
    "build_close_media_popup_expression": [()],
    "build_read_page_facts_expression": [()],
    "build_query_element_expression": [
        ('input[type="file"]',), (".sell-component-image-v2-media-popup",)],
    "build_search_category_expression": [("袜子",)],
    "build_switch_category_tab_expression": [("类目",), ("全部",)],
    "build_count_publish_rows_expression": [()],
    "build_click_media_finish_expression": [()],
    "build_count_media_cards_expression": [()],
    "build_media_gallery_state_expression": [()],
    "build_open_media_page_expression": [(1,), (2,), (30,)],
    "build_has_media_image_expression": [("主图_04_1x1.jpg",)],
    "build_read_media_queue_expression": [()],
    "build_attr_block_fragment": [("尺码",), ("颜色分类",)],
    "build_find_exact_candidate_expression": [
        ("女士内衣/男士内衣/家居服>短袜/打底袜/丝袜/美腿袜（新）>一次性袜子",)],
}

NO_ARG_DEFAULT: List[Tuple] = [()]

#: 声明错误码的四种方式。少一种就会漏扫——实测补了三次才扫全。
CODE_DECLARATION_PATTERNS = (
    r"StageOutcome\.failed\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]",
    r"Blocker\(\s*code=\s*['\"]([A-Z][A-Z0-9_]+)['\"]",
    r"super\(\)\.__init__\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]",
    r"^\s*code\s*=\s*['\"]([A-Z][A-Z0-9_]+)['\"]",
)


@dataclass
class CheckResult:
    """一道门的结果。"""

    name: str
    ok: bool
    detail: str = ""
    failures: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail,
                "failures": list(self.failures)}


# ---------------------------------------------------------------------------
# 门 1：契约自检
# ---------------------------------------------------------------------------
def check_contracts() -> CheckResult:
    from .contracts import load_contracts, validate_contracts

    problems = validate_contracts(load_contracts())
    if problems:
        return CheckResult("契约自检", False,
                           "{} 条问题".format(len(problems)), list(problems))
    return CheckResult("契约自检", True, "阶段登记表 / 选择器 / 字段映射自洽")


# ---------------------------------------------------------------------------
# 门 2：构造器冒烟
# ---------------------------------------------------------------------------
def check_builders() -> CheckResult:
    from . import page

    builders = sorted(
        name for name, _ in inspect.getmembers(page, inspect.isfunction)
        if name.startswith("build_")
    )
    failures: List[str] = []
    checked = 0
    for name in builders:
        function = getattr(page, name)
        for args in ARG_CASES.get(name, NO_ARG_DEFAULT):
            checked += 1
            try:
                output = function(*args)
            except TypeError as exc:
                failures.append("{}{} -> 参数不匹配（ARG_CASES 需更新）：{}".format(
                    name, args or "()", exc))
                continue
            except Exception as exc:  # noqa: BLE001
                failures.append("{}{} -> {}: {}".format(
                    name, args or "()", type(exc).__name__, exc))
                continue
            residual = output.count("{{") + output.count("}}")
            if residual:
                failures.append("{}{} -> 残留双花括号 {} 处".format(
                    name, args or "()", residual))

    detail = "{} 个构造器 / {} 次调用".format(len(builders), checked)
    return CheckResult("构造器冒烟", not failures, detail, failures)


# ---------------------------------------------------------------------------
# 门 3：错误目录完备性
# ---------------------------------------------------------------------------
def _iter_package_sources():
    package = Path(__file__).resolve().parent
    for path in sorted(package.glob("*.py")):
        yield path, path.read_text(encoding="utf-8")


def declared_error_codes() -> Dict[str, List[str]]:
    found: Dict[str, List[str]] = {}
    for path, source in _iter_package_sources():
        for pattern in CODE_DECLARATION_PATTERNS:
            flags = re.M if pattern.startswith("^") else 0
            for match in re.finditer(pattern, source, flags):
                found.setdefault(match.group(1), []).append(path.name)
    return found


def check_error_catalog() -> CheckResult:
    from .errors import ERROR_CATALOG

    declared = declared_error_codes()
    missing = sorted(code for code in declared if code not in ERROR_CATALOG)
    failures = [
        "{}（{}）不在错误目录里——界面会显示成「平台返回未归类错误」".format(
            code, "、".join(sorted(set(declared[code]))))
        for code in missing
    ]
    detail = "扫出 {} 个码，目录 {} 条，缺失 {}".format(
        len(declared), len(ERROR_CATALOG), len(missing))
    return CheckResult("错误目录完备性", not missing, detail, failures)


# ---------------------------------------------------------------------------
# 门 4：hard 规则名字覆盖
# ---------------------------------------------------------------------------
def hard_rule_names() -> List[str]:
    """从 ``contracts/rules.json`` 直接读——**不用 dir()**。

    踩过的坑：用 ``dir(rules)`` 枚举会扫出 **0 条**（规则是 ``.get(name)``
    访问的，不是属性），于是「覆盖检查」永远通过。
    """

    path = SUBPROJECT_ROOT / "contracts" / "rules.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = data.get("rules") or data
    return sorted(name for name, spec in rules.items()
                  if isinstance(spec, dict) and spec.get("hard") is True)


def check_hard_rules() -> CheckResult:
    names = hard_rule_names()
    sources = [source for _, source in _iter_package_sources()]
    # 也把 sidecar 算上：规则可能在那里被使用
    sidecar = SUBPROJECT_ROOT.parent / "tauri-app" / "python-sidecar" / "app.py"
    if sidecar.is_file():
        sources.append(sidecar.read_text(encoding="utf-8"))

    failures = []
    for name in names:
        if not any(re.search(r"\b" + re.escape(name) + r"\b", source) for source in sources):
            failures.append("{} 是 hard 规则，但代码里从没出现".format(name))

    detail = "{} 条 hard 规则".format(len(names))
    if not failures:
        detail += "（**仅名字覆盖**；行为验证见 tests/test_every_hard_rule_fires.py）"
    return CheckResult("hard 规则覆盖", not failures, detail, failures)




# ---------------------------------------------------------------------------
# 门 5：陈旧说法
# ---------------------------------------------------------------------------
#: 看起来像「还没做」的说法。
STALE_PHRASES = (
    "尚未实现", "暂未实现", "未启用", "不支持自动", "尚未支持",
    "未开发", "还没实现", "尚未接通",
)

#: 旧的模式名（字符串字面量里出现才算）。
STALE_TOKENS = ("manual_preparation",)

#: 淘宝响应里**硬编码**的布尔字段名 → 允许的固定值。
#:
#: 这一类与「陈旧文案」不同：布尔值不带语气，但一旦写死就会与实际能力脱节
#: （`automatic_publish_ready: False` 就是这么过了两轮没被发现）。
STALE_BOOLEAN_FIELDS = ("ready", "publish", "implemented", "supported")

#: **已知正确**的出现位置：``(文件名, 该行的特征片段)``。
#:
#: ⚠️ **不列清单就会一直红，红了就会被人整体忽略——那比没有这道门更糟。**
#: 每条都要能说出「为什么它是正确的」。匹配用「文件名 + 行内容片段」而不是行号：
#: 行号会随无关改动漂移，清单会因此悄悄失效。
STALE_ALLOWLIST = (
    # ⚠️ **每条都要精确到那一行。**
    #
    # 上一版写的是 `("stages.py", "尚未实现")`——那会豁免 `stages.py` 里
    # **任何**含「尚未实现」的行。实测塞一句假的 `"自动发布尚未实现"` 进去，
    # 这道门照样 `ok=True`。**清单宽到豁免整个文件，就等于没有这道门。**
    #
    # 所以每条都取那一行**独有**的片段。

    # 错误目录里的 `NOT_IMPLEMENTED`：给「没有处理器的阶段」用的守卫。
    # 目前 0 个阶段命中，但守卫本身必须留——没有它，忘了登记处理器会被静默放行。
    ("errors.py", '"NOT_IMPLEMENTED"'),

    # 运行时守卫：阶段没有处理器时显式失败（不静默跳过）。
    ("stages.py", "stage_not_implemented("),

    # CLI 里那句**只在真有未实现阶段时才打印**。
    ("__main__.py", "readiness.unimplemented_stages"),

    # 资料包 manifest：`packet_kind` 描述的是**产物本身**（它确实供人工上传），
    # `platform_published: False` 描述的是「这个包没发布过」——都对。
    #
    # ⚠️ 这里原先写的是 `("desktop.py", '"mode": "manual_preparation",')`。
    # 2026-10-03 把那个键改名了：`mode` 被用了两次、意思不同——
    # `desktop_readiness()` 用它说**应用流水线**的模式（`automated_pipeline`），
    # 而 manifest 又覆盖成 `manual_preparation`，读的人会以为应用还停在人工阶段。
    # 现在 `mode` 保留真实值，资料包的性质由 `packet_kind` 表达。
    ("desktop.py", '"packet_kind": "manual_preparation",'),
    ("desktop.py", '"platform_published": False,'),

    # 任务结果里的 `publish_confirmed` 按设计**永远为 False**，
    # 直到人工在卖家中心核对过。
    ("stages.py", '"publish_confirmed": False,'),
    # 新读取器只覆盖明确的原生控件；复合或未知控件确实需要专用读取器。
    # 此文案只在supportedReader=False的实际失败分支出现，不豁免整个模块。
    ("required_fields.py", "reasons.get(reason,'当前控件类型尚未支持')"),
)

#: 本文件定义这些模式，扫它只会扫到自己。
SCAN_EXCLUDED_FILES = ("selfcheck.py",)


def blank_comments(text: str) -> str:
    """把注释替换成**空行**——躲开「被自己的注释骗」，同时保住行号。

    直接删掉注释行会让行号与真实文件对不上，而**报告里给错行号比不给更糟**。
    """

    result = []
    in_block = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if in_block:
            result.append("")
            if "*/" in line:
                in_block = False
            continue
        if stripped.startswith("/*"):
            result.append("")
            if "*/" not in stripped:
                in_block = True
            continue
        if stripped.startswith(("#", "//", "*")):
            result.append("")
            continue
        result.append(re.sub(r"\s+(#|//).*$", "", line))
    return "\n".join(result)


def _scan_stale_claims():
    """扫子项目的可疑陈旧说法。返回 ``(文件, 行号, 说法, 行内容)`` 列表。"""

    package = Path(__file__).resolve().parent
    found = []
    for path in sorted(package.glob("*.py")):
        if path.name in SCAN_EXCLUDED_FILES:
            continue
        code = blank_comments(path.read_text(encoding="utf-8"))
        for index, line in enumerate(code.splitlines(), 1):
            for phrase in STALE_PHRASES:
                if re.search(r'["\'`][^"\'`]*' + re.escape(phrase), line):
                    found.append((path.name, index, phrase, line.strip()))
                    break
            else:
                for token in STALE_TOKENS:
                    if re.search(r'["\'`]' + re.escape(token) + r'["\'`]', line):
                        found.append((path.name, index, token, line.strip()))
                        break
                else:
                    # 硬编码布尔：字段名里带 ready/publish/implemented/supported
                    match = re.search(
                        r'["\']([A-Za-z_]*(?:' + "|".join(STALE_BOOLEAN_FIELDS)
                        + r')[A-Za-z_]*)["\']\s*:\s*(True|False)\b', line)
                    if match:
                        found.append((path.name, index,
                                      "硬编码布尔 " + match.group(1), line.strip()))
    return found


def _is_allowed(name: str, line: str) -> bool:
    return any(name == allowed_name and fragment in line
               for allowed_name, fragment in STALE_ALLOWLIST)


def check_stale_claims() -> CheckResult:
    findings = _scan_stale_claims()
    new = [item for item in findings if not _is_allowed(item[0], item[3])]

    failures = [
        "{}:{} 说了「{}」——若这是对的，请加进 STALE_ALLOWLIST 并写明理由：{}".format(
            name, line, phrase, text[:70])
        for name, line, phrase, text in new
    ]

    detail = "扫出 {} 处，其中 {} 处在允许清单里".format(
        len(findings), len(findings) - len(new))
    return CheckResult("陈旧说法", not failures, detail, failures)


def stale_allowlist_rot() -> List[str]:
    """允许清单里**已经匹配不到任何东西**的条目。

    留着会悄悄豁免掉将来真正的同类问题，所以它们该被删掉。
    """

    findings = _scan_stale_claims()
    return [
        "{} :: {}".format(name, fragment)
        for name, fragment in STALE_ALLOWLIST
        if not any(item[0] == name and fragment in item[3] for item in findings)
    ]



# ---------------------------------------------------------------------------
# 门 6：动作守卫
# ---------------------------------------------------------------------------
#: 「点按条件挑出来的第一个」——**只认真的被点的那个 `X[0]`**。
#:
#: 取第一个 `[0]` 会误报：运费模板先 `found[0]` 挑**下拉容器**（多个可见容器正常），
#: 真正被点的是 `hits[0]`。
INDEXED_CLICK = re.compile(r"(\w+)\s*\[\s*0\s*\][^;\n]*?\.click\s*\(\s*\)")

#: 精确计数守卫：`x.length === 1` / `x.length !== 1`
EXACT_GUARD = re.compile(r"(\w+)\.length\s*(===|!==|==|!=)\s*1")

#: 下界守卫：`x.length >= 1` / `x.length > 0` —— 选候选时**没有正当用途**
LOWER_BOUND_GUARD = re.compile(r"(\w+)\.length\s*(>=|>|<=|<)\s*(\d+)")

#: 真值守卫：`if (x.length)` —— 同上
TRUTHY_GUARD = re.compile(r"if\s*\(\s*(\w+)\.length\s*\)")


def audit_action_guards():
    """扫所有 ``build_*`` 表达式，返回 ``(passing, bad, unknown)``。

    * ``passing``：被点的变量上有精确计数守卫；
    * ``bad``：有**下界 / 真值**守卫 —— 多命中时会静默挑第一个；
    * ``unknown``：找不到守卫（可能写在别处，**只提示**）。
    """

    import inspect

    from . import page as page_module

    try:
        from .selfcheck import ARG_CASES as _cases  # 自己
    except Exception:  # noqa: BLE001
        _cases = {}

    passing, bad, unknown = [], [], []
    for name, _ in inspect.getmembers(page_module, inspect.isfunction):
        if not name.startswith("build_"):
            continue
        cases = _cases.get(name, [()])
        outputs = []
        for args in cases:
            try:
                outputs.append(getattr(page_module, name)(*args))
            except Exception:  # noqa: BLE001
                continue
        if not outputs:
            continue
        expression = "\n".join(outputs)

        click = INDEXED_CLICK.search(expression)
        if not click:
            continue
        variable = click.group(1)

        exact = [g for g in EXACT_GUARD.finditer(expression) if g.group(1) == variable]
        if exact:
            passing.append("{} :: {}".format(name, exact[0].group(0)))
            continue
        lower = [g for g in LOWER_BOUND_GUARD.finditer(expression) if g.group(1) == variable]
        if lower:
            bad.append("{} :: {} —— 「至少一个就点第一个」，多命中时会**静默选错**；"
                       "改成 === 1 或 !== 1".format(name, lower[0].group(0)))
            continue
        truthy = [g for g in TRUTHY_GUARD.finditer(expression) if g.group(1) == variable]
        if truthy:
            bad.append("{} :: {} —— 真值即点，多命中时会**静默选错**；"
                       "改成 === 1 或 !== 1".format(name, truthy[0].group(0)))
            continue
        unknown.append("{} :: 变量 {}".format(name, variable))

    return passing, bad, unknown


def audit_all_clicks():
    """**每一处 `.click()`** 前面有没有精确守卫（不只是 `X[0]`）。

    点击还有别的形态：``someEl.click()``、``root.querySelector(SEL).click()``
    ——这些没守卫同样会在多命中时点错。门 6 只覆盖 `X[0]` 是不够的。

    ⚠️ 判据演进过三版，每版的问题都记在 ``click_sites`` 的注释里：
    第一版「表达式里任何位置有没有守卫」**没有判别力**；
    第二版按 `if (` 切片**把真正的守卫切掉了**（实测误报两个）；
    第三版看前 600 字符窗口里的**精确**守卫——下界与真值不算。
    """

    import re as _re

    from . import page as page_module
    try:
        from .selfcheck import ARG_CASES as _cases
    except Exception:  # noqa: BLE001
        _cases = {}

    #: **精确守卫**：唯一性 / 存在性 / 可点性。
    #: ⚠️ 不含下界（`>= 1`）——「至少有一个」和「恰好一个」是两回事。
    exact = (
        r"\.length\s*(===|!==|==|!=)\s*1",
        r"getBoundingClientRect\(\)\.height\s*>\s*0",
        r"\.disabled",
        r"if\s*\(\s*!\s*\w+",
        r"reason:\s*'ambiguous'",
        r"reason:\s*'not_found'",
    )

    bare = []
    total_clicks = 0
    for name, _ in __import__("inspect").getmembers(page_module,
                                                    __import__("inspect").isfunction):
        if not name.startswith("build_"):
            continue
        outputs = []
        for args in _cases.get(name, [()]):
            try:
                outputs.append(getattr(page_module, name)(*args))
            except Exception:  # noqa: BLE001
                continue
        if not outputs:
            continue
        expression = "\n".join(outputs)
        for match in _re.finditer(r"\.click\s*\(\s*\)", expression):
            total_clicks += 1
            window = expression[max(0, match.start() - 600):match.start()]
            if not any(_re.search(pattern, window) for pattern in exact):
                head = expression[max(0, match.start() - 46):match.start()]
                bare.append("{} :: 点击前 600 字符内没有精确守卫：…{}".format(
                    name, head.replace("\n", " ").strip()[-60:]))
    return total_clicks, bare


def check_action_guards() -> CheckResult:
    """⚠️ **只对「明确错误」的写法失败**——误报会让人整体忽略这道门。"""

    try:
        passing, bad, unknown = audit_action_guards()
    except Exception as exc:  # noqa: BLE001
        return CheckResult("动作守卫", False,
                           "自检自身抛错：{}: {}".format(type(exc).__name__, exc))

    try:
        total_clicks, bare = audit_all_clicks()
    except Exception as exc:  # noqa: BLE001
        return CheckResult("动作守卫", False,
                           "全点击审计抛错：{}: {}".format(type(exc).__name__, exc))

    failures = list(bad) + bare
    detail = "{} 个精确计数守卫、{} 处点击（{} 处无就近守卫）、{} 个明确错误".format(
        len(passing), total_clicks, len(bare), len(bad))
    if unknown:
        detail += "、{} 个待人工确认（不判失败）".format(len(unknown))
    return CheckResult("动作守卫", not failures, detail, failures)

# ---------------------------------------------------------------------------
# 一起跑
# ---------------------------------------------------------------------------
ALL_CHECKS = (check_contracts, check_builders, check_error_catalog,
              check_hard_rules, check_stale_claims, check_action_guards)


def run_all() -> List[CheckResult]:
    results = []
    for check in ALL_CHECKS:
        try:
            results.append(check())
        except Exception as exc:  # noqa: BLE001
            # 门自己炸了也算失败——不能静默跳过，那会让「没检查」看起来像「没问题」。
            results.append(CheckResult(
                getattr(check, "__name__", "unknown"), False,
                "自检自身抛错：{}: {}".format(type(exc).__name__, exc)))
    return results


def main(argv: Optional[List[str]] = None) -> int:
    """命令行入口，供 ``python -m taobao_publish check`` 调用。"""

    import sys

    as_json = bool(argv and "--json" in argv)
    results = run_all()

    if as_json:
        print(json.dumps({"ok": all(r.ok for r in results),
                          "checks": [r.to_dict() for r in results]},
                         ensure_ascii=False, indent=2))
    else:
        print("=" * 72)
        print("淘宝发布子项目自检")
        print("=" * 72)
        for result in results:
            print("  {} {:<20} {}".format(
                "✓" if result.ok else "✗", result.name, result.detail))
            for failure in result.failures[:12]:
                print("      {}".format(failure))
            if len(result.failures) > 12:
                print("      …（还有 {} 条）".format(len(result.failures) - 12))
        failed = [r for r in results if not r.ok]
        print()
        if failed:
            print("**{} 道门未通过**：{}".format(
                len(failed), "、".join(r.name for r in failed)))
        else:
            # **不写死门的数量**——加一道门就得记得改文案，
            # 忘了的表现是「门都跑完了，输出里的数字还是旧的」。
            print("{} 道门全部通过".format(len(results)))

    return 1 if any(not r.ok for r in results) else 0

# -*- coding: utf-8 -*-
"""扩大扫描：**全部 `.click()`**，不只是 `X[0]`。

第 50 轮的审计只覆盖「点集合第 0 个」的表达式（`X[0].click()`）。
但点击还有别的形态：

* `build_click_unique_text_expression` —— 点唯一的文本匹配；
* `someEl.click()` —— 点一个直接查到的元素；
* `root.querySelector(SEL).click()` —— 点第一个匹配。

**这些如果没守卫，同样会在多命中时静默点错。**

这个脚本把每个含 `.click()` 的表达式列出来，并报出它周围的守卫情况。
⚠️ 只报告，不下结论。**只读。**
"""

from __future__ import annotations

import inspect
import pathlib
import re
import sys

SUBPROJECT = pathlib.Path(__file__).resolve().parent.parent
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page  # noqa: E402

#: **精确守卫**：唯一性 / 存在性 / 可点性。
#:
#: ⚠️ 这里**不能**放 `>= 1` 这类下界——第 50 轮反复纠正过：
#: **「至少有一个」和「恰好一个」是两回事**，
#: 前者在多命中时会静默挑第一个，正是要抓的那个 bug。
EXACT_GUARDS = (
    r"\.length\s*(===|!==|==|!=)\s*1",          # 精确计数
    r"getBoundingClientRect\(\)\.height\s*>\s*0",  # 可见性
    r"\.disabled",                                 # 禁用
    r"if\s*\(\s*!\s*\w+",                       # 取反（没找到就退出）
    r"reason:\s*'ambiguous'",                      # 多命中分支
    r"reason:\s*'not_found'",                      # 没找到分支
)

#: **弱守卫**：看似判断，实际拦不住「多命中挑第一个」。
WEAK_GUARDS = (
    r"\.length\s*(>=|>)\s*\d",                   # 下界
    r"if\s*\(\s*\w+\.length\s*\)",             # 真值
)


def build_expressions():
    from taobao_publish.selfcheck import ARG_CASES

    found = {}
    for name, _ in inspect.getmembers(page, inspect.isfunction):
        if not name.startswith("build_"):
            continue
        outputs = []
        for args in ARG_CASES.get(name, [()]):
            try:
                outputs.append(getattr(page, name)(*args))
            except Exception:  # noqa: BLE001
                continue
        if outputs:
            found[name] = "\n".join(outputs)
    return found


def click_sites(expression):
    """每一处 `.click()` 的 ``(位置, 点的是什么, 在它前面找到的精确守卫)``。

    ⚠️ **不按 `if (` 切片。**

    第一版问「表达式里任何位置有没有守卫」——**宽松到没有判别力**：
    别处有个 `.length !== 1`，所有点击就都被算作有守卫。

    第二版改成「只看最后一个 `if (` 之后」——**又太狠**：
    实测把 `build_set_prop_selected_expression` 真正的守卫切掉了
    （`hits.length !== 1` 在更前面，中间还夹着一个 `if (isSelected === ...)`），
    于是误报。

    这一版折中：看点击**前 600 字符**窗口，要求里面有**精确守卫**。
    下界（`>= 1`）与真值（`if (x.length)`）不算——
    **「至少有一个」和「恰好一个」是两回事。**
    """

    sites = []
    for match in re.finditer(r"\.click\s*\(\s*\)", expression):
        position = match.start()
        head = expression[max(0, position - 46):position].replace("\n", " ").strip()
        window = expression[max(0, position - 600):position]
        guards = [pattern for pattern in EXACT_GUARDS if re.search(pattern, window)]
        sites.append((position, head, guards))
    return sites


def main() -> int:
    expressions = build_expressions()
    rows = []
    for name, expression in sorted(expressions.items()):
        sites = click_sites(expression)
        if not sites:
            continue
        # 这一处点击**自己**有没有守卫
        guarded_sites = [site for site in sites if site[2]]
        unguarded_sites = [site for site in sites if not site[2]]
        rows.append((name, sites, guarded_sites, unguarded_sites))

    print("有 `.click()` 的构造器：{} 个".format(len(rows)))
    print()

    unguarded = [row for row in rows if row[3]]
    clean = [row for row in rows if not row[3]]

    print("==== 每一处点击都有就近守卫的（{} 个）====".format(len(clean)))
    for name, sites, _, _ in clean:
        print("  ✓ {:<46} {} 处点击".format(name, len(sites)))

    print()
    print("==== **有光秃点击的**（{} 个）====".format(len(unguarded)))
    for name, sites, _, bare in unguarded:
        print("  ? {}（{}/{} 处无守卫）".format(name, len(bare), len(sites)))
        for _, head, _ in bare:
            print("      点的是：…{}".format(head[-46:]))
    if not unguarded:
        print("  （无）")

    print()
    print("⚠️ 「没有守卫提示」**不等于**有问题——")
    print("   有些点击本来就该无条件（例如点一个自己刚创建的元素）。逐条人工看。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

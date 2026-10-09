# -*- coding: utf-8 -*-
"""重写动作守卫审计：**「守卫在前」是错的标准。**

## 第一版审计是空的

它判断「守卫模式出现在动作之前」。而当初那个 bug：

```js
if (hits.length >= 1) { hits[0].click(); }     // `hits.length` 命中「守卫」模式，且在点击之前
```

**审计判它通过**——而它正是要抓的那个 bug。

## 正确的标准

点「**按条件挑出来的第一个**」（`X[0].click()`）时，守卫必须是**精确计数**：

| 写法 | 含义 | 判定 |
|---|---|---|
| `hits.length === 1` | 唯一才点 | ✓ |
| `hits.length !== 1` → return | 不唯一就退出 | ✓ |
| `hits.length >= 1` | 至少一个就点第一个 | ❌ **静默选错** |
| `hits.length > 0` | 同上 | ❌ |
| `if (hits.length)` | 真值即点 | ❌ |

**「至少有一个」和「恰好一个」在选候选时是两回事**——
前者在重名/多命中时会悄悄挑第一个。
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

#: 「点按条件挑出来的第一个」——**只认真的被点的那个 `X[0]`**。
#:
#: ⚠️ 第一版写的是 `(\w+)\s*\[\s*0\s*\]`，取**第一个** `X[0]`。
#: 对运费模板那条就取错了：它先 `found[0]` 挑**下拉容器**（多个可见容器正常），
#: 真正被点的是 `hits[0]`。于是审计对着容器变量报误报。
#:
#: 现在要求 `[0]` 与 `.click()` 在**同一个语句**里：
#: `hits[0].click()`、`clickTarget(hits[0]).click()`。
INDEXED_CLICK = re.compile(
    r"(\w+)\s*\[\s*0\s*\][^;\n]*?\.click\s*\(\s*\)"
)

#: 精确计数守卫（好的）
EXACT_GUARD = re.compile(r"(\w+)\.length\s*(===|!==|==|!=)\s*1")

#: 下界守卫（可疑）：至少一个、大于零
LOWER_BOUND_GUARD = re.compile(r"(\w+)\.length\s*(>=|>|<=|<)\s*(\d+)")

#: 真值守卫（可疑）：`if (hits.length)`
TRUTHY_GUARD = re.compile(r"if\s*\(\s*(\w+)\.length\s*\)")


def build_expressions():
    from taobao_publish.selfcheck import ARG_CASES, NO_ARG_DEFAULT

    found = {}
    for name, _ in inspect.getmembers(page, inspect.isfunction):
        if not name.startswith("build_"):
            continue
        cases = ARG_CASES.get(name, NO_ARG_DEFAULT)
        outputs = []
        for args in cases:
            try:
                outputs.append(getattr(page, name)(*args))
            except Exception:  # noqa: BLE001
                continue
        if outputs:
            found[name] = "\n".join(outputs)
    return found


def audit(expressions):
    """返回 ``(passing, suspect)``。"""

    passing, suspect = [], []
    for name, expression in sorted(expressions.items()):
        # 这条表达式点的是哪个「集合的第 0 个」？
        indexed = INDEXED_CLICK.search(expression)
        if not indexed:
            continue
        variable = indexed.group(1)

        # ⚠️ **按被点的变量搜**，不能只取第一个。
        #
        # `if (btns.length !== 1 || visible.length !== 1) { return ... }`
        # ——第一个精确守卫在 `btns` 上，而被点的是 `visible`。
        # 只看第一个会误报。
        exact = [g for g in EXACT_GUARD.finditer(expression) if g.group(1) == variable]
        lower = [g for g in LOWER_BOUND_GUARD.finditer(expression) if g.group(1) == variable]
        truthy = [g for g in TRUTHY_GUARD.finditer(expression) if g.group(1) == variable]

        if exact:
            passing.append((name, variable, exact[0].group(0)))
            continue
        if lower:
            suspect.append((name, variable, "下界守卫 " + lower[0].group(0),
                            "至少一个就点第一个——多命中时会**静默选错**"))
            continue
        if truthy:
            suspect.append((name, variable, "真值守卫 " + truthy[0].group(0),
                            "真值即点——多命中时会**静默选错**"))
            continue
        # 该变量既没有精确守卫也没有可疑守卫：可能是循环里判的，报出来人工看
        suspect.append((name, variable, "找不到该变量的计数守卫",
                        "人工确认：点击前有没有排除「多命中」"))

    return passing, suspect


def main() -> int:
    expressions = build_expressions()
    print("检查 {} 个构造器；其中点「集合第 0 个」的单独看".format(len(expressions)))
    print()

    passing, suspect = audit(expressions)

    print("==== 精确计数守卫（{} 个）====".format(len(passing)))
    for name, variable, guard in passing:
        print("  ✓ {:<46} {} -> {}".format(name, variable, guard))

    print()
    print("==== 可疑（{} 个）====".format(len(suspect)))
    for name, variable, why, detail in suspect:
        print("  ? {:<46} {}：{}".format(name, variable, why))
        print("      {}".format(detail))
    if not suspect:
        print("  （无）")

    print()
    print("⚠️ 这只是清单。**要逐条人工确认**——")
    print("   「找不到该变量的计数守卫」不等于有问题（守卫可能写在别处）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

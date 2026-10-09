# -*- coding: utf-8 -*-
"""钉住前端**不许把非法数值悄悄变成 0**。

踩出来的缺陷：`buildProductRequest` 用 ``Number(sku.price) || 0`` 处理数值，
而同一个文件里的 `buildPayload` 用的是 `parseNumber`（空→报错、非数字→报错、
<=0→报错）。

``Number(x) || 0`` 会把**空值和垃圾都变成 0**——正是「猜一个默认值让它跑通」，
项目红线明确禁止。更糟的是 ``Number("1e999") === Infinity``，
而 ``Infinity || 0`` 仍是 ``Infinity``，会一路写进表单。

这些是**静态**检查（读 Vue 源码），不启动浏览器也不启动前端构建。
"""

from __future__ import annotations

import pathlib
import re
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
PANEL = PROJECT_ROOT / "tauri-app" / "src" / "components" / "TaobaoPublishPanel.vue"


def _strip_line_comments(text: str) -> str:
    """去掉整行注释。

    ⚠️ **检查代码时必须先去掉注释**：这次的第一版检查就被**自己写的注释**命中了
    ——注释里恰好写着「不能写 `Number(x) || 0`」。同一类教训在
    `api.ts` 那边也出现过一次（`options.product` 被子串
    `options.productDir` 命中）。**子串检查要作用在代码上，不是原文上。**
    """

    keep = []
    for line in text.splitlines():
        if line.lstrip().startswith("//") or line.lstrip().startswith("*"):
            continue
        keep.append(line)
    return chr(10).join(keep)


def _builder_source() -> str:
    source = PANEL.read_text(encoding="utf-8")
    start = source.index("function buildProductRequest(")
    end = source.index("async function checkPreparation", start)
    return _strip_line_comments(source[start:end])


class FrontendProductValidationTest(unittest.TestCase):
    def test_builder_uses_the_shared_number_validator(self) -> None:
        builder = _builder_source()
        self.assertIn("parseNumber(", builder, "必须走与 buildPayload 同一套校验")

    def test_builder_never_coerces_garbage_to_zero(self) -> None:
        """``Number(x) || 0`` 这种写法一个都不许有。"""

        builder = _builder_source()
        self.assertNotIn("|| 0", builder, "``|| 0`` 会把空值与垃圾都变成 0")
        # 词边界：parseNumber( 里也含 Number(，不加边界会误报。
        for match in re.finditer(r"(?<![\\w.])Number\\(([^)]*)\\)", builder):
            line = builder[: match.start()].count("\n")
            self.fail(
                "第 {} 行用了裸 Number()：{!r}——请改用 parseNumber".format(
                    line + 1, match.group(0))
            )

    def test_builder_returns_null_when_validation_fails(self) -> None:
        builder = _builder_source()
        self.assertIn("TaobaoProductRequest | null", _signature())
        self.assertIn("Object.keys(fieldErrors.value).length", builder)
        self.assertIn("return null", builder)

    def test_builder_surfaces_the_error_to_the_operator(self) -> None:
        """拒绝之后要**说清为什么**，不能只是静默不发。"""

        builder = _builder_source()
        self.assertIn("actionError.value", builder)

    def test_caller_aborts_before_sending_when_validation_fails(self) -> None:
        """校验没过就**不发请求**——宁可让操作人改对，也不拿编出来的 0 去发布。"""

        source = PANEL.read_text(encoding="utf-8")
        start = source.index("const product = buildProductRequest();")
        segment = source[start:start + 700]
        self.assertIn("if (!product)", segment)
        # 判空必须出现在真正发请求之前
        self.assertLess(segment.index("if (!product)"), segment.index("api.startTaobaoPublish"))

    def test_no_stale_copy_claiming_automation_is_disabled(self) -> None:
        """顶部文案不能再说「自动填表 / 提交未启用」——面板里已经有流水线了。"""

        source = PANEL.read_text(encoding="utf-8")
        self.assertNotIn("自动填表 / 提交未启用", source)
        self.assertIn("dry-run", source)


def _signature() -> str:
    source = PANEL.read_text(encoding="utf-8")
    start = source.index("function buildProductRequest(")
    return source[start:source.index("{", start)]


if __name__ == "__main__":
    unittest.main()

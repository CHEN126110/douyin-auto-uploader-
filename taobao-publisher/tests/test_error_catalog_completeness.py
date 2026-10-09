# -*- coding: utf-8 -*-
"""**每个被抛出的错误码都必须在错误目录里**——新加的码漏了就直接失败。

背景：``describe_error`` 对未知码**静默退化**成 ``PLATFORM_ERROR``：

```python
fallback = ERROR_CATALOG["PLATFORM_ERROR"]
return ErrorSpec(code=code, category=fallback.category,
                 message=fallback.message, hint=fallback.hint)
```

于是 ``TITLE_TOO_LONG`` 在界面上显示成「**平台返回未归类错误**」——
可它根本不是平台错误，是**本地校验失败**。消息与处置建议都是错的。

实测扫出 **9 个**这样的码（本轮补齐）：

```
TITLE_TOO_LONG  TITLE_TOO_SHORT  BRAND_REQUIRED  PRICE_TOO_LOW
FREIGHT_TEMPLATE_NOT_FOUND  SELECTION_NOT_CONFIRMED
READBACK_FAILED  READBACK_UNREADABLE  SELECTOR_AMBIGUOUS
```

这条用例把「不许再漏」钉住。**它检查的是结构（正则匹配声明处），不是原文**——
前几轮反复踩过「检查被注释/文档字符串命中」的坑。
"""

from __future__ import annotations

import pathlib
import re
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish.errors import ERROR_CATALOG  # noqa: E402

PACKAGE = SUBPROJECT / "taobao_publish"

#: 四种声明错误码的方式，缺一不可。
#:
#: 每一条都是补齐过程中发现的——起先只有前两条，于是
#: ``FieldMismatchError`` 这类**用类属性声明**的异常被漏掉，
#: 而 ``SelectorAmbiguousError`` 是补上第 4 条之后才扫出来的。
DECLARATION_PATTERNS = (
    r"StageOutcome\.failed\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]",      # 阶段失败
    r"Blocker\(\s*code=\s*['\"]([A-Z][A-Z0-9_]+)['\"]",           # 阻塞项
    r"super\(\)\.__init__\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]",       # 异常类（旧写法）
    r"^\s*code\s*=\s*['\"]([A-Z][A-Z0-9_]+)['\"]",                # 异常类的类属性
)


def declared_codes() -> dict:
    found: dict = {}
    for path in sorted(PACKAGE.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for pattern in DECLARATION_PATTERNS:
            flags = re.M if pattern.startswith("^") else 0
            for match in re.finditer(pattern, source, flags):
                found.setdefault(match.group(1), set()).add(path.name)
    return found


class ErrorCatalogCompletenessTest(unittest.TestCase):
    def test_every_declared_code_is_in_the_catalog(self) -> None:
        declared = declared_codes()
        missing = sorted(code for code in declared if code not in ERROR_CATALOG)
        self.assertEqual(
            missing, [],
            "以下错误码被抛出但不在 ERROR_CATALOG 里——界面会把它显示成"
            "「平台返回未归类错误」，消息和处置建议都是错的：\n  "
            + "\n  ".join("{}（{}）".format(c, "、".join(sorted(declared[c]))) for c in missing),
        )

    def test_detector_actually_finds_codes(self) -> None:
        """防「检测器坏了所以永远通过」——它得真找到东西。"""

        declared = declared_codes()
        self.assertGreater(len(declared), 20, "检测器至少该扫出二十几个码")
        for expected in ("WRITE_NOT_AUTHORIZED", "FIELD_MISMATCH", "CANDIDATE_NOT_FOUND"):
            self.assertIn(expected, declared, "检测器漏了 {}".format(expected))

    def test_unknown_code_message_says_it_is_unknown(self) -> None:
        """未知码**不能**借别人的消息冒充。

        这条防的是「目录写错了但没人发现」——真出现未知码时，
        文案本身就该说明它是未知的，而不是伪装成一个平台错误。
        """

        from taobao_publish.errors import describe_error

        spec = describe_error("THIS_CODE_IS_NOT_IN_THE_CATALOG")
        self.assertEqual(spec.code, "THIS_CODE_IS_NOT_IN_THE_CATALOG")
        # 回落文案要能看出「这是个没归类的码」，而不是一句具体的错误说明
        self.assertIn("未归类", spec.message)

    def test_catalog_entries_have_message_and_hint(self) -> None:
        """每个条目都要有中文消息与处置建议——目录存在的意义就是这个。"""

        for code, spec in ERROR_CATALOG.items():
            with self.subTest(code=code):
                self.assertTrue(spec.message.strip(), "{} 没有消息".format(code))
                self.assertTrue(spec.hint.strip(), "{} 没有处置建议".format(code))
                self.assertTrue(spec.category.strip(), "{} 没有分类".format(code))


if __name__ == "__main__":
    unittest.main()

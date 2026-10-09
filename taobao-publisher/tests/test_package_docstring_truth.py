# -*- coding: utf-8 -*-
"""**文档字符串不许说「没实现」**——东西已经实现了。

`scripts/scan-stale-claims.py` 扫出来的（本轮修掉的三处）：

| 位置 | 说 | 实际 |
|---|---|---|
| `__init__.py` | 真实写平台**尚未实现** | 已实现，10 个阶段实机跑通 |
| `__init__.py` | `publish_route_ready` **目前为 False** | 是 `True` |
| `pipeline.py` | `upload_images` 与 `fill_skus` **还没实现** | 都已实现并实机跑过 |

这与前两轮修的东西是同一类：**代码改了，说代码的话没改。**
只不过前两轮是 JSON 字段与前端守卫，这次是文档。

⚠️ 但**不能一刀切**：有些「尚未实现」是**正确的**——
`NOT_IMPLEMENTED` 错误码（给没有处理器的阶段用）、
`stages.py` 的运行时守卫、`__main__.py` 里只在真有未实现阶段时才打印的那句。
所以这里只钉**本轮修掉的那三处具体说法**。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

INIT = SUBPROJECT / "taobao_publish" / "__init__.py"
PIPELINE = SUBPROJECT / "taobao_publish" / "pipeline.py"
ERRORS = SUBPROJECT / "taobao_publish" / "errors.py"


class PackageDocstringTruthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.init_source = INIT.read_text(encoding="utf-8")

    def test_does_not_claim_the_write_route_is_unimplemented(self) -> None:
        """包文档是读代码的人第一眼看到的东西，它过期最误导。"""

        self.assertNotIn("真实写平台尚未实现", self.init_source)
        self.assertIn("11 个阶段全部已实现", self.init_source)

    def test_does_not_claim_publish_route_ready_is_false(self) -> None:
        self.assertNotIn("目前为 False", self.init_source)
        self.assertIn("现在为 True", self.init_source)

    def test_mentions_the_submit_caveat(self) -> None:
        """「全部已实现」也要带上边界——`submit` 未实机执行。"""

        self.assertIn("submit", self.init_source)
        self.assertIn("未实机执行", self.init_source)

    def test_route_ready_docstring_does_not_claim_stages_missing(self) -> None:
        source = PIPELINE.read_text(encoding="utf-8")
        self.assertNotIn("两个阶段**还没实现**", source)
        # 仍然要保留「本属性不等于能发布」这层意思
        self.assertIn("要判断「现在能不能一键发布」", source)


class ErrorCatalogStaleClaimTest(unittest.TestCase):
    def test_media_selection_code_says_it_should_not_recur(self) -> None:
        """`MEDIA_SELECTION_NOT_IMPLEMENTED` 现在**没有任何地方会抛**。

        选图入位已实现（点卡片里的 label）。保留这个码是当**回归信号**用的：
        它若再次出现，说明选图退化了。文案必须说清这一点，
        而不是继续声称「尚未实现」。
        """

        source = ERRORS.read_text(encoding="utf-8")
        block = source.split('"MEDIA_SELECTION_NOT_IMPLEMENTED"', 1)[1].split("),", 1)[0]
        self.assertIn("不应该再出现", block)
        self.assertIn("退化", block)

    def test_nothing_raises_the_media_selection_code(self) -> None:
        """钉住「没有任何地方会抛」这个前提——一旦有人开始抛它，
        上面那条文案的语义就变了，这条会提醒。"""

        import re

        package = SUBPROJECT / "taobao_publish"
        raisers = []
        for path in package.glob("*.py"):
            if path.name == "errors.py":
                continue
            source = path.read_text(encoding="utf-8")
            if re.search(r"failed\(\s*[\"']MEDIA_SELECTION_NOT_IMPLEMENTED", source):
                raisers.append(path.name)
        self.assertEqual(raisers, [],
                         "有人开始抛这个码了——请同步更新它的文案与上面的用例")


if __name__ == "__main__":
    unittest.main()

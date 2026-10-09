# -*- coding: utf-8 -*-
"""终态验证脚本要**保住可复跑**——它回答的是「交付物到底行不行」。

## 它做什么

1. 走**生产路径**（界面 → Sidecar → 流水线）跑一遍，`stop_before_submit=True`；
2. 然后读**平台侧**的可见状态——**比我们自己的核对更权威**。

第 73 轮就是靠第 2 步发现「至少有一个sku的价格大于0」的：
**平台的报错比我们的核对更能说明问题。**

## 实测（2026-10-03）

```
status = succeeded    publish_confirmed = False    blockers = 0
10 个阶段全部 [OK]
readback: 9 项全部一致（…、主图内容、SKU 规格值、SKU 价格、运费模板）
```

平台侧：

```
SKU 行： [{'price': '16.80', 'stock': '200'}]
提交按钮： present=True disabled=False visible=True
疑似校验错误（1 条）：宝贝详情图【高/宽≤ 2】，超出将被裁剪。建议宽度≥1440像素
```

那一条是**建议**（「建议宽度≥1440」），不是阻塞项。
"""
from __future__ import annotations

import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
SCRIPT = SUBPROJECT / "scripts" / "verify-final-state-live.py"


class FinalStateScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = SCRIPT.read_text(encoding="utf-8")

    def test_it_uses_the_production_path(self) -> None:
        """必须走 Sidecar 的 HTTP 接口，而不是直接调流水线——
        那才验得到「界面 → Sidecar → 流水线」这条真路径。"""

        self.assertIn("/api/taobao/publish/start", self.source)
        self.assertIn("/api/taobao/publish/status/", self.source)

    def test_it_stops_before_submit(self) -> None:
        """⚠️ **`stop_before_submit` 必须是 True。**

        这个脚本是**验证**用的，不是提交通道。写错一个值就把商品发出去了。
        """

        self.assertIn('"stop_before_submit": True', self.source)
        self.assertNotIn('"stop_before_submit": False', self.source)

    def test_it_checks_the_platform_side_not_just_ours(self) -> None:
        """**平台侧的报错比我们自己的核对更权威**（第 73 轮的教训）。"""

        self.assertIn("平台侧的可见状态", self.source)
        self.assertIn("read_sku_row_numbers", self.source)

    def test_it_classifies_messages_rather_than_dumping_them(self) -> None:
        """要**分类**（疑似校验错误 vs 说明文字），不能一股脑列出来。"""

        self.assertIn("ERROR_MARKERS", self.source)
        self.assertIn("疑似", self.source)

    def test_it_reads_the_submit_button_state(self) -> None:
        self.assertIn("read_submit_state", self.source)

    def test_the_import_path_points_at_the_package_root(self) -> None:
        """`scripts/` 的上一级才是 `taobao_publish` 包所在。"""

        self.assertIn("parents[1]", self.source)


class RestrictiveErrorMarkersTest(unittest.TestCase):
    """判定「这是校验错误」的词表要**保守**——宽了会误报，误报的检查器会被忽略。"""

    def test_markers_do_not_include_generic_words(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        start = source.index("ERROR_MARKERS = (")
        end = source.index(")", start)
        block = source[start:end]
        # 这些词太泛，任何提示都可能命中
        for too_generic in ('"请"', '"不"', '"图"', '"建议"'):
            with self.subTest(word=too_generic):
                self.assertNotIn(too_generic, block)


if __name__ == "__main__":
    unittest.main()

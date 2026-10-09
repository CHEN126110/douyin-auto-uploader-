# -*- coding: utf-8 -*-
"""两件小而实的事的守卫。

## 一、界面要有「品牌必填」的提示

实测（第 58 轮）：不给品牌时 `select_category` 报 `BRAND_REQUIRED` 并停下——
契约记着「选完类目后还会要求选品牌，未选品牌时『确认，下一步』保持 disabled」。

界面的类目属性区设计得不错（placeholder 写着 `例如 品牌`），
但**没说"不填就进不了下一步"**——用户会在第 3 个阶段（共 11 个）才撞上失败。

**不预填**：契约里没有「品牌」的映射条目，`无品牌/无注册商标` 是
`selectors.json` 里的**页面事实**、不是字段映射。悄悄预填等于替用户做决定。

## 二、新鲜度检查要覆盖前端 `dist/`

Sidecar 那个「产物比源码旧」的坑，前端也有：改了 `.vue` 不跑 `npm run build`，
**界面看到的还是旧前端**——而没有任何东西会报错。

实测它会真的报：

```
[陈旧] 前端源码比 dist 新 76 分钟——**界面看到的是旧前端**
```
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import tempfile
import time
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

PANEL = REPO_ROOT / "tauri-app" / "src" / "components" / "TaobaoPublishPanel.vue"
CHECK = SUBPROJECT / "scripts" / "check-sidecar-freshness.py"

spec = importlib.util.spec_from_file_location("freshness_again", CHECK)
freshness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(freshness)


class BrandHintTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = PANEL.read_text(encoding="utf-8")

    def test_hint_exists(self) -> None:
        self.assertIn("brand-hint", self.source)

    def test_hint_says_the_next_button_stays_disabled(self) -> None:
        """要说清**后果**，不是只说「请填品牌」。"""

        self.assertIn("确认，下一步", self.source)
        self.assertIn("不可点", self.source)

    def test_hint_gives_the_standard_candidate(self) -> None:
        """要给出平台标准候选原文——操作人照着填就能命中。"""

        self.assertIn("无品牌/无注册商标", self.source)
        self.assertIn("平台标准候选", self.source)

    def test_hint_says_the_pipeline_will_not_guess(self) -> None:
        self.assertIn("未指定品牌时默认选择", self.source)
        self.assertIn("指定品牌会按原值精确匹配", self.source)
        self.assertIn("不会替你猜其他品牌", self.source)

    def test_brand_is_not_silently_prefilled(self) -> None:
        """⚠️ **不许悄悄预填**：`无品牌/无注册商标` 是页面事实，不是字段映射。

        预填等于替用户做决定；提示 + 可编辑才是对的。
        """

        # 初始草稿里不该带 props
        self.assertIn("props: [],", self.source)
        self.assertNotIn("props: [{ prop_name: '品牌'", self.source)


class FrontendFreshnessTest(unittest.TestCase):
    def test_check_frontend_reports_stale_for_synthetic_case(self) -> None:
        """合成一组时间戳：源码比 dist 新 → 必须报陈旧。"""

        with tempfile.TemporaryDirectory(prefix="fe-") as directory:
            root = pathlib.Path(directory)
            src = root / "src"
            dist = root / "dist"
            src.mkdir()
            dist.mkdir()
            (src / "a.vue").write_text("x", encoding="utf-8")
            (dist / "a.js").write_text("y", encoding="utf-8")
            os.utime(dist / "a.js", (time.time() - 600, time.time() - 600))
            os.utime(src / "a.vue", (time.time(), time.time()))

            original_src, original_dist = freshness.FRONTEND_SRC, freshness.FRONTEND_DIST
            try:
                freshness.FRONTEND_SRC = src
                freshness.FRONTEND_DIST = dist
                verdict, source_time, dist_time, _ = freshness.check_frontend()
            finally:
                freshness.FRONTEND_SRC, freshness.FRONTEND_DIST = original_src, original_dist

        self.assertEqual(verdict, "stale")
        self.assertGreater(source_time, dist_time)

    def test_check_frontend_reports_no_dist(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fe2-") as directory:
            root = pathlib.Path(directory)
            src = root / "src"
            src.mkdir()
            (src / "a.vue").write_text("x", encoding="utf-8")

            original_src, original_dist = freshness.FRONTEND_SRC, freshness.FRONTEND_DIST
            try:
                freshness.FRONTEND_SRC = src
                freshness.FRONTEND_DIST = root / "nope"
                verdict, _, _, _ = freshness.check_frontend()
            finally:
                freshness.FRONTEND_SRC, freshness.FRONTEND_DIST = original_src, original_dist

        self.assertEqual(verdict, "no-dist")

    def test_frontend_paths_point_at_the_right_places(self) -> None:
        self.assertTrue(str(freshness.FRONTEND_SRC).endswith("tauri-app\\src"))
        self.assertTrue(str(freshness.FRONTEND_DIST).endswith("tauri-app\\dist"))

    def test_report_gives_the_build_command(self) -> None:
        source = CHECK.read_text(encoding="utf-8")
        self.assertIn("npm run build", source)
        self.assertIn("刷新界面", source)

    def test_fresh_path_also_checks_the_frontend(self) -> None:
        """⚠️ 新鲜时**也要**查前端——否则前端陈旧会被漏掉。"""

        source = CHECK.read_text(encoding="utf-8")
        # 内容哈希新鲜那条分支必须接着查前端
        marker = "[新鲜] 内容哈希与构建时一致"
        index = source.index(marker)
        following = source[index:index + 300]
        self.assertIn("check_frontend_and_report", following)


if __name__ == "__main__":
    unittest.main()

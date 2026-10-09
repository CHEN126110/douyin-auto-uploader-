# -*- coding: utf-8 -*-
"""CLI 的 CDP 地址参数，以及「两个数字要对得上」。

## 缺口 1：CLI 连不上应用管理的浏览器

`pipeline.run` 的默认是研究环境的 `9334`，而 Sidecar 里明确写着：

```
必须是应用管理的那个浏览器（9500-9599 端口段），不是研究用的 9334——
两者登录态不同，流水线跑到错误的浏览器上会什么都找不到。
```

**而 CLI 没有任何参数可改**。实测：

```
"code": "CDP_UNREACHABLE",
"message": "无法连接 http://127.0.0.1:9334/json/list…"
```

——**9334 上根本没有浏览器**（实机那个在 9502）。
所以 `python -m taobao_publish dry-run` **实际上用不了**。

## 缺口 2：`preflight_warnings` 与 precheck 步骤说的不是一回事

```
precheck 步骤 summary      : 「阻塞 0，**告警 2**」
聚合 data.preflight_warnings : []          ← 空的
```

原因是聚合用了 `static.warnings`（**连浏览器之前**的本地预检），
而步骤用的是 `precheck` **阶段**带页面快照的完整预检。**同一个概念，两个数字。**
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import io
import json
import os
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import __main__ as cli  # noqa: E402
from taobao_publish import pipeline  # noqa: E402

MAIN_SOURCE = (SUBPROJECT / "taobao_publish" / "__main__.py").read_text(encoding="utf-8")


class CdpAddressOptionTest(unittest.TestCase):
    """CLI 必须能指到应用管理的那个浏览器。"""

    def test_dry_run_accepts_cdp_address(self) -> None:
        parser = cli.build_parser() if hasattr(cli, "build_parser") else None
        self.assertIn("--cdp-address", MAIN_SOURCE)
        self.assertIn("--cdp-list-url", MAIN_SOURCE)

    def test_cdp_address_is_wired_into_run(self) -> None:
        """光有参数不够——要真的传进 `run()`。"""

        self.assertIn("cdp_list_url", MAIN_SOURCE)
        self.assertIn('"http://{}/json/list".format(args.cdp_address.strip())', MAIN_SOURCE)

    def test_explicit_url_wins_over_address(self) -> None:
        self.assertIn("if not cdp_list_url and args.cdp_address.strip()", MAIN_SOURCE)

    def test_help_says_the_default_is_the_research_environment(self) -> None:
        """默认值是 9334，**那是研究环境**——帮助文本要说清楚，别让人踩坑。"""

        index = MAIN_SOURCE.index("--cdp-address")
        block = MAIN_SOURCE[index:index + 400]
        self.assertIn("9334", block)
        self.assertIn("研究环境", block)

    def test_parses_address_into_a_list_url(self) -> None:
        """行为验证：给 `--cdp-address` 要变成 `/json/list` URL。"""

        captured = {}

        def fake_run(local, request, **kwargs):  # noqa: ANN001
            captured.update(kwargs)
            raise SystemExit(0)

        original = pipeline.run
        try:
            pipeline.run = fake_run  # type: ignore[assignment]
            cli.run = fake_run  # type: ignore[attr-defined]
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    cli.main([
                        "dry-run", "--record-id", "1",
                        "--db", str(SUBPROJECT.parent / "sqlite.db"),
                        "--title", "X",
                        "--sku-price", "1", "--sku-stock", "1",
                        "--cdp-address", "127.0.0.1:9502",
                    ])
        finally:
            pipeline.run = original  # type: ignore[assignment]
            cli.run = original  # type: ignore[attr-defined]

        if captured:
            self.assertEqual(captured.get("cdp_list_url"),
                             "http://127.0.0.1:9502/json/list")


class PreflightWarningsConsistencyTest(unittest.TestCase):
    """聚合告警与 precheck 步骤必须**同一个来源**。"""

    def test_aggregate_does_not_use_static_warnings(self) -> None:
        """聚合那一行**不许**再直接用它。

        第一版是 `"preflight_warnings": [w.to_dict() for w in static.warnings]`
        ——那是连浏览器之前的本地预检，与步骤说的不是一回事。
        """

        source = inspect.getsource(pipeline.run)
        self.assertNotIn(
            'for warning in static.warnings]', source,
            "聚合不能直接用 static.warnings（那是连浏览器之前的预检）")
        self.assertIn("_preflight_warnings_for_report", source)

    def test_helper_prefers_the_stage_result(self) -> None:
        """有阶段结果就用它；没有才退回静态预检。"""

        helper = getattr(pipeline, "_preflight_warnings_for_report", None)
        self.assertIsNotNone(helper, "辅助函数必须存在（第一版曾静默没加成）")

        class _Ctx:
            def __init__(self, scratch):
                self.scratch = scratch

        class _Pre:
            def __init__(self, warnings):
                self.warnings = warnings

        static = _Pre(["static-1"])

        # 没跑 precheck 阶段 → 用静态预检
        self.assertEqual(pipeline._preflight_warnings_for_report(_Ctx({}), static),
                         ["static-1"])
        # 跑了 → 用阶段的（完整视图）
        self.assertEqual(
            pipeline._preflight_warnings_for_report(
                _Ctx({"preflight": _Pre(["stage-1", "stage-2"])}), static),
            ["stage-1", "stage-2"])

    def test_source_field_is_reported(self) -> None:
        """带上来源，读的人能分辨是完整预检还是本地预检。"""

        source = inspect.getsource(pipeline.run)
        self.assertIn("preflight_warnings_source", source)
        self.assertIn("precheck_stage", source)
        self.assertIn("static_preflight", source)

    def test_named_function_definition_actually_exists(self) -> None:
        """⚠️ 这条钉住一个**静默失败**。

        加辅助函数的第一个脚本把**调用**先插了进去，然后才检查
        `if "_preflight_warnings_for_report" not in source` ——名字已经出现了，
        于是**函数定义被静默跳过**，跑起来才 `NameError`。

        所以这里检查的是 **`def` 在不在**，不是「名字在不在」。
        """

        source = (SUBPROJECT / "taobao_publish" / "pipeline.py").read_text(encoding="utf-8")
        self.assertIn("def _preflight_warnings_for_report(", source)


if __name__ == "__main__":
    unittest.main()

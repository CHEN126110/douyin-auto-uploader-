# -*- coding: utf-8 -*-
"""**冻结产物比源码旧** —— 一种没有报错的脱节。

## 实测（2026-10-03）

```
python-backend.exe      17:52:36   （冻结时间）
taobao_publish/page.py  20:03:45   （源码修改时间）
→ 源码比产物新 146 分钟
```

运行中的 Sidecar 带着约两小时的陈旧代码，包括第 56–59 轮的全部修复。
表现是 `/api/taobao/readiness` 返回**第 42 轮就已改掉**的值
（`mode: manual_preparation`、`automatic_publish_ready: False`）。

**界面因此跑着一个"填不了属性、传不了图"的版本，而没有任何东西发现。**

这与本会话反复碰到的「代码改了、话没改」是同一类，只是这次"话"是**打包产物**。

## 为什么不做成门

它会把「开发中源码比产物新」也判红——**那是常态，不是问题**。
所以定位是**脚本 + 测试**（人工在交付前跑一次），而不是每次都跑的门。

*要*修的时候它会告诉你命令。
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import time
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

SCRIPT = SUBPROJECT / "scripts" / "check-sidecar-freshness.py"

spec = importlib.util.spec_from_file_location("sidecar_freshness", SCRIPT)
freshness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(freshness)


class FreshnessDetectorTest(unittest.TestCase):
    """判据本身要能分辨「陈旧」与「新鲜」。"""

    def test_newest_mtime_picks_the_latest_file(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="fresh-") as directory:
            root = pathlib.Path(directory)
            old = root / "old.py"
            new = root / "new.py"
            old.write_text("x", encoding="utf-8")
            new.write_text("y", encoding="utf-8")
            os.utime(old, (time.time() - 3600, time.time() - 3600))
            # ⚠️ **时间戳要在 `with` 里取**：`TemporaryDirectory` 退出时就删了，
            # 在外面 `new.stat()` 会 FileNotFoundError（第一版就是这么挂的）。
            expected = new.stat().st_mtime
            stamp, where = freshness.newest_mtime([root])
        self.assertAlmostEqual(stamp, expected, delta=5)
        self.assertTrue(where.endswith("new.py"))

    def test_missing_paths_are_skipped(self) -> None:
        stamp, where = freshness.newest_mtime([pathlib.Path("C:/definitely/not/here")])
        self.assertEqual(stamp, 0.0)

    def test_watched_paths_cover_the_taobao_package(self) -> None:
        """打包进去的东西都要在看守范围里，否则「陈旧」判不出来。"""

        names = {str(p.relative_to(REPO_ROOT)) for p in freshness.WATCHED}
        self.assertIn("taobao-publisher\\taobao_publish", names)

    def test_exe_path_points_at_the_packaged_artifact(self) -> None:
        self.assertTrue(str(freshness.EXE).endswith("sidecar\\python-backend.exe"))

    def test_script_explains_the_rebuild_command(self) -> None:
        """报陈旧时要**给出修的命令**，否则看的人还得自己找。"""

        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("build_sidecar.py", source)

    def test_script_documents_why_it_is_not_a_gate(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("人工", source)
        self.assertIn("陈旧", source)


class SourceIsFresherDetectionTest(unittest.TestCase):
    def test_detects_staleness_with_synthetic_timestamps(self) -> None:
        """合成一组时间戳，验证「源码更新 → 报陈旧」。"""

        import tempfile

        with tempfile.TemporaryDirectory(prefix="fresh2-") as directory:
            root = pathlib.Path(directory)
            source = root / "src"
            source.mkdir()
            code = source / "a.py"
            code.write_text("x", encoding="utf-8")
            exe = root / "python-backend.exe"
            exe.write_text("bin", encoding="utf-8")

            os.utime(exe, (time.time() - 600, time.time() - 600))
            os.utime(code, (time.time(), time.time()))

            stamp, where = freshness.newest_mtime([source])
            self.assertGreater(stamp, exe.stat().st_mtime,
                               "合成的场景应当被判为陈旧")
            self.assertTrue(where.endswith("a.py"))


if __name__ == "__main__":
    unittest.main()

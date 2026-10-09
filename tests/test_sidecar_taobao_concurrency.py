# -*- coding: utf-8 -*-
"""Sidecar 淘宝发布任务的**并发准入**测试。

审查发现的问题：`/api/taobao/publish/start` 无条件创建任务并立刻启动 worker。
两个任务驱动的是**同一个浏览器页面**（同一个 CDP target），会互相把页面
导航来导航去、交叉写表单，而各自还在按自己的期望值回读——可能拿 A 的期望值
去核对 B 写出来的页面。若 `submit` 已授权，两个任务甚至可能都去点提交。

这里只做**静态**检查（不启动 Flask、不碰平台），钉住三件事：

1. 有「已有任务在进行中」的检查；
2. 检查与插入**在同一把锁里**（分开写就是 TOCTOU 竞态）；
3. 冲突时返回 409 并说清是哪个任务占着。
"""

from __future__ import annotations

import ast
import pathlib
import re
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "tauri-app" / "python-sidecar" / "app.py"


def _start_function_source() -> str:
    source = APP_PATH.read_text(encoding="utf-8")
    start = source.index("def taobao_publish_start():")
    end = source.index("@app.get('/api/taobao/publish/status", start)
    return source[start:end]


class TaobaoPublishConcurrencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.body = _start_function_source()

    def test_refuses_to_start_while_another_task_is_in_flight(self) -> None:
        self.assertIn("in_flight", self.body, "必须有「已有任务在跑」的检查")
        self.assertIn("'pending'", self.body)
        self.assertIn("'running'", self.body)

    def test_conflict_returns_409_with_the_blocking_task_id(self) -> None:
        """409 Conflict 是这里唯一说得通的语义；文案要让人知道**是谁**占着。"""

        self.assertIn("409", self.body)
        self.assertIn("busy.get('task_id')", self.body)
        self.assertIn("请等它结束后再发起", self.body)

    def test_check_and_insert_share_one_lock_block(self) -> None:
        """**检查与插入必须在同一把锁里。**

        分开写就是 TOCTOU：两个并发请求可以同时通过检查，然后都插入，
        于是两个任务照样一起跑。这条用缩进解析来验证，
        而不是靠字面顺序——顺序对但锁不同锁的话，照样是竞态。
        """

        tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        function = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "taobao_publish_start"
        )

        found = False
        for node in ast.walk(function):
            if not isinstance(node, ast.With):
                continue
            # 找到 `with _taobao_tasks_lock:` 这个块
            items = [getattr(item.context_expr, "id", None) for item in node.items]
            if "_taobao_tasks_lock" not in items:
                continue
            segment = ast.get_source_segment(
                APP_PATH.read_text(encoding="utf-8"), node) or ""
            if "in_flight" in segment and "_taobao_tasks[task_id] = task" in segment:
                found = True
                break
        self.assertTrue(
            found,
            "「查 in_flight」与「插入任务」必须在**同一个** _taobao_tasks_lock 块里",
        )

    def test_admission_check_is_not_a_separate_top_level_block(self) -> None:
        """反面：不允许出现「先单独加锁查一次、出了锁再单独加锁插一次」的写法。"""

        occurrences = len(re.findall(r"with _taobao_tasks_lock:", self.body))
        self.assertEqual(
            occurrences, 1,
            "start 里只应有一处 _taobao_tasks_lock 块（查+插合并后的那一处），"
            "实际 {} 处——分开写就是竞态".format(occurrences),
        )


if __name__ == "__main__":
    unittest.main()

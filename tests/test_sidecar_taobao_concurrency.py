# -*- coding: utf-8 -*-
"""Sidecar 淘宝发布任务的**并发准入**测试。

审查发现的问题：`/api/taobao/publish/start` 无条件创建任务并立刻启动 worker。
两个任务驱动的是**同一个浏览器页面**（同一个 CDP target），会互相把页面
导航来导航去、交叉写表单，而各自还在按自己的期望值回读——可能拿 A 的期望值
去核对 B 写出来的页面。若 `submit` 已授权，两个任务甚至可能都去点提交。

钉住三件事：

1. 有「已有任务在进行中」的检查；
2. 检查与插入**在同一把锁里**（分开写就是 TOCTOU 竞态）；
3. 冲突时返回 409 并说清是哪个任务占着。

前两件是结构性不变量，用 AST 读源码验证（接口在 ``src/sidecar/taobao_routes.py``）；
第三件直接用真实的 Blueprint 发请求验证。

批量发布 ``/api/taobao/publish/start-all`` 是同一套规则（它以前什么准入检查都没有，见 ``TaobaoBatchPublishAdmissionTest``）：
先过账户切换互斥（不得在 ``service.lock`` 里），再在同一把 ``service.lock`` 里「查 + 插」。
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from sidecar_function_source import function_source, module_text  # noqa: E402
from taobao_test_support import make_app, make_record_model, make_service  # noqa: E402


def _start_function_source() -> str:
    """取 `taobao_publish_start` 自己的源码（按函数名用 AST 取，不按文本位置切片）。

    以前按文本截到下一个 `@app.get('/api/taobao/publish/status` 为止，两个路由之间后来插入了
    批量发布 worker 等函数，截出来的区间里混进了别的函数的 `with _taobao_tasks_lock:`，
    「只有一处锁块」的反面断言就误报失败。直接取函数本身，才是在检查这个函数。
    """

    return function_source("taobao_publish_start", within="taobao_routes.py")


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

        source = module_text("taobao_routes.py")
        function = next(
            node for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.FunctionDef) and node.name == "taobao_publish_start"
        )

        found = False
        for node in ast.walk(function):
            if not isinstance(node, ast.With):
                continue
            # 找到 `with service.lock:` 这个块
            items = [ast.unparse(item.context_expr) for item in node.items]
            if "service.lock" not in items:
                continue
            segment = ast.get_source_segment(source, node) or ""
            if "in_flight" in segment and "service.tasks[task_id] = task" in segment:
                found = True
                break
        self.assertTrue(
            found,
            "「查 in_flight」与「插入任务」必须在**同一个** service.lock 块里",
        )

    def test_admission_check_is_not_a_separate_top_level_block(self) -> None:
        """反面：不允许出现「先单独加锁查一次、出了锁再单独加锁插一次」的写法。"""

        source = module_text("taobao_routes.py")
        function = next(
            node for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.FunctionDef) and node.name == "taobao_publish_start"
        )
        occurrences = sum(
            1 for node in ast.walk(function)
            if isinstance(node, ast.With) and any(ast.unparse(item.context_expr) == "service.lock" for item in node.items)
        )
        self.assertEqual(
            occurrences, 1,
            "start 里只应有一处 service.lock 块（查+插合并后的那一处），"
            "实际 {} 处——分开写就是竞态".format(occurrences),
        )


def _function_node(name: str) -> tuple[str, ast.FunctionDef]:
    source = module_text("taobao_routes.py")
    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    return source, function


class TaobaoBatchPublishAdmissionTest(unittest.TestCase):
    """批量发布（``/api/taobao/publish/start-all``）与单个发布是同一套准入规则。

    它以前既不查「已有任务在跑」、也不过账户切换互斥：有任务在跑时照样能再起一个批量任务，
    两个流水线会驱动同一个浏览器页面。这里用 AST 钉住结构（与 ``taobao_publish_start`` 的钉法一致），
    行为在 ``test_taobao_routes.py`` 里用真实的 Blueprint 验证。
    """

    NAME = "taobao_publish_start_all"

    def setUp(self) -> None:
        self.source, self.function = _function_node(self.NAME)
        self.body = function_source(self.NAME, within="taobao_routes.py")

    def _service_lock_blocks(self) -> list[ast.With]:
        return [
            node for node in ast.walk(self.function)
            if isinstance(node, ast.With) and any(ast.unparse(item.context_expr) == "service.lock" for item in node.items)
        ]

    def test_refuses_to_start_while_another_task_is_in_flight(self) -> None:
        for needle in ("in_flight", "'pending'", "'running'", "409", "busy.get('task_id')", "请等它结束后再发起"):
            self.assertIn(needle, self.body, needle)

    def test_check_and_insert_share_one_lock_block(self) -> None:
        blocks = self._service_lock_blocks()
        self.assertEqual(len(blocks), 1, "start-all 里只应有一处 service.lock 块（查+插合并后的那一处）")
        segment = ast.get_source_segment(self.source, blocks[0]) or ""
        self.assertIn("in_flight", segment, "「查 in_flight」必须在 service.lock 块里")
        self.assertIn("service.tasks[task_id] =", segment, "「插入任务」必须与检查在同一个 service.lock 块里")

    def test_account_gate_runs_before_the_browser_and_outside_the_task_lock(self) -> None:
        """``ensure_fill_browser`` 会拉起账户的浏览器，所以账户切换互斥必须先过。

        而 ``account_change_blocked`` 内部要拿 ``service.lock``（读任务表），那把锁不可重入——
        所以它**不能**写在 ``with service.lock`` 里面，否则请求会把自己锁死。
        """
        calls = {}
        for node in ast.walk(self.function):
            if isinstance(node, ast.Call):
                calls.setdefault(ast.unparse(node.func), []).append(node)
        self.assertIn("accounts.account_change_blocked", calls, "批量发布必须过账户切换互斥")
        gate = calls["accounts.account_change_blocked"][0]
        browser = calls["service.ensure_fill_browser"][0]
        self.assertLess(gate.lineno, browser.lineno, "账户切换互斥必须在拉起浏览器之前")
        for block in self._service_lock_blocks():
            inside = [ast.unparse(n.func) for n in ast.walk(block) if isinstance(n, ast.Call)]
            self.assertNotIn("accounts.account_change_blocked", inside, "不得在 service.lock 里面调用（不可重入的锁）")


class TaobaoPublishConcurrencyBehaviorTest(unittest.TestCase):
    """真实的 Blueprint + 真实的服务对象：已有任务在进行中时，第二次发起必须被拦下。"""

    ROW = {"id": 7, "name": "商品七", "path": "", "content": "[]"}

    def _case(self):
        service = make_service(record_model=make_record_model({7: self.ROW}))
        service.cdp_list_url = lambda: "http://127.0.0.1:9502/json/list"      # 校对路径：不起浏览器
        service.run_publish_task = Mock()                                   # worker 什么也不做，任务停在 pending
        app, _accounts = make_app(service)
        return service, app.test_client()

    def _start(self, client):
        return client.post("/api/taobao/publish/start", json={"record_id": 7, "account_profile": "taobao-test"})

    def test_second_start_is_refused_and_names_the_task_holding_the_browser(self) -> None:
        service, client = self._case()
        first = self._start(client)
        self.assertEqual(first.status_code, 200, first.get_json())
        task_id = first.get_json()["data"]["task_id"]
        self.assertEqual(service.tasks[task_id]["status"], "pending")

        second = self._start(client)
        self.assertEqual(second.status_code, 409)
        body = second.get_json()
        self.assertIs(body["success"], False)
        self.assertIn(task_id, body["msg"])
        self.assertIn("请等它结束后再发起", body["msg"])
        self.assertEqual(list(service.tasks), [task_id], "被拒绝的请求不得登记新任务")

    def test_finished_tasks_do_not_block_a_new_start(self) -> None:
        service, client = self._case()
        for status in ("succeeded", "failed", "cancelled"):
            service.tasks.clear()
            service.tasks["old"] = {"task_id": "old", "status": status, "record_name": "旧任务"}
            response = self._start(client)
            self.assertEqual(response.status_code, 200, (status, response.get_json()))

    def test_running_tasks_block_too(self) -> None:
        service, client = self._case()
        service.tasks["busy"] = {"task_id": "busy", "status": "running", "record_name": "占着的任务"}
        response = self._start(client)
        self.assertEqual(response.status_code, 409)
        self.assertIn("busy", response.get_json()["msg"])
        self.assertIn("占着的任务", response.get_json()["msg"])


if __name__ == "__main__":
    unittest.main()

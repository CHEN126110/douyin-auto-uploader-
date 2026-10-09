# -*- coding: utf-8 -*-
"""`listTaobaoPublishTasks` **定义了、没人调用** —— 于是重开面板看不到正在跑的任务。

## 发现（2026-10-03）

把 `api.ts` 的 51 个方法逐个查调用面，与淘宝/发布/账户有关又没人调用的只有一个：

```
listTaobaoPublishTasks
```

而面板：

```ts
onMounted(() => { void loadReadiness(); });            // ← 只读就绪度
onBeforeUnmount(() => { ... stopPublishPolling(); });  // ← 卸载时停轮询
```

**关掉面板再打开，任务就从视野里消失**——而它在 Sidecar 里**继续跑**。

**「真实发布」模式下这尤其严重**：任务正在往平台写，
而用户**既看不见进度、也点不到第 80 轮刚加上的取消按钮**。

## 实机验证判据

用**与界面一字不差**的条件筛真数据：

```
抓到 running；列表 4 条，按判据筛出 1 条
**判据成立**：用与界面相同的条件筛出了刚起的任务。
```

**两条限制**（都是判据的一部分）：

* 只接**当前商品**的——否则会把别的商品的任务显示在这里；
* 只接 `pending` / `running` 的——已经结束的没有接的意义。
"""
from __future__ import annotations

import pathlib
import re
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
PANEL = REPO_ROOT / "tauri-app" / "src" / "components" / "TaobaoPublishPanel.vue"
API_TS = REPO_ROOT / "tauri-app" / "src" / "services" / "api.ts"
APP = REPO_ROOT / "tauri-app" / "python-sidecar" / "app.py"


def code_only(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(line for line in text.splitlines()
                     if not line.strip().startswith("//"))


class RestoreIsWiredTest(unittest.TestCase):
    def setUp(self) -> None:
        self.panel = PANEL.read_text(encoding="utf-8")
        self.code = code_only(self.panel)

    def test_the_panel_calls_the_list_api(self) -> None:
        """⚠️ **这一条就是本轮发现的缺口。**"""

        self.assertIn("api.listTaobaoPublishTasks", self.code)

    def test_it_is_called_on_mount(self) -> None:
        index = self.code.index("onMounted(")
        body = self.code[index:index + 260]
        self.assertIn("restoreRunningTask", body,
                      "挂载时要接回正在跑的任务——否则重开面板看不到它")

    def test_it_only_takes_pending_or_running(self) -> None:
        """已经结束的任务没有接的意义。"""

        index = self.code.index("async function restoreRunningTask")
        body = self.code[index:index + 1600]
        self.assertIn('"pending"', body)
        self.assertIn('"running"', body)

    def test_it_only_takes_the_current_record(self) -> None:
        """**否则会把别的商品的任务显示在这里。**"""

        index = self.code.index("async function restoreRunningTask")
        body = self.code[index:index + 1600]
        self.assertIn("record_id === recordId", body)

    def test_it_does_not_overwrite_an_existing_task(self) -> None:
        index = self.code.index("async function restoreRunningTask")
        body = self.code[index:index + 400]
        self.assertIn("if (publishTask.value) return", body)

    def test_it_resumes_polling(self) -> None:
        """只显示不轮询的话，进度会停在接上那一刻。"""

        index = self.code.index("async function restoreRunningTask")
        body = self.code[index:index + 1600]
        self.assertIn("pollPublish", body)

    def test_failure_to_restore_is_silent_but_not_faked(self) -> None:
        """接不回来不该打断面板，**但也不能假装接上了**。"""

        index = self.code.index("async function restoreRunningTask")
        body = self.code[index:index + 1600]
        self.assertIn("catch", body)
        # catch 里不该给 publishTask 赋一个假值
        catch_part = body[body.index("catch"):]
        self.assertNotIn("publishTask.value =", catch_part)


class SidecarProvidesTheListTest(unittest.TestCase):
    def test_the_endpoint_exists(self) -> None:
        self.assertIn("/api/taobao/publish/tasks", APP.read_text(encoding="utf-8"))

    def test_it_passes_the_tasks_through_unchanged(self) -> None:
        """列表接口**原样透传**任务对象——所以字段取决于任务是怎么建的。"""

        source = APP.read_text(encoding="utf-8")
        start = source.index("def taobao_publish_tasks")
        end = source.index("\n@app.", start)
        body = source[start:end]
        self.assertIn("dict(item)", body, "应当原样透传，不做裁剪")

    def test_the_task_object_carries_the_fields_the_filter_needs(self) -> None:
        """⚠️ 判据用到 `record_id` 与 `status`——**任务创建时就要放进去**。

        （在列表函数里找这两个字面量是错的：它只 `dict(item)` 透传。
        将来若有人改任务结构把 `record_id` 去掉，列表接口会照旧透传，
        **只有查创建处才拦得住**。）
        """

        source = APP.read_text(encoding="utf-8")

        # `record_id` 在**路由注册任务时**放进去（工作线程只更新不新建）。
        route_start = source.index("def taobao_publish_start")
        route_end = source.index("\n@app.", route_start)
        self.assertIn("'record_id'", source[route_start:route_end],
                      "注册任务时要带 record_id——界面靠它筛「是不是本商品的」")

        # `status` 由**工作线程**写（pending → running → 终态）。
        run_start = source.index("def _run_taobao_publish_task")
        run_end = source.index("\ndef ", run_start + 10)
        run_body = source[run_start:run_end]
        self.assertIn("'status'", run_body,
                      "工作线程要写 status——界面靠它筛「还在不在跑」")

    def test_api_ts_declares_it(self) -> None:
        self.assertIn("listTaobaoPublishTasks", API_TS.read_text(encoding="utf-8"))


class FilterLogicTest(unittest.TestCase):
    """判据是纯逻辑——可以直接验。"""

    @staticmethod
    def _filter(tasks, record_id):
        return [t for t in tasks
                if t.get("record_id") == record_id
                and t.get("status") in ("pending", "running")]

    def test_it_picks_a_running_task_of_this_record(self) -> None:
        tasks = [{"task_id": "a", "record_id": 1, "status": "running"}]
        self.assertEqual([t["task_id"] for t in self._filter(tasks, 1)], ["a"])

    def test_it_skips_other_records(self) -> None:
        tasks = [{"task_id": "a", "record_id": 2, "status": "running"}]
        self.assertEqual(self._filter(tasks, 1), [])

    def test_it_skips_finished_tasks(self) -> None:
        for status in ("succeeded", "failed", "cancelled"):
            with self.subTest(status=status):
                tasks = [{"task_id": "a", "record_id": 1, "status": status}]
                self.assertEqual(self._filter(tasks, 1), [])

    def test_it_picks_pending_too(self) -> None:
        """任务刚创建、还没跑起来时也要接得上。"""

        tasks = [{"task_id": "a", "record_id": 1, "status": "pending"}]
        self.assertEqual([t["task_id"] for t in self._filter(tasks, 1)], ["a"])


if __name__ == "__main__":
    unittest.main()

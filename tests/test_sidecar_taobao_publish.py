# -*- coding: utf-8 -*-
"""淘宝发布接口的安全不变量。

与 `test_sidecar_protocol_ports.py` 同一套路：把 `app.py` 当文本读，断言**关键片段**
在不在。这样做的理由是这些不变量属于「接口契约」，不是「业务逻辑」——
真要跑起来需要 Flask 上下文、数据库和一个已登录的浏览器，成本远高于收益。

覆盖的都是**一旦写错就会静默出错**的地方：

* dry-run 与 stop-before-submit 的默认值（写错默认值 = 默认就往平台写）；
* 布尔值必须真的是布尔（`"false"` 是真值，会绕过默认的 dry-run）；
* 调试地址必须走应用管理的淘宝账户（写死 9334 会跑到研究用的浏览器上）；
* `publish_confirmed` 永远为假（把「跑完了」当成「已上架」是最难发现的错误）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
APP_PATH = PROJECT_ROOT / "tauri-app" / "python-sidecar" / "app.py"


class TaobaoPublishRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = APP_PATH.read_text(encoding="utf-8")

    def _body(self, start: str, end: str) -> str:
        self.assertIn(start, self.source, f"app.py 里找不到 {start!r}")
        return self.source.split(start, 1)[1].split(end, 1)[0]

    def _start_body(self) -> str:
        return self._body(
            "def taobao_publish_start():",
            "@app.get('/api/taobao/publish/status",
        )

    def _options_body(self) -> str:
        """参数解析与校验所在的**纯函数**。

        ⚠️ 它原本内联在路由里，于是只有登录淘宝账户才测得到（前面还有
        `_require_publish_platform` 那道账户门）。抽成纯函数后，下面这些
        "默认值写反就静默出错"的不变量可以**直接调用**验证，不必只断言字符串。
        """

        return self._body("def _parse_taobao_publish_options(", "@app.post('/api/taobao/publish/start')")

    def _parse(self, data):
        """直接调用纯函数（不需 Flask 上下文、不需账户）。"""

        import ast as _ast
        import types as _types

        source = APP_PATH.read_text(encoding="utf-8")
        tree = _ast.parse(source)
        node = next(n for n in tree.body
                    if isinstance(n, _ast.FunctionDef) and n.name == "_parse_taobao_publish_options")
        module = _types.ModuleType("_options_probe")
        module.TAOBAO_LISTING_MODES = ("", "立刻上架", "定时上架", "放入仓库")
        exec(compile(_ast.Module(body=[node], type_ignores=[]), str(APP_PATH), "exec"),
             module.__dict__)
        return module._parse_taobao_publish_options(data)

    def test_defaults_to_dry_run(self) -> None:
        """默认必须是**不写平台**。默认值写反 = 用户点一下就往平台写。"""

        options, error = self._parse({})
        self.assertIsNone(error)
        self.assertIs(options["dry_run"], True)

    def test_defaults_to_stopping_before_submit(self) -> None:
        options, error = self._parse({})
        self.assertIsNone(error)
        self.assertIs(options["stop_before_submit"], True)

    def test_rejects_non_boolean_switches(self) -> None:
        """字符串 `"false"` 在 Python 里是真值——不校验就会绕过 dry-run 默认值。"""

        self.assertIn("isinstance(value, bool)", self._options_body())
        self.assertIn("必须是布尔值", self._options_body())
        for key in ("dry_run", "stop_before_submit", "fill_only", "save_draft"):
            options, error = self._parse({key: "false"})
            self.assertIsNone(options, key + " 的字符串值必须被拒")
            self.assertIn("必须是布尔值", error)


    def test_uses_the_app_managed_taobao_browser(self) -> None:
        """调试地址必须走当前淘宝账户的浏览器，不能写死研究用的 9334。"""

        body = self._start_body()
        self.assertIn("_taobao_cdp_list_url()", body)
        self.assertNotIn("9334", body)

    def test_refuses_when_no_taobao_browser_is_available(self) -> None:
        body = self._start_body()
        self.assertIn("if not cdp_list_url:", body)

    def test_requires_a_taobao_account(self) -> None:
        """在抖音账户下发起淘宝发布会选错浏览器与登录态。"""

        body = self._start_body()
        self.assertIn("_require_publish_platform('taobao'", body)

    def test_only_accepts_known_parameters(self) -> None:
        options, error = self._parse({"record_id": 1, "未知参数": 1})
        self.assertIsNone(options)
        self.assertIn("不支持的参数", error)
        # 已知参数必须全部放行（白名单别误伤）
        options, error = self._parse({
            "record_id": 1, "platform": "taobao", "account_profile": "x", "dry_run": False,
            "stop_before_submit": True, "product": {}, "fill_only": True,
            "expected_record_revision": "r", "listing_mode": "放入仓库", "save_draft": True,
        })
        self.assertIsNone(error, error)
        self.assertIs(options["save_draft"], True)

    def test_save_draft_defaults_to_not_saving(self) -> None:
        """**保存草稿是写入，默认必须是"不保存"。**

        授权（`save_draft` 操作族）只是**白名单**，请求才是**开关**——两者分开，
        界面与后端都不会"顺手就存了"。默认值写反 = 用户点一下平台上就多一条草稿。
        """

        self.assertIn("'save_draft': data.get('save_draft', False)", self._options_body())
        options, error = self._parse({})
        self.assertIsNone(error)
        self.assertIs(options["save_draft"], False)
        # 显式请求才为真
        options, error = self._parse({"save_draft": True})
        self.assertIsNone(error)
        self.assertIs(options["save_draft"], True)

    def test_listing_mode_is_restricted_to_the_measured_options(self) -> None:
        """上架方式只能取页面上**实测存在**的三个选项，且留空走"放入仓库"。

        危险的那个（立刻上架）绝不能是默认值——默认值是"放进仓库，等人复核"。
        """

        for mode in ("立刻上架", "定时上架", "放入仓库"):
            options, error = self._parse({"listing_mode": mode})
            self.assertIsNone(error, mode)
            self.assertEqual(options["listing_mode"], mode)
        for bad in ("上架到月球", "immediately", "立刻上架 "):   # 末项会被 strip 成合法值
            if bad.strip() in ("立刻上架", "定时上架", "放入仓库"):
                continue
            options, error = self._parse({"listing_mode": bad})
            self.assertIsNone(options, bad + " 必须被拒")
            self.assertIn("只能是", error)
        # 留空 = 用流水线默认值（放入仓库），**不是**立刻上架
        options, error = self._parse({})
        self.assertIsNone(error)
        self.assertEqual(options["listing_mode"], "")
        self.assertNotEqual(options["listing_mode"], "立刻上架")
        # 非字符串被拒
        options, error = self._parse({"listing_mode": 123})
        self.assertIsNone(options)
        self.assertIn("必须是字符串", error)

    def test_does_not_fall_back_to_the_douyin_upload_path(self) -> None:
        """绝不回退到抖店上传——那会把商品发到另一个平台。"""

        body = self._start_body()
        for forbidden in ("_run_upload_task", "/api/upload/start", "_upload_tasks["):
            self.assertNotIn(forbidden, body)

    def test_task_is_kept_separate_from_douyin_tasks(self) -> None:
        body = self._start_body()
        self.assertIn("_taobao_tasks[task_id] = task", body)
        self.assertNotIn("_upload_tasks[task_id]", body)

    def test_worker_reads_authorization_from_environment(self) -> None:
        """授权只能来自 sidecar 的环境变量，不能由请求体传入。"""

        body = self._body("def _run_taobao_publish_task(", "@app.post('/api/taobao/publish/start')")
        self.assertIn("WriteAuthorization.from_environment()", body)
        self.assertNotIn("data.get('authorization'", body)


class TaobaoPublishTaskOutcomeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = APP_PATH.read_text(encoding="utf-8")
        self.worker = self.source.split("def _run_taobao_publish_task(", 1)[1].split(
            "@app.post('/api/taobao/publish/start')", 1)[0]

    def test_never_claims_publish_confirmed(self) -> None:
        """**核心不变量**：流水线跑完 ≠ 商品已上架。

        提交通道的成功特征尚未实证，所以任务里这个字段必须恒为 False，
        只由人工在卖家中心核对后另行确认。
        """

        self.assertIn("task['publish_confirmed'] = False", self.worker)
        self.assertNotIn("task['publish_confirmed'] = True", self.worker)

    def test_forwards_listing_mode_and_save_draft_to_the_pipeline(self) -> None:
        """**界面上的选择必须真的到得了流水线。**

        实测踩过：侧边栏只传 `fill_only`/`dry_run`/`stop_before_submit` 时，
        界面上的「上架方式」会静默用默认值、`save_draft` 阶段永远 `skipped`——
        表现为"GUI 里点了保存草稿但平台上没有草稿"，极难排查。
        """

        self.assertIn("listing_mode=options.get('listing_mode', '')", self.worker)
        self.assertIn("save_draft=options.get('save_draft', False)", self.worker)

    def test_success_message_points_at_manual_confirmation(self) -> None:
        self.assertIn("卖家中心核对", self.worker)

    def test_failure_carries_blockers(self) -> None:
        """失败必须带上结构化阻塞项，而不是只有一句话。"""

        self.assertIn("task['blockers'] = payload.get('blockers')", self.worker)

    def test_progress_callback_matches_the_douyin_signature(self) -> None:
        """进度回调签名与抖店一致，前端那套 UploadStepInfo 才能复用。"""

        self.assertIn("def _report_progress(pct, msg, step_name, steps):", self.worker)

    def test_records_the_result_for_inspection(self) -> None:
        self.assertIn("task['result'] = payload", self.worker)

    def test_passes_a_cancel_hook_to_the_pipeline(self) -> None:
        """取消必须真的接进流水线——否则 cancel 接口只是设了个没人看的标记。"""

        self.assertIn("should_cancel=_should_cancel", self.worker)
        self.assertIn("def _should_cancel():", self.worker)

    def test_cancel_hook_reads_the_task_flag_under_lock(self) -> None:
        hook = self.worker.split("def _should_cancel():", 1)[1].split("try:", 1)[0]
        self.assertIn("_taobao_tasks_lock", hook)
        self.assertIn("task.get('cancelled')", hook)

    def test_cancelled_result_maps_to_cancelled_status(self) -> None:
        """流水线报 CANCELLED 时任务状态要是 cancelled，不能混进 failed。"""

        self.assertIn("(payload.get('error') or {}).get('code') == 'CANCELLED'", self.worker)
        self.assertIn("task['status'] = 'cancelled'", self.worker)

    def test_cancelled_branch_comes_before_success_and_failure(self) -> None:
        """顺序不能反：取消时 payload.success 为假，先判 failed 就会把取消报成失败。"""

        cancelled_at = self.worker.index("if cancelled:")
        succeeded_at = self.worker.index("elif payload.get('success'):")
        self.assertLess(cancelled_at, succeeded_at)


class TaobaoPublishStatusRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = APP_PATH.read_text(encoding="utf-8")

    def test_status_locks_when_reading(self) -> None:
        """任务表被工作线程写、被请求线程读，读的时候也要持锁。"""

        body = self.source.split("@app.get('/api/taobao/publish/status", 1)[1].split(
            "@app.post('/api/taobao/publish/cancel", 1)[0]
        self.assertIn("_taobao_tasks_lock", body)

    def test_status_returns_404_for_unknown_task(self) -> None:
        body = self.source.split("@app.get('/api/taobao/publish/status", 1)[1].split(
            "@app.post('/api/taobao/publish/cancel", 1)[0]
        self.assertIn("404", body)

    def test_cancel_does_not_claim_the_worker_stopped(self) -> None:
        """取消只是**请求**；实际停止发生在阶段边界，不能报成「已停止」。"""

        body = self.source.split("@app.post('/api/taobao/publish/cancel", 1)[1].split(
            "@app.get('/api/taobao/publish/tasks", 1)[0]
        self.assertIn("阶段边界", body)


if __name__ == "__main__":
    unittest.main()


class TaobaoProductPayloadTest(unittest.TestCase):
    """界面收集的商品资料必须**真的传进流水线**。

    踩过的坑：界面填了标题/价格/库存/类目，却只用在「资料检查/导出资料包」上；
    `/api/taobao/publish/start` 只传 record_id，于是流水线在静态预检就报
    「标题为空」——**UI 收集的数据从来没有到达过发布流水线**。
    """

    def setUp(self) -> None:
        self.source = APP_PATH.read_text(encoding='utf-8')

    def _start_body(self) -> str:
        return self.source.split("def taobao_publish_start():", 1)[1].split(
            "@app.get('/api/taobao/publish/status", 1)[0]

    def test_start_accepts_the_product_field(self) -> None:
        body = self._start_body()
        self.assertIn("'product'", body, "白名单里必须有 product")
        self.assertIn("data.get('product')", body)
        self.assertIn("_taobao_product_request_payload(", body)

    def test_translation_never_guesses_spec_values(self) -> None:
        """**规格值必须由调用方明确给出**，不许从 SKU 名字里拆。

        SKU 名字形如「黑色-白色-浅灰 【5双装】+均码(35-40)【甄选优质棉】」，
        从里面猜颜色/尺码是典型的「猜字段」——项目红线明确禁止。
        """

        body = self.source.split("def _taobao_product_request_payload(", 1)[1].split(
            "def _run_taobao_publish_task(", 1)[0]
        self.assertIn("spec_values", body, "说明里必须点明 spec_values 由调用方给出")
        # 不许出现任何「拆名字」的痕迹
        for forbidden in ("split('-')", 'split("-")', "split('+')", 'split("+")',
                          "sku['name']", 'sku.get("name")'):
            self.assertNotIn(forbidden, body, "不许从 SKU 名字推断属性值")

    def test_translation_splits_category_path_on_gt(self) -> None:
        """`category_path` 用 `>` 分层；流水线要求**完整路径精确相等**。"""

        body = self.source.split("def _taobao_product_request_payload(", 1)[1].split(
            "def _run_taobao_publish_task(", 1)[0]
        self.assertIn('split(">")', body)

    def test_translation_is_a_pure_function_near_the_worker(self) -> None:
        """翻译函数要在工作线程函数附近，便于单测直接取出来跑。"""

        self.assertLess(
            self.source.index("def _taobao_product_request_payload("),
            self.source.index("def _run_taobao_publish_task("),
        )


if __name__ == "__main__":
    unittest.main()


class TaobaoFrontendProductWiringTest(unittest.TestCase):
    """界面必须把它收集的资料**真的发出去**。

    踩过的坑：面板填了标题/价格/库存/类目，但 `startTaobaoPublish` 只发
    `record_id`——数据从来没到达过流水线，静态预检永远报「标题为空」。
    """

    PANEL = PROJECT_ROOT / 'tauri-app' / 'src' / 'components' / 'TaobaoPublishPanel.vue'
    API = PROJECT_ROOT / 'tauri-app' / 'src' / 'services' / 'api.ts'
    TYPES = PROJECT_ROOT / 'tauri-app' / 'src' / 'types' / 'index.ts'

    def test_api_sends_product_in_the_post_body(self) -> None:
        source = self.API.read_text(encoding='utf-8')
        start = source.split('startTaobaoPublish(', 1)[1]
        body = start.split('http.post(', 1)[1].split('});', 1)[0]
        self.assertIn('{ product: options.product }', body,
                      "POST body 里必须真的带上 product（别被 productDir 之类的同名前缀骗了）")

    def test_types_declare_the_product_request(self) -> None:
        source = self.TYPES.read_text(encoding='utf-8')
        self.assertIn('export interface TaobaoProductRequest', source)
        self.assertIn('spec_values', source,
                      "规格值必须是显式字段——不许从 SKU 名字里拆")

    def test_panel_passes_product_when_starting_publish(self) -> None:
        source = self.PANEL.read_text(encoding='utf-8')
        self.assertIn('buildProductRequest()', source)
        # 校验不通过时**不发请求**：判空要在调接口之前。
        start = source.index('const product = buildProductRequest();')
        segment = source[start:start + 700]
        self.assertIn('if (!product)', segment, '校验没通过就不该发请求')
        self.assertLess(segment.index('if (!product)'),
                        segment.index('api.startTaobaoPublish'),
                        '判空必须在调接口之前')
        # 真的带上 product（简写形式 product,）
        call = source.split('api.startTaobaoPublish(', 1)[1].split('});', 1)[0]
        self.assertRegex(call, r'\bproduct\b', '启动发布时必须带上 product')

    def test_panel_never_invents_prop_or_spec_values(self) -> None:
        """**界面不许替用户编造属性值或规格值。**

        面板里补的两样输入（类目属性、规格值）都必须是**操作人自己填的**；
        从商品名或 SKU 名字里推断属于「猜字段」，项目红线明确禁止。
        """

        source = self.PANEL.read_text(encoding='utf-8')
        builder = source.split('function buildProductRequest(', 1)[1].split(
            'async function checkPreparation', 1)[0]
        self.assertIn('draft.value.props', builder)
        self.assertIn('specValuesOf', builder)
        # 不许出现任何按分隔符拆名字的痕迹
        for forbidden in ('name.split', "name.match", 'sku.name.split'):
            self.assertNotIn(forbidden, builder, '不许从名字推断属性值')

    def test_panel_seeds_spec_values_as_empty_not_guessed(self) -> None:
        """资料里没有规格值，所以 seed 时必须是**空串**，不能编一个。"""

        source = self.PANEL.read_text(encoding='utf-8')
        seed = source.split('function seedDraft(', 1)[1].split('function ', 1)[0]
        self.assertIn('spec_values: ""', seed)
        self.assertIn('props: []', seed)


if __name__ == "__main__":
    unittest.main()

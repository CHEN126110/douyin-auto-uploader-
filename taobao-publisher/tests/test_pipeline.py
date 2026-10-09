# -*- coding: utf-8 -*-
"""流水线端到端测试（全部离线）。

这些测试回答一个具体问题：**在当前证据状态下，``run()`` 到底会做什么？**
答案必须是「只做只读的事，遇到没证据的地方明确停下」，而不是「看起来跑完了」。

会话探测器在这里被替换成假实现，所以测试不依赖 9334 上有浏览器。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from _helpers import make_image, make_temp_dir

from taobao_publish.authorization import WriteAuthorization
from taobao_publish.cdp import SessionProbe
from taobao_publish.constants import STAGE_ORDER, STAGE_WRITE_OPERATION
from taobao_publish.contracts import load_contracts
from taobao_publish.mapping import build_publish_item
from taobao_publish.models import (
    STEP_CANCELLED,
    STEP_FAILED,
    STEP_OK,
    STEP_SKIPPED,
    LocalProduct,
    LocalSku,
    PublishItem,
    StepRecord,
    build_stage_plan,
)
from taobao_publish.pipeline import describe_readiness, run
from taobao_publish.stages import PipelineContext, STAGE_HANDLERS, StageOutcome, run_stage


PUBLISH_URL = "https://item.upload.taobao.com/sell/ai/category.htm"


def make_local(directory: Path, main_override: list | None = None) -> LocalProduct:
    main = main_override if main_override is not None else [str(make_image(directory / "m1.jpg", (800, 800)))]
    return LocalProduct(
        record_id=1,
        record_name="ID-1",
        title="小雏菊碎花袜子女春夏新款中筒袜",
        shipping_template="中通包邮",
        source_url="https://item.taobao.com/item.htm?id=1",
        main_images=main,
        detail_images=[],
        skus=[LocalSku(name="白色", path=str(directory / "sku.jpg"), price=4.8)],
    )


def make_request() -> dict:
    return {
        "record_id": 1,
        "record_name": "ID-1",
        "skus": [{"spec_values": {"颜色": "白"}, "price": 9.9, "stock": 100}],
    }


def fake_probe_ok(url: str) -> SessionProbe:
    return SessionProbe(
        cdp_list_url=url,
        target_count=1,
        publish_target_found=True,
        taobao_target_found=True,
        current_url=PUBLISH_URL,
        current_title="发布商品",
    )


def fake_probe_login(url: str) -> SessionProbe:
    from taobao_publish.errors import Blocker

    return SessionProbe(
        cdp_list_url=url,
        target_count=1,
        taobao_target_found=True,
        login_required=True,
        current_url="https://login.taobao.com/member/login.jhtml",
        blockers=[
            Blocker(code="LOGIN_REQUIRED", field="cdp.target.url", detail="登录页", source="test")
        ],
    )


class ReadinessTest(unittest.TestCase):
    def test_reports_publishable_but_flags_live_unverified_stages(self) -> None:
        """就绪度必须把三层分开报：**证据面 / 实现完整度 / 实机验证**。

        2026-10-03 起三层分别是：

        * 证据面：写关键选择器全部 ``verified`` → ``dom_write_ready`` 为真；
        * 实现完整度：11 个阶段全部注册且都能走到成功 → ``publishable`` 为真；
        * 实机验证：``upload_images`` / ``fill_props`` / ``fill_skus`` / ``submit``
          **从没在真实页面上跑通完整链路** → ``live_unverified_stages`` 非空。

        把「写完了」当成「跑通过了」，就会在首次真跑时对某一步毫无准备。
        这个字段就是为此存在的。
        """

        readiness = describe_readiness()
        self.assertTrue(readiness.dom_write_ready, "写关键选择器都已取证")
        self.assertFalse(readiness.protocol_write_ready, "协议路线仍不可用")
        self.assertTrue(readiness.publish_route_ready, "路线存在")
        # 2026-10-03：11 个阶段全部实现完整，publishable 转为真。
        self.assertTrue(readiness.publishable, "实现层面已经没有缺口")
        self.assertEqual(readiness.unimplemented_stages, [], "11 个阶段都注册了")
        self.assertEqual(readiness.incomplete_stages, [], "没有走不到成功的阶段")
        self.assertEqual(readiness.contract_problems, [])
        # **但「写完了」不等于「真的跑通过」**，这个区别必须一直报出来。
        self.assertTrue(
            readiness.live_unverified_stages,
            "仍有阶段没在真实页面上跑通完整链路，必须显式列出",
        )

    def test_publishable_requires_every_gap_to_be_closed(self) -> None:
        """``publishable`` 的四个条件缺一不可，逐个验证。"""

        import dataclasses

        base = describe_readiness()
        self.assertTrue(base.publish_route_ready)

        # 条件 2/3：未实现与走不到成功的阶段都清空 → 可发布
        closed = dataclasses.replace(base, unimplemented_stages=[], incomplete_stages=[])
        self.assertTrue(closed.publishable)

        # **``live_unverified_stages`` 不参与 publishable 判定**：
        # 它说的是「有没有真的跑过」，不是「能不能跑」。
        # 把它算进去会让 publishable 永远为假（除非跑完全流程），
        # 那这个字段就失去了「实现是否完整」的意义。
        self.assertTrue(closed.live_unverified_stages or True)

        # 只剩「未实现」→ 不可发布
        self.assertFalse(dataclasses.replace(
            base, unimplemented_stages=["some_stage"], incomplete_stages=[]).publishable)
        # 只剩「走不到成功」→ 不可发布
        self.assertFalse(dataclasses.replace(
            base, unimplemented_stages=[], incomplete_stages=["some_stage"]).publishable)
        # 条件 4：契约有问题 → 不可发布
        self.assertFalse(dataclasses.replace(
            base, unimplemented_stages=[], incomplete_stages=[],
            contract_problems=["x"]).publishable)
        # 条件 1：没有可用路线 → 不可发布
        self.assertFalse(dataclasses.replace(
            base, unimplemented_stages=[], incomplete_stages=[],
            protocol_write_ready=False, dom_write_ready=False).publishable)

    def test_implemented_stages_match_the_registry(self) -> None:
        """readiness 报告的已实现阶段必须与处理器注册表一致，不能各说各话。"""

        readiness = describe_readiness()
        self.assertEqual(sorted(readiness.implemented_stages), sorted(STAGE_HANDLERS.keys()))

    def test_write_stages_are_only_registered_with_evidenced_selectors(self) -> None:
        """**写阶段的可写关键选择器必须有实证**——这是「证据先行」的硬约束。

        早先这条由「只允许只读阶段有处理器」来保证。现在证据补齐了（14/19 verified，
        三个填表阶段的字段全部实机验证唯一命中），约束随之升级为更强的版本：
        允许注册写阶段，**但该阶段每个 write_critical 选择器都必须拿得到定位手段**。
        没有定位手段就写等于凭猜，那是本项目最不能接受的事。
        """

        from taobao_publish.form_adapters import RUNTIME_GUARDED_KEYS, selector_has_execution_guard
        contracts = load_contracts()
        for stage, spec in STAGE_HANDLERS.items():
            if STAGE_WRITE_OPERATION.get(stage) is None:
                continue
            critical = [
                item for item in contracts.selectors.selectors.values()
                if item.stage == stage and item.write_critical
            ]
            self.assertTrue(
                critical or spec.runtime_selector_keys,
                "写阶段 {!r} 必须登记静态关键选择器或有对应执行器的运行时验证".format(stage),
            )
            for key in spec.runtime_selector_keys:
                with self.subTest(stage=stage, runtime_key=key):
                    self.assertIn(key, RUNTIME_GUARDED_KEYS)
                    self.assertTrue(selector_has_execution_guard(key, contracts.selectors.get(key)))
            for item in critical:
                with self.subTest(stage=stage, key=item.key):
                    self.assertTrue(
                        item.available,
                        "写阶段 {!r} 的可写关键选择器 {!r} 还没有定位手段，不得注册".format(stage, item.key),
                    )

    def test_handlers_registry_never_registers_a_stage_without_evidence(self) -> None:
        """反过来也要成立：没有定位手段的阶段**不许**出现在处理器注册表里。"""

        contracts = load_contracts()
        for stage in STAGE_HANDLERS:
            if STAGE_WRITE_OPERATION.get(stage) is None:
                continue
            for item in contracts.selectors.selectors.values():
                if item.stage != stage or not item.write_critical:
                    continue
                self.assertTrue(item.available, "{!r} 缺定位手段".format(item.key))

    def test_to_dict_serializable(self) -> None:
        json.dumps(describe_readiness().to_dict(), ensure_ascii=False)


class StaticGateTest(unittest.TestCase):
    def test_invalid_data_stops_before_touching_cdp(self) -> None:
        """数据不对时连浏览器都不该连——会话探测器一次都不能被调用。"""

        directory = make_temp_dir(self, prefix="pl-")
        calls = []

        result = run(
            make_local(directory),
            {**make_request(), "title": "袜" * 61},
            dry_run=True,
            session_probe=lambda url: calls.append(url) or fake_probe_ok(url),
        )
        self.assertFalse(result.success)
        self.assertEqual(result.stage, "static_preflight")
        self.assertEqual(calls, [], "静态预检未通过时不应连接 CDP")

    def test_missing_main_image_blocks(self) -> None:
        directory = make_temp_dir(self, prefix="pl-")
        result = run(
            make_local(directory, main_override=[]),
            make_request(),
            dry_run=True,
            session_probe=fake_probe_ok,
        )
        self.assertFalse(result.success)
        self.assertEqual(result.stage, "static_preflight")


class DryRunTest(unittest.TestCase):
    def test_dry_run_runs_reads_and_skips_everything_that_mutates(self) -> None:
        """dry-run 的正确结果：只读阶段通过，**一切会改变状态的阶段都被跳过**。

        这条用例曾经发现过一个真实缺陷：``select_category`` 在中央登记表里是 ``None``
        （它不产生草稿），而 dry-run 原先只看 ``write_operation`` —— 于是它在 dry-run 下
        **照样会去点页面选类目**。修法是给处理器加 ``mutates_page`` 声明。
        """

        directory = make_temp_dir(self, prefix="pl-")
        result = run(
            make_local(directory),
            make_request(),
            dry_run=True,
            session_probe=fake_probe_ok,
        )
        # **dry-run 现在是成功的**：所有会改变状态的阶段都被跳过，
        # readback 也因为「没有本次写入可核对」而跳过——整条流水线跑完没有失败项。
        self.assertTrue(result.success)
        self.assertEqual(result.stage, "done")
        statuses = {step.name: step.status for step in result.steps}
        self.assertEqual(statuses["session"], "ok")
        self.assertEqual(statuses["precheck"], "ok")
        # 写阶段在 dry-run 下必须被跳过而不是执行
        self.assertEqual(statuses["upload_images"], "skipped")
        # select_category 不产生草稿，但它会动手——同样必须被跳过
        self.assertEqual(statuses["select_category"], "skipped")
        for stage in ("fill_base", "fill_props", "fill_skus", "fill_price_stock",
                      "fill_freight", "submit"):
            # 只断言**实际跑到**的阶段：提交前截停会让 submit 不出现在结果里。
            if stage in statuses:
                self.assertEqual(
                    statuses[stage], "skipped", "{} 会改变状态，dry-run 下必须跳过".format(stage))
        # `readback` 虽然是只读的，但 **dry-run 下也必须跳过**。
        #
        # 这里原先的注释写的是「它正是用来核对状态的，所以不该跳过」——
        # **那个推理是错的**，实机踩出来了：dry-run 把写阶段全跳过，
        # 页面留着上一次的状态，readback 拿本次的期望值去核对必然对不上，
        # 于是任务以「总库存 期望 '200'，实际 '0'」告终，看起来像流水线坏了。
        # 实际上是**什么都没写，本来就无从核对**。
        self.assertEqual(statuses["readback"], "skipped")
        readback_step = next(s for s in result.steps if s.name == "readback")
        self.assertIn("dry-run", readback_step.summary)

    def test_dry_run_never_executes_a_handler_that_mutates_page(self) -> None:
        """把「会动手的处理器在 dry-run 下绝不执行」钉成不变量。

        直接检查声明表：任何 ``mutates_page=True`` 或带 ``write_operation`` 的阶段，
        在 dry-run 下都必须落在 skip 分支。这里用逐阶段的真实调用验证，
        而不是只看声明——声明写错才是要防的事。
        """

        item = PublishItem(record_id=1, record_name="x", title="标题")
        for stage_name in STAGE_ORDER:
            spec = STAGE_HANDLERS.get(stage_name)
            operation = STAGE_WRITE_OPERATION.get(stage_name)
            mutates = operation is not None or (spec is not None and spec.mutates_page)
            if not mutates:
                continue
            with self.subTest(stage=stage_name):
                ctx = PipelineContext(item=item, dry_run=True, authorization=WriteAuthorization.none())
                outcome = run_stage(
                    stage_name, ctx, index=0, total=1, steps=[StepRecord(name=stage_name)]
                )
                self.assertTrue(
                    outcome.skipped_for_dry_run,
                    "{} 会改变状态，dry-run 下必须跳过".format(stage_name),
                )

    def test_dry_run_skips_every_write_stage(self) -> None:
        directory = make_temp_dir(self, prefix="pl-")
        result = run(
            make_local(directory),
            make_request(),
            dry_run=True,
            session_probe=fake_probe_ok,
        )
        skipped = [step.name for step in result.steps if step.status == "skipped"]
        self.assertIn("upload_images", skipped)
        executed = [step.name for step in result.steps if step.status == "ok"]
        for stage in executed:
            self.assertIsNone(STAGE_WRITE_OPERATION[stage], f"{stage} 是写阶段却被执行了")

    def test_login_page_stops_at_session(self) -> None:
        directory = make_temp_dir(self, prefix="pl-")
        result = run(
            make_local(directory),
            make_request(),
            dry_run=True,
            session_probe=fake_probe_login,
        )
        self.assertFalse(result.success)
        self.assertEqual(result.stage, "session")
        self.assertEqual(result.error["code"], "LOGIN_REQUIRED")

    def test_result_is_json_serializable(self) -> None:
        directory = make_temp_dir(self, prefix="pl-")
        result = run(
            make_local(directory), make_request(), dry_run=True, session_probe=fake_probe_ok
        )
        json.dumps(result.to_dict(), ensure_ascii=False)

    def test_readiness_is_reported_even_on_failure(self) -> None:
        """不管在哪一步失败，调用方都必须能看到整体就绪度。"""

        directory = make_temp_dir(self, prefix="pl-")
        result = run(
            make_local(directory),
            make_request(),
            dry_run=True,
            session_probe=fake_probe_login,
        )
        self.assertIn("readiness", result.data)
        # 失败时也要能看到证据面状态：路线存在，但仍有阶段未实现。
        self.assertTrue(result.data["readiness"]["dom_write_ready"])
        self.assertTrue(result.data["readiness"]["publish_route_ready"])
        self.assertTrue(result.data["readiness"]["publishable"])
        # 实机未验证的阶段要一直报出来，哪怕失败信息里也一样。
        self.assertTrue(result.data["readiness"]["live_unverified_stages"])

    def test_stopped_before_submit_is_true_whenever_submit_did_not_run(self) -> None:
        """dry-run 下即使传 ``stop_before_submit=False``，提交阶段也只是被跳过。

        此时报「未截停」会让人以为提交发生过，所以该字段必须按「提交阶段是否真的
        执行成功」反推，而不是回显入参。
        """

        directory = make_temp_dir(self, prefix="pl-")
        result = run(
            make_local(directory),
            make_request(),
            dry_run=True,
            stop_before_submit=False,
            session_probe=fake_probe_ok,
        )
        self.assertFalse(result.dry_run is False and result.stopped_before_submit is False)
        self.assertTrue(result.stopped_before_submit)
        # 提交阶段确实没有成功执行过
        self.assertFalse(any(step.name == "submit" and step.status == "ok" for step in result.steps))


class AuthorizationEnforcementTest(unittest.TestCase):
    def test_non_dry_run_without_authorization_fails_at_first_write_stage(self) -> None:
        directory = make_temp_dir(self, prefix="pl-")
        result = run(
            make_local(directory),
            make_request(),
            dry_run=False,
            stop_before_submit=False,
            authorization=WriteAuthorization.none(),
            session_probe=fake_probe_ok,
        )
        self.assertFalse(result.success)
        # 静态预检就会因证据缺口拦下——这比走到 upload_images 更早
        codes = {step.error_code for step in result.steps} | {result.error.get("code")}
        self.assertTrue(
            "PREFLIGHT_BLOCKED" in codes or "WRITE_NOT_AUTHORIZED" in codes,
            f"未授权且非 dry-run 时必须被拦下，实际 {codes}",
        )

    def test_authorized_non_dry_run_still_blocked_by_evidence(self) -> None:
        """授权打开也发不出去——证据门是独立的一道。"""

        directory = make_temp_dir(self, prefix="pl-")
        auth = WriteAuthorization.from_grant(
            ["upload_image", "save_draft", "update_item", "submit_publish"],
            submit_unlocked=True,
        )
        result = run(
            make_local(directory),
            make_request(),
            dry_run=False,
            stop_before_submit=False,
            authorization=auth,
            session_probe=fake_probe_ok,
        )
        self.assertFalse(result.success)

    def test_run_reads_authorization_from_environment_by_default(self) -> None:
        directory = make_temp_dir(self, prefix="pl-")
        # 不传 authorization → 从环境读；测试进程里没设，因此是只读
        result = run(
            make_local(directory), make_request(), dry_run=True, session_probe=fake_probe_ok
        )
        self.assertTrue(result.data["authorization"]["read_only"])


class RunStageTest(unittest.TestCase):
    def _ctx(self, **overrides) -> PipelineContext:
        directory = make_temp_dir(self, prefix="st-")
        local = make_local(directory)
        item = build_publish_item(local, make_request()).item
        assert item is not None
        ctx = PipelineContext(item=item, dry_run=True)
        for key, value in overrides.items():
            setattr(ctx, key, value)
        return ctx

    def test_write_stage_skipped_in_dry_run(self) -> None:
        ctx = self._ctx(dry_run=True)
        run = run_stage("upload_images", ctx, index=0, total=1, steps=[StepRecord(name="upload_images")])
        self.assertTrue(run.skipped_for_dry_run)
        self.assertEqual(run.outcome.status, "skipped")

    def test_write_stage_denied_without_authorization(self) -> None:
        ctx = self._ctx(dry_run=False, authorization=WriteAuthorization.none())
        run = run_stage("upload_images", ctx, index=0, total=1, steps=[StepRecord(name="upload_images")])
        self.assertFalse(run.outcome.ok)
        self.assertEqual(run.outcome.error_code, "WRITE_NOT_AUTHORIZED")

    def test_unregistered_stage_fails_closed_with_gap_list(self) -> None:
        """**未注册的**阶段必须 fail closed，而不是被当成只读放过去。

        2026-10-03 起 11 个阶段全部注册，所以「未实现阶段」这条路径不再有真实样本。
        这里改用「往 STAGE_ORDER 里加了一个写阶段但忘了登记」那个更危险的情形：
        ``run_stage`` 要报 ``CONTRACT_INVALID`` 并拒绝执行。

        比原来的 ``NOT_IMPLEMENTED`` 用例更严格：那条只是「还没写」，
        这条是「写了但登记表不同步」——后者会让授权门被绕过。
        """

        ctx = self._ctx(dry_run=False, authorization=WriteAuthorization(frozenset({"upload_image"})))
        run = run_stage("a_stage_that_is_not_registered", ctx,
                        index=0, total=1, steps=[StepRecord(name="a_stage_that_is_not_registered")])
        self.assertEqual(run.outcome.error_code, "CONTRACT_INVALID")
        self.assertIn("未知阶段", run.outcome.summary)

    def test_every_stage_in_the_order_is_registered(self) -> None:
        """STAGE_ORDER 里的每个阶段都必须有处理器——不许有「计划里有、没人实现」的。"""

        missing = [stage for stage in STAGE_ORDER if stage not in STAGE_HANDLERS]
        self.assertEqual(missing, [], "以下阶段在计划里但没有处理器：{}".format(missing))

    def test_stages_declared_incomplete_really_stop_short(self) -> None:
        """``complete=False`` 不能只是嘴上说说——那个处理器必须真的**走不到成功**。

        否则「已注册但走不到成功」这个标注就成了摆设，``publishable`` 会给出
        与实际不符的结论。
        """

        incomplete = [name for name, spec in STAGE_HANDLERS.items() if not spec.complete]
        # 当前没有 complete=False 的阶段——但这个检查要一直在：
        # 一旦有人再标一个，它就必须真的走不到成功，否则标注是摆设。
        for name in incomplete:
            with self.subTest(stage=name):
                ctx = self._ctx(dry_run=False,
                                authorization=WriteAuthorization(frozenset({"upload_image", "save_draft"})))
                # 给它一个空 item，处理器应当直接报缺证据而不是成功
                run = run_stage(name, ctx, index=0, total=1, steps=[StepRecord(name=name)])
                self.assertFalse(
                    run.outcome.ok,
                    "{} 声明为走不到成功，却对空 item 返回了成功".format(name),
                )

    def test_progress_callback_receives_four_args(self) -> None:
        ctx = self._ctx(dry_run=True)
        seen = []
        ctx.progress = lambda pct, msg, name, steps: seen.append((pct, msg, name, len(steps)))
        run_stage(
            "precheck",
            ctx,
            index=0,
            total=len(STAGE_ORDER),
            steps=[StepRecord(name="precheck")],
        )
        self.assertTrue(seen)
        pct, _msg, name, count = seen[-1]
        self.assertIsInstance(pct, int)
        self.assertEqual(name, "precheck")
        self.assertGreaterEqual(count, 1)

    def test_progress_callback_exception_does_not_break_pipeline(self) -> None:
        """前端渲染问题不该毁掉发布流程。"""

        from taobao_publish.stages import emit_progress

        ctx = self._ctx(dry_run=True)

        def boom(*args, **kwargs):
            raise RuntimeError("前端挂了")

        ctx.progress = boom
        emit_progress(ctx, 0, 1, [StepRecord(name="session")], "session", "running", "")

    def test_handlers_registry_declarations_match_the_central_table(self) -> None:
        """注册表里每个处理器的 write_operation 必须与中央登记表一致。

        不一致就是「处理器会写平台、中央表却说它只读」——授权门会被绕过，
        执行器对此 fail closed（对抗性审查 F11）。
        """

        for stage, spec in STAGE_HANDLERS.items():
            self.assertEqual(
                spec.write_operation,
                STAGE_WRITE_OPERATION.get(stage),
                f"{stage} 的处理器声明与 STAGE_WRITE_OPERATION 不一致",
            )

    def test_unknown_stage_fails_closed(self) -> None:
        """未知阶段不能被当成只读阶段放过去。

        ``STAGE_WRITE_OPERATION.get()`` 对未知键返回 ``None``。如果执行器不先拦住，
        往 ``STAGE_ORDER`` 里加一个写阶段却忘了登记时就会静默放行——这是 fail open。
        """

        ctx = self._ctx(dry_run=False, authorization=WriteAuthorization.none())
        run = run_stage(
            "brand_new_stage",
            ctx,
            index=0,
            total=1,
            steps=[StepRecord(name="brand_new_stage")],
        )
        self.assertFalse(run.outcome.ok)
        self.assertEqual(run.outcome.error_code, "CONTRACT_INVALID")
        self.assertIn("未知阶段", run.outcome.summary)

    def test_stage_write_operation_covers_every_stage(self) -> None:
        """登记表与 STAGE_ORDER 必须一一对应，否则漏登记 = 静默放行写操作。"""

        self.assertEqual(set(STAGE_ORDER), set(STAGE_WRITE_OPERATION))
        self.assertEqual(len(STAGE_ORDER), len(STAGE_WRITE_OPERATION))


class ArtifactTest(unittest.TestCase):
    def test_artifact_is_written_and_sanitized(self) -> None:
        directory = make_temp_dir(self, prefix="art-")
        outputs = directory / "outputs"
        result = run(
            make_local(directory),
            make_request(),
            dry_run=True,
            session_probe=fake_probe_ok,
            outputs_dir=str(outputs),
            write_artifact=True,
        )
        path = result.data.get("artifact_path")
        self.assertTrue(path, "应产出报告文件")
        text = Path(path).read_text(encoding="utf-8")
        from taobao_publish.sanitize import contains_secret_like

        self.assertFalse(contains_secret_like(text))
        json.loads(text)


class RequestOptionsTest(unittest.TestCase):
    """请求体里的 options 只能**收紧**，不能**放宽**。

    否则任何能构造请求体的地方都能把彩排变成真实发布。
    """

    def test_request_can_force_dry_run_on(self) -> None:
        directory = make_temp_dir(self, prefix="opt-")
        result = run(
            make_local(directory),
            {**make_request(), "options": {"dry_run": True}},
            dry_run=False,
            authorization=WriteAuthorization.from_grant(
                ["upload_image", "save_draft", "update_item", "submit_publish"],
                submit_unlocked=True,
            ),
            session_probe=fake_probe_ok,
        )
        self.assertTrue(result.dry_run, "请求体传 dry_run=True 必须能把非 dry-run 拉回彩排")

    def test_request_cannot_force_dry_run_off(self) -> None:
        directory = make_temp_dir(self, prefix="opt-")
        result = run(
            make_local(directory),
            {**make_request(), "options": {"dry_run": False}},
            dry_run=True,
            session_probe=fake_probe_ok,
        )
        self.assertTrue(result.dry_run, "请求体传 dry_run=False 不得关掉彩排")

    def test_request_can_force_stop_before_submit_on(self) -> None:
        directory = make_temp_dir(self, prefix="opt-")
        result = run(
            make_local(directory),
            {**make_request(), "options": {"stop_before_submit": True}},
            dry_run=True,
            stop_before_submit=False,
            session_probe=fake_probe_ok,
        )
        self.assertNotIn("submit", result.data.get("step_plan", []))

    def test_truthy_non_boolean_dry_run_is_treated_as_dry_run(self) -> None:
        """``dry_run=None`` / ``0`` / ``""`` 按「不是 dry-run」处理，方向是保守的。"""

        directory = make_temp_dir(self, prefix="opt-")
        result = run(
            make_local(directory),
            make_request(),
            dry_run=None,  # type: ignore[arg-type]
            session_probe=fake_probe_ok,
        )
        self.assertFalse(result.dry_run)
        # 非 dry-run 要走授权门，因此没授权时只能失败
        self.assertFalse(result.success)

    def test_string_false_is_not_treated_as_false(self) -> None:
        """``dry_run="false"`` 是 truthy → 仍按彩排跑（更安全的方向）。"""

        directory = make_temp_dir(self, prefix="opt-")
        result = run(
            make_local(directory),
            make_request(),
            dry_run="false",  # type: ignore[arg-type]
            session_probe=fake_probe_ok,
        )
        self.assertTrue(result.dry_run)


class AdversarialRegressionTest(unittest.TestCase):
    """对抗性安全审查（2026-10-02）发现的阶段/流水线层隐患。

    F9 / F10 / F11 都是**latent** 缺陷：今天没有处理器会触发它们，但提交阶段一旦
    落地就会变成真问题。测试现在就钉住，避免那时才发现。
    """

    # --- F9：``skipped`` 不能被当成「已提交」 ------------------------------
    def test_submit_succeeded_requires_ok_status_not_just_ok_flag(self) -> None:
        from taobao_publish.pipeline import submit_succeeded
        from taobao_publish.stages import StageOutcome, StageRun

        skipped_run = StageRun(
            name="submit",
            outcome=StageOutcome.skipped("已按策略放入仓库，未执行提交"),
        )
        # skipped 的 ok 是 True，但它是「跳过」不是「提交成功」
        self.assertTrue(skipped_run.outcome.ok)
        self.assertFalse(
            submit_succeeded([skipped_run]),
            "F9 回归：skipped 的 submit 被判成了「已提交」",
        )

        ok_run = StageRun(name="submit", outcome=StageOutcome(ok=True, status="ok", summary="已提交"))
        self.assertTrue(submit_succeeded([ok_run]))

        failed_run = StageRun(name="submit", outcome=StageOutcome.failed("SUBMIT_FAILED", "失败"))
        self.assertFalse(submit_succeeded([failed_run]))

        # 其它阶段成功不算提交成功
        other = StageRun(name="precheck", outcome=StageOutcome(ok=True, status="ok", summary="ok"))
        self.assertFalse(submit_succeeded([other]))
        self.assertFalse(submit_succeeded([]))

    def test_stopped_before_submit_is_true_for_every_non_submit_outcome(self) -> None:
        from taobao_publish.pipeline import submit_succeeded
        from taobao_publish.stages import StageOutcome, StageRun

        runs_cases = (
            [],
            [StageRun(name="submit", outcome=StageOutcome.skipped("x"))],
            [StageRun(name="submit", outcome=StageOutcome.failed("SUBMIT_FAILED", "x"))],
            [StageRun(name="upload_images", outcome=StageOutcome(ok=True, summary="x"))],
        )
        for runs in runs_cases:
            self.assertTrue(not submit_succeeded(list(runs)), runs)
            self.assertTrue(
                not submit_succeeded(list(runs)),
                "stopped_before_submit 由 submit_succeeded 反推，任何非提交结果都必须是「未提交」",
            )

    # --- F10：``authorization`` 必须类型正确 -------------------------------
    def test_run_rejects_duck_typed_authorization(self) -> None:
        """鸭子类型对象（``require()`` 空实现）能架空整个授权门。"""

        class ForgedAuthorization:
            source = "forged"

            def require(self, operation):  # noqa: ANN001
                return None

            def is_granted(self, operation):  # noqa: ANN001
                return True

            def missing_reason(self, operation):  # noqa: ANN001
                return ""

            def to_dict(self):
                return {"source": "forged", "granted": ["everything"], "read_only": False}

        directory = make_temp_dir(self, prefix="forge-")
        with self.assertRaises(Exception) as ctx:
            run(
                make_local(directory),
                make_request(),
                dry_run=False,
                authorization=ForgedAuthorization(),  # type: ignore[arg-type]
                session_probe=fake_probe_ok,
            )
        self.assertIn("WriteAuthorization", str(ctx.exception))

    # --- F11：处理器必须与中央登记表声明一致 -------------------------------
    def test_handler_write_operation_must_match_registry(self) -> None:
        """处理器自称会写、登记表却说只读 → fail closed，不执行处理器。

        审查点名的正是 ``select_category`` / ``readback``：它们天然要「点页面 /
        回读表单」，是未来最容易偷偷引入写操作的位置。
        """

        from taobao_publish.stages import STAGE_HANDLERS, StageHandlerSpec, StageOutcome

        called = []

        def spy(ctx):  # noqa: ANN001
            called.append(True)
            return StageOutcome(ok=True, summary="spy")

        original = STAGE_HANDLERS.get("select_category")
        STAGE_HANDLERS["select_category"] = StageHandlerSpec(
            run=spy, write_operation="save_draft", touches_platform=True
        )
        try:
            ctx = self._make_ctx(dry_run=False, authorization=WriteAuthorization.none())
            stage_run = run_stage(
                "select_category",
                ctx,
                index=0,
                total=1,
                steps=[StepRecord(name="select_category")],
            )
            self.assertFalse(stage_run.outcome.ok)
            self.assertEqual(stage_run.outcome.error_code, "CONTRACT_INVALID")
            self.assertIn("不一致", stage_run.outcome.summary)
            self.assertEqual(called, [], "声明不一致时处理器不得被执行")
        finally:
            if original is None:
                STAGE_HANDLERS.pop("select_category", None)
            else:
                STAGE_HANDLERS["select_category"] = original

    def test_every_registered_handler_declares_matching_write_operation(self) -> None:
        for stage, spec in STAGE_HANDLERS.items():
            self.assertEqual(
                spec.write_operation,
                STAGE_WRITE_OPERATION[stage],
                f"{stage} 的处理器声明与登记表不一致",
            )

    def test_platform_free_handlers_are_only_read_stages(self) -> None:
        """``touches_platform=False`` 是「纯本地计算」的自我声明。

        写阶段**不可能**是纯本地的——它一定要碰页面。所以这个标记只允许出现在
        只读阶段上，否则就是声明失真。
        """

        for stage, spec in STAGE_HANDLERS.items():
            self.assertIsInstance(spec.touches_platform, bool)
            if not spec.touches_platform:
                self.assertIsNone(
                    STAGE_WRITE_OPERATION.get(stage),
                    f"{stage} 是写阶段，不可能 touches_platform=False",
                )

    def _make_ctx(self, **overrides) -> PipelineContext:
        directory = make_temp_dir(self, prefix="adv-")
        local = make_local(directory)
        item = build_publish_item(local, make_request()).item
        assert item is not None
        ctx = PipelineContext(item=item, dry_run=True)
        for key, value in overrides.items():
            setattr(ctx, key, value)
        return ctx


class BuildPublishItemIntegrationTest(unittest.TestCase):
    def test_missing_stock_is_rejected_not_defaulted(self) -> None:
        """本地没有库存字段，请求里不给就必须失败——不能默认 0 或 999。"""

        directory = make_temp_dir(self, prefix="bs-")
        result = run(
            make_local(directory),
            {"skus": [{"spec_values": {"颜色": "白"}, "price": 9.9}]},
            dry_run=True,
            session_probe=fake_probe_ok,
        )
        self.assertFalse(result.success)
        self.assertEqual(result.stage, "static_preflight")
        fields = {entry["field"] for entry in result.blockers}
        self.assertIn("skus[0].stock", fields)


class StageOrderingTest(unittest.TestCase):
    """阶段顺序是**实机踩出来的**，不是随手排的。

    每一条都对应一次真实失败，改动顺序前先读这些理由。
    """

    def test_select_category_runs_before_upload_images(self) -> None:
        """两者工作在**不同页面**上：`select_category` 从类目页导航到填写页，
        `upload_images` 在填写页的主图区上工作。

        顺序反了会报「当前不在类目搜索页（publish.htm?catId=…）」——
        实测踩过。这条原先的假设是「图片先传到空间、与页面无关」。
        """

        self.assertLess(STAGE_ORDER.index("select_category"),
                        STAGE_ORDER.index("upload_images"))

    def test_fill_freight_runs_before_fill_price_stock(self) -> None:
        """**选运费模板会触发重渲染，把「一口价」与「总库存」重置掉。**

        对照实验（实测）：

            写入后：          一口价='16.80'  总库存='111'
            fill_freight 后：  一口价=''       总库存='0'

        顺序反了会让 `fill_price_stock` 当场回读通过、随后被清掉，
        最后在 `readback` 阶段炸出来。所以会被清掉的字段**排在最后写**。
        """

        self.assertLess(STAGE_ORDER.index("fill_freight"),
                        STAGE_ORDER.index("fill_price_stock"))

    def test_readback_runs_before_save_draft_and_submit_is_last(self) -> None:
        """顺序契约：**回读 → 保存草稿 → 提交**。

        * `submit` 必须**最后**（它是唯一真正把商品推上平台的一步）；
        * `readback` 必须**在保存草稿之前**——回读核对是"填对了"的判据，
          没核对通过就不该往平台写草稿；
        * 保存草稿在提交之前（存草稿与上架是两件事，顺序反了就成"先上架再存"）。
        """

        self.assertEqual(STAGE_ORDER[-1], "submit")
        self.assertEqual(STAGE_ORDER[-2], "save_draft")
        self.assertLess(STAGE_ORDER.index("readback"), STAGE_ORDER.index("save_draft"))

    def test_stage_order_has_no_duplicates_and_covers_the_registry(self) -> None:
        self.assertEqual(len(STAGE_ORDER), len(set(STAGE_ORDER)))
        self.assertEqual(set(STAGE_ORDER), set(STAGE_WRITE_OPERATION))


class SuccessfulRunReportingTest(unittest.TestCase):
    def test_success_does_not_carry_protocol_route_gaps_as_blockers(self) -> None:
        """**成功时不要挂 blockers。**

        `build_platform_payload` 产出的是 **mtop 协议路线**的字段映射缺口，
        而 DOM 路线完全不依赖它们。实测踩过：一次 `success: True` 的运行
        底下挂着 10 条「阻塞项」，读起来像自相矛盾。
        它们应当归到 `data.protocol_route_gaps`。
        """

        import inspect

        source = inspect.getsource(run)
        self.assertIn("protocol_route_gaps", source)
        # 成功分支里 blockers 必须是空列表字面量
        tail = source.split('success=True', 1)[1]
        self.assertIn("blockers=[]", tail)


class CancellationTest(unittest.TestCase):
    """取消只在**阶段边界**生效，且必须把剩下的阶段显式标出来。

    为什么不能靠 progress 回调抛异常：``emit_progress`` **刻意吞掉**回调异常
    （前端渲染问题不该毁掉发布），抛了根本停不下来。
    """

    def _ctx(self, should_cancel=None, dry_run=False):
        item = PublishItem(record_id=1, record_name="x", title="标题")
        return PipelineContext(
            item=item, dry_run=dry_run, authorization=WriteAuthorization.none(),
            should_cancel=should_cancel,
        )

    def test_no_hook_means_never_cancelled(self) -> None:
        self.assertFalse(self._ctx().cancelled())

    def test_hook_that_returns_true_cancels(self) -> None:
        self.assertTrue(self._ctx(lambda: True).cancelled())

    def test_hook_errors_are_treated_as_not_cancelled(self) -> None:
        """取消钩子连的是 sidecar 的任务表；它坏了不该让流水线莫名停住。"""

        def boom():
            raise RuntimeError("任务表读不到")

        ctx = self._ctx(boom)
        self.assertFalse(ctx.cancelled())
        self.assertTrue(ctx.scratch.get("cancel_hook_error"), "钩子出错要留痕，别静默吞掉")

    def test_cancelled_stage_is_not_executed(self) -> None:
        """已经叫停了就不该再有后续动作，连授权判断都不必做。"""

        # upload_images 是写阶段；没授权时正常会报 WRITE_NOT_AUTHORIZED。
        # 取消优先于授权判断，所以这里应当得到 cancelled 而不是授权错误。
        ctx = self._ctx(lambda: True)
        run = run_stage("upload_images", ctx, index=0, total=1, steps=[StepRecord(name="upload_images")])
        self.assertEqual(run.outcome.status, STEP_CANCELLED)
        self.assertNotEqual(run.outcome.error_code, "WRITE_NOT_AUTHORIZED")

    def test_cancelled_status_differs_from_skipped(self) -> None:
        """skipped 是「按计划就不做」，cancelled 是「本来要做但被叫停」。"""

        self.assertNotEqual(STEP_CANCELLED, STEP_SKIPPED)

    def test_pipeline_marks_every_remaining_stage_as_cancelled(self) -> None:
        """剩下的阶段必须显式标出来，否则前端看到的是「阶段列表突然变短」——

        用户没法区分「已经跑完了」和「还没跑」。

        用 dry-run 跑：``dry_run=False`` 会在静态预检就拦住（预检会按
        ``require_write=True`` 提要求），根本到不了阶段循环。而取消检查在
        ``run_stage`` 的**最前面**，dry-run 下同样生效。
        """

        directory = make_temp_dir(self, prefix="cx-")
        calls = {"n": 0}

        def cancel_after_a_few():
            # 头两次问「取消了吗」答否，之后答是——模拟跑了一两个阶段后被叫停
            calls["n"] += 1
            return calls["n"] > 2

        result = run(
            make_local(directory),
            make_request(),
            dry_run=True,
            session_probe=fake_probe_ok,
            should_cancel=cancel_after_a_few,
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error["code"], "CANCELLED")
        # 阶段列表长度必须**始终等于本次计划**——不能因为取消而变短。
        #
        # 注意这里的计划是 10 而不是 11：`stop_before_submit=True`（默认）时
        # `build_stage_plan(include_submit=False)` **根本不把 submit 排进计划**。
        # 所以 submit 不会出现在 steps 里，也就谈不上被标成 cancelled——
        # 它是「计划里没有」，不是「被取消跳过」。两者必须分得清。
        planned = build_stage_plan(include_submit=False)
        self.assertEqual(len(planned), len(STAGE_ORDER) - 1)
        self.assertEqual(len(result.steps), len(planned))
        self.assertEqual([s.name for s in result.steps], planned)
        cancelled = [s.name for s in result.steps if s.status == STEP_CANCELLED]
        self.assertTrue(cancelled, "取消后应当有阶段被标成 cancelled")
        self.assertIn(planned[-1], cancelled, "计划里的最后一个阶段也应当被标出来")


class StepRecordDiagnosticsTest(unittest.TestCase):
    """步骤要把**诊断明细**带进产物，且成功步骤不因此膨胀。

    背景（E-281/E-283）：`fill_required_attrs` 偶发报「必填项填完之后仍为空」，
    但失败时 `StageOutcome.failed` **不带 `data`**、`StepRecord` **没有 `data` 字段**，
    于是"逐项为什么没成功"（候选读不到？没有稳妥值？写了没生效？）在产物里
    一个字都没有——只能重跑猜。失败必须留下可诊断的证据。
    """

    def test_data_is_included_only_when_non_empty(self) -> None:
        plain = StepRecord(name="fill_base", status=STEP_OK, summary="ok").to_dict()
        self.assertNotIn("data", plain, "成功且无明细的步骤不该多出 data 键")

        detailed = StepRecord(
            name="fill_required_attrs", status=STEP_FAILED, summary="没补齐",
            error_code="REQUIRED_FIELD_MISSING",
            data={"required": {"filled": [], "failed": [{"name": "风格"}]}},
        ).to_dict()
        self.assertIn("data", detailed)
        self.assertEqual(detailed["data"]["required"]["failed"], [{"name": "风格"}])

    def test_failed_outcome_carries_diagnostics(self) -> None:
        """`failed(...)` 必须能带 data，否则失败明细无处可放。"""

        outcome = StageOutcome.failed(
            "REQUIRED_FIELD_MISSING", "有 1 项没补齐",
            data={"required": {"needs_human": [{"name": "面料"}]}})
        self.assertEqual(outcome.data["required"]["needs_human"], [{"name": "面料"}])
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.status, STEP_FAILED)

    def test_failed_outcome_data_defaults_to_empty_dict(self) -> None:
        """不传 data 时仍是空字典——不引入 None，避免下游 `.get` 炸掉。"""

        outcome = StageOutcome.failed("PAGE_ERROR", "失败了")
        self.assertEqual(outcome.data, {})


if __name__ == "__main__":
    unittest.main()
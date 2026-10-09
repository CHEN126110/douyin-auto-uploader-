# -*- coding: utf-8 -*-
"""发布前置检查测试。

重点在于**严重级别语义**：dry-run 时证据缺口只是告警（因为「数据对不对」与
「这条路能不能走」是两个问题），真实写入前必须升级为阻塞。
"""

from __future__ import annotations

import unittest

from _helpers import make_image, make_temp_dir

from taobao_publish.authorization import WriteAuthorization
from taobao_publish.constants import ENV_ALLOW_SUBMIT, ENV_ALLOW_WRITE
from taobao_publish.errors import SEVERITY_BLOCKER, SEVERITY_WARNING
from taobao_publish.models import ImageSet, PublishItem, SkuEntry
from taobao_publish.preflight import (
    PageSnapshot,
    check_authorization,
    check_page_snapshot,
    check_workbench_ready,
    host_of,
    is_allowed_host,
    run_preflight,
    run_static_preflight,
)


def valid_item(**overrides) -> PublishItem:
    """构造一个「数据本身完全合法」的商品，用来隔离证据门的影响。"""

    directory = overrides.pop("_dir", None)
    images = overrides.pop("images", None)
    if images is None:
        images = ImageSet()
    return PublishItem(
        record_id=1,
        record_name="ID-1",
        title=overrides.pop("title", "小雏菊碎花袜子女春夏新款中筒袜"),
        skus=overrides.pop("skus", [SkuEntry(spec_values={"颜色": "白"}, price=9.9, stock=100)]),
        images=images,
        **overrides,
    )


class HostHelperTest(unittest.TestCase):
    def test_host_extraction(self) -> None:
        self.assertEqual(host_of("https://item.upload.taobao.com/x?y=1"), "item.upload.taobao.com")
        self.assertEqual(host_of("http://127.0.0.1:9334/json/list"), "127.0.0.1:9334")

    def test_allowed_hosts(self) -> None:
        for url in (
            "https://item.upload.taobao.com/sell/ai/category.htm",
            "https://item.upload.tmall.com/router/publish.htm",
            "https://taobao.com/",
        ):
            self.assertTrue(is_allowed_host(url), url)

    def test_rejects_lookalike_hosts(self) -> None:
        """``notataobao.com`` 这类相似域名必须被拒，避免钓鱼/误操作。"""

        for url in (
            "https://notataobao.com/x",
            "https://taobao.com.evil.example/x",
            "https://evil.example/x",
            "",
        ):
            self.assertFalse(is_allowed_host(url), url)


class CheckPageSnapshotTest(unittest.TestCase):
    def test_none_snapshot_means_static_only(self) -> None:
        self.assertEqual(check_page_snapshot(None), [])

    def test_empty_url_blocks(self) -> None:
        blockers = check_page_snapshot(PageSnapshot(url=""))
        self.assertEqual({item.code for item in blockers}, {"WRONG_PAGE"})

    def test_login_page_blocks(self) -> None:
        blockers = check_page_snapshot(PageSnapshot(url="https://login.taobao.com/member/login.jhtml"))
        self.assertEqual({item.code for item in blockers}, {"LOGIN_REQUIRED"})

    def test_risk_control_takes_priority_over_login(self) -> None:
        snapshot = PageSnapshot(url="https://sec.taobao.com/punish")
        blockers = check_page_snapshot(snapshot)
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0].code, "RISK_CONTROL_HIT")
        self.assertIn("人工", blockers[0].detail)

    def test_foreign_host_blocks(self) -> None:
        blockers = check_page_snapshot(PageSnapshot(url="https://evil.example.com/x"))
        self.assertEqual({item.code for item in blockers}, {"WRONG_PAGE"})

    def test_overlay_confirmed_blocks_and_is_not_auto_dismissed(self) -> None:
        snapshot = PageSnapshot(
            url="https://item.upload.taobao.com/sell/ai/category.htm",
            has_blocking_overlay=True,
        )
        blockers = check_page_snapshot(snapshot)
        self.assertEqual(len(blockers), 1)
        self.assertIn("人工", blockers[0].detail)

    def test_overlay_unevaluated_is_warning_read_only_but_blocker_for_write(self) -> None:
        snapshot = PageSnapshot(url="https://item.upload.taobao.com/sell/ai/category.htm")
        read_only = check_page_snapshot(snapshot, require_write=False)
        self.assertEqual(len(read_only), 1)
        self.assertFalse(read_only[0].is_blocking)

        for_write = check_page_snapshot(snapshot, require_write=True)
        self.assertEqual(len(for_write), 1)
        self.assertTrue(for_write[0].is_blocking)

    def test_valid_page_passes(self) -> None:
        snapshot = PageSnapshot(
            url="https://item.upload.taobao.com/sell/ai/category.htm",
            has_blocking_overlay=False,
        )
        self.assertEqual(check_page_snapshot(snapshot), [])


class CheckWorkbenchReadyTest(unittest.TestCase):
    def test_none_snapshot_is_skipped(self) -> None:
        self.assertEqual(check_workbench_ready(None), [])

    def test_confirmed_absent_blocks(self) -> None:
        snapshot = PageSnapshot(url="https://item.upload.taobao.com/x", has_workbench_root=False)
        blockers = check_workbench_ready(snapshot)
        self.assertEqual({item.code for item in blockers}, {"WRONG_PAGE"})
        self.assertTrue(all(item.is_blocking for item in blockers))

    def test_unevaluated_is_warning_in_read_only_mode(self) -> None:
        """「还没评估」不等于「没问题」，也不等于「有问题」。

        只读预检下出告警；真实写入前必须升级为阻塞——见下一个测试。
        """

        snapshot = PageSnapshot(url="https://item.upload.taobao.com/x", has_workbench_root=None)
        blockers = check_workbench_ready(snapshot, require_write=False)
        self.assertEqual(len(blockers), 1)
        self.assertFalse(blockers[0].is_blocking)
        self.assertIn("尚未确认", blockers[0].detail)

    def test_unevaluated_blocks_when_write_is_required(self) -> None:
        snapshot = PageSnapshot(url="https://item.upload.taobao.com/x", has_workbench_root=None)
        blockers = check_workbench_ready(snapshot, require_write=True)
        self.assertEqual(len(blockers), 1)
        self.assertTrue(blockers[0].is_blocking)

    def test_present_root_passes(self) -> None:
        snapshot = PageSnapshot(url="https://item.upload.taobao.com/x", has_workbench_root=True)
        self.assertEqual(check_workbench_ready(snapshot), [])


class CheckAuthorizationTest(unittest.TestCase):
    def test_read_only_yields_warnings_not_blockers(self) -> None:
        blockers, warnings = check_authorization(WriteAuthorization.none())
        self.assertEqual(blockers, [])
        self.assertTrue(warnings)
        self.assertTrue(all(item.severity == SEVERITY_WARNING for item in warnings))

    def test_fully_authorized_yields_nothing(self) -> None:
        auth = WriteAuthorization.from_grant(
            ["upload_image", "save_draft", "update_item", "submit_publish"],
            submit_unlocked=True,
        )
        blockers, warnings = check_authorization(auth)
        self.assertEqual(blockers, [])
        self.assertEqual(warnings, [])

    def test_submit_uses_its_own_error_code(self) -> None:
        auth = WriteAuthorization.from_grant(["submit_publish"], submit_unlocked=False)
        _, warnings = check_authorization(auth)
        codes = {item.code for item in warnings}
        self.assertIn("SUBMIT_NOT_AUTHORIZED", codes)


class StaticPreflightTest(unittest.TestCase):
    def test_valid_data_passes_in_dry_run_mode(self) -> None:
        """数据合法就该通过；字段证据由 **DOM 路线**满足（2026-10-03 起）。

        协议路线的 ``platform_field`` 仍全是 ``None``，但每个 intent 所属阶段的
        写关键选择器都就位了——``field_mapping.json`` 的 ``blocker_hint``
        本来就写着「**或在 DOM 路线中确认……**」。所以这里不再有证据告警。
        """

        directory = make_temp_dir(self, prefix="pf-")
        main = str(make_image(directory / "m.jpg", (800, 800)))
        item = valid_item(images=ImageSet(main=[main]))

        result = run_static_preflight(item, require_write=False)
        self.assertTrue(result.ready, [b.render() for b in result.blockers])
        self.assertEqual(
            [entry for entry in result.warnings if entry.code == "EVIDENCE_INSUFFICIENT"], [],
            "DOM 路线已经覆盖全部 intent，不该再有证据缺口",
        )

    def test_same_data_blocks_when_write_is_required_and_data_is_bad(self) -> None:
        """**授权门与数据门是独立的**：``require_write=True`` 下数据问题照样拦。

        这条原来叫 `test_same_data_blocks_when_write_is_required`，靠「证据缺口」
        来制造阻塞。证据补齐后改用**数据问题**——它才是真正该拦住写入的东西。
        """

        directory = make_temp_dir(self, prefix="pf-")
        main = str(make_image(directory / "m.jpg", (800, 800)))
        item = valid_item(title="", images=ImageSet(main=[main]))

        result = run_static_preflight(item, require_write=True)
        self.assertFalse(result.ready)
        codes = {entry.code for entry in result.blockers}
        self.assertIn("REQUIRED_FIELD_MISSING", codes)
        self.assertTrue(all(entry.severity == SEVERITY_BLOCKER for entry in result.blockers))

    def test_data_problem_blocks_even_in_dry_run(self) -> None:
        result = run_static_preflight(valid_item(title=""), require_write=False)
        self.assertFalse(result.ready)
        self.assertIn("REQUIRED_FIELD_MISSING", {entry.code for entry in result.blockers})

    def test_image_check_can_be_skipped(self) -> None:
        result = run_static_preflight(
            valid_item(images=ImageSet()),
            require_write=False,
            check_images=False,
        )
        self.assertTrue(result.ready, [b.render() for b in result.blockers])

    def test_to_dict_is_serializable(self) -> None:
        import json

        result = run_static_preflight(valid_item(), require_write=False)
        json.dumps(result.to_dict(), ensure_ascii=False)

    def test_render_lines_are_chinese(self) -> None:
        result = run_static_preflight(valid_item(title=""), require_write=False)
        lines = result.render_lines()
        self.assertTrue(lines[0].startswith("未通过"))
        self.assertTrue(any("[阻塞]" in line for line in lines))


class FullPreflightTest(unittest.TestCase):
    def test_page_and_data_checks_combine(self) -> None:
        snapshot = PageSnapshot(url="https://login.taobao.com/member/login.jhtml")
        result = run_preflight(valid_item(), snapshot=snapshot, require_write=False)
        codes = {entry.code for entry in result.blockers}
        self.assertIn("LOGIN_REQUIRED", codes)

    def test_require_write_upgrades_auth_to_blocker(self) -> None:
        result = run_preflight(
            valid_item(),
            authorization=WriteAuthorization.none(),
            require_write=True,
        )
        self.assertFalse(result.ready)
        codes = {entry.code for entry in result.blockers}
        self.assertIn("WRITE_NOT_AUTHORIZED", codes)

    def test_authorized_write_still_blocked_by_data_problems(self) -> None:
        """**授权打开不等于能发布**——数据问题仍然拦着。这两道门是独立的。

        这条原来靠「证据缺口」制造阻塞；证据补齐后改用**数据问题**。
        属性没变：把两把写锁都打开，也不能让一个标题为空的商品发出去。
        """

        auth = WriteAuthorization.from_grant(
            ["upload_image", "save_draft", "update_item", "submit_publish"],
            submit_unlocked=True,
        )
        result = run_preflight(valid_item(title=""), authorization=auth, require_write=True)
        self.assertFalse(result.ready)
        self.assertIn("REQUIRED_FIELD_MISSING", {entry.code for entry in result.blockers})

    def test_checks_block_reports_authorization_state(self) -> None:
        auth = WriteAuthorization.from_environment({ENV_ALLOW_WRITE: "save_draft"})
        result = run_preflight(valid_item(), authorization=auth, require_write=False)
        self.assertEqual(result.checks["authorization"]["granted"], ["save_draft"])
        self.assertFalse(result.checks["authorization"]["read_only"])
        self.assertFalse(result.checks["require_write"])

    def test_checks_do_not_leak_env_names(self) -> None:
        """授权状态可以回操作名，但**不得**回显环境变量原文里的可疑内容。

        环境变量**名**出现在提示里是刻意的——那正是要告诉用户改哪个变量。
        真正不能出现的是值：无论是未识别的密钥，还是任何 secret 形态的串。
        """

        import json

        from taobao_publish.sanitize import contains_secret_like

        auth = WriteAuthorization.from_environment(
            {ENV_ALLOW_WRITE: "save_draft", ENV_ALLOW_SUBMIT: "1"}
        )
        result = run_preflight(valid_item(), authorization=auth, require_write=False)
        rendered = json.dumps(result.to_dict(), ensure_ascii=False)
        self.assertFalse(contains_secret_like(rendered))
        self.assertEqual(result.checks["authorization"]["granted"], ["save_draft"])
        # 环境变量的**值**不应被原样回显
        self.assertNotIn('"1"', json.dumps(result.checks["authorization"], ensure_ascii=False).replace('"1.0"', ""))

    def test_secret_shaped_grant_token_is_not_echoed(self) -> None:
        """用户把密钥误写进授权变量时，不能把它抄进报告。"""

        auth = WriteAuthorization.from_environment(
            {ENV_ALLOW_WRITE: "upload_image,sk-live-ABCDEF1234567890"}
        )
        payload = auth.to_dict()
        rendered = str(payload)
        self.assertNotIn("sk-live-ABCDEF1234567890", rendered)
        self.assertIn("已隐去", rendered)

    def test_underscore_identifier_grant_token_is_echoed(self) -> None:
        auth = WriteAuthorization.from_environment({ENV_ALLOW_WRITE: "upload_image,typo_op"})
        self.assertIn("typo_op", auth.to_dict()["ignored_tokens"])


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""`docs/04-安全门与授权红线.md` 不许有**路线混淆**，也不许把界面开关说成锁。

## 它犯过的错（与代码里修过的同一类）

第 3 节原文：

> 门 2 证据门：用到的平台字段都是 verified 且带 evidence.source 吗？

**而我们走 DOM 路线**——实测 `dom_write_ready = True` 而 `field_mapping` 里
**0 个 verified**。照这段读会以为项目被证据缺口卡死。

这与**第 41 轮修的 CLI 面板**、**第 42 轮修的就绪度出口**是同一个毛病：
把「另一条路线的门」说成了「本次的门」。**文档是第三处。**

## 另外三件必须写着的

* 门 1 在**哪三个层次**强制（不是纸面策略）；
* 界面上的「真实发布」开关**不是第三把锁**；
* 这道锁**实机验证过**。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import contracts  # noqa: E402
from taobao_publish.pipeline import describe_readiness  # noqa: E402

DOC = SUBPROJECT / "docs" / "04-安全门与授权红线.md"


class SecurityDocTest(unittest.TestCase):
    def setUp(self) -> None:
        self.text = DOC.read_text(encoding="utf-8")
        self.readiness = describe_readiness()
        self.route = contracts.write_route_status()

    def test_doc_exists_and_covers_both_locks(self) -> None:
        for phrase in ("TAOBAO_UPLOAD_ALLOW_WRITE", "TAOBAO_UPLOAD_ALLOW_SUBMIT"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_doc_separates_the_two_routes_when_they_diverge(self) -> None:
        """⚠️ **这一条对应文档犯过的路线混淆。**

        只要「DOM 可用而协议不可用」，文档就必须**显式分开两条路线**
        ——否则读的人会以为 0 个 verified 字段等于发布被卡死。
        """

        if not (self.route["dom_write_ready"] and not self.route["protocol_write_ready"]):
            self.skipTest("两条路线没有分叉，不需要这段澄清")
        for phrase in ("协议路线", "DOM 路线", "platform_field", "选择器"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_doc_does_not_claim_fields_block_the_dom_route(self) -> None:
        """不许把字段缺口说成本次的阻塞。"""

        if not self.route["dom_write_ready"]:
            self.skipTest("DOM 路线还不可用")
        # 文档里必须有一句明确说「字段缺口不构成 DOM 路线的阻塞」
        self.assertIn("不构成发布阻塞", self.text)

    def test_doc_says_where_the_authorization_gate_is_enforced(self) -> None:
        for phrase in ("stage_precheck", "run_stage", "spec.run(ctx)"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_doc_says_rejection_happens_before_the_action(self) -> None:
        """第 49 轮踩过反面：拒绝写在包装层，而动作已经发生。"""

        self.assertIn("动作之前", self.text)

    def test_doc_says_the_ui_toggle_is_not_a_lock(self) -> None:
        self.assertIn("不是第三把锁", self.text)
        self.assertIn("publishMode", self.text)

    def test_doc_records_the_live_verification(self) -> None:
        self.assertIn("verify-submit-lock-holds.py", self.text)
        self.assertIn("SUBMIT_NOT_AUTHORIZED", self.text)

    def test_doc_points_at_the_real_predicates(self) -> None:
        """判据要指向代码里的真名，不是复述。"""

        source = (SUBPROJECT / "taobao_publish" / "contracts.py").read_text(encoding="utf-8")
        for name in ("protocol_write_ready", "dom_write_ready"):
            with self.subTest(name=name):
                self.assertIn(name, source)
                self.assertIn(name, self.text)


class NoRouteConfusionAnywhereTest(unittest.TestCase):
    """**整棵 docs/ 扫一遍**——路线混淆别再出现在第三、第四处。"""

    def test_no_doc_claims_fields_block_publishing_without_route_context(self) -> None:
        route = contracts.write_route_status()
        if not (route["dom_write_ready"] and not route["protocol_write_ready"]):
            self.skipTest("两条路线没有分叉")

        offenders = []
        for path in (SUBPROJECT / "docs").glob("*.md"):
            if path.name == "05-证据日志.md":
                continue  # 证据日志是历史记录，允许保留当时的说法
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if "platform_field" not in line:
                    continue
                # 提到 platform_field 的行，必须同时点明是**协议路线**的判据
                if "协议" not in line and "mtop" not in line:
                    offenders.append("{}: {}".format(path.name, line.strip()[:90]))
        self.assertEqual(offenders, [],
                         "这些行提到 platform_field 却没说它只关协议路线：\n  "
                         + "\n  ".join(offenders))


if __name__ == "__main__":
    unittest.main()

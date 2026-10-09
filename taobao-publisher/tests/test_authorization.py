# -*- coding: utf-8 -*-
"""写操作授权门测试。**这是子项目里最不能出错的测试。**"""

from __future__ import annotations

import unittest

from taobao_publish.authorization import WriteAuthorization, parse_grant
from taobao_publish.constants import (
    ENV_ALLOW_SUBMIT,
    ENV_ALLOW_WRITE,
    WRITE_SAVE_DRAFT,
    WRITE_SUBMIT_PUBLISH,
    WRITE_UPLOAD_IMAGE,
)
from taobao_publish.errors import SubmitNotAuthorizedError, WriteNotAuthorizedError


class ParseGrantTest(unittest.TestCase):
    def test_empty_input_grants_nothing(self) -> None:
        for raw in (None, "", "   ", ",,,"):
            granted, ignored = parse_grant(raw)
            self.assertEqual(granted, frozenset(), f"输入 {raw!r} 不应授予任何权限")
            self.assertEqual(ignored, ())

    def test_parses_known_operations_and_reports_unknown(self) -> None:
        granted, ignored = parse_grant(" upload_image , SAVE_DRAFT ,hack_everything ")
        self.assertEqual(granted, frozenset({WRITE_UPLOAD_IMAGE, WRITE_SAVE_DRAFT}))
        self.assertEqual(ignored, ("hack_everything",))

    def test_secret_shaped_token_is_hidden(self) -> None:
        """误把密钥写进授权变量时，回报里不能出现原文。

        对抗性审查（2026-10-02，F5）：早先的判据 ``^[A-Za-z0-9_]{1,32}$`` 会**放行**
        32 位十六进制 mtop token、``AKIA…`` 与去掉连字符的 ``sk-`` 密钥，
        它们会被原样写进 ``run()`` 的产物。
        """

        cases = (
            "sk-live-ABCDEF1234567890",
            "4f2a9c1d8b7e6a5d4c3b2a1908172635",  # 32 位十六进制 = _m_h5_tk 实测形态
            "AKIAIOSFODNN7EXAMPLE",
            "sklive00011122233344455566",
            "*",
            "1",
        )
        for token in cases:
            granted, ignored = parse_grant(f"upload_image,{token}")
            self.assertEqual(granted, frozenset({WRITE_UPLOAD_IMAGE}))
            self.assertEqual(len(ignored), 1)
            self.assertNotIn(token, " ".join(ignored), f"F5 回归：{token!r} 被原样回显")

    def test_typo_shaped_token_is_still_echoed(self) -> None:
        """真正的拼写错误要能看见，否则用户不知道哪里写错了。"""

        _, ignored = parse_grant("upload_image,uplod_image,hack_everything")
        self.assertEqual(set(ignored), {"uplod_image", "hack_everything"})

    def test_non_string_grant_value_grants_nothing(self) -> None:
        for raw in (1, True, None, ["upload_image"], {"a": 1}, b"upload_image"):
            granted, _ = parse_grant(raw)  # type: ignore[arg-type]
            self.assertEqual(granted, frozenset(), f"{raw!r} 不应授予任何权限")

    def test_truthy_shortcut_is_not_a_grant(self) -> None:
        """``ALLOW_WRITE=1`` / ``=*`` / ``=all`` 这类写法必须**不**授予任何权限。"""

        for raw in ("1", "true", "yes", "all", "*"):
            granted, ignored = parse_grant(raw)
            self.assertEqual(granted, frozenset(), f"{raw!r} 不应被当成通配授权")
            self.assertEqual(len(ignored), 1, f"{raw!r} 应被识别为无效词元")
            # ``*`` 不是标识符形态，会被隐去；其余原样回报（它们本身不含秘密）
            self.assertTrue(ignored[0])


class WriteAuthorizationTest(unittest.TestCase):
    def test_none_is_read_only_and_denies_everything(self) -> None:
        auth = WriteAuthorization.none()
        self.assertTrue(auth.is_read_only)
        for operation in (WRITE_UPLOAD_IMAGE, WRITE_SAVE_DRAFT, WRITE_SUBMIT_PUBLISH):
            self.assertFalse(auth.is_granted(operation))
            with self.assertRaises(WriteNotAuthorizedError):
                auth.require(operation)

    def test_from_environment_default_is_read_only(self) -> None:
        auth = WriteAuthorization.from_environment({})
        self.assertTrue(auth.is_read_only)
        self.assertEqual(auth.source, "environment")

    def test_upload_grant_does_not_unlock_submit(self) -> None:
        """只要没设第二把锁，提交就不能执行——即使白名单里写了它。"""

        auth = WriteAuthorization.from_environment(
            {ENV_ALLOW_WRITE: "upload_image,save_draft,submit_publish"}
        )
        self.assertTrue(auth.is_granted(WRITE_UPLOAD_IMAGE))
        self.assertTrue(auth.is_granted(WRITE_SAVE_DRAFT))
        self.assertFalse(auth.is_granted(WRITE_SUBMIT_PUBLISH))
        with self.assertRaises(SubmitNotAuthorizedError):
            auth.require(WRITE_SUBMIT_PUBLISH)

    def test_submit_lock_alone_does_not_unlock_submit(self) -> None:
        """只要白名单里没有它，第二把锁单独存在也没用。"""

        auth = WriteAuthorization.from_environment({ENV_ALLOW_SUBMIT: "1"})
        self.assertTrue(auth.is_read_only)
        self.assertFalse(auth.is_granted(WRITE_SUBMIT_PUBLISH))
        with self.assertRaises(WriteNotAuthorizedError):
            auth.require(WRITE_SUBMIT_PUBLISH)

    def test_both_locks_unlock_submit(self) -> None:
        auth = WriteAuthorization.from_environment(
            {ENV_ALLOW_WRITE: "submit_publish", ENV_ALLOW_SUBMIT: "1"}
        )
        self.assertTrue(auth.is_granted(WRITE_SUBMIT_PUBLISH))
        auth.require(WRITE_SUBMIT_PUBLISH)  # 不应抛错

    def test_submit_lock_requires_exact_value(self) -> None:
        for raw in ("true", "yes", "0", "01", " 2 "):
            auth = WriteAuthorization.from_environment(
                {ENV_ALLOW_WRITE: "submit_publish", ENV_ALLOW_SUBMIT: raw}
            )
            self.assertFalse(
                auth.is_granted(WRITE_SUBMIT_PUBLISH),
                f"{ENV_ALLOW_SUBMIT}={raw!r} 不应解锁提交",
            )

    def test_submit_lock_rejects_whitespace_wrapped_one(self) -> None:
        """第二把锁必须**精确**等于 ``"1"``，空白包裹也不行。

        对抗性审查（2026-10-02，F6）实测 ``str(...).strip() == "1"`` 让
        ``"1 "`` / ``" 1"`` / ``"1\\n"`` / NBSP / 全角空格包裹的 ``1``、
        以及非字符串的 ``1`` 全部解锁。不可撤销的动作不该容忍形态含糊。
        """

        for raw in ("1 ", " 1", "  1  ", "1\n", "1\r\n", "1\t", "\t1", "\u00a01", "1\u3000", 1):
            auth = WriteAuthorization.from_environment(
                {ENV_ALLOW_WRITE: "submit_publish", ENV_ALLOW_SUBMIT: raw}  # type: ignore[dict-item]
            )
            self.assertFalse(
                auth.is_granted(WRITE_SUBMIT_PUBLISH),
                f"{ENV_ALLOW_SUBMIT}={raw!r} 不应解锁提交（必须精确等于 '1'）",
            )

    def test_submit_lock_accepts_exactly_one(self) -> None:
        auth = WriteAuthorization.from_environment(
            {ENV_ALLOW_WRITE: "submit_publish", ENV_ALLOW_SUBMIT: "1"}
        )
        self.assertTrue(auth.is_granted(WRITE_SUBMIT_PUBLISH))

    def test_read_only_is_false_when_any_operation_granted(self) -> None:
        auth = WriteAuthorization.from_grant([WRITE_SAVE_DRAFT])
        self.assertFalse(auth.is_read_only)
        self.assertTrue(auth.is_granted(WRITE_SAVE_DRAFT))
        self.assertFalse(auth.is_granted(WRITE_UPLOAD_IMAGE))

    def test_missing_reason_is_specific(self) -> None:
        auth = WriteAuthorization.from_environment({ENV_ALLOW_WRITE: "submit_publish"})
        reason = auth.missing_reason(WRITE_SUBMIT_PUBLISH)
        self.assertIn(ENV_ALLOW_SUBMIT, reason)
        self.assertIn("第二把锁", reason)

    def test_to_dict_never_leaks_raw_environment_values(self) -> None:
        auth = WriteAuthorization.from_environment(
            {ENV_ALLOW_WRITE: "upload_image", ENV_ALLOW_SUBMIT: "1"}
        )
        payload = auth.to_dict()
        self.assertEqual(payload["granted"], ["upload_image"])
        self.assertTrue(payload["submit_unlocked"])
        # 不出现任何环境变量原名/原值
        rendered = str(payload)
        self.assertNotIn(ENV_ALLOW_WRITE, rendered)
        self.assertNotIn(ENV_ALLOW_SUBMIT, rendered)

    def test_unknown_operation_name_is_denied_not_defaulted(self) -> None:
        auth = WriteAuthorization.from_grant(["upload_image"])
        with self.assertRaises(WriteNotAuthorizedError):
            auth.require("totally_made_up_operation")

    def test_require_is_case_insensitive(self) -> None:
        auth = WriteAuthorization.from_grant(["upload_image"])
        auth.require("UPLOAD_IMAGE")


if __name__ == "__main__":
    unittest.main()

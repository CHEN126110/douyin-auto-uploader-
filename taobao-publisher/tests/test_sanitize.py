# -*- coding: utf-8 -*-
"""脱敏测试。红线第 3 条的执行体，必须有覆盖。"""

from __future__ import annotations

import json
import unittest

from taobao_publish.sanitize import (
    REDACTED,
    assert_capture_ready,
    assert_clean,
    contains_secret_like,
    sanitize_cookie_string,
    sanitize_headers,
    sanitize_payload,
    sanitize_text,
    sanitize_url,
)

H5_TOKEN = "a" * 32 + "_1790000000000"


class SanitizeTextTest(unittest.TestCase):
    def test_redacts_m_h5_tk(self) -> None:
        text = f"_m_h5_tk={H5_TOKEN}; path=/"
        result = sanitize_text(text)
        self.assertNotIn("a" * 32, result)
        self.assertIn(REDACTED, result)

    def test_redacts_cookie_header(self) -> None:
        text = "Cookie: cookie2=abc123; _tb_token_=deadbeef; cna=xyz"
        result = sanitize_text(text)
        self.assertNotIn("abc123", result)
        self.assertNotIn("deadbeef", result)
        self.assertNotIn("xyz", result)

    def test_redacts_phone_and_email(self) -> None:
        result = sanitize_text("联系人 13812345678 邮箱 seller@example.com")
        self.assertNotIn("13812345678", result)
        self.assertNotIn("seller@example.com", result)

    def test_redacts_signed_url_query(self) -> None:
        url = "https://h5api.m.taobao.com/h5/mtop.x/1.0/?jsv=2.6.2&sign=abcdef123456&t=123"
        result = sanitize_text(url)
        self.assertNotIn("abcdef123456", result)
        self.assertIn("h5api.m.taobao.com", result)

    def test_is_idempotent(self) -> None:
        once = sanitize_text("Cookie: cookie2=abc123; _tb_token_=deadbeef")
        twice = sanitize_text(once)
        self.assertEqual(once, twice)
        self.assertNotIn(REDACTED + REDACTED, twice)


class SanitizeUrlTest(unittest.TestCase):
    def test_url_with_signature_param_gets_whole_query_stripped(self) -> None:
        """含 ``sign`` 的 URL **整条 query 被抹掉**，而不是只抹 sign 的值。

        这是刻意的：``sign`` 由 ``_m_h5_tk`` 令牌派生，泄漏 sign + t + data 等于
        给出一次可重放的请求。所以只要出现签名类参数，就把整个 query 当敏感处理。
        """

        url = "https://h5api.m.taobao.com/h5/mtop.x/1.0/?appKey=12574478&sign=deadbeef&t=123"
        result = sanitize_url(url)
        self.assertNotIn("deadbeef", result)
        self.assertNotIn("12574478", result)
        self.assertEqual(result, "https://h5api.m.taobao.com/h5/mtop.x/1.0/?" + REDACTED)

    def test_redacts_sensitive_query_keys_but_keeps_others(self) -> None:
        """没有签名类参数时按参数名逐个抹，保留非敏感参数供研究使用。"""

        url = "https://example.com/path?nick=seller&uid=12345&api=mtop.x&v=1.0"
        result = sanitize_url(url)
        self.assertNotIn("seller", result)
        self.assertNotIn("12345", result)
        self.assertIn("api=mtop.x", result)
        self.assertIn("v=1.0", result)

    def test_non_sensitive_url_survives_intact(self) -> None:
        url = "https://item.upload.taobao.com/sell/ai/category.htm?spm=1"
        result = sanitize_url(url)
        self.assertNotIn("spm=1", result)  # spm 含场景标识，在敏感名单里
        self.assertIn("item.upload.taobao.com", result)

    def test_url_without_query_passes_through_text_filter(self) -> None:
        self.assertEqual(
            sanitize_url("https://item.upload.taobao.com/sell/ai/category.htm"),
            "https://item.upload.taobao.com/sell/ai/category.htm",
        )

    def test_empty_url(self) -> None:
        self.assertEqual(sanitize_url(""), "")
        self.assertEqual(sanitize_url(None), "")


class SanitizeHeadersTest(unittest.TestCase):
    def test_sensitive_headers_fully_redacted(self) -> None:
        headers = {
            "Cookie": "cookie2=abc; _tb_token_=def",
            "Referer": "https://x.com/?token=zzz",
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        }
        result = sanitize_headers(headers)
        self.assertEqual(result["Cookie"], REDACTED)
        self.assertEqual(result["Referer"], REDACTED)
        self.assertEqual(result["User-Agent"], "Mozilla/5.0")
        self.assertEqual(result["Accept"], "application/json")

    def test_empty(self) -> None:
        self.assertEqual(sanitize_headers(None), {})
        self.assertEqual(sanitize_headers({}), {})


class SanitizeCookieStringTest(unittest.TestCase):
    def test_keeps_names_drops_values(self) -> None:
        raw = "cookie2=abc123; _tb_token_=deadbeef; cna=xyz"
        result = sanitize_cookie_string(raw)
        self.assertIn("cookie2", result)
        self.assertIn("_tb_token_", result)
        self.assertIn("cna", result)
        for secret in ("abc123", "deadbeef", "xyz"):
            self.assertNotIn(secret, result)

    def test_malformed_chunks_are_dropped_not_leaked(self) -> None:
        result = sanitize_cookie_string("garbage-without-equals; a=b")
        self.assertNotIn("garbage-without-equals", result)
        self.assertIn("a=", result)

    def test_empty(self) -> None:
        self.assertEqual(sanitize_cookie_string(None), "")
        self.assertEqual(sanitize_cookie_string(""), "")


class SanitizePayloadTest(unittest.TestCase):
    def test_recursive_redaction(self) -> None:
        payload = {
            "ret": ["SUCCESS::调用成功"],
            "data": {
                "cookie2": "abc123",
                "items": [
                    {"title": "袜子", "sign": "deadbeef"},
                    {"url": "https://x.com/a?token=zzz"},
                ],
                "phone": "13812345678",
            },
        }
        result = sanitize_payload(payload)
        rendered = str(result)
        for secret in ("abc123", "deadbeef", "zzz", "13812345678"):
            self.assertNotIn(secret, rendered)
        self.assertIn("袜子", rendered)

    def test_depth_limit_does_not_crash(self) -> None:
        deep: dict = {}
        cursor = deep
        for _ in range(50):
            cursor["next"] = {}
            cursor = cursor["next"]
        result = sanitize_payload(deep)
        self.assertIsInstance(result, dict)

    def test_scalars_pass_through(self) -> None:
        self.assertEqual(sanitize_payload(1), 1)
        self.assertEqual(sanitize_payload(True), True)
        self.assertEqual(sanitize_payload(None), None)


class SecretSelfCheckTest(unittest.TestCase):
    def test_detects_residual_secret(self) -> None:
        self.assertTrue(contains_secret_like("_m_h5_tk=abcdef_123"))
        self.assertTrue(contains_secret_like("Cookie: cookie2=abc"))

    def test_clean_text_passes(self) -> None:
        self.assertFalse(contains_secret_like("普通中文内容，没有登录态"))
        self.assertFalse(contains_secret_like(f"Cookie: {REDACTED}"))
        self.assertFalse(contains_secret_like(""))

    def test_assert_clean_raises_on_residual_secret(self) -> None:
        with self.assertRaises(ValueError):
            assert_clean("_m_h5_tk=abcdef_123", context="unit-test")
        assert_clean("干净内容", context="unit-test")

    def test_own_report_shaped_json_is_not_flagged(self) -> None:
        """自家报告里的 ``"authorization"`` / ``"cookie2"`` **键**不能被误判成泄漏。

        否则每次 ``run(write_artifact=True)`` 都会因为自己的结构化字段而报错。
        """

        report = json.dumps(
            {
                "authorization": {"source": "environment", "granted": ["save_draft"], "read_only": False},
                "cookie2": [REDACTED],
                "blockers": [],
            },
            ensure_ascii=False,
        )
        self.assertFalse(contains_secret_like(report), report)
        assert_clean(report, context="self-report")


class AdversarialRegressionTest(unittest.TestCase):
    """对抗性安全审查（2026-10-02）发现过的每一类泄漏。

    这些用例**逐条对应一个曾经真实泄漏过的形态**，不允许被削弱。
    审查结论见 ``docs/05-证据日志.md`` 的 R-009 与 ``tmp/review/审查报告.md``。
    """

    COOKIE = (
        "cna=ABCdef123GHI; unb=1234567890; tracknick=mystore; "
        "_m_h5_tk=deadbeefdeadbeefdeadbeefdeadbeef_1790000000000; cookie2=abcdef0123456789; "
        "sgcookie=SGxyz789; _tb_token_=tbtok123; sn=12345; _l_g_=lgvalue; cookie17=UU1234567"
    )

    # --- F1：递归路径必须认识**头部名字** ---------------------------------
    def test_f1_request_headers_cookie_and_auth_are_fully_redacted(self) -> None:
        payload = {
            "request_headers": {
                "Cookie": self.COOKIE,
                "Authorization": "Bearer sk-bearer-000111222",
                "X-Token": "xtok-abcdef000111",
            }
        }
        result = sanitize_payload(payload)
        headers = result["request_headers"]
        self.assertEqual(headers["Cookie"], REDACTED)
        self.assertEqual(headers["Authorization"], REDACTED)
        self.assertEqual(headers["X-Token"], REDACTED)
        rendered = json.dumps(result, ensure_ascii=False)
        for secret in (
            "ABCdef123GHI",
            "1234567890",
            "mystore",
            "lgvalue",
            "UU1234567",
            "sk-bearer-000111222",
            "xtok-abcdef000111",
        ):
            self.assertNotIn(secret, rendered, f"F1 回归：{secret} 泄漏")

    def test_f1_header_names_are_case_insensitive(self) -> None:
        for name in ("cookie", "COOKIE", "Cookie", "set-cookie", "authorization", "X-Token"):
            result = sanitize_payload({name: "secret-value-123"})
            self.assertEqual(result[name], REDACTED, name)

    def test_f1_cookie_string_under_an_unrelated_key_is_still_scrubbed(self) -> None:
        """cookie 串即便挂在 ``post_data`` 这类无关键下，值也不能漏。"""

        result = sanitize_payload({"post_data": self.COOKIE})
        rendered = result["post_data"]
        for secret in ("ABCdef123GHI", "1234567890", "mystore", "lgvalue", "UU1234567"):
            self.assertNotIn(secret, rendered, f"F1 回归：{secret} 泄漏")

    # --- F2：JSON 引号键形态 ---------------------------------------------
    def test_f2_json_quoted_keys_are_redacted(self) -> None:
        cases = [
            ('data={"sign":"cafebabecafebabe","_m_h5_tk":"' + "d" * 32 + '"}',
             ["cafebabecafebabe", "d" * 32]),
            ('{"token" : "tok-abcdef000111"}', ["tok-abcdef000111"]),
            ('{"cookie2":"abcdef0123456789"}', ["abcdef0123456789"]),
            ('{"access_token":"at-000111222333"}', ["at-000111222333"]),
            ('{"_m_h5_tk_enc":"enc-abcdef000111"}', ["enc-abcdef000111"]),
            ("{'sign': 'cafebabecafebabe'}", ["cafebabecafebabe"]),
        ]
        for raw, secrets in cases:
            result = sanitize_text(raw)
            for secret in secrets:
                self.assertNotIn(secret, result, f"F2 回归：{raw!r} 里的 {secret} 泄漏")
            self.assertIn(REDACTED, result)

    def test_f2_result_stays_valid_json(self) -> None:
        """脱敏不能把 JSON 改坏，否则产物没法再被解析。"""

        raw = '{"sign":"cafebabecafebabe","t":"1"}'
        result = sanitize_text(raw)
        self.assertEqual(result, '{"sign":"' + REDACTED + '","t":"1"}')
        json.loads(result)

    def test_f2_assign_is_not_mistaken_for_sign(self) -> None:
        """``assign=`` 里的 ``sign`` 不能被误抹（否则正常文本会被改坏）。"""

        self.assertNotIn(REDACTED, sanitize_text("assign=hello"))

    # --- F3：手机号变形 ---------------------------------------------------
    def test_f3_phone_variants_are_redacted(self) -> None:
        for raw in (
            "13812345678",
            "+8613812345678",
            "008613812345678",
            "8613812345678",
            "１３８１２３４５６７８",
            "138-1234-5678",
            "+86 138 1234 5678",
            "138 1234 5678",
        ):
            self.assertEqual(sanitize_text(raw), REDACTED, f"F3 回归：{raw} 泄漏")

    def test_f3_numeric_phone_scalar_is_redacted(self) -> None:
        self.assertEqual(sanitize_payload({"mobile": 13812345678})["mobile"], REDACTED)

    def test_f3_ordinary_numbers_survive(self) -> None:
        """不能把普通数字也抹掉——脱敏要能用，不是越糊越好。"""

        for raw in ("12345", "800", "4.8", "20509"):
            self.assertEqual(sanitize_text(raw), raw)
        self.assertEqual(sanitize_payload({"price": 4.8})["price"], 4.8)

    # --- F4：URL 百分号编码 -----------------------------------------------
    def test_f4_percent_encoded_signature_params_are_scrubbed(self) -> None:
        cases = [
            ("https://h5api.m.taobao.com/h5/a/1.0/?t=1&%73ign=SIGNVALUE3", "SIGNVALUE3"),
            ("https://h5api.m.taobao.com/h5/a/1.0/?t=1&sign%3DSIGNVALUE5", "SIGNVALUE5"),
            ("https://h5api.m.taobao.com/h5/a/1.0/?q=a%3D1%26sign%3DSIGNVALUE4", "SIGNVALUE4"),
            ("https://h5api.m.taobao.com/h5/a/1.0/?t=1&sign=SIGNVALUE1", "SIGNVALUE1"),
        ]
        for url, secret in cases:
            self.assertNotIn(secret, sanitize_url(url), f"F4 回归：{url} 泄漏")

    # --- F12：bytes 标量 ---------------------------------------------------
    def test_f12_bytes_scalar_is_sanitized(self) -> None:
        result = sanitize_payload({"data": b"_m_h5_tk=bytesvalue123"})
        self.assertNotIn("bytesvalue123", str(result))

    # --- 结构变形 ---------------------------------------------------------
    def test_deeply_nested_secret_is_found(self) -> None:
        payload: dict = {"a": [{"b": [{"c": {"cookie2": "deepsecret123"}}]}]}
        self.assertNotIn("deepsecret123", json.dumps(sanitize_payload(payload)))

    def test_idempotent_on_adversarial_input(self) -> None:
        raw = json.dumps(
            {"sign": "cafebabecafebabe", "_m_h5_tk": "d" * 32, "phone": "13812345678"},
            ensure_ascii=False,
        )
        once = sanitize_text(raw)
        self.assertEqual(once, sanitize_text(once))
        self.assertFalse(contains_secret_like(once))


class CaptureGuardTest(unittest.TestCase):
    """``captures/`` 是要进仓库的目录，守卫必须比普通产物更严。"""

    def test_clean_text_passes(self) -> None:
        assert_capture_ready('{"title": "袜子", "ret": ["SUCCESS::ok"]}', context="t")

    def test_residual_secret_fails(self) -> None:
        with self.assertRaises(ValueError):
            assert_capture_ready("_m_h5_tk=abcdef_123", context="t")

    def test_bare_marker_without_redaction_fails(self) -> None:
        """敏感字段名字出现、附近却没有脱敏占位符 → 说明脱敏漏了。

        这一类 ``contains_secret_like`` 抓不到（没有 ``=值`` 形态），只有
        captures 守卫会拦。
        """

        text = "请求头里带了 Authorization 字段，值没记下来"
        self.assertFalse(contains_secret_like(text), "本条应由 captures 守卫拦截，而非 assert_clean")
        with self.assertRaises(ValueError) as ctx:
            assert_capture_ready(text, context="t")
        self.assertIn("captures", str(ctx.exception))

    def test_sanitized_marker_passes(self) -> None:
        assert_capture_ready(f'"Authorization": "{REDACTED}"', context="t")
        assert_capture_ready(f"cookie2={REDACTED} 已抹除", context="t")


if __name__ == "__main__":
    unittest.main()

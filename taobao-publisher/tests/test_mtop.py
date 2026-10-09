# -*- coding: utf-8 -*-
"""mtop 签名与响应分类测试。

签名算法来自实证（读路径 ``app.py:10875-10903`` + 外部资料），因此这里用
**硬编码向量**锁死实现——算法一旦被改坏，测试必须红。
"""

from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qs, urlparse

from taobao_publish.mtop import (
    H5_APP_KEY_DEFAULT,
    RET_ILLEGAL_ACCESS,
    RET_SESSION_EXPIRED,
    RET_SUCCESS,
    RET_TOKEN_EXPIRED,
    build_headers,
    build_request,
    canonical_data,
    classify_response,
    extract_h5_tk_from_set_cookie,
    parse_h5_tk,
    sign,
)


class SignTest(unittest.TestCase):
    def test_known_vectors_are_stable(self) -> None:
        """硬编码向量。格式 ``md5(token&t&appKey&data)`` 被改坏时必须失败。"""

        self.assertEqual(sign("abc", "123", "key", "{}"), "f0b2fd2247228e81877d4aa6305137ce")
        self.assertEqual(
            sign("0" * 32, "1700000000000", "12574478", '{"shopId":"1"}'),
            "5760dcc2fdada7223b4356f72022f1d6",
        )

    def test_empty_inputs_raise(self) -> None:
        for token, ts, app_key in (("", "1", "k"), ("t", "", "k"), ("t", "1", "")):
            with self.assertRaises(ValueError):
                sign(token, ts, app_key, "{}")

    def test_data_is_part_of_the_signature(self) -> None:
        self.assertNotEqual(sign("t", "1", "k", "{}"), sign("t", "1", "k", '{"a":1}'))

    def test_timestamp_is_part_of_the_signature(self) -> None:
        self.assertNotEqual(sign("t", "1", "k", "{}"), sign("t", "2", "k", "{}"))


class CanonicalDataTest(unittest.TestCase):
    def test_dict_is_compact_and_preserves_key_order(self) -> None:
        self.assertEqual(canonical_data({"b": 1, "a": 2}), '{"b":1,"a":2}')

    def test_string_passes_through_verbatim(self) -> None:
        raw = '{"x": 1}'
        self.assertEqual(canonical_data(raw), raw)

    def test_chinese_is_not_escaped(self) -> None:
        self.assertEqual(canonical_data({"t": "袜子"}), '{"t":"袜子"}')


class ParseH5TkTest(unittest.TestCase):
    def test_parses_token_and_expiry(self) -> None:
        parsed = parse_h5_tk("a" * 32 + "_1790000000000")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.value, "a" * 32)
        self.assertEqual(parsed.expire_at_ms, 1790000000000)
        self.assertTrue(parsed.is_well_formed)

    def test_token_without_separator_is_rejected(self) -> None:
        """没有 ``_`` 分隔符的值形态非法，**fail closed** 返回 None。

        宁可让调用方去刷新 token，也不要拿一个切错的值去签名——那只会换来
        ``FAIL_SYS_ILLEGAL_ACCESS``，还看不出是本地解析错了。
        """

        self.assertIsNone(parse_h5_tk("b" * 32))

    def test_invalid_inputs_return_none(self) -> None:
        for raw in (None, "", "   ", "_1790000000000"):
            self.assertIsNone(parse_h5_tk(raw))

    def test_expires_within_uses_expiry(self) -> None:
        parsed = parse_h5_tk("c" * 32 + "_1000")
        assert parsed is not None
        # 已到期 → 视为需要刷新
        self.assertTrue(parsed.expires_within(0, now=1001))
        # 恰好到期 → 视为需要刷新
        self.assertTrue(parsed.expires_within(0, now=1000))
        # 还有 1ms → 不触发刷新
        self.assertFalse(parsed.expires_within(0, now=999))
        # 提前量大于剩余寿命 → 触发刷新
        self.assertTrue(parsed.expires_within(500, now=999))

    def test_describe_does_not_leak_token(self) -> None:
        parsed = parse_h5_tk("s" * 32 + "_1000")
        assert parsed is not None
        rendered = json.dumps(parsed.describe())
        self.assertNotIn("s" * 32, rendered)
        self.assertIn('"token_length": 32', rendered)


class BuildRequestTest(unittest.TestCase):
    def test_url_contains_sign_and_data_goes_to_body(self) -> None:
        request = build_request(
            "mtop.taobao.shop.simple.item.fetch",
            {"shopId": "1"},
            "a" * 32,
            timestamp_ms="1700000000000",
        )
        parsed = urlparse(request.url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "h5api.m.taobao.com")
        self.assertEqual(parsed.path, "/h5/mtop.taobao.shop.simple.item.fetch/1.0/")
        self.assertEqual(query["appKey"][0], H5_APP_KEY_DEFAULT)
        self.assertEqual(query["t"][0], "1700000000000")
        self.assertEqual(query["sign"][0], sign("a" * 32, "1700000000000", H5_APP_KEY_DEFAULT, '{"shopId":"1"}'))
        # data 不进 query，走 body
        self.assertNotIn("data", query)
        body = parse_qs(request.body.decode("utf-8"))
        self.assertEqual(body["data"][0], '{"shopId":"1"}')

    def test_describe_is_sanitized(self) -> None:
        request = build_request("mtop.x", {"a": 1}, "z" * 32, timestamp_ms="1")
        rendered = json.dumps(request.describe(), ensure_ascii=False)
        self.assertNotIn("z" * 32, rendered)
        self.assertNotIn("sign=", rendered)

    def test_empty_api_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_request("", {}, "t" * 32)

    def test_headers_include_cookie_when_asked(self) -> None:
        headers = build_headers(cookie_str="cookie2=x", referer="https://x.com/")
        self.assertEqual(headers["Cookie"], "cookie2=x")
        self.assertEqual(headers["Referer"], "https://x.com/")


class ClassifyResponseTest(unittest.TestCase):
    def test_success(self) -> None:
        payload = json.dumps({"ret": ["SUCCESS::调用成功"], "data": {"x": 1}})
        result = classify_response(payload)
        self.assertTrue(result.ok)
        self.assertEqual(result.message, "调用成功")

    def test_token_expired_is_marked_retryable(self) -> None:
        payload = json.dumps({"ret": [f"{RET_TOKEN_EXPIRED}::令牌过期"]})
        result = classify_response(payload)
        self.assertFalse(result.ok)
        self.assertTrue(result.is_token_retryable)
        self.assertEqual(result.error_code, "LOGIN_REQUIRED")

    def test_auth_failures(self) -> None:
        for code in (RET_SESSION_EXPIRED, RET_ILLEGAL_ACCESS):
            result = classify_response(json.dumps({"ret": [f"{code}::失败"]}))
            self.assertTrue(result.is_auth_failure, code)
            self.assertFalse(result.ok)

    def test_unknown_code_falls_back_to_platform_error(self) -> None:
        result = classify_response(json.dumps({"ret": ["FAIL_BIZ_SOMETHING_NEW::新的失败"]}))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "PLATFORM_ERROR")
        self.assertEqual(result.message, "新的失败")

    def test_risk_page_detected_for_non_json(self) -> None:
        html = "<html><script>window._sec_ = 1; baxia();</script></html>"
        result = classify_response(html)
        self.assertFalse(result.ok)
        self.assertTrue(result.is_risk_page)
        self.assertEqual(result.error_code, "RISK_CONTROL_HIT")

    def test_non_json_without_marker_is_plain_error(self) -> None:
        result = classify_response("<html>502 Bad Gateway</html>")
        self.assertFalse(result.is_risk_page)
        self.assertEqual(result.error_code, "PLATFORM_ERROR")

    def test_missing_ret(self) -> None:
        result = classify_response(json.dumps({"data": {}}))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "PLATFORM_ERROR")

    def test_broken_json_is_object_like(self) -> None:
        result = classify_response("{not json")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "PLATFORM_ERROR")

    def test_empty_response(self) -> None:
        for raw in (None, ""):
            result = classify_response(raw)
            self.assertFalse(result.ok)

    def test_ret_as_string_not_list(self) -> None:
        result = classify_response(json.dumps({"ret": f"{RET_SUCCESS}::ok"}))
        self.assertTrue(result.ok)

    def test_describe_is_serializable(self) -> None:
        result = classify_response(json.dumps({"ret": ["SUCCESS::ok"]}))
        json.dumps(result.describe())


class SetCookieTest(unittest.TestCase):
    def test_extracts_new_token(self) -> None:
        token = extract_h5_tk_from_set_cookie(
            [
                "other=1; Path=/",
                f"_m_h5_tk={'d' * 32}_1790000000000; Path=/; HttpOnly",
            ]
        )
        self.assertIsNotNone(token)
        assert token is not None
        self.assertEqual(token.value, "d" * 32)
        self.assertEqual(token.expire_at_ms, 1790000000000)

    def test_returns_none_when_absent(self) -> None:
        self.assertIsNone(extract_h5_tk_from_set_cookie(["a=1; Path=/"]))
        self.assertIsNone(extract_h5_tk_from_set_cookie(None))
        self.assertIsNone(extract_h5_tk_from_set_cookie([]))


if __name__ == "__main__":
    unittest.main()

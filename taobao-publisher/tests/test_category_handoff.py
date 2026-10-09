# -*- coding: utf-8 -*-
"""类目到填写页的交接必须由真实目标 URL 与 catId 证明；全部使用内存页面。"""

from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest import mock

from taobao_publish import page, stages
from taobao_publish.models import CategoryRef, PublishItem


CATEGORY_URL = "https://item.upload.taobao.com/sell/ai/category.htm"
FORM_URL = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=202187801"


class NavigationPage:
    def __init__(self, urls):
        self.urls = list(urls)
        self.last_url = self.urls[-1]
        self.clicks = 0
        self.closed = False

    def evaluate(self, expression):
        if expression == "location.href":
            return self.urls.pop(0) if self.urls else self.last_url
        if ".click()" in expression:
            self.clicks += 1
            return {"ok": True}
        return {"present": True, "visible": True, "disabled": False}

    def close(self):
        self.closed = True


def ticking_clock():
    now = 0.0

    def read():
        nonlocal now
        now += 0.5
        return now

    return read


class ConfirmCategoryNavigationTest(unittest.TestCase):
    def confirm(self, urls):
        client = NavigationPage(urls)
        with mock.patch.object(page.time, "time", side_effect=ticking_clock()), \
                mock.patch.object(page.time, "sleep"):
            result = page.confirm_category_and_read_id(client, wait=3)
        self.assertEqual(client.clicks, 1, "等待页面不应该重复点击下一步")
        return result

    def test_staying_on_category_page_is_a_failure(self):
        with self.assertRaises(page.PageError):
            self.confirm([CATEGORY_URL])

    def test_waits_for_navigation_and_reads_the_authoritative_category(self):
        result = self.confirm([CATEGORY_URL, FORM_URL])
        self.assertEqual(result, {"category_id": "202187801", "href": FORM_URL})

    def test_invalid_destination_or_category_cannot_be_success(self):
        urls = [
            "https://example.test/sell/v2/publish.htm?catId=202187801",
            "https://item.upload.taobao.com.example.test/sell/v2/publish.htm?catId=202187801",
            "https://item.upload.taobao.com/other/publish.htm?catId=202187801",
            "http://item.upload.taobao.com/sell/v2/publish.htm?catId=202187801",
            "https://item.upload.taobao.com/sell/v2/publish.htm",
            "https://item.upload.taobao.com/sell/v2/publish.htm?catId=",
            "https://item.upload.taobao.com/sell/v2/publish.htm?catId=not-a-category",
            "https://item.upload.taobao.com/sell/v2/publish.htm?catId=0",
            "https://item.upload.taobao.com/sell/v2/publish.htm?catId=202187801&catId=999",
        ]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(page.PageError):
                self.confirm([url])

    def test_invisible_next_button_is_not_clicked(self):
        client = NavigationPage([FORM_URL])
        with mock.patch.object(page, "read_confirm_button_state", return_value={
                "present": True, "disabled": False, "visible": False}), \
                self.assertRaises(page.PageError):
            page.confirm_category_and_read_id(client)
        self.assertEqual(client.clicks, 0)

    def test_disabled_or_unknown_next_button_is_not_clicked(self):
        for state in ({"present": True, "visible": True, "disabled": True},
                      {"present": True, "visible": True}, {"visible": True, "disabled": False}):
            client = NavigationPage([FORM_URL])
            with self.subTest(state=state), mock.patch.object(
                    page, "read_confirm_button_state", return_value=state), self.assertRaises(page.PageError):
                page.confirm_category_and_read_id(client)
            self.assertEqual(client.clicks, 0)


class SelectCategoryHandoffTest(unittest.TestCase):
    def run_stage(self, resolved, expected_id="", *, keyword="", path=("上级", "目标类目"),
                  leaf_result=None):
        item = PublishItem(record_id=1, record_name="offline", title="offline",
                           category=CategoryRef(path=path,
                                                category_id=expected_id))
        if keyword:
            item.category = SimpleNamespace(path=path, category_id=expected_id,
                                            search_keyword=keyword)
        ctx = stages.PipelineContext(item=item, dry_run=False)
        client = NavigationPage([CATEGORY_URL])
        replacements = {
            "read_brand_control_state": {"present": False, "hitCount": 0},
            "search_category": {}, "switch_category_tab": {},
            "find_exact_category_candidate": {}, "click_unique_text": {},
            "wait_for_selected_category": list((leaf_result or {}).get("path") or item.category.path),
            "read_confirm_button_state": {"present": True, "visible": True, "disabled": False},
            "confirm_category_and_read_id": resolved,
        }
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(stages, "_open_publish_page", return_value=client))
            leaf = stack.enter_context(mock.patch.object(page, "find_leaf_category_candidate",
                                                        return_value=leaf_result))
            for name, value in replacements.items():
                stack.enter_context(mock.patch.object(page, name, return_value=value))
            result = stages.stage_select_category(ctx)
        if keyword and not path:
            leaf.assert_called_once_with(client, keyword)
        else:
            leaf.assert_not_called()
        self.assertTrue(client.closed)
        return result, ctx

    def test_empty_or_unconfirmed_handoff_is_not_recorded_as_success(self):
        for resolved in ({"category_id": "", "href": CATEGORY_URL},
                         {"category_id": "202187801", "href": CATEGORY_URL},
                         {"category_id": "999", "href": FORM_URL}):
            with self.subTest(resolved=resolved):
                result, ctx = self.run_stage(resolved)
                self.assertFalse(result.ok)
                self.assertNotIn("resolved_category_id", ctx.scratch)

    def test_explicit_category_mismatch_is_rejected(self):
        result, ctx = self.run_stage({"category_id": "202187801", "href": FORM_URL}, "999")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "SELECTION_NOT_CONFIRMED")
        self.assertNotIn("resolved_category_id", ctx.scratch)

    def test_confirmed_category_is_recorded_when_id_is_absent_or_matches(self):
        for expected_id in ("", "202187801"):
            with self.subTest(expected_id=expected_id):
                result, ctx = self.run_stage({"category_id": "202187801", "href": FORM_URL}, expected_id)
                self.assertTrue(result.ok)
                self.assertEqual(ctx.scratch["resolved_category_id"], "202187801")

    def test_keyword_resolves_full_path_from_the_unique_platform_candidate(self):
        result, ctx = self.run_stage(
            {"category_id": "202187801", "href": FORM_URL}, keyword="中筒袜", path=(),
            leaf_result={"path_text": "平台上级>中筒袜", "path": ["平台上级", "中筒袜"]})
        self.assertTrue(result.ok)
        self.assertEqual(ctx.item.category.path, ("平台上级", "中筒袜"))
        self.assertEqual(ctx.item.category.category_id, "202187801")
        self.assertEqual(ctx.scratch["resolved_category_path"], ["平台上级", "中筒袜"])


class LeafCategoryCandidateTest(unittest.TestCase):
    def find(self, candidates):
        client = mock.Mock()
        client.evaluate.return_value = {"candidates": candidates}
        result = page.find_leaf_category_candidate(client, "中筒袜")
        client.evaluate.assert_called_once()
        return result

    def test_reads_the_actual_full_path_and_matches_only_the_leaf(self):
        result = self.find(["其他上级>中筒袜裤", "平台上级>中筒袜", "中筒袜>其他叶子"])
        self.assertEqual(result["path_text"], "平台上级>中筒袜")
        self.assertEqual(result["path"], ["平台上级", "中筒袜"])

    def test_missing_or_ambiguous_leaf_is_rejected_instead_of_picking_first(self):
        for candidates in ([], ["上级>长筒袜"], ["上级甲>中筒袜", "上级乙>中筒袜"],
                           ["上级>中筒袜", "上级>中筒袜"]):
            with self.subTest(candidates=candidates), self.assertRaises(page.CandidateNotFound):
                self.find(candidates)

    def test_incomplete_platform_path_is_rejected(self):
        with self.assertRaises(page.PageError):
            self.find(["上级>>中筒袜"])


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""离线反例：未选择属性、缺失 SKU、错价库存及无法确认身份的旧主图。"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import hashlib
from io import BytesIO
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock

from PIL import Image

SUBPROJECT = pathlib.Path(__file__).resolve().parents[1]
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page, stages
from taobao_publish import protocol_media
from taobao_publish.models import PublishItem, SkuEntry


def context(skus=()):
    return stages.PipelineContext(
        item=PublishItem(record_id=1, record_name="ID-1", title="标题", skus=list(skus)),
        dry_run=False,
    )


class SkuCreationIntegrityTest(unittest.TestCase):
    def test_a_visible_but_unselected_required_attribute_is_selected(self):
        ctx = context([SkuEntry(spec_values={"尺码": "M"}, price=12, stock=3)])
        initial = {"open": True, "props": [{"name": "尺码", "selected": False}],
                   "blocks": [{"name": "尺码", "count": 1, "rowValues": ["M"]}]}
        selected = {**initial, "props": [{"name": "尺码", "selected": True}]}
        table = {"tableCount": 1, "rowCount": 1, "rows": [{"specs": ["M"]}]}
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(stages, "_open_publish_page", return_value=mock.Mock()))
            stack.enter_context(mock.patch.object(page, "open_sku_drawer"))
            stack.enter_context(mock.patch.object(page, "read_sku_drawer_state", side_effect=[initial, selected, selected]))
            selector = stack.enter_context(mock.patch.object(page, "set_prop_selected"))
            stack.enter_context(mock.patch.object(page, "confirm_sku_creation"))
            stack.enter_context(mock.patch.object(page, "wait_for_sku_table", return_value=table))
            stack.enter_context(mock.patch.object(page, "read_sku_table", return_value=table))
            stack.enter_context(mock.patch.object(page, "set_sku_row_numbers"))
            stack.enter_context(mock.patch.object(page, "read_sku_row_numbers", return_value=[
                {"specs": ["M"], "price": "12.00", "stock": "3"}]))
            outcome = stages.stage_fill_skus(ctx)
        self.assertTrue(outcome.ok, outcome.summary)
        selector.assert_called_once()
        self.assertEqual(selector.call_args.args[1:], ("尺码", True))

    def test_a_missing_attribute_reports_the_candidate_error(self):
        ctx = context([SkuEntry(spec_values={"尺码": "M"}, price=12, stock=3)])
        state = {"open": True, "props": [{"name": "尺码", "selected": True}], "blocks": []}
        with mock.patch.object(stages, "_open_publish_page", return_value=mock.Mock()), \
                mock.patch.object(page, "open_sku_drawer"), \
                mock.patch.object(page, "read_sku_drawer_state", return_value=state), \
                mock.patch.object(page, "confirm_sku_creation") as confirm:
            outcome = stages.stage_fill_skus(ctx)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "CANDIDATE_NOT_FOUND")
        self.assertNotIn("NameError", outcome.summary)
        confirm.assert_not_called()

    def test_an_incomplete_table_is_rejected_before_any_price_write(self):
        ctx = context([SkuEntry(spec_values={"尺码": "M"}, price=12, stock=3),
                       SkuEntry(spec_values={"尺码": "L"}, price=15, stock=4)])
        table = {"tableCount": 1, "rowCount": 1, "rows": [{"specs": ["M"]}]}
        with mock.patch.object(page, "read_sku_table", return_value=table), \
                mock.patch.object(page, "set_sku_row_numbers") as setter:
            with self.assertRaises(page.CandidateNotFound):
                stages._fill_sku_row_numbers(mock.Mock(), page, ctx)
        setter.assert_not_called()

    def test_duplicate_platform_rows_are_rejected_before_any_price_write(self):
        ctx = context([SkuEntry(spec_values={"尺码": "M"}, price=12, stock=3),
                       SkuEntry(spec_values={"尺码": "L"}, price=15, stock=4)])
        table = {"rows": [{"specs": ["M"]}, {"specs": ["M"]}]}
        with mock.patch.object(page, "read_sku_table", return_value=table), \
                mock.patch.object(page, "set_sku_row_numbers") as setter:
            with self.assertRaises(page.CandidateNotFound):
                stages._fill_sku_row_numbers(mock.Mock(), page, ctx)
        setter.assert_not_called()


class SkuFinalReadbackIntegrityTest(unittest.TestCase):
    def _readback(self, actual):
        ctx = context([SkuEntry(spec_values={"尺码": "M"}, price=12, stock=3),
                       SkuEntry(spec_values={"尺码": "L"}, price=15, stock=4)])
        fields = {"宝贝标题": "标题", "一口价": "24.00", "总库存": "7"}
        with mock.patch.object(stages, "_open_publish_page", return_value=mock.Mock()), \
                mock.patch.object(page, "read_text_field", side_effect=lambda _client, label: fields[label]), \
                mock.patch.object(page, "read_sku_table", return_value={"rows": [
                    {"specs": ["M"]}, {"specs": ["L"]}]}), \
                mock.patch.object(page, "read_sku_row_numbers", return_value=actual), \
                mock.patch.object(page, "read_submit_state", return_value={"submit": {
                    "present": True, "visible": True, "disabled": False}}), \
                mock.patch.object(page, "read_required_form", return_value={'known': True, 'scope': 'visible_publish_rows_required', 'completePage': False, 'rowCount': 1, 'required': [], 'unownedRequiredCount': 0}), \
                mock.patch.object(page, "read_required_properties", return_value={
                    "known": True, "rowCount": 1, "scope": "visible_property_label_required",
                    "completePage": False, "required": []}), \
                mock.patch.object(page, "read_selected_options", return_value=[]):
            return stages.stage_readback(ctx)

    def test_positive_but_swapped_sku_prices_fail_final_readback(self):
        out = self._readback([{"specs": ["M"], "price": "15", "stock": "3"},
                              {"specs": ["L"], "price": "12", "stock": "4"}])
        self.assertFalse(out.ok)
        self.assertTrue(any(blocker.field == "SKU 逐行价格库存" for blocker in out.blockers))

    def test_changed_sku_stock_fails_even_when_the_total_matches(self):
        out = self._readback([{"specs": ["M"], "price": "12", "stock": "4"},
                              {"specs": ["L"], "price": "15", "stock": "3"}])
        self.assertFalse(out.ok)
        self.assertTrue(any(blocker.field == "SKU 逐行价格库存" for blocker in out.blockers))

    def test_equivalent_numeric_formatting_and_row_order_are_accepted(self):
        expected = [{"specs": ["M"], "price": 12, "stock": 3},
                    {"specs": ["L"], "price": 15, "stock": 4}]
        actual = [{"specs": ["L"], "price": "15.00", "stock": "04"},
                  {"specs": ["M"], "price": "12.0", "stock": "3"}]
        self.assertEqual(stages._format_sku_row_values(expected), stages._format_sku_row_values(actual))

    def test_reordered_sku_rows_pass_the_complete_readback(self):
        out = self._readback([{"specs": ["L"], "price": "15.00", "stock": "4"},
                              {"specs": ["M"], "price": "12.0", "stock": "3"}])
        self.assertTrue(out.ok, out.summary)


class MainImageIntegrityTest(unittest.TestCase):
    @staticmethod
    def _image_bytes():
        output = BytesIO()
        Image.new('RGB', (16, 16), (40, 80, 120)).save(output, format='JPEG')
        return output.getvalue()

    def _run(self, filled_before, *, missing_url=False):
        with tempfile.TemporaryDirectory() as directory:
            files = [str(pathlib.Path(directory) / (name + ".jpg")) for name in ("a", "b")]
            for filename in files:
                pathlib.Path(filename).write_bytes(self._image_bytes())
            ctx = context()
            ctx.item.images.main = files
            before = {"found": True, "filled": filled_before, "images": ["old"] * filled_before}
            after = {"found": True, "filled": 2, "images": ["url-a"] if missing_url else ["url-a", "url-b"]}
            with ExitStack() as stack:
                client = mock.Mock()
                client.evaluate.return_value = {'ok': True, 'supported': False, 'path': []}
                stack.enter_context(mock.patch.object(stages, "_open_publish_page", return_value=client))
                stack.enter_context(mock.patch.object(page, "read_main_image_slots", return_value=before))
                opener = stack.enter_context(mock.patch.object(page, "open_media_popup"))
                stack.enter_context(mock.patch.object(page, "read_media_popup", return_value={"open": True}))
                stack.enter_context(mock.patch.object(page, "media_iframe_context", return_value=1))
                stack.enter_context(mock.patch.object(page, "find_media_images", side_effect=lambda client, names, **kwargs: {
                    'receipts': {name: {'url': url} for name, url in zip(names, ['url-a', 'url-b'])}, 'missing': []}))
                upload = stack.enter_context(mock.patch.object(page, "upload_files_to_media"))
                stack.enter_context(mock.patch.object(page, "wait_for_media_cards"))
                select = stack.enter_context(mock.patch.object(page, "select_media_image", side_effect=[
                    {'url': 'url-a'}, {'url': 'url-b'}]))
                stack.enter_context(mock.patch.object(page, "close_media_popup"))
                stack.enter_context(mock.patch.object(page, "ensure_media_popup_closed"))
                # 上传名=源文件名后，预扫命中要过账本验证（同名+同 sha256+同图）才接受。
                # 夹具里的「已传图」是 mock 出来的，登记假账本回执让它过验证；
                # 不带 picture_id 是故意的——主图选图仍走被 mock 的 select_media_image 名字路径。
                fake_ledger = SimpleNamespace(lookup=lambda identity: {
                    'a.jpg': {'url': 'url-a'}, 'b.jpg': {'url': 'url-b'}}.get(identity.get('name')))
                stack.enter_context(mock.patch.object(
                    protocol_media.UploadLedger, 'load', new=classmethod(lambda cls: fake_ledger)))
                stack.enter_context(mock.patch.object(page, "wait_for_main_image_slots", side_effect=[
                    {"filled": 1, "images": ["url-a"]}, {"filled": 2, "images": ["url-a", "url-b"]}, after]))
                outcome = stages.stage_upload_images(ctx)
            return outcome, opener, upload, select, ctx

    def test_old_images_are_not_counted_as_this_products_upload(self):
        for count in (1, 2):
            with self.subTest(filled_before=count):
                outcome, opener, upload, select, _ctx = self._run(count)
                self.assertFalse(outcome.ok)
                self.assertIn("无法核验", outcome.summary)
                opener.assert_not_called()
                upload.assert_not_called()
                select.assert_not_called()

    def test_an_empty_form_selects_every_requested_image_once(self):
        outcome, _opener, _upload, select, ctx = self._run(0)
        self.assertTrue(outcome.ok, outcome.summary)
        # 上传名=源文件名（2026-10-08 起）：选图按源文件 basename 找。
        self.assertEqual([call.args[1] for call in select.call_args_list], ["a.jpg", "b.jpg"])
        self.assertEqual(ctx.scratch["upload_images"]["selected_urls"], ["url-a", "url-b"])

    def test_missing_selected_urls_cannot_produce_a_verified_upload_record(self):
        outcome, _opener, _upload, _select, ctx = self._run(0, missing_url=True)
        self.assertFalse(outcome.ok)
        self.assertNotIn("upload_images", ctx.scratch)


if __name__ == "__main__":
    unittest.main()

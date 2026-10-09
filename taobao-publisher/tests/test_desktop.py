# -*- coding: utf-8 -*-
"""淘宝桌面资料准备的离线行为与资料边界验证。"""

from __future__ import annotations

import csv
import importlib
import json
import shutil
import socket
import stat
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from _helpers import make_image, make_temp_dir

from taobao_publish import contracts
from taobao_publish.constants import STAGE_ORDER
from taobao_publish.desktop import desktop_readiness, export_packet, prepare_product


class DesktopTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir(self, prefix="desktop-product-").resolve()
        self.output = make_temp_dir(self, prefix="desktop-packets-").resolve()
        self.main = make_image(self.root / "主图" / "主图_01.jpg")
        self.sku_image = make_image(self.root / "SKU" / "白色.jpg")
        self.record = {
            "id": 17,
            "name": "ID-1234567890123",
            "title": "棉袜白色均码",
            "path": str(self.root),
            "clazz": "抖店类目",
            "shipping_template": "抖店模板",
            "content": [{"name": "白色+均码", "price": 4.8, "stock": 999,
                         "path": str(self.sku_image)}],
        }
        self.minimum = {"item_price": 10.5, "total_stock": 0}

    def test_initial_values_do_not_inherit_douyin_data_or_purchase_price(self) -> None:
        prepared = prepare_product(self.record, {})
        self.assertFalse(prepared["can_export"])
        self.assertIsNone(prepared["item_price"])
        self.assertIsNone(prepared["total_stock"])
        self.assertIsNone(prepared["skus"][0]["price"])
        self.assertIsNone(prepared["skus"][0]["stock"])
        self.assertEqual(prepared["category_path"], "")
        self.assertEqual(prepared["freight_template_name"], "")
        missing = {check["field"] for check in prepared["checks"] if check["status"] == "missing"}
        self.assertEqual(missing, {"item_price", "total_stock"})

    def test_minimal_explicit_data_exports_with_manual_sku_warnings(self) -> None:
        prepared = prepare_product(self.record, self.minimum)
        self.assertTrue(prepared["can_export"])
        # 这一项现在**由真实状态推导**，不再是「流水线未实现」时的 False。
        # 断言「与就绪度一致」而不是写死值，状态再变也不用改这条用例。
        self.assertEqual(prepared["automatic_publish_ready"],
                         desktop_readiness()["automatic_publish_ready"])
        warnings = {check["field"] for check in prepared["checks"] if check["status"] == "warning"}
        self.assertTrue({"category_path", "freight_template_name", "skus.0.price", "skus.0.stock"} <= warnings)

    def test_overrides_are_independent_and_matched_by_index(self) -> None:
        self.record["content"].append({"name": "黑色", "path": str(self.sku_image)})
        overrides = {**self.minimum, "title": "淘宝独立标题", "guide_title": "导购标题",
                     "category_path": "淘宝袜子类目", "freight_template_name": "淘宝模板",
                     "skus": [{"index": 1, "price": 12.0, "stock": 7},
                              {"index": 0, "price": 11.0, "stock": 0}]}
        original = json.loads(json.dumps(self.record, ensure_ascii=False))
        prepared = prepare_product(self.record, overrides)
        self.assertEqual([sku["price"] for sku in prepared["skus"]], [11.0, 12.0])
        self.assertEqual([sku["stock"] for sku in prepared["skus"]], [0, 7])
        self.assertEqual(prepared["title"], "淘宝独立标题")
        self.assertEqual(self.record, original)

    def test_bool_strings_nonfinite_and_negative_numbers_are_rejected(self) -> None:
        cases = [("item_price", value) for value in (True, "10", 0, -1, float("nan"), float("inf"), 10**400)]
        cases += [("total_stock", value) for value in (False, "1", -1, 1.5, float("nan"), float("inf"))]
        for field, value in cases:
            with self.subTest(field=field, value=repr(value)), self.assertRaises(ValueError):
                prepare_product(self.record, {**self.minimum, field: value})
        for field in ("price", "stock"):
            with self.subTest(sku_field=field), self.assertRaises(ValueError):
                prepare_product(self.record, {**self.minimum, "skus": [{"index": 0, field: True}]})

    def test_invalid_sku_overrides_and_path_override_are_rejected(self) -> None:
        for value in ([{"index": 0}, {"index": 0}], [{"index": 1}], [{"index": True}],
                      [{"index": 0, "image_path": str(self.main)}], {}, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                prepare_product(self.record, {**self.minimum, "skus": value})
        with self.assertRaises(ValueError):
            prepare_product(self.record, {**self.minimum, "path": str(self.output)})

    def test_title_length_warning_is_sample_scoped_and_counts_chinese_twice(self) -> None:
        prepared = prepare_product(self.record, {**self.minimum, "title": "袜" * 31})
        result = next(check for check in prepared["checks"] if check["field"] == "title_length")
        self.assertEqual(result["status"], "warning")
        self.assertIn("超过 60 字符", result["message"])
        self.assertIn("目标类目", result["message"])

    def test_no_platform_or_network_calls_even_if_write_env_is_enabled(self) -> None:
        with patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")), \
                patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
                patch("taobao_publish.pipeline.run", side_effect=AssertionError("pipeline forbidden")), \
                patch("taobao_publish.cdp.probe_session", side_effect=AssertionError("CDP forbidden")), \
                patch.dict("os.environ", {"TAOBAO_UPLOAD_ALLOW_WRITE": "upload_image,save_draft,submit_publish",
                                          "TAOBAO_UPLOAD_ALLOW_SUBMIT": "1"}):
            readiness = desktop_readiness()
            prepared = prepare_product(self.record, self.minimum)
            exported = export_packet(self.record, self.minimum, self.output)
        # 本用例的重点在 finally 之前那一段：即使把写入授权全开，desktop 资料准备路线
        # 也**不得**发起任何平台调用（网络、CDP、流水线都被 patch 成会断言失败）。
        #
        # 阶段名单**不写死**——流水线推进时它本来就会变，写死会让这条安全用例
        # 因为无关原因变红，进而被人草率改掉。两份名单必须恰好覆盖当前全部阶段。
        self.assertTrue(readiness["implemented_stages"])
        self.assertCountEqual(
            readiness["implemented_stages"] + readiness["unimplemented_stages"],
            STAGE_ORDER,
            "已实现与未实现阶段应当无重复、无遗漏地覆盖当前阶段",
        )
        self.assertEqual(readiness["automatic_publish_ready"],
                         desktop_readiness()["automatic_publish_ready"])
        self.assertTrue(readiness["blocked_fields"])
        self.assertTrue(prepared["can_export"])
        self.assertTrue(Path(exported["manifest_path"]).is_file())

    def test_missing_directory_title_main_and_corrupt_images_block_export(self) -> None:
        variants = [dict(self.record, path=str(self.root / "missing")),
                    dict(self.record, title=" "), dict(self.record, path="")]
        for record in variants:
            with self.subTest(record=record):
                self.assertFalse(prepare_product(record, self.minimum)["can_export"])
                with self.assertRaises(ValueError):
                    export_packet(record, self.minimum, self.output)
        self.main.write_bytes(b"not an image")
        prepared = prepare_product(self.record, self.minimum)
        self.assertFalse(prepared["can_export"])
        self.assertTrue(any(check["field"].startswith("image.") for check in prepared["checks"]))
        self.assertEqual(list(self.output.iterdir()), [])

    def test_main_image_is_required_even_if_sku_image_exists(self) -> None:
        self.main.rename(self.root / "SKU" / "old_main.jpg")
        prepared = prepare_product(self.record, self.minimum)
        self.assertFalse(prepared["can_export"])
        self.assertIn("main_images", [check["field"] for check in prepared["checks"] if check["status"] == "missing"])

    def test_external_and_traversal_sku_paths_are_rejected(self) -> None:
        external = make_image(self.output / "private.jpg")
        for raw in (str(external), "../private.jpg", "../../private.jpg"):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, "超出"):
                prepare_product(dict(self.record, content=[{"name": "白色", "path": raw}]), self.minimum)

    def test_symlink_root_folder_and_image_are_rejected(self) -> None:
        link = self.root / "SKU" / "linked.jpg"
        try:
            link.symlink_to(self.sku_image)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"当前 Windows 不允许创建符号链接：{exc}")
        with self.assertRaisesRegex(ValueError, "符号链接"):
            prepare_product(self.record, self.minimum)

    def test_windows_reparse_points_are_rejected_without_link_privileges(self) -> None:
        original_lstat = Path.lstat
        for target in (self.root, self.root / "SKU", self.sku_image):
            def checked_lstat(path, *, _target=target):
                if path == _target:
                    return SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
                return original_lstat(path)

            with self.subTest(target=target), patch.object(Path, "lstat", checked_lstat):
                with self.assertRaisesRegex(ValueError, "重解析点"):
                    prepare_product(self.record, self.minimum)

    def test_packet_copies_bytes_by_purpose_and_uses_relative_paths(self) -> None:
        detail = make_image(self.root / "详情页" / "详情01.jpg")
        white = make_image(self.root / "白底图.jpg")
        overrides = {**self.minimum, "skus": [{"index": 0, "price": 11.25, "stock": 0}]}
        sources = {path: path.read_bytes() for path in (self.main, self.sku_image, detail, white)}
        result = export_packet(self.record, overrides, self.output)
        packet = Path(result["packet_dir"])
        payload = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        # `mode` 说的是**应用流水线**的模式，`packet_kind` 说的是**这份资料包**的性质。
        # 原先这里断言 `mode == "manual_preparation"`——那是 manifest 覆盖 `mode`
        # 的时代（同一个键两个意思，读的人会以为应用还停在人工阶段）。
        self.assertEqual(payload["mode"], "automated_pipeline")
        self.assertEqual(payload["packet_kind"], "manual_preparation")
        self.assertFalse(payload["platform_published"])
        # 资料包 manifest —— 与就绪度同源。
        self.assertEqual(payload["automatic_publish_ready"],
                         desktop_readiness()["automatic_publish_ready"])
        for purpose, source in (("main", self.main), ("detail", detail), ("sku", self.sku_image)):
            relative = payload["assets"][purpose][0]
            self.assertFalse(Path(relative).is_absolute())
            self.assertEqual((packet / relative).read_bytes(), sources[source])
        self.assertEqual((packet / payload["assets"]["white_bg"]).read_bytes(), sources[white])
        csv_path = Path(result["sku_csv_path"])
        self.assertTrue(csv_path.read_bytes().startswith(b"\xef\xbb\xbf"))
        with csv_path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["name"], "白色+均码")
        self.assertEqual(rows[0]["stock"], "0")
        self.assertEqual(rows[0]["image_path"], payload["skus"][0]["image_path"])
        self.assertEqual(result["files_count"], len([path for path in packet.rglob("*") if path.is_file()]))
        for path, original in sources.items():
            self.assertEqual(path.read_bytes(), original)

    def test_new_exports_do_not_overwrite_existing_packets(self) -> None:
        first = export_packet(self.record, self.minimum, self.output)
        saved = Path(first["manifest_path"]).read_bytes()
        second = export_packet(self.record, {**self.minimum, "item_price": 15}, self.output)
        self.assertNotEqual(first["packet_dir"], second["packet_dir"])
        self.assertEqual(Path(first["manifest_path"]).read_bytes(), saved)

    def test_output_cannot_be_inside_original_product_directory(self) -> None:
        with self.assertRaisesRegex(ValueError, "原始商品"):
            export_packet(self.record, self.minimum, self.root / "packets")
        self.assertFalse((self.root / "packets").exists())

    def test_failure_is_visible_and_partial_packet_is_cleaned(self) -> None:
        with patch("taobao_publish.desktop.shutil.copyfileobj", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                export_packet(self.record, self.minimum, self.output)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertTrue(self.main.is_file())

    def test_secrets_are_not_exported_and_csv_formula_is_text(self) -> None:
        self.record["cookie"] = "secret-cookie"
        self.record["access_token"] = "secret-access"
        self.record["content"][0]["name"] = "=1+1"
        with self.assertRaisesRegex(ValueError, "敏感信息") as raised:
            export_packet(self.record, {**self.minimum, "title": "棉袜 token=never-export-this"}, self.output)
        self.assertNotIn("never-export-this", str(raised.exception))
        self.assertEqual(list(self.output.iterdir()), [])
        result = export_packet(self.record, self.minimum, self.output)
        text = Path(result["manifest_path"]).read_text(encoding="utf-8")
        self.assertNotIn("never-export-this", text)
        self.assertNotIn("secret-cookie", text)
        self.assertNotIn("secret-access", text)
        with Path(result["sku_csv_path"]).open(encoding="utf-8-sig", newline="") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row["name"], "'=1+1")


class FrozenContractsTest(unittest.TestCase):
    def test_frozen_resource_root_uses_bundle_taobao_publisher(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        bundle_root = make_temp_dir(self, prefix="desktop-frozen-").resolve()
        expected = bundle_root / "taobao-publisher"
        shutil.copytree(source_root / "contracts", expected / "contracts")
        try:
            with patch.object(sys, "frozen", True, create=True), \
                    patch.object(sys, "_MEIPASS", str(bundle_root), create=True):
                importlib.reload(contracts)
                self.assertEqual(contracts.SUBPROJECT_ROOT, expected)
                self.assertNotEqual(contracts.SUBPROJECT_ROOT, source_root)
                self.assertFalse(contracts.validate_contracts())
        finally:
            importlib.reload(contracts)


if __name__ == "__main__":
    unittest.main()

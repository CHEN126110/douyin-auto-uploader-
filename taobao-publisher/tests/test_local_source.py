# -*- coding: utf-8 -*-
"""本地资产发现测试。

目录约定对齐 ``src/utils.py:2530-2830``，这里用合成目录验证归类与排序。
"""

from __future__ import annotations

import json
import unittest

from _helpers import make_image, make_temp_dir

from taobao_publish.local_source import (
    discover_product_assets,
    iter_readable_files,
    local_product_from_record,
    natural_sort_key,
    parse_record_content,
    summarize_assets,
)


class NaturalSortTest(unittest.TestCase):
    def test_numeric_order_not_lexicographic(self) -> None:
        """``10.jpg`` 必须排在 ``2.jpg`` 之后——这正是提交 de6721d 修掉的 bug。"""

        names = ["主图_10.jpg", "主图_2.jpg", "主图_1.jpg"]
        self.assertEqual(
            sorted(names, key=natural_sort_key),
            ["主图_1.jpg", "主图_2.jpg", "主图_10.jpg"],
        )

    def test_handles_names_without_digits(self) -> None:
        names = ["b.jpg", "a.jpg"]
        self.assertEqual(sorted(names, key=natural_sort_key), ["a.jpg", "b.jpg"])


class DiscoverAssetsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir(self, prefix="product-")

    def test_missing_directory_reports_instead_of_raising(self) -> None:
        discovery = discover_product_assets(self.root / "nope")
        self.assertEqual(discovery.images.main, [])
        self.assertTrue(any("不存在" in item for item in discovery.missing))

    def test_finds_main_detail_sku_and_white_bg(self) -> None:
        make_image(self.root / "主图" / "主图_01.jpg")
        make_image(self.root / "主图" / "主图_02.jpg")
        make_image(self.root / "详情页" / "详情_01.jpg")
        make_image(self.root / "SKU" / "白色.jpg")
        make_image(self.root / "白底图.jpg")

        discovery = discover_product_assets(self.root)
        self.assertEqual(len(discovery.images.main), 2)
        self.assertEqual(len(discovery.images.detail), 1)
        self.assertEqual(len(discovery.images.sku), 1)
        self.assertTrue(discovery.images.white_bg.endswith("白底图.jpg"))

    def test_square_images_are_preferred_and_originals_do_not_mix_in(self) -> None:
        """主图**优先用 ``_1x1`` 方图**，原图让位但**不混进同一个列表**。

        淘宝的「1:1主图」是必填位，静态预检按 1:1 校验宽高比。采集目录里通常
        同时有原图（3:4）与 whitebg 产出的方图，而原图过不了 1:1 校验——
        实测商品 ID-1083867541795：5 张 3:4 原图让预检直接报
        「宽高比 0.75 偏离 1.00」，而旁边 5 张 800x800 的 ``_1x1`` 被完全忽略，
        于是这个**明明有合规主图的商品永远发不出去**。

        两组**不混用**（混用会在平台上重复上传同一张图）：
        ``main`` 取方图，原图放到 ``main_plain`` 备用。
        """

        make_image(self.root / "主图" / "主图_01.jpg")
        make_image(self.root / "主图" / "主图_01_1x1.jpg")

        discovery = discover_product_assets(self.root)
        self.assertEqual(len(discovery.images.main), 1, "main 只放一组，不混用")
        self.assertTrue(discovery.images.main[0].endswith("主图_01_1x1.jpg"),
                        "main 应当取方图")
        self.assertEqual([p.split("\\")[-1] for p in discovery.images.main_plain],
                         ["主图_01.jpg"], "原图让位到 main_plain")
        self.assertTrue(any("_1x1" in note for note in discovery.notes))

    def test_plain_main_images_are_used_when_no_square_version_exists(self) -> None:
        """没有方图时退回原图——不能因为没有 ``_1x1`` 就报「没有可用主图」。"""

        make_image(self.root / "主图" / "主图_01.jpg")

        discovery = discover_product_assets(self.root)
        self.assertEqual(len(discovery.images.main), 1)
        self.assertTrue(discovery.images.main[0].endswith("主图_01.jpg"))
        self.assertEqual(discovery.images.main_plain, [], "没有方图时不该有让位记录")

    def test_only_square_images_still_work(self) -> None:
        make_image(self.root / "主图" / "主图_01_1x1.jpg")

        discovery = discover_product_assets(self.root)
        self.assertEqual(len(discovery.images.main), 1)
        self.assertTrue(discovery.images.main[0].endswith("主图_01_1x1.jpg"))

    def test_prefers_800_dir_over_750_over_plain(self) -> None:
        make_image(self.root / "主图" / "主图_01.jpg")
        make_image(self.root / "主图" / "750" / "主图_01.jpg")
        make_image(self.root / "主图" / "800" / "主图_01.jpg")

        discovery = discover_product_assets(self.root)
        self.assertEqual(discovery.main_dir_used, "主图\\800")

    def test_detail_dir_alternative_name(self) -> None:
        make_image(self.root / "详情图片" / "d1.jpg")
        discovery = discover_product_assets(self.root)
        self.assertEqual(discovery.detail_dir_used, "详情图片")

    def test_white_bg_candidates_inside_main_dir(self) -> None:
        for stem in ("白底", "white", "白底图"):
            root = make_temp_dir(self, prefix="wb-")
            make_image(root / "主图" / f"{stem}.jpg")
            discovery = discover_product_assets(root)
            self.assertTrue(discovery.images.white_bg.endswith(f"{stem}.jpg"), stem)

    def test_white_bg_falls_back_to_whitebg_subdir(self) -> None:
        make_image(self.root / "白底图" / "白色.jpg")
        discovery = discover_product_assets(self.root)
        self.assertTrue(discovery.images.white_bg.endswith("白色.jpg"))

    def test_missing_main_dir_is_recorded(self) -> None:
        discovery = discover_product_assets(self.root)
        self.assertTrue(any("主图目录" in item for item in discovery.missing))

    def test_non_image_files_are_ignored(self) -> None:
        (self.root / "主图").mkdir(parents=True, exist_ok=True)
        (self.root / "主图" / "readme.txt").write_text("x", encoding="utf-8")
        make_image(self.root / "主图" / "主图_01.jpg")
        discovery = discover_product_assets(self.root)
        self.assertEqual(len(discovery.images.main), 1)

    def test_summary_is_chinese_and_serializable(self) -> None:
        make_image(self.root / "主图" / "主图_01.jpg")
        discovery = discover_product_assets(self.root)
        summary = summarize_assets(discovery)
        self.assertIn("主图", summary)
        json.dumps(discovery.to_dict(), ensure_ascii=False)

    def test_square_dir_note(self) -> None:
        make_image(self.root / "SKU_1x1" / "白色.jpg")
        discovery = discover_product_assets(self.root)
        self.assertTrue(any("SKU_1x1" in note for note in discovery.notes))


class ParseRecordContentTest(unittest.TestCase):
    def test_parses_real_shape(self) -> None:
        """真实结构实测自 sqlite.db：``{dir_name, file_name, name, path, price}``。"""

        raw = json.dumps(
            [
                {
                    "dir_name": "SKU",
                    "file_name": "01_白色+均码",
                    "name": "白色+均码",
                    "path": "C:/x/SKU/01_白色+均码.jpg",
                    "price": 4.8,
                }
            ],
            ensure_ascii=False,
        )
        skus = parse_record_content(raw)
        self.assertEqual(len(skus), 1)
        self.assertEqual(skus[0].name, "白色+均码")
        self.assertEqual(skus[0].price, 4.8)
        self.assertEqual(skus[0].dir_name, "SKU")

    def test_accepts_list_directly(self) -> None:
        skus = parse_record_content([{"name": "a", "price": "1.5", "path": "p"}])
        self.assertEqual(skus[0].price, 1.5)

    def test_empty_inputs_return_empty(self) -> None:
        self.assertEqual(parse_record_content(None), [])
        self.assertEqual(parse_record_content(""), [])

    def test_broken_json_raises_instead_of_returning_empty(self) -> None:
        """解析失败与「确实没有 SKU」必须区分开。"""

        with self.assertRaises(ValueError):
            parse_record_content("{not json")

    def test_non_array_json_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_record_content('{"a": 1}')

    def test_non_numeric_price_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_record_content('[{"name": "a", "price": "abc"}]')

    def test_missing_price_is_none(self) -> None:
        skus = parse_record_content('[{"name": "a"}]')
        self.assertIsNone(skus[0].price)


class LocalProductFromRecordTest(unittest.TestCase):
    def test_projects_row_and_scans_directory(self) -> None:
        root = make_temp_dir(self, prefix="rec-")
        make_image(root / "主图" / "主图_01.jpg")

        row = {
            "id": 7,
            "name": "ID-976666440420",
            "title": "标题",
            "clazz": 2,
            "shipping_template": "中通包邮",
            "source_url": "https://item.taobao.com/item.htm?id=1",
            "content": json.dumps([{"name": "白色", "price": 4.8, "path": "p"}], ensure_ascii=False),
        }
        local = local_product_from_record(row, product_dir=str(root))
        self.assertEqual(local.record_id, 7)
        self.assertEqual(local.record_name, "ID-976666440420")
        self.assertEqual(local.clazz, 2)
        self.assertEqual(local.shipping_template, "中通包邮")
        self.assertEqual(len(local.skus), 1)
        self.assertEqual(len(local.main_images), 1)

    def test_missing_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            local_product_from_record({"name": "x"})

    def test_without_product_dir_still_works(self) -> None:
        local = local_product_from_record({"id": 1, "name": "n"}, product_dir="")
        self.assertEqual(local.main_images, [])


class IterReadableFilesTest(unittest.TestCase):
    def test_filters_out_missing_paths(self) -> None:
        root = make_temp_dir(self, prefix="rf-")
        existing = make_image(root / "a.jpg")
        result = list(iter_readable_files([str(existing), str(root / "nope.jpg"), ""]))
        self.assertEqual(result, [str(existing)])


if __name__ == "__main__":
    unittest.main()

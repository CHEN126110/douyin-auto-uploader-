# -*- coding: utf-8 -*-
"""**每条 `hard: true` 的契约规则，都要有一个能证明它生效的用例。**

这是上一轮那个发现的固化。上一轮发现 `main_image_max_bytes` 与
`main_image_formats` 两条 hard 规则根本没执行——而 `check-hard-rules-coverage.py`
显示**它们的名字都出现在源码里**。

**「名字出现」不等于「真的执行」。** 所以这里不查名字，直接**喂一个越界输入，
看它会不会被拦**。

## 为什么这比查名字强

上一轮导购标题那件事就是反例：`guide_title_max_chars` 的名字**出现在
`desktop.py` 里**（人工准备路径），于是「名字检查」判它 PASS，
而**发布流水线根本不引用 desktop**——操作人填的导购标题被静默丢弃。

行为验证不会有这个盲区：**规矩在哪一层执行不重要，执行了才算数。**
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

from PIL import Image

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish.contracts import load_contracts  # noqa: E402
from taobao_publish.mapping import build_publish_item  # noqa: E402
from taobao_publish.models import LocalProduct  # noqa: E402
from taobao_publish.preflight import run_static_preflight  # noqa: E402


class _Fixture:
    """造样本的小工具。"""

    def __init__(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="tb-hardrules-"))
        self.contracts = load_contracts()

    def image(self, name: str, size=(800, 800), fmt: str = "JPEG") -> str:
        path = self.tmp / name
        Image.new("RGB", size, (200, 30, 30)).save(path, format=fmt)
        return str(path)

    def noisy_image(self, name: str, side: int) -> str:
        path = self.tmp / name
        raw = bytes(bytearray(os.urandom(side * side * 3)))
        Image.frombytes("RGB", (side, side), raw).save(path, quality=100)
        return str(path)

    def blockers(self, *, title="标题", guide_title="", skus=None, main=None,
                 local_title="本地标题"):
        if skus is None:
            skus = [{"spec_values": {"尺码": "均码"}, "price": 9.9, "stock": 10}]
        if main is None:
            main = [self.image("正常.jpg")]

        local = LocalProduct(record_id=1, record_name="ID-1", title=local_title,
                             main_images=list(main), detail_images=[])
        request = {"title": title, "skus": skus}
        if guide_title:
            request["guide_title"] = guide_title
        item = build_publish_item(local, request).item
        return run_static_preflight(item, contracts=self.contracts).blockers


class EveryHardRuleFiresTest(unittest.TestCase):
    """11 条 hard 规则，逐条喂越界输入。"""

    def setUp(self) -> None:
        self.fx = _Fixture()
        self.contracts = self.fx.contracts

    def _rule(self, name: str):
        spec = self.contracts.rules.get(name)
        self.assertIsNotNone(spec, "契约里没有 {}".format(name))
        self.assertTrue(spec.hard, "{} 不再是 hard 了，本用例的前提变了".format(name))
        return spec

    # --- 标题 ---------------------------------------------------------------
    def test_title_min_chars(self) -> None:
        """⚠️ **请求与本地标题都要为空**。

        ``build_publish_item`` 里有明确回落：``request_title or local.title``。
        只清空请求侧的标题会回落到本地标题，标题仍然非空——
        **第一版用例就是这么写错的**（是测试错了，不是代码错了）。
        """

        self._rule("title_min_chars")
        found = self.fx.blockers(title="", local_title="",
                                 main=[self.fx.image("a.jpg")])
        self.assertTrue([b for b in found if b.field == "title"], "两边都空时必须拦")

    def test_title_falls_back_to_local_when_request_is_empty(self) -> None:
        """反过来把回落行为也钉住：请求侧空、本地有，就**不算空标题**。"""

        found = self.fx.blockers(title="", local_title="本地标题")
        self.assertFalse([b for b in found if b.field == "title"],
                         "请求侧为空时应回落到本地标题，不该判成空标题")

    def test_title_max_chars(self) -> None:
        limit = self._rule("title_max_chars").integer()
        found = self.fx.blockers(title="字" * (limit + 1))
        self.assertTrue([b for b in found if b.field == "title"], "超长标题必须拦")

    def test_guide_title_max_chars(self) -> None:
        limit = self._rule("guide_title_max_chars").integer()
        found = self.fx.blockers(guide_title="字" * (limit + 1))
        self.assertTrue([b for b in found if b.field == "guide_title"],
                        "超长导购标题必须拦")

    # --- SKU ----------------------------------------------------------------
    def test_sku_min_count(self) -> None:
        self._rule("sku_min_count")
        found = self.fx.blockers(skus=[])
        self.assertTrue([b for b in found if b.field.startswith("skus")], "没有 SKU 必须拦")

    def test_sku_price_min(self) -> None:
        minimum = self._rule("sku_price_min").number()
        found = self.fx.blockers(skus=[
            {"spec_values": {"尺码": "均码"}, "price": minimum / 2, "stock": 10}])
        self.assertTrue(
            [b for b in found if "price" in b.field or "sku" in b.field.lower()],
            "低于 sku_price_min 必须拦",
        )

    # --- 主图 ---------------------------------------------------------------
    def test_main_image_min_count(self) -> None:
        self._rule("main_image_min_count")
        found = self.fx.blockers(main=[])
        self.assertTrue([b for b in found if b.field.startswith("images")], "没有主图必须拦")

    def test_main_image_max_count(self) -> None:
        limit = self._rule("main_image_max_count").integer()
        many = [self.fx.image("m{}.jpg".format(i)) for i in range(limit + 1)]
        found = self.fx.blockers(main=many)
        self.assertTrue([b for b in found if b.field.startswith("images")],
                        "主图超过 {} 张必须拦".format(limit))

    def test_main_image_min_side_px(self) -> None:
        minimum = self._rule("main_image_min_side_px").integer()
        small = self.fx.image("小.jpg", size=(minimum - 100, minimum - 100))
        found = self.fx.blockers(main=[small])
        self.assertTrue([b for b in found if b.field.startswith("images")],
                        "最小边不足必须拦")

    def test_main_image_aspect_ratio(self) -> None:
        tall = self.fx.image("三比四.jpg", size=(600, 800))
        found = self.fx.blockers(main=[tall])
        self.assertTrue([b for b in found if b.field.startswith("images")], "非 1:1 必须拦")

    def test_main_image_formats(self) -> None:
        allowed = self._rule("main_image_formats").strings()
        self.assertNotIn("bmp", allowed)
        bmp = self.fx.image("错误格式.bmp", fmt="BMP")
        found = self.fx.blockers(main=[bmp])
        self.assertTrue([b for b in found if b.field.startswith("images")],
                        "不允许的格式必须拦")

    def test_main_image_max_bytes(self) -> None:
        maximum = self._rule("main_image_max_bytes").integer()
        big = self.fx.noisy_image("超大.jpg", side=1400)
        self.assertGreater(pathlib.Path(big).stat().st_size, maximum,
                           "样本本身要越界，否则这条验证没有意义")
        found = self.fx.blockers(main=[big])
        self.assertTrue([b for b in found if b.field.startswith("images")],
                        "超过体积上限必须拦")

    # --- 元测试 -------------------------------------------------------------
    def test_the_table_covers_every_hard_rule(self) -> None:
        """**契约里加了新的 hard 规则却忘了加用例，这条会失败。**

        名字里带 `test_` 且以 ``_chars`` / ``_count`` / ``_px`` /
        ``_bytes`` / ``_formats`` / ``_ratio`` / ``_min`` / ``_max`` 结尾的规则
        都在上面逐条覆盖了；这里用「规则名 → 用例函数名」的映射表核对。
        """

        covered = {
            "title_min_chars": "test_title_min_chars",
            "title_max_chars": "test_title_max_chars",
            "guide_title_max_chars": "test_guide_title_max_chars",
            "sku_min_count": "test_sku_min_count",
            "sku_price_min": "test_sku_price_min",
            "main_image_min_count": "test_main_image_min_count",
            "main_image_max_count": "test_main_image_max_count",
            "main_image_min_side_px": "test_main_image_min_side_px",
            "main_image_aspect_ratio": "test_main_image_aspect_ratio",
            "main_image_formats": "test_main_image_formats",
            "main_image_max_bytes": "test_main_image_max_bytes",
        }

        hard_names = set()
        for name in covered:
            spec = self.contracts.rules.get(name)
            if spec is not None and spec.hard:
                hard_names.add(name)

        # 反过来：契约里所有 hard 规则都必须在表里。
        #
        # ⚠️ **不能用 ``dir(rules)``**：规则是通过 ``.get(name)`` 访问的，
        # 不是属性——第一版就是这么写的，扫出 **0 条**，于是断言永远成立，
        # 那条测试**等于没有检查**（而且它「通过」了，给出一种已覆盖的假象）。
        all_hard = set()
        for name in self.contracts.rules.rules:
            spec = self.contracts.rules.get(name)
            if spec is not None and spec.hard:
                all_hard.add(name)

        # **自证**：扫出来的条数必须与契约 JSON 里的一致。
        # 扫出 0 条时这条会立刻失败，而不是悄悄放行。
        raw = json.loads(
            (SUBPROJECT / "contracts" / "rules.json").read_text(encoding="utf-8"))
        raw_rules = raw.get("rules") or raw
        expected_hard = {name for name, spec in raw_rules.items()
                         if isinstance(spec, dict) and spec.get("hard") is True}
        self.assertEqual(
            all_hard, expected_hard,
            "枚举出来的 hard 规则与契约 JSON 不一致——枚举方式坏了",
        )
        self.assertGreaterEqual(len(all_hard), 10, "hard 规则不可能只有这么点")

        missing = sorted(all_hard - set(covered))
        self.assertEqual(
            missing, [],
            "契约里有 hard 规则没有对应的行为用例：{}——"
            "请像其它规则一样加一条「喂越界输入看它会不会被拦」，"
            "**不要只查名字出现过**（导购标题那条就是名字出现了却没人执行）".format(missing),
        )
        self.assertGreaterEqual(len(hard_names), 11)


if __name__ == "__main__":
    unittest.main()

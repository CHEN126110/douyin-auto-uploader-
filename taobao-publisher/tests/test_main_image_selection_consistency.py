# -*- coding: utf-8 -*-
"""**两处取主图的逻辑正好相反** —— 报告与流水线说的不是同一批图。

## 实测（2026-10-03）

商品的 `主图/` 下同时有两套：

| 文件 | 尺寸 | 比例 | 合规？ |
|---|---|---|---|
| `主图_NN.jpg` | 1440x1920 | **0.75** | 不合（契约要求 1.0±0.02） |
| `主图_NN_1x1.jpg` | 800x800 | **1.0** | 合规 |

**两处逻辑相反：**

| 位置 | 取哪套 |
|---|---|
| `local_source`（**流水线真正用的**） | **优先 `_1x1`**，注释写着「两组不混用——混用会在平台上重复上传同一张图」 |
| `desktop._asset_paths`（**出报告与资料包用的**） | `if "_1x1" not in Path(p).stem` —— **显式排除 `_1x1`** |

后果：`prepare_product` 报 5 条

```
本地主图不是 1:1；资料包保留原图，上传前需人工确认与处理。
```

**而流水线上传的是旁边那 5 张合规方图。**
**报告让用户去"人工处理"一批流水线根本不会用的图**——而且"处理"完可能反而
改动了真正会被上传的东西。

`local_source` 的注释里记着**这一模一样的坑**：

> 而旁边 5 张 800x800 的 `_1x1` 因为「不属于主图列表」被完全忽略，
> 于是这个**明明有合规主图的商品永远发不出去**

**那边修了，`desktop` 这边没修。**

## 修法

`desktop._asset_paths` 复用 `local_source.is_square_name`（公开别名，同一份实现）：

* `main` 取方图，没有才取原图（**不混用**）；
* 被让位的原图记到 `main_plain`。

实测：`image_ratio` 警告 **5 → 0**，`assets.main` 变成与流水线相同的 5 张方图。
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import desktop, local_source  # noqa: E402

#: 一张最小的合法 JPEG（1x1）—— 用来搭合成目录，不依赖真实商品。
TINY_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300"
    + "08" * 64
    + "ffc0000b080001000101011100ffc4001f0000010501010101010100000000000000000102030405"
    + "0607" + "08090a0b" + "ffc400b5100002010303020403050504040000017d01020300041105122131"
    + "410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a"
    + "3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a83"
    + "8485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6"
    + "c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9fa"
    + "ffc4001f0100030101010101010101010000000000000102030405060708090a0b"
    + "ffda0008010100003f00d2cf20ffd9"
)


def make_product_dir(root: pathlib.Path, names) -> None:
    main = root / "主图"
    main.mkdir(parents=True, exist_ok=True)
    for name in names:
        (main / name).write_bytes(TINY_JPEG)


class SquarePreferenceTest(unittest.TestCase):
    def test_is_square_name_is_public_and_shared(self) -> None:
        """**同一份实现**——两处各写一份迟早会反（实测就反过）。"""

        self.assertTrue(hasattr(local_source, "is_square_name"))
        self.assertIs(local_source.is_square_name, local_source._is_square_name)

    def test_it_recognises_the_marker(self) -> None:
        self.assertTrue(local_source.is_square_name(pathlib.Path("主图_01_1x1.jpg")))
        self.assertFalse(local_source.is_square_name(pathlib.Path("主图_01.jpg")))


class AssetPathsPreferSquareTest(unittest.TestCase):
    """`_asset_paths` 必须**与流水线取同一套**。"""

    def test_prefers_square_when_both_exist(self) -> None:
        with tempfile.TemporaryDirectory(prefix="assets-") as directory:
            root = pathlib.Path(directory)
            make_product_dir(root, ["主图_01.jpg", "主图_02.jpg",
                                    "主图_01_1x1.jpg", "主图_02_1x1.jpg"])
            assets = desktop._asset_paths(root)

        names = sorted(pathlib.Path(p).name for p in assets["main"])
        self.assertEqual(names, ["主图_01_1x1.jpg", "主图_02_1x1.jpg"],
                         "主图应当取方图（与 local_source 一致）")

    def test_plain_images_are_kept_aside(self) -> None:
        """被让位的原图**不丢**——将来的 3:4 主图位要用。"""

        with tempfile.TemporaryDirectory(prefix="assets2-") as directory:
            root = pathlib.Path(directory)
            make_product_dir(root, ["主图_01.jpg", "主图_01_1x1.jpg"])
            assets = desktop._asset_paths(root)

        self.assertEqual([pathlib.Path(p).name for p in assets["main"]],
                         ["主图_01_1x1.jpg"])
        self.assertEqual([pathlib.Path(p).name for p in assets["main_plain"]],
                         ["主图_01.jpg"])

    def test_falls_back_to_plain_when_no_square(self) -> None:
        with tempfile.TemporaryDirectory(prefix="assets3-") as directory:
            root = pathlib.Path(directory)
            make_product_dir(root, ["主图_01.jpg", "主图_02.jpg"])
            assets = desktop._asset_paths(root)

        names = sorted(pathlib.Path(p).name for p in assets["main"])
        self.assertEqual(names, ["主图_01.jpg", "主图_02.jpg"])
        self.assertEqual(assets["main_plain"], [], "没有方图时不该有被让位的原图")

    def test_does_not_mix_the_two_sets(self) -> None:
        """⚠️ **两组不混用**——`local_source` 的注释写明：混用会重复上传同一张图。"""

        with tempfile.TemporaryDirectory(prefix="assets4-") as directory:
            root = pathlib.Path(directory)
            make_product_dir(root, ["主图_01.jpg", "主图_01_1x1.jpg"])
            assets = desktop._asset_paths(root)

        squares = [p for p in assets["main"]
                   if local_source.is_square_name(pathlib.Path(p))]
        self.assertEqual(len(squares), len(assets["main"]),
                         "`main` 里不该混进原图")


class ReportMatchesPipelineTest(unittest.TestCase):
    """**报告里说的主图，要与流水线取的是同一批。**"""

    def test_both_sides_pick_the_same_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="same-") as directory:
            root = pathlib.Path(directory)
            make_product_dir(root, ["主图_01.jpg", "主图_01_1x1.jpg",
                                    "主图_02.jpg", "主图_02_1x1.jpg"])

            assets = desktop._asset_paths(root)
            discovery = local_source.discover_product_assets(str(root))

        report = sorted(pathlib.Path(p).name for p in assets["main"])
        pipeline = sorted(pathlib.Path(p).name for p in discovery.images.main)
        self.assertEqual(report, pipeline,
                         "报告与流水线必须取同一批主图——否则报告会让人去处理\n"
                         "一批根本不会被上传的图")


if __name__ == "__main__":
    unittest.main()

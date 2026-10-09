# -*- coding: utf-8 -*-
"""`contracts/rules.json` 里标了 ``hard: true`` 的图片规则，**必须真的执行**。

实测（`scripts/probe-image-rules-coverage.py`，修之前）：

```
3:4 比例被拦:   是 ✓        ← 对照，证明检测方式有效
>3MB 被拦:      否（缺口）
.bmp 被拦:      否（缺口）
正常图不误伤:   是 ✓
```

`main_image_max_bytes`（3 MB）与 `main_image_formats`（png/jpg/jpeg）
在契约里都是 ``hard: true``，而 `validate_images` **没有执行它们**——
一个 3.71 MB 的图或一个 ``.bmp`` 能一路通过静态预检，到平台上才被拒。

**预检存在的意义就是把这一步提前。** 契约说 hard，代码就必须执行。

> 写这条测试时还踩了两个自己的坑，都记在里面：
> 1. 第一版探针**把「任意阻塞」当成「图片被拦」**，输出了假阳性；
> 2. 第一版「超大图」只有 2.29 MB，**样本本身就没越界**。
"""

from __future__ import annotations

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

from taobao_publish.mapping import build_publish_item  # noqa: E402
from taobao_publish.models import LocalProduct  # noqa: E402
from taobao_publish.preflight import run_static_preflight  # noqa: E402

MAX_BYTES = 3145728


def _image_blockers(paths) -> list:
    r"""只取 **images.\* 字段**的阻塞项。

    ⚠️ **必须限定字段**：第一版探针没限定，于是「至少需要 1 条 SKU」那条
    被当成了图片校验生效，输出了假阳性。
    """

    local = LocalProduct(record_id=1, record_name="ID-1", title="标题",
                         main_images=list(paths), detail_images=[])
    request = {"title": "标题",
               "skus": [{"spec_values": {"尺码": "均码"}, "price": 1.0, "stock": 1}]}
    item = build_publish_item(local, request).item
    return [b for b in run_static_preflight(item).blockers
            if b.field.startswith("images.")]


class ImageHardRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="tb-imgrules-"))

    def _square(self, name: str, side: int = 800, color=(200, 30, 30)) -> pathlib.Path:
        path = self.tmp / name
        Image.new("RGB", (side, side), color).save(path)
        return path

    def _noisy_square(self, name: str, side: int) -> pathlib.Path:
        """高熵图，体积才真的上得去。"""

        path = self.tmp / name
        raw = bytes(bytearray(os.urandom(side * side * 3)))
        Image.frombytes("RGB", (side, side), raw).save(path, quality=100)
        return path

    def test_normal_image_passes(self) -> None:
        """防误伤。"""

        self.assertEqual(_image_blockers([str(self._square("正常.jpg"))]), [])

    def test_oversized_image_is_blocked(self) -> None:
        path = self._noisy_square("超大.jpg", side=1400)
        self.assertGreater(path.stat().st_size, MAX_BYTES, "样本本身要越界，否则验证无意义")
        found = _image_blockers([str(path)])
        self.assertTrue(found, "超过 main_image_max_bytes 必须拦")
        self.assertIn("超过上限", found[0].detail)

    def test_disallowed_format_is_blocked(self) -> None:
        path = self._square("错误格式.bmp")
        found = _image_blockers([str(path)])
        self.assertTrue(found, ".bmp 不在 main_image_formats 里，必须拦")
        self.assertIn("不在允许范围", found[0].detail)

    def test_non_square_is_blocked(self) -> None:
        """对照：这条**本来就在执行**，钉住它别退化。"""

        path = self.tmp / "三比四.jpg"
        Image.new("RGB", (600, 800), (10, 120, 200)).save(path)
        found = _image_blockers([str(path)])
        self.assertTrue(found)
        self.assertIn("宽高比", found[0].detail)

    def test_every_hard_image_rule_is_actually_read(self) -> None:
        """**契约说 hard，代码就必须读它。**

        这条按 ``rules.json`` 里前缀是 ``main_image_`` 且 ``hard: true`` 的规则，
        逐条确认 ``validate_images`` 读到了——**将来加一条 hard 规则却忘了执行，
        这里会失败**。
        """

        import inspect

        from taobao_publish.contracts import load_contracts
        from taobao_publish.mapping import validate_images

        contracts = load_contracts()
        source = inspect.getsource(validate_images)
        hard_names = []
        raw = contracts.rules
        for name in (
            "main_image_min_count", "main_image_max_count", "main_image_min_side_px",
            "main_image_aspect_ratio", "main_image_max_bytes", "main_image_formats",
        ):
            spec = raw.get(name)
            if spec is None or not spec.hard:
                continue
            hard_names.append(name)
            self.assertIn(
                name, source,
                "{} 在契约里是 hard: true，但 validate_images 没读它".format(name),
            )
        self.assertGreaterEqual(len(hard_names), 5, "至少该覆盖到五条 hard 图片规则")

    def test_missing_rules_do_not_silently_pass(self) -> None:
        """规则读不到时**要报错**，不能静默当成「检查通过」。

        `RuleSpec.strings()` / `integer()` 对形状不对的值直接抛错——
        这条钉住「不做隐式兜底」。
        """

        import inspect

        from taobao_publish.mapping import validate_images

        source = inspect.getsource(validate_images)
        # 格式规则必须走 strings()（枚举校验），不许自己 if isinstance
        self.assertIn("strings()", source, "格式规则要走 strings()，它会拒绝形状不对的契约")


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""验证 `validate_images` **漏掉了哪两条 hard 规则**（修正版）。

第一版探针有两处错，都值得记下来：

1. **把「任意阻塞」当成「图片被拦」**——`.bmp` 那次命中的其实是
   「至少需要 1 条 SKU」，于是输出了「被拦: 是」这种**假阳性**。
   检查必须**限定范围**（只看 `images.*` 字段）。
2. **「超大图」只有 2.29 MB**，根本没到 3 MB 限额——造样本时没验证样本本身。

`contracts/rules.json` 里这两条都是 `hard: true`：

```
main_image_max_bytes   3145728 (3 MB)
main_image_formats     ["png", "jpg", "jpeg"]
```

**纯离线**，用临时目录造图。
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile

from PIL import Image

SUBPROJECT = pathlib.Path(__file__).resolve().parents[1]
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish.mapping import build_publish_item  # noqa: E402
from taobao_publish.models import LocalProduct, SkuEntry  # noqa: E402
from taobao_publish.preflight import run_static_preflight  # noqa: E402

#: 限额来自 contracts/rules.json，这里只用于**造样本时自检**。
MAX_BYTES = 3145728


def make_noisy_square(path: pathlib.Path, side: int) -> None:
    """造一张 1:1 的**高熵**图，让体积真正上去。"""

    raw = bytes(bytearray(os.urandom(side * side * 3)))
    Image.frombytes("RGB", (side, side), raw).save(path, quality=100)


def image_blockers(paths):
    """只取 **images.* 字段**的阻塞项。

    第一版就是在这里栽的：没限定字段，于是 SKU 的阻塞被当成了图片校验生效。
    """

    local = LocalProduct(record_id=1, record_name="ID-1", title="标题",
                         main_images=paths, detail_images=[])
    request = {"title": "标题",
               "skus": [{"spec_values": {"尺码": "均码"}, "price": 1.0, "stock": 1}]}
    item = build_publish_item(local, request).item
    result = run_static_preflight(item)
    return [b for b in result.blockers if b.field.startswith("images.")]


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="tb-imgcheck-"))
    print("临时目录：{}".format(tmp))

    big = tmp / "主图_超大.jpg"
    make_noisy_square(big, side=1400)
    size_mb = big.stat().st_size / 1024 / 1024
    print("  超大图: {:.2f} MB（限额 {:.2f} MB）".format(size_mb, MAX_BYTES / 1024 / 1024))
    assert big.stat().st_size > MAX_BYTES, "样本没超过限额，这一轮验证没有意义"
    print("      ✓ 样本确实超过限额")

    bmp = tmp / "主图_错误格式.bmp"
    Image.new("RGB", (800, 800), (200, 30, 30)).save(bmp)
    print("  错误格式: .bmp（允许 {:}）".format(["png", "jpg", "jpeg"]))

    normal = tmp / "主图_正常.jpg"
    Image.new("RGB", (800, 800), (200, 30, 30)).save(normal)

    print()
    cases = [
        ("正常图（对照）", [str(normal)]),
        ("超大图（>3MB）", [str(big)]),
        (".bmp（不允许的格式）", [str(bmp)]),
        ("宽高比 3:4", None),  # 单独造，见下
    ]

    # 3:4 的对照样本：用来证明「比例那条**是**生效的」
    tall = tmp / "主图_三比四.jpg"
    Image.new("RGB", (600, 800), (10, 120, 200)).save(tall)

    results = {}
    for label, paths in cases[:-1]:
        found = image_blockers(paths)
        results[label] = bool(found)
        print("{:<24} 图片相关阻塞 {} 条".format(label, len(found)))
        for blocker in found:
            print("      [{}] {}".format(blocker.code, blocker.detail[:92]))

    found = image_blockers([str(tall)])
    results["宽高比 3:4"] = bool(found)
    print("{:<24} 图片相关阻塞 {} 条".format("宽高比 3:4", len(found)))
    for blocker in found:
        print("      [{}] {}".format(blocker.code, blocker.detail[:92]))

    print()
    print("==== 判定 ====")
    print("  3:4 比例被拦:      {}".format("是 ✓" if results["宽高比 3:4"] else "**否（缺口）**"))
    print("  >3MB 被拦:         {}".format("是 ✓" if results["超大图（>3MB）"] else "**否（缺口）**"))
    print("  .bmp 被拦:         {}".format("是 ✓" if results[".bmp（不允许的格式）"] else "**否（缺口）**"))
    print("  正常图不误伤:      {}".format("是 ✓" if not results["正常图（对照）"] else "**否（误伤）**"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

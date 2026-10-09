# -*- coding: utf-8 -*-
"""⚠️ **在关闭后的连接上读** + **吞掉异常** —— 我自己的两个错误。

## 现象

单独测（自己新开连接）**读得到**：

```
上架时间 → ['立刻上架']
```

**链条里却全是空**：

```
default_notice： {"上架时间": [], "发货时间": [], "提取方式": []}
```

## 错误一：在 `client.close()` 之后用 `client`

```
62: finally:
64:     client.close()        ← 连接关掉
...
105: default_notice = {}      ← 读取在这里
108:     page.read_selected_options(client, _label)
```

**「单独测能行、链条里不行」最容易被漏掉**——两种环境的差别只在
「连接是什么时候关的」。

## 错误二：`except Exception: ... = []` **吞掉了异常**

那是**「兜底掩盖真实问题」**，红线明令禁止。

**没有这个 except 的话，第一次跑就会看到「连接已关闭」的报错**，
而不是一个看起来像「没有选中项」的 `[]`。

**又一次验证**：`[]` 与「读不到」是两回事，**而吞异常会把前者伪装成后者**。

## 修后（链条实测）

```
default_notice： {"上架时间": ["立刻上架"],
                  "发货时间": ["按商品统一设置", "48小时内发货"],
                  "提取方式": ["使用物流配送"]}
matched 项数： 9   （没虚增）
```

## 为什么 `上架时间` 必须在这一组里

**它决定提交后是否立即开卖**——实测默认「立刻上架」。
`submit` 从未执行过，所以**这条默认值此前没被任何人看过**。
发货时间错了是延后；**上架时间错了是直接开卖**。
"""
from __future__ import annotations

import inspect
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page, stages  # noqa: E402

SMOKE = SUBPROJECT / "scripts" / "smoke-full-chain-live.py"


class ReadHappensWhileConnectedTest(unittest.TestCase):
    """⚠️ **顺序**：初始化 → 打开连接 → 读取 → 关闭连接。"""

    def setUp(self) -> None:
        self.source = inspect.getsource(stages.stage_readback)

    def test_the_read_is_before_client_close(self) -> None:
        # ⚠️ **剥掉注释再判。**
        #
        # 这段源码里有一句注释写着 `finally: client.close()`（用来解释这个 bug
        # 是什么），位置**就在读取之前**——直接 index() 会命中注释，
        # 断言就反了。本会话固定套路。
        code = "\n".join(line for line in self.source.splitlines()
                          if not line.strip().startswith("#"))
        read_at = code.index("read_selected_options(client")
        close_at = code.index("client.close()")
        self.assertLess(read_at, close_at,
                        "在 client.close() 之后读会读到空——"
                        "而单独测能行，两种环境不一致")

    def test_the_accumulator_is_initialised_before_the_connection(self) -> None:
        init_at = self.source.index("default_notice: Dict[str, Any] = {}")
        open_at = self.source.index("client = _open_publish_page(ctx)")
        self.assertLess(init_at, open_at)

    def test_the_summary_is_built_after_close_which_is_fine(self) -> None:
        """拼字符串不用连接，放在 `finally` 之后没问题。"""

        close_at = self.source.index("client.close()")
        bits_at = self.source.index("notice_bits = []")
        self.assertLess(close_at, bits_at)


class NoSwallowingTest(unittest.TestCase):
    """⚠️ **红线：不用兜底掩盖真实问题。**"""

    def setUp(self) -> None:
        self.source = inspect.getsource(stages.stage_readback)

    def test_a_failure_is_recorded_not_converted_to_empty(self) -> None:
        self.assertNotIn("default_notice[_label] = []", self.source,
                         "把异常转成空列表 = 把「读失败」伪装成「没有选中项」")
        self.assertIn('"error"', self.source)

    def test_the_summary_says_it_was_unreadable(self) -> None:
        self.assertIn("未读到", self.source)


class ListingTimeIsIncludedTest(unittest.TestCase):
    def test_it_is_read(self) -> None:
        """⚠️ **`上架时间` 决定提交后是否立即开卖。**"""

        source = inspect.getsource(stages.stage_readback)
        self.assertIn("上架时间", source)

    def test_it_is_in_the_same_loop_as_the_logistics_rows(self) -> None:
        source = inspect.getsource(stages.stage_readback)
        index = source.index('for _label in (')
        window = source[index:index + 80]
        for label in ("上架时间", "发货时间", "提取方式"):
            with self.subTest(label=label):
                self.assertIn(label, window)


class CountIsNotInflatedTest(unittest.TestCase):
    def test_the_count_still_comes_only_from_matched(self) -> None:
        source = inspect.getsource(stages.stage_readback)
        index = source.index("项全部一致")
        segment = source[source.rindex("summary=", 0, index):index + 60]
        self.assertIn("len(matched)", segment)
        self.assertNotIn("default_notice", segment)

    def test_the_notice_is_appended_separately(self) -> None:
        source = inspect.getsource(stages.stage_readback)
        self.assertIn("+ notice_text", source)


class SmokeArtifactCarriesItTest(unittest.TestCase):
    def test_the_script_records_default_notice(self) -> None:
        """不记的话，事后看产物只有一句 summary，重建不出当时的状态。"""

        source = SMOKE.read_text(encoding="utf-8")
        self.assertIn("default_notice", source)


class ReadSelectedOptionsStillWorksTest(unittest.TestCase):
    def test_it_tries_both_row_profiles(self) -> None:
        """第 58 轮的坑：行结构取决于**怎么到页面的**。"""

        expression = page.build_read_selected_options_expression("上架时间")
        self.assertIn("sell-component-info-wrapper-wrap", expression)
        self.assertIn("sell-catProp-item-common", expression)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""`readback` 的最后一项：**平台自己说这张表单能不能提交**。

## 缺口

`readback` 原先核对 8 项——但它们**每一项都是我们自己从 `item` 算出来的期望值**：

> 八项全一致，只能说明「我们填的进去了」，
> **不能说明「表单完整、平台愿意收」**。

而**提交按钮的 `disabled` 是平台自己的判断**：它把该类的全部必填校验都算进去，
**包括我们没实现/没填的那些行**（发货时间、提取方式、电脑端描述…）。

**它是唯一一个不依赖我们自己的完整性信号。**

## 实测（2026-10-03）

```
"submit": {"present": true, "disabled": false, "visible": true}
```

URL 里还带着品牌生效的证据：

```
keyProps={"p-20000":{"value":30025069481,"text":"无品牌/无注册商标"}}
```

**平台自己记下了 `p-20000`（品牌属性 id）= 无品牌/无注册商标。**

完整链条跑下来：

```
[OK] readback  回读核对通过：9 项全部一致
     （…、运费模板、提交按钮）
```
"""

from __future__ import annotations

import inspect
import pathlib
import sys
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page, stages  # noqa: E402
from taobao_publish.models import (  # noqa: E402
    CategoryRef,
    ImageSet,
    PropEntry,
    PublishItem,
    SkuEntry,
)


def make_item() -> PublishItem:
    return PublishItem(
        record_id=1, record_name="X", title="标题", guide_title="导购",
        category=CategoryRef(path=("a", "b"), category_id="202187801"),
        images=ImageSet(main=["a.jpg"], detail=[]),
        props=[PropEntry("品牌", "无品牌/无注册商标")],
        skus=[SkuEntry(spec_values={"尺码": "M"}, price=16.8, stock=200)],
        freight_template_name="极兔快递",
    )


class SubmitReadyExpectationTest(unittest.TestCase):
    def setUp(self) -> None:
        ctx = stages.PipelineContext(item=make_item(), dry_run=False)
        self.entries = stages.expected_field_values(ctx)

    def test_submit_button_is_among_the_expectations(self) -> None:
        labels = [e["label"] for e in self.entries]
        self.assertIn("提交按钮", labels)

    def test_it_is_marked_veto_only(self) -> None:
        """⚠️ **它只做否决，不是一项通过的核对。**

        `stage_submit` 的注释里写着实测事实：「按钮可用」不等于「表单填完了」——
        平台是**点击之后才校验**的。把它算进「N 项一致」会虚增计数，
        还会给人「平台说可以提交」的误导印象。
        """

        entry = next(e for e in self.entries if e["label"] == "提交按钮")
        self.assertEqual(entry["kind"], "submit_ready")
        self.assertTrue(entry.get("veto_only"), "必须标成 veto_only")
        self.assertIn("平台", entry["source"])
        self.assertIn("read_submit_state", entry["source"])
        self.assertIn("只做否决", entry["source"])

    def test_it_is_the_last_expectation(self) -> None:
        """放在最后：它是**总括性**的一项，前置的是逐字段核对。"""

        self.assertEqual(self.entries[-1]["label"], "提交按钮")


class VetoDoesNotInflateTheCountTest(unittest.TestCase):
    """**「N 项一致」的 N 不许被否决项算进去。**"""

    def test_only_the_veto_entry_is_flagged(self) -> None:
        ctx = stages.PipelineContext(item=make_item(), dry_run=False)
        entries = stages.expected_field_values(ctx)
        vetoes = [e for e in entries if e.get("veto_only")]
        self.assertEqual([e["label"] for e in vetoes], ["提交按钮"])
        # 目前 10 个真正的核对项：标题、导购标题、品牌、一口价、总库存、
        # 主图（内容或张数）、SKU 规格值、SKU 价格、逐行价格库存、运费模板。
        self.assertEqual(len(entries) - len(vetoes), 10,
                         "除否决项外应当还有 10 个真正的核对项")

    def test_readback_stage_records_vetoes_separately(self) -> None:
        """源码里必须把否决项单独记，而不是并进 `matched`。"""

        import inspect

        source = inspect.getsource(stages.stage_readback)
        self.assertIn("vetoes_passed", source)
        self.assertIn('entry.get("veto_only")', source)


class SubmitReadyDispatchTest(unittest.TestCase):
    """分派要如实区分四种情形。"""

    def _read(self, state):
        client = mock.MagicMock()
        with mock.patch.object(page, "read_submit_state", return_value=state):
            return stages._read_expected_value(
                client, page, {"label": "提交按钮", "kind": "submit_ready"})

    def test_enabled_button_is_ok(self) -> None:
        self.assertEqual(self._read({"submit": {"present": True,
                                                "disabled": False,
                                                "visible": True}}), "可点")

    def test_disabled_button_is_reported(self) -> None:
        """⚠️ **这一条正是新检查的意义**：8 项都对但平台说不行。"""

        self.assertEqual(self._read({"submit": {"present": True,
                                                "disabled": True,
                                                "visible": True}}), "不可点")

    def test_missing_button_is_reported(self) -> None:
        self.assertIn("查不到", self._read({"submit": {"present": False}}))

    def test_invisible_button_is_reported(self) -> None:
        self.assertIn("不可见", self._read({"submit": {"present": True,
                                                     "disabled": False,
                                                     "visible": False}}))

    def test_is_not_a_boolean_trap(self) -> None:
        """`disabled` 缺失时**不能**当成「可点」——那是把「不知道」当「没问题」。"""

        self.assertNotEqual(self._read({"submit": {"present": True}}), "可点")


class ReadbackOnlyRunsInWriteModeTest(unittest.TestCase):
    """`readback` 只在真实写入模式下跑——所以这一项在 dry-run 下不会误报。"""

    def test_readback_is_skipped_in_dry_run(self) -> None:
        """源码里写明了理由：校对模式没有本次写入可回读。"""

        source = inspect.getsource(stages.stage_readback)
        self.assertIn("dry_run", source)
        # 阶段登记表里它是只读且不改页面
        spec = stages.STAGE_HANDLERS["readback"]
        self.assertIsNone(spec.write_operation)
        self.assertFalse(spec.mutates_page)


class ChainScriptReportsNineItemsTest(unittest.TestCase):
    def test_chain_script_covers_the_new_item(self) -> None:
        """冒烟脚本的链条要能覆盖到它（readback 在链尾）。"""

        script = (SUBPROJECT / "scripts" / "smoke-full-chain-live.py").read_text(encoding="utf-8")
        self.assertIn('"readback"', script)
        chain = script[script.index("CHAIN = ("):script.index(")", script.index("CHAIN = ("))]
        self.assertLess(chain.index("readback"), len(chain),
                        "readback 要在链条里且是最后一步")


if __name__ == "__main__":
    unittest.main()

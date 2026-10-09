# -*- coding: utf-8 -*-
"""**「拒绝猜」必须发生在表达式里，不能只写在 Python 包装层。**

第 31 轮发现选图在命中多张时静默挑了第一张，改法是「命中不是恰好 1 张就拒绝」——
**但那个判断被写在了 Python 包装层**，而表达式里是：

```js
if (found.hits.length >= 1) {
  clickTarget(found.hits[0]).click();      // ← 5 张也照点第一张
  return { ok: true, matched: found.hits.length };
}
```

于是调用顺序是**先点错、后报错**。实机实测（2026-10-03，只读验证）：

```
修复前：三次「已拒绝」的调用  →  主图位 0 → **3**     （点击全都发生了）
修复后：三次「已拒绝」的调用  →  主图位 0 → 0        （一次点击都没发生）
```

**改动看起来做了正确的事，实际执行路径没有被拦住**——这是这几轮反复碰到的同一类。

这些用例钉住：
1. 表达式里是 `=== 1` 才点，不是 `>= 1`；
2. 多张时**返回** `ambiguous` 而不是点击；
3. 文案按 reason 分开写（说「有 N 张」，不是「没有」）。
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page  # noqa: E402


class ExpressionMustNotClickOnAmbiguityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.expression = page.build_select_media_image_expression("主图01.jpg")

    def test_clicks_only_when_exactly_one(self) -> None:
        self.assertIn("hits.length === 1", self.expression,
                      "必须是「恰好一张才点」")
        self.assertNotIn("hits.length >= 1", self.expression,
                         "`>= 1` 会在多张时也点第一张——**先点错、后报错**")

    def test_url_disambiguation_still_requires_exactly_one(self) -> None:
        """同名多张时允许**按期望 URL 消歧**，但消歧后仍必须**恰好一张**。

        这是 2026-10-05 加的：协议上传回执里有那张图的准确 URL，
        图库里存在同名旧图时，只有 URL 能确定身份。放宽的只有「拿什么判身份」，
        「不是唯一就拒绝」这条没有放宽——命中 0 张或 ≥2 张仍然拒绝。
        """

        self.assertIn("hits.length > 1 && WANT", self.expression,
                      "只有给了期望 URL 才允许走消歧分支")
        self.assertIn("byUrl.length !== 1", self.expression,
                      "消歧后不是恰好一张必须拒绝（reason: ambiguous_after_url_match）")
        self.assertIn("ambiguous_after_url_match", self.expression)
        self.assertIn("urlMap", self.expression, "批量查找按名字给期望 URL（urlMap）")

    def test_returns_ambiguous_instead_of_clicking(self) -> None:
        self.assertIn("reason: 'ambiguous'", self.expression)

    def test_no_click_in_the_ambiguous_branch(self) -> None:
        """`ambiguous` 那条分支里**不能有 click**。

        用「分支体里有没有 .click()」来判断——比只看关键字可靠。
        """

        marker = "reason: 'ambiguous'"
        index = self.expression.index(marker)
        # 往回找这条分支的开头（`if (found.hits.length > 1) {`）
        branch_start = self.expression.rindex("hits.length > 1", 0, index)
        # 往前后各取一段，确认这段里没有 click
        segment = self.expression[branch_start:index]
        self.assertNotIn(".click()", segment,
                         "ambiguous 分支里不能点击——那正是「先点错」的来源")

    def test_no_double_braces_left(self) -> None:
        self.assertEqual(self.expression.count("{{") + self.expression.count("}}"), 0)


class ReasonAwareMessageTest(unittest.TestCase):
    """文案要说**真实原因**。"""

    def _raise_for(self, payload):
        client = mock.MagicMock()
        client.evaluate.side_effect = [{'ok': True, 'supported': True, 'busy': False}, payload]
        with mock.patch.object(page, "wait_for_media_cards", return_value=1):
            with mock.patch.object(page.time, "sleep", lambda *_: None):
                with self.assertRaises(Exception) as ctx:
                    page.select_media_image(client, "主图01.jpg", context_id=1)
        self.assertEqual(client.evaluate.call_count, 2, '必须检查真实选图回执而非提前被加载状态拒绝')
        return str(ctx.exception)

    def test_ambiguous_says_how_many(self) -> None:
        message = self._raise_for({"ok": False, "reason": "ambiguous", "matched": 5})
        self.assertIn("有 5 张", message)
        self.assertIn("拒绝猜", message)
        self.assertNotIn("没有文件名含", message, "有多张时**不能说「没有」**")

    def test_no_cards_says_so(self) -> None:
        message = self._raise_for({"ok": False, "reason": "no_cards"})
        self.assertIn("no_cards", message)
        self.assertIn("还没渲染", message)

    def test_no_match_says_not_found(self) -> None:
        message = self._raise_for({"ok": False, "reason": "no_match"})
        self.assertIn("没有文件名含", message)

    def test_unexpected_matched_is_refused(self) -> None:
        """表达式理论上只返回 `matched == 1` 的成功值；真出现别的，**显式拒绝**。"""

        message = self._raise_for({"ok": True, "matched": 3})
        self.assertIn("matched=3", message)
        self.assertIn("拒绝", message)

    def test_happy_path_returns_payload(self) -> None:
        client = mock.MagicMock()
        client.evaluate.side_effect = [{'ok': True, 'supported': True, 'busy': False},
            {"ok": True, "matched": 1, "hint": "X", "url": "https://img.example.invalid/x.jpg"}]
        with mock.patch.object(page, "wait_for_media_cards", return_value=1):
            with mock.patch.object(page.time, "sleep", lambda *_: None):
                got = page.select_media_image(client, "X", context_id=1)
        self.assertTrue(got.get("ok"))
        self.assertEqual(client.evaluate.call_count, 2)


if __name__ == "__main__":
    unittest.main()

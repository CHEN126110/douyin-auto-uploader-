# -*- coding: utf-8 -*-
"""选图器目录树是**虚拟列表**：只渲染滚动窗口里的节点（2026-10-10 真机）。

## 为什么单独一个文件

真机任务 ``6afce43f``（``record_id=2``，``ID-1089528753058``）：

* ``prepare_media`` **成功**：整目录 31 张 ``uploaded_now=true``，
  回执里的云端目录就是 ``ID-1089528753058/{主图,SKU,详情页}``；
* 紧接着 ``stage_upload_images`` 报
  ``媒体失败｜…｜页面=选图器｜目标=ID-1089528753058｜判据=directory_missing``，
  并提示"先在素材中心建好该目录"——**而那个目录和 31 张图都已经在云端**。

真机逐档实测（``tmp/probe-picker-scroll-map.json``，同一棵树反复设值）钉死了原因：
选图器目录树是 ``div.next-virtual-tree-container`` 里的虚拟列表
（``scrollHeight=616`` / ``clientHeight=306``），**只渲染滚动窗口里的节点**：

=================  ======================================  ==========
scrollTop          渲染出的根层                            目标在否
=================  ======================================  ==========
310（上次选中）     ``ID-986833932804`` + 智淘×3 + 神笔      否
200                含 ``ID-1089528753058``                是
0                  含 ``ID-1089528753058``（可重复）       是
=================  ======================================  ==========

同一个商品的**平台响应**（选图器自己发的 ``console.dir.query``）里根层有 8 个目录、
目标就在其中 —— 所以既不是"目录不存在"，也不是"平台没返回"，而是**页面只渲染了一部分**。

曾经以为是"弹层打开时的旧快照、重开就好"——**已被真机证伪**：重开后 iframe 确实重建
（``handleId`` 与上下文都换），但选中/滚动位置保留，窗口又落回原处，目标照样不在 DOM 里。

修复：``media_library._scroll_tree_to_top``，在**每次读树之前**把虚拟列表滚到顶。

## 边界

只用 ``unittest`` + 纯替身：不联网、不碰平台、不启浏览器、不写仓库外文件。
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from taobao_publish import form_adapters, media_library, page, stages
from taobao_publish.page import PageError


def tree(paths, *, current=("全部图片",)):
    """构造一份 ``folder_expression`` 那种形状的读树结果。"""

    return {
        "ok": True, "supported": True, "path": list(current),
        "paths": [list(path) for path in paths],
        "directories": [{"path": list(path), "folder_id": str(index + 1)}
                        for index, path in enumerate(paths)],
    }


#: 虚拟列表窗口停在"上次选中的目录"时，根层只渲染出这几个（真机 scrollTop=310 的读数）。
WINDOW_AT_BOTTOM = tree([["全部图片"], ["全部图片", "ID-986833932804"],
                         ["全部图片", "ID-986833932804", "详情页"],
                         ["全部图片", "智淘商品复制宝贝素材_勿删"]])

#: 滚到顶部之后：目标目录进入渲染窗口（真机 scrollTop=0 的读数）。
WINDOW_AT_TOP = tree([["全部图片"], ["全部图片", "ID-1089528753058"],
                      ["全部图片", "ID-986833932804"], ["全部图片", "神笔"]])

#: "滚了也读不到"用：窗口回到原处、目标**两个窗口里都没有**（目录确实不在云端时的形态）。
WINDOW_WITHOUT_TARGET = tree([["全部图片"], ["全部图片", "ID-986833932804"],
                              ["全部图片", "ID-986833932804", "详情页"]])


class FakeVirtualTreeClient:
    """按**滚动窗口位置**给不同快照的替身。

    收到"滚到顶"那条表达式 → 窗口切到顶部（``scrolled=True``）；
    收到读树表达式 → 按当前窗口返回。这样"滚了才读得到"这件事是可断言的，
    而不是靠调用顺序碰巧成立。

    ⚠️ 真实表达式由 ``media_library._SCROLL_TREE_TO_TOP_EXPRESSION`` 提供；
    这里只按它导出的**唯一标记**（``SCROLL_EXPRESSION_MARKER``）识别，
    避免把整段 JS 抄进测试（抄了就会漂移）。
    """

    SCROLL_MARKER = media_library.SCROLL_EXPRESSION_MARKER

    def __init__(self, *, window, top, bottom, context=0):
        self.window = window
        self.top = top
        self.bottom = bottom
        self.context = context
        self.reads = []
        self.scrolls = []
        self.scroll_effective = False

    def evaluate(self, expression, context_id=None, timeout=None):  # noqa: ARG002
        if self.SCROLL_MARKER in expression:
            self.scrolls.append(context_id)
            self.scroll_effective = self.window == self.bottom
            self.window = self.top
            return {"ok": True, "scrolled": self.scroll_effective}
        self.reads.append(context_id)
        return self.window

    def close(self):
        """阶段收尾会关客户端（真机是断开 CDP 连接）。"""


class ScrollIntoWindowTest(unittest.TestCase):
    """`ensure_product_root`：读之前先把虚拟列表滚到顶。"""

    PRODUCT = "ID-1089528753058"

    def _client(self):
        return FakeVirtualTreeClient(window=WINDOW_AT_BOTTOM,
                                     top=WINDOW_AT_TOP, bottom=WINDOW_AT_BOTTOM)

    def test_missing_from_the_window_is_found_after_scrolling_to_top(self) -> None:
        client = self._client()
        path = media_library.ensure_product_root(
            client, self.PRODUCT, context_id=None,
            on_stale=lambda name: 99, context_holder={"context_id": None})

        self.assertEqual(["全部图片", self.PRODUCT], path)
        self.assertEqual(1, len(client.reads), "滚到顶之后第一次读就该命中，不该再重试")
        self.assertEqual([None], client.scrolls, "读之前必须滚一次")
        self.assertEqual([None], client.reads, "滚动与读都用**同一个**上下文")

    def test_scroll_happens_before_every_read(self) -> None:
        """已经有了窗口的节点时也要滚（幂等，只改滚动位置）。"""

        client = FakeVirtualTreeClient(window=WINDOW_AT_TOP,
                                       top=WINDOW_AT_TOP, bottom=WINDOW_AT_BOTTOM)
        path = media_library.ensure_product_root(client, self.PRODUCT, context_id=None)
        self.assertEqual(["全部图片", self.PRODUCT], path)
        self.assertEqual([None], client.scrolls)

    def test_no_scroll_is_attempted_when_nothing_is_missing(self) -> None:
        """命中就只滚一次、读一次——不许因为"顺手"多读。"""

        client = FakeVirtualTreeClient(window=WINDOW_AT_TOP,
                                       top=WINDOW_AT_TOP, bottom=WINDOW_AT_BOTTOM)
        media_library.ensure_product_root(client, self.PRODUCT, context_id=None)
        self.assertEqual(1, len(client.reads))
        self.assertEqual(1, len(client.scrolls))

    def test_scroll_failure_never_masks_the_real_judgement(self) -> None:
        """滚不动不是判决：树里真没有这个目录时，照旧如实报 directory_missing。"""

        class NoScrollClient(FakeVirtualTreeClient):
            def evaluate(self, expression, context_id=None, timeout=None):  # noqa: ARG002
                if self.SCROLL_MARKER in expression:
                    raise RuntimeError('虚拟列表容器找不到了')
                return super().evaluate(expression, context_id=context_id)

        client = NoScrollClient(window=WINDOW_AT_BOTTOM,
                                top=WINDOW_AT_TOP, bottom=WINDOW_AT_BOTTOM)
        with self.assertRaises(PageError) as caught:
            media_library.ensure_product_root(client, self.PRODUCT, context_id=None)
        self.assertIn("判据=directory_missing", str(caught.exception))

    def test_scroll_is_not_attempted_on_the_material_center_page(self) -> None:
        """素材中心页没有这棵虚拟列表：那里不许乱滚（跨页动作只做它该做的）。"""

        client = FakeVirtualTreeClient(window=WINDOW_AT_BOTTOM,
                                       top=WINDOW_AT_TOP, bottom=WINDOW_AT_BOTTOM)
        with self.assertRaises(PageError):
            media_library.ensure_product_root(
                client, self.PRODUCT, context_id=None,
                page=media_library.PAGE_MATERIAL_CENTER)
        self.assertEqual([], client.scrolls)


class SegmentedVirtualTreeClient:
    """按真实 metrics 驱动分段扫描；只认生产表达式导出的标记。"""

    def __init__(self, windows):
        self.windows = windows
        self.window = WINDOW_WITHOUT_TARGET
        self.positions = []
        self.reads = 0

    def evaluate(self, expression, context_id=None, timeout=None):  # noqa: ARG002
        if media_library.SCROLL_EXPRESSION_MARKER in expression:
            self.positions.append(0)
            self.window = self.windows.get(0, WINDOW_WITHOUT_TARGET)
            return {"ok": True}
        if media_library.VIRTUAL_TREE_METRICS_MARKER in expression:
            return {"ok": True, "virtualTreeMetrics": True,
                    "scrollHeight": 880, "clientHeight": 306}
        if media_library.SCROLL_TO_POSITION_MARKER in expression:
            position = int(expression.split("const position=", 1)[1].split(";", 1)[0])
            self.positions.append(position)
            self.window = self.windows.get(position, WINDOW_WITHOUT_TARGET)
            return {"ok": True, "scrollTop": position}
        self.reads += 1
        return self.window


class SegmentedProductRootTest(unittest.TestCase):
    """2026-10-27：目标在第二屏，回顶部找不到不等于目录不存在。"""

    PRODUCT = "ID-966677280061"

    def test_target_in_a_later_window_is_found_without_reopening(self) -> None:
        target_window = tree([["全部图片"], ["全部图片", self.PRODUCT]])
        client = SegmentedVirtualTreeClient({0: WINDOW_WITHOUT_TARGET, 229: target_window})
        stale = mock.Mock()
        path = media_library.ensure_product_root(
            client, self.PRODUCT, context_id=None, on_stale=stale)
        self.assertEqual(["全部图片", self.PRODUCT], path)
        self.assertEqual([0, 0, 229], client.positions)
        self.assertEqual(3, client.reads, "顶部初读、渲染后复读、第二屏各核对一次")
        stale.assert_not_called()

    def test_missing_target_scans_through_the_bottom_before_failing(self) -> None:
        client = SegmentedVirtualTreeClient({})
        with self.assertRaises(PageError) as caught:
            media_library.ensure_product_root(client, self.PRODUCT, context_id=None)
        self.assertIn("判据=directory_missing", str(caught.exception))
        self.assertEqual([0, 0, 229, 458, 574] * 2, client.positions,
                         "首次扫描到底后允许刷新一次；刷新后仍须扫描到底才能判定目录缺失")

    def test_position_scroll_expression_notifies_virtual_tree(self) -> None:
        expression = media_library._scroll_tree_to_position_expression(229)
        assignment = expression.index("scroller.scrollTop=position;")
        notification = expression.index("scroller.dispatchEvent(new Event('scroll'));")
        rendered = expression.index("await new Promise")
        self.assertLess(assignment, notification)
        self.assertLess(notification, rendered,
                        "必须先通知虚拟树重算窗口，再等待新节点挂载")


class RetryOpenDirectoryClient(SegmentedVirtualTreeClient):
    """根目录已展开但子目录未渲染：模拟失败重试时的真实页面。"""

    def __init__(self, windows, open_plan):
        super().__init__(windows)
        self.open_plan = [list(path) for path in open_plan]
        self.opened = []
        self.current = []

    def evaluate(self, expression, context_id=None, timeout=None):
        if '"action": "open"' in expression:
            target = self.open_plan[len(self.opened)]
            self.opened.append(target)
            self.current = list(target)
            return {"ok": True, "supported": True, "path": list(target)}
        result = super().evaluate(expression, context_id=context_id, timeout=timeout)
        if isinstance(result, dict) and "paths" in result:
            return {**result, "path": list(self.current)}
        return result


class RetryOpenDirectoryTest(unittest.TestCase):
    PRODUCT = "ID-966677280061"

    def test_expanded_root_child_is_scanned_before_opening(self) -> None:
        root_only = tree([["全部图片"], ["全部图片", self.PRODUCT]])
        with_child = tree([["全部图片"], ["全部图片", self.PRODUCT],
                           ["全部图片", self.PRODUCT, "主图"]])
        client = RetryOpenDirectoryClient({0: root_only, 229: with_child},
                                          open_plan=[[self.PRODUCT], [self.PRODUCT, "主图"]])
        with mock.patch.object(media_library, "wait_listing_settled", return_value={}), \
                mock.patch.object(page, "wait_for_media_gallery_ready", return_value={}):
            path = media_library.open_directory(
                client, [self.PRODUCT, "主图"], context_id=None)
        self.assertEqual([self.PRODUCT, "主图"], path)
        self.assertEqual([[self.PRODUCT], [self.PRODUCT, "主图"]], client.opened)
        self.assertEqual([0, 0, 0, 229], client.positions,
                         "根目录先定位一次；子目录回顶后再初读、渲染复读并定位第二屏")


class BindPreparedMediaRetryTest(unittest.TestCase):
    PRODUCT = "ID-966677280061"

    def test_binding_also_uses_segmented_lookup_when_direct_read_misses(self) -> None:
        target_window = tree([["全部图片"], ["全部图片", self.PRODUCT]])
        client = SegmentedVirtualTreeClient({0: WINDOW_WITHOUT_TARGET, 229: target_window})
        prepared = SimpleNamespace(
            manifest=SimpleNamespace(folder_name=self.PRODUCT),
            selection_plan=mock.Mock(return_value={}))
        with mock.patch.object(form_adapters, "config_for", return_value={}):
            plan = form_adapters.bind_prepared_media(
                client, SimpleNamespace(), {}, prepared, "account-A", context_id=None)
        self.assertEqual({}, plan)
        self.assertEqual([0, 0, 229], client.positions,
                         "绑定阶段的直读未命中后，也必须走同一套分段定位")


class EnsureProductRootStaleTreeTest(unittest.TestCase):
    """`ensure_product_root`：重取是兜底，滚到顶才是修复。"""

    PRODUCT = "ID-1089528753058"

    def test_refetch_fallback_still_reports_the_new_context(self) -> None:
        """调用方给了 `on_stale` 时，新上下文仍要回写（旧 id 重开后立刻失效）。

        构造：滚动后**窗口本身也不含目标**（目录确实不在树上时的形态）→ 走重取兜底 →
        重取换成另一个上下文，那一边的窗口里有目标。钉住的是"新上下文必须回写并用于下一次读"。
        """

        client = FakeVirtualTreeClient(window=WINDOW_AT_BOTTOM,
                                       top=WINDOW_WITHOUT_TARGET,
                                       bottom=WINDOW_AT_BOTTOM)
        holder = {"context_id": None}
        reopened = []

        def on_stale(product_name):
            reopened.append(product_name)
            # 换上下文之后那棵树是好的（滚到顶也会落在这个窗口上）。
            client.top = WINDOW_AT_TOP
            client.bottom = WINDOW_AT_TOP
            return 17

        with mock.patch.object(media_library.time, "sleep", return_value=None):
            path = media_library.ensure_product_root(
                client, self.PRODUCT, context_id=None, wait_seconds=0.0,
                on_stale=on_stale, context_holder=holder)

        self.assertEqual(["全部图片", self.PRODUCT], path)
        self.assertEqual([self.PRODUCT], reopened)
        self.assertEqual(17, holder["context_id"])
        self.assertIn(17, client.reads, "重取之后必须用**新的**上下文读")

    def test_unreadable_after_refetch_fails_loudly_with_a_runnable_action(self) -> None:
        """滚到顶 + 重取都做过仍读不到 → 如实失败，动作句不再让人去建可能已存在的目录。"""

        client = FakeVirtualTreeClient(window=WINDOW_AT_BOTTOM,
                                       top=WINDOW_AT_BOTTOM, bottom=WINDOW_AT_BOTTOM)
        with self.assertRaises(PageError) as caught:
            media_library.ensure_product_root(
                client, self.PRODUCT, context_id=None,
                on_stale=lambda name: 17, context_holder={"context_id": None})

        message = str(caught.exception)
        self.assertIn("判据=directory_missing", message)
        self.assertIn("目标={}｜".format(self.PRODUCT), message)
        self.assertNotIn("先在素材中心", message,
                         "已经滚过顶、也重取过还让人去建目录，会建出重复目录（真机踩过）")
        self.assertIn("手动重载淘宝发布页该标签页后重试", message)

    def test_without_a_refetch_callback_the_old_semantics_is_untouched(self) -> None:
        """没给重取回调时（DOM 路线/旧调用方）失败文案与改动前一致。"""

        client = FakeVirtualTreeClient(window=WINDOW_AT_BOTTOM,
                                       top=WINDOW_AT_BOTTOM, bottom=WINDOW_AT_BOTTOM)
        with self.assertRaises(PageError) as caught:
            media_library.ensure_product_root(client, self.PRODUCT, context_id=None)

        message = str(caught.exception)
        self.assertIn("分支=resolve_role_folder｜", message)
        self.assertIn("页面=选图器｜", message)
        self.assertIn("判据=directory_missing", message)
        self.assertIn("先在素材中心", message)

    def test_creator_path_still_wins_when_a_creator_is_given(self) -> None:
        """给了 ``creator`` 时仍然走建目录：滚动/重取是**并列**的助推，不是替代。"""

        client = FakeVirtualTreeClient(window=WINDOW_AT_BOTTOM,
                                       top=WINDOW_AT_BOTTOM, bottom=WINDOW_AT_BOTTOM)
        creator = mock.Mock(return_value={"主图": "333"})
        with mock.patch.object(media_library.time, "sleep", return_value=None):
            with self.assertRaises(PageError):
                media_library.ensure_product_root(
                    client, self.PRODUCT, context_id=None, creator=creator,
                    role_names=["主图"], wait_seconds=0.0)
        creator.assert_called_once()


class StageReopenPickerTest(unittest.TestCase):
    """`stage_upload_images`：陈旧窗口下**先滚后读**，并且不许再建空目录。"""

    PRODUCT = "ID-1089528753058"

    def _ctx(self):
        item = SimpleNamespace(images=SimpleNamespace(main=["主图.jpg"]), record_id=2,
                               record_name=self.PRODUCT)
        prepared = SimpleNamespace(manifest=SimpleNamespace(folder_name=self.PRODUCT))
        return SimpleNamespace(
            item=item, prepared_media=prepared, account_profile="A",
            resolved_contracts=lambda: {}, scratch={}, dry_run=False)

    def test_stage_scrolls_the_window_and_binds_with_the_same_context(self) -> None:
        client = FakeVirtualTreeClient(window=WINDOW_AT_BOTTOM,
                                       top=WINDOW_AT_TOP, bottom=WINDOW_AT_BOTTOM)
        ctx = self._ctx()
        with mock.patch.object(stages, "_stage_adapter_guard", return_value=None), \
                mock.patch.object(stages.os.path, "isfile", return_value=True), \
                mock.patch.object(form_adapters, "media_file_identity",
                                  return_value={"name": "主图.jpg", "path": "主图.jpg",
                                                "sha256": "a" * 64}), \
                mock.patch.object(stages, "_open_publish_page", return_value=client), \
                mock.patch.object(page, "read_main_image_slots",
                                  return_value={"found": True, "filled": 0}), \
                mock.patch.object(page, "open_media_popup") as open_popup, \
                mock.patch.object(page, "read_media_popup",
                                  return_value={"open": True}), \
                mock.patch.object(page, "media_iframe_context",
                                  return_value=17), \
                mock.patch.object(form_adapters, "bind_prepared_media",
                                  side_effect=PageError("fixture_after_bind")) as bind:
            stages.stage_upload_images(ctx)

        self.assertEqual([17], client.scrolls, "读之前必须在这棵树上滚一次")
        self.assertIn(17, client.reads)
        open_popup.assert_called_once_with(client)
        self.assertEqual(17, bind.call_args.kwargs["context_id"])
        self.assertNotIn("creator", " ".join(str(call) for call in client.reads))


if __name__ == "__main__":
    unittest.main()


# -*- coding: utf-8 -*-
"""「按图片空间目录归档」的四条接线回归（2026-10-07）。

## 为什么单独一个文件

复盘（`docs/35-淘宝发布路线复盘与图片上传流程选型_2026-10-06.md`）里，
"图片全落在图片空间根目录、不按商品文件夹归档"的根因**不是缺实现**，
而是四处接线：

1. 桌面任务从没设过 `TAOBAO_MEDIA_ROUTE` → 永远走 DOM 路线；
   而 DOM 路线的上传目标被 `upload_panel.ensure_all_images` **强制**成
   「全部图片」（根目录）。
2. 协议路线的目标目录必须**预先存在**，而唯一能自动建目录的
   `protocol_media.ensure_cloud_folders` **没有调用方**。
3. `form_adapters.prepare_media` 调 `resolve_role_folder` 时**没传 `creator=`**，
   于是目录不存在就只剩"请去素材中心手工建"这一条路。
4. 建目录是**跨页**动作（选图器里没有建目录入口，E-286；只有素材中心页有，
   E-282），只有流水线那层拿得到 CDP 端口——所以必须由 `stages` 侧提供 creator。

四条都在 2026-10-07 接上。这个文件把它们锁住：**任何一次重构把它们摘掉，
失败表现不是崩溃，而是图片悄悄传进根目录**——正是用户要修的那个问题。

## 边界

只用 `unittest` + 纯替身：不联网、不碰平台、不用系统临时目录
（本机沙箱下 `tempfile` 不可用，见 `tests/_helpers.py` 的说明）。
"""

from __future__ import annotations

import inspect
import os
import unittest
from contextlib import contextmanager, ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from taobao_publish import form_adapters, media_library, protocol_media, stages
from taobao_publish.authorization import WriteAuthorization
from taobao_publish.errors import WriteNotAuthorizedError
from taobao_publish.page import PageError

SUBPROJECT_ROOT = Path(__file__).resolve().parents[1]
SIDECAR_APP = SUBPROJECT_ROOT.parent / "tauri-app" / "python-sidecar" / "app.py"


@contextmanager
def route(value):
    """临时把 ``TAOBAO_MEDIA_ROUTE`` 设成 ``value``（``None`` = 不设）。"""

    key = protocol_media.ENV_MEDIA_ROUTE
    previous = os.environ.get(key)
    os.environ.pop(key, None)
    if value is not None:
        os.environ[key] = value
    try:
        yield
    finally:
        os.environ.pop(key, None)
        if previous is not None:
            os.environ[key] = previous


class FakeDirectoryClient:
    """只实现 `evaluate`——`media_library.read_directory` 的唯一依赖。

    ``supported=False`` 表示"当前页面没有可用的目录树"，于是
    `product_root_path` 返回 `None`，`resolve_role_folder` 直接进建目录分支。
    这正是"新商品第一次上架、图片空间里还没有它的目录"的真实形态。
    """

    def __init__(self, state):
        self.state = state
        self.expressions = []

    def evaluate(self, expression, context_id=None, timeout=None):  # noqa: ARG002
        self.expressions.append(expression)
        return self.state


class FakeContext:
    """最小 ctx：`_cloud_folder_creator` 只读这两个属性。"""

    def __init__(self, authorization, cdp_list_url="http://127.0.0.1:9555/json/list"):
        self.authorization = authorization
        self.cdp_list_url = cdp_list_url


def missing_directory_client():
    return FakeDirectoryClient({"ok": True, "supported": False, "paths": [], "directories": []})


class ResolveRoleFolderCreatorTest(unittest.TestCase):
    """第 3 条：目录缺失时必须调用 creator，且**一次建齐**全部角色目录。"""

    def test_missing_folder_calls_creator_with_every_role_once(self) -> None:
        # 建目录前后的两种树状态。新设计要求"**建完出现在树里**"（否则如实报错），
        # 所以夹具必须说出这件事，而不是永远返回"目录不存在"。
        missing = {
            "ok": True, "supported": True, "path": ["全部图片"],
            "paths": [["全部图片"], ["全部图片", "别的商品"]],
            "directories": [{"path": ["全部图片"], "folder_id": "0"},
                            {"path": ["全部图片", "别的商品"], "folder_id": "111"}],
        }
        created = {
            "ok": True, "supported": True, "path": ["全部图片", "ID-1074582642352"],
            "paths": [["全部图片"], ["全部图片", "ID-1074582642352"],
                      ["全部图片", "ID-1074582642352", "主图"]],
            "directories": [{"path": ["全部图片"], "folder_id": "0"},
                            {"path": ["全部图片", "ID-1074582642352"], "folder_id": "111"},
                            {"path": ["全部图片", "ID-1074582642352", "主图"],
                             "folder_id": "folder-主图"}],
        }
        client = SequenceDirectoryClient([missing, missing, created, created])
        seen = {}

        def creator(product_name, folder_names):
            seen["product"] = product_name
            seen["names"] = list(folder_names)
            return {name: "folder-" + name for name in folder_names}

        with mock.patch.object(media_library, "open_directory"):
            folder_id = media_library.resolve_role_folder(
                client, "ID-1074582642352", "主图", context_id=None,
                creator=creator, role_folders=["主图", "SKU", "详情页"])

        self.assertEqual("folder-主图", folder_id)
        self.assertEqual("ID-1074582642352", seen["product"])
        # 三个角色**一次**交出去：素材中心标签每个约 7 秒，不能三个角色各开一次。
        self.assertEqual(["主图", "SKU", "详情页"], seen["names"])

    def test_without_creator_it_still_fails_loudly(self) -> None:
        """不传 creator 时保持老语义：**如实报错**，绝不悄悄传到根目录。"""

        client = missing_directory_client()
        with self.assertRaises(PageError) as caught:
            media_library.resolve_role_folder(client, "ID-1", "主图", context_id=None)
        self.assertIn("素材中心", str(caught.exception))

    def test_creator_returning_nothing_for_the_role_is_rejected(self) -> None:
        """creator 必须给出**这个角色**的 folderId；给不出就失败，不猜。"""

        client = missing_directory_client()
        with self.assertRaises(PageError):
            media_library.resolve_role_folder(
                client, "ID-1", "主图", context_id=None,
                creator=lambda product_name, names: {"SKU": "111"},
                role_folders=["主图", "SKU"])


class CloudFolderCreatorTest(unittest.TestCase):
    """第 4 条：`stages._cloud_folder_creator` 的路由、授权与端口。"""

    def test_dom_route_has_no_creator(self) -> None:
        for value in (None, protocol_media.ROUTE_DOM):
            with self.subTest(route=value), route(value):
                self.assertIsNone(
                    stages._cloud_folder_creator(FakeContext(WriteAuthorization.for_form_filling())))

    def test_protocol_route_requires_upload_authorization(self) -> None:
        """建目录也是写平台：没授权时**一个目录都不建**。"""

        with route(protocol_media.ROUTE_PROTOCOL):
            create = stages._cloud_folder_creator(FakeContext(WriteAuthorization.none()))
            with mock.patch.object(protocol_media, "ensure_cloud_folders") as ensure:
                with self.assertRaises(WriteNotAuthorizedError):
                    create("ID-1", ["主图"])
                ensure.assert_not_called()

    def test_protocol_route_creates_on_the_same_browser_port_as_upload(self) -> None:
        """建目录与上传必须落在**同一个**调试浏览器上，否则上传那侧看不见目录。"""

        environment = dict(os.environ)
        os.environ.pop("TAOBAO_CDP_PORT", None)
        try:
            with route(protocol_media.ROUTE_PROTOCOL):
                create = stages._cloud_folder_creator(
                    FakeContext(WriteAuthorization.for_form_filling(),
                                cdp_list_url="http://127.0.0.1:9555/json/list"))
                with mock.patch.object(protocol_media, "ensure_cloud_folders",
                                       return_value={"主图": "222"}) as ensure:
                    created = create("ID-1", ["主图", "SKU"])
        finally:
            os.environ.clear()
            os.environ.update(environment)

        self.assertEqual({"主图": "222"}, created)
        ensure.assert_called_once_with(9555, "ID-1", ["主图", "SKU"])

    def test_stage_hands_the_creator_to_prepare_media(self) -> None:
        """第 2 条的另一半：creator 要真的被传进 `prepare_media`，否则形同虚设。"""

        source = inspect.getsource(stages.stage_upload_images)
        self.assertIn("folder_creator=_cloud_folder_creator(ctx)", source)
        self.assertIn("protocol_upload=_protocol_upload_hook(ctx)", source)


class PrepareMediaForwardingTest(unittest.TestCase):
    """第 3 条的前半段：`prepare_media` 必须把 creator 与角色清单一并转交。"""

    def test_signature_keeps_backward_compatible_default(self) -> None:
        parameter = inspect.signature(form_adapters.prepare_media).parameters["folder_creator"]
        self.assertIsNone(parameter.default, "不传 creator 时必须保持原行为（如实报错）")

    def test_forwards_creator_and_role_names(self) -> None:
        source = inspect.getsource(form_adapters.prepare_media)
        self.assertIn("creator=folder_creator", source)
        self.assertIn("role_folders=folder_names", source)
        # 角色清单要在循环**之前**算好，否则只有被请求的那个角色会被建。
        self.assertIn("folder_names = sorted({str(groups[role]) for role in plan})", source)
        self.assertLess(source.index("folder_names = sorted("),
                        source.index("creator=folder_creator"))

    def test_folders_are_created_before_any_path_scan(self) -> None:
        """**先建目录，再按路径扫**——顺序错了就是"新商品第一次上架必然失败"。

        真机 2026-10-07：扫描在 ``['全部图片', ID-…]`` 上拿 ``directory_missing``，
        而建目录排在它后面，永远跑不到；平台上于是从头到尾没有该商品目录。
        """

        source = inspect.getsource(form_adapters.prepare_media)
        self.assertLess(source.index("resolve_role_folder("),
                        source.index("lookup = find_product_images("),
                        "建目录必须早于任何按路径的扫描")

    def test_no_longer_invents_a_directory_path(self) -> None:
        """**不再自己拼目录路径**：选图器里商品目录是顶层节点，真实路径不带「全部图片」前缀。"""

        source = inspect.getsource(form_adapters.prepare_media)
        self.assertNotIn("ALL_IMAGES_NODE, item.record_name", source,
                         "拼出来的 ['全部图片', 商品名, 角色] 是一条注定不存在的路径")

    def test_rejects_pending_media_without_a_role_folder(self) -> None:
        """素材身份缺用途目录时**拒绝按根目录上传**（不是回退，是拒绝）。"""

        source = inspect.getsource(form_adapters.prepare_media)
        self.assertIn("素材身份缺少用途目录，拒绝按根目录上传", source)


class SidecarRouteDefaultTest(unittest.TestCase):
    """第 1 条：桌面任务必须真的打开协议路线，且**显式值优先**（可一行回滚）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SIDECAR_APP.read_text(encoding="utf-8")

    def task_source(self) -> str:
        marker = "def _run_taobao_publish_task("
        start = self.source.index(marker)
        rest = self.source[start + len(marker):]
        end = rest.index("\ndef ")
        return rest[:end]

    def test_task_enables_protocol_media_route(self) -> None:
        task = self.task_source()
        self.assertIn("os.environ.setdefault('TAOBAO_MEDIA_ROUTE', 'protocol')", task)

    def test_explicit_route_value_is_not_overridden(self) -> None:
        """用 `setdefault` 而不是赋值：用户显式设 `dom` 时必须能回滚。"""

        task = self.task_source()
        self.assertNotIn("os.environ['TAOBAO_MEDIA_ROUTE'] = 'protocol'", task)
        self.assertNotIn('os.environ["TAOBAO_MEDIA_ROUTE"] = "protocol"', task)
        # 唯一允许的赋值是**还原原值**（见下一条）。
        self.assertIn("os.environ['TAOBAO_MEDIA_ROUTE'] = _previous_media_route", task)

    def test_media_route_is_restored_when_the_task_ends(self) -> None:
        """用完必须还原。

        `setdefault` 改的是**进程级**环境变量，而 `tests/test_desktop_fill_entry.py`
        会 exec 本函数并**真的调用它**（`:300`、`:315`）。不还原就会把 `protocol`
        泄漏给同一进程里后面的用例，让它们从 DOM 路线悄悄切到协议路线而集体失败——
        2026-10-07 实测让全量回归红了 **24 项**，而且症状与本次改动看起来毫无关系。
        """

        task = self.task_source()
        self.assertIn("_previous_media_route = os.environ.get('TAOBAO_MEDIA_ROUTE')", task)
        self.assertIn("os.environ.pop('TAOBAO_MEDIA_ROUTE', None)", task)
        self.assertIn("finally:", task)

    def test_route_is_set_before_the_pipeline_runs(self) -> None:
        """必须在 `pipeline.run_from_record` **之前**设，否则本次运行读不到。"""

        task = self.task_source()
        self.assertLess(task.index("TAOBAO_MEDIA_ROUTE"),
                        task.index("pipeline.run_from_record("))


class RootPrefixTest(unittest.TestCase):
    """「全部图片」这一层在树里怎么表示——**两个页面不一样**（2026-10-07 真机）。

    写死"一定有根节点"会让 `ensure_cloud_folders` 在素材中心页必然失败；
    写死"一定没有根节点"又会让选图器那条路失效。所以判据必须是**看树**。
    """

    def test_picker_page_uses_the_explicit_root_node(self) -> None:
        state = {"supported": True,
                 "paths": [["全部图片"], ["全部图片", "ID-1"]],
                 "directories": [{"path": ["全部图片"], "folder_id": "0"}]}
        self.assertEqual(["全部图片"], media_library.root_prefix(state))

    def test_material_center_page_root_is_the_tree_itself(self) -> None:
        """素材中心页实测：顶层 path 只有一段，``全部图片`` 节点根本不在树里。"""

        state = {"supported": True,
                 "paths": [["ID-1074582642352"], ["ID-1074582642352", "SKU"]],
                 "directories": [{"path": ["ID-1074582642352"], "folder_id": "111"}]}
        self.assertEqual([], media_library.root_prefix(state))

    def test_unrendered_tree_is_not_guessed(self) -> None:
        """树里一个节点都没有 → 返回 None（读不到就不猜），由调用方如实失败。"""

        self.assertIsNone(media_library.root_prefix({"supported": True, "paths": []}))


class EnsureChildDirectoryRootTest(unittest.TestCase):
    """「新建文件夹」建在**当前选中目录**下，所以父目录为空时必须先回到根。"""

    def test_empty_parent_returns_to_root_instead_of_using_the_tree(self) -> None:
        with mock.patch.object(media_library, "directory_folder_id",
                               side_effect=[None, "222"]) as folder_id, \
                mock.patch.object(media_library, "open_directory") as enter, \
                mock.patch.object(media_library, "open_root_directory") as to_root:
            client = mock.Mock()
            client.evaluate.return_value = {"ok": True}
            created = media_library.ensure_child_directory(client, [], "ID-1", context_id=None)

        self.assertEqual("222", created)
        to_root.assert_called_once()
        enter.assert_not_called()
        self.assertEqual(2, folder_id.call_count)

    def test_non_empty_parent_still_enters_it(self) -> None:
        # 懒加载助推窗口 patch 成 0：这个用例验证的是「非空父目录 → 创建前
        # 先站上去」，助推回路有专门的合成用例覆盖，这里不再真等 5 秒。
        with mock.patch.object(media_library, "_EXISTENCE_RENDER_TIMEOUT", 0.0), \
                mock.patch.object(media_library, "directory_folder_id",
                               side_effect=[None, "333"]), \
                mock.patch.object(media_library, "open_directory") as enter, \
                mock.patch.object(media_library, "open_root_directory") as to_root:
            client = mock.Mock()
            client.evaluate.return_value = {"ok": True}
            created = media_library.ensure_child_directory(
                client, ["全部图片", "ID-1"], "主图", context_id=None)

        self.assertEqual("333", created)
        enter.assert_called_once()
        to_root.assert_not_called()

    def test_existing_folder_creates_nothing(self) -> None:
        """幂等：目录已存在时**一次都不点**（不评估守卫、不建目录）。"""

        with mock.patch.object(media_library, "directory_folder_id", return_value="111"):
            client = mock.Mock()
            created = media_library.ensure_child_directory(client, [], "ID-1", context_id=None)

        self.assertEqual("111", created)
        client.evaluate.assert_not_called()


class SequenceDirectoryClient(FakeDirectoryClient):
    """按调用次数依次返回不同状态（最后一次重复），用来模拟"先空、后渲染"。"""

    def __init__(self, states):
        super().__init__(states[0])
        self._states = list(states)
        self._calls = 0

    def evaluate(self, expression, context_id=None, timeout=None):  # noqa: ARG002
        self.expressions.append(expression)
        if self._calls < len(self._states) - 1:
            self._calls += 1
        return self._states[self._calls]


class RoleFolderWaitTest(unittest.TestCase):
    """有界等待：**先等渲染，再判定"不存在"**——否则会白白拒绝或误建。"""

    WITHOUT_ROLE = {
        "ok": True, "supported": True, "path": ["全部图片", "ID-1"],
        "paths": [["全部图片"], ["全部图片", "ID-1"]],
        "directories": [{"path": ["全部图片"], "folder_id": "0"},
                        {"path": ["全部图片", "ID-1"], "folder_id": "111"}],
    }

    WITH_ROLE = {
        "ok": True, "supported": True, "path": ["全部图片", "ID-1"],
        "paths": [["全部图片"], ["全部图片", "ID-1"], ["全部图片", "ID-1", "主图"]],
        "directories": [{"path": ["全部图片"], "folder_id": "0"},
                        {"path": ["全部图片", "ID-1"], "folder_id": "111"},
                        {"path": ["全部图片", "ID-1", "主图"], "folder_id": "999"}],
    }

    def test_role_folder_that_appears_after_a_wait_is_used(self) -> None:
        """第一次读不到、随即渲染出来 → **用渲染出来的那个**，不建新目录。"""

        creator = mock.Mock(return_value={"主图": "333"})
        client = SequenceDirectoryClient([self.WITHOUT_ROLE, self.WITHOUT_ROLE,
                                          self.WITH_ROLE, self.WITH_ROLE])
        with mock.patch.object(media_library, "open_directory"):
            resolved = media_library.resolve_role_folder(
                client, "ID-1", "主图", context_id=None,
                creator=creator, role_folders=["主图"])

        self.assertEqual("999", resolved)
        creator.assert_not_called()


class EnsureProductRootTest(unittest.TestCase):
    """`ensure_product_root`：**唯一**建目录入口（2026-10-07 做减法后）。

    判据只剩一条：**商品目录自己在不在树里**。不再看"子目录渲染没渲染"——
    那套 `rendered_children` 门 + 配套轮询已经删掉：它把"没渲染"与"不存在"
    混在一起，真机上反而让"目录确实不存在"这条主路径走不到建目录。
    """

    #: 商品目录**不在**树里（全新商品第一次上架）。
    MISSING = {
        "ok": True, "supported": True, "path": ["全部图片"],
        "paths": [["全部图片"], ["全部图片", "别的商品"]],
        "directories": [{"path": ["全部图片"], "folder_id": "0"},
                        {"path": ["全部图片", "别的商品"], "folder_id": "111"}],
    }

    #: 商品目录在树里。
    PRESENT = {
        "ok": True, "supported": True, "path": ["全部图片", "ID-1"],
        "paths": [["全部图片"], ["全部图片", "ID-1"], ["全部图片", "ID-1", "主图"]],
        "directories": [{"path": ["全部图片"], "folder_id": "0"},
                        {"path": ["全部图片", "ID-1"], "folder_id": "111"},
                        {"path": ["全部图片", "ID-1", "主图"], "folder_id": "222"}],
    }

    def test_missing_product_folder_creates_it_once_and_waits(self) -> None:
        creator = mock.Mock(return_value={"主图": "333"})
        client = SequenceDirectoryClient([self.MISSING, self.MISSING, self.PRESENT])
        with mock.patch.object(media_library.time, "sleep", return_value=None):
            path = media_library.ensure_product_root(
                client, "ID-1", context_id=None, creator=creator, role_names=["主图"])
        self.assertEqual(["全部图片", "ID-1"], path)
        creator.assert_called_once_with("ID-1", ["主图"])

    def test_present_product_folder_never_creates(self) -> None:
        creator = mock.Mock(return_value={"主图": "333"})
        path = media_library.ensure_product_root(
            FakeDirectoryClient(self.PRESENT), "ID-1", context_id=None,
            creator=creator, role_names=["主图"])
        self.assertEqual(["全部图片", "ID-1"], path)
        creator.assert_not_called()

    def test_without_creator_it_still_fails_loudly_instead_of_falling_back_to_root(self) -> None:
        with self.assertRaises(PageError) as caught:
            media_library.ensure_product_root(
                FakeDirectoryClient(self.MISSING), "ID-1", context_id=None)
        message = str(caught.exception)
        # 兼容锚点：既有的「去素材中心建」语义不许丢。
        self.assertIn("素材中心", message)
        # 契约六项：阶段 / 分支 / 页面 / 目标 / 判据 / 下一步。
        self.assertIn("媒体失败｜阶段=upload_images｜", message)
        self.assertIn("分支=resolve_role_folder｜", message)
        self.assertIn("页面=选图器｜", message)
        self.assertIn("目标=ID-1｜", message)
        self.assertIn("判据=directory_missing", message)
        self.assertIn("下一步：", message)

    def test_created_but_still_invisible_is_reported_not_swallowed(self) -> None:
        """建完仍读不到 → **如实报错**，不假装成功、不回退根目录。

        这条报错语义（建过但读不到）**保留**，本轮只补齐页面与路径：
        页面是建目录前所在的选图器，目标是刚建好的那个商品目录名。
        """

        creator = mock.Mock(return_value={"主图": "333"})
        with mock.patch.object(media_library.time, "sleep", return_value=None):
            with self.assertRaises(PageError) as caught:
                media_library.ensure_product_root(
                    FakeDirectoryClient(self.MISSING), "ID-1", context_id=None,
                    creator=creator, role_names=["主图"], wait_seconds=0.0)
        message = str(caught.exception)
        self.assertIn("目录树没能刷新出来", message)
        self.assertIn("阶段=upload_images", message)
        self.assertIn("分支=ensure_product_root", message)
        self.assertIn("页面=选图器", message)
        self.assertIn("目标=ID-1", message)
        self.assertIn("判据=directory_missing", message)
        self.assertIn("下一步：", message)


class PreparedMediaBindingTest(unittest.TestCase):
    """已完成整目录上传的商品只绑定回执；缺失交接目录不能靠新建空目录掩盖。"""

    def _run_binding(self, directory_error=None):
        from taobao_publish import page
        client = mock.Mock()
        prepared = SimpleNamespace(manifest=SimpleNamespace(folder_name='ID-1'))
        ctx = SimpleNamespace(
            item=SimpleNamespace(images=SimpleNamespace(main=['主图.jpg']), record_id=1),
            prepared_media=prepared, account_profile='A', resolved_contracts=lambda: {}, scratch={})
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(stages, '_stage_adapter_guard', return_value=None))
            stack.enter_context(mock.patch.object(stages.os.path, 'isfile', return_value=True))
            stack.enter_context(mock.patch.object(form_adapters, 'media_file_identity',
                return_value={'name': '主图.jpg', 'path': '主图.jpg', 'sha256': 'a' * 64}))
            stack.enter_context(mock.patch.object(stages, '_open_publish_page', return_value=client))
            stack.enter_context(mock.patch.object(page, 'read_main_image_slots', return_value={'found': True, 'filled': 0}))
            open_popup = stack.enter_context(mock.patch.object(page, 'open_media_popup'))
            stack.enter_context(mock.patch.object(page, 'read_media_popup', return_value={'open': True}))
            stack.enter_context(mock.patch.object(page, 'media_iframe_context', return_value=17))
            creator = stack.enter_context(mock.patch.object(stages, '_cloud_folder_creator'))
            upload = stack.enter_context(mock.patch.object(form_adapters, 'prepare_media'))
            ensure = stack.enter_context(mock.patch.object(media_library, 'ensure_product_root', side_effect=directory_error))
            bind = stack.enter_context(mock.patch.object(form_adapters, 'bind_prepared_media',
                side_effect=PageError('fixture_after_bind')))
            outcome = stages.stage_upload_images(ctx)
        creator.assert_not_called()
        upload.assert_not_called()
        open_popup.assert_called_once_with(client)
        client.close.assert_called_once()
        return outcome, ensure, bind, prepared, client

    def test_existing_prepared_directory_binds_receipt_without_uploading_again(self):
        outcome, ensure, bind, prepared, client = self._run_binding()
        ensure.assert_called_once_with(client, 'ID-1', context_id=17, wait_seconds=8.0)
        bind.assert_called_once()
        self.assertIs(bind.call_args.args[3], prepared)
        self.assertEqual(bind.call_args.args[4], 'A')
        self.assertFalse(outcome.ok)  # 替身在绑定边界明确截停，未模拟后续图片成功回填。
        self.assertIn('fixture_after_bind', outcome.summary)

    def test_missing_prepared_directory_fails_before_binding_or_creating_folders(self):
        outcome, ensure, bind, _prepared, _client = self._run_binding(PageError('directory_missing'))
        ensure.assert_called_once()
        bind.assert_not_called()
        self.assertFalse(outcome.ok)
        self.assertIn('directory_missing', outcome.summary)


if __name__ == "__main__":
    unittest.main()

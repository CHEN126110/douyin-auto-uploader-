# -*- coding: utf-8 -*-
"""店铺会话身份的不变量测试。

这些用例保护的是「不会把商品发到别人店铺」这条红线：
slug 必须幂等且互不碰撞，店铺 id 任何情况下都不能被猜出来。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src import shop_session  # noqa: E402


class SlugifyProfileNameTest(unittest.TestCase):
    def test_is_idempotent(self) -> None:
        # slugify 在路由、注册表、目录解析三层都会被调用。
        # 不幂等就会出现「切换成功但列表里找不到这家店」。
        for name in ["测试店铺甲", "A店", "Shop B", "", "upload-browser-profile", "abc-12345678"]:
            once = shop_session.slugify_profile_name(name)
            twice = shop_session.slugify_profile_name(once)
            self.assertEqual(once, twice, f"slugify 对 {name!r} 不幂等")

    def test_chinese_names_do_not_collapse_into_default_profile(self) -> None:
        # 纯中文名如果被过滤成空串再退回默认 profile，
        # 两家店会共用同一份登录态，等于发错店。
        first = shop_session.slugify_profile_name("甲店")
        second = shop_session.slugify_profile_name("乙店")
        self.assertNotEqual(first, shop_session.DEFAULT_PROFILE_NAME)
        self.assertNotEqual(second, shop_session.DEFAULT_PROFILE_NAME)
        self.assertNotEqual(first, second)

    def test_names_sharing_ascii_prefix_stay_distinct(self) -> None:
        self.assertNotEqual(
            shop_session.slugify_profile_name("A店"),
            shop_session.slugify_profile_name("A铺"),
        )

    def test_empty_name_falls_back_to_default_profile(self) -> None:
        self.assertEqual(shop_session.slugify_profile_name(""), shop_session.DEFAULT_PROFILE_NAME)
        self.assertEqual(shop_session.slugify_profile_name(None), shop_session.DEFAULT_PROFILE_NAME)


class DisplayLabelTest(unittest.TestCase):
    def test_measured_shop_name_wins_over_everything(self) -> None:
        # 店铺名是登录后从平台读回来的事实，优先级高于任何本地备注。
        self.assertEqual(
            shop_session.display_label("shop-abcd1234", "旧备注", "起了个球球", "155450371"),
            "起了个球球",
        )

    def test_falls_back_to_shop_id_when_platform_gives_no_name(self) -> None:
        self.assertEqual(
            shop_session.display_label("shop-abcd1234", None, None, "155450371"),
            "店铺 155450371",
        )

    def test_never_invents_a_shop_name(self) -> None:
        # 「默认店铺」「待登录」这类名字都不存在：没登录过就不是一家店，
        # 给它安个名字用户会以为自己真有这么一家。
        self.assertEqual(shop_session.display_label("shop-abcd1234"), "")
        self.assertEqual(shop_session.display_label(shop_session.DEFAULT_PROFILE_NAME), "")


class ProfileListingTest(unittest.TestCase):
    def _isolated(self):
        return tempfile.TemporaryDirectory()

    def test_created_accounts_are_listed_without_claiming_logged_in(self) -> None:
        with self._isolated() as tmp_dir:
            old = os.environ.get("DOUYIN_DATA_DIR")
            os.environ["DOUYIN_DATA_DIR"] = tmp_dir
            try:
                self.assertEqual(shop_session.list_profiles(), [], "全新状态不该凭空有店铺")

                slug = shop_session.create_profile()
                account = shop_session.list_profiles()[0]
                self.assertEqual(account["profile_name"], slug)
                self.assertTrue(account["label"].startswith("抖音账户 "))
                self.assertNotEqual(slug, shop_session.DEFAULT_PROFILE_NAME)
                self.assertIsNone(account["shop_id"], "账户备注不能冒充已核实店铺")
                self.assertIsNone(account["shop_name"])
                self.assertEqual(account["identity_source"], "local_account")

                shop_session.observe_identity(slug, "177886360", "拾寻袜子铺")
                listed = shop_session.list_profiles()
                self.assertEqual([p["label"] for p in listed], ["拾寻袜子铺"])
            finally:
                if old is None:
                    os.environ.pop("DOUYIN_DATA_DIR", None)
                else:
                    os.environ["DOUYIN_DATA_DIR"] = old


    def test_container_with_leftover_login_is_not_reused(self) -> None:
        """磁盘上还留着 cookie 的目录不能当空容器交出去。

        2026-09-06 实测事故：点「添加店铺」后打开的浏览器已经登录着原店铺，
        因为被复用的目录里还存着上一次的登录数据。
        """
        with self._isolated() as tmp_dir:
            old = os.environ.get("DOUYIN_DATA_DIR")
            os.environ["DOUYIN_DATA_DIR"] = tmp_dir
            try:
                stale = shop_session.create_profile()
                cookie_path = Path(shop_session.profile_dir(stale)) / "Default" / "Network"
                cookie_path.mkdir(parents=True, exist_ok=True)
                (cookie_path / "Cookies").write_bytes(b"not empty")

                self.assertTrue(shop_session.has_login_data(stale))
                self.assertNotEqual(
                    shop_session.create_profile(), stale, "留着登录数据的目录不该被当成空容器"
                )
            finally:
                if old is None:
                    os.environ.pop("DOUYIN_DATA_DIR", None)
                else:
                    os.environ["DOUYIN_DATA_DIR"] = old

    def test_empty_container_is_reused_instead_of_piling_up(self) -> None:
        with self._isolated() as tmp_dir:
            old = os.environ.get("DOUYIN_DATA_DIR")
            os.environ["DOUYIN_DATA_DIR"] = tmp_dir
            try:
                first = shop_session.create_profile()
                self.assertEqual(shop_session.create_profile(), first, "没登录过的容器该复用")
                shop_session.observe_identity(first, "1", "甲店")
                self.assertNotEqual(shop_session.create_profile(), first)
            finally:
                if old is None:
                    os.environ.pop("DOUYIN_DATA_DIR", None)
                else:
                    os.environ["DOUYIN_DATA_DIR"] = old

    def test_active_shop_can_be_removed_and_active_hands_over(self) -> None:
        """当前账户**可以**删除，删完把 active 交接给另一个仍然存在的账户。

        早先这里断言「当前这家不可移除」，理由写的是「当前这家移除了也会被实测记回来」。
        那个顾虑本身成立（浏览器还开着并登录着时，下一次实测确实会把记录重新登记回来），
        但拿它来禁用删除是错的：「登录错了账户」时，那个错账户恰恰就是当前账户，
        要求先切走等于把人卡死在原地。真正的解法是让删除连浏览器数据目录一起删
        （``purge_directory=True``），而不是藏掉按钮。

        这里同时钉住两件事：① 当前账户可删；② 交接目标是**确实还存在**的账户，
        而不是一个可能根本不在注册表里的默认占位——后者会让下一个
        ``/api/shop/current`` 直接报「当前账户不存在」。
        """

        with self._isolated() as tmp_dir:
            old = os.environ.get("DOUYIN_DATA_DIR")
            os.environ["DOUYIN_DATA_DIR"] = tmp_dir
            try:
                other = shop_session.create_profile()
                shop_session.observe_identity(other, "2", "乙店")
                slug = shop_session.create_profile()
                shop_session.observe_identity(slug, "1", "甲店")
                shop_session.set_active_profile(slug)

                listed = shop_session.list_profiles()
                active_item = next(item for item in listed if item["profile_name"] == slug)
                self.assertTrue(active_item["is_active"])
                self.assertTrue(active_item["removable"], "当前账户必须可删，否则登录错账户时无法纠正")

                self.assertTrue(shop_session.remove_profile(slug))
                registry = shop_session.load_registry()
                self.assertNotIn(slug, registry["profiles"])
                self.assertEqual(
                    shop_session.get_active_profile(),
                    other,
                    "active 必须交接给仍然存在的账户",
                )
            finally:
                if old is None:
                    os.environ.pop("DOUYIN_DATA_DIR", None)
                else:
                    os.environ["DOUYIN_DATA_DIR"] = old

    def test_removing_the_last_account_falls_back_to_default_placeholder(self) -> None:
        """一个都不剩时退回默认占位，而不是留下一个悬空的 active。"""

        with self._isolated() as tmp_dir:
            old = os.environ.get("DOUYIN_DATA_DIR")
            os.environ["DOUYIN_DATA_DIR"] = tmp_dir
            try:
                slug = shop_session.create_profile()
                shop_session.observe_identity(slug, "1", "甲店")
                shop_session.set_active_profile(slug)
                self.assertTrue(shop_session.remove_profile(slug))
                self.assertEqual(
                    shop_session.load_registry()["active_profile"],
                    shop_session.DEFAULT_PROFILE_NAME,
                )
                self.assertEqual(shop_session.load_registry()["profiles"], {})
            finally:
                if old is None:
                    os.environ.pop("DOUYIN_DATA_DIR", None)
                else:
                    os.environ["DOUYIN_DATA_DIR"] = old


class PlatformAccountTest(unittest.TestCase):
    """平台是账户绑定，不能随选择界面、备注或 FXG 观测改变。"""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        environment = patch.dict(os.environ, {"DOUYIN_DATA_DIR": str(self.directory)})
        environment.start()
        self.addCleanup(environment.stop)

    def _write_raw_registry(self, payload) -> Path:
        path = Path(shop_session.registry_path())
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_legacy_account_migrates_to_douyin_without_changing_identity(self) -> None:
        slug = shop_session.DEFAULT_PROFILE_NAME
        path = self._write_raw_registry({
            "active_profile": slug,
            "profiles": {slug: {"label": "旧备注", "shop_id": "123", "shop_name": "实测抖店"}},
        })
        registry = shop_session.load_registry()
        self.assertEqual(registry["profiles"][slug]["platform"], "douyin")
        self.assertEqual(registry["profiles"][slug]["shop_id"], "123")
        listed = shop_session.list_profiles()
        self.assertEqual(listed[0]["platform"], "douyin")
        self.assertEqual(listed[0]["label"], "实测抖店")
        shop_session.set_active_profile(slug)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["profiles"][slug]["platform"], "douyin")

    def test_taobao_does_not_reuse_legacy_default_or_empty_douyin_account(self) -> None:
        douyin = shop_session.create_profile()
        taobao = shop_session.create_profile(platform="taobao")
        self.assertNotEqual(taobao, douyin)
        self.assertNotEqual(taobao, shop_session.DEFAULT_PROFILE_NAME)
        registry = shop_session.load_registry()
        self.assertEqual(registry["profiles"][douyin]["platform"], "douyin")
        self.assertEqual(registry["profiles"][taobao]["platform"], "taobao")
        self.assertEqual(shop_session.create_profile(platform="taobao"), taobao)
        self.assertEqual(shop_session.create_profile(), douyin)

    def test_custom_account_labels_are_not_overwritten_by_add(self) -> None:
        first = shop_session.create_profile(platform="taobao", label="淘宝甲账号")
        second = shop_session.create_profile(platform="taobao", label="淘宝乙账号")
        self.assertNotEqual(first, second)
        self.assertEqual(shop_session.create_profile(platform="taobao", label="淘宝甲账号"), first)
        shop_session.create_profile(platform="taobao")
        registry = shop_session.load_registry()
        self.assertEqual(registry["profiles"][first]["label"], "淘宝甲账号")
        self.assertEqual(registry["profiles"][second]["label"], "淘宝乙账号")

    def test_explicit_label_can_name_unlabelled_account_only(self) -> None:
        first = shop_session.create_profile(platform="taobao")
        self.assertEqual(shop_session.create_profile(platform="taobao", label="用户备注"), first)
        self.assertEqual(shop_session.load_registry()["profiles"][first]["label"], "用户备注")

    def test_taobao_account_is_selectable_without_claiming_verified_identity(self) -> None:
        slug = shop_session.create_profile(platform="taobao")
        shop_session.set_active_profile(slug)
        self.assertEqual(shop_session.get_active_profile(), slug)
        entry = shop_session.list_profiles()[0]
        self.assertEqual(entry["platform"], "taobao")
        self.assertTrue(entry["label"].startswith("淘宝账户 "))
        self.assertEqual(entry["identity_source"], "local_account")
        self.assertIsNone(entry["shop_id"])
        self.assertIsNone(entry["shop_name"])
        self.assertTrue(entry["is_active"])

    def test_platform_is_immutable_and_failure_does_not_modify_registry(self) -> None:
        slug = shop_session.create_profile(platform="taobao", label="淘宝备注")
        path = Path(shop_session.registry_path())
        original = path.read_bytes()
        for operation in (shop_session.ensure_profile, shop_session.set_active_profile):
            with self.subTest(operation=operation.__name__), self.assertRaisesRegex(ValueError, "不可更改"):
                operation(slug, label="不能覆盖", platform="douyin")
            self.assertEqual(path.read_bytes(), original)
        shop_session.ensure_profile(slug)
        self.assertEqual(shop_session.load_registry()["profiles"][slug]["platform"], "taobao")

    def test_default_profile_cannot_be_bound_to_taobao_even_when_unregistered(self) -> None:
        with self.assertRaisesRegex(ValueError, "只能绑定抖店"):
            shop_session.ensure_profile(shop_session.DEFAULT_PROFILE_NAME, platform="taobao")
        self.assertEqual(shop_session.load_registry()["profiles"], {})

    def test_identity_observation_rejects_mismatched_platform_before_any_write(self) -> None:
        """平台不匹配的实测结果必须被拒绝，且一个字节都不许写。

        这条守的是「profile 名字不代表登录了哪个店铺」那条原则的另一面：
        拿抖店的读法去证明淘宝账户的身份（或反过来）会得出错误身份，
        必须报错而不是凑合记下来。

        早先这个测试只针对「淘宝 profile 拒收抖店身份」；现在两个平台都能记录了，
        但**跨平台**拒收的行为必须一模一样——所以断言的是行为，不只是文案。
        """

        slug = shop_session.create_profile(platform="taobao")
        path = Path(shop_session.registry_path())
        original = path.read_bytes()
        for shop_id in ("123", None):
            with self.subTest(shop_id=shop_id), self.assertRaisesRegex(ValueError, "账户平台不匹配"):
                shop_session.observe_identity(slug, shop_id, "错误抖店身份")
            self.assertEqual(path.read_bytes(), original)

    def test_taobao_identity_can_be_recorded_without_cross_platform_leak(self) -> None:
        """淘宝 profile 现在**可以**记录淘宝实测身份——这是本次产品决策的改动点。"""

        slug = shop_session.create_profile(platform="taobao")
        observation = shop_session.observe_identity(slug, "123456789", "猫咪宝贝", platform="taobao")
        self.assertEqual(observation["status"], "new")
        entry = shop_session.load_registry()["profiles"][slug]
        self.assertEqual(entry["platform"], "taobao")
        self.assertEqual(entry["shop_id"], "123456789")
        self.assertEqual(entry["shop_name"], "猫咪宝贝")
        # 记录之后必须真的被判为「已验证」——这正是用户报的「未验证」问题
        listed = next(item for item in shop_session.list_profiles() if item["profile_name"] == slug)
        self.assertEqual(listed["shop_id"], "123456789")
        self.assertEqual(listed["identity_source"], "registry_last_seen")

        # 反向：同一个 profile 再收到抖店观测必须被拒
        with self.assertRaisesRegex(ValueError, "账户平台不匹配"):
            shop_session.observe_identity(slug, "999", "错误抖店身份", platform="douyin")

    def test_taobao_without_identity_still_reports_unverified(self) -> None:
        """没有实测身份时必须仍然是「未验证」——不能因为放宽了规则就默认成已验证。"""

        slug = shop_session.create_profile(platform="taobao")
        listed = next(item for item in shop_session.list_profiles() if item["profile_name"] == slug)
        self.assertIsNone(listed["shop_id"])
        self.assertIsNone(listed["shop_name"])
        self.assertEqual(listed["identity_source"], "local_account")

    def test_invalid_explicit_platform_is_rejected_instead_of_douyin_fallback(self) -> None:
        for value in (None, "", " ", "tmall", "other", True, 1, {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                shop_session.create_profile(platform=value)
        self.assertEqual(shop_session.normalize_platform(" Taobao "), "taobao")
        for value in ("", "other", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                shop_session.ensure_profile("新账户", platform=value)
        self.assertEqual(shop_session.load_registry()["profiles"], {})

    def test_corrupt_or_invalid_registry_is_visible_and_never_replaced(self) -> None:
        variants = [[], {"profiles": []}, {"profiles": {"shop-12345678": []}},
                    {"profiles": {"shop-12345678": {"platform": None}}},
                    {"profiles": {"shop-12345678": {"platform": "other"}}},
                    {"profiles": {shop_session.DEFAULT_PROFILE_NAME: {"platform": "taobao"}}},
                    {"active_profile": None, "profiles": {}}]
        for payload in variants:
            path = self._write_raw_registry(payload)
            original = path.read_bytes()
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                shop_session.create_profile(platform="taobao")
            self.assertEqual(path.read_bytes(), original)
        path.write_text("{invalid-json", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "内容损坏"):
            shop_session.get_active_profile()
        self.assertEqual(path.read_text(encoding="utf-8"), "{invalid-json")

    def test_atomic_save_failure_preserves_old_registry_and_reports_error(self) -> None:
        shop_session.create_profile(platform="taobao", label="既有账号")
        path = Path(shop_session.registry_path())
        original = path.read_bytes()
        with patch("src.shop_session.os.replace", side_effect=OSError("replace blocked")):
            with self.assertRaisesRegex(OSError, "replace blocked"):
                shop_session.create_profile(platform="taobao", label="新账号")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.directory.glob("shop_profiles-*.tmp")), [])

    def test_taobao_container_with_cookie_is_not_reused(self) -> None:
        first = shop_session.create_profile(platform="taobao", label="已有登录")
        directory = Path(shop_session.profile_dir(first)) / "Default" / "Network"
        directory.mkdir(parents=True)
        (directory / "Cookies").write_bytes(b"existing login cookie")
        self.assertNotEqual(shop_session.create_profile(platform="taobao"), first)
        self.assertEqual(shop_session.load_registry()["profiles"][first]["label"], "已有登录")

    def test_both_platform_accounts_remain_selectable_before_login(self) -> None:
        douyin = shop_session.create_profile(label="我的抖音账号")
        taobao = shop_session.create_profile(platform="taobao", label="我的淘宝账号")
        shop_session.set_active_profile(taobao)
        accounts = shop_session.list_profiles()
        self.assertEqual({item["profile_name"] for item in accounts}, {douyin, taobao})
        self.assertTrue(all(item["shop_id"] is None for item in accounts))
        self.assertTrue(all(item["identity_source"] == "local_account" for item in accounts))
        self.assertEqual(accounts[0]["profile_name"], taobao)
        shop_session.set_active_profile(douyin)
        self.assertEqual(shop_session.list_profiles()[0]["label"], "我的抖音账号")

    def test_unreadable_cookie_cannot_be_assumed_to_be_an_empty_account(self) -> None:
        shop_session.create_profile(platform="taobao")
        original_stat = os.stat

        def checked_stat(path, *args, **kwargs):
            if str(path).endswith("Cookies"):
                raise PermissionError("cookie metadata denied")
            return original_stat(path, *args, **kwargs)

        with patch("src.shop_session.os.stat", side_effect=checked_stat):
            with self.assertRaisesRegex(PermissionError, "cookie metadata denied"):
                shop_session.create_profile(platform="taobao")

    def test_first_douyin_account_is_independent_instead_of_fixed_default(self) -> None:
        slug = shop_session.create_profile()
        self.assertRegex(slug, r"^shop-[0-9a-f]{8}$")
        registry = shop_session.load_registry()
        self.assertNotIn(shop_session.DEFAULT_PROFILE_NAME, registry["profiles"])
        self.assertEqual(registry["profiles"][slug]["platform"], "douyin")

    def test_removing_empty_default_preserves_directory_and_active_taobao(self) -> None:
        default = shop_session.DEFAULT_PROFILE_NAME
        shop_session.ensure_profile(default)
        taobao = shop_session.create_profile(platform="taobao", label="我的淘宝账户")
        shop_session.set_active_profile(taobao)
        browser_directory = Path(shop_session.profile_dir(default))
        browser_directory.mkdir(parents=True)
        sentinel = browser_directory / "retained-browser-data.txt"
        sentinel.write_text("原浏览器资料保持不变", encoding="utf-8")
        account = next(item for item in shop_session.list_profiles() if item["profile_name"] == default)
        self.assertTrue(account["removable"])
        self.assertTrue(shop_session.remove_profile(default))
        self.assertEqual(shop_session.get_active_profile(), taobao)
        self.assertNotIn(default, shop_session.load_registry()["profiles"])
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "原浏览器资料保持不变")
        new_douyin = shop_session.create_profile(label="新抖音账户")
        self.assertNotEqual(new_douyin, default)
        self.assertNotIn(default, [item["profile_name"] for item in shop_session.list_profiles()])
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "原浏览器资料保持不变")

    def test_default_with_identity_custom_label_or_history_cannot_be_removed(self) -> None:
        default = shop_session.DEFAULT_PROFILE_NAME
        taobao = shop_session.create_profile(platform="taobao")
        shop_session.set_active_profile(taobao)
        preserved = shop_session.load_registry()
        variants = ({"shop_id": "177886360"}, {"shop_name": "真实店铺"},
                    {"last_seen_at": "2026-10-03T10:00:00"}, {"seen_count": 1},
                    {"history": [{"shop_id": "以前的店铺"}]}, {"label": "我的旧抖音账户"})
        for facts in variants:
            registry = json.loads(json.dumps(preserved, ensure_ascii=False))
            registry["profiles"][default] = {"profile_name": default, "platform": "douyin", **facts}
            shop_session.save_registry(registry)
            path = Path(shop_session.registry_path())
            original = path.read_bytes()
            with self.subTest(facts=facts):
                self.assertFalse(shop_session.is_empty_default_profile(default, registry["profiles"][default]))
                listed = next(item for item in shop_session.list_profiles() if item["profile_name"] == default)
                self.assertFalse(listed["removable"])
                with self.assertRaisesRegex(ValueError, "不能作为空占位"):
                    shop_session.remove_profile(default)
                self.assertEqual(path.read_bytes(), original)
                self.assertIn(default, shop_session.load_registry()["profiles"])

    def test_observed_legacy_default_keeps_name_and_profile_compatibility(self) -> None:
        default = shop_session.DEFAULT_PROFILE_NAME
        shop_session.observe_identity(default, "177886360", "真实旧店铺")
        taobao = shop_session.create_profile(platform="taobao")
        shop_session.set_active_profile(taobao)
        account = next(item for item in shop_session.list_profiles() if item["profile_name"] == default)
        self.assertEqual(account["label"], "真实旧店铺")
        self.assertEqual(account["identity_source"], "registry_last_seen")
        self.assertFalse(account["removable"])
        shop_session.set_active_profile(default)
        self.assertEqual(shop_session.get_active_profile(), default)
        self.assertEqual(Path(shop_session.profile_dir(default)), self.directory / default)

    def test_active_empty_default_placeholder_can_now_be_removed(self) -> None:
        """空默认占位不再是「不可删」——它没有任何身份/备注/历史，删掉是安全的。

        **有历史**的默认账户仍然不能删，那条守卫没动
        （见 ``test_default_with_identity_custom_label_or_history_cannot_be_removed`` 与
        ``test_historical_default_is_not_reused_as_a_new_empty_account``）。
        """

        default = shop_session.DEFAULT_PROFILE_NAME
        shop_session.ensure_profile(default)
        account = shop_session.list_profiles()[0]
        self.assertTrue(account["removable"])
        self.assertTrue(shop_session.remove_profile(default))
        self.assertNotIn(default, shop_session.load_registry()["profiles"])

    def test_default_account_with_history_still_cannot_be_removed(self) -> None:
        """保留真正的那条守卫：有身份/备注/历史的默认账户不能当空占位移除。"""

        default = shop_session.DEFAULT_PROFILE_NAME
        shop_session.ensure_profile(default)
        shop_session.observe_identity(default, "999", "真实旧店铺")
        account = shop_session.list_profiles()[0]
        self.assertFalse(account["removable"])
        with self.assertRaisesRegex(ValueError, "不能作为空占位移除"):
            shop_session.remove_profile(default)
        self.assertIn(default, shop_session.load_registry()["profiles"])

    def test_historical_default_is_not_reused_as_a_new_empty_account(self) -> None:
        default = shop_session.DEFAULT_PROFILE_NAME
        self._write_raw_registry({"active_profile": default, "profiles": {
            default: {"profile_name": default, "seen_count": 1, "history": [{"shop_id": "旧店铺"}]},
        }})
        slug = shop_session.create_profile(label="新账号备注")
        self.assertNotEqual(slug, default)
        old_account = shop_session.load_registry()["profiles"][default]
        self.assertIsNone(old_account.get("label"))
        self.assertEqual(old_account["seen_count"], 1)
        self.assertEqual(old_account["history"], [{"shop_id": "旧店铺"}])

    def test_default_placeholder_helper_and_empty_delete_request_are_explicit(self) -> None:
        default = shop_session.DEFAULT_PROFILE_NAME
        self.assertTrue(shop_session.is_empty_default_profile(default, {
            "shop_id": None, "shop_name": None, "last_seen_at": None,
            "seen_count": 0, "history": [], "label": " ",
        }))
        self.assertFalse(shop_session.is_empty_default_profile("shop-12345678", {}))
        self.assertFalse(shop_session.is_empty_default_profile(default, None))
        for value in ("", " ", None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "非空字符串"):
                shop_session.remove_profile(value)

    def test_other_account_removal_keeps_existing_behavior(self) -> None:
        douyin = shop_session.create_profile(label="普通抖音账户")
        shop_session.observe_identity(douyin, "123", "普通实测店铺")
        taobao = shop_session.create_profile(platform="taobao")
        shop_session.set_active_profile(taobao)
        self.assertTrue(shop_session.remove_profile(douyin))
        self.assertEqual(shop_session.get_active_profile(), taobao)
        self.assertFalse(shop_session.remove_profile(douyin))

class ShopFieldExtractionTest(unittest.TestCase):
    def test_reads_id_and_name_from_wrapped_payload(self) -> None:
        fields = shop_session._extract_shop_fields(
            {"code": 0, "data": {"id": 155450371, "shop_name": "起了个球球"}}
        )
        self.assertEqual(fields["shop_id"], "155450371")
        self.assertEqual(fields["shop_name"], "起了个球球")

    def test_never_invents_a_shop_id(self) -> None:
        # 历史事故：读不到 shop_id 时兜底成测试店铺，把商品提交到了别人店铺。
        for payload in [None, {}, {"code": 1, "msg": "not login"}, [], "html"]:
            fields = shop_session._extract_shop_fields(payload)
            self.assertIsNone(fields["shop_id"], f"{payload!r} 不该产出 shop_id")

    def test_zero_shop_id_is_not_accepted(self) -> None:
        fields = shop_session._extract_shop_fields({"data": {"id": 0, "shop_id": "0"}})
        self.assertIsNone(fields["shop_id"])


class ShopInfoEnvelopeTest(unittest.TestCase):
    """实测响应：{"st":10008,"msg":"账号未登录","code":10008,"data":{},...}（2026-09-06）"""

    @staticmethod
    def _raw(body: dict, status: int = 200) -> str:
        return json.dumps({"status": status, "body": json.dumps(body)})

    def test_envelope_root_is_never_read_as_shop(self) -> None:
        # 信封外层的 id / name 与店铺无关，认错了就是发错店。
        fields = shop_session._extract_shop_fields(
            {"id": 999, "name": "不是店铺", "code": 0, "data": {}}
        )
        self.assertIsNone(fields["shop_id"])
        self.assertIsNone(fields["shop_name"])

    def test_server_logged_out_code_is_recognised(self) -> None:
        self.assertTrue(
            shop_session._server_says_logged_out(self._raw({"st": 10008, "code": 10008, "data": {}}))
        )
        self.assertFalse(
            shop_session._server_says_logged_out(
                self._raw({"code": 0, "data": {"id": 1, "shop_name": "x"}})
            )
        )

    def test_unparsable_response_does_not_override_cookie(self) -> None:
        # 不确定的时候不该推翻 cookie 的结论。
        for raw in [None, "", "not json", json.dumps({"status": 500})]:
            self.assertFalse(shop_session._server_says_logged_out(raw), raw)

    def test_failure_description_lists_data_field_names(self) -> None:
        # 字段名变了要能一次看出来，而不是只知道「没有店铺名」。
        detail = shop_session._describe_shop_info_failure(
            self._raw({"code": 0, "data": {"shopId": 1, "title": "某店"}})
        )
        self.assertIn("shopId", detail)
        self.assertIn("title", detail)


class FreightTemplateTest(unittest.TestCase):
    """实测响应（2026-09-06，起了个球球 / 拾寻袜子铺 两家店各自不同）：

    {"code":0,"st":0,"data":{"count":7,"list":[
        {"id":719533506,"template_name":"中通-满6件包邮","shop_id":177886360,...},
        {"id":0,"template_name":"包邮","shop_id":0,...}
    ]}}
    """

    def test_reads_templates_from_data_list(self) -> None:
        templates = shop_session._extract_freight_templates(
            {
                "code": 0,
                "data": {
                    "count": 2,
                    "list": [
                        {"id": 719533506, "template_name": "中通-满6件包邮", "shop_id": 177886360},
                        {"id": 45971087, "template_name": "中通快递", "shop_id": 177886360},
                    ],
                },
            }
        )
        self.assertEqual([t["name"] for t in templates], ["中通-满6件包邮", "中通快递"])
        self.assertEqual(templates[0]["id"], "719533506")
        self.assertTrue(all(t["shop_scoped"] for t in templates))

    def test_platform_wide_option_is_kept(self) -> None:
        # {id:0, name:"包邮", shop_id:0} 是平台通用项。发布按名字匹配模板，
        # 因为 id 是 0 就丢掉它，用户就选不到这一项了。
        templates = shop_session._extract_freight_templates(
            {"data": {"list": [{"id": 0, "template_name": "包邮", "shop_id": 0}]}}
        )
        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0]["name"], "包邮")
        self.assertFalse(templates[0]["shop_scoped"])
        self.assertIsNone(templates[0]["shop_id"])

    def test_never_invents_a_template(self) -> None:
        # 编一个不存在的模板名出来，发布要么失败，要么按别的运费规则发货。
        for payload in [None, {}, {"data": {}}, {"data": {"list": []}}, {"data": {"list": [{}]}}]:
            self.assertEqual(shop_session._extract_freight_templates(payload), [], repr(payload))

    def test_entries_without_a_name_are_dropped(self) -> None:
        templates = shop_session._extract_freight_templates(
            {"data": {"list": [{"id": 1, "template_name": "   "}, {"id": 2, "template_name": "甲"}]}}
        )
        self.assertEqual([t["name"] for t in templates], ["甲"])

    def test_duplicate_names_collapse(self) -> None:
        templates = shop_session._extract_freight_templates(
            {"data": {"list": [{"id": 1, "template_name": "包邮"}, {"id": 2, "template_name": "包邮"}]}}
        )
        self.assertEqual(len(templates), 1)


class BrowserFilterTest(unittest.TestCase):
    """多店铺并存时，复用不能跨店。这是最容易静默发错店的一段逻辑。"""

    KNOWN = ["upload-browser-profile", "shop-aaaaaaaa", "shop-bbbbbbbb"]

    def _browsers(self):
        return [
            {"debug_address": "127.0.0.1:9101", "user_data_dir": r"C:\runtime\shop-aaaaaaaa"},
            {"debug_address": "127.0.0.1:9102", "user_data_dir": r"C:\runtime\shop-bbbbbbbb"},
            {
                "debug_address": "127.0.0.1:9103",
                "user_data_dir": r"C:\runtime\upload-browser-profile",
            },
            {"debug_address": "127.0.0.1:9104", "user_data_dir": r"C:\.runtime\chrome-fxg-cdp"},
        ]

    def _addresses(self, kept):
        return {item["debug_address"] for item in kept}

    def test_other_shops_are_excluded(self) -> None:
        kept = shop_session.filter_browsers_for_profile(
            self._browsers(), "shop-aaaaaaaa", self.KNOWN
        )
        addresses = self._addresses(kept)
        self.assertIn("127.0.0.1:9101", addresses)
        self.assertNotIn("127.0.0.1:9102", addresses)
        self.assertNotIn("127.0.0.1:9103", addresses)

    def test_default_profile_cannot_grab_another_shop_browser(self) -> None:
        # 过滤必须双向：历史遗留那份容器同样不能反过来抢别人的浏览器。
        kept = shop_session.filter_browsers_for_profile(
            self._browsers(), shop_session.DEFAULT_PROFILE_NAME, self.KNOWN
        )
        addresses = self._addresses(kept)
        self.assertIn("127.0.0.1:9103", addresses)
        self.assertNotIn("127.0.0.1:9101", addresses)
        self.assertNotIn("127.0.0.1:9102", addresses)

    def test_unowned_browser_is_still_allowed(self) -> None:
        # 协议探针那个独立目录不归属任何一家店，谈不上串店，保持历史行为放行。
        for active in ["shop-aaaaaaaa", shop_session.DEFAULT_PROFILE_NAME]:
            kept = shop_session.filter_browsers_for_profile(self._browsers(), active, self.KNOWN)
            self.assertIn("127.0.0.1:9104", self._addresses(kept), active)


class OwningProfileTest(unittest.TestCase):
    """实测结果必须记到「它来自哪个 profile」，不是「当前选中哪个」。"""

    def test_recognises_our_own_profile_dirs(self) -> None:
        base = shop_session.profiles_base_dir()
        self.assertEqual(
            shop_session.owning_profile_of(os.path.join(base, "shop-19fe7c8a")), "shop-19fe7c8a"
        )
        self.assertEqual(
            shop_session.owning_profile_of(os.path.join(base, shop_session.DEFAULT_PROFILE_NAME)),
            shop_session.DEFAULT_PROFILE_NAME,
        )

    def test_foreign_dirs_are_not_attributed(self) -> None:
        # 不归属任何店铺的浏览器（协议探针那种）不该往注册表里写东西。
        base = shop_session.profiles_base_dir()
        for path in [
            r"C:\Users\x\.runtime\chrome-fxg-cdp",
            os.path.join(base, "shop-abc", "Default"),
            "",
            None,
        ]:
            self.assertIsNone(shop_session.owning_profile_of(path), path)


class ReadShopIdentityTest(unittest.TestCase):
    def test_unreachable_port_reports_unreachable_without_shop_id(self) -> None:
        # 端口 1 上不会有 CDP 服务，用它验证「连不上」分支不产出任何店铺身份。
        result = shop_session.read_shop_identity("127.0.0.1:1", timeout=1.0)
        self.assertEqual(result["status"], "unreachable")
        self.assertIsNone(result["shop_id"])
        self.assertIsNone(result["shop_name"])


class ReadTaobaoIdentityTest(unittest.TestCase):
    """淘宝身份读取。

    不连真实浏览器（那些用例需要登录态，跑不了）；这里覆盖**纯函数**与
    「连不上」分支，保证不猜、不兜底。
    """

    def test_unreachable_port_reports_unreachable_without_identity(self) -> None:
        result = shop_session.read_taobao_identity("127.0.0.1:1", timeout=1.0)
        self.assertEqual(result["status"], "unreachable")
        self.assertIsNone(result["shop_id"])
        self.assertIsNone(result["shop_name"])
        self.assertIsNone(result["nick"])
        self.assertEqual(result["platform"], "taobao")

    def test_read_account_identity_dispatches_by_platform(self) -> None:
        taobao = shop_session.read_account_identity("127.0.0.1:1", platform="taobao", timeout=1.0)
        douyin = shop_session.read_account_identity("127.0.0.1:1", platform="douyin", timeout=1.0)
        # 淘宝分支带 platform 字段，抖店分支不带——用它区分走了哪条路
        self.assertEqual(taobao.get("platform"), "taobao")
        self.assertNotIn("platform", douyin)
        self.assertEqual(taobao["status"], "unreachable")
        self.assertEqual(douyin["status"], "unreachable")

    def test_pick_target_prefers_seller_page_over_login_page(self) -> None:
        login = {"type": "page", "url": "https://login.taobao.com/member/login.jhtml", "webSocketDebuggerUrl": "ws://x"}
        publish = {"type": "page", "url": "https://item.upload.taobao.com/sell/v2/publish.htm?catId=1", "webSocketDebuggerUrl": "ws://y"}
        picked = shop_session._pick_taobao_target([login, publish])
        self.assertIn("item.upload.taobao.com", picked["url"])

    def test_pick_target_accepts_login_page_when_that_is_all_there_is(self) -> None:
        """停在登录页也要能被选中，否则「停在登录页」与「根本没有淘宝页」会混成一个状态。"""

        login = {"type": "page", "url": "https://login.taobao.com/member/login.jhtml", "webSocketDebuggerUrl": "ws://x"}
        picked = shop_session._pick_taobao_target([login])
        self.assertIsNotNone(picked)
        self.assertIn("login.taobao.com", picked["url"])

    def test_pick_target_ignores_non_taobao_and_non_page_targets(self) -> None:
        targets = [
            {"type": "page", "url": "https://fxg.jinritemai.com/ffa/mshop/homepage/index", "webSocketDebuggerUrl": "ws://a"},
            {"type": "page", "url": "https://www.baidu.com", "webSocketDebuggerUrl": "ws://b"},
            {"type": "iframe", "url": "https://item.taobao.com/item.htm?id=1", "webSocketDebuggerUrl": "ws://c"},
            {"type": "page", "url": "devtools://devtools/bundled/inspector.html", "webSocketDebuggerUrl": "ws://d"},
        ]
        self.assertIsNone(shop_session._pick_taobao_target(targets))

    def test_pick_target_accepts_tmall_pages(self) -> None:
        tmall = {"type": "page", "url": "https://item.upload.tmall.com/router/publish.htm", "webSocketDebuggerUrl": "ws://x"}
        self.assertIsNotNone(shop_session._pick_taobao_target([tmall]))


class TaobaoCookieExtractionTest(unittest.TestCase):
    def test_returns_first_non_empty_value_by_priority(self) -> None:
        cookies = [
            {"name": "_nk_", "value": "昵称"},
            {"name": "tracknick", "value": ""},
        ]
        self.assertEqual(shop_session._taobao_cookie_value(cookies, ("tracknick", "_nk_")), "昵称")

    def test_returns_none_when_absent_or_blank(self) -> None:
        for cookies in ([], [{"name": "unb", "value": ""}], [{"name": "unb", "value": "   "}], [{"name": "other", "value": "x"}]):
            self.assertIsNone(shop_session._taobao_cookie_value(cookies, ("unb",)))


class TaobaoFreightTemplateTest(unittest.TestCase):
    def test_reports_need_publish_page_instead_of_an_empty_list(self) -> None:
        """淘宝改走 **DOM** 之后，不再是 `not_captured`。

        模板下拉只在**发布表单**里，所以没有发布页时应如实报 `need_publish_page`——
        而**绝不能**返回空列表冒充「该店铺没有模板」。

        （原用例断言的是 `not_captured`，那是「等协议接口」时代的行为。）
        """

        import src.shop_session as shop_session

        # 连不上调试浏览器 → 如实报，不编模板
        result = shop_session.read_taobao_freight_templates("127.0.0.1:1", timeout=0.5)
        self.assertIn(result["status"],
                      {"no_browser", "unavailable", "read_failed", "need_publish_page"})
        self.assertNotEqual(result["status"], "ok")
        self.assertEqual(result["templates"], [])
        self.assertTrue(result.get("error"), "必须带错误说明，不能只给空列表")


class PurgeProfileDirectoryTest(unittest.TestCase):
    """彻底删除：记录 + 浏览器登录资料一起删。

    这是用户明确要的语义——「删除的本质就完全移除它，下次添加再登录就能正常切到店铺」。
    早先 ``remove_profile`` 只摘记录、保留目录，登录态留在磁盘上。
    """

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        environment = patch.dict(os.environ, {"DOUYIN_DATA_DIR": str(self.directory)})
        environment.start()
        self.addCleanup(environment.stop)

    def _make_profile_with_directory(self, marker: str = "cookie") -> str:
        slug = shop_session.create_profile()
        profile_path = Path(shop_session.profile_dir(slug))
        (profile_path / "Default").mkdir(parents=True, exist_ok=True)
        (profile_path / "Default" / "Cookies").write_text(marker, encoding="utf-8")
        return slug

    def test_forget_without_purge_keeps_the_login_data(self) -> None:
        slug = self._make_profile_with_directory()
        self.assertTrue(shop_session.remove_profile(slug))
        self.assertTrue(Path(shop_session.profile_dir(slug)).is_dir(), "不 purge 时目录必须保留")

    def test_purge_removes_record_and_directory(self) -> None:
        slug = self._make_profile_with_directory("登录态")
        self.assertTrue(shop_session.remove_profile(slug, purge_directory=True))
        self.assertNotIn(slug, shop_session.load_registry()["profiles"])
        self.assertFalse(Path(shop_session.profile_dir(slug)).exists(), "purge 必须连目录一起删")

    def test_purge_without_an_existing_directory_still_removes_the_record(self) -> None:
        slug = shop_session.create_profile()  # 目录从未创建
        self.assertTrue(shop_session.remove_profile(slug, purge_directory=True))
        self.assertNotIn(slug, shop_session.load_registry()["profiles"])

    def test_purge_leaves_no_staging_directory_behind(self) -> None:
        """改名用的临时目录不能留在磁盘上。"""

        slug = self._make_profile_with_directory()
        shop_session.remove_profile(slug, purge_directory=True)
        leftovers = [p.name for p in self.directory.iterdir() if p.name.startswith(".purge-")]
        self.assertEqual(leftovers, [], "残留了改名用的临时目录")

    def test_purge_refuses_to_touch_foreign_paths(self) -> None:
        """路径安全：只允许删账户目录根下正下方的同名目录。"""

        outsider = self.directory / "not-a-profile"
        outsider.mkdir()
        with self.assertRaises(ValueError):
            shop_session._purge_profile_directory("..")
        with self.assertRaises(ValueError):
            shop_session._purge_profile_directory("../not-a-profile")
        self.assertTrue(outsider.is_dir(), "越界路径必须原封不动")

    def test_purge_of_a_missing_directory_reports_false(self) -> None:
        self.assertFalse(shop_session._purge_profile_directory("never-created-12345678"))

    def test_purge_failure_does_not_remove_the_record(self) -> None:
        """目录删不掉时整体失败——不能出现「记录没了但登录资料还在」。"""

        slug = self._make_profile_with_directory()
        with patch.object(shop_session, "_purge_profile_directory", side_effect=ValueError("占用")):
            with self.assertRaises(ValueError):
                shop_session.remove_profile(slug, purge_directory=True)
        self.assertIn(slug, shop_session.load_registry()["profiles"])
        self.assertTrue(Path(shop_session.profile_dir(slug)).is_dir())


class TaobaoShopInfoTest(unittest.TestCase):
    """淘宝店铺信息接口（观察得来，不是猜的）。

    接口名与请求形态来自 CDP 观察发布工作台自身的请求，见
    ``taobao-publisher/tmp/review/capture_shop_info_api.py``。这里用 mock
    覆盖解析与失败分支，**不联网**。
    """

    def test_sign_matches_the_documented_algorithm(self) -> None:
        # md5("<token>&<t>&<appKey>&<data>")
        expected = hashlib.md5("tok&1700000000000&12574478&{}".encode("utf-8")).hexdigest()
        self.assertEqual(
            shop_session._mtop_sign("tok", "1700000000000", "12574478", "{}"), expected
        )

    def test_app_key_and_jsv_match_the_subproject_constants(self) -> None:
        """两侧常量必须一致——不一致会导致签名被拒，且很难查。"""

        self.assertEqual(shop_session.TAOBAO_MTOP_APP_KEY, "12574478")
        self.assertEqual(shop_session.TAOBAO_MTOP_JSV, "2.6.1")

    def test_unreachable_port_reports_unreachable(self) -> None:
        result = shop_session.read_taobao_shop_info("127.0.0.1:1", timeout=1.0)
        self.assertEqual(result["status"], "unreachable")
        self.assertIsNone(result["shop_id"])
        self.assertIsNone(result["shop_name"])

    def test_clean_text_never_returns_blank(self) -> None:
        for value in (None, "", "   "):
            self.assertIsNone(shop_session._clean_text(value))
        self.assertEqual(shop_session._clean_text(" 猫咪 "), "猫咪")

    def _response(self, payload_text: str, status_code: int = 200):
        response = mock.Mock()
        response.text = payload_text
        response.status_code = status_code
        return response

    def test_call_parses_a_successful_body(self) -> None:
        body = {"ret": ["SUCCESS::调用成功"], "data": {"result": {"shopId": 187760698}}}
        with mock.patch("requests.get", return_value=self._response(json.dumps(body))):
            result = shop_session._call_taobao_shop_info(
                [{"name": "unb", "value": "1", "domain": ".taobao.com"}], "tok", 5.0
            )
        self.assertEqual(result["body"]["ret"], ["SUCCESS::调用成功"])

    def test_call_reports_token_expiry_without_echoing_the_url(self) -> None:
        """token 失效要单独识别；异常文本里不能回显带 sign 的完整 URL。"""

        with mock.patch(
            "requests.get",
            return_value=self._response('{"ret":["FAIL_SYS_TOKEN_EXOIRED::令牌过期"]}'),
        ):
            result = shop_session._call_taobao_shop_info([], "tok", 5.0)
        self.assertEqual(result["status"], "auth_failed")
        self.assertIn("FAIL_SYS_TOKEN_EXOIRED", result["detail"])
        self.assertNotIn("sign=", result["detail"])

    def test_call_reports_a_non_json_response_without_dumping_it(self) -> None:
        with mock.patch("requests.get", return_value=self._response("<html>登录</html>", 200)):
            result = shop_session._call_taobao_shop_info([], "tok", 5.0)
        self.assertIn("不是 JSON", result["error"])
        self.assertNotIn("html", result["detail"])

    def test_call_does_not_leak_the_cookie_header_on_failure(self) -> None:
        """异常分支最危险：requests 的异常文本常带完整 URL。"""

        with mock.patch("requests.get", side_effect=OSError("boom https://h5api.m.taobao.com/?sign=deadbeef")):
            result = shop_session._call_taobao_shop_info([], "tok", 5.0)
        self.assertNotIn("sign=", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("deadbeef", json.dumps(result, ensure_ascii=False))

    def test_account_id_and_shop_id_are_recorded_separately(self) -> None:
        """淘宝上「谁登录的」和「哪家店」是两个字段，不能混。"""

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"DOUYIN_DATA_DIR": tmp}):
                slug = shop_session.create_profile(platform="taobao")
                shop_session.observe_identity(
                    slug, "187760698", "猫咪宝贝袜子铺", platform="taobao", account_id="2223179290236"
                )
                entry = shop_session.load_registry()["profiles"][slug]
                self.assertEqual(entry["shop_id"], "187760698")
                self.assertEqual(entry["account_id"], "2223179290236")
                self.assertEqual(entry["shop_name"], "猫咪宝贝袜子铺")

    def test_account_only_profile_still_counts_as_verified_login(self) -> None:
        """只读到账户、没读到店铺时：算已验证登录，但不得凭空造店铺身份。"""

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"DOUYIN_DATA_DIR": tmp}):
                slug = shop_session.create_profile(platform="taobao")
                shop_session.observe_identity(
                    slug, None, None, platform="taobao", account_id="2223179290236"
                )
                listed = next(i for i in shop_session.list_profiles() if i["profile_name"] == slug)
                self.assertEqual(listed["identity_source"], "registry_last_seen")
                self.assertIsNone(listed["shop_id"], "账户 ID 不得被当成店铺 ID")
                self.assertIsNone(listed["shop_name"])
                self.assertEqual(listed["account_id"], "2223179290236")

    def test_nothing_at_all_is_still_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"DOUYIN_DATA_DIR": tmp}):
                slug = shop_session.create_profile(platform="taobao")
                observation = shop_session.observe_identity(slug, None, None, platform="taobao")
                self.assertEqual(observation["status"], "unknown")
                self.assertIsNone(shop_session.load_registry()["profiles"][slug]["shop_id"])


class RegistryPathTest(unittest.TestCase):
    def test_registry_sits_next_to_profile_dirs(self) -> None:
        # 注册表记的就是这些目录的实测身份，分开放会产生「记录还在、目录没了」的错配。
        base = Path(shop_session.profiles_base_dir())
        self.assertEqual(Path(shop_session.registry_path()).parent, base)
        self.assertEqual(
            Path(shop_session.profile_dir(shop_session.DEFAULT_PROFILE_NAME)),
            base / shop_session.DEFAULT_PROFILE_NAME,
        )


if __name__ == "__main__":
    unittest.main()

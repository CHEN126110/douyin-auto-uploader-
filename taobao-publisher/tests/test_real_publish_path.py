# -*- coding: utf-8 -*-
"""「真实发布」路径的守卫测试。

## 缺口是什么

抖店有 `realPublish` 路径（模式选择 + 显式确认 + `confirmFinalPublish: true`），
**淘宝面板一样都没有**——写死了 `dryRun: true, stopBeforeSubmit: true`。
而 Sidecar 照请求里的 `dry_run` / `stop_before_submit` 走，
所以**界面永远不可能真正写入平台**。

## 三把锁

| 锁 | 在哪 |
|---|---|
| 界面模式 | 默认「校对模式」 |
| 显式确认 | 每次真实发布弹确认框 |
| Sidecar 环境变量 | `TAOBAO_UPLOAD_ALLOW_WRITE` / `..._ALLOW_SUBMIT=1` |

**只开前两把不会有任何写入**——授权开关在服务端。

这些用例钉住的是**默认值与三把锁的存在**，不是"能不能发布"。
"""

from __future__ import annotations

import pathlib
import re
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from frontend_source_helper import code_only  # noqa: E402

TAURI = REPO_ROOT / "tauri-app"
API = TAURI / "src" / "services" / "api.ts"
PANEL = TAURI / "src" / "components" / "TaobaoPublishPanel.vue"




class ApiRealPublishTest(unittest.TestCase):
    def setUp(self) -> None:
        self.code = code_only(API.read_text(encoding="utf-8"))

    def test_accepts_real_publish_option(self) -> None:
        self.assertIn("realPublish?: boolean;", self.code)

    def test_real_publish_flips_both_fields(self) -> None:
        """**两个字段要一起翻**——少一个都到不了提交。"""

        self.assertIn("dry_run: realPublish ? false : (options.dryRun ?? true)", self.code)
        self.assertIn(
            "stop_before_submit: realPublish ? false : (options.stopBeforeSubmit ?? true)",
            self.code)

    def test_default_is_still_dry_run(self) -> None:
        """**零写入默认的红线不动。**"""

        self.assertIn("options.dryRun ?? true", self.code)
        self.assertIn("options.stopBeforeSubmit ?? true", self.code)

    def test_real_publish_requires_explicit_true(self) -> None:
        """`realPublish` 必须**严格等于 true**——字符串 "false" 会被当成真。"""

        self.assertIn("options.realPublish === true", self.code)
        self.assertNotIn("if (options.realPublish)", self.code)


class PanelRealPublishTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = PANEL.read_text(encoding="utf-8")
        self.code = code_only(self.source)

    def test_mode_defaults_to_dry_run(self) -> None:
        match = re.search(r'publishMode\s*=\s*ref<"dry_run"\s*\|\s*"real">\((\"[a-z_]+\")\)',
                          self.code)
        self.assertIsNotNone(match, "找不到 publishMode 的声明")
        self.assertEqual(match.group(1), '"dry_run"', "默认必须是校对模式")

    def test_mode_selector_exists_in_template(self) -> None:
        self.assertIn('v-model="publishMode"', self.source)
        self.assertIn('value="real"', self.source)
        self.assertIn('value="dry_run"', self.source)

    def test_real_publish_always_confirms(self) -> None:
        """真实发布**每次都弹确认**——防手滑。"""

        self.assertIn('publishMode.value === "real"', self.code)
        self.assertIn("await confirmRealPublish()", self.code)
        # 取消确认后必须**不发请求**
        confirm_index = self.code.index("await confirmRealPublish()")
        after = self.code[confirm_index:confirm_index + 260]
        self.assertIn("return", after, "取消确认后必须直接返回")

    def test_confirmation_mentions_the_shop_and_irreversibility(self) -> None:
        match = re.search(r"async function confirmRealPublish\(\).*?\n}", self.source, re.S)
        self.assertIsNotNone(match, "找不到 confirmRealPublish")
        body = match.group(0)
        self.assertIn("无法撤销", body)
        self.assertIn("将发布到", body, "要说清发到哪个店")

    def test_confirmation_says_server_side_authorization_is_also_needed(self) -> None:
        """**别让人以为在界面上点两下就能写平台。**"""

        match = re.search(r"async function confirmRealPublish\(\).*?\n}", self.source, re.S)
        body = match.group(0)
        self.assertIn("Sidecar", body)
        self.assertIn("不会写入平台", body)

    def test_request_carries_real_publish(self) -> None:
        self.assertIn("realPublish,", self.code)
        self.assertNotIn("dryRun: true,", self.code,
                         "写死的 dryRun: true 会让真实发布永远到不了平台")

    def test_copy_is_mode_aware(self) -> None:
        self.assertIn("真实写入", self.source)
        self.assertIn("dry-run，不会写入平台", self.source)


class ModeAwareCopyTest(unittest.TestCase):
    """文案要跟着模式走——**说「校对」就得真的是校对。**

    一个写着「开始校对（dry-run）」的按钮，如果实际会写入平台，
    那比没有文案更糟：它让人以为自己是安全的。
    """

    def setUp(self) -> None:
        self.source = PANEL.read_text(encoding="utf-8")

    def test_does_not_claim_the_mode_is_fixed(self) -> None:
        self.assertNotIn("当前固定为", self.source,
                         "模式已经不固定了——界面提供了开关")

    def test_does_not_claim_there_is_no_switch(self) -> None:
        """⚠️ **这句在加了开关之后就成了假话。**"""

        self.assertNotIn("界面不提供开关", self.source,
                         "界面现在提供开关，不能再说没有")

    def test_button_label_follows_the_mode(self) -> None:
        match = re.search(r">\{\{[^}]*publishMode[^}]*\}\}</el-button>", self.source)
        self.assertIsNotNone(match, "按钮标签要按 publishMode 区分")
        label = match.group(0)
        self.assertIn("真实发布", label)
        self.assertIn("开始校对", label)

    def test_real_publish_button_is_not_primary(self) -> None:
        """真实发布的按钮**不该**长得像安全操作。"""

        self.assertIn("publishMode === 'real' ? 'danger' : 'primary'", self.source)

    def test_description_is_mode_aware(self) -> None:
        self.assertIn("v-if=\"publishMode === 'dry_run'\"", self.source)
        self.assertIn("v-else", self.source)

    def test_real_publish_description_names_the_env_locks(self) -> None:
        """选了真实发布就要说明**服务端还有锁**，别让人以为点两下就写进去了。"""

        match = re.search(r'<p v-else class="field-hint publish-mode-warning">(.*?)</p>',
                          self.source, re.S)
        self.assertIsNotNone(match, "找不到真实发布的说明段")
        body = match.group(1)
        for name in ("TAOBAO_UPLOAD_ALLOW_WRITE", "TAOBAO_UPLOAD_ALLOW_SUBMIT"):
            self.assertIn(name, body)
        self.assertIn("不会写入平台", body)

    def test_dry_run_description_says_nothing_is_written(self) -> None:
        match = re.search(
            r'<p v-if="publishMode === \'dry_run\'" class="field-hint">(.*?)</p>',
            self.source, re.S)
        self.assertIsNotNone(match, "找不到校对模式的说明段")
        self.assertIn("都会被跳过", match.group(1))


class ServerSideLockStillDocumentedTest(unittest.TestCase):
    def test_api_docstring_names_both_env_locks(self) -> None:
        source = API.read_text(encoding="utf-8")
        for name in ("TAOBAO_UPLOAD_ALLOW_WRITE", "TAOBAO_UPLOAD_ALLOW_SUBMIT"):
            self.assertIn(name, source, "接口注释要写明服务端还有一把锁：" + name)


if __name__ == "__main__":
    unittest.main()

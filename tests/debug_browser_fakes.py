# -*- coding: utf-8 -*-
"""调试浏览器测试共用的假件：假标签页 / 假元素 / 假页面 / 假浏览器端口，以及可控的时钟。

和 ``sidecar_test_support.py`` 一样放在 tests/ 下，不属于任何一个测试文件。只模拟 DrissionPage 被
``BrowserDebugService`` 实际用到的那一小块接口（``eles`` / ``run_js`` / ``get`` / ``get_screenshot`` / ``html`` ……），
所有「坏掉的浏览器」都由 ``World.flags`` 里的开关控制，不依赖真实 Chrome。
"""

from __future__ import annotations

import os
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.sidecar.debug_browser_service import BrowserDebugService, DebugBrowserPort  # noqa: E402

DEFAULT_URL = "https://fxg.jinritemai.com/ffa/g/create"


class BrokenStates:
    @property
    def is_displayed(self):
        raise RuntimeError("状态不可用")


class FakeElement:
    """quirky=True 的元素：每一种读取都会抛错，用来验证摘要 / 过滤对坏元素的降级。"""

    def __init__(self, world, locator, index, text, displayed=True, tag="div", fail_on=(), quirky=False):
        self.world, self.locator, self.index = world, locator, index
        self._text, self._tag, self._quirky = text, tag, quirky
        self._fail_on = set(fail_on)
        self.states = BrokenStates() if quirky else types.SimpleNamespace(is_displayed=displayed)
        self.scroll = types.SimpleNamespace(to_center=lambda: self._log("scroll.to_center"))

    @property
    def text(self):
        if self._quirky:
            raise RuntimeError("文本不可读")
        return self._text

    def _log(self, *entry):
        self.world.calls.append(["element", self.locator, self.index, *entry])

    def _maybe_fail(self, what):
        if what in self._fail_on:
            raise RuntimeError("元素操作失败: %s" % what)

    def run_js(self, script):
        if self._quirky:
            raise RuntimeError("脚本不可用")
        if "tagName" in script:
            return self._tag
        if "outerHTML" in script:
            return '<%s class="x">%s</%s>' % (self._tag, self._text, self._tag)
        return None

    def attr(self, name):
        if self._quirky:
            raise RuntimeError("属性不可读")
        return {"id": "el-%d" % self.index, "class": "cls", "attr-field-id": "field-%d" % self.index,
                "value": "v%d" % self.index, "placeholder": "p"}.get(name)

    def click(self, by_js=False):
        self._maybe_fail("click")
        self._log("click", by_js)

    def hover(self):
        self._maybe_fail("hover")
        self._log("hover")

    def clear(self, by_js=False):
        self._maybe_fail("clear")
        self._log("clear", by_js)

    def input(self, value, clear=True):
        self._maybe_fail("input")
        self._log("input", value, clear)


class FakeTab:
    def __init__(self, world, address):
        self.world, self.address = world, address
        self._url, self._title = DEFAULT_URL, "抖店-发布商品"
        self.ready_state = "complete"

    @property
    def url(self):
        if self.world.flags.get("url_fail"):
            raise RuntimeError("地址不可读")
        return self._url

    @property
    def title(self):
        if self.world.flags.get("title_fail"):
            raise RuntimeError("标题不可读")
        return self._title

    @property
    def html(self):
        if self.world.flags.get("html_fail"):
            raise RuntimeError("读取 html 失败")
        return "<html><body>fake page %s</body></html>" % self.address

    def run_js(self, script):
        if self.world.flags.get("snapshot_fail"):
            raise RuntimeError("页面脚本执行失败")
        if "maxFields" in script:
            return {
                "url": self._url, "title": self._title, "ready_state": self.ready_state,
                "scroll": {"x": 0, "y": 12},
                "field_items": [{"index": 0, "field_id": "商品标题", "text": "标题"}],
                "control_items": [{"index": 0, "tag": "button", "type": "", "text": "保存", "value": "",
                                   "attr_field_id": ""}],
                "overlay_items": [], "upload_signals": {"upload_busy": False},
            }
        if "document.readyState" in script:
            return self.ready_state
        return None

    def eles(self, locator, timeout=1.0):
        self.world.calls.append(["eles", locator, timeout])
        if "boom" in locator:
            raise RuntimeError("定位器炸了")
        if "none" in locator:
            return []
        if "quirky" in locator:
            return [FakeElement(self.world, locator, 0, "", quirky=True)]
        if "long" in locator:
            return [FakeElement(self.world, locator, 0, "长" * 400)]
        if "hidden" in locator:
            return [FakeElement(self.world, locator, 0, "隐藏的", displayed=False)]
        fail_on = ("click", "input") if "fail" in locator else ()
        return [FakeElement(self.world, locator, 0, "第一个", fail_on=fail_on),
                FakeElement(self.world, locator, 1, "第二个", displayed=False, tag="span")]

    def get(self, url):
        self.world.calls.append(["tab.get", url])
        self._url = url

    def get_screenshot(self, path=None, name=None, full_page=False):
        if self.world.flags.get("screenshot_fail"):
            raise RuntimeError("截图失败")
        with open(os.path.join(path, name), "wb") as fp:
            fp.write(b"\x89PNG fake screenshot")


class FakePage:
    def __init__(self, world, address):
        self.world, self.address = world, address
        self.latest_tab = "tab-1"
        self._tab = FakeTab(world, address)

    @property
    def browser(self):
        if self.world.flags.get("broken_browser"):
            raise RuntimeError("浏览器对象已失效")
        return types.SimpleNamespace(address=self.address)

    def get_tab(self, ident):
        if self.world.flags.pop("tab_fail_once", False):
            raise RuntimeError("标签页刚被关闭")
        if self.world.flags.get("tab_fail"):
            raise RuntimeError("标签页已关闭")
        return self._tab


class FakeProcess:
    pid = 4321

    def __init__(self, world):
        self.world, self.returncode = world, None

    def poll(self):
        code = self.world.flags.get("proc_exit")
        if code is not None:
            self.returncode = code
        return code

    def kill(self):
        self.world.calls.append(["proc.kill"])
        if self.world.flags.get("kill_fail"):
            raise RuntimeError("杀进程失败")


class FakeClock:
    """虚拟时钟：``sleep`` 只推进时间，不真等；超时类用例瞬间跑完。

    ``sleep`` 次数有上限：被测的等待循环如果不推进时间（例如间隔被改成 0），在虚拟时钟下会死循环，
    这里直接抛 ``AssertionError`` 让测试失败，而不是把整个测试进程挂住。
    """

    MAX_SLEEPS = 20000

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        if len(self.sleeps) > self.MAX_SLEEPS:
            raise AssertionError("等待循环没有推进时间（疑似死循环）")
        self.now += seconds


class TickingDatetime(datetime):
    """每次 ``now()`` 前进（或后退）一秒，让会话 id / 创建时间可预测且互不相同。"""

    step = 1
    counter = 0

    @classmethod
    def now(cls, tz=None):
        cls.counter += 1
        return datetime(2026, 10, 19, 8, 0, 0) + timedelta(seconds=cls.step * cls.counter)

    @classmethod
    def reset(cls, step=1):
        cls.step, cls.counter = step, 0


def normalize_address(value):
    return str(value or "").strip().replace("http://", "").rstrip("/")


class World:
    """一个测试里的假外部世界：浏览器端口各能力 + 状态开关 + 调用记录。"""

    def __init__(self, root):
        self.root = Path(root)
        self.flags = {}
        self.calls = []
        self.gui = types.SimpleNamespace(page=None)
        self.browsers = []                 # discover_browsers 的返回
        self.open_ports = set()            # verify_browser 判定为可连的端口
        self.free_ports = set()            # is_port_available 判定为空闲的端口
        self.chrome = None
        self.profile = "shop-aaaaaaaa"
        self.page_address = "127.0.0.1:9333"
        self.open_error = None
        self.attach_error = None
        self.verify_error = None
        self.ready_after_popen = False
        self.popen_started = False

    # ---- 端口
    def open_page(self, url, profile_name=None, **kwargs):
        self.calls.append(["get_page", url, profile_name])
        if self.open_error is not None:
            raise self.open_error
        return FakePage(self, self.page_address)

    def attach(self, address, existing_only=False):
        self.calls.append(["attach", address, existing_only])
        if self.attach_error is not None:
            raise self.attach_error
        return FakePage(self, address)

    def discover(self, verify=False):
        self.calls.append(["discover", verify])
        return [dict(item) for item in self.browsers]

    def verify(self, address, timeout=2.0):
        self.calls.append(["verify", address, timeout])
        port = int(address.rsplit(":", 1)[-1])
        if port in self.open_ports or (self.ready_after_popen and self.popen_started):
            return {"ok": True, "address": address}
        if self.verify_error:
            return {"ok": False, "error": self.verify_error}
        return {"ok": False}

    def chrome_path(self):
        self.calls.append(["chrome_path"])
        return self.chrome

    def port_free(self, host, port):
        self.calls.append(["port_free", host, port])
        return port in self.free_ports

    def popen(self, command, **kwargs):
        self.calls.append(["popen", [os.path.basename(str(command[0]))] + list(command[1:]), sorted(kwargs)])
        self.popen_started = True
        return FakeProcess(self)

    # ---- 装配
    def port(self):
        return DebugBrowserPort(
            page_state=lambda: self.gui,
            active_profile=lambda: self.profile,
            discover_browsers=self.discover,
            normalize_address=normalize_address,
            verify_browser=self.verify,
            attach_existing=self.attach,
            open_page=self.open_page,
            chrome_path=self.chrome_path,
            is_port_available=self.port_free,
            host="127.0.0.1", port_start=9333, port_end=9340, default_url=DEFAULT_URL,
        )

    def service(self, get_app_root=None):
        return BrowserDebugService(
            browser=self.port(), repo_root=str(self.root),
            get_app_root=get_app_root or (lambda: str(self.root / "frozen-root")),
        )

    def set_page(self, address="127.0.0.1:9333"):
        self.gui.page = FakePage(self, address)
        return self.gui.page

    @property
    def debug_root(self):
        return self.root / "output" / "browser-debug"

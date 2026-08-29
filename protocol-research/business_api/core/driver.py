# -*- coding: utf-8 -*-
"""浏览器 DOM 驱动抽象与 DrissionPage 实现。

设计原则：
- 驱动只负责"在一个已连接的浏览器标签页上做 DOM 原子操作"，不负责启动 / attach
  浏览器的复杂逻辑（那部分由集成层提供 page 对象；现有 app.py 已有成熟的 CDP attach 实现可复用）。
- 通过依赖注入（传入 page 对象）使业务层可用 mock 驱动做单元测试。
- 合规边界：本驱动只在真实浏览器上做真人式操作，不复现签名、不绕过风控。

locator 直接使用 DrissionPage 原生语法，例如：
    'css:.product-row'、'xpath://button'、'tag:button@text()=发货'、'text:发货'
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, List, Optional

from .errors import BusinessApiError, ErrorCode


class BrowserDriver(ABC):
    """业务层依赖的 DOM 原子能力接口。"""

    @abstractmethod
    def navigate(self, url: str) -> None: ...

    @abstractmethod
    def current_url(self) -> str: ...

    @abstractmethod
    def exists(self, locator: str, timeout: float = 1.0) -> bool: ...

    @abstractmethod
    def count(self, locator: str, timeout: float = 1.0) -> int: ...

    @abstractmethod
    def read_text(self, locator: str, timeout: float = 2.0) -> str: ...

    @abstractmethod
    def read_texts(self, locator: str, timeout: float = 2.0) -> List[str]: ...

    @abstractmethod
    def get_attr(self, locator: str, name: str, timeout: float = 2.0) -> Optional[str]: ...

    @abstractmethod
    def click(self, locator: str, timeout: float = 3.0, index: int = 0) -> None: ...

    @abstractmethod
    def input(self, locator: str, value: str, clear: bool = True, timeout: float = 3.0) -> None: ...

    @abstractmethod
    def wait_visible(self, locator: str, timeout: float = 10.0) -> bool: ...

    @abstractmethod
    def wait_gone(self, locator: str, timeout: float = 10.0) -> bool: ...

    @abstractmethod
    def capture(self, label: str = "capture") -> dict: ...

    @abstractmethod
    def read_rows(self, row_locator: str, cell_locator: str = "tag:td", limit: int = 100) -> List[list]: ...


class DrissionDriver(BrowserDriver):
    """基于 DrissionPage 的真实浏览器驱动。

    只封装 DOM 操作，page 对象由外部注入（便于复用 app.py 的会话或在测试中替换）。
    实现仅使用 app.py 已验证在用的 DrissionPage API 子集，避免依赖不确定的高层封装。
    """

    def __init__(self, page: Any, address: Optional[str] = None) -> None:
        if page is None:
            raise BusinessApiError(
                ErrorCode.BROWSER_NOT_READY,
                "未提供浏览器标签页对象（page 为空）。",
                hint="请先通过集成层连接 / attach 到真实 Chrome 后再注入 page。",
            )
        self._page = page
        self._address = address  # 提供则可在 CDP 连接断开时重连

    @staticmethod
    def _is_disconnect(exc: Exception) -> bool:
        text = f"{type(exc).__name__} {exc}"
        return "Disconnect" in text or "断开" in text

    def _reconnect(self) -> bool:
        if not self._address:
            return False
        try:
            from DrissionPage import ChromiumOptions, ChromiumPage

            self._page = ChromiumPage(ChromiumOptions().set_address(self._address))
            return True
        except Exception:
            return False

    # --- 内部工具 ---
    def _ele(self, locator: str, timeout: float):
        try:
            return self._page.ele(locator, timeout=timeout)
        except Exception as exc:
            raise BusinessApiError(
                ErrorCode.ACTION_FAILED,
                f"定位元素出错：{locator}（{exc}）",
                context={"locator": locator},
            ) from exc

    def _eles(self, locator: str, timeout: float):
        try:
            return self._page.eles(locator, timeout=timeout)
        except Exception as exc:
            raise BusinessApiError(
                ErrorCode.ACTION_FAILED,
                f"批量定位元素出错：{locator}（{exc}）",
                context={"locator": locator},
            ) from exc

    # --- 导航 ---
    def navigate(self, url: str) -> None:
        try:
            self._page.get(url)
            return
        except Exception as exc:
            # 某些页面导航会触发 CDP 连接断开，尝试重连一次再导航
            if self._is_disconnect(exc) and self._reconnect():
                try:
                    self._page.get(url)
                    return
                except Exception as exc2:
                    exc = exc2
            raise BusinessApiError(
                ErrorCode.ACTION_FAILED,
                f"导航到目标页失败：{url}（{exc}）",
                hint="检查浏览器是否在线、网络是否正常；若为页面重定向导致连接断开，已尝试重连仍失败。",
                context={"url": url},
            ) from exc

    def current_url(self) -> str:
        try:
            return self._page.url or ""
        except Exception:
            return ""

    # --- 查询 ---
    def exists(self, locator: str, timeout: float = 1.0) -> bool:
        try:
            return bool(self._page.ele(locator, timeout=timeout))
        except Exception:
            return False

    def count(self, locator: str, timeout: float = 1.0) -> int:
        eles = self._eles(locator, timeout)
        return len(eles) if eles else 0

    def read_text(self, locator: str, timeout: float = 2.0) -> str:
        ele = self._ele(locator, timeout)
        if not ele:
            raise BusinessApiError(
                ErrorCode.ELEMENT_NOT_FOUND,
                f"读取文本失败：未找到元素 {locator}",
                hint="选择器可能已失效（页面改版）或页面尚未加载完成。",
                context={"locator": locator},
            )
        try:
            return ele.text or ""
        except Exception as exc:
            raise BusinessApiError(
                ErrorCode.ACTION_FAILED,
                f"读取文本出错：{locator}（{exc}）",
                context={"locator": locator},
            ) from exc

    def read_texts(self, locator: str, timeout: float = 2.0) -> List[str]:
        eles = self._eles(locator, timeout)
        result: List[str] = []
        for e in (eles or []):
            try:
                result.append(e.text or "")
            except Exception:
                result.append("")
        return result

    def get_attr(self, locator: str, name: str, timeout: float = 2.0) -> Optional[str]:
        ele = self._ele(locator, timeout)
        if not ele:
            return None
        try:
            return ele.attr(name)
        except Exception:
            return None

    # --- 动作 ---
    def click(self, locator: str, timeout: float = 3.0, index: int = 0) -> None:
        eles = self._eles(locator, timeout)
        if not eles or index >= len(eles):
            raise BusinessApiError(
                ErrorCode.ELEMENT_NOT_FOUND,
                f"点击失败：未找到元素 {locator}（index={index}）",
                hint="页面可能未加载完成，或选择器已失效（页面改版）。",
                context={"locator": locator, "index": index, "match_count": len(eles) if eles else 0},
            )
        ele = eles[index]
        try:
            try:
                ele.scroll.to_center()
            except Exception:
                pass
            ele.click(by_js=True)
        except Exception as exc:
            raise BusinessApiError(
                ErrorCode.ACTION_FAILED,
                f"点击元素失败：{locator}（{exc}）",
                context={"locator": locator, "index": index},
            ) from exc

    def input(self, locator: str, value: str, clear: bool = True, timeout: float = 3.0) -> None:
        ele = self._ele(locator, timeout)
        if not ele:
            raise BusinessApiError(
                ErrorCode.ELEMENT_NOT_FOUND,
                f"输入失败：未找到输入框 {locator}",
                hint="选择器可能已失效（页面改版）或输入框尚未渲染。",
                context={"locator": locator},
            )
        try:
            try:
                ele.scroll.to_center()
            except Exception:
                pass
            ele.input(str(value), clear=clear)
        except Exception as exc:
            raise BusinessApiError(
                ErrorCode.ACTION_FAILED,
                f"向输入框写入失败：{locator}（{exc}）",
                context={"locator": locator},
            ) from exc

    # --- 等待 ---
    def wait_visible(self, locator: str, timeout: float = 10.0) -> bool:
        """等待元素出现。

        注意：当前以"元素存在"近似"可见"，真实可见性（display / opacity / 视口内）
        待真实页面联调时按需补强。这是已知的临时近似，不代表已闭环。
        """
        deadline = time.time() + max(0.1, timeout)
        while time.time() < deadline:
            try:
                if self._page.ele(locator, timeout=0.5):
                    return True
            except Exception:
                pass
            time.sleep(0.2)
        return False

    def wait_gone(self, locator: str, timeout: float = 10.0) -> bool:
        deadline = time.time() + max(0.1, timeout)
        while time.time() < deadline:
            try:
                if not self._page.ele(locator, timeout=0.3):
                    return True
            except Exception:
                return True
            time.sleep(0.2)
        return False

    # --- 取证 ---
    def capture(self, label: str = "capture") -> dict:
        info: dict = {"label": label}
        try:
            info["url"] = self._page.url
        except Exception:
            info["url"] = None
        try:
            info["title"] = self._page.title
        except Exception:
            info["title"] = None
        return info

    def read_rows(self, row_locator: str, cell_locator: str = "tag:td", limit: int = 100) -> List[list]:
        """读取表格：对每个 row 元素取其下 cell 子元素的文本，返回二维文本数组。"""
        rows = self._eles(row_locator, 3.0)
        out: List[list] = []
        for r in (rows or [])[:limit]:
            try:
                cells = r.eles(cell_locator, timeout=0.3)
                out.append([(c.text or "") for c in cells])
            except Exception:
                out.append([])
        return out


def connect_chromium(address: str = "127.0.0.1:9222") -> DrissionDriver:
    """attach 到一个已开启远程调试端口的真实 Chrome，返回 DrissionDriver。

    合规说明：仅接管用户本机已登录的真实浏览器，不创建无头伪装环境、不复现签名。
    """
    try:
        from DrissionPage import ChromiumOptions, ChromiumPage
    except Exception as exc:
        raise BusinessApiError(
            ErrorCode.BROWSER_NOT_READY,
            f"未能导入 DrissionPage：{exc}",
            hint="请确认已安装 DrissionPage（见 requirements.txt）。",
        ) from exc

    try:
        options = ChromiumOptions().set_address(address)
        page = ChromiumPage(options)
    except Exception as exc:
        raise BusinessApiError(
            ErrorCode.BROWSER_NOT_READY,
            f"连接 Chrome 调试端口失败：{address}（{exc}）",
            hint="请先以 --remote-debugging-port 启动 Chrome，或复用项目现有的浏览器启动流程。",
            context={"address": address},
        ) from exc

    return DrissionDriver(page, address=address)

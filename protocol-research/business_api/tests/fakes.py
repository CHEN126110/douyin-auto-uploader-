# -*- coding: utf-8 -*-
"""测试用假驱动：实现 BrowserDriver，行为可脚本化，记录调用序列。"""
from __future__ import annotations

from typing import Dict, List

from business_api.core import BrowserDriver, BusinessApiError, ErrorCode


class FakeDriver(BrowserDriver):
    def __init__(
        self,
        *,
        texts_map: Dict[str, List[str]] = None,
        exists_map: Dict[str, bool] = None,
        rows: List[list] = None,
        visible: bool = True,
        logged_in: bool = True,
        captcha: bool = False,
        xpath_exists: bool = True,
        url: str = "https://fxg.jinritemai.com/ffa/g/list",
    ) -> None:
        self.calls: List[tuple] = []
        self._texts_map = texts_map or {}
        self._exists_map = exists_map or {}
        self._rows = rows or []
        self._visible = visible
        self._logged_in = logged_in
        self._captcha = captcha
        self._xpath_exists = xpath_exists
        self._url = url

    def navigate(self, url):
        self.calls.append(("navigate", url))
        self._url = url

    def current_url(self):
        if not self._logged_in:
            return "https://fxg.jinritemai.com/login/common"
        return self._url

    def exists(self, locator, timeout=1.0):
        self.calls.append(("exists", locator))
        low = locator.lower()
        if self._captcha and ("captcha" in low or "验证" in locator or "滑块" in locator):
            return True
        if "shopname" in low or "header-shop" in low or "userinfo" in low:
            return self._logged_in
        if locator in self._exists_map:
            return self._exists_map[locator]
        if locator.startswith("xpath:"):
            return self._xpath_exists
        return False

    def count(self, locator, timeout=1.0):
        return len(self._texts_map.get(locator, []))

    def read_text(self, locator, timeout=2.0):
        vals = self._texts_map.get(locator)
        if not vals:
            raise BusinessApiError(ErrorCode.ELEMENT_NOT_FOUND, f"未找到 {locator}")
        return vals[0]

    def read_texts(self, locator, timeout=2.0):
        return list(self._texts_map.get(locator, []))

    def read_rows(self, row_locator, cell_locator="tag:td", limit=100):
        return [list(r) for r in self._rows[:limit]]

    def get_attr(self, locator, name, timeout=2.0):
        return None

    def click(self, locator, timeout=3.0, index=0):
        self.calls.append(("click", locator, index))

    def input(self, locator, value, clear=True, timeout=3.0):
        self.calls.append(("input", locator, value))

    def wait_visible(self, locator, timeout=10.0):
        self.calls.append(("wait_visible", locator))
        if locator in self._exists_map:
            return self._exists_map[locator]
        return self._visible

    def wait_gone(self, locator, timeout=10.0):
        return True

    def capture(self, label="capture"):
        return {"label": label, "url": self._url}

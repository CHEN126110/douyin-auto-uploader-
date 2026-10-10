# -*- coding: utf-8 -*-
"""平台自己的 ``dir.query`` / ``file.query`` 响应解析与「读不到 ≠ 不存在」判据。

真机 2026-10-10 的两次代价都在这里：
1. 目录树是 DOM 虚拟列表，读不到就当「没有这个商品目录」→ 走整目录导入 →
   **云端多一个同名目录 + 33 张重传**（目录 id 连变三次）；
2. 文件清单靠 DOM 读，页面一刷新就读不到 → 「图片空间缺少原目录图片」。
"""

from __future__ import annotations

import json

import pytest

from taobao_publish import folder_import, page
from taobao_publish.cloud_listing import CloudListing, _parse_jsonp


class FakeBrowser:
    """只实现 CloudListing 用到的那几个 CDP 调用。"""

    def __init__(self, events, bodies=None):
        self._events = list(events)
        self._bodies = dict(bodies or {})
        self.calls = []

    def drain_events(self, deadline=None, event_names=()):
        # 真实 `CdpBrowser.drain_events` 一次把缓存里的事件全交出来。
        events, self._events = self._events, []
        return events

    def call(self, method, params=None, session_id=None):
        self.calls.append((method, params))
        if method == "Network.getResponseBody":
            return {"body": self._bodies.get((params or {}).get("requestId"), "")}
        return {}


def request_event(request_id, url):
    return {"method": "Network.requestWillBeSent",
            "params": {"requestId": request_id, "request": {"url": url}}}


def response_event(request_id):
    return {"method": "Network.responseReceived", "params": {"requestId": request_id}}


def jsonp(payload):
    return "callback({});".format(json.dumps(payload, ensure_ascii=False))


DIR_TREE = {"data": {"dirs": {"children": [
    {"name": "ID-1", "id": "111", "pid": "0", "childrenSize": 1, "children": [
        {"name": "SKU", "id": "222", "pid": "111", "childrenSize": 0, "children": []},
    ]},
    {"name": "神笔", "id": "333", "pid": "0", "childrenSize": 0, "children": []},
]}}}

FILE_LIST = {"data": {"fileModule": [
    {"name": "01.jpg", "fullUrl": "https://img.example.invalid/O1CN01aaa_!!1-0.jpg",
     "pictureId": "9001", "md5": "abc", "pictureCategoryId": "222"},
], "catModule": [], "page": 1}}


def test_jsonp_and_plain_json_are_both_accepted():
    assert _parse_jsonp('cb({"a":1});') == {"a": 1}
    assert _parse_jsonp('{"a":1}') == {"a": 1}
    assert _parse_jsonp('not json at all') is None


def test_directory_tree_is_flattened_with_ids():
    browser = FakeBrowser(
        [request_event("1", "https://qn.taobao.com/api/dir.query?data=%7B%7D"),
         response_event("1")],
        {"1": jsonp(DIR_TREE)})
    listing = CloudListing(browser, session_id=1)
    listing.observe(0)
    assert [node["name"] for node in listing.directories()] == ["ID-1", "SKU", "神笔"]
    assert listing.find_directories("ID-1")[0]["id"] == "111"
    assert listing.find_directories("SKU")[0]["depth"] == 1


def test_file_query_gives_name_url_and_picture_id():
    browser = FakeBrowser(
        [request_event("2", "https://qn.taobao.com/api/file.query?data=%7B%22catId%22%3A%22222%22%7D"),
         response_event("2")],
        {"2": jsonp(FILE_LIST)})
    listing = CloudListing(browser, session_id=1)
    listing.observe(0)
    files = listing.files("222")
    assert [item["name"] for item in files] == ["01.jpg"]
    assert files[0]["picture_id"] == "9001"
    assert files[0]["url"].startswith("https://img.example.invalid/O1CN01aaa")


def test_missing_response_is_not_an_empty_directory():
    """**本模块存在的唯一理由**：读不到（``None``）与目录是空的（``[]``）必须分开。"""

    browser = FakeBrowser(
        [request_event("3", "https://qn.taobao.com/api/file.query?data=%7B%22catId%22%3A%22777%22%7D"),
         response_event("3")],
        {"3": jsonp({"data": {"fileModule": []}})})
    listing = CloudListing(browser, session_id=1)
    listing.observe(0)
    assert listing.files("777") == [], "平台明确回了空清单，这才是「目录是空的」"
    assert listing.files("888") is None, "没收到这个目录的响应 = 读不出来，不是空目录"


class FakeListing:
    """给 folder_import 的判据用：只实现它调用的那几个方法。"""

    def __init__(self, directories=(), files=None, dir_responses=1):
        self._directories = list(directories)
        self._files = dict(files or {})
        self.dir_responses = dir_responses
        self.observed = 0

    def observe(self, seconds=0.0):
        self.observed += 1

    def find_directories(self, name):
        return [node for node in self._directories if node["name"] == name]

    def find_child(self, parent_id, name):
        for node in self._directories:
            if node["pid"] == str(parent_id) and node["name"] == name:
                return node
        return None

    def files(self, cat_id):
        return self._files.get(str(cat_id))


def test_product_root_uses_the_platform_directory_listing(monkeypatch):
    """DOM 树读不到不算数：平台列了目录就按目录走「逐张核对」，不走整目录导入。"""

    monkeypatch.setattr('taobao_publish.media_library.product_root_path',
                        lambda *args, **kwargs: None)
    listing = FakeListing([{"name": "ID-1", "id": "111", "pid": "0", "depth": 0}])
    assert folder_import._cloud_product_root(None, listing, "ID-1") == ["ID-1"]


def test_two_same_named_product_folders_stop_the_flow():
    listing = FakeListing([{"name": "ID-1", "id": "111", "pid": "0", "depth": 0},
                           {"name": "ID-1", "id": "999", "pid": "0", "depth": 0}])
    with pytest.raises(page.PageError, match="多个同名商品目录"):
        folder_import._cloud_product_root(None, listing, "ID-1")


def test_unreadable_directory_listing_never_means_the_folder_is_absent(monkeypatch):
    """**最贵的一条**：没读到目录清单时走整目录导入，会在云端新建同名目录并重传全部图片。"""

    monkeypatch.setattr('taobao_publish.media_library.open_root_directory',
                        lambda *args, **kwargs: None)
    monkeypatch.setattr('taobao_publish.media_library.product_root_path',
                        lambda *args, **kwargs: None)
    listing = FakeListing([], dir_responses=0)
    with pytest.raises(page.PageError, match="读不到不等于目录不存在"):
        folder_import._cloud_product_root(None, listing, "ID-1")


def test_directory_listing_saying_absent_allows_a_fresh_import():
    """真·新商品：读到了目录清单、里面确实没有它 → 才允许整目录导入。"""

    listing = FakeListing([{"name": "别的商品", "id": "111", "pid": "0", "depth": 0}],
                          dir_responses=1)
    assert folder_import._cloud_product_root(None, listing, "ID-1") is None


def test_receipts_prefer_the_platform_file_listing(monkeypatch):
    """回执读的是平台自己的 `fileModule`——页面刷新不该再影响这一步。"""

    class Source:
        relative_path = "SKU/01.jpg"
        sha256 = "a" * 64

    class Manifest:
        folder_name = "ID-1"
        images = [Source()]

    def forbidden(*args, **kwargs):
        raise AssertionError("有权威清单时不该再走 DOM 读取")

    monkeypatch.setattr('taobao_publish.media_library.read_directory_files', forbidden)
    monkeypatch.setattr('taobao_publish.media_library.open_directory',
                        lambda *args, **kwargs: ["ID-1", "SKU"])
    listing = FakeListing(
        [{"name": "ID-1", "id": "111", "pid": "0", "depth": 0},
         {"name": "SKU", "id": "222", "pid": "111", "depth": 1}],
        files={"222": [
            {"name": "01.jpg", "url": "https://img.example.invalid/01.jpg", "picture_id": "9001"}]})
    receipts = folder_import._read_receipts(None, Manifest(), ["ID-1"], listing=listing)
    assert [item.relative_path for item in receipts] == ["SKU/01.jpg"]
    assert receipts[0].picture_id == "9001"

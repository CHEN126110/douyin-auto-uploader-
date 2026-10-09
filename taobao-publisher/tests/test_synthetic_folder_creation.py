# -*- coding: utf-8 -*-
"""合成素材中心页上的「自动建目录」整段回归（**完全离线**）。

2026-10-07。这段路（回根 → 唯一性守卫 → 点「新建文件夹」→ 填名字 → 点「确定」→ 回读
folderId）在真机上需要**写平台**（要在别人的图片空间里新建目录），所以默认不能跑。
而它又是"图片按商品文件夹归档"的关键一步——不验证就上线，风险全压在用户第一次上架。

本文件用项目既有的隔离套路解决这个矛盾：
`chrome-headless-shell` + 独立 profile + `--host-resolver-rules=MAP * ~NOTFOUND`
（除 127.0.0.1 外全部解析失败）+ **本地同形合成页**
`tests/fixtures/synthetic-material-center.html`。

合成页的形状**全部来自真机取证**，不是猜的：
树节点外层 `li.next-tree-node[value][name]`（E-282/E-285）、
**树里没有「全部图片」节点**（E-291）、回根只能点面包屑第一项（E-292）。

配套的独立脚本：`tmp/verify-create-folders-synthetic.py`（同样内容，便于人工复跑与看输出）。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from taobao_publish import media_library
from taobao_publish.page import PageClient

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "synthetic-material-center.html"


def _headless_shell():
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    found = sorted(root.glob(
        "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"))
    return found[-1] if found else None


@pytest.fixture(scope="module")
def synthetic_browser(tmp_path_factory):
    """启动隔离浏览器并把**端口 / 原标签 id** 一并交给用例。

    需要端口是因为要验证 `protocol_media.ensure_cloud_folders` 的**跨标签页**编排
    （它自己开一个素材中心标签建目录、建完关掉）。
    """

    exe = _headless_shell()
    if exe is None:
        pytest.skip("缺少本地独立 headless Chromium")
    # 每轮独立 profile，不能清空另一个测试会话仍在使用的浏览器目录。
    profile = tmp_path_factory.mktemp('synthetic-browser-profile')
    process = subprocess.Popen(
        [str(exe), "--headless", "--remote-debugging-port=0",
         "--user-data-dir=" + str(profile),
         "--disable-background-networking", "--no-proxy-server",
         "--host-resolver-rules=MAP * ~NOTFOUND",
         "--disable-component-update", "--no-first-run", FIXTURE.as_uri()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    client = None
    try:
        active = profile / "DevToolsActivePort"
        deadline = time.monotonic() + 20
        while not active.is_file():
            if time.monotonic() > deadline or process.poll() is not None:
                pytest.fail("隔离测试浏览器启动失败")
            time.sleep(0.1)
        port = int(active.read_text(encoding="utf-8").splitlines()[0])
        with urllib.request.urlopen("http://127.0.0.1:%s/json/list" % port, timeout=5) as response:
            targets = json.load(response)
        matches = [t for t in targets if t.get("url") == FIXTURE.as_uri()]
        assert len(matches) == 1, "只能连接此次新建浏览器中的本地合成页"
        client = PageClient.connect(matches[0]["webSocketDebuggerUrl"],
                                    target_url=FIXTURE.as_uri())
        # CDP 能发现目标 URL 不代表 HTML 已加载；只等待文档生命周期，不重试业务读树。
        deadline = time.monotonic() + 10
        while not client.evaluate("document.readyState === 'complete'", timeout=2):
            if time.monotonic() >= deadline:
                pytest.fail('隔离测试页面未完成加载')
            time.sleep(0.05)
        yield SimpleNamespace(client=client, port=port, target_id=matches[0]["id"])
    finally:
        if client is not None:
            client.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.fixture(scope="module")
def synthetic_client(synthetic_browser):
    return synthetic_browser.client


def test_material_center_shape_has_no_root_node(synthetic_client):
    """合成页与真机一样：树里没有「全部图片」节点 → 根前缀必须是空前缀。"""

    state = media_library.read_directory(synthetic_client, context_id=None)
    assert state["supported"] is True
    assert media_library.root_prefix(state) == []


def test_breadcrumb_returns_to_the_root_layer(synthetic_client):
    """进到子目录后再回根——这是"建到根下"而不是"建到当前目录下"的前提。"""

    media_library.open_directory(synthetic_client, ["ID-1"], context_id=None,
                                 page=media_library.PAGE_MATERIAL_CENTER)
    assert media_library.read_directory(synthetic_client, context_id=None)["path"] == ["ID-1"]

    assert media_library.open_root_directory(synthetic_client, context_id=None) == []
    assert media_library.read_directory(synthetic_client, context_id=None)["path"] == []


def test_create_product_then_role_folder_and_read_back(synthetic_client):
    """整段：建商品目录 → 在它下面建角色目录 → 回读两个 folderId（且必须不同）。"""

    media_library.open_root_directory(synthetic_client, context_id=None)
    product = "ID-合成测试商品"
    product_id = media_library.ensure_child_directory(synthetic_client, [], product,
                                                      context_id=None)
    assert product_id

    role_id = media_library.ensure_child_directory(synthetic_client, [product], "主图",
                                                   context_id=None)
    assert role_id
    # 两个目录必须是不同的 id：合成页曾用 JS number 递增（超出安全整数范围）而让
    # 两个新目录拿到同一个 id —— 那种"看起来对"的结果最危险。
    assert role_id != product_id

    paths = [list(entry["path"]) for entry in
             media_library.read_directory(synthetic_client, context_id=None)["directories"]]
    assert [product] in paths
    assert [product, "主图"] in paths


def test_second_call_is_idempotent(synthetic_client):
    """幂等：目录已存在时直接返回既有 folderId，**不再建一个同名的**。"""

    media_library.open_root_directory(synthetic_client, context_id=None)
    product = "ID-合成幂等商品"
    first = media_library.ensure_child_directory(synthetic_client, [], product, context_id=None)
    second = media_library.ensure_child_directory(synthetic_client, [], product, context_id=None)
    assert first == second

    names = [entry["path"][-1] for entry in
             media_library.read_directory(synthetic_client, context_id=None)["directories"]]
    assert names.count(product) == 1, "同一个名字被建了两次：{}".format(names)


def test_ensure_cloud_folders_runs_in_its_own_tab(synthetic_browser, monkeypatch):
    """`protocol_media.ensure_cloud_folders` 的**跨标签页**编排。

    这是生产真正调用的那个函数（`stages._cloud_folder_creator` 就是包着它）。
    它承诺：**自己开一个素材中心标签**建目录、**建完立刻关掉**、
    不去导航正在填写的发布页。这三条以前只有静态推断，这里把它钉住：
      ① 返回商品子目录的 folderId（且互不相同）；
      ② 临时标签被关掉（浏览器里只剩原来那一个页面）；
      ③ **原标签仍然活着**——"不影响正在填写的表单"这句承诺有据。
    """

    from taobao_publish import protocol_media

    # 让"素材中心页"指向本地合成页（同样的 file:// 来源，零网络）。
    monkeypatch.setattr(protocol_media, "MATERIAL_CENTER_URL", FIXTURE.as_uri())

    created = protocol_media.ensure_cloud_folders(
        synthetic_browser.port, "ID-合成商品-002", ["主图", "SKU"])
    assert created.get("主图") and created.get("SKU"), created
    assert created["主图"] != created["SKU"], "两个角色目录拿到了同一个 folderId"

    with urllib.request.urlopen(
            "http://127.0.0.1:%s/json/list" % synthetic_browser.port, timeout=5) as response:
        targets = json.load(response)
    pages = [t for t in targets if t.get("type") == "page"]
    assert [t for t in pages if t["id"] == synthetic_browser.target_id], \
        "原页面被关掉了——建目录不该影响正在填写的表单"
    assert len(pages) == 1, "建目录用的临时标签没有关掉：{}".format(
        [(t.get("title"), t.get("url")) for t in pages])

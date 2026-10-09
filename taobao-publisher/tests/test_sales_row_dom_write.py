# -*- coding: utf-8 -*-
"""`fill_price_stock` 的**真实 DOM 写入**：隔离浏览器 + 合成销售信息页。

## 这个文件现在只钉两件事

1. 「一口价 / 总库存」真的通过 ``page.fill_text_field`` 写进页面（含"写入前先回读既有值"）；
2. 「购买须知」这一行**不再被碰**——该功能已按用户要求撤掉（界面 + 流水线 + 契约，
   2026-10-07 删死链）。这一条是**反向断言**：证明撤干净了，而不是假装它还活着。

## 被删掉的两条（留个记录，不要照着复活）

* ``test_empty_notice_leaves_the_row_untouched``：随功能一起删——"没填就不动这一行"
  对一个已经不存在的功能没有意义；
* ``test_programmatic_write_bypasses_maxlength``：**结论仍然成立、但不再由本阶段触发**。
  实测事实（证据 E-315）：``fill_text_field`` 用 JS 直接赋 ``value``，而 ``maxlength``
  **只约束用户输入、不约束脚本赋值**——所以"回读"这一层拦不住超长值，任何依赖
  ``maxlength`` 的字段都得靠**写入方自己**先限长。哪天再往表单里加带长度上限的字段，
  记得把这条结论带上。

## 边界

不联网、不碰淘宝、不发上传请求；只驱动真实 PageClient 对着本地 ``file://`` 合成页。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

from taobao_publish import models, stages
from taobao_publish.page import PageClient

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "synthetic-publish-sales.html"


def _headless_shell():
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    found = sorted(root.glob(
        "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"))
    return found[-1] if found else None


@pytest.fixture(scope="module")
def sales_page(tmp_path_factory):
    """隔离浏览器里的合成销售信息页。产出**连接参数**而不是客户端。

    ⚠️ 不能让测试复用同一个 `PageClient`：`stage_fill_price_stock` 在 `finally` 里
    会 `client.close()`（阶段自己管连接，这是它的设计）。所以每次要读页面都得**新开一个
    客户端**——顺带这也让"页面上的值"成为**独立回读**，而不是听阶段自己汇报。
    """

    exe = _headless_shell()
    if exe is None:
        pytest.skip("缺少本地独立 headless Chromium")
    profile = tmp_path_factory.mktemp('synthetic-sales-profile')
    process = subprocess.Popen(
        [str(exe), "--headless", "--remote-debugging-port=0",
         "--user-data-dir=" + str(profile),
         "--disable-background-networking", "--no-proxy-server",
         "--host-resolver-rules=MAP * ~NOTFOUND",
         "--disable-component-update", "--no-first-run", FIXTURE.as_uri()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        active = profile / "DevToolsActivePort"
        deadline = time.monotonic() + 20
        while not active.is_file():
            if time.monotonic() > deadline or process.poll() is not None:
                pytest.fail("隔离测试浏览器启动失败")
            time.sleep(0.1)
        with urllib.request.urlopen("http://127.0.0.1:%s/json/list" % active.read_text(
                encoding="utf-8").splitlines()[0], timeout=5) as response:
            matches = [t for t in json.load(response) if t.get("url") == FIXTURE.as_uri()]
        assert len(matches) == 1, "只能连接此次新建浏览器中的本地合成页"
        connection = {"ws_url": matches[0]["webSocketDebuggerUrl"], "url": FIXTURE.as_uri()}
        ready_client = _open(connection)
        try:
            deadline = time.monotonic() + 5
            while ready_client.evaluate("document.readyState === 'complete' && !!document.getElementById('stock')") is not True:
                if time.monotonic() >= deadline:
                    pytest.fail('本地销售信息夹具未完成加载')
                time.sleep(0.05)
        finally:
            ready_client.close()
        yield connection
    finally:
        process.terminate()
        process.wait(timeout=8)


def _open(sales_page):
    return PageClient.connect(sales_page["ws_url"], target_url=sales_page["url"])


class _Ctx:
    def __init__(self, item):
        from taobao_publish.contracts import load_contracts
        self.item = item
        self._contracts = load_contracts()
        self.scratch = {}
        self.dry_run = False
        self.authorization = None
        self.cdp_list_url = ""

    def resolved_contracts(self):
        return self._contracts


def _item():
    return models.PublishItem(
        record_id=7, record_name="ID-销售行",
        skus=[models.SkuEntry(spec_values={"颜色分类": "黑"}, price=19.9, stock=10),
              models.SkuEntry(spec_values={"颜色分类": "白"}, price=25.0, stock=5)])


def _run(sales_page, monkeypatch):
    """把 `_open_publish_page` 换成"连到本地合成页"，其余全走真代码。"""

    ctx = _Ctx(_item())
    client = _open(sales_page)
    monkeypatch.setattr(stages, "_open_publish_page", lambda *a, **k: client)
    return stages.stage_fill_price_stock(ctx)


def _values(sales_page):
    """**新开一个客户端**独立回读页面上的值（阶段已经把它的连接关掉了）。"""

    client = _open(sales_page)
    try:
        return {
            name: client.evaluate("document.getElementById(%s).value" % json.dumps(name))
            for name in ("price", "stock", "notice")
        }
    finally:
        client.close()


def test_sales_rows_are_written_through_the_real_dom(sales_page, monkeypatch):
    outcome = _run(sales_page, monkeypatch)

    assert outcome.ok, outcome.summary
    values = _values(sales_page)
    # 一口价取最低 SKU 单价的两倍并向上取整到元；总库存是合计。
    assert values["price"] == stages._format_price(40)
    assert values["stock"] == "15"
    assert outcome.data["stock_before"] == "1", "写入前必须回读到真机的预填值"


def test_the_purchase_notice_row_is_no_longer_touched(sales_page, monkeypatch):
    """「购买须知」功能已删（界面 + 流水线 + 契约），这一行**不该再被写**。

    反向断言的价值：证明死链真的撤干净了，而不是"看起来删了、其实还写"。
    """

    cleaner = _open(sales_page)
    try:
        cleaner.evaluate("document.getElementById('notice').value=''")
    finally:
        cleaner.close()

    outcome = _run(sales_page, monkeypatch)

    assert outcome.ok, outcome.summary
    assert _values(sales_page)["notice"] == "", "这一行不该再被流水线写"
    assert "购买须知" not in outcome.summary, "阶段摘要里也不该再出现这个概念"

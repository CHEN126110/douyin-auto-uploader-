# -*- coding: utf-8 -*-
"""测试路径注入。

本子项目的测试**独立于仓库根**：``python -m pytest taobao-publisher/tests``
即可运行，不需要 ``cd`` 到仓库根，也不需要数据库或网络。
"""

from __future__ import annotations

import sys
from pathlib import Path

SUBPROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(SUBPROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT_ROOT))


import ipaddress
import socket
import pytest


@pytest.fixture(autouse=True)
def forbid_live_app_and_browser_connections(monkeypatch):
    """只允许隔离测试自己的临时本地端口；不让早期返回掩盖未隔离的调用。"""
    reserved = {1420, 5001, 8769, 9222, 9333, 9334} | set(range(9500, 9600))
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex

    def check(address):
        if not isinstance(address, tuple) or len(address) < 2:
            return
        host, port = address[:2]
        try:
            local = str(host).lower() == 'localhost' or ipaddress.ip_address(str(host)).is_loopback
        except ValueError:
            local = False
        if not local or port in reserved:
            raise AssertionError('离线测试禁止连接外部网站或正在使用的应用/浏览器；请注入本地模型或替身')

    def isolated_connect(sock, address):
        check(address)
        return connect(sock, address)

    def isolated_connect_ex(sock, address):
        check(address)
        return connect_ex(sock, address)

    monkeypatch.setattr(socket.socket, 'connect', isolated_connect)
    monkeypatch.setattr(socket.socket, 'connect_ex', isolated_connect_ex)


@pytest.fixture(autouse=True)
def isolate_upload_ledger(monkeypatch, tmp_path, request):
    """上传账本隔离：默认把账本重定向到测试临时目录。

    上传名=源文件名后，**DOM 路线也会在定位成功后登记账本**——不隔离的话，
    跑离线测试会往真实账本（``taobao_media_upload_ledger.json``）写夹具素材
    条目（2026-10-08 实测污染了 34 条 ``img.example.invalid`` 记录）。
    重定向 ``ledger_path`` 而不是替换 ``UploadLedger``：键规则、https 过滤、
    落盘语义都保持真实。需要特定账本内容的测试用 ``fake_ledger.install``
    再覆盖 ``UploadLedger.load`` 即可（后注册的 monkeypatch 生效）。
    测试 ``ledger_path`` 本身行为的用例打 ``@pytest.mark.real_ledger_path``
    豁免本隔离。
    """
    if request.node.get_closest_marker('real_ledger_path') is not None:
        return
    from taobao_publish import protocol_media

    monkeypatch.setattr(protocol_media, 'ledger_path',
                        lambda: tmp_path / 'upload-ledger.json')

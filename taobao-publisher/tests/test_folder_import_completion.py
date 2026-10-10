# -*- coding: utf-8 -*-
"""云端已有商品目录时的补传语义（**离线**：假客户端 + 假上传通道，不连接平台）。

真机 2026-10-10 的事实：`ID-986833932804/` 三个角色目录都在、folderId 与上传账本逐字相同，
但目录里一个文件都没有（平台自己的 `file.query` 对三个 catId 都返回 0）。
旧代码把"目录在"当成"图在"，于是要么复用一份已经失效的回执，要么报
`判据=directory_missing` 让人去建那个**已经存在**的目录。

本文件钉住新语义：
* 云端有的同名文件 → 身份一致才采纳（`uploaded_now=False`）；
* 云端没有的 → 用协议上传补进它该去的那个 folderId，**回读核对**后才算落库，并写进账本；
* 身份对不上 / 账本没有本批回执 → **如实失败且一个字节都不上传**（不覆盖、不将就）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_prepared_media_manifest import prepared_case  # noqa: F401 - pytest fixture
from taobao_publish import folder_import as module, media_library
from taobao_publish.authorization import WriteAuthorization
from taobao_publish.page import PageError
from taobao_publish.upload_api import UploadReceipt

AUTH = WriteAuthorization.for_form_filling()
PORT = 9500


class FakeLedger:
    """假账本：按「文件名 + sha256」查回执，并记录写入。"""

    current: "FakeLedger"

    def __init__(self, entries=None):
        self.entries = dict(entries or {})
        self.recorded = []

    @classmethod
    def load(cls):
        return cls.current

    def lookup(self, identity):
        return self.entries.get((identity["name"], identity["sha256"]))

    def record(self, identity, receipt, folder_id=""):
        self.recorded.append({"name": identity["name"], "url": receipt.get("url"),
                              "folder_id": folder_id})


@pytest.fixture
def completion(monkeypatch, prepared_case):
    """把云端目录、账本、上传通道全部换成可控的假实现。"""

    _root, prepared, _item = prepared_case
    manifest = prepared.manifest
    cloud: dict = {}          # {(商品目录, 'SKU'): {文件名: url}}——键是完整云端路径
    folder_ids: dict = {}     # {完整云端路径: folderId}
    uploads: list = []
    ledger = FakeLedger()

    def cloud_url(source):
        return "https://img.example.invalid/" + source.sha256 + ".jpg"

    def read_directory_files(_client, directory, **_kwargs):
        return {"files": [{"name": name, "url": url, "picture_id": "pid-" + name}
                          for name, url in cloud.get(tuple(directory), {}).items()]}

    def ensure_child_directory(_client, parent, name, **_kwargs):
        key = tuple(parent) + (str(name),)
        folder_ids.setdefault(key, "fid-{}".format(len(folder_ids) + 1))
        return folder_ids[key]

    class FakeUploader:
        def __init__(self, _session):
            pass

        def upload_batch(self, candidates, *, folder_id, authorization,
                         progress=None, pace_seconds=0.0, on_receipt=None):
            authorization.require("upload_image")
            names = [item.name for item in candidates]
            uploads.append({"folder_id": folder_id, "names": names})
            parts = next(key for key, value in folder_ids.items() if value == folder_id)
            receipts = []
            for item in candidates:
                url = "https://img.example.invalid/uploaded-" + item.name
                cloud.setdefault(parts, {})[item.name] = url
                receipts.append(UploadReceipt(name=item.name, url=url,
                                              picture_id="new-" + item.name,
                                              folder_id=folder_id))
            return SimpleNamespace(ok=True, receipts=tuple(receipts), failed=(),
                                   stopped_reason="", attempted=len(names))

    FakeLedger.current = ledger
    monkeypatch.setattr(media_library, "read_directory_files", read_directory_files)
    monkeypatch.setattr(media_library, "ensure_child_directory", ensure_child_directory)
    # 回读前的「进目录 + 让页面重拉这一层」在这里没有真实页面，桩成无副作用；
    # 云端内容由上面的 read_directory_files 假实现提供。
    monkeypatch.setattr(media_library, "open_directory",
                        lambda _client, path, **_kwargs: list(path))
    monkeypatch.setattr(media_library, "refresh_gallery", lambda _client, **_kwargs: True)
    monkeypatch.setattr("taobao_publish.protocol_media.UploadLedger", FakeLedger)
    monkeypatch.setattr("taobao_publish.cdp_ws.CdpBrowser", lambda **_k: Mock())
    monkeypatch.setattr("taobao_publish.upload_page.open_session",
                        lambda _browser, **_k: Mock())
    monkeypatch.setattr("taobao_publish.upload_page.PictureSpacePageUploader", FakeUploader)
    return SimpleNamespace(manifest=manifest, cloud=cloud, folder_ids=folder_ids,
                           uploads=uploads, ledger=ledger, cloud_url=cloud_url,
                           client=Mock())


def _cloud_path(manifest, relative_path):
    return (manifest.folder_name, *Path(relative_path).parts[:-1])


def _adopt_all(completion):
    """把云端目录铺成"图都在、账本也一致"的状态。"""

    manifest = completion.manifest
    for source in manifest.images:
        name = Path(source.relative_path).name
        url = completion.cloud_url(source)
        completion.cloud.setdefault(_cloud_path(manifest, source.relative_path), {})[name] = url
        completion.ledger.entries[(name, source.sha256)] = {"url": url, "picture_id": "old"}


def _complete(completion):
    return module._complete_existing(completion.client, completion.manifest,
                                     [completion.manifest.folder_name], "account-A",
                                     port=PORT, authorization=AUTH)


def test_present_files_are_adopted_without_any_upload(completion):
    _adopt_all(completion)
    prepared = _complete(completion)
    prepared.validate("account-A")
    assert completion.uploads == [], "图都在云端时不该上传任何一张"
    assert all(receipt.uploaded_now is False for receipt in prepared.receipts)
    assert {receipt.folder for receipt in prepared.receipts} == {
        (completion.manifest.folder_name, *Path(source.relative_path).parts[:-1])
        for source in completion.manifest.images}


def test_missing_files_are_uploaded_into_their_own_role_folder(completion):
    """真机形态：目录都在，但只有部分层里还有图 → **只补缺的那些**，且各回各的角色目录。"""

    manifest = completion.manifest
    # 云端只保留「主图」那一张，其余目录清空（目录仍在，folderId 仍在）
    keep = next(source for source in manifest.images
                if Path(source.relative_path).parts[0] == "主图")
    keep_name = Path(keep.relative_path).name
    for source in manifest.images:
        bucket = completion.cloud.setdefault(_cloud_path(manifest, source.relative_path), {})
        if source is not keep:
            bucket.pop(Path(source.relative_path).name, None)
    keep_path = _cloud_path(manifest, keep.relative_path)
    completion.cloud.setdefault(keep_path, {})[keep_name] = completion.cloud_url(keep)
    completion.ledger.entries[(keep_name, keep.sha256)] = {
        "url": completion.cloud_url(keep), "picture_id": "old"}

    prepared = _complete(completion)
    prepared.validate("account-A")

    expected = sorted(Path(source.relative_path).name for source in manifest.images
                      if source is not keep)
    uploaded = sorted(name for call in completion.uploads for name in call["names"])
    assert uploaded == expected
    # 按目标目录分组：每个 folderId 一次调用，且都落在「商品目录/<角色>」这一层
    assert len({call["folder_id"] for call in completion.uploads}) == len(completion.uploads)
    for call in completion.uploads:
        parts = next(key for key, value in completion.folder_ids.items()
                     if value == call["folder_id"])
        assert parts[0] == manifest.folder_name
        assert len(parts) == 2, "图必须落到角色子目录，不能落到商品目录根层"
    assert all(receipt.uploaded_now for receipt in prepared.receipts
               if Path(receipt.relative_path).name != keep_name
               or receipt.folder != (manifest.folder_name, "主图"))
    # 补传成功后写回账本，键里带目录，避免以后又被"有回执"挡住
    assert {item["folder_id"] for item in completion.ledger.recorded} == {
        call["folder_id"] for call in completion.uploads}


def test_read_returning_nothing_while_ledger_says_uploaded_refuses_to_reupload(completion):
    """**读不到 ≠ 不存在**：账本说图就传在这个目录，页面却读到 0 张 → 拒绝重传。

    真机 2026-10-10 的代价：素材中心的文件列表与选图器不是同一套 class，读取器
    把「目录里明明有 5 张图」读成 0 张，于是补传了 5 张**同名重复素材**。
    现在这种自相矛盾的状态一律停下来：重复素材比停下来难收拾得多。
    """

    manifest = completion.manifest
    # 账本记录这批图就传在各自的角色目录里，但云端一个文件都读不到
    for source in manifest.images:
        parts = tuple(Path(source.relative_path).parts[:-1])
        name = Path(source.relative_path).name
        completion.ledger.entries[(name, source.sha256)] = {
            "url": completion.cloud_url(source),
            "folder_id": completion.folder_ids.setdefault(
                (manifest.folder_name, *parts), "fid-" + "-".join(parts)),
        }

    with pytest.raises(PageError) as caught:
        _complete(completion)
    assert "拒绝重复上传" in str(caught.value)
    assert completion.uploads == [], "这种情况下一个字节都不许传"


def test_missing_role_folder_is_created_then_filled(completion):
    """用途目录云端还不存在时：**先建目录，再把图补进去**，而不是报 directory_missing。

    真机 2026-10-10：本地商品目录当时有 33 张图 / 5 个子目录（`白底图`、`SKU_1x1`
    是白底图流水线后来生成的），云端只有 3 个目录。旧顺序「先读后建」在
    `ID-986833932804/SKU_1x1` 上又报了一次 `判据=directory_missing`——
    而建目录本来就是协议路线的既定动作（`ensure_cloud_folders`，E-287）。
    """

    manifest = completion.manifest
    completion.cloud.clear()
    completion.ledger.entries.clear()

    prepared = _complete(completion)
    prepared.validate("account-A")

    assert all(receipt.uploaded_now for receipt in prepared.receipts)
    # 每个用途目录都被建出来，且图按目录分组成批上传
    expected_paths = {_cloud_path(manifest, source.relative_path)
                      for source in manifest.images}
    assert set(completion.folder_ids) == expected_paths
    assert len(completion.uploads) == len(expected_paths)
    for call in completion.uploads:
        parts = next(key for key, value in completion.folder_ids.items()
                     if value == call["folder_id"])
        assert parts[0] == manifest.folder_name and len(parts) == 2


def test_same_name_with_different_identity_fails_and_uploads_nothing(completion):
    _adopt_all(completion)
    source = completion.manifest.images[0]
    completion.cloud[_cloud_path(completion.manifest, source.relative_path)][
        Path(source.relative_path).name] = "https://img.example.invalid/another-image.jpg"

    with pytest.raises(PageError) as caught:
        _complete(completion)
    assert "不是同一张图" in str(caught.value)
    assert completion.uploads == [], "身份对不上时不许上传、不许覆盖"


def test_same_name_without_batch_receipt_fails_and_uploads_nothing(completion):
    _adopt_all(completion)
    completion.ledger.entries.clear()

    with pytest.raises(PageError) as caught:
        _complete(completion)
    assert "没有本批回执" in str(caught.value)
    assert completion.uploads == []

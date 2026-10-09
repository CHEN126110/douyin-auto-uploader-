# -*- coding: utf-8 -*-
"""假上传账本：让「账本验证同名命中」这条新政策在离线夹具里可测。

上传名=源文件名后，预扫命中要过「同名+同 sha256+同图」的账本验证才接受。
夹具里的卡片是手工摆的，没走过真上传——用它登记一条假回执即可。
"""
from types import SimpleNamespace


def install(monkeypatch, records):
    """登记假账本。records: {文件名: {'url': ..., 'picture_id': ...}}（可按名省略 sha）。

    返回假账本对象；lookup 语义与 `protocol_media.UploadLedger.lookup` 一致，
    并支持 `record`（DOM 路线上传成功后登记，供二次准备复用）。
    """
    from taobao_publish import protocol_media

    records = {name: dict(row) for name, row in records.items()}

    def lookup(identity):
        record = records.get(identity.get('name'))
        if record is None:
            return None
        sha = record.get('sha256')
        if sha and sha != identity.get('sha256'):
            return None
        return record

    def record(identity, receipt, folder_id=''):
        records[str(identity.get('name') or '')] = {
            'name': str(identity.get('name') or ''),
            'sha256': str(identity.get('sha256') or ''),
            'url': str(receipt.get('url') or ''),
            'picture_id': str(receipt.get('picture_id') or ''),
        }

    fake = SimpleNamespace(lookup=lookup, record=record)
    monkeypatch.setattr(protocol_media.UploadLedger, 'load', classmethod(lambda cls: fake))
    return fake

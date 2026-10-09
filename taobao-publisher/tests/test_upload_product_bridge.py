"""协议候选上传端到目录回执的交接；全部使用本地图片与内存传输端。"""
from dataclasses import replace
import hashlib
from pathlib import Path

from PIL import Image
import pytest

from taobao_publish.authorization import WriteAuthorization
from taobao_publish.media_manifest import (
    MediaBatchPreparationError, build_media_manifest, prepare_media_batch,
    snapshot_media_batch,
)
from taobao_publish.upload_api import UploadReceipt
from taobao_publish.upload_client import BatchUploadReport, make_upload_product


@pytest.fixture
def product(tmp_path):
    root = tmp_path / '原目录'
    for index, name in enumerate(('主图/同名.jpg', 'SKU/同名.jpg', '详情页/一组/详情.jpg')):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (220, 220), (30 * index, 60, 90)).save(path)
    return build_media_manifest(17, str(root))


class MemoryUploader:
    def __init__(self, fault=None):
        self.calls = []
        self.fault = fault

    def upload_batch(self, candidates, *, folder_id, authorization, progress=None):
        self.calls.append((folder_id, tuple(candidates)))
        receipts = tuple(UploadReceipt(candidate.name,
            'https://img.alicdn.com/imgextra/' + candidate.sha256 + '.jpg',
            folder_id=folder_id, picture_id=str(1000000000+len(self.calls)*100+index))
            for index,candidate in enumerate(candidates))
        if self.fault:
            return self.fault(folder_id, receipts)
        return BatchUploadReport(receipts=receipts, attempted=len(candidates))


def adapter(uploader, folders):
    def resolve(account, full_path):
        assert account == 'account-A'
        assert isinstance(full_path, tuple), '目录必须传完整路径，不能只传商品名'
        folders.append(full_path)
        return '/'.join(full_path)
    return make_upload_product(lambda account: uploader, folder_resolver=resolve,
                               authorization=WriteAuthorization.for_form_filling())


def test_uploaded_bytes_come_from_snapshots_and_each_subdirectory_has_its_own_id(product):
    uploader, folders = MemoryUploader(), []
    result = prepare_media_batch([product], adapter(uploader, folders), account_profile='account-A',
                                 authorization=WriteAuthorization.for_form_filling())
    assert folders == [(product.folder_name,)] + [
        (product.folder_name, *Path(name).parts) for name in product.directories]
    assert {folder for folder, _ in uploader.calls} == {
        product.folder_name + '/' + str(Path(image.relative_path).parent).replace('\\', '/')
        for image in product.images}
    for _, candidates in uploader.calls:
        for candidate in candidates:
            assert not Path(candidate.path).is_relative_to(product.product_dir)
    assert {receipt.relative_path for receipt in result[0].receipts} == {
        image.relative_path for image in product.images}
    assert [receipt.name for receipt in result[0].receipts].count('同名.jpg') == 2
    assert len({receipt.url for receipt in result[0].receipts}) == len(product.images)
    assert all(receipt.picture_id for receipt in result[0].receipts), '交接必须保留上传返回的图片 ID'


def test_snapshot_tampering_is_found_before_cloud_directories_or_uploads(product):
    uploader, folders = MemoryUploader(), []
    upload = adapter(uploader, folders)
    with snapshot_media_batch([product]) as snapshots:
        Image.new('RGB', (220, 220), 'yellow').save(Path(snapshots[0]) / product.images[0].relative_path)
        with pytest.raises(ValueError, match='快照'):
            upload(product, snapshots[0], 'account-A')
    assert folders == [] and uploader.calls == []


def test_distinct_directories_cannot_resolve_to_one_cloud_directory(product):
    uploader = MemoryUploader()
    upload = make_upload_product(lambda account: uploader, folder_resolver=lambda *_: 'same-id',
                                 authorization=WriteAuthorization.for_form_filling())
    with pytest.raises(MediaBatchPreparationError, match='目录'):
        prepare_media_batch([product], upload, account_profile='account-A',
                            authorization=WriteAuthorization.for_form_filling())
    assert uploader.calls == []


@pytest.mark.parametrize('bad', ['missing', 'duplicate', 'wrong_folder', 'renamed'])
def test_bad_upload_receipt_is_not_reconstructed_from_the_local_manifest(product, bad):
    def fault(folder, receipts):
        if bad == 'missing': receipts = ()
        if bad == 'duplicate': receipts = receipts + receipts
        if bad == 'wrong_folder': receipts = tuple(replace(row, folder_id='unrelated') for row in receipts)
        if bad == 'renamed': receipts = tuple(replace(row, name='改名.jpg') for row in receipts)
        return BatchUploadReport(receipts=receipts, attempted=1)
    uploader = MemoryUploader(fault)
    with pytest.raises(MediaBatchPreparationError, match='回执'):
        prepare_media_batch([product], adapter(uploader, []), account_profile='account-A',
                            authorization=WriteAuthorization.for_form_filling())
    assert len(uploader.calls) == 1


def test_failed_later_directory_retains_partial_product_receipts(product):
    def fault(folder, receipts):
        if folder.endswith('/主图'):
            return BatchUploadReport(failed=({'name': '同名.jpg', 'message': '测试平台拒绝'},), attempted=1)
        return BatchUploadReport(receipts=receipts, attempted=len(receipts))
    uploader = MemoryUploader(fault)
    with pytest.raises(MediaBatchPreparationError) as error:
        prepare_media_batch([product], adapter(uploader, []), account_profile='account-A',
                            authorization=WriteAuthorization.for_form_filling())
    partial = error.value.partial_product
    assert partial.manifest == product and partial.account_profile == 'account-A'
    assert [row.relative_path for row in partial.receipts] == ['SKU/同名.jpg']
    assert all(not folder.endswith('一组') for folder, _ in uploader.calls)

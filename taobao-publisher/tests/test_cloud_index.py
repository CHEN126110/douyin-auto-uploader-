"""云端索引判定层的离线对账测试：复用 / 上传 / 歧义 / 阻塞。

不联网、不碰 DOM、不读磁盘：本地清单用真实 ``ProductMediaManifest``，
云端清单用 ``find_product_images`` / ``read_directory_files`` 那种 mapping。
"""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from taobao_publish.cloud_index import (
    CloudFile, CloudListing, ReuseCandidate, index_cloud_media,
)
from taobao_publish.media_manifest import (
    ProductMediaManifest, SourceImage, UploadedImageReceipt,
)

FOLDER = '远端商品'
DIGEST_A = 'a' * 64
DIGEST_B = 'b' * 64
DIGEST_C = 'c' * 64
MAIN_URL = 'https://img.example.invalid/main.jpg'
SKU_URL = 'https://img.example.invalid/sku.jpg'


def manifest(*images, folder_name=FOLDER):
    """(相对路径, sha256, size) 三元组 → 真实 ProductMediaManifest（不落盘、不读文件）。"""

    return ProductMediaManifest(19, 'C:/商品/' + folder_name, folder_name, (),
        tuple(SourceImage(*image) for image in images), 'digest')


def receipt(name, directory, url, *, page=None, folder_name=FOLDER):
    """``find_product_images`` 那种回执：目录是含图库根层的完整路径。"""

    entry = {'name': name, 'url': url, 'folder_path': ['全部图片', folder_name, *directory]}
    if page is not None:
        entry['page_number'] = page
    return entry


def listing(*files, folder_name=FOLDER, complete=True):
    return CloudListing(folder_name, tuple(files), complete)


def paths(items):
    return [item.relative_path for item in items]


def test_exact_name_and_directory_reuses_the_cloud_receipt_in_manifest_order():
    plan = manifest(('主图/主图_01.jpg', DIGEST_A, 1024), ('详情页/详情_01.jpg', DIGEST_B, 2048))
    cloud = listing(
        receipt('主图_01.jpg', ['主图'], MAIN_URL, page=2),
        receipt('详情_01.jpg', ['详情页'], SKU_URL, page=1),
        receipt('无关.jpg', ['主图'], 'https://img.example.invalid/other.jpg'),
    )
    decision = index_cloud_media(plan, cloud)
    assert decision.is_blocked is False and decision.blocked == ()
    assert decision.upload == () and decision.ambiguous == ()
    assert decision.reuse == (
        ReuseCandidate('主图/主图_01.jpg', '主图_01.jpg', MAIN_URL,
                       ('全部图片', FOLDER, '主图'), DIGEST_A, 2, False),
        ReuseCandidate('详情页/详情_01.jpg', '详情_01.jpg', SKU_URL,
                       ('全部图片', FOLDER, '详情页'), DIGEST_B, 1, False),
    )


def test_cloudfile_instances_and_declared_digests_verify_content():
    plan = manifest(('主图/a.jpg', DIGEST_A, 10))
    cloud = listing(CloudFile('a.jpg', MAIN_URL, ('全部图片', FOLDER, '主图'), 3, DIGEST_A))
    decision = index_cloud_media(plan, cloud)
    assert decision.reuse == (ReuseCandidate('主图/a.jpg', 'a.jpg', MAIN_URL,
        ('全部图片', FOLDER, '主图'), DIGEST_A, 3, True),)
    assert decision.upload == () and decision.ambiguous == ()


def test_empty_but_complete_listing_uploads_everything():
    plan = manifest(('主图/a.jpg', DIGEST_A, 10), ('SKU/b.jpg', DIGEST_B, 20))
    decision = index_cloud_media(plan, listing())
    assert decision.is_blocked is False
    assert decision.reuse == () and decision.ambiguous == ()
    assert paths(decision.upload) == ['主图/a.jpg', 'SKU/b.jpg']
    assert [task.folder_path for task in decision.upload] == [(FOLDER, '主图'), (FOLDER, 'SKU')]
    assert [task.size for task in decision.upload] == [10, 20]
    assert all('必须上传' in task.reason for task in decision.upload)
    assert decision.missing == decision.upload


@pytest.mark.parametrize('complete', [False, None])
def test_listing_that_is_not_complete_blocks_without_deciding_anything(complete):
    plan = manifest(('主图/a.jpg', DIGEST_A, 10))
    cloud = listing(receipt('a.jpg', ['主图'], MAIN_URL), complete=complete)
    decision = index_cloud_media(plan, cloud)
    assert decision.is_blocked is True
    assert decision.reuse == () and decision.upload == () and decision.ambiguous == ()
    assert [item.code for item in decision.blocked] == ['cloud_listing_incomplete']
    assert '完整' in decision.blocked_reasons[0]


def test_listing_for_another_product_root_blocks_everything():
    plan = manifest(('主图/a.jpg', DIGEST_A, 10))
    cloud = listing(receipt('a.jpg', ['主图'], MAIN_URL, folder_name='别的商品'), folder_name='别的商品')
    decision = index_cloud_media(plan, cloud)
    assert decision.is_blocked is True and not decision.reuse
    assert [item.code for item in decision.blocked] == ['cloud_root_mismatch']
    assert FOLDER in decision.blocked[0].reason and '别的商品' in decision.blocked[0].reason


def test_listing_without_a_root_name_blocks():
    plan = manifest(('主图/a.jpg', DIGEST_A, 10))
    decision = index_cloud_media(plan, listing(folder_name=''))
    assert [item.code for item in decision.blocked] == ['cloud_root_unrecognized']
    assert decision.reuse == () and decision.upload == () and decision.ambiguous == ()


def test_entry_from_another_product_blocks_and_is_not_silently_ignored():
    plan = manifest(('主图/a.jpg', DIGEST_A, 10))
    cloud = listing({'name': 'a.jpg', 'url': MAIN_URL, 'folder_path': ['全部图片', '别的商品', '主图']})
    decision = index_cloud_media(plan, cloud)
    assert [item.code for item in decision.blocked] == ['cloud_entry_directory_unrecognized']
    assert '无法归属到本商品' in decision.blocked[0].reason
    assert decision.reuse == () and decision.upload == () and decision.ambiguous == ()


@pytest.mark.parametrize('folder_path', [None, [], ['全部图片', FOLDER, ''], '全部图片/远端商品/主图'])
def test_missing_or_unusable_entry_directory_blocks(folder_path):
    plan = manifest(('主图/a.jpg', DIGEST_A, 10))
    cloud = listing({'name': 'a.jpg', 'url': MAIN_URL, 'folder_path': folder_path})
    decision = index_cloud_media(plan, cloud)
    assert [item.code for item in decision.blocked] == ['cloud_entry_directory_unrecognized']
    assert decision.reuse == () and decision.upload == () and decision.ambiguous == ()


@pytest.mark.parametrize('entry, code', [
    ('主图/a.jpg', 'cloud_entry_unreadable'),
    ({'url': MAIN_URL, 'folder_path': ['全部图片', FOLDER, '主图']}, 'cloud_entry_without_name'),
    ({'name': ' ', 'url': MAIN_URL, 'folder_path': ['全部图片', FOLDER, '主图']}, 'cloud_entry_without_name'),
    ({'name': 'a.jpg', 'url': 5, 'folder_path': ['全部图片', FOLDER, '主图']}, 'cloud_entry_unreadable'),
    ({'name': 'a.jpg', 'url': MAIN_URL, 'folder_path': ['全部图片', FOLDER, '主图'], 'page': 0},
     'cloud_entry_page_invalid'),
    ({'name': 'a.jpg', 'url': MAIN_URL, 'folder_path': ['全部图片', FOLDER, '主图'], 'sha256': 'zz'},
     'cloud_entry_digest_invalid'),
])
def test_structurally_broken_entries_block_the_whole_decision(entry, code):
    plan = manifest(('主图/a.jpg', DIGEST_A, 10))
    decision = index_cloud_media(plan, listing(entry))
    assert [item.code for item in decision.blocked] == [code]
    assert decision.reuse == () and decision.upload == () and decision.ambiguous == ()


@pytest.mark.parametrize('url', [
    'http://img.example.invalid/a.jpg',
    'https://user:pass@img.example.invalid/a.jpg',
    'https://user@img.example.invalid/a.jpg',
    'https:///a.jpg',
    'img.example.invalid/a.jpg',
    '',
])
def test_url_that_is_missing_or_not_a_clean_https_address_is_ambiguous(url):
    plan = manifest(('主图/a.jpg', DIGEST_A, 10))
    cloud = listing(receipt('a.jpg', ['主图'], url))
    decision = index_cloud_media(plan, cloud)
    assert decision.reuse == () and decision.upload == ()
    assert [item.code for item in decision.ambiguous] == ['url_missing_or_insecure']
    assert 'HTTPS' in decision.ambiguous[0].reason


def test_same_name_with_two_different_urls_is_ambiguous():
    plan = manifest(('主图/a.jpg', DIGEST_A, 10))
    cloud = listing(receipt('a.jpg', ['主图'], MAIN_URL), receipt('a.jpg', ['主图'], SKU_URL))
    decision = index_cloud_media(plan, cloud)
    assert decision.reuse == () and decision.upload == ()
    assert [item.code for item in decision.ambiguous] == ['same_name_different_url']
    assert '不自动挑第一个' in decision.ambiguous[0].reason
    assert len(decision.ambiguous[0].candidates) == 2


def test_same_name_multiple_copies_in_the_expected_directory_is_ambiguous():
    plan = manifest(('主图/a.jpg', DIGEST_A, 10))
    cloud = listing(receipt('a.jpg', ['主图'], MAIN_URL), receipt('a.jpg', ['主图'], MAIN_URL))
    decision = index_cloud_media(plan, cloud)
    assert decision.reuse == () and decision.upload == ()
    assert [item.code for item in decision.ambiguous] == ['same_name_multiple_copies']
    assert '同名副本有 2 份' in decision.ambiguous[0].reason


def test_same_name_in_another_directory_is_ambiguous():
    plan = manifest(('主图/a.jpg', DIGEST_A, 10))
    cloud = listing(receipt('a.jpg', ['SKU'], SKU_URL))
    decision = index_cloud_media(plan, cloud)
    assert decision.reuse == () and decision.upload == ()
    assert [item.code for item in decision.ambiguous] == ['directory_mismatch']
    assert 'SKU' in decision.ambiguous[0].reason and '主图' in decision.ambiguous[0].reason


def test_same_url_in_another_directory_does_not_block_the_exact_match():
    """同名副本在不同目录但地址相同：按精确目录取唯一命中，不误判为歧义。"""

    plan = manifest(('主图/a.jpg', DIGEST_A, 10))
    cloud = listing(receipt('a.jpg', ['主图'], MAIN_URL), receipt('a.jpg', ['SKU'], MAIN_URL))
    decision = index_cloud_media(plan, cloud)
    assert decision.ambiguous == () and decision.upload == ()
    assert decision.reuse == (ReuseCandidate('主图/a.jpg', 'a.jpg', MAIN_URL,
        ('全部图片', FOLDER, '主图'), DIGEST_A, None, False),)


def test_changed_local_content_is_ambiguous_and_not_silently_reused():
    """本地内容变了（sha256 与历史回执不同）：既不静默复用，也不当确定性上传。"""

    plan = manifest(('主图/a.jpg', DIGEST_B, 10))
    history = [UploadedImageReceipt('主图/a.jpg', 'a.jpg', (FOLDER, '主图'),
        'https://img.example.invalid/old.jpg', DIGEST_A)]
    decision = index_cloud_media(plan, listing(receipt('a.jpg', ['主图'], MAIN_URL)), history=history)
    assert decision.reuse == () and decision.upload == ()
    assert [item.code for item in decision.ambiguous] == ['content_changed']
    assert '不静默复用' in decision.ambiguous[0].reason
    assert decision.ambiguous[0].candidates[0].url == MAIN_URL


def test_history_with_the_same_digest_verifies_content_even_if_the_url_moved():
    plan = manifest(('主图/a.jpg', DIGEST_A, 10))
    history = [{'relative_path': '主图/a.jpg', 'sha256': DIGEST_A.upper()}]
    decision = index_cloud_media(plan, listing(receipt('a.jpg', ['主图'], MAIN_URL)), history=history)
    assert decision.reuse[0].content_verified is True
    assert decision.reuse[0].url == MAIN_URL


def test_conflicting_history_digests_for_one_path_are_ambiguous():
    plan = manifest(('主图/a.jpg', DIGEST_A, 10))
    history = [UploadedImageReceipt('主图/a.jpg', 'a.jpg', (FOLDER, '主图'), MAIN_URL, DIGEST_A),
               UploadedImageReceipt('主图/a.jpg', 'a.jpg', (FOLDER, '主图'), SKU_URL, DIGEST_B)]
    decision = index_cloud_media(plan, listing(receipt('a.jpg', ['主图'], MAIN_URL)), history=history)
    assert decision.reuse == () and decision.upload == ()
    assert [item.code for item in decision.ambiguous] == ['content_history_conflict']
    assert '多个不同内容摘要' in decision.ambiguous[0].reason


def test_cloud_digest_mismatch_is_ambiguous_but_a_match_verifies_content():
    plan = manifest(('主图/a.jpg', DIGEST_A, 10))
    mismatched = {'name': 'a.jpg', 'url': MAIN_URL,
                  'folder_path': ['全部图片', FOLDER, '主图'], 'sha256': DIGEST_B}
    decision = index_cloud_media(plan, listing(mismatched))
    assert decision.reuse == () and decision.upload == ()
    assert [item.code for item in decision.ambiguous] == ['cloud_content_mismatch']
    assert '不是同一份内容' in decision.ambiguous[0].reason

    matched = dict(mismatched, sha256=DIGEST_A.upper())
    decision = index_cloud_media(plan, listing(matched))
    assert decision.reuse[0].content_verified is True
    assert decision.reuse[0].sha256 == DIGEST_A


def test_cloud_digest_takes_precedence_over_stale_history():
    """云端条目自带当下内容摘要时以它为准；历史回执只是过去的事实。"""

    plan = manifest(('主图/a.jpg', DIGEST_B, 10))
    history = [UploadedImageReceipt('主图/a.jpg', 'a.jpg', (FOLDER, '主图'), SKU_URL, DIGEST_A)]
    cloud = listing({'name': 'a.jpg', 'url': MAIN_URL,
                     'folder_path': ['全部图片', FOLDER, '主图'], 'sha256': DIGEST_B})
    decision = index_cloud_media(plan, cloud, history=history)
    assert decision.ambiguous == () and decision.upload == ()
    assert decision.reuse[0].content_verified is True


@pytest.mark.parametrize('cloud_name', ['主图_01 (1).jpg', '主图_1.jpg', '主图_01.JPG', '主图_01.jpg '])
def test_names_that_only_look_alike_are_never_matched(cloud_name):
    plan = manifest(('主图/主图_01.jpg', DIGEST_A, 10))
    cloud = listing(receipt(cloud_name, ['主图'], MAIN_URL))
    decision = index_cloud_media(plan, cloud)
    assert decision.reuse == () and decision.ambiguous == ()
    assert paths(decision.upload) == ['主图/主图_01.jpg']
    assert '没有同名文件' in decision.upload[0].reason


def test_mixed_listing_decides_every_local_image_exactly_once_and_keeps_order():
    plan = manifest(('主图/主图_01.jpg', DIGEST_A, 10), ('SKU/规格_白.jpg', DIGEST_B, 20),
                    ('详情页/详情_01.jpg', DIGEST_C, 30), ('主图/主图_02.jpg', DIGEST_A, 40))
    cloud = listing(
        receipt('主图_01.jpg', ['主图'], MAIN_URL, page=1),
        receipt('规格_白.jpg', ['SKU'], SKU_URL),
        receipt('详情_01.jpg', ['详情页'], 'https://img.example.invalid/detail.jpg'),
        receipt('详情_01.jpg', ['详情页'], 'https://img.example.invalid/detail-2.jpg'),
    )
    decision = index_cloud_media(plan, cloud)
    assert decision.is_blocked is False
    assert paths(decision.reuse) == ['主图/主图_01.jpg', 'SKU/规格_白.jpg']
    assert paths(decision.upload) == ['主图/主图_02.jpg']
    assert paths(decision.ambiguous) == ['详情页/详情_01.jpg']
    assert decision.reuse[1].page is None
    covered = paths(decision.reuse) + paths(decision.upload) + paths(decision.ambiguous)
    assert sorted(covered) == sorted(image.relative_path for image in plan.images)


def test_image_at_the_product_root_matches_a_root_level_entry():
    """商品根目录下的图片：预期目录只有根目录名，根层条目要精确命中，子目录条目不算。"""

    plan = manifest(('主图.jpg', DIGEST_A, 10))
    cloud = listing({'name': '主图.jpg', 'url': MAIN_URL, 'folder_path': ['全部图片', FOLDER]})
    decision = index_cloud_media(plan, cloud)
    assert decision.ambiguous == () and decision.upload == ()
    assert decision.reuse == (ReuseCandidate('主图.jpg', '主图.jpg', MAIN_URL,
        ('全部图片', FOLDER), DIGEST_A, None, False),)

    in_subdirectory = listing(receipt('主图.jpg', ['主图'], MAIN_URL))
    decision = index_cloud_media(plan, in_subdirectory)
    assert decision.reuse == () and decision.upload == ()
    assert [item.code for item in decision.ambiguous] == ['directory_mismatch']


def test_a_list_of_cloud_files_is_accepted_like_a_tuple():
    plan = manifest(('主图/a.jpg', DIGEST_A, 10))
    cloud = CloudListing(FOLDER, [receipt('a.jpg', ['主图'], MAIN_URL)], True)
    decision = index_cloud_media(plan, cloud)
    assert paths(decision.reuse) == ['主图/a.jpg']


def test_tuple_and_mapping_local_image_forms_are_supported():
    plan = SimpleNamespace(folder_name=FOLDER, images=[
        ('主图/a.jpg', DIGEST_A, 10),
        {'relative_path': 'SKU/b.jpg', 'sha256': DIGEST_B, 'size': 20},
    ])
    cloud = listing(receipt('a.jpg', ['主图'], MAIN_URL))
    decision = index_cloud_media(plan, cloud)
    assert paths(decision.reuse) == ['主图/a.jpg']
    assert paths(decision.upload) == ['SKU/b.jpg']
    assert decision.upload[0].folder_path == (FOLDER, 'SKU')


@pytest.mark.parametrize('relative_path', ['/主图/a.jpg', '主图\\a.jpg', '../a.jpg',
                                           '主图//a.jpg', '主图/./a.jpg', '主图/a.jpg/', ''])
def test_unsafe_local_relative_paths_are_rejected(relative_path):
    with pytest.raises(ValueError, match='POSIX'):
        index_cloud_media(manifest((relative_path, DIGEST_A, 10)), listing())


@pytest.mark.parametrize('image, message', [
    (('主图/a.jpg', 'abc', 10), 'sha256'),
    (('主图/a.jpg', DIGEST_A, -1), '文件大小'),
    (('主图/a.jpg', DIGEST_A, '10'), '文件大小'),
])
def test_local_digest_and_size_must_be_explicit(image, message):
    with pytest.raises(ValueError, match=message):
        index_cloud_media(manifest(image), listing())


def test_a_plain_mapping_is_not_accepted_as_a_listing():
    with pytest.raises(ValueError, match='CloudListing'):
        index_cloud_media(manifest(('主图/a.jpg', DIGEST_A, 10)),
                          {'folder_name': FOLDER, 'files': [], 'complete': True})


def test_bad_history_entries_are_rejected_instead_of_ignored():
    plan = manifest(('主图/a.jpg', DIGEST_A, 10))
    for history in ([{'relative_path': '/主图/a.jpg', 'sha256': DIGEST_A}],
                    [{'relative_path': '主图/a.jpg', 'sha256': 'nope'}]):
        with pytest.raises(ValueError, match='历史回执'):
            index_cloud_media(plan, listing(receipt('a.jpg', ['主图'], MAIN_URL)), history=history)


def test_module_stays_pure_without_network_dom_or_filesystem():
    """结构体检：只允许纯标准库导入，没有网络 / DOM / 文件系统入口。"""

    source = (Path(__file__).resolve().parents[1] / 'taobao_publish' / 'cloud_index.py').read_text(encoding='utf-8')
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or '')
    assert imported <= {'__future__', 'collections.abc', 'dataclasses', 'pathlib', 'typing', 'urllib.parse'}
    for forbidden in ('socket', 'requests', 'subprocess', 'urllib.request', 'evaluate(', 'open('):
        assert forbidden not in source

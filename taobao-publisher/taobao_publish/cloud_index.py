# -*- coding: utf-8 -*-
"""图片空间去重索引：把云端文件清单与本地素材清单对账，判定复用 / 上传 / 歧义 / 阻塞。

定位
====

本模块是**纯函数判定层**：不联网、不读磁盘、不碰 DOM、不引入第三方依赖。
云端清单由 ``media_library`` 的 DOM 路线取好（``find_product_images`` 的 ``receipts``、
``read_directory_files`` 的 ``files``），本地清单由 ``media_manifest.ProductMediaManifest``
给出；这里只做**精确对账**——不补默认值、不猜匹配、不自动重传。

输入
====

``manifest``
    本地素材清单，需要 ``folder_name``（该商品在图片空间的根目录名）与 ``images``
    （相对路径 + sha256 + size）。既可以是 ``ProductMediaManifest``，也可以是任何提供
    这两个属性的对象；``images`` 每项可以是 ``media_manifest.SourceImage``、含有同样三个
    键的 mapping，或 ``(相对路径, sha256, size)`` 三元组。相对路径必须是规范 POSIX 形式
    （``主图/800/x.jpg``）：绝对路径、反斜杠、``a//b``、``a/./b``、``a/../b`` 一律
    ``ValueError``，不会被静默改写。
``listing``
    ``CloudListing``：``folder_name`` + 本商品子树内的文件条目 + ``complete``。
    条目既可以是 ``CloudFile``，也可以是 ``find_product_images`` / ``read_directory_files``
    那种 mapping：``name``（必填）、``url``、``folder_path``（云端完整目录路径，序列）、
    可选 ``page`` / ``page_number`` 与 ``sha256``。清单必须已经限定在本商品子树内。
``history``
    可选，上一次上传的 ``UploadedImageReceipt`` 序列（或含 ``relative_path`` / ``sha256``
    的 mapping），用来识别「本地内容已变化」。只按 ``relative_path`` + ``sha256`` 使用，
    不假设跨会话 URL 稳定。

判定规则（逐条可测）
====================

R1  复用候选必须三条同时成立：云端文件名 == 本地文件名（逐字符相等，不做大小写折叠、
    前缀/后缀或「名字像」的匹配）；云端目录归属 == 本地预期目录（逐段相等）；云端 URL
    是 https、有主机名、不带用户名密码。
R2  云端目录归属以 ``listing.folder_name`` 为锚点：从锚点开始的整段路径（含商品根目录名）
    就是归属；锚点之前（例如图库根层「全部图片」）只是容器层，不参与判定。锚点在路径里
    出现 0 次或多次都判为目录不可识别，整体 blocked。不做前缀/后缀兜底，也不静默丢弃
    别的商品条目。
R3  本地预期目录 = ``(folder_name, *PurePosixPath(relative_path).parent.parts)``。
R4  同名条目里出现 URL 缺失 / 非文本 / 不是 https / 带凭据 → ``ambiguous``（不猜测、
    也不因为另一份地址好看就挑它）。
R5  同名但云端 URL 有两个不同值 → ``ambiguous``，不自动挑第一个（与
    ``find_product_images`` 对「同名但图片地址不同」直接报错的既有策略一致）。
R6  同名同目录出现多份 → ``ambiguous``，不挑第一份。
R7  同名但目录归属不符 → ``ambiguous``，理由里同时给出云端目录与预期目录。
R8  本地内容变了（sha256 与历史回执不同）而云端同名 → ``ambiguous``，**绝不静默复用**。
    选 ``ambiguous`` 而不是 ``upload`` 的理由：云端导出清单只有名字/地址/目录，读不到
    云端对象的真实内容摘要；同名文件传到平台上究竟是**覆盖**还是**改名保留**，本子项目
    没有实证（``unknown``）。两条路都无法证明时把决定权交回调用方，符合「宁可拒绝执行
    也不悄悄产出错误结果」。只有摘要能证明一致时才复用，并在回执里标
    ``content_verified=True``：云端条目自带 ``sha256`` 且与本地一致，或历史回执同 sha。
    两者都在时**以云端条目自带的摘要为准**（它描述云端对象当下的内容）。
R9  云端清单不完整（``complete`` 不为 ``True``，含分页未读完、子树未展开、完整性未知）
    → 整体 blocked，``reuse`` / ``upload`` / ``ambiguous`` 全为空。不完整的清单既不能
    证明「云端已有」，也不能证明「必须上传」，所以这里什么都不判。
R10 云端为空且清单完整 → 本地全部 ``upload``；这是合法状态，不是错误。
R11 条目不可读、缺文件名、缺目录、条目 sha256 / 页码非法、云端根目录缺失或与本地不一致
    → blocked，且**不做部分判定**（一个坏条目不放大成整批结果）。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class CloudFile:
    """云端清单里的一条文件记录。

    ``folder_path`` 是云端完整目录路径（原样保留，含「全部图片」这类容器层）；
    它只作为复用回执与理由展示用，归属判定见 ``index_cloud_media`` 的 R2。
    """

    name: str
    url: str
    folder_path: tuple[str, ...]
    page: int | None = None
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class CloudListing:
    """某商品在图片空间的文件清单；``complete`` 必须明确为 ``True`` 才参与判定。"""

    folder_name: str
    files: tuple[CloudFile | Mapping[str, Any], ...] = ()
    complete: bool = True


@dataclass(frozen=True, slots=True)
class ReuseCandidate:
    """可以直接复用云端回执的本地图片（本地内容与云端对象的内容身份见 ``content_verified``）。"""

    relative_path: str
    name: str
    url: str
    folder_path: tuple[str, ...]
    sha256: str
    page: int | None = None
    content_verified: bool = False


@dataclass(frozen=True, slots=True)
class UploadTask:
    """云端确实没有、必须上传的本地图片；``folder_path`` 是本地预期云端目录。"""

    relative_path: str
    name: str
    sha256: str
    size: int
    folder_path: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class AmbiguousItem:
    """无法唯一判定的本地图片；``code`` 是机器可读的歧义码，``reason`` 是中文原因。"""

    relative_path: str
    name: str
    code: str
    reason: str
    candidates: tuple[CloudFile, ...] = ()


@dataclass(frozen=True, slots=True)
class BlockedItem:
    """判定根本无法进行的原因；``code`` 是机器可读的阻塞码，``reason`` 是中文原因。"""

    code: str
    reason: str


@dataclass(frozen=True, slots=True)
class CloudIndexDecision:
    """一次对账的完整结论；blocked 非空时其余三个列表必为空。"""

    reuse: tuple[ReuseCandidate, ...] = ()
    upload: tuple[UploadTask, ...] = ()
    ambiguous: tuple[AmbiguousItem, ...] = ()
    blocked: tuple[BlockedItem, ...] = ()

    @property
    def is_blocked(self) -> bool:
        return bool(self.blocked)

    @property
    def missing(self) -> tuple[UploadTask, ...]:
        """``upload`` 的别名：云端清单里确实没有、必须上传的项。"""

        return self.upload

    @property
    def blocked_reasons(self) -> tuple[str, ...]:
        return tuple(item.reason for item in self.blocked)


_HEX_DIGITS = frozenset('0123456789abcdefABCDEF')


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in _HEX_DIGITS for char in value)


def _is_relative_posix_path(value: object) -> bool:
    """只接受规范 POSIX 相对路径；不做任何静默改写。"""

    if not isinstance(value, str) or not value or '\\' in value:
        return False
    path = PurePosixPath(value)
    return (not path.is_absolute() and bool(path.parts)
            and '..' not in path.parts and str(path) == value)


def _read_local_image(image: object, index: int) -> tuple[str, str, int]:
    if isinstance(image, Mapping):
        relative_path, digest, size = image.get('relative_path'), image.get('sha256'), image.get('size')
    elif isinstance(image, (tuple, list)) and len(image) == 3:
        relative_path, digest, size = image
    else:
        relative_path = getattr(image, 'relative_path', None)
        digest = getattr(image, 'sha256', None)
        size = getattr(image, 'size', None)
    if not _is_relative_posix_path(relative_path):
        raise ValueError('第 {} 项本地素材的相对路径不是明确的 POSIX 相对路径：{!r}'.format(index, relative_path))
    if not _is_digest(digest):
        raise ValueError('第 {} 项本地素材的 sha256 不是 64 位十六进制摘要：{}'.format(index, relative_path))
    if type(size) is not int or size < 0:
        raise ValueError('第 {} 项本地素材的文件大小不是非负整数：{}'.format(index, relative_path))
    return relative_path, digest.lower(), size


def _read_local_images(manifest: object) -> tuple[str, tuple[tuple[str, str, str, int], ...]]:
    folder_name = getattr(manifest, 'folder_name', None)
    images = getattr(manifest, 'images', None)
    if not isinstance(folder_name, str) or not folder_name.strip():
        raise ValueError('本地素材清单缺少商品在图片空间的目录名称')
    if images is None:
        raise ValueError('本地素材清单缺少图片序列')
    result = []
    for index, image in enumerate(images, 1):
        relative_path, digest, size = _read_local_image(image, index)
        result.append((relative_path, PurePosixPath(relative_path).name, digest, size))
    return folder_name, tuple(result)


def _usable_url(url: object) -> bool:
    """与 ``page.py`` 的素材回执校验同一口径：https、有主机名、不带凭据。"""

    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password


def _anchored_directory(folder_name: str, folder_path: tuple[str, ...]) -> tuple[str, ...] | None:
    """把云端完整目录路径锚定到本商品根目录，返回含根目录名的归属路径。

    锚点（``folder_name``）出现 0 次或多次都无法归属，返回 ``None``；
    锚点之前的层级（如「全部图片」这类图库容器）不参与判定。
    """

    if folder_path.count(folder_name) != 1:
        return None
    return tuple(folder_path[folder_path.index(folder_name):])


def _display_directory(parts: tuple[str, ...]) -> str:
    return '/'.join(parts) if parts else '（商品根目录）'


def _dedupe(items: list[BlockedItem]) -> tuple[BlockedItem, ...]:
    seen, result = set(), []
    for item in items:
        key = (item.code, item.reason)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return tuple(result)


def _listing_blockers(listing: CloudListing, folder_name: str) -> tuple[BlockedItem, ...]:
    blocked = []
    if listing.complete is not True:
        blocked.append(BlockedItem('cloud_listing_incomplete',
            '云端文件清单未标记为完整（complete 不为 True，含分页未读完或子树未展开），不能把它当作全量索引'))
    root = listing.folder_name
    if not isinstance(root, str) or not root.strip():
        blocked.append(BlockedItem('cloud_root_unrecognized',
            '云端清单没有可用的商品根目录名，无法确定文件归属'))
    elif root != folder_name:
        blocked.append(BlockedItem('cloud_root_mismatch',
            '云端清单的商品根目录（{}）与本地预期（{}）不一致，不能互相复用'.format(root, folder_name)))
    return tuple(blocked)


def _read_cloud_file(raw: object, folder_name: str) -> tuple[CloudFile | None, BlockedItem | None]:
    if isinstance(raw, CloudFile):
        name, url, folder_path, page, digest = raw.name, raw.url, raw.folder_path, raw.page, raw.sha256
    elif isinstance(raw, Mapping):
        name = raw.get('name')
        url = raw.get('url')
        folder_path = raw.get('folder_path')
        page = raw.get('page', raw.get('page_number'))
        digest = raw.get('sha256')
    else:
        return None, BlockedItem('cloud_entry_unreadable',
            '云端清单条目既不是 CloudFile 也不是映射，无法建立文件索引')
    if not isinstance(name, str) or not name.strip():
        return None, BlockedItem('cloud_entry_without_name',
            '云端清单有条目缺少文件名，无法与本地素材对账')
    if url is None:
        url = ''
    elif not isinstance(url, str):
        return None, BlockedItem('cloud_entry_unreadable', '云端清单条目的地址不是文本：' + name)
    if (not isinstance(folder_path, (tuple, list)) or not folder_path
            or any(not isinstance(part, str) or not part.strip() for part in folder_path)):
        return None, BlockedItem('cloud_entry_directory_unrecognized',
            '云端条目缺少明确的目录路径：' + name)
    folder_path = tuple(folder_path)
    if folder_path.count(folder_name) != 1:
        return None, BlockedItem('cloud_entry_directory_unrecognized',
            '云端条目的目录无法归属到本商品（{}）：{}'.format(_display_directory(folder_path), name))
    if page is not None and (type(page) is not int or page < 1):
        return None, BlockedItem('cloud_entry_page_invalid',
            '云端条目的页码不是正整数：{}'.format(name))
    if digest is not None:
        if not _is_digest(digest):
            return None, BlockedItem('cloud_entry_digest_invalid',
                '云端条目的 sha256 不是 64 位十六进制摘要：{}'.format(name))
        digest = digest.lower()
    return CloudFile(name, url, folder_path, page, digest), None


def _read_cloud_files(listing: CloudListing) -> tuple[tuple[CloudFile, ...], tuple[BlockedItem, ...]]:
    entries, problems = [], []
    for raw in listing.files:
        entry, problem = _read_cloud_file(raw, listing.folder_name)
        if problem is not None:
            problems.append(problem)
        else:
            entries.append(entry)
    return tuple(entries), _dedupe(problems)


def _read_history(history: object) -> dict[str, tuple[str, ...]]:
    if history is None:
        return {}
    result: dict[str, list[str]] = {}
    for entry in history:
        if isinstance(entry, Mapping):
            relative_path, digest = entry.get('relative_path'), entry.get('sha256')
        else:
            relative_path = getattr(entry, 'relative_path', None)
            digest = getattr(entry, 'sha256', None)
        if not _is_relative_posix_path(relative_path):
            raise ValueError('历史回执缺少有效的 POSIX 相对路径：{!r}'.format(relative_path))
        if not _is_digest(digest):
            raise ValueError('历史回执缺少有效的 sha256：' + relative_path)
        values = result.setdefault(relative_path, [])
        if digest.lower() not in values:
            values.append(digest.lower())
    return {key: tuple(values) for key, values in result.items()}


def _decide(relative_path: str, name: str, digest: str, size: int, folder_name: str,
            expected: tuple[str, ...], cloud: tuple[CloudFile, ...],
            historical: dict[str, tuple[str, ...]]) -> ReuseCandidate | UploadTask | AmbiguousItem:
    candidates = tuple(entry for entry in cloud if entry.name == name)
    if not candidates:
        return UploadTask(relative_path, name, digest, size, expected,
            '云端清单没有同名文件（预期目录 {}），必须上传'.format(_display_directory(expected)))
    unusable = tuple(entry for entry in candidates if not _usable_url(entry.url))
    if unusable:
        return AmbiguousItem(relative_path, name, 'url_missing_or_insecure',
            '云端有同名文件但地址缺失或不是可用的 HTTPS 地址（{} 份），不能确认能否复用'.format(len(unusable)),
            unusable)
    addresses = {entry.url for entry in candidates}
    if len(addresses) > 1:
        return AmbiguousItem(relative_path, name, 'same_name_different_url',
            '云端同名文件有 {} 个不同地址，不自动挑第一个'.format(len(addresses)), candidates)
    matched = tuple(entry for entry in candidates
                    if _anchored_directory(folder_name, entry.folder_path) == expected)
    if not matched:
        where = '、'.join(dict.fromkeys(
            _display_directory(_anchored_directory(folder_name, entry.folder_path)) for entry in candidates))
        return AmbiguousItem(relative_path, name, 'directory_mismatch',
            '云端同名文件在其它目录（{}），预期目录 {} 没有，不能确认是同一份素材'.format(
                where, _display_directory(expected)), candidates)
    if len(matched) > 1:
        return AmbiguousItem(relative_path, name, 'same_name_multiple_copies',
            '云端预期目录 {} 下同名副本有 {} 份，无法唯一确定本批素材'.format(
                _display_directory(expected), len(matched)), matched)
    entry = matched[0]
    verified = False
    if entry.sha256 is not None:
        if entry.sha256 != digest:
            return AmbiguousItem(relative_path, name, 'cloud_content_mismatch',
                '云端同名文件的内容摘要与本地不一致（云端 {}…，本地 {}…），不是同一份内容'.format(
                    entry.sha256[:12], digest[:12]), (entry,))
        verified = True
    else:
        digests = historical.get(relative_path, ())
        if len(digests) > 1:
            return AmbiguousItem(relative_path, name, 'content_history_conflict',
                '历史回执对同一路径记录了多个不同内容摘要，无法确认云端内容一致', (entry,))
        if digests and digests[0] != digest:
            return AmbiguousItem(relative_path, name, 'content_changed',
                '本地内容已变化（sha256 与历史回执不同），云端同名文件不能证明是同一内容，不静默复用', (entry,))
        if digests:
            verified = True
    return ReuseCandidate(relative_path, name, entry.url, entry.folder_path, digest, entry.page, verified)


def index_cloud_media(manifest, listing: CloudListing, *, history=()) -> CloudIndexDecision:
    """对账本地素材清单与云端文件清单，判定复用 / 上传 / 歧义 / 阻塞。

    判定规则见模块 docstring 的 R1–R11。任何一条不成立都不会被兜底掩盖：
    要么进 ``ambiguous``（可判但无法唯一判定），要么进 ``blocked``（根本判不了）。
    """

    folder_name, images = _read_local_images(manifest)
    if not isinstance(listing, CloudListing):
        raise ValueError('云端清单必须是 CloudListing：' + type(listing).__name__)
    blocked = _listing_blockers(listing, folder_name)
    if blocked:
        return CloudIndexDecision(blocked=blocked)
    cloud, blocked = _read_cloud_files(listing)
    if blocked:
        return CloudIndexDecision(blocked=blocked)
    historical = _read_history(history)
    reuse, upload, ambiguous = [], [], []
    for relative_path, name, digest, size in images:
        expected = (folder_name, *PurePosixPath(relative_path).parts[:-1])
        item = _decide(relative_path, name, digest, size, folder_name, expected, cloud, historical)
        if isinstance(item, ReuseCandidate):
            reuse.append(item)
        elif isinstance(item, UploadTask):
            upload.append(item)
        else:
            ambiguous.append(item)
    return CloudIndexDecision(tuple(reuse), tuple(upload), tuple(ambiguous))

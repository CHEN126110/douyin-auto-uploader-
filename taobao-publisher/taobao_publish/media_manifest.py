# -*- coding: utf-8 -*-
"""两阶段素材交接：保留商品文件树，准备完成后供 DOM 按准确路径选图。

本模块不实现或猜测网页私有上传接口。上传端提供逐文件回执，填写端只消费
已绑定账户及这份源文件清单的回执；缺图、改名、改目录、内容变更均显式失败。
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from urllib.parse import urlsplit

from .local_source import SUPPORTED_IMAGE_SUFFIXES, _check_asset_path, natural_sort_key
from .authorization import WriteAuthorization
from .constants import WRITE_UPLOAD_IMAGE
from .errors import TaobaoPublishError


@dataclass(frozen=True, slots=True)
class SourceImage:
    relative_path: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class ProductMediaManifest:
    record_id: int
    product_dir: str
    folder_name: str
    directories: tuple[str, ...]
    images: tuple[SourceImage, ...]
    digest: str

    def source(self, relative_path: str) -> Path:
        if relative_path not in {image.relative_path for image in self.images}:
            raise ValueError('图片不在本批商品文件清单中')
        return _check_asset_path(Path(self.product_dir), Path(self.product_dir) / relative_path)


def _file_hash(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build_media_manifest(record_id: int, product_dir: str) -> ProductMediaManifest:
    """递归保留原始目录/文件名，非图片资料不进入图片上传清单。"""
    if type(record_id) is not int or record_id <= 0:
        raise ValueError('素材清单必须绑定有效商品编号')
    root = Path(product_dir)
    if not root.is_absolute() or not root.is_dir() or not root.name:
        raise ValueError('素材清单必须使用实际商品文件夹的完整路径')
    for ancestor in (root, *root.parents):
        if ancestor.is_symlink() or getattr(ancestor.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('商品目录不能经过符号链接或目录联接')
    root = root.resolve(strict=True)
    directories, images = [], []
    def visit(folder):
        for child in sorted(folder.iterdir(), key=lambda value: natural_sort_key(value.name)):
            _check_asset_path(root, child)
            relative = child.relative_to(root).as_posix()
            if child.is_dir():
                directories.append(relative)
                visit(child)
            elif child.is_file() and child.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES:
                before = child.stat()
                digest = _file_hash(child)
                from PIL import Image
                with Image.open(child) as image:
                    image.verify()
                after = child.stat()
                if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                    raise ValueError('建立素材清单时文件发生变化：' + relative)
                images.append(SourceImage(relative, digest, after.st_size))
    visit(root)
    if not images:
        raise ValueError('商品目录没有可上传的图片')
    identity = [record_id, root.name, directories, [(image.relative_path, image.sha256, image.size) for image in images]]
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    return ProductMediaManifest(record_id, str(root), root.name, tuple(directories), tuple(images), digest)


def build_batch_manifests(records) -> tuple[ProductMediaManifest, ...]:
    """所有商品先形成清单；同名顶层目录不自动加后缀或混在一个目录内。"""
    plans = tuple(build_media_manifest(record['id'], record['path']) for record in records)
    if not plans or len({plan.record_id for plan in plans}) != len(plans):
        raise ValueError('素材批次为空或包含重复商品')
    if len({plan.folder_name.casefold() for plan in plans}) != len(plans):
        raise ValueError('本批存在同名商品文件夹，不能在图片空间自动合并')
    return plans


def validate_media_manifest(plan: ProductMediaManifest) -> None:
    current = build_media_manifest(plan.record_id, plan.product_dir)
    if current != plan:
        raise ValueError('商品图片、文件名或子目录已改变，需要重新准备该商品素材')


@contextmanager
def snapshot_media_batch(plans: tuple[ProductMediaManifest, ...], *, retain_on_error=False):
    """先验证并复制整批快照；原生异步导入失败时可保留快照，避免中断页面读文件。"""
    plans = tuple(plans)
    if (not plans or len({plan.folder_name.casefold() for plan in plans}) != len(plans)
            or len({plan.record_id for plan in plans}) != len(plans)):
        raise ValueError('素材快照需要不重复的商品文件夹')
    for plan in plans:
        validate_media_manifest(plan)
    target = Path(tempfile.mkdtemp(prefix='taobao-media-batch-')).resolve()
    keep = False
    handed_off = False
    try:
        folders = []
        for plan in plans:
            folder = target / plan.folder_name
            folder.mkdir()
            folders.append(str(folder))
            for directory in plan.directories:
                (folder / directory).mkdir(parents=True, exist_ok=True)
            for image in plan.images:
                source = plan.source(image.relative_path)
                destination = folder / image.relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                if destination.stat().st_size != image.size or _file_hash(destination) != image.sha256:
                    raise ValueError('素材快照与本批清单不一致：' + image.relative_path)
        for plan in plans:
            validate_media_manifest(plan)
        handed_off = True
        yield tuple(folders)
    except Exception as exc:
        if retain_on_error and handed_off:
            keep = True
            raise TaobaoPublishError(getattr(exc, 'code', 'IMAGE_UPLOAD_FAILED'),
                '{}；素材快照暂留在 {}，页面队列结束后可清理'.format(exc, target)) from exc
        raise
    finally:
        if not keep:
            shutil.rmtree(target)


@dataclass(frozen=True, slots=True)
class UploadedImageReceipt:
    relative_path: str
    name: str
    folder: tuple[str, ...]
    url: str
    sha256: str
    uploaded_now: bool = True
    picture_id: str = ""


@dataclass(frozen=True, slots=True)
class PreparedProductMedia:
    manifest: ProductMediaManifest
    account_profile: str
    receipts: tuple[UploadedImageReceipt, ...]
    # 当前运行创建/导航的发布标签，仅用于后续阶段定位；不持久化到素材缓存。
    publish_target_id: str = ''

    def validate(self, account_profile: str) -> None:
        if not isinstance(self.account_profile, str) or not self.account_profile.strip() or account_profile != self.account_profile:
            raise ValueError('素材准备回执不属于本次店铺账户')
        expected = {image.relative_path: image for image in self.manifest.images}
        actual = {receipt.relative_path: receipt for receipt in self.receipts}
        if len(actual) != len(self.receipts) or actual.keys() != expected.keys():
            raise ValueError('素材准备回执存在缺图、重复图或不属于本商品的图片')
        for relative, image in expected.items():
            receipt = actual[relative]
            parts = PurePosixPath(relative).parts
            if receipt.name != parts[-1] or receipt.folder != (self.manifest.folder_name, *parts[:-1]):
                raise ValueError('上传后的文件名或子目录与原始结构不一致：' + relative)
            if receipt.sha256 != image.sha256:
                raise ValueError('图片上传回执不属于本批素材内容：' + relative)
            if type(receipt.uploaded_now) is not bool or not isinstance(receipt.url, str):
                raise ValueError('素材准备回执的状态或地址格式不正确')
            if not isinstance(receipt.picture_id, str):
                raise ValueError('素材准备回执的图片 ID 格式不正确')
            parsed = urlsplit(receipt.url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('图片上传回执缺少有效的 HTTPS 图片地址')
        validate_media_manifest(self.manifest)

    def selection_plan(self, item, account_profile: str) -> dict:
        """把商品用途与已上传的同一个文件对应，不按图库顺序猜 SKU。"""
        self.validate(account_profile)
        if item.record_id != self.manifest.record_id:
            raise ValueError('素材准备回执属于其它商品')
        root = Path(self.manifest.product_dir)
        uploaded = {receipt.relative_path: receipt for receipt in self.receipts}
        assigned = [sku.image_path for sku in item.skus if sku.image_path]
        if set(item.images.sku) - set(assigned):
            raise ValueError('SKU 图片缺少具体规格对应关系')
        roles = {'main': item.images.main, 'sku': list(dict.fromkeys(assigned)), 'detail': item.images.detail}
        result = {}
        for role, paths in roles.items():
            result[role] = []
            for raw in paths:
                path = Path(raw)
                if not path.is_absolute():
                    path = root / path
                _check_asset_path(root, path)
                relative = path.resolve(strict=True).relative_to(root).as_posix()
                receipt = uploaded.get(relative)
                if receipt is None:
                    raise ValueError('待填写图片没有本批上传回执：' + relative)
                result[role].append({'path': raw, 'name': receipt.name, 'sha256': receipt.sha256,
                    'url': receipt.url, 'picture_id': receipt.picture_id, 'cloud_folder': list(receipt.folder), 'uploaded_now': receipt.uploaded_now})
        return result


class MediaBatchPreparationError(TaobaoPublishError):
    """停止时保留已完成商品的回执，调用方不能盲目把整批再传一次。"""
    def __init__(self, cause: Exception, completed):
        self.completed = tuple(completed)
        self.partial_product = cause if isinstance(cause, ProductMediaPreparationError) else None
        super().__init__(getattr(cause, 'code', 'PAGE_ERROR'),
            '本批素材准备停止，已准备 {} 件商品：{}'.format(len(self.completed), cause))


class ProductMediaPreparationError(TaobaoPublishError):
    """某商品中途停止时保留已确认文件；该对象不是可供填写的完整回执。"""
    def __init__(self, cause: Exception, manifest, account_profile, receipts):
        self.manifest = manifest
        self.account_profile = account_profile
        self.receipts = tuple(receipts)
        super().__init__(getattr(cause, 'code', 'IMAGE_UPLOAD_FAILED'),
            '商品素材准备停止，已确认 {} 张图片：{}'.format(len(self.receipts), cause))


def prepare_media_batch(plans, upload_product, *, account_profile: str,
                        authorization: WriteAuthorization | None = None, progress=None, should_cancel=None):
    """先准备全批素材，再返回填写所需的回执；实际上传由会话上传端提供。

    upload_product 必须等待一个商品的文件真正入库后返回 PreparedProductMedia。
    本函数不会调用商品填写、保存草稿或提交；网页接口的生产适配尚需实证契约。
    """
    if not isinstance(account_profile, str) or not account_profile.strip():
        raise ValueError('素材批次必须绑定当前店铺账户')
    if not callable(upload_product):
        raise ValueError('没有可执行的网页素材上传端')
    plans = tuple(plans)
    auth = authorization if authorization is not None else WriteAuthorization.none()
    auth.require(WRITE_UPLOAD_IMAGE)
    completed = []
    try:
        with snapshot_media_batch(plans) as folders:
            for index, (plan, folder) in enumerate(zip(plans, folders), 1):
                if should_cancel is not None and should_cancel():
                    raise TaobaoPublishError('CANCELLED', '已取消，尚未开始后续商品的素材准备或表单填写')
                if progress:
                    progress('准备商品素材：{}/{} {}'.format(index, len(folders), plan.folder_name))
                prepared = upload_product(plan, folder, account_profile)
                if not isinstance(prepared, PreparedProductMedia) or prepared.manifest != plan:
                    raise ValueError('上传端没有返回当前商品的完整准备回执')
                prepared.validate(account_profile)
                completed.append(prepared)
            if should_cancel is not None and should_cancel():
                raise TaobaoPublishError('CANCELLED', '已取消，素材回执已保留，尚未进入表单填写')
    except (OSError, ValueError, TaobaoPublishError) as exc:
        raise MediaBatchPreparationError(exc, completed) from exc
    return tuple(completed)

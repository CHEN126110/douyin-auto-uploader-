# -*- coding: utf-8 -*-
"""商品目录浏览与本地素材回执。只读商品原文件，不连接平台。"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import threading

from PIL import Image, ImageOps, UnidentifiedImageError


IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
_CATALOG_LOCK = threading.RLock()


def _no_links(path: Path) -> None:
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('不读取符号链接或目录联接，请使用商品目录内的原文件')


def product_root(record: dict) -> Path:
    raw = record.get('path')
    if not isinstance(raw, str) or not raw.strip() or not Path(raw).is_absolute():
        raise ValueError('商品目录不存在或不是完整路径')
    root = Path(raw)
    _no_links(root)
    if not root.is_dir():
        raise ValueError('商品目录不存在')
    return root.resolve(strict=True)


def media_path(record: dict, relative: str = '') -> Path:
    root = product_root(record)
    if not isinstance(relative, str) or '\\' in relative or ':' in relative or '\0' in relative:
        raise ValueError('目录路径无效')
    if relative and (relative.startswith('/') or any(p in ('', '.', '..') for p in relative.split('/'))):
        raise ValueError('只允许访问当前商品目录内的文件')
    target = root.joinpath(*relative.split('/')) if relative else root
    _no_links(target)
    target = target.resolve(strict=True)
    if not target.is_relative_to(root):
        raise ValueError('文件不在当前商品目录内')
    return target


def validate_white_bg_selection(record: dict, relative: str) -> str:
    """只保存商品目录内实际图片的相对路径；空值恢复自动选择，不改任何图片。"""
    if not isinstance(relative, str):
        raise ValueError('白底图选择必须是图片相对路径')
    if not relative:
        return ''
    path = media_path(record, relative)
    if not path.is_file() or path.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}:
        raise ValueError('请选择 JPG、PNG、WebP 或 BMP 图片')
    with Image.open(path) as image:
        image.verify()
    return path.relative_to(product_root(record)).as_posix()


def selected_white_bg(record: dict) -> str:
    """明确指定后不静默换图；上传时再次确认文件仍存在且可读。"""
    relative = record.get('white_bg_path') or ''
    if not relative:
        return ''
    try:
        relative = validate_white_bg_selection(record, relative)
    except (ValueError, OSError) as exc:
        raise ValueError('指定的发布白底图不可用，请重新选择或恢复自动选择：' + str(exc)) from exc
    return str(media_path(record, relative))


def white_bg_selection(record: dict) -> dict:
    relative = record.get('white_bg_path') or ''
    error = ''
    if relative:
        try:
            selected_white_bg(record)
        except (ValueError, OSError) as exc:
            error = str(exc)
    return {'path': relative, 'valid': not error, 'error': error}


def _catalog_path(storage: Path, record: dict, profile: str) -> Path:
    scope = [record['id'], str(product_root(record)), profile]
    digest = hashlib.sha256(json.dumps(scope, ensure_ascii=False).encode('utf-8')).hexdigest()
    return Path(storage) / (digest + '.json')


def _validate_receipt(entry: dict) -> dict:
    required = {'path', 'role', 'name', 'sha256', 'status', 'folder_path', 'observed_at'}
    if not isinstance(entry, dict) or set(entry) != required:
        raise ValueError('素材记录结构无效')
    if (not isinstance(entry['path'], str) or not entry['path'] or
            any(p in ('', '.', '..') for p in entry['path'].split('/')) or
            any(c in entry['path'] for c in ('\\', ':', '\0'))):
        raise ValueError('素材记录的本地路径无效')
    if entry['role'] not in ('main', 'sku', 'detail') or entry['status'] not in ('located', 'uploaded_unlocated'):
        raise ValueError('素材记录的用途或状态无效')
    if not isinstance(entry['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', entry['sha256']):
        raise ValueError('素材记录缺少有效的内容校验值')
    if (not isinstance(entry['name'], str) or not entry['name'].strip() or len(entry['name']) > 255
            or any(character in entry['name'] for character in ('/', '\\', ':', '\0'))
            or any(ord(character) < 32 for character in entry['name'])
            or Path(entry['name']).suffix.lower() not in IMAGE_SUFFIXES):
        raise ValueError('素材记录的上传名称无效')
    folder = entry['folder_path']
    if (not isinstance(folder, list) or len(folder) > 30 or
            any(not isinstance(v, str) or not v.strip() or len(v) > 255 or
                any(c in v for c in ('/', '\\', '\0')) for v in folder)):
        raise ValueError('素材记录的图片空间目录无效')
    if entry['status'] == 'uploaded_unlocated' and folder:
        raise ValueError('未定位素材不能写入推测目录')
    if not isinstance(entry['observed_at'], str):
        raise ValueError('素材记录时间无效')
    datetime.fromisoformat(entry['observed_at'])
    return entry


def read_receipts(storage: Path, record: dict, profile: str) -> list[dict]:
    if not profile:
        return []
    target = _catalog_path(storage, record, profile)
    with _CATALOG_LOCK:
        if not target.exists():
            return []
        _no_links(target)
        data = json.loads(target.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('entries'), list):
        raise ValueError('素材记录文件无效，未把它当成空记录')
    return [_validate_receipt(entry) for entry in data['entries']]


def save_receipts(storage: Path, record: dict, profile: str, observations: list[dict]) -> None:
    """按账户、商品目录和用途保存最近事实。平台 URL、登录资料不落盘。"""
    if not profile or not isinstance(observations, list):
        raise ValueError('保存素材记录需要任务所绑定的账户及图片清单')
    root = product_root(record)
    now = datetime.now(timezone.utc).isoformat()
    additions = []
    for raw in observations:
        source = Path(raw['path'])
        if not source.is_absolute():
            source = root / source
        relative = source.relative_to(root).as_posix()
        # 文件可能在任务结束后被外部程序修改；保留上传当时的校验值，不重新计算。
        additions.append(_validate_receipt({
            'path': relative, 'role': raw['role'], 'name': raw['name'],
            'sha256': raw['sha256'], 'status': raw['status'],
            'folder_path': raw['folder_path'], 'observed_at': now,
        }))
    target = _catalog_path(storage, record, profile)
    with _CATALOG_LOCK:
        existing = read_receipts(storage, record, profile)
        # 同一路径/用途的新尝试替代旧尝试；主图重复槽位按上传名称分别保留。
        replaced = {(entry['path'], entry['role']) for entry in additions}
        merged = {(entry['path'], entry['role'], entry['name']): entry for entry in existing
                  if (entry['path'], entry['role']) not in replaced}
        for entry in additions:
            merged[(entry['path'], entry['role'], entry['name'])] = entry
        target.parent.mkdir(parents=True, exist_ok=True)
        _no_links(target.parent)
        payload = json.dumps({'version': 1, 'entries': list(merged.values())}, ensure_ascii=False, indent=2)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def _natural_key(name: str):
    return [(0, int(part)) if part.isdigit() else (1, part.casefold())
            for part in re.split(r'(\d+)', name)]


def list_directory(record: dict, relative: str, *, receipts=(), offset=0, limit=100) -> dict:
    """只枚举本层，不把父目录内容误当成子目录内容。图片按文件名自然排序。"""
    directory = media_path(record, relative)
    if not directory.is_dir():
        raise ValueError('请选择一个文件夹')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('目录分页参数无效')
    children = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), _natural_key(p.name)))
    entries = []
    for child in children[offset:offset + limit]:
        path = '/'.join(filter(None, [relative, child.name]))
        item = {'name': child.name, 'path': path, 'kind': 'file', 'size': 0,
                'modified_at': '', 'receipts': [], 'error': ''}
        try:
            safe = media_path(record, path)
            info = safe.stat()
            item.update(size=info.st_size, modified_at=datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat())
            if safe.is_dir():
                item['kind'] = 'folder'
            elif safe.is_file() and safe.suffix.lower() in IMAGE_SUFFIXES:
                item['kind'] = 'image'
                matches = [r for r in receipts if r['path'] == path]
                if matches:
                    with safe.open('rb') as stream:
                        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                    item['receipts'] = [dict(r, content_matches=r['sha256'] == digest) for r in matches]
        except (OSError, ValueError) as exc:
            item.update(kind='blocked', error=str(exc))
        entries.append(item)
    return {'record_id': record['id'], 'product_name': record.get('name') or str(record['id']),
            'path': relative, 'parent': relative.rsplit('/', 1)[0] if '/' in relative else '',
            'entries': entries, 'total': len(children), 'offset': offset, 'limit': limit}


def preview_image(record: dict, relative: str, *, thumbnail: bool) -> BytesIO:
    path = media_path(record, relative)
    if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError('只支持预览商品目录中的图片')
    if path.stat().st_size > 30 * 1024 * 1024:
        raise ValueError('图片超过 30 MB，请在文件夹中查看原图')
    try:
        with Image.open(path) as image:
            image.seek(0)
            output = ImageOps.exif_transpose(image)
            output.thumbnail((320, 320) if thumbnail else (1800, 1800))
            output = output.convert('RGB')
            buffer = BytesIO()
            output.save(buffer, format='JPEG', quality=88)
            buffer.seek(0)
            return buffer
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise ValueError('图片无法解码，原文件已保留') from exc

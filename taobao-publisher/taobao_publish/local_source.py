# -*- coding: utf-8 -*-
"""本地资产发现层。

把「磁盘上的采集目录」与「SQLite ``record`` 行」投影成 :mod:`taobao_publish.models`
里的纯数据对象。**本模块不导入 ``src/``、不导入 Peewee、不连数据库**，
这样发布流水线的其余部分可以在没有数据库的机器上被单测。

目录约定与 ``src/utils.py`` 保持一致（``get_main_pic_list`` / ``get_detail_pic_list``
/ ``get_white_pic`` 定义在 ``src/utils.py:2530-2830``），差异只有一点：
那边接收 Peewee 的 ``Record`` 对象，这边接收普通 ``dict`` 与路径。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .models import ImageSet, LocalProduct, LocalSku

#: 支持的图片扩展名。与 ``src/utils.py`` 的 supported_formats 一致。
SUPPORTED_IMAGE_SUFFIXES: Tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

#: 主图目录候选（按优先级）。
MAIN_IMAGE_DIRS: Tuple[str, ...] = ("主图/800", "主图/750", "主图")

#: 详情图目录候选。
DETAIL_IMAGE_DIRS: Tuple[str, ...] = ("详情页", "详情图片")

#: SKU 图目录。
SKU_IMAGE_DIR = "SKU"
#: 白底图子目录（``src/whitebg`` 的产出）。
WHITE_BG_DIR = "白底图"
#: 1:1 规格图目录（``src/whitebg`` 的产出）。
SQUARE_DIR = "SKU_1x1"

#: 白底图文件名（不含扩展名）候选，来自 ``src/utils.py:2796``。
WHITE_BG_STEMS: Tuple[str, ...] = ("白底", "white", "WHITE", "白底图")

#: 1:1 方图文件名后缀标记（``主图_01_1x1.jpg``）。
SQUARE_SUFFIX_MARKER = "_1x1"

_NUMERIC_RE = re.compile(r"(\d+)")


def natural_sort_key(value: str) -> List[Any]:
    """自然排序键，避免 ``10.jpg`` 排在 ``2.jpg`` 前面。

    等价于 ``src/utils.py`` 的 ``_natural_sort_key``（该实现正是为修掉这个 bug
    而加的，见提交 ``de6721d``）。
    """

    return [int(part) if part.isdigit() else part.lower() for part in _NUMERIC_RE.split(str(value))]


def _check_asset_path(root: Path, path: Path) -> Path:
    """商品目录内的真实文件/目录；拒绝符号链接和 Windows 重解析点。"""
    base, candidate = root.absolute(), path.absolute()
    try:
        candidate.relative_to(base)
        candidate.resolve().relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError('素材路径越出当前商品目录') from exc
    current = candidate
    while True:
        attributes = getattr(current.lstat(), 'st_file_attributes', 0)
        if current.is_symlink() or attributes & 0x400:
            raise ValueError('商品素材不能经过符号链接或重解析点')
        if current == base:
            return path
        current = current.parent


def _list_images(directory: Path, *, root: Path) -> List[Path]:
    """列出目录下的图片文件（非递归），自然排序。目录不存在时返回空列表。"""

    if not directory.is_dir():
        return []
    _check_asset_path(root, directory)
    files = [
        _check_asset_path(root, item)
        for item in directory.iterdir()
        if item.is_file() and item.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
    ]
    return sorted(files, key=lambda item: natural_sort_key(item.name))


def _first_existing_dir(root: Path, names: Sequence[str]) -> Optional[Path]:
    for name in names:
        candidate = root / name
        if candidate.is_dir():
            return _check_asset_path(root, candidate)
    return None


def _is_square_name(path: Path) -> bool:
    return SQUARE_SUFFIX_MARKER in path.stem


@dataclass(slots=True)
class AssetDiscovery:
    """磁盘扫描结果。``notes`` 记录扫描过程中的事实，便于排查「图为什么没找到」。"""

    images: ImageSet = field(default_factory=ImageSet)
    main_dir_used: str = ""
    detail_dir_used: str = ""
    notes: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    square_images: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "main_dir_used": self.main_dir_used,
            "detail_dir_used": self.detail_dir_used,
            "main_count": len(self.images.main),
            "detail_count": len(self.images.detail),
            "sku_count": len(self.images.sku),
            "square_count": len(self.square_images),
            "white_bg": bool(self.images.white_bg),
            "notes": list(self.notes),
            "missing": list(self.missing),
        }



#: 公开别名：`*_1x1` 方图判据。
#:
#: `desktop._asset_paths` 也要用它，好让「资料包里放哪些主图」
#: 与「流水线实际上传哪些主图」**用同一套判据**——
#: 两处各写一份迟早会反（实测就反过：一处偏好方图、一处排除方图）。
is_square_name = _is_square_name

def discover_product_assets(product_dir: str | os.PathLike[str]) -> AssetDiscovery:
    """扫描一个采集商品目录，按用途归类图片。

    **只读**：不创建、不修改、不移动任何文件。
    """

    root = Path(product_dir)
    discovery = AssetDiscovery()
    if not root.is_dir():
        discovery.missing.append(f"商品目录不存在：{root}")
        return discovery

    # --- 主图 -------------------------------------------------------------
    main_dir = _first_existing_dir(root, MAIN_IMAGE_DIRS)
    if main_dir is None:
        discovery.missing.append("未找到主图目录（尝试：" + "、".join(MAIN_IMAGE_DIRS) + "）")
    else:
        discovery.main_dir_used = str(main_dir.relative_to(root))
        all_main = _list_images(main_dir, root=root)
        # 主图**优先用 1:1 方图**（``*_1x1.jpg``）。
        #
        # 淘宝的「1:1主图」是必填位，静态预检会按 1:1 校验宽高比。
        # 采集目录里通常同时有原图（3:4）与 whitebg 产出的方图（`_1x1`），
        # 而原图过不了 1:1 校验——实测商品 ID-1083867541795 就是这样：
        # 5 张 3:4 主图让预检直接报「宽高比 0.75 偏离 1.00」，
        # 而旁边 5 张 800x800 的 `_1x1` 因为「不属于主图列表」被完全忽略，
        # 于是这个**明明有合规主图的商品永远发不出去**。
        #
        # 所以这里改成「优先方图，没有才退回原图」，而不是把方图一律排除。
        # 两组**不混用**——混用会在平台上重复上传同一张图。
        square_in_main = [str(p) for p in all_main if _is_square_name(p)]
        plain_in_main = [str(p) for p in all_main if not _is_square_name(p)]
        if square_in_main and plain_in_main:
            discovery.notes.append(
                f"主图目录内同时有 {len(square_in_main)} 张 _1x1 方图与 "
                f"{len(plain_in_main)} 张原图；主图列表取方图（淘宝 1:1 主图必填），"
                f"原图不参与上传以免重复"
            )
        elif square_in_main:
            discovery.notes.append(f"主图目录内只有 {len(square_in_main)} 张 _1x1 方图，直接作为主图")
        discovery.images.main = square_in_main or plain_in_main
        #: 被让位的原图（3:4）仍然记下来，便于 3:4 主图位将来使用。
        discovery.images.main_plain = plain_in_main if square_in_main else []
        if not discovery.images.main:
            discovery.missing.append(f"主图目录 {discovery.main_dir_used} 下没有可用图片")

    # --- 详情图 -----------------------------------------------------------
    detail_dir = _first_existing_dir(root, DETAIL_IMAGE_DIRS)
    if detail_dir is None:
        discovery.missing.append("未找到详情图目录（尝试：" + "、".join(DETAIL_IMAGE_DIRS) + "）")
    else:
        discovery.detail_dir_used = str(detail_dir.relative_to(root))
        discovery.images.detail = [str(p) for p in _list_images(detail_dir, root=root)]

    # --- SKU 图 -----------------------------------------------------------
    sku_dir = root / SKU_IMAGE_DIR
    if sku_dir.is_dir():
        discovery.images.sku = [str(p) for p in _list_images(sku_dir, root=root)]

    # --- 白底图 -----------------------------------------------------------
    discovery.images.white_bg = _find_white_bg(root, main_dir)

    # --- 1:1 方图（whitebg 子系统产出）-------------------------------------
    square_dir = root / SQUARE_DIR
    if square_dir.is_dir():
        squares = [str(p) for p in _list_images(square_dir, root=root)]
        discovery.square_images = squares
        if squares:
            discovery.notes.append(f"{SQUARE_DIR}/ 提供 {len(squares)} 张 1:1 规格图")

    return discovery


def selected_white_bg(root: Path, relative: str) -> str:
    """Record 中的人工选择；不导入桌面业务模块，保持本地资料投影可独立运行。"""
    if not relative:
        return ''
    if not root.is_absolute() or not root.is_dir():
        raise ValueError('指定白底图所属的商品目录无效')
    if (not isinstance(relative, str) or any(c in relative for c in ('\\', ':', '\0')) or
            any(part in ('', '.', '..') for part in relative.split('/'))):
        raise ValueError('指定的白底图必须在当前商品目录内')
    try:
        path = _check_asset_path(root, root.joinpath(*relative.split('/')))
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            raise ValueError('指定路径不是支持的图片文件')
        from PIL import Image
        with Image.open(path) as image:
            image.verify()
    except (ValueError, OSError) as exc:
        raise ValueError('指定的发布白底图不可用，请重新选择或恢复自动选择：' + str(exc)) from exc
    return str(path)


def _find_white_bg(root: Path, main_dir: Optional[Path]) -> str:
    """按 ``src/utils.py:2796`` 的候选名找白底图。

    查找顺序（与 ``get_white_pic`` 的意图一致，但**只找不生成**）：
    1. 商品目录根的 ``白底图.jpg``（``src/whitebg`` 的产出，发布端约定自动取用）
    2. 主图目录下的 ``白底/white/WHITE/白底图`` + 支持的扩展名
    3. ``白底图/`` 子目录里的第一张
    """

    for suffix in SUPPORTED_IMAGE_SUFFIXES:
        root_candidate = root / f"白底图{suffix}"
        if root_candidate.is_file():
            return str(_check_asset_path(root, root_candidate))

    if main_dir is not None:
        for stem in WHITE_BG_STEMS:
            for suffix in SUPPORTED_IMAGE_SUFFIXES:
                candidate = main_dir / f"{stem}{suffix}"
                if candidate.is_file():
                    return str(_check_asset_path(root, candidate))

    white_dir = root / WHITE_BG_DIR
    if white_dir.is_dir():
        found = _list_images(white_dir, root=root)
        if found:
            return str(found[0])

    return ""


# ---------------------------------------------------------------------------
# SQLite record 行 → LocalProduct
# ---------------------------------------------------------------------------
def parse_record_content(raw: Any) -> List[LocalSku]:
    """解析 ``record.content``。

    实测结构（``sqlite.db``）：JSON 数组，元素为
    ``{dir_name, file_name, name, path, price}``，``price`` 为 float。

    解析失败时抛 :class:`ValueError`——**不返回空列表兜底**，因为「解析失败」
    与「确实没有 SKU」是两件必须区分的事。
    """

    if raw is None or raw == "":
        return []
    if isinstance(raw, (list, tuple)):
        payload = list(raw)
    else:
        try:
            payload = json.loads(str(raw))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"record.content 不是合法 JSON：{exc}") from exc
    if not isinstance(payload, list):
        raise ValueError("record.content 解析后不是数组")

    skus: List[LocalSku] = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise ValueError(f"record.content[{index}] 不是对象")
        price_raw = item.get("price")
        price: Optional[float] = None
        if price_raw is not None and str(price_raw).strip() != "":
            try:
                price = float(price_raw)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"record.content[{index}].price 不是数字：{price_raw!r}") from exc
        skus.append(
            LocalSku(
                name=str(item.get("name") or ""),
                path=str(item.get("path") or ""),
                price=price,
                dir_name=str(item.get("dir_name") or ""),
                file_name=str(item.get("file_name") or ""),
            )
        )
    return skus


def local_product_from_record(
    row: Mapping[str, Any],
    *,
    product_dir: str = "",
    discovery: Optional[AssetDiscovery] = None,
) -> LocalProduct:
    """把一行 ``record`` 数据（普通 dict）投影成 :class:`LocalProduct`。

    :param row: 至少包含 ``id`` 与 ``name``；其余字段缺失按 ``None`` 处理。
    :param product_dir: 采集目录绝对路径（即 ``record.path``）。
    """

    record_id = row.get("id")
    if record_id is None:
        raise ValueError("record 行缺少 id")
    from .captured_attributes import normalize
    captured_attributes = normalize(row.get("captured_attributes"))
    skus = parse_record_content(row.get("content"))
    assets = discovery if discovery is not None else (discover_product_assets(product_dir) if product_dir else None)

    return LocalProduct(
        record_id=int(record_id),
        record_name=str(row.get("name") or ""),
        title=str(row.get("title") or ""),
        clazz=int(row["clazz"]) if row.get("clazz") is not None else None,
        remark=str(row.get("remark") or ""),
        shipping_template=str(row.get("shipping_template") or ""),
        source_url=str(row.get("source_url") or ""),
        product_dir=str(product_dir or row.get("path") or ""),
        skus=skus,
        captured_attributes=captured_attributes,
        main_images=list(assets.images.main) if assets else [],
        detail_images=list(assets.images.detail) if assets else [],
        white_bg_image=(selected_white_bg(Path(product_dir or row.get('path') or ''), row['white_bg_path'])
                        if row.get('white_bg_path') else (assets.images.white_bg if assets else "")),
        square_images=list(assets.square_images) if assets else [],
    )


def summarize_assets(discovery: AssetDiscovery) -> str:
    """一行中文摘要，用于进度上报。"""

    parts = [
        f"主图 {len(discovery.images.main)}",
        f"详情 {len(discovery.images.detail)}",
        f"SKU图 {len(discovery.images.sku)}",
        f"白底图 {'有' if discovery.images.white_bg else '无'}",
    ]
    return "，".join(parts)


def iter_readable_files(paths: Iterable[str]) -> Iterable[str]:
    """只产出确实存在的文件路径。用于把「找不到文件」的判定权交回给校验层。"""

    for path in paths:
        if path and Path(path).is_file():
            yield path

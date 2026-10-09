# -*- coding: utf-8 -*-
"""桌面端淘宝资料准备与本地资料包导出。

本模块只读取调用方提供的 Record 和采集目录，不连数据库、浏览器或平台。
``can_export`` 仅说明本地资料包可生成，始终不代表平台接受资料或已经发布。
淘宝售价、库存、类目与运费模板必须单独提供，不继承抖店字段或采购价。
"""

from __future__ import annotations

import csv
import io
import json
import pathlib
import math
import os
import shutil
import stat
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from PIL import Image

from .constants import STAGE_ORDER
from .contracts import load_contracts, validate_contracts, write_route_status
from .local_source import (
    DETAIL_IMAGE_DIRS,
    MAIN_IMAGE_DIRS,
    SKU_IMAGE_DIR,
    SUPPORTED_IMAGE_SUFFIXES,
    WHITE_BG_STEMS,
    WHITE_BG_DIR,
    natural_sort_key,
)
from .sanitize import assert_clean, sanitize_payload, sanitize_text
from . import local_source

_OVERRIDE_FIELDS = frozenset({
    "title", "guide_title", "category_path", "item_price", "total_stock",
    "freight_template_name", "skus",
})


def desktop_readiness() -> dict[str, Any]:
    """读取契约与阶段注册表，不执行任何阶段或会话探测。"""

    from .stages import STAGE_HANDLERS

    contracts = load_contracts()
    problems = validate_contracts(contracts)
    if problems:
        raise ValueError("淘宝契约自检失败：" + "；".join(problems))
    route = write_route_status(contracts)

    # ⚠️ 这里曾经硬编码 ``automatic_publish_ready: False``，消息也写着
    # 「自动填表、上传、草稿保存和上架尚未实现」——**它们现在都已实现**。
    # 而前端还把这个 False 当成必须成立的不变量来校验，于是两边一起陈旧：
    # 后端如实报告反而会让界面报错。
    #
    # 现在从真实状态推导。注意两条路线的**归属要分清**（与 CLI 出口一致）：
    # 字段缺口只关 mtop 协议路线，选择器缺口才关 DOM 路线。
    from .pipeline import describe_readiness

    readiness = describe_readiness(contracts)
    return {
        "platform": "taobao",
        "mode": "automated_pipeline",
        "automatic_publish_ready": bool(readiness.publishable),
        "publish_route_ready": bool(readiness.publish_route_ready),
        "dom_write_ready": bool(readiness.dom_write_ready),
        "protocol_write_ready": bool(readiness.protocol_write_ready),
        "implemented_stages": [stage for stage in STAGE_ORDER if stage in STAGE_HANDLERS],
        "unimplemented_stages": [stage for stage in STAGE_ORDER if stage not in STAGE_HANDLERS],
        "incomplete_stages": list(readiness.incomplete_stages),
        "live_unverified_stages": list(readiness.live_unverified_stages),
        # 这两个列表**归属不同路线**，字段名里带上看得出差别的前缀会更好，
        # 但改动会波及前端类型；这里用下划线字段显式说明归属。
        "blocked_fields": list(route["blocked_required_fields"]),
        "blocked_fields_note": "以上只关 mtop 协议路线；本次走 DOM 路线，不依赖它们",
        "blocked_selectors": list(route["blocked_write_critical_selectors"]),
        "blocked_selectors_note": "以上才关 DOM 路线；为 0 表示 DOM 路线不缺选择器",
        "message": (
            "提供资料准备与自动填表流水线："
            "选类目 → 上传主图 → 填标题/属性/规格/物流/价格库存 → 回读核对，"
            "**提交前截停**。是否上架请在卖家中心人工核对。"
        ),
    }


def _text(value: Any, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是字符串")
    text = value.strip()
    if sanitize_text(text) != text:
        raise ValueError(f"{field} 含登录态或个人敏感信息，请先清理后重新提供")
    return text


def _price(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} 必须是明确填写的数字")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field} 必须是有限且大于 0 的数字") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field} 必须是有限且大于 0 的数字")
    return number


def _stock(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} 必须是明确填写的非负整数")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise ValueError(f"{field} 必须是有限的非负整数")
    if value < 0:
        raise ValueError(f"{field} 必须是非负整数")
    return int(value)


def _record_id(record: Mapping[str, Any]) -> int:
    value = record.get("id")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Record.id 必须是正整数")
    return value


def _reject_links(path: Path) -> None:
    """拒绝符号链接、junction 及其它重解析点，避免越权读取/复制。"""

    for candidate in (path, *path.parents):
        try:
            attrs = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(attrs.st_mode) or (
            getattr(attrs, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise ValueError("资料路径不能包含符号链接或重解析点")


def _product_root(record: Mapping[str, Any]) -> Path | None:
    raw = record.get("path")
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise ValueError("Record.path 必须是本地目录路径")
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError("Record.path 必须是本地绝对目录路径")
    _reject_links(path)
    if not path.is_dir():
        return None
    return path.resolve(strict=True)


def _contained_file(root: Path, raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    _reject_links(path)
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ValueError("商品图片路径超出当前记录目录")
    return resolved


def _images_in(root: Path, directory: Path) -> list[str]:
    _reject_links(directory)
    if not directory.is_dir():
        return []
    result: list[Path] = []
    for entry in directory.iterdir():
        if entry.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES:
            path = _contained_file(root, str(entry))
            if path.is_file():
                result.append(path)
    return [str(path) for path in sorted(result, key=lambda path: natural_sort_key(path.name))]


def _asset_paths(root: Path | None, white_bg_path: str = '') -> dict[str, Any]:
    assets: dict[str, Any] = {"main": [], "main_plain": [], "detail": [], "sku": [],
                              "white_bg": ""}
    if root is None:
        return assets
    main_dir: Path | None = None
    for name in MAIN_IMAGE_DIRS:
        candidate = root / name
        _reject_links(candidate)
        if candidate.is_dir():
            main_dir = candidate
            # ⚠️ **与 `local_source` 用同一套选择**：主图**优先方图**（`*_1x1`），
            # 没有才退回原图，**两组不混用**。
            #
            # 实测：`主图/` 下同时有 1440x1920（比例 0.75，不合契约）与
            # 800x800（比例 1.0，合规）两套。原先这里取**全部**，
            # 于是报告对前者报 5 条「本地主图不是 1:1，上传前需人工确认与处理」——
            # **而流水线上传的是后者**。报告让用户去处理一批根本不会被用的图。
            #
            # `local_source` 里写得很清楚：「两组不混用——混用会在平台上
            # 重复上传同一张图」。
            listed = _images_in(root, main_dir)
            square = [p for p in listed
                      if local_source.is_square_name(pathlib.Path(p))]
            plain = [p for p in listed
                     if not local_source.is_square_name(pathlib.Path(p))]
            assets["main"] = square or plain
            # 被让位的原图仍然记下来——`local_source` 也留着（`images.main_plain`），
            # 供将来的 3:4 主图位使用。
            assets["main_plain"] = plain if square else []
            break
    for name in DETAIL_IMAGE_DIRS:
        candidate = root / name
        _reject_links(candidate)
        if candidate.is_dir():
            assets["detail"] = _images_in(root, candidate)
            break
    assets["sku"] = _images_in(root, root / SKU_IMAGE_DIR)
    if white_bg_path:
        assets["white_bg"] = local_source.selected_white_bg(root, white_bg_path)
        return assets
    white_candidates = [root / f"白底图{suffix}" for suffix in SUPPORTED_IMAGE_SUFFIXES]
    if main_dir is not None:
        white_candidates.extend(
            main_dir / f"{stem}{suffix}"
            for stem in WHITE_BG_STEMS for suffix in SUPPORTED_IMAGE_SUFFIXES
        )
    for candidate in white_candidates:
        _reject_links(candidate)
        if candidate.is_file():
            assets["white_bg"] = str(_contained_file(root, str(candidate)))
            break
    if not assets["white_bg"]:
        white_files = _images_in(root, root / WHITE_BG_DIR)
        if white_files:
            assets["white_bg"] = white_files[0]
    return assets


def _content(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = record.get("content")
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            raise ValueError("Record.content 不是合法 JSON") from exc
    if not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
        raise ValueError("Record.content 必须是规格对象数组")
    return raw


def _sku_overrides(overrides: Mapping[str, Any], count: int) -> dict[int, Mapping[str, Any]]:
    entries = overrides.get("skus", [])
    if not isinstance(entries, list):
        raise ValueError("skus 必须是规格覆盖数组")
    result: dict[int, Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) - {"index", "price", "stock"}:
            raise ValueError("规格覆盖仅允许 index、price、stock")
        index = entry.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < count:
            raise ValueError("规格覆盖 index 超出当前记录规格范围")
        if index in result:
            raise ValueError("规格覆盖 index 不能重复")
        result[index] = entry
    return result


def _image_size(path: str) -> tuple[int, int]:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            return image.size


def _weighted_length(text: str) -> int:
    """与真实填写路径共用归档样本计数，不宣称跨类目验证。"""

    from .text_rules import count_title_units
    return count_title_units(text)


def prepare_product(record: Mapping[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    """整理独立淘宝字段与检查结果。所有售价和库存仅来自显式 overrides。"""

    if not isinstance(record, Mapping) or not isinstance(overrides, Mapping):
        raise ValueError("record 与 overrides 必须是对象")
    if set(overrides) - _OVERRIDE_FIELDS:
        raise ValueError("淘宝资料覆盖包含不允许的字段")
    root = _product_root(record)
    assets = _asset_paths(root, record.get('white_bg_path') or '')
    content = _content(record)
    sku_edits = _sku_overrides(overrides, len(content))
    skus = []
    for index, item in enumerate(content):
        raw_path = item.get("path")
        if raw_path is not None and not isinstance(raw_path, str):
            raise ValueError("规格图片 path 必须是字符串")
        path = str(_contained_file(root, raw_path)) if root is not None and raw_path else ""
        edit = sku_edits.get(index, {})
        skus.append({
            "index": index,
            "name": _text(item.get("name"), f"规格 {index + 1} 名称"),
            "price": _price(edit.get("price"), f"规格 {index + 1} 售价"),
            "stock": _stock(edit.get("stock"), f"规格 {index + 1} 库存"),
            "image_path": path,
        })
        if path and path not in assets["sku"]:
            assets["sku"].append(path)

    title = _text(overrides.get("title", record.get("title")), "淘宝标题")
    guide_title = _text(overrides.get("guide_title"), "导购标题")
    category_path = _text(overrides.get("category_path"), "淘宝类目")
    freight_name = _text(overrides.get("freight_template_name"), "淘宝运费模板名称")
    item_price = _price(overrides.get("item_price"), "商品一口价")
    total_stock = _stock(overrides.get("total_stock"), "商品总库存")
    checks: list[dict[str, str]] = []

    def check(field: str, label: str, status: str, message: str) -> None:
        checks.append({"field": field, "label": label, "status": status, "message": message})

    check("product_dir", "商品资料目录", "ok" if root else "missing",
          "当前记录的本地目录可读取。" if root else "当前记录的资料目录不存在或未提供。")
    check("title", "淘宝标题", "ok" if title else "missing",
          "已提供独立淘宝标题；发布前仍需按目标类目人工核对。" if title else "请提供淘宝宝贝标题。")
    contracts = load_contracts()
    title_limit = contracts.rules.integer("title_max_chars")
    guide_limit = contracts.rules.integer("guide_title_max_chars")
    if _weighted_length(title) > title_limit:
        check("title_length", "标题长度提示", "warning",
              f"按已归档样本中文计 2 字符，当前标题超过 {title_limit} 字符；目标类目实际计数需人工确认。")
    else:
        check("title_length", "标题长度提示", "warning",
              "目标类目的实时标题上限尚未确认，当前长度仅供人工核对。")
    if guide_title and _weighted_length(guide_title) > guide_limit:
        check("guide_title", "导购标题", "warning",
              f"超过已归档样本的 {guide_limit} 字符提示；请按目标类目确认。")
    check("main_images", "主图资料", "ok" if assets["main"] else "missing",
          f"发现 {len(assets['main'])} 张本地主图。" if assets["main"] else "请在当前商品目录提供可解码主图。")
    all_paths = list(dict.fromkeys(
        assets["main"] + assets["detail"] + assets["sku"]
        + ([assets["white_bg"]] if assets["white_bg"] else [])
    ))
    for index, path in enumerate(all_paths):
        try:
            width, height = _image_size(path)
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            check(f"image.{index}", "图片可读性", "missing", "发现不存在、无法解码或尺寸异常的图片，请修复原始资料。")
            continue
        if path in assets["main"] and width != height:
            check(f"image_ratio.{index}", "主图比例", "warning", "本地主图不是 1:1；资料包保留原图，上传前需人工确认与处理。")
    if len(assets["main"]) > contracts.rules.integer("main_image_max_count"):
        check("main_image_count", "主图数量", "warning", "本地主图数量超过已归档样本提示，发布前请人工选定图片。")
    if not assets["detail"]:
        check("detail_images", "详情图片", "warning", "未发现详情图；请在淘宝图文描述阶段人工补齐。")
    check("item_price", "商品一口价", "ok" if item_price is not None else "missing",
          "商品一口价已单独填写，目标类目价格规则仍需人工确认。" if item_price is not None else "请单独填写淘宝商品一口价，不能从采购价或 SKU 价格推导。")
    check("total_stock", "商品总库存", "ok" if total_stock is not None else "missing",
          "商品总库存已单独填写，未按 SKU 合计自动替代。" if total_stock is not None else "请单独填写商品总库存；不会默认填入库存。")
    check("category_path", "淘宝类目", "warning",
          "类目名称仅供人工选类目核对，尚未验证平台类目 ID 与属性映射。" if category_path else "请在淘宝工作台人工选择并核对类目；不会使用抖店类目 ID。")
    check("freight_template_name", "淘宝运费模板", "warning",
          "模板名称仅供人工核对，淘宝店铺内模板与发货规则尚未验证。" if freight_name else "请在淘宝店铺核对运费模板和发货规则；不会继承抖店模板。")
    for sku in skus:
        index = sku["index"]
        if not sku["name"]:
            check(f"skus.{index}.name", "规格名称", "warning", f"第 {index + 1} 条规格名称未提供，请人工补齐。")
        if sku["price"] is None:
            check(f"skus.{index}.price", "规格售价", "warning", f"第 {index + 1} 条规格尚未填写淘宝售价；采购价不能自动作为淘宝售价。")
        if sku["stock"] is None:
            check(f"skus.{index}.stock", "规格库存", "warning", f"第 {index + 1} 条规格尚未提供库存，请在平台填写前人工补齐。")
        if not sku["image_path"]:
            check(f"skus.{index}.image", "规格图片", "warning", f"第 {index + 1} 条规格没有本地图片，请人工核对。")
    if not skus:
        check("skus", "销售规格", "warning", "当前记录没有规格资料，请人工核对商品是否需要销售规格。")
    check("platform_review", "平台人工复核", "warning", "本资料包尚未上传平台；类目属性、资质、价格、物流、图文描述与最终上架操作均需人工核对。")
    return {
        "platform": "taobao",
        "record_id": _record_id(record),
        "record_name": _text(record.get("name"), "商品记录名称"),
        "title": title,
        "guide_title": guide_title,
        "category_path": category_path,
        "item_price": item_price,
        "total_stock": total_stock,
        "freight_template_name": freight_name,
        "skus": skus,
        "assets": assets,
        "checks": checks,
        "can_export": not any(item["status"] == "missing" for item in checks),
        # ⚠️ 这里也曾硬编码 False——与 `desktop_readiness` 那处是**两条独立的链**。
        # 前端有三处守卫要求它为 false，于是后端如实报告反而会让界面报错。
        "automatic_publish_ready": bool(_current_readiness().publishable),
    }



def _current_readiness():
    """惰性取流水线就绪度。

    放在函数里而不是模块顶部：``pipeline`` 会 import ``stages``，
    而 ``stages`` 又依赖 ``desktop`` 的若干常量——顶栏导入容易成环。
    """

    from .pipeline import describe_readiness

    return describe_readiness()


def _csv_text(value: Any) -> str:
    text = "" if value is None else str(value)
    # 在表格软件中打开时将规格名视为文本，避免执行以公式符号开头的资料。
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def export_packet(
    record: Mapping[str, Any], overrides: Mapping[str, Any], output_base: str | os.PathLike[str]
) -> dict[str, Any]:
    """在调用方受控 output_base 下生成新资料包；失败抛错，不改源资料。"""

    prepared = prepare_product(record, overrides)
    if not prepared["can_export"]:
        missing = [item["label"] for item in prepared["checks"] if item["status"] == "missing"]
        raise ValueError("淘宝资料包尚不可导出：" + "、".join(missing))
    root = _product_root(record)
    if root is None:
        raise ValueError("当前记录的商品目录不可读取")
    base = Path(output_base)
    if not base.is_absolute():
        raise ValueError("资料包输出根目录必须是受控的本地绝对路径")
    _reject_links(base)
    base = base.resolve(strict=False)
    if base.is_relative_to(root):
        raise ValueError("资料包输出根目录不能位于原始商品资料目录内")
    base.mkdir(parents=True, exist_ok=True)
    _reject_links(base)
    packet = base / f"taobao-{prepared['record_id']}-{uuid4().hex}"
    packet.mkdir(exist_ok=False)
    manifest = dict(prepared)
    # `mode` 说的是**应用流水线**的模式，真源在就绪度里。
    # 取不到就留 None——**不编一个字符串**（编出来就是「话跟不上代码」的老毛病）。
    try:
        # `describe_readiness()` 的结果里没有 `mode` 字段——它描述的是流水线能力，
        # 不是路由模式。取 `desktop_readiness()`（真正给出 `mode` 的那个）。
        _route_mode = desktop_readiness().get("mode")
    except Exception:
        _route_mode = None
    manifest.update({
        "mode": _route_mode,
        # ⚠️ **`mode` 不再被覆盖。**
        #
        # 它由 `prepare_product` 从 `_readiness_payload` 带来，说的是**应用流水线**的模式
        # （现在是 `automated_pipeline`）。原先这里把它改写成 `manual_preparation`，
        # 于是同一个键在一份文件里有两个意思——读 manifest 的人会以为应用还停在
        # 「人工准备」阶段，而它早已是自动流水线。
        #
        # 「这份资料包只是本地资料」这件事由 `packet_kind` 明确表达。
        "packet_kind": "manual_preparation",
        "platform_published": False,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "message": "仅为本地淘宝资料包，尚未上传、保存平台草稿或发布商品。",
    })
    manifest["assets"] = {"main": [], "detail": [], "sku": [], "white_bg": ""}
    manifest["skus"] = [dict(sku) for sku in prepared["skus"]]
    copies = 0
    sku_copies: dict[str, str] = {}
    try:
        for purpose in ("main", "detail", "sku", "white_bg"):
            raw_paths = prepared["assets"][purpose]
            paths = ([raw_paths] if raw_paths else []) if purpose == "white_bg" else raw_paths
            for index, raw_path in enumerate(paths):
                source = _contained_file(root, raw_path)
                _image_size(str(source))
                relative = Path("images") / purpose / f"{index + 1:03d}{source.suffix.lower()}"
                destination = packet / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                # 不转换图片或修改元数据，资料包保留原始字节。
                with source.open("rb") as reader, destination.open("xb") as writer:
                    shutil.copyfileobj(reader, writer)
                copies += 1
                if purpose == "white_bg":
                    manifest["assets"][purpose] = relative.as_posix()
                else:
                    manifest["assets"][purpose].append(relative.as_posix())
                if purpose == "sku":
                    sku_copies[str(source)] = relative.as_posix()
        for sku in manifest["skus"]:
            sku["image_path"] = sku_copies.get(sku["image_path"], "")
        sanitized_manifest = sanitize_payload(manifest)
        if sanitized_manifest != manifest:
            raise ValueError("淘宝资料包含敏感信息，请清理资料后重新导出")
        manifest = sanitized_manifest
        manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        assert_clean(manifest_text, context="淘宝本地资料包 manifest")
        manifest_path = packet / "manifest.json"
        with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(manifest_text)
        csv_stream = io.StringIO(newline="")
        csv_writer = csv.writer(csv_stream)
        csv_writer.writerow(["index", "name", "price", "stock", "image_path"])
        for sku in manifest["skus"]:
            csv_writer.writerow([sku["index"], _csv_text(sku["name"]), sku["price"], sku["stock"], sku["image_path"]])
        csv_text = csv_stream.getvalue()
        assert_clean(csv_text, context="淘宝本地资料包 SKU CSV")
        csv_path = packet / "skus.csv"
        with csv_path.open("x", encoding="utf-8-sig", newline="") as stream:
            stream.write(csv_text)
        with (packet / "使用说明.txt").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(
                "淘宝本地资料准备包\n\n"
                "本资料包未上传图片、未保存平台草稿、未发布商品。\n"
                "请按 manifest.json 的 checks 核对类目、属性、图片、售价、库存、物流和资质。\n"
                "skus.csv 是规格资料表，不是已验证的淘宝批量导入格式。\n"
                "图片按用途复制，保留原始格式、像素和字节，尚未完成平台上传校验。\n"
                "原始商品资料和应用数据库均未修改。\n"
            )
    except Exception:
        # 仅回收本次 UUID 新建的受控目录；保留原异常与源资料。
        _reject_links(packet)
        if packet.parent != base or not packet.name.startswith(f"taobao-{prepared['record_id']}-"):
            raise RuntimeError("资料包失败后的清理路径不在受控输出根内")
        shutil.rmtree(packet)
        raise
    return {
        "platform": "taobao",
        "record_id": prepared["record_id"],
        "packet_dir": str(packet),
        "manifest_path": str(manifest_path),
        "sku_csv_path": str(csv_path),
        "files_count": copies + 3,
        "message": "淘宝本地资料包已生成；尚未上传图片、保存平台草稿或发布商品。",
    }

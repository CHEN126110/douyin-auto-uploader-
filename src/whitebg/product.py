# -*- coding: utf-8 -*-
"""采集目录级编排：给一个商品目录补上「白底图」和「1:1 规格图」。

输入是采集目录（如 `<uploads>/products/ID-1075636304051`），产出：

    白底图/<原SKU名>.jpg   每个 SKU 一张 1:1 白底语义抠图（可直接当规格图用）
    白底图/_report.json    每张的判定数据、警告、被拒原因
    白底图.jpg             目录根一张，供 src/utils.py 的 get_white_pic() 自动取用
    SKU_1x1/<原SKU名>.jpg  原场景裁成 1:1 —— 白底图被拒时规格图也有 1:1 可用

为什么 SKU_1x1 一定要出：白底图流水线会**如实拒绝**做不出来的图
（多色对照图、穿着图），但平台的「规格图长宽比需为 1:1」是每个 SKU 都要满足的，
所以这一份不依赖模型、不会失败，兜住比例要求。

只新增文件，不动 SKU/ 主图/ 详情页/ 里的原图。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from . import geometry as geo
from .pipeline import Config, SockWhiteBg, UnsuitableSource

SKU_DIR = 'SKU'
MAIN_DIR = '主图'
WHITE_DIR = '白底图'
SQUARE_DIR = 'SKU_1x1'
WHITE_ROOT_NAME = '白底图.jpg'
REPORT_NAME = '_report.json'
IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')


@dataclass
class ProductOutcome:
    product_dir: str
    ok: bool = False
    white_dir: str = ''
    square_dir: str = ''
    white_root: str = ''
    white_root_source: str = ''
    items: list = field(default_factory=list)   # 每张 SKU 图一条
    fallback_items: list = field(default_factory=list)  # 为了凑根白底图额外试的主图
    seconds: float = 0.0
    message: str = ''

    def to_dict(self) -> dict:
        return {
            'product_dir': self.product_dir,
            'ok': self.ok,
            'white_dir': self.white_dir,
            'square_dir': self.square_dir,
            'white_root': self.white_root,
            'white_root_source': self.white_root_source,
            'items': self.items,
            'fallback_items': self.fallback_items,
            'seconds': round(self.seconds, 2),
            'message': self.message,
        }


def list_images(directory: str) -> list[str]:
    if not os.path.isdir(directory):
        return []
    names = [n for n in os.listdir(directory)
             if os.path.splitext(n)[1].lower() in IMAGE_EXTS
             and os.path.isfile(os.path.join(directory, n))]
    return [os.path.join(directory, n) for n in sorted(names)]


def process_product_dir(product_dir: str, cfg: Config | None = None,
                        processor: SockWhiteBg | None = None,
                        square_size: int | None = None,
                        overwrite: bool = True,
                        progress=None, preserve_paths=()) -> ProductOutcome:
    """处理一个采集目录。processor 可复用，批量处理多个商品时省下模型加载。"""
    started = time.perf_counter()
    out = ProductOutcome(product_dir=os.path.abspath(product_dir))
    if not os.path.isdir(product_dir):
        out.message = f'采集目录不存在: {product_dir}'
        return out

    sku_files = list_images(os.path.join(product_dir, SKU_DIR))
    if not sku_files:
        out.message = f'{SKU_DIR}/ 下没有图片，无法处理'
        return out

    cfg = cfg or Config()
    cfg.debug = False                      # 目录级批处理不留调试大数组
    proc = processor or SockWhiteBg(cfg)

    white_dir = os.path.join(product_dir, WHITE_DIR)
    square_dir = os.path.join(product_dir, SQUARE_DIR)
    os.makedirs(white_dir, exist_ok=True)
    os.makedirs(square_dir, exist_ok=True)
    out.white_dir = white_dir
    out.square_dir = square_dir

    total = len(sku_files)
    for idx, path in enumerate(sku_files, start=1):
        if progress:
            progress(idx, total, os.path.basename(path))
        out.items.append(_process_one(proc, path, white_dir, square_dir,
                                      square_size, overwrite))

    # 目录根的白底图：取第一张成功的 SKU 白底图
    picked = next((it for it in out.items if it['white_ok']), None)
    if picked is None:
        # SKU 全军覆没（多色对照图这类），退而从主图里找一张能用的
        for path in list_images(os.path.join(product_dir, MAIN_DIR)):
            item = _process_one(proc, path, white_dir, square_dir, square_size,
                                overwrite, square=False, name_prefix='主图_')
            out.fallback_items.append(item)
            if item['white_ok']:
                picked = item
                break

    if picked is not None:
        root_path = os.path.join(product_dir, WHITE_ROOT_NAME)
        Image.open(picked['white_path']).save(root_path, quality=95, subsampling=0)
        out.white_root = root_path
        out.white_root_source = picked['source']
        out.ok = True
        n_ok = sum(1 for it in out.items if it['white_ok'])
        out.message = (f'白底图 {n_ok}/{total} 张成功，规格图 1:1 {total} 张；'
                       f'目录根白底图取自 {os.path.basename(picked["source"])}')
    else:
        n_sq = sum(1 for it in out.items if it['square_ok'])
        out.message = (f'没有一张图能抠出可用的白底图（{total} 张 SKU 图全部被拒，'
                       f'主图也没找到可用的）；规格图 1:1 已出 {n_sq} 张')

    # 清掉上一轮留下、这一轮没产出的文件。
    # 换模型/换参数重跑时目录会攒垃圾：实测 bria-rmbg 那轮 SKU 全被拒、走了主图兜底，
    # 换成 birefnet 后 SKU 全成功、不再需要兜底，但 `白底图/主图_主图_02.jpg` 还留在那儿，
    # 发布端和人都分不清哪张是这一轮的。采集下载也是同样的先清后写。
    # 用户已指定用于发布的图片不能被“清理上一轮产物”删掉。
    preserved = {os.path.normcase(os.path.abspath(os.path.join(product_dir, relative)))
                 for relative in preserve_paths}
    def keep_in(directory):
        return {name for name in os.listdir(directory)
                if os.path.normcase(os.path.abspath(os.path.join(directory, name))) in preserved}

    _prune_stale(white_dir, {os.path.basename(it['white_path'])
                             for it in out.items + out.fallback_items if it['white_ok']},
                 keep_names={REPORT_NAME} | keep_in(white_dir))
    _prune_stale(square_dir, {os.path.basename(it['square_path'])
                              for it in out.items + out.fallback_items if it['square_ok']},
                 keep_names=keep_in(square_dir))

    report = {
        'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'matte_model': cfg.matte_model,
        'model_dir': getattr(proc, 'model_dir', ''),
        'canvas': cfg.canvas,
        'fill_ratio': cfg.fill_ratio,
        'outcome': out.to_dict(),
    }
    with open(os.path.join(white_dir, REPORT_NAME), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    out.seconds = time.perf_counter() - started
    return out


def _prune_stale(directory: str, produced: set, keep_names: set | None = None) -> list:
    """删掉本轮没产出的旧文件，只碰图片（和 keep_names 白名单之外的东西一概不动）。"""
    keep = set(keep_names or ())
    removed = []
    if not os.path.isdir(directory):
        return removed
    for name in os.listdir(directory):
        if name in produced or name in keep:
            continue
        fp = os.path.join(directory, name)
        if not os.path.isfile(fp):
            continue
        if os.path.splitext(name)[1].lower() not in IMAGE_EXTS:
            continue
        try:
            os.remove(fp)
            removed.append(name)
        except OSError:
            pass
    return removed


def _process_one(proc: SockWhiteBg, path: str, white_dir: str, square_dir: str,
                 square_size: int | None, overwrite: bool,
                 square: bool = True, name_prefix: str = '') -> dict:
    """单张图：出白底图（可能被拒）+ 出 1:1 规格图（不会被拒）。"""
    stem = name_prefix + os.path.splitext(os.path.basename(path))[0]
    item = {
        'source': os.path.abspath(path),
        'name': stem,
        'white_ok': False,
        'white_path': '',
        'square_ok': False,
        'square_path': '',
        'code': '',
        'message': '',
        'warnings': [],
        'tilt_deg': 0.0,
        'tilt_confident': False,
        'scene': {},
        'verdicts': [],
        'compose': {},
        'seconds': 0.0,
    }
    t0 = time.perf_counter()
    subject_box = None

    try:
        res = proc.process(path)
        dest = os.path.join(white_dir, f'{stem}.jpg')
        if overwrite or not os.path.exists(dest):
            res.image.save(dest, quality=95, subsampling=0)
        item.update({
            'white_ok': True,
            'white_path': os.path.abspath(dest),
            'warnings': list(res.warnings),
            'tilt_deg': res.tilt_deg,
            'tilt_confident': bool(res.tilt_info.get('confident')),
            'scene': {k: round(v, 3) for k, v in res.scene.items()},
            'verdicts': res.verdicts,
            'compose': res.compose_meta,
        })
        subject_box = res.compose_meta.get('subject_box_src')
    except UnsuitableSource as exc:
        item.update({'code': exc.code, 'message': exc.message})
        item['scene'] = {k: round(v, 3) for k, v in (exc.detail.get('scene') or {}).items()}
        item['verdicts'] = exc.detail.get('verdicts') or []
        # 白底图被拒不代表连主体在哪都不知道；有外框就拿来给 1:1 裁剪定位
        subject_box = exc.detail.get('subject_box')
    except Exception as exc:                        # 解码失败、文件损坏等
        item.update({'code': 'exception', 'message': f'{type(exc).__name__}: {exc}'})

    if square:
        try:
            rgb = np.asarray(Image.open(path).convert('RGB'))
            img, meta = geo.square_original(rgb, subject_box, square_size)
            dest = os.path.join(square_dir, f'{stem}.jpg')
            if overwrite or not os.path.exists(dest):
                img.save(dest, quality=95, subsampling=0)
            item['square_ok'] = True
            item['square_path'] = os.path.abspath(dest)
            item['square'] = meta
        except Exception as exc:
            item['square_error'] = f'{type(exc).__name__}: {exc}'

    item['seconds'] = round(time.perf_counter() - t0, 2)
    return item

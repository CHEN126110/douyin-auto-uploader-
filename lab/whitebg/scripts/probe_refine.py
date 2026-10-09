# -*- coding: utf-8 -*-
"""诊断：怎样把「两只袜子之间那条地毯」从 alpha 里去掉。

isnet 在 1024 输入下把两只袜子之间几十像素宽的地毯缝隙当成主体内部填实了。
这里对比几种在全分辨率上重判边界的办法：

  A 原始（聚焦 + 引导滤波）           —— 作为基线
  B 宽腐蚀 trimap + closed-form matting（pymatting）
  C 宽腐蚀 trimap + KNN matting（pymatting，快一些）
  D 宽腐蚀 trimap + random walker（skimage，按梯度传播标签）

关键在 trimap 的腐蚀半径要大于缝隙宽度的一半，缝隙才会落进 unknown 区，
让真实像素颜色来决定它到底是袜子还是地毯。
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

# 实现已搬到 src/whitebg/（单一真源），实验脚本从那里导入
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), 'src'))
from whitebg import matte as matte_mod   # noqa: E402

SRC_DIR = (r'C:\Users\CRB\AppData\Local\com.dyin.sock-publisher'
           r'\uploads\products\ID-1075636304051\SKU')
OUT = os.path.join('lab', 'whitebg', 'out', '06_refine_probe')
TEST_FILES = ['01_大花边.jpg', '02_长丝带.jpg', '06_蛋糕波点.jpg']


def build_trimap(alpha: np.ndarray, erode_px: int, bg_thresh: int = 24,
                 fg_thresh: int = 230, bg_dilate_px: int = 8) -> np.ndarray:
    """返回 0=背景 / 0.5=待定 / 1=前景 的 trimap。"""
    fg_seed = alpha >= fg_thresh
    fg = ndimage.binary_erosion(fg_seed, structure=_disk(erode_px))
    if not fg.any():                       # 腐蚀过头就退回较小的半径
        fg = ndimage.binary_erosion(fg_seed, structure=_disk(max(2, erode_px // 3)))
    bg = alpha <= bg_thresh
    bg = ndimage.binary_erosion(bg, structure=_disk(bg_dilate_px))
    tri = np.full(alpha.shape, 0.5, dtype=np.float64)
    tri[bg] = 0.0
    tri[fg] = 1.0
    return tri


def _disk(r: int) -> np.ndarray:
    if r <= 0:
        return np.ones((1, 1), dtype=bool)
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return (x * x + y * y) <= r * r


def crop_with_margin(alpha: np.ndarray, margin: float = 0.06):
    m = alpha >= 128
    if not m.any():
        return None
    ys = np.flatnonzero(m.any(axis=1))
    xs = np.flatnonzero(m.any(axis=0))
    y0, y1 = int(ys[0]), int(ys[-1]) + 1
    x0, x1 = int(xs[0]), int(xs[-1]) + 1
    pad = int(round(max(y1 - y0, x1 - x0) * margin))
    h, w = alpha.shape
    return (max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad))


def run_matting(rgb: np.ndarray, alpha: np.ndarray, method: str, erode_px: int,
                work_side: int = 900):
    """在主体外框内、降采样到 work_side 上求解，再把 alpha 放回全分辨率。

    matting 求的是大规模线性系统，直接在 1440×1919 上跑太慢；
    在 ~900px 上求解再上采样，对「缝隙要不要保留」这种大尺度判断已经够了。
    """
    box = crop_with_margin(alpha)
    if box is None:
        raise ValueError('alpha 空')
    x0, y0, x1, y1 = box
    sub_rgb = rgb[y0:y1, x0:x1]
    sub_a = alpha[y0:y1, x0:x1]
    h, w = sub_a.shape
    scale = min(1.0, work_side / float(max(h, w)))
    if scale < 1.0:
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        sub_rgb_s = np.asarray(Image.fromarray(sub_rgb).resize((nw, nh), Image.LANCZOS))
        sub_a_s = np.asarray(Image.fromarray(sub_a).resize((nw, nh), Image.LANCZOS))
        er = max(2, int(round(erode_px * scale)))
    else:
        sub_rgb_s, sub_a_s, er = sub_rgb, sub_a, erode_px

    tri = build_trimap(sub_a_s, er)
    img = sub_rgb_s.astype(np.float64) / 255.0

    t = time.time()
    if method == 'cf':
        from pymatting import estimate_alpha_cf
        out = estimate_alpha_cf(img, tri)
    elif method == 'knn':
        from pymatting import estimate_alpha_knn
        out = estimate_alpha_knn(img, tri)
    elif method == 'rw':
        from skimage.segmentation import random_walker
        markers = np.zeros(tri.shape, dtype=np.int32)
        markers[tri == 0.0] = 1
        markers[tri == 1.0] = 2
        lab = random_walker(img, markers, beta=250, mode='cg_j', channel_axis=-1,
                            return_full_prob=True)
        out = lab[1]
    else:
        raise ValueError(method)
    cost = time.time() - t

    out_u8 = (np.clip(out, 0, 1) * 255).astype(np.uint8)
    if scale < 1.0:
        out_u8 = np.asarray(Image.fromarray(out_u8).resize((w, h), Image.BICUBIC))
    full = np.zeros_like(alpha)
    full[y0:y1, x0:x1] = out_u8
    return full, cost, tri, (x0, y0, x1, y1)


def white_comp(rgb: np.ndarray, alpha: np.ndarray) -> Image.Image:
    a = alpha.astype(np.float32)[:, :, None] / 255.0
    out = rgb.astype(np.float32) * a + 255.0 * (1 - a)
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


def sheet(tiles, pad=8):
    w = sum(t.width for _, t in tiles) + pad * (len(tiles) + 1)
    h = max(t.height for _, t in tiles) + pad * 2 + 22
    c = Image.new('RGB', (w, h), (250, 250, 250))
    d = ImageDraw.Draw(c)
    x = pad
    for cap, t in tiles:
        c.paste(t, (x, pad + 22))
        d.text((x + 2, pad + 4), cap, fill=(20, 20, 20))
        x += t.width + pad
    return c


def main():
    os.makedirs(OUT, exist_ok=True)
    session = matte_mod.make_session(matte_mod.DEFAULT_MODEL, os.path.expanduser('~/.rembg'))
    for fname in TEST_FILES:
        path = os.path.join(SRC_DIR, fname)
        if not os.path.isfile(path):
            print('缺文件', path)
            continue
        rgb = np.asarray(Image.open(path).convert('RGB'))
        base, info = matte_mod.focused_alpha(rgb, session, passes=3)
        base_ref = matte_mod.guided_refine(base, rgb)
        box = crop_with_margin(base_ref)
        subject_long = max(box[3] - box[1], box[2] - box[0])
        erode_px = max(12, int(round(subject_long * 0.035)))
        print(f'--- {fname}  主体长边 {subject_long}px  腐蚀半径 {erode_px}px')

        tiles = [('原图', _t(Image.fromarray(rgb))),
                 ('A 基线', _t(white_comp(rgb, base_ref)))]
        for method, cap in (('cf', 'B closed-form'), ('knn', 'C KNN'), ('rw', 'D randomwalk')):
            try:
                a2, cost, tri, _ = run_matting(rgb, base_ref, method, erode_px)
                print(f'    {cap}: {cost:.1f}s  前景占比 {(a2 >= 128).mean() * 100:.1f}%')
                tiles.append((f'{cap} {cost:.1f}s', _t(white_comp(rgb, a2))))
            except Exception as exc:
                print(f'    {cap}: 失败 {type(exc).__name__}: {exc}')
        name = os.path.splitext(fname)[0]
        sheet(tiles).save(os.path.join(OUT, f'{name}__refine.jpg'), quality=88)
        print('    写出', os.path.join(OUT, f'{name}__refine.jpg'))


def _t(im: Image.Image, size=(400, 540)) -> Image.Image:
    im = im.copy()
    im.thumbnail(size, Image.LANCZOS)
    return im


if __name__ == '__main__':
    main()

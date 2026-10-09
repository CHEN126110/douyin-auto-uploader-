# -*- coding: utf-8 -*-
"""诊断：两只袜子之间那条缝隙，matte 到底给了多少 alpha。

出图：原图局部 | alpha 灰度 | alpha>=150 二值 | alpha 等级分层着色
"""
from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image, ImageDraw

# 实现已搬到 src/whitebg/（单一真源），实验脚本从那里导入
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), 'src'))
from whitebg import matte as matte_mod   # noqa: E402

SRC = (r'C:\Users\CRB\AppData\Local\com.dyin.sock-publisher'
       r'\uploads\products\ID-1075636304051\SKU\01_大花边.jpg')
OUT = os.path.join('lab', 'whitebg', 'out', '05_gap_probe')


def level_color(alpha: np.ndarray) -> Image.Image:
    """alpha 分层着色：0 黑 / 1-63 深蓝 / 64-127 青 / 128-199 黄 / 200+ 红。"""
    h, w = alpha.shape
    out = np.zeros((h, w, 3), dtype=np.uint8)
    out[alpha < 1] = (20, 20, 20)
    out[(alpha >= 1) & (alpha < 64)] = (30, 60, 200)
    out[(alpha >= 64) & (alpha < 128)] = (30, 190, 200)
    out[(alpha >= 128) & (alpha < 200)] = (240, 210, 40)
    out[alpha >= 200] = (230, 50, 40)
    return Image.fromarray(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    rgb = np.asarray(Image.open(SRC).convert('RGB'))
    session = matte_mod.make_session(matte_mod.DEFAULT_MODEL, os.path.expanduser('~/.rembg'))

    a1 = matte_mod.raw_alpha(rgb, session)
    a2, info = matte_mod.focused_alpha(rgb, session, passes=3)
    a2r = matte_mod.guided_refine(a2, rgb)
    print('focus info:', info)

    # 缝隙区域：主体外框内，取左右袜子之间那一竖条。
    # 用「核心区的水平投影谷底」自动找缝：先求核心区，再在框内找每列的前景像素数。
    core = a2r >= 150
    ys = np.flatnonzero(core.any(axis=1))
    xs = np.flatnonzero(core.any(axis=0))
    y0, y1, x0, x1 = int(ys[0]), int(ys[-1]) + 1, int(xs[0]), int(xs[-1]) + 1
    print(f'主体外框 x[{x0},{x1}) y[{y0},{y1})  尺寸 {x1-x0}x{y1-y0}')

    band = rgb[y0:y1, x0:x1]
    Image.fromarray(band).save(os.path.join(OUT, 'crop_rgb.jpg'), quality=92)

    tiles = []
    for tag, arr in (('原图', Image.fromarray(band)),
                     ('alpha 单遍', Image.fromarray(a1[y0:y1, x0:x1]).convert('RGB')),
                     ('alpha 聚焦', Image.fromarray(a2[y0:y1, x0:x1]).convert('RGB')),
                     ('聚焦+引导', Image.fromarray(a2r[y0:y1, x0:x1]).convert('RGB')),
                     ('分层', level_color(a2r[y0:y1, x0:x1]))):
        t = arr.copy()
        t.thumbnail((420, 560), Image.LANCZOS)
        tiles.append((tag, t))

    pad = 8
    w = sum(t.width for _, t in tiles) + pad * (len(tiles) + 1)
    h = max(t.height for _, t in tiles) + pad * 2 + 22
    canvas = Image.new('RGB', (w, h), (250, 250, 250))
    d = ImageDraw.Draw(canvas)
    x = pad
    for tag, t in tiles:
        canvas.paste(t, (x, pad + 22))
        d.text((x + 2, pad + 4), tag, fill=(20, 20, 20))
        x += t.width + pad
    canvas.save(os.path.join(OUT, 'gap_compare.jpg'), quality=90)

    # 缝隙处 alpha 的数值分布：沿主体中部取一条水平扫描线
    mid = (y0 + y1) // 2
    line = a2r[mid, x0:x1]
    print(f'y={mid} 扫描线 alpha（每 20 列采样一次）:')
    print('  ', ' '.join(f'{v:3d}' for v in line[::20]))
    print('写出', os.path.join(OUT, 'gap_compare.jpg'))


if __name__ == '__main__':
    main()

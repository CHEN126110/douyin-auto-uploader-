# -*- coding: utf-8 -*-
"""诊断 alpha 收紧强度：毛边压掉多少 vs 真花边吃掉多少。

左边看 04_条纹（深色袜子，毛边最明显），右边看 01_大花边（有蕾丝，最怕吃边）。
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

SRC_DIR = (r'C:\Users\CRB\AppData\Local\com.dyin.sock-publisher'
           r'\uploads\products\ID-1075636304051\SKU')
OUT = os.path.join('lab', 'whitebg', 'out', '12_tighten')
SETTINGS = [(0.0, 1.0), (0.28, 0.95), (0.40, 0.96), (0.55, 0.97)]


def white_comp(rgb, alpha):
    a = alpha.astype(np.float32)[:, :, None] / 255.0
    out = rgb.astype(np.float32) * a + 255.0 * (1 - a)
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


def _top_window(alpha, side=560):
    """主体顶部窗口 —— 花边/蕾丝在这里，用来检查收紧有没有吃掉产品的软边。"""
    m = alpha >= 128
    ys = np.flatnonzero(m.any(axis=1))
    xs = np.flatnonzero(m.any(axis=0))
    y0 = int(ys[0])
    x0, x1 = int(xs[0]), int(xs[-1]) + 1
    cx = (x0 + x1) // 2
    left = max(0, cx - side // 2)
    top = max(0, y0 - side // 8)
    return (left, top, left + side, top + side)


def _emit(rgb, a, zoom, name):
    tiles = []
    for lo, hi in SETTINGS:
        at = a if lo == 0.0 and hi == 1.0 else matte_mod.tighten_alpha(a, lo, hi)
        im = white_comp(rgb, at).crop(zoom).resize((440, 440), Image.LANCZOS)
        cap = '原样' if (lo, hi) == (0.0, 1.0) else f'lo={lo} hi={hi}'
        tiles.append((cap, im))
    pad = 8
    w = sum(t.width for _, t in tiles) + pad * (len(tiles) + 1)
    h = max(t.height for _, t in tiles) + pad * 2 + 22
    c = Image.new('RGB', (w, h), (250, 250, 250))
    d = ImageDraw.Draw(c)
    x = pad
    for cap, t in tiles:
        c.paste(t, (x, pad + 22))
        d.text((x + 2, pad + 4), cap, fill=(20, 20, 20))
        x += t.width + pad
    dest = os.path.join(OUT, f'{name}__tighten.jpg')
    c.save(dest, quality=92)
    print('  写出', dest)


def _left_edge_window(alpha, side=420):
    """自动取主体左边缘中部的放大窗口 —— 毛边最容易看清的地方。"""
    m = alpha >= 128
    ys = np.flatnonzero(m.any(axis=1))
    xs = np.flatnonzero(m.any(axis=0))
    y0, y1 = int(ys[0]), int(ys[-1]) + 1
    x0 = int(xs[0])
    cy = (y0 + y1) // 2
    left = max(0, x0 - side // 4)
    top = max(0, cy - side // 2)
    return (left, top, left + side, top + side)


def main():
    os.makedirs(OUT, exist_ok=True)
    sess = matte_mod.make_session('bria-rmbg', os.path.expanduser('~/.rembg'))
    for fname in ('04_条纹.jpg', '01_大花边.jpg'):
        rgb = np.asarray(Image.open(os.path.join(SRC_DIR, fname)).convert('RGB'))
        a, _ = matte_mod.focused_alpha(rgb, sess, passes=2)
        a = matte_mod.guided_refine(a, rgb)
        for tag, zoom in (('左边缘', _left_edge_window(a)), ('花边袜口', _top_window(a))):
            print(f'{fname} {tag} 窗口 {zoom}')
            _emit(rgb, a, zoom, os.path.splitext(fname)[0] + f'__{tag}')
        continue
        tiles = []
        for lo, hi in SETTINGS:
            at = a if lo == 0.0 and hi == 1.0 else matte_mod.tighten_alpha(a, lo, hi)
            im = white_comp(rgb, at).crop(zoom).resize((440, 440), Image.LANCZOS)
            cap = '原样' if (lo, hi) == (0.0, 1.0) else f'lo={lo} hi={hi}'
            tiles.append((cap, im))
        pad = 8
        w = sum(t.width for _, t in tiles) + pad * (len(tiles) + 1)
        h = max(t.height for _, t in tiles) + pad * 2 + 22
        c = Image.new('RGB', (w, h), (250, 250, 250))
        d = ImageDraw.Draw(c)
        x = pad
        for cap, t in tiles:
            c.paste(t, (x, pad + 22))
            d.text((x + 2, pad + 4), cap, fill=(20, 20, 20))
            x += t.width + pad
        name = os.path.splitext(fname)[0]
        c.save(os.path.join(OUT, f'{name}__tighten.jpg'), quality=92)
        print('写出', os.path.join(OUT, f'{name}__tighten.jpg'))


if __name__ == '__main__':
    main()

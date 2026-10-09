# -*- coding: utf-8 -*-
"""诊断：哪个 matte 模型能把两只袜子之间那条地毯缝隙分开。

对每个本地已有模型，跑「二次聚焦 + 引导滤波」的完整第一层，
出白底合成图 + alpha 分层图，直接看缝隙那条是红（实前景）还是黑（背景）。
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

# 实现已搬到 src/whitebg/（单一真源），实验脚本从那里导入
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), 'src'))
from whitebg import matte as matte_mod   # noqa: E402

SRC_DIR = (r'C:\Users\CRB\AppData\Local\com.dyin.sock-publisher'
           r'\uploads\products\ID-1075636304051\SKU')
OUT = os.path.join('lab', 'whitebg', 'out', '10_model_gap')
# 模型统一由 whitebg.paths 解析
from whitebg import paths as model_paths  # noqa: E402
HOME = str(model_paths.rembg_home(model_paths.resolve_model_dir()))
FILES = ['01_大花边.jpg', '02_长丝带.jpg']


def present(name):
    return os.path.isfile(os.path.join(HOME, 'models', name, f'{name}.onnx'))


def white_comp(rgb, alpha):
    a = alpha.astype(np.float32)[:, :, None] / 255.0
    out = rgb.astype(np.float32) * a + 255.0 * (1 - a)
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


def levels(alpha):
    h, w = alpha.shape
    out = np.zeros((h, w, 3), dtype=np.uint8)
    out[alpha < 1] = (20, 20, 20)
    out[(alpha >= 1) & (alpha < 64)] = (30, 60, 200)
    out[(alpha >= 64) & (alpha < 128)] = (30, 190, 200)
    out[(alpha >= 128) & (alpha < 200)] = (240, 210, 40)
    out[alpha >= 200] = (230, 50, 40)
    return Image.fromarray(out)


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
    names = [n for n in ('isnet-general-use', 'birefnet-general-lite',
                         'birefnet-general', 'bria-rmbg') if present(n)]
    print('可用模型:', names)
    for fname in FILES:
        rgb = np.asarray(Image.open(os.path.join(SRC_DIR, fname)).convert('RGB'))
        comp_tiles = [('原图', _t(Image.fromarray(rgb)))]
        lvl_tiles = []
        for n in names:
            sess = matte_mod.make_session(n, HOME)
            t0 = time.time()
            a, info = matte_mod.focused_alpha(rgb, sess, passes=3)
            a = matte_mod.guided_refine(a, rgb)
            cost = time.time() - t0
            box = info['final_box']
            sub = a[box[1]:box[3], box[0]:box[2]]
            comp_tiles.append((f'{n} {cost:.1f}s', _t(white_comp(rgb, a))))
            lvl_tiles.append((n, _t(levels(sub))))
            print(f'  {fname} {n}: {cost:.1f}s 聚焦轮 {len(info["passes"])} '
                  f'前景占比 {(a >= 128).mean() * 100:.1f}%')
        name = os.path.splitext(fname)[0]
        sheet(comp_tiles).save(os.path.join(OUT, f'{name}__models.jpg'), quality=88)
        sheet(lvl_tiles).save(os.path.join(OUT, f'{name}__levels.jpg'), quality=88)
        print('  写出', os.path.join(OUT, f'{name}__models.jpg'))


def _t(im, size=(380, 510)):
    im = im.copy()
    im.thumbnail(size, Image.LANCZOS)
    return im


if __name__ == '__main__':
    main()

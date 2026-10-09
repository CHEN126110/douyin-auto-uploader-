# -*- coding: utf-8 -*-
"""诊断语义闸门的判别力：

1. 在不同 core 阈值下看连通域怎么分裂/合并；
2. 单独把鞋子那块喂给 CLIP，确认它会被判成 shoe 而不是 sock
   —— 只有这一点成立，"语义抠图"才不是靠阈值碰巧蒙对。
"""
from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

# 实现已搬到 src/whitebg/（单一真源），实验脚本从那里导入
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), 'src'))
from whitebg import matte as matte_mod                 # noqa: E402
from whitebg import paths as model_paths  # noqa: E402
from whitebg.clip_gate import ClipGate, crop_for_clip  # noqa: E402

SRC_DIR = (r'C:\Users\CRB\AppData\Local\com.dyin.sock-publisher'
           r'\uploads\products\ID-1075636304051\SKU')
OUT = os.path.join('lab', 'whitebg', 'out', '09_gate_probe')
# 模型统一由 whitebg.paths 解析，实验室不再单独存一份副本
CLIP_DIR = str(model_paths.clip_dir(model_paths.resolve_model_dir()))


def main():
    os.makedirs(OUT, exist_ok=True)
    fname = sys.argv[1] if len(sys.argv) > 1 else '01_大花边.jpg'
    path = os.path.join(SRC_DIR, fname)
    rgb = np.asarray(Image.open(path).convert('RGB'))
    session = matte_mod.make_session(matte_mod.DEFAULT_MODEL, os.path.expanduser('~/.rembg'))
    gate = ClipGate(CLIP_DIR)

    # 注意：用整图单遍 matte，不做聚焦裁剪 —— 聚焦会把画面裁到主体外框，
    # 这里要看的恰恰是「陪衬物在不同阈值下怎么和主体粘连」。
    alpha = matte_mod.guided_refine(matte_mod.raw_alpha(rgb, session), rgb)

    for core in (32, 64, 96, 128, 150, 180):
        m = matte_mod.clean_mask(alpha, core, 0.0015, 0.02)
        labels, n = ndimage.label(m)
        sizes = [int((labels == i).sum()) for i in range(1, n + 1)]
        print(f'core={core:3d}  连通域 {n}  面积 {sizes}')
        if n == 0:
            continue
        crops = [crop_for_clip(rgb, labels == i) for i in range(1, n + 1)]
        scored = gate.score(crops)
        tiles = []
        for i, (c, s) in enumerate(zip(crops, scored), start=1):
            g = s['groups']
            t = c.copy()
            t.thumbnail((220, 220), Image.LANCZOS)
            tiles.append((f"#{i} sock={g['sock']:.2f} shoe={g['shoe']:.2f} "
                          f"other={g['other']:.2f}", t))
            print(f"    #{i} area={int((labels == i).sum()):>7} "
                  f"sock={g['sock']:.3f} shoe={g['shoe']:.3f} other={g['other']:.3f} "
                  f"| {s['top_prompt']}")
        _sheet(tiles).save(os.path.join(OUT, f'core{core}__crops.jpg'), quality=88)


def _sheet(tiles, pad=8):
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


if __name__ == '__main__':
    main()

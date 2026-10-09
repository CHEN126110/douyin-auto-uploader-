# -*- coding: utf-8 -*-
"""实验 01：对比各 rembg 模型在袜子平铺图上的 matte 表现。

只做观察与出图，不改任何业务代码、不写回采集目录。
用法： python lab/whitebg/scripts/matte_compare.py [模型名 ...]
"""
from __future__ import annotations

import os
import sys
import time
import glob

import numpy as np
from PIL import Image

SRC_DIR = r'C:\Users\CRB\AppData\Local\com.dyin.sock-publisher\uploads\products\ID-1075636304051\SKU'
OUT_DIR = os.path.join('lab', 'whitebg', 'out', '01_matte_compare')

CANDIDATES = ['u2netp', 'u2net', 'isnet-general-use', 'birefnet-general-lite', 'bria-rmbg']


def available_models(names):
    home = os.path.join(os.environ.get('REMBG_HOME', os.path.expanduser('~/.rembg')), 'models')
    ok = []
    for n in names:
        p = os.path.join(home, n, f'{n}.onnx')
        if os.path.isfile(p):
            ok.append(n)
        else:
            print(f'[skip] {n} 模型文件未就绪: {p}')
    return ok


def run_model(name, images, max_side=1024):
    from rembg import new_session, remove
    t0 = time.time()
    session = new_session(name)
    print(f'[{name}] session 就绪 {time.time()-t0:.1f}s')
    results = {}
    for path in images:
        im = Image.open(path).convert('RGB')
        small = im.copy()
        small.thumbnail((max_side, max_side), Image.LANCZOS)
        t = time.time()
        cut = remove(small, session=session, post_process_mask=False)
        alpha = np.asarray(cut.split()[-1], dtype=np.uint8)
        results[path] = (small, alpha)
        print(f'[{name}] {os.path.basename(path)} {small.size} 推理 {time.time()-t:.1f}s  '
              f'前景占比 {(alpha > 127).mean()*100:.1f}%')
    return results


def white_composite(rgb: Image.Image, alpha: np.ndarray) -> Image.Image:
    a = alpha.astype(np.float32)[:, :, None] / 255.0
    arr = np.asarray(rgb, dtype=np.float32)
    out = arr * a + 255.0 * (1 - a)
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    names = sys.argv[1:] or CANDIDATES
    names = available_models(names)
    if not names:
        print('没有可用模型，先跑 lab/whitebg/scripts/fetch_models.sh')
        return 1

    images = sorted(glob.glob(os.path.join(SRC_DIR, '*.jpg')))
    if not images:
        print(f'源目录没有图片: {SRC_DIR}')
        return 1
    # 先用前 3 张做快速对比
    images = images[:3]

    per_model = {}
    for n in names:
        per_model[n] = run_model(n, images)

    # 每张原图一行对比图：原图 + 各模型白底结果
    for path in images:
        tiles = []
        base = per_model[names[0]][path][0]
        tiles.append(('原图', base))
        for n in names:
            small, alpha = per_model[n][path]
            tiles.append((n, white_composite(small, alpha)))
        w = sum(t.width for _, t in tiles)
        h = max(t.height for _, t in tiles)
        canvas = Image.new('RGB', (w, h), (235, 235, 235))
        x = 0
        for _, t in tiles:
            canvas.paste(t, (x, 0))
            x += t.width
        canvas.thumbnail((2000, 2000), Image.LANCZOS)
        name = os.path.splitext(os.path.basename(path))[0]
        dest = os.path.join(OUT_DIR, f'{name}__compare.jpg')
        canvas.save(dest, quality=86)
        print('写出', dest, '顺序:', ['原图'] + names)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

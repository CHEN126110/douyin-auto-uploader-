# -*- coding: utf-8 -*-
"""逐像素验证：新的 onnxruntime 直连实现与 rembg 出的 mask 是否等价。

为什么必须有这一步：把 ``rembg → pymatting → numba → llvmlite`` 摘掉能省 39.5 MB，
但代价是**自己复刻 rembg 的数值流程**（除以最大值而不是 255、sigmoid + min-max、
LANCZOS 回原尺寸）。复刻错了不会报错，只会安静地出一张不一样的 mask —— 所以这里
对真实采集图逐像素比对，等价才算通过。

跑法（仓库根目录）：

    python lab/whitebg/scripts/verify_onnx_equivalence.py [图片目录或文件 ...]

不给参数时用采集目录里的真实商品图。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'src'))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

MODEL = os.environ.get('MATTE_MODEL', 'birefnet-general')
MODEL_HOME = Path(os.environ.get(
    'DOUYIN_WHITEBG_MODEL_DIR',
    str(Path(os.environ.get('LOCALAPPDATA', '')) / 'com.dyin.sock-publisher/models/whitebg')))
REMBG_HOME = MODEL_HOME / 'rembg'


def collect_inputs(argv: list) -> list:
    targets = []
    for item in argv:
        path = Path(item)
        if path.is_file():
            targets.append(path)
        elif path.is_dir():
            targets.extend(sorted(p for p in path.rglob('*')
                                  if p.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')))
    if targets:
        return targets[:12]
    products = (Path(os.environ.get('LOCALAPPDATA', '')) /
                'com.dyin.sock-publisher/uploads/products')
    if products.is_dir():
        for product in sorted(products.iterdir()):
            for name in ('主图', 'SKU'):
                folder = product / name
                if folder.is_dir():
                    targets.extend(sorted(folder.glob('*.jpg'))[:2])
    return targets[:8]


def old_mask(img: Image.Image, session) -> Image.Image:
    from rembg import remove
    return remove(img, session=session, only_mask=True, post_process_mask=False)


def new_mask(img: Image.Image, session) -> Image.Image:
    from whitebg import onnx_session
    return onnx_session.predict_mask(session, img)


def main() -> int:
    images = collect_inputs(sys.argv[1:])
    if not images:
        print('没有找到可比对的图片')
        return 2
    os.environ['REMBG_HOME'] = str(REMBG_HOME)
    from rembg import new_session
    from whitebg import matte, onnx_session

    print('模型: {}  模型目录: {}'.format(MODEL, MODEL_HOME))
    print('比对图片 {} 张'.format(len(images)))
    old_session = new_session(MODEL)
    new_session_obj = onnx_session.make_session(MODEL, REMBG_HOME)

    worst = {'max': 0, 'mean': 0.0, 'diff_pixels': 0.0, 'name': ''}
    all_identical = True
    for path in images:
        img = Image.open(path).convert('RGB')
        a = np.asarray(old_mask(img, old_session).convert('L'), dtype=np.int16)
        b = np.asarray(new_mask(img, new_session_obj).convert('L'), dtype=np.int16)
        if a.shape != b.shape:
            print('  {:<28} 尺寸不一致 {} vs {}'.format(path.name, a.shape, b.shape))
            return 1
        diff = np.abs(a - b)
        identical = not diff.any()
        all_identical &= identical
        ratio = float((diff > 0).mean())
        print('  {:<28} 最大差 {:>3}  平均差 {:>6.3f}  不同像素 {:.4%}  {}'.format(
            path.name, int(diff.max()), float(diff.mean()), ratio,
            '逐像素相同' if identical else '有差异'))
        if int(diff.max()) > worst['max']:
            worst = {'max': int(diff.max()), 'mean': float(diff.mean()),
                     'diff_pixels': ratio, 'name': path.name}

    print('\n最差一张：{}  最大差 {}  平均差 {:.3f}  不同像素 {:.4%}'.format(
        worst['name'], worst['max'], worst['mean'], worst['diff_pixels']))
    if all_identical:
        print('结论：与 rembg 逐像素相同 ✓')
        return 0
    if worst['max'] <= 1:
        print('结论：最大差 ≤1 灰阶（浮点/线程差异级别），可接受 ✓')
        return 0
    print('结论：**不等价**，不能就这么摘掉 rembg ✗')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())

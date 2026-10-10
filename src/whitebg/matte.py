# -*- coding: utf-8 -*-
"""抠图第一层：通用 matte 模型 + 二次聚焦 + 全分辨率边缘细化。

这一层只负责「把前景从背景里分出来」，**不做语义判断**；
谁是袜子谁是鞋，交给 clip_gate.py。

isnet / u2net 的 ONNX 输入固定 1024×1024，1440×1919 的采集图喂进去先被压到
1024 再把 mask 拉回来，两只袜子之间那条几十像素宽的地毯缝隙在 1024 下只有十几
像素，模型分不开，结果就是「两只袜子中间粘着一条地毯」。解决办法是二次聚焦：
第一遍定位主体 → 按主体外框裁原图 → 第二遍在裁剪图上重跑，主体的有效分辨率
提高 2~3 倍，缝隙自然就分开了。
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image
from scipy import ndimage

DEFAULT_MODEL = 'birefnet-general'


def make_session(model_name: str = DEFAULT_MODEL, model_home: str | None = None):
    """建 matte 会话。model_home 指向存放 ``models/<name>/<name>.onnx`` 的目录。

    ⚠️ 不再经 rembg：``rembg → pymatting → numba → llvmlite`` 那条链只为拿到一个
    onnxruntime 会话，却要给安装包塞进 39.5 MB 的 ``llvmlite.dll``（真机实测 2026-10-10）。
    现在由 :mod:`whitebg.onnx_session` 按同一套数值流程直接建会话，数值等价在
    ``lab/whitebg`` 逐像素比对过。
    """
    if model_home:
        os.environ.setdefault('REMBG_HOME', str(model_home))
    from . import onnx_session
    return onnx_session.make_session(model_name, model_home)


def _infer(rgb: np.ndarray, session, infer_side: int) -> np.ndarray:
    """单次 matte 推理，返回与输入同分辨率的 alpha（uint8）。"""
    from . import onnx_session
    im = Image.fromarray(rgb)
    work = im
    if infer_side and max(im.size) > infer_side:
        work = im.copy()
        work.thumbnail((infer_side, infer_side), Image.LANCZOS)
    mask = onnx_session.predict_mask(session, work)
    if mask.size != im.size:
        mask = mask.resize(im.size, Image.BICUBIC)
    return np.asarray(mask.convert('L'), dtype=np.uint8)


def raw_alpha(rgb: np.ndarray, session, infer_side: int = 1024) -> np.ndarray:
    return _infer(rgb, session, infer_side)


def focused_alpha(rgb: np.ndarray, session, infer_side: int = 1024,
                  passes: int = 2, margin: float = 0.08, core: int = 128):
    """二次聚焦 matte：逐轮按主体外框裁剪重跑，提高主体的有效分辨率。

    返回 (alpha_full, info)。alpha_full 与原图同尺寸，聚焦框之外一律为 0
    —— 框外本来就没有主体，保留那里的弱 alpha 只会引进噪声。
    """
    h, w = rgb.shape[:2]
    alpha = _infer(rgb, session, infer_side)
    info = {'passes': [{'box': (0, 0, w, h), 'fg_ratio': round(float((alpha >= core).mean()), 4)}]}
    box = (0, 0, w, h)

    for _ in range(max(0, passes - 1)):
        nb = _focus_box(alpha, core, margin)
        if nb is None:
            break
        x0, y0, x1, y1 = nb
        # 聚焦框相对上一轮没明显收紧就停：再裁下去只是白跑一遍推理
        prev_area = (box[2] - box[0]) * (box[3] - box[1])
        if prev_area > 0 and ((x1 - x0) * (y1 - y0)) / prev_area > 0.92:
            break
        sub = rgb[y0:y1, x0:x1]
        sub_alpha = _infer(sub, session, infer_side)
        alpha = np.zeros((h, w), dtype=np.uint8)
        alpha[y0:y1, x0:x1] = sub_alpha
        box = (x0, y0, x1, y1)
        info['passes'].append({'box': box,
                               'fg_ratio': round(float((sub_alpha >= core).mean()), 4)})
    info['final_box'] = box
    return alpha, info


def _focus_box(alpha: np.ndarray, core: int, margin: float):
    m = alpha >= core
    if not m.any():
        return None
    ys = np.flatnonzero(m.any(axis=1))
    xs = np.flatnonzero(m.any(axis=0))
    y0, y1 = int(ys[0]), int(ys[-1]) + 1
    x0, x1 = int(xs[0]), int(xs[-1]) + 1
    pad = int(round(max(y1 - y0, x1 - x0) * margin))
    h, w = alpha.shape
    return (max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad))


def _box_filter(x: np.ndarray, r: int) -> np.ndarray:
    return ndimage.uniform_filter(x, size=2 * r + 1, mode='nearest')


def guided_refine(alpha: np.ndarray, rgb: np.ndarray, radius: int = 6, eps: float = 1e-4) -> np.ndarray:
    """以原图灰度为引导图细化 alpha（He et al. guided filter）。

    模型输出是低分辨率上采样来的，边缘发虚；引导滤波把 alpha 的边界
    重新贴回原图真实边缘，比单纯锐化/阈值靠谱。
    """
    guide = np.asarray(Image.fromarray(rgb).convert('L'), dtype=np.float32) / 255.0
    p = alpha.astype(np.float32) / 255.0
    mean_i = _box_filter(guide, radius)
    mean_p = _box_filter(p, radius)
    var_i = _box_filter(guide * guide, radius) - mean_i * mean_i
    cov_ip = _box_filter(guide * p, radius) - mean_i * mean_p
    a = cov_ip / (var_i + eps)
    b = mean_p - a * mean_i
    q = _box_filter(a, radius) * guide + _box_filter(b, radius)
    return (q.clip(0, 1) * 255.0).astype(np.uint8)


def clean_mask(alpha: np.ndarray, core: int = 150, min_area_ratio: float = 0.0015,
               max_hole_ratio: float = 0.02) -> np.ndarray:
    """按强 alpha 取核心区，去掉碎屑和小孔，返回二值 mask（bool）。

    core 取得高是故意的：matte 模型对「不确定的陪衬物」（鞋子、毯子）
    往往只给半透明 alpha，先按强度砍一刀能让后面的连通域更干净。
    这只是预筛，真正的取舍仍由语义闸门决定。
    """
    m = alpha >= core
    if not m.any():
        m = alpha >= max(32, core // 2)
    m = ndimage.binary_opening(m, structure=np.ones((3, 3)), iterations=2)
    m = ndimage.binary_closing(m, structure=np.ones((5, 5)), iterations=2)
    m = fill_small_holes(m, max_hole_ratio)
    labels, n = ndimage.label(m)
    if n == 0:
        return m
    total = float(m.shape[0] * m.shape[1])
    sizes = ndimage.sum(m, labels, index=np.arange(1, n + 1))
    keep = np.zeros(n + 1, dtype=bool)
    for i, s in enumerate(sizes, start=1):
        if s / total >= min_area_ratio:
            keep[i] = True
    return keep[labels]


def fill_small_holes(mask: np.ndarray, max_hole_ratio: float = 0.02) -> np.ndarray:
    """只补小洞，不补大洞。

    绝对不能用 ndimage.binary_fill_holes：两只袜子在鞋头和花边处互相搭住，
    它们之间那条地毯缝隙在拓扑上是一个「洞」，无脑填洞会把一条地毯当成
    袜子的一部分保留下来（实测 01_大花边 就是这么坏的）。
    这里按洞的面积占主体面积的比例决定填不填，只抹掉真正的噪声孔。
    """
    holes = ndimage.binary_fill_holes(mask) & ~mask
    if not holes.any():
        return mask
    hl, hn = ndimage.label(holes)
    if hn == 0:
        return mask
    subject_area = float(mask.sum())
    sizes = ndimage.sum(holes, hl, index=np.arange(1, hn + 1))
    fill = np.zeros(hn + 1, dtype=bool)
    for i, sz in enumerate(sizes, start=1):
        if subject_area > 0 and sz / subject_area <= max_hole_ratio:
            fill[i] = True
    return mask | fill[hl]


def tighten_alpha(alpha: np.ndarray, lo: float = 0.35, hi: float = 0.95) -> np.ndarray:
    """收紧 alpha 的软边：线性重映射 [lo, hi] → [0, 1]。

    地毯的绒毛/毛圈会被 matte 判成半透明 alpha，贴到白底上就是袜子边上挂一圈
    毛边。抬高下界能把这层软毛边压掉。

    实测（01_大花边 的蕾丝花边区域，lo=0/0.28/0.40/0.55 四档对比）：
    到 lo=0.55 蕾丝的锯齿边仍然完整，说明这个模型的 alpha 本身够硬，收紧不吃
    产品细节；但也说明剩下的毛边是模型**当成实前景**给进来的地毯纤维，
    单靠收紧去不掉，只能靠更好的 matte 模型。默认取 0.35 —— 软毛边收干净，
    离实测到的安全上限还有余量。
    """
    a = alpha.astype(np.float32) / 255.0
    span = max(1e-6, hi - lo)
    a = (a - lo) / span
    return (np.clip(a, 0.0, 1.0) * 255.0).astype(np.uint8)

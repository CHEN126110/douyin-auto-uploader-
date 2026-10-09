# -*- coding: utf-8 -*-
"""袜子白底图的几何归一化：转正（去倾斜）→ 裁主体 → 缩放 → 1:1 白底居中。

所有函数都只吃 (RGB ndarray, alpha ndarray)，不依赖任何模型，便于单独验证。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy import ndimage


@dataclass
class AxisInfo:
    """单个连通域的主轴信息。"""
    label: int
    area: int
    angle_deg: float      # 主轴与「垂直方向」的夹角，右倾为正，范围 (-90, 90]
    elongation: float     # 长轴/短轴，越大越像细长的袜筒
    centroid: tuple[float, float]


def component_axes(mask: np.ndarray, labels: np.ndarray, label_ids) -> list[AxisInfo]:
    """对每个连通域做 PCA，求它自己的长轴方向。

    注意：不能对「整对袜子」的并集做 PCA —— 两只袜子并排时并集的主轴会偏向
    水平（并排方向），转正会把袜子转倒。必须逐只求角度再做圆均值。
    """
    out: list[AxisInfo] = []
    for lb in label_ids:
        ys, xs = np.nonzero(labels == lb)
        if ys.size < 32:
            continue
        w = mask[ys, xs].astype(np.float64) / 255.0
        wsum = w.sum()
        if wsum <= 0:
            continue
        cy = float((ys * w).sum() / wsum)
        cx = float((xs * w).sum() / wsum)
        dy = ys - cy
        dx = xs - cx
        cxx = float((w * dx * dx).sum() / wsum)
        cyy = float((w * dy * dy).sum() / wsum)
        cxy = float((w * dx * dy).sum() / wsum)
        cov = np.array([[cxx, cxy], [cxy, cyy]], dtype=np.float64)
        vals, vecs = np.linalg.eigh(cov)          # eigh 升序
        major = vecs[:, -1]                        # (vx, vy) 长轴方向
        minor_val, major_val = float(vals[0]), float(vals[-1])
        elong = math.sqrt(major_val / minor_val) if minor_val > 1e-9 else float('inf')
        vx, vy = float(major[0]), float(major[1])
        # 长轴与「垂直(0,1)」的夹角：袜子竖直时为 0，右倾为正
        ang = math.degrees(math.atan2(vx, abs(vy) if vy != 0 else 1e-9))
        ang = ((ang + 90.0) % 180.0) - 90.0        # 归到 (-90, 90]
        out.append(AxisInfo(int(lb), int(ys.size), ang, elong, (cx, cy)))
    return out


def robust_tilt(axes: list[AxisInfo], min_elongation: float = 1.45,
                max_spread_deg: float = 20.0) -> tuple[float, dict]:
    """把多只袜子的倾角合成一个稳健的整体倾角，并给出「敢不敢转」的判断。

    返回 (tilt_deg, info)。info['confident'] 为 False 时**必须按 0° 处理**，
    不要退而求其次拿不可信的角度去转 —— 转错 90° 比不转难看得多。

    算法：
    - 角度是「轴向」量（mod 180°），用倍角圆均值，避免 +89°/-89° 平均成 0；
    - 权重 = 面积 × 细长度，大而细长的主体说话。

    两道护栏都是从 22 张实测图量出来的，不是拍的：
    - min_elongation：单双袜子平铺图的主体细长度实测 1.53~2.11；而
      「一排 6 只密排袜子」1.39、「篮子里一堆袜子」1.12、「手拿一把袜子」1.14。
      这三张的 PCA 长轴指的是**排列方向**不是袜筒方向，转正会把袜子转倒
      （主图_02 实测被转了 -87.8°）。阈值取 1.45 落在两组之间。
    - max_spread_deg：多个主体各自的角度必须彼此一致。ID-904889787428/主图_02
      实测两个域一个 -84.1° 一个 -5.5°，差 78.6°，说明这不是「一组平行的袜筒」，
      合成出来的 -75.8° 毫无意义。
    """
    finite = [a for a in axes if math.isfinite(a.elongation)]
    usable = [a for a in finite if a.elongation >= min_elongation]
    info = {
        'confident': False,
        'used': len(usable),
        'total': len(axes),
        'max_elongation': round(max((a.elongation for a in finite), default=0.0), 3),
        'spread_deg': None,
        'reason': '',
    }
    if not usable:
        info['reason'] = (f'主体不够细长（最大细长度 {info["max_elongation"]} < '
                          f'{min_elongation}），长轴方向不可信，不做转正')
        return 0.0, info

    sx = sy = 0.0
    for a in usable:
        w = float(a.area) * min(a.elongation, 8.0)
        th = math.radians(a.angle_deg * 2.0)
        sx += w * math.cos(th)
        sy += w * math.sin(th)
    if abs(sx) < 1e-12 and abs(sy) < 1e-12:
        info['reason'] = '各主体角度互相抵消，不做转正'
        return 0.0, info
    mean = math.degrees(math.atan2(sy, sx)) / 2.0
    mean = ((mean + 90.0) % 180.0) - 90.0

    spread = max((abs(_axis_delta(a.angle_deg, mean)) for a in usable), default=0.0)
    info['spread_deg'] = round(spread, 2)
    if spread > max_spread_deg:
        info['reason'] = (f'各主体长轴方向不一致（最大偏差 {spread:.1f}° > '
                          f'{max_spread_deg}°），不像一组平行的袜筒，不做转正')
        return 0.0, info

    info['confident'] = True
    return mean, info


def _axis_delta(a: float, b: float) -> float:
    """两个轴向角之差，归到 (-90, 90]。"""
    return ((a - b + 90.0) % 180.0) - 90.0


def rotate_rgba(rgb: np.ndarray, alpha: np.ndarray, angle_deg: float):
    """绕画面中心旋转 RGB+alpha。角度为「主体当前倾角」，函数内部取反转正。

    expand=True 保证旋转后主体不被裁掉；alpha 用双线性、RGB 用双三次。
    旋转前把透明区域的 RGB 填成主体边缘色，避免插值把背景色吸进边缘。
    """
    if abs(angle_deg) < 0.05:
        return rgb, alpha
    rgb_filled = _bleed_edge_color(rgb, alpha)
    im_rgb = Image.fromarray(rgb_filled)
    im_a = Image.fromarray(alpha)
    rot_rgb = im_rgb.rotate(-angle_deg, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))
    rot_a = im_a.rotate(-angle_deg, resample=Image.BILINEAR, expand=True, fillcolor=0)
    return np.asarray(rot_rgb), np.asarray(rot_a)


def _bleed_edge_color(rgb: np.ndarray, alpha: np.ndarray, iters: int = 6) -> np.ndarray:
    """把主体颜色向透明侧外扩几像素。

    不做这一步的话，旋转/缩放的插值会在主体边缘混入未定义的背景像素，
    抠出来的袜子边缘会挂一圈原背景的米色。
    """
    out = rgb.astype(np.float32).copy()
    known = (alpha > 8)
    if not known.any():
        return rgb
    for _ in range(iters):
        unknown = ~known
        if not unknown.any():
            break
        # 用已知区域的 3x3 均值填充紧邻的未知像素
        k = known.astype(np.float32)
        cnt = ndimage.uniform_filter(k, size=3, mode='nearest')
        acc = np.stack([ndimage.uniform_filter(out[:, :, c] * k, size=3, mode='nearest')
                        for c in range(3)], axis=-1)
        fill = unknown & (cnt > 1e-4)
        if not fill.any():
            break
        out[fill] = (acc[fill] / cnt[fill][:, None])
        known = known | fill
    return out.clip(0, 255).astype(np.uint8)


def subject_bbox(alpha: np.ndarray, thresh: int = 8) -> tuple[int, int, int, int] | None:
    """主体外接框 (x0, y0, x1, y1)，右下开区间。"""
    m = alpha > thresh
    if not m.any():
        return None
    ys = np.flatnonzero(m.any(axis=1))
    xs = np.flatnonzero(m.any(axis=0))
    return int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1


def compose_square_white(
    rgb: np.ndarray,
    alpha: np.ndarray,
    canvas: int = 1200,
    fill_ratio: float = 0.82,
    max_upscale: float = 1.45,
) -> tuple[Image.Image, dict]:
    """裁主体 → 等比缩放到目标占比 → 贴到 canvas×canvas 白底正中。

    fill_ratio 指主体长边占画布边长的比例（抖店白底图建议主体占比大、留白均匀）。
    max_upscale 限制放大倍数，避免小主体被拉成糊图；1.45 是实测上限，
    权威默认值在 pipeline.Config.max_upscale，这里的默认值只是跟它保持一致。
    """
    box = subject_bbox(alpha)
    if box is None:
        raise ValueError('alpha 全空，没有可用主体')
    x0, y0, x1, y1 = box
    crop_rgb = _bleed_edge_color(rgb, alpha)[y0:y1, x0:x1]
    crop_a = alpha[y0:y1, x0:x1]
    h, w = crop_a.shape
    long_side = max(h, w)

    target_long = canvas * float(fill_ratio)
    scale = target_long / float(long_side)
    scale = min(scale, max_upscale)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    # 缩放后仍要装得进画布
    if new_w > canvas or new_h > canvas:
        shrink = min(canvas / new_w, canvas / new_h)
        new_w = max(1, int(new_w * shrink))
        new_h = max(1, int(new_h * shrink))

    resample = Image.LANCZOS if scale < 1 else Image.BICUBIC
    rgb_s = np.asarray(Image.fromarray(crop_rgb).resize((new_w, new_h), resample))
    a_s = np.asarray(Image.fromarray(crop_a).resize((new_w, new_h), resample))

    out = np.full((canvas, canvas, 3), 255.0, dtype=np.float32)
    ox = (canvas - new_w) // 2
    oy = (canvas - new_h) // 2
    a_f = a_s.astype(np.float32)[:, :, None] / 255.0
    region = out[oy:oy + new_h, ox:ox + new_w, :]
    out[oy:oy + new_h, ox:ox + new_w, :] = rgb_s.astype(np.float32) * a_f + region * (1 - a_f)

    meta = {
        'crop_box': (x0, y0, x1, y1),
        'crop_size': (w, h),
        'scale': round(float(new_w) / float(w), 4),
        'placed_size': (new_w, new_h),
        'offset': (ox, oy),
        'fill_ratio_actual': round(max(new_w, new_h) / float(canvas), 4),
        'margin_lr': (ox, canvas - new_w - ox),
        'margin_tb': (oy, canvas - new_h - oy),
    }
    return Image.fromarray(out.clip(0, 255).astype(np.uint8)), meta


def square_original(rgb: np.ndarray, subject_box=None, size: int | None = None,
                    pad_color=(255, 255, 255)) -> tuple[Image.Image, dict]:
    """把原图做成 1:1，尽量不丢主体、不改画面内容。

    平台要求规格图长宽比 1:1，而采集下来的 SKU 图是 1440×1919（3:4）。
    两种做法各有代价，这里按「能装下主体就裁，装不下就补白」选：

    1. 优先在原分辨率上裁一个边长 = min(宽,高) 的正方形，位置沿长边滑动，
       保证完整包住主体外框（subject_box）。不放大、不补白、不改构图，
       只丢掉主体之外的背景 —— 实测 1440×1919 的图里主体只占 y[661,1649)，
       1440 的窗口装得下。
    2. 主体本身超过短边装不下时，退回补白：把整图贴到 max(宽,高) 的白底方图正中，
       一个像素的主体都不丢。

    subject_box 传 None 就按画面中心裁，不保证主体完整。
    """
    h, w = rgb.shape[:2]
    short, long_side = min(h, w), max(h, w)
    meta: dict = {'src_size': (w, h)}

    need = None
    if subject_box is not None:
        x0, y0, x1, y1 = subject_box
        need = (x1 - x0, y1 - y0)

    if need is None or (need[0] <= short and need[1] <= short):
        side = short
        if w >= h:                      # 横图：沿 x 滑动
            off = (w - side) // 2 if need is None else _slide(subject_box[0], subject_box[2], side, w)
            box = (off, 0, off + side, side)
        else:                           # 竖图：沿 y 滑动
            off = (h - side) // 2 if need is None else _slide(subject_box[1], subject_box[3], side, h)
            box = (0, off, side, off + side)
        meta.update({'mode': 'crop', 'crop_box': box, 'out_size': (side, side)})
        out = Image.fromarray(rgb).crop(box)
    else:
        side = long_side
        canvas = Image.new('RGB', (side, side), tuple(pad_color))
        ox, oy = (side - w) // 2, (side - h) // 2
        canvas.paste(Image.fromarray(rgb), (ox, oy))
        meta.update({'mode': 'pad', 'offset': (ox, oy), 'out_size': (side, side),
                     'note': '主体超过短边，改为补白，避免裁掉主体'})
        out = canvas

    if size and out.width != size:
        resample = Image.LANCZOS if out.width > size else Image.BICUBIC
        out = out.resize((size, size), resample)
        meta['resized_to'] = size
    return out, meta


def _slide(lo: int, hi: int, side: int, limit: int) -> int:
    """在 [0, limit-side] 范围内选窗口起点，使 [lo,hi) 尽量居中且完整落在窗口内。"""
    center = (lo + hi) // 2
    off = center - side // 2
    off = max(0, min(off, limit - side))
    # 主体没被完整包住就把窗口推回去（能装下的前提下一定推得进来）
    if lo < off:
        off = max(0, lo)
    if hi > off + side:
        off = min(limit - side, hi - side)
    return int(off)

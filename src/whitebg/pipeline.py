# -*- coding: utf-8 -*-
"""袜子白底图流水线：语义抠图 → 只留袜子 → 转正 → 1:1 白底居中。

顺序（每一步都可单独出调试图）：
  A. scene      整图场景判断，穿着图直接拒绝 —— 穿在脚上的袜子做不出白底图
  B. matte      通用 matte 模型给出前景 alpha（含鞋子/毯子等陪衬物）
  C. component  强 alpha 取核心 → 形态学清理 → 连通域拆成独立物体
  D. semantic   每个连通域送 CLIP 零样本分类，只保留 sock 组
  E. gate       用「到保留域 / 到丢弃域」的距离做 Voronoi 闸门，
                保住袜子的软边，同时把靠近鞋子的像素彻底清零
  F. deskew     逐只袜子 PCA 求长轴 → 倍角圆均值 → 整体转正
                三道护栏：场景不是群图 / 主体够细长 / 多主体方向一致
  G. compose    裁主体 → 按目标占比缩放 → 贴到 canvas×canvas 白底正中

设计原则：宁可明确拒绝，不要悄悄输出错的图。拒绝都带 code + 可读原因 +
判定数据，方便前端如实展示给人看。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
from PIL import Image
from scipy import ndimage

from . import matte as matte_mod
from . import geometry as geo
from . import paths as model_paths
from .clip_gate import ClipGate, SceneClassifier, crop_for_clip


class UnsuitableSource(Exception):
    """这张图做不出可用的白底图。code 给机器看，message 给人看。"""

    def __init__(self, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


@dataclass
class Config:
    matte_model: str = 'birefnet-general'
    # 留空则按 paths.resolve_model_dir() 解析（环境变量 → 运行数据目录 → 仓库 models/）
    rembg_home: str | None = None
    clip_dir: str | None = None
    infer_side: int = 1024
    focus_passes: int = 2             # matte 二次聚焦轮数（1=只跑全图一遍）
    focus_margin: float = 0.08
    tighten_lo: float = 0.35          # alpha 软边收紧下界（0 = 不收紧）
    tighten_hi: float = 0.95
    core_alpha: int = 150             # 取核心区的 alpha 阈值
    min_area_ratio: float = 0.0015    # 小于画面这个比例的连通域直接当碎屑
    max_hole_ratio: float = 0.02      # 只补小于主体这个比例的洞（大洞是真缝隙）
    sock_prob: float = 0.45           # CLIP 判定为袜子的最低概率
    sock_margin: float = 0.15         # 还要领先第二名语义组这么多才算数
    soft_band: int = 14               # 保留域外可以保留软边的像素半径
    reject_worn: bool = True          # 穿着图（脚/腿）直接拒绝
    worn_prob: float = 0.35           # 判定为穿着图的概率门槛
    min_elongation: float = 1.45      # 敢转正所需的主体细长度
    max_axis_spread: float = 20.0     # 多主体长轴方向的最大允许偏差
    # 场景侧的转正闸门：many/packaged 领先 single_pair 超过这个值就不转。
    # 细长度那道护栏是照 bria-rmbg 的 mask 校的，换 birefnet-general 之后它的
    # mask 更干净、细长度更高（主图_02 从 1.39 升到 1.47），直接从 1.45 底下溜过去
    # 被转了 -87.5°。场景判断只看整图、不看 matte，所以这道闸门与模型无关。
    # 实测 22 张：该转的 8 张领先度 -0.58~-0.04，转错的 8 张 +0.38~+0.96，
    # 中间空档 0.42，阈值取 0.20。
    deskew_group_margin: float = 0.20
    canvas: int = 1440
    fill_ratio: float = 0.82          # 主体长边占画布边长的比例
    # 1.45 是实测出来的上限：同一张图在 1200/1440/1600/1919 画布上对比，
    # 放大到 1.42 倍袜口织纹开始发软，1.60 倍明显糊。
    max_upscale: float = 1.45
    warn_upscale: float = 1.30        # 放大超过这个倍数就提示画质被拉伸
    deskew: bool = True
    debug: bool = True


@dataclass
class Result:
    image: Image.Image
    verdicts: list = field(default_factory=list)
    tilt_deg: float = 0.0
    tilt_info: dict = field(default_factory=dict)
    scene: dict = field(default_factory=dict)
    compose_meta: dict = field(default_factory=dict)
    debug: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


class SockWhiteBg:
    """可复用的处理器：模型只加载一次，批量处理同一商品的多张图。"""

    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        base = model_paths.resolve_model_dir(self.cfg.matte_model)
        rembg_home = self.cfg.rembg_home or str(model_paths.rembg_home(base))
        clip_dir = self.cfg.clip_dir or str(model_paths.clip_dir(base))
        self.model_dir = str(base)
        self.session = matte_mod.make_session(self.cfg.matte_model, rembg_home)
        self.gate = ClipGate(clip_dir)
        self.scene = SceneClassifier(self.gate)

    # ---------------- 主流程 ----------------
    def process(self, image_path: str) -> Result:
        cfg = self.cfg
        src = Image.open(image_path).convert('RGB')
        rgb = np.asarray(src)
        warnings: list = []

        # A. 场景判断（先做，不合格的图省下后面的 matte 推理）
        scene = self.scene.classify([src])[0]
        sg = scene['groups']
        if cfg.reject_worn and scene['top'] == 'worn' and sg.get('worn', 0.0) >= cfg.worn_prob:
            raise UnsuitableSource(
                'worn_source',
                f'这是穿着图（脚/腿上的袜子，判定概率 {sg["worn"]:.2f}），'
                f'袜子和腿是连在一起的，抠不出单独的袜子，不能当白底图来源',
                {'scene': sg})
        # 群图/包装图的提醒只在 F 步说一次（那里连「所以不转正」一起讲），
        # 这里再加一条就是同一件事说两遍，界面上是噪声

        # B. matte（二次聚焦，解决两只袜子之间的缝隙分不开）
        alpha_raw, focus_info = matte_mod.focused_alpha(
            rgb, self.session, cfg.infer_side, cfg.focus_passes, cfg.focus_margin)
        alpha_ref = matte_mod.guided_refine(alpha_raw, rgb)
        if cfg.tighten_lo > 0 or cfg.tighten_hi < 1:
            alpha_ref = matte_mod.tighten_alpha(alpha_ref, cfg.tighten_lo, cfg.tighten_hi)

        # C. 连通域
        core = matte_mod.clean_mask(alpha_ref, cfg.core_alpha, cfg.min_area_ratio,
                                    cfg.max_hole_ratio)
        labels, n = ndimage.label(core)
        if n == 0:
            raise UnsuitableSource('no_foreground', 'matte 没有分出任何前景主体',
                                   {'matte_model': cfg.matte_model})

        # D. 语义闸门
        crops, ids = [], []
        for lb in range(1, n + 1):
            crops.append(crop_for_clip(rgb, labels == lb))
            ids.append(lb)
        scored = self.gate.score(crops)

        verdicts = []
        for lb, sc in zip(ids, scored):
            g = sc['groups']
            runner_up = max(g['shoe'], g['other'])
            kept = (g['sock'] >= cfg.sock_prob
                    and g['sock'] - runner_up >= cfg.sock_margin)
            verdicts.append({
                'label': lb,
                'kept': bool(kept),
                'area_px': int((labels == lb).sum()),
                'sock': round(g['sock'], 4),
                'shoe': round(g['shoe'], 4),
                'other': round(g['other'], 4),
                'margin': round(g['sock'] - runner_up, 4),
                'top_prompt': sc['top_prompt'],
                'reason': 'sock' if kept else ('shoe' if g['shoe'] >= g['other'] else 'other'),
            })

        keep_ids = [v['label'] for v in verdicts if v['kept']]
        drop_ids = [v['label'] for v in verdicts if not v['kept']]
        if not keep_ids:
            best = max(verdicts, key=lambda v: v['sock'])
            raise UnsuitableSource(
                'no_sock_found',
                f'语义闸门没有在画面里认出袜子（最像袜子的主体只有 '
                f'{best["sock"]:.2f}，需要 ≥{cfg.sock_prob} 且领先第二名 '
                f'≥{cfg.sock_margin}）',
                # 顺带把 matte 认出来的主体外框带出去：白底图做不出来，
                # 但「原场景裁成 1:1」还能靠它避免把商品裁掉，别退化成中心裁剪
                {'verdicts': verdicts, 'scene': sg,
                 'subject_box': geo.subject_bbox(np.where(core, 255, 0).astype(np.uint8))})

        # E. Voronoi 软边闸门
        keep_core = np.isin(labels, keep_ids)
        drop_core = np.isin(labels, drop_ids) if drop_ids else np.zeros_like(keep_core)
        d_keep = ndimage.distance_transform_edt(~keep_core)
        if drop_core.any():
            d_drop = ndimage.distance_transform_edt(~drop_core)
            gate_mask = (d_keep <= cfg.soft_band) & (d_keep < d_drop)
        else:
            gate_mask = d_keep <= cfg.soft_band
        alpha = np.where(gate_mask, alpha_ref, 0).astype(np.uint8)
        # 核心区必须实心，避免袜子内部被 alpha 抖动打出洞
        alpha = np.maximum(alpha, np.where(keep_core, 255, 0)).astype(np.uint8)

        # F. 转正（不可信就按 0° 处理，绝不拿不可信的角度去转）
        tilt = 0.0
        tilt_info: dict = {'confident': False, 'reason': '未启用转正'}
        axes = []
        group_lead = max(sg.get('many', 0.0), sg.get('packaged', 0.0)) - sg.get('single_pair', 0.0)
        if cfg.deskew and group_lead >= cfg.deskew_group_margin:
            tilt_info = {
                'confident': False,
                'used': 0,
                'total': 0,
                'group_lead': round(group_lead, 4),
                'reason': (f'图源是多双合拍或以包装为主体的图（判定为「{scene["top"]}」，'
                           f'比单品判定高 {group_lead:+.2f}）：白底图里可能不止一双袜子，'
                           f'而且画面里没有一双平行的袜子可以对齐，所以不做转正'),
            }
            warnings.append(tilt_info['reason'])
        elif cfg.deskew:
            axes = geo.component_axes(alpha, labels, keep_ids)
            tilt, tilt_info = geo.robust_tilt(axes, cfg.min_elongation, cfg.max_axis_spread)
            tilt_info['group_lead'] = round(group_lead, 4)
            if not tilt_info['confident'] and tilt_info.get('reason'):
                warnings.append(tilt_info['reason'])
        rgb_r, alpha_r = geo.rotate_rgba(rgb, alpha, tilt)

        # G. 1:1 白底居中
        final, meta = geo.compose_square_white(
            rgb_r, alpha_r, cfg.canvas, cfg.fill_ratio, cfg.max_upscale)
        # 原图坐标系下的主体外框：转正前算，给「原场景裁成 1:1」复用，
        # 免得那边为了找主体再跑一遍 matte
        meta['subject_box_src'] = geo.subject_bbox(alpha)
        if meta['scale'] > cfg.warn_upscale:
            warnings.append(f'主体偏小，放大了 {meta["scale"]:.2f} 倍才凑到 '
                            f'{cfg.fill_ratio:.0%} 占比，边缘会偏软')
        if meta['fill_ratio_actual'] < cfg.fill_ratio - 0.05:
            warnings.append(f'主体占比只有 {meta["fill_ratio_actual"]:.0%}，'
                            f'低于目标 {cfg.fill_ratio:.0%}（受 max_upscale 限制）')

        debug = {}
        if cfg.debug:
            debug = {
                'alpha_raw': alpha_raw,
                'alpha_ref': alpha_ref,
                'alpha_final': alpha_r,
                'labels': labels,
                'n_components': n,
                'crops': crops,
                'axes': [(a.label, round(a.angle_deg, 2), round(a.elongation, 2), a.area)
                         for a in axes],
                'focus': focus_info,
            }
        return Result(final, verdicts, round(float(tilt), 3), tilt_info, sg,
                      meta, debug, warnings)

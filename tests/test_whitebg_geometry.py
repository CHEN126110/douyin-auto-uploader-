# -*- coding: utf-8 -*-
"""白底图流水线里不依赖模型的那些逻辑 —— 几何归一化和 alpha 处理。

这些测试用合成 mask，不加载任何 ONNX 模型，所以可以在没装模型的机器上跑。
覆盖的都是实测踩过的坑：
  - 「一排密排袜子」的 PCA 长轴指向排列方向，转正会把袜子转倒 87.8°
  - `binary_fill_holes` 会把两只袜子之间的地毯缝隙当成洞填实
  - 1:1 画布必须严格方形、主体必须居中、放大倍数必须受限
"""
from __future__ import annotations

import math
import os
import sys
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.whitebg import geometry as geo
from src.whitebg import matte as matte_mod


def bar_mask(shape, center, half_w, half_h, angle_deg):
    """画一根绕中心旋转 angle_deg 的实心长条（模拟一只袜筒）。

    angle_deg 用和 geometry 一致的口径：长轴相对垂直方向，右倾为正。
    """
    h, w = shape
    ys, xs = np.mgrid[0:h, 0:w]
    cy, cx = center
    t = math.radians(angle_deg)
    # 把像素坐标转到长条自身的坐标系：长轴为 v，短轴为 u
    dx = xs - cx
    dy = ys - cy
    u = dx * math.cos(t) - dy * math.sin(t)
    v = dx * math.sin(t) + dy * math.cos(t)
    return (np.abs(u) <= half_w) & (np.abs(v) <= half_h)


def labeled(masks):
    """把若干 mask 合成 (alpha, labels)，标号从 1 开始。"""
    shape = masks[0].shape
    labels = np.zeros(shape, dtype=np.int32)
    for i, m in enumerate(masks, start=1):
        labels[m] = i
    alpha = np.where(labels > 0, 255, 0).astype(np.uint8)
    return alpha, labels


class TestRobustTilt(unittest.TestCase):
    def test_一对平行袜筒能求出倾角(self):
        shape = (900, 700)
        a = bar_mask(shape, (450, 280), 55, 300, -20.0)
        b = bar_mask(shape, (450, 430), 55, 300, -20.0)
        alpha, labels = labeled([a, b])
        axes = geo.component_axes(alpha, labels, [1, 2])
        tilt, info = geo.robust_tilt(axes)
        self.assertTrue(info['confident'], info)
        self.assertAlmostEqual(tilt, -20.0, delta=2.0)

    def test_矮胖实心块不敢转正(self):
        """密排成一行的袜子，mask 就是个实心矩形，长轴指的是排列方向。

        实测 ID-1075636304051/主图_02 细长度 1.39 时 PCA 给了 -87.8°，
        照着转就把袜子转倒了。护栏必须在这里拦住。
        """
        shape = (900, 900)
        block = bar_mask(shape, (450, 450), 380, 280, 0.0)   # 宽 760 高 560
        alpha, labels = labeled([block])
        axes = geo.component_axes(alpha, labels, [1])
        self.assertLess(axes[0].elongation, 1.45)
        tilt, info = geo.robust_tilt(axes)
        self.assertFalse(info['confident'])
        self.assertEqual(tilt, 0.0)
        self.assertIn('细长度', info['reason'])

    def test_两个主体方向打架时不敢转正(self):
        """实测 ID-904889787428/主图_02 两个域差 78.6°，合成角度毫无意义。"""
        shape = (900, 900)
        a = bar_mask(shape, (300, 300), 50, 250, -80.0)
        b = bar_mask(shape, (650, 650), 50, 250, 0.0)
        alpha, labels = labeled([a, b])
        axes = geo.component_axes(alpha, labels, [1, 2])
        tilt, info = geo.robust_tilt(axes)
        self.assertFalse(info['confident'])
        self.assertEqual(tilt, 0.0)
        self.assertGreater(info['spread_deg'], 20.0)

    def test_倍角圆均值不会把正负89度平均成0(self):
        """+89° 和 -89° 其实只差 2°，普通算术平均会给出 0°，转正就废了。"""
        shape = (900, 900)
        a = bar_mask(shape, (300, 450), 50, 300, 89.0)
        b = bar_mask(shape, (600, 450), 50, 300, -89.0)
        alpha, labels = labeled([a, b])
        axes = geo.component_axes(alpha, labels, [1, 2])
        tilt, info = geo.robust_tilt(axes)
        self.assertTrue(info['confident'], info)
        self.assertGreater(abs(tilt), 80.0)


class TestComposeSquareWhite(unittest.TestCase):
    def setUp(self):
        # 主体高 801px：在 1200 画布上按 0.82 只需放大 1.23 倍，不会撞上
        # max_upscale 上限 —— 上限本身由 test_放大倍数受max_upscale限制 单独覆盖
        shape = (900, 700)
        self.mask = bar_mask(shape, (450, 350), 60, 400, 0.0)
        self.alpha = np.where(self.mask, 255, 0).astype(np.uint8)
        self.rgb = np.zeros(shape + (3,), dtype=np.uint8)
        self.rgb[self.mask] = (40, 90, 160)

    def test_输出严格1比1(self):
        img, _ = geo.compose_square_white(self.rgb, self.alpha, canvas=1440)
        self.assertEqual(img.size, (1440, 1440))

    def test_主体居中且长边占比达标(self):
        img, meta = geo.compose_square_white(self.rgb, self.alpha,
                                             canvas=1200, fill_ratio=0.82)
        self.assertLessEqual(abs(meta['margin_lr'][0] - meta['margin_lr'][1]), 1)
        self.assertLessEqual(abs(meta['margin_tb'][0] - meta['margin_tb'][1]), 1)
        self.assertAlmostEqual(meta['fill_ratio_actual'], 0.82, delta=0.01)

        # 再从成品像素上验一遍居中，不只信 meta
        arr = np.asarray(img)
        nonwhite = (arr < 250).any(axis=2)
        ys = np.flatnonzero(nonwhite.any(axis=1))
        xs = np.flatnonzero(nonwhite.any(axis=0))
        cy = (int(ys[0]) + int(ys[-1])) / 2
        cx = (int(xs[0]) + int(xs[-1])) / 2
        self.assertAlmostEqual(cy, 1200 / 2, delta=2)
        self.assertAlmostEqual(cx, 1200 / 2, delta=2)

    def test_背景是纯白(self):
        img, _ = geo.compose_square_white(self.rgb, self.alpha, canvas=600)
        arr = np.asarray(img)
        self.assertEqual(tuple(arr[2, 2]), (255, 255, 255))
        self.assertEqual(tuple(arr[-3, -3]), (255, 255, 255))

    def test_放大倍数受max_upscale限制(self):
        small = np.zeros((200, 200), dtype=np.uint8)
        small[80:120, 90:110] = 255
        rgb = np.zeros((200, 200, 3), dtype=np.uint8)
        rgb[small > 0] = (10, 10, 10)
        _img, meta = geo.compose_square_white(rgb, small, canvas=1440,
                                              fill_ratio=0.82, max_upscale=1.45)
        self.assertLessEqual(meta['scale'], 1.45 + 1e-6)
        # 被限制之后占比必然低于目标，这是有意的：宁可留白也不糊图
        self.assertLess(meta['fill_ratio_actual'], 0.82)

    def test_alpha全空时明确报错(self):
        empty = np.zeros((100, 100), dtype=np.uint8)
        rgb = np.zeros((100, 100, 3), dtype=np.uint8)
        with self.assertRaises(ValueError):
            geo.compose_square_white(rgb, empty)


class TestSquareOriginal(unittest.TestCase):
    def test_竖图裁成方图且主体完整(self):
        """1440×1919 的采集图裁成 1440×1440，主体不能被切到。"""
        rgb = np.full((1919, 1440, 3), 200, dtype=np.uint8)
        subject = (323, 661, 1105, 1649)          # 实测 01_大花边 的主体外框
        rgb[661:1649, 323:1105] = (30, 30, 30)
        img, meta = geo.square_original(rgb, subject)
        self.assertEqual(img.size, (1440, 1440))
        self.assertEqual(meta['mode'], 'crop')
        x0, y0, x1, y1 = meta['crop_box']
        self.assertLessEqual(y0, subject[1])
        self.assertGreaterEqual(y1, subject[3])
        # 主体像素确实还在
        arr = np.asarray(img)
        self.assertTrue((arr < 100).any())

    def test_主体超过短边时改为补白不裁掉主体(self):
        rgb = np.full((1000, 400, 3), 200, dtype=np.uint8)
        subject = (10, 10, 390, 990)              # 高 980 > 短边 400
        img, meta = geo.square_original(rgb, subject)
        self.assertEqual(meta['mode'], 'pad')
        self.assertEqual(img.size, (1000, 1000))

    def test_可以统一缩放到指定边长(self):
        rgb = np.full((1919, 1440, 3), 200, dtype=np.uint8)
        img, meta = geo.square_original(rgb, (323, 661, 1105, 1649), size=800)
        self.assertEqual(img.size, (800, 800))
        self.assertEqual(meta['resized_to'], 800)


class TestAlphaHelpers(unittest.TestCase):
    def test_大洞不补小洞补(self):
        """两只袜子之间那条地毯在拓扑上是个洞，无脑填洞会把地毯当袜子留下。"""
        mask = np.zeros((400, 400), dtype=bool)
        mask[50:350, 50:350] = True
        mask[100:300, 180:220] = False      # 大洞：8000px，占主体 ~9%
        mask[60:66, 60:66] = False          # 小洞：36px

        filled = matte_mod.fill_small_holes(mask, max_hole_ratio=0.02)
        self.assertFalse(filled[200, 200], '大洞被错误填实了')
        self.assertTrue(filled[62, 62], '小洞应该补掉')

    def test_收紧alpha把软边压到0把实心抬到255(self):
        alpha = np.array([[0, 60, 90, 130, 200, 250, 255]], dtype=np.uint8)
        out = matte_mod.tighten_alpha(alpha, lo=0.35, hi=0.95)
        self.assertEqual(out[0, 0], 0)
        self.assertEqual(out[0, 1], 0)       # 60/255=0.235 < 0.35 → 压成 0
        self.assertLessEqual(out[0, 2], 2)   # 90/255=0.353 刚过下界，几乎为 0
        self.assertGreater(out[0, 3], 0)
        self.assertEqual(out[0, 5], 255)     # 250/255=0.98 > 0.95 → 抬到 255
        self.assertEqual(out[0, 6], 255)
        # 单调不减
        self.assertTrue(np.all(np.diff(out[0].astype(int)) >= 0))

    def test_clean_mask丢掉碎屑保留主体(self):
        alpha = np.zeros((500, 500), dtype=np.uint8)
        alpha[100:400, 150:350] = 255        # 主体 60000px = 24%
        alpha[10:14, 10:14] = 255            # 碎屑 16px
        core = matte_mod.clean_mask(alpha, core=150, min_area_ratio=0.0015)
        self.assertTrue(core[250, 250])
        self.assertFalse(core[12, 12])


class TestModelPaths(unittest.TestCase):
    def test_缺模型时报出具体缺什么(self):
        import tempfile
        from src.whitebg import paths as model_paths
        with tempfile.TemporaryDirectory() as tmp:
            old = model_paths.os.environ.get(model_paths.MODEL_DIR_ENV)
            model_paths.os.environ[model_paths.MODEL_DIR_ENV] = tmp
            try:
                status = model_paths.model_status('bria-rmbg')
                self.assertFalse(status['ready'])
                self.assertTrue(status['missing'])
                self.assertTrue(any('bria-rmbg' in m for m in status['missing']))
            finally:
                if old is None:
                    model_paths.os.environ.pop(model_paths.MODEL_DIR_ENV, None)
                else:
                    model_paths.os.environ[model_paths.MODEL_DIR_ENV] = old


class TestPruneStale(unittest.TestCase):
    """清理旧产物的逻辑会删文件，必须确认它只删该删的。"""

    def setUp(self):
        import tempfile
        from src.whitebg import product
        self.product = product
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, name, body=b'x'):
        p = Path(self.tmp) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
        return p

    def test_只删本轮没产出的图片(self):
        self._touch('01_本轮.jpg')
        self._touch('主图_上一轮.jpg')
        removed = self.product._prune_stale(self.tmp, {'01_本轮.jpg'})
        self.assertEqual(removed, ['主图_上一轮.jpg'])
        self.assertTrue((Path(self.tmp) / '01_本轮.jpg').is_file())
        self.assertFalse((Path(self.tmp) / '主图_上一轮.jpg').is_file())

    def test_非图片一概不动(self):
        """报告、说明、用户自己放的东西都不许碰。"""
        self._touch('_report.json')
        self._touch('我自己放的说明.txt')
        self._touch('note.md')
        removed = self.product._prune_stale(self.tmp, set(), keep_names={'_report.json'})
        self.assertEqual(removed, [])
        for n in ('_report.json', '我自己放的说明.txt', 'note.md'):
            self.assertTrue((Path(self.tmp) / n).is_file(), n)

    def test_白名单里的文件不删(self):
        self._touch('_report.json')
        self._touch('旧图.jpg')
        removed = self.product._prune_stale(self.tmp, set(), keep_names={'_report.json'})
        self.assertEqual(removed, ['旧图.jpg'])
        self.assertTrue((Path(self.tmp) / '_report.json').is_file())

    def test_子目录不递归删(self):
        self._touch('sub/里面的图.jpg')
        removed = self.product._prune_stale(self.tmp, set())
        self.assertEqual(removed, [])
        self.assertTrue((Path(self.tmp) / 'sub' / '里面的图.jpg').is_file())

    def test_目录不存在时不报错(self):
        removed = self.product._prune_stale(os.path.join(self.tmp, '不存在'), set())
        self.assertEqual(removed, [])


if __name__ == '__main__':
    unittest.main()

# -*- coding: utf-8 -*-
"""诊断：CLIP 能不能判断「这张图适不适合做白底图源」。

为什么需要这一关（实测结论）：
  - ID-1075636304051/主图_02 是 6 只袜子密排站成一行，matte 出来就是一个实心
    矩形，单只袜子的轮廓信息全没了，PCA 求出的长轴是「排列方向」（水平），
    转正直接把袜子转倒 87.8°。这类图**几何上不可能**修对。
  - ID-904889787428/SKU/* 是一张 5 色对照图（还带葡萄、果盘、鲜花、文字标签），
    本身就没法为单个颜色生成白底图。
所以正确做法不是硬修几何，而是先判断图源类型，不合格的图明确报出来交给人。

分四类：
  single_pair 单个商品的平铺/立拍（唯一适合做白底图的）
  many        多双/多色合拍、陈列图
  worn        穿在脚上/腿上
  packaged    带包装袋、纸卡、吊牌为主体
"""
from __future__ import annotations

import glob
import os
import sys

import numpy as np
from PIL import Image

# 实现已搬到 src/whitebg/（单一真源），实验脚本从那里导入
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), 'src'))
from whitebg import paths as model_paths  # noqa: E402
from whitebg.clip_gate import ClipGate, _l2, _softmax, _preprocess  # noqa: E402

# 模型统一由 whitebg.paths 解析，实验室不再单独存一份副本
CLIP_DIR = str(model_paths.clip_dir(model_paths.resolve_model_dir()))
BASE = (r'C:\Users\CRB\AppData\Local\com.dyin.sock-publisher\uploads\products')

SCENE_PROMPTS = {
    'single_pair': [
        'a product photo of one pair of socks',
        'two socks laid flat side by side',
        'a single pair of socks on a plain surface',
        'one pair of socks photographed from above',
    ],
    'many': [
        'many different socks lined up in a row',
        'a collection of many pairs of socks',
        'a group of socks in different colors on display',
        'a shop display of many socks',
    ],
    'worn': [
        'a person wearing socks on their feet',
        'legs wearing socks',
        'feet in socks and shoes',
        'a model wearing socks',
    ],
    'packaged': [
        'socks sealed in plastic packaging bags',
        'socks with paper label bands',
        'packaged socks with price tags',
    ],
}

# 人工标注的期望分类，用来算准确率 —— 不写期望就只是「看着像对」
EXPECTED = {
    'ID-1075636304051/SKU': 'single_pair',
    'ID-1075636304051/主图/主图_01': 'many',
    'ID-1075636304051/主图/主图_02': 'many',
    'ID-1075636304051/主图/主图_03': 'many',
    'ID-1075636304051/主图/主图_04': 'single_pair',
    'ID-1075636304051/主图/主图_05': 'many',
    'ID-904889787428/SKU': 'many',
    'ID-904889787428/主图/主图_01': 'many',
    'ID-904889787428/主图/主图_02': 'many',
    'ID-904889787428/主图/主图_03': 'worn',
    'ID-904889787428/主图/主图_04': 'worn',
    'ID-904889787428/主图/主图_05': 'packaged',
}


def expected_for(rel: str):
    if rel in EXPECTED:
        return EXPECTED[rel]
    parent = rel.rsplit('/', 1)[0]
    return EXPECTED.get(parent)


class SceneClassifier:
    """复用 ClipGate 的 vision 塔，只换一套文本 prompt。"""

    def __init__(self, gate: ClipGate):
        self.gate = gate
        self.flat, self.group = [], []
        for g, ps in SCENE_PROMPTS.items():
            for p in ps:
                self.flat.append(p)
                self.group.append(g)
        self.text_emb = gate._encode_text(self.flat)
        self.groups = list(SCENE_PROMPTS.keys())

    def classify(self, images):
        batch = np.stack([_preprocess(im) for im in images], axis=0)
        emb = _l2(self.gate.vision.run([self.gate.v_out],
                                       {self.gate.v_in: batch})[0].astype(np.float32))
        probs = _softmax(100.0 * emb @ self.text_emb.T, axis=1)
        out = []
        for row in probs:
            g = {k: 0.0 for k in self.groups}
            for p, name in zip(row, self.group):
                g[name] += float(p)
            out.append(g)
        return out


def main():
    gate = ClipGate(CLIP_DIR)
    clf = SceneClassifier(gate)

    files = []
    for pid in ('ID-1075636304051', 'ID-904889787428'):
        for sub in ('SKU', '主图'):
            files += sorted(glob.glob(os.path.join(BASE, pid, sub, '*.jpg')))

    images = [Image.open(f).convert('RGB') for f in files]
    scores = clf.classify(images)

    hit = miss = unlabeled = 0
    print(f"{'图':<44}{'判定':<13}{'期望':<13}  single  many   worn  packaged")
    for f, s in zip(files, scores):
        rel = os.path.normpath(f).replace(os.sep, '/')
        rel = rel.split('products/')[-1]
        key = os.path.splitext(rel)[0]
        pred = max(s, key=s.get)
        exp = expected_for(key)
        if exp is None:
            unlabeled += 1
            mark = '?'
        elif pred == exp:
            hit += 1
            mark = ''
        else:
            miss += 1
            mark = '  <<< 不符'
        print(f'{key:<44}{pred:<13}{str(exp):<13}'
              f"{s['single_pair']:7.3f}{s['many']:7.3f}{s['worn']:7.3f}"
              f"{s['packaged']:9.3f}{mark}")
    total = hit + miss
    print(f'\n对 {hit}/{total}'
          f'{"，未标注 " + str(unlabeled) if unlabeled else ""}'
          f'{f"，准确率 {hit / total * 100:.0f}%" if total else ""}')


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""抠图第二层：CLIP 零样本语义闸门 —— 只留袜子。

为什么需要这一层：matte 模型（u2net / isnet / BiRefNet / RMBG）做的是**显著性**
分割，画面里和袜子一起摆拍的鞋子、毯子、礼盒都会被当成前景带进来（平台
「一键抠图」就是这个毛病）。而且**模型越好这层越必需**：实测 birefnet-general 和
bria-rmbg 给鞋子的都是满 alpha，靠阈值根本筛不掉。CLIP 给每个连通域做开放词表
分类，按「是不是袜子」取舍，这才是语义抠图。

文本侧 embedding 只依赖固定 prompt，可以离线算好缓存成 .npz，
上线时只需要 vision 塔（int8 约 84MB）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

IMAGE_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
IMAGE_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
LOGIT_SCALE = 100.0          # CLIP 训练收敛后的 logit_scale

# 语义词表：分三组，sock 为正类，其余都是不许带进白底图的东西
PROMPTS: dict[str, list[str]] = {
    'sock': [
        'a photo of a sock',
        'a photo of a pair of socks',
        'a pair of knitted cotton socks',
        'an ankle sock',
        'a crew sock',
        'a stocking',
        'hosiery product photo',
    ],
    'shoe': [
        'a photo of a shoe',
        'a photo of a pair of shoes',
        'a black leather ballet flat shoe',
        'a sneaker',
        'a sandal',
        'a boot',
        'a slipper',
    ],
    'other': [
        'a folded blanket',
        'a towel',
        'a fluffy rug',
        'a cushion',
        'a piece of fabric',
        'a paper bag',
        'a cardboard box',
        'a gift box',
        'a human leg',
        'a human hand',
        'a potted plant',
        'a clothes hanger',
        'a price tag label',
        'a plain white background',
    ],
}


@dataclass
class GateVerdict:
    label: int
    kept: bool
    scores: dict
    top_prompt: str
    reason: str = ''
    extra: dict = field(default_factory=dict)


class ClipGate:
    def __init__(self, model_dir: str, providers=None, text_cache: str | None = None):
        import onnxruntime as ort
        self.model_dir = model_dir
        providers = providers or ['CPUExecutionProvider']
        so = ort.SessionOptions()
        so.log_severity_level = 3
        v_path = self._pick(['vision_model_quantized.onnx', 'vision_model.onnx'])
        self.vision = ort.InferenceSession(v_path, sess_options=so, providers=providers)
        self.v_in = self.vision.get_inputs()[0].name
        self.v_out = self._pick_out(self.vision, ('image_embeds', 'pooler_output'))

        self.groups = list(PROMPTS.keys())
        self.flat_prompts = []
        self.flat_group = []
        for g, ps in PROMPTS.items():
            for p in ps:
                self.flat_prompts.append(p)
                self.flat_group.append(g)

        cache = text_cache or os.path.join(model_dir, 'text_embeds.npz')
        self.text_emb = self._load_or_build_text(cache)

    # ---------- 基础设施 ----------
    def _pick(self, names):
        for n in names:
            p = os.path.join(self.model_dir, n)
            if os.path.isfile(p):
                return p
        raise FileNotFoundError(f'{self.model_dir} 下找不到 {names}')

    @staticmethod
    def _pick_out(sess, preferred):
        outs = [o.name for o in sess.get_outputs()]
        for p in preferred:
            if p in outs:
                return p
        return outs[0]

    def _load_or_build_text(self, cache_path: str) -> np.ndarray:
        if os.path.isfile(cache_path):
            data = np.load(cache_path, allow_pickle=True)
            if list(data['prompts']) == self.flat_prompts:
                return data['emb'].astype(np.float32)
        emb = self._encode_text(self.flat_prompts)
        np.savez(cache_path, emb=emb, prompts=np.array(self.flat_prompts, dtype=object))
        return emb

    def _encode_text(self, prompts) -> np.ndarray:
        import onnxruntime as ort
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(os.path.join(self.model_dir, 'tokenizer.json'))
        tok.enable_truncation(max_length=77)
        tok.enable_padding(length=77, pad_id=self._pad_id(tok))
        encs = tok.encode_batch(prompts)
        ids = np.array([e.ids for e in encs], dtype=np.int64)
        attn = np.array([e.attention_mask for e in encs], dtype=np.int64)
        so = ort.SessionOptions()
        so.log_severity_level = 3
        t_path = self._pick(['text_model_quantized.onnx', 'text_model.onnx'])
        sess = ort.InferenceSession(t_path, sess_options=so, providers=['CPUExecutionProvider'])
        feed = {}
        for i in sess.get_inputs():
            if 'input_ids' in i.name:
                feed[i.name] = ids
            elif 'attention' in i.name:
                feed[i.name] = attn
        out_name = self._pick_out(sess, ('text_embeds', 'pooler_output'))
        emb = sess.run([out_name], feed)[0].astype(np.float32)
        return _l2(emb)

    @staticmethod
    def _pad_id(tok) -> int:
        for cand in ('<|endoftext|>', '!'):
            tid = tok.token_to_id(cand)
            if tid is not None:
                return tid
        return 0

    # ---------- 图像侧 ----------
    def encode_images(self, images) -> np.ndarray:
        batch = np.stack([_preprocess(im) for im in images], axis=0)
        emb = self.vision.run([self.v_out], {self.v_in: batch})[0].astype(np.float32)
        return _l2(emb)

    def score(self, images) -> list:
        """返回每张图在各语义组上的概率，以及最像的那条 prompt。"""
        emb = self.encode_images(images)
        logits = LOGIT_SCALE * emb @ self.text_emb.T
        probs = _softmax(logits, axis=1)
        results = []
        for row in probs:
            grouped = {g: 0.0 for g in self.groups}
            for p, g in zip(row, self.flat_group):
                grouped[g] += float(p)
            top = int(np.argmax(row))
            results.append({
                'groups': grouped,
                'top_prompt': self.flat_prompts[top],
                'top_prob': float(row[top]),
            })
        return results


def _l2(x: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.maximum(n, 1e-8)


def _softmax(x: np.ndarray, axis=-1) -> np.ndarray:
    x = x - x.max(axis=axis, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=axis, keepdims=True)


def _preprocess(im: Image.Image) -> np.ndarray:
    """CLIP 预处理：短边缩到 224（bicubic）→ 中心裁 224 → 归一化。"""
    im = im.convert('RGB')
    w, h = im.size
    s = 224.0 / min(w, h)
    im = im.resize((max(224, int(round(w * s))), max(224, int(round(h * s)))), Image.BICUBIC)
    w, h = im.size
    left = (w - 224) // 2
    top = (h - 224) // 2
    im = im.crop((left, top, left + 224, top + 224))
    arr = np.asarray(im, dtype=np.float32) / 255.0
    arr = (arr - IMAGE_MEAN) / IMAGE_STD
    return arr.transpose(2, 0, 1)


def crop_for_clip(rgb: np.ndarray, mask: np.ndarray, pad_ratio: float = 0.12,
                  bg: int = 255) -> Image.Image:
    """把一个连通域抠出来贴到白底方图上再送 CLIP。

    贴白底而不是保留原背景：否则 CLIP 看到的是「地毯上的一团东西」，
    背景纹理会主导判断；贴成白底商品图最接近 CLIP 的训练分布。
    """
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        raise ValueError('空 mask')
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    h, w = y1 - y0, x1 - x0
    pad = int(round(max(h, w) * pad_ratio))
    y0 = max(0, y0 - pad)
    x0 = max(0, x0 - pad)
    y1 = min(rgb.shape[0], y1 + pad)
    x1 = min(rgb.shape[1], x1 + pad)
    sub = rgb[y0:y1, x0:x1].astype(np.float32)
    m = mask[y0:y1, x0:x1].astype(np.float32)[:, :, None]
    comp = sub * m + float(bg) * (1 - m)
    h2, w2 = comp.shape[:2]
    side = max(h2, w2)
    canvas = np.full((side, side, 3), float(bg), dtype=np.float32)
    oy, ox = (side - h2) // 2, (side - w2) // 2
    canvas[oy:oy + h2, ox:ox + w2] = comp
    return Image.fromarray(canvas.clip(0, 255).astype(np.uint8))


# ---------------------------------------------------------------------------
# 图源适用性判断：这张图能不能当白底图的来源
# ---------------------------------------------------------------------------
SCENE_PROMPTS: dict[str, list[str]] = {
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


class SceneClassifier:
    """整图场景分类，复用 ClipGate 的 vision 塔，只换一套文本 prompt。

    实测（22 张真实采集图，人工标注对照）：四分类只有 59% 准确率，
    many / packaged 两类互相混；但降到「能不能用」的二分类是 20/22，
    且**零误接受** —— 没有一张不合格的图被判成 single_pair。
    其中 worn（穿在脚上/腿上）这一类判得最干净：2/2 全中，
    其他图的 worn 概率最高只到 0.172。所以只有 worn 用作硬拒绝，
    many / packaged 只出警告，否则会误杀真实单品图
    （04_条纹 被判成 many，主图_04 被判成 many，都是好图）。
    """

    def __init__(self, gate: 'ClipGate'):
        self.gate = gate
        self.flat_prompts = []
        self.flat_group = []
        for g, ps in SCENE_PROMPTS.items():
            for p in ps:
                self.flat_prompts.append(p)
                self.flat_group.append(g)
        cache = os.path.join(gate.model_dir, 'scene_text_embeds.npz')
        self.text_emb = self._load_or_build(cache)
        self.groups = list(SCENE_PROMPTS.keys())

    def _load_or_build(self, cache_path: str) -> np.ndarray:
        if os.path.isfile(cache_path):
            data = np.load(cache_path, allow_pickle=True)
            if list(data['prompts']) == self.flat_prompts:
                return data['emb'].astype(np.float32)
        emb = self.gate._encode_text(self.flat_prompts)
        np.savez(cache_path, emb=emb, prompts=np.array(self.flat_prompts, dtype=object))
        return emb

    def classify(self, images) -> list:
        batch = np.stack([_preprocess(im) for im in images], axis=0)
        raw = self.gate.vision.run([self.gate.v_out], {self.gate.v_in: batch})[0]
        emb = _l2(raw.astype(np.float32))
        probs = _softmax(LOGIT_SCALE * emb @ self.text_emb.T, axis=1)
        out = []
        for row in probs:
            g = {k: 0.0 for k in self.groups}
            for p, name in zip(row, self.flat_group):
                g[name] += float(p)
            out.append({'groups': g, 'top': max(g, key=g.get)})
        return out

# -*- coding: utf-8 -*-
"""直接使用 onnxruntime 的 matte 会话与推理。

## 为什么不再用 rembg

rembg 的 ``__init__`` 顶层 ``from .bg import remove``，而 ``bg.py`` 顶层
``from pymatting...``；``pymatting`` 又依赖 ``numba``，``numba`` 依赖 ``llvmlite``。
结果就是：**只要还 import rembg，打包里就必须带上 llvmlite**——而 llvmlite 的
``binding/llvmlite.dll`` 单个文件就是 **39.5 MB**（实测 2026-10-10，sidecar 138.9 MB 里
它排第一）。可是我们真正用到的只有两件事：

* ``new_session(model_name)`` —— 建一个 onnxruntime 会话；
* ``remove(img, session=..., only_mask=True, post_process_mask=False)`` —— 出一张 mask。

本模块把这两件事按 rembg 的**同一套数值流程**重写，从而把
``rembg → pymatting → numba → llvmlite`` 整条链从运行时与安装包里摘掉。
数值等价由 ``lab/whitebg`` 的对比脚本逐像素验证，**不是「看起来差不多」**。

## 复刻要点（照抄 rembg 的实现，别自己发挥）

1. 预处理是 ``im_ary / max(np.max(im_ary), 1e-6)``——**除以最大值，不是除以 255**；
   然后按 mean/std 归一化、CHW、加 batch 维、float32。
2. 图像先 ``convert('RGB')`` 再 ``resize(spec.size, LANCZOS)``。
3. 后处理按模型分两类：birefnet 系先 sigmoid 再 min-max；其余直接 min-max；
   u2net 额外 ``clip(0, 1)``。
4. mask 用 ``Image.fromarray(..., mode='L')``，再 resize 回**原图尺寸**（LANCZOS）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
from PIL import Image

#: 我方支持的模型（``src/whitebg/setup_models.py`` 的下载表与之对应）。
#: size / mean / std / 后处理类型，全部照抄 rembg 对应 session 类，改这里等于改数值结果。
MODEL_SPECS: Dict[str, dict] = {
    'birefnet-general': {'size': (1024, 1024), 'mean': (0.485, 0.456, 0.406),
                         'std': (0.229, 0.224, 0.225), 'post': 'sigmoid_minmax'},
    'birefnet-general-lite': {'size': (1024, 1024), 'mean': (0.485, 0.456, 0.406),
                              'std': (0.229, 0.224, 0.225), 'post': 'sigmoid_minmax'},
    'bria-rmbg': {'size': (1024, 1024), 'mean': (0.485, 0.456, 0.406),
                  'std': (0.229, 0.224, 0.225), 'post': 'minmax'},
    'isnet-general-use': {'size': (1024, 1024), 'mean': (0.5, 0.5, 0.5),
                          'std': (1.0, 1.0, 1.0), 'post': 'minmax'},
    'u2net': {'size': (320, 320), 'mean': (0.485, 0.456, 0.406),
              'std': (0.229, 0.224, 0.225), 'post': 'minmax_clip'},
    'u2netp': {'size': (320, 320), 'mean': (0.485, 0.456, 0.406),
               'std': (0.229, 0.224, 0.225), 'post': 'minmax'},
}


class SessionError(RuntimeError):
    """建会话失败（模型文件缺失、onnxruntime 不可用等），如实抛出。"""


@dataclass
class MatteSession:
    """onnxruntime 会话 + 它对应的规格。``matte.py`` 只透过它做事。"""

    model_name: str
    spec: dict
    inner: object
    model_path: str

    @property
    def inner_session(self):  # 与 rembg 会话同名，方便替换时对读
        return self.inner

    def run(self, feeds) -> list:
        return self.inner.run(None, feeds)


def model_file(model_name: str, model_home: str | Path) -> Path:
    """模型文件路径：``<model_home>/models/<name>/<name>.onnx``（与 rembg 布局一致）。"""

    return Path(model_home) / 'models' / model_name / '{}.onnx'.format(model_name)


def _providers() -> list:
    """照抄 rembg 的选择顺序：能用 GPU 就用，否则 CPU。"""

    import onnxruntime as ort

    device = ort.get_device()
    available = ort.get_available_providers()
    if device == 'GPU' and 'CUDAExecutionProvider' in available:
        return ['CUDAExecutionProvider', 'CPUExecutionProvider']
    if device[:3] == 'GPU' and 'ROCMExecutionProvider' in available:
        return ['ROCMExecutionProvider', 'CPUExecutionProvider']
    if 'OpenVINOExecutionProvider' in available:
        return ['OpenVINOExecutionProvider', 'CPUExecutionProvider']
    return ['CPUExecutionProvider']


def make_session(model_name: str = 'birefnet-general',
                 model_home: str | Path | None = None) -> MatteSession:
    """建一个 matte 会话。模型缺失时抛出**带路径**的错误，不静默降级。"""

    if model_name not in MODEL_SPECS:
        raise SessionError('不支持的 matte 模型：{}（可用：{}）'.format(
            model_name, '、'.join(sorted(MODEL_SPECS))))
    if model_home is None:
        raise SessionError('建 matte 会话必须给出模型目录（model_home）')
    path = model_file(model_name, model_home)
    if not path.is_file():
        raise SessionError('模型文件不存在：{}（先跑 python -m whitebg.setup_models）'.format(path))
    try:
        import onnxruntime as ort
    except Exception as exc:  # noqa: BLE001
        raise SessionError('onnxruntime 不可用：{}: {}'.format(type(exc).__name__, exc))
    session = ort.InferenceSession(str(path), providers=_providers())
    return MatteSession(model_name, MODEL_SPECS[model_name], session, str(path))


def normalize(img: Image.Image, spec: dict) -> np.ndarray:
    """rembg 的预处理：**除以最大值**、按 mean/std 归一化、CHW、加 batch 维。"""

    im = img.convert('RGB').resize(spec['size'], Image.Resampling.LANCZOS)
    array = np.array(im).astype(np.float64)
    array = array / max(float(np.max(array)), 1e-6)
    mean, std = spec['mean'], spec['std']
    out = np.zeros((array.shape[0], array.shape[1], 3), dtype=np.float64)
    for channel in range(3):
        out[:, :, channel] = (array[:, :, channel] - mean[channel]) / std[channel]
    return out.transpose((2, 0, 1))[None].astype(np.float32)


def predict_mask(session: MatteSession, img: Image.Image) -> Image.Image:
    """出一张与原图同尺寸的 ``L`` mask（等价于 rembg ``remove(only_mask=True,
    post_process_mask=False)``）。"""

    spec = session.spec
    feeds = normalize(img, spec)
    input_name = session.inner.get_inputs()[0].name
    outputs = session.inner.run(None, {input_name: feeds})
    pred = outputs[0][:, 0, :, :]
    if spec['post'] == 'sigmoid_minmax':
        pred = 1 / (1 + np.exp(-pred))
    low, high = float(np.min(pred)), float(np.max(pred))
    pred = (pred - low) / (high - low)
    if spec['post'] == 'minmax_clip':
        pred = pred.clip(0, 1)
    pred = np.squeeze(pred)
    mask = Image.fromarray((pred * 255).astype('uint8'), mode='L')
    return mask.resize(img.size, Image.Resampling.LANCZOS)

# -*- coding: utf-8 -*-
"""袜子白底图流水线：语义抠图（只留袜子）→ 转正 → 1:1 白底居中。

和平台「一键抠图 → 白底图」的区别：平台用的是**显著性**分割，和袜子一起
摆拍的鞋子、毯子、礼盒都会被当成主体带进白底图（实测就是这个毛病）。
这里在 matte 之后加一层 CLIP 零样本**语义**闸门，逐个连通域判断「是不是袜子」，
只保留袜子。

对外只需要这三个入口：

    from whitebg import WhiteBgConfig, process_product_dir, resolve_model_dir

模块分层：
    matte.py      matte 模型 + 二次聚焦 + 引导滤波 + alpha 收紧
    clip_gate.py  CLIP 语义闸门（逐域「是不是袜子」）+ 整图场景判断
    geometry.py   转正（带置信度护栏）/ 裁主体 / 1:1 白底居中
    pipeline.py   单张图的编排，不合格就明确拒绝
    product.py    整个采集目录的编排，产出 白底图/ 和 SKU_1x1/
    paths.py      模型目录解析（走项目的 runtime_paths 约定）
"""
from .pipeline import Config as WhiteBgConfig, Result, SockWhiteBg, UnsuitableSource
from .paths import resolve_model_dir, model_status
from .product import process_product_dir, ProductOutcome

__all__ = [
    'WhiteBgConfig',
    'Result',
    'SockWhiteBg',
    'UnsuitableSource',
    'resolve_model_dir',
    'model_status',
    'process_product_dir',
    'ProductOutcome',
]

# -*- coding: utf-8 -*-
"""测试辅助工具。

**为什么不用系统临时目录**：本机 DSH 文件沙箱把系统临时目录限制成「可建目录、
不可写文件」，``tempfile`` / ``TemporaryDirectory`` 一律失败
（``PermissionError: [WinError 5]`` / ``[Errno 13]``）。工作区是确定可写的，
因此测试素材统一落在 ``taobao-publisher/tmp/test-scratch/``，收尾时尽力清理。

该目录已在 ``.gitignore`` 中排除。
"""

from __future__ import annotations

import itertools
import shutil
import unittest
from pathlib import Path
from typing import Tuple

from PIL import Image

#: 测试 scratch 根目录（子项目内，工作区可写）。
SCRATCH_ROOT = Path(__file__).resolve().parents[1] / "tmp" / "test-scratch"

_counter = itertools.count()


def make_temp_dir(case: unittest.TestCase, prefix: str = "tbp-") -> Path:
    """在 scratch 根下创建一个独立目录，并注册「尽力清理」的收尾动作。"""

    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    path = SCRATCH_ROOT / f"{prefix}{next(_counter):04d}"
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    case.addCleanup(lambda: shutil.rmtree(path, ignore_errors=True))
    return path


def make_image(path: Path, size: Tuple[int, int] = (800, 800)) -> Path:
    """生成一张纯白 JPEG，用于图片校验测试。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (255, 255, 255)).save(path, format="JPEG")
    return path


def make_square_images(directory: Path, count: int, size: Tuple[int, int] = (800, 800)) -> list:
    return [str(make_image(directory / f"m{index}.jpg", size)) for index in range(count)]

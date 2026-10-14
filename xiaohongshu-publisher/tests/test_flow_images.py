# -*- coding: utf-8 -*-
"""`describe_images`：上传前的只读自检（计划 1.2）。

为什么要单独测它：上传失败时界面只显示「图片上传未成功」✗，
真实原因（路径不存在 / 超 5M / 格式不收）就在这个自检里 ——
它必须**如实**区分这三种情况，且**只读**（不做任何平台写入）✓。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "xiaohongshu-publisher"))

from xiaohongshu_publish.flow import describe_images  # noqa: E402


def test_describe_images_reports_missing_existing_and_oversized(tmp_path):
    good = tmp_path / "主图_01.jpg"
    good.write_bytes(b"x" * 1024)
    big = tmp_path / "超大.jpg"
    with open(big, "wb") as handle:      # 稀疏文件，避免真写 5MB
        handle.truncate(5 * 1024 * 1024 + 1)
    wrong_format = tmp_path / "图.webp"
    wrong_format.write_bytes(b"x" * 64)
    missing = tmp_path / "不存在.jpg"

    described = describe_images([str(good), str(big), str(wrong_format), str(missing)])
    by_name = {Path(item["path"]).name: item for item in described}

    assert by_name["主图_01.jpg"]["ok"] is True
    assert by_name["主图_01.jpg"]["exists"] is True
    assert by_name["主图_01.jpg"]["size_mb"] == round(1024 / 1048576.0, 3)

    assert by_name["超大.jpg"]["ok"] is False
    assert "5M" in by_name["超大.jpg"]["problem"]

    assert by_name["图.webp"]["ok"] is False
    assert "格式" in by_name["图.webp"]["problem"]

    assert by_name["不存在.jpg"]["ok"] is False
    assert by_name["不存在.jpg"]["exists"] is False
    assert by_name["不存在.jpg"]["problem"] == "本地图片不存在"


def test_describe_images_handles_empty_and_bad_input():
    assert describe_images([]) == []
    assert describe_images(None) == []
    # 空字符串不是文件，要如实报"不存在"，不能抛
    item = describe_images([""])[0]
    assert item["ok"] is False and item["exists"] is False

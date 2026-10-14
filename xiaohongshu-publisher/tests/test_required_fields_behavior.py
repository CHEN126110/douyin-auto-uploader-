# -*- coding: utf-8 -*-
"""`REQUIRED_FIELDS` 的**行为级**回归：把真实 JS 放进最小 DOM 桩件里跑（Node）。

为什么不能只做字符串断言（2026-10-14 真机踩过 ✗）：
旧判据只看 `input.value` 与"请选择"，于是**四类已填字段被误报未填**：
  - 单选框显示具体值（适用性别＝`通用`、上市时间＝`2024年秋冬季`、运费模板＝`系统默认-非偏远地区包邮模版`）；
  - 多选框已选值渲染成 tag（适用季节＝春季/秋季/秋冬，而 `select_text` 拼成 `请选择春季秋季秋冬`）；
  - 图片行已落图（`img[src]` 指向 `ros-preview.xhscdn.com/arkgoods/`，文案却残留"上传中..."）。
字符串包含断言对这类 bug **完全无效**（脚本里确实有"请选择"、也有 `required-icon`）✓，
所以这里让那段 JS 真跑一遍，用真机读到的形态断言输出。

需要 Node（本仓已有 runtime/node.exe；找不到时**明确 skip**，不伪装通过 ✗）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "xiaohongshu-publisher") not in sys.path:
    sys.path.insert(0, str(REPO / "xiaohongshu-publisher"))

from xiaohongshu_publish import page_scripts  # noqa: E402

CHECKER = Path(__file__).resolve().parent / "js" / "run-required-fields-check.mjs"
NODE_CANDIDATES = (
    os.environ.get("DSH_NODE", ""),
    str(REPO / "runtime" / "node.exe"),
    r"C:\Users\CRB\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe",
)


def _node() -> str:
    for candidate in NODE_CANDIDATES:
        if candidate and Path(candidate).is_file():
            return candidate
    found = shutil.which("node")
    if found:
        return found
    pytest.skip("找不到 Node，无法做 REQUIRED_FIELDS 的行为级验证（明确跳过，不算通过）")


def test_required_fields_marks_real_filled_shapes_as_filled(tmp_path):
    """真机四种"已填"形态必须判为已填；两种"未填"形态必须判为未填。"""
    source = tmp_path / "required-fields.js"
    source.write_text(json.dumps(page_scripts.REQUIRED_FIELDS, ensure_ascii=False),
                      encoding="utf-8")

    completed = subprocess.run(
        [_node(), str(CHECKER), str(source)],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    payload = None
    if completed.stdout.strip():
        payload = json.loads(completed.stdout)

    assert completed.returncode == 0, (
        "REQUIRED_FIELDS 的判定与真机形态不符：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n--- stderr ---\n" + (completed.stderr or ""))
    assert payload and payload["failed"] == []

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""CI 构建前置：补齐仓库里被 .gitignore 排除、但打包必需的运行时资产。

背景：
    build_sidecar.py 的 DATA_FILES / copy_resources 需要 sqlite.db、trending_keywords.db、
    user_settings.json；tauri.conf.json 的 bundle.resources 需要 tauri-app/runtime/node.exe。
    这几个文件都是本地运行时产物或大二进制，按 .gitignore 不进仓库，所以 CI 检出后必须现造。

    脚本对缺失文件才创建，已存在则原样保留（本地误跑不会覆盖真实数据）。
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TAURI_APP_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = TAURI_APP_DIR.parent

# GitHub windows-latest 是 en-US 镜像（ACP=1252），Actions 把 step 的 stdout 接成管道，
# Python 此时按 locale 编码写 stdout，本文件的中文日志会直接 UnicodeEncodeError 把 CI 打断。
# 与 tauri-app/python-sidecar/app.py 的既有做法保持一致。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, ValueError):
        pass


def log(message: str) -> None:
    print(f"[ci-prepare] {message}", flush=True)


def seed_main_database() -> None:
    """建一个只有表结构、没有业务数据的 sqlite.db。

    src/orm.py 在 import 时就会执行 initialize_database_schema()，
    非 frozen 且未设 DOUYIN_DATA_DIR 时落到仓库根，正是 build_sidecar.py 取用的位置。
    """
    target = PROJECT_ROOT / "sqlite.db"
    if target.exists():
        log(f"sqlite.db 已存在，跳过: {target}")
        return

    sys.path.insert(0, str(PROJECT_ROOT))
    os.environ.pop("DOUYIN_DATA_DIR", None)
    import src.orm  # noqa: F401  # import 副作用即建表

    if not target.exists():
        raise SystemExit(f"导入 src.orm 后仍未生成 {target}")
    log(f"已生成空 sqlite.db: {target}")


def seed_trending_database() -> None:
    """建空的 trending_keywords.db。

    表结构与 src/trending_keywords_scraper.py 的 CREATE TABLE IF NOT EXISTS 一致；
    即便字段有出入，运行时那句 IF NOT EXISTS 也只在表不存在时才建，不会冲突。
    """
    target = PROJECT_ROOT / "trending_keywords.db"
    if target.exists():
        log(f"trending_keywords.db 已存在，跳过: {target}")
        return

    with sqlite3.connect(target) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trending_keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                category TEXT,
                heat_score REAL,
                source TEXT,
                collected_at TEXT
            )
            """
        )
    log(f"已生成空 trending_keywords.db: {target}")


def seed_user_settings() -> None:
    """从去敏模板生成 user_settings.json（根目录与 tauri-app/ 各一份）。"""
    template = TAURI_APP_DIR / "user_settings.default.json"
    if not template.exists():
        raise SystemExit(f"缺少模板文件: {template}")

    for target in (TAURI_APP_DIR / "user_settings.json", PROJECT_ROOT / "user_settings.json"):
        if target.exists():
            log(f"user_settings.json 已存在，跳过: {target}")
            continue
        shutil.copy2(template, target)
        log(f"已从模板生成: {target}")


def stage_node_runtime() -> None:
    """把 node.exe 放到 tauri-app/runtime/。

    tauri.conf.json 把它作为 mcp-runtime/node.exe 打进安装包，用于跑内置 MCP Server。
    CI 上直接复用 runner 自带的 node（actions/setup-node 已装好），不额外下载。
    """
    target = TAURI_APP_DIR / "runtime" / "node.exe"
    if target.exists():
        log(f"node.exe 已存在，跳过: {target}")
        return

    node_path = shutil.which("node")
    if not node_path:
        raise SystemExit("PATH 上找不到 node，无法准备 mcp-runtime/node.exe")

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(node_path, target)
    log(f"已复制 node 运行时: {node_path} -> {target}")


def main() -> None:
    log(f"仓库根: {PROJECT_ROOT}")
    seed_main_database()
    seed_trending_database()
    seed_user_settings()
    stage_node_runtime()
    log("构建前置资产准备完成")


if __name__ == "__main__":
    main()

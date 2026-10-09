#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Build the Python sidecar executable used by the Tauri app."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime
import json
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

#: 源码清单（**不能放进 OUTPUT_DIR**：那里只允许打包资源，
#: prune_output_dir() 会把非打包资源挪走）。
MANIFEST_PATH = SCRIPT_DIR / ".source-manifest.json"
TAURI_APP_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = TAURI_APP_DIR.parent
OUTPUT_DIR = TAURI_APP_DIR / "src-tauri" / "sidecar"
MAIN_SCRIPT = SCRIPT_DIR / "app.py"

DATA_FILES: list[tuple[Path, str]] = [
    (PROJECT_ROOT / "src", "src"),
    (PROJECT_ROOT / "sqlite.db", "."),
    (PROJECT_ROOT / "cfg.yaml", "."),
    (PROJECT_ROOT / "pricing_config.json", "."),
    (TAURI_APP_DIR / "user_settings.json", "."),
    (PROJECT_ROOT / "trending_keywords.db", "."),
    (PROJECT_ROOT / "protocol-research" / "fxg_protocol_v2.py", "protocol-research"),
    (PROJECT_ROOT / "protocol-research" / "fxg_errors.py", "protocol-research"),
    # 协议上传 v4 主脚本：app.py 在 _execute_protocol_flow() 中通过
    # sys.path.insert(0, <_base>/protocol-research-clean-20260505/scripts) 后 import fxg_protocol_v4
    # 之前没加进打包，frozen 模式下导致 "No module named 'fxg_protocol_v4'"
    (PROJECT_ROOT / "protocol-research-clean-20260505" / "scripts" / "fxg_protocol_v4.py",
     "protocol-research-clean-20260505/scripts"),
]

# 仅收集四份事实契约，不将截图、账号数据、测试或研究产物带进安装包。
TAOBAO_CONTRACT_FILES = ("field_mapping.json", "selectors.json", "rules.json", "publish_item.schema.json")
DATA_FILES += [
    (PROJECT_ROOT / "taobao-publisher" / "contracts" / name, "taobao-publisher/contracts")
    for name in TAOBAO_CONTRACT_FILES
]

# 只列 PyInstaller 静态分析看不到、或必须保底的**三方**模块。
# 曾经这里混进过 dataclasses/typing/pathlib/json/logging/threading/queue/uuid/hashlib/
# base64/traceback/shutil/tempfile/subprocess 这些标准库名字——它们只要被 import 就一定会
# 被收集，写在这里没有任何作用，只会让人以为「列了才打进去」。已删除（2026-10-01）。
HIDDEN_IMPORTS = [
    "peewee",
    "flask",
    "flask_cors",
    "werkzeug",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "yaml",
    "py7zr",
    "requests",
    "urllib3",
    "psutil",
    "DrissionPage",
    "websocket",
    "websocket._core",
    "websocket._abnf",
    "certifi",
    "src",
    "src.orm",
    "src.config",
    "src.utils",
    "src.shop_session",
    "src.product_media",
    "src.runtime_paths",
    "src.material_options_cache",
    "src.chrome_manager",
    "src.enhanced_category_selector",
    "src.smart_pricing_engine",
    "src.professional_title_generator",
    "src.trending_keywords_scraper",
    "src.constants",
    "src.config_manager",
    "src.confidence_scorer",
    "src.quantity_extraction_enhanced",
    "src.post_interaction_validator",
    "taobao_publish.desktop",
    # 白底图语义抠图（src/whitebg）。模型文件不打包，运行时从数据目录解析；
    # 但这几个模块和它们的三方依赖必须显式列出，否则打出来的 exe 一调就 ModuleNotFoundError
    "src.whitebg",
    "src.whitebg.paths",
    "src.whitebg.matte",
    "src.whitebg.geometry",
    "src.whitebg.clip_gate",
    "src.whitebg.pipeline",
    "src.whitebg.product",
    "rembg",
    "rembg.sessions",
    "rembg.sessions.bria_rmbg",
    "rembg.sessions.birefnet_general",
    "rembg.sessions.dis_general_use",
    "rembg.sessions.u2net",
    "onnxruntime",
    "tokenizers",
    "scipy",
    "scipy.ndimage",
    "numpy",
    "pooch",
    "natsort",
]

# 排除项按「有没有证据」加，不要凭感觉堆包名。
# 证据来源：用 PyInstaller.archive.readers.CArchiveReader 列出 python-backend.exe 的归档
# 条目（2026-10-01 实测：exe 142.72 MB，解压后 354.99 MB / 630 条），再对每条做全仓引用检索。
EXCLUDED_MODULES = [
    "PyQt5",
    "PyQt6",
    "PySide2",
    # PySide6/shiboken6 只在非 sidecar 模式下由 app.py 动态 import（app.py:140 importlib 调 src.gui），
    # PyInstaller 静态分析看不见它，所以今天没被打进去；但两份 requirements.txt 都装着 PySide6，
    # 一旦哪天有静态 import 把它牵进来，exe 会凭空涨几百 MB。这里显式钉死。
    "PySide6",
    "shiboken6",
    "tkinter",
    "matplotlib",
    "IPython",
    "sphinx",
    "notebook",
    "jupyter",
    # pywin32 的 MFC GUI 壳：全仓只用 win32api / win32con（src/gui.py:8-9），
    # Pythonwin + mfc140u.dll 实测占归档 6.50 MB，纯浪费。
    "Pythonwin",
    "win32ui",
    # 下面这些全仓零引用，钉死是为了防止它们哪天被某个依赖的可选 import 带进来。
    "cv2",
    "pandas",
    "pytest",
    "_pytest",
]

# 输出目录里只允许出现「安装包真正需要」的东西。sidecar/ 是 tauri.conf.json
# `"sidecar/*": "./"` 的采集源，目录里放什么就会原样进安装包。已经出过两次事：
#   - python-backend.exe.bak（85.37 MB，2026-09-06）
#   - python-backend.exe.known-good-20260924（142.72 MB，2026-10-01 回滚备份）
# 两者实测都几乎不可压缩（zlib 98.6% / lzma 98.5%），NSIS 也救不了，等于安装包 1:1 涨。
#
# 处理策略：白名单之外的文件**搬走而不是删**——移到 TAURI_APP_DIR/_sidecar_backups/，
# 回滚备份照样留着，只是不再躺在会被打包的目录里。
ALLOWED_OUTPUT_FILES = {
    "python-backend.exe",
    "sqlite.db",
    "cfg.yaml",
    "pricing_config.json",
    "user_settings.json",
    "trending_keywords.db",
}
# 这两类是真垃圾（可重新生成），直接删：
#   data/  —— 手工跑 exe 时落的运行目录；打包运行时 main.rs 会把 DOUYIN_DATA_DIR
#             指到 %LOCALAPPDATA%，资源目录里这份永远读不到（src/runtime_paths.py:45-54）
#   build/ —— PyInstaller workpath 万一落到这里
OUTPUT_DIR_JUNK_DIRS = ("data", "build")
SIDECAR_BACKUP_DIR = TAURI_APP_DIR / "_sidecar_backups"


def build_sidecar() -> bool:
    print("=" * 60)
    print("[BUILD] Building Python sidecar")
    print("=" * 60)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        "python-backend",
        "--distpath",
        str(OUTPUT_DIR),
        "--workpath",
        str(SCRIPT_DIR / "build"),
        "--specpath",
        str(SCRIPT_DIR),
        "--clean",
        "--noconfirm",
        "--paths",
        str(PROJECT_ROOT),
        "--paths",
        str(PROJECT_ROOT / "taobao-publisher"),
        "--collect-submodules",
        "taobao_publish",
        "--collect-submodules",
        "DrissionPage",
        "--collect-data",
        "DrissionPage",
        # pymatting 在导入时读取自己的分发版本；只有模块没有元数据会使冻结版抠图失败。
        "--copy-metadata",
        "pymatting",
    ]

    for module in EXCLUDED_MODULES:
        cmd.extend(["--exclude-module", module])

    for module in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", module])

    for src, dest in DATA_FILES:
        if src.exists():
            cmd.extend(["--add-data", f"{src}{os.pathsep}{dest}"])

    cmd.append(str(MAIN_SCRIPT))

    print(f"[CMD] {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True)
        print("=" * 60)
        print("[OK] Sidecar build complete")
        print(f"[OUTPUT] {OUTPUT_DIR / 'python-backend.exe'}")
        print("=" * 60)
        return True
    except subprocess.CalledProcessError as exc:
        print("=" * 60)
        print(f"[ERROR] Sidecar build failed: {exc}")
        print("=" * 60)
        return False


def copy_resources() -> None:
    print("[COPY] Copying resource files...")

    resource_sources = {
        "sqlite.db": PROJECT_ROOT / "sqlite.db",
        "cfg.yaml": PROJECT_ROOT / "cfg.yaml",
        "pricing_config.json": PROJECT_ROOT / "pricing_config.json",
        "user_settings.json": TAURI_APP_DIR / "user_settings.json",
        "trending_keywords.db": PROJECT_ROOT / "trending_keywords.db",
    }

    for target_name, source_path in resource_sources.items():
        target_path = OUTPUT_DIR / target_name
        if source_path.exists():
            shutil.copy2(source_path, target_path)
            print(f"  [OK] {source_path.name} -> {target_name}")
        else:
            print(f"  [WARN] Missing resource: {source_path}")


def _unique_destination(directory: Path, name: str) -> Path:
    """同名已存在时加时间戳后缀，绝不覆盖上一次的备份。"""
    target = directory / name
    if not target.exists():
        return target
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return directory / f"{name}.{stamp}"


def prune_output_dir() -> None:
    """把输出目录整理成「只有安装包需要的 6 个文件」。

    OUTPUT_DIR 是 tauri.conf.json 的 `"sidecar/*"` 采集源，目录里的任何文件都会被
    原样复制进安装包。白名单之外的东西分两种处理：

    - `data/`、`build/`：可重新生成的运行/构建残留，直接删；
    - 其它（`.bak`、`.known-good-*`、日志、临时备份……）：**搬到**
      `tauri-app/_sidecar_backups/`，保留回滚能力，只是不再躺在会被打包的目录里。
      这类文件实测几乎不可压缩（zlib 98.6% / lzma 98.5%），留在原处等于安装包 1:1 涨。
    """
    if not OUTPUT_DIR.exists():
        return

    print("[PRUNE] Cleaning output dir to the packaged-resource allowlist...")
    actions = 0

    for name in OUTPUT_DIR_JUNK_DIRS:
        path = OUTPUT_DIR / name
        if path.is_dir():
            size_mb = sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1024 / 1024
            shutil.rmtree(path)
            actions += 1
            print(f"  [DEL]  {name}/  ({size_mb:.2f} MB, 可重新生成)")

    strays = [p for p in sorted(OUTPUT_DIR.iterdir()) if p.name not in ALLOWED_OUTPUT_FILES]
    if strays:
        SIDECAR_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        for path in strays:
            if path.is_dir():
                size_mb = sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1024 / 1024
            else:
                size_mb = path.stat().st_size / 1024 / 1024
            destination = _unique_destination(SIDECAR_BACKUP_DIR, path.name)
            shutil.move(str(path), str(destination))
            actions += 1
            print(f"  [MOVE] {path.name}  ({size_mb:.2f} MB) -> _sidecar_backups/{destination.name}")

    if actions == 0:
        print("  (already clean)")
    else:
        print("  说明：搬到 _sidecar_backups/ 的文件不会被 tauri.conf.json 的 `sidecar/*` 采集到，"
              "回滚时手工复制回去即可。")


def verify_output_dir() -> None:
    """打包前自检：必需的资源必须在，且不该有别的杂物会被打进安装包。"""
    if not OUTPUT_DIR.exists():
        raise FileNotFoundError(f"sidecar output dir not found: {OUTPUT_DIR}")

    missing = [name for name in ("python-backend.exe",) if not (OUTPUT_DIR / name).exists()]
    if missing:
        raise FileNotFoundError(f"sidecar output dir missing required files: {missing}")

    unexpected = sorted(p.name for p in OUTPUT_DIR.iterdir() if p.name not in ALLOWED_OUTPUT_FILES)
    if unexpected:
        raise RuntimeError(
            f"sidecar 输出目录里还有会被打进安装包的文件: {unexpected}\n"
            f"tauri.conf.json 的 `\"sidecar/*\": \"./\"` 会把它们原样复制进安装包。\n"
            f"把它们移出 {OUTPUT_DIR}（回滚备份建议放 {SIDECAR_BACKUP_DIR}）后重新构建。"
        )
    print(f"[VERIFY] 输出目录干净，{len(ALLOWED_OUTPUT_FILES)} 个打包资源齐全")



def write_source_manifest() -> None:
    """把**打包进去的源码**与各自的内容哈希写成清单。

    给 `taobao-publisher/scripts/check-sidecar-freshness.py` 用。

    ⚠️ **写在 `python-sidecar/` 下，不写进 `src-tauri/sidecar/`**——
    后者会被 `prune_output_dir()` 当作非打包资源挪走，而且
    `tauri.conf.json` 的 `"sidecar/*": "./"` 会把它照单收进安装包。

    ⚠️ **用哈希而不是 mtime**：实测源码的 mtime 会自己往前跑而内容不变，
    按 mtime 判会**误报陈旧**。
    """

    import hashlib

    roots = [
        PROJECT_ROOT / "taobao-publisher" / "taobao_publish",
        PROJECT_ROOT / "taobao-publisher" / "contracts",
        PROJECT_ROOT / "src",
        MAIN_SCRIPT,
    ]
    entries = {}
    for root in roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            if not path.is_file() or path.suffix in (".pyc",):
                continue
            if "__pycache__" in path.parts:
                continue
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
            entries[str(path.relative_to(PROJECT_ROOT))] = digest

    manifest = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "exe": "tauri-app/src-tauri/sidecar/python-backend.exe",
        "files": entries,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")
    print(f"[MANIFEST] 记下 {len(entries)} 个文件的内容哈希 -> {MANIFEST_PATH.name}")



def ensure_sidecar_not_running() -> None:
    """**构建前先确认 Sidecar 没在跑。**

    实机踩过：PyInstaller 跑了十几分钟，最后一步写 exe 时报

        PermissionError: [WinError 5] 拒绝访问。: '...python-backend.exe'

    ——因为正在运行的 Sidecar 锁着它。报错只有一句 `PermissionError`，
    看不出「是因为没停 Sidecar」。**而这个原因一开始就能查出来。**

    先停 Sidecar（`POST /internal/terminate`，再 `Stop-Process`）再构建。
    """

    import urllib.error
    import urllib.request

    problems = []

    try:
        request = urllib.request.Request("http://127.0.0.1:5001/internal/terminate",
                                         method="POST")
        urllib.request.urlopen(request, timeout=2)
        print("[WARN] 5001 上有 Sidecar 在跑，已请求它停止——**请等它退出后重跑构建**")
        problems.append("Sidecar 正在运行（已请求终止）")
    except (urllib.error.URLError, OSError):
        pass  # 端口不通就是没在跑，正常

    exe = OUTPUT_DIR / "python-backend.exe"
    if exe.exists():
        try:
            with open(exe, "r+b"):
                pass
        except OSError as exc:
            problems.append(f"{exe.name} 被占用（{exc.__class__.__name__}）")

    if problems:
        raise RuntimeError(
            "构建前检查未通过：\n  - " + "\n  - ".join(problems) + "\n"
            "PyInstaller 会在**最后一步**才因为写不了 exe 而失败，\n"
            "白白花掉十几分钟。先停掉 Sidecar 再构建：\n"
            "  1) POST http://127.0.0.1:5001/internal/terminate\n"
            "  2) Stop-Process -Name python-backend -Force\n"
            "  3) 重新运行本脚本"
        )


def main() -> None:
    print("[START] Python sidecar build tool")

    if not MAIN_SCRIPT.exists():
        raise FileNotFoundError(f"Main script not found: {MAIN_SCRIPT}")

    for name in TAOBAO_CONTRACT_FILES:
        contract_path = PROJECT_ROOT / "taobao-publisher" / "contracts" / name
        if not contract_path.is_file():
            raise FileNotFoundError(f"淘宝发布契约缺失：{contract_path}")
    if not (PROJECT_ROOT / "taobao-publisher" / "taobao_publish" / "desktop.py").is_file():
        raise FileNotFoundError("淘宝桌面资料准备模块缺失")

    # **在花十几分钟之前**先确认 exe 没被占用。
    ensure_sidecar_not_running()

    prune_output_dir()

    if not build_sidecar():
        raise SystemExit(1)

    copy_resources()
    prune_output_dir()
    verify_output_dir()
    write_source_manifest()
    print("[NEXT] Run `npm run tauri:build` to create the installer.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Build the Python sidecar executable used by the Tauri app."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
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
    "natsort",
    "dataclasses",
    "typing",
    "pathlib",
    "json",
    "logging",
    "threading",
    "queue",
    "uuid",
    "hashlib",
    "base64",
    "traceback",
    "shutil",
    "tempfile",
    "subprocess",
]

EXCLUDED_MODULES = [
    "PyQt5",
    "PyQt6",
    "PySide2",
    "tkinter",
    "matplotlib",
    "IPython",
    "sphinx",
    "notebook",
    "jupyter",
]


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
        "--collect-submodules",
        "DrissionPage",
        "--collect-data",
        "DrissionPage",
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


def main() -> None:
    print("[START] Python sidecar build tool")

    if not MAIN_SCRIPT.exists():
        raise FileNotFoundError(f"Main script not found: {MAIN_SCRIPT}")

    if not build_sidecar():
        raise SystemExit(1)

    copy_resources()
    print("[NEXT] Run `npm run tauri:build` to create the installer.")


if __name__ == "__main__":
    main()

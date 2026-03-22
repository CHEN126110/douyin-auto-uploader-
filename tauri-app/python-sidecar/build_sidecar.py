#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyInstaller 打包脚本 - 生成 Tauri Sidecar 可执行文件
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# 配置
SCRIPT_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # 项目根目录
OUTPUT_DIR = SCRIPT_DIR.parent / "src-tauri" / "sidecar"
MAIN_SCRIPT = SCRIPT_DIR / "app.py"

# 需要包含的数据文件
DATA_FILES = [
    # (源路径, 目标路径)
    (PROJECT_ROOT / "src", "src"),
    (PROJECT_ROOT / "sqlite.db", "."),
    (PROJECT_ROOT / "cfg.yaml", "."),
    (PROJECT_ROOT / "pricing_config.json", "."),
]

# 隐藏导入
HIDDEN_IMPORTS = [
    # Flask 相关
    "peewee",
    "flask",
    "flask_cors",
    "werkzeug",
    # 图像处理
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    # 配置
    "yaml",
    "requests",
    "urllib3",
    "psutil",
    # DrissionPage 和浏览器自动化
    "DrissionPage",
    "DrissionPage.chromium_page",
    "DrissionPage.chromium_element",
    "DrissionPage.chromium_tab",
    "DrissionPage.commons",
    "DrissionPage.commons.web",
    "DrissionPage.commons.keys",
    "DrissionPage.configs",
    "DrissionPage.configs.chromium_options",
    "DrissionPage.configs.session_options",
    "DrissionPage.errors",
    "DrissionPage._base",
    "DrissionPage._pages",
    "DrissionPage._units",
    "websocket",
    "websocket._core",
    "websocket._abnf",
    "certifi",
    # src 模块
    "src",
    "src.orm",
    "src.config",
    "src.utils",
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
    # 其他
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


def build_sidecar():
    """构建 Sidecar 可执行文件"""
    print("=" * 60)
    print("[BUILD] 开始构建 Python Sidecar")
    print("=" * 60)
    
    # 确保输出目录存在
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 构建 PyInstaller 命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",  # 隐藏控制台窗口
        "--name", "python-backend",
        "--distpath", str(OUTPUT_DIR),
        "--workpath", str(SCRIPT_DIR / "build"),
        "--specpath", str(SCRIPT_DIR),
        "--clean",
        "--noconfirm",
        # 添加 src 目录到 Python 路径
        "--paths", str(PROJECT_ROOT),
        # 收集 DrissionPage 的所有子模块
        "--collect-submodules", "DrissionPage",
        "--collect-data", "DrissionPage",
        # 收集 src 的所有子模块
        "--collect-submodules", "src",
        # 排除 Qt 相关模块避免冲突
        "--exclude-module", "PyQt5",
        "--exclude-module", "PySide6",
        "--exclude-module", "PyQt6",
        "--exclude-module", "PySide2",
        "--exclude-module", "tkinter",
        "--exclude-module", "matplotlib",
        "--exclude-module", "IPython",
        "--exclude-module", "sphinx",
        "--exclude-module", "notebook",
        "--exclude-module", "jupyter",
    ]
    
    # 添加隐藏导入
    for module in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", module])
    
    # 添加数据文件
    for src, dest in DATA_FILES:
        if Path(src).exists():
            if Path(src).is_dir():
                cmd.extend(["--add-data", f"{src}{os.pathsep}{dest}"])
            else:
                cmd.extend(["--add-data", f"{src}{os.pathsep}{dest}"])
    
    # 添加主脚本
    cmd.append(str(MAIN_SCRIPT))
    
    print(f"[CMD] 执行命令: {' '.join(cmd)}")
    print()
    
    # 执行打包
    try:
        result = subprocess.run(cmd, check=True, capture_output=False)
        print()
        print("=" * 60)
        print("[OK] Sidecar 构建成功!")
        print(f"[OUTPUT] 输出位置: {OUTPUT_DIR / 'python-backend.exe'}")
        print("=" * 60)
        return True
    except subprocess.CalledProcessError as e:
        print()
        print("=" * 60)
        print(f"[ERROR] 构建失败: {e}")
        print("=" * 60)
        return False


def copy_resources():
    """复制必要的资源文件到 sidecar 目录"""
    print("\n[COPY] 复制资源文件...")
    
    resources = [
        ("sqlite.db", "sqlite.db"),
        ("cfg.yaml", "cfg.yaml"),
        ("pricing_config.json", "pricing_config.json"),
    ]
    
    for src_name, dest_name in resources:
        src = PROJECT_ROOT / src_name
        dest = OUTPUT_DIR / dest_name
        if src.exists():
            shutil.copy2(src, dest)
            print(f"  [OK] {src_name} -> {dest_name}")
        else:
            print(f"  [WARN] {src_name} 不存在，跳过")


def main():
    """主函数"""
    print("\n[START] Python Sidecar 构建工具\n")
    
    # 检查主脚本是否存在
    if not MAIN_SCRIPT.exists():
        print(f"[ERROR] 错误: 找不到主脚本 {MAIN_SCRIPT}")
        sys.exit(1)
    
    # 构建
    success = build_sidecar()
    
    if success:
        # 复制资源
        copy_resources()
        
        print("\n[INFO] 后续步骤:")
        print("  1. 确保 src-tauri/tauri.conf.json 中配置了 externalBin")
        print("  2. 运行 npm run tauri:build 构建完整应用")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()

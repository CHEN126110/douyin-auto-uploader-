# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# 数据文件配置
datas = [
    ('web', 'web'),
    ('config', 'config'),
    ('src', 'src'),
    ('*.py', '.'),
    ('*.txt', '.'),
    ('*.md', '.'),
]

# 额外收集 PySide6 运行时资源和动态库
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs
import os
try:
    pyside6_datas = collect_data_files('PySide6', includes=['plugins/*', 'resources/*', 'translations/*'])
    pyside6_binaries = collect_dynamic_libs('PySide6')
    datas += pyside6_datas
    # 确保 QtWebEngine 子进程被打包
    import PySide6
    pyside6_dir = os.path.dirname(PySide6.__file__)
    qtwebengine_process = os.path.join(pyside6_dir, 'Qt6WebEngineProcess.exe')
    if os.path.exists(qtwebengine_process):
        datas.append((qtwebengine_process, 'PySide6'))
except Exception:
    pyside6_binaries = []

# 隐藏导入模块
hiddenimports = [
    'selenium',
    'selenium.webdriver',
    'selenium.webdriver.chrome',
    'selenium.webdriver.chrome.service',
    'selenium.webdriver.chrome.options',
    'selenium.webdriver.common.by',
    'selenium.webdriver.support.ui',
    'selenium.webdriver.support.wait',
    'selenium.webdriver.support.expected_conditions',
    'selenium.common.exceptions',
    'webdriver_manager',
    'webdriver_manager.chrome',
    'requests',
    'json',
    'time',
    'random',
    'threading',
    'queue',
    'tkinter',
    'tkinter.ttk',
    'tkinter.messagebox',
    'tkinter.filedialog',
    'PIL',
    'PIL.Image',
    'PIL.ImageTk',
    'openpyxl',
    'pandas',
    'numpy',
    'cv2',
    'pyautogui',
    'keyboard',
    'mouse',
    'psutil',
    'win32gui',
    'win32con',
    'win32api',
    'configparser',
    'logging',
    'datetime',
    'pathlib',
    'os',
    'sys',
    'subprocess',
    'shutil',
    'zipfile',
    'urllib',
    'urllib.request',
    'urllib.parse',
    'http',
    'http.client',
    'socket',
    'ssl',
    'certifi',
    'charset_normalizer',
    'idna',
    'urllib3',
    'PySide6',
    'PySide6.QtCore',
    'PySide6.QtWidgets',
    'PySide6.QtGui',
    'PySide6.QtWebEngineWidgets',
    'shiboken6',
    'openai',
    'anthropic',
    'google.generativeai',
    'zhipuai',
    'dashscope',
    'qianfan',
    'volcengine',
    'minimax',
    'baichuan',
    'moonshot',
    'deepseek',
    'groq',
    'cohere',
    'together',
    'replicate',
    'huggingface_hub',
    'transformers',
    'torch',
    'tensorflow',
    'onnxruntime',
    'scikit-learn',
    'src.gui',
    'src.orm',
    'src.utils',
    'src.config',
    'src.thread',
    'src.smart_integration',
    'src.smart_title_generator',
    'src.professional_title_generator',
    'src.enhanced_category_selector',
    'src.chrome_manager',
    'src.deepseek_ai_client',
    'src.mcp_ai_vision',
    'src.multi_ai_manager',
    'src.network_stability_manager',
    'src.smart_automation_manager',
    'src.smart_page',
    'src.smart_pricing_engine',
    'src.ai_element_detector',
    'src.constants',
    'src.douyin_keywords_scraper',
    'src.trending_keywords_scraper',
    'src.keywords_scraper',
    'src.quantity_extraction_enhanced',
]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=pyside6_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['hooks/runtime_pyside6_path.py'],
    excludes=['PyQt5', 'PyQt6', 'tkinter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='抖音袜子发布工具v3.0_win',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='E:/Script Project/Dyin/app3.0/web/admin/images/logo.ico',  # 图标文件
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='抖音袜子发布工具v3.0_win'
)

# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = [('E:\\Script Project\\Dyin\\beiufen\\2.0\\src', 'src'), ('E:\\Script Project\\Dyin\\beiufen\\2.0\\sqlite.db', '.'), ('E:\\Script Project\\Dyin\\beiufen\\2.0\\cfg.yaml', '.'), ('E:\\Script Project\\Dyin\\beiufen\\2.0\\pricing_config.json', '.'), ('E:\\Script Project\\Dyin\\beiufen\\2.0\\tauri-app\\user_settings.json', '.'), ('E:\\Script Project\\Dyin\\beiufen\\2.0\\trending_keywords.db', '.')]
hiddenimports = ['peewee', 'flask', 'flask_cors', 'werkzeug', 'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont', 'yaml', 'py7zr', 'requests', 'urllib3', 'psutil', 'DrissionPage', 'websocket', 'websocket._core', 'websocket._abnf', 'certifi', 'src', 'src.orm', 'src.config', 'src.utils', 'src.runtime_paths', 'src.chrome_manager', 'src.enhanced_category_selector', 'src.smart_pricing_engine', 'src.professional_title_generator', 'src.trending_keywords_scraper', 'src.constants', 'src.config_manager', 'src.confidence_scorer', 'src.quantity_extraction_enhanced', 'src.post_interaction_validator', 'natsort', 'dataclasses', 'typing', 'pathlib', 'json', 'logging', 'threading', 'queue', 'uuid', 'hashlib', 'base64', 'traceback', 'shutil', 'tempfile', 'subprocess']
datas += collect_data_files('DrissionPage')
hiddenimports += collect_submodules('DrissionPage')


a = Analysis(
    ['E:\\Script Project\\Dyin\\beiufen\\2.0\\tauri-app\\python-sidecar\\app.py'],
    pathex=['E:\\Script Project\\Dyin\\beiufen\\2.0'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'tkinter', 'matplotlib', 'IPython', 'sphinx', 'notebook', 'jupyter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='python-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

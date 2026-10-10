# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = [('C:/Users/CRB/Desktop/2.1/src', 'src'), ('C:/Users/CRB/Desktop/2.1/sqlite.db', '.'), ('C:/Users/CRB/Desktop/2.1/cfg.yaml', '.'), ('C:/Users/CRB/Desktop/2.1/pricing_config.json', '.'), ('C:/Users/CRB/Desktop/2.1/tauri-app/user_settings.json', '.'), ('C:/Users/CRB/Desktop/2.1/trending_keywords.db', '.'), ('C:/Users/CRB/Desktop/2.1/protocol-research/fxg_protocol_v2.py', 'protocol-research'), ('C:/Users/CRB/Desktop/2.1/protocol-research/fxg_errors.py', 'protocol-research'), ('C:/Users/CRB/Desktop/2.1/protocol-research-clean-20260505/scripts/fxg_protocol_v4.py', 'protocol-research-clean-20260505/scripts'), ('C:/Users/CRB/Desktop/2.1/taobao-publisher/contracts/field_mapping.json', 'taobao-publisher/contracts'), ('C:/Users/CRB/Desktop/2.1/taobao-publisher/contracts/selectors.json', 'taobao-publisher/contracts'), ('C:/Users/CRB/Desktop/2.1/taobao-publisher/contracts/rules.json', 'taobao-publisher/contracts'), ('C:/Users/CRB/Desktop/2.1/taobao-publisher/contracts/publish_item.schema.json', 'taobao-publisher/contracts')]
hiddenimports = ['peewee', 'flask', 'flask_cors', 'werkzeug', 'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont', 'yaml', 'py7zr', 'requests', 'urllib3', 'psutil', 'DrissionPage', 'websocket', 'websocket._core', 'websocket._abnf', 'certifi', 'src', 'src.orm', 'src.config', 'src.utils', 'src.shop_session', 'src.product_media', 'src.runtime_paths', 'src.material_options_cache', 'src.chrome_manager', 'src.enhanced_category_selector', 'src.smart_pricing_engine', 'src.professional_title_generator', 'src.trending_keywords_scraper', 'src.constants', 'src.config_manager', 'src.confidence_scorer', 'src.quantity_extraction_enhanced', 'src.post_interaction_validator', 'taobao_publish.desktop', 'src.whitebg', 'src.whitebg.paths', 'src.whitebg.matte', 'src.whitebg.geometry', 'src.whitebg.clip_gate', 'src.whitebg.pipeline', 'src.whitebg.product', 'src.whitebg.onnx_session', 'onnxruntime', 'tokenizers', 'scipy', 'scipy.ndimage', 'numpy']
datas += collect_data_files('DrissionPage')
hiddenimports += collect_submodules('taobao_publish')
hiddenimports += collect_submodules('DrissionPage')


a = Analysis(
    ['C:/Users/CRB/Desktop/2.1/tauri-app/python-sidecar/app.py'],
    pathex=['C:/Users/CRB/Desktop/2.1', 'C:/Users/CRB/Desktop/2.1/taobao-publisher'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'shiboken6', 'tkinter', 'matplotlib', 'IPython', 'sphinx', 'notebook', 'jupyter', 'Pythonwin', 'win32ui', 'cv2', 'pandas', 'pytest', '_pytest', 'rembg', 'pymatting', 'numba', 'llvmlite', 'pooch', 'natsort'],
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

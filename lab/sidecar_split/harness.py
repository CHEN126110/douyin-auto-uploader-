# -*- coding: utf-8 -*-
"""把任意一份 app.py 源码当成真正的 app 模块加载（隔离数据目录，不碰用户数据）。

关键：源码来自 source_path，但 __file__ 伪装成仓库里真实的 app.py 路径，
这样 repo_root、资源路径的推导和线上完全一致。
"""
import os
import sys
import tempfile
import types

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
SIDECAR = os.path.join(REPO, 'tauri-app', 'python-sidecar')
APP_PATH = os.path.join(SIDECAR, 'app.py')


def setup_env(data_dir=None):
    os.environ['SIDECAR_MODE'] = '1'
    if data_dir:
        os.environ['DOUYIN_DATA_DIR'] = data_dir
    else:
        os.environ.setdefault('DOUYIN_DATA_DIR', tempfile.mkdtemp(prefix='sidecar-data-'))
    for p in (SIDECAR, REPO):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        import capture_url_utils  # noqa: F401
    except ImportError:
        # 2026-10-20 起 capture_url_utils 在 src/ 里；搬迁前的旧 app.py（对打的基准）还按顶层模块名导入它
        import src.capture_url_utils as _moved
        sys.modules['capture_url_utils'] = _moved
    return os.environ['DOUYIN_DATA_DIR']


def load_app(source_path, name):
    setup_env()
    text = open(source_path, encoding='utf-8').read()
    mod = types.ModuleType(name)
    mod.__file__ = APP_PATH
    sys.modules[name] = mod
    exec(compile(text, APP_PATH, 'exec'), mod.__dict__)
    return mod


def route_table(app):
    rows = []
    for rule in app.url_map.iter_rules():
        methods = sorted(m for m in rule.methods if m not in ('HEAD', 'OPTIONS'))
        rows.append((rule.rule, tuple(methods)))
    return sorted(rows)

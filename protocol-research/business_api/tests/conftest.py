# -*- coding: utf-8 -*-
"""保证可从 protocol-research 作为根导入 business_api 包。"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 环境兼容垫片（仅作用于测试，不影响生产依赖）：
# 当前环境 Flask 2.3.2 的 test_client 会读取 werkzeug.__version__，而较新版 werkzeug
# 已移除该属性，导致 AttributeError。这里在测试期补一个兼容值即可，不改动任何运行时代码。
try:
    import werkzeug

    if not hasattr(werkzeug, "__version__"):
        try:
            from importlib.metadata import version as _pkg_version

            werkzeug.__version__ = _pkg_version("werkzeug")
        except Exception:
            werkzeug.__version__ = "0.0.0"
except Exception:
    pass

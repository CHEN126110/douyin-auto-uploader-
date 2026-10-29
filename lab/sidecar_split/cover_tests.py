# -*- coding: utf-8 -*-
"""用 pytest 的测试跑一遍，报告指定模块里“从未被执行过的语句”（2026-10-21，上传域第二步用）。

用法（仓库根执行）::

    python lab/sidecar_split/cover_tests.py src/sidecar/upload_service.py src/sidecar/upload_routes.py -- tests/test_upload_service.py tests/test_upload_routes.py

``--`` 前面是要看的模块文件，后面是原样传给 pytest 的参数。基于 ``sys.settrace``（lab 里的 ``linecover.py``），不依赖 coverage 库；
测试跑得会比平时慢几倍。报告和新旧对打的行覆盖是同一种格式：每个函数里没执行过的语句逐行列出。
适合回答“我写的单元测试到底有没有跑到每一条分支”——跑不到的要么补用例，要么写明为什么跑不到。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pytest  # noqa: E402
from linecover import Recorder, report  # noqa: E402

args = sys.argv[1:]
if '--' not in args:
    sys.exit(__doc__)
split = args.index('--')
modules, pytest_args = args[:split], args[split + 1:]
files = [os.path.abspath(m) for m in modules]
recorder = Recorder(files)
recorder.start()
try:
    code = pytest.main(['-q', '-p', 'no:cacheprovider', '--no-header', '-x'] + pytest_args)
finally:
    recorder.stop()
for path in files:
    report(path, open(path, encoding='utf-8').read(), recorder.hits)
sys.exit(int(code))

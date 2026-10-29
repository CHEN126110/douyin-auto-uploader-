# -*- coding: utf-8 -*-
"""驱动：python run_slice.py <slice_key[,slice_key...]> <before_app.py> <stage_dir>

生成 stage/src/sidecar/<module> 与 stage/app_<key>.py，并跑独立校验。
给多个 key（逗号分隔）时按顺序链式运行：后一个切片的输入是前一个切片生成的 app.py，
最终结果同时写到 stage/app_final.py。每一步的校验问题必须为 0，否则立即停止。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mover import Source  # noqa: E402
import slice_tool as T  # noqa: E402
from slice_defs import SLICES  # noqa: E402

keys, before_path, stage = sys.argv[1:4]
os.makedirs(os.path.join(stage, 'src', 'sidecar'), exist_ok=True)
current = before_path
failed = False
for key in keys.split(','):
    sl = SLICES[key]
    print('=' * 70)
    print('切片 %s -> src/sidecar/%s' % (key, sl.module_file))
    src = Source(current)
    module_text, problems = T.gen(sl, src)
    if problems:
        print('GEN PROBLEMS:')
        for p in problems:
            print('  -', p)
        sys.exit(2)
    before_text = open(current, encoding='utf-8').read()
    after_text = T.patch_app(sl, before_text)
    issues, changed, added = T.verify(sl, before_text, module_text, after_text)

    with io.open(os.path.join(stage, 'src', 'sidecar', sl.module_file), 'w', encoding='utf-8', newline='\n') as fp:
        fp.write(module_text)
    out_app = os.path.join(stage, 'app_%s.py' % key)
    with io.open(out_app, 'w', encoding='utf-8', newline='\n') as fp:
        fp.write(after_text)

    print('module lines:', len(module_text.splitlines()), '| app.py lines: %d -> %d' % (
        len(before_text.splitlines()), len(after_text.splitlines())))
    print('app.py 顶层节点变化（不含搬走的函数）：')
    for k in changed:
        print('   变更/删除:', k)
    for k in added:
        print('   新增:', k)
    print('校验问题 %d 个' % len(issues))
    for p in issues:
        print('  !!', p)
    if issues:
        failed = True
        break
    current = out_app

if not failed and ',' in keys:
    with io.open(os.path.join(stage, 'app_final.py'), 'w', encoding='utf-8', newline='\n') as fp:
        fp.write(open(current, encoding='utf-8').read())
    print('最终 app.py -> %s' % os.path.join(stage, 'app_final.py'))
sys.exit(1 if failed else 0)

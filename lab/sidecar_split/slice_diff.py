# -*- coding: utf-8 -*-
"""新旧对打：python slice_diff.py <scenario> <old|new> <app.py 路径> <输出json> <数据目录>

old：直接用搬迁前的 app.py（路由读 app.py 全局，所以 monkeypatch 全局）。
new：搬迁后的 app.py 只用来拿 Record 等依赖；被测 Blueprint 由场景脚本直接注册到一个干净的 Flask 里。
同一套请求、同一套假件，响应必须逐字相同（时间戳字段除外）。
"""
import json
import os
import re
import shutil
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

scenario_name, mode, app_path, out_path, data_dir = sys.argv[1:6]
if os.path.exists(data_dir):
    shutil.rmtree(data_dir)
os.makedirs(data_dir)
os.environ['DOUYIN_DATA_DIR'] = data_dir

from harness import load_app  # noqa: E402
import scenarios  # noqa: E402
import scen_settings_pricing  # noqa: E402,F401  （注册 settings_pricing 场景）
import scen_shop_debug  # noqa: E402,F401  （注册 debug 场景）
import scen_shop  # noqa: E402,F401  （注册 shop 场景）
import scen_import_xhs  # noqa: E402,F401  （注册 import_folders 场景）
import scen_xhs_batch  # noqa: E402,F401  （注册 xhs_batch 场景）
import scen_capture_flow  # noqa: E402,F401  （注册 capture 场景）
import scen_taobao  # noqa: E402,F401  （注册 taobao 场景）
import scen_upload  # noqa: E402,F401  （注册 upload 场景）

mod = load_app(app_path, 'app_' + mode)
ctx = types.SimpleNamespace(mod=mod, mode=mode, data_dir=data_dir, Record=mod.Record, state={})
sc = scenarios.SCENARIOS[scenario_name]

for old_row in mod.Record.select():
    old_row.delete_instance()
sc['setup'](ctx)

if mode == 'old':
    sc['patch_old'](ctx)
    client = mod.app.test_client()
elif sc.get('new_via_app'):
    # 新版直接用 app.py 自己的装配，只把注入端口里的外部能力换成假件
    sc['patch_new'](ctx)
    client = mod.app.test_client()
else:
    from flask import Flask
    test_app = Flask('slice_test')
    for bp in sc['build_new'](ctx):
        test_app.register_blueprint(bp)
    client = test_app.test_client()

TS_RE = re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?')
STAMP_RE = re.compile(r'\d{8}_\d{6}_\d{6}')   # 文件名 / 会话 id 里的 %Y%m%d_%H%M%S_%f
VOLATILE = re.compile(r'(_at$|^created|^updated|^last_updated|timestamp|^checked|duration_seconds|reload_time)')


def scrub(value):
    if isinstance(value, dict):
        return {k: ('<volatile>' if VOLATILE.search(k) else scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        text = value.replace('\\', '/').replace(data_dir.replace('\\', '/'), '<DATA_DIR>')
        return STAMP_RE.sub('<stamp>', TS_RE.sub('<ts>', text))
    return value


recorder = None
cover_spec = os.environ.get('SLICE_COVER', '').strip()
if cover_spec:
    import importlib
    import linecover
    import harness
    if mode == 'old':
        cover_files = {harness.APP_PATH}
    else:
        cover_files = {importlib.import_module('src.sidecar.' + n.strip()[:-3]).__file__
                       for n in cover_spec.split(',') if n.strip()}
    recorder = linecover.Recorder(cover_files)
    recorder.start()

results = []
for item in sc['requests'](ctx):
    method, path, payload = item[:3]
    opts = item[3] if len(item) > 3 else {}
    before = opts.get('before')
    if before:
        before(ctx)
    kwargs = {}
    if method == 'GET':
        resp = client.get(path)
    elif method == 'DELETE':
        resp = client.delete(path)
    elif method == 'PUT':
        resp = client.put(path, json=payload)
    elif opts.get('data') is not None:
        resp = client.post(path, data=opts['data'], content_type=opts.get('content_type'))
    else:
        resp = client.post(path, json=payload)
    ct = resp.headers.get('Content-Type', '')
    if 'json' in ct:
        body = resp.get_json()
    elif ct.startswith('image') or 'octet' in ct:
        body = '<binary %d bytes %s>' % (len(resp.get_data()), ct)
    else:
        body = resp.get_data(as_text=True)
    entry = {'method': method, 'path': path, 'status': resp.status_code, 'body': scrub(body)}
    probe = opts.get('after')
    if probe:
        entry['probe'] = scrub(probe(ctx))
    results.append(entry)

extra = sc.get('final')
final = scrub(extra(ctx)) if extra else None
if recorder is not None:
    recorder.stop()
    if mode == 'old':
        linecover.report(harness.APP_PATH, open(app_path, encoding='utf-8').read(), recorder.hits,
                         only_names={n.strip() for n in cover_spec.split(',') if n.strip()})
    else:
        for filename in sorted(recorder.wanted):
            linecover.report(filename, open(filename, encoding='utf-8').read(), recorder.hits)
with open(out_path, 'w', encoding='utf-8', newline='\n') as fp:
    json.dump({'results': results, 'final': final}, fp, ensure_ascii=False, indent=1, sort_keys=True)
ok = sum(1 for r in results if isinstance(r['body'], dict) and r['body'].get('success'))
print('scenario=%s mode=%s requests=%d success=%d' % (scenario_name, mode, len(results), ok))

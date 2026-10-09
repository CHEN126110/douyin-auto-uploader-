# -*- coding: utf-8 -*-
"""白底图接口冒烟测试：用 Flask test_client 在进程内打真实路由。

不起端口、不抢 5001 —— 桌面端的 python-backend.exe 正在占用 5001，
起第二个实例会互相打架。test_client 走的是同一套 WSGI 入口，
路由注册、参数解析、越界校验都是真的。

用法：
  python lab/whitebg/scripts/smoke_api.py
  python lab/whitebg/scripts/smoke_api.py --run   # 连带真跑一次生成（约 80 秒）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

DATA_DIR = r'C:\Users\CRB\AppData\Local\com.dyin.sock-publisher'
PRODUCT_DIR = os.path.join(DATA_DIR, 'uploads', 'products', 'ID-1075636304051')


def load_app():
    os.environ.setdefault('SIDECAR_MODE', '1')
    os.environ.setdefault('DOUYIN_DATA_DIR', DATA_DIR)
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    sidecar_dir = os.path.join(repo_root, 'tauri-app', 'python-sidecar')
    sys.path.insert(0, sidecar_dir)
    sys.path.insert(0, repo_root)
    os.chdir(sidecar_dir)
    import app as sidecar_app       # noqa: E402
    return sidecar_app.app


def show(label, resp):
    body = resp.get_data(as_text=True)
    try:
        parsed = json.loads(body)
        body = json.dumps(parsed, ensure_ascii=False)
    except Exception:
        pass
    print(f'  {label}: HTTP {resp.status_code}  {body[:400]}')
    return resp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', action='store_true', help='真跑一次生成任务')
    args = ap.parse_args()

    flask_app = load_app()
    routes = sorted(str(r.rule) for r in flask_app.url_map.iter_rules()
                    if '/api/whitebg' in str(r.rule))
    print('注册到的白底图路由:')
    for r in routes:
        print('  ', r)
    assert len(routes) == 5, f'路由数不对: {routes}'

    c = flask_app.test_client()
    print('\n[1] GET /api/whitebg/status')
    show('模型状态', c.get('/api/whitebg/status'))

    print('\n[2] GET /api/whitebg/list（按 product_dir）')
    show('已有产物', c.get('/api/whitebg/list', query_string={'product_dir': PRODUCT_DIR}))

    print('\n[3] 越界防护')
    show('list 越界', c.get('/api/whitebg/list', query_string={'product_dir': r'C:\Windows'}))
    show('image 越界', c.get('/api/whitebg/image',
                             query_string={'path': r'C:\Windows\win.ini'}))
    show('start 越界', c.post('/api/whitebg/start',
                              json={'product_dir': r'C:\Windows'}))

    print('\n[4] GET /api/whitebg/image（真实产物）')
    img = os.path.join(PRODUCT_DIR, '白底图.jpg')
    r = c.get('/api/whitebg/image', query_string={'path': img})
    print(f'  白底图.jpg: HTTP {r.status_code}  {len(r.get_data())} bytes  '
          f'{r.headers.get("Content-Type")}')

    print('\n[5] GET /api/whitebg/task/<不存在>')
    show('不存在的任务', c.get('/api/whitebg/task/deadbeef'))

    if args.run:
        print('\n[6] POST /api/whitebg/start + 轮询')
        r = show('启动', c.post('/api/whitebg/start', json={'product_dir': PRODUCT_DIR}))
        task_id = (r.get_json() or {}).get('data', {}).get('task_id')
        assert task_id, '没拿到 task_id'
        last = ''
        for _ in range(200):
            time.sleep(2)
            t = (c.get(f'/api/whitebg/task/{task_id}').get_json() or {}).get('data') or {}
            line = f"{t.get('status')} {t.get('progress')}% {t.get('message')}"
            if line != last:
                print('   ', line)
                last = line
            if t.get('status') in ('success', 'failed'):
                res = t.get('result') or {}
                print('    白底图目录:', res.get('white_dir'))
                print('    规格图目录:', res.get('square_dir'))
                print('    目录根白底图:', res.get('white_root'))
                break
        else:
            print('    轮询超时')

    print('\n冒烟测试结束')


if __name__ == '__main__':
    main()

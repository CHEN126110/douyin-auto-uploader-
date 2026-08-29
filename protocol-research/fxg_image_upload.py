# -*- coding: utf-8 -*-
"""Douyin FXG 图片协议上传测试。
通过 CDP 浏览器 Cookies + Python HTTP multipart 上传图片到 batchupload 端点。
"""

import json, os, sys, time, base64, re
from urllib.request import urlopen, Request
from urllib.parse import urlencode
import websocket


def get_browser_cookies(cdp_port=9333):
    """从 CDP 浏览器获取 cookies"""
    targets = json.loads(urlopen(f'http://127.0.0.1:{cdp_port}/json/list', timeout=3).read())
    target = next((t for t in targets if 'jinritemai.com' in (t.get('url') or '')), None)
    if not target:
        target = next((t for t in targets if t.get('type') == 'page'), None)
    if not target:
        return '', ''

    ws = websocket.create_connection(target['webSocketDebuggerUrl'], timeout=5, suppress_origin=True)
    mid = [0]

    def cdp(method, params=None):
        mid[0] += 1
        ws.send(json.dumps({'id': mid[0], 'method': method, 'params': params or {}}))
        deadline = time.time() + 10
        while time.time() < deadline:
            raw = ws.recv()
            msg = json.loads(raw)
            if msg.get('id') == mid[0]:
                return msg
        return {}

    cdp('Network.enable')
    r = cdp('Network.getAllCookies')

    cookies = (r.get('result') or {}).get('cookies') or []
    cookie_str = '; '.join(f"{c['name']}={c['value']}" for c in cookies if 'jinritemai' in (c.get('domain', '')))

    # 从页面提取 CSRF token
    r2 = cdp('Runtime.evaluate', {
        'expression': '''
            (function() {
                var csrf = document.cookie.match(/(?:^|;\\s*)XSRF-TOKEN=([^;]*)/);
                return csrf ? csrf[1] : '';
            })()
        ''',
        'returnByValue': True
    })
    csrf_token = ((r2.get('result') or {}).get('result') or {}).get('value', '')

    ws.close()
    return cookie_str, csrf_token


def upload_single_image(image_path, cookie_str, csrf_token=''):
    """上传单张图片到 batchupload，返回图片 URL"""
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图片不存在: {image_path}")

    filename = os.path.basename(image_path)
    ext = os.path.splitext(filename)[1].lower()

    mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                '.webp': 'image/webp', '.bmp': 'image/bmp', '.gif': 'image/gif'}
    mime_type = mime_map.get(ext, 'image/png')

    with open(image_path, 'rb') as f:
        image_data = f.read()

    # 构建 multipart/form-data
    boundary = '----WebKitFormBoundary' + os.urandom(16).hex()
    body_parts = []
    body_parts.append(f'--{boundary}'.encode())
    body_parts.append(f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\nContent-Type: {mime_type}'.encode())
    body_parts.append(b'')
    body_parts.append(image_data)
    body_parts.append(f'--{boundary}--'.encode())
    body = b'\r\n'.join(body_parts)

    url = 'https://fxg.jinritemai.com/product/img/batchupload'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120',
        'Cookie': cookie_str,
        'Content-Type': f'multipart/form-data; boundary={boundary}',
        'Accept': 'application/json',
        'Referer': 'https://fxg.jinritemai.com/ffa/g/create',
        'Origin': 'https://fxg.jinritemai.com',
    }
    if csrf_token:
        headers['X-XSRF-TOKEN'] = csrf_token

    req = Request(url, data=body, headers=headers, method='POST')
    try:
        resp = urlopen(req, timeout=30)
        result = json.loads(resp.read().decode('utf-8'))
        return {'ok': True, 'response': result}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def main():
    cdp_port = int(os.environ.get('CDP_PORT', 9333))
    image_path = os.environ.get('IMAGE_PATH', '')

    if not image_path:
        print("Usage: IMAGE_PATH=/path/to/image.jpg python fxg_image_upload.py")
        print("  或通过环境变量 IMAGE_PATH 指定图片路径")
        sys.exit(1)

    print(f"[*] 连接 CDP 端口 {cdp_port}...")
    cookie_str, csrf_token = get_browser_cookies(cdp_port)
    print(f"[*] Cookie: {len(cookie_str)} chars, CSRF: {bool(csrf_token)}")

    print(f"[*] 上传图片: {image_path}")
    result = upload_single_image(image_path, cookie_str, csrf_token)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

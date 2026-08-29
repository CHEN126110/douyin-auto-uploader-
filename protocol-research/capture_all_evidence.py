# -*- coding: utf-8 -*-
"""Douyin FXG 协议证据全集探针。
通过 CDP 连接到已登录的 fxg.jinritemai.com 发布页，
拦截所有关键 API 请求，保存去敏后的请求/响应证据。

用法:
  python capture_all_evidence.py [--port 9333] [--duration 120] [--output evidence.json]

在运行期间，在浏览器中正常操作发布流程:
  填写标题 → 上传图片 → 选类目 → 填属性 → 配置SKU → 填价格库存 → 保存草稿/发布
脚本会自动拦截所有 API 请求并保存证据。
"""

import json, os, sys, time, argparse, hashlib, re
from urllib.request import urlopen
from urllib.parse import urlparse, parse_qs

try:
    import websocket
except ImportError:
    print("请安装 websocket-client: pip install websocket-client")
    sys.exit(1)

# 需要拦截的 API 端点模式
TARGET_PATTERNS = [
    'addWithSchema', 'editWithSchema',
    'getSchema', 'searchCategoryN', 'refetchSchema',
    'batchupload', 'saveMaterial', 'submitWhiteImg',
    'tproduct', 'product',
]


def sanitize_value(val):
    """去敏：替换敏感字段值为占位符"""
    if isinstance(val, str) and len(val) > 100 and val.count('/') > 5:
        return f"[LONG_URL_{len(val)}]"
    return val


def sanitize_obj(obj, depth=0):
    """递归去敏"""
    if depth > 10:
        return "[MAX_DEPTH]"
    if isinstance(obj, dict):
        sensitive_keys = {'cookie', 'token', 'authorization', 'set-cookie', 'x-csrf-token'}
        return {
            k: sanitize_obj(v, depth + 1) if k not in sensitive_keys else '[REDACTED]'
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [sanitize_obj(v, depth + 1) for v in obj[:50]]
    return sanitize_value(obj)


def connect_cdp(cdp_port, target_filter=None):
    """连接到 CDP 页面的 WebSocket"""
    targets = json.loads(urlopen(f'http://127.0.0.1:{cdp_port}/json/list', timeout=3).read())
    target = next(
        (t for t in targets if t.get('type') == 'page' and (target_filter or '') in (t.get('url') or '')),
        None
    )
    if not target and targets:
        target = next((t for t in targets if t.get('type') == 'page'), None)
    if not target:
        raise Exception("No page target found")
    ws = websocket.create_connection(target['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
    return ws, target


def cdp_send(ws, msg_id_counter, method, params=None, timeout=15):
    """发送 CDP 命令并等待响应"""
    msg_id_counter[0] += 1
    ws.send(json.dumps({'id': msg_id_counter[0], 'method': method, 'params': params or {}}, ensure_ascii=False))
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = ws.recv()
        msg = json.loads(raw)
        if msg.get('id') == msg_id_counter[0]:
            return msg
    return {'error': 'timeout', 'method': method}


def matches_target(url):
    """检查 URL 是否匹配目标 API"""
    url_lower = url.lower()
    return any(pattern.lower() in url_lower for pattern in TARGET_PATTERNS) and 'jinritemai.com' in url_lower


def main():
    parser = argparse.ArgumentParser(description='Douyin FXG 协议证据收集')
    parser.add_argument('--port', type=int, default=9333, help='CDP 调试端口')
    parser.add_argument('--duration', type=int, default=120, help='收集持续时间(秒)')
    parser.add_argument('--output', type=str, default=None, help='输出 JSON 文件路径')
    parser.add_argument('--block', action='store_true', help='是否拦截请求(本地中止)')
    args = parser.parse_args()

    cdp_port = int(os.environ.get('CDP_PORT', args.port))
    duration = int(os.environ.get('DURATION_MS', args.duration * 1000)) / 1000
    output_path = os.environ.get('OUTPUT_PATH') or args.output

    print(f"[*] 连接到 CDP 端口 {cdp_port}...")
    ws, target = connect_cdp(cdp_port, 'jinritemai.com')
    print(f"[*] 已连接: {target['url'][:80]}")
    print(f"[*] 收集持续时间: {duration}s")
    print(f"[*] 拦截模式: {'是' if args.block else '否'}")
    print()

    msg_id = [0]
    evidence = {
        'source_url': target['url'],
        'capture_start': time.strftime('%Y-%m-%d %H:%M:%S'),
        'targets': {},
        'requests': [],
        'responses': [],
    }
    captured_ids = set()
    body_cache = {}

    # 启用 Network 域
    cdp_send(ws, msg_id, 'Network.enable')
    print("[+] Network.enable 已启用")
    print(f"[*] 现在请在浏览器中操作发布流程（{duration}秒内）...")
    print()

    deadline = time.time() + duration
    while time.time() < deadline:
        remaining = int(deadline - time.time())
        if remaining % 10 == 0 and remaining > 0:
            print(f"  剩余 {remaining}s...", end='\r')

        try:
            raw = ws.recv()
        except Exception:
            break

        try:
            msg = json.loads(raw)
        except Exception:
            continue

        method = msg.get('method', '')

        if method == 'Network.requestWillBeSent':
            req = msg['params']['request']
            url = req.get('url', '')
            if matches_target(url):
                rid = msg['params']['requestId']
                captured_ids.add(rid)
                evidence['requests'].append({
                    'requestId': rid,
                    'url': url,
                    'method': req.get('method', ''),
                    'headers': sanitize_obj(req.get('headers', {})),
                    'postData': req.get('postData', '')[:5000] if req.get('postData') else '',
                })

                # 解析 API 名称
                parsed = urlparse(url)
                path_parts = parsed.path.split('/')
                api_name = next((p for p in path_parts if any(t in p for t in ['product', 'addWith', 'editWith', 'getSchema', 'batchupload', 'saveMaterial', 'searchCategory', 'refetchSchema'])), path_parts[-1])
                if api_name not in evidence['targets']:
                    evidence['targets'][api_name] = []
                evidence['targets'][api_name].append(url)

        elif method == 'Network.responseReceived':
            url = msg['params']['response'].get('url', '')
            rid = msg['params'].get('requestId', '')
            if rid in captured_ids:
                # 获取响应体
                try:
                    body_result = cdp_send(ws, msg_id, 'Network.getResponseBody', {'requestId': rid}, timeout=8)
                    body_text = ((body_result.get('result') or {}).get('body') or '')
                    if body_text:
                        body_cache[rid] = body_text
                        try:
                            parsed_body = json.loads(body_text)
                            body_preview = sanitize_obj(parsed_body)
                        except (json.JSONDecodeError, TypeError):
                            body_preview = body_text[:2000]

                        evidence['responses'].append({
                            'requestId': rid,
                            'url': url,
                            'status': msg['params']['response'].get('status', 0),
                            'mimeType': msg['params']['response'].get('mimeType', ''),
                            'body': body_preview if isinstance(body_preview, str) else json.dumps(body_preview, ensure_ascii=False),
                        })
                except Exception:
                    pass

        elif method == 'Fetch.requestPaused' and args.block:
            rid = msg['params']['requestId']
            url = msg['params']['request']['url']
            if matches_target(url):
                print(f"  [!] 拦截: {url[:100]}")
                cdp_send(ws, msg_id, 'Fetch.failRequest', {'requestId': rid, 'errorReason': 'BlockedByClient'})

    ws.close()
    print(f"\n[*] 收集完成")

    # 汇总
    print(f"\n=== 证据汇总 ===")
    print(f"API 端点: {len(evidence['targets'])}")
    for name, urls in evidence['targets'].items():
        print(f"  {name}: {len(urls)} 个请求")

    print(f"请求记录: {len(evidence['requests'])}")
    print(f"响应记录: {len(evidence['responses'])}")

    # 保存
    if not output_path:
        ts = time.strftime('%Y%m%d_%H%M%S')
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'tmp_runtime_probe_live',
            f'fxg_evidence_{ts}.json'
        )
    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2)
    print(f"\n[+] 证据已保存: {output_path}")


if __name__ == '__main__':
    main()

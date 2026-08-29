from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import Request, urlopen

import websocket
from websocket import WebSocketTimeoutException

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SIDECAR_ROOT = SCRIPT_PATH.parents[2]
REPO_ROOT = SCRIPT_PATH.parents[4]
for path in (REPO_ROOT, PYTHON_SIDECAR_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from protocol_publish.measure_info_variants import (  # noqa: E402
    build_measure_info_variants,
    build_named_variant,
    normalize_text,
)
from protocol_publish.stages.price_stock_protocol import (  # noqa: E402
    replay_price_stock_protocol_request,
)
from src.utils import attach_existing_debug_browser  # noqa: E402


def _read_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as fp:
        payload = json.load(fp)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 文件必须是对象：{path}")
    return payload


def _extract_submit_request(capture: dict[str, Any]) -> dict[str, Any]:
    requests = capture.get("requests")
    if not isinstance(requests, list):
        raise ValueError("capture.requests 不是数组")

    matched: list[dict[str, Any]] = []
    for request in requests:
        if not isinstance(request, dict):
            continue
        url = request.get("url") if isinstance(request.get("url"), dict) else {}
        path = normalize_text(url.get("path") or url.get("sanitized"))
        if "/product/tproduct/addWithSchema" in path or "/product/tproduct/editWithSchema" in path:
            matched.append(request)

    if not matched:
        raise ValueError("未在 capture 中找到 addWithSchema/editWithSchema 请求")

    for request in reversed(matched):
        if bool(request.get("blocked")) or bool(request.get("intercepted")):
            return request
    return matched[-1]


def _load_variants(capture: dict[str, Any], variants_path: str) -> dict[str, Any]:
    if variants_path:
        payload = _read_json(variants_path)
        if not isinstance(payload.get("variants"), list):
            raise ValueError("variants 文件缺少 variants 数组")
        return payload
    return build_measure_info_variants(capture)


def _parse_variant_names(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        for item in str(value or "").split(","):
            name = normalize_text(item)
            if name and name not in normalized:
                normalized.append(name)
    return normalized


def _select_variants(variants_payload: dict[str, Any], selected_names: list[str]) -> list[dict[str, Any]]:
    variants = variants_payload.get("variants")
    if not isinstance(variants, list):
        raise ValueError("variants 不是数组")

    normalized = []
    for variant in variants:
        if isinstance(variant, dict):
            normalized.append(variant)

    if not selected_names:
        return normalized

    selected: list[dict[str, Any]] = []
    selected_set = set(selected_names)
    for variant in normalized:
        name = normalize_text(variant.get("name"))
        if name in selected_set:
            selected.append(variant)

    missing = [name for name in selected_names if name not in {normalize_text(item.get("name")) for item in normalized}]
    if missing:
        raise ValueError(f"未找到指定变体: {', '.join(missing)}")
    return selected


def _current_tab_url(tab: Any) -> str:
    for getter in (
        lambda: str(getattr(tab, "url", "") or ""),
        lambda: str(tab.run_js("return location.href || '';") or ""),
    ):
        try:
            value = getter()
        except Exception:
            value = ""
        if value:
            return value
    return ""


def _attach_main_tab(debug_address: str, target_url_contains: str, allow_url_mismatch: bool) -> tuple[Any, str]:
    page = attach_existing_debug_browser(debug_address, existing_only=True)
    tab = page.get_tab(page.latest_tab)
    current_url = _current_tab_url(tab)
    if target_url_contains and target_url_contains not in current_url and not allow_url_mismatch:
        raise ValueError(
            f"当前页 URL 不符合预期，要求包含 {target_url_contains}，实际为 {current_url or '<empty>'}"
        )
    return tab, current_url


def _click_trigger(tab: Any, trigger: str) -> None:
    selectors = {
        "save_draft": 'xpath://span[text()="保存草稿"]/..',
        "publish": 'xpath://span[text()="发布商品"]/..',
    }
    selector = selectors.get(trigger)
    if not selector:
        raise ValueError(f"不支持的 trigger: {trigger}")

    button = tab.ele(selector, timeout=1.5)
    if not button:
        raise RuntimeError(f"未找到触发按钮: {trigger}")
    button.scroll.to_center()
    button.click(by_js=True)


def _handle_publish_reminder(tab: Any) -> bool:
    try:
        modal = tab.ele('xpath://div[@class="ecom-g-modal-title"][text()="发布提醒"]/../..', timeout=0.3)
    except Exception:
        modal = None
    if not modal:
        return False

    continue_btn = modal.ele('xpath:.//div[text()="不修改，继续发布"]/ancestor::button', timeout=0.5)
    if not continue_btn:
        return False
    continue_btn.scroll.to_center()
    continue_btn.click(by_js=True)
    return True


def _normalize_protocol_response(response: dict[str, Any]) -> dict[str, Any]:
    status = int(response.get("status") or 0)
    response_text = str(response.get("responseText") or "")
    body_json = None
    try:
        body_json = json.loads(response_text) if response_text else None
    except json.JSONDecodeError:
        body_json = None

    success = 200 <= status < 300
    failure_reason = ""
    if body_json is not None and isinstance(body_json, dict):
        if body_json.get("success") is False:
            success = False
        for key in ("code", "status_code", "statusCode", "errno", "st"):
            if key in body_json:
                raw_value = body_json.get(key)
                try:
                    if int(raw_value) != 0:
                        success = False
                        failure_reason = str(body_json.get("msg") or body_json.get("message") or raw_value)
                except Exception:
                    if str(raw_value or "").strip() not in {"", "0", "success", "ok"}:
                        success = False
                        failure_reason = str(body_json.get("msg") or body_json.get("message") or raw_value)
                break
        if not failure_reason:
            failure_reason = str(body_json.get("msg") or body_json.get("message") or "")
    elif not success:
        failure_reason = response_text[:300]

    return {
        "success": success,
        "status": status,
        "response_url": response.get("responseUrl") or "",
        "failure_reason": failure_reason.strip(),
        "response_json": body_json,
        "response_text_preview": response_text[:2000],
    }


def _default_headers() -> dict[str, str]:
    return {
        "content-type": "application/json;charset=UTF-8",
    }


def _sanitize_header_names(headers: dict[str, Any]) -> list[str]:
    return sorted(str(key) for key in headers.keys())


def _request_url_summary(url: str) -> dict[str, Any]:
    parsed = urlsplit(str(url or ""))
    return {
        "path": parsed.path,
        "query_keys": [key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)],
    }


def _prepare_request_source_summary(source_request: dict[str, Any]) -> dict[str, Any]:
    url = source_request.get("url") if isinstance(source_request.get("url"), dict) else {}
    return {
        "request_id": source_request.get("requestId"),
        "method": source_request.get("method"),
        "path": url.get("path") or "",
        "sanitized_url": url.get("sanitized") or "",
        "query_keys": url.get("queryKeys") or [],
        "blocked": bool(source_request.get("blocked")),
        "intercepted": bool(source_request.get("intercepted")),
    }


def _build_prepare_result(
    *,
    capture_path: str,
    variants_payload: dict[str, Any],
    selected_variants: list[dict[str, Any]],
    source_request: dict[str, Any],
) -> dict[str, Any]:
    return {
        "mode": "measure_info_replay_prepare",
        "execute_live": False,
        "capture_path": capture_path,
        "request_source": _prepare_request_source_summary(source_request),
        "variant_count": len(selected_variants),
        "available_variant_names": [
            normalize_text(item.get("name"))
            for item in (variants_payload.get("variants") or [])
            if isinstance(item, dict)
        ],
        "selected_variants": [
            {
                "name": variant.get("name"),
                "mutation_scope": variant.get("mutation_scope"),
                "description": variant.get("description"),
                "property_785": variant.get("property_785"),
            }
            for variant in selected_variants
        ],
        "note": (
            "该输出仅用于确认将要执行的变体内容。"
            "要进入 live replay，需额外传入 --execute-live，并让脚本先从当前发布页捕获未脱敏的 addWithSchema 请求。"
        ),
    }


class _CdpClient:
    def __init__(self, websocket_url: str) -> None:
        self._ws = websocket.create_connection(websocket_url, timeout=8, suppress_origin=True)
        self._message_id = 0
        self._events: deque[dict[str, Any]] = deque()

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass

    def _recv_until(self, predicate, timeout_seconds: float) -> dict[str, Any]:
        deadline = time.time() + max(timeout_seconds, 0.1)
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            self._ws.settimeout(remaining)
            try:
                raw = self._ws.recv()
            except WebSocketTimeoutException:
                continue
            message = json.loads(raw)
            if predicate(message):
                return message
            if isinstance(message, dict) and message.get("method"):
                self._events.append(message)
        raise TimeoutError("等待 CDP 消息超时")

    def call(self, method: str, params: dict[str, Any] | None = None, timeout_seconds: float = 10.0) -> dict[str, Any]:
        self._message_id += 1
        message_id = self._message_id
        self._ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        return self._recv_until(lambda message: message.get("id") == message_id, timeout_seconds)

    def wait_event(self, method: str, timeout_seconds: float) -> dict[str, Any]:
        deadline = time.time() + max(timeout_seconds, 0.1)
        while time.time() < deadline:
            for _ in range(len(self._events)):
                message = self._events.popleft()
                if message.get("method") == method:
                    return message
                self._events.append(message)
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            message = self._recv_until(lambda item: bool(item.get("method")), min(remaining, 1.0))
            if message.get("method") == method:
                return message
            self._events.append(message)
        raise TimeoutError(f"等待 CDP 事件超时: {method}")


def _prepare_python_http_headers(headers: dict[str, Any]) -> dict[str, str]:
    blocked = {
        "connection",
        "content-length",
        "host",
        "transfer-encoding",
    }
    prepared: dict[str, str] = {}
    for key, value in (headers or {}).items():
        header_key = str(key or "").strip()
        if not header_key:
            continue
        if header_key.lower() in blocked:
            continue
        prepared[header_key] = str(value or "")
    prepared.setdefault("Content-Type", "application/json;charset=UTF-8")
    return prepared


def _replay_via_python_http(
    *,
    url: str,
    method: str,
    headers: dict[str, Any] | None,
    body_text: str,
) -> dict[str, Any]:
    request = Request(
        url=str(url or ""),
        data=str(body_text or "").encode("utf-8"),
        headers=_prepare_python_http_headers(headers or {}),
        method=str(method or "POST").upper(),
    )
    try:
        with urlopen(request, timeout=20) as response:
            response_text = response.read().decode("utf-8", errors="replace")
            return {
                "ok": 200 <= response.status < 300,
                "status": int(response.status),
                "responseText": response_text,
                "responseUrl": response.geturl(),
            }
    except HTTPError as error:
        response_text = error.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status": int(error.code or 0),
            "responseText": response_text,
            "responseUrl": error.geturl() or str(url or ""),
        }
    except URLError as error:
        return {
            "ok": False,
            "status": 0,
            "responseText": str(error.reason),
            "responseUrl": str(url or ""),
        }


def _resolve_target_websocket_url(debug_address: str, target_url_contains: str) -> str:
    list_url = f"http://{debug_address}/json/list"
    with urlopen(list_url, timeout=5) as response:
        targets = json.loads(response.read().decode("utf-8"))
    if not isinstance(targets, list):
        raise ValueError(f"CDP target 列表格式异常: {list_url}")

    matches = []
    for target in targets:
        if not isinstance(target, dict):
            continue
        if target.get("type") != "page":
            continue
        if target_url_contains and target_url_contains not in str(target.get("url") or ""):
            continue
        if not target.get("webSocketDebuggerUrl"):
            continue
        matches.append(target)
    if not matches:
        raise ValueError(f"未找到匹配的 CDP 页面 target: {target_url_contains}")
    return str(matches[0]["webSocketDebuggerUrl"])


def _capture_submit_request_via_cdp(
    *,
    tab: Any,
    debug_address: str,
    target_url_contains: str,
    trigger: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    client = _CdpClient(_resolve_target_websocket_url(debug_address, target_url_contains))
    reminder_handled = False
    try:
        client.call(
            "Fetch.enable",
            {
                "patterns": [
                    {
                        "urlPattern": "*://*/product/tproduct/*WithSchema*",
                        "requestStage": "Request",
                    }
                ]
            },
        )
        client.call(
            "Network.enable",
            {
                "maxTotalBufferSize": 10_000_000,
                "maxResourceBufferSize": 5_000_000,
                "maxPostDataSize": 10 * 1024 * 1024,
            },
        )
        _click_trigger(tab, trigger)
        deadline = time.time() + max(timeout_seconds, 0.5)
        while time.time() < deadline:
            if trigger == "publish" and not reminder_handled:
                reminder_handled = _handle_publish_reminder(tab) or reminder_handled
            try:
                event = client.wait_event("Fetch.requestPaused", timeout_seconds=0.5)
            except TimeoutError:
                continue
            params = event.get("params") if isinstance(event.get("params"), dict) else {}
            request = params.get("request") if isinstance(params.get("request"), dict) else {}
            url = str(request.get("url") or "")
            if "/product/tproduct/addWithSchema" not in url and "/product/tproduct/editWithSchema" not in url:
                client.call("Fetch.continueRequest", {"requestId": params.get("requestId")})
                continue
            request_id = str(params.get("requestId") or "")
            if not request_id:
                raise ValueError("CDP requestPaused 缺少 requestId")
            client.call("Fetch.failRequest", {"requestId": request_id, "errorReason": "Aborted"})
            return {
                "requestId": request_id,
                "method": str(request.get("method") or "POST").upper(),
                "url": url,
                "headers": request.get("headers") if isinstance(request.get("headers"), dict) else {},
                "postData": str(request.get("postData") or ""),
                "resourceType": params.get("resourceType"),
                "reminder_handled": reminder_handled,
            }
        raise TimeoutError("等待 CDP 拦截 addWithSchema/editWithSchema 超时")
    finally:
        try:
            client.call("Fetch.disable")
        except Exception:
            pass
        client.close()


def _execute_live_replay(
    *,
    debug_address: str,
    target_url_contains: str,
    allow_url_mismatch: bool,
    trigger: str,
    capture_wait_seconds: float,
    selected_variants: list[dict[str, Any]],
    replay_transport: str,
) -> dict[str, Any]:
    tab, current_url = _attach_main_tab(debug_address, target_url_contains, allow_url_mismatch)
    captured = _capture_submit_request_via_cdp(
        tab=tab,
        debug_address=debug_address,
        target_url_contains=target_url_contains,
        trigger=trigger,
        timeout_seconds=capture_wait_seconds,
    )
    captured_headers = captured.get("headers") if isinstance(captured.get("headers"), dict) else {}
    request_headers = dict(captured_headers)
    request_headers.setdefault("content-type", "application/json;charset=UTF-8")
    captured_body_text = str(captured.get("postData") or "")
    if not captured_body_text:
        raise ValueError("CDP 已拦截请求，但 postData 为空")
    live_request_body = json.loads(captured_body_text)
    if not isinstance(live_request_body, dict):
        raise ValueError("CDP 拦截到的请求体不是 JSON 对象")

    results: list[dict[str, Any]] = []
    for selected_variant in selected_variants:
        variant_name = normalize_text(selected_variant.get("name"))
        variant = build_named_variant(live_request_body, variant_name)
        request_body = variant.get("request_body") if isinstance(variant.get("request_body"), dict) else {}
        body_text = json.dumps(request_body, ensure_ascii=False, separators=(",", ":"))
        if replay_transport == "python_http":
            replay_response = _replay_via_python_http(
                url=str(captured.get("url") or ""),
                method=str(captured.get("method") or "POST"),
                headers=request_headers or _default_headers(),
                body_text=body_text,
            )
        else:
            replay_response = replay_price_stock_protocol_request(
                tab,
                url=str(captured.get("url") or ""),
                method=str(captured.get("method") or "POST"),
                headers=request_headers or _default_headers(),
                body_text=body_text,
            )
        results.append(
            {
                "name": variant.get("name"),
                "mutation_scope": variant.get("mutation_scope"),
                "description": variant.get("description"),
                "property_785": variant.get("property_785"),
                "request_body_size": len(body_text),
                "replay_transport": replay_transport,
                "response": _normalize_protocol_response(replay_response),
            }
        )

    return {
        "mode": "measure_info_replay_live",
        "execute_live": True,
        "page_url": current_url,
        "debug_address": debug_address,
        "trigger": trigger,
        "replay_transport": replay_transport,
        "captured_request": {
            "channel": "cdp_fetch_intercept",
            "method": captured.get("method"),
            "request_id": captured.get("requestId"),
            "resource_type": captured.get("resourceType"),
            "url_summary": _request_url_summary(str(captured.get("url") or "")),
            "request_header_names": _sanitize_header_names(request_headers),
            "request_body_preview": captured_body_text[:2000],
            "reminder_handled": bool(captured.get("reminder_handled")),
        },
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "基于 deep capture 生成的 785.measure_info 变体，"
            "在当前已登录 FXG 发布页中执行受控 replay。"
            "默认只输出准备信息，不发送请求。"
        )
    )
    parser.add_argument("--capture", required=True, help="deep addWithSchema capture JSON 路径")
    parser.add_argument("--variants", default="", help="可选，已生成的 variants JSON 路径")
    parser.add_argument("--variant", action="append", default=[], help="可选，指定要执行的变体名，可重复传入或逗号分隔")
    parser.add_argument("--output", default="", help="可选，输出 JSON 路径")
    parser.add_argument("--execute-live", action="store_true", help="启用 live replay；否则只输出准备信息")
    parser.add_argument("--debug-address", default="127.0.0.1:9222", help="已登录调试浏览器地址，默认 127.0.0.1:9222")
    parser.add_argument(
        "--target-url-contains",
        default="fxg.jinritemai.com/ffa/g/create",
        help="要求当前激活页 URL 包含的片段，默认 fxg.jinritemai.com/ffa/g/create",
    )
    parser.add_argument(
        "--trigger",
        default="save_draft",
        choices=["save_draft", "publish"],
        help="live 模式下先在页内抓真实请求所用的按钮，默认 save_draft",
    )
    parser.add_argument(
        "--replay-transport",
        default="browser_xhr",
        choices=["browser_xhr", "python_http"],
        help="live 模式下重放变体请求所用的通道，默认 browser_xhr；python_http 可用于排除页内 XHR 被拦截的情况",
    )
    parser.add_argument("--capture-wait-seconds", type=float, default=8.0, help="live 模式下等待 CDP 拦截提交请求的超时时间")
    parser.add_argument("--allow-url-mismatch", action="store_true", help="允许当前页 URL 不匹配 target-url-contains")
    args = parser.parse_args()

    capture = _read_json(args.capture)
    source_request = _extract_submit_request(capture)
    variants_payload = _load_variants(capture, args.variants)
    selected_variants = _select_variants(variants_payload, _parse_variant_names(args.variant))

    if not selected_variants:
        raise ValueError("没有可执行的变体")

    if args.execute_live:
        result = _execute_live_replay(
            debug_address=normalize_text(args.debug_address) or "127.0.0.1:9222",
            target_url_contains=normalize_text(args.target_url_contains),
            allow_url_mismatch=bool(args.allow_url_mismatch),
            trigger=normalize_text(args.trigger) or "save_draft",
            capture_wait_seconds=float(args.capture_wait_seconds or 6.0),
            selected_variants=selected_variants,
            replay_transport=normalize_text(args.replay_transport) or "browser_xhr",
        )
    else:
        result = _build_prepare_result(
            capture_path=args.capture,
            variants_payload=variants_payload,
            selected_variants=selected_variants,
            source_request=source_request,
        )

    output_text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_text + "\n", encoding="utf-8")
    else:
        print(output_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

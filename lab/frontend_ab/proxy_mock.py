# -*- coding: utf-8 -*-
"""
验证用代理：监听 127.0.0.1:5003（可用环境变量 AB_PROXY_PORT 改），把请求转发给隔离的 Sidecar（5002）。

前端把后端地址写死成 127.0.0.1:5001，而 5001 是**真实桌面应用**的 Sidecar 端口（验证时它可能正在运行，
里面是用户的真实数据），所以本代理不占 5001：验证用的前端开发服务器由 vite.ab.config.mts 把页面里的
5001 改写成代理端口，被测源码一个字不改。

只做三件事：
1. 记录每个请求（方法 / 路径 / 查询 / 请求体），供拆分前后逐条对比；
2. 对「会真的去操作抖店 / 淘宝 / 小红书」的发布类接口给出受控的假响应，
   这样前端的发布流程可以完整走一遍，而不会真的启动浏览器或发布；
3. 提供 /__ctl/* 控制与抓取接口（保存 DOM 快照、切换假场景、读取请求日志）。

其余请求（商品、设置、定价、图片……）原样转发给真实后端。
"""
import http.client
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

LISTEN = ("127.0.0.1", int(os.environ.get("AB_PROXY_PORT", "5003")))
UPSTREAM = ("127.0.0.1", int(os.environ.get("UPSTREAM_PORT", "5002")))
HERE = os.path.dirname(os.path.abspath(__file__))
# 工作目录（隔离数据、抓取到的快照与请求日志都放这里，已被 .gitignore 忽略）
WORK = os.environ.get("AB_WORK") or os.path.join(HERE, ".work")
CAP = os.path.join(WORK, "captures")
os.makedirs(CAP, exist_ok=True)

lock = threading.Lock()
LOG = []
STATE = {
    "mock_platform": None,       # None：/api/shop/current 转发真实后端；否则返回该平台的假账户
    "upload_mode": "success",    # success | failed | stuck | flaky
    "start_mode": "ok",          # ok | reject | no_task_id | http500
    "flaky_failures": 7,         # flaky：前 N 次状态查询返回 500
    "external_tasks": [],        # /api/upload/tasks 返回的外部任务
    "taobao_external": [],       # /api/taobao/publish/tasks 返回的外部任务
    "taobao_mode": "fill_ok",    # fill_ok | fill_unverified | publish_ok
    "xhs_ok": True,
    "freight_mode": None,        # None 转发真实后端；ok | missing | need_publish_page | http500
    "capture_mode": None,        # None 转发真实后端；success | failed | stuck：采集接口给假响应
    "mock_deletes": False,       # True：/menu_delete 与 /delete_all 只返回成功，不碰真实数据
    "mock_publish_save": False,  # True：for_publish 的 /save_info 返回假的 record_revision
    "settings_fail": False,      # True：GET /settings 返回 500，用来走「设置加载失败」分支
}
TASKS = {}   # task_id -> {polls, platform, record_id, account_profile, cancelled, stop_before_submit, dry_run}
COUNTER = {"n": 0}

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
}


def shop_state(platform):
    labels = {"douyin": "抖音", "taobao": "淘宝", "xiaohongshu": "小红书千帆"}
    return {
        "platform": platform,
        "active_profile": f"mock-{platform}",
        "active_profile_label": f"测试{labels[platform]}账户",
        "profile_dir": "",
        "status": "logged_in",
        "shop_id": "10086",
        "shop_name": "测试店铺",
        "account_id": "20001" if platform == "taobao" else None,
        "nick": "mock_nick" if platform == "taobao" else None,
        "browser_source": "none",
        "profile_match": True,
        "observation": "confirmed",
        "checked_at": "2026-10-19T08:00:00",
    }


def whole_form_verification():
    return {
        "status": "complete",
        "complete": True,
        "reason": "mock",
        "required_field_coverage": {
            "known": True,
            "completePage": True,
            "scope": "whole_publish_form_required_fields",
            "rowCount": 2,
            "checkedCount": 2,
            "required": [
                {"label": "宝贝标题", "hitCount": 1, "supportedReader": True},
                {"label": "一口价", "hitCount": 1, "supportedReader": True},
            ],
            "checked": [
                {"label": "宝贝标题", "value": "测试标题"},
                {"label": "一口价", "value": "9.9"},
            ],
        },
    }


def new_task(prefix, **extra):
    with lock:
        COUNTER["n"] += 1
        task_id = f"mock-{prefix}-{COUNTER['n']}"
        TASKS[task_id] = {"polls": 0, "cancelled": False, **extra}
    return task_id


def steps_for(progress):
    steps = [
        {"name": "open_page", "label": "打开发布页", "status": "ok", "elapsed_ms": 120, "summary": "已打开"},
        {"name": "fill_form", "label": "填写表单", "status": "ok" if progress >= 70 else "running", "elapsed_ms": 340, "summary": "填写中"},
    ]
    if progress >= 100:
        steps.append({"name": "submit", "label": "提交", "status": "ok", "elapsed_ms": 80, "summary": "完成"})
    return steps


def douyin_status(task_id):
    task = TASKS.get(task_id)
    if not task:
        return 404, {"success": False, "msg": "任务不存在"}
    task["polls"] += 1
    n = task["polls"]
    mode = STATE["upload_mode"]
    if mode == "flaky":
        if n <= STATE["flaky_failures"]:
            return 500, {"success": False, "msg": "mock 状态查询失败"}
        n -= STATE["flaky_failures"]  # 恢复后从第 1 次起算进度
    base = {
        "task_id": task_id,
        "record_id": task.get("record_id") or 0,
        "record_name": "mock-record",
        "message": "上传进行中...",
        "error": None,
        "created_at": "2026-10-19T08:00:00",
        "steps": [],
    }
    if task["cancelled"]:
        base.update(status="cancelled", progress=50, message="已取消", steps=steps_for(50))
        return 200, {"success": True, "data": base}
    if mode == "stuck":
        base.update(status="running", progress=50, message="卡住的任务(mock)", steps=steps_for(50))
        return 200, {"success": True, "data": base}
    running = [15, 40, 70]
    if n <= len(running):
        progress = running[n - 1]
        base.update(status="running", progress=progress, message=f"进行中 {progress}%(mock)", steps=steps_for(progress))
        return 200, {"success": True, "data": base}
    if mode == "failed":
        base.update(status="failed", progress=100, error="mock 上传失败：页面元素未找到", message="失败", steps=steps_for(100))
    else:
        base.update(status="success", progress=100, message="mock 上传完成", steps=steps_for(100))
    return 200, {"success": True, "data": base}


def taobao_status(task_id):
    task = TASKS.get(task_id)
    if not task:
        return 404, {"success": False, "msg": "任务不存在"}
    task["polls"] += 1
    n = task["polls"]
    real = task.get("stop_before_submit") is False
    base = {
        "task_id": task_id,
        "platform": "taobao",
        "account_profile": task.get("account_profile", "mock-taobao"),
        "record_id": task.get("record_id"),
        "record_name": "mock-record",
        "progress": min(100, n * 35),
        "message": "淘宝填写中(mock)",
        "steps": steps_for(min(100, n * 35)),
        "dry_run": task.get("dry_run", False),
        "stop_before_submit": task.get("stop_before_submit", True),
        "publish_confirmed": False,
        "created_at": "2026-10-19T08:00:00",
        "started_at": "2026-10-19T08:00:01",
    }
    if task["cancelled"]:
        base.update(status="cancelled", message="已取消")
        return 200, {"success": True, "data": base}
    if STATE["upload_mode"] == "stuck":
        base.update(status="running", progress=50)
        return 200, {"success": True, "data": base}
    if n < 3:
        base.update(status="running")
        return 200, {"success": True, "data": base}
    if STATE["upload_mode"] == "failed":
        base.update(status="failed", progress=100, error="mock 淘宝失败")
        return 200, {"success": True, "data": base}
    if real:
        base.update(status="succeeded", progress=100, message="完成", result={"success": True, "stopped_before_submit": False})
    elif STATE["taobao_mode"] == "fill_unverified":
        base.update(status="succeeded", progress=100, message="完成",
                    result={"success": True, "stopped_before_submit": True, "data": {"form_verification": {"status": "partial", "complete": False}}})
    else:
        base.update(status="succeeded", progress=100, message="完成",
                    result={"success": True, "stopped_before_submit": True, "data": {"form_verification": whole_form_verification()}})
    return 200, {"success": True, "data": base}


def xhs_status(task_id):
    task = TASKS.get(task_id)
    if not task:
        return 404, {"success": False, "msg": "任务不存在"}
    task["polls"] += 1
    n = task["polls"]
    data = {"task_id": task_id, "platform": "xiaohongshu", "status": "running", "progress": min(100, n * 40),
            "message": "小红书填表中(mock)", "steps": steps_for(min(100, n * 40))}
    if task["cancelled"]:
        data.update(status="cancelled", message="已取消")
    elif n >= 3:
        data.update(status="success", progress=100, message="小红书批量填表完成(mock)")
    return 200, {"success": True, "data": data}


def mock_response(method, path, query, body):
    """返回 (status, payload)；None 表示不 mock，转发给真实后端。"""
    if method == "GET" and path == "/api/shop/current" and STATE["mock_platform"]:
        return 200, {"success": True, "msg": "mock", "data": shop_state(STATE["mock_platform"])}

    if STATE["mock_deletes"] and method == "GET" and path == "/menu_delete":
        return 200, {"success": True, "msg": "mock 删除成功"}
    if STATE["mock_deletes"] and method == "DELETE" and path == "/delete_all":
        return 200, {"success": True, "msg": "mock 已清空"}
    if STATE["mock_publish_save"] and method == "POST" and path == "/save_info" and (body or {}).get("for_publish"):
        return 200, {"success": True, "data": {"id": (body or {}).get("_id"), "update_time": "2026-10-19 09:00:00", "record_revision": "a" * 64}}
    if STATE["capture_mode"]:
        mode = STATE["capture_mode"]
        if method == "POST" and path == "/api/capture/start":
            task_id = new_task("cap")
            return 200, {"success": True, "data": {"task_id": task_id, "url": (body or {}).get("url")}}
        m = re.fullmatch(r"/api/capture/status/(.+)", path)
        if method == "GET" and m:
            task = TASKS.get(m.group(1))
            if not task:
                return 404, {"success": False, "msg": "任务不存在"}
            task["polls"] += 1
            n = task["polls"]
            if task["cancelled"]:
                return 200, {"success": True, "status": "failed", "progress": 40, "message": "已取消"}
            if mode == "stuck":
                return 200, {"success": True, "status": "running", "progress": 40, "message": "采集中(mock 卡住)", "current_step": "读取商品页"}
            if mode == "failed":
                return 200, {"success": True, "status": "failed", "progress": 60, "message": "采集失败(mock)", "action_hint": "请先在浏览器里完成登录", "can_retry": True, "user_action_required": True}
            if n < 2:
                return 200, {"success": True, "status": "running", "progress": 30, "message": "采集中(mock)", "current_step": "读取商品页"}
            return 200, {"success": True, "status": "completed", "progress": 90, "message": "采集完成(mock)", "result": {"title": "mock 商品", "sku_count": 3}}
        if method == "POST" and path == "/api/capture/import":
            return 200, {"success": True, "data": {"sku_count": 3}}
        m = re.fullmatch(r"/api/capture/cancel/(.+)", path)
        if method == "POST" and m:
            if m.group(1) in TASKS:
                TASKS[m.group(1)]["cancelled"] = True
            return 200, {"success": True, "msg": "已取消"}
    if method == "GET" and path == "/settings" and STATE["settings_fail"]:
        return 500, {"success": False, "msg": "mock 设置读取失败"}
    if method == "GET" and path == "/api/shop/freight-templates" and STATE["freight_mode"]:
        mode = STATE["freight_mode"]
        if mode == "http500":
            return 500, {"success": False, "msg": "mock 运费模板读取失败"}
        if mode == "need_publish_page":
            return 200, {"success": True, "data": {"status": "need_publish_page", "templates": [], "error": "没有读到运费模板"}}
        templates = [
            {"id": "t2", "name": "包邮", "shop_scoped": False},
            {"id": "t3", "name": "顺丰到付", "shop_scoped": True, "shop_id": "10086"},
        ]
        if mode == "ok":
            templates.insert(0, {"id": "t1", "name": "中通包邮", "shop_scoped": True, "shop_id": "10086"})
        return 200, {"success": True, "data": {"status": "ok", "shop_name": "测试店铺", "templates": templates, "error": None}}
    if method == "POST" and path == "/api/ai/models":
        return 200, {"success": True, "data": {"models": ["mock-model-a", "mock-model-b"]}}
    if method == "POST" and path == "/api/ai/test":
        key = next(iter(body or {}), "deepseek")
        return 200, {"success": True, "data": {key: {"success": True}}}

    if method == "POST" and path in ("/api/upload/start", "/api/upload/start-all"):
        mode = STATE["start_mode"]
        if mode == "reject":
            return 200, {"success": False, "msg": "mock 后端拒绝启动：测试原因"}
        if mode == "http500":
            return 500, {"success": False, "msg": "mock 内部错误"}
        if mode == "no_task_id":
            return 200, {"success": True, "data": {}}
        task_id = new_task("douyin", record_id=(body or {}).get("record_id"), account_profile=(body or {}).get("account_profile"))
        return 200, {"success": True, "data": {"task_id": task_id}}
    m = re.fullmatch(r"/api/upload/status/(.+)", path)
    if method == "GET" and m:
        return douyin_status(m.group(1))
    m = re.fullmatch(r"/api/upload/cancel/(.+)", path)
    if method == "POST" and m:
        if m.group(1) in TASKS:
            TASKS[m.group(1)]["cancelled"] = True
        return 200, {"success": True, "msg": "已请求取消"}
    if method == "GET" and path == "/api/upload/tasks":
        return 200, {"success": True, "data": {"tasks": STATE["external_tasks"], "browser_status": {"current_task": None, "has_browser": False, "is_running": False}}}

    if method == "POST" and path in ("/api/taobao/publish/start", "/api/taobao/publish/start-all"):
        mode = STATE["start_mode"]
        if mode == "reject":
            return 400, {"success": False, "msg": "mock 淘宝后端拒绝：测试原因"}
        if mode == "http500":
            # 不带 success:false：前端据此判断「结果未知」（可能已创建任务），而不是「被明确拒绝」
            return 500, {"msg": "mock 淘宝内部错误"}
        task_id = new_task("taobao", record_id=(body or {}).get("record_id"), account_profile=(body or {}).get("account_profile"),
                           stop_before_submit=(body or {}).get("stop_before_submit", True), dry_run=(body or {}).get("dry_run", True))
        return 200, {"success": True, "data": {"task_id": task_id, "dry_run": (body or {}).get("dry_run", True),
                                                  "stop_before_submit": (body or {}).get("stop_before_submit", True), "count": 1}}
    m = re.fullmatch(r"/api/taobao/publish/status/(.+)", path)
    if method == "GET" and m:
        return taobao_status(m.group(1))
    m = re.fullmatch(r"/api/taobao/publish/cancel/(.+)", path)
    if method == "POST" and m:
        if m.group(1) in TASKS:
            TASKS[m.group(1)]["cancelled"] = True
        return 200, {"success": True, "data": {"task_id": m.group(1), "status": "cancelling"}}
    if method == "GET" and path == "/api/taobao/publish/tasks":
        return 200, {"success": True, "data": {"count": len(STATE["taobao_external"]), "tasks": STATE["taobao_external"]}}

    if method == "POST" and path == "/api/xhs/fill-only":
        if STATE["xhs_ok"]:
            return 200, {"success": True, "data": {"ok": True, "blocked": [], "steps": []}}
        return 200, {"success": True, "data": {"ok": False, "blocked": ["图片上传未成功"],
                     "steps": [{"name": "upload_images", "ok": False, "reason": "超过 5M"}],
                     "resolved_images": [{"path": "C:/x/1.jpg", "ok": False, "problem": "文件不存在"}],
                     "gaps": {"unfilled": ["商品类目"]}}}
    if method == "POST" and path == "/api/xhs/fill-batch":
        task_id = new_task("xhs")
        return 200, {"success": True, "data": {"task_id": task_id, "count": 2}}
    m = re.fullmatch(r"/api/xhs/fill-status/(.+)", path)
    if method == "GET" and m:
        return xhs_status(m.group(1))
    m = re.fullmatch(r"/api/xhs/fill-cancel/(.+)", path)
    if method == "POST" and m:
        if m.group(1) in TASKS:
            TASKS[m.group(1)]["cancelled"] = True
        return 200, {"success": True, "data": {"task_id": m.group(1)}}
    return None


HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, status, payload, content_type="application/json; charset=utf-8", extra=None):
        data = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for k, v in {**CORS, **(extra or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _handle(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        raw = self._body()
        method = self.command

        if path.startswith("/__ctl/"):
            return self._ctl(method, path, query, raw)

        if method == "OPTIONS":
            # 预检统一由代理应答（前端到代理的所有请求同源规则一致）
            return self._send(204, b"", extra={"Access-Control-Max-Age": "600"})

        body = None
        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                body = {"__raw__": raw.decode("utf-8", errors="replace")}

        entry = {"method": method, "path": path, "query": {k: v for k, v in query.items() if k != "t"}, "body": body, "mock": False}
        with lock:
            LOG.append(entry)  # 按到达顺序记录（而不是按后端处理完的顺序）
        mocked = mock_response(method, path, query, body)
        entry["mock"] = mocked is not None
        if mocked is not None:
            status, payload = mocked
            entry["status"] = status
            return self._send(status, payload)

        try:
            conn = http.client.HTTPConnection(*UPSTREAM, timeout=120)
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
            conn.request(method, self.path, body=raw or None, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            entry["status"] = resp.status
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() in HOP or k.lower().startswith("access-control-"):
                    continue
                self.send_header(k, v)
            for k, v in CORS.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:  # 上游不可用时如实返回 502，让前端走它自己的失败分支
            entry["status"] = 502
            self._send(502, {"success": False, "msg": f"proxy upstream error: {exc}"})

    def _ctl(self, method, path, query, raw):
        if method == "OPTIONS":
            return self._send(204, b"")
        if path == "/__ctl/harness.js":
            with open(os.path.join(HERE, "harness.js"), "rb") as fp:
                return self._send(200, fp.read(), "application/javascript; charset=utf-8")
        if path.startswith("/__ctl/script/"):
            name = re.sub(r"[^A-Za-z0-9_.\-]", "_", path.rsplit("/", 1)[1])
            with open(os.path.join(HERE, "scenarios", name), "rb") as fp:
                return self._send(200, fp.read(), "application/javascript; charset=utf-8")
        if path == "/__ctl/capture":
            name = re.sub(r"[^A-Za-z0-9_.\-]", "_", (query.get("name") or ["x"])[0])
            with open(os.path.join(CAP, name), "wb") as fp:
                fp.write(raw)
            return self._send(200, {"ok": True, "bytes": len(raw), "name": name})
        if path == "/__ctl/reset":
            with lock:
                LOG.clear()
            return self._send(200, {"ok": True})
        if path == "/__ctl/log":
            with lock:
                return self._send(200, {"count": len(LOG), "log": list(LOG)})
        if path == "/__ctl/save-log":
            name = re.sub(r"[^A-Za-z0-9_.\-]", "_", (query.get("name") or ["log"])[0])
            with lock:
                text = "\n".join(json.dumps(e, ensure_ascii=False, sort_keys=True) for e in LOG)
            with open(os.path.join(CAP, name), "w", encoding="utf-8") as fp:
                fp.write(text)
            return self._send(200, {"ok": True, "count": len(LOG), "name": name})
        if path == "/__ctl/mock":
            patch = json.loads(raw.decode("utf-8") or "{}")
            with lock:
                reg = patch.pop("register_task", None)
                for key, value in patch.items():
                    STATE[key] = value
                if patch.get("reset_tasks"):
                    TASKS.clear()
                if reg:  # 登记一个外部任务，使 /status/<id> 能返回它的进度
                    TASKS[reg["id"]] = {"polls": 0, "cancelled": False, **{k: v for k, v in reg.items() if k != "id"}}
            return self._send(200, {"ok": True, "state": {k: v for k, v in STATE.items()}})
        if path == "/__ctl/state":
            return self._send(200, {"state": STATE, "tasks": TASKS})
        return self._send(404, {"error": "unknown ctl"})

    do_GET = do_POST = do_PUT = do_DELETE = do_OPTIONS = _handle


if __name__ == "__main__":
    # HTTPServer 默认开着 SO_REUSEADDR；在 Windows 上它允许「绑到别的进程正在监听的端口」，
    # 等于能劫持别人的连接。验证代理绝不能这样：端口被占就直接失败。
    ThreadingHTTPServer.allow_reuse_address = False
    try:
        server = ThreadingHTTPServer(LISTEN, Handler)
    except OSError as exc:
        sys.exit(f"代理无法监听 {LISTEN}（端口被占用？）：{exc}")
    server.daemon_threads = True
    print(f"proxy listening on {LISTEN}, upstream {UPSTREAM}", flush=True)
    server.serve_forever()

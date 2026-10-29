# -*- coding: utf-8 -*-
"""小红书批量填表（src/sidecar/xhs_batch_service.py + xhs_batch_routes.py）回归。

不连浏览器：执行器（``xhs_routes.default_runner``）、取图函数、端口扫描用的 ``urlopen`` 全部换成假件；
后台线程换成同步执行，所以每条用例的结果是确定的。重点守住：
1. 红线：这组接口只有「启动 / 查询 / 取消」，没有任何提交 / 保存草稿 / 上架类路由；上传默认不授权；
2. 账户门禁：当前账户不是小红书千帆，什么都不会启动；
3. worker 的逐条结果、成功 / 失败判定、取消只在两个商品之间生效；
4. 从 Record 取图片 / 类目、扫描账户浏览器端口的规则；
5. 已结束任务的清理（见 test_xhs_task_prune.py）。
"""

from __future__ import annotations

import json
import sys
import types
import urllib.request
from pathlib import Path
from urllib.error import URLError

import pytest
from flask import Flask, jsonify

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from sidecar_test_support import make_record_model  # noqa: E402
from src.sidecar import xhs_batch_routes, xhs_batch_service, xhs_routes  # noqa: E402
from src.sidecar.xhs_batch_service import XhsBatchService  # noqa: E402

XHS_URL = "https://ark.xiaohongshu.com/app-item/good/create"


class SyncThread:
    """把 ``threading.Thread`` 换成同步执行：start() 返回时 worker 已经跑完。"""

    def __init__(self, target, args=(), daemon=None):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


class Env:
    pass


@pytest.fixture()
def env(tmp_path, monkeypatch):
    Record, database = make_record_model(tmp_path / "records.db")
    e = Env()
    e.Record = Record
    e.pics = {}                 # (record_id, key) -> 图片列表，或要抛的异常
    e.runner_calls = []
    e.runner_reply = lambda payload: {"ok": True}
    e.gate_calls = []
    e.denied = None             # 非 None 时，账户门禁拒绝

    def get_pic_list(record, key):
        value = e.pics.get((record.id, key), [])
        if isinstance(value, Exception):
            raise value
        return value

    def require_publish_platform(expected):
        e.gate_calls.append(expected)
        return e.denied

    def fake_runner(payload):
        e.runner_calls.append(json.loads(json.dumps(payload)))
        return e.runner_reply(payload)

    monkeypatch.setattr(xhs_routes, "default_runner", fake_runner)
    monkeypatch.setattr(xhs_batch_routes, "threading", types.SimpleNamespace(Thread=SyncThread))

    e.shop_session = types.SimpleNamespace(XHS_DOMAINS=("xiaohongshu.com",))
    e.service = XhsBatchService(record_model=Record, get_pic_list=get_pic_list, shop_session=e.shop_session,
                                host="127.0.0.1", port_start=9500, port_end=9502)
    app = Flask(__name__, static_folder=None)
    app.register_blueprint(xhs_batch_routes.create_xhs_batch_blueprint(
        record_model=Record, service=e.service,
        accounts=types.SimpleNamespace(require_publish_platform=require_publish_platform)))
    e.client = app.test_client()
    e.app = app
    e.tmp = tmp_path
    yield e
    database.close()


def _add(env, record_id, *, title="", name="商品", status=0, clazz="2", content="[]"):
    return env.Record.create(id=record_id, name=name, title=title, status=status, clazz=clazz, content=content)


def _start(env, **payload):
    return env.client.post("/api/xhs/fill-batch", json=payload).get_json()


def _task(env, task_id):
    return env.client.get("/api/xhs/fill-status/%s" % task_id).get_json()["data"]


# ---------------------------------------------------------------- 红线与门禁

def test_blueprint_has_only_start_status_and_cancel_routes(env):
    routes = {(m, r.rule) for r in env.app.url_map.iter_rules() for m in r.methods if m not in ("HEAD", "OPTIONS")}
    assert routes == {("POST", "/api/xhs/fill-batch"), ("GET", "/api/xhs/fill-status/<task_id>"),
                      ("POST", "/api/xhs/fill-cancel/<task_id>")}
    assert not any(word in rule for _, rule in routes for word in ("submit", "publish", "draft", "save"))


def test_account_gate_denial_is_returned_untouched_and_nothing_starts(env):
    _add(env, 1, title="T")
    with env.app.test_request_context():
        env.denied = (jsonify(success=False, code="ACCOUNT_PLATFORM_MISMATCH", msg="不是小红书账户"), 409)
    response = env.client.post("/api/xhs/fill-batch", json={})
    assert response.status_code == 409 and response.get_json()["code"] == "ACCOUNT_PLATFORM_MISMATCH"
    assert env.gate_calls == ["xiaohongshu"]
    assert env.service.tasks == {} and env.runner_calls == []


def test_body_must_be_a_json_object(env):
    _add(env, 1, title="T")
    response = env.client.post("/api/xhs/fill-batch", json=[1])
    assert response.status_code == 400 and response.get_json()["msg"] == "请求必须是 JSON 对象"


def test_no_pending_products_means_nothing_to_start(env):
    _add(env, 1, title="T", status=1)
    body = _start(env)
    assert body["success"] is False and "没有待上传的商品" in body["msg"]
    assert env.service.tasks == {}


def test_upload_is_not_authorized_unless_the_caller_says_so(env):
    _add(env, 1, title="T")
    _start(env, port=9555)
    assert env.runner_calls[0]["allow_upload"] is False
    assert env.runner_calls[0]["allow_advance"] is True
    assert env.runner_calls[0]["service_values"] == XhsBatchService.DEFAULT_SERVICE_VALUES
    _start(env, port=9555, allow_upload=True, allow_advance=False, service_values={"物流模板": "自定义"})
    assert env.runner_calls[1]["allow_upload"] is True and env.runner_calls[1]["allow_advance"] is False
    assert env.runner_calls[1]["service_values"] == {"物流模板": "自定义"}


# ---------------------------------------------------------------- worker

def test_batch_runs_every_pending_product_and_reports_each_one(env):
    _add(env, 1, title="好商品", name="A", clazz="2")
    _add(env, 2, title="", name="只有名字", clazz="长筒袜")
    _add(env, 3, title="被拦下", name="C")
    _add(env, 4, title="", name="")                      # 标题和名字都空：不调用执行器
    _add(env, 5, title="已上传", name="E", status=1)     # 不是待上传
    env.runner_reply = lambda p: ({"ok": False, "blocked": ["缺少主图", "类目未选"]} if p["title"] == "被拦下"
                                  else {"ok": True})
    started = _start(env, port=9555)
    assert started["success"] is True and started["data"]["count"] == 4
    task = _task(env, started["data"]["task_id"])

    assert [c["title"] for c in env.runner_calls] == ["好商品", "只有名字", "被拦下"]
    assert [c["category"] for c in env.runner_calls] == ["中筒袜", "长筒袜", "中筒袜"]
    assert all(c["port"] == 9555 for c in env.runner_calls)
    result = task["result"]
    assert (result["succeeded"], result["failed"], result["total"]) == (2, 2, 4)
    by_id = {item["record_id"]: item for item in result["results"]}
    assert by_id[1]["success"] is True and by_id[1]["error"] == ""
    assert by_id[3] == {"record_id": 3, "name": "C", "success": False, "error": "缺少主图; 类目未选"}
    assert by_id[4]["error"] == "标题为空"
    assert task["status"] == "succeeded" and task["progress"] == 100                  # 有成功的就算结束成功
    assert task["message"] == "批量填表结束：2 成功 / 2 失败 / 共 4"


def test_executor_exception_is_recorded_per_product_and_the_batch_continues(env):
    _add(env, 1, title="崩溃")
    _add(env, 2, title="正常")

    def reply(payload):
        if payload["title"] == "崩溃":
            raise RuntimeError("模拟填表异常")
        return {"ok": True}

    env.runner_reply = reply
    task = _task(env, _start(env, port=1)["data"]["task_id"])
    errors = {item["record_id"]: item["error"] for item in task["result"]["results"]}
    assert errors == {1: "RuntimeError: 模拟填表异常", 2: ""}
    assert task["result"]["success"] is False and task["status"] == "succeeded"


def test_batch_is_failed_when_nothing_succeeded(env):
    _add(env, 1, title="A")
    env.runner_reply = lambda p: {"ok": False}
    task = _task(env, _start(env, port=1)["data"]["task_id"])
    assert task["status"] == "failed" and task["result"]["succeeded"] == 0


def test_worker_without_pending_products_marks_the_task_failed(env):
    env.service.tasks["t1"] = {"task_id": "t1", "status": "pending", "message": "", "progress": 0}
    env.service.run_fill_batch_task("t1", {})
    task = env.service.tasks["t1"]
    assert task["status"] == "failed" and task["message"] == "没有待上传的商品" and task["finished_at"]
    env.service.run_fill_batch_task("unknown", {})                                   # 任务不存在：静默返回


def test_cancel_takes_effect_between_two_products(env):
    _add(env, 1, title="第一个")
    _add(env, 2, title="第二个")
    _add(env, 3, title="第三个")

    def reply(payload):
        # 第一个商品正在填的时候用户点了取消（取消路由做的就是设这个标志）：当前这个填完，后面的不再开始
        with env.service.lock:
            for task in env.service.tasks.values():
                task["cancelled"] = True
        return {"ok": True}

    env.runner_reply = reply
    body = _start(env, port=1)
    task = _task(env, body["data"]["task_id"])
    assert [c["title"] for c in env.runner_calls] == ["第一个"]
    assert task["status"] == "cancelled" and task["message"] == "批量填表已取消（1/3）"
    assert task["result"] is None                                                       # 取消的批次没有汇总结果


def test_status_and_cancel_report_unknown_and_finished_tasks(env):
    assert env.client.get("/api/xhs/fill-status/nope").status_code == 404
    assert env.client.post("/api/xhs/fill-cancel/nope", json={}).status_code == 404
    env.service.tasks["done"] = {"task_id": "done", "status": "succeeded"}
    body = env.client.post("/api/xhs/fill-cancel/done", json={}).get_json()
    assert body["msg"] == "任务已结束，无需取消" and body["data"] == {"task_id": "done", "status": "succeeded"}
    env.service.tasks["live"] = {"task_id": "live", "status": "running", "cancelled": False}
    assert env.client.post("/api/xhs/fill-cancel/live", json={}).get_json()["msg"] == "已请求取消"
    assert env.service.tasks["live"]["cancelled"] is True


def test_starting_a_batch_prunes_old_finished_tasks_first(env):
    _add(env, 1, title="A")
    for index in range(xhs_batch_service.XHS_TASK_KEEP_FINISHED + 5):
        stamp = "2099-01-01T00:%02d:00" % index
        env.service.tasks["old%02d" % index] = {"task_id": "old%02d" % index, "status": "succeeded",
                                                "created_at": stamp, "finished_at": stamp}
    env.service.tasks["live"] = {"task_id": "live", "status": "running"}
    _start(env, port=1)
    tasks = env.service.tasks
    # 启动时先清理：25 条已结束的只留最新的 KEEP 条（最旧的 5 条被丢），运行中的不动；新任务随后加进来
    assert not any("old%02d" % i in tasks for i in range(5))
    assert "old05" in tasks and "old24" in tasks and "live" in tasks
    assert len([t for t in tasks.values() if t["status"] in ("succeeded", "failed", "cancelled")]) ==         xhs_batch_service.XHS_TASK_KEEP_FINISHED + 1


# ---------------------------------------------------------------- 取图 / 类目 / 端口

@pytest.mark.parametrize("clazz,expected", [("2", "中筒袜"), ("0", "船袜"), ("袜套", "袜套"), (" 3 ", "长筒袜"),
                                            ("x", ""), ("", ""), (None, "")])
def test_category_comes_from_clazz_and_is_never_guessed(env, clazz, expected):
    record = types.SimpleNamespace(clazz=clazz)
    assert env.service.category_from_record(record) == expected


def test_images_come_from_the_product_dirs_and_sku_paths_but_only_existing_files(env):
    main, detail, sku = (env.tmp / n for n in ("main.jpg", "detail.jpg", "sku.jpg"))
    for path in (main, detail, sku):
        path.write_bytes(b"x")
    content = json.dumps([{"path": str(sku)}, {"path": str(env.tmp / "missing.jpg")}, "junk", {"path": ""}])
    record = _add(env, 1, title="A", content=content)
    env.pics[(1, "800")] = [str(main), str(env.tmp / "gone.jpg")]
    env.pics[(1, "750")] = [str(detail)]
    assert env.service.images_from_record(record) == [str(main), str(detail), str(sku)]
    env.pics[(1, "800")] = RuntimeError("目录读取失败")                                # 取图出错：跳过这一路，不影响别的
    assert env.service.images_from_record(record) == [str(detail), str(sku)]
    broken = _add(env, 2, title="B", content="not json")
    assert env.service.images_from_record(broken) == []


class _Resp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_debug_port_prefers_an_explicit_port_then_scans_the_account_port_range(env, monkeypatch):
    seen = []

    def fake_urlopen(url, timeout=None):
        seen.append(url)
        if ":9500/" in url:
            return _Resp(b"not json")                                                      # 解析失败：继续
        if ":9501/" in url:
            return _Resp(json.dumps([{"type": "worker", "url": XHS_URL}]).encode())       # 不是页面：不算
        return _Resp(json.dumps([{"type": "page", "url": "https://example.com/"},
                                 {"type": "page", "url": XHS_URL}]).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert env.service.debug_port(9777) == 9777 and seen == []                           # 显式端口不扫描
    assert env.service.debug_port("9778") == 9778
    assert env.service.debug_port("abc") == 9502                                         # 非法端口回落到扫描
    assert seen == ["http://127.0.0.1:%d/json/list" % p for p in (9500, 9501, 9502)]
    assert env.service.debug_port() == 9502


def test_debug_port_is_none_when_no_xiaohongshu_page_is_found(env, monkeypatch):
    def refuse(url, timeout=None):
        raise URLError("refused")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    assert env.service.debug_port() is None

# -*- coding: utf-8 -*-
"""给隔离后端准备一张水洗标图片并写入设置（直连 5002，不经过代理，不进请求日志）。"""
import json
import os
import urllib.request

BASE = "http://127.0.0.1:5002"
HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get("AB_WORK") or os.path.join(HERE, ".work")


def call(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))


src = os.path.join(WORK, "fixtures", "ID-1000001 测试船袜", "SKU", "01(黑色).jpg")
imp = call("POST", "/settings/automation/wash-label/import", {"source_path": src})
assert imp.get("success"), imp
stored = imp["data"]["stored_path"]
cur = call("GET", "/settings")["data"]["settings"]
cfg = cur["automation_config"]
cfg["wash_label_tag_image_path"] = stored
res = call("POST", "/settings", {"automation_config": cfg})
assert res.get("success"), res
check = call("GET", "/settings")["data"]["settings"]["automation_config"]["wash_label_tag_image_path"]
print("wash label stored:", os.path.basename(check or ""))

# -*- coding: utf-8 -*-
"""小红书千帆：Sidecar HTTP 适配（Flask Blueprint）。

边界（与 `taobao-publisher` 同级红线）：
- **只暴露"体检"与"填满"两类能力**：`GET /api/xhs/status`（只读）、
  `POST /api/xhs/fill-only`（填表；上传需显式 `allow_upload=true`）；
- **不提供任何提交 / 保存草稿 / 上架类路由**——提交上架必须单独授权后另行实现，
  这里连入口都不放（并有回归测试守着）；
- 业务实现不写在本模块：通过 `runner` / `status_probe` 注入，
  默认实现延迟导入 `xiaohongshu-publisher/xiaohongshu_publish`，
  导入失败只影响这两条路由，不影响 sidecar 启动（与 `whitebg_routes` 同策略）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

from flask import Blueprint, jsonify, request

from .responses import api_error, api_ok

REPO_ROOT = Path(__file__).resolve().parents[2]
XHS_PACKAGE_ROOT = REPO_ROOT / "xiaohongshu-publisher"


def _load_xhs_modules():
    """延迟导入小红书实现包；返回 `(flow, browser)`。"""
    if str(XHS_PACKAGE_ROOT) not in sys.path:
        sys.path.insert(0, str(XHS_PACKAGE_ROOT))
    from xiaohongshu_publish import browser as xhs_browser  # noqa: PLC0415
    from xiaohongshu_publish import flow as xhs_flow  # noqa: PLC0415

    return xhs_flow, xhs_browser


def default_status_probe(port: int = 9336) -> dict:
    """只读体检：能否连上调试浏览器、当前页在不在创建页、标签页可见性、**还差哪些必填项**。

    `gaps` 读的是平台自己的判据（`required-icon` 标记 + 三套完成度计数）；
    读不到只记 error，不影响其余体检结果（一项读不到不该让整体体检失败）。
    """
    flow, xhs_browser = _load_xhs_modules()
    browser, page, client, _session = xhs_browser.connect(port)
    try:
        state = page.state()
        result = {"port": port, "url": state.get("url", ""),
                  "visibility": page.visibility(),
                  "title_counter": state.get("title_counter", ""),
                  "category_lines": state.get("category_lines", []),
                  "errors": state.get("errors", []),
                  "drawer": page.drawer_state()}
        try:
            result["gaps"] = flow.required_gaps(page)
        except Exception as error:  # noqa: BLE001 - 判据是附加信息
            result["gaps"] = {"error": str(error)}
        return result
    finally:
        client.close()
        browser.close()


def default_runner(payload: dict) -> dict:
    """默认执行器：连真机跑 `run_fill_only`。"""
    flow, xhs_browser = _load_xhs_modules()
    port = int(payload.get("port") or 9336)
    browser, page, client, session_id = xhs_browser.connect(port)
    try:
        plan = flow.FillPlan(title=payload.get("title") or "",
                             images=list(payload.get("images") or []),
                             allow_upload=bool(payload.get("allow_upload")))
        return flow.run_fill_only(page, plan,
                                  upload_fn=xhs_browser.make_upload_fn(browser, client,
                                                                       session_id, page))
    finally:
        client.close()
        browser.close()


def create_xhs_blueprint(*, runner: Callable[[dict], dict] | None = None,
                         status_probe: Callable[[], dict] | None = None) -> Blueprint:
    """构造蓝图。`runner` / `status_probe` 可注入，便于离线回归。"""
    blueprint = Blueprint("xhs_routes", __name__)
    run_fill = runner or default_runner
    probe = status_probe or default_status_probe

    @blueprint.get("/api/xhs/status")
    def xhs_status():
        try:
            return jsonify(api_ok("ok", probe()))
        except Exception as error:  # noqa: BLE001 - 浏览器不可达属可预期失败
            return jsonify(api_error("小红书调试浏览器不可达：{}".format(error))), 503

    @blueprint.post("/api/xhs/fill-only")
    def xhs_fill_only():
        payload: dict[str, Any] = request.get_json(silent=True) or {}
        title = (payload.get("title") or "").strip()
        if not title:
            return jsonify(api_error("缺少 title")), 400
        if payload.get("allow_submit"):
            # 明确拒绝：本蓝图没有提交能力，收到该字段说明调用方理解错了接口
            return jsonify(api_error("本接口不支持提交上架（allow_submit 无效）")), 400
        # 安全默认值在 HTTP 边界就定死：不传 allow_upload 一律视为未授权
        payload.setdefault("allow_upload", False)
        payload["images"] = list(payload.get("images") or [])
        try:
            report = run_fill(payload)
        except Exception as error:  # noqa: BLE001 - 执行失败按可预期错误返回
            return jsonify(api_error("fill-only 执行失败：{}".format(error))), 500
        return jsonify(api_ok("fill-only 完成", report))

    return blueprint

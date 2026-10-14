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


def _xhs_package_candidates() -> list:
    """列出 `xiaohongshu-publisher` 可能所在的目录（冻结包与源码仓都覆盖）。

    PyInstaller onefile 下 ``__file__`` 落在 ``_MEIPASS/src/sidecar/``，
    ``parents[2]`` 才是解压根；但 ``resolve()`` 在个别环境下会指到别处。
    所以按「最可能 → 兜底」列出候选，找到含 ``xiaohongshu_publish`` 的那个就用。
    """
    candidates = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass) / "xiaohongshu-publisher")
        candidates.append(Path(meipass))
    candidates.append(XHS_PACKAGE_ROOT)
    candidates.append(REPO_ROOT / "xiaohongshu-publisher")
    # 源码仓里本文件在 src/sidecar/，再上两级就是仓库根
    candidates.append(Path(__file__).resolve().parents[2] / "xiaohongshu-publisher")
    return candidates


def _load_xhs_modules():
    """延迟导入小红书实现包；返回 `(flow, browser)`。"""
    try:
        from xiaohongshu_publish import browser as xhs_browser  # noqa: PLC0415
        from xiaohongshu_publish import flow as xhs_flow  # noqa: PLC0415
        return xhs_flow, xhs_browser
    except ImportError:
        pass
    tried = []
    for root in _xhs_package_candidates():
        if not root or not (root / "xiaohongshu_publish").is_dir():
            continue
        path_text = str(root)
        if path_text not in sys.path:
            sys.path.insert(0, path_text)
        tried.append(path_text)
        try:
            from xiaohongshu_publish import browser as xhs_browser  # noqa: PLC0415
            from xiaohongshu_publish import flow as xhs_flow  # noqa: PLC0415
            return xhs_flow, xhs_browser
        except ImportError:
            continue
    raise ImportError(
        "XHSLOADER-V2 找不到 xiaohongshu_publish（已试路径：{}）".format(tried or "无可用候选"))


def _default_port() -> int:
    """小红书调试端口只保留**一处定义**：``src.shop_session.XHS_CDP_PORT`` ✓。

    以前这个 9336 同时写在后端常量、本模块与启动命令里 ✗，改端口时极易漏掉一处 ✓。
    导入失败也不要让接口挂掉（退化成同一个字面值，并让调用方仍能显式指定 port ✓）。
    """
    try:
        from ..shop_session import XHS_CDP_PORT  # type: ignore[import-not-found]

        return int(XHS_CDP_PORT)
    except Exception:  # noqa: BLE001 - 常量拿不到不该让接口不可用
        return 9336


def default_status_probe(port: int | None = None) -> dict:
    """只读体检：能否连上调试浏览器、当前页在不在创建页、标签页可见性、**还差哪些必填项**。

    `gaps` 读的是平台自己的判据（`required-icon` 标记 + 三套完成度计数）；
    读不到只记 error，不影响其余体检结果（一项读不到不该让整体体检失败）。
    """
    flow, xhs_browser = _load_xhs_modules()
    port = int(port or _default_port())
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
                             allow_upload=bool(payload.get("allow_upload")),
                             allow_advance=bool(payload.get("allow_advance")),
                             category=(payload.get("category") or "").strip(),
                             service_values=dict(payload.get("service_values") or {}))
        return flow.run_fill_only(page, plan,
                                  upload_fn=xhs_browser.make_upload_fn(browser, client,
                                                                       session_id, page))
    finally:
        client.close()
        browser.close()


def create_xhs_blueprint(*, runner: Callable[[dict], dict] | None = None,
                         status_probe: Callable[[], dict] | None = None,
                         account_guard: Callable[[], Any] | None = None) -> Blueprint:
    """构造蓝图。`runner` / `status_probe` / `account_guard` 可注入，便于离线回归。

    `account_guard()` 返回 `None` 表示放行；返回 `(response, status)` 则原样拒绝。
    生产环境由 `app.py` 注入 `_require_publish_platform('xiaohongshu')`，
    保证**按账户区分发布路线**——当前账户不是小红书千帆就进不了本路线。
    """
    blueprint = Blueprint("xhs_routes", __name__)
    run_fill = runner or default_runner
    probe = status_probe or default_status_probe

    @blueprint.get("/api/xhs/status")
    def xhs_status():
        if account_guard is not None:
            denied = account_guard()
            if denied is not None:
                return denied
        try:
            return jsonify(api_ok("ok", probe()))
        except Exception as error:  # noqa: BLE001 - 浏览器不可达属可预期失败
            return jsonify(api_error("小红书调试浏览器不可达：{}".format(error))), 503

    @blueprint.post("/api/xhs/fill-only")
    def xhs_fill_only():
        if account_guard is not None:
            denied = account_guard()
            if denied is not None:
                return denied
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
        payload["category"] = (payload.get("category") or "").strip()
        payload["service_values"] = dict(payload.get("service_values") or {})
        try:
            report = run_fill(payload)
        except Exception as error:  # noqa: BLE001 - 执行失败按可预期错误返回
            return jsonify(api_error("fill-only 执行失败：{}".format(error))), 500
        return jsonify(api_ok("fill-only 完成", report))

    return blueprint

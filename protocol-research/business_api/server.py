# -*- coding: utf-8 -*-
"""business_api 独立服务入口。

运行（在 protocol-research 目录下）：
    python -m business_api.server

环境变量：
    DOUYIN_CHROME_ADDRESS  已开启调试端口的 Chrome 地址，默认 127.0.0.1:9222
    BUSINESS_API_PORT      服务端口，默认 8800
"""
from __future__ import annotations

import json
import os

from flask import Flask, current_app, jsonify, redirect, request, send_from_directory

from .agent.tools import TOOL_BY_NAME, list_tools_mcp
from .core import ErrorCode, err_envelope
from .domains import IMPLEMENTED_DOMAINS, all_blueprints, domain_catalog

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")


def create_app() -> Flask:
    app = Flask(__name__)
    # 中文 JSON 直出，避免 \uXXXX 转义影响可读性
    try:
        app.json.ensure_ascii = False  # Flask >= 2.3
    except Exception:
        app.config["JSON_AS_ASCII"] = False  # 兼容旧版本

    @app.after_request
    def _cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
        return resp

    @app.get("/")
    def root():
        # 人访问根路径直达 2.5D 驾驶舱；机器用 /health、/catalog、/api/*、/mcp/* 显式路径
        return redirect("/console", code=302)

    @app.get("/console")
    def console_index():
        """2.5D 经营驾驶舱前端入口。"""
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/console/<path:filename>")
    def console_assets(filename):
        return send_from_directory(WEB_DIR, filename)

    @app.get("/health")
    def health():
        domains = list(IMPLEMENTED_DOMAINS) + [c["domain"] for c in domain_catalog()]
        return jsonify({"ok": True, "service": "business_api", "domains": domains})

    @app.get("/catalog")
    def catalog():
        return jsonify(
            {
                "implemented_domains": list(IMPLEMENTED_DOMAINS),
                "note": "implemented_domains 为已联调真实域；skeleton 为契约骨架，待联调填充。",
                "skeleton": domain_catalog(),
            }
        )

    @app.get("/mcp/tools")
    def mcp_tools():
        """导出全部业务接口为 Agent 可发现的工具 schema。"""
        return jsonify({"tools": list_tools_mcp()})

    @app.post("/mcp/call")
    def mcp_call():
        """统一工具调用入口：Agent 传 {name, arguments}，内部转发到对应业务接口。"""
        data = request.get_json(silent=True) or {}
        name = data.get("name") or data.get("tool")
        args = data.get("arguments") or {}
        spec = TOOL_BY_NAME.get(name)
        if not spec:
            return (
                jsonify(err_envelope(
                    f"未知工具：{name}", ErrorCode.INVALID_PARAM,
                    hint="先调用 GET /mcp/tools 获取可用工具列表。",
                )),
                400,
            )
        client = current_app.test_client()
        if spec.http_method.upper() == "GET":
            path = spec.http_path
            for key, value in args.items():
                path = path.replace(f"<{key}>", str(value))
            resp = client.get(path)
        else:
            resp = client.post(spec.http_path, json=args)
        body = resp.get_json() or {}
        return jsonify({
            "name": name,
            "isError": not bool(body.get("ok", False)),
            "structuredContent": body,
            "content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}],
        })

    @app.errorhandler(404)
    def not_found(_e):
        return (
            jsonify(err_envelope("接口不存在。", ErrorCode.INVALID_PARAM, hint="请检查请求路径与方法。")),
            404,
        )

    for bp in all_blueprints():
        app.register_blueprint(bp)
    return app


def main() -> None:
    port = int(os.environ.get("BUSINESS_API_PORT", "8800"))
    address = os.environ.get("DOUYIN_CHROME_ADDRESS", "127.0.0.1:9222")
    app = create_app()
    print(f"[business_api] 启动于 http://127.0.0.1:{port}  (Chrome attach: {address})")
    app.run(host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()

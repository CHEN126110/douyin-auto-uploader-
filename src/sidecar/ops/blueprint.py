# -*- coding: utf-8 -*-
"""运营闭环接口（/api/ops/*）的 Blueprint 装配。"""
from flask import Blueprint

from .browser_routes import OpsBrowserPort, register_ops_browser_routes
from .ledger_routes import register_ops_ledger_routes
from .planning_routes import register_ops_planning_routes
from .sourcing_routes import register_ops_sourcing_routes


def create_ops_blueprint(*, record_model, browser: OpsBrowserPort, is_sidecar_mode,
                         get_sidecar_port, repo_root):
    """依赖都由应用入口显式传入；本包不导入 app.py。"""
    routes = Blueprint('ops', __name__)
    register_ops_planning_routes(routes, record_model=record_model)
    register_ops_ledger_routes(routes, record_model=record_model)
    register_ops_sourcing_routes(routes)
    register_ops_browser_routes(
        routes, record_model=record_model, browser=browser, is_sidecar_mode=is_sidecar_mode,
        get_sidecar_port=get_sidecar_port, repo_root=repo_root,
    )
    return routes

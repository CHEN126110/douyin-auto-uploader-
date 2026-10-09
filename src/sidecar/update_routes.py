# -*- coding: utf-8 -*-
"""仅供本机桌面更新器使用的任务状态检查。"""
from flask import Blueprint, jsonify, request


def create_update_blueprint(active_tasks):
    routes = Blueprint('desktop_update', __name__)

    @routes.get('/internal/update-readiness')
    def update_readiness():
        if request.remote_addr not in {'127.0.0.1', '::1', '::ffff:127.0.0.1'}:
            return jsonify(success=False, message='forbidden'), 403
        counts = active_tasks()
        return jsonify(success=True, data={'ready': not any(counts.values()), 'active_tasks': counts})

    return routes

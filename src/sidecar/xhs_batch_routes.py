# -*- coding: utf-8 -*-
"""小红书千帆批量填表接口（/api/xhs/fill-batch、fill-status、fill-cancel）：依次对 status=0 的商品只填表、不提交。

这些接口只做 HTTP 适配；任务字典和 worker 在 ``XhsBatchService``。和 ``xhs_routes`` 一样，这里**没有任何提交 / 保存草稿 / 上架类路由**。"""
import threading
from datetime import datetime

from flask import Blueprint, jsonify, request

from .responses import api_error, api_ok


def create_xhs_batch_blueprint(*, record_model, service, accounts):
    """``service`` 是 ``XhsBatchService``（任务字典与 worker），``accounts`` 是 ``ShopAccountGuard``
    （当前账户不是小红书千帆就不让进这条路线）。"""
    routes = Blueprint('xhs_batch', __name__)
    Record = record_model

    @routes.post('/api/xhs/fill-batch')
    def xhs_fill_batch():
        """一键批量小红书填表：依次处理全部 status=0 商品（只填不提交）。"""
        # 按账户区分发布路线：当前账户不是小红书千帆就进不了这条路线
        error = accounts.require_publish_platform('xiaohongshu')
        if error is not None:
            return error
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify(success=False, msg='请求必须是 JSON 对象'), 400

        records = list(Record.select().where(Record.status == 0).order_by(Record.id))
        if not records:
            return api_error(msg='没有待上传的商品（status=0）')

        import uuid
        task_id = str(uuid.uuid4())[:8]
        payload = {
            'allow_upload': bool(data.get('allow_upload')),
            'allow_advance': bool(data.get('allow_advance', True)),
            'service_values': dict(data.get('service_values') or service.DEFAULT_SERVICE_VALUES),
            'port': data.get('port'),
        }
        with service.lock:
            service.prune_finished_locked()  # 计划 3.3：先清理已结束的旧任务，避免无限积累 ✗
            service.tasks[task_id] = {
                'task_id': task_id,
                'platform': 'xiaohongshu',
                'record_id': None,
                'record_name': '批量({}个)'.format(len(records)),
                'status': 'pending',
                'progress': 0,
                'message': '批量填表 {} 个商品'.format(len(records)),
                'result': None,
                'created_at': datetime.now().isoformat(),
                'started_at': None,
                'finished_at': None,
                'cancelled': False,
            }
        worker = threading.Thread(target=service.run_fill_batch_task, args=(task_id, payload), daemon=True)
        worker.start()
        return api_ok(msg='已启动小红书批量填表（{}个商品）'.format(len(records)),
                      data={'task_id': task_id, 'count': len(records)})

    @routes.get('/api/xhs/fill-status/<task_id>')
    def xhs_fill_status(task_id):
        with service.lock:
            task = service.tasks.get(task_id)
            if not task:
                return jsonify(success=False, msg='任务不存在'), 404
            return api_ok('已获取小红书填表进度', data=dict(task))

    @routes.post('/api/xhs/fill-cancel/<task_id>')
    def xhs_fill_cancel(task_id):
        with service.lock:
            task = service.tasks.get(task_id)
            if not task:
                return jsonify(success=False, msg='任务不存在'), 404
            if task.get('status') in ('succeeded', 'failed', 'cancelled'):
                return api_ok('任务已结束，无需取消', data={'task_id': task_id, 'status': task['status']})
            task['cancelled'] = True
        return api_ok('已请求取消', data={'task_id': task_id})

    return routes

# -*- coding: utf-8 -*-
"""白底图 HTTP 适配：保留既有 URL、字段、消息和返回状态。"""
from __future__ import annotations

import os

from flask import Blueprint, current_app, request, send_file

from .responses import api_error, api_ok
from .whitebg_service import WhiteBgService, processing_options


def create_whitebg_blueprint(*, record_model, account_lock, service: WhiteBgService):
    routes = Blueprint('whitebg', __name__)

    def resolve_target(data):
        record_id = data.get('record_id') or data.get('recordId')
        if record_id:
            record = record_model.get_or_none(record_model.id == record_id)
            if not record:
                return None, None, '未找到该商品记录'
            if not record.path or not os.path.isdir(record.path):
                return None, None, f'商品目录不存在: {record.path}'
            return service.checked_path(record.path), record, ''
        raw = str(data.get('product_dir') or data.get('productDir') or '').strip()
        if not raw:
            return None, None, '需要提供 record_id 或 product_dir'
        target = service.checked_path(raw)
        if not os.path.isdir(target):
            return None, None, f'采集目录不存在: {target}'
        return target, None, ''

    @routes.get('/api/whitebg/status')
    def whitebg_status():
        try:
            model = str(request.args.get('matte_model') or 'birefnet-general')
            return api_ok(msg='白底图模型状态', data=service.model_status(model))
        except RuntimeError as exc:
            return api_error(str(exc), data={'ready': False, 'missing': [], 'deps_missing': True})
        except Exception as exc:
            current_app.logger.exception('读取白底图模型状态失败')
            return api_error(f'读取白底图模型状态失败: {exc}')

    @routes.post('/api/whitebg/start')
    def whitebg_start():
        # 与账户切换和手动选图共用入口传入的锁；不会在后台推理时持有它。
        with account_lock:
            data = request.get_json(silent=True) or {}
            if not isinstance(data, dict):
                return api_error('图片处理参数必须是 JSON 对象')
            try:
                target, record, err = resolve_target(data)
                if err:
                    return api_error(err)
                selected = getattr(record, 'white_bg_path', '')
                options = processing_options(data, preserve_paths=[selected] if selected else ())
            except ValueError as exc:
                return api_error(str(exc))
            try:
                status = service.model_status(options['matte_model'])
            except RuntimeError as exc:
                return api_error(str(exc), data={'deps_missing': True})
            if not status['ready']:
                return api_error(msg='白底图模型未就绪，缺：' + '、'.join(status['missing']), data=status)
            try:
                task_id = service.start(target, options, record_id=getattr(record, 'id', None),
                                        record_name=getattr(record, 'name', ''))
            except (ValueError, RuntimeError) as exc:
                return api_error(str(exc))
            return api_ok(msg='白底图生成任务已启动', data={'task_id': task_id})

    @routes.get('/api/whitebg/task/<task_id>')
    def whitebg_task(task_id):
        task = service.task(task_id)
        if task is None:
            return api_error(msg='白底图任务不存在')
        return api_ok(msg='获取白底图任务状态成功', data=task)

    @routes.get('/api/whitebg/list')
    def whitebg_list():
        try:
            target, _record, err = resolve_target({
                'record_id': request.args.get('record_id'), 'product_dir': request.args.get('product_dir'),
            })
        except ValueError as exc:
            return api_error(str(exc))
        if err:
            return api_error(err)
        try:
            return api_ok(msg='读取白底图列表成功', data=service.list_outputs(target))
        except RuntimeError as exc:
            return api_error(str(exc), data={'deps_missing': True})

    @routes.get('/api/whitebg/image')
    def whitebg_image():
        try:
            target = service.checked_path(request.args.get('path') or '')
        except ValueError:
            return '', 403
        if not os.path.isfile(target):
            return '', 404
        return send_file(target)

    return routes

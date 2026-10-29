# -*- coding: utf-8 -*-
"""抖店上传接口：/api/upload/{start,ensure-session,status,cancel,debug/injection,start-all,tasks}、/api/protocol/fxg/runtime-options，以及 GUI 兼容模式的 /start。

这些接口只做 HTTP 适配和请求校验；任务字典、互斥锁、发布浏览器会话、流水线和 worker 在 ``UploadService``，账户门禁在 ``ShopAccountGuard``，页面级操作在 ``upload_steps``。

与 app.py 旧名字的对应：
  _with_shop_account_lock / _require_publish_platform / _active_shop_account
                                  -> accounts.with_lock / require_publish_platform / active_account
  _upload_tasks / _upload_tasks_lock -> service.tasks / service.lock
  gui.page（有没有浏览器）          -> service.page_state().page
  _require_product_revision        -> 工厂参数 require_product_revision（保存商品、淘宝也在用，留在应用入口）
  _serialize_upload_task           -> 本模块的同名模块级函数（任务的 JSON 形态属于 HTTP 层）"""
import json
import os
import threading
import traceback
from datetime import datetime

from flask import Blueprint, jsonify, request

from .responses import api_error, api_ok


def _serialize_upload_task(task):
    return {
        'task_id': task.get('task_id'),
        'platform': task.get('platform', 'douyin'),
        'account_profile': task.get('account_profile'),
        'record_id': task.get('record_id'),
        'record_name': task.get('record_name'),
        'status': task.get('status'),
        'progress': task.get('progress', 0),
        'message': task.get('message', ''),
        'current_step': task.get('current_step'),
        'steps': task.get('steps') or [],
        'error': task.get('error'),
        'created_at': task.get('created_at'),
        'started_at': task.get('started_at'),
        'finished_at': task.get('finished_at'),
        'debug_report': task.get('debug_report'),
        'stop_before_submit': task.get('stop_before_submit', False),
        'final_publish_confirmed': task.get('final_publish_confirmed', False),
        'cancelled': task.get('cancelled', False),
    }


def create_upload_blueprint(*, service, accounts, record_model, require_product_revision):
    """``service`` 是 ``UploadService``（任务状态、发布浏览器会话、流水线、worker）；``accounts`` 是 ``ShopAccountGuard``（账户锁与平台门禁）；
    ``record_model`` 是商品表；``require_product_revision`` 校验界面带来的商品资料版本（保存商品、淘宝也在用，所以留在应用入口）。"""
    routes = Blueprint('upload', __name__)
    Record = record_model

    @routes.post('/api/protocol/fxg/runtime-options')
    def protocol_fxg_runtime_options():
        try:
            payload = request.get_json(silent=True) or {}
            result = service.run_fxg_runtime_options_probe(payload)
            return api_ok('运行时配置读取成功。', data=result)
        except Exception as exc:
            return api_error(str(exc))

    @routes.post('/start')
    def start():
        request_data = request.get_json(silent=True) or {}
        try:
            stop_before_submit, _ = service.resolve_stop_before_submit(request_data)
        except ValueError as e:
            return api_error(msg=str(e))

        return service.execute_upload_flow(
            record_id=request_data.get('record_id'),
            stop_before_submit=stop_before_submit,
        )

    @routes.post('/api/upload/start')
    @accounts.with_lock
    def upload_start():
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict) or data.get('platform', 'douyin') != 'douyin':
            return jsonify(success=False, msg='该接口仅用于抖音发布，请使用对应平台入口'), 400
        error = accounts.require_publish_platform('douyin', data.get('account_profile'))
        if error is not None:
            return error
        try:
            stop_before_submit, final_publish_confirmed = service.resolve_stop_before_submit(data)
        except ValueError as e:
            return api_error(msg=str(e))

        record_id = data.get('record_id')
        record_name = '全部商品'

        if record_id:
            record = Record.get_or_none(Record.id == record_id)
            if not record:
                return api_error(msg='未找到要上传的商品')
            record_name = record.name or f'商品{record_id}'
            if 'expected_record_revision' in data:
                error = require_product_revision(dict(record.__data__), data['expected_record_revision'])
                if error is not None:
                    return error
        elif 'expected_record_revision' in data:
            return jsonify(success=False, msg='商品资料版本必须绑定单件商品'), 400

        import uuid
        task_id = str(uuid.uuid4())[:8]
        task = {
            'task_id': task_id,
            'platform': 'douyin',
            'account_profile': accounts.active_account()['profile_name'],
            'record_id': record_id,
            'record_name': record_name,
            'status': 'pending',
            'progress': 0,
            'message': '任务已创建',
            'current_step': None,
            'steps': [],
            'error': None,
            'created_at': datetime.now().isoformat(),
            'started_at': None,
            'finished_at': None,
            'debug_report': None,
            'stop_before_submit': stop_before_submit,
            'final_publish_confirmed': final_publish_confirmed,
            'cancelled': False,
        }

        with service.lock:
            service.tasks[task_id] = task

        worker = threading.Thread(target=service.run_upload_task, args=(task_id, record_id, stop_before_submit), daemon=True)
        worker.start()

        return api_ok(msg='上传任务已启动', data={'task_id': task_id})

    @routes.post('/api/upload/ensure-session')
    @accounts.with_lock
    def upload_ensure_session():
        error = accounts.require_publish_platform('douyin')
        if error is not None:
            return error
        progress_events = []

        def _report_progress(progress, message):
            progress_events.append({
                'progress': int(progress),
                'message': str(message or '')
            })

        try:
            main_tab, error = service.ensure_publish_session(_report_progress)
            if error:
                return api_error(msg=error, data={
                    'browser_status': {
                        'has_browser': bool(service.page_state().page),
                        'is_logged_in': False,
                        'current_url': None,
                        'title': None,
                    },
                    'events': progress_events[-20:],
                })

            current_url = None
            current_title = None
            try:
                current_url = main_tab.url
            except Exception:
                current_url = None
            try:
                current_title = main_tab.title
            except Exception:
                current_title = None

            return api_ok(msg='上传浏览器会话已就绪', data={
                'browser_status': {
                    'has_browser': bool(service.page_state().page),
                    'is_logged_in': True,
                    'current_url': current_url,
                    'title': current_title,
                },
                'events': progress_events[-20:],
            })
        except Exception as e:
            traceback.print_exc()
            return api_error(msg=f'上传浏览器会话检查失败：{str(e)}', data={
                'browser_status': {
                    'has_browser': bool(service.page_state().page),
                    'is_logged_in': False,
                    'current_url': None,
                    'title': None,
                },
                'events': progress_events[-20:],
            })

    @routes.get('/api/upload/status/<task_id>')
    def upload_status(task_id):
        with service.lock:
            task = service.tasks.get(task_id)
            if not task:
                return api_error(msg='上传任务不存在')
            return api_ok(msg='获取任务状态成功', data=_serialize_upload_task(task))

    @routes.post('/api/upload/cancel/<task_id>')
    def upload_cancel(task_id):
        with service.lock:
            task = service.tasks.get(task_id)
            if not task:
                return api_error(msg='上传任务不存在')
            if task.get('status') in ('success', 'completed', 'failed', 'cancelled'):
                return api_error(msg=f'任务已完成，无法取消（状态：{task["status"]}）')
            task['cancelled'] = True
            task['message'] = '正在取消...'
        return api_ok(msg='已发送取消指令，任务将在当前步骤完成后停止')

    @routes.get('/api/upload/debug/injection')
    def upload_debug_injection():
        """读取协议注入调试文件"""
        import tempfile
        result_path = os.path.join(tempfile.gettempdir(), 'sku_inject_result.json')
        error_path = os.path.join(tempfile.gettempdir(), 'sku_inject_error.txt')
        data = {'result': None, 'error': None}
        try:
            if os.path.exists(result_path):
                with open(result_path, 'r', encoding='utf-8') as f:
                    data['result'] = json.load(f)
        except: pass
        try:
            if os.path.exists(error_path):
                with open(error_path, 'r', encoding='utf-8') as f:
                    data['error'] = f.read()
        except: pass
        return api_ok(msg='协议注入调试信息', data=data)

    @routes.post('/api/upload/start-all')
    @accounts.with_lock
    def upload_start_all():
        """启动全部商品上传"""
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict) or data.get('platform', 'douyin') != 'douyin':
            return jsonify(success=False, msg='该接口仅用于抖音发布，请使用对应平台入口'), 400
        error = accounts.require_publish_platform('douyin', data.get('account_profile'))
        if error is not None:
            return error
        try:
            stop_before_submit, final_publish_confirmed = service.resolve_stop_before_submit(data)
        except ValueError as e:
            return api_error(msg=str(e))

        records = list(Record.select().where(Record.status == 0).order_by(Record.id))
        if not records:
            return api_error(msg='没有待上传的商品')
        import uuid
        task_id = str(uuid.uuid4())[:8]
        task = {
            'task_id': task_id, 'record_id': None, 'record_name': f'全部({len(records)}个)',
            'platform': 'douyin',
            'account_profile': accounts.active_account()['profile_name'],
            'status': 'pending', 'progress': 0, 'message': f'批量上传{len(records)}个商品',
            'current_step': None, 'steps': [],
            'error': None, 'created_at': datetime.now().isoformat(),
            'started_at': None, 'finished_at': None, 'debug_report': None,
            'stop_before_submit': stop_before_submit,
            'final_publish_confirmed': final_publish_confirmed,
            'cancelled': False,
        }
        with service.lock:
            service.tasks[task_id] = task
        worker = threading.Thread(target=service.run_upload_task, args=(task_id, None, stop_before_submit), daemon=True)
        worker.start()
        return api_ok(msg=f'已启动批量上传({len(records)}个商品)', data={'task_id': task_id, 'count': len(records)})

    @routes.get('/api/upload/tasks')
    def upload_tasks():
        with service.lock:
            tasks = [_serialize_upload_task(item) for item in service.tasks.values()]

        tasks.sort(key=lambda x: x.get('created_at') or '', reverse=True)
        running_task = next((item for item in tasks if item.get('status') in ('pending', 'running')), None)
        return api_ok(msg='获取任务列表成功', data={
            'tasks': tasks,
            'browser_status': {
                'current_task': running_task.get('task_id') if running_task else None,
                'has_browser': bool(service.page_state().page),
                'is_running': bool(running_task),
            }
        })

    return routes

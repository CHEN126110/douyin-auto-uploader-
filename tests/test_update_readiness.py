# -*- coding: utf-8 -*-
import ast
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

from flask import Flask
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.sidecar.update_routes import create_update_blueprint
from src.sidecar.whitebg_service import WhiteBgService, processing_options


@pytest.mark.parametrize('counts,ready', [
    ({'capture': 0, 'douyin_publish': 0, 'taobao_publish': 0, 'image_processing': 0}, True),
    ({'capture': 1}, False), ({'douyin_publish': 1}, False),
    ({'taobao_publish': 1}, False), ({'image_processing': 1}, False),
])
def test_readiness_reports_active_work_without_exposing_task_data(counts, ready):
    app = Flask(__name__)
    app.register_blueprint(create_update_blueprint(lambda: counts))
    response = app.test_client().get('/internal/update-readiness')
    assert response.json == {'success': True, 'data': {'ready': ready, 'active_tasks': counts}}


def test_remote_request_cannot_read_internal_state():
    app = Flask(__name__)
    app.register_blueprint(create_update_blueprint(lambda: (_ for _ in ()).throw(AssertionError('不应读取'))))
    assert app.test_client().get('/internal/update-readiness', environ_overrides={'REMOTE_ADDR': '192.0.2.1'}).status_code == 403


def test_aggregate_covers_capture_both_platforms_and_image_jobs():
    file = ROOT / 'tauri-app/python-sidecar/app.py'
    node = next(node for node in ast.parse(file.read_text(encoding='utf-8')).body
                if isinstance(node, ast.FunctionDef) and node.name == '_active_update_tasks')
    namespace = {'_upload_tasks_lock': threading.Lock(), '_taobao_tasks_lock': threading.Lock(),
                 '_capture_lock': threading.Lock(), '_capture_running_task_id': 'test',
                 '_upload_tasks': {'a': {'status': 'running'}, 'b': {'status': 'success'}},
                 '_taobao_tasks': {'c': {'status': 'pending'}},
                 'whitebg_service': SimpleNamespace(active_task_count=lambda: 2)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(file), 'exec'), namespace)
    assert namespace['_active_update_tasks']() == {'capture': 1, 'douyin_publish': 1, 'taobao_publish': 1, 'image_processing': 2}


def test_pending_image_jobs_are_counted(tmp_path):
    jobs = WhiteBgService(lambda: tmp_path, thread_factory=lambda **kw: SimpleNamespace(start=lambda: None))
    assert jobs.active_task_count() == 0
    jobs.start(str(tmp_path / 'product'), processing_options({}))
    assert jobs.active_task_count() == 1

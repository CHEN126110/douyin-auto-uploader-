# -*- coding: utf-8 -*-
"""独立服务与真实 Flask 路由回归；使用临时目录，不加载模型或用户数据库。"""
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

from flask import Flask
from flask_cors import CORS
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.sidecar.whitebg_routes import create_whitebg_blueprint
from src.sidecar.whitebg_service import WhiteBgService, processing_options


class Outcome:
    ok = True
    message = '生成完成'
    items = ['袜子.jpg']

    def to_dict(self):
        return {'items': [{'name': '袜子.jpg'}], 'message': self.message}


class Threads:
    def __init__(self):
        self.threads = []

    def __call__(self, **kwargs):
        thread = threading.Thread(**kwargs)
        self.threads.append(thread)
        return thread

    def join(self):
        for thread in self.threads:
            thread.join(5)
            assert not thread.is_alive(), '图片处理线程未正常退出'


def fake_module(process=None):
    processors = []

    def make_processor(cfg):
        processor = SimpleNamespace(cfg=cfg)
        processors.append(processor)
        return processor

    return SimpleNamespace(WhiteBgConfig=SimpleNamespace, SockWhiteBg=make_processor,
                           process_product_dir=process or (lambda *a, **k: Outcome()),
                           model_status=lambda model: {'ready': True, 'missing': [], 'model': model},
                           processors=processors)


def test_importing_routes_never_initializes_models_database_or_browser():
    script = '''
import sys
from src.sidecar.media_routes import create_media_blueprint
from src.sidecar.whitebg_routes import create_whitebg_blueprint
from src.sidecar.whitebg_service import WhiteBgService
WhiteBgService(lambda: '.')
for name in ('src.orm', 'src.utils', 'src.whitebg', 'onnxruntime', 'rembg', 'DrissionPage'):
    assert name not in sys.modules, name
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_concurrent_jobs_serialize_inference_but_polling_remains_available(tmp_path):
    entered, release = threading.Event(), threading.Event()
    threads = Threads()
    seen = []
    module = None

    def process(directory, cfg, *, processor, progress, **options):
        if Path(directory).name == 'first':
            entered.set()
            assert release.wait(5)
        assert processor.cfg is cfg, '其他任务改写了当前模型参数'
        seen.append((Path(directory).name, cfg.canvas, options['preserve_paths']))
        progress(1, 1, '袜子.jpg')
        return Outcome()

    module = fake_module(process)
    service = WhiteBgService(lambda: tmp_path, module_loader=lambda _: module, thread_factory=threads)
    first_options = processing_options({'canvas': 1200}, preserve_paths=['自选.png'])
    first = service.start(str(tmp_path / 'first'), first_options, record_id=1)
    try:
        assert entered.wait(3)
        second = service.start(str(tmp_path / 'second'), processing_options({'canvas': 1800}), record_id=2)
        first_options['preserve_paths'].clear()
        assert service.task(first)['status'] == 'running'
        assert service.task(second)['status'] == 'pending'
        assert service.is_processing(1, str(tmp_path / 'first'))
        assert service.is_processing(2, str(tmp_path / 'second'))
        assert not service.is_processing(3, str(tmp_path / 'third'))
        assert len(module.processors) == 1
    finally:
        release.set()
        threads.join()
    assert seen == [('first', 1200, ['自选.png']), ('second', 1800, ())]
    assert service.task(first)['status'] == service.task(second)['status'] == 'success'
    assert len(module.processors) == 1, '同一模型应复用'
    assert not service.is_processing(1, str(tmp_path / 'first'))
    snapshot = service.task(first)
    snapshot['result']['items'][0]['name'] = '不应改变服务内部记录'
    assert service.task(first)['result']['items'][0]['name'] == '袜子.jpg'


def test_duplicate_pending_job_cannot_write_same_product_twice(tmp_path):
    service = WhiteBgService(lambda: tmp_path, thread_factory=lambda **kw: SimpleNamespace(start=lambda: None))
    service.start(str(tmp_path / 'product'), processing_options({}), record_id=7)
    with pytest.raises(ValueError, match='正在生成'):
        service.start(str(tmp_path / 'product'), processing_options({}), record_id=None)
    with pytest.raises(ValueError, match='正在生成'):
        service.start(str(tmp_path / 'renamed'), processing_options({}), record_id=7)


def test_worker_failure_is_visible_and_does_not_lock_next_job(tmp_path):
    threads = Threads()

    def process(directory, *args, **kwargs):
        if Path(directory).name == 'broken':
            raise OSError('模拟读取图片失败')
        return Outcome()

    module = fake_module(process)
    service = WhiteBgService(lambda: tmp_path, module_loader=lambda _: module, thread_factory=threads)
    failed = service.start(str(tmp_path / 'broken'), processing_options({}))
    threads.join()
    task = service.task(failed)
    assert task['status'] == 'failed' and task['finished_at']
    assert task['error'] == 'OSError: 模拟读取图片失败' and task['result'] is None
    success = service.start(str(tmp_path / 'good'), processing_options({}))
    threads.join()
    assert service.task(success)['status'] == 'success'


def test_thread_start_failure_releases_product_and_keeps_failed_status(tmp_path):
    class BrokenThread:
        def start(self):
            raise RuntimeError('模拟线程不可用')
    ids = iter(['abcd1234', 'efgh5678'])
    from unittest.mock import patch
    service = WhiteBgService(lambda: tmp_path, thread_factory=lambda **kw: BrokenThread())
    with patch('src.sidecar.whitebg_service.uuid.uuid4', side_effect=lambda: next(ids)):
        with pytest.raises(RuntimeError, match='任务启动失败'):
            service.start(str(tmp_path / 'product'), processing_options({}))
        assert service.task('abcd1234')['status'] == 'failed'
        assert not service.is_processing(None, str(tmp_path / 'product'))


def test_model_switch_only_reloads_when_model_changes(tmp_path):
    threads = Threads()
    module = fake_module()
    service = WhiteBgService(lambda: tmp_path, module_loader=lambda _: module, thread_factory=threads)
    for model in ['first', 'first', 'second', 'second']:
        job = service.start(str(tmp_path / 'product'), processing_options({'matte_model': model}))
        threads.join()
        assert service.task(job)['status'] == 'success'
    assert [proc.cfg.matte_model for proc in module.processors] == ['first', 'second']


@pytest.fixture
def api(tmp_path):
    class Record:
        id = 7

        @classmethod
        def get_or_none(cls, _query):
            return cls.row

    root = tmp_path / 'products'
    root.mkdir()
    product = root / '商品'
    product.mkdir()
    Record.row = SimpleNamespace(id=7, name='商品', path=str(product), white_bg_path='自选.png')
    module = fake_module()
    jobs = []
    def thread_factory(**kwargs):
        jobs.append(kwargs)
        return SimpleNamespace(start=lambda: None)
    service = WhiteBgService(lambda: root, module_loader=lambda _: module, thread_factory=thread_factory)
    app = Flask('isolated-whitebg')
    CORS(app, resources={r'/*': {'origins': '*'}})
    app.register_blueprint(create_whitebg_blueprint(record_model=Record, account_lock=threading.RLock(), service=service))
    return SimpleNamespace(client=app.test_client(), app=app, service=service, module=module,
                           jobs=jobs, product=product, root=root, Record=Record)


def test_existing_routes_methods_defaults_and_cors_are_preserved(api):
    rules = {(rule.rule, method) for rule in api.app.url_map.iter_rules()
             if rule.rule.startswith('/api/') for method in rule.methods - {'OPTIONS', 'HEAD'}}
    assert rules == {('/api/whitebg/status', 'GET'), ('/api/whitebg/start', 'POST'),
                     ('/api/whitebg/task/<task_id>', 'GET'), ('/api/whitebg/list', 'GET'),
                     ('/api/whitebg/image', 'GET')}
    status = api.client.get('/api/whitebg/status')
    assert status.json == {'success': True, 'msg': '白底图模型状态',
                           'data': {'ready': True, 'missing': [], 'model': 'birefnet-general'}}
    response = api.client.post('/api/whitebg/start', json={'record_id': 7})
    assert response.status_code == 200 and response.json['success']
    task_id = response.json['data']['task_id']
    task = api.client.get('/api/whitebg/task/' + task_id).json['data']
    assert set(task) == {'task_id', 'product_dir', 'record_id', 'record_name', 'status', 'progress',
                         'message', 'current', 'total', 'done', 'result', 'error', 'created_at', 'finished_at'}
    assert task['status'] == 'pending' and task['record_id'] == 7
    assert api.jobs[0]['args'][2] == {'matte_model': 'birefnet-general', 'canvas': 1440,
        'fill_ratio': 0.82, 'deskew': True, 'square_size': None, 'overwrite': True, 'preserve_paths': ['自选.png']}
    response = api.client.options('/api/whitebg/start', headers={
        'Origin': 'http://tauri.localhost', 'Access-Control-Request-Method': 'POST'})
    assert 'POST' in response.headers['Access-Control-Allow-Methods']


def test_camel_case_options_keep_existing_meanings(api):
    response = api.client.post('/api/whitebg/start', json={'productDir': str(api.product),
        'matteModel': 'custom', 'canvasSize': 1200, 'fillRatio': 0.9, 'squareSize': 800,
        'deskew': 'false', 'overwrite': 'no'})
    assert response.json['success']
    assert api.jobs[0]['args'][2] == {'matte_model': 'custom', 'canvas': 1200, 'fill_ratio': 0.9,
        'square_size': 800, 'deskew': False, 'overwrite': False, 'preserve_paths': []}


@pytest.mark.parametrize('payload', [{'canvas': '错误'}, {'canvas': -1}, {'fill_ratio': 'nan'},
                                     {'fill_ratio': -1}, {'square_size': -1}, ['不是对象']])
def test_invalid_start_creates_no_pending_task(api, payload):
    if isinstance(payload, dict):
        payload['record_id'] = 7
    response = api.client.post('/api/whitebg/start', json=payload)
    assert response.status_code == 200 and response.json['success'] is False
    assert not api.jobs and not api.service.is_processing(7, str(api.product))


def test_missing_models_and_dependencies_keep_existing_error_contract(api, monkeypatch):
    monkeypatch.setattr(api.module, 'model_status', lambda _: {'ready': False, 'missing': ['model.onnx']})
    response = api.client.post('/api/whitebg/start', json={'record_id': 7})
    assert response.json == {'success': False, 'msg': '白底图模型未就绪，缺：model.onnx',
                             'data': {'ready': False, 'missing': ['model.onnx']}}
    assert not api.jobs
    def missing(_name):
        raise RuntimeError('缺少运行依赖')
    monkeypatch.setattr(api.service, '_load', missing)
    assert api.client.get('/api/whitebg/status').json['data'] == {
        'ready': False, 'missing': [], 'deps_missing': True}
    assert api.client.post('/api/whitebg/start', json={'record_id': 7}).json['data'] == {'deps_missing': True}


def test_directory_and_preview_boundaries_are_preserved(api):
    outside = api.root.parent / 'outside.jpg'
    outside.write_bytes(b'outside')
    assert api.client.get('/api/whitebg/image', query_string={'path': str(outside)}).status_code == 403
    assert api.client.get('/api/whitebg/image', query_string={'path': str(api.product / 'missing.jpg')}).status_code == 404
    for route in ['list', 'start']:
        call = api.client.get if route == 'list' else api.client.post
        args = {'product_dir': str(api.root.parent)}
        response = call('/api/whitebg/' + route, **({'query_string': args} if route == 'list' else {'json': args}))
        assert response.json['success'] is False and '越界' in response.json['msg']
    assert api.client.get('/api/whitebg/task/missing').json == {
        'success': False, 'msg': '白底图任务不存在', 'data': None}


def test_output_listing_keeps_paths_and_readable_report(api):
    (api.product / '白底图').mkdir()
    (api.product / 'SKU_1x1').mkdir()
    image = api.product / '白底图' / '袜子.jpg'
    image.write_bytes(b'fixture')
    (api.product / '白底图' / '_report.json').write_text('{"message":"已生成"}', encoding='utf-8')
    product_module = SimpleNamespace(WHITE_DIR='白底图', SQUARE_DIR='SKU_1x1',
        WHITE_ROOT_NAME='白底图.jpg', REPORT_NAME='_report.json',
        list_images=lambda folder: [str(p) for p in Path(folder).glob('*.jpg')])
    api.service._load = lambda name: product_module
    response = api.client.get('/api/whitebg/list', query_string={'record_id': 7})
    assert response.json == {'success': True, 'msg': '读取白底图列表成功', 'data': {
        'product_dir': str(api.product), 'white_root': '', 'square_images': [],
        'white_images': [{'path': str(image), 'name': '袜子.jpg', 'size': 7}],
        'report': {'message': '已生成'}}}

# -*- coding: utf-8 -*-
"""图片处理任务的进程级服务，与 Flask、数据库和浏览器解耦。

一个服务持有一个模型实例。执行锁覆盖参数设置及整个处理过程，避免并发任务
修改同一个 processor.cfg；状态锁只保护短时间读写，轮询不会被模型推理阻塞。
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import importlib
import json
import logging
import math
import os
import threading
import uuid


logger = logging.getLogger(__name__)
_DEPS_HINT = ('白底图功能缺少运行依赖，请安装 '
              'rembg / onnxruntime / tokenizers / scipy / numpy')


def _load_whitebg(name: str):
    """只在请求真正需要模型时导入，缺少可选依赖不影响桌面启动。"""
    try:
        return importlib.import_module('src.whitebg' if not name else f'src.whitebg.{name}')
    except ImportError as exc:
        raise RuntimeError(f'{_DEPS_HINT}（缺 {exc.name or exc}）') from exc


def _boolean(value, default):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def processing_options(data: dict, *, preserve_paths=()) -> dict:
    """沿用现有参数别名和默认值，在创建任务前完成参数解析。"""
    try:
        options = {
            'matte_model': str(data.get('matte_model') or data.get('matteModel') or 'birefnet-general'),
            'canvas': int(data.get('canvas') or data.get('canvasSize') or 1440),
            'fill_ratio': float(data.get('fill_ratio') or data.get('fillRatio') or 0.82),
            'deskew': _boolean(data.get('deskew', True), True),
            'square_size': int(data.get('square_size') or data.get('squareSize') or 0) or None,
            'overwrite': _boolean(data.get('overwrite', True), True),
            'preserve_paths': list(preserve_paths),
        }
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('图片处理参数无效，请检查画布尺寸和主体占比') from exc
    if (options['canvas'] <= 0 or
            not math.isfinite(options['fill_ratio']) or options['fill_ratio'] <= 0 or
            (options['square_size'] is not None and options['square_size'] <= 0)):
        raise ValueError('画布尺寸、规格图尺寸和主体占比必须为正数')
    return options


class WhiteBgService:
    """由应用入口创建并注入路由，每个应用有自己的任务状态。"""

    def __init__(self, uploads_root, *, module_loader=_load_whitebg, thread_factory=threading.Thread):
        self._uploads_root = uploads_root
        self._load = module_loader
        self._thread_factory = thread_factory
        self._tasks = {}
        self._tasks_lock = threading.Lock()
        self._execution_lock = threading.Lock()
        self._processor = None
        self._processor_key = None

    def checked_path(self, path: str) -> str:
        raw = str(path or '').strip()
        if not raw:
            raise ValueError('缺少路径')
        target = os.path.abspath(raw)
        root = os.path.abspath(self._uploads_root())
        try:
            inside = os.path.commonpath([target, root]) == root
        except ValueError:
            inside = False
        if not inside:
            raise ValueError(f'路径越界，只允许处理 {root} 下的采集目录')
        return target

    def model_status(self, matte_model='birefnet-general'):
        return self._load('').model_status(matte_model)

    @staticmethod
    def _same_product(task, record_id, product_dir):
        return ((record_id is not None and task.get('record_id') == record_id) or
                os.path.normcase(task['product_dir']) == os.path.normcase(product_dir))

    def is_processing(self, record_id, product_dir: str) -> bool:
        with self._tasks_lock:
            return any(task['status'] in ('pending', 'running') and
                       self._same_product(task, record_id, product_dir)
                       for task in self._tasks.values())

    def active_task_count(self) -> int:
        with self._tasks_lock:
            return sum(task['status'] in ('pending', 'running') for task in self._tasks.values())

    def start(self, product_dir: str, options: dict, *, record_id=None, record_name='') -> str:
        target = self.checked_path(product_dir)
        # 拷贝参数，调用方后续修改不能影响已启动的任务。
        options = deepcopy(options)
        task_id = str(uuid.uuid4())[:8]
        task = {
            'task_id': task_id, 'product_dir': target, 'record_id': record_id,
            'record_name': record_name or os.path.basename(target),
            'status': 'pending', 'progress': 0, 'message': '任务已创建',
            'current': '', 'total': 0, 'done': 0, 'result': None, 'error': None,
            'created_at': datetime.now().isoformat(), 'finished_at': None,
        }
        with self._tasks_lock:
            if any(existing['status'] in ('pending', 'running') and
                   self._same_product(existing, record_id, target)
                   for existing in self._tasks.values()):
                raise ValueError('该商品的图片正在生成，请等待任务完成')
            while task_id in self._tasks:
                task_id = str(uuid.uuid4())[:8]
            task['task_id'] = task_id
            self._tasks[task_id] = task
        try:
            self._thread_factory(target=self._run, args=(task_id, target, options), daemon=True).start()
        except Exception as exc:
            self._failed(task_id, exc)
            raise RuntimeError(f'白底图任务启动失败: {exc}') from exc
        return task_id

    def task(self, task_id: str):
        with self._tasks_lock:
            return deepcopy(self._tasks.get(task_id))

    def _update(self, task_id, **changes):
        with self._tasks_lock:
            self._tasks[task_id].update(changes)

    def _failed(self, task_id, exc):
        self._update(task_id, status='failed', progress=100, message=f'白底图生成失败: {exc}',
                     error=f'{type(exc).__name__}: {exc}', finished_at=datetime.now().isoformat())

    def _run(self, task_id: str, product_dir: str, options: dict):
        try:
            # 模型加载、切换与 cfg 设置全部处于同一个执行临界区。
            with self._execution_lock:
                self._update(task_id, status='running', progress=2, message='正在加载语义抠图模型')
                whitebg = self._load('')
                if self._processor is None or self._processor_key != options['matte_model']:
                    processor = whitebg.SockWhiteBg(whitebg.WhiteBgConfig(
                        matte_model=options['matte_model'], debug=False))
                    self._processor = processor
                    self._processor_key = options['matte_model']
                cfg = whitebg.WhiteBgConfig(
                    matte_model=options['matte_model'], canvas=options['canvas'],
                    fill_ratio=options['fill_ratio'], deskew=options['deskew'], debug=False)
                self._processor.cfg = cfg

                def progress(index, total, name):
                    pct = 5 + int(88 * (index - 1) / max(1, total))
                    self._update(task_id, progress=pct, total=total, done=index - 1, current=name,
                                 message=f'正在处理 {name}（{index}/{total}）')

                outcome = whitebg.process_product_dir(
                    product_dir, cfg, processor=self._processor,
                    square_size=options['square_size'], overwrite=options['overwrite'],
                    preserve_paths=options.get('preserve_paths') or (), progress=progress)
                self._update(task_id, status='success' if outcome.ok else 'failed',
                             progress=100, done=len(outcome.items), message=outcome.message,
                             result=outcome.to_dict(), error=None if outcome.ok else outcome.message,
                             finished_at=datetime.now().isoformat())
        except Exception as exc:
            logger.exception('白底图任务 %s 失败', task_id)
            self._failed(task_id, exc)

    def list_outputs(self, product_dir: str) -> dict:
        target = self.checked_path(product_dir)
        product = self._load('product')
        report = None
        report_path = os.path.join(target, product.WHITE_DIR, product.REPORT_NAME)
        if os.path.isfile(report_path):
            try:
                with open(report_path, 'r', encoding='utf-8') as handle:
                    report = json.load(handle)
            except (OSError, ValueError):
                # 保持旧接口的 report=None，但记录原因以便排查损坏的历史报告。
                logger.exception('读取图片处理报告失败: %s', report_path)

        def entry(path):
            return {'path': path, 'name': os.path.basename(path),
                    'size': os.path.getsize(path) if os.path.isfile(path) else 0}

        root_white = os.path.join(target, product.WHITE_ROOT_NAME)
        return {
            'product_dir': target,
            'white_root': root_white if os.path.isfile(root_white) else '',
            'white_images': [entry(p) for p in product.list_images(os.path.join(target, product.WHITE_DIR))],
            'square_images': [entry(p) for p in product.list_images(os.path.join(target, product.SQUARE_DIR))],
            'report': report,
        }

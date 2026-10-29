# -*- coding: utf-8 -*-
"""小红书千帆批量填表服务：任务字典与锁、批量 worker、已结束任务的清理，以及从 Record 取图片 / 类目 / 调试端口。

任务字典是进程内的，所以属于 ``XhsBatchService`` 实例（由应用入口创建一次），不再是 ``app.py`` 的模块全局；
真正去填表的 ``default_runner`` 仍在 ``xhs_routes`` 里按调用时延迟导入，本模块不导入浏览器库、不反向导入 app.py。

与 app.py 旧函数名的对应：
  _xhs_tasks / _xhs_tasks_lock      -> XhsBatchService.tasks / lock
  _xhs_images_from_record           -> XhsBatchService.images_from_record
  _xhs_category_from_record         -> XhsBatchService.category_from_record
  _run_xhs_fill_batch_task          -> XhsBatchService.run_fill_batch_task
  _prune_xhs_tasks_locked           -> XhsBatchService.prune_finished_locked
  _xhs_debug_port                   -> XhsBatchService.debug_port
  _XHS_DEFAULT_SERVICE_VALUES       -> XhsBatchService.DEFAULT_SERVICE_VALUES"""
import json
import os
import threading
from datetime import datetime


#: 与前端 `CATEGORY_OPTIONS`（tauri-app/src/types/index.ts）对齐。
#: clazz 存的是 CharField，可能是 "3" 也可能是 "长筒袜"，两种都认。
_XHS_CATEGORY_LABELS = {
    '0': '船袜', '1': '短袜', '2': '中筒袜', '3': '长筒袜', '4': '袜套',
    '船袜': '船袜', '短袜': '短袜', '中筒袜': '中筒袜', '长筒袜': '长筒袜', '袜套': '袜套',
}
#: 服务信息组**已实测存在**的默认取值（`verified`，见 xiaohongshu-publisher/docs/07-字段测绘表.md §8.9）。
#: 只放已核实文案；`unknown` 字段（发货模式/现货发货时间/开售时间/售后服务）一律不预设。
_XHS_DEFAULT_SERVICE_VALUES = {
    '物流模板': '【系统创建】物流模板默认—联系人',
    '运费模板': '系统默认-全国包邮模版',
    '物流类型': '普通内贸',
}
#: 已完成的小红书任务在内存里保留的上限与时长（计划 3.3）。
#: `_xhs_tasks` 是**进程内字典**，不清理就会随每次批量填表一直积累 ✗。
#: 只清理**已结束**的任务；`running` / `pending` 一律不动（前端可能还在轮询它们 ✓）。
XHS_TASK_KEEP_FINISHED = 20
XHS_TASK_FINISHED_TTL_HOURS = 24


class XhsBatchService:
    """一个应用一个实例，持有批量填表的任务字典和锁。

    ``record_model`` 是商品表；``get_pic_list`` 取商品目录里的图片（在 src.utils 里，会连带导入浏览器库，所以注入）；
    ``shop_session`` 提供小红书页面域名；``host`` / ``port_start`` / ``port_end`` 是账户浏览器的调试地址和端口段。"""

    def __init__(self, *, record_model, get_pic_list, shop_session, host, port_start, port_end):
        self._record_model = record_model
        self._get_pic_list = get_pic_list
        self._shop_session = shop_session
        self._host = host
        self._port_start = port_start
        self._port_end = port_end
        # ---------------------------------------------------------------------------
        # 小红书千帆批量填表（status=0 商品依次 fill-only）
        # ---------------------------------------------------------------------------
        self.tasks: dict = {}
        self.lock = threading.Lock()

    #: 路由层要用的默认服务信息取值（模块常量的只读引用）。
    DEFAULT_SERVICE_VALUES = _XHS_DEFAULT_SERVICE_VALUES

    def images_from_record(self, record):
        """从 Record 收集本地图片绝对路径列表。"""
        images = []
        for key in ('800', '750'):
            try:
                for p in self._get_pic_list(record, key):
                    if os.path.isfile(p):
                        images.append(p)
            except Exception:
                pass
        try:
            sku_list = json.loads(record.content) if record.content else []
        except (ValueError, TypeError):
            sku_list = []
        for s in sku_list:
            if not isinstance(s, dict):
                continue
            p = str(s.get('path') or '').strip()
            if p and os.path.isfile(p):
                images.append(p)
        return images

    def category_from_record(self, record):
        """从 Record.clazz 映射到小红书类目短名；认不出返回空串（不猜）。"""
        raw = (record.clazz or '').strip() if record.clazz is not None else ''
        return _XHS_CATEGORY_LABELS.get(raw, '')

    def run_fill_batch_task(self, task_id, payload):
        """小红书批量填表 worker：依次对 status=0 商品执行 fill-only。"""
        from src.sidecar.xhs_routes import default_runner as _xhs_runner

        records = list(self._record_model.select().where(self._record_model.status == 0).order_by(self._record_model.id))
        total = len(records)
        if total == 0:
            with self.lock:
                task = self.tasks.get(task_id)
                if task:
                    task['status'] = 'failed'
                    task['message'] = '没有待上传的商品'
                    task['finished_at'] = datetime.now().isoformat()
            return

        allow_upload = bool(payload.get('allow_upload'))
        port = self.debug_port(payload.get('port'))
        results, succeeded, failed = [], 0, 0

        for idx, record in enumerate(records):
            with self.lock:
                task = self.tasks.get(task_id)
                if task and task.get('cancelled'):
                    task['status'] = 'cancelled'
                    task['message'] = '批量填表已取消（{}/{}）'.format(idx, total)
                    task['finished_at'] = datetime.now().isoformat()
                    return
                if task:
                    task['message'] = '批量填表 {}/{}：{}'.format(idx + 1, total, record.name or record.id)
                    task['progress'] = int((idx / total) * 100)

            title = (record.title or '').strip() or (record.name or '').strip()
            images = self.images_from_record(record)
            if not title:
                failed += 1
                results.append({'record_id': record.id, 'name': record.name,
                                'success': False, 'error': '标题为空'})
                continue

            category = self.category_from_record(record)
            service_values = dict(payload.get('service_values') or _XHS_DEFAULT_SERVICE_VALUES)
            try:
                report = _xhs_runner({
                    'title': title,
                    'images': images,
                    'allow_upload': allow_upload,
                    'allow_advance': bool(payload.get('allow_advance', True)),
                    'category': category,
                    'service_values': service_values,
                    'port': port,
                })
                ok = bool(report.get('ok', False))
                if ok:
                    succeeded += 1
                else:
                    failed += 1
                results.append({'record_id': record.id, 'name': record.name, 'success': ok,
                                'error': '; '.join(report.get('blocked') or []) or ''})
            except Exception as exc:  # noqa: BLE001
                failed += 1
                results.append({'record_id': record.id, 'name': record.name, 'success': False,
                                'error': '{}: {}'.format(type(exc).__name__, exc)})

        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            task['progress'] = 100
            task['result'] = {'success': failed == 0, 'results': results,
                              'succeeded': succeeded, 'failed': failed, 'total': total}
            task['status'] = 'succeeded' if failed == 0 else ('succeeded' if succeeded > 0 else 'failed')
            task['message'] = '批量填表结束：{} 成功 / {} 失败 / 共 {}'.format(succeeded, failed, total)
            task['finished_at'] = datetime.now().isoformat()

    def prune_finished_locked(self) -> int:
        """清理已结束的小红书任务（**必须持锁调用** ✓）。返回删除条数。

        规则：先丢弃结束时间超过 TTL 的，再按"保留最近 N 条"丢弃多余的。
        时间戳解析失败（异常路径）时**保留不动**，不猜 ✗。
        """
        terminal = ('succeeded', 'failed', 'cancelled')

        def _stamp(task):
            text = task.get('finished_at') or task.get('created_at') or ''
            try:
                return datetime.fromisoformat(text)
            except (TypeError, ValueError):
                return None

        finished = [t for t in self.tasks.values() if t.get('status') in terminal]
        if not finished:
            return 0

        removed = 0
        now = datetime.now()
        for task in finished:
            stamp = _stamp(task)
            if stamp is not None and (now - stamp).total_seconds() > XHS_TASK_FINISHED_TTL_HOURS * 3600:
                if self.tasks.pop(task['task_id'], None) is not None:
                    removed += 1

        remaining = sorted((t for t in self.tasks.values() if t.get('status') in terminal),
                           key=lambda t: t.get('finished_at') or t.get('created_at') or '')
        if len(remaining) > XHS_TASK_KEEP_FINISHED:
            for task in remaining[:len(remaining) - XHS_TASK_KEEP_FINISHED]:
                if self.tasks.pop(task['task_id'], None) is not None:
                    removed += 1
        return removed

    def debug_port(self, payload_port=None):
        """小红书填表端口：显式传入优先，否则在账户浏览器端口段直扫千帆页面。

        刻意不依赖 ``_resolve_active_shop_browser``：那条链在 sidecar 里
        实测扫不到 9500 上的千帆页（shop/current 报 no_browser），
        而同机 ``urlopen('http://127.0.0.1:9500/json/list')`` 是通的。
        """
        if payload_port:
            try:
                return int(payload_port)
            except (TypeError, ValueError):
                pass
        try:
            from urllib.error import URLError
            from urllib.request import urlopen

            for port in range(self._port_start, self._port_end + 1):
                address = '{}:{}'.format(self._host, port)
                try:
                    with urlopen('http://{}/json/list'.format(address), timeout=0.4) as resp:
                        targets = json.loads(resp.read().decode('utf-8', errors='replace'))
                except (URLError, OSError, ValueError):
                    continue
                for target in targets:
                    url = str(target.get('url') or '')
                    if target.get('type') == 'page' and any(d in url for d in self._shop_session.XHS_DOMAINS):
                        return port
        except Exception:
            pass
        return None

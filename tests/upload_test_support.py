# -*- coding: utf-8 -*-
"""抖店上传服务（``UploadService``）与接口（``upload_routes``）的测试共用件。

``make_upload_service(**overrides)`` 返回**真实的** ``UploadService``：构造函数只是把依赖存起来，所以默认的两个端口全是
“一碰就失败”的假件（``forbidden``）——被测代码意外去碰浏览器 / 页面步骤时用例当场报错，而不是悄悄通过。
需要哪个能力，就在 ``browser=`` / ``steps=`` 里覆盖对应字段（``port_overrides``），或者直接替换服务实例上的方法。

``World`` 是一整套“按剧本演”的替身：页面步骤（记录每次调用，可以按步骤名指定返回值 / 抛异常）、浏览器端口（计时、睡眠、图片列表、
CDP 探测都记录下来）、设置、商品表、日志。流水线的单元测试都建立在它上面，``world.calls`` 是按发生顺序排列的全部调用。

文件名故意不叫 ``sidecar_*``：``tests/`` 与 ``taobao-publisher/`` 的辅助模块不能重名（见 CLAUDE.md「工作约定」）。
"""
import dataclasses
import threading
from types import SimpleNamespace

from src.sidecar.upload_service import UploadBrowserPort, UploadService, UploadStepsPort


def forbidden(name):
    """返回一个一调用就失败的函数，错误信息里带上它代表的端口字段。"""
    def fail(*_args, **_kwargs):
        raise AssertionError('被测代码不该碰 %s' % name)
    fail.__name__ = 'forbidden_' + name
    return fail


def inert_browser_port(**overrides):
    values = {field.name: forbidden(field.name) for field in dataclasses.fields(UploadBrowserPort)}
    values['page_state'] = lambda: SimpleNamespace(page=None)
    values['time'] = SimpleNamespace(sleep=forbidden('time.sleep'))
    values.update(overrides)
    return UploadBrowserPort(**values)


def inert_steps_port(**overrides):
    values = {field.name: forbidden(field.name) for field in dataclasses.fields(UploadStepsPort)}
    values['create_url'] = 'https://example.invalid/ffa/g/create'
    values['login_wait_seconds'] = 3
    values.update(overrides)
    return UploadStepsPort(**values)


def make_upload_service(*, browser=None, steps=None, port_overrides=None, **overrides):
    """真实的 ``UploadService``。``port_overrides`` 形如 ``{'browser': {...}, 'steps': {...}}``，只覆盖端口里的个别字段。"""
    port_overrides = port_overrides or {}
    values = dict(
        record_model=SimpleNamespace(),
        accounts=SimpleNamespace(active_profile=lambda: 'test-profile'),
        browser=browser or inert_browser_port(**port_overrides.get('browser', {})),
        steps=steps or inert_steps_port(**port_overrides.get('steps', {})),
        settings_manager=SimpleNamespace(),
        shop_session=SimpleNamespace(),
        logger=SimpleNamespace(info=lambda *a, **k: None, debug=lambda *a, **k: None),
        get_app_root=forbidden('get_app_root'),
        app_file=__file__,
        repo_root='.',
        stage_timing_log_path='',
    )
    values.update(overrides)
    return UploadService(**values)


def task_registry(service, **tasks):
    """往服务的任务表里放几个任务（在锁里放），返回任务表本身。"""
    with service.lock:
        service.tasks.update(tasks)
    return service.tasks


def fresh_lock():
    return threading.RLock()


# ---------------------------------------------------------------------------------------------- 商品表 / 记录替身
class _IdField:
    """``Record.id == value`` 返回 ``value`` 本身，于是 ``get_or_none(Record.id == record_id)`` 收到的就是 record_id。"""

    def __eq__(self, other):
        return other

    __hash__ = None


class _Query:
    """select() 的返回：where(Record.status == 0) 真的按 status 过滤，execute() 不过滤（和 peewee 一样）。"""

    def __init__(self, rows):
        self._rows = list(rows)

    def where(self, wanted_status):
        return _Query(row for row in self._rows if getattr(row, 'status', 0) == wanted_status)

    def order_by(self, *_fields):
        return _Query(sorted(self._rows, key=lambda row: row.id))

    def execute(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class FakeRecordModel:
    id = _IdField()
    status = _IdField()

    def __init__(self, rows=()):
        self.rows = {row.id: row for row in rows}

    def get_or_none(self, wanted_id):
        return self.rows.get(wanted_id)

    def select(self):
        return _Query(self.rows.values())


def make_record(record_id=1, name='白袜_货号_x_商品一', **fields):
    values = dict(id=record_id, name=name, title='标题', remark='备注', clazz='2', repo=100, status=0,
                  content='[{"name": "白色", "price": 9.9, "path": "SKU/白.jpg"}]')
    values.update(fields)
    return SimpleNamespace(**values)


# ---------------------------------------------------------------------------------------------- 剧本
STEP_NAMES = ['settle_between_records', 'wait_login_complete', 'prepare_record_assets', 'dismiss_pending_browser_alert',
              'open_publish_page', 'fill_title_for_record', 'select_category_and_prepare_attributes',
              'fill_category_attributes', 'upload_main_images', 'upload_media_assets', 'configure_sku_entries',
              'configure_sku_structure', 'fill_price_stock_and_delivery', 'submit_publish']

DEFAULT_ASSETS = {'main_pic_list': ['main.jpg'], 'diaopai_pic': 'diaopai.jpg', 'sub_pic_list': ['sub.jpg'], 'my_video': 'v.mp4',
                  'white_pic': 'white.jpg', 'detail_pic_list': ['d1.jpg'], 'sku_list': [{'name': '白色', 'price': 9.9}]}

DEFAULT_AUTOMATION = {'publish_mode': 'dom', 'shipping_template': '中通包邮', 'material_compositions': []}


class World:
    """一次测试里的全部替身。

    * ``world.calls``：按发生顺序记录的 ``(名字, 参数...)``——页面步骤、计时、睡眠、业务回调都在里面；
    * ``behaviors``：``{步骤名: 值}``。值是异常实例 / 异常类 → 抛出；可调用 → 调用它拿返回值；其它 → 当返回值。
      页面步骤的默认返回：``prepare_record_assets`` 给一份完整素材，``open_publish_page`` / ``submit_publish`` / ``wait_login_complete`` 给 True；
    * ``automation``：设置里的自动化配置（``publish_mode`` 等）；
    * ``world.service``：接好以上替身的真实 ``UploadService``。
    """

    def __init__(self, tmp_path, *, records=(), behaviors=None, automation=None, page=None, active_profile='shop-a',
                 browser_overrides=None, service_overrides=None):
        self.calls = []
        self.behaviors = dict(behaviors or {})
        self.automation = dict(DEFAULT_AUTOMATION, **(automation or {}))
        self.records = FakeRecordModel(records)
        self.state = SimpleNamespace(page=page)
        self.timer_summaries = []
        self.sleeps = []
        self.automation_errors = []
        self.latest_error = {'stage': 'unknown'}
        self.settings = SimpleNamespace(
            get_settings=lambda: SimpleNamespace(automation_config=dict(self.automation)),
            normalize_automation_config=lambda config: dict(config),
        )
        steps = {}
        for name in STEP_NAMES:
            steps[name] = self._step(name)
        browser = dict(
            page_state=lambda: self.state,
            open_page=lambda *a, **k: self._record('open_page', *a, **k),
            get_pic_list=lambda record, size: self._record('get_pic_list', record.id, size) or [],
            get_detail_pic_list=lambda record: self._record('get_detail_pic_list', record.id) or [],
            reset_category_expanded_state=lambda: self._record('reset_category_expanded_state'),
            timer_start_session=lambda session_id: self._record('timer_start_session', session_id),
            timer_end_session=lambda: self._record('timer_end_session') or {'steps': 0},
            timer_record=lambda *a: self._record('timer_record', *a),
            time=SimpleNamespace(sleep=lambda seconds: self.sleeps.append(seconds)),
            normalize_debug_address=lambda value: str(value or ''),
            discover_debuggable_browsers=lambda **k: self._record('discover_debuggable_browsers', **k) or [],
            fetch_cdp_page_targets=lambda address: self._record('fetch_cdp_page_targets', address) or [],
            is_logged_in_fxg_target_url=lambda url: 'jinritemai.com' in str(url),
            attach_reusable_browser=lambda report: self._record('attach_reusable_browser') or None,
            find_cdp_port=lambda: self._record('find_cdp_port') or None,
            record_automation_error=lambda stage, exc, detail, **k: self.automation_errors.append((stage, str(exc), detail, k)),
            latest_error_after=lambda started_at: self.latest_error,
        )
        browser.update(browser_overrides or {})
        self.browser_fields = browser
        self.step_fields = steps
        self.service = make_upload_service(
            record_model=self.records,
            accounts=SimpleNamespace(active_profile=lambda: active_profile, active_account=lambda: {'profile_name': active_profile}),
            browser=UploadBrowserPort(**browser),
            steps=UploadStepsPort(create_url='https://example.invalid/ffa/g/create', login_wait_seconds=3, **steps),
            settings_manager=self.settings,
            shop_session=SimpleNamespace(),
            app_file=str(tmp_path / 'app.py'),            # 诊断日志（run_task_diag.log / protocol_diag.log）落在 tmp_path，不污染仓库
            repo_root=str(tmp_path),
            stage_timing_log_path=str(tmp_path / 'timing.jsonl'),
            get_app_root=lambda: str(tmp_path),
            **(service_overrides or {}),
        )

    # ---- 内部
    def _record(self, name, *args, **kwargs):
        self.calls.append((name,) + args + (tuple(sorted(kwargs.items())) if kwargs else ()))
        return None

    def _step(self, name):
        def call(*args, **kwargs):
            self.calls.append((name,) + tuple(_brief(a) for a in args))
            behavior = self.behaviors.get(name, _DEFAULT_STEP_RETURNS.get(name))
            if isinstance(behavior, BaseException) or (isinstance(behavior, type) and issubclass(behavior, BaseException)):
                raise behavior
            if callable(behavior) and not isinstance(behavior, type):
                return behavior(*args, **kwargs)
            return behavior
        call.__name__ = name
        return call

    # ---- 查询
    def names(self):
        return [call[0] for call in self.calls]

    def count(self, name):
        return self.names().count(name)

    def stages(self):
        """每条记录的“阶段步骤”调用顺序（只取页面步骤，去掉计时 / 重置之类）。"""
        return [name for name in self.names() if name in STEP_NAMES]


def _brief(value):
    """调用记录里只保留易比较的部分：商品记录取 id，函数取名字，其它原样。"""
    if hasattr(value, 'id') and hasattr(value, 'name') and not isinstance(value, (str, bytes)):
        return ('record', value.id)
    if callable(value):
        return 'callable'
    return value


_DEFAULT_STEP_RETURNS = {
    'prepare_record_assets': lambda record: (dict(DEFAULT_ASSETS), ''),
    'open_publish_page': True,
    'submit_publish': True,
    'wait_login_complete': True,
}

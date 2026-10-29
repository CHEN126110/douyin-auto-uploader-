# -*- coding: utf-8 -*-
"""淘宝发布模块（src/sidecar/taobao_*.py）的测试夹具。

2026-10-20 淘宝发布从 ``app.py`` 拆成 ``taobao_helpers``（纯函数）、``taobao_service``（``TaobaoPublishService``）、
``taobao_routes``（八个接口）。旧测试靠按名字从 ``app.py`` 源码里抽函数再 ``exec``；现在直接构造真实的服务对象和 Blueprint，
外部依赖（商品表、浏览器、淘宝流水线、数据目录）都用假件注入，不导入 ``app.py``、不碰真实数据库。

账户门禁用真实的 ``ShopAccountGuard``，注册表是一个只含当前账户的最小假件。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT, ROOT / 'taobao-publisher'):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from src.sidecar.shop_accounts import ShopAccountGuard  # noqa: E402
from src.sidecar.taobao_routes import create_taobao_blueprint  # noqa: E402
from src.sidecar.taobao_service import TaobaoPublishService  # noqa: E402


def make_registry(profile='taobao-test', platform='taobao'):
    """只含一个当前账户的最小注册表假件（``ShopAccountGuard`` 用到的那几个成员）。"""
    state = {'registry': {'active_profile': profile, 'profiles': {profile: {'platform': platform, 'label': '测试账户'}}}}
    return SimpleNamespace(
        DEFAULT_PROFILE_NAME='upload-browser-profile',
        load_registry=lambda: state['registry'],
        slugify_profile_name=lambda name: name,
        normalize_platform=lambda value: value,
        state=state,
    )


class _Query:
    """``Record.select().where(...).order_by(...)`` 的最小替身：条件在假件里不求值，只返回事先挑好的行。"""

    def __init__(self, rows):
        self._rows = rows

    def where(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def __iter__(self):
        return iter(self._rows)


class FakeRecord:
    """最小的商品表替身：``get_by_id`` 按 ``rows`` 查；``select`` 返回 ``status == 0`` 的行（按 id 排序）。"""
    DoesNotExist = LookupError
    rows = {}
    id = 0            # 类属性只为让 ``Record.id`` / ``Record.status == 0`` 这类表达式能求值
    status = 0

    @classmethod
    def _row(cls, row):
        return SimpleNamespace(**row, __data__=dict(row))

    @classmethod
    def get_by_id(cls, record_id):
        if record_id not in cls.rows:
            raise cls.DoesNotExist()
        return cls._row(cls.rows[record_id])

    @classmethod
    def select(cls):
        return _Query([cls._row(row) for _id, row in sorted(cls.rows.items()) if row.get('status') == 0])


def make_record_model(rows=None):
    """每个用例一个独立的商品表替身，避免类属性在用例之间串。"""
    return type('FakeRecord', (FakeRecord,), {'rows': dict(rows or {})})


def make_row(record_id, **overrides):
    """一条商品记录（字典）；``content`` 缺省是两个 SKU。

    ``clazz`` 缺省是字符串 ``'2'``：``Record.clazz`` 是 ``CharField``，从库里读出来就是字符串（整数 2 存进去、读出来是 ``'2'``）。
    这里曾经写成整数 2，于是批量发布里「数字字符串类目没被映射成名称」的问题测不出来。
    """
    row = {'id': record_id, 'name': '商品%d' % record_id, 'title': '标题%d' % record_id, 'path': '', 'clazz': '2', 'repo': 5,
           'status': 0, 'content': json.dumps([{'name': '白色', 'price': 12.5, 'path': ''},
                                               {'name': '黑色', 'price': 13, 'path': ''}], ensure_ascii=False)}
    row.update(overrides)
    return row


def make_service(**overrides):
    """所有依赖都是无害的假件；用例按需覆盖其中几个。"""
    registry = overrides.pop('registry', None) or make_registry()
    tasks_running = overrides.pop('has_running_publish_tasks', lambda: False)
    guard = overrides.pop('accounts', None) or ShopAccountGuard(
        shop_session=registry, has_running_publish_tasks=tasks_running,
    )
    deps = dict(
        record_model=make_record_model(), repo_root=str(ROOT), accounts=guard,
        shop_service=SimpleNamespace(
            resolve_active_browser=lambda platform=None: ('', None, 'none'),
            activate_profile=lambda *args, **kwargs: {},
        ),
        normalize_debug_address=lambda value: value or '', resolve_data_file=lambda name: ROOT / '.tmp' / name,
        bootstrap_log=lambda message: None,
    )
    deps.update(overrides)
    return TaobaoPublishService(**deps)


def make_app(service, **overrides):
    """装好淘宝 Blueprint 的 Flask 应用；返回 (app, 账户门禁)。"""
    accounts = overrides.pop('accounts', None) or service._accounts
    deps = dict(
        service=service, accounts=accounts, record_model=service._record_model,
        resolve_data_file=service._resolve_data_file, require_product_revision=lambda row, expected: None,
    )
    deps.update(overrides)
    app = Flask('taobao-test')
    app.config.update(TESTING=True)
    app.register_blueprint(create_taobao_blueprint(**deps))
    return app, accounts


class FakePipeline:
    """``taobao_publish.pipeline`` 的替身：记录每次 ``run_from_record`` 的参数，按 ``behavior`` 返回结果或抛异常。

    ``behavior`` 可以是一个 payload 字典、一个会抛的异常、或一个 ``(row, request, kwargs) -> payload`` 的函数。
    """

    def __init__(self, behavior=None):
        self.behavior = behavior if behavior is not None else {'success': True, 'steps': []}
        self.calls = []

    def run_from_record(self, row, request_payload, **kwargs):
        self.calls.append(SimpleNamespace(row=row, request=request_payload, kwargs=kwargs))
        behavior = self.behavior
        if isinstance(behavior, BaseException):
            raise behavior
        payload = behavior(row, request_payload, kwargs) if callable(behavior) else behavior
        return SimpleNamespace(to_dict=lambda: json.loads(json.dumps(payload)))

# -*- coding: utf-8 -*-
"""淘宝发布服务（``src/sidecar/taobao_service.py``）：任务表、淘宝模块的延迟加载、浏览器地址、界面资料 → 流水线请求的翻译、
单品 / 批量发布的后台 worker。

服务对象直接构造，依赖（账户门禁、店铺会话、商品表、数据目录、启动日志）都用假件注入；流水线是 ``FakePipeline``。
翻译用的是真实的 ``taobao_publish.desktop``（本地契约、目录安全检查），商品目录放在 pytest 的临时目录里。
"""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'taobao-publisher'))

from taobao_publish.authorization import WriteAuthorization  # noqa: E402
from taobao_publish.folder_import import MATERIAL_CENTER_URL  # noqa: E402
from taobao_publish.verification import WHOLE_FORM_SCOPE  # noqa: E402
from taobao_test_support import (  # noqa: E402
    FakePipeline, make_record_model, make_registry, make_row, make_service,
)

ACCOUNT = 'taobao-test'
URL = 'http://127.0.0.1:9501/json/list'


@pytest.fixture(autouse=True)
def isolated_media_route(monkeypatch):
    """worker 会临时改进程级环境变量 TAOBAO_MEDIA_ROUTE：每个用例从「未设置」开始，也不留痕迹。"""
    monkeypatch.delenv('TAOBAO_MEDIA_ROUTE', raising=False)


# ------------------------------------------------------------------------------------------ 商品目录
@pytest.fixture
def product(tmp_path):
    """一个真实的商品目录：两张已登记的 SKU 图，加一张没登记的。"""
    base = tmp_path / '商品资料'
    for name in ('白色', '黑色', '没登记'):
        (base / 'SKU').mkdir(parents=True, exist_ok=True)
        (base / 'SKU' / (name + '.jpg')).write_bytes(b'img-' + name.encode('utf-8'))
    content = [{'path': str(base / 'SKU' / (name + '.jpg')), 'name': name, 'price': 12.5} for name in ('白色', '黑色')]
    row = make_row(7, path=str(base), content=json.dumps(content, ensure_ascii=False))
    return SimpleNamespace(base=base, row=row, white=str(base / 'SKU' / '白色.jpg'), black=str(base / 'SKU' / '黑色.jpg'),
                           other=str(base / 'SKU' / '没登记.jpg'))


# ------------------------------------------------------------------------------------------ 依赖边界
def test_importing_the_taobao_modules_does_not_load_the_browser_stack(tmp_path):
    """三个模块都不导入 src.utils / DrissionPage / app.py，也不在导入时加载 taobao_publish 包（请求里才加载）。"""
    code = (
        "import sys; sys.path.insert(0, %r); "
        "import src.sidecar.taobao_helpers, src.sidecar.taobao_service, src.sidecar.taobao_routes; "
        "bad = [m for m in ('DrissionPage', 'src.utils', 'PySide6', 'app', 'src.orm', 'taobao_publish') if m in sys.modules]; "
        "print('LOADED=' + ','.join(bad))" % str(ROOT)
    )
    env = dict(os.environ, DOUYIN_DATA_DIR=str(tmp_path / 'data'), PYTHONUTF8='1')
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, encoding='utf-8', env=env, check=True)
    assert out.stdout.strip().splitlines()[-1] == 'LOADED='


# ------------------------------------------------------------------------------------------ 状态
def test_each_service_owns_its_task_table_and_lock():
    first, second = make_service(), make_service()
    assert first.tasks == {} and first.tasks is not second.tasks
    assert first.lock is not second.lock
    assert type(first.lock) is type(threading.Lock())


# ------------------------------------------------------------------------------------------ 延迟加载
@pytest.mark.parametrize('loader,module', [('load_desktop', 'taobao_publish.desktop'), ('load_pipeline', 'taobao_publish.pipeline')])
def test_source_run_puts_the_package_root_on_sys_path_once(monkeypatch, tmp_path, loader, module):
    monkeypatch.setattr(sys, 'path', [p for p in sys.path if p != os.path.join(str(tmp_path), 'taobao-publisher')])
    monkeypatch.delattr(sys, 'frozen', raising=False)
    service = make_service(repo_root=str(tmp_path))
    package_root = os.path.join(str(tmp_path), 'taobao-publisher')
    assert getattr(service, loader)().__name__ == module
    assert sys.path[0] == package_root
    getattr(service, loader)()
    assert sys.path.count(package_root) == 1


@pytest.mark.parametrize('loader', ['load_desktop', 'load_pipeline'])
def test_frozen_run_leaves_sys_path_alone(monkeypatch, tmp_path, loader):
    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    before = list(sys.path)
    getattr(make_service(repo_root=str(tmp_path)), loader)()
    assert sys.path == before


# ------------------------------------------------------------------------------------------ 浏览器地址
def test_cdp_list_url_comes_from_the_browser_of_the_taobao_account():
    calls = []

    def resolve(platform=None):
        calls.append(platform)
        return '127.0.0.1:9502', {'pid': 1}, 'fake'

    service = make_service(shop_service=SimpleNamespace(resolve_active_browser=resolve))
    assert service.cdp_list_url() == 'http://127.0.0.1:9502/json/list'
    assert calls == ['taobao']


@pytest.mark.parametrize('address', ['', None])
def test_cdp_list_url_is_empty_when_there_is_no_browser(address):
    service = make_service(shop_service=SimpleNamespace(resolve_active_browser=lambda platform=None: (address, None, 'none')))
    assert service.cdp_list_url() == ''


def shop_with(result=None, error=None):
    calls = []

    def activate(profile_name, open_browser=False, browser_url=None):
        calls.append((profile_name, open_browser, browser_url))
        if error:
            raise error
        return result

    return SimpleNamespace(activate_profile=activate, calls=calls)


def test_ensure_fill_browser_opens_the_material_center_with_the_current_account():
    shop = shop_with({'active_profile': ACCOUNT, 'browser_opened': True, 'debug_address': 'localhost:9501'})
    service = make_service(shop_service=shop, normalize_debug_address=lambda value: value.replace('localhost', '127.0.0.1'))
    assert service.ensure_fill_browser() == URL
    assert shop.calls == [(ACCOUNT, True, MATERIAL_CENTER_URL)]


def test_ensure_fill_browser_refuses_a_non_taobao_account():
    shop = shop_with({})
    service = make_service(shop_service=shop, registry=make_registry(platform='douyin'))
    with pytest.raises(ValueError, match='当前账户不属于淘宝'):
        service.ensure_fill_browser()
    assert shop.calls == []


@pytest.mark.parametrize('result,message', [
    ({'active_profile': 'other', 'browser_opened': True, 'debug_address': 'x'}, '浏览器账户与当前淘宝账户不一致'),
    ({'active_profile': ACCOUNT, 'browser_opened': False, 'browser_error': 'Chrome启动失败'}, 'Chrome启动失败'),
    ({'active_profile': ACCOUNT, 'browser_opened': False}, '浏览器未能启动'),
    ({'active_profile': ACCOUNT, 'browser_opened': True, 'debug_address': ''}, '浏览器已打开，但没有返回可连接的调试地址'),
    ({'active_profile': ACCOUNT, 'browser_opened': True}, '浏览器已打开，但没有返回可连接的调试地址'),
])
def test_ensure_fill_browser_reports_why_it_failed(result, message):
    service = make_service(shop_service=shop_with(result))
    with pytest.raises(RuntimeError) as caught:
        service.ensure_fill_browser()
    assert str(caught.value) == message


def test_ensure_fill_browser_does_not_swallow_errors_from_the_account_lifecycle():
    service = make_service(shop_service=shop_with(error=OSError('无法启动浏览器进程')))
    with pytest.raises(OSError, match='无法启动浏览器进程'):
        service.ensure_fill_browser()


# ------------------------------------------------------------------------------------------ 翻译
def translate(product_data, record=None):
    return make_service().product_request_payload(product_data, record=record)


@pytest.mark.parametrize('bad', [None, [], 'x', 5])
def test_translation_refuses_non_object_products_with_none(bad):
    assert translate(bad) is None


def test_translation_of_an_empty_product_only_has_the_caller_fields():
    assert translate({}) == {'record_id': None, 'record_name': ''}


def test_text_fields_are_stripped_and_must_be_text():
    request = translate({'title': ' 标题 ', 'guide_title': ' 导购 ', 'freight_template_name': ' 模板 ', 'outer_id': ' 编码 '})
    assert (request['title'], request['guide_title'], request['freight_template_name'], request['outer_id']) == (
        '标题', '导购', '模板', '编码')
    for key in ('title', 'guide_title', 'freight_template_name', 'outer_id'):
        for bad in (None, True, 100, []):
            with pytest.raises(ValueError, match='%s 必须是文本' % key):
                translate({key: bad})


@pytest.mark.parametrize('title,ok', [('袜' * 30, True), ('A' * 60, True), ('袜' * 29 + 'AB', True),
                                      ('袜' * 31, False), ('A' * 61, False), ('袜' * 29 + 'ABC', False)])
def test_title_length_follows_the_archived_contract_with_chinese_counted_twice(title, ok):
    if ok:
        assert translate({'title': title})['title'] == title
    else:
        with pytest.raises(ValueError, match=r'宝贝标题 \d+ 字符，超过已归档规则上限 60'):
            translate({'title': title})


def test_empty_title_is_refused_but_empty_guide_title_is_allowed():
    with pytest.raises(ValueError, match='宝贝标题不能为空'):
        translate({'title': '   '})
    assert translate({'guide_title': ''})['guide_title'] == ''


@pytest.mark.parametrize('length,ok', [(15, True), (16, False)])
def test_guide_title_length_limit(length, ok):
    if ok:
        assert translate({'guide_title': '好' * length})
    else:
        with pytest.raises(ValueError, match='导购标题 32 字符，超过已归档规则上限 30'):
            translate({'guide_title': '好' * length})


def test_sku_mode_is_validated_and_kept():
    assert translate({'sku_mode': 'custom'})['sku_mode'] == 'custom'
    assert translate({'sku_mode': 'standard'})['sku_mode'] == 'standard'
    assert 'sku_mode' not in translate({})
    for bad in (None, '', 'guess', True, [], {}):
        with pytest.raises(ValueError, match='sku_mode'):
            translate({'sku_mode': bad})


def test_category_path_is_split_on_gt_and_never_guessed():
    assert translate({'category_path': ' 女装 > 袜子 >  > 中筒袜 '})['category'] == {
        'category_id': '', 'path': ['女装', '袜子', '中筒袜']}
    assert 'category' not in translate({'category_path': '   '})
    assert 'category' not in translate({'category_path': 5})
    assert translate({'category_path': 'a>b', 'category_id': '123'})['category'] == {'category_id': '123', 'path': ['a', 'b']}


def test_category_keyword_and_id():
    assert translate({'category_keyword': ' 中筒袜 '})['category'] == {'search_keyword': '中筒袜'}
    assert translate({'category_keyword': '中筒袜', 'category_id': 456})['category'] == {
        'search_keyword': '中筒袜', 'category_id': '456'}
    assert translate({'category_id': ''}) .get('category') is None and translate({'category_id': None}).get('category') is None
    for bad in ('  ', '', 5, []):          # None 等于没给这个键，不算错
        with pytest.raises(ValueError, match='category_keyword 必须是已选择的类目名称'):
            translate({'category_keyword': bad})
    for bad in (True, 1.5, -1, 0, 'abc', '-5', '０１２', '1.5', []):
        with pytest.raises(ValueError, match='category_id 必须是有效的平台类目编号'):
            translate({'category_id': bad})


def test_props_and_skus_must_be_lists_of_objects_and_are_passed_through_untouched():
    props = [{'name': '材质', 'value': '棉'}]
    assert translate({'props': props})['props'] == props
    assert translate({'props': []})['props'] == []
    for bad in ('x', [1], [{'a': 1}, 2], {}):
        with pytest.raises(ValueError, match='props 必须是属性对象列表'):
            translate({'props': bad})
    skus = [{'spec_values': {'颜色分类': '白色'}, 'price': 12, 'stock': 3}]
    assert translate({'skus': skus})['skus'] == skus
    for bad in ('x', [1], {}, [{'a': 1}, 'b']):
        with pytest.raises(ValueError, match='skus 必须是规格对象列表'):
            translate({'skus': bad})


def test_spec_values_are_never_guessed_from_the_sku_name():
    request = translate({'skus': [{'name': '黑色-白色【5双装】+均码(35-40)', 'price': 1}]})
    assert 'spec_values' not in request['skus'][0]


@pytest.mark.parametrize('field,value,message', [
    ('price', 'x', '第1条SKU的price必须是有效数字'), ('price', True, '第1条SKU的price必须是有效数字'),
    ('price', float('nan'), '第1条SKU的price必须是有效数字'), ('price', float('inf'), '第1条SKU的price必须是有效数字'),
    ('price', 10 ** 400, '第1条SKU的price必须是有效数字'),
    ('price', 0, '第1条SKU的price超出有效范围'), ('price', -1, '第1条SKU的price超出有效范围'),
    ('stock', -1, '第1条SKU的stock超出有效范围'), ('stock', 1.5, '第1条SKU的stock超出有效范围'),
    ('stock', 'x', '第1条SKU的stock必须是有效数字'), ('stock', 2 ** 2000, '第1条SKU的stock必须是有效数字'),
])
def test_sku_numbers_are_validated(field, value, message):
    with pytest.raises(ValueError) as caught:
        translate({'skus': [{field: value}]})
    assert str(caught.value) == message


@pytest.mark.parametrize('entry', [{'price': 1, 'stock': 0}, {'price': 0.01, 'stock': 3.0}, {'stock': None, 'price': None}, {}])
def test_valid_or_missing_sku_numbers_pass(entry):
    assert translate({'skus': [dict(entry)]})['skus'] == [entry]


def test_the_error_names_the_sku_that_is_wrong():
    with pytest.raises(ValueError, match='第3条SKU的price'):
        translate({'skus': [{'price': 1}, {'price': 2}, {'price': -3}]})


@pytest.mark.parametrize('bad', ['', '   ', 5, ['x']])
def test_sku_image_source_must_be_text(bad):
    with pytest.raises(ValueError, match='第1条SKU的图片来源无效'):
        translate({'skus': [{'image_path': bad}]})


def test_image_paths_are_only_checked_when_a_record_is_given():
    assert translate({'skus': [{'image_path': 'anything.jpg'}]})['skus'] == [{'image_path': 'anything.jpg'}]


def test_registered_sku_image_is_accepted_and_resolved(product):
    request = translate({'skus': [{'image_path': product.white}, {'image_path': os.path.join('SKU', '黑色.jpg'), 'price': 3}]},
                        record=product.row)
    assert [s['image_path'] for s in request['skus']] == [str(Path(product.white).resolve()), str(Path(product.black).resolve())]
    assert request['skus'][1]['price'] == 3


@pytest.mark.parametrize('which,message', [
    ('other', '第1条SKU图片与当前商品来源不匹配'),            # 在目录里但没登记为这个商品的 SKU
    ('missing', '第1条SKU图片与当前商品来源不匹配'),          # 登记了路径之外的不存在的文件
    ('outside', '商品图片路径超出当前记录目录'),
    ('parent', '商品图片路径超出当前记录目录'),
])
def test_unregistered_or_outside_images_are_refused(product, which, message):
    paths = {'other': product.other, 'missing': str(product.base / 'SKU' / '不存在.jpg'),
             'outside': str(product.base.parent / '商品外.jpg'), 'parent': '../商品外.jpg'}
    with pytest.raises(ValueError, match=message):
        translate({'skus': [{'image_path': paths[which]}]}, record=product.row)


@pytest.mark.parametrize('record,message', [
    (make_row(7, path=''), '当前商品目录不存在，无法确认SKU图片来源'),
    (make_row(7, path='uploads/products/C'), 'Record.path 必须是本地绝对目录路径'),
    (make_row(7, path=str(ROOT / '不存在的商品目录')), '当前商品目录不存在，无法确认SKU图片来源'),
])
def test_record_without_a_usable_directory_cannot_confirm_images(record, message):
    with pytest.raises(ValueError, match=message):
        translate({'skus': [{'image_path': 'x.jpg'}]}, record=record)


@pytest.mark.parametrize('content,message', [
    ('{oops', None),
    (json.dumps({'a': 1}), '当前商品SKU来源记录无效'),
    (json.dumps([1, 2]), '当前商品SKU来源记录无效'),
])
def test_unreadable_sku_records_are_refused(product, content, message):
    row = dict(product.row, content=content)
    if message is None:
        with pytest.raises(ValueError):          # json.JSONDecodeError 是 ValueError 的子类
            translate({'skus': [{'image_path': product.white}]}, record=row)
    else:
        with pytest.raises(ValueError, match=message):
            translate({'skus': [{'image_path': product.white}]}, record=row)


def test_content_given_as_a_list_is_accepted(product):
    row = dict(product.row, content=json.loads(product.row['content']) + [{'name': '无路径'}])
    assert translate({'skus': [{'image_path': product.white}]}, record=row)['skus'][0]['image_path'] == str(Path(product.white).resolve())


# ------------------------------------------------------------------------------------------ 单品 worker
def worker_case(tmp_path, behavior=None, *, logs=None, rows=None, task_extra=None, **service_overrides):
    """一个服务 + 一个待处理的任务 + 替身流水线。返回 (service, pipeline, row)。"""
    pipeline = FakePipeline(behavior)
    service = make_service(
        resolve_data_file=lambda name: tmp_path / name,
        bootstrap_log=(logs.append if logs is not None else (lambda message: None)),
        record_model=make_record_model(rows or {}), **service_overrides,
    )
    service.load_pipeline = lambda: pipeline
    row = make_row(7)
    service.tasks['t'] = dict({'task_id': 't', 'status': 'pending', 'progress': 0, 'steps': [], 'account_profile': ACCOUNT,
                               'message': '任务已创建', 'error': None, 'blockers': []}, **(task_extra or {}))
    return service, pipeline, row


FILL = {'fill_only': True, 'dry_run': False, 'stop_before_submit': True, 'cdp_list_url': URL}


def ok_payload(**extra):
    payload = {'success': True, 'steps': [{'name': 'session', 'status': 'ok'}], 'data': {}, 'error': None, 'blockers': [],
               'dry_run': False, 'stopped_before_submit': True}
    payload.update(extra)
    return payload


def complete_verification():
    return {'complete': True, 'status': 'complete', 'required_field_coverage': {
        'known': True, 'completePage': True, 'scope': WHOLE_FORM_SCOPE, 'rowCount': 3, 'checkedCount': 1,
        'required': [{'label': '宝贝标题', 'hitCount': 1, 'supportedReader': True}],
        'checked': [{'label': '宝贝标题', 'value': '标题'}]}}


def test_task_runs_and_records_the_outcome(tmp_path):
    service, pipeline, row = worker_case(tmp_path, ok_payload())
    service.run_publish_task('t', row, {'record_id': 7}, FILL)
    task = service.tasks['t']
    assert (task['status'], task['progress'], task['publish_confirmed']) == ('succeeded', 100, False)
    assert task['result']['success'] is True and task['steps'] == [{'name': 'session', 'status': 'ok'}]
    assert task['started_at'] and task['finished_at']
    assert pipeline.calls[0].request == {'record_id': 7} and pipeline.calls[0].row is row


def test_the_pipeline_receives_everything_the_ui_chose(tmp_path):
    service, pipeline, row = worker_case(tmp_path, ok_payload())
    service.run_publish_task('t', row, {'record_id': 7}, dict(FILL, listing_mode='定时上架', save_draft=True))
    kwargs = pipeline.calls[0].kwargs
    assert (kwargs['dry_run'], kwargs['stop_before_submit'], kwargs['cdp_list_url'], kwargs['write_artifact']) == (False, True, URL, False)
    assert (kwargs['listing_mode'], kwargs['save_draft'], kwargs['account_profile']) == ('定时上架', True, ACCOUNT)
    assert callable(kwargs['media_preparer']) and callable(kwargs['should_cancel']) and callable(kwargs['progress_callback'])


def test_listing_mode_and_save_draft_default_when_the_caller_omits_them(tmp_path):
    service, pipeline, row = worker_case(tmp_path, ok_payload())
    service.run_publish_task('t', row, {'record_id': 7}, FILL)
    assert (pipeline.calls[0].kwargs['listing_mode'], pipeline.calls[0].kwargs['save_draft']) == ('', False)


@pytest.mark.parametrize('options,source,submit_unlocked', [
    (FILL, 'desktop_form_filling', False),
    (dict(FILL, fill_only=False, stop_before_submit=False), None, True),          # 直接发布：界面确认后一次性放行到提交
    (dict(FILL, fill_only=False, dry_run=True), 'environment', False),           # 校对 / 研究入口：只认环境变量授权（这里没设 = 零写入）
    (dict(FILL, fill_only=False, dry_run=False, stop_before_submit=True), 'environment', False),
])
def test_authorization_is_chosen_by_the_requested_mode_and_never_from_the_request(tmp_path, monkeypatch, options, source, submit_unlocked):
    monkeypatch.delenv('TAOBAO_UPLOAD_ALLOW_WRITE', raising=False)
    monkeypatch.delenv('TAOBAO_UPLOAD_ALLOW_SUBMIT', raising=False)
    service, pipeline, row = worker_case(tmp_path, ok_payload())
    service.run_publish_task('t', row, {'record_id': 7}, options)
    auth = pipeline.calls[0].kwargs['authorization']
    assert auth.submit_unlocked is submit_unlocked
    if source:
        assert auth.source == source
    else:
        assert auth.is_granted('submit_publish')
    if source == 'environment':
        assert auth.granted == frozenset()                # 环境变量没设：什么写入都不授权


def test_environment_authorization_is_used_for_the_research_entry(tmp_path, monkeypatch):
    monkeypatch.setenv('TAOBAO_UPLOAD_ALLOW_WRITE', 'upload_image')
    service, pipeline, row = worker_case(tmp_path, ok_payload())
    service.run_publish_task('t', row, {'record_id': 7}, dict(FILL, fill_only=False, dry_run=True))
    auth = pipeline.calls[0].kwargs['authorization']
    assert auth.is_granted('upload_image') and not auth.is_granted('submit_publish')


@pytest.mark.parametrize('options,payload,message', [
    (FILL, ok_payload(data={'form_verification': complete_verification()}),
     '完整填写与回读已确认，停在提交前，尚未发布'),
    (FILL, ok_payload(data={'form_verification': complete_verification()},
                      steps=[{'name': 'save_draft', 'status': 'ok'}]),
     '完整填写与回读已确认，停在提交前，尚未发布；已在平台保存草稿'),
    (FILL, ok_payload(steps=[{'name': 'save_draft', 'status': 'skipped'}], data={'form_verification': complete_verification()}),
     '完整填写与回读已确认，停在提交前，尚未发布'),                                        # 草稿被跳过：不能说「已保存」
    (FILL, ok_payload(data={'form_verification': {'complete': False, 'status': 'partial'}}),
     '本次填写操作已结束并停在提交前；整页必填尚未确认，不能认定完整填写'),
    (FILL, ok_payload(),
     '本次填写操作已结束并停在提交前；整页必填尚未确认，不能认定完整填写'),
    (FILL, ok_payload(dry_run=True, data={'form_verification': complete_verification()}),
     '本次填写操作已结束并停在提交前；整页必填尚未确认，不能认定完整填写'),               # 回执自称 dry-run：不能认定完整填写
    (FILL, ok_payload(data={'form_verification': {'complete': True, 'status': 'complete'}}),
     '本次填写操作已结束并停在提交前；整页必填尚未确认，不能认定完整填写'),               # 自称完整，但没有整页必填的覆盖证据
    (FILL, ok_payload(data={'form_verification': dict(complete_verification(), status='partial')}),
     '本次填写操作已结束并停在提交前；整页必填尚未确认，不能认定完整填写'),               # complete 为真但状态不是 complete
    (FILL, ok_payload(data={'form_verification': dict(complete_verification(), complete=False)}),
     '本次填写操作已结束并停在提交前；整页必填尚未确认，不能认定完整填写'),               # 状态是 complete 但 complete 不为真
    (FILL, ok_payload(data={'form_verification': dict(
        complete_verification(), required_field_coverage=dict(complete_verification()['required_field_coverage'], completePage=False))}),
     '本次填写操作已结束并停在提交前；整页必填尚未确认，不能认定完整填写'),               # 覆盖证据说整页没读全
    (FILL, ok_payload(stopped_before_submit=False, data={'form_verification': complete_verification()}),
     '本次填写操作已结束并停在提交前；整页必填尚未确认，不能认定完整填写'),
    (dict(FILL, fill_only=False, dry_run=True), ok_payload(), '资料校对完成，未填写或发布商品'),
    (dict(FILL, fill_only=False, stop_before_submit=False), ok_payload(),
     '流水线已完成；是否上架请在卖家中心核对'),
    (dict(FILL, fill_only=False, stop_before_submit=False), ok_payload(steps=[{'name': 'save_draft', 'status': 'ok'}]),
     '流水线已完成；是否上架请在卖家中心核对；已在平台保存草稿'),
])
def test_success_message_never_overstates_what_happened(tmp_path, options, payload, message):
    service, _pipeline, row = worker_case(tmp_path, payload)
    service.run_publish_task('t', row, {'record_id': 7}, options)
    task = service.tasks['t']
    assert task['status'] == 'succeeded' and task['message'] == message
    assert task['publish_confirmed'] is False             # 「流水线跑完了」不等于「商品已上架」


def test_a_cancelled_result_is_cancelled_not_failed(tmp_path):
    payload = {'success': False, 'steps': [], 'error': {'code': 'CANCELLED', 'message': 'x'}, 'blockers': []}
    service, _pipeline, row = worker_case(tmp_path, payload)
    service.run_publish_task('t', row, {'record_id': 7}, FILL)
    assert service.tasks['t']['status'] == 'cancelled'
    assert service.tasks['t']['message'] == '已取消，流水线在阶段边界停止'


def test_a_failed_result_carries_the_reason_and_the_blockers(tmp_path):
    payload = {'success': False, 'steps': [], 'error': {'code': 'FILL', 'message': '填写阶段未通过'}, 'blockers': ['标题为空']}
    service, _pipeline, row = worker_case(tmp_path, payload)
    service.run_publish_task('t', row, {'record_id': 7}, FILL)
    task = service.tasks['t']
    assert (task['status'], task['message'], task['error'], task['blockers']) == ('failed', '填写阶段未通过', '填写阶段未通过', ['标题为空'])


def test_a_failed_result_without_details_still_says_it_failed(tmp_path):
    service, _pipeline, row = worker_case(tmp_path, {'success': False, 'steps': None, 'error': None, 'blockers': None})
    service.run_publish_task('t', row, {'record_id': 7}, FILL)
    task = service.tasks['t']
    assert (task['status'], task['message'], task['blockers']) == ('failed', '流水线未通过', [])


def test_an_exception_in_the_pipeline_fails_the_task_with_its_text(tmp_path, capsys):
    service, _pipeline, row = worker_case(tmp_path, RuntimeError('流水线崩溃'))
    service.run_publish_task('t', row, {'record_id': 7}, FILL)
    task = service.tasks['t']
    assert (task['status'], task['progress'], task['message'], task['error']) == ('failed', 100, '淘宝发布失败', '流水线崩溃')
    assert 'RuntimeError' in capsys.readouterr().err          # 回溯打到 stderr，不是悄悄吞掉


def test_an_unloadable_pipeline_fails_the_task(tmp_path, capsys):
    service, _pipeline, row = worker_case(tmp_path)

    def missing():
        raise ImportError('missing module')
    service.load_pipeline = missing
    service.run_publish_task('t', row, {'record_id': 7}, FILL)
    assert service.tasks['t']['status'] == 'failed' and service.tasks['t']['error'] == 'missing module'


def test_progress_and_cancel_hooks_work_on_the_task_table(tmp_path):
    seen = {}

    def behavior(row, request, kwargs):
        seen['before'] = kwargs['should_cancel']()
        kwargs['progress_callback'](42, '填写中', 'fill', [{'name': 'fill', 'status': 'running'}])
        seen['mid'] = {k: service.tasks['t'][k] for k in ('progress', 'message', 'current_step', 'steps')}
        service.tasks['t']['cancelled'] = True
        seen['after'] = kwargs['should_cancel']()
        return ok_payload()

    service, _pipeline, row = worker_case(tmp_path, behavior)
    service.run_publish_task('t', row, {'record_id': 7}, FILL)
    assert seen['before'] is False and seen['after'] is True
    assert seen['mid'] == {'progress': 42, 'message': '填写中', 'current_step': 'fill', 'steps': [{'name': 'fill', 'status': 'running'}]}


def test_hooks_are_quiet_when_the_task_has_disappeared(tmp_path):
    def behavior(row, request, kwargs):
        service.tasks.clear()
        kwargs['progress_callback'](80, '收尾', 'verify', [])
        assert kwargs['should_cancel']() is False
        return ok_payload()

    service, _pipeline, row = worker_case(tmp_path, behavior)
    service.run_publish_task('t', row, {'record_id': 7}, FILL)
    assert service.tasks == {}


def test_a_task_that_was_never_registered_is_ignored(tmp_path):
    service, pipeline, row = worker_case(tmp_path, ok_payload())
    service.run_publish_task('ghost', row, {'record_id': 7}, FILL)
    assert pipeline.calls == [] and 'ghost' not in service.tasks


def test_a_vanished_task_does_not_turn_a_crash_into_an_error(tmp_path):
    def behavior(row, request, kwargs):
        service.tasks.clear()
        raise RuntimeError('崩溃')

    service, _pipeline, row = worker_case(tmp_path, behavior)
    service.run_publish_task('t', row, {'record_id': 7}, FILL)
    assert service.tasks == {}


@pytest.mark.parametrize('before', [None, 'dom', 'protocol'])
def test_media_route_is_protocol_only_while_the_task_runs(tmp_path, monkeypatch, before):
    """进程级环境变量：运行期间默认走协议路线，但任务结束必须原样还原，否则会泄漏给后面的任务。"""
    if before:
        monkeypatch.setenv('TAOBAO_MEDIA_ROUTE', before)
    during = []
    service, _pipeline, row = worker_case(
        tmp_path, lambda r, q, k: (during.append(os.environ.get('TAOBAO_MEDIA_ROUTE')), ok_payload())[1])
    service.run_publish_task('t', row, {'record_id': 7}, FILL)
    assert during == [before or 'protocol']
    assert os.environ.get('TAOBAO_MEDIA_ROUTE') == before


@pytest.mark.parametrize('behavior', [RuntimeError('x'), {'success': False, 'steps': []}])
def test_media_route_is_restored_on_failures_too(tmp_path, behavior):
    service, _pipeline, row = worker_case(tmp_path, behavior)
    service.run_publish_task('t', row, {'record_id': 7}, FILL)
    assert 'TAOBAO_MEDIA_ROUTE' not in os.environ


def test_media_route_is_restored_when_the_task_is_missing(tmp_path):
    service, _pipeline, row = worker_case(tmp_path)
    service.run_publish_task('ghost', row, {'record_id': 7}, FILL)
    assert 'TAOBAO_MEDIA_ROUTE' not in os.environ


def observation(product, name='白色.jpg'):
    return {'path': str(product.base / 'SKU' / name), 'role': 'sku', 'name': name, 'sha256': 'a' * 64,
            'status': 'located', 'folder_path': ['袜子']}


def test_media_observations_are_saved_under_the_task_account(tmp_path, product):
    service, _pipeline, _row = worker_case(tmp_path, ok_payload(data={'media_observations': [observation(product)]}))
    service.run_publish_task('t', product.row, {'record_id': 7}, FILL)
    files = list((tmp_path / 'media_catalog').glob('*.json'))
    assert len(files) == 1
    entries = json.loads(files[0].read_text(encoding='utf-8'))['entries']
    assert [(e['path'], e['role'], e['name']) for e in entries] == [('SKU/白色.jpg', 'sku', '白色.jpg')]
    assert 'media_record_error' not in service.tasks['t']['result']['data']


def test_a_failure_to_record_media_never_discards_the_platform_result(tmp_path, product):
    """图片目录记录只是本地索引：它写不进去，不能把「平台侧已经全做完」的任务报成失败。"""
    logs = []
    service, _pipeline, _row = worker_case(
        tmp_path, ok_payload(data={'media_observations': [{'path': 'x'}]}), logs=logs)
    service.run_publish_task('t', product.row, {'record_id': 7}, FILL)
    task = service.tasks['t']
    assert task['status'] == 'succeeded'
    assert task['message'].endswith("；图片目录记录保存失败（KeyError）：'role'")
    assert task['result']['data']['media_record_error'] == "图片目录记录保存失败（KeyError）：'role'"
    assert logs == ["图片目录记录保存失败（KeyError）：'role'"]


def test_the_account_for_the_media_record_is_the_one_bound_to_the_task(tmp_path, product):
    service, _pipeline, _row = worker_case(
        tmp_path, ok_payload(data={'media_observations': [observation(product)]}), task_extra={'account_profile': ''})
    service.run_publish_task('t', product.row, {'record_id': 7}, FILL)
    assert service.tasks['t']['message'].endswith('；图片目录记录保存失败（ValueError）：保存素材记录需要任务所绑定的账户及图片清单')


# ------------------------------------------------------------------------------------------ 批量 worker
def batch_case(tmp_path, behavior=None, rows=None, **overrides):
    rows = rows if rows is not None else {1: make_row(1), 2: make_row(2)}
    service, pipeline, _row = worker_case(tmp_path, behavior if behavior is not None else ok_payload(), rows=rows, **overrides)
    # 与路由创建的批量任务同形（``started_at`` / ``finished_at`` 一开始是 None）
    service.tasks['t'].update(record_name='批量', record_id=None, started_at=None, finished_at=None)
    return service, pipeline


BATCH = {'dry_run': True, 'stop_before_submit': True, 'cdp_list_url': URL, 'account_profile': ACCOUNT}


def test_batch_runs_every_pending_record_in_id_order(tmp_path):
    service, pipeline = batch_case(tmp_path, rows={2: make_row(2), 1: make_row(1), 3: make_row(3, status=1)})
    service.run_publish_batch_task('t', BATCH)
    assert [c.row['id'] for c in pipeline.calls] == [1, 2]
    task = service.tasks['t']
    assert (task['status'], task['progress'], task['publish_confirmed']) == ('succeeded', 100, False)
    assert task['message'] == '批量发布完成：2/2 成功'
    assert task['result']['succeeded'] == 2 and task['result']['failed'] == 0 and task['result']['total'] == 2
    assert [(r['record_id'], r['success']) for r in task['result']['results']] == [(1, True), (2, True)]


def test_batch_builds_each_request_from_the_record(tmp_path):
    service, pipeline = batch_case(tmp_path)
    service.run_publish_batch_task('t', BATCH)
    first = pipeline.calls[0]
    assert first.request['record_id'] == 1 and first.request['record_name'] == '商品1'
    assert first.request['title'] == '标题1' and first.request['category'] == {'search_keyword': '中筒袜'}
    assert [s['price'] for s in first.request['skus']] == [12.5, 13.0] and first.request['sku_mode'] == 'custom'
    assert first.kwargs['account_profile'] == ACCOUNT and first.kwargs['cdp_list_url'] == URL
    assert (first.kwargs['dry_run'], first.kwargs['stop_before_submit'], first.kwargs['write_artifact']) == (True, True, False)
    assert (first.kwargs['listing_mode'], first.kwargs['save_draft']) == ('', False)


def test_batch_uses_the_same_authorization_rules_as_a_single_task(tmp_path, monkeypatch):
    monkeypatch.delenv('TAOBAO_UPLOAD_ALLOW_WRITE', raising=False)
    monkeypatch.delenv('TAOBAO_UPLOAD_ALLOW_SUBMIT', raising=False)
    for options, source in ((dict(BATCH, fill_only=True), 'desktop_form_filling'), (dict(BATCH, dry_run=False, stop_before_submit=False), None),
                            (BATCH, 'environment')):
        service, pipeline = batch_case(tmp_path)
        service.run_publish_batch_task('t', options)
        auth = pipeline.calls[0].kwargs['authorization']
        if source:
            assert auth.source == source
        else:
            assert auth.submit_unlocked is True


def test_batch_passes_listing_mode_and_save_draft_when_given(tmp_path):
    service, pipeline = batch_case(tmp_path)
    service.run_publish_batch_task('t', dict(BATCH, listing_mode='放入仓库', save_draft=True))
    assert (pipeline.calls[0].kwargs['listing_mode'], pipeline.calls[0].kwargs['save_draft']) == ('放入仓库', True)


@pytest.mark.parametrize('failing,status,message', [
    ({2}, 'succeeded', '批量发布结束：1 成功 / 1 失败 / 共 2'),
    ({1, 2}, 'failed', '批量发布结束：0 成功 / 2 失败 / 共 2'),
])
def test_batch_outcome_counts_successes_and_failures(tmp_path, failing, status, message):
    def behavior(row, request, kwargs):
        if row['id'] in failing:
            return {'success': False, 'steps': [], 'error': {'message': '这条没过'}}
        return ok_payload()

    service, _pipeline = batch_case(tmp_path, behavior)
    service.run_publish_batch_task('t', BATCH)
    task = service.tasks['t']
    assert (task['status'], task['message']) == (status, message)
    assert [r['error'] for r in task['result']['results']] == ['这条没过' if i in failing else '' for i in (1, 2)]
    assert task['result']['success'] is False


def test_an_exception_on_one_record_is_recorded_and_the_batch_continues(tmp_path):
    def behavior(row, request, kwargs):
        if row['id'] == 1:
            raise RuntimeError('崩')
        return ok_payload()

    service, pipeline = batch_case(tmp_path, behavior)
    service.run_publish_batch_task('t', BATCH)
    task = service.tasks['t']
    results = task['result']['results']
    assert [(r['record_id'], r['success'], r['error']) for r in results] == [(1, False, 'RuntimeError: 崩'), (2, True, '')]
    assert len(pipeline.calls) == 2
    # 异常也算一次失败：计数、状态、文案都要反映出来，不能只在明细里有
    assert (task['result']['succeeded'], task['result']['failed'], task['result']['success']) == (1, 1, False)
    assert (task['status'], task['message']) == ('succeeded', '批量发布结束：1 成功 / 1 失败 / 共 2')


def test_batch_with_no_pending_records_fails_cleanly(tmp_path):
    service, pipeline = batch_case(tmp_path, rows={1: make_row(1, status=1)})
    service.run_publish_batch_task('t', BATCH)
    assert service.tasks['t']['status'] == 'failed' and service.tasks['t']['message'] == '没有待上传的商品'
    assert pipeline.calls == [] and service.tasks['t']['finished_at']


def test_cancel_is_noticed_before_the_next_record_starts(tmp_path):
    def behavior(row, request, kwargs):
        service.tasks['t']['cancelled'] = True          # 第一条跑着的时候收到取消
        return ok_payload()

    service, pipeline = batch_case(tmp_path, behavior)
    service.run_publish_batch_task('t', BATCH)
    task = service.tasks['t']
    assert (task['status'], task['message']) == ('cancelled', '批量发布已取消（1/2）')
    assert [c.row['id'] for c in pipeline.calls] == [1] and task['finished_at']


def test_a_batch_that_was_cancelled_before_it_started_does_nothing(tmp_path):
    service, pipeline = batch_case(tmp_path)
    service.tasks['t']['cancelled'] = True
    service.run_publish_batch_task('t', BATCH)
    assert pipeline.calls == [] and service.tasks['t']['message'] == '批量发布已取消（0/2）'


def test_batch_progress_message_names_the_record_being_processed(tmp_path):
    messages = []

    def behavior(row, request, kwargs):
        messages.append((service.tasks['t']['progress'], service.tasks['t']['message'], service.tasks['t']['current_step']))
        return ok_payload()

    service, _pipeline = batch_case(tmp_path, behavior)
    service.run_publish_batch_task('t', BATCH)
    assert messages == [(0, '批量发布 1/2：商品1', 'batch'), (50, '批量发布 2/2：商品2', 'batch')]


def test_a_vanished_batch_task_is_ignored(tmp_path):
    service, pipeline = batch_case(tmp_path)
    service.tasks.clear()
    service.run_publish_batch_task('t', BATCH)
    assert service.tasks == {} and len(pipeline.calls) == 2           # 记录仍然会逐条处理，但收尾时找不到任务就安静返回


def untranslatable(record_id, path=''):
    """翻译这条记录时会抛 ``ValueError``：商品目录不存在（或不是绝对路径），而 SKU 又带着图片，没法确认图片来源。"""
    return make_row(record_id, path=path, content=json.dumps([{'name': '黄色', 'price': 8, 'path': 'x.jpg'}], ensure_ascii=False))


def test_batch_is_running_with_a_start_time_while_it_works(tmp_path):
    """批量 worker 以前从头到尾不改状态，任务一直是 ``pending``——界面和别的接口分不出「排队中」和「在跑」。"""
    seen = []

    def behavior(row, request, kwargs):
        task = service.tasks['t']
        seen.append((task['status'], bool(task['started_at']), task['finished_at']))
        return ok_payload()

    service, _pipeline = batch_case(tmp_path, behavior)
    assert (service.tasks['t']['status'], service.tasks['t']['started_at']) == ('pending', None)
    service.run_publish_batch_task('t', BATCH)
    assert seen == [('running', True, None), ('running', True, None)]
    task = service.tasks['t']
    assert task['status'] == 'succeeded' and task['started_at'] and task['finished_at']


@pytest.mark.parametrize('path,reason', [
    ('', '当前商品目录不存在，无法确认SKU图片来源'),
    ('uploads/products/C', 'Record.path 必须是本地绝对目录路径'),
])
def test_a_record_that_cannot_be_translated_fails_alone_and_the_batch_continues(tmp_path, path, reason):
    """商品目录不存在 / 不是绝对路径时，翻译会抛 ``ValueError``。

    它以前在 ``try`` 之外：工作线程直接崩溃，任务永远停在「进行中」，而 ``pending`` 算「在跑」，
    会一直挡住账户切换、保存这个商品和单品发布（直到重启 Sidecar）。现在只让这一条记录失败。
    """
    rows = {1: make_row(1), 2: untranslatable(2, path), 3: make_row(3)}
    service, pipeline = batch_case(tmp_path, rows=rows)
    service.run_publish_batch_task('t', BATCH)                          # 不抛
    assert [c.row['id'] for c in pipeline.calls] == [1, 3]              # 坏的那条没进流水线，后面的照常处理
    task = service.tasks['t']
    assert [(r['record_id'], r['name'], r['success'], r['error']) for r in task['result']['results']] == [
        (1, '商品1', True, ''), (2, '商品2', False, 'ValueError: %s' % reason), (3, '商品3', True, '')]
    result = task['result']
    assert (result['succeeded'], result['failed'], result['total'], result['success']) == (2, 1, 3, False)
    assert (task['status'], task['progress'], task['message']) == ('succeeded', 100, '批量发布结束：2 成功 / 1 失败 / 共 3')
    assert task['finished_at'] and task['publish_confirmed'] is False


def test_a_batch_where_no_record_can_be_translated_ends_failed_without_touching_the_pipeline(tmp_path):
    service, pipeline = batch_case(tmp_path, rows={1: untranslatable(1), 2: untranslatable(2)})
    service.run_publish_batch_task('t', BATCH)
    task = service.tasks['t']
    assert pipeline.calls == []
    assert (task['status'], task['message']) == ('failed', '批量发布结束：0 成功 / 2 失败 / 共 2')
    assert [r['error'] for r in task['result']['results']] == ['ValueError: 当前商品目录不存在，无法确认SKU图片来源'] * 2
    assert task['finished_at']


def test_any_exception_while_translating_a_record_is_recorded_with_its_type_name(tmp_path):
    """不只是 ``ValueError``：翻译抛什么都记成这一条的失败（类型名 + 消息），不能只拦住已知的那一种。"""
    service, pipeline = batch_case(tmp_path)

    def broken(product, record=None):
        if record['id'] == 1:
            raise OSError('读不了商品目录')
        return {'title': '翻译后'}
    service.product_request_payload = broken
    service.run_publish_batch_task('t', BATCH)
    results = service.tasks['t']['result']['results']
    assert [(r['record_id'], r['success'], r['error']) for r in results] == [(1, False, 'OSError: 读不了商品目录'), (2, True, '')]
    assert [c.row['id'] for c in pipeline.calls] == [2]
    assert pipeline.calls[0].request == {'title': '翻译后', 'record_id': 2, 'record_name': '商品2'}


def test_a_failure_outside_the_record_loop_still_ends_the_task(tmp_path, capsys):
    """读不出待发布列表这类、不属于任何一条记录的失败：线程不能带着任务一起死。

    任务以 ``failed`` 结束，原因写在任务上，回溯打到 stderr（和单品 worker 同一口径）。
    """
    service, pipeline = batch_case(tmp_path)

    def broken_select():
        raise RuntimeError('商品库打不开')
    service._record_model.select = broken_select
    service.run_publish_batch_task('t', BATCH)                          # 不抛
    task = service.tasks['t']
    assert (task['status'], task['progress'], task['message'], task['error']) == ('failed', 100, '淘宝批量发布失败', '商品库打不开')
    assert task['finished_at'] and task['started_at'] and pipeline.calls == []
    assert 'RuntimeError' in capsys.readouterr().err


def fail_second(row, request, kwargs):
    if row['id'] == 2:
        return {'success': False, 'steps': [], 'error': {'message': '这条没过'}}
    return ok_payload()


@pytest.mark.parametrize('rows,behavior,expected', [
    (None, ok_payload(), 'succeeded'),                                          # 全部成功
    (None, fail_second, 'succeeded'),                                           # 一条失败
    (None, {'success': False, 'steps': []}, 'failed'),                          # 全部失败
    (None, RuntimeError('崩'), 'failed'),                                       # 流水线抛异常
    ({1: make_row(1, status=1)}, ok_payload(), 'failed'),                       # 没有待发布的记录
    ({1: untranslatable(1)}, ok_payload(), 'failed'),                           # 唯一一条翻译失败
], ids=['all-ok', 'one-failed', 'all-failed', 'pipeline-raises', 'no-records', 'untranslatable'])
def test_the_batch_always_ends_in_a_finished_state(tmp_path, rows, behavior, expected):
    """``pending`` / ``running`` 都算「在跑」：它们会挡住账户切换、保存该商品和单品发布。所以不管怎么结束，
    任务都必须落在 succeeded / failed / cancelled 之一，并有结束时间。"""
    service, _pipeline = batch_case(tmp_path, behavior, rows=rows)
    service.run_publish_batch_task('t', BATCH)
    task = service.tasks['t']
    assert task['status'] == expected and task['status'] not in ('pending', 'running')
    assert task['finished_at']


# ------------------------------------------------------------------------------------------ 批量 worker 与图片路线环境变量
# ``TAOBAO_MEDIA_ROUTE`` 是**进程级**环境变量：批量 worker 和单品 worker 一样会临时把它设成 ``protocol``，结束时必须还原，
# 否则 ``protocol`` 会一直留在进程里，泄漏给后面读它的代码（别的研究入口、别的任务、别的测试）。
# 批量 worker 曾经漏了这一步——它是照单品 worker 抄的，``finally`` 没抄过来（「5. 未决问题」第 25 条）。
@pytest.mark.parametrize('before', [None, 'dom', 'protocol'])
def test_batch_media_route_is_protocol_only_while_the_batch_runs(tmp_path, monkeypatch, before):
    if before:
        monkeypatch.setenv('TAOBAO_MEDIA_ROUTE', before)             # 调用方显式配的优先，worker 不覆盖也不改动它
    during = []
    service, _pipeline = batch_case(
        tmp_path, lambda r, q, k: (during.append(os.environ.get('TAOBAO_MEDIA_ROUTE')), ok_payload())[1])
    service.run_publish_batch_task('t', BATCH)
    assert during == [before or 'protocol'] * 2                      # 两条记录，每条运行期间都是协议路线（或显式配的那个）
    assert os.environ.get('TAOBAO_MEDIA_ROUTE') == before


def break_authorization(monkeypatch):
    """让批量 worker 在设好环境变量**之后**、记录循环**之外**抛异常：授权对象构造失败（校对入口读环境授权）。"""

    def broken(cls, *_args, **_kwargs):
        raise RuntimeError('授权对象构造失败')
    monkeypatch.setattr(WriteAuthorization, 'from_environment', classmethod(broken))


BATCH_ENDINGS = {
    'all-ok': dict(),
    'one-failed': dict(behavior=fail_second),
    'all-failed': dict(behavior={'success': False, 'steps': []}),
    'pipeline-raises': dict(behavior=RuntimeError('崩')),
    'untranslatable': dict(rows={1: untranslatable(1)}),
    'cancelled': dict(cancel=True),
    'outside-the-loop': dict(break_authorization=True),
    'no-records': dict(rows={1: make_row(1, status=1)}),               # 还没走到设环境变量那一步就结束了：同样不能留下东西
}


@pytest.mark.parametrize('ending', sorted(BATCH_ENDINGS))
def test_batch_media_route_is_restored_however_the_batch_ends(tmp_path, monkeypatch, ending):
    plan = BATCH_ENDINGS[ending]
    service, _pipeline = batch_case(tmp_path, plan.get('behavior'), rows=plan.get('rows'))
    if plan.get('cancel'):
        service.tasks['t']['cancelled'] = True                       # 设好环境变量之后、第一条记录开始前发现取消
    if plan.get('break_authorization'):
        break_authorization(monkeypatch)
    service.run_publish_batch_task('t', BATCH)
    assert 'TAOBAO_MEDIA_ROUTE' not in os.environ
    assert service.tasks['t']['status'] in ('succeeded', 'failed', 'cancelled')


def test_a_batch_leaves_nothing_behind_for_the_single_task_that_follows(tmp_path):
    """批量跑完接着跑单品：单品 worker 看到的「之前的值」必须还是没设置，跑完同样没设置。"""
    service, _pipeline = batch_case(tmp_path)
    service.run_publish_batch_task('t', BATCH)
    service.tasks['single'] = {'task_id': 'single', 'status': 'pending', 'progress': 0, 'steps': [], 'account_profile': ACCOUNT,
                               'message': '任务已创建', 'error': None, 'blockers': []}
    service.run_publish_task('single', make_row(7), {'record_id': 7}, FILL)
    assert service.tasks['single']['status'] == 'succeeded'
    assert 'TAOBAO_MEDIA_ROUTE' not in os.environ

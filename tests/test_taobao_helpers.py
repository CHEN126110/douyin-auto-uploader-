# -*- coding: utf-8 -*-
"""淘宝发布的纯函数（``src/sidecar/taobao_helpers.py``）：发布开关的解析与校验、从商品记录构造请求载荷。

这些是「默认值写反就静默出错」的不变量：dry-run / 停在提交前 / 保存草稿的默认值、布尔开关必须真的是布尔、
上架方式只能取页面上实测存在的选项。它们是纯函数，不需要 Flask、账户或数据库，直接调用验证。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from sidecar_test_support import make_record_model  # noqa: E402
from src.sidecar.taobao_helpers import (  # noqa: E402
    TAOBAO_LISTING_MODES, _CATEGORY_LABELS, _parse_taobao_publish_options, _taobao_product_from_record,
)

KNOWN_KEYS = {
    'record_id': 1, 'platform': 'taobao', 'account_profile': 'x', 'dry_run': False, 'stop_before_submit': True,
    'product': {}, 'fill_only': True, 'expected_record_revision': 'r', 'listing_mode': '放入仓库', 'save_draft': True,
}


# ------------------------------------------------------------------------------------------ 发布开关解析
def test_defaults_are_the_safe_ones():
    options, error = _parse_taobao_publish_options({})
    assert error is None
    assert options == {'dry_run': True, 'stop_before_submit': True, 'fill_only': False, 'save_draft': False, 'listing_mode': ''}


@pytest.mark.parametrize('data', [None, [], 'x', 5])
def test_non_object_requests_are_refused(data):
    assert _parse_taobao_publish_options(data) == (None, '请求必须是 JSON 对象')


@pytest.mark.parametrize('extra', [{'未知参数': 1}, {'allow_write': True}, {'output_base': 'C:/x'}])
def test_unknown_parameters_are_refused(extra):
    assert _parse_taobao_publish_options(dict(KNOWN_KEYS, **extra)) == (None, '请求包含不支持的参数')


def test_every_known_parameter_is_accepted():
    options, error = _parse_taobao_publish_options(dict(KNOWN_KEYS))
    assert error is None
    assert options == {'dry_run': False, 'stop_before_submit': True, 'fill_only': True, 'save_draft': True, 'listing_mode': '放入仓库'}


@pytest.mark.parametrize('flag', ['dry_run', 'stop_before_submit', 'fill_only', 'save_draft'])
@pytest.mark.parametrize('bad', ['false', 'true', 0, 1, None, [], {}])
def test_switches_must_be_real_booleans(flag, bad):
    """字符串 ``"false"`` 在 Python 里是真值，不校验就会绕过 dry-run / save_draft 的默认值。"""
    assert _parse_taobao_publish_options({flag: bad}) == (None, '%s 必须是布尔值' % flag)


@pytest.mark.parametrize('flag,value', [('dry_run', False), ('stop_before_submit', False), ('fill_only', True), ('save_draft', True)])
def test_explicit_booleans_are_passed_through(flag, value):
    options, error = _parse_taobao_publish_options({flag: value})
    assert error is None and options[flag] is value


def test_listing_mode_is_restricted_to_the_measured_options():
    assert TAOBAO_LISTING_MODES == ('', '立刻上架', '定时上架', '放入仓库')
    for mode in TAOBAO_LISTING_MODES:
        assert _parse_taobao_publish_options({'listing_mode': mode})[0]['listing_mode'] == mode
    # 空值与 None 都是「用流水线默认值」，**不是**立刻上架
    for blank in (None, '', '   '):
        assert _parse_taobao_publish_options({'listing_mode': blank})[0]['listing_mode'] == ''
    assert _parse_taobao_publish_options({})[0]['listing_mode'] != '立刻上架'
    # 首尾空白会被去掉再比对
    assert _parse_taobao_publish_options({'listing_mode': ' 定时上架 '})[0]['listing_mode'] == '定时上架'


@pytest.mark.parametrize('bad', ['上架到月球', 'immediately', '立刻 上架'])
def test_other_listing_modes_are_refused_with_the_valid_choices_named(bad):
    options, error = _parse_taobao_publish_options({'listing_mode': bad})
    assert options is None
    assert error == 'listing_mode 只能是 立刻上架、定时上架、放入仓库 之一'


@pytest.mark.parametrize('bad', [3, True, ['立刻上架'], {}])
def test_listing_mode_must_be_text(bad):
    assert _parse_taobao_publish_options({'listing_mode': bad}) == (None, 'listing_mode 必须是字符串')


def test_boolean_check_runs_before_listing_mode_check():
    """两个都不合法时，先报开关（调用方按这个顺序改）。"""
    assert _parse_taobao_publish_options({'dry_run': 'no', 'listing_mode': 3}) == (None, 'dry_run 必须是布尔值')


# ------------------------------------------------------------------------------------------ 从商品记录构造载荷
def record(**overrides):
    fields = dict(content=json.dumps([{'name': '白色', 'price': 12.5, 'path': ' SKU/白色.jpg '}]), clazz=2, repo=3,
                  title=' 标题 ', name=' 商品名 ')
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_product_is_built_from_the_record():
    assert _taobao_product_from_record(record()) == {
        'title': '标题', 'category_keyword': '中筒袜', 'sku_mode': 'custom', 'outer_id': '商品名',
        'skus': [{'spec_values': {'颜色分类': '白色'}, 'price': 12.5, 'stock': 3, 'image_path': 'SKU/白色.jpg'}],
    }


def test_product_preserves_auxiliary_specs_but_current_name_owns_primary_spec():
    row = record(content=json.dumps([{'name': '白色', 'price': 12.5, 'path': 'SKU/白色.jpg',
        'remark': '独立备注', 'spec_values': {'颜色分类': '旧名字', '双数': '2', '袜筒高度': '中筒'}}]))
    sku = _taobao_product_from_record(row)['skus'][0]
    assert sku['spec_values'] == {'颜色分类': '白色', '双数': '2', '袜筒高度': '中筒'}


@pytest.mark.parametrize('clazz,keyword', [(0, '船袜'), (1, '短袜'), (2, '中筒袜'), (3, '长筒袜'), (4, '袜套'), (9, ''), (-1, '')])
def test_integer_categories_map_to_their_labels(clazz, keyword):
    assert _CATEGORY_LABELS[0] == '船袜'
    assert _taobao_product_from_record(record(clazz=clazz))['category_keyword'] == keyword


@pytest.mark.parametrize('clazz,keyword', [(' 短袜 ', '短袜'), ('中筒袜', '中筒袜'), ('', ''), (None, ''),
                                           ('2号', '2号'), ('中筒袜2', '中筒袜2'),    # 只有「全是数字」才是类目代码
                                           ('²', '²'), ('２', '２')])                # 非 ASCII 的数字不是代码（``'²'.isdigit()`` 为真，``int('²')`` 却会抛）
def test_text_categories_are_used_as_they_are(clazz, keyword):
    assert _taobao_product_from_record(record(clazz=clazz))['category_keyword'] == keyword


@pytest.mark.parametrize('clazz,keyword', [('0', '船袜'), ('1', '短袜'), ('2', '中筒袜'), ('3', '长筒袜'), ('4', '袜套'),
                                           (' 2 ', '中筒袜'), ('\t3\n', '长筒袜')])    # 去掉首尾空白后全是数字
def test_digit_string_categories_map_like_integers(clazz, keyword):
    """``Record.clazz`` 是 ``CharField``：库里读出来是 ``'2'`` 而不是 ``2``，两者是同一个类目代码。

    以前只有整数才映射，批量发布给流水线的类目关键词因此是 ``'2'``（不是任何淘宝类目）。
    """
    assert _taobao_product_from_record(record(clazz=clazz))['category_keyword'] == keyword


@pytest.mark.parametrize('clazz', ['5', '9', '10', ' 7 ', '99999999999999999999'])
def test_unknown_digit_string_categories_give_no_keyword_instead_of_the_code(clazz):
    """认不得的代码不猜，也不能把 ``'9'`` 当关键词去搜类目——和整数 9 一样给空串。"""
    assert _taobao_product_from_record(record(clazz=clazz))['category_keyword'] == ''


def test_digit_strings_and_integers_agree_on_every_code():
    """同一个代码，字符串和整数两条路径必须给出同一个结果（认得的和不认得的都一样）。"""
    for code in range(0, 12):
        assert (_taobao_product_from_record(record(clazz=str(code)))['category_keyword']
                == _taobao_product_from_record(record(clazz=code))['category_keyword'])


def test_a_category_read_back_from_the_real_table_is_mapped(tmp_path):
    """根因：整数 2 存进 ``CharField`` 再读出来是 ``'2'``。用真实的 peewee 模型走一遍存取，不靠手写假件去猜读出来是什么类型。"""
    Record, database = make_record_model(tmp_path / 'record.db')
    try:
        created = Record.create(name='袜子', title='标题', clazz=2, repo=3)
        stored = Record.get_by_id(created.id)
        assert stored.clazz == '2'
        assert _taobao_product_from_record(stored)['category_keyword'] == '中筒袜'
        stored_text = Record.get_by_id(Record.create(name='袜子二', title='标题', clazz='短袜').id)
        assert _taobao_product_from_record(stored_text)['category_keyword'] == '短袜'
        stored_none = Record.get_by_id(Record.create(name='袜子三', title='标题', clazz=None).id)
        assert _taobao_product_from_record(stored_none)['category_keyword'] == ''
    finally:
        database.close()


def test_title_falls_back_to_the_name():
    assert _taobao_product_from_record(record(title=None))['title'] == '商品名'
    assert _taobao_product_from_record(record(title='  '))['title'] == '商品名'
    assert _taobao_product_from_record(record(title='', name='  '))['title'] == ''


@pytest.mark.parametrize('repo,stock', [(None, 0), (0, 0), (7, 7), ('3', 3)])
def test_stock_comes_from_repo(repo, stock):
    assert _taobao_product_from_record(record(repo=repo))['skus'][0]['stock'] == stock


@pytest.mark.parametrize('content', ['not json', '{oops', None, '', json.dumps({'a': 1}) + 'x'])
def test_unreadable_content_means_no_skus_instead_of_a_crash(content):
    assert _taobao_product_from_record(record(content=content))['skus'] == []


def test_invalid_sku_rows_are_skipped_not_guessed():
    content = json.dumps([
        1, 'text', None, {'name': '', 'price': 1}, {'name': '   ', 'price': 1}, {'name': None, 'price': 1},
        {'name': '零价', 'price': 0}, {'name': '负价', 'price': -2}, {'name': '坏价', 'price': 'x'}, {'name': '空价', 'price': None},
        {'name': '缺价'}, {'name': '字符价', 'price': '2.5', 'path': None}, {'name': '带图', 'price': 3, 'path': ' a.jpg '},
        {'name': '空图', 'price': 4, 'path': '   '},
    ], ensure_ascii=False)
    skus = _taobao_product_from_record(record(content=content, repo=1))['skus']
    assert [(s['spec_values']['颜色分类'], s['price'], s.get('image_path')) for s in skus] == [
        ('字符价', 2.5, None), ('带图', 3.0, 'a.jpg'), ('空图', 4.0, None)]
    assert all(s['stock'] == 1 for s in skus)


def test_a_non_list_content_means_no_skus():
    # JSON 合法但不是列表：逐项遍历的是字典的键（字符串），全部被跳过
    assert _taobao_product_from_record(record(content=json.dumps({'name': '白', 'price': 1})))['skus'] == []

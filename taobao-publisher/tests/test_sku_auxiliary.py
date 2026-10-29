# -*- coding: utf-8 -*-
"""SKU 动态附加规格列：主规格身份、缺失拦截、真实 DOM 写入与回读。"""
import pytest

from test_candidate_form_adapters import browser, fixture_contracts  # noqa: F401
from taobao_publish import page, required_fields, stages
from taobao_publish.models import CategoryRef, PublishItem, SkuEntry
from taobao_publish.sku_auxiliary import fill_sku_auxiliary_values


def _item(pairs=('1','2')):
    return PublishItem(record_id=1,record_name='测试袜',sku_mode='custom',
        category=CategoryRef(search_keyword='中筒袜'),
        skus=[SkuEntry(spec_values={'颜色分类':name,'双数':pair},price=9.9,stock=10)
              for name,pair in zip(('灰色','粉色'),pairs)])


def _install(browser, names=('灰色','粉色'), confirm=True, columns=None):
    if columns is None:
        columns = [
            {'name':'袜筒高度','type':'combobox','required':True},
            {'name':'双数','type':'text','required':True,'placeholder':'规格'},
        ]
    browser.evaluate('window.skuAuxiliaryColumns='+__import__('json').dumps(columns))
    browser.evaluate('''window.skuAuxiliaryOptions={袜筒高度:['船袜','短筒','中筒','长筒']};''')
    if confirm:
        for index,name in enumerate(names):
            if index:
                browser.evaluate('addRow()')
            browser.evaluate('document.querySelectorAll("#names li")[%d].dataset.name=%s;'
                             'document.querySelectorAll("#names input")[%d].value=%s;'
                             % (index,__import__('json').dumps(name),index,__import__('json').dumps(name)))
    browser.evaluate('''(() => {
      const wrap=document.createElement('div');wrap.className='sell-component-info-wrapper-wrap';
      const label=document.createElement('div');label.className='sell-component-info-wrapper-label';
      label.textContent='销售规格*';wrap.append(label);
      const table=document.getElementById('skuTable');table.parentNode.insertBefore(wrap,table);
      wrap.append(table);
    })()''')
    if confirm:
        browser.evaluate('confirmRows()')


def _cells(browser):
    return browser.evaluate(r'''Array.from(document.querySelectorAll('tr.sku-table-row')).map(row=>{
      const cells=row.querySelectorAll('td');
      return {spec:cells[0].textContent,height:cells[4].querySelector('input').value,
        pairs:cells[5].querySelector('input').value};
    })''')


def test_required_auxiliary_values_are_filled_by_primary_spec_not_row_index(browser):
    _install(browser)
    result = fill_sku_auxiliary_values(browser,_item())
    assert result['filled_cells'] == 4
    assert result['required_columns'] == ['袜筒高度','双数']
    assert _cells(browser) == [
        {'spec':'粉色','height':'中筒','pairs':'2'},
        {'spec':'灰色','height':'中筒','pairs':'1'},
    ]
    for index in range(2):
        page.set_sku_row_numbers(browser,index,price='9.90',stock='10',wait=0)
    coverage = required_fields.read(browser)
    sales = next(row for row in coverage['required'] if row['label']=='销售规格')
    assert sales['filled'] is True and sales['valid'] is True
    expected = next(row for row in stages.expected_field_values(stages.PipelineContext(item=_item()))
                    if row['kind']=='sku_specs')
    assert expected['value'] == '2 行：灰色｜粉色'
    assert stages._read_expected_value(browser,page,expected) == expected['value']


def test_missing_pair_count_is_rejected_before_any_cell_is_written(browser):
    _install(browser,names=('灰色',))
    with pytest.raises(page.PageError,match='双数'):
        fill_sku_auxiliary_values(browser,_item(pairs=('',)))
    cells = _cells(browser)
    assert cells[0]['height'] == '' and cells[0]['pairs'] == ''
    coverage = required_fields.read(browser)
    sales = next(row for row in coverage['required'] if row['label']=='销售规格')
    assert sales['filled'] is False and sales['valid'] is False


def test_custom_stage_fills_auxiliary_columns_and_price_stock(browser,fixture_contracts):
    _install(browser, confirm=False)
    item = _item(pairs=('1','2'))
    outcome = stages.stage_fill_skus(stages.PipelineContext(
        item=item,contracts=fixture_contracts))
    assert outcome.ok,outcome.summary
    assert outcome.data['auxiliary']['filled_cells'] == 4
    rows = browser.evaluate('''Array.from(document.querySelectorAll('tr.sku-table-row')).map(row=>{
      const cells=row.querySelectorAll('td');return [cells[2].querySelector('input').value,
        cells[3].querySelector('input').value];})''')
    assert rows == [['9.90','10'],['9.90','10']]


def test_measurement_pair_uses_trusted_quantity_and_unit_input(browser):
    _install(browser,names=('灰色',),columns=[
        {'name':'双数','type':'measurement','required':True,'placeholder':'规格'},
    ])
    result = fill_sku_auxiliary_values(browser,_item(pairs=('1',)))
    assert result['filled_cells'] == 1
    assert browser.evaluate('document.querySelector("tr.sku-table-row td:nth-child(5) input").value') == '1双'
    assert browser.evaluate('''Array.from(document.querySelectorAll(
      '.sell-common-sale-props-multi-expression-overlay')).filter(el=>el.getBoundingClientRect().height>0).length''') == 0

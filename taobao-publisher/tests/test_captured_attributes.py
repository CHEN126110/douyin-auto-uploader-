"""真实 DOM 语义的离线验证；页面、产品和选项全为本地合成数据。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_candidate_form_adapters import browser, fixture_contracts
from test_offline_pipeline_handoff import handoff, save_case, save_and_start
from taobao_publish import captured_attributes as attributes, attribute_fill, page
from taobao_publish.local_source import local_product_from_record
from taobao_publish.mapping import build_publish_item
from taobao_publish.models import PublishItem, PropEntry


def data(**values):
    return {'version': 1, 'source': attributes.SOURCE, 'status': 'captured',
            'attributes': [{'name': key, 'value': value} for key, value in values.items()]}


def product(**values):
    return PublishItem(1, '本地模型', captured_attributes=data(**values))


def model(browser, html):
    browser.evaluate('document.body.innerHTML=' + json.dumps(html))
    browser.evaluate('window.events=0;document.body.addEventListener("input",()=>window.events++)')


def row(name, control, required=True):
    return '<div class="sell-catProp-item-common"><label class="' + ('required' if required else '') + '">' + name + '</label>' + control + '</div>'


def test_capture_reads_only_visible_product_parameter_structures(browser):
    model(browser, '<table aria-label="订单信息"><tr><td>适用季节</td><td>错误数据</td></tr></table>'
        '<section><h2>商品参数</h2><dl><dt>适用季节</dt><dd>四季</dd></dl>'
        '<table><tr><td>适用性别</td><td>女</td></tr></table></section>'
        '<table aria-label="商品参数" hidden><tr><td>适用季节</td><td>隐藏数据</td></tr></table>')
    browser.evaluate('window.__ICE_APP_CONTEXT__={params:{trackParams:{适用季节:"不应采集"}}}')
    captured=attributes.capture(SimpleNamespace(run_js=lambda js: browser.evaluate(js.removeprefix('return '))))
    assert captured==attributes.normalize(data(适用季节='四季',适用性别='女'))
    assert browser.evaluate('window.events')==0


def test_unknown_structure_is_not_found_and_old_tracking_dictionary_is_rejected(browser):
    model(browser,'<div>适用季节：四季</div>')
    assert browser.evaluate(attributes.read_expression())['status']=='not_found'
    with pytest.raises(ValueError):
        attributes.normalize({'trackParams': {'适用季节':'四季'}})
    assert attributes.normalize(None) is None
    with pytest.raises(ValueError,match='没有返回'):
        attributes.capture(SimpleNamespace(run_js=lambda js: None))


@pytest.mark.parametrize('raw', [
    {'version': True, 'source': attributes.SOURCE, 'status':'captured','attributes':[]},
    {'version': 1, 'source': 'trackParams', 'status':'captured','attributes':[{'name':'适用季节','value':'四季'}]},
    {'version': 1, 'source': attributes.SOURCE, 'status':'not_found','attributes':[{'name':'适用季节','value':'四季'}]},
    {'version': 1, 'source': attributes.SOURCE, 'status':'captured','attributes':[{'name':'适用季节','value':['四季']}]},
])
def test_invalid_envelopes_are_not_silently_ignored(raw):
    with pytest.raises(ValueError): attributes.normalize(raw)


def test_duplicate_values_dedupe_but_conflicting_values_fail():
    raw=data(适用季节='四季')
    raw['attributes']*=2
    assert len(attributes.normalize(raw)['attributes'])==1
    raw['attributes'][1]={'name':'适用季节','value':'冬季'}
    with pytest.raises(ValueError,match='冲突'): attributes.normalize(raw)


def test_local_projection_and_mapping_keep_the_captured_values():
    raw=data(适用季节='四季')
    local=local_product_from_record({'id':1,'name':'本地模型','content':'[]','captured_attributes':attributes.dumps(raw)})
    built=build_publish_item(local,{})
    assert built.item.captured_attributes==attributes.normalize(raw)
    assert built.item.props==[]  # 必须在当前页面确认是否为目标字段后才成为填写意图。


@pytest.mark.parametrize('control', ['<input>', '<textarea></textarea>',
    '<select><option value="">请选择</option><option value="season-all">四季</option></select>'])
def test_required_native_controls_are_written_and_read_back(browser,control):
    model(browser,row('适用季节',control))
    item=product(适用季节='四季')
    results,skipped=attribute_fill.fill(browser,item)
    assert not skipped and results[0]['read_back']=='四季'
    assert item.props[0].value_name=='四季'
    assert browser.evaluate('window.events')==1


def test_source_cannot_override_explicit_values_or_brand_stock_and_logistics(browser):
    model(browser,row('适用季节','<input value="用户设置">')+row('品牌','<input value="无品牌">'))
    item=product(适用季节='四季',品牌='采集品牌',总库存='500',发货时间='24小时')
    item.props=[PropEntry('适用季节','用户设置')]
    results,skipped=attribute_fill.fill(browser,item)
    assert not results and len(skipped)==4
    assert browser.evaluate('window.events')==0


def test_optional_and_prefix_labels_are_not_automatic_matches(browser):
    model(browser,row('适用季节说明','<input>')+row('适用性别','<input>',required=False))
    results,skipped=attribute_fill.fill(browser,product(适用季节='四季',适用性别='女'))
    assert not results and len(skipped)==2
    assert browser.evaluate('window.events')==0


@pytest.mark.parametrize('controls', [
    '<select><option value="">请选择</option><option value="winter">冬季</option></select>',
    '<input readonly>', '<input disabled>', '<input type=radio>', '<input><input>',
    '<input oninput="this.value=\'未接受\'">',
])
def test_unsupported_controls_and_unaccepted_values_are_explicit_failures(browser,controls):
    model(browser,row('适用季节',controls))
    item=product(适用季节='四季')
    with pytest.raises(page.PageError): attribute_fill.fill(browser,item)
    assert not item.props


def test_same_name_in_multiple_profiles_is_rejected_before_any_write(browser):
    model(browser,row('适用季节','<input>')+'<div class="sell-component-info-wrapper-wrap">'
          '<span class="sell-component-info-wrapper-label">适用季节</span><input required></div>')
    with pytest.raises(page.PageError,match='不唯一'): attribute_fill.fill(browser,product(适用季节='四季'))
    assert browser.evaluate('window.events')==0


def test_final_readback_detects_a_value_changed_after_filling(browser):
    model(browser,row('适用季节','<input>'))
    item=product(适用季节='四季')
    attribute_fill.fill(browser,item)
    browser.evaluate('document.querySelector("input").value="冬季"')
    from taobao_publish.stages import expected_field_values, _read_expected_value, PipelineContext
    expected=next(entry for entry in expected_field_values(PipelineContext(item=item)) if entry['label']=='适用季节')
    assert expected['value']=='四季'
    assert _read_expected_value(browser,page,expected)=='冬季'


def test_changed_row_is_not_replaced_by_a_prefix_match_during_combobox_actions(browser,monkeypatch):
    model(browser,row('适用季节','<div class="next-select" onclick="document.querySelector(\'label\').textContent=\'适用季节说明\'">'
        '<input role="combobox" readonly></div>'))
    monkeypatch.setattr(page.time,'sleep',lambda seconds:None)
    item=product(适用季节='四季')
    with pytest.raises(page.CandidateNotFound,match='目标已改变'):
        attribute_fill.fill(browser,item)
    assert item.props==[]


def test_combobox_uses_actual_exact_option_and_does_not_touch_prefix_row(browser,monkeypatch):
    model(browser,'<div class="sell-component-info-wrapper-wrap"><span class="sell-component-info-wrapper-label">适用季节说明</span>'
          '<input onclick="window.wrong=true"></div>'+row('适用季节',
          '<div class="next-select" onclick="document.querySelector(\'.sell-o-select-options\').hidden=false">'
          '<input role="combobox" readonly><div class="next-select-values"></div></div>')+
          '<div class="sell-o-select-options next-select-popup-wrap" hidden><input><div class="options-item" onclick="'
          'document.querySelector(\'.next-select-values\').textContent=\'四季\';this.parentElement.hidden=true">'
          '<span class="sell-o-info">四季</span></div></div>')
    monkeypatch.setattr(page.time,'sleep',lambda seconds:None)
    results,_=attribute_fill.fill(browser,product(适用季节='四季'))
    assert results[0]['read_back']=='四季'
    assert browser.evaluate('Boolean(window.wrong)') is False


@pytest.mark.parametrize('control', ['<input>', '<textarea></textarea>',
    '<select><option value="">请选择</option><option value="all">四季</option></select>'])
def test_http_save_start_and_pipeline_fill_capture_attribute_without_ui_props(handoff,control):
    handoff.case.ns['_load_capture_attributes']=lambda:attributes
    handoff.case.db['captured_attributes']=attributes.dumps(data(适用季节='四季'))
    handoff.browser.evaluate('document.body.insertAdjacentHTML("afterbegin",'+json.dumps(row('适用季节',control))+')')
    _,task=save_and_start(handoff)
    assert task['status']=='succeeded',task['error']
    assert attribute_fill.read(handoff.browser,'适用季节')=='四季'
    assert handoff.browser.evaluate('window.submitCalls + window.draftCalls')==0
    step=next(step for step in task['steps'] if step['name']=='fill_props')
    assert '适用季节' in step['summary']
    from taobao_publish.sanitize import assert_clean
    artifact={'scope':'local_synthetic_browser_only','live_platform_tested':False,
        'source':data(适用季节='四季'), 'result':task['result'], 'submitted_or_saved_draft':False,
        'test_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    assert_clean(artifact)
    (Path(__file__).resolve().parents[1]/'outputs/captured_attribute_pipeline_handoff.json').write_text(
        json.dumps(artifact,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

# -*- coding: utf-8 -*-
"""属性区以外必填控件的本地原生DOM反例；不读取真实浏览器。"""
import json
from unittest.mock import Mock

import pytest

from test_candidate_form_adapters import browser, fixture_contracts
from test_offline_pipeline_handoff import handoff, save_case, save_and_start
from test_category_first_pipeline import install_model
from test_runtime_native_controls import use_native_detail
from taobao_publish.contracts import load_contracts
from taobao_publish import page, required_fields


def model(browser, contents):
    # ⚠️ 裸 DOM 里的 `input[type=radio|checkbox]` **尺寸是 0**，而读取器的可见性守卫
    #    要求 `width>0 && height>0`——不给尺寸就会被过滤成"行内没有控件"，
    #    于是报「控件类型尚未支持」而不是「未填写」（实测踩过）。
    #    真实页面上这些控件当然是有尺寸的，所以这里补最小样式让夹具**如实渲染**。
    browser.evaluate(
        'var s=document.getElementById("__fixture_size__");'
        'if(!s){s=document.createElement("style");s.id="__fixture_size__";document.head.append(s);}'
        's.textContent="input[type=radio],input[type=checkbox]{width:14px;height:14px}'
        'input,select,textarea,button{min-height:20px;min-width:40px}"')
    browser.evaluate('document.body.innerHTML='+json.dumps(contents))
    browser.evaluate('window.formEvents=0;document.body.addEventListener("input",()=>window.formEvents++);'
                     'document.body.addEventListener("invalid",()=>window.formEvents++,true)')


def row(label, controls, marker='*'):
    return '<div class="sell-component-info-wrapper-wrap"><div class="sell-component-info-wrapper-label-wrap">' \
        '<span>'+marker+'</span><span class="sell-component-info-wrapper-label">'+label+'</span></div>'+controls+'</div>'


def report(browser):
    value=page.read_required_form(browser)
    assert value['known'] is True
    assert value['completePage'] is False
    assert browser.evaluate('window.formEvents') == 0
    return value, required_fields.blockers(value)


def test_sibling_required_marker_catches_empty_title_outside_property_area(browser):
    model(browser,row('宝贝标题','<input>'))
    value, errors=report(browser)
    assert value['required'][0]['label']=='宝贝标题'
    assert [(e.code,e.field) for e in errors]==[('REQUIRED_FIELD_MISSING','宝贝标题')]


def test_native_required_marker_is_detected_without_an_asterisk(browser):
    model(browser,row('商家编码','<input required>',marker=''))
    _,errors=report(browser)
    assert errors[0].field=='商家编码'


def test_minimum_constraint_is_checked_without_dispatching_invalid_event(browser):
    model(browser,row('一口价','<input type=number min=1 value=0 required>'))
    _,errors=report(browser)
    assert errors[0].code=='READBACK_MISMATCH'


def test_required_native_select_placeholder_is_empty(browser):
    model(browser,row('物流选项','<select required><option value="">请选择</option><option value="x">明确选项</option></select>'))
    _,errors=report(browser)
    assert errors[0].code=='REQUIRED_FIELD_MISSING'
    browser.evaluate('document.querySelector("select").value="x"')
    _,errors=report(browser)
    assert not errors


def test_one_checked_radio_group_does_not_cover_another_empty_group(browser):
    model(browser,row('发货时间','<input type=radio name=mode checked><input type=radio name=time><input type=radio name=time>'))
    _,errors=report(browser)
    assert errors[0].field=='发货时间'
    browser.evaluate('document.querySelector("input[name=time]").checked=true')
    browser.evaluate('document.querySelectorAll("input[name=time]")[1].disabled=true')
    _,errors=report(browser)
    assert not errors


def test_combobox_placeholder_is_not_a_selection(browser):
    model(browser,row('运费模板','<input role=combobox readonly><div class="next-select-values"><span class="next-select-placeholder">请选择</span></div>'))
    _,errors=report(browser)
    assert errors[0].code=='REQUIRED_FIELD_MISSING'


def test_typed_combobox_search_text_is_not_proof_of_selection(browser):
    model(browser,row('运费模板','<input role=combobox value="搜索关键字">'))
    _,errors=report(browser)
    assert errors[0].code=='UNSUPPORTED_REQUIRED_FIELD'


def test_empty_main_slots_and_placeholder_image_do_not_satisfy_required(browser):
    model(browser,row('1:1主图','<div class="sell-component-material-item-view"><img src=""></div>'))
    _,errors=report(browser)
    assert errors[0].field=='1:1主图' and errors[0].code=='REQUIRED_FIELD_MISSING'
    browser.evaluate('document.querySelector("img").src="https://img.example.invalid/selected.jpg"')
    _,errors=report(browser)
    assert not errors


def test_rich_text_empty_markup_is_not_content(browser):
    model(browser,row('宝贝详情','<div contenteditable="true" style="height:40px"><p><br></p></div>'))
    _,errors=report(browser)
    assert errors[0].code=='REQUIRED_FIELD_MISSING'
    browser.evaluate('document.querySelector("[contenteditable]").innerHTML="<p>已提供的商品说明</p>"')
    _,errors=report(browser)
    assert not errors


def test_composite_material_field_is_reported_as_unsupported(browser):
    model(browser,row('材质成分','<button>添加材质成分</button>'))
    _,errors=report(browser)
    assert errors[0].field=='材质成分' and errors[0].code=='UNSUPPORTED_REQUIRED_FIELD'


def test_child_property_controls_are_not_misread_as_the_outer_row(browser):
    child='<div class="sell-catProp-item-common"><label class="required">品牌</label><input value="已有品牌"></div>'
    model(browser,row('商品属性',child,marker=''))
    value,errors=report(browser)
    assert value['required']==[] and not errors


def test_property_native_required_attribute_is_not_lost_when_label_has_no_class(browser):
    child='<div class="sell-catProp-item-common"><label>新属性</label><input required></div>'
    model(browser,row('商品属性',child,marker=''))
    _,errors=report(browser)
    assert [(e.field,e.code) for e in errors]==[('新属性','REQUIRED_FIELD_MISSING')]


def test_required_sku_table_uses_its_existing_row_structure(browser):
    sku='<div class="sell-sku-table-wrapper-new"><table><tr class="sku-table-row"><td>黑色</td><td></td><td><input value="29.8"></td><td><input value="100"></td></tr></table></div>'
    model(browser,row('销售规格',sku))
    value,errors=report(browser)
    assert not errors and value['required'][0]['reader']=='sku_table'
    browser.evaluate('document.querySelectorAll("input")[1].value=""')
    _,errors=report(browser)
    assert errors[0].field=='销售规格' and errors[0].code=='REQUIRED_FIELD_MISSING'


def test_unknown_visible_required_control_is_a_coverage_gap(browser):
    model(browser,row('宝贝标题','<input value="有效标题">')+'<input required>')
    value,errors=report(browser)
    assert value['unownedRequiredCount']==1
    assert errors[0].code=='UNSUPPORTED_REQUIRED_FIELD'


def test_reader_reports_presence_without_exporting_field_text(browser):
    model(browser,row('已提供信息','<input value="不应落入回执的具体内容">'))
    value,errors=report(browser)
    assert not errors and '不应落入回执' not in json.dumps(value,ensure_ascii=False)


def test_duplicate_labels_are_rejected_but_disabled_native_values_remain_readable(browser):
    model(browser,row('标题','<input value="A">')+row('标题','<input value="B">')+row('另一个字段','<input disabled value="值">'))
    _,errors=report(browser)
    assert [e.code for e in errors]==['READBACK_UNREADABLE','READBACK_UNREADABLE']
    model(browser,row('计算字段','<input disabled>'))
    _,errors=report(browser)
    assert errors[0].code=='REQUIRED_FIELD_MISSING'


@pytest.mark.parametrize('invalid',[None,{}, {'known':True,'completePage':True}])
def test_malformed_required_form_is_not_an_empty_success(invalid):
    client=Mock();client.evaluate.return_value=invalid
    facts=page.read_required_form(client)
    assert facts['known'] is False
    assert required_fields.blockers(facts)[0].code=='EVIDENCE_INSUFFICIENT'


@pytest.mark.parametrize('selected',[False,True])
def test_real_worker_checks_required_logistics_outside_property_area(handoff,monkeypatch,selected):
    install_model(handoff,load_contracts(),monkeypatch)
    use_native_detail(handoff.browser)
    # ⚠️ `setupCategoryModel` 把原有行 `display:none` 藏起来；读取器**会查 `display`**
    # （对的：隐藏区块不该算当前必填项），所以隐藏的旧行本不该被算上。
    #
    # 但 `当前类目` 那个必填行是**展示型**的（不是输入控件），模型页里它是空壳。
    # 真实页面迁到填写页后这一行**本来就有类目路径文本**——这里如实补上，
    # 免得把"夹具没写内容"当成"页面上没填"（实测报「当前类目 实际值为空」）。
    handoff.browser.evaluate(
        'Array.from(document.querySelectorAll(".sell-component-info-wrapper-wrap")).forEach(r=>{'
        'var l=r.querySelector(".sell-component-info-wrapper-label");'
        'if(l&&(l.textContent||"").replace(/[*＊\\s]/g,"")==="当前类目"'
        '&&!r.querySelector(".model-category-path")){'
        'var d=document.createElement("div");d.className="model-category-path";'
        'd.textContent="女士内衣/男士内衣/家居服>中筒袜";r.appendChild(d);} })')
    choices='<input type=radio name=delivery '+('checked' if selected else '')+'><input type=radio name=delivery>'
    markup=row('发货时间',choices)
    handoff.browser.evaluate('document.body.insertAdjacentHTML("beforeend",'+json.dumps(markup)+')')
    _,task=save_and_start(handoff)
    if selected:
        assert task['status']=='succeeded',task['error']
        assert task['result']['data']['form_verification']['status']=='partial'
    else:
        assert task['status']=='failed'
        assert task['result']['stage']=='readback'
        assert any(b['field']=='发货时间' and b['code']=='REQUIRED_FIELD_MISSING' for b in task['result']['blockers'])
        assert '发货时间' in task['error'] and '未填写或未选择' in task['error']
    facts=task['result']['data']['form_verification']['visible_form_requirements']
    assert facts['known'] is True and facts['completePage'] is False
    shipping=next(entry for entry in facts['required'] if entry['label']=='发货时间')
    assert shipping['filled'] is selected
    assert handoff.browser.evaluate('window.submitCalls+window.draftCalls')==0
    assert handoff.browser.evaluate('document.querySelector("input[name=delivery]").checked') is selected
    from pathlib import Path
    import hashlib
    from taobao_publish.sanitize import assert_clean
    artifact={'scope':'isolated_native_required_controls_and_real_http_worker',
        'live_platform_tested':False,'upload_server_simulated':True,'selected_logistics':selected,
        'model_submit_calls':0,'model_draft_calls':0,'result':task['result'],'error':task['error'],
        'test_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    assert_clean(artifact)
    filename='required_form_pipeline_'+('selected' if selected else 'missing')+'.json'
    (Path(__file__).resolve().parents[1]/'outputs'/filename).write_text(
        json.dumps(artifact,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

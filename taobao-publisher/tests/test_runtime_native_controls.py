# -*- coding: utf-8 -*-
"""生产候选配置通过当前DOM验证后填写；仅使用独立人工页面。"""
from dataclasses import replace
import json

import pytest

from test_candidate_form_adapters import browser, item, fixture_contracts, prepare_in_fixture
from test_category_first_pipeline import install_model
from test_offline_pipeline_handoff import handoff, save_case, save_and_start
from taobao_publish import form_adapters, page, stages
from taobao_publish.constants import STAGE_ORDER
from taobao_publish.contracts import load_contracts, SelectorContract


def use_native_detail(browser):
    browser.evaluate('''const old=document.querySelector('textarea');
      const editor=document.createElement('div');editor.contentEditable='true';
      editor.setAttribute('role','textbox');editor.style.cssText='width:600px;min-height:200px';
      old.replaceWith(editor);''')


def test_current_contract_can_run_all_fill_stages_with_supported_native_controls(handoff, monkeypatch):
    contracts = load_contracts()
    assert contracts.selectors.get('detail.editor').evidence_level == 'candidate'
    assert contracts.selectors.get('sku.custom_input').evidence_level == 'candidate'
    install_model(handoff, contracts, monkeypatch)
    use_native_detail(handoff.browser)
    handoff.browser.evaluate("""const add=window.addCard;window.addCard=(name,url)=>{
      add(name,url);const card=document.querySelector('#gallery').lastElementChild;
      card.className='PicList_pic_background__runtime card';card.querySelector('img').removeAttribute('alt');
    };""")
    _, task = save_and_start(handoff)
    assert task['status'] == 'succeeded', task['error']
    # ⚠️ 阶段数**不要硬编码**（加一个阶段就要改一堆测试）。
    # 离线跑到 `readback` 就停（停在提交前），所以断言"跑的正是 STAGE_ORDER 去掉 submit"。
    ran = [step['name'] for step in task['steps']]
    assert ran == [name for name in STAGE_ORDER if name != 'submit'], ran
    # `save_draft` **默认 skipped**（未显式请求保存草稿），其余都必须是 ok。
    assert all(step['status'] in ('ok', 'skipped') for step in task['steps']), task['steps']
    others = [step['status'] for step in task['steps'] if step['name'] != 'save_draft']
    assert others == ['ok'] * len(others), task['steps']
    assert [s['name'] for s in task['steps']].index('fill_skus') < [s['name'] for s in task['steps']].index('fill_detail')
    assert len(handoff.uploads) == 5
    assert len(page.read_sku_row_numbers(handoff.browser)) == 2
    assert handoff.browser.evaluate("document.querySelector('[contenteditable=true]').querySelectorAll('img').length") == 2
    assert task['result']['data']['form_verification']['status'] == 'partial'
    assert task['result']['stopped_before_submit'] is True
    assert handoff.browser.evaluate('window.submitCalls + window.draftCalls') == 0
    assert load_contracts().selectors.get('detail.editor').evidence_level == 'candidate'
    from pathlib import Path
    import hashlib
    from taobao_publish.sanitize import assert_clean
    artifact = {'scope':'current_contract_with_isolated_native_dom_and_real_http_worker',
        'live_platform_tested':False, 'browser_protocol':'file:', 'upload_server_simulated':True,
        'model_upload_count':len(handoff.uploads), 'model_sku_count':2, 'model_detail_count':2,
        'model_submit_calls':0, 'model_draft_calls':0, 'result':task['result'],
        'test_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    assert_clean(artifact)
    (Path(__file__).resolve().parents[1]/'outputs/runtime_native_pipeline_handoff.json').write_text(
        json.dumps(artifact,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def test_existing_draft_is_preserved_before_switching_sku_mode(browser, item, monkeypatch):
    receipts = prepare_in_fixture(browser, item, load_contracts(), monkeypatch)
    browser.evaluate('''document.querySelector('#names input').value='用户已有规格';
      window.modeClicks=0;document.querySelector('.select-mode label').addEventListener('click',()=>window.modeClicks++);''')
    with pytest.raises(page.PageError, match='规格抽屉已有内容'):
        form_adapters.create_custom_skus(browser, item, load_contracts(), receipts)
    assert browser.evaluate('window.modeClicks') == 0
    assert browser.evaluate("document.querySelector('#names input').value") == '用户已有规格'


def test_add_button_cannot_submit_a_form(browser, item, monkeypatch):
    receipts = prepare_in_fixture(browser, item, load_contracts(), monkeypatch)
    browser.evaluate('''const button=document.querySelector('button.add'),form=document.createElement('form');
      button.before(form);form.append(button);button.type='submit';window.badSubmitCalls=0;
      form.onsubmit=e=>{e.preventDefault();window.badSubmitCalls++};''')
    with pytest.raises(page.PageError, match='可能提交表单'):
        form_adapters.create_custom_skus(browser, item, load_contracts(), receipts)
    assert browser.evaluate('window.badSubmitCalls + window.submitCalls + window.draftCalls') == 0
    assert browser.evaluate("document.querySelectorAll('#names li').length") == 1


def test_unconfirmed_textarea_is_not_treated_as_an_html_editor(browser, item, monkeypatch):
    receipts = prepare_in_fixture(browser, item, load_contracts(), monkeypatch)
    with pytest.raises(page.PageError, match='文本输入模式'):
        form_adapters.fill_detail(browser, item, load_contracts(), receipts)
    assert browser.evaluate('document.querySelector("textarea").value') == ''


@pytest.mark.parametrize('level', ['unknown', 'rejected'])
def test_unsupported_evidence_still_stops_before_opening_page(item, monkeypatch, level):
    contracts = load_contracts()
    payload = json.loads(json.dumps(contracts.selectors._payload))
    for entry in payload['selectors']:
        if entry['key'] == 'sku.custom_mode':
            entry['evidence'] = {'level': level, 'source': 'LOCAL_NEGATIVE_MODEL'}
    contracts = replace(contracts, selectors=SelectorContract(payload))
    def no_open(*args, **kwargs):
        raise AssertionError('未知/已否定控件不能开始操作')
    monkeypatch.setattr(stages, '_open_publish_page', no_open)
    outcome = stages.stage_fill_skus(stages.PipelineContext(item=item, dry_run=False, contracts=contracts))
    assert not outcome.ok and outcome.error_code == 'EVIDENCE_INSUFFICIENT'
    assert [blocker.field for blocker in outcome.blockers] == ['sku.custom_mode']


@pytest.mark.parametrize('stage', ['fill_skus', 'fill_detail'])
def test_runtime_control_declaration_cannot_be_omitted(item, monkeypatch, stage):
    from unittest.mock import Mock
    handler = stages.STAGE_HANDLERS[stage]
    monkeypatch.setitem(stages.STAGE_HANDLERS, stage, replace(handler, runtime_selector_keys=()))
    opener = Mock(side_effect=AssertionError('缺少声明不能开始操作'))
    monkeypatch.setattr(stages, '_open_publish_page', opener)
    outcome = handler.run(stages.PipelineContext(item=item, dry_run=False, contracts=load_contracts()))
    assert not outcome.ok and outcome.error_code == 'CONTRACT_INVALID'
    assert outcome.blockers
    opener.assert_not_called()


def test_platform_sku_length_limit_is_not_bypassed_or_truncated(browser, item, monkeypatch):
    receipts = prepare_in_fixture(browser, item, load_contracts(), monkeypatch)
    browser.evaluate("document.querySelector('#names input').maxLength=3")
    with pytest.raises(page.PageError, match='长度限制'):
        form_adapters.create_custom_skus(browser, item, load_contracts(), receipts)
    assert browser.evaluate("document.querySelector('#names input').value") == ''


def test_sku_image_button_cannot_submit_a_form(browser, item, monkeypatch):
    """图片落点若是「会提交表单的按钮」，必须拒绝点击。

    真实平台上落点是 `div.sell-color-option-image-upload`（不是 button，E-237），
    但**守卫不能依赖这一点**——所以这里把它换成 `type=submit` 的 button 并放进
    form，验证守卫照样拦下来、且**没有真的提交**。
    """

    receipts = prepare_in_fixture(browser, item, load_contracts(), monkeypatch)
    browser.evaluate("""const slot=document.querySelector('#names .sell-color-option-image-upload');
      const button=document.createElement('button');
      button.className='sell-color-option-image-upload';
      button.textContent='添加图片';
      const form=document.createElement('form');
      slot.before(form);form.append(button);button.type='submit';window.badSubmitCalls=0;
      form.onsubmit=e=>{e.preventDefault();window.badSubmitCalls++};""")
    # 会提交表单的落点**任何一个守卫拦下来都算通过**：
    #   * `image_slot_not_unique`——两个候选（真实 div + 注入的 submit 按钮）不唯一；
    #   * `image_slot_may_submit`——唯一但落在 form 里且 type 不是 button。
    # 关键是**没有真的提交**（下面那条断言）。
    with pytest.raises(page.PageError, match='image_slot_not_unique|image_slot_may_submit|图片落点'):
        form_adapters.create_custom_skus(browser, item, load_contracts(), receipts)
    assert browser.evaluate('window.badSubmitCalls + window.submitCalls + window.draftCalls') == 0

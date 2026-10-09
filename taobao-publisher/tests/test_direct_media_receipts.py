"""凭上传回执直达素材：本地合成浏览器，不连接用户账户。"""
from dataclasses import replace
import json
from unittest.mock import Mock

import pytest
from test_candidate_form_adapters import browser, item, fixture_contracts
from test_prepared_media_manifest import prepared_case
from test_uploaded_media_subdirectories import grouped_gallery
from test_listing_skeleton_gate import LAZY_CLEAR_TREE_JS
from taobao_publish import form_adapters as adapters, media_library as library, page, stages


def test_target_present_without_observed_list_change_does_not_navigate_away(browser):
    grouped_gallery(browser,'123')
    browser.evaluate('''window.cardsByFolder={'主图':[{name:'主图_01.jpg',url:'https://img.example.invalid/main.jpg'}]};
        window.currentFolder='主图';renderFolder();
        document.querySelectorAll('[aria-selected]').forEach(el=>el.removeAttribute('aria-selected'));
        Array.from(document.querySelectorAll('[role=treeitem]')).find(el=>el.getAttribute('aria-label')==='主图').setAttribute('aria-selected','true');''')
    previous=library._listing_signature(browser.evaluate(library._LISTING_STATE_EXPRESSION))
    receipt={'picture_id':'0000000001','url':'https://img.example.invalid/main.jpg'}
    state=library.wait_listing_settled(browser,context_id=None,change_from=previous,
                                       timeout=0.5,expected_images=[receipt])
    assert state['cards']==1
    for _ in range(3):
        library.open_directory(browser,['123','主图'],context_id=None,expected_images=[receipt])
    assert browser.evaluate('window.directoryClicks') == []


def test_wrong_id_url_pair_fails_before_selection_and_requery(browser,monkeypatch):
    grouped_gallery(browser,'123')
    browser.evaluate("addCard('图01.jpg','https://img.example.invalid/wrong.jpg')")
    recover=Mock(side_effect=AssertionError('身份不符不能靠来回切目录掩盖'))
    monkeypatch.setattr(library,'retrigger_listing',recover)
    with pytest.raises(page.FieldMismatchError,match='本批上传回执不一致'):
        library.pick_media_by_id_with_requery(browser,['0000000001'],context_id=None,wait=0,
            expected_urls={'0000000001':'https://img.example.invalid/expected.jpg'})
    assert browser.evaluate('window.selectCalls')==0
    recover.assert_not_called()


def test_expected_target_waits_for_delayed_folder_without_using_stale_card(browser):
    browser.evaluate(LAZY_CLEAR_TREE_JS)
    library.open_directory(browser,['123','主图'],context_id=None,
        expected_images=[{'picture_id':'0000000001','url':'https://img.example.invalid/m1.jpg'}])
    assert browser.evaluate('window.directoryClicks') == ['主图']
    assert 'm1.jpg' in browser.evaluate(library._LISTING_STATE_EXPRESSION)['sig']


def test_protocol_preparation_keeps_ids_and_does_not_scan_role_directories(browser,item,fixture_contracts,monkeypatch):
    grouped_gallery(browser,item.record_name)
    browser.evaluate('''Array.from(document.querySelectorAll('[role=treeitem]')).forEach((el,index)=>el.setAttribute('value',String(100+index)))''')
    scan=Mock(side_effect=AssertionError('协议回执完整，不应先扫描全部用途目录'))
    monkeypatch.setattr(library,'find_product_images',scan)
    monkeypatch.setattr(library,'product_directory_tree',scan)
    batch_calls=[]
    def upload(batch,destinations):
        batch_calls.append((batch,destinations))
        return {entry['name']:{'url':'https://img.alicdn.com/imgextra/i1/1/O1CNtest%s.jpg'%index,
                'picture_id':str(1000000000+index),'uploaded_now':index!=0} for index,entry in enumerate(batch)}
    observations=[]
    result=adapters.prepare_media(browser,item,fixture_contracts,context_id=None,
        protocol_upload=upload,observations=observations)
    assert len(batch_calls)==1
    assert browser.evaluate('window.directoryClicks')==[]
    assert {entry['status'] for entry in observations}=={'uploaded_unlocated'}
    assert all(entry['folder_path']==[] for entry in observations)
    assert all(entry['picture_id'] for entries in result.values() for entry in entries)
    assert result['sku'][0]['uploaded_now'] is False
    assert result['sku'][0]['folder_path']==['全部图片',item.record_name,'SKU']
    scan.assert_not_called()


def test_prepared_handoff_keeps_picture_id_without_opening_each_folder(browser,prepared_case,fixture_contracts,monkeypatch):
    _, prepared, item = prepared_case
    prepared=replace(prepared,receipts=tuple(replace(receipt,picture_id=str(2000000000+index))
        for index,receipt in enumerate(prepared.receipts)))
    grouped_gallery(browser,prepared.manifest.folder_name)
    read_all=Mock(side_effect=AssertionError('回执交接不能提前读取所有用途目录'))
    monkeypatch.setattr(library,'read_directory_files',read_all)
    plan=adapters.bind_prepared_media(browser,item,fixture_contracts,prepared,'account-A',context_id=None)
    assert all(entry['picture_id'] for entries in plan.values() for entry in entries)
    assert browser.evaluate('window.directoryClicks')==[]
    read_all.assert_not_called()


def test_main_stage_never_visits_sku_or_detail_folders(browser,prepared_case,monkeypatch):
    root, prepared, item = prepared_case
    # 主图相同文件用于两个槽位；SKU/详情仍有准备回执，但到各自阶段才进入。
    item.images.main=[str(root/'主图/同名.jpg')]*2
    grouped_gallery(browser,prepared.manifest.folder_name)
    groups={}
    for receipt in prepared.receipts:
        groups.setdefault(receipt.folder[-1],[]).append({'name':receipt.name,'url':receipt.url})
    browser.evaluate('window.cardsByFolder='+json.dumps(groups)+';renderFolder();closeGallery()')
    requery=Mock(side_effect=AssertionError('目标图片已在当前目录，不应点走再点回'))
    monkeypatch.setattr(library,'retrigger_listing',requery)
    ctx=stages.PipelineContext(item=item,dry_run=False,prepared_media=prepared,account_profile='account-A')
    result=stages.stage_upload_images(ctx)
    assert result.ok,result.summary
    assert browser.evaluate('window.directoryClicks') == ['主图']
    assert page.read_main_image_slots(browser)['filled']==2
    assert {entry['status'] for entry in ctx.scratch['media_observations'] if entry['role']=='main'} == {'located'}
    assert {entry['status'] for entry in ctx.scratch['media_observations'] if entry['role']=='sku'} == {'uploaded_unlocated'}
    requery.assert_not_called()

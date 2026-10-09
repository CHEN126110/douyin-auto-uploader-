"""用户提供的上传至全部图片、整批完成状态及一次备齐素材的本地验证。"""
import json
from unittest.mock import Mock

import pytest

from test_candidate_form_adapters import browser, item, fixture_contracts
from taobao_publish import page, upload_panel, form_adapters
from taobao_publish.contracts import load_contracts


def render(browser, html):
    browser.evaluate('document.body.innerHTML='+json.dumps(html))


def test_native_destination_is_selected_and_read_back(browser):
    render(browser,'<div class="UploadPanel_uploadDir"><select><option value="old">旧目录</option>'
        '<option value="root">全部图片</option></select></div>')
    receipt=upload_panel.ensure_all_images(browser,context_id=None)
    assert receipt['value']=='全部图片'
    assert browser.evaluate('document.querySelector("select").value')=='root'


def test_combobox_destination_is_changed_through_its_owned_popup(browser):
    render(browser,'<span class="next-select UploadPanel_uploadDir" onclick="document.getElementById(\'dirs\').hidden=false">'
        '<input role="combobox" aria-controls="dirs" readonly><span class="next-select-values">旧目录</span></span>'
        '<div id="dirs" role="listbox" hidden><div role="option" onclick="'
        'document.querySelector(\'.next-select-values\').textContent=\'全部图片\';this.parentElement.hidden=true">全部图片</div></div>')
    assert upload_panel.ensure_all_images(browser,context_id=None)['value']=='全部图片'


def test_existing_all_images_does_not_reopen_dropdown(browser):
    render(browser,'<span class="UploadPanel_uploadDir" onclick="window.badClick=true"><input role="combobox" readonly>'
        '<span class="next-select-values">全部图片</span></span>')
    upload_panel.ensure_all_images(browser,context_id=None)
    assert browser.evaluate('Boolean(window.badClick)') is False


@pytest.mark.parametrize('html',[
    '<input type=file>',
    '<div class="UploadPanel_uploadDir"><select disabled><option>旧目录</option><option>全部图片</option></select></div>',
    '<div class="UploadPanel_uploadDir"><select><option>旧目录</option></select></div>',
    '<div class="UploadPanel_uploadDir"><select><option>旧目录</option><option>全部图片</option><option>全部图片</option></select></div>',
])
def test_unknown_or_unavailable_destination_is_not_an_upload_permission(browser,html):
    render(browser,html)
    with pytest.raises(page.PageError):
        upload_panel.ensure_all_images(browser,context_id=None,timeout=0)


def test_green_files_do_not_override_overall_uploading_state(browser):
    render(browser,'<div class="UploadPanel_uploadPanel"><div class="UploadPanel_fileItem">'
        '<span class="UploadPanel_fileName">one.jpg</span><span class="UploadPanel_fileState"><i class="next-icon-success"></i></span>'
        '</div><div id="busy">25 个文件上传中...</div></div>')
    receipt=page.wait_for_media_upload_queue(browser,['one.jpg'],context_id=None,timeout=0)
    assert receipt['confirmed']==['one.jpg'] and receipt['ok'] is False
    browser.evaluate('document.getElementById("busy").textContent="上传完成"')
    assert page.wait_for_media_upload_queue(browser,['one.jpg'],context_id=None,timeout=0)['ok'] is True


def test_hidden_old_queue_is_not_part_of_active_upload(browser):
    row='<div class="UploadPanel_fileItem"><span class="UploadPanel_fileName">one.jpg</span>'
    render(browser,'<div class="UploadPanel_uploadPanel" hidden>'+row+'<span class="UploadPanel_fileState"><i class="next-icon-error"></i></span></div></div>'
        '<div class="UploadPanel_uploadPanel">'+row+'<span class="UploadPanel_fileState"><i class="next-icon-success"></i></span></div></div>')
    receipt=page.wait_for_media_upload_queue(browser,['one.jpg'],context_id=None,timeout=0)
    assert receipt['ok'] and len(receipt['queue']['items'])==1


def test_finish_targets_the_upload_panel_not_another_finish_button(browser):
    render(browser,'<button onclick="window.wrong=true">完成</button><div class="UploadPanel_uploadPanel">'
        '<button onclick="window.correct=true">完成</button></div>')
    page.click_media_finish(browser,context_id=None,wait=0)
    assert browser.evaluate('Boolean(window.correct)') is True
    assert browser.evaluate('Boolean(window.wrong)') is False


def test_cached_media_is_reused_and_second_preparation_does_not_upload(browser,item,monkeypatch):
    browser.evaluate('openGallery(null,null)')
    # 新命名政策下「复用」= 账本证明同名+同 sha256+同图。DOM 路线在定位成功后
    # 登记账本（待测行为），这里用假账本隔离真实账本文件。
    import fake_ledger
    fake_ledger.install(monkeypatch,{})
    counts=[]
    def upload(client,files,*,context_id,rename_to,expected_sha256):
        counts.append(len(files))
        for name in rename_to:
            client.evaluate('addCard('+json.dumps(name)+','+json.dumps('https://img.example.invalid/'+name)+')')
        return {'ok':True}
    monkeypatch.setattr(page,'upload_files_to_media',upload)
    first=form_adapters.prepare_media(browser,item,load_contracts(),context_id=None)
    second=form_adapters.prepare_media(browser,item,load_contracts(),context_id=None)
    assert counts==[4]
    assert all(row['uploaded_now'] for rows in first.values() for row in rows)
    assert all(not row['uploaded_now'] for rows in second.values() for row in rows)


@pytest.mark.parametrize('payload',[None,{}, {'count':1,'items':[]}, {'count':1,'items':[{}]}])
def test_invalid_queue_response_fails_immediately(payload):
    with pytest.raises(page.PageError):
        page.read_media_queue_state(Mock(evaluate=Mock(return_value=payload)),context_id=1)


@pytest.mark.parametrize('change',['overall_busy','file_loading','file_missing','file_duplicate'])
def test_final_queue_readback_cannot_reuse_an_earlier_success(change,tmp_path,monkeypatch):
    from test_stale_queue_rejection import FakeMediaClient,ok_item
    client=FakeMediaClient([ok_item('one.jpg')])
    source=tmp_path/'one.jpg'
    source.write_bytes(b'isolated queue test')
    initial={'count':1,'items':[ok_item('one.jpg')],'uploading':False}
    final={'count':1,'items':[ok_item('one.jpg')],'uploading':change=='overall_busy'}
    if change=='file_loading':
        final['items'][0]['state']='loading'
    elif change=='file_missing':
        final.update(count=0,items=[])
    elif change=='file_duplicate':
        final.update(count=2,items=[ok_item('one.jpg'),ok_item('one.jpg')])
    monkeypatch.setattr(page,'read_media_queue_state',Mock(side_effect=[initial,final]))
    finish=Mock(side_effect=AssertionError('当前队列未完成，不能点击完成'))
    monkeypatch.setattr(page,'click_media_finish',finish)
    if change=='file_duplicate':
        with pytest.raises(page.PageError,match='同名重复'):
            page.upload_files_to_media(client,[str(source)],context_id=1,wait=0)
    else:
        result=page.upload_files_to_media(client,[str(source)],context_id=1,wait=0)
        assert result['ok'] is False
        if change=='overall_busy':
            assert '上传中' in result['reason']
    finish.assert_not_called()

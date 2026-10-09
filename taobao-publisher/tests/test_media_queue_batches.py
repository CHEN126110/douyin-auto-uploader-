# -*- coding: utf-8 -*-
"""上传队列成功→完成→图库的顺序和批量完整性，不访问平台。"""
from unittest.mock import Mock

import pytest

from taobao_publish import page
from test_candidate_form_adapters import browser


def test_queue_success_returns_without_waiting_for_gallery(monkeypatch):
    monkeypatch.setattr(page,'read_media_queue_state',lambda *a,**k:{'items':[{'name':'a.jpg','state':'success'}]})
    monkeypatch.setattr(page,'media_image_exists',Mock(side_effect=AssertionError('完成前不能等图库')))
    sleep=Mock(side_effect=AssertionError('已成功队列不应额外等待'))
    monkeypatch.setattr(page.time,'sleep',sleep)
    result=page.wait_for_media_upload_queue(Mock(),['a.jpg'],context_id=1)
    assert result['ok'] and result['confirmed']==['a.jpg']
    sleep.assert_not_called()


@pytest.mark.parametrize('state',['loading','unknown','error'])
def test_partial_or_rejected_queue_is_not_complete(monkeypatch,state):
    monkeypatch.setattr(page,'read_media_queue_state',lambda *a,**k:{'items':[
        {'name':'a.jpg','state':'success'},{'name':'b.jpg','state':state}]})
    result=page.wait_for_media_upload_queue(Mock(),['a.jpg','b.jpg'],context_id=1,timeout=0)
    assert not result['ok'] and result['missing']==['b.jpg']


def test_duplicate_queue_identity_is_an_error(monkeypatch):
    monkeypatch.setattr(page,'read_media_queue_state',lambda *a,**k:{'items':[{'name':'a.jpg','state':'success'}]*2})
    with pytest.raises(page.PageError,match='同名重复'):
        page.wait_for_media_upload_queue(Mock(),['a.jpg'],context_id=1)


@pytest.mark.parametrize('multiple,expected_calls',[(True,1),(False,3)])
def test_files_use_one_batch_only_when_native_input_supports_it(monkeypatch,tmp_path,multiple,expected_calls):
    from test_stale_queue_rejection import FakeMediaClient,ok_item
    names=['a.jpg','b.jpg','c.jpg']
    client=FakeMediaClient([ok_item(name) for name in names])
    base=client.evaluate
    client.evaluate=lambda expr,**kwargs: {'count':1,'inputs':[{'multiple':multiple}]} if 'input[type=' in expr and 'count' in expr else base(expr,**kwargs)
    client.set_file_input_files=Mock(return_value={'ok':True})
    monkeypatch.setattr(page.time,'sleep',lambda *_:None)
    paths=[]
    for name in names:
        path=tmp_path/name;path.write_bytes(b'local image');paths.append(str(path))
    result=page.upload_files_to_media(client,paths,context_id=1,wait=0)
    assert result['ok'] and client.set_file_input_files.call_count==expected_calls
    assert sum(len(call.args[0]) for call in client.set_file_input_files.call_args_list)==3


def test_unaccepted_batch_does_not_finish_or_resend(monkeypatch,tmp_path):
    from test_stale_queue_rejection import FakeMediaClient,ok_item
    client=FakeMediaClient([ok_item('a.jpg')])
    client.set_file_input_files=Mock(return_value={'ok':True})
    finish=Mock(side_effect=AssertionError('少文件不能点完成'))
    monkeypatch.setattr(page,'click_media_finish',finish)
    monkeypatch.setattr(page.time,'sleep',lambda *_:None)
    paths=[]
    for name in ['a.jpg','b.jpg']:
        path=tmp_path/name;path.write_bytes(b'local image');paths.append(str(path))
    result=page.upload_files_to_media(client,paths,context_id=1,wait=0,per_file_timeout=0)
    assert not result['ok'] and result['failed']==['b.jpg']
    assert client.set_file_input_files.call_count==1
    finish.assert_not_called()


def test_real_native_batch_queue_finishes_before_gallery_is_populated(browser,tmp_path):
    browser.evaluate('''document.body.innerHTML=`<button>本地上传</button>
      <div class="UploadPanel_uploadPanel"><div class="UploadPanel_uploadDir"><select><option>全部图片</option></select></div><input type="file" multiple><div id="queue"></div><button id="finish">完成</button></div>
      <div id="gallery"></div>`;
      window.batchChanges=0;window.finished=0;
      document.querySelector('input').onchange=e=>{
        window.batchChanges++;window.names=Array.from(e.target.files).map(f=>f.name);
        document.getElementById('queue').innerHTML=window.names.map(name=>
          '<div class="UploadPanel_fileItem"><span class="UploadPanel_fileName">'+name+'</span><span class="UploadPanel_fileState"><i class="next-icon-success"></i></span></div>').join('');
      };
      document.getElementById('finish').onclick=()=>{
        window.finished++;document.getElementById('gallery').textContent=window.names.join(' ');
        document.querySelector('.UploadPanel_uploadPanel').style.display='none';
      };''')
    files=[]
    for name in ('one.jpg','two.jpg','three.jpg'):
        path=tmp_path/name;path.write_bytes(b'local native batch');files.append(str(path))
    result=page.upload_files_to_media(browser,files,context_id=None,wait=0,per_file_timeout=1)
    assert result['ok'] and len(result['confirmed'])==3
    assert browser.evaluate('window.batchChanges')==1
    assert browser.evaluate('window.finished')==1
    assert len(result['landed'])==3

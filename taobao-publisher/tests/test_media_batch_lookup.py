"""整批查图库及部分缓存的主图位置；只使用隔离本地页面。"""
import json
import hashlib
from pathlib import Path

from PIL import Image
import pytest
from unittest.mock import Mock

from test_candidate_form_adapters import browser, item, fixture_contracts
from test_offline_pipeline_handoff import handoff, save_case, save_and_start
from test_category_first_pipeline import install_model
from test_runtime_native_controls import use_native_detail
from taobao_publish import page, stages, form_adapters
from taobao_publish.constants import STAGE_ORDER
from taobao_publish.models import PublishItem, ImageSet


def test_repeated_local_path_with_ledger_verified_cache_uploads_nothing(browser,tmp_path,monkeypatch):
    """同一文件占两个主图槽位 + 账本已证明云端有这张图 → 零上传，两槽共用一张。"""
    path=tmp_path/'同一张主图.jpg'
    Image.new('RGB',(800,800),'white').save(path)
    item=PublishItem(17,'本地模型',images=ImageSet(main=[str(path),str(path)]))
    identities=[form_adapters.media_file_identity(path,17,'main',slot=slot) for slot in (1,2)]
    # 上传名=源文件名：两个槽位是同一个身份。
    assert identities[0]['name']==identities[1]['name']=='同一张主图.jpg'
    import fake_ledger
    # 不带 picture_id 是故意的：夹具卡片的 checkbox value 只能从文件名取数字，
    # 给了 ID 选图就走「按 ID 精确选」那条路而夹具命中不了——本测试的要点是
    # 「账本验证后零上传、两槽共用一张」，选图走名字路径即可。
    fake_ledger.install(monkeypatch,{'同一张主图.jpg':{'url':'https://img.example.invalid/cached.jpg'}})
    browser.evaluate('openGallery(null,null);addCard('+json.dumps(identities[0]['name'])+',"https://img.example.invalid/cached.jpg");closeGallery()')
    monkeypatch.setattr(page,'open_media_popup',lambda client:form_adapters._checked(client,page.build_open_media_popup_expression()))
    def upload(*args,**kwargs):
        raise AssertionError('账本已证明云端有这张图，不应再上传')
    monkeypatch.setattr(page,'upload_files_to_media',upload)
    result=stages.stage_upload_images(stages.PipelineContext(item=item))
    assert result.ok,result.summary
    assert page.read_main_image_slots(browser)['images']==['https://img.example.invalid/cached.jpg','https://img.example.invalid/cached.jpg']


def test_batch_has_the_same_identity_rules_as_single_lookup_and_never_clicks(browser):
    browser.evaluate('''openGallery(null,null);
      addCard('one.jpg','https://img.example.invalid/one.jpg');
      addCard('two.jpg','https://img.example.invalid/two.jpg');
      addCard('missing.jpg.backup','https://img.example.invalid/backup.jpg');
      window.mediaClicks=0;document.querySelectorAll('#gallery label').forEach(n=>n.onclick=()=>window.mediaClicks++);''')
    result=page.find_media_images(browser,['one.jpg','two.jpg','missing.jpg'],context_id=None)
    assert list(result['receipts'])==['one.jpg','two.jpg']
    assert result['missing']==['missing.jpg']
    assert browser.evaluate('window.mediaClicks')==0


def install_virtual_gallery(browser):
    browser.evaluate('''openGallery(null,null);
      const gallery=document.getElementById('gallery');gallery.style.position='relative';
      gallery.innerHTML='<div style="height:1800px"></div><div id="virtualCards" style="position:absolute;top:0;width:100%"></div>';
      window.visits=[];
      const render=()=>{const part=Math.floor(gallery.scrollTop/300);window.visits.push(part);
        const layer=document.getElementById('virtualCards');layer.style.top=gallery.scrollTop+'px';
        layer.innerHTML='<div class="PicList_pic_background"><label><img src="https://img.example.invalid/'+part+'.jpg">part'+part+'.jpg</label></div>';};
      gallery.onscroll=()=>setTimeout(render,20);render();''')


def test_many_missing_names_only_traverse_virtual_gallery_once(browser):
    install_virtual_gallery(browser)
    result=page.find_media_images(browser,['part0.jpg','part3.jpg','missing-one.jpg','missing-two.jpg','missing-three.jpg'],context_id=None)
    visits=browser.evaluate('window.visits')
    assert set(result['receipts'])=={'part0.jpg','part3.jpg'}
    assert result['missing']==['missing-one.jpg','missing-two.jpg','missing-three.jpg']
    assert result['scrolled']<15 and max(visits)>=5
    assert all(second>=first for first,second in zip(visits,visits[1:])),visits
    assert visits.count(0)<=2  # 初始绘制及重置一次，不能按每张缺图反复归零。


@pytest.mark.parametrize('variant',['same_name','invalid_url','incomplete'])
def test_uncertain_batch_is_an_error_not_permission_to_upload(browser,variant):
    browser.evaluate('openGallery(null,null);addCard("one.jpg","https://img.example.invalid/one.jpg")')
    if variant=='same_name':
        browser.evaluate('addCard("one.jpg","https://img.example.invalid/other.jpg")')
    elif variant=='invalid_url':
        browser.evaluate('document.querySelector("#gallery img").src="http://img.example.invalid/insecure.jpg"')
    else:
        browser.evaluate('document.querySelector("#gallery").innerHTML="<div style=height:100000px>spacer</div>"')
    with pytest.raises(page.PageError) as error:
        page.find_media_images(browser,['one.jpg','missing.jpg'],context_id=None)
    assert not isinstance(error.value,page.MediaImageMissing)


@pytest.mark.parametrize('payload',[
    None, {'ok':True,'receipts':[]},
    {'ok':True,'receipts':[],'missing':[]},
    {'ok':True,'receipts':[],'missing':['one.jpg','one.jpg']},
    {'ok':True,'receipts':[],'missing':['another.jpg']},
])
def test_batch_response_must_account_for_every_requested_name(payload):
    ready = {'ok': True, 'supported': True, 'busy': False}
    client = Mock(evaluate=Mock(side_effect=[ready, payload, ready]))
    with pytest.raises(page.PageError):
        page.find_media_images(client,['one.jpg'],context_id=1)
    assert client.evaluate.call_count == 3, '必须实际检查查找回执，不能靠前面的加载状态错误通过'


def test_popup_close_must_be_observed_before_reusing_a_main_slot(monkeypatch):
    close=Mock()
    monkeypatch.setattr(page,'close_media_popup',close)
    monkeypatch.setattr(page,'read_media_popup',lambda client:{'open':True})
    with pytest.raises(page.PageError,match='未关闭'):
        page.ensure_media_popup_closed(Mock(),timeout=0)
    close.assert_called_once()


@pytest.mark.parametrize('payload',[None,{}, {'open':0}])
def test_unknown_popup_state_is_not_treated_as_closed(payload):
    with pytest.raises(page.PageError):
        page.read_media_popup(Mock(evaluate=Mock(return_value=payload)))


def test_five_main_slots_and_other_media_finish_the_local_pipeline(handoff,monkeypatch):
    from taobao_publish.contracts import load_contracts
    install_model(handoff,load_contracts(),monkeypatch)
    use_native_detail(handoff.browser)
    main=Path(handoff.case.db['path'])/'主图/800'
    image=next(main.glob('*.jpg'))
    for index in range(2,6):
        (main/('主图%02d.jpg' % index)).write_bytes(image.read_bytes())
    batches=[]
    upload=page.upload_files_to_media
    def record(client,files,**kwargs):
        # 上传名=源文件名（2026-10-08 起），角色从**源路径的角色目录**判。
        def role_of(path):
            parts=Path(path).parts
            for role,label in (('main','主图'),('sku','SKU'),('detail','详情页')):
                if label in parts:return role
            raise AssertionError('素材路径里没有角色目录：%s' % path)
        batches.append({'roles':list(dict.fromkeys(role_of(path) for path in files)),
                        'count':len(files)})
        return upload(client,files,**kwargs)
    monkeypatch.setattr(page,'upload_files_to_media',record)
    queries=[]
    lookup=page.find_media_images
    def find(client,names,**kwargs):
        queries.append(len(names))
        return lookup(client,names,**kwargs)
    monkeypatch.setattr(page,'find_media_images',find)
    _,task=save_and_start(handoff)
    assert task['status']=='succeeded',task['error']
    assert batches==[{'roles':['main','sku','detail'],'count':9}]
    assert queries==[9,9]  # 无商品子目录时只合并查询一次根图库，再整批上传后回读。
    slots=page.read_main_image_slots(handoff.browser)
    assert slots['filled']==5 and len(set(slots['images']))==5
    assert len(handoff.uploads)==9
    # 离线跑到 `readback` 就停（停在提交前）——按 STAGE_ORDER 推导，不硬编码阶段数。
    assert [step['name'] for step in task['steps']] == [
        name for name in STAGE_ORDER if name != 'submit']
    assert handoff.browser.evaluate('window.submitCalls + window.draftCalls')==0
    assert task['result']['data']['form_verification']['status']=='partial'
    from taobao_publish.sanitize import assert_clean
    artifact={'scope':'local_synthetic_browser_with_real_http_worker','live_platform_tested':False,
        'server_uploads_simulated':True,'main_slots':5,'upload_batches':batches,'lookup_batch_sizes':queries,
        'model_files':9,'submitted_or_saved_draft':False,'result':task['result'],
        'test_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    assert_clean(artifact)
    (Path(__file__).resolve().parents[1]/'outputs/media_cache_scan_handoff.json').write_text(
        json.dumps(artifact,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

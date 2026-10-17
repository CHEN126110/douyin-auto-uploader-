"""用户反馈：上传完成后必须点击用途目录才显示图片。仅使用本地合成页面。"""
import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest

from test_candidate_form_adapters import browser, item
from test_media_directory_flow import install_tree
from test_runtime_native_controls import use_native_detail
from taobao_publish import page, stages, form_adapters
from taobao_publish.contracts import load_contracts
from taobao_publish.models import PublishItem, ImageSet, SkuEntry


def grouped_gallery(browser, product_name, *, caption='inside'):
    use_native_detail(browser)
    install_tree(browser, product_name)
    browser.evaluate('''window.cardsByFolder={}; const originalAdd=window.addCard;
      window.addCard=(name,url)=>{
        originalAdd(name,url);
        if(CAPTION==='inside')return;
        const gallery=document.getElementById('gallery'),card=gallery.lastElementChild;
        const label=card.querySelector('label');
        for(const node of Array.from(label.childNodes))if(node.nodeType===Node.TEXT_NODE)node.remove();
        const owner=document.createElement('article'),nameNode=document.createElement('span');
        owner.className='local-asset-owner';
        nameNode.textContent=CAPTION==='title'?name.slice(0,8)+'…':name;
        if(CAPTION==='title')nameNode.title=name;
        gallery.append(owner);owner.append(card,nameNode);
      };
      window.renderFolder=()=>{
        const gallery=document.getElementById('gallery');gallery.replaceChildren();
        const rows=window.cardsByFolder[window.currentFolder]||[];
        if(!rows.length){const e=document.createElement('div');e.className='next-empty';e.textContent='暂无图片';gallery.append(e);return;}
        for(const row of rows)window.addCard(row.name,row.url);
      };
      openGallery(null,null);renderFolder();'''.replace('CAPTION',json.dumps(caption)))


def group_upload(browser,monkeypatch,item):
    # 上传名=源文件名后，角色不在名字里也未必在路径里（夹具文件平铺在临时目录），
    # 从商品的素材计划查「源文件名→用途目录」。
    name_to_group={Path(p).name:'主图' for p in (item.images.main or [])}
    for role,paths in form_adapters.media_plan(item).items():
        name_to_group.update({Path(p).name:{'sku':'SKU','detail':'详情页'}[role] for p in paths})
    batches=[]
    def upload(client,files,*,context_id,rename_to,expected_sha256):
        batches.append(list(rename_to))
        grouped={}
        for path,name,digest in zip(files,rename_to,expected_sha256):
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
            # 上传名与源文件名逐字一致（2026-10-08 命名政策）
            assert name==Path(path).name
            grouped.setdefault(name_to_group[name],[]).append({'name':name,'url':'https://img.example.invalid/'+name})
        client.evaluate('''window.cardsByFolder=window.cardsByFolder||{};
          const incoming=INCOMING;
          for(const folder of Object.keys(incoming)){
            window.cardsByFolder[folder]=(window.cardsByFolder[folder]||[]).concat(incoming[folder]);}
          renderFolder();'''.replace('INCOMING',json.dumps(grouped)))
        return {'ok':True}
    monkeypatch.setattr(page,'upload_files_to_media',upload)
    return batches


@pytest.mark.parametrize('caption',['inside','sibling','title'])
def test_uploaded_images_are_found_in_their_product_role_folders(browser,item,monkeypatch,caption):
    grouped_gallery(browser,item.record_name,caption=caption)
    batches=group_upload(browser,monkeypatch,item)
    receipts=form_adapters.prepare_media(browser,item,load_contracts(),context_id=None)
    assert len(batches)==1 and len(batches[0])==4
    for role,group in [('sku','SKU'),('detail','详情页')]:
        assert all(row['folder_path']==['全部图片',item.record_name,group] for row in receipts[role])
    table,bindings=form_adapters.create_custom_skus(browser,item,load_contracts(),receipts)
    assert len(table['rows'])==2 and len(bindings)==2
    form_adapters.fill_detail(browser,item,load_contracts(),receipts)
    assert len(batches)==1


def test_same_named_unverified_images_are_not_substituted_for_this_upload(browser,item,monkeypatch):
    """云端躺着**同名旧图**（名字逐字相同、内容不同、账本无法证明同图）时，
    不得把它当成这次要用的图——宁可如实报错，也不静默选旧图。"""
    grouped_gallery(browser,item.record_name)
    # 预先把同名旧图摆进各用途目录（URL 与本次上传的不同）
    from taobao_publish import form_adapters as fa
    old={}
    for role,paths in fa.media_plan(item).items():
        label={'sku':'SKU','detail':'详情页'}.get(role, '主图')
        old[label]=[{'name':fa.media_file_identity(p,item.record_id,role)['name'],
                     'url':'https://img.example.invalid/old-'+str(i)+'.jpg'} for i,p in enumerate(paths)]
    browser.evaluate('window.cardsByFolder='+json.dumps(old)+';renderFolder()')
    batches=group_upload(browser,monkeypatch,item)
    with pytest.raises(page.PageError):
        form_adapters.prepare_media(browser,item,load_contracts(),context_id=None)
    assert browser.evaluate('Boolean(window.imageTarget)') is False


def test_caption_belongs_to_one_image_not_the_neighbour_or_gallery(browser):
    browser.evaluate('''openGallery(null,null);addCard('wrong.jpg','https://img.example.invalid/wrong.jpg');
      const card=document.querySelector('.PicList_pic_background');
      for(const node of Array.from(card.querySelector('label').childNodes))if(node.nodeType===Node.TEXT_NODE)node.remove();
      const text=document.createElement('span');text.textContent='target.jpg';document.getElementById('gallery').append(text);''')
    result=page.find_media_images(browser,['target.jpg'],context_id=None)
    assert result['missing']==['target.jpg']


def test_hidden_sibling_caption_is_not_a_file_identity(browser):
    grouped_gallery(browser,'123',caption='sibling')
    browser.evaluate('addCard("target.jpg","https://img.example.invalid/target.jpg");document.querySelector(".local-asset-owner > span").hidden=true')
    assert page.find_media_images(browser,['target.jpg'],context_id=None)['missing']==['target.jpg']


def test_duplicate_sibling_names_do_not_select_the_first_image(browser):
    grouped_gallery(browser,'123',caption='sibling')
    browser.evaluate('addCard("target.jpg","https://img.example.invalid/one.jpg");addCard("target.jpg","https://img.example.invalid/two.jpg")')
    with pytest.raises(page.PageError):
        page.find_media_images(browser,['target.jpg'],context_id=None)


def test_21_images_continue_from_upload_to_main_sku_and_detail(browser,tmp_path,monkeypatch):
    paths=[]
    for index in range(21):
        path=tmp_path/('素材_%02d.jpg'%index)
        Image.new('RGB',(800,800),(index*11,70,120)).save(path)
        paths.append(str(path))
    item=PublishItem(record_id=1,record_name='ID-目录模型',title='本地目录测试',sku_mode='custom',
        images=ImageSet(main=paths[:5],sku=paths[5:11],detail=paths[11:]),
        skus=[SkuEntry(spec_values={'颜色分类':'规格%d'%index},image_path=path,price=29.8+index,stock=100)
              for index,path in enumerate(paths[5:11])])
    grouped_gallery(browser,item.record_name,caption='sibling')
    browser.evaluate('closeGallery()')
    batches=group_upload(browser,monkeypatch,item)
    ctx=stages.PipelineContext(item=item,dry_run=False)
    results=[]
    for handler in (stages.stage_upload_images,stages.stage_fill_skus,stages.stage_fill_detail):
        result=handler(ctx)
        assert result.ok,result.summary
        results.append(result.summary)
    assert [len(batch) for batch in batches]==[21]
    assert page.read_main_image_slots(browser)['filled']==5
    assert len(page.read_sku_table(browser)['rows'])==6
    assert len(ctx.scratch['bound_media']['detail'])==10
    assert browser.evaluate('window.submitCalls+window.draftCalls')==0
    artifact={'scope':'isolated_browser_with_simulated_upload_server_and_role_subdirectories',
        'live_platform_tested':False,'main_images':5,'sku_images':6,'detail_images':10,
        'upload_batches':[21],'subdirectory_lookup_required':True,'caption_is_sibling':True,
        'stage_summaries':results,'saved_draft_or_submitted':False,
        'test_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    from taobao_publish.sanitize import assert_clean
    assert_clean(artifact)
    (Path(__file__).resolve().parents[1]/'outputs/uploaded_media_subdirectories_handoff.json').write_text(
        json.dumps(artifact,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

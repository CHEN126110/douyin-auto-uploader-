"""原名/目录批次快照与已上传素材的 DOM 交接；不连接真实平台。"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

from PIL import Image
import pytest

from test_candidate_form_adapters import browser, fixture_contracts
from test_offline_pipeline_handoff import handoff, save_case, save_and_start
from test_uploaded_media_subdirectories import grouped_gallery
from test_runtime_native_controls import use_native_detail
from taobao_publish import stages, page
from taobao_publish.models import PublishItem, ImageSet, SkuEntry
from taobao_publish.authorization import WriteAuthorization
from taobao_publish.errors import WriteNotAuthorizedError
from taobao_publish.media_manifest import (
    build_media_manifest, build_batch_manifests, snapshot_media_batch, prepare_media_batch,
    PreparedProductMedia, UploadedImageReceipt, MediaBatchPreparationError,
)


@pytest.fixture
def prepared_case(tmp_path):
    root = tmp_path / '原商品目录'
    names = ['主图/同名.jpg', 'SKU/同名.jpg', 'SKU/规格.jpg', '详情页/详情01.jpg']
    for index, name in enumerate(names):
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (800, 800), (index * 45, 80, 130)).save(file)
    (root / '详情页/说明.json').write_text('{"title":"不上传资料文件"}', encoding='utf-8')
    manifest = build_media_manifest(19, str(root))
    receipts = tuple(UploadedImageReceipt(image.relative_path, Path(image.relative_path).name,
        (manifest.folder_name, *Path(image.relative_path).parts[:-1]),
        'https://img.example.invalid/' + image.sha256 + '.jpg', image.sha256) for image in manifest.images)
    prepared = PreparedProductMedia(manifest, 'account-A', receipts)
    item = PublishItem(record_id=19, record_name='前端显示名可以不同', title='测试袜子', sku_mode='custom',
        images=ImageSet(main=[str(root / name) for name in names[:2]],
            sku=[str(root / names[2])], detail=[str(root / names[3])]),
        skus=[SkuEntry(spec_values={'颜色分类':'白色均码'}, image_path=str(root / names[2]), price=19.8, stock=100)])
    return root, prepared, item


def test_manifest_and_snapshot_keep_original_folder_structure(prepared_case):
    root, prepared, _ = prepared_case
    plan = prepared.manifest
    before = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    with snapshot_media_batch([plan]) as folders:
        copied = Path(folders[0])
        assert copied.name == root.name
        assert {path.relative_to(copied).as_posix() for path in copied.rglob('*') if path.is_file()} == {image.relative_path for image in plan.images}
        assert not (copied / '详情页/说明.json').exists()
        assert all(hashlib.sha256((copied / image.relative_path).read_bytes()).hexdigest() == image.sha256 for image in plan.images)
    assert not copied.exists()
    assert before == {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob('*') if path.is_file()}


def test_batch_rejects_same_named_roots_before_upload(prepared_case, tmp_path):
    root, _, _ = prepared_case
    second = tmp_path / '另外位置' / root.name
    second.mkdir(parents=True)
    Image.new('RGB',(800,800),'blue').save(second/'图.jpg')
    with pytest.raises(ValueError, match='同名商品文件夹'):
        build_batch_manifests([{'id':19,'path':str(root)}, {'id':20,'path':str(second)}])


def test_batch_upload_consumes_validated_snapshots_and_has_no_publish_action(prepared_case):
    _, prepared, _ = prepared_case
    calls=[]
    def upload(manifest, directory, account):
        calls.append((manifest.record_id, account, Path(directory).name))
        assert Path(directory) != Path(manifest.product_dir)
        return prepared
    result = prepare_media_batch(iter([prepared.manifest]), upload, account_profile='account-A',
                                  authorization=WriteAuthorization.for_form_filling())
    assert result == (prepared,)
    assert calls == [(19,'account-A','原商品目录')]


def test_no_authorization_never_calls_upload(prepared_case):
    _, prepared, _ = prepared_case
    upload=Mock()
    with pytest.raises(WriteNotAuthorizedError):
        prepare_media_batch([prepared.manifest], upload, account_profile='account-A')
    upload.assert_not_called()


def test_failed_second_product_keeps_first_products_receipts(prepared_case, tmp_path):
    root, prepared, _=prepared_case
    other=tmp_path/'第二个商品'
    other.mkdir()
    Image.new('RGB',(800,800),'blue').save(other/'图.jpg')
    second=build_media_manifest(20,str(other))
    calls=[]
    def upload(plan, folder, account):
        calls.append(plan.record_id)
        if plan.record_id==19: return prepared
        raise ValueError('第二件素材没有完整入库回执')
    with pytest.raises(MediaBatchPreparationError) as error:
        prepare_media_batch([prepared.manifest,second],upload,account_profile='account-A',
                             authorization=WriteAuthorization.for_form_filling())
    assert calls==[19,20]
    assert error.value.completed==(prepared,)


def test_cancel_after_preparation_keeps_receipt_and_does_not_enter_filling(prepared_case):
    _,prepared,_=prepared_case
    cancelled={'value':False}
    def upload(*_):
        cancelled['value']=True
        return prepared
    with pytest.raises(MediaBatchPreparationError) as error:
        prepare_media_batch([prepared.manifest],upload,account_profile='account-A',
            authorization=WriteAuthorization.for_form_filling(),should_cancel=lambda:cancelled['value'])
    assert error.value.code=='CANCELLED' and error.value.completed==(prepared,)


@pytest.mark.parametrize('change',['rename','folder','digest','missing','account','added_file'])
def test_changed_or_incomplete_receipt_is_rejected(prepared_case, change):
    root, prepared, item = prepared_case
    first = prepared.receipts[0]
    if change == 'rename': first=replace(first,name='自动改名(1).jpg')
    if change == 'folder': first=replace(first,folder=('另一个商品',))
    if change == 'digest': first=replace(first,sha256='0'*64)
    if change in ('rename','folder','digest'):
        prepared=replace(prepared,receipts=(first,*prepared.receipts[1:]))
    if change == 'missing': prepared=replace(prepared,receipts=prepared.receipts[1:])
    if change == 'account': prepared=replace(prepared,account_profile='account-B')
    if change == 'added_file': Image.new('RGB',(800,800),'white').save(root/'新增.jpg')
    with pytest.raises(ValueError): prepared.selection_plan(item, 'account-A')


def test_source_change_before_upload_is_not_a_partial_batch(prepared_case):
    root, prepared, _ = prepared_case
    Image.new('RGB',(800,800),'yellow').save(root/'主图/同名.jpg')
    upload=Mock()
    with pytest.raises(MediaBatchPreparationError) as error:
        prepare_media_batch([prepared.manifest], upload, account_profile='account-A',
                             authorization=WriteAuthorization.for_form_filling())
    assert error.value.completed == ()
    upload.assert_not_called()


def test_original_names_and_same_names_in_different_folders_select_correct_images(browser, prepared_case, monkeypatch):
    _, prepared, item = prepared_case
    grouped_gallery(browser, prepared.manifest.folder_name, caption='sibling')
    groups={}
    for receipt in prepared.receipts:
        groups.setdefault(receipt.folder[-1], []).append({'name':receipt.name,'url':receipt.url})
    browser.evaluate('window.cardsByFolder='+json.dumps(groups)+';renderFolder();closeGallery()')
    upload=Mock(side_effect=AssertionError('素材准备已完成，表单填写不得再次上传'))
    monkeypatch.setattr(page,'upload_files_to_media',upload)
    ctx=stages.PipelineContext(item=item,dry_run=False,prepared_media=prepared,account_profile='account-A')
    for handler in (stages.stage_upload_images,stages.stage_fill_skus,stages.stage_fill_detail):
        outcome=handler(ctx)
        assert outcome.ok,outcome.summary
    plan=prepared.selection_plan(item,'account-A')
    assert page.read_main_image_slots(browser)['images'] == [entry['url'] for entry in plan['main']]
    assert plan['main'][0]['name'] == plan['main'][1]['name'] == '同名.jpg'
    assert plan['main'][0]['url'] != plan['main'][1]['url']
    assert len(ctx.scratch['bound_media']['sku']) == 1 and len(ctx.scratch['bound_media']['detail']) == 1
    assert browser.evaluate('window.submitCalls + window.draftCalls') == 0
    upload.assert_not_called()


def test_wrong_remote_url_stops_without_upload_or_select(browser, prepared_case, monkeypatch):
    _, prepared, item=prepared_case
    grouped_gallery(browser,prepared.manifest.folder_name,caption='sibling')
    browser.evaluate('window.cardsByFolder={"主图":[{name:"同名.jpg",url:"https://img.example.invalid/wrong.jpg"}]};renderFolder();closeGallery()')
    upload=Mock(side_effect=AssertionError('不得通过重传掩盖对应关系错误'))
    monkeypatch.setattr(page,'upload_files_to_media',upload)
    outcome=stages.stage_upload_images(stages.PipelineContext(item=item,dry_run=False,
        prepared_media=prepared,account_profile='account-A'))
    assert not outcome.ok and 'media_url_changed' in outcome.summary
    assert browser.evaluate('window.selectCalls') == 0
    assert page.read_main_image_slots(browser)['filled']==0
    upload.assert_not_called()


def test_prepared_original_folders_pass_through_the_actual_http_worker_and_pipeline(handoff, monkeypatch):
    """上传回执/平台页面由隔离模型提供，真实工作线程把预备素材交给生产流水线。"""
    from types import SimpleNamespace
    use_native_detail(handoff.browser)
    manifest=build_media_manifest(7,handoff.case.db['path'])
    receipts=tuple(UploadedImageReceipt(image.relative_path,Path(image.relative_path).name,
        (manifest.folder_name,*Path(image.relative_path).parts[:-1]),
        'https://img.example.invalid/'+image.sha256+'.jpg',image.sha256) for image in manifest.images)
    prepared=PreparedProductMedia(manifest,'测试账户',receipts)
    groups={}
    for receipt in receipts:
        groups.setdefault('/'.join(receipt.folder),[]).append({'name':receipt.name,'url':receipt.url})
    tree_paths=[[manifest.folder_name]]+[[manifest.folder_name,*Path(path).parts] for path in manifest.directories]
    handoff.browser.evaluate('''(() => {
      const groups=GROUPS,paths=PATHS,tree=document.createElement('div');tree.setAttribute('role','tree');
      tree.style.cssText='display:block;width:250px';document.body.prepend(tree);const nodes=new Map();
      window.renderPreparedFolder=key=>{document.getElementById('gallery').replaceChildren();for(const row of groups[key]||[])addCard(row.name,row.url)};
      for(const path of [['全部图片'],...paths]){
        const key=path.join('/'),node=document.createElement('div');node.setAttribute('role','treeitem');node.setAttribute('aria-label',path.at(-1));
        node.style.cssText='min-height:28px;width:200px';const label=document.createElement('span');label.className='next-tree-node-label';label.textContent=path.at(-1);node.append(label);
        const parent=path.length>1?nodes.get(path.slice(0,-1).join('/')):tree;parent.append(node);nodes.set(key,node);
        label.onclick=event=>{event.stopPropagation();tree.querySelectorAll('[aria-selected]').forEach(n=>n.removeAttribute('aria-selected'));node.setAttribute('aria-selected','true');renderPreparedFolder(key)};
      }
      nodes.get('全部图片').setAttribute('aria-selected','true');renderPreparedFolder('全部图片');
    })()'''.replace('GROUPS',json.dumps(groups)).replace('PATHS',json.dumps(tree_paths)))
    existing_loader=handoff.case.ns['_load_taobao_pipeline']
    def load():
        actual=existing_loader()
        def from_record(row, request, **options):
            assert options['account_profile'] == '测试账户'
            options['media_preparer'] = lambda *args: prepared
            return actual.run_from_record(row, request, **options)
        return SimpleNamespace(run_from_record=from_record)
    handoff.case.ns['_load_taobao_pipeline']=load
    _,task=save_and_start(handoff)
    assert task['status']=='succeeded',task.get('error')
    assert not handoff.uploads,'进入表单后不得再次上传素材'
    assert task['result']['data']['form_verification']['status']=='partial'
    assert task['result']['stopped_before_submit'] is True
    observed=task['result']['data']['media_observations']
    assert {entry['name'] for entry in observed} <= {receipt.name for receipt in receipts}
    assert all(not entry['name'].startswith('tb_') for entry in observed)
    assert handoff.browser.evaluate('window.submitCalls+window.draftCalls')==0


#: 按真机语义建模「素材中心刚建好的目录，选图器看不见」（2026-10-08 真机
#: ID-986833932804）：creator 只改「服务端」清单 ``cloudFolders``，选图器的树
#: 只在**弹层重新打开**时从清单重建——不重新打开，读多少次都是旧树。
SERVER_SIDE_TREE_JS = '''(() => {
  window.cloudFolders=['OTHER'];
  window.rebuildTree=()=>{
    document.querySelectorAll('[role=tree]').forEach(t=>t.remove());
    const tree=document.createElement('div');tree.setAttribute('role','tree');
    tree.style.cssText='display:block;width:250px';document.body.prepend(tree);
    const make=(label,parent)=>{const li=document.createElement('div');li.setAttribute('role','treeitem');
      li.setAttribute('aria-label',label);li.style.cssText='min-height:28px;width:200px';
      const text=document.createElement('span');text.className='next-tree-node-label';text.textContent=label;li.append(text);
      text.onclick=e=>{e.stopPropagation();tree.querySelectorAll('[aria-selected]').forEach(n=>n.removeAttribute('aria-selected'));
        li.setAttribute('aria-selected','true');window.currentFolder=label;
        document.getElementById('gallery').replaceChildren();setTimeout(()=>window.renderFolder(),60);};
      parent.append(li);return li;};
    const root=make('全部图片',tree);
    for(const f of window.cloudFolders){const p=make(f,root);make('主图',p);make('SKU',p);make('详情页',p);}
    root.setAttribute('aria-selected','true');window.currentFolder='全部图片';
  };
  window.openGallery=(orig=>(...args)=>{window.rebuildTree();return orig(...args);})(window.openGallery);
})()'''


def test_prepared_media_never_creates_empty_folder_to_hide_missing_upload(browser, prepared_case, monkeypatch):
    """已有完整上传回执但云端目录缺失是交接错误，不能用建空目录掩盖。"""
    _, prepared, item = prepared_case
    grouped_gallery(browser, 'OTHER')  # 初始树里没有本商品目录
    browser.evaluate(SERVER_SIDE_TREE_JS)
    folder = prepared.manifest.folder_name
    groups = {}
    for receipt in prepared.receipts:
        groups.setdefault(receipt.folder[-1], []).append({'name': receipt.name, 'url': receipt.url})
    browser.evaluate('window.cardsByFolder=' + json.dumps(groups) + ';closeGallery()')
    events = []
    real_open = page.open_media_popup
    def tracked_open(client, *args, **kwargs):
        events.append('open')
        return real_open(client, *args, **kwargs)
    monkeypatch.setattr(page, 'open_media_popup', tracked_open)
    def creator(name, roles):
        events.append('creator')
        browser.evaluate('window.cloudFolders.push(%s)' % json.dumps(name))
        return {role: 'fid-%s' % role for role in roles}
    monkeypatch.setattr(stages, '_cloud_folder_creator', lambda ctx: creator)
    from taobao_publish import media_library
    actual_ensure = media_library.ensure_product_root
    monkeypatch.setattr(media_library, 'ensure_product_root', lambda client, name, **kwargs:
        actual_ensure(client, name, **dict(kwargs, wait_seconds=0)))
    upload = Mock(side_effect=AssertionError('素材准备已完成，表单填写不得再次上传'))
    monkeypatch.setattr(page, 'upload_files_to_media', upload)
    ctx = stages.PipelineContext(item=item, dry_run=False, prepared_media=prepared,
                                 account_profile='account-A')
    outcome = stages.stage_upload_images(ctx)
    assert not outcome.ok and 'directory_missing' in outcome.summary
    assert events == ['open'], events
    upload.assert_not_called()

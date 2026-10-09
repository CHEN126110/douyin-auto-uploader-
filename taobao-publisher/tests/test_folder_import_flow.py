# -*- coding: utf-8 -*-
"""目录先行的隔离验证；平台上传服务为模型，不连接用户浏览器或实际淘宝。"""
from dataclasses import replace
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_candidate_form_adapters import browser
from test_media_folder_capability import local_http_browser
from test_prepared_media_manifest import prepared_case
from test_pipeline import make_local, make_request
from _helpers import make_image
from taobao_publish import folder_import as module, media_library, page, pipeline, stages, cdp, cdp_ws
from taobao_publish.authorization import WriteAuthorization
from taobao_publish.errors import TaobaoPublishError
from taobao_publish.media_manifest import (build_media_manifest, PreparedProductMedia,
                                         UploadedImageReceipt, snapshot_media_batch)

AUTH = WriteAuthorization.for_form_filling()


def queue(names, state='success', uploading=False):
    return {'items': [{'name': name, 'state': state} for name in names], 'uploading': uploading}


@pytest.mark.parametrize('case', ['missing', 'uploading', 'directory_pending', 'unknown', 'empty'])
def test_queue_requires_all_files_and_final_state(case):
    names = ['同名.jpg', '同名.jpg', '详情.jpg']
    value = queue(names)
    if case == 'missing': value = queue(names[:-1])
    if case == 'uploading': value['uploading'] = True
    if case == 'directory_pending': value['items'].append({'name': 'SKU', 'state': 'loading'})
    if case == 'unknown': value['items'][0]['state'] = 'unknown'
    if case == 'empty': value = queue([])
    assert not module.queue_complete(value, names, {'SKU'})


def test_queue_accepts_duplicate_basename_in_separate_folders():
    names = ['同名.jpg', '同名.jpg', '详情.jpg']
    assert module.queue_complete(queue(names + ['SKU']), names, {'SKU'})


@pytest.mark.parametrize('bad', ['duplicate', 'extra', 'rejected'])
def test_queue_rejects_wrong_batch_or_platform_errors(bad):
    value = queue(['主图.jpg'])
    if bad == 'duplicate': value['items'].append({'name': '主图.jpg', 'state': 'success'})
    if bad == 'extra': value['items'].append({'name': '外部.jpg', 'state': 'success'})
    if bad == 'rejected': value['items'][0].update(state='error', desc='平台拒绝')
    with pytest.raises(TaobaoPublishError):
        module.queue_complete(value, ['主图.jpg'])


NATIVE_PANEL = r'''(() => {
  document.body.innerHTML = `<div role="tree"><div role="treeitem" aria-label="智能创作">智能创作</div></div>
    <div class="UploadPanel_uploadPanel" style="width:800px;height:700px">
    <select class="UploadPanel_uploadDir"><option>全部图片</option></select>
    <div class="UploadPanel_uploadPart" style="width:600px;height:300px;border:1px solid">本地合成目录导入</div>
    <div id="rows"></div><span id="status"></span><button id="finish" type="button">完成</button></div>`;
  window.imported=[];window.dropCount=0;window.finishCount=0;window.directoryRoots=[];
  const addRow=(name)=>{
    const row=document.createElement('div');row.className='UploadPanel_fileItem';
    const label=document.createElement('span');label.className='UploadPanel_fileName';label.textContent=name;
    const state=document.createElement('span');state.className='UploadPanel_fileState';
    state.innerHTML='<i class="next-icon-success"></i>';row.append(label,state);document.getElementById('rows').append(row);
  };
  const visit=async entry=>{
    if(entry.isFile){
      const file=await new Promise((resolve,reject)=>entry.file(resolve,reject));
      const hash=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());
      const sha=Array.from(new Uint8Array(hash)).map(b=>b.toString(16).padStart(2,'0')).join('');
      imported.push({path:entry.fullPath,sha});addRow(entry.name);return;
    }
    addRow(entry.name);const reader=entry.createReader();
    while(true){const children=await new Promise((resolve,reject)=>reader.readEntries(resolve,reject));
      if(!children.length)break;for(const child of children)await visit(child);}
  };
  const drop=document.querySelector('.UploadPanel_uploadPart');
  drop.ondragover=e=>e.preventDefault();
  drop.ondrop=async e=>{
    e.preventDefault();window.dropCount++;document.getElementById('status').textContent='4 个文件上传中...';
    const roots=Array.from(e.dataTransfer.items).map(item=>item.webkitGetAsEntry());
    window.directoryRoots=roots.map(entry=>({name:entry.name,isDirectory:entry.isDirectory}));
    try{for(const entry of roots)await visit(entry);document.getElementById('status').textContent='';}
    catch(error){window.importError=String(error);}
  };
  document.getElementById('finish').onclick=()=>{window.finishCount++;document.querySelector('.UploadPanel_uploadPanel').style.display='none';};
})()'''


@pytest.mark.parametrize('browser', ['memory_http_only'], indirect=True)
def test_one_native_directory_preserves_paths_bytes_and_waits_for_cloud_receipts(
        local_http_browser, prepared_case, monkeypatch):
    client, url = local_http_browser
    _, prepared, _ = prepared_case
    manifest = prepared.manifest
    client.evaluate(NATIVE_PANEL)
    monkeypatch.setattr(media_library, 'product_root_path', lambda *args, **kwargs:
        [manifest.folder_name] if client.evaluate('window.finishCount') == 1 else None)
    reads = []
    def cloud_files(_, directory, **kwargs):
        assert client.evaluate('window.finishCount') == 1, '队列完成并确认后才读取云端目录'
        reads.append(directory)
        actual = client.evaluate('window.imported')
        wanted_prefix = '/' + '/'.join(directory) + '/'
        files = [{'name': Path(entry['path']).name, 'url': 'https://img.example.invalid/' + entry['sha'] + '.jpg',
                  'picture_id': str(index + 100)} for index, entry in enumerate(actual)
                 if entry['path'].rsplit('/', 1)[0] + '/' == wanted_prefix]
        return {'files': files}
    monkeypatch.setattr(media_library, 'read_directory_files', cloud_files)
    result = module.import_directory(client, manifest, 'account-A', authorization=AUTH)
    result.validate('account-A')
    assert client.evaluate('window.dropCount') == 1
    assert client.evaluate('window.finishCount') == 1
    assert client.evaluate('window.directoryRoots') == [{'name': manifest.folder_name, 'isDirectory': True}]
    received = {entry['path']: entry['sha'] for entry in client.evaluate('window.imported')}
    assert received == {'/' + manifest.folder_name + '/' + source.relative_path: source.sha256 for source in manifest.images}
    assert len(reads) == 3 and len({tuple(path) for path in reads}) == 3
    assert all(receipt.picture_id for receipt in result.receipts)
    assert client.evaluate('location.href') == url, '素材模块本身没有导航到发布页'


def test_directory_input_is_used_once_without_flattening(browser, prepared_case, monkeypatch):
    root, _, _ = prepared_case
    browser.evaluate('''document.body.innerHTML='<div class="UploadPanel_uploadPanel" style="height:100px"><input type=file webkitdirectory multiple></div>';
        window.changeCount=0;document.querySelector('input').onchange=()=>window.changeCount++''')
    send = Mock(wraps=browser.send)
    monkeypatch.setattr(browser, 'send', send)
    assert module.send_directory(browser, str(root)) == 'directory_input'
    deadline = time.monotonic() + 3
    while browser.evaluate('window.changeCount') == 0 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert browser.evaluate('window.changeCount') == 1
    assert all('/' in path for path in browser.evaluate('Array.from(document.querySelector("input").files).map(f=>f.webkitRelativePath)'))
    assert not any(call.args[0] == 'Input.dispatchDragEvent' for call in send.call_args_list)


@pytest.mark.parametrize('condition', ['no_zone', 'covered', 'ambiguous_input'])
def test_invalid_directory_target_never_sends_files(browser, prepared_case, monkeypatch, condition):
    browser.evaluate(NATIVE_PANEL)
    if condition == 'no_zone': browser.evaluate('document.querySelector(".UploadPanel_uploadPart").remove()')
    if condition == 'covered': browser.evaluate("const cover=document.createElement('div');cover.style.cssText='position:fixed;inset:0;background:white;z-index:9999';document.body.append(cover)")
    if condition == 'ambiguous_input': browser.evaluate("document.querySelector('.UploadPanel_uploadPanel').innerHTML='<input type=file webkitdirectory><input type=file webkitdirectory>'")
    sender = Mock(wraps=browser.send)
    monkeypatch.setattr(browser, 'send', sender)
    with pytest.raises(page.PageError): module.send_directory(browser, str(prepared_case[0]))
    assert not any(call.args[0] in ('DOM.setFileInputFiles', 'Input.dispatchDragEvent') for call in sender.call_args_list)


def test_snapshot_is_preserved_when_native_upload_stops(prepared_case, tmp_path, monkeypatch):
    import taobao_publish.media_manifest as manifests
    snapshot_root = tmp_path / 'retained'
    snapshot_root.mkdir()
    monkeypatch.setattr(manifests.tempfile, 'mkdtemp', lambda **kwargs: str(snapshot_root))
    with pytest.raises(TaobaoPublishError, match='素材快照暂留') as stopped:
        with snapshot_media_batch([prepared_case[1].manifest], retain_on_error=True) as folders:
            raise TaobaoPublishError('CANCELLED', '测试取消')
    assert stopped.value.code == 'CANCELLED'
    assert Path(folders[0]).is_dir()
    assert list(Path(folders[0]).rglob('*.jpg'))


def test_unreceived_folder_is_sent_only_once_and_reports_failure(prepared_case, tmp_path, monkeypatch):
    import taobao_publish.media_manifest as manifests
    snapshot_root = tmp_path / 'empty-queue-snapshot'
    snapshot_root.mkdir()
    monkeypatch.setattr(manifests.tempfile, 'mkdtemp', lambda **kwargs: str(snapshot_root))
    monkeypatch.setattr(media_library, 'product_root_path', lambda *args, **kwargs: None)
    monkeypatch.setattr(media_library, 'read_directory', lambda *args, **kwargs: {'supported': True, 'paths': [['智能创作']]})
    monkeypatch.setattr(module, '_open_panel', lambda *args: None)
    from taobao_publish import upload_panel
    monkeypatch.setattr(upload_panel, 'ensure_all_images', lambda *args, **kwargs: None)
    monkeypatch.setattr(page, 'read_media_queue_state', lambda *args, **kwargs: queue([]))
    sent = Mock(return_value='native_directory_drop')
    monkeypatch.setattr(module, 'send_directory', sent)
    finish = Mock()
    monkeypatch.setattr(page, 'click_media_finish', finish)
    with pytest.raises(TaobaoPublishError, match='未完成'):
        module.import_directory(None, prepared_case[1].manifest, 'account-A', authorization=AUTH, timeout=0)
    sent.assert_called_once()
    assert Path(sent.call_args.args[1]).is_dir()
    finish.assert_not_called()


@pytest.fixture
def preparation_model(prepared_case, tmp_path, monkeypatch):
    from src import runtime_paths
    root, prepared, item = prepared_case
    target = SimpleNamespace(kind='page', url=module.MATERIAL_CENTER_URL, target_id='new-tab',
                             web_socket_url='ws://isolated.invalid/')
    browser = SimpleNamespace(list_targets=Mock(return_value=[target]), new_page=Mock(), close=Mock())
    client = SimpleNamespace(evaluate=Mock(return_value=True), navigate=Mock(), close=Mock())
    monkeypatch.setattr(cdp_ws, 'CdpBrowser', Mock(return_value=browser))
    monkeypatch.setattr(page.PageClient, 'connect', Mock(return_value=client))
    monkeypatch.setattr(runtime_paths, 'resolve_data_file', lambda name: tmp_path / name)
    importer = Mock(return_value=prepared)
    monkeypatch.setattr(module, 'import_directory', importer)
    local = SimpleNamespace(record_id=prepared.manifest.record_id, product_dir=str(root))
    return SimpleNamespace(local=local, prepared=prepared, item=item, client=client, browser=browser,
                           importer=importer, cache=tmp_path / 'taobao_folder_import_receipts')


def test_preparation_uploads_before_navigation_and_reuses_complete_cache(preparation_model):
    model = preparation_model
    events = []
    model.importer.side_effect = lambda *args, **kwargs: events.append('upload_complete') or model.prepared
    model.client.navigate.side_effect = lambda *args, **kwargs: events.append('publish_navigation')
    prepare = module.make_preparer('account-A', 'http://127.0.0.1:1/json/list')
    first = prepare(model.local, model.item, AUTH, lambda message: None, None)
    second = prepare(model.local, model.item, AUTH, lambda message: None, None)
    assert events == ['upload_complete', 'publish_navigation', 'publish_navigation']
    assert first.publish_target_id == second.publish_target_id == 'new-tab'
    assert all(not receipt.uploaded_now for receipt in second.receipts)
    model.importer.assert_called_once()
    assert 'publish_target_id' not in next(model.cache.glob('*.json')).read_text(encoding='utf-8')


@pytest.mark.parametrize('failure', ['platform_error', 'cancelled', 'wrong_receipts'])
def test_preparation_failure_never_enters_publish_page(preparation_model, failure):
    model = preparation_model
    if failure != 'wrong_receipts':
        model.importer.side_effect = TaobaoPublishError('CANCELLED' if failure == 'cancelled' else 'IMAGE_UPLOAD_FAILED', failure)
    else:
        model.importer.return_value = replace(model.prepared, receipts=model.prepared.receipts[:-1])
    prepare = module.make_preparer('account-A', 'http://127.0.0.1:1/json/list')
    with pytest.raises((TaobaoPublishError, ValueError)):
        prepare(model.local, model.item, AUTH, None, None)
    model.client.navigate.assert_not_called()
    assert not list(model.cache.glob('*.json'))
    model.client.close.assert_called_once()


def test_cache_corruption_is_not_a_new_upload(preparation_model):
    model = preparation_model
    prepare = module.make_preparer('account-A', 'http://127.0.0.1:1/json/list')
    prepare(model.local, model.item, AUTH, None, None)
    saved = next(model.cache.glob('*.json'))
    data = json.loads(saved.read_text(encoding='utf-8'))
    data['manifest_digest'] = 'wrong'
    saved.write_text(json.dumps(data), encoding='utf-8')
    model.importer.reset_mock()
    model.client.navigate.reset_mock()
    with pytest.raises(ValueError, match='摘要'):
        prepare(model.local, model.item, AUTH, None, None)
    model.importer.assert_not_called()
    model.client.navigate.assert_not_called()


def test_cache_is_separate_for_each_account(preparation_model):
    model = preparation_model
    module.make_preparer('account-A', 'http://127.0.0.1:1/json/list')(model.local, model.item, AUTH, None, None)
    model.importer.return_value = replace(model.prepared, account_profile='account-B')
    second = module.make_preparer('account-B', 'http://127.0.0.1:1/json/list')(model.local, model.item, AUTH, None, None)
    assert second.account_profile == 'account-B'
    assert model.importer.call_count == 2
    assert len(list(model.cache.glob('*.json'))) == 2


def test_changed_source_invalidates_receipt_cache(preparation_model):
    from PIL import Image
    model = preparation_model
    prepare = module.make_preparer('account-A', 'http://127.0.0.1:1/json/list')
    prepare(model.local, model.item, AUTH, None, None)
    Image.new('RGB', (800, 800), 'red').save(Path(model.local.product_dir) / model.prepared.manifest.images[0].relative_path)
    model.client.navigate.reset_mock()
    # 旧回执即使上传端误返也不能用于内容已经改变的商品。
    with pytest.raises(ValueError, match='已改变'):
        prepare(model.local, model.item, AUTH, None, None)
    assert model.importer.call_count == 2
    model.client.navigate.assert_not_called()


def test_preparation_cancel_after_receipt_preserves_cache_without_navigation(preparation_model):
    model = preparation_model
    cancel = {'value': False}
    def done(*args, **kwargs):
        cancel['value'] = True
        return model.prepared
    model.importer.side_effect = done
    with pytest.raises(TaobaoPublishError, match='取消'):
        module.make_preparer('account-A', 'http://127.0.0.1:1/json/list')(
            model.local, model.item, AUTH, None, lambda: cancel['value'])
    assert len(list(model.cache.glob('*.json'))) == 1
    model.client.navigate.assert_not_called()


def test_old_ledger_requires_same_resource_in_current_account(prepared_case, monkeypatch):
    from taobao_publish.protocol_media import UploadLedger
    _, prepared, _ = prepared_case
    originals = {(receipt.name, receipt.sha256): {'url': receipt.url, 'picture_id': str(index)}
                 for index, receipt in enumerate(prepared.receipts, 1)}
    monkeypatch.setattr(UploadLedger, 'load', lambda: SimpleNamespace(lookup=lambda identity:
        originals.get((identity['name'], identity['sha256']))))
    groups = {}
    for receipt in prepared.receipts:
        groups.setdefault(receipt.folder, []).append({'name': receipt.name, 'url': receipt.url})
    monkeypatch.setattr(media_library, 'product_root_path', lambda *args, **kwargs: [prepared.manifest.folder_name])
    monkeypatch.setattr(media_library, 'read_directory', lambda *args, **kwargs: {'supported': True, 'paths': [[prepared.manifest.folder_name]]})
    monkeypatch.setattr(media_library, 'read_directory_files', lambda client, directory, **kwargs: {'files': groups[tuple(directory)]})
    send = Mock(side_effect=AssertionError('已有素材不得再次发送目录'))
    monkeypatch.setattr(module, 'send_directory', send)
    result = module.import_directory(None, prepared.manifest, 'account-A', authorization=AUTH)
    assert all(not receipt.uploaded_now for receipt in result.receipts)
    groups[prepared.receipts[0].folder][0]['url'] = 'https://img.example.invalid/wrong.jpg'
    # 同名但身份对不上 → 必须如实失败（措辞与协议路线 verify_against_gallery 一致），
    # 既不重传整个目录，也不覆盖云端那张。
    with pytest.raises(page.PageError, match='不是同一张图'):
        module.import_directory(None, prepared.manifest, 'account-A', authorization=AUTH)
    send.assert_not_called()


def test_unloaded_tree_does_not_mean_product_folder_is_absent(prepared_case, monkeypatch):
    monkeypatch.setattr(media_library, 'read_directory', lambda *args, **kwargs: {'supported': True, 'paths': []})
    sender = Mock()
    monkeypatch.setattr(module, 'send_directory', sender)
    with pytest.raises(page.PageError, match='空树'):
        module.import_directory(None, prepared_case[1].manifest, 'account-A', authorization=AUTH)
    sender.assert_not_called()


def test_directory_inventory_retains_picture_id_for_direct_selection(browser):
    from test_uploaded_media_subdirectories import grouped_gallery
    grouped_gallery(browser, '目录图片身份')
    browser.evaluate("addCard('主图.jpg','https://img.example.invalid/main.jpg')")
    inventory = page.list_media_images(browser, context_id=None)
    assert inventory['files'][0]['name'] == '主图.jpg'
    assert inventory['files'][0]['picture_id'] == '0000000001'
    assert browser.evaluate('window.selectCalls') == 0


def test_material_ready_waits_for_actual_tree_nodes(browser):
    browser.evaluate("document.body.innerHTML='<div role=tree style=\"height:100px\"></div>'")
    assert browser.evaluate(module.MATERIAL_READY_EXPRESSION) is False
    browser.evaluate("document.querySelector('[role=tree]').innerHTML='<div role=treeitem>智能创作</div>'")
    assert browser.evaluate(module.MATERIAL_READY_EXPRESSION) is True
    browser.evaluate("document.querySelector('[role=tree]').setAttribute('aria-busy','true')")
    assert browser.evaluate(module.MATERIAL_READY_EXPRESSION) is False


@pytest.fixture
def pipeline_case(tmp_path, monkeypatch):
    local = make_local(tmp_path)
    local.product_dir = str(tmp_path)
    make_image(tmp_path / 'sku.jpg', (800, 800))
    manifest = build_media_manifest(1, str(tmp_path))
    prepared = PreparedProductMedia(manifest, 'account-A', tuple(
        UploadedImageReceipt(source.relative_path, Path(source.relative_path).name,
            (manifest.folder_name, *Path(source.relative_path).parts[:-1]),
            'https://img.example.invalid/' + source.sha256 + '.jpg', source.sha256)
        for source in manifest.images), publish_target_id='new-tab')
    events = []
    def stage(name, ctx, **kwargs):
        events.append(name)
        return stages.StageRun(name, stages.StageOutcome.failed('LOCAL_TEST_STOP', '隔离阶段边界'))
    monkeypatch.setattr(pipeline, 'run_stage', stage)
    prepare = Mock(side_effect=lambda *args: events.append('prepare_media') or prepared)
    return SimpleNamespace(local=local, prepared=prepared, prepare=prepare, events=events)


def test_pipeline_material_phase_precedes_all_publish_stages(pipeline_case):
    model = pipeline_case
    progress = []
    result = pipeline.run(model.local, make_request(), dry_run=False, authorization=AUTH,
        account_profile='account-A', media_preparer=model.prepare,
        progress_callback=lambda pct, *args: progress.append(pct))
    assert result.stage == 'session', result.to_dict()
    assert model.events == ['prepare_media', 'session']
    assert result.steps[0].status == 'ok'
    assert progress == sorted(progress) and progress[:2] == [15, 30]


@pytest.mark.parametrize('options', [{'start_from': 'invalid'}, {'skip_stages': ['invalid']}, {'start_from': 'fill_props'}])
def test_invalid_or_resumed_plan_never_uploads_before_validation(pipeline_case, options):
    model = pipeline_case
    with pytest.raises(TaobaoPublishError, match='阶段|继续填写'):
        pipeline.run(model.local, make_request(), dry_run=False, authorization=AUTH,
            account_profile='account-A', media_preparer=model.prepare, **options)
    model.prepare.assert_not_called()
    assert not model.events


@pytest.mark.parametrize('mode', ['unauthorized', 'cancelled', 'dry_run'])
def test_no_upload_without_authorized_active_write_run(pipeline_case, mode):
    model = pipeline_case
    result = pipeline.run(model.local, make_request(), dry_run=mode == 'dry_run',
        authorization=WriteAuthorization.none() if mode == 'unauthorized' else AUTH,
        should_cancel=(lambda: True) if mode == 'cancelled' else None,
        account_profile='account-A', media_preparer=model.prepare)
    model.prepare.assert_not_called()
    assert result.stage == ('session' if mode == 'dry_run' else 'prepare_media')


def test_pinned_publish_tab_is_used_even_when_old_page_is_first(monkeypatch):
    url = module.PUBLISH_WORKBENCH_URL
    targets = [{'id': key, 'type': 'page', 'url': url, 'webSocketDebuggerUrl': 'ws://isolated/' + key}
               for key in ['old-tab', 'new-tab']]
    monkeypatch.setattr(cdp, 'list_targets', lambda *args, **kwargs: targets)
    client = SimpleNamespace(health_check=lambda **kwargs: True)
    connect = Mock(return_value=client)
    monkeypatch.setattr(page.PageClient, 'connect', connect)
    ctx = SimpleNamespace(cdp_list_url='http://isolated.invalid/', prepared_media=SimpleNamespace(publish_target_id='new-tab'))
    assert stages._open_publish_page(ctx, wait_form=False) is client
    assert connect.call_args.args[0] == 'ws://isolated/new-tab'
    assert cdp.probe_session('http://isolated.invalid/', target_id='new-tab', require_publish_page=True).target_count == 1
    ctx.prepared_media.publish_target_id = 'missing'
    with pytest.raises(page.PageError): stages._open_publish_page(ctx, wait_form=False)
    assert not cdp.probe_session('http://isolated.invalid/', target_id='missing', require_publish_page=True).publish_target_found

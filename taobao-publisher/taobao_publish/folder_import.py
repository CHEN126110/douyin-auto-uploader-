# -*- coding: utf-8 -*-
"""先在独立素材页整目录导入，再进入发布页。

目录输入/原生拖放能力已有隔离浏览器证据；当前淘宝 DOM 路线仍为 candidate。
一次发送目录后必须读到本批队列完成、真实目录和文件回执，不自动重传或改成逐层建目录。
"""
from collections import Counter
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path, PurePosixPath
import time
from urllib.parse import urlsplit

from . import page
from .constants import WRITE_UPLOAD_IMAGE, PUBLISH_WORKBENCH_URL
from .errors import TaobaoPublishError
from .media_manifest import (PreparedProductMedia, UploadedImageReceipt, build_media_manifest,
                             snapshot_media_batch)

MATERIAL_CENTER_URL = 'https://qn.taobao.com/home.htm/material-center/mine-material/sucai-tu?from=sucaitu'
MATERIAL_READY_EXPRESSION = r'''(() => {
    const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);
      return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';};
    const trees=Array.from(document.querySelectorAll('[role=tree],.next-tree')).filter(visible)
      .filter(el=>!el.parentElement.closest('[role=tree],.next-tree'));
    if(document.readyState!=='complete'||trees.length!==1)return false;
    const tree=trees[0];
    return !tree.closest('[aria-busy=true]') && !tree.querySelector('[aria-busy=true]')
      && Array.from(tree.querySelectorAll('[role=treeitem],.next-tree-node')).some(visible);
})()'''


def _cancelled(should_cancel):
    if should_cancel is not None and should_cancel():
        raise TaobaoPublishError('CANCELLED', '已取消素材准备，未进入发布页；已发送的平台上传队列可能仍在处理')


def queue_complete(queue, names, directory_names=()):
    """新建的空队列中，同名文件按数量核对，目录归属稍后逐路径验证。"""
    wanted=Counter(names)
    rows=queue['items']
    failed=[row for row in rows if row['state']=='error']
    if failed:
        raise TaobaoPublishError('IMAGE_UPLOAD_FAILED','整目录导入被平台拒绝：'+'；'.join(
            str(row['name'])+'：'+str(row.get('desc') or '上传失败') for row in failed[:3]))
    unexpected = [row['name'] for row in rows if row['name'] not in wanted
                  and row['name'] not in directory_names]
    if unexpected:
        raise page.PageError('整目录队列混入了本批之外的文件：' + '、'.join(unexpected[:3]))
    actual=Counter(row['name'] for row in rows if row['name'] in wanted)
    if any(actual[name]>count for name,count in wanted.items()):
        raise page.PageError('整目录队列包含超出本批清单的同名文件，不能确认来源')
    accepted=Counter(row['name'] for row in rows if row['name'] in wanted and row['state']=='success')
    return (bool(wanted) and accepted==wanted and queue.get('uploading') is not True
            and all(row['state']=='success' for row in rows))


def _open_panel(client):
    result=client.evaluate(r'''(() => {
      const visible=el=>{const r=el.getBoundingClientRect();return r.width>0&&r.height>0;};
      const panels=Array.from(document.querySelectorAll('[class*="UploadPanel_uploadPanel"]')).filter(visible);
      if(panels.length===1)return {ok:true};
      if(panels.length)return {ok:false,reason:'upload_panel_not_unique'};
      const buttons=Array.from(document.querySelectorAll('button,[role="button"]')).filter(visible)
        .filter(el=>(el.textContent||'').trim()==='上传文件');
      if(buttons.length!==1)return {ok:false,reason:'upload_entry_not_unique'};
      const button=buttons[0];
      if(button.disabled||button.getAttribute('aria-disabled')==='true'||(button.form&&button.type!=='button'))
        return {ok:false,reason:'upload_entry_unavailable'};
      button.click();return {ok:true};
    })()''')
    if not isinstance(result,dict) or result.get('ok') is not True:
        raise page.PageError('素材中心没有唯一可用的上传入口：'+str(result))
    deadline=time.monotonic()+10
    while True:
        present=client.evaluate("Array.from(document.querySelectorAll('[class*=\"UploadPanel_uploadPanel\"]')).filter(el=>el.getBoundingClientRect().height>0).length")
        if present==1:return
        if time.monotonic()>=deadline:raise page.PageError('素材中心上传面板未打开')
        time.sleep(0.1)


def send_directory(client, directory):
    """只发送一次真实文件夹。普通 multiple 输入不支持目录，绝不把目录路径塞进去。"""
    target=client.evaluate(r'''(() => {
      const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);
        return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
      const panels=Array.from(document.querySelectorAll('[class*="UploadPanel_uploadPanel"]')).filter(visible);
      if(panels.length!==1)return {ok:false,reason:'upload_panel_not_unique'};
      const inputs=Array.from(panels[0].querySelectorAll('input[type="file"][webkitdirectory]')).filter(el=>!el.disabled);
      if(inputs.length>1)return {ok:false,reason:'directory_input_not_unique'};
      if(inputs.length===1){
        if(document.querySelectorAll('[class*="UploadPanel_uploadPanel"] input[type="file"][webkitdirectory]:not(:disabled)').length!==1)
          return {ok:false,reason:'directory_input_not_unique'};
        return {ok:true,method:'directory_input'};
      }
      const zones=Array.from(panels[0].querySelectorAll('[class*="UploadPanel_uploadPart"]')).filter(visible);
      if(zones.length!==1)return {ok:false,reason:'folder_drop_zone_not_unique'};
      const zone=zones[0];zone.scrollIntoView({block:'center',inline:'center'});
      const r=zone.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2;
      const top=document.elementFromPoint(x,y);
      if(!top||!zone.contains(top))return {ok:false,reason:'folder_drop_zone_covered'};
      return {ok:true,method:'native_directory_drop',x,y};
    })()''')
    if not isinstance(target,dict) or target.get('ok') is not True:
        raise page.PageError('整文件夹导入入口无法确认：'+str(target))
    if target['method']=='directory_input':
        client.set_file_input_files([str(directory)],
            '[class*="UploadPanel_uploadPanel"] input[type="file"][webkitdirectory]:not(:disabled)')
    else:
        client.send('Page.bringToFront')
        data={'items':[],'files':[str(directory)],'dragOperationsMask':1}
        for event in ('dragEnter','dragOver','drop'):
            client.send('Input.dispatchDragEvent',{'type':event,'x':target['x'],'y':target['y'],'data':data})
    return target['method']


def _read_receipts(client, manifest, root, *, previous=None, should_cancel=None):
    """每个图片目录只读一次。旧账本必须与当前账户图库中的实际资源一致。"""
    from . import media_library
    from .upload_api import same_image
    grouped = {}
    for source in manifest.images:
        grouped.setdefault(PurePosixPath(source.relative_path).parts[:-1], []).append(source)
    receipts = []
    for folder, sources in grouped.items():
        _cancelled(should_cancel)
        contents = media_library.read_directory_files(client, [*root, *folder], context_id=None,
                                                      page=media_library.PAGE_MATERIAL_CENTER)
        files = {entry['name']: entry for entry in contents['files']}
        if len(files) != len(contents['files']):
            raise page.PageError('商品子目录存在同名图片，无法确认来源：' + '/'.join(folder))
        for source in sources:
            name = PurePosixPath(source.relative_path).name
            actual = files.get(name)
            if actual is None:
                raise page.PageError('图片空间缺少原目录图片：' + source.relative_path)
            picture_id = str(actual.get('picture_id') or '')
            if previous is not None:
                old = previous.get(source.relative_path)
                if old is None or not same_image(actual['url'], old['url']):
                    raise page.PageError('已有同名目录的图片与本批上传回执不符：' + source.relative_path)
                if picture_id and old.get('picture_id') and picture_id != old['picture_id']:
                    raise page.PageError('已有图片 ID 与本批上传回执不符：' + source.relative_path)
                picture_id = picture_id or str(old.get('picture_id') or '')
            receipts.append(UploadedImageReceipt(source.relative_path, name, (manifest.folder_name, *folder),
                actual['url'], source.sha256, uploaded_now=previous is None, picture_id=picture_id))
    return tuple(receipts)


def _reuse_existing(client, manifest, root, account_profile, *, should_cancel=None):
    """迁移旧协议上传的回执；仅文件名相同不够，摘要和当前云端资源也必须相同。"""
    from .protocol_media import UploadLedger
    ledger = UploadLedger.load()
    previous = {}
    for source in manifest.images:
        receipt = ledger.lookup({'name': PurePosixPath(source.relative_path).name, 'sha256': source.sha256})
        if receipt is None:
            raise page.PageError('图片空间已存在同名商品目录，但缺少本批素材回执：' + source.relative_path
                + '；未重复导入或自动合并')
        previous[source.relative_path] = receipt
    receipts = _read_receipts(client, manifest, root, previous=previous, should_cancel=should_cancel)
    prepared = PreparedProductMedia(manifest, account_profile, receipts)
    prepared.validate(account_profile)
    return prepared


def import_directory(client, manifest, account_profile, *, authorization, progress=None,
                     should_cancel=None, timeout=300.0):
    from . import media_library
    from .upload_panel import ensure_all_images
    authorization.require(WRITE_UPLOAD_IMAGE)
    _cancelled(should_cancel)
    tree = media_library.read_directory(client, context_id=None)
    if not tree.get('supported') or not tree.get('paths'):
        raise page.PageError('素材中心目录尚未加载，不能把空树当作商品目录不存在')
    root = media_library.product_root_path(client, manifest.folder_name, context_id=None,
                                          page=media_library.PAGE_MATERIAL_CENTER)
    if root:
        prepared = _reuse_existing(client, manifest, root, account_profile, should_cancel=should_cancel)
        if progress: progress('原商品目录已有完整素材，已核对旧回执与当前图片空间，不重复上传')
        return prepared
    _open_panel(client)
    ensure_all_images(client,context_id=None)
    if page.read_media_queue_state(client,context_id=None)['items']:
        raise page.PageError('上传面板已有队列，未混入新的商品目录')
    names=[PurePosixPath(image.relative_path).name for image in manifest.images]
    directory_names = {manifest.folder_name, *(PurePosixPath(path).name for path in manifest.directories)}
    with snapshot_media_batch([manifest], retain_on_error=True) as folders:
        if progress:progress('整目录导入：{}，{} 张图片'.format(manifest.folder_name,len(names)))
        method=send_directory(client,folders[0])
        started=time.monotonic()
        previous_count = None
        while True:
            _cancelled(should_cancel)
            queue=page.read_media_queue_state(client,context_id=None)
            if queue_complete(queue,names,directory_names):break
            completed = sum(row['state']=='success' and row['name'] in names for row in queue['items'])
            if completed != previous_count:
                if progress: progress('整目录上传：已完成 {} / {} 张图片'.format(completed, len(names)))
                previous_count = completed
            elapsed=time.monotonic()-started
            if not queue['items'] and elapsed>=10:
                raise TaobaoPublishError('IMAGE_UPLOAD_FAILED','页面未接收本次整文件夹导入，上传队列为空；未进入发布页或改走逐层建目录')
            if elapsed>=timeout:
                raise TaobaoPublishError('IMAGE_UPLOAD_FAILED','整目录上传队列未完成，未进入发布页')
            time.sleep(0.25)
        if not queue_complete(page.read_media_queue_state(client,context_id=None),names,directory_names):
            raise TaobaoPublishError('IMAGE_UPLOAD_FAILED','完成前上传队列发生变化，未确认成功')
        page.click_media_finish(client,context_id=None,wait=0.3)
        deadline=time.monotonic()+15
        root=None
        while root is None:
            _cancelled(should_cancel)
            root=media_library.product_root_path(client,manifest.folder_name,context_id=None,
                                                page=media_library.PAGE_MATERIAL_CENTER)
            if root is not None:break
            if time.monotonic()>=deadline:raise page.PageError('上传队列已完成，但图片空间未出现原商品文件夹')
            time.sleep(0.2)
        receipts = _read_receipts(client, manifest, root, should_cancel=should_cancel)
    result=PreparedProductMedia(manifest,account_profile,tuple(receipts))
    result.validate(account_profile)
    if progress:progress('商品目录与 {} 张图片已确认入库（{}）'.format(len(receipts),method))
    return result


def make_preparer(account_profile, cdp_list_url):
    """构造阶段回调；构造本身不访问浏览器。"""
    def prepare(local,item,authorization,progress,should_cancel):
        from .cdp_ws import CdpBrowser
        from src.runtime_paths import resolve_data_file
        authorization.require(WRITE_UPLOAD_IMAGE)
        if not account_profile:raise ValueError('素材准备必须绑定当前淘宝账户')
        endpoint=urlsplit(cdp_list_url)
        if endpoint.hostname not in ('127.0.0.1','localhost') or not endpoint.port:
            raise ValueError('素材准备没有当前账户的本地浏览器地址')
        manifest=build_media_manifest(local.record_id,local.product_dir)
        cache_dir=Path(resolve_data_file('taobao_folder_import_receipts'))
        cache_key=hashlib.sha256(account_profile.encode('utf-8')).hexdigest()+'-'+manifest.digest+'.json'
        cached=cache_dir/cache_key
        prepared=None
        if cached.is_file():
            payload=json.loads(cached.read_text(encoding='utf-8'))
            receipts=tuple(UploadedImageReceipt(**{**entry,'folder':tuple(entry['folder'])}) for entry in payload['receipts'])
            if payload.get('manifest_digest') != manifest.digest:
                raise ValueError('素材缓存与本批目录摘要不一致')
            prepared=PreparedProductMedia(manifest,payload['account_profile'],
                tuple(replace(receipt, uploaded_now=False) for receipt in receipts))
            prepared.selection_plan(item,account_profile)
        _cancelled(should_cancel)
        browser=CdpBrowser(port=endpoint.port,host=endpoint.hostname)
        client=None
        try:
            material_targets=[target for target in browser.list_targets() if target.kind=='page'
                and urlsplit(target.url).hostname=='qn.taobao.com'
                and '/material-center/mine-material/sucai-tu' in urlsplit(target.url).path]
            target=material_targets[0] if len(material_targets)==1 else browser.new_page(MATERIAL_CENTER_URL)
            client=page.PageClient.connect(target.web_socket_url,target_url=target.url)
            if prepared is None:
                deadline=time.monotonic()+30
                while not client.evaluate(MATERIAL_READY_EXPRESSION):
                    _cancelled(should_cancel)
                    if time.monotonic()>=deadline:raise page.PageError('素材中心尚未就绪，请完成登录后再试')
                    time.sleep(0.2)
                prepared=import_directory(client,manifest,account_profile,authorization=authorization,
                    progress=progress,should_cancel=should_cancel)
                prepared.selection_plan(item,account_profile)
                cache_dir.mkdir(parents=True,exist_ok=True)
                temp=cached.with_suffix('.tmp')
                temp.write_text(json.dumps({'account_profile':account_profile,
                    'manifest_digest':manifest.digest,
                    'receipts':[asdict(receipt) for receipt in prepared.receipts]},ensure_ascii=False),encoding='utf-8')
                temp.replace(cached)
            elif progress:
                progress('复用本账户、本批文件的完整目录回执，不重复上传')
            _cancelled(should_cancel)
            # 只有完整目录上传成功/完整缓存验证通过才允许进入发布入口。
            client.navigate(PUBLISH_WORKBENCH_URL,wait=1)
            return replace(prepared,publish_target_id=target.target_id)
        finally:
            if client is not None:client.close()
            browser.close()
    return prepare

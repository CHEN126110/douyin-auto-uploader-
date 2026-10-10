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


def _queue_rows_judgement(queue, names, directory_names=()):
    """队列**行级判据**（`queue_complete` 与 `queue_evidence_complete` 共用）。

    任何一条不成立就抛错——不把它降级成「返回 False」，否则真实的平台拒绝会被
    「还没传完」这种模糊判断盖掉。
    """

    wanted = Counter(names)
    rows = queue['items']
    failed = [row for row in rows if row['state'] == 'error']
    if failed:
        raise TaobaoPublishError('IMAGE_UPLOAD_FAILED', '整目录导入被平台拒绝：' + '；'.join(
            str(row['name']) + '：' + str(row.get('desc') or '上传失败') for row in failed[:3]))
    unexpected = [row['name'] for row in rows if row['name'] not in wanted
                  and row['name'] not in directory_names]
    if unexpected:
        raise page.PageError('整目录队列混入了本批之外的文件：' + '、'.join(unexpected[:3]))
    actual = Counter(row['name'] for row in rows if row['name'] in wanted)
    if any(actual[name] > count for name, count in wanted.items()):
        raise page.PageError('整目录队列包含超出本批清单的同名文件，不能确认来源')
    accepted = Counter(row['name'] for row in rows if row['name'] in wanted and row['state'] == 'success')
    return accepted, wanted


def queue_complete(queue, names, directory_names=()):
    """新建的空队列中，同名文件按数量核对，目录归属稍后逐路径验证。

    **严格版**：还要求面板的 ``uploading`` 横幅消失。真机上这句横幅会在队列全部
    成功之后仍然挂着（见 :func:`queue_evidence_complete`），所以生产路径不要只看这一条。
    """

    accepted, wanted = _queue_rows_judgement(queue, names, directory_names)
    return (bool(wanted) and accepted == wanted and queue.get('uploading') is not True
            and all(row['state'] == 'success' for row in queue['items']))


#: 「按证据收口」需要的稳定窗口（秒）：行集合与状态连续不变这么久，才认为队列真的传完了。
_QUEUE_SETTLE_SECONDS = 3.0


def queue_evidence_complete(queue, names, directory_names=()):
    """**按证据**判断整目录队列是否传完：每张图的成功数正好等于清单、且没有非 success 行。

    与 :func:`queue_complete` 的差别只有一条：**不要求 ``uploading`` 横幅消失**。
    真机 2026-10-10：33 张全部 success、队列 39 行全绿，面板仍挂着
    「39 个文件上传中...」，`uploading` 永远为 True——严格判据会把已经传完的队列
    一直等到 300 秒超时，用户看到的就是「已完成 33 / 33 张图片」之后卡住不动。

    横幅是平台的提示文案，**行状态才是证据**。为避免在行还在陆续到达时抢跑，
    调用方必须再叠一个「行集合连续稳定若干秒」的窗口（见 ``_queue_signature``）。
    """

    accepted, wanted = _queue_rows_judgement(queue, names, directory_names)
    return (bool(wanted) and accepted == wanted
            and all(row['state'] == 'success' for row in queue['items']))


def _queue_signature(queue):
    """队列的稳定判据：每行的「名字 + 状态」。行集合或状态一变，签名就变。"""

    return tuple((str(row.get('name')), str(row.get('state'))) for row in (queue.get('items') or []))


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


#: 点击目录后等平台自己的 `file.query` / `dir.query` 回来。
_LISTING_OBSERVE_SECONDS = 4.0


def _cloud_files(client, listing, path, *, folder_id):
    """读某一层云端的**文件清单**，权威来源是平台自己的 ``file.query``。

    DOM 只负责**触发导航**（点目录树），清单本身取自 ``fileModule``。

    ⚠️ 页面**已经停在这一层**时，再点它是不会重发请求的（真机 2026-10-10 实测：
    于是读数恒为「读不出来」）。所以读不到就先退回上一层再进一次，逼它重新拉一遍。

    :returns: 文件条目列表；**返回 ``None`` 表示「读不出来」**——与「目录是空的」（``[]``）
        是两件不同的事。调用方必须区分：把读不出来当成空目录，就会重复上传（真机踩过）。
    """

    from . import media_library
    if listing is None:
        # 没有收响应的能力时**不要点**：调用方会退回 DOM 读取，而 DOM 读取自带导航。
        return None
    media_library.open_directory(client, path, context_id=None,
                                 page=media_library.PAGE_MATERIAL_CENTER)
    listing.observe(_LISTING_OBSERVE_SECONDS)
    entries = listing.files(folder_id)
    if entries is not None:
        return entries
    # 强制重拉：退回上一层（或根层）再进来一次。
    parent = list(path[:-1])
    try:
        if parent:
            media_library.open_directory(client, parent, context_id=None,
                                         page=media_library.PAGE_MATERIAL_CENTER)
        else:
            media_library.open_root_directory(client, context_id=None)
        listing.observe(_LISTING_OBSERVE_SECONDS)
        media_library.open_directory(client, path, context_id=None,
                                     page=media_library.PAGE_MATERIAL_CENTER)
        listing.observe(_LISTING_OBSERVE_SECONDS)
    except Exception:  # noqa: BLE001 - 重拉失败就如实返回「读不出来」
        return None
    return listing.files(folder_id)


#: 权威清单读不到时的**如实**报错文案（不是「目录是空的」）。
_NO_LISTING = ('没有读到平台对目录 {} 的文件清单响应（file.query）：'
               '读不到不等于目录是空的，拒绝据此判断缺图或重传')


def _cloud_product_root(client, listing, folder_name):
    """商品目录在云端到底存不存在。**返回 ``[名字]`` / ``None`` / 抛错**。

    判据优先级（真机 2026-10-10：这里误判一次，云端就多一个同名目录 + 33 张重传）：

    1. 平台自己的 ``dir.query`` 说了算——它列出**全部**目录（含 id），不受虚拟列表影响；
    2. 读到了目录清单、里面确实没有这个名字 → 才是「不存在」，可以走整目录导入；
    3. **没读到目录清单**（``dir_responses == 0``）→ 先点回根层、再**刷新一次**把它逼出来
       （平台只在页面加载时发目录清单）；两条都不行才**如实失败**，
       绝不把「读不出来」当成「不存在」。
    """

    from . import media_library
    if listing is None:
        return media_library.product_root_path(client, folder_name, context_id=None,
                                               page=media_library.PAGE_MATERIAL_CENTER)
    if listing.dir_responses == 0:
        # 页面可能早就开着、这次没重新拉目录——先点回根层试一次（点，不刷新）。
        try:
            media_library.open_root_directory(client, context_id=None)
        except Exception:  # noqa: BLE001
            pass
        listing.observe(_LISTING_OBSERVE_SECONDS)
    if listing.dir_responses == 0:
        # 还是没有：目录清单只在**页面加载**时发一次，所以刷新一次把它逼出来。
        # 这一步只发生在 `import_directory` 刚进来、页面还没被动过的时候；
        # 没有权威目录树就判「没有这个商品目录」= 云端多一个同名目录 + 全部图片重传。
        try:
            listing.reload_and_observe()
        except Exception:  # noqa: BLE001
            pass
    matches = listing.find_directories(folder_name)
    if len(matches) > 1:
        raise page.PageError('图片空间存在多个同名商品目录，不能确认该用哪一个：' + folder_name)
    if matches:
        return [folder_name]
    if listing.dir_responses == 0:
        # 刷新都拿不到清单：这时**只能**接受 DOM 的**肯定**结论（看见了就是看见了），
        # 看不见则如实失败——绝不把「读不出来」当成「不存在」。
        dom = media_library.product_root_path(client, folder_name, context_id=None,
                                              page=media_library.PAGE_MATERIAL_CENTER)
        if dom:
            return dom
        raise page.PageError(
            '没有读到平台对图片空间的目录清单响应（dir.query）：读不到不等于目录不存在，'
            '拒绝据此走整目录导入（那会在云端新建同名目录并重传全部图片）')
    return None


def _read_receipts(client, manifest, root, *, previous=None, should_cancel=None, listing=None):
    """每个图片目录只读一次。旧账本必须与当前账户图库中的实际资源一致。"""
    from . import media_library
    from .upload_api import same_image
    grouped = {}
    for source in manifest.images:
        grouped.setdefault(PurePosixPath(source.relative_path).parts[:-1], []).append(source)
    receipts = []
    for folder, sources in grouped.items():
        _cancelled(should_cancel)
        # 目录 id 从平台自己的目录树里按 `pid` + 名字取（DOM 点击只负责触发 file.query）。
        folder_id = None
        if listing is not None:
            roots = listing.find_directories(manifest.folder_name)
            if len(roots) == 1:
                node = roots[0]
                for part in folder:
                    node = listing.find_child(node['id'], str(part))
                    if node is None:
                        break
                folder_id = node['id'] if node else None
        entries = _cloud_files(client, listing, [*root, *folder], folder_id=folder_id)
        if entries is None:
            if listing is not None:
                raise page.PageError(_NO_LISTING.format('/'.join([*root, *folder])))
            contents = media_library.read_directory_files(
                client, [*root, *folder], context_id=None,
                page=media_library.PAGE_MATERIAL_CENTER)
            entries = contents['files']
        files = {entry['name']: entry for entry in entries}
        if len(files) != len(entries):
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


def _folder_id_for(client, root, parts):
    """拿到（必要时建出）``root/parts…`` 的 folderId。已存在就返回，不重复建。"""

    from . import media_library
    folder_id = ""
    for index, part in enumerate(parts, start=1):
        folder_id = media_library.ensure_child_directory(
            client, [*root, *parts[:index - 1]], str(part), context_id=None)
    return folder_id


def _content_matches(entry, manifest, source):
    """**按内容**判同一张图：平台给的 ``md5`` 与本地文件逐字节一致。

    为什么需要它（真机 2026-10-10 实测）：平台把*整目录导入*的图片重新上传过一次，
    同一张图的资源号变了（``O1CN01…`` 不同），于是「比 URL 身份」会把
    **内容完全相同**的图判成「不是同一张图」，用户明明什么都没做错却被卡住。
    平台在 ``fileModule`` 里给了 ``md5``，实测与本地文件 md5 逐张一致（SKU 5/5 ✓），
    所以这里不用下载也能判定；**拿不到 md5 就不算同一张图**（不猜）。
    """

    digest = str(entry.get('md5') or '')
    if not digest:
        return False
    path = Path(manifest.product_dir) / source.relative_path
    if not path.is_file():
        return False
    actual = hashlib.md5()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            actual.update(chunk)
    return actual.hexdigest() == digest


def _complete_existing(client, manifest, root, account_profile, *, port, authorization,
                       progress=None, should_cancel=None, listing=None):
    """云端已有该商品目录时：**按证据决定哪些图要补传**。

    ## 为什么不能"有目录就当成已完成"，也不能"整目录重来"

    真机 2026-10-10（``ID-986833932804``）：三个角色目录都在，folderId 与上传账本逐字相同，
    但目录里**一个文件都没有**——平台自己的 ``file.query`` 对三个 catId 都返回 0，
    而账本里的旧回执还指着这三个目录。此时：
    * 直接复用旧回执 → 把"目录在"当成"图在"，发布出去的是没有图的商品；
    * 整目录重传 → 同名目录是**合并还是新建重复目录，平台语义未取证**（见阻塞项），不许赌；
    * 直接失败 → 用户明明什么都没做错，只是空间里的图没了，却被告知"去建那个已存在的目录"。

    所以按证据做**最小动作**：

    * 用途目录**不存在** → 先在素材中心建出来（`ensure_child_directory` 幂等，
      与协议路线 `ensure_cloud_folders` 同一动作、同一道写授权门），再读它的文件；
    * 云端**没有**的同名文件 → 用已验证的 ``upload.api``（E-212/E-216/E-221/E-247）
      直接传进它该去的那个 ``folderId``，传完**回读核对** URL 才算落库，并写进账本；
    * 云端**有**同名文件 → 身份判定两条路：**URL 身份**（账本回执与云端同资源号）
      或**内容身份**（平台 ``fileModule`` 的 ``md5`` 与本地文件逐字节一致，实测 SKU 5/5 一致）。
      两条都不成立才**如实失败**——不覆盖、不改名、不将就。
      内容一致但资源号变了，说明平台把同一张图重传过（整目录导入就是），
      这时把**这次观测到**的回执记进账本，下一次核对就是干净的。

    每一步都过写授权门（``upload_image``）；没有授权时一个字节都不会发出去。
    """

    from . import media_library
    from .protocol_media import UploadLedger, default_pace_seconds
    from .upload_api import UploadCandidate, same_image

    grouped = {}
    for source in manifest.images:
        grouped.setdefault(PurePosixPath(source.relative_path).parts[:-1], []).append(source)

    ledger = UploadLedger.load()
    receipts = []
    pending = []
    for folder, sources in grouped.items():
        _cancelled(should_cancel)
        # ⚠️ **必须先确保目录存在，再读它**（2026-10-10 真机踩到）：
        # 本地新生成的 `白底图/`、`SKU_1x1/` 在云端还没有目录，先读会直接报
        # `判据=directory_missing`——而建目录本来就是协议路线的既定动作
        # （`ensure_cloud_folders` 就是这么做的，E-287），且与上传共用同一道
        # 写授权门（`import_directory` 开头已 `require(WRITE_UPLOAD_IMAGE)`）。
        # 已存在时 `ensure_child_directory` 幂等，不会建出重复目录。
        # ⚠️ 商品目录**根层**也会放图（白底图工具的 `白底图.jpg` 就落在这一层）：
        # 它的 folderId 不是空串，而是商品目录自己的 id。
        if folder:
            folder_id = _folder_id_for(client, root, folder)
        else:
            folder_id = ""
            if listing is not None:
                matches = listing.find_directories(manifest.folder_name)
                if len(matches) == 1:
                    folder_id = matches[0]['id']
            if not folder_id:
                raise page.PageError('商品目录根层有图片，但没读到该商品目录的 id（dir.query），'
                                     '无法核对这一层：' + manifest.folder_name)
        # 文件清单以平台自己的 `file.query` 为准（DOM 一刷新就读不到，真机踩过）；
        # 读不到响应时才退回 DOM 读取，而 DOM 的「空」由下面的守卫兜住（拒绝重传）。
        entries = _cloud_files(client, listing, [*root, *folder], folder_id=folder_id)
        if entries is None:
            if listing is not None:
                # 有收响应的能力却读不到清单：**不许**拿 DOM 的读数顶上（那个页面读不准，
                # 而且「读不到」会被误当成「目录是空的」→ 重复上传）。如实失败。
                raise page.PageError(_NO_LISTING.format('/'.join([*root, *folder])))
            contents = media_library.read_directory_files(
                client, [*root, *folder], context_id=None,
                page=media_library.PAGE_MATERIAL_CENTER)
            entries = contents['files']
        files = {entry['name']: entry for entry in entries}
        if len(files) != len(entries):
            raise page.PageError('商品子目录存在同名图片，无法确认来源：' + '/'.join(folder))
        missing = []
        suspicious = []
        for source in sources:
            name = PurePosixPath(source.relative_path).name
            actual = files.get(name)
            if actual is None:
                # ⚠️ **读不到 ≠ 不存在**（2026-10-10 真机踩过，代价是 5 张重复素材）：
                # 账本记录这张图**就传在这个目录里**，页面却读不到它——两者不可能同时为真，
                # 说明是读取器读不出来（素材中心的文件列表与选图器不同套 class）。
                # 此时**拒绝重传**：重传只会造出同名重复素材，比停下来更难收拾。
                old_receipt = ledger.lookup({'name': name, 'sha256': source.sha256})
                if old_receipt is not None and str(old_receipt.get('folder_id') or '') == str(folder_id):
                    suspicious.append(source.relative_path)
                else:
                    missing.append(source)
                continue
            old = ledger.lookup({'name': name, 'sha256': source.sha256})
            # 身份判定两条路：**URL 身份**（账本回执与云端同资源号）或**内容身份**
            # （平台给的 md5 与本地文件逐字节一致）。后者是为了「平台把同一张图重传过、
            # 资源号变了」这种情形——真机 2026-10-10：整目录导入把 33 张全重传了一遍，
            # 只比 URL 会把内容完全相同的图判成「不是同一张图」，把用户无故卡住。
            same_as_receipt = old is not None and same_image(actual['url'], old['url'])
            if not same_as_receipt and not _content_matches(actual, manifest, source):
                if old is None:
                    raise page.PageError('图片空间已有同名素材，但账本里没有本批回执，'
                                         '内容也与本地文件不一致，不能确认是不是同一张图：'
                                         + source.relative_path)
                raise page.PageError('图片空间里的同名素材与本批上传回执不是同一张图：'
                                     '既不是同一个资源号，内容也与本地文件不一致：'
                                     + source.relative_path)
            if not same_as_receipt:
                # 内容一致 = 同一张图：把**这次观测到**的回执记进账本，下一次就是干净的。
                ledger.record({'name': name, 'sha256': source.sha256,
                               'path': str(Path(manifest.product_dir) / source.relative_path)},
                              {'url': actual['url'],
                               'picture_id': str(actual.get('picture_id') or '')},
                              folder_id=folder_id)
            receipts.append(UploadedImageReceipt(
                source.relative_path, name, (manifest.folder_name, *folder), actual['url'],
                source.sha256, uploaded_now=False,
                picture_id=str(actual.get('picture_id') or '')
                or str((old or {}).get('picture_id') or '')))
        if suspicious:
            raise page.PageError(
                '云端这一层读不到本该在里面的素材（{}）：账本记录它们就传在 {} 目录里。'
                '读不出来不等于不存在，**已拒绝重复上传**；'
                '请重载素材中心标签页后重试'.format('、'.join(suspicious[:3]), '/'.join(folder)))
        if missing:
            pending.append((folder_id, folder, missing))

    if pending:
        total = sum(len(item[2]) for item in pending)
        if progress:
            progress('云端已有该商品目录，其中 {} 张素材不在目录里，按用途补传'.format(total))
        from .cdp_ws import CdpBrowser
        from .upload_page import PictureSpacePageUploader, open_session
        if not port:
            raise TaobaoPublishError('IMAGE_UPLOAD_FAILED', '补传缺失素材需要当前账户的调试端口')
        browser = CdpBrowser(port=port)
        session = None
        try:
            session = open_session(browser)
            uploader = PictureSpacePageUploader(session)
            pace = default_pace_seconds()
            for folder_id, folder, sources in pending:
                _cancelled(should_cancel)
                candidates = []
                for source in sources:
                    path = Path(manifest.product_dir) / source.relative_path
                    candidates.append(UploadCandidate(
                        path=str(path), name=PurePosixPath(source.relative_path).name,
                        size=source.size, sha256=source.sha256))
                report = uploader.upload_batch(
                    candidates, folder_id=folder_id, authorization=authorization,
                    progress=(lambda message: progress(message) if progress else None),
                    pace_seconds=pace)
                if not report.ok:
                    detail = report.stopped_reason or '；'.join(
                        '{}：{}'.format(item.get('name'),
                                        item.get('message') or item.get('error_code'))
                        for item in report.failed[:3])
                    raise TaobaoPublishError(
                        'IMAGE_UPLOAD_FAILED',
                        '补传缺失素材失败（{}）：{}'.format('/'.join(folder), detail))
                by_name = {item.name: item for item in report.receipts}
                # 上传成功不算数：**回读**到同一个 URL 才算落库（与协议路线同一判据）。
                #
                # ⚠️ 协议上传是**页面外**发的请求，素材中心页并不知道（真机 2026-10-10：
                # 5 张全传成功，紧接着读该目录却仍是空的）。必须先进目录、再点一次
                # 当前目录让页面重拉这一层（`refresh_gallery` 就是为此而写），
                # 并给云端一点传播时间——有界重试，不无限等。
                deadline = time.monotonic() + 15.0
                files = {}
                while True:
                    media_library.open_directory(client, [*root, *folder], context_id=None,
                                                 page=media_library.PAGE_MATERIAL_CENTER)
                    media_library.refresh_gallery(client, context_id=None)
                    contents = media_library.read_directory_files(
                        client, [*root, *folder], context_id=None,
                        page=media_library.PAGE_MATERIAL_CENTER)
                    files = {entry['name']: entry for entry in contents['files']}
                    if all(PurePosixPath(source.relative_path).name in files
                           for source in sources):
                        break
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(1.0)
                for source in sources:
                    name = PurePosixPath(source.relative_path).name
                    receipt = by_name.get(name)
                    actual = files.get(name)
                    if receipt is None or actual is None:
                        raise page.PageError('补传后回读不到该素材：' + source.relative_path)
                    if not same_image(actual['url'], receipt.url):
                        raise page.PageError('补传后回读到的不是同一张图：' + source.relative_path)
                    ledger.record({'name': name, 'sha256': source.sha256,
                                   'path': str(Path(manifest.product_dir) / source.relative_path)},
                                  {'url': receipt.url, 'picture_id': receipt.picture_id},
                                  folder_id=folder_id)
                    receipts.append(UploadedImageReceipt(
                        source.relative_path, name, (manifest.folder_name, *folder),
                        receipt.url, source.sha256, uploaded_now=True,
                        picture_id=receipt.picture_id))
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:  # noqa: BLE001 - 关上传页失败不该掩盖补传结果
                    pass
            browser.close()

    prepared = PreparedProductMedia(manifest, account_profile, tuple(receipts))
    prepared.validate(account_profile)
    return prepared


def import_directory(client, manifest, account_profile, *, authorization, progress=None,
                     should_cancel=None, timeout=300.0, port=0):
    from . import media_library
    from .upload_panel import ensure_all_images
    authorization.require(WRITE_UPLOAD_IMAGE)
    _cancelled(should_cancel)
    tree = media_library.read_directory(client, context_id=None)
    if not tree.get('supported') or not tree.get('paths'):
        raise page.PageError('素材中心目录尚未加载，不能把空树当作商品目录不存在')
    # 目录存不存在，以平台自己的 `dir.query` 为准（DOM 树是虚拟列表，读不到就会误判成
    # 「没有这个目录」→ 走整目录导入 → **云端多一个同名目录 + 全部图片重传**）。
    listing = _attach_listing(port)
    try:
        root = _cloud_product_root(client, listing, manifest.folder_name)
        if root:
            # 目录在 ≠ 图在：逐张核对，缺的用协议上传补进它该去的那一层。
            prepared = _complete_existing(client, manifest, root, account_profile, port=port,
                                         authorization=authorization, progress=progress,
                                         should_cancel=should_cancel, listing=listing)
            if progress: progress('原商品目录与当前图片空间已逐张核对，缺失的素材已补齐')
            return prepared
        return _import_fresh(client, manifest, account_profile, listing=listing,
                             authorization=authorization, progress=progress,
                             should_cancel=should_cancel, timeout=timeout)
    finally:
        if listing is not None:
            listing.close()


def _attach_listing(port):
    """连上素材中心页收平台自己的响应；连不上就返回 ``None``（调用方退回 DOM 判据）。"""

    if not port:
        return None
    try:
        from .cloud_listing import CloudListing
        return CloudListing.attach(int(port))
    except Exception:  # noqa: BLE001 - 收不到响应是能力缺失，不该让整条流程起不来
        return None


def _import_fresh(client, manifest, account_profile, *, listing, authorization, progress=None,
                  should_cancel=None, timeout=300.0):
    from . import media_library
    from .upload_panel import ensure_all_images
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
        signature = None
        stable_since = None
        while True:
            _cancelled(should_cancel)
            queue=page.read_media_queue_state(client,context_id=None)
            if queue_complete(queue,names,directory_names):break
            # ⚠️ **横幅会一直挂着**（真机 2026-10-10）：行全绿了 `uploading` 仍是 True，
            # 只等严格判据会一直空转到 300 秒超时（用户看到「已完成 33 / 33」之后卡住）。
            # 所以再叠一条按证据的出口：每张图都成功 + 行集合与状态连续稳定若干秒。
            current = _queue_signature(queue)
            if queue_evidence_complete(queue,names,directory_names) and current == signature:
                if stable_since is None:
                    stable_since = time.monotonic()
                elif time.monotonic() - stable_since >= _QUEUE_SETTLE_SECONDS:
                    break
            else:
                stable_since = None
            signature = current
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
        if not queue_evidence_complete(page.read_media_queue_state(client,context_id=None),
                                       names,directory_names):
            raise TaobaoPublishError('IMAGE_UPLOAD_FAILED','完成前上传队列发生变化，未确认成功')
        page.click_media_finish(client,context_id=None,wait=0.3)
        deadline=time.monotonic()+15
        root=None
        read_ok=False
        while root is None:
            _cancelled(should_cancel)
            # 目录清单仍然以平台自己的 `dir.query` 为准（DOM 树读不到就当成没建好，
            # 会把已经建好的目录误判成失败）。
            if listing is not None:
                listing.observe(1.5)
            if listing is None or listing.dir_responses:
                read_ok = True
                matches = (listing.find_directories(manifest.folder_name)
                           if listing is not None else
                           (media_library.product_root_path(
                               client, manifest.folder_name, context_id=None,
                               page=media_library.PAGE_MATERIAL_CENTER) or []))
                if len(matches) > 1:
                    raise page.PageError('图片空间出现多个同名商品目录：' + manifest.folder_name)
                if matches:
                    root = [manifest.folder_name]
            if root is not None:break
            if time.monotonic()>=deadline:
                raise page.PageError(
                    '上传队列已完成，但图片空间里没有出现原商品文件夹'
                    if read_ok else
                    '上传队列已完成，但没有读到图片空间的目录清单响应（dir_query），'
                    '无法确认目录是否已建好')
            time.sleep(0.2)
        receipts = _read_receipts(client, manifest, root, should_cancel=should_cancel,
                                  listing=listing)
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
                    progress=progress,should_cancel=should_cancel,port=endpoint.port)
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

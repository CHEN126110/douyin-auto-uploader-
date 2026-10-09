"""已有商品目录优先使用；平铺图片空间不能按每种用途重复扫描。"""
import json

import pytest

from test_candidate_form_adapters import browser, item
from test_media_directory_flow import install_tree
from taobao_publish import page, form_adapters
from taobao_publish.contracts import load_contracts


@pytest.mark.parametrize('tree', ['flat', 'other_product'])
def test_one_root_scan_for_all_roles_and_no_reupload_when_cached(browser,item,monkeypatch,tree):
    if tree == 'other_product':
        install_tree(browser, product='另外一件商品')
    browser.evaluate('openGallery(null,null)')
    queries, batches = [], []
    find = page.find_media_images
    def lookup(client, names, **kwargs):
        queries.append(list(names))
        return find(client, names, **kwargs)
    def upload(client, files, *, context_id, rename_to, expected_sha256):
        batches.append(list(rename_to))
        for name in rename_to:
            client.evaluate('addCard('+json.dumps(name)+','+json.dumps('https://img.example.invalid/'+name)+')')
        return {'ok': True}
    monkeypatch.setattr(page, 'find_media_images', lookup)
    monkeypatch.setattr(page, 'upload_files_to_media', upload)
    messages = []
    first = form_adapters.prepare_media(browser, item, load_contracts(), context_id=None,
                                         progress=messages.append)
    assert len(batches) == 1 and len(batches[0]) == 4
    assert [len(query) for query in queries] == [4, 4]
    assert all(row['uploaded_now'] for rows in first.values() for row in rows)
    assert not any(message.startswith('进入') for message in messages)
    queries.clear()
    # 第二次准备要能认出「这批图已在图库」：上传名=源文件名后，同名命中必须过
    # 账本验证（同名+同 sha256+同图）——这里登记第一批上传的假账本回执。
    import fake_ledger
    fake_ledger.install(monkeypatch, {name: {'url': 'https://img.example.invalid/' + name,
                                             'picture_id': 'p-' + str(index)}
                                      for index, name in enumerate(batches[0])})
    second = form_adapters.prepare_media(browser, item, load_contracts(), context_id=None)
    assert len(batches) == 1
    assert [len(query) for query in queries] == [4]
    assert all(not row['uploaded_now'] for rows in second.values() for row in rows)


def test_verified_role_cache_is_read_before_unrelated_root_gallery(browser,item,monkeypatch):
    install_tree(browser, product=item.record_name)
    browser.evaluate('''openGallery(null,null);window.cardsByFolder={};const add=window.addCard;
      window.renderFolder=()=>{const gallery=document.getElementById('gallery');gallery.replaceChildren();
        const rows=(window.cardsByFolder[window.currentFolder]||[]);
        if(!rows.length){const e=document.createElement('div');e.className='next-empty';e.textContent='暂无图片';gallery.append(e);return;}
        for(const row of rows)add(row.name,row.url)};''')
    groups = {}
    ledger_records = {}
    for role,paths in form_adapters.media_plan(item).items():
        label = {'sku':'SKU','detail':'详情页'}[role]
        rows = [{'name':form_adapters.media_file_identity(path,item.record_id,role)['name'],
                 'url':'https://img.example.invalid/'+str(index)+'-'+role+'.jpg'}
                for index,path in enumerate(paths)]
        groups[label] = rows
        # 「已有明确回执不重复上传」在新命名政策下 = 账本验证通过（同名+同 sha+同图）。
        for row in rows:
            ledger_records[row['name']] = {'url': row['url'], 'picture_id': 'p-' + row['name']}
    import fake_ledger
    fake_ledger.install(monkeypatch, ledger_records)
    browser.evaluate('window.cardsByFolder='+json.dumps(groups)+';renderFolder()')
    queries = []
    inventory = page.list_media_images
    def lookup(client,**kwargs):
        directory = client.evaluate('window.currentFolder')
        assert directory != '全部图片', '用途目录已能确认全部缓存，不应再扫描无关的根图库'
        result = inventory(client,**kwargs)
        queries.append((directory,len(result['files'])))
        return result
    monkeypatch.setattr(page,'list_media_images',lookup)
    def unexpected_root_lookup(*args, **kwargs):
        raise AssertionError('商品子树已有完整缓存，不应再查询根图库')
    monkeypatch.setattr(page,'find_media_images',unexpected_root_lookup)
    def unexpected_upload(*args,**kwargs):
        raise AssertionError('已有明确回执的素材不应重复上传')
    monkeypatch.setattr(page,'upload_files_to_media',unexpected_upload)
    receipts = form_adapters.prepare_media(browser,item,load_contracts(),context_id=None)
    assert queries == [(item.record_name,0),('主图',0),('SKU',2),('详情页',2)]
    assert all(not row['uploaded_now'] for rows in receipts.values() for row in rows)

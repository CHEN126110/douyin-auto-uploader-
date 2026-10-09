"""云端树/目录内容的本地浏览器模型。测试无需本地商品文件或真实店铺。"""
import json
from dataclasses import replace

import pytest
from test_candidate_form_adapters import browser, item
from test_uploaded_media_subdirectories import grouped_gallery, group_upload
from taobao_publish import media_library, page, form_adapters
from taobao_publish.contracts import load_contracts


def nested_tree(browser):
    grouped_gallery(browser, '远端商品', caption='sibling')
    browser.evaluate('''(() => {
      const root = window.productTreeNode;
      const parent = root.querySelector('[aria-label="主图"]');
      const child = parent.cloneNode(true);
      child.setAttribute('aria-label','800');child.querySelector('span').textContent='800';
      child.querySelector('span').onclick=e=>{e.stopPropagation();document.querySelectorAll('[aria-selected]').forEach(n=>n.removeAttribute('aria-selected'));
        child.setAttribute('aria-selected','true');window.currentFolder='800';window.directoryClicks.push('800');
        document.getElementById('gallery').replaceChildren();setTimeout(()=>renderFolder(),120)};
      parent.append(child);
      window.cardsByFolder={'800':[{name:'主图_01.jpg',url:'https://img.example.invalid/main.jpg'}],
        'SKU':[{name:'规格_白色.jpg',url:'https://img.example.invalid/sku.jpg'}],
        '详情页':[{name:'详情_01.jpg',url:'https://img.example.invalid/detail.jpg'}]};renderFolder();
    })()''')


def test_remote_tree_and_inventory_do_not_require_local_files(browser):
    nested_tree(browser)
    tree = media_library.product_directory_tree(browser, '远端商品', context_id=None)
    assert tree['complete'] is True
    assert ['全部图片', '远端商品', '主图', '800'] in tree['directories']
    contents = media_library.read_directory_files(browser, ['全部图片', '远端商品', '主图', '800'], context_id=None)
    assert [f['name'] for f in contents['files']] == ['主图_01.jpg']
    receipts = media_library.locate_uploaded_images(browser, ['主图_01.jpg', '规格_白色.jpg', '详情_01.jpg'],
        ['全部图片'], context_id=None, product_name='远端商品')
    assert receipts['主图_01.jpg']['folder_path'][-2:] == ['主图', '800']
    assert receipts['规格_白色.jpg']['folder_path'][-1] == 'SKU'
    assert receipts['详情_01.jpg']['folder_path'][-1] == '详情页'
    assert browser.evaluate('window.submitCalls + window.draftCalls') == 0


def test_lazy_child_tree_waits_until_children_arrive(browser):
    nested_tree(browser)
    browser.evaluate('''(() => {const node=window.productTreeNode;
      const children=Array.from(node.children).filter(n=>n.getAttribute('role')==='treeitem');children.forEach(n=>n.remove());
      node.setAttribute('aria-expanded','false');const toggle=document.createElement('button');toggle.type='button';toggle.className='next-tree-switcher';toggle.textContent='展开';
      toggle.onclick=()=>{node.setAttribute('aria-expanded','true');setTimeout(()=>children.forEach(n=>node.append(n)),250)};
      node.prepend(toggle);})()''')
    tree = media_library.product_directory_tree(browser, '远端商品', context_id=None)
    assert len(tree['directories']) == 5
    assert ['全部图片', '远端商品', '主图', '800'] in tree['directories']


def test_unrelated_product_is_not_expanded_or_selected(browser):
    nested_tree(browser)
    browser.evaluate('''const unrelated=window.productTreeNode.cloneNode(true);unrelated.setAttribute('aria-label','别的商品');
      unrelated.querySelector('span').textContent='别的商品';unrelated.setAttribute('aria-expanded','false');
      document.querySelector('[role=tree]').append(unrelated);''')
    tree = media_library.product_directory_tree(browser, '远端商品', context_id=None)
    assert all(path[1] == '远端商品' for path in tree['directories'])
    assert '别的商品' not in browser.evaluate('window.directoryClicks')


def test_directory_name_ambiguity_and_duplicate_images_are_errors(browser):
    nested_tree(browser)
    browser.evaluate('''window.cardsByFolder.SKU.push({name:'规格_白色.jpg',url:'https://img.example.invalid/other.jpg'})''')
    with pytest.raises(page.PageError, match='ambiguous'):
        media_library.read_directory_files(browser, ['全部图片', '远端商品', 'SKU'], context_id=None)


def test_failed_lookup_retains_upload_completed_fact_without_claiming_location(browser, item, monkeypatch):
    grouped_gallery(browser, item.record_name)
    # 「上传完成但页面上定位不到」：mock 一个**不往图库列表里放卡片**的上传——
    # 平台侧算成功（ok=True），但页面清单里看不到，定位必然失败。
    # （不能用 group_upload：它会把卡片登记进 cardsByFolder，定位会成功。）
    def silent_upload(client, files, *, context_id, rename_to, expected_sha256):
        return {'ok': True}
    monkeypatch.setattr(page, 'upload_files_to_media', silent_upload)
    observations = []
    with pytest.raises(page.PageError):
        form_adapters.prepare_media(browser, item, load_contracts(), context_id=None, observations=observations)
    assert len(observations) == 4
    assert all(row['status'] == 'uploaded_unlocated' and row['folder_path'] == [] for row in observations)
    assert all('url' not in row for row in observations)


def test_incomplete_pagination_is_not_misreported_as_complete_folder(browser):
    nested_tree(browser)
    browser.evaluate('''const pager=document.createElement('div');pager.className='next-pagination';
      pager.innerHTML='<button type="button">下一页</button>';document.body.append(pager);''')
    with pytest.raises(page.PageError, match='分页'):
        media_library.read_directory_files(browser, ['全部图片', '远端商品', 'SKU'], context_id=None)


def test_inventory_reads_all_pages_and_selection_returns_to_recorded_page(browser):
    grouped_gallery(browser, '远端商品', caption='sibling')
    browser.evaluate('''(() => {
      const pager=document.createElement('div');pager.className='next-pagination';
      pager.innerHTML='<button type="button">1</button><button type="button">2</button><button type="button" class="next-next">下一页</button>';
      document.body.append(pager);window.mediaPage=2;
      function render(){
        const buttons=Array.from(pager.children);buttons.forEach((b,i)=>b.classList.toggle('next-current',i===window.mediaPage-1));
        buttons.forEach(b=>b.classList.add('next-pagination-item'));buttons[2].disabled=window.mediaPage===2;
        document.getElementById('gallery').replaceChildren();addCard('第'+window.mediaPage+'页.jpg','https://img.example.invalid/page'+window.mediaPage+'.jpg');
      }
      Array.from(pager.children).forEach((button,i)=>button.onclick=()=>{window.mediaPage=i===2?2:i+1;render()});render();
      window.imageTargetSlot=document.querySelector('.sell-component-material-item-view');
    })()''')
    inventory = page.list_media_images(browser, context_id=None)
    assert inventory['complete'] is True and inventory['pages'] == 2
    assert [(entry['name'], entry['page_number']) for entry in inventory['files']] == [('第1页.jpg', 1), ('第2页.jpg', 2)]
    receipt = page.select_media_image(browser, '第1页.jpg', context_id=None,
        expected_url='https://img.example.invalid/page1.jpg', page_number=1, wait=0)
    assert receipt['url'] == 'https://img.example.invalid/page1.jpg'
    assert page.read_main_image_slots(browser)['images'] == ['https://img.example.invalid/page1.jpg']


def test_existing_files_in_nested_cloud_folder_are_reused_without_upload(browser, item, monkeypatch):
    nested_tree(browser)
    item = replace(item, record_name='远端商品')
    identities = [form_adapters.media_file_identity(path, item.record_id, role)
        for role, paths in form_adapters.media_plan(item).items() for path in paths]
    rows = [{'name': value['name'], 'url': 'https://img.example.invalid/' + value['name']} for value in identities]
    browser.evaluate('window.cardsByFolder=' + json.dumps({'800': rows}) + ';renderFolder()')
    # 新命名政策下「已存在就复用」= 同名命中过账本验证（同名+同 sha256+同图）。
    import fake_ledger
    fake_ledger.install(monkeypatch, {row['name']: {'url': row['url'], 'picture_id': 'p-' + str(index)}
                                      for index, row in enumerate(rows)})
    def unexpected_upload(*args, **kwargs):
        raise AssertionError('已经存在于实际子目录的图片不应再次上传')
    monkeypatch.setattr(page, 'upload_files_to_media', unexpected_upload)
    result = form_adapters.prepare_media(browser, item, load_contracts(), context_id=None)
    assert all(not entry['uploaded_now'] and entry['folder_path'][-2:] == ['主图', '800']
               for rows in result.values() for entry in rows)

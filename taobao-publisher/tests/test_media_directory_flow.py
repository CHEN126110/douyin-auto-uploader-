# -*- coding: utf-8 -*-
"""当前目录无图、必须进入子目录的本地模型；不使用真实店铺或浏览器。"""
from dataclasses import replace
import json
from unittest.mock import Mock

import pytest

from test_candidate_form_adapters import browser, item, fixture_contracts, prepare_in_fixture
from test_offline_pipeline_handoff import handoff, save_case, save_and_start
from test_category_first_pipeline import install_model
from test_runtime_native_controls import use_native_detail
from taobao_publish import page, media_library, form_adapters, stages
from taobao_publish.contracts import load_contracts


def install_tree(browser, product='123'):
    browser.evaluate('''window.directoryClicks=[];
      const tree=document.createElement('div');tree.setAttribute('role','tree');
      tree.style.cssText='display:block;width:250px';document.body.prepend(tree);
      function node(label,parent){const li=document.createElement('div');li.setAttribute('role','treeitem');
        li.setAttribute('aria-label',label);li.style.cssText='min-height:28px;width:200px';
        const text=document.createElement('span');text.className='next-tree-node-label';text.textContent=label;li.append(text);
        text.onclick=e=>{e.stopPropagation();tree.querySelectorAll('[aria-selected]').forEach(n=>n.removeAttribute('aria-selected'));
          li.setAttribute('aria-selected','true');window.directoryClicks.push(label);window.currentFolder=label;
          if(window.renderFolder){document.getElementById('gallery').replaceChildren();setTimeout(()=>window.renderFolder(),120);}};parent.append(li);return li;}
      const root=node('全部图片',tree), product=node(PRODUCT,root);window.productTreeNode=product;
      node('主图',product);node('SKU',product);node('详情页',product);
      root.setAttribute('aria-selected','true');window.currentFolder='全部图片';
      // 真机上选图器只能由主图空位按钮打开（openGallery 需要落点槽位），
      // 目录操作期间弹层一直保持打开——夹具对齐：带第一个主图槽位打开。
      openGallery(null,document.querySelector('#mainImages .sell-component-material-item-view'));
      if(window.renderFolder)window.renderFolder();
    '''.replace('PRODUCT',json.dumps(product)))


def test_parent_is_not_treated_as_an_empty_gallery(browser):
    install_tree(browser)
    assert media_library.enter_product_group(browser,'123','主图',context_id=None)==['全部图片','123','主图']
    assert browser.evaluate('window.directoryClicks') == ['123','主图']
    media_library.open_directory(browser,['全部图片','123','主图'],context_id=None)
    assert browser.evaluate('window.directoryClicks') == ['123','主图']
    media_library.enter_product_group(browser,'123','SKU',context_id=None)
    assert browser.evaluate('window.currentFolder') == 'SKU'


def test_duplicate_product_folder_does_not_pick_the_first(browser):
    install_tree(browser)
    browser.evaluate("document.querySelector('[role=tree]').append(window.productTreeNode.cloneNode(true))")
    with pytest.raises(page.PageError, match='多个同名商品目录'):
        media_library.enter_product_group(browser,'123','SKU',context_id=None)
    assert browser.evaluate('window.directoryClicks') == []


def test_already_selected_collapsed_parent_is_expanded(browser):
    install_tree(browser)
    browser.evaluate('''document.querySelectorAll('[aria-selected]').forEach(n=>n.removeAttribute('aria-selected'));
      const parent=window.productTreeNode;parent.setAttribute('aria-selected','true');parent.setAttribute('aria-expanded','false');
      const children=Array.from(parent.children).filter(n=>n.getAttribute('role')==='treeitem');children.forEach(n=>n.hidden=true);
      const button=document.createElement('button');button.type='button';button.className='next-tree-switcher';button.textContent='展开';
      button.onclick=()=>{parent.setAttribute('aria-expanded','true');children.forEach(n=>n.hidden=false)};parent.prepend(button);''')
    assert media_library.enter_product_group(browser,'123','主图',context_id=None)==['全部图片','123','主图']
    assert browser.evaluate("window.productTreeNode.getAttribute('aria-expanded')")=='true'


def test_other_products_same_role_folder_is_never_selected(browser):
    install_tree(browser)
    browser.evaluate("const copy=window.productTreeNode.cloneNode(true);copy.setAttribute('aria-label','other');copy.querySelector('span').textContent='other';document.querySelector('[role=tree]').append(copy)")
    media_library.enter_product_group(browser,'123','详情页',context_id=None)
    assert media_library.read_directory(browser,context_id=None)['path'] == ['全部图片','123','详情页']


def test_directory_and_upload_batch_run_through_the_real_pipeline(handoff, monkeypatch):
    # 本用例的上传器是 DOM 文件输入框模型；明确选 DOM，避免继承桌面默认协议路线。
    monkeypatch.setenv('TAOBAO_MEDIA_ROUTE', 'dom')
    install_model(handoff, load_contracts(), monkeypatch)
    use_native_detail(handoff.browser)
    # 使用当前测试商品名称，目录层级与用户说明一致。
    install_tree(handoff.browser, handoff.case.db['name'])
    handoff.browser.evaluate('''window.cardsByFolder={};const add=window.addCard;
      window.addCard=(name,url)=>{(window.cardsByFolder[window.currentFolder]||=[]).push({name,url});add(name,url)};
      window.renderFolder=()=>{const gallery=document.getElementById('gallery');gallery.replaceChildren();
        const rows=(window.cardsByFolder[window.currentFolder]||[]);
        if(!rows.length){const e=document.createElement('div');e.className='next-empty';e.textContent='暂无图片';gallery.append(e);return;}
        for(const entry of rows)add(entry.name,entry.url)};''')
    original_upload=page.upload_files_to_media
    batches=[]
    def upload(client,files,**kwargs):
        batches.append((client.evaluate('window.currentFolder'),len(files)))
        result=original_upload(client,files,**kwargs)
        client.evaluate("document.querySelector('[role=tree] > [role=treeitem] > span').click()")
        return result
    monkeypatch.setattr(page,'upload_files_to_media',upload)
    messages=[]
    original_progress=stages.emit_progress
    def progress(*args,**kwargs):
        if args[4]=='upload_images' and args[6]:
            messages.append(args[6])
        return original_progress(*args,**kwargs)
    monkeypatch.setattr(stages,'emit_progress',progress)
    _, task = save_and_start(handoff)
    assert task['status'] == 'succeeded', task['error']
    assert task['result']['stopped_before_submit'] is True
    assert batches==[('全部图片',5)]
    assert len(handoff.uploads)==5
    assert task['result']['data']['form_verification']['status']=='partial'
    assert handoff.browser.evaluate('window.submitCalls + window.draftCalls') == 0
    assert any('进入SKU目录' in message for message in messages)
    assert any('一次上传本商品全部缺图：5张' in message for message in messages)
    assert any('选择主图：1/1' in message for message in messages)
    from pathlib import Path
    import hashlib
    from taobao_publish.sanitize import assert_clean
    artifact={'scope':'isolated_file_browser_with_product_subfolders_and_real_http_worker',
        'live_platform_tested':False,'upload_server_simulated':True,'batches':batches,
        'model_files':len(handoff.uploads),'model_submit_calls':0,'model_draft_calls':0,
        'progress_messages':messages,'result':task['result'],
        'test_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    assert_clean(artifact)
    (Path(__file__).resolve().parents[1]/'outputs/media_single_upload_directory_handoff.json').write_text(
        json.dumps(artifact,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def test_upload_destination_can_differ_from_selected_product_folder(browser):
    install_tree(browser)
    browser.evaluate('openGallery(null,null);addCard("exact.jpg","https://img.example.invalid/exact.jpg")')
    receipt=media_library.locate_uploaded_image(browser,'exact.jpg',['全部图片','123','SKU'],context_id=None)
    assert receipt['folder_path']==['全部图片']
    assert browser.evaluate('window.directoryClicks')==[]


def test_sku_and_detail_are_uploaded_in_one_batch_to_all_images(browser,item,monkeypatch):
    install_tree(browser,item.record_name)
    browser.evaluate('''openGallery(null,null);window.cardsByFolder={};
      const add=window.addCard;window.renderFolder=()=>{
        const gallery=document.getElementById('gallery');gallery.replaceChildren();
        const rows=(window.cardsByFolder[window.currentFolder]||[]);
        if(!rows.length){const e=document.createElement('div');e.className='next-empty';e.textContent='暂无图片';gallery.append(e);return;}
        for(const entry of rows)add(entry.name,entry.url);
      };''')
    batches=[]
    def upload(client,files,*,context_id,rename_to,expected_sha256):
        batches.append((client.evaluate('window.currentFolder'),len(files)))
        rows=[{'name':name,'url':'https://img.example.invalid/'+name} for name in rename_to]
        client.evaluate('window.cardsByFolder[window.currentFolder]='+json.dumps(rows)+';renderFolder()')
        return {'ok':True}
    monkeypatch.setattr(page,'upload_files_to_media',upload)
    receipts=form_adapters.prepare_media(browser,item,load_contracts(),context_id=None)
    assert batches==[('全部图片',4)]
    assert all(row['folder_path']==['全部图片'] for rows in receipts.values() for row in rows)
    browser.evaluate("window.currentFolder='全部图片';renderFolder();closeGallery()")
    table,bindings=form_adapters.create_custom_skus(browser,item,load_contracts(),receipts)
    assert len(table['rows'])==2 and len(bindings)==2
    assert len(batches)==1

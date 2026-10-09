# -*- coding: utf-8 -*-
"""只连接本次创建的本地模型浏览器；截图布局的候选适配，不代表淘宝实测。"""
from dataclasses import replace
from pathlib import Path
from PIL import Image
import pytest

from test_candidate_form_adapters import browser, item, fixture_contracts, prepare_in_fixture
from taobao_publish import form_adapters as adapters, page
from taobao_publish.sku_batch import BatchSkuPicker


SETUP_BATCH = r'''(() => {
  const original = window.openGallery;
  window.batchOpens = 0; window.batchConfirms = 0; window.batchSwitches = 0;
  window.batchOpenSources=[];
  window.openGallery = (row, slot) => {
    window.batchOpenSources.push(new Error().stack);
    original(row, slot);
    window.batchOpens++;
    const modal = document.createElement('section'); modal.setAttribute('role','dialog');
    const title = document.createElement('h2'); title.textContent='批量填充规格主图'; modal.append(title);
    const panel = document.createElement('aside');
    const heading = document.createElement('h3'); heading.textContent='选择图片填充'; panel.append(heading);
    const originals = Array.from(document.querySelectorAll('#names > li'));
    for (const originalRow of originals) {
      const target = document.createElement('div'); target.className='batch-row';
      target.style.cssText='display:flex;gap:20px;height:45px';
      target.dataset.name=originalRow.querySelector('input').value;
      const label=document.createElement('span'); label.textContent=target.dataset.name;
      const preview=document.createElement('div'); preview.className='image-slot';
      preview.style.cssText='width:40px;height:40px';
      target.append(label,preview); panel.append(target);
      target.onclick=()=>{
        window.batchSwitches++;
        for(const other of panel.querySelectorAll('.batch-row')) other.setAttribute('aria-selected','false');
        target.setAttribute('aria-selected','true');
        for(const box of document.querySelectorAll('#gallery input')) box.checked=false;
        window.imageTarget=target; window.imageTargetSlot=preview;
      };
    }
    const confirm=document.createElement('button'); confirm.type='button'; confirm.textContent='确定';
    confirm.onclick=()=>{
      window.batchConfirms++;
      for(const target of panel.querySelectorAll('.batch-row')){
        const image=target.querySelector('img'); if(!image) continue;
        const destination=originals.find(el=>el.querySelector('input').value===target.dataset.name);
        destination.querySelector('.sell-color-option-image-upload').replaceChildren(image.cloneNode());
        destination.dataset.image=image.src;
      }
      modal.hidden=true; closeGallery();
    };
    modal.append(panel,confirm); document.body.append(modal);
    if(window.duplicateBatchName) panel.querySelector('.batch-row').append(panel.querySelector('span').cloneNode(true));
  };
})()'''


@pytest.mark.parametrize('reuse_image', [False, True])
def test_five_skus_use_one_window_and_one_confirmation(browser, item, fixture_contracts, monkeypatch, reuse_image):
    colors = ['奶白 / 均码', '棕咖 / 均码', '藏青 / 均码', '黑色 / 均码', '深灰 / 均码']
    if not reuse_image:
        for index in range(3):
            # 基础夹具使用 0..3；模型 pictureId 来源于文件名数字，也须保持唯一。
            path=Path(item.images.sku[0]).parent / ('不同规格图_%s.jpg' % (index+4))
            Image.new('RGB', (800,800), (30,index*80,130)).save(path)
            item.images.sku.append(str(path))
    item.skus = [replace(item.skus[0], spec_values={'颜色分类': color},
        image_path=item.images.sku[0 if reuse_image else index]) for index, color in enumerate(colors)]
    if reuse_image:
        item.images.sku = item.images.sku[:1]
    receipts = prepare_in_fixture(browser, item, fixture_contracts, monkeypatch)
    uploaded = browser.evaluate('window.uploadCalls')
    browser.evaluate(SETUP_BATCH)
    try:
        table, bindings = adapters.create_custom_skus(browser, item, fixture_contracts, receipts)
    except page.PageError as exc:
        pytest.fail(str(exc) + '\n' + str(browser.evaluate('window.batchOpenSources')))
    assert len(bindings) == len(table['rows']) == 5
    assert browser.evaluate('window.batchOpens') == 1
    assert browser.evaluate('window.batchConfirms') == 1
    assert browser.evaluate('window.batchSwitches') == 5
    assert browser.evaluate('window.selectCalls') == 5
    assert browser.evaluate('window.uploadCalls') == uploaded, 'SKU 绑定只复用回执，不再次上传'
    assert browser.evaluate('window.submitCalls + window.draftCalls') == 0
    adapters.verify_sku_images(browser, adapters.config_for(item, fixture_contracts, purpose='sku'), bindings)


def test_ambiguous_batch_rows_do_not_fall_back_or_confirm(browser, item, fixture_contracts, monkeypatch):
    receipts = prepare_in_fixture(browser, item, fixture_contracts, monkeypatch)
    browser.evaluate(SETUP_BATCH + ';window.duplicateBatchName=true')
    with pytest.raises(page.PageError, match='batch_row_not_unique'):
        adapters.create_custom_skus(browser, item, fixture_contracts, receipts)
    assert browser.evaluate('window.batchOpens') == 1
    assert browser.evaluate('window.selectCalls + window.batchConfirms') == 0


def test_confirmation_rejects_image_bound_to_wrong_sku(browser):
    browser.evaluate(r'''document.body.innerHTML = `<section role="dialog"><h2>批量填充规格主图</h2>
        <aside><h3>选择图片填充</h3><div><span>黑色</span><img src="https://img.example.invalid/white.jpg"></div>
        <div><span>白色</span><img src="https://img.example.invalid/black.jpg"></div></aside>
        <button onclick="window.confirmed=true">确定</button></section>`''')
    picker = BatchSkuPicker.discover(browser, ['黑色', '白色'], [None])
    with pytest.raises(page.FieldMismatchError, match='确认前规格图片发生变化'):
        picker.confirm({'黑色':'https://img.example.invalid/black.jpg', '白色':'https://img.example.invalid/white.jpg'},
                       lambda actual, expected: actual == expected)
    assert browser.evaluate('window.confirmed === true') is False

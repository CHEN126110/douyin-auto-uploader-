"""目录选中与图片异步换页分离时，不得把上一目录的图片归到新目录。"""
import json

import pytest
from test_candidate_form_adapters import browser
from test_cloud_media_tree import nested_tree
from taobao_publish import media_library, page


def delayed_directory(browser, *, same_images=False, target_empty=False):
    nested_tree(browser)
    media_library.open_directory(browser, ['全部图片', '远端商品', '主图', '800'], context_id=None)
    browser.evaluate('''(() => {
      const gallery=document.getElementById('gallery');
      const target=window.productTreeNode.querySelector('[aria-label="SKU"]');
      if(SAME)window.cardsByFolder.SKU=window.cardsByFolder['800'].map(value=>({...value}));
      if(EMPTY)window.cardsByFolder.SKU=[];
      target.querySelector('span').onclick=event=>{
        event.stopPropagation();document.querySelectorAll('[aria-selected]').forEach(n=>n.removeAttribute('aria-selected'));
        target.setAttribute('aria-selected','true');window.currentFolder='SKU';gallery.setAttribute('aria-busy','true');
        gallery.replaceChildren();
        setTimeout(()=>{renderFolder();gallery.setAttribute('aria-busy','false');},250);
      };
    })()'''.replace('SAME', json.dumps(same_images)).replace('EMPTY', json.dumps(target_empty)))


def test_new_directory_waits_for_its_images_instead_of_recording_previous_folder(browser):
    delayed_directory(browser)
    contents = media_library.read_directory_files(browser, ['全部图片', '远端商品', 'SKU'], context_id=None)
    assert [row['name'] for row in contents['files']] == ['规格_白色.jpg']
    assert contents['files'][0]['url'] == 'https://img.example.invalid/sku.jpg'


def test_loading_empty_folder_does_not_inherit_previous_images(browser):
    delayed_directory(browser, target_empty=True)
    contents = media_library.read_directory_files(browser, ['全部图片', '远端商品', 'SKU'], context_id=None)
    assert contents['files'] == []


def test_already_selected_directory_still_waits_when_loading(browser):
    delayed_directory(browser)
    browser.evaluate('window.productTreeNode.querySelector("[aria-label=SKU] > span").click()')
    contents = media_library.read_directory_files(browser, ['全部图片', '远端商品', 'SKU'], context_id=None)
    assert [row['name'] for row in contents['files']] == ['规格_白色.jpg']


def test_same_image_in_two_folders_is_accepted_after_loading_completes(browser):
    delayed_directory(browser, same_images=True)
    contents = media_library.read_directory_files(browser, ['全部图片', '远端商品', 'SKU'], context_id=None)
    assert [row['name'] for row in contents['files']] == ['主图_01.jpg']
    assert browser.evaluate('document.getElementById("gallery").getAttribute("aria-busy")') == 'false'


def test_loading_timeout_preserves_old_cards_without_returning_them(browser):
    nested_tree(browser)
    media_library.open_directory(browser, ['全部图片', '远端商品', 'SKU'], context_id=None)
    browser.evaluate('document.getElementById("gallery").setAttribute("aria-busy","true")')
    with pytest.raises(page.PageError, match='仍在加载'):
        media_library.open_directory(browser, ['全部图片', '远端商品', 'SKU'], context_id=None, timeout=0.15)
    assert browser.evaluate('document.querySelector("#gallery img").src') == 'https://img.example.invalid/sku.jpg'
    assert browser.evaluate('window.submitCalls + window.draftCalls') == 0


def test_hidden_loading_indicator_does_not_block_visible_gallery(browser):
    nested_tree(browser)
    browser.evaluate('''(() => {
      const marker=document.createElement('span');marker.setAttribute('role','progressbar');
      marker.style.cssText='display:block;visibility:hidden;width:20px;height:20px';
      document.getElementById('gallery').append(marker);
    })()''')
    assert page.wait_for_media_gallery_ready(browser, context_id=None, timeout=0)['busy'] is False


def test_loading_restart_invalidates_the_completed_read(browser, monkeypatch):
    nested_tree(browser)
    real_evaluate = browser.evaluate
    def evaluate(expression, **options):
        result = real_evaluate(expression, **options)
        if 'A.inventory' in expression:
            real_evaluate('document.getElementById("gallery").setAttribute("aria-busy","true")')
        return result
    monkeypatch.setattr(browser, 'evaluate', evaluate)
    with pytest.raises(page.PageError, match='文件清单已作废'):
        media_library.read_directory_files(browser, ['全部图片', '远端商品', 'SKU'], context_id=None)


def test_batch_lookup_cannot_confirm_old_images_while_loading(browser):
    delayed_directory(browser)
    browser.evaluate('window.productTreeNode.querySelector("[aria-label=SKU] > span").click()')
    result = page.find_media_images(browser, ['主图_01.jpg', '规格_白色.jpg'], context_id=None)
    assert result['missing'] == ['主图_01.jpg']
    assert result['receipts']['规格_白色.jpg']['url'] == 'https://img.example.invalid/sku.jpg'


def test_selection_waits_before_clicking_an_image_in_the_new_directory(browser):
    delayed_directory(browser)
    browser.evaluate('''window.imageTargetSlot=document.querySelector('.sell-component-material-item-view');
        window.productTreeNode.querySelector('[aria-label=SKU] > span').click()''')
    result = page.select_media_image(browser, '规格_白色.jpg', context_id=None, wait=0,
                                     expected_url='https://img.example.invalid/sku.jpg')
    assert result['url'] == 'https://img.example.invalid/sku.jpg'
    assert page.read_main_image_slots(browser)['images'] == ['https://img.example.invalid/sku.jpg']

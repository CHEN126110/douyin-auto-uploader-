# -*- coding: utf-8 -*-
"""SKU 备注与商品级备注的前端保存边界。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sku_remark_has_its_own_input_and_save_key():
    sku_list = (ROOT / 'tauri-app/src/components/SkuList.vue').read_text(encoding='utf-8')
    save_form = (ROOT / 'tauri-app/src/composables/useProductForm.ts').read_text(encoding='utf-8')
    assert 'updateSkuRemark' in sku_list
    assert 'sku.remark' in sku_list
    assert 'SKU备注（可选）' in sku_list
    assert 'attr_remark_' in save_form
    assert 'sku.remark ?? ""' in save_form


def test_only_sku_rows_expose_a_remark_editor():
    page = (ROOT / 'tauri-app/src/views/ProductManager.vue').read_text(encoding='utf-8')
    save_form = (ROOT / 'tauri-app/src/composables/useProductForm.ts').read_text(encoding='utf-8')
    assert 'v-model="formData.remark"' not in page
    assert '商品卖点/商品备注（非 SKU 备注）' not in page
    # 隐藏重复入口不等于删除商品资料；旧记录的商品级备注仍原样保存。
    assert 'remark: form.remark' in save_form
    assert 'remark: product.remark || ""' in save_form

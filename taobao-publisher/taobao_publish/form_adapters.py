# -*- coding: utf-8 -*-
"""自定义规格与详情编辑的候选适配器。

静态 candidate 不等于控件不存在。仅对下列原生控件，在当前页面上逐步
验证范围、类型、唯一性、已有内容和回读后操作；不提升静态平台证据等级。
所有目标限定在所属区域，定位不唯一、已有未知内容或回读不符即停止。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
from . import page
from .errors import Blocker, TaobaoPublishError

CUSTOM_KEYS = ('sku.custom_mode', 'sku.custom_rows', 'sku.custom_input', 'sku.custom_add')
SKU_IMAGE_KEYS = ('sku.image_slot', 'sku.table_image', 'media.image_card')
DETAIL_KEYS = ('detail.editor', 'media.image_card')
#: 必填项阶段的两个运行期守卫键：每次动作前都校验「这一行/这个弹层」在不在、唯不唯一。
REQUIRED_KEYS = ('required.row_marker', 'required.option_item')
#: 按文本点按钮（提交 / 保存草稿）。契约里这两个按钮 `selector` 为 null、靠 `label` 文本定位，
#: 而定位动作本身每次都做**命中数=1 + 可见 + 未禁用**三项前置校验，属于运行期守卫。
BUTTON_KEYS = ('submit.save_draft_button', 'submit.submit_button')

# 这些处理器在每次动作之前检查实际 DOM；其它未取证选择器仍明确拒绝。
RUNTIME_GUARDED_KEYS = frozenset(
    CUSTOM_KEYS + ('sku.image_slot', 'sku.table_image', 'detail.editor')
    + REQUIRED_KEYS + BUTTON_KEYS)


def selector_has_execution_guard(key, spec):
    if spec is None or not spec.evidence_source.strip():
        return False
    # ⚠️ **`label` 也是定位手段。** 契约自己的规则写着「CSS 选择器无法按文本匹配，
    # 真实表单里按钮没有唯一属性；按钮填**按钮文本**」——所以按钮类条目的
    # `selector` 就是 `null`、靠 `label` 定位。原来只认 `selector`，会把
    # 「提交宝贝信息」「保存草稿」这两个已取证的按钮判成"没有定位手段"。
    has_locator = bool(spec.selector) or bool(getattr(spec, 'label', ''))
    if not has_locator:
        return False
    return spec.evidence_level == 'verified' or (
        spec.evidence_level == 'candidate' and key in RUNTIME_GUARDED_KEYS)



MediaImageMissing = page.MediaImageMissing


class AdapterEvidenceMissing(page.PageError):
    code = 'EVIDENCE_INSUFFICIENT'


# 每个阶段只核对它将使用的控件。类目选择不依赖图片/详情/SKU 编辑器。
STAGE_PURPOSES = {'upload_images': 'media', 'fill_detail': 'detail',
                  'fill_skus': 'sku', 'readback': 'readback'}


def required_keys(item, *, purpose='all'):
    if purpose not in ('all', 'media', 'sku', 'detail', 'readback'):
        raise ValueError('未知控件用途：' + str(purpose))
    keys = []
    has_sku_images = bool(item.images.sku or any(s.image_path for s in item.skus))
    if item.sku_mode == 'custom' and purpose in ('all', 'sku'):
        keys.extend(CUSTOM_KEYS)
    if has_sku_images:
        if purpose in ('all', 'sku'):
            keys.extend(SKU_IMAGE_KEYS)
        elif purpose == 'media':
            keys.append('media.image_card')
        elif purpose == 'readback':
            keys.append('sku.table_image')
    if item.images.detail:
        if purpose in ('all', 'detail'):
            keys.extend(DETAIL_KEYS)
        elif purpose == 'media':
            keys.append('media.image_card')
        elif purpose == 'readback':
            keys.append('detail.editor')
    if purpose in ('all', 'media') and item.images.main:
        keys.append('media.image_card')
    return tuple(dict.fromkeys(keys))


def adapter_blockers(item, contracts, *, purpose='all'):
    keys = required_keys(item, purpose=purpose)
    blockers = []
    if (purpose in ('all', 'sku', 'readback') and item.sku_mode != 'custom'
            and (item.images.sku or any(s.image_path for s in item.skus))):
        blockers.append(Blocker(code='EVIDENCE_INSUFFICIENT', field='skus.image_path',
                               detail='标准属性模式的图片入口尚未确认，当前候选图片处理器仅支持自定义模式',
                               source='form_adapters.adapter_blockers'))
    for key in keys:
        spec = contracts.selectors.selectors.get(key)
        if not selector_has_execution_guard(key, spec):
            blockers.append(Blocker(
                code='EVIDENCE_INSUFFICIENT', field=key,
                detail='该控件没有已确认契约或受支持的运行时验证方式，不能操作',
                source='form_adapters.adapter_blockers'))
    return blockers


def stage_adapter_blockers(item, contracts, stage):
    purpose = STAGE_PURPOSES.get(stage)
    return [] if purpose is None else adapter_blockers(item, contracts, purpose=purpose)


def config_for(item, contracts, *, purpose='all'):
    blockers = adapter_blockers(item, contracts, purpose=purpose)
    if blockers:
        raise AdapterEvidenceMissing('本阶段控件证据不足', blockers)
    result = {key: contracts.selectors.get(key).selector for key in required_keys(item, purpose=purpose)}
    if 'sku.custom_mode' in result:
        result['mode_label'] = contracts.selectors.get('sku.custom_mode').label
        if not result['mode_label']:
            raise page.PageError('自定义模式缺少精确标签')
    if 'detail.editor' in result:
        # 原生 textarea 的内容未必被平台解释为 HTML，candidate 不据此猜测。
        result['detail.require_native_html'] = contracts.selectors.get('detail.editor').evidence_level != 'verified'
    return result


def _expression(body, config, **values):
    data = json.dumps({'config': config, **values}, ensure_ascii=False)
    return '''(() => {
      const A = %s;
      const C = A.config;
      const visible = el => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      };
      const text = el => String(el.textContent || '').trim();
      const unique = (root, selector) => Array.from(root.querySelectorAll(selector)).filter(visible);
      const available = el => !el.disabled && !el.readOnly && el.getAttribute('aria-disabled') !== 'true';
      const fail = reason => ({ok: false, reason});
      const setText = (el, value) => {
        const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
        el.focus();
        setter.call(el, value);
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        el.blur();
      };
      %s
    })()''' % (data, body)


def build_custom_expression(config, action='read', value='', row_index=-1):
    """候选单层模式；不把自由文本塞进标准候选下拉。

    ⚠️ **图片落点用 ``image_slot``（自定义规格自己的选择器），不是契约里的
    ``sku.image_slot``**：后者在自定义抽屉里命中 0（E-237），
    真实落点是 ``.sell-color-option-image-upload``。
    """
    if action not in ('probe', 'read', 'mode', 'add', 'name', 'image'):
        raise ValueError('未知自定义规格动作')
    return _expression(r'''
      const drawers = unique(document, '.sku-decouple-drawer-container');
      if (drawers.length !== 1) return fail('drawer_not_unique');
      const drawer = drawers[0];
      const modes = unique(drawer, C['sku.custom_mode']).filter(el => text(el).replace(/\s/g, '') === C.mode_label.replace(/\s/g, ''));
      if (modes.length !== 1) return fail('mode_not_unique');
      const mode = modes[0];
      const radios = mode.querySelectorAll('input[type="radio"]');
      if (radios.length !== 1) return fail('mode_radio_not_unique');
      if (A.action === 'probe') {
        if (!available(radios[0])) return fail('mode_disabled');
        const existing = unique(drawer, 'input,textarea').filter(el =>
          !['radio', 'checkbox', 'button', 'submit', 'file', 'hidden'].includes(el.type) && String(el.value || '').trim());
        if (existing.length) return fail('unknown_existing_sku_draft');
        if (A.image_slot && unique(drawer, A.image_slot).some(el => el.querySelector('img[src]')))
          return fail('unknown_existing_sku_image');
        return {ok: true, modeUnique: true, nativeRadio: true, emptyDraft: true};
      }
      if (A.action === 'mode') {
        if (!available(radios[0])) return fail('mode_disabled');
        if (!radios[0].checked) mode.click();
        return {ok: true};
      }
      if (!radios[0].checked) return fail('custom_mode_not_selected');
      const rows = unique(drawer, C['sku.custom_rows']);
      const descriptors = rows.map(row => {
        const fields = unique(row, C['sku.custom_input']).filter(el => el.closest(C['sku.custom_rows']) === row);
        return {fields, value: fields.length === 1 ? fields[0].value : null};
      });
      if (descriptors.some(r => r.fields.length !== 1)) return fail('custom_input_not_unique');
      if (descriptors.some(r => r.fields[0].tagName !== 'INPUT' || r.fields[0].type !== 'text'
          || r.fields[0].getAttribute('role') === 'combobox')) return fail('native_text_input_required');
      if (A.action === 'read') {
        const images = rows.map(row => {
          if (!A.image_slot) return '';
          const slots = row.querySelectorAll(A.image_slot);
          const image = slots.length === 1 ? slots[0].querySelectorAll('img[src]') : [];
          return image.length === 1 ? image[0].src : '';
        });
        return {ok: true, values: descriptors.map(r => r.value), images};
      }
      if (A.action === 'add') {
        const buttons = unique(drawer, C['sku.custom_add']);
        if (buttons.length !== 1 || !available(buttons[0])) return fail('add_not_available');
        if (buttons[0].tagName !== 'BUTTON' || (buttons[0].form && buttons[0].type !== 'button'))
          return fail('add_button_may_submit');
        if (descriptors.some(r => !r.value.trim())) return fail('empty_row_before_add');
        buttons[0].click();
        return {ok: true};
      }
      const row = rows[A.row_index], desc = descriptors[A.row_index];
      if (!row || !desc) return fail('row_missing');
      if (A.action === 'name') {
        const field = desc.fields[0];
        if (!available(field)) return fail('custom_input_disabled');
        if (field.getAttribute('role') === 'combobox' || !['text', ''].includes(field.type)) return fail('not_plain_text');
        if (field.maxLength >= 0 && A.value.length > field.maxLength) return fail('custom_name_too_long');
        if (field.value && field.value !== A.value) return fail('unknown_existing_name');
        setText(field, A.value);
        // 只让当前输入框失焦，不点任意“空白”节点：图片空槽也可能是无子控件的 div。
        // setText 已派发 input/change 并 blur；保留幂等确认，避免误开配图窗口。
        if (document.activeElement === field) field.blur();
        return {ok: field.value === A.value, value: field.value,
                blurred: document.activeElement !== field};
      }
      if (desc.value !== A.value) return fail('image_row_identity_changed');
      // ⚠️ 图片落点用的是**自定义规格自己的**选择器，不是契约里的 `sku.image_slot`
      //   ——后者（`.sell-component-material-item-view`）在自定义抽屉里命中 0（E-237）。
      const slots = unique(row, A.image_slot);
      if (slots.length !== 1 || !available(slots[0])) return fail('image_slot_not_unique');
      if (slots[0].tagName === 'BUTTON' && slots[0].form && slots[0].type !== 'button') return fail('image_button_may_submit');
      if (slots[0].querySelector('img[src]')) return fail('unknown_existing_image');
      slots[0].click();
      return {ok: true};
    ''', config, action=action, value=value, row_index=row_index,
        image_slot=page.SKU_CUSTOM_IMAGE_UPLOAD)


def build_sku_images_expression(config):
    return _expression(r'''
      const roots = unique(document, '.sell-sku-table-wrapper-new');
      if (roots.length !== 1) return fail('sku_table_not_unique');
      const rows = unique(roots[0], 'tr.sku-table-row');
      if (!rows.length) return fail('sku_table_empty');
      const values = [];
      for (const row of rows) {
        const specs = Array.from(row.querySelectorAll('td')).slice(0, 2).map(text).filter(Boolean);
        const images = Array.from(row.querySelectorAll(C['sku.table_image']));
        if (!specs.length || images.length > 1) return fail('sku_image_not_unique');
        values.push({specs, url: images.length === 1 ? images[0].src : ''});
      }
      return {ok: true, rows: values};
    ''', config)


def build_detail_expression(config, action='read', urls=()):
    """仅支持明确定位的原生 HTML textarea / contenteditable；不猜编辑器私有 API。"""
    if action not in ('read', 'write'):
        raise ValueError('未知详情动作')
    return _expression(r'''
      const rows = unique(document, '.sell-component-info-wrapper-wrap').filter(row => {
        const labels = row.querySelectorAll('.sell-component-info-wrapper-label');
        return labels.length === 1 && text(labels[0]).replace(/\s|\*/g, '') === '宝贝详情';
      });
      if (rows.length !== 1) return fail('detail_row_not_unique');
      const editors = unique(rows[0], C['detail.editor']);
      if (editors.length !== 1) return fail('detail_editor_not_unique');
      const editor = editors[0];
      const native = editor.tagName === 'TEXTAREA';
      if (native && C['detail.require_native_html']) return fail('detail_text_mode_unconfirmed');
      if (!native && !editor.isContentEditable) return fail('detail_editor_not_supported');
      const read = () => {
        const fragment = document.createElement('div');
        fragment.innerHTML = native ? editor.value : editor.innerHTML;
        return {urls: Array.from(fragment.querySelectorAll('img')).map(img => img.getAttribute('src') || ''),
                text: (fragment.textContent || '').trim(),
                hasOtherContent: Array.from(fragment.querySelectorAll('*')).some(el => !['P', 'BR', 'DIV', 'SPAN', 'IMG'].includes(el.tagName))};
      };
      const before = read();
      if (A.action === 'read') return {ok: true, ...before};
      if (!available(editor)) return fail('detail_editor_disabled');
      const raw = native ? editor.value : editor.innerHTML;
      const emptyMarkup = raw.replace(/(?:<p>\s*(?:<br\s*\/?>)?\s*<\/p>|<br\s*\/?>|\s)/gi, '');
      if (emptyMarkup || before.urls.length || before.text || before.hasOtherContent) return fail('unknown_existing_detail');
      if (!A.urls.length) return fail('detail_images_empty');
      const fragment = document.createElement('div');
      for (const url of A.urls) {
        const parsed = new URL(url);
        if (parsed.protocol !== 'https:' || parsed.username || parsed.password) return fail('detail_url_invalid');
        const p = document.createElement('p'), image = document.createElement('img');
        image.setAttribute('src', url);
        p.appendChild(image);
        fragment.appendChild(p);
      }
      if (native) setText(editor, fragment.innerHTML);
      else {
        editor.focus();
        const event = new InputEvent('beforeinput', {bubbles: true, cancelable: true, inputType: 'insertFromPaste'});
        if (!editor.dispatchEvent(event)) return fail('detail_input_cancelled');
        editor.replaceChildren(...Array.from(fragment.childNodes));
        editor.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertFromPaste'}));
        editor.blur();
      }
      const after = read();
      return {ok: JSON.stringify(after.urls) === JSON.stringify(A.urls) && !after.text && !after.hasOtherContent, ...after};
    ''', config, action=action, urls=list(urls))


def _checked(client, expression, *, context_id=None):
    result = client.evaluate(expression, context_id=context_id)
    if not isinstance(result, dict) or result.get('ok') is not True:
        reason = result.get('reason', '回读不一致') if isinstance(result, dict) else '无有效返回'
        descriptions = {
            'unknown_existing_sku_draft': '规格抽屉已有内容，已保留，未切换模式',
            'unknown_existing_sku_image': '规格抽屉已有图片，已保留，未切换模式',
            'native_text_input_required': '规格名称控件不是可直接填写的原生文本输入框',
            'add_button_may_submit': '新增规格按钮可能提交表单，未点击',
            'image_button_may_submit': '规格图片按钮可能提交表单，未点击',
            'custom_name_too_long': '规格名称超过当前输入控件的长度限制，未截断或写入',
            'detail_text_mode_unconfirmed': '详情区是文本输入模式，尚未确认其HTML含义，未写入图片',
        }
        raise page.PageError('控件验证未通过：' + descriptions.get(reason, str(reason)))
    return result


def _wait(client, expression, predicate, *, timeout=5.0, interval=0.1):
    deadline = time.monotonic() + timeout
    last = None
    while True:
        result = client.evaluate(expression)
        last = result if isinstance(result, dict) else {'ok': None, 'raw': str(result)[:120]}
        if isinstance(result, dict) and result.get('ok') is True and predicate(result):
            return result
        if time.monotonic() >= deadline:
            # 把"最后读到了什么"带进错误里——否则只报"回读不一致"，
            # 分不清是**没写进去**、**控件定位变了**还是**读的是别的东西**。
            raise page.FieldMismatchError(
                '控件未在限定时间内回读为期望值；最后读到的：'
                + json.dumps(last, ensure_ascii=False)[:400])
        time.sleep(interval)


def media_plan(item):
    """SKU 集合不能按顺序猜绑定；每张图须有具体规格行来源。"""
    assigned = [s.image_path for s in item.skus if s.image_path]
    orphaned = set(item.images.sku) - set(assigned)
    if orphaned:
        raise page.PageError('SKU 图片未指定对应的规格行，不能按列表序号绑定')
    return {'sku': list(dict.fromkeys(assigned)), 'detail': list(item.images.detail)}


def gallery_find(client, config, name, *, context_id, select=False, expected_url='', page_number=None):
    """规格图/详情图复用主图卡片的精确文件名及完整 URL 处理器。"""
    selector = config.get('media.image_card')
    if not isinstance(selector, str) or not selector.strip():
        raise AdapterEvidenceMissing('缺少图片空间卡片契约')
    if select:
        return page.select_media_image(client, name, context_id=context_id,
            expected_url=expected_url, card_selector=selector, wait=0, page_number=page_number)
    return page.find_media_image(client, name, context_id=context_id, card_selector=selector)


def media_file_identity(path, record_id, role, *, slot=None):
    """上传身份 = **源文件名 + 内容 SHA-256**；名字与采集目录里的源文件逐字一致。

    ## 命名政策（2026-10-08 用户明确要求）

    上传到图片空间的文件名**就是源文件名**（``主图_01.jpg`` 这种），内容也
    逐字节一致——图片空间里看到的是什么，本地就是什么。早先的
    ``tb_<记录>_<角色>_<哈希>.jpg`` 生成名解决了「跨商品同名混淆」（见
    `tests/test_media_name_identity.py` 的历史背景），但现在：

    * 素材按商品/用途**分目录归档**（``全部图片/<商品>/主图`` 等），
      同名冲突被目录天然隔离；
    * 选图走 **pictureId / 回执 URL** 的确定性身份，文件名只是展示与查找提示。

    内容身份仍是 SHA-256：同名文件内容变了 → 身份变 → 重新上传（账本键是
    名字+摘要）。**同一商品内两个不同内容的同名文件**没法同名共存——
    这种冲突由 ``prepare_media`` 如实报错，不静默改名。

    :param slot: 保留给主图槽位语义（同一文件占多个槽位合法，去重后共用一张
        云端素材）；**不再参与命名**。
    """
    if type(record_id) is not int or record_id <= 0 or role not in ('main', 'sku', 'detail'):
        raise page.PageError('素材商品编号或用途无效')
    if slot is not None and (type(slot) is not int or slot <= 0):
        raise page.PageError('素材槽位无效')
    path = Path(path)
    if not path.is_file():
        raise page.PageError('本地素材文件不存在')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'path': str(path), 'name': path.name, 'sha256': digest}


def _ledger_verify(identity, card_url, *, ledger):
    """账本是否证明「同名 + 同 sha256 + 同图」：是 → 返回账本记录；否 → ``None``。

    上传名=源文件名后，「同名」不证明「同内容」——预扫命中必须过这道验证，
    过不了就当没传过（重传后用回执 URL 消歧），绝不把同名旧图当新图选进去。
    """
    if ledger is None:
        return None
    try:
        from .upload_api import same_image
        record = ledger.lookup({'name': identity.get('name'), 'sha256': identity.get('sha256')})
    except Exception:  # noqa: BLE001 - 账本读不出来不拖垮定位，按未验证处理
        return None
    if not record:
        return None
    ledger_url = str(record.get('url') or '')
    if ledger_url and card_url and not same_image(ledger_url, card_url):
        # 同名同内容但地址对不上：卡片不是账本那次上传的产物，不猜。
        return None
    return record


def _attach_ledger_picture_id(entry, *, ledger=None):
    """把账本上**同身份且同图**的 ``picture_id`` 补进回执。

    预扫/卡片定位拿到的回执只有 ``name/url/folder_path/page_number``，没有
    ``picture_id``；而按 ID 精确选图（主图 ``pick_media_by_id``、详情模块编辑器
    多选 ``fill_detail_by_picture_id``）**靠它才能走确定性那条路**。账本记了每次
    上传的 ``picture_id``——身份（文件名+sha256）命中且图片地址一致才补，
    缺一项就保持缺失，让调用方走它自己的既有兜底（不猜）。
    """
    if entry.get('picture_id'):
        return entry
    if ledger is None:
        return entry
    try:
        from .upload_api import same_image
        record = ledger.lookup({'name': entry.get('name'), 'sha256': entry.get('sha256')})
    except Exception:  # noqa: BLE001 - 账本读不出来不拖垮定位，保持原回执
        return entry
    if not record or not record.get('picture_id'):
        return entry
    ledger_url = str(record.get('url') or '')
    card_url = str(entry.get('url') or '')
    if ledger_url and card_url and not same_image(ledger_url, card_url):
        # 同名同内容但地址对不上：卡片不是账本那次上传的产物，不猜。
        return entry
    return dict(entry, picture_id=str(record.get('picture_id') or ''))


def bind_prepared_media(client, item, contracts, prepared_product, account_profile, *, context_id,
                        progress=None, observations=None):
    """先验证本地内容、账户和上传回执；在各用途真正选择时校验远端卡片。"""
    from .media_library import product_root_path
    config_for(item, contracts, purpose='media')
    plan = prepared_product.selection_plan(item, account_profile)
    root = product_root_path(client, prepared_product.manifest.folder_name, context_id=context_id)
    if root is None:
        raise page.PageError('图片空间中尚未找到本批准备好的商品目录')
    for role, entries in plan.items():
        for entry in entries:
            entry['folder_path'] = list(root) + list(entry['cloud_folder'][1:])
            if observations is not None:
                observations.append({key: entry[key] for key in ('path','name','sha256')}
                                    | {'role': role, 'status': 'uploaded_unlocated', 'folder_path': []})
    if progress:
        progress('已读取上传回执，按用途直接进入目标目录选图')
    return plan


def prepare_media(client, item, contracts, *, context_id, progress=None, main_identities=None,
                  observations=None, protocol_upload=None, folder_creator=None):
    """准备本商品的素材身份与选择回执。

    协议路线由上传钩子按摘要与目录 ID 复用/上传素材；拿到完整回执后直达
    目标用途目录，在真正选图前验证卡片身份，不预先遍历其它用途。
    DOM 路线没有完整上传回执，保留上传后从商品文件树定位的流程。
    folder_creator 只负责创建缺少的商品/用途目录，不能回退到根目录上传。
    """
    from .media_library import find_product_images, open_all_images, locate_uploaded_images
    config = config_for(item, contracts, purpose='media')
    plan = media_plan(item)
    if main_identities is not None:
        plan = {'main': list(item.images.main), **plan}
        if [entry['path'] for entry in main_identities] != [str(Path(path)) for path in item.images.main]:
            raise page.PageError('主图位置与本次素材清单不一致')
    groups = {'main': '主图', 'sku': 'SKU', 'detail': '详情页'}
    identities_by_role, unique, prepared = {}, {}, {}
    for role, paths in plan.items():
        identities = []
        for index, raw in enumerate(paths):
            path = Path(raw)
            from PIL import Image
            with Image.open(path) as image:
                image.verify()
            identity = main_identities[index] if role == 'main' else media_file_identity(path, item.record_id, role)
            # ⚠️ **把角色钉在身份上**：协议上传要按角色决定落到图片空间哪个子目录
            # （`主图`/`SKU`/`详情页`）。早先身份只有 `{path, name, sha256}`，
            # 角色只体现在**文件名**里，于是上传时目录信息整个丢失——
            # 实测症状就是"图片全是散的、没有文件夹结构"（E-279）。
            identity = {**identity, 'role': role, 'cloud_folder': groups[role]}
            identities.append(identity)
            # 上传名 = 源文件名。同一商品内**同名不同内容**没法在图片空间同名共存
            # （也没法确定选图身份）——如实报错，不静默改名；同名同内容（同一文件
            # 复用于多个角色/槽位）合法，去重后共用一张云端素材。
            existing = unique.get(identity['name'])
            if existing is None:
                unique[identity['name']] = identity
            elif existing['sha256'] != identity['sha256']:
                raise page.PageError(
                    '同名素材内容不一致，无法按源文件名上传（请改名后再试）：{} 与 {}'.format(
                        existing['path'], identity['path']))
        identities_by_role[role] = identities
    def observe(names, status):
        if observations is None:
            return
        for role, identities in identities_by_role.items():
            for identity in identities:
                if identity['name'] in names:
                    receipt = prepared.get(identity['name'], {})
                    observations.append({**identity, 'role': role, 'status': status,
                        'folder_path': list(receipt.get('folder_path') or []) if status == 'located' else []})

    if protocol_upload is not None:
        # 上传钩子已经按内容摘要和目录 ID 复用账本，无需再预扫整棵商品树。
        # 这里只接收完整回执；远端卡片核验在主图/SKU/详情实际选择之前执行。
        from .media_library import product_root_path, resolve_role_folder
        from .upload_api import validate_image_url
        folder_names = sorted({str(groups[role]) for role in plan})
        if any(not name for name in folder_names):
            raise page.PageError('素材身份缺少用途目录，拒绝按根目录上传')
        destination_folder_ids = {name:resolve_role_folder(
            client,item.record_name,name,context_id=context_id,
            creator=folder_creator,role_folders=folder_names) for name in folder_names}
        root = product_root_path(client,item.record_name,context_id=context_id)
        if not root:
            raise page.PageError('上传目标商品目录未确认，不能建立选图路径')
        destinations = {name:destination_folder_ids[identity['cloud_folder']] for name,identity in unique.items()}
        if progress:
            progress('按上传回执准备{}张素材，主图、SKU、详情在各自阶段直接选图'.format(len(unique)))
        receipts=protocol_upload(list(unique.values()),destinations)
        if not isinstance(receipts,dict) or set(receipts)!=set(unique):
            raise page.PageError('协议上传回执与本次素材清单不一致，未进入选图阶段')
        for name,identity in unique.items():
            receipt=receipts[name]
            if not isinstance(receipt,dict):
                raise page.PageError('协议上传回执格式无效：'+name)
            validate_image_url(receipt.get('url'))
            uploaded_now=receipt.get('uploaded_now',True)
            if type(uploaded_now) is not bool:
                raise page.PageError('协议上传回执状态无效：'+name)
            prepared[name]=dict(identity,url=receipt['url'],picture_id=str(receipt.get('picture_id') or ''),
                folder_path=list(root)+[identity['cloud_folder']],uploaded_now=uploaded_now)
        observe(prepared,'uploaded_unlocated')
        return {role:[dict(prepared[identity['name']],path=raw)
                      for raw,identity in zip(plan[role],identities)] for role,identities in identities_by_role.items()}

    # ⚠️ 上传名=源文件名之后，「同名」不再证明「同内容」（旧命名把内容哈希编进
    # 名字，同名即同图；现在同名可能是上一次采集留下的**另一张图**）。账本先行：
    # ① 给预扫带上期望 URL——同名多张时靠它消歧（同一商品目录里可能躺着上次的
    #    同名旧图）；② 命中是否接受由下面的「同名+同 sha256+同图」验证把关。
    pre_scan_ledger = None
    try:
        from .protocol_media import UploadLedger
        pre_scan_ledger = UploadLedger.load()
    except Exception:  # noqa: BLE001 - 账本读不出来不拖垮预扫，保持原回执
        pre_scan_ledger = None
    pre_scan_expected = {}
    if pre_scan_ledger is not None:
        for name, identity in unique.items():
            record = pre_scan_ledger.lookup(identity)
            if record and str(record.get('url') or '').startswith('https://'):
                pre_scan_expected[name] = str(record['url'])
    lookup = find_product_images(client, item.record_name, list(unique), context_id=context_id,
                                 progress=progress, allow_conflict=False,
                                 expected_urls=pre_scan_expected or None,
                                 extra_paths=())
    # 预扫命中必须由账本证明「同名 + 同 sha256 + 同图」（`_ledger_verify`）
    # 才接受；证明不了就当没传过——重传后用回执 URL 消歧。
    accepted = {}
    for name, receipt in lookup['receipts'].items():
        record = _ledger_verify(unique[name], str(receipt.get('url') or ''),
                                ledger=pre_scan_ledger)
        if record is None:
            continue
        entry = dict(unique[name], url=receipt['url'], folder_path=receipt['folder_path'],
                     page_number=receipt.get('page_number'), uploaded_now=False)
        if record.get('picture_id'):
            entry['picture_id'] = str(record['picture_id'])
        prepared[name] = entry
        accepted[name] = receipt
    observe(accepted, 'located')
    pending = {name: identity for name, identity in unique.items() if name not in prepared}
    if pending:
        # DOM 路线上兼容已经入库的旧素材；仍须由摘要和地址证明身份。
        directory = open_all_images(client, context_id=context_id)
        if progress:
            progress('查找全部图片中的{}张商品素材'.format(len(pending)))
        lookup = page.find_media_images(client, list(pending), context_id=context_id,
                                        card_selector=config['media.image_card'])
        accepted_dom = {}
        for name, receipt in lookup['receipts'].items():
            record = _ledger_verify(pending[name], str(receipt.get('url') or ''),
                                    ledger=pre_scan_ledger)
            if record is None:
                # 同名≠同图（见上方账本验证说明）：未证明的命中不接受。
                continue
            entry = dict(pending[name], url=receipt['url'], folder_path=directory,
                         uploaded_now=False)
            if record.get('picture_id'):
                entry['picture_id'] = str(record['picture_id'])
            prepared[name] = entry
            accepted_dom[name] = receipt
        observe(accepted_dom, 'located')
        pending = {name: pending[name] for name in pending if name not in prepared}
    if pending:
        if progress:
            progress('一次上传本商品全部缺图：{}张；主图、SKU、详情共用本批素材'.format(len(pending)))
        batch = list(pending.values())
        result = page.upload_files_to_media(client, [entry['path'] for entry in batch],
            context_id=context_id, rename_to=list(pending), expected_sha256=[entry['sha256'] for entry in batch])
        if result.get('rejectedByPlatform'):
            raise TaobaoPublishError('VERIFICATION_REQUIRED',
                '平台拒绝了上传：' + str(result.get('reason') or '平台未给具体原因'))
        if not result.get('ok'):
            raise page.PageError('本商品素材上传未完成：' +
                str(result.get('reason') or '、'.join(result.get('failed') or list(pending))))
        # 后面的目录查找可能失败；队列完成事实仍须留给图片管理，不冒充已定位。
        observe(pending, 'uploaded_unlocated')
        directory = open_all_images(client, context_id=context_id)
        group_names = {groups[role]: list(dict.fromkeys(identity['name'] for identity in identities
            if identity['name'] in pending)) for role, identities in identities_by_role.items()}
        def located(name, receipt):
            prepared[name] = dict(pending[name], url=receipt['url'], folder_path=receipt['folder_path'],
                                  page_number=receipt.get('page_number'), uploaded_now=True)
            observe([name], 'located')
        uploaded = locate_uploaded_images(client, list(pending), directory, context_id=context_id,
            product_name=item.record_name, group_names=group_names, progress=progress, on_located=located)
        # ⚠️ **DOM 路线也要登记账本**：新命名政策下「复用已有素材」的判据是
        # 「账本证明同名 + 同 sha256 + 同图」。协议路线在上传回执到达时就记账
        # （`stages._protocol_upload_hook` 的 `remember`），DOM 路线只有在
        # 这里定位成功、拿到卡片 URL 之后才具备记账条件。不登记的话，这批图
        # 下次发布过不了验证，只能整批重传——还会在图片空间留下同名重复素材。
        if pre_scan_ledger is not None:
            for name in pending:
                receipt = uploaded[name]
                try:
                    pre_scan_ledger.record(pending[name], {'url': receipt['url'],
                        'picture_id': str(receipt.get('picture_id') or '')})
                except Exception:  # noqa: BLE001 - 账本写不进去不拖垮已完成的定位，下次重传即可
                    pass
        for name, identity in pending.items():
            receipt = uploaded[name]
            prepared[name] = dict(identity, url=receipt['url'], folder_path=receipt['folder_path'],
                                  page_number=receipt.get('page_number'), uploaded_now=True)
    return {role: [dict(prepared[identity['name']], path=raw) for raw, identity in zip(plan[role], identities)]
            for role, identities in identities_by_role.items()}


def _trace_sku(message: str) -> None:
    """`TAOBAO_MEDIA_DEBUG=1` 时把自定义规格每一步的原始返回写到 stderr。

    为什么要它：`FIELD_MISMATCH 控件未在限定时间内回读为期望值` 这句话本身
    **分不清**是"没写进去 / 控件定位变了 / 读到了别的东西"。把每步返回打出来
    才能一次定位（本项目已多次因为"只看最后一句错误"而误判）。
    """

    if os.environ.get('TAOBAO_MEDIA_DEBUG') != '1':
        return
    import sys as _sys

    _sys.stderr.write('[sku-debug] ' + str(message) + '\n')
    _sys.stderr.flush()


def _trace_timing(message: str, started: float) -> None:
    """`TAOBAO_TIMING=1` 时把自定义规格**内部各步**的耗时写到 stderr。

    为什么要拆到这么细：阶段总耗时只说"fill_skus 慢"，
    而它内部有"开抽屉 / 建行 / 写规格名 / 逐行绑图 / 填价格库存"好几步——
    不拆开就不知道该优化哪一步（`upload_images` 那次就是靠这个发现
    时间全耗在"等一个永远不会成立的条件"上，见 E-264）。
    """

    if os.environ.get('TAOBAO_TIMING') != '1':
        return
    import sys as _sys
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    # 用 ascii() 输出，避免控制台把中文显示成乱码而误读
    _sys.stderr.write('[sku-timing] {:>7} ms  {}\n'.format(elapsed_ms, ascii(message)))
    _sys.stderr.flush()


def _pick_sku_receipt(client, config, receipt, context_id, *, open_folder=True):
    from .media_library import open_directory, pick_media_by_id_with_requery
    if open_folder and receipt.get('folder_path'):
        receipt['folder_path'] = open_directory(client, receipt['folder_path'], context_id=context_id,
                                               expected_images=[receipt])
    picture_id = str(receipt.get('picture_id') or '')
    if picture_id:
        picked = pick_media_by_id_with_requery(client, [picture_id], context_id=context_id,
                                               select=True, wait=10.0, stage='fill_skus', expected_urls={picture_id:receipt['url']})
        chosen = (picked.get('selected') or [{}])[0]
        if not _detail_url_matches(str(chosen.get('url') or ''), receipt['url']):
            raise page.FieldMismatchError('SKU 图选中的不是本次回执那张')
    else:
        gallery_find(client, config, receipt['name'], context_id=context_id, select=True,
                     expected_url=receipt['url'], page_number=receipt.get('page_number'))


def create_custom_skus(client, item, contracts, prepared_media):
    config = config_for(item, contracts, purpose='sku')
    dimensions = {tuple(sorted(s.spec_values)) for s in item.skus}
    if len(dimensions) != 1 or len(next(iter(dimensions), ())) != 1:
        raise page.PageError('候选自定义模式只支持单个规格维度，不能拆分或猜测组合')
    values = [next(iter(s.spec_values.values())).strip() for s in item.skus]
    if os.environ.get('TAOBAO_MEDIA_DEBUG') == '1':
        import sys as _sys
        _sys.stderr.write('[sku-debug] 目标规格值 {} 个: {!r}\n'.format(len(values), values))
        _sys.stderr.flush()
    if not values or any(not value for value in values) or len(set(values)) != len(values):
        raise page.PageError('自定义规格名称为空或重复')
    _t_total = time.perf_counter()
    existing = page.read_sku_table(client)
    if existing.get('rows'):
        raise page.PageError('填写页已有规格表，无法确认来源，保留原有规格')
    _t = time.perf_counter()
    page.open_sku_drawer(client)
    _trace_timing('open_sku_drawer', _t)
    _trace_sku('抽屉已打开；开始 probe')
    probe = _checked(client, build_custom_expression(config, 'probe'))
    _trace_sku('probe OK: ' + json.dumps(probe, ensure_ascii=False)[:200])
    mode_result = _checked(client, build_custom_expression(config, 'mode'))
    _trace_sku('mode OK: ' + json.dumps(mode_result, ensure_ascii=False)[:120])
    state = _wait(client, build_custom_expression(config), lambda result: True)
    _trace_sku('初始 state: ' + json.dumps(
        {'values': state.get('values'), 'images': state.get('images')}, ensure_ascii=False)[:300])
    if any(state['values']):
        raise page.PageError('自定义抽屉已有规格，无法核验来源，保留现有资料')
    if len(state['values']) > 1:
        raise page.PageError('自定义抽屉初始行数不明确')
    for index, value in enumerate(values):
        if index >= len(state['values']):
            add_result = _checked(client, build_custom_expression(config, 'add'))
            _trace_sku('add OK({}): {}'.format(index, json.dumps(add_result, ensure_ascii=False)[:120]))
            state = _wait(client, build_custom_expression(config), lambda result: len(result['values']) == index + 1)
        name_result = _checked(client, build_custom_expression(config, 'name', value, index))
        _trace_sku('name OK({}): {}'.format(index, json.dumps(name_result, ensure_ascii=False)[:160]))
        if os.environ.get('TAOBAO_MEDIA_DEBUG') == '1':
            import sys as _sys
            _sys.stderr.write('[sku-debug] 写完第{}个规格名 {!r}，等待回读 values={!r}\n'.format(
                index, value, values[:index + 1]))
            _sys.stderr.flush()
        state = _wait(client, build_custom_expression(config), lambda result: result['values'] == values[:index + 1])
        if os.environ.get('TAOBAO_MEDIA_DEBUG') == '1':
            import sys as _sys
            _sys.stderr.write('[sku-debug] 第{}个回读 OK，values={!r}\n'.format(index, state['values']))
            _sys.stderr.flush()
    sku_receipts = {r['path']: r for r in prepared_media.get('sku', [])}
    jobs, bindings = [], []
    for index, sku in enumerate(item.skus):
        if not sku.image_path:
            continue
        receipt = sku_receipts.get(sku.image_path)
        if receipt is None:
            raise page.PageError('规格图片没有本次上传身份回执')
        jobs.append((index, sku, receipt))
    if jobs:
        from .sku_batch import BatchSkuPicker
        page.open_sku_image_picker(client, values[jobs[0][0]])
        context_id = page.media_iframe_context(client)
        batch = BatchSkuPicker.discover(client, values, [None, context_id])
        if batch is not None:
            # 同一个批量窗口内逐项切换右侧规格；同一目录只进入一次。
            previous_folder = None
            for index, sku, receipt in jobs:
                batch.activate(values[index])
                folder = tuple(receipt.get('folder_path') or ())
                _pick_sku_receipt(client, config, receipt, context_id,
                                  open_folder=folder != previous_folder)
                previous_folder = folder
                batch.verify_image(values[index], receipt['url'], _detail_url_matches)
                bindings.append({'specs': list(sku.spec_values.values()), 'path': sku.image_path,
                                 'url': receipt['url'], 'picture_id': str(receipt.get('picture_id') or '')})
            batch.confirm({values[index]: receipt['url'] for index, _, receipt in jobs}, _detail_url_matches)
            _wait(client, build_custom_expression(config), lambda result: result['values'] == values
                  and all(_detail_url_matches(str(result['images'][index] or ''), receipt['url'])
                          for index, _, receipt in jobs))
        else:
            # 旧版单图选择器没有批量规格列表，仍使用它本身的逐行确认语义。
            for ordinal, (index, sku, receipt) in enumerate(jobs):
                if ordinal:
                    page.open_sku_image_picker(client, values[index])
                    context_id = page.media_iframe_context(client)
                _pick_sku_receipt(client, config, receipt, context_id)
                try:
                    page.confirm_media_selection(client, context_id=context_id)
                except page.PageError:
                    pass
                try:
                    page.close_media_popup(client, wait=1.0)
                except Exception:
                    pass
                _wait(client, build_custom_expression(config), lambda result: result['values'] == values
                      and _detail_url_matches(str(result['images'][index] or ''), receipt['url']))
                bindings.append({'specs': list(sku.spec_values.values()), 'path': sku.image_path,
                                 'url': receipt['url'], 'picture_id': str(receipt.get('picture_id') or '')})
    _t = time.perf_counter()
    final = _checked(client, build_custom_expression(config))
    if final['values'] != values:
        raise page.FieldMismatchError('选规格图后规格名称发生变化，未确认创建')
    page.confirm_sku_creation(client)
    table = page.wait_for_sku_table(client, expected_rows=len(values))
    _trace_timing('确认创建 + 等表格', _t)
    actual = [row.get('specs') for row in table.get('rows', [])]
    if sorted(actual) != sorted([[value] for value in values]):
        raise page.FieldMismatchError('自定义规格表的完整名称或行数不符')
    if bindings:
        verify_sku_images(client, config, bindings)
    table['runtime_control_checks'] = {'scope': 'current_dom_and_readback',
        'mode_unique': probe['modeUnique'], 'native_radio': probe['nativeRadio'],
        'empty_draft_before_action': probe['emptyDraft'], 'names_read_back': len(values),
        'bound_images_read_back': len(bindings)}
    return table, bindings


def verify_sku_images(client, config, bindings):
    """核对 SKU 图是否绑到对应规格行（按**资源标识**，不逐字比 URL）。

    ⚠️ 自定义规格模式下规格表是 `.sell-sku-table-wrapper-new` 里的
    `tr.sku-table-row`，每行的图是 `td` 里的 `<img>`。**不能**用契约
    `sku.table_image = img`（那是全页所有 `img`，会把图标/预览也算进来）。
    这里按行取尺寸正常的图，并用资源标识比对——与写入侧同一判据。
    """

    expression = r'''(() => {
      const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      const roots = Array.from(document.querySelectorAll('.sell-sku-table-wrapper-new'));
      if (roots.length !== 1) return { ok: false, reason: 'sku_table_not_unique', hitCount: roots.length };
      const rows = Array.from(roots[0].querySelectorAll('tr.sku-table-row'));
      if (!rows.length) return { ok: false, reason: 'sku_table_empty' };
      return { ok: true, rows: rows.map(row => {
        const cells = Array.from(row.querySelectorAll('td'));
        const images = Array.from(row.querySelectorAll('img[src]'))
          .filter(img => { const r = img.getBoundingClientRect(); return r.width > 20 || r.height > 20; })
          .map(img => String(img.src || ''));
        return { specs: cells.slice(0, 2).map(text).filter(Boolean), images: images };
      }) };
    })()'''
    actual = client.evaluate(expression, timeout=30.0)
    if not isinstance(actual, dict) or actual.get('ok') is not True:
        raise page.FieldMismatchError('SKU 表回读失败：' + str(
            (actual or {}).get('reason') if isinstance(actual, dict) else '无有效返回'))
    rows = actual.get('rows') or []
    identities = [tuple(sorted(str(v) for v in (row.get('specs') or []))) for row in rows]
    if len(set(identities)) != len(identities):
        raise page.FieldMismatchError('SKU 图片回读含重复规格身份')
    for binding in bindings:
        wanted = tuple(sorted(str(v) for v in binding['specs']))
        matches = [row for row in rows
                   if tuple(sorted(str(v) for v in (row.get('specs') or []))) == wanted]
        if len(matches) != 1:
            raise page.FieldMismatchError('SKU 图没有绑定到唯一对应规格：' + '、'.join(binding['specs']))
        images = matches[0].get('images') or []
        if len(images) != 1:
            raise page.FieldMismatchError('SKU 行的图片数不是 1：' + '、'.join(binding['specs']))
        if not _detail_url_matches(str(images[0]), binding['url']):
            raise page.FieldMismatchError('SKU 图片身份已变化：' + '、'.join(binding['specs']))


def _detail_receipts_from_ledger(item):
    """从**上传账本**补齐详情图回执（按本地文件身份查，不按名字猜）。

    为什么需要：`prepared_media` 是「本次运行的上传结果」，只有真跑过
    `upload_images` 才有。用 `--start-from fill_detail`（或断点续跑）时它是空的，
    但**图其实早就按同一身份传进图片空间了**——账本里就有回执。
    只补 `item.images.detail` 里缺的那些，顺序与 `images.detail` 对齐；
    任何一张查不到就**返回 None**（让调用方明确报缺，不用部分回执糊过去）。
    """

    from .protocol_media import UploadLedger

    if not item.images.detail:
        return None
    ledger = UploadLedger.load()
    rows = []
    for path in item.images.detail:
        try:
            identity = media_file_identity(path, item.record_id, 'detail')
        except Exception:  # noqa: BLE001 - 文件不在本地就不能确认身份
            return None
        record = ledger.lookup(identity)
        if not record or not record.get('url'):
            return None
        rows.append({'path': str(path), 'name': identity['name'],
                     'url': str(record.get('url') or ''),
                     'picture_id': str(record.get('picture_id') or ''),
                     'uploaded_now': False})
    return rows


def fill_detail_by_picture_id(client, item, contracts, prepared_media):
    """**按 `pictureId` 把详情图写进模块编辑器**（实测跑通的路径）。

    ## 与 `fill_detail` 的区别（为什么需要另一条）

    `fill_detail` 走的是契约 `detail.editor = [contenteditable="true"],textarea`
    ——那是**旧版图文描述**的形态。新版详情是**模块化编辑器**，里面
    `contenteditable` 与 `textarea` **都是 0**（实测 E-233/234），所以那条路
    会报 `detail_editor_not_unique`。

    新版正确路径（实测 E-235）：
    1. 点详情行的 `[data-type="pic"]`「图片」模块 → 平台弹出**同一个
       `sucai-selector-ng` 选图器**（`max=100` 多选实例）；
    2. 在选图器 iframe 内**按 `pictureId` 勾选**（卡片 `checkbox.value` = 回执 `fileId`）；
    3. 点页脚「确定」（文案带计数如 `确定（3）`，靠类名 `Footer_selectOk` 定位）；
    4. 回读详情区内容图，按**资源标识**核对身份与顺序。

    注意：勾选是**切换**语义，已选中的再点会取消——所以必须先读 `checkbox.checked`。

    :raises page.PageError: 任何一步没达到预期都失败，**不把"选上了"当"写进去了"**。
    """

    receipts = detail_receipts_for(item, prepared_media)
    if [r['path'] for r in receipts] != item.images.detail:
        raise page.PageError('详情图上传回执与输入顺序不一致（账本也补不齐，拒绝用部分回执）')
    picture_ids = [str(r.get('picture_id') or '') for r in receipts]
    if not picture_ids or any(not value for value in picture_ids):
        raise page.PageError('详情图缺少 pictureId，无法按 ID 选图（不允许退回按名字猜）')

    opened = client.evaluate(page.build_open_detail_pic_module_expression(), timeout=45.0)
    if not isinstance(opened, dict) or opened.get('ok') is not True:
        raise page.PageError('详情「图片」模块未打开：' + str(
            (opened or {}).get('reason') if isinstance(opened, dict) else '无有效返回'))
    time.sleep(2.0)
    context_id = page.media_iframe_context(client, timeout=20.0)
    # ⚠️ 按用途分目录归档后，详情图在「全部图片/<商品>/详情页」子目录里，
    # 而选图器默认停在根图库（或上次停留的目录）——不进目录就按 ID 勾，
    # 14 张会全部报 missing（2026-10-08 run13 实测）。优先用回执自带的
    # folder_path；账本补齐的回执没有它，就按归档约定推导。
    # （树根「全部图片」是否要在路径里带上，由 open_directory 按树实况换算。）
    from .media_library import open_directory, pick_media_by_id_with_requery, ALL_IMAGES_NODE
    folder = next((list(r['folder_path']) for r in receipts if r.get('folder_path')), None)
    if folder is None:
        folder = [ALL_IMAGES_NODE, item.record_name, '详情页']
    actual_folder = open_directory(client, folder, context_id=context_id, expected_images=receipts)
    for receipt in receipts:
        receipt['folder_path'] = list(actual_folder)
    # `wait` 是"等卡片渲染出来"的上限（详情这条也走同一张图库，见 E-277）。
    try:
        picked = pick_media_by_id_with_requery(client, picture_ids, context_id=context_id,
                                               select=True, wait=10.0, stage='fill_detail', expected_urls={str(r['picture_id']):r['url'] for r in receipts})
    except page.MediaImageMissing:
        # ⚠️ 与主图路径同一恢复思路（2026-10-08 run53 真机：详情 12 张全 missing）：
        # 选图器刚打开时卡片偶发渲染不出，10s 轮询 + 点走再点回共 20s 都等不到。
        # 重开选图器是完整重置——平台对新弹层一定会做初始加载。missing 时表达式
        # 还没勾选任何卡片（先找齐再勾），重试是幂等的。图真不在则第二次仍如实抛。
        page.ensure_media_popup_closed(client)
        reopened = client.evaluate(page.build_open_detail_pic_module_expression(), timeout=45.0)
        if not isinstance(reopened, dict) or reopened.get('ok') is not True:
            raise page.PageError('详情「图片」模块重开失败：' + str(
                (reopened or {}).get('reason') if isinstance(reopened, dict) else '无有效返回'))
        time.sleep(2.0)
        context_id = page.media_iframe_context(client, timeout=20.0)
        actual_folder = open_directory(client, folder, context_id=context_id, expected_images=receipts)
        picked = pick_media_by_id_with_requery(client, picture_ids, context_id=context_id,
                                               select=True, wait=10.0, stage='fill_detail', expected_urls={str(r['picture_id']):r['url'] for r in receipts})
    confirmed = page.confirm_media_selection(client, context_id=context_id)
    time.sleep(2.0)
    actual = client.evaluate(page.build_detail_content_images_expression(), timeout=30.0)
    if not isinstance(actual, dict) or actual.get('ok') is not True:
        raise page.PageError('详情区回读失败：' + str(
            (actual or {}).get('reason') if isinstance(actual, dict) else '无有效返回'))
    actual_identities = [_identity_of(str(url)) for url in (actual.get('images') or [])]
    want = [_identity_of(str(r['url'])) for r in receipts]
    if actual_identities != want:
        raise page.FieldMismatchError('详情区图片身份或顺序与本次回执不一致')
    return [dict(r) for r in receipts]


def _identity_of(url: str) -> str:
    from .upload_api import image_identity

    return image_identity(url)


def _identity_strict(url: str) -> str:
    """比 `_identity_of` **更严**的身份串：没有 `O1CN` 标识时**保留整个地址**。

    为什么需要（实测踩过）：详情回读一度只用 `image_identity`（取 `O1CN…`）比较，
    对**没有该标识**的地址（如夹具里的 `img.example.invalid/...?version=…`）
    两边都取到空串，于是"内容变了"检测不出来——把一条既有断言打成"该报错却没报"。
    这里在没有标识时退回**整串去挥发参数**后的地址，保证「换了地址就判不一致」。
    """

    from .upload_api import image_identity, _url_without_volatile_query

    identity = image_identity(url)
    if identity:
        return identity
    return _url_without_volatile_query(url)


def detail_content_is_empty(client, *, timeout: float = 20.0) -> bool:
    """详情区是否**没有实质内容**（决定能否安全切换到旧版）。

    判据：详情行里没有尺寸大于 40px 的 ``<img>``（平台自己的图标是 12×12 SVG，
    实测那 3 张都是图标，不能当内容），且模块面板里没有子模块。

    ⚠️ 这个检查是"切换旧版"的**前置条件**：平台明确提示切换会**清空详情内容**，
    所以有内容时绝不能切。判不准时**返回 False**（保守：宁可不切）。
    """

    expression = r'''(() => {
      const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      const rows = Array.from(document.querySelectorAll('.sell-component-info-wrapper-wrap')).filter(row => {
        const labels = row.querySelectorAll('.sell-component-info-wrapper-label');
        return labels.length === 1 && text(labels[0]).replace(/\s|\*/g, '') === '宝贝详情';
      });
      if (rows.length !== 1) return { ok: false, reason: 'detail_row_not_unique' };
      const host = rows[0].querySelector('.sell-component-lite-decoration-editor') || rows[0];
      const contentImages = Array.from(host.querySelectorAll('img')).filter(img => {
        const r = img.getBoundingClientRect();
        return r.width > 40 || r.height > 40;
      }).length;
      const modules = host.querySelectorAll('[class*="panel_edit_content"] > *').length;
      return { ok: true, contentImages: contentImages, modules: modules };
    })()'''
    payload = client.evaluate(expression, timeout=timeout)
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return False
    return int(payload.get("contentImages") or 0) == 0 and int(payload.get("modules") or 0) == 0


def _detail_matches(actual_urls, expected_urls) -> bool:
    """详情区回读的 URL 是否就是写入的那批图。

    ⚠️ **不能逐字比**：详情编辑器/平台会把 ``src`` 规整成另一种形态（转码、加参数），
    逐字比会把同一张图判成不一致。判据用稳定资源标识（``O1CN…``），
    顺序必须与写入顺序一致。取不到标识时退回逐字比较（不误杀普通地址）。
    """

    if len(actual_urls) != len(expected_urls):
        return False
    return all(page._images_match(str(actual), str(expected))
               for actual, expected in zip(actual_urls, expected_urls))


def detail_receipts_for(item, prepared_media):
    """取详情图回执：优先用**本次运行**的，缺了就按身份从**账本**补齐。

    `prepared_media` 只在真跑过 `upload_images` 时才有内容；断点续跑
    （`--start-from fill_detail`）时它是空的或不完整。图其实早已按**同一身份**
    入过库，账本里就有回执——按 `sha256` 身份查，不按名字猜。
    补不齐就返回 ``[]``，由调用方明确报错，**不用部分回执糊过去**。
    """

    receipts = list((prepared_media or {}).get('detail') or [])
    expected = list(getattr(item.images, 'detail', None) or [])
    if expected and [r.get('path') for r in receipts] == expected:
        # 本次运行的预扫回执可能没有 picture_id（卡片定位不带它）；
        # 详情模块编辑器按 ID 多选需要它——从账本按身份补齐，补不齐保持原样。
        try:
            from .protocol_media import UploadLedger
            ledger = UploadLedger.load()
        except Exception:  # noqa: BLE001
            ledger = None
        return [_attach_ledger_picture_id(r, ledger=ledger) for r in receipts]
    from_ledger = _detail_receipts_from_ledger(item)
    if from_ledger is not None:
        return from_ledger
    return receipts if [r.get('path') for r in receipts] == expected else []


def fill_detail(client, item, contracts, prepared_media):
    config = config_for(item, contracts, purpose='detail')
    receipts = detail_receipts_for(item, prepared_media)
    if [r['path'] for r in receipts] != item.images.detail:
        raise page.PageError('详情图上传回执与输入顺序不一致（账本也补不齐，拒绝用部分回执）')
    urls = [r['url'] for r in receipts]
    _checked(client, build_detail_expression(config, 'write', urls))
    _wait(client, build_detail_expression(config),
          lambda result: _detail_matches(result['urls'], urls)
          and not result['text'] and not result['hasOtherContent'])
    return [dict(r) for r in receipts]


def missing_media_roles(item, bound_media):
    missing = []
    if not isinstance(bound_media, dict):
        bound_media = {}
    sku = bound_media.get('sku', [])
    if not isinstance(sku, list):
        sku = []
    expected = [(sorted(s.spec_values.values()), s.image_path) for s in item.skus if s.image_path]
    provided = [(sorted(r.get('specs', [])), r.get('path')) for r in sku if isinstance(r, dict) and r.get('url')]
    if (item.images.sku or expected) and (not expected or sorted(expected) != sorted(provided)
            or set(item.images.sku) - {path for _, path in provided}):
        missing.append(('images.sku', 'SKU 图片'))
    detail = bound_media.get('detail', [])
    if item.images.detail and (not isinstance(detail, list) or not all(isinstance(r, dict) for r in detail)
                              or [r.get('path') for r in detail] != item.images.detail
                              or any(not r.get('url') for r in detail)):
        missing.append(('images.detail', '详情图片'))
    return missing


def _detail_url_matches(actual: str, expected: str) -> bool:
    """两个图片地址是否指向同一张图（按资源标识，不逐字比）。

    槽位/列表回读给的是**转码形态**（`…_320x320q80_.webp`），回执给的是原图地址，
    逐字比永远不等——这正是选图/回读一直失败的根因（E-227/E-230）。
    """

    return page._images_match(actual, expected)


def detail_uses_module_editor(client, *, timeout: float = 20.0) -> bool:
    """详情区当前是**新版模块编辑器**还是**旧版原生编辑区**。

    真机是新版（`contenteditable`/`textarea` 都是 0，E-233/234）；离线夹具与旧版
    类目是原生编辑区。两类形态**各有各的读取器**，所以先判形态再读——
    不判形态就会"拿 A 的读取器去读 B"，报出与真实原因无关的错误
    （实测把夹具打成 `detail_editor_not_unique`）。
    """

    payload = client.evaluate(r'''(() => {
      const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      const rows = Array.from(document.querySelectorAll('.sell-component-info-wrapper-wrap')).filter(row => {
        const labels = row.querySelectorAll('.sell-component-info-wrapper-label');
        return labels.length === 1 && text(labels[0]).replace(/\s|\*/g, '') === '宝贝详情';
      });
      if (rows.length !== 1) return { ok: false, reason: 'detail_row_not_unique', rowCount: rows.length };
      const native = Array.from(rows[0].querySelectorAll('[contenteditable="true"],textarea'))
        .filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }).length;
      const moduleHost = !!rows[0].querySelector('.sell-component-lite-decoration-editor');
      return { ok: true, native: native, moduleHost: moduleHost };
    })()''', timeout=timeout)
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise page.PageError('详情区形态判断失败：' + str(
            (payload or {}).get("reason") if isinstance(payload, dict) else '无有效返回'))
    # 同时存在时以**原生编辑区**为准（旧版能直接写 HTML，判据更硬）
    return int(payload.get("native") or 0) == 0 and bool(payload.get("moduleHost"))


def verify_bound_media(client, item, contracts, bound_media):
    config = config_for(item, contracts, purpose='readback')
    if missing_media_roles(item, bound_media):
        raise page.FieldMismatchError('媒体绑定回执不完整')
    if bound_media.get('sku'):
        verify_sku_images(client, config, bound_media['sku'])
    if item.images.detail:
        want_ids = [_identity_strict(str(r['url'])) for r in bound_media['detail']]
        # ⚠️ 详情有两种形态，**按形态选读取器**（真机=模块编辑器，旧版=原生编辑区）。
        # 与写入侧保持同一判据：有 `O1CN` 标识时按标识比，没有标识时按**整串**
        # （只忽略时间戳类参数）比——不逐字比 URL，但也不放过"地址真的变了"。
        if detail_uses_module_editor(client):
            actual = client.evaluate(page.build_detail_content_images_expression(), timeout=30.0)
            if not isinstance(actual, dict) or actual.get('ok') is not True:
                raise page.FieldMismatchError('详情区回读失败：' + str(
                    (actual or {}).get('reason') if isinstance(actual, dict) else '无有效返回'))
            actual_ids = [_identity_strict(str(u)) for u in (actual.get('images') or [])]
        else:
            legacy = _checked(client, build_detail_expression(config))
            actual_ids = [_identity_strict(str(u)) for u in (legacy.get('urls') or [])]
            if legacy.get('text') or legacy.get('hasOtherContent'):
                raise page.FieldMismatchError('详情区出现了图片以外的内容，与写入回执不一致')
        if actual_ids != want_ids:
            raise page.FieldMismatchError('详情图片顺序或图片身份与写入回执不一致')

# -*- coding: utf-8 -*-
"""抖店发布页（fxg.jinritemai.com/ffa/g/create）的页面级操作：清弹层、标题与品牌名、类目与属性、水洗标 / 吊牌、主图 / 白底图 / 详情图上传、SKU 规格、价格库存与发货、提交发布及其结果判定。

这里的函数只靠入参里的标签页对象、标准库、``src.utils`` 里的浏览器工具和本模块常量工作，不碰任务字典、锁、账户、``gui`` 和 Flask 请求上下文——所以能脱离任务状态直接单测（用假的标签页对象）。任务生命周期、浏览器会话和流程编排在 ``upload_service.UploadService``，HTTP 在 ``upload_routes``。

函数名保持 app.py 里的原名（含下划线前缀），便于新旧对照；函数体与搬迁前逐字相同。

这个模块直接导入 ``src.utils``（页面操作本来就依赖那套浏览器工具）；其余 ``src/sidecar`` 模块不应导入它，需要页面操作时由应用入口把函数作为端口注入。"""
import json
import os
import re
import time as system_time
from decimal import Decimal, InvalidOperation

from src.enhanced_category_selector import smart_select_category
from src.professional_title_generator import sanitize_no_brand_title_text
from src.utils import (
    _ensure_section_ready,
    _find_ai_material_tool_panel,
    _is_upload_busy,
    _wait_until,
    _white_bg_state,
    _xpath_literal,
    click_field_action,
    close_ai_material_tool_panel,
    ensure_no_brand,
    get_current_category_text,
    get_detail_pic_list,
    get_diaopai_pic,
    get_my_video,
    get_pic_list,
    get_sex,
    get_white_pic,
    handle_main_image_post_upload_prompts,
    handle_white_bg_post_upload_prompts,
    infer_sock_height_value,
    select_text,
    set_material_composition,
    set_sku_info,
    time,
    timer_record,
    upload_file,
    wazi_dict,
)


def _settle_between_records(main_tab):
    try:
        if main_tab:
            _wait_until(
                lambda: not _is_upload_busy(main_tab),
                timeout=0.4,
                interval=0.05,
            )
    except Exception:
        pass
    system_time.sleep(0.1)


_PUBLISH_CREATE_URL = 'https://fxg.jinritemai.com/ffa/g/create'

# 发布流程等待用户完成登录的上限。原来写死 150 次 × 0.2 秒 = 30 秒：
# 换账号、短信验证、甚至只是掏出手机扫码，都可能超过 30 秒，
# 超时后用户看到的是「超时未登录！！！」，只能从头再点一次发布——
# 而登录本来就和抖店后台一样是流程的一部分，不该被这么短的窗口判死。
_PUBLISH_LOGIN_WAIT_SECONDS = 180

_PUBLISH_LOGIN_WAIT_POLL_SECONDS = 0.2


def _wait_login_complete(page, report_progress):
    """等待用户在浏览器里完成登录。

    窗口按 ``_PUBLISH_LOGIN_WAIT_SECONDS`` 给足（默认 3 分钟），并且首次
    等待时就把「请先在浏览器完成登录」说清楚——用户不知道程序在等什么的时候，
    再长的超时也只会被当成卡死。
    """
    attempts = max(1, int(_PUBLISH_LOGIN_WAIT_SECONDS / _PUBLISH_LOGIN_WAIT_POLL_SECONDS))
    wait_notice_every = max(1, attempts // 12)
    reported_waiting = False
    for idx in range(attempts):
        current_url = str(page.url or '')
        if '/homepage' in current_url or '/ffa/g/create' in current_url:
            return True
        if idx % wait_notice_every == 0:
            # 第一次是提醒去登录，之后是「还在等」——两者对用户的意义不同。
            report_progress(14, '请在浏览器中完成登录，登录后会自动继续' if not reported_waiting else '仍在等待登录完成')
            reported_waiting = True
        time.sleep(_PUBLISH_LOGIN_WAIT_POLL_SECONDS)
    return False


def _dismiss_pending_browser_alert(main_tab):
    try:
        main_tab.handle_alert(next_one=True)
    except Exception:
        pass


def _prepare_record_assets(record):
    if not record.title:
        return None, '标题为空！！！'
    if not record.clazz:
        return None, '类目为空！！！'
    if not str(record.repo):
        return None, '库存为空！！！'

    try:
        main_pic_list = get_pic_list(record, '800')
    except:
        return None, '未找到主图或者主图不全！！！'

    try:
        sub_pic_list = get_pic_list(record, '750')
        if record.type == 2 and len(sub_pic_list) == 0:
            print('ID模式：没有3:4主图，将使用平台自带的1:1导入功能')
    except:
        if record.type == 1:
            return None, '未找到4:3主图或者4:3主图不全！！！'
        sub_pic_list = []
        print('ID模式：获取3:4主图时出现异常，将使用平台自带的1:1导入功能')

    try:
        detail_pic_list = get_detail_pic_list(record)
    except:
        return None, '未找到详情图！！！'

    diaopai_pic = get_diaopai_pic(record)
    my_video = get_my_video(record)

    sku_list = json.loads(record.content)
    if len(sku_list) == 0:
        return None, '未找到sku信息！！！'

    for sku_item in sku_list:
        if not sku_item['name'] or sku_item['price'] is None:
            return None, 'sku信息不全！！！'
        try:
            float(sku_item['price'])
        except (ValueError, TypeError):
            return None, 'sku信息不全！！！'

    white_pic = get_white_pic(record, sku_list)
    return {
        'main_pic_list': main_pic_list,
        'sub_pic_list': sub_pic_list,
        'detail_pic_list': detail_pic_list,
        'diaopai_pic': diaopai_pic,
        'my_video': my_video,
        'sku_list': sku_list,
        'white_pic': white_pic,
    }, None


_INTERFERING_OVERLAY_TEXTS = (
    '我知道了',
    '知道了',
    '暂不',
    '跳过',
    '关闭引导',
    '关闭新手引导',
    '稍后再说',
    '下次再说',
    '以后再说',
)


def _build_overlay_button_selector(scope_expr=None):
    predicate_parts = []
    for text in _INTERFERING_OVERLAY_TEXTS:
        predicate_parts.append(f'normalize-space(.)="{text}"')
        predicate_parts.append(f'.//span[normalize-space(.)="{text}"]')
    predicate = ' or '.join(predicate_parts)
    base = '//*[self::button or @role="button"]'
    if scope_expr:
        base = f'//*[{scope_expr}]//*[self::button or @role="button"]'
    return f'xpath:{base}[{predicate}]'


_VISIBLE_SELECTOR_PROBE_JS = r'''
const specs = arguments[0] || [];
for (let i = 0; i < specs.length; i++) {
    const spec = specs[i];
    let nodes = [];
    try {
        if (spec.t === 'x') {
            const found = document.evaluate(spec.e, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
            for (let j = 0; j < found.snapshotLength; j++) nodes.push(found.snapshotItem(j));
        } else {
            nodes = Array.prototype.slice.call(document.querySelectorAll(spec.e));
        }
    } catch (err) {
        continue;
    }
    for (let k = 0; k < nodes.length; k++) {
        const node = nodes[k];
        if (!node || node.nodeType !== 1) continue;
        if (node.offsetParent || node.getClientRects().length > 0) return i;
    }
}
return -1;
'''


def _first_visible_selector_index(tab, selectors):
    """用一次 JS 批量判定哪个选择器命中可见元素。

    返回命中下标；全部落空返回 -1；JS 不可用返回 None（调用方回退原逐个探测）。

    DrissionPage 的 ele/eles 在**未命中时会阻塞满 timeout** 才返回，
    所以「准备 N 个候选选择器逐个试」的落空成本是 N × timeout，
    常见组合就是 1~2.5 秒的纯空转。先用一次 JS 判定可把它压成一次往返。
    """
    specs = []
    for selector in selectors:
        text = str(selector)
        if text.startswith('xpath:'):
            specs.append({'t': 'x', 'e': text[6:]})
        elif text.startswith('css:'):
            specs.append({'t': 'c', 'e': text[4:]})
        else:
            specs.append({'t': 'c', 'e': text})
    if not specs:
        return -1
    try:
        index = tab.run_js(_VISIBLE_SELECTOR_PROBE_JS, specs)
    except Exception:
        return None
    if isinstance(index, bool) or not isinstance(index, (int, float)):
        return None
    return int(index)


def _find_first_visible_element(tab, selectors, timeout=0.15):
    ordered = list(selectors)
    index = _first_visible_selector_index(tab, ordered)
    if index is not None:
        if index < 0:
            return None
        # 命中的选择器排到最前，其余保留作兜底（JS 可见性判据与
        # DrissionPage states.is_displayed 极少数情况下可能不一致）
        ordered = [ordered[index]] + [item for pos, item in enumerate(ordered) if pos != index]

    for selector in ordered:
        try:
            elements = tab.eles(selector, timeout=timeout)
        except Exception:
            continue
        for element in elements:
            try:
                if element and element.states.is_displayed:
                    return element
            except Exception:
                continue
    return None


def _click_element_safely(element):
    try:
        element.scroll.to_center()
    except Exception:
        pass
    for action in (
        lambda: element.click(),
        lambda: element.click(by_js=True),
        lambda: element.run_js('arguments[0].click();', element),
    ):
        try:
            action()
            return True
        except Exception:
            continue
    return False


def _is_element_displayed(element):
    if not element:
        return False
    try:
        return bool(element.states.is_displayed)
    except Exception:
        return False


def _dismiss_interfering_overlays(main_tab, context=''):
    total_actions = 0

    try:
        drag_selector = 'xpath://div[contains(@class,"index_DragController__")]'
        drag_index = _first_visible_selector_index(main_tab, [drag_selector])
        # JS 明确缺席时不再发起 0.1s 的空查询；不可用或命中时保留原路径。
        drag_controller = None if drag_index == -1 else main_tab.ele(drag_selector, timeout=0.1)
        if drag_controller and drag_controller.states.is_displayed:
            main_tab.remove_ele(drag_controller)
            total_actions += 1
    except Exception:
        pass

    overlay_root = (
        'contains(@class,"ecom-g-modal") or contains(@class,"ecom-g-popover") '
        'or @role="dialog" or contains(@class,"guide") or contains(@class,"Guide") '
        'or contains(@class,"tour") or contains(@class,"Tour") '
        'or contains(@class,"coach") or contains(@class,"Coach")'
    )

    text_button_selector = _build_overlay_button_selector()
    scoped_text_button_selector = _build_overlay_button_selector(overlay_root)
    close_button_selector = (
        f'xpath://*[{overlay_root}]//*[self::button or @role="button"]'
        '[contains(@aria-label,"关闭") or contains(@title,"关闭") '
        'or contains(@class,"close") or contains(@class,"Close")]'
    )

    for _ in range(2):
        clicked = False
        selectors = [scoped_text_button_selector, text_button_selector]
        for text in ():
            selectors.extend([
                f'xpath://button[normalize-space(.)="{text}" or .//span[normalize-space(.)="{text}"]]',
                f'xpath://*[{overlay_root}]//*[self::button or @role="button"][normalize-space(.)="{text}" or .//span[normalize-space(.)="{text}"]]',
                f'xpath://*[{overlay_root}]//*[normalize-space(.)="{text}"]/ancestor::*[self::button or @role="button"][1]',
            ])
        selectors.extend([
            f'xpath://*[{overlay_root}]//*[self::button or @role="button"][contains(@aria-label,"关闭") or contains(@title,"关闭")]',
            f'xpath://*[{overlay_root}]//*[self::button or @role="button"][contains(@class,"close") or contains(@class,"Close")]',
        ])
        target = _find_first_visible_element(main_tab, selectors, timeout=0.02)
        if target and _click_element_safely(target):
            clicked = True
            total_actions += 1
            _wait_until(
                lambda: not _is_element_displayed(target),
                timeout=0.18,
                interval=0.03,
            )

        if not clicked:
            break

    if total_actions > 0:
        print(f'已处理干扰弹层{total_actions}次' + (f'，阶段: {context}' if context else ''))
    return total_actions


def _get_title_input(main_tab, timeout=0.3):
    title_field = main_tab.ele('xpath://div[@attr-field-id="商品标题"]', timeout=timeout)
    if not title_field:
        return None

    selectors = [
        'xpath:.//input[@id="pg-title-input"]',
        'xpath:.//input[@type="text"]',
        'xpath:.//input',
        'xpath:.//textarea',
    ]
    for selector in selectors:
        try:
            candidates = title_field.eles(selector, timeout=0.05)
        except Exception:
            candidates = []
        for item in candidates:
            try:
                if item and item.states.is_displayed:
                    return item
            except Exception:
                continue
    return None


def _find_title_brand_name_checkbox(main_tab):
    try:
        title_field = main_tab.ele('xpath://div[@attr-field-id="商品标题"]', timeout=0.2)
    except Exception:
        title_field = None
    if not title_field:
        return None, None

    label = None
    label_selectors = [
        'xpath:.//*[normalize-space(.)="使用品牌名"]/ancestor::label[1]',
        'xpath:.//*[contains(normalize-space(.),"使用品牌名")]/ancestor::label[1]',
    ]
    for selector in label_selectors:
        try:
            item = title_field.ele(selector, timeout=0.08)
        except Exception:
            item = None
        if item:
            label = item
            break

    checkbox = None
    search_scope = label or title_field
    checkbox_selectors = [
        'xpath:.//input[@type="checkbox"]',
        'xpath:.//*[@role="checkbox"]',
    ]
    for selector in checkbox_selectors:
        try:
            item = search_scope.ele(selector, timeout=0.08)
        except Exception:
            item = None
        if item:
            checkbox = item
            break
    return checkbox, label


def _checkbox_is_checked(element):
    if not element:
        return False
    for attr_name in ('checked', 'aria-checked'):
        try:
            raw_value = element.attr(attr_name)
        except Exception:
            raw_value = None
        if str(raw_value).strip().lower() in ('true', 'checked', '1'):
            return True
    try:
        return bool(
            element.run_js(
                'return !!this.checked || this.getAttribute("aria-checked") === "true" || '
                '!!(this.closest("label") && String(this.closest("label").className || "").includes("checked"));'
            )
        )
    except Exception:
        return False


def _ensure_title_brand_name_disabled(main_tab):
    checkbox, label = _find_title_brand_name_checkbox(main_tab)
    if not checkbox:
        return
    if not _checkbox_is_checked(checkbox):
        return

    print('取消标题区“使用品牌名”')
    target = label or checkbox
    if not _click_element_safely(target):
        raise Exception('标题区“使用品牌名”取消失败')

    if not _wait_until(
        lambda: not _checkbox_is_checked(_find_title_brand_name_checkbox(main_tab)[0]),
        timeout=0.8,
        interval=0.05,
    ):
        raise Exception('标题区“使用品牌名”仍处于勾选状态')


_PUBLISH_STEP1_SELECTORS = [
    'xpath://button[.//span[text()="下一步"]]',
    'xpath://span[text()="下一步"]/..',
    'xpath://div[contains(@class,"categorySelectorV2")]',
    'xpath://span[text()="手动选择"]/..',
    # 2026-10 新版 AI 发布页；追加而不替换，继续兼容旧版「下一步」。
    'xpath://button[.//span[normalize-space(text())="确认信息，继续生成"]]',
    'xpath://span[normalize-space(text())="确认信息，继续生成"]/..',
    'xpath://button[contains(@class,"aiPublishButton")]',
]

_PUBLISH_STEP2_SELECTORS = [
    'xpath://div[@attr-field-id="价格与库存"]',
    'xpath://div[@id="goodsEditScrollContainer-价格库存"]',
    'xpath://div[@attr-field-id="售卖价"]',
    'xpath://div[@attr-field-id="订单库存计数"]',
    'xpath://div[@attr-field-id="主图3:4"]',
    'xpath://div[@attr-field-id="主图视频"]',
    'xpath://div[@attr-field-id="商品类目"]//*[text()="修改"]',
    'xpath://div[@attr-field-id="类目属性"]',
    'xpath://aside[contains(@class,"index-module_assistant__")]',
]


def _get_current_tab_url(main_tab):
    try:
        return str(main_tab.url or '')
    except Exception:
        return ''


def _is_any_selector_visible(main_tab, selectors, timeout=0.05):
    return _find_first_visible_element(main_tab, selectors, timeout=timeout) is not None


_PUBLISH_STAGE_PROBE_JS = r'''
const step2 = arguments[0] || [];
const step1 = arguments[1] || [];
const visible = function (node) {
    return !!node && node.nodeType === 1 && (node.offsetParent || node.getClientRects().length > 0);
};
const anyVisible = function (xpaths) {
    for (let i = 0; i < xpaths.length; i++) {
        try {
            const found = document.evaluate(xpaths[i], document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
            for (let j = 0; j < found.snapshotLength; j++) {
                if (visible(found.snapshotItem(j))) return true;
            }
        } catch (err) {
            continue;
        }
    }
    return false;
};
if (anyVisible(step2)) return 'step2';
const titleField = document.querySelector('[attr-field-id="商品标题"]');
let titleReady = false;
if (titleField) {
    titleReady = visible(titleField.querySelector('#pg-title-input') || titleField.querySelector('input') || titleField.querySelector('textarea'));
}
if (titleReady || anyVisible(step1)) return 'step1';
return 'unknown';
'''


def _detect_publish_page_stage(main_tab):
    current_url = _get_current_tab_url(main_tab)
    if '/ffa/g/create' not in current_url:
        return 'outside'

    # 一次 JS 判定整页阶段。原实现要逐个探测 13~18 条 XPath（约 0.6~0.9s），
    # 而本函数是 _wait_until(interval=0.1) 的判据，会让轮询间隔彻底失效。
    try:
        stage = main_tab.run_js(
            _PUBLISH_STAGE_PROBE_JS,
            [item[6:] for item in _PUBLISH_STEP2_SELECTORS],
            [item[6:] for item in _PUBLISH_STEP1_SELECTORS],
        )
    except Exception:
        stage = None
    if stage in ('step1', 'step2', 'unknown'):
        return stage

    # JS 不可用时回退到逐个探测
    if _is_any_selector_visible(main_tab, _PUBLISH_STEP2_SELECTORS, timeout=0.05):
        return 'step2'

    step1_selectors = list(_PUBLISH_STEP1_SELECTORS)
    title_input = _get_title_input(main_tab, timeout=0.05)
    if title_input:
        step1_selectors.append('xpath://div[@attr-field-id="商品标题"]')

    if _is_any_selector_visible(main_tab, step1_selectors, timeout=0.05):
        return 'step1'

    return 'unknown'


_PUBLISH_FORM_SNAPSHOT_JS = r'''
const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
const fields = Array.from(document.querySelectorAll('[attr-field-id]')).map((node) => {
    const inputs = Array.from(node.querySelectorAll('input:not([type="file"]), textarea')).map((input) => ({
        type: input.type || '',
        value: String(input.value || ''),
        checked: !!input.checked
    }));
    const selections = Array.from(node.querySelectorAll(
        '[class*="select-selection-item"], [class*="selection-item-content"], [class*="cascader-picker-label"]'
    )).map((item) => norm(item.innerText || item.getAttribute('title'))).filter(Boolean);
    return {
        id: node.getAttribute('attr-field-id') || '',
        visible: !!(node.offsetParent || node.getClientRects().length),
        inputs: inputs,
        selections: selections
    };
});
const body = document.body ? document.body.innerText || '' : '';
const assistant = document.querySelector('aside[class*="index-module_assistant__"]');
const aiComplete = !!(
    (assistant && /index-module_completed__/.test(assistant.className || ''))
    || body.indexOf('已帮您自动填入商品信息') >= 0
);
const aiPresent = !!assistant || /AI\s*智能填写/.test(body) || aiComplete;
const cancelVisible = !!(assistant && Array.from(assistant.querySelectorAll('button, [role="button"], span, div, a')).some((node) => {
    return norm(node.innerText || node.textContent) === '取消识别'
        && (node.offsetParent || node.getClientRects().length);
}));
const titleField = document.querySelector('[attr-field-id="商品标题"]');
const titleInput = document.querySelector('#pg-title-input') || (titleField && titleField.querySelector('input, textarea'));
return {
    aiStatus: aiComplete ? 'complete' : (aiPresent ? 'active' : 'none'),
    cancelVisible: cancelVisible,
    title: titleInput ? String(titleInput.value || '') : '',
    fields: fields,
    fingerprint: JSON.stringify(fields)
};
'''


def _read_publish_form_snapshot(main_tab):
    """读取当前页面的 AI 状态、字段骨架和值快照；JS 不可用时返回 None。"""
    try:
        snapshot = main_tab.run_js(_PUBLISH_FORM_SNAPSHOT_JS)
    except Exception:
        return None
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('fields'), list):
        return None
    if snapshot.get('aiStatus') not in ('none', 'active', 'complete'):
        return None
    return snapshot


def _find_ai_prefill_cancel_button(main_tab):
    """AI 智能填写助手中的「取消识别」，不扩大到其它 OCR/上传取消按钮。"""
    return _find_first_visible_element(
        main_tab,
        [
            'xpath://aside[.//*[contains(normalize-space(.),"智能填写")]]'
            '//*[normalize-space(.)="取消识别"]',
            'xpath://aside[contains(@class,"assistant") or contains(@class,"Assistant")]'
            '//*[normalize-space(.)="取消识别"]',
        ],
        timeout=0.06,
    )


def _cancel_ai_prefill_if_present(main_tab, timeout=2.0):
    """按钮出现即取消；点击后必须确认入口消失，不能把未生效当成功。"""
    button = _find_ai_prefill_cancel_button(main_tab)
    if not button:
        return False
    print('检测到AI智能填写，点击「取消识别」，后续按商品资料初始化')
    if not _click_element_safely(button):
        raise Exception('AI「取消识别」按钮点击失败')
    if not _wait_until(
        lambda: not _find_ai_prefill_cancel_button(main_tab),
        timeout=timeout,
        interval=0.05,
    ):
        raise Exception('AI「取消识别」点击后入口仍未消失，已停止以避免继续自动填写')
    return True


def _wait_for_ai_prefill_ready(main_tab, timeout=30.0, interval=0.12, cancel_ai=True):
    """出现「取消识别」即取消；否则等 AI 完成且字段连续稳定。

    旧版没有 AI 卡片时只需两次一致快照，不增加固定等待；JS 不可用返回 None，
    由调用方走原有兼容流程。AI 仍在填写或取消后仍不稳定时必须停止，不能抢写。
    """
    deadline = system_time.perf_counter() + timeout
    last_fingerprint = None
    stable_samples = 0
    saw_active_ai = False
    cancel_requested = False
    while True:
        snapshot = _read_publish_form_snapshot(main_tab)
        if snapshot is None:
            return None
        status = snapshot['aiStatus']
        if cancel_ai and status == 'active' and snapshot.get('cancelVisible'):
            # 可见性已包含在快照里；按钮在任意一次轮询出现时都立即取消。
            cancel_requested = _cancel_ai_prefill_if_present(main_tab) or cancel_requested
        saw_active_ai = saw_active_ai or status == 'active'
        fingerprint = str(snapshot.get('fingerprint') or '')
        stable_samples = stable_samples + 1 if fingerprint == last_fingerprint else 1
        last_fingerprint = fingerprint
        if stable_samples >= 2:
            if status == 'complete' or (status == 'none' and not saw_active_ai):
                if cancel_requested and status != 'complete':
                    snapshot = dict(snapshot, cancelled=True)
                return snapshot
            if cancel_requested and not snapshot.get('cancelVisible'):
                return dict(snapshot, cancelled=True)
        if system_time.perf_counter() >= deadline:
            break
        system_time.sleep(interval)
    if saw_active_ai:
        if cancel_requested:
            raise Exception('AI 取消识别后页面仍不稳定，已停止后续操作以避免与自动填写同时写入')
        raise Exception('AI 智能填写尚未完成，已停止后续操作以避免覆盖平台预填；请稍后重试')
    # 旧版没有 AI 卡片时，超时只是没等到稳定快照，不应被误报为 AI 未完成。
    return snapshot


def _restore_record_title_after_ai(main_tab, record, snapshot):
    """AI 完成或取消识别后，若标题被改写则恢复商品记录目标值。"""
    if not snapshot or (snapshot.get('aiStatus') != 'complete' and not snapshot.get('cancelled')):
        return False
    safe_title = sanitize_no_brand_title_text(record.title)
    if safe_title and str(snapshot.get('title') or '').strip() != safe_title:
        print('检测到 AI 改写了商品标题，按商品记录恢复目标标题')
        _fill_title_for_record(main_tab, record)
        return True
    return False


def _click_return_to_old_version(main_tab):
    """检测新版 AI 生成引导页并点击"返回旧版"按钮。

    2026-08 抖店新版发品页把"返回旧版"改成直接持有文本的
    <div class="styles-module_lightButton__...">，React onClick 绑定在该 div 自身。
    旧的 //span[text()="返回旧版"]/.. 选择器实测命中 0 个节点，导致 _open_publish_page
    在入口就返回失败。这里按文本直接命中持有点击句柄的元素本身，保留旧结构兜底。
    """
    btn = _find_first_visible_element(
        main_tab,
        [
            'xpath://div[normalize-space(text())="返回旧版"]',
            'xpath://*[normalize-space(text())="返回旧版"]',
            'xpath://button[.//span[text()="返回旧版"]]',
            'xpath://span[text()="返回旧版"]/..',
            'xpath://span[text()="返回旧版"]',
        ],
        timeout=0.5,
    )
    if not btn:
        return False
    print('检测到新版AI引导页，点击"返回旧版"')
    return _click_element_safely(btn)


def _open_publish_page(main_tab, report_progress):
    print('打开商品发布页面...')
    report_progress(22, '正在打开商品发布页面')
    _dismiss_pending_browser_alert(main_tab)

    def _settle_to_stage(targets, timeout):
        """轮询到页面进入目标阶段；停在新版 AI 引导页时点一次「返回旧版」。

        取代原先「固定 sleep(1.0) + 点返回旧版 + 固定 sleep(1.5)」的写法：
        那些延时没有任何判据，页面快时纯浪费、页面慢时又不够。
        """
        deadline = system_time.perf_counter() + timeout
        clicked_old = False
        stage = _detect_publish_page_stage(main_tab)
        while True:
            if stage in targets:
                return stage
            if stage == 'unknown' and not clicked_old:
                # AI 引导页在本函数的判据里就是 unknown
                clicked_old = _click_return_to_old_version(main_tab)
            if system_time.perf_counter() >= deadline:
                return stage
            system_time.sleep(0.1)
            stage = _detect_publish_page_stage(main_tab)

    # 会话可能刚导航到发布页，React 尚未 hydrate；先给一小段时间等它渲染，
    # 避免因为「检测早了一步」判成 unknown 而白白再整页重载一次。
    stage = _settle_to_stage(('step1', 'step2'), timeout=3.0)
    if stage not in ('step1', 'step2'):
        main_tab.get(_PUBLISH_CREATE_URL)
        stage = _settle_to_stage(('step1', 'step2'), timeout=10)
        if stage not in ('step1', 'step2'):
            return False

    if stage == 'step2':
        report_progress(22, '检测到停留在第二页面，正在返回第一页')
        main_tab.get(_PUBLISH_CREATE_URL)
        stage = _settle_to_stage(('step1',), timeout=10)
        if stage != 'step1':
            return False
    elif stage != 'step1':
        return False

    _dismiss_interfering_overlays(main_tab, context='open_publish_page')

    try:
        republish_btn = _find_first_visible_element(
            main_tab,
            ['xpath://span[text()="重新发布"]/../..'],
            timeout=0.15,
        )
        if republish_btn:
            republish_btn.click(by_js=True)
            _dismiss_interfering_overlays(main_tab, context='republish')
    except Exception:
        pass
    return True


def _is_element_lost_error(exc) -> bool:
    """判断异常是否属于「元素句柄失效」。

    fxg 发布页是 Garfish SSR + React hydrate 的微前端，节点会被 React 重建，
    已持有的 DrissionPage 句柄随之作废 —— 后续任何操作（click / input / 读 rect）
    都会抛 ElementLostError、NoRectError 或底层 CDP 的
    `Could not find node with given id`。

    这里按「类名 + 消息」判定而不是硬导入 DrissionPage 的异常类：
    包结构或导出路径变化时不会静默退化成"永远判否"。
    """
    name = type(exc).__name__
    if name in ('ElementLostError', 'NoRectError', 'ContextLostError'):
        return True
    text = str(exc)
    return 'Could not find node with given id' in text or '元素对象已失效' in text


def _title_field_stable(main_tab, samples: int = 2, interval: float = 0.08, timeout: float = 2.0) -> bool:
    """商品标题输入框是否已连续 samples 次稳定存在。

    `_detect_publish_page_stage` 的 step1 判据可以被 hydrate **之前**的 SSR DOM 满足，
    于是代码会在表单还没渲染稳定时就取到句柄，约 0.4s 后 React 重建该节点、句柄作废。
    实测 6 次 `fill_title` 失败全部死在 `input_element.click()` 的 ElementLostError
    （见 output/browser-debug/upload_error_*/*_fill_title_report.json 的 traceback）。
    """
    hits = 0
    deadline = system_time.perf_counter() + timeout
    while system_time.perf_counter() < deadline:
        if _get_title_input(main_tab, timeout=0.15):
            hits += 1
            if hits >= samples:
                return True
        else:
            hits = 0
        system_time.sleep(interval)
    return False


def _fill_title_for_record(main_tab, record):
    _dismiss_interfering_overlays(main_tab, context='fill_title')
    safe_title = sanitize_no_brand_title_text(record.title)
    if not safe_title:
        raise Exception('商品标题清理品牌后为空，不能继续发布')

    # 先确认输入框存在（给出明确的"没找到"错误），再等它渲染稳定，
    # 而不是取一次句柄就往下面用。
    if not _get_title_input(main_tab, timeout=0.4):
        raise Exception('未找到商品标题输入框')
    if not _title_field_stable(main_tab):
        print('  ⚠ 商品标题输入框未在 2s 内稳定下来，仍按当前句柄尝试写入')

    _ensure_title_brand_name_disabled(main_tab)

    # 关键：_ensure_title_brand_name_disabled 会操作页面并可能触发重渲染，
    # 上面取到的句柄到这一刻可能已经失效。这里改为**每次操作前重新取句柄**，
    # 并在句柄失效时重取重试 —— 而不是依赖"上游等得够久"这种巧合。
    last_error = None
    for attempt in range(1, 4):
        input_element = _get_title_input(main_tab, timeout=0.4)
        if not input_element:
            last_error = Exception('未找到商品标题输入框')
            system_time.sleep(0.15)
            continue
        try:
            input_element.click()
            time.sleep(0.05)
            input_element.input(safe_title)
        except Exception as exc:
            if not _is_element_lost_error(exc):
                raise
            last_error = exc
            print(f'  商品标题输入框句柄失效（第{attempt}次），重新取句柄后重试')
            system_time.sleep(0.15)
            continue
        if _wait_until(
            lambda: str(input_element.attr('value') or '').strip() == safe_title,
            timeout=0.8,
            interval=0.05,
        ):
            last_error = None
            break
        last_error = Exception('商品标题写入校验失败：输入框值未变成目标标题')
        system_time.sleep(0.15)

    if last_error is not None:
        raise Exception(f'商品标题写入失败（已重取句柄重试 3 次）：{last_error}')
    try:
        drag = main_tab.ele('xpath://div[contains(@class,"index_DragController__")]', timeout=0.2)
        if drag:
            main_tab.remove_ele(drag)
    except Exception:
        pass
    _dismiss_interfering_overlays(main_tab, context='fill_title')


def _upload_main_images(main_tab, record, main_pic_list):
    upload_file(main_tab, main_pic_list, '主图', error_size='长宽比需为1:1' if record.type == 2 else None)
    handle_main_image_post_upload_prompts(main_tab, timeout=2.0)


def _select_category_and_prepare_attributes(main_tab, record, diaopai_pic):
    _dismiss_interfering_overlays(main_tab, context='select_category')
    print(f'开始智能类目选择: {wazi_dict.get(record.clazz)}')
    if not smart_select_category(main_tab, record.clazz):
        print('类目选择失败，已尝试推荐与手动选择。请检查页面结构或账号资质。')
        raise Exception('类目选择失败')
    print('智能类目选择成功')
    form_snapshot = _wait_for_ai_prefill_ready(main_tab)
    _restore_record_title_after_ai(main_tab, record, form_snapshot)
    _dismiss_interfering_overlays(main_tab, context='select_category')

    gen_btn = main_tab.ele(
        'xpath://div[@data-better-log-outer-key="short_product_name"]'
        + '//span[contains(@class,"ecom-g-input-suffix")]//img',
        timeout=3,
    )
    if gen_btn:
        gen_btn.scroll.to_center()
        gen_btn.click(by_js=True)
        print('已点击生成短标题按钮')
    else:
        print('未找到生成短标题按钮，检查 XPath 或页面结构是否变化')

    _dismiss_interfering_overlays(main_tab, context='after_short_title')

    wash_tag_field_exists = False
    try:
        wash_tag_field_exists = bool(main_tab.ele('xpath://div[@attr-field-id="水洗标/吊牌图"]', timeout=0.3))
    except Exception:
        wash_tag_field_exists = False

    if diaopai_pic and str(record.clazz) != '0' and not wash_tag_field_exists:
        print('处理其他类目吊牌上传...')
        upload_file(main_tab, [diaopai_pic], '吊牌')
        _wait_until(
            lambda: bool(main_tab.ele('吊牌识别成功', timeout=0.05)) or bool(main_tab.ele('吊牌识别失败', timeout=0.05)),
            timeout=3.0,
            interval=0.05,
        )


def _upload_wash_label_or_tag_image(main_tab, diaopai_pic, configured_wash_label_tag_image_path):
    wash_tag_area = None
    try:
        wash_tag_area = main_tab.ele('xpath://div[@attr-field-id="水洗标/吊牌图"]', timeout=0.5)
    except Exception:
        wash_tag_area = None

    if not wash_tag_area:
        return False

    upload_path = ''
    if diaopai_pic and os.path.isfile(diaopai_pic):
        upload_path = diaopai_pic
    elif configured_wash_label_tag_image_path and os.path.isfile(configured_wash_label_tag_image_path):
        upload_path = configured_wash_label_tag_image_path

    if not upload_path:
        print('当前未提供吊牌/水洗标图片，将跳过图片上传并改为依赖面料材质配置')
        return False

    print('开始上传水洗标/吊牌图...')
    upload_file(
        main_tab,
        [upload_path],
        '水洗标/吊牌图',
        target_field_id='水洗标/吊牌图',
        wait_for_finish=False,
    )
    return True


# 与仓库根目录「吊牌.HTML」中抖音商品发布页一致：OCR 未解析材质时的固定提示
_WASH_LABEL_MANUAL_MATERIAL_TIP = '图片中未识别到材质信息，请手动填写'


def _wash_label_manual_material_tip_visible(main_tab):
    try:
        return bool(
            main_tab.ele(
                f'xpath://div[@attr-field-id="水洗标/吊牌图"]'
                f'//*[contains(normalize-space(.),"{_WASH_LABEL_MANUAL_MATERIAL_TIP}")]',
                timeout=0.06,
            )
        )
    except Exception:
        return False


def _wash_label_material_ocr_spinning(main_tab):
    try:
        return bool(
            main_tab.ele(
                'xpath://div[@attr-field-id="水洗标/吊牌图"]'
                '//*[contains(@class,"ecom-g-spin-spinning") or contains(@class,"ant-spin-spinning")]',
                timeout=0.05,
            )
        )
    except Exception:
        return False


def _wash_label_needs_configured_material_fill(main_tab, max_wait_sec=10.0, poll_sec=0.1):
    """
    先等「水洗标/吊牌图」区块内 Ant Spin 结束（表示 OCR 一轮结束），再判断是否出现固定提示。
    成功识别时不会出现该文案，可尽快结束；失败时文案在 attr-field-id 区块内，与吊牌.HTML 结构一致。
    """
    deadline = system_time.time() + max_wait_sec
    consecutive_idle = 0
    while system_time.time() < deadline:
        if _wash_label_manual_material_tip_visible(main_tab):
            return True
        if _wash_label_material_ocr_spinning(main_tab):
            consecutive_idle = 0
        else:
            consecutive_idle += 1
            if consecutive_idle >= 2:
                for _ in range(5):
                    if _wash_label_manual_material_tip_visible(main_tab):
                        return True
                    system_time.sleep(poll_sec)
                return False
        system_time.sleep(poll_sec)
    return _wash_label_manual_material_tip_visible(main_tab)


def _fill_fabric_material_if_wash_label_unrecognized(main_tab, configured_materials):
    if not _wash_label_needs_configured_material_fill(main_tab):
        return
    print('水洗标/吊牌图未识别到材质信息，按自动化配置填写面料材质')
    if not configured_materials:
        raise Exception('吊牌未识别到材质，但未配置面料材质（material_compositions）')
    material_ok = set_material_composition(main_tab, configured_materials)
    if not material_ok:
        raise Exception('面料材质填写失败（吊牌未识别且配置写入失败）')


def _field_exists(main_tab, field_name: str, timeout: float = 0.2) -> bool:
    try:
        return bool(main_tab.ele(f'xpath://div[@attr-field-id="{field_name}"]', timeout=timeout))
    except Exception:
        return False


def _first_existing_field_name(main_tab, field_names, timeout: float = 0.2):
    for field_name in field_names:
        if _field_exists(main_tab, field_name, timeout=timeout):
            return field_name
    return None


def _get_category_field_presence(main_tab):
    """一次读取类目可选字段的存在性，避免五个串行空等。

    这里只判断字段是否存在，不改变旧版对「隐藏但已渲染字段」的接受语义；
    JS 不可用时完整回退到原来的五个 ele 查询，字段别名优先级也不变。
    """
    try:
        state = main_tab.run_js(r'''
const names = arguments[0] || [];
const present = {};
const nodes = document.querySelectorAll('[attr-field-id]');
for (let i = 0; i < nodes.length; i++) {
    const name = nodes[i].getAttribute('attr-field-id') || '';
    if (names.indexOf(name) >= 0) present[name] = true;
}
return present;
''', ['面料材质', '材质', '适用人群', '适用性别', '筒高'])
    except Exception:
        state = None
    if isinstance(state, dict):
        return {
            'material_field_name': next((name for name in ('面料材质', '材质') if state.get(name)), None),
            'has_audience_field': bool(state.get('适用人群')),
            'has_gender_field': bool(state.get('适用性别')),
            'has_sock_height_field': bool(state.get('筒高')),
        }
    return {
        'material_field_name': _first_existing_field_name(main_tab, ('面料材质', '材质')),
        'has_audience_field': _field_exists(main_tab, '适用人群'),
        'has_gender_field': _field_exists(main_tab, '适用性别'),
        'has_sock_height_field': _field_exists(main_tab, '筒高'),
    }


def _fill_category_attributes(main_tab, record, configured_materials, diaopai_pic, wash_label_tag_image_path):
    category_attr_timer_start = system_time.perf_counter()
    _dismiss_interfering_overlays(main_tab, context='fill_category_attributes')
    current_category_text = get_current_category_text(main_tab)
    current_sock_height = infer_sock_height_value(current_category_text, record.clazz)
    is_ship_socks = '船袜' in current_category_text
    field_presence = _get_category_field_presence(main_tab)
    material_field_name = field_presence['material_field_name']
    has_material_field = bool(material_field_name)
    has_audience_field = field_presence['has_audience_field']
    has_gender_field = field_presence['has_gender_field']
    has_sock_height_field = field_presence['has_sock_height_field']
    has_configured_materials = bool(configured_materials)
    has_wash_label_asset = bool(
        (diaopai_pic and os.path.isfile(diaopai_pic))
        or (wash_label_tag_image_path and os.path.isfile(wash_label_tag_image_path))
    )
    print(f'当前页面类目: {current_category_text or "未识别"}')
    if current_sock_height:
        print(f'当前页面筒高目标值: {current_sock_height}')

    if is_ship_socks:
        print('处理船袜类目属性...')
        main_tab.ele('xpath://div[@attr-field-id="主图3:4"]').scroll.to_see()

        if not ensure_no_brand(main_tab):
            raise Exception('品牌未能设置为「无品牌」')
        if has_material_field:
            material_ok = set_material_composition(main_tab, configured_materials, material_field_name)
            timer_record('类目属性阶段', f'{material_field_name}配置写入', 0, system_time.perf_counter() - category_attr_timer_start, material_ok)
            if not material_ok:
                raise Exception(f'{material_field_name}填写失败')
            print(f'船袜类目：已按用户设置写入{material_field_name}')
        else:
            print('页面无“面料材质/材质”字段，跳过材质配置')

    elif has_wash_label_asset:
        print('处理其他类目属性（有可用吊牌/水洗标图）...')
        step_timer_start = system_time.perf_counter()
        main_tab.ele('xpath://div[@attr-field-id="主图3:4"]').scroll.to_see()

        if not has_configured_materials:
            ss = main_tab.eles('xpath://div[@attr-field-id="面料材质"]//span[contains(@class,"styles_del__")]', timeout=0.5)
            for del_btn in ss:
                before_count = len(main_tab.eles('xpath://div[@attr-field-id="面料材质"]//span[contains(@class,"styles_del__")]', timeout=0.05) or [])
                del_btn.click(by_js=True)
                _wait_until(
                    lambda: len(main_tab.eles('xpath://div[@attr-field-id="面料材质"]//span[contains(@class,"styles_del__")]', timeout=0.03) or []) < before_count,
                    timeout=0.5,
                    interval=0.03,
                )

        if not ensure_no_brand(main_tab):
            raise Exception('品牌未能设置为「无品牌」')
        if has_audience_field:
            select_text(main_tab, '适用人群', '成人')
        if has_gender_field:
            select_text(main_tab, '适用性别', get_sex(record.title))
        if current_sock_height and has_sock_height_field:
            select_text(main_tab, '筒高', current_sock_height)
        timer_record('类目属性阶段', '基础属性', 0, system_time.perf_counter() - step_timer_start, True)

    else:
        print('处理其他类目属性（无吊牌/水洗标图，改走面料材质配置）...')
        main_tab.ele('xpath://div[@attr-field-id="主图3:4"]').scroll.to_see()
        step_timer_start = system_time.perf_counter()
        material_ok = True
        if has_material_field:
            material_ok = set_material_composition(main_tab, configured_materials, material_field_name)
            if not material_ok:
                raise Exception(f'{material_field_name}填写失败')
        else:
            print('页面无“面料材质/材质”字段，跳过材质配置')
        timer_record('类目属性阶段', f'{material_field_name or "材质"}配置写入', 0, system_time.perf_counter() - step_timer_start, material_ok)
        step_timer_start = system_time.perf_counter()
        if not ensure_no_brand(main_tab):
            raise Exception('品牌未能设置为「无品牌」')
        if has_audience_field:
            select_text(main_tab, '适用人群', '成人')
        if has_gender_field:
            select_text(main_tab, '适用性别', get_sex(record.title))
        if current_sock_height and has_sock_height_field:
            select_text(main_tab, '筒高', current_sock_height)
        timer_record('类目属性阶段', '基础属性', 0, system_time.perf_counter() - step_timer_start, True)

    _dismiss_interfering_overlays(main_tab, context='before_wash_label_upload')
    step_timer_start = system_time.perf_counter()
    uploaded_wash_label = _upload_wash_label_or_tag_image(main_tab, diaopai_pic, wash_label_tag_image_path)
    timer_record('类目属性阶段', '水洗标吊牌上传触发', 0, system_time.perf_counter() - step_timer_start, True)
    if uploaded_wash_label and has_configured_materials:
        step_timer_start = system_time.perf_counter()
        material_ok = set_material_composition(main_tab, configured_materials, material_field_name)
        timer_record('类目属性阶段', f'{material_field_name or "材质"}配置写入', 0, system_time.perf_counter() - step_timer_start, material_ok)
        if not material_ok:
            raise Exception(f'{material_field_name or "材质"}填写失败（配置写入失败）')
        print(f'已按配置写入{material_field_name or "材质"}，跳过水洗标/吊牌图 OCR 等待')
    elif uploaded_wash_label:
        step_timer_start = system_time.perf_counter()
        _fill_fabric_material_if_wash_label_unrecognized(main_tab, configured_materials)
        timer_record('类目属性阶段', '水洗标OCR判断', 0, system_time.perf_counter() - step_timer_start, True)
    timer_record('类目属性阶段', '总计', 0, system_time.perf_counter() - category_attr_timer_start, True)


def _find_ai_main_image_panel(main_tab):
    try:
        return main_tab.ele(
            'xpath://div[text()="AI智能做主图"]/ancestor::div[contains(@class,"styles_panel__") or contains(@class,"styles_wrapper__")][1]',
            timeout=0.1,
        )
    except Exception:
        return None


def _find_ai_main_image_action(panel, action_text):
    if not panel:
        return None
    selectors = (
        f'xpath:.//button[.//span[normalize-space(text())="{action_text}"]]',
        f'xpath:.//span[normalize-space(text())="{action_text}"]/ancestor::button[1]',
        f'xpath:.//*[normalize-space(text())="{action_text}"]/ancestor::button[1]',
    )
    for selector in selectors:
        try:
            button = panel.ele(selector, timeout=0.05)
        except Exception:
            button = None
        if not button:
            continue
        try:
            if button.states.is_displayed:
                return button
        except Exception:
            continue
    return None


def _drive_ai_main_image_actions(main_tab):
    """
    详情图上传前可能出现「AI智能做主图」面板。
    这里不再使用固定 3s/0.5s 停顿，而是按面板动作是否真正切换来推进。
    """
    panel = _find_ai_main_image_panel(main_tab)
    if not panel:
        return False

    apply_btn = _find_ai_main_image_action(panel, '应用')
    if apply_btn:
        try:
            apply_btn.click(by_js=True)
        except Exception:
            try:
                apply_btn.click()
            except Exception:
                pass
        _wait_until(
            lambda: bool(_find_ai_main_image_action(_find_ai_main_image_panel(main_tab), '上传'))
            or not _find_ai_main_image_panel(main_tab)
            or _is_upload_busy(main_tab),
            timeout=1.2,
            interval=0.05,
        )

    panel = _find_ai_main_image_panel(main_tab)
    upload_btn = _find_ai_main_image_action(panel, '上传')
    if not upload_btn:
        return False

    try:
        upload_btn.click(by_js=True)
    except Exception:
        try:
            upload_btn.click()
        except Exception:
            return False

    _wait_until(
        lambda: not _find_ai_main_image_panel(main_tab) or _is_upload_busy(main_tab),
        timeout=1.0,
        interval=0.05,
    )
    return True


def _wait_for_detail_upload_area_ready(main_tab, timeout=1.2, interval=0.05):
    detail_selectors = (
        'xpath://div[@attr-field-id="商品详情"]//label[.//input[@type="file"]]',
        'xpath://div[@attr-field-id="商品详情"]//div[contains(@class,"material-upload-button")]',
        'xpath://div[@attr-field-id="商品详情"]//*[contains(normalize-space(.),"上传图片")]',
    )
    return _wait_until(
        lambda: any(main_tab.ele(selector, timeout=0.05) for selector in detail_selectors),
        timeout=timeout,
        interval=interval,
    )


def _normalize_upload_numeric_text(value):
    text = '' if value is None else str(value).strip()
    if not text:
        return ''
    cleaned = text.replace('￥', '').replace(',', '').strip()
    try:
        number = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return cleaned
    normalized = format(number.normalize(), 'f')
    if '.' in normalized:
        normalized = normalized.rstrip('0').rstrip('.')
    return normalized or '0'


def _upload_media_assets(main_tab, sub_pic_list, my_video, white_pic, detail_pic_list):
    media_timer_start = system_time.perf_counter()
    _dismiss_interfering_overlays(main_tab, context='upload_media_assets')

    step_timer_start = system_time.perf_counter()
    if len(sub_pic_list) > 0:
        _ensure_section_ready(main_tab, '主图3:4', timeout=12.0)
        upload_file(
            main_tab,
            sub_pic_list,
            '主图',
            error_size='长宽比需为3:4',
            target_field_id='主图3:4',
            wait_for_finish=False,
        )
    else:
        print("跳过3:4主图上传，尝试自动点击'从1:1主图智能裁剪'按钮")
        try:
            if click_field_action(main_tab, '主图3:4', '从1:1主图智能裁剪') or click_field_action(main_tab, '主图3:4', '从1:1主图一键填入'):
                print('成功触发3:4主图智能裁剪')
            else:
                print('未找到3:4主图智能裁剪按钮')
        except Exception as exc:
            print(f"自动点击3:4主图智能裁剪按钮失败: {str(exc)}")
            print('请手动点击3:4主图智能裁剪按钮')
    timer_record('媒体上传阶段', '3比4主图', 0, system_time.perf_counter() - step_timer_start, True)

    main_tab.ele('xpath://div[@attr-field-id="主图视频"]').scroll.to_see()
    _dismiss_interfering_overlays(main_tab, context='before_video_upload')

    step_timer_start = system_time.perf_counter()
    if my_video:
        print('开始上传主图视频...')
        upload_file(
            main_tab,
            [my_video],
            '主图视频',
            target_field_id='主图视频',
            wait_for_finish=False,
        )
    else:
        print('没有本地主图视频，尝试在主图视频区域内点击一键生成')
        if click_field_action(main_tab, '主图视频', '一键生成'):
            _wait_until(
                lambda: _is_upload_busy(main_tab) or bool(_find_ai_material_tool_panel(main_tab, timeout=0.05)),
                timeout=0.5,
                interval=0.03,
            )
        else:
            print('未找到可用的一键生成按钮，或按钮当前不可点击')
    timer_record('媒体上传阶段', '主图视频', 0, system_time.perf_counter() - step_timer_start, True)

    step_timer_start = system_time.perf_counter()
    upload_file(
        main_tab,
        [white_pic],
        '白底图',
        target_field_id='白底图',
        wait_for_finish=False,
    )
    white_prompt_timer_start = system_time.perf_counter()
    try:
        handle_white_bg_post_upload_prompts(main_tab, timeout=2.5)
    except Exception as exc:
        print(f'处理白底图上传后AI素材工具失败: {exc}')
    timer_record('媒体上传阶段', '白底图AI面板处理', 0, system_time.perf_counter() - white_prompt_timer_start, True)

    white_settle_timer_start = system_time.perf_counter()
    # 这里原本是 wait_white_bg_processing_complete(timeout=3.0, ...)，实测中位 4.04s、
    # 33/64 次跑满 4.00~4.25s（已超过它自己的 3.0s 预算，说明每轮仍在走慢回退路径），
    # 而它的返回值只用于下面这一句 print —— 纯等待、零作用，却占掉整条流程的 ~4 秒。
    # 改成一次 _white_bg_state 探测（单次 CDP 往返）：可观测性保留，不再阻塞流程。
    try:
        white_bg_state = _white_bg_state(main_tab)
    except Exception:
        white_bg_state = None
    if white_bg_state and white_bg_state.get('blocking'):
        print('白底图已触发上传，但平台侧提示存在问题（如「非白底」），按非阻塞流程继续后续发布步骤')
    elif white_bg_state and white_bg_state.get('processing'):
        print('白底图平台侧仍在处理中，按非阻塞流程继续后续发布步骤')
    timer_record('媒体上传阶段', '白底图状态短确认', 0, system_time.perf_counter() - white_settle_timer_start, True)
    try:
        close_ai_material_tool_panel(main_tab, timeout=0.2)
    except Exception:
        pass
    timer_record('媒体上传阶段', '白底图与AI收尾', 0, system_time.perf_counter() - step_timer_start, True)

    _dismiss_interfering_overlays(main_tab, context='before_detail_upload')
    step_timer_start = system_time.perf_counter()
    try:
        _drive_ai_main_image_actions(main_tab)
    except Exception:
        pass
    try:
        detail_block = main_tab.ele('xpath://div[@attr-field-id="商品详情"]', timeout=2)
        if detail_block:
            detail_block.scroll.to_see()
            _wait_for_detail_upload_area_ready(main_tab, timeout=0.6, interval=0.03)
    except Exception:
        pass
    upload_file(main_tab, detail_pic_list, '图片', extra=True, target_field_id='商品详情')
    timer_record('媒体上传阶段', '详情图', 0, system_time.perf_counter() - step_timer_start, True)
    timer_record('媒体上传阶段', '总计', 0, system_time.perf_counter() - media_timer_start, True)


def _find_price_stock_root(main_tab, timeout=0.2):
    selectors = [
        'xpath://div[@attr-field-id="价格与库存"]',
        'xpath://div[@id="goodsEditScrollContainer-价格库存"]',
        'xpath://div[@attr-field-id="售卖价"]/ancestor::div[@id="goodsEditScrollContainer-价格库存"][1]',
        'xpath://div[@attr-field-id="订单库存计数"]/ancestor::div[@id="goodsEditScrollContainer-价格库存"][1]',
    ]
    return _find_first_visible_element(main_tab, selectors, timeout=timeout)


def _scroll_to_price_stock_area(main_tab, timeout=2.0):
    price_stock_root = _find_price_stock_root(main_tab, timeout=0.1)
    if price_stock_root:
        try:
            price_stock_root.scroll.to_see()
        except Exception:
            try:
                price_stock_root.scroll.to_center()
            except Exception:
                pass
        return price_stock_root

    legacy_title = None
    try:
        legacy_title = main_tab.ele('xpath://span[text()="价格与库存"]', timeout=0.1)
    except Exception:
        legacy_title = None
    if legacy_title:
        try:
            legacy_title.scroll.to_see()
        except Exception:
            pass

    if _wait_until(lambda: bool(_find_price_stock_root(main_tab, timeout=0.05)), timeout=timeout, interval=0.05):
        return _find_price_stock_root(main_tab, timeout=0.1)
    raise Exception('未找到价格库存区域')


def _find_manual_sku_mode_button(main_tab):
    selectors = [
        'xpath://button[.//*[contains(normalize-space(.),"切换手动填写")] or contains(normalize-space(.),"切换手动填写")]',
        'xpath://*[contains(normalize-space(.),"切换手动填写")]/ancestor::button[1]',
    ]
    return _find_first_visible_element(main_tab, selectors, timeout=0.1)


def _ensure_manual_sku_entry_mode(main_tab):
    if _sku_color_type_exists(main_tab):
        return

    _scroll_to_price_stock_area(main_tab)
    switch_button = _find_manual_sku_mode_button(main_tab)
    if switch_button:
        print('切换规格设置 -> 手动填写')
        if not _click_element_safely(switch_button):
            raise Exception('SKU手动填写按钮点击失败')
        _wait_until(
            lambda: _sku_color_type_exists(main_tab) or bool(_find_add_spec_type_button(_find_goods_spec_field(main_tab))),
            timeout=2.0,
            interval=0.05,
        )

    if _find_manual_sku_mode_button(main_tab) and not _sku_color_type_exists(main_tab):
        raise Exception('SKU手动填写模式未成功展开')


_SKU_DIMENSIONS_TO_KEEP = ('颜色分类', '码数')


def _sku_dimension_names(main_tab):
    """读取当前实际可见的规格维度，忽略旧版/隐藏节点。"""
    try:
        names = main_tab.run_js(r'''
return Array.from(document.querySelectorAll('div[id^="skuValue-"]'))
    .filter(node => node.offsetParent || node.getClientRects().length)
    .map(node => node.id.slice('skuValue-'.length))
    .filter(Boolean);
''')
    except Exception:
        return []
    return list(dict.fromkeys(names)) if isinstance(names, list) else []


def _sku_dimension_exists(main_tab, axis_name):
    try:
        node = main_tab.ele(
            f'xpath://div[@id={_xpath_literal("skuValue-" + axis_name)}]', timeout=0.05,
        )
        return bool(node and node.states.is_displayed)
    except Exception:
        return False


def _confirm_sku_dimension_delete(main_tab):
    modal = (
        'xpath://div[(contains(@class,"ecom-g-modal") or @role="dialog")'
        ' and .//*[contains(normalize-space(.),"删除") and contains(normalize-space(.),"规格")]]'
    )
    button = _find_first_visible_element(
        main_tab,
        [modal + '//button[contains(normalize-space(.),"确定") or contains(normalize-space(.),"确认") or normalize-space(.)="删除"]'],
        timeout=0.05,
    )
    return _click_element_safely(button) if button else False


def _delete_sku_dimension(main_tab, axis_name):
    container = (
        f'xpath://div[@id={_xpath_literal("skuValue-" + axis_name)}]'
        '/ancestor::div[contains(@class,"style_contentBox__")][1]'
    )
    delete_button = _find_first_visible_element(
        main_tab,
        [
            container + '//div[contains(@class,"style_skuNameBox__")]'
            '//div[contains(@class,"style_specOperations__")]'
            '//div[contains(@class,"style_item__")][.//*[name()="use" and @href="#icon-shanchu"]]',
            container + '//div[contains(@class,"style_skuNameBox__")]'
            '//div[contains(@class,"style_specOperations__")]/div[contains(@class,"style_item__")][last()]',
        ],
        timeout=0.08,
    )
    if not delete_button:
        raise Exception(f'无法找到规格维度「{axis_name}」的删除按钮，已停止以避免保留AI多余规格')
    if not _click_element_safely(delete_button):
        raise Exception(f'规格维度「{axis_name}」删除按钮点击失败')
    _confirm_sku_dimension_delete(main_tab)
    if not _wait_until(
        lambda: not _sku_dimension_exists(main_tab, axis_name),
        timeout=1.2,
        interval=0.05,
    ):
        raise Exception(f'规格维度「{axis_name}」删除后仍未消失，已停止以避免SKU结构冲突')


def _reset_unexpected_sku_dimensions(main_tab):
    """只保留颜色和码数；AI/历史产生的其它维度必须真实删除并读回。"""
    removed = []
    for axis_name in _sku_dimension_names(main_tab):
        if axis_name in _SKU_DIMENSIONS_TO_KEEP:
            continue
        _delete_sku_dimension(main_tab, axis_name)
        removed.append(axis_name)
    return removed


def _visible_sku_value_delete_buttons(main_tab, axis_name):
    base = f'xpath://div[@id={_xpath_literal("skuValue-" + axis_name)}]'
    selectors = [
        base + '//span[@data-kora="删除规格值"]',
        base + '//*[contains(@class,"cascader-multiple-selection-item-remove")'
        ' or contains(@class,"select-selection-item-remove") or contains(@class,"ecom-g-select-clear")]',
    ]
    buttons = []
    for selector in selectors:
        try:
            candidates = main_tab.eles(selector, timeout=0.06) or []
        except Exception:
            candidates = []
        for button in candidates:
            try:
                if button and button.states.is_displayed:
                    buttons.append(button)
            except Exception:
                continue
    return buttons


def _sku_axis_has_selected_values(main_tab, axis_name):
    try:
        return bool(main_tab.run_js(r'''
const root = document.getElementById(arguments[0]);
return !!(root && root.querySelector(
    '.ecom-g-select-selection-item[title], .ecom-g-cascader-multiple-selection-item, .aurora-select-selection-item[title]'
));
''', 'skuValue-' + axis_name))
    except Exception:
        return False


def _clear_sku_axis_values(main_tab, axis_name):
    """清空指定维度的已有值；有值但无法删除时必须停止，不能静默保留。"""
    for _ in range(128):
        buttons = _visible_sku_value_delete_buttons(main_tab, axis_name)
        if not buttons:
            if _sku_axis_has_selected_values(main_tab, axis_name):
                raise Exception(f'规格维度「{axis_name}」存在无法清理的AI/历史规格值')
            return
        before_count = len(buttons)
        try:
            buttons[-1].click(by_js=True)
        except Exception:
            pass
        decreased = _wait_until(
            lambda: len(_visible_sku_value_delete_buttons(main_tab, axis_name)) < before_count,
            timeout=0.8,
            interval=0.04,
        )
        if not decreased:
            try:
                buttons[-1].click()
            except Exception:
                pass
        if not decreased and not _wait_until(
            lambda: len(_visible_sku_value_delete_buttons(main_tab, axis_name)) < before_count,
            timeout=0.8,
            interval=0.04,
        ):
            raise Exception(f'规格维度「{axis_name}」的AI/历史规格值删除失败')
    raise Exception(f'规格维度「{axis_name}」清理次数异常，已停止')


def _configure_sku_entries(main_tab, sku_list, remark, record=None):
    _dismiss_interfering_overlays(main_tab, context='configure_sku_entries')
    _scroll_to_price_stock_area(main_tab)

    print('选择发货时间 -> 48小时')
    ship_time = main_tab.ele('xpath://span[text()="48小时"]', timeout=1)
    if not ship_time:
        raise Exception('未找到发货时间选项：48小时')
    ship_time.click()

    _ensure_manual_sku_entry_mode(main_tab)
    removed_dimensions = _reset_unexpected_sku_dimensions(main_tab)
    if removed_dimensions:
        print('已清理AI/历史多余规格维度：' + '、'.join(removed_dimensions))
    _ensure_color_sku_type(main_tab)
    _clear_sku_axis_values(main_tab, '颜色分类')
    _clear_sku_axis_values(main_tab, '码数')

    # 勾选添加规格图片（SKU图片上传必需）
    print('勾选添加规格图片')
    add_spec_image = main_tab.ele('xpath://span[text()="添加规格图"]', timeout=1)
    if add_spec_image:
        add_spec_image.click(by_js=True)
    else:
        print('未找到添加规格图开关，跳过')

    for i, sku in enumerate(sku_list):
        set_sku_info(main_tab, i, sku, remark)
        if i < len(sku_list) - 1:
            sku_gap_start = system_time.perf_counter()
            while system_time.perf_counter() - sku_gap_start < 0.5:
                if not _is_upload_busy(main_tab):
                    break
                system_time.sleep(0.05)  # SKU间暂停，让页面完成图片处理


def _sku_color_type_exists(main_tab) -> bool:
    try:
        color_block = main_tab.ele('xpath://div[@id="skuValue-颜色分类"]', timeout=0.2)
        return bool(color_block and color_block.states.is_displayed)
    except Exception:
        return False


def _find_goods_spec_field(main_tab):
    selectors = [
        'xpath://div[@attr-field-id="商品规格"]',
        'xpath://div[@id="goodsEditScrollContainer-价格库存"]',
        'xpath://div[@attr-field-id="售卖价"]/ancestor::div[@id="goodsEditScrollContainer-价格库存"][1]',
    ]
    return _find_first_visible_element(main_tab, selectors, timeout=0.2)


def _find_add_spec_type_button(spec_field):
    if not spec_field:
        return None
    try:
        buttons = spec_field.eles(
            'xpath:.//button[.//span[contains(normalize-space(.),"添加规格类型")]]',
            timeout=0.2,
        ) or []
    except Exception:
        buttons = []
    for button in buttons:
        try:
            if button and button.states.is_displayed and button.states.is_enabled:
                return button
        except Exception:
            continue
    return None


def _find_pending_spec_type_selector(spec_field):
    if not spec_field:
        return None
    selectors = [
        'xpath:.//div[contains(@class,"ecom-g-select") and .//span[contains(normalize-space(.),"请选择规格类型")]]',
        'xpath:.//*[contains(normalize-space(.),"请选择规格类型")]/ancestor::div[contains(@class,"ecom-g-select")][1]',
    ]
    return _find_first_visible_element(spec_field, selectors, timeout=0.1)


def _find_visible_spec_type_option(main_tab, text):
    literal = _xpath_literal(text)
    selectors = [
        f'xpath://div[contains(@class,"ecom-g-select-dropdown") and not(contains(@class,"hidden"))]//*[normalize-space(.)={literal}]',
        f'xpath://div[contains(@class,"ecom-g-select-dropdown") and not(contains(@class,"hidden"))]//*[contains(normalize-space(.), {literal})]',
    ]
    return _find_first_visible_element(main_tab, selectors, timeout=0.08)


def _find_create_spec_type_entry(main_tab):
    selectors = [
        'xpath://div[contains(@class,"ecom-g-select-dropdown") and not(contains(@class,"hidden"))]//*[contains(@class,"styles_newSKU") and contains(normalize-space(.),"创建类型")]',
        'xpath://div[contains(@class,"ecom-g-select-dropdown") and not(contains(@class,"hidden"))]//*[contains(normalize-space(.),"创建类型")]',
    ]
    return _find_first_visible_element(main_tab, selectors, timeout=0.08)


def _find_custom_spec_type_input(main_tab):
    selectors = [
        'xpath://input[@placeholder="请输入规格类型"]',
        'xpath://div[contains(@class,"ecom-g-select-dropdown") and not(contains(@class,"hidden"))]//input[contains(@class,"styles_skuNameInput")]',
    ]
    return _find_first_visible_element(main_tab, selectors, timeout=0.08)


def _press_enter(main_tab):
    main_tab.run_cdp('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', windowsVirtualKeyCode=13)
    main_tab.run_cdp('Input.dispatchKeyEvent', type='keyUp', key='Enter', code='Enter', windowsVirtualKeyCode=13)


def _ensure_color_sku_type(main_tab):
    if _sku_color_type_exists(main_tab):
        return

    print('当前类目未生成颜色分类规格，创建颜色分类规格类型')
    spec_field = _find_goods_spec_field(main_tab)
    if not spec_field:
        raise Exception('未找到商品规格区域')

    add_type_button = _find_add_spec_type_button(spec_field)
    if not add_type_button:
        raise Exception('未找到添加规格类型按钮')
    add_type_button.scroll.to_center()
    add_type_button.click(by_js=True)

    if not _wait_until(lambda: bool(_find_pending_spec_type_selector(spec_field)), timeout=1.2, interval=0.04):
        raise Exception('添加规格类型后未出现规格类型选择器')

    spec_type_selector = _find_pending_spec_type_selector(spec_field)
    if not spec_type_selector or not _click_element_safely(spec_type_selector):
        raise Exception('规格类型选择器点击失败')

    if not _wait_until(
        lambda: bool(_find_visible_spec_type_option(main_tab, '颜色分类')) or bool(_find_create_spec_type_entry(main_tab)),
        timeout=1.2,
        interval=0.04,
    ):
        raise Exception('规格类型下拉未出现颜色分类或创建类型入口')

    color_option = _find_visible_spec_type_option(main_tab, '颜色分类')
    if color_option:
        if not _click_element_safely(color_option):
            raise Exception('颜色分类规格类型点击失败')
    else:
        create_entry = _find_create_spec_type_entry(main_tab)
        if not create_entry or not _click_element_safely(create_entry):
            raise Exception('创建规格类型入口点击失败')
        if not _wait_until(lambda: bool(_find_custom_spec_type_input(main_tab)), timeout=1.0, interval=0.04):
            raise Exception('未出现自定义规格类型输入框')
        custom_input = _find_custom_spec_type_input(main_tab)
        custom_input.click(by_js=True)
        custom_input.input('颜色分类', clear=True)
        if not _wait_until(lambda: custom_input.attr('value') == '颜色分类', timeout=0.5, interval=0.03):
            raise Exception('颜色分类规格类型未成功写入')
        _press_enter(main_tab)

    if not _wait_until(lambda: _sku_color_type_exists(main_tab), timeout=2.0, interval=0.05):
        raise Exception('颜色分类规格类型未创建成功')


def _sku_size_has_uniform(main_tab) -> bool:
    try:
        size_block = main_tab.ele('xpath://div[@id="skuValue-码数"]', timeout=0.2)
    except Exception:
        size_block = None
    if not size_block:
        return False
    selected_size_selectors = [
        'xpath:.//*[contains(@class,"ecom-g-cascader-picker") and contains(normalize-space(.),"均码")]',
        'xpath:.//*[contains(@class,"ecom-g-cascader-picker-label") and normalize-space(.)="均码"]',
        'xpath:.//*[contains(@class,"ecom-g-select-selection-item") and normalize-space(.)="均码"]',
        'xpath:.//*[contains(@class,"ecom-g-cascader-multiple-selection-item") and .//*[normalize-space(.)="均码"]]',
    ]
    for selector in selected_size_selectors:
        try:
            selected = size_block.ele(selector, timeout=0.05)
            if selected and selected.states.is_displayed:
                return True
        except Exception:
            continue
    try:
        price_stock_root = _find_price_stock_root(main_tab, timeout=0.05)
        if not price_stock_root:
            return False
        return bool(
            price_stock_root.ele(
                'xpath:.//td[contains(@class,"attr-column-field_spec_1")]//*[normalize-space(.)="均码"]',
                timeout=0.05,
            )
        )
    except Exception:
        return False


def _find_size_value_picker(main_tab):
    selectors = [
        'xpath://div[@id="skuValue-码数"]//div[contains(@class,"style_forCreate__")]//span[contains(@class,"ecom-g-cascader-multiple-placeholder") and contains(normalize-space(.),"码数")]/ancestor::div[contains(@class,"ecom-g-cascader-picker")][1]',
        'xpath://div[@id="skuValue-码数"]//div[contains(@class,"style_forCreate__")]//*[contains(@class,"ecom-g-cascader-picker")][1]',
        'xpath://div[@id="skuValue-码数"]//input',
    ]
    for selector in selectors:
        try:
            element = main_tab.ele(selector, timeout=0.3)
            if element and element.states.is_displayed:
                return element
        except Exception:
            continue
    return None


def _find_uniform_size_group(main_tab):
    return _find_first_visible_element(
        main_tab,
        [
            'xpath://div[contains(@class,"ecom-g-cascader-menus") and not(contains(@class,"hidden"))]//li[@title="均码" and contains(@class,"ecom-g-cascader-menu-item-expand")]',
            'xpath://div[contains(@class,"ecom-g-cascader-menus") and not(contains(@class,"hidden"))]//li[contains(@class,"ecom-g-cascader-menu-item-expand") and .//*[normalize-space(.)="均码"]]',
        ],
        timeout=0.05,
    )


def _find_uniform_size_leaf(main_tab):
    return _find_first_visible_element(
        main_tab,
        [
            'xpath://div[contains(@class,"ecom-g-cascader-menus") and not(contains(@class,"hidden"))]//li[@title="均码" and .//label[contains(@class,"ecom-g-cascader-menu-item-checkbox")]]',
            'xpath://div[contains(@class,"ecom-g-cascader-menus") and not(contains(@class,"hidden"))]//li[.//label[contains(@class,"ecom-g-cascader-menu-item-checkbox")] and .//*[normalize-space(.)="均码"]]',
        ],
        timeout=0.05,
    )


def _size_menu_candidates_text(main_tab) -> str:
    """诊断用：列出码数级联菜单里当前可见的候选项文案。

    用来把「菜单没展开」和「菜单开了但没有均码分组」区分开 ——
    旧实现两种情况报同一句话，现场无法判断，只能靠人工复现。
    """
    try:
        items = main_tab.eles(
            'xpath://div[contains(@class,"ecom-g-cascader-menus") and not(contains(@class,"hidden"))]//li',
            timeout=0.1,
        ) or []
    except Exception:
        return '(读取失败)'
    texts = []
    for item in items:
        try:
            text = ' '.join((item.text or '').split())
        except Exception:
            continue
        if text and text not in texts:
            texts.append(text)
    return '、'.join(texts[:12]) or '(空)'


def _uniform_size_leaf_checked(main_tab) -> bool:
    leaf = _find_uniform_size_leaf(main_tab)
    if not leaf:
        return False
    try:
        return bool(
            leaf.ele(
                'xpath:.//*[contains(@class,"ecom-g-checkbox-checked") or @checked or @aria-checked="true"]',
                timeout=0.05,
            )
        )
    except Exception:
        return False


def _find_size_confirm_button(main_tab, require_enabled=False):
    buttons = main_tab.eles(
        'xpath://div[contains(@class,"ecom-g-cascader-menus") and not(contains(@class,"hidden"))]//button[.//span[contains(normalize-space(.),"确定")] or contains(normalize-space(.),"确定")]',
        timeout=0.1,
    ) or []
    for button in buttons:
        try:
            if not button.states.is_displayed:
                continue
            if require_enabled and not button.states.is_enabled:
                continue
            return button
        except Exception:
            continue
    return None


def _configure_sku_structure(main_tab):
    _dismiss_interfering_overlays(main_tab, context='configure_sku_structure')
    if _sku_size_has_uniform(main_tab):
        return

    print('选择均码')
    size_picker = _find_size_value_picker(main_tab)
    if not size_picker:
        print('当前类目没有码数规格轴，跳过均码选择')
        timer_record('SKU阶段', '码数规格轴不存在跳过', 0, 0, True)
        return
    size_picker.scroll.to_center()

    def _size_menu_opened() -> bool:
        """级联菜单是否真的展开了。

        只要菜单里有任意可选项或确定按钮即算展开 —— 用它把
        「点击没生效」和「菜单开了但没有均码分组」区分开。
        """
        return bool(_find_uniform_size_group(main_tab)) or bool(
            _find_size_confirm_button(main_tab)
        )

    # 点击方式逐个尝试并即时确认：cascader 只认真实 mousedown，JS 的 element.click()
    # 打不开；原生 click 也可能落在被遮挡的位置。旧实现只点一次、且失败时把
    # 「菜单没展开」报成「未找到码数均码分组选项」，现场无法区分（实测 5 次失败里 4 次）。
    for attempt, clicker in enumerate(
        (
            lambda: size_picker.click(),
            lambda: size_picker.click(by_js=True),
            lambda: _click_element_safely(size_picker),
        ),
        start=1,
    ):
        try:
            clicker()
        except Exception as exc:
            print(f'  码数下拉第{attempt}次点击抛错: {exc}')
            continue
        if _wait_until(_size_menu_opened, timeout=1.2, interval=0.04):
            break
        print(f'  码数下拉第{attempt}次点击后菜单未展开，换一种点击方式重试')
    else:
        raise Exception(
            '码数下拉未能展开（已依次尝试 原生点击 / JS 点击 / 安全点击）：'
            '无法确认「均码」是否可选，请检查页面是否被弹窗或浮层遮挡'
        )

    if not _wait_until(
        lambda: bool(_find_uniform_size_group(main_tab)),
        timeout=3.0,
        interval=0.04,
    ):
        raise Exception(
            '码数下拉已展开，但未找到「均码」分组选项'
            f'｜下拉当前可见候选项：{_size_menu_candidates_text(main_tab)}'
        )

    uniform_group = _find_uniform_size_group(main_tab)
    if not uniform_group or not _click_element_safely(uniform_group):
        raise Exception('码数均码分组点击失败')
    if not _wait_until(lambda: bool(_find_uniform_size_leaf(main_tab)), timeout=2.0, interval=0.04):
        raise Exception(
            '码数下拉已展开且找到了「均码」分组，但点击后未渲染出叶子选项'
            f'｜下拉当前可见候选项：{_size_menu_candidates_text(main_tab)}'
        )

    uniform_leaf = _find_uniform_size_leaf(main_tab)
    leaf_checkbox = None
    try:
        leaf_checkbox = uniform_leaf.ele('xpath:.//label[contains(@class,"ecom-g-cascader-menu-item-checkbox")]', timeout=0.05)
    except Exception:
        pass
    if not _click_element_safely(leaf_checkbox or uniform_leaf):
        raise Exception('码数均码叶子选项点击失败')
    if not _wait_until(
        lambda: _uniform_size_leaf_checked(main_tab) or bool(_find_size_confirm_button(main_tab, require_enabled=True)),
        timeout=2.0,
        interval=0.04,
    ):
        raise Exception('码数「均码」叶子选项已找到但勾选未生效（复选框未选中，且确定按钮不可用）')

    confirm_button = _find_size_confirm_button(main_tab, require_enabled=True)
    if not confirm_button:
        raise Exception('码数确认按钮不可用')
    confirm_button.click()

    if not _wait_until(lambda: _sku_size_has_uniform(main_tab), timeout=2.5, interval=0.05):
        raise Exception('码数未成功选择为均码')
    _dismiss_interfering_overlays(main_tab, context='configure_sku_structure')


# 价格库存表整表扫描：一次 CDP 往返取回所有已渲染行的 key、规格文本与当前值，
# 替代「逐行 × 多次属性读取」的 DrissionPage 调用，显著降低填写过程的卡顿。
_PRICE_STOCK_ROW_SCAN_JS = r'''
const rows = this.querySelectorAll('tr[class*="ecom-g-table-row"]');
const out = [];
for (let i = 0; i < rows.length; i++) {
    const tr = rows[i];
    if (!tr.offsetParent && tr.getClientRects().length === 0) continue;
    const specs = tr.querySelectorAll('td[class*="attr-column-field_spec_"]');
    const texts = [];
    for (let j = 0; j < specs.length; j++) {
        const text = (specs[j].innerText || specs[j].textContent || '').replace(/\s+/g, ' ').trim();
        if (text) texts.push(text);
    }
    const priceInput = tr.querySelector('td[class*="attr-column-field_price"] input');
    const stockInput = tr.querySelector('td[class*="attr-column-field_stock_info"] input');
    out.push({
        key: tr.getAttribute('data-row-key') || '',
        texts: texts,
        price: priceInput ? (priceInput.value || '') : null,
        stock: stockInput ? (stockInput.value || '') : null
    });
}
return out;
'''


def _fill_price_stock_and_delivery(main_tab, record, sku_list, shipping_template_name):
    print('设置价格和库存...')
    _dismiss_interfering_overlays(main_tab, context='fill_price_and_stock')
    price_stock_root = _find_price_stock_root(main_tab)
    if not price_stock_root:
        raise Exception('未找到价格与库存区域')

    # 表格无法继续滚动时，允许原地重扫的次数。
    # 每次重扫都会按 data-row-key 重新解析行句柄，是句柄被重渲染打掉后的唯一恢复手段，
    # 代价只有几次 CDP 往返，所以给足机会；同时用次数上限防止真正的死循环。
    _stall_retry_limit = 3

    def _norm_text(value):
        return ' '.join(str(value or '').split()).strip()

    def _strip_tail_parentheses(value):
        text = _norm_text(value)
        while text:
            updated = re.sub(r'\s*[（(][^（）()]*[）)]\s*$', '', text).strip()
            if updated == text:
                break
            text = updated
        return text

    # SKU 名的分隔符不统一：采集侧产出「颜色 / 尺码」，文件夹导入会把文件名里的
    # "-" 换成 "+"（见 _derive_sku_name），多规格还可能被直接连写。
    # 只认 " / " 会让 "S2636组合E+均码" 这类名字整串被当成颜色值，永远匹配不上页面行。
    _sku_separator_re = re.compile(r'\s*/\s*|\s*\+\s*|\s*、\s*|\s*\|\s*')

    def _split_sku_name(value):
        text = _norm_text(value)
        parts = [part.strip() for part in _sku_separator_re.split(text) if part.strip()]
        if len(parts) >= 2:
            return ' / '.join(parts[:-1]).strip(), _strip_tail_parentheses(parts[-1])
        return text, ''

    def _identity_from_texts(spec_texts):
        name_text = spec_texts[0] if spec_texts else ''
        size_text = _strip_tail_parentheses(spec_texts[1]) if len(spec_texts) > 1 else ''
        inline_name, inline_size = _split_sku_name(name_text)
        if inline_size and not size_text:
            size_text = inline_size
        if inline_name:
            name_text = inline_name
        return _norm_text(name_text), _norm_text(size_text)

    def _row_identity(row):
        spec_texts = []
        try:
            spec_cells = row.eles('xpath:./td[contains(@class,"attr-column-field_spec_")]', timeout=0.05) or []
        except Exception:
            spec_cells = []
        for cell in spec_cells:
            try:
                text = _norm_text(cell.text)
            except Exception:
                text = ''
            if text:
                spec_texts.append(text)
        return _identity_from_texts(spec_texts)

    def _sku_tokens(value):
        """规格文本 → token 序列（统一分隔符 + 去掉尾部括号噪声）。"""
        tokens = []
        for part in _sku_separator_re.split(_norm_text(value)):
            part = _strip_tail_parentheses(part)
            if part:
                tokens.append(part)
        return tokens

    def _row_match_score(row_name, row_size, sku_name):
        """页面行 ←→ sku_list 条目的匹配打分，0 表示不匹配。

        为什么不能直接比字符串：页面上「码数」轴是本工具**写死为「均码」**的
        （见 _configure_sku_structure 的「选择均码」），它不携带任何区分信息；
        而 sku_list 的名字可能带源平台真实尺码（`塞纳灰格纹 / 36-40`）、
        或把多个规格值连写（`男袜高橡筋款 / 均码/长绒棉/抗起球/独立包装`）。

        旧守卫 `expected_size and row_size and expected_size != row_size → False`
        因此**必然失败**：拿 SKU 名里的 36-40 去比页面的均码，永远不等。
        2026-10-01 的 5 连败就是这个原因（失败现场截图确认：
        颜色分类的规格值就是完整 SKU 名 `榛子蝴蝶结 / 36-40`，码数轴是「均码」）。

        改为「颜色主题一致 + 共享 token 越多越具体」：
        - 行的首个 token 必须出现在 SKU 的 token 里 —— 防止把 A 款填成 B 款；
        - 行侧其余 token（绝大多数是码数）**不作为否决条件**；
        - 打分让同名不同规格的多个候选里，最具体的那个胜出。
        """
        row_tokens = _sku_tokens(row_name) + _sku_tokens(row_size)
        sku_tokens = _sku_tokens(sku_name)
        if not row_tokens or not sku_tokens:
            return 0
        if row_tokens[0] not in sku_tokens:
            return 0
        return 2 + len(set(row_tokens) & set(sku_tokens))

    def _visible_rows(root):
        try:
            rows = root.eles('xpath:.//tr[contains(@class,"ecom-g-table-row")]', timeout=0.1) or []
        except Exception:
            rows = []
        result = []
        for row in rows:
            try:
                if row and row.states.is_displayed:
                    result.append(row)
            except Exception:
                continue
        return result

    def _row_key(row, row_name, row_size):
        try:
            key = _norm_text(row.attr('data-row-key'))
        except Exception:
            key = ''
        return key or f'{row_name}||{row_size}'

    def _input_in_row(row, field):
        try:
            return row.ele(f'xpath:./td[contains(@class,"attr-column-field_{field}")]//input', timeout=0.2)
        except Exception:
            return None

    def _scan_rows(root):
        """一次往返取回所有已渲染行的 key / 规格文本 / 当前值。

        逐行走 DrissionPage 属性读取每行要 4~5 次 CDP 往返（可见性、规格单元格、
        单元格文本、data-row-key），再叠加等待重渲染的轮询后可达数千次，
        是填写过程卡顿的主因。这里用一次整表 JS 扫描替代；
        JS 不可用时回退到逐行读取，保证功能不依赖该优化。

        返回 (rows, blank_row_count)，rows 元素为
        {'key','name','size','price','stock'}，name/size 已按既有规则规范化。
        """
        raw = None
        try:
            raw = root.run_js(_PRICE_STOCK_ROW_SCAN_JS)
        except Exception:
            raw = None

        rows = []
        blank = 0
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                texts = [_norm_text(text) for text in (item.get('texts') or [])]
                texts = [text for text in texts if text]
                name, size = _identity_from_texts(texts)
                if not name and not size:
                    blank += 1
                    continue
                rows.append({
                    'key': _norm_text(item.get('key')) or f'{name}||{size}',
                    'name': name,
                    'size': size,
                    'price': item.get('price'),
                    'stock': item.get('stock'),
                })
            return rows, blank

        for row in _visible_rows(root):
            name, size = _row_identity(row)
            if not name and not size:
                blank += 1
                continue
            rows.append({
                'key': _row_key(row, name, size),
                'name': name,
                'size': size,
                'price': None,
                'stock': None,
                'element': row,
            })
        return rows, blank

    def _find_row_by_identity(root, row_name, row_size):
        """没有 data-row-key 时的慢路径：遍历可见行按规格文本定位。"""
        for row in _visible_rows(root):
            name, size = _row_identity(row)
            if name == row_name and size == row_size:
                return row
        return None

    def _refresh_row(root, row_key):
        """按 data-row-key 重新解析行元素。

        虚拟列表在 scroll.to_center() 后可能重新挂载行，旧句柄随之失效，
        继续拿旧句柄取输入框只会得到 None。row_key 为回退值（name||size）时
        无法精确定位，返回 None 交由调用方走下一轮重扫。
        """
        if not row_key or '||' in row_key:
            return None
        try:
            return root.ele(f'xpath:.//tr[@data-row-key={_xpath_literal(row_key)}]', timeout=0.3)
        except Exception:
            return None

    def _holder():
        for selector in (
            'xpath:.//div[contains(@class,"ecom-g-table-tbody-virtual-holder")]',
            'xpath:.//div[contains(@class,"ecom-g-table-tbody-virtual") and contains(@class,"ecom-g-table-tbody")]',
        ):
            try:
                item = price_stock_root.ele(selector, timeout=0.1)
            except Exception:
                item = None
            if item:
                return item
        return None

    def _metrics(holder):
        if not holder:
            return {'top': 0, 'height': 0, 'total': 0}
        try:
            data = holder.run_js('return {top: this.scrollTop || 0, height: this.clientHeight || 0, total: this.scrollHeight || 0};') or {}
        except Exception:
            data = {}
        return {
            'top': int(data.get('top') or 0),
            'height': int(data.get('height') or 0),
            'total': int(data.get('total') or 0),
        }

    def _set_top(holder, top):
        if holder:
            holder.run_js('this.scrollTop = arguments[0]; this.dispatchEvent(new Event("scroll", {bubbles:true}));', int(top))

    def _row_keys_snapshot(root):
        """当前已渲染行的 key 序列，用来判断虚拟列表是否真的换了一批行。

        该函数在等待重渲染的轮询里被反复调用，必须走整表扫描的单次往返，
        否则每次轮询都要按行发起数十次 CDP 调用。
        """
        rows, _ = _scan_rows(root)
        return tuple(item['key'] for item in rows)

    def _scroll_rows_to(holder, root, target_top, previous_keys):
        """滚到指定位置，并等虚拟列表真正渲染出新的一批行。

        rc-virtual-list 的 scrollTop 是同步赋值、行渲染是 React 异步的，
        只等 scrollTop 数值到位会立刻通过（等于没等），随后读到的仍是上一屏的旧行，
        表现为「滚到底还剩最后几个 SKU 没填」。因此这里额外等待行 key 集合发生变化。
        """
        _set_top(holder, target_top)
        _wait_until(
            lambda: abs((_metrics(holder).get('top') or 0) - target_top) <= 2,
            timeout=0.5,
            interval=0.02,
        )
        if not previous_keys:
            return
        _wait_until(
            lambda: _row_keys_snapshot(root) not in ((), previous_keys),
            timeout=1.5,
            interval=0.05,
        )

    holder = _holder()
    if holder:
        _set_top(holder, 0)
        _wait_until(lambda: abs((_metrics(holder).get('top') or 0) - 0) <= 2, timeout=0.2, interval=0.02)

    processed_keys = set()
    pending_indexes = list(range(len(sku_list)))
    guard = 0
    rollback_count = 0
    # 表格不需要（或无法）继续滚动时，唯一能救回「本轮因句柄失效被跳过的行」的手段
    # 就是原地重扫。旧实现只在 current_top > 0 时才重试，等于「表格一屏放得下」
    # 就一次机会都不给，直接抛「滚动未推进」——2026-10-01 的失败现场
    # （末尾数行已完整渲染、价格/库存输入框就在 DOM 里，却始终没被写入）正是这种情形。
    stall_retries = 0
    last_keys = None
    while pending_indexes:
        guard += 1
        if guard > max(len(sku_list) * 8, 32):
            raise Exception('价格库存填写过程中出现异常循环，未能按顺序推进')

        price_stock_root = _find_price_stock_root(main_tab)
        if not price_stock_root:
            raise Exception('未找到价格与库存区域')
        holder = _holder()

        scanned_rows, blank_rows = _scan_rows(price_stock_root)
        if not scanned_rows and not blank_rows:
            raise Exception('未找到价格库存表格行')
        last_keys = tuple(item['key'] for item in scanned_rows)
        # 本轮消解掉的 SKU 数（写入成功 + 扫描时发现已是目标值而快速跳过）。
        # 用来区分「原地重扫能救回来」与「真的卡死了」：
        # 只要本轮还有 SKU 被消解，说明行句柄是活的，剩余的大概率只是被瞬态重渲染跳过。
        pending_before_pass = len(pending_indexes)

        for item in scanned_rows:
            row_name, row_size = item['name'], item['size']
            row_key = item['key']
            if row_key in processed_keys:
                continue

            # 在所有尚未填写的 SKU 里找与当前行匹配的那一条。
            # 不能只匹配「下一个」SKU：虚拟滚动换屏会跳行，页面行序也不保证与
            # sku_list 顺序一致，按序匹配会让整屏行全部落空，最终卡死在滚动未推进。
            # 也不能取「第一个命中」：多个 SKU 共享同一颜色主题时
            # （如 `S2636组合A+均码` 与 `S2636组合A+自选2双`，首 token 相同），
            # 首个命中可能落到相邻规格上，把价格写错行。取分数最高者。
            matched_index = None
            best_score = 0
            for candidate_index in pending_indexes:
                candidate_name = str(sku_list[candidate_index].get('name', '')).strip()
                score = _row_match_score(row_name, row_size, candidate_name)
                if score > best_score:
                    best_score = score
                    matched_index = candidate_index
            if matched_index is None:
                continue

            sku = sku_list[matched_index]
            sku_name = str(sku.get('name', '')).strip()
            sku_price = _normalize_upload_numeric_text(sku.get('price'))
            sku_stock = _normalize_upload_numeric_text(record.repo)

            # 扫描时已带回当前值：命中目标值就无需重写（回滚重扫时可直接略过整屏）
            if (
                item.get('price') is not None
                and _normalize_upload_numeric_text(item.get('price')) == sku_price
                and _normalize_upload_numeric_text(item.get('stock')) == sku_stock
            ):
                processed_keys.add(row_key)
                pending_indexes.remove(matched_index)
                continue

            # 只对确实要填的行做 DOM 定位，避免整屏行都走一遍元素查找
            tr = item.get('element') or _refresh_row(price_stock_root, row_key)
            if tr is None:
                tr = _find_row_by_identity(price_stock_root, row_name, row_size)
            if tr is None:
                continue
            tr.scroll.to_center()

            # to_center() 可能触发虚拟列表重挂载，使 tr 句柄失效，
            # 先按 data-row-key 重新解析一次再取输入框。
            row_element = _refresh_row(price_stock_root, row_key) or tr
            price_input = _input_in_row(row_element, 'price')
            stock_input = _input_in_row(row_element, 'stock_info')
            if not price_input or not stock_input:
                # 多为重渲染导致的句柄失效，本轮跳过、交给下一轮以新句柄重扫；
                # 若确实是结构缺失，最终会带着「页面当前可见行」一并报错，不会被静默吞掉。
                continue

            filled_no = len(sku_list) - len(pending_indexes) + 1
            print(f'填写SKU价格库存 -> {filled_no}/{len(sku_list)}. {sku_name} | 价格:{sku_price} | 库存:{sku_stock}')

            price_input.input(sku_price, clear=True)
            stock_input.input(sku_stock, clear=True)

            expected_price = _normalize_upload_numeric_text(sku_price)
            expected_stock = _normalize_upload_numeric_text(sku_stock)

            def _written():
                return (
                    _normalize_upload_numeric_text(price_input.attr('value')) == expected_price
                    and _normalize_upload_numeric_text(stock_input.attr('value')) == expected_stock
                )

            if not _wait_until(_written, timeout=2.0, interval=0.1):
                price_value = _normalize_upload_numeric_text(price_input.attr('value'))
                stock_value = _normalize_upload_numeric_text(stock_input.attr('value'))
                raise Exception(
                    f'价格库存写入校验失败：{sku_name} -> 期望价格[{expected_price}] 实际价格[{price_value}] 期望库存[{expected_stock}] 实际库存[{stock_value}]'
                )

            processed_keys.add(row_key)
            pending_indexes.remove(matched_index)

        if blank_rows:
            print(f'跳过价格库存空白行：{blank_rows} 行')

        if not pending_indexes:
            break

        def _remaining_text():
            return '、'.join(
                str(sku_list[index].get('name', '')).strip() for index in pending_indexes[:5]
            )

        def _visible_rows_text():
            names = []
            for row in _visible_rows(price_stock_root):
                row_name, row_size = _row_identity(row)
                if not row_name and not row_size:
                    continue
                names.append(f'{row_name}+{row_size}' if row_size else row_name)
            return '、'.join(names[:8]) or '(无)'

        def _pending_diagnosis():
            """区分「行压根没渲染」与「行渲染了但输入框没定位到」。

            这两类问题的修法完全不同，旧文案统一说成「滚动未推进」，
            导致 2026-08-27 ~ 2026-10-01 的排查方向被带偏了整整一个月。
            """
            seen = []
            for item in scanned_rows:
                for index in pending_indexes:
                    name = str(sku_list[index].get('name', '')).strip()
                    if _row_match_score(item['name'], item['size'], name) > 0:
                        seen.append(f'{name}→row#{item["key"]}')
                        break
            if not seen:
                return '这些 SKU 的行未出现在已渲染行里（虚拟滚动未覆盖或数据对不上）'
            return '行已渲染但价格/库存输入框未定位到（' + '、'.join(seen[:3]) + '）'

        if not holder:
            raise Exception(
                f'价格库存可见行不足，剩余SKU未填写：{_remaining_text()}'
                f'｜页面当前可见行：{_visible_rows_text()}'
            )

        # 一律以页面真实滚动位置为准推进：填写时的 tr.scroll.to_center() 会在背后
        # 改变 scrollTop，若继续按本地维护的目标值回设，两者会来回拉扯，
        # 表现为「填到一半后可见行被拉回开头，再也推进不了」。
        data = _metrics(holder)
        viewport_height = data.get('height') or 0
        total_height = data.get('total') or 0
        current_top = data.get('top') or 0
        max_top = max(total_height - viewport_height, 0)
        # 步长取半屏，留足重叠区域，减少虚拟滚动跳行
        step = max(int(viewport_height * 0.50), 120) if viewport_height else 120
        next_top = min(current_top + step, max_top)
        if next_top <= current_top:
            # 已滚到底但还有 SKU 未填写——可能被跳行遗漏了，
            # 回滚到顶部重新完整扫描一遍（最多回滚 2 次防死循环）。
            # 清空 processed_keys 让每一行重新参与匹配；pending_indexes 保证已填的 SKU 不会重复写。
            if current_top > 0 and rollback_count < 2:
                rollback_count += 1
                print(f'价格库存滚动到底仍有 {len(pending_indexes)} 个SKU未填写，回滚重扫(第{rollback_count}次)')
                processed_keys.clear()
                _scroll_rows_to(holder, price_stock_root, 0, last_keys)
                last_keys = None
                continue
            # 滚不动了（current_top == 0，典型是整表一屏放得下）。
            # 循环体里对「句柄失效」的处理是 continue、「交给下一轮以新句柄重扫」，
            # 但旧实现到这里就直接抛错了——那个承诺的重扫永远不会发生，
            # 于是任何一次瞬态重渲染都变成硬失败，且报错文案把「输入框没定位到」
            # 说成「滚动未推进」，把排查方向带偏（2026-10-01 现场：末尾数行
            # 已完整渲染、输入框就在 DOM 里，却始终没被写入）。
            # 只要本轮还有 SKU 被消解（写入成功，或扫描时发现已是目标值），
            # 就说明行句柄是活的，剩余的大概率只是被瞬态重渲染跳过，原地重扫能救回来。
            if (pending_before_pass - len(pending_indexes)) > 0 and stall_retries < _stall_retry_limit:
                stall_retries += 1
                print(
                    f'价格库存无需继续滚动但仍有 {len(pending_indexes)} 个SKU未填写，'
                    f'原地重扫(第{stall_retries}/{_stall_retry_limit}次)'
                )
                processed_keys.clear()
                last_keys = None
                system_time.sleep(0.2)
                continue
            raise Exception(
                f'价格库存填写未完成（表格无法继续滚动，{_pending_diagnosis()}），'
                f'剩余SKU未填写：{_remaining_text()}'
                f'｜页面当前可见行：{_visible_rows_text()}'
            )
        _scroll_rows_to(holder, price_stock_root, next_top, last_keys)

    main_tab.ele('xpath://span[text()="售后服务承诺"]').scroll.to_see()
    select_text(main_tab, '运费模板', shipping_template_name, '包邮')
    youhui_btn = main_tab.ele('xpath://button[contains(@class,"marketing_sylva-switch-checked")]', timeout=1)
    if youhui_btn:
        print('取消商品优惠券勾选')
        youhui_btn.click(by_js=True)

    print('选择商品状态 -> 上架')
    main_tab.ele('xpath://span[text()="上架"]').click(by_js=True)

    try:
        switch = main_tab.ele('xpath://button[@dropdownclassname="auto-dropdown-id-支持联盟达人带货"]', timeout=2)
        if switch and switch.states.is_displayed:
            cls = switch.attr('class') or ''
            disabled_attr = switch.attr('disabled')
            if ('disabled' not in cls) and (disabled_attr is None):
                print('勾选支持联盟达人带货')
                switch.click(by_js=True)
                rate_input = main_tab.ele('xpath://label[@title="佣金率"]/../..//input', timeout=2)
                if rate_input:
                    print('输入佣金率：20%')
                    rate_input.input('20')
                    _wait_until(
                        lambda: _normalize_upload_numeric_text(rate_input.attr('value')) == '20',
                        timeout=0.6,
                        interval=0.03,
                    )
            else:
                print('联盟达人带货不可用，已跳过')
        else:
            print('未找到联盟达人带货开关，已跳过')
    except Exception:
        print('处理联盟达人带货失败，已跳过')


class PublishUnconfirmedError(Exception):
    """已点「发布商品」但没读到结果——绝不能当成「没发布」处理。

    这是本流程里最贵的一类错误：判成失败就会被重跑，而重跑即重复铺货。
    2026-10-01 实测：商品 ID-1081080198595 已提交成功、页面显示
    「商品提交成功，需审核通过后生效」，程序却判失败且不落库（status=0）。
    """


# 提交结果确认预算。原实现只等 13s，实测 5 次失败全部跑满窗口，
# 而平台侧「创建商品 + 图片转存 + 送审」在此之前没有返回结果页。
_SUBMIT_CONFIRM_TIMEOUT = 60.0

# 发布成功后页面切到结果页会渲染这组按钮，表单页上不会同时出现，
# 因此作为整句文案之外的第二判据（文案改版时仍能判对）。
_SUBMIT_RESULT_BUTTONS = ('继续发布', '返回商品列表', '编辑商品')

# 一次 CDP 往返同时取回「成功文案 / 结果页按钮 / 表单是否卸载 / 发布提醒弹窗」四个状态。
_SUBMIT_STATE_PROBE_JS = r'''
const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
const body = document.body ? (document.body.innerText || '') : '';
const buttons = Array.prototype.map.call(document.querySelectorAll('button'), (b) => norm(b.innerText));
const wanted = ['继续发布', '返回商品列表', '编辑商品'];
const resultButtons = wanted.filter((t) => buttons.indexOf(t) >= 0);
const titles = document.querySelectorAll('[class*="ecom-g-modal-title"]');
let publishModal = false;
for (let i = 0; i < titles.length; i++) {
    if (norm(titles[i].innerText) === '发布提醒') { publishModal = true; break; }
}
return {
    success: body.indexOf('商品提交成功') >= 0 || body.indexOf('商品发布成功') >= 0,
    fieldCount: document.querySelectorAll('[attr-field-id]').length,
    resultButtons: resultButtons,
    publishModal: publishModal
};
'''


def _submit_publish(main_tab, record):
    print('发布商品')
    _dismiss_interfering_overlays(main_tab, context='submit_publish')
    main_tab.ele('xpath://span[text()="发布商品"]/..').click()
    # @class 全等匹配在组件追加 class 时会失效，这里放宽为 contains
    modal_selector = (
        'xpath://div[contains(@class,"ecom-g-modal-title") and normalize-space(text())="发布提醒"]/../..'
    )
    success_selectors = (
        '商品提交成功，继续发布商品视频，分享到抖音',
        '商品发布成功，继续发布商品视频，分享到抖音',
        '商品发布成功，线上商品数据已更新',
    )

    def _handle_publish_modal():
        """处理「发布提醒」弹窗。

        该弹窗可能迟于点击若干秒才出现，因此必须在整个等待窗口内持续尝试：
        原实现只在前 1.2s 查一次，弹窗迟到就再也不会被点掉，
        随后白等满 12s 判定失败——而失败路径不落库，重跑即造成重复铺货。
        """
        try:
            modal = main_tab.ele(modal_selector, timeout=0.05)
        except Exception:
            return False
        if not modal:
            return False
        try:
            continue_btn = modal.ele(
                'xpath:.//div[text()="不修改，继续发布"]/ancestor::button', timeout=0.1
            )
        except Exception:
            continue_btn = None
        if not continue_btn:
            return False
        try:
            continue_btn.scroll.to_center()
            continue_btn.click()
        except Exception as exc:
            print(f'处理发布提醒弹窗失败: {exc}')
            return False
        print('已处理发布提醒弹窗')
        return True

    def _read_submit_state():
        """一次往返读回页面状态；JS 不可用时返回 None，由调用方回退文本判据。"""
        try:
            state = main_tab.run_js(_SUBMIT_STATE_PROBE_JS)
        except Exception:
            return None
        return state if isinstance(state, dict) else None

    def _state_means_success(state):
        if not state:
            return False
        if state.get('success'):
            return True
        # 结果页按钮组比整句文案更稳：文案改版、走别的成功分支都能认出来。
        return len(state.get('resultButtons') or []) >= 2

    publish_ok = False
    last_state = None
    started_at = system_time.perf_counter()
    deadline = started_at + _SUBMIT_CONFIRM_TIMEOUT
    next_progress_log = started_at + 10.0
    while True:
        state = _read_submit_state()
        last_state = state
        if _state_means_success(state):
            publish_ok = True
            break
        if state is None:
            # JS 不可用时保留旧文案，并兼容新版「商品发布成功」及结果页按钮组。
            try:
                for success_selector in success_selectors:
                    if main_tab.ele(success_selector, timeout=0.05):
                        publish_ok = True
                        break
            except Exception:
                pass
            if not publish_ok:
                result_button_hits = 0
                for button_text in _SUBMIT_RESULT_BUTTONS:
                    try:
                        button_selector = (
                            f'xpath://button[normalize-space(.)="{button_text}"'
                            f' or .//span[normalize-space(.)="{button_text}"]]'
                        )
                        if main_tab.ele(button_selector, timeout=0.05):
                            result_button_hits += 1
                    except Exception:
                        continue
                if result_button_hits >= 2:
                    publish_ok = True
            if publish_ok:
                break
        if _handle_publish_modal():
            _dismiss_interfering_overlays(main_tab, context='after_publish_click')
            continue
        now = system_time.perf_counter()
        if now >= deadline:
            break
        if now >= next_progress_log:
            print(f'  等待发布结果…已 {now - started_at:.0f}s / {_SUBMIT_CONFIRM_TIMEOUT:.0f}s')
            next_progress_log = now + 10.0
        system_time.sleep(0.15)

    if publish_ok:
        print('发布成功！')
        record.status = 1
        record.publish_time = time.now()
        record.save()
        return True

    # 未读到成功信号 ≠ 一定没提交：文案改版、页面跳转、服务端慢都会这样。
    # 把它当成「没发布」是本流程里最贵的错误——重跑即重复铺货。
    # 因此这里：
    #   1) 落库为「已提交待确认」(status=2)；「一键发布全部」只挑 status == 0
    #      （见 start-all 的 Record.status == 0 过滤），所以它不会被自动重跑；
    #   2) 抛可读异常而不是 return False —— 让上层走异常分支抓取浏览器现场快照
    #      （旧实现 return False 会绕过快照，最危险的一次失败反而没有现场记录）。
    record.status = 2
    record.save()
    current_url = _get_current_tab_url(main_tab)
    field_count = (last_state or {}).get('fieldCount')
    result_buttons = (last_state or {}).get('resultButtons') or []
    detail = (
        f'当前页面: {current_url}'
        f'｜表单字段数: {field_count if field_count is not None else "未知"}'
        f'｜已出现的结果页按钮: {result_buttons or "无"}'
    )
    print('发布结果未确认！')
    print(f'  {detail}')
    raise PublishUnconfirmedError(
        f'提交结果未在 {_SUBMIT_CONFIRM_TIMEOUT:.0f}s 内确认：已点击「发布商品」，但没读到成功标志。'
        f'商品可能已经提交成功（平台侧生效有延迟），请先到「商品管理 → 审核记录」核对，'
        f'确认不存在该商品后再重跑——直接重跑会造成重复铺货。'
        f'本记录已标记为「已提交待确认」，不会被「一键发布全部」自动重跑。'
        f'｜{detail}'
    )

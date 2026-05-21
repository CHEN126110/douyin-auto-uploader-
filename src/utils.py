# -*- coding: utf-8 -*-
# mypy: ignore-errors
# pyright: reportOptionalMemberAccess=false, reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportGeneralTypeIssues=false
# type: ignore

import json
import os
import re
import tempfile
import time as _time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener, urlopen
from DrissionPage import ChromiumOptions, ChromiumPage  # type: ignore
from flask_jwt_extended import create_access_token
import logging
from src import constants
from typing import Union, Optional, List, Dict, Any, Callable
import traceback
import psutil
from PIL import Image
from contextlib import contextmanager

# 导入Chrome管理器
try:
    from src.chrome_manager import ensure_chrome_available, get_chrome_path
except ImportError:
    # 如果chrome_manager模块不存在,使用备用方案
    def ensure_chrome_available():
        return None
    def get_chrome_path():
        return None

logger = logging.getLogger(__name__)
_interaction_recovery_hook: Optional[Callable[[Any, str], Any]] = None

_DEBUG_BROWSER_NAMES = {
    'chrome.exe': 'Chrome',
    'msedge.exe': 'Edge',
    'chromium.exe': 'Chromium',
}


def register_interaction_recovery_hook(hook: Optional[Callable[[Any, str], Any]]) -> None:
    global _interaction_recovery_hook
    _interaction_recovery_hook = hook


def _run_interaction_recovery(tab, context: str) -> None:
    hook = _interaction_recovery_hook
    if not callable(hook) or tab is None:
        return
    try:
        hook(tab, context=context)
    except Exception:
        pass


def _get_automation_timer_log_path():
    local_app_data = os.environ.get('LOCALAPPDATA')
    if local_app_data:
        log_dir = os.path.join(local_app_data, 'com.dyin.sock-publisher', 'logs')
    else:
        log_dir = os.path.join(tempfile.gettempdir(), 'com.dyin.sock-publisher', 'logs')
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        return os.path.join(tempfile.gettempdir(), 'automation-substeps.jsonl')
    return os.path.join(log_dir, 'automation-substeps.jsonl')


_AUTOMATION_TIMER_LOG_PATH = _get_automation_timer_log_path()


def _append_automation_timer_log(entry):
    try:
        with open(_AUTOMATION_TIMER_LOG_PATH, 'a', encoding='utf-8', errors='replace') as fp:
            fp.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass


# ==================== 自动化计时器 ====================
class AutomationTimer:
    """自动化操作计时器，用于追踪每个步骤的耗时"""
    
    _stats = {}  # 类级别的统计数据
    _current_session = None  # 当前会话ID
    
    @classmethod
    def start_session(cls, session_id: str = None):
        """开始新的计时会话"""
        cls._current_session = session_id or datetime.now().strftime('%Y%m%d_%H%M%S')
        cls._stats[cls._current_session] = {
            'start_time': _time.time(),
            'operations': [],
            'summary': {}
        }
        logger.info(f"[TIMER] ========== 开始计时会话: {cls._current_session} ==========")
        return cls._current_session
    
    @classmethod
    def end_session(cls):
        """结束当前计时会话并输出汇总"""
        if cls._current_session and cls._current_session in cls._stats:
            session = cls._stats[cls._current_session]
            total_time = _time.time() - session['start_time']
            
            logger.info(f"[TIMER] ========== 会话汇总: {cls._current_session} ==========")
            logger.info(f"[TIMER] 总耗时: {total_time:.2f}s")
            
            # 按操作类型汇总
            summary = {}
            for op in session['operations']:
                op_type = op['type']
                if op_type not in summary:
                    summary[op_type] = {'count': 0, 'total_time': 0, 'wait_time': 0, 'action_time': 0}
                summary[op_type]['count'] += 1
                summary[op_type]['total_time'] += op.get('total_time', 0)
                summary[op_type]['wait_time'] += op.get('wait_time', 0)
                summary[op_type]['action_time'] += op.get('action_time', 0)
            
            # 输出汇总
            logger.info(f"[TIMER] {'操作类型':<20} {'次数':>6} {'总耗时':>10} {'等待时间':>10} {'操作时间':>10}")
            logger.info(f"[TIMER] {'-'*60}")
            for op_type, stats in sorted(summary.items(), key=lambda x: x[1]['total_time'], reverse=True):
                logger.info(f"[TIMER] {op_type:<20} {stats['count']:>6} {stats['total_time']:>9.2f}s {stats['wait_time']:>9.2f}s {stats['action_time']:>9.2f}s")
            
            # 找出最耗时的操作
            if session['operations']:
                slowest = max(session['operations'], key=lambda x: x.get('total_time', 0))
                logger.info(f"[TIMER] 最耗时操作: {slowest['name']} - {slowest.get('total_time', 0):.2f}s")
            
            logger.info(f"[TIMER] ========== 会话结束 ==========")
            session['summary'] = summary
            cls._current_session = None
            return summary
        return {}
    
    @classmethod
    def record(cls, op_type: str, name: str, wait_time: float = 0, action_time: float = 0, success: bool = True):
        """记录一次操作"""
        if cls._current_session and cls._current_session in cls._stats:
            total_time = wait_time + action_time
            op_record = {
                'type': op_type,
                'name': name,
                'wait_time': wait_time,
                'action_time': action_time,
                'total_time': total_time,
                'success': success,
                'timestamp': datetime.now().isoformat()
            }
            cls._stats[cls._current_session]['operations'].append(op_record)
            _append_automation_timer_log({
                'session_id': cls._current_session,
                'captured_at': datetime.now().isoformat(),
                **op_record,
            })
            
            # 实时日志输出
            status = "[OK]" if success else "[FAIL]"
            logger.info(f"[TIMER] {status} {op_type}/{name}: 等待={wait_time:.2f}s, 操作={action_time:.2f}s, 总计={total_time:.2f}s")
    
    @classmethod
    @contextmanager
    def measure(cls, op_type: str, name: str):
        """上下文管理器方式计时"""
        start = _time.time()
        wait_start = start
        result = {'wait_time': 0, 'action_time': 0, 'success': True}
        
        try:
            yield result
        except Exception as e:
            result['success'] = False
            raise
        finally:
            end = _time.time()
            if result.get('wait_end'):
                result['wait_time'] = result['wait_end'] - wait_start
                result['action_time'] = end - result['wait_end']
            else:
                result['action_time'] = end - start
            cls.record(op_type, name, result['wait_time'], result['action_time'], result['success'])
    
    @classmethod
    def get_stats(cls, session_id: str = None):
        """获取统计数据"""
        sid = session_id or cls._current_session
        if sid and sid in cls._stats:
            return cls._stats[sid]
        return None


# 便捷函数
def timer_start_session(session_id: str = None):
    """开始计时会话"""
    return AutomationTimer.start_session(session_id)

def timer_end_session():
    """结束计时会话"""
    return AutomationTimer.end_session()

def timer_record(op_type: str, name: str, wait_time: float = 0, action_time: float = 0, success: bool = True):
    """记录操作计时"""
    AutomationTimer.record(op_type, name, wait_time, action_time, success)


class time:
    @staticmethod
    def now():
        return datetime.now()
    
    @staticmethod
    def sleep(seconds):
        try:
            delay = float(seconds)
        except Exception:
            return
        if delay <= 0:
            return
        _time.sleep(delay)
        
    @staticmethod
    def strftime(dt, format_str):
        return dt.strftime(format_str)

wazi_dict = {
    0: '船袜',
    1: '短袜', 
    2: '中筒袜',
    3: '长筒袜',
    4: '袜套'
}

wazi_dict_2 = {
    2: '中筒袜',
    3: '长筒袜',
    4: '短筒袜'
}

def get_current_category_text(new_tab) -> str:
    selectors = [
        'xpath://div[@attr-field-id="商品类目"]//div[contains(@class,"style_currentCategory")]',
        'xpath://div[@attr-field-id="商品类目"]//*[contains(text(),">")]',
    ]
    for selector in selectors:
        try:
            ele = new_tab.ele(selector, timeout=0.5)
            text = re.sub(r'\s+', ' ', (ele.text or '').strip())
            if text:
                return text
        except Exception:
            pass
    return ''


def infer_sock_height_value(category_text: str, fallback=None) -> str:
    category_text = re.sub(r'\s+', ' ', str(category_text or '')).strip()
    leaf = category_text.split('>')[-1].strip() if category_text else ''

    if leaf in ('长筒袜', '中筒袜', '短筒袜'):
        return leaf
    if leaf == '短袜':
        return '短筒袜'
    if leaf == '袜套':
        return '短筒袜'
    if leaf == '船袜':
        return ''
    if '长筒' in leaf:
        return '长筒袜'
    if '中筒' in leaf:
        return '中筒袜'
    if '短筒' in leaf or '短袜' in leaf:
        return '短筒袜'

    fallback_map = {
        1: '短筒袜',
        2: '中筒袜',
        3: '长筒袜',
        4: '短筒袜',
    }
    try:
        return fallback_map.get(int(fallback), '')
    except Exception:
        return ''


def click_field_action(new_tab, field_id: str, action_text: str, timeout: float = 1.0) -> bool:
    try:
        areas = new_tab.eles(f'xpath://div[@attr-field-id="{field_id}"]', timeout=timeout)
    except Exception:
        areas = []
    if not areas:
        return False

    selectors = [
        f'xpath:.//button[.//*[contains(normalize-space(text()),"{action_text}")]]',
        f'xpath:.//*[contains(normalize-space(text()),"{action_text}")]/ancestor::button[1]',
        f'xpath:.//*[contains(normalize-space(text()),"{action_text}")]/ancestor::div[contains(@class,"styles-module_wrapper__")][1]',
        f'xpath:.//*[contains(normalize-space(text()),"{action_text}")]/ancestor::div[contains(@class,"style_modifyButton__")][1]',
        f'xpath:.//*[contains(normalize-space(text()),"{action_text}")]',
    ]

    def _find_target(area, probe_timeout: float):
        for selector in selectors:
            try:
                target = area.ele(selector, timeout=probe_timeout)
            except Exception:
                target = None
            if not target:
                continue
            try:
                if not target.states.is_displayed:
                    continue
            except Exception:
                continue
            class_name = (target.attr('class') or '').lower()
            if 'disabled' in class_name:
                continue
            return target
        return None

    for area in areas:
        try:
            area.scroll.to_center()
        except Exception:
            pass
        target = _find_target(area, 0.12)
        if not target:
            try:
                area.hover()
            except Exception:
                pass
            _wait_until(lambda: _find_target(area, 0.05) is not None, timeout=0.3, interval=0.03)
            target = _find_target(area, 0.05)
        if not target:
            continue
        try:
            _run_interaction_recovery(new_tab, f'click_field_action:{field_id}:{action_text}')
            target.click(by_js=True)
            return True
        except Exception:
            try:
                _run_interaction_recovery(new_tab, f'click_field_action:{field_id}:{action_text}:native')
                target.click()
                return True
            except Exception:
                continue

    return False


MATERIAL_FIELD_IDS = ("面料材质", "材质")


def _material_comboboxes(area, timeout: float = 0.05):
    try:
        return area.eles('xpath:.//input[@role="combobox"]', timeout=timeout) or []
    except Exception:
        return []


def _material_ratio_inputs(area, timeout: float = 0.05):
    try:
        return area.eles(
            'xpath:.//input[contains(@class,"ecom-g-input") and not(@role="combobox")]',
            timeout=timeout,
        ) or []
    except Exception:
        return []


def _find_material_composition_area(new_tab, preferred_field_id=None):
    field_ids = [preferred_field_id] if preferred_field_id else list(MATERIAL_FIELD_IDS)
    for field_id in field_ids:
        if not field_id:
            continue
        try:
            areas = new_tab.eles(f'xpath://div[@attr-field-id="{field_id}"]', timeout=0.6)
        except Exception:
            areas = []
        for candidate in areas:
            if _material_comboboxes(candidate, timeout=0.08):
                return field_id, candidate
    return None, None


def set_material_composition(new_tab, materials, field_id=None) -> bool:
    if not materials:
        return True

    active_field_id, area = _find_material_composition_area(new_tab, field_id)
    if not area:
        expected_name = field_id or " / ".join(MATERIAL_FIELD_IDS)
        print(f'未找到材质配置区域: {expected_name}')
        return False

    try:
        area.scroll.to_center()
    except Exception:
        pass
    _run_interaction_recovery(new_tab, f'set_material_composition:{active_field_id}:start')

    try:
        del_btns = area.eles('xpath:.//span[contains(@class,"styles_del__")]', timeout=0.3)
    except Exception:
        del_btns = []
    extra_count = max(0, len(_material_comboboxes(area, timeout=0.05)) - len(materials))
    for del_btn in reversed(del_btns[-extra_count:] if extra_count else []):
        try:
            before_count = len(area.eles('xpath:.//span[contains(@class,"styles_del__")]', timeout=0.05) or [])
            del_btn.click(by_js=True)
            _wait_until(
                lambda: len(area.eles('xpath:.//span[contains(@class,"styles_del__")]', timeout=0.05) or []) < before_count,
                timeout=0.2,
                interval=0.03,
            )
        except Exception:
            pass

    for idx in range(1, len(materials)):
        target_count = idx + 1
        for attempt in range(2):
            combo_count = len(_material_comboboxes(area, timeout=0.05))
            if combo_count >= target_count:
                break
            added = click_field_action(new_tab, active_field_id, '添加材质')
            if not added:
                fallback_selectors = [
                    f'xpath://div[@attr-field-id="{active_field_id}"]//button[.//*[contains(normalize-space(text()),"添加材质")] or contains(normalize-space(.),"添加材质")]',
                    f'xpath://div[@attr-field-id="{active_field_id}"]//*[contains(normalize-space(text()),"添加材质")]/ancestor::button[1]',
                    f'xpath://div[@attr-field-id="{active_field_id}"]//*[contains(normalize-space(text()),"添加材质")]',
                    'xpath://button[contains(normalize-space(.),"添加材质")]',
                    'xpath://span[contains(normalize-space(.),"添加材质")]/ancestor::button[1]',
                ]
                for selector in fallback_selectors:
                    try:
                        btn = new_tab.ele(selector, timeout=0.3)
                    except Exception:
                        btn = None
                    if not btn:
                        continue
                    try:
                        btn.click(by_js=True)
                        added = True
                        break
                    except Exception:
                        continue
            if not added:
                if attempt == 0:
                    _run_interaction_recovery(new_tab, f'set_material_composition:{active_field_id}:add_retry')
                continue
            _wait_until(
                lambda: len(_material_comboboxes(area, timeout=0.03)) >= target_count,
                timeout=0.35,
                interval=0.03,
            )

    combo_count = len(_material_comboboxes(area, timeout=0.1))
    if combo_count < len(materials):
        print(f'面料输入框数量不足，期望{len(materials)}，实际{combo_count}')
        return False
    if combo_count <= 0:
        return False

    materials_to_fill = list(materials[:len(materials)])

    for idx, material in enumerate(materials_to_fill):
        name = str(material[0]).strip()
        ratio = '' if len(material) < 2 or material[1] is None else str(material[1]).strip()
        caizhi_select(new_tab, name, ratio, idx, active_field_id, area)

    return True

new_btn_xpath = '//div[not(contains(@class,"ecom-g-cascader-menus-hidden"))]/div/div[@style="padding-bottom: 8px;"]/div[starts-with(@class,"styles_addSKUName__")]/span'


def protocol_inject_sku_data(new_tab, sku_list, price, stock=100) -> bool:
    """协议级SKU注入: 通过 React 状态直接注入 spec_detail + sku_detail, 秒填所有SKU
    会等待 schemaForm 出现 (最多5秒)"""
    import uuid as _uuid

    # 等待 schemaForm 可用
    _time.sleep(0.5)  # 先给页面一点时间渲染
    sf_available = False
    for attempt in range(10):
        probe = new_tab.run_cdp('Runtime.evaluate',
            expression='''
                (function() {
                    try {
                        var inst = window.DouXiaoerStore && (window.DouXiaoerStore.instance || window.DouXiaoerStore);
                        if (inst && inst.schemaForm && inst.schemaForm.n) return JSON.stringify({found: true});
                    } catch(e) {}
                    try {
                        if (window.dxStoreRef && window.dxStoreRef.current && window.dxStoreRef.current.schemaForm)
                            return JSON.stringify({found: true});
                    } catch(e) {}
                    return JSON.stringify({found: false});
                })()
            ''', returnByValue=True, awaitPromise=False)
        try:
            probe_data = json.loads((probe.get('result', {}) if isinstance(probe, dict) else {}).get('value', '{"found":false}'))
            if probe_data.get('found'):
                sf_available = True
                break
        except:
            # probe format might differ, try direct
            try:
                val = probe.get('value') if isinstance(probe, dict) else None
                if val and json.loads(val).get('found'):
                    sf_available = True
                    break
            except: pass
        _time.sleep(0.5)

    if not sf_available:
        print('[协议注入] schemaForm 在5秒内未出现, 降级到DOM')
        return False

    colors = list(set(str(s.get('name', '默认')).strip() for s in sku_list)) if sku_list else ['默认']

    spec_detail = [
        {
            'id': '10000', 'cp_id': 2752, 'name': '颜色分类',
            'spec_values': [
                {'id': str(996874532588296900 + i + 18), 'name': c, 'cpv_id': 0, 'cpv_path': [], 'img_url': None}
                for i, c in enumerate(colors)
            ]
        },
        {
            'id': '20000', 'cp_id': 3939, 'name': '码数',
            'spec_values': [{'id': '990897920130195435', 'name': '均码', 'cpv_id': 0, 'cpv_path': [], 'img_url': None}]
        },
        {'id': '30000', 'cp_id': 4706, 'name': '筒高长度', 'spec_values': []},
        {'id': '40000', 'cp_id': 93, 'name': '规格', 'spec_values': []},
    ]

    color_ids = [sv['id'] for sv in spec_detail[0]['spec_values']]
    size_id = spec_detail[1]['spec_values'][0]['id']

    sku_detail = []
    for i, color in enumerate(colors):
        sid = str(_uuid.uuid4())[:8] + '-' + str(_uuid.uuid4())[:6] + '-' + str(_uuid.uuid4())[:12]
        sku_detail.append({
            'id': sid,
            'stock_info': {'stock_num': stock},
            'sku_status': True,
            'confirm_no_barcode': False,
            'spec_detail_ids': [color_ids[i] if i < len(color_ids) else color_ids[0], size_id],
            'price': str(price),
        })

    spec_json = json.dumps(spec_detail, ensure_ascii=False)
    sku_json = json.dumps(sku_detail, ensure_ascii=False)

    expression = f'''
        (function() {{
            try {{
                var sf = null;
                var inst = window.DouXiaoerStore && (window.DouXiaoerStore.instance || window.DouXiaoerStore);
                if (inst) sf = inst.schemaForm;
                if (!sf && window.dxStoreRef && window.dxStoreRef.current) sf = window.dxStoreRef.current.schemaForm;
                if (!sf) return JSON.stringify({{error: 'schemaForm lost'}});

                sf.n('spec_detail').setState({{value: {spec_json}}}, 'inject');
                sf.n('sku_detail').setState({{value: {sku_json}}}, 'inject');

                return JSON.stringify({{ok: true, specs: {len(colors)}, skus: {len(colors)}}});
            }} catch(e) {{
                return JSON.stringify({{error: e.message || String(e)}});
            }}
        }})()
    '''

    try:
        result = new_tab.run_cdp('Runtime.evaluate', expression=expression, returnByValue=True, awaitPromise=False)
        # DrissionPage run_cdp 直接返回 CDP result 字段的内容
        # 格式可能是: {'result': {...}} 或直接是 {...}
        if isinstance(result, dict):
            raw_value = result.get('result', {}).get('value') if isinstance(result.get('result'), dict) else result.get('value', '')
            if not raw_value:
                raw_value = str(result.get('result', result))[:500]
        else:
            raw_value = str(result)[:500]
        try:
            data = json.loads(raw_value) if isinstance(raw_value, str) else (raw_value or {})
        except (json.JSONDecodeError, TypeError):
            data = {'raw': str(raw_value)[:200]}

        # 调试: 写入结果文件
        debug_path = os.path.join(tempfile.gettempdir(), 'sku_inject_result.json')
        try:
            with open(debug_path, 'w', encoding='utf-8') as df:
                json.dump({
                    'ok': data.get('ok', False),
                    'data': str(data)[:500],
                    'raw_value': str(raw_value)[:500],
                    'full_result': str(result)[:1000],
                }, df, ensure_ascii=False)
        except: pass

        if data.get('ok'):
            print(f'[协议注入] SKU秒填成功: {len(colors)}规格 {len(colors)}SKU 价格{price} 库存{stock}')
            return True
        error_reason = data.get('error', data.get('raw', str(data)[:200]))
        print(f'[协议注入] 失败: {error_reason} — 降级到DOM逐行填写')
        return False
    except Exception as e:
        print(f'[协议注入] CDP异常: {e} — 降级到DOM逐行填写')
        debug_path = os.path.join(tempfile.gettempdir(), 'sku_inject_error.txt')
        try:
            with open(debug_path, 'w', encoding='utf-8') as df:
                df.write(f'CDP异常: {e}')
        except: pass
        return False


_SKU_SPEC_INPUT_XPATH = 'xpath://input[@placeholder="请输入规格值"]'
_SKU_REMARK_INPUT_XPATH = 'xpath://div[@id="skuValue-颜色分类"]//input[@placeholder="备注"]'
_SKU_CONFIRM_BOTTOM_XPATHS = (
    'xpath://div[contains(@class,"styles_popupFooter")]//button[contains(@class,"ecom-g-btn-primary")]',
    'xpath://div[contains(@class,"popupFooter")]//button[contains(@class,"ecom-g-btn-primary")]',
    'xpath://button[contains(@class,"ecom-g-btn-primary")][.//span[contains(normalize-space(.),"确定")]]',
)
_SKU_LOCAL_UPLOAD_LABEL_SELECTORS = (
    'xpath://div[contains(@class,"ecom-g-popover")]//label[contains(@class,"index-module_actionBefore") and .//input[@type="file"] and .//*[normalize-space(text())="本地上传"]]',
    'xpath://div[contains(@class,"ecom-g-popover")]//label[contains(@class,"index-module_actionBefore") and .//input[@type="file"] and contains(normalize-space(.),"本地上传")]',
    'xpath://div[contains(@class,"ecom-g-popover-inner-content")]//label[contains(@class,"index-module_actionBefore") and .//input[@type="file"] and contains(normalize-space(.),"本地上传")]',
    'xpath://div[contains(@class,"ecom-g-popover")]//label[.//input[@type="file"] and contains(normalize-space(.),"本地上传")]',
    'xpath://div[contains(@class,"ecom-g-popover-inner-content")]//*[contains(normalize-space(.),"本地上传")]/ancestor::label[1][.//input[@type="file"]]',
)
_SKU_LOCAL_UPLOAD_CONTEXT_SELECTORS = _SKU_LOCAL_UPLOAD_LABEL_SELECTORS + (
    'xpath://div[@id="skuValue-颜色分类"]//label[.//input[@type="file"] and contains(normalize-space(.),"本地上传")]',
    'xpath://div[@id="skuValue-颜色分类"]//*[contains(normalize-space(.),"本地上传")]/ancestor::label[1][.//input[@type="file"]]',
)


def _sku_spec_input_visible_count(tab):
    return len(_get_visible_elements(tab, _SKU_SPEC_INPUT_XPATH, timeout=0.05))


def _sku_confirmed_value_label_elements(tab):
    try:
        labels = tab.eles(
            'xpath://div[@id="skuValue-颜色分类"]//span[contains(@class,"ecom-g-cascader-picker-label")]',
            timeout=0.05,
        )
    except Exception:
        labels = []
    visible = []
    for label in labels:
        try:
            if label and label.states.is_displayed:
                visible.append(label)
        except Exception:
            continue
    return visible


def _sku_confirmed_value_count(tab) -> int:
    return len(_sku_confirmed_value_label_elements(tab))


def _find_sku_anchor_by_index(tab, index: int):
    labels = _sku_confirmed_value_label_elements(tab)
    if 0 <= index < len(labels):
        return labels[index]
    return labels[-1] if labels else None


def _sku_find_visible_confirm_icon(tab):
    """与原先内联逻辑一致：多枚「确认」时取最后一个可见（通常为当前规格行）。"""
    try:
        icons = tab.eles('xpath://span[@data-kora="确认"]', timeout=0.05)
    except Exception:
        icons = []
    last = None
    for icon in icons:
        try:
            if icon and icon.states.is_displayed:
                last = icon
        except Exception:
            continue
    return last


def _sku_find_visible_confirm_bottom(tab):
    for selector in _SKU_CONFIRM_BOTTOM_XPATHS:
        try:
            buttons = tab.eles(selector, timeout=0.05)
        except Exception:
            buttons = []
        for btn in buttons:
            try:
                if btn and btn.states.is_displayed and btn.states.is_enabled:
                    return btn
            except Exception:
                continue
    return None


def _sku_cascader_shows_name(tab, literal: str) -> bool:
    for selector in (
        f'xpath://div[contains(@class,"ecom-g-cascader-menus")]//li[.//*[contains(normalize-space(.), {literal})]]',
        f'xpath://div[contains(@class,"ecom-g-cascader-menus")]//*[contains(normalize-space(.), {literal})]',
    ):
        try:
            for item in tab.eles(selector, timeout=0.05):
                if item and item.states.is_displayed:
                    return True
        except Exception:
            pass
    return False


def _sku_finish_spec_confirmation(
    new_tab,
    sku_name: str,
    before_spec_count: int,
    before_value_count: Optional[int] = None,
) -> None:
    """
    规格值填写后：点小勾 → 如有底部「确定」则点掉关闭弹层。
    逻辑与原先内联实现一致，仅抽出以降低主流程噪音、避免重复选择器散落。
    """
    expected_value_count = (before_value_count + 1) if before_value_count is not None else None

    def _has_confirmed_value():
        if expected_value_count is None:
            return _sku_spec_input_visible_count(new_tab) <= before_spec_count
        return _sku_confirmed_value_count(new_tab) >= expected_value_count

    def _after_icon_progress():
        return (
            _has_confirmed_value()
            or _sku_find_visible_confirm_bottom(new_tab) is not None
        )

    confirm_icon = _sku_find_visible_confirm_icon(new_tab)
    if not confirm_icon:
        raise Exception("未找到规格确认按钮")

    icon_confirmed = False
    for action in (
        lambda: confirm_icon.click(),
        lambda: confirm_icon.click(by_js=True),
        lambda: confirm_icon.run_js(
            "['mousedown','mouseup','click'].forEach(function(type){"
            "this.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,view:window}));"
            "}, this);"
        ),
    ):
        try:
            action()
        except Exception:
            continue
        if _wait_until(_after_icon_progress, timeout=1.0, interval=0.05):
            icon_confirmed = True
            break

    if not icon_confirmed:
        raise Exception("创建类型后未成功确认规格值")

    if _has_confirmed_value():
        return

    _wait_until(lambda: bool(_sku_find_visible_confirm_bottom(new_tab)) or _has_confirmed_value(), timeout=0.5, interval=0.04)
    if _has_confirmed_value():
        return

    confirm_bottom = _sku_find_visible_confirm_bottom(new_tab)

    def _confirm_popup_closed():
        if _has_confirmed_value():
            return True
        visible_n = _sku_spec_input_visible_count(new_tab)
        for selector in _SKU_CONFIRM_BOTTOM_XPATHS:
            try:
                buttons = new_tab.eles(selector, timeout=0.05)
            except Exception:
                buttons = []
            for btn in buttons:
                try:
                    if btn and btn.states.is_displayed:
                        return False
                except Exception:
                    continue
        return expected_value_count is None and visible_n <= before_spec_count

    confirmed = False
    if confirm_bottom:
        try:
            confirm_bottom.scroll.to_center()
        except Exception:
            pass
        for action in (
            lambda: confirm_bottom.click(),
            lambda: confirm_bottom.click(by_js=True),
            lambda: confirm_bottom.run_js(
                "['mousedown','mouseup','click'].forEach(function(type){"
                "this.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,view:window}));"
                "}, this);"
            ),
        ):
            try:
                action()
            except Exception:
                continue
            if _wait_until(_confirm_popup_closed, timeout=1.0, interval=0.04):
                confirmed = True
                break
    else:
        confirmed = _confirm_popup_closed()

    if not confirmed:
        raise Exception("规格确认弹窗未关闭，确定按钮未生效")


def _sku_unique_hover_targets(upload_trigger, hover_target, sku_anchor):
    """同一 DOM 节点只悬停一次，减少无效 hover 与等待。"""
    out = []
    seen = set()
    for t in (upload_trigger, hover_target, sku_anchor):
        if not t:
            continue
        tid = id(t)
        if tid in seen:
            continue
        seen.add(tid)
        out.append(t)
    return out


def _find_first_visible_upload_label(tab, selectors, timeout=0.3, require_enabled=False):
    for selector in selectors:
        try:
            elements = tab.eles(selector, timeout=timeout)
        except Exception:
            elements = []
        for element in elements:
            try:
                if not element or not element.states.is_displayed:
                    continue
                if require_enabled and not element.states.is_enabled:
                    continue
                return element
            except Exception:
                continue
    return None


def _find_sku_row_scope(sku_anchor):
    if not sku_anchor:
        return None
    for selector in (
        'xpath:ancestor::*[.//div[contains(@class,"material-button") and contains(@class,"material-upload-button")]][1]',
        'xpath:ancestor::*[contains(@class,"index-module_")][1]',
    ):
        try:
            scope = sku_anchor.parent(selector)
        except Exception:
            scope = None
        if scope and _find_sku_upload_trigger_in_scope(scope):
            return scope
    node = sku_anchor
    for _ in range(10):
        try:
            node = node.parent()
        except Exception:
            node = None
        if not node:
            break
        if _find_sku_upload_trigger_in_scope(node):
            return node
    return sku_anchor


def _find_sku_upload_trigger_in_scope(row_scope):
    if not row_scope:
        return None
    for selector in (
        'xpath:.//div[contains(@class,"material-button") and contains(@class,"material-upload-button")][1]',
        'xpath:.//div[contains(@class,"material-upload-button")][1]',
        'xpath:.//label[.//input[@type="file"]][1]',
    ):
        try:
            elements = row_scope.eles(selector, timeout=0.12)
        except Exception:
            elements = []
        for item in elements:
            try:
                if item and item.states.is_displayed:
                    return item
            except Exception:
                continue
    return None


def _find_sku_direct_upload_label(row_scope):
    if not row_scope:
        return None
    for selector in (
        'xpath:.//div[contains(@class,"material-upload-button")]//label[.//input[@type="file"]][1]',
        'xpath:.//label[contains(@class,"index-module_button__")][.//input[@type="file"]][1]',
        'xpath:.//label[.//input[@type="file"]][1]',
    ):
        try:
            elements = row_scope.eles(selector, timeout=0.12)
        except Exception:
            elements = []
        for item in elements:
            try:
                if item and item.states.is_displayed:
                    return item
            except Exception:
                continue
    return None


def _sku_resolve_local_upload_label(new_tab, row_scope, sku_anchor, hover_target):
    """
    优先使用当前 SKU 行内真实的文件上传按钮；只有行内按钮不可用时，才回退到
    悬停后寻找 Popover 内的「本地上传」label。
    """
    direct_label = _find_sku_direct_upload_label(row_scope)
    if direct_label:
        return direct_label

    upload_trigger = _find_sku_upload_trigger_in_scope(row_scope)
    for target in _sku_unique_hover_targets(upload_trigger, hover_target, sku_anchor):
        try:
            target.scroll.to_center()
        except Exception:
            pass
        try:
            target.hover()
        except Exception:
            continue

        hovered_button = None

        def _probe_hover_result():
            nonlocal direct_label, hovered_button
            direct_label = _find_sku_direct_upload_label(row_scope)
            if direct_label:
                return True
            try:
                if upload_trigger and upload_trigger.states.is_displayed:
                    hovered_button = upload_trigger
                    return True
            except Exception:
                pass
            btn = _find_sku_local_upload_button(new_tab)
            try:
                if btn and btn.states.is_displayed:
                    hovered_button = btn
                    return True
            except Exception:
                pass
            return False

        if not _probe_hover_result():
            _wait_until(_probe_hover_result, timeout=0.12, interval=0.03)

        if direct_label:
            return direct_label
        if hovered_button:
            return hovered_button
    return None


def api_ok(msg, data=None):
    return {'success': True, 'msg': msg, 'data': data}


def api_error(msg, data=None):
    return {'success': False, 'msg': msg, 'data': data}


def table_api(count, data):
    return {
        'code': 0,
        'msg': '',
        'count': count,
        'data': data
    }


def json_read(file):
    with open(file, 'r', encoding='utf-8-sig') as f:
        return json.loads(f.read())


def json_write(file, data):
    with open(file, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data, indent=4, ensure_ascii=False))


def is_valid_phone_number(phone_number):
    pattern = r'^1[3-9]\d{9}dollar'
    if re.match(pattern, phone_number):
        return True
    else:
        return False


def update_payload(username, remember):
    if username:
        constants.payload = {
            'name': username
        }
        constants.access_token = create_access_token(identity=constants.payload)
    else:
        constants.payload = {}
        constants.access_token = ''
    if remember:
        constants.cfg.data['base']['access_token'] = constants.access_token
        constants.cfg.dump()


def split_number_prefix(text):
    match = re.match(r'^(\d+)\s*', text)
    if match:
        number = match.group(1)
        rest_of_text = text[len(number):].strip()
        return number, rest_of_text
    else:
        return None, text


def should_filter_file(filename: str, filters: List[str]) -> bool:
    """检查文件名是否应该被过滤"""
    if not filters:
        return False
    
    filename_lower = filename.lower()
    for filter_word in filters:
        if filter_word.lower() in filename_lower:
            return True
    return False


def get_nick(file_name: str, dir_name: str) -> str:
    if file_name.startswith('SKU图片_'):
        file_name = re.sub(r'^SKU图片_\d+_', '', file_name)
        file_name = re.sub(r'_\(\d+\)dollar', '', file_name)
        return file_name

    arr = re.findall(r'\((.*?)\)', file_name)
    if len(arr) > 0:
        nick = arr[0]
    else:
        if '自选备注' in dir_name:
            nick = dir_name
        else:
            file_index, file_name = split_number_prefix(file_name)
            nick = file_name.replace('-', '+')
            file_arr = nick.split('+')
            file_arr = sorted(file_arr)
            file_dict: Dict[str, int] = {}
            for file_item in file_arr:
                if file_item in file_dict.keys():
                    file_dict[file_item] += 1
                else:
                    file_dict[file_item] = 1
            nick_list = []
            for k, v in file_dict.items():
                if v == 1:
                    nick_list.append(k)
                else:
                    nick_list.append(f'{v}双{k}')
            nick = '+'.join(nick_list)
    return nick


def _normalize_debug_address(address: str) -> str:
    value = str(address or '').strip()
    if not value:
        return ''
    value = value.replace('localhost', '127.0.0.1')
    value = re.sub(r'^https?://', '', value, flags=re.IGNORECASE)
    value = re.sub(r'^wss?://', '', value, flags=re.IGNORECASE)
    return value.strip().strip('/')


def _is_local_debug_address(address: str) -> bool:
    normalized = _normalize_debug_address(address)
    if not normalized:
        return False
    host = normalized.split(':', 1)[0].strip().lower()
    return host in {'127.0.0.1', 'localhost', '::1', '[::1]'}


def _verify_debug_browser(address: str, timeout: float = 1.0) -> Dict[str, Any]:
    normalized = _normalize_debug_address(address)
    if not normalized:
        return {'ok': False, 'address': '', 'error': 'debug address is required'}

    request = Request(
        f'http://{normalized}/json/version',
        headers={'Connection': 'close', 'User-Agent': 'dyin-debug-browser-discovery'}
    )
    try:
        if _is_local_debug_address(normalized):
            opener = build_opener(ProxyHandler({}))
            response = opener.open(request, timeout=timeout)
        else:
            response = urlopen(request, timeout=timeout)
        with response:
            payload = json.loads(response.read().decode('utf-8', errors='replace'))
        return {
            'ok': True,
            'address': normalized,
            'browser': payload.get('Browser', ''),
            'user_agent': payload.get('User-Agent', ''),
            'websocket_debugger_url': payload.get('webSocketDebuggerUrl', ''),
        }
    except (URLError, HTTPError, TimeoutError, OSError, ValueError) as exc:
        return {
            'ok': False,
            'address': normalized,
            'error': str(exc),
        }


def _extract_remote_debug_address(cmdline: List[str]) -> str:
    host = '127.0.0.1'
    port = ''
    for index, raw_arg in enumerate(cmdline or []):
        arg = str(raw_arg or '').strip()
        if not arg:
            continue
        if arg.startswith('--remote-debugging-address='):
            host = arg.split('=', 1)[1].strip() or host
        elif arg == '--remote-debugging-address' and index + 1 < len(cmdline):
            host = str(cmdline[index + 1] or '').strip() or host
        elif arg.startswith('--remote-debugging-port='):
            port = arg.split('=', 1)[1].strip()
        elif arg == '--remote-debugging-port' and index + 1 < len(cmdline):
            port = str(cmdline[index + 1] or '').strip()

    if not port:
        return ''
    if host in ('0.0.0.0', '::', '[::]', ''):
        host = '127.0.0.1'
    return _normalize_debug_address(f'{host}:{port}')


def discover_debuggable_browsers(verify: bool = True) -> List[Dict[str, Any]]:
    browsers: List[Dict[str, Any]] = []
    seen_addresses = set()

    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            name = str(proc.info.get('name') or '').lower()
            if name not in _DEBUG_BROWSER_NAMES:
                continue

            cmdline = proc.info.get('cmdline') or []
            address = _extract_remote_debug_address(cmdline)
            if not address or address in seen_addresses:
                continue

            seen_addresses.add(address)
            item: Dict[str, Any] = {
                'browser_name': _DEBUG_BROWSER_NAMES.get(name, name),
                'process_name': name,
                'pid': proc.info.get('pid'),
                'debug_address': address,
                'profile_directory': '',
                'user_data_dir': '',
                'command_line': cmdline,
            }

            for raw_arg in cmdline:
                arg = str(raw_arg or '').strip()
                if arg.startswith('--profile-directory='):
                    item['profile_directory'] = arg.split('=', 1)[1].strip()
                elif arg.startswith('--user-data-dir='):
                    item['user_data_dir'] = arg.split('=', 1)[1].strip()

            if verify:
                item['verification'] = _verify_debug_browser(address)
            browsers.append(item)
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue

    browsers.sort(key=lambda item: (item.get('browser_name', ''), item.get('pid') or 0))
    return browsers


def attach_existing_debug_browser(debug_address: str, existing_only: bool = True) -> ChromiumPage:
    normalized_address = _normalize_debug_address(debug_address)
    if not normalized_address:
        raise ValueError('debug_address is required')

    verification = _verify_debug_browser(normalized_address)
    if not verification.get('ok'):
        raise Exception(f'Unable to connect to debug browser {normalized_address}: {verification.get("error")}')

    co = ChromiumOptions(read_file=False)
    co.set_address(normalized_address)
    if existing_only:
        co.existing_only()

    page = ChromiumPage(addr_or_opts=co)
    page.handle_alert(next_one=True)
    return page


def get_page(index_url):
    """创建ChromiumPage实例,支持自动Chrome管理"""
    co = ChromiumOptions()
    
    # [修复] 智能Chrome路径检测与下载
    try:
        # 1. 检查是否已有可用的Chrome
        chrome_path = get_chrome_path()
        
        if chrome_path:
            logger.info(f"[成功] 检测到Chrome: {chrome_path}")
            co.set_browser_path(chrome_path)
        else:
            # 2. 尝试自动下载Chrome
            logger.info("[处理] Chrome未检测到,尝试自动配置...")
            chrome_path = ensure_chrome_available()
            
            if chrome_path:
                logger.info(f"[成功] Chrome自动配置成功: {chrome_path}")
                co.set_browser_path(chrome_path)
            else:
                logger.warning("[警告] Chrome自动配置失败,使用系统默认配置")
                
    except Exception as e:
        logger.error(f"[失败] Chrome配置过程出错: {e}")
        logger.info("[处理] fallback到系统默认Chrome配置")
    
    # 基础配置
    co.set_pref(arg='credentials_enable_service', value=False)
    co.set_user() 
    
    # 额外优化配置
    co.set_argument('--disable-dev-shm-usage')  # 减少内存使用
    co.set_argument('--disable-gpu')  # 避免GPU相关问题
    co.set_argument('--disable-extensions')  # 禁用扩展提高性能
    co.set_argument('--disable-background-timer-throttling')  # 优化性能
    co.set_argument('--disable-features=VizDisplayCompositor')  # 兼容性优化
    
    try:
        page = ChromiumPage(addr_or_opts=co)
        page.set.window.max()
        page.handle_alert(next_one=True)
        page.get(index_url)
        logger.info("[成功] 浏览器页面创建成功")
        return page
        
    except Exception as e:
        logger.error(f"[失败] 浏览器启动失败: {e}")
        # 如果失败,尝试不指定Chrome路径的默认方式
        try:
            logger.info("[处理] 尝试使用默认配置...")
            co_fallback = ChromiumOptions()
            co_fallback.set_pref(arg='credentials_enable_service', value=False)
            co_fallback.set_user()
            
            page = ChromiumPage(addr_or_opts=co_fallback)
            page.set.window.max()
            page.handle_alert(next_one=True)
            page.get(index_url)
            logger.info("[成功] 使用默认配置成功创建浏览器")
            return page
            
        except Exception as e2:
            logger.error(f"[失败] 所有浏览器配置都失败: {e2}")
            raise Exception(f"无法启动浏览器,请检查Chrome安装状态.错误: {e2}")


def _collect_id_mode_three_four_candidates(base_dir: str, supported_formats: List[str]) -> List[str]:
    """ID 模式下为 3:4 主图收集候选文件。"""
    if not os.path.isdir(base_dir):
        return []

    candidates: List[str] = []
    normalized_formats = {fmt.lower() for fmt in supported_formats}
    try:
        for fname in sorted(os.listdir(base_dir)):
            fext = os.path.splitext(fname)[1].lower()
            if fext not in normalized_formats:
                continue
            fpath = os.path.join(base_dir, fname)
            try:
                with Image.open(fpath) as im:
                    width, height = im.size
                ratio = (width / height) if height else 0
            except Exception:
                continue
            if abs(ratio - 0.75) >= 0.03:
                continue
            candidates.append(fpath)
            if len(candidates) >= 5:
                break
    except Exception:
        return []

    return candidates


def get_pic_list(record, key: str) -> List[str]:
    """获取图片列表,使用硬编码的默认配置"""
    result = []
    # 注意：打包版为无控制台模式，避免大量 print 造成性能问题
    
    # 使用硬编码的默认配置
    if key == '800':
        folder_path = '主图/800'
    elif key == '750':
        folder_path = '主图/750'
    else:
        # 向后兼容,使用默认路径
        folder_path = f'主图/{key}' if record.type == 1 else '主图'
    
    # 支持的图片格式(硬编码默认值)
    supported_formats = ['.jpg', '.jpeg', '.png', '.webp']
    
    # 确定基础文件夹路径
    if record.type == 1:
        base_dir = os.path.join(record.path, folder_path)
    else:
        # ID模式使用不同的路径结构
        if key == '800':
            base_dir = os.path.join(record.path, '主图')
        elif key == '750':
            preferred_dir = os.path.join(record.path, '主图', '750')
            fallback_dir = os.path.join(record.path, '主图')
            base_dir = preferred_dir if os.path.isdir(preferred_dir) else fallback_dir
        else:
            base_dir = os.path.join(record.path, folder_path)

    # ID模式 3:4 主图：优先使用独立 750 目录；缺失时回退到主图目录中筛选 3:4 比例图片。
    if record.type != 1 and key == '750':
        candidates = _collect_id_mode_three_four_candidates(base_dir, supported_formats)
        if not candidates and os.path.normpath(base_dir) != os.path.normpath(os.path.join(record.path, '主图')):
            candidates = _collect_id_mode_three_four_candidates(os.path.join(record.path, '主图'), supported_formats)
        return candidates
    
    for i in range(5):
        file_path = None
        
        if record.type == 1:  # 标准模式
            if i == 0:
                # 尝试不同的命名方式
                possible_names = []
                for fmt in supported_formats or ['.jpg', '.png']:
                    fmt = fmt.lstrip('.')
                    possible_names.extend([
                        f'{key}.{fmt}',
                        f'{key}-1.{fmt}',
                        f'{key}-2.{fmt}'
                    ])
                
                for name in possible_names:
                    temp_path = os.path.join(base_dir, name)
                    if os.path.exists(temp_path):
                        file_path = temp_path
                        break
            else:
                # 对于后续的图片
                possible_names = []
                for fmt in supported_formats or ['.jpg', '.png']:
                    fmt = fmt.lstrip('.')
                    possible_names.extend([
                        f'{i + 1}.{fmt}',
                        f'0{i + 1}.{fmt}' if i + 1 < 10 else f'{i + 1}.{fmt}'
                    ])
                
                for name in possible_names:
                    temp_path = os.path.join(base_dir, name)
                    if os.path.exists(temp_path):
                        file_path = temp_path
                        break
        else:
            possible_names = []
            for fmt in supported_formats or ['.jpg', '.png']:
                fmt = fmt.lstrip('.')
                possible_names.extend([
                    f'主图_{i + 1}.{fmt}',
                    f'主图_0{i + 1}.{fmt}' if i + 1 < 10 else f'主图_{i + 1}.{fmt}'
                ])
            for name in possible_names:
                temp_path = os.path.join(base_dir, name)
                if os.path.exists(temp_path):
                    file_path = temp_path
                    break
        
        if file_path:
            result.append(file_path)
        else:
            pass
    
    # [修复] 修改策略:ID模式下,如果没有主图3:4,直接跳过不填充
    # 让平台使用自带的"从1:1主图一键填入"功能,避免触发裁剪工具
    if record.type == 2 and key == '750' and len(result) == 0:
        # 直接返回空列表,不抛出异常
        return []
    
    if len(result) < 1:
        raise Exception(f'未找到主图,至少需要一张主图!当前找到的图片数量:{len(result)}')

    return result


def get_detail_pic_list(record) -> List[str]:
    """获取详情图列表,使用硬编码的默认配置"""
    result = []
    
    # 使用硬编码的默认配置
    detail_folder = '详情图片'
    supported_formats = ['.jpg', '.jpeg', '.png', '.webp']
    filters = []
    
    # 根据记录类型确定详情图文件夹路径
    if record.type == 1:
        base_dir = os.path.join(record.path, detail_folder)
    else:
        base_dir = os.path.join(record.path, '详情页')
    
    # 如果设置的路径不存在,尝试兼容旧的路径
    if not os.path.exists(base_dir):
        fallback_dir = os.path.join(record.path, 'images')
        if os.path.exists(fallback_dir):
            base_dir = fallback_dir
        else:
            raise Exception(f'未找到详情图文件夹!尝试的路径:{base_dir}')
    
    def _natural_sort_key(name):
        """自然排序键: 将文件名中的数字作为整数排序，避免 10.jpg 排在 2.jpg 前面"""
        import re as _ns_re
        parts = _ns_re.split(r'(\d+)', name)
        return [int(p) if p.isdigit() else p.lower() for p in parts]

    for file_path in sorted(os.listdir(base_dir), key=_natural_sort_key):
        # 检查文件扩展名
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext in [fmt.lower() for fmt in supported_formats]:
            # 检查文件名过滤规则
            if not should_filter_file(file_path, filters):
                result.append(os.path.join(base_dir, file_path))

    if len(result) == 0:
        raise Exception('未找到详情图!!!')
    return result


def get_white_pic(record, sku_list, with_source: bool = False):
    def _result(path: str, is_fallback: bool):
        if with_source:
            return {
                'path': path,
                'is_fallback': is_fallback,
            }
        return path
    """获取白底图,支持多种格式和文件名"""
    # 使用硬编码的默认格式
    supported_formats = ['.jpg', '.jpeg', '.png', '.webp']
    
    # 尝试不同的文件名和格式
    possible_names = ['白底', 'white', 'WHITE', '白底图']
    
    for name in possible_names:
        for fmt in supported_formats:
            fmt = fmt.lstrip('.')
            
            if record.type == 1:
                # 标准模式:在主图文件夹中查找
                file_path = os.path.join(record.path, f'主图/{name}.{fmt}')
                if os.path.exists(file_path):
                    return _result(file_path, False)
                # 也在根目录查找
                file_path = os.path.join(record.path, f'{name}.{fmt}')
                if os.path.exists(file_path):
                    return _result(file_path, False)
            else:
                # ID模式:在根目录查找
                file_path = os.path.join(record.path, f'{name}.{fmt}')
                if os.path.exists(file_path):
                    return _result(file_path, False)
    
    # 如果没找到白底图,返回第一个SKU图片作为备用
    fallback_path = sku_list[0]['path'] if sku_list else ''
    return _result(fallback_path, True)


def get_diaopai_pic(record) -> Optional[str]:
    """获取吊牌图片,支持多种格式"""
    # 使用硬编码的默认格式
    supported_formats = ['.jpg', '.jpeg', '.png', '.webp']
    
    for fmt in supported_formats:
        fmt = fmt.lstrip('.')
        file_path = os.path.join(record.path, f'吊牌.{fmt}')
        if os.path.exists(file_path):
            return file_path
    
    return None


def get_my_video(record) -> Optional[str]:
    video_dir = os.path.join(record.path, '主图视频')
    if os.path.exists(video_dir):
        for root, dirs, files in os.walk(video_dir):
            for file in files:
                if file.lower().endswith('.mp4'):
                    return os.path.join(root, file)
    return None


# 配置日志
logging.basicConfig(level=logging.INFO)

# ... 这里保留原有的其他函数(caizhi_select、select_text、get_sex等)
# 由于篇幅限制,这些函数保持原样

# 全局变量：记录类目属性是否已展开，避免重复操作
_category_expanded = False


def _find_category_expand_button(new_tab, timeout: float = 0.12):
    selectors = [
        'xpath://span[contains(@class,"style_categoryFolderBtn__") and contains(text(),"展开更多")]',
        'xpath://div[contains(@class,"style_categoryFolderBtnWrapperNew__")]//span[contains(text(),"展开更多")]',
    ]
    for selector in selectors:
        try:
            elements = new_tab.eles(selector, timeout=timeout)
        except Exception:
            elements = []
        for element in elements:
            try:
                if element and element.states.is_displayed:
                    return element
            except Exception:
                continue
    return None

def _expand_category_more(new_tab, force: bool = False):
    """
    展开类目属性区域 - 优化版
    使用全局缓存避免重复展开操作，大幅减少等待时间
    
    Args:
        new_tab: 浏览器标签页对象
        force: 是否强制重新展开（用于页面刷新后）
    """
    global _category_expanded
    
    # 如果已展开且不强制，直接返回
    if _category_expanded and not force:
        return
    
    try:
        btn = _find_category_expand_button(new_tab, timeout=0.15)
        if btn:
            btn.scroll.to_center()
            clicked = False
            for action in (
                lambda: btn.click(by_js=True),
                lambda: btn.click(),
            ):
                try:
                    action()
                    clicked = True
                    break
                except Exception:
                    continue
            if clicked:
                _wait_until(
                    lambda: _find_category_expand_button(new_tab, timeout=0.05) is None,
                    timeout=0.4,
                    interval=0.03,
                )
            _category_expanded = _find_category_expand_button(new_tab, timeout=0.05) is None
        else:
            # 没找到按钮说明已经展开了
            _category_expanded = True
    except:
        _category_expanded = True  # 出错也标记为已处理，避免重复尝试


def reset_category_expanded_state():
    """重置类目展开状态（在新商品上传开始时调用）"""
    global _category_expanded
    _category_expanded = False


def caizhi_select(new_tab, key, value, index, field_id="面料材质", area=None):
    """
    设置材质属性（面料材质）
    
    Args:
        new_tab: 浏览器标签页对象
        key: 材质类型（如"棉"）
        value: 材质占比（如"100%"）
        index: 材质索引
    """
    func_start = _time.time()
    if area is None:
        _expand_category_more(new_tab)
    
    # 1) 选择材质（下拉）
    inputs = _material_comboboxes(area, timeout=0.05) if area else []
    if not inputs:
        try:
            inputs = new_tab.eles(f'xpath://div[@attr-field-id="{field_id}"]//input[@role="combobox"]', timeout=0.1)
        except Exception:
            inputs = []
    
    combo = None
    if inputs and len(inputs) > index:
        combo = inputs[index]
    else:
        try:
            combo = new_tab.ele(f'xpath://div[@attr-field-id="{field_id}"]//input[@role="combobox"]', timeout=0.15)
        except Exception:
            combo = None
    
    if combo:
        try:
            combo.scroll.to_center()
        except Exception:
            pass
        try:
            combo.click()
        except Exception:
            _run_interaction_recovery(new_tab, f'caizhi_select:{key}:open_retry')
            try:
                combo.click(by_js=True)
            except Exception:
                pass
        try:
            combo.clear()
        except Exception:
            pass
        try:
            combo.input(key)
            _wait_until(
                lambda: bool(new_tab.ele(f'xpath://div[contains(@class,"ecom-g-select-item-option-content") and contains(normalize-space(text()),"{key}")]', timeout=0.05))
                or str(combo.attr('value') or '').strip() == key,
                timeout=0.18,
                interval=0.03,
            )
        except Exception:
            pass

        option_selected = False
        option_selectors = [
            f'xpath://div[contains(@class,"ecom-g-select-item-option-content") and normalize-space(text())="{key}"]',
            f'xpath://div[contains(@class,"ecom-g-select-item-option-content") and starts-with(normalize-space(text()),"{key}")]',
            f'xpath://div[contains(@class,"ecom-g-select-item-option-content") and contains(normalize-space(text()),"{key}")]',
        ]

        def _try_select_option() -> bool:
            nonlocal option_selected
            for selector in option_selectors:
                try:
                    opt = new_tab.ele(selector, timeout=0.05)
                except Exception:
                    opt = None
                if not opt:
                    continue
                try:
                    opt.click(by_js=True)
                    option_selected = True
                    return True
                except Exception:
                    continue
            return False

        if not _try_select_option():
            _wait_until(_try_select_option, timeout=0.18, interval=0.03)
        if not option_selected:
            try:
                combo.input('\n')
            except Exception:
                pass
    
    # 2) 选择占比（可选）
    if value:
        texts = _material_ratio_inputs(area, timeout=0.05) if area else []
        if not texts:
            try:
                texts = new_tab.eles(
                    f'xpath://div[@attr-field-id="{field_id}"]//input[contains(@class,"ecom-g-input") and not(@role="combobox")]',
                    timeout=0.15
                )
            except Exception:
                texts = []
        if texts and len(texts) > index:
            try:
                texts[index].clear()
                texts[index].input(value)
                _wait_until(
                    lambda: str(texts[index].attr('value') or '').strip() == str(value),
                    timeout=0.2,
                    interval=0.03,
                )
            except Exception:
                pass
    
    timer_record('属性设置', f'材质-{key}', 0, _time.time() - func_start, True)


def select_text(new_tab, key, value, extra=None):
    """
    选择下拉属性 - 极速优化版
    
    优化策略:
    1. 使用最短超时时间（0.1s）
    2. 优先使用 attr-field-id 定位（最可靠）
    3. 减少不必要的等待
    
    Args:
        new_tab: 浏览器标签页对象
        key: 属性名称（如"品牌"、"适用人群"）
        value: 要选择的值（如"无品牌"、"成人"）
        extra: 备用值
    """
    func_start = _time.time()
    _expand_category_more(new_tab)
    
    # 优先级1: 通过 attr-field-id 定位（最快最准）
    input_element = None
    try:
        input_element = new_tab.ele(f'xpath://div[@attr-field-id="{key}"]//input', timeout=0.1)
    except:
        pass
    
    # 优先级2: 其他选择器
    if not input_element:
        backup_selectors = [
            f'xpath://span[text()="{key}"]/../../..//input',
            f'xpath://span[text()="{key}"]/ancestor::div[contains(@class,"ecom-g-form-item")]//input',
        ]
        for selector in backup_selectors:
            try:
                input_element = new_tab.ele(selector, timeout=0.1)
                if input_element and input_element.states.is_displayed:
                    break
            except:
                input_element = None
                continue
    
    if not input_element:
        print(f'未找到字段:{key}')
        timer_record('属性设置', f'{key}(未找到)', 0, _time.time() - func_start, False)
        return
        
    print(f'选择{key} -> {value}')
    _run_interaction_recovery(new_tab, f'select_text:{key}:open')
    input_element.click()

    dropdown_selector = 'xpath://div[contains(@class,"ecom-g-select-dropdown") and not(contains(@class,"hidden"))]'
    _wait_until(
        lambda: bool(new_tab.ele(dropdown_selector, timeout=0.05)),
        timeout=0.6,
        interval=0.03,
    )

    # 查找下拉菜单（只用一个选择器）
    dropdown_menu = None
    try:
        dropdown_menu = new_tab.ele(dropdown_selector, timeout=0.1)
    except:
        pass
    
    if dropdown_menu and dropdown_menu.states.is_displayed:
        # 直接查找选项（使用最精确的选择器）
        try:
            option = dropdown_menu.ele(f'xpath:.//div[@class="ecom-g-select-item-option-content"][text()="{value}"]', timeout=0.1)
            if option and option.states.is_displayed:
                _run_interaction_recovery(new_tab, f'select_text:{key}:choose_exact')
                option.click()
                _wait_until(
                    lambda: (str(input_element.attr('value') or '').strip() in {str(value), str(extra or '')})
                    or (not bool(new_tab.ele(dropdown_selector, timeout=0.05))),
                    timeout=0.6,
                    interval=0.03,
                )
                timer_record('属性设置', f'{key}={value}', 0, _time.time() - func_start, True)
                return
        except:
            pass
        
        # 备用：模糊匹配
        try:
            option = dropdown_menu.ele(f'xpath:.//*[text()="{value}"]', timeout=0.1)
            if option and option.states.is_displayed:
                _run_interaction_recovery(new_tab, f'select_text:{key}:choose_fuzzy')
                option.click()
                _wait_until(
                    lambda: (str(input_element.attr('value') or '').strip() in {str(value), str(extra or '')})
                    or (not bool(new_tab.ele(dropdown_selector, timeout=0.05))),
                    timeout=0.6,
                    interval=0.03,
                )
                timer_record('属性设置', f'{key}={value}', 0, _time.time() - func_start, True)
                return
        except:
            pass
        
        # 尝试备用值
        if extra:
            try:
                option = dropdown_menu.ele(f'xpath:.//*[text()="{extra}"]', timeout=0.1)
                if option and option.states.is_displayed:
                    _run_interaction_recovery(new_tab, f'select_text:{key}:choose_extra')
                    option.click()
                    _wait_until(
                        lambda: str(input_element.attr('value') or '').strip() == str(extra)
                        or (not bool(new_tab.ele(dropdown_selector, timeout=0.05))),
                        timeout=0.6,
                        interval=0.03,
                    )
                    timer_record('属性设置', f'{key}={extra}', 0, _time.time() - func_start, True)
                    return
            except:
                pass
            print(f'未在下拉菜单中找到选项:{value} 或 {extra}')
        else:
            print(f'未在下拉菜单中找到选项:{value}')
    else:
        print('未找到下拉菜单')
    timer_record('属性设置', f'{key}(失败)', 0, _time.time() - func_start, False)


def get_sex(title):
    if '男' in title and '女' in title:
        return '通用'
    if '男' not in title and '女' not in title:
        return '通用'
    if '男' in title:
        return '男'
    else:
        return '女'


def handle_crop_popup(new_tab):
    """
    如果出现图片裁剪弹窗,则点击3次"-"按钮缩放到0.8,然后点击"确定".
    如果未出现弹窗,则快速返回.
    优化版：减少等待时间
    """
    try:
        # 快速判断是否出现裁剪弹窗
        crop_title = new_tab.ele(
            'xpath://div[@class="ecom-g-modal-title" and contains(text(),"图片裁剪")]',
            timeout=0.2  # 优化：减少超时
        )
        if not crop_title:
            return False
    except Exception:
        return False

    try:
        # 查找 "-" 按钮
        minus_btn = new_tab.ele(
            'xpath://div[contains(@class,"styles_zoom")]//button[1]',
            timeout=0.2  # 优化：减少超时
        )
        if minus_btn:
            # 优化：快速连续点击3次，不等待
            for _ in range(3):
                minus_btn.click()
                _time.sleep(0.03)

        # 点击 "确定" 按钮
        confirm_btn = new_tab.ele(
            'xpath://div[@class="ecom-g-modal-footer"]//button[contains(.,"确定")]',
            timeout=0.3  # 优化：减少超时
        )
        if confirm_btn:
            confirm_btn.click(by_js=True)
            _wait_until(lambda: not _is_crop_popup_visible(new_tab), timeout=1.0, interval=0.03)
        return True

    except Exception as e:
        print(f"处理裁剪弹窗异常:{e}")
        return False


def _is_crop_popup_visible(new_tab) -> bool:
    selectors = [
        'xpath://div[@class="ecom-g-modal-title" and contains(text(),"图片裁剪")]',
        'xpath://div[contains(@class,"ecom-g-modal")][.//*[contains(normalize-space(.),"图片裁剪")]]',
    ]
    for selector in selectors:
        try:
            modal = new_tab.ele(selector, timeout=0.05)
        except Exception:
            modal = None
        if not modal:
            continue
        try:
            if modal.states.is_displayed:
                return True
        except Exception:
            continue
    return False


def _main_image_smart_crop_prompt_selectors() -> List[str]:
    return [
        'xpath://div[@role="dialog"][.//*[contains(normalize-space(.),"是否需要为你智能裁剪为1:1主图")]]',
        'xpath://div[@role="dialog"][.//*[contains(normalize-space(.),"智能裁剪为1:1主图")]]',
        'xpath://div[contains(@class,"ecom-g-modal")][.//*[contains(normalize-space(.),"是否需要为你智能裁剪为1:1主图")]]',
        'xpath://div[contains(@class,"ecom-g-modal")][.//*[contains(normalize-space(.),"智能裁剪为1:1主图")]]',
        'xpath://div[contains(@class,"ecom-g-modal")][.//*[contains(normalize-space(.),"当前还有") and contains(normalize-space(.),"不是1:1比例")]]',
    ]


def _is_main_image_smart_crop_prompt_visible(new_tab) -> bool:
    return bool(_wait_for_first_visible(new_tab, _main_image_smart_crop_prompt_selectors(), timeout=0.05, interval=0.01))


def handle_main_image_smart_crop_prompt(new_tab, timeout: float = 0.2) -> bool:
    """处理主图上传后的 1:1 智能裁剪确认弹窗。"""
    prompt_selectors = _main_image_smart_crop_prompt_selectors()
    confirm_selectors = [
        'xpath:.//button[.//span[normalize-space(.)="确定"]]',
        'xpath:.//*[normalize-space(.)="确定"]/ancestor::button[1]',
    ]

    modal = _wait_for_first_visible(new_tab, prompt_selectors, timeout=timeout, interval=0.05)
    if not modal:
        return False

    confirm_btn = None
    for selector in confirm_selectors:
        try:
            btn = modal.ele(selector, timeout=0.1)
        except Exception:
            btn = None
        if btn and btn.states.is_displayed:
            confirm_btn = btn
            break

    if not confirm_btn:
        print('检测到1:1主图智能裁剪弹窗，但未找到“确定”按钮')
        return False

    try:
        confirm_btn.click(by_js=True)
    except Exception:
        try:
            confirm_btn.click()
        except Exception as e:
            print(f'点击1:1主图智能裁剪弹窗“确定”失败: {e}')
            return False

    _wait_until(
        lambda: not _wait_for_first_visible(new_tab, prompt_selectors, timeout=0.05, interval=0.01),
        timeout=0.5,
        interval=0.03,
    )
    print('已自动确认1:1主图智能裁剪弹窗')
    return True


def _find_ai_material_tool_panel(new_tab, timeout: float = 0.2):
    panel_selectors = [
        'xpath://div[contains(@class,"auxo-drawer-wrapper-body")][.//*[contains(normalize-space(.),"AI素材工具")]]',
        'xpath://div[contains(@class,"ecom-g-modal")][.//*[contains(normalize-space(.),"AI素材工具")]]',
        'xpath://div[contains(@class,"drawer") or contains(@class,"Drawer")][.//*[contains(normalize-space(.),"AI素材工具")]]',
        'xpath://div[.//*[contains(normalize-space(.),"AI素材工具")] and (.//*[contains(normalize-space(.),"全部上传")] or .//*[contains(normalize-space(.),"上传")])]',
    ]
    return _wait_for_first_visible(new_tab, panel_selectors, timeout=timeout, interval=0.05)


def _click_text_button(container, texts, timeout_each: float = 0.08):
    for text in texts:
        selectors = [
            f'xpath:.//button[normalize-space(.)="{text}" or .//span[normalize-space(.)="{text}"]]',
            f'xpath:.//*[normalize-space(.)="{text}"]/ancestor::button[1]',
        ]
        for selector in selectors:
            try:
                btn = container.ele(selector, timeout=timeout_each)
            except Exception:
                btn = None
            if not btn:
                continue
            try:
                if not btn.states.is_displayed:
                    continue
                btn_class = (btn.attr('class') or '').lower()
                if 'disabled' in btn_class:
                    continue
            except Exception:
                pass
            try:
                btn.click(by_js=True)
            except Exception:
                try:
                    btn.click()
                except Exception:
                    continue
            return text
    return ''


def close_ai_material_tool_panel(new_tab, timeout: float = 0.2) -> bool:
    """关闭 AI素材工具 面板，避免遮挡后续 SKU 上传区域。"""
    panel = _find_ai_material_tool_panel(new_tab, timeout=timeout)
    if not panel:
        return False

    close_selectors = [
        'xpath:.//button[contains(@class,"auxo-drawer-close")]',
        'xpath:.//button[@aria-label="Close" or @aria-label="关闭"]',
        'xpath:.//*[contains(@class,"anticon-close")]/ancestor::button[1]',
        'xpath:.//button[contains(@title,"关闭") or contains(@aria-label,"close") or contains(@aria-label,"Close")]',
    ]

    for selector in close_selectors:
        try:
            btn = panel.ele(selector, timeout=0.08)
        except Exception:
            btn = None
        if not btn:
            continue
        try:
            btn.click(by_js=True)
        except Exception:
            try:
                btn.click()
            except Exception:
                continue
        if _wait_until(
            lambda: not _find_ai_material_tool_panel(new_tab, timeout=0.05),
            timeout=0.5,
            interval=0.03,
        ):
            print('已关闭AI素材工具面板')
            return True
    return False


def handle_main_image_ai_tool_upload(new_tab, timeout: float = 0.2) -> bool:
    """处理 AI素材工具 面板中的“全部上传/上传”按钮。"""
    panel = _find_ai_material_tool_panel(new_tab, timeout=timeout)
    if not panel:
        return False

    clicked_text = _click_text_button(panel, ('全部上传', '上传'))
    if not clicked_text:
        print('检测到AI素材工具面板，但未找到“全部上传/上传”按钮')
        return False

    _wait_until(
        lambda: _is_upload_busy(new_tab) or not _find_ai_material_tool_panel(new_tab, timeout=0.05),
        timeout=0.6,
        interval=0.03,
    )
    print(f'已触发AI素材工具“{clicked_text}”')
    return True


def handle_white_bg_ai_tool_upload(new_tab, timeout: float = 0.3) -> bool:
    """处理白底图阶段 AI素材工具：优先应用，再上传。"""
    panel = _find_ai_material_tool_panel(new_tab, timeout=timeout)
    if not panel:
        return False

    white_related = False
    for marker in ('白底图', '一键抠图', '无损放大'):
        try:
            if panel.ele(f'xpath:.//*[contains(normalize-space(.),"{marker}")]', timeout=0.05):
                white_related = True
                break
        except Exception:
            pass
    if not white_related:
        return False

    before_effect = _get_ai_white_bg_effect_state(new_tab).get('effect_src', '')
    if not _click_white_bg_cutout_apply(panel):
        print('检测到白底图AI素材工具面板，但未找到“一键抠图 > 白底图”的应用按钮')
        return False

    if not _wait_until(
        lambda: _ai_white_bg_effect_ready(new_tab, before_effect),
        timeout=25.0,
        interval=0.2,
    ):
        state = _get_ai_white_bg_effect_state(new_tab)
        print(f'白底图AI效果图尚未生成完成，暂不点击上传: {state}')
        return False

    clicked_text = ''

    def _click_white_bg_upload_once() -> bool:
        nonlocal clicked_text
        panel_now = _find_ai_material_tool_panel(new_tab, timeout=0.05)
        if not panel_now:
            return False
        clicked_text = _click_ai_material_footer_upload(panel_now) or _click_text_button(panel_now, ('上传', '全部上传'))
        return bool(clicked_text)

    if not _click_white_bg_upload_once():
        _wait_until(_click_white_bg_upload_once, timeout=0.4, interval=0.03)
    if not clicked_text:
        print('检测到白底图AI素材工具面板，但未找到“上传”按钮')
        return False

    _wait_until(
        lambda: _is_upload_busy(new_tab) or not _find_ai_material_tool_panel(new_tab, timeout=0.05),
        timeout=0.8,
        interval=0.03,
    )
    print(f'已触发白底图AI素材工具“{clicked_text}”，等待平台完成白底图处理')
    return True


def _click_white_bg_cutout_apply(panel) -> bool:
    selectors = (
        'xpath:.//*[normalize-space(.)="一键抠图"]/ancestor::*[contains(@class,"itemWrapper")][1]//button[.//span[normalize-space(.)="应用"] or normalize-space(.)="应用"]',
        'xpath:.//*[contains(normalize-space(.),"一键抠图") and contains(normalize-space(.),"白底图")]/descendant::button[.//span[normalize-space(.)="应用"] or normalize-space(.)="应用"]',
    )
    for selector in selectors:
        try:
            buttons = panel.eles(selector, timeout=0.08) or []
        except Exception:
            buttons = []
        for btn in buttons:
            try:
                btn_class = (btn.attr('class') or '').lower()
                if not btn.states.is_displayed or 'disabled' in btn_class or btn.attr('disabled') is not None:
                    continue
                btn.click(by_js=True)
                return True
            except Exception:
                try:
                    btn.click()
                    return True
                except Exception:
                    continue
    return False


def _click_ai_material_footer_upload(panel) -> str:
    selectors = (
        'xpath:.//*[contains(@class,"footerWrapper") or contains(@class,"actionsWrapper")]//button[.//span[normalize-space(.)="上传"] or normalize-space(.)="上传"]',
        'xpath:.//button[.//span[normalize-space(.)="上传"] or normalize-space(.)="上传"]',
    )
    for selector in selectors:
        try:
            buttons = panel.eles(selector, timeout=0.08) or []
        except Exception:
            buttons = []
        for btn in buttons:
            try:
                btn_class = (btn.attr('class') or '').lower()
                if not btn.states.is_displayed or 'disabled' in btn_class or btn.attr('disabled') is not None:
                    continue
                btn.click(by_js=True)
                return '上传'
            except Exception:
                try:
                    btn.click()
                    return '上传'
                except Exception:
                    continue
    return ''


def _get_ai_white_bg_effect_state(tab) -> dict:
    js = r'''
return (() => {
  const isVisible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity || 1) > 0.01;
  };
  const hasHiddenAncestor = (el, root) => {
    let cur = el;
    while (cur && cur !== root) {
      if (String(cur.className || '').includes('hide')) return true;
      cur = cur.parentElement;
    }
    return false;
  };
  const panel = [...document.querySelectorAll('.auxo-drawer,.ecom-g-modal,[class*="drawer"],[class*="Drawer"]')]
    .find(el => isVisible(el) && String(el.innerText || '').includes('AI素材工具'));
  if (!panel) return { ready: false, reason: 'no_panel' };

  const busyTexts = [...panel.querySelectorAll('*')]
    .filter(el => isVisible(el) && !hasHiddenAncestor(el, panel) && /效果生成中|请耐心等待|生成中|处理中|识别中/.test(String(el.innerText || el.textContent || '')))
    .map(el => String(el.innerText || el.textContent || '').trim())
    .filter(Boolean);

  const compare = panel.querySelector('[class*="compareWrapper"]');
  const normalize = (src) => String(src || '').replace(/^\/\//, 'https://').split('~tplv')[0].split('?')[0];
  const images = compare
    ? [...compare.querySelectorAll('img')]
        .map(img => normalize(img.currentSrc || img.src || img.getAttribute('src') || img.getAttribute('srcset') || ''))
        .filter(src => src.includes('ecom-shop-material'))
    : [];
  const distinct = [...new Set(images)].filter(Boolean);
  const original = distinct[0] || '';
  const effect = distinct.find((src, index) => index > 0 && src !== original) || '';

  const footerUpload = [...panel.querySelectorAll('button')]
    .find(btn => isVisible(btn) && String(btn.innerText || '').trim() === '上传');
  const uploadEnabled = !!footerUpload && !footerUpload.disabled && !String(footerUpload.className || '').includes('disabled');

  return {
    ready: busyTexts.length === 0 && !!effect && uploadEnabled,
    reason: busyTexts.length ? 'effect_generating' : (!effect ? 'effect_missing' : (!uploadEnabled ? 'upload_disabled' : 'ready')),
    busy_texts: busyTexts.slice(0, 3),
    original_src: original,
    effect_src: effect,
    upload_enabled: uploadEnabled,
    image_count: distinct.length
  };
})()
'''
    try:
        state = tab.run_js(js)
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def _ai_white_bg_effect_ready(tab, previous_effect_src: str = '') -> bool:
    state = _get_ai_white_bg_effect_state(tab)
    if not state.get('ready'):
        return False
    effect_src = str(state.get('effect_src') or '')
    if previous_effect_src and effect_src == previous_effect_src:
        return False
    return True


_WHITE_BG_BLOCKING_TEXTS = (
    '图片存在“非白底”问题',
    '图片存在"非白底"问题',
    '非白底',
    '请上传其他白底图',
)
_WHITE_BG_PROCESSING_TEXTS = ('识别中', '处理中', '审核中', '上传中', '生成中', '应用中')


def _get_white_bg_field(tab, timeout: float = 0.08):
    try:
        return tab.ele('xpath://div[@attr-field-id="白底图"]', timeout=timeout)
    except Exception:
        return None


def _scope_has_text(scope, texts, timeout: float = 0.03) -> bool:
    if not scope:
        return False
    for text in texts:
        try:
            if scope.ele(f'xpath:.//*[contains(normalize-space(.),"{text}")]', timeout=timeout):
                return True
        except Exception:
            pass
    return False


def _page_has_text(tab, texts, timeout: float = 0.03) -> bool:
    for text in texts:
        try:
            if tab.ele(f'xpath://*[contains(normalize-space(.),"{text}")]', timeout=timeout):
                return True
        except Exception:
            pass
    return False


def _white_bg_has_blocking_issue(tab) -> bool:
    field = _get_white_bg_field(tab, timeout=0.05)
    if _scope_has_text(field, _WHITE_BG_BLOCKING_TEXTS):
        return True
    return _page_has_text(tab, ('图片存在“非白底”问题', '图片存在"非白底"问题'), timeout=0.03)


def _white_bg_is_processing(tab) -> bool:
    if _is_upload_busy(tab):
        return True
    field = _get_white_bg_field(tab, timeout=0.05)
    if _scope_has_text(field, _WHITE_BG_PROCESSING_TEXTS):
        return True
    panel = _find_ai_material_tool_panel(tab, timeout=0.03)
    return _scope_has_text(panel, _WHITE_BG_PROCESSING_TEXTS, timeout=0.02)


def wait_white_bg_processing_complete(tab, timeout: float = 30.0, interval: float = 0.2, min_wait: float = 3.0) -> bool:
    """等待白底图上传后的平台识别/自动处理结束。"""
    start = _time.time()
    stable_checks = 0
    saw_processing = False

    while _time.time() - start < timeout:
        if _white_bg_has_blocking_issue(tab):
            return False

        if _white_bg_is_processing(tab):
            saw_processing = True
            stable_checks = 0
            _time.sleep(interval)
            continue

        if _time.time() - start < min_wait:
            _time.sleep(interval)
            continue

        stable_checks += 1
        if stable_checks >= (3 if saw_processing else 4):
            return True
        _time.sleep(interval)

    return not _white_bg_has_blocking_issue(tab)


def handle_main_image_post_upload_prompts(new_tab, timeout: float = 8.0) -> bool:
    """主图上传后处理弹窗链：AI素材工具 -> 全部上传 -> 1:1智能裁剪确认。"""
    start = _time.time()
    idle_checks = 0
    handled_any = False
    seen_prompt = False

    while _time.time() - start < timeout:
        acted = False
        try:
            if handle_main_image_ai_tool_upload(new_tab, timeout=0.12):
                acted = True
                handled_any = True
        except Exception:
            pass

        try:
            if handle_main_image_smart_crop_prompt(new_tab, timeout=0.12):
                acted = True
                handled_any = True
        except Exception:
            pass

        if not acted:
            try:
                if _find_ai_material_tool_panel(new_tab, timeout=0.05):
                    seen_prompt = True
            except Exception:
                pass
            try:
                if _is_upload_busy(new_tab):
                    seen_prompt = True
            except Exception:
                pass

        if acted:
            seen_prompt = True
            idle_checks = 0
            continue

        idle_checks += 1
        if idle_checks >= (1 if not seen_prompt else 3):
            break
        _time.sleep(0.03)

    return handled_any


def handle_white_bg_post_upload_prompts(new_tab, timeout: float = 6.0) -> bool:
    """白底图上传后处理 AI素材工具侧边栏与残留确认弹窗。"""
    start = _time.time()
    idle_checks = 0
    handled_any = False
    seen_prompt = False
    white_action_done = False

    while _time.time() - start < timeout:
        acted = False
        try:
            if not white_action_done and handle_white_bg_ai_tool_upload(new_tab, timeout=0.12):
                acted = True
                handled_any = True
                white_action_done = True
        except Exception:
            pass

        try:
            if handle_main_image_smart_crop_prompt(new_tab, timeout=0.1):
                acted = True
                handled_any = True
        except Exception:
            pass

        if not acted:
            try:
                if _find_ai_material_tool_panel(new_tab, timeout=0.05):
                    seen_prompt = True
            except Exception:
                pass
            try:
                if _is_upload_busy(new_tab):
                    seen_prompt = True
            except Exception:
                pass

        if acted:
            seen_prompt = True
            idle_checks = 0
            continue

        idle_checks += 1
        if idle_checks >= (1 if not seen_prompt else 3):
            break
        _time.sleep(0.03)

    return handled_any


def smart_find_upload_button(tab, context="SKU"):
    """
    智能查找"本地上传"按钮 - 优化版
    
    根据2026年抖音页面结构优化，使用精确的 class 选择器提高速度和稳定性
    
    Args:
        tab: 页面标签页对象
        context: 上下文信息,用于更精确的定位（'主图'、'SKU'、'白底图'、'吊牌'、'主图视频'等）
        
    Returns:
        找到的按钮元素,如果未找到返回None
    """
    print(f"[检查] 智能查找'{context}'上传按钮...")
    
    # ========== 优先级1: 精确选择器（只接受真正的“本地上传”文件输入）==========
    precise_selectors = list(_SKU_LOCAL_UPLOAD_LABEL_SELECTORS) if context == 'SKU' else []

    if precise_selectors:
        element = _find_first_visible_upload_label(
            tab,
            precise_selectors,
            timeout=0.3,
            require_enabled=False,
        )
        if element:
            print("  [成功] 精确定位: SKU本地上传label")
            return element
    
    # ========== 优先级2: 根据上下文的选择器 ==========
    upload_selectors = []
    
    if context == '主图':
        upload_selectors = [
            # 新版页面 - saotu 区域中的上传按钮
            'xpath://div[@id="saotu"]//label[.//input[@type="file"]]',
            'xpath://div[@id="saotu"]//label[contains(@class,"material-upload-button") and .//input[@type="file"]]',
            'xpath://div[contains(@class,"ecom-g-popover")]//label[.//input[@type="file"] and contains(normalize-space(.),"本地上传")]',
        ]
    elif context == 'SKU':
        upload_selectors = list(_SKU_LOCAL_UPLOAD_CONTEXT_SELECTORS)
    else:
        # 通用选择器（白底图、吊牌、视频等）
        upload_selectors = [
            'xpath://div[contains(@class,"ecom-g-popover")]//label[.//input[@type="file"] and contains(normalize-space(.),"本地上传")]',
            'xpath://div[contains(@class,"ecom-g-popover-inner-content")]//label[.//input[@type="file"] and contains(normalize-space(.),"本地上传")]',
            'xpath://label[.//input[@type="file"] and contains(normalize-space(.),"本地上传")]',
        ]

    # 尝试上下文选择器
    element = _find_first_visible_upload_label(
        tab,
        upload_selectors,
        timeout=0.8,
        require_enabled=True,
    )
    if element:
        print(f"  [成功] 上下文定位: {context}")
        return element
    
    # ========== 优先级3: 备用选择器（仍然必须是“本地上传”而不是“本地替换”）==========
    fallback_selectors = [
        'xpath://label[.//input[@type="file"] and .//*[contains(normalize-space(.),"本地上传")]]',
        'xpath://*[contains(normalize-space(.),"本地上传")]/ancestor::label[1][.//input[@type="file"]]',
        'xpath://div[contains(normalize-space(.),"本地上传")]',
    ]
    
    for selector in fallback_selectors:
        try:
            elements = tab.eles(selector, timeout=0.5)
            for element in elements:
                try:
                    text = element.text.strip() if element.text else ''
                    if '本地上传' in text:
                        if element.states.is_displayed:
                            print(f"  [成功] 备用定位: '{text}'")
                            return element
                except:
                    continue
        except:
            continue
    
    print(f"  [失败] 未找到'{context}'上传按钮")
    return None


def _wait_until(predicate, timeout=2, interval=0.05):
    """轮询直到条件满足"""
    start = _time.time()
    while _time.time() - start < timeout:
        try:
            if predicate():
                return True
        except:
            pass
        _time.sleep(interval)
    return False


def _wait_upload_paths_inputted(new_tab, timeout: Optional[float] = None) -> bool:
    if timeout is None:
        return bool(new_tab.wait.upload_paths_inputted())

    original_timeout = None
    try:
        original_timeout = new_tab.timeout
        new_tab.set.timeouts(base=timeout)
        return bool(new_tab.wait.upload_paths_inputted())
    except Exception:
        return False
    finally:
        if original_timeout is not None:
            try:
                new_tab.set.timeouts(base=original_timeout)
            except Exception:
                pass


def _get_visible_elements(tab, selector, timeout=0.1):
    """获取当前可见元素列表"""
    try:
        return [el for el in tab.eles(selector, timeout=timeout) if el and el.states.is_displayed]
    except:
        return []


def _wait_for_first_visible(tab, selectors, timeout=2.0, interval=0.1):
    start = _time.time()
    while _time.time() - start < timeout:
        for selector in selectors:
            try:
                element = tab.ele(selector, timeout=0.1)
                if element and element.states.is_displayed:
                    return element
            except:
                pass
        _time.sleep(interval)
    return None


def _wait_for_first_visible_in_scope(scope, selectors, timeout=0.6, interval=0.05):
    start = _time.time()
    while _time.time() - start < timeout:
        for selector in selectors:
            try:
                elements = scope.eles(selector, timeout=0.05)
            except Exception:
                elements = []
            for element in elements:
                try:
                    if element and element.states.is_displayed:
                        return element
                except Exception:
                    continue
        _time.sleep(interval)
    return None


def _is_upload_busy(tab):
    try:
        if tab.ele('xpath://span[contains(@class,"ecom-g-btn-loading-icon")]', timeout=0.1):
            return True
    except:
        pass
    try:
        if tab.ele('上传中', timeout=0.1):
            return True
    except:
        pass
    return False


def _wait_for_upload_complete(tab, timeout=90.0, interval=0.08):
    start = _time.time()
    seen_busy = False
    seen_reaction = False
    idle_checks = 0
    while _time.time() - start < timeout:
        panel_visible = bool(_find_ai_material_tool_panel(tab, timeout=0.05))
        crop_visible = _is_crop_popup_visible(tab)
        smart_crop_visible = _is_main_image_smart_crop_prompt_visible(tab)

        try:
            if panel_visible:
                seen_reaction = True
                handle_main_image_ai_tool_upload(tab, timeout=0.08)
                handle_white_bg_ai_tool_upload(tab, timeout=0.08)
        except Exception:
            pass
        try:
            if crop_visible or smart_crop_visible:
                seen_reaction = True
                handle_main_image_smart_crop_prompt(tab, timeout=0.08)
        except Exception:
            pass

        panel_visible = bool(_find_ai_material_tool_panel(tab, timeout=0.05))
        crop_visible = _is_crop_popup_visible(tab)
        smart_crop_visible = _is_main_image_smart_crop_prompt_visible(tab)
        busy = _is_upload_busy(tab)
        if busy or panel_visible or crop_visible or smart_crop_visible:
            seen_busy = True
            idle_checks = 0
        else:
            idle_checks += 1
            if idle_checks >= (1 if (seen_busy or seen_reaction) else 2):
                return True
        _time.sleep(interval)
    return False


def _count_scope_visible_images(scope) -> int:
    if not scope:
        return 0
    selectors = (
        'xpath:.//img[not(starts-with(@src,"data:image/"))]',
        'xpath:.//img',
    )
    seen = set()
    count = 0
    for selector in selectors:
        try:
            elements = scope.eles(selector, timeout=0.05)
        except Exception:
            elements = []
        for element in elements:
            try:
                if not element or not element.states.is_displayed:
                    continue
                backend_id = id(element)
                if backend_id in seen:
                    continue
                seen.add(backend_id)
                count += 1
            except Exception:
                continue
        if count:
            return count
    return count


def _collect_scope_visible_image_signatures(scope):
    if not scope:
        return set()
    signatures = set()
    selectors = (
        'xpath:.//img[not(starts-with(@src,"data:image/"))]',
        'xpath:.//img',
    )
    for selector in selectors:
        try:
            elements = scope.eles(selector, timeout=0.05)
        except Exception:
            elements = []
        for element in elements:
            try:
                if not element or not element.states.is_displayed:
                    continue
                src = str(element.attr('src') or '').strip()
                alt = str(element.attr('alt') or '').strip()
                cls = str(element.attr('class') or '').strip()
                if not src and not alt and not cls:
                    continue
                signatures.add((src, alt, cls))
            except Exception:
                continue
        if signatures:
            return signatures
    return signatures


def _is_scope_upload_busy(scope) -> bool:
    if not scope:
        return False
    selectors = (
        'xpath:.//span[contains(@class,"ecom-g-btn-loading-icon")]',
        'xpath:.//*[contains(normalize-space(.),"上传中")]',
    )
    for selector in selectors:
        try:
            elements = scope.eles(selector, timeout=0.05)
        except Exception:
            elements = []
        for element in elements:
            try:
                if element and element.states.is_displayed:
                    return True
            except Exception:
                continue
    return False


def _wait_for_sku_upload_settled(
    new_tab,
    row_scope=None,
    before_image_count: Optional[int] = None,
    before_image_signatures=None,
    timeout=8.0,
    interval=0.03,
):
    start = _time.time()
    seen_reaction = False
    idle_checks = 0
    grace_until = start + 0.18
    preview_seen_at = None

    while _time.time() - start < timeout:
        crop_visible = _is_crop_popup_visible(new_tab)
        if crop_visible:
            seen_reaction = True
            idle_checks = 0
            preview_seen_at = None
            try:
                handle_crop_popup(new_tab)
            except Exception:
                pass
            _time.sleep(max(0.03, interval))
            continue

        panel = None
        try:
            panel = _find_ai_material_tool_panel(new_tab, timeout=0.05)
        except Exception:
            panel = None
        if panel:
            seen_reaction = True
            idle_checks = 0
            preview_seen_at = None
            try:
                close_ai_material_tool_panel(new_tab, timeout=0.08)
            except Exception:
                pass
            _time.sleep(max(0.03, interval))
            continue

        scope_busy = _is_scope_upload_busy(row_scope)
        busy = scope_busy or _is_upload_busy(new_tab)
        current_image_count = _count_scope_visible_images(row_scope)
        current_image_signatures = _collect_scope_visible_image_signatures(row_scope)
        preview_progressed = (
            before_image_count is not None
            and row_scope is not None
            and current_image_count > before_image_count
        )
        preview_changed = (
            before_image_signatures is not None
            and row_scope is not None
            and current_image_signatures != before_image_signatures
        )
        if busy:
            seen_reaction = True
            idle_checks = 0
            preview_seen_at = None
            _time.sleep(interval)
            continue

        if preview_progressed or preview_changed:
            seen_reaction = True
            if preview_seen_at is None:
                preview_seen_at = _time.time()
            elif _time.time() - preview_seen_at >= max(0.02, interval):
                return True
            _time.sleep(interval)
            continue

        if not seen_reaction and _time.time() < grace_until:
            _time.sleep(interval)
            continue

        idle_checks += 1
        if idle_checks >= 1:
            return True
        _time.sleep(interval)

    try:
        print(
            'SKU upload settle timeout: '
            f'busy={_is_upload_busy(new_tab)} '
            f'scope_busy={_is_scope_upload_busy(row_scope)} '
            f'before_count={before_image_count} '
            f'current_count={_count_scope_visible_images(row_scope)} '
            f'before_signatures={len(before_image_signatures or [])} '
            f'current_signatures={len(_collect_scope_visible_image_signatures(row_scope))}'
        )
    except Exception:
        pass
    return False


def _find_direct_target_upload_label(target_area_element):
    if not target_area_element:
        return None
    selectors = (
        'xpath:.//div[contains(@class,"material-upload-button")]//label[.//input[@type="file"]][1]',
        'xpath:.//*[contains(@class,"material-preview-button")][.//input[@type="file"]][1]',
        'xpath:.//input[@type="file"]/ancestor::*[contains(@class,"material-preview-button")][1]',
        'xpath:.//input[@type="file"]/ancestor::*[@role="button"][1]',
        'xpath:.//label[contains(@class,"index-module_button__")][.//input[@type="file"]][1]',
        'xpath:.//label[.//input[@type="file"]][1]',
        'xpath:(.//input[@type="file"])[1]',
    )
    for selector in selectors:
        try:
            element = target_area_element.ele(selector, timeout=0.08)
        except Exception:
            element = None
        if not element:
            continue
        try:
            if element.states.is_displayed:
                return element
        except Exception:
            continue
    return None


def _xpath_literal(value: str) -> str:
    """安全拼接 XPath 字符串"""
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ', "\'", '.join([f"'{part}'" for part in parts]) + ")"


def _find_sku_local_upload_button(new_tab):
    """
    颜色分类悬停后的 Popover 内「本地上传」。
    与 smart_find_upload_button 中精确定位一致：避免仅用 normalize-space(text())=\"本地上传\"
    时子节点换行/嵌套 span 导致匹配失败（多 SKU、靠下几行时更易触发）。
    """
    return _find_first_visible_upload_label(
        new_tab,
        _SKU_LOCAL_UPLOAD_LABEL_SELECTORS,
        timeout=0.3,
        require_enabled=False,
    )


def set_sku_info(new_tab, index, sku, remark):
    print(f'设置第{index + 1}个sku -> {sku["name"]}')
    sku_timer_start = _time.time()

    try:
        sku_name = str(sku.get("name") or "").strip()
        if not sku_name:
            raise Exception("SKU名称为空")

        step_start = _time.time()
        before_spec_count = _sku_spec_input_visible_count(new_tab)
        before_value_count = _sku_confirmed_value_count(new_tab)

        color_inputs = _get_visible_elements(new_tab, 'xpath://div[@id="skuValue-颜色分类"]//input', timeout=0.2)
        if not color_inputs:
            raise Exception("未找到颜色分类输入框")
        color_inputs[-1].scroll.to_center()
        color_inputs[-1].click(by_js=True)

        add_btn = new_tab.ele(f'xpath:{new_btn_xpath}', timeout=0.8)
        if not add_btn:
            raise Exception("未找到添加规格按钮")
        add_btn.click(by_js=True)
        timer_record('SKU阶段', f'{index + 1}-打开新增规格', 0, _time.time() - step_start, True)

        spec_input = None

        step_start = _time.time()
        def _probe_spec_input():
            nonlocal spec_input
            inputs = _get_visible_elements(new_tab, _SKU_SPEC_INPUT_XPATH, timeout=0.05)
            if not inputs:
                return False
            if len(inputs) > before_spec_count:
                spec_input = inputs[-1]
                return True
            spec_input = inputs[-1]
            return spec_input.states.is_displayed

        if not _wait_until(_probe_spec_input, timeout=0.6, interval=0.04) or not spec_input:
            raise Exception("未找到规格值输入框")

        spec_input.click(by_js=True)
        spec_input.input(sku_name, clear=True)

        if not _wait_until(
            lambda: (spec_input.attr("value") or "").strip() == sku_name,
            timeout=0.35,
            interval=0.03
        ):
            raise Exception(f'规格值 "{sku_name}" 未成功写入')
        timer_record('SKU阶段', f'{index + 1}-写入规格值', 0, _time.time() - step_start, True)

        step_start = _time.time()
        _sku_finish_spec_confirmation(new_tab, sku_name, before_spec_count, before_value_count)
        timer_record('SKU阶段', f'{index + 1}-确认规格值', 0, _time.time() - step_start, True)

        remark_text = str(remark or '').strip()
        if remark_text:
            remark_inputs = _get_visible_elements(new_tab, _SKU_REMARK_INPUT_XPATH, timeout=0.1)
            if remark_inputs:
                remark_inputs[-1].input(remark_text + '\n')
                _time.sleep(0.01)

        literal = _xpath_literal(sku_name)
        sku_anchor_selector = f'xpath://div[@id="skuValue-颜色分类"]//*[contains(normalize-space(.), {literal})]'
        sku_anchor = _find_sku_anchor_by_index(new_tab, index)

        step_start = _time.time()
        def _probe_sku_anchor():
            nonlocal sku_anchor
            sku_anchor = _find_sku_anchor_by_index(new_tab, index)
            if sku_anchor:
                return True
            anchor = new_tab.ele(sku_anchor_selector, timeout=0.05)
            if anchor and anchor.states.is_displayed:
                sku_anchor = anchor
                return True
            return False

        if not _wait_until(_probe_sku_anchor, timeout=0.5, interval=0.03):
            raise Exception(f'未找到 SKU "{sku_name}" 对应的悬停元素')
        timer_record('SKU阶段', f'{index + 1}-定位SKU行', 0, _time.time() - step_start, True)

        # 多规格时下方行常在视口外或未挂载完整，先滚整块「颜色分类」再滚锚点，避免悬停无 Popover
        try:
            sku_block = new_tab.ele('xpath://div[@id="skuValue-颜色分类"]', timeout=0.2)
            if sku_block:
                sku_block.scroll.to_see()
        except Exception:
            pass
        try:
            sku_anchor.scroll.to_see()
            sku_anchor.scroll.to_center()
        except Exception:
            pass

        row_scope = _find_sku_row_scope(sku_anchor)
        hover_target = row_scope or sku_anchor
        before_row_image_count = _count_scope_visible_images(row_scope)
        before_row_image_signatures = _collect_scope_visible_image_signatures(row_scope)

        step_start = _time.time()
        upload_button = _sku_resolve_local_upload_label(new_tab, row_scope, sku_anchor, hover_target)
        if not upload_button:
            def _probe_upload_button():
                nonlocal upload_button
                upload_button = _find_sku_direct_upload_label(row_scope)
                if upload_button:
                    return True
                upload_button = _find_sku_upload_trigger_in_scope(row_scope)
                try:
                    if upload_button and upload_button.states.is_displayed:
                        return True
                except Exception:
                    upload_button = None
                upload_button = _find_sku_local_upload_button(new_tab)
                try:
                    return bool(upload_button and upload_button.states.is_displayed)
                except Exception:
                    upload_button = None
                    return False

            if not _wait_until(_probe_upload_button, timeout=0.25, interval=0.03):
                upload_button = None

        if not upload_button:
            print(f'SKU图片上传跳过(未启用规格图): {sku_name}')
        else:
            timer_record('SKU阶段', f'{index + 1}-定位上传入口', 0, _time.time() - step_start, True)

            sku_image_path = str(sku.get('path') or '').strip()
            if not sku_image_path or not os.path.isfile(sku_image_path):
                print(f'SKU图片路径无效,跳过上传: {sku_image_path!r}')
            else:
                new_tab.set.upload_files(sku_image_path)
                try:
                    upload_button.click(by_js=True)
                except Exception:
                    try:
                        upload_button.click()
                    except Exception as exc:
                        raise Exception(f'SKU 上传按钮点击失败: {exc}')

                step_start = _time.time()
                new_tab.wait.upload_paths_inputted()
                timer_record('SKU阶段', f'{index + 1}-触发上传', 0, _time.time() - step_start, True)
                settle_timer_start = _time.time()
                # 已触发上传, 快速检查后立即继续下一个SKU(页面异步处理)
                _time.sleep(0.3)  # 给上传触发留时间
        timer_record('SKU阶段', f'{index + 1}-上传触发完成', 0, _time.time() - step_start, True)
        timer_record('SKU阶段', f'{index + 1}-上传并收尾', 0, _time.time() - step_start, True)
        timer_record('SKU阶段', f'{index + 1}-总计', 0, _time.time() - sku_timer_start, True)
        print(f"[成功] SKU {index + 1} 设置完成")

    except Exception as e:
        error_msg = f"[失败] 设置SKU {index + 1}失败: {str(e)}"
        timer_record('SKU阶段', f'{index + 1}-失败', 0, _time.time() - sku_timer_start, False)
        print(error_msg)
        traceback.print_exc()
        # 非致命: 继续处理下一个SKU而非中断整个流程

def _ensure_section_ready(new_tab, section_label: str, timeout: float = 10.0):
    return _wait_until(
        lambda: bool(new_tab.ele(f'xpath://div[@attr-field-id="{section_label}"]', timeout=0.1))
        or bool(new_tab.ele('xpath://div[contains(@class,"index-module_batchImageUpload")]', timeout=0.1)),
        timeout=timeout,
        interval=0.05,
    )


def upload_file(
    new_tab,
    file_list: List[str],
    key: str,
    extra: bool = False,
    error_size: Union[bool, str] = False,
    target_field_id: str = None,
    wait_for_finish: bool = True,
) -> None:
    """
    上传文件到抖音商品发布页面（完全恢复原版逻辑）
    
    Args:
        new_tab: 浏览器标签页对象
        file_list: 文件路径列表
        key: 上传区域标识（如"主图"、"主图视频"）
        extra: 是否为详情图上传模式
        error_size: 错误尺寸提示（用于处理裁剪）
        target_field_id: 目标区域的 attr-field-id（如"主图3:4"），用于精确定位
        wait_for_finish: 是否等待上传完成或裁剪完成
    """
    print(f'开始上传{key}... (共{len(file_list)}个文件)')

    # 检查文件列表是否为空
    if not file_list:
        print(f'没有需要上传的 {key},跳过此步骤.')
        return

    # 判断文件是否存在
    if not os.path.exists(file_list[0]):
        print(f'文件 {file_list[0]} 不存在,跳过上传 {key}')
        return

    fast_mode = not wait_for_finish
    is_detail_target = bool(extra or target_field_id == '商品详情')
    trigger_wait = 0.01 if fast_mode else (0.03 if is_detail_target else 0.05)
    post_trigger_wait = 0.01 if fast_mode else (0.03 if is_detail_target else 0.05)
    size_error_timeout = 0.05 if fast_mode else 0.3

    # 根据 key 设置不同的 key_value
    if key == '主图视频':
        key_value = key
    else:
        key_value = f'上传{key}'

    # ========== 定位并悬浮到上传区域 ==========
    locate_step_start = _time.time()
    target_area_element = None  # 用于在指定区域内查找上传按钮
    upload_label = None
    
    if target_field_id:
        # 使用 attr-field-id 精确定位（用于 3:4 主图等特定区域）
        print(f'  使用 attr-field-id="{target_field_id}" 定位上传区域')
        target_area_element = new_tab.ele(f'xpath://div[@attr-field-id="{target_field_id}"]', timeout=3)
        if target_area_element:
            target_area_element.scroll.to_see()
            target_area_element.scroll.to_center()
            new_tab.scroll.up(50)
            
            upload_label = _find_direct_target_upload_label(target_area_element)
            if upload_label:
                try:
                    upload_label.scroll.to_see()
                except Exception:
                    pass
                print(f'  已在"{target_field_id}"区域直接找到上传入口')
            else:
                try:
                    target_area_element.hover()
                except Exception:
                    pass
                _wait_until(
                    lambda: _find_direct_target_upload_label(target_area_element) is not None,
                    timeout=0.4 if is_detail_target else 0.3,
                    interval=0.03,
                )
                upload_label = _find_direct_target_upload_label(target_area_element)
                if upload_label:
                    print(f'  已在"{target_field_id}"区域悬停后找到上传入口')
        else:
            raise Exception(f'未找到 attr-field-id="{target_field_id}" 区域')
    
    if not target_field_id:
        if extra:
            # 详情图上传模式
            upload_anchor = new_tab.ele(f'xpath://span[text()="{key_value}"]', timeout=1.5)
            if upload_anchor:
                upload_anchor.scroll.to_center()
            detail_decoration = new_tab.ele('xpath://div[contains(text(),"商详装修")]', timeout=1.0)
            if detail_decoration:
                detail_decoration.scroll.to_see()
            if upload_anchor:
                try:
                    upload_anchor.hover()
                except Exception:
                    pass
        else:
            # 标准上传模式（与原版完全一致）
            upload_anchor = new_tab.ele(f'xpath://div[text()="{key_value}"]', timeout=1.5)
            if upload_anchor:
                upload_anchor.scroll.to_center()
            new_tab.scroll.up(30)
            if upload_anchor:
                try:
                    upload_anchor.hover()
                except Exception:
                    pass

    timer_record('上传子步骤', f'{key}-定位入口', 0, _time.time() - locate_step_start, True)

    # ========== 智能查找并点击"本地上传"按钮 ==========
    upload_button = upload_label if (target_area_element and upload_label) else None
    upload_triggered = False
    file_inputs = []
    
    # 如果指定了目标区域，优先在该区域内直接点击 label 触发文件选择
    if target_area_element and not upload_button:
        print(f'  在 "{target_field_id}" 区域内直接触发上传...')
        
        # 方案1：直接在目标区域找到 input[type="file"] 并触发
        try:
            file_input_selectors = [
                'xpath:.//div[contains(@class,"material-upload-button")]//input[@type="file"]',
                'xpath:.//label[.//input[@type="file"]]//input[@type="file"]',
                'xpath:.//input[@type="file"]',
            ]
            for selector in file_input_selectors:
                file_inputs = target_area_element.eles(selector, timeout=0.3 if target_field_id == '商品详情' else 1)
                if file_inputs:
                    break
            if file_inputs and len(file_inputs) > 0:
                # 直接使用第一个文件输入框
                print(f'  [成功] 在"{target_field_id}"区域内找到文件输入框，直接触发上传')
                # 文件已经通过 set.upload_files 设置，现在点击 label 触发
                first_label = None
                for selector in (
                    'xpath:.//div[contains(@class,"material-upload-button")]//label',
                    'xpath:.//label[.//input[@type="file"]]',
                ):
                    first_label = target_area_element.ele(selector, timeout=0.2 if target_field_id == '商品详情' else 1)
                    if first_label:
                        break
                if first_label:
                    upload_button = first_label
                else:
                    upload_button = file_inputs[0]
                    print(f'  [成功] 在"{target_field_id}"区域内改用隐藏文件输入框触发上传')
        except Exception as e:
            print(f'  方案1失败: {e}')
        
        # 方案2：检查是否有弹窗出现（hover后可能出现popover）
        if not upload_button:
            popover_selectors = [
                'xpath://div[contains(@class,"ecom-g-popover-inner-content")]//label[contains(text(),"本地上传")]',
                'xpath://label[contains(@class,"index-module_actionBefore")]',
                'xpath://label[text()="本地上传"]',
                'xpath://div[text()="本地上传"]',
            ]
            for selector in popover_selectors:
                try:
                    btn = new_tab.ele(selector, timeout=0.2 if is_detail_target else 0.5)
                    if btn and btn.states.is_displayed:
                        upload_button = btn
                        print(f'  [成功] 在弹窗中找到本地上传按钮')
                        break
                except:
                    continue
    
    # 如果还没找到，使用智能查找
    if not upload_button and not target_field_id:
        upload_button = smart_find_upload_button(new_tab, key)

    if target_field_id and not upload_button:
        raise Exception(f'未能在 "{target_field_id}" 区域内定位上传按钮')
    
    if not upload_triggered and upload_button:
        print(f'  设置上传文件列表: {len(file_list)}个')
        for i, f in enumerate(file_list):
            print(f'    [{i+1}] {os.path.basename(f)}')
        new_tab.set.upload_files(file_list)
        print(f"[成功] 智能定位成功,点击{key}上传按钮...")
        try:
            upload_button.click(by_js=True)
            upload_triggered = True
        except Exception:
            try:
                upload_button.click()
                upload_triggered = True
            except Exception as exc:
                raise Exception(f'{key} 上传按钮点击失败: {exc}')
    elif not upload_button:
        # 备用策略：尝试原始的查找方式（与原版完全一致）
        print(f"[警告] 智能查找失败,尝试备用方案...")
        print(f'  设置上传文件列表: {len(file_list)}个')
        for i, f in enumerate(file_list):
            print(f'    [{i+1}] {os.path.basename(f)}')
        new_tab.set.upload_files(file_list)
        found_backup = False
        for upload_btn in new_tab.eles('xpath://div[text()="本地上传"]'):
            try:
                upload_btn.click()
                found_backup = True
                break
            except:
                pass
        
        if not found_backup:
            print(f"[失败] 无法找到{key}的'本地上传'按钮")
            return  # 直接返回,不抛出异常
    
    # 等待文件路径注入完成（与原版完全一致）
    trigger_step_start = _time.time()
    paths_wait_timeout = 1.0 if fast_mode else None
    paths_inputted = _wait_upload_paths_inputted(new_tab, timeout=paths_wait_timeout)
    if not paths_inputted:
        print(f"[提示] {key}上传文件路径未在短等待内确认，按异步上传流程继续")
    _wait_until(
        lambda: _is_upload_busy(new_tab)
        or _is_crop_popup_visible(new_tab)
        or (error_size and bool(_wait_for_first_visible(new_tab, [
                f'xpath://div[contains(text(),"{error_size}")]',
                f'xpath://div[text()="{error_size}"]',
            ], timeout=0.05, interval=0.01))),
        timeout=max(trigger_wait + post_trigger_wait, 0.01),
        interval=0.01,
    )
    timer_record('上传子步骤', f'{key}-触发上传', 0, _time.time() - trigger_step_start, True)
    
    print(f"[OK] {key}上传已触发，共{len(file_list)}个文件")

    if not wait_for_finish:
        if error_size:
            try:
                size_error = _wait_for_first_visible(new_tab, [
                    f'xpath://div[contains(text(),"{error_size}")]',
                    f'xpath://div[text()="{error_size}"]',
                ], timeout=size_error_timeout, interval=0.02)
            except Exception:
                size_error = None
            if not size_error:
                return
            print(f'检测到{key}存在尺寸提示，继续执行完整等待处理')
        else:
            return

    # 处理需要裁剪的情况（与原版完全一致）
    if error_size:
        # 如果是3:4主图，先确保页面区域就绪
        if isinstance(error_size, str) and '3:4' in error_size:
            _ensure_section_ready(new_tab, '主图3:4', timeout=12.0)
        # 构建宽松匹配的 size error 选择器 (兼容完整/部分文本)
        size_error_selectors = [
            f'xpath://div[contains(text(),"{error_size}")]',
            f'xpath://div[text()="{error_size}"]',
        ]
        for i in range(3):
            if i > 0:
                size_error_elem = _wait_for_first_visible(new_tab, size_error_selectors, timeout=0.15, interval=0.02)
                if not size_error_elem:
                    break
                try:
                    size_error_elem.ele('xpath:./../..//img/../..', timeout=0.1).hover()
                except Exception:
                    pass
                ai_change_bg_btn = _wait_for_first_visible(new_tab, [
                    'xpath://div[text()="AI换背景"]',
                    'xpath://div[contains(text(),"AI换背景")]',
                ], timeout=0.3, interval=0.03)
                if ai_change_bg_btn:
                    ai_change_bg_btn.click(by_js=True)
                    _wait_until(
                        lambda: bool(_wait_for_first_visible(new_tab, ['xpath://span[text()="应用"]/..', 'xpath://span[contains(text(),"应用")]/..'], timeout=0.05, interval=0.01)),
                        timeout=0.4,
                        interval=0.03,
                    )
                else:
                    break
            apply_btn_curr = _wait_for_first_visible(new_tab, [
                'xpath://span[text()="应用"]/..',
                'xpath://span[contains(text(),"应用")]/..',
                'xpath://button[contains(.,"应用")]',
            ], timeout=0.8, interval=0.05)
            if not apply_btn_curr:
                break
            print('遇到需要裁剪，点击应用...')
            apply_btn_curr.click(by_js=True)
            footer_selectors = [
                'xpath://button[contains(@class,"ecom-g-btn-primary")]//span[text()="上传"]/..',
                'xpath://span[text()="上传"]/parent::button[contains(@class,"ecom-g-btn-primary")]',
                'xpath://div[contains(@class,"footerWrapper")]//button[contains(@class,"ecom-g-btn-primary")]',
                'xpath://div[contains(@class,"footer")]//span[text()="上传"]/..',
                'xpath://div[contains(@class,"modal")]//button[contains(@class,"primary")]//span[text()="上传"]/..',
                'xpath://button[contains(.,"上传") and contains(@class,"primary")]',
            ]
            upload_btn = _wait_for_first_visible(new_tab, footer_selectors, timeout=0.5, interval=0.04)
            if upload_btn:
                upload_btn.click(by_js=True)
                btn_class = upload_btn.attr('class') or ''
                if 'disabled' in btn_class:
                    try:
                        new_tab.run_js('arguments[0].click();', upload_btn)
                    except:
                        pass
            else:
                print('警告: 未找到上传按钮')
        wait_complete_start = _time.time()
        upload_flag = _wait_for_upload_complete(new_tab, timeout=90.0, interval=0.06)
        if not upload_flag:
            raise Exception(f'上传{key}超时失败!')
        timer_record('上传子步骤', f'{key}-等待完成', 0, _time.time() - wait_complete_start, True)
        print(f'上传{key}成功!')

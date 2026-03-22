# -*- coding: utf-8 -*-
# mypy: ignore-errors
# pyright: reportOptionalMemberAccess=false, reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportGeneralTypeIssues=false
# type: ignore

import json
import os
import re
import time as _time
from datetime import datetime
from DrissionPage import ChromiumOptions, ChromiumPage  # type: ignore
from flask_jwt_extended import create_access_token
import logging
from src import constants
from typing import Union, Optional, List, Dict, Any
import traceback
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
            if seconds < 0.6:
                _time.sleep(max(0.1, min(seconds, 0.25)))
            elif seconds <= 1.0:
                _time.sleep(0.4)
            else:
                _time.sleep(seconds)
        except Exception:
            _time.sleep(seconds)
        
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
        area = new_tab.ele(f'xpath://div[@attr-field-id="{field_id}"]', timeout=timeout)
    except Exception:
        area = None

    if not area:
        return False

    try:
        area.scroll.to_center()
    except Exception:
        pass
    time.sleep(0.1)

    selectors = [
        f'xpath:.//button[.//*[normalize-space(text())="{action_text}"]]',
        f'xpath:.//*[normalize-space(text())="{action_text}"]/ancestor::button[1]',
        f'xpath:.//*[normalize-space(text())="{action_text}"]/ancestor::div[contains(@class,"styles-module_wrapper__")][1]',
        f'xpath:.//*[normalize-space(text())="{action_text}"]/ancestor::div[contains(@class,"style_modifyButton__")][1]',
        f'xpath:.//*[normalize-space(text())="{action_text}"]',
    ]

    for selector in selectors:
        try:
            target = area.ele(selector, timeout=0.5)
        except Exception:
            target = None
        if not target:
            continue

        class_name = (target.attr('class') or '').lower()
        if 'disabled' in class_name:
            continue

        try:
            target.click(by_js=True)
            return True
        except Exception:
            continue

    return False


def set_material_composition(new_tab, materials) -> bool:
    if not materials:
        return True

    try:
        area = new_tab.ele('xpath://div[@attr-field-id="面料材质"]', timeout=1)
    except Exception:
        area = None

    if not area:
        print('未找到面料材质区域')
        return False

    try:
        area.scroll.to_center()
    except Exception:
        pass
    time.sleep(0.1)

    try:
        del_btns = area.eles('xpath:.//span[contains(@class,"styles_del__")]', timeout=0.3)
    except Exception:
        del_btns = []
    for del_btn in reversed(del_btns):
        try:
            del_btn.click(by_js=True)
            time.sleep(0.1)
        except Exception:
            pass

    for idx in range(1, len(materials)):
        try:
            combo_count = len(area.eles('xpath:.//input[@role="combobox"]', timeout=0.3))
        except Exception:
            combo_count = 0
        if combo_count >= idx + 1:
            continue
        if not click_field_action(new_tab, '面料材质', '添加材质'):
            print(f'未找到第{idx + 1}组面料的添加材质按钮')
            return False
        time.sleep(0.1)

    for idx, material in enumerate(materials):
        name = str(material[0]).strip()
        ratio = '' if len(material) < 2 or material[1] is None else str(material[1]).strip()
        caizhi_select(new_tab, name, ratio, idx)
        time.sleep(0.05)

    return True

new_btn_xpath = '//div[not(contains(@class,"ecom-g-cascader-menus-hidden"))]/div/div[@style="padding-bottom: 8px;"]/div[starts-with(@class,"styles_addSKUName__")]/span'


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
    def _result(path: str, is_fallback: bool):
        if with_source:
            return {
                'path': path,
                'is_fallback': is_fallback,
            }
        return path

    def _result(path: str, is_fallback: bool):
        if with_source:
            return {
                'path': path,
                'is_fallback': is_fallback,
            }
        return path

    def _result(path: str, is_fallback: bool):
        if with_source:
            return {
                'path': path,
                'is_fallback': is_fallback,
            }
        return path
    
    # 确定基础文件夹路径
    if record.type == 1:
        base_dir = os.path.join(record.path, folder_path)
    else:
        # ID模式使用不同的路径结构
        if key == '800':
            base_dir = os.path.join(record.path, '主图')
        elif key == '750':
            # [性能修复] ID模式下不强制要求 3:4 主图；若没有单独的 750 目录则直接跳过，
            # 避免在主图目录对大量 1:1 图片做重复扫描（打包环境下会非常慢）
            preferred_dir = os.path.join(record.path, '主图', '750')
            if not os.path.isdir(preferred_dir):
                return []
            base_dir = preferred_dir
        else:
            base_dir = os.path.join(record.path, folder_path)

    # ID模式 3:4 主图：直接取前 5 张，不做图片打开与比例判断（避免严重卡顿）
    if record.type != 1 and key == '750':
        if not os.path.isdir(base_dir):
            return []
        candidates: List[str] = []
        try:
            for fname in sorted(os.listdir(base_dir)):
                fext = os.path.splitext(fname)[1].lower()
                if fext in [fmt.lower() for fmt in supported_formats]:
                    candidates.append(os.path.join(base_dir, fname))
                    if len(candidates) >= 5:
                        break
        except Exception:
            return []
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
        fallback_dir = os.path.join(record.path, 'images' if record.type == 1 else 'images')
        if os.path.exists(fallback_dir):
            base_dir = fallback_dir
        else:
            raise Exception(f'未找到详情图文件夹!尝试的路径:{base_dir}')
    
    for file_path in os.listdir(base_dir):
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
        btn = new_tab.ele('xpath://span[contains(@class,"style_categoryFolderBtn__") and contains(text(),"展开更多")]', timeout=0.3)
        if not btn:
            btn = new_tab.ele('xpath://div[contains(@class,"style_categoryFolderBtnWrapperNew__")]//span[contains(text(),"展开更多")]', timeout=0.3)
        if btn and btn.states.is_displayed:
            btn.scroll.to_center()
            time.sleep(0.1)
            btn.click(by_js=True)
            time.sleep(0.2)
            _category_expanded = True
        else:
            # 没找到按钮说明已经展开了
            _category_expanded = True
    except:
        _category_expanded = True  # 出错也标记为已处理，避免重复尝试


def reset_category_expanded_state():
    """重置类目展开状态（在新商品上传开始时调用）"""
    global _category_expanded
    _category_expanded = False


def caizhi_select(new_tab, key, value, index):
    """
    设置材质属性（面料材质）
    
    Args:
        new_tab: 浏览器标签页对象
        key: 材质类型（如"棉"）
        value: 材质占比（如"100%"）
        index: 材质索引
    """
    func_start = _time.time()
    _expand_category_more(new_tab)
    
    # 1) 选择材质（下拉）
    try:
        inputs = new_tab.eles('xpath://div[@attr-field-id="面料材质"]//input[@role="combobox"]', timeout=0.3)
    except Exception:
        inputs = []
    
    combo = None
    if inputs and len(inputs) > index:
        combo = inputs[index]
    else:
        try:
            combo = new_tab.ele('xpath://div[@attr-field-id="面料材质"]//input[@role="combobox"]', timeout=0.3)
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
            pass
        try:
            combo.clear()
        except Exception:
            pass
        try:
            combo.input(key)
            _time.sleep(0.05)
        except Exception:
            pass
        
        # 点击下拉选项
        try:
            opt = new_tab.ele(
                f'xpath://div[contains(@class,"ecom-g-select-item-option-content") and normalize-space(text())="{key}"]',
                timeout=0.8
            )
            if opt:
                opt.click(by_js=True)
        except Exception:
            pass
    
    # 2) 选择占比（可选）
    if value:
        try:
            texts = new_tab.eles('xpath://div[@attr-field-id="面料材质"]//input[@class="ecom-g-input"]', timeout=0.6)
        except Exception:
            texts = []
        if texts and len(texts) > index:
            try:
                texts[index].clear()
                texts[index].input(value)
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
    input_element.click()
    time.sleep(0.1)  # 极短等待
    
    # 查找下拉菜单（只用一个选择器）
    dropdown_menu = None
    try:
        dropdown_menu = new_tab.ele('xpath://div[contains(@class,"ecom-g-select-dropdown") and not(contains(@class,"hidden"))]', timeout=0.2)
    except:
        pass
    
    if dropdown_menu and dropdown_menu.states.is_displayed:
        # 直接查找选项（使用最精确的选择器）
        try:
            option = dropdown_menu.ele(f'xpath:.//div[@class="ecom-g-select-item-option-content"][text()="{value}"]', timeout=0.1)
            if option and option.states.is_displayed:
                option.click()
                time.sleep(0.1)
                timer_record('属性设置', f'{key}={value}', 0, _time.time() - func_start, True)
                return
        except:
            pass
        
        # 备用：模糊匹配
        try:
            option = dropdown_menu.ele(f'xpath:.//*[text()="{value}"]', timeout=0.1)
            if option and option.states.is_displayed:
                option.click()
                time.sleep(0.1)
                timer_record('属性设置', f'{key}={value}', 0, _time.time() - func_start, True)
                return
        except:
            pass
        
        # 尝试备用值
        if extra:
            try:
                option = dropdown_menu.ele(f'xpath:.//*[text()="{extra}"]', timeout=0.1)
                if option and option.states.is_displayed:
                    option.click()
                    time.sleep(0.1)
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
    time.sleep(0.1)


def _select_text_legacy(new_tab, key, value, extra=None):
    """旧版 select_text 函数（备用）"""
    func_start = _time.time()
    _expand_category_more(new_tab)
    
    input_selectors = [
        f'xpath://div[@attr-field-id="{key}"]//input',
        f'xpath://span[text()="{key}"]/../../..//input',
    ]
    
    input_element = None
    for selector in input_selectors:
        try:
            input_element = new_tab.ele(selector, timeout=0.2)
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
    input_element.click()
    time.sleep(0.15)
    
    dropdown_selectors = [
        'xpath://div[contains(@class,"ecom-g-select-dropdown") and not(contains(@class,"hidden"))]',
    ]
    
    dropdown_menu = None
    for selector in dropdown_selectors:
        try:
            dropdown_menu = new_tab.ele(selector, timeout=0.2)
            if dropdown_menu and dropdown_menu.states.is_displayed:
                break
        except:
            dropdown_menu = None
            continue
    
    if dropdown_menu:
        option_selectors = [
            f'xpath:.//div[@class="ecom-g-select-item-option-content"][text()="{value}"]',
            f'xpath:.//*[text()="{value}"]',
        ]
        
        option = None
        for opt_sel in option_selectors:
            try:
                option = dropdown_menu.ele(opt_sel, timeout=0.1)
                if option and option.states.is_displayed:
                    option.click()
                    time.sleep(0.1)
                    timer_record('属性设置', f'{key}={value}', 0, _time.time() - func_start, True)
                    return
            except:
                continue
        
        if extra:
            try:
                option = dropdown_menu.ele(f'xpath:.//*[text()="{extra}"]', timeout=0.1)
                if option and option.states.is_displayed:
                    option.click()
                    time.sleep(0.1)
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
    time.sleep(0.1)


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
            return  # 快速返回，不打印日志
    except:
        return

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
                time.sleep(0.05)  # 优化：0.2s -> 0.05s

        # 点击 "确定" 按钮
        confirm_btn = new_tab.ele(
            'xpath://div[@class="ecom-g-modal-footer"]//button[contains(.,"确定")]',
            timeout=0.3  # 优化：减少超时
        )
        if confirm_btn:
            confirm_btn.click(by_js=True)
            time.sleep(0.15)  # 优化：0.5s -> 0.15s

    except Exception as e:
        print(f"处理裁剪弹窗异常:{e}")


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
    
    # ========== 优先级1: 精确选择器（基于实际DOM结构）==========
    # 新版抖音页面的"本地上传"按钮位于 popover 弹窗中
    # 精确 class: label.index-module_actionBefore__VyHLB
    precise_selectors = [
        # 最精确的选择器 - 弹窗中的"本地上传" label
        'xpath://label[contains(@class,"index-module_actionBefore")]',
        # 弹窗容器中的本地上传
        'xpath://div[contains(@class,"ecom-g-popover-inner-content")]//label[contains(text(),"本地上传")]',
        'xpath://div[contains(@class,"popover-inner-content")]//label[1]',
    ]
    
    # 快速尝试精确选择器（超时更短）
    for selector in precise_selectors:
        try:
            element = tab.ele(selector, timeout=0.5)
            if element and element.states.is_displayed:
                print(f"  [成功] 精确定位: {selector}")
                return element
        except:
            continue
    
    # ========== 优先级2: 根据上下文的选择器 ==========
    upload_selectors = []
    
    if context == '主图':
        upload_selectors = [
            # 新版页面 - saotu 区域中的上传按钮
            'xpath://div[@id="saotu"]//label[contains(@class,"index-module_button")][1]',
            'xpath://div[@id="saotu"]//label[contains(@class,"material-upload-button")]',
            # 弹窗中的本地上传（文本匹配）
            'xpath://label[text()="本地上传"]',
            'xpath://div[text()="本地上传"]',
        ]
    elif context == 'SKU':
        upload_selectors = [
            # SKU 规格图上传
            'xpath://div[@id="skuValue-颜色分类"]//label[contains(@class,"index-module_actionBefore")]',
            'xpath://label[contains(@class,"index-module_actionBefore")]',
            'xpath://div[text()="本地上传"]',
        ]
    else:
        # 通用选择器（白底图、吊牌、视频等）
        upload_selectors = [
            'xpath://label[contains(@class,"index-module_actionBefore")]',
            'xpath://div[text()="本地上传"]',
            'xpath://span[text()="本地上传"]',
            'xpath://label[text()="本地上传"]',
        ]
    
    # 尝试上下文选择器
    for i, selector in enumerate(upload_selectors, 1):
        try:
            elements = tab.eles(selector, timeout=0.8)
            if elements:
                for element in elements:
                    try:
                        if element.states.is_displayed and element.states.is_enabled:
                            print(f"  [成功] 上下文定位 {i}: {selector}")
                            return element
                    except:
                        continue
        except:
            continue
    
    # ========== 优先级3: 备用宽松选择器 ==========
    fallback_selectors = [
        'xpath://*[contains(text(),"本地上传")]',
        'xpath://button[contains(text(),"上传")]',
        'xpath://label[contains(@class,"button")]',
    ]
    
    for selector in fallback_selectors:
        try:
            elements = tab.eles(selector, timeout=0.5)
            for element in elements:
                try:
                    text = element.text.strip() if element.text else ''
                    if '本地' in text or '上传' in text:
                        if element.states.is_displayed:
                            print(f"  [成功] 备用定位: '{text}'")
                            return element
                except:
                    continue
        except:
            continue
    
    print(f"  [失败] 未找到'{context}'上传按钮")
    return None


def smart_find_element_with_retry(tab, element_name, selectors_list, max_retries=3, wait_time=1):
    """
    带重试的智能元素查找
    
    Args:
        tab: 页面标签页
        element_name: 元素名称(用于日志)
        selectors_list: 选择器列表
        max_retries: 最大重试次数
        wait_time: 重试等待时间
        
    Returns:
        找到的元素或None
    """
    for attempt in range(max_retries):
        print(f"[检查] 查找{element_name}(第{attempt + 1}/{max_retries}次尝试)...")
        
        for i, selector in enumerate(selectors_list, 1):
            try:
                print(f"  尝试选择器 {i}: {selector}")
                element = tab.ele(selector, timeout=2)
                if element and element.states.is_displayed:
                    print(f"  [成功] 成功找到{element_name}")
                    return element
            except Exception as e:
                print(f"  [失败] 选择器 {i} 失败: {e}")
                continue
        
        if attempt < max_retries - 1:
            print(f"  [等待] 等待{wait_time}秒后重试...")
            time.sleep(wait_time)
    
    print(f"  [失败] 最终未找到{element_name}")
    return None


def _wait_for_element(tab, selector, timeout=2, visible=True):
    """等待元素出现并可见"""
    start = _time.time()
    while _time.time() - start < timeout:
        try:
            el = tab.ele(selector, timeout=0.1)
            if el:
                if not visible or el.states.is_displayed:
                    return el
        except:
            pass
        time.sleep(0.05)
    return None


def _wait_for_element_gone(tab, selector, timeout=2):
    """等待元素消失"""
    start = _time.time()
    while _time.time() - start < timeout:
        try:
            el = tab.ele(selector, timeout=0.1)
            if not el or not el.states.is_displayed:
                return True
        except:
            return True
        time.sleep(0.05)
    return False


def _wait_until(predicate, timeout=2, interval=0.05):
    """轮询直到条件满足"""
    start = _time.time()
    while _time.time() - start < timeout:
        try:
            if predicate():
                return True
        except:
            pass
        time.sleep(interval)
    return False


def _get_visible_elements(tab, selector, timeout=0.1):
    """获取当前可见元素列表"""
    try:
        return [el for el in tab.eles(selector, timeout=timeout) if el and el.states.is_displayed]
    except:
        return []


def _xpath_literal(value: str) -> str:
    """安全拼接 XPath 字符串"""
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ', "\'", '.join([f"'{part}'" for part in parts]) + ")"


def _find_sku_local_upload_button(new_tab):
    popover_selectors = [
        'xpath://div[contains(@class,"ecom-g-popover")]//label[contains(@class,"index-module_actionBefore") and .//input[@type="file"] and .//*[normalize-space(text())="本地上传"]]',
        'xpath://div[contains(@class,"ecom-g-popover")]//label[.//input[@type="file"] and .//*[contains(normalize-space(.),"本地上传")]]',
        'xpath://div[contains(@class,"ecom-g-popover")]//label[.//input[@type="file"]]',
        'xpath://div[contains(@class,"ecom-g-popover-inner-content")]//label[contains(@class,"index-module_actionBefore")]',
        'xpath://div[contains(@class,"ecom-g-popover-inner-content")]//label[.//input[@type="file"]]',
        'xpath://div[contains(@class,"ecom-g-popover-inner-content")]//label[.//div[contains(normalize-space(.),"本地上传")]]',
        'xpath://div[contains(@class,"ecom-g-popover-inner-content")]//*[contains(normalize-space(.),"本地上传")]/ancestor::label[1]',
    ]

    for selector in popover_selectors:
        try:
            buttons = new_tab.eles(selector, timeout=0.3)
        except:
            buttons = []
        for btn in buttons:
            try:
                if btn and btn.states.is_displayed:
                    return btn
            except:
                continue

    return smart_find_upload_button(new_tab, "SKU")


def _find_sku_upload_trigger(new_tab, sku_name: str):
    literal = _xpath_literal(sku_name)
    trigger_selectors = [
        f'xpath://div[@id="skuValue-颜色分类"]//*[contains(normalize-space(.), {literal})]/ancestor::*[.//div[contains(@class,"material-button") and contains(@class,"material-upload-button")]][1]//div[contains(@class,"material-button") and contains(@class,"material-upload-button")][1]',
        f'xpath://div[@id="skuValue-颜色分类"]//*[contains(normalize-space(.), {literal})]/ancestor::*[.//div[contains(@class,"material-upload-button")]][1]//div[contains(@class,"material-upload-button")][1]',
        f'xpath://div[@id="skuValue-颜色分类"]//*[contains(normalize-space(.), {literal})]/following::div[contains(@class,"material-button") and contains(@class,"material-upload-button")][1]',
        f'xpath://div[@id="skuValue-颜色分类"]//*[contains(normalize-space(.), {literal})]/following::div[contains(@class,"material-upload-button")][1]',
    ]

    for selector in trigger_selectors:
        try:
            elements = new_tab.eles(selector, timeout=0.1)
        except:
            elements = []
        for item in elements:
            try:
                if item and item.states.is_displayed:
                    return item
            except:
                continue
    return None


def _set_sku_info_legacy(new_tab, index, sku, remark):
    print(f'设置第{index + 1}个sku -> {sku["name"]}')

    try:
        sku_name = str(sku.get("name") or "").strip()
        if not sku_name:
            raise Exception("SKU名称为空")

        spec_input_selector = 'xpath://input[@placeholder="请输入规格值"]'
        remark_input_selector = 'xpath://div[@id="skuValue-颜色分类"]//input[@placeholder="备注"]'
        confirm_bottom_selectors = [
            'xpath://div[contains(@class,"styles_popupFooter")]//button[contains(@class,"ecom-g-btn-primary")]',
            'xpath://div[contains(@class,"popupFooter")]//button[contains(@class,"ecom-g-btn-primary")]',
            'xpath://button[contains(@class,"ecom-g-btn-primary")][.//span[contains(normalize-space(.),"确定")]]',
        ]

        new_tab.set.upload_files(sku['path'])
        before_spec_count = len(_get_visible_elements(new_tab, spec_input_selector, timeout=0.05))

        color_inputs = _get_visible_elements(new_tab, 'xpath://div[@id="skuValue-颜色分类"]//input', timeout=0.2)
        if not color_inputs:
            raise Exception("未找到颜色分类输入框")
        color_inputs[-1].scroll.to_center()
        time.sleep(0.03)
        color_inputs[-1].click(by_js=True)

        add_btn = new_tab.ele(f'xpath:{new_btn_xpath}', timeout=1.5)
        if not add_btn:
            raise Exception("未找到添加规格按钮")
        add_btn.click(by_js=True)

        spec_input = None

        def _probe_spec_input():
            nonlocal spec_input
            inputs = _get_visible_elements(new_tab, spec_input_selector, timeout=0.05)
            if not inputs:
                return False
            if len(inputs) > before_spec_count:
                spec_input = inputs[-1]
                return True
            spec_input = inputs[-1]
            return spec_input.states.is_displayed

        if not _wait_until(_probe_spec_input, timeout=2.0, interval=0.05) or not spec_input:
            raise Exception("未找到规格值输入框")

        spec_input.click(by_js=True)
        try:
            spec_input.clear(by_js=True)
        except:
            pass
        spec_input.input(sku_name, clear=True)

        if not _wait_until(
            lambda: (spec_input.attr("value") or "").strip() == sku_name,
            timeout=0.8,
            interval=0.05
        ):
            raise Exception(f'规格值 "{sku_name}" 未成功写入')

        literal = _xpath_literal(sku_name)

        def _find_visible_confirm_icon():
            confirm_icons = new_tab.eles('xpath://span[@data-kora="确认"]', timeout=0.05)
            visible_icons = []
            for icon in confirm_icons:
                try:
                    if icon and icon.states.is_displayed:
                        visible_icons.append(icon)
                except:
                    continue
            return visible_icons[-1] if visible_icons else None

        def _find_visible_confirm_bottom():
            for selector in confirm_bottom_selectors:
                try:
                    buttons = new_tab.eles(selector, timeout=0.05)
                except:
                    buttons = []
                for btn in buttons:
                    try:
                        if btn and btn.states.is_displayed and btn.states.is_enabled:
                            return btn
                    except:
                        continue
            return None

        def _created_option_visible():
            created_selectors = [
                f'xpath://div[contains(@class,"ecom-g-cascader-menus")]//li[.//*[contains(normalize-space(.), {literal})]]',
                f'xpath://div[contains(@class,"ecom-g-cascader-menus")]//*[contains(normalize-space(.), {literal})]',
            ]
            for selector in created_selectors:
                try:
                    elements = new_tab.eles(selector, timeout=0.05)
                except:
                    elements = []
                for item in elements:
                    try:
                        if item and item.states.is_displayed:
                            return True
                    except:
                        continue
            return False

        confirm_icon = _find_visible_confirm_icon()
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
            except:
                continue
            if _wait_until(
                lambda: len(_get_visible_elements(new_tab, spec_input_selector, timeout=0.05)) <= before_spec_count
                or _find_visible_confirm_bottom() is not None
                or _created_option_visible(),
                timeout=2.0,
                interval=0.05
            ):
                icon_confirmed = True
                break

        if not icon_confirmed:
            raise Exception("创建类型后未成功确认规格值")

        confirm_bottom = None
        _wait_until(
            lambda: bool(_find_visible_confirm_bottom())
            or len(_get_visible_elements(new_tab, spec_input_selector, timeout=0.05)) <= before_spec_count,
            timeout=1.2,
            interval=0.05
        )
        confirm_bottom = _find_visible_confirm_bottom()

        def _confirm_popup_closed():
            visible_inputs = _get_visible_elements(new_tab, spec_input_selector, timeout=0.05)
            if len(visible_inputs) <= before_spec_count:
                return True

            for selector in confirm_bottom_selectors:
                try:
                    buttons = new_tab.eles(selector, timeout=0.05)
                except:
                    buttons = []
                for btn in buttons:
                    try:
                        if btn and btn.states.is_displayed:
                            return False
                    except:
                        continue
            return len(visible_inputs) <= before_spec_count

        confirmed = False
        if confirm_bottom:
            try:
                confirm_bottom.scroll.to_center()
            except:
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
                except:
                    continue
                if _wait_until(_confirm_popup_closed, timeout=1.5, interval=0.05):
                    confirmed = True
                    break
        else:
            confirmed = _confirm_popup_closed()

        if not confirmed:
            raise Exception("规格确认弹窗未关闭，确定按钮未生效")

        time.sleep(0.05)

        remark_text = str(remark or '').strip()
        if remark_text:
            remark_inputs = _get_visible_elements(new_tab, remark_input_selector, timeout=0.1)
            if remark_inputs:
                remark_inputs[-1].input(remark_text + '\n')
                time.sleep(0.15)

        sku_anchor_selector = f'xpath://div[@id="skuValue-颜色分类"]//*[contains(normalize-space(.), {literal})]'
        sku_anchor = None

        def _probe_sku_anchor():
            nonlocal sku_anchor
            anchor = new_tab.ele(sku_anchor_selector, timeout=0.05)
            if anchor and anchor.states.is_displayed:
                sku_anchor = anchor
                return True
            return False

        if not _wait_until(_probe_sku_anchor, timeout=2.5, interval=0.08):
            raise Exception(f'未找到 SKU "{sku_name}" 对应的悬停元素')

        hover_target = sku_anchor
        try:
            anchor_container = sku_anchor.parent('xpath:ancestor::*[contains(@class,"index-module_")][1]')
            if anchor_container:
                hover_target = anchor_container
        except:
            pass

        upload_trigger = _find_sku_upload_trigger(new_tab, sku_name)
        active_hover_target = upload_trigger or hover_target
        try:
            active_hover_target.scroll.to_center()
        except:
            pass
        time.sleep(0.03)
        upload_button = None

        def _probe_upload_button():
            nonlocal upload_button, upload_trigger, active_hover_target
            upload_trigger = _find_sku_upload_trigger(new_tab, sku_name) or upload_trigger
            active_hover_target = upload_trigger or active_hover_target or hover_target
            for target in (active_hover_target, hover_target, sku_anchor):
                if not target:
                    continue
                try:
                    target.hover()
                except:
                    continue
                time.sleep(0.08)
                btn = _find_sku_local_upload_button(new_tab)
                if btn and btn.states.is_displayed:
                    upload_button = btn
                    return True
            return False

        if not _wait_until(_probe_upload_button, timeout=1.8, interval=0.08) or not upload_button:
            raise Exception("无法找到'本地上传'按钮")

        try:
            upload_button.click()
        except:
            upload_button.click(by_js=True)

        new_tab.wait.upload_paths_inputted()
        time.sleep(0.12)
        handle_crop_popup(new_tab)
        print(f"[成功] SKU {index + 1} 设置完成")

    except Exception as e:
        error_msg = f"[失败] 设置SKU {index + 1}失败: {str(e)}"
        print(error_msg)
        traceback.print_exc()
        raise Exception(error_msg)


def set_sku_info(new_tab, index, sku, remark):
    return _set_sku_info_legacy(new_tab, index, sku, remark)
    """
    设置SKU信息 - 稳定优化版（带时间记录）
    
    使用等待元素状态的方式确保每一步操作完成后再继续
    """
    sku_start_time = _time.time()
    step_times = {}  # 记录每个步骤的耗时
    
    def _record_step(step_name, start_time):
        """记录步骤耗时"""
        elapsed = _time.time() - start_time
        step_times[step_name] = elapsed
        return _time.time()
    
    print(f'\n{"="*50}')
    print(f'设置第{index + 1}个SKU -> {sku["name"]}')
    print(f'{"="*50}')
    
    try:
        step_start = _time.time()
        sku_name = str(sku.get("name") or "").strip()
        if not sku_name:
            raise Exception("SKU名称为空")
        spec_input_selector = 'xpath://input[@placeholder="请输入规格值"]'
        remark_input_selector = 'xpath://div[@id="skuValue-颜色分类"]//input[@placeholder="备注"]'
        popup_selector = 'xpath://div[contains(@class,"cascader-menus")]'
        confirm_bottom_selectors = [
            'xpath://div[contains(@class,"styles_popupFooter")]//button[contains(@class,"ecom-g-btn-primary")]',
            'xpath://div[contains(@class,"popupFooter")]//button[contains(@class,"ecom-g-btn-primary")]',
            'xpath://button[contains(@class,"ecom-g-btn-primary")][.//span[starts-with(normalize-space(text()),"确定")]]',
        ]
        
        # 1. 设置待上传的图片文件
        new_tab.set.upload_files(sku['path'])
        step_start = _record_step("1.设置上传文件", step_start)

        # 2. 滚动并点击颜色分类输入框
        color_inputs = _get_visible_elements(new_tab, 'xpath://div[@id="skuValue-颜色分类"]//input')
        if not color_inputs:
            raise Exception("未找到颜色分类输入框")
        
        last_input = color_inputs[-1]
        last_input.scroll.to_center()
        time.sleep(0.05)
        last_input.click()
        
        popup_appeared = _wait_until(
            lambda: _wait_for_element(new_tab, popup_selector, timeout=0.05) is not None,
            timeout=0.6,
            interval=0.05
        )
        if not popup_appeared:
            last_input.click(by_js=True)
            popup_appeared = _wait_until(
                lambda: _wait_for_element(new_tab, popup_selector, timeout=0.05) is not None,
                timeout=1.0,
                interval=0.05
            )
        if not popup_appeared:
            raise Exception("未打开规格下拉菜单")
        step_start = _record_step("2.点击颜色分类", step_start)

        # 3. 点击"+"按钮(添加规格值)
        before_spec_count = len(_get_visible_elements(new_tab, spec_input_selector, timeout=0.05))
        before_remark_count = len(_get_visible_elements(new_tab, remark_input_selector, timeout=0.05))
        add_btn = _wait_for_element(new_tab, f'xpath:{new_btn_xpath}', timeout=1.5)
        if add_btn:
            add_btn.click(by_js=True)
        else:
            raise Exception("未找到添加规格按钮")

        # 等待输入框出现
        spec_input = None
        def _probe_spec_input():
            nonlocal spec_input
            inputs = _get_visible_elements(new_tab, spec_input_selector, timeout=0.05)
            if not inputs:
                return False
            if len(inputs) > before_spec_count:
                spec_input = inputs[-1]
                return True
            spec_input = inputs[-1]
            return spec_input.states.is_displayed

        _wait_until(_probe_spec_input, timeout=2.0, interval=0.05)
        step_start = _record_step("3.点击添加按钮", step_start)

        # 4. 输入规格值
        if spec_input:
            try:
                spec_input.click(by_js=True)
            except:
                pass
            try:
                spec_input.clear(by_js=True)
            except:
                pass
            spec_input.input(sku_name, clear=True)
            if not _wait_until(
                lambda: (spec_input.attr("value") or "").strip() == sku_name,
                timeout=0.6,
                interval=0.05
            ):
                spec_input.input(sku_name, clear=True, by_js=True)
        else:
            raise Exception("未找到规格值输入框")
        step_start = _record_step("4.输入规格值", step_start)

        # 5. 点击绿色勾选图标 [确认] - 优化版
        confirm_icon = None
        def _probe_confirm_icon():
            nonlocal confirm_icon
            icons = _get_visible_elements(new_tab, 'xpath://span[@data-kora="确认"]', timeout=0.05)
            if icons:
                confirm_icon = icons[-1]
                return True
            return False

        _wait_until(_probe_confirm_icon, timeout=1.2, interval=0.05)
        
        if confirm_icon:
            confirm_icon.click(by_js=True)
            _wait_until(
                lambda: (spec_input.attr("value") or "").strip() == sku_name,
                timeout=0.3,
                interval=0.05
            )
        step_start = _record_step("5.点击确认图标", step_start)
        
        # 6. 等待并点击底部 "确定 (数字)" 按钮 - 优化版
        confirm_bottom = None
        def _probe_confirm_bottom():
            nonlocal confirm_bottom
            for selector in confirm_bottom_selectors:
                try:
                    buttons = new_tab.eles(selector, timeout=0.05)
                except:
                    buttons = []
                for btn in reversed(buttons):
                    try:
                        classes = btn.attr('class') or ''
                        disabled = btn.attr('disabled')
                        if btn.states.is_displayed and disabled is None and 'disabled' not in classes:
                            confirm_bottom = btn
                            return True
                    except:
                        continue
            return False

        _wait_until(_probe_confirm_bottom, timeout=1.5, interval=0.05)
        
        if confirm_bottom:
            confirm_bottom.click(by_js=True)
            _wait_until(
                lambda: len(_get_visible_elements(new_tab, spec_input_selector, timeout=0.05)) <= before_spec_count,
                timeout=1.5,
                interval=0.05
            )
        else:
            raise Exception("未找到规格确认按钮")
        step_start = _record_step("6.点击确定按钮", step_start)
        
        literal = _xpath_literal(sku_name)
        sku_anchor_selector = f'xpath://div[@id="skuValue-颜色分类"]//*[contains(normalize-space(.), {literal})]'
        sku_anchor = None
        def _probe_sku_anchor():
            nonlocal sku_anchor
            anchor = new_tab.ele(sku_anchor_selector, timeout=0.05)
            if anchor and anchor.states.is_displayed:
                sku_anchor = anchor
                return True
            return False

        if not _wait_until(_probe_sku_anchor, timeout=3.0, interval=0.08):
            raise Exception(f'SKU "{sku_name}" 未稳定生成')

        # 7. 提交备注
        remark_text = str(remark or '').strip()
        if remark_text:
            try:
                remark_input = None
                def _probe_remark_input():
                    nonlocal remark_input
                    inputs = _get_visible_elements(new_tab, remark_input_selector, timeout=0.05)
                    if not inputs:
                        return False
                    if len(inputs) > before_remark_count:
                        remark_input = inputs[-1]
                        return True
                    remark_input = inputs[-1]
                    return remark_input.states.is_displayed

                if _wait_until(_probe_remark_input, timeout=2.0, interval=0.05) and remark_input:
                    remark_input.click(by_js=True)
                    try:
                        remark_input.clear(by_js=True)
                    except:
                        pass
                    remark_input.input(remark_text, clear=True)
                    _wait_until(
                        lambda: (remark_input.attr("value") or "").strip() == remark_text,
                        timeout=0.5,
                        interval=0.05
                    )
                    try:
                        remark_input.run_js('this.blur();')
                    except:
                        pass
            except:
                pass
        step_start = _record_step("7.填写备注", step_start)

        # 8. 滚动并悬停到当前 SKU 元素
        hover_target = sku_anchor
        try:
            anchor_container = sku_anchor.parent('xpath:ancestor::*[contains(@class,"index-module_")][1]')
            if anchor_container:
                hover_target = anchor_container
        except:
            pass
        if hover_target:
            hover_target.scroll.to_center()
            time.sleep(0.05)
            hover_target.hover()
        step_start = _record_step("8.悬停SKU元素", step_start)

        # 9. 点击上传按钮
        upload_button = None
        def _probe_upload_button():
            nonlocal upload_button
            btn = smart_find_upload_button(new_tab, "SKU")
            if btn and btn.states.is_displayed:
                upload_button = btn
                return True
            return False

        if _wait_until(_probe_upload_button, timeout=2.0, interval=0.08) and upload_button:
            upload_button.click(by_js=True)
        else:
            raise Exception("无法找到'本地上传'按钮")
        step_start = _record_step("9.点击上传按钮", step_start)

        # 10. 处理裁剪弹窗（如果有）
        handle_crop_popup(new_tab)
        step_start = _record_step("10.处理裁剪弹窗", step_start)
        
        # 输出时间统计
        total_time = _time.time() - sku_start_time
        print(f'\n[时间统计] SKU {index + 1} ({sku["name"]}):')
        print(f'{"步骤":<20} {"耗时(ms)":<10}')
        print(f'{"-"*30}')
        for step_name, elapsed in step_times.items():
            print(f'{step_name:<20} {int(elapsed*1000):<10}')
        print(f'{"-"*30}')
        print(f'{"总计":<20} {int(total_time*1000):<10}ms')
        print(f'{"="*50}\n')
        
    except Exception as e:
        total_time = _time.time() - sku_start_time
        error_msg = f"[失败] 设置SKU {index + 1}失败: {str(e)} (耗时: {int(total_time*1000)}ms)"
        print(error_msg)
        traceback.print_exc()
        raise Exception(error_msg)


def _ensure_section_ready(new_tab, section_label: str, timeout: float = 10.0):
    start = _time.time()
    while _time.time() - start < timeout:
        try:
            if new_tab.ele(f'xpath://div[@attr-field-id="{section_label}"]', timeout=0.5):
                return True
            if new_tab.ele('xpath://div[contains(@class,"index-module_batchImageUpload")]', timeout=0.5):
                return True
        except:
            pass
        time.sleep(0.2)
    return False


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

    # ========== 关键：一次性设置所有待上传的文件（与原版完全一致）==========
    print(f'  设置上传文件列表: {len(file_list)}个')
    for i, f in enumerate(file_list):
        print(f'    [{i+1}] {os.path.basename(f)}')
    new_tab.set.upload_files(file_list)

    fast_mode = not wait_for_finish
    area_ready_wait = 0.05 if fast_mode else 0.3
    hover_wait = 0.05 if fast_mode else 0.2
    trigger_wait = 0.1 if fast_mode else 0.5
    post_trigger_wait = 0.02 if fast_mode else 0.8
    size_error_timeout = 0.05 if fast_mode else 0.3

    # 根据 key 设置不同的 key_value
    if key == '主图视频':
        key_value = key
    else:
        key_value = f'上传{key}'

    # ========== 定位并悬浮到上传区域 ==========
    target_area_element = None  # 用于在指定区域内查找上传按钮
    
    if target_field_id:
        # 使用 attr-field-id 精确定位（用于 3:4 主图等特定区域）
        print(f'  使用 attr-field-id="{target_field_id}" 定位上传区域')
        target_area_element = new_tab.ele(f'xpath://div[@attr-field-id="{target_field_id}"]', timeout=3)
        if target_area_element:
            target_area_element.scroll.to_center()
            new_tab.scroll.up(50)
            time.sleep(area_ready_wait)
            
            # ========== 关键修复：直接在目标区域内找到上传按钮并点击 ==========
            # 根据抖音页面结构，上传按钮是 label.index-module_button__st1_R 或 material-upload-button
            upload_label_selectors = [
                # 精确匹配：material-upload-button 类的 label
                'xpath:.//div[contains(@class,"material-upload-button")]//label[contains(@class,"index-module_button")]',
                'xpath:.//label[contains(@class,"index-module_button__st1_R")]',
                # 查找包含"上传"文字的label
                'xpath:.//label[.//span[contains(text(),"上传")]]',
                # 查找 input[type="file"] 的父级 label
                'xpath:.//label[.//input[@type="file"]]',
            ]
            
            upload_label = None
            for selector in upload_label_selectors:
                try:
                    # 找到第一个可见的上传按钮
                    labels = target_area_element.eles(selector, timeout=0.5)
                    for label in labels:
                        if label and label.states.is_displayed:
                            upload_label = label
                            print(f'  找到上传按钮: {selector}')
                            break
                    if upload_label:
                        break
                except:
                    continue
            
            if upload_label:
                # 悬停到上传按钮
                upload_label.hover()
                time.sleep(hover_wait)
                print(f'  已悬停到"{target_field_id}"区域的上传按钮')
            else:
                # 直接悬停到目标区域
                target_area_element.hover()
                time.sleep(hover_wait)
        else:
            print(f'  警告: 未找到 attr-field-id="{target_field_id}" 区域，回退到默认定位')
            target_field_id = None  # 回退到默认逻辑
    
    if not target_field_id:
        if extra:
            # 详情图上传模式
            new_tab.ele(f'xpath://span[text()="{key_value}"]').scroll.to_center()
            time.sleep(0.05 if fast_mode else 0.1)
            new_tab.ele('xpath://div[contains(text(),"商详装修")]').scroll.to_see()
            time.sleep(0.05 if fast_mode else 0.1)
            new_tab.ele(f'xpath://span[text()="{key_value}"]').hover()
            time.sleep(0.1 if fast_mode else 0.5)
        else:
            # 标准上传模式（与原版完全一致）
            new_tab.ele(f'xpath://div[text()="{key_value}"]').scroll.to_center()
            new_tab.scroll.up(30)
            time.sleep(area_ready_wait)
            new_tab.ele(f'xpath://div[text()="{key_value}"]').hover()
            time.sleep(area_ready_wait)

    # ========== 智能查找并点击"本地上传"按钮 ==========
    upload_button = None
    
    # 如果指定了目标区域，优先在该区域内直接点击 label 触发文件选择
    if target_area_element:
        print(f'  在 "{target_field_id}" 区域内直接触发上传...')
        
        # 方案1：直接在目标区域找到 input[type="file"] 并触发
        try:
            # 找到第一个 material-upload-button 容器内的 input
            file_inputs = target_area_element.eles('xpath:.//div[contains(@class,"material-upload-button")]//input[@type="file"]', timeout=1)
            if file_inputs and len(file_inputs) > 0:
                # 直接使用第一个文件输入框
                print(f'  [成功] 在"{target_field_id}"区域内找到文件输入框，直接触发上传')
                # 文件已经通过 set.upload_files 设置，现在点击 label 触发
                first_label = target_area_element.ele('xpath:.//div[contains(@class,"material-upload-button")]//label', timeout=1)
                if first_label:
                    first_label.click(by_js=True)
                    upload_button = first_label  # 标记已找到
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
                    btn = new_tab.ele(selector, timeout=0.5)
                    if btn and btn.states.is_displayed:
                        upload_button = btn
                        print(f'  [成功] 在弹窗中找到本地上传按钮')
                        break
                except:
                    continue
    
    # 如果还没找到，使用智能查找
    if not upload_button:
        upload_button = smart_find_upload_button(new_tab, key)
    
    if upload_button and upload_button != True:  # 如果是元素而不是标记
        print(f"[成功] 智能定位成功,点击{key}上传按钮...")
        try:
            upload_button.click(by_js=True)
        except:
            pass  # 可能已经点击过了
    elif not upload_button:
        # 备用策略：尝试原始的查找方式（与原版完全一致）
        print(f"[警告] 智能查找失败,尝试备用方案...")
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
    time.sleep(trigger_wait)
    new_tab.wait.upload_paths_inputted()
    time.sleep(post_trigger_wait)
    
    print(f"[OK] {key}上传已触发，共{len(file_list)}个文件")

    if not wait_for_finish:
        if error_size:
            try:
                size_error = new_tab.ele(f'xpath://div[text()="{error_size}"]', timeout=size_error_timeout)
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
        for i in range(5):
            if i > 0:
                if not new_tab.ele(f'xpath://div[text()="{error_size}"]', timeout=1):
                    break
                new_tab.ele(f'xpath://div[text()="{error_size}"]/../..//img/../..').hover()
                time.sleep(0.5)
                # 点击"AI换背景"按钮来调整尺寸
                ai_change_bg_btn = new_tab.ele('xpath://div[text()="AI换背景"]', timeout=1)
                if ai_change_bg_btn:
                    ai_change_bg_btn.click(by_js=True)
                    time.sleep(0.5)
                else:
                    print('未找到AI换背景按钮')
                    break
            apply_btn_curr = None
            for _ in range(10):
                apply_btn_list = new_tab.eles('xpath://span[text()="应用"]/..', timeout=0.5)
                for apply_btn in apply_btn_list:
                    if apply_btn.states.is_displayed:
                        apply_btn_curr = apply_btn
                        break
                if apply_btn_curr:
                    break
                time.sleep(0.5)
            if not apply_btn_curr:
                break
            print('遇到需要裁剪!!!')
            print('点击应用...')
            apply_btn_curr.click()
            time.sleep(3)
            print('点击上传...')
            # 使用多种选择器查找上传按钮（兼容不同版本的页面结构）
            upload_btn = None
            footer_selectors = [
                # 通用选择器 - 查找包含"上传"文本的主按钮
                'xpath://button[contains(@class,"ecom-g-btn-primary")]//span[text()="上传"]/..',
                'xpath://span[text()="上传"]/parent::button[contains(@class,"ecom-g-btn-primary")]',
                # 弹窗底部的上传按钮
                'xpath://div[contains(@class,"footerWrapper")]//button[contains(@class,"ecom-g-btn-primary")]',
                'xpath://div[contains(@class,"footer")]//span[text()="上传"]/..',
                # 模态框底部
                'xpath://div[contains(@class,"modal")]//button[contains(@class,"primary")]//span[text()="上传"]/..',
            ]
            for selector in footer_selectors:
                try:
                    btn = new_tab.ele(selector, timeout=2)
                    if btn and btn.states.is_displayed:
                        upload_btn = btn
                        print(f'  找到上传按钮: {selector}')
                        break
                except:
                    continue
            
            if upload_btn:
                # 使用JavaScript点击增强可靠性
                upload_btn.click(by_js=True)
                btn_class = upload_btn.attr('class') or ''
                if 'disabled' in btn_class:
                    print('检测到禁用状态,强制JS点击')
                    try:
                        new_tab.run_js('arguments[0].click();', upload_btn)
                    except:
                        pass
                time.sleep(0.3)
            else:
                print('警告: 未找到上传按钮，跳过本次裁剪')
        # 等待上传完成（动态判断，最多90秒）
        upload_flag = False
        idle_checks = 0
        for _ in range(180):
            spinner = new_tab.ele('xpath://span[contains(@class,"ecom-g-btn-loading-icon")]', timeout=0.5)
            uploading_text = new_tab.ele('上传中', timeout=0.5)
            if not spinner and not uploading_text:
                idle_checks += 1
            else:
                idle_checks = 0
            if idle_checks >= 3:
                upload_flag = True
                break
            time.sleep(0.5)
        if not upload_flag:
            raise Exception(f'上传{key}超时失败!')
        print(f'上传{key}成功!')
        time.sleep(0.3)


def create_video(new_tab):
    if not new_tab.ele('xpath://div[text()="主图视频"]', timeout=1):
        return
    print('生成主图视频')
    new_tab.ele('xpath://div[text()="主图视频"]').scroll.to_center()
    time.sleep(0.3)
    new_tab.ele('xpath://div[text()="主图视频"]').hover()
    time.sleep(0.3)
    new_tab.ele('xpath://div[text()="制作视频"]').click()
    time.sleep(1)
    new_tab.ele('xpath://div[text()="一键生成视频"]/../../..//span[text()="立即使用"]/..').click(by_js=True)
    time.sleep(1)
    new_tab.ele('xpath://div[text()="3:4主图视频"]').click()
    time.sleep(0.5)
    new_tab.ele('xpath://span[text()="一键生成"]/..').click()
    time.sleep(3)
    flag = False
    for _ in range(300):
        if not new_tab.ele('创意生成中...', timeout=1) and not new_tab.ele('创意视频生成中...', timeout=1):
            flag = True
            break
        time.sleep(1)
    if not flag:
        raise Exception('创意生成超时失败!!!')
    new_tab.ele('xpath://div[text()="商品展示类创意"]/../..//span[text()="上传该视频"]/..').click(by_js=True)
    time.sleep(1)
    print('生成主图视频成功!')

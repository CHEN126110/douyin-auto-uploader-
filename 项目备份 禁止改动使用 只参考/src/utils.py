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
            base_dir = preferred_dir if os.path.isdir(preferred_dir) else os.path.join(record.path, '主图')
        else:
            base_dir = os.path.join(record.path, folder_path)
    
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
            if key == '750':
                candidates = []
                for fname in sorted(os.listdir(base_dir)):
                    fext = os.path.splitext(fname)[1].lower()
                    if fext in [fmt.lower() for fmt in supported_formats]:
                        fpath = os.path.join(base_dir, fname)
                        try:
                            with Image.open(fpath) as im:
                                w, h = im.size
                            ratio = w / h if h else 0
                            if abs(ratio - 0.75) < 0.03:
                                candidates.append(fpath)
                        except Exception:
                            pass
                if i < len(candidates):
                    file_path = candidates[i]
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
    
    # [修复] 修改策略:ID模式下,如果没有主图3:4,直接跳过不填充
    # 让平台使用自带的"从1:1主图一键填入"功能,避免触发裁剪工具
    if record.type == 2 and key == '750' and len(result) == 0:
        print("ID模式:未找到主图3:4,跳过上传,让平台使用自带的1:1导入功能")
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


def get_white_pic(record, sku_list) -> str:
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
                    return file_path
                # 也在根目录查找
                file_path = os.path.join(record.path, f'{name}.{fmt}')
                if os.path.exists(file_path):
                    return file_path
            else:
                # ID模式:在根目录查找
                file_path = os.path.join(record.path, f'{name}.{fmt}')
                if os.path.exists(file_path):
                    return file_path
    
    # 如果没找到白底图,返回第一个SKU图片作为备用
    return sku_list[0]['path']


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

def _expand_category_more(new_tab):
    try:
        btn = new_tab.ele('xpath://span[contains(@class,"style_categoryFolderBtn__") and contains(text(),"展开更多")]', timeout=1)
        if not btn:
            btn = new_tab.ele('xpath://div[contains(@class,"style_categoryFolderBtnWrapperNew__")]//span[contains(text(),"展开更多")]', timeout=1)
        if btn and btn.states.is_displayed:
            btn.scroll.to_center()
            time.sleep(0.2)
            btn.click(by_js=True)
            time.sleep(0.5)
    except:
        pass


def caizhi_select(new_tab, key, value, index):
    print(f'设置材质 -> {key}({value})')
    _expand_category_more(new_tab)
    inputs = new_tab.eles('xpath://div[@attr-field-id="面料材质"]//input[@role="combobox"]', timeout=1)
    if not inputs or len(inputs) <= index:
        # 兼容未展开或不同结构：直接定位输入框
        combo = new_tab.ele('xpath://div[@attr-field-id="面料材质"]//input[@role="combobox"]', timeout=1)
        if combo:
            combo.clear()
            combo.input(key)
            time.sleep(0.5)
            combo.click()
            time.sleep(0.5)
            opt = new_tab.ele(f'xpath://div[@class="ecom-g-select-item-option-content" and text()="{key}"]', timeout=1)
            if opt:
                opt.click()
        text_input = new_tab.ele('xpath://div[@attr-field-id="面料材质"]//input[@class="ecom-g-input"]', timeout=1)
        if text_input:
            text_input.clear()
            text_input.input(value)
        time.sleep(0.8)
        return
    # 正常路径
    inputs[index].clear()
    inputs[index].input(key)
    time.sleep(0.5)
    inputs[index].click()
    time.sleep(0.5)
    opt = new_tab.ele(f'xpath://div[@class="ecom-g-select-item-option-content" and text()="{key}"]', timeout=1)
    if opt:
        opt.click()
    time.sleep(0.5)
    texts = new_tab.eles('xpath://div[@attr-field-id="面料材质"]//input[@class="ecom-g-input"]', timeout=1)
    if texts and len(texts) > index:
        texts[index].clear()
        texts[index].input(value)
    time.sleep(1)


def select_text(new_tab, key, value, extra=None):
    _expand_category_more(new_tab)
    input_element = new_tab.ele(f'xpath://span[text()="{key}"]/../../../../../..//input', timeout=0.5)
    if not input_element:
        print(f'未找到字段:{key}')
        return
    print(f'选择{key} -> {value}')
    input_element.click()
    time.sleep(0.5)
    dropdown_menu = new_tab.ele('xpath://div[contains(@class,"ecom-g-select-dropdown") and not(contains(@class,"ecom-g-select-dropdown-hidden"))]', timeout=1)
    if dropdown_menu:
        option = dropdown_menu.ele(f'xpath:.//div[@class="ecom-g-select-item-option-content"][text()="{value}"]', timeout=1)
        if option:
            option.click()
        elif extra:
            option = dropdown_menu.ele(f'xpath:.//div[@class="rc-virtual-list-holder-inner"][text()="{extra}"]', timeout=1)
            if option:
                option.click()
            else:
                print(f'未在下拉菜单中找到选项:{value} 或 {extra}')
        else:
            print(f'未在下拉菜单中找到选项:{value}')
    else:
        print('未找到下拉菜单')
    time.sleep(0.5)


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
    """
    try:
        # 先判断是否出现裁剪弹窗
        crop_title = new_tab.ele(
            'xpath://div[@class="ecom-g-modal-title" and contains(text(),"图片裁剪")]',
            timeout=0.5
        )
        if not crop_title:
            print("未检测到图片裁剪弹窗,继续后续操作.")
            return
    except:
        print("未检测到图片裁剪弹窗,继续操作.")
        return

    print("检测到图片裁剪弹窗,开始处理...")

    try:
        # 查找 "-" 按钮(一般是第一个按钮)
        minus_btn = new_tab.ele(
            'xpath://div[contains(@class,"styles_zoom")]//button[1]',
            timeout=0.5
        )
        if not minus_btn:
            print("未找到 \"-\" 按钮,无法缩放图片.")
            return

        # 连续点击 3 次 "-"
        for i in range(3):
            minus_btn.click()
            print(f"点击 \"-\" 按钮,第 {i + 1} 次.")
            time.sleep(0.2)

        # 点击 "确定" 按钮
        confirm_btn = new_tab.ele(
            'xpath://div[@class="ecom-g-modal-footer"]//button[@type="button" and contains(.,"确定")]',
            timeout=1
        )
        if confirm_btn:
            confirm_btn.click(by_js=True)
            print("点击裁剪弹窗中的 确定 按钮完成裁剪.")
            time.sleep(0.5)
        else:
            print("未找到裁剪弹窗中的 [确定] 按钮,可能已经自动关闭.")

    except Exception as e:
        print(f"处理图片裁剪弹窗时出现异常:{e}")


def smart_find_upload_button(tab, context="SKU"):
    """
    智能查找"本地上传"按钮
    
    Args:
        tab: 页面标签页对象
        context: 上下文信息,用于更精确的定位
        
    Returns:
        找到的按钮元素,如果未找到返回None
    """
    print(f"[检查] 智能查找'{context}'上传按钮...")
    
    # 定义多种可能的定位策略
    upload_selectors = [
        # 原始策略
        'xpath://div[text()="本地上传"]',
        
        # 更宽松的文本匹配
        'xpath://div[contains(text(),"本地上传")]',
        'xpath://span[text()="本地上传"]',
        'xpath://span[contains(text(),"本地上传")]',
        'xpath://button[contains(text(),"本地上传")]',
        
        # 基于class和属性的查找
        'xpath://div[contains(@class,"upload")]//div[contains(text(),"本地")]',
        'xpath://div[contains(@class,"upload")]//span[contains(text(),"本地")]',
        
        # 图标+文字的组合
        'xpath://div[contains(@class,"icon")]/..//div[contains(text(),"本地")]',
        'xpath://i[contains(@class,"upload")]/..//div[contains(text(),"本地")]',
        
        # 更广泛的搜索
        'xpath://*[contains(text(),"本地上传")]',
        'xpath://*[contains(text(),"上传")]',
        
        # 基于功能的查找
        'xpath://div[@role="button" and contains(text(),"上传")]',
        'xpath://button[contains(text(),"上传")]'
    ]
    
    # 逐个尝试定位策略
    for i, selector in enumerate(upload_selectors, 1):
        try:
            print(f"  尝试策略 {i}: {selector}")
            elements = tab.eles(selector, timeout=1)
            
            if elements:
                for element in elements:
                    try:
                        # 检查元素是否可见且可点击
                        if element.states.is_displayed and element.states.is_enabled:
                            print(f"  [成功] 找到可用的上传按钮: {selector}")
                            return element
                    except:
                        continue
            
        except Exception as e:
            print(f"  [失败] 策略 {i} 失败: {e}")
            continue
    
    # 如果以上策略都失败,尝试AI辅助查找
    try:
        print("  [AI] 启用AI辅助查找...")
        # 这里可以集成AI视觉识别
        # 暂时使用更宽泛的搜索
        all_clickable = tab.eles('xpath://div[@role="button"] | //button | //span[contains(@class,"btn")] | //div[contains(@class,"btn")]', timeout=2)
        
        for element in all_clickable:
            try:
                text_content = element.text.strip().lower()
                if any(keyword in text_content for keyword in ['本地', '上传', 'upload', '本地上传']):
                    if element.states.is_displayed and element.states.is_enabled:
                        print(f"  [成功] AI找到匹配按钮: '{element.text}' -> {element.tag}")
                        return element
            except:
                continue
                
    except Exception as e:
        print(f"  [失败] AI辅助查找失败: {e}")
    
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


def set_sku_info(new_tab, index, sku, remark):
    print(f'设置第{index + 1}个sku -> {sku["name"]}')
    
    try:
        # 上传当前 SKU 的本地图片
        new_tab.set.upload_files(sku['path'])

        # 滚动并点击颜色分类输入框
        new_tab.eles('xpath://div[@id="skuValue-颜色分类"]//input')[-1].scroll.to_center()
        time.sleep(0.1)  
        new_tab.eles('xpath://div[@id="skuValue-颜色分类"]//input')[-1].click()
        time.sleep(0.3)  

        # 点击"+"按钮(添加规格值)
        new_tab.ele(f'xpath:{new_btn_xpath}', timeout=1.5).click(by_js=True)
        time.sleep(0.1)  

        # 输入规格值
        new_tab.eles('xpath://input[@placeholder="请输入规格值"]')[-1].input(sku["name"])
        time.sleep(0.3)  

        # 点击 [确认] 按钮
        new_tab.eles('xpath://span[@data-kora="确认"]')[-1].click(by_js=True)
        time.sleep(0.5)  
        confirm_bottom = new_tab.ele(
            'xpath://div[contains(@class,"styles_popupFooter")]/button[contains(@class,"ecom-g-btn-primary") and .//span[contains(text(),"确定")]]',
            timeout=2
        )
        confirm_bottom.scroll.to_center()
        confirm_bottom.click(by_js=True)
        time.sleep(0.3)
        # 提交备注
        new_tab.eles('xpath://div[@id="skuValue-颜色分类"]//input[@placeholder="备注"]', timeout=0.5)[-1].input(remark + '\n')
        time.sleep(0.2)  

        # 滚动并悬停到当前 SKU 的最末元素
        new_tab.eles('xpath://div[@id="skuValue-颜色分类"]//div[starts-with(@class,"index-module_")]')[-1].scroll.to_center()
        time.sleep(0.1)  
        new_tab.eles('xpath://div[@id="skuValue-颜色分类"]//div[starts-with(@class,"index-module_")]')[-1].hover()
        time.sleep(0.3)  # 悬浮操作稍微增加等待,确保悬浮效果

        # [修复] 使用智能查找替代硬编码的xpath
        upload_button = smart_find_upload_button(new_tab, "SKU")
        if upload_button:
            print(f"[成功] 智能定位成功,点击上传按钮...")
            upload_button.click(by_js=True)
        else:
            # 如果智能查找失败,抛出详细错误
            raise Exception("无法找到'本地上传'按钮,页面元素可能已更改.请检查页面状态或联系技术支持.")

        new_tab.wait.upload_paths_inputted()
        time.sleep(0.5)  # 上传路径注入后稍等

        # 新增:调用裁剪弹窗处理逻辑
        handle_crop_popup(new_tab)
        
        print(f"[成功] SKU {index + 1} 设置完成")
        
    except Exception as e:
        error_msg = f"[失败] 设置SKU {index + 1}失败: {str(e)}"
        print(error_msg)
        # 记录详细错误信息
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


def upload_file(new_tab, file_list: List[str], key: str, extra: bool = False, error_size: Union[bool, str] = False) -> None:
    print(f'开始上传{key}...')

    # 检查文件列表是否为空
    if not file_list:
        print(f'没有需要上传的 {key},跳过此步骤.')
        return

    # 判断文件是否存在
    if not os.path.exists(file_list[0]):
        print(f'文件 {file_list[0]} 不存在,跳过上传 {key}')
        return

    new_tab.set.upload_files(file_list)

    # 根据 key 设置不同的 key_value
    if key == '主图视频':
        key_value = key
    else:
        key_value = f'上传{key}'

    # 定位并点击上传按钮
    if extra:
        new_tab.ele(f'xpath://span[text()="{key_value}"]').scroll.to_center()
        time.sleep(0.1)
        new_tab.ele('xpath://div[contains(text(),"商详装修")]').scroll.to_see()
        time.sleep(0.1)
        new_tab.ele(f'xpath://span[text()="{key_value}"]').hover()
        time.sleep(0.5)
    else:
        new_tab.ele(f'xpath://div[text()="{key_value}"]').scroll.to_center()
        new_tab.scroll.up(30)
        time.sleep(0.3)
        new_tab.ele(f'xpath://div[text()="{key_value}"]').hover()
        time.sleep(0.3)

    # [修复] 使用智能查找"本地上传"按钮
    upload_button = smart_find_upload_button(new_tab, key)
    if upload_button:
        print(f"[成功] 智能定位成功,点击{key}上传按钮...")
        upload_button.click(by_js=True)
    else:
        # 备用策略:尝试原始的查找方式
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
    time.sleep(0.5)
    new_tab.wait.upload_paths_inputted()
    time.sleep(0.8)

    # 处理需要裁剪的情况
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
            # 先定位底部操作栏容器
            footer = new_tab.ele('xpath://div[contains(@class,"styles-module_footerWrapper__vb95p")]', timeout=10)
            # 在容器内精确查找上传按钮
            upload_btn = footer.ele('xpath:.//button[contains(@class,"ecom-g-btn-primary")]//span[text()="上传"]/..')
            # 使用JavaScript点击增强可靠性
            upload_btn.click(by_js=True)  # 优先尝试常规点击
            if 'disabled' in upload_btn.attr('class'):
                print('检测到禁用状态,强制JS点击')
                new_tab.driver.execute_script("arguments[0].click();", upload_btn.obj)
                time.sleep(0.3)
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

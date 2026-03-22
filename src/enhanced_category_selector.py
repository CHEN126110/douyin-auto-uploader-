"""
增强的类目选择器 - 处理抖音小店新版类目选择界面
解决需要先点击"手动选择"按钮才能显示完整类目选择器的问题
"""

import time
import time as _time_module
import logging

logger = logging.getLogger(__name__)



# 导入计时器
try:
    from src.utils import timer_record
except ImportError:
    def timer_record(*args, **kwargs):
        pass  # 如果导入失败，使用空函数

class EnhancedCategorySelector:
    """增强的类目选择器"""
    
    def __init__(self, tab):
        """
        初始化类目选择器
        
        Args:
            tab: DrissionPage标签页对象
        """
        self.tab = tab
        self.wazi_dict = {
            '0': '船袜',
            '1': '短袜', 
            '2': '中筒袜',
            '3': '长筒袜',
            '4': '袜套'
        }
    
    def select_category(self, category_code: str, max_retries: int = 3) -> bool:
        """
        智能选择类目 - 优化版（快速判断，无犹豫）
        
        优化策略:
        1. 不等待图片上传完成，直接检查类目
        2. 快速检查默认选中的类目是否匹配
        3. 如果匹配，直接点击下一步
        4. 减少所有等待时间
        
        Args:
            category_code: 类目代码 ('0', '1', '2', '3', '4')
            max_retries: 最大重试次数
            
        Returns:
            bool: 选择是否成功
        """
        func_start = _time_module.time()
        category_code = str(category_code)
        category_name = self.wazi_dict.get(category_code)
        if not category_name:
            logger.error(f"未知的类目代码: {category_code}")
            timer_record('类目选择', f'未知类目-{category_code}', 0, _time_module.time() - func_start, False)
            return False
            
        logger.info(f"[START] 选择类目: {category_name}")
        
        for attempt in range(max_retries):
            try:
                # ========== 快速路径1: 检查默认选中的类目 ==========
                if self._is_current_category(category_name):
                    logger.info(f"[FAST] 默认类目匹配，直接下一步")
                    if self._click_next_step():
                        timer_record('类目选择', f'{category_name}(默认匹配)', 0, _time_module.time() - func_start, True)
                        return True
                    timer_record('类目选择', f'{category_name}(默认匹配)', 0, _time_module.time() - func_start, True)
                    return True

                # ========== 快速路径2: 从推荐列表中选择 ==========
                if self._select_from_recommendations(category_name):
                    logger.info(f"[OK] 推荐列表选择成功: {category_name}")
                    if self._click_next_step():
                        timer_record('类目选择', f'{category_name}(推荐列表)', 0, _time_module.time() - func_start, True)
                        return True
                    timer_record('类目选择', f'{category_name}(推荐列表)', 0, _time_module.time() - func_start, True)
                    return True

                # ========== 扩展搜索: 点击更多推荐 ==========
                self._click_more_recommend(1)
                if self._select_from_recommendations(category_name):
                    logger.info(f"[OK] 更多推荐后选择成功")
                    if self._click_next_step():
                        timer_record('类目选择', f'{category_name}(更多推荐)', 0, _time_module.time() - func_start, True)
                        return True
                    timer_record('类目选择', f'{category_name}(更多推荐)', 0, _time_module.time() - func_start, True)
                    return True

                # 再次点击更多推荐
                self._click_more_recommend(1)
                if self._select_from_recommendations(category_name):
                    logger.info(f"[OK] 第二次更多推荐后选择成功")
                    if self._click_next_step():
                        timer_record('类目选择', f'{category_name}(更多推荐x2)', 0, _time_module.time() - func_start, True)
                        return True
                    timer_record('类目选择', f'{category_name}(更多推荐x2)', 0, _time_module.time() - func_start, True)
                    return True

                # ========== 最后方案: 手动选择 ==========
                logger.info("[INFO] 尝试手动选择...")
                if not self._handle_recommendations():
                    pass  # 继续尝试
                if not self._click_manual_select():
                    if attempt < max_retries - 1:
                        time.sleep(0.5)  # 减少等待时间
                    continue

                if not self._wait_for_category_selector():
                    if attempt < max_retries - 1:
                        time.sleep(0.5)
                    continue

                if self._perform_category_selection(category_name):
                    logger.info(f"[OK] 手动选择成功: {category_name}")
                    timer_record('类目选择', f'{category_name}(手动选择)', 0, _time_module.time() - func_start, True)
                    return True

            except Exception as e:
                logger.error(f"[ERROR] 选择类目出错: {str(e)}")

            if attempt < max_retries - 1:
                time.sleep(0.5)  # 减少重试等待时间

        logger.error(f"[FAIL] 类目选择失败，已重试 {max_retries} 次")
        timer_record('类目选择', f'{category_name}(失败)', 0, _time_module.time() - func_start, False)
        return False
    
    
    
    def _handle_recommendations(self) -> bool:
        """
        处理推荐类目界面，点击“更多推荐”直到“手动选择”出现
        
        Returns:
            bool: 是否成功进入手动选择
        """
        logger.info("处理推荐类目界面...")
        
        max_clicks = 3  # 最大点击次数
        for attempt in range(max_clicks):
            # 检查是否已有手动选择按钮
            if self._is_manual_select_visible():
                logger.info("手动选择按钮已可见")
                return True
            
            # 尝试点击“更多推荐”
            more_recommend_selector = 'xpath://div[contains(@class,"styles_recommendBottom__eoMau")]//button[contains(@class,"ecom-g-btn")]//span[text()="更多推荐"]/..'
            try:
                more_btn = self.tab.ele(more_recommend_selector, timeout=2)
                if more_btn and more_btn.states.is_displayed:
                    try:
                        more_btn.scroll.to_see()
                    except:
                        pass
                    more_btn.click(by_js=True)
                    time.sleep(1)
                    logger.info(f"点击了更多推荐 (第 {attempt + 1} 次)")
                else:
                    logger.info("未找到更多推荐按钮")
                    break
            except Exception as e:
                logger.debug(f"点击更多推荐失败: {str(e)}")
                break
        
        # 最终检查
        return self._is_manual_select_visible()

    def _click_more_recommend(self, times: int = 1):
        """
        点击"更多推荐"按钮 - 优化版
        
        基于2026年抖音页面结构优化:
        - 类目区域: div.styles_categorySelectorV2__l6n1S
        - 更多推荐按钮: button.ecom-g-btn-link > span (文本"更多推荐")
        """
        for _ in range(times):
            btn = None
            # 优先级1: 精确选择器（基于实际DOM）
            precise_selectors = [
                # 新版页面 - 类目选择区域中的更多推荐按钮
                'xpath://div[contains(@class,"categorySelectorV2")]//button[contains(@class,"ecom-g-btn-link")]//span[text()="更多推荐"]/..',
                'xpath://div[contains(@class,"categorySelectorV2")]//span[text()="更多推荐"]/..',
                # 通用选择器
                'xpath://button[contains(@class,"ecom-g-btn-link")]//span[text()="更多推荐"]/..',
                'xpath://span[text()="更多推荐"]/..',
                'xpath://span[text()="更多推荐"]',
            ]
            
            for selector in precise_selectors:
                try:
                    btn = self.tab.ele(selector, timeout=0.8)
                    if btn and btn.states.is_displayed:
                        break
                except:
                    btn = None
                    continue
            
            if btn:
                try:
                    btn.scroll.to_see()
                except:
                    pass
                btn.click(by_js=True)
                time.sleep(0.5)  # 减少等待时间提高速度

    def _select_from_recommendations(self, category_name: str) -> bool:
        """
        从推荐类目中选择 - 优化版
        
        基于2026年抖音页面结构优化:
        - 推荐容器: div.styles_recommendContainer__w3eyn
        - 类目选项: div.styles_normal__HSl_a
        - 选中状态: div.styles_itemSelected__Y78bg
        
        注意: 不需要等待图片上传完成，直接选择类目
        """
        try:
            # 优先级1: 精确选择器（基于实际DOM结构）
            precise_selectors = [
                # 新版页面 - 推荐容器中的类目选项
                f'xpath://div[contains(@class,"recommendContainer")]//div[contains(@class,"normal") and contains(text(),"{category_name}") and not(contains(@class,"disable"))]',
                f'xpath://div[contains(@class,"styles_normal") and contains(text(),"{category_name}") and not(contains(@class,"disable"))]',
                # 类目选择器区域
                f'xpath://div[contains(@class,"categorySelectorV2")]//div[contains(text(),"{category_name}") and not(contains(@class,"disable"))]',
            ]
            
            for selector in precise_selectors:
                try:
                    el = self.tab.ele(selector, timeout=0.5)  # 快速超时
                    if el and el.states.is_displayed:
                        # 检查是否已经选中
                        el_class = el.attr('class') or ''
                        if 'itemSelected' in el_class:
                            logger.info(f"[FAST] 类目已选中: {category_name}")
                            return True
                        # 点击选择
                        el.click(by_js=True)
                        time.sleep(0.2)  # 最小等待
                        logger.info(f"[OK] 选择类目: {category_name}")
                        return True
                except:
                    continue
                    
            # 优先级2: 遍历推荐容器中的所有选项
            try:
                container = self.tab.ele('xpath://div[contains(@class,"recommendContainer")]', timeout=0.5)
                if container:
                    all_items = container.eles('xpath:.//div[contains(@class,"normal")]')
                    for item in all_items:
                        try:
                            txt = (item.text or '').strip()
                            if category_name in txt and item.states.is_displayed:
                                item_class = item.attr('class') or ''
                                if 'disable' not in item_class:
                                    if 'itemSelected' in item_class:
                                        logger.info(f"[FAST] 类目已选中: {txt}")
                                        return True
                                    item.click(by_js=True)
                                    time.sleep(0.2)
                                    logger.info(f"[OK] 选择类目: {txt}")
                                    return True
                        except:
                            continue
            except:
                pass
                
        except:
            pass
        return False

    def _is_current_category(self, category_name: str) -> bool:
        """
        快速检查当前选中的类目是否匹配 - 优化版
        
        基于2026年抖音页面结构:
        - 选中状态: div.styles_normal__HSl_a.styles_itemSelected__Y78bg
        - 包含选中图标: img.styles_selectedIcon__plc8d
        """
        try:
            # 优先级1: 精确查找已选中的类目（使用 itemSelected class）
            selected_selectors = [
                'xpath://div[contains(@class,"itemSelected")]',
                'xpath://div[contains(@class,"styles_itemSelected")]',
                'xpath://div[contains(@class,"recommendContainer")]//div[contains(@class,"itemSelected")]',
            ]
            
            for selector in selected_selectors:
                try:
                    el = self.tab.ele(selector, timeout=0.5)  # 减少超时时间
                    if el and el.states.is_displayed:
                        txt = (el.text or '').strip()
                        if category_name in txt:
                            logger.info(f"[FAST] 默认选中类目匹配: {txt}")
                            return True
                        else:
                            logger.info(f"[INFO] 默认选中类目不匹配: {txt} (需要: {category_name})")
                            return False
                except:
                    continue
        except:
            pass
        return False
    
    def _is_manual_select_visible(self) -> bool:
        """检查手动选择按钮是否可见"""
        manual_select_selectors = [
            'xpath://button[contains(@class,"ecom-g-btn")]//span[text()="手动选择"]/..',
            'xpath://span[text()="手动选择"]/..',
            'xpath://button[contains(@class,"ecom-g-btn-link")]//span[text()="手动选择"]/..',
        ]
        for selector in manual_select_selectors:
            try:
                element = self.tab.ele(selector, timeout=1)
                if element and element.states.is_displayed:
                    return True
            except:
                continue
        return False
    
    def _click_manual_select(self) -> bool:
        """
        点击"手动选择"按钮
        
        Returns:
            bool: 点击是否成功
        """
        logger.info("尝试点击手动选择按钮...")
        
        manual_select_selectors = [
            # 新版界面选择器
            'xpath://button[contains(@class,"ecom-g-btn")]//span[text()="手动选择"]/..',
            'xpath://span[text()="手动选择"]/..',
            'xpath://button[contains(@class,"ecom-g-btn-link")]//span[text()="手动选择"]/..',
            
            # 备用选择器
            'xpath://div[contains(@class,"manual-select")]',
            'xpath://*[contains(text(),"手动选择")]',
            'xpath://button[contains(text(),"手动选择")]',
        ]
        
        for i, selector in enumerate(manual_select_selectors, 1):
            try:
                logger.info(f"尝试选择器 {i}: {selector}")
                element = self.tab.ele(selector, timeout=2)
                
                if element and element.states.is_displayed:
                    element.scroll.to_center()
                    time.sleep(0.3)
                    element.click(by_js=True)
                    time.sleep(0.8)
                    logger.info(f"✅ 成功点击手动选择按钮 (选择器 {i})")
                    return True
            except Exception as e:
                logger.debug(f"选择器 {i} 失败: {str(e)}")
                continue
        
        logger.error("❌ 所有手动选择按钮选择器都失败了")
        return False
    
    def _wait_for_category_selector(self, timeout: int = 6) -> bool:
        """
        等待类目选择器加载完成 - 优化版
        
        优化：减少超时时间和等待间隔
        
        Args:
            timeout: 超时时间（秒），默认从10秒优化为6秒
            
        Returns:
            bool: 是否加载成功
        """
        logger.info("等待类目选择器加载...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # 检查类目选择器是否已加载
                selectors_to_check = [
                    'xpath://div[contains(@class,"style_selectTree")]',
                    'xpath://div[contains(@class,"ecom-g-tree")]',
                    'xpath://span[text()="内衣裤袜"]',
                    'xpath://div[contains(@class,"style_catItem")]//span[text()="内衣裤袜"]'
                ]
                
                for selector in selectors_to_check:
                    element = self.tab.ele(selector, timeout=0.5)  # 优化：减少超时
                    if element and element.states.is_displayed:
                        logger.info("✅ 类目选择器加载完成")
                        return True
                        
                time.sleep(0.2)  # 优化：减少等待间隔
                
            except Exception as e:
                logger.debug(f"等待类目选择器时出错: {str(e)}")
                time.sleep(0.2)
        
        logger.error("❌ 类目选择器加载超时")
        return False
    
    def _perform_category_selection(self, category_name: str) -> bool:
        """
        执行具体的类目选择操作
        
        Args:
            category_name: 类目名称
            
        Returns:
            bool: 选择是否成功
        """
        logger.info(f"开始执行类目选择: 内衣裤袜 > 袜子 > {category_name}")
        
        try:
            # 步骤1: 选择一级类目 - 内衣裤袜
            if not self._select_first_level_category():
                return False
            
            # 步骤2: 选择二级类目 - 袜子
            if not self._select_second_level_category():
                return False
            
            # 步骤3: 选择三级类目 - 具体袜子类型
            if not self._select_third_level_category(category_name):
                return False
            
            # 步骤4: 点击确认/下一步
            if not self._confirm_selection():
                return False
            
            # 步骤5: 点击下一步进入商品信息页面
            if not self._click_next_step():
                logger.error("❌ 点击下一步失败")
                return False
            
            logger.info("✅ 类目选择流程完成")
            return True
            
        except Exception as e:
            logger.error(f"执行类目选择时发生错误: {str(e)}")
            return False
    
    def _select_first_level_category(self) -> bool:
        """选择一级类目：内衣裤袜"""
        logger.info("选择一级类目：内衣裤袜")
        
        selectors = [
            'xpath://div[contains(@class,"style_catItem")]//span[text()="内衣裤袜"]',
            'xpath://span[text()="内衣裤袜"]',
            'xpath://div[contains(@class,"ecom-g-tree-title")]//span[text()="内衣裤袜"]'
        ]
        
        for selector in selectors:
            try:
                element = self.tab.ele(selector, timeout=3)
                if element and element.states.is_displayed:
                    element.scroll.to_center()
                    time.sleep(0.2)
                    element.click(by_js=True)
                    time.sleep(0.5)
                    logger.info("✅ 成功选择一级类目：内衣裤袜")
                    return True
            except Exception as e:
                logger.debug(f"一级类目选择器失败: {selector}, 错误: {str(e)}")
                continue
        
        logger.error("❌ 选择一级类目失败")
        return False
    
    def _select_second_level_category(self) -> bool:
        """选择二级类目：袜子 - 优化版"""
        logger.info("选择二级类目：袜子")
        
        # 优化：减少等待时间
        time.sleep(0.2)
        
        selectors = [
            'xpath://span[text()="袜子"]',
            'xpath://div[contains(@class,"ecom-g-tree-title")]//span[text()="袜子"]',
            'xpath://*[contains(@class,"tree")]//span[text()="袜子"]'
        ]
        
        for selector in selectors:
            try:
                element = self.tab.ele(selector, timeout=2)  # 优化：减少超时
                if element and element.states.is_displayed:
                    element.scroll.to_center()
                    time.sleep(0.1)  # 优化：减少等待
                    element.click(by_js=True)
                    time.sleep(0.2)  # 优化：减少等待
                    logger.info("✅ 成功选择二级类目：袜子")
                    return True
            except Exception as e:
                logger.debug(f"二级类目选择器失败: {selector}, 错误: {str(e)}")
                continue
        
        logger.error("❌ 选择二级类目失败")
        return False
    
    def _select_third_level_category(self, category_name: str) -> bool:
        """选择三级类目：具体袜子类型 - 优化版"""
        logger.info(f"选择三级类目：{category_name}")
        
        # 优化：减少等待时间
        time.sleep(0.3)
        
        # 处理可能的搜索框遮挡问题
        try:
            search_box = self.tab.ele('xpath://input[@placeholder="搜索三级类目"]', timeout=0.5)
            if search_box:
                search_box.click()
                time.sleep(0.05)
        except:
            pass
        
        # 使用更精确的选择器，确保完全匹配类目名称
        selectors = [
            # 精确匹配文本内容，避免部分匹配导致的错误选择
            f'xpath://span[text()="{category_name}" and not(contains(@class,"disable"))]',
            f'xpath://div[contains(@class,"ecom-g-tree-title")]//span[text()="{category_name}" and not(contains(@class,"disable"))]',
            f'xpath://*[contains(@class,"tree")]//span[text()="{category_name}" and not(contains(@class,"disable"))]',
            f'xpath://div[contains(@class,"style_recomTag")]//span[text()="{category_name}"]',
            # 备用选择器，但仍然确保精确匹配
            f'xpath://*[text()="{category_name}" and not(contains(@class,"disable"))]'
        ]
        
        for i, selector in enumerate(selectors):
            try:
                logger.debug(f"尝试三级类目选择器 {i+1}: {selector}")
                element = self.tab.ele(selector, timeout=2)  # 优化：减少超时
                if element and element.states.is_displayed:
                    # 验证元素文本是否完全匹配
                    element_text = element.text.strip()
                    if element_text == category_name:
                        logger.info(f"找到精确匹配的三级类目: {element_text}")
                        element.scroll.to_center()
                        time.sleep(0.1)  # 优化：减少等待
                        element.click(by_js=True)
                        time.sleep(0.15)  # 优化：减少等待
                        logger.info(f"✅ 成功选择三级类目：{category_name}")
                        return True
                    else:
                        logger.debug(f"文本不匹配: 期望'{category_name}', 实际'{element_text}'")
            except Exception as e:
                logger.debug(f"三级类目选择器失败: {selector}, 错误: {str(e)}")
                continue
        
        # 如果直接选择失败，尝试从推荐标签中选择
        logger.info("尝试从智能推荐标签中选择...")
        try:
            # 查找智能推荐区域中的类目
            recommend_selectors = [
                f'xpath://div[contains(@class,"style_recomTag")]//div[contains(text(),"{category_name}")]',
                f'xpath://div[contains(@class,"style_recomTag")][contains(text(),"{category_name}")]',
                f'xpath://div[contains(@class,"style_items")]//div[contains(text(),"{category_name}")]'
            ]
            
            for selector in recommend_selectors:
                try:
                    element = self.tab.ele(selector, timeout=2)
                    if element and element.states.is_displayed:
                        element_text = element.text.strip()
                        if category_name in element_text:
                            logger.info(f"在推荐区域找到类目: {element_text}")
                            element.scroll.to_center()
                            time.sleep(0.2)
                            element.click(by_js=True)
                            time.sleep(0.3)
                            logger.info(f"✅ 从推荐区域成功选择：{category_name}")
                            return True
                except Exception as e:
                    logger.debug(f"推荐区域选择器失败: {selector}, 错误: {str(e)}")
                    continue
        except Exception as e:
            logger.debug(f"推荐区域选择失败: {str(e)}")
        
        logger.error(f"❌ 选择三级类目失败：{category_name}")
        return False
    
    def _confirm_selection(self) -> bool:
        """确认选择/点击确认按钮"""
        logger.info("确认类目选择")
        
        # 等待确认按钮出现
        time.sleep(0.4)
        
        # 基于用户提供的HTML结构，更新确认按钮选择器
        confirm_selectors = [
            # 根据用户提供的HTML结构：<button type="button" class="ecom-g-btn ecom-g-btn-primary"><span>确认</span></button>
            'xpath://div[contains(@class,"styles_modalFooterWrapper")]//button[contains(@class,"ecom-g-btn-primary")]//span[text()="确认"]/..',
            'xpath://button[contains(@class,"ecom-g-btn-primary")]//span[text()="确认"]/..',
            'xpath://div[contains(@class,"styles_btnWrapper")]//button[contains(@class,"ecom-g-btn-primary")]',
            'xpath://span[text()="确认"]/..',
            'xpath://button[contains(text(),"确认")]',
            'xpath://span[text()="确定"]/..',
            'xpath://button[contains(text(),"确定")]',
            'xpath://div[contains(@class,"modal-footer")]//button[contains(@class,"primary")]'
        ]
        
        for i, selector in enumerate(confirm_selectors):
            try:
                logger.debug(f"尝试确认按钮选择器 {i+1}: {selector}")
                element = self.tab.ele(selector, timeout=3)
                if element and element.states.is_displayed:
                    logger.info(f"找到确认按钮，使用选择器: {selector}")
                    element.scroll.to_center()
                    time.sleep(0.2)
                    element.click(by_js=True)
                    time.sleep(0.4)
                    logger.info("✅ 成功点击确认按钮")
                    
                    # 处理可能的提示弹窗
                    try:
                        popup_selectors = [
                            'xpath://*[text()="我知道了"]',
                            'xpath://button[contains(text(),"我知道了")]',
                            'xpath://span[text()="确定"]/..',
                            'xpath://button[contains(text(),"确定")]'
                        ]
                        for popup_selector in popup_selectors:
                            popup = self.tab.ele(popup_selector, timeout=1)
                            if popup and popup.states.is_displayed:
                                popup.click()
                                logger.info("处理了确认后的弹窗")
                                break
                    except:
                        pass
                    
                    return True
            except Exception as e:
                logger.debug(f"确认按钮选择器失败: {selector}, 错误: {str(e)}")
                continue
        
        logger.error("❌ 确认类目选择失败 - 未找到确认按钮")
        return False
    
    def _click_next_step(self) -> bool:
        """
        点击下一步按钮，进入商品信息填写页面 - 稳定增强版
        
        问题：JS点击可能不触发页面跳转
        解决：多种点击方式 + 验证页面是否真正跳转
        """
        logger.info("点击下一步按钮")
        
        # 所有可能的选择器
        all_selectors = [
            'xpath://button[contains(@class,"nextStep")]',
            'xpath://button[contains(@class,"style_nextStep")]',
            'xpath://div[contains(@class,"nextStepWrapper")]//button',
            'xpath://button[contains(@class,"ecom-g-btn-primary")]//span[text()="下一步"]/..',
            'xpath://span[text()="下一步"]/..',
            'xpath://button[.//span[text()="下一步"]]',
        ]
        
        next_btn = None
        for selector in all_selectors:
            try:
                element = self.tab.ele(selector, timeout=0.5)
                if element and element.states.is_displayed:
                    next_btn = element
                    logger.info(f"[OK] 找到下一步按钮")
                    break
            except:
                continue
        
        if not next_btn:
            logger.error("[ERROR] 未找到下一步按钮")
            return False
        
        # 先滚动到按钮可见位置
        next_btn.scroll.to_center()
        time.sleep(0.2)
        
        # 尝试多种点击方式
        click_methods = [
            ('普通点击', lambda: next_btn.click()),
            ('JS点击', lambda: next_btn.click(by_js=True)),
            ('模拟点击', lambda: self.tab.actions.click(next_btn)),
        ]
        
        for method_name, click_func in click_methods:
            try:
                logger.info(f"[尝试] {method_name}...")
                click_func()
                time.sleep(0.5)
                
                # 处理可能出现的弹窗
                
                # 验证是否真正跳转到第二页
                if self._wait_for_second_page(max_wait=5.0):
                    logger.info(f"[OK] {method_name}成功，第二页已加载")
                    return True
                else:
                    logger.warning(f"[WARN] {method_name}后页面未跳转，尝试下一种方式")
                    # 如果没跳转，可能是因为有验证失败，检查错误提示
                    self._check_and_handle_error()
                    
            except Exception as e:
                logger.warning(f"[WARN] {method_name}失败: {e}")
                continue
        
        # 最后一次尝试：强制JS执行点击
        try:
            logger.info("[尝试] 强制JS执行点击...")
            self.tab.run_js('document.querySelector("button[class*=nextStep]")?.click()')
            time.sleep(0.5)
            self._handle_post_click_popup()
            if self._wait_for_second_page(max_wait=5.0):
                logger.info("[OK] 强制JS点击成功")
                return True
        except:
            pass
        
        logger.error("[ERROR] 所有点击方式都失败，页面未跳转")
        return False
    
    def _check_and_handle_error(self):
        """检查并处理页面上的错误提示"""
        try:
            # 查找错误提示
            error_selectors = [
                'xpath://div[contains(@class,"ecom-g-message-error")]',
                'xpath://div[contains(@class,"error")]//span',
                'xpath://div[contains(@class,"toast")]',
            ]
            for sel in error_selectors:
                try:
                    err = self.tab.ele(sel, timeout=0.3)
                    if err and err.states.is_displayed:
                        logger.warning(f"[错误提示] {err.text}")
                except:
                    continue
        except:
            pass
    
    def _wait_for_second_page(self, max_wait: float = 10.0) -> bool:
        """
        等待第二页（商品详情编辑页面）加载完成
        
        Args:
            max_wait: 最大等待时间（秒）
            
        Returns:
            bool: 页面是否加载成功
        """
        logger.info("等待第二页加载...")
        
        # 第二页的特征元素选择器
        second_page_selectors = [
            # 基础信息区域
            'xpath://div[@id="goodsEditScrollContainer-基础信息"]',
            'xpath://div[contains(@class,"formBlockNewUI")]',
            # 主图3:4 区域
            'xpath://span[text()="主图3:4"]',
            'xpath://span[contains(text(),"主图3:4")]',
            # 主图视频区域
            'xpath://span[text()="主图视频"]',
            # 商品类目显示区域（第二页有修改按钮）
            'xpath://div[contains(@class,"formBlockNewUI")]//span[text()="修改"]',
            # 类目属性区域
            'xpath://div[contains(text(),"类目属性")]',
        ]
        
        start_time = time.time()
        check_interval = 0.3  # 检查间隔
        
        while time.time() - start_time < max_wait:
            for selector in second_page_selectors:
                try:
                    element = self.tab.ele(selector, timeout=0.2)
                    if element and element.states.is_displayed:
                        logger.info(f"[OK] 检测到第二页元素: {selector[:50]}...")
                        time.sleep(0.5)  # 额外等待页面稳定
                        return True
                except:
                    continue
            time.sleep(check_interval)
        
        logger.warning(f"[WARN] 等待第二页超时 ({max_wait}s)，继续执行...")
        return False
    
    def _handle_post_click_popup(self):
        """处理点击下一步后可能出现的弹窗"""
        try:
            popup_selectors = [
                'xpath://*[text()="我知道了"]',
                'xpath://button[contains(text(),"我知道了")]',
                'xpath://span[text()="我知道了"]/..',
            ]
            for popup_selector in popup_selectors:
                try:
                    popup = self.tab.ele(popup_selector, timeout=0.5)
                    if popup and popup.states.is_displayed:
                        popup.click()
                        logger.info("处理了下一步后的弹窗")
                        break
                except:
                    pass
        except:
            pass


def smart_select_category(tab, category_code: str) -> bool:
    """
    智能类目选择的便捷函数
    
    Args:
        tab: DrissionPage标签页对象
        category_code: 类目代码 ('0', '1', '2', '3', '4')
        
    Returns:
        bool: 选择是否成功
    """
    selector = EnhancedCategorySelector(tab)
    return selector.select_category(category_code)



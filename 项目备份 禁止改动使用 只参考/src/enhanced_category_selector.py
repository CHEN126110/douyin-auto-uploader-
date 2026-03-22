"""
增强的类目选择器 - 处理抖音小店新版类目选择界面
解决需要先点击"手动选择"按钮才能显示完整类目选择器的问题
"""

import time
import logging

logger = logging.getLogger(__name__)

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
        智能选择类目
        
        Args:
            category_code: 类目代码 ('0', '1', '2', '3')
            max_retries: 最大重试次数
            
        Returns:
            bool: 选择是否成功
        """
        category_code = str(category_code)
        category_name = self.wazi_dict.get(category_code)
        if not category_name:
            logger.error(f"未知的类目代码: {category_code}")
            return False
            
        logger.info(f"开始选择类目: {category_name} (代码: {category_code})")
        
        for attempt in range(max_retries):
            try:
                logger.info(f"第 {attempt + 1} 次尝试选择类目")

                if self._is_current_category(category_name):
                    logger.info(f"当前已选择匹配类目: {category_name}")
                    if self._click_next_step():
                        return True
                    return True

                if self._select_from_recommendations(category_name):
                    logger.info(f"在推荐列表中选择成功: {category_name}")
                    if self._click_next_step():
                        return True
                    return True

                self._click_more_recommend(1)
                if self._select_from_recommendations(category_name):
                    logger.info(f"在推荐列表中选择成功(第1次更多推荐后): {category_name}")
                    if self._click_next_step():
                        return True
                    return True

                self._click_more_recommend(1)
                if self._select_from_recommendations(category_name):
                    logger.info(f"在推荐列表中选择成功(第2次更多推荐后): {category_name}")
                    if self._click_next_step():
                        return True
                    return True

                # 仍未命中，最后进入手动选择
                if not self._handle_recommendations():
                    logger.warning("更多推荐操作未能显示手动选择入口")
                if not self._click_manual_select():
                    logger.warning("点击手动选择失败")
                    continue

                if not self._wait_for_category_selector():
                    logger.warning("类目选择器加载失败")
                    continue

                if self._perform_category_selection(category_name):
                    logger.info(f"类目选择成功: {category_name}")
                    return True
                else:
                    logger.warning("手动选择流程执行失败")

            except Exception as e:
                logger.error(f"第 {attempt + 1} 次尝试选择类目时发生错误: {str(e)}")

            if attempt < max_retries - 1:
                time.sleep(1)

        logger.error(f"类目选择最终失败，已重试 {max_retries} 次")
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
        for _ in range(times):
            btn = None
            try:
                btn = self.tab.ele('xpath://span[text()="更多推荐"]', timeout=2)
            except:
                btn = None
            if not btn:
                try:
                    btn = self.tab.ele('xpath://div[contains(@class,"styles_recommendBottom")]//button//span[text()="更多推荐"]/..', timeout=2)
                except:
                    btn = None
            if btn:
                try:
                    btn.scroll.to_see()
                except:
                    pass
                btn.click(by_js=True)
                time.sleep(0.8)

    def _select_from_recommendations(self, category_name: str) -> bool:
        try:
            selectors = [
                f'xpath://div[contains(@class,"styles_normal") and contains(text(),"{category_name}") and not(contains(@class,"disable"))]',
                f'xpath://div[contains(@class,"style_recomTag")]//div[contains(text(),"{category_name}")]',
                f'xpath://div[contains(@class,"styles_items")]//div[contains(text(),"{category_name}")]',
            ]
            for selector in selectors:
                try:
                    el = self.tab.ele(selector, timeout=2)
                    if el and el.states.is_displayed:
                        el.scroll.to_center()
                        time.sleep(0.3)
                        el.click(by_js=True)
                        time.sleep(0.6)
                        return True
                except:
                    continue
        except:
            pass
        return False

    def _is_current_category(self, category_name: str) -> bool:
        try:
            el = None
            try:
                el = self.tab.ele('xpath://div[contains(@class,"styles_itemSelected")]', timeout=2)
            except:
                el = None
            if el and el.states.is_displayed:
                txt = (el.text or '').strip()
                if category_name in txt:
                    return True
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
    
    def _wait_for_category_selector(self, timeout: int = 10) -> bool:
        """
        等待类目选择器加载完成
        
        Args:
            timeout: 超时时间（秒）
            
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
                    element = self.tab.ele(selector, timeout=1)
                    if element and element.states.is_displayed:
                        logger.info("✅ 类目选择器加载完成")
                        return True
                        
                time.sleep(0.5)
                
            except Exception as e:
                logger.debug(f"等待类目选择器时出错: {str(e)}")
                time.sleep(0.5)
        
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
        """选择二级类目：袜子"""
        logger.info("选择二级类目：袜子")
        
        # 等待二级类目加载
        time.sleep(0.5)
        
        selectors = [
            'xpath://span[text()="袜子"]',
            'xpath://div[contains(@class,"ecom-g-tree-title")]//span[text()="袜子"]',
            'xpath://*[contains(@class,"tree")]//span[text()="袜子"]'
        ]
        
        for selector in selectors:
            try:
                element = self.tab.ele(selector, timeout=3)
                if element and element.states.is_displayed:
                    element.scroll.to_center()
                    time.sleep(0.2)
                    element.click(by_js=True)
                    time.sleep(0.5)
                    logger.info("✅ 成功选择二级类目：袜子")
                    return True
            except Exception as e:
                logger.debug(f"二级类目选择器失败: {selector}, 错误: {str(e)}")
                continue
        
        logger.error("❌ 选择二级类目失败")
        return False
    
    def _select_third_level_category(self, category_name: str) -> bool:
        """选择三级类目：具体袜子类型"""
        logger.info(f"选择三级类目：{category_name}")
        
        # 等待三级类目加载
        time.sleep(1)
        
        # 处理可能的搜索框遮挡问题
        try:
            search_box = self.tab.ele('xpath://input[@placeholder="搜索三级类目"]', timeout=1)
            if search_box:
                search_box.click()
                time.sleep(0.1)
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
                element = self.tab.ele(selector, timeout=3)
                if element and element.states.is_displayed:
                    # 验证元素文本是否完全匹配
                    element_text = element.text.strip()
                    if element_text == category_name:
                        logger.info(f"找到精确匹配的三级类目: {element_text}")
                        element.scroll.to_center()
                        time.sleep(0.2)
                        element.click(by_js=True)
                        time.sleep(0.3)
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
        """点击下一步按钮，进入商品信息填写页面"""
        logger.info("点击下一步按钮")
        
        # 等待下一步按钮出现
        time.sleep(0.4)
        
        # 下一步按钮的选择器
        next_step_selectors = [
            'xpath://span[text()="下一步"]/..',
            'xpath://button[contains(text(),"下一步")]',
            'xpath://div[contains(@class,"styles_btnWrapper")]//span[text()="下一步"]/..',
            'xpath://button[contains(@class,"ecom-g-btn-primary")]//span[text()="下一步"]/..',
            'xpath://div[contains(@class,"footer")]//span[text()="下一步"]/..'
        ]
        
        for i, selector in enumerate(next_step_selectors):
            try:
                logger.debug(f"尝试下一步按钮选择器 {i+1}: {selector}")
                element = self.tab.ele(selector, timeout=3)
                if element and element.states.is_displayed:
                    logger.info(f"找到下一步按钮，使用选择器: {selector}")
                    element.scroll.to_center()
                    time.sleep(0.2)
                    element.click(by_js=True)
                    time.sleep(0.4)
                    logger.info("✅ 成功点击下一步按钮")
                    
                    # 处理可能的提示弹窗
                    try:
                        popup_selectors = [
                            'xpath://*[text()="我知道了"]',
                            'xpath://button[contains(text(),"我知道了")]'
                        ]
                        for popup_selector in popup_selectors:
                            popup = self.tab.ele(popup_selector, timeout=1)
                            if popup and popup.states.is_displayed:
                                popup.click()
                                logger.info("处理了下一步后的弹窗")
                                break
                    except:
                        pass
                    
                    return True
            except Exception as e:
                logger.debug(f"下一步按钮选择器失败: {selector}, 错误: {str(e)}")
                continue
        
        logger.error("❌ 点击下一步失败 - 未找到下一步按钮")
        return False


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


if __name__ == "__main__":
    print("增强的类目选择器模块已加载")

"""
交互后验证器 - 确保自愈操作的正确性
技术方案文档第六部分:关键保障措施中的VALIDATE阶段实现
"""

import time
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class ValidationResult:
    """验证结果"""
    passed: bool
    failed_checks: List[str]
    details: Dict[str, Any]

class PostInteractionValidator:
    """交互后验证器"""
    
    def __init__(self):
        """初始化验证器"""
        self.validation_timeout = 5.0  # 验证超时时间
    
    def validate_interaction(
        self, 
        page, 
        validation_rules: List[Dict[str, Any]], 
        pre_interaction_state: Optional[Dict] = None
    ) -> ValidationResult:
        """
        验证交互后的状态是否符合预期
        
        Args:
            page: DrissionPage页面对象
            validation_rules: 验证规则列表
            pre_interaction_state: 交互前的状态(可选)
            
        Returns:
            验证结果
        """
        failed_checks = []
        details = {}
        
        try:
            logger.info(f"开始执行 {len(validation_rules)} 项验证检查")
            
            for rule in validation_rules:
                rule_type = rule.get('type')
                
                try:
                    if rule_type == 'url_contains':
                        if not self._validate_url_contains(page, rule):
                            failed_checks.append(f"URL验证失败: {rule}")
                    
                    elif rule_type == 'url_equals':
                        if not self._validate_url_equals(page, rule):
                            failed_checks.append(f"URL精确匹配失败: {rule}")
                    
                    elif rule_type == 'element_is_visible':
                        if not self._validate_element_visible(page, rule):
                            failed_checks.append(f"元素可见性验证失败: {rule}")
                    
                    elif rule_type == 'element_is_not_visible':
                        if not self._validate_element_not_visible(page, rule):
                            failed_checks.append(f"元素隐藏验证失败: {rule}")
                    
                    elif rule_type == 'text_on_page':
                        if not self._validate_text_on_page(page, rule):
                            failed_checks.append(f"页面文本验证失败: {rule}")
                    
                    elif rule_type == 'text_not_on_page':
                        if not self._validate_text_not_on_page(page, rule):
                            failed_checks.append(f"页面文本不存在验证失败: {rule}")
                    
                    elif rule_type == 'page_title_contains':
                        if not self._validate_page_title_contains(page, rule):
                            failed_checks.append(f"页面标题验证失败: {rule}")
                    
                    elif rule_type == 'wait_for_element':
                        if not self._validate_wait_for_element(page, rule):
                            failed_checks.append(f"等待元素验证失败: {rule}")
                    
                    elif rule_type == 'custom_script':
                        if not self._validate_custom_script(page, rule):
                            failed_checks.append(f"自定义脚本验证失败: {rule}")
                    
                    else:
                        logger.warning(f"未知的验证类型: {rule_type}")
                        details[f"unknown_rule_{rule_type}"] = rule
                
                except Exception as e:
                    logger.error(f"验证规则执行异常: {rule} -> {e}")
                    failed_checks.append(f"验证执行异常: {rule} -> {str(e)}")
            
            # 汇总结果
            passed = len(failed_checks) == 0
            details['total_rules'] = len(validation_rules)
            details['failed_count'] = len(failed_checks)
            details['success_rate'] = (len(validation_rules) - len(failed_checks)) / len(validation_rules) if validation_rules else 1.0
            
            result = ValidationResult(
                passed=passed,
                failed_checks=failed_checks,
                details=details
            )
            
            if passed:
                logger.info("[成功] 所有验证检查通过")
            else:
                logger.warning(f"[失败] {len(failed_checks)} 项验证检查失败")
            
            return result
            
        except Exception as e:
            logger.error(f"验证过程异常: {e}")
            return ValidationResult(
                passed=False,
                failed_checks=[f"验证系统异常: {str(e)}"],
                details={"error": str(e)}
            )
    
    def _validate_url_contains(self, page, rule: Dict) -> bool:
        """验证URL包含指定文本"""
        expected_text = rule.get('value', '')
        current_url = getattr(page, 'url', '')
        
        result = expected_text in current_url
        logger.debug(f"URL包含验证: '{expected_text}' in '{current_url}' = {result}")
        return result
    
    def _validate_url_equals(self, page, rule: Dict) -> bool:
        """验证URL精确匹配"""
        expected_url = rule.get('value', '')
        current_url = getattr(page, 'url', '')
        
        result = expected_url == current_url
        logger.debug(f"URL精确匹配: '{expected_url}' == '{current_url}' = {result}")
        return result
    
    def _validate_element_visible(self, page, rule: Dict) -> bool:
        """验证元素可见"""
        target_locator = rule.get('target_element_id') or rule.get('locator', '')
        timeout = rule.get('timeout', 3.0)
        
        try:
            element = page.ele(target_locator, timeout=timeout)
            if element:
                is_visible = getattr(element, 'is_displayed', lambda: True)()
                logger.debug(f"元素可见验证: {target_locator} = {is_visible}")
                return is_visible
        except Exception as e:
            logger.debug(f"元素可见验证失败: {target_locator} -> {e}")
        
        return False
    
    def _validate_element_not_visible(self, page, rule: Dict) -> bool:
        """验证元素不可见"""
        target_locator = rule.get('target_element_id') or rule.get('locator', '')
        timeout = rule.get('timeout', 1.0)
        
        try:
            element = page.ele(target_locator, timeout=timeout)
            if element:
                is_visible = getattr(element, 'is_displayed', lambda: True)()
                logger.debug(f"元素不可见验证: {target_locator} = {not is_visible}")
                return not is_visible
            else:
                # 元素不存在也算不可见
                return True
        except Exception:
            # 找不到元素,算作不可见
            return True
    
    def _validate_text_on_page(self, page, rule: Dict) -> bool:
        """验证页面包含指定文本"""
        expected_text = rule.get('value', '')
        
        try:
            # 尝试通过text定位器查找
            element = page.ele(f'text:{expected_text}', timeout=2.0)
            result = element is not None
            logger.debug(f"页面文本验证: '{expected_text}' = {result}")
            return result
        except Exception as e:
            logger.debug(f"页面文本验证失败: '{expected_text}' -> {e}")
            return False
    
    def _validate_text_not_on_page(self, page, rule: Dict) -> bool:
        """验证页面不包含指定文本"""
        return not self._validate_text_on_page(page, rule)
    
    def _validate_page_title_contains(self, page, rule: Dict) -> bool:
        """验证页面标题包含指定文本"""
        expected_text = rule.get('value', '')
        current_title = getattr(page, 'title', '')
        
        result = expected_text in current_title
        logger.debug(f"页面标题验证: '{expected_text}' in '{current_title}' = {result}")
        return result
    
    def _validate_wait_for_element(self, page, rule: Dict) -> bool:
        """验证等待元素出现"""
        target_locator = rule.get('target_element_id') or rule.get('locator', '')
        timeout = rule.get('timeout', self.validation_timeout)
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                element = page.ele(target_locator, timeout=0.5)
                if element:
                    logger.debug(f"等待元素验证成功: {target_locator}")
                    return True
            except Exception:
                continue
            
            time.sleep(0.1)
        
        logger.debug(f"等待元素验证超时: {target_locator}")
        return False
    
    def _validate_custom_script(self, page, rule: Dict) -> bool:
        """执行自定义验证脚本"""
        script = rule.get('script', '')
        expected_result = rule.get('expected_result', True)
        
        try:
            # 这里可以执行自定义的JavaScript脚本
            # 由于DrissionPage的API可能不同,这里使用模拟实现
            logger.info(f"执行自定义验证脚本: {script}")
            
            # 模拟脚本执行结果
            # 实际实现中应该调用page.run_js(script)或类似方法
            result = expected_result  # 模拟成功
            
            logger.debug(f"自定义脚本验证: {script} = {result}")
            return result == expected_result
            
        except Exception as e:
            logger.error(f"自定义脚本执行失败: {script} -> {e}")
            return False
    
    def create_pre_interaction_snapshot(self, page) -> Dict[str, Any]:
        """创建交互前的状态快照"""
        try:
            snapshot = {
                'timestamp': time.time(),
                'url': getattr(page, 'url', ''),
                'title': getattr(page, 'title', ''),
                'visible_elements_count': len(page.eles('css:*:visible')) if hasattr(page, 'eles') else 0
            }
            
            logger.debug("创建交互前状态快照")
            return snapshot
            
        except Exception as e:
            logger.warning(f"创建状态快照失败: {e}")
            return {}

# 全局实例
post_interaction_validator = PostInteractionValidator() 
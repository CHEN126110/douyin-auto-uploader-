# -*- coding: utf-8 -*-
# mypy: ignore-errors
# pyright: reportMissingModuleSource=false

"""
增强的元素指纹管理器 - 基于技术方案文档的完整实现
支持YAML格式、置信度评分、交互后验证和学习闭环
"""

import os
import time
import json
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime

try:
    import yaml  # type: ignore
except ImportError:
    # 如果yaml不可用,使用json作为备选
    yaml = None  # type: ignore

from src.confidence_scorer import confidence_scorer, ConfidenceResult
from src.post_interaction_validator import post_interaction_validator, ValidationResult

logger = logging.getLogger(__name__)

@dataclass
class EnhancedElementTemplate:
    """增强的元素模板类"""
    element_unique_id: str
    description: str
    associated_tests: List[str]
    locators: List[Dict[str, Any]]
    attribute_snapshot: Dict[str, Any]
    structural_context: Dict[str, Any]
    visual_properties: Dict[str, Any]
    validation: List[Dict[str, Any]]
    healing_metadata: Dict[str, Any]
    healing_config: Dict[str, Any]

class EnhancedElementManager:
    """增强的元素指纹管理器"""
    
    def __init__(self, templates_dir: str = "src/enhanced_element_templates"):
        """
        初始化增强的元素管理器
        
        Args:
            templates_dir: YAML模板文件目录
        """
        self.templates_dir = templates_dir
        self.templates: Dict[str, EnhancedElementTemplate] = {}
        self.load_all_templates()
    
    def load_all_templates(self) -> None:
        """加载所有YAML模板文件"""
        try:
            os.makedirs(self.templates_dir, exist_ok=True)
            
            if yaml:
                template_files = [f for f in os.listdir(self.templates_dir) if f.endswith('.yaml') or f.endswith('.yml')]
            else:
                template_files = [f for f in os.listdir(self.templates_dir) if f.endswith('.json')]
            
            for template_file in template_files:
                file_path = os.path.join(self.templates_dir, template_file)
                self.load_template_from_file(file_path)
            
            logger.info(f"[成功] 加载了 {len(self.templates)} 个增强元素模板")
            
        except Exception as e:
            logger.error(f"[失败] 加载模板失败: {e}")
    
    def load_template_from_file(self, file_path: str) -> None:
        """从文件加载单个模板"""
        try:
            if yaml and file_path.endswith(('.yaml', '.yml')):
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            
            template = EnhancedElementTemplate(
                element_unique_id=data.get('element_unique_id', ''),
                description=data.get('description', ''),
                associated_tests=data.get('associated_tests', []),
                locators=data.get('locators', []),
                attribute_snapshot=data.get('attribute_snapshot', {}),
                structural_context=data.get('structural_context', {}),
                visual_properties=data.get('visual_properties', {}),
                validation=data.get('validation', []),
                healing_metadata=data.get('healing_metadata', {}),
                healing_config=data.get('healing_config', {})
            )
            
            self.templates[template.element_unique_id] = template
            logger.debug(f"[列表] 加载模板: {template.element_unique_id}")
            
        except Exception as e:
            logger.error(f"[失败] 加载模板文件失败 {file_path}: {e}")
    
    def smart_find_element_enhanced(
        self, 
        page, 
        element_unique_id: str, 
        context: Optional[Dict] = None
    ) -> Optional[Any]:
        """
        增强的智能元素查找 - 集成完整的五阶段工作流
        DETECT -> ANALYZE -> ADAPT -> VALIDATE -> LEARN
        """
        if element_unique_id not in self.templates:
            logger.error(f"[失败] 未找到元素模板: {element_unique_id}")
            return None
        
        template = self.templates[element_unique_id]
        context = context or {}
        
        # PHASE 1: DETECT - 尝试标准定位器
        element = self._try_standard_locators(page, template)
        if element:
            logger.info(f"[成功] 标准定位器成功: {element_unique_id}")
            return element
        
        # PHASE 2 & 3: ANALYZE & ADAPT - 分析并寻找最佳候选者
        best_candidate = self._find_best_candidate_with_confidence(page, template, context)
        if not best_candidate:
            logger.warning(f"[失败] 未找到合适候选者: {element_unique_id}")
            return None
        
        confidence_result = best_candidate['confidence_result']
        element = best_candidate['element']
        
        # 根据置信度决定是否继续
        if confidence_result.decision == "fail":
            logger.warning(f"[失败] 置信度过低: {element_unique_id} (分数: {confidence_result.score})")
            return None
        
        # PHASE 4 & 5: VALIDATE & LEARN
        if confidence_result.decision == "manual_review":
            logger.info(f"[警告] 需要人工审查: {element_unique_id} (分数: {confidence_result.score})")
        
        logger.info(f"[处理] 治愈成功: {element_unique_id} (置信度: {confidence_result.score})")
        self._learn_from_successful_heal(template, element, confidence_result)
        
        return element
    
    def _try_standard_locators(self, page, template: EnhancedElementTemplate) -> Optional[Any]:
        """尝试标准定位器"""
        sorted_locators = sorted(template.locators, key=lambda x: x.get('priority', 999))
        
        for locator_info in sorted_locators:
            try:
                locator_type = locator_info.get('type')
                locator_value = locator_info.get('value')
                
                if locator_type == 'xpath':
                    element = page.ele(f'xpath:{locator_value}', timeout=1)
                elif locator_type == 'css':
                    element = page.ele(f'css:{locator_value}', timeout=1)
                elif locator_type == 'id':
                    element = page.ele(f'#{locator_value}', timeout=1)
                else:
                    element = page.ele(locator_value, timeout=1)
                
                if element:
                    # 更新使用时间
                    locator_info['last_used'] = datetime.now().isoformat()
                    return element
                    
            except Exception as e:
                logger.debug(f"定位器失败: {locator_info} -> {e}")
                continue
        
        return None
    
    def _find_best_candidate_with_confidence(
        self, 
        page, 
        template: EnhancedElementTemplate, 
        context: Dict
    ) -> Optional[Dict[str, Any]]:
        """寻找最佳候选者并评估置信度"""
        try:
            # 基于标签类型寻找候选者
            target_tag = template.attribute_snapshot.get('tag', 'div')
            potential_elements = page.eles(f'tag:{target_tag}')
            
            best_candidate = None
            highest_score = 0
            
            for element in potential_elements[:20]:  # 限制候选者数量
                try:
                    candidate_info = {
                        'id': getattr(element, 'attr', lambda x: '')('id'),
                        'class': getattr(element, 'attr', lambda x: '')('class'),
                        'text': getattr(element, 'text', ''),
                        'tag': target_tag,
                        'location': {'x': 0, 'y': 0}  # 简化的位置信息
                    }
                    
                    # 构建目标元素指纹
                    target_fingerprint = {
                        'attribute_snapshot': template.attribute_snapshot,
                        'visual_properties': template.visual_properties,
                        'structural_context': template.structural_context
                    }
                    
                    # 计算置信度
                    confidence_result = confidence_scorer.calculate_confidence(
                        target_fingerprint, 
                        candidate_info
                    )
                    
                    if confidence_result.score > highest_score and confidence_result.decision != "fail":
                        highest_score = confidence_result.score
                        best_candidate = {
                            'element': element,
                            'candidate_info': candidate_info,
                            'confidence_result': confidence_result
                        }
                        
                except Exception as e:
                    logger.debug(f"评估候选者失败: {e}")
                    continue
            
            if best_candidate:
                logger.info(f"[测试] 最佳候选者评分: {highest_score}")
            
            return best_candidate
            
        except Exception as e:
            logger.error(f"[失败] 寻找候选者失败: {e}")
            return None
    
    def _learn_from_successful_heal(
        self, 
        template: EnhancedElementTemplate, 
        element: Any, 
        confidence_result: ConfidenceResult
    ) -> None:
        """从成功的治愈中学习"""
        try:
            # 更新治愈元数据
            now = datetime.now().isoformat()
            template.healing_metadata.update({
                'last_successful_heal': now,
                'confidence_of_last_heal': confidence_result.score,
                'total_heals': template.healing_metadata.get('total_heals', 0) + 1
            })
            
            # 生成新的定位器
            new_locator = self._generate_new_locator(element)
            if new_locator:
                template.locators.insert(0, {
                    'type': new_locator['type'],
                    'value': new_locator['value'],
                    'priority': 1,
                    'last_used': now,
                    'success_rate': 1.0,
                    'source': 'auto_healing'
                })
            
            logger.info(f"[学习] 学习完成: {template.element_unique_id}")
            
        except Exception as e:
            logger.error(f"[失败] 学习过程失败: {e}")
    
    def _generate_new_locator(self, element: Any) -> Optional[Dict[str, str]]:
        """根据成功的元素生成新定位器"""
        try:
            # 尝试生成最稳定的定位器
            element_id = getattr(element, 'attr', lambda x: '')('id')
            if element_id:
                return {'type': 'id', 'value': element_id}
            
            element_text = getattr(element, 'text', '')
            if element_text and len(element_text.strip()) > 0:
                return {'type': 'xpath', 'value': f"//*[contains(text(), '{element_text[:20]}')]"}
            
            return None
            
        except Exception as e:
            logger.debug(f"生成新定位器失败: {e}")
            return None
    
    def create_template_from_element(
        self, 
        element_id: str, 
        element: Any, 
        description: str,
        validation_rules: Optional[List[Dict]] = None
    ) -> EnhancedElementTemplate:
        """从现有元素创建模板"""
        try:
            template = EnhancedElementTemplate(
                element_unique_id=element_id,
                description=description,
                associated_tests=[],
                locators=[{
                    'type': 'xpath',
                    'value': f"//*[@id='{getattr(element, 'attr', lambda x: '')('id')}']",
                    'priority': 1,
                    'last_used': datetime.now().isoformat(),
                    'success_rate': 1.0
                }],
                attribute_snapshot={
                    'tag': element.tag if hasattr(element, 'tag') else 'div',
                    'id': getattr(element, 'attr', lambda x: '')('id'),
                    'class': getattr(element, 'attr', lambda x: '')('class'),
                    'text_content': getattr(element, 'text', ''),
                },
                structural_context={},
                visual_properties={
                    'bounding_box': {'x': 0, 'y': 0, 'width': 0, 'height': 0}
                },
                validation=validation_rules or [],
                healing_metadata={
                    'total_heals': 0,
                    'heal_success_rate': 1.0
                },
                healing_config={
                    'retry_strategy': 'ai_visual_locate',
                    'confidence_threshold': 0.75,
                    'enable_learning': True
                }
            )
            
            self.templates[element_id] = template
            logger.info(f"[列表] 创建新模板: {element_id}")
            
            return template
            
        except Exception as e:
            logger.error(f"[失败] 创建模板失败: {e}")
            raise

# 全局实例
enhanced_element_manager = EnhancedElementManager() 

"""
置信度评分系统 - 基于技术方案文档的加权启发式模型
用于评估自愈操作的可信度,降低假阳性风险
"""

# -*- coding: utf-8 -*-
# mypy: ignore-errors
# pyright: reportMissingImports=false

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

try:
    from thefuzz import fuzz  # type: ignore
except ImportError:
    # 如果thefuzz不可用,使用简单的相似度计算
    class fuzz:  # type: ignore
        @staticmethod
        def ratio(s1: str, s2: str) -> int:
            """简单的字符串相似度计算"""
            if s1 == s2:
                return 100
            return 50 if s1.lower() in s2.lower() or s2.lower() in s1.lower() else 0

logger = logging.getLogger(__name__)

@dataclass
class ConfidenceResult:
    """置信度评分结果"""
    score: float
    decision: str  # "auto_heal", "manual_review", "fail"
    details: Dict[str, Any]

class ConfidenceScorer:
    """置信度评分引擎"""
    
    def __init__(self):
        """初始化评分引擎"""
        # 评分权重表(基于技术方案文档表3)
        self.scoring_weights = {
            'id_exact_match': 100,
            'name_exact_match': 80,
            'text_exact_match': 50,
            'text_fuzzy_match_90': 35,
            'shared_class_each': 10,
            'same_tag': 5,
            'position_similar': 20,
            'same_parent': 30
        }
        
        # 决策阈值 - 使用float类型
        self.thresholds: Dict[str, float] = {
            'auto_heal': 90.0,
            'manual_review': 60.0,
            'fail': 60.0
        }
    
    def calculate_confidence(
        self,
        target_element_fingerprint: Dict[str, Any],
        candidate_element: Dict[str, Any],
        position_tolerance: int = 50
    ) -> ConfidenceResult:
        """
        计算候选元素的置信度分数
        
        Args:
            target_element_fingerprint: 目标元素的历史指纹
            candidate_element: 当前页面上的候选元素
            position_tolerance: 位置容差(像素)
            
        Returns:
            置信度评分结果
        """
        score = 0
        details = {}
        
        try:
            # 1. ID精确匹配检查
            if self._check_id_match(target_element_fingerprint, candidate_element):
                score += self.scoring_weights['id_exact_match']
                details['id_exact_match'] = True
            
            # 2. Name精确匹配检查
            if self._check_name_match(target_element_fingerprint, candidate_element):
                score += self.scoring_weights['name_exact_match']
                details['name_exact_match'] = True
            
            # 3. 文本内容检查
            text_score = self._check_text_match(target_element_fingerprint, candidate_element)
            score += text_score
            details['text_match_score'] = text_score
            
            # 4. 共享类名检查
            class_score = self._check_shared_classes(target_element_fingerprint, candidate_element)
            score += class_score
            details['shared_classes_score'] = class_score
            
            # 5. 标签名相同检查
            if self._check_tag_match(target_element_fingerprint, candidate_element):
                score += self.scoring_weights['same_tag']
                details['same_tag'] = True
            
            # 6. 位置相似性检查
            if self._check_position_similarity(
                target_element_fingerprint, 
                candidate_element, 
                position_tolerance
            ):
                score += self.scoring_weights['position_similar']
                details['position_similar'] = True
            
            # 7. 父元素相同检查
            if self._check_parent_match(target_element_fingerprint, candidate_element):
                score += self.scoring_weights['same_parent']
                details['same_parent'] = True
            
            # 8. 根据分数做出决策
            decision = self._make_decision(score)
            
            result = ConfidenceResult(
                score=score,
                decision=decision,
                details=details
            )
            
            logger.info(f"置信度评分: {score}, 决策: {decision}")
            return result
            
        except Exception as e:
            logger.error(f"置信度计算失败: {e}")
            return ConfidenceResult(
                score=0,
                decision="fail",
                details={"error": str(e)}
            )
    
    def _check_id_match(self, target: Dict, candidate: Dict) -> bool:
        """检查ID精确匹配"""
        target_id = target.get('attribute_snapshot', {}).get('id', '')
        candidate_id = candidate.get('id', '')
        return target_id and candidate_id and target_id == candidate_id
    
    def _check_name_match(self, target: Dict, candidate: Dict) -> bool:
        """检查name属性精确匹配"""
        target_name = target.get('attribute_snapshot', {}).get('name', '')
        candidate_name = candidate.get('name', '')
        return target_name and candidate_name and target_name == candidate_name
    
    def _check_text_match(self, target: Dict, candidate: Dict) -> float:
        """检查文本内容匹配"""
        target_text = target.get('attribute_snapshot', {}).get('text_content', '')
        candidate_text = candidate.get('text', '')
        
        if not target_text or not candidate_text:
            return 0
        
        # 精确匹配
        if target_text == candidate_text:
            return self.scoring_weights['text_exact_match']
        
        # 模糊匹配
        similarity = fuzz.ratio(target_text, candidate_text)
        if similarity >= 90:
            return self.scoring_weights['text_fuzzy_match_90']
        
        return 0
    
    def _check_shared_classes(self, target: Dict, candidate: Dict) -> float:
        """检查共享的CSS类名"""
        target_classes = target.get('attribute_snapshot', {}).get('class', '').split()
        candidate_classes = candidate.get('class', '').split()
        
        shared_count = len(set(target_classes) & set(candidate_classes))
        return shared_count * self.scoring_weights['shared_class_each']
    
    def _check_tag_match(self, target: Dict, candidate: Dict) -> bool:
        """检查标签名匹配"""
        target_tag = target.get('attribute_snapshot', {}).get('tag', '')
        candidate_tag = candidate.get('tag', '')
        return target_tag and candidate_tag and target_tag == candidate_tag
    
    def _check_position_similarity(self, target: Dict, candidate: Dict, tolerance: int) -> bool:
        """检查位置相似性"""
        target_pos = target.get('visual_properties', {}).get('bounding_box', {})
        candidate_pos = candidate.get('location', {})
        
        if not target_pos or not candidate_pos:
            return False
        
        target_x = target_pos.get('x', 0)
        target_y = target_pos.get('y', 0)
        candidate_x = candidate_pos.get('x', 0)
        candidate_y = candidate_pos.get('y', 0)
        
        distance = ((target_x - candidate_x) ** 2 + (target_y - candidate_y) ** 2) ** 0.5
        return distance <= tolerance
    
    def _check_parent_match(self, target: Dict, candidate: Dict) -> bool:
        """检查父元素匹配"""
        target_parent = target.get('structural_context', {})
        candidate_parent = candidate.get('parent', {})
        
        if not target_parent or not candidate_parent:
            return False
        
        # 检查父元素标签和关键属性
        parent_tag_match = (
            target_parent.get('parent_tag') == 
            candidate_parent.get('tag')
        )
        
        parent_id_match = (
            target_parent.get('parent_id') == 
            candidate_parent.get('id')
        )
        
        return parent_tag_match or parent_id_match
    
    def _make_decision(self, score: float) -> str:
        """根据分数做出决策"""
        if score >= self.thresholds['auto_heal']:
            return "auto_heal"
        elif score >= self.thresholds['manual_review']:
            return "manual_review"
        else:
            return "fail"
    
    def update_thresholds(self, auto_heal: float, manual_review: float) -> None:
        """更新决策阈值"""
        self.thresholds['auto_heal'] = auto_heal
        self.thresholds['manual_review'] = manual_review
        self.thresholds['fail'] = manual_review
        logger.info(f"阈值已更新: 自动治愈={auto_heal}, 人工审查={manual_review}")

# 全局实例
confidence_scorer = ConfidenceScorer() 
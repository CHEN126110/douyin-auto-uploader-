# -*- coding: utf-8 -*-
# [优秀] 专业产品标题生成器
# 基于抖音热门词数据,生成60字符专业标题,无重复关键词,语句通顺

import json
import re
import logging
import random
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from datetime import datetime

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set

logger = logging.getLogger(__name__)


SOURCE_BRAND_PREFIX_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9&.\-]{1,24}[\u4e00-\u9fff]{1,8}"
    r"(?:\s+|(?=布标|袜|短袜|中筒袜|长筒袜|船袜|女|男))"
)

KNOWN_SOURCE_BRAND_MARKERS = ("songmu", "淞木", "kikisocks")


def sanitize_no_brand_title_text(title: str) -> str:
    """Remove brand-like source markers from title text under the no-brand policy."""
    text = str(title or "").strip()
    if not text:
        return ""

    for marker in KNOWN_SOURCE_BRAND_MARKERS:
        text = re.sub(re.escape(marker), "", text, flags=re.IGNORECASE)
    text = SOURCE_BRAND_PREFIX_PATTERN.sub("", text)
    for marker in ("官方旗舰店", "旗舰店", "专卖店", "专营店", "无品牌", "品牌"):
        text = text.replace(marker, "")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^[\s\"'“”‘’·:：,，\-_/]+|[\s\"'“”‘’·:：,，\-_/]+$", "", text)
    return text.strip()


def audit_no_brand_title_text(title: str) -> Dict[str, object]:
    """Audit title text for source-brand residue while preserving style terms like jk/ins."""
    text = str(title or "").strip()
    normalized = re.sub(r"^[\s\"'“”‘’·:：,，\-_/]+", "", text)
    lower_text = normalized.lower()
    risk_flags: List[str] = []

    if SOURCE_BRAND_PREFIX_PATTERN.search(normalized):
        risk_flags.append("source_brand_like_prefix")
    if any(marker in lower_text for marker in KNOWN_SOURCE_BRAND_MARKERS):
        risk_flags.append("known_source_brand_marker")

    unique_flags = list(dict.fromkeys(risk_flags))
    return {
        "has_risk": bool(unique_flags),
        "risk_flags": unique_flags,
        "original_title": text,
        "sanitized_title": sanitize_no_brand_title_text(text),
        "brand_policy": {
            "required_value": "无品牌",
            "title_use_brand_name_required": False,
            "reason": "当前无品牌资质，安全稳健优先",
        },
    }


@dataclass
class ProductInfo:
    """产品信息"""
    name: str
    category: int
    remark: str = ""
    sku_list: List[Dict] = field(default_factory=list)

@dataclass
class TitleSuggestion:
    """标题建议"""
    title: str
    confidence: float
    character_count: int
    tags: List[str] = field(default_factory=list)
    reasoning: str = ""
    blue_ocean_words: List[str] = field(default_factory=list)

@dataclass
class DouyinKeyword:
    keyword: str
    blue_ocean_score: float = 0.0

class ProfessionalTitleGenerator:
    """专业标题生成器"""
    
    def __init__(self):
        
        # 类目映射
        self.category_map = {
            1: "船袜",
            2: "短袜", 
            3: "中筒袜",
            4: "长筒袜"
        }
        
        # 专业运营词库
        self.marketing_words = {
            "品质词": ["精梳棉", "纯棉", "优质", "精选", "高档", "舒适"],
            "功能词": ["透气", "吸汗", "防臭", "抗菌", "速干", "保暖"],
            "场景词": ["商务", "运动", "休闲", "居家", "办公", "户外"],
            "卖点词": ["爆款", "热销", "新品", "包邮", "特价", "限时"],
            "数量词": ["3双装", "5双装", "10双装", "家庭装", "超值装"],
            "性别词": ["男士", "女士", "男款", "女款", "通用", "情侣"],
            "季节词": ["春季", "夏季", "秋季", "冬季", "四季", "全年"],
            "颜色词": ["纯色", "黑色", "白色", "灰色", "彩色", "多色"]
        }
        
        # 标题结构模板 (确保60字符)
        self.title_templates = [
            # 模板1: 产品+功能+场景+卖点+数量 (约50-60字符)
            "{product}{function}{scene}{selling_point}{quantity}",
            # 模板2: 卖点+品质+产品+功能+数量 (约50-60字符)
            "{selling_point}{quality}{product}{function}{gender}{quantity}",
            # 模板3: 季节+功能+产品+场景+特色 (约50-60字符)
            "{season}{function}{product}{scene}{quality}{special}",
        ]
        
        logger.info("[优秀] 专业标题生成器已初始化")
    
    def generate_professional_titles(self, product_info: ProductInfo) -> List[TitleSuggestion]:
        """生成专业标题"""
        try:
            logger.info(f"[启动] 开始生成专业标题 - 产品: {product_info.name}")
            
            # 1. 获取蓝海关键词（本地生成）
            blue_ocean_keywords = self._get_blue_ocean_keywords(limit=10)
            logger.info(f"[测试] 获取到 {len(blue_ocean_keywords)} 个蓝海关键词")
            
            # 2. 分析产品特征
            product_features = self._analyze_product_features(product_info)
            
            # 3. 生成多个标题
            titles = []
            
            # 生成基于蓝海词的标题
            for keyword in blue_ocean_keywords[:3]:
                title = self._create_professional_title(product_info, product_features, keyword)
                if title:
                    titles.append(title)
            
            # 生成基于AI的标题（已禁用）
            
            # 生成本地算法标题
            local_titles = self._generate_local_titles(product_info, product_features)
            titles.extend(local_titles)
            
            # 去重和排序
            unique_titles = self._deduplicate_titles(titles)
            sorted_titles = sorted(unique_titles, key=lambda x: x.confidence, reverse=True)
            
            # 返回前5个最佳标题
            result = sorted_titles[:5]
            logger.info(f"[成功] 成功生成 {len(result)} 个专业标题")
            
            return result
            
        except Exception as e:
            logger.error(f"[失败] 生成专业标题失败: {e}")
            return self._generate_fallback_titles(product_info)
    
    def _analyze_product_features(self, product_info: ProductInfo) -> Dict:
        """分析产品特征"""
        features = {
            "category": self.category_map.get(product_info.category, "短袜"),
            "colors": [],
            "materials": [],
            "functions": [],
            "target_gender": "通用",
            "quantity": f"{len(product_info.sku_list)}双装" if product_info.sku_list else "多双装"
        }
        
        # 分析产品名称和备注
        combined_text = f"{product_info.name} {product_info.remark}".lower()
        
        # 提取颜色
        color_patterns = ["黑", "白", "灰", "红", "蓝", "绿", "黄", "紫", "粉", "棕"]
        for color in color_patterns:
            if color in combined_text:
                features["colors"].append(color + "色")
        
        # 提取材质
        material_patterns = ["棉", "纯棉", "精梳棉", "丝", "毛", "尼龙", "涤纶"]
        for material in material_patterns:
            if material in combined_text:
                features["materials"].append(material)
        
        # 提取功能
        function_patterns = ["透气", "吸汗", "防臭", "抗菌", "保暖", "速干"]
        for function in function_patterns:
            if function in combined_text:
                features["functions"].append(function)
        
        # 判断性别倾向
        if any(word in combined_text for word in ["男", "先生", "gentleman"]):
            features["target_gender"] = "男士"
        elif any(word in combined_text for word in ["女", "女士", "lady"]):
            features["target_gender"] = "女士"
        
        return features
    
    def _create_professional_title(self, product_info: ProductInfo, features: Dict, blue_ocean_keyword: DouyinKeyword) -> Optional[TitleSuggestion]:
        """创建专业标题"""
        try:
            # 基础词汇池
            word_pool = {
                "product": features["category"],
                "blue_ocean": blue_ocean_keyword.keyword,
                "quality": random.choice(self.marketing_words["品质词"]),
                "function": random.choice(features.get("functions", []) or self.marketing_words["功能词"]),
                "scene": random.choice(self.marketing_words["场景词"]),
                "selling_point": random.choice(self.marketing_words["卖点词"]),
                "quantity": features["quantity"],
                "gender": features["target_gender"],
                "season": random.choice(self.marketing_words["季节词"]),
                "material": random.choice(features.get("materials", []) or ["精梳棉"]),
                "special": random.choice(self.marketing_words["颜色词"])
            }
            
            # 选择模板并填充
            template = random.choice(self.title_templates)
            
            # 构建标题
            title_parts = []
            used_words = set()
            
            # 按优先级添加词汇
            priority_order = [
                ("blue_ocean", 1.0),  # 蓝海词最重要
                ("product", 1.0),     # 产品词必须有
                ("selling_point", 0.8), # 卖点词
                ("quality", 0.7),     # 品质词
                ("function", 0.7),    # 功能词
                ("quantity", 0.6),    # 数量词
                ("scene", 0.5),       # 场景词
                ("gender", 0.4),      # 性别词
                ("material", 0.4),    # 材质词
                ("season", 0.3),      # 季节词
                ("special", 0.2)      # 特色词
            ]
            
            current_length = 0
            target_length = 58  # 留2个字符余量
            
            for word_key, priority in priority_order:
                word = word_pool.get(word_key, "")
                
                # 检查重复
                if self._contains_duplicate_chars(word, used_words):
                    continue
                
                # 检查长度
                if current_length + len(word) > target_length:
                    # 尝试缩短词汇
                    if len(word) > 2:
                        word = word[:2]
                        if current_length + len(word) > target_length:
                            continue
                    else:
                        continue
                
                title_parts.append(word)
                used_words.update(word)
                current_length += len(word)
                
                # 如果接近目标长度,停止添加
                if current_length >= 50:
                    break
            
            # 拼接标题
            title = "".join(title_parts)
            
            # 确保60字符(补充或裁剪)
            title = self._adjust_title_length(title, target_length=60)
            
            # 创建标题建议
            suggestion = TitleSuggestion(
                title=title,
                confidence=self._calculate_confidence(title, blue_ocean_keyword),
                character_count=len(title),
                tags=["蓝海词", "专业运营", "60字符"],
                reasoning=f"融入蓝海词'{blue_ocean_keyword.keyword}',优化搜索权重",
                blue_ocean_words=[blue_ocean_keyword.keyword]
            )
            
            return suggestion
            
        except Exception as e:
            logger.error(f"[失败] 创建专业标题失败: {e}")
            return None
    
    def _contains_duplicate_chars(self, new_word: str, used_words: Set[str]) -> bool:
        """检查是否包含重复字符"""
        for char in new_word:
            if char in used_words:
                return True
        return False
    
    def _adjust_title_length(self, title: str, target_length: int = 60) -> str:
        """调整标题长度到目标长度"""
        title = sanitize_no_brand_title_text(title)
        current_length = len(title)
        
        if current_length == target_length:
            return title
        elif current_length < target_length:
            # 标题太短,需要补充
            gap = target_length - current_length
            
            # 补充词汇
            filler_words = ["优质", "精选", "舒适", "透气", "包邮", "热销", "新品", "特价"]
            
            for word in filler_words:
                if gap <= 0:
                    break
                
                # 检查不重复
                if not any(char in title for char in word):
                    if len(word) <= gap:
                        title += word
                        gap -= len(word)
            
            # 如果还不够,添加标点符号和空格的替代
            while len(title) < target_length:
                remaining = target_length - len(title)
                if remaining >= 3:
                    title += "超值"
                elif remaining >= 2:
                    title += "棒"
                else:
                    title += "!"
            
        else:
            # 标题太长,需要裁剪
            title = title[:target_length]
        
        return title
    
    def _calculate_confidence(self, title: str, blue_ocean_keyword: DouyinKeyword) -> float:
        """计算标题置信度"""
        confidence = 0.7  # 基础置信度
        
        # 蓝海词加分
        if blue_ocean_keyword.keyword in title:
            confidence += blue_ocean_keyword.blue_ocean_score * 0.2
        
        # 长度合规加分
        if 58 <= len(title) <= 60:
            confidence += 0.1
        
        # 无重复字符加分
        if len(set(title)) == len(title):
            confidence += 0.1
        
        # 包含营销词汇加分
        marketing_count = sum(1 for word_list in self.marketing_words.values() 
                            for word in word_list if word in title)
        confidence += min(marketing_count * 0.05, 0.15)
        
        return min(confidence, 1.0)
    
    def _generate_ai_titles(self, product_info: ProductInfo, blue_ocean_keywords: List['DouyinKeyword']) -> List[TitleSuggestion]:
        return []
    
    def _parse_ai_response(self, content: str, blue_ocean_keywords: List[DouyinKeyword]) -> List[TitleSuggestion]:
        """解析AI响应"""
        titles = []
        
        try:
            # 提取标题
            title_pattern = r'标题\d+:(.+)'
            matches = re.findall(title_pattern, content)
            
            for i, title_text in enumerate(matches):
                title_text = title_text.strip()
                
                # 验证标题
                if 50 <= len(title_text) <= 70:  # 允许一定范围
                    # 调整到60字符
                    title_text = self._adjust_title_length(title_text, 60)
                    
                    # 计算包含的蓝海词
                    blue_ocean_words = [kw.keyword for kw in blue_ocean_keywords if kw.keyword in title_text]
                    
                    suggestion = TitleSuggestion(
                        title=title_text,
                        confidence=0.85 + len(blue_ocean_words) * 0.05,
                        character_count=len(title_text),
                        tags=["AI生成", "专业运营"],
                        reasoning="基于AI和热门词生成的专业标题",
                        blue_ocean_words=blue_ocean_words
                    )
                    
                    titles.append(suggestion)
            
        except Exception as e:
            logger.error(f"[失败] 解析AI响应失败: {e}")
        
        return titles

    def _get_blue_ocean_keywords(self, limit: int = 10) -> List['DouyinKeyword']:
        words = [
            ('透气短袜', 0.9), ('商务棉袜', 0.7), ('运动船袜', 0.8),
            ('舒适中筒袜', 0.8), ('防臭袜子', 0.9)
        ]
        result = []
        for w, score in words[:limit]:
            result.append(DouyinKeyword(keyword=w, blue_ocean_score=score))
        return result
    
    def _generate_local_titles(self, product_info: ProductInfo, features: Dict) -> List[TitleSuggestion]:
        """生成本地算法标题"""
        titles = []
        
        try:
            # 本地模板
            local_templates = [
                f"爆款{features['category']}{features['target_gender']}装透气舒适棉袜防臭吸汗运动休闲居家办公{features['quantity']}包邮特价限时热销新品优质精选高档四季",
                f"热销{features['category']}精梳棉材质{features['target_gender']}专用透气防臭抗菌速干保暖四季通用{features['quantity']}超值家庭装包邮",
                f"新品{features['category']}优质纯棉{features['target_gender']}款舒适透气吸汗防臭商务休闲运动{features['quantity']}特价包邮爆款热销"
            ]
            
            for i, template in enumerate(local_templates):
                # 调整到60字符
                title = self._adjust_title_length(template, 60)
                
                suggestion = TitleSuggestion(
                    title=title,
                    confidence=0.6 + i * 0.05,
                    character_count=len(title),
                    tags=["本地算法", "专业模板"],
                    reasoning="基于专业运营模板生成",
                    blue_ocean_words=[]
                )
                
                titles.append(suggestion)
        
        except Exception as e:
            logger.error(f"[失败] 生成本地标题失败: {e}")
        
        return titles
    
    def _deduplicate_titles(self, titles: List[TitleSuggestion]) -> List[TitleSuggestion]:
        """去重标题"""
        seen = set()
        unique_titles = []
        
        for title in titles:
            if title.title not in seen:
                seen.add(title.title)
                unique_titles.append(title)
        
        return unique_titles
    
    def _generate_fallback_titles(self, product_info: ProductInfo) -> List[TitleSuggestion]:
        """生成备用标题"""
        category = self.category_map.get(product_info.category, "短袜")
        
        fallback_titles = [
            f"爆款{category}精梳棉透气舒适男女通用防臭吸汗运动休闲居家办公多双装包邮特价限时热销新品优质精选高档四季",
            f"热销{category}纯棉材质透气防臭抗菌速干保暖商务休闲运动家庭装超值包邮新品特价爆款优质舒适男女款多色选择",
        ]
        
        suggestions = []
        for i, title in enumerate(fallback_titles):
            title = self._adjust_title_length(title, 60)
            
            suggestion = TitleSuggestion(
                title=title,
                confidence=0.5 + i * 0.1,
                character_count=len(title),
                tags=["备用方案"],
                reasoning="系统备用标题,确保功能可用性",
                blue_ocean_words=[]
            )
            
            suggestions.append(suggestion)
        
        return suggestions

# 全局实例
_professional_generator = None

def get_professional_generator() -> ProfessionalTitleGenerator:
    """获取专业标题生成器实例"""
    global _professional_generator
    if _professional_generator is None:
        _professional_generator = ProfessionalTitleGenerator()
    return _professional_generator 

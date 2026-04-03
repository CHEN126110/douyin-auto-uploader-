# -*- coding: utf-8 -*-
# [热门] 热门关键词抓取器(增强版 - 蓝海词优化)
# 从电商平台抓取实时热门搜索词,智能识别蓝海关键词,提升标题生成质量

import requests
import json
import time
import logging
import hashlib
from typing import Dict, List, Optional, Set, Any
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin
import re
from dataclasses import dataclass, field
import threading
import sqlite3
import os
import random
import math
from .runtime_paths import resolve_data_file

logger = logging.getLogger(__name__)

@dataclass
class TrendingKeyword:
    """热门关键词数据结构(增强版)"""
    keyword: str
    category: str
    trend_score: float
    search_volume: int = 0
    competition_level: float = 0.5  # [热门] 新增:竞争度 (0-1, 越低越好)
    blue_ocean_score: float = 0.0   # [热门] 新增:蓝海分数 (0-1, 越高越好)
    opportunity_score: float = 0.0   # [热门] 新增:机会分数 (综合评估)
    related_keywords: List[str] = field(default_factory=list)
    platform: str = "unknown"
    timestamp: datetime = field(default_factory=datetime.now)
    
    # [热门] 新增字段
    growth_trend: str = "stable"     # 增长趋势: up/down/stable
    seasonal_factor: float = 1.0     # 季节性因子
    user_intent: str = "unknown"     # 用户意图: purchase/browse/compare

@dataclass
class CategoryData:
    """类目数据"""
    name: str
    keywords: List[TrendingKeyword] = field(default_factory=list)
    last_updated: datetime = field(default_factory=datetime.now)

class TrendingKeywordsScraper:
    """热门关键词抓取器(蓝海词优化版)"""
    
    def __init__(self, db_path: str = "trending_keywords.db"):
        """
        初始化抓取器
        
        Args:
            db_path: 数据库文件路径
        """
        legacy_path = db_path if os.path.isabs(db_path) else db_path
        self.db_path = str(resolve_data_file(db_path, legacy_fallback=legacy_path))
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Cache-Control': 'no-cache'
        })
        
        # 类目映射
        self.category_mapping = {
            1: "短袜",
            2: "中筒袜", 
            3: "长筒袜"
        }
        
        # 袜子相关的搜索关键词
        self.sock_keywords = [
            "袜子", "短袜", "中筒袜", "长筒袜", "船袜", "隐形袜",
            "棉袜", "丝袜", "运动袜", "商务袜", "休闲袜"
        ]
        
        # [热门] 新增:蓝海词识别相关配置
        self.blue_ocean_config = {
            "min_search_volume": 100,      # 最小搜索量
            "max_competition": 0.7,        # 最大竞争度
            "trend_weight": 0.3,           # 趋势权重
            "volume_weight": 0.4,          # 搜索量权重
            "competition_weight": 0.3      # 竞争度权重
        }
        
        # [热门] 高价值修饰词库(蓝海挖掘)
        self.high_value_modifiers = {
            "功能性": ["防臭", "透气", "吸汗", "速干", "抗菌", "保暖", "加厚"],
            "材质类": ["纯棉", "精梳棉", "竹纤维", "莫代尔", "天丝", "丝光棉", "丝光棉"],
            "场景类": ["运动", "商务", "休闲", "居家", "户外", "睡眠"],
            "人群类": ["学生", "上班族", "孕妇", "老人", "儿童", "男士", "女士"],
            "季节类": ["春季", "夏季", "秋季", "冬季", "四季"],
            "包装类": ["家庭装", "情侣装", "组合装", "礼盒装", "试用装"],
            "风格类": ["简约", "时尚", "经典", "潮流", "复古", "日系", "韩版"]
        }
        
        # 初始化数据库
        self._init_database()
        
        # 缓存热门词(避免频繁查询)
        self._cache = {}
        self._cache_expire_time = 3600  # 1小时
        
        logger.info("[热门] 热门关键词抓取器(蓝海优化版)已初始化")
    
    def _init_database(self):
        """初始化数据库(更新表结构支持蓝海词)"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS trending_keywords (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL,
                    category TEXT NOT NULL,
                    trend_score REAL NOT NULL,
                    search_volume INTEGER DEFAULT 0,
                    competition_level REAL DEFAULT 0.5,
                    blue_ocean_score REAL DEFAULT 0.0,
                    opportunity_score REAL DEFAULT 0.0,
                    growth_trend TEXT DEFAULT 'stable',
                    seasonal_factor REAL DEFAULT 1.0,
                    user_intent TEXT DEFAULT 'unknown',
                    related_keywords TEXT,
                    platform TEXT DEFAULT 'unknown',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 添加新字段到现有表(如果不存在)
            try:
                conn.execute('ALTER TABLE trending_keywords ADD COLUMN competition_level REAL DEFAULT 0.5')
                conn.execute('ALTER TABLE trending_keywords ADD COLUMN blue_ocean_score REAL DEFAULT 0.0')
                conn.execute('ALTER TABLE trending_keywords ADD COLUMN opportunity_score REAL DEFAULT 0.0')
                conn.execute('ALTER TABLE trending_keywords ADD COLUMN growth_trend TEXT DEFAULT "stable"')
                conn.execute('ALTER TABLE trending_keywords ADD COLUMN seasonal_factor REAL DEFAULT 1.0')
                conn.execute('ALTER TABLE trending_keywords ADD COLUMN user_intent TEXT DEFAULT "unknown"')
            except sqlite3.OperationalError:
                pass  # 字段已存在
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_keyword_category 
                ON trending_keywords(keyword, category)
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_blue_ocean_score 
                ON trending_keywords(blue_ocean_score DESC)
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_created_at 
                ON trending_keywords(created_at)
            ''')
            
            conn.commit()
    
    def scrape_douyin_trending(self, category: str = "袜子") -> List[TrendingKeyword]:
        """
        抓取抖音小店热门搜索词(增强版 - 蓝海词优化)
        
        Args:
            category: 产品类目
            
        Returns:
            热门关键词列表
        """
        trending_keywords = []
        
        try:
            # 方法1: 抓取抖音搜索建议
            search_suggestions = self._get_douyin_search_suggestions(category)
            trending_keywords.extend(search_suggestions)
            
            # 方法2: 抓取热门标签
            trending_tags = self._get_douyin_trending_tags(category)
            trending_keywords.extend(trending_tags)
            
            # 方法3: 分析商品标题热词
            title_keywords = self._analyze_douyin_product_titles(category)
            trending_keywords.extend(title_keywords)
            
            # [热门] 方法4: 蓝海词挖掘(核心功能)
            blue_ocean_keywords = self._mine_blue_ocean_keywords(category, trending_keywords)
            trending_keywords.extend(blue_ocean_keywords)
            
            # [热门] 方法5: 智能组合词生成
            combination_keywords = self._generate_smart_combinations(category)
            trending_keywords.extend(combination_keywords)
            
            # [热门] 增强处理:分析竞争度和机会评估
            enhanced_keywords = self._enhance_keywords_with_analysis(trending_keywords)
            
            logger.info(f"[热门] 从抖音抓取到 {len(enhanced_keywords)} 个热门关键词(含{len(blue_ocean_keywords)}个蓝海词)")
            
            return enhanced_keywords
            
        except Exception as e:
            logger.error(f"[失败] 抖音热门词抓取失败: {e}")
        
        return trending_keywords
    
    def _get_douyin_search_suggestions(self, keyword: str) -> List[TrendingKeyword]:
        """获取抖音搜索建议"""
        suggestions = []
        
        try:
            # 构建搜索建议API请求
            api_url = "https://compass.jinritemai.com/api/search/suggest"
            
            params = {
                "keyword": keyword,
                "platform": "douyin",
                "limit": 10
            }
            
            response = self.session.get(api_url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('success') and 'suggestions' in data:
                    for item in data['suggestions']:
                        suggestions.append(TrendingKeyword(
                            keyword=item.get('text', ''),
                            category=keyword,
                            trend_score=item.get('score', 0.5),
                            search_volume=item.get('volume', 0),
                            platform="douyin_search"
                        ))
            
        except Exception as e:
            logger.warning(f"抖音搜索建议获取失败: {e}")
        
        return suggestions
    
    def _get_douyin_trending_tags(self, category: str) -> List[TrendingKeyword]:
        """获取抖音热门标签"""
        trending_tags = []
        
        try:
            # 分析热门话题标签
            hashtags_url = "https://compass.jinritemai.com/api/trending/hashtags"
            
            params = {
                "category": category,
                "time_range": "7d",
                "limit": 20
            }
            
            response = self.session.get(hashtags_url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('success') and 'hashtags' in data:
                    for tag in data['hashtags']:
                        trending_tags.append(TrendingKeyword(
                            keyword=tag.get('name', '').replace('#', ''),
                            category=category,
                            trend_score=tag.get('heat_score', 0.5),
                            search_volume=tag.get('mentions', 0),
                            platform="douyin_hashtag"
                        ))
            
        except Exception as e:
            logger.warning(f"抖音热门标签获取失败: {e}")
        
        return trending_tags
    
    def _analyze_douyin_product_titles(self, category: str) -> List[TrendingKeyword]:
        """分析抖音商品标题中的热词"""
        title_keywords = []
        
        try:
            # 获取热门商品列表
            products_url = "https://compass.jinritemai.com/api/products/trending"
            
            params = {
                "category": category,
                "sort": "sales_desc",
                "limit": 50
            }
            
            response = self.session.get(products_url, params=params, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('success') and 'products' in data:
                    # 分析商品标题
                    title_analysis = self._extract_keywords_from_titles(
                        [product.get('title', '') for product in data['products']]
                    )
                    
                    for keyword, score in title_analysis.items():
                        title_keywords.append(TrendingKeyword(
                            keyword=keyword,
                            category=category,
                            trend_score=score,
                            platform="douyin_products"
                        ))
            
        except Exception as e:
            logger.warning(f"抖音商品标题分析失败: {e}")
        
        return title_keywords
    
    def _extract_keywords_from_titles(self, titles: List[str]) -> Dict[str, float]:
        """从标题中提取关键词并计算热度"""
        keyword_freq = {}
        total_titles = len(titles)
        
        for title in titles:
            # 提取中文词汇
            words = re.findall(r'[\u4e00-\u9fff]+', title)
            
            for word in words:
                if len(word) >= 2 and len(word) <= 6:  # 合理的词汇长度
                    keyword_freq[word] = keyword_freq.get(word, 0) + 1
        
        # 计算热度分数(出现频率 + 长度权重)
        keyword_scores = {}
        for keyword, freq in keyword_freq.items():
            if freq >= 2:  # 至少出现2次
                frequency_score = freq / total_titles
                length_bonus = min(len(keyword) / 6, 1.0)  # 长度奖励
                keyword_scores[keyword] = frequency_score * 0.7 + length_bonus * 0.3
        
        # 返回前20个热门词
        sorted_keywords = sorted(keyword_scores.items(), key=lambda x: x[1], reverse=True)
        return dict(sorted_keywords[:20])
    
    def scrape_taobao_trending(self, category: str = "袜子") -> List[TrendingKeyword]:
        """抓取淘宝热门搜索词"""
        trending_keywords = []
        
        try:
            # 淘宝搜索热词接口
            taobao_api = "https://suggest.taobao.com/sug"
            
            params = {
                "code": "utf-8",
                "q": category,
                "callback": "cb"
            }
            
            response = self.session.get(taobao_api, params=params, timeout=10)
            
            if response.status_code == 200:
                # 解析JSONP格式
                content = response.text
                if content.startswith("cb(") and content.endswith(")"):
                    json_str = content[3:-1]
                    data = json.loads(json_str)
                    
                    if 'result' in data:
                        for item in data['result']:
                            trending_keywords.append(TrendingKeyword(
                                keyword=item[0],
                                category=category,
                                trend_score=0.8,
                                platform="taobao"
                            ))
            
            logger.info(f"[购物] 从淘宝抓取到 {len(trending_keywords)} 个热门关键词")
            
        except Exception as e:
            logger.error(f"[失败] 淘宝热门词抓取失败: {e}")
        
        return trending_keywords
    
    def scrape_jd_trending(self, category: str = "袜子") -> List[TrendingKeyword]:
        """抓取京东热门搜索词"""
        trending_keywords = []
        
        try:
            # 京东搜索建议接口
            jd_api = "https://search.jd.com/Search"
            
            params = {
                "keyword": category,
                "enc": "utf-8",
                "suggest": "1.def.0.V02",
                "wq": category
            }
            
            response = self.session.get(jd_api, params=params, timeout=10)
            
            if response.status_code == 200:
                # 解析响应获取搜索建议
                suggestions = self._parse_jd_suggestions(response.text, category)
                trending_keywords.extend(suggestions)
            
            logger.info(f"[打包] 从京东抓取到 {len(trending_keywords)} 个热门关键词")
            
        except Exception as e:
            logger.error(f"[失败] 京东热门词抓取失败: {e}")
        
        return trending_keywords
    
    def _parse_jd_suggestions(self, html_content: str, category: str) -> List[TrendingKeyword]:
        """解析京东搜索建议"""
        suggestions = []
        
        try:
            # 使用正则提取搜索建议
            pattern = r'"([^"]*' + re.escape(category) + r'[^"]*)"'
            matches = re.findall(pattern, html_content)
            
            for match in matches[:10]:  # 取前10个
                if len(match) > len(category):
                    suggestions.append(TrendingKeyword(
                        keyword=match,
                        category=category,
                        trend_score=0.7,
                        platform="jd"
                    ))
        
        except Exception as e:
            logger.warning(f"京东建议解析失败: {e}")
        
        return suggestions
    
    def get_trending_keywords_for_category(self, category_id: int, limit: int = 20) -> List[TrendingKeyword]:
        """
        获取指定类目的热门关键词
        
        Args:
            category_id: 类目ID (1=短袜, 2=中筒袜, 3=长筒袜)
            limit: 返回数量限制
            
        Returns:
            热门关键词列表
        """
        category_name = self.category_mapping.get(category_id, "袜子")
        cache_key = f"trending_{category_id}_{limit}"
        
        # 检查缓存
        if cache_key in self._cache:
            cache_data = self._cache[cache_key]
            if (datetime.now() - cache_data['timestamp']).seconds < self._cache_expire_time:
                return cache_data['keywords']
        
        # 从数据库获取最新数据
        keywords = self._get_keywords_from_db(category_name, limit)
        
        # 如果数据不够新,重新抓取
        if not keywords or self._need_refresh(category_name):
            logger.info(f"[处理] 开始刷新 {category_name} 的热门关键词")
            
            # 异步抓取新数据
            threading.Thread(
                target=self._refresh_category_keywords,
                args=(category_name,),
                daemon=True
            ).start()
            
            # 返回现有数据或默认数据
            if not keywords:
                keywords = self._get_default_keywords(category_name)
        
        # 更新缓存
        self._cache[cache_key] = {
            'keywords': keywords,
            'timestamp': datetime.now()
        }
        
        return keywords[:limit]
    
    def _get_keywords_from_db(self, category: str, limit: int) -> List[TrendingKeyword]:
        """从数据库获取关键词(支持蓝海词字段)"""
        keywords = []
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT keyword, category, trend_score, search_volume, 
                           competition_level, blue_ocean_score, opportunity_score,
                           growth_trend, seasonal_factor, user_intent,
                           related_keywords, platform, created_at
                    FROM trending_keywords 
                    WHERE category = ? 
                    ORDER BY blue_ocean_score DESC, opportunity_score DESC, trend_score DESC
                    LIMIT ?
                ''', (category, limit))
                
                for row in cursor.fetchall():
                    related_keywords = json.loads(row[10]) if row[10] else []
                    
                    keywords.append(TrendingKeyword(
                        keyword=row[0],
                        category=row[1],
                        trend_score=row[2],
                        search_volume=row[3],
                        competition_level=row[4] if row[4] is not None else 0.5,
                        blue_ocean_score=row[5] if row[5] is not None else 0.0,
                        opportunity_score=row[6] if row[6] is not None else 0.0,
                        growth_trend=row[7] if row[7] else "stable",
                        seasonal_factor=row[8] if row[8] is not None else 1.0,
                        user_intent=row[9] if row[9] else "unknown",
                        related_keywords=related_keywords,
                        platform=row[11],
                        timestamp=datetime.fromisoformat(row[12])
                    ))
        
        except Exception as e:
            logger.error(f"数据库查询失败: {e}")
        
        return keywords
    
    def _need_refresh(self, category: str) -> bool:
        """判断是否需要刷新数据"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT MAX(created_at) FROM trending_keywords WHERE category = ?
                ''', (category,))
                
                result = cursor.fetchone()
                if not result[0]:
                    return True
                
                last_update = datetime.fromisoformat(result[0])
                hours_since_update = (datetime.now() - last_update).total_seconds() / 3600
                
                return hours_since_update > 6  # 6小时更新一次
        
        except Exception:
            return True
    
    def _refresh_category_keywords(self, category: str):
        """刷新类目关键词(后台任务)"""
        try:
            all_keywords = []
            
            # 从各平台抓取
            all_keywords.extend(self.scrape_douyin_trending(category))
            all_keywords.extend(self.scrape_taobao_trending(category))
            all_keywords.extend(self.scrape_jd_trending(category))
            
            # 去重和合并
            unique_keywords = self._merge_and_deduplicate(all_keywords)
            
            # 保存到数据库
            self._save_keywords_to_db(unique_keywords)
            
            logger.info(f"[成功] {category} 热门关键词刷新完成,共 {len(unique_keywords)} 个")
        
        except Exception as e:
            logger.error(f"[失败] 关键词刷新失败: {e}")
    
    def _merge_and_deduplicate(self, keywords: List[TrendingKeyword]) -> List[TrendingKeyword]:
        """合并和去重关键词"""
        keyword_map = {}
        
        for kw in keywords:
            key = kw.keyword.lower().strip()
            
            if key in keyword_map:
                # 合并相同关键词,取最高分数
                existing = keyword_map[key]
                if kw.trend_score > existing.trend_score:
                    keyword_map[key] = kw
            else:
                keyword_map[key] = kw
        
        # 按热度排序
        sorted_keywords = sorted(keyword_map.values(), key=lambda x: x.trend_score, reverse=True)
        
        return sorted_keywords[:50]  # 保留前50个
    
    def _save_keywords_to_db(self, keywords: List[TrendingKeyword]):
        """保存关键词到数据库(支持蓝海词字段)"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 清除旧数据(保留最近30天)
                conn.execute('''
                    DELETE FROM trending_keywords 
                    WHERE created_at < datetime('now', '-30 days')
                ''')
                
                # 插入新数据(包含蓝海词字段)
                for kw in keywords:
                    conn.execute('''
                        INSERT OR REPLACE INTO trending_keywords 
                        (keyword, category, trend_score, search_volume, 
                         competition_level, blue_ocean_score, opportunity_score,
                         growth_trend, seasonal_factor, user_intent,
                         related_keywords, platform, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        kw.keyword,
                        kw.category,
                        kw.trend_score,
                        kw.search_volume,
                        kw.competition_level,
                        kw.blue_ocean_score,
                        kw.opportunity_score,
                        kw.growth_trend,
                        kw.seasonal_factor,
                        kw.user_intent,
                        json.dumps(kw.related_keywords),
                        kw.platform,
                        kw.timestamp.isoformat(),
                        datetime.now().isoformat()
                    ))
                
                conn.commit()
        
        except Exception as e:
            logger.error(f"数据库保存失败: {e}")
    
    def _get_default_keywords(self, category: str) -> List[TrendingKeyword]:
        """获取默认关键词(备用方案)"""
        default_keywords = {
            "短袜": ["短袜", "船袜", "隐形袜", "棉质短袜", "透气短袜", "运动短袜"],
            "中筒袜": ["中筒袜", "商务袜", "休闲袜", "棉袜", "保暖袜", "吸汗袜"],
            "长筒袜": ["长筒袜", "高筒袜", "保暖袜", "冬季袜", "厚袜", "毛圈袜"],
            "袜子": ["袜子", "棉袜", "透气袜", "舒适袜", "防臭袜", "吸湿袜"]
        }
        
        keywords = []
        for i, keyword in enumerate(default_keywords.get(category, default_keywords["袜子"])):
            keywords.append(TrendingKeyword(
                keyword=keyword,
                category=category,
                trend_score=0.8 - i * 0.1,
                platform="default"
            ))
        
        return keywords
    
    def get_related_keywords(self, base_keyword: str) -> List[str]:
        """获取相关关键词"""
        related = []
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT related_keywords FROM trending_keywords 
                    WHERE keyword LIKE ? OR keyword = ?
                    ORDER BY trend_score DESC LIMIT 5
                ''', (f"%{base_keyword}%", base_keyword))
                
                for row in cursor.fetchall():
                    if row[0]:
                        related_list = json.loads(row[0])
                        related.extend(related_list)
        
        except Exception as e:
            logger.warning(f"相关关键词查询失败: {e}")
        
        # 去重并返回
        return list(set(related))[:10]
    
    def analyze_keyword_trends(self, category: str, days: int = 7) -> Dict[str, Any]:
        """分析关键词趋势"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT keyword, trend_score, created_at
                    FROM trending_keywords 
                    WHERE category = ? AND created_at >= datetime('now', '-{} days')
                    ORDER BY created_at DESC
                '''.format(days), (category,))
                
                trends = {}
                for row in cursor.fetchall():
                    keyword = row[0]
                    score = row[1]
                    timestamp = row[2]
                    
                    if keyword not in trends:
                        trends[keyword] = []
                    trends[keyword].append({
                        'score': score,
                        'timestamp': timestamp
                    })
                
                # 分析趋势变化
                trend_analysis = {}
                for keyword, data in trends.items():
                    if len(data) >= 2:
                        latest_score = data[0]['score']
                        oldest_score = data[-1]['score']
                        trend_change = (latest_score - oldest_score) / oldest_score
                        
                        trend_analysis[keyword] = {
                            'current_score': latest_score,
                            'trend_change': trend_change,
                            'trend_direction': 'up' if trend_change > 0.1 else 'down' if trend_change < -0.1 else 'stable'
                        }
                
                return trend_analysis
        
        except Exception as e:
            logger.error(f"趋势分析失败: {e}")
            return {}
    
    # [热门] 新增:蓝海词识别核心算法
    def _mine_blue_ocean_keywords(self, category: str, base_keywords: List[TrendingKeyword]) -> List[TrendingKeyword]:
        """蓝海关键词挖掘"""
        blue_ocean_keywords = []
        
        try:
            # 1. 基于现有关键词扩展
            for base_kw in base_keywords[:10]:  # 取前10个基础词
                expanded = self._expand_keyword_with_modifiers(base_kw.keyword, category)
                blue_ocean_keywords.extend(expanded)
            
            # 2. 长尾词挖掘
            long_tail_keywords = self._generate_long_tail_keywords(category)
            blue_ocean_keywords.extend(long_tail_keywords)
            
            # 3. 竞争度过滤(保留低竞争词)
            filtered_keywords = [kw for kw in blue_ocean_keywords if kw.competition_level < 0.6]
            
            # 4. 计算蓝海分数
            for kw in filtered_keywords:
                kw.blue_ocean_score = self._calculate_blue_ocean_score(kw)
            
            # 5. 排序并返回最佳蓝海词
            filtered_keywords.sort(key=lambda x: x.blue_ocean_score, reverse=True)
            
            logger.info(f"[蓝海] 蓝海词挖掘完成,发现 {len(filtered_keywords[:15])} 个优质蓝海关键词")
            return filtered_keywords[:15]  # 返回前15个蓝海词
            
        except Exception as e:
            logger.error(f"蓝海词挖掘失败: {e}")
            return []
    
    def _expand_keyword_with_modifiers(self, base_keyword: str, category: str) -> List[TrendingKeyword]:
        """使用高价值修饰词扩展关键词"""
        expanded_keywords = []
        
        for modifier_type, modifiers in self.high_value_modifiers.items():
            for modifier in modifiers[:3]:  # 每种类型取3个
                # 前缀组合
                new_keyword1 = f"{modifier}{base_keyword}"
                # 后缀组合
                new_keyword2 = f"{base_keyword}{modifier}"
                
                for new_keyword in [new_keyword1, new_keyword2]:
                    if len(new_keyword) <= 10 and new_keyword != base_keyword:
                        # 模拟评估竞争度(实际应用中可接入真实数据)
                        competition = self._estimate_competition_level(new_keyword)
                        
                        expanded_keywords.append(TrendingKeyword(
                            keyword=new_keyword,
                            category=category,
                            trend_score=0.7,
                            search_volume=random.randint(50, 500),
                            competition_level=competition,
                            platform="blue_ocean_expansion",
                            growth_trend="stable",
                            user_intent="purchase"
                        ))
        
        return expanded_keywords
    
    def _generate_long_tail_keywords(self, category: str) -> List[TrendingKeyword]:
        """生成长尾关键词"""
        long_tail_keywords = []
        
        # 长尾关键词模板
        templates = [
            "{category}哪个牌子好",
            "{category}性价比高",
            "{category}质量好的推荐",
            "{category}舒适透气款",
            "{category}学生党必备",
            "{category}上班族专用",
            "好穿的{category}推荐",
            "不掉跟的{category}",
            "防臭{category}品牌",
            "纯棉{category}哪款好"
        ]
        
        for template in templates:
            keyword = template.format(category=category)
            long_tail_keywords.append(TrendingKeyword(
                keyword=keyword,
                category=category,
                trend_score=0.6,
                search_volume=random.randint(20, 200),
                competition_level=self._estimate_competition_level(keyword),
                platform="long_tail_generation",
                growth_trend="up",
                user_intent="compare"
            ))
        
        return long_tail_keywords
    
    def _estimate_competition_level(self, keyword: str) -> float:
        """估算关键词竞争度"""
        # 基于关键词特征估算竞争度
        competition = 0.5  # 基础竞争度
        
        # 长度因子:越长竞争度越低
        length_factor = max(0.1, 1.0 - (len(keyword) - 4) * 0.1)
        competition *= length_factor
        
        # 修饰词因子:包含修饰词的竞争度相对较低
        has_modifier = any(modifier in keyword for modifiers in self.high_value_modifiers.values() for modifier in modifiers)
        if has_modifier:
            competition *= 0.8
        
        # 长尾词因子:问句形式竞争度较低
        if any(question_word in keyword for question_word in ["哪个", "什么", "怎么", "推荐"]):
            competition *= 0.7
        
        return min(max(competition, 0.1), 0.9)
    
    def _calculate_blue_ocean_score(self, keyword: TrendingKeyword) -> float:
        """计算蓝海分数"""
        config = self.blue_ocean_config
        
        # 搜索量分数(归一化)
        volume_score = min(keyword.search_volume / 1000, 1.0) if keyword.search_volume > 0 else 0.3
        
        # 竞争度分数(越低越好)
        competition_score = 1.0 - keyword.competition_level
        
        # 趋势分数
        trend_score = 0.8 if keyword.growth_trend == "up" else 0.5 if keyword.growth_trend == "stable" else 0.3
        
        # 综合蓝海分数
        blue_ocean_score = (
            volume_score * config["volume_weight"] +
            competition_score * config["competition_weight"] +
            trend_score * config["trend_weight"]
        )
        
        return round(blue_ocean_score, 3)
    
    def _generate_smart_combinations(self, category: str) -> List[TrendingKeyword]:
        """智能关键词组合生成"""
        combination_keywords = []
        
        # 季节性组合
        current_season = self._get_current_season()
        season_modifiers = self.high_value_modifiers.get("季节类", [])
        
        for season in season_modifiers:
            if season in current_season or season == "四季":
                combo_keyword = f"{season}{category}"
                combination_keywords.append(TrendingKeyword(
                    keyword=combo_keyword,
                    category=category,
                    trend_score=0.75,
                    search_volume=random.randint(100, 400),
                    competition_level=self._estimate_competition_level(combo_keyword),
                    seasonal_factor=1.2 if season in current_season else 1.0,
                    platform="smart_combination",
                    user_intent="purchase"
                ))
        
        # 功能性组合
        function_combos = [
            f"防臭透气{category}",
            f"吸汗速干{category}",
            f"舒适柔软{category}",
            f"加厚保暖{category}"
        ]
        
        for combo in function_combos:
            combination_keywords.append(TrendingKeyword(
                keyword=combo,
                category=category,
                trend_score=0.8,
                search_volume=random.randint(80, 300),
                competition_level=self._estimate_competition_level(combo),
                platform="smart_combination",
                user_intent="purchase"
            ))
        
        return combination_keywords
    
    def _get_current_season(self) -> str:
        """获取当前季节"""
        month = datetime.now().month
        if month in [3, 4, 5]:
            return "春季"
        elif month in [6, 7, 8]:
            return "夏季"
        elif month in [9, 10, 11]:
            return "秋季"
        else:
            return "冬季"
    
    def _enhance_keywords_with_analysis(self, keywords: List[TrendingKeyword]) -> List[TrendingKeyword]:
        """增强关键词分析(竞争度、机会评估等)"""
        enhanced_keywords = []
        
        for kw in keywords:
            # 计算机会分数
            kw.opportunity_score = self._calculate_opportunity_score(kw)
            
            # 用户意图分析
            if not kw.user_intent or kw.user_intent == "unknown":
                kw.user_intent = self._analyze_user_intent(kw.keyword)
            
            # 季节性因子
            if kw.seasonal_factor == 1.0:
                kw.seasonal_factor = self._calculate_seasonal_factor(kw.keyword)
            
            enhanced_keywords.append(kw)
        
        # 去重和排序
        unique_keywords = self._merge_and_deduplicate(enhanced_keywords)
        
        return unique_keywords
    
    def _calculate_opportunity_score(self, keyword: TrendingKeyword) -> float:
        """计算关键词机会分数"""
        # 综合评估:蓝海分数 + 趋势分数 + 季节性加成
        base_score = keyword.blue_ocean_score * 0.5 + keyword.trend_score * 0.3
        
        # 季节性加成
        seasonal_bonus = (keyword.seasonal_factor - 1.0) * 0.2
        
        # 用户意图加成
        intent_bonus = 0.1 if keyword.user_intent == "purchase" else 0.05 if keyword.user_intent == "compare" else 0
        
        opportunity_score = base_score + seasonal_bonus + intent_bonus
        
        return round(min(opportunity_score, 1.0), 3)
    
    def _analyze_user_intent(self, keyword: str) -> str:
        """分析用户搜索意图"""
        if any(word in keyword for word in ["买", "购买", "价格", "多少钱", "便宜"]):
            return "purchase"
        elif any(word in keyword for word in ["对比", "哪个好", "推荐", "评价"]):
            return "compare"
        elif any(word in keyword for word in ["怎么", "如何", "什么是"]):
            return "browse"
        else:
            return "purchase"  # 默认为购买意图
    
    def _calculate_seasonal_factor(self, keyword: str) -> float:
        """计算季节性因子"""
        current_season = self._get_current_season()
        
        seasonal_keywords = {
            "春季": ["春", "透气", "薄款"],
            "夏季": ["夏", "清爽", "速干", "薄"],
            "秋季": ["秋", "保暖", "中厚"],
            "冬季": ["冬", "加厚", "保暖", "毛圈"]
        }
        
        # 检查关键词是否包含当前季节的特征
        current_keywords = seasonal_keywords.get(current_season, [])
        if any(season_word in keyword for season_word in current_keywords):
            return 1.3  # 季节性加成
        
        return 1.0  # 无季节性特征
    
    # [热门] 新增:蓝海词专用获取方法
    def get_blue_ocean_keywords(self, category_id: int, limit: int = 10) -> List[TrendingKeyword]:
        """
        获取指定类目的蓝海关键词
        
        Args:
            category_id: 类目ID (1=短袜, 2=中筒袜, 3=长筒袜)
            limit: 返回数量限制
            
        Returns:
            蓝海关键词列表(按蓝海分数排序)
        """
        category_name = self.category_mapping.get(category_id, "袜子")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT keyword, category, trend_score, search_volume, 
                           competition_level, blue_ocean_score, opportunity_score,
                           growth_trend, seasonal_factor, user_intent,
                           related_keywords, platform, created_at
                    FROM trending_keywords 
                    WHERE category = ? AND blue_ocean_score > 0.5 AND competition_level < 0.7
                    ORDER BY blue_ocean_score DESC, opportunity_score DESC
                    LIMIT ?
                ''', (category_name, limit))
                
                blue_ocean_keywords = []
                for row in cursor.fetchall():
                    related_keywords = json.loads(row[10]) if row[10] else []
                    
                    blue_ocean_keywords.append(TrendingKeyword(
                        keyword=row[0],
                        category=row[1],
                        trend_score=row[2],
                        search_volume=row[3],
                        competition_level=row[4],
                        blue_ocean_score=row[5],
                        opportunity_score=row[6],
                        growth_trend=row[7],
                        seasonal_factor=row[8],
                        user_intent=row[9],
                        related_keywords=related_keywords,
                        platform=row[11],
                        timestamp=datetime.fromisoformat(row[12])
                    ))
                
                return blue_ocean_keywords
                
        except Exception as e:
            logger.error(f"蓝海关键词查询失败: {e}")
            # 返回默认蓝海词
            return self._generate_default_blue_ocean_keywords(category_name, limit)
    
    def _generate_default_blue_ocean_keywords(self, category: str, limit: int) -> List[TrendingKeyword]:
        """生成默认蓝海关键词(当数据库为空时)"""
        default_blue_ocean = []
        
        # 基于当前季节生成
        current_season = self._get_current_season()
        season_keywords = {
            "夏季": [f"夏季透气{category}", f"清爽{category}", f"速干{category}"],
            "冬季": [f"加厚保暖{category}", f"冬季{category}", f"毛圈{category}"],
            "春季": [f"春季薄款{category}", f"透气{category}", f"舒适{category}"],
            "秋季": [f"秋季{category}", f"中厚{category}", f"保暖{category}"]
        }
        
        seasonal_words = season_keywords.get(current_season, season_keywords["夏季"])
        
        for i, keyword in enumerate(seasonal_words[:limit]):
            default_blue_ocean.append(TrendingKeyword(
                keyword=keyword,
                category=category,
                trend_score=0.7,
                search_volume=random.randint(100, 300),
                competition_level=0.4,
                blue_ocean_score=0.8 - i * 0.1,
                opportunity_score=0.7 - i * 0.05,
                growth_trend="up",
                seasonal_factor=1.3,
                user_intent="purchase",
                platform="default_blue_ocean"
            ))
        
        return default_blue_ocean
    
    def analyze_blue_ocean_opportunities(self, category_id: int) -> Dict[str, Any]:
        """
        分析蓝海机会
        
        Args:
            category_id: 类目ID
            
        Returns:
            蓝海机会分析报告
        """
        category_name = self.category_mapping.get(category_id, "袜子")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 获取蓝海词统计
                cursor = conn.execute('''
                    SELECT 
                        COUNT(*) as total_keywords,
                        COUNT(CASE WHEN blue_ocean_score > 0.7 THEN 1 END) as high_quality_blue_ocean,
                        COUNT(CASE WHEN competition_level < 0.5 THEN 1 END) as low_competition,
                        AVG(blue_ocean_score) as avg_blue_ocean_score,
                        AVG(competition_level) as avg_competition
                    FROM trending_keywords 
                    WHERE category = ? AND created_at >= datetime('now', '-7 days')
                ''', (category_name,))
                
                stats = cursor.fetchone()
                
                # 获取最佳蓝海词
                cursor = conn.execute('''
                    SELECT keyword, blue_ocean_score, competition_level, opportunity_score
                    FROM trending_keywords 
                    WHERE category = ? AND blue_ocean_score > 0.6
                    ORDER BY blue_ocean_score DESC
                    LIMIT 5
                ''', (category_name,))
                
                top_blue_ocean = cursor.fetchall()
                
                return {
                    "category": category_name,
                    "analysis_date": datetime.now().isoformat(),
                    "statistics": {
                        "total_keywords": stats[0] if stats[0] else 0,
                        "high_quality_blue_ocean": stats[1] if stats[1] else 0,
                        "low_competition_keywords": stats[2] if stats[2] else 0,
                        "avg_blue_ocean_score": round(stats[3], 3) if stats[3] else 0,
                        "avg_competition_level": round(stats[4], 3) if stats[4] else 0.5
                    },
                    "top_opportunities": [
                        {
                            "keyword": row[0],
                            "blue_ocean_score": row[1],
                            "competition_level": row[2],
                            "opportunity_score": row[3]
                        } for row in top_blue_ocean
                    ],
                    "recommendations": self._generate_blue_ocean_recommendations(stats)
                }
                
        except Exception as e:
            logger.error(f"蓝海机会分析失败: {e}")
            return {
                "error": str(e),
                "category": category_name,
                "analysis_date": datetime.now().isoformat()
            }
    
    def _generate_blue_ocean_recommendations(self, stats) -> List[str]:
        """生成蓝海词推荐建议"""
        recommendations = []
        
        if not stats or not stats[0]:
            recommendations.append("[处理] 建议先抓取关键词数据进行分析")
            return recommendations
        
        total_keywords = stats[0]
        high_quality_blue_ocean = stats[1] if stats[1] else 0
        avg_blue_ocean_score = stats[3] if stats[3] else 0
        avg_competition = stats[4] if stats[4] else 0.5
        
        # 基于统计数据生成建议
        if high_quality_blue_ocean / total_keywords > 0.3:
            recommendations.append("[成功] 该类目蓝海机会丰富,建议重点发力")
        else:
            recommendations.append("[警告] 蓝海机会相对较少,建议拓展长尾词")
        
        if avg_competition < 0.5:
            recommendations.append("[测试] 整体竞争度较低,有利于新品推广")
        else:
            recommendations.append("[优秀] 竞争激烈,建议选择差异化关键词")
        
        if avg_blue_ocean_score > 0.6:
            recommendations.append("[精品] 发现高价值蓝海词,建议优先使用")
        
        recommendations.append("[统计] 建议结合季节性因子选择关键词")
        recommendations.append("[设计] 利用功能性修饰词提升标题吸引力")
        
        return recommendations 

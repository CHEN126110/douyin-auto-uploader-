# -*- coding: utf-8 -*-
# [测试] 抖音热门关键词抓取器
# 从真实的抖音小店搜索页面抓取热门关键词和蓝海词

import requests
import json
import time
import re
import logging
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urljoin, quote
import sqlite3
import os
try:
    from bs4 import BeautifulSoup
    BeautifulSoupType = BeautifulSoup
except ImportError:
    # 如果没有安装bs4,使用简单的HTML解析
    BeautifulSoup = None
    BeautifulSoupType = Any
    print("[警告] 警告: 未安装BeautifulSoup4,将使用简单的正则表达式解析HTML")
import hashlib

logger = logging.getLogger(__name__)

@dataclass
class DouyinKeyword:
    """抖音关键词数据结构"""
    keyword: str
    search_volume: int = 0  # 搜索量
    competition_level: str = "unknown"  # 竞争程度: low/medium/high
    trend_score: float = 0.0  # 趋势分数
    category: str = "socks"
    related_keywords: List[str] = field(default_factory=list)
    pricing_range: Tuple[float, float] = (0.0, 0.0)  # 价格区间
    blue_ocean_score: float = 0.0  # 蓝海评分 (搜索量/竞争度)
    last_updated: datetime = field(default_factory=datetime.now)

@dataclass
class CompetitorAnalysis:
    """竞争对手分析"""
    total_products: int = 0
    avg_price: float = 0.0
    price_range: Tuple[float, float] = (0.0, 0.0)
    top_brands: List[str] = field(default_factory=list)
    promotion_rate: float = 0.0  # 促销比例
    avg_sales: int = 0

class DouyinKeywordsScraper:
    """抖音关键词抓取器"""
    
    def __init__(self):
        self.db_path = "douyin_keywords.db"
        self.session = self._create_session()
        self._init_database()
        
        # 袜子类目映射
        self.category_keywords = {
            1: ["船袜", "隐形袜", "浅口袜"],
            2: ["短袜", "棉袜", "运动袜"], 
            3: ["中筒袜", "商务袜", "休闲袜"],
            4: ["长筒袜", "过膝袜", "连裤袜"]
        }
        
        # 抖音搜索页面基础URL
        self.base_url = "https://compass.jinritemai.com/shop/chance/rank-search"
        
        logger.info("[测试] 抖音关键词抓取器已初始化")
    
    def _create_session(self) -> requests.Session:
        """创建请求会话"""
        session = requests.Session()
        
        # 设置请求头,模拟真实浏览器
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
        return session
    
    def _init_database(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建关键词表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS douyin_keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                search_volume INTEGER DEFAULT 0,
                competition_level TEXT DEFAULT 'unknown',
                trend_score REAL DEFAULT 0.0,
                category TEXT DEFAULT 'socks',
                related_keywords TEXT,
                min_price REAL DEFAULT 0.0,
                max_price REAL DEFAULT 0.0,
                blue_ocean_score REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(keyword, category)
            )
        ''')
        
        # 创建竞争分析表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS competitor_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                total_products INTEGER DEFAULT 0,
                avg_price REAL DEFAULT 0.0,
                min_price REAL DEFAULT 0.0,
                max_price REAL DEFAULT 0.0,
                top_brands TEXT,
                promotion_rate REAL DEFAULT 0.0,
                avg_sales INTEGER DEFAULT 0,
                analysis_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(keyword, analysis_date)
            )
        ''')
        
        conn.commit()
        conn.close()
        
        logger.info("[统计] 数据库初始化完成")
    
    def scrape_douyin_search_page(self, search_url: str) -> List[DouyinKeyword]:
        """
        抓取抖音搜索页面数据
        
        Args:
            search_url: 抖音搜索页面URL (用户登录后跳转的页面)
            
        Returns:
            关键词列表
        """
        try:
            logger.info(f"[检查] 开始抓取抖音搜索页面: {search_url}")
            
            # 发起请求
            response = self.session.get(search_url)
            response.raise_for_status()
            
            # 解析页面内容
            keywords = self._parse_search_page(response.text)
            
            # 存储到数据库
            self._save_keywords_to_db(keywords)
            
            logger.info(f"[成功] 成功抓取 {len(keywords)} 个关键词")
            return keywords
            
        except Exception as e:
            logger.error(f"[失败] 抓取抖音搜索页面失败: {e}")
            return []
    
    def _parse_search_page(self, html_content: str) -> List[DouyinKeyword]:
        """解析搜索页面HTML内容"""
        keywords = []
        
        try:
            if BeautifulSoup is None:
                # 使用正则表达式解析
                return self._parse_with_regex(html_content)
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # 查找关键词数据 (根据抖音页面结构调整)
            keyword_elements = soup.find_all(['span', 'div', 'td'], text=re.compile(r'袜|棉|短|长|船|运动'))
            
            for element in keyword_elements:
                keyword_text = element.get_text().strip()
                
                if self._is_valid_keyword(keyword_text):
                    # 分析竞争程度和搜索量
                    competition_data = self._analyze_keyword_competition(keyword_text, soup)
                    
                    keyword = DouyinKeyword(
                        keyword=keyword_text,
                        search_volume=competition_data.get('search_volume', 0),
                        competition_level=competition_data.get('competition_level', 'medium'),
                        trend_score=competition_data.get('trend_score', 0.5),
                        category="socks",
                        related_keywords=competition_data.get('related_keywords', []),
                        pricing_range=competition_data.get('pricing_range', (0.0, 0.0)),
                        blue_ocean_score=self._calculate_blue_ocean_score(
                            competition_data.get('search_volume', 0),
                            competition_data.get('competition_level', 'medium')
                        )
                    )
                    
                    keywords.append(keyword)
            
            # 去重和排序
            unique_keywords = self._deduplicate_keywords(keywords)
            sorted_keywords = sorted(unique_keywords, key=lambda x: x.blue_ocean_score, reverse=True)
            
            return sorted_keywords[:20]  # 返回前20个最有价值的关键词
            
        except Exception as e:
            logger.error(f"[失败] 解析页面内容失败: {e}")
            return []
    
    def _is_valid_keyword(self, keyword: str) -> bool:
        """判断是否为有效关键词"""
        if len(keyword) < 2 or len(keyword) > 10:
            return False
        
        # 排除无意义的词汇
        invalid_patterns = [
            r'^\d+dollar',  # 纯数字
            r'^[a-zA-Z]+dollar',  # 纯英文
            r'[^\u4e00-\u9fa5a-zA-Z0-9]',  # 特殊字符
        ]
        
        for pattern in invalid_patterns:
            if re.match(pattern, keyword):
                return False
        
        # 必须包含袜子相关词汇
        sock_keywords = ['袜', '棉', '丝', '筒', '船', '运动', '商务', '休闲']
        return any(sock_word in keyword for sock_word in sock_keywords)
    
    def _analyze_keyword_competition(self, keyword: str, soup) -> Dict:
        """分析关键词竞争程度"""
        try:
            # 在页面中查找与该关键词相关的数据
            competition_data = {
                'search_volume': 0,
                'competition_level': 'medium',
                'trend_score': 0.5,
                'related_keywords': [],
                'pricing_range': (0.0, 0.0)
            }
            
            # 尝试从页面数据中提取搜索量和竞争度
            # 这里需要根据抖音页面的实际结构来调整
            
            # 查找数字模式 (可能是搜索量或销量)
            number_patterns = soup.find_all(text=re.compile(r'\d+万?'))
            if number_patterns:
                numbers = []
                for pattern in number_patterns[:5]:  # 只取前5个数字
                    match = re.search(r'(\d+(?:\.\d+)?)万?', pattern)
                    if match:
                        num = float(match.group(1))
                        if '万' in pattern:
                            num *= 10000
                        numbers.append(int(num))
                
                if numbers:
                    competition_data['search_volume'] = max(numbers)
            
            # 分析竞争程度
            if competition_data['search_volume'] > 100000:
                competition_data['competition_level'] = 'high'
                competition_data['trend_score'] = 0.8
            elif competition_data['search_volume'] > 10000:
                competition_data['competition_level'] = 'medium'
                competition_data['trend_score'] = 0.6
            else:
                competition_data['competition_level'] = 'low'
                competition_data['trend_score'] = 0.4
            
            # 查找价格信息
            price_patterns = soup.find_all(text=re.compile(r'yuan?\d+(?:\.\d+)?'))
            prices = []
            for pattern in price_patterns:
                match = re.search(r'yuan?(\d+(?:\.\d+)?)', pattern)
                if match:
                    price = float(match.group(1))
                    if 1 <= price <= 200:  # 合理的袜子价格范围
                        prices.append(price)
            
            if prices:
                competition_data['pricing_range'] = (min(prices), max(prices))
            
            return competition_data
            
        except Exception as e:
            logger.warning(f"[警告] 分析关键词竞争度失败 {keyword}: {e}")
            return {
                'search_volume': 1000,
                'competition_level': 'medium', 
                'trend_score': 0.5,
                'related_keywords': [],
                'pricing_range': (10.0, 50.0)
            }
    
    def _calculate_blue_ocean_score(self, search_volume: int, competition_level: str) -> float:
        """计算蓝海评分"""
        # 竞争程度权重
        competition_weights = {
            'low': 1.0,
            'medium': 0.6,
            'high': 0.3
        }
        
        # 搜索量标准化 (0-1)
        normalized_volume = min(search_volume / 100000, 1.0)
        
        # 竞争权重
        competition_weight = competition_weights.get(competition_level, 0.6)
        
        # 蓝海评分 = 搜索量 * 反竞争权重
        blue_ocean_score = normalized_volume * competition_weight
        
        return round(blue_ocean_score, 3)
    
    def _deduplicate_keywords(self, keywords: List[DouyinKeyword]) -> List[DouyinKeyword]:
        """去重关键词"""
        seen = set()
        unique_keywords = []
        
        for keyword in keywords:
            if keyword.keyword not in seen:
                seen.add(keyword.keyword)
                unique_keywords.append(keyword)
        
        return unique_keywords
    
    def _save_keywords_to_db(self, keywords: List[DouyinKeyword]):
        """保存关键词到数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            for keyword in keywords:
                cursor.execute('''
                    INSERT OR REPLACE INTO douyin_keywords 
                    (keyword, search_volume, competition_level, trend_score, category,
                     related_keywords, min_price, max_price, blue_ocean_score, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    keyword.keyword,
                    keyword.search_volume,
                    keyword.competition_level,
                    keyword.trend_score,
                    keyword.category,
                    json.dumps(keyword.related_keywords),
                    keyword.pricing_range[0],
                    keyword.pricing_range[1],
                    keyword.blue_ocean_score,
                    datetime.now()
                ))
            
            conn.commit()
            conn.close()
            
            logger.info(f"[保存] 已保存 {len(keywords)} 个关键词到数据库")
            
        except Exception as e:
            logger.error(f"[失败] 保存关键词到数据库失败: {e}")
    
    def get_blue_ocean_keywords(self, category_id: int = 2, limit: int = 10) -> List[DouyinKeyword]:
        """获取蓝海关键词"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 查询蓝海评分最高的关键词
            cursor.execute('''
                SELECT keyword, search_volume, competition_level, trend_score, 
                       related_keywords, min_price, max_price, blue_ocean_score
                FROM douyin_keywords 
                WHERE category = 'socks' AND blue_ocean_score > 0.3
                ORDER BY blue_ocean_score DESC, search_volume DESC
                LIMIT ?
            ''', (limit,))
            
            results = cursor.fetchall()
            conn.close()
            
            keywords = []
            for row in results:
                keyword = DouyinKeyword(
                    keyword=row[0],
                    search_volume=row[1],
                    competition_level=row[2],
                    trend_score=row[3],
                    category="socks",
                    related_keywords=json.loads(row[4]) if row[4] else [],
                    pricing_range=(row[5], row[6]),
                    blue_ocean_score=row[7]
                )
                keywords.append(keyword)
            
            logger.info(f"[测试] 获取到 {len(keywords)} 个蓝海关键词")
            return keywords
            
        except Exception as e:
            logger.error(f"[失败] 获取蓝海关键词失败: {e}")
            return []
    
    def analyze_keyword_trends(self, days: int = 7) -> Dict[str, Any]:
        """分析关键词趋势"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 获取最近几天的数据
            date_threshold = datetime.now() - timedelta(days=days)
            
            cursor.execute('''
                SELECT keyword, blue_ocean_score, updated_at
                FROM douyin_keywords 
                WHERE updated_at >= ?
                ORDER BY updated_at DESC
            ''', (date_threshold,))
            
            results = cursor.fetchall()
            conn.close()
            
            # 分析趋势
            trending_up = []
            trending_down = []
            
            # 简单的趋势分析逻辑
            keyword_scores = {}
            for row in results:
                keyword, score, date = row
                if keyword not in keyword_scores:
                    keyword_scores[keyword] = []
                keyword_scores[keyword].append((score, date))
            
            for keyword, scores in keyword_scores.items():
                if len(scores) >= 2:
                    scores.sort(key=lambda x: x[1])  # 按时间排序
                    if scores[-1][0] > scores[0][0]:
                        trending_up.append(keyword)
                    elif scores[-1][0] < scores[0][0]:
                        trending_down.append(keyword)
            
            return {
                'trending_up': trending_up[:5],
                'trending_down': trending_down[:5],
                'total_keywords': len(keyword_scores),
                'analysis_period': f"{days}天"
            }
            
        except Exception as e:
            logger.error(f"[失败] 分析关键词趋势失败: {e}")
            return {}
    
    def get_competitor_analysis(self, keyword: str) -> Optional[CompetitorAnalysis]:
        """获取竞争对手分析"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT total_products, avg_price, min_price, max_price,
                       top_brands, promotion_rate, avg_sales
                FROM competitor_analysis 
                WHERE keyword = ?
                ORDER BY analysis_date DESC
                LIMIT 1
            ''', (keyword,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return CompetitorAnalysis(
                    total_products=result[0],
                    avg_price=result[1],
                    price_range=(result[2], result[3]),
                    top_brands=json.loads(result[4]) if result[4] else [],
                    promotion_rate=result[5],
                    avg_sales=result[6]
                )
            
            return None
            
        except Exception as e:
            logger.error(f"[失败] 获取竞争分析失败: {e}")
            return None

    def _parse_with_regex(self, html_content: str) -> List[DouyinKeyword]:
        """使用正则表达式解析HTML内容(备用方案)"""
        keywords = []
        
        try:
            # 查找可能的关键词模式
            patterns = [
                r'[船隐浅短棉运动中筒商务休闲长过膝连裤][袜]',
                r'[男女童成人][袜]',
                r'[春夏秋冬][袜]',
                r'[纯棉丝绸尼龙][袜]'
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, html_content)
                for match in matches:
                    if self._is_valid_keyword(match):
                        keyword = DouyinKeyword(
                            keyword=match,
                            search_volume=1000,
                            competition_level='medium',
                            trend_score=0.5,
                            category="socks",
                            blue_ocean_score=0.5
                        )
                        keywords.append(keyword)
            
            return self._deduplicate_keywords(keywords)
            
        except Exception as e:
            logger.error(f"[失败] 正则表达式解析失败: {e}")
            return []

# 全局实例
_douyin_scraper = None

def get_douyin_scraper() -> DouyinKeywordsScraper:
    """获取抖音抓取器实例"""
    global _douyin_scraper
    if _douyin_scraper is None:
        _douyin_scraper = DouyinKeywordsScraper()
    return _douyin_scraper 

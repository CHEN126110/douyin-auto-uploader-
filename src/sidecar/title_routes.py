# -*- coding: utf-8 -*-
"""商品标题生成与热门关键词接口。

其中智能标题 / 热门关键词两组返回的是模板与示例数据（AI 组件已移除），专业标题走 ``src.professional_title_generator``。"""
import json
import threading
import time
import traceback
from datetime import datetime

from flask import Blueprint, current_app, request

from src.professional_title_generator import (
    ProductInfo as ProfessionalProductInfo,
    get_professional_generator,
    sanitize_no_brand_title_text,
)
from .responses import api_error, api_ok


def create_title_blueprint(*, record_model):
    """依赖都由应用入口显式传入；本模块不导入 app.py。"""
    routes = Blueprint('title', __name__)
    Record = record_model

    @routes.post('/api/generate_smart_title')
    def generate_smart_title():
        """🧠 智能产品标题生成API"""
        try:
            data = request.get_json()
            record_id = data.get('record_id')
        
            if not record_id:
                return api_error('缺少产品ID参数')
        
            # 获取产品信息
            try:
                record = Record.get_by_id(record_id)
            except:
                return api_error('产品不存在')
        
            # 解析SKU列表
            sku_list = json.loads(record.content) if record.content else []
        
            base_name = sanitize_no_brand_title_text(record.name) if record.name else "产品"
            base_name = base_name or "产品"
        
            # 简化的标题建议
            suggestions_data = [
                {
                    'title': f"{base_name} 优质商品",
                    'confidence': 0.8,
                    'reasoning': "基础标题模板",
                    'tags': ["基础", "通用"],
                    'character_count': len(f"{base_name} 优质商品")
                },
                {
                    'title': f"精选 {base_name} 推荐",
                    'confidence': 0.7,
                    'reasoning': "推荐标题模板",
                    'tags': ["推荐", "精选"],
                    'character_count': len(f"精选 {base_name} 推荐")
                },
                {
                    'title': f"{base_name} 热销款",
                    'confidence': 0.6,
                    'reasoning': "热销标题模板",
                    'tags': ["热销", "流行"],
                    'character_count': len(f"{base_name} 热销款")
                }
            ]
        
            return api_ok(msg='标题生成成功！', data={
                'suggestions': suggestions_data,
                'product_info': {
                    'name': base_name,
                    'category': record.clazz if record.clazz else 1,
                    'sku_count': len(sku_list)
                }
            })
        
        except Exception as e:
            traceback.print_exc()
            return api_error(f'标题生成失败：{str(e)}')

    @routes.post('/api/generate_smart_title_enhanced')
    def generate_smart_title_enhanced():
        """[AI组件移除] 简化版增强标题生成API"""
        try:
            data = request.get_json()
            record_id = data.get('record_id')
            use_trending = data.get('use_trending', True)  # 是否使用热门词抓取
        
            if not record_id:
                return api_error('缺少产品ID参数')
        
            # 获取产品信息
            try:
                record = Record.get_by_id(record_id)
            except:
                return api_error('产品不存在')
        
            # 解析SKU列表
            sku_list = json.loads(record.content) if record.content else []
        
            base_name = sanitize_no_brand_title_text(record.name) if record.name else "产品"
            base_name = base_name or "产品"
        
            # 简化的增强标题建议
            suggestions_data = [
                {
                    'title': f"【热销】{base_name} 精品推荐",
                    'confidence': 0.9,
                    'reasoning': "增强热销标题模板",
                    'tags': ["热销", "精品", "推荐"],
                    'character_count': len(f"【热销】{base_name} 精品推荐")
                },
                {
                    'title': f"限时特价 {base_name} 优质好货",
                    'confidence': 0.85,
                    'reasoning': "限时特价标题模板",
                    'tags': ["限时", "特价", "优质"],
                    'character_count': len(f"限时特价 {base_name} 优质好货")
                },
                {
                    'title': f"新品上市 {base_name} 爆款推荐",
                    'confidence': 0.8,
                    'reasoning': "新品爆款标题模板",
                    'tags': ["新品", "爆款", "推荐"],
                    'character_count': len(f"新品上市 {base_name} 爆款推荐")
                },
                {
                    'title': f"品质保证 {base_name} 厂家直销",
                    'confidence': 0.75,
                    'reasoning': "品质保证标题模板",
                    'tags': ["品质", "保证", "直销"],
                    'character_count': len(f"品质保证 {base_name} 厂家直销")
                }
            ]
        
            # 模拟热门关键词
            trending_keywords = [
                {'keyword': '热销', 'trend_score': 0.9, 'platform': '抖音'},
                {'keyword': '精品', 'trend_score': 0.8, 'platform': '淘宝'},
                {'keyword': '限时', 'trend_score': 0.7, 'platform': '京东'},
                {'keyword': '新品', 'trend_score': 0.6, 'platform': '拼多多'}
            ]
        
            # 模拟网络状态
            network_status = {
                'status': 'stable',
                'latency': 50,
                'success_rate': 0.95
            }
        
            return api_ok(msg='增强标题生成成功！', data={
                'suggestions': suggestions_data,
                'product_info': {
                    'name': base_name,
                    'category': record.clazz if record.clazz else 1,
                    'sku_count': len(sku_list)
                },
                'trending_keywords': trending_keywords,
                'network_status': network_status,
                'generation_method': 'simplified_template'
            })
        
        except Exception as e:
            traceback.print_exc()
            # 如果增强版失败，降级到标准版
            try:
                return generate_smart_title()
            except:
                return api_error(f'标题生成失败：{str(e)}')

    @routes.get('/api/trending_keywords/<int:category_id>')
    def get_trending_keywords(category_id):
        """📈 获取指定类目的热门关键词 - 简化版本（已移除AI组件）"""
        try:
            limit = request.args.get('limit', 10, type=int)
        
            # 基础关键词模板
            basic_keywords = [
                "优质", "精选", "热销", "推荐", "新款", 
                "时尚", "舒适", "耐用", "实用", "经典",
                "高品质", "性价比", "畅销", "爆款", "限时"
            ]
        
            keywords_data = []
            for i, keyword in enumerate(basic_keywords[:limit]):
                keywords_data.append({
                    'keyword': keyword,
                    'trend_score': round(0.8 - i * 0.05, 3),  # 模拟趋势分数
                    'search_volume': 1000 - i * 50,  # 模拟搜索量
                    'platform': '综合平台',
                    'related_keywords': [f"{keyword}商品", f"{keyword}推荐"],
                    'timestamp': datetime.now().isoformat()
                })
        
            return api_ok(msg='关键词获取成功！', data={
                'keywords': keywords_data,
                'category_id': category_id,
                'total_count': len(keywords_data)
            })
        
        except Exception as e:
            traceback.print_exc()
            return api_error(f'获取关键词失败：{str(e)}')

    @routes.post('/api/refresh_trending_keywords')
    def refresh_trending_keywords():
        """🔄 手动刷新热门关键词 - 简化版本（已移除AI组件）"""
        try:
            data = request.get_json()
            category_id = data.get('category_id', 1)
        
            # 异步模拟刷新
        
            def refresh_async():
                try:
                    # 模拟刷新过程
                    time.sleep(1)  # 模拟网络请求时间
                    print(f"🔄 模拟刷新类目 {category_id} 的关键词完成")
                
                except Exception as e:
                    print(f"模拟刷新关键词失败: {e}")
        
            refresh_thread = threading.Thread(target=refresh_async, daemon=True)
            refresh_thread.start()
        
            return api_ok(msg='关键词刷新已启动，请稍后查看最新数据')
        
        except Exception as e:
            traceback.print_exc()
            return api_error(f'刷新关键词失败：{str(e)}')

    @routes.post('/api/generate_professional_title')
    def generate_professional_title():
        """🏆 专业产品标题生成API (60字符无重复)"""
        try:
            data = request.get_json()
            record_id = data.get('record_id')
        
            if not record_id:
                return api_error('缺少产品ID参数')
        
            # 获取产品信息
            try:
                record = Record.get_by_id(record_id)
            except:
                return api_error('产品不存在')
        
            # 解析SKU列表
            sku_list = json.loads(record.content) if record.content else []
        
            # 构建产品信息对象
            product_info = ProfessionalProductInfo(
                name=sanitize_no_brand_title_text(record.name),
                category=record.clazz if record.clazz else 2,
                remark=record.remark if record.remark else "",
                sku_list=sku_list
            )
        
            # 调用专业标题生成器
            professional_generator = get_professional_generator()
            title_suggestions = professional_generator.generate_professional_titles(product_info)
        
            # 格式化响应数据
            suggestions_data = []
            for suggestion in title_suggestions:
                suggestions_data.append({
                    'title': suggestion.title,
                    'confidence': suggestion.confidence,
                    'character_count': suggestion.character_count,
                    'tags': suggestion.tags,
                    'reasoning': suggestion.reasoning,
                    'blue_ocean_words': suggestion.blue_ocean_words
                })
        
            return api_ok(msg=f"专业标题生成成功！生成了 {len(suggestions_data)} 个60字符标题", data={
                'suggestions': suggestions_data,
                'product_info': {
                    'name': product_info.name,
                    'category': product_info.category,
                    'sku_count': len(product_info.sku_list)
                },
                'generation_method': 'professional_60_chars'
            })
        
        except Exception as e:
            current_app.logger.error(f"专业标题生成失败: {e}")
            return api_error(f'生成失败: {str(e)}')

    return routes

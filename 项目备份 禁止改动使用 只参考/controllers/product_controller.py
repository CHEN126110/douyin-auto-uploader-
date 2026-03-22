#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产品管理控制器 - 处理产品相关的HTTP请求
从app.py中提取的产品相关路由逻辑
"""

from typing import Dict, Any
import logging
from flask import request, jsonify

from services.product_service import ProductService
from core.container import injectable, inject

logger = logging.getLogger(__name__)


@injectable
class ProductController:
    """
    产品管理控制器
    负责处理产品相关的HTTP请求和响应
    """
    
    def __init__(self, product_service: ProductService):
        """
        初始化产品控制器
        
        Args:
            product_service: 产品服务层
        """
        self.service = product_service
    
    def load_detail(self) -> Dict[str, Any]:
        """
        加载产品详情
        对应原始路由: @app.get('/load_detail')
        
        Returns:
            产品详情响应
        """
        try:
            # 获取请求参数
            record_id = request.args.get('_id')
            if not record_id:
                return jsonify({'code': 400, 'msg': '记录ID不能为空！'})
            
            try:
                record_id = int(record_id)
            except (ValueError, TypeError):
                return jsonify({'code': 400, 'msg': '记录ID格式错误！'})
            
            # 调用服务层获取详情
            result = self.service.get_product_detail(record_id)
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"加载产品详情失败: {e}")
            return jsonify({'code': 500, 'msg': f'加载详情失败：{str(e)}'})
    
    def save_info(self) -> Dict[str, Any]:
        """
        保存产品信息
        对应原始路由: @app.post('/save_info')
        
        Returns:
            保存结果响应
        """
        try:
            # 获取请求数据
            request_data = request.get_json()
            if not request_data:
                return jsonify({'code': 400, 'msg': '请求数据为空！'})
            
            # 调用服务层保存信息
            result = self.service.save_product_info(request_data)
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"保存产品信息失败: {e}")
            return jsonify({'code': 500, 'msg': f'保存失败：{str(e)}'})
    
    def delete_sku(self) -> Dict[str, Any]:
        """
        删除产品SKU
        对应原始路由: @app.route('/delete_sku', methods=['POST'])
        
        Returns:
            删除结果响应
        """
        try:
            # 获取请求数据
            request_data = request.get_json()
            if not request_data:
                return jsonify({'code': 400, 'msg': '请求数据为空！'})
            
            # 调用服务层删除SKU
            result = self.service.delete_product_sku(request_data)
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"删除SKU失败: {e}")
            return jsonify({'code': 500, 'msg': f'删除SKU失败：{str(e)}'})
    
    def delete_all(self) -> Dict[str, Any]:
        """
        删除所有产品记录
        对应原始路由: @app.delete('/delete_all')
        
        Returns:
            删除结果响应
        """
        try:
            # 调用服务层删除所有记录
            result = self.service.delete_all_products()
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"删除所有产品失败: {e}")
            return jsonify({'code': 500, 'msg': f'删除失败：{str(e)}'})
    
    def get_products(self) -> Dict[str, Any]:
        """
        获取产品列表
        新增功能：支持分页和搜索
        
        Returns:
            产品列表响应
        """
        try:
            # 获取查询参数
            limit = request.args.get('limit', type=int)
            offset = request.args.get('offset', type=int, default=0)
            keyword = request.args.get('keyword', '').strip()
            
            # 根据是否有搜索关键词选择不同的服务方法
            if keyword:
                result = self.service.search_products(keyword)
            else:
                result = self.service.get_all_products(limit=limit, offset=offset)
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"获取产品列表失败: {e}")
            return jsonify({'code': 500, 'msg': f'获取产品列表失败：{str(e)}'})
    
    def get_product_statistics(self) -> Dict[str, Any]:
        """
        获取产品统计信息
        新增功能：提供产品数据统计
        
        Returns:
            统计信息响应
        """
        try:
            result = self.service.get_product_statistics()
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"获取产品统计信息失败: {e}")
            return jsonify({'code': 500, 'msg': f'获取统计信息失败：{str(e)}'})
    
    def update_product_status(self) -> Dict[str, Any]:
        """
        更新产品状态
        新增功能：单个产品状态更新
        
        Returns:
            更新结果响应
        """
        try:
            request_data = request.get_json()
            if not request_data:
                return jsonify({'code': 400, 'msg': '请求数据为空！'})
            
            record_id = request_data.get('id')
            status = request_data.get('status')
            
            if record_id is None:
                return jsonify({'code': 400, 'msg': '产品ID不能为空！'})
            
            if status is None:
                return jsonify({'code': 400, 'msg': '状态值不能为空！'})
            
            try:
                record_id = int(record_id)
                status = int(status)
            except (ValueError, TypeError):
                return jsonify({'code': 400, 'msg': 'ID或状态格式错误！'})
            
            result = self.service.update_product_status(record_id, status)
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"更新产品状态失败: {e}")
            return jsonify({'code': 500, 'msg': f'更新状态失败：{str(e)}'})
    
    def batch_update_status(self) -> Dict[str, Any]:
        """
        批量更新产品状态
        新增功能：批量状态更新
        
        Returns:
            更新结果响应
        """
        try:
            request_data = request.get_json()
            if not request_data:
                return jsonify({'code': 400, 'msg': '请求数据为空！'})
            
            record_ids = request_data.get('ids', [])
            status = request_data.get('status')
            
            if not record_ids:
                return jsonify({'code': 400, 'msg': '产品ID列表不能为空！'})
            
            if status is None:
                return jsonify({'code': 400, 'msg': '状态值不能为空！'})
            
            try:
                record_ids = [int(id_) for id_ in record_ids]
                status = int(status)
            except (ValueError, TypeError):
                return jsonify({'code': 400, 'msg': 'ID列表或状态格式错误！'})
            
            result = self.service.batch_update_status(record_ids, status)
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"批量更新产品状态失败: {e}")
            return jsonify({'code': 500, 'msg': f'批量更新失败：{str(e)}'})
    
    def create_product(self) -> Dict[str, Any]:
        """
        创建新产品
        新增功能：产品创建
        
        Returns:
            创建结果响应
        """
        try:
            request_data = request.get_json()
            if not request_data:
                return jsonify({'code': 400, 'msg': '请求数据为空！'})
            
            result = self.service.create_product(request_data)
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"创建产品失败: {e}")
            return jsonify({'code': 500, 'msg': f'创建产品失败：{str(e)}'})
    
    def search_products(self) -> Dict[str, Any]:
        """
        搜索产品
        新增功能：产品搜索
        
        Returns:
            搜索结果响应
        """
        try:
            keyword = request.args.get('keyword', '').strip()
            if not keyword:
                return jsonify({'code': 400, 'msg': '搜索关键词不能为空！'})
            
            result = self.service.search_products(keyword)
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"搜索产品失败: {e}")
            return jsonify({'code': 500, 'msg': f'搜索失败：{str(e)}'})


def register_product_routes(app, container):
    """
    注册产品相关路由
    
    Args:
        app: Flask应用实例
        container: 依赖注入容器
    """
    # 从容器中获取控制器实例
    controller = container.resolve(ProductController)
    
    # 注册原有路由（保持向后兼容）
    app.add_url_rule('/load_detail', 'load_detail', controller.load_detail, methods=['GET'])
    app.add_url_rule('/save_info', 'save_info', controller.save_info, methods=['POST'])
    app.add_url_rule('/delete_sku', 'delete_sku', controller.delete_sku, methods=['POST'])
    app.add_url_rule('/delete_all', 'delete_all', controller.delete_all, methods=['DELETE'])
    
    # 注册新增路由（RESTful API）
    app.add_url_rule('/api/products', 'get_products', controller.get_products, methods=['GET'])
    app.add_url_rule('/api/products', 'create_product', controller.create_product, methods=['POST'])
    app.add_url_rule('/api/products/search', 'search_products', controller.search_products, methods=['GET'])
    app.add_url_rule('/api/products/statistics', 'get_product_statistics', controller.get_product_statistics, methods=['GET'])
    app.add_url_rule('/api/products/status', 'update_product_status', controller.update_product_status, methods=['PUT'])
    app.add_url_rule('/api/products/batch/status', 'batch_update_status', controller.batch_update_status, methods=['PUT'])


# 便捷函数：获取控制器实例
def get_product_controller() -> ProductController:
    """
    获取产品控制器实例
    
    Returns:
        产品控制器实例
    """
    return inject(ProductController)


if __name__ == "__main__":
    # 测试代码
    from core.container import container
    from services.product_service import ProductService
    from repositories.product_repository import ProductRepository
    
    # 注册依赖
    container.register_singleton(ProductRepository, ProductRepository)
    container.register_singleton(ProductService, ProductService)
    container.register_singleton(ProductController, ProductController)
    
    # 测试控制器
    controller = container.resolve(ProductController)
    print(f"产品控制器创建成功: {controller}")
    
    # 模拟测试（需要Flask上下文）
    print("产品控制器测试完成")
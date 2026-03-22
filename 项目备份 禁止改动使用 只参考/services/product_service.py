#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产品服务层 - 负责产品相关的业务逻辑处理
包括产品数据处理、图片处理、SKU管理等核心业务功能
"""

from typing import List, Optional, Dict, Any, Tuple
import json
import logging
from datetime import datetime
import base64
import os

from repositories.product_repository import ProductRepository
from src.orm import Record
from src.utils import time, api_ok, api_error
from core.container import injectable

logger = logging.getLogger(__name__)


@injectable
class ProductService:
    """
    产品服务层
    负责产品相关的所有业务逻辑处理
    """
    
    def __init__(self, product_repository: ProductRepository):
        """
        初始化产品服务
        
        Args:
            product_repository: 产品数据访问层
        """
        self.repository = product_repository
    
    def get_product_detail(self, record_id: int) -> Dict[str, Any]:
        """
        获取产品详情
        
        Args:
            record_id: 产品记录ID
            
        Returns:
            产品详情数据
        """
        try:
            record = self.repository.get_by_id(record_id)
            if not record:
                return api_error(msg='记录不存在！')
            
            # 解析SKU数据
            try:
                content_data = json.loads(record.content) if record.content else []
            except json.JSONDecodeError:
                logger.warning(f"产品ID {record_id} 的content数据格式错误")
                content_data = []
            
            # 构建返回数据
            product_data = {
                'id': record.id,
                'name': record.name,
                'title': record.title or '',
                'remark': record.remark or '',
                'clazz': record.clazz or 0,
                'repo': record.repo or 0,
                'status': record.status,
                'type': record.type,
                'path': record.path,
                'shipping_template': getattr(record, 'shipping_template', '中通包邮'),
                'update_time': record.update_time.strftime('%Y-%m-%d %H:%M:%S') if record.update_time else '',
                'publish_time': record.publish_time.strftime('%Y-%m-%d %H:%M:%S') if record.publish_time else '',
                'content': content_data
            }
            
            return api_ok(data=product_data)
            
        except Exception as e:
            logger.error(f"获取产品详情失败: {e}")
            return api_error(msg=f'获取产品详情失败：{str(e)}')
    
    def save_product_info(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        保存产品信息
        
        Args:
            request_data: 请求数据
            
        Returns:
            保存结果
        """
        try:
            if not request_data:
                return api_error(msg='请求数据为空！')
            
            record_id = request_data.get('_id')
            if not record_id:
                return api_error(msg='记录ID不能为空！')
            
            record = self.repository.get_by_id(record_id)
            if not record:
                return api_error(msg='记录不存在！')
            
            # 准备更新数据
            update_data = {}
            
            # 更新类目
            clazz = request_data.get('clazz')
            if clazz is not None and str(clazz).strip():
                try:
                    update_data['clazz'] = int(clazz)
                except (ValueError, TypeError) as e:
                    logger.warning(f"类目转换失败: {e}")
            
            # 更新基本信息
            update_data['title'] = request_data.get('title', '')
            update_data['remark'] = request_data.get('remark', '')
            
            # 更新仓库
            repo = request_data.get('repo')
            if repo is not None and str(repo).strip():
                try:
                    update_data['repo'] = int(repo)
                except (ValueError, TypeError) as e:
                    logger.warning(f"仓库转换失败: {e}")
            
            # 更新SKU数据
            try:
                sku_content = self._process_sku_data(record.content, request_data)
                update_data['content'] = sku_content
            except Exception as e:
                logger.error(f"SKU数据处理失败: {e}")
                return api_error(msg=f'SKU数据处理失败：{str(e)}')
            
            # 执行更新
            success = self.repository.update(record_id, update_data)
            if success:
                logger.info(f"产品信息保存成功: ID={record_id}")
                return api_ok(msg='保存成功！', data={
                    'id': record_id,
                    'update_time': datetime.now().strftime('%Y-%m-%d %H:%M')
                })
            else:
                return api_error(msg='保存失败！')
                
        except Exception as e:
            logger.error(f"保存产品信息失败: {e}")
            return api_error(msg=f'保存失败：{str(e)}')
    
    def _process_sku_data(self, original_content: str, request_data: Dict[str, Any]) -> str:
        """
        处理SKU数据
        
        Args:
            original_content: 原始content数据
            request_data: 请求数据
            
        Returns:
            处理后的content JSON字符串
        """
        try:
            # 解析原始数据
            original_data = json.loads(original_content) if original_content else []
            
            # 构建路径映射
            path_map = {}
            for item in original_data:
                if 'path' in item:
                    path_map[item['path']] = item
            
            # 处理属性数据
            attr_size = int(request_data.get('attr_size', 0))
            for i in range(attr_size):
                path_key = f'attr_path_{i + 1}'
                name_key = f'attr_name_{i + 1}'
                price_key = f'attr_price_{i + 1}'
                
                attr_path = request_data.get(path_key)
                if attr_path and attr_path in path_map:
                    # 更新名称
                    path_map[attr_path]['name'] = request_data.get(name_key, '')
                    
                    # 更新价格，确保是数字
                    try:
                        price_value = request_data.get(price_key, '0')
                        path_map[attr_path]['price'] = float(price_value) if price_value else 0.0
                    except (ValueError, TypeError):
                        path_map[attr_path]['price'] = 0.0
                        logger.warning(f"价格转换失败，使用默认值0: {price_key}")
            
            return json.dumps(list(path_map.values()))
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"SKU数据处理失败: {e}")
            raise
    
    def delete_product_sku(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        删除产品SKU
        
        Args:
            request_data: 请求数据
            
        Returns:
            删除结果
        """
        try:
            if not request_data:
                return api_error(msg='请求数据为空！')
            
            record_id = request_data.get('_id')
            sku_path = request_data.get('path')
            
            if not record_id:
                return api_error(msg='记录ID不能为空！')
            
            if not sku_path:
                return api_error(msg='SKU路径不能为空！')
            
            record = self.repository.get_by_id(record_id)
            if not record:
                return api_error(msg='记录不存在！')
            
            # 解析并处理SKU数据
            try:
                content_data = json.loads(record.content) if record.content else []
                
                # 过滤掉指定路径的SKU
                filtered_data = [item for item in content_data if item.get('path') != sku_path]
                
                # 更新记录
                update_data = {
                    'content': json.dumps(filtered_data)
                }
                
                success = self.repository.update(record_id, update_data)
                if success:
                    logger.info(f"SKU删除成功: 记录ID={record_id}, 路径={sku_path}")
                    return api_ok(msg='SKU删除成功！')
                else:
                    return api_error(msg='SKU删除失败！')
                    
            except json.JSONDecodeError as e:
                logger.error(f"SKU数据解析失败: {e}")
                return api_error(msg='SKU数据格式错误！')
                
        except Exception as e:
            logger.error(f"删除SKU失败: {e}")
            return api_error(msg=f'删除SKU失败：{str(e)}')
    
    def delete_all_products(self) -> Dict[str, Any]:
        """
        删除所有产品记录
        
        Returns:
            删除结果
        """
        try:
            deleted_count = self.repository.delete_all()
            logger.info(f"删除所有产品记录成功，共删除{deleted_count}条记录")
            return api_ok(msg=f'成功删除{deleted_count}条记录！', data={'deleted_count': deleted_count})
            
        except Exception as e:
            logger.error(f"删除所有产品记录失败: {e}")
            return api_error(msg=f'删除失败：{str(e)}')
    
    def get_all_products(self, limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
        """
        获取所有产品列表
        
        Args:
            limit: 限制数量
            offset: 偏移量
            
        Returns:
            产品列表
        """
        try:
            records = self.repository.get_all(limit=limit, offset=offset)
            
            products = []
            for record in records:
                try:
                    content_data = json.loads(record.content) if record.content else []
                except json.JSONDecodeError:
                    content_data = []
                
                product = {
                    'id': record.id,
                    'name': record.name,
                    'title': record.title or '',
                    'remark': record.remark or '',
                    'clazz': record.clazz or 0,
                    'repo': record.repo or 0,
                    'status': record.status,
                    'type': record.type,
                    'path': record.path,
                    'shipping_template': getattr(record, 'shipping_template', '中通包邮'),
                    'update_time': record.update_time.strftime('%Y-%m-%d %H:%M:%S') if record.update_time else '',
                    'publish_time': record.publish_time.strftime('%Y-%m-%d %H:%M:%S') if record.publish_time else '',
                    'sku_count': len(content_data)
                }
                products.append(product)
            
            return api_ok(data={
                'products': products,
                'total': self.repository.count(),
                'limit': limit,
                'offset': offset
            })
            
        except Exception as e:
            logger.error(f"获取产品列表失败: {e}")
            return api_error(msg=f'获取产品列表失败：{str(e)}')
    
    def search_products(self, keyword: str) -> Dict[str, Any]:
        """
        搜索产品
        
        Args:
            keyword: 搜索关键词
            
        Returns:
            搜索结果
        """
        try:
            if not keyword or not keyword.strip():
                return api_error(msg='搜索关键词不能为空！')
            
            records = self.repository.search_by_keyword(keyword.strip())
            
            products = []
            for record in records:
                try:
                    content_data = json.loads(record.content) if record.content else []
                except json.JSONDecodeError:
                    content_data = []
                
                product = {
                    'id': record.id,
                    'name': record.name,
                    'title': record.title or '',
                    'remark': record.remark or '',
                    'clazz': record.clazz or 0,
                    'repo': record.repo or 0,
                    'status': record.status,
                    'type': record.type,
                    'path': record.path,
                    'shipping_template': getattr(record, 'shipping_template', '中通包邮'),
                    'update_time': record.update_time.strftime('%Y-%m-%d %H:%M:%S') if record.update_time else '',
                    'publish_time': record.publish_time.strftime('%Y-%m-%d %H:%M:%S') if record.publish_time else '',
                    'sku_count': len(content_data)
                }
                products.append(product)
            
            return api_ok(data={
                'products': products,
                'keyword': keyword,
                'total': len(products)
            })
            
        except Exception as e:
            logger.error(f"搜索产品失败: {e}")
            return api_error(msg=f'搜索失败：{str(e)}')
    
    def get_product_statistics(self) -> Dict[str, Any]:
        """
        获取产品统计信息
        
        Returns:
            统计信息
        """
        try:
            stats = self.repository.get_statistics()
            return api_ok(data=stats)
            
        except Exception as e:
            logger.error(f"获取产品统计信息失败: {e}")
            return api_error(msg=f'获取统计信息失败：{str(e)}')
    
    def update_product_status(self, record_id: int, status: int) -> Dict[str, Any]:
        """
        更新产品状态
        
        Args:
            record_id: 产品记录ID
            status: 新状态
            
        Returns:
            更新结果
        """
        try:
            success = self.repository.update(record_id, {'status': status})
            if success:
                logger.info(f"产品状态更新成功: ID={record_id}, 状态={status}")
                return api_ok(msg='状态更新成功！')
            else:
                return api_error(msg='状态更新失败！')
                
        except Exception as e:
            logger.error(f"更新产品状态失败: {e}")
            return api_error(msg=f'状态更新失败：{str(e)}')
    
    def batch_update_status(self, record_ids: List[int], status: int) -> Dict[str, Any]:
        """
        批量更新产品状态
        
        Args:
            record_ids: 产品记录ID列表
            status: 新状态
            
        Returns:
            更新结果
        """
        try:
            if not record_ids:
                return api_error(msg='产品ID列表不能为空！')
            
            updated_count = self.repository.batch_update_status(record_ids, status)
            logger.info(f"批量状态更新成功: 更新{updated_count}条记录，状态={status}")
            
            return api_ok(msg=f'成功更新{updated_count}条记录状态！', data={
                'updated_count': updated_count,
                'status': status
            })
            
        except Exception as e:
            logger.error(f"批量更新产品状态失败: {e}")
            return api_error(msg=f'批量更新失败：{str(e)}')
    
    def validate_product_data(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        验证产品数据
        
        Args:
            data: 产品数据
            
        Returns:
            (是否有效, 错误信息)
        """
        try:
            # 检查必填字段
            required_fields = ['name', 'path', 'content']
            for field in required_fields:
                if not data.get(field):
                    return False, f'字段 {field} 不能为空'
            
            # 验证content格式
            if data.get('content'):
                try:
                    content_data = json.loads(data['content'])
                    if not isinstance(content_data, list):
                        return False, 'content字段必须是JSON数组格式'
                except json.JSONDecodeError:
                    return False, 'content字段JSON格式错误'
            
            # 验证数值字段
            numeric_fields = ['type', 'status', 'clazz', 'repo']
            for field in numeric_fields:
                if field in data and data[field] is not None:
                    try:
                        int(data[field])
                    except (ValueError, TypeError):
                        return False, f'字段 {field} 必须是数字'
            
            return True, ''
            
        except Exception as e:
            logger.error(f"验证产品数据失败: {e}")
            return False, f'数据验证失败：{str(e)}'
    
    def create_product(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        创建新产品
        
        Args:
            data: 产品数据
            
        Returns:
            创建结果
        """
        try:
            # 验证数据
            is_valid, error_msg = self.validate_product_data(data)
            if not is_valid:
                return api_error(msg=error_msg)
            
            # 检查名称是否已存在
            if self.repository.exists_by_name(data['name']):
                return api_error(msg='产品名称已存在！')
            
            # 创建产品
            record = self.repository.create(data)
            if record:
                logger.info(f"产品创建成功: {record.name}")
                return api_ok(msg='产品创建成功！', data={
                    'id': record.id,
                    'name': record.name
                })
            else:
                return api_error(msg='产品创建失败！')
                
        except Exception as e:
            logger.error(f"创建产品失败: {e}")
            return api_error(msg=f'创建失败：{str(e)}')
    
    def process_image_data(self, image_data: str, save_path: str) -> bool:
        """
        处理图片数据
        
        Args:
            image_data: Base64编码的图片数据
            save_path: 保存路径
            
        Returns:
            是否处理成功
        """
        try:
            # 解码Base64数据
            if image_data.startswith('data:image'):
                # 移除data:image/xxx;base64,前缀
                image_data = image_data.split(',')[1]
            
            image_bytes = base64.b64decode(image_data)
            
            # 确保目录存在
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            # 保存图片
            with open(save_path, 'wb') as f:
                f.write(image_bytes)
            
            logger.info(f"图片保存成功: {save_path}")
            return True
            
        except Exception as e:
            logger.error(f"处理图片数据失败: {e}")
            return False


# 创建全局实例（可选）
# product_service = ProductService(ProductRepository())


if __name__ == "__main__":
    # 测试代码
    from repositories.product_repository import ProductRepository
    
    repo = ProductRepository()
    service = ProductService(repo)
    
    # 测试获取产品列表
    result = service.get_all_products(limit=10)
    print(f"获取产品列表结果: {result}")
    
    # 测试获取统计信息
    stats = service.get_product_statistics()
    print(f"统计信息: {stats}")
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产品数据访问层 - 负责Record模型的CRUD操作
实现数据查询、过滤、分页等功能
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import logging
from peewee import DoesNotExist, IntegrityError

from src.orm import Record, database
from core.container import injectable

logger = logging.getLogger(__name__)


@injectable
class ProductRepository:
    """
    产品数据访问层
    负责Record模型的所有数据库操作
    """
    
    def __init__(self):
        """初始化产品仓储"""
        self.model = Record
    
    def get_all(self, limit: Optional[int] = None, offset: int = 0) -> List[Record]:
        """
        获取所有产品记录
        
        Args:
            limit: 限制返回数量
            offset: 偏移量
            
        Returns:
            产品记录列表
        """
        try:
            query = self.model.select().order_by(self.model.update_time.desc())
            
            if offset > 0:
                query = query.offset(offset)
            
            if limit:
                query = query.limit(limit)
            
            return list(query)
        except Exception as e:
            logger.error(f"获取所有产品记录失败: {e}")
            return []
    
    def get_by_id(self, record_id: int) -> Optional[Record]:
        """
        根据ID获取产品记录
        
        Args:
            record_id: 记录ID
            
        Returns:
            产品记录或None
        """
        try:
            return self.model.get_by_id(record_id)
        except DoesNotExist:
            logger.warning(f"未找到ID为{record_id}的产品记录")
            return None
        except Exception as e:
            logger.error(f"根据ID获取产品记录失败: {e}")
            return None
    
    def get_by_name(self, name: str) -> Optional[Record]:
        """
        根据名称获取产品记录
        
        Args:
            name: 产品名称
            
        Returns:
            产品记录或None
        """
        try:
            return self.model.get(self.model.name == name)
        except DoesNotExist:
            logger.warning(f"未找到名称为{name}的产品记录")
            return None
        except Exception as e:
            logger.error(f"根据名称获取产品记录失败: {e}")
            return None
    
    def get_by_type(self, record_type: int) -> List[Record]:
        """
        根据类型获取产品记录
        
        Args:
            record_type: 记录类型
            
        Returns:
            产品记录列表
        """
        try:
            return list(self.model.select().where(self.model.type == record_type))
        except Exception as e:
            logger.error(f"根据类型获取产品记录失败: {e}")
            return []
    
    def get_by_status(self, status: int) -> List[Record]:
        """
        根据状态获取产品记录
        
        Args:
            status: 记录状态
            
        Returns:
            产品记录列表
        """
        try:
            return list(self.model.select().where(self.model.status == status))
        except Exception as e:
            logger.error(f"根据状态获取产品记录失败: {e}")
            return []
    
    def search_by_keyword(self, keyword: str) -> List[Record]:
        """
        根据关键词搜索产品记录
        
        Args:
            keyword: 搜索关键词
            
        Returns:
            匹配的产品记录列表
        """
        try:
            return list(
                self.model.select().where(
                    (self.model.name.contains(keyword)) |
                    (self.model.title.contains(keyword)) |
                    (self.model.content.contains(keyword)) |
                    (self.model.remark.contains(keyword))
                ).order_by(self.model.update_time.desc())
            )
        except Exception as e:
            logger.error(f"搜索产品记录失败: {e}")
            return []
    
    def create(self, data: Dict[str, Any]) -> Optional[Record]:
        """
        创建新的产品记录
        
        Args:
            data: 产品数据字典
            
        Returns:
            创建的产品记录或None
        """
        try:
            # 设置默认值
            data.setdefault('update_time', datetime.now())
            data.setdefault('status', 0)
            data.setdefault('type', 0)
            data.setdefault('shipping_template', '中通包邮')
            
            record = self.model.create(**data)
            logger.info(f"成功创建产品记录: {record.name}")
            return record
        except IntegrityError as e:
            logger.error(f"创建产品记录失败，数据完整性错误: {e}")
            return None
        except Exception as e:
            logger.error(f"创建产品记录失败: {e}")
            return None
    
    def update(self, record_id: int, data: Dict[str, Any]) -> bool:
        """
        更新产品记录
        
        Args:
            record_id: 记录ID
            data: 更新数据字典
            
        Returns:
            是否更新成功
        """
        try:
            # 自动更新时间
            data['update_time'] = datetime.now()
            
            query = self.model.update(**data).where(self.model.id == record_id)
            rows_updated = query.execute()
            
            if rows_updated > 0:
                logger.info(f"成功更新产品记录ID: {record_id}")
                return True
            else:
                logger.warning(f"未找到ID为{record_id}的产品记录进行更新")
                return False
        except Exception as e:
            logger.error(f"更新产品记录失败: {e}")
            return False
    
    def update_by_name(self, name: str, data: Dict[str, Any]) -> bool:
        """
        根据名称更新产品记录
        
        Args:
            name: 产品名称
            data: 更新数据字典
            
        Returns:
            是否更新成功
        """
        try:
            # 自动更新时间
            data['update_time'] = datetime.now()
            
            query = self.model.update(**data).where(self.model.name == name)
            rows_updated = query.execute()
            
            if rows_updated > 0:
                logger.info(f"成功更新产品记录: {name}")
                return True
            else:
                logger.warning(f"未找到名称为{name}的产品记录进行更新")
                return False
        except Exception as e:
            logger.error(f"根据名称更新产品记录失败: {e}")
            return False
    
    def delete(self, record_id: int) -> bool:
        """
        删除产品记录
        
        Args:
            record_id: 记录ID
            
        Returns:
            是否删除成功
        """
        try:
            query = self.model.delete().where(self.model.id == record_id)
            rows_deleted = query.execute()
            
            if rows_deleted > 0:
                logger.info(f"成功删除产品记录ID: {record_id}")
                return True
            else:
                logger.warning(f"未找到ID为{record_id}的产品记录进行删除")
                return False
        except Exception as e:
            logger.error(f"删除产品记录失败: {e}")
            return False
    
    def delete_by_name(self, name: str) -> bool:
        """
        根据名称删除产品记录
        
        Args:
            name: 产品名称
            
        Returns:
            是否删除成功
        """
        try:
            query = self.model.delete().where(self.model.name == name)
            rows_deleted = query.execute()
            
            if rows_deleted > 0:
                logger.info(f"成功删除产品记录: {name}")
                return True
            else:
                logger.warning(f"未找到名称为{name}的产品记录进行删除")
                return False
        except Exception as e:
            logger.error(f"根据名称删除产品记录失败: {e}")
            return False
    
    def delete_all(self) -> int:
        """
        删除所有产品记录
        
        Returns:
            删除的记录数量
        """
        try:
            rows_deleted = self.model.delete().execute()
            logger.info(f"成功删除{rows_deleted}条产品记录")
            return rows_deleted
        except Exception as e:
            logger.error(f"删除所有产品记录失败: {e}")
            return 0
    
    def count(self) -> int:
        """
        获取产品记录总数
        
        Returns:
            记录总数
        """
        try:
            return self.model.select().count()
        except Exception as e:
            logger.error(f"获取产品记录总数失败: {e}")
            return 0
    
    def count_by_status(self, status: int) -> int:
        """
        根据状态获取产品记录数量
        
        Args:
            status: 记录状态
            
        Returns:
            指定状态的记录数量
        """
        try:
            return self.model.select().where(self.model.status == status).count()
        except Exception as e:
            logger.error(f"根据状态获取产品记录数量失败: {e}")
            return 0
    
    def exists(self, record_id: int) -> bool:
        """
        检查产品记录是否存在
        
        Args:
            record_id: 记录ID
            
        Returns:
            是否存在
        """
        try:
            return self.model.select().where(self.model.id == record_id).exists()
        except Exception as e:
            logger.error(f"检查产品记录是否存在失败: {e}")
            return False
    
    def exists_by_name(self, name: str) -> bool:
        """
        检查指定名称的产品记录是否存在
        
        Args:
            name: 产品名称
            
        Returns:
            是否存在
        """
        try:
            return self.model.select().where(self.model.name == name).exists()
        except Exception as e:
            logger.error(f"检查产品记录是否存在失败: {e}")
            return False
    
    def get_recent(self, days: int = 7) -> List[Record]:
        """
        获取最近几天的产品记录
        
        Args:
            days: 天数
            
        Returns:
            最近的产品记录列表
        """
        try:
            from datetime import timedelta
            cutoff_date = datetime.now() - timedelta(days=days)
            
            return list(
                self.model.select()
                .where(self.model.update_time >= cutoff_date)
                .order_by(self.model.update_time.desc())
            )
        except Exception as e:
            logger.error(f"获取最近产品记录失败: {e}")
            return []
    
    def batch_update_status(self, record_ids: List[int], status: int) -> int:
        """
        批量更新产品记录状态
        
        Args:
            record_ids: 记录ID列表
            status: 新状态
            
        Returns:
            更新的记录数量
        """
        try:
            query = self.model.update(
                status=status,
                update_time=datetime.now()
            ).where(self.model.id.in_(record_ids))
            
            rows_updated = query.execute()
            logger.info(f"批量更新{rows_updated}条产品记录状态为{status}")
            return rows_updated
        except Exception as e:
            logger.error(f"批量更新产品记录状态失败: {e}")
            return 0
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取产品记录统计信息
        
        Returns:
            统计信息字典
        """
        try:
            total = self.count()
            status_counts = {}
            type_counts = {}
            
            # 统计各状态数量
            for status in [0, 1, 2, 3]:  # 假设状态值为0-3
                status_counts[status] = self.count_by_status(status)
            
            # 统计各类型数量
            for record_type in [0, 1, 2]:  # 假设类型值为0-2
                type_counts[record_type] = len(self.get_by_type(record_type))
            
            return {
                'total': total,
                'status_counts': status_counts,
                'type_counts': type_counts,
                'recent_7_days': len(self.get_recent(7)),
                'recent_30_days': len(self.get_recent(30))
            }
        except Exception as e:
            logger.error(f"获取产品记录统计信息失败: {e}")
            return {
                'total': 0,
                'status_counts': {},
                'type_counts': {},
                'recent_7_days': 0,
                'recent_30_days': 0
            }


# 创建全局实例（可选）
product_repository = ProductRepository()


if __name__ == "__main__":
    # 测试代码
    repo = ProductRepository()
    
    # 测试创建
    test_data = {
        'name': '测试产品',
        'path': '/test/path',
        'content': '测试内容',
        'title': '测试标题'
    }
    
    record = repo.create(test_data)
    if record:
        print(f"创建成功: {record.name}")
        
        # 测试查询
        found = repo.get_by_name('测试产品')
        if found:
            print(f"查询成功: {found.name}")
        
        # 测试更新
        success = repo.update(record.id, {'title': '更新后的标题'})
        if success:
            print("更新成功")
        
        # 测试删除
        success = repo.delete(record.id)
        if success:
            print("删除成功")
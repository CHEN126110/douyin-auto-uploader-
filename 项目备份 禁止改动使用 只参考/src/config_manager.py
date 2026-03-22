#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
⚙️ 智能配置管理系统
提供可靠的数据持久化、状态管理、配置验证、热更新等功能
"""

import json
import os
import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, Callable
from dataclasses import dataclass, asdict, field
from datetime import datetime
from contextlib import contextmanager
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class PricingConfig:
    """价格配置数据类"""
    base_cost_per_unit: float = 8.0          # 单位成本（元/双）
    platform_commission: float = 0.06        # 平台佣金率
    shipping_cost: float = 5.0               # 运费（元）
    packaging_cost: float = 1.0              # 包装费（元）
    target_profit_margin: float = 0.30       # 目标利润率
    min_profit_margin: float = 0.15          # 最低利润率
    max_profit_margin: float = 0.50          # 最高利润率
    
    # 新增配置项
    auto_update_prices: bool = True          # 自动更新价格
    enable_dynamic_pricing: bool = False     # 启用动态价格
    competitor_monitoring: bool = True       # 竞争对手监控
    seasonal_adjustment: bool = True         # 季节性调整
    
    # 高级设置
    price_rounding_strategy: str = "psychology"  # 价格取整策略
    currency: str = "CNY"                   # 货币单位
    tax_rate: float = 0.0                   # 税率
    volume_pricing_enabled: bool = True     # 批量定价启用
    
    def validate(self) -> List[str]:
        """验证配置的有效性"""
        errors = []
        
        if self.base_cost_per_unit <= 0:
            errors.append("单位成本必须大于0")
        
        if not 0 <= self.platform_commission <= 1:
            errors.append("平台佣金率必须在0-1之间")
        
        if self.shipping_cost < 0:
            errors.append("运费不能为负数")
        
        if self.packaging_cost < 0:
            errors.append("包装费不能为负数")
        
        if not 0 < self.target_profit_margin < 1:
            errors.append("目标利润率必须在0-1之间")
        
        if self.min_profit_margin >= self.max_profit_margin:
            errors.append("最低利润率必须小于最高利润率")
        
        return errors

@dataclass 
class SystemConfig:
    """系统配置数据类"""
    language: str = "zh_CN"                 # 界面语言
    theme: str = "auto"                     # 主题模式
    debug_mode: bool = False                # 调试模式
    auto_save_interval: int = 300           # 自动保存间隔(秒)
    backup_retention_days: int = 30         # 备份保留天数
    max_log_size_mb: int = 100             # 最大日志大小(MB)
    
    # 数据库设置
    db_connection_pool_size: int = 5        # 数据库连接池大小
    db_query_timeout: int = 30              # 数据库查询超时(秒)
    
    # 性能设置
    cache_enabled: bool = True              # 启用缓存
    cache_ttl_seconds: int = 3600          # 缓存TTL(秒)
    max_concurrent_calculations: int = 10   # 最大并发计算数
    
    def validate(self) -> List[str]:
        """验证配置的有效性"""
        errors = []
        
        if self.auto_save_interval < 60:
            errors.append("自动保存间隔不能少于60秒")
        
        if self.backup_retention_days < 1:
            errors.append("备份保留天数至少为1天")
        
        if self.max_log_size_mb < 1:
            errors.append("最大日志大小至少为1MB")
        
        return errors

class ConfigStorage:
    """配置存储抽象基类"""
    
    def save(self, key: str, data: Dict[str, Any]) -> bool:
        """保存配置"""
        raise NotImplementedError
    
    def load(self, key: str) -> Optional[Dict[str, Any]]:
        """加载配置"""
        raise NotImplementedError
    
    def delete(self, key: str) -> bool:
        """删除配置"""
        raise NotImplementedError
    
    def list_keys(self) -> List[str]:
        """列出所有配置键"""
        raise NotImplementedError

class JSONFileStorage(ConfigStorage):
    """JSON文件存储实现"""
    
    def __init__(self, storage_dir: str = "config"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)
    
    def save(self, key: str, data: Dict[str, Any]) -> bool:
        """保存配置到JSON文件"""
        try:
            file_path = self.storage_dir / f"{key}.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"配置已保存: {key}")
            return True
        except Exception as e:
            logger.error(f"保存配置失败 {key}: {e}")
            return False
    
    def load(self, key: str) -> Optional[Dict[str, Any]]:
        """从JSON文件加载配置"""
        try:
            file_path = self.storage_dir / f"{key}.json"
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"配置已加载: {key}")
                return data
            return None
        except Exception as e:
            logger.error(f"加载配置失败 {key}: {e}")
            return None
    
    def delete(self, key: str) -> bool:
        """删除配置文件"""
        try:
            file_path = self.storage_dir / f"{key}.json"
            if file_path.exists():
                file_path.unlink()
                logger.info(f"配置已删除: {key}")
                return True
            return False
        except Exception as e:
            logger.error(f"删除配置失败 {key}: {e}")
            return False
    
    def list_keys(self) -> List[str]:
        """列出所有配置键"""
        return [f.stem for f in self.storage_dir.glob("*.json")]

class SQLiteStorage(ConfigStorage):
    """SQLite数据库存储实现"""
    
    def __init__(self, db_path: str = "config/app_config.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self._init_database()
        self._lock = threading.Lock()
    
    def _init_database(self):
        """初始化数据库"""
        with self._get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS app_configs (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS config_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL,
                    data TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path, timeout=30)
        try:
            yield conn
        finally:
            conn.close()
    
    def save(self, key: str, data: Dict[str, Any]) -> bool:
        """保存配置到数据库"""
        try:
            with self._lock:
                json_data = json.dumps(data, ensure_ascii=False)
                with self._get_connection() as conn:
                    conn.execute('''
                        INSERT OR REPLACE INTO app_configs (key, data, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                    ''', (key, json_data))
                    
                    # 记录历史
                    conn.execute('''
                        INSERT INTO config_history (key, data, operation)
                        VALUES (?, ?, 'UPDATE')
                    ''', (key, json_data))
                    
                    conn.commit()
                logger.info(f"配置已保存到数据库: {key}")
                return True
        except Exception as e:
            logger.error(f"保存配置到数据库失败 {key}: {e}")
            return False
    
    def load(self, key: str) -> Optional[Dict[str, Any]]:
        """从数据库加载配置"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    'SELECT data FROM app_configs WHERE key = ?', (key,)
                )
                row = cursor.fetchone()
                if row:
                    data = json.loads(row[0])
                    logger.info(f"配置已从数据库加载: {key}")
                    return data
                return None
        except Exception as e:
            logger.error(f"从数据库加载配置失败 {key}: {e}")
            return None
    
    def delete(self, key: str) -> bool:
        """从数据库删除配置"""
        try:
            with self._lock:
                with self._get_connection() as conn:
                    # 记录删除历史
                    cursor = conn.execute(
                        'SELECT data FROM app_configs WHERE key = ?', (key,)
                    )
                    row = cursor.fetchone()
                    if row:
                        conn.execute('''
                            INSERT INTO config_history (key, data, operation)
                            VALUES (?, ?, 'DELETE')
                        ''', (key, row[0]))
                    
                    # 删除配置
                    conn.execute('DELETE FROM app_configs WHERE key = ?', (key,))
                    conn.commit()
                    
                logger.info(f"配置已从数据库删除: {key}")
                return True
        except Exception as e:
            logger.error(f"从数据库删除配置失败 {key}: {e}")
            return False
    
    def list_keys(self) -> List[str]:
        """列出数据库中所有配置键"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute('SELECT key FROM app_configs')
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"列出配置键失败: {e}")
            return []

class ConfigManager:
    """配置管理器"""
    
    def __init__(self, storage_backend: str = "sqlite"):
        """
        初始化配置管理器
        
        Args:
            storage_backend: 存储后端 ("json" 或 "sqlite")
        """
        if storage_backend == "sqlite":
            self.storage = SQLiteStorage()
        else:
            self.storage = JSONFileStorage()
        
        self._pricing_config: Optional[PricingConfig] = None
        self._system_config: Optional[SystemConfig] = None
        self._config_cache: Dict[str, Any] = {}
        self._change_listeners: Dict[str, List[Callable]] = {}
        self._lock = threading.Lock()
        
        # 加载配置
        self._load_all_configs()
    
    def _load_all_configs(self):
        """加载所有配置"""
        try:
            # 加载价格配置
            pricing_data = self.storage.load("pricing_config")
            if pricing_data:
                self._pricing_config = PricingConfig(**pricing_data)
            else:
                self._pricing_config = PricingConfig()
                self.save_pricing_config(self._pricing_config)
            
            # 加载系统配置
            system_data = self.storage.load("system_config")
            if system_data:
                self._system_config = SystemConfig(**system_data)
            else:
                self._system_config = SystemConfig()
                self.save_system_config(self._system_config)
                
            logger.info("所有配置加载完成")
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
    
    def get_pricing_config(self) -> PricingConfig:
        """获取价格配置"""
        if self._pricing_config is None:
            self._pricing_config = PricingConfig()
        return self._pricing_config
    
    def save_pricing_config(self, config: PricingConfig) -> bool:
        """保存价格配置"""
        # 验证配置
        errors = config.validate()
        if errors:
            logger.error(f"价格配置验证失败: {errors}")
            return False
        
        success = self.storage.save("pricing_config", asdict(config))
        if success:
            with self._lock:
                old_config = self._pricing_config
                self._pricing_config = config
                self._notify_listeners("pricing_config", old_config, config)
        
        return success
    
    def get_system_config(self) -> SystemConfig:
        """获取系统配置"""
        if self._system_config is None:
            self._system_config = SystemConfig()
        return self._system_config
    
    def save_system_config(self, config: SystemConfig) -> bool:
        """保存系统配置"""
        # 验证配置
        errors = config.validate()
        if errors:
            logger.error(f"系统配置验证失败: {errors}")
            return False
        
        success = self.storage.save("system_config", asdict(config))
        if success:
            with self._lock:
                old_config = self._system_config
                self._system_config = config
                self._notify_listeners("system_config", old_config, config)
        
        return success
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """获取自定义配置"""
        if key in self._config_cache:
            return self._config_cache[key]
        
        data = self.storage.load(key)
        if data is not None:
            self._config_cache[key] = data
            return data
        
        return default
    
    def set_config(self, key: str, value: Any) -> bool:
        """设置自定义配置"""
        success = self.storage.save(key, {"value": value, "timestamp": datetime.now().isoformat()})
        if success:
            with self._lock:
                old_value = self._config_cache.get(key)
                self._config_cache[key] = value
                self._notify_listeners(key, old_value, value)
        
        return success
    
    def add_change_listener(self, config_key: str, listener: Callable[[Any, Any], None]):
        """添加配置变更监听器"""
        if config_key not in self._change_listeners:
            self._change_listeners[config_key] = []
        self._change_listeners[config_key].append(listener)
    
    def remove_change_listener(self, config_key: str, listener: Callable):
        """移除配置变更监听器"""
        if config_key in self._change_listeners:
            try:
                self._change_listeners[config_key].remove(listener)
            except ValueError:
                pass
    
    def _notify_listeners(self, config_key: str, old_value: Any, new_value: Any):
        """通知配置变更监听器"""
        if config_key in self._change_listeners:
            for listener in self._change_listeners[config_key]:
                try:
                    listener(old_value, new_value)
                except Exception as e:
                    logger.error(f"配置变更监听器执行失败: {e}")
    
    def export_config(self, output_path: str) -> bool:
        """导出所有配置"""
        try:
            export_data = {
                "pricing_config": asdict(self.get_pricing_config()),
                "system_config": asdict(self.get_system_config()),
                "custom_configs": {},
                "export_timestamp": datetime.now().isoformat(),
                "version": "1.0"
            }
            
            # 导出自定义配置
            for key in self.storage.list_keys():
                if key not in ["pricing_config", "system_config"]:
                    data = self.storage.load(key)
                    if data:
                        export_data["custom_configs"][key] = data
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"配置已导出到: {output_path}")
            return True
        except Exception as e:
            logger.error(f"导出配置失败: {e}")
            return False
    
    def import_config(self, input_path: str, merge: bool = True) -> bool:
        """导入配置"""
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                import_data = json.load(f)
            
            success_count = 0
            
            # 导入价格配置
            if "pricing_config" in import_data:
                try:
                    config = PricingConfig(**import_data["pricing_config"])
                    if self.save_pricing_config(config):
                        success_count += 1
                except Exception as e:
                    logger.error(f"导入价格配置失败: {e}")
            
            # 导入系统配置
            if "system_config" in import_data:
                try:
                    config = SystemConfig(**import_data["system_config"])
                    if self.save_system_config(config):
                        success_count += 1
                except Exception as e:
                    logger.error(f"导入系统配置失败: {e}")
            
            # 导入自定义配置
            if "custom_configs" in import_data:
                for key, data in import_data["custom_configs"].items():
                    try:
                        if self.storage.save(key, data):
                            success_count += 1
                    except Exception as e:
                        logger.error(f"导入自定义配置 {key} 失败: {e}")
            
            logger.info(f"配置导入完成，成功导入 {success_count} 项")
            return success_count > 0
        except Exception as e:
            logger.error(f"导入配置失败: {e}")
            return False
    
    def backup_config(self, backup_dir: str = "backups") -> str:
        """备份配置"""
        backup_path = Path(backup_dir)
        backup_path.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_path / f"config_backup_{timestamp}.json"
        
        if self.export_config(str(backup_file)):
            logger.info(f"配置备份成功: {backup_file}")
            return str(backup_file)
        else:
            logger.error("配置备份失败")
            return ""
    
    def restore_config(self, backup_file: str) -> bool:
        """恢复配置"""
        return self.import_config(backup_file, merge=False)
    
    def reset_to_defaults(self) -> bool:
        """重置为默认配置"""
        try:
            # 重置价格配置
            default_pricing = PricingConfig()
            pricing_success = self.save_pricing_config(default_pricing)
            
            # 重置系统配置
            default_system = SystemConfig()
            system_success = self.save_system_config(default_system)
            
            if pricing_success and system_success:
                logger.info("配置已重置为默认值")
                return True
            else:
                logger.error("重置配置失败")
                return False
        except Exception as e:
            logger.error(f"重置配置失败: {e}")
            return False
    
    def cleanup_old_backups(self, backup_dir: str = "backups", retention_days: int = 30):
        """清理旧备份文件"""
        try:
            backup_path = Path(backup_dir)
            if not backup_path.exists():
                return
            
            cutoff_time = datetime.now().timestamp() - (retention_days * 24 * 3600)
            
            for backup_file in backup_path.glob("config_backup_*.json"):
                if backup_file.stat().st_mtime < cutoff_time:
                    backup_file.unlink()
                    logger.info(f"已删除过期备份: {backup_file}")
        except Exception as e:
            logger.error(f"清理备份失败: {e}")

def main():
    """演示配置管理功能"""
    print("⚙️ 配置管理系统演示")
    print("=" * 50)
    
    # 创建配置管理器
    config_manager = ConfigManager(storage_backend="sqlite")
    
    # 获取当前配置
    pricing_config = config_manager.get_pricing_config()
    system_config = config_manager.get_system_config()
    
    print("📊 当前价格配置:")
    print(f"  单位成本: {pricing_config.base_cost_per_unit}元/双")
    print(f"  目标利润率: {pricing_config.target_profit_margin:.1%}")
    print(f"  平台佣金: {pricing_config.platform_commission:.1%}")
    
    print("\n🔧 当前系统配置:")
    print(f"  语言: {system_config.language}")
    print(f"  主题: {system_config.theme}")
    print(f"  调试模式: {system_config.debug_mode}")
    
    # 演示配置变更
    print("\n🔄 测试配置变更...")
    
    # 添加变更监听器
    def on_pricing_change(old_config, new_config):
        print(f"💡 价格配置已更新: 目标利润率 {old_config.target_profit_margin:.1%} → {new_config.target_profit_margin:.1%}")
    
    config_manager.add_change_listener("pricing_config", on_pricing_change)
    
    # 修改配置
    pricing_config.target_profit_margin = 0.35
    success = config_manager.save_pricing_config(pricing_config)
    print(f"配置保存: {'✅ 成功' if success else '❌ 失败'}")
    
    # 演示备份和导出
    print("\n💾 测试备份和导出...")
    backup_file = config_manager.backup_config()
    if backup_file:
        print(f"✅ 备份创建成功: {backup_file}")
    
    export_success = config_manager.export_config("config_export.json")
    print(f"导出配置: {'✅ 成功' if export_success else '❌ 失败'}")
    
    print("\n✅ 配置管理系统演示完成！")

if __name__ == "__main__":
    main()
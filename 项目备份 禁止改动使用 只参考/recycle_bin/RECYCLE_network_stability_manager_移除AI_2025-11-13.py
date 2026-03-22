# -*- coding: utf-8 -*-
# [网络] 网络稳定性管理器 (Python 3.9兼容版)
# 提供重试机制、多通道备用方案,确保AI服务稳定可用

import requests
import time
import logging
import asyncio
import threading
import random
import sys
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json
import hashlib
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

# Python 3.9 兼容性处理
if sys.version_info >= (3, 11):
    from asyncio import timeout as asyncio_timeout
else:
    # Python 3.9 兼容方案
    import asyncio
    from contextlib import asynccontextmanager
    
    @asynccontextmanager
    async def asyncio_timeout(delay):
        """Python 3.9 兼容的超时上下文管理器"""
        task = asyncio.current_task()
        handle = asyncio.get_event_loop().call_later(
            delay, lambda: task.cancel() if task and not task.done() else None
        )
        try:
            yield
        finally:
            handle.cancel()

class NetworkStatus(Enum):
    """网络状态枚举"""
    UNKNOWN = "unknown"
    EXCELLENT = "excellent"
    GOOD = "good"
    POOR = "poor"
    FAILED = "failed"

@dataclass
class NetworkMetrics:
    """网络指标"""
    latency: float = 0.0  # 延迟(ms)
    success_rate: float = 0.0  # 成功率
    avg_response_time: float = 0.0  # 平均响应时间
    error_count: int = 0  # 错误次数
    last_success: Optional[datetime] = None
    last_error: Optional[str] = None

@dataclass
class EndpointConfig:
    """端点配置"""
    name: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    timeout: float = 15.0
    max_retries: int = 3
    weight: float = 1.0  # 权重
    enabled: bool = True
    metrics: NetworkMetrics = field(default_factory=NetworkMetrics)

class CircuitBreaker:
    """熔断器"""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    def call(self, func: Callable, *args, **kwargs):
        """执行调用并管理熔断状态"""
        if self.state == "OPEN":
            if self._should_attempt_reset():
                self.state = "HALF_OPEN"
            else:
                raise Exception("Circuit breaker is OPEN")
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _should_attempt_reset(self) -> bool:
        """是否应该尝试重置"""
        if self.last_failure_time is None:
            return True
        return time.time() - self.last_failure_time >= self.recovery_timeout
    
    def _on_success(self):
        """成功回调"""
        self.failure_count = 0
        self.state = "CLOSED"
    
    def _on_failure(self):
        """失败回调"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"

class RequestCache:
    """请求缓存"""
    
    def __init__(self, default_ttl: float = 300.0):  # 5分钟缓存
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.default_ttl = default_ttl
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if key in self.cache:
            entry = self.cache[key]
            if time.time() - entry["timestamp"] < entry["ttl"]:
                return entry["data"]
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, data: Any, ttl: Optional[float] = None):
        """设置缓存"""
        self.cache[key] = {
            "data": data,
            "timestamp": time.time(),
            "ttl": ttl or self.default_ttl
        }
    
    def clear(self):
        """清空缓存"""
        self.cache.clear()
    
    def size(self) -> int:
        """缓存大小"""
        # 清理过期缓存
        current_time = time.time()
        expired_keys = [
            key for key, entry in self.cache.items()
            if current_time - entry["timestamp"] >= entry["ttl"]
        ]
        for key in expired_keys:
            del self.cache[key]
        
        return len(self.cache)

class NetworkStabilityManager:
    """网络稳定性管理器"""
    
    def __init__(self):
        self.endpoints: Dict[str, EndpointConfig] = {}
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.cache = RequestCache()
        self.session = self._create_session()
        
        # 初始化端点配置
        self._init_endpoints()
    
    def _create_session(self) -> requests.Session:
        """创建会话"""
        session = requests.Session()
        
        # 配置重试策略
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def _init_endpoints(self):
        """初始化端点配置"""
        # DeepSeek主端点
        self.add_endpoint(
            name="deepseek_primary",
            url="https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": "Bearer sk-02cedf2a45444a529c94df9f7e84f029",
                "Content-Type": "application/json"
            },
            timeout=30.0,  # [修复] 增加超时时间到30秒,适应AI复杂请求
            weight=1.0
        )
        
        # 备用端点配置(使用相同的有效密钥)
        self.add_endpoint(
            name="deepseek_backup1",
            url="https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": "Bearer sk-02cedf2a45444a529c94df9f7e84f029",
                "Content-Type": "application/json"
            },
            timeout=30.0,  # [修复] 统一30秒超时
            weight=0.8
        )
        
        # 本地缓存服务(禁用,因为通常不可用)
        self.add_endpoint(
            name="local_cache",
            url="http://localhost:8080/ai/chat",
            headers={"Content-Type": "application/json"},
            timeout=10.0,  # 本地服务保持较短超时
            weight=0.5,
            enabled=False  # 默认禁用本地缓存服务
        )
    
    def add_endpoint(self, name: str, url: str, headers: Optional[Dict[str, str]] = None,
                    timeout: float = 15.0, max_retries: int = 3, weight: float = 1.0, enabled: bool = True):
        """添加端点"""
        self.endpoints[name] = EndpointConfig(
            name=name,
            url=url,
            headers=headers or {},
            timeout=timeout,
            max_retries=max_retries,
            weight=weight,
            enabled=enabled
        )
        self.circuit_breakers[name] = CircuitBreaker()
    
    def _generate_cache_key(self, prompt: str, **kwargs) -> str:
        """生成缓存键"""
        content = f"{prompt}_{json.dumps(kwargs, sort_keys=True)}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _calculate_network_status(self) -> NetworkStatus:
        """计算整体网络状态"""
        active_endpoints = [ep for ep in self.endpoints.values() if ep.enabled]
        
        if not active_endpoints:
            return NetworkStatus.FAILED
        
        avg_success_rate = sum(ep.metrics.success_rate for ep in active_endpoints) / len(active_endpoints)
        avg_response_time = sum(ep.metrics.avg_response_time for ep in active_endpoints) / len(active_endpoints)
        
        if avg_success_rate >= 0.95 and avg_response_time < 2000:
            return NetworkStatus.EXCELLENT
        elif avg_success_rate >= 0.8 and avg_response_time < 5000:
            return NetworkStatus.GOOD
        elif avg_success_rate >= 0.5:
            return NetworkStatus.POOR
        else:
            return NetworkStatus.FAILED
    
    def make_stable_request(self, prompt: str, **kwargs) -> Optional[Dict[str, Any]]:
        """发起稳定的请求 (同步版本)"""
        # 检查缓存
        cache_key = self._generate_cache_key(prompt, **kwargs)
        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.info("[测试] 返回缓存结果")
            return cached_result
        
        # 按权重排序端点
        sorted_endpoints = sorted(
            [ep for ep in self.endpoints.values() if ep.enabled],
            key=lambda x: x.weight,
            reverse=True
        )
        
        for endpoint in sorted_endpoints:
            try:
                logger.info(f"[处理] 尝试端点: {endpoint.name}")
                
                # 检查熔断器
                circuit_breaker = self.circuit_breakers[endpoint.name]
                if circuit_breaker.state == "OPEN":
                    logger.warning(f"[警告] 端点 {endpoint.name} 熔断中,跳过")
                    continue
                
                result = self._make_request(endpoint, prompt, **kwargs)
                
                if result:
                    # 更新成功指标
                    endpoint.metrics.last_success = datetime.now()
                    endpoint.metrics.success_rate = min(1.0, endpoint.metrics.success_rate + 0.1)
                    
                    # 缓存结果
                    self.cache.set(cache_key, result)
                    
                    logger.info(f"[成功] 端点 {endpoint.name} 请求成功")
                    return result
                    
            except Exception as e:
                logger.error(f"端点 {endpoint.name} 请求异常: {e}")
                endpoint.metrics.error_count += 1
                endpoint.metrics.last_error = str(e)
                endpoint.metrics.success_rate = max(0.0, endpoint.metrics.success_rate - 0.2)
                logger.warning(f"[警告] 端点 {endpoint.name} 请求失败: {e}")
                continue
        
        logger.error("[失败] 所有端点都失败了")
        return None
    
    def _make_request(self, endpoint: EndpointConfig, prompt: str, **kwargs) -> Optional[Dict[str, Any]]:
        """发起具体请求"""
        start_time = time.time()
        
        try:
            # 构建请求数据
            request_data = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 2000,
                "temperature": 0.7
            }
            request_data.update(kwargs)
            
            # 发起请求
            response = self.session.post(
                endpoint.url,
                json=request_data,
                headers=endpoint.headers,
                timeout=endpoint.timeout
            )
            
            response_time = (time.time() - start_time) * 1000
            endpoint.metrics.avg_response_time = response_time
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"端点响应错误: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error(f"端点 {endpoint.name} 请求超时")
            return None
        except Exception as e:
            logger.error(f"端点 {endpoint.name} 请求异常: {e}")
            return None
    
    def get_network_status_info(self) -> Dict[str, Any]:
        """获取网络状态信息"""
        return {
            "network_status": self._calculate_network_status().value,
            "cache_size": self.cache.size(),
            "endpoints": {
                name: {
                    "enabled": ep.enabled,
                    "success_rate": ep.metrics.success_rate,
                    "avg_response_time": ep.metrics.avg_response_time,
                    "error_count": ep.metrics.error_count,
                    "circuit_breaker_state": self.circuit_breakers[name].state
                }
                for name, ep in self.endpoints.items()
            }
        }

# 全局实例
_network_manager = None

def get_network_manager() -> NetworkStabilityManager:
    """获取网络管理器实例"""
    global _network_manager
    if _network_manager is None:
        _network_manager = NetworkStabilityManager()
    return _network_manager

def stable_ai_request(prompt: str, **kwargs) -> Optional[Dict[str, Any]]:
    """稳定的AI请求接口"""
    manager = get_network_manager()
    return manager.make_stable_request(prompt, **kwargs)

def get_network_status_info() -> Dict[str, Any]:
    """获取网络状态信息"""
    manager = get_network_manager()
    return manager.get_network_status_info() 

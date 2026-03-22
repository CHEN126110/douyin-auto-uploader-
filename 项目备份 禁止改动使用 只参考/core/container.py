#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
依赖注入容器 - 管理服务的注册、解析和生命周期
实现单例模式、工厂模式和依赖注入
"""

from typing import Dict, Type, Any, Callable, Optional, TypeVar, Generic
import threading
import inspect
from functools import wraps

T = TypeVar('T')


class ServiceContainer:
    """
    依赖注入容器
    支持单例模式、工厂模式和依赖注入
    """
    
    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._singletons: Dict[str, Any] = {}
        self._factories: Dict[str, Callable] = {}
        self._lock = threading.Lock()
    
    def register_singleton(self, interface: Type[T], implementation: Type[T]) -> None:
        """
        注册单例服务
        
        Args:
            interface: 服务接口类型
            implementation: 服务实现类型
        """
        service_name = interface.__name__
        with self._lock:
            self._services[service_name] = {
                'type': 'singleton',
                'interface': interface,
                'implementation': implementation,
                'instance': None
            }
    
    def register_transient(self, interface: Type[T], implementation: Type[T]) -> None:
        """
        注册瞬态服务（每次调用都创建新实例）
        
        Args:
            interface: 服务接口类型
            implementation: 服务实现类型
        """
        service_name = interface.__name__
        with self._lock:
            self._services[service_name] = {
                'type': 'transient',
                'interface': interface,
                'implementation': implementation
            }
    
    def register_factory(self, interface: Type[T], factory: Callable[[], T]) -> None:
        """
        注册工厂方法
        
        Args:
            interface: 服务接口类型
            factory: 工厂方法
        """
        service_name = interface.__name__
        with self._lock:
            self._factories[service_name] = factory
    
    def register_instance(self, interface: Type[T], instance: T) -> None:
        """
        注册已存在的实例
        
        Args:
            interface: 服务接口类型
            instance: 服务实例
        """
        service_name = interface.__name__
        with self._lock:
            self._singletons[service_name] = instance
    
    def resolve(self, interface: Type[T]) -> T:
        """
        解析服务实例
        
        Args:
            interface: 服务接口类型
            
        Returns:
            服务实例
            
        Raises:
            ValueError: 服务未注册
        """
        service_name = interface.__name__
        
        # 检查是否有已注册的实例
        if service_name in self._singletons:
            return self._singletons[service_name]
        
        # 检查是否有工厂方法
        if service_name in self._factories:
            return self._factories[service_name]()
        
        # 检查是否有注册的服务
        if service_name not in self._services:
            raise ValueError(f"Service '{service_name}' is not registered")
        
        service_config = self._services[service_name]
        
        if service_config['type'] == 'singleton':
            return self._get_singleton(service_config)
        elif service_config['type'] == 'transient':
            return self._create_instance(service_config['implementation'])
        else:
            raise ValueError(f"Unknown service type: {service_config['type']}")
    
    def _get_singleton(self, service_config: Dict[str, Any]) -> Any:
        """获取单例实例"""
        if service_config['instance'] is None:
            with self._lock:
                if service_config['instance'] is None:
                    service_config['instance'] = self._create_instance(
                        service_config['implementation']
                    )
        return service_config['instance']
    
    def _create_instance(self, implementation: Type[T]) -> T:
        """
        创建服务实例，自动注入依赖
        
        Args:
            implementation: 实现类型
            
        Returns:
            服务实例
        """
        # 获取构造函数签名
        signature = inspect.signature(implementation.__init__)
        parameters = signature.parameters
        
        # 准备构造函数参数
        kwargs = {}
        for param_name, param in parameters.items():
            if param_name == 'self':
                continue
            
            # 尝试解析依赖
            if param.annotation != inspect.Parameter.empty:
                try:
                    dependency = self.resolve(param.annotation)
                    kwargs[param_name] = dependency
                except ValueError:
                    # 如果依赖无法解析且没有默认值，抛出异常
                    if param.default == inspect.Parameter.empty:
                        raise ValueError(
                            f"Cannot resolve dependency '{param.annotation.__name__}' "
                            f"for parameter '{param_name}' in '{implementation.__name__}'"
                        )
        
        return implementation(**kwargs)
    
    def is_registered(self, interface: Type[T]) -> bool:
        """
        检查服务是否已注册
        
        Args:
            interface: 服务接口类型
            
        Returns:
            是否已注册
        """
        service_name = interface.__name__
        return (service_name in self._services or 
                service_name in self._singletons or 
                service_name in self._factories)
    
    def clear(self) -> None:
        """清空所有注册的服务"""
        with self._lock:
            self._services.clear()
            self._singletons.clear()
            self._factories.clear()


# 全局容器实例
container = ServiceContainer()


def inject(interface: Type[T]) -> T:
    """
    依赖注入装饰器
    
    Args:
        interface: 服务接口类型
        
    Returns:
        服务实例
    """
    return container.resolve(interface)


def injectable(cls: Type[T]) -> Type[T]:
    """
    标记类为可注入的装饰器
    
    Args:
        cls: 要标记的类
        
    Returns:
        原始类
    """
    # 为类添加元数据
    cls._injectable = True
    return cls


def autowired(func: Callable) -> Callable:
    """
    自动装配装饰器，自动注入函数参数
    
    Args:
        func: 要装配的函数
        
    Returns:
        装配后的函数
    """
    signature = inspect.signature(func)
    
    @wraps(func)
    def wrapper(*args, **kwargs):
        # 获取函数参数
        bound_args = signature.bind_partial(*args, **kwargs)
        
        # 自动注入缺失的参数
        for param_name, param in signature.parameters.items():
            if param_name not in bound_args.arguments:
                if param.annotation != inspect.Parameter.empty:
                    try:
                        dependency = container.resolve(param.annotation)
                        bound_args.arguments[param_name] = dependency
                    except ValueError:
                        # 如果无法解析且没有默认值，跳过
                        if param.default == inspect.Parameter.empty:
                            continue
        
        return func(*bound_args.args, **bound_args.kwargs)
    
    return wrapper


# 配置容器的便捷函数
def configure_container():
    """配置依赖注入容器"""
    # 这里可以注册所有的服务
    # 在应用启动时调用此函数
    pass


if __name__ == "__main__":
    # 测试代码
    class IRepository:
        def get_data(self):
            pass
    
    class Repository(IRepository):
        def get_data(self):
            return "data from repository"
    
    class IService:
        def process(self):
            pass
    
    @injectable
    class Service(IService):
        def __init__(self, repository: IRepository):
            self.repository = repository
        
        def process(self):
            return f"processed: {self.repository.get_data()}"
    
    # 注册服务
    container.register_singleton(IRepository, Repository)
    container.register_singleton(IService, Service)
    
    # 解析服务
    service = container.resolve(IService)
    print(service.process())  # 输出: processed: data from repository
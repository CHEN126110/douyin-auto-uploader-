# -*- coding: utf-8 -*-

import threading
import time as _time
from typing import Callable, Tuple, Any
import logging


class Thread:
    """改进的线程管理类 - 使用安全的线程终止机制"""
    
    def __init__(self, run: Callable[..., Any], args: Tuple[Any, ...] = ()) -> None:
        self._stop_event = threading.Event()
        self._target_func = run
        self._args = args
        
        # 包装目标函数，添加停止检查
        def wrapped_target():
            try:
                # 如果目标函数支持stop_event参数，传递给它
                import inspect
                sig = inspect.signature(self._target_func)
                if 'stop_event' in sig.parameters:
                    self._target_func(*self._args, stop_event=self._stop_event)
                else:
                    self._target_func(*self._args)
            except Exception as e:
                logging.error(f"线程执行异常: {e}")
        
        self.factory = threading.Thread(target=wrapped_target, daemon=True)

    def is_alive(self) -> bool:
        return self.factory.is_alive()

    def start(self) -> None:
        self.factory.start()

    def stop(self, timeout: float = 5.0) -> bool:
        """安全停止线程
        
        Args:
            timeout: 等待线程停止的超时时间（秒）
            
        Returns:
            bool: 是否成功停止线程
        """
        if not self.is_alive():
            return True
            
        # 设置停止事件
        self._stop_event.set()
        
        # 等待线程自然结束
        self.factory.join(timeout=timeout)
        
        if self.is_alive():
            logging.warning(f"线程在 {timeout} 秒后仍未停止")
            return False
        else:
            logging.info("线程已安全停止")
            return True

    def kill(self) -> None:
        """保持向后兼容性的kill方法，实际调用安全的stop方法"""
        logging.warning("使用了已弃用的kill方法，建议使用stop方法")
        self.stop()

    @property
    def stop_event(self) -> threading.Event:
        """获取停止事件，供目标函数检查"""
        return self._stop_event

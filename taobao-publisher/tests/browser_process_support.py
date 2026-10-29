"""隔离浏览器进程启动同步辅助；不连接平台，也不处理业务页面。"""
import time


def wait_for_devtools_port(process, active_port_file, timeout=20.0):
    """等到端口文件可读取且端口有效；Windows 创建文件时的短暂占用不等于启动失败。"""
    deadline = time.monotonic() + max(0.1, float(timeout))
    while True:
        if process.poll() is not None:
            raise RuntimeError('隔离测试浏览器启动失败')
        try:
            lines = active_port_file.read_text(encoding='utf-8').splitlines()
            port = int(lines[0].strip()) if lines else 0
            if 1 <= port <= 65535:
                return port
        except (OSError, ValueError, IndexError):
            # 文件可能已创建但仍被浏览器占用，或首行尚未写完；继续受时限约束的等待。
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError('隔离测试浏览器启动失败')
        time.sleep(0.1)

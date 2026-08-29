# -*- coding: utf-8 -*-
"""Chrome 调试实例启动器。

合规说明：仅在用户本机启动用户自己的真实 Chrome（带远程调试端口），供用户手动登录后
由本工具 attach 接管。不做无头伪装、不注入任何反检测参数。

为 Agent 设计：Agent 在调用业务接口前可先调用 ensure_browser 确保浏览器就绪，
再根据登录态决定是否提示用户登录。
"""
from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from typing import Optional

from .errors import BusinessApiError, ErrorCode

DEFAULT_PORT = 9222
DEFAULT_LOGIN_URL = "https://fxg.jinritemai.com/"

_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def find_chrome() -> Optional[str]:
    """定位本机 Chrome：环境变量 > 标准路径 > 注册表 App Paths。"""
    env_path = os.environ.get("DOUYIN_CHROME_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path
    for path in _CHROME_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    try:
        import winreg  # 仅 Windows

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(
                    hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
                ) as key:
                    val, _ = winreg.QueryValueEx(key, None)
                    if val and os.path.isfile(val):
                        return val
            except OSError:
                continue
    except Exception:
        pass
    return None


def debug_endpoint_alive(address: str, timeout: float = 1.5) -> bool:
    """检测调试端口是否可连接（CDP 的 /json/version 探针）。"""
    try:
        with urllib.request.urlopen(f"http://{address}/json/version", timeout=timeout) as resp:
            return getattr(resp, "status", 200) == 200
    except Exception:
        return False


def default_user_data_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".douyin_business_api_chrome")


def launch_debug_chrome(
    port: int = DEFAULT_PORT,
    user_data_dir: Optional[str] = None,
    url: Optional[str] = DEFAULT_LOGIN_URL,
    chrome_path: Optional[str] = None,
    wait_ready: float = 12.0,
) -> dict:
    """启动一个带远程调试端口的独立 Chrome 实例。若端口已就绪则直接复用。"""
    address = f"127.0.0.1:{port}"
    if debug_endpoint_alive(address):
        return {"address": address, "already_running": True, "pid": None, "url": url}

    exe = chrome_path or find_chrome()
    if not exe:
        raise BusinessApiError(
            ErrorCode.BROWSER_NOT_READY,
            "未找到 Chrome 可执行文件。",
            hint="请安装 Chrome，或用环境变量 DOUYIN_CHROME_PATH 指定 chrome.exe 路径。",
        )

    user_data_dir = user_data_dir or default_user_data_dir()
    os.makedirs(user_data_dir, exist_ok=True)

    args = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if url:
        args.append(url)

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except Exception as exc:
        raise BusinessApiError(
            ErrorCode.BROWSER_NOT_READY,
            f"启动 Chrome 失败：{exc}",
            hint="请确认 Chrome 路径正确、未被安全软件拦截。",
            context={"chrome_path": exe},
        ) from exc

    deadline = time.time() + max(2.0, wait_ready)
    while time.time() < deadline:
        if debug_endpoint_alive(address):
            return {
                "address": address,
                "already_running": False,
                "pid": proc.pid,
                "user_data_dir": user_data_dir,
                "url": url,
            }
        time.sleep(0.4)

    raise BusinessApiError(
        ErrorCode.BROWSER_NOT_READY,
        f"已启动 Chrome 但调试端口 {port} 在 {wait_ready:.0f}s 内未就绪。",
        hint="可能端口被占用或被防火墙拦截；换一个端口（BUSINESS_API/DOUYIN_CHROME 端口）后重试。",
        context={"address": address, "pid": proc.pid},
    )


def ensure_browser(
    port: int = DEFAULT_PORT,
    user_data_dir: Optional[str] = None,
    url: Optional[str] = DEFAULT_LOGIN_URL,
) -> dict:
    """确保调试浏览器就绪：已就绪则复用，否则启动。供 Agent 调用。"""
    address = f"127.0.0.1:{port}"
    if debug_endpoint_alive(address):
        return {"address": address, "already_running": True}
    return launch_debug_chrome(port=port, user_data_dir=user_data_dir, url=url)

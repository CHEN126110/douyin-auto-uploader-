# -*- coding: utf-8 -*-
"""抖店/电商业务域 DOM 自动化 API（合规 RPA 方案）。

本包通过 DrissionPage 接管用户本机已登录的真实 Chrome，在真实页面上执行
真人式的 DOM 操作，对外暴露统一的 HTTP 业务接口。

合规边界（务必遵守）：
- 只接管用户自己的、已登录的真实浏览器，操作用户自己的店铺数据。
- 不复现平台私有签名（a_bogus / X-Bogus / msToken 等），不拼裸协议请求。
- 不绕过验证码与风控：命中即暂停并交人工处理。
- 通过 HumanPacer 控频，按真人节奏操作，避免高频自动化对抗平台限流。
"""

def _ensure_werkzeug_version() -> None:
    """环境兼容垫片：flask 2.3.2 的 test_client 读取 werkzeug.__version__，而较新 werkzeug
    已移除该属性。/mcp/call 内部用 test_client 转发，故在包初始化补齐，保证生产运行（非仅测试）
    也健壮。根治建议见 README：将 flask 与 werkzeug 对齐到兼容版本。
    """
    try:
        import werkzeug

        if not hasattr(werkzeug, "__version__"):
            try:
                from importlib.metadata import version

                werkzeug.__version__ = version("werkzeug")
            except Exception:
                werkzeug.__version__ = "0.0.0"
    except Exception:
        pass


_ensure_werkzeug_version()

__version__ = "0.1.0"

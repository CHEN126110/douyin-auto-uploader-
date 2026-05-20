# -*- coding: utf-8 -*-
"""FXG 协议流水线 — 结构化错误处理体系。
提供统一的错误分类、中文描述、修复建议，用于调试和维护。
"""

from enum import Enum


# ============================================================
# 错误类别
# ============================================================

class ErrorCategory(Enum):
    CDP = "cdp"               # Chrome DevTools Protocol 连接/通信错误
    NETWORK = "network"       # HTTP 网络请求错误
    AUTH = "auth"             # 认证/Token 错误
    VALIDATION = "validation" # 数据验证错误 (图片比例/SKU/价格等)
    PLATFORM = "platform"     # 平台 API 返回的业务错误
    INPUT = "input"           # 用户输入错误 (文件不存在/参数缺失)
    SCHEMA = "schema"         # 类目 Schema 相关错误
    UNKNOWN = "unknown"       # 未分类错误


# ============================================================
# 错误码定义 {code: (category, message_template, fix_hint)}
# ============================================================

ERROR_DEFS = {
    # —— CDP 层 ——
    "ERR_CDP_NO_BROWSER": (ErrorCategory.CDP,
        "无法连接到Chrome调试端口 (端口: {port})",
        "请使用 --remote-debugging-port={port} 启动Chrome，并确保已登录fxg.jinritemai.com"),
    "ERR_CDP_NO_PAGE": (ErrorCategory.CDP,
        "未找到jinritemai.com的浏览器标签页",
        "请在Chrome中打开 https://fxg.jinritemai.com 任意页面后重试"),
    "ERR_CDP_WEBPACK_CHUNK": (ErrorCategory.CDP,
        "未找到webpack chunk (@ecom-mcenter/ffa-goods)，页面可能未完全加载",
        "请刷新页面或导航到 https://fxg.jinritemai.com/ffa/g/create"),
    "ERR_CDP_WEBSOCKET": (ErrorCategory.CDP,
        "CDP WebSocket通信失败: {detail}",
        "Chrome调试连接中断，请检查Chrome是否正常运行"),
    "ERR_CDP_TIMEOUT": (ErrorCategory.CDP,
        "CDP命令超时: {method} (已等待{timeout}秒)",
        "页面响应过慢，请刷新页面或检查网络连接"),

    # —— 认证层 ——
    "ERR_AUTH_NO_COOKIE": (ErrorCategory.AUTH,
        "未获取到jinritemai.com的登录Cookie",
        "请先在Chrome中登录 https://fxg.jinritemai.com"),
    "ERR_AUTH_NO_PUBLISH_ID": (ErrorCategory.AUTH,
        "无法生成publishId，webpack模块注入可能失败",
        "请确保当前在发品页面 (/ffa/g/create) 或商品列表页"),
    "ERR_AUTH_TOKEN_INVALID": (ErrorCategory.AUTH,
        "Token认证失败: {platform_msg}",
        "n_token/shop_id/feature 字段可能缺失或错误，若不是→可能是提交频率限制"),
    "ERR_ANTI_ABUSE_BLOCK": (ErrorCategory.AUTH,
        "平台反滥用拦截: {platform_msg}",
        "代码=10013/10001010A。高频提交触发了平台安全检测。等待2-5分钟冷却后重试，或通过页面手动发布一次以恢复正常。生产环境建议每次提交间隔≥60秒。"),
    "ERR_BODY_TITLE_TOO_LONG": (ErrorCategory.VALIDATION,
        "标题过长: {platform_msg}",
        "标题最长30个汉字(60个字符)，请缩短标题"),
    "ERR_PRICE_TOO_LOW": (ErrorCategory.VALIDATION,
        "价格过低: {platform_msg}",
        "价格最小应为0.01元，请调整价格"),
    "ERR_SKU_DUPLICATE": (ErrorCategory.VALIDATION,
        "SKU重复: {platform_msg}",
        "存在重复的SKU名称，请去重后再提交"),
    "ERR_SPEC_MISMATCH": (ErrorCategory.VALIDATION,
        "规格不匹配: {platform_msg}",
        "SKU的规格组合与spec_detail不一致，请检查spec_detail_ids"),
    "ERR_AUTH_SESSION_EXPIRED": (ErrorCategory.AUTH,
        "会话可能已过期 (多次10013错误)",
        "请刷新Chrome页面重新建立会话，或在发品页面上执行一次手动操作"),

    # —— Schema 层 ——
    "ERR_SCHEMA_FAILED": (ErrorCategory.SCHEMA,
        "获取类目Schema失败: platform_code={platform_code}, msg={msg}",
        "检查category_leaf_id是否正确，或网络是否正常"),
    "ERR_SCHEMA_EMPTY": (ErrorCategory.SCHEMA,
        "类目Schema返回为空，category_leaf_id={category_id}",
        "该类目ID可能不存在或已被平台废弃，请确认类目ID有效"),
    "ERR_SCHEMA_NO_PROPERTIES": (ErrorCategory.SCHEMA,
        "类目Schema中无category_properties，数据不完整",
        "Schema返回异常，请查看原始数据排查"),

    # —— 图片上传层 ——
    "ERR_IMAGE_NOT_FOUND": (ErrorCategory.INPUT,
        "图片文件不存在: {path}",
        "请检查文件路径是否正确，文件是否已被移动或删除"),
    "ERR_IMAGE_UPLOAD_FAILED": (ErrorCategory.NETWORK,
        "图片上传失败: {path} → {detail}",
        "检查Cookie是否有效、网络是否正常、图片格式是否支持"),
    "ERR_IMAGE_RATIO_34": (ErrorCategory.VALIDATION,
        "平台拒绝3:4主图: {msg}",
        "图片自动裁剪为1440x1920后可能仍有问题，请检查原图质量"),
    "ERR_IMAGE_RATIO_11": (ErrorCategory.VALIDATION,
        "平台拒绝1:1白底图/主图: {msg}",
        "图片自动裁剪为1440x1440后可能仍有问题，请检查原图"),
    "ERR_IMAGE_COUNT": (ErrorCategory.VALIDATION,
        "平台要求上传1~5张商品主图，当前为{count}张",
        "请确保至少上传1张主图"),

    # —— Body 构建层 ——
    "ERR_BODY_MISSING_TITLE": (ErrorCategory.INPUT,
        "商品标题为空或少于8个字符",
        "标题至少需要8个中文字符"),
    "ERR_BODY_MISSING_CATEGORY": (ErrorCategory.INPUT,
        "缺少类目配置 (category_config)",
        "请提供完整的category_config，包含first/second/third/fourth的cid和cname"),
    "ERR_BODY_MISSING_PRICE": (ErrorCategory.INPUT,
        "商品价格未设置或为0",
        "price.current 必须 > 0.01"),
    "ERR_BODY_INVALID_SKU": (ErrorCategory.VALIDATION,
        "SKU列表为空",
        "至少需要1个SKU"),

    # —— 提交层 ——
    "ERR_SUBMIT_PLATFORM": (ErrorCategory.PLATFORM,
        "平台提交失败: platform_code={platform_code}, msg={msg}",
        "请根据具体msg排查：schema参数为空→body格式问题; token非法→认证字段缺失; 主图比例→图片比例不匹配"),
    "ERR_SUBMIT_TIMEOUT": (ErrorCategory.NETWORK,
        "提交请求超时 (已等待{timeout}秒)",
        "平台响应缓慢，可稍后重试"),
    "ERR_SUBMIT_NETWORK": (ErrorCategory.NETWORK,
        "提交请求网络错误: {detail}",
        "检查网络连接，确认Chrome和平台均可正常访问"),

    # —— 网络层 ——
    "ERR_NETWORK_REQUEST": (ErrorCategory.NETWORK,
        "HTTP请求失败: {url} → {detail}",
        "检查网络连接和目标服务可用性"),
    "ERR_NETWORK_TIMEOUT": (ErrorCategory.NETWORK,
        "请求超时: {url} (已等待{timeout}秒)",
        "网络延迟过高或服务端无响应，建议重试"),

    # —— 通用 ——
    "ERR_UNKNOWN": (ErrorCategory.UNKNOWN,
        "未知错误: {detail}",
        "请查看原始错误信息排查"),
    "ERR_PIPELINE_STEP": (ErrorCategory.UNKNOWN,
        "流水线在 [{step}] 步骤失败: {detail}",
        "检查该步骤的输入和前置条件"),
}


# ============================================================
# 结构化错误构建
# ============================================================

def make_error(code, **kwargs):
    """构建结构化错误响应。

    Args:
        code: 错误码 (如 ERR_CDP_NO_BROWSER)
        **kwargs: 用于填充消息模板的参数

    Returns:
        dict: {"success": False, "error": {...}}
    """
    if code not in ERROR_DEFS:
        code = "ERR_UNKNOWN"
        kwargs.setdefault("detail", code)

    category, template, hint = ERROR_DEFS[code]

    # 安全格式化：只替换已知占位符，未提供的保留原样
    message = template
    for k, v in kwargs.items():
        message = message.replace("{" + k + "}", str(v))

    error = {
        "code": code,
        "category": category.value,
        "message": message,
        "fix_hint": hint.format(**kwargs) if "{" in hint else hint,
        "retryable": _is_retryable(code, category),
    }

    # 附加诊断信息
    for key in ("detail", "raw", "step", "port", "category_id", "path", "timeout"):
        if key in kwargs:
            error[key] = kwargs[key]

    return {"success": False, "error": error}


def make_success(data=None):
    """构建成功响应"""
    return {"success": True, "data": data or {}}


def _is_retryable(code, category):
    """判断错误是否可重试"""
    if category == ErrorCategory.NETWORK:
        return True
    if code in ("ERR_CDP_TIMEOUT", "ERR_SUBMIT_TIMEOUT", "ERR_AUTH_SESSION_EXPIRED"):
        return True
    if code in ("ERR_AUTH_TOKEN_INVALID",):
        return True  # 刷新session后可重试
    return False


# ============================================================
# 平台 API 错误码映射
# ============================================================

PLATFORM_CODE_MAP = {
    "10002": "ERR_SUBMIT_PLATFORM",   # schema参数为空
    "10013": "ERR_AUTH_TOKEN_INVALID", # token非法 (也可能是图片/验证错误 — 需要看msg区分)
    "500": "ERR_SCHEMA_FAILED",       # 类目ID必传
    "10001010A": "ERR_AUTH_TOKEN_INVALID", # 系统检测到发品方式异常
}


def from_platform_response(result, step="submit"):
    """将平台API响应转换为结构化错误。

    重要: code=10013 是平台通用验证错误码，具体原因在 msg 字段。
    已发现的 msg 模式:
    - 反滥用: "发品方式可能存在异常/非官方途径/非正规技术"
    - 标题过长: "商品标题最长不能超过30个汉字"
    - 标题过短: (平台前端验证，不会到API)
    - 图片比例: "主图3：4比例要求3:4" / "主图1:1"
    - 图片数量: "请上传1~5张商品主图"
    - token非法: "提交参数异常 token非法" (仅当认证字段缺失时)
    - 价格: 待发现
    - SKU: 待发现
    """
    code = str(result.get("code", ""))
    msg = result.get("msg", "")

    # ---- 顺序很重要: 先匹配具体msg，再回退到通用code ----

    # 反滥用拦截 (最高优先级，因为code可能是10013或10001010A)
    if any(kw in msg for kw in ["非官方途径", "非正规技术", "发品方式可能存在异常"]):
        return make_error("ERR_ANTI_ABUSE_BLOCK", platform_code=code, platform_msg=msg, raw=result, step=step)

    # 标题验证
    if "标题最长" in msg:
        return make_error("ERR_BODY_TITLE_TOO_LONG", platform_code=code, platform_msg=msg, raw=result, step=step)

    # 图片比例
    if "主图" in msg and ("3:4" in msg or "3：4" in msg):
        return make_error("ERR_IMAGE_RATIO_34", platform_msg=msg, raw=result, step=step)
    if "主图" in msg and ("1:1" in msg or "1：1" in msg):
        return make_error("ERR_IMAGE_RATIO_11", platform_msg=msg, raw=result, step=step)

    # 图片数量
    if "上传1~5张" in msg or "上传1～5张" in msg or "1~5张商品主图" in msg:
        return make_error("ERR_IMAGE_COUNT", count=0, raw=result, step=step)

    # 价格验证
    if "价格" in msg:
        if "最小" in msg or "0.01" in msg:
            return make_error("ERR_PRICE_TOO_LOW", platform_code=code, platform_msg=msg, raw=result, step=step)
        return make_error("ERR_BODY_MISSING_PRICE", platform_code=code, platform_msg=msg, raw=result, step=step)

    # SKU/规格
    if any(kw in msg for kw in ["SKU", "sku", "规格型号", "规格值"]):
        if "重复" in msg:
            return make_error("ERR_SKU_DUPLICATE", platform_code=code, platform_msg=msg, raw=result, step=step)
        return make_error("ERR_SPEC_MISMATCH", platform_code=code, platform_msg=msg, raw=result, step=step)

    # token非法 (仅当真的是认证问题 — msg包含"参数异常"或"token")
    if code == "10013" and ("参数异常" in msg or "token" in msg.lower()):
        return make_error("ERR_AUTH_TOKEN_INVALID", platform_code=code, platform_msg=msg, raw=result, step=step)

    # 通用: code=10013 但msg模式未知 → 新发现的验证规则
    if code == "10013":
        return make_error("ERR_SUBMIT_PLATFORM", platform_code=code, platform_msg=msg, raw=result, step=step,
                          detail=f"未知的10013子类型, msg={msg[:100]}")

    # 其他通用平台错误
    mapped_code = PLATFORM_CODE_MAP.get(code, "ERR_SUBMIT_PLATFORM")
    return make_error(mapped_code, platform_code=code, platform_msg=msg, raw=result, step=step)


# ============================================================
# 流水线步骤错误包装
# ============================================================

class PipelineError(Exception):
    """流水线异常，携带结构化错误信息"""
    def __init__(self, error_response):
        self.error = error_response
        super().__init__(error_response.get("error", {}).get("message", "pipeline error"))


def wrap_pipeline_result(step_name, fn, *args, **kwargs):
    """包装流水线步骤，统一异常处理。

    用法:
        result = wrap_pipeline_result("get_session", get_fxg_session)
        if not result["success"]:
            return result  # 直接返回错误给调用者
    """
    try:
        return fn(*args, **kwargs)
    except PipelineError:
        raise  # 透传
    except Exception as e:
        return make_error("ERR_PIPELINE_STEP",
                          step=step_name,
                          detail=str(e)[:500])

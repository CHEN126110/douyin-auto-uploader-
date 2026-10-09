# -*- coding: utf-8 -*-
"""mtop H5 网关的签名与响应分类。

**为什么需要这个模块**：外部调研已实证，淘宝官方发品 API（``taobao.item.add`` /
``alibaba.item.publish.submit``）对普通淘宝集市卖家实质关闭——自研商家身份「仅面向
天猫商家开放」，第三方必须走 ISV 资质审核。因此本子项目只能走
Web 工作台 + 页面内 mtop 调用这条路线，mtop 签名是这条路线的地基。

证据来源（见 ``docs/05-证据日志.md`` E-005 / E-006）：

* 仓库内已跑通的**读路径**实现：``tauri-app/python-sidecar/app.py:10875-10903``
  与 ``:10959-10973``，使用的正是 ``md5(token&t&appKey&data)`` 与 appKey ``12574478``。
* 外部资料给出的同一算法与 token 生命周期说明。

**红线**：本模块只做纯计算与分类，**不发起任何请求**。``token`` 只在内存中流转，
不写日志、不落盘。请求的发送由调用方（浏览器内 fetch 或 CDP）负责。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple
from urllib.parse import urlencode

#: mtop H5 网关。
MTOP_H5_HOST: str = "https://h5api.m.taobao.com"

#: H5 场景的常见 appKey。读路径实测使用该值并成功返回数据。
H5_APP_KEY_DEFAULT: str = "12574478"

#: ``_m_h5_tk`` 里明文 token 的长度（``token_expireTime`` 中 ``_`` 之前的部分）。
H5_TK_TOKEN_LENGTH: int = 32

#: 读路径实测的 jsv 版本。
MTOP_JSV: str = "2.6.2"

#: 签名算法标识。写进产物便于回溯，不含任何密钥。
SIGN_ALGORITHM: str = "md5(token&t&appKey&data)"

# --- mtop 业务返回码 -------------------------------------------------------
RET_SUCCESS: str = "SUCCESS"
#: token 为空或过期。服务端会同时 Set-Cookie 下发新 token，可自愈一次。
RET_TOKEN_EXPIRED: str = "FAIL_SYS_TOKEN_EXOIRED"  # 平台侧拼写如此，不要"纠正"
RET_TOKEN_EMPTY: str = "FAIL_SYS_TOKEN_EMPTY"
RET_ILLEGAL_ACCESS: str = "FAIL_SYS_ILLEGAL_ACCESS"
RET_SESSION_EXPIRED: str = "FAIL_SYS_SESSION_EXPIRED"
RET_SIGN_ERROR: str = "FAIL_SYS_SIGN_ERROR"

TOKEN_RETRY_CODES: Tuple[str, ...] = (RET_TOKEN_EXPIRED, RET_TOKEN_EMPTY)
AUTH_FAILURE_CODES: Tuple[str, ...] = (
    RET_SESSION_EXPIRED,
    RET_ILLEGAL_ACCESS,
    RET_SIGN_ERROR,
)


def now_ms() -> int:
    """当前毫秒时间戳。抽成函数便于测试注入。"""

    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# token 解析
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class H5Token:
    """``_m_h5_tk`` 的解析结果。

    :param raw_length: 原始 cookie 值长度，仅用于诊断（不回显内容）。
    :param expire_at_ms: 过期时间戳（毫秒）；解析不出时为 ``None``。
    """

    value: str
    expire_at_ms: Optional[int] = None
    raw_length: int = 0

    @property
    def is_well_formed(self) -> bool:
        """长度是否符合实证的 32 字符形态。"""

        return len(self.value) == H5_TK_TOKEN_LENGTH

    def expires_within(self, ms: int, *, now: Optional[int] = None) -> bool:
        """判断 token 是否将在 ``ms`` 毫秒内过期。解析不出过期时间时返回 ``True``
        （宁可多刷一次，也不要用过期 token 去打接口）。"""

        if self.expire_at_ms is None:
            return True
        reference = now if now is not None else now_ms()
        return self.expire_at_ms - reference <= ms

    def describe(self) -> Dict[str, Any]:
        """**不含 token 值**的诊断信息。"""

        return {
            "token_length": len(self.value),
            "well_formed": self.is_well_formed,
            "has_expiry": self.expire_at_ms is not None,
            "raw_length": self.raw_length,
        }


def parse_h5_tk(cookie_value: Optional[str]) -> Optional[H5Token]:
    """解析 ``_m_h5_tk`` 的 cookie 值，格式为 ``明文token_expireTime``。

    :return: 解析失败返回 ``None``；成功返回 :class:`H5Token`。

    实现细节：token 本身**不含** ``_``，因此按**第一个** ``_`` 切分；过期时间取
    **最后一段**纯数字。这样即便格式将来多出字段也不会把 token 截错。
    """

    if not cookie_value:
        return None
    raw = str(cookie_value).strip()
    if not raw:
        return None
    token, sep, _rest = raw.partition("_")
    if not sep or not token:
        return None
    expire_at_ms: Optional[int] = None
    tail = raw.rsplit("_", 1)[-1]
    if tail.isdigit():
        try:
            expire_at_ms = int(tail)
        except ValueError:  # pragma: no cover - isdigit 已保证
            expire_at_ms = None
    return H5Token(value=token, expire_at_ms=expire_at_ms, raw_length=len(raw))


# ---------------------------------------------------------------------------
# 签名
# ---------------------------------------------------------------------------
def canonical_data(data: Any) -> str:
    """把请求 data 规范化成签名用的字符串。

    **必须**与真正发出去的 ``data`` 参数逐字节一致，否则签名必然失败。
    这里统一用 ``separators=(',', ':')`` 紧凑序列化（读路径实测用法）；
    ``dict`` 的键顺序按传入顺序保留，不做排序——排序会改变签名却改不了
    服务端看到的内容。
    """

    if isinstance(data, str):
        return data
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def sign(token: str, timestamp_ms: str, app_key: str, data_str: str) -> str:
    """计算 mtop 签名：``md5(token&t&appKey&data)``。

    :param timestamp_ms: 与请求 query 里的 ``t`` **完全相同**的字符串。
    """

    if not token:
        raise ValueError("mtop 签名的 token 不能为空")
    if not timestamp_ms:
        raise ValueError("mtop 签名的 t 不能为空")
    if not app_key:
        raise ValueError("mtop 签名的 appKey 不能为空")
    material = f"{token}&{timestamp_ms}&{app_key}&{data_str}"
    return hashlib.md5(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MtopRequest:
    """一次 mtop GET 的完整描述。``url`` 已含签名；``body`` 是 POST 表单体。

    .. warning::
        ``url`` 里含 ``sign`` 参数。按红线第 3 条，**落盘或上报前必须过
        :func:`taobao_publish.sanitize.sanitize_url`**。
    """

    api: str
    version: str
    url: str
    body: bytes
    data_str: str
    timestamp_ms: str
    sign_algorithm: str = SIGN_ALGORITHM
    extra: Dict[str, Any] = field(default_factory=dict)

    def describe(self) -> Dict[str, Any]:
        """脱敏后的描述，可直接进日志与产物。"""

        return {
            "api": self.api,
            "version": self.version,
            "timestamp_ms": self.timestamp_ms,
            "sign_algorithm": self.sign_algorithm,
            "data_keys": sorted(json.loads(self.data_str).keys())
            if self.data_str.startswith("{")
            else [],
            "url_host": MTOP_H5_HOST,
        }


def build_request(
    api: str,
    data: Any,
    token: str,
    *,
    version: str = "1.0",
    app_key: str = H5_APP_KEY_DEFAULT,
    timestamp_ms: Optional[str] = None,
    timeout_ms: int = 10000,
    extra_query: Optional[Mapping[str, str]] = None,
) -> MtopRequest:
    """构造一次已签名的 mtop 请求（不发送）。

    URL 形态与读路径实测一致：``https://h5api.m.taobao.com/h5/<api>/<v>/?<query>``，
    签名在 query 里，``data`` 走 POST 表单体。
    """

    if not api:
        raise ValueError("api 不能为空")
    normalized_version = str(version or "1.0")
    data_str = canonical_data(data)
    ts = str(timestamp_ms) if timestamp_ms is not None else str(now_ms())
    signature = sign(token, ts, app_key, data_str)

    query: Dict[str, str] = {
        "jsv": MTOP_JSV,
        "appKey": app_key,
        "t": ts,
        "sign": signature,
        "api": api,
        "v": normalized_version,
        "type": "originaljson",
        "timeout": str(int(timeout_ms)),
        "dataType": "json",
    }
    if extra_query:
        query.update({str(k): str(v) for k, v in extra_query.items()})

    url = f"{MTOP_H5_HOST}/h5/{api}/{normalized_version}/?{urlencode(query)}"
    body = urlencode({"data": data_str}).encode("utf-8")
    return MtopRequest(
        api=api,
        version=normalized_version,
        url=url,
        body=body,
        data_str=data_str,
        timestamp_ms=ts,
    )


#: 浏览器里 mtop 客户端实际用的 jsv（2026-10-05 被动观察 h5api 请求得到）。
BROWSER_JSV: str = "2.6.1"
#: 浏览器里 mtop 客户端实际用的响应类型。它返回的是 **JSONP**（``callback({...})``）。
BROWSER_TYPE: str = "originaljsonp"
#: JSONP 回调名的**前缀**。实测真实页面用的是全小写 ``mtopjsonp33`` / ``mtopjsonp34``
#: （数字是页面内的自增序号）。写成 ``MTopJsonp1`` 这种形态会被网关判「非法请求」——
#: 这一点是实测踩出来的，别改。
JSONP_CALLBACK_PREFIX: str = "mtopjsonp"
#: 解析原始响应时，JSONP 包装的正则（回调名大小写都容忍）。
_JSONP_RE = re.compile(r"^[A-Za-z_$][\w$.]*\s*\(\s*(.*?)\s*\)\s*;?\s*$", re.DOTALL)


def jsonp_callback_name(sequence: int = 1) -> str:
    """生成 JSONP 回调名。实测形态是 ``mtopjsonp<序号>``。"""

    if type(sequence) is not int or sequence < 1:
        raise ValueError("JSONP 序号必须是从 1 开始的整数")
    return f"{JSONP_CALLBACK_PREFIX}{sequence}"


def strip_jsonp(text: Optional[str]) -> Optional[str]:
    """把 JSONP 包装剥掉，只留 JSON 文本；不是 JSONP 就原样返回。"""

    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return raw
    match = _JSONP_RE.match(raw)
    if match:
        return match.group(1).strip()
    return raw


def build_browser_request(
    api: str,
    data: Any,
    token: str,
    *,
    version: str = "1.0",
    app_key: str = H5_APP_KEY_DEFAULT,
    timestamp_ms: Optional[str] = None,
    ttid: str = "",
    callback: str = "",
    extra_query: Optional[Mapping[str, str]] = None,
) -> MtopRequest:
    """构造**浏览器同形态**的 mtop GET 请求（不发送）。

    ## 为什么要有这个函数

    ``build_request`` 是照仓库里已跑通的**采集读路径**做的（POST，``data`` 在 body，
    ``type=originaljson``）。2026-10-05 用 CDP 被动观察真实图片空间页面
    （``qn.taobao.com`` 素材中心）发现，浏览器里的 mtop 客户端实际发的是**另一种形态**，
    并且下面每一条都**实测过**（``tmp/live-directory-headers.json`` 与
    一次逐参数对照）：

    ==========================  ==========================================
    项                          实测值
    ==========================  ==========================================
    方法                        ``GET``，``data`` 在 **query**
    ``jsv``                     ``2.6.1``
    ``type``                    ``originaljsonp``
    ``dataType``                ``originaljsonp``（**不是** ``jsonp``）
    ``timeout``                 **不发送**（早先多发这个参数是错的）
    ``ttid``                    ``<会员ID>@taobao_WEB_<主>.<次>.<修订>``，长度 23
    ``callback``                ``mtopjsonp<序号>``（全小写）
    ``appKey`` / ``v``          ``12574478`` / ``1.0``（与读路径一致）
    请求头                      ``referer`` 是页面自身（``qn.taobao.com``），**无 Origin**
    ==========================  ==========================================

    按 POST 形态、或按 ``jsonp`` / 带 ``timeout`` 的形态去打
    ``mtop.taobao.picturecenter.console.dir.query``，实测一律返回
    ``FAIL_SYS_ILLEGAL_ACCESS::非法请求``——**同一套签名，错的只是形态**。

    :param ttid: 客户端标识。实测必需，形态见上表。留空则不发送
        （**但那样会被网关当非法请求**，所以调用方应当传真实值）。
    :param callback: JSONP 回调名；留空用 :func:`jsonp_callback_name`。
    """

    if not api:
        raise ValueError("api 不能为空")
    normalized_version = str(version or "1.0")
    data_str = canonical_data(data)
    ts = str(timestamp_ms) if timestamp_ms is not None else str(now_ms())
    signature = sign(token, ts, app_key, data_str)
    query: Dict[str, str] = {
        "jsv": BROWSER_JSV,
        "appKey": app_key,
        "t": ts,
        "sign": signature,
        "api": api,
        "v": normalized_version,
        "type": BROWSER_TYPE,
        "dataType": BROWSER_TYPE,
        "data": data_str,
        "callback": callback or jsonp_callback_name(),
    }
    if ttid:
        query["ttid"] = ttid
    if extra_query:
        query.update({str(k): str(v) for k, v in extra_query.items()})
    url = f"{MTOP_H5_HOST}/h5/{api}/{normalized_version}/?{urlencode(query)}"
    return MtopRequest(
        api=api,
        version=normalized_version,
        url=url,
        body=b"",
        data_str=data_str,
        timestamp_ms=ts,
        extra={
            "method": "GET",
            "data_in_query": True,
            "jsv": BROWSER_JSV,
            "type": BROWSER_TYPE,
            "ttid_present": bool(ttid),
        },
    )


def browser_ttid(member_id: Any, *, major: int = 7, minor: int = 0, patch: int = 0) -> str:
    """拼出实测形态的 ``ttid``：``<会员ID>@taobao_WEB_<主>.<次>.<修订>``。

    :param member_id: 会员数字 ID（cookie ``unb``）。**不要把它写进产物**，
        这是店铺身份信息；本函数只负责拼字符串。
    """

    text = str(member_id or "").strip()
    if not text.isdigit():
        raise ValueError("ttid 需要真实会员数字 ID（cookie unb）")
    return f"{text}@taobao_WEB_{int(major)}.{int(minor)}.{int(patch)}"


def build_headers(
    *,
    cookie_str: str,
    referer: str,
    origin: Optional[str] = None,
) -> Dict[str, str]:
    """构造 mtop 请求头。

    .. warning::
        返回的 ``Cookie`` 头含登录态。**禁止**原样写日志或落盘。
    """

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": referer,
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": cookie_str,
    }
    if origin:
        headers["Origin"] = origin
    return headers


# ---------------------------------------------------------------------------
# 响应分类
# ---------------------------------------------------------------------------
#: 返回码 → 本子项目错误码。
RET_TO_ERROR_CODE: Dict[str, str] = {
    RET_TOKEN_EXPIRED: "LOGIN_REQUIRED",
    RET_TOKEN_EMPTY: "LOGIN_REQUIRED",
    RET_SESSION_EXPIRED: "LOGIN_REQUIRED",
    RET_ILLEGAL_ACCESS: "PLATFORM_ERROR",
    RET_SIGN_ERROR: "PLATFORM_ERROR",
}

#: 命中即说明拿到的不是 JSON，而是风控/验证页。
RISK_PAGE_MARKERS: Tuple[str, ...] = (
    "baxia",
    "x5sec",
    "punish",
    "captcha",
    "_sec_",
    "nc_1_n1z",
)


@dataclass(frozen=True)
class MtopResponse:
    """一次 mtop 响应的分类结果。"""

    ok: bool
    ret: Tuple[str, ...]
    error_code: str = ""
    is_token_retryable: bool = False
    is_auth_failure: bool = False
    is_risk_page: bool = False
    message: str = ""
    payload: Optional[Dict[str, Any]] = None
    raw_length: int = 0

    def describe(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "ret": list(self.ret),
            "error_code": self.error_code,
            "token_retryable": self.is_token_retryable,
            "auth_failure": self.is_auth_failure,
            "risk_page": self.is_risk_page,
            "message": self.message,
            "raw_length": self.raw_length,
        }


def classify_response(raw_text: Optional[str]) -> MtopResponse:
    """把 mtop 的原始响应文本分类。

    分三种情况：

    1. **不是 JSON** → 多为 baxia/x5sec 风控页。命中 :data:`RISK_PAGE_MARKERS`
       标记为风控；否则按普通平台错误处理。
    2. **是 JSON 但缺 ``ret``** → 平台错误，保留 ``api``/``v`` 等诊断字段。
    3. **有 ``ret``** → 首个 ``ret`` 元素形如 ``SUCCESS::调用成功`` 或
       ``FAIL_SYS_XXX::原因``，按 ``::`` 前段判定。
    """

    if not raw_text:
        return MtopResponse(ok=False, ret=(), error_code="PLATFORM_ERROR", message="响应为空", raw_length=0)

    text = str(raw_text)
    # 浏览器形态（``type=originaljsonp``）返回的是 ``callback({...})``：
    # 不先剥掉包装，后面会一律被判成「响应不是 JSON」——那会把
    # 「网关其实回了 ret」这件事直接丢掉（实测踩过）。
    stripped_text = strip_jsonp(text) or ""
    stripped = stripped_text.lstrip()
    is_json_like = stripped.startswith("{") or stripped.startswith("[")
    if not is_json_like:
        lower = text.lower()
        is_risk = any(marker in lower for marker in RISK_PAGE_MARKERS)
        return MtopResponse(
            ok=False,
            ret=(),
            error_code="RISK_CONTROL_HIT" if is_risk else "PLATFORM_ERROR",
            is_risk_page=is_risk,
            message="响应不是 JSON，疑似风控或验证页" if is_risk else "响应不是 JSON",
            raw_length=len(text),
        )

    try:
        payload = json.loads(stripped_text)
    except (ValueError, TypeError):
        return MtopResponse(
            ok=False,
            ret=(),
            error_code="PLATFORM_ERROR",
            message="响应不是合法 JSON",
            raw_length=len(text),
        )

    if not isinstance(payload, dict):
        return MtopResponse(
            ok=False,
            ret=(),
            error_code="PLATFORM_ERROR",
            message="响应 JSON 不是对象",
            payload=None,
            raw_length=len(text),
        )

    raw_ret = payload.get("ret")
    if isinstance(raw_ret, str):
        ret_list = (raw_ret,)
    elif isinstance(raw_ret, (list, tuple)):
        ret_list = tuple(str(item) for item in raw_ret)
    else:
        ret_list = ()

    if not ret_list:
        return MtopResponse(
            ok=False,
            ret=(),
            error_code="PLATFORM_ERROR",
            message="响应缺少 ret 字段",
            payload=payload,
            raw_length=len(text),
        )

    head = ret_list[0]
    code = head.split("::", 1)[0].strip()
    message = head.split("::", 1)[1].strip() if "::" in head else ""

    if code == RET_SUCCESS:
        return MtopResponse(ok=True, ret=ret_list, message=message, payload=payload, raw_length=len(text))

    return MtopResponse(
        ok=False,
        ret=ret_list,
        error_code=RET_TO_ERROR_CODE.get(code, "PLATFORM_ERROR"),
        is_token_retryable=code in TOKEN_RETRY_CODES,
        is_auth_failure=code in AUTH_FAILURE_CODES,
        message=message or code,
        payload=payload,
        raw_length=len(text),
    )


def extract_h5_tk_from_set_cookie(set_cookie_values: Any) -> Optional[H5Token]:
    """从 ``Set-Cookie`` 头列表中提取服务端下发的新 ``_m_h5_tk``。

    token 过期时 mtop 会回 ``FAIL_SYS_TOKEN_EXOIRED`` 并在同一响应里 Set-Cookie
    新 token，这是自愈路径。**取到的 token 只进内存。**
    """

    if not set_cookie_values:
        return None
    values = [set_cookie_values] if isinstance(set_cookie_values, str) else list(set_cookie_values)
    for header in values:
        for chunk in str(header).split(";"):
            name, sep, value = chunk.strip().partition("=")
            if sep and name.strip().lower() == "_m_h5_tk":
                parsed = parse_h5_tk(value)
                if parsed is not None:
                    return parsed
    return None

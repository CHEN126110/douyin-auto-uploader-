# -*- coding: utf-8 -*-
"""脱敏：保证任何落盘/上报的产物都不含登录态与个人信息。

红线要求（``taobao-publisher/AGENTS.md`` 第 3 条）：禁止把 cookie、token、
``_m_h5_tk``、``_tb_token_``、``cookie2``、手机号、店铺敏感信息、完整签名 URL、
未脱敏请求头写进仓库、日志或产物。

本模块是**唯一**允许把原始数据转成产物的地方。任何写文件/写日志/回报给前端的
路径都必须先过这里。

设计取舍：

* cookie **保留名字、抹掉值**——研究需要知道「哪些 cookie 存在」，但不需​要值。
* 签名 URL 保留 path 与参数名，抹掉签名类参数；一旦出现签名参数，**整条 query**
  都按敏感处理（泄漏 ``sign`` + ``t`` + ``data`` 等于交出去一次可重放的请求）。
* 脱敏**幂等**：对已脱敏文本再跑一次结果不变（便于多层调用不产生叠加污染）。

.. warning::
    2026-10-02 的对抗性审查（见 ``tmp/review/审查报告.md``）发现了本模块的四类真实
    泄漏，均已在当前版本修复并有回归测试守着。修改本文件时请先跑
    ``tests/test_sanitize.py``，那里面每一条都对应一个曾经泄漏过的具体形态：

    * 头部名字（``Cookie`` / ``Authorization`` / ``X-Token``）在递归脱敏路径里
      没被识别（F1）。
    * 三个密钥正则要求 ``name=value``，JSON 的 ``"name": "value"`` 形态全部失配（F2）。
    * 手机号只认裸 11 位，``+86`` / ``0086`` / 全角数字漏网（F3）。
    * ``sanitize_url`` 对百分号编码的敏感参数名与等号失效（F4）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import unquote

#: 统一的脱敏占位符。测试与文档都依赖这个字面量。
REDACTED = "***REDACTED***"

# ---------------------------------------------------------------------------
# 敏感名单
# ---------------------------------------------------------------------------
#: 需要整体抹值的请求/响应头（小写比较）。
SENSITIVE_HEADER_NAMES = frozenset(
    {
        "cookie",
        "set-cookie",
        "authorization",
        "proxy-authorization",
        "x-token",
        "x-csrf-token",
        "x-xsrf-token",
        "referer",  # 可能含 token 参数
        "x-requested-with",
    }
)

#: 已知的淘宝登录态/会话 cookie 名。命中即整体抹值。
SENSITIVE_COOKIE_NAMES = frozenset(
    {
        "_m_h5_tk",
        "_m_h5_tk_enc",
        "_tb_token_",
        "cookie2",
        "cookie17",
        "sgcookie",
        "tfstk",
        "cna",
        "skt",
        "unb",
        "wk_unb",
        "wk_cookie2",
        "_l_g_",
        "_nk_",
        "lgc",
        "csg",
        "tracknick",
        "sn",
    }
)

#: URL query / POST body / JSON 里需要抹值的参数名与键名。
SENSITIVE_QUERY_KEYS = frozenset(
    {
        "sign",
        "signature",
        "_m_h5_tk",
        "_m_h5_tk_enc",
        "token",
        "access_token",
        "refresh_token",
        "auth",
        "ticket",
        "session",
        "sessionid",
        "sid",
        "spm",  # 含用户/场景标识
        "utparam",
        "utdiddisable",
        "uid",
        "userid",
        "user_id",
        "nick",
        "tracknick",
        "unb",
        "cookie2",
        "_tb_token_",
        "sgcookie",
        "tfstk",
        "cna",
        "skt",
        "lgc",
        "csg",
        "t",
    }
)

#: 文本级「键=值」脱敏的键名（合并上面两份名单，并补上通用的凭据名字）。
#: 这些键无论在 ``a=b``、``"a":"b"``、``a: b`` 哪种形态下都要抹值。
SENSITIVE_SECRET_KEYS = frozenset(
    set(SENSITIVE_COOKIE_NAMES)
    | {
        "sign",
        "signature",
        "token",
        "access_token",
        "refresh_token",
        "auth",
        "ticket",
        "sessionid",
        "password",
        "passwd",
        "secret",
        "apikey",
        "api_key",
        "cookie",
        "set-cookie",
        "authorization",
        "x-token",
    }
)

#: 在 URL query 里出现即视为「带签名」，整条 query 都要抹掉。
SIGNATURE_QUERY_KEYS = frozenset(
    {"sign", "signature", "_m_h5_tk", "_m_h5_tk_enc", "token", "access_token", "sgcookie", "tfstk"}
)


# ---------------------------------------------------------------------------
# 正则
# ---------------------------------------------------------------------------
_COOKIE_HEADER_RE = re.compile(r"(?i)\b(cookie|set-cookie)\b\s*[:=]\s*([^\r\n]*)")

#: ``name=value`` / ``"name":"value"`` / ``'name': 'value'`` 三种形态通吃。
#: 前置的负向后顾保证 ``assign=`` 里的 ``sign`` 不会被误匹配。
#:
#: 值的字符集**排除 ``{`` 与 ``[``**：真正的凭据值是标量（hex / base64 / 串），
#: 而以 ``{`` / ``[`` 开头的是我们自己的 JSON 结构——例如报告里的
#: ``"authorization": {"source": "environment"}``。不排除的话，脱敏器会把
#: 自己的结构化报告判成「藏了凭据」，`assert_clean` 就会对干净产物误报。
_SECRET_VALUE_CLASS = r"[^\s;&\"'<>,\}\{\[\]]+"
_SECRET_PAIR_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?P<lead>[\"']?(?P<key>"
    + "|".join(re.escape(key) for key in sorted(SENSITIVE_SECRET_KEYS, key=len, reverse=True))
    + r")[\"']?\s*[:=]\s*)(?P<quote>[\"']?)(?P<value>"
    + _SECRET_VALUE_CLASS
    + r")"
)

#: 裸 URL 扫描：用于按「整条 query 是否含签名参数」做判断。
_URL_RE = re.compile(r"(?i)\bhttps?://[^\s\"'<>]+")

#: 手机号：可选国家码（``+86`` / ``86`` / ``0086``），裸 11 位（``1[3-9]`` 开头），
#: 允许 ``-`` / 空格分组（``138-1234-5678``、``+86 138 1234 5678``）。
_PHONE_RE = re.compile(
    r"(?<!\d)(?:(?:\+?86)|(?:0086))?[-\s]?1[3-9]\d[-\s]?\d{4}[-\s]?\d{4}(?!\d)"
)
#: 纯数字手机号（用于 int 标量）。
_PHONE_DIGITS_RE = re.compile(r"^(?:(?:\+?86)|(?:0086))?1[3-9]\d{9}$")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

#: 全角数字/加号 → 半角。全角与半角都是单字符，因此替换不会让位置偏移。
_FULLWIDTH_TO_HALFWIDTH = str.maketrans(
    {chr(0xFF10 + offset): str(offset) for offset in range(10)} | {chr(0xFF0B): "+"}
)

#: 「看起来像 cookie 串」的判据：至少两段 ``name=value`` 且用 ``;`` 分隔。
_COOKIE_PAIR_RE = re.compile(r"(?i)(?:^|[;\s])([A-Za-z0-9_\-]{1,40})=([^;\s]{1,200})")


def _looks_like_cookie_string(text: str) -> bool:
    """判断一段文本是否是 cookie 串。

    命中即整体过 :func:`sanitize_cookie_string`——这样即便出现在一个名字毫不相干的
    键下（例如 ``post_data``），也不会把值漏出去。
    """

    if not text or ";" not in text:
        return False
    pairs = _COOKIE_PAIR_RE.findall(text)
    if len(pairs) < 2:
        return False
    known = {name.strip().lower() for name, _ in pairs} & SENSITIVE_COOKIE_NAMES
    return len(known) >= 1


# ---------------------------------------------------------------------------
# 文本脱敏
# ---------------------------------------------------------------------------
def _redact_phones(text: str) -> str:
    """抹掉手机号，兼容国家码前缀与全角数字。

    做法：先把文本归一化成半角做**定位**，再把命中的区间映射回原文本替换。
    半角与全角数字都是一字符宽，因此区间可直接复用。
    """

    normalized = text.translate(_FULLWIDTH_TO_HALFWIDTH)
    spans = [match.span() for match in _PHONE_RE.finditer(normalized)]
    if not spans:
        return text
    pieces: List[str] = []
    cursor = 0
    for start, end in spans:
        if start < cursor:
            continue
        pieces.append(text[cursor:start])
        pieces.append(REDACTED)
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _strip_url_query(url: str) -> str:
    """保留 scheme/host/path，把 query 整体替换为占位符。"""

    head = url.split("?", 1)[0]
    if "?" not in url:
        return head
    return f"{head}?{REDACTED}"


def _url_query_pairs(url: str) -> Optional[List[str]]:
    if "?" not in url:
        return None
    _, _, query = url.partition("?")
    return query.split("&")


def _query_has_signature(query: str) -> bool:
    """判断 query 是否含签名类参数。

    **同时检查原文与百分号解码后的形态**：``%73ign=SIGN``、``sign%3DSIGN``、
    ``q=a%3D1%26sign%3DSIGN`` 这三种编码变形都必须被识别（F4）。
    """

    for candidate in (query, unquote(query)):
        for chunk in candidate.split("&"):
            if not chunk:
                continue
            name, sep, _value = chunk.partition("=")
            key = name.strip().lower()
            if key in SIGNATURE_QUERY_KEYS:
                return True
            if not sep and "=" in candidate and key in SIGNATURE_QUERY_KEYS:
                return True
    return False


def sanitize_text(text: Optional[str]) -> str:
    """抹掉任意文本里的 token、手机号、邮箱与签名 URL。

    幂等：已脱敏文本再次输入结果不变。
    """

    if text is None:
        return ""
    value = str(text)

    # 1) 整段 cookie 串：先按「只留名字」处理，避免逐键规则漏掉个别 cookie 名。
    if _looks_like_cookie_string(value):
        value = _sanitize_cookie_pairs(value)

    # 2) Header 形态的 cookie。
    value = _COOKIE_HEADER_RE.sub(lambda m: f"{m.group(1)}: {REDACTED}", value)

    # 3) ``name=value`` / ``"name": "value"`` 形态的凭据。
    #
    #    只补 ``quote`` 一个引号：值的**闭合引号仍在原文里**，再补一个会产生
    #    ``"sign":"***REDACTED***""`` 这种畸形 JSON，让脱敏产物没法再被解析。
    value = _SECRET_PAIR_RE.sub(
        lambda m: f"{m.group('lead')}{m.group('quote')}{REDACTED}", value
    )

    # 4) URL：含签名类参数就把整条 query 抹掉，不论它是明文还是百分号编码。
    def _replace_url(match: re.Match) -> str:
        raw = match.group(0)
        query = raw.partition("?")[2]
        if not query:
            return raw
        if _query_has_signature(query):
            return _strip_url_query(raw)
        return _scrub_query_loosely(raw)

    value = _URL_RE.sub(_replace_url, value)

    # 5) 手机号与邮箱。
    value = _redact_phones(value)
    value = _EMAIL_RE.sub(REDACTED, value)
    return value


def _scrub_query_loosely(url: str) -> str:
    """按参数名逐个抹值（没有签名类参数时的路径）。"""

    head, sep, query = url.partition("?")
    if not sep:
        return url
    pairs = []
    for chunk in query.split("&"):
        if not chunk:
            continue
        name, pair_sep, _value = chunk.partition("=")
        # 百分号解码后再比较参数名，防止 ``%73ign`` 这类变形逃逸。
        decoded_name = unquote(name).strip().lower()
        if decoded_name in SENSITIVE_QUERY_KEYS:
            pairs.append(f"{name}{pair_sep}{REDACTED}")
        else:
            pairs.append(chunk)
    return f"{head}?{'&'.join(pairs)}"


def _sanitize_cookie_pairs(text: str) -> str:
    """把 cookie 串转成 ``name=***REDACTED***``，保留结构、抹掉全部值。"""

    def _replace(match: re.Match) -> str:
        return f"{match.group(1)}={REDACTED}"

    return _COOKIE_PAIR_RE.sub(_replace, text)


def sanitize_url(url: Optional[str]) -> str:
    """脱敏 URL。

    两层处理：

    1. 用 :func:`_query_has_signature` 判断整条 query 是否含签名类参数
       （**含百分号编码变形**）。命中就整条抹掉。
    2. 否则按参数名逐个抹（:data:`SENSITIVE_QUERY_KEYS`，参数名先解码再比较）。
    """

    if not url:
        return ""
    value = str(url)
    if "?" not in value:
        return sanitize_text(value)
    query = value.partition("?")[2]
    if _query_has_signature(query):
        return sanitize_text(_strip_url_query(value))
    return sanitize_text(_scrub_query_loosely(value))


def sanitize_headers(headers: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """脱敏请求/响应头。敏感头整体抹值，其余头保留（值再过一遍文本脱敏）。"""

    if not headers:
        return {}
    result: Dict[str, str] = {}
    for raw_name, raw_value in headers.items():
        name = str(raw_name)
        if name.strip().lower() in SENSITIVE_HEADER_NAMES:
            result[name] = REDACTED
        else:
            result[name] = sanitize_text(None if raw_value is None else str(raw_value))
    return result


def sanitize_cookie_string(raw: Optional[str]) -> str:
    """把 cookie 串转成 ``name=***REDACTED***; ...``，**只保留名字**。

    解析不出 ``name=value`` 的片段整段丢弃，避免畸形 cookie 把值漏出去。
    """

    if not raw:
        return ""
    parts: List[str] = []
    for chunk in str(raw).split(";"):
        name, sep, _value = chunk.strip().partition("=")
        name = name.strip()
        if not sep or not name:
            continue
        parts.append(f"{name}={REDACTED}")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# 递归脱敏
# ---------------------------------------------------------------------------
def _key_is_sensitive(key: str) -> bool:
    """键名是否敏感。

    **必须同时查三份名单**：早先只查 query keys ∪ cookie names，导致
    ``{"request_headers": {"Cookie": "..."}}`` 里的 ``Cookie`` 值原样落盘（F1）——
    而这正是 ``capture-publish-requests.mjs`` 产出的形状。
    """

    lowered = key.strip().lower()
    return (
        lowered in SENSITIVE_HEADER_NAMES
        or lowered in SENSITIVE_COOKIE_NAMES
        or lowered in SENSITIVE_QUERY_KEYS
    )


def sanitize_payload(value: Any, *, depth: int = 0, max_depth: int = 12) -> Any:
    """递归脱敏任意 JSON 兼容结构。

    * dict 的键命中**三份名单中任意一份** → 值整体抹掉。
    * 字符串 → 过 :func:`sanitize_text`（URL 额外走 :func:`sanitize_url` 语义）。
    * 整型如果是手机号 → 抹掉（JSON 里手机号常被写成数字）。
    * ``bytes`` → 解码后按文本脱敏，避免成为绕过通道。
    * 超出 ``max_depth`` 时返回截断标记，避免畸形深嵌套把栈打爆。
    """

    if depth > max_depth:
        return f"<{REDACTED}:max_depth>"
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if _key_is_sensitive(key):
                result[key] = REDACTED
            else:
                result[key] = sanitize_payload(raw_value, depth=depth + 1, max_depth=max_depth)
        return result
    if isinstance(value, (list, tuple)):
        return [sanitize_payload(item, depth=depth + 1, max_depth=max_depth) for item in value]
    if isinstance(value, str):
        if value.lower().startswith(("http://", "https://")):
            return sanitize_url(value)
        return sanitize_text(value)
    if isinstance(value, (bytes, bytearray)):
        return sanitize_text(bytes(value).decode("utf-8", errors="replace"))
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if _PHONE_DIGITS_RE.match(str(value)):
            return REDACTED
        return value
    return value


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
def contains_secret_like(text: Optional[str]) -> bool:
    """自检：文本里是否还残留疑似登录态。

    用途：打产物前的最后一道断言。**必须对上面修过的四类形态都敏感**，
    否则守卫会放过泄漏（这正是 2026-10-02 审查发现的问题）。
    """

    if not text:
        return False
    value = str(text)

    # 1) 未被抹掉的 ``name=value`` / ``"name": "value"`` 凭据
    for match in _SECRET_PAIR_RE.finditer(value):
        if REDACTED not in match.group("value"):
            return True

    # 2) 未被抹掉的 cookie 串（整体形态）
    if ";" in value:
        for chunk in value.split(";"):
            name, sep, raw_pair_value = chunk.strip().partition("=")
            if sep and name.strip().lower() in SENSITIVE_COOKIE_NAMES:
                if REDACTED not in raw_pair_value:
                    return True

    # 3) 头部形态
    for match in _COOKIE_HEADER_RE.finditer(value):
        if REDACTED not in match.group(2):
            return True
    for header in SENSITIVE_HEADER_NAMES:
        # 值不能以 ``{`` / ``[`` 开头：那是我们自己的 JSON 结构（例如报告里的
        # ``"authorization": {"source": ...}`` 或 ``"cookie2": [...]``），
        # 不是泄漏的头值。不排除就会对干净产物误报。
        pattern = re.compile(
            rf"(?i)[\"']?{re.escape(header)}[\"']?\s*[:=]\s*[\"']?(?!{re.escape(REDACTED)})[^\s\"',\{{\[\}}]+"
        )
        if pattern.search(value):
            return True

    # 4) 手机号与邮箱
    if _PHONE_RE.search(value.translate(_FULLWIDTH_TO_HALFWIDTH)):
        return True
    if _EMAIL_RE.search(value):
        return True

    return False


def assert_clean(text: Optional[str], *, context: str = "") -> None:
    """产物落盘前的守卫。残留登录态时直接抛错而不是打个警告继续写。"""

    if contains_secret_like(text):
        where = f"（{context}）" if context else ""
        raise ValueError(f"脱敏自检失败：产物中仍残留疑似登录态{where}")


#: 这些字面量一旦出现在**要进仓库**的产物里就说明脱敏漏了。
CAPTURE_FORBIDDEN_MARKERS = tuple(
    marker
    for marker in (
        "_m_h5_tk",
        "_tb_token_",
        "cookie2",
        "sgcookie",
        "tfstk",
        "Authorization",
        "Set-Cookie",
    )
)


def assert_capture_ready(text: Optional[str], *, context: str = "") -> None:
    """写 ``captures/`` 前的**更严格**守卫。

    ``captures/`` 是要进仓库的目录，而 ``tmp/`` 不会。这条检查比
    :func:`assert_clean` 更严：只要出现敏感字段**名字**就报错——因为按设计，
    脱敏后的产物里这些名字只应该以 ``***REDACTED***`` 相邻出现。
    """

    assert_clean(text, context=context)
    value = str(text or "")
    for marker in CAPTURE_FORBIDDEN_MARKERS:
        for match in re.finditer(re.escape(marker), value, flags=re.IGNORECASE):
            window = value[max(0, match.start() - 80) : match.end() + 160]
            if REDACTED not in window:
                raise ValueError(
                    f"captures 守卫失败：出现敏感标记 {marker!r} 且邻近没有脱敏占位符"
                    + (f"（{context}）" if context else "")
                )

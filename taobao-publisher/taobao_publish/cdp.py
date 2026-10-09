# -*- coding: utf-8 -*-
"""CDP 环境探测（**只读**）。

本模块只做两件事：

1. 用 HTTP 读 ``/json/list`` 拿目标列表——纯 GET，不建立 WebSocket，
   因此不可能触发任何页面交互。
2. 从目标元数据（url / title）推断会话状态，产出
   :class:`taobao_publish.preflight.PageSnapshot` 所需的**页面事实**。

**不做的事**：不做 ``Runtime.evaluate``。页面内的深度勘察由 Node 探针负责
（``scripts/probe-publish-workbench.mjs``，复用 ``mcp-server/cdp-client.js``），
那里有成熟的 WebSocket 客户端，而 Python 侧标准库没有。

端口守卫：淘宝固定 9334，抖店固定 9333。连错实例会把抖店的登录态当成淘宝的用，
所以这里在建立任何连接**之前**就校验端口，而不是拿到结果再判断。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

from .constants import (
    LOGIN_URL_MARKERS,
    RISK_CONTROL_URL_MARKERS,
    TAOBAO_CDP_LIST_URL,
    TAOBAO_CDP_PORT,
)
from .errors import Blocker
from .preflight import PageSnapshot, host_of, is_allowed_host

#: 发布工作台的目标页标记，用于从多个标签页里挑出正确的那一个。
PUBLISH_TARGET_HINTS: Tuple[str, ...] = (
    "item.upload.taobao.com",
    "item.upload.tmall.com",
)


class CdpError(RuntimeError):
    """CDP 环境不可用。``code`` 对应 :mod:`taobao_publish.errors` 的错误码。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


#: 应用管理的桌面账户端口段（见 docs/06-阻塞项.md B-16）。
DESKTOP_ACCOUNT_PORT_RANGE: Tuple[int, int] = (9500, 9599)


def taobao_port_of(cdp_list_url: str) -> Optional[int]:
    """从调试地址里取出端口号；取不到返回 ``None``。"""

    match = re.search(r":(\d+)(?:/|$)", str(cdp_list_url or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:  # pragma: no cover - 正则已保证是数字
        return None


def is_taobao_port(cdp_list_url: str) -> bool:
    """这个调试端口是不是一个**允许的淘宝端口**。

    允许两类：

    * ``9334`` —— 本子项目的**研究会话**（独立 profile；抖店 9333 不可混用）；
    * ``9500-9599`` —— **应用管理的桌面账户**端口段。应用给每个店铺账户开一个
      独立 profile 与端口，`/api/shop/*` 走的就是这一段。

    真正防串店的是「标签页必须是 taobao.com / tmall.com」（见
    :func:`select_publish_target`），端口只是第二道提示。
    """

    port = taobao_port_of(cdp_list_url)
    if port is None:
        return False
    low, high = DESKTOP_ACCOUNT_PORT_RANGE
    return port == TAOBAO_CDP_PORT or low <= port <= high


def assert_taobao_port(cdp_list_url: str) -> None:
    """校验 CDP 端口确实是淘宝端口。

    抖店用 9333，淘宝用 9334 或桌面账户端口段 9500-9599。混用会拿到另一套登录态，
    属于**必须中止**的错误。
    """

    if is_taobao_port(cdp_list_url):
        return
    low, high = DESKTOP_ACCOUNT_PORT_RANGE
    raise CdpError(
        "WRONG_CDP_PORT",
        f"CDP 地址 {cdp_list_url!r} 不是淘宝端口；"
        f"研究用 {TAOBAO_CDP_PORT}，应用管理的桌面账户用 {low}-{high}，"
        f"抖店端口 9333 的登录态不能用于淘宝发布",
    )


def list_targets(
    cdp_list_url: str = TAOBAO_CDP_LIST_URL,
    *,
    timeout: float = 3.0,
    opener: Optional[Callable[..., Any]] = None,
) -> List[Dict[str, Any]]:
    """读取 CDP 目标列表。连不上时抛 :class:`CdpError`，**不返回空列表**。

    :param opener: 便于测试注入；默认用 ``urllib.request.urlopen``。
    """

    assert_taobao_port(cdp_list_url)
    open_fn = opener if opener is not None else urlopen
    request = Request(cdp_list_url, headers={"Accept": "application/json"})
    try:
        with open_fn(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except (URLError, OSError, ValueError) as exc:
        raise CdpError(
            "CDP_UNREACHABLE",
            f"无法连接 {cdp_list_url}：{exc}；"
            "请先用 protocol-research-taobao-20260908/scripts/start-taobao-cdp-chrome.mjs 启动",
        ) from exc

    try:
        payload = json.loads(raw) if raw.strip() else []
    except ValueError as exc:
        raise CdpError("CDP_UNREACHABLE", f"{cdp_list_url} 返回的不是 JSON：{exc}") from exc
    if not isinstance(payload, list):
        raise CdpError("CDP_UNREACHABLE", f"{cdp_list_url} 返回的 JSON 不是数组")
    return [item for item in payload if isinstance(item, Mapping)]


def select_publish_target(
    targets: Iterable[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """从目标列表里挑出发布工作台页面。

    只按 URL 命中，不看标题文案——标题会被平台改写，URL 更稳定。
    """

    pages = [item for item in targets if str(item.get("type") or "") == "page"]
    for hint in PUBLISH_TARGET_HINTS:
        for item in pages:
            if hint in str(item.get("url") or ""):
                return dict(item)
    return None


def select_any_taobao_target(
    targets: Iterable[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """挑出任一淘宝/天猫页面。用于「还没打开发布页，但登录态可能有效」的场景。"""

    pages = [item for item in targets if str(item.get("type") or "") == "page"]
    for item in pages:
        url = str(item.get("url") or "")
        if is_allowed_host(url):
            return dict(item)
    return None


@dataclass
class SessionProbe:
    """会话探测结果。``targets`` 只保留脱敏后的字段。"""

    cdp_list_url: str = ""
    target_count: int = 0
    publish_target_found: bool = False
    taobao_target_found: bool = False
    login_required: bool = False
    risk_control_hit: bool = False
    current_url: str = ""
    current_title: str = ""
    blockers: List[Blocker] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blockers

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cdp_list_url": self.cdp_list_url,
            "target_count": self.target_count,
            "publish_target_found": self.publish_target_found,
            "taobao_target_found": self.taobao_target_found,
            "login_required": self.login_required,
            "risk_control_hit": self.risk_control_hit,
            "current_host": host_of(self.current_url),
            "current_title": self.current_title,
            "notes": list(self.notes),
            "blockers": [item.to_dict() for item in self.blockers],
        }


def probe_session(
    cdp_list_url: str = TAOBAO_CDP_LIST_URL,
    *,
    timeout: float = 3.0,
    require_publish_page: bool = False,
    opener: Optional[Callable[..., Any]] = None,
    target_id: str = '',
) -> SessionProbe:
    """探测淘宝调试浏览器会话是否就绪。

    :param require_publish_page: 为 ``True`` 时，找不到发布工作台标签页即视为阻塞。
    """

    probe = SessionProbe(cdp_list_url=cdp_list_url)
    try:
        targets = list_targets(cdp_list_url, timeout=timeout, opener=opener)
    except CdpError as exc:
        probe.blockers.append(
            Blocker(
                code=exc.code,
                field="cdp",
                detail=str(exc),
                source="cdp.probe_session",
            )
        )
        return probe

    if target_id:
        targets = [target for target in targets if str(target.get('id') or '') == target_id]
    probe.target_count = len(targets)
    publish_target = select_publish_target(targets)
    any_target = select_any_taobao_target(targets)

    if publish_target is not None:
        probe.publish_target_found = True
    if any_target is not None:
        probe.taobao_target_found = True

    chosen = publish_target or any_target
    if chosen is not None:
        probe.current_url = str(chosen.get("url") or "")
        probe.current_title = str(chosen.get("title") or "")
    else:
        probe.notes.append("没有任何淘宝/天猫标签页；登录态无法确认")

    lower_url = probe.current_url.lower()
    probe.risk_control_hit = any(marker in lower_url for marker in RISK_CONTROL_URL_MARKERS)
    probe.login_required = any(marker in lower_url for marker in LOGIN_URL_MARKERS)

    if probe.risk_control_hit:
        probe.blockers.append(
            Blocker(
                code="RISK_CONTROL_HIT",
                field="cdp.target.url",
                detail="当前标签页 URL 命中风控标记；停止自动化，交由人工处理",
                source="cdp.probe_session",
            )
        )
    elif probe.login_required:
        probe.blockers.append(
            Blocker(
                code="LOGIN_REQUIRED",
                field="cdp.target.url",
                detail="当前标签页是登录页，需要在该 profile 里扫码登录一次",
                source="cdp.probe_session",
            )
        )
    elif require_publish_page and not probe.publish_target_found:
        probe.blockers.append(
            Blocker(
                code="WRONG_PAGE",
                field="cdp.target.url",
                detail="未找到发布工作台标签页（URL 未命中 " + " / ".join(PUBLISH_TARGET_HINTS) + "）",
                source="cdp.probe_session",
            )
        )

    return probe


def snapshot_from_probe(probe: SessionProbe) -> PageSnapshot:
    """把会话探测结果转成预检用的页面快照。

    注意：这只覆盖**能从 URL/标题推断**的事实。DOM 事实（工作台根节点、遮挡弹层）
    一律留成 ``None``（未评估）——本模块不做 ``Runtime.evaluate``，猜出来的
    ``True`` 会让预检误判为通过。要让它们变成 ``True``/``False``，必须由 Node 探针
    在页面内评估后回填。
    """

    return PageSnapshot(
        url=probe.current_url,
        title=probe.current_title,
        has_workbench_root=None,
        has_blocking_overlay=None,
        notes=list(probe.notes) + ["DOM 事实未评估（None），需由 Node 探针回填"],
    )

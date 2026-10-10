# -*- coding: utf-8 -*-
"""页面交互的最小 CDP 客户端。

只做三件事：连标签页、执行表达式、关掉。业务语义在 :mod:`taobao_publish.locating`
（定位）与 :mod:`taobao_publish.fillers`（写值）里。

## 为什么写值要这么麻烦

淘宝的表单是 React 受控组件。**直接给 ``input.value`` 赋值不会触发 onChange**，
React 的状态不会更新，界面上看着有字、提交时却是空的——这类「看起来成功、
其实没写进去」正是最难查的故障。

正确做法（实测可用，见 ``scripts/probe-category-search.py``）：

1. 取原生 setter：``Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set``
2. 用 ``setter.call(input, value)`` 赋值（绕过 React 的 value 劫持）
3. 派发 ``input`` 与 ``change`` 事件，让 React 收到通知

## 三次校验

写一个字段要过三关，任何一关不过就报错、**不继续**：

1. **定位唯一**：由 :func:`taobao_publish.locating.require_unique` 保证；
2. **控件可用**：必须存在且未被 ``disabled`` / ``readOnly``；
3. **回读一致**：写完立刻读回，与期望值不符即失败。

第 3 关是有意加的。表单可能格式化输入（去空格、改千分位、截断），
只报告「已写入」而不核对，就等于把「写进去了吗」这件事交给运气。
"""

from __future__ import annotations

import json
import hashlib
import re
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import parse_qs, urlsplit

from . import locating
from .constants import PUBLISH_FORM_URL, PUBLISH_FORM_CATEGORY_PARAM
from .errors import Blocker, TaobaoPublishError


class PageError(TaobaoPublishError):
    """页面交互失败。

    ⚠️ **与基类的参数顺序相反**：这里第一个参数是**消息**，不是错误码。

    踩过的坑：基类是 ``TaobaoPublishError(code, detail)``，而本模块一直按
    ``PageError("消息")`` 调用。于是那串消息被当成错误码送进 ``describe_error``，
    落到「未知错误码」分支——结果是**每个页面异常的 ``.code`` 都等于整条消息**，
    ``str()`` 永远显示「平台返回未归类错误」。

    子类都有类级 ``code``，实例化时不该再传错误码，所以这里把签名收窄成
    ``(detail, blockers)``，让「第一个参数是消息」成为**唯一**用法。
    """

    code = "PAGE_ERROR"

    def __init__(self, detail: str = "", blockers: Optional[Iterable] = None) -> None:
        super().__init__(type(self).code, detail, blockers)


class RendererHungError(PageError):
    """调试通道已连接，但页面执行线程无法响应。"""

    code = "RENDERER_HUNG"


class MediaSourceChangedError(PageError):
    """上传快照与本次素材身份不一致，尚未发送文件。"""

    code = "MEDIA_SOURCE_CHANGED"


class MediaImageMissing(PageError):
    """已完成图片卡片查找且没有目标；未知、歧义及未完成搜索不能当作不存在。"""

    code = "MEDIA_IMAGE_MISSING"


class FieldMismatchError(PageError):
    """回读值与期望值不一致。"""

    code = "FIELD_MISMATCH"


@dataclass
class PageClient:
    """连到一个标签页的最小客户端。

    用法::

        client = PageClient.connect(ws_url)
        try:
            value = client.evaluate("document.title")
        finally:
            client.close()
    """

    ws: Any
    target_url: str = ""

    @classmethod
    def connect(cls, ws_url: str, target_url: str = "", timeout: float = 8.0) -> "PageClient":
        try:
            import websocket
        except Exception as exc:  # pragma: no cover - 依赖缺失属于环境问题
            raise PageError("websocket 模块不可用：{}".format(exc)) from exc
        try:
            ws = websocket.create_connection(ws_url, timeout=timeout, suppress_origin=True)
        except Exception as exc:
            raise PageError("连不上标签页：{}".format(type(exc).__name__)) from exc
        ws.settimeout(2)
        return cls(ws=ws, target_url=target_url)

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001 - 关闭失败不影响结果
            pass

    def __enter__(self) -> "PageClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def send(self, method: str, params: Optional[Dict[str, Any]] = None,
             timeout: float = 15.0) -> Dict[str, Any]:
        """发一条原始 CDP 命令并等它的响应。

        ``evaluate`` 覆盖不到的命令（``DOM.setFileInputFiles``、``Page.getFrameTree`` …）
        走这里。事件消息会被丢弃——本方法只关心请求/响应配对。
        """

        self._counter = getattr(self, "_counter", 0) + 1
        message_id = self._counter
        self.ws.send(json.dumps({
            "id": message_id, "method": method, "params": params or {},
        }))
        deadline = time.time() + max(1.0, timeout)
        while time.time() < deadline:
            try:
                message = json.loads(self.ws.recv())
            except Exception:
                continue
            if message.get("id") != message_id:
                continue
            payload = message.get("result") or {}
            if message.get("error"):
                raise PageError("CDP {} 失败：{}".format(
                    method, str(message.get("error"))[:120]))
            return payload
        raise PageError("等待 CDP {} 响应超时".format(method))

    def evaluate(self, expression: str, timeout: float = 15.0,
                 context_id: Optional[int] = None) -> Any:
        """执行一段表达式并取回值。

        :param context_id: 指定执行上下文。**操作 iframe 时必须传**——
            不传就一直在主 frame 里跑，在 iframe 里找元素永远找不到。
            上下文 id 用 :meth:`find_frame_context` 拿。

        异常信息**只报类型**，不回显表达式内容——表达式里可能嵌了字段值。
        """

        self._counter = getattr(self, "_counter", 0) + 1
        message_id = self._counter
        params: Dict[str, Any] = {
            "expression": expression, "returnByValue": True, "awaitPromise": True,
        }
        if context_id is not None:
            params["contextId"] = context_id
        self.ws.send(json.dumps({
            "id": message_id, "method": "Runtime.evaluate", "params": params,
        }))
        deadline = time.time() + max(1.0, timeout)
        while time.time() < deadline:
            try:
                message = json.loads(self.ws.recv())
            except Exception:
                continue
            if message.get("id") != message_id:
                continue
            payload = message.get("result") or {}
            if payload.get("exceptionDetails"):
                raise PageError("页面内执行报错（表达式内容不在此回显）")
            return (payload.get("result") or {}).get("value")
        raise PageError("等待页面响应超时")

    def navigate(self, url: str, *, wait: float = 8.0, timeout: float = 25.0) -> Dict[str, Any]:
        """把当前标签页导航到指定 URL，并等它加载完。**会改变页面位置。**

        为什么放在客户端层：流水线**不能依赖「用户恰好停在某个页面」**——
        `select_category` 需要类目搜索页，而上一轮可能把页面留在了填写页。
        实测踩过：不自己导航就会报「当前不在类目搜索页（publish.htm?catId=…）」。
        """

        if not str(url or "").strip():
            raise PageError("导航目标为空")
        self.send("Page.enable", timeout=timeout)
        self.send("Page.navigate", {"url": str(url)}, timeout=timeout)
        time.sleep(max(1.0, wait))
        return {"ok": True, "url": str(url), "current": str(self.evaluate("location.href") or "")}

    def health_check(self, timeout: float = 5.0) -> bool:
        """渲染进程是否还能执行 JS。**只读，极轻量。**

        为什么需要它：反复导航 + 上传 + 选图之后，标签页的 JS 主线程可能被压垮——
        实测症状是 `Runtime.evaluate('1+1')` **超时**、
        `document.readyState` 返回 `null`、`Page.navigate` 也超时，
        CDP 已经救不回来（E-125）。

        没有这个检查时，卡死表现为一个光秃秃的「等待页面响应超时」——
        看的人分不清是**页面卡了**还是**选择器写错了**。
        有了它就能明确说「请重载该标签页」，而不是让人去翻选择器。
        """

        try:
            self._counter = getattr(self, "_counter", 0) + 1
            message_id = self._counter
            self.ws.send(json.dumps({
                "id": message_id, "method": "Runtime.evaluate",
                "params": {"expression": "1+1", "returnByValue": True},
            }))
            deadline = time.time() + max(1.0, timeout)
            while time.time() < deadline:
                try:
                    message = json.loads(self.ws.recv())
                except Exception:
                    continue
                if message.get("id") != message_id:
                    continue
                value = ((message.get("result") or {}).get("result") or {}).get("value")
                return value == 2
            return False
        except Exception:  # noqa: BLE001
            return False

    def frame_urls(self, timeout: float = 15.0) -> Dict[str, str]:
        """取 ``frameId → url`` 映射。"""

        payload = self.send("Page.getFrameTree", timeout=timeout)
        mapping: Dict[str, str] = {}

        def walk(node: Optional[Dict[str, Any]]) -> None:
            frame = (node or {}).get("frame") or {}
            if frame.get("id"):
                mapping[str(frame["id"])] = str(frame.get("url") or "")
            for child in (node or {}).get("childFrames") or []:
                walk(child)

        walk(payload.get("frameTree"))
        return mapping

    def find_frame_context(self, url_substring: str, *, timeout: float = 8.0) -> Optional[int]:
        """按 **frame URL 子串**找可用的执行上下文 id。

        ⚠️ **必须按 URL 匹配，不能按 origin**：实测 ``market.m.taobao.com`` 下有
        3 个 iframe（详情预览 / 服务大厅 / 素材中心），按 origin 会挑错，
        然后在错误的页面里找上传入口。

        ⚠️ **不能用 ``self.send("Runtime.enable")``**：``send`` 会丢弃沿途的事件，
        而 ``executionContextCreated`` 是在 ``Runtime.enable`` 的**响应之前**
        批量发出的——用 ``send`` 会把它们全丢掉（实测踩过：contexts 为空、
        于是报「找不到素材中心的执行上下文」，而 iframe 明明开着）。
        所以这里自己收事件，一边收一边等响应。
        """

        self._counter = getattr(self, "_counter", 0) + 1
        message_id = self._counter
        self.ws.send(json.dumps({
            "id": message_id, "method": "Runtime.enable", "params": {},
        }))

        contexts: Dict[str, int] = {}
        deadline = time.time() + max(1.0, timeout)
        while time.time() < deadline:
            try:
                message = json.loads(self.ws.recv())
            except Exception:
                continue
            if message.get("id") == message_id:
                # 响应到了。事件通常已在此之前发完，再收一小轮就够。
                break
            if message.get("method") != "Runtime.executionContextCreated":
                continue
            context = (message.get("params") or {}).get("context") or {}
            aux = context.get("auxData") or {}
            if not aux.get("isDefault"):
                continue
            frame_id = str(aux.get("frameId") or "")
            if frame_id:
                contexts[frame_id] = int(context.get("id"))

        wanted = str(url_substring or "")
        mapping = self.frame_urls(timeout=timeout)
        for frame_id, context_id in contexts.items():
            if wanted and wanted in mapping.get(frame_id, ""):
                return context_id
        return None

    def frame_id_for_url(self, url_substring: str, *, timeout: float = 10.0) -> Optional[str]:
        """按 URL 子串找 frameId。"""

        wanted = str(url_substring or "")
        for frame_id, url in self.frame_urls(timeout=timeout).items():
            if wanted and wanted in url:
                return frame_id
        return None

    def create_frame_context(self, frame_id: str, *, timeout: float = 10.0) -> int:
        """为一个 frame **新建**执行上下文并返回 id（``Page.createIsolatedWorld``）。

        这是 :meth:`find_frame_context` 的**确定性后备**：不依赖事件时序，
        直接按 frameId 拿上下文。

        代价：隔离世界拿不到页面自己的 JS 全局变量（React 内部对象等），
        但 DOM 查询与 ``element.click()`` 照常工作——本子项目对 iframe 只需要这两件事。
        """

        payload = self.send("Page.createIsolatedWorld", {
            "frameId": frame_id, "grantUniveralAccess": False, "worldName": "taobao-publish",
        }, timeout=timeout)
        context_id = payload.get("executionContextId")
        if not context_id:
            raise PageError("为 frame {} 建上下文失败".format(str(frame_id)[:16]))
        return int(context_id)

    def set_file_input_files(self, files: Sequence[str], selector: str,
                             *, context_id: Optional[int] = None,
                             timeout: float = 20.0) -> Dict[str, Any]:
        """往 ``<input type="file">`` 塞文件（``DOM.setFileInputFiles``）。

        绕开原生文件选择框——这正是自动化上传的关键。

        路径：``Runtime.evaluate`` 拿到元素对象 → ``DOM.requestNode`` 换 nodeId
        → ``DOM.setFileInputFiles``。

        :param context_id: file input 所在 frame 的上下文；在 iframe 里时必须传
        """

        if not files:
            raise PageError("没有要上传的文件")
        self.send("DOM.enable", timeout=timeout)
        expression = build_query_element_expression(selector)

        self._counter = getattr(self, "_counter", 0) + 1
        message_id = self._counter
        params: Dict[str, Any] = {
            "expression": expression, "returnByValue": False, "awaitPromise": True,
        }
        if context_id is not None:
            params["contextId"] = context_id
        self.ws.send(json.dumps({
            "id": message_id, "method": "Runtime.evaluate", "params": params,
        }))
        remote = None
        deadline = time.time() + max(1.0, timeout)
        while time.time() < deadline:
            try:
                message = json.loads(self.ws.recv())
            except Exception:
                continue
            if message.get("id") != message_id:
                continue
            payload = message.get("result") or {}
            if payload.get("exceptionDetails"):
                raise PageError("在目标 frame 里找 {!r} 时报错".format(selector))
            remote = (payload.get("result") or {}).get("objectId")
            break
        if not remote:
            raise CandidateNotFound("目标 frame 里没有 {!r}".format(selector))

        # ``DOM.setFileInputFiles`` 接受 nodeId / backendNodeId / **objectId** 三者之一。
        # 优先直接用 objectId：实测这里的 file input 在 **iframe 的隔离世界**里，
        # ``DOM.requestNode`` 对它拿不到 nodeId（返回空），报「拿不到 nodeId」。
        payload = {"files": [str(p) for p in files], "objectId": remote}
        try:
            self.send("DOM.setFileInputFiles", payload, timeout=timeout)
            return {"ok": True, "via": "objectId", "fileCount": len(files)}
        except PageError:
            # 退一步：换 nodeId 再试。某些 CDP 版本对 objectId 支持不完整。
            node = self.send("DOM.requestNode", {"objectId": remote}, timeout=timeout)
            node_id = node.get("nodeId")
            if not node_id:
                raise PageError("拿不到 {!r} 的 nodeId，也无法用 objectId 直接设置".format(selector))
            self.send("DOM.setFileInputFiles", {
                "files": [str(p) for p in files], "nodeId": node_id,
            }, timeout=timeout)
            return {"ok": True, "via": "nodeId", "nodeId": node_id, "fileCount": len(files)}


# ---------------------------------------------------------------------------
# 值写入
# ---------------------------------------------------------------------------
#: 把值写进 ``control`` 并让 React 收到通知。``VALUE_JSON`` 是占位符。
_SET_VALUE_ACTION = """
const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
setter.call(control, {value});
control.dispatchEvent(new Event('input', {{ bubbles: true }}));
control.dispatchEvent(new Event('change', {{ bubbles: true }}));
"""

#: 读回行内控件的当前值。用**局部变量**而不是挂到 ``window`` 上——
#: 写全局会在用户页面上留下痕迹，而这个模块的原则是尽量不碰页面之外的任何东西。
_READ_VALUE_ACTION = "const readBack = control ? String(control.value) : null;"


def _value_literal(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("字段值必须是字符串")
    return json.dumps(value, ensure_ascii=False)


def build_set_expression(label: str, value: str) -> str:
    """生成「按标签定位行 → 写值」的页面表达式。"""

    action = _SET_VALUE_ACTION.format(value=_value_literal(value))
    return locating.operate_row_expression(label, action)


def build_read_expression(label: str) -> str:
    """生成「按标签定位行 → 读回值」的页面表达式。"""

    action = locating.operate_row_expression(label, _READ_VALUE_ACTION)
    # operate_row_expression 的返回值是固定结构，把读回值并进去
    return action.replace(
        "return { ok: true, label: LABEL };",
        "return { ok: true, label: LABEL, value: readBack };",
    )


def _check_result(payload: Any, label: str) -> Dict[str, Any]:
    """把页面返回的 ``{ok, reason, ...}`` 转成结果或异常。"""

    if not isinstance(payload, dict):
        raise PageError("定位标签 {!r} 时页面没有返回可解析的结果".format(label))
    if payload.get("ok") is True:
        return payload
    reason = str(payload.get("reason") or "unknown")
    hit_count = payload.get("hitCount")
    if reason == "label_not_found":
        raise locating.LabelNotFound("标签 {!r} 没有定位到行".format(label))
    if reason == "label_ambiguous":
        raise locating.LabelAmbiguous(
            "标签 {!r} 定位到 {} 行，拒绝写入".format(label, hit_count))
    raise PageError("定位标签 {!r} 失败：{}".format(label, reason))


def read_text_field(client: PageClient, label: str) -> Optional[str]:
    """按标签读回行内控件的当前值。定位不唯一时抛错。"""

    payload = client.evaluate(build_read_expression(label))
    result = _check_result(payload, label)
    value = result.get("value")
    return None if value is None else str(value)



def build_read_selected_options_expression(label: str) -> str:
    """生成「读被选中的单选项 / 复选项文字」的表达式。

    ⚠️ **为什么要提成命名构造器**（而不是内联 `evaluate`）。

    仓库的约定是表达式集中在 `build_*_expression()` 里——
    `ARG_CASES` 构造器冒烟与动作守卫审计都靠这个约定。
    内联的话那些门覆盖不到，`test_inline_evaluate_calls_are_extracted` 会直接失败。

    实测结构（2026-10-03）：选项文字**不在** `closest('label')` 上——
    那一层是空的 `label.next-radio-wrapper`，文字在再往上一层的 `label` 里。
    所以要**逐级往上走到有文字为止**。
    """

    return """
    (() => {
      const LABEL = %s;
      // ⚠️ **两套行结构都要试**——第 58 轮实测：行结构取决于**怎么到页面的**：
      //   直接导航到 publish.htm?catId=…  → `.sell-catProp-item-common`
      //   经 select_category 走到填写页   → `.sell-component-info-wrapper-wrap`
      //
      // 只试一套的话，单独测能读到、**链条里读不到**（实测栽过：
      // 单独测读到 ['立刻上架']，链条第里全是空）。
      // `classify_row` 早就用 ROW_PROFILE_ORDER 两套都试了，这里跟上。
      const PROFILES = [
        { row: '.sell-component-info-wrapper-wrap',
          label: '.sell-component-info-wrapper-label' },
        { row: '.sell-catProp-item-common',
          label: '.sell-catProp-item-common-label, label' },
      ];
      let row = null;
      for (const profile of PROFILES) {
        for (const r of document.querySelectorAll(profile.row)) {
          const lab = r.querySelector(profile.label);
          const text = lab ? (lab.textContent || '').replace(/\\*/g, '').trim() : '';
          if (text === LABEL) { row = r; break; }
        }
        if (row) break;
      }
      if (!row) return { ok: false, reason: 'row_not_found', tried: PROFILES.length };
      const picked = [];
      for (const input of row.querySelectorAll('input[type=radio], input[type=checkbox]')) {
        if (input.checked !== true) continue;
        // ⚠️ **往上走到有文字为止，不要停在第一个 label 上。**
        //
        //   实测结构：
        //     depth 0 input.next-radio-input            ""
        //     depth 1 span.next-radio.checked           ""
        //     depth 2 label.next-radio-wrapper.checked  ""       ← 停在第一个 label 上
        //     depth 3 label                             "按商品统一设置"  ← 文字在这
        //
        //   停在 depth 2 会读出空串，而空串会被当成「没选中任何项」——
        //   「读不到」与「没有」是两回事。
        let text = '';
        let node = input;
        for (let depth = 0; depth < 5 && node; depth++) {
          const candidate = (node.textContent || '').replace(/\\s+/g, ' ').trim();
          if (candidate) { text = candidate; break; }
          node = node.parentElement;
        }
        if (text) picked.push(text.slice(0, 40));
      }
      return { ok: true, picked };
    })()
    """ % __import__("json").dumps(label, ensure_ascii=False)


def read_selected_options(client: "PageClient", label: str) -> List[str]:
    """读一行里**被选中的**单选项 / 复选项的文字。

    ⚠️ **为什么要单独一个函数。**

    实测（2026-10-03）：「发货时间」是两组单选（按商品统一设置/按规格单独设置
    + 四档发货时效），6 个 ``input[type=radio]`` 且 ``value`` 全是 ``'on'``。

    **``value`` 读不出选中状态**——``'on'`` 对 radio 是默认值。
    要判「哪个被选了」必须看 ``checked``，而选中项的文字在它旁边那个 label 里。

    读不到返回空列表（调用方据此如实说明「没读到」）。
    """

    payload = client.evaluate(build_read_selected_options_expression(label))

    if not isinstance(payload, dict) or not payload.get("ok"):
        return []
    return [str(t) for t in (payload.get("picked") or []) if str(t).strip()]


def classify_row(client: "PageClient", label: str) -> Dict[str, Any]:
    """按标签定位一行，并判断它的控件**能不能用文本方式写**。

    依次尝试 :data:`locating.ROW_PROFILE_ORDER` 里的组合——
    发布页的普通字段与类目属性行用的是**两套结构**，只试一套会漏。

    :return: ``{'located': bool, 'profile': str, 'controlCount': int, 'kind': str}``；
        ``kind`` 取 ``'text'`` / ``'combobox'`` / ``'no_control'`` / ``'not_located'``。
    """

    from . import locating

    for profile in locating.ROW_PROFILE_ORDER:
        try:
            payload = client.evaluate(locating.locate_row_expression(label, profile))
        except Exception:  # noqa: BLE001 - 定位本身失败按「这个组合没有」处理
            continue
        if not isinstance(payload, dict) or not payload.get("hitCount"):
            continue
        if int(payload.get("hitCount") or 0) != 1:
            # 命中多行——**不能挑一行写**（那是猜）。交给调用方按歧义处理。
            return {"located": True, "profile": profile.name,
                    "controlCount": int(payload.get("controlCount") or 0),
                    "kind": "ambiguous", "hitCount": int(payload.get("hitCount") or 0)}
        controls = payload.get("controls") or []
        roles = {str(c.get("role") or "") for c in controls}
        tags = {str(c.get("tag") or "") for c in controls}
        types = {str(c.get("type") or "").lower() for c in controls}
        if not controls:
            kind = "no_control"
        elif "combobox" in roles:
            # **可搜索下拉**：往里打字不会提交值，必须从候选项里选。
            kind = "combobox"
        elif tags and tags <= {"input"} and types and types <= {"radio", "checkbox"}:
            # ⚠️ **选项组，不是文本框。**
            #
            # 实测（2026-10-03）：「发货时间」是两组单选，6 个 `input[type=radio]`
            # 且 `value` 全是 `'on'`。原先它落到下面的 `text` 分支——
            # 拿 `fill_text_field` 去写它会写到一个 `value='on'` 的 radio 上，
            # **毫无意义，而回读还可能"看起来设上了"**。
            #
            # 选它需要**按文字点对应的那个选项**，与填文本是两回事。
            kind = "choice"
        elif tags & {"input", "textarea"}:
            kind = "text"
        else:
            kind = "no_control"
        return {"located": True, "profile": profile.name,
                "controlCount": int(payload.get("controlCount") or len(controls)),
                "kind": kind, "hitCount": 1}
    return {"located": False, "profile": "", "controlCount": 0, "kind": "not_located"}


def fill_text_field(
    client: PageClient,
    label: str,
    value: str,
    *,
    verify: bool = True,
) -> Dict[str, Any]:
    """按标签把一个文本值写进去，并**回读校验**。

    :raises locating.LabelNotFound: 标签没有定位到行
    :raises locating.LabelAmbiguous: 标签定位到多行——拒绝写入
    :raises FieldMismatchError: 回读值与期望值不符

    :return: ``{'label', 'written', 'read_back'}``
    """

    payload = client.evaluate(build_set_expression(label, value))
    _check_result(payload, label)

    if not verify:
        return {"label": label, "written": value, "read_back": None}

    read_back = read_text_field(client, label)
    if read_back != value:
        # 表单可能做了格式化，也可能根本没接受这个值。两种都算失败：
        # 只报告「已写入」而不核对，等于把「写进去了吗」交给运气。
        raise FieldMismatchError(
            "字段 {!r} 回读不一致：期望 {!r}，实际 {!r}".format(label, value, read_back)
        )
    return {"label": label, "written": value, "read_back": read_back}


def blockers_for(exc: Exception, *, stage: str) -> list:
    """把页面异常转成结构化 blocker，供阶段返回。"""

    code = getattr(exc, "code", "PAGE_ERROR")
    if isinstance(exc, locating.LabelNotFound):
        code = "EVIDENCE_INSUFFICIENT"
    elif isinstance(exc, locating.LabelAmbiguous):
        code = "SELECTOR_AMBIGUOUS"
    return [Blocker(
        code=code,
        field="",
        detail="{}（阶段 {}）".format(str(exc), stage),
        source="taobao_publish.page",
    )]


# ---------------------------------------------------------------------------
# 类目搜索页 / 下拉选择
# ---------------------------------------------------------------------------
#: 类目候选的**可点击元素**。
#:
#: ⚠️ 实测教训：事件处理器在**文本元素自己**身上，不在祖先卡片上。
#: 点 ``.result-item`` / ``.wrap`` 不会报错、也没有任何效果（无网络请求、URL 不变、
#: 按钮状态不变）——「静默无效」是最难查的一类失败。
CATEGORY_CANDIDATE_SELECTOR = ".sell-rich-text.path-text"

#: 类目候选的文本容器（用于读取候选列表本身，不用于点击）。
CATEGORY_CANDIDATE_PATH_SELECTOR = ".sell-component-general-category-result-cate-path"

#: 品牌下拉的选项根、选项元素、选项文本、搜索框。全部为语义类名（非哈希）。
BRAND_OPTIONS_ROOT = ".sell-o-select-options"
BRAND_OPTION_ITEM = ".options-item"
BRAND_OPTION_TEXT = ".info-content"
BRAND_SEARCH_INPUT = ".options-search input"


class CandidateNotFound(PageError):
    """按文本没有唯一定位到目标元素。"""

    code = "CANDIDATE_NOT_FOUND"


def build_click_unique_text_expression(selector: str, text: str, *, contains: bool = False) -> str:
    """生成「按文本唯一定位并点击」的表达式。

    ``contains=False``（默认）要求**精确相等**。类目路径这种「选错就发错类目」的场景
    必须精确匹配——用包含匹配会让 ``一次性袜子`` 同时命中两个候选。
    """

    if not isinstance(selector, str) or not selector.strip():
        raise ValueError("selector 不能为空")
    literal = _value_literal(text)
    match = "t.includes(TEXT)" if contains else "t === TEXT"
    return """
(() => {{
  const TEXT = {text_literal};
  const els = Array.from(document.querySelectorAll({selector_literal}));
  const hits = els.filter(el => {{ const t = (el.textContent || '').trim(); return {match_js}; }});
  // 同一候选可能同时命中内外两层（文本相同）——按包含关系去重，保留最内层
  const unique = [];
  for (const el of hits) {{
    if (!unique.some(other => other.contains(el) || el.contains(other))) unique.push(el);
  }}
  if (unique.length !== 1) {{
    return {{ ok: false, reason: unique.length === 0 ? 'no_match' : 'ambiguous',
              hitCount: unique.length,
              seen: els.map(e => (e.textContent || '').trim().slice(0, 60)) }};
  }}
  const target = unique[0];
  target.click();
  return {{ ok: true, clickedText: (target.textContent || '').trim(),
           clickedClass: typeof target.className === 'string' ? target.className.slice(0, 120) : '' }};
}})()
""".format(
        text_literal=literal,
        selector_literal=json.dumps(selector),
        match_js=match,
    )


def click_unique_text(
    client: "PageClient", selector: str, text: str, *, contains: bool = False
) -> Dict[str, Any]:
    """按文本唯一定位并点击。命中 0 或多个都抛错——**绝不猜一个点下去**。"""

    payload = client.evaluate(build_click_unique_text_expression(selector, text, contains=contains))
    if not isinstance(payload, dict):
        raise PageError("点击 {!r} 时页面没有返回可解析的结果".format(text))
    if payload.get("ok") is True:
        return payload
    reason = str(payload.get("reason") or "unknown")
    hit_count = payload.get("hitCount")
    if reason == "no_match":
        raise CandidateNotFound(
            "没有找到文本为 {!r} 的元素（选择器 {}）".format(text, selector))
    if reason == "ambiguous":
        raise locating.LabelAmbiguous(
            "文本 {!r} 命中 {} 个元素，拒绝点击".format(text, hit_count))
    raise PageError("点击 {!r} 失败：{}".format(text, reason))


# 用户指定默认“无品牌”；已归档的平台原文也包含“无品牌/无注册商标”。
NO_BRAND_LABELS = ('无品牌', '无品牌/无注册商标')


def _visible_brand_rows_js():
    return r"""
  const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const rows = Array.from(document.querySelectorAll('.sell-catProp-item-common')).filter(row => {
    const label = row.querySelector('label');
    return visible(row) && label && (label.textContent || '').replace(/[\s*＊]/g, '') === '品牌';
  });
"""


def build_read_brand_control_expression():
    return '(() => {' + _visible_brand_rows_js() + r"""
      return {present: rows.length > 0, hitCount: rows.length};
    })()"""


def read_brand_control_state(client):
    payload = client.evaluate(build_read_brand_control_expression())
    if (not isinstance(payload, dict) or type(payload.get('present')) is not bool
            or type(payload.get('hitCount')) is not int or payload['hitCount'] < 0
            or payload['present'] != (payload['hitCount'] > 0)):
        raise PageError('无法确认当前类目页是否存在品牌控件')
    return payload


def build_select_brand_expression(brand_name: str) -> str:
    """只打开唯一可见品牌行；保留 readonly 下拉触发器，拒绝禁用控件。"""
    return '(() => {' + _visible_brand_rows_js() + r"""
      if (rows.length !== 1) return {ok: false, reason: rows.length ? 'ambiguous' : 'not_found', hitCount: rows.length};
      const inputs = Array.from(rows[0].querySelectorAll('input')).filter(visible);
      if (inputs.length !== 1) return {ok: false, reason: 'trigger_not_unique'};
      const trigger = inputs[0];
      if (trigger.disabled || trigger.getAttribute('aria-disabled') === 'true') return {ok: false, reason: 'trigger_disabled'};
      trigger.click(); trigger.focus();
      return {ok: true, step: 'opened'};
    })()"""


def build_pick_brand_option_expression(brand_name: str) -> str:
    """默认无品牌只接受两个已知原文；显式品牌保留精确匹配。"""
    names = [brand_name]
    if brand_name in NO_BRAND_LABELS:
        names.extend(name for name in NO_BRAND_LABELS if name != brand_name)
    return '(() => {' + 'const NAMES = ' + json.dumps(names, ensure_ascii=False) + r""";
      const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
      const roots = Array.from(document.querySelectorAll('.sell-o-select-options')).filter(visible);
      if (roots.length !== 1) return {ok: false, reason: 'options_root_not_unique'};
      const items = Array.from(roots[0].querySelectorAll('.options-item')).filter(visible);
      const text = item => { const el = item.querySelector('.info-content'); return el ? (el.textContent || '').trim() : ''; };
      for (const name of NAMES) {
        const hits = items.filter(item => text(item) === name);
        if (hits.length > 1) return {ok: false, reason: 'ambiguous', hitCount: hits.length};
        if (hits.length === 1) {
          const item = hits[0];
          if (item.disabled || item.getAttribute('aria-disabled') === 'true') return {ok: false, reason: 'option_disabled'};
          item.click();
          return {ok: true, picked: name};
        }
      }
      return {ok: false, reason: 'no_match', hitCount: 0, shown: items.map(text).filter(Boolean).slice(0, 12)};
    })()"""


def build_search_in_brand_dropdown_expression(text: str) -> str:
    """生成「在下拉搜索框里输入关键词」的表达式（同样要触发 React 的 onChange）。"""

    literal = _value_literal(text)
    return """
(() => {{
  const TEXT = {text_literal};
  const input = document.querySelector({search_input});
  if (!input) return {{ ok: false, reason: 'no_search_input' }};
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(input, TEXT);
  input.dispatchEvent(new Event('input', {{ bubbles: true }}));
  input.dispatchEvent(new Event('change', {{ bubbles: true }}));
  return {{ ok: true, typed: TEXT }};
}})()
""".format(
        text_literal=literal,
        search_input=json.dumps(BRAND_SEARCH_INPUT),
    )


def select_brand(client: "PageClient", brand_name: str, *, wait: float = 1.5) -> Dict[str, Any]:
    """在下拉里选中品牌。

    流程：展开 → （可选）在搜索框输入 → 点中文本精确等于品牌名的选项。

    **精确匹配**：品牌选错会直接导致商品挂错品牌，属于「发出去才发现」的错误。
    命中 0 或多数都拒绝，不做「最接近」的妥协。
    """

    opened = client.evaluate(build_select_brand_expression(brand_name))
    if not isinstance(opened, dict) or not opened.get("ok"):
        raise CandidateNotFound(
            "展开品牌下拉失败：{}".format(json.dumps(opened, ensure_ascii=False)[:160]))

    time.sleep(wait)
    client.evaluate(build_search_in_brand_dropdown_expression(brand_name))
    time.sleep(wait)

    picked = client.evaluate(build_pick_brand_option_expression(brand_name))
    if not isinstance(picked, dict):
        raise PageError("选择品牌 {!r} 时页面没有返回可解析的结果".format(brand_name))
    if not picked.get("ok"):
        # 搜过还是没命中，报出当时可见的选项，便于判断是名字不对还是列表没刷新
        raise CandidateNotFound(
            "品牌 {!r} 未在下拉中精确命中（{}）；当时可见：{}".format(
                brand_name, picked.get("reason"),
                "、".join(picked.get("shown") or []) or "（空）"))
    allowed = NO_BRAND_LABELS if brand_name in NO_BRAND_LABELS else (brand_name,)
    if picked.get('picked') not in allowed:
        raise PageError('品牌点击没有返回本次对应的候选原文')
    return picked


# ---------------------------------------------------------------------------
# 类目搜索页的四个动作
# ---------------------------------------------------------------------------
#: 搜索发品输入框。实测 placeholder 为「可输入产品名称、类目关键词、条码信息」。
CATEGORY_SEARCH_INPUT = 'input[placeholder*="可输入产品名称"]'

#: 「确认，下一步」按钮文本。实测选中类目且填了品牌之前一直是 disabled。
CONFIRM_NEXT_TEXT = "确认，下一步"


def build_search_category_expression(keyword: str) -> str:
    """搜索发品：填关键词并点「搜索」。

    ⚠️ 原先是内联在 `search_category` 里的三引号表达式。它**碰巧写对了**花括号，
    但不在命名构造器里，`tests/check_all_builders.py` 覆盖不到——
    下一次改动就可能引入单花括号而没人发现。提出来是为了让静态检查保持零豁免。
    """

    return """
(() => {{
  const KEYWORD = {keyword};
  const input = document.querySelector({input_sel});
  if (!input) return {{ ok: false, reason: 'no_search_input' }};
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(input, KEYWORD);
  input.dispatchEvent(new Event('input', {{ bubbles: true }}));
  input.dispatchEvent(new Event('change', {{ bubbles: true }}));
  const btn = Array.from(document.querySelectorAll('button'))
.find(b => (b.textContent || '').trim() === '搜索');
  if (!btn) return {{ ok: false, reason: 'no_search_button' }};
  if (btn.disabled) return {{ ok: false, reason: 'search_button_disabled' }};
  btn.click();
  return {{ ok: true, keyword: KEYWORD }};
}})()
""".format(keyword=_value_literal(keyword), input_sel=json.dumps(CATEGORY_SEARCH_INPUT))


def search_category(client: "PageClient", keyword: str) -> Dict[str, Any]:
    """在「搜索发品」框里输入关键词并点「搜索」。"""

    expression = build_search_category_expression(keyword)

    payload = client.evaluate(expression)
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise PageError("搜索发品失败：{}".format(
            json.dumps(payload, ensure_ascii=False)[:160] if payload else "无返回"))
    time.sleep(3.0)
    return {"step": "search", "keyword": keyword}


def build_switch_category_tab_expression(tab_name: str) -> str:
    """切到类目页的结果 tab。

    ⚠️ 原先是内联在 `switch_category_tab` 里的三引号表达式。它**碰巧写对了**花括号，
    但不在命名构造器里，`tests/check_all_builders.py` 覆盖不到——
    下一次改动就可能引入单花括号而没人发现。提出来是为了让静态检查保持零豁免。
    """

    return """
(() => {{
  const NAME = {name};
  const tabs = Array.from(document.querySelectorAll('[role="tab"], li.next-tabs-tab'));
  const hits = tabs.filter(t => (t.textContent || '').trim() === NAME);
  if (hits.length !== 1) {{
return {{ ok: false, reason: hits.length === 0 ? 'no_match' : 'ambiguous',
          hitCount: hits.length,
          tabs: tabs.map(t => (t.textContent || '').trim()).filter(Boolean) }};
  }}
  hits[0].click();
  return {{ ok: true, tab: NAME }};
}})()
""".format(name=_value_literal(tab_name))


def switch_category_tab(client: "PageClient", tab_name: str) -> Dict[str, Any]:
    """切到类目页的结果 tab（全部 / 类目 / 我的商品）。"""

    expression = build_switch_category_tab_expression(tab_name)

    payload = client.evaluate(expression)
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise PageError("切换 tab {!r} 失败：{}".format(
            tab_name, json.dumps(payload, ensure_ascii=False)[:160] if payload else "无返回"))
    time.sleep(3.0)
    return {"step": "switch_tab", "tab": tab_name}


def build_find_exact_candidate_expression(path_text: str) -> str:
    """按完整路径精确匹配类目候选。

    ⚠️ 原先是内联在 `find_exact_category_candidate` 里的三引号表达式。它**碰巧写对了**花括号，
    但不在命名构造器里，`tests/check_all_builders.py` 覆盖不到——
    下一次改动就可能引入单花括号而没人发现。提出来是为了让静态检查保持零豁免。
    """

    return """
(() => {{
  const TARGET = {target};
  const SEl = {path_sel};
  const els = Array.from(document.querySelectorAll(SEl));
  const texts = els.map(e => (e.textContent || '').trim());
  const hits = texts.filter(t => t === TARGET);
  return {{ target: TARGET, hitCount: hits.length, candidates: texts }};
}})()
""".format(target=_value_literal(path_text), path_sel=json.dumps(CATEGORY_CANDIDATE_PATH_SELECTOR))


def find_exact_category_candidate(client: "PageClient", path_text: str) -> Dict[str, Any]:
    """在候选里找**完整路径精确相等**的那一个。命中 0 或多个都抛错。

    为什么必须精确：实测「一次性袜子」同时是
    ``户外/登山/野营/旅行用品>…>一次性袜子`` 与
    ``女士内衣/男士内衣/家居服>…>一次性袜子`` 的结尾，
    用包含匹配会随机命中其中一个——**发错类目**。
    """

    expression = build_find_exact_candidate_expression(path_text)

    payload = client.evaluate(expression)
    if not isinstance(payload, dict):
        raise PageError("读取类目候选失败")
    if payload.get("hitCount") != 1:
        candidates = payload.get("candidates") or []
        raise CandidateNotFound(
            "目标类目 {!r} 在候选里精确命中 {} 个；当前候选项 {} 个：{}".format(
                path_text, payload.get("hitCount"), len(candidates),
                "；".join(candidates[:9]) or "（空）"))
    return payload


def find_leaf_category_candidate(client: "PageClient", leaf_name: str) -> Dict[str, Any]:
    """从实际搜索候选中按末级名称唯一匹配，完整路径只取页面原文。"""

    leaf_name = str(leaf_name or "").strip()
    if not leaf_name:
        raise CandidateNotFound("没有明确的末级类目名称，无法选择候选")
    # 与完整路径查询使用同一来源；读取候选不会点击或替用户推断上级类目。
    payload = client.evaluate(build_find_exact_candidate_expression(leaf_name))
    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
        raise PageError("读取类目候选失败")
    candidates = payload["candidates"]
    if any(not isinstance(text, str) for text in candidates):
        raise PageError("类目候选不是有效路径文本")
    hits = []
    for text in candidates:
        path = [segment.strip() for segment in text.split(">")]
        if path[-1] == leaf_name:
            if any(not segment for segment in path):
                raise PageError("匹配到的类目候选包含空路径段，无法确认完整路径")
            hits.append({"path_text": text, "path": path})
    if len(hits) != 1:
        raise CandidateNotFound(
            "末级类目 {!r} 在候选里精确命中 {} 个；需要唯一完整路径，当前候选：{}".format(
                leaf_name, len(hits), "；".join(candidates[:9]) or "（空）"))
    return dict(hits[0], target=leaf_name, hitCount=1, candidates=candidates)


def read_selected_category(client: "PageClient") -> List[str]:
    """读回已选中的类目面包屑（实测渲染为 ``.category-item.selected``）。"""

    payload = client.evaluate(
        "JSON.stringify(Array.from(document.querySelectorAll('.category-item.selected'))"
        ".map(e => (e.textContent || '').trim()))"
    )
    if not isinstance(payload, str):
        return []
    try:
        value = json.loads(payload)
    except Exception:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def wait_for_selected_category(
    client: "PageClient", expected: List[str], *, timeout: float = 10.0, interval: float = 0.6
) -> List[str]:
    """等到面包屑渲染出期望的类目，返回最后一次读到的结果。

    **不能点完立刻读**：React 渲染面包屑需要时间。实测「点完马上读」会拿到空数组，
    看起来像是点击没生效——而实际上是读早了。这类竞态会让人误以为是选择逻辑坏了，
    进而去改本来正确的点击代码。

    轮询而不是固定 sleep：弱网下固定等待会误判成失败，快的时候又白白多等。
    """

    deadline = time.time() + max(1.0, timeout)
    selected: List[str] = []
    while time.time() < deadline:
        selected = read_selected_category(client)
        if selected == expected:
            return selected
        time.sleep(interval)
    return selected


def build_read_confirm_button_expression() -> str:
    """读「确认，下一步」的可用状态。

    ⚠️ 原先是内联在 `read_confirm_button_state` 里的三引号表达式。它**碰巧写对了**花括号，
    但不在命名构造器里，`tests/check_all_builders.py` 覆盖不到——
    下一次改动就可能引入单花括号而没人发现。提出来是为了让静态检查保持零豁免。
    """

    return """
(() => {{
  const TEXT = {text};
  const btns = Array.from(document.querySelectorAll('button'))
.filter(b => (b.textContent || '').trim() === TEXT);
  if (btns.length !== 1) return {{ present: false, hitCount: btns.length }};
  const r = btns[0].getBoundingClientRect();
  return {{ present: true, disabled: btns[0].disabled === true,
       visible: r.width > 0 && r.height > 0 }};
}})()
""".format(text=_value_literal(CONFIRM_NEXT_TEXT))


def read_confirm_button_state(client: "PageClient") -> Dict[str, Any]:
    """读「确认，下一步」的可用状态。找不到按钮时 ``present=False``。"""

    expression = build_read_confirm_button_expression()

    payload = client.evaluate(expression)
    return payload if isinstance(payload, dict) else {"present": False}


def wait_for_confirm_button(client, *, timeout=8.0, interval=0.2):
    """品牌点击后等待页面重渲染完成，只观察按钮，不重复点击品牌。"""
    deadline = time.monotonic() + max(0.1, timeout)
    state = {}
    while True:
        state = read_confirm_button_state(client)
        if state.get('present') is True and state.get('visible') is True and state.get('disabled') is False:
            return state
        if time.monotonic() >= deadline:
            return state
        time.sleep(interval)


def build_click_confirm_next_expression() -> str:
    """生成「点击确认，下一步」的表达式。

    单独提成函数是有原因的：这段原先内联在 :func:`confirm_category_and_read_id` 里，
    开头写成了单花括号 ``(() => {``，``str.format`` 会直接抛
    ``unexpected '{' in field name``。内联时它不在任何单测的覆盖范围内——
    提出来之后 :mod:`tests.test_page_and_fill_stages` 能直接调到它。
    """

    return """
(() => {{
  const TEXT = {text};
  const btns = Array.from(document.querySelectorAll('button'))
    .filter(b => (b.textContent || '').trim() === TEXT);
  if (btns.length !== 1 || btns[0].disabled) return {{ ok: false, hitCount: btns.length }};
  const rect = btns[0].getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return {{ ok: false, reason: 'not_visible' }};
  btns[0].click();
  return {{ ok: true }};
}})()
""".format(text=_value_literal(CONFIRM_NEXT_TEXT))


def category_id_from_publish_url(href: str) -> str:
    """只接受契约中填写页的 HTTPS 地址及唯一、正整数 catId。纯函数。"""

    try:
        destination = urlsplit(str(href or ""))
        expected = urlsplit(PUBLISH_FORM_URL)
        valid_page = (
            destination.scheme == expected.scheme
            and destination.hostname == expected.hostname
            and destination.path == expected.path
            and destination.port in (None, 443)
            and destination.username is None
            and destination.password is None
        )
        values = parse_qs(destination.query, keep_blank_values=True).get(
            PUBLISH_FORM_CATEGORY_PARAM, [])
    except ValueError as exc:
        raise PageError("下一步返回的页面地址格式无效，无法确认类目") from exc
    if not valid_page:
        raise PageError("下一步尚未进入契约指定的商品填写页")
    if len(values) != 1:
        raise PageError("商品填写页缺少唯一的 catId，无法确认所选类目")
    category_id = values[0]
    if not category_id or not category_id.isascii() or not category_id.isdecimal() or not category_id.strip("0"):
        raise PageError("商品填写页的 catId 不是有效的正整数，无法确认所选类目")
    return category_id


def confirm_category_and_read_id(client: "PageClient", *, wait: float = 12.0) -> Dict[str, Any]:
    """点「确认，下一步」并**从跳转后的 URL 里回读 catId**。

    ``catId`` 是导航参数而不是写入字段（E-026 已注明），但它确实是**平台给出的
    类目 ID**——比人类可读的路径权威。未跳转、地址不符或拿不到 ID 都明确失败。
    """

    state = read_confirm_button_state(client)
    if state.get("present") is not True:
        raise PageError("页面上没有唯一的「{}」按钮".format(CONFIRM_NEXT_TEXT))
    if state.get("disabled") is not False:
        raise PageError("「{}」仍是禁用状态或状态未知——类目或品牌尚未选好".format(CONFIRM_NEXT_TEXT))
    if state.get("visible") is not True:
        raise PageError("「{}」不可见，不能确认下一步".format(CONFIRM_NEXT_TEXT))

    clicked = client.evaluate(build_click_confirm_next_expression())
    if not isinstance(clicked, dict) or not clicked.get("ok"):
        raise PageError("点击「{}」失败".format(CONFIRM_NEXT_TEXT))

    # 等跳转。用轮询而不是固定 sleep：弱网下固定等待会误判成失败。
    deadline = time.time() + max(3.0, wait)
    last_problem = "尚未读到填写页地址"
    while time.time() < deadline:
        time.sleep(0.8)
        try:
            href = str(client.evaluate("location.href") or "")
            category_id = category_id_from_publish_url(href)
        except PageError as exc:
            # 导航期间只观察，绝不重复点击；超时会保留最后一次失败原因。
            last_problem = str(exc)
        else:
            return {"category_id": category_id, "href": href}
    raise PageError("点击下一步后未能确认填写页与类目：{}".format(last_problem))


# ---------------------------------------------------------------------------
# 运费模板下拉
# ---------------------------------------------------------------------------
#: 运费模板下拉的容器。
#:
#: ⚠️ **两种下拉的容器类名不一样**（实测）：
#:
#: * 品牌下拉   ``.next-select-popup-wrap``（带搜索框、虚拟滚动）
#: * 运费模板   ``.next-overlay-inner.next-select-single-menu``（简单单选菜单）
#:
#: 只认其中一种会导致「下拉明明开了」却报「没有可见的容器」。
#: **不要**把 ``.next-menu`` 加进来：那会抓到顶部导航栏
#: （基础信息/销售信息/物流服务/图文描述），选项看起来完全不对。
FREIGHT_DROPDOWN_SELECTORS = (
    ".next-overlay-inner.next-select-single-menu",
    ".next-overlay-inner.next-select-menu",
    ".next-select-popup-wrap",
)

#: 下拉里的一个选项。
FREIGHT_OPTION_ITEM = "li.next-menu-item"

#: 选项的显示文本。
FREIGHT_OPTION_TEXT = ".next-menu-item-text"


class OptionNotFound(PageError):
    """下拉里没有精确匹配的选项。"""

    code = "OPTION_NOT_FOUND"


def build_open_freight_expression() -> str:
    """生成「按文本锚点找到运费模板控件并展开下拉」的表达式。

    用**文本锚点**而不是类名：实测它的容器是 ``div.template-lzNicC``、
    标签是 ``div.label-HElTNK``，两个都是 CSS Modules 哈希类名，每次构建都会变。
    """

    return """
(() => {{
  const ANCHOR = {anchor};
  const all = Array.from(document.querySelectorAll('div,span,label'));
  const exact = all.filter(el => (el.textContent || '').trim() === ANCHOR);
  if (!exact.length) return {{ ok: false, reason: 'anchor_not_found' }};
  const anchorEl = exact[exact.length - 1];

  let node = anchorEl;
  let container = null;
  for (let hop = 0; hop <= 4 && node; hop++) {{
    const controls = Array.from(node.querySelectorAll('input,textarea,select,[role="combobox"]'))
      .filter(el => {{ const b = el.getBoundingClientRect(); return b.width > 0 && b.height > 0; }});
    if (controls.length === 1) {{ container = node; break; }}
    node = node.parentElement;
  }}
  if (!container) return {{ ok: false, reason: 'no_unique_container' }};

  const control = container.querySelector('input,select,[role="combobox"]');
  if (!control) return {{ ok: false, reason: 'no_control' }};
  const current = String(control.value || '');
  control.click();
  control.focus();
  return {{ ok: true, current, controlPlaceholder: control.getAttribute('placeholder') || '' }};
}})()
""".format(anchor=_value_literal("运费模板"))


def build_read_freight_options_expression() -> str:
    """生成「读下拉里的全部选项」的表达式。"""

    return """
(() => {{
  const SELS = {sels};
  const ITEM = {item};
  const TEXT = {text};
  let root = null;
  let usedSelector = '';
  for (const sel of SELS) {{
    const found = Array.from(document.querySelectorAll(sel))
      .filter(e => e.getBoundingClientRect().height > 0);
    if (found.length) {{ root = found[0]; usedSelector = sel; break; }}
  }}
  if (!root) {{
    return {{ ok: false, reason: 'no_visible_dropdown',
              visibleOverlays: Array.from(document.querySelectorAll('.next-overlay-inner'))
                .filter(e => e.getBoundingClientRect().height > 0)
                .map(e => String(e.className).slice(0, 90)) }};
  }}
  const items = Array.from(root.querySelectorAll(ITEM));
  return {{
    ok: true,
    usedSelector,
    options: items.map(li => {{
      const el = li.querySelector(TEXT);
      return {{
        text: el ? (el.textContent || '').trim() : '',
        selected: (typeof li.className === 'string' ? li.className : '').includes('next-selected'),
      }};
    }}).filter(o => o.text),
  }};
}})()
""".format(
        sels=json.dumps(list(FREIGHT_DROPDOWN_SELECTORS)),
        item=json.dumps(FREIGHT_OPTION_ITEM),
        text=json.dumps(FREIGHT_OPTION_TEXT),
    )


def build_pick_freight_option_expression(name: str) -> str:
    """生成「点中文本精确等于模板名的选项」的表达式。"""

    return """
(() => {{
  const NAME = {name};
  const SELS = {sels};
  const ITEM = {item};
  const TEXT = {text};
  let root = null;
  for (const sel of SELS) {{
    const found = Array.from(document.querySelectorAll(sel))
      .filter(e => e.getBoundingClientRect().height > 0);
    if (found.length) {{ root = found[0]; break; }}
  }}
  if (!root) return {{ ok: false, reason: 'no_visible_dropdown' }};

  const items = Array.from(root.querySelectorAll(ITEM));
  const hits = items.filter(li => {{
    const el = li.querySelector(TEXT);
    return el && (el.textContent || '').trim() === NAME;
  }});
  if (hits.length !== 1) {{
    return {{ ok: false, reason: hits.length === 0 ? 'no_match' : 'ambiguous',
              hitCount: hits.length,
              shown: items.map(li => {{
                const e = li.querySelector(TEXT);
                return e ? (e.textContent || '').trim() : '';
              }}).filter(Boolean) }};
  }}
  hits[0].click();
  return {{ ok: true, picked: NAME }};
}})()
""".format(
        name=_value_literal(name),
        sels=json.dumps(list(FREIGHT_DROPDOWN_SELECTORS)),
        item=json.dumps(FREIGHT_OPTION_ITEM),
        text=json.dumps(FREIGHT_OPTION_TEXT),
    )


def build_read_freight_value_expression() -> str:
    """生成「按文本锚点读当前运费模板名」的表达式。

    提成函数不是洁癖：这段原先内联在 :func:`read_freight_template` 里，
    开头写成了单花括号 ``(() => {``，``str.format`` 抛
    ``unexpected '{' in field name``。**同一类错误在本文件里已经出现三次**，
    三次都是「内联 → 不在单测覆盖里 → 直到实机才炸」。规则：**凡是要经过
    ``.format`` 的 JS，一律写成命名构造器**，这样
    `test_every_builder_runs_without_raising` 才能覆盖到。

    ⚠️ **值不在 ``input.value`` 里**（实测为 ``""``）。Fusion 的 Select 把选中项
    放在 **``aria-valuetext``**，容器里另有一个 ``<em>`` 显示同样的文本。
    三个来源按可靠性依次尝试——只看 ``value`` 会永远读到空，
    然后把「读不到」误判成「选择没生效」。
    """

    return """
(() => {{
  const ANCHOR = {anchor};
  const all = Array.from(document.querySelectorAll('div,span,label'));
  const exact = all.filter(el => (el.textContent || '').trim() === ANCHOR);
  if (!exact.length) return {{ ok: false, reason: 'anchor_not_found' }};
  let node = exact[exact.length - 1];
  for (let hop = 0; hop <= 4 && node; hop++) {{
    const controls = Array.from(node.querySelectorAll('input,select,[role="combobox"]'))
      .filter(el => {{ const b = el.getBoundingClientRect(); return b.width > 0 && b.height > 0; }});
    if (controls.length === 1) {{
      const c = controls[0];
      const aria = String(c.getAttribute('aria-valuetext') || '').trim();
      const value = String(c.value || '').trim();
      const em = node.querySelector('em');
      const emText = em ? (em.textContent || '').trim() : '';
      return {{
        ok: true,
        value: aria || value || emText || '',
        source: aria ? 'aria-valuetext' : (value ? 'value' : (emText ? 'em' : 'none')),
      }};
    }}
    node = node.parentElement;
  }}
  return {{ ok: false, reason: 'no_unique_container' }};
}})()
""".format(anchor=_value_literal("运费模板"))


def read_freight_template(client: "PageClient") -> Optional[str]:
    """读当前控件上的运费模板名（未选时可能为空或显示占位）。

    优先读 ``input.value``；实测该控件是 ``input[role=combobox]``。
    """

    payload = client.evaluate(build_read_freight_value_expression())

    if not isinstance(payload, dict) or not payload.get("ok"):
        return None
    value = payload.get("value")
    return str(value) if value else None


def open_freight_dropdown(client: "PageClient", *, wait: float = 1.5) -> Dict[str, Any]:
    """展开运费模板下拉，返回它当前的显示值。"""

    payload = client.evaluate(build_open_freight_expression())
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise CandidateNotFound(
            "展开运费模板下拉失败：{}".format(
                json.dumps(payload, ensure_ascii=False)[:160] if payload else "无返回"))
    time.sleep(wait)
    return payload


def read_freight_options(client: "PageClient") -> List[str]:
    """读下拉里的全部模板名。读不到返回空列表（调用方据此报错）。"""

    payload = client.evaluate(build_read_freight_options_expression())
    if not isinstance(payload, dict) or not payload.get("ok"):
        return []
    return [str(o["text"]) for o in (payload.get("options") or []) if o.get("text")]


def pick_freight_option(client: "PageClient", name: str) -> Dict[str, Any]:
    """按**精确文本**选中运费模板。命中 0 或多个都拒绝。

    运费模板选错的后果是按别人的运费规则发货，而且**发出去才发现**，
    所以不做「最接近」的妥协。
    """

    payload = client.evaluate(build_pick_freight_option_expression(name))
    if not isinstance(payload, dict):
        raise PageError("选择运费模板 {!r} 时页面没有返回可解析的结果".format(name))
    if not payload.get("ok"):
        raise OptionNotFound(
            "运费模板 {!r} 未在下拉中精确命中（{}）；当时可见：{}".format(
                name, payload.get("reason"),
                "、".join(payload.get("shown") or []) or "（空）"))
    return payload


def wait_for_freight_value(
    client: "PageClient", expected: str, *, timeout: float = 8.0, interval: float = 0.6
) -> Optional[str]:
    """等到控件上的运费模板名变成期望值，返回最后一次读到的结果。

    与 :func:`wait_for_selected_category` 同理：**点完立刻读会拿到旧值**，
    看起来像选择没生效。轮询而不是固定 sleep——弱网下固定等待会误判失败。
    """

    deadline = time.time() + max(1.0, timeout)
    value: Optional[str] = None
    while time.time() < deadline:
        value = read_freight_template(client)
        if value == expected:
            return value
        time.sleep(interval)
    return value


# ---------------------------------------------------------------------------
# 提交发布
# ---------------------------------------------------------------------------
#: 「提交宝贝信息」——整套流水线里唯一真正把商品推上平台的按钮。
SUBMIT_BUTTON_TEXT = "提交宝贝信息"

#: 「保存草稿」。
SAVE_DRAFT_BUTTON_TEXT = "保存草稿"


def build_read_submit_state_expression() -> str:
    """生成「读提交按钮与保存草稿按钮的状态」的表达式。**只读。**"""

    return """
(() => {{
  const SUBMIT = {submit};
  const DRAFT = {draft};
  const btns = Array.from(document.querySelectorAll('button'));
  const pick = (text) => {{
    const hits = btns.filter(b => (b.textContent || '').trim() === text);
    if (hits.length !== 1) return {{ present: false, hitCount: hits.length }};
    const r = hits[0].getBoundingClientRect();
    return {{ present: true, disabled: hits[0].disabled === true,
             visible: r.width > 0 && r.height > 0 }};
  }};
  return {{ submit: pick(SUBMIT), draft: pick(DRAFT), href: location.href }};
}})()
""".format(
        submit=_value_literal(SUBMIT_BUTTON_TEXT),
        draft=_value_literal(SAVE_DRAFT_BUTTON_TEXT),
    )


def build_click_submit_expression() -> str:
    """生成「点提交按钮」的表达式。

    唯一性判定在动作**之前**：命中数不为 1、不可见、或处于禁用状态时直接返回失败，
    绝不点下去。「提交错商品」没有撤销按钮。

    实现委托给 :func:`build_click_button_by_text_expression`——**判据只有一份**，
    避免"提交"与"保存草稿"两条路各自演化出不同的守卫。
    """

    return build_click_button_by_text_expression(SUBMIT_BUTTON_TEXT)


def build_read_submit_outcome_expression() -> str:
    """生成「读提交后页面上的提示」的表达式。**只读**。

    返回可见的提示类元素文本（成功/失败提示通常是 ``.next-message`` /
    ``.next-feedback`` 一类）**以及可见的对话框**。

    ⚠️ **对话框要单独列出来，不能只当成"一条提示"。** 实测（2026-10-06，保存草稿）：
    点击「保存草稿」后平台弹出一个 `next-dialog … next-dialog-quick` 对话框
    （「草稿箱最大保存 10 条草稿…确定」），**而页面上没有任何"成功"字样**。
    对话框是"平台处理了这次动作"的**可观察信号**，与页面常驻的静态说明文字
    完全不是一回事——混在一起读就会把静态文案当成结果。
    """

    return """
(() => {{
  const SELS = ['.next-message', '.next-feedback', '.next-dialog', '.next-overlay-inner',
                '[class*="message"]', '[class*="toast"]', '[class*="feedback"]'];
  const visible = el => {{
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }};
  const out = [];
  for (const sel of SELS) {{
    for (const el of Array.from(document.querySelectorAll(sel))) {{
      if (!visible(el)) continue;
      const text = (el.textContent || '').trim().slice(0, 120);
      if (text) out.push({{ selector: sel, text }});
    }}
  }}
  // 去重
  const seen = new Set();
  const unique = [];
  for (const item of out) {{
    if (seen.has(item.text)) continue;
    seen.add(item.text);
    unique.push(item);
  }}
  // 可见对话框：单独回报（它是"平台弹了框"这种强信号，不是普通说明文字）
  const dialogSel = '.next-dialog, [role="dialog"], .next-message-box';
  const dialogs = Array.from(document.querySelectorAll(dialogSel)).filter(visible)
    .map(el => ({{ className: String(el.className || '').slice(0, 80),
                  text: (el.textContent || '').trim().slice(0, 200) }}))
    .filter(d => d.text);
  return {{ href: location.href, messages: unique.slice(0, 8), dialogs: dialogs.slice(0, 4) }};
}})()
""".format()


def read_submit_state(client: "PageClient") -> Dict[str, Any]:
    """读提交按钮与草稿按钮的状态。**只读**。"""

    payload = client.evaluate(build_read_submit_state_expression())
    return payload if isinstance(payload, dict) else {}


def build_click_button_by_text_expression(button_text: str) -> str:
    """生成「按**按钮文本**点一个按钮」的表达式。

    唯一性判定在动作**之前**：命中数不为 1、不可见、或禁用时直接返回失败，绝不点下去。

    ⚠️ 为什么按文本：CSS 选择器无法按文本匹配，而「提交宝贝信息」与「保存草稿」
    的类名只差 `next-btn-primary`——**区别只在文本**。契约里两个按钮都是
    `label` 承载文本、`selector` 为 null。
    """

    return """
(() => {{
  const TEXT = {text};
  const btns = Array.from(document.querySelectorAll('button'))
    .filter(b => (b.textContent || '').trim() === TEXT);
  const visible = btns.filter(b => {{
    const r = b.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }});
  if (btns.length !== 1 || visible.length !== 1) {{
    return {{ ok: false, reason: btns.length === 0 ? 'not_found'
              : (btns.length > 1 ? 'ambiguous' : 'not_visible'),
              hitCount: btns.length, visibleCount: visible.length }};
  }}
  if (visible[0].disabled) return {{ ok: false, reason: 'disabled' }};
  visible[0].click();
  return {{ ok: true }};
}})()
""".format(text=_value_literal(button_text))


def click_button_by_text(client: "PageClient", button_text: str) -> Dict[str, Any]:
    """按文本点一个按钮（唯一性 + 可见 + 未禁用都在动作前判定）。

    :raises PageError: 按钮不唯一、不可见或禁用
    """

    payload = client.evaluate(build_click_button_by_text_expression(button_text))
    if not isinstance(payload, dict):
        raise PageError("点按钮 {!r} 时页面没有返回可解析的结果".format(button_text))
    if payload.get("ok") is not True:
        raise PageError("按钮 {!r} 不可点（{}；命中 {}，可见 {}）".format(
            button_text, payload.get("reason"), payload.get("hitCount"),
            payload.get("visibleCount")))
    return payload


def click_submit_button(client: "PageClient") -> Dict[str, Any]:
    """点「提交宝贝信息」。

    **调用方必须先确认已获得 ``submit_publish`` 授权**——本函数不做授权判断，
    授权门在执行器（``run_stage``）里，早于处理器被调用。

    :raises PageError: 按钮不唯一、不可见或禁用
    """

    payload = client.evaluate(build_click_submit_expression())
    if not isinstance(payload, dict):
        raise PageError("点提交按钮时页面没有返回可解析的结果")
    if payload.get("ok") is not True:
        reason = str(payload.get("reason") or "unknown")
        raise PageError("提交按钮不可点（{}；命中 {}，可见 {}）".format(
            reason, payload.get("hitCount"), payload.get("visibleCount")))
    return payload


def read_submit_outcome(client: "PageClient") -> Dict[str, Any]:
    """读提交后页面上的提示与当前 URL。**只读**，且**不判断成功与否**。"""

    payload = client.evaluate(build_read_submit_outcome_expression())
    return payload if isinstance(payload, dict) else {}


def wait_for_submit_outcome(
    client: "PageClient", before_href: str, *,
    before_messages: Optional[Sequence[str]] = None,
    timeout: float = 20.0, interval: float = 1.0,
) -> Dict[str, Any]:
    """等到「页面有了**新的**变化」为止：URL 变了，或出现了**新的**提示文本。

    .. warning::
        **不能把「页面上有提示文本」当成「有变化」。**

        页面本来就飘着一堆 ``.next-message``（说明文字、历史提示）。
        实测（2026-10-03）未提交的页面上有 5 条，原判据因此 **0.0 秒**就返回，
        并把这 5 条**点击前就存在**的提示当成「提交的结果」——
        提交什么都没发生时，它也会报「观察到页面响应」。

        现在只认**新增**的提示（与 ``before_messages`` 做差）。

    :param before_messages: 点击**前**页面上的提示文本。传了才能做差；
        不传时退化为「任何提示都算」——**调用方应当传**。

    有超时是**有意的**：提交通道的成功特征尚未实证，等不到变化时应当如实报
    「点了但读不到结果」，而不是无限等下去或假装成功。
    超时时返回体里的 ``changed`` 为 ``False``。
    """

    baseline = {str(text) for text in (before_messages or [])}
    deadline = time.time() + max(2.0, timeout)
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        last = read_submit_outcome(client)
        href = str(last.get("href") or "")
        texts = [m.get("text") for m in (last.get("messages") or []) if m.get("text")]
        fresh = [t for t in texts if str(t) not in baseline]
        if href and href != before_href:
            return dict(last, changed=True, new_messages=fresh)
        if fresh:
            return dict(last, changed=True, new_messages=fresh)
        time.sleep(interval)
    return dict(last, changed=False, new_messages=[])


# ---------------------------------------------------------------------------
# 销售规格抽屉
# ---------------------------------------------------------------------------
#: 抽屉容器。打开「+ 创建规格」后出现。
SKU_DRAWER = ".sku-decouple-drawer-container"

#: 抽屉底部（**它是 .next-drawer-body 的子节点，不是抽屉容器的子节点**，别写错层级）。
SKU_DRAWER_FOOTER = ".sku-decouple-drawer-footer"

#: 一个销售属性块（「颜色分类」「尺码」各一块）。
SKU_ATTR_BLOCK = ".common-wrap"

#: 属性块的标题，形如 ``颜色分类(0)添加图片``——括号里是**已选值个数**。
SKU_ATTR_HEADER = ".header"

#: 属性块里的值行。
SKU_ATTR_ROW = "li"

#: 「+」加值行的按钮。**这是新增值行的唯一入口**（E-095）。
SKU_ADD_BUTTON = "button.add"

#: 可选属性项，带 ``selected`` 类表示已勾选。
SKU_PROP_ITEM = ".prop-item"

#: 底部确认按钮文本。
SKU_CONFIRM_TEXT = "确认创建"

#: 打开抽屉的按钮文本。
SKU_OPEN_TEXT = "+ 创建规格"

#: 规格值下拉里的候选项。
#:
#: ⚠️ **与运费模板下拉的结构不同**（E-090，实测）：
#:
#: * 标准选择（选品牌、选规格值）→ 容器 ``.next-select-popup-wrap``，
#:   候选 ``.options-item``，文本 ``.info-content``；
#: * 简单菜单（运费模板）→ 容器 ``.next-overlay-inner.next-select-single-menu``，
#:   候选 ``li.next-menu-item``，文本 ``.next-menu-item-text``。
#:
#: 拿后者去读前者的候选会得到 **0 个**，而弹层其实开着——很容易误判成「下拉没打开」。
SKU_OPTION_ITEM = BRAND_OPTION_ITEM
SKU_OPTION_TEXT = BRAND_OPTION_TEXT

#: SKU 表格容器。**没创建规格时它也可见**，里面只有「+ 创建规格」按钮，
#: 所以「容器在」不能当作「规格已创建」——必须查 ``table`` / ``tr`` 的数量。
SKU_TABLE_ROOT = ".sell-sku-table-wrapper-new"

#: SKU 表格的数据行。
SKU_ROW = "tr.sku-table-row"


def build_query_element_expression(selector: str) -> str:
    """生成「在目标 frame 里按选择器取一个元素**对象**（不是值）」的表达式。

    ``returnByValue: False`` 时返回的是 remote object，可以直接交给
    ``DOM.requestNode`` 换成 nodeId——``DOM.setFileInputFiles`` 需要的就是它。

    ⚠️ 这段原先**内联在** :meth:`PageClient.set_file_input_files` 里，写成
    ``"(() => { const el = ...; }})()"`` 并直接 ``.format()``——第一个 ``{``
    是单花括号，``.format()`` 抛 ``unexpected '{' in field name``，
    **upload_images 因此一跑就炸**。提成命名构造器之后
    ``tests/check_all_builders.py`` 才能覆盖到它。
    """

    return """
(() => {{
  const el = document.querySelector({sel});
  return el ? el : null;
}})()
""".format(sel=_value_literal(selector))


def build_open_sku_drawer_expression() -> str:
    """生成「点 + 创建规格」的表达式。**只展开抽屉，不创建任何规格。**"""

    return """
(() => {{
  const TEXT = {open_text};
  const btns = Array.from(document.querySelectorAll('button'))
    .filter(b => (b.textContent || '').trim() === TEXT);
  const visible = btns.filter(b => {{
    const r = b.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }});
  if (btns.length !== 1 || visible.length !== 1) {{
    return {{ ok: false, reason: btns.length === 0 ? 'not_found'
              : (btns.length > 1 ? 'ambiguous' : 'not_visible'),
              hitCount: btns.length }};
  }}
  if (visible[0].disabled) return {{ ok: false, reason: 'disabled' }};
  visible[0].click();
  return {{ ok: true }};
}})()
""".format(open_text=_value_literal(SKU_OPEN_TEXT))


def build_read_sku_drawer_state_expression() -> str:
    """生成「读抽屉状态」的表达式。**只读。**

    返回：抽屉是否打开、每个属性块的计数与行值、哪些属性被勾选。
    """

    return """
(() => {{
  const DRAWER = {drawer};
  const BLOCK = {block};
  const HEADER = {header};
  const ROW = {row};
  const PROP = {prop};

  const drawer = document.querySelector(DRAWER);
  const open = Boolean(drawer && drawer.getBoundingClientRect().height > 0);

  const readCount = (text) => {{
    const m = String(text || '').match(/\\((\\d+)\\)/);
    return m ? Number(m[1]) : null;
  }};

  const blockEl = drawer ? drawer.querySelectorAll(BLOCK) : [];
  const blocks = Array.from(blockEl).map(w => {{
    const h = w.querySelector(HEADER);
    const headerText = h ? (h.textContent || '').trim() : '';
    const rows = Array.from(w.querySelectorAll(ROW));
    return {{
      header: headerText.slice(0, 40),
      // 块名取括号前的部分，用于和 item 里的属性名比对
      name: headerText.split('(')[0].trim(),
      count: readCount(headerText),
      rowCount: rows.length,
      rowValues: rows.map(li => {{
        const inp = li.querySelector('input,[role="combobox"]');
        return inp ? String(inp.value || '').trim().slice(0, 30) : '';
      }}),
      addButtons: Array.from(w.querySelectorAll({add})).length,
    }};
  }});

  const props = drawer ? Array.from(drawer.querySelectorAll(PROP)).map(el => ({{
    name: (el.textContent || '').trim().slice(0, 20),
    selected: String(el.className).includes('selected'),
  }})) : [];

  return {{ open, blocks, props }};
}})()
""".format(
        drawer=_value_literal(SKU_DRAWER),
        block=_value_literal(SKU_ATTR_BLOCK),
        header=_value_literal(SKU_ATTR_HEADER),
        row=_value_literal(SKU_ATTR_ROW),
        prop=_value_literal(SKU_PROP_ITEM),
        add=_value_literal(SKU_ADD_BUTTON),
    )


def build_attr_block_fragment(name: str, indent: str = "  ") -> str:
    """生成「在抽屉里按名字找到属性块」的 JS 片段。

    按 **header 文本前缀**匹配，不按 DOM 顺序：属性块的顺序会随勾选变化。
    """

    return (
        "{i}const WANT = {name};\n"
        "{i}const drawer = document.querySelector({drawer});\n"
        "{i}if (!drawer) return {{ ok: false, reason: 'no_drawer' }};\n"
        "{i}const block = Array.from(drawer.querySelectorAll({block})).find(w => {{\n"
        "{i}  const h = w.querySelector({header});\n"
        "{i}  const text = h ? (h.textContent || '').trim() : '';\n"
        "{i}  return text.split('(')[0].trim() === WANT;\n"
        "{i}}});\n"
        "{i}if (!block) return {{ ok: false, reason: 'no_block', want: WANT,\n"
        "{i}  available: Array.from(drawer.querySelectorAll({block})).map(w => {{\n"
        "{i}    const h = w.querySelector({header});\n"
        "{i}    return h ? (h.textContent || '').trim().split('(')[0].trim() : '';\n"
        "{i}  }}) }};\n"
    ).format(
        i=indent,
        name=_value_literal(name),
        drawer=_value_literal(SKU_DRAWER),
        block=_value_literal(SKU_ATTR_BLOCK),
        header=_value_literal(SKU_ATTR_HEADER),
    )


def build_add_spec_row_expression(attr_name: str) -> str:
    """生成「点某个属性块的 + 加一个值行」的表达式。

    ⚠️ **加值必须走这里**（E-095）：块里那个 ``input[role=combobox]`` 是
    **所在行**的编辑器，反复用它只会改掉同一行的值，不会新增值。
    """

    return """
(() => {{
{block}
  const btns = Array.from(block.querySelectorAll({add}));
  if (btns.length !== 1) return {{ ok: false, reason: 'not_unique_add', hitCount: btns.length }};
  const r = btns[0].getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return {{ ok: false, reason: 'add_not_visible' }};
  if (btns[0].disabled) return {{ ok: false, reason: 'add_disabled' }};
  btns[0].click();
  return {{ ok: true }};
}})()
""".format(
        block=build_attr_block_fragment(attr_name),
        add=_value_literal(SKU_ADD_BUTTON),
    )


def build_open_spec_value_input_expression(attr_name: str) -> str:
    """生成「点**最后一行**的值输入框」的表达式。

    取最后一行：新加的行在末尾。从后往前找，兼容某些行没有输入的情况。
    """

    return """
(() => {{
{block}
  const rows = Array.from(block.querySelectorAll({row}));
  if (!rows.length) return {{ ok: false, reason: 'no_rows' }};
  const before = document.querySelectorAll('.next-select-popup-wrap').length;
  let target = null;
  for (let i = rows.length - 1; i >= 0 && !target; i--) {{
    const inputs = Array.from(rows[i].querySelectorAll('input,[role="combobox"]')).filter(el => {{
      const r = el.getBoundingClientRect();
      if (r.height === 0) return false;
      const cls = typeof el.className === 'string' ? el.className : '';
      return !cls.includes('checkbox') && !cls.includes('radio');
    }});
    if (inputs.length) target = inputs[inputs.length - 1];
  }}
  if (!target) return {{ ok: false, reason: 'no_input' }};
  target.click();
  target.focus();
  return {{ ok: true, popupsBeforeClick: before }};
}})()
""".format(
        block=build_attr_block_fragment(attr_name),
        row=_value_literal(SKU_ATTR_ROW),
    )


def build_pick_spec_value_expression(value: str) -> str:
    """生成「在**最后一个**可见弹层里点中候选值」的表达式。

    **必须取最后一个弹层**：残留的旧弹层还在 DOM 里时，点到的是上一次渲染的
    节点，React 处理器作用在旧状态上——值会填进输入框但**不会提交**（实测踩过）。

    候选结构与运费模板下拉**不同**：标准选择用 ``.options-item`` + ``.info-content``。
    """

    return """
(() => {{
  const WANT = {value};
  const pops = Array.from(document.querySelectorAll('.next-select-popup-wrap'))
    .filter(e => e.getBoundingClientRect().height > 0);
  if (!pops.length) return {{ ok: false, reason: 'no_popup' }};
  const pop = pops[pops.length - 1];
  // ⚠️ **候选文本的读取要认多种结构。**
  //
  // 实测两种属性控件：`sell-o-combobox`（品牌）的候选项有 `.info-content`；
  // `sell-o-select`（适用季节）的候选项是 `DIV.sell-o-info`，**没有** `.info-content`。
  // 只认前者的话，后者的候选项会被整条 `filter` 掉 → 报 `no_match`，
  // **而真相是「读不出候选文本」**。
  const textOf = (el) => {{
    const specific = el.querySelector({text} + ", .sell-o-info");
    if (specific) return (specific.textContent || '').trim();
    for (const child of el.children) {{
      const t = (child.textContent || '').trim();
      if (t) return t;
    }}
    return (el.textContent || '').trim();
  }};
  const options = Array.from(pop.querySelectorAll({item})).map(el => {{
    return {{ el, text: textOf(el) }};
  }}).filter(o => o.text);
  const hits = options.filter(o => o.text === WANT);
  if (hits.length !== 1) {{
    return {{ ok: false, reason: hits.length === 0 ? 'no_match' : 'ambiguous',
             hitCount: hits.length, popupCount: pops.length,
             shown: [...new Set(options.map(o => o.text))].slice(0, 20) }};
  }}
  hits[0].el.click();
  return {{ ok: true, popupCount: pops.length, picked: WANT }};
}})()
""".format(
        value=_value_literal(value),
        item=_value_literal(SKU_OPTION_ITEM),
        text=_value_literal(SKU_OPTION_TEXT),
    )


def build_set_prop_selected_expression(attr_name: str, selected: bool) -> str:
    """生成「勾选 / 取消勾选某个销售属性」的表达式。

    **存在的意义是规避 E-097 的静默失败**：分层展示模式下，已勾选但**没有值**的
    属性会让「确认创建」什么都不做——不报错、按钮也不禁用。所以不需要的属性
    必须**显式取消勾选**。
    """

    return """
(() => {{
  const WANT = {name};
  const WANT_SELECTED = {selected};
  const drawer = document.querySelector({drawer});
  if (!drawer) return {{ ok: false, reason: 'no_drawer' }};
  const items = Array.from(drawer.querySelectorAll({prop}));
  const hits = items.filter(el => (el.textContent || '').trim() === WANT);
  if (hits.length !== 1) {{
    return {{ ok: false, reason: hits.length === 0 ? 'no_match' : 'ambiguous',
             hitCount: hits.length,
             shown: items.map(el => (el.textContent || '').trim()).slice(0, 12) }};
  }}
  const isSelected = String(hits[0].className).includes('selected');
  if (isSelected === WANT_SELECTED) return {{ ok: true, changed: false, selected: isSelected }};
  hits[0].click();
  return {{ ok: true, changed: true, wasSelected: isSelected }};
}})()
""".format(
        name=_value_literal(attr_name),
        selected="true" if selected else "false",
        drawer=_value_literal(SKU_DRAWER),
        prop=_value_literal(SKU_PROP_ITEM),
    )


def build_confirm_sku_expression() -> str:
    """生成「点确认创建」的表达式。

    唯一性判定在动作之前：命中数不为 1 或处于禁用状态时直接返回失败。
    """

    return """
(() => {{
  const TEXT = {confirm};
  const footer = document.querySelector({footer});
  if (!footer) return {{ ok: false, reason: 'no_footer' }};
  const btns = Array.from(footer.querySelectorAll('button'))
    .filter(b => (b.textContent || '').trim() === TEXT);
  if (btns.length !== 1) return {{ ok: false, reason: 'not_unique', hitCount: btns.length }};
  if (btns[0].disabled) return {{ ok: false, reason: 'disabled' }};
  btns[0].click();
  return {{ ok: true }};
}})()
""".format(
        confirm=_value_literal(SKU_CONFIRM_TEXT),
        footer=_value_literal(SKU_DRAWER_FOOTER),
    )


def build_set_sku_row_numbers_expression(row_index: int, price: str, stock: str) -> str:
    """设置第 ``row_index`` 行（0 起）的价格与库存。

    * 按**单元格文本里的单位字**（``元`` / ``件``）定位列，不按列序号；
    * 走**原生 setter + `input`/`change`/`blur` 事件**——
      这是 React 受控输入，直接赋 `value` 不会触发框架状态更新；
    * 只设值，**不判断成功**——调用方必须回读确认。
    """

    return r"""
    (() => {
      const roots = Array.from(document.querySelectorAll(%(root)s));
      if (roots.length !== 1) return { ok: false, reason: 'sku_root_not_unique' };
      const trs = Array.from(roots[0].querySelectorAll(%(row)s));
      const tr = trs[%(index)d];
      if (!tr) return { ok: false, reason: 'no_row', rowCount: trs.length };

      const setValue = (input, value) => {
        if (value === null || value === undefined) return false;
        const proto = Object.getPrototypeOf(input);
        const desc = Object.getOwnPropertyDescriptor(proto, 'value');
        if (desc && desc.set) desc.set.call(input, String(value));
        else input.value = String(value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        input.dispatchEvent(new Event('blur', { bubbles: true }));
        return true;
      };

      const controls = { price: [], stock: [] };
      for (const td of tr.querySelectorAll('td')) {
        const text = (td.textContent || '').trim();
        const input = td.querySelector('input');
        if (!input) continue;
        if (text.includes('\u5143')) controls.price.push(input);
        else if (text.includes('\u4ef6')) controls.stock.push(input);
      }
      if (controls.price.length !== 1 || controls.stock.length !== 1)
        return { ok: false, reason: 'sku_controls_not_unique' };
      if ([controls.price[0], controls.stock[0]].some(input => input.disabled || input.readOnly))
        return { ok: false, reason: 'sku_controls_unavailable' };
      const done = {
        price: setValue(controls.price[0], %(price)s),
        stock: setValue(controls.stock[0], %(stock)s),
      };
      return { ok: true, set: done };
    })()
    """ % {
        "root": _value_literal(SKU_TABLE_ROOT),
        "row": _value_literal(SKU_ROW),
        "index": int(row_index),
        "price": repr(str(price)),
        "stock": repr(str(stock)),
    }


def set_sku_row_numbers(client: "PageClient", row_index: int, *,
                        price: str = "", stock: str = "",
                        wait: float = 0.6) -> Dict[str, Any]:
    """设置某一行的价格 / 库存。返回页面给的原始结果。"""

    payload = client.evaluate(
        build_set_sku_row_numbers_expression(row_index, price, stock))
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise CandidateNotFound("SKU 价格库存行定位失败：{}".format(payload))
    if not (payload.get("set") or {}).get("price") or not (payload.get("set") or {}).get("stock"):
        raise CandidateNotFound("SKU 行缺少可填写的价格或库存控件；未确认完整写入")
    time.sleep(wait)
    return payload


def build_read_sku_row_numbers_expression() -> str:
    """读 SKU 表**每一行**的「价格」与「库存」。

    ⚠️ **为什么需要单独一个表达式。**

    实测（2026-10-03）：完整链条跑完之后，平台在页面上**可见地**报着

        至少有一个sku的价格大于0，请先设置sku价格

    而 SKU 行第 3 列（单元格文本 `元`）的输入框是**空的**、第 5 列（`件`）是 `0`
    ——因为 `fill_skus` 只负责创建规格行，商品级的「一口价/总库存」是**另一回事**
    （`fill_price_stock` 填的）。两者都被「核对通过」，而平台说不能提交。

    **列的定位靠单元格文本里的单位字**（`元` / `件`），不靠列序号——
    列顺序会随「是否显示商家编码」之类的设置变。
    """

    return r"""
    (() => {
      const roots = Array.from(document.querySelectorAll(ROOT_SELECTOR));
      if (roots.length !== 1) return { ok: false, reason: 'sku_root_not_unique' };
      const rows = [];
      for (const tr of roots[0].querySelectorAll(ROW_SELECTOR)) {
        let price = null, stock = null;
        for (const td of tr.querySelectorAll('td')) {
          const text = (td.textContent || '').trim();
          const input = td.querySelector('input');
          if (!input) continue;
          if (text.includes('\u5143') && price === null) price = input.value || '';
          else if (text.includes('\u4ef6') && stock === null) stock = input.value || '';
        }
        const specs = Array.from(tr.querySelectorAll('td')).slice(0, 2)
          .map(td => (td.textContent || '').trim()).filter(Boolean);
        rows.push({ specs, price, stock });
      }
      return { ok: true, rows };
    })()
    """.replace("ROOT_SELECTOR", _value_literal(SKU_TABLE_ROOT)).replace(
        "ROW_SELECTOR", _value_literal(SKU_ROW))


def read_sku_row_numbers(client: "PageClient") -> List[Dict[str, Any]]:
    """读每一行的价格 / 库存。读不到返回空列表（调用方据此报错）。"""

    payload = client.evaluate(build_read_sku_row_numbers_expression())
    if not isinstance(payload, dict) or not payload.get("ok"):
        return []
    return list(payload.get("rows") or [])


def build_read_sku_table_expression() -> str:
    """生成「读 SKU 表格」的表达式。**只读。**

    注意 ``.sell-sku-table-wrapper-new`` 在**没创建规格时也存在**（里面只有
    「+ 创建规格」按钮），所以必须看 ``table`` / ``tr`` 的数量，不能看容器在不在。
    """

    return """
(() => {{
  const root = document.querySelector({root_sel});
  const drawer = document.querySelector({drawer});
  const open = Boolean(drawer && drawer.getBoundingClientRect().height > 0);
  if (!root) return {{ found: false, drawerOpen: open }};

  const tables = Array.from(root.querySelectorAll('table'));
  if (!tables.length) {{
    return {{ found: true, drawerOpen: open, tableCount: 0,
             wrapperText: (root.textContent || '').trim().slice(0, 120) }};
  }}

  const rows = Array.from(root.querySelectorAll({row_sel}));
  return {{
    found: true,
    drawerOpen: open,
    tableCount: tables.length,
    rowCount: rows.length,
    rows: rows.map(tr => ({{
      specs: Array.from(tr.querySelectorAll('td')).slice(0, 2)
        .map(td => (td.textContent || '').trim()).filter(Boolean),
      inputs: Array.from(tr.querySelectorAll('input,textarea')).map(i => ({{
        placeholder: i.getAttribute('placeholder') || '',
        value: String(i.value || ''),
        className: typeof i.className === 'string' ? i.className.slice(0, 60) : '',
      }})),
    }})),
  }};
}})()
""".format(
        root_sel=_value_literal(SKU_TABLE_ROOT),
        drawer=_value_literal(SKU_DRAWER),
        row_sel=_value_literal(SKU_ROW),
    )


def read_sku_drawer_state(client: "PageClient") -> Dict[str, Any]:
    """读销售规格抽屉的状态。抽屉没打开时 ``open`` 为假。"""

    payload = client.evaluate(build_read_sku_drawer_state_expression())
    return payload if isinstance(payload, dict) else {"open": False, "blocks": [], "props": []}


def open_sku_drawer(client: "PageClient", *, wait: float = 3.0) -> Dict[str, Any]:
    """点「+ 创建规格」展开抽屉。**只展开，不创建。**"""

    payload = client.evaluate(build_open_sku_drawer_expression())
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise CandidateNotFound("展开销售规格抽屉失败：{}".format(
            json.dumps(payload, ensure_ascii=False)[:160] if payload else "无返回"))
    time.sleep(wait)
    return payload


def add_spec_row(client: "PageClient", attr_name: str, *, wait: float = 1.2) -> Dict[str, Any]:
    """给某个销售属性加一个值行。"""

    payload = client.evaluate(build_add_spec_row_expression(attr_name))
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise CandidateNotFound("给属性 {!r} 加值行失败：{}".format(
            attr_name, json.dumps(payload, ensure_ascii=False)[:160] if payload else "无返回"))
    time.sleep(wait)
    return payload



def build_open_prop_dropdown_expression(label: str, *, exact_only: bool = False) -> str:
    """生成「打开某个**类目属性**的下拉」的表达式。

    与 `build_open_spec_value_input_expression` 的区别：那个点的是 SKU 抽屉里
    **最后一行**（抽屉是刚创建的，只有那一行）；这个点的是**按标签唯一定位**
    的那一行——属性行有几十个，不能靠「最后一个」。

    ⚠️ **唯一性判定与点击在同一个表达式里**：命中不是恰好 1 行时**一次点击都不发生**。
    「先查一次、再点一次」在两次查询之间页面可能变化。
    """

    return """
(() => {{
  const LABEL = {label_literal};
  // ⚠️ **两种行结构都要试。**
  //
  // 实测：直接导航到填写页时属性行在 `.sell-catProp-item-common` 里，
  // 而 `select_category` 选完类目后同一批属性行在
  // `.sell-component-info-wrapper-wrap` 里。**写死一种 = 只在一种状态下能用。**
  const PROFILES = [
    {{ row: ".sell-component-info-wrapper-wrap",
      labelSel: ".sell-component-info-wrapper-label" }},
    {{ row: ".sell-catProp-item-common", labelSel: "label" }},
  ];

  const labelOf = (el, sel) => {{
    const t = el.querySelector(sel);
    return t ? (t.textContent || '').trim() : '';
  }};

  let row = null;
  let tries = [];
  for (const prof of PROFILES) {{
    const rows = Array.from(document.querySelectorAll(prof.row));
    let hits = rows.filter(r => labelOf(r, prof.labelSel) === LABEL);
    if (!{exact_only} && hits.length === 0) hits = rows.filter(r => labelOf(r, prof.labelSel).startsWith(LABEL));
    tries.push({{ row: prof.row, rowCount: rows.length, hitCount: hits.length }});
    if (hits.length === 1) {{ row = hits[0]; break; }}
    if (hits.length > 1) {{
      return {{ ok: false, label: LABEL, reason: 'label_ambiguous',
               hitCount: hits.length, tries }};
    }}
  }}
  if (!row) {{
    return {{ ok: false, label: LABEL, reason: 'label_not_found',
             hitCount: 0, tries }};
  }}
  // ⚠️ **点的是 `.next-select` 容器，不是 input。**
  //
  // 实测两种控件：`sell-o-combobox`（品牌）点 input 能展开；
  // `sell-o-select`（适用季节，`next-no-search`）的 input 是 **readonly**，
  // 点它**不展开**（实测 `no_popup`）。两者的容器都带 `.next-select`，
  // 也是页面上真正可点的触发器。
  const input = row.querySelector('input[role="combobox"]')
             || row.querySelector('input[type="text"]')
             || row.querySelector('input');
  const trigger = row.querySelector('[class*="next-select"]') || input;
  if (!trigger) return {{ ok: false, label: LABEL, reason: 'no_control' }};
  const box = trigger.getBoundingClientRect();
  if (box.width <= 0 || box.height <= 0) {{
    return {{ ok: false, label: LABEL, reason: 'control_not_visible' }};
  }}
  const expanded = trigger.getAttribute
    ? trigger.getAttribute('aria-expanded') === 'true' : false;
  if (input && input.disabled === true) {{
    return {{ ok: false, label: LABEL, reason: 'input_disabled' }};
  }}

  // **已经是展开状态就不再点**——再点会把它关掉（实测踩过）。
  if (!expanded) {{
    if (input) input.focus();
    trigger.click();
  }}
  return {{ ok: true, label: LABEL, role: input ? (input.getAttribute('role') || '') : '',
           wasExpanded: expanded }};
}})()
""".format(
        label_literal=_value_literal(label),
        exact_only=json.dumps(exact_only),
    )



def build_search_prop_options_expression(keyword: str) -> str:
    """生成「在**已打开的下拉**的搜索框里输入关键词」的表达式。

    ⚠️ **输入 ≠ 选中。** 这一步只是把候选列表**过滤**到看得见的几条；
    真正的提交是随后点中候选项（``build_pick_spec_value_expression``）。
    契约实测：往输入框里打自由文本并回车**不会**加入任何值。

    ⚠️ 弹层可能有多个，认**最后一个可见的**（与选规格值一致）——
    点击属性行之后新开的那个排在最后。
    """

    return """
(() => {{
  const KEYWORD = {keyword_literal};
  const pops = Array.from(document.querySelectorAll('.next-select-popup-wrap'))
    .filter(e => e.getBoundingClientRect().height > 0);
  if (!pops.length) return {{ ok: false, reason: 'no_popup' }};
  const pop = pops[pops.length - 1];
  const input = pop.querySelector('input');
  if (!input) return {{ ok: false, reason: 'no_search_input' }};
  const box = input.getBoundingClientRect();
  if (box.width <= 0 || box.height <= 0) return {{ ok: false, reason: 'search_not_visible' }};

  const proto = input.tagName === 'TEXTAREA'
    ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  input.focus();
  setter.call(input, KEYWORD);
  input.dispatchEvent(new Event('input', {{ bubbles: true }}));
  input.dispatchEvent(new Event('change', {{ bubbles: true }}));
  return {{ ok: true, typed: input.value }};
}})()
""".format(keyword_literal=_value_literal(keyword))



def build_read_prop_value_expression(label: str, *, exact_only: bool = False) -> str:
    """生成「读回一个类目属性当前值」的表达式。

    ⚠️ **两种控件的值不在同一个地方：**

    * ``sell-o-combobox``（品牌）——值在 ``input.value``；
    * ``sell-o-select``（适用季节、适用性别）——``input`` 是 ``readonly``、
      value 恒空，值显示在 ``.next-select-values`` 的 ``em[title]`` 里。

    只读 input 的话，后者会被判成「没选上」——**假失败**（实测踩过）。
    """

    return """
(() => {{
  const LABEL = {label_literal};
  // ⚠️ **两种行结构都要试**（同 `build_open_prop_dropdown_expression`）：
  // 属性行会随页面状态落在不同结构里，写死一种就会在另一种下读不到。
  const PROFILES = [
    {{ row: ".sell-component-info-wrapper-wrap",
      labelSel: ".sell-component-info-wrapper-label" }},
    {{ row: ".sell-catProp-item-common", labelSel: "label" }},
  ];
  const labelOf = (el, sel) => {{
    const t = el.querySelector(sel);
    return t ? (t.textContent || '').trim() : '';
  }};
  let row = null;
  for (const prof of PROFILES) {{
    const rows = Array.from(document.querySelectorAll(prof.row));
    let hits = rows.filter(r => labelOf(r, prof.labelSel) === LABEL);
    if (!{exact_only} && hits.length === 0) hits = rows.filter(r => labelOf(r, prof.labelSel).startsWith(LABEL));
    if (hits.length === 1) {{ row = hits[0]; break; }}
  }}
  if (!row) return {{ ok: false, hitCount: 0 }};
  const values = row.querySelector('.next-select-values');
  if (values) {{
    // ⚠️ **必须先把 placeholder 摘掉再读文本。**
    // `.next-select-values` 里同时可能有占位符（`.next-select-placeholder`，文案「请选择」）
    // 和真实值；直接读 `textContent` 会把两者拼在一起，导致"明明选了却读不到"
    // （实测「品牌」回读成空/错值）。占位符类是 `.next-select-placeholder` / `.next-placeholder`。
    const copy = values.cloneNode(true);
    copy.querySelectorAll('.next-select-placeholder,.next-placeholder').forEach(n => n.remove());
    const text = (copy.textContent || '').trim();
    if (text) {{
      // ⚠️ **多选控件的汇总显示不是值本身**：「适用场景」这类多选（最多 9 项）选中后，
      // 文本是 `已选择 1/9 项全天候穿戴`——`已选择 N/M 项` 是汇总前缀，后面拼的才是
      // 选中值。不剥掉的话回读永远不等于目标值，填对了也报 FIELD_MISMATCH
      // （2026-10-08 真机长筒袜类目实测）。
      const multi = text.match(/^已选择\s*\d+\s*\/\s*\d+\s*项/);
      return {{ ok: true, value: multi ? text.slice(multi[0].length) : text,
               from: multi ? 'values_multi' : 'values' }};
    }}
    // 占位符之外没有文本时，值也可能只存在于 `em[title]` 上
    const titled = values.querySelector('em[title]');
    if (titled) {{
      const title = (titled.getAttribute('title') || '').trim();
      if (title) return {{ ok: true, value: title, from: 'values_title' }};
    }}
  }}
  const select = row.querySelector('select');
  if (select) {{
    const selected = select.selectedOptions;
    if (selected.length !== 1 || !select.value || !select.validity.valid) return {{ok:true,value:''}};
    return {{ok:true,value:(selected[0].textContent || '').trim(),from:'native_select'}};
  }}
  const input = row.querySelector('input,textarea');
  if (input && input.value) return {{ ok: true, value: input.value, from: 'input' }};
  const em = row.querySelector('.next-select-values em, em[title]');
  if (em) {{
    return {{ ok: true, value: (em.getAttribute('title') || em.textContent || '').trim(),
             from: 'em' }};
  }}
  return {{ ok: true, value: '', from: 'none' }};
}})()
""".format(
        label_literal=_value_literal(label),
        exact_only=json.dumps(exact_only),
    )



def build_read_required_properties_expression() -> str:
    """读取当前可见类目属性的 ``label.required`` 标记；不推断其它类目的字段。"""

    return """
(() => {{
  const ROW = {row};
  const visible = el => {{ const box = el.getBoundingClientRect(); return box.width > 0 && box.height > 0; }};
  const rows = Array.from(document.querySelectorAll(ROW)).filter(visible);
  const labels = rows.map(row => {{
    const label = row.querySelector('label');
    return label && label.closest(ROW) === row ? (label.textContent || '').trim() : '';
  }});
  const required = [];
  rows.forEach((row, index) => {{
    const label = row.querySelector('label');
    if (!label || !label.matches('label.required')) return;
    const input = row.querySelector('input,textarea');
    const type = input ? String(input.type || 'text').toLowerCase() : '';
    const supported = Boolean(row.querySelector('.next-select-values,select,textarea')
      || (input && ['text', 'search', 'number'].includes(type)));
    required.push({{ label: labels[index], hitCount: labels.filter(text => text === labels[index]).length,
                     supportedReader: supported }});
  }});
  return {{ known: rows.length > 0 && labels.every(Boolean),
            scope: 'visible_property_label_required', completePage: false,
            rowCount: rows.length, required: required }};
}})()
""".format(row=_value_literal(locating.PROPERTY_ROW.row_selector))


def read_required_properties(client: "PageClient") -> Dict[str, Any]:
    """读**当前页面标了 `*` 的必填项事实**；未知时显式 ``known=False``，不伪装成零个必填。

    ⚠️ **这里改为复用 `required_fields` 的读取器。**
    原先本函数自带一套实现（`:func:`build_read_required_properties_expression`），
    只认旧行结构 ``.sell-catProp-item-common`` + ``label.required``。而当前的填写页
    用的是 ``.sell-component-info-wrapper-wrap`` + **独立标记元素**
    ``.sell-component-info-wrapper-required``——于是它实测返回 ``known=False``，
    在链尾报「没有读到完整、可识别的当前类目属性行与必填标记事实」（E-258）。

    **两套读取器分叉就是这一整轮 `readback` 报假的根因**：写入侧用的是新的
    `required_fields`，回读侧用的是旧的这一套。现在只留**一套**（`required_fields`），
    它已被真机验证：17/17 必填项能被识别、0 个未归属必填控件。
    """

    from . import required_fields

    payload = required_fields.read(client)
    if payload.get("known") is not True:
        return {"known": False, "scope": "visible_property_label_required",
                "completePage": False, "required": [],
                "reason": payload.get("reason")
                          or "没有读到完整、可识别的当前类目属性行与必填标记事实"}
    return payload


def build_read_required_form_expression() -> str:
    from .required_fields import expression
    return expression()


def read_required_form(client: "PageClient") -> Dict[str, Any]:
    from .required_fields import read
    return read(client)


def wait_for_prop_row(client: "PageClient", label: str, *,
                      timeout: float = 20.0, interval: float = 1.0) -> Dict[str, Any]:
    """等某个**类目属性行**渲染出来，返回 :func:`classify_row` 的结果。

    ⚠️ **「类目属性」块比表单行渲染得晚。** 实测：`select_category` 刚导航到填写页时，
    `wait_for_publish_form` 已经能数到行，但紧接着的 `fill_props` 找「品牌」
    报 `label_not_found`——而几秒后它就在那里。

    这与 `_open_publish_page` 那个交接缺陷是**同一个问题的深一层**：
    等到了「页面有行」不等于「要的那一行在了」。

    超时返回最后一次的分类结果（`not_located`），由调用方决定怎么报。
    """

    deadline = time.time() + max(0.0, timeout)
    shape = classify_row(client, label)
    while not shape.get("located") and time.time() < deadline:
        time.sleep(interval)
        shape = classify_row(client, label)
    return shape


def read_prop_value(client: "PageClient", label: str, *, exact_only: bool = False) -> Optional[str]:
    """读回一个**类目属性**当前的值。

    ⚠️ **必须回读。**「点中了候选」不等于「字段被接受了」——
    契约实测下拉「选了未必生效」。而属性行的值**不在 ``textContent`` 里**
    （input 的 value 不进 textContent），所以要看构造器里那三个位置。
    """

    payload = client.evaluate(build_read_prop_value_expression(label, exact_only=True) if exact_only else build_read_prop_value_expression(label))
    if not isinstance(payload, dict) or not payload.get("ok"):
        return None
    return payload.get("value")


def pick_prop_value(client: "PageClient", label: str, value: str, *,
                    wait: float = 1.2, exact_only: bool = False,
                    readback_timeout: float = 6.0) -> Dict[str, Any]:
    """给一个**类目属性**选值：打开它的下拉 → 在候选中精确点中。

    **候选必须来自平台**——往输入框里打自由文本不会提交值
    （契约实测：往「主色(必选)」输入自由文本并回车，计数仍是 0）。
    所以这里只「点开 + 点候选」，不做任何自由输入。

    :param readback_timeout: **值提交回属性行**的等待上限（秒）。平台提交是异步的，
        点中候选后行上可能还是旧值；这里在**目标值本身**上轮询，轮完仍不相等才失败。
        见下方 E-283 的说明。
    """

    opened = client.evaluate(build_open_prop_dropdown_expression(label, exact_only=True) if exact_only else build_open_prop_dropdown_expression(label))
    if not isinstance(opened, dict) or not opened.get("ok"):
        raise CandidateNotFound(
            "打开属性 {!r} 的下拉失败：{}".format(
                label, json.dumps(opened, ensure_ascii=False)[:200] if opened else "无返回"))
    time.sleep(wait)

    # 搜索框里输入**完整值**做过滤——实测 '无品牌/无注册商标' 能精确过滤到 1 条。
    # ⚠️ 这一步**不提交任何值**，只是把候选列表缩小到看得见。
    searched = client.evaluate(build_search_prop_options_expression(value))
    if not isinstance(searched, dict) or not searched.get("ok"):
        raise CandidateNotFound(
            "在属性 {!r} 的下拉里搜索 {!r} 失败：{}".format(
                label, value, json.dumps(searched, ensure_ascii=False)[:200] if searched else "无返回"))
    time.sleep(wait)

    payload = client.evaluate(build_pick_spec_value_expression(value))
    if not isinstance(payload, dict) or not payload.get("ok"):
        # **拒绝自由文本兜底**：候选里没有就是没有，不硬填。
        raise OptionNotFound(
            "属性 {!r} 的候选里没有精确匹配 {!r}：{}".format(
                label, value, json.dumps(payload, ensure_ascii=False)[:260] if payload else "无返回"))
    time.sleep(wait)

    # ⚠️ **必须回读。**「点中了候选」不等于「字段被接受了」——
    # 契约实测下拉「选了未必生效」。属性行的值不在 textContent 里，
    # 所以直接读该行 input 的 value。
    #
    # ⚠️ **但回读要轮询，不能只读一次。**（E-283）
    #
    # 平台把选中值提交回属性行是**异步**的：`time.sleep(wait)` 用完的那一刻，
    # 行上可能还是**旧值**。早先这里只读一次、不等就抛 `FieldMismatchError`，
    # 于是「写了但没生效」被记成失败——正是用户报的「属性要填两次才成功」，
    # 也是 `fill_required_attrs` 偶发报「必填项填完之后仍为空」的机制。
    #
    # 与 E-277（选图器判据）是同一类病：**在异步操作上只查一次**。
    # 修法同样是"在既定上限内轮询**目标值本身**"，而不是把固定等待调大；
    # 轮完仍不相等就**如实抛**——不兜底、不吞错、不静默改小目标值。
    deadline = time.monotonic() + max(0.0, readback_timeout)
    read_back = read_prop_value(client, label, exact_only=True) if exact_only else read_prop_value(client, label)
    while read_back != value and time.monotonic() < deadline:
        time.sleep(0.25)
        read_back = read_prop_value(client, label, exact_only=True) if exact_only else read_prop_value(client, label)
    if read_back != value:
        raise FieldMismatchError(
            "属性 {!r} 回读不一致：期望 {!r}，实际 {!r}".format(label, value, read_back))
    return {**payload, "read_back": read_back}


def pick_spec_value(client: "PageClient", attr_name: str, value: str, *, wait: float = 1.2) -> Dict[str, Any]:
    """给某个销售属性选一个值。

    链路：点**最后一行**的输入 → 在**最后一个**弹层里点中候选。
    点中即提交（不需要回车或失焦）。
    """

    opened = client.evaluate(build_open_spec_value_input_expression(attr_name))
    if not isinstance(opened, dict) or not opened.get("ok"):
        raise CandidateNotFound("打开属性 {!r} 的值输入失败：{}".format(
            attr_name, json.dumps(opened, ensure_ascii=False)[:160] if opened else "无返回"))
    time.sleep(wait)

    payload = client.evaluate(build_pick_spec_value_expression(value))
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise OptionNotFound("属性 {!r} 的候选里没有精确匹配 {!r}：{}".format(
            attr_name, value, json.dumps(payload, ensure_ascii=False)[:200] if payload else "无返回"))
    time.sleep(wait)
    return payload


def set_prop_selected(client: "PageClient", attr_name: str, selected: bool, *, wait: float = 1.0) -> Dict[str, Any]:
    """勾选 / 取消勾选某个销售属性。已是目标状态时不做动作。"""

    payload = client.evaluate(build_set_prop_selected_expression(attr_name, selected))
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise CandidateNotFound("设置属性 {!r} 的勾选状态失败：{}".format(
            attr_name, json.dumps(payload, ensure_ascii=False)[:160] if payload else "无返回"))
    time.sleep(wait)
    return payload


def confirm_sku_creation(client: "PageClient") -> Dict[str, Any]:
    """点「确认创建」。

    ⚠️ **这一步会静默失败**（E-097）：只要有一个已勾选属性没有值，
    抽屉就不关、表格不出现、**也不报错**。调用方必须靠
    :func:`wait_for_sku_table` 判断成败，不能靠「点到了」。
    """

    payload = client.evaluate(build_confirm_sku_expression())
    if not isinstance(payload, dict):
        raise PageError("点「确认创建」时页面没有返回可解析的结果")
    if not payload.get("ok"):
        raise PageError("「{}」不可点（{}）".format(SKU_CONFIRM_TEXT, payload.get("reason")))
    return payload


def read_sku_table(client: "PageClient") -> Dict[str, Any]:
    """读 SKU 表格。**只读。**"""

    payload = client.evaluate(build_read_sku_table_expression())
    return payload if isinstance(payload, dict) else {"found": False}


def wait_for_sku_table(
    client: "PageClient", *, expected_rows: int = 0, timeout: float = 20.0, interval: float = 1.0
) -> Dict[str, Any]:
    """等 SKU 表格出现。

    **这是「确认创建」是否成功的唯一可靠判据。** 成功时抽屉关闭、表格出现；
    失败时（E-097）抽屉一直开着且不报错——所以只能等表格。

    :param expected_rows: 期望的行数；>0 时要求行数相等
    """

    deadline = time.time() + max(2.0, timeout)
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        last = read_sku_table(client)
        rows = int(last.get("rowCount") or 0)
        if rows > 0 and last.get("tableCount"):
            if expected_rows <= 0 or rows == expected_rows:
                return last
        # 抽屉关了但没表格 —— 说明被取消了，没必要再等
        if not last.get("drawerOpen") and not last.get("tableCount"):
            return last
        time.sleep(interval)
    return last


# ---------------------------------------------------------------------------
# 图片上传：素材中心弹层
# ---------------------------------------------------------------------------
#: 主图空位。点它打开素材中心弹层。
MEDIA_SLOT = ".image-empty"

#: 素材中心弹层容器。
MEDIA_POPUP = ".sell-component-image-v2-media-popup"

#: 素材中心 iframe 的 URL 特征。
#:
#: ⚠️ **按 URL 匹配 frame，不能按 origin**：``market.m.taobao.com`` 下有 3 个
#: iframe（详情预览 / 服务大厅 / 素材中心），按 origin 会挑错。
MEDIA_IFRAME_URL_HINT = "sucai-selector-ng"

#: 素材中心里的「本地上传」入口文本。
MEDIA_LOCAL_UPLOAD_TEXT = "本地上传"

#: 素材中心里的「图片空间」入口文本。
MEDIA_SPACE_TEXT = "图片空间"

#: 素材中心的 file input（**按需创建**，点「本地上传」之前不存在）。
MEDIA_FILE_INPUT = 'input[type="file"]'

#: 上传面板的「完成」按钮文本。
#:
#: ⚠️ **这是上传真正落库的关键一步**（E-123）：面板里每个文件都会带
#: `next-icon-success` 成功图标、文案也有「上传成功」，但**不点「完成」，
#: 图就不会进图片空间**——实测空间里 144 张卡片一张都没有它们。
#:
#: 上一轮之所以没发现它，是因为探测脚本的关键词列表里**没有「完成」**
#: （只找了「上传/确定/确认/开始上传/上传至」），于是报「面板内按钮 0 个」。
MEDIA_FINISH_TEXT = "完成"

#: 上传面板容器的类名子串（同样带 CSS Modules 哈希后缀，用子串匹配）。
MEDIA_UPLOAD_PANEL = '[class*="UploadPanel_uploadPanel"]'



def build_count_publish_rows_expression() -> str:
    """生成「数一数填写页渲染出了多少行」的表达式。**只读。**"""

    return """
(() => {{
  const rows = Array.from(document.querySelectorAll({root}));
  const visible = rows.filter(el => el.getBoundingClientRect().height > 0);
  return {{ total: rows.length, visible: visible.length }};
}})()
""".format(root=_value_literal(WORKBENCH_ROOT))


def wait_for_publish_form(client: "PageClient", *, timeout: float = 30.0,
                          interval: float = 1.0) -> int:
    """等**填写页真正渲染出来**，返回可见的填写行数。

    为什么需要它：`select_category` 选中类目后会**导航到填写页**，
    而紧接着的阶段可能在页面还没渲染完时就开始找元素——
    实测 46 毫秒后就去找主图区，报 `no_area`（而页面几秒后完全正常）。
    """

    deadline = time.time() + max(3.0, timeout)
    last = 0
    while time.time() < deadline:
        payload = client.evaluate(build_count_publish_rows_expression())
        last = int((payload or {}).get("visible") or 0)
        if last > 0:
            # 再多给一拍，让主图区这类靠后渲染的区块也出来
            time.sleep(1.5)
            return last
        time.sleep(interval)
    return last


def build_open_media_popup_expression(image_kind: str = "1:1主图") -> str:
    """生成「点主图空位，打开素材中心弹层」的表达式。

    弹层已经开着时直接返回成功——重复点空位会把已选的图清掉。
    """

    return """
(() => {{
  const KIND = {kind};
  const POPUP = {popup};
  // ⚠️ **判「可见」，不是判「存在」**：弹层关闭后节点仍留在 DOM 里（只是隐藏），
  // 用 querySelector 判存在会永远返回 already——弹层从没真正打开，
  // 后续选图全部落空（实测踩过：连选 5 张，主图位一个没变）。
  const existing = document.querySelector(POPUP);
  if (existing && existing.getBoundingClientRect().height > 0) {{
    return {{ ok: true, already: true }};
  }}

  const areas = Array.from(document.querySelectorAll({row}))
    .filter(el => {{
      const label = el.querySelector({label});
      return label && label.closest({row}) === el && (label.textContent || '').trim() === KIND;
    }});
  if (areas.length !== 1) return {{ ok: false, reason: 'area_not_unique', kind: KIND,
                                  hitCount: areas.length }};
  const area = areas[0];
  const slot = area.querySelector({slot});
  if (!slot) return {{ ok: false, reason: 'no_slot', kind: KIND }};
  const r = slot.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return {{ ok: false, reason: 'slot_not_visible' }};
  slot.click();
  return {{ ok: true, already: false }};
}})()
""".format(
        row=_value_literal(locating.ROW_SELECTOR),
        label=_value_literal(locating.LABEL_SELECTOR),
        kind=_value_literal(image_kind),
        popup=_value_literal(MEDIA_POPUP),
        slot=_value_literal(MEDIA_SLOT),
    )


def build_read_media_popup_expression() -> str:
    """生成「读素材中心弹层状态」的表达式。**只读。**"""

    return """
(() => {{
  const pop = document.querySelector({popup});
  if (!pop) return {{ open: false }};
  const r = pop.getBoundingClientRect();
  return {{
    open: r.height > 0,
    className: String(pop.className).slice(0, 100),
    text: (pop.textContent || '').trim().slice(0, 160),
    iframes: Array.from(pop.querySelectorAll('iframe')).map(f => String(f.src || '')),
    // 弹层里**没有** file input——一切发生在 iframe 里
    fileInputs: pop.querySelectorAll('input[type="file"]').length,
  }};
}})()
""".format(popup=_value_literal(MEDIA_POPUP))


def build_click_media_entry_expression(text: str) -> str:
    """生成「在素材中心 iframe 里点某个入口（本地上传 / 图片空间）」的表达式。

    **必须在 iframe 的上下文里跑**（用 ``context_id``）。在主 frame 里跑永远找不到。
    """

    return """
(() => {{
  const TEXT = {text};
  const els = Array.from(document.querySelectorAll('button, [role="button"], .next-btn, span, div'))
    .filter(e => (e.textContent || '').trim() === TEXT
                 && e.getBoundingClientRect().height > 0);
  if (!els.length) return {{ ok: false, reason: 'not_found', text: TEXT }};
  // 取最内层那个：外层容器文本也等于目标文本，点它不触发 handler
  const target = els[els.length - 1];
  target.click();
  return {{ ok: true, tag: target.tagName.toLowerCase() }};
}})()
""".format(text=_value_literal(text))


def build_read_media_file_input_expression() -> str:
    """生成「读素材中心 iframe 里的 file input」的表达式。**只读。**"""

    return """
(() => {{
  const inputs = Array.from(document.querySelectorAll({selector}));
  return {{
    count: inputs.length,
    inputs: inputs.map(el => ({{
      accept: el.getAttribute('accept') || '',
      multiple: el.multiple === true,
      directory: el.hasAttribute('webkitdirectory'),
      disabled: el.disabled === true,
      visible: el.getBoundingClientRect().height > 0,
    }})),
  }};
}})()
""".format(selector=_value_literal(MEDIA_FILE_INPUT))


def build_read_media_space_images_expression(limit: int = 500) -> str:
    """生成「读图片空间里当前的图片名」的表达式。**只读。**

    ⚠️ **这个列表是虚拟化的**（实测：容器 `h=5419` 而可视区 `client=384`，
    页面里 271 个 `img`），所以它**只能读到当前渲染出来的那部分**。
    早先这里写死了 ``.slice(0, 80)``，于是**恰好返回 80 个**——
    新上传的图排在窗口之外时就「看不见」，让人误以为上传失败（实测踩过）。

    因此：**判断某张图在不在空间里，别用这个函数，用
    :func:`build_has_media_image_expression`** ——后者按文件名在整页 DOM 里查找，
    不受虚拟化与数量上限影响。
    """

    return """
(() => {{
  const names = Array.from(document.querySelectorAll(
    'img[alt], [class*="name"], [class*="title"], [class*="fileName"], [class*="item"]'))
    .map(el => (el.getAttribute && el.getAttribute('alt')) || (el.textContent || '').trim())
    .map(t => String(t || '').trim())
    .filter(t => t && t.length <= 60 && /\\.(jpg|jpeg|png|gif|webp|heic)$/i.test(t));
  const unique = [...new Set(names)];
  return {{ count: unique.length, names: unique.slice(0, {limit}) }};
}})()
""".format(limit=int(limit))


def build_has_media_image_expression(name: str) -> str:
    """生成「某张图**真的在图片空间里**」的表达式。**只读。**

    按文件名在整页 DOM 里查找，**不受虚拟化与数量上限影响**。

    ⚠️ **必须先把「上传面板」整棵子树摘掉再查。**

    E-121 记过这个陷阱：``document.body.innerHTML.includes(name)`` 会命中
    **上传面板队列里的文件名**，而不是空间里的图。当时只写进了文档没修代码，
    后果是实机踩出来的——

    * ``upload_files_to_media`` 在「完成」**还没点**的时候就报 ``arrived: true``；
    * 于是「上传成功」实际上只是「文件进了队列」；
    * 真出问题时，错误会以别处的 ``no_match`` 冒出来，**离原因很远**（本轮实测：
      明明报的是「选图找不到」，真实原因是图根本没落库）。

    所以这里把带 ``UploadPanel`` 的节点整棵删掉再取 ``innerHTML``。
    """

    return """
(() => {{
  const NAME = {name};
  if (!document.body) return {{ name: NAME, inHtml: false, inText: false }};

  // 克隆一份再把上传面板摘掉——**不动真实 DOM**，这是只读探针。
  const clone = document.body.cloneNode(true);
  const panels = clone.querySelectorAll('[class*="UploadPanel"]');
  for (let i = panels.length - 1; i >= 0; i--) {{
    const node = panels[i];
    if (node.parentNode) node.parentNode.removeChild(node);
  }}
  const html = clone.innerHTML;
  const text = clone.innerText || clone.textContent || '';

  return {{
    name: NAME,
    inHtml: html.includes(NAME),
    inText: text.includes(NAME),
    // 顺带报一下队列里有没有——调用方想知道「是不是只是排上队了」时用得上。
    queuedOnly: !html.includes(NAME)
      && (document.body.innerHTML || '').includes(NAME),
  }};
}})()
""".format(name=_value_literal(name))


def wait_for_media_popup_ready(client: "PageClient", *, timeout: float = 5.0,
                               interval: float = 0.15) -> Dict[str, Any]:
    """轮询到**素材中心弹层真的可用**为止。

    ⚠️ **当前不用于主图选图**（保留给"已经知道就绪形态"的调用方）。
    实测教训（E-264）：把主图选图的固定 `sleep(3.0)` 换成"早点返回"是**错的**——
    弹层"画出来了 + iframe 上下文有了"之后，**图库自身仍在初始化**，
    此时去读卡片会命中**多个 scroller**（`scroller_not_unique`），
    或读到无效的目录上下文（`图片目录读取失败：上下文无效`）。

    也就是说那个 3 秒等的是**图库就绪**，而我当时**找不到比"固定等"更可靠的判据**——
    与其用一个测不准的判据把它换成偶发失败，不如老实保留固定等待。
    真正的提速点不在这里（见 `wait_for_main_image_slots` 的资源标识比较修复）。
    """

    deadline = time.time() + max(0.5, timeout)
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        last = read_media_popup(client)
        if last.get("open"):
            try:
                context_id = media_iframe_context(client, timeout=min(2.0, max(0.5, timeout)))
            except Exception:  # noqa: BLE001 - 上下文还没好，继续轮询
                context_id = None
            if context_id is not None:
                return {**last, "contextId": context_id}
        time.sleep(interval)
    return last


def open_media_popup(client: "PageClient", *, image_kind: str = "1:1主图",
                     wait: float = 3.0) -> Dict[str, Any]:
    """点主图空位打开素材中心弹层。

    ⚠️ **先等填写页渲染出来**：上一步 `select_category` 会导航到填写页，
    紧接着就找主图区会报 `no_area`（实测只隔了 46 毫秒）。

    ⚠️ **`wait` 保持固定等待，不要改成"早点返回"**（E-264 实测教训）：
    这 3 秒等的是**图库自身就绪**——弹层画出来、iframe 上下文可建之后，
    图库还在初始化，此时读卡片会 `scroller_not_unique`，或 directory 上下文无效。
    试过按"弹层 open + iframe 出现"就返回，两次真机都当场失败。
    """

    wait_for_publish_form(client)
    payload = client.evaluate(build_open_media_popup_expression(image_kind))
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise CandidateNotFound("打开图片选择弹层失败：{}".format(
            json.dumps(payload, ensure_ascii=False)[:160] if payload else "无返回"))
    time.sleep(wait)
    return payload


def read_media_popup(client: "PageClient") -> Dict[str, Any]:
    """读素材中心弹层状态。**只读。**"""

    payload = client.evaluate(build_read_media_popup_expression())
    if not isinstance(payload, dict) or type(payload.get('open')) is not bool:
        raise PageError('无法确认素材选择弹层的打开状态')
    return payload


def media_iframe_context(client: "PageClient", *, timeout: float = 10.0,
                         stage: Optional[str] = None) -> int:
    """取素材中心 iframe 的执行上下文 id。

    **按 frame URL 匹配**（``sucai-selector-ng``），不按 origin。

    :param stage: 可选阶段名（``upload_images`` / ``fill_skus`` / ``fill_detail``）。
    """

    deadline = time.time() + max(2.0, timeout)
    context_id = None
    while time.time() < deadline and context_id is None:
        context_id = client.find_frame_context(MEDIA_IFRAME_URL_HINT, timeout=4.0)
        if context_id is None:
            # 事件时序不可靠时的确定性后备：按 frameId 直接建一个隔离世界。
            frame_id = client.frame_id_for_url(MEDIA_IFRAME_URL_HINT, timeout=4.0)
            if frame_id:
                context_id = client.create_frame_context(frame_id)
        if context_id is None:
            time.sleep(0.8)
    if context_id is None:
        raise CandidateNotFound(_picker_failure(
            'media_iframe_context', MEDIA_IFRAME_URL_HINT, None, stage=stage,
            note='（找不到素材中心的执行上下文：按 frame URL 含该标识去匹配）',
            action='关掉选图器弹层重新打开后，再点一次「开始淘宝发布」'))
    return context_id


def click_media_entry(client: "PageClient", text: str, *, context_id: int,
                      wait: float = 2.0) -> Dict[str, Any]:
    """在素材中心 iframe 里点一个入口。"""

    payload = client.evaluate(build_click_media_entry_expression(text),
                              context_id=context_id)
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise CandidateNotFound("素材中心里没有可点的 {!r}：{}".format(
            text, json.dumps(payload, ensure_ascii=False)[:160] if payload else "无返回"))
    time.sleep(wait)
    return payload



def build_click_media_finish_expression() -> str:
    """生成「点上传面板的『完成』」的表达式。

    **不点它，上传就不落库**（E-123）——面板会一直显示成功图标，
    而图片空间里什么都没有。
    """

    return """
(() => {{
  const TEXT = {text};
  const PANEL = {panel};
  const panels = Array.from(document.querySelectorAll(PANEL)).filter(el=>el.getBoundingClientRect().height>0);
  if(panels.length!==1)return {{ok:false,reason:'upload_panel_not_unique'}};
  const scope = panels[0];
  const btns = Array.from(scope.querySelectorAll('button, [role=button], .next-btn'))
    .filter(b => (b.textContent || '').trim() === TEXT
                 && b.getBoundingClientRect().height > 0);
  if (btns.length !== 1) {{
    return {{ ok: false, reason: btns.length === 0 ? 'not_found' : 'ambiguous',
             hitCount: btns.length,
             seen: Array.from(scope.querySelectorAll('button'))
               .map(b => (b.textContent || '').trim()).filter(Boolean).slice(0, 12) }};
  }}
  if (btns[0].disabled) return {{ ok: false, reason: 'disabled' }};
  btns[0].click();
  return {{ ok: true }};
}})()
""".format(text=_value_literal(MEDIA_FINISH_TEXT), panel=_value_literal(MEDIA_UPLOAD_PANEL))


def click_media_finish(client: "PageClient", *, context_id: int, wait: float = 3.0) -> Dict[str, Any]:
    """点上传面板的「完成」。**上传落库的最后一步。**"""

    payload = client.evaluate(build_click_media_finish_expression(), context_id=context_id)
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise CandidateNotFound("上传面板里没有可点的「{}」：{}".format(
            MEDIA_FINISH_TEXT,
            json.dumps(payload, ensure_ascii=False)[:200] if payload else "无返回"))
    time.sleep(wait)
    return payload



def build_read_media_queue_expression() -> str:
    """生成「读上传队列每一项的状态」的表达式。**只读。**

    为什么需要它：``upload_files_to_media`` 早先只看「文件名出现在 DOM 里」，
    于是平台把文件放进队列时就算「成功」——**而队列里的项可能是失败状态**
    （实测：``操作过于频繁，请滑动验证码之后，重新上传。``）。

    返回每项的 ``name`` / ``state``（``success`` / ``error`` / ``loading`` / ``unknown``）
    / ``desc``（平台给的说明文案，失败时就是原因）。
    """

    return r"""
(() => {{
  const panels = Array.from(document.querySelectorAll('[class*="UploadPanel_uploadPanel"]'))
    .filter(el=>el.getBoundingClientRect().height>0);
  if(panels.length!==1)return {{ok:false,reason:'upload_panel_not_unique'}};
  const items = Array.from(panels[0].querySelectorAll('[class*="UploadPanel_fileItem"]'));
  const uploading = Array.from(panels[0].querySelectorAll('div,span'))
    .some(el=>el.getBoundingClientRect().height>0 && /^\d+\s*个文件上传中[.。…]*$/.test((el.textContent||'').trim()));
  return {{
    count: items.length,
    uploading,
    items: items.map((el, index) => {{
      const nameEl = el.querySelector('[class*="UploadPanel_fileName"]');
      const descEl = el.querySelector('[class*="UploadPanel_fileDesc"]');
      const stateEl = el.querySelector('[class*="UploadPanel_fileState"]');
      const icon = stateEl ? stateEl.querySelector('i') : null;
      const iconClass = icon ? String(icon.className || '') : '';
      let state = 'unknown';
      if (iconClass.indexOf('next-icon-success') >= 0) state = 'success';
      else if (iconClass.indexOf('next-icon-error') >= 0) state = 'error';
      else if (iconClass.indexOf('next-icon-loading') >= 0) state = 'loading';
      return {{
        index: index,
        name: nameEl ? (nameEl.textContent || '').trim() : '',
        state: state,
        desc: descEl ? (descEl.textContent || '').trim().slice(0, 200) : '',
        iconClass: iconClass.slice(0, 60),
      }};
    }}),
  }};
}})()
""".format()


def read_media_queue_state(client: "PageClient", *, context_id: int) -> Dict[str, Any]:
    """读上传队列里每一项的状态。**只读。**"""

    payload = client.evaluate(build_read_media_queue_expression(), context_id=context_id)
    if not isinstance(payload, dict) or payload.get('ok') is False:
        reason = payload.get('reason', '无有效结果') if isinstance(payload, dict) else '无有效结果'
        raise PageError('上传队列读取失败：' + str(reason))
    items = payload.get('items')
    if (not isinstance(items, list) or type(payload.get('count')) is not int
            or payload['count'] != len(items)
            or not all(isinstance(item, dict) and isinstance(item.get('name'), str)
                       and item.get('state') in ('success', 'error', 'loading', 'unknown') for item in items)):
        raise PageError('上传队列返回了不完整的文件状态，不能当作空队列等待')
    return payload


def wait_for_media_upload_queue(client, expected_names, *, context_id, timeout=120.0, interval=0.25):
    """等待本批逐文件成功且整批结束；完成前不以图库可见作为条件。"""
    wanted = list(expected_names)
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        queue = read_media_queue_state(client, context_id=context_id)
        rows = queue.get('items', [])
        matches = {name: [row for row in rows if row.get('name') == name] for name in wanted}
        if any(len(values) > 1 for values in matches.values()):
            raise PageError('上传队列出现本批同名重复项，无法确认逐文件状态')
        rejected = [name for name, values in matches.items() if values and values[0].get('state') == 'error']
        accepted = [name for name, values in matches.items() if values and values[0].get('state') == 'success']
        complete = len(accepted) == len(wanted) and queue.get('uploading') is not True
        if rejected or complete or time.monotonic() >= deadline:
            return {'ok': complete, 'confirmed': accepted,
                    'missing': [name for name in wanted if name not in accepted], 'queue': queue,
                    'rejected': rejected}
        time.sleep(interval)


def upload_files_to_media(client: "PageClient", files: Sequence[str], *,
                          context_id: int, wait: float = 4.0,
                          per_file_timeout: float = 120.0,
                          rename_to: Optional[Sequence[str]] = None,
                          expected_sha256: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """先复制整批素材并核对内容，再按原生输入能力批量发送；原文件保持不变。

    所有本地验证在点击上传入口之前完成，异常、平台拒绝及正常返回均清理快照。
    expected_sha256 绑定主图/SKU/详情的本次内容身份，不允许复制失败被旧队列转成成功。
    """
    sources = [str(path) for path in files]
    targets = list(rename_to) if rename_to is not None else [os.path.basename(path) for path in sources]
    if len(targets) != len(sources):
        raise PageError("rename_to 的长度必须与 files 一致")
    if not sources or len(set(targets)) != len(targets):
        raise PageError("上传文件为空或目标文件名重复")
    if any(not isinstance(name, str) or not name or name in ('.', '..')
           or os.path.basename(name) != name or any(char in name for char in '\\/:*?"<>|') for name in targets):
        raise PageError("上传目标必须是合法的单个文件名")
    expected = list(expected_sha256) if expected_sha256 is not None else None
    if expected is not None and (len(expected) != len(sources)
            or any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', value) for value in expected)):
        raise PageError("expected_sha256 必须与文件一一对应且为完整 SHA-256")
    temp_dir = tempfile.mkdtemp(prefix="tb-upload-")
    try:
        staged = []
        for index, (path, name) in enumerate(zip(sources, targets)):
            upload_path = os.path.join(temp_dir, name)
            shutil.copy2(path, upload_path)
            if expected is not None:
                with open(upload_path, 'rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if digest != expected[index].lower():
                    raise MediaSourceChangedError("本地图片内容在任务期间改变；本次尚未发送该批文件")
            staged.append(upload_path)
        return _upload_staged_files_to_media(client, staged, targets,
            source_names=[os.path.basename(path) for path in sources], context_id=context_id,
            wait=wait, per_file_timeout=per_file_timeout)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _upload_staged_files_to_media(client, files, targets, *, source_names,
                                  context_id, wait, per_file_timeout):
    """只消费本次已复制并验证的快照，不重读用户原图。"""
    click_media_entry(client, MEDIA_LOCAL_UPLOAD_TEXT, context_id=context_id, wait=wait)
    from .upload_panel import ensure_all_images
    destination = ensure_all_images(client, context_id=context_id)
    attempts: List[Dict[str, Any]] = []
    confirmed: List[str] = []
    failed: List[str] = []

    probe = client.evaluate(build_read_media_file_input_expression(), context_id=context_id)
    inputs = (probe or {}).get('inputs', [])
    if (probe or {}).get('count') != 1 or len(inputs) != 1 or inputs[0].get('disabled'):
        raise PageError('本地上传入口没有唯一可用的文件输入控件')
    if inputs[0].get('directory'):
        raise PageError('当前是整文件夹上传入口；云端目录创建规则尚未确认，未发送文件，请使用普通多文件上传入口')
    if inputs[0].get('multiple') is True:
        groups = [(list(files), list(targets))]
        mode = 'multiple_files'
    else:
        groups = [([path], [name]) for path, name in zip(files, targets)]
        mode = 'single_file'
    for paths, names in groups:
        record = {'files': names, 'fileInputCount': 1, 'mode': mode}
        record['set'] = client.set_file_input_files(paths, MEDIA_FILE_INPUT, context_id=context_id)
        accepted_batch = wait_for_media_upload_queue(
            client, names, context_id=context_id, timeout=per_file_timeout)
        record['accepted'] = accepted_batch['confirmed']
        attempts.append(record)
        confirmed.extend(accepted_batch['confirmed'])
        failed.extend(accepted_batch['missing'])
        if not accepted_batch['ok']:
            # 未接收的批次不重传，不用下一次上传掩盖本次丢文件/拒绝。
            failed.extend(name for name in targets if name not in confirmed and name not in failed)
            break

    # ⚠️ **点「完成」之前先看队列状态。**
    #
    # 早先只看「文件名出现在 DOM 里」就算成功，而队列里的项**可能是失败状态**——
    # 实测平台给的是「操作过于频繁，请滑动验证码之后，重新上传。」，
    # 而当时报的是 ``arrived: true`` / ``confirmed``。**平台拒绝了却报成功。**
    #
    # 这一层只如实报告，**不尝试绕过验证码**；人工处理之后重跑。
    queue = read_media_queue_state(client, context_id=context_id)

    # ⚠️ **只统计「本次设进去的那几个文件」。**
    #
    # 实机踩过：上传面板的队列会**跨尝试残留**——上一次失败留下的
    # `主图_01_1x1.jpg（state=error）` 还在，而本次传的文件是 `state=success`，
    # 于是整个调用被判成「平台拒绝」。那是**假失败**。
    #
    # 后果不只是误报：那个陈旧项会让**之后每一次上传都失败**，
    # 而重新开始并没有清理队列的路径。
    wanted_names = {str(name) for name in targets}

    # 队列里**不属于本次**的失败项单独报出来：它们不影响本次结论，
    # 但会一直堆着，值得让调用方看见。
    #
    # ⚠️ 这段必须紧跟读队列之后算——原先写在 `if rejected: return` **之后**，
    # 于是「平台拒绝」这条路径上它永远是空的（实机验证时发现的）。
    stale_rejected = [
        {"name": item.get("name"), "desc": item.get("desc")}
        for item in (queue.get("items") or [])
        if item.get("state") == "error"
        and str(item.get("name") or "") not in wanted_names
    ]
    rejected = [
        item for item in (queue.get("items") or [])
        if item.get("state") == "error" and str(item.get("name") or "") in wanted_names
    ]
    if rejected:
        reasons = "；".join(
            "{}：{}".format(item.get("name") or "（未命名）", item.get("desc") or "（平台未给原因）")
            for item in rejected[:3])
        return {
            "confirmed": [],
            "failed": [item.get("name") for item in rejected],
            "attempts": attempts,
            "queue": queue,
            "staleQueueErrors": stale_rejected,
            "finish": {},
            "rejectedByPlatform": True,
            "reason": reasons,
            "ok": False,
        }

    # 点击完成前重新核对全部文件。早先成功、现在缺失/加载中的项不能沿用旧状态。
    final_rows = {name: [row for row in queue['items'] if row['name'] == name] for name in targets}
    if any(len(rows) > 1 for rows in final_rows.values()):
        raise PageError('完成前上传队列出现本批同名重复项，未点击完成')
    confirmed = [name for name, rows in final_rows.items() if rows and rows[0]['state'] == 'success']
    failed = [name for name in targets if name not in confirmed]

    # **点「完成」让上传落库**（E-123）：不点它，文件只停在上传面板里，
    # 图片空间里什么都看不到，而面板上全是成功图标。
    finish: Dict[str, Any] = {}
    if confirmed and not failed and queue.get('uploading') is not True:
        try:
            finish = click_media_finish(client, context_id=context_id, wait=wait)
        except Exception as exc:  # noqa: BLE001
            finish = {"ok": False, "error": "{}: {}".format(type(exc).__name__, exc)}

    # **点完之后再核对**：这才是「落库确认」。
    # 队列说成功 ≠ 已经进了图片空间——中间隔着「完成」这一下。
    landed: List[str] = []
    if confirmed and finish.get("ok"):
        try:
            for name in confirmed:
                if media_image_exists(client, name, context_id=context_id):
                    landed.append(name)
        except Exception as exc:  # noqa: BLE001
            finish["landedError"] = "{}: {}".format(type(exc).__name__, exc)

    return {
        "confirmed": confirmed,
        "landed": landed,
        "failed": failed,
        "attempts": attempts,
        "queue": queue,
        "destination": destination['value'],
        "reason": "上传队列仍显示文件上传中，未点击完成" if queue.get('uploading') is True else "",
        "staleQueueErrors": stale_rejected,
        "finish": finish,
        # 成功 = **平台接受**（队列 success）**且**点了「完成」。
        # `landed` 单独报，因为「点了完成但读不到」可能是列表虚拟化，不一定是没落库。
        "ok": not failed and bool(confirmed) and bool(finish.get("ok")),
    }


def read_media_space_images(client: "PageClient", *, context_id: int) -> List[str]:
    """读图片空间里当前的图片名。**只读。**"""

    payload = client.evaluate(build_read_media_space_images_expression(),
                              context_id=context_id)
    return [str(n) for n in ((payload or {}).get("names") or [])]


def media_image_exists(client: "PageClient", name: str, *, context_id: int) -> bool:
    """上传过程的文件名到达信号，可能来自队列；不作为已入库素材回执。

    保留它供上传队列交接使用，避免先等入库再点完成形成死锁。
    业务缓存复用和图片选择统一使用 ``find_media_image`` / ``select_media_image``。
    """

    payload = client.evaluate(build_has_media_image_expression(name), context_id=context_id)
    return bool((payload or {}).get("inHtml") or (payload or {}).get("inText"))


def wait_for_media_images(client: "PageClient", expected_names: Sequence[str], *,
                          context_id: int, timeout: float = 120.0,
                          interval: float = 3.0) -> Dict[str, Any]:
    """等待上传名称到达；接收状态由队列确认，入库卡片在完成后严格查找。

    此函数不返回素材 URL，不能独立证明上传完成。上传器还会核对本批队列
    成功状态并点击完成；后续所有媒体处理均用完整文件名和 URL 定位入库卡片。
    """

    wanted = [str(n) for n in expected_names]
    deadline = time.time() + max(5.0, timeout)
    missing: List[str] = list(wanted)
    while time.time() < deadline:
        missing = [w for w in wanted if not media_image_exists(client, w, context_id=context_id)]
        if not missing:
            return {"ok": True, "confirmed": list(wanted), "missing": []}
        time.sleep(interval)
    return {"ok": False, "confirmed": [w for w in wanted if w not in missing], "missing": missing}


#: 图片空间里的一张图卡片。**点它即选中并回填主图位**，不需要确认按钮。
#:
#: ⚠️ **必须用子串匹配**：实测类名是 `PicList_pic_background__pGTdV`——
#: CSS Modules 的**哈希后缀**。写成 `.PicList_pic_background` 是**精确匹配**，
#: 永远匹配不上，表现为「卡片数 0、报 no_cards」，而列表里明明有图（实测踩过）。
MEDIA_IMAGE_CARD = '[class*="PicList_pic_background"]'

#: 素材中心页（``qn.taobao.com/.../sucai-tu``）里文件卡片的类名子串。
#:
#: ⚠️ **与选图器不是同一套 class**（真机 2026-10-10）：选图器卡片是
#: ``PicList_pic_background``，素材中心是 ``PicturesShow_..._main-document-show``。
#: 在素材中心页用选图器的选择器读文件，结果**恒为 0 张且 complete=true**——
#: 「目录里明明有图」会被判成空目录，进而重复上传同名素材（实测踩过）。
#:
#: ⚠️ 指向**同时含图片与文件名、且带 `id`（pictureId）的那个卡片 div**：
#: 素材中心里 ``PicturesShow_pic_background`` 只是卡片内部的图片区，名字是它的
#: 兄弟节点；指到那里会读不出文件名（``判据=directory_file_name_unconfirmed``）。
MEDIA_CENTER_FILE_CARD = '[class*="PicturesShow_main-document-show"]'

#: 主图位。空位里含 ``.image-empty``，已填位里是 ``img``。
MEDIA_MAIN_SLOT = ".sell-component-material-item-view"

#: 「宝贝详情」区里那个**模块编辑器**的宿主。
#:
#: ⚠️ **它里面一个 `contenteditable` 都没有**（实测 `editableCount: 0`）：
#: 新版详情是模块化编辑器（`add_item-NH_hk3` 加「图片/文字/源码导入/模板」模块），
#: 契约里 `[contenteditable="true"],textarea` 那种"原生 HTML 编辑区"
#: **在这个形态下不存在**——所以 `fill_detail` 会报 `detail_editor_not_unique`
#: （匹配 0 个）。要写详情必须先**切到旧版图文描述**（见下）。
DETAIL_MODULE_HOST = '.sell-component-lite-decoration-editor'

#: 切到旧版图文描述的按钮（干净的 `type="button"`，无 form、未禁用——已核实）。
#: 旧版才是可直接写 HTML 的编辑区。
DETAIL_LEGACY_BUTTON = 'button[class*="label_wrapper_right"]'


def build_read_detail_editor_state_expression() -> str:
    """读「宝贝详情」区当前是哪种编辑器形态、以及有没有可写编辑区。**只读。**"""

    return r'''(() => {
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      const rows = Array.from(document.querySelectorAll('.sell-component-info-wrapper-wrap')).filter(row => {
        const labels = row.querySelectorAll('.sell-component-info-wrapper-label');
        return labels.length === 1 && text(labels[0]).replace(/\s|\*/g, '') === '宝贝详情';
      });
      if (rows.length !== 1) return { ok: false, reason: 'detail_row_not_unique', rowCount: rows.length };
      const row = rows[0];
      const native = Array.from(row.querySelectorAll('[contenteditable="true"],textarea')).filter(visible);
      const moduleHost = row.querySelector(HOST_SELECTOR);
      const legacyButton = Array.from(row.querySelectorAll(BUTTON_SELECTOR))
        .filter(visible).filter(el => /旧版/.test(text(el)));
      return {
        ok: true,
        mode: native.length ? 'native' : (moduleHost ? 'module' : 'unknown'),
        nativeCount: native.length,
        nativeTags: native.map(el => el.tagName).slice(0, 5),
        moduleHost: Boolean(moduleHost),
        legacyButtons: legacyButton.length,
        legacyDisabled: legacyButton.length === 1
          ? (legacyButton[0].disabled === true || legacyButton[0].getAttribute('aria-disabled') === 'true')
          : null,
        legacyHasForm: legacyButton.length === 1 ? Boolean(legacyButton[0].form) : null,
      };
    })()'''.replace('HOST_SELECTOR', json.dumps(DETAIL_MODULE_HOST)) \
             .replace('BUTTON_SELECTOR', json.dumps(DETAIL_LEGACY_BUTTON))


def build_switch_detail_to_legacy_expression() -> str:
    """点「返回旧版图文描述」。**改变页面形态**，只在详情区为空时调用。"""

    return r'''(() => {
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      const rows = Array.from(document.querySelectorAll('.sell-component-info-wrapper-wrap')).filter(row => {
        const labels = row.querySelectorAll('.sell-component-info-wrapper-label');
        return labels.length === 1 && text(labels[0]).replace(/\s|\*/g, '') === '宝贝详情';
      });
      if (rows.length !== 1) return { ok: false, reason: 'detail_row_not_unique', rowCount: rows.length };
      const buttons = Array.from(rows[0].querySelectorAll(BUTTON_SELECTOR))
        .filter(visible).filter(el => /旧版/.test(text(el)));
      if (buttons.length !== 1) return { ok: false, reason: 'legacy_entry_not_unique', hitCount: buttons.length };
      const button = buttons[0];
      if (button.disabled === true || button.getAttribute('aria-disabled') === 'true')
        return { ok: false, reason: 'legacy_entry_disabled' };
      // 可能提交表单的控件一律不点（按钮本身已核实无 form，这里是二次守卫）
      if (button.form && button.type !== 'button') return { ok: false, reason: 'legacy_entry_may_submit' };
      button.click();
      return { ok: true };
    })()'''.replace('BUTTON_SELECTOR', json.dumps(DETAIL_LEGACY_BUTTON))


def read_detail_editor_state(client: "PageClient", *, timeout: float = 10.0) -> Dict[str, Any]:
    """读详情区编辑器形态。只读，不点。"""

    payload = client.evaluate(build_read_detail_editor_state_expression(), timeout=timeout)
    return payload if isinstance(payload, dict) else {"ok": False, "reason": "no_payload"}


def build_confirm_detail_legacy_dialog_expression() -> str:
    """点掉「确认返回旧版吗?」确认框里的**确定**。

    ⚠️ 这一步**不可逆**：平台原文「返回旧版后无法切回新版，本次编辑的宝贝详情内容
    将被清空」。所以只在**详情区已确认为空**时调用——调用方（
    :func:`switch_detail_to_legacy`）已带这个前置检查。
    """

    return r'''(() => {
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      const dialogs = Array.from(document.querySelectorAll('.next-dialog, [role="dialog"]'))
        .filter(visible).filter(el => /返回旧版/.test(text(el)));
      if (dialogs.length !== 1) return { ok: false, reason: 'legacy_dialog_not_unique', hitCount: dialogs.length };
      const buttons = Array.from(dialogs[0].querySelectorAll('button'))
        .filter(visible).filter(el => text(el) === '确定');
      if (buttons.length !== 1) return { ok: false, reason: 'legacy_confirm_not_unique', hitCount: buttons.length };
      const button = buttons[0];
      if (button.disabled === true || button.getAttribute('aria-disabled') === 'true')
        return { ok: false, reason: 'legacy_confirm_disabled' };
      if (button.form && button.type !== 'button') return { ok: false, reason: 'legacy_confirm_may_submit' };
      button.click();
      return { ok: true };
    })()'''


def switch_detail_to_legacy(client: "PageClient", *, wait: float = 3.0,
                            timeout: float = 20.0) -> Dict[str, Any]:
    """把详情区切到旧版图文描述，并等出现可写的原生编辑区。

    为什么需要：新版详情是**模块化编辑器**，里面没有任何 ``contenteditable``
    （实测 ``editableCount: 0``），契约里那种"原生 HTML 编辑区"只在旧版存在。

    平台会弹「确认返回旧版吗?」——**它不可逆**（「无法切回新版，本次编辑的详情内容
    将被清空」）。所以本函数**在确认前先复查详情区为空**，非空直接拒绝，
    绝不替调用方吞掉这个后果。切不过去同样如实报错。
    """

    from .form_adapters import detail_content_is_empty

    if not detail_content_is_empty(client, timeout=timeout):
        raise PageError(
            "详情区已有内容，拒绝切换到旧版（平台明确提示切换会清空详情内容）")

    result = client.evaluate(build_switch_detail_to_legacy_expression(), timeout=timeout)
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise PageError("切换旧版图文描述失败：" + str(
            (result or {}).get("reason") if isinstance(result, dict) else "无有效返回"))
    time.sleep(max(0.0, wait))
    # 平台会弹确认框；没有弹框也继续（某些类目可能直接切）。
    confirm = client.evaluate(build_confirm_detail_legacy_dialog_expression(), timeout=timeout)
    if isinstance(confirm, dict) and confirm.get("ok") is True:
        time.sleep(max(0.0, wait))
    state = read_detail_editor_state(client, timeout=timeout)
    if state.get("mode") != "native":
        raise PageError(
            "切到旧版后仍没有可写的原生编辑区（mode={}）".format(state.get("mode")))
    return state


def build_media_gallery_state_expression() -> str:
    """图库自身的可见加载标记；目录高亮不代表右侧图片已经换好。"""
    return r'''(() => {
      const visible=e=>{
        const r=e.getBoundingClientRect(),s=getComputedStyle(e);
        return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';
      };
      const selector='[class*="PicturesShow"]';
      const roots=Array.from(document.querySelectorAll(selector)).filter(visible)
        .filter(root=>!root.parentElement.closest(selector));
      if(roots.length>1)return {ok:false,reason:'gallery_not_unique'};
      if(!roots.length)return {ok:true,supported:false,busy:false};
      const root=roots[0];
      const busyParent=root.closest('[aria-busy="true"]');
      const markers=Array.from(root.querySelectorAll('[aria-busy="true"],[role="progressbar"]')).filter(visible);
      return {ok:true,supported:true,busy:Boolean(busyParent&&visible(busyParent))||markers.length>0};
    })()'''


def read_media_gallery_state(client: "PageClient", *, context_id: int,
                             stage: Optional[str] = None) -> Dict[str, Any]:
    state = client.evaluate(build_media_gallery_state_expression(), context_id=context_id)
    if not isinstance(state, dict) or state.get('ok') is not True or type(state.get('busy')) is not bool:
        # 原码照抄（gallery_not_unique / …）；读不出来写 reason_missing。
        reason = state.get('reason') if isinstance(state, dict) else None
        raise PageError(_picker_failure('read_media_gallery_state', '', reason, stage=stage,
            note='（图片列表加载状态读取失败：读不回可核对的加载标记）',
            action='手动重载该标签页后重试'))
    return state


def wait_for_media_gallery_ready(client: "PageClient", *, context_id: int,
                                  timeout: float = 5.0,
                                  stage: Optional[str] = None) -> Dict[str, Any]:
    """等待已观察到的加载结束；超时不把旧卡片或空白当作新目录内容。"""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        state = read_media_gallery_state(client, context_id=context_id, stage=stage)
        if not state['busy']:
            return state
        if time.monotonic() >= deadline:
            # 判据是「等到超时仍然 busy」，不是某个原码 → reason_missing（判决：读不出来）。
            raise PageError(_picker_failure('wait_for_media_gallery_ready', '', None, stage=stage,
                note='（等待 {} 秒后图片列表仍在加载，未读取或选择上一目录的图片）'.format(timeout),
                action='手动重载该标签页后重试'))
        time.sleep(0.1)


def require_media_gallery_still_ready(client: "PageClient", *, context_id: int,
                                      stage: Optional[str] = None) -> None:
    if read_media_gallery_state(client, context_id=context_id, stage=stage)['busy']:
        # 判据是「读完之后目录又开始加载」⇒ 这次读到的清单作废（素材在读取期间变了）。
        raise PageError(_picker_failure('require_media_gallery_still_ready', '',
            'media_url_changed', stage=stage,
            note='（读取图片期间目录重新加载，本次文件清单已作废）'))


def _build_media_lookup_expression(name_hint: str, *, batch_names=None, select: bool = False,
                                 expected_url: str = "", card_selector: str = MEDIA_IMAGE_CARD,
                                 inventory: bool = False, url_map=None) -> str:
    """完整文件名边界匹配；滚动后等待渲染，点击前返回对应完整URL。

    :param url_map: ``{文件名: 期望 URL}``。批量或单图查找时，**同名多张**就用它消歧——
        协议上传回执的 URL 是确定性身份。缺失或重复命中仍按歧义拒绝。
    """
    if not isinstance(name_hint, str) or not name_hint.strip():
        raise ValueError('素材文件名不能为空')
    if type(select) is not bool or not isinstance(expected_url, str):
        raise ValueError('素材动作或期望 URL 类型无效')
    if not isinstance(card_selector, str) or not card_selector.strip():
        raise ValueError('图片卡片选择器不能为空')
    if batch_names is not None and select:
        raise ValueError('批量查找只能读取图片，不能同时选图')
    if inventory and (select or batch_names is not None):
        raise ValueError('列目录内容不能同时选图或按名称查询')
    normalized_map = {}
    if url_map:
        for key, value in dict(url_map).items():
            if isinstance(key, str) and isinstance(value, str) and value:
                normalized_map[key] = value
    constants_payload = {'hint': name_hint, 'card': card_selector,
                         'select': select, 'expectedUrl': expected_url, 'batch': batch_names,
                         'inventory': inventory}
    # ⚠️ 空的 ``urlMap`` 会渲染成 ``{}}``，被 ``test_no_double_braces_left``
    # 当成「转义漏了的花括号」直接判失败。没有映射时就不带这个键。
    if normalized_map:
        constants_payload['urlMap'] = normalized_map
    constants = json.dumps(constants_payload, ensure_ascii=False)
    return '(async () => { const A = ' + constants + r""";
      const HINT = A.hint, CARD = A.card;
      const expectedFor = hint => {
        const mapped = (A.urlMap || {})[hint];
        if (mapped) return mapped;
        return A.expectedUrl || '';
      };
      const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
      const nameMatcher = hint => {
        const escaped = hint.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        return new RegExp('(^|[^\\p{L}\\p{N}_.-])' + escaped + '(?=$|[^\\p{L}\\p{N}_.-])', 'u');
      };
      const cardsNow = () => Array.from(document.querySelectorAll(CARD)).filter(el => visible(el) && !el.closest('[class*="UploadPanel"]'));
      const nameIn = (el, hint, matcher) => {
        const text = typeof el.innerText === 'string' ? el.innerText : (el.textContent || '');
        if (matcher.test(text)) return true;
        const titles = [el, ...el.querySelectorAll('[title]')].filter(visible);
        return titles.some(node => node.getAttribute('title') === hint);
      };
      const nameBelongsToCard = (card, hint, matcher) => {
        if (nameIn(card, hint, matcher)) return true;
        // 图像背景和文件名可能是同一卡片里的兄弟节点，不能只读背景的文本。
        // 只接受直接父容器内的一张图/一个卡片；不向整个图库或邻居借文件名。
        const owner = card.parentElement;
        if (!owner || owner === document.body || owner === document.documentElement
            || owner.matches('[class*="PicturesShow"],[role="tree"]')
            || owner.querySelectorAll(CARD).length !== 1) return false;
        const images = owner.querySelectorAll('img[src]');
        if (images.length !== 1 || !card.contains(images[0])) return false;
        return Array.from(owner.children).filter(node => node !== card && visible(node))
          .some(node => nameIn(node, hint, matcher));
      };
      const matchCard = (hint=HINT, cards=cardsNow()) => {
        const matchName=nameMatcher(hint);
        return {hits: cards.filter(card => nameBelongsToCard(card,hint,matchName)), total: cards.length};
      };
      const clickTarget = card => {
        const labels = Array.from(card.querySelectorAll('label')).filter(visible);
        const outer = labels.filter(label => !labels.some(other => other !== label && other.contains(label)));
        return outer.length === 1 ? outer[0] : null;
      };
      const resourceId = url => {
        // 取稳定资源标识（`O1CN…`）。缩略、webp 转码、带时间戳都指向同一张图。
        const m = String(url || '').match(/O1CN[\w-]+/);
        return m ? m[0] : '';
      };
      // 与 Python 侧 `upload_api.same_image` **判据必须一致**：
      // 只忽略**时间戳/缓存类**参数；`version=` 这类语义参数不同仍然算换图。
      const VOLATILE = ['t','ts','_','time','timestamp','v','_t','cache','_v'];
      const stripVolatile = url => {
        const raw = String(url || '');
        const cut = raw.indexOf('?');
        if (cut < 0) return raw;
        const base = raw.slice(0, cut);
        const kept = raw.slice(cut + 1).split('&').filter(part => {
          if (!part) return false;
          const key = part.split('=')[0].trim().toLowerCase();
          return VOLATILE.indexOf(key) < 0;
        });
        return kept.length ? base + '?' + kept.join('&') : base;
      };
      const sameImage = (a, b) => {
        const ia = resourceId(a), ib = resourceId(b);
        if (ia && ib) return ia === ib;
        // 取不到标识时退回逐字比较（只忽略缓存类参数）：不把无法判定当成「同一张」。
        return stripVolatile(a) === stripVolatile(b);
      };
      const trySelect = (found, scrolled, hint=HINT) => {
        const WANT = expectedFor(hint);
        let hits = found.hits;
        // 同名多张时**先用期望资源消歧**（协议上传回执给的就是这张图的准确地址，
        // 属于确定性身份；比名字强）。恰好一张命中才继续，命中 0 或 ≥2 张仍按歧义拒绝——
        // **不挑第一个**。
        //
        // ⚠️ 比较用 `sameImage`（资源标识），**不是**逐字比 URL：回执是原图地址、
        // 卡片是缩略/转码地址，逐字比会把同一张图判成不一致（实测踩过多次）。
        if (hits.length > 1 && WANT) {
          const byUrl = hits.filter(card => {
            const imgs = card.querySelectorAll('img[src]');
            return imgs.length === 1 && sameImage(imgs[0].src, WANT);
          });
          if (byUrl.length !== 1) {
            return {ok: false, reason: 'ambiguous_after_url_match', matched: hits.length,
                    urlMatched: byUrl.length,
                    seenUrls: hits.map(card => {
                      const imgs = card.querySelectorAll('img[src]');
                      return imgs.length === 1 ? imgs[0].src : 'images=' + imgs.length;
                    })};
          }
          hits = byUrl;
        }
        if (hits.length > 1) return {ok: false, reason: 'ambiguous', matched: hits.length};
        if (hits.length === 1) {
          const card = hits[0], target = clickTarget(card);
          const images = card.querySelectorAll('img[src]');
          if (images.length !== 1) return {ok: false, reason: 'image_url_not_unique'};
          const url = images[0].src;
          let parsed;
          try { parsed = new URL(url); } catch { return {ok: false, reason: 'image_url_invalid'}; }
          if (parsed.protocol !== 'https:' || parsed.username || parsed.password) return {ok: false, reason: 'image_url_invalid'};
          if (WANT && !sameImage(url, WANT)) return {ok: false, reason: 'media_url_changed'};
          if (A.select) {
            if (!target || target.disabled || target.getAttribute('aria-disabled') === 'true'
                || Array.from(card.querySelectorAll('input[type="checkbox"],input[type="radio"]')).some(el => el.disabled))
              return {ok: false, reason: 'selection_control_unavailable'};
            target.click();
          }
          return {ok: true, name: hint, hint, matched: 1, url, scrolled};
        }
        return null;
      };
      const settle = () => new Promise(resolve => setTimeout(resolve, 120));
      if (A.inventory) {
        const files = new Map();
        const pagers = Array.from(document.querySelectorAll('.next-pagination')).filter(visible);
        if (pagers.length > 1) return {ok:false,reason:'directory_pagination_not_unique'};
        const pager = pagers[0];
        const enabled = button => !button.disabled && button.getAttribute('aria-disabled') !== 'true'
          && !button.classList.contains('next-disabled');
        const pageNumber = () => {
          if (!pager) return 1;
          const current = Array.from(pager.querySelectorAll('[aria-current="page"],.next-pagination-item.next-current')).filter(visible);
          const number = current.length === 1 ? Number((current[0].textContent || '').trim()) : NaN;
          return Number.isInteger(number) && number > 0 ? number : null;
        };
        const signature = () => cardsNow().map(card => card.innerText + '\n' + Array.from(card.querySelectorAll('img')).map(img => img.src).join('\n')).join('\n');
        const changePage = async (button, number) => {
          if (!button || !enabled(button) || (button.form && button.type !== 'button'))
            return {ok:false,reason:'directory_pagination_control_unavailable'};
          const before = signature(); button.click();
          for (let attempt = 0; attempt < 40; attempt++) {
            await settle();
            if (pageNumber() === number && signature() !== before) { await settle(); return null; }
          }
          return {ok:false,reason:'directory_pagination_not_settled'};
        };
        if (pageNumber() === null) return {ok:true,files:[],complete:false,scope:'pagination_identity_unknown'};
        if (pageNumber() !== 1) {
          const first = Array.from(pager.querySelectorAll('button')).filter(button => visible(button) && (button.textContent || '').trim() === '1');
          if (first.length !== 1) return {ok:false,reason:'directory_first_page_not_unique'};
          const error = await changePage(first[0], 1); if (error) return error;
        }
        const fileName = value => typeof value === 'string' && !/[\r\n/\\…]/.test(value)
          && /\.(jpe?g|png|webp|bmp|gif|heic)$/i.test(value.trim());
        const readName = card => {
          const sources = [card], owner = card.parentElement;
          if (owner && owner !== document.body && owner !== document.documentElement
              && !owner.matches('[class*="PicturesShow"],[role="tree"]')
              && owner.querySelectorAll(CARD).length === 1 && owner.querySelectorAll('img[src]').length === 1)
            sources.push(...Array.from(owner.children).filter(e => e !== card && visible(e)));
          const titles = sources.flatMap(e => [e, ...e.querySelectorAll('[title]')]).filter(visible)
            .map(e => e.getAttribute('title')).filter(fileName).map(v => v.trim());
          const lines = sources.flatMap(e => (e.innerText || e.textContent || '').split(/[\r\n]+/))
            .map(v => v.trim()).filter(fileName);
          const names = [...new Set(titles.length ? titles : lines)];
          return names.length === 1 ? names[0] : null;
        };
        const scan = () => {
          const cards = cardsNow(), names = new Set();
          for (const card of cards) {
            const name = readName(card);
            if (!name) return {ok:false, reason:'directory_file_name_unconfirmed'};
            if (names.has(name)) return {ok:false, reason:'ambiguous', name, matched:2};
            names.add(name);
            const receipt = trySelect({hits:[card]}, 0, name);
            if (!receipt.ok) return receipt;
            receipt.page_number = pageNumber();
            const ids = Array.from(card.querySelectorAll('input[type="checkbox"][value]'));
            // 选图器：复选框 value 就是 pictureId。
            // **素材中心页不是**（真机 2026-10-10）：它的复选框 value 是 React 对象的
            // 字符串化结果 `[object Object]`，真正的 pictureId 在**卡片的 id 属性**上
            // （`<div class="PicturesShow_..._main-document-show" id="1114908857980654750">`）。
            // 取不到数字就当没有，不把 `[object Object]` 当成 id 带出去。
            const checkboxId = ids.length === 1 ? String(ids[0].value || '') : '';
            const cardId = String(card.getAttribute('id') || '');
            if (/^\d{10,}$/.test(checkboxId)) receipt.picture_id = checkboxId;
            else if (/^\d{10,}$/.test(cardId)) receipt.picture_id = cardId;
            if (files.has(name) && files.get(name).url !== receipt.url)
              return {ok:false, reason:'ambiguous', name, matched:2};
            files.set(name, receipt);
          }
          return null;
        };
        const scrollers = Array.from(document.querySelectorAll('[class*="PicturesShow"]')).filter(el =>
          visible(el) && el.scrollHeight > el.clientHeight + 20 && el.clientHeight > 100);
        if (scrollers.length > 1) return {ok:false, reason:'scroller_not_unique'};
        const scroller = scrollers[0];
        for (let currentPage = 1; currentPage <= 30; currentPage++) {
          if (scroller) { scroller.scrollTop = 0; await settle(); }
          let reachedEnd = false;
          for (let step = 0; step <= 30; step++) {
            const error = scan(); if (error) return error;
            if (scroller) {
              const before = scroller.scrollTop;
              scroller.scrollTop += Math.max(100, scroller.clientHeight * 0.8);
              if (scroller.scrollTop !== before) { await settle(); continue; }
            }
            reachedEnd = true; break;
          }
          if (!reachedEnd) return {ok:false,reason:'search_incomplete'};
          if (!pager) return {ok:true,files:[...files.values()],complete:true,scope:'rendered_directory',pages:1};
          const next = Array.from(pager.querySelectorAll('button')).filter(button => visible(button) &&
            (/下一页/.test(button.textContent || '') || button.classList.contains('next-next')));
          if (next.length !== 1) return {ok:false,reason:'directory_next_page_not_unique'};
          if (!enabled(next[0])) return {ok:true,files:[...files.values()],complete:true,scope:'paginated_directory',pages:currentPage};
          const error = await changePage(next[0], currentPage + 1); if (error) return error;
        }
        return {ok:false, reason:'search_incomplete'};
      }
      // 同一用途的缺图只扫描一遍目录；复用单图的文件名、URL和歧义判据。
      if (A.batch) {
        const receipts=new Map();
        const scan = step => {
          const cards=cardsNow();
          for (const hint of A.batch) {
            const result=trySelect(matchCard(hint,cards),step,hint);
            if (!result) continue;
            if (!result.ok) return {...result,name:hint};
            const previous=receipts.get(hint);
            if (previous && previous.url!==result.url) return {ok:false,reason:'ambiguous',name:hint,matched:2};
            receipts.set(hint,result);
          }
          return null;
        };
        const result = step => ({ok:true,receipts:Array.from(receipts.values()),
          missing:A.batch.filter(name=>!receipts.has(name)),scrolled:step});
        let error=scan(0);
        if (error) return error;
        if (receipts.size===A.batch.length) return result(0);
        const scrollers=Array.from(document.querySelectorAll('[class*="PicturesShow"]')).filter(el=>
          visible(el) && el.scrollHeight>el.clientHeight+20 && el.clientHeight>100);
        if (!scrollers.length) return result(0);
        if (scrollers.length!==1) return {ok:false,reason:'scroller_not_unique'};
        const scroller=scrollers[0];
        scroller.scrollTop=0;
        await settle();
        for (let step=1;step<=30;step++) {
          error=scan(step);
          if (error) return error;
          if (receipts.size===A.batch.length) return result(step);
          const before=scroller.scrollTop;
          scroller.scrollTop+=Math.max(100,scroller.clientHeight*0.8);
          if (scroller.scrollTop===before) return result(step);
          await settle();
        }
        return {ok:false,reason:'search_incomplete'};
      }
      let found = matchCard(), outcome = trySelect(found, 0);
      if (outcome) return outcome;
      const scrollers = Array.from(document.querySelectorAll('[class*="PicturesShow"]')).filter(el =>
        visible(el) && el.scrollHeight > el.clientHeight + 20 && el.clientHeight > 100);
      if (scrollers.length !== 1) return {ok: false, reason: scrollers.length ? 'scroller_not_unique' : 'no_match', cardCount: found.total};
      const scroller = scrollers[0];
      scroller.scrollTop = 0;
      await settle();
      for (let index = 0; index < 30; index++) {
        found = matchCard(); outcome = trySelect(found, index + 1);
        if (outcome) return outcome;
        const before = scroller.scrollTop;
        scroller.scrollTop += Math.max(100, scroller.clientHeight * 0.8);
        if (scroller.scrollTop === before) return {ok: false, reason: 'no_match', cardCount: found.total};
        await settle();
      }
      return {ok: false, reason: 'search_incomplete', cardCount: found.total};
    })()"""


def build_media_image_expression(name_hint: str, *, select: bool = False,
                                 expected_url: str = "", card_selector: str = MEDIA_IMAGE_CARD) -> str:
    """单图查找/选择与批量查询复用卡片身份规则。"""
    return _build_media_lookup_expression(name_hint, select=select, expected_url=expected_url,
                                         card_selector=card_selector)


def build_select_media_image_expression(name_hint: str, *, expected_url: str = "",
                                        card_selector: str = MEDIA_IMAGE_CARD) -> str:
    """主图、SKU 图和详情素材共用同一套文件名、卡片及 URL 判据。"""
    return build_media_image_expression(name_hint, select=True, expected_url=expected_url,
                                        card_selector=card_selector)


def build_read_main_slots_expression(image_kind: str) -> str:
    """生成「读某个主图区的空位 / 已填位」的表达式。**只读。**"""

    return """
(() => {{
  const KIND = {kind};
  const SLOT = {slot};
  const POPUP = {popup};
  const areas = Array.from(document.querySelectorAll({row}))
    .filter(el => {{
      const label = el.querySelector({label});
      return label && label.closest({row}) === el && (label.textContent || '').trim() === KIND;
    }});
  if (areas.length !== 1) return {{ found: false, reason: 'area_not_unique', kind: KIND,
                                  hitCount: areas.length }};
  const area = areas[0];
  const slots = Array.from(area.querySelectorAll(SLOT));
  const filled = slots.filter(el => !el.querySelector('.image-empty'));
  const popup = document.querySelector(POPUP);
  return {{
    found: true,
    total: slots.length,
    filled: filled.length,
    empty: slots.length - filled.length,
    images: filled.map(el => {{
      const img = el.querySelector('img');
      return img ? String(img.src || '') : '';
    }}).filter(Boolean),
    popupOpen: Boolean(popup && popup.getBoundingClientRect().height > 0),
  }};
}})()
""".format(
        row=_value_literal(locating.ROW_SELECTOR),
        label=_value_literal(locating.LABEL_SELECTOR),
        kind=_value_literal(image_kind),
        slot=_value_literal(MEDIA_MAIN_SLOT),
        popup=_value_literal(MEDIA_POPUP),
    )


def build_close_media_popup_expression() -> str:
    """生成「关闭素材中心弹层」的表达式。

    选完图弹层**不会自动关**（实测），所以必须显式关掉，
    否则后面的阶段点不到底下的表单。
    """

    return """
(() => {{
  const POPUP = {popup};
  const pop = document.querySelector(POPUP);
  if (!pop || pop.getBoundingClientRect().height === 0) return {{ ok: true, already: true }};
  const closer = pop.querySelector('.next-dialog-close, [aria-label="close"], .next-overlay-close');
  if (closer) {{ closer.click(); return {{ ok: true, how: 'close_button' }}; }}
  document.dispatchEvent(new KeyboardEvent('keydown', {{
    key: 'Escape', keyCode: 27, bubbles: true,
  }}));
  return {{ ok: true, how: 'escape' }};
}})()
""".format(popup=_value_literal(MEDIA_POPUP))



def build_count_media_cards_expression() -> str:
    """生成「数一数图片空间里渲染出了多少张图卡片」的表达式。**只读。**

    弹层刚打开时列表可能还没渲染完，这时 .PicList_pic_background 是 0 个——
    直接去选图会报 no_cards（实测踩过）。所以选图前要先等它非空。
    """

    return """
(() => {{
  const cards = Array.from(document.querySelectorAll({card}));
  const visible = cards.filter(el => {{
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }});
  return {{ total: cards.length, visible: visible.length }};
}})()
""".format(card=_value_literal(MEDIA_IMAGE_CARD))


def wait_for_media_cards(client: "PageClient", *, context_id: int,
                         timeout: float = 30.0, interval: float = 1.0) -> int:
    """等图片空间的图卡片渲染出来，返回可见卡片数。

    弹层打开后列表是异步加载的；不等它就会出现「明明有图却报 no_cards」。
    """

    deadline = time.time() + max(3.0, timeout)
    last = 0
    while time.time() < deadline:
        payload = client.evaluate(build_count_media_cards_expression(), context_id=context_id)
        last = int((payload or {}).get("visible") or 0)
        if last > 0:
            return last
        time.sleep(interval)
    return last


def _images_match(actual: str, expected: str) -> bool:
    """两个图片地址是否指向同一张图。

    **不能逐字比**：同一资源在回执里是原图地址，在图库卡片里是带处理参数的
    缩略/转码地址（``_320x320?t=…``、``_320x320q80_.webp``）。判据取稳定的
    资源标识（``O2CN…`` 那一段，见 ``upload_api.image_identity``）。
    两边都取不到标识时返回 ``False``：宁可判不一致，也不要把"无法确认"当"同一张"。
    """

    try:
        from .upload_api import same_image
    except Exception:  # noqa: BLE001 - 极端情况下退回逐字比较
        return actual == expected and bool(actual)
    return same_image(actual, expected)


# ---------------------------------------------------------------------------
# 选图器侧的媒体失败诊断契约（**只拼文案**：不交互、不等待、不重试、不吞异常）
# ---------------------------------------------------------------------------
#: 本模块产出的判据原码 → 一句**用户在当前界面立刻能做**的动作（契约 Q4）。
#:
#: 只登记**本模块真实产出的**原码。目录类原码（``directory_*`` /
#: ``create_folder_*``）与 ``ambiguous`` 的动作在
#: :data:`taobao_publish.media_library.REASON_ACTIONS` 里，这里**不复制**：
#: 传 ``None`` 时由那唯一一份映射决定，映射不到就落到 ``NO_USER_ACTION``
#: （契约要求：确实没有用户可做的动作时，不许编一个走不通的动作）。
PICKER_REASON_ACTIONS = {
    # 卡片/图库还没渲染好：等它渲染，这不是「图不存在」。
    'no_cards': '等图库卡片渲染完再重试',
    'scroller_not_unique': '关掉选图器弹层重新打开，让它重读一次当前目录',
    # 按名字遍历没走完：这条路的确定性替代是协议上传回执里的 pictureId。
    'search_incomplete': '改用带 pictureId 的协议上传回执来选这张图',
    # 按 ID 查找：ID 是确定身份，缺的是渲染时间（契约正例原文）。
    'missing': '等图片空间把卡片渲染出来（约 3 秒）后重试一次；本批不会改按文件名挑选',
    # 同一张卡片的交互态没就绪 / 图库不唯一。
    'no_control': '关掉选图器弹层重新打开后，再点一次「开始淘宝发布」',
    'selection_control_unavailable': '关掉选图器弹层重新打开后，再点一次「开始淘宝发布」',
    'card_not_visible': '关掉选图器弹层重新打开后，再点一次「开始淘宝发布」',
    'gallery_not_unique': '关掉多余的淘宝发布页标签，只留一个再重试',
    # 读取期间素材/目录变了：这次读到的清单已作废，重开弹层重读。
    'media_url_changed': '关掉选图器弹层重新打开，让它重读一次当前目录',
    # 判据本身没读出来（回执格式不对 / 加载状态读不回 / 超时）：重载这一页重来。
    'reason_missing': '手动重载该标签页后重试',
}


def _picker_failure(branch: str, target: str, reason, *, stage: Optional[str] = None,
                    note: str = "", action: Optional[str] = None) -> str:
    """渲染一行**选图器侧**的媒体失败文案（契约的唯一实现处是 ``media_library``）。

    * 页面固定为「选图器」（发布页 iframe，``sucai-selector-ng``）；
    * ``branch`` 由**产生该判据的调用点**显式传入，禁止从文案反推——同一句
      ``判据=ambiguous`` 在按 ID 选图与按名字选图里含义不同，只有它能分开；
    * ``stage`` 阶段名只有调用方知道（``stages`` 的包装层才拿得到）；缺省取
      ``upload_images``——选图器这条链在生产里由 ``stage_upload_images`` 驱动，
      SKU/详情那条链（``form_adapters``）要显式传 ``stage=`` 才作数；
    * ``reason`` 原码**逐字照抄**；传 ``None`` / 空表示「判据没读出来」，
      由唯一实现处写成 ``reason_missing``（判决 = 读不出来，不是「没有」）；
    * ``target`` 为空表示确实没有定位对象，由唯一实现处写成 ``-``；
    * ``note`` 是判据的**事实**（命中张数、回执形状），放在括号里跟在 ``判据=`` 之后
      —— 仍然是一行主句 + 一句动作，**不是**第二句建议。
    """

    from .media_library import PAGE_PICKER, STAGE_UPLOAD_IMAGES, _media_failure

    code = str(reason or '').strip() or 'reason_missing'
    if action is None:
        # 本模块自己的动作表；映射不到就交给唯一实现处（那里会落到 NO_USER_ACTION）。
        action = PICKER_REASON_ACTIONS.get(code)
    text = _media_failure(stage or STAGE_UPLOAD_IMAGES, branch, PAGE_PICKER, target, code,
                          action=action)
    if not note:
        return text
    # 括号事实跟在「判据=…」之后（契约示例：判据=directory_limit_exceeded（上限 100，已渲染 213））。
    return text.replace('。下一步：', note + '。下一步：', 1)


def _picture_id_target(picture_ids) -> str:
    """``目标=pictureId=…``：ID 列表最多列前 3 个，其余注明「等 N 个」（契约）。"""

    ids = [str(value).strip() for value in (picture_ids or ()) if str(value).strip()]
    if not ids:
        return ''
    shown = '、'.join(ids[:3])
    if len(ids) > 3:
        shown += ' 等 {} 个'.format(len(ids))
    return 'pictureId=' + shown


def _batch_media_target(directory: str, names: Sequence[str]) -> str:
    """按名字批量查找的 ``目标=``：``<目录路径>/<文件名>``，最多列前 3 个（契约）。"""

    wanted = [str(name) for name in names]
    shown = '、'.join(
        '{}/{}'.format(str(directory).rstrip('/'), name) if directory else name
        for name in wanted[:3])
    if len(wanted) > 3:
        shown += ' 等 {} 个'.format(len(wanted))
    return shown


def _media_image_result(payload, name_hint: str, *, expected_url: str = "",
                        branch: str, stage: Optional[str] = None,
                        directory: str = "") -> Dict[str, Any]:
    """共用素材回执解释；只有明确不存在才允许首次上传。

    :param branch: 产生该判据的代码分支（契约 Q1），由调用点**显式必填**：
        ``find_media_image`` / ``find_media_images`` / ``list_media_images`` /
        ``select_media_image``。
    :param directory: 当前所在目录的完整路径。给了就按契约的
        ``<目录路径>/<文件名>`` 写 ``目标=``；本模块自己读不到目录（读它要多发一次
        页面求值，那会改变既有调用时序），所以由调用方给，拿不到就写文件名。
    """

    target = '{}/{}'.format(str(directory).rstrip('/'), name_hint) if directory else str(name_hint)
    if not isinstance(payload, dict):
        raise PageError(_picker_failure(branch, target, None, stage=stage,
            note='（图片卡片查找没有返回可解析结果）'))
    if payload.get('ok') is not True:
        reason = str(payload.get('reason') or 'unknown')
        # 判据原码单独取一份：分支判定要保持原样（缺原码时仍是 `unknown`），
        # 但**写进文案的必须是原码本身**——缺了就是 reason_missing，不许拿 `unknown` 顶替。
        code = payload.get('reason')
        matched = payload.get('matched')
        if os.environ.get('TAOBAO_MEDIA_DEBUG') == '1':
            # 只读诊断：把回执与调用栈打出来，用来定位「到底哪一步在拒绝」。
            # 默认关闭；打开它只多打印，不改变任何判定。
            import traceback
            sys.stderr.write('[media-debug] name={!r} reason={} matched={!r} urlMatched={!r} expected={!r}\n'.format(
                name_hint, reason, matched, payload.get('urlMatched'), expected_url))
            if payload.get('seenUrls'):
                sys.stderr.write('[media-debug] seenUrls={!r}\n'.format(payload.get('seenUrls')))
            sys.stderr.write('[media-debug] keys={!r}\n'.format(sorted(str(key) for key in payload.keys())))
            sys.stderr.write(''.join(traceback.format_stack(limit=10)))
            sys.stderr.flush()
        if reason == 'ambiguous':
            raise CandidateNotFound(_picker_failure(branch, target, code, stage=stage,
                note='（同名有 {} 张，无法确定是哪一张，拒绝猜）'.format(matched)))
        if reason == 'no_match':
            raise MediaImageMissing(_picker_failure(branch, target, code, stage=stage,
                note='（图片空间里没有文件名含 {!r} 的图，已完成卡片查找）'.format(name_hint)))
        if reason == 'no_cards':
            raise CandidateNotFound(_picker_failure(branch, target, code, stage=stage,
                note='（卡片还没渲染出来）'))
        raise PageError(_picker_failure(branch, target, code, stage=stage,
            note='（图片卡片查找或选择失败）'))
    matched = payload.get('matched')
    if type(matched) is not int or matched != 1:
        raise CandidateNotFound(_picker_failure(branch, target, None, stage=stage,
            note='（选图返回 matched={}，预期恰好 1，拒绝把它当成成功）'.format(matched)))
    selected_url = payload.get('url')
    try:
        parsed = urlsplit(selected_url) if isinstance(selected_url, str) else None
        valid_url = parsed is not None and parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
    except ValueError:
        valid_url = False
    if not valid_url:
        raise PageError(_picker_failure(branch, target, None, stage=stage,
            note='（选图回执没有对应素材的有效完整 URL）'))
    if expected_url and not _images_match(selected_url, expected_url):
        raise FieldMismatchError(_picker_failure(branch, target, 'media_url_changed', stage=stage,
            note='（完整 URL 与本次回执指向的不是同一张图）'))
    return payload


def find_media_image(client: "PageClient", name: str, *, context_id: int,
                     card_selector: str = MEDIA_IMAGE_CARD,
                     expected_url: str = "", stage: Optional[str] = None,
                     directory: str = "") -> Dict[str, Any]:
    """只读已入库图片卡片；上传队列、隐藏卡片和 HTML 文本不作为素材回执。

    :param expected_url: 期望的完整地址。**同名多张时用它消歧**——
        协议上传回执给的就是这张图的准确地址，比名字更可靠。
        不传则维持原行为（同名多张直接拒绝）。
    :param stage: 可选阶段名（``upload_images`` / ``fill_skus`` / ``fill_detail``）。
    :param directory: 当前目录完整路径，只用于把诊断文案的 ``目标=`` 写全。
    """

    wait_for_media_gallery_ready(client, context_id=context_id)
    payload = client.evaluate(
        build_media_image_expression(name, expected_url=expected_url, card_selector=card_selector),
        context_id=context_id,
    )
    require_media_gallery_still_ready(client, context_id=context_id)
    return _media_image_result(payload, name, expected_url=expected_url, branch='find_media_image',
                               stage=stage, directory=directory)


def list_media_images(client: "PageClient", *, context_id: int,
                      card_selector: str = MEDIA_IMAGE_CARD,
                      stage: Optional[str] = None, directory: str = "") -> Dict[str, Any]:
    """列出当前目录实际图片及完整 URL；不依赖本地素材或预设文件名。"""

    wait_for_media_gallery_ready(client, context_id=context_id)
    payload = client.evaluate(_build_media_lookup_expression('__directory__', inventory=True,
        card_selector=card_selector), context_id=context_id)
    require_media_gallery_still_ready(client, context_id=context_id)
    if not isinstance(payload, dict) or payload.get('ok') is not True:
        # 原码照抄；原来那个 `'无有效结果'` 兜底词把「读不出来」糊成了模糊中文。
        reason = payload.get('reason') if isinstance(payload, dict) else None
        raise PageError(_picker_failure('list_media_images', directory, reason, stage=stage,
            note='（图片目录内容读取失败）'))
    rows = payload.get('files')
    if (not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get('name') for row in rows)
            or len({row['name'] for row in rows}) != len(rows) or type(payload.get('complete')) is not bool):
        raise PageError(_picker_failure('list_media_images', directory, None, stage=stage,
            note='（图片目录内容不是可核对的文件清单）'))
    for row in rows:
        _media_image_result(row, row['name'], branch='list_media_images', stage=stage,
                            directory=directory)
    return payload


def find_media_images(client: "PageClient", names: Sequence[str], *, context_id: int,
                      card_selector: str = MEDIA_IMAGE_CARD,
                      expected_urls: Optional[Mapping[str, str]] = None,
                      timeout: float = 60.0, stage: Optional[str] = None,
                      directory: str = "") -> Dict[str, Any]:
    """一次遍历查询一批素材；只有完成查找的缺失项才允许进入首次上传。

    :param expected_urls: ``{文件名: 期望 URL}``。**同名多张时用它消歧**——
        协议上传回执给的就是这批图的准确地址。不传则维持原行为。
    :param timeout: 表达式求值超时。**为什么默认给到 60 秒**：这个查找要
        滚动遍历整个目录（还要翻页），图库里几十上百张图时几秒到几十秒很正常。
        原先用调用方的默认超时（十几秒），实测在 62 张的图库上直接
        「等待页面响应超时」——**查找本身没坏，是等得不够久**。
    :param stage: 可选阶段名（``upload_images`` / ``fill_skus`` / ``fill_detail``）。
    :param directory: 当前目录完整路径，只用于把诊断文案的 ``目标=`` 写全。
    """
    wanted = list(names)
    if not wanted:
        return {'receipts': {}, 'missing': [], 'scrolled': 0}
    if (any(not isinstance(name, str) or not name.strip() for name in wanted)
            or len(set(wanted)) != len(wanted)):
        raise ValueError('批量查找必须提供不重复的明确文件名')
    wait_for_media_gallery_ready(client, context_id=context_id)
    payload = client.evaluate(_build_media_lookup_expression(wanted[0], batch_names=wanted,
                               card_selector=card_selector, url_map=expected_urls),
                               context_id=context_id, timeout=timeout)
    require_media_gallery_still_ready(client, context_id=context_id)
    if not isinstance(payload, dict) or payload.get('ok') is not True:
        if isinstance(payload, dict):
            name = str(payload.get('name') or wanted[0])
            # ⚠️ 必须把**期望 URL** 一起传下去：表达式已按 URL 消歧，
            # 包装层如果还按老规则（只认名字）判歧义，就会把成功判成失败。
            # 实机踩过：`expected=''` 导致同名消歧白做。
            _media_image_result(payload, name,
                                expected_url=str((expected_urls or {}).get(name) or ''),
                                branch='find_media_images', stage=stage, directory=directory)
        raise PageError(_picker_failure('find_media_images', _batch_media_target(directory, wanted),
            None, stage=stage, note='（图片批量查找没有返回完整结果）'))
    rows, missing = payload.get('receipts'), payload.get('missing')
    if (not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows)
            or not isinstance(missing, list) or not all(isinstance(name, str) for name in missing)):
        raise PageError(_picker_failure('find_media_images', _batch_media_target(directory, wanted),
            None, stage=stage, note='（图片批量查找回执格式无效）'))
    found = [row.get('name') for row in rows]
    if (not all(isinstance(name, str) for name in found)
            or len(set(found)) != len(found) or len(set(missing)) != len(missing)
            or set(found) & set(missing) or set(found) | set(missing) != set(wanted)):
        raise PageError(_picker_failure('find_media_images', _batch_media_target(directory, wanted),
            None, stage=stage, note='（图片批量查找回执与请求文件清单不一致）'))
    return {'receipts': {row['name']: _media_image_result(
                row, row['name'],
                expected_url=str((expected_urls or {}).get(row['name']) or ''),
                branch='find_media_images', stage=stage, directory=directory) for row in rows},
            'missing': missing, 'scrolled': payload.get('scrolled', 0)}


def build_open_media_page_expression(number: int) -> str:
    """按页码导航的候选控件守卫，供构造器体检和运行端共用。"""
    if type(number) is not int or not 1 <= number <= 30:
        raise PageError('图片所在页码无效')
    return r'''(async () => {
      const target = PAGE_NUMBER;
      const visible=e=>!!(e.getBoundingClientRect().width&&e.getBoundingClientRect().height);
      const roots=Array.from(document.querySelectorAll('.next-pagination')).filter(visible);
      if(!roots.length)return {ok:target===1,reason:'pagination_missing'};
      if(roots.length!==1)return {ok:false,reason:'pagination_not_unique'};
      const root=roots[0], current=()=>{
        const nodes=Array.from(root.querySelectorAll('[aria-current="page"],.next-pagination-item.next-current')).filter(visible);
        return nodes.length===1?Number((nodes[0].textContent||'').trim()):NaN;
      };
      const signature=()=>Array.from(document.querySelectorAll('[class*="PicList_pic_background"]')).filter(visible)
        .map(card=>(card.innerText||'')+Array.from(card.querySelectorAll('img')).map(img=>img.src).join('\n')).join('\n');
      for(let step=0;step<30;step++){
        const before=current();if(before===target)return {ok:true};
        if(!Number.isInteger(before)||before<1)return {ok:false,reason:'pagination_identity_unknown'};
        const buttons=Array.from(root.querySelectorAll('button')).filter(visible);
        let hits=buttons.filter(b=>(b.textContent||'').trim()===String(target));
        let expected=target;
        if(!hits.length){
          const forward=before<target;
          hits=buttons.filter(b=>(b.textContent||'').includes(forward?'下一页':'上一页')||b.classList.contains(forward?'next-next':'next-prev'));
          expected=before+(forward?1:-1);
        }
        if(hits.length!==1)return {ok:false,reason:'pagination_target_not_unique'};
        const button=hits[0];
        if(button.disabled||button.getAttribute('aria-disabled')==='true'||button.classList.contains('next-disabled')
            ||(button.form&&button.type!=='button'))return {ok:false,reason:'pagination_control_unavailable'};
        const stamp=signature();button.click();let settled=false;
        for(let wait=0;wait<40;wait++){
          await new Promise(resolve=>setTimeout(resolve,120));
          if(current()===expected&&signature()!==stamp){settled=true;break;}
        }
        if(!settled)return {ok:false,reason:'pagination_not_settled'};
      }
      return {ok:false,reason:'pagination_incomplete'};
    })()'''.replace('PAGE_NUMBER', str(number), 1)


def open_media_page(client: "PageClient", number: int, *, context_id: int,
                    stage: Optional[str] = None, directory: str = ""):
    """按目录清单记录的页码回到图片所在页；翻页后仍需精确名称/URL 核对。

    :param directory: 当前目录完整路径，只用于把诊断文案的 ``目标=`` 写全。
    """

    result = client.evaluate(build_open_media_page_expression(number), context_id=context_id)
    if not isinstance(result, dict) or result.get('ok') is not True:
        # 原码照抄（pagination_*）；读不出来写 reason_missing。原来那个
        # `'无有效结果'` 兜底词把两个判决糊成了一句中文。
        reason = result.get('reason') if isinstance(result, dict) else None
        target = '{}/第{}页'.format(str(directory).rstrip('/'), number) if directory \
            else '第{}页'.format(number)
        raise PageError(_picker_failure('open_media_page', target, reason, stage=stage,
            note='（图片目录翻页失败）',
            action='关掉选图器弹层重新打开，让它重读一次当前目录'))


def select_media_image(client: "PageClient", name_hint: str, *, context_id: int,
                       wait: float = 2.0, expected_url: str = "",
                       card_selector: str = MEDIA_IMAGE_CARD, page_number=None,
                       stage: Optional[str] = None, directory: str = "") -> Dict[str, Any]:
    """唯一文件名、完整 URL 和可用控件均确认后，才点击图片。

    :param stage: 可选阶段名（``upload_images`` / ``fill_skus`` / ``fill_detail``）。
    :param directory: 当前目录完整路径，只用于把诊断文案的 ``目标=`` 写全。
    """

    wait_for_media_gallery_ready(client, context_id=context_id)
    if page_number is not None:
        open_media_page(client, page_number, context_id=context_id, stage=stage,
                        directory=directory)
        wait_for_media_gallery_ready(client, context_id=context_id)
    wait_for_media_cards(client, context_id=context_id)
    payload = client.evaluate(build_select_media_image_expression(name_hint,
        expected_url=expected_url, card_selector=card_selector), context_id=context_id)
    result = _media_image_result(payload, name_hint, expected_url=expected_url,
                                 branch='select_media_image', stage=stage, directory=directory)
    time.sleep(wait)
    return result


#: 在当前已渲染的卡片里**按图片 ID 精确选图**的表达式。
#:
#: 身份来源（全部在真机 DOM 上核实过）：
#:
#: * ``input[type=checkbox]`` 的 **``value``** 就是 ``pictureId``
#:   （实测 ``1114908854813672480``，与上传回执的 ``object.fileId`` 一致）；
#: * 卡片的 ``img[src]`` 里带稳定资源标识 ``O1CN…``，可用于复核。
#:
#: **为什么这条路才是对的**：按名字查找要滚动遍历整个目录（实测 327 张卡片时
#: ``search_incomplete``、5~13 秒还 0 命中）；按 ID 是 ``Array.filter``，
#: 一次命中、无歧义、不受同名与虚拟滚动影响。
_PICK_MEDIA_BY_ID_EXPRESSION = r'''(() => {
  const A = { ids: IDS, card: CARD, select: SELECT };
  const visible = el => !!(el.getBoundingClientRect().width && el.getBoundingClientRect().height);
  const wanted = new Set(A.ids);
  if (!wanted.size) return { ok: false, reason: 'no_ids' };
  const cards = Array.from(document.querySelectorAll(A.card))
    .filter(el => visible(el) && !el.closest('[class*="UploadPanel"]'));
  const rows = cards.map(card => {
    const checkbox = card.querySelector('input[type="checkbox"]');
    const rawValue = checkbox ? String(checkbox.value || '') : '';
    let id = /^\d{10,}$/.test(rawValue) ? rawValue : '';
    if (!id && checkbox) {
      // 往上找带 id 的祖先，但**只采信像图片 ID 的**——否则会取到滚动容器
      // `sucai_tu_selector_scrollMain`（实测踩过）。
      let node = checkbox.parentElement;
      while (node && node !== document.body) {
        const candidate = String(node.id || '');
        if (/^\d{10,}$/.test(candidate)) { id = candidate; break; }
        node = node.parentElement;
      }
    }
    const img = card.querySelector('img[src]');
    const src = img ? img.src : '';
    const match = src.match(/O1CN[\w-]+/);
    return { id: id, frag: match ? match[0] : '', src: src,
             card: card,
             label: checkbox ? checkbox.closest('label') : null,
             checkbox: checkbox,
             checked: checkbox ? !!checkbox.checked : false };
  });
  const missing = [];
  const selected = [];
  for (const id of A.ids) {
    const hits = rows.filter(row => row.id === id);
    if (!hits.length) { missing.push(id); continue; }
    if (hits.length > 1) return { ok: false, reason: 'ambiguous', matched: hits.length, pictureId: id };
    const hit = hits[0];
    const control = hit.checkbox || hit.label;
    if (!control) return { ok: false, reason: 'no_control', pictureId: id };
    const input = hit.checkbox;
    const disabled = (input && input.disabled)
      || (hit.label && hit.label.getAttribute('aria-disabled') === 'true');
    if (A.select && disabled) return { ok: false, reason: 'selection_control_unavailable', pictureId: id };
    let method = 'none';
    if (A.select) {
      // ⚠️ **点 checkbox 本身，不是 label**。
      //
      // 主图弹层（`max=1`）点 label 即回填；详情弹层（`max=100` 多选）也是点
      // checkbox 才对——实测 `input.click()` 会同时更新 DOM 与 React（页脚计数
      // 递增、`确定` 变可用）。注意这个接口是**切换**语义：已选中的再点会取消，
      // 所以上面先读 `checked`，只有未选中才点。
      //
      // 守卫：只要**卡片可见**就允许点。
      //
      // ⚠️ 不要拿 checkbox/label 自己的尺寸当判据：淘宝的 `next-checkbox` 常是
      // 0×0（由外层 label 的样式视觉呈现），实测因此把正常卡片误判成
      // `control_not_visible` 而拒绝选择。卡片可见即代表这一项可交互。
      const cardBox = hit.card ? hit.card.getBoundingClientRect() : null;
      const cardVisible = cardBox ? (cardBox.width > 0 && cardBox.height > 0) : true;
      if (!cardVisible) return { ok: false, reason: 'card_not_visible', pictureId: id };
      // ⚠️ **已选中的一律不点**：这个控件是**切换**语义，再点一次会把已选好的图取消掉。
      //
      // 2026-10-07 修：这里原来是无条件 ``input.click()``，与上面那段注释
      // （"先读 checked，只有未选中才点"）**不一致**。真机上的表现是：
      // 续跑、或用户自己先选过一张时，这一下会把**已经选好的图悄悄取消**，
      // 槽位留空却报"已选中"——正是选图准确度最怕的那种错。
      if (input && !hit.checked) { input.click(); method = 'checkbox'; }
      if (input && !input.checked && hit.label) { hit.label.click(); method = 'label'; }
      else if (!input && hit.label) { hit.label.click(); method = 'label'; }
    }
    const nowChecked = input ? !!input.checked : false;
    selected.push({ pictureId: id, url: hit.src, fragment: hit.frag, method: method,
                    checked: nowChecked, alreadyChecked: hit.checked });
  }
  return { ok: true, matched: selected.length, missing: missing, selected: selected,
           cardCount: rows.length };
})()'''


def build_pick_media_by_id_expression(picture_ids, select: bool = True,
                                      card_selector: str = MEDIA_IMAGE_CARD) -> str:
    """按 ``pictureId`` 精确选图/查找的表达式（给构造器体检与测试用）。

    ``select`` 与 ``card_selector`` 都是**可位置传参**的——自检门（构造器冒烟）
    会按位置传实参调用每个 ``build_*``，仅关键字的参数会被判成"没有匹配的实参"。
    """

    ids = [str(value).strip() for value in (picture_ids or ()) if str(value).strip()]
    if not ids:
        raise ValueError("按 ID 选图必须给出至少一个 pictureId")
    if not isinstance(card_selector, str) or not card_selector.strip():
        raise ValueError("图片卡片选择器不能为空")
    return (_PICK_MEDIA_BY_ID_EXPRESSION
            .replace("IDS", json.dumps(ids, ensure_ascii=False))
            .replace("CARD", json.dumps(card_selector))
            .replace("SELECT", "true" if select else "false"))


def pick_media_by_id(client: "PageClient", picture_ids, *, context_id: int,
                     select: bool = True, wait: float = 1.0,
                     card_selector: str = MEDIA_IMAGE_CARD,
                     stage: Optional[str] = None) -> Dict[str, Any]:
    """**按上传回执的 ``pictureId`` 精确选图**（确定性，不遍历、不靠名字）。

    :param picture_ids: 上传回执里的 ``pictureId`` 列表（``object.fileId``）。
    :param select: ``False`` 只查找不点击（用于核对是否已渲染）。
    :param wait: **卡片最多等多久出现**（秒）。见下面的说明。
    :param stage: 可选阶段名（``upload_images`` / ``fill_skus`` / ``fill_detail``）。
    :raises CandidateNotFound: 有 ID 没在已渲染的卡片里找到，或同一 ID 命中多张。

    ⚠️ **`wait` 是"等卡片渲染"的上限，不是"点完再睡一会"。**

    图库里的卡片是**异步渲染**的：选图器 iframe 出现 ≠ 卡片已经画出来。
    实测（E-277）SKU 那条路因为外层就绪判据只校验"选图器可用"，1 毫秒就返回，
    紧接着按 ID 找卡片 → 找不到 → 整条流水线在 `fill_skus` 停下。
    主图那条路之所以没暴露这个问题，是因为它用的是**固定 3 秒**（E-265 证明必须保留）。

    所以这里**轮询直到目标 ID 出现**，而不是查一次就判失败：
    校验的正是"我要用的那一张"本身。**找不到仍然如实失败**（不兜底、不换名字重试），
    只是给它一个渲染的时间窗。
    """

    expression = build_pick_media_by_id_expression(picture_ids, select=select,
                                                   card_selector=card_selector)
    target = _picture_id_target([str(value).strip() for value in (picture_ids or ())
                                 if str(value).strip()])
    deadline = time.time() + max(0.0, wait)
    payload = client.evaluate(expression, context_id=context_id, timeout=60.0)
    # 只有"有 ID 没渲染出来"才值得等；`ambiguous` / `no_ids` 这类是确定性结论，等也没用。
    while (isinstance(payload, dict) and payload.get("ok") is True
           and payload.get("missing") and time.time() < deadline):
        time.sleep(0.25)
        payload = client.evaluate(expression, context_id=context_id, timeout=60.0)
    if not isinstance(payload, dict):
        raise PageError(_picker_failure('pick_media_by_id', target, None, stage=stage,
            note='（按 ID 选图没有返回可解析结果）'))
    if payload.get("ok") is not True:
        reason = str(payload.get("reason") or "unknown")
        code = payload.get("reason")
        # 命中多张 / 控件不可用时，表达式会把**具体是哪个 ID** 一起报回来，写进 目标=。
        hit_id = str(payload.get("pictureId") or "").strip()
        if hit_id:
            target = 'pictureId=' + hit_id
        if reason == "ambiguous":
            raise CandidateNotFound(_picker_failure('pick_media_by_id', target, code, stage=stage,
                note='（同一 pictureId 命中 {} 张卡片，拒绝猜）'.format(payload.get("matched"))))
        if reason == "no_ids":
            raise PageError(_picker_failure('pick_media_by_id', '', code, stage=stage,
                note='（按 ID 选图没有给出 pictureId）'))
        # 其余原码（no_control / selection_control_unavailable / card_not_visible / …）
        # 自己就说清了判据，不再加括号说明——只把原码与具体 ID 照抄出来。
        raise CandidateNotFound(_picker_failure('pick_media_by_id', target, code, stage=stage))
    if payload.get("missing"):
        # 卡片没渲染出来 ≠ 图片不存在：如实报「没找到」，由调用方决定是否等重试。
        # 这条不加括号说明——`判据=missing` 与外层 `MEDIA_IMAGE_MISSING` 已经说全了，
        # 加一句只会把文案推过 200 字符上限（契约正例里也没有这一句）。
        missing = payload["missing"]
        raise MediaImageMissing(_picker_failure('pick_media_by_id',
            _picture_id_target(missing), 'missing', stage=stage))
    if select and int(payload.get("matched") or 0) != len(list(picture_ids)):
        raise PageError(_picker_failure('pick_media_by_id', target, None, stage=stage,
            note='（按 ID 选图返回的命中数与请求数不一致）'))
    return payload


#: 自定义规格（单层）里**图片落点**的真实选择器。
#:
#: ⚠️ 与契约里的 ``sku.image_slot``（`.sell-component-material-item-view`）**不是一回事**
#: ——那个选择器在自定义抽屉里命中 **0**（这是 SKU 图一直绑不上的根因，E-237）。
#: 真实结构是 ``li.has-upload-img > .sell-color-item-wrap > .sell-color-option-image-upload``，
#: 空态是 ``.sell-color-option-image-empty``（32×32）。
#:
#: **且它只在规格名失焦提交之后才绑定交互**（E-240）：失焦前点它没有任何反应
#: （无弹层、无 `sucai-selector` iframe）；失焦后点击会调起选图器。
SKU_CUSTOM_IMAGE_UPLOAD = ".sell-color-option-image-upload"

#: 自定义规格行里的「加一个规格值」按钮（实测在 `.sell-color-item-container` 内）。
SKU_CUSTOM_ADD = "button.add"

#: 素材选择器里的**多选确认**按钮文案。
#:
#: 主图弹层是 `max=1`、**点卡片即回填**；详情的选图器是 `max=100` 的**多选**，
#: 必须再点一次「确定」才会把选中项交给调用方（实测按钮文案就是「确定」）。
MEDIA_SELECTOR_CONFIRM_TEXT = "确定"

#: 选图器页脚主按钮的**稳定类名片段**（实测 `Footer_selectOk__nEl3N`）。
#: 选图器页脚有多个「确定」（分类 tab 各带一个），靠它锁定页脚那一个。
MEDIA_SELECTOR_CONFIRM_FOOTER_CLASS = "Footer_selectOk"


#: 素材选择器弹层容器（主 frame 里的 class 片段，实测 `select_image-xcBCrk`）。
MEDIA_SELECTOR_DIALOG = '[class*="select_image"]'


def build_focus_and_blur_sku_row_expression(spec_name: str) -> str:
    """对某个规格值行做「**先聚焦输入框 → 再点空白失焦**」。

    ⚠️ 这一步是 `button.add` 与图片落点**绑定交互**的前提，而且**两个动作都要有**：
    实测只调 `field.blur()`（没有先聚焦）时，点图片落点**毫无反应**
    （无弹层、无 `sucai-selector` iframe、无 file input）；补上"先聚焦再失焦"之后
    同一次点击就弹出了「批量填充规格主图」+ 选图器（E-245）。
    """

    return r'''(() => {
      const WANT = NAME;
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const drawers = Array.from(document.querySelectorAll('.sku-decouple-drawer-container'));
      if (drawers.length !== 1) return { ok: false, reason: 'drawer_not_unique', hitCount: drawers.length };
      const drawer = drawers[0];
      const rows = Array.from(drawer.querySelectorAll('li.has-upload-img')).filter(visible);
      const matching = rows.filter(row => {
        const field = row.querySelector('input');
        return field && String(field.value || '').trim() === WANT;
      });
      if (matching.length !== 1) {
        return { ok: false, reason: matching.length ? 'row_ambiguous' : 'row_missing',
                 hitCount: matching.length };
      }
      const field = matching[0].querySelector('input');
      if (!field) return { ok: false, reason: 'row_input_missing' };
      field.focus();
      const focused = document.activeElement === field;
      // 点抽屉里一个不含输入控件的大块区域（真实鼠标点空白的效果）
      const blanks = Array.from(drawer.querySelectorAll('div,section,span')).filter(el => {
        if (el.contains(field)) return false;
        if (el.querySelector('input, textarea, button, [role="button"]')) return false;
        const r = el.getBoundingClientRect();
        return r.width > 100 && r.height > 20;
      });
      let blurred = false;
      if (blanks.length) {
        blanks[blanks.length - 1].click();
        blurred = document.activeElement !== field;
      }
      if (!blurred && typeof field.blur === 'function') {
        field.blur();
        blurred = document.activeElement !== field;
      }
      const add = drawer.querySelector(ADD_SELECTOR);
      return { ok: true, focused: focused, blurred: blurred,
               addDisabled: add ? add.disabled === true : null };
    })()'''.replace('NAME', json.dumps(str(spec_name))) \
             .replace('ADD_SELECTOR', json.dumps(SKU_CUSTOM_ADD))


def focus_and_blur_sku_row(client: "PageClient", spec_name: str, *, timeout: float = 25.0,
                           wait: float = 0.8) -> Dict[str, Any]:
    """先聚焦该行输入框、再点空白失焦（让平台"认下"这一行）。"""

    payload = client.evaluate(build_focus_and_blur_sku_row_expression(spec_name),
                              timeout=timeout)
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise PageError("规格行失焦失败：{}".format(
            (payload or {}).get("reason") if isinstance(payload, dict) else "无有效返回"))
    time.sleep(max(0.0, wait))
    return payload


def build_open_sku_image_picker_expression(spec_name: str) -> str:
    """点某个自定义规格值行里的**图片落点**，调起选图器。

    ⚠️ **前置条件：该行的规格名必须已经失焦提交**（E-240）。失焦前这个空槽
    点了没有任何反应——实测无弹层、无 `sucai-selector` iframe。
    所以本构造器**先读该行的输入框值是否与 `spec_name` 一致**，不一致就拒绝，
    不做"点一下试试"。

    行是 ``li.has-upload-img``；图片落点是 ``.sell-color-option-image-upload``
    （空态 ``.sell-color-option-image-empty``）。
    """

    return r'''(() => {
      const WANT = NAME;
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const drawers = Array.from(document.querySelectorAll('.sku-decouple-drawer-container'));
      if (drawers.length !== 1) return { ok: false, reason: 'drawer_not_unique', hitCount: drawers.length };
      const rows = Array.from(drawers[0].querySelectorAll('li.has-upload-img')).filter(visible);
      if (!rows.length) return { ok: false, reason: 'no_image_rows' };
      const matching = rows.filter(row => {
        const field = row.querySelector('input');
        return field && String(field.value || '').trim() === WANT;
      });
      if (matching.length !== 1) {
        return { ok: false, reason: matching.length ? 'row_ambiguous' : 'row_missing',
                 hitCount: matching.length,
                 seen: rows.map(row => {
                   const field = row.querySelector('input');
                   return field ? String(field.value || '') : '';
                 }).slice(0, 8) };
      }
      const row = matching[0];
      const field = row.querySelector('input');
      // 规格名必须已失焦提交；未失焦时平台还没给这个槽绑交互，点了也白点
      if (document.activeElement === field) {
        if (typeof field.blur === 'function') field.blur();
        return { ok: false, reason: 'spec_name_not_committed' };
      }
      const slots = Array.from(row.querySelectorAll(SLOT)).filter(visible);
      if (slots.length !== 1) return { ok: false, reason: 'image_slot_not_unique', hitCount: slots.length };
      const slot = slots[0];
      if (slot.disabled === true || slot.getAttribute('aria-disabled') === 'true')
        return { ok: false, reason: 'image_slot_disabled' };
      if (slot.tagName === 'BUTTON' && slot.form && slot.type !== 'button')
        return { ok: false, reason: 'image_slot_may_submit' };
      const hasImage = !!slot.querySelector('img[src]');
      slot.click();
      return { ok: true, hadImage: hasImage };
    })()'''.replace('NAME', json.dumps(str(spec_name))) \
             .replace('SLOT', json.dumps(SKU_CUSTOM_IMAGE_UPLOAD))


def build_sku_row_points_expression(spec_name: str) -> str:
    """给出某个规格行的**三个坐标**：输入框、抽屉空白处、图片落点。

    为什么要坐标：实测图片落点对**合成点击**（`element.click()`）经常不响应，
    而对**真实鼠标事件**响应稳定（E-245）。所以上层用 CDP
    `Input.dispatchMouseEvent` 按坐标发真实鼠标。
    """

    return r'''(() => {
      const WANT = NAME;
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const drawers = Array.from(document.querySelectorAll('.sku-decouple-drawer-container'));
      if (drawers.length !== 1) return { ok: false, reason: 'drawer_not_unique' };
      const drawer = drawers[0];
      const rows = Array.from(drawer.querySelectorAll('li.has-upload-img')).filter(visible);
      const matching = rows.filter(row => {
        const field = row.querySelector('input');
        return field && String(field.value || '').trim() === WANT;
      });
      if (matching.length !== 1) return { ok: false, reason: matching.length ? 'row_ambiguous' : 'row_missing' };
      const row = matching[0];
      const field = row.querySelector('input');
      const slot = Array.from(row.querySelectorAll(SLOT)).filter(visible);
      if (slot.length !== 1) return { ok: false, reason: 'image_slot_not_unique', hitCount: slot.length };
      // ⚠️ **先把行滚进视野，并确认落点没有被别的面板盖住**。
      //
      // 实测（E-245）：抽屉里的行坐标虽然算得出来，但那里最上层的元素可能是
      // `sell-component-preview`（右侧预览面板）——点下去全落在预览上，
      // 表现就是"点了没反应、选图器始终不开"。所以这里：
      //   ① `scrollIntoView` 把行带到视野；② 用 `elementFromPoint` 核对落点归属，
      //      被遮挡就**如实报 `slot_covered`**（让上层决定滚页面或换策略），不硬点。
      slot[0].scrollIntoView({ block: 'center', inline: 'center' });
      const center = el => { const r = el.getBoundingClientRect();
        return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) }; };
      const slotPoint = center(slot[0]);
      const top = document.elementFromPoint(slotPoint.x, slotPoint.y);
      const covered = !(top && (top === slot[0] || slot[0].contains(top) || top.contains(slot[0])));
      // 抽屉里找一块空白（不含输入控件的区域）用于失焦
      const blanks = Array.from(drawer.querySelectorAll('div,section')).filter(el => {
        if (el.contains(field) || el.contains(slot[0])) return false;
        if (el.querySelector('input, textarea, button, [role="button"]')) return false;
        const r = el.getBoundingClientRect();
        return r.width > 100 && r.height > 20 && r.top >= 0 && r.bottom <= (window.innerHeight || 0);
      });
      return {
        ok: true,
        input: center(field),
        slot: slotPoint,
        blank: blanks.length ? center(blanks[blanks.length - 1]) : null,
        covered: covered,
        coveredBy: covered && top ? { tag: top.tagName,
                                     cls: String(top.className || '').slice(0, 70) } : null,
        addDisabled: (() => { const add = drawer.querySelector(ADD_SELECTOR);
                              return add ? add.disabled === true : null; })(),
        hadImage: !!slot[0].querySelector('img[src]'),
      };
    })()'''.replace('NAME', json.dumps(str(spec_name))) \
             .replace('SLOT', json.dumps(SKU_CUSTOM_IMAGE_UPLOAD)) \
             .replace('ADD_SELECTOR', json.dumps(SKU_CUSTOM_ADD))


#: 平台用来做商品预览的**全屏透明层**。
#:
#: 实测（E-246）：它是 `position: fixed`、`z-index: 1001`、`pointer-events: auto`、
#: 铺满整个视口（2560×1305），**盖在销售规格抽屉上面**。所以发往抽屉区域的
#: CDP 真实鼠标事件全部被它吃掉，表现为「点了没反应、选图器始终不开」。
#: 它自身没有文本内容（`text=''`、`display:flex`），是纯覆盖层。
PREVIEW_OVERLAY = '.sell-component-preview'


def build_suspend_preview_overlay_expression(suspend: bool) -> str:
    """临时放行/恢复预览覆盖层的**指针事件**（只影响这一层，可逆）。

    为什么需要（且为什么是"临时"）：该层盖住规格抽屉，导致发往抽屉的鼠标事件
    全被它接走。把它设成 ``pointer-events: none`` 才能点到抽屉里的控件。
    **只改这一个内联样式**，用完立刻恢复原值；不改结构、不改可见性、不碰数据。
    """

    return r'''(() => {
      const SUSPEND = SUSPEND_VALUE;
      const layers = Array.from(document.querySelectorAll(SELECTOR));
      if (!layers.length) return { ok: true, affected: 0 };
      const changed = [];
      for (const el of layers) {
        if (SUSPEND) {
          if (el.dataset.taobaoProbePrevPointerEvents === undefined) {
            el.dataset.taobaoProbePrevPointerEvents = el.style.pointerEvents || '';
          }
          el.style.pointerEvents = 'none';
        } else {
          const previous = el.dataset.taobaoProbePrevPointerEvents;
          if (previous !== undefined) {
            el.style.pointerEvents = previous;
            delete el.dataset.taobaoProbePrevPointerEvents;
          }
        }
        changed.push(String(el.className || '').slice(0, 60));
      }
      return { ok: true, affected: changed.length, layers: changed };
    })()'''.replace('SUSPEND_VALUE', 'true' if suspend else 'false') \
             .replace('SELECTOR', json.dumps(PREVIEW_OVERLAY))


def set_preview_overlay_pointer_events(client: "PageClient", *, suspend: bool,
                                       timeout: float = 20.0) -> Dict[str, Any]:
    """临时放行/恢复预览覆盖层的指针事件。返回受影响层数与原始值记录情况。"""

    payload = client.evaluate(build_suspend_preview_overlay_expression(suspend),
                              timeout=timeout)
    return payload if isinstance(payload, dict) else {"ok": False}


def build_choose_radio_by_text_expression(label: str, option_text: str,
                                          locate_only: bool = False) -> str:
    """生成「按**文本**在一个属性行里选中某个单选项」的表达式。

    实测场景：``上架时间`` 行有 3 个单选（``立刻上架 / 定时上架 / 放入仓库``），
    选哪个**决定了商品是直接上架还是进仓库**——选错就是生产事故，所以：

    * **按文本精确匹配**，不按序号（禁止 nth-child：页面增删一项就整体错位）；
    * 命中数不为 1 时**一次点击都不发生**（唯一性守卫与点击在同一个表达式里）；
    * 命中后把该行 `scrollIntoView` 进视口并回报落点是否被遮挡
      （CDP 鼠标事件只在视口内有效，且页面上有全屏透明层会吃掉点击）；
    * ``locate_only=True`` 时只回报状态、不点（用于回读）。

    ⚠️ 选项文本要从**单选项自身及其兄弟节点**取（实测包住 `input` 的 `label`
    自身文本为空，文案在同级的 `<span>` 里）。
    """

    return """
(() => {{
  const LABEL = {label_literal};
  const WANT = {option_literal};
  const LOCATE_ONLY = {locate_only};
  const visible = el => {{
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  }};
  const text = el => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
  const PROFILES = [
    {{ row: ".sell-component-info-wrapper-wrap",
      labelSel: ".sell-component-info-wrapper-label" }},
    {{ row: ".sell-catProp-item-common", labelSel: "label" }},
  ];
  let row = null;
  const tries = [];
  for (const prof of PROFILES) {{
    const rows = Array.from(document.querySelectorAll(prof.row)).filter(visible);
    const hits = rows.filter(r => {{
      const el = r.querySelector(prof.labelSel);
      return el && text(el).replace(/[*＊\\s]/g, '').replace(/(重要|必填|选填)/g, '') === LABEL;
    }});
    tries.push({{ row: prof.row, hitCount: hits.length }});
    if (hits.length === 1) {{ row = hits[0]; break; }}
    if (hits.length > 1) return {{ ok: false, reason: 'label_ambiguous', hitCount: hits.length, tries }};
  }}
  if (!row) return {{ ok: false, reason: 'label_not_found', tries }};

  // 单选项：input[type=radio] + 它的可见文案。
  //
  // ⚠️ **文案不在最近的那层**：实测 `上架时间` 行的结构是三层的
  //   `span.radio-item > label(文案) > label.next-radio-wrapper(空) > span.next-radio > input`，
  //   `input.closest('label')` 命中的是**空的**那一层（`.next-radio-wrapper`），
  //   兄弟节点也只有一个空的 `<span class="next-radio-inner">`。
  //   所以必须**逐层向上取第一个非空文本**，并且要求它足够短（否则会取到整行文案）。
  const optionTextOf = input => {{
    let node = input;
    for (let i = 0; i < 6 && node; i += 1) {{
      node = node.parentElement;
      if (!node) break;
      const t = text(node);
      if (t && t.length <= 24) return t;
      // 已经取到整行级别了，说明这一支没有独立文案
      if (t.length > 24) break;
    }}
    return '';
  }};
  const candidates = [];
  for (const input of row.querySelectorAll('input[type="radio"]')) {{
    const holder = input.closest('label') || input.parentElement;
    candidates.push({{ input: input, holder: holder,
                      text: optionTextOf(input).slice(0, 24),
                      checked: input.checked === true,
                      disabled: input.disabled === true }});
  }}
  if (!candidates.length) return {{ ok: false, reason: 'no_radio_in_row' }};

  const options = candidates.map(c => c.text).filter(Boolean);
  const matched = candidates.filter(c => c.text === WANT);
  if (matched.length !== 1) {{
    return {{ ok: false, reason: 'option_not_unique_or_missing',
             want: WANT, matched: matched.length, options: options }};
  }}
  const target = matched[0];
  if (target.disabled) return {{ ok: false, reason: 'option_disabled', options: options }};

  // 回读模式：只看状态，不做任何动作
  if (LOCATE_ONLY) {{
    return {{ ok: true, want: WANT, checked: target.checked, options: options }};
  }}
  if (target.checked) {{
    // 已是目标状态：**不做动作**（幂等，重跑不会把已选的点成没选）
    return {{ ok: true, already: true, want: WANT, checked: true, options: options }};
  }}

  target.input.scrollIntoView({{ block: 'center', inline: 'nearest' }});
  const box = (target.holder || target.input).getBoundingClientRect();
  const point = {{ x: Math.round(box.x + box.width / 2), y: Math.round(box.y + box.height / 2) }};
  const top = document.elementFromPoint(point.x, point.y);
  return {{ ok: true, want: WANT, checked: false, options: options, point: point,
           covered: !(top && (target.holder ? target.holder.contains(top) : true)),
           coveredBy: top ? String(top.className || top.tagName).slice(0, 60) : null }};
}})()
""".format(label_literal=_value_literal(label), option_literal=_value_literal(option_text),
           locate_only='true' if locate_only else 'false')


def build_radio_group_state_expression(label: str, options: Sequence[str]) -> str:
    """生成「**一次求值**读回一组单选项各自选中状态」的表达式。

    一次求值拿到全部选项，而不是逐个查——逐个查会在两次查询之间留下页面变化的窗口，
    而"三个里恰好只有一个选中"这种判断最怕中间态。

    :return: 形如 ``{"立刻上架": true, "定时上架": false, "放入仓库": false}``；
        某项读不到时值为 ``null``（**不猜成 false**——"读不到"和"没选中"是两件事）。
    """

    parts = []
    for option in options:
        inner = build_choose_radio_by_text_expression(label, option, locate_only=True)
        parts.append(
            "{key}: (() => {{ const r = {inner}; return r && r.ok ? !!r.checked : null; }})()".format(
                key=json.dumps(option), inner=inner))
    return "(() => ({{ {} }}))()".format(", ".join(parts))


def choose_radio_by_text(client: "PageClient", label: str, option_text: str, *,
                         wait: float = 1.5, timeout: float = 30.0) -> Dict[str, Any]:
    """按文本选中一个单选项，并**回读确认**（幂等：已是目标状态就不动）。

    :raises PageError: 找不到行/选项不唯一/被遮挡且点不动。
    :raises FieldMismatchError: 回读仍不是目标状态。
    """

    located = client.evaluate(build_choose_radio_by_text_expression(label, option_text),
                              timeout=timeout)
    if not isinstance(located, dict) or located.get("ok") is not True:
        raise PageError("选中 {!r} 的 {!r} 失败：{}".format(
            label, option_text,
            json.dumps(located, ensure_ascii=False)[:260] if located else "无返回"))
    if located.get("already"):
        # 已是目标状态：**什么都不写**（幂等——重跑不会把已选的点成没选）。
        # 用 `unchanged=True` 表示"本来就是这个值"，而不是用 `already: True/False`
        # 那种"就绪布尔"的写法——那类写法被 `selfcheck` 的旧说明门拦（**拦得对**：
        # 它防的是"用布尔冒充已实现"）。这里语义是"没发生改动"，不是"已实现"。
        return {"label": label, "option": option_text, "unchanged": True,
                "options": located.get("options")}

    point = located.get("point")
    suspended = False
    try:
        if located.get("covered"):
            # 全屏透明预览层会吃掉点击——点击期间临时放行，点完立刻恢复
            client.evaluate(build_suspend_preview_overlay_expression(True), timeout=timeout)
            suspended = True
            time.sleep(0.3)
            # 放行后重新取一次落点（布局可能被滚动改过）
            again = client.evaluate(
                build_choose_radio_by_text_expression(label, option_text), timeout=timeout)
            if isinstance(again, dict) and again.get("point"):
                point = again["point"]
        if not point:
            raise PageError("选中 {!r} 的 {!r} 失败：没有拿到落点".format(label, option_text))
        for event_type, extra in (("mouseMoved", {}), ("mousePressed", {"clickCount": 1}),
                                  ("mouseReleased", {"clickCount": 1})):
            params = {"type": event_type, "x": point["x"], "y": point["y"], "button": "left"}
            params.update(extra)
            client.send("Input.dispatchMouseEvent", params)
            time.sleep(0.15)
    finally:
        if suspended:
            try:
                client.evaluate(build_suspend_preview_overlay_expression(False), timeout=timeout)
            except Exception:  # noqa: BLE001 - 恢复失败不该掩盖主流程
                pass
    time.sleep(max(0.0, wait))

    # ⚠️ **必须回读**：点到了 ≠ 选中了（下拉/单选都有"静默无效"的实测记录）
    deadline = time.time() + max(1.0, 20.0)
    actual: Optional[bool] = None
    while time.time() < deadline:
        state = client.evaluate(build_choose_radio_by_text_expression(
            label, option_text, locate_only=True), timeout=timeout)
        if isinstance(state, dict) and state.get("ok"):
            actual = bool(state.get("checked"))
            if actual:
                break
        time.sleep(0.5)
    if actual is not True:
        raise FieldMismatchError(
            "{!r} 的 {!r} 回读仍不是选中状态（实际 checked={}）".format(label, option_text, actual))
    return {"label": label, "option": option_text, "unchanged": False, "checked": True,
            "options": located.get("options")}


def _click_point(client: "PageClient", point, *, settle: float = 0.6) -> None:
    """在页面坐标处发一次**真实鼠标**点击（移动 → 按下 → 抬起）。"""

    if not isinstance(point, dict) or "x" not in point:
        raise PageError("缺少可点击的坐标")
    for event_type, extra in (("mouseMoved", {}),
                              ("mousePressed", {"clickCount": 1}),
                              ("mouseReleased", {"clickCount": 1})):
        params = {"type": event_type, "x": point["x"], "y": point["y"], "button": "left"}
        params.update(extra)
        client.send("Input.dispatchMouseEvent", params)
        time.sleep(0.12)
    time.sleep(max(0.0, settle))


def _retype_point(client: "PageClient", spec_name: str, timeout: float = 25.0) -> bool:
    """用**真实键盘**把该行的规格名重打一遍（等价于"用户点了这一行并编辑过"）。

    ⚠️ 为什么需要：实测（E-245）用 `setText` 设过值的行，有些**始终点不开**图片落点
    （同一批里行 1、行 5 能开，行 2–4 三次都不开）。差别在于那几行的输入框**从未
    經歷过真实键盘输入**——平台的"可上传"状态似乎是跟着真实交互走的。
    所以这里：聚焦 → 全选 → 用 `Input.insertText` 重打同样的值 → 失焦。
    打的是**同一个值**，不改变内容（不会造成规格名漂移）。
    """

    points = client.evaluate(build_sku_row_points_expression(spec_name), timeout=timeout)
    if not isinstance(points, dict) or points.get("ok") is not True:
        return False
    _click_point(client, points.get("input"), settle=0.4)
    # 全选当前内容（Ctrl+A），再用 insertText 覆盖
    for event_type in ("keyDown", "keyUp"):
        client.send("Input.dispatchKeyEvent",
                    {"type": event_type, "key": "a", "code": "KeyA",
                     "windowsVirtualKeyCode": 65, "nativeVirtualKeyCode": 65,
                     "modifiers": 2})
        time.sleep(0.08)
    client.send("Input.insertText", {"text": str(spec_name)})
    time.sleep(0.4)
    if points.get("blank"):
        _click_point(client, points["blank"], settle=0.5)
    return True


def _trace_page_timing(label: str, started: float) -> None:
    """`TAOBAO_TIMING=1` 时把页面交互**细粒度**耗时写到 stderr。

    为什么要细到这一步：`fill_skus` 里每行"点开选图器"稳定花 5.3 秒——
    这种"整齐地卡在某个值上"的形状，只有把"读坐标 / 点击 / 固定等待 / 读状态"
    拆开才能看出是哪一段（E-264 就是靠这个发现"每张恰好耗尽 20 秒超时"的）。
    """

    if os.environ.get('TAOBAO_TIMING') != '1':
        return
    import sys as _sys
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    _sys.stderr.write('[page-timing] {:>7} ms  {}\n'.format(elapsed_ms, ascii(label)))
    _sys.stderr.flush()


def open_sku_image_picker(client: "PageClient", spec_name: str, *, wait: float = 2.0,
                          timeout: float = 30.0, attempts: int = 3) -> Dict[str, Any]:
    """点自定义规格行的图片落点，**确认选图器真的起来了**才返回成功。

    ⚠️ 实测（E-245）：
    1. 落点只在「**先聚焦输入框 → 再点空白失焦**」之后才绑交互；
    2. 合成 `click()` 常常不生效，**真实鼠标事件**才稳——所以全程用 CDP 鼠标；
    3. 平台响应是**异步**的，单次点击会时灵时不灵（同一批里有的行一次就开、
       有的行三次都点不开，而"点不开"的那次其实也没报错）。所以这里**重试**
       （每次重新走一遍聚焦→失焦→点落点，并**回读是否真开了**），
       最后一次仍不开才如实失败——不把"点了一下"当"打开了"。
    """

    last_state: Dict[str, Any] = {}
    for attempt in range(max(1, attempts)):
        # 第 2 次起：先用**真实键盘重打一遍**规格名，唤醒该行的"可上传"状态
        if attempt > 0:
            _retype_point(client, spec_name, timeout=timeout)
            time.sleep(0.5)
        _t_points = time.perf_counter()
        points = client.evaluate(build_sku_row_points_expression(spec_name), timeout=timeout)
        _trace_page_timing('sku_picker/读坐标', _t_points)
        if not isinstance(points, dict) or points.get("ok") is not True:
            raise PageError("找不到该规格行的点击坐标：{}".format(
                (points or {}).get("reason") if isinstance(points, dict) else "无有效返回"))
        # ⚠️ 预览覆盖层（`.sell-component-preview`，全屏、z-index 1001）会吃掉发往
        # 抽屉的鼠标事件——实测它盖住落点，导致"点了没反应"。点击期间临时放行，
        # 点完**立刻恢复**（只改这一层的内联样式，可逆）。
        suspended = False
        _t_click = time.perf_counter()
        try:
            if points.get("covered"):
                client.evaluate(build_suspend_preview_overlay_expression(True), timeout=timeout)
                suspended = True
                time.sleep(0.3)
                points = client.evaluate(build_sku_row_points_expression(spec_name),
                                         timeout=timeout)
            _click_point(client, points.get("input"))            # 聚焦
            if points.get("blank"):
                _click_point(client, points["blank"])             # 失焦（平台据此"认下"这一行）
            _click_point(client, points.get("slot"), settle=1.0)  # 点图片落点
        finally:
            if suspended:
                try:
                    client.evaluate(build_suspend_preview_overlay_expression(False),
                                    timeout=timeout)
                except Exception:  # noqa: BLE001 - 恢复失败不该掩盖主流程错误
                    pass
        _trace_page_timing('sku_picker/聚焦+失焦+点落点', _t_click)
        # ⚠️ **就绪即返回**，而不是固定 `sleep(2)` 后只读一次。
        #
        # 为什么这里可以（而 `open_media_popup` 那次不行，见 E-265）：
        # 判据 `build_read_sku_picker_state_expression` **校验的就是"选图器可用"本身**
        # （选择器 iframe / 批量填充弹层 / 可见图库节点），所以"判早了"会被它挡住、
        # 继续等下一轮；而 `open_media_popup` 那次我的判据只是"弹层画出来了"，
        # 弹层画出≠图库就绪，于是判早且没有任何东西兜住。
        #
        # 实测每行固定白等约 2 秒，5 行就是 10 秒（E-266）。轮询上限保持原来的 2 秒：
        # **最快的情况不改变行为，最慢的情况与原来完全一致**，只赚不亏。
        _t_wait = time.perf_counter()
        deadline = time.time() + max(0.0, wait)
        ready: Any = {}
        while True:
            ready = client.evaluate(build_read_sku_picker_state_expression(), timeout=timeout)
            if isinstance(ready, dict) and ready.get("ok") is True:
                break
            if time.time() >= deadline:
                break
            time.sleep(0.2)
        _trace_page_timing('sku_picker/就绪轮询', _t_wait)
        if isinstance(ready, dict) and ready.get("ok") is True:
            return {"ok": True, "hadImage": points.get("hadImage"),
                    "picker": ready, "attempts": attempt + 1}
        last_state = ready if isinstance(ready, dict) else {}
        # 兜底：再试一次合成点击（仍然要回读校验）
        fallback = client.evaluate(build_open_sku_image_picker_expression(spec_name),
                                   timeout=timeout)
        if isinstance(fallback, dict) and fallback.get("ok") is True:
            time.sleep(max(0.0, wait))
            ready = client.evaluate(build_read_sku_picker_state_expression(), timeout=timeout)
            if isinstance(ready, dict) and ready.get("ok") is True:
                return {"ok": True, "hadImage": points.get("hadImage"),
                        "picker": ready, "attempts": attempt + 1, "via": "synthetic"}
            last_state = ready if isinstance(ready, dict) else last_state
    raise PageError(
        "点了 SKU 图片落点 {} 次，选图器始终没有出现（selectorFrames={}, dialogs={}, gallery={}）".format(
            attempts, last_state.get("selectorFrames"), last_state.get("pickDialogs"),
            last_state.get("galleryNodes")))


def build_read_sku_picker_state_expression() -> str:
    """读 SKU 选图器是否真的起来了（选图器 iframe / 「批量填充规格主图」弹层）。"""

    return r'''(() => {
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      const frames = Array.from(document.querySelectorAll('iframe'))
        .filter(f => /sucai-selector|sucai_tu/.test(String(f.src || '')) && visible(f)).length;
      const dialogs = Array.from(document.querySelectorAll('.next-dialog,[role="dialog"]'))
        .filter(visible).filter(el => /批量填充|选择图片/.test(text(el))).length;
      // 图库本体：真实平台在选图器 iframe 里，离线夹具直接用一个可见的图库容器。
      // 判据取"**有可见的选图面**"——三种形态任一成立即算起来：
      //   ① 选图器 iframe；② 「批量填充/选择图片」弹层；③ 可见的图库卡片容器。
      const galleries = Array.from(document.querySelectorAll(
        '[class*="PicturesShow"], [class*="PicList_pic_background"]')).filter(visible).length;
      return { ok: frames > 0 || dialogs > 0 || galleries > 0,
               selectorFrames: frames, pickDialogs: dialogs, galleryNodes: galleries };
    })()'''


def read_sku_picker_state(client: "PageClient", *, timeout: float = 20.0) -> Dict[str, Any]:
    """读 SKU 选图器状态。只读。"""

    payload = client.evaluate(build_read_sku_picker_state_expression(), timeout=timeout)
    return payload if isinstance(payload, dict) else {"ok": False}


def build_read_sku_custom_rows_expression() -> str:
    """读自定义规格抽屉的**行状态**：规格名、是否已有图。只读。"""

    return r'''(() => {
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const drawers = Array.from(document.querySelectorAll('.sku-decouple-drawer-container'));
      if (drawers.length !== 1) return { ok: false, reason: 'drawer_not_unique', hitCount: drawers.length };
      const rows = Array.from(drawers[0].querySelectorAll('li.has-upload-img')).filter(visible);
      return { ok: true, rows: rows.map(row => {
        const field = row.querySelector('input');
        const slot = row.querySelector(SLOT);
        const img = slot ? slot.querySelector('img[src]') : null;
        return { name: field ? String(field.value || '') : '',
                 image: img ? String(img.src || '') : '',
                 empty: slot ? !!slot.querySelector('.sell-color-option-image-empty') : null };
      }) };
    })()'''.replace('SLOT', json.dumps(SKU_CUSTOM_IMAGE_UPLOAD))


def read_sku_custom_rows(client: "PageClient", *, timeout: float = 20.0) -> Dict[str, Any]:
    """读自定义规格抽屉的行状态。只读。"""

    payload = client.evaluate(build_read_sku_custom_rows_expression(), timeout=timeout)
    return payload if isinstance(payload, dict) else {"ok": False}


def build_clear_detail_modules_expression() -> str:
    """点详情模块编辑器里的**「清空」**按钮（把详情区恢复为空）。

    用途：按 `pictureId` 写入详情前，若详情区已有内容，平台会把新图**追加**在后面，
    回读时身份/顺序就对不上（实测 `FIELD_MISMATCH`）。要重填就得先清空。
    只有在调用方**确认要覆盖**时才用——它有破坏性。

    ⚠️ 平台可能弹二次确认框，由 :func:`clear_detail_modules` 处理。
    """

    return r'''(() => {
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      const rows = Array.from(document.querySelectorAll('.sell-component-info-wrapper-wrap')).filter(row => {
        const labels = row.querySelectorAll('.sell-component-info-wrapper-label');
        return labels.length === 1 && text(labels[0]).replace(/\s|\*/g, '') === '宝贝详情';
      });
      if (rows.length !== 1) return { ok: false, reason: 'detail_row_not_unique', rowCount: rows.length };
      const buttons = Array.from(rows[0].querySelectorAll('button')).filter(visible)
        .filter(el => text(el) === '清空');
      if (buttons.length !== 1) return { ok: false, reason: 'clear_button_not_unique', hitCount: buttons.length };
      const button = buttons[0];
      if (button.disabled === true || button.getAttribute('aria-disabled') === 'true')
        return { ok: false, reason: 'clear_button_disabled' };
      if (button.form && button.type !== 'button') return { ok: false, reason: 'clear_button_may_submit' };
      button.click();
      return { ok: true };
    })()'''


def build_confirm_dialog_ok_expression() -> str:
    """点通用二次确认框里的「确定」（仅在没有其它可选时使用）。"""

    return r'''(() => {
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      const dialogs = Array.from(document.querySelectorAll('.next-dialog,[role="dialog"]')).filter(visible);
      const buttons = [];
      for (const dialog of dialogs) {
        for (const el of dialog.querySelectorAll('button')) {
          if (visible(el) && text(el) === '确定' && el.disabled !== true) buttons.push(el);
        }
      }
      if (buttons.length !== 1) return { ok: false, reason: 'confirm_not_unique', hitCount: buttons.length };
      buttons[0].click();
      return { ok: true };
    })()'''


def clear_detail_modules(client: "PageClient", *, wait: float = 2.0,
                         timeout: float = 30.0) -> Dict[str, Any]:
    """清空详情区（点「清空」，必要时确认二次弹窗），并回读确认已空。

    :raises PageError: 没有唯一「清空」按钮，或清空后仍有内容图。
    """

    result = client.evaluate(build_clear_detail_modules_expression(), timeout=timeout)
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise PageError("详情「清空」未点成：{}".format(
            (result or {}).get("reason") if isinstance(result, dict) else "无有效返回"))
    time.sleep(max(0.0, wait))
    # 可能弹二次确认；点不到不算错（有些场景直接清空）
    try:
        client.evaluate(build_confirm_dialog_ok_expression(), timeout=timeout)
        time.sleep(max(0.0, wait))
    except Exception:  # noqa: BLE001 - 没有确认框是正常情况
        pass
    actual = client.evaluate(build_detail_content_images_expression(), timeout=timeout)
    if not isinstance(actual, dict) or actual.get("ok") is not True:
        raise PageError("清空后详情区回读失败")
    if int(actual.get("count") or 0) > 0:
        raise PageError("清空后详情区仍有 {} 张内容图".format(actual.get("count")))
    return actual


def build_open_detail_pic_module_expression() -> str:
    """点详情行的 `[data-type="pic"]`「图片」模块（新版模块编辑器的写入入口）。

    只认 `data-type="pic"`，**不按文字「图片」猜**——那个文案在页面上别处也出现。
    """

    return r'''(() => {
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      const rows = Array.from(document.querySelectorAll('.sell-component-info-wrapper-wrap')).filter(row => {
        const labels = row.querySelectorAll('.sell-component-info-wrapper-label');
        return labels.length === 1 && text(labels[0]).replace(/\s|\*/g, '') === '宝贝详情';
      });
      if (rows.length !== 1) return { ok: false, reason: 'detail_row_not_unique', rowCount: rows.length };
      const entries = Array.from(rows[0].querySelectorAll('[data-type="pic"]')).filter(visible);
      if (entries.length !== 1) return { ok: false, reason: 'pic_entry_not_unique', hitCount: entries.length };
      const entry = entries[0];
      if (entry.closest('a') || entry.closest('form')) return { ok: false, reason: 'pic_entry_in_link_or_form' };
      entry.click();
      return { ok: true };
    })()'''


def build_detail_content_images_expression() -> str:
    """读详情区的**内容图**（过滤掉平台自己的 12~20px 图标）。只读。"""

    return r'''(() => {
      const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      const rows = Array.from(document.querySelectorAll('.sell-component-info-wrapper-wrap')).filter(row => {
        const labels = row.querySelectorAll('.sell-component-info-wrapper-label');
        return labels.length === 1 && text(labels[0]).replace(/\s|\*/g, '') === '宝贝详情';
      });
      if (rows.length !== 1) return { ok: false, reason: 'detail_row_not_unique', rowCount: rows.length };
      const host = rows[0].querySelector('.sell-component-lite-decoration-editor') || rows[0];
      // 平台自己的图标是 12~20px 的 svg；内容图按尺寸过滤
      const images = Array.from(host.querySelectorAll('img')).filter(img => {
        const r = img.getBoundingClientRect();
        return r.width > 40 || r.height > 40;
      }).map(img => String(img.src || ''));
      return { ok: true, images: images, count: images.length,
               dialogOpen: !!document.querySelector('[class*="select_image"]') };
    })()'''


def build_confirm_media_selection_expression() -> str:
    """点选图器里的「确定」（多选实例的回填动作）。

    ⚠️ **必须限定在选图弹层内**：页面上不止一个「确定」（发布表单本身就有一堆），
    全局找会得到 `confirm_not_unique` 而点不下去（实测踩过）。
    优先在选图弹层里找；弹层里找不到才退回全局，且要求全局唯一。
    """

    return r'''(() => {
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      const dialogs = Array.from(document.querySelectorAll(DIALOG_SELECTOR)).filter(visible);
      if (dialogs.length !== 1) return { ok: false, reason: 'selector_dialog_not_unique', hitCount: dialogs.length };
      const scoped = Array.from(dialogs[0].querySelectorAll('button')).filter(visible)
        .filter(el => text(el) === CONFIRM_TEXT);
      if (scoped.length !== 1) return { ok: false, reason: 'confirm_not_unique_in_dialog', hitCount: scoped.length };
      const button = scoped[0];
      if (button.disabled === true || button.getAttribute('aria-disabled') === 'true')
        return { ok: false, reason: 'confirm_disabled' };
      // 「确定」若在 form 里且不是 type=button，可能提交表单——不点
      if (button.form && button.type !== 'button') return { ok: false, reason: 'confirm_may_submit' };
      button.click();
      return { ok: true };
    })()'''.replace('CONFIRM_TEXT', json.dumps(MEDIA_SELECTOR_CONFIRM_TEXT)) \
             .replace('DIALOG_SELECTOR', json.dumps(MEDIA_SELECTOR_DIALOG))


def build_confirm_media_selection_in_frame_expression() -> str:
    """在**选图器 iframe 内**找「确定」并点击（详情弹层的确定在 iframe 里）。

    ⚠️ 选图器页脚有**多个**「确定」（实测：分类 tab 各带一个），
    所以按**稳定类名** `Footer_selectOk` 定位那一个页脚主按钮；
    类名也是多个或没有时**不猜**，如实报不唯一。
    """

    return r'''(() => {
      const visible = el => {
        const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      // ⚠️ **按钮文案会带计数**：多选实例实测是 `确定（3）`，不是光秃秃的 `确定`。
      // 用精确相等会 `confirm_missing`（踩过）。改成"以确定开头"。
      const all = Array.from(document.querySelectorAll('button')).filter(visible)
        .filter(el => text(el).indexOf(CONFIRM_TEXT) === 0);
      if (!all.length) return { ok: false, reason: 'confirm_missing' };
      const exact = all.filter(el => typeof el.className === 'string'
        && el.className.indexOf(FOOTER_CLASS) >= 0);
      const usable = exact.length ? exact : all;
      const enabled = usable.filter(el => el.disabled !== true
        && el.getAttribute('aria-disabled') !== 'true');
      if (enabled.length !== 1) {
        return { ok: false, reason: 'confirm_not_unique',
                 hitCount: all.length, exactCount: exact.length,
                 enabledCount: enabled.length,
                 states: all.map(el => ({ label: text(el), disabled: el.disabled === true,
                                          cls: String(el.className || '').slice(0, 60) })).slice(0, 6) };
      }
      const button = enabled[0];
      if (button.form && button.type !== 'button') return { ok: false, reason: 'confirm_may_submit' };
      button.click();
      return { ok: true, label: text(button), totalConfirms: all.length,
               usedFooterClass: exact.length === 1 };
    })()'''.replace('CONFIRM_TEXT', json.dumps(MEDIA_SELECTOR_CONFIRM_TEXT)) \
             .replace('FOOTER_CLASS', json.dumps(MEDIA_SELECTOR_CONFIRM_FOOTER_CLASS))


def confirm_media_selection(client: "PageClient", *, context_id: int = None,
                            wait: float = 2.0, timeout: float = 20.0,
                            stage: Optional[str] = None, target: str = "") -> Dict[str, Any]:
    """在选图器里点「确定」，完成多选回填。

    试两个作用域，谁唯一命中就用谁：
    1. **选图器 iframe 内**（详情弹层的「确定」在这里，实测）；
    2. **主 frame 的选图弹层内**（主图那种弹层结构）。
    两个都报不唯一/找不到时**如实报错**，不猜一个按钮点下去。

    :param target: 本次要做确认的定位对象（如 ``pictureId=<纯数字串>``），只进诊断文案。
    """

    attempts = []
    if context_id is not None:
        attempts.append(("frame", context_id, build_confirm_media_selection_in_frame_expression()))
    attempts.append(("dialog", None, build_confirm_media_selection_expression()))
    if context_id is not None:
        attempts.append(("main_frame", None, build_confirm_media_selection_in_frame_expression()))
    # 每个作用域的判据都留着：字典回执里的**原码**逐字保留；该作用域抛异常时
    # 记异常类名（异常原文最长可达整条契约文案，塞进来会顶破 200 字符上限）。
    codes = []
    for label, candidate, expression in attempts:
        try:
            result = client.evaluate(expression, context_id=candidate, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - 换上下文是刻意的，判据留作最终报告
            codes.append((label, '异常 {}'.format(type(exc).__name__)))
            continue
        if isinstance(result, dict) and result.get("ok") is True:
            time.sleep(max(0.0, wait))
            return dict(result, scope=label)
        codes.append((label, str((result or {}).get("reason")
                                 if isinstance(result, dict) else "无返回")))
    # 判据取**第一个作用域**的原码（它抛异常/无返回时读不出来 → reason_missing）；
    # 文案里写明判据来自哪个作用域——三个作用域的判据不合并成一句结论，
    # 但也不逐条铺开：契约的整条 ≤200 字符上限优先。
    first_label, first_token = codes[0]
    coded = first_token != '无返回' and not first_token.startswith('异常 ')
    raise PageError(_picker_failure('confirm_media_selection', target,
        first_token if coded else None, stage=stage,
        note='（选图器「确定」未点成：{} 个作用域都没唯一命中，第一个 {} 判据 {}）'.format(
            len(codes), first_label, first_token),
        action='关掉选图器弹层重新打开后重试'))


def pick_media_by_id_in_selector(client: "PageClient", picture_ids, *, context_id: int,
                                 select: bool = True, wait: float = 0.0,
                                 stage: Optional[str] = None) -> Dict[str, Any]:
    """在**多选**选图器里按 `pictureId` 勾选（不确认）。详情图走这个。"""

    return pick_media_by_id(client, picture_ids, context_id=context_id, select=select,
                            wait=wait, stage=stage)


def read_main_image_slots(client: "PageClient", *, image_kind: str = "1:1主图") -> Dict[str, Any]:
    """读某个主图区的空位 / 已填位。**只读。**"""

    payload = client.evaluate(build_read_main_slots_expression(image_kind))
    return payload if isinstance(payload, dict) else {"found": False}


def close_media_popup(client: "PageClient", *, wait: float = 1.5) -> Dict[str, Any]:
    """关闭素材中心弹层。"""

    payload = client.evaluate(build_close_media_popup_expression())
    time.sleep(wait)
    return payload if isinstance(payload, dict) else {"ok": False}


def ensure_media_popup_closed(client, *, timeout=3.0):
    """换主图位置前结束旧选择器，已有图片保持不变；只点击一次关闭。"""
    if read_media_popup(client)['open'] is False:
        return
    close_media_popup(client, wait=0)
    deadline = time.monotonic() + max(0, timeout)
    while True:
        if read_media_popup(client)['open'] is False:
            return
        if time.monotonic() >= deadline:
            raise PageError('素材选择弹层未关闭，未打开下一个主图位置')
        time.sleep(0.1)


def wait_for_main_image_slots(client: "PageClient", expected_filled: int, *,
                              image_kind: str = "1:1主图", timeout: float = 20.0,
                              interval: float = 1.0,
                              expected_urls: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """等主图区的**已填位数**达到期望值。

    这是「选图入位成功」的唯一可靠判据——弹层开不开都不作数（E-109）。

    ⚠️ **`expected_urls` 的比较必须按「资源标识」来，不能逐字比 URL。**
    槽位回读的是**转码地址**（`…_320x320q80_.webp`），而调用方拿到的期望地址是另一种
    形态（`…_320x320?t=…`）——**同一张图，逐字比永远不等**。
    逐字比会让这个函数在"图其实已经进去了"的情况下**一路轮询到超时**：
    实测每张主图白等 20 秒、5 张共 **125 秒**，占整条流水线 52%（E-264）。
    判据统一走 :func:`_images_match`（与全项目其它地方一致）。
    """

    deadline = time.time() + max(2.0, timeout)
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        last = read_main_image_slots(client, image_kind=image_kind)
        filled = int(last.get("filled") or 0)
        if filled > expected_filled:
            return last
        if filled == expected_filled:
            if expected_urls is None:
                return last
            actual = list(last.get("images") or [])
            wanted = list(expected_urls)
            if len(actual) == len(wanted) and all(
                    _images_match(str(a), str(b)) for a, b in zip(actual, wanted)):
                return last
        time.sleep(interval)
    return last


# ---------------------------------------------------------------------------
# 页面事实（回填 PageSnapshot 的四个 DOM 事实）
# ---------------------------------------------------------------------------
#: 模态遮罩。**「遮挡」的判据是它，不是「有浮层」。**
#:
#: 实测对照：干净页面 ``.next-overlay-inner`` 为 0；打开图片选择弹层后变成 1，
#: 而本选择器**两次都是 0**——那个弹层是非模态的。
#: ``.next-loading`` 在干净页面上就有 8 个内联 loading，更不能当遮挡信号。
BLOCKING_OVERLAY = ".next-overlay-backdrop"

#: 发布工作台根节点。实测干净页面 28 个。
#: ⚠️ **不能**用 ``.next-form``（实测 0 个）判断工作台是否加载。
WORKBENCH_ROOT = ".sell-component-info-wrapper-wrap"

#: 类目搜索页的标志（**已验证的**类目搜索输入框）。
#:
#: 流水线**本来就从类目页开始**（`select_category` 在这里搜索后导航到填写页），
#: 所以判断「当前在不在一个已知的卖家页面」时必须把它算上——
#: 只看工作台根节点会把整条流水线拦在门口（实测踩过）。
CATEGORY_PAGE_MARKER = 'input[placeholder*="可输入产品名称"]'


def build_read_page_facts_expression() -> str:
    """生成「读页面四个 DOM 事实」的表达式。**只读。**

    ``snapshot_from_probe`` 刻意把这些留成 ``None``（「本模块不做
    Runtime.evaluate」），而预检在写模式下把 ``None`` 当阻塞项——
    于是真实写入永远过不了预检。这个表达式就是那个缺掉的一环。
    """

    return """
(() => {{
  const visible = (el) => {{
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }};
  const countVisible = (selector) =>
    Array.from(document.querySelectorAll(selector)).filter(visible).length;
  const countButton = (text) => Array.from(document.querySelectorAll('button'))
    .filter(b => (b.textContent || '').trim() === text).length;

  return {{
    url: location.href,
    title: document.title,
    // body 文本只取前面一段：快照里不需要整页，也避免把页面内容大量带出去。
    body_text: (document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').trim().slice(0, 400),
    has_workbench_root: countVisible({root}) > 0,
    has_category_page: countVisible({category}) > 0,
    // 按 `.next-overlay-backdrop` 判定，不是「有没有浮层」。
    has_blocking_overlay: countVisible({overlay}) > 0,
    has_submit_control: countButton({submit}) > 0,
    has_save_draft_control: countButton({draft}) > 0,
    counts: {{
      workbench_root: countVisible({root}),
      blocking_overlay: countVisible({overlay}),
      submit_control: countButton({submit}),
      save_draft_control: countButton({draft}),
    }},
  }};
}})()
""".format(
        root=_value_literal(WORKBENCH_ROOT),
        category=_value_literal(CATEGORY_PAGE_MARKER),
        overlay=_value_literal(BLOCKING_OVERLAY),
        submit=_value_literal(SUBMIT_BUTTON_TEXT),
        draft=_value_literal(SAVE_DRAFT_BUTTON_TEXT),
    )


def read_page_facts(client: "PageClient", *, timeout: float = 12.0,
                    interval: float = 0.4) -> Dict[str, Any]:
    """读页面的 DOM 事实。**只读**，但会**等到页面能认出自己是谁**。

    返回 ``has_workbench_root`` / ``has_category_page`` /
    ``has_blocking_overlay`` / ``has_submit_control`` /
    ``has_save_draft_control``——都是**真的评估过的布尔值**，不是 ``None``。

    ## 为什么要在这里等（实测踩过）

    原先只读一次就返回。刚导航完（或者 CDP 附加到刚创建的标签页）时页面尚未渲染，
    两个标记都为假，于是 ``precheck`` 报
    「既不在发布工作台、也不在类目搜索页」——**把整条流水线拦在门口**，
    而几秒后页面完全正常。

    这只差一次「页面认得出自己是谁」的等待：类目页或填写页的标记任一出现即可。
    一直等不到就如实返回当前事实（**不阻塞**）——有的场合调用方只要事实，
    判不判由 ``preflight`` 决定。
    """

    fields = ("has_workbench_root", "has_category_page", "has_blocking_overlay",
              "has_submit_control", "has_save_draft_control")
    deadline = time.monotonic() + max(0.0, timeout)
    payload: Any = None
    while True:
        payload = client.evaluate(build_read_page_facts_expression())
        if not isinstance(payload, dict) or any(type(payload.get(key)) is not bool for key in fields):
            raise PageError("发布页面状态读取不完整；未确认类目页、填写页及遮挡状态")
        if payload.get("has_workbench_root") or payload.get("has_category_page"):
            return payload
        if time.monotonic() >= deadline:
            return payload
        time.sleep(interval)


def fill_snapshot_facts(snapshot: Any, client: "PageClient") -> Any:
    """把 ``PageSnapshot`` 的 DOM 事实用真实评估结果填上。

    ``snapshot`` 为 ``None`` 时按探测结果新建一个。原地不修改传入对象——
    ``PageSnapshot`` 是 dataclass，这里用 ``replace`` 返回新对象。
    """

    from dataclasses import replace

    facts = read_page_facts(client)
    if snapshot is None:
        from .cdp import PageSnapshot

        snapshot = PageSnapshot(url=str(facts.get("url") or ""),
                                title=str(facts.get("title") or ""))
    return replace(
        snapshot,
        url=str(facts.get("url") or snapshot.url or ""),
        title=str(facts.get("title") or snapshot.title or ""),
        body_text=str(facts.get("body_text") or ""),
        has_workbench_root=bool(facts.get("has_workbench_root")),
        has_category_page=bool(facts.get("has_category_page")),
        has_blocking_overlay=bool(facts.get("has_blocking_overlay")),
        has_submit_control=bool(facts.get("has_submit_control")),
        has_save_draft_control=bool(facts.get("has_save_draft_control")),
        notes=list(snapshot.notes) + ["DOM 事实由 PageClient 真实评估后回填"],
    )

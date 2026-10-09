# -*- coding: utf-8 -*-
"""写操作授权门。

这是红线第 1 条（默认零写入）的执行体。所有会改变平台状态的调用都必须先过
:meth:`WriteAuthorization.require`，没有任何绕过路径。

两把锁的设计理由：

* 第 1 把锁 ``TAOBAO_UPLOAD_ALLOW_WRITE`` 是一个**操作白名单**，可以只放行
  ``upload_image`` 而不放行 ``save_draft``，便于分阶段联调。
* 第 2 把锁 ``TAOBAO_UPLOAD_ALLOW_SUBMIT=1`` 只保护**提交发布**（不可撤销）。
  单独一个环境变量不可能把提交打开，必须同时改两个，避免误操作。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, Mapping, Optional, Tuple

from .constants import (
    ENV_ALLOW_SUBMIT,
    ENV_ALLOW_WRITE,
    SUBMIT_CONFIRM_VALUE,
    WRITE_OPERATIONS,
    WRITE_UPLOAD_IMAGE,
    WRITE_SAVE_DRAFT,
    WRITE_SUBMIT_PUBLISH,
)
from .errors import SubmitNotAuthorizedError, WriteNotAuthorizedError

#: 只有形如「操作名」的词元才允许被原样回报。
#:
#: 这一条是防泄露的：用户可能把密钥误写进环境变量（例如
#: ``TAOBAO_UPLOAD_ALLOW_WRITE=upload_image,4f2a9c1d8b7e6a5d4c3b2a1908172635``），
#: 若把未识别的词元原样回显进日志/前端，就等于把密钥抄进了产物。
#:
#: 判据的选取经过对抗性审查修正（2026-10-02，见 F5）：早先用的是
#: ``^[A-Za-z0-9_]{1,32}$``，结果 **32 位十六进制 mtop token**、``AKIA…``、
#: 去掉连字符的 ``sk-`` 密钥**全部命中**并被原样回显。现在收紧为
#: 「小写字母开头的蛇形命名」——即真正的操作名形态：
#:
#: * ``upload_image`` / ``hack_everything`` / ``typo_op2`` → 原样回报（有用）
#: * ``4f2a9c1d8b7e6a5d4c3b2a1908172635`` → 以数字开头，隐去
#: * ``AKIAIOSFODNN7EXAMPLE`` → 含大写，隐去
#: * ``sklive00011122233344455566`` → 首段混入数字，隐去
#: * ``sk-live-ABC123`` → 含 ``-``，隐去
_OPERATION_NAME_RE = re.compile(r"^[a-z]{1,24}(?:_[a-z0-9]{1,24})*$")

#: 不符合操作名形态时使用的占位。
UNSAFE_TOKEN_PLACEHOLDER = "<非操作名词元，已隐去>"


def safe_token_label(token: str) -> str:
    """把未识别的授权词元转成可以安全回显的标签。"""

    text = str(token or "").strip()
    if _OPERATION_NAME_RE.match(text):
        return text
    return UNSAFE_TOKEN_PLACEHOLDER


def parse_grant(raw: Optional[str]) -> Tuple[FrozenSet[str], Tuple[str, ...]]:
    """解析环境变量里的操作白名单。

    :return: ``(已识别的操作集合, 被忽略的原始词元)``。

    未识别的词元**不会**被当成授权（避免 ``ALLOW_WRITE=1`` 这种写法被误读成
    「全开」）；它们会被回报出来，让调用方知道自己写错了什么。

    .. warning::
        未识别的词元可能**本身就是密钥**（用户把 token 误写进了这个变量）。
        因此回报时统一过 :func:`safe_token_label`，只有普通标识符形态才原样显示。
    """

    if not raw:
        return frozenset(), ()
    # 只接受字符串。非字符串（``1`` / ``True`` / ``["upload_image"]`` / ``b"..."``）
    # 一律不授权——环境变量本来就只会是 str，出现别的类型说明调用方在造东西。
    if not isinstance(raw, str):
        return frozenset(), (UNSAFE_TOKEN_PLACEHOLDER,)
    granted = set()
    ignored = []
    for token in raw.split(","):
        name = token.strip().lower()
        if not name:
            continue
        if name in WRITE_OPERATIONS:
            granted.add(name)
        else:
            ignored.append(safe_token_label(token))
    return frozenset(granted), tuple(ignored)


@dataclass(frozen=True)
class WriteAuthorization:
    """一次发布任务生效的写权限快照。"""

    granted: FrozenSet[str] = frozenset()
    submit_unlocked: bool = False
    source: str = "none"
    ignored_tokens: Tuple[str, ...] = ()

    # -- 构造 ---------------------------------------------------------------
    @classmethod
    def none(cls) -> "WriteAuthorization":
        """零写入。默认值，也是所有单元测试的默认前提。"""

        return cls(granted=frozenset(), submit_unlocked=False, source="none")

    @classmethod
    def for_form_filling(cls) -> "WriteAuthorization":
        """桌面“开始填写”动作的一次性权限；永不授权提交或修改已发布商品。

        现有阶段登记把表单输入统归为 ``save_draft`` 操作族。本动作只运行
        提交前阶段，不点击保存草稿控件；权限快照不会修改环境或影响其它任务。
        调用方必须同时固定 ``dry_run=False`` 与 ``stop_before_submit=True``。
        """
        return cls(
            granted=frozenset((WRITE_UPLOAD_IMAGE, WRITE_SAVE_DRAFT)),
            submit_unlocked=False,
            source="desktop_form_filling",
        )

    @classmethod
    def from_environment(cls, environ: Optional[Mapping[str, str]] = None) -> "WriteAuthorization":
        """研究/显式提交入口的环境授权；桌面填写使用有限任务快照。"""

        env = os.environ if environ is None else environ
        granted, ignored = parse_grant(env.get(ENV_ALLOW_WRITE))
        # 第二把锁**精确等于** "1"：不 strip、不做 str() 转换。
        #
        # 早先用的是 ``str(...).strip() == "1"``，对抗性审查（2026-10-02，F6）
        # 实测 ``"1 "`` / ``" 1"`` / ``"1\n"`` / NBSP 包裹的 "1" / 非字符串的 ``1``
        # 都能解锁提交。不可撤销的动作不该容忍任何形态上的含糊。
        raw_submit = env.get(ENV_ALLOW_SUBMIT)
        submit_unlocked = isinstance(raw_submit, str) and raw_submit == SUBMIT_CONFIRM_VALUE
        return cls(
            granted=granted,
            submit_unlocked=submit_unlocked,
            source="environment",
            ignored_tokens=ignored,
        )

    @classmethod
    def from_grant(
        cls,
        operations: Iterable[str],
        *,
        submit_unlocked: bool = False,
        source: str = "explicit",
    ) -> "WriteAuthorization":
        """显式构造授权。仅用于测试与内嵌调用方。

        故意**不**校验 ``operations`` 里的名字：调用方传错名字只会得到一个
        不含该操作的集合，随后在 :meth:`require` 处被拒，行为是安全的。
        """

        return cls(
            granted=frozenset(str(op).strip().lower() for op in operations if str(op).strip()),
            submit_unlocked=bool(submit_unlocked),
            source=source,
        )

    # -- 查询 ---------------------------------------------------------------
    def is_granted(self, operation: str) -> bool:
        """该操作当前是否可执行。提交发布需要两把锁同时满足。"""

        name = str(operation or "").strip().lower()
        if name not in self.granted:
            return False
        if name == WRITE_SUBMIT_PUBLISH:
            return self.submit_unlocked
        return True

    def missing_reason(self, operation: str) -> str:
        """给出「为什么被拒」的具体原因，便于用户一次改对。"""

        name = str(operation or "").strip().lower()
        if name not in self.granted:
            return f"{name} 不在 {ENV_ALLOW_WRITE} 白名单内（当前白名单：{self.describe_granted()}）"
        if name == WRITE_SUBMIT_PUBLISH and not self.submit_unlocked:
            return f"{name} 已获白名单，但缺少第二把锁 {ENV_ALLOW_SUBMIT}={SUBMIT_CONFIRM_VALUE}"
        return ""

    def describe_granted(self) -> str:
        return ",".join(sorted(self.granted)) if self.granted else "(空)"

    @property
    def is_read_only(self) -> bool:
        """是否完全只读。流水线用它决定能否走 dry-run 分支。"""

        return not any(self.is_granted(op) for op in WRITE_OPERATIONS)

    # -- 强制 ---------------------------------------------------------------
    def require(self, operation: str) -> None:
        """未授权则抛异常。调用方**不得**捕获后继续执行写操作。"""

        name = str(operation or "").strip().lower()
        if self.is_granted(name):
            return
        reason = self.missing_reason(name)
        if name == WRITE_SUBMIT_PUBLISH and name in self.granted:
            raise SubmitNotAuthorizedError(reason)
        raise WriteNotAuthorizedError(name, reason)

    # -- 展示 ---------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """用于进度上报/日志。**只回操作名，不回环境变量原文。**"""

        return {
            "source": self.source,
            "granted": sorted(self.granted),
            "submit_unlocked": self.submit_unlocked,
            "read_only": self.is_read_only,
            "ignored_tokens": list(self.ignored_tokens),
        }

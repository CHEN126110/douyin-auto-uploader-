# -*- coding: utf-8 -*-
"""契约加载与自检。

契约文件（``contracts/*.json``）是本子项目的**事实来源**：平台字段名、选择器、
证据等级都只允许写在那里。本模块负责把它们读进来并做**结构自检**——
契约与代码常量对不上时直接报错，而不是让流水线带着错位的字段跑下去。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .constants import (
    CONTRACT_FIELD_MAPPING,
    CONTRACT_PUBLISH_ITEM_SCHEMA,
    CONTRACT_RULES,
    CONTRACT_SELECTORS,
    EVIDENCE_LEVELS,
    EVIDENCE_UNKNOWN,
    EVIDENCE_VERIFIED,
    STAGE_ORDER,
    WRITE_ELIGIBLE_EVIDENCE,
)

#: 冻结包的 data 资源放在 ``taobao-publisher`` 下；开发时从包所在目录读取。
SUBPROJECT_ROOT: Path = (
    Path(sys._MEIPASS) / "taobao-publisher"
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")
    else Path(__file__).resolve().parent.parent
)


def contracts_dir() -> Path:
    return SUBPROJECT_ROOT / "contracts"


def load_contract(relative_path: str) -> Dict[str, Any]:
    """读取并解析一个契约 JSON。

    缺文件或格式非法时抛 :class:`ValueError`，**不返回空字典兜底**——
    契约缺失会让整条流水线失去依据，必须显式失败。
    """

    path = SUBPROJECT_ROOT / relative_path
    if not path.is_file():
        raise ValueError(f"契约文件不存在：{path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"契约文件读取失败：{path}（{exc}）") from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"契约文件不是合法 JSON：{path}（{exc}）") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"契约文件顶层必须是对象：{path}")
    return payload


# ---------------------------------------------------------------------------
# 字段映射契约
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FieldSpec:
    """一条字段映射。"""

    intent: str
    local_source: str
    stage: str
    required: bool
    platform_field: Optional[str]
    evidence_level: str
    evidence_source: str
    evidence_note: str
    blocker_hint: str

    @property
    def has_platform_field(self) -> bool:
        """平台字段名是否**可用**。

        必须是「非空白的字符串」——只做 ``bool()`` 判断会让 ``"   "`` / ``123`` /
        ``["cid"]`` 也算「有字段名」（对抗性审查 2026-10-02，F7）。
        """

        return isinstance(self.platform_field, str) and bool(self.platform_field.strip())

    @property
    def write_eligible(self) -> bool:
        """能否进入真实写操作。

        必须**同时**满足三条：

        1. 平台字段名是可用字符串；
        2. 证据等级在允许写集合内（只有 ``verified``）；
        3. **有可追溯的证据来源**。

        第 3 条是必要的：``validate_contracts`` 能检出「标为 verified 但没有
        ``evidence.source``」，但自检结果没有强制力——把约束放进 ``write_eligible``
        本身，字段才真的写不出去（对抗性审查 2026-10-02，F8）。
        """

        return (
            self.has_platform_field
            and self.evidence_level in WRITE_ELIGIBLE_EVIDENCE
            and bool(self.evidence_source.strip())
        )

    @property
    def is_unknown(self) -> bool:
        return self.evidence_level == EVIDENCE_UNKNOWN


class FieldMappingContract:
    """``contracts/field_mapping.json`` 的类型化视图。"""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = dict(payload)
        fields: Dict[str, FieldSpec] = {}
        for entry in payload.get("fields") or []:
            if not isinstance(entry, Mapping):
                raise ValueError("field_mapping.fields 的元素必须是对象")
            intent = str(entry.get("intent") or "").strip()
            if not intent:
                raise ValueError("field_mapping 存在没有 intent 的条目")
            if intent in fields:
                raise ValueError(f"field_mapping 存在重复 intent：{intent}")
            evidence = entry.get("evidence") or {}
            fields[intent] = FieldSpec(
                intent=intent,
                local_source=str(entry.get("local_source") or ""),
                stage=str(entry.get("stage") or ""),
                required=bool(entry.get("required")),
                platform_field=entry.get("platform_field"),
                evidence_level=str(evidence.get("level") or EVIDENCE_UNKNOWN),
                evidence_source=str(evidence.get("source") or ""),
                evidence_note=str(evidence.get("note") or ""),
                blocker_hint=str(entry.get("blocker_hint") or ""),
            )
        self.fields: Dict[str, FieldSpec] = fields

    @property
    def version(self) -> str:
        return str(self._payload.get("contract_version") or "")

    def get(self, intent: str) -> FieldSpec:
        if intent not in self.fields:
            raise KeyError(f"field_mapping 缺少 intent：{intent}")
        return self.fields[intent]

    def maybe(self, intent: str) -> Optional[FieldSpec]:
        return self.fields.get(intent)

    def by_stage(self, stage: str) -> List[FieldSpec]:
        return [spec for spec in self.fields.values() if spec.stage == stage]

    def blocked_fields(self) -> List[FieldSpec]:
        """所有**不允许**进入真实写操作的字段。"""

        return [spec for spec in self.fields.values() if not spec.write_eligible]

    def required_unmapped(self) -> List[FieldSpec]:
        """必填但拿不到平台字段名的字段——这些必须先解决才能真实发布。"""

        return [spec for spec in self.fields.values() if spec.required and not spec.write_eligible]

    def evidence_summary(self) -> Dict[str, int]:
        summary = {level: 0 for level in EVIDENCE_LEVELS}
        for spec in self.fields.values():
            summary[spec.evidence_level] = summary.get(spec.evidence_level, 0) + 1
        return summary


# ---------------------------------------------------------------------------
# 选择器契约
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SelectorSpec:
    key: str
    stage: str
    purpose: str
    selector: Optional[str]
    write_critical: bool
    evidence_level: str
    evidence_source: str
    #: 按**标签文本**定位时的字段名（如「宝贝标题」「一口价」）。
    #:
    #: 为什么需要它：真实表单里控件的 ``placeholder`` 大量重复（「请选择」出现 20+ 次），
    #: 而 **CSS 选择器无法按文本匹配**。只有 ``selector`` 时，实现方会被迫退化成
    #: 「第 N 个 input」——页面增删一个字段就整体错位，且每一步都会「成功」。
    #: 见 :mod:`taobao_publish.locating`。
    label: Optional[str] = None

    @property
    def available(self) -> bool:
        """有 CSS 选择器**或**有标签定位，才算拿到了定位手段。"""

        return bool(self.selector) or bool(self.label)

    @property
    def locator_kind(self) -> str:
        if self.label and self.selector:
            return "label+selector"
        if self.label:
            return "label"
        if self.selector:
            return "selector"
        return "none"


class SelectorContract:
    """``contracts/selectors.json`` 的类型化视图。"""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = dict(payload)
        items: Dict[str, SelectorSpec] = {}
        for entry in payload.get("selectors") or []:
            if not isinstance(entry, Mapping):
                raise ValueError("selectors 的元素必须是对象")
            key = str(entry.get("key") or "").strip()
            if not key:
                raise ValueError("selectors 存在没有 key 的条目")
            if key in items:
                raise ValueError(f"selectors 存在重复 key：{key}")
            evidence = entry.get("evidence") or {}
            items[key] = SelectorSpec(
                key=key,
                stage=str(entry.get("stage") or ""),
                purpose=str(entry.get("purpose") or ""),
                selector=entry.get("selector"),
                write_critical=bool(entry.get("write_critical")),
                evidence_level=str(evidence.get("level") or EVIDENCE_UNKNOWN),
                evidence_source=str(evidence.get("source") or ""),
                label=entry.get("label"),
            )
        self.selectors: Dict[str, SelectorSpec] = items

    def get(self, key: str) -> SelectorSpec:
        if key not in self.selectors:
            raise KeyError(f"selectors 缺少 key：{key}")
        return self.selectors[key]

    def missing_write_critical(self) -> List[SelectorSpec]:
        """写关键但未取证的选择器。非空则 DOM 写路线整体不可用。"""

        return [spec for spec in self.selectors.values() if spec.write_critical and not spec.available]

    def dom_write_route_ready(self) -> bool:
        return not self.missing_write_critical()

    def dom_ready_stages(self) -> "frozenset":
        """写关键选择器**全部就位**的阶段。

        这是 DOM 路线的「字段证据」：协议路线靠 ``field_mapping.json`` 里的
        ``platform_field`` 证明「这个字段知道往哪写」；DOM 路线靠**该阶段的写关键
        选择器全部可得**证明同一件事。

        为什么要这个：``field_mapping.json`` 的 ``blocker_hint`` 自己就写着
        「**或在 DOM 路线中确认……（contracts/selectors.json 的 base.title_input）**」，
        但 ``FieldSpec.write_eligible`` 硬要求 ``platform_field`` 非空——
        于是 DOM 路线证据齐了，字段照样被判为不可写，真实写入永远被拦。
        实测商品 ID-1083867541795：18 条静态阻塞项里 15 条是这类误报。
        """

        broken = {spec.stage for spec in self.missing_write_critical()}
        stages = {spec.stage for spec in self.selectors.values() if spec.write_critical}
        return frozenset(stages - broken)

    def evidence_summary(self) -> Dict[str, int]:
        summary = {level: 0 for level in EVIDENCE_LEVELS}
        for spec in self.selectors.values():
            summary[spec.evidence_level] = summary.get(spec.evidence_level, 0) + 1
        return summary


# ---------------------------------------------------------------------------
# 平台硬约束契约
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RuleSpec:
    """一条平台硬约束。"""

    name: str
    value: Any
    unit: str
    hard: bool
    evidence_level: str
    evidence_source: str
    evidence_note: str
    tolerance: Optional[float] = None

    def number(self) -> float:
        """按数值取用。契约里写成非数字时直接报错，不做隐式转换兜底。"""

        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ValueError(f"规则 {self.name} 的值不是数字：{self.value!r}")
        return float(self.value)

    def integer(self) -> int:
        value = self.number()
        if value != int(value):
            raise ValueError(f"规则 {self.name} 的值不是整数：{value}")
        return int(value)

    def strings(self) -> tuple:
        """按「标量列表」取用（例如允许的图片格式）。

        只接受 ``str`` 元素：允许的格式是枚举，混进数字没有意义。
        值不是列表时直接报错，不做「单值当单元素列表」的隐式兜底——
        那会让 ``"png,jpg"`` 这种写错的契约看起来能用。
        """

        if isinstance(self.value, str) or not isinstance(self.value, (list, tuple)):
            raise ValueError(f"规则 {self.name} 的值不是标量列表：{self.value!r}")
        result = []
        for item in self.value:
            if not isinstance(item, str):
                raise ValueError(f"规则 {self.name} 的列表元素不是字符串：{item!r}")
            result.append(item)
        return tuple(result)


class RulesContract:
    """``contracts/rules.json`` 的类型化视图。"""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = dict(payload)
        rules: Dict[str, RuleSpec] = {}
        for name, entry in (payload.get("rules") or {}).items():
            if not isinstance(entry, Mapping):
                raise ValueError(f"rules[{name}] 必须是对象")
            evidence = entry.get("evidence") or {}
            rules[str(name)] = RuleSpec(
                name=str(name),
                value=entry.get("value"),
                unit=str(entry.get("unit") or ""),
                hard=bool(entry.get("hard")),
                evidence_level=str(evidence.get("level") or EVIDENCE_UNKNOWN),
                evidence_source=str(evidence.get("source") or ""),
                evidence_note=str(evidence.get("note") or ""),
                tolerance=float(entry["tolerance"]) if entry.get("tolerance") is not None else None,
            )
        self.rules: Dict[str, RuleSpec] = rules
        self.unknown_rules: List[Dict[str, str]] = [
            {"name": str(item.get("name") or ""), "note": str(item.get("note") or "")}
            for item in (payload.get("unknown_rules") or [])
            if isinstance(item, Mapping)
        ]

    @property
    def version(self) -> str:
        return str(self._payload.get("contract_version") or "")

    def get(self, name: str) -> RuleSpec:
        if name not in self.rules:
            raise KeyError(f"rules 缺少规则：{name}")
        return self.rules[name]

    def number(self, name: str) -> float:
        return self.get(name).number()

    def integer(self, name: str) -> int:
        return self.get(name).integer()

    def evidence_summary(self) -> Dict[str, int]:
        summary = {level: 0 for level in EVIDENCE_LEVELS}
        for spec in self.rules.values():
            summary[spec.evidence_level] = summary.get(spec.evidence_level, 0) + 1
        return summary


# ---------------------------------------------------------------------------
# 汇总与自检
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Contracts:
    field_mapping: FieldMappingContract
    selectors: SelectorContract
    rules: RulesContract
    publish_item_schema: Dict[str, Any]


def load_contracts() -> Contracts:
    """一次性加载全部契约。"""

    return Contracts(
        field_mapping=FieldMappingContract(load_contract(CONTRACT_FIELD_MAPPING)),
        selectors=SelectorContract(load_contract(CONTRACT_SELECTORS)),
        rules=RulesContract(load_contract(CONTRACT_RULES)),
        publish_item_schema=load_contract(CONTRACT_PUBLISH_ITEM_SCHEMA),
    )


def validate_contracts(contracts: Optional[Contracts] = None) -> List[str]:
    """自检契约与代码常量的一致性。

    :return: 问题清单（空列表表示通过）。**调用方必须把非空结果当错误处理**，
        不要只打日志。
    """

    data = contracts if contracts is not None else load_contracts()
    problems: List[str] = []

    # 阶段登记表必须与 STAGE_ORDER 一一对应。
    # 漏登记的写阶段会被 ``STAGE_WRITE_OPERATION.get()`` 当成只读（返回 None），
    # 这是**fail open**，必须在自检里拦住。
    from .constants import STAGE_WRITE_OPERATION

    for stage in STAGE_ORDER:
        if stage not in STAGE_WRITE_OPERATION:
            problems.append(f"STAGE_WRITE_OPERATION 缺少阶段登记：{stage}（漏登记会被当成只读阶段）")
    for stage in STAGE_WRITE_OPERATION:
        if stage not in STAGE_ORDER:
            problems.append(f"STAGE_WRITE_OPERATION 登记了不在 STAGE_ORDER 里的阶段：{stage}")

    known_stages = set(STAGE_ORDER)
    for spec in data.field_mapping.fields.values():
        if spec.stage and spec.stage not in known_stages:
            problems.append(f"field_mapping[{spec.intent}].stage 不是已知阶段：{spec.stage}")
        if spec.evidence_level not in EVIDENCE_LEVELS:
            problems.append(
                f"field_mapping[{spec.intent}].evidence.level 非法：{spec.evidence_level}"
            )
        if spec.platform_field is not None and not isinstance(spec.platform_field, str):
            problems.append(
                f"field_mapping[{spec.intent}].platform_field 必须是字符串或 null，"
                f"实际是 {type(spec.platform_field).__name__}（{spec.platform_field!r}）"
            )
        if isinstance(spec.platform_field, str) and spec.platform_field != spec.platform_field.strip():
            problems.append(
                f"field_mapping[{spec.intent}].platform_field 含首尾空白：{spec.platform_field!r}"
            )
        if isinstance(spec.platform_field, str) and not spec.platform_field.strip():
            problems.append(
                f"field_mapping[{spec.intent}].platform_field 是纯空白：{spec.platform_field!r}"
            )
        if spec.evidence_level == EVIDENCE_VERIFIED and not spec.evidence_source:
            problems.append(
                f"field_mapping[{spec.intent}] 标为 verified 但没有 evidence.source（证据必须可追溯）"
            )
        if spec.evidence_level == EVIDENCE_VERIFIED and spec.platform_field is None:
            problems.append(
                f"field_mapping[{spec.intent}] 标为 verified 但 platform_field 仍是 null"
                "（证据等级与字段名自相矛盾：既然已实证，就该写上字段名）"
            )
        if not spec.write_eligible and spec.required and not spec.blocker_hint:
            problems.append(
                f"field_mapping[{spec.intent}] 是必填但不可写，却没有 blocker_hint（后人不知道要做什么）"
            )

    for spec in data.selectors.selectors.values():
        if spec.stage and spec.stage not in known_stages:
            problems.append(f"selectors[{spec.key}].stage 不是已知阶段：{spec.stage}")
        if spec.evidence_level not in EVIDENCE_LEVELS:
            problems.append(f"selectors[{spec.key}].evidence.level 非法：{spec.evidence_level}")
        if spec.available and spec.evidence_level == EVIDENCE_UNKNOWN:
            problems.append(
                f"selectors[{spec.key}] 已填选择器但证据仍是 unknown（取证必须留痕）"
            )

    for spec in data.rules.rules.values():
        if spec.evidence_level not in EVIDENCE_LEVELS:
            problems.append(f"rules[{spec.name}].evidence.level 非法：{spec.evidence_level}")
        if spec.evidence_level == EVIDENCE_VERIFIED and not spec.evidence_source:
            problems.append(f"rules[{spec.name}] 标为 verified 但没有 evidence.source")
        # 值允许标量，也允许**标量列表**（例如允许的图片格式枚举）。
        # 列表里不允许再嵌套列表/字典——那是把契约当配置文件用了。
        if isinstance(spec.value, bool):
            problems.append(f"rules[{spec.name}].value 不应是布尔：{spec.value!r}")
        elif isinstance(spec.value, (list, tuple)):
            if not spec.value:
                problems.append(f"rules[{spec.name}].value 是空列表，没有意义")
            for item in spec.value:
                if isinstance(item, bool) or not isinstance(item, (int, float, str)):
                    problems.append(
                        f"rules[{spec.name}].value 的列表元素类型不支持：{type(item).__name__}（{item!r}）"
                    )
        elif not isinstance(spec.value, (int, float, str)):
            problems.append(f"rules[{spec.name}].value 类型不支持：{type(spec.value).__name__}")

    for name in (
        "title_max_chars",
        "main_image_min_count",
        "main_image_max_count",
        "main_image_min_side_px",
        "sku_min_count",
        "sku_price_min",
    ):
        if name not in data.rules.rules:
            problems.append(f"rules 缺少必需规则：{name}")
        elif not data.rules.get(name).hard:
            problems.append(f"rules[{name}] 被流水线当作硬约束使用，但契约里 hard=false")

    schema = data.publish_item_schema
    if schema.get("type") != "object":
        problems.append("publish_item.schema.json 顶层 type 必须是 object")
    required = schema.get("required") or []
    if "record_id" not in required or "title" not in required or "skus" not in required:
        problems.append("publish_item.schema.json 的 required 必须包含 record_id / title / skus")

    return problems


def write_route_status(contracts: Optional[Contracts] = None) -> Dict[str, Any]:
    """给 CLI / API 用的一览：两条写路线当前到底能不能用。

    **契约自检有未解决问题时，两条路线一律报告为不可用。** 自检报错却仍宣称
    「可以发布」，等于让自检形同虚设（对抗性审查 2026-10-02，F8）。
    """

    data = contracts if contracts is not None else load_contracts()
    problems = validate_contracts(data)
    field_blocked = data.field_mapping.required_unmapped()
    selector_blocked = data.selectors.missing_write_critical()
    contracts_ok = not problems
    return {
        "contract_version": data.field_mapping.version,
        "rules_version": data.rules.version,
        "contract_problems": problems,
        "field_evidence": data.field_mapping.evidence_summary(),
        "selector_evidence": data.selectors.evidence_summary(),
        "rule_evidence": data.rules.evidence_summary(),
        "protocol_write_ready": contracts_ok and not field_blocked,
        "dom_write_ready": contracts_ok and not selector_blocked,
        "blocked_required_fields": [spec.intent for spec in field_blocked],
        "blocked_write_critical_selectors": [spec.key for spec in selector_blocked],
        "unknown_rules": list(data.rules.unknown_rules),
    }

def assert_contracts_usable(contracts: Optional[Contracts] = None) -> List[str]:
    """返回契约问题清单；**非空即意味着不允许组装真实写载荷**。

    这是自检结果唯一的强制消费点，调用方必须检查返回值。
    """

    return validate_contracts(contracts)


def iter_evidence_rows(contracts: Optional[Contracts] = None) -> Iterable[Tuple[str, str, str, str]]:
    """产出 ``(类别, 标识, 证据等级, 来源)`` 元组，供文档生成与人工巡检。"""

    data = contracts if contracts is not None else load_contracts()
    for spec in data.field_mapping.fields.values():
        yield ("field", spec.intent, spec.evidence_level, spec.evidence_source)
    for spec in data.selectors.selectors.values():
        yield ("selector", spec.key, spec.evidence_level, spec.evidence_source)

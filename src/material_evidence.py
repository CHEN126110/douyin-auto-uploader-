# -*- coding: utf-8 -*-
"""按商品证据解析面料成分；不靠默认值补齐、归一化或猜测缺失比例。

优先级：采集到的结构化商品参数 > 商品级备注 / 标题 / SKU 名称 > 用户默认配置。
SKU 的 ``remark`` 是该 SKU 的备注，不是商品材质来源，这里故意不读取它。
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import re


class MaterialEvidenceError(ValueError):
    """商品材质信息不完整、冲突或损坏，必须人工确认后才能写入。"""


# 只用于定位文字中的材质信号，不是平台选项白名单。结构化字段可保留其它真实名称。
_MATERIAL_WORDS = (
    '再生纤维素纤维', '聚酯纤维', '桑蚕丝', '绵羊毛', '精梳棉', '丝光棉',
    '莫代尔', '莱赛尔', '粘胶纤维', '粘纤', '竹纤维', '铜氨纤维',
    '聚丙烯腈纤维', '聚酰胺纤维', '聚氨酯弹性纤维', '腈纶', '锦纶',
    '氨纶', '涤纶', '丙纶', '维纶', '氯纶', '羊毛', '兔毛',
    '羊绒', '驼绒', '马海毛', '蚕丝', '亚麻', '苎麻', '纯棉', '全棉', '棉',
)
_MATERIAL_WORD_RE = re.compile('|'.join(re.escape(word) for word in _MATERIAL_WORDS))
_PAIR_RE = re.compile(
    r'(?P<name>[^\d%:：;；，,。｜|\r\n]{1,80}?)'
    r'\s*(?P<percentage>-?(?:\d+(?:\.\d*)?|\.\d+))\s*%'
)
_MATERIAL_FIELD_NAMES = {
    '材质', '材质成分', '材质面料', '面料', '面料材质', '面料成分',
    '成分', '成分含量', '纤维成分', '纤维含量', '主面料材质',
}


@dataclass(frozen=True)
class MaterialResolution:
    materials: tuple
    source: str

    @property
    def text(self):
        return ';'.join(f'{name}{percentage}%' for name, percentage in self.materials)


@dataclass(frozen=True)
class _Evidence:
    pairs: tuple = ()
    signals: frozenset = frozenset()
    issues: tuple = ()
    present: bool = False


def _percentage(value):
    try:
        number = Decimal(str(value).strip().rstrip('%').strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        raise MaterialEvidenceError(f'材质比例「{value}」不是有效数字')
    if not number.is_finite() or number <= 0 or number > 100:
        raise MaterialEvidenceError(f'材质比例「{value}」必须在 0% 到 100% 之间')
    text = format(number, 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return number, text


def format_material_percentage(value):
    """配置与协议共用的比例格式化；保留小数，不静默取整。"""
    return _percentage(value)[1]


def _canonical_name(name):
    """只用于证据一致性比较；写入平台时仍保留用户配置的完整材质名称。"""
    normalized = re.sub(r'\s+', '', str(name or ''))
    normalized = re.sub(r'[（(][^）)]*[）)]$', '', normalized)
    aliases = {
        '纯棉': '棉', '全棉': '棉', '绵羊毛': '羊毛',
        '涤纶': '聚酯纤维', '锦纶': '聚酰胺纤维',
        '腈纶': '聚丙烯腈纤维', '氨纶': '聚氨酯弹性纤维',
        '粘纤': '粘胶纤维',
    }
    return aliases.get(normalized, normalized).casefold()


def _structured_evidence(raw):
    if raw is None or raw == '':
        return _Evidence()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise MaterialEvidenceError('结构化商品属性不是有效 JSON，请重新采集或修正资料') from exc
    if not isinstance(raw, dict) or not isinstance(raw.get('attributes'), list):
        raise MaterialEvidenceError('结构化商品属性格式无效，请重新采集或修正资料')

    evidences = []
    for entry in raw['attributes']:
        if not isinstance(entry, dict):
            raise MaterialEvidenceError('结构化商品属性条目格式无效')
        name = entry.get('name')
        value = entry.get('value')
        if not isinstance(name, str) or not isinstance(value, str):
            raise MaterialEvidenceError('结构化商品属性必须提供文字名称和值')
        normalized_name = re.sub(r'[\s_\-—/]+', '', name).strip(' :：')
        if normalized_name in _MATERIAL_FIELD_NAMES:
            evidences.append(_text_evidence(value, explicit=True))
    return _merge_evidence(evidences)


def _text_evidence(text, explicit=False):
    text = str(text or '').replace('％', '%').strip()
    if not text:
        return _Evidence(present=explicit)
    signals = frozenset(_canonical_name(match.group()) for match in _MATERIAL_WORD_RE.finditer(text))
    pairs = []
    issues = []
    for match in _PAIR_RE.finditer(text):
        raw_name = match.group('name').strip(' \t()（）[]【】')
        known_names = [word for word in _MATERIAL_WORDS if raw_name.endswith(word)]
        if known_names:
            name = max(known_names, key=len)
            prefix = raw_name[:-len(name)]
            if _MATERIAL_WORD_RE.search(prefix):
                issues.append(f'材质成分不完整：「{raw_name}{match.group("percentage")}%」中多个材质共用一个比例，含义不明确')
                continue
        else:
            # 普通文案只接受明确的纤维名称；避免把“100%正品”当材质。
            if not explicit and not re.search(r'(?:纤维|棉|毛|丝|纶|麻|绒)$', raw_name):
                continue
            name = re.sub(
                r'^(?:主要|主面料|面料材质|材质成分|纤维含量|成分含量|面料|材质|成分|采用|含有|含|为|是)+',
                '', raw_name,
            ).strip()
            if not name or len(name) > 40 or re.search(r'\s', name):
                issues.append(f'无法可靠识别「{match.group()}」的材质名称')
                continue
        try:
            _number, percentage = _percentage(match.group('percentage'))
        except MaterialEvidenceError as exc:
            issues.append(str(exc))
            continue
        pairs.append((name, percentage))
    if explicit and not pairs:
        issues.append('结构化材质字段没有给出可核实的完整成分及百分比')
    return _Evidence(
        pairs=_unique_pairs(pairs),
        signals=signals,
        issues=tuple(issues),
        present=bool(explicit or signals or pairs or issues),
    )


def _unique_pairs(pairs):
    result = []
    seen = {}
    for name, percentage in pairs:
        name = str(name or '').strip()
        if not name:
            raise MaterialEvidenceError('材质名称不能为空')
        key = _canonical_name(name)
        if key in seen and seen[key] != percentage:
            raise MaterialEvidenceError(f'材质「{name}」存在冲突比例：{seen[key]}% 与 {percentage}%')
        if key not in seen:
            seen[key] = percentage
            result.append((name, percentage))
    return tuple(result)


def _merge_evidence(evidences):
    pairs = []
    signals = set()
    issues = []
    present = False
    for evidence in evidences:
        pairs.extend(evidence.pairs)
        signals.update(evidence.signals)
        issues.extend(evidence.issues)
        present = present or evidence.present
    return _Evidence(_unique_pairs(pairs), frozenset(signals), tuple(issues), present)


def _complete_materials(evidence, origin):
    if not evidence.present:
        return None
    if evidence.issues:
        raise MaterialEvidenceError(f'{origin}：' + '；'.join(evidence.issues))
    if not evidence.pairs:
        raise MaterialEvidenceError(f'{origin}：检测到材质信息，但没有可靠百分比，请按真实商品资料补齐')
    total = sum((_percentage(percentage)[0] for _name, percentage in evidence.pairs), Decimal('0'))
    if total != 100:
        detail = '；'.join(f'{name}{percentage}%' for name, percentage in evidence.pairs)
        raise MaterialEvidenceError(
            f'{origin}：材质成分不完整，已识别 {detail}，合计 {_percentage(total)[1]}%；'
            '请人工补齐真实成分，不会用默认材质凑成100%'
        )
    names = {_canonical_name(name) for name, _percentage_text in evidence.pairs}
    missing_signals = evidence.signals - names
    if missing_signals:
        raise MaterialEvidenceError(
            f'{origin}：材质信息不完整或冲突，以下材质没有对应比例：{"、".join(sorted(missing_signals))}'
        )
    return evidence.pairs


def _composition_is_declared(text):
    """区分明确成分声明与标题/卖点里的简略材质线索。"""
    value = str(text or '').replace('％', '%')
    has_declaration_label = re.search(r'(?:材质|面料|成分|纤维含量|纤维成分)\s*[:：为是]', value)
    has_composition_context = '%' in value and re.search(r'(?:材质|面料|成分|纤维含量|纤维成分)', value)
    return bool(has_declaration_label or has_composition_context)


def _complete_weak_materials(evidence):
    """简略文字只有在自身已经构成完整成分表时，才替代用户配置。"""
    if not evidence.present or evidence.issues or not evidence.pairs:
        return None
    total = sum((_percentage(percentage)[0] for _name, percentage in evidence.pairs), Decimal('0'))
    if total != 100:
        return None
    return _complete_materials(evidence, '商品文字资料')


def _validate_text_against_materials(text, resolved_pairs, *, origin, weak=False):
    if not text.present:
        return
    if text.issues and not weak:
        raise MaterialEvidenceError(f'{origin}与其它商品文字资料无法一致核对：' + '；'.join(text.issues))
    resolved = {_canonical_name(name): percentage for name, percentage in resolved_pairs}
    for name, percentage in text.pairs:
        if resolved.get(_canonical_name(name)) != percentage:
            raise MaterialEvidenceError(
                f'{origin}与其它商品文字资料的材质比例冲突：{name}{percentage}%'
            )
    if text.signals - set(resolved):
        raise MaterialEvidenceError(
            f'{origin}与其它商品文字资料的材质种类冲突：' + '、'.join(sorted(text.signals - set(resolved)))
        )


def _validate_default_against_weak_text(text, default_pairs):
    """简略线索不能强拆比例，但仍要防止默认配置漏掉材质或违背明确比例。"""
    if not text.present:
        return
    defaults = {_canonical_name(name): percentage for name, percentage in default_pairs}
    missing = text.signals - set(defaults)
    if missing:
        raise MaterialEvidenceError(
            '默认材质配置未包含商品提到的材质：' + '、'.join(sorted(missing)) + '；请核对商品真实成分'
        )
    for name, percentage in text.pairs:
        configured = defaults.get(_canonical_name(name))
        if configured != percentage:
            raise MaterialEvidenceError(
                f'默认材质配置与商品文字资料中的明确比例冲突：{name}{percentage}%'
            )


def _default_materials(configured_materials):
    pairs = []
    for item in configured_materials or []:
        if isinstance(item, dict):
            name = str(item.get('material') or item.get('name') or '').strip()
            raw_percentage = item.get('percentage', item.get('percent'))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            name, raw_percentage = str(item[0] or '').strip(), item[1]
        else:
            raise MaterialEvidenceError('默认材质配置格式无效')
        _number, percentage = _percentage(raw_percentage)
        pairs.append((name, percentage))
    evidence = _Evidence(pairs=_unique_pairs(pairs), present=bool(pairs))
    if not evidence.present:
        raise MaterialEvidenceError('商品没有可用材质证据，且未配置默认材质，请先补齐真实成分')
    return _complete_materials(evidence, '默认材质配置')


def resolve_material_composition(record, configured_materials):
    """返回可写入的 ``(材质名, 百分比字符串)``，不确定时抛出明确错误。"""
    structured = _structured_evidence(getattr(record, 'captured_attributes', None))
    sku_texts = []
    try:
        content = json.loads(getattr(record, 'content', '') or '[]')
    except (TypeError, ValueError):
        content = []
    if isinstance(content, list):
        # 只读 SKU 名称；SKU 备注是商家备注，不能升级为商品材质事实。
        sku_texts = [item.get('name', '') for item in content if isinstance(item, dict)]
    texts = [getattr(record, 'remark', ''), getattr(record, 'title', ''), *sku_texts]
    strong_text = _merge_evidence([
        _text_evidence(value) for value in texts if _composition_is_declared(value)
    ])
    weak_text = _merge_evidence([
        _text_evidence(value) for value in texts if not _composition_is_declared(value)
    ])
    if structured.present:
        materials = _complete_materials(structured, '商品结构化属性')
        _validate_text_against_materials(strong_text, materials, origin='商品结构化属性')
        _validate_text_against_materials(weak_text, materials, origin='商品结构化属性', weak=True)
        return MaterialResolution(materials, '商品结构化属性')
    materials = _complete_materials(strong_text, '商品文字资料')
    if materials:
        _validate_text_against_materials(weak_text, materials, origin='商品文字资料', weak=True)
        return MaterialResolution(materials, '商品文字资料')
    materials = _complete_weak_materials(weak_text)
    if materials:
        return MaterialResolution(materials, '商品文字资料')
    materials = _default_materials(configured_materials)
    _validate_default_against_weak_text(weak_text, materials)
    return MaterialResolution(materials, '用户默认配置')

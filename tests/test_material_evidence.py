# -*- coding: utf-8 -*-
"""商品材质证据优先级、完整性和 SKU 备注边界。"""
import json
from types import SimpleNamespace

import pytest

from src.material_evidence import MaterialEvidenceError, resolve_material_composition


DEFAULT = [('棉', '75'), ('氨纶', '25')]


def record(**values):
    data = dict(title='秋冬中筒袜', remark='', content='[]', captured_attributes=None)
    data.update(values)
    return SimpleNamespace(**data)


def captured(name, value):
    return json.dumps({
        'version': 1,
        'source': 'visible_product_parameters_v1',
        'status': 'captured',
        'attributes': [{'name': name, 'value': value}],
    }, ensure_ascii=False)


def test_complete_structured_material_wins_over_default_and_supports_decimal():
    result = resolve_material_composition(
        record(captured_attributes=captured('面料材质', '桑蚕丝6.4%; 羊毛93.6%')),
        DEFAULT,
    )
    assert result.materials == (('桑蚕丝', '6.4'), ('羊毛', '93.6'))
    assert result.source == '商品结构化属性'


def test_complete_text_material_is_used_without_structured_attributes():
    result = resolve_material_composition(record(remark='成分：棉80%；聚酯纤维20%'), DEFAULT)
    assert result.materials == (('棉', '80'), ('聚酯纤维', '20'))
    assert result.source == '商品文字资料'


def test_no_product_evidence_keeps_legacy_default():
    result = resolve_material_composition(record(), DEFAULT)
    assert result.materials == tuple(DEFAULT)
    assert result.source == '用户默认配置'


def current_silk_wool_record():
    return record(
        title='songmu淞木 两穿小腿袜女 桑蚕丝羊毛堆堆袜直筒袜',
        remark='两穿直筒堆堆｜桑蚕丝羊毛6.4%｜分段抽条显瘦｜均码35-40',
    )


def test_shorthand_does_not_force_an_unrelated_default():
    with pytest.raises(MaterialEvidenceError, match='未包含商品提到的材质'):
        resolve_material_composition(current_silk_wool_record(), DEFAULT)


def test_shorthand_uses_complete_compatible_configuration_without_splitting_ratio():
    configured = [
        ('桑蚕丝', '3'), ('绵羊毛', '3'), ('聚酯纤维', '44'),
        ('聚酰胺纤维（锦纶）', '25'), ('聚丙烯腈纤维（腈纶）', '24'),
        ('聚氨酯弹性纤维（氨纶）', '1'),
    ]
    result = resolve_material_composition(current_silk_wool_record(), configured)
    assert result.materials == tuple(configured)
    assert result.source == '用户默认配置'


def test_partial_percentage_is_not_completed_with_default_or_normalized():
    with pytest.raises(MaterialEvidenceError, match='不完整') as error:
        resolve_material_composition(record(remark='材质：羊毛6.4%'), DEFAULT)
    assert '6.4%' in str(error.value) and '100%' in str(error.value)


def test_declared_material_name_without_ratio_is_not_enough():
    with pytest.raises(MaterialEvidenceError, match='没有可靠百分比'):
        resolve_material_composition(record(remark='材质：纯棉'), DEFAULT)


def test_unlabeled_material_name_only_checks_default_coverage():
    result = resolve_material_composition(record(title='纯棉中筒袜'), DEFAULT)
    assert result.materials == tuple(DEFAULT)


def test_complete_unlabeled_composition_still_wins_over_default():
    result = resolve_material_composition(record(remark='棉80%;聚酯纤维20%'), DEFAULT)
    assert result.materials == (('棉', '80'), ('聚酯纤维', '20'))
    assert result.source == '商品文字资料'


def test_weak_but_unambiguous_ratio_conflict_is_rejected():
    configured = [('绵羊毛', '3'), ('聚酯纤维', '97')]
    with pytest.raises(MaterialEvidenceError, match='明确比例冲突'):
        resolve_material_composition(record(remark='羊毛6.4%'), configured)


def test_complete_declared_text_does_not_ignore_conflicting_title():
    with pytest.raises(MaterialEvidenceError, match='材质种类冲突'):
        resolve_material_composition(record(title='桑蚕丝中筒袜', remark='材质：棉100%'), DEFAULT)


def test_conflicting_structured_and_text_values_are_rejected():
    with pytest.raises(MaterialEvidenceError, match='冲突'):
        resolve_material_composition(record(
            captured_attributes=captured('材质成分', '棉75%;氨纶25%'),
            remark='真实成分：桑蚕丝6.4%;羊毛93.6%',
        ), DEFAULT)


def test_duplicate_material_with_different_ratios_is_rejected():
    with pytest.raises(MaterialEvidenceError, match='冲突比例'):
        resolve_material_composition(record(remark='棉60%;棉40%'), DEFAULT)


def test_sku_remark_is_only_a_note_not_product_material_evidence():
    content = json.dumps([{'name': '奶白', 'remark': '仓库备注：桑蚕丝6.4%;羊毛93.6%'}], ensure_ascii=False)
    result = resolve_material_composition(record(content=content), DEFAULT)
    assert result.materials == tuple(DEFAULT)


def test_sku_name_material_conflict_is_not_hidden():
    content = json.dumps([{'name': '桑蚕丝款'}], ensure_ascii=False)
    with pytest.raises(MaterialEvidenceError, match='未包含商品提到的材质'):
        resolve_material_composition(record(content=content), DEFAULT)


def test_invalid_structured_data_never_silently_uses_default():
    with pytest.raises(MaterialEvidenceError, match='JSON'):
        resolve_material_composition(record(captured_attributes='{broken'), DEFAULT)


def test_default_must_also_be_complete():
    with pytest.raises(MaterialEvidenceError, match='不完整'):
        resolve_material_composition(record(), [('羊毛', '6.4')])


def test_no_evidence_and_no_default_is_an_explicit_error():
    with pytest.raises(MaterialEvidenceError, match='未配置默认材质'):
        resolve_material_composition(record(), [])

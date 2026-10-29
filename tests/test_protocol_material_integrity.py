# -*- coding: utf-8 -*-
"""协议提交体的材质契约：显式比例、小数保真、禁止缺失时编造100%。"""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def protocol():
    path = Path(__file__).resolve().parents[1] / 'protocol-research-clean-20260505/scripts/fxg_protocol_v4.py'
    spec = importlib.util.spec_from_file_location('_fxg_protocol_material_contract', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(protocol, material):
    return protocol.step_build_body_offline(
        product_data={
            'title': '真实成分测试中筒袜',
            'sku_info': [{'name': '奶白', 'price': 12.9, 'stock': 10}],
            'material': material,
        },
        image_urls={},
        category_config={'category_leaf_id': 1000010267},
        publish_id='test',
        shop_id='shop',
        freight_id='freight',
    )


def test_protocol_preserves_decimal_material_percentages(protocol):
    result = build(protocol, '桑蚕丝6.4%;羊毛93.6%')
    assert result['success'] is True, result
    materials = result['data']['body']['schema']['model']['category_properties']['value']['785']
    assert [entry['value_name'] for entry in materials] == ['桑蚕丝6.4%', '羊毛93.6%']
    assert [entry['measure_info']['values'][1]['value'] for entry in materials] == ['6.4', '93.6']


@pytest.mark.parametrize('material', ['羊毛', '羊毛6.4%', '羊毛0%;其他100%', '棉75%;氨纶25'])
def test_protocol_rejects_missing_or_incomplete_material_ratios(protocol, material):
    result = build(protocol, material)
    assert result['success'] is False
    assert result['error']['code'] == 'INVALID_MATERIAL'

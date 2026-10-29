# -*- coding: utf-8 -*-
"""SKU 主规格与平台动态附加规格列的边界。"""


def primary_spec_name(sku) -> str:
    """返回创建器使用的主规格名；附加列不参与主规格行身份。"""
    values = getattr(sku, 'spec_values', None) or {}
    if '颜色分类' in values:
        return '颜色分类'
    return next(iter(values), '')


def primary_spec_value(sku) -> str:
    """主规格值；只用于匹配创建器和表格行，不把附加列拼进行身份。"""
    name = primary_spec_name(sku)
    return str((getattr(sku, 'spec_values', None) or {}).get(name, '') or '').strip()

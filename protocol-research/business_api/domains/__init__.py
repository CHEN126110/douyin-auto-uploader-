# -*- coding: utf-8 -*-
"""业务域汇总：导出全部 Blueprint 与域清单。"""
from typing import List

from flask import Blueprint

from .aftersale import bp as aftersale_bp
from .compass import bp as compass_bp
from .marketing import bp as marketing_bp
from .order import bp as order_bp
from .product import bp as product_bp
from .skeletons import build_skeleton_blueprints, domain_catalog

# 已联调真实跑通的业务域（单一事实来源，供 /health、/catalog 复用，避免各处硬编码漏域）
IMPLEMENTED_DOMAINS: List[str] = ["product", "order", "aftersale", "compass", "marketing"]


def all_blueprints() -> List[Blueprint]:
    """商品 / 订单 / 售后 / 罗盘 / 营销（真实）+ 其余域（契约骨架）。"""
    return [
        product_bp, order_bp, aftersale_bp, compass_bp, marketing_bp,
    ] + build_skeleton_blueprints()


__all__ = ["all_blueprints", "domain_catalog", "IMPLEMENTED_DOMAINS"]

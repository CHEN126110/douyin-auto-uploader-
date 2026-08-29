# -*- coding: utf-8 -*-
"""其余业务域的接口契约骨架。

每个域定义一组 SkeletonEndpoint，统一生成 Blueprint。这些接口的 API 面已完整可对接，
真实 DOM 编排待在登录环境联调后逐个填充（实现模式参考 product.py）。
"""
from __future__ import annotations

from typing import Dict, List

from flask import Blueprint

from .base import SkeletonEndpoint as SE
from .base import register_skeleton

# domain -> {title, prefix, endpoints}
SKELETON_DOMAINS: Dict[str, dict] = {
    "traffic": {
        "title": "流量运营",
        "prefix": "/api/traffic",
        "endpoints": [
            SE("POST", "/overview", "overview", "流量概览（访客数 / 曝光 / 点击）",
               [{"name": "date_range", "desc": "统计周期，如 7d/30d"}]),
            SE("POST", "/keywords", "keywords", "搜索关键词数据"),
            SE("POST", "/sources", "sources", "流量来源分布"),
        ],
    },
    "ad": {
        "title": "付费推广",
        "prefix": "/api/ad",
        "endpoints": [
            SE("POST", "/campaigns", "campaigns", "推广计划列表"),
            SE("POST", "/campaign/create", "campaign_create", "新建推广计划"),
            SE("POST", "/campaign/budget", "campaign_budget", "调整推广预算",
               [{"name": "campaign_id", "required": True}, {"name": "budget", "required": True}]),
            SE("POST", "/campaign/toggle", "campaign_toggle", "启停推广计划",
               [{"name": "campaign_id", "required": True}, {"name": "enable", "required": True}]),
        ],
    },
    "shop": {
        "title": "店铺",
        "prefix": "/api/shop",
        "endpoints": [
            SE("POST", "/info", "info", "店铺基础信息"),
            SE("POST", "/score", "score", "店铺体验分 / 口碑分"),
            SE("POST", "/notice", "notice", "商家公告查看 / 设置"),
        ],
    },
    "user": {
        "title": "用户",
        "prefix": "/api/user",
        "endpoints": [
            SE("POST", "/profile", "profile", "当前登录账号信息"),
            SE("POST", "/sub-accounts", "sub_accounts", "子账号列表"),
            SE("POST", "/permissions", "permissions", "权限信息"),
        ],
    },
    "fund": {
        "title": "资金",
        "prefix": "/api/fund",
        "endpoints": [
            SE("POST", "/balance", "balance", "账户余额"),
            SE("POST", "/bills", "bills", "账单流水",
               [{"name": "date_range"}, {"name": "page"}]),
            SE("POST", "/settlement", "settlement", "结算记录"),
            SE("POST", "/withdraw-records", "withdraw_records", "提现记录"),
        ],
    },
    "qianchuan": {
        "title": "巨量千川",
        "prefix": "/api/qianchuan",
        "endpoints": [
            SE("POST", "/account", "account", "账户信息与余额"),
            SE("POST", "/campaigns", "campaigns", "千川计划列表"),
            SE("POST", "/report", "report", "数据报表",
               [{"name": "date_range"}, {"name": "metrics", "desc": "指标列表"}]),
            SE("POST", "/campaign/budget", "campaign_budget", "调整计划预算",
               [{"name": "campaign_id", "required": True}, {"name": "budget", "required": True}]),
        ],
    },
}


def build_skeleton_blueprints() -> List[Blueprint]:
    blueprints: List[Blueprint] = []
    for domain, cfg in SKELETON_DOMAINS.items():
        bp = Blueprint(domain, __name__, url_prefix=cfg["prefix"])
        register_skeleton(bp, cfg["endpoints"], domain)
        blueprints.append(bp)
    return blueprints


def domain_catalog() -> List[dict]:
    """返回域 + 接口清单，供 /catalog 端点与文档使用。"""
    catalog: List[dict] = []
    for domain, cfg in SKELETON_DOMAINS.items():
        catalog.append(
            {
                "domain": domain,
                "title": cfg["title"],
                "prefix": cfg["prefix"],
                "endpoints": [
                    {
                        "method": e.method,
                        "path": cfg["prefix"] + e.path,
                        "name": e.name,
                        "summary": e.summary,
                        "params": e.params,
                    }
                    for e in cfg["endpoints"]
                ],
            }
        )
    return catalog

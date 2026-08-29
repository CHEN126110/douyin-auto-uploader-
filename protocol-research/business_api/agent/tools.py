# -*- coding: utf-8 -*-
"""面向 Agent 的工具清单与 schema 导出。

设计要点（为 Agent 经营店铺考虑）：
- 每个业务接口 = 一个工具，name=域.动作，带机器可读 inputSchema 与决策元数据。
- read_only / destructive：让 Agent 区分"查询"与"会改动店铺的写操作"。
- 写操作默认 dry_run（预演定位不提交），需 Agent 显式 confirm=true 才真实执行，防误操作。
- 业务接口命中验证码 / 登录失效会返回 CAPTCHA_REQUIRED / LOGIN_REQUIRED，Agent 据此交回人类。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ..domains.skeletons import SKELETON_DOMAINS


@dataclass
class ToolSpec:
    name: str
    description: str
    http_method: str
    http_path: str
    input_schema: dict
    read_only: bool = True
    destructive: bool = False
    requires_confirm: bool = False
    implemented: bool = True

    def to_mcp(self) -> dict:
        desc = self.description
        if not self.implemented:
            desc += "（未联调真实页面，调用将返回 NOT_IMPLEMENTED）"
        return {
            "name": self.name,
            "description": desc,
            "inputSchema": self.input_schema or {"type": "object", "properties": {}},
            "annotations": {
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
            },
            "_meta": {
                "httpMethod": self.http_method,
                "httpPath": self.http_path,
                "requiresConfirm": self.requires_confirm,
                "implemented": self.implemented,
            },
        }


def _obj(props: dict, required: list = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


# --- 已联调的真实工具 ---
REAL_TOOLS: List[ToolSpec] = [
    ToolSpec(
        "product.list",
        "查询商品列表（标题/商品ID/价格/销量/状态）。只读，安全。",
        "POST", "/api/product/list",
        _obj({
            "keyword": {"type": "string", "description": "按标题或商品ID过滤，可空"},
            "limit": {"type": "integer", "description": "返回数量上限", "default": 20},
        }),
        read_only=True, destructive=False,
    ),
    ToolSpec(
        "product.off_shelf",
        "将指定商品下架。写操作：默认 dry_run 仅预演定位，需 confirm=true 才真实下架。",
        "POST", "/api/product/off-shelf",
        _obj({
            "product_id": {"type": "string", "description": "商品ID"},
            "dry_run": {"type": "boolean", "description": "预演模式，仅定位不提交", "default": True},
            "confirm": {"type": "boolean", "description": "确认真实执行下架", "default": False},
        }, ["product_id"]),
        read_only=False, destructive=True, requires_confirm=True,
    ),
    ToolSpec(
        "product.on_shelf",
        "将指定商品上架。写操作：默认 dry_run 仅预演定位，需 confirm=true 才真实上架。",
        "POST", "/api/product/on-shelf",
        _obj({
            "product_id": {"type": "string", "description": "商品ID"},
            "dry_run": {"type": "boolean", "default": True},
            "confirm": {"type": "boolean", "default": False},
        }, ["product_id"]),
        read_only=False, destructive=True, requires_confirm=True,
    ),
]

# --- 商品域骨架工具（待联调） ---
PRODUCT_SKELETON_TOOLS: List[ToolSpec] = [
    ToolSpec("product.detail", "[商品] 商品详情。", "GET", "/api/product/detail/<product_id>",
             _obj({"product_id": {"type": "string"}}, ["product_id"]),
             read_only=True, implemented=False),
    ToolSpec("product.create", "[商品] 新建 / 发布商品。", "POST", "/api/product/create",
             _obj({"payload": {"type": "object"}}, ["payload"]),
             read_only=False, destructive=True, requires_confirm=True, implemented=False),
    ToolSpec("product.update_price", "[商品] 修改价格。", "POST", "/api/product/update-price",
             _obj({"product_id": {"type": "string"}, "price": {"type": "number"}}, ["product_id", "price"]),
             read_only=False, destructive=True, requires_confirm=True, implemented=False),
    ToolSpec("product.update_stock", "[商品] 修改库存。", "POST", "/api/product/update-stock",
             _obj({"product_id": {"type": "string"}, "stock": {"type": "integer"}}, ["product_id", "stock"]),
             read_only=False, destructive=True, requires_confirm=True, implemented=False),
]

# 只读动作名特征（用于推断骨架接口是否只读）
_READ_HINTS = (
    "list", "detail", "overview", "report", "info", "score", "profile", "balance",
    "bills", "settlement", "account", "campaigns", "activities", "permissions",
    "sub_accounts", "keywords", "sources", "analysis", "withdraw", "notice",
)


def _looks_read_only(name: str, method: str) -> bool:
    if method.upper() == "GET":
        return True
    return any(hint in name for hint in _READ_HINTS)


def _build_skeleton_tools() -> List[ToolSpec]:
    tools: List[ToolSpec] = []
    for domain, cfg in SKELETON_DOMAINS.items():
        for ep in cfg["endpoints"]:
            props, required = {}, []
            for p in ep.params:
                pname = p.get("name")
                if not pname or p.get("in") == "path":
                    if pname and p.get("in") == "path":
                        props[pname] = {"type": "string", "description": p.get("desc", "路径参数")}
                        if p.get("required"):
                            required.append(pname)
                    continue
                props[pname] = {"type": "string", "description": p.get("desc", "")}
                if p.get("required"):
                    required.append(pname)
            read_only = _looks_read_only(ep.name, ep.method)
            tools.append(ToolSpec(
                f"{domain}.{ep.name}",
                f"[{cfg['title']}] {ep.summary}",
                ep.method, cfg["prefix"] + ep.path,
                _obj(props, required),
                read_only=read_only,
                destructive=not read_only,
                requires_confirm=not read_only,
                implemented=False,
            ))
    return tools


ORDER_TOOLS: List[ToolSpec] = [
    ToolSpec(
        "order.list",
        "查询订单列表（订单号/商品/金额/状态，已隐去买家隐私）。只读。",
        "POST", "/api/order/list",
        _obj({
            "status": {"type": "string", "description": "按状态筛选，如 待发货/已发货，可空"},
            "limit": {"type": "integer", "default": 20},
        }),
        read_only=True, destructive=False,
    ),
    ToolSpec(
        "order.ship",
        "对指定订单发货。写操作：默认 dry_run 仅定位发货入口；真实发货需物流编排，confirm 当前返回 NOT_IMPLEMENTED。",
        "POST", "/api/order/ship",
        _obj({
            "order_id": {"type": "string"},
            "dry_run": {"type": "boolean", "default": True},
            "confirm": {"type": "boolean", "default": False},
        }, ["order_id"]),
        read_only=False, destructive=True, requires_confirm=True,
    ),
    ToolSpec("order.detail", "[订单] 订单详情（含收货信息，单笔查询）。", "GET", "/api/order/detail/<order_id>",
             _obj({"order_id": {"type": "string"}}, ["order_id"]),
             read_only=True, implemented=False),
    ToolSpec("order.batch_ship", "[订单] 批量发货。", "POST", "/api/order/batch-ship",
             _obj({"shipments": {"type": "array"}}, ["shipments"]),
             read_only=False, destructive=True, requires_confirm=True, implemented=False),
    ToolSpec("order.remark", "[订单] 订单备注。", "POST", "/api/order/remark",
             _obj({"order_id": {"type": "string"}, "remark": {"type": "string"}}, ["order_id", "remark"]),
             read_only=False, destructive=True, requires_confirm=True, implemented=False),
]

AFTERSALE_TOOLS: List[ToolSpec] = [
    ToolSpec(
        "aftersale.list",
        "查询售后单列表（订单号/商品/退款金额/售后状态，已隐去买家隐私）。只读。",
        "POST", "/api/aftersale/list",
        _obj({
            "status": {"type": "string", "description": "按售后状态筛选，可空"},
            "limit": {"type": "integer", "default": 20},
        }),
        read_only=True, destructive=False,
    ),
    ToolSpec(
        "aftersale.agree_refund",
        "同意退款。写操作（涉及真实资金）：默认 dry_run 仅定位；confirm 当前返回 NOT_IMPLEMENTED。",
        "POST", "/api/aftersale/agree-refund",
        _obj({
            "order_id": {"type": "string"},
            "dry_run": {"type": "boolean", "default": True},
            "confirm": {"type": "boolean", "default": False},
        }, ["order_id"]),
        read_only=False, destructive=True, requires_confirm=True,
    ),
    ToolSpec(
        "aftersale.reject_refund",
        "拒绝退款。写操作（涉及真实资金）：默认 dry_run 仅定位；confirm 当前返回 NOT_IMPLEMENTED。",
        "POST", "/api/aftersale/reject-refund",
        _obj({
            "order_id": {"type": "string"},
            "dry_run": {"type": "boolean", "default": True},
            "confirm": {"type": "boolean", "default": False},
        }, ["order_id"]),
        read_only=False, destructive=True, requires_confirm=True,
    ),
    ToolSpec("aftersale.detail", "[售后] 售后详情。", "GET", "/api/aftersale/detail/<aftersale_id>",
             _obj({"aftersale_id": {"type": "string"}}, ["aftersale_id"]),
             read_only=True, implemented=False),
    ToolSpec("aftersale.agree_return", "[售后] 同意退货退款。", "POST", "/api/aftersale/agree-return",
             _obj({"order_id": {"type": "string"}}, ["order_id"]),
             read_only=False, destructive=True, requires_confirm=True, implemented=False),
]

MARKETING_TOOLS: List[ToolSpec] = [
    ToolSpec(
        "marketing.activities",
        "查询营销活动 / 优惠列表（类型/名称/活动ID/有效期/效果/状态，含优惠券、新人礼金、限时折扣等）。只读。",
        "POST", "/api/marketing/activities",
        _obj({
            "status": {"type": "string", "description": "按状态筛选，如 进行中/已失效，可空"},
            "activity_type": {"type": "string", "description": "按类型筛选，如 优惠券/新人礼金/单品直降，可空"},
            "keyword": {"type": "string", "description": "按名称或活动ID过滤，可空"},
            "limit": {"type": "integer", "default": 20},
        }),
        read_only=True, destructive=False,
    ),
    ToolSpec("marketing.coupon_create", "[营销] 创建优惠券。", "POST", "/api/marketing/coupon/create",
             _obj({"name": {"type": "string"}, "discount": {"type": "number"},
                   "total": {"type": "integer"}, "threshold": {"type": "number"}},
                  ["name", "discount", "total"]),
             read_only=False, destructive=True, requires_confirm=True, implemented=False),
    ToolSpec("marketing.discount_create", "[营销] 创建限时折扣。", "POST", "/api/marketing/discount/create",
             _obj({"product_id": {"type": "string"}, "discount": {"type": "number"}},
                  ["product_id", "discount"]),
             read_only=False, destructive=True, requires_confirm=True, implemented=False),
    ToolSpec("marketing.activity_join", "[营销] 报名平台营销活动。", "POST", "/api/marketing/activity/join",
             _obj({}), read_only=False, destructive=True, requires_confirm=True, implemented=False),
]

COMPASS_TOOLS: List[ToolSpec] = [
    ToolSpec(
        "compass.overview",
        "查询电商罗盘核心经营数据（成交金额/支付/结算/订单/曝光/点击/客单价/退款/转化率等指标卡，含昨日值与同行基准）。只读。",
        "POST", "/api/compass/overview",
        _obj({
            "keyword": {"type": "string", "description": "按指标名过滤，如 成交/退款/曝光，可空"},
            "limit": {"type": "integer", "description": "返回指标数量上限", "default": 50},
        }),
        read_only=True, destructive=False,
    ),
    ToolSpec("compass.product_analysis", "[电商罗盘] 商品分析。", "POST", "/api/compass/product-analysis",
             _obj({}), read_only=True, implemented=False),
    ToolSpec("compass.traffic_analysis", "[电商罗盘] 流量分析。", "POST", "/api/compass/traffic-analysis",
             _obj({}), read_only=True, implemented=False),
    ToolSpec("compass.live_analysis", "[电商罗盘] 直播分析。", "POST", "/api/compass/live-analysis",
             _obj({}), read_only=True, implemented=False),
]

TOOLS: List[ToolSpec] = (
    REAL_TOOLS + ORDER_TOOLS + AFTERSALE_TOOLS + COMPASS_TOOLS + MARKETING_TOOLS
    + PRODUCT_SKELETON_TOOLS + _build_skeleton_tools()
)
TOOL_BY_NAME = {t.name: t for t in TOOLS}


def list_tools_mcp() -> List[dict]:
    return [t.to_mcp() for t in TOOLS]

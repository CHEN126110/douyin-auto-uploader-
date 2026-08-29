# -*- coding: utf-8 -*-
"""订单域：订单查询（脱敏）+ 发货定位（dry_run）。

订单列表 /ffa/morder/order/list 为表格，每个订单跨两行：
  订单号行（td=2，td1="订单编号 xxx"）+ 明细行（td>=8：td1=商品、td2=单价x数量、td4=状态、td5=实付、td7=操作）。

隐私保护：list 默认不返回收货人 / 电话 / 地址等买家隐私；如需收货信息走 detail（单笔、用户明确查询）。
发货安全：ship 默认 dry_run 仅定位发货入口；真实发货涉及物流方式 / 运单号抽屉编排且不可逆，
当前不做未经确认的自动提交，confirm 模式暂返回 NOT_IMPLEMENTED，留待专门联调谨慎实现。
"""
from __future__ import annotations

from flask import Blueprint

from ..core import BrowserContext, BusinessApiError, ErrorCode
from .base import (
    SkeletonEndpoint,
    as_int,
    get_context,
    get_json,
    handle_errors,
    json_ok,
    register_skeleton,
    require_params,
)

bp = Blueprint("order", __name__, url_prefix="/api/order")

URLS = {"list": "https://fxg.jinritemai.com/ffa/morder/order/list"}
SEL = {"row": "css:table tbody tr", "row_cell": "tag:td"}

ORDER_MARK = "订单编号"
COL_PRODUCT = 1
COL_PRICE_QTY = 2
COL_STATUS = 4
COL_PAID = 5
COL_ACTION = 7


class OrderService:
    def __init__(self, ctx: BrowserContext) -> None:
        self.ctx = ctx

    def _open_list(self) -> None:
        self.ctx.goto(URLS["list"])
        self.ctx.require_login()
        if not self.ctx.wait_visible(SEL["row"], timeout=12):
            raise BusinessApiError(
                ErrorCode.ELEMENT_NOT_FOUND,
                "未能加载订单列表表格。",
                hint="可能当前无订单、页面未加载完成，或登录态失效。",
                context={"url": URLS["list"]},
            )

    def list_orders(self, status: str = "", limit: int = 20) -> dict:
        self._open_list()
        rows = self.ctx.read_rows(SEL["row"], SEL["row_cell"], limit=max(1, limit) * 3 + 10)
        items = []
        current_id = None
        for cells in rows:
            n = len(cells)
            head = cells[1] if n > 1 else ""
            if ORDER_MARK in (head or ""):
                seg = (head or "").replace(ORDER_MARK, "").strip().split()
                current_id = seg[0] if seg else None
                continue
            if n > COL_ACTION and current_id:
                status_text = (cells[COL_STATUS] or "").replace("\n", " ").strip()
                item = {
                    "order_id": current_id,
                    "product": (cells[COL_PRODUCT] or "").strip()[:40],
                    "price_qty": (cells[COL_PRICE_QTY] or "").strip(),
                    "paid": (cells[COL_PAID] or "").strip(),
                    "status": status_text.split()[0] if status_text else "",
                }
                if not status or status in status_text:
                    items.append(item)
                current_id = None
                if len(items) >= limit:
                    break
        return {"count": len(items), "items": items}

    def ship_order(self, order_id: str, dry_run: bool = True, confirm: bool = False) -> dict:
        self._open_list()
        row_xpath = f'xpath://tr[contains(., "{order_id}")]'
        if not self.ctx.exists(row_xpath, timeout=3):
            raise BusinessApiError(
                ErrorCode.ELEMENT_NOT_FOUND,
                f"未在首页订单列表找到订单 {order_id}。",
                hint="确认订单在第一页，或先按状态筛选 / 翻页（待扩展）。",
                context={"order_id": order_id},
            )
        ship_xpath = (
            f'xpath://tr[contains(., "{order_id}")]/following-sibling::tr[1]'
            f'//*[contains(normalize-space(text()), "发货")]'
        )
        located = self.ctx.exists(ship_xpath, timeout=2)

        if dry_run or not confirm:
            return {
                "order_id": order_id,
                "dry_run": True,
                "located": located,
                "note": "预演模式：仅定位发货入口，未提交。真实发货需物流抽屉编排，见 confirm 行为说明。",
            }

        raise BusinessApiError(
            ErrorCode.NOT_IMPLEMENTED,
            "真实发货涉及物流方式 / 运单号抽屉编排且不可逆，尚未实现自动提交。",
            hint="请在浏览器中手动完成发货，或在专门联调中谨慎实现该编排后再开放 confirm。",
            context={"order_id": order_id},
        )


@bp.post("/list")
@handle_errors
def order_list():
    data = get_json()
    status = str(data.get("status") or "")
    limit = as_int(data, "limit", 20)
    svc = OrderService(get_context())
    return json_ok("订单列表已读取（已隐去买家隐私）。", svc.list_orders(status=status, limit=limit))


@bp.post("/ship")
@handle_errors
def order_ship():
    data = get_json()
    require_params(data, ["order_id"])
    dry_run = bool(data.get("dry_run", True))
    confirm = bool(data.get("confirm", False))
    svc = OrderService(get_context())
    return json_ok("发货请求已处理。", svc.ship_order(str(data["order_id"]), dry_run, confirm))


# 订单域其余接口：契约骨架
register_skeleton(
    bp,
    [
        SkeletonEndpoint("GET", "/detail/<order_id>", "detail", "订单详情（含收货信息，单笔查询）",
                         [{"name": "order_id", "in": "path", "required": True}]),
        SkeletonEndpoint("POST", "/batch-ship", "batch_ship", "批量发货",
                         [{"name": "shipments", "required": True, "desc": "发货明细数组"}]),
        SkeletonEndpoint("POST", "/remark", "remark", "订单备注",
                         [{"name": "order_id", "required": True}, {"name": "remark", "required": True}]),
    ],
    "order",
)

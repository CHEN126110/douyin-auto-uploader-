# -*- coding: utf-8 -*-
"""售后域：售后单查询（脱敏）+ 退款决定定位（dry_run）。

售后列表为表格，每个售后单跨两行：订单号行 + 明细行
  （td1=商品、td2=应付、td3=售后退款金额、td4=售后状态、td5=介入状态、td7=操作）。

资金安全：同意 / 拒绝退款涉及真实退款给买家，极敏感。decide_refund 默认 dry_run 仅定位；
confirm 暂返回 NOT_IMPLEMENTED，绝不做未经严格确认的自动退款。
隐私：list 不返回买家隐私字段。
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

bp = Blueprint("aftersale", __name__, url_prefix="/api/aftersale")

URLS = {"list": "https://fxg.jinritemai.com/ffa/merchant-aftersale-workbench/aftersale/list"}
SEL = {"row": "css:table tbody tr", "row_cell": "tag:td"}

ORDER_MARK = "订单编号"
COL_PRODUCT = 1
COL_PAY = 2
COL_REFUND = 3
COL_STATUS = 4
COL_INTERVENE = 5
COL_ACTION = 7


class AftersaleService:
    def __init__(self, ctx: BrowserContext) -> None:
        self.ctx = ctx

    def _open_list(self) -> None:
        self.ctx.goto(URLS["list"])
        self.ctx.require_login()
        if not self.ctx.wait_visible(SEL["row"], timeout=12):
            raise BusinessApiError(
                ErrorCode.ELEMENT_NOT_FOUND,
                "未能加载售后列表表格。",
                hint="可能当前无售后单、页面未加载完成，或登录态失效。",
                context={"url": URLS["list"]},
            )

    def list_aftersales(self, status: str = "", limit: int = 20) -> dict:
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
                    "refund": (cells[COL_REFUND] or "").replace("\n", " ").strip()[:30],
                    "aftersale_status": status_text.split()[0] if status_text else "",
                    "intervene": (cells[COL_INTERVENE] or "").strip()[:10],
                }
                if not status or status in status_text:
                    items.append(item)
                current_id = None
                if len(items) >= limit:
                    break
        return {"count": len(items), "items": items}

    def decide_refund(self, order_id: str, agree: bool, dry_run: bool = True, confirm: bool = False) -> dict:
        action = "同意退款" if agree else "拒绝"
        self._open_list()
        row_xpath = f'xpath://tr[contains(., "{order_id}")]'
        if not self.ctx.exists(row_xpath, timeout=3):
            raise BusinessApiError(
                ErrorCode.ELEMENT_NOT_FOUND,
                f"未在首页售后列表找到订单 {order_id} 的售后单。",
                hint="确认在第一页，或先按状态筛选 / 翻页（待扩展）。",
                context={"order_id": order_id},
            )
        act_xpath = (
            f'xpath://tr[contains(., "{order_id}")]/following-sibling::tr[1]'
            f'//*[contains(normalize-space(text()), "{action}")]'
        )
        located = self.ctx.exists(act_xpath, timeout=2)

        if dry_run or not confirm:
            return {
                "order_id": order_id,
                "action": action,
                "dry_run": True,
                "located": located,
                "note": "预演模式：仅定位，未提交。退款涉及真实资金，需严格确认后才实现真实提交。",
            }

        raise BusinessApiError(
            ErrorCode.NOT_IMPLEMENTED,
            "同意 / 拒绝退款涉及真实资金且不可逆，尚未实现自动提交。",
            hint="请在浏览器中手动处理，或在专门联调中谨慎实现后再开放 confirm。",
            context={"order_id": order_id},
        )


@bp.post("/list")
@handle_errors
def aftersale_list():
    data = get_json()
    status = str(data.get("status") or "")
    limit = as_int(data, "limit", 20)
    svc = AftersaleService(get_context())
    return json_ok("售后列表已读取（已隐去买家隐私）。", svc.list_aftersales(status=status, limit=limit))


@bp.post("/agree-refund")
@handle_errors
def aftersale_agree_refund():
    data = get_json()
    require_params(data, ["order_id"])
    dry_run = bool(data.get("dry_run", True))
    confirm = bool(data.get("confirm", False))
    svc = AftersaleService(get_context())
    return json_ok("同意退款请求已处理。", svc.decide_refund(str(data["order_id"]), True, dry_run, confirm))


@bp.post("/reject-refund")
@handle_errors
def aftersale_reject_refund():
    data = get_json()
    require_params(data, ["order_id"])
    dry_run = bool(data.get("dry_run", True))
    confirm = bool(data.get("confirm", False))
    svc = AftersaleService(get_context())
    return json_ok("拒绝退款请求已处理。", svc.decide_refund(str(data["order_id"]), False, dry_run, confirm))


# 售后域其余接口：契约骨架
register_skeleton(
    bp,
    [
        SkeletonEndpoint("GET", "/detail/<aftersale_id>", "detail", "售后详情",
                         [{"name": "aftersale_id", "in": "path", "required": True}]),
        SkeletonEndpoint("POST", "/agree-return", "agree_return", "同意退货退款",
                         [{"name": "order_id", "required": True}]),
    ],
    "aftersale",
)

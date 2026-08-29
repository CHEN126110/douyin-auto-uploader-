# -*- coding: utf-8 -*-
"""营销活动域：营销活动 / 优惠列表（只读）+ 创建类写操作骨架。

优惠查询页为单行表格，每行 6 个 td：
  td0=活动类型、td1="名称 创建日期 时间 ID:xxx [范围]"、td2=有效期、td3=效果数据、
  td4=状态（进行中/已失效）、td5=操作按钮。

合规：list_activities 只读，仅查看用户自己店铺的营销活动。
创建优惠券 / 折扣、报名平台活动等会真实改动店铺营销与价格，列为写操作骨架，
待严格的 dry_run / confirm 编排后再开放。
"""
from __future__ import annotations

import re
from typing import List, Optional

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
)

bp = Blueprint("marketing", __name__, url_prefix="/api/marketing")

URLS = {"activities": "https://fxg.jinritemai.com/ffa/marketing/discount-query"}
SEL = {"row": "css:table tbody tr", "row_cell": "tag:td"}

COL_TYPE = 0
COL_INFO = 1
COL_PERIOD = 2
COL_EFFECT = 3
COL_STATUS = 4

_ID_RE = re.compile(r"ID[:：]\s*(\d+)")
_DATE_RE = re.compile(r"\b(\d{8})\b")  # 创建日期 YYYYMMDD


def _parse_row(cells: List[str]) -> Optional[dict]:
    """把优惠查询表格一行解析为营销活动条目。无法识别（无 ID 且无名称）返回 None。"""
    if len(cells) <= COL_STATUS:
        return None
    activity_type = (cells[COL_TYPE] or "").strip()
    info = " ".join((cells[COL_INFO] or "").split())
    m_id = _ID_RE.search(info)
    activity_id = m_id.group(1) if m_id else ""
    m_date = _DATE_RE.search(info)
    if m_date:
        name = info[: m_date.start()].strip()
    elif m_id:
        name = info[: m_id.start()].strip()
    else:
        name = info
    if not activity_id and not name:
        return None
    effect = " ".join((cells[COL_EFFECT] or "").split()).split("查看数据")[0].strip()
    return {
        "activity_type": activity_type,
        "name": name[:40],
        "activity_id": activity_id,
        "period": " ".join((cells[COL_PERIOD] or "").split()),
        "status": (cells[COL_STATUS] or "").strip(),
        "effect": effect[:60],
    }


class MarketingService:
    def __init__(self, ctx: BrowserContext) -> None:
        self.ctx = ctx

    def _open_list(self) -> None:
        self.ctx.goto(URLS["activities"])
        self.ctx.require_login()
        if not self.ctx.wait_visible(SEL["row"], timeout=12):
            raise BusinessApiError(
                ErrorCode.ELEMENT_NOT_FOUND,
                "未能加载营销活动（优惠查询）表格。",
                hint="可能当前无营销活动、页面未加载完成，或登录态失效。",
                context={"url": URLS["activities"]},
            )

    def list_activities(
        self, status: str = "", activity_type: str = "", keyword: str = "", limit: int = 20
    ) -> dict:
        self._open_list()
        rows = self.ctx.read_rows(SEL["row"], SEL["row_cell"], limit=max(1, limit) + 10)
        items = []
        for cells in rows:
            item = _parse_row(cells)
            if not item:
                continue
            if status and status not in item["status"]:
                continue
            if activity_type and activity_type not in item["activity_type"]:
                continue
            if keyword and keyword not in item["name"] and keyword != item["activity_id"]:
                continue
            items.append(item)
            if len(items) >= limit:
                break
        return {"count": len(items), "items": items}


@bp.post("/activities")
@handle_errors
def marketing_activities():
    data = get_json()
    status = str(data.get("status") or "")
    activity_type = str(data.get("activity_type") or data.get("type") or "")
    keyword = str(data.get("keyword") or "")
    limit = as_int(data, "limit", 20)
    svc = MarketingService(get_context())
    return json_ok(
        "营销活动列表已读取。",
        svc.list_activities(status=status, activity_type=activity_type, keyword=keyword, limit=limit),
    )


# 创建类写操作（改动店铺营销 / 价格）：契约骨架，待严格 dry_run/confirm 编排后开放
register_skeleton(
    bp,
    [
        SkeletonEndpoint("POST", "/coupon/create", "coupon_create", "创建优惠券",
                         [{"name": "name", "required": True}, {"name": "discount", "required": True},
                          {"name": "total", "required": True}, {"name": "threshold", "desc": "使用门槛"}]),
        SkeletonEndpoint("POST", "/discount/create", "discount_create", "创建限时折扣",
                         [{"name": "product_id", "required": True}, {"name": "discount", "required": True}]),
        SkeletonEndpoint("POST", "/activity/join", "activity_join", "报名平台营销活动"),
    ],
    "marketing",
)

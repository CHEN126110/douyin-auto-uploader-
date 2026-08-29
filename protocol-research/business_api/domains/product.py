# -*- coding: utf-8 -*-
"""商品域：基于真实表格结构的实现（已联调校准）。

商品列表页 /ffa/g/list 为表格布局，每行 8 个 td：
  td1=标题+ID、td2=价格、td3=销量、td6=时间+状态、td7=操作（编辑/下架/...）。
操作元素为行内可点击文本（编辑/上架/下架）。

写操作安全：上下架默认 dry_run（仅预演定位，不真实提交），
需显式 dry_run=False 且 confirm=True 才真实执行，避免误改真实店铺数据。
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

bp = Blueprint("product", __name__, url_prefix="/api/product")

URLS = {
    "list": "https://fxg.jinritemai.com/ffa/g/list",
    "create": "https://fxg.jinritemai.com/ffa/g/create",
}

SEL = {
    "login_flag": "css:[class*=shopName], css:[class*=header-shop], css:[class*=userInfo]",
    "row": "css:table tbody tr",
    "row_cell": "tag:td",
    "success_toast": "text:操作成功",
    "confirm_btn": "text:确定",
}

ID_MARKER = "ID:"
# 表格列索引（已按真实页面校准）
COL_TITLE_ID = 1
COL_PRICE = 2
COL_SALES = 3
COL_STATUS = 6
COL_ACTION = 7


def _parse_row(cells: list):
    """把一行单元格文本解析为结构化商品信息；非数据行返回 None。"""
    if len(cells) <= COL_STATUS:
        return None
    title_id = (cells[COL_TITLE_ID] or "").strip()
    if ID_MARKER not in title_id:
        return None
    title, _, id_part = title_id.partition(ID_MARKER)
    product_id = id_part.strip().split()[0] if id_part.strip() else ""
    status_cell = (cells[COL_STATUS] or "").replace("\n", " ").strip()
    status = ""
    for part in reversed(status_cell.split()):
        if part:
            status = part
            break
    return {
        "product_id": product_id,
        "title": title.strip(),
        "price": (cells[COL_PRICE] or "").strip(),
        "sales": (cells[COL_SALES] or "").strip(),
        "status": status,
    }


class ProductService:
    def __init__(self, ctx: BrowserContext) -> None:
        self.ctx = ctx
        self.ctx.login_check_locator = SEL["login_flag"]

    def _open_list(self) -> None:
        self.ctx.goto(URLS["list"])
        self.ctx.require_login()
        if not self.ctx.wait_visible(SEL["row"], timeout=12):
            raise BusinessApiError(
                ErrorCode.ELEMENT_NOT_FOUND,
                "未能加载到商品列表表格。",
                hint="可能页面未加载完成、当前无商品，或登录态失效。",
                context={"url": URLS["list"], "locator": SEL["row"]},
            )

    def list_products(self, keyword: str = "", limit: int = 20) -> dict:
        self._open_list()
        rows = self.ctx.read_rows(SEL["row"], SEL["row_cell"], limit=max(1, limit) + 5)
        items = []
        for cells in rows:
            info = _parse_row(cells)
            if not info:
                continue
            if keyword and keyword not in info["title"] and keyword != info["product_id"]:
                continue
            items.append(info)
            if len(items) >= limit:
                break
        return {"count": len(items), "keyword": keyword, "items": items}

    def set_shelf_state(
        self, product_id: str, on_shelf: bool, dry_run: bool = True, confirm: bool = False
    ) -> dict:
        action = "上架" if on_shelf else "下架"
        self._open_list()

        row_xpath = f'xpath://tr[contains(., "{ID_MARKER}{product_id}")]'
        if not self.ctx.exists(row_xpath, timeout=3):
            raise BusinessApiError(
                ErrorCode.ELEMENT_NOT_FOUND,
                f"未在列表首页找到商品 ID={product_id}。",
                hint="确认该商品在第一页；若在后续页，需先翻页 / 搜索（待扩展）。",
                context={"product_id": product_id},
            )
        action_xpath = f'{row_xpath}//*[normalize-space(text())="{action}"]'
        located = self.ctx.exists(action_xpath, timeout=2)

        # 默认预演：只验证能否定位到操作入口，绝不真实提交
        if dry_run or not confirm:
            return {
                "product_id": product_id,
                "action": action,
                "dry_run": True,
                "located": located,
                "note": "预演模式：未真实提交。需 dry_run=false 且 confirm=true 才会真实执行。",
            }

        if not located:
            raise BusinessApiError(
                ErrorCode.ELEMENT_NOT_FOUND,
                f"未找到该商品的「{action}」操作入口。",
                hint=f"商品可能已处于{action}状态，或入口在「更多」菜单内（待扩展）。",
                context={"product_id": product_id, "locator": action_xpath},
            )
        self.ctx.click(action_xpath)
        if self.ctx.exists(SEL["confirm_btn"], timeout=1.5):
            self.ctx.click(SEL["confirm_btn"])
        if not self.ctx.wait_visible(SEL["success_toast"], timeout=8):
            raise BusinessApiError(
                ErrorCode.UPSTREAM_ERROR,
                f"{action}未确认成功（未捕获成功提示）。",
                hint="请在浏览器中确认实际结果；提示文案可能不同，需校准。",
                context={"product_id": product_id},
            )
        return {"product_id": product_id, "action": action, "dry_run": False, "result": "ok"}


@bp.post("/list")
@handle_errors
def product_list():
    data = get_json()
    keyword = str(data.get("keyword") or "")
    limit = as_int(data, "limit", 20)
    svc = ProductService(get_context())
    return json_ok("商品列表已读取。", svc.list_products(keyword=keyword, limit=limit))


@bp.post("/off-shelf")
@handle_errors
def product_off_shelf():
    data = get_json()
    require_params(data, ["product_id"])
    dry_run = bool(data.get("dry_run", True))
    confirm = bool(data.get("confirm", False))
    svc = ProductService(get_context())
    return json_ok("下架请求已处理。", svc.set_shelf_state(str(data["product_id"]), False, dry_run, confirm))


@bp.post("/on-shelf")
@handle_errors
def product_on_shelf():
    data = get_json()
    require_params(data, ["product_id"])
    dry_run = bool(data.get("dry_run", True))
    confirm = bool(data.get("confirm", False))
    svc = ProductService(get_context())
    return json_ok("上架请求已处理。", svc.set_shelf_state(str(data["product_id"]), True, dry_run, confirm))


# 商品域其余接口：契约骨架，待联调填充
register_skeleton(
    bp,
    [
        SkeletonEndpoint("GET", "/detail/<product_id>", "detail", "商品详情",
                         [{"name": "product_id", "in": "path", "required": True}]),
        SkeletonEndpoint("POST", "/create", "create", "新建 / 发布商品",
                         [{"name": "payload", "required": True}]),
        SkeletonEndpoint("POST", "/update-price", "update_price", "修改商品价格",
                         [{"name": "product_id", "required": True}, {"name": "price", "required": True}]),
        SkeletonEndpoint("POST", "/update-stock", "update_stock", "修改商品库存",
                         [{"name": "product_id", "required": True}, {"name": "stock", "required": True}]),
    ],
    "product",
)

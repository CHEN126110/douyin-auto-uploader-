# -*- coding: utf-8 -*-
"""淘宝发布子项目的共享常量与证据分级定义。

设计原则（见上级 ``AGENTS.md``）：
本模块只放**不可变的事实与枚举**，不放任何带副作用的逻辑，也不放任何
需要联网或需要登录态才能得到的东西——所有平台事实都必须带证据等级，
没有证据的一律是 :data:`EVIDENCE_UNKNOWN`。
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# 证据分级
# ---------------------------------------------------------------------------
#: 有可复现的实验证据（脚本输出 / 抓包产物 / 官方文档），且已归档。
EVIDENCE_VERIFIED: Final = "verified"
#: 有间接证据或合理推断，尚未实证。可以写代码，但必须能被证伪。
EVIDENCE_CANDIDATE: Final = "candidate"
#: 查不到。**必须进 blockers**，不得用默认值填充。
EVIDENCE_UNKNOWN: Final = "unknown"
#: 已实证不成立。必须写明证伪方式，避免后人重试。
EVIDENCE_REJECTED: Final = "rejected"

EVIDENCE_LEVELS: Final = (
    EVIDENCE_VERIFIED,
    EVIDENCE_CANDIDATE,
    EVIDENCE_UNKNOWN,
    EVIDENCE_REJECTED,
)

#: 允许驱动「真实写入」分支的证据等级。``candidate`` 不足以放行写操作：
#: 猜出来的选择器 / 字段一旦写进平台就是脏数据。
WRITE_ELIGIBLE_EVIDENCE: Final = (EVIDENCE_VERIFIED,)


# ---------------------------------------------------------------------------
# 环境（与 protocol-research-taobao-20260908/AGENTS.md 保持一致）
# ---------------------------------------------------------------------------
#: 淘宝调试端口。抖店用 9333，**不要复用**。
TAOBAO_CDP_PORT: Final = 9334
TAOBAO_CDP_LIST_URL: Final = f"http://127.0.0.1:{TAOBAO_CDP_PORT}/json/list"
#: 调试 profile（需要独立扫码登录一次，登录态随 profile 持久化）。
TAOBAO_CDP_PROFILE_DIR: Final = ".runtime/chrome-taobao-cdp"

#: 发布工作台入口（以图发品 / AI 发品的类目选择页）。
PUBLISH_WORKBENCH_URL: Final = "https://item.upload.taobao.com/sell/ai/category.htm"
#: 选定类目后的**发布表单页**。已实证（2026-10-03 实拍）：
#: 从类目页选定叶子类目后会跳到
#: ``…/sell/v2/publish.htm?catId=<叶子类目ID>&fromAICategory=true&keyProps={}&fromAIPublish=true&newRouter=1``
#: 实测样本：``catId=201581801``（服装鞋包 → 女士内衣/男士内衣/家居服 → 短袜/打底袜/丝袜/美腿袜）。
#:
#: .. warning::
#:     ``catId`` 是**页面导航**参数，不是提交体的字段名。别把它当写接口字段用——
#:     契约门（``contracts/field_mapping.json``）要求写字段名 `verified` 才能进载荷。
PUBLISH_FORM_URL: Final = "https://item.upload.taobao.com/sell/v2/publish.htm"
#: 发布表单页的叶子类目查询参数名（已实证）。
PUBLISH_FORM_CATEGORY_PARAM: Final = "catId"
#: 发布相关页面必须命中的域名后缀，用于拒绝在错误页面上执行任何操作。
PUBLISH_ALLOWED_HOST_SUFFIXES: Final = (
    ".taobao.com",
    ".tmall.com",
    "taobao.com",
    "tmall.com",
)
#: 命中即视为掉登录态、必须中止的真值来源（只匹配 URL，不做文案猜测）。
LOGIN_URL_MARKERS: Final = (
    "login.taobao.com",
    "login.tmall.com",
    "login.m.taobao.com",
)
#: 命中即视为被风控拦截，必须中止并交由人工处理（不做自动绕过）。
RISK_CONTROL_URL_MARKERS: Final = (
    "sec.taobao.com",
    "punish",
    "bixi.alicdn.com",
    "captcha",
)


# ---------------------------------------------------------------------------
# 写操作与授权开关
# ---------------------------------------------------------------------------
#: 会上线平台状态、因而必须被授权门拦截的操作标识。
WRITE_UPLOAD_IMAGE: Final = "upload_image"
WRITE_SAVE_DRAFT: Final = "save_draft"
WRITE_SUBMIT_PUBLISH: Final = "submit_publish"
WRITE_UPDATE_ITEM: Final = "update_item"

WRITE_OPERATIONS: Final = (
    WRITE_UPLOAD_IMAGE,
    WRITE_SAVE_DRAFT,
    WRITE_SUBMIT_PUBLISH,
    WRITE_UPDATE_ITEM,
)

#: 第一阶段允许被授权的最小写集合。提交发布不在其中（见下面 SUBMIT 开关）。
WRITE_OPERATIONS_PRIMARY: Final = (
    WRITE_UPLOAD_IMAGE,
    WRITE_SAVE_DRAFT,
    WRITE_UPDATE_ITEM,
)

#: 授权写操作的白名单环境变量，逗号分隔，例如 ``upload_image,save_draft``。
#: 未设置或为空 → 零写入。
ENV_ALLOW_WRITE: Final = "TAOBAO_UPLOAD_ALLOW_WRITE"
#: 「提交发布」的第二把锁。必须显式为 ``1``，与 ENV_ALLOW_WRITE 相互独立，
#: 避免只改一个环境变量就把不可撤销的发布动作打开。
ENV_ALLOW_SUBMIT: Final = "TAOBAO_UPLOAD_ALLOW_SUBMIT"

#: 第二个锁的确认值。
SUBMIT_CONFIRM_VALUE: Final = "1"


# ---------------------------------------------------------------------------
# 流水线阶段
# ---------------------------------------------------------------------------
#: 阶段标识符。顺序即执行顺序，不可跳步（预检/会话阶段缺失时后续阶段无处依附）。
STAGE_SESSION: Final = "session"
STAGE_PRECHECK: Final = "precheck"
STAGE_UPLOAD_IMAGES: Final = "upload_images"
STAGE_SELECT_CATEGORY: Final = "select_category"
STAGE_FILL_BASE: Final = "fill_base"
STAGE_FILL_PROPS: Final = "fill_props"
#: 补齐**平台标了 `*` 的必填项**（与 `fill_props` 分工不同）。
#:
#: `fill_props` 填的是**采集到的**属性值（按 `MEASURED_ROW_LABELS` 定位；
#: 属性名对不上就 fail closed）；本阶段填的是**平台要求必填、而采集数据里没有**的那些，
#: 取值来自 `category_defaults` 的稳妥值/类目驱动规则，**商品事实一律不碰**。
#: 单独成阶段的好处：它是"平台要求"这条关注点，失败时能一眼看出是"缺必填"而不是"属性写错"。
STAGE_FILL_REQUIRED: Final = "fill_required_attrs"
#: 设置**上架时间**（立刻上架 / 定时上架 / 放入仓库）。
#:
#: 单独成阶段的原因：它决定商品**是否立刻对消费者可见**。默认走 `放入仓库`——
#: 流程跑完先进仓库，人复核后再上架，**不会误上架**。失败时也一眼能看出是哪一步。
STAGE_SET_LISTING: Final = "set_listing_time"
#: 保存草稿（把填好的商品存成后台草稿，**不上架**）。
#:
#: ⚠️ **默认不执行**：本阶段是写入，且会让平台上多出一条草稿记录。
#: 只有调用方显式要求（`ctx.scratch["save_draft_requested"]`）时才真的点按钮；
#: 否则**一个动作都不做**，如实报"未请求"。这样既守住"默认零写入"，
#: 又让"整条链走到保存草稿"这件事可被验证。
STAGE_SAVE_DRAFT: Final = "save_draft"
STAGE_FILL_SKUS: Final = "fill_skus"
STAGE_FILL_DETAIL: Final = "fill_detail"
STAGE_FILL_PRICE_STOCK: Final = "fill_price_stock"
STAGE_FILL_FREIGHT: Final = "fill_freight"
STAGE_READBACK: Final = "readback"
STAGE_SUBMIT: Final = "submit"

STAGE_ORDER: Final = (
    STAGE_SESSION,
    STAGE_PRECHECK,
    # ⚠️ **先选类目，再传图**（2026-10-03 实机纠正）。
    #
    # 这两个阶段工作在**不同的页面**上：
    #   * ``select_category`` 从**类目搜索页**（``sell/ai/category.htm``）出发，
    #     搜索 → 选中 → 导航到**填写页**（``publish.htm?catId=…``）；
    #   * ``upload_images`` 在**填写页**的主图区上工作。
    #
    # 所以顺序只能是「先选类目（顺带把页面带到填写页）→ 再传图」。
    # 原来的顺序是反的——那是按「图片先传到图片空间、与页面无关」的假设定的，
    # 而实测上传**必须在填写页里做**（点主图空位打开素材中心弹层）。
    # 实测踩过：顺序反了会报「当前不在类目搜索页（publish.htm?catId=…）」。
    STAGE_SELECT_CATEGORY,
    STAGE_UPLOAD_IMAGES,
    STAGE_FILL_BASE,
    STAGE_FILL_PROPS,
    # ⚠️ **必填项紧跟属性之后**：必填项里有一部分（适用季节/适用年龄/适用性别/风格…）
    # 就属于类目属性区，`fill_props` 写完采集属性后立刻补齐平台要求，语义上连在一起；
    # 而且它必须在 `fill_skus` 之前——SKU 抽屉会遮住属性区，之后再填要反复开关抽屉。
    STAGE_FILL_REQUIRED,
    STAGE_FILL_SKUS,
    STAGE_FILL_DETAIL,
    # ⚠️ **物流必须在价格库存之前**（2026-10-03 实机纠正）。
    #
    # 实测：**选运费模板会触发一次重渲染，把「一口价」与「总库存」重置掉**
    # （标题不受影响，SKU 行数也不变）。对照实验：
    #
    #     写入后：          一口价='16.80'  总库存='111'
    #     fill_freight 后：  一口价=''       总库存='0'
    #
    # 原来的顺序（价格库存 → 物流）会让 fill_price_stock **当场回读通过**、
    # 随后被 fill_freight 清掉，最后在 readback 阶段炸出来——
    # 表现为「填了价格库存，回读却是空的」。
    #
    # 所以把会被清掉的字段**排在最后写**。第一个假设是「fill_skus 的异步重渲染」，
    # 已用对照实验证伪（写入后盯 45 秒，值一直没变）。
    STAGE_FILL_FREIGHT,
    STAGE_FILL_PRICE_STOCK,
    # ⚠️ **上架时间排在最后写**：和 `fill_freight` 会重置价格库存同一个道理——
    # 它是"是否对消费者可见"的开关，放在最后写，避免被前面的重渲染带回默认值
    # （默认值是「立刻上架」，最危险的那个）。`readback` 紧跟其后核对。
    STAGE_SET_LISTING,
    STAGE_READBACK,
    # ⚠️ **保存草稿排在回读之后**：回读核对是"填对了"的判据，保存是"落地"的动作——
    # 没核对通过就不该往平台写草稿。
    STAGE_SAVE_DRAFT,
    STAGE_SUBMIT,
)

#: 阶段标识 → 中文显示名。前端进度条直接用它，不要在前端硬编码第二份。
STAGE_LABELS: Final = {
    'prepare_media': '整目录上传商品素材',
    STAGE_SESSION: "连接调试浏览器",
    STAGE_PRECHECK: "发布前置检查",
    STAGE_UPLOAD_IMAGES: "上传商品图片",
    STAGE_SELECT_CATEGORY: "选择商品类目",
    STAGE_FILL_BASE: "填写标题与基础信息",
    STAGE_FILL_PROPS: "填写类目属性",
    STAGE_FILL_REQUIRED: "补齐必填项",
    STAGE_FILL_SKUS: "填写销售规格(SKU)",
    STAGE_FILL_DETAIL: "填写商品详情",
    STAGE_FILL_PRICE_STOCK: "填写价格与库存",
    STAGE_SET_LISTING: "设置上架时间",
    STAGE_SAVE_DRAFT: "保存草稿",
    STAGE_FILL_FREIGHT: "填写物流与发货",
    STAGE_READBACK: "回读页面校验",
    STAGE_SUBMIT: "提交发布",
}

#: 每个阶段是否为写操作。非写阶段在 dry-run 下也要真实执行（只读安全）。
STAGE_WRITE_OPERATION: Final = {
    STAGE_SESSION: None,
    STAGE_PRECHECK: None,
    STAGE_UPLOAD_IMAGES: WRITE_UPLOAD_IMAGE,
    STAGE_SELECT_CATEGORY: None,
    STAGE_FILL_BASE: WRITE_SAVE_DRAFT,
    STAGE_FILL_PROPS: WRITE_SAVE_DRAFT,
    STAGE_FILL_REQUIRED: WRITE_SAVE_DRAFT,
    STAGE_FILL_SKUS: WRITE_SAVE_DRAFT,
    STAGE_FILL_DETAIL: WRITE_SAVE_DRAFT,
    STAGE_FILL_PRICE_STOCK: WRITE_SAVE_DRAFT,
    STAGE_SET_LISTING: WRITE_SAVE_DRAFT,
    STAGE_SAVE_DRAFT: WRITE_SAVE_DRAFT,
    STAGE_FILL_FREIGHT: WRITE_SAVE_DRAFT,
    STAGE_READBACK: None,
    STAGE_SUBMIT: WRITE_SUBMIT_PUBLISH,
}


#: **完整链路已在真实页面上跑通**的阶段。更新时要连同日期一起改。
#:
#: 「实现完了」与「真的跑通过」是两件事。`STAGE_HANDLERS` 只说明前者——
#: 一个阶段可以有完整实现、单元测试全绿，却从没在真实页面上从头走到尾。
#: 把这两者混起来，就会报出「能一键发布」而实际上某一步从没被验证过。
#:
#: 判定标准（严格）：**该阶段的完整成功路径在真实登录态下执行过，且结果被回读确认**。
#: 只跑过其中的零件（比如单独试过某个按钮）不算。
LIVE_VERIFIED_STAGES: Final = frozenset({
    # 会话探测：多次实机确认登录态与页面身份。
    STAGE_SESSION,
    # 静态预检：本地计算，随每次流水线运行执行。
    STAGE_PRECHECK,
    # 选类目 + 品牌：2026-10-03 实机跑通，导航到 publish.htm?catId=202187801。
    STAGE_SELECT_CATEGORY,
    # 上传主图：2026-10-03 实机跑通——素材中心 iframe → 本地上传 → 点「完成」落库 →
    # 逐张点卡片里的 label 选入主图位 → 回读确认 5/5。
    # 本轮扩展为主图/SKU/详情共用上传，完整路径仍需实机验证。
    # 基础信息：2026-10-03 实机写入并回读确认（标题、商家编码）。
    STAGE_FILL_BASE,
    # 类目属性：2026-10-03 实机写入并回读确认（品牌='无品牌/无注册商标'）。
    STAGE_FILL_PROPS,
    # 销售规格：2026-10-03 实机创建并回读确认（1 个属性、2 行 SKU，
    # 并正确取消了不需要的「颜色分类」）。
    # 自定义名称与逐规格图片绑定未完成实机验证，不继承旧标准模式标记。
    # 价格库存：2026-10-03 实机写入并回读确认（一口价 16.80、总库存 10）。
    STAGE_FILL_PRICE_STOCK,
    # 运费模板：2026-10-03 实机选择并回读确认（极兔快递 ↔ 系统模板-商家默认模板）。
    STAGE_FILL_FREIGHT,
    # 历史回读：2026-10-03 实机执行，4/4 字段匹配。
    # 本轮加入完整 SKU 图片/详情顺序及必填覆盖检查，扩展后的回读待实测。
})

#: **尚未**在真实页面上跑通完整链路的阶段。与 ``LIVE_VERIFIED_STAGES`` 互补，
#: 显式列出来是为了让就绪度能主动提醒——不列的话它会静默地"看起来都能用"。
LIVE_UNVERIFIED_STAGES: Final = tuple(
    stage for stage in STAGE_ORDER if stage not in LIVE_VERIFIED_STAGES
)


# ---------------------------------------------------------------------------
# 契约文件位置
# ---------------------------------------------------------------------------
CONTRACT_FIELD_MAPPING: Final = "contracts/field_mapping.json"
CONTRACT_PUBLISH_ITEM_SCHEMA: Final = "contracts/publish_item.schema.json"
CONTRACT_SELECTORS: Final = "contracts/selectors.json"
CONTRACT_RULES: Final = "contracts/rules.json"


#: 类目搜索页。`select_category` 从这里开始，选完导航到填写页。
CATEGORY_PAGE_URL: Final = "https://item.upload.taobao.com/sell/ai/category.htm"

#: 判断「当前是否已在类目搜索页」用的 URL 片段。
CATEGORY_PAGE_HINT: Final = "sell/ai/category.htm"

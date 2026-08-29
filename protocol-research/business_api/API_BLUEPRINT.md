# 抖店电商业务域 API 蓝图（DOM 自动化方案）

> 本蓝图覆盖 11 个大项业务域。底层通过 DrissionPage 接管用户本机**已登录的真实 Chrome**，
> 在真实页面上执行真人式 DOM 操作，对外暴露统一 HTTP 接口。

## 合规边界（务必遵守）

- 只接管用户自己、已登录的真实浏览器，操作用户自己的店铺数据。
- **不复现平台私有签名**（a_bogus / X-Bogus / msToken 等），不拼裸协议请求。
- **不绕过验证码与风控**：命中即暂停并交人工处理（返回 `CAPTCHA_REQUIRED`）。
- 通过 `HumanPacer` 控频，按真人节奏操作。

## 实现状态图例

- ✅ 已联调真实跑通（真实环境验证；写操作含 dry_run 保护）
- 🔲 契约骨架（API 可对接，返回 `NOT_IMPLEMENTED`，待联调真实页面后填充）

## 实现进度总览（截至当前）

**已联调真实跑通 ✅**

| 工具 | 类型 | 说明 |
|---|---|---|
| `product.list` | 读 | 商品列表（ID/标题/价格/销量/状态）|
| `product.on_shelf` / `off_shelf` | 写 | 上下架，默认 dry_run，需 confirm |
| `order.list` | 读 | 订单列表（已脱敏，无买家隐私）|
| `order.ship` | 写 | 发货入口定位 dry_run（真实发货编排待开发）|
| `aftersale.list` | 读 | 售后单列表（已脱敏）|
| `aftersale.agree_refund` / `reject_refund` | 写 | 退款定位 dry_run（资金敏感，confirm 暂不开放）|
| `compass.overview` | 读 | 电商罗盘核心经营数据（指标卡：今日值/昨日/同行对比）|

**待联调骨架 🔲**：流量运营、营销活动、付费推广、巨量千川、资金、店铺、用户。

**Agent 接入**：`GET /mcp/tools` 发现全部工具；`POST /mcp/call` 统一调用（写操作带 dry_run/confirm 保护）。

## 统一返回结构

```json
{ "ok": true, "code": "OK", "message": "...", "hint": null, "data": {} }
```

错误码（`code`）→ HTTP 状态：`INVALID_PARAM`=400、`LOGIN_REQUIRED`=401、`CAPTCHA_REQUIRED`=423、
`RATE_LIMITED`=429、`NOT_IMPLEMENTED`=501、`ELEMENT_NOT_FOUND`/`PAGE_STRUCTURE_CHANGED`/`UPSTREAM_ERROR`=502、
`BROWSER_NOT_READY`=503、`WAIT_TIMEOUT`=504、`ACTION_FAILED`/`UNKNOWN`=500。

---

## 1. 商品（product）`/api/product`

| 状态 | 方法 | 路径 | 说明 | 关键参数 |
|---|---|---|---|---|
| ✅ | POST | `/list` | 商品列表 | `keyword`, `limit` |
| ✅ | POST | `/on-shelf` | 上架 | `keyword`(必填) |
| ✅ | POST | `/off-shelf` | 下架 | `keyword`(必填) |
| 🔲 | GET | `/detail/<product_id>` | 商品详情 | `product_id`(路径) |
| 🔲 | POST | `/create` | 新建 / 发布商品 | `payload` |
| 🔲 | POST | `/update-price` | 修改价格 | `keyword`, `price` |
| 🔲 | POST | `/update-stock` | 修改库存 | `keyword`, `stock` |

## 2. 订单发货（order）`/api/order`

| 状态 | 方法 | 路径 | 说明 | 关键参数 |
|---|---|---|---|---|
| 🔲 | POST | `/list` | 订单列表 | `status`, `page`, `page_size` |
| 🔲 | GET | `/detail/<order_id>` | 订单详情 | `order_id`(路径) |
| 🔲 | POST | `/ship` | 单笔发货 | `order_id`, `company`, `tracking_no` |
| 🔲 | POST | `/batch-ship` | 批量发货 | `shipments` |
| 🔲 | POST | `/remark` | 订单备注 | `order_id`, `remark` |

## 3. 售后（aftersale）`/api/aftersale`

| 状态 | 方法 | 路径 | 说明 | 关键参数 |
|---|---|---|---|---|
| 🔲 | POST | `/list` | 售后单列表 | — |
| 🔲 | GET | `/detail/<aftersale_id>` | 售后详情 | `aftersale_id`(路径) |
| 🔲 | POST | `/agree-refund` | 同意退款 | `aftersale_id` |
| 🔲 | POST | `/reject-refund` | 拒绝退款 | `aftersale_id`, `reason` |
| 🔲 | POST | `/agree-return` | 同意退货退款 | `aftersale_id` |

## 4. 营销活动（marketing）`/api/marketing`

| 状态 | 方法 | 路径 | 说明 | 关键参数 |
|---|---|---|---|---|
| 🔲 | POST | `/activities` | 营销活动列表 | — |
| 🔲 | POST | `/coupon/create` | 创建优惠券 | `name`, `discount`, `total`, `threshold` |
| 🔲 | POST | `/discount/create` | 创建限时折扣 | `product_id`, `discount` |
| 🔲 | POST | `/activity/join` | 报名平台活动 | — |

## 5. 流量运营（traffic）`/api/traffic`

| 状态 | 方法 | 路径 | 说明 | 关键参数 |
|---|---|---|---|---|
| 🔲 | POST | `/overview` | 流量概览 | `date_range` |
| 🔲 | POST | `/keywords` | 搜索关键词数据 | — |
| 🔲 | POST | `/sources` | 流量来源分布 | — |

## 6. 付费推广（ad）`/api/ad`

| 状态 | 方法 | 路径 | 说明 | 关键参数 |
|---|---|---|---|---|
| 🔲 | POST | `/campaigns` | 推广计划列表 | — |
| 🔲 | POST | `/campaign/create` | 新建推广计划 | — |
| 🔲 | POST | `/campaign/budget` | 调整预算 | `campaign_id`, `budget` |
| 🔲 | POST | `/campaign/toggle` | 启停计划 | `campaign_id`, `enable` |

## 7. 巨量千川（qianchuan）`/api/qianchuan`

| 状态 | 方法 | 路径 | 说明 | 关键参数 |
|---|---|---|---|---|
| 🔲 | POST | `/account` | 账户信息与余额 | — |
| 🔲 | POST | `/campaigns` | 千川计划列表 | — |
| 🔲 | POST | `/report` | 数据报表 | `date_range`, `metrics` |
| 🔲 | POST | `/campaign/budget` | 调整计划预算 | `campaign_id`, `budget` |

## 8. 电商罗盘（compass）`/api/compass`

> 核心数据在独立子域 `compass.jinritemai.com/shop`。`/overview` 解析指标卡，每项返回
> `{label, value(今日), yesterday(昨日), benchmark(同行对比值), benchmark_type(同行基准/同行顶尖)}`，
> 并附 `by_label` 便捷映射。图表为 canvas 绘制，其内部明细无法经 DOM 提取。

| 状态 | 方法 | 路径 | 说明 | 关键参数 |
|---|---|---|---|---|
| ✅ | POST | `/overview` | 核心经营数据指标卡 | `keyword`(按指标名过滤), `limit` |
| 🔲 | POST | `/product-analysis` | 商品分析 | — |
| 🔲 | POST | `/traffic-analysis` | 流量分析 | — |
| 🔲 | POST | `/live-analysis` | 直播分析 | — |

## 9. 资金（fund）`/api/fund`

| 状态 | 方法 | 路径 | 说明 | 关键参数 |
|---|---|---|---|---|
| 🔲 | POST | `/balance` | 账户余额 | — |
| 🔲 | POST | `/bills` | 账单流水 | `date_range`, `page` |
| 🔲 | POST | `/settlement` | 结算记录 | — |
| 🔲 | POST | `/withdraw-records` | 提现记录 | — |

## 10. 店铺（shop）`/api/shop`

| 状态 | 方法 | 路径 | 说明 |
|---|---|---|---|
| 🔲 | POST | `/info` | 店铺基础信息 |
| 🔲 | POST | `/score` | 店铺体验分 / 口碑分 |
| 🔲 | POST | `/notice` | 商家公告查看 / 设置 |

## 11. 用户（user）`/api/user`

| 状态 | 方法 | 路径 | 说明 |
|---|---|---|---|
| 🔲 | POST | `/profile` | 当前登录账号信息 |
| 🔲 | POST | `/sub-accounts` | 子账号列表 |
| 🔲 | POST | `/permissions` | 权限信息 |

---

## 辅助端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 + 域列表 |
| GET | `/catalog` | 运行时接口清单（已实现 + 骨架） |

## 填充骨架接口的标准流程

1. 在真实登录环境打开对应页面，用 `/api/debug/browser/query`（app.py 已有）或浏览器开发者工具确认选择器。
2. 参考 `domains/product.py` 的 `ProductService` 模式，新建对应域的 Service 类，把 URL 与选择器集中到 `URLS` / `SEL`。
3. 用真实编排替换该接口的骨架路由（移出 `register_skeleton`，改为真实 view）。
4. 为新接口补单元测试（参考 `tests/test_product.py`，用 `FakeDriver` 脚本化页面行为）。
5. `python -m pytest business_api/tests` 全绿后再联调真实页面。

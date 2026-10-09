# taobao-publisher · 淘宝商品上传发布流程（研究 + 开发）

> 本目录是**独立子项目**，与抖店（fxg）发布体系完全隔离。
> 工作前必读本文件与 [`AGENTS.md`](AGENTS.md)。

2026-10-03 第一阶段资料整理见 [淘宝发布流程与字段清单](docs/09-淘宝发布流程与字段清单.md)。页面画面已归档，写字段和选择器仍未取证，本轮暂不接入桌面应用。

2026-10-03：应用已接入独立的 [淘宝资料准备与人工发布路线](docs/10-桌面淘宝资料发布路线.md)，可检查资料和生成本地资料包；自动发布路线仍未就绪。下表与就绪度命令描述的是自动发布流水线。

## 一句话结论（2026-10-02）

**淘宝官方发品 API 对普通淘宝集市卖家实质关闭**，只能走「网页发布工作台 + mtop 协议 / DOM」
路线。而这条路线上的**字段名与选择器，目前一条都还没有实证** —— 所以本子项目现在
**能跑的是只读部分**（会话探测、发布前置检查、载荷构建与契约门），
**不能真的发布**，而且这一点是被代码硬性拦住的，不是靠自觉。

```powershell
cd taobao-publisher
python -m taobao_publish readiness     # 看当前到底能不能发
```

输出会明确写出：`是否存在可用发布路线：否`。

## 现状速查

| 维度 | 状态 |
|---|---|
| 已实现阶段 | `session`（CDP 会话探测）、`precheck`（发布前置检查） |
| 未实现阶段 | `upload_images`、`select_category`、`fill_base`、`fill_props`、`fill_skus`、`fill_price_stock`、`fill_freight`、`readback`、`submit` |
| mtop 协议写路线 | **不可用**（0 个字段 `verified`） |
| DOM 写路线 | **不可用**（15 个写关键选择器全部未取证） |
| 离线测试 | 270 passed（`python -m pytest taobao-publisher/tests -q`） |
| 独立对抗性安全审查 | 已做一轮，15 项发现**全部修复**并固化为回归测试，见 [`docs/05-证据日志.md`](docs/05-证据日志.md) §E |
| 会写平台的能力 | **没有**。写操作默认全关，且有独立的第二把锁保护提交 |

## 目录导航

| 路径 | 内容 |
|---|---|
| [`AGENTS.md`](AGENTS.md) | 子项目红线、证据分级、环境与已实证的服务限制 |
| `taobao_publish/` | 可导入的 Python 包（不依赖 Peewee / Flask，可独立单测） |
| `contracts/` | **事实来源**：字段映射、选择器、平台硬约束、入参 schema |
| `docs/` | 研究结论、设计、证据日志、阻塞项、分阶段计划 |
| `scripts/` | 只读 CDP 探针（Node，复用 `mcp-server/cdp-client.js`） |
| `tests/` | 离线测试，不联网、不碰平台、不需要数据库 |
| `captures/` | **脱敏后**的取证产物 |
| `outputs/` | **脱敏后**的运行报告 |
| `tmp/` | 原始探针产物与测试 scratch（已 gitignore，**不会进仓库**） |

## 快速上手

### 1. 看当前就绪度（不碰平台）

```powershell
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
Set-Location taobao-publisher

python -m taobao_publish readiness          # 文本报告
python -m taobao_publish readiness --json   # JSON
python -m taobao_publish contracts          # 列出所有证据项与来源
```

### 2. 跑离线测试（不需要浏览器、不需要数据库）

```powershell
# 从仓库根执行
python -m pytest taobao-publisher/tests -q
```

### 3. 对一条本地记录做 dry-run（**不触碰平台**）

```powershell
python -m taobao_publish dry-run --record-id 1 --sku-price 9.9 --sku-stock 100
python -m taobao_publish dry-run --record-id 1 --sku-price 9.9 --sku-stock 100 --json
```

`--sku-price` 与 `--sku-stock` 必须成对提供：本地 `record` 表**没有库存字段**，
缺了就直接拒绝，不会默认填 0 或 999。

### 4. 只读取证（需要先启动淘宝调试浏览器并扫码登录）

```powershell
# 从**仓库根**执行
node protocol-research-taobao-20260908/scripts/start-taobao-cdp-chrome.mjs

# 另一个窗口：勘察发布工作台结构（只读，不点击/不输入/不提交）
node taobao-publisher/scripts/probe-publish-workbench.mjs

# 另一个窗口：被动观察请求（你自己手动操作，它只记录）
node taobao-publisher/scripts/capture-publish-requests.mjs --seconds 300

# 产物脱敏后才允许进 captures/
python -m taobao_publish sanitize taobao-publisher/tmp/xxx_raw.json taobao-publisher/captures/tb_xxx.json
```

## 为什么不能直接发

三条独立的理由，任一条成立就不能发：

1. **平台侧**：`taobao.item.add` 等发布编辑接口已于 2022-08-31 起逐步下线；
   替代接口 `alibaba.item.publish.submit` 的商家自研身份「必须**是**天猫商家」。
   详见 [`docs/01-平台入口与路线判断.md`](docs/01-平台入口与路线判断.md)。
2. **证据侧**：网页工作台的写字段名、类目属性解析方式、图片空间接口，一条都没取证。
   契约门（`contracts/field_mapping.json` 的 `write_gate`）规定只有 `verified` 的字段
   才能进真实写操作，当前 0 个字段达标。
3. **安全侧**：写操作默认全关（`TAOBAO_UPLOAD_ALLOW_WRITE` 未设即零写入），
   提交另有独立的第二把锁（`TAOBAO_UPLOAD_ALLOW_SUBMIT=1`）。
   详见 [`docs/04-安全门与授权红线.md`](docs/04-安全门与授权红线.md)。

## 与既有目录的关系

| 目录 | 关系 |
|---|---|
| `protocol-research-taobao-20260908/` | 淘宝发布环境的 CDP 引导脚本与**环境限制实证**。本子项目直接复用，不重复实证。 |
| `protocol-research-clean-20260505/` | **抖店**协议研究区。只借架构（阶段划分 / 错误映射 / 安全门形态），结论与字段**一律不搬用**。 |
| `tauri-app/python-sidecar/app.py` | 淘宝**采集（读）** 已落地处（`_extract_taobao_ice_data` 等）。本子项目不修改它。 |
| `src/whitebg/` | 白底图产出。淘宝主图第 5 张要求白底图，是潜在的上游依赖。 |

## 下一步该做什么

见 [`docs/07-分阶段实施计划.md`](docs/07-分阶段实施计划.md)。
最短路径是：**扫码登录 → 跑两个只读探针 → 把证据回填契约 → 解锁第一个写阶段**。

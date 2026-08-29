# Harness 与 skills 插件

> 本文由设计评审产出（2026-08-29），其中的结论**需要被实现验证**。
> 已被实证推翻或修正的部分见文末「实证修正」。

---

# 电商 Agent 的 Harness 与 skills 插件机制设计

> 定位一句话：**Harness 是"不许出错的那部分"，Agent 是"允许有判断的那部分"，两者之间用证据契约隔开。**
> 现有 `D:\抖店\lib` 的四个基础件（`data-contract` / `approval-gate` / `shop_registry` / `compass_snapshots`）已经是闸门的真源，Harness 不重写它们，只做**编排、状态化、强制执行**。

---

## 1. Harness 的职责边界

### 1.1 划分原则

一件事该交给代码还是模型，只看一条判据：

> **"这件事做错了，会不会不报错？"**
> 会不报错的（跨店污染、区间当点估计、平台结论当原始指标、未审批的写操作）→ **必须代码保证**。
> 做错了人一眼能看出来的（词该不该归到袜子类目、卖点文案好不好）→ **交给模型**。

`shop_registry.js` 的注释已经把这条判据写清楚了：「你以为在查 A 店，拿到的是 B 店的真实数据，每个数字都对，只是属于另一家店。」——这类错误必须由代码拦。

### 1.2 确定性 vs 判断（对照表）

| 事项 | 归属 | 依据 |
|---|---|---|
| DAG 拓扑、节点调度、续跑、幂等 | **Harness** | 不能靠模型记得自己跑到哪 |
| 工具调用出口唯一化（只能经 dispatcher） | **Harness** | 旁路一条就等于闸门不存在 |
| 店铺身份锁定与每次调用的一致性比对 | **Harness** | 失效不报错 |
| 作用域/可信度判定与证据准入 | **Harness** | `data-contract` 已是机读事实 |
| 区间 → 可比值的换算、精度传播 | **Harness** | `rangeToComparable`，模型算会取 lower 或 upper |
| 写操作审批凭据的签发与校验 | **Harness** | 模型不得自证已获批 |
| 证据落盘、evidence_id 分配、可重放校验 | **Harness** | 证据链不能靠自觉 |
| claim 中每个数字的溯源校验 | **Harness** | 这是"不编数字"的唯一技术保证 |
| 空数据三分类的处置分流 | **Harness** | `compass_unwrap` 已区分 platform_empty / chart_only / unparsed_shape |
| 从 200 个行业词里挑哪些值得深看 | **Agent** | 语义判断 |
| 一个词属不属于袜子的真实需求（vs 比价词/蹭词） | **Agent** | 需要常识 |
| 为"需求真实存在"构造反证 | **Agent** | 这是核心智力活 |
| 卖点提炼、标题措辞、素材方向 | **Agent** | 创作 |
| 几个候选机会之间的取舍与理由陈述 | **Agent** | 权衡 |
| 把证据组织成人能判断的呈现 | **Agent** | 表达 |
| **最终决定** | **人** | 硬约束 2 |

### 1.3 Harness 明确不管的

- **不管取数细节**：会话、反爬、cookie 刷新、重试——归 `compass_pool` / `fxg_pool` / `retry.js`。Harness 只看返回的 `_meta` 与 envelope。
- **不管发布 DOM 操作**：归 2.1 的 sidecar。Harness 只发指令、收 dry-run diff、管审批。
- **不做业务结论**：Harness 永远不说"这个品能卖"。它只说"证据 A/B/C 齐了，可信度分别是 X/Y/Z，缺 D"。
- **不做数据修复、补全、外推、默认值填充**。缺就是缺（硬约束 3、4）。
- **不管 UI 美学**，但管**确认卡必须包含哪些字段**（见第 6 节）。

---

## 2. DAG：把用户的原话落成节点

用户的概念是「了解市场 → 找到真实需求 + 竞争小 → 选品 → 素材 → 上架 → 运营」。落成 11 个节点，其中 4 个是回环入口。

```
N1 market.scan        行业词/榜单/热点扫描 → 机会候选池
N2 demand.verify      需求真伪验证（构造反证）
N3 competition.assess 竞争度评估（代理指标，必须标注为代理）
N4 opportunity.card   机会档位卡（不给综合分，见 2.3）      ◀ 确认点 CP-1
N5 sourcing           选品/找货（1688 等供给侧）
N6 economics          单品经济模型（成本/定价/利润阶梯）    ◀ 确认点 CP-2（备货花钱前）
N7 asset              素材设计
N8 listing.compose    上架资料组装（类目/属性/SKU/运费/无品牌）
N9 publish            发布（写操作）                        ◀ 确认点 CP-3（强制）
N10 ops.observe       运营观测（快照序列积累）
N11 ops.diagnose      诊断与归因

回环：N11 → N1（新机会） / N6（改价）◀ CP-4 / N7（换素材） / N9.delist（下架）◀ CP-4
```

### 2.1 节点契约的形状

每个节点是一份声明式定义（`agent/dag/nodes/*.yaml`），Harness 按它执行：

```yaml
id: market.scan
requires_scope: [market]            # 只有这些作用域的证据能进模型上下文
allows_advisory: true               # 允许平台结论进入，但只能落到 hypotheses 通道
evidence_freshness: { window: 7d }  # 快照库里 stat_key 在窗口内则复用，不重取
tools:
  - compass.search.industry_rank
  - compass.market.hotspot
  - compass.product.category_tree
produces:
  claims:  { schema: contracts/claim.schema.json, evidence_required: true }
  hypotheses: { schema: ..., must_flag: 待验证 }
coverage_required: true             # 必须声明用了多少证据、缺了什么
checkpoint: none
```

### 2.2 两条通道，物理隔开

Harness 给模型的上下文分两个互不相通的通道：

- **evidence 通道**：`_meta.canDriveDecision === true` 的数据。可以据此下结论。
- **hypotheses 通道**：`advisory: true` 的平台结论（`diagnosis`、`search_diagnosis`、`recommend_optimized_product`）。**进来时就被 `data-contract` 判为 SUSPECT**，模型引用它时 Harness 强制在输出上打 `unverified: true`，并要求配一条 `verification_plan`——"用哪个原始指标、哪个字段来验证这条平台结论"。验证没做，这条假设不许升级为 claim。

这直接实现硬约束 1：**平台推荐只能作为待验证假设**，而且是结构上做不到绕过，不是靠提示词请求模型。

### 2.3 Harness 内置的确定性计算（字段 / 阈值 / 数据不足怎么办）

以下全部由代码算，模型只能读结果，不能自己算。每条都标了实际字段。

**(1) 需求规模 D_word**
- 字段：`search_show_ucnt__lower` / `search_show_ucnt__upper` → `rangeToComparable()` 的 `mid`
- 实测（袜子）：750,000 ~ 1,000,000 → mid ≈ 866,025，spread = 1.33，`reliable = true`
- 数据不足：只有 `__ratio` 没有区间 → **D 标 `unavailable`**，不参与规模排序，机会卡该格显示"平台未下发规模值"。**不用 ratio 反推**（缺行业总盘）。

**(2) 成交规模 G_word**
- 字段：`pay_amt__lower` / `pay_amt__upper` → `mid`。实测 750,000,000 ~ 1,000,000,000 → mid ≈ 8.66 亿
- 数据不足：同 (1)。

**(3) 归一化变现效率 M —— 本设计的主指标**
- 公式：`M = pay_amt__ratio / search_show_ucnt__ratio`
- 实测（袜子）：0.2262 / 0.1639 = **1.380**
- **为什么用它**：两个 ratio 是**精确下发的小数，不受 `is_self=0` 的区间脱敏影响**。且代数上 `M = (该词变现效率) / (行业平均变现效率)`——分母是行业总盘，在比值里被消掉，所以**不需要知道行业总量也能算**，也不需要词榜全量。这是当前数据条件下少数几个能得到精确值的市场指标。
- 分档（**是标签，不是决策**）：`M ≥ 1.2` 记「变现优于大盘」；`0.8 < M < 1.2` 记「与大盘相当」；`M ≤ 0.8` 记「搜得多、买得少」。后者正是用户要找的"需求存在但未被满足"的候选信号——**但也可能是比价词/信息词**，所以必须交 N2 由 Agent 构造反证。
- 升级规则：单期只判 `provisional`。只有从 `compass_snapshots.series()` 取到 **≥3 期同口径快照且 M 的方向一致**，才升级为可驱动决策。
- 数据不足：任一 ratio 缺失 → M 标 `unavailable`，**不用区间中值代算**（会引入脱敏误差，且不同词误差方向不同）。

**(4) 口径一致性校验（硬校验，M 的前置条件）**
- 对同一响应里的每个词算隐含行业总盘：`T_i = mid(pay_amt__lower, pay_amt__upper) / pay_amt__ratio`
- 判据：`max(T) / min(T) ≤ 2` 才放行。（区间 spread 通常 ≤1.33，几何均值误差约 ±15%，2 倍阈值是宽松的）
- 不过 → **该批次所有 M 判 `suspect`，全部拒绝使用**，并在 run 事件里记下"ratio 分母口径不一致"，而不是静默降级。

**(5) 竞争基数 N_shop**
- 字段：`compass.market.shop_rank` 解包后的 `rows__total`（`compass_unwrap` 已从 `page_result.total` 提取）
- 数据不足：`total` 缺失 → **竞争度判 `UNKNOWN`**，N4 机会卡标红「竞争度未验证」，**该机会不得自动流入 N5**，必须人工在 CP-1 显式放行。

**(6) 头部集中度 CR_k（代理指标，必须标注为代理）**
- 公式：`CR_k = Σ(前 k 家的 pay_amt mid) / T`（T 取 (4) 的隐含总盘）
- 分档：`≥0.5` 高集中 / `0.25~0.5` 中 / `<0.25` 分散
- 只输出**档位**，不输出百分比数字——因为分子由区间中值累加，误差会累积。
- 降级条件：前 k 家中**任一家** `rangeToComparable().reliable === false`（spread > 4）→ CR 整体判 `unavailable`。
- 完全不可得时的替代路径：改用 `compass.market.index_range` 的档位边界，输出「进入中位档需要多少 pay_amt」。这是**位置量（SHOP_STATE）**，不受本店样本量约束。

**(7) 本店位置 P**
- 字段：`compass.market.index_range` 中带 `isCurrentShop` / `tag` 的档位
- **这是本店唯一一类始终可用的数据**。按 `data-contract` 的 SHOP_STATE 定义，"本店在哪一档"是事实而非概率，**店铺 19 个商品、曝光 2 次、支付 0 单的情况下依然成立**。
- 相对地，本店的 `pay_amt` / 转化率等 SHOP_METRIC 在 `sampleSize < 100` 时**一律被 `canDrivedecision` 拒绝**，Harness 不把它们送进模型上下文。这不是保守，这是不让噪音变成结论。

**(8) 单品经济模型（N6）**
- 来源不是罗盘：采购单价（1688 skill 或人工）、运费（**从店铺运费模板读，不写死**，硬约束 5）、平台扣点（人工确认的费率）、退货率
- **退货率无法从平台取到可信值**（本店样本不足，行业值平台不下发）→ 标为 **assumption 而非 evidence**，由人在 CP-2 显式填写并承担。确认卡上单独一栏：「以下数字是你自己假设的，不是查来的」。
- 与 2.1 `src/ops_engine.py` 的利润阶梯对接：Harness 传入成本与假设，ops_engine 出阶梯。ops_engine 是本地规则计算，与"不调外部 AI/官方 API"的既有约束一致。

**(9) 关于"综合机会分"——本设计主张不做**

理由与硬约束 4 直接相关：把「精确 ratio 算出的 M」「区间中值算出的规模」「代理指标 CR」「人工假设的退货率」加权成一个分数，等于**把可信度差异抹平**，让不可信的部分借可信部分的信用。分数越好看，越掩盖问题。

替代方案：**四维档位卡**（需求规模 / 变现效率 / 竞争基数 / 本店位置），每维带独立的值 + 精度 + 可信度 + 证据 id。需要排序时用**字典序**：先按可信度过滤（剔除任一关键维 `unavailable/suspect` 的），再按人在 CP-1 选定的主维度排。**不做加权求和。**

---

## 3. 状态与证据

### 3.1 run 状态：为"人第二天回来继续"设计

状态库 `agent/runs/<run_id>/run.db`（SQLite）：

| 表 | 内容 |
|---|---|
| `run` | run_id、目标、**锁定的 shop_id + shop_name**、dag 版本、创建/更新时间、总状态 |
| `node_attempt` | run_id、node_id、attempt、input_hash、status、started_at、ended_at、output_hash |
| `claim` | claim_id、node_id、文本、数值、单位、scope、trust、precision、evidence_ref[] |
| `assumption` | 人工填写的数字，与 claim 分表存（不能混） |
| `checkpoint` | 确认点快照、呈现内容 hash、人的选择、**理由文本**、决定时间 |
| `event` | 闸门拦截、skill 拒绝、口径校验失败等，**只追加** |

节点状态机：
```
pending → running → { done | awaiting_human | blocked | insufficient_evidence | failed }
```
- `awaiting_human` 是**持久状态**：进程可以退出，第二天 `resume <run_id>` 从这里继续。
- **幂等键** = `(run_id, node_id, input_hash)`。重跑时 input_hash 未变且 status=done → 直接复用产出，不重算不重取。
- **取数幂等**天然由 `compass_snapshots` 的 `UNIQUE(shop_id, endpoint, stat_key, dedup_key)` 保证：同口径同内容重抓零新行。是否重新**请求**由节点的 `evidence_freshness` 决定。
- 崩溃恢复不需要重新取数——raw 已落盘，只要新鲜度允许就直接读快照重放。

### 3.2 证据总账：复用 `compass_snapshots`，不另起炉灶

`compass_snapshots.js` 已经把最难的部分做对了：内容寻址 + gzip + sha256、**原文落文件不进 DB**（DB 坏了证据还在）、**失败也入库**（区分"没数据"和"没抓"）、shop_id 显式存。

新增的只有一层**指针表** `evidence`（同一个 `data/compass_snapshots/snapshots.db`，加表不加库）：

| 字段 | 说明 |
|---|---|
| `evidence_id` | 主键 |
| `run_id` / `node_id` | 谁在什么时候用了它 |
| `shop_id` / `endpoint` / `stat_key` / `body_sha256` | **指向 snapshots 表的四元组**，可直接 `readRaw(stat_key, sha)` 取回原文 |
| `json_path` | 从原文中抽取该值的路径 |
| `extracted_value` | 抽取到的值（**仅作校验用，不作真源**） |
| `scope` / `scope_by` | 来自 `data-contract.fieldScope(toolId, field)`，含 `by: field / source / unregistered_in_mixed / unknown` |
| `trust` / `precision` | TRUSTED/PROVISIONAL/SUSPECT/REJECTED；EXACT/RANGE/UNKNOWN |
| `range_lower` / `range_upper` / `spread` / `reliable` | 区间原值全留，**不只存 mid** |

**核心设计：evidence 不复制数值，只存"指针 + 抽取路径"。**

因此"追溯到原始 API 响应"是**可重放校验**，不是靠信任：
```
verify(evidence_id):
  raw = compass_snapshots.readRaw(stat_key, body_sha256)   # gzip 原文
  v   = jsonpath(raw, json_path)
  assert v == extracted_value                              # 不等 → 证据失效，所有引用它的 claim 一并失效
```
Harness 在两个时机跑这个校验：**节点产出时**（防抽取错误）、**生成确认卡时**（防状态漂移）。任一 evidence 校验失败 → 相关 claim 直接从确认卡上消失并显示失效原因，**不静默替换成别的值**。

**非罗盘来源同表处理**：1688 页面、素材文件、2.1 发布层的 dry-run 响应，一律走 `record()` 落盘，`endpoint` 用 `source.1688.search` / `publisher.dryrun` 等，`shop_id` 对非店铺来源传 `'global'`。这是最小扩展，共用同一套内容寻址与去重。

### 3.3 数字溯源闸门（claim-check）

节点产出的每条 claim，Harness 做**数值 token 提取**：把 claim 文本与结构化字段里的所有数字抽出来，逐个要求在 `evidence_ref[]` 指向的证据中找到出处（原值、或 Harness 内置公式在 2.3 里登记过的推导结果）。

- 找不到出处的数字 → **节点产出被拒**，`status = failed`，事件记「模型产生了无出处的数字：<token>」。
- 允许的例外只有一类：模型引用 `assumption` 表里人已填写的数字，且必须带 `assumption_ref`。

这是"AI 只给建议"能落地的技术前提——否则建议里混进一个编造的数字，人是看不出来的。

### 3.4 四种数据状态，没有第五种

`available` / `provisional` / `unavailable` / `suspect`。**不存在"用默认值填上"**。每个节点产出必须附 `coverage`：用了几条证据、缺哪几项、缺失对结论的**影响方向**（"缺竞争度 → 当前判断偏乐观"）。

---

## 4. 闸门体系

### 4.1 四道闸门在 DAG 中的位置

| 闸门 | 真源 | 触发时机 | 拦截粒度 |
|---|---|---|---|
| **G0 身份** | `shop_registry.verify` | run 启动锁定 shopId；**此后每次工具返回的 `_meta.shopId` 都比对** | **冻结整个 run**，不是跳过单条 |
| **G1 作用域** | `data-contract` | ① 证据入库打标 ② 注入模型上下文前过滤 | 单条证据；不合格的进 hypotheses 通道或直接丢弃 |
| **G2 写操作** | `approval-gate.WRITE_TOOLS` | skill/节点请求写工具时 | 单次调用，转 `awaiting_human` |
| **G3 证据溯源** | 新增 `claim-check` | 节点产出时、渲染确认卡时 | 单条 claim；无出处数字 → 节点失败 |

**G0 为什么必须冻结整个 run 而不是跳过单条**：一旦发现某次调用落到了别的店铺，此前该 run 内已采集的证据都无法自证归属（可能会话早就漂移了）。跳过单条会让污染留在结论里。冻结后由人处理：确认换店 → 新开 run；确认是误报 → 显式 `--expect-shop-id` 重启。

### 4.2 拦截后怎么让人处理

拦截**永远不是静默降级**。每种拦截对应一个可操作的出口：

| 拦截 | 人看到什么 | 可选动作 |
|---|---|---|
| G0 身份不符 | 期望 shopId + 实际 shopId + 期望来源（调用方/环境变量/注册表） | 换店重开 / 更正注册表 / 显式指定后重启 |
| G1 样本不足（`sampleSize < 100`） | "本店该指标样本 N，低于 100，属统计噪音" + 建议改看哪个 SHOP_STATE 字段 | 换指标 / 接受为参考不作依据 |
| G1 未登记作用域 | "该工具未在 SOURCE_SCOPES 登记" + 工具 id | 登记后重跑（开发动作，不许运行时绕过） |
| G1 平台结论（advisory） | 结论原文 + "只能作为待验证假设" + Agent 给的验证方案 | 执行验证 / 忽略 |
| `platform_empty` | "平台确实没下发数据" | 换时间窗 / 换端点 |
| `chart_only` | "平台只给了图表坐标，该端点不给明细" | 接受（这是端点能力边界，不是故障） |
| `unparsed_shape` | "**我们没解出来**，结构未知" + 原文 sha | 报缺陷（这是我方 bug，与平台无关） |
| G2 写操作 | 见第 6.2 节的写操作确认卡 | 批准 / 改参数后批准 / 拒绝 |
| G3 无出处数字 | 具体是哪个数字、在哪条 claim 里 | 重跑节点（不许人工"确认它是对的"） |

### 4.3 现有闸门的两个加固点（不改语义，在 Harness 侧包一层）

**加固 1：`execute` / `approved` 的产生权收归 Harness。**
`approval-gate.checkApproval` 目前接受 `args.execute === true`、`args.approved === true`、或 `DOUDIAN_ALLOW_WRITES=1` 三种放行。这对内部调用方是合理的，但对**第三方 skill** 就是一个可自证的后门。Harness 的做法：
- skill 通过 `ctx.call()` 传入的 args，**无条件剥离 `execute` / `approved` 字段**（不是报错，是剥离——报错会诱使 skill 试探）；
- Harness 进程内**禁止设置 `DOUDIAN_ALLOW_WRITES`**，启动时若检测到该环境变量已设置则拒绝启动并说明原因;
- 只有 `write-gate` 在校验通过一张**审批凭据**后才置 `execute: true`。

**审批凭据（approval receipt）** 是可核验的记录，不是布尔值：
```
{ run_id, node_id, tool_id, args_hash, shop_id, presented_hash,
  decided_by, decided_at, decision, reason, ttl }
```
- `args_hash`：批准的是**这一组参数**。参数变了凭据失效——防止"批准预览、执行别的"。
- `presented_hash`：人当时**看到的确认卡内容**的 hash。看到的东西和执行的东西对不上，凭据无效。
- `ttl`：默认 30 分钟。过期需重新确认。

**加固 2：2.1 的发布接口必须纳入同一个 `WRITE_TOOLS`。**
这是当前的真实缺口：`approval-gate.WRITE_TOOLS` 只覆盖 `D:\抖店` 的 `store.*`，而 2.1 sidecar 的 `/api/upload/*`、`/api/protocol/fxg/*` 完全不在其中——**存在两个互不知情的写路径**。设计要求：Harness 侧建 adapter 把 2.1 的写接口注册为 `publisher.*` toolId 并加入 `WRITE_TOOLS`，让"什么算写操作"**只有一个真源**。（`dispatcher.js` 的注释记录过同类事故：三处各存一份写操作清单，`delete_draft` 与 `batch_edit` 因不一致而绕过了身份闸门。)

同时，2.1 已有的 `/api/ops/publish-preflight-safety` 与 `save-edit-human-gate` 不作为并行路径，而是被 **N9 publish 节点的 pre 槽内置调用**——不通过则节点 `blocked`，凭据根本不会签发。

---

## 5. skills 插件机制

「额外添加一些手」= **在固定的 DAG 骨架上开可扩展槽位，但槽位的四壁是闸门。**

### 5.1 清单格式（`skill.yaml`）

```yaml
id: sourcing.1688-quote
version: 1.2.0
name: 1688 比价与货源核价
determinism: model_assisted        # deterministic | model_assisted

mounts:                            # 可挂哪些节点的哪个槽
  - { node: sourcing,   slot: produce }
  - { node: economics,  slot: pre }

capabilities:                      # 白名单，声明之外一律拒绝
  tools:    [source.1688.search]   # 必须是 tool-registry 里存在的 toolId
  network:  [detail.1688.com, s.1688.com]
  fs_write: ["runs/${run_id}/skills/sourcing.1688-quote/"]
  writes:   false                  # 是否可能触发 WRITE_TOOLS

io:
  input_schema:  contracts/sourcing.input.json
  output_schema: contracts/sourcing.output.json
  evidence_required: true          # 每条输出必须带 evidence_ref
  declares_scope: market           # 产出数据的作用域，由 Harness 复核，不采信自述
  declares_trust: provisional      # 抓取所得，不是平台下发 → 天然不到 TRUSTED

limits: { timeout_s: 120, max_tool_calls: 40 }
```

**关键：`declares_scope` / `declares_trust` 是 skill 的自述，Harness 只把它当"上限声明"**——skill 说自己是 MARKET，Harness 仍按 `data-contract.fieldScope()` 独立判定，取两者中**更严格**的那个。skill 不能通过自我声明提升可信度。

### 5.2 槽位：不是每个节点随便挂

每个节点开四个槽，语义不同、权限不同：

| 槽 | 能做什么 | 不能做什么 | 数量 |
|---|---|---|---|
| `pre` | 补充证据来源、做前置检查 | 不能产出 claim | 多个，顺序执行 |
| `produce` | 产出节点的主 claim | — | **每节点至多 1 个**；多个候选走 candidate 合并 + CP 人工选 |
| `post` | 加工/富化：出图、导表、生成文件 | **不能修改任何 claim 的数值** | 多个 |
| `review` | 输出 findings，可把节点判 `blocked` | **不能修改产出** | 多个 |

`review` 槽是合规与安全的挂载点——无品牌审计、素材违禁词、价格低于成本、跨店检查都挂这里。它只有否决权，没有编辑权，因此第三方 review skill 无法通过"修正"来注入内容。

### 5.3 怎么保证第三方 skill 不绕过闸门

五层，缺一层就有洞：

1. **进程隔离**：skill 以子进程运行，stdio JSON-RPC 协议（与 MCP 同构，便于复用）。**没有直接的文件系统与网络能力**——网络走 `ctx.fetch()` 域名白名单代理，写盘限定在 `runs/<run_id>/skills/<id>/`。
2. **唯一 API 面**：skill 只能看见 Harness 注入的 `ctx`（`ctx.call` / `ctx.fetch` / `ctx.evidence` / `ctx.log` / `ctx.ask`）。`ctx.call` 内部走 `dispatcher`，且**剥离 `execute` / `approved`**（4.3 加固 1）。skill 无法 `require('./lib/dispatcher')`。
3. **工具白名单**：调用未在 `capabilities.tools` 声明的 toolId → 直接拒绝并记 event。
4. **产出校验**：schema 校验 → 作用域复核 → 证据溯源校验，三关全过才入 run 状态。
5. **安装即审批**：skill 安装需人工一次性确认，记录**清单 hash + 代码目录 hash**。运行时 hash 不符 → 拒绝加载（防"装完再改"）。清单变更（尤其 `capabilities`）需重新审批。

另外：`writes: true` 的 skill 走**更严格的路径**——它的每次写请求都必须独立签发凭据，且确认卡上明确标注"该请求来自第三方 skill `<id>@<version>`"。

### 5.4 三个具体例子

**A. `material.designer`（素材生成）**
- 挂载：`asset` 节点 `produce`
- 输入：机会卡 + 选定货源 + 卖点 claim 列表 + 本地图片路径
- 输出：素材文件（落 `runs/<id>/artifacts/`）+ **每张图上的每个文案主张 → claim_ref 映射**
- 契约要点：文案里出现的每个**可核查主张**（"加厚"、"纯棉"、"防臭"）必须指向一条 evidence（供应商页面证据或 SKU 属性），否则标 `unverified_claim`。挂在同节点 `review` 槽的合规 skill 会把 `unverified_claim` 判 `blocked`——这条链路正是无品牌/虚假宣传风险的闸口。
- 能力：`network: []`（不联网），`tools: []`，只写盘。

**B. `sourcing.1688-quote`（1688 比价）**
- 挂载：`sourcing.produce` + `economics.pre`
- 输入：关键词 / 规格（棉含量、筒高、克重）/ 目标价格带
- 输出：候选货源列表 — 报价（**通常是区间/阶梯价，按 `rangeToComparable` 处理，不取最低价当点估计**）、起订量、发货地、供应商评分
- 契约要点：每条报价必须带**原始页面快照 evidence**（同样走 `compass_snapshots.record`，`endpoint: 'source.1688.search'`，`shop_id: 'global'`）。`trust` 封顶 `provisional`（抓取所得，非平台下发）。
- 数据不足：拿不到阶梯价只有单价 → 标 `precision: exact` 但 `note: 未见阶梯，实际采购价可能更低`；拿不到起订量 → `unavailable`，N6 的备货金额算不出，CP-2 上明确显示"备货成本无法估算"，而不是按 1 件估。

**C. `competitor.watch`（竞品监控）**
- 挂载：`ops.observe.pre`，可由定时器独立触发
- 输入：**人工确认过的**竞品商品 id 列表（不许 skill 自己决定盯谁）
- 输出：**只有变更事件**（价格变化、标题改动、主图更换、销量档位跨越），**不产出结论**
- 契约要点：竞品销量平台只给档位/区间 → 只报「从 A 档跨到 B 档」，**绝不报增长率百分比**。这是硬约束 4 的直接体现：一个由区间差算出的增长率看起来精确、实际是编的。
- 结论由 `ops.diagnose` 节点的 Agent 做，且必须同时看本店 SHOP_STATE 数据。

### 5.5 与 2.1 现有 `skills/douyin-publisher-mcp` 和 `mcp-server` 的关系

**并存 + 分层，不取代。** 三者层级不同，现在混在一起是概念问题不是实现问题：

| 组件 | 真实身份 | 在新机制中的位置 |
|---|---|---|
| `mcp-server/`（core.js、cdp-tools.js） | **能力提供方（tool provider）** | 注册为 Harness 的一个 tool adapter，工具以 `publisher.*` / `cdp.*` 前缀进入 `tool-registry`，写操作**必须**加入 `approval-gate.WRITE_TOOLS` |
| `skills/douyin-publisher-mcp/`（SKILL.md、playbooks.md、capabilities.md） | **给 Claude 用的提示词/剧本包**，不是可执行插件 | 降级为 `listing.compose` / `publish` 两个节点的**节点知识素材**（`agent/dag/nodes/*.md` 引用），不再作为独立执行路径 |
| 新的 skill 插件 | **DAG 节点内的可插拔执行单元** | 本节设计的机制 |
| `D:\抖店\skills/*/skill.md`（market-analysis 等） | 当前是**流程说明文档**，无契约无隔离 | 迁移为节点定义（`market.scan` 等）+ 少量 produce skill。注意 `market-analysis/skill.md` 现在直接调 `diagnosis.compass.diagnosis`、`search_diagnosis` 这类**平台结论型端点并直接写进报告**——迁移时必须改走 hypotheses 通道 |
| `D:\抖店\harness/*.md`（12 个 Agent 作业台） | **角色提示词**，与本设计的 Harness 同名但不同层 | 保留为节点的 role prompt 素材。建议改名 `agent/roles/` 以消除歧义 |

一句话：**mcp-server 出"手"，douyin-publisher-mcp 出"话术"，新 skill 机制出"可插拔的判断单元"，Harness 出"骨架和闸门"。**

---

## 6. 人在环中（HITL）

### 6.1 确认卡：人看到什么才能真正做判断

「同意/拒绝」两个按钮是不够的。确认卡固定七段：

```
① 结论（一句话） + 置信标签
   建议在「船袜 纯棉 防滑」方向找货                    [ 可信度：中 ]

② 判断依据（逐条可展开）
   ┌ 变现效率 M = 1.380  ── 优于大盘 38%
   │  算法：pay_amt__ratio(0.2262) ÷ search_show_ucnt__ratio(0.1639)
   │  来源：compass.search.industry_rank · scope=MARKET · 精度=EXACT
   │  证据：ev_8f3a…  [查看原始响应]   口径一致性校验：通过(max/min=1.4)
   │  期数：1 期 → 标 provisional（需 3 期方向一致才可驱动决策）
   ├ 需求规模 ≈ 86.6 万人  ── 由区间 [75万, 100万] 取几何中值
   │  ⚠ 这是区间不是精确值。平台对同行数据只下发区间，这是最高可得精度。
   │  spread = 1.33 · reliable = true
   └ 竞争基数 ── ✗ 不可用（shop_rank 未返回 total）

③ 反面证据与未验证项（必须显示，不能只列支持证据）
   · M 偏高也可能因为「袜子」是宽泛词，成交来自其他子类目 —— 未验证
   · 平台的搜索诊断建议「优化 3 个商品」→ advisory，判 SUSPECT，未采纳
     验证方案：用 compass.search.source 的本店来源词交叉比对（未执行）

④ 你自己假设的数字（不是查来的）
   退货率 12%（你于 08-27 填写）· 平台扣点 5%（你于 08-20 填写）

⑤ 覆盖度
   用了 4 条证据，缺 2 项（竞争基数、子类目拆分）
   缺失影响方向：当前判断 **偏乐观**

⑥ 如果错了，最坏损失
   备货 200 双 × 采购中值 3.2 元 ≈ 640 元（采购价为区间，实际 512~800 元）

⑦ 你的选择
   [ 批准 ]  [ 批准但改参数 ]  [ 先补数据：补竞争基数 ]  [ 拒绝 ]
   理由（必填，会写进复盘）：____________
```

设计要点：
- **③ 是这张卡最重要的一段**。只列支持证据的卡片会让人变成橡皮图章，那就等于无人值守。
- **④ 把假设和证据物理分开**，人才知道哪些数字是自己给的。
- **⑤ 的"影响方向"**比"缺了 2 项"有用得多——它告诉人往哪个方向打折扣。
- **选项四选一而非二选一**，其中"先补数据"是把控制权交回给人的关键出口。
- 理由必填：它进 `checkpoint` 表，成为 N11 复盘的输入（"你上次以 X 理由批准，实际结果是 Y"）。

### 6.2 三类确认点，形态不同

**CP-决策类（CP-1 机会、CP-2 备货）**：上面的七段卡。

**CP-写操作类（CP-3 发布、CP-4 改价/下架）**：额外三项，缺一不可：
- **店铺横幅**：`shopId + 店名`，来自本次实测 cookie，置顶显示（跨店误操作不可逆）
- **字段级 diff**：将写入什么 / 覆盖什么，逐字段左右对照
- **dry-run 结果原文**：`approval-gate.dryRunResponse` 与 2.1 preflight 的返回，可展开看原始 JSON

批准后签发凭据（4.3），`args_hash` 与 `presented_hash` 一并写入——**人看到的和执行的必须是同一件事**。

**CP-补数类**：不是"批准/拒绝"，是三选一：**跳过该维度（并接受结论降级）/ 我手工提供这个数字（转 assumption）/ 换一条取数路径**。

### 6.3 防确认疲劳

- **批量 + 例外上浮**：同质低风险项（如 20 张素材）批量呈现摘要，只有触发确定性规则的**例外**单独展开。规则包括：无品牌违规、价格 ≤ 成本、shopId 不符、`unverified_claim`、证据重放校验失败。
- **确认粒度随信任累积上升**：同一类操作连续 N 次批准且未出事 → 可提议把粒度从"逐条"改为"批量"。**但这必须由人显式同意一次，并且写操作永远不能降级为免确认**（硬约束 2）。
- **不批准也是有效结果**：`awaiting_human` 持久化，run 可以挂三天。Harness 不催、不超时自动放行。

---

## 7. 目录结构与文件职责

### 7.1 `D:\抖店`（数据层 + Harness 运行时）

```
D:\抖店\
├─ lib\                            【现有，不动】tool provider + 三道闸门真源
│   ├─ data-contract.js               作用域/可信度/精度 —— G1 真源
│   ├─ approval-gate.js               WRITE_TOOLS —— G2 真源（需扩充 publisher.*）
│   ├─ shop_registry.js               店铺身份 —— G0 真源
│   ├─ compass_snapshots.js           证据存储底座（加 evidence 表，不另起库）
│   ├─ compass_unwrap.js / dispatcher.js / tool-registry.js / envelope.js
│
├─ agent\                          【新增】Harness 运行时
│   ├─ runtime\
│   │   ├─ run-store.js               run/node_attempt/claim/assumption/checkpoint/event 六表
│   │   ├─ dag.js                     DAG 定义加载、拓扑校验、版本 hash
│   │   ├─ scheduler.js               调度、续跑、幂等键、awaiting_human 恢复
│   │   ├─ node-runner.js             单节点执行：备证据 → 跑 skill → 校验 → 落盘
│   │   ├─ evidence.js                证据总账（薄封装 compass_snapshots + 非罗盘来源）
│   │   ├─ claim-check.js             数值溯源校验 —— G3
│   │   ├─ metrics.js                 2.3 节全部确定性公式（M、CR、区间处理、口径校验）
│   │   ├─ gates\
│   │   │   ├─ identity-gate.js       G0：run 级 shopId 锁定与逐次比对
│   │   │   ├─ scope-gate.js          G1：证据准入 + 两通道分流
│   │   │   ├─ write-gate.js          G2：凭据签发/校验 + args 净化（剥 execute/approved）
│   │   │   └─ evidence-gate.js       G3：产出前的证据完整性与重放校验
│   │   ├─ adapters\
│   │   │   ├─ compass.js             D:\抖店 dispatcher 适配
│   │   │   ├─ publisher-2_1.js       2.1 sidecar 5001 → publisher.* toolId
│   │   │   └─ mcp.js                 mcp-server 工具接入
│   │   ├─ hitl\
│   │   │   ├─ checkpoint.js          确认点生成、presented_hash 计算
│   │   │   └─ renderer.js            七段确认卡渲染（终端 / HTML）
│   │   └─ skills\
│   │       ├─ loader.js              清单解析、安装审批、hash 校验
│   │       ├─ host.js                子进程宿主、超时、资源限制
│   │       ├─ ctx.js                 skill 唯一可见 API 面
│   │       └─ protocol.md            stdio JSON-RPC 协议规范
│   ├─ dag\
│   │   ├─ commerce.dag.yaml          11 节点主 DAG
│   │   └─ nodes\<node>.yaml + .md    节点契约 + 节点提示词
│   ├─ contracts\
│   │   ├─ run.schema.json / claim.schema.json / evidence.schema.json
│   │   ├─ assumption.schema.json / checkpoint.schema.json
│   │   └─ skill-manifest.schema.json
│   ├─ roles\                       ← 由现 harness\*.md 迁入（角色提示词，消歧义）
│   ├─ skills\                      ← 已安装 skill（每个含 skill.yaml + 代码 + hash）
│   └─ runs\<run_id>\
│       ├─ run.db  artifacts\  checkpoints\  skills\<skill_id>\
│
├─ data\compass_snapshots\          【现有】snapshots.db + raw\（+ 新增 evidence 表）
└─ shop_profiles\registry.json      【现有】shop_registry 自动维护
```

### 7.2 `C:\Users\CRB\Desktop\2.1`（发布层执行器）

**保持现状，只做两件事**（都不是重构）：
1. `skills/douyin-publisher-mcp/playbooks.md` 的内容被 `agent/dag/nodes/listing.compose.md` 与 `publish.md` 引用为节点知识——**内容复用，执行路径收归 Harness**。
2. 发布相关写接口经 `adapters/publisher-2_1.js` 注册为 `publisher.*` 并加入 `approval-gate.WRITE_TOOLS`。现有的 `/api/ops/publish-preflight-safety`、`save-edit-human-gate` 成为 `publish` 节点 `pre` 槽的必经检查。
3. `src/ops_engine.py` 的利润阶梯 / 选品评估被 `economics` 节点调用——它是本地规则计算，与"禁用外部 AI 与官方 API"的既有约束天然兼容，不需要改。

---

## 8. 落地顺序与验收判据

按"每一步都能独立证伪"排：

| 阶段 | 交付 | 验收（必须能实测出来） |
|---|---|---|
| P0 | `evidence.js` + evidence 表 + 重放校验 | 任取一条 evidence，能 gunzip 原文、按 json_path 重放、值一致；改动原文后校验必须失败 |
| P1 | `metrics.js`（M、口径校验、区间处理） | 用袜子实测数据算出 M=1.380；人为构造口径不一致的数据，必须整批判 suspect |
| P2 | `run-store` + `scheduler` + 幂等 | 跑到一半 kill 进程，`resume` 后不重复取数、不重复算已完成节点 |
| P3 | 四道闸门 + `write-gate` 凭据 | 构造 shopId 漂移 → run 冻结；skill 传 `execute:true` → 被剥离且写操作仍拦下 |
| P4 | 七段确认卡 + CP-1 | 卡上每个数字都能点开看到原始响应；反面证据段非空 |
| P5 | skill 宿主 + 三个示例 skill | 越权调用未声明的 toolId → 拒绝并留 event；改 skill 代码不改 hash → 拒绝加载 |
| P6 | N9 publish 打通 + `publisher.*` 入 WRITE_TOOLS | 从 2.1 侧直接调发布接口的旧路径被堵死，只剩经凭据的一条 |

**贯穿全程的一条红线**：任何阶段，宁可让流程停在 `insufficient_evidence` 并把缺口列清楚，也不产出一个看起来完整的结论。这条不是风格偏好——用户店铺当前 19 个商品、曝光 2 次、支付 0 单，本店统计量全部落在 `MIN_SAMPLE_FOR_METRIC = 100` 门槛之下。在这个样本条件下，**任何"看起来完整"的自家数据分析都是编的**。这套 Harness 存在的全部意义，就是让这件事变成一次明确的失败，而不是一份漂亮的报告。
# DAG 节点与契约

> 本文由设计评审产出（2026-08-29），其中的结论**需要被实现验证**。
> 已被实证推翻或修正的部分见文末「实证修正」。

---

# 电商 Agent DAG:节点与契约设计

> 范围:仅设计,不含实现代码。所有 toolId 均取自 `D:\抖店\lib\compass_tools.js` 的 `CATALOG`(完整 id = `compass.<id>`)、`lib\dispatcher.js` 的路由表、`lib\1688.js`,以及 `C:\Users\CRB\Desktop\2.1\tauri-app\python-sidecar\app.py` 的 `/api/ops/*` 路由。

---

## 0. 全局契约(所有节点共用)

### 0.1 节点结果信封 `NodeResult`

```
NodeResult {
  run_id            # 一次 DAG 运行实例
  node_id           # 稳定节点标识,见下表
  node_run_id       # 同一节点的第 N 次执行(重跑不覆盖,append-only)
  upstream          [ {node_id, node_run_id} ]   # 显式记录本次用的上游版本
  status            ok | degraded | blocked | rejected
  outputs           {...}                        # 见各节点
  evidence          [ EvidenceRef ]
  degrade           [ {field, reason, fallback_used|null} ]
  blocked_reason    null | string
  human_gate        null | {required:bool, decision, decided_by, decided_at, diff_digest}
  produced_at
}
```

### 0.2 证据引用 `EvidenceRef`(结论可追溯的唯一手段)

```
EvidenceRef {
  ev_id
  tool_id           # 例 'compass.search.industry_rank'
  args              # 例 {date:'2026-08-28'}
  snapshot_id       # lib/compass_snapshots.js 的 sha256,原始 gzip 响应可回放
  field_path        # 例 'data.list[0].pay_amt.extra_value.lower'
  raw_value
  scope             # data-contract.SCOPE:market/shop_metric/shop_state/reference/local
  trust             # trusted/provisional/suspect/rejected
  precision         # exact/range/unknown (detectPrecision)
  sample_size       # shop_metric 必填
  can_drive_decision# data-contract.describe() 的结果,不是本节点自己判的
  advisory          # CATALOG 里 advisory:true 的工具必须为 true
  captured_at
}
```

**三条硬规则(违反即节点 blocked,不做静默降级):**

1. `outputs` 里任何**数值型结论字段**必须带 `derived_from: [ev_id...]`。拿不到证据的字段输出 `null` + 进 `degrade`,**禁止填默认值/0/上期值**。
2. `can_drive_decision === false` 的字段**不得进入任何公式**。进入即抛错,不得跳过该项继续算(跳过=悄悄改了公式含义)。
3. `advisory === true` 的数据(`compass.product.recommend_optimized`、`diagnosis.compass.diagnosis`、`diagnosis.compass.search_diagnosis`、`compass.content.video_advices`)**只能写入 `assumption_to_test[]`**,每条必须绑定一个 `verification_plan{tool_id, field_path, op, threshold}`;绑不上就丢弃并记进 `dropped_advisory[]`。这是"平台推荐不准确"这条约束的机器化落点。

### 0.3 区间处理约定

行业数据以区间为**最高可得精度**(`is_self=0` 连 `value` 字段都不下发)。所有消费方:

- 用 `data-contract.rangeToComparable(lower, upper)` → `{lower, upper, mid, spread, reliable}`,`reliable = (upper/lower) <= 4`。
- **禁止取 lower 或 upper 当点估计**。
- 两个区间做除法时误差必须传播:`E_lower = M_lower / D_upper`,`E_upper = M_upper / D_lower`。
- `reliable === false` 的量**只能用于定性排序,不得用于绝对阈值判定**(例如不能说"月成交 8750 万",只能说"量级在 7.5e8~1e9 之间")。

### 0.4 比值字段优先原则(本设计的一个关键取舍)

实测样本里 `pay_amt__ratio: 0.2262` / `search_show_ucnt__ratio: 0.1639` 是**精确下发的**,而 `pay_amt__lower/upper` 是区间。

因此:**凡是能用 ratio 表达的判据,一律用 ratio,不用区间中值**。ratio 是精确值、无区间误差、且天然做了类目归一化(跨日期/跨类目可比)。绝对量级只用于"这个盘子够不够大"的粗档位判断。

---

## 1. 节点总表

| node_id | 名称 | 类型 | 上游 | 人工闸门 | 可重跑 |
|---|---|---|---|---|---|
| `N0.shop_anchor` | 店铺与目标锚定 | 只读 | — | 目标值人工填 | 是 |
| `N1.market_harvest` | 市场原始信号采集 | 只读 | N0 | 无 | 是(按 date 幂等) |
| `N2.hypothesis_gen` | 机会假设生成 | 计算 | N1, N0 | 无 | 是 |
| `N3.cross_check` | 交叉证伪与去重 | 只读+计算 | N2, N1 | **是(机会短名单拍板)** | 是 |
| `N4.sourcing_brief` | 选品条件翻译 | 计算 | N3, N9a, N0 | **是(词映射定稿)** | 是 |
| `N5.supply_search` | 供给侧检索(1688) | 只读(外站) | N4 | **是(候选勾选)** | 否(报价会变) |
| `N6.profit_gate` | 利润门 | 本地计算 | N5, N2, N0, N12↺ | 无 | 是 |
| `N7.candidate_lock` | 候选定档+假设冻结 | 写账本 | N6 | **是(拍板)** | 半不可逆 |
| `N8.asset_build` | 素材与标题生产 | 计算+本地 | N7, N4, N9a | **是(主图/标题定稿)** | 是 |
| `N9a.schema_prep` | 类目属性与合规准备 | 只读 | N0 | 无 | 是 |
| `N9b.listing_assemble` | 上架包组装+预检 | 计算 | N7,N8,N9a | 无 | 是 |
| `N10.publish` | 发布上架 | **写** | N9b | **是(逐项预检签核)** | **不可逆** |
| `N11.cold_observe` | 冷启动观测 | 只读(定时) | N10 | 无 | 是(按日幂等) |
| `N12.adjudicate` | 假设裁决(回流验证) | 计算 | N11, N7, N1' | **是(裁决复核)** | 是,记录 append-only |
| `N13.ops_loop` | 运营动作闭环 | 计算+**写** | N12, N11 | **是(每个写动作)** | 动作不可逆 |

横切(非流程节点,是基础设施):`X1.snapshot`(compass_snapshots)、`X2.contract_gate`(data-contract)、`X3.approval`(approval-gate)、`X4.hypothesis_ledger`(假设账本 SQLite)。

---

## 2. 各节点契约

### N0.shop_anchor — 店铺与目标锚定

**职责**:确定"我们在给哪个店做决策",并把店铺级参数(目标、成本结构、运费模板集合)取到。**不做**任何市场判断。

**输入**:人工输入 `target_daily_net_profit`(默认 500,来自 ops_engine 利润阶梯设定)、`capital_ceiling`、`sku_capacity`。

**输出**:
```
shop_id, shop_name, category_roots[]
freight_templates: [{template_id, name, rule_digest}]   # 来自 store.freight.list,不写死
cost_params: {platform_commission_rate, refund_rate, ad_cost_ratio,
              each with {value, source: 'measured'|'benchmark'|'assumed', derived_from[]}}
targets: {daily_net_profit, window_days, capital_ceiling}
qualification: {no_brand_ok, category_restrictions[]}
```

**工具**:`store.shop.info`、`store.shop.list`、`store.freight.list`、`store.qualification.query`、`lib/shop_registry.js` 身份校验、`compass.shop.core_index`(仅探活)。

**人工确认点**:`targets` 全部由人填;`cost_params` 中 `source !== 'measured'` 的项必须人工确认后才允许下游使用(并会自动登记成一条待验证预测,见 N6)。

**失败与降级**:
- 身份校验不通过(profile 名 ≠ 实测 cookie 店铺)→ **BLOCK 整条 DAG**。这是唯一一处"什么都不做"比"做点什么"更对的地方——所有下游证据都要打 `shopId` 标签。
- `store.freight.list` 拿不到 → 不阻塞采集链,但把 `N9b` 标为 blocked(不允许猜运费模板 id)。

---

### N1.market_harvest — 市场原始信号采集

**职责**:只抓原始指标并存证,**不下任何结论**,不过滤、不排序、不打分。

**输入**:`N0.shop_id`、`N0.category_roots`、`date`(单日)。

**输出**:
```
signal_pool: [
  { word, rank, date,
    pay_amt: {lower, upper, mid, spread, reliable} | null,
    pay_amt_ratio: number,                 # 精确值
    search_show_ucnt: {lower, upper, mid, spread, reliable} | null,
    search_show_ucnt_ratio: number,        # 精确值
    derived_from: [ev_id...] }
]
shop_rank_frame:  {total, self_rank, rows[]}     # compass.search.industry_shop_rank
index_range_frame:[{index_name, buckets[{lo,hi,shop_cnt,ratio}], self_bucket_idx}]
hot_sale_frame:   [...]                          # diagnosis.compass.hot_sale_rank
content_frame:    [...]                          # diagnosis.douyin.hot_search
self_search_words:[{word, is_indexed:true}]      # compass.search.source,词属 MARKET
category_tree:    {...}                          # REFERENCE
empty_classification: [{tool_id, kind: platform_empty|chart_only|unparsed_shape}]
```

**工具**:`compass.search.industry_rank`(主)、`compass.search.industry_shop_rank`、`compass.market.index_range`、`compass.market.benchmark`、`compass.search.source`、`diagnosis.compass.hot_sale_rank`、`diagnosis.compass.keyword_search`(**混合作用域,必须按 `FIELD_SCOPE_RULES` 逐字段拆**:`shop_*` 前缀归 SHOP_STATE)、`diagnosis.douyin.hot_search`、`compass.product.category_tree`。

**人工确认点**:无(纯只读采集)。

**失败与降级**(严格按 `lib/compass_unwrap.js` 的三分类,不合并处理):
| 情况 | 处置 |
|---|---|
| `platform_empty` | 记为"平台确实没有数据",该项 `null`,**不重试、不换端点凑数**。已知 `diagnosis.compass.industry_words` 实测只回表头 → 直接不进主链 |
| `chart_only` | 只有图无明细 → 该词不进入 `signal_pool`,记进 `degrade`。不做 OCR/估读 |
| `unparsed_shape` | **BLOCK 该工具**并上报"结构可能变更",不吞。这是唯一应该吵闹的一类 |
| Cookie 失效/风控 | BLOCK,提示人工重新登录。不允许用 `cache/` 里的旧快照冒充当日数据 |

**已知不确定项(必须实测,不许假设)**:`compass.search.industry_rank` 的 `args` 只有 `['date']`,**返回条数由平台决定,能否取到长尾词未经证实**。N2 的长尾策略依赖这一点,若实测只回 Top N,N2 必须走降级分支(见下)。

---

### N2.hypothesis_gen — 机会假设生成

**职责**:把 `signal_pool` 组合成**可证伪的命题**。**不判断真假**,不选品,不打单一"机会分"当结论。

**输入**:`N1.signal_pool`、`N1.shop_rank_frame`、`N1.index_range_frame`、`N0.category_roots`。

#### 计算规则(每条写明字段与不足时的处置)

**(a) 变现效率 E_ratio —— 首要判据**
```
E_ratio(word) = pay_amt__ratio / search_show_ucnt__ratio
```
- 字段:`pay_amt__ratio`、`search_show_ucnt__ratio`(两者均为精确值,无区间误差)。
- 含义:该词的成交占比相对曝光占比的倍数。>1 = 该词的流量比类目平均更值钱。
- 实测锚点:`袜子` = 0.2262 / 0.1639 = **1.38**。
- 数据不足:任一 ratio 缺失 → `E_ratio = null`,该词标 `unmeasurable_efficiency`,**不进候选池**(不是给它 1.0)。

**(b) 盘子量级 D_mid / M_mid**
```
D = rangeToComparable(search_show_ucnt__lower, search_show_ucnt__upper)
M = rangeToComparable(pay_amt__lower, pay_amt__upper)
```
- 只用于**档位判断**(能不能养活一个 SKU),不用于绝对预测。
- `D.reliable === false`(spread > 4)→ 量级只输出档名(`大/中/小`),不输出数字。实测袜子 `7.5e5~1e6`,spread=1.33,reliable=true;而 `7.5e8~1e9` 同样 reliable。跨数量级的词(如 `1e4~1e6`)会被判 unreliable。

**(c) 竞争集中度代理 C —— 明确拒绝用平台"竞争度"结论**
```
C_top = index_range_frame 中 pay_amt 指标最高档的 (成交占比 / 店铺数占比)
```
- 字段:`compass.market.index_range` 的 `buckets[].ratio` 与 `buckets[].shop_cnt`;辅以 `compass.search.industry_shop_rank` 的 `total`。
- C_top 越大 = 头部店铺吃掉的份额越集中 = 新店越难切入。
- 数据不足:`index_range` 不可得 → `C = null`,该机会打 `competition_unknown: true`,**且 `opportunity_grade` 强制降一档并禁止自动进入 N3 短名单**(必须人工看)。绝不用默认值。

**(d) 头部词剔除(启发式,必须标注为启发式)**
`rank <= 10` 或 `search_show_ucnt_ratio > 类目Top1的0.5倍` 的词只用作**类目基准**,不作机会候选。理由:头部词位次由投放预算决定,不是选品能改变的变量。
- 基准值:`E_base = 头部词 E_ratio 的中位数`(袜子样本给出 1.38 量级)。
- 候选筛选:`E_ratio >= E_base × 1.2` 且 `D` 落在中小档。
- **这条本身是一个元假设**,写入 `meta_hypotheses[]`,由 N12 的多轮结果检验(见 §5.3)。

**(e) 不输出单一分数掩盖缺失**
输出三元组 + 缺失清单,而非一个 score:
```
opportunity_grade = { demand: L/M/H|null, efficiency: L/M/H|null, competition: L/M/H|null }
missing_terms = ['competition']        # 非空时 can_drive_decision=false
```
若坚持要排序,排序键仅用 `E_ratio`(精确值),并在 UI 明示"排序只依据变现效率,未计入竞争"。

#### 输出:`Hypothesis` 记录格式(回流验证的地基)

```
Hypothesis {
  hyp_id, version, shop_id, created_at, created_from_run_id
  statement            # 人话:"目标词族 {kw} 存在真实需求且非头部集中,
                       #  一个满足 {spec} 的商品在 {price_band} 内,
                       #  {window_days} 天内可达 {target}"
  keyword_set: [ {word, rank, date, tool_id:'compass.search.industry_rank', snapshot_id} ]
  demand:        {field:'search_show_ucnt', lower, upper, mid, spread, reliable, ev_id}
  monetization:  {field:'pay_amt', lower, upper, mid, spread, reliable, ev_id}
  efficiency:    {field:'pay_amt__ratio / search_show_ucnt__ratio', value, ev_id[]}
  competition:   {proxy:'index_range_top_bucket_concentration', value|null,
                  unknown_reason, ev_id[]}
  price_band:    {lower, upper, derivation, ev_id[]} | null
  product_spec:  {category_path, required_attrs{}, pack_spec, material}
  assumption_to_test: [ {claim, source_tool(advisory), verification_plan{...}} ]
  predictions:   [ Prediction ]           # ★ 必须在 N10 之前冻结
  falsifiers:    [ Falsifier ]
  observability: {expected_impressions_in_window, min_sample_needed:100,
                  verifiable: bool, unverifiable_reason}
  status: draft | active | confirmed | refuted | inconclusive | expired | superseded
  frozen_at, bound_product_ids[]
}

Prediction {
  pred_id, kind: 'state' | 'metric',
  metric_tool_id, field_path, scope,
  op, threshold, threshold_derivation,     # 阈值必须写清是怎么来的
  window_days,
  precondition: {min_sample|min_days|requires_field}, hard: bool
}

Falsifier {
  fal_id, description, metric_tool_id, field_path, op, threshold, window_days
}
```

**预测必须分两类**,这是应对新品样本量问题的核心:

| kind | scope | 例子 | 样本量约束 |
|---|---|---|---|
| `state` | SHOP_STATE | 上架后 14 天内出现在 `compass.search.source` 的目标词列表中;`compass.product.rank` 里出现 `rank_num`;`compass.market.index_range` 中本店 `self_bucket_idx` 上移 ≥1 档 | **不受** `MIN_SAMPLE_FOR_METRIC` 约束("没被某个词收录"是事实不是概率) |
| `metric` | SHOP_METRIC | 21 天累计支付订单 ≥ N;转化率 ≥ x | 受 100 样本门槛约束,不足即判 `inconclusive`,**不判 refuted** |

**可观测性预检(强设计点)**:
```
expected_impressions_in_window = D.mid × 预期词内份额 × window_days
```
若 `expected_impressions_in_window < 100`,则 `observability.verifiable = false`。此时 **N2 就要明确告诉人:这个机会在你设定的窗口内无法被数据验证**,由人决定是否仍要试(试则记 `unverifiable_by_design = true`,N12 一律裁 `inconclusive`,不许事后编成功故事)。

**失败与降级**:
- `signal_pool` 只有 Top N 无长尾 → 降级为"在可得词表内选 `E_ratio` 最高且 `D` 最小的词",并把 `degrade: [{field:'long_tail_pool', reason:'industry_rank 未下发长尾'}]` 显式写出。
- `price_band = null` → 假设仍可生成(status=draft),但**不允许进入 N4 → N6**(没有价格带就没有成本天花板,利润判断是假的)。

---

### N3.cross_check — 交叉证伪与去重

**职责**:用**与生成假设不同的数据源**独立验证需求是否成立,并排除"本店已经在做/做过"的重复机会。**不做**选品。

**输入**:`N2.hypothesis[]`、`N1.hot_sale_frame`、`N1.self_search_words`。

**输出**:
```
per_hypothesis: {
  hyp_id,
  cross_confirm: {
     search_side_present: bool,   # compass.search.industry_rank
     trade_side_present: bool,    # diagnosis.compass.hot_sale_rank(成交侧,独立来源)
     content_side_present: bool,  # diagnosis.douyin.hot_search(内容侧,弱信号,仅参考)
     verdict: confirmed_both_sides | search_only | trade_only | none
  },
  duplication: {already_indexed_words[], existing_product_ids[], overlap_ratio},
  advisory_handling: {tested[], dropped_advisory[]},
  routing: promote | hold | reject_duplicate | reject_no_cross_confirmation
}
shortlist: [hyp_id...]   # ≤5,给人看
```

**工具**:`diagnosis.compass.hot_sale_rank`(成交侧交叉源)、`compass.search.source`(本店已被哪些词收录,SHOP_STATE)、`store.product.list`、`compass.product.rank`、`compass.product.category_overview`。

**平台结论的处理**:`compass.product.recommend_optimized`(advisory)、`diagnosis.compass.diagnosis`、`diagnosis.compass.search_diagnosis` 在这里被消费,但**只允许生成 `assumption_to_test` 条目**。例如平台说"该商品标题不佳" → 转成"预测:改标题后 14 天内 `compass.search.source` 中出现目标词",而不是直接接受"标题不佳"这个结论。绑不上原始字段的一律进 `dropped_advisory[]` 并在报告里可见。

**人工确认点**:★ **机会短名单拍板**。Agent 给 ≤5 条,附每条的三元档位、缺失项、证据链接;人选 1~2 条进入选品。这是第一个正式人工闸门。

**失败与降级**:
- 只有搜索侧确认、成交侧空 → `search_only`,不阻塞,但把 `cross_confirm_weak: true` 写进假设,并在 N12 裁决时降低置信。
- `hot_sale_rank` 不可达 → DEGRADE(标注"无独立交叉源"),**不允许把 `industry_rank` 拆两次算作两个来源**。

---

### N4.sourcing_brief — 选品条件翻译 ★机会→选品的交接

**职责**:把一个抽象"机会"翻译成**可执行的 1688 搜索条件 + 硬验收判据**。**不做**搜索,不做评估。

**输入**:`N3.shortlist` 选中的 `Hypothesis`、`N9a.listing_schema`(类目必填属性——**这条跨层边是 DAG 的关键证据之一**)、`N0.cost_params`/`targets`。

**输出:`SourcingBrief`**
```
SourcingBrief {
  brief_id, hyp_id, version,

  query_terms: {
    primary: []            # 品类中心词,进 1688 搜索
    attribute: []          # 材质/工艺/规格词,进搜索 + 后续标题
    audience_scene: []     # 人群/场景/情绪词 —— 不进 1688 搜索,只进 N8 素材与标题
    exclude: []            # 品牌词、明确不做的方向
    term_mapping: [ {douyin_word, alibaba_query, kept_parts[], dropped_parts[],
                     why, ev_id[]} ]
  },

  spec_constraints: {
    category_path, category_id,
    required_attrs: {...},        # 来自 store.product.schema / compass.product.category_tree
    forbidden: ['任何品牌名','商标图案','吊牌露出'],
    pack_spec, size_range, material_required[]
  },

  cost_ceiling: {
    target_sale_price_band: [lo, hi],
    max_landed_cost: number,       # ops_engine 反解
    derivation: 'recommend_sale_price_for_margin(target_net_margin) 反解 + 运费/佣金/退货率',
    inputs_used: [{name, value, source:'measured'|'benchmark'|'assumed', ev_id}]
  },

  supply_filters: {moq_max, ship_within_days, min_shop_years, min_repurchase_rate},

  acceptance: [ {field, op, value, hard:bool} ]   # 选品命中判据
}
```

#### 翻译规则(具体到怎么切词)

抖音搜索词按**人群/场景**组织(如"男士 中筒袜 纯棉 防臭"),1688 供给侧按**品类+材质+工艺**组织。规则:

| 词成分 | 去向 | 理由 |
|---|---|---|
| 品类中心词(袜子/船袜/中筒袜) | `primary` → 1688 搜索 | 供给侧按品类建索引 |
| 材质工艺词(纯棉/抗菌/精梳) | `attribute` → 1688 搜索 + 属性筛选 | 供给侧有对应属性筛选 |
| 人群场景情绪词(男士/学生/送男友/ins风) | `audience_scene` → **不进搜索**,进 N8 标题与主图文案 | 1688 上这些词命中率低且会误伤供给面;但它们是抖音端的成交词,必须保留到素材侧 |
| 品牌词 | `exclude` | 无品牌策略硬约束 |

**每条 `term_mapping` 必须写 `why` 和 `ev_id`,且最终版由人工确认**(★ 人工闸门)。理由:这一步是跨平台语义映射,没有任何可验证的数据源能证明映射对不对——诚实的做法是承认它是人的判断,Agent 只给建议和依据。

#### 价格带推导链(数据不足逐级降级,到底就阻塞)

| 优先级 | 方法 | 依赖字段 | 不可得时 |
|---|---|---|---|
| 1 | 词级客单价 = `pay_amt` 区间 ÷ `pay_ucnt` 区间 | `compass.search.industry_rank` 是否下发 `pay_ucnt` **待实测** | 降级 2 |
| 2 | `compass.market.index_range` 客单价指标的相邻档位边界(取本店目标档) | `buckets[].lo/hi` | 降级 3 |
| 3 | `compass.search.industry_shop_rank` 同类目店铺客单价字段(区间) | 行数足够 | 降级 4 |
| 4 | **无** → `price_band = null` | — | **BLOCK N6**,不允许"按 1688 进价 ×3"这类经验倍率蒙混过去 |

`max_landed_cost` 由 `POST /api/ops/sourcing-profit-gate` 反解(内部走 `ops_engine._supplier_target_cost_ceiling` / `recommend_sale_price_for_margin`),其输入里凡是 `source:'assumed'` 的参数,**自动在 `Hypothesis.predictions` 里追加一条待验证预测**(见 N6)。

**失败与降级**:`listing_schema` 未就绪 → brief 可以出草稿但 `spec_constraints.required_attrs` 为空并标 `degraded`,禁止进入 N7 定档(否则选到的货可能填不满类目必填属性)。

---

### N5.supply_search — 供给侧检索(1688)

**职责**:按 brief 找货、取报价与素材原件。**不做**评估、不下单、不联系供应商。

**输入**:`N4.SourcingBrief`。

**输出**:
```
candidates: [{
  candidate_id, source:'1688', offer_id, url, title,
  price_tiers: [{moq, price}], quoted_at,          # 报价时间戳必带
  landed_cost_parts: {goods, inbound_freight, packaging, unknown[]},
  supplier: {shop_years, repurchase_rate|null, ship_days|null, ev_id[]},
  attrs_matched: {...}, acceptance_check: [{field, pass, actual}],
  media: {main_images[], detail_images[], local_paths[]},
  ev_id[]
}]
```

**工具**:`source.1688.search`、`source.1688.product`、`source.1688.shop`(`lib/1688.js`);素材落地与详情采集用 2.1 的 `POST /api/capture/start` + `GET /api/capture/status/<task_id>`;图片处理用 `lib/image.js`。

**人工确认点**:★ 候选勾选(Agent 排序,人选)。**供应商询价、议价、下单一律由人执行**,Agent 不做外站写操作。

**失败与降级**:
- 滑块/风控拦截(`lib/slider_solver.js` 失败)→ **BLOCK 该 brief**,提示人工介入。禁止用 `cache/` 里的历史报价当现价。
- 报价 `quoted_at` 距今 > 7 天 → 标 `stale_quote: true`,**禁止进入 N6**(利润门用旧价算 = 假数据)。
- `landed_cost_parts.unknown` 非空(如运费未知)→ N6 只能输出"成本区间下的利润区间",不输出点估计。

---

### N6.profit_gate — 利润门(纯本地规则)

**职责**:判断"按这个成本和这个价格带,能不能赚到目标利润"。纯本地计算 + SQLite 账本,**不调外部 AI、不调抖店官方 API**(`ops_engine.AI_POLICY` 硬约束)。

**输入**:`N5.candidates`、`N2.price_band`、`N0.cost_params`/`targets`、**`N12` 回流的实测参数(见下)**。

**工具**(全部是 2.1 sidecar 现有路由):
`POST /api/ops/sourcing-profit-gate`、`/api/ops/evaluate-product`、`/api/ops/apply-candidate-pricing`、`/api/ops/product-candidates`、`/api/ops/first-order-decision-matrix`、`/api/ops/net-profit-verification-matrix`、`/api/ops/profit-ladder-to-500`、`/api/ops/stock-plan`。

**输出**:
```
gate_result: [{
  candidate_id, verdict: pass|fail|blocked,
  sale_price_suggested, breakeven_price, unit_net_profit,
  orders_needed_for_daily_target,           # 对齐 N0.targets.daily_net_profit
  sensitivity: {refund_rate_breakeven, ad_ratio_breakeven},  # 哪个假设一崩就亏
  inputs_used: [{name, value, source, ev_id}],
  assumed_inputs: [...]                     # source==='assumed' 的清单
}]
```

**关键设计:把"猜的参数"变成"待验证的预测",而不是隐形默认值。**

`refund_rate`(退货率)、`ad_cost_ratio`(推广费占比)这两个参数决定利润门的成败,而新店拿不到可信的自家数据:
1. 优先:本店实测 —— `diagnosis.compass.transaction`、`store.finance.settlement`、`store.aftersale.count`。**但 `scope=shop_metric`,样本 < 100 时 `canDriveDecision=false`,不得使用**。
2. 次选:行业基准 —— `compass.market.benchmark`、`compass.market.index_range` 的广告费占比档(实测背景已给出同行 9~14% 的量级),标 `source:'benchmark'`。
3. 再次:人工填,标 `source:'assumed'`。
4. **无论 2 还是 3,都必须往 `Hypothesis.predictions` 追加一条:**
   `{kind:'metric', metric_tool_id:'store.finance.settlement', field_path:'refund_rate', op:'<=', threshold: 假设值×1.3, precondition:{min_sample:100}, hard:false}`
   这样 N12 会去验它,而不是让它永远当一个没人检查的默认值。

**失败与降级**:
- `price_band = null` 或 `stale_quote` → `verdict: blocked`,给出**具体缺什么**,不给猜测利润。
- `landed_cost_parts.unknown` 非空 → 输出利润**区间**并标 `reliable:false`,允许人工看,但 `verdict` 只能是 `blocked`,不能 `pass`。

---

### N7.candidate_lock — 候选定档与假设冻结

**职责**:人工拍板选定候选,并**冻结假设的预测集**。这是回流验证能成立的唯一前提。

**输入**:`N6.gate_result`、`N2.Hypothesis`。

**输出**:`locked_candidate`、`Hypothesis.status = 'active'`、`frozen_at`、`predictions` 写入 `X4.hypothesis_ledger` 并置为**只读**。

**人工确认点**:★ 拍板。确认页必须显示:三元档位、缺失项、假设的每条预测与阈值、`observability.verifiable`(若为 false 要二次确认)。

**不可逆性**:冻结后 `predictions` 不可编辑,只能"作废并新建 version"(旧版记 `superseded_by`)。**允许修改已冻结的预测 = 允许事后编故事,整个闭环就废了。**

---

### N8.asset_build — 素材与标题生产(可与 N9a/N9b 并行)

**职责**:产出主图、详情图、标题、卖点文案。**不做**发布。

**输入**:`N7.locked_candidate`、`N4.query_terms`(尤其 `audience_scene` 词)、`N9a.listing_schema`、`N5.media`。

**工具**:`src/professional_title_generator.py`、`src/title_engine.py`、`src/people_goods_scene.py`;`POST /api/ops/material-gap-plan`、`/api/ops/conversion-asset-pack`、`/api/ops/detail-conversion-audit`;`GET /api/ops/no-brand-title-audit`、`POST /api/ops/no-brand-remediation-plan`;图片 `lib/image.js` + `photoshop-plugin`。

**输出**:
```
title: {text, term_provenance: [{term, from_hyp_keyword_set:bool, ev_id}], audit: {...}}
main_images: [{path, role, source_offer_id, brand_scrubbed:bool}]
detail_pack: {...}
selling_points: [{text, backed_by: 'spec'|'supplier_claim'|'inference'}]
material_gaps: [...]
```

**约束**:标题选词**必须来自 `Hypothesis.keyword_set` 或 `N4.query_terms`**,每个词标注出处。凭空造词=断了假设与结果的因果链,N12 就无法归因。

**人工确认点**:★ 主图定稿、标题定稿(合规、版权、观感均非数据可判)。

**失败与降级**:素材不全**不阻塞本节点**(输出 `material_gaps`),但在 `N9b` 预检里变成硬阻塞项(缺主图不能发)。

---

### N9a.schema_prep — 类目属性与合规准备(并行,且有一条早期边指向 N4)

**职责**:取类目、属性 schema、SKU 规格、运费模板、资质要求。**不做**填值。

**输入**:`N0`(店铺)、`N2.product_spec`(粗类目)。

**工具**:`compass.product.category_tree`、`store.product.predict_category`、`store.product.schema`、`store.spec.list`、`store.freight.list`、`store.qualification.query`、`store.qualification.brand_list`(用于确认无品牌路径);2.1 侧 `src/enhanced_category_selector.py`、`src/category_attr_suggester.py`。

**输出**:`listing_schema {category_id, category_path, required_attrs[], optional_attrs[], sku_dimensions[], freight_template_options[], qualification_required[]}`。

**失败与降级**:schema 拉不到 → **BLOCK N9b/N10**。凭记忆或凭上一个商品的属性去填 = 典型的"看起来可用"。运费模板必须从 `freight_template_options` 里由人选,**任何写死的 template_id 视为缺陷**。

---

### N9b.listing_assemble — 上架包组装与预检

**职责**:把候选 + 素材 + schema 组装成一个完整上架包,跑安全预检。**不发布**。

**输入**:`N7`、`N8`、`N9a`。

**工具**:`POST /api/ops/publish-preflight-safety`、`/api/ops/upload-main-video-preflight`、`/api/ops/save-edit-human-gate`;定价 `src/smart_pricing_engine.py` + `/api/ops/apply-candidate-pricing`;库存 `/api/ops/stock-plan`。

**输出**:`listing_package{...}` + `preflight: [{check, pass, detail, blocking:bool}]`。

**失败与降级**:任一 `blocking:true` 未过 → BLOCK。预检项至少含:类目正确、必填属性齐全、无品牌合规、主图齐全、SKU 价格 ≥ `breakeven_price`、运费模板已选(非默认)、库存与 `stock_plan` 一致。

---

### N10.publish — 发布上架 ★不可逆

**职责**:执行发布。**这是整条 DAG 唯一对外产生持久后果的写节点**(N13 除外)。

**输入**:`N9b.listing_package`。

**工具**:
- 主路径:2.1 的 DOM 发布流水线(类目/属性/SKU/价格库存/主图/运费模板/无品牌)。
- 数据层路径:`store.product.upload_image` → `store.product.create_draft` → `store.product.launch`。这三个都在 `lib/approval-gate.js` 的 `WRITE_TOOLS` 里,**默认 dry-run**,`execute:true` 需要审批回执(`riskLevel: L4_STORE_HIGH`)。

**人工确认点**:★ **逐项预检签核**。人看到的是 `preflight` 全表 + `diff_digest`,签核后生成 `approval_receipt{who, when, package_hash}`。

**输出**:
```
publish_receipt {product_id, published_at, package_hash, approval_receipt_id}
hypothesis_binding {hyp_id, product_id, bound_at}   # ★ 回流验证的接缝,写进 X4 账本
```

**不可逆性与幂等**:
- `create_draft` 可重(草稿可删)。**`launch` 不可逆**:`store.product.delist` 只回滚上架状态,不回滚曝光历史与商品权重。
- 防重:以 `package_hash` + `hyp_id` 作幂等键。同一 hash 已有 `product_id` 时**拒绝再次 launch 并返回已有 id**,不是"再发一个"。

---

### N11.cold_observe — 冷启动观测(定时,只读)

**职责**:按日采集商品上线后的数据。**不下结论**。

**输入**:`N10.hypothesis_binding`、`N7.frozen predictions`(决定要采哪些字段)。

**工具**:`compass.product.rank`、`compass.search.source`、`diagnosis.compass.product_analytics`、`diagnosis.compass.traffic_source`、`compass.search.industry_shop_rank`、`compass.market.index_range`、`compass.product.channel_cards`、`store.order.count`、`store.finance.settlement`、`store.aftersale.count`。

**输出**:`observation_series: [{date, metrics{...}, states{...}, sample_size, ev_id[]}]`(每日一条,全部带 `snapshot_id`)。

**新品样本量的正面处理(不是绕过,是承认)**:
新品曝光小 → 所有 `scope=shop_metric` 的字段 `canDriveDecision=false`。所以冷启动期的判据**建在 SHOP_STATE 上**,这正是 `data-contract` 里 SHOP_STATE 的定义("与样本量无关,曝光为 0 也成立"):
- 是否出现在 `compass.search.source` 的目标词里(被收录)
- `compass.product.rank` 里是否出现 `rank_num`
- `compass.market.index_range` 的 `self_bucket_idx` 是否移动
- 类目挂载、属性完备度是否正确

**失败与降级**:某日采集失败 → 该日缺失,序列不插值。连续缺失 ≥3 天 → N12 的 `window_days` 顺延并记 `observation_gap`。

---

### N12.adjudicate — 假设裁决 ★回流验证核心

**职责**:用冻结的预测比对实测,判定假设成立/证伪/无法判定,并**把失败定位到 DAG 的具体节点**。

**输入**:`N11.observation_series`、`N7` 冻结的 `Hypothesis`、**`N1'`(同期重新采集的市场数据,作对照组)**。

**裁决算法(顺序不可调换)**:

```
1. 逐条 Prediction:
   1.1 检查 precondition
       - kind='metric' 且 sample_size < 100  → inconclusive_insufficient_sample
       - 数据源不可得 / observation_gap 超限  → inconclusive_no_data
       - kind='state' 不检查样本量
   1.2 满足前提 → 比 actual vs threshold → met / not_met

2. 检查 Falsifier:任一触发 → 直接进入第 4 步归因

3. 假设级判定:
   全部 hard=true 的 prediction met            → confirmed
   任一 falsifier 触发                          → refuted(待归因确认)
   存在 inconclusive 且无 falsifier 触发        → inconclusive
   其余                                         → partially_met

4. 归因分离(★ 这才是回流验证的价值)
```

**归因决策表**(把失败定位到节点):

| 观测事实(字段) | 归因 | 假设裁决 | 重入哪个节点 |
|---|---|---|---|
| 目标词未出现在 `compass.search.source`;或 `compass.product.rank` 无 `rank_num` | **执行问题:未被收录**(类目/属性/标题) | `inconclusive`(机会根本没被测到) | `N9a` → `N8` → `N13` 改标题 |
| 已收录,`product_show_ucnt` 有量但点击率显著低于 `compass.market.index_range` 同档 | **素材问题** | `inconclusive` | `N8` |
| 点击正常,支付转化低于同档 | **价格/详情/评价问题** | `inconclusive`(或 `partially_met`) | `N13` + `N6` 重算 |
| 一切正常但成交量未达门槛,**且** N1' 显示同期该词 `pay_amt__ratio` 下滑 / `industry_shop_rank` 同类目普遍下滑 | **市场问题** | `refuted`(机会假设不成立) | `N2`(下一轮) |
| 一切正常、同期市场稳定、成交仍未达门槛 | **机会假设本身错**(需求不存在或竞争被低估) | `refuted` | `N2` + 修正 `C_proxy` |
| `observability.verifiable === false` | — | 强制 `inconclusive` | 提示"这个窗口本来就测不出来" |

**对照组的必要性**:第 4 步必须重跑 `N1`(新 date)拿同期市场数据。没有对照组,就分不清"我做得差"和"整个类目在跌"——这是把单向流水线变成闭环的关键一环,也是 `N12` 有多个上游的原因。

**输出**:
```
Adjudication {
  adj_id, hyp_id, adjudicated_at, revision,      # append-only,改判新增 revision
  per_prediction: [{pred_id, actual, actual_ev_id, verdict, reason}],
  hypothesis_verdict: confirmed|refuted|inconclusive|partially_met,
  attribution: {layer, evidence[], confidence},
  market_control: {tool_id:'compass.search.industry_rank', date, delta_ratio},
  next_actions: [{type:'rerun_node', node_id, reason, expected_cost}],
  parameter_feedback: [{param:'refund_rate', measured, was_assumed, ev_id}]  # ★回流给 N6
}
```

**参数回流**:`parameter_feedback` 把实测的退货率/推广费占比写回 `N0.cost_params`(标 `source:'measured'`),下一轮 `N6` 就不再靠 benchmark。**但只有 `sample_size >= 100` 才允许升格为 measured**,否则仍是 assumed。

**人工确认点**:★ 裁决复核。`refuted` 意味着放弃一条路线(有成本),必须人看过归因证据后确认。

---

### N13.ops_loop — 运营动作闭环

**职责**:把 N12 的 `next_actions` 变成可执行的日常动作,并保证**每个动作都绑定一个可验证的子假设**。

**工具**:`POST /api/ops/daily-plan`、`/api/ops/daily-review`、`/api/ops/search-conversion-work-package`、`/api/ops/conversion-experiment-plan`、`/api/ops/execution-queue`、`/api/ops/post-save-conversion-monitor`、`/api/ops/reconcile-strategy-actions`、`/api/ops/profit-ramp-plan`、`/api/ops/portfolio-path-to-500`;写操作走 `store.product.batch_edit`、`store.product.edit_draft`、`store.promotion.coupon_create`(均在 `WRITE_TOOLS`)。

**硬规则**:**任何运营动作必须先创建一个 sub-Hypothesis**(带预测与窗口),否则不允许执行。改标题 → "预测:14 天内新词进入 `compass.search.source`";改价 → "预测:21 天内转化率提升 x% 且 `unit_net_profit` 不低于 y"。没有预测的动作 = 不可验证的动作 = 闭环断裂。

**人工确认点**:★ 每一个写动作单独确认(approval-gate 默认 dry-run)。

---

## 3. 为什么是 DAG,不是线性流水线

### 3.1 并行(同层无依赖)

- **N1 内部**:9 个只读工具彼此独立,可并发(受平台限流约束)。
- **N8 ‖ N9a ‖ N9b前置**:素材生产与类目 schema 准备互不依赖,同时进行;人工询价(N5 之后的线下动作)也与这两者并行。
- **多机会 / 多候选 fan-out**:N3 出 2 条假设 → 各自独立走 N4~N12,互不阻塞。这是"多试几个"的结构基础,线性流水线做不到。
- **N11 是定时长跑节点**,与 N13 的日常动作并行运行。

### 3.2 多上游(fan-in,真正让它不是链的原因)

| 节点 | 上游 | 说明 |
|---|---|---|
| `N4` | N3(假设) + **N9a(类目属性)** + N0(店铺目标) | 类目必填属性在**选品之前**就要约束规格,否则选到填不满属性的货。这条 `N9a → N4` 的**早期跨层边**是线性流程里最常被漏掉的 |
| `N6` | N5(成本) + N2(价格带) + N0(成本参数) + **N12↺(实测参数)** | 利润门同时需要供给侧、需求侧、店铺侧三路输入 |
| `N9b` | N7 + N8 + N9a | 三路汇聚 |
| `N12` | N11(本店观测) + N7(冻结预测) + **N1'(同期市场对照)** | 没有第三路对照就无法归因 |

### 3.3 反馈边如何保持无环

`N12 → N2/N4/N6/N8` 看起来是环,实际不是:**反馈边跨 run 实例**。`N12` 输出 `next_actions[{rerun_node}]`,由调度器创建**新的 `run_id`(或新的 `node_run_id`)**,新节点实例的上游指向旧实例的 `adj_id`。在"节点实例"这一层,图始终无环;在"节点类型"这一层看到的环,是多轮迭代,不是循环依赖。

假设账本同理:`Hypothesis` 用 `version` + `superseded_by` 做单向链,永不原地修改。

---

## 4. 重入(rerun)代价与不可逆性

| 节点 | 幂等 | 重跑代价 | 不可逆点 |
|---|---|---|---|
| N0 | 是 | 低 | 无 |
| N1 | 按 `date` 幂等(换 date = 新数据,旧快照保留) | 低,但吃平台限流/风控额度 | 无 |
| N2 | 是(同输入同输出,除非权重配置改) | 极低(纯计算) | 无 |
| N3 | 是 | 低 | 人工短名单选择被版本化记录 |
| N4 | 是 | 低 | `term_mapping` 人工定稿版本化 |
| N5 | **否**(报价随时变) | **中**:1688 风控/滑块,失败率高 | 无 |
| N6 | 是(纯本地) | 极低 | 无 |
| N7 | 人工 | — | **半不可逆**:冻结 predictions,只能作废重建版本 |
| N8 | 是 | 中(人工审美 + 素材制作时间) | 本地文件版本化,可回滚 |
| N9a | 是 | 低 | 无 |
| N9b | 是 | 低 | 无 |
| **N10** | **否** | 高 | **`launch` 不可逆**。`create_draft` 可重;重复 launch 会产生重复商品 → 必须靠 `package_hash + hyp_id` 幂等键拒绝 |
| N11 | 按日期幂等 | 低 | 无 |
| N12 | 是(同数据同裁决) | 低 | **裁决 append-only**,改判必须新增 revision 并写明理由 |
| N13 | **否** | 中~高 | 改价/发券/改标题**对外可见且影响权重**,不可逆 |

**级联失效规则**:某节点产生新 `node_run_id` 后,所有下游 `NodeResult` 标记 `stale`(因为它们的 `upstream[].node_run_id` 已过期)。**不自动级联重跑**——自动级联会一路冲到 N10/N13 的写操作。stale 只是一个提示,由人决定重跑哪一段。

---

## 5. 三个专项说明

### 5.1 机会→选品的交接,一句话总结

一个"机会"是**一组带证据的词 + 一个价格带 + 一个竞争档位**;它变成选品条件靠三次翻译:
1. **词的翻译**:抖音的人群/场景词剥离到素材侧,只把品类+材质词送去 1688(人工定稿);
2. **价格带 → 成本天花板**:`ops_engine` 反解 `max_landed_cost`,拿不到价格带就阻塞而不是猜倍率;
3. **类目 schema → 规格硬条件**:必填属性反过来约束"能选什么货"。

三者任一缺失,brief 就是 `degraded` 且不许进利润门。

### 5.2 回流验证,一句话总结

**预测必须在上架前冻结**,裁决必须**三分**(confirmed / refuted / **inconclusive**),且必须带**同期市场对照组**做归因。没有对照组就分不清"我差"和"市场差";没有 inconclusive 这一档,样本不足会被强行判成结论,那就是最危险的假数据。

### 5.3 需要被系统自己检验的元假设(诚实清单)

这些是设计里的启发式,**不是已验证的事实**,应作为 `meta_hypotheses` 由多轮 N12 结果检验:
- `E_ratio >= E_base × 1.2` 的长尾词比头部词更适合新店 —— 待多轮验证;
- `rank <= 10` 剔除头部词的规则 —— 阈值 10 是拍的,应改为按 `search_show_ucnt_ratio` 分位;
- `window_days = 21` 的冷启动周期 —— 应由实测的首单时间分布替换;
- `C_top` 作为竞争代理是否与实际获客难度相关 —— 待验证;
- `compass.search.industry_rank` 能否取到长尾词 —— **未实测,是整个 N2 长尾策略的前置依赖,应优先跑一次实测确认**。
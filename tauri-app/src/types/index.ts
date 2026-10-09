/**
 * Shared frontend types.
 */

export interface Product {
  id: number;
  name: string;
  update_time: string;
}

export interface SKU {
  path: string;
  name: string;
  price: number | "";
  url?: string;
  sku_id?: string;
  sku_key?: string;
  spec_values?: Record<string, string>;
  image_source?: string;
  price_source?: string;
}

export interface ProductDetail {
  id: number;
  name: string;
  title: string;
  remark: string;
  repo: number;
  clazz: number | null;
  content: SKU[];
  path?: string;
  white_bg_path?: string;
  update_time?: string;
}

export interface ProductMediaReceipt {
  path: string;
  role: "main" | "sku" | "detail";
  name: string;
  sha256: string;
  status: "located" | "uploaded_unlocated";
  folder_path: string[];
  observed_at: string;
  content_matches: boolean;
}

export interface ProductMediaEntry {
  name: string;
  path: string;
  kind: "folder" | "image" | "file" | "blocked";
  size: number;
  modified_at: string;
  receipts: ProductMediaReceipt[];
  error: string;
}

export interface WhiteBgSelection {
  /** 当前商品目录内的相对路径；空字符串表示自动选择 */
  path: string;
  valid: boolean;
  error: string;
}

export interface WhiteBgSelectionResult {
  record_id: number;
  selection: WhiteBgSelection;
  update_time: string;
  record_revision: string;
}

export interface ProductMediaListing {
  record_id: number;
  product_name: string;
  path: string;
  parent: string;
  account_profile: string;
  platform: TargetPublishPlatform | null;
  entries: ProductMediaEntry[];
  white_bg_selection?: WhiteBgSelection;
  total: number;
  offset: number;
  limit: number;
}

export interface ApiResponse<T = unknown> {
  success: boolean;
  msg?: string;
  message?: string;
  data?: T;
}

export type TargetPublishPlatform = "douyin" | "taobao";

export interface ProductSaveResult {
  id: number;
  update_time: string;
  record_revision: string;
}

export interface ProductSaveOptions {
  recordId?: number;
  publishPlatform?: TargetPublishPlatform;
  accountProfile?: string;
}

export interface TaobaoPublishPayload {
  record_id: number;
  account_profile?: string;
  overrides?: {
    title?: string;
    guide_title?: string;
    category_path?: string;
    item_price?: number | null;
    total_stock?: number | null;
    freight_template_name?: string;
    skus?: Array<{
      index: number;
      price: number | null;
      stock: number | null;
    }>;
  };
}

export interface TaobaoReadiness {
  platform: "taobao";
  /** 流水线模式：资料准备 + 自动填表 + 上传，**提交前截停**。 */
  mode: "automated_pipeline";
  /** 由后端按真实状态推导，**不再硬编码 false**。 */
  automatic_publish_ready: boolean;
  publish_route_ready: boolean;
  dom_write_ready: boolean;
  protocol_write_ready: boolean;
  implemented_stages: string[];
  unimplemented_stages: string[];
  incomplete_stages: string[];
  /** **未在真实页面跑通**的阶段；与「未实现」是两件事。 */
  live_unverified_stages: string[];
  /** ⚠️ 只关 mtop 协议路线，DOM 路线不依赖。 */
  blocked_fields: string[];
  blocked_fields_note: string;
  /** ⚠️ 这一条才关 DOM 路线。 */
  blocked_selectors: string[];
  blocked_selectors_note: string;
  message: string;
}

export interface TaobaoPreparedSku {
  index: number;
  name: string;
  price: number | null;
  stock: number | null;
  image_path: string;
}

export interface TaobaoPreparationCheck {
  field: string;
  label: string;
  status: "ok" | "warning" | "missing";
  message: string;
}

export interface TaobaoPreparation {
  platform: "taobao";
  account_profile: string;
  record_id: number;
  record_name: string;
  title: string;
  guide_title: string;
  category_path: string;
  item_price: number | null;
  total_stock: number | null;
  freight_template_name: string;
  skus: TaobaoPreparedSku[];
  assets: {
    main: string[];
    detail: string[];
    sku: string[];
    white_bg: string;
  };
  checks: TaobaoPreparationCheck[];
  can_export: boolean;
  /** 与 `TaobaoReadiness` 同源：由后端按真实状态推导，**不再硬编码 false**。 */
  automatic_publish_ready: boolean;
}

export interface TaobaoPacketExport {
  platform: "taobao";
  account_profile: string;
  record_id: number;
  packet_dir: string;
  manifest_path: string;
  sku_csv_path: string;
  files_count: number;
  message: string;
}

/**
 * 启动淘宝发布时随带的商品资料。
 *
 * ⚠️ **这是补上的一个真实缺口**：界面一直收集着标题/价格/库存/类目，
 * 却只用在「资料检查 / 导出资料包」上，`/api/taobao/publish/start` 只发
 * `record_id`——流水线因此永远在静态预检报「标题为空」。
 * 也就是说：**UI 收集的数据从来没有到达过发布流水线。**
 *
 * `skus[].spec_values` 必须由操作人**明确写出**（如 `尺码=M(37-41)`）；
 * 不许从 SKU 名字里拆——那是猜字段，项目红线明确禁止。
 */
export interface TaobaoProductRequest {
  title?: string;
  /** 导购标题。**选填**；实测表单上有这一行，以前填了不会被发布。 */
  guide_title?: string;
  /** 完整类目路径，用 `>` 分层。流水线要求与平台候选**精确相等**。 */
  category_path?: string;
  category_id?: string;
  /** 商品种类的搜索词；只用于平台类目搜索，不是平台类目 ID。 */
  category_keyword?: string;
  sku_mode?: "standard" | "custom";
  freight_template_name?: string;
  outer_id?: string;
  props?: Array<{ prop_name: string; value_name: string }>;
  skus?: Array<{
    /** 「属性名 → 属性值」，值必须是平台标准候选项里的原文。 */
    spec_values?: Record<string, string>;
    price?: number;
    stock?: number;
    /** 本地规格图片路径，服务端须与当前商品资产核对。 */
    image_path?: string;
  }>;
}

/** `/api/taobao/publish/start` 的返回。形状与抖店的 `/api/upload/start` 对齐。 */
export interface TaobaoPublishStartResult {
  task_id: string;
  /** 本次是不是校对模式（不写平台）。默认就是 true。 */
  dry_run: boolean;
  /** 是否在提交前截停。默认就是 true。 */
  stop_before_submit: boolean;
  fill_only?: boolean;
  /** 本次是否请求了「保存草稿」。**默认 false**——保存是写入，必须显式请求。 */
  save_draft?: boolean;
  /** 上架方式。空串表示走流水线默认值（放入仓库）。 */
  listing_mode?: string;
}

/**
 * 上架方式。取值必须是页面上**实测存在**的三个选项之一。
 *
 * ⚠️ **默认走 `放入仓库`，不是 `立刻上架`。** 页面的默认值是「立刻上架」——
 * 最危险的那个恰好是默认值，所以流水线刻意不跟随它：填完先进仓库，人复核后再上架。
 */
export type TaobaoListingMode = "立刻上架" | "定时上架" | "放入仓库";

/**
 * 淘宝发布任务。
 *
 * ⚠️ **`status === "succeeded"` 表示「流水线跑完了」，不表示「商品已上架」。**
 * 提交通道的成功特征尚未实证，所以后端固定返回 `publish_confirmed: false`，
 * 是否上架必须人工在卖家中心核对。展示时不要把这两件事合并。
 */
export interface TaobaoVisibleFormRequirements {
  known: boolean;
  scope: "visible_publish_rows_required";
  completePage: false;
  rowCount?: number;
  unownedRequiredCount?: number;
  required: Array<{
    label: string;
    hitCount: number;
    supportedReader: boolean;
    filled: boolean;
    valid: boolean | null;
    reader?: string;
    reason?: string;
  }>;
  reason?: string;
  coverageLimits?: string[];
}

export interface TaobaoFormVerification {
  status: "not_verified" | "failed" | "partial" | "complete";
  complete: boolean;
  reason: string;
  visible_form_requirements?: TaobaoVisibleFormRequirements | null;
  required_field_coverage: {
    known: boolean;
    completePage: boolean;
    scope: string;
    rowCount?: number;
    checkedCount?: number;
    required?: Array<{ label: string; hitCount: number; supportedReader: boolean }>;
    checked?: Array<{ label: string; value: string }>;
  } | null;
}

export interface TaobaoPublishTask {
  task_id: string;
  platform: "taobao";
  account_profile: string;
  record_id: number | null;
  record_name: string;
  status: "pending" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number;
  message: string;
  current_step?: string | null;
  steps: Array<{
    name: string;
    status: string;
    elapsed_ms?: number;
    summary?: string;
    error_code?: string;
    [key: string]: unknown;
  }>;
  error?: string | null;
  blockers?: Array<{ code: string; field?: string; detail: string }>;
  result?: {
    success?: boolean;
    stopped_before_submit?: boolean;
    data?: { form_verification?: TaobaoFormVerification; [key: string]: unknown };
    [key: string]: unknown;
  } | null;
  dry_run: boolean;
  stop_before_submit: boolean;
  /** 永远为 false，直到人工核对确认上架。 */
  publish_confirmed: boolean;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

// 以下 Ops* 运营闭环类型当前没有前端消费方（实际消费方是 mcp-server/core.js），有意保留待运营面板 UI 落地。
export interface OpsAiPolicy {
  external_ai_disabled: boolean;
  decision_source: string;
  blocked_providers: string[];
}

export interface OpsBrowserSnapshot {
  status?: string;
  has_browser?: boolean;
  url?: string;
  title?: string;
  source?: string;
  error?: string;
}

export interface OpsShopMetrics {
  snapshot_date?: string;
  net_profit?: number;
  net_profit_verified?: boolean;
  gross_sales?: number;
  orders_count?: number;
  refund_amount?: number;
  after_sale_amount?: number;
  promotion_cost?: number;
  experience_score?: number;
  source?: string;
  status?: string;
  notes?: string;
  raw_payload?: Record<string, unknown>;
}

export interface OpsDailySnapshot extends OpsShopMetrics {
  id: number;
  target_net_profit: number;
  raw_payload_json?: string;
  created_at?: string;
}

export interface OpsDailyPlan {
  snapshot_date: string;
  target_net_profit: number;
  net_profit: number;
  net_profit_verified: boolean;
  profit_gap: number | null;
  orders_count: number;
  gross_sales: number;
  promotion_cost: number;
  refund_amount: number;
  after_sale_amount: number;
  experience_score?: number;
  ready_products: number;
  blocked_products: number;
  low_stock_products: number;
  actions: string[];
  ai_policy: OpsAiPolicy;
}

export interface OpsSyncShopMetricsPayload {
  metrics?: OpsShopMetrics;
  source?: string;
  browser?: OpsBrowserSnapshot;
  audit_metrics?: Array<Record<string, unknown>>;
  raw_payload?: Record<string, unknown>;
}

export interface OpsSyncShopMetricsResult {
  synced: boolean;
  snapshot?: OpsDailySnapshot;
  daily_plan?: OpsDailyPlan;
  browser?: OpsBrowserSnapshot;
  audit_rows?: Array<Record<string, unknown>>;
  ai_policy: OpsAiPolicy;
}

export interface OpsProductCandidate {
  record_id: number;
  title: string;
  sku_count: number;
  sku_price_min: number;
  sku_price_max: number;
  goods_cost_source: string;
  goods_cost: number;
  recommended_sale_price: number;
  target_net_margin: number;
  evaluation: Record<string, unknown>;
  stock_plan: Record<string, unknown>;
  warnings: string[];
}

export interface OpsDailyReview {
  snapshot_date: string;
  target_net_profit: number;
  goal_status: "achieved" | "below_target" | "not_verified";
  verified_net_profit_achieved: boolean;
  daily_plan: OpsDailyPlan;
  top_candidate?: OpsProductCandidate | null;
  candidate_count: number;
  actions: string[];
  ai_policy: OpsAiPolicy;
}

export interface OpsCandidatePricingApplyResult {
  dry_run: boolean;
  saved: boolean;
  record: Record<string, unknown>;
  candidate: OpsProductCandidate;
  pricing: {
    sale_price: number;
    updated_count: number;
    changes: Array<Record<string, unknown>>;
  };
  current_sku_prices: Array<{
    name?: string;
    price?: number;
    ops_goods_cost?: number;
  }>;
  ai_policy: OpsAiPolicy;
}

export interface ProductListResponse extends ApiResponse {
  products: Product[];
}

export interface ProductDetailResponse extends ApiResponse {
  data: ProductDetail;
}

export interface TitleSuggestion {
  title: string;
  confidence: number;
  reasoning: string;
  tags: string[];
  character_count: number;
}

export interface PricingResult {
  sku_name: string;
  sku_path?: string;
  quantity: number;
  sock_cost: number;
  fixed_costs: number;
  per_unit_extra: number;
  percentage_cost: number;
  total_cost: number;
  suggested_price: number;
  profit: number;
  profit_margin: number;
  confidence?: number;
  method?: string;
}

export interface PricingStatistics {
  average_price: number;
  average_margin: number;
  total_skus: number;
  min_price: number;
  max_price: number;
}

export interface PricingConfigUsed {
  target_gross_margin: number;
  fixed_costs: number;
  percentage_costs: number;
  cost_items_count: number;
}

// 由采集端保存并直接交给发布端；共同编辑页面不需要新增配置。
export interface CapturedProductAttributes {
  version: 1;
  source: "visible_product_parameters_v1";
  status: "captured" | "not_found" | "disabled";
  attributes: Array<{ name: string; value: string }>;
}

export interface CaptureStatus {
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  message: string;
  error_code?: string;
  can_retry?: boolean;
  user_action_required?: boolean;
  action_hint?: string;
  platform?: string;
  capture_mode?: string;
  current_step?: string;
  result?: {
    title: string;
    sku_count: number;
    captured_attributes?: CapturedProductAttributes;
  };
}

export interface CaptureHistoryTask {
  task_id: string;
  url: string;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  message: string;
  error_code?: string;
  can_retry?: boolean;
  user_action_required?: boolean;
  action_hint?: string;
  platform?: string;
  capture_mode?: string;
  created_at?: string;
}

export interface UploadStepInfo {
  name: string;
  status: "running" | "ok" | "failed";
  elapsed_ms: number;
  summary: string;
}

export interface UploadTaskSummary {
  task_id: string;
  record_id: number;
  record_name: string;
  status: "pending" | "running" | "success" | "failed" | "cancelled";
  progress: number;
  message: string;
  current_step?: string;
  steps?: UploadStepInfo[];
  error?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface UploadStartOptions {
  /** 上传只消费已确认保存的当前商品版本。 */
  expectedRecordRevision?: string;
  /** 发起动作时的账户快照，后端用于拒绝已切换账户的过时请求。 */
  accountProfile?: string;
  /** true = 走到提交前停下，不发布；false = 真实提交上架 */
  stopBeforeSubmit?: boolean;
  /**
   * 真实发布前的人工确认。后端要求 stopBeforeSubmit=false 时必须同时带上它，
   * 否则拒绝执行——发布不可撤销，必须有一次明确的人点过头。
   */
  confirmFinalPublish?: boolean;
}

export interface SettingsPricingConfig {
  target_gross_margin: number;
}

export interface CostItem {
  id: string;
  name: string;
  cost_type: "fixed" | "per_unit" | "percentage";
  value: number;
  description: string;
}

export interface ModelConfig {
  id: string;
  name: string;
  provider: string;
  api_key: string;
  api_base: string;
  model_name: string;
  enabled: boolean;
}

export interface MaterialComposition {
  material: string;
  percentage: number;
}

// 采集方式：dom = 读浏览器渲染数据；protocol = 拦截网络请求（预览版）
export type CaptureMode = "dom" | "protocol";

// 采集偏好：分平台独立保存。1688 和 淘宝/天猫 是两个不同平台，互不交叉。
export interface CapturePreferences {
  alibaba_1688_mode: CaptureMode;
  taobao_tmall_mode: CaptureMode;
}

export interface AutomationConfig {
  shipping_template: string;
  shipping_templates: string[];
  material_compositions: MaterialComposition[];
  material_options?: string[];
  wash_label_tag_image_path?: string | null;
  runtime_category_keyword?: string | null;
  runtime_matrix_keywords?: string | null;
  publish_mode?: string;  // "protocol" | "official" | "dom"
  /** 旧字段：单一采集方式，保留兼容，不再使用 */
  capture_mode?: string;
  /** 采集偏好：分平台独立配置（1688 和 淘宝/天猫 是两个独立平台，互不交叉） */
  capture_preferences?: CapturePreferences;
  /** 提交方式：publish 直接提交上架，stop 全部填好后停下不提交 */
  publish_submit_mode?: PublishSubmitMode;
  /** 后端规范化后的值，只读，不要回传 */
  publish_submit_mode_effective?: PublishSubmitMode;
}

/** 历史配置里可能存着 auto，后端按 publish 处理 */
export type PublishSubmitMode = "stop" | "publish";

/**
 * 登录状态一律来自实测，两个平台走同一套取值。
 *
 * 注意平台差异会导致**不同的未登录原因**：抖音可能没有抖店页面（`no_fxg_tab`），
 * 淘宝可能没有淘宝/天猫页面（`no_taobao_tab`）。这两种都表示「浏览器里没有
 * 可用来判定身份的页面」，不是「已确认没登录」。
 *
 * `manual` 是历史值：旧版后端对淘宝会返回它，表示「本地绑定、不做验证」。
 * 新版后端不再返回；保留在联合类型里只是为了让老 sidecar 配新前端时能编译。
 */
export type ShopSessionStatus =
  | "manual"
  | "logged_in"
  | "logged_out"
  | "no_fxg_tab"
  | "no_taobao_tab"
  | "no_browser"
  | "unreachable"
  | "conflict";

export interface ShopSessionState {
  platform: TargetPublishPlatform;
  /** 当前选中的店铺目录名。它只是容器，不代表登录了哪个店 */
  active_profile: string;
  active_profile_label: string;
  profile_dir: string;
  /** 注册表里「上次看到的」店铺，与本次实测严格区分 */
  last_seen_shop_id?: string | null;
  last_seen_shop_name?: string | null;
  status: ShopSessionStatus;
  /** 本次实测到的**店铺** ID；读不到就是 null，不会有兜底值 */
  shop_id?: string | null;
  shop_name?: string | null;
  /** 本次实测到的**账户** ID（淘宝 `unb`）。与 shop_id 不是一回事 */
  account_id?: string | null;
  /** 会员名。淘宝的会员名与店铺名是两个不同的概念 */
  nick?: string | null;
  debug_address?: string | null;
  browser_source?:
    | "gui_page"
    | "reusable_browser"
    | "open_browser"
    | "taobao_seller_page"
    | "taobao_page"
    | "none";
  browser_user_data_dir?: string | null;
  page_url?: string | null;
  /** 实际使用的浏览器是否属于所选店铺目录；null 表示信息不足无法判断 */
  profile_match?: boolean | null;
  /** 这次实测来自哪份账号信息；后端会把选中项对齐到它 */
  owner_profile?: string | null;
  error?: string | null;
  /** 技术细节，仅用于排查，不要展示给用户 */
  detail?: string | null;
  observation?: "new" | "confirmed" | "changed" | "unknown";
  checked_at?: string;
}

export interface ShopProfile {
  platform: TargetPublishPlatform;
  profile_name: string;
  label: string;
  profile_dir?: string;
  created_at?: string | null;
  /** 上次实测到的**店铺** ID（抖店 shopId / 淘宝 shopId），不是当前登录状态 */
  shop_id?: string | null;
  shop_name?: string | null;
  /**
   * 上次实测到的**账户** ID。
   *
   * 只有淘宝用得上：淘宝的账户（`unb`）与店铺（`shopId`）是两个不同的东西，
   * 实测是 13 位 : 9 位。抖店两者同为店铺身份，这里是 null。
   */
  account_id?: string | null;
  last_seen_at?: string | null;
  seen_count?: number;
  is_active: boolean;
  /** 能否从列表移除。默认账户有历史记录时不行 */
  removable?: boolean;
  identity_source?: string;
}

export interface FreightTemplate {
  id: string;
  name: string;
  /** 所属店铺；平台通用项没有 */
  shop_id?: string | null;
  /** false 表示这是平台通用项（例如「包邮」），不属于任何店铺 */
  shop_scoped: boolean;
}

export interface ShopFreightTemplates {
  /**
   * `ok` 才表示**确实读到了**。
   *
   * ⚠️ `read_failed` / `need_publish_page` / `not_captured` 一律表示**没读到**——
   * 它们**不等于**「该店铺没有模板」，界面必须分开说。
   *
   * * `need_publish_page`：淘宝的模板下拉只在**发布表单**里，请先打开商品的发布页；
   * * `read_failed`：下拉展开了但一个选项都没有（结构变了或不是发布页）；
   * * `not_captured`：抖店那侧的旧状态；淘宝已改走 DOM，不再返回它。
   */
  status:
    | "ok"
    | "logged_out"
    | "no_fxg_tab"
    | "no_browser"
    | "unreachable"
    | "failed"
    | "conflict"
    | "not_captured"
    | "need_publish_page"
    | "read_failed"
    | "unavailable";
  templates: FreightTemplate[];
  /** 当前挂在发布表单上的模板名。读不到就是 null——**不兜底**。 */
  current?: string | null;
  shop_id?: string | null;
  shop_name?: string | null;
  error?: string | null;
  /** 技术细节，仅用于排查，不要展示给用户 */
  detail?: string | null;
}

export interface ShopSwitchResult {
  platform: TargetPublishPlatform;
  active_profile: string;
  profile_dir: string;
  previous_debug_address?: string | null;
  /** 浏览器启动结果，仅表示已打开，不代表登录或店铺身份已验证。 */
  browser_opened: boolean;
  browser_error?: string | null;
  debug_address?: string | null;
}

export interface Settings {
  pricing_config?: SettingsPricingConfig;
  cost_items?: CostItem[];
  model_configs?: ModelConfig[];
  // Legacy alias returned by older backend paths.
  model_apis?: ModelConfig[];
  automation_config?: AutomationConfig;
}


// ========== 白底图（语义抠图） ==========

/** 模型就绪状态。白底图模型约 1GB，不打进安装包，由运行数据目录提供 */
export interface WhiteBgModelStatus {
  ready: boolean;
  model_dir: string;
  matte_model: string;
  rembg_home: string;
  clip_dir: string;
  /** 缺失的文件清单，ready=false 时据此提示用户 */
  missing: string[];
  searched: string[];
}

/** 单个连通域的语义判定：是不是袜子，凭什么 */
export interface WhiteBgVerdict {
  label: number;
  kept: boolean;
  area_px: number;
  sock: number;
  shoe: number;
  other: number;
  margin: number;
  top_prompt: string;
  reason: string;
}

/** 单张图的处理结果。白底图可能被拒，1:1 规格图不会 */
export interface WhiteBgItem {
  source: string;
  name: string;
  white_ok: boolean;
  white_path: string;
  square_ok: boolean;
  square_path: string;
  /** 被拒时的机器可读原因：worn_source / no_sock_found / no_foreground / exception */
  code: string;
  message: string;
  warnings: string[];
  tilt_deg: number;
  /** false 表示方向不可信，本次没有转正（宁可不转也不转错） */
  tilt_confident: boolean;
  scene: Record<string, number>;
  verdicts: WhiteBgVerdict[];
  compose: Record<string, unknown>;
  seconds: number;
}

export interface WhiteBgOutcome {
  product_dir: string;
  ok: boolean;
  white_dir: string;
  square_dir: string;
  white_root: string;
  white_root_source: string;
  items: WhiteBgItem[];
  /** SKU 图全被拒时，为凑目录根白底图额外试过的主图 */
  fallback_items: WhiteBgItem[];
  seconds: number;
  message: string;
}

export interface WhiteBgTask {
  task_id: string;
  product_dir: string;
  record_id: number | null;
  record_name: string;
  status: "pending" | "running" | "success" | "failed";
  progress: number;
  message: string;
  current: string;
  total: number;
  done: number;
  result: WhiteBgOutcome | null;
  error: string | null;
  created_at?: string | null;
  finished_at?: string | null;
}

export interface WhiteBgFileEntry {
  path: string;
  name: string;
  size: number;
}

export interface WhiteBgListing {
  product_dir: string;
  white_root: string;
  white_images: WhiteBgFileEntry[];
  square_images: WhiteBgFileEntry[];
  report: {
    generated_at?: string;
    matte_model?: string;
    model_dir?: string;
    canvas?: number;
    fill_ratio?: number;
    outcome?: WhiteBgOutcome;
  } | null;
}

export interface WhiteBgStartOptions {
  recordId?: number;
  productDir?: string;
  matteModel?: string;
  /** 输出边长，默认 1440（1:1） */
  canvas?: number;
  /** 主体长边占画布的比例，默认 0.82 */
  fillRatio?: number;
  /** 是否转正，默认 true */
  deskew?: boolean;
  squareSize?: number;
  overwrite?: boolean;
}

export const CATEGORY_OPTIONS = [
  { value: 0, label: "船袜" },
  { value: 1, label: "短袜" },
  { value: 2, label: "中筒袜" },
  { value: 3, label: "长筒袜" },
  { value: 4, label: "袜套" },
] as const;

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
  price: number;
  url?: string;
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
  update_time?: string;
}

export interface ApiResponse<T = unknown> {
  success: boolean;
  msg?: string;
  message?: string;
  data?: T;
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
  stopBeforeSubmit?: boolean;
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
}

export interface Settings {
  pricing_config?: SettingsPricingConfig;
  cost_items?: CostItem[];
  model_configs?: ModelConfig[];
  // Legacy alias returned by older backend paths.
  model_apis?: ModelConfig[];
  automation_config?: AutomationConfig;
}

export const CATEGORY_OPTIONS = [
  { value: 0, label: "船袜" },
  { value: 1, label: "短袜" },
  { value: 2, label: "中筒袜" },
  { value: 3, label: "长筒袜" },
  { value: 4, label: "袜套" },
] as const;

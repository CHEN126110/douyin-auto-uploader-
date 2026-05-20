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
  created_at?: string;
}

export interface UploadTaskSummary {
  task_id: string;
  record_id: number;
  record_name: string;
  status: "pending" | "running" | "success" | "failed" | "cancelled";
  progress: number;
  message: string;
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

export interface AutomationConfig {
  shipping_template: string;
  shipping_templates: string[];
  material_compositions: MaterialComposition[];
  material_options?: string[];
  wash_label_tag_image_path?: string | null;
  runtime_category_keyword?: string | null;
  runtime_matrix_keywords?: string | null;
  publish_mode?: string;  // "protocol" | "official" | "dom"
}

export interface FxgRuntimeCategory {
  path?: string;
  leafId?: string;
  enable?: boolean;
  industry_status?: number;
}

export interface FxgRuntimeValueOption {
  value_id?: string;
  value_name?: string;
  disabled?: boolean;
}

export interface FxgRuntimeCategoryProperty {
  id: string;
  label: string;
  required?: boolean;
  optionCount?: number;
  optionPreview?: FxgRuntimeValueOption[];
  hasMeasureTemplates?: boolean;
}

export interface FxgRuntimeSpecAxis {
  id?: string;
  cp_id?: number;
  name: string;
}

export interface FxgRuntimeSkuColumn {
  key: string;
  label: string;
  required?: boolean;
  hidden?: boolean;
}

export interface FxgRuntimePublishControl {
  key?: string;
  label?: string;
  required?: boolean;
  optionCount?: number;
  optionPreview?: FxgRuntimeValueOption[];
  optionNames?: string[];
}

export interface FxgRuntimeFreight {
  ok: boolean;
  optionCount: number;
  options?: FxgRuntimeValueOption[];
  currentValue?: string;
  hasCurrentValue?: boolean;
  error?: string | null;
}

export interface FxgRuntimeSettingsReadiness {
  canRenderCategorySettings?: boolean;
  canRenderFreightSettings?: boolean;
  issues?: string[];
}

export interface FxgRuntimeOptionsFields<TSpecAxis = FxgRuntimeSpecAxis[]> {
  ok: boolean;
  category?: FxgRuntimeCategory;
  requiredCategoryProperties?: FxgRuntimeCategoryProperty[];
  specAxes?: TSpecAxis;
  skuColumns?: FxgRuntimeSkuColumn[];
  publishControls?: Record<string, FxgRuntimePublishControl>;
  freight?: FxgRuntimeFreight | null;
  settingsReadiness?: FxgRuntimeSettingsReadiness;
}

export interface FxgRuntimeOptions extends FxgRuntimeOptionsFields {}

export interface FxgRuntimeOptionsMatrixEntry extends FxgRuntimeOptionsFields<string[]> {
  keyword: string;
  error?: string;
}

export interface FxgRuntimeOptionsMatrix {
  ok: boolean;
  categoryKeywords: string[];
  entries: FxgRuntimeOptionsMatrixEntry[];
}

export type FxgRuntimeOptionsResult = FxgRuntimeOptions | FxgRuntimeOptionsMatrix;

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

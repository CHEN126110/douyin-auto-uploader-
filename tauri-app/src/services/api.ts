/**
 * API服务层
 * 与Python后端通信 + Tauri命令调用
 */

import axios from "axios";
import { invoke } from "@tauri-apps/api/core";
import type {
  ApiResponse,
  Product,
  ProductDetail,
  ProductMediaListing,
  ProductSaveResult,
  TitleSuggestion,
  PricingResult,
  PricingStatistics,
  CaptureStatus,
  CaptureHistoryTask,
  UploadTaskSummary,
  UploadStartOptions,
  TaobaoPublishPayload,
  TaobaoReadiness,
  TaobaoPreparation,
  TaobaoPacketExport,
  TaobaoPublishStartResult,
  TaobaoProductRequest,
  TaobaoListingMode,
  TaobaoPublishTask,
  TargetPublishPlatform,
  Settings,
  ShopSessionState,
  ShopProfile,
  ShopSwitchResult,
  ShopFreightTemplates,
  WhiteBgModelStatus,
  WhiteBgSelectionResult,
  WhiteBgTask,
  WhiteBgListing,
  WhiteBgStartOptions,
} from "@/types";

// 后端URL配置
// 注意: 如果端口5000被占用，使用5001
const BACKEND_URL = "http://127.0.0.1:5001";

export function productMediaImageUrl(recordId: number, path: string, modifiedAt: string, preview = false) {
  const query = new URLSearchParams({ path, version: modifiedAt, size: preview ? "preview" : "thumb" });
  return `${BACKEND_URL}/api/products/${recordId}/media/image?${query}`;
}

// 创建axios实例
const http = axios.create({
  baseURL: BACKEND_URL,
  timeout: 60000,
  headers: {
    "Content-Type": "application/json",
  },
});

type CaptureStartPayload = {
  task_id?: string;
  url?: string;
};

type CaptureStartResponse = ApiResponse<CaptureStartPayload> & {
  task_id?: string;
  url?: string;
};

function normalizeCaptureStartResponse(
  response: CaptureStartResponse
): CaptureStartResponse {
  const taskId = response?.data?.task_id || response?.task_id;
  const resolvedUrl = response?.data?.url || response?.url;

  if (!taskId) {
    return response;
  }

  return {
    ...response,
    task_id: taskId,
    url: resolvedUrl,
    data: {
      ...(response?.data || {}),
      task_id: taskId,
      url: resolvedUrl,
    },
  };
}

function shouldLogApiError(error: unknown): boolean {
  const config = (error as { config?: { __silentError?: boolean } })?.config;
  return !config?.__silentError;
}

// 响应拦截器
http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (shouldLogApiError(error)) {
      console.error("API请求错误:", error);
    }
    return Promise.reject(error);
  }
);

// ========== Tauri 命令 ==========

// 后端生命周期（启动/停止/状态）由 Rust 壳层独占管理，前端不提供任何拉起或停止封装。
export const tauriCommands = {
  /** 打开文件夹 */
  async openFolder(path: string): Promise<void> {
    try {
      await invoke("open_folder", { path });
    } catch (error) {
      console.error("打开文件夹失败:", error);
      throw error;
    }
  },

  /** 获取应用信息 */
  async getAppInfo(): Promise<{
    name: string;
    version: string;
    platform: string;
    arch: string;
    backend_url: string;
    runtime_mode: "development" | "packaged";
    app_dir: string;
    workspace_root: string;
    resource_root: string | null;
    mcp_server_dir: string;
    mcp_server_entry: string;
    mcp_readme_path: string;
    skill_dir: string;
    mcp_http_endpoint: string;
    mcp_executable_path: string | null;
    mcp_server_exists: boolean;
    mcp_server_entry_exists: boolean;
    mcp_readme_exists: boolean;
    skill_dir_exists: boolean;
    mcp_executable_exists: boolean;
    preferred_mcp_launch_mode: "node" | "exe";
  }> {
    try {
      return await invoke("get_app_info");
    } catch (error) {
      console.error("获取应用信息失败:", error);
      throw error;
    }
  },
};

// ========== HTTP API ==========

export const api = {
  getProductMedia(recordId: number, path: string, accountProfile: string, offset = 0): Promise<ApiResponse<ProductMediaListing>> {
    return http.get(`/api/products/${recordId}/media`, {
      params: { path, account_profile: accountProfile, offset },
    });
  },
  setProductWhiteBg(recordId: number, path: string): Promise<ApiResponse<WhiteBgSelectionResult>> {
    return http.put(`/api/products/${recordId}/media/white-background`, { path });
  },
  // ========== 产品管理 ==========

  /** 获取产品列表 */
  getProducts(): Promise<{ success: boolean; products: Product[] }> {
    return http.get("/api/products");
  },

  /** 获取产品详情 */
  loadDetail(
    id: number,
    loadImages = true
  ): Promise<{ success: boolean; data: ProductDetail }> {
    return http.get(`/load_detail?_id=${id}&images=${loadImages}`);
  },

  /** 保存产品信息 */
  saveInfo(data: Record<string, unknown>): Promise<ApiResponse<ProductSaveResult>> {
    return http.post("/save_info", data);
  },

  /** 删除SKU */
  deleteSku(skuPath: string, recordId: number): Promise<ApiResponse> {
    return http.post("/delete_sku", {
      sku_path: skuPath,
      record_id: recordId,
    });
  },

  /** 删除产品 */
  deleteProduct(id: number): Promise<ApiResponse> {
    return http.get(`/menu_delete?_id=${id}`);
  },

  /** 删除所有产品 */
  deleteAll(): Promise<ApiResponse> {
    return http.delete("/delete_all");
  },

  /** 打开产品文件夹 */
  async openProduct(id: number): Promise<ApiResponse> {
    // 先获取产品路径，然后用Tauri打开
    try {
      const detail = await this.loadDetail(id, false);
      if (detail.success && detail.data?.path) {
        await tauriCommands.openFolder(detail.data.path);
        return { success: true, msg: "已打开文件夹" };
      }
      // 降级到HTTP方式
      return http.get(`/menu_open?_id=${id}`);
    } catch {
      // 降级到HTTP方式
      return http.get(`/menu_open?_id=${id}`);
    }
  },

  // ========== 淘宝资料准备（独立于抖音上传） ==========

  getTaobaoReadiness(): Promise<ApiResponse<TaobaoReadiness>> {
    return http.get("/api/taobao/readiness");
  },

  prepareTaobaoProduct(payload: TaobaoPublishPayload): Promise<ApiResponse<TaobaoPreparation>> {
    return http.post("/api/taobao/publish/prepare", payload);
  },

  exportTaobaoPacket(payload: TaobaoPublishPayload): Promise<ApiResponse<TaobaoPacketExport>> {
    return http.post("/api/taobao/publish/export", payload);
  },

  /**
   * 启动淘宝发布流水线。
   *
   * **默认 dry-run**：`dryRun` 缺省 true，所有会写平台的阶段全部跳过，
   * 只验证数据与前置条件。真写入还需要 sidecar 的 `TAOBAO_UPLOAD_ALLOW_WRITE`；
   * 真提交还需要 `TAOBAO_UPLOAD_ALLOW_SUBMIT` 精确为 `"1"`，且
   * `stopBeforeSubmit` 必须显式传 false。
   *
   * 后端刻意不接受字符串形式的布尔值——`"false"` 会被当成真，进而绕过默认的 dry-run。
   */
  startTaobaoPublish(
    recordId: number,
    options: {
      /**
       * **真实发布。** 与抖店的 `confirmFinalPublish` 对应。
       *
       * 打开后本次请求带 `dry_run: false` + `stop_before_submit: false`。
       * **但这不等于会写入平台**——Sidecar 侧还要求环境变量
       * `TAOBAO_UPLOAD_ALLOW_WRITE`（写操作）与 `TAOBAO_UPLOAD_ALLOW_SUBMIT=1`
       * （提交）。授权开关在服务端，不由界面决定。
       *
       * 缺省 `false`：默认走校对模式。
       */
      realPublish?: boolean;
      dryRun?: boolean;
      stopBeforeSubmit?: boolean;
      /** 本次仅上传与填写，并在提交前停止；服务端限定授权范围。 */
      fillOnly?: boolean;
      accountProfile?: string;
      expectedRecordRevision?: string;
      /** 随带的商品资料。**不给的话流水线收不到标题/价格/库存/类目。** */
      product?: TaobaoProductRequest;
      /**
       * 上架方式。留空 = 走流水线默认值（**放入仓库**）。
       *
       * ⚠️ 页面的默认值是「立刻上架」——最危险的那个。所以这里不传时流水线会
       * 明确写成「放入仓库」，要立刻上架必须**显式**选，不是一个疏忽就能让商品上架。
       */
      listingMode?: TaobaoListingMode;
      /**
       * 是否在回读通过后**保存草稿**。**默认 false。**
       *
       * 授权（sidecar 的 `TAOBAO_UPLOAD_ALLOW_WRITE` 含 `save_draft`）只是**白名单**，
       * 这个字段才是**开关**——两者分开，界面和后端都不会"顺手就存了"。
       */
      saveDraft?: boolean;
    } = {}
  ): Promise<ApiResponse<TaobaoPublishStartResult>> {
    // 真实发布要**两个字段一起**显式带上：`dry_run=false` 才让写阶段真的执行，
    // `stop_before_submit=false` 才允许走到提交。少一个都到不了提交。
    const realPublish = options.realPublish === true;
    return http.post("/api/taobao/publish/start", {
      record_id: recordId,
      platform: "taobao",
      ...(options.accountProfile ? { account_profile: options.accountProfile } : {}),
      ...(options.expectedRecordRevision ? { expected_record_revision: options.expectedRecordRevision } : {}),
      // 随带的商品资料：不给的话流水线收不到标题/价格/库存/类目。
      ...(options.product ? { product: options.product } : {}),
      dry_run: realPublish ? false : (options.dryRun ?? true),
      stop_before_submit: realPublish ? false : (options.stopBeforeSubmit ?? true),
      ...(options.fillOnly === true ? { fill_only: true } : {}),
      // 上架方式：只在显式选了才发；不发=流水线用默认的「放入仓库」。
      ...(options.listingMode ? { listing_mode: options.listingMode } : {}),
      // 保存草稿：**只在显式为 true 时发**。不发=后端默认 False=不保存。
      ...(options.saveDraft === true ? { save_draft: true } : {}),
    });
  },

  getTaobaoPublishStatus(taskId: string): Promise<ApiResponse<TaobaoPublishTask>> {
    return http.get(`/api/taobao/publish/status/${taskId}`);
  },

  cancelTaobaoPublish(taskId: string): Promise<ApiResponse<{ task_id: string; status: string }>> {
    return http.post(`/api/taobao/publish/cancel/${taskId}`);
  },

  listTaobaoPublishTasks(): Promise<ApiResponse<{ count: number; tasks: TaobaoPublishTask[] }>> {
    return http.get("/api/taobao/publish/tasks");
  },

  // ========== 上传功能 ==========

  /** 开始上传 */
  startUpload(recordId?: number, options?: UploadStartOptions): Promise<ApiResponse> {
    // 新版上传：返回 task_id，前端需轮询 /api/upload/status/<task_id>
    const payload: Record<string, unknown> = {};
    if (recordId) {
      payload.record_id = recordId;
    }
    if (options?.accountProfile) {
      payload.account_profile = options.accountProfile;
    }
    if (options?.expectedRecordRevision) {
      payload.expected_record_revision = options.expectedRecordRevision;
    }
    // 后端 stop_before_submit 默认 true（提交前截停）。真实发布必须两个字段一起显式带上：
    // stop_before_submit=false 表示要提交，confirm_final_publish=true 表示人已确认。
    // 只传其一后端会直接拒绝，这是防误发的安全门，不要绕过它。
    if (options?.confirmFinalPublish) {
      payload.stop_before_submit = false;
      payload.confirm_final_publish = true;
    } else if (options?.stopBeforeSubmit !== false) {
      payload.stop_before_submit = true;
    }
    return http.post("/api/upload/start", payload);
  },

  /** 获取上传任务状态 */
  getUploadStatus(taskId: string): Promise<{
    success: boolean;
    data: {
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
    };
    msg?: string;
  }> {
    return http.get(`/api/upload/status/${taskId}`);
  },

  /** 请求在当前阶段结束后取消上传，不提前认定任务已结束。 */
  cancelUpload(taskId: string): Promise<ApiResponse> {
    return http.post(`/api/upload/cancel/${encodeURIComponent(taskId)}`);
  },

  /** 获取上传任务列表 */
  getUploadTasks(options: { silentError?: boolean } = {}): Promise<{
    success: boolean;
    data?: {
      tasks: UploadTaskSummary[];
      browser_status?: {
        current_task?: string | null;
        has_browser?: boolean;
        is_running?: boolean;
      };
    };
  }> {
    return http.get("/api/upload/tasks", {
      __silentError: !!options.silentError,
    } as any);
  },

  // ========== 智能标题 ==========

  /** 生成智能标题 */
  generateSmartTitle(recordId: number): Promise<{
    success: boolean;
    data: { suggestions: TitleSuggestion[] };
  }> {
    return http.post("/api/generate_smart_title", { record_id: recordId });
  },

  /** 生成增强标题 */
  generateEnhancedTitle(
    recordId: number,
    useTrending = true
  ): Promise<{
    success: boolean;
    data: {
      suggestions: TitleSuggestion[];
      trending_keywords: { keyword: string; trend_score: number }[];
    };
  }> {
    return http.post("/api/generate_smart_title_enhanced", {
      record_id: recordId,
      use_trending: useTrending,
    });
  },

  /** 生成专业标题 */
  generateProfessionalTitle(
    recordId: number,
    style = "trendy"
  ): Promise<ApiResponse> {
    return http.post("/api/generate_professional_title", {
      record_id: recordId,
      style: style,
    });
  },

  // ========== 价格计算 ==========

  /** 智能价格计算 */
  calculateSmartPrices(
    recordId: number,
    unitPrice?: number
  ): Promise<{
    success: boolean;
    data: {
      pricing_results: PricingResult[];
      statistics: PricingStatistics;
      config_used: {
        target_gross_margin: number;
        fixed_costs: number;
        percentage_costs: number;
        cost_items_count: number;
      };
    };
  }> {
    return http.post("/api/pricing/calculate_smart_prices", {
      record_id: recordId,
      unit_price: unitPrice,
    });
  },

  // ========== 采集功能 ==========

  /** 开始采集 */
  startCapture(
    url: string,
    options?: Record<string, unknown>
  ): Promise<CaptureStartResponse> {
    return http
      .post("/api/capture/start", { url, options })
      .then((response) =>
        normalizeCaptureStartResponse(response as unknown as CaptureStartResponse)
      );
  },

  /** 获取采集状态 */
  getCaptureStatus(
    taskId: string
  ): Promise<{ success: boolean } & CaptureStatus> {
    return http.get(`/api/capture/status/${taskId}`);
  },

  /** 获取采集历史 */
  getCaptureHistory(): Promise<{
    success: boolean;
    data?: {
      tasks: CaptureHistoryTask[];
    };
  }> {
    return http.get("/api/capture/history");
  },

  /** 导入采集结果 */
  importCaptureResult(taskId: string, category: number = 1): Promise<ApiResponse> {
    return http.post("/api/capture/import", { task_id: taskId, category: category });
  },

  /** 取消采集任务 */
  cancelCapture(taskId: string): Promise<ApiResponse> {
    return http.post(`/api/capture/cancel/${taskId}`);
  },

  /** 导入文件夹 */
  importFolders(paths: string[]): Promise<ApiResponse & {
    data?: {
      imported_count?: number;
      errors?: string[];
      duplicate_sku_products?: Array<{
        product_name: string;
        path?: string;
        duplicate_groups?: Array<{
          display_name: string;
          count: number;
          paths?: string[];
        }>;
      }>;
    };
  }> {
    return http.post("/api/import/folders", { paths });
  },

  // ========== 店铺会话 ==========

  /**
   * 当前账户与平台状态。抖音店铺身份来自发布浏览器实测；
   * 淘宝使用独立浏览器手动登录，当前仍返回 manual，不宣称身份已验证。
   */
  getShopSession(silent = false): Promise<ApiResponse<ShopSessionState>> {
    return http.get("/api/shop/current", { __silentError: silent } as any);
  },

  /** 已登记的店铺列表 */
  getShopProfiles(): Promise<
    ApiResponse<{ active_profile: string; profiles: ShopProfile[]; registry_path: string }>
  > {
    return http.get("/api/shop/profiles");
  },

  /** 新建平台账户并打开对应独立登录浏览器；名称只用于本地标记。 */
  addShop(
    platform: TargetPublishPlatform = "douyin",
    label = "",
    openBrowser = true
  ): Promise<ApiResponse<ShopSwitchResult>> {
    return http.post("/api/shop/add", { platform, label, open_browser: openBrowser });
  },

  /** 切换到某个已有店铺，并打开登录页 */
  switchShop(profileName: string, openBrowser = true): Promise<ApiResponse<ShopSwitchResult>> {
    return http.post("/api/shop/switch", {
      profile_name: profileName,
      open_browser: openBrowser,
    });
  },

  /**
   * 当前登录店铺的运费模板，实时从店铺读。
   * 模板是每家店自己的，不能用本地维护的列表——名字对不上发布就会选错。
   */
  getShopFreightTemplates(): Promise<ApiResponse<ShopFreightTemplates>> {
    return http.get("/api/shop/freight-templates");
  },

  /**
   * 删除一个店铺账户。
   *
   * @param purge `true` 表示**连本地浏览器登录资料一起删除**——这才是用户
   *   理解的「删除」：下次重新添加同一个账户时是全新未登录状态。
   *   `false` 只摘掉列表记录，登录态留在磁盘上。
   */
  forgetShop(profileName: string, purge = true): Promise<
    ApiResponse<{
      purged: boolean;
      removed_profile: string;
      active_profile: string;
      profiles: ShopProfile[];
    }>
  > {
    return http.post("/api/shop/forget", { profile_name: profileName, purge });
  },

  // ========== 设置管理 ==========

  /** 获取设置 */
  getSettings(): Promise<{
    success: boolean;
    data: { settings: Settings };
  }> {
    return http.get("/settings");
  },

  /** 更新设置 */
  updateSettings(settings: Partial<Settings>): Promise<ApiResponse> {
    return http.post("/settings", settings);
  },

  /** 导入自动化设置中的水洗标/吊牌图 */
  importAutomationWashLabelTagImage(sourcePath: string): Promise<
    ApiResponse<{
      stored_path: string;
      file_name: string;
    }>
  > {
    return http.post("/settings/automation/wash-label/import", {
      source_path: sourcePath,
    });
  },

  /** 删除自动化设置中的水洗标/吊牌图 */
  removeAutomationWashLabelTagImage(storedPath?: string): Promise<ApiResponse> {
    return http.post("/settings/automation/wash-label/remove", {
      stored_path: storedPath || "",
    });
  },

  /** 重置设置 */
  resetSettings(): Promise<ApiResponse> {
    return http.post("/settings/reset");
  },

  /**
   * 测试 AI 模型连接
   * 后端接收 { [provider]: { enabled, api_key, model } } 形态，
   * 一次只测一个 provider，由调用方按 provider 包装 payload。
   */
  testAiConfig(payload: Record<string, {
    enabled: boolean;
    api_key: string;
    model: string;
  }>): Promise<ApiResponse<Record<string, { success: boolean; error?: string }>>> {
    return http.post("/api/ai/test", payload);
  },

  /**
   * 获取某厂商可用模型列表（OpenAI 兼容 GET /models）
   */
  listAiModels(payload: {
    provider: string;
    api_key: string;
    api_base: string;
  }): Promise<ApiResponse<{ models: string[] }>> {
    return http.post("/api/ai/models", payload);
  },

  // ========== 热门关键词 ==========

  /** 获取热门关键词 */
  getTrendingKeywords(categoryId: number, limit = 10): Promise<ApiResponse> {
    return http.get(`/api/trending_keywords/${categoryId}?limit=${limit}`);
  },

  /** 刷新热门关键词 */
  refreshTrendingKeywords(categoryId: number): Promise<ApiResponse> {
    return http.post("/api/refresh_trending_keywords", {
      category_id: categoryId,
    });
  },

  // ========== 白底图（语义抠图） ==========

  /**
   * 白底图模型是否就绪。模型约 1GB（birefnet-general + CLIP），不打进安装包，
   * 从运行数据目录读取，缺文件时 missing 会列出具体路径。
   */
  getWhiteBgStatus(matteModel?: string): Promise<ApiResponse<WhiteBgModelStatus>> {
    const qs = matteModel ? `?matte_model=${encodeURIComponent(matteModel)}` : "";
    return http.get(`/api/whitebg/status${qs}`);
  },

  /**
   * 启动白底图生成。一个商品 7 张图约 80 秒，所以是异步任务，
   * 拿到 task_id 后轮询 getWhiteBgTask。
   */
  startWhiteBg(
    options: WhiteBgStartOptions
  ): Promise<ApiResponse<{ task_id: string }>> {
    return http.post("/api/whitebg/start", {
      record_id: options.recordId,
      product_dir: options.productDir,
      matte_model: options.matteModel,
      canvas: options.canvas,
      fill_ratio: options.fillRatio,
      deskew: options.deskew,
      square_size: options.squareSize,
      overwrite: options.overwrite,
    });
  },

  /** 轮询白底图任务进度与结果 */
  getWhiteBgTask(taskId: string): Promise<ApiResponse<WhiteBgTask>> {
    return http.get(`/api/whitebg/task/${taskId}`);
  },

  /** 读取某个采集目录已生成的白底图 / 1:1 规格图与上次的判定报告 */
  listWhiteBg(params: {
    recordId?: number;
    productDir?: string;
  }): Promise<ApiResponse<WhiteBgListing>> {
    const search = new URLSearchParams();
    if (params.recordId !== undefined) {
      search.set("record_id", String(params.recordId));
    }
    if (params.productDir) {
      search.set("product_dir", params.productDir);
    }
    return http.get(`/api/whitebg/list?${search.toString()}`);
  },

  /** 白底图预览地址。后端只放行 uploads/products 之内的文件 */
  whiteBgImageUrl(path: string): string {
    return `${BACKEND_URL}/api/whitebg/image?path=${encodeURIComponent(path)}`;
  },

  // ========== 健康检查 ==========

  /** 检查后端健康状态 */
  async healthCheck(): Promise<{
    success: boolean;
    status: string;
    version?: string;
  }> {
    try {
      const response = await http.get("/health", {
        __silentError: true,
      } as any) as any;
      return {
        success: response?.success ?? false,
        status: response?.status ?? "unknown",
        version: response?.version,
      };
    } catch {
      return { success: false, status: "offline" };
    }
  },
};

// ========== 初始化函数 ==========

/**
 * 初始化API服务
 * - 检查后端状态
 * - 仅等待桌面壳层自动拉起 sidecar，不在前端重复拉起
 */
export async function initializeApi(): Promise<boolean> {
  console.log("🔄 正在初始化API服务...");
  for (let retry = 0; retry < 12; retry += 1) {
    const health = await api.healthCheck();
    if (health.success) {
      console.log("✅ 后端服务已就绪");
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 800));
  }

  console.warn("⚠️ 后端服务未就绪，请通过唯一入口 start_frontend.bat 启动");
  return false;
}

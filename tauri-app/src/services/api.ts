/**
 * API服务层
 * 与Python后端通信 + Tauri命令调用
 */

import axios from "axios";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type {
  ApiResponse,
  Product,
  ProductDetail,
  TitleSuggestion,
  PricingResult,
  PricingStatistics,
  CaptureStatus,
  CaptureHistoryTask,
  UploadTaskSummary,
  Settings,
} from "@/types";

// 后端URL配置
// 注意: 如果端口5000被占用，使用5001
const BACKEND_URL = "http://127.0.0.1:5001";

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

function shouldLogApiError(error: unknown) {
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

export const tauriCommands = {
  /** 启动Python后端 */
  async startBackend(): Promise<string> {
    try {
      return await invoke<string>("start_python_backend");
    } catch (error) {
      console.error("启动后端失败:", error);
      throw error;
    }
  },

  /** 停止Python后端 */
  async stopBackend(): Promise<string> {
    try {
      return await invoke<string>("stop_python_backend");
    } catch (error) {
      console.error("停止后端失败:", error);
      throw error;
    }
  },

  /** 检查后端状态 */
  async checkBackendStatus(): Promise<{
    success: boolean;
    status: string;
    message?: string;
  }> {
    try {
      return await invoke("check_backend_status");
    } catch (error) {
      return { success: false, status: "error", message: String(error) };
    }
  },

  /** 打开文件夹 */
  async openFolder(path: string): Promise<void> {
    try {
      await invoke("open_folder", { path });
    } catch (error) {
      console.error("打开文件夹失败:", error);
      throw error;
    }
  },

  /** 导入拖入的文件 */
  async importDroppedFiles(paths: string[]): Promise<ApiResponse> {
    try {
      return await invoke("import_dropped_files", { paths });
    } catch (error) {
      console.error("导入文件失败:", error);
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

  /** 监听文件拖入事件 */
  async onFilesDropped(
    callback: (paths: string[]) => void
  ): Promise<() => void> {
    const unlisten = await listen<string[]>("files-dropped", (event) => {
      callback(event.payload);
    });
    return unlisten;
  },
};

// ========== HTTP API ==========

export const api = {
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
  saveInfo(data: Record<string, unknown>): Promise<ApiResponse> {
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

  // ========== 上传功能 ==========

  /** 开始上传 */
  startUpload(recordId?: number): Promise<ApiResponse> {
    // 新版上传：返回 task_id，前端需轮询 /api/upload/status/<task_id>
    return http.post("/api/upload/start", recordId ? { record_id: recordId } : {});
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

  /** 获取价格配置 */
  getPricingConfig(): Promise<ApiResponse> {
    return http.get("/api/pricing/config");
  },

  /** 保存成本配置 */
  saveCostConfig(data: Record<string, unknown>): Promise<ApiResponse> {
    return http.post("/api/pricing/cost-config", data);
  },

  /** 获取成本项目列表 */
  getCostItems(): Promise<ApiResponse> {
    return http.get("/api/pricing/cost-items");
  },

  /** 保存成本项目 */
  saveCostItem(data: Record<string, unknown>): Promise<ApiResponse> {
    return http.post("/api/pricing/cost-item", data);
  },

  /** 保存利润率配置 */
  saveProfitMarginConfig(data: Record<string, unknown>): Promise<ApiResponse> {
    return http.post("/api/pricing/profit-margin-config", data);
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

  // ========== GUI控制 ==========

  /** 切换拖拽区域显示 */
  toggleDragArea(show: boolean): Promise<ApiResponse> {
    return http.post("/gui/toggle_drag_area", { show });
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

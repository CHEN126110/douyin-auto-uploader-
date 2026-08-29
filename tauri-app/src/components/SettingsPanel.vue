<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  Connection,
  Cpu,
  Setting,
  Box,
  Document,
  InfoFilled,
  CircleCheck,
  Warning,
  Lightning,
  Mouse,
  Link,
  CopyDocument,
  Promotion,
} from "@element-plus/icons-vue";
import { getVersion } from "@tauri-apps/api/app";
import { api, tauriCommands } from "@/services/api";
import { checkForUpdate } from "@/services/updater";
import type {
  AutomationConfig,
  CaptureMode,
  CapturePreferences,
  CostItem,
  MaterialComposition,
  ModelConfig,
  Settings,
} from "@/types";

type AppInfo = {
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
  bundled_node_path: string | null;
  mcp_server_exists: boolean;
  mcp_server_entry_exists: boolean;
  mcp_readme_exists: boolean;
  skill_dir_exists: boolean;
  mcp_executable_exists: boolean;
  bundled_node_exists: boolean;
  preferred_mcp_launch_mode: "node" | "exe";
};

// 当前选中的标签页
type SettingsTab = "pricing" | "model" | "automation" | "mcp";

const SETTINGS_TABS: SettingsTab[] = ["pricing", "model", "automation", "mcp"];
const route = useRoute();
const routeTab = typeof route.query.tab === "string" ? route.query.tab : "";
const activeTab = ref<SettingsTab>(
  SETTINGS_TABS.includes(routeTab as SettingsTab) ? (routeTab as SettingsTab) : "pricing"
);

// 加载状态
const loading = ref(false);

// 是否有未保存的更改
const hasUnsavedChanges = ref(false);
// 初次 loadSettings 完成前，所有 watch 都不应标记为 dirty
const settingsLoaded = ref(false);

function markDirty() {
  if (settingsLoaded.value) {
    hasUnsavedChanges.value = true;
  }
}

// 设置加载失败标记。加载失败时面板显示的是本文件里的硬编码默认值，
// 一旦保存就会把后端真实的成本项 / 运费模板 / 材质成分 / 洗唛吊牌图 / 发布模式 /
// 采集偏好整体覆盖，所以必须禁用保存并把失败原因暴露给用户。
const loadFailed = ref(false);
// 原始错误信息，直接展示给用户作为排查入口，不做吞掉或美化
const loadErrorMessage = ref("");

function markLoadFailed(detail: string) {
  loadFailed.value = true;
  loadErrorMessage.value = detail;
  ElMessage.error(`设置加载失败：${detail}。请确认后端已启动，修复后点击「重试加载」，在此之前请勿保存`);
}


// ========== 价格设置 ==========

// 基础配置
const pricingConfig = ref({
  target_gross_margin: 30,     // 目标毛利率（%）
});

// 成本项目列表（可增删改）
const costItems = ref<CostItem[]>([
  { id: "1", name: "单位成本", cost_type: "per_unit", value: 8.0, description: "每双袜子的基础成本" },
  { id: "2", name: "运费", cost_type: "fixed", value: 5.0, description: "物流运输费用" },
  { id: "3", name: "包装费", cost_type: "fixed", value: 1.0, description: "包装材料费用" },
  { id: "4", name: "平台佣金", cost_type: "percentage", value: 6, description: "平台抽成比例" },
]);

// 当前编辑的成本项索引（-1表示未编辑）
const editingCostIndex = ref(-1);

// 新增成本项
const newCostItem = ref<CostItem>({
  id: "",
  name: "",
  cost_type: "fixed",
  value: 0,
  description: "",
});

// 是否显示添加表单
const showAddForm = ref(false);

// 添加成本项
function addCostItem() {
  if (!newCostItem.value.name.trim()) {
    ElMessage.warning("请输入成本项名称");
    return;
  }

  costItems.value.push({
    ...newCostItem.value,
    id: Date.now().toString(),
  });

  // 重置表单
  newCostItem.value = {
    id: "",
    name: "",
    cost_type: "fixed",
    value: 0,
    description: "",
  };
  showAddForm.value = false;

  ElMessage.success("添加成功");
}

// 取消添加
function cancelAddCostItem() {
  newCostItem.value = {
    id: "",
    name: "",
    cost_type: "fixed",
    value: 0,
    description: "",
  };
  showAddForm.value = false;
}

// 删除成本项
async function removeCostItem(index: number) {
  try {
    await ElMessageBox.confirm("确定删除该成本项吗？", "提示", {
      type: "warning",
    });
    costItems.value.splice(index, 1);
    editingCostIndex.value = -1;
    ElMessage.success("删除成功");
  } catch {
    // 用户取消
  }
}

// 开始编辑成本项
function startEditCostItem(index: number) {
  editingCostIndex.value = index;
}

// 完成编辑
function finishEditCostItem() {
  editingCostIndex.value = -1;
}

// 获取单位
function getUnit(type: string): string {
  return type === "percentage" ? "%" : "元";
}

// 获取类型标签样式
function getTypeTagType(type: string): "success" | "warning" | "info" {
  switch (type) {
    case "fixed":
      return "info";
    case "per_unit":
      return "warning";
    case "percentage":
      return "success";
    default:
      return "info";
  }
}

// 获取类型显示名称
function getTypeName(type: string): string {
  switch (type) {
    case "fixed":
      return "固定";
    case "per_unit":
      return "按数量";
    case "percentage":
      return "百分比";
    default:
      return type;
  }
}

// 计算成本汇总
const costSummary = computed(() => {
  let fixed = 0;
  let perUnit = 0;
  let percentage = 0;
  
  for (const item of costItems.value) {
    switch (item.cost_type) {
      case "fixed":
        fixed += item.value;
        break;
      case "per_unit":
        perUnit += item.value;
        break;
      case "percentage":
        percentage += item.value;
        break;
    }
  }
  
  return { fixed, perUnit, percentage };
});

// ========== 自动化设置 ==========

// 运费模板列表
const shippingTemplates = ref<string[]>([]);
// 当前选中的运费模板
const selectedShippingTemplate = ref("");
// 新增模板名称
const newTemplateName = ref("");
const materialOptions = ref<string[]>([]);
const materialCompositions = ref<MaterialComposition[]>([]);
const washLabelTagImagePath = ref("");
const washLabelTagImageLoading = ref(false);
const publishMode = ref("dom");
// 采集偏好：分平台独立配置。1688 和 淘宝/天猫 是两个独立平台，采集协议互不交叉。
//   - dom（默认）：读浏览器渲染数据（1688 走 window.context；淘宝/天猫 走 mtop SDK）
//   - protocol（预览版）：CDP 网络拦截抓接口响应，目前数据提取仍回退到 DOM，
//     主要价值是会把协议层网络快照保存到工件目录，方便后续抓包分析。
const capturePreferences = ref<CapturePreferences>({
  alibaba_1688_mode: "dom",
  taobao_tmall_mode: "dom",
});
const newMaterialName = ref("");
const newMaterialPercentage = ref(0);

function normalizeMaterialCompositions(
  source?: Array<Partial<MaterialComposition>> | null
): MaterialComposition[] {
  return Array.isArray(source)
    ? source
        .map((item) => ({
          material: String(item?.material ?? "").trim(),
          percentage: Number(item?.percentage ?? 0),
        }))
        .filter((item) => item.material && Number.isFinite(item.percentage) && item.percentage > 0)
    : [];
}

const materialPercentageTotal = computed(() =>
  materialCompositions.value.reduce((sum, item) => sum + Number(item.percentage || 0), 0)
);
const materialSettingsInvalid = computed(() => {
  // 材质允许自定义输入：平台会不断新增面料，写死白名单会把新材质挡在外面。
  // 这里只保证「非空」与「含量合计 100%」，是否为平台标准项交由 isCustomMaterial 提示。
  const hasEmptyMaterial = materialCompositions.value.some((item) => !item.material);
  return materialPercentageTotal.value !== 100 || hasEmptyMaterial;
});

/** 该材质是否为平台选项之外的自定义项（仅用于提示，不阻断保存） */
function isCustomMaterial(name: string): boolean {
  const value = String(name || "").trim();
  if (!value) return false;
  return !materialOptions.value.includes(value);
}

const customMaterialNames = computed(() =>
  materialCompositions.value
    .map((item) => String(item.material || "").trim())
    .filter((name) => name && isCustomMaterial(name))
);
const washLabelTagImagePreviewUrl = computed(() => {
  const p = washLabelTagImagePath.value.trim();
  if (!p) return "";
  return `http://127.0.0.1:5001/settings/automation/wash-label/preview?t=${Date.now()}`;
});

function addMaterialComposition() {
  const material = newMaterialName.value.trim();
  const percentage = Number(newMaterialPercentage.value);
  if (!material) {
    ElMessage.warning("请选择或输入材质");
    return;
  }
  if (materialCompositions.value.some((item) => item.material === material)) {
    ElMessage.warning("该材质已存在");
    return;
  }
  if (!Number.isFinite(percentage) || percentage <= 0) {
    ElMessage.warning("请输入有效含量");
    return;
  }
  materialCompositions.value.push({ material, percentage });
  newMaterialName.value = "";
  newMaterialPercentage.value = 0;
}

function removeMaterialComposition(index: number) {
  materialCompositions.value.splice(index, 1);
}

async function selectWashLabelTagImage() {
  try {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({
      directory: false,
      multiple: false,
      title: "选择水洗标/吊牌图",
      filters: [
        {
          name: "图片文件",
          extensions: ["jpg", "jpeg", "png", "bmp", "webp"],
        },
      ],
    });

    if (!selected || Array.isArray(selected)) {
      return;
    }

    washLabelTagImageLoading.value = true;
    const response = await api.importAutomationWashLabelTagImage(String(selected));
    if (response.success && response.data?.stored_path) {
      washLabelTagImagePath.value = response.data.stored_path;
      ElMessage.success(response.msg || "水洗标/吊牌图导入成功");
      return;
    }
    ElMessage.error(response.msg || "水洗标/吊牌图导入失败");
  } catch (error) {
    console.error("选择水洗标/吊牌图失败:", error);
    ElMessage.error("无法选择水洗标/吊牌图");
  } finally {
    washLabelTagImageLoading.value = false;
  }
}

async function clearWashLabelTagImage() {
  if (!washLabelTagImagePath.value) {
    return;
  }
  try {
    await ElMessageBox.confirm("确定清空当前水洗标/吊牌图吗？", "提示", {
      type: "warning",
    });
    washLabelTagImageLoading.value = true;
    const response = await api.removeAutomationWashLabelTagImage(washLabelTagImagePath.value);
    if (!response.success) {
      ElMessage.error(response.msg || "清空水洗标/吊牌图失败");
      return;
    }
    washLabelTagImagePath.value = "";
    ElMessage.success(response.msg || "水洗标/吊牌图已清空");
  } catch (error) {
    if (error !== "cancel") {
      console.error("清空水洗标/吊牌图失败:", error);
    }
  } finally {
    washLabelTagImageLoading.value = false;
  }
}

// 添加运费模板
function addShippingTemplate() {
  const name = newTemplateName.value.trim();
  if (!name) {
    ElMessage.warning("请输入模板名称");
    return;
  }
  if (shippingTemplates.value.includes(name)) {
    ElMessage.warning("该模板名称已存在");
    return;
  }
  shippingTemplates.value.push(name);
  selectedShippingTemplate.value = name; // 自动选中新添加的
  newTemplateName.value = "";
  ElMessage.success("添加成功");
}

// 删除运费模板
async function removeShippingTemplate(index: number) {
  const name = shippingTemplates.value[index];
  
  // 至少保留一个模板
  if (shippingTemplates.value.length <= 1) {
    ElMessage.warning("至少保留一个运费模板");
    return;
  }
  
  try {
    await ElMessageBox.confirm(`确定删除模板 "${name}" 吗？`, "提示", {
      type: "warning",
    });
    
    shippingTemplates.value.splice(index, 1);
    
    // 如果删除的是当前选中的，切换到第一个
    if (selectedShippingTemplate.value === name) {
      selectedShippingTemplate.value = shippingTemplates.value[0];
    }
    
    ElMessage.success("删除成功");
  } catch {
    // 用户取消
  }
}

// ========== 模型API设置 ==========

const DEEPSEEK_BASE_URL = "https://api.deepseek.com";
const DEEPSEEK_DEFAULT_MODEL = "deepseek-chat";
// 小米 MiMo 开放平台（OpenAI 兼容，实证确认端点）。密钥从 platform.xiaomimimo.com 控制台创建
const XIAOMI_BASE_URL = "https://api.xiaomimimo.com/v1";
const XIAOMI_DEFAULT_MODEL = "mimo-v2.5-pro";
const KNOWN_MODEL_BASE_URLS = new Set([DEEPSEEK_BASE_URL, XIAOMI_BASE_URL]);
const KNOWN_MODEL_NAMES = new Set([DEEPSEEK_DEFAULT_MODEL, XIAOMI_DEFAULT_MODEL]);
const ALLOWED_PROVIDERS = new Set(["deepseek", "xiaomi"]);

function createDeepSeekModelConfig(): ModelConfig {
  return {
    id: "deepseek",
    name: "DeepSeek",
    provider: "deepseek",
    api_key: "",
    api_base: DEEPSEEK_BASE_URL,
    model_name: DEEPSEEK_DEFAULT_MODEL,
    enabled: false,
  };
}

function createXiaomiModelConfig(): ModelConfig {
  return {
    id: "xiaomi",
    name: "小米大模型",
    provider: "xiaomi",
    api_key: "",
    api_base: XIAOMI_BASE_URL,
    model_name: XIAOMI_DEFAULT_MODEL,
    enabled: false,
  };
}

function createNewModelConfig(): ModelConfig {
  return {
    id: "",
    name: "",
    provider: "deepseek",
    api_key: "",
    api_base: DEEPSEEK_BASE_URL,
    model_name: DEEPSEEK_DEFAULT_MODEL,
    enabled: true,
  };
}

function normalizeModelConfigs(source?: ModelConfig[] | null): ModelConfig[] {
  const list = Array.isArray(source) ? source : [];
  // 仅保留发布优化允许的厂商；缺省补齐 DeepSeek / 小米 两个空配置供填写
  const normalized = list.filter((c) =>
    ALLOWED_PROVIDERS.has(String(c.provider || "").toLowerCase())
  );
  const has = (p: string) =>
    normalized.some((c) => String(c.provider || "").toLowerCase() === p);
  const result = [...normalized];
  if (!has("deepseek")) result.unshift(createDeepSeekModelConfig());
  if (!has("xiaomi")) result.push(createXiaomiModelConfig());
  return result;
}

const modelConfigs = ref<ModelConfig[]>(normalizeModelConfigs([]));

// 新增模型配置
const newModelConfig = ref<ModelConfig>(createNewModelConfig());

function applyModelProviderDefaults(config: ModelConfig): void {
  const shouldReplaceBaseUrl =
    !config.api_base.trim() || KNOWN_MODEL_BASE_URLS.has(config.api_base.trim());
  const shouldReplaceModel =
    !config.model_name.trim() || KNOWN_MODEL_NAMES.has(config.model_name.trim());

  switch (config.provider) {
    case "deepseek":
      if (shouldReplaceBaseUrl) config.api_base = DEEPSEEK_BASE_URL;
      if (shouldReplaceModel) config.model_name = DEEPSEEK_DEFAULT_MODEL;
      if (!config.name.trim() || config.name === "小米大模型") config.name = "DeepSeek";
      break;
    case "xiaomi":
      if (shouldReplaceBaseUrl) config.api_base = XIAOMI_BASE_URL;
      if (shouldReplaceModel) config.model_name = XIAOMI_DEFAULT_MODEL;
      if (!config.name.trim() || config.name === "DeepSeek") config.name = "小米大模型";
      break;
    default:
      break;
  }
}

function handleModelProviderChange(config: ModelConfig): void {
  applyModelProviderDefaults(config);
}

// 添加模型配置
function addModelConfig() {
  if (!newModelConfig.value.name.trim()) {
    ElMessage.warning("请输入配置名称");
    return;
  }

  modelConfigs.value.push({
    ...newModelConfig.value,
    id: Date.now().toString(),
  });

  // 重置表单
  newModelConfig.value = createNewModelConfig();

  ElMessage.success("添加成功");
}

// 删除模型配置
async function removeModelConfig(index: number) {
  try {
    await ElMessageBox.confirm("确定删除该模型配置吗？", "提示", {
      type: "warning",
    });
    modelConfigs.value.splice(index, 1);
    ElMessage.success("删除成功");
  } catch {
    // 用户取消
  }
}

// 服务商 → 后端能识别的 provider 名映射。后端 /api/ai/test 支持 deepseek / xiaomi。
const TESTABLE_PROVIDER_MAP: Record<string, string> = {
  deepseek: "deepseek",
  xiaomi: "xiaomi",
};

const testingModelId = ref<string>("");
const fetchingModelsId = ref<string>("");
const modelOptions = ref<Record<string, string[]>>({});

// 通过官方 GET /models 动态获取模型列表（避免手输错误、自动跟进最新模型）
async function fetchModels(config: ModelConfig) {
  const apiKey = String(config.api_key || "").trim();
  const apiBase = String(config.api_base || "").trim();
  if (!apiKey) {
    ElMessage.warning("请先填写访问密钥后再获取模型");
    return;
  }
  if (!apiBase) {
    ElMessage.warning("请先填写服务地址后再获取模型");
    return;
  }
  fetchingModelsId.value = config.id;
  try {
    const resp = await api.listAiModels({
      provider: config.provider,
      api_key: apiKey,
      api_base: apiBase,
    });
    const models = resp?.data?.models || [];
    if (models.length) {
      modelOptions.value = { ...modelOptions.value, [config.id]: models };
      if (!config.model_name || !models.includes(config.model_name)) {
        config.model_name = models[0];
      }
      ElMessage.success(`获取到 ${models.length} 个模型`);
    } else {
      ElMessage.warning("未获取到模型列表");
    }
  } catch (error: any) {
    const detail = error?.response?.data?.msg || error?.message || String(error);
    ElMessage.error(`获取模型失败：${detail}`);
  } finally {
    fetchingModelsId.value = "";
  }
}

async function testModelConnection(config: ModelConfig) {
  const providerKey = String(config.provider || "").trim();
  const backendProvider = TESTABLE_PROVIDER_MAP[providerKey];

  if (!backendProvider) {
    ElMessage.warning(
      `「${providerKey || "未指定服务商"}」暂不支持一键测试，请先保存后手动验证一次`
    );
    return;
  }

  const apiKey = String(config.api_key || "").trim();
  if (!apiKey) {
    ElMessage.warning("请先填写访问密钥后再测试连接");
    return;
  }
  const apiBase = String(config.api_base || "").trim();
  if (!apiBase) {
    ElMessage.warning("请先填写服务地址（base_url）后再测试连接");
    return;
  }

  testingModelId.value = config.id;
  try {
    const payload = {
      [backendProvider]: {
        enabled: true,
        api_key: apiKey,
        model: String(config.model_name || "").trim(),
        api_base: apiBase,
      },
    };
    const response = await api.testAiConfig(payload);
    const result = response?.data?.[backendProvider];

    if (result?.success) {
      ElMessage.success(`${config.name} 连接成功`);
    } else {
      const reason = result?.error || response?.msg || "未知原因";
      ElMessage.error(`${config.name} 连接失败：${reason}`);
    }
  } catch (error: any) {
    console.error("测试模型连接失败:", error);
    const detail = error?.response?.data?.msg || error?.message || String(error);
    ElMessage.error(`${config.name} 连接失败：${detail}`);
  } finally {
    testingModelId.value = "";
  }
}

const defaultAppInfo: AppInfo = {
  name: "Douyin Sock Publisher",
  version: __APP_VERSION__,
  platform: "windows",
  arch: "x64",
  backend_url: "http://127.0.0.1:5001",
  runtime_mode: "development",
  app_dir: "",
  workspace_root: "",
  resource_root: null,
  mcp_server_dir: "",
  mcp_server_entry: "",
  mcp_readme_path: "",
  skill_dir: "",
  mcp_http_endpoint: "http://127.0.0.1:3300/mcp",
  mcp_executable_path: null,
  bundled_node_path: null,
  mcp_server_exists: false,
  mcp_server_entry_exists: false,
  mcp_readme_exists: false,
  skill_dir_exists: false,
  mcp_executable_exists: false,
  bundled_node_exists: false,
  preferred_mcp_launch_mode: "node",
};

const appInfo = ref<AppInfo>({ ...defaultAppInfo });

// 应用版本（来自 tauri.conf.json，与自动更新比对的是同一个权威版本号）
const appVersion = ref<string>("");
const checkingUpdate = ref<boolean>(false);

async function handleCheckUpdate() {
  checkingUpdate.value = true;
  try {
    await checkForUpdate();
  } finally {
    checkingUpdate.value = false;
  }
}

function escapeForPowerShell(path: string) {
  return path.replace(/'/g, "''");
}

function escapeForJson(path: string) {
  return path.replace(/\\/g, "\\\\");
}

const backendUrl = computed(() => appInfo.value.backend_url || "http://127.0.0.1:5001");
const mcpServerPath = computed(() => appInfo.value.mcp_server_entry || "未检测到");
const mcpHttpEndpoint = computed(
  () => appInfo.value.mcp_http_endpoint || "http://127.0.0.1:3300/mcp"
);
const skillPath = computed(() => appInfo.value.skill_dir || "未检测到");
const mcpReadmePath = computed(() => appInfo.value.mcp_readme_path || "未检测到");
const mcpExecutablePath = computed(() => appInfo.value.mcp_executable_path || "");
const bundledNodePath = computed(() => appInfo.value.bundled_node_path || "");
const runtimeModeLabel = computed(() =>
  appInfo.value.runtime_mode === "packaged" ? "安装包模式" : "开发模式"
);
const preferredMcpModeLabel = computed(() =>
  appInfo.value.preferred_mcp_launch_mode === "exe" ? "stdio(EXE)" : "Node(stdio/HTTP)"
);
const mcpLaunchHint = computed(() => {
  if (appInfo.value.preferred_mcp_launch_mode === "exe" && mcpExecutablePath.value) {
    return "当前已检测到独立 MCP 可执行文件，推荐直接用 stdio(EXE) 接入客户端；这样不依赖源码路径，也更适合打包分发。";
  }
  if (appInfo.value.bundled_node_exists && bundledNodePath.value) {
    return "当前安装包已内置 Node 运行时，可直接用内置 node.exe 启动随包分发的 MCP Server，无需用户另装 Node 环境。";
  }
  return "当前检测到的是 Node 版 MCP Server，适合开发调试。后续如果提供独立 MCP EXE，这里会自动切换为 EXE 启动指引。";
});
const mcpAvailabilityHint = computed(() => {
  if (appInfo.value.mcp_executable_exists) {
    return "";
  }
  if (!appInfo.value.mcp_server_entry_exists) {
    return "当前环境未检测到 MCP 入口文件，HTTP 模式和 Node 版 stdio 模式可能不可用。";
  }
  return "";
});

const mcpStdioCommand = computed(() => {
  if (appInfo.value.mcp_executable_exists && mcpExecutablePath.value) {
    return `& '${escapeForPowerShell(mcpExecutablePath.value)}'`;
  }
  if (appInfo.value.mcp_server_entry_exists && bundledNodePath.value) {
    return `& '${escapeForPowerShell(bundledNodePath.value)}' '${escapeForPowerShell(appInfo.value.mcp_server_entry)}'`;
  }
  if (appInfo.value.mcp_server_dir) {
    return `Set-Location '${escapeForPowerShell(appInfo.value.mcp_server_dir)}'
npm start`;
  }
  return "当前环境未检测到可用的 MCP 启动路径";
});

const mcpHttpCommand = computed(() => {
  if (!appInfo.value.mcp_server_entry_exists || !appInfo.value.mcp_server_dir) {
    return "当前环境未检测到 Node 版 MCP Server，HTTP 模式不可用";
  }
  if (bundledNodePath.value) {
    return `Set-Location '${escapeForPowerShell(appInfo.value.mcp_server_dir)}'
& '${escapeForPowerShell(bundledNodePath.value)}' server-http.js`;
  }
  return `Set-Location '${escapeForPowerShell(appInfo.value.mcp_server_dir)}'
npm run start:http`;
});

const mcpClientConfig = computed(() => {
  if (appInfo.value.mcp_executable_exists && mcpExecutablePath.value) {
    return `{
  "mcpServers": {
    "douyin-publisher": {
      "command": "${escapeForJson(mcpExecutablePath.value)}",
      "args": [],
      "env": {
        "DOUYIN_BACKEND_URL": "${backendUrl.value}",
        "DOUYIN_CDP_LIST_URL": "http://127.0.0.1:9333/json/list"
      }
    }
  }
}`;
  }

  return `{
  "mcpServers": {
    "douyin-publisher": {
      "command": "${escapeForJson(bundledNodePath.value || "node")}",
      "args": [
        "${escapeForJson(appInfo.value.mcp_server_entry || "<your-mcp-server-entry>")}"
      ],
      "env": {
        "DOUYIN_BACKEND_URL": "${backendUrl.value}",
        "DOUYIN_CDP_LIST_URL": "http://127.0.0.1:9333/json/list"
      }
    }
  }
}`;
});

async function loadAppInfo() {
  try {
    appInfo.value = {
      ...defaultAppInfo,
      ...(await tauriCommands.getAppInfo()),
    };
  } catch (error) {
    console.error("加载应用运行时路径失败:", error);
    appInfo.value = { ...defaultAppInfo };
  }
}

async function copyGuideText(text: string, label: string) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const textArea = document.createElement("textarea");
      textArea.value = text;
      textArea.style.position = "fixed";
      textArea.style.opacity = "0";
      document.body.appendChild(textArea);
      textArea.focus();
      textArea.select();
      document.execCommand("copy");
      document.body.removeChild(textArea);
    }
    ElMessage.success(`${label}已复制`);
  } catch (error) {
    console.error(`复制${label}失败:`, error);
    ElMessage.error(`复制${label}失败，请手动复制`);
  }
}

// ========== 保存和加载 ==========

// 加载所有设置
async function loadSettings() {
  loading.value = true;
  try {
    const response = await api.getSettings();
    console.log("[Settings] 加载设置响应:", response);
    
    if (response.success && response.data?.settings) {
      const settings = response.data.settings as Settings;
      
      // 加载价格配置
      if (settings.pricing_config) {
        const pc = settings.pricing_config;
        // 后端返回的是百分比形式（如30），直接使用，不需要乘以100
        const rawValue = pc.target_gross_margin ?? 30;
        // 如果值小于1，说明是小数形式（0.30），需要转换为百分比
        pricingConfig.value = {
          target_gross_margin: rawValue < 1 ? rawValue * 100 : rawValue,
        };
        console.log("[Settings] 加载毛利率配置:", rawValue, "->", pricingConfig.value.target_gross_margin);
      }
      
      // 加载成本项目
      if (settings.cost_items && Array.isArray(settings.cost_items)) {
        costItems.value = settings.cost_items;
        console.log("[Settings] 加载成本项目:", costItems.value.length, "个");
      }
      
      // 加载模型配置
      const apiModelConfigs = settings.model_configs ?? settings.model_apis;
      if (apiModelConfigs && Array.isArray(apiModelConfigs)) {
        modelConfigs.value = normalizeModelConfigs(apiModelConfigs);
      } else {
        modelConfigs.value = normalizeModelConfigs(modelConfigs.value);
      }
      
      // 加载自动化配置
      if (settings.automation_config) {
        const ac = settings.automation_config as AutomationConfig;
        // 加载模板列表
        if (ac.shipping_templates && Array.isArray(ac.shipping_templates)) {
          shippingTemplates.value = ac.shipping_templates
            .map((item) => String(item).trim())
            .filter(Boolean);
        }
        // 加载当前选中的模板
        if (ac.shipping_template) {
          selectedShippingTemplate.value = ac.shipping_template;
          // 确保选中的模板在列表中
          if (!shippingTemplates.value.includes(ac.shipping_template)) {
            shippingTemplates.value.push(ac.shipping_template);
          }
        }
        if (!selectedShippingTemplate.value) {
          selectedShippingTemplate.value = shippingTemplates.value[0] || "";
        }
        if (ac.material_options && Array.isArray(ac.material_options)) {
          materialOptions.value = ac.material_options;
        }
        materialCompositions.value = normalizeMaterialCompositions(ac.material_compositions);
        washLabelTagImagePath.value = String(ac.wash_label_tag_image_path || "").trim();
        publishMode.value = String(ac.publish_mode || "dom").trim();

        // 加载采集偏好（分平台独立）
        // 兼容旧的单一字段 capture_mode：如果新字段缺失就用旧字段作为两个平台的初始值
        const legacyCaptureMode = String(ac.capture_mode || "dom").trim();
        const prefs = ac.capture_preferences;
        const normalizeMode = (v: unknown): CaptureMode => (v === "protocol" ? "protocol" : "dom");
        capturePreferences.value = {
          alibaba_1688_mode: normalizeMode(prefs?.alibaba_1688_mode ?? legacyCaptureMode),
          taobao_tmall_mode: normalizeMode(prefs?.taobao_tmall_mode ?? legacyCaptureMode),
        };
        console.log("[Settings] 加载自动化配置:", {
          templates: shippingTemplates.value,
          selected: selectedShippingTemplate.value,
          materialOptions: materialOptions.value,
          materials: materialCompositions.value,
          washLabelTagImagePath: washLabelTagImagePath.value,
          capturePreferences: capturePreferences.value,
        });
      }

      // 只有真正拿到后端设置才允许保存
      loadFailed.value = false;
      loadErrorMessage.value = "";
    } else {
      // 后端返回 success:false 或缺少 settings：界面上留下的是本文件里的硬编码默认值，
      // 此时保存会把后端真实的 cost_items / shipping_templates / material_compositions /
      // wash_label_tag_image_path / publish_mode / capture_preferences 整体覆盖掉。
      const detail =
        (response as { msg?: string; message?: string }).msg ||
        (response as { msg?: string; message?: string }).message ||
        "后端未返回设置数据";
      console.error("加载设置失败:", response);
      markLoadFailed(detail);
    }
  } catch (error) {
    console.error("加载设置失败:", error);
    markLoadFailed(error instanceof Error ? error.message : String(error));
  } finally {
    loading.value = false;
    // 先让本次 loadSettings 赋值触发的 watch 回调（默认 'pre' flush，下一 tick 才执行）
    // 在 settingsLoaded 仍为 false 时跑完。否则这些"加载赋值"会在下一 tick 被 markDirty
    // 误判为用户改动，导致设置页一加载就显示"有未保存的更改"。
    await nextTick();
    settingsLoaded.value = true;
    hasUnsavedChanges.value = false;
  }
}

// 保存所有设置
async function handleSave() {
  loading.value = true;
  try {
    // 后端期望百分比形式（如30），直接发送输入框的值
    const settingsToSave: Settings = {
      pricing_config: {
        target_gross_margin: pricingConfig.value.target_gross_margin,
      },
      cost_items: costItems.value,
      model_configs: modelConfigs.value,
      automation_config: {
        shipping_template: selectedShippingTemplate.value,
        shipping_templates: shippingTemplates.value,
        material_options: materialOptions.value,
        material_compositions: normalizeMaterialCompositions(materialCompositions.value),
        wash_label_tag_image_path: washLabelTagImagePath.value.trim() || null,
        publish_mode: publishMode.value,
        // 分平台采集偏好：1688 和 淘宝/天猫 独立保存
        capture_preferences: {
          alibaba_1688_mode: capturePreferences.value.alibaba_1688_mode,
          taobao_tmall_mode: capturePreferences.value.taobao_tmall_mode,
        },
      },
    };

    if (materialSettingsInvalid.value) {
      activeTab.value = "automation";
      ElMessage.warning("材质名称不能为空，且含量总和必须等于100%");
      loading.value = false;
      return;
    }

    console.log("[Settings] 保存设置:", settingsToSave);

    const response = await api.updateSettings(settingsToSave);

    if (response.success) {
      ElMessage.success("设置保存成功");
      hasUnsavedChanges.value = false;
    } else {
      ElMessage.error(response.msg || "保存失败");
    }
  } catch (error) {
    console.error("保存设置失败:", error);
    ElMessage.error("保存失败");
  } finally {
    loading.value = false;
  }
}

// 显示新手引导
function showOnboarding() {
  // 清除已查看标记，让引导重新显示
  localStorage.removeItem('onboarding_completed');
  // 刷新页面以显示引导
  window.location.reload();
}

// 重置引导状态
function resetOnboarding() {
  localStorage.removeItem('onboarding_completed');
  localStorage.removeItem('onboarding_completed_at');
  ElMessage.success('引导状态已重置，下次启动时将显示新手引导');
}

// 监听用户改动，统一标记 dirty
watch(
  [
    pricingConfig,
    costItems,
    modelConfigs,
    shippingTemplates,
    () => selectedShippingTemplate.value,
    materialCompositions,
    () => washLabelTagImagePath.value,
    () => publishMode.value,
    () => capturePreferences.value.alibaba_1688_mode,
    () => capturePreferences.value.taobao_tmall_mode,
  ],
  () => {
    markDirty();
  },
  { deep: true }
);

// 初始化设置页面
onMounted(async () => {
  loadAppInfo();
  loadSettings();
  try {
    appVersion.value = await getVersion();
  } catch {
    appVersion.value = "";
  }
});
</script>

<template>
  <div class="settings-panel">
    <div v-loading="loading" class="settings-content">
      <el-tabs v-model="activeTab" class="settings-tabs">
        <!-- 价格设置标签页 -->
        <el-tab-pane label="💰 价格设置" name="pricing">
          <!-- 毛利率配置 -->
          <div class="settings-section">
            <h3 class="section-title">📈 毛利率配置</h3>
            <div class="config-row">
              <div class="config-item">
                <label>目标毛利率</label>
                <div class="config-input">
                  <el-input
                    v-model.number="pricingConfig.target_gross_margin"
                    type="number"
                    :min="0"
                    :max="100"
                  />
                  <span class="unit">%</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 成本项目管理 -->
          <div class="settings-section">
                <div class="section-header">
              <h3 class="section-title">💵 成本项目</h3>
              <el-button
                v-if="!showAddForm"
                type="success"
                size="small"
                @click="showAddForm = true"
              >
                + 添加成本项
              </el-button>
            </div>

            <!-- 成本汇总 -->
            <div class="cost-summary">
              <div class="summary-item">
                <span class="label">固定成本</span>
                <span class="value">¥{{ costSummary.fixed.toFixed(2) }}</span>
              </div>
              <div class="summary-item">
                <span class="label">按数量成本</span>
                <span class="value">¥{{ costSummary.perUnit.toFixed(2) }}/件</span>
              </div>
              <div class="summary-item">
                <span class="label">百分比成本</span>
                <span class="value">{{ costSummary.percentage }}%</span>
              </div>
            </div>
            
            <!-- 成本项目列表 - 紧凑型 -->
            <div class="cost-items-compact">
              <div
                v-for="(item, index) in costItems"
                :key="item.id"
                class="cost-item-row"
                :class="{ editing: editingCostIndex === index }"
              >
                <!-- 只读模式 -->
                <template v-if="editingCostIndex !== index">
                  <div class="item-info">
                    <span class="item-value">
                      {{ item.cost_type === 'percentage' ? '' : '¥' }}{{ item.value }}{{ getUnit(item.cost_type) }}
                    </span>
                    <span class="item-name">{{ item.name }}</span>
                    <el-tag :type="getTypeTagType(item.cost_type)" size="small" effect="light">
                      {{ getTypeName(item.cost_type) }}
                    </el-tag>
                    <span v-if="item.description" class="item-desc">{{ item.description }}</span>
                  </div>
                  <div class="item-actions">
                    <el-button type="primary" size="small" @click="startEditCostItem(index)">编辑</el-button>
                    <el-button type="danger" size="small" @click="removeCostItem(index)">删除</el-button>
                  </div>
                </template>

                <!-- 编辑模式 -->
                <template v-else>
                  <div class="edit-mode-container">
                    <!-- 标题行 -->
                    <div class="edit-labels">
                      <span class="label-item label-name">名称</span>
                      <span class="label-item label-value">数值</span>
                      <span class="label-item label-type">类型</span>
                      <span class="label-item label-desc">描述</span>
                      <span class="label-item label-action"></span>
                    </div>
                    <!-- 表单行 -->
                    <div class="edit-form">
                      <el-input
                        v-model="item.name"
                        placeholder="名称"
                        size="small"
                        class="edit-name"
                      />
                      <el-input
                        v-model.number="item.value"
                        type="number"
                        :min="0"
                        size="small"
                        class="edit-value"
                      >
                        <template #suffix>
                          <span class="unit-suffix">{{ getUnit(item.cost_type) }}</span>
                        </template>
                      </el-input>
                      <el-select v-model="item.cost_type" size="small" class="edit-type">
                        <el-option label="固定金额" value="fixed" />
                        <el-option label="按数量" value="per_unit" />
                        <el-option label="百分比" value="percentage" />
                      </el-select>
                      <el-input
                        v-model="item.description"
                        placeholder="描述（可选）"
                        size="small"
                        class="edit-desc"
                      />
                      <el-button type="primary" size="small" @click="finishEditCostItem">
                        完成
                      </el-button>
                    </div>
                  </div>
                </template>
              </div>
            </div>

            <!-- 添加新成本项表单 -->
            <transition name="fade">
              <div v-if="showAddForm" class="add-cost-form">
                <div class="add-form-header">
                  <span>添加新成本项</span>
                  <el-button text size="small" @click="cancelAddCostItem">✕</el-button>
                </div>
                <div class="add-form-body">
                  <div class="form-row">
                    <div class="form-item">
                      <label>名称</label>
                      <el-input
                        v-model="newCostItem.name"
                        placeholder="如：包装费"
                        size="small"
                      />
                    </div>
                    <div class="form-item">
                      <label>类型</label>
                      <el-select v-model="newCostItem.cost_type" size="small" style="width: 100%">
                        <el-option label="固定金额" value="fixed" />
                        <el-option label="按数量计算" value="per_unit" />
                        <el-option label="按百分比计算" value="percentage" />
                      </el-select>
                    </div>
                    <div class="form-item">
                      <label>数值</label>
                      <el-input
                        v-model.number="newCostItem.value"
                        type="number"
                        :min="0"
                        size="small"
                      >
                        <template #append>{{ getUnit(newCostItem.cost_type) }}</template>
                      </el-input>
                    </div>
                  </div>
                  <div class="form-row single">
                    <div class="form-item full">
                      <label>描述（可选）</label>
                      <el-input
                        v-model="newCostItem.description"
                        placeholder="简要说明此成本项的用途"
                        size="small"
                      />
                    </div>
                  </div>
                  <div class="form-actions">
                    <el-button size="small" @click="cancelAddCostItem">取消</el-button>
                    <el-button type="primary" size="small" @click="addCostItem">确认添加</el-button>
                  </div>
                </div>
              </div>
            </transition>
          </div>

          <!-- 公式说明 -->
          <div class="formula-tip">
            <p><strong>💡 智能定价公式：</strong></p>
            <code>建议价格 = 总成本 ÷ (1 - 目标毛利率)</code>
            <p class="sub-tip">总成本 = 固定成本 + (按数量成本 × 数量) + (基础成本 × 百分比成本)</p>
          </div>
        </el-tab-pane>

        <!-- 智能模型 -->
        <el-tab-pane label="🤖 智能模型" name="model">
          <div class="settings-section">
            <h3 class="section-title">🔗 已配置的模型</h3>
            
            <div class="model-configs-list">
              <div
                v-for="(config, index) in modelConfigs"
                :key="config.id"
                class="model-config-item"
              >
                <div class="model-header">
                  <div class="model-info">
                    <span class="model-name">{{ config.name }}</span>
                    <el-tag size="small" :type="config.enabled ? 'success' : 'info'">
                      {{ config.enabled ? '已启用' : '未启用' }}
                    </el-tag>
                  </div>
                  <div class="model-actions">
                    <el-switch v-model="config.enabled" size="small" />
                    <el-button
                      size="small"
                      :loading="testingModelId === config.id"
                      @click="testModelConnection(config)"
                    >
                      {{ testingModelId === config.id ? '测试中' : '测试' }}
                    </el-button>
                    <el-button
                      type="danger"
                      size="small"
                      @click="removeModelConfig(index)"
                    >
                      删除
                    </el-button>
                  </div>
                </div>
                
                <div class="model-details">
                  <div class="detail-row">
                    <label>服务商</label>
                    <el-select
                      v-model="config.provider"
                      size="small"
                      @change="handleModelProviderChange(config)"
                    >
                      <el-option label="DeepSeek" value="deepseek" />
                      <el-option label="小米大模型" value="xiaomi" />
                    </el-select>
                  </div>
                  <div class="detail-row">
                    <label>服务地址</label>
                    <el-input
                      v-model="config.api_base"
                      placeholder="服务地址，如 https://api.openai.com/v1"
                      size="small"
                    />
                  </div>
                  <div class="detail-row">
                    <label>访问密钥</label>
                    <el-input
                      v-model="config.api_key"
                      type="password"
                      placeholder="填入服务商提供的访问密钥；本地模型可留空"
                      size="small"
                      show-password
                    />
                  </div>
                  <div class="detail-row">
                    <label>模型名称</label>
                    <div style="display:flex; gap:8px; flex:1; align-items:center;">
                      <el-select
                        v-model="config.model_name"
                        size="small"
                        filterable
                        allow-create
                        default-first-option
                        placeholder="点右侧『获取模型』，或手动输入"
                        style="flex:1;"
                      >
                        <el-option
                          v-for="m in (modelOptions[config.id] || [])"
                          :key="m"
                          :label="m"
                          :value="m"
                        />
                      </el-select>
                      <el-button
                        size="small"
                        :loading="fetchingModelsId === config.id"
                        @click="fetchModels(config)"
                      >
                        {{ fetchingModelsId === config.id ? '获取中' : '获取模型' }}
                      </el-button>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 添加新模型配置 -->
            <div class="add-model-section">
              <h4>➕ 添加新模型</h4>
              <div class="add-model-form">
                <el-input
                  v-model="newModelConfig.name"
                  placeholder="给这个配置起个名字（如：我的 DeepSeek）"
                />
                <el-select
                  v-model="newModelConfig.provider"
                  @change="handleModelProviderChange(newModelConfig)"
                >
                  <el-option label="DeepSeek" value="deepseek" />
                  <el-option label="小米大模型" value="xiaomi" />
                </el-select>
                <el-input
                  v-model="newModelConfig.api_base"
                  placeholder="服务地址"
                />
                <el-input
                  v-model="newModelConfig.model_name"
                  placeholder="模型名称"
                />
                <el-button type="primary" @click="addModelConfig">
                  添加模型
                </el-button>
              </div>
            </div>
          </div>

          <!-- 功能说明 -->
          <div class="feature-tip">
            <p><strong>🎯 模型用途：</strong></p>
            <ul>
              <li>📝 <strong>智能标题生成</strong> - 根据产品信息自动生成抖音商品标题</li>
              <li>🏷️ <strong>智能分类</strong> - 自动识别商品类目</li>
              <li>💬 <strong>卖点提取</strong> - 提取产品卖点和关键词</li>
            </ul>
          </div>
        </el-tab-pane>

        <!-- 自动化设置标签页 -->
        <el-tab-pane label="🤖 自动化设置" name="automation">
          <div class="settings-section">
            <h3 class="section-title">
              <el-icon class="section-icon"><Promotion /></el-icon>
              发布方式
            </h3>
            <div class="mode-card-group">
              <label
                class="mode-card"
                :class="{ active: publishMode === 'dom' }"
              >
                <input type="radio" v-model="publishMode" value="dom" />
                <el-icon class="mode-icon"><Mouse /></el-icon>
                <div class="mode-text">
                  <div class="mode-name">浏览器自动发布</div>
                  <div class="mode-desc">像人工一样在浏览器里逐步填表，稳定但稍慢</div>
                </div>
                <el-tag size="small" type="info" effect="plain">推荐新手</el-tag>
              </label>
              <label
                class="mode-card"
                :class="{ active: publishMode === 'protocol' }"
              >
                <input type="radio" v-model="publishMode" value="protocol" />
                <el-icon class="mode-icon"><Lightning /></el-icon>
                <div class="mode-text">
                  <div class="mode-name">极速发布</div>
                  <div class="mode-desc">跳过界面操作直接提交，单个商品约 18 秒</div>
                </div>
                <el-tag size="small" type="success" effect="plain">最快</el-tag>
              </label>
              <label
                class="mode-card"
                :class="{ active: publishMode === 'official' }"
              >
                <input type="radio" v-model="publishMode" value="official" />
                <el-icon class="mode-icon"><Link /></el-icon>
                <div class="mode-text">
                  <div class="mode-name">抖店官方授权</div>
                  <div class="mode-desc">使用抖店开放平台官方接口，最稳定，需先申请授权</div>
                </div>
                <el-tag size="small" type="warning" effect="plain">需授权</el-tag>
              </label>
            </div>
          </div>

          <div class="settings-section">
            <h3 class="section-title">
              <el-icon class="section-icon"><Connection /></el-icon>
              采集方式
            </h3>
            <div class="capture-strategy-intro">
              1688 与 淘宝/天猫 是两个独立平台，采集协议互不交叉，需分别选择。
              主页粘贴链接时会按平台自动应用对应配置，无需手动切换。
            </div>
            <div class="capture-pref-list">
              <!-- 1688 -->
              <div class="capture-pref-row">
                <div class="capture-pref-platform">
                  <el-icon class="strategy-icon"><Lightning /></el-icon>
                  <div>
                    <div class="strategy-name">1688 商品链接</div>
                    <div class="strategy-host">detail.1688.com / offer.1688.com</div>
                  </div>
                </div>
                <el-radio-group v-model="capturePreferences.alibaba_1688_mode" size="small">
                  <el-radio-button value="dom">DOM 采集</el-radio-button>
                  <el-radio-button value="protocol">协议采集</el-radio-button>
                </el-radio-group>
              </div>

              <!-- 淘宝 / 天猫 -->
              <div class="capture-pref-row">
                <div class="capture-pref-platform">
                  <el-icon class="strategy-icon"><Connection /></el-icon>
                  <div>
                    <div class="strategy-name">淘宝 / 天猫商品链接</div>
                    <div class="strategy-host">item.taobao.com / detail.tmall.com</div>
                  </div>
                </div>
                <el-radio-group v-model="capturePreferences.taobao_tmall_mode" size="small">
                  <el-radio-button value="dom">DOM 采集</el-radio-button>
                  <el-radio-button value="protocol">协议采集</el-radio-button>
                </el-radio-group>
              </div>

              <!-- 店铺批量：无可配置项，保留说明 -->
              <div class="capture-pref-row capture-pref-row-static">
                <div class="capture-pref-platform">
                  <el-icon class="strategy-icon"><Mouse /></el-icon>
                  <div>
                    <div class="strategy-name">淘宝 / 天猫店铺链接</div>
                    <div class="strategy-host">shop*.taobao.com / *.m.tmall.com</div>
                  </div>
                </div>
                <div class="capture-pref-static-tag">
                  <el-tag size="small" type="info" effect="plain">浏览器批量翻页</el-tag>
                  <span class="strategy-desc">店铺采集只有单一路径，无需选择</span>
                </div>
              </div>
            </div>
            <div class="capture-strategy-tip">
              <el-icon><InfoFilled /></el-icon>
              <span>
                DOM 采集 = 读浏览器渲染数据，最稳定；
                协议采集 = 拦截网络请求（预览版，目前数据提取仍会走 DOM 路径，但会把协议层网络快照保存到工件目录便于抓包分析）。
              </span>
            </div>
          </div>

          <div class="settings-section">
            <h3 class="section-title">🚚 运费模板管理</h3>
            
            <!-- 当前使用的模板 -->
            <div class="current-template">
              <label>当前使用：</label>
              <el-select v-model="selectedShippingTemplate" placeholder="选择运费模板" class="template-select">
                <el-option
                  v-for="template in shippingTemplates"
                  :key="template"
                  :label="template"
                  :value="template"
                />
              </el-select>
            </div>
            
            <!-- 模板列表 -->
            <div class="template-list">
              <div
                v-for="(template, index) in shippingTemplates"
                :key="index"
                class="template-item"
                :class="{ active: template === selectedShippingTemplate }"
              >
                <span class="template-name">
                  <span v-if="template === selectedShippingTemplate" class="active-badge">✓</span>
                  {{ template }}
                </span>
                <div class="template-actions">
                  <el-button
                    v-if="template !== selectedShippingTemplate"
                    type="primary"
                    size="small"
                    class="template-use-btn"
                    @click="selectedShippingTemplate = template"
                  >
                    使用
                  </el-button>
                  <el-button
                    type="danger"
                    size="small"
                    class="automation-delete-btn"
                    :disabled="shippingTemplates.length <= 1"
                    @click="removeShippingTemplate(index)"
                  >
                    删除
                  </el-button>
                </div>
              </div>
            </div>
            
            <!-- 添加新模板 -->
            <div class="add-template-form">
              <el-input
                v-model="newTemplateName"
                placeholder="输入新的运费模板名称"
                class="template-input"
                @keyup.enter="addShippingTemplate"
              />
              <el-button type="primary" @click="addShippingTemplate">
                添加模板
              </el-button>
            </div>

            <h3 class="section-title material-title">🧵 产品材质面料</h3>
            <div class="material-config-panel" :class="{ invalid: materialSettingsInvalid }">
              <div class="material-list">
                <div
                  v-for="(item, index) in materialCompositions"
                  :key="`material-${index}`"
                  class="material-item"
                >
                  <el-select
                    v-model="item.material"
                    placeholder="选择或输入材质"
                    filterable
                    allow-create
                    default-first-option
                    :reserve-keyword="false"
                    class="material-name-input"
                  >
                    <el-option
                      v-for="option in materialOptions"
                      :key="`material-option-${option}`"
                      :label="option"
                      :value="option"
                    />
                  </el-select>
                  <el-input-number
                    v-model="item.percentage"
                    :min="1"
                    :max="100"
                    :precision="0"
                    :controls="false"
                    class="material-percentage-input"
                  />
                  <span class="material-unit">%</span>
                  <el-button
                    type="danger"
                    size="small"
                    class="automation-delete-btn"
                    :disabled="materialCompositions.length <= 1"
                    @click="removeMaterialComposition(index)"
                  >
                    删除
                  </el-button>
                </div>
              </div>
              <div class="add-material-form">
                <el-select
                  v-model="newMaterialName"
                  placeholder="选择或输入材质"
                  filterable
                  allow-create
                  default-first-option
                  :reserve-keyword="false"
                  class="material-name-input"
                >
                  <el-option
                    v-for="option in materialOptions"
                    :key="`new-material-option-${option}`"
                    :label="option"
                    :value="option"
                  />
                </el-select>
                <el-input-number
                  v-model="newMaterialPercentage"
                  :min="1"
                  :max="100"
                  :precision="0"
                  :controls="false"
                  class="material-percentage-input"
                />
                <span class="material-unit">%</span>
                <el-button type="primary" @click="addMaterialComposition">
                  添加材质
                </el-button>
              </div>
              <div class="material-total-row">
                <div class="material-total-label">
                  <span>含量总和</span>
                  <span
                    class="material-total-value"
                    :class="{ warning: materialPercentageTotal !== 100 }"
                  >
                    {{ materialPercentageTotal }}%
                  </span>
                  <span class="material-total-target">/ 100%</span>
                </div>
                <el-progress
                  :percentage="Math.min(materialPercentageTotal, 100)"
                  :status="materialPercentageTotal === 100 ? 'success' : (materialPercentageTotal > 100 ? 'exception' : undefined)"
                  :stroke-width="8"
                  :show-text="false"
                  class="material-progress"
                />
              </div>
              <div v-if="materialSettingsInvalid" class="material-warning-text">
                <el-icon><Warning /></el-icon>
                <span>材质名称不能为空，且含量总和必须等于 100%</span>
              </div>
              <div v-else-if="customMaterialNames.length" class="material-custom-text">
                <el-icon><Warning /></el-icon>
                <span>
                  自定义材质：{{ customMaterialNames.join("、") }}
                  —— 不在已知平台选项内，发布时若平台下拉搜不到该材质会报错，请确认名称与平台一致
                </span>
              </div>
            </div>

            <h3 class="section-title certificate-title">🏷️ 水洗标/吊牌图</h3>
            <div class="certificate-config-panel">
              <div class="certificate-file-info">
                <template v-if="washLabelTagImagePath">
                  <img
                    :src="washLabelTagImagePreviewUrl"
                    class="certificate-preview-img"
                    alt="水洗标/吊牌图"
                  />
                </template>
                <div v-else class="certificate-empty-tip">
                  当前未配置水洗标/吊牌图。发布页出现“水洗标/吊牌图”必填项时，自动化会优先上传商品目录中的吊牌图片；若商品目录没有，则使用这里配置的全局图片。
                </div>
              </div>
              <div class="certificate-actions">
                <el-button
                  type="primary"
                  :loading="washLabelTagImageLoading"
                  @click="selectWashLabelTagImage"
                >
                  {{ washLabelTagImagePath ? "重新选择图片" : "选择水洗标/吊牌图" }}
                </el-button>
                <el-button
                  :disabled="!washLabelTagImagePath || washLabelTagImageLoading"
                  @click="clearWashLabelTagImage"
                >
                  清空图片
                </el-button>
              </div>
            </div>
          </div>

          <!-- 配置说明 -->
          <div class="automation-tip">
            <p><strong>💡 配置说明：</strong></p>
            <ul>
              <li>📋 <strong>运费模板</strong> - 管理可用的运费模板列表，选择上传时使用的模板</li>
              <li>🧵 <strong>面料材质</strong> - 仅可选择平台材质选项，并确保总和为100%</li>
              <li>🏷️ <strong>水洗标/吊牌图</strong> - 优先使用商品目录中的吊牌图片；没有则使用这里配置的全局图片；如果两者都没有，就按上面的材质配置填写面料材质</li>
              <li>🔍 <strong>自动匹配</strong> - 脚本会在抖音运费模板下拉列表中查找匹配的选项</li>
              <li>⚠️ <strong>注意</strong> - 模板名称需与抖音后台设置的完全一致</li>
            </ul>
          </div>

          <!-- 帮助与引导 -->
          <div class="settings-section">
            <h3 class="section-title">📚 帮助与引导</h3>
            <div class="help-buttons">
              <el-button type="primary" plain class="guide-white-btn" @click="showOnboarding">
                📖 重新查看新手引导
              </el-button>
              <el-button plain @click="resetOnboarding">
                🔄 重置引导状态
              </el-button>
            </div>
            <p class="help-tip">如果您是第一次使用本工具，建议查看新手引导了解基本操作流程。</p>
          </div>
        </el-tab-pane>

        <el-tab-pane label="🧩 高级集成" name="mcp">
          <!-- 高级功能前置说明 -->
          <div class="mcp-intro-card">
            <el-icon class="intro-icon"><InfoFilled /></el-icon>
            <div class="intro-text">
              <div class="intro-title">这是给高级用户的功能，普通用户可以跳过本页</div>
              <div class="intro-desc">
                本页用于把本工具接入 Claude Desktop、Cursor 等 AI 客户端，让 AI 直接帮你采集、整理、发布商品。
                如果你只是想日常使用本工具完成发布，<strong>不需要做任何配置</strong>。
              </div>
            </div>
          </div>

          <!-- 运行环境概览 -->
          <div class="settings-section">
            <h3 class="section-title">
              <el-icon class="section-icon"><InfoFilled /></el-icon>
              运行环境概览
            </h3>
            <div class="mcp-env-grid">
              <div class="mcp-env-item">
                <div class="env-label">本地后端地址</div>
                <div class="env-value"><code>{{ backendUrl }}</code></div>
              </div>
              <div class="mcp-env-item">
                <div class="env-label">运行模式</div>
                <div class="env-value">
                  <el-tag size="small" :type="appInfo.runtime_mode === 'packaged' ? 'success' : 'info'">
                    {{ runtimeModeLabel }}
                  </el-tag>
                </div>
              </div>
              <div class="mcp-env-item">
                <div class="env-label">推荐启动方式</div>
                <div class="env-value">
                  <el-tag size="small" type="primary">{{ preferredMcpModeLabel }}</el-tag>
                </div>
              </div>
              <div class="mcp-env-item">
                <div class="env-label">MCP 入口</div>
                <div class="env-value">
                  <el-icon v-if="appInfo.mcp_server_entry_exists" class="env-state ok"><CircleCheck /></el-icon>
                  <el-icon v-else class="env-state miss"><Warning /></el-icon>
                  <code>{{ mcpServerPath }}</code>
                </div>
              </div>
              <div class="mcp-env-item">
                <div class="env-label">Skill 目录</div>
                <div class="env-value">
                  <el-icon v-if="appInfo.skill_dir_exists" class="env-state ok"><CircleCheck /></el-icon>
                  <el-icon v-else class="env-state miss"><Warning /></el-icon>
                  <code>{{ skillPath }}</code>
                </div>
              </div>
              <div class="mcp-env-item" v-if="mcpExecutablePath">
                <div class="env-label">独立 MCP EXE</div>
                <div class="env-value">
                  <el-icon class="env-state ok"><CircleCheck /></el-icon>
                  <code>{{ mcpExecutablePath }}</code>
                </div>
              </div>
            </div>
            <div class="mcp-hint">
              <el-icon><InfoFilled /></el-icon>
              <span>{{ mcpLaunchHint }}</span>
            </div>
            <div v-if="mcpAvailabilityHint" class="mcp-hint warning">
              <el-icon><Warning /></el-icon>
              <span>{{ mcpAvailabilityHint }}</span>
            </div>
          </div>

          <!-- 本地 stdio 启动 -->
          <div class="settings-section">
            <div class="section-header">
              <h3 class="section-title">
                <el-icon class="section-icon"><Cpu /></el-icon>
                本地 stdio 启动
              </h3>
              <el-button size="small" :icon="CopyDocument" @click="copyGuideText(mcpStdioCommand, 'stdio 命令')">
                复制命令
              </el-button>
            </div>
            <div class="deploy-guide-card">
              <pre class="guide-code">{{ mcpStdioCommand }}</pre>
              <p class="guide-note">适合通过 stdio 直接接入支持 MCP 的客户端，例如 Claude Desktop、Cursor。</p>
            </div>
          </div>

          <!-- Streamable HTTP 启动 -->
          <div class="settings-section">
            <div class="section-header">
              <h3 class="section-title">
                <el-icon class="section-icon"><Connection /></el-icon>
                Streamable HTTP 启动
              </h3>
              <el-button size="small" :icon="CopyDocument" @click="copyGuideText(mcpHttpCommand, 'HTTP 命令')">
                复制命令
              </el-button>
            </div>
            <div class="deploy-guide-card">
              <pre class="guide-code">{{ mcpHttpCommand }}</pre>
              <p class="guide-note">HTTP 端点：<code>{{ mcpHttpEndpoint }}</code></p>
              <p class="guide-note">HTTP 模式主要用于本地调试。如果已有独立 MCP EXE，优先使用 stdio(EXE) 以避免依赖 Node。</p>
            </div>
          </div>

          <!-- 客户端 MCP 配置示例 -->
          <div class="settings-section">
            <div class="section-header">
              <h3 class="section-title">
                <el-icon class="section-icon"><Setting /></el-icon>
                客户端 MCP 配置示例
              </h3>
              <el-button size="small" :icon="CopyDocument" @click="copyGuideText(mcpClientConfig, 'MCP 配置')">
                复制配置
              </el-button>
            </div>
            <div class="deploy-guide-card">
              <pre class="guide-code">{{ mcpClientConfig }}</pre>
              <p class="guide-note">该配置基于当前机器的运行时路径自动生成，而非硬编码的开发路径。</p>
              <p class="guide-note">将上面的 JSON 合并到支持 MCP 的客户端配置里即可生效。</p>
            </div>
          </div>

          <!-- Skills 安装说明 -->
          <div class="settings-section">
            <div class="section-header">
              <h3 class="section-title">
                <el-icon class="section-icon"><Box /></el-icon>
                Skills 安装说明
              </h3>
              <el-button size="small" :icon="CopyDocument" @click="copyGuideText(skillPath, 'Skill 路径')">
                复制路径
              </el-button>
            </div>
            <div class="deploy-guide-card">
              <ul class="deploy-guide-list">
                <li>支持本地 Skills 的客户端，可以直接引用目录 <code>{{ skillPath }}</code></li>
                <li>Skill 名称是 <code>douyin-publisher-mcp</code>，会指导模型按安全顺序使用导入、标题、定价、校验、上传能力</li>
                <li>如果客户端不支持 Skills，也可以只接入 MCP，能力仍然可用</li>
                <li>建议先调用 <code>health_check</code>，再执行采集、导入、定价或上传</li>
              </ul>
              <p v-if="!appInfo.skill_dir_exists" class="guide-note">当前运行环境中未找到 Skill 目录。如果是安装包构建，请把 Skill 文件作为资源一并打包。</p>
            </div>
          </div>

          <!-- 仓库内说明文件 -->
          <div class="settings-section">
            <h3 class="section-title">
              <el-icon class="section-icon"><Document /></el-icon>
              仓库内说明文件
            </h3>
            <div class="deploy-guide-card">
              <p class="guide-note">MCP 详细说明：<code>{{ mcpReadmePath }}</code></p>
              <p class="guide-note">Skill 入口目录：<code>{{ skillPath }}</code></p>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="ℹ️ 关于" name="about">
          <div class="settings-section">
            <h3 class="section-title">
              <el-icon class="section-icon"><InfoFilled /></el-icon>
              关于与更新
            </h3>
            <div class="mcp-env-grid">
              <div class="mcp-env-item">
                <div class="env-label">当前版本</div>
                <div class="env-value">
                  <el-tag size="small" type="success">v{{ appVersion || "—" }}</el-tag>
                </div>
              </div>
              <div class="mcp-env-item">
                <div class="env-label">软件更新</div>
                <div class="env-value">
                  <el-button
                    type="primary"
                    size="small"
                    :loading="checkingUpdate"
                    @click="handleCheckUpdate"
                  >
                    {{ checkingUpdate ? "检查中" : "检查更新" }}
                  </el-button>
                </div>
              </div>
            </div>
            <div class="mcp-hint">
              <el-icon><InfoFilled /></el-icon>
              <span>点击「检查更新」会从官方发布源获取最新版本；有新版时可一键下载并自动安装、重启。更新为整包下载（含后端，体积较大），更新前请先确保没有正在进行的采集 / 发布任务。</span>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
    <div class="settings-footer">
      <div class="footer-status">
        <template v-if="loadFailed">
          <el-icon class="status-icon failed"><Warning /></el-icon>
          <span class="status-text failed">设置加载失败，已禁用保存（当前显示的是默认值，保存会覆盖后端真实配置）</span>
          <span v-if="loadErrorMessage" class="status-error-detail" :title="loadErrorMessage">
            {{ loadErrorMessage }}
          </span>
          <el-button size="small" :loading="loading" @click="loadSettings">重试加载</el-button>
        </template>
        <template v-else-if="hasUnsavedChanges">
          <el-icon class="status-icon dirty"><Warning /></el-icon>
          <span class="status-text dirty">有未保存的更改</span>
        </template>
        <template v-else>
          <el-icon class="status-icon clean"><CircleCheck /></el-icon>
          <span class="status-text clean">所有更改已保存</span>
        </template>
      </div>
      <div class="footer-actions">
        <el-button
          type="primary"
          size="large"
          :loading="loading"
          :disabled="loadFailed || (!hasUnsavedChanges && !loading)"
          @click="handleSave"
        >
          <el-icon><Promotion /></el-icon>
          <span style="margin-left: 6px">保存设置</span>
        </el-button>
      </div>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.settings-panel {
  background: var(--card-background);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: 20px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
  overflow: hidden;
}

.settings-content {
  flex: 1;
  min-height: 0;
  // 滚动下放到 .el-tabs__content：让 tab 标签栏完全脱离滚动区域
  overflow: hidden;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.settings-tabs {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;

  // Tab 头：在滚动区域之外，自然固定在顶部，不会有滚动条穿过
  :deep(.el-tabs__header) {
    flex-shrink: 0;
    margin: 0 0 16px 0;
    padding: 0 20px 0 10px;
    background: var(--card-background-solid);
    border-bottom: 1px solid rgba(92, 124, 250, 0.1);
  }

  // Tab 内容区：真正的滚动容器，滚动条只出现在这里
  :deep(.el-tabs__content) {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
    // 底部留出 32px 呼吸空间，避免滚到底时最后一行紧贴 footer 看起来被截
    padding: 0 20px 32px 10px;
  }

  :deep(.el-tab-pane) {
    height: auto;
  }

  :deep(.el-tabs__item) {
    font-size: 15px;
    padding: 0 24px;
  }
}

// ========== 布局间距优化 ==========

.settings-section {
  margin-bottom: 28px;
  
  &:last-child {
    margin-bottom: 0;
  }
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 16px 0;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(92, 124, 250, 0.12);
}

// 利润率配置行
.config-row {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  padding: 12px 20px;
  background: rgba(92, 124, 250, 0.03);
  border-radius: 10px;
}

.config-item {
  display: flex;
  align-items: center;
  gap: 12px;

  label {
    font-size: 14px;
    color: var(--text-secondary);
    white-space: nowrap;
  }
}

.config-input {
  display: flex;
  align-items: center;
  gap: 6px;

  .el-input {
    width: 90px;
  }

  .unit {
    font-size: 14px;
    color: var(--text-secondary);
    font-weight: 500;
  }
}

// Section头部（带按钮）
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(92, 124, 250, 0.12);
  
  .section-title {
    margin: 0;
    padding: 0;
    border: none;
  }
}

// 成本汇总
.cost-summary {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  padding: 16px 24px;
  background: linear-gradient(135deg, rgba(92, 124, 250, 0.06), rgba(156, 136, 255, 0.03));
  border-radius: 10px;
  margin-bottom: 18px;
  
  .summary-item {
    display: flex;
    flex-direction: column;
    gap: 4px;
    text-align: center;
    
    .label {
      font-size: 12px;
      color: var(--text-secondary);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    
    .value {
      font-size: 18px;
      font-weight: 600;
      color: var(--text-primary);
    }
  }
}

// 成本项目列表
.cost-items-compact {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 20px;
}

.cost-item-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 20px;
  background: #fff;
  border: 1px solid rgba(92, 124, 250, 0.1);
  border-radius: 10px;
  transition: all 0.15s ease;
  min-height: 56px;
  
  &:hover {
    border-color: rgba(92, 124, 250, 0.2);
    background: rgba(92, 124, 250, 0.015);
  }
  
  &.editing {
    border-color: var(--primary-color);
    background: rgba(92, 124, 250, 0.04);
    padding: 16px 20px;
    box-shadow: 0 2px 10px rgba(92, 124, 250, 0.12);
  }
}

.item-info {
  display: flex;
  align-items: center;
  gap: 20px;
  flex: 1;
  
  .item-value {
    font-size: 16px;
    font-weight: 600;
    color: var(--primary-color);
    min-width: 70px;
  }
  
  .item-name {
    font-size: 14px;
    font-weight: 500;
    color: var(--text-primary);
  }
  
  .item-desc {
    font-size: 13px;
    color: var(--text-secondary);
    margin-left: auto;
    max-width: 300px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.item-actions {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-left: 16px;
  
  .el-button {
    padding: 6px 16px;
    font-size: 13px;
  }
}

// 编辑模式容器
.edit-mode-container {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

// 编辑表单标题行
.edit-labels {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 4px;
  
  .label-item {
    font-size: 11px;
    color: var(--text-secondary);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.3px;
  }
  
  .label-name {
    width: 100px;
  }
  
  .label-value {
    width: 90px;
  }
  
  .label-type {
    width: 110px;
  }
  
  .label-desc {
    flex: 1;
    min-width: 150px;
  }
  
  .label-action {
    width: 60px;
  }
}

// 编辑表单 - 单行布局
.edit-form {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
}

.edit-name {
  width: 100px;
  
  :deep(.el-input__inner) {
    font-size: 13px;
  }
}

.edit-type {
  width: 110px;
  
  :deep(.el-select__wrapper) {
    font-size: 13px;
  }
}

.edit-value {
  width: 90px;
  
  :deep(.el-input__inner) {
    font-size: 13px;
    text-align: center;
  }
  
  .unit-suffix {
    font-size: 12px;
    color: var(--text-secondary);
    font-weight: 500;
    margin-right: 4px;
  }
}

.edit-desc {
  flex: 1;
  min-width: 150px;
  
  :deep(.el-input__inner) {
    font-size: 13px;
  }
}

// 添加成本项表单
.add-cost-form {
  background: linear-gradient(135deg, rgba(105, 219, 124, 0.05), rgba(105, 219, 124, 0.02));
  border: 1px solid rgba(105, 219, 124, 0.2);
  border-radius: 10px;
  overflow: hidden;
  margin-bottom: 20px;
  
  .add-form-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    background: rgba(105, 219, 124, 0.06);
    font-size: 14px;
    font-weight: 500;
    color: var(--success-color);
    
    .close-btn {
      padding: 4px 8px;
      font-size: 16px;
      cursor: pointer;
      opacity: 0.6;
      
      &:hover {
        opacity: 1;
      }
    }
  }
  
  .add-form-body {
    padding: 16px 20px;
  }
  
  .form-row {
    display: flex;
    gap: 10px;
    margin-bottom: 10px;
    
    &.single {
      margin-bottom: 12px;
    }
    
    &:last-child {
      margin-bottom: 0;
    }
  }
  
  .form-item {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 3px;
    
    &.full {
      flex: 1;
    }
    
    label {
      font-size: 11px;
      color: var(--text-secondary);
      font-weight: 500;
    }
  }
  
  .form-actions {
    display: flex;
    justify-content: flex-end;
    gap: 6px;
    padding-top: 4px;
  }
}

// 智能定价公式区域
.pricing-formula {
  background: linear-gradient(135deg, rgba(255, 193, 7, 0.06), rgba(255, 193, 7, 0.02));
  border: 1px solid rgba(255, 193, 7, 0.15);
  border-radius: 8px;
  padding: 12px 14px;
  margin-top: 8px;
  
  p {
    margin: 0 0 6px 0;
    font-size: 12px;
    
    &:last-child {
      margin-bottom: 0;
      font-size: 11px;
      color: var(--text-secondary);
    }
  }
  
  strong {
    color: var(--text-primary);
  }
  
  code {
    display: inline-block;
    background: rgba(92, 124, 250, 0.08);
    padding: 4px 10px;
    border-radius: 4px;
    font-family: 'SF Mono', Monaco, 'Consolas', monospace;
    font-size: 12px;
    color: var(--primary-color);
    margin: 4px 0;
  }
}

// 过渡动画
.fade-enter-active,
.fade-leave-active {
  transition: all 0.25s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

.unit {
  font-size: 13px;
  color: var(--text-secondary);
  min-width: 20px;
}

// 公式说明
.formula-tip {
  padding: 14px 20px;
  background: linear-gradient(135deg, rgba(255, 193, 7, 0.06), rgba(255, 193, 7, 0.02));
  border: 1px solid rgba(255, 193, 7, 0.12);
  border-radius: 10px;
  font-size: 13px;
  margin-top: 16px;

  p {
    margin: 0 0 8px;
    
    &:first-child {
      margin-bottom: 10px;
    }
  }

  code {
    display: block;
    padding: 10px 14px;
    background: rgba(92, 124, 250, 0.08);
    border-radius: 6px;
    font-family: 'SF Mono', Monaco, 'Consolas', monospace;
    font-size: 13px;
    color: var(--primary-color);
    margin-bottom: 8px;
  }

  .sub-tip {
    font-size: 12px;
    color: var(--text-secondary);
    margin: 0;
  }
}

// 模型配置列表
.model-configs-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 20px;
}

.model-config-item {
  padding: 16px;
  background: rgba(92, 124, 250, 0.03);
  border: 1px solid rgba(92, 124, 250, 0.1);
  border-radius: 8px;
}

.model-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.model-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.model-name {
  font-weight: 600;
  font-size: 14px;
}

.model-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.model-details {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.detail-row {
  display: flex;
  flex-direction: column;
  gap: 4px;

  label {
    font-size: 12px;
    color: var(--text-secondary);
  }
}

// 添加模型
.add-model-section {
  padding: 16px;
  background: rgba(105, 219, 124, 0.05);
  border: 1px dashed rgba(105, 219, 124, 0.4);
  border-radius: 8px;

  h4 {
    margin: 0 0 12px;
    font-size: 14px;
    color: var(--success-color);
  }
}

.add-model-form {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;

  .el-button {
    grid-column: span 2;
    justify-self: start;
  }
}

// 功能说明
.feature-tip {
  padding: 12px 16px;
  background: rgba(92, 124, 250, 0.05);
  border-radius: 8px;
  font-size: 13px;

  p {
    margin: 0 0 8px;
  }

  ul {
    margin: 0;
    padding-left: 20px;
  }

  li {
    margin-bottom: 4px;
  }
}

// 自动化设置
.current-template {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding: 12px;
  background: rgba(92, 124, 250, 0.05);
  border-radius: 8px;

  label {
    font-size: 14px;
    font-weight: 500;
    color: var(--text-primary);
    white-space: nowrap;
  }
}

.template-select {
  width: 200px;
}

.template-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.template-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  background: #fff;
  border: 1px solid rgba(92, 124, 250, 0.15);
  border-radius: 6px;
  transition: all 0.2s ease;

  &:hover {
    border-color: rgba(92, 124, 250, 0.3);
    background: rgba(92, 124, 250, 0.02);
  }

  &.active {
    border-color: var(--primary-color);
    background: rgba(92, 124, 250, 0.05);
  }
}

.template-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--text-primary);
}

.active-badge {
  color: var(--success-color);
  font-weight: bold;
}

.template-actions {
  display: flex;
  gap: 4px;
}

.automation-delete-btn {
  color: #fff !important;
}

.template-use-btn {
  // 强制保证文字始终白色，避免被全局 el-button text 默认色或主题色覆盖
  color: #fff !important;
}

.add-template-form {
  display: flex;
  gap: 12px;
  padding: 12px;
  background: rgba(105, 219, 124, 0.05);
  border: 1px dashed rgba(105, 219, 124, 0.4);
  border-radius: 8px;
}

.template-input {
  flex: 1;
  max-width: 300px;
}

.material-title {
  margin-top: 20px;
}

.material-config-panel {
  padding: 12px;
  border: 1px solid rgba(92, 124, 250, 0.2);
  border-radius: 10px;
  background: rgba(92, 124, 250, 0.03);
}

.material-config-panel.invalid {
  border-color: var(--danger-color);
  box-shadow: 0 0 0 1px rgba(245, 108, 108, 0.25) inset;
}

.material-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}

.material-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid rgba(92, 124, 250, 0.15);
  border-radius: 8px;
  background: rgba(92, 124, 250, 0.02);
}

.material-name-input {
  width: 240px;
}

.material-percentage-input {
  width: 120px;
}

.material-unit {
  font-size: 13px;
  color: var(--text-secondary);
}

.add-material-form {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  border: 1px dashed rgba(105, 219, 124, 0.4);
  border-radius: 8px;
  background: rgba(105, 219, 124, 0.05);
}

.material-total {
  margin-top: 10px;
  font-size: 13px;
  color: var(--text-secondary);
}

.material-total.warning {
  color: var(--danger-color);
}

.material-warning-text {
  margin-top: 8px;
  font-size: 12px;
  color: var(--danger-color);
}

.certificate-title {
  margin-top: 20px;
}

.certificate-config-panel {
  padding: 14px;
  border: 1px solid rgba(92, 124, 250, 0.2);
  border-radius: 10px;
  background: rgba(92, 124, 250, 0.03);
}

.certificate-file-info {
  margin-bottom: 12px;
}

.certificate-preview-img {
  max-width: 200px;
  max-height: 160px;
  object-fit: contain;
  border-radius: 8px;
  border: 1px solid rgba(92, 124, 250, 0.15);
  background: #fff;
  padding: 4px;
}

.certificate-empty-tip {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.certificate-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.automation-tip {
  padding: 12px 16px;
  background: rgba(92, 124, 250, 0.05);
  border-radius: 8px;
  font-size: 13px;
  margin-top: 20px;

  p {
    margin: 0 0 8px;
  }

  ul {
    margin: 0;
    padding-left: 20px;
  }

  li {
    margin-bottom: 4px;
  }
}

// 帮助与引导
.help-buttons {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

.guide-white-btn {
  --el-button-text-color: #fff;
  --el-button-hover-text-color: #fff;
  --el-button-active-text-color: #fff;
}

.help-tip {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0;
}

.deploy-guide-card {
  padding: 16px;
  background: rgba(92, 124, 250, 0.05);
  border: 1px solid rgba(92, 124, 250, 0.12);
  border-radius: 10px;
}

.deploy-guide-list {
  margin: 0;
  padding-left: 20px;

  li {
    margin-bottom: 8px;
    line-height: 1.6;
  }
}

.guide-code {
  margin: 0;
  padding: 14px;
  background: rgba(15, 23, 42, 0.88);
  color: #e2e8f0;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

.guide-note {
  margin: 12px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
}

// ========== Sticky 底部保存栏 ==========
.settings-footer {
  flex-shrink: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 14px 24px;
  margin: 16px -20px -20px;
  background: rgba(255, 255, 255, 0.96);
  border-top: 1px solid rgba(92, 124, 250, 0.12);
  backdrop-filter: blur(8px);
  position: sticky;
  bottom: 0;
  z-index: 5;
}

.footer-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;

  .status-icon {
    font-size: 16px;

    &.dirty {
      color: var(--warning-light);
    }

    &.clean {
      color: var(--success-color);
    }

    &.failed {
      color: var(--danger-color);
    }
  }

  .status-text {
    &.dirty {
      color: var(--warning-light);
      font-weight: 500;
    }

    &.clean {
      color: var(--text-secondary);
    }

    &.failed {
      color: var(--danger-color);
      font-weight: 500;
    }
  }

  .status-error-detail {
    max-width: 340px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    font-size: 12px;
    color: var(--text-secondary);
  }
}

.footer-actions {
  display: flex;
  gap: 12px;
}

// ========== Section 标题带图标 ==========
.section-title {
  display: flex;
  align-items: center;
  gap: 8px;

  .section-icon {
    color: var(--primary-color);
    font-size: 18px;
  }
}

// ========== 发布/采集方式 - 卡片单选 ==========
.mode-card-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.mode-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  background: #fff;
  border: 1.5px solid rgba(92, 124, 250, 0.15);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
  position: relative;

  // 隐藏原生 radio 但保留可访问性
  input[type="radio"] {
    position: absolute;
    opacity: 0;
    width: 0;
    height: 0;
  }

  &:hover {
    border-color: var(--primary-color);
    background: rgba(92, 124, 250, 0.03);
  }

  &.active {
    border-color: var(--primary-color);
    background: linear-gradient(135deg, rgba(92, 124, 250, 0.08), rgba(116, 143, 252, 0.04));
    box-shadow: 0 2px 12px rgba(92, 124, 250, 0.12);

    .mode-icon {
      color: var(--primary-color);
      transform: scale(1.05);
    }

    .mode-name {
      color: var(--primary-color);
    }
  }

  &.disabled {
    cursor: not-allowed;
    opacity: 0.55;
    background: rgba(0, 0, 0, 0.02);

    &:hover {
      border-color: rgba(92, 124, 250, 0.15);
      background: rgba(0, 0, 0, 0.02);
      box-shadow: none;
    }

    .mode-icon {
      color: var(--text-placeholder);
      transform: none;
    }

    .mode-name {
      color: var(--text-secondary);
    }
  }

  .mode-icon {
    font-size: 24px;
    color: var(--text-secondary);
    flex-shrink: 0;
    transition: all var(--transition-fast) ease;
  }

  .mode-text {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 2px;

    .mode-name {
      font-size: 14px;
      font-weight: 600;
      color: var(--text-primary);
    }

    .mode-desc {
      font-size: 12px;
      color: var(--text-secondary);
      line-height: 1.5;
    }
  }
}

// ========== 材质含量进度 ==========
.material-total-row {
  margin-top: 12px;
}

.material-total-label {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 6px;

  .material-total-value {
    font-size: 16px;
    font-weight: 700;
    color: var(--success-color);

    &.warning {
      color: var(--danger-color);
    }
  }

  .material-total-target {
    font-size: 12px;
    color: var(--text-placeholder);
  }
}

.material-progress {
  width: 100%;
}

.material-custom-text {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 6px 12px;
  background: rgba(230, 162, 60, 0.08);
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--el-color-warning, #e6a23c);
  line-height: 1.5;

  .el-icon {
    flex-shrink: 0;
    font-size: 14px;
  }
}

.material-warning-text {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 6px 12px;
  background: rgba(255, 138, 128, 0.08);
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--danger-color);

  .el-icon {
    font-size: 14px;
  }
}

// ========== MCP Tab - 环境概览网格 ==========
.mcp-env-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.mcp-env-item {
  padding: 12px 14px;
  background: #fff;
  border: 1px solid rgba(92, 124, 250, 0.12);
  border-radius: var(--radius-sm);
  display: flex;
  flex-direction: column;
  gap: 6px;

  .env-label {
    font-size: 12px;
    color: var(--text-secondary);
    font-weight: 500;
  }

  .env-value {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: var(--text-primary);
    word-break: break-all;

    code {
      flex: 1;
      background: rgba(92, 124, 250, 0.06);
      padding: 2px 8px;
      border-radius: 4px;
      font-family: "SF Mono", Consolas, monospace;
      font-size: 12px;
      color: var(--primary-color);
    }

    .env-state {
      flex-shrink: 0;
      font-size: 14px;

      &.ok {
        color: var(--success-color);
      }

      &.miss {
        color: var(--danger-color);
      }
    }
  }
}

.mcp-hint {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(92, 124, 250, 0.05);
  border-left: 3px solid var(--primary-color);
  border-radius: var(--radius-sm);
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary);
  margin-top: 8px;

  .el-icon {
    color: var(--primary-color);
    flex-shrink: 0;
    margin-top: 2px;
  }

  &.warning {
    background: rgba(255, 138, 128, 0.06);
    border-left-color: var(--danger-color);

    .el-icon {
      color: var(--danger-color);
    }
  }
}

// ========== 设置面板自身的滚动布局调整 ==========
.settings-panel {
  position: relative;
}

// ========== 采集策略 / 采集偏好（每平台独立可配置） ==========
.capture-strategy-intro {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 12px;
}

.capture-pref-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.capture-pref-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  background: #fff;
  border: 1px solid rgba(92, 124, 250, 0.12);
  border-radius: var(--radius-md);
  transition: border-color var(--transition-fast) ease;

  &:hover {
    border-color: rgba(92, 124, 250, 0.25);
  }

  &.capture-pref-row-static {
    background: rgba(92, 124, 250, 0.02);
  }
}

.capture-pref-platform {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;

  .strategy-icon {
    flex-shrink: 0;
    font-size: 20px;
    color: var(--primary-color);
  }

  .strategy-name {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .strategy-host {
    font-size: 11px;
    color: var(--text-placeholder);
    font-family: "SF Mono", Consolas, monospace;
    margin-top: 2px;
  }
}

.capture-pref-static-tag {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  flex-shrink: 0;
  text-align: right;

  .strategy-desc {
    font-size: 12px;
    color: var(--text-secondary);
  }
}

.capture-strategy-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding: 10px 14px;
  background: rgba(92, 124, 250, 0.04);
  border-left: 3px solid var(--primary-color);
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--text-secondary);

  .el-icon {
    color: var(--primary-color);
    flex-shrink: 0;
  }
}

// ========== 高级集成 Tab 顶部说明卡 ==========
.mcp-intro-card {
  display: flex;
  gap: 12px;
  padding: 14px 18px;
  margin-bottom: 20px;
  background: linear-gradient(135deg, rgba(255, 193, 7, 0.08), rgba(255, 193, 7, 0.02));
  border: 1px solid rgba(255, 193, 7, 0.25);
  border-radius: var(--radius-md);

  .intro-icon {
    font-size: 22px;
    color: #f59e0b;
    flex-shrink: 0;
    margin-top: 1px;
  }

  .intro-text {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 6px;
    line-height: 1.6;
  }

  .intro-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .intro-desc {
    font-size: 13px;
    color: var(--text-secondary);

    strong {
      color: var(--text-primary);
    }
  }
}
</style>

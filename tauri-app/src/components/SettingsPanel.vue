<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, tauriCommands } from "@/services/api";
import type {
  AutomationConfig,
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
const captureMode = ref("dom");
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
  const allowed = new Set(materialOptions.value);
  const hasInvalidMaterial = materialCompositions.value.some(
    (item) => !item.material || !allowed.has(item.material)
  );
  return materialPercentageTotal.value !== 100 || hasInvalidMaterial;
});
const washLabelTagImagePreviewUrl = computed(() => {
  const p = washLabelTagImagePath.value.trim();
  if (!p) return "";
  return `http://127.0.0.1:5001/settings/automation/wash-label/preview?t=${Date.now()}`;
});

function addMaterialComposition() {
  const material = newMaterialName.value.trim();
  const percentage = Number(newMaterialPercentage.value);
  if (!material) {
    ElMessage.warning("请选择平台材质");
    return;
  }
  if (!materialOptions.value.includes(material)) {
    ElMessage.warning("材质不在平台可选列表内");
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

const DS_FREE_API_BASE_URL = "http://127.0.0.1:8000/v1";
const DS_FREE_API_MODEL = "deepseek-v4-pro";
const OPENAI_BASE_URL = "https://api.openai.com/v1";
const OPENAI_DEFAULT_MODEL = "gpt-3.5-turbo";
const OLLAMA_BASE_URL = "http://localhost:11434";
const OLLAMA_DEFAULT_MODEL = "qwen2.5:7b";
const KNOWN_MODEL_BASE_URLS = new Set([DS_FREE_API_BASE_URL, OPENAI_BASE_URL, OLLAMA_BASE_URL]);
const KNOWN_MODEL_NAMES = new Set([DS_FREE_API_MODEL, OPENAI_DEFAULT_MODEL, OLLAMA_DEFAULT_MODEL]);
const LEGACY_DEEPSEEK_MODEL_NAMES = new Set([
  "deepseek-chat",
  "deepseek-coder",
  "deepseek-r1",
  "deepseek-reasoner",
  "deepseek-search",
  "deepseek-r1-search",
]);

function createDsFreeApiModelConfig(): ModelConfig {
  return {
    id: "ds-free-api",
    name: "DeepSeek V4 Pro（ds-free-api）",
    provider: "ds-free-api",
    api_key: "",
    api_base: DS_FREE_API_BASE_URL,
    model_name: DS_FREE_API_MODEL,
    enabled: false,
  };
}

function createOpenAiModelConfig(): ModelConfig {
  return {
    id: "1",
    name: "OpenAI GPT",
    provider: "openai",
    api_key: "",
    api_base: OPENAI_BASE_URL,
    model_name: OPENAI_DEFAULT_MODEL,
    enabled: false,
  };
}

function createOllamaModelConfig(): ModelConfig {
  return {
    id: "2",
    name: "本地 Ollama",
    provider: "ollama",
    api_key: "",
    api_base: OLLAMA_BASE_URL,
    model_name: OLLAMA_DEFAULT_MODEL,
    enabled: false,
  };
}

function createNewModelConfig(): ModelConfig {
  return {
    id: "",
    name: "",
    provider: "ds-free-api",
    api_key: "",
    api_base: DS_FREE_API_BASE_URL,
    model_name: DS_FREE_API_MODEL,
    enabled: true,
  };
}

function isLegacyDeepSeekConfig(config: ModelConfig): boolean {
  const modelName = String(config.model_name || "").trim();
  return config.provider === "deepseek" || LEGACY_DEEPSEEK_MODEL_NAMES.has(modelName);
}

function normalizeModelConfigs(source?: ModelConfig[] | null): ModelConfig[] {
  const list = Array.isArray(source) ? source : [];
  const normalized = list.map((config) => {
    const next = { ...config };

    if (isLegacyDeepSeekConfig(next)) {
      next.provider = "ds-free-api";
      next.api_base = DS_FREE_API_BASE_URL;
      next.model_name = DS_FREE_API_MODEL;
      if (!next.name.trim() || next.name.toLowerCase().includes("deepseek")) {
        next.name = "DeepSeek V4 Pro（ds-free-api）";
      }
    }

    return next;
  });

  const hasDsFreeApi = normalized.some(
    (config) => config.provider === "ds-free-api" || config.model_name === DS_FREE_API_MODEL
  );

  return hasDsFreeApi ? normalized : [createDsFreeApiModelConfig(), ...normalized];
}

const modelConfigs = ref<ModelConfig[]>(
  normalizeModelConfigs([createOpenAiModelConfig(), createOllamaModelConfig()])
);

// 新增模型配置
const newModelConfig = ref<ModelConfig>(createNewModelConfig());

function applyModelProviderDefaults(config: ModelConfig): void {
  const shouldReplaceBaseUrl =
    !config.api_base.trim() || KNOWN_MODEL_BASE_URLS.has(config.api_base.trim());
  const shouldReplaceModel =
    !config.model_name.trim() || KNOWN_MODEL_NAMES.has(config.model_name.trim());

  switch (config.provider) {
    case "ds-free-api":
      if (!config.name.trim() || config.name === "OpenAI GPT" || config.name === "本地 Ollama") {
        config.name = "DeepSeek V4 Pro（ds-free-api）";
      }
      config.api_base = DS_FREE_API_BASE_URL;
      config.model_name = DS_FREE_API_MODEL;
      break;
    case "openai":
      if (shouldReplaceBaseUrl) {
        config.api_base = OPENAI_BASE_URL;
      }
      if (shouldReplaceModel) {
        config.model_name = OPENAI_DEFAULT_MODEL;
      }
      break;
    case "ollama":
      if (shouldReplaceBaseUrl) {
        config.api_base = OLLAMA_BASE_URL;
      }
      if (shouldReplaceModel) {
        config.model_name = OLLAMA_DEFAULT_MODEL;
      }
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

// 测试模型连接
async function testModelConnection(config: ModelConfig) {
  ElMessage.info(`正在测试 ${config.name} 连接...`);
  // TODO: 实现实际的连接测试
  setTimeout(() => {
    ElMessage.success(`${config.name} 连接成功`);
  }, 1000);
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

function escapeForPowerShell(path: string) {
  return path.replace(/'/g, "''");
}

function escapeForJson(path: string) {
  return path.replace(/\\/g, "\\\\");
}

const backendUrl = computed(() => appInfo.value.backend_url || "http://127.0.0.1:5001");
const mcpServerDir = computed(() => appInfo.value.mcp_server_dir || "未检测到");
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
        captureMode.value = String(ac.capture_mode || "dom").trim();
        console.log("[Settings] 加载自动化配置:", {
          templates: shippingTemplates.value,
          selected: selectedShippingTemplate.value,
          materialOptions: materialOptions.value,
          materials: materialCompositions.value,
          washLabelTagImagePath: washLabelTagImagePath.value,
        });
      }
    }
  } catch (error) {
    console.error("加载设置失败:", error);
  } finally {
    loading.value = false;
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
        capture_mode: captureMode.value,
      },
    };

    if (materialSettingsInvalid.value) {
      activeTab.value = "automation";
      ElMessage.warning("材质必须来自平台选项且含量总和等于100%");
      loading.value = false;
      return;
    }

    console.log("[Settings] 保存设置:", settingsToSave);

    const response = await api.updateSettings(settingsToSave);

    if (response.success) {
      ElMessage.success("设置保存成功");
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

// 初始化设置页面
onMounted(() => {
  loadAppInfo();
  loadSettings();
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

        <!-- 模型API设置标签页 -->
        <el-tab-pane label="🤖 模型API" name="model">
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
                      @click="testModelConnection(config)"
                    >
                      测试
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
                      <el-option label="ds-free-api (DeepSeek V4 Pro)" value="ds-free-api" />
                      <el-option label="OpenAI" value="openai" />
                      <el-option label="Ollama (本地)" value="ollama" />
                      <el-option label="Azure OpenAI" value="azure" />
                      <el-option label="自定义" value="custom" />
                    </el-select>
                  </div>
                  <div class="detail-row">
                    <label>API地址</label>
                    <el-input
                      v-model="config.api_base"
                      placeholder="API Base URL"
                      size="small"
                    />
                  </div>
                  <div class="detail-row">
                    <label>API Key</label>
                    <el-input
                      v-model="config.api_key"
                      type="password"
                      placeholder="ds-free-api 填 userToken.value；本地模型可留空"
                      size="small"
                      show-password
                    />
                  </div>
                  <div class="detail-row">
                    <label>模型名称</label>
                    <el-input
                      v-model="config.model_name"
                      placeholder="如: deepseek-v4-pro, gpt-3.5-turbo, qwen2.5:7b"
                      size="small"
                    />
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
                  placeholder="配置名称"
                />
                <el-select
                  v-model="newModelConfig.provider"
                  @change="handleModelProviderChange(newModelConfig)"
                >
                  <el-option label="ds-free-api (DeepSeek V4 Pro)" value="ds-free-api" />
                  <el-option label="OpenAI" value="openai" />
                  <el-option label="Ollama (本地)" value="ollama" />
                  <el-option label="Azure OpenAI" value="azure" />
                  <el-option label="自定义" value="custom" />
                </el-select>
                <el-input
                  v-model="newModelConfig.api_base"
                  placeholder="API地址"
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
            <h3 class="section-title">📤 发布方式</h3>
            <el-radio-group v-model="publishMode">
              <el-radio value="dom">🖱️ DOM 流水线 — 模拟操作页面发布（稳定，较慢）</el-radio>
              <el-radio value="protocol">⚡ 纯协议 — API 直接调用 addWithSchema（最快，约18秒/品）</el-radio>
              <el-radio value="official">🔗 官方 API — 抖店开放平台接口（最稳定，需配置密钥）</el-radio>
            </el-radio-group>
          </div>

          <div class="settings-section">
            <h3 class="section-title">🔍 采集方式</h3>
            <el-radio-group v-model="captureMode">
              <el-radio value="dom">🖱️ DOM 采集 — 模拟浏览器访问商品页（兼容性好）</el-radio>
              <el-radio value="protocol">⚡ 协议采集 — 直接读取页面JS数据/mtop API（更快）</el-radio>
            </el-radio-group>
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
                    text
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
                    placeholder="选择平台材质"
                    filterable
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
                  placeholder="选择平台材质"
                  filterable
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
              <div class="material-total" :class="{ warning: materialSettingsInvalid }">
                当前含量总和：{{ materialPercentageTotal }}%
              </div>
              <div v-if="materialSettingsInvalid" class="material-warning-text">
                材质必须来自平台选项，且含量总和必须等于100%
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

        <el-tab-pane label="🧩 MCP / Skills" name="mcp">
          <div class="settings-section">
            <h3 class="section-title">🚀 部署前提</h3>
            <div class="deploy-guide-card">
              <ul class="deploy-guide-list">
                <li>先启动本工具，让本地后端可用，默认地址是 <code>{{ backendUrl }}</code></li>
                <li>Runtime mode: <code>{{ runtimeModeLabel }}</code></li>
                <li>Preferred MCP launch mode: <code>{{ preferredMcpModeLabel }}</code></li>
                <li>MCP directory: <code>{{ mcpServerDir }}</code></li>
                <li>MCP entry: <code>{{ mcpServerPath }}</code></li>
                <li>Skill 目录位于 <code>{{ skillPath }}</code></li>
                <li>如果客户端支持远程 MCP，优先使用 <code>streamable_http</code>；否则使用本地 <code>stdio</code></li>
              </ul>
              <p class="guide-note">{{ mcpLaunchHint }}</p>
              <p v-if="mcpExecutablePath" class="guide-note">Detected MCP executable: <code>{{ mcpExecutablePath }}</code></p>
              <p v-if="mcpAvailabilityHint" class="guide-note">{{ mcpAvailabilityHint }}</p>
            </div>
          </div>

          <div class="settings-section">
            <div class="section-header">
              <h3 class="section-title">🖥️ 本地 stdio 启动</h3>
              <el-button size="small" @click="copyGuideText(mcpStdioCommand, 'stdio 命令')">
                复制命令
              </el-button>
            </div>
            <div class="deploy-guide-card">
              <pre class="guide-code">{{ mcpStdioCommand }}</pre>
              <p class="guide-note">Use stdio for direct MCP client integration.</p>
            </div>
          </div>

          <div class="settings-section">
            <div class="section-header">
              <h3 class="section-title">🌐 Streamable HTTP 启动</h3>
              <el-button size="small" @click="copyGuideText(mcpHttpCommand, 'HTTP 命令')">
                复制命令
              </el-button>
            </div>
            <div class="deploy-guide-card">
              <pre class="guide-code">{{ mcpHttpCommand }}</pre>
              <p class="guide-note">HTTP 端点：<code>{{ mcpHttpEndpoint }}</code></p>
              <p class="guide-note">HTTP mode is mainly for local debugging. If an MCP EXE is available, prefer stdio(EXE) to avoid a Node dependency.</p>
            </div>
          </div>

          <div class="settings-section">
            <div class="section-header">
              <h3 class="section-title">⚙️ 客户端 MCP 配置示例</h3>
              <el-button size="small" @click="copyGuideText(mcpClientConfig, 'MCP 配置')">
                复制配置
              </el-button>
            </div>
            <div class="deploy-guide-card">
              <pre class="guide-code">{{ mcpClientConfig }}</pre>
              <p class="guide-note">This config is generated from the current machine's runtime paths instead of a hardcoded development path.</p>
              <p class="guide-note">将上面的 JSON 合并到支持 MCP 的客户端配置里。</p>
            </div>
          </div>

          <div class="settings-section">
            <div class="section-header">
              <h3 class="section-title">🧠 Skills 安装说明</h3>
              <el-button size="small" @click="copyGuideText(skillPath, 'Skill 路径')">
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
              <p v-if="!appInfo.skill_dir_exists" class="guide-note">Skill directory was not found in the current runtime. For installer builds, package the Skill files as resources.</p>
            </div>
          </div>

          <div class="settings-section">
            <h3 class="section-title">📘 仓库内说明文件</h3>
            <div class="deploy-guide-card">
              <p class="guide-note">MCP 详细说明：<code>{{ mcpReadmePath }}</code></p>
              <p class="guide-note">Skill 入口目录：<code>{{ skillPath }}</code></p>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
    <div class="settings-footer">
      <el-button type="primary" :loading="loading" @click="handleSave">
        保存设置
      </el-button>
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
  overflow-y: auto;
  padding: 0 20px 0 10px;
}

.settings-tabs {
  :deep(.el-tabs__header) {
    margin-bottom: 20px;
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
  color: rgba(255, 255, 255, 0.5);
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

.settings-footer {
  display: flex;
  gap: 12px;
}
</style>

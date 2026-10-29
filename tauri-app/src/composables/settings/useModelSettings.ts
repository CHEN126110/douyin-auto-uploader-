/**
 * 设置页「智能模型」的表单模型：已配置的模型厂商列表。
 *
 * 由 SettingsPanel 创建并持有，ModelTab 通过 props 拿到同一个对象就地编辑。
 * 厂商预设（地址 / 默认模型）与规范化规则也放在这里，ModelTab 和加载逻辑共用同一份。
 */
import { reactive, ref } from "vue";
import type { ModelConfig, Settings } from "@/types";

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

/** 「添加新模型」表单的初始值 */
export function createNewModelConfig(): ModelConfig {
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

/** 切换服务商时，把仍是默认值（或为空）的地址 / 模型名 / 配置名换成新厂商的预设 */
export function applyModelProviderDefaults(config: ModelConfig): void {
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

export function useModelSettings() {
  const modelConfigs = ref<ModelConfig[]>(normalizeModelConfigs([]));

  /** 用后端返回的设置覆盖表单；后端没给模型配置时也要补齐两个默认厂商。 */
  function applySettings(settings: Settings) {
    // 加载模型配置
    const apiModelConfigs = settings.model_configs ?? settings.model_apis;
    if (apiModelConfigs && Array.isArray(apiModelConfigs)) {
      modelConfigs.value = normalizeModelConfigs(apiModelConfigs);
    } else {
      modelConfigs.value = normalizeModelConfigs(modelConfigs.value);
    }
  }

  return reactive({ modelConfigs, applySettings });
}

export type ModelSettingsModel = ReturnType<typeof useModelSettings>;
